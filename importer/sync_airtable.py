#!/usr/bin/env python3
"""Sync the Airtable "Games" table into the Postgres `games` table.

The Next.js app reads from Postgres; this importer is the bridge that keeps it
current. It reuses the same Airtable PAT the existing Python scorer uses
(env AIRTABLE_PAT or a .airtable_pat file), and upserts one row per game keyed
on the Airtable record id, so it is safe to run repeatedly.

Usage:
    pip install -r requirements.txt
    export DATABASE_URL=postgres://cfb:cfb@localhost:5433/highlights
    python sync_airtable.py            # full sync
    python sync_airtable.py --limit 50 # sync first N records (testing)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import psycopg

AIRTABLE_BASE_ID = "appwv5KrUoIiMXoaM"
AIRTABLE_GAMES_TABLE = "tblEiBW2TbLaNNips"
AIRTABLE_TEAMS_TABLE = "tblvRWbkclZbB9rll"
USER_AGENT = "cfb-highlights-importer/1.0"

DEFAULT_DB_URL = "postgres://cfb:cfb@localhost:5433/highlights"

# Conference types to exclude from the app entirely.
EXCLUDED_CONFERENCE_TYPES = ["Soccer"]

# College football divisions, for the --cfb-only scope.
CFB_CONFERENCE_TYPES = {"FBS", "FCS"}

# NFL, for the --nfl-only scope.
NFL_CONFERENCE_TYPES = {"NFL"}

CREATE_TEAMS_SQL = """
CREATE TABLE IF NOT EXISTS teams (
    id                   SERIAL PRIMARY KEY,
    airtable_id          TEXT NOT NULL UNIQUE,
    external_id          TEXT,
    name                 TEXT,
    mascot               TEXT,
    conference           TEXT,
    conference_type      TEXT,
    color                TEXT,
    logo_url             TEXT,
    conference_logo_url  TEXT,
    logo_data            TEXT,
    logo_mime            TEXT,
    conference_logo_data TEXT,
    conference_logo_mime TEXT,
    synced_at            TIMESTAMPTZ DEFAULT NOW()
);
"""

# Add the downloaded-image columns on databases created before logo caching.
MIGRATE_TEAMS_SQL = """
ALTER TABLE teams ADD COLUMN IF NOT EXISTS logo_data TEXT;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS logo_mime TEXT;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS conference_logo_data TEXT;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS conference_logo_mime TEXT;
"""

CREATE_GAMES_SQL = """
CREATE TABLE IF NOT EXISTS games (
    id                SERIAL PRIMARY KEY,
    airtable_id       TEXT NOT NULL UNIQUE,
    external_id       TEXT,
    name              TEXT,
    season            TEXT,
    week              INTEGER,
    type              TEXT,
    game_date         TIMESTAMPTZ,
    location          TEXT,
    home_team_id      INTEGER REFERENCES teams(id),
    away_team_id      INTEGER REFERENCES teams(id),
    home_points       INTEGER,
    away_points       INTEGER,
    home_rank         INTEGER,
    away_rank         INTEGER,
    home_record       TEXT,
    away_record       TEXT,
    overtime          BOOLEAN DEFAULT FALSE,
    excitement_index  NUMERIC,
    thumbnail_url     TEXT,
    video_id          TEXT,
    highlights_valid  BOOLEAN DEFAULT FALSE,
    highlights_checked BOOLEAN DEFAULT FALSE,
    better_video_id   TEXT,
    reason            TEXT,
    review_status     TEXT DEFAULT 'pending',
    modified          TIMESTAMPTZ,
    synced_at         TIMESTAMPTZ DEFAULT NOW()
);
"""

# Add the foreign-key columns on databases created before normalization.
MIGRATE_SQL = """
ALTER TABLE games ADD COLUMN IF NOT EXISTS home_team_id INTEGER REFERENCES teams(id);
ALTER TABLE games ADD COLUMN IF NOT EXISTS away_team_id INTEGER REFERENCES teams(id);
"""

# Denormalized team columns replaced by the teams table; dropped after FKs are
# populated so an older database converges to the normalized shape.
DROP_LEGACY_SQL = """
ALTER TABLE games DROP COLUMN IF EXISTS home_team_name;
ALTER TABLE games DROP COLUMN IF EXISTS away_team_name;
ALTER TABLE games DROP COLUMN IF EXISTS home_conference;
ALTER TABLE games DROP COLUMN IF EXISTS away_conference;
ALTER TABLE games DROP COLUMN IF EXISTS conference_type;
ALTER TABLE games DROP COLUMN IF EXISTS home_conference_type;
ALTER TABLE games DROP COLUMN IF EXISTS away_conference_type;
ALTER TABLE games DROP COLUMN IF EXISTS home_logo_url;
ALTER TABLE games DROP COLUMN IF EXISTS away_logo_url;
ALTER TABLE games DROP COLUMN IF EXISTS home_conference_logo_url;
ALTER TABLE games DROP COLUMN IF EXISTS away_conference_logo_url;
"""

TEAM_COLUMNS = [
    "airtable_id", "external_id", "name", "mascot", "conference",
    "conference_type", "color", "logo_url", "conference_logo_url",
    "logo_data", "logo_mime", "conference_logo_data", "conference_logo_mime",
]

TEAM_UPSERT_SQL = f"""
INSERT INTO teams ({", ".join(TEAM_COLUMNS)})
VALUES ({", ".join("%s" for _ in TEAM_COLUMNS)})
ON CONFLICT (airtable_id) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in TEAM_COLUMNS if c != "airtable_id")},
    synced_at = NOW();
