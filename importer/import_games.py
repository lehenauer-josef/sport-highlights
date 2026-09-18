#!/usr/bin/env python3
"""Import College Football games straight from the collegefootballdata.com API
into Postgres — a Python replacement for the two N8N workflows.

The old pipeline was: N8N pulled the CFD calendar + games, searched YouTube for
each game's best highlight, and upserted everything into Airtable, after which
sync_airtable.py mirrored Airtable into Postgres. This script collapses that
into one step by writing games (and the highlight it finds) directly to the
`games` table.

Teams are expected to already exist in the `teams` table (populated by
sync_airtable.py); games link to them by CFD team id (external_id) with a
normalized-name fallback. Games are keyed on external_id (the CFD game id), so
re-runs update in place and any existing Airtable-sourced row is reused.

The YouTube search + "best highlight" scorer is reused verbatim from
check_highlights.py so the ranking stays identical to the validation tooling.

Usage:
    pip install -r requirements.txt
    export CFBD_API_KEY=...        # or create importer/.cfbd_key / .cfbd_key
    export DATABASE_URL=postgres://cfb:cfb@localhost:5433/highlights
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
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

import psycopg

# Reuse the exact "best highlight" scorer the retired N8N workflow used.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import n8n_find_highlight as scorer  # noqa: E402

CFBD_BASE = "https://api.collegefootballdata.com"
USER_AGENT = "cfb-highlights-importer/1.0"
DEFAULT_DB_URL = "postgres://cfb:cfb@localhost:5433/highlights"

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
    return weeks


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


def game_row(game: dict) -> dict:
    home = pick(game, "homeTeam", "home_team")
    away = pick(game, "awayTeam", "away_team")
    return {
        "external_id": str(pick(game, "id")),
        "name": f"{away} at {home}" if home and away else None,
        "season": str(pick(game, "season", default="")) or None,
        "week": to_int(pick(game, "week")),
        "type": pick(game, "seasonType", "season_type", default="regular"),
        "location": pick(game, "venue"),
        "home_points": to_int(pick(game, "homePoints", "home_points")),
        "away_points": to_int(pick(game, "awayPoints", "away_points")),
        "excitement_index": to_float(pick(game, "excitementIndex", "excitement_index")),
    }


INSERT_SQL = """
INSERT INTO games (
    airtable_id, external_id, name, season, week, type, game_date, location,
    home_team_id, away_team_id, home_points, away_points, excitement_index,
    video_id, highlights_valid, highlights_checked, review_status
) VALUES (
    %(airtable_id)s, %(external_id)s, %(name)s, %(season)s, %(week)s, %(type)s,
    %(game_date)s, %(location)s, %(home_team_id)s, %(away_team_id)s,
    %(home_points)s, %(away_points)s, %(excitement_index)s,
    %(video_id)s, %(highlights_valid)s, FALSE, 'pending'
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
    shape the n8n scorer expects. Skips live streams and results without a
    duration, mirroring the n8n 'Parse Video Information' node."""
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
    """Search YouTube, then score the results with the n8n scorer; best id or None."""
    if not (home and away):
        return None
    try:
        videos = search_youtube(build_query(home, away, game_date), limit=20)
        best = scorer.find_best_video(home, away, videos, home_mascot, away_mascot)
    except Exception as exc:  # network/parse errors shouldn't abort the run
        print(f"    highlight search error: {exc}", flush=True)
        return None
    return best.get("video_id") if best else None


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
    db_url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    now = datetime.now(timezone.utc)

    if args.week is not None:
        weeks = [(args.season_type, args.week)]
    else:
        weeks = fetch_weeks(key, args.season, now)
    print(f"Season {args.season}: {len(weeks)} week(s) to import.", flush=True)

    inserted = updated = skipped_future = highlights_found = 0

    with psycopg.connect(db_url) as conn:
        by_ext, by_name, mascot_by_id = load_team_maps(conn)
        print(f"Loaded {len(by_ext)} teams from Postgres.", flush=True)

        done = False
        for season_type, week in weeks:
            if done:
                break
            games = fetch_games(key, args.season, season_type, week)
            print(f"Week {week} ({season_type}): {len(games)} games.", flush=True)

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
                home_mascot = mascot_by_id.get(row["home_team_id"])
                away_mascot = mascot_by_id.get(row["away_team_id"])

                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, video_id, highlights_valid, highlights_checked "
                        "FROM games WHERE external_id = %s",
                        (row["external_id"],),
                    )
                    existing = cur.fetchone()

                video_id = existing[1] if existing else None
                highlights_valid = bool(existing[2]) if existing else False
                checked = bool(existing[3]) if existing else False

                # Only spend a YouTube search when it can change something and
                # the human review flag hasn't locked the choice.
                do_search = not args.no_highlights
                if do_search and not args.force_highlights and (highlights_valid or checked):
                    do_search = False

                if do_search:
                    found = find_highlight(
                        home, away, game_date, home_mascot, away_mascot
                    )
                    time.sleep(random.uniform(0.8, 1.8))  # be polite to YouTube
                    if found:
                        video_id = found
                        highlights_valid = True
                        highlights_found += 1
                        print(f"    ✓ {away} at {home}: {found}", flush=True)

                if args.dry_run:
                    inserted += 0 if existing else 1
                    updated += 1 if existing else 0
                elif existing:
                    sets = [
                        "name = %s", "season = %s", "week = %s", "type = %s",
                        "game_date = %s", "location = %s", "home_team_id = %s",
                        "away_team_id = %s", "home_points = %s", "away_points = %s",
                        "excitement_index = %s", "synced_at = NOW()",
                    ]
                    vals = [
                        row["name"], row["season"], row["week"], row["type"],
                        row["game_date"], row["location"], row["home_team_id"],
                        row["away_team_id"], row["home_points"], row["away_points"],
                        row["excitement_index"],
                    ]
                    # Never clobber a human's reviewed pick; otherwise store what
                    # the search produced.
                    if do_search and not checked:
                        sets += ["video_id = %s", "highlights_valid = %s"]
                        vals += [video_id, highlights_valid]
                    vals.append(existing[0])
                    with conn.cursor() as cur:
                        cur.execute(
                            f"UPDATE games SET {', '.join(sets)} WHERE id = %s", vals
                        )
                    updated += 1
                else:
                    row["airtable_id"] = f"cfbd:{row['external_id']}"
                    row["video_id"] = video_id
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

    print(
        f"\nDone. Inserted {inserted}, updated {updated} games "
        f"({highlights_found} highlights found, {skipped_future} future games skipped)."
        + (" [dry-run]" if args.dry_run else "")
    )


if __name__ == "__main__":
    main()
