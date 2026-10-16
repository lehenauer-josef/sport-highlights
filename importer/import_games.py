#!/usr/bin/env python3
"""Import College Football games straight from the collegefootballdata.com API
into Postgres.

Fetches the CFD calendar + games, searches YouTube for each game's best
highlight, and writes games (and the highlight it finds) directly to the
`games` table.

Teams are expected to already exist in the `teams` table; games link to them by
CFD team id (external_id) with a normalized-name fallback. Games are keyed on
external_id (the CFD game id), so re-runs update existing rows in place.

Highlights are ranked by the shared scorer in `highlight_scorer.py`.

Usage:
    pip install -r requirements.txt
    export CFBD_API_KEY=...        # or create importer/.cfbd_key / .cfbd_key
    export DATABASE_URL="postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
    python import_games.py --season 2026            # all started weeks
    python import_games.py --season 2026 --week 3   # a single week
    python import_games.py --season 2026 --limit 10 # cap games (testing)
    python import_games.py --season 2026 --no-highlights   # skip YouTube
    python import_games.py --season 2026 --dry-run  # don't write to Postgres
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import ssl
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

import psycopg

import highlight_scorer as scorer
from records import apply_pregame_records

CFBD_BASE = "https://api.collegefootballdata.com"
USER_AGENT = "cfb-highlights-importer/1.0"

# Browser-like UA so YouTube serves the real results markup.
YT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
YT_SEARCH_URL = "https://www.youtube.com/results?search_query="
YT_DATA_RE = re.compile(r"ytInitialData\s*=\s*(\{.+?\})\s*;\s*</script>", re.S)

# CFD classifications to pull; the teams table already scopes FBS/FCS.
CLASSIFICATIONS = ["fbs", "fcs"]


def get_cfbd_key() -> str:
    val = os.environ.get("CFBD_API_KEY")
    if val:
        return val.strip()
    for path in (
        os.path.join(os.path.dirname(__file__), ".cfbd_key"),
        os.path.join(os.path.dirname(__file__), "..", ".cfbd_key"),
    ):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
    raise SystemExit("Set CFBD_API_KEY or create a .cfbd_key file.")


def ssl_context() -> ssl.SSLContext:
    # This Python install lacks CA certs; match the existing scorer scripts.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def cfbd_get(path: str, key: str, **params):
    """GET a collegefootballdata.com endpoint, returning parsed JSON (or [])."""
    url = f"{CFBD_BASE}/{path}?{urlencode(params)}"
    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
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
            raise SystemExit(f"CFD {path} returned {exc.code}: {body}")
        except URLError:
            if attempt < 3:
                time.sleep(1 + attempt)
                continue
            raise
    return []


def pick(d: dict, *keys, default=None):
    """First present, non-empty value among camelCase/snake_case key variants."""
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
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


def fetch_weeks(key: str, season: int, now: datetime):
    """Return [(season_type, week)] for weeks that have already started."""
    try:
        calendar = cfbd_get("calendar", key, year=season)
    except SystemExit as exc:
        print(f"  calendar fetch failed ({exc}); using weeks 1-16.", flush=True)
        calendar = []
    weeks = []
    for w in calendar or []:
        start = parse_dt(pick(w, "firstGameStart", "startDate"))
        if start and start > now:
            continue  # a future week can't have highlights yet
        season_type = pick(w, "seasonType", "season_type", default="regular")
        week = to_int(pick(w, "week"))
        if week is not None:
            weeks.append((season_type, week))
    if not weeks:
        weeks = [("regular", n) for n in range(1, 17)] + [("postseason", 1)]
    return weeks + extra_postseason_weeks(key, season, now, weeks)


def extra_postseason_weeks(key: str, season: int, now: datetime, known: list):
    """Postseason weeks with started games that the CFD calendar doesn't list.

    Some seasons (e.g. 2023) list the early FCS playoff rounds as postseason
    weeks 13-15 while the calendar only has postseason week 1, so those games
    would never be fetched week by week.
    """
    have = {week for season_type, week in known if season_type == "postseason"}
    extra = set()
    for classification in CLASSIFICATIONS:
        try:
            rows = cfbd_get("games", key, year=season, seasonType="postseason",
                            classification=classification)
        except SystemExit as exc:
            print(f"  postseason week lookup failed ({exc}).", flush=True)
            continue
        for game in rows or []:
            week = to_int(pick(game, "week"))
            start = parse_dt(pick(game, "startDate", "start_date"))
            if week is not None and week not in have and start and start <= now:
                extra.add(week)
    if extra:
        print(f"  postseason weeks missing from the calendar: {sorted(extra)}", flush=True)
    return [("postseason", week) for week in sorted(extra)]


def fetch_games(key: str, season: int, season_type: str, week: int):
    """Fetch FBS + FCS games for a week, deduped by CFD game id."""
    merged: dict = {}
    for classification in CLASSIFICATIONS:
        rows = cfbd_get(
            "games",
            key,
            year=season,
            week=week,
            seasonType=season_type,
            classification=classification,
        )
        for g in rows or []:
            gid = pick(g, "id")
            if gid is not None:
                merged[gid] = g
    return list(merged.values())


def normalize_hex_color(value):
    if value in (None, ""):
        return None
    color = str(value).strip()
    if not color:
        return None
    if color.startswith("#"):
        color = color[1:]
    color = color.lower()
    if len(color) == 3 and all(c in "0123456789abcdef" for c in color):
        color = "".join([c * 2 for c in color])
    if len(color) != 6 or not all(c in "0123456789abcdef" for c in color):
        return None
    return f"#{color}"


def fetch_team_colors(key: str):
    rows_out: list[tuple[str | None, str | None, str]] = []
    for classification in CLASSIFICATIONS:
        rows = cfbd_get("teams", key, classification=classification)
        for team in rows or []:
            if not isinstance(team, dict):
                continue
            color = normalize_hex_color(pick(team, "color"))
            if not color:
                continue
            ext = pick(team, "id", "schoolId", "teamId")
            school = pick(team, "school", "name", "team")
            norm_name = scorer.normalize_text(str(school)) if school else None
            rows_out.append((str(ext) if ext is not None else None, norm_name, color))
    return rows_out


def apply_team_colors(conn, team_colors):
    if not team_colors:
        return 0

    by_ext: dict[str, int] = {}
    by_name: dict[str, int] = {}
    current_by_id: dict[int, str | None] = {}

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, external_id, name, color FROM teams "
            "WHERE conference_type IS NULL "
            "OR conference_type NOT IN ('NFL', 'NHL', 'NBA', 'Soccer')"
        )
        for tid, ext, name, color in cur.fetchall():
            current_by_id[tid] = normalize_hex_color(color)
            if ext:
                by_ext[str(ext)] = tid
            if name:
                by_name[scorer.normalize_text(str(name))] = tid

    updates: list[tuple[str, int]] = []
    touched_ids: set[int] = set()

    for ext, norm_name, color in team_colors:
        team_id = by_ext.get(ext) if ext else None
        if team_id is None and norm_name:
            team_id = by_name.get(norm_name)
        if team_id is None or team_id in touched_ids:
            continue
        if current_by_id.get(team_id) == color:
            continue
        updates.append((color, team_id))
        touched_ids.add(team_id)

    if not updates:
        return 0

    with conn.cursor() as cur:
        cur.executemany("UPDATE teams SET color = %s WHERE id = %s", updates)

    return len(updates)


def load_team_maps(conn):
    """Build CFD-id -> team_id, normalized-name -> team_id, and team_id -> mascot
    maps from the teams table (read-only; teams are never modified). Only college
    football teams are considered; pro/soccer leagues are excluded so their
    external_ids/names don't collide with college teams (e.g. ESPN id 23 is both
    San Jose State and the NBA's Sacramento Kings)."""
    by_ext: dict[str, int] = {}
    by_name: dict[str, int] = {}
    mascot_by_id: dict[int, str | None] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, external_id, name, mascot FROM teams "
            "WHERE conference_type IS NULL "
            "OR conference_type NOT IN ('NFL', 'NHL', 'NBA', 'Soccer')"
        )
        for tid, ext, name, mascot in cur.fetchall():
            mascot_by_id[tid] = mascot
            if ext:
                by_ext[str(ext)] = tid
            if name:
                by_name[scorer.normalize_text(name)] = tid
    return by_ext, by_name, mascot_by_id


