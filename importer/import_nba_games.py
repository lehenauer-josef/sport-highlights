#!/usr/bin/env python3
"""Import NBA games and highlights into Postgres.

- It syncs the NBA rows of the `teams` table from ESPN's NBA team list (matched
  on sport + ESPN team id, since ESPN ids are shared with college teams),
- fetches each game day from the ESPN scoreboard API,
- skips preseason games,
- fetches each completed game's ESPN summary (quarter scores, team stats and
  per-team stat leaders),
- searches YouTube for the best highlight video (preferring a full-length
  "GameTime Highlights" upload that names both teams),
- and upserts the result into `games` (keyed by the ESPN event id).

Without `--season` the importer processes the last `--days` days (default 17).
Use `--season` to import a whole season;
NBA seasons are identified by their end year, so `2026` (or `2025-26`) is the
2025-26 season.

The NBA has no numbered weeks, so the importer derives them as consecutive
7-day blocks (US Eastern dates) starting on the first day of the regular season.

Usage:
    pip install -r requirements.txt
    export DATABASE_URL="postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
    python import_nba_games.py
    python import_nba_games.py --days 3
    python import_nba_games.py --season 2026
    python import_nba_games.py --season 2025-26 --limit 10 --dry-run
    python import_nba_games.py --season 2026 --stats-only
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import random
import re
import ssl
import time
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import psycopg

import highlight_scorer as scorer

USER_AGENT = "nba-highlights-importer/1.0"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
ESPN_GROUPS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/groups"
ESPN_SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
STAT_COLUMNS = (
    "home_line_scores", "away_line_scores",
    "home_team_stats", "away_team_stats", "game_leaders",
)
ESPN_SEASON_TYPE_URL = (
    "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{season}/types/{type}"
)
# ESPN season types: 1 = preseason, 2 = regular season, 3 = postseason, 5 = play-in.
PRESEASON_TYPE = 1
REGULAR_SEASON_TYPE = 2
# Game days and week blocks follow the US schedule rather than UTC.
LOCAL_TZ = ZoneInfo("America/New_York")
PREFERRED_CHANNEL = "gametime highlights"

YT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
YT_SEARCH_URL = "https://www.youtube.com/results?search_query="


def ssl_context() -> ssl.SSLContext:
    # This Python install lacks CA certs; match the existing scorer scripts.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def pick(d: dict, *keys, default=None):
    if not isinstance(d, dict):
        return default
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
    # ESPN omits seconds ("2026-10-13T23:00Z"), which older Pythons reject.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+-]\d{2}:\d{2}", text):
        text = text[:16] + ":00" + text[16:]
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def local_date(dt: datetime) -> date:
    return dt.astimezone(LOCAL_TZ).date()


def parse_season(value) -> int | None:
    """Accept `2026`, `2025-26` or `2025-2026` and return ESPN's end-year season."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{4}", text):
        return int(text)
    m = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", text)
    if m:
        return int(m.group(1)) + 1
    raise SystemExit(f"Invalid --season {value!r}; use e.g. 2026 or 2025-26.")


def fetch_json(url: str):
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    ctx = ssl_context()
    for attempt in range(4):
        try:
            with urlopen(req, timeout=30, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
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


def fetch_scoreboard(day: date) -> dict | None:
    return fetch_json(f"{ESPN_SCOREBOARD_URL}?dates={day:%Y%m%d}&limit=100")


def season_calendar(season: int) -> list[date]:
    """All game days ESPN lists for a season (preseason through the Finals)."""
    # Any in-season date returns the full calendar; Jan 1 is always mid-season.
    payload = fetch_json(f"{ESPN_SCOREBOARD_URL}?dates={season}0101&limit=1")
    leagues = pick(payload or {}, "leagues", default=[])
    calendar = pick(leagues[0], "calendar", default=[]) if leagues else []
    days = set()
    for entry in calendar:
        raw = entry if isinstance(entry, str) else pick(entry, "startDate", "date")
        if isinstance(raw, str) and len(raw) >= 10:
            # Calendar entries are US dates stored as "YYYY-MM-DDT07:00Z".
            days.add(date.fromisoformat(raw[:10]))
    return sorted(days)


_season_start_cache: dict[int, date | None] = {}


def regular_season_start(season: int) -> date | None:
    if season not in _season_start_cache:
        payload = fetch_json(ESPN_SEASON_TYPE_URL.format(season=season, type=REGULAR_SEASON_TYPE))
        start = parse_dt(pick(payload or {}, "startDate"))
        # ESPN encodes the US calendar day as 07:00Z, so the UTC date is the day.
        _season_start_cache[season] = start.date() if start else None
    return _season_start_cache[season]


def nba_week_number(game_date: datetime | None, season_start: date | None) -> int | None:
    if game_date is None or season_start is None:
        return None
    week = (local_date(game_date) - season_start).days // 7 + 1
    return week if week >= 1 else None


def collect_events(days: list[date]) -> list[dict]:
    merged: dict[str, dict] = {}
    for day in days:
        payload = fetch_scoreboard(day)
        for event in pick(payload or {}, "events", default=[]) or []:
            if isinstance(event, dict) and event.get("id") is not None:
                merged[str(event["id"])] = event
    return list(merged.values())


def competitor(event: dict, side: str) -> dict:
    competitions = pick(event, "competitions", default=[]) or [{}]
    competitors = pick(competitions[0], "competitors", default=[]) or []
    for comp in competitors:
        if comp.get("homeAway") == side:
            return comp
    # ESPN lists competitors home first, away second.
    idx = 0 if side == "home" else 1
    return competitors[idx] if len(competitors) > idx else {}


def stat_number(value) -> int | float | None:
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def made_attempted(value) -> tuple[int, int] | None:
    parts = str(value or "").split("-")
    if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
        return int(parts[0]), int(parts[1])
    return None


# Team box score stat -> stored key.
TEAM_STAT_KEYS = {
    "totalRebounds": "rebounds",
    "offensiveRebounds": "offensiveRebounds",
    "assists": "assists",
    "steals": "steals",
    "blocks": "blocks",
    "totalTurnovers": "turnovers",
    "pointsInPaint": "pointsInPaint",
    "fastBreakPoints": "fastBreakPoints",
    "fouls": "fouls",
    "largestLead": "largestLead",
}
# Shooting splits ("38-89") -> (made key, attempted key, pct key, ESPN pct stat).
SHOOTING_KEYS = {
    "fieldGoalsMade-fieldGoalsAttempted": (
        "fieldGoalsMade", "fieldGoalsAttempted", "fieldGoalPct", "fieldGoalPct",
    ),
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": (
        "threePointMade", "threePointAttempted", "threePointPct", "threePointFieldGoalPct",
    ),
    "freeThrowsMade-freeThrowsAttempted": (
        "freeThrowsMade", "freeThrowsAttempted", "freeThrowPct", "freeThrowPct",
    ),
}
# Player box score leader categories: (stored key, ESPN key, detail labels).
LEADER_SPECS = (
    ("points", "points", ["FG", "3PT", "FT"]),
    ("rebounds", "rebounds", ["OREB", "DREB"]),
    ("assists", "assists", ["TO", "MIN"]),
    ("steals", "steals", ["MIN"]),
    ("blocks", "blocks", ["MIN"]),
)


def normalize_espn_stats(summary: dict) -> dict:
    """Map ESPN's NBA game summary into the shared line score/team stat/leader columns."""
    result = dict.fromkeys(STAT_COLUMNS)
    competitions = pick(pick(summary, "header", default={}), "competitions", default=[]) or []
    if not competitions:
        return result

    sides = {}
    for comp in pick(competitions[0], "competitors", default=[]) or []:
        side = comp.get("homeAway")
        if side not in ("home", "away") or comp.get("id") is None:
            continue
        sides[str(comp["id"])] = side
        scores = [
            to_int(pick(period, "displayValue", "value"))
            for period in comp.get("linescores") or []
        ]
        if scores and all(score is not None for score in scores):
            result[f"{side}_line_scores"] = scores

    boxscore = pick(summary, "boxscore", default={}) or {}
    team_stats = {"home": {}, "away": {}}
    for team in boxscore.get("teams") or []:
        side = sides.get(str(pick(team.get("team") or {}, "id")))
        if side is None:
            continue
        raw = {stat.get("name"): stat.get("displayValue") for stat in team.get("statistics") or []}
        for name, key in TEAM_STAT_KEYS.items():
            value = stat_number(raw.get(name))
            if value is not None:
                team_stats[side][key] = value
        for name, (made_key, att_key, pct_key, espn_pct) in SHOOTING_KEYS.items():
            split = made_attempted(raw.get(name))
            if split:
                team_stats[side][made_key], team_stats[side][att_key] = split
            # ESPN rounds percentages to whole numbers; recompute with one decimal.
            pct = round(split[0] / split[1] * 100, 1) if split and split[1] else stat_number(raw.get(espn_pct))
            if pct is not None:
                team_stats[side][pct_key] = pct

    leaders = {"home": {}, "away": {}}
    for team in boxscore.get("players") or []:
        side = sides.get(str(pick(team.get("team") or {}, "id")))
        if side is None:
            continue
        for category in team.get("statistics") or []:
            keys = category.get("keys") or []
            labels = category.get("labels") or []
            for target, primary, details in LEADER_SPECS:
                if primary not in keys:
                    continue
                index = keys.index(primary)
                best, best_value = None, 0
                for entry in category.get("athletes") or []:
                    values = entry.get("stats") or []
                    value = stat_number(values[index]) if index < len(values) else None
                    if value is not None and value > best_value:
                        best, best_value = entry, value
                if best is None:
                    continue
                athlete = best.get("athlete") or {}
                detail_values = dict(zip(labels, best.get("stats") or []))
                leaders[side][target] = {
                    "id": str(athlete.get("id") or ""),
                    "name": athlete.get("displayName") or athlete.get("shortName") or "",
                    "stat": best_value,
                    "statType": labels[index] if index < len(labels) else primary,
                    "detail": " · ".join(
                        f"{label} {detail_values[label]}" for label in details
                        if detail_values.get(label) not in (None, "", "--", "—")
                    ),
                }

    for side in ("home", "away"):
        if team_stats[side]:
            result[f"{side}_team_stats"] = json.dumps(team_stats[side])
    if leaders["home"] or leaders["away"]:
        result["game_leaders"] = json.dumps(leaders)
    return result


def fetch_game_stats(event_id: str) -> dict:
    try:
        summary = fetch_json(f"{ESPN_SUMMARY_URL}?event={event_id}")
        if not isinstance(summary, dict):
            raise ValueError("empty response")
        stats = normalize_espn_stats(summary)
        if not any(value is not None for value in stats.values()):
            raise ValueError("no box score or statistics in ESPN response")
        return stats
    except (SystemExit, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"    stats unavailable for {event_id}: {exc}", flush=True)
        return dict.fromkeys(STAT_COLUMNS)


def youtube_query(event: dict, away: str | None, home: str | None, game_date: datetime | None) -> str:
    base = game_date or datetime.now(timezone.utc)
    before = (base + timedelta(days=3)).date().isoformat()
    after = (base - timedelta(days=1)).date().isoformat()
    # The ESPN event name ("Away at Home") + NBA highlights.
    teams = pick(event, "name") or f"{away} at {home}"
    return f"{teams} NBA highlights before:{before} after:{after}"


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


def parse_views(text: str | None):
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def duration_to_seconds(duration: str | None) -> int:
    return scorer.parse_duration(duration) or 0


def extract_videos(html: str | None, limit: int = 10) -> list[dict]:
    if not html:
        return []
    script = next(
        (
            m.group(1)
            for m in re.finditer(r"<script\b[^>]*>([\s\S]*?)</script>", html, re.I)
            if "var ytInitialData" in m.group(1)
        ),
        None,
    )
    if not script:
        return []
    json_match = re.search(r"ytInitialData\s*=\s*(\{[\s\S]*?\})\s*;", script)
    if not json_match:
        return []
    try:
        data = json.loads(json_match.group(1))
    except json.JSONDecodeError:
        return []

    sections = (
        data.get("contents", {})
        .get("twoColumnSearchResultsRenderer", {})
        .get("primaryContents", {})
        .get("sectionListRenderer", {})
        .get("contents", [])
    )
    videos = []
    for section in sections:
        for item in section.get("itemSectionRenderer", {}).get("contents", []):
            v = item.get("videoRenderer")
            if not v or not v.get("videoId"):
                continue
            if any(
                (b.get("metadataBadgeRenderer") or {}).get("style") == "BADGE_STYLE_TYPE_LIVE_NOW"
                for b in v.get("badges") or []
            ):
                continue
            duration = (v.get("lengthText") or {}).get("simpleText")
            if not duration:
                continue
            video_id = v["videoId"]
            videos.append(
                {
                    "videoId": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "title": ((v.get("title") or {}).get("runs") or [{}])[0].get("text"),
                    "duration": duration,
                    "views": parse_views((v.get("viewCountText") or {}).get("simpleText")),
                    "channel": ((v.get("ownerText") or {}).get("runs") or [{}])[0].get("text"),
                }
            )
    return videos[:limit]


MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
TITLE_DATE_RE = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})\b",
    re.I,
)
TITLE_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b")
GAME_NUMBER_RE = re.compile(r"\bgame\s+(\d)\b", re.I)


def title_dates(title: str | None) -> set[date]:
    found = set()
    for month, day, year in TITLE_DATE_RE.findall(title or ""):
        try:
            found.add(date(int(year), MONTHS[month.lower()], int(day)))
        except ValueError:
            pass
    for month, day, year in TITLE_NUMERIC_DATE_RE.findall(title or ""):
        try:
            found.add(date(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day)))
        except ValueError:
            pass
    return found


def series_game_number(event: dict) -> int | None:
    competitions = pick(event, "competitions", default=[]) or [{}]
    for note in pick(competitions[0], "notes", default=[]) or []:
        m = GAME_NUMBER_RE.search(pick(note, "headline", default=""))
        if m:
            return int(m.group(1))
    return None


def is_other_game(title: str | None, game_day: date | None, game_number: int | None) -> bool:
    """True when the title names a different date or playoff game than ours.

    The search window spans several days, so back-to-back meetings and playoff
    series often return highlights for the wrong game between the same teams.
    """
    dates = title_dates(title)
    if game_day and dates and game_day not in dates:
        return True
    m = GAME_NUMBER_RE.search(title or "")
    return bool(game_number and m and int(m.group(1)) != game_number)


def names_team(norm_title: str, *names: str | None) -> bool:
    return any(n and scorer.normalize_text(n) in norm_title for n in names)


def title_names_both(title, home, away, home_mascot=None, away_mascot=None) -> bool:
    # ESPN says "LA Clippers" while titles say "Los Angeles Clippers", so the
    # nickname is accepted too (NBA nicknames are unique).
    norm = scorer.normalize_text(title or "")
    return bool(norm) and names_team(norm, home, home_mascot) and names_team(norm, away, away_mascot)


def preferred_video(videos, home, away, home_mascot=None, away_mascot=None, game_day=None) -> dict | None:
    """First choice: a >5 min GameTime Highlights video naming both teams."""
    candidates = [
        v
        for v in videos
        if PREFERRED_CHANNEL in (v.get("channel") or "").lower()
        and duration_to_seconds(v.get("duration")) > 5 * 60
        and title_names_both(v.get("title"), home, away, home_mascot, away_mascot)
    ]
    # Prefer the upload whose title carries this game's date.
    candidates.sort(key=lambda v: game_day not in title_dates(v.get("title")))
    return candidates[0] if candidates else None


def scorer_safe(videos: list[dict]) -> list[dict]:
    # The shared scorer rejects titles containing "basketball" (meant to filter
    # out other college sports); that word is expected in NBA titles.
    out = []
    for v in videos:
        title = re.sub(r"basketball", "", v.get("title") or "", flags=re.I)
        out.append({**v, "title": " ".join(title.split())})
    return out


def score_candidates(home, away, videos, home_mascot=None, away_mascot=None, limit: int = 3):
    scored = []
    for item in scorer_safe(videos):
        candidate = {
            "video_id": item["videoId"],
            "title": item.get("title") or "",
            "channel": item.get("channel") or "",
            "views": item.get("views"),
            "duration_seconds": scorer.parse_duration(item.get("duration")),
        }
        candidate["score"] = scorer.candidate_score(candidate, home, away, home_mascot, away_mascot)
        scored.append(candidate)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def choose_highlight(
    event: dict,
    home: str | None,
    away: str | None,
    game_date: datetime | None,
    home_mascot: str | None = None,
    away_mascot: str | None = None,
):
    if not (home and away):
        return None, None, []
    search_url = YT_SEARCH_URL + quote_plus(youtube_query(event, away, home, game_date))
    game_day = local_date(game_date) if game_date else None
    game_number = series_game_number(event)
    try:
        videos = extract_videos(fetch_youtube_html(search_url), limit=10)
        candidates = [v for v in videos if not is_other_game(v.get("title"), game_day, game_number)]
        preferred = preferred_video(candidates, home, away, home_mascot, away_mascot, game_day)
        if preferred:
            return preferred["videoId"], search_url, videos
        dated = [v for v in candidates if game_day in title_dates(v.get("title"))]
        best = None
        for pool in (dated, candidates):
            best = scorer.find_best_video(home, away, scorer_safe(pool), home_mascot, away_mascot)
            if best:
                break
    except Exception as exc:  # network/parse errors shouldn't abort the run
        print(f"    highlight search error: {exc}", flush=True)
        return None, search_url, []
    return (best.get("video_id") if best else None), search_url, videos


