import { sportForConferenceType } from "@/lib/sports";

export type RoundDef = {
  key: string;
  label: string;
  // Sub-group in the week filter (college football splits FBS and FCS).
  group?: "FBS" | "FCS";
};

// Postseason rounds per sport, in bracket order. Keys match
// games.postseason_round (set by the importers) and are used as week filter
// values alongside week numbers, "regular", "postseason" and the
// "postseason-<group>" values below.
export const POSTSEASON_ROUNDS: Record<string, RoundDef[]> = {
  "College Football": [
    { key: "bowl", label: "Bowl Games", group: "FBS" },
    { key: "cfp-first-round", label: "CFP 1st Round", group: "FBS" },
    { key: "cfp-quarterfinal", label: "CFP Quarterfinals", group: "FBS" },
    { key: "cfp-semifinal", label: "CFP Semifinals", group: "FBS" },
    { key: "cfp-championship", label: "National Championship", group: "FBS" },
    { key: "fcs-bowl", label: "Bowl Games", group: "FCS" },
    { key: "fcs-first-round", label: "FCS 1st Round", group: "FCS" },
    { key: "fcs-second-round", label: "FCS 2nd Round", group: "FCS" },
    { key: "fcs-quarterfinal", label: "FCS Quarterfinals", group: "FCS" },
    { key: "fcs-semifinal", label: "FCS Semifinals", group: "FCS" },
    { key: "fcs-championship", label: "FCS Championship", group: "FCS" },
  ],
  NFL: [
    { key: "wild-card", label: "Wild Card Playoffs" },
    { key: "divisional", label: "Divisional Playoffs" },
    { key: "conference", label: "Conference Championship" },
    { key: "super-bowl", label: "Super Bowl" },
  ],
  NHL: [
    { key: "round-1", label: "1st Round" },
    { key: "round-2", label: "2nd Round" },
    { key: "conference-finals", label: "Conference Finals" },
    { key: "finals", label: "Stanley Cup Final" },
  ],
  NBA: [
    { key: "play-in", label: "Play-In" },
    { key: "round-1", label: "1st Round" },
    { key: "round-2", label: "2nd Round" },
    { key: "conference-finals", label: "Conference Finals" },
    { key: "finals", label: "NBA Finals" },
  ],
};

const ALL_ROUND_KEYS = new Set(
  Object.values(POSTSEASON_ROUNDS).flatMap((rounds) => rounds.map((r) => r.key)),
);

export function isRoundKey(value: string): boolean {
  return ALL_ROUND_KEYS.has(value);
}

// Week filter values selecting every round of a sub-group
// ("postseason-fbs" -> all FBS bowl and CFP games).
const GROUP_FILTERS: Record<string, string[]> = {};
for (const rounds of Object.values(POSTSEASON_ROUNDS)) {
  for (const r of rounds) {
    if (!r.group) continue;
    (GROUP_FILTERS[`postseason-${r.group.toLowerCase()}`] ??= []).push(r.key);
  }
}

// Round keys selected by a "postseason-<group>" filter value, else null.
export function groupFilterRounds(value: string): string[] | null {
  return GROUP_FILTERS[value] ?? null;
}

// Postseason groups of the week filter for a sport: one "Postseason" group
// (value "postseason"), or one per sub-group ("Postseason – FBS", value
// "postseason-fbs"). Only rounds in `available` are listed; empty groups are
// dropped.
export function postseasonGroups(
  sport: string | null,
  available: string[],
): { label: string; value: string; rounds: RoundDef[] }[] {
  const have = new Set(available);
  const rounds = (POSTSEASON_ROUNDS[sport ?? ""] ?? []).filter((r) =>
    have.has(r.key),
  );
  const groups = [...new Set(rounds.map((r) => r.group))];
  return groups.map((group) =>
    group
      ? {
          label: `Postseason – ${group}`,
          value: `postseason-${group.toLowerCase()}`,
          rounds: rounds.filter((r) => r.group === group),
        }
      : { label: "Postseason", value: "postseason", rounds },
  );
}

// Display label for a game's week: its round for postseason games
// ("Super Bowl"), "Postseason" when the round is unknown, else "Week N".
export function weekLabel(game: {
  conferenceType: string | null;
  type: string | null;
  week: number | null;
  postseasonRound: string | null;
}): string | null {
  if (game.type === "postseason") {
    const sport = sportForConferenceType(game.conferenceType);
    const round = (POSTSEASON_ROUNDS[sport ?? ""] ?? []).find(
      (r) => r.key === game.postseasonRound,
    );
    return round?.label ?? "Postseason";
  }
  return game.week ? `Week ${game.week}` : null;
}
