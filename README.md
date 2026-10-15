# CFB Highlights

A web app for reviewing college football (and other sports) game highlights, plus
Python importers that pull games from the [College Football Data API](https://collegefootballdata.com)
and find the best YouTube highlight video for each game.

## Stack

- **Web**: Next.js 15 (App Router), React 19, Tailwind CSS 4, Drizzle ORM.
- **Database**: PostgreSQL 16 (Docker), exposed on host port **5433**.
- **Importers**: Python 3.9+ scripts in `importer/`.

## Project layout

```
docker-compose.yml        # Postgres 16 (container cfb_highlights_db)
web/                      # Next.js app
  src/app/                # routes (review UI, per-sport tabs, API routes)
  src/db/schema.ts        # Drizzle schema
  .env.example            # DATABASE_URL template
importer/
  import_games.py         # CFD API -> Postgres (games + YouTube highlights)
  import_nhl_games.py     # NHL API -> Postgres (games, stats + YouTube highlights)
  import_nba_games.py     # ESPN NBA API -> Postgres (games + YouTube highlights)
  import_nfl_games.py     # nflverse + ESPN -> Postgres (games, stats + highlights)
  sync_airtable.py        # Airtable -> Postgres (teams + games)
  requirements.txt        # psycopg
  .cfbd_key               # (optional) CFD API key file
n8n_find_highlight.py     # production highlight scorer (used by import_games.py)
check_highlights.py       # older standalone validation harness
```

## Prerequisites

- Docker (for Postgres)
- Node.js 18+ and npm
- Python 3.9+
- A [College Football Data API](https://collegefootballdata.com/key) key (for `import_games.py`)
- An Airtable Personal Access Token (only for `sync_airtable.py`)

---

## 1. Start the database

```bash
docker compose up -d
```

This starts Postgres on `localhost:5433` (user `cfb`, password `cfb`, database
`highlights`). Data persists in the `cfb_db_data` volume.

### Restore from the bundled dump (fastest way to get data)

A compressed snapshot of the database is stored as split parts
(`db/highlights.sql.gz.part-*`, each under 50 MB). Restore it instead of
re-running all the importers:

```bash
docker compose up -d                                   # start Postgres first
cat db/highlights.sql.gz.part-* | gunzip | docker exec -i cfb_highlights_db psql -U cfb -d highlights
```

This loads all teams and games (including logos and highlight picks). To refresh
the snapshot after new imports, regenerate the parts with:

```bash
docker exec cfb_highlights_db pg_dump -U cfb -d highlights --no-owner --no-privileges | gzip > db/highlights.sql.gz
split -b 45m db/highlights.sql.gz db/highlights.sql.gz.part- && rm db/highlights.sql.gz
```

If you restore from the dump you can skip the schema push and the importer steps
below.

## 2. Start the web application

```bash
# from the repo root
cp web/.env.example web/.env        # first time only
npm --prefix web install            # first time only
npm --prefix web run dev
```

The app reads `DATABASE_URL` from `web/.env`
(`postgres://cfb:cfb@localhost:5433/highlights`). By default Next.js serves on
<http://localhost:3000> (it will pick the next free port, e.g. 3001, if 3000 is
in use).

Sport pages and the review queue offer team, season, week, highlights, and sorting
controls, plus division/ranking filters for college football. Conference filtering
is not available in the UI; legacy `conference` URL parameters are ignored on
these pages. Conference details remain visible on games.

Apply the schema to a fresh database with:

```bash
npm --prefix web run db:push
```

> **Note:** never run `next build` while `next dev` is running — they share
> `web/.next` and it can corrupt the dev build. If that happens, stop dev and run
> `rm -rf web/.next`, then restart.

---

## 3. Import data

All importers connect via the `DATABASE_URL` environment variable (defaults to the
docker-compose connection string if unset). Install dependencies once:

```bash
pip install -r importer/requirements.txt
```

### A. Import games + highlights from the CFD API (`import_games.py`)

This is the primary importer. It fetches games from the College Football Data API,
resolves each team against the `teams` table, searches YouTube for the best
highlight video using the scorer in `n8n_find_highlight.py`, and upserts everything
into Postgres.

Provide your CFD API key via the `CFBD_API_KEY` environment variable **or** a
`.cfbd_key` file in `importer/` (or the repo root):

```bash
export CFBD_API_KEY=your_key_here
export DATABASE_URL=postgres://cfb:cfb@localhost:5433/highlights
```

Import a single week (recommended for a first run):

```bash
python3 importer/import_games.py --season 2022 --week 4
```

Import a whole season (walks the CFD calendar and imports every started week):

```bash
python3 importer/import_games.py --season 2022
```

Common flags:

| Flag                  | Description                                                        |
| --------------------- | ----------------------------------------------------------------- |
| `--season YEAR`       | Season/year to import (default: current year).                    |
| `--week N`            | Only this week (skips the calendar lookup).                       |
| `--season-type TYPE`  | Season type for `--week` (default: `regular`).                    |
| `--limit N`           | Stop after importing N games (testing).                           |
| `--no-highlights`     | Skip the YouTube highlight search (only import game data/FKs).    |
| `--force-highlights`  | Re-run the search even for games that already have a video.       |
| `--include-future`    | Also import games that have not started yet.                      |
| `--dry-run`           | Fetch and score but do not write to Postgres.                     |

Notes:
- Games are keyed on the CFD game id; re-running updates in place.
- A game already marked as human-reviewed is never overwritten by the search.
- Teams are read-only: the importer only resolves existing teams, it never
  creates or modifies them. Populate teams first via `sync_airtable.py`.

### B. Sync teams (and games) from Airtable (`sync_airtable.py`)

Use this to populate the `teams` table (the source of teams the CFD importer
resolves against) and, optionally, to mirror Airtable's games.

Provide your Airtable token via the `AIRTABLE_PAT` environment variable **or** a
`.airtable_pat` file in the repo root:

```bash
export AIRTABLE_PAT=your_pat_here
export DATABASE_URL=postgres://cfb:cfb@localhost:5433/highlights

python3 importer/sync_airtable.py                 # full sync
python3 importer/sync_airtable.py --limit 50      # first N records (testing)
python3 importer/sync_airtable.py --cfb-only      # only FBS/FCS games
```

### C. Import NHL games + highlights (`import_nhl_games.py`)

This importer mirrors the NHL N8N workflow. It pulls each NHL team's schedule
from `api-web.nhle.com`, deduplicates games across teams, searches YouTube for
the best highlight, and upserts the result into Postgres.
NHL does not provide numbered weeks, so the importer derives them as consecutive
7-day blocks starting with the first regular-season game of each season. Running
the importer again also fills in week numbers for existing NHL game records.
The web app uses the same calculation for NHL records with no stored week, so
existing data can be filtered without reimporting it. The Week dropdown selects
one week or Postseason; All weeks removes the week restriction and preserves that
choice rather than reapplying the default week.

Use the live `/now` endpoint by omitting `--season`, or import a historical
season explicitly with an eight-digit season code such as `20232024`:

```bash
python3 importer/import_nhl_games.py
python3 importer/import_nhl_games.py --season 20232024
python3 importer/import_nhl_games.py --season 20222023 --dry-run
# Backfill game stats only, preserving all existing game metadata/highlight reviews:
python3 importer/import_nhl_games.py --stats-only
python3 importer/import_nhl_games.py --season 20252026 --stats-only
```

For every completed game the importer also fetches the NHL game story
(`/v1/wsc/game-story/{gameId}`) and stores it for the game modal:

- **Scoring**: goals grouped by period (including overtime) with scorer and
  assists (headshots and season totals), running score, PPG/SHG/EN badges and a
  link to the goal clip, plus every shootout attempt. Goals stay hidden while
  "Show result" is off.
- **Three Stars**: headshot, number, position and team, with G/A/P for skaters
  or SV%/GAA for goalies.
- **Team Stats**: shots, faceoff %, power play, penalty minutes, hits, blocked
  shots, giveaways and takeaways.

Team stats are stored in `home_team_stats`/`away_team_stats`, and goals, shootout
and three stars in `game_leaders` (no schema change needed). An unavailable game
story is logged and never erases previously imported stats.

Common flags:

| Flag                 | Description                                                        |
| -------------------- | ------------------------------------------------------------------ |
| `--season YYYYYYYY`  | Import a specific NHL season (e.g. `20232024`). Omit for `/now`.  |
| `--include-future`   | Also import games that have not started yet.                       |
| `--no-highlights`    | Skip the YouTube highlight search.                                 |
| `--force-highlights` | Re-run the highlight search even for already-checked games.        |
| `--stats-only`       | Only backfill game stats for existing games (no highlight search). |
| `--limit N`          | Stop after importing N games (testing).                            |
| `--dry-run`          | Fetch and score but do not write to Postgres.                      |

### D. Import NBA games + highlights (`import_nba_games.py`)

This importer mirrors the "NBA Game Highlights" / "NBA Highlight Search" N8N
workflows. It fetches each game day from the ESPN NBA scoreboard API, skips
preseason and All-Star games, searches YouTube for the best highlight (preferring
a full-length "GameTime Highlights" upload naming both teams, and rejecting videos
whose title names a different date or playoff game number), and upserts the
result into Postgres keyed by the ESPN event id. Play-in and playoff games are
stored as `postseason`.

NBA seasons are identified by their end year (`2026` = 2025-26). The NBA has no
numbered weeks, so the importer derives them as consecutive 7-day blocks (US
Eastern dates) starting on the first day of the regular season; postseason games
continue the numbering. Running the importer again also fills in week numbers for
existing NBA game records, and the web app uses the same calculation for NBA
records with no stored week, so existing data can be filtered by week without
reimporting it.

NBA and college teams share ESPN ids (e.g. `12` is both the LA Clippers and
Arizona), so teams are identified by sport + id: `teams` has a unique key on
`(conference_type, external_id)`. NBA team data is owned by this importer: on
every run it syncs the NBA rows from ESPN's NBA team list (name, nickname,
conference, color, logo), adds missing teams, and carries renames into the
stored game names. `sync_airtable.py` no longer overwrites existing NBA teams,
because the Airtable NBA records contain the data of the college teams with the
same ids. College team rows are never modified.

