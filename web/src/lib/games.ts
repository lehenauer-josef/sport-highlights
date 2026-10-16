import {
  and,
  between,
  desc,
  eq,
  inArray,
  isNotNull,
  or,
  sql,
  type SQL,
} from "drizzle-orm";
import { unstable_cache } from "next/cache";
import { alias } from "drizzle-orm/pg-core";
import { db } from "@/db";
import { games, teams } from "@/db/schema";
import { conferenceTypesForSport, slugToSport } from "@/lib/sports";

export const PAGE_SIZE = 24;

export type SortField = "date" | "excitement" | "rank";

// Team rows joined twice — once as home, once as away.
export const homeTeam = alias(teams, "home_team");
export const awayTeam = alias(teams, "away_team");

// Week numbers only apply to non-postseason games; postseason games are
// grouped under the single "Postseason" week choice for every sport.
const isPostseason = eq(games.type, "postseason");
const notPostseason = sql`${games.type} is distinct from 'postseason'`;

// Flattened game shape the UI consumes (team attributes come from the join).
export const gameColumns = {
  id: games.id,
  externalId: games.externalId,
  name: games.name,
  season: games.season,
  week: games.week,
  type: games.type,
  gameDate: games.gameDate,
  location: games.location,
  homePoints: games.homePoints,
  awayPoints: games.awayPoints,
  homeLineScores: games.homeLineScores,
  awayLineScores: games.awayLineScores,
  homeTeamStats: games.homeTeamStats,
  awayTeamStats: games.awayTeamStats,
  gameLeaders: games.gameLeaders,
  homeRank: games.homeRank,
  awayRank: games.awayRank,
  homeRecord: games.homeRecord,
  awayRecord: games.awayRecord,
  overtime: games.overtime,
  excitementIndex: games.excitementIndex,
  thumbnailUrl: games.thumbnailUrl,
  videoId: games.videoId,
  highlightsValid: games.highlightsValid,
  highlightsChecked: games.highlightsChecked,
  betterVideoId: games.betterVideoId,
  reason: games.reason,
  reviewStatus: games.reviewStatus,
  modified: games.modified,
  homeTeamId: games.homeTeamId,
  awayTeamId: games.awayTeamId,
  homeTeamName: homeTeam.name,
  awayTeamName: awayTeam.name,
  homeLogoUrl: homeTeam.logoUrl,
  awayLogoUrl: awayTeam.logoUrl,
  homeConference: homeTeam.conference,
  awayConference: awayTeam.conference,
  homeConferenceLogoUrl: homeTeam.conferenceLogoUrl,
  awayConferenceLogoUrl: awayTeam.conferenceLogoUrl,
  homeConferenceType: homeTeam.conferenceType,
  awayConferenceType: awayTeam.conferenceType,
  homeTeamColor: homeTeam.color,
  awayTeamColor: awayTeam.color,
  // Badge sport label derives from the home team's division.
  conferenceType: homeTeam.conferenceType,
};

export type GameView = {
  id: number;
  externalId: string | null;
  name: string | null;
  season: string | null;
  week: number | null;
  type: string | null;
  gameDate: Date | string | null;
  location: string | null;
  homePoints: number | null;
  awayPoints: number | null;
  homeLineScores: number[] | null;
  awayLineScores: number[] | null;
  homeTeamStats: Record<string, number | null> | null;
  awayTeamStats: Record<string, number | null> | null;
  gameLeaders: Record<string, unknown> | null;
  homeRank: number | null;
  awayRank: number | null;
  homeRecord: string | null;
  awayRecord: string | null;
  overtime: boolean | null;
  excitementIndex: string | null;
  thumbnailUrl: string | null;
  videoId: string | null;
  highlightsValid: boolean | null;
  highlightsChecked: boolean | null;
  betterVideoId: string | null;
  reason: string | null;
  reviewStatus: string | null;
  modified: Date | string | null;
  homeTeamId: number | null;
  awayTeamId: number | null;
  homeTeamName: string | null;
  awayTeamName: string | null;
  homeLogoUrl: string | null;
  awayLogoUrl: string | null;
  homeConference: string | null;
  awayConference: string | null;
  homeConferenceLogoUrl: string | null;
  awayConferenceLogoUrl: string | null;
  homeConferenceType: string | null;
  awayConferenceType: string | null;
  homeTeamColor: string | null;
  awayTeamColor: string | null;
  conferenceType: string | null;
};

