#!/usr/bin/env python3
"""Import NHL games and highlights into Postgres.

This script mirrors the attached N8N workflows in a standalone Python importer:

- it loads NHL teams from the local `teams` table,
- fetches each team's season schedule from the NHL API,
- deduplicates games across teams,
- skips preseason games,
- searches YouTube for the best highlight video,
- fetches each completed game's story (goals, three stars, team stats),
- and upserts the result into `games`.

Use `--season` to import a historical season such as `20232024` or `20222023`.
If `--season` is omitted, the importer uses the live `/now` endpoint, matching
the main workflow.

Usage:
    pip install -r requirements.txt
    export DATABASE_URL=postgres://cfb:cfb@localhost:5433/highlights
    python import_nhl_games.py
    python import_nhl_games.py --season 20232024
    python import_nhl_games.py --season 20222023 --limit 10
    python import_nhl_games.py --season 20232024 --dry-run
    python import_nhl_games.py --season 20232024 --stats-only
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import n8n_find_highlight as scorer  # noqa: E402

DEFAULT_DB_URL = "postgres://cfb:cfb@localhost:5433/highlights"
USER_AGENT = "nhl-highlights-importer/1.0"
GAME_STORY_URL = "https://api-web.nhle.com/v1/wsc/game-story/{game_id}"
STAT_COLUMNS = ("home_team_stats", "away_team_stats", "game_leaders")

YT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
YT_SEARCH_URL = "https://www.youtube.com/results?search_query="
YT_DATA_RE = re.compile(r"ytInitialData\s*=\s*(\{.+?\})\s*;\s*</script>", re.S)


def ssl_context() -> ssl.SSLContext:
    # This Python install lacks CA certs; match the existing scorer scripts.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def pick(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_dt(value):
    if not value or not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_name(value: str | None) -> str | None:
    if not value:
        return None
    return scorer.normalize_text(str(value))


def current_nhl_season(now: datetime) -> str:
    start_year = now.year if now.month >= 7 else now.year - 1
    return f"{start_year}{start_year + 1}"


def normalize_nhl_season(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{8}", text):
        return text[:4]
    if re.fullmatch(r"\d{4}-\d{4}", text):
        return text.split("-")[0]
    if re.fullmatch(r"\d{4}", text):
        return text
    return text


def fetch_json(url: str, *, headers: dict[str, str] | None = None):
    req = Request(url, headers=headers or {"User-Agent": USER_AGENT})
    ctx = ssl_context()
    for attempt in range(4):
        try:
            with urlopen(req, timeout=30, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            body = exc.read().decode("utf-8", errors="ignore")[:300]
            raise SystemExit(f"GET {url} returned {exc.code}: {body}")
        except URLError:
            if attempt < 3:
                time.sleep(1 + attempt)
                continue
            return None
    return None


def fetch_youtube_html(url: str) -> str | None:
    req = Request(
        url,
        headers={
            "User-Agent": YT_UA,
            "Accept-Language": "en-US,en;q=0.9",
            # Skip the EU consent interstitial so we get real results markup.
            "Cookie": "CONSENT=YES+1",
        },
    )
    ctx = ssl_context()
    for attempt in range(3):
        try:
            with urlopen(req, timeout=30, context=ctx) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                time.sleep(2 + attempt)
                continue
            return None
        except URLError:
            if attempt < 2:
                time.sleep(1 + attempt)
                continue
            return None
    return None


def _runs_text(value):
    if not isinstance(value, dict):
        return None
    runs = value.get("runs")
    if runs:
        return runs[0].get("text")
    return value.get("simpleText")


def _view_text(value):
    if not isinstance(value, dict):
        return None
    if value.get("simpleText"):
        return value["simpleText"]
    runs = value.get("runs")
    if runs:
        return "".join(r.get("text", "") for r in runs)
    return None


def _is_live(vr):
    for badge in vr.get("badges") or []:
        style = (badge.get("metadataBadgeRenderer") or {}).get("style")
        if style == "BADGE_STYLE_TYPE_LIVE_NOW":
            return True
    return False


def parse_views(text: str | None):
    if not text:
        return None
    s = text.lower().replace("views", "").strip()
    s = s.replace(",", "")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([mk])?", s)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    suffix = (m.group(2) or "").lower()
    if suffix == "m":
        num *= 1_000_000
    elif suffix == "k":
        num *= 1_000
    return int(round(num))

def duration_to_seconds(duration: str | None) -> int:
    if not duration:
        return 0
    parts = duration.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return 0


def build_video_list(html: str | None, limit: int = 10) -> list[dict]:
    let_html = html
    if not let_html:
        return []

    script_match = [m.group(1) for m in re.finditer(r"<script\b[^>]*>([\s\S]*?)</script>", let_html, re.I)]
    script_match = [code for code in script_match if "var ytInitialData" in code]
    if not script_match:
        let_html = None
        return []

    script = script_match[0]
    let_html = None

    json_match = re.search(r"ytInitialData\s*=\s*(\{[\s\S]*?\})\s*;", script)
    if not json_match:
        script = None
        return []

    raw_json = json_match.group(1)
    script = None

    try:
        yt_initial_data = json.loads(raw_json)
    except json.JSONDecodeError:
        raw_json = None
        return []

    raw_json = None

    data = yt_initial_data
    if not data:
        return []

    sections = (
        data.get("contents", {})
        .get("twoColumnSearchResultsRenderer", {})
        .get("primaryContents", {})
        .get("sectionListRenderer", {})
        .get("contents", [])
    )

    video_renderers = [
        item.get("videoRenderer")
        for section in sections
        for item in section.get("itemSectionRenderer", {}).get("contents", [])
        if item.get("videoRenderer")
    ]

    videos = []
    for v in video_renderers:
        if v.get("badges") and any(
            (b.get("metadataBadgeRenderer") or {}).get("style") == "BADGE_STYLE_TYPE_LIVE_NOW"
            for b in v.get("badges") or []
        ):
            continue
        if not v.get("lengthText", {}).get("simpleText"):
            continue
        video_id = v.get("videoId") or None
        if not video_id:
            continue
        videos.append(
            {
                "videoId": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": v.get("title", {}).get("runs", [{}])[0].get("text"),
                "duration": v.get("lengthText", {}).get("simpleText"),
                "views": parse_views(v.get("viewCountText", {}).get("simpleText")),
                "channel": v.get("ownerText", {}).get("runs", [{}])[0].get("text"),
            }
        )

    videos = videos[:limit]
    sportsnet = next(
        (
            v
            for v in videos
            if v.get("channel")
            and "sportsnet" in v["channel"].lower()
            and duration_to_seconds(v.get("duration")) > 5 * 60
        ),
        None,
    )
    return [sportsnet] if sportsnet else videos


def search_youtube(query: str, limit: int = 10) -> list[dict]:
    html = fetch_youtube_html(YT_SEARCH_URL + quote_plus(query))
    return build_video_list(html, limit=limit)


def score_candidates(home: str, away: str, videos: list[dict], home_mascot=None, away_mascot=None, limit: int = 3):
    scored = []
    for item in videos or []:
        vid = item.get("videoId") or item.get("video_id")
        if not vid:
            continue
        candidate = {
            "video_id": vid,
            "url": item.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "title": item.get("title") or "",
            "channel": item.get("channel") or "",
            "views": item.get("views"),
            "duration_seconds": scorer.parse_duration(item.get("duration")),
        }
        candidate["score"] = scorer.candidate_score(candidate, home, away, home_mascot, away_mascot)
        scored.append(candidate)
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return scored[:limit]


def choose_highlight(
    home: str,
    away: str,
    game_date: datetime | None,
    home_mascot: str | None = None,
    away_mascot: str | None = None,
):
    if not (home and away):
        return None, None, []
    try:
        base = game_date or datetime.now(timezone.utc)
        before = (base + timedelta(days=3)).date().isoformat()
        after = (base - timedelta(days=1)).date().isoformat()
        # This matches the N8N search window and order.
        # Match the attached N8N workflow: away vs home + NHL highlights.
        query = f"{away} vs {home} NHL highlights before:{before} after:{after}"
        search_url = YT_SEARCH_URL + quote_plus(query)
        videos = search_youtube(query, limit=10)
        best = scorer.find_best_video(home, away, videos, home_mascot, away_mascot)
    except Exception as exc:  # network/parse errors shouldn't abort the run
        print(f"    highlight search error: {exc}", flush=True)
        return None, None, []
    return (best.get("video_id") if best else None), search_url, videos


def load_team_maps(conn):
    """Build NHL team lookups from the local `teams` table."""
    by_ext: dict[str, int] = {}
    by_name: dict[str, int] = {}
    name_by_id: dict[int, str | None] = {}
    mascot_by_id: dict[int, str | None] = {}
    team_codes: list[str] = []

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, external_id, name, mascot FROM teams "
            "WHERE conference_type = 'NHL'"
        )
        for tid, ext, name, mascot in cur.fetchall():
            name_by_id[tid] = name
            mascot_by_id[tid] = mascot
            if ext:
                code = str(ext).strip().upper()
                by_ext.setdefault(code, tid)
                team_codes.append(code)
            if name:
                by_name.setdefault(normalize_name(name), tid)
            if mascot:
                by_name.setdefault(normalize_name(mascot), tid)

    # Keep the schedule fetch list stable and avoid duplicate requests.
    team_codes = sorted({code for code in team_codes if code})
    return team_codes, by_ext, by_name, name_by_id, mascot_by_id


def team_label(team: dict | None, fallback: str | None = None) -> str | None:
    if isinstance(team, dict):
        place = pick(team, "placeName", default={})
        common = pick(team, "commonName", default={})
        place_name = pick(place, "default") if isinstance(place, dict) else None
        common_name = pick(common, "default") if isinstance(common, dict) else None
        parts = [str(p).strip() for p in (place_name, common_name) if p]
        if parts:
            return " ".join(parts)
        abbrev = pick(team, "abbrev")
        if abbrev:
            return str(abbrev)
    if fallback:
        return fallback
    return None


def build_search_url(home, away, game_date):
    base = game_date or datetime.now(timezone.utc)
    before = (base + timedelta(days=3)).date().isoformat()
    after = (base - timedelta(days=1)).date().isoformat()
    query = f"{away} vs {home} NHL highlights before:{before} after:{after}"
    return YT_SEARCH_URL + quote_plus(query)


def resolve_team(game: dict, side: str, by_ext, by_name):
    team = pick(game, f"{side}Team", f"{side}_team")
    code = pick(team or {}, "abbrev") if isinstance(team, dict) else None
    if code and str(code).upper() in by_ext:
        return by_ext[str(code).upper()]

    if code is not None and str(code).upper() in by_ext:
        return by_ext[str(code).upper()]

    # Fallback: resolve by the team display name if the abbreviation lookup fails.
    name = team_label(team)
    if name:
        return by_name.get(normalize_name(name))
    return None


def fetch_schedule(team_code: str, season: str | None):
    if season:
        url = f"https://api-web.nhle.com/v1/club-schedule-season/{team_code}/{season}"
    else:
        url = f"https://api-web.nhle.com/v1/club-schedule-season/{team_code}/now"
    return fetch_json(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})


def collect_games(team_codes: list[str], season: str | None):
    merged: dict[str, dict] = {}
    for code in team_codes:
        payload = fetch_schedule(code, season)
        games = []
        if isinstance(payload, dict):
            games = payload.get("games") or []
        if not isinstance(games, list):
            continue
        for game in games:
            if not isinstance(game, dict):
                continue
            gid = pick(game, "id")
            if gid is None:
                continue
            merged[str(gid)] = game
    return list(merged.values())


def _text(value):
    if isinstance(value, dict):
        value = value.get("default")
    return str(value).strip() if value not in (None, "") else None


def _number(value, scale: float = 1, digits: int = 1):
    try:
        number = float(value) * scale
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    number = round(number, digits)
    return int(number) if number.is_integer() else number


def normalize_game_story(story: dict) -> dict:
    """Map the NHL game story into the shared stats columns.

    Team stats go into home/away_team_stats; goals by period, the shootout and
    the three stars go into game_leaders (the UI renders that shape for NHL).
    """
    result = dict.fromkeys(STAT_COLUMNS)
    summary = story.get("summary") if isinstance(story, dict) else None
    if not isinstance(summary, dict):
        return result

    home_abbrev = _text((story.get("homeTeam") or {}).get("abbrev"))
    season = _text(story.get("season"))

    def headshot(player_id, team):
        if player_id and team and season:
            return f"https://assets.nhle.com/mugs/nhl/{season}/{team}/{player_id}.png"
        return None

    def is_home(raw, team):
        return raw if isinstance(raw, bool) else (team is not None and team == home_abbrev)

    full_names: dict[str, str] = {}

    def person(raw: dict, team, total_key):
        player_id = str(raw.get("playerId") or "") or None
        first, last = _text(raw.get("firstName")), _text(raw.get("lastName"))
        name = " ".join(p for p in (first, last) if p) or _text(raw.get("name")) or ""
        if player_id and first and last:
            full_names[player_id] = name
        return {
            "id": player_id,
            "name": name,
            "headshot": raw.get("headshot") or headshot(player_id, team),
            "total": to_int(raw.get(total_key)),
        }

    periods = []
    for period in summary.get("scoring") or []:
        descriptor = period.get("periodDescriptor") or {}
        period_type = descriptor.get("periodType")
        # The shootout "goal" is only the deciding marker; attempts come from `shootout`.
        if period_type == "SO":
            continue
        goals = []
        for goal in period.get("goals") or []:
            team = _text(goal.get("teamAbbrev"))
            modifier = goal.get("goalModifier")
            goals.append({
                "time": goal.get("timeInPeriod"),
                "strength": goal.get("strength"),
                "modifier": modifier if modifier and modifier != "none" else None,
                "shotType": goal.get("shotType"),
                "team": team,
                "isHome": is_home(goal.get("isHome"), team),
                "homeScore": to_int(goal.get("homeScore")),
                "awayScore": to_int(goal.get("awayScore")),
                "scorer": person(goal, team, "goalsToDate"),
                "assists": [person(a, team, "assistsToDate") for a in goal.get("assists") or []],
                "clipUrl": goal.get("highlightClipSharingUrl"),
            })
        periods.append({
            "number": to_int(descriptor.get("number")),
            "type": period_type,
            "goals": goals,
        })

    shootout = []
    for attempt in summary.get("shootout") or []:
        team = _text(attempt.get("teamAbbrev"))
        shooter = person(attempt, team, "goals")
        shootout.append({
            "sequence": to_int(attempt.get("sequence")),
            "team": team,
            "isHome": is_home(None, team),
            "id": shooter["id"],
            "name": shooter["name"],
            "headshot": shooter["headshot"],
            "result": attempt.get("result"),
            "gameWinner": bool(attempt.get("gameWinner")),
        })

    stars = []
    for star in summary.get("threeStars") or []:
        team = _text(star.get("teamAbbrev"))
        player_id = str(star.get("playerId") or "") or None
        entry = {
            "star": to_int(star.get("star")),
            "id": player_id,
            "name": full_names.get(player_id or "") or _text(star.get("name")) or "",
            "headshot": star.get("headshot") or headshot(player_id, team),
            "team": team,
            "isHome": is_home(None, team),
            "position": star.get("position"),
            "sweaterNo": to_int(star.get("sweaterNo")),
            "goals": to_int(star.get("goals")),
            "assists": to_int(star.get("assists")),
            "points": to_int(star.get("points")),
            "savePct": _number(star.get("savePctg"), digits=3),
            "gaa": _number(star.get("goalsAgainstAverage"), digits=2),
        }
        stars.append({k: v for k, v in entry.items() if v is not None})
    stars.sort(key=lambda s: s.get("star") or 99)

    team_stats = {"home": {}, "away": {}}
    keys = {
        "sog": ("shotsOnGoal", 1),
        "faceoffWinningPctg": ("faceoffPct", 100),
        "powerPlayPctg": ("powerPlayPct", 100),
        "pim": ("pim", 1),
        "hits": ("hits", 1),
        "blockedShots": ("blockedShots", 1),
        "giveaways": ("giveaways", 1),
        "takeaways": ("takeaways", 1),
    }
    for stat in summary.get("teamGameStats") or []:
        category = stat.get("category")
        for side in ("home", "away"):
            raw = stat.get(f"{side}Value")
            if category == "powerPlay":
                parts = str(raw or "").split("/")
                if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                    team_stats[side]["powerPlayGoals"] = int(parts[0])
                    team_stats[side]["powerPlayOpportunities"] = int(parts[1])
            elif category in keys:
                key, scale = keys[category]
                value = _number(raw, scale)
                if value is not None:
                    team_stats[side][key] = value

    for side in ("home", "away"):
        if team_stats[side]:
            result[f"{side}_team_stats"] = json.dumps(team_stats[side])
    if periods or shootout or stars:
        result["game_leaders"] = json.dumps({
            "sport": "NHL",
            "homeTeam": home_abbrev,
            "awayTeam": _text((story.get("awayTeam") or {}).get("abbrev")),
            "periods": periods,
            "shootout": shootout,
            "threeStars": stars,
        })
    return result


def fetch_game_stats(game_id: str) -> dict:
    try:
        story = fetch_json(GAME_STORY_URL.format(game_id=game_id), headers={
            "User-Agent": USER_AGENT, "Accept": "application/json",
        })
        stats = normalize_game_story(story) if isinstance(story, dict) else dict.fromkeys(STAT_COLUMNS)
    except (SystemExit, ValueError, TypeError, AttributeError) as exc:
        print(f"    stats unavailable for {game_id}: {exc}", flush=True)
        return dict.fromkeys(STAT_COLUMNS)
    if not any(stats.values()):
        print(f"    stats unavailable for {game_id}: empty game story", flush=True)
    return stats


def nhl_week_number(game_date: datetime | None, season_start: datetime | None) -> int | None:
    if game_date is None or season_start is None:
        return None
    return (game_date.date() - season_start.date()).days // 7 + 1


def build_row(
    game: dict,
    season_label: str,
    season_start: datetime | None,
    home_id: int | None,
    away_id: int | None,
    video_id: str | None,
    home_name: str | None,
    away_name: str | None,
):
    game_id = str(pick(game, "id"))
    game_date = parse_dt(pick(game, "startTimeUTC", "startTime"))
    period = pick(game, "periodDescriptor", default={})
    period_type = pick(period, "periodType") if isinstance(period, dict) else None
    game_type = to_int(pick(game, "gameType"))

    return {
        "airtable_id": f"nhl:{game_id}",
        "external_id": game_id,
        "name": f"{away_name} at {home_name}" if home_name and away_name else None,
        "season": normalize_nhl_season(season_label),
        "week": nhl_week_number(game_date, season_start),
        "type": "regular" if game_type == 2 else "postseason",
        "game_date": game_date,
        "location": pick(pick(game, "venue", default={}), "default"),
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_points": to_int(pick(pick(game, "homeTeam", default={}), "score")),
        "away_points": to_int(pick(pick(game, "awayTeam", default={}), "score")),
        "overtime": bool(period_type and period_type != "REG"),
        "thumbnail_url": None,
        "video_id": video_id,
        "highlights_valid": bool(video_id),
        "highlights_checked": False,
        "better_video_id": None,
        "reason": None,
        "review_status": "pending",
        "modified": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import NHL games and highlights from the NHL API into Postgres.",
    )
    parser.add_argument(
        "--season",
        default=None,
        help="Season to import in YYYYYYYY format (e.g. 20232024). Omit to use /now.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after importing N games (testing).",
    )
    parser.add_argument(
        "--include-future",
        action="store_true",
        help="Also import games that have not started yet.",
    )
    parser.add_argument(
        "--no-highlights",
        action="store_true",
        help="Skip the YouTube highlight search entirely.",
    )
    parser.add_argument(
        "--force-highlights",
        action="store_true",
        help="Re-run the highlight search even for games that already have a reviewed highlight.",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Backfill game stats for existing games without changing highlights or other game data.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and score but do not write to Postgres.",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    now = datetime.now(timezone.utc)

    use_now_endpoint = args.season in (None, "", "now", "current")
    season_label = current_nhl_season(now) if use_now_endpoint else str(args.season).strip()
    normalized_season = normalize_nhl_season(season_label)
    print(
        f"Season {season_label}{' (now)' if use_now_endpoint else ''} -> storing season {normalized_season}",
        flush=True,
    )

    with psycopg.connect(db_url) as conn:
        team_codes, by_ext, by_name, name_by_id, mascot_by_id = load_team_maps(conn)
        print(f"Loaded {len(team_codes)} NHL teams from Postgres.", flush=True)

        if not team_codes:
            raise SystemExit("No NHL teams found in the teams table (conference_type = 'NHL').")

        games = collect_games(team_codes, None if use_now_endpoint else season_label)
        print(
            f"Season {season_label}{' (now)' if use_now_endpoint else ''}: {len(games)} unique games queued.",
            flush=True,
        )

        # Sort chronologically so re-runs are deterministic and inserts happen in order.
        games.sort(
            key=lambda g: (
                parse_dt(pick(g, "startTimeUTC", "startTime")) or now,
                str(pick(g, "id") or ""),
            )
        )
        season_start = min(
            (
                game_date
                for game in games
                if to_int(pick(game, "gameType")) == 2
                and (game_date := parse_dt(pick(game, "startTimeUTC", "startTime")))
            ),
            default=None,
        )

        inserted = updated = skipped_future = highlights_found = 0
        no_highlight_examples = 0

        for game in games:
            game_date = parse_dt(pick(game, "startTimeUTC", "startTime"))
            game_state = str(pick(game, "gameState", default="")).upper()
            completed = game_state in {"OFF", "FINAL"}
            is_future = (game_date and game_date > now) or not completed
            if is_future and not args.include_future:
                skipped_future += 1
                continue

            if to_int(pick(game, "gameType")) == 1:
                continue

            if args.stats_only:
                game_id = str(pick(game, "id"))
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM games WHERE external_id = %s", (game_id,))
                    existing = cur.fetchone()
                    if existing is None:
                        continue
                    stats = fetch_game_stats(game_id)
                    if not args.dry_run:
                        cur.execute(
                            "UPDATE games SET "
                            + ", ".join(f"{column} = COALESCE(%s, {column})" for column in STAT_COLUMNS)
                            + " WHERE id = %s",
                            [stats[column] for column in STAT_COLUMNS] + [existing[0]],
                        )
                updated += 1
                if not args.dry_run and updated % 20 == 0:
                    conn.commit()
                if args.limit and updated >= args.limit:
                    break
                continue

            home_id = resolve_team(game, "home", by_ext, by_name)
            away_id = resolve_team(game, "away", by_ext, by_name)
            home_team = pick(game, "homeTeam", default={})
            away_team = pick(game, "awayTeam", default={})
            home_name = team_label(home_team) or name_by_id.get(home_id) or str(pick(home_team, "abbrev") or "") or None
            away_name = team_label(away_team) or name_by_id.get(away_id) or str(pick(away_team, "abbrev") or "") or None
            home_mascot = mascot_by_id.get(home_id)
            away_mascot = mascot_by_id.get(away_id)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, video_id, highlights_valid, highlights_checked "
                    "FROM games WHERE external_id = %s",
                    (str(pick(game, "id")),),
                )
                existing = cur.fetchone()

            video_id = existing[1] if existing else None
            highlights_valid = bool(existing[2]) if existing else False
            checked = bool(existing[3]) if existing else False

            do_search = not args.no_highlights
            if do_search and not args.force_highlights and checked:
                do_search = False
            if do_search and is_future:
                do_search = False

            if do_search:
                found, search_url, videos = choose_highlight(
                    home_name,
                    away_name,
                    game_date,
                    home_mascot,
                    away_mascot,
                )
                time.sleep(random.uniform(0.8, 1.8))  # be polite to YouTube
                if found:
                    video_id = found
                    highlights_valid = True
                    highlights_found += 1
                    print(f"    ✓ {away_name} at {home_name}: {found}", flush=True)
                elif no_highlight_examples < 5:
                    no_highlight_examples += 1
                    top = score_candidates(
                        home_name,
                        away_name,
                        videos,
                        home_mascot,
                        away_mascot,
                        limit=3,
                    )
                    print(
                        f"    · no highlight picked for {away_name} at {home_name}\n"
                        f"      search: {search_url}",
                        flush=True,
                    )
                    for idx, cand in enumerate(top, start=1):
                        print(
                            f"        {idx}. score={cand['score']} | {cand['title']} | {cand['channel']} | {cand['duration_seconds']}s | {cand['video_id']}",
                            flush=True,
                        )

            row = build_row(
                game,
                season_label,
                season_start,
                home_id,
                away_id,
                video_id,
                home_name,
                away_name,
            )
            row.update(fetch_game_stats(str(pick(game, "id"))) if completed else dict.fromkeys(STAT_COLUMNS))
            # Preserve manually reviewed rows when no new search result is chosen.
            if do_search or not existing:
                row["highlights_valid"] = bool(video_id)
                row["highlights_checked"] = False
                row["review_status"] = "pending"

            if args.dry_run:
                inserted += 0 if existing else 1
                updated += 1 if existing else 0
                if args.limit and (inserted + updated) >= args.limit:
                    break
                continue

            if existing:
                sets = [
                    "name = %s",
                    "season = %s",
                    "week = %s",
                    "type = %s",
                    "game_date = %s",
                    "location = %s",
                    "home_team_id = %s",
                    "away_team_id = %s",
                    "home_points = %s",
                    "away_points = %s",
                    "overtime = %s",
                    "home_team_stats = COALESCE(%s, home_team_stats)",
                    "away_team_stats = COALESCE(%s, away_team_stats)",
                    "game_leaders = COALESCE(%s, game_leaders)",
                    "synced_at = NOW()",
                ]
                vals = [
                    row["name"],
                    row["season"],
                    row["week"],
                    row["type"],
                    row["game_date"],
                    row["location"],
                    row["home_team_id"],
                    row["away_team_id"],
                    row["home_points"],
                    row["away_points"],
                    row["overtime"],
                    row["home_team_stats"],
                    row["away_team_stats"],
                    row["game_leaders"],
                ]
                if do_search and not checked:
                    sets += ["video_id = %s", "highlights_valid = %s"]
                    vals += [video_id, bool(video_id)]
                vals.append(existing[0])
                with conn.cursor() as cur:
                    cur.execute(f"UPDATE games SET {', '.join(sets)} WHERE id = %s", vals)
                updated += 1
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO games (
                            airtable_id, external_id, name, season, week, type, game_date,
                            location, home_team_id, away_team_id, home_points, away_points,
                            overtime, thumbnail_url, video_id, highlights_valid,
                            highlights_checked, better_video_id, reason, review_status,
                            modified, home_team_stats, away_team_stats, game_leaders
                        ) VALUES (
                            %(airtable_id)s, %(external_id)s, %(name)s, %(season)s, %(week)s,
                            %(type)s, %(game_date)s, %(location)s, %(home_team_id)s,
                            %(away_team_id)s, %(home_points)s, %(away_points)s, %(overtime)s,
                            %(thumbnail_url)s, %(video_id)s, %(highlights_valid)s,
                            %(highlights_checked)s, %(better_video_id)s, %(reason)s,
                            %(review_status)s, %(modified)s, %(home_team_stats)s,
                            %(away_team_stats)s, %(game_leaders)s
                        )
                        """,
                        row,
                    )
                inserted += 1

            if (inserted + updated) % 20 == 0:
                conn.commit()

            if args.limit and (inserted + updated) >= args.limit:
                break

        if not args.dry_run:
            conn.commit()

    print(
        f"\nDone. Inserted {inserted}, updated {updated} games "
        f"({highlights_found} highlights found, {skipped_future} future/incomplete games skipped)."
        + (" [dry-run]" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()