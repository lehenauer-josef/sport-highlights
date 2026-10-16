# CFB Highlights

A web app for reviewing college football (and other sports) game highlights, plus
Python importers that pull games from the [College Football Data API](https://collegefootballdata.com)
and find the best YouTube highlight video for each game.

## Stack

- **Web**: Next.js 15 (App Router), React 19, Tailwind CSS 4, Drizzle ORM; deployed on Vercel.
- **Database**: hosted PostgreSQL on [Neon](https://neon.tech). Production, the
  daily importers (GitHub Actions, triggered by [cron-job.org](https://console.cron-job.org/jobs/8656592))
  and local development all use this database.
- **Importers**: Python 3.9+ scripts in `importer/`.

## Project layout

```
web/                      # Next.js app
  src/app/                # routes (review UI, per-sport tabs, API routes)
  src/db/schema.ts        # Drizzle schema
  .env.example            # DATABASE_URL template
importer/
  import_games.py         # CFD API -> Postgres (games + YouTube highlights)
  import_nhl_games.py     # NHL API -> Postgres (games, stats + YouTube highlights)
  import_nba_games.py     # ESPN NBA API -> Postgres (teams, games, stats + highlights)
  import_nfl_games.py     # nflverse + ESPN -> Postgres (games, stats + highlights)
  highlight_scorer.py     # shared YouTube highlight scorer (used by all importers)
  requirements.txt        # psycopg
  .cfbd_key               # (optional) CFD API key file
db/
  migrations/             # SQL migrations already applied to the Neon database
.github/workflows/        # daily importer run (triggered by cron-job.org)
```

## Prerequisites

- Node.js 20.12+ and npm
- Python 3.9+
- The Neon connection string (`DATABASE_URL`)
- A [College Football Data API](https://collegefootballdata.com/key) key (for `import_games.py`)

---

## 1. Configure the database connection

Everything connects through the `DATABASE_URL` environment variable; there is no
local database or default connection. Copy the template and paste the Neon
connection string:

```bash
cp web/.env.example web/.env.local
```

Keep the value in quotes: the Neon URL contains `&`, which breaks unquoted shell
sourcing. To use it in a shell (for the importers or `psql`):

```bash
export DATABASE_URL="$(grep '^DATABASE_URL=' web/.env.local | cut -d= -f2- | tr -d '"')"
```

The GitHub Actions importers read it from the `DATABASE_URL` repository secret,
and Vercel from its project environment variables.

Teams are maintained in the database: only the NBA importer creates or updates
teams; college football, NFL and NHL teams already exist in Neon.

### Schema changes

`web/src/db/schema.ts` is the source of truth. Apply changes with:

```bash
npm --prefix web run db:push
```

Renames need a hand-written SQL migration instead (see `db/migrations/`), so
`db:push` does not drop and recreate a column. Apply migrations with
`psql "$DATABASE_URL" -f db/migrations/<file>.sql`. `0001` (already applied)
renamed the legacy `airtable_id` key column of `teams` and `games` to
`source_id` (the unique import key, e.g. `nfl:2024_15_BAL_NYG`). `0002` (already
applied) added `games.postseason_round`; existing postseason games were filled in
once by a one-off backfill script (removed afterwards, see git history). `0003`
added `games.highlight_score`, the scorer score (see `importer/highlight_scorer.py`)
of the auto-picked highlight video. The importers write it together with
`video_id`, and the review queue shows it on each card. It stays NULL for
games imported before the column existed and is cleared when a reviewer sets
a video by hand.

## 2. Start the web application

```bash
# from the repo root
npm --prefix web install            # first time only
npm --prefix web run dev
```

The app reads `DATABASE_URL` from `web/.env.local`. By default Next.js serves on
<http://localhost:3000> (it will pick the next free port, e.g. 3001, if 3000 is
in use).

Sport pages and the review queue offer team, season, week, highlights, and sorting
controls, plus division/ranking filters for college football. Conference filtering
is not available in the UI; legacy `conference` URL parameters are ignored on
these pages. Conference details remain visible on games.

The Week dropdown lists only weeks and rounds with games in the selected season,
grouped: "Regular Season" (Week 1…N, then "All" regular-season games,
`week=regular`) and "Postseason" (the rounds, then "All" postseason games,
`week=postseason`). College football splits the postseason into "Postseason –
FBS" (`week=postseason-fbs` for its "All") and "Postseason – FCS"
(`week=postseason-fcs`). There is no option for all games at once; a missing or
unavailable week falls back to the regular-season "All" (or a postseason "All"
if the season has no regular-season games). Week numbers match regular-season
games only; postseason rounds are stored per game in `games.postseason_round` by
the importers:

| Sport | Rounds (`postseason_round` key) |
| ----- | ------------------------------- |
| College Football – FBS | Bowl Games (`bowl`), CFP 1st Round (`cfp-first-round`), CFP Quarterfinals (`cfp-quarterfinal`), CFP Semifinals (`cfp-semifinal`), National Championship (`cfp-championship`) |
| College Football – FCS | Bowl Games (`fcs-bowl`, bowls between two FCS teams such as the Celebration Bowl), FCS 1st Round (`fcs-first-round`), FCS 2nd Round (`fcs-second-round`), FCS Quarterfinals (`fcs-quarterfinal`), FCS Semifinals (`fcs-semifinal`), FCS Championship (`fcs-championship`) |
| NFL | Wild Card Playoffs (`wild-card`), Divisional Playoffs (`divisional`), Conference Championship (`conference`), Super Bowl (`super-bowl`) |
| NHL | 1st Round (`round-1`), 2nd Round (`round-2`), Conference Finals (`conference-finals`), Stanley Cup Final (`finals`) |
| NBA | Play-In (`play-in`), 1st Round (`round-1`), 2nd Round (`round-2`), Conference Finals (`conference-finals`), NBA Finals (`finals`) |

The importers take the round from their source: CollegeFootballData game notes,
the nflverse `game_type` (WC/DIV/CON/SB), the NHL schedule's `seriesStatus.round`,
and the ESPN NBA competition type (play-in games are ESPN season type 5).
CollegeFootballData lists the FCS playoff rounds before the semifinals as
regular-season games; the importer stores every game whose notes name an
"FCS Championship" round as `postseason`, so it no longer counts towards a week.

> **Note:** never run `next build` while `next dev` is running — they share
> `web/.next` and it can corrupt the dev build. If that happens, stop dev and run
> `rm -rf web/.next`, then restart.

---

## 3. Import data

All importers connect via the `DATABASE_URL` environment variable and exit with
an error if it is not set (see step 1). Install dependencies once:

```bash
pip install -r importer/requirements.txt
```

### A. Import games + highlights from the CFD API (`import_games.py`)

This is the primary importer. It fetches games from the College Football Data API,
resolves each team against the `teams` table, searches YouTube for the best
highlight video using the scorer in `importer/highlight_scorer.py`, and upserts everything
into Postgres.

Provide your CFD API key via the `CFBD_API_KEY` environment variable **or** a
`.cfbd_key` file in `importer/` (or the repo root):

```bash
export CFBD_API_KEY=your_key_here
```

Import a single week (recommended for a first run):

```bash
python3 importer/import_games.py --season 2022 --week 4
```

Import a whole season (walks the CFD calendar and imports every started week, plus
postseason weeks the calendar omits, e.g. the 2023 FCS playoff rounds listed as
postseason weeks 13–15):

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
  creates or modifies them.

### B. Import NHL games + highlights (`import_nhl_games.py`)

This importer pulls each NHL team's schedule
from `api-web.nhle.com`, deduplicates games across teams, searches YouTube for
the best highlight, and upserts the result into Postgres.
NHL does not provide numbered weeks, so the importer derives them as consecutive
7-day blocks starting with the first regular-season game of each season. Running
the importer again also fills in week numbers for existing NHL game records.
The web app reads the stored `week` column directly (all existing NHL records
have been backfilled), so games without a stored week do not match week filters.
The Week dropdown selects
one week, all regular-season games, a single playoff round or all postseason
games.

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

### C. Import NBA games, stats + highlights (`import_nba_games.py`)

This importer fetches each game day from the ESPN NBA scoreboard API, skips
preseason and All-Star games, searches YouTube for the best highlight (preferring
a full-length "GameTime Highlights" upload naming both teams, and rejecting videos
whose title names a different date or playoff game number), and upserts the
result into Postgres keyed by the ESPN event id. Play-in and playoff games are
stored as `postseason`.

NBA seasons are identified by their end year (`2026` = 2025-26). The NBA has no
numbered weeks, so the importer derives them as consecutive 7-day blocks (US
Eastern dates) starting on the first day of the regular season; postseason games
continue the numbering. Running the importer again also fills in week numbers for
existing NBA game records. The web app reads the stored `week` column directly
(all existing NBA records have been backfilled), so games without a stored week
do not match week filters.

NBA and college teams share ESPN ids (e.g. `12` is both the LA Clippers and
Arizona), so teams are identified by sport + id: `teams` has a unique key on
`(conference_type, external_id)`. NBA team data is owned by this importer: on
every run it syncs the NBA rows from ESPN's NBA team list (name, nickname,
conference, color, logo), adds missing teams, and carries renames into the
stored game names. College team rows are never modified.

```bash
python3 importer/import_nba_games.py                        # last 17 days
python3 importer/import_nba_games.py --days 3
python3 importer/import_nba_games.py --season 2025-26
python3 importer/import_nba_games.py --season 2026 --limit 10 --dry-run
# Backfill game stats only, preserving all existing game metadata/highlight reviews:
python3 importer/import_nba_games.py --stats-only
python3 importer/import_nba_games.py --season 2025-26 --stats-only
```

For every completed game the importer also fetches ESPN's NBA game summary
(`/apis/site/v2/sports/basketball/nba/summary?event={id}`) and stores it for the
game modal, using the same layout as football:

- **Quarter scores**: 1-4 plus OT (all overtime periods summed), hidden while
  "Show result" is off.
- **Team Stats**: FG%, 3PT%, FT%, rebounds, offensive rebounds, assists, steals,
  blocks, turnovers, points in the paint, fast break points, fouls and largest lead.
- **Game Leaders**: per-team points, rebounds, assists, steals and blocks leaders
  with NBA player headshots.

Line scores go into `home_line_scores`/`away_line_scores`, team stats into
`home_team_stats`/`away_team_stats` and leaders into `game_leaders` (no schema
change needed). An unavailable summary is logged and never erases previously
imported stats.

Common flags:

| Flag                 | Description                                                         |
| -------------------- | ------------------------------------------------------------------- |
| `--season SEASON`    | Import a whole season by end year (`2026`, `2025-26`).              |
| `--days N`           | Without `--season`: days back from today to import (default: 17).   |
| `--include-future`   | Also import games that have not finished yet.                       |
| `--no-highlights`    | Skip the YouTube highlight search.                                  |
| `--force-highlights` | Re-run the highlight search even for already-checked games.         |
| `--stats-only`       | Only backfill game stats for existing games (no highlight search).  |
| `--limit N`          | Stop after importing N games (testing).                             |
| `--dry-run`          | Fetch and score but do not write to Postgres.                       |

---

### D. Import NFL games, stats + highlights (`import_nfl_games.py`)

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

### E. Daily import run (GitHub Actions + cron-job.org)

[`.github/workflows/daily-importers.yml`](.github/workflows/daily-importers.yml)
runs the CFB, NFL, NHL and NBA importers one after another with their default
(recent-games) arguments. It has no GitHub `schedule` trigger, because GitHub
started scheduled runs hours late. Instead, the
[cron-job.org job](https://console.cron-job.org/jobs/8656592) triggers the workflow
through the GitHub API once a day; the run time is set in that job (Europe/Vienna
time zone).

The cron-job.org job is configured as follows:

| Setting                         | Value                                                                                                          |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| URL                             | `https://api.github.com/repos/lehenauer-josef/sport-highlights/actions/workflows/daily-importers.yml/dispatches` |
| Request method (Advanced tab)   | `POST`                                                                                                         |
| Headers (Advanced tab)          | `Accept: application/vnd.github+json`, `Authorization: Bearer <token>`, `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json` |
| Request body (Advanced tab)     | `{"ref":"main"}`                                                                                               |

The token is a GitHub fine-grained personal access token limited to this
repository, with only the **Actions: Read and write** permission. It expires, so
when the job starts failing with `401`, create a new token
([github.com/settings/personal-access-tokens](https://github.com/settings/personal-access-tokens))
and replace it in the job's `Authorization` header. A successful trigger returns
`204 No Content`. Never commit the token.

To run the importers manually, use **Actions → Daily Sports Importers → Run
workflow** on GitHub, or the cron-job.org job's test run.

---

## Typical first-time setup

```bash
cp web/.env.example web/.env.local                # 1. paste the Neon DATABASE_URL
npm --prefix web install                          # 2. web dependencies
npm --prefix web run dev                          # 3. run the app
pip install -r importer/requirements.txt          # 4. (optional) run an importer
export DATABASE_URL="$(grep '^DATABASE_URL=' web/.env.local | cut -d= -f2- | tr -d '"')"
python3 importer/import_nfl_games.py --season 2024 --week 15 --no-highlights
```

## Database access

```bash
psql "$DATABASE_URL"
```
