import {
  boolean,
  integer,
  index,
  jsonb,
  numeric,
  pgTable,
  serial,
  text,
  timestamp,
  uniqueIndex,
} from "drizzle-orm/pg-core";

// Canonical team data (name, logo, conference, division). Teams are maintained in
// the database; NBA teams are synced from ESPN by import_nba_games.py.
// Games reference these rows instead of duplicating team attributes on every game.
export const teams = pgTable("teams", {
  id: serial("id").primaryKey(),
  // Unique import key, e.g. "nba:<espn id>"; legacy rows keep their original key.
  sourceId: text("source_id").notNull().unique(),
  externalId: text("external_id"),
  name: text("name"),
  mascot: text("mascot"),
  conference: text("conference"),
  conferenceType: text("conference_type"),
  color: text("color"),
  logoUrl: text("logo_url"),
  conferenceLogoUrl: text("conference_logo_url"),
  // Downloaded image bytes (base64) so logos never depend on expiring image URLs.
  logoData: text("logo_data"),
  logoMime: text("logo_mime"),
  conferenceLogoData: text("conference_logo_data"),
  conferenceLogoMime: text("conference_logo_mime"),
  syncedAt: timestamp("synced_at", { withTimezone: true }).defaultNow(),
}, (table) => ({
  teamsConferenceTypeIdx: index("teams_conference_type_idx").on(table.conferenceType),
  teamsConferenceIdx: index("teams_conference_idx").on(table.conference),
  teamsNameIdx: index("teams_name_idx").on(table.name),
  // ESPN ids repeat across sports (12 is both the LA Clippers and Arizona), so a
  // team is identified by sport + external id.
  teamsConferenceTypeExternalIdKey: uniqueIndex("teams_conference_type_external_id_key").on(
    table.conferenceType,
    table.externalId,
  ),
}));

export type Team = typeof teams.$inferSelect;

// One row per game. Team attributes are looked up via home/away team ids;
// only game-specific data (rank, record, points, video) lives here.
export const games = pgTable("games", {
  id: serial("id").primaryKey(),
  // Unique import key, e.g. "nfl:<game id>", "nhl:<game id>", "cfbd:<game id>".
  sourceId: text("source_id").notNull().unique(),
  externalId: text("external_id"),
  name: text("name"),

  season: text("season"),
  week: integer("week"),
  type: text("type"),
  gameDate: timestamp("game_date", { withTimezone: true }),
  location: text("location"),

  homeTeamId: integer("home_team_id").references(() => teams.id),
  awayTeamId: integer("away_team_id").references(() => teams.id),

  homePoints: integer("home_points"),
  awayPoints: integer("away_points"),
  homeLineScores: integer("home_line_scores").array(),
  awayLineScores: integer("away_line_scores").array(),
  homeTeamStats: jsonb("home_team_stats"),
  awayTeamStats: jsonb("away_team_stats"),
  gameLeaders: jsonb("game_leaders"),
  homeRank: integer("home_rank"),
  awayRank: integer("away_rank"),
  homeRecord: text("home_record"),
  awayRecord: text("away_record"),
  overtime: boolean("overtime").default(false),
  excitementIndex: numeric("excitement_index"),

  thumbnailUrl: text("thumbnail_url"),

  videoId: text("video_id"),
  highlightsValid: boolean("highlights_valid").default(false),
  highlightsChecked: boolean("highlights_checked").default(false),
  betterVideoId: text("better_video_id"),
  reason: text("reason"),
  reviewStatus: text("review_status").default("pending"),

  modified: timestamp("modified", { withTimezone: true }),
  syncedAt: timestamp("synced_at", { withTimezone: true }).defaultNow(),
}, (table) => ({
  gamesSeasonDateIdx: index("games_season_date_idx").on(table.season, table.gameDate),
  gamesGameDateIdx: index("games_game_date_idx").on(table.gameDate),
  gamesHomeTeamIdx: index("games_home_team_idx").on(table.homeTeamId),
  gamesAwayTeamIdx: index("games_away_team_idx").on(table.awayTeamId),
  gamesWeekIdx: index("games_week_idx").on(table.week),
  gamesTypeIdx: index("games_type_idx").on(table.type),
  gamesHighlightsCheckedIdx: index("games_highlights_checked_idx").on(table.highlightsChecked),
  gamesVideoIdIdx: index("games_video_id_idx").on(table.videoId),
}));

export type Game = typeof games.$inferSelect;