```bash
python3 importer/import_nba_games.py                        # last 17 days (like the workflow)
python3 importer/import_nba_games.py --days 3
python3 importer/import_nba_games.py --season 2025-26
python3 importer/import_nba_games.py --season 2026 --limit 10 --dry-run
```

Common flags:

| Flag                 | Description                                                         |
| -------------------- | ------------------------------------------------------------------- |
| `--season SEASON`    | Import a whole season by end year (`2026`, `2025-26`).              |
| `--days N`           | Without `--season`: days back from today to import (default: 17).   |
| `--include-future`   | Also import games that have not finished yet.                       |
| `--no-highlights`    | Skip the YouTube highlight search.                                  |
| `--force-highlights` | Re-run the highlight search even for already-checked games.         |
| `--limit N`          | Stop after importing N games (testing).                             |
| `--dry-run`          | Fetch and score but do not write to Postgres.                       |

---

### E. Import NFL games, stats + highlights (`import_nfl_games.py`)

NFL schedules and final scores come from nflverse's games CSV. For completed
games, the importer uses the CSV's `espn` event ID to fetch ESPN's NFL summary:
quarter/overtime scores, team stats, and per-team game leaders (passing, rushing,
receiving, tackles, sacks, and interceptions). These use the same detail layout
as college football, with NFL player headshots. "Show result" controls the quarter
scores and final score, just as it does for college games.

```bash
python3 importer/import_nfl_games.py --season 2024 --week 15 --no-highlights
# Backfill stats only, preserving all existing game metadata/highlight reviews:
python3 importer/import_nfl_games.py --season 2024 --week 15 --stats-only
python3 importer/import_nfl_games.py --season 2024 --stats-only
```

The NFL importer also accepts `--limit`, `--dry-run`, `--include-future`,
`--no-highlights`, and `--force-highlights`. `--stats-only` updates existing games
only and never searches for highlights. A missing ESPN ID, unavailable summary,
or missing stat is logged (where the whole summary is unavailable) and does not
erase previously imported stats. Older seasons need a backfill before stats
appear; no database migration or ESPN API key is required.

---

## Typical first-time setup

```bash
docker compose up -d                              # 1. database
cp web/.env.example web/.env                      # 2. web env
npm --prefix web install && npm --prefix web run db:push
python3 importer/sync_airtable.py                 # 3. load teams
export CFBD_API_KEY=your_key_here                 # 4. import games + highlights
python3 importer/import_games.py --season 2022 --week 4
npm --prefix web run dev                          # 5. run the app
```

## Database access

```bash
docker exec cfb_highlights_db psql -U cfb -d highlights
```
