import type { FilterOptions, WeekOptions } from "@/lib/games";

// Week choices that have games in the given season ("" = all seasons).
export function weekOptionsFor(
  options: FilterOptions,
  season: string,
): WeekOptions {
  if (!season) return options;
  return options.bySeason[season] ?? { weeks: [], hasPostseason: false };
}

// True when every selected week ("postseason" or a number) has games in the
// season. An empty selection ("All weeks") is always available.
export function weeksAvailable(
  options: FilterOptions,
  season: string,
  weeks: string[],
): boolean {
  const opts = weekOptionsFor(options, season);
  return weeks.every((w) =>
    w === "postseason" ? opts.hasPostseason : opts.weeks.includes(Number(w)),
  );
}