"""

# Game columns written by the importer (review_status is user-owned, left
# untouched on update so manual review decisions survive a re-sync).
GAME_COLUMNS = [
    "airtable_id", "external_id", "name", "season", "week", "type", "game_date",
    "location", "home_team_id", "away_team_id", "home_points", "away_points",
    "home_rank", "away_rank", "home_record", "away_record", "overtime",
    "excitement_index", "thumbnail_url", "video_id", "highlights_valid",
    "highlights_checked", "better_video_id", "reason", "modified",
]

GAME_UPSERT_SQL = f"""
INSERT INTO games ({", ".join(GAME_COLUMNS)})
VALUES ({", ".join("%s" for _ in GAME_COLUMNS)})
ON CONFLICT (airtable_id) DO UPDATE SET
    {", ".join(f"{c} = EXCLUDED.{c}" for c in GAME_COLUMNS if c != "airtable_id")},
    synced_at = NOW();
"""


def ssl_context() -> ssl.SSLContext:
    # This Python install lacks CA certs; match the existing scorer scripts.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def download_image(url, cache):
    """Fetch an image once and return (base64 str, mime) or (None, None)."""
    if not url:
        return (None, None)
    if cache is not None and url in cache:
        return cache[url]
    result = (None, None)
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=30, context=ssl_context()) as resp:
            data = resp.read()
            mime = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
        result = (base64.b64encode(data).decode("ascii"), mime or "image/png")
    except Exception:
        result = (None, None)
    if cache is not None:
        cache[url] = result
    return result


def get_pat() -> str:
    val = os.environ.get("AIRTABLE_PAT")
    if val:
        return val.strip()
    for path in (
        os.path.join(os.path.dirname(__file__), "..", ".airtable_pat"),
        os.path.join(os.path.dirname(__file__), ".airtable_pat"),
    ):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
    raise SystemExit("Set AIRTABLE_PAT or create a .airtable_pat file.")


def airtable_records(pat: str, table_id: str, formula: str | None = None):
    base_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{table_id}"
    headers = {"Authorization": f"Bearer {pat}", "User-Agent": USER_AGENT}
    ctx = ssl_context()
    params = {"pageSize": 100}
    if formula:
        params["filterByFormula"] = formula
    while True:
        url = f"{base_url}?{urlencode(params)}"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for rec in data.get("records", []):
            yield rec
        offset = data.get("offset")
        if not offset:
            break
        params["offset"] = offset


def first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def first_attachment_url(value):
    if isinstance(value, list) and value:
        return value[0].get("url")
    return None


def first_link(value):
    """First linked record id from an Airtable link field."""
    if isinstance(value, list) and value:
        return value[0]
    return None


def clean_str(value):
    s = first(value)
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def to_int(value):
    v = first(value)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def map_team(rec, logo_data, logo_mime, conf_data, conf_mime) -> tuple:
    f = rec.get("fields", {})
    return (
        rec["id"],
        clean_str(f.get("ID")),
        clean_str(f.get("Name")),
        clean_str(f.get("Mascot")),
        clean_str(f.get("Conference")),
        clean_str(f.get("Conference Type")),
        clean_str(f.get("Color")),
        first_attachment_url(f.get("Logo")),
        first_attachment_url(f.get("Conference Logo")),
        logo_data,
        logo_mime,
        conf_data,
        conf_mime,
    )


def map_record(rec, home_team_id, away_team_id) -> tuple:
    f = rec.get("fields", {})
    return (
        rec["id"],
        clean_str(f.get("ID")),
        clean_str(f.get("Name")),
        clean_str(f.get("Season")),
        to_int(f.get("Week")),
        clean_str(f.get("Type")),
        clean_str(f.get("Date")),
        clean_str(f.get("Location")),
        home_team_id,
        away_team_id,
        to_int(f.get("Home Points")),
        to_int(f.get("Away Points")),
        to_int(f.get("Home Rank")),
        to_int(f.get("Away Rank")),
        clean_str(f.get("Home Record")),
        clean_str(f.get("Away Record")),
        bool(f.get("Overtime")),
        f.get("Excitement Index"),
        first_attachment_url(f.get("Thumbnail")),
        clean_str(f.get("Highlights")),
        bool(f.get("Highlights Valid")),
        bool(f.get("Highlights checked")),
        clean_str(f.get("Highlights found")),
        clean_str(f.get("Reason new highlights")),
        clean_str(f.get("modified")),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Airtable games into Postgres.")
    parser.add_argument("--limit", type=int, default=None, help="Only sync first N records.")
    parser.add_argument("--season", type=str, default=None, help="Only sync games from this season.")
    parser.add_argument("--week", type=int, default=None, help="Only sync games from this week.")
    parser.add_argument(
        "--cfb-only",
        action="store_true",
        help="Only college football (FBS/FCS) games.",
    )
    parser.add_argument(
        "--nfl-only",
        action="store_true",
        help="Only NFL games.",
    )
    args = parser.parse_args()

    # Scope the Airtable games fetch to the requested season/week.
    game_conditions = []
    if args.season:
        game_conditions.append(f"{{Season}}&''='{args.season}'")
    if args.week is not None:
        game_conditions.append(f"{{Week}}&''='{args.week}'")
    if len(game_conditions) > 1:
        game_formula = "AND(" + ",".join(game_conditions) + ")"
    elif game_conditions:
        game_formula = game_conditions[0]
    else:
        game_formula = None

    db_url = os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    pat = get_pat()

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TEAMS_SQL)
            cur.execute(CREATE_GAMES_SQL)
            cur.execute(MIGRATE_SQL)
            cur.execute(MIGRATE_TEAMS_SQL)
        conn.commit()

        # Reuse already-downloaded logo bytes so we only fetch each once.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT airtable_id, logo_data, logo_mime, "
                "conference_logo_data, conference_logo_mime FROM teams"
            )
            stored_logos = {
                aid: (ld, lm, cd, cm)
                for aid, ld, lm, cd, cm in cur.fetchall()
            }

        # 1. Teams first, so games can reference them.
        img_cache: dict = {}
        team_count = 0
        downloaded = 0
        team_batch: list[tuple] = []
        for rec in airtable_records(pat, AIRTABLE_TEAMS_TABLE):
            f = rec.get("fields", {})
            prev = stored_logos.get(rec["id"])
            logo_url = first_attachment_url(f.get("Logo"))
            conf_url = first_attachment_url(f.get("Conference Logo"))
            if prev and prev[0]:
                logo_data, logo_mime = prev[0], prev[1]
            else:
                logo_data, logo_mime = download_image(logo_url, img_cache)
                if logo_data:
                    downloaded += 1
            if prev and prev[2]:
                conf_data, conf_mime = prev[2], prev[3]
            else:
                conf_data, conf_mime = download_image(conf_url, img_cache)
                if conf_data:
                    downloaded += 1
            team_batch.append(
                map_team(rec, logo_data, logo_mime, conf_data, conf_mime)
            )
            team_count += 1
            if len(team_batch) >= 200:
                with conn.cursor() as cur:
                    cur.executemany(TEAM_UPSERT_SQL, team_batch)
                conn.commit()
                print(f"  synced {team_count} teams ({downloaded} images)...", flush=True)
                team_batch.clear()
        if team_batch:
            with conn.cursor() as cur:
                cur.executemany(TEAM_UPSERT_SQL, team_batch)
            conn.commit()
        print(f"  synced {team_count} teams ({downloaded} images downloaded).", flush=True)

        # Map Airtable team record id -> (db id, conference_type).
        with conn.cursor() as cur:
            cur.execute("SELECT airtable_id, id, conference_type FROM teams")
            team_map = {
                aid: (tid, ctype) for aid, tid, ctype in cur.fetchall()
            }

        # 2. Games, resolving team links to foreign keys.
        count = 0
        skipped = 0
        batch: list[tuple] = []
        for rec in airtable_records(pat, AIRTABLE_GAMES_TABLE, game_formula):
            f = rec.get("fields", {})
            home = team_map.get(first_link(f.get("Home Team")))
            away = team_map.get(first_link(f.get("Away Team")))
            home_type = home[1] if home else None
            away_type = away[1] if away else None
            if (
                home_type in EXCLUDED_CONFERENCE_TYPES
                or away_type in EXCLUDED_CONFERENCE_TYPES
            ):
                skipped += 1
                continue
            if (
                args.cfb_only
                and home_type not in CFB_CONFERENCE_TYPES
                and away_type not in CFB_CONFERENCE_TYPES
            ):
                skipped += 1
                continue
            if (
                args.nfl_only
                and home_type not in NFL_CONFERENCE_TYPES
                and away_type not in NFL_CONFERENCE_TYPES
            ):
                skipped += 1
                continue
            batch.append(
                map_record(rec, home[0] if home else None, away[0] if away else None)
            )
            count += 1
            if len(batch) >= 200:
                with conn.cursor() as cur:
                    cur.executemany(GAME_UPSERT_SQL, batch)
                conn.commit()
                print(f"  upserted {count} games...", flush=True)
                batch.clear()
            if args.limit and count >= args.limit:
                break

        if batch:
            with conn.cursor() as cur:
                cur.executemany(GAME_UPSERT_SQL, batch)
            conn.commit()

        # Purge games linked to excluded teams (e.g. Soccer) from earlier syncs.
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM games
                WHERE home_team_id IN (
                        SELECT id FROM teams WHERE conference_type = ANY(%s))
                   OR away_team_id IN (
                        SELECT id FROM teams WHERE conference_type = ANY(%s))
                """,
                (EXCLUDED_CONFERENCE_TYPES, EXCLUDED_CONFERENCE_TYPES),
            )
            deleted = cur.rowcount
        conn.commit()

        # Retire the denormalized team columns once FKs are populated.
        with conn.cursor() as cur:
            cur.execute(DROP_LEGACY_SQL)
        conn.commit()

    print(
        f"Done. Synced {team_count} teams and {count} games "
        f"(skipped {skipped} excluded; removed {deleted} stale excluded rows)."
    )


if __name__ == "__main__":
    main()