def resolve_team(game: dict, side: str, by_ext, by_name):
    tid = pick(game, f"{side}Id", f"{side}_id")
    if tid is not None and str(tid) in by_ext:
        return by_ext[str(tid)]
    name = pick(game, f"{side}Team", f"{side}_team")
    if name:
        return by_name.get(scorer.normalize_text(name))
    return None


def to_int_list(value):
    if value in (None, ""):
        return None
    if isinstance(value, list):
        return [to_int(v) for v in value]
    if isinstance(value, tuple):
        return [to_int(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [to_int(v) for v in parsed]
        except json.JSONDecodeError:
            pass
    return None


FCS_PLAYOFF_ROUNDS = (
    ("first round", "fcs-first-round"),
    ("second round", "fcs-second-round"),
    ("quarterfinal", "fcs-quarterfinal"),
    ("semifinal", "fcs-semifinal"),
)


def fcs_playoff_round(notes: str) -> str | None:
    """FCS bracket round from CFD notes ("FCS Championship - First Round", ...).

    CFD lists the early FCS rounds as regular-season games, so this is checked
    regardless of the game's seasonType.
    """
    if "fcs championship" not in notes and "division i football championship" not in notes:
        return None
    for needle, key in FCS_PLAYOFF_ROUNDS:
        if needle in notes:
            return key
    return "fcs-championship"


def cfb_postseason_round(game: dict) -> str | None:
    """Postseason round key from the CFD game notes; non-playoff games are bowls."""
    notes = str(pick(game, "notes", default="") or "").lower()
    fcs_round = fcs_playoff_round(notes)
    if fcs_round:
        return fcs_round
    if pick(game, "seasonType", "season_type", default="regular") != "postseason":
        return None
    if "college football playoff" in notes or re.search(r"\bcfp\b", notes):
        if "first round" in notes:
            return "cfp-first-round"
        if "quarterfinal" in notes:
            return "cfp-quarterfinal"
        if "semifinal" in notes:
            return "cfp-semifinal"
        if "championship" in notes:
            return "cfp-championship"
    # Bowls between two FCS teams (e.g. the Celebration Bowl) belong to FCS.
    home = str(pick(game, "homeClassification", "home_classification", default="") or "")
    away = str(pick(game, "awayClassification", "away_classification", default="") or "")
    if home.lower() == "fcs" and away.lower() == "fcs":
        return "fcs-bowl"
    return "bowl"


def game_row(game: dict) -> dict:
    home = pick(game, "homeTeam", "home_team")
    away = pick(game, "awayTeam", "away_team")
    postseason_round = cfb_postseason_round(game)
    return {
        "external_id": str(pick(game, "id")),
        "name": f"{away} at {home}" if home and away else None,
        "season": str(pick(game, "season", default="")) or None,
        "week": to_int(pick(game, "week")),
        # FCS playoff rounds come back as regular-season games; store every
        # bracket game as postseason.
        "type": "postseason"
        if postseason_round
        else pick(game, "seasonType", "season_type", default="regular"),
        "postseason_round": postseason_round,
        "location": pick(game, "venue"),
        "home_points": to_int(pick(game, "homePoints", "home_points")),
        "away_points": to_int(pick(game, "awayPoints", "away_points")),
        "home_line_scores": to_int_list(pick(game, "homeLineScores", "home_line_scores")),
        "away_line_scores": to_int_list(pick(game, "awayLineScores", "away_line_scores")),
        "excitement_index": to_float(pick(game, "excitementIndex", "excitement_index")),
        "home_rank": None,
        "away_rank": None,
        "home_record": None,
        "away_record": None,
    }


INSERT_SQL = """
INSERT INTO games (
    source_id, external_id, name, season, week, type, postseason_round, game_date, location,
    home_team_id, away_team_id, home_points, away_points, home_line_scores,
    away_line_scores, home_team_stats, away_team_stats, game_leaders, home_rank, away_rank,
    home_record, away_record,
    excitement_index, video_id, highlight_score, highlights_valid, highlights_checked,
    review_status
) VALUES (
    %(source_id)s, %(external_id)s, %(name)s, %(season)s, %(week)s, %(type)s,
    %(postseason_round)s,
    %(game_date)s, %(location)s, %(home_team_id)s, %(away_team_id)s,
    %(home_points)s, %(away_points)s, %(home_line_scores)s, %(away_line_scores)s,
    %(home_team_stats)s, %(away_team_stats)s, %(game_leaders)s, %(home_rank)s, %(away_rank)s,
    %(home_record)s, %(away_record)s,
    %(excitement_index)s, %(video_id)s, %(highlight_score)s, %(highlights_valid)s, FALSE,
    'pending'
)
"""


def fetch_youtube_html(url):
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


def _add_video(vr, out, seen):
    vid = vr.get("videoId")
    if not vid or vid in seen or _is_live(vr):
        return
    length = vr.get("lengthText")
    duration = length.get("simpleText") if isinstance(length, dict) else None
    if not duration:
        return  # a real highlight reel always reports a duration
    seen.add(vid)
    out.append(
        {
            "videoId": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": _runs_text(vr.get("title")),
            "channel": _runs_text(vr.get("ownerText"))
            or _runs_text(vr.get("longBylineText")),
            "views": _view_text(vr.get("viewCountText"))
            or _view_text(vr.get("shortViewCountText")),
            "duration": duration,
        }
    )


def search_youtube(query, limit=20):
    """Scrape a YouTube search page into the {videoId,title,channel,views,duration}
    shape the highlight scorer expects. Skips live streams and results without a
    duration."""
    html = fetch_youtube_html(YT_SEARCH_URL + quote_plus(query))
    if not html:
        return []
    match = YT_DATA_RE.search(html)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    out: list[dict] = []
    seen: set[str] = set()

    def walk(node):
        if len(out) >= limit:
            return
        if isinstance(node, dict):
            vr = node.get("videoRenderer")
            if isinstance(vr, dict):
                _add_video(vr, out, seen)
            for value in node.values():
                if len(out) >= limit:
                    return
                walk(value)
        elif isinstance(node, list):
            for value in node:
                if len(out) >= limit:
                    return
                walk(value)

    walk(data)
    return out[:limit]


def build_query(home, away, game_date):
    """Mirror the app's search formula: away vs home + sport + highlights,
    windowed to the days around the game (before: +10d, after: -1d)."""
    base = game_date or datetime.now(timezone.utc)
    before = (base + timedelta(days=10)).date().isoformat()
    after = (base - timedelta(days=1)).date().isoformat()
    return (
        f"{away} vs {home} College Football highlights "
        f"before:{before} after:{after}"
    )


def find_highlight(home, away, game_date, home_mascot, away_mascot):
    """Search YouTube, then score the results with the highlight scorer.
    Returns (video_id, score) of the best match, or (None, None)."""
    if not (home and away):
        return None, None
    try:
        videos = search_youtube(build_query(home, away, game_date), limit=20)
        best = scorer.find_best_video(home, away, videos, home_mascot, away_mascot)
    except Exception as exc:  # network/parse errors shouldn't abort the run
        print(f"    highlight search error: {exc}", flush=True)
        return None, None
    if not best:
        return None, None
    return best.get("video_id"), best.get("score")


def fetch_rankings(key: str, season: int, season_type: str, week: int | None = None):
    """Fetch this week's ranking snapshot and return normalized-name -> rank."""
    params = {"year": season, "seasonType": season_type}
    if week is not None:
        params["week"] = week
    try:
        rows = cfbd_get("rankings", key, **params)
    except SystemExit:
        return {}

    if not rows:
        return {}

    ranking_by_name: dict[str, int] = {}
    for entry in rows:
        if not isinstance(entry, dict):
            continue

        # CFBD returns a single object like {season, week, polls:[{poll, ranks:[...]}]}.
        if isinstance(entry.get("polls"), list):
            for poll in entry["polls"]:
                if not isinstance(poll, dict):
                    continue
                for item in poll.get("ranks") or []:
                    if not isinstance(item, dict):
                        continue
                    rank = to_int(pick(item, "rank", "ranking"))
                    if rank is None:
                        continue
                    team_name = pick(item, "school", "team", "schoolName", "teamName", "name")
                    if not team_name:
                        continue
                    ranking_by_name[scorer.normalize_text(str(team_name))] = rank
            continue

        candidates = []
        if isinstance(entry.get("ranks"), list):
            candidates = entry["ranks"]
        elif isinstance(entry.get("rankings"), list):
            candidates = entry["rankings"]
        elif "rank" in entry and any(key in entry for key in ("school", "team", "schoolName", "teamName", "name")):
            candidates = [entry]
        else:
            continue

        for item in candidates:
            if not isinstance(item, dict):
                continue
            rank = to_int(pick(item, "rank", "ranking"))
            if rank is None:
                continue
            team_name = pick(item, "school", "team", "schoolName", "teamName", "name")
            if not team_name:
                continue
            ranking_by_name[scorer.normalize_text(str(team_name))] = rank

    return ranking_by_name


def build_team_rank_map(by_name: dict[str, int], rankings: dict[str, int]) -> dict[int, int]:
    """Map team ids in the DB to their ranking for the week."""
    team_rank_map: dict[int, int] = {}
    for team_key, team_id in by_name.items():
        rank = rankings.get(team_key)
        if rank is not None:
            team_rank_map[team_id] = rank
    return team_rank_map


def coerce_stat_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if isinstance(value, int) else float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if "." in text:
                return float(text)
            return int(text)
        except ValueError:
            return None
    return None


def normalize_team_stats(team_row):
    if not isinstance(team_row, dict):
        return {}

    stats = team_row.get("stats") or []
    if not isinstance(stats, list):
        return {}

    result: dict[str, int | float | None] = {}
    for item in stats:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").strip()
        if not category:
            continue
        value = coerce_stat_value(item.get("stat"))
        if value is None:
            continue

        key = {
            "netPassingYards": "passingYards",
            "passingYards": "passingYards",
            "passYards": "passingYards",
            "rushingYards": "rushingYards",
            "rushYards": "rushingYards",
            "totalYards": "totalYards",
            "tackles": "tackles",
            "sacks": "sacks",
            "interceptions": "interceptions",
            "fumblesLost": "fumbles",
            "fumbles": "fumbles",
            "totalFumbles": "fumbles",
        }.get(category)
        if key is None:
            continue
        result[key] = value

    return {
        "passingYards": result.get("passingYards"),
        "rushingYards": result.get("rushingYards"),
        "totalYards": result.get("totalYards"),
        "tackles": result.get("tackles"),
        "sacks": result.get("sacks"),
        "interceptions": result.get("interceptions"),
        "fumbles": result.get("fumbles"),
    }


def fetch_team_stats(key: str, season: int, season_type: str, week: int | None):
    params = {"year": season, "seasonType": season_type}
    if week is not None:
        params["week"] = week
    rows = cfbd_get("games/teams", key, **params)
    by_game: dict[str, dict[str, dict[str, int | float | None]]] = {}

    for game_entry in rows or []:
        if not isinstance(game_entry, dict):
            continue
        game_id = pick(game_entry, "id", "gameId", "game_id")
        if game_id is None:
            continue
        for side in game_entry.get("teams") or []:
            if not isinstance(side, dict):
                continue
            team_id = pick(side, "teamId", "schoolId", "team_id")
            stats = normalize_team_stats(side)
            if not stats:
                continue
            game_map = by_game.setdefault(str(game_id), {})
            home_away = str(side.get("homeAway") or "").lower()
            if home_away in {"home", "away"}:
                game_map[home_away] = stats
            if team_id is not None:
                game_map[str(team_id)] = stats
            team_name = pick(side, "team", "school", "name", "teamName")
            if team_name:
                game_map[scorer.normalize_text(str(team_name))] = stats

    return by_game


def fetch_game_leaders(key: str, season: int, season_type: str, week: int | None):
    """Fetch player game leaders from /games/players endpoint."""
    params = {"year": season, "seasonType": season_type}
    if week is not None:
        params["week"] = week

    # Category -> (target key, primary stat type, supporting detail stat types)
    leader_specs = {
        "passing": ("passingYards", "YDS", ["C/ATT", "TD", "INT"]),
        "rushing": ("rushingYards", "YDS", ["CAR", "TD"]),
        "receiving": ("receivingYards", "YDS", ["REC", "TD"]),
        "defensive_tackles": ("tackles", "TOT", ["SOLO"]),
        "defensive_sacks": ("sacks", "SACKS", []),
        "interceptions": ("interceptions", "INT", ["YDS", "TD"]),
    }

    def to_num(raw):
        if raw is None:
            return None
        s = str(raw).strip()
        if not s or s == "—":
            return None
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return None

    def make_leader(category_obj, spec):
        key_name, primary_type, detail_types = spec
        type_maps: dict[str, dict[str, str]] = {}

        for type_obj in category_obj.get("types") or []:
            if not isinstance(type_obj, dict):
                continue
            tname = str(type_obj.get("name") or "").strip().upper()
            if not tname:
                continue
            athletes = type_obj.get("athletes") or []
            if not isinstance(athletes, list):
                continue
            bucket: dict[str, str] = {}
            for athlete in athletes:
                if not isinstance(athlete, dict):
                    continue
                aid = str(athlete.get("id") or "")
                aname = str(athlete.get("name") or "")
                if not aid and not aname:
                    continue
                ident = aid or aname
                bucket[ident] = str(athlete.get("stat") or "").strip()
            type_maps[tname] = bucket

        primary = type_maps.get(primary_type)
        if not primary:
            return key_name, None

        best_id = None
        best_name = ""
        best_raw = ""
        best_val = -1.0

        for type_obj in category_obj.get("types") or []:
            if not isinstance(type_obj, dict):
                continue
            tname = str(type_obj.get("name") or "").strip().upper()
            if tname != primary_type:
                continue
            for athlete in type_obj.get("athletes") or []:
                if not isinstance(athlete, dict):
                    continue
                aid = str(athlete.get("id") or "")
                aname = str(athlete.get("name") or "")
                ident = aid or aname
                raw = str(athlete.get("stat") or "").strip()
                val = to_num(raw)
                if val is None:
                    continue
                if val > best_val:
                    best_val = val
                    best_id = ident
                    best_name = aname
                    best_raw = raw

        if best_id is None or best_val <= 0:
            return key_name, None

        detail_parts = []
        for t in detail_types:
            raw = type_maps.get(t, {}).get(best_id)
            if raw and raw != "—":
                detail_parts.append(f"{t} {raw}")

        leader = {
            "id": best_id,
            "name": best_name,
            "stat": int(best_val) if best_val.is_integer() else best_val,
            "statType": primary_type,
            "detail": " · ".join(detail_parts),
        }
        return key_name, leader

    by_game: dict[str, dict] = {}

    # Fetch all player data without category filtering
    rows = cfbd_get("games/players", key, **params)

    for game_entry in rows or []:
        if not isinstance(game_entry, dict):
            continue
        game_id = pick(game_entry, "id", "gameId", "game_id")
        if game_id is None:
            continue

        game_map = by_game.setdefault(str(game_id), {"home": {}, "away": {}})

        for side in game_entry.get("teams") or []:
            if not isinstance(side, dict):
                continue

            home_away = str(side.get("homeAway") or "").lower()
            if home_away not in {"home", "away"}:
                continue

            side_map = game_map[home_away]

            for category_obj in side.get("categories") or []:
                if not isinstance(category_obj, dict):
                    continue

                category_name = str(category_obj.get("name") or "").strip().lower()

                if category_name in {"passing", "rushing", "receiving", "interceptions"}:
                    key_name, leader = make_leader(category_obj, leader_specs[category_name])
                    if leader:
                        side_map[key_name] = leader
                    continue

                if category_name == "defensive":
                    for defensive_spec in ("defensive_tackles", "defensive_sacks"):
                        key_name, leader = make_leader(
                            category_obj,
                            leader_specs[defensive_spec],
                        )
                        if leader:
                            side_map[key_name] = leader

    return by_game


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import CFB games (and highlights) from the CFD API into Postgres.",
    )
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year,
                        help="Season/year to import (default: current year).")
    parser.add_argument("--week", type=int, default=None,
                        help="Only this week (skips the calendar lookup).")
    parser.add_argument("--season-type", default="regular",
                        help="Season type for --week (default: regular).")
    parser.add_argument("--no-backfill", action="store_true",
                        help="With --week, import only that week (disable regular-season 1..N backfill).")
    parser.add_argument("--recent-weeks", type=int, default=None,
                        help="Without --week, import only the N most recent started weeks.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after importing N games (testing).")
    parser.add_argument("--no-highlights", action="store_true",
                        help="Skip the YouTube highlight search entirely.")
    parser.add_argument("--force-highlights", action="store_true",
                        help="Re-run the highlight search even for games that "
                             "already have a valid or manually-checked video.")
    parser.add_argument("--include-future", action="store_true",
                        help="Also import games that have not started yet.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and score but do not write to Postgres.")
    args = parser.parse_args()

    key = get_cfbd_key()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL is not set. Export the Postgres (Neon) connection string first.")
    now = datetime.now(timezone.utc)

    if args.week is not None:
        if (not args.no_backfill) and args.season_type == "regular" and args.week > 1:
            weeks = [(args.season_type, w) for w in range(1, args.week + 1)]
        else:
            weeks = [(args.season_type, args.week)]
    else:
        weeks = fetch_weeks(key, args.season, now)
        if args.recent_weeks:
            weeks = weeks[-args.recent_weeks:]
    print(f"Season {args.season}: {len(weeks)} week(s) to import.", flush=True)

    inserted = updated = skipped_future = highlights_found = 0

    with psycopg.connect(db_url) as conn:
        team_colors = fetch_team_colors(key)
        colors_updated = apply_team_colors(conn, team_colors)
        if colors_updated:
            print(f"Updated colors for {colors_updated} teams.", flush=True)

        by_ext, by_name, mascot_by_id = load_team_maps(conn)
        print(f"Loaded {len(by_ext)} teams from Postgres.", flush=True)

        done = False
        for season_type, week in weeks:
            if done:
                break
            games = fetch_games(key, args.season, season_type, week)
            print(f"Week {week} ({season_type}): {len(games)} games.", flush=True)

            # Fetch and cache the rankings for this week; used by build_team_rank_map().
            rankings = {}
            if week is not None:
                try:
                    rankings = fetch_rankings(key, args.season, season_type, week)
                    print(f"  fetched {len(rankings)} rankings.", flush=True)
                except Exception as exc:
                    print(f"  rankings fetch error: {exc}", flush=True)

            team_stats_by_game = fetch_team_stats(key, args.season, season_type, week)
            game_leaders_by_game = fetch_game_leaders(key, args.season, season_type, week)

            # Map team ids to their rank for this week; used when inserting/updating games.
            team_rank_map = build_team_rank_map(by_name, rankings)

            for game in games:
                row = game_row(game)
                game_date = parse_dt(pick(game, "startDate", "start_date"))
                completed = bool(pick(game, "completed", default=False))
                is_future = (game_date and game_date > now) or not completed
                if is_future and not args.include_future:
                    skipped_future += 1
                    continue

                home = pick(game, "homeTeam", "home_team")
                away = pick(game, "awayTeam", "away_team")
                row["home_team_id"] = resolve_team(game, "home", by_ext, by_name)
                row["away_team_id"] = resolve_team(game, "away", by_ext, by_name)
                row["game_date"] = game_date
                game_id_key = str(pick(game, "id"))
                next_game_stats = team_stats_by_game.get(game_id_key, {})
                home_stats = next_game_stats.get("home")
                if home_stats is None:
                    home_stats = next_game_stats.get(str(row["home_team_id"]))
                if home_stats is None and home:
                    home_stats = next_game_stats.get(scorer.normalize_text(str(home)))
                away_stats = next_game_stats.get("away")
                if away_stats is None:
                    away_stats = next_game_stats.get(str(row["away_team_id"]))
                if away_stats is None and away:
                    away_stats = next_game_stats.get(scorer.normalize_text(str(away)))
                row["home_team_stats"] = json.dumps(home_stats) if home_stats is not None else None
                row["away_team_stats"] = json.dumps(away_stats) if away_stats is not None else None
                
                # Store game leaders (top players by category)
                next_game_leaders = game_leaders_by_game.get(game_id_key, {})
                has_leaders = bool(
                    (next_game_leaders.get("home") or {})
                    or (next_game_leaders.get("away") or {})
                )
                if has_leaders:
                    row["game_leaders"] = json.dumps(next_game_leaders)
                else:
                    row["game_leaders"] = None
                    
                home_mascot = mascot_by_id.get(row["home_team_id"])
                away_mascot = mascot_by_id.get(row["away_team_id"])

                # Add rank info to the row from the cached team_rank_map.
                row["home_rank"] = team_rank_map.get(row["home_team_id"])
                row["away_rank"] = team_rank_map.get(row["away_team_id"])

                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, video_id, highlights_valid, highlights_checked, highlight_score "
                        "FROM games WHERE external_id = %s",
                        (row["external_id"],),
                    )
                    existing = cur.fetchone()

                video_id = existing[1] if existing else None
                highlights_valid = bool(existing[2]) if existing else False
                checked = bool(existing[3]) if existing else False
                highlight_score = existing[4] if existing else None

                # Only spend a YouTube search when it can change something and
                # the human review flag hasn't locked the choice.
                do_search = not args.no_highlights
                if do_search and not args.force_highlights and (highlights_valid and checked):
                    do_search = False
                # Skip highlight search for future games (no highlights exist yet)
                if do_search and is_future:
                    do_search = False

                if do_search:
                    found, found_score = find_highlight(
                        home, away, game_date, home_mascot, away_mascot
                    )
                    time.sleep(random.uniform(0.8, 1.8))  # be polite to YouTube
                    if found:
                        video_id = found
                        highlight_score = found_score
                        highlights_valid = True
                        highlights_found += 1
                        print(f"    ✓ {away} at {home}: {found} (score {found_score})", flush=True)

                if args.dry_run:
                    inserted += 0 if existing else 1
                    updated += 1 if existing else 0
                elif existing:
                    sets = [
                        "name = %s", "season = %s", "week = %s", "type = %s",
                        "postseason_round = %s",
                        "game_date = %s", "location = %s", "home_team_id = %s",
                        "away_team_id = %s", "home_points = %s", "away_points = %s",
                        "home_line_scores = %s", "away_line_scores = %s",
                        "home_team_stats = %s", "away_team_stats = %s", "game_leaders = %s",
                        "home_rank = %s", "away_rank = %s",
                        "home_record = %s", "away_record = %s",
                        "excitement_index = %s", "synced_at = NOW()",
                    ]
                    vals = [
                        row["name"], row["season"], row["week"], row["type"],
                        row["postseason_round"],
                        row["game_date"], row["location"], row["home_team_id"],
                        row["away_team_id"], row["home_points"], row["away_points"],
                        row["home_line_scores"], row["away_line_scores"],
                        row["home_team_stats"], row["away_team_stats"], row["game_leaders"],
                        row["home_rank"], row["away_rank"],
                        row["home_record"], row["away_record"],
                        row["excitement_index"],
                    ]
                    # Never clobber a human's reviewed pick; otherwise store what
                    # the search produced.
                    if do_search and not checked:
                        sets += ["video_id = %s", "highlight_score = %s", "highlights_valid = %s"]
                        vals += [video_id, highlight_score, highlights_valid]
                    vals.append(existing[0])
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE games SET {', '.join(sets)} WHERE id = %s", vals
                        )
                    updated += 1
                else:
                    row["source_id"] = f"cfbd:{row['external_id']}"
                    row["video_id"] = video_id
                    row["highlight_score"] = highlight_score
                    row["highlights_valid"] = highlights_valid
                    with conn.cursor() as cur:
                        cur.execute(INSERT_SQL, row)
                    inserted += 1

                if not args.dry_run and (inserted + updated) % 20 == 0:
                    conn.commit()

                if args.limit and (inserted + updated) >= args.limit:
                    done = True
                    break

        if not args.dry_run:
            conn.commit()
        
        # Compute pregame records for all games (W-L-T snapshots before each game date)
        if not args.dry_run:
            records_updated = apply_pregame_records(conn, args.season)
            if records_updated:
                print(f"Updated pregame records for {records_updated} games.", flush=True)
                conn.commit()

    print(
        f"\nDone. Inserted {inserted}, updated {updated} games "
        f"({highlights_found} highlights found, {skipped_future} future games skipped)."
        + (" [dry-run]" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()
