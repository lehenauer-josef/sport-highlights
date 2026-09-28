#!/usr/bin/env python3
"""Import NFL games and highlights into Postgres.

This is the Python equivalent of the two N8N workflows attached in the task:

- the main workflow fetches NFL games from nflverse/games.csv,
- resolves NFL teams from the local `teams` table,
- builds the YouTube search URL,
- scrapes the search results page,
- keeps the top NFL-channel results sorted by views,
- and stores the winning highlight on the game row.

Like `import_games.py` for college football, this script writes directly to the
`games` table and is safe to re-run. Existing rows are updated in place by
`external_id` (the NFL game id). If a row already exists and has been manually
reviewed (`highlights_checked = true`), the highlight choice is left alone unless
`--force-highlights` is used.

Usage:
    pip install -r requirements.txt
    export DATABASE_URL=postgres://cfb:cfb@localhost:5433/highlights
    python import_nfl_games.py --season 2026
    python import_nfl_games.py --season 2026 --week 3
    python import_nfl_games.py --season 2026 --limit 10
    python import_nfl_games.py --season 2026 --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import n8n_find_highlight as scorer  # noqa: E402

NFLVERSE_GAMES_URL = (
    "https://raw.githubusercontent.com/nflverse/nfldata/refs/heads/master/data/games.csv"
)
DEFAULT_DB_URL = "postgres://cfb:cfb@localhost:5433/highlights"
USER_AGENT = "nfl-highlights-importer/1.0"
YT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
YT_SEARCH_URL = "https://www.youtube.com/results?search_query="

NFL_TEAM_NAME_BY_ABBR = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LV": "Las Vegas Raiders",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}


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


def parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            try:
                dt = datetime.strptime(str(value), "%Y-%m-%d")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_url_text(url: str, *, headers: dict[str, str] | None = None) -> str | None:
    req = Request(url, headers=headers or {"User-Agent": USER_AGENT})
    ctx = ssl_context()
    for attempt in range(4):
        try:
            with urlopen(req, timeout=30, context=ctx) as resp:
                return resp.read().decode("utf-8", errors="ignore")
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


def fetch_games_csv() -> list[dict]:
    text = fetch_url_text(NFLVERSE_GAMES_URL)
    if not text:
        return []
    reader = csv.DictReader(StringIO(text))
    return [row for row in reader]


def normalize_name(value: str | None) -> str | None:
    if not value:
        return None
    return scorer.normalize_text(str(value))


def load_team_maps(conn):
    """Build NFL team lookups from the local `teams` table."""
    by_ext: dict[str, int] = {}
    by_name: dict[str, int] = {}
    name_by_id: dict[int, str | None] = {}
    mascot_by_id: dict[int, str | None] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, external_id, name, mascot, conference_type FROM teams "
            "WHERE conference_type = 'NFL' OR conference_type IS NULL"
        )
        for tid, ext, name, mascot, conference_type in cur.fetchall():
            name_by_id[tid] = name
            mascot_by_id[tid] = mascot
            # Prefer NFL rows, but allow null conference_type rows to participate
            # in case the database was populated before the type was backfilled.
            if ext:
                by_ext.setdefault(str(ext), tid)
            if name:
                by_name.setdefault(normalize_name(name), tid)
            if mascot:
                by_name.setdefault(normalize_name(mascot), tid)
    return by_ext, by_name, name_by_id, mascot_by_id


def resolve_team(game: dict, side: str, by_ext, by_name):
    raw_id = pick(game, f"{side}_team", f"{side}Team", f"{side}_id")
    if raw_id is not None and str(raw_id) in by_ext:
        return by_ext[str(raw_id)]
    raw_name = pick(game, f"{side}_team_name", f"{side}TeamName", f"{side}Team")
    if raw_name:
        return by_name.get(normalize_name(raw_name))
    return None


def team_display_name(game: dict, side: str) -> str | None:
    name = pick(game, f"{side}_team_name", f"{side}TeamName", f"{side}Team")
    if name:
        return str(name)
    return None


def resolve_display_name(raw_name: str | None, team_id: int | None, name_by_id: dict[int, str | None]) -> str | None:
    if team_id is not None:
        mapped = name_by_id.get(team_id)
        if mapped:
            return mapped
    if raw_name:
        raw = str(raw_name).strip()
        if raw.upper() in NFL_TEAM_NAME_BY_ABBR:
            return NFL_TEAM_NAME_BY_ABBR[raw.upper()]
        return raw
    return None


def plusify(text: str | None) -> str:
    return (text or "").strip().replace(" ", "+")


def build_search_query(home: str, away: str, game_date: datetime | None) -> str:
    base = game_date or datetime.now(timezone.utc)
    before = (base + timedelta(days=2)).date().isoformat()
    after = (base - timedelta(days=1)).date().isoformat()
    return f"{away} vs {home} NFL highlights before:{before} after:{after}"


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


YT_DATA_RE = re.compile(r"ytInitialData\s*=\s*(\{.+?\})\s*;\s*</script>", re.S)


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


def _add_video(vr, out, seen):
    vid = vr.get("videoId")
    if not vid or vid in seen or _is_live(vr):
        return
    length = vr.get("lengthText")
    duration = length.get("simpleText") if isinstance(length, dict) else None
    if not duration:
        return
    owner = _runs_text(vr.get("ownerText")) or _runs_text(vr.get("longBylineText"))
    if owner != "NFL":
        return
    seen.add(vid)
    out.append(
        {
            "videoId": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": _runs_text(vr.get("title")),
            "channel": owner,
            "views": parse_views(_view_text(vr.get("viewCountText"))
                                  or _view_text(vr.get("shortViewCountText"))),
            "duration": duration,
        }
    )


def search_youtube(query: str, limit: int = 5) -> list[dict]:
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
    out.sort(key=lambda item: item.get("views") or 0, reverse=True)
    return out[:limit]


def choose_highlight(
    home: str,
    away: str,
    game_date: datetime | None,
    home_mascot: str | None = None,
    away_mascot: str | None = None,
) -> tuple[str | None, list[dict]]:
    if not (home and away):
        return None, []
    try:
        query = build_search_query(home, away, game_date)
        videos = search_youtube(query, limit=5)
    except Exception as exc:  # network/parse errors shouldn't abort the run
        print(f"    highlight search error: {exc}", flush=True)
        return None, []
    if not videos:
        return None, []
    best = scorer.find_best_video(home, away, videos, home_mascot, away_mascot)
    return (best.get("video_id") if best else None), videos


def game_type_from_csv(value: str | None) -> str | None:
    raw = (value or "").strip().upper()
    if raw == "REG":
        return "regular"
    if raw == "POST":
        return "postseason"
    if raw == "PRE":
        return "preseason"
    return raw.lower() or None


def game_row(
    game: dict,
    home_id: int | None,
    away_id: int | None,
    video_id: str | None,
    home_label: str | None,
    away_label: str | None,
) -> dict:
    gameday = parse_date(pick(game, "gameday", "game_date", "start_date"))
    season = pick(game, "season")
    game_id = str(pick(game, "game_id", "id", "gameId"))

    return {
        "airtable_id": f"nfl:{game_id}",
        "external_id": game_id,
        "name": f"{away_label} at {home_label}" if home_label and away_label else None,
        "season": str(season) if season is not None else None,
        "week": to_int(pick(game, "week")),
        "type": game_type_from_csv(pick(game, "game_type", "season_type", "type")),
        "game_date": gameday,
        "location": pick(game, "stadium", "location", "venue"),
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_points": to_int(pick(game, "home_score", "home_points")),
        "away_points": to_int(pick(game, "away_score", "away_points")),
        "home_line_scores": None,
        "away_line_scores": None,
        "home_team_stats": None,
        "away_team_stats": None,
        "game_leaders": None,
        "home_rank": None,
        "away_rank": None,
        "home_record": None,
        "away_record": None,
        "overtime": bool(to_int(pick(game, "overtime"))),
        "excitement_index": None,
        "thumbnail_url": None,
        "video_id": video_id,
        "highlights_valid": bool(video_id),
        "highlights_checked": False,
        "better_video_id": None,
        "reason": None,
        "review_status": "pending",
        "modified": None,
    }


def apply_pregame_records(conn, season: int) -> int:
    """Set home_record/away_record to each team's record before that game."""

    def fmt(w: int, l: int, t: int) -> str:
        return f"{w}-{l}" if t == 0 else f"{w}-{l}-{t}"

    team_wlt: dict[int, tuple[int, int, int]] = {}
    updates: list[tuple[str, str, int]] = []

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, home_team_id, away_team_id, home_points, away_points "
            "FROM games "
            "WHERE season = %s "
            "AND game_date IS NOT NULL "
            "AND home_team_id IS NOT NULL "
            "AND away_team_id IS NOT NULL "
            "ORDER BY game_date ASC, id ASC",
            (str(season),),
        )
        rows = cur.fetchall()

    for game_id, home_id, away_id, home_points, away_points in rows:
        hw, hl, ht = team_wlt.get(home_id, (0, 0, 0))
        aw, al, at = team_wlt.get(away_id, (0, 0, 0))
        updates.append((fmt(hw, hl, ht), fmt(aw, al, at), game_id))

        if home_points is None or away_points is None:
            continue

        if home_points > away_points:
            team_wlt[home_id] = (hw + 1, hl, ht)
            team_wlt[away_id] = (aw, al + 1, at)
        elif home_points < away_points:
            team_wlt[home_id] = (hw, hl + 1, ht)
            team_wlt[away_id] = (aw + 1, al, at)
        else:
            team_wlt[home_id] = (hw, hl, ht + 1)
            team_wlt[away_id] = (aw, al, at + 1)

    if not updates:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE games SET home_record = %s, away_record = %s WHERE id = %s",
            updates,
        )

    return len(updates)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import NFL games and highlights from nflverse + YouTube into Postgres.",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=datetime.now(timezone.utc).year,
        help="Season/year to import (default: current year).",
    )
    parser.add_argument(
        "--week",
        type=int,
        default=None,
        help="Only this week (skips the broader season scan).",
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
        "--dry-run",
        action="store_true",
        help="Fetch and score but do not write to Postgres.",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    now = datetime.now(timezone.utc)

    rows = fetch_games_csv()
    games = []
    for row in rows:
        if to_int(pick(row, "season")) != args.season:
            continue
        if args.week is not None and to_int(pick(row, "week")) != args.week:
            continue
        games.append(row)

    # Sort in chronological order, then by id for stable re-runs.
    games.sort(
        key=lambda g: (
            parse_date(pick(g, "gameday", "game_date", "start_date")) or now,
            str(pick(g, "game_id", "id", "gameId") or ""),
        )
    )

    print(f"Season {args.season}: {len(games)} game(s) queued.", flush=True)

    inserted = updated = skipped_future = highlights_found = 0

    with psycopg.connect(db_url) as conn:
        by_ext, by_name, name_by_id, mascot_by_id = load_team_maps(conn)
        print(f"Loaded {len(by_ext)} NFL teams from Postgres.", flush=True)

        for game in games:
            game_date = parse_date(pick(game, "gameday", "game_date", "start_date"))
            completed = (
                to_int(pick(game, "home_score")) is not None
                and to_int(pick(game, "away_score")) is not None
            )
            is_future = (game_date and game_date > now) or not completed
            if is_future and not args.include_future:
                skipped_future += 1
                continue

            home_id = resolve_team(game, "home", by_ext, by_name)
            away_id = resolve_team(game, "away", by_ext, by_name)

            home_name = pick(game, "home_team_name", "homeTeamName", "home_team")
            away_name = pick(game, "away_team_name", "awayTeamName", "away_team")
            home_display = resolve_display_name(home_name, home_id, name_by_id) or team_display_name(game, "home")
            away_display = resolve_display_name(away_name, away_id, name_by_id) or team_display_name(game, "away")
            home_mascot = mascot_by_id.get(home_id)
            away_mascot = mascot_by_id.get(away_id)

            existing = None
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, video_id, highlights_valid, highlights_checked "
                    "FROM games WHERE external_id = %s",
                    (str(pick(game, "game_id", "id", "gameId")),),
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
                found, videos = choose_highlight(
                    home_display,
                    away_display,
                    game_date,
                    home_mascot,
                    away_mascot,
                )
                time.sleep(random.uniform(0.8, 1.8))  # be polite to YouTube
                if found:
                    video_id = found
                    highlights_valid = True
                    highlights_found += 1
                    print(
                        f"    ✓ {away_display} at {home_display}: {found}",
                        flush=True,
                    )
                elif videos:
                    print(
                        f"    · no highlight picked for {away_display} at {home_display}",
                        flush=True,
                    )

            row = game_row(game, home_id, away_id, video_id, home_display, away_display)

            # These extra values are only meaningful when we actually searched.
            if do_search or not existing:
                row["highlights_valid"] = bool(video_id)
                row["highlights_checked"] = False
                row["review_status"] = "pending"

            if args.dry_run:
                inserted += 0 if existing else 1
                updated += 1 if existing else 0
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
                    "home_line_scores = %s",
                    "away_line_scores = %s",
                    "home_team_stats = %s",
                    "away_team_stats = %s",
                    "game_leaders = %s",
                    "home_rank = %s",
                    "away_rank = %s",
                    "home_record = %s",
                    "away_record = %s",
                    "overtime = %s",
                    "excitement_index = %s",
                    "thumbnail_url = %s",
                    "modified = %s",
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
                    row["home_line_scores"],
                    row["away_line_scores"],
                    row["home_team_stats"],
                    row["away_team_stats"],
                    row["game_leaders"],
                    row["home_rank"],
                    row["away_rank"],
                    row["home_record"],
                    row["away_record"],
                    row["overtime"],
                    row["excitement_index"],
                    row["thumbnail_url"],
                    row["modified"],
                ]
                if do_search and not checked:
                    sets += ["video_id = %s", "highlights_valid = %s", "highlights_checked = %s", "review_status = %s"]
                    vals += [video_id, bool(video_id), False, "pending"]
                vals.append(existing[0])
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE games SET {', '.join(sets)} WHERE id = %s",
                        vals,
                    )
                updated += 1
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO games (
                            airtable_id, external_id, name, season, week, type, game_date, location,
                            home_team_id, away_team_id, home_points, away_points, home_line_scores,
                            away_line_scores, home_team_stats, away_team_stats, game_leaders,
                            home_rank, away_rank, home_record, away_record, overtime,
                            excitement_index, thumbnail_url, video_id, highlights_valid,
                            highlights_checked, better_video_id, reason, review_status, modified
                        ) VALUES (
                            %(airtable_id)s, %(external_id)s, %(name)s, %(season)s, %(week)s, %(type)s,
                            %(game_date)s, %(location)s, %(home_team_id)s, %(away_team_id)s,
                            %(home_points)s, %(away_points)s, %(home_line_scores)s,
                            %(away_line_scores)s, %(home_team_stats)s, %(away_team_stats)s, %(game_leaders)s,
                            %(home_rank)s, %(away_rank)s, %(home_record)s, %(away_record)s,
                            %(overtime)s, %(excitement_index)s, %(thumbnail_url)s, %(video_id)s,
                            %(highlights_valid)s, %(highlights_checked)s, %(better_video_id)s,
                            %(reason)s, %(review_status)s, %(modified)s
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