def download_image(url: str | None) -> tuple[str | None, str | None]:
    """Fetch an image and return (base64 str, mime) for storing logos in the DB."""
    if not url:
        return None, None
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=30, context=ssl_context()) as resp:
            data = resp.read()
            mime = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
        return base64.b64encode(data).decode("ascii"), mime or "image/png"
    except (HTTPError, URLError, TimeoutError, OSError):
        return None, None


def rename_team_in_games(cur, team_id: int, old_name: str, new_name: str) -> int:
    """Replace a team's name inside the stored game names ("Away (W-L) - Home (W-L)").

    Only games involving this NBA team are touched, and only the exact
    "<name> (" form, so "Arizona" never matches inside "Arizona State".
    """
    cur.execute(
        "UPDATE games SET name = replace(name, %s, %s) "
        "WHERE (home_team_id = %s OR away_team_id = %s) AND strpos(name, %s) > 0",
        (old_name + " (", new_name + " (", team_id, team_id, old_name + " ("),
    )
    return cur.rowcount


def ensure_team_identity(conn) -> None:
    """Teams are identified by sport + external id, never by external id alone.

    ESPN ids are only unique within a league (12 is both the LA Clippers and
    Arizona), so the unique key includes conference_type.
    """
    with conn.cursor() as cur:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS teams_conference_type_external_id_key "
            "ON teams (conference_type, external_id)"
        )
    conn.commit()


def fetch_nba_teams() -> list[dict]:
    """NBA teams from ESPN with their conference name attached."""
    data = fetch_json(ESPN_TEAMS_URL)
    leagues = pick(pick(data, "sports", default=[{}])[0], "leagues", default=[{}])
    teams = [
        t["team"]
        for t in pick(leagues[0], "teams", default=[]) or []
        if pick(pick(t, "team", default={}), "id") is not None
    ]
    conference_by_team: dict[str, str] = {}
    for conference in pick(fetch_json(ESPN_GROUPS_URL), "groups", default=[]) or []:
        for division in pick(conference, "children", default=[]) or []:
            for team in pick(division, "teams", default=[]) or []:
                conference_by_team[str(team.get("id"))] = conference.get("name")
    for team in teams:
        team["conference"] = conference_by_team.get(str(team["id"]))
    return teams