export type GameFilters = {
  sportLabel: string | null;
  teams: string[];
  season: string;
  conference: string;
  division: string; // "top25" | "FBS" | "FCS" | ""
  weeks: string[]; // week numbers as strings and/or "postseason"
  highlights: string; // "with" | "without" | "checked" | ""
  sort: SortField;
  dir: "asc" | "desc";
  page: number;
};

const SORT_FIELDS: SortField[] = ["date", "excitement", "rank"];

function splitList(value: string | null): string[] {
  return (value ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function parseFilters(p: URLSearchParams): GameFilters {
  const sortParam = p.get("sort") ?? "date";
  const dirParam = p.get("dir") ?? "asc";
  const highlightsParam = p.get("highlights") ?? "";
  return {
    sportLabel: slugToSport(p.get("sport") ?? ""),
    teams: splitList(p.get("team")),
    season: p.get("season") ?? "",
    conference: p.get("conference") ?? "",
    division: p.get("division") ?? "",
    weeks: splitList(p.get("week")),
    highlights: ["with", "without", "checked"].includes(highlightsParam)
      ? highlightsParam
      : "",
    sort: (SORT_FIELDS as string[]).includes(sortParam)
      ? (sortParam as SortField)
      : "date",
    dir: dirParam === "asc" ? "asc" : "desc",
    page: Math.max(1, Number(p.get("page")) || 1),
  };
}

export async function loadDefaultSeasonAndWeek(
  sportTypes: string[],
): Promise<{ season: string | null; week: string | null }> {
  return cachedDefaultSeasonAndWeek(sportTypes.join("|"));
}

const cachedDefaultSeasonAndWeek = unstable_cache(
  async (sportTypesKey: string): Promise<{ season: string | null; week: string | null }> => {
    const sportTypes = sportTypesKey.split("|").filter(Boolean);
    const cutoff = new Date().toISOString();
    const rows = await db
      .select({ season: games.season, week: games.week, type: games.type })
      .from(games)
      .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
      .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
      .where(
        and(
          or(
            inArray(homeTeam.conferenceType, sportTypes),
            inArray(awayTeam.conferenceType, sportTypes),
          )!,
          sql`${games.gameDate} is not null`,
          sql`${games.gameDate} <= ${cutoff}`,
        ),
      )
      .orderBy(desc(games.gameDate), desc(games.id))
      .limit(1);

    const season = rows[0]?.season ?? null;
    const week =
      rows[0]?.type === "postseason" ? "postseason" : (rows[0]?.week ?? null);

    return {
      season,
      week: week == null ? null : String(week),
    };
  },
  ["default-season-week-regular-weeks"],
  { revalidate: 900 },
);

function buildWhere(f: GameFilters, sportTypes: string[]): SQL {
  const conditions: SQL[] = [
    or(
      inArray(homeTeam.conferenceType, sportTypes),
      inArray(awayTeam.conferenceType, sportTypes),
    )!,
  ];

  if (f.teams.length) {
    conditions.push(
      or(inArray(homeTeam.name, f.teams), inArray(awayTeam.name, f.teams))!,
    );
  }
  if (f.season) conditions.push(eq(games.season, f.season));
  if (f.conference) {
    conditions.push(
      or(
        eq(homeTeam.conference, f.conference),
        eq(awayTeam.conference, f.conference),
      )!,
    );
  }
  if (f.division === "top25") {
    conditions.push(
      or(between(games.homeRank, 1, 25), between(games.awayRank, 1, 25))!,
    );
  } else if (f.division === "FBS" || f.division === "FCS") {
    // Show the game when either team belongs to the division.
    conditions.push(
      or(
        eq(homeTeam.conferenceType, f.division),
        eq(awayTeam.conferenceType, f.division),
      )!,
    );
  }

  const weekNums = f.weeks
    .filter((w) => /^\d+$/.test(w))
    .map((w) => Number(w));
  const wantPostseason = f.weeks.includes("postseason");
  if (weekNums.length || wantPostseason) {
    const parts: SQL[] = [];
    if (weekNums.length) {
      parts.push(and(inArray(games.week, weekNums), notPostseason)!);
    }
    if (wantPostseason) parts.push(isPostseason);
    conditions.push(or(...parts)!);
  }

  if (f.highlights === "with") {
    conditions.push(sql`${games.videoId} is not null`);
  } else if (f.highlights === "without") {
    conditions.push(sql`${games.videoId} is null`);
  } else if (f.highlights === "checked") {
    conditions.push(eq(games.highlightsChecked, true));
  }

  return and(...conditions)!;
}

function buildOrderBy(f: GameFilters): SQL {
  const expr: SQL =
    f.sort === "excitement"
      ? sql`${games.excitementIndex}`
      : f.sort === "rank"
        ? // Best (lowest) rank of either team; unranked sinks to the bottom.
          sql`least(coalesce(${games.homeRank}, 999), coalesce(${games.awayRank}, 999))`
        : sql`${games.gameDate}`;
  const dir: SQL = f.dir === "asc" ? sql`asc` : sql`desc`;
  return sql`${expr} ${dir} nulls last, ${games.id} desc`;
}

function serializeGameFilters(f: GameFilters, extra: Record<string, unknown> = {}) {
  return JSON.stringify({
    sportLabel: f.sportLabel,
    teams: [...f.teams].sort(),
    season: f.season,
    conference: f.conference,
    division: f.division,
    weeks: [...f.weeks].sort(),
    highlights: f.highlights,
    sort: f.sort,
    dir: f.dir,
    page: f.page,
    ...extra,
  });
}

const cachedFetchGames = unstable_cache(
  async (payload: string): Promise<{ rows: GameView[]; total: number; hasMore: boolean }> => {
    const { filters } = JSON.parse(payload) as { filters: GameFilters };
    if (!filters.sportLabel) return { rows: [], total: 0, hasMore: false };
    const sportTypes = conferenceTypesForSport(filters.sportLabel);
    const where = buildWhere(filters, sportTypes);

    const [rows, countRes] = await Promise.all([
      db
        .select(gameColumns)
        .from(games)
        .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
        .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
        .where(where)
        .orderBy(buildOrderBy(filters))
        .limit(PAGE_SIZE)
        .offset((filters.page - 1) * PAGE_SIZE),
      db
        .select({ n: sql<number>`count(*)::int` })
        .from(games)
        .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
        .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
        .where(where),
    ]);

    const total = countRes[0]?.n ?? 0;
    return {
      rows: rows as GameView[],
      total,
      hasMore: filters.page * PAGE_SIZE < total,
    };
  },
  ["games-list-regular-weeks"],
  { revalidate: 60 },
);

export async function fetchGames(
  f: GameFilters,
): Promise<{ rows: GameView[]; total: number; hasMore: boolean }> {  if (!f.sportLabel) return { rows: [], total: 0, hasMore: false };
  return cachedFetchGames(JSON.stringify({ filters: f }));
}

// Games shown on the review queue. By default only unchecked highlights
// (Highlights checked = false); showAll drops that restriction so already
// checked games can be revisited. Honors the standard grid filters.
export async function fetchReviewGames(
  f: GameFilters,
  opts: { showAll: boolean; limit?: number },
): Promise<{ rows: GameView[]; total: number }> {
  if (!f.sportLabel) return { rows: [], total: 0 };
  const sportTypes = conferenceTypesForSport(f.sportLabel);
  const base = buildWhere(f, sportTypes);
  const where = opts.showAll
    ? base
    : and(base, eq(games.highlightsChecked, false))!;

  const [rows, countRes] = await Promise.all([
    db
      .select(gameColumns)
      .from(games)
      .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
      .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
      .where(where)
      .orderBy(buildOrderBy(f))
      .limit(opts.limit ?? 120),
    db
      .select({ n: sql<number>`count(*)::int` })
      .from(games)
      .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
      .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
      .where(where),
  ]);

  return { rows: rows as GameView[], total: countRes[0]?.n ?? 0 };
}

export async function fetchGameById(id: number): Promise<GameView | null> {  const rows = await db
    .select(gameColumns)
    .from(games)
    .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
    .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
    .where(eq(games.id, id))
    .limit(1);
  return (rows[0] as GameView) ?? null;
}

export type FormResult = {
  gameId: number;
  result: "W" | "L" | "T";
  teamPoints: number;
  oppPoints: number;
  opponent: string | null;
  opponentId: number | null;
  opponentLogoUrl: string | null;
  home: boolean;
  week: number | null;
  date: Date | string | null;
};

export type TeamForm = { home: FormResult[]; away: FormResult[] };

// A team's last (up to 5) completed results in the same season, up to and
// including this game's date. Never crosses into another season.
async function recentResults(
  teamId: number,
  season: string,
  onOrBeforeDate: string,
  excludeGameId: number,
): Promise<FormResult[]> {
  const rows = await db
    .select({
      id: games.id,
      week: games.week,
      gameDate: games.gameDate,
      homeTeamId: games.homeTeamId,
      awayTeamId: games.awayTeamId,
      homePoints: games.homePoints,
      awayPoints: games.awayPoints,
      homeName: homeTeam.name,
      awayName: awayTeam.name,
      homeLogoUrl: homeTeam.logoUrl,
      awayLogoUrl: awayTeam.logoUrl,
    })
    .from(games)
    .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
    .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
    .where(
      and(
        eq(games.season, season),
        or(eq(games.homeTeamId, teamId), eq(games.awayTeamId, teamId)),
        sql`${games.homePoints} is not null`,
        sql`${games.awayPoints} is not null`,
        sql`${games.gameDate} <= ${onOrBeforeDate}`,
        sql`${games.id} <> ${excludeGameId}`,
      ),
    )
    .orderBy(desc(games.gameDate), desc(games.id))
    .limit(5);

  // Query is newest-first; reverse so display reads oldest -> newest.
  return rows.reverse().map((r) => {
    const isHome = r.homeTeamId === teamId;
    const teamPoints = (isHome ? r.homePoints : r.awayPoints) ?? 0;
    const oppPoints = (isHome ? r.awayPoints : r.homePoints) ?? 0;
    const result: "W" | "L" | "T" =
      teamPoints > oppPoints ? "W" : teamPoints < oppPoints ? "L" : "T";
    return {
      gameId: r.id,
      result,
      teamPoints,
      oppPoints,
      opponent: isHome ? r.awayName : r.homeName,
      opponentId: isHome ? r.awayTeamId : r.homeTeamId,
      opponentLogoUrl: isHome ? r.awayLogoUrl : r.homeLogoUrl,
      home: isHome,
      week: r.week,
      date: r.gameDate,
    };
  });
}

export async function fetchTeamForm(gameId: number): Promise<TeamForm> {
  const g = (
    await db
      .select({
        season: games.season,
        gameDate: games.gameDate,
        homeTeamId: games.homeTeamId,
        awayTeamId: games.awayTeamId,
      })
      .from(games)
      .where(eq(games.id, gameId))
      .limit(1)
  )[0];
  if (!g || !g.season) return { home: [], away: [] };
  const raw = g.gameDate ?? new Date();
  const date =
    typeof raw === "string" ? raw : (raw as Date).toISOString();
  const [home, away] = await Promise.all([
    g.homeTeamId
      ? recentResults(g.homeTeamId, g.season, date, gameId)
      : Promise.resolve([]),
    g.awayTeamId
      ? recentResults(g.awayTeamId, g.season, date, gameId)
      : Promise.resolve([]),
  ]);
  return { home, away };
}

export type WeekOptions = {
  weeks: number[];
  hasPostseason: boolean;
};

export type FilterOptions = WeekOptions & {
  seasons: string[];
  // Week choices per season; the top-level weeks cover all seasons.
  bySeason: Record<string, WeekOptions>;
};

// Season/week choices limited to the current sport.
export async function loadFilterOptions(
  sportTypes: string[],
): Promise<FilterOptions> {
  return cachedFilterOptions(sportTypes.join("|"));
}

const cachedFilterOptions = unstable_cache(
  async (sportTypesKey: string): Promise<FilterOptions> => {
    const sportTypes = sportTypesKey.split("|").filter(Boolean);
    const gameScope = or(
      inArray(homeTeam.conferenceType, sportTypes),
      inArray(awayTeam.conferenceType, sportTypes),
    );

    const [seasons, weeks, post] = await Promise.all([
      db
        .selectDistinct({ v: games.season })
        .from(games)
        .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
        .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
        .where(gameScope)
        .orderBy(desc(games.season)),
      db
        .selectDistinct({ season: games.season, week: games.week })
        .from(games)
        .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
        .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
        .where(and(gameScope, notPostseason, isNotNull(games.week))),
      db
        .selectDistinct({ season: games.season })
        .from(games)
        .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
        .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
        .where(and(gameScope, isPostseason)),
    ]);

    const bySeason: Record<string, WeekOptions> = {};
    const forSeason = (season: string) =>
      (bySeason[season] ??= { weeks: [], hasPostseason: false });
    const allWeeks = new Set<number>();
    for (const { season, week } of weeks) {
      if (week == null) continue;
      allWeeks.add(week);
      if (season) forSeason(season).weeks.push(week);
    }
    for (const { season } of post) {
      if (season) forSeason(season).hasPostseason = true;
    }
    for (const opts of Object.values(bySeason)) {
      opts.weeks.sort((a, b) => a - b);
    }

    return {
      seasons: seasons
        .map((r) => r.v)
        .filter((v): v is string => Boolean(v)),
      weeks: [...allWeeks].sort((a, b) => a - b),
      hasPostseason: post.length > 0,
      bySeason,
    };
  },
  ["filter-options-weeks-by-season"],
  { revalidate: 1800 },
);
