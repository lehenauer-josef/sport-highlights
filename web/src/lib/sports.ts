// Groups Airtable "Conference Type" values into the sports shown in the UI.
// FCS + FBS are both college football; Soccer is excluded entirely.
export const SPORT_GROUPS: Record<string, string[]> = {
  "College Football": ["FCS", "FBS"],
  NFL: ["NFL"],
  NHL: ["NHL"],
  NBA: ["NBA"],
};

export const EXCLUDED_CONFERENCE_TYPES = ["Soccer"];

const SHORT_LABELS: Record<string, string> = {
  "College Football": "CFB",
};

const CONFERENCE_TYPE_TO_SPORT: Record<string, string> = Object.fromEntries(
  Object.entries(SPORT_GROUPS).flatMap(([sport, types]) =>
    types.map((t) => [t, sport]),
  ),
);

export function sportForConferenceType(ct: string | null): string | null {
  if (!ct) return null;
  return CONFERENCE_TYPE_TO_SPORT[ct] ?? ct;
}

export function shortSportLabel(ct: string | null): string | null {
  const sport = sportForConferenceType(ct);
  if (!sport) return null;
  return SHORT_LABELS[sport] ?? sport;
}

export function conferenceTypesForSport(sport: string): string[] {
  return SPORT_GROUPS[sport] ?? [sport];
}

// Top-level sport tabs, in nav order, with their URL slugs.
export const SPORT_TABS: { slug: string; label: string }[] = [
  { slug: "college-football", label: "College Football" },
  { slug: "nfl", label: "NFL" },
  { slug: "nhl", label: "NHL" },
  { slug: "nba", label: "NBA" },
];

export function slugToSport(slug: string): string | null {
  return SPORT_TABS.find((t) => t.slug === slug)?.label ?? null;
}

export function sportToSlug(label: string): string | null {
  return SPORT_TABS.find((t) => t.label === label)?.slug ?? null;
}

// Sports offered on the review queue, in tab order (CFB is the default).
export const REVIEW_SPORT_TABS: { label: string; short: string }[] = [
  { label: "College Football", short: "CFB" },
  { label: "NFL", short: "NFL" },
  { label: "NBA", short: "NBA" },
  { label: "NHL", short: "NHL" },
];

export const REVIEW_SPORTS = REVIEW_SPORT_TABS.map((t) => t.label);
export const DEFAULT_REVIEW_SPORT = "College Football";


// Collapse a list of raw conference types into the deduped, ordered sport list.
export function sportsFromConferenceTypes(types: (string | null)[]): string[] {
  const order = Object.keys(SPORT_GROUPS);
  const seen = new Set<string>();
  for (const t of types) {
    if (!t || EXCLUDED_CONFERENCE_TYPES.includes(t)) continue;
    seen.add(sportForConferenceType(t)!);
  }
  const known = order.filter((s) => seen.has(s));
  const extra = [...seen].filter((s) => !order.includes(s)).sort();
  return [...known, ...extra];
}