def sync_nba_teams(conn, dry_run: bool = False) -> int:
    """Keep the NBA rows of `teams` in sync with ESPN's NBA team list.

    NBA team data is owned by this importer: rows are matched on
    (conference_type = 'NBA', external_id) and their name, mascot, conference,
    color and logo come from ESPN's NBA endpoint, so data of another sport's team
    with the same id can't end up on an NBA row. Other sports are never touched.
    """
    try:
        espn_teams = fetch_nba_teams()
    except Exception as exc:  # keep importing games with the stored teams
        print(f"Warning: could not load NBA teams from ESPN ({exc}); skipping team sync.", flush=True)
        return 0
    if not espn_teams:
        print("Warning: ESPN returned no NBA teams; skipping team sync.", flush=True)
        return 0

    if not dry_run:
        ensure_team_identity(conn)

    changed = 0
    with conn.cursor() as cur:
        cur.execute(
            "SELECT external_id, id, name, mascot, conference, color, logo_url, "
            "logo_data IS NOT NULL, conference_logo_data IS NOT NULL "
            "FROM teams WHERE conference_type = 'NBA'"
        )
        stored = {str(row[0]).strip(): row[1:] for row in cur.fetchall() if row[0]}
        cur.execute(
            "SELECT DISTINCT ON (conference) conference, conference_logo_url, "
            "conference_logo_data, conference_logo_mime FROM teams "
            "WHERE conference_type = 'NBA' AND conference_logo_data IS NOT NULL "
            "ORDER BY conference, id"
        )
        conference_logos = {row[0]: row[1:] for row in cur.fetchall()}

        for team in espn_teams:
            ext = str(team["id"])
            logo_url = pick((pick(team, "logos", default=[]) or [{}])[0], "href")
            values = {
                "name": team.get("displayName"),
                "mascot": team.get("name"),
                "conference": team.get("conference"),
                "color": team.get("color"),
                "logo_url": logo_url,
            }
            current = stored.get(ext)
            if current:
                tid, *fields, has_logo, has_conf_logo = current
                if (
                    dict(zip(values, fields)) == values
                    and has_logo
                    and (has_conf_logo or values["conference"] not in conference_logos)
                ):
                    continue
                old_name = fields[0]
            else:
                tid = old_name = None

            changed += 1
            action = "Updating" if current else "Adding"
            rename = f" ({old_name!r} -> {values['name']!r})" if old_name and old_name != values["name"] else ""
            print(
                f"  {action} NBA team {values['name']} (ESPN {ext}){rename}" + (" [dry-run]" if dry_run else ""),
                flush=True,
            )
            if dry_run:
                continue

            logo_changed = not current or fields[4] != logo_url or not has_logo
            logo_data, logo_mime = download_image(logo_url) if logo_changed else (None, None)
            conf_url, conf_data, conf_mime = conference_logos.get(values["conference"], (None, None, None))
            params = {**values, "ext": ext, "logo_data": logo_data, "logo_mime": logo_mime,
                      "conf_url": conf_url, "conf_data": conf_data, "conf_mime": conf_mime}
            if current:
                cur.execute(
                    "UPDATE teams SET name = %(name)s, mascot = %(mascot)s, conference = %(conference)s, "
                    "color = %(color)s, logo_url = %(logo_url)s, "
                    "logo_data = COALESCE(%(logo_data)s, logo_data), logo_mime = COALESCE(%(logo_mime)s, logo_mime), "
                    "conference_logo_url = COALESCE(%(conf_url)s, conference_logo_url), "
                    "conference_logo_data = COALESCE(%(conf_data)s, conference_logo_data), "
                    "conference_logo_mime = COALESCE(%(conf_mime)s, conference_logo_mime), "
                    "synced_at = NOW() "
                    "WHERE conference_type = 'NBA' AND external_id = %(ext)s",
                    params,
                )
                if rename:
                    rename_team_in_games(cur, tid, old_name, values["name"])
            else:
                cur.execute(
                    "INSERT INTO teams (source_id, external_id, name, mascot, conference, conference_type, "
                    "color, logo_url, logo_data, logo_mime, conference_logo_url, conference_logo_data, "
                    "conference_logo_mime) VALUES ('espn:nba:' || %(ext)s, %(ext)s, %(name)s, %(mascot)s, "
                    "%(conference)s, 'NBA', %(color)s, %(logo_url)s, %(logo_data)s, %(logo_mime)s, "
                    "%(conf_url)s, %(conf_data)s, %(conf_mime)s) "
                    "ON CONFLICT (conference_type, external_id) DO NOTHING",
                    params,
                )
    if not dry_run:
        conn.commit()
    return changed


def load_team_map(conn) -> dict[str, int]:
    """ESPN team id -> teams.id for NBA teams in the local `teams` table."""
    by_ext: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT id, external_id FROM teams WHERE conference_type = 'NBA' ORDER BY id")
        for tid, ext in cur.fetchall():
            if ext:
                by_ext.setdefault(str(ext).strip(), tid)
    return by_ext


