import type { FilterOptions, WeekOptions } from "@/lib/games";
import { groupFilterRounds } from "@/lib/rounds";

// Week choices that have games in the given season ("" = all seasons).
export function weekOptionsFor(
  options: FilterOptions,
  season: string,
): WeekOptions {
  if (!season) return options;
  return (
    options.bySeason[season] ?? { weeks: [], hasPostseason: false, rounds: [] }
  );
}

// True when every selected week (a number, "regular", "postseason" or a
// postseason round key) has games in the season. An empty selection is always
// available.
export function weeksAvailable(
  options: FilterOptions,
  season: string,
  weeks: string[],
): boolean {
  const opts = weekOptionsFor(options, season);
  return weeks.every((w) => {
    if (w === "regular") return opts.weeks.length > 0;
    if (w === "postseason") return opts.hasPostseason;
    if (/^\d+$/.test(w)) return opts.weeks.includes(Number(w));
    const group = groupFilterRounds(w);
    if (group) return group.some((r) => opts.rounds.includes(r));
    return opts.rounds.includes(w);
  });
}

// Week choice to use when none (or an unavailable one) is selected: all
// regular-season games, else all postseason games (the first sub-group for
// sports that split their postseason); null if the season is empty.
export function fallbackWeek(
  options: FilterOptions,
  season: string,
): string | null {
  const opts = weekOptionsFor(options, season);
  if (opts.weeks.length) return "regular";
  if (!opts.hasPostseason) return null;
  return (
    ["postseason-fbs", "postseason-fcs"].find((value) =>
      groupFilterRounds(value)?.some((r) => opts.rounds.includes(r)),
    ) ?? "postseason"
  );
}
