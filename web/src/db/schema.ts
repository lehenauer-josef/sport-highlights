import {
  boolean,
  integer,
  jsonb,
  numeric,
  pgTable,
  serial,
  text,
  timestamp,
} from "drizzle-orm/pg-core";

// Canonical team data (name, logo, conference, division), synced from the
// Airtable "Teams" table. Games reference these rows instead of duplicating
// team attributes on every game.
export const teams = pgTable("teams", {
  id: serial("id").primaryKey(),
  airtableId: text("airtable_id").notNull().unique(),
  externalId: text("external_id"),
  name: text("name"),
  mascot: text("mascot"),
  conference: text("conference"),
  conferenceType: text("conference_type"),
  color: text("color"),
  logoUrl: text("logo_url"),
  conferenceLogoUrl: text("conference_logo_url"),
  // Downloaded image bytes (base64) so logos survive Airtable URL expiry.
  logoData: text("logo_data"),
  logoMime: text("logo_mime"),
  conferenceLogoData: text("conference_logo_data"),
  conferenceLogoMime: text("conference_logo_mime"),
  syncedAt: timestamp("synced_at", { withTimezone: true }).defaultNow(),
});

export type Team = typeof teams.$inferSelect;

// One row per game. Team attributes are looked up via home/away team ids;
// only game-specific data (rank, record, points, video) lives here.
export const games = pgTable("games", {
  id: serial("id").primaryKey(),
  airtableId: text("airtable_id").notNull().unique(),
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
});

export type Game = typeof games.$inferSelect;