def build_row(
    event: dict,
    home_id: int | None,
    away_id: int | None,
    home_name: str | None,
    away_name: str | None,
    video_id: str | None,
):
    event_id = str(event["id"])
    game_date = parse_dt(pick(event, "date"))
    season = pick(event, "season", default={})
    season_year = to_int(pick(season, "year"))
    competitions = pick(event, "competitions", default=[]) or [{}]
    comp = competitions[0]
    status = pick(comp, "status", default={}) or pick(event, "status", default={})
    period = to_int(pick(status, "period")) or 0
    week = nba_week_number(game_date, regular_season_start(season_year)) if season_year else None

    return {
        "source_id": f"nba:{event_id}",
        "external_id": event_id,
        "name": pick(event, "name") or (f"{away_name} at {home_name}" if home_name and away_name else None),
        "season": str(season_year) if season_year else None,
        "week": week,
        # Everything after the regular season (incl. play-in) is postseason.
        "type": "regular" if to_int(pick(season, "type")) == REGULAR_SEASON_TYPE else "postseason",
        "game_date": game_date,
        "location": pick(pick(comp, "venue", default={}), "fullName"),
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_points": to_int(pick(competitor(event, "home"), "score")),
        "away_points": to_int(pick(competitor(event, "away"), "score")),
        "overtime": period > 4,
        "thumbnail_url": None,
        "video_id": video_id,
        "highlights_valid": bool(video_id),
        "highlights_checked": False,
        "better_video_id": None,
        "reason": None,
        "review_status": "pending",
        "modified": None,
        **dict.fromkeys(STAT_COLUMNS),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import NBA games, ESPN stats, and YouTube highlights into Postgres.",
    )
    parser.add_argument(
        "--season",
        default=None,
        help="Whole season to import, by end year (e.g. 2026 or 2025-26). Omit to import the last --days days.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=17,
        help="Without --season: how many days back from today to import (default: 17).",
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
        help="Also import games that have not finished yet.",
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
        help="Backfill ESPN stats for existing games without changing highlights or other game data.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and score but do not write to Postgres.",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL is not set. Export the Postgres (Neon) connection string first.")
    now = datetime.now(timezone.utc)
    today = local_date(now)
    season = parse_season(args.season)

    if season:
        days = season_calendar(season)
        if not args.include_future:
            days = [d for d in days if d <= today]
        print(f"Season {season - 1}-{str(season)[2:]}: {len(days)} game day(s) to fetch.", flush=True)
    else:
        days = [today - timedelta(days=offset) for offset in range(max(args.days, 0) + 1)]
        days.reverse()
        print(f"Fetching {len(days)} day(s): {days[0]} to {days[-1]}.", flush=True)

    events = collect_events(days)
    if season:
        events = [e for e in events if to_int(pick(pick(e, "season", default={}), "year")) == season]
    events.sort(key=lambda e: (parse_dt(pick(e, "date")) or now, str(e["id"])))
    print(f"{len(events)} unique game(s) found.", flush=True)

    inserted = updated = skipped_future = skipped_preseason = skipped_teams = 0
    highlights_found = no_highlight_examples = 0

    with psycopg.connect(db_url) as conn:
        by_ext: dict[str, int] = {}
        if not args.stats_only:
            synced = sync_nba_teams(conn, dry_run=args.dry_run)
            if synced:
                print(f"Synced {synced} NBA team(s) from ESPN.", flush=True)
            by_ext = load_team_map(conn)
            print(f"Loaded {len(by_ext)} NBA teams from Postgres.", flush=True)
            if not by_ext:
                raise SystemExit("No NBA teams found in the teams table (conference_type = 'NBA').")

        for event in events:
            event_id = str(event["id"])
            game_date = parse_dt(pick(event, "date"))
            season_info = pick(event, "season", default={})
            if to_int(pick(season_info, "type")) == PRESEASON_TYPE:
                skipped_preseason += 1
                continue

            competitions = pick(event, "competitions", default=[]) or [{}]
            status = pick(competitions[0], "status", default={}) or pick(event, "status", default={})
            completed = bool(pick(pick(status, "type", default={}), "completed", default=False))
            is_future = (game_date and game_date > now) or not completed
            if is_future and not args.include_future:
                skipped_future += 1
                continue

            if args.stats_only:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM games WHERE external_id = %s OR source_id = %s ORDER BY id LIMIT 1",
                        (event_id, f"nba:{event_id}"),
                    )
                    existing = cur.fetchone()
                    if existing is None:
                        continue
                    stats = fetch_game_stats(event_id) if completed else dict.fromkeys(STAT_COLUMNS)
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

            home, away = competitor(event, "home"), competitor(event, "away")
            home_team, away_team = pick(home, "team", default={}), pick(away, "team", default={})
            home_id = by_ext.get(str(pick(home_team, "id") or pick(home, "id") or ""))
            away_id = by_ext.get(str(pick(away_team, "id") or pick(away, "id") or ""))
            home_name = pick(home_team, "displayName")
            away_name = pick(away_team, "displayName")
            if home_id is None or away_id is None:
                # e.g. All-Star games or teams missing from the teams table.
                skipped_teams += 1
                print(f"    - skipping {pick(event, 'name') or event_id}: team not in teams table", flush=True)
                continue
            home_mascot = pick(home_team, "name")
            away_mascot = pick(away_team, "name")

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, video_id, highlights_checked FROM games "
                    "WHERE external_id = %s OR source_id = %s ORDER BY id LIMIT 1",
                    (event_id, f"nba:{event_id}"),
                )
                existing = cur.fetchone()

            video_id = existing[1] if existing else None
            checked = bool(existing[2]) if existing else False

            do_search = not args.no_highlights and not is_future
            if do_search and checked and not args.force_highlights:
                do_search = False

            found = None
            if do_search:
                found, search_url, videos = choose_highlight(
                    event, home_name, away_name, game_date, home_mascot, away_mascot
                )
                time.sleep(random.uniform(0.8, 1.8))  # be polite to YouTube
                if found:
                    video_id = found
                    highlights_found += 1
                    print(f"    ✓ {away_name} at {home_name}: {found}", flush=True)
                else:
                    found = None
                    if no_highlight_examples < 5:
                        no_highlight_examples += 1
                        print(
                            f"    · no highlight picked for {away_name} at {home_name}\n"
                            f"      search: {search_url}",
                            flush=True,
                        )
                        for idx, cand in enumerate(
                            score_candidates(home_name, away_name, videos, home_mascot, away_mascot), start=1
                        ):
                            print(
                                f"        {idx}. score={cand['score']} | {cand['title']} | {cand['channel']} "
                                f"| {cand['duration_seconds']}s | {cand['video_id']}",
                                flush=True,
                            )

            row = build_row(event, home_id, away_id, home_name, away_name, video_id)
            if completed:
                row.update(fetch_game_stats(event_id))

            if args.dry_run:
                inserted += 0 if existing else 1
                updated += 1 if existing else 0
            elif existing:
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
                    "home_line_scores = COALESCE(%s, home_line_scores)",
                    "away_line_scores = COALESCE(%s, away_line_scores)",
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
                    *(row[column] for column in STAT_COLUMNS),
                ]
                # Keep the existing video when the search comes up empty.
                if found:
                    sets += ["video_id = %s", "highlights_valid = %s"]
                    vals += [found, True]
                    if checked:
                        # --force-highlights replaced a reviewed pick; send it back to review.
                        sets += ["highlights_checked = %s", "review_status = %s"]
                        vals += [False, "pending"]
                vals.append(existing[0])
                with conn.cursor() as cur:
                    cur.execute(f"UPDATE games SET {', '.join(sets)} WHERE id = %s", vals)
                updated += 1
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO games (
                            source_id, external_id, name, season, week, type, game_date,
                            location, home_team_id, away_team_id, home_points, away_points,
                            overtime, thumbnail_url, video_id, highlights_valid,
                            highlights_checked, better_video_id, reason, review_status,
                            modified, home_line_scores, away_line_scores, home_team_stats,
                            away_team_stats, game_leaders
                        ) VALUES (
                            %(source_id)s, %(external_id)s, %(name)s, %(season)s, %(week)s,
                            %(type)s, %(game_date)s, %(location)s, %(home_team_id)s,
                            %(away_team_id)s, %(home_points)s, %(away_points)s, %(overtime)s,
                            %(thumbnail_url)s, %(video_id)s, %(highlights_valid)s,
                            %(highlights_checked)s, %(better_video_id)s, %(reason)s,
                            %(review_status)s, %(modified)s, %(home_line_scores)s,
                            %(away_line_scores)s, %(home_team_stats)s, %(away_team_stats)s,
                            %(game_leaders)s
                        )
                        """,
                        row,
                    )
                inserted += 1

            if not args.dry_run and (inserted + updated) % 20 == 0:
                conn.commit()

            if args.limit and (inserted + updated) >= args.limit:
                break

        if not args.dry_run:
            conn.commit()

    print(
        f"\nDone. Inserted {inserted}, updated {updated} games "
        f"({highlights_found} highlights found, {skipped_future} future/incomplete, "
        f"{skipped_preseason} preseason, {skipped_teams} unknown-team games skipped)."
        + (" [dry-run]" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()
