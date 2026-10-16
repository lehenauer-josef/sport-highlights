import { notFound, redirect } from "next/navigation";
import { Filters } from "@/components/Filters";
import { GameGrid } from "@/components/GameGrid";
import { GameModal } from "@/components/GameModal";
import {
  fetchGames,
  loadDefaultSeasonAndWeek,
  loadFilterOptions,
  parseFilters,
} from "@/lib/games";
import { conferenceTypesForSport, slugToSport } from "@/lib/sports";
import { fallbackWeek, weeksAvailable } from "@/lib/weeks";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

// Next's searchParams object -> URLSearchParams, plus the sport from the path.
function toParams(
  sp: Record<string, string | string[] | undefined>,
  sportSlug: string,
): URLSearchParams {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) {
    if (v == null || k === "conference") continue;
    u.set(k, Array.isArray(v) ? (v[0] ?? "") : v);
  }
  u.set("sport", sportSlug);
  return u;
}

export default async function SportPage({
  params,
  searchParams,
}: {
  params: Promise<{ sport: string }>;
  searchParams: SearchParams;
}) {
  const { sport: slug } = await params;
  const sportLabel = slugToSport(slug);
  if (!sportLabel) notFound();

  const sportTypes = conferenceTypesForSport(sportLabel);
  const sp = await searchParams;
  const searchParamsObj = toParams(sp, slug);

  const [options, defaultRange] = await Promise.all([
    loadFilterOptions(sportTypes),
    loadDefaultSeasonAndWeek(sportTypes),
  ]);

  if (!searchParamsObj.has("season") && defaultRange.season) {
    searchParamsObj.set("season", defaultRange.season);
  }
  if (!searchParamsObj.has("week") && defaultRange.week) {
    searchParamsObj.set("week", defaultRange.week);
  }
  if (!searchParamsObj.has("sort")) {
    searchParamsObj.set("sort", "date");
  }
  if (!searchParamsObj.has("dir")) {
    searchParamsObj.set("dir", "asc");
  }

  if (
    sp.season == null &&
    sp.week == null &&
    sp.sort == null &&
    sp.dir == null &&
    defaultRange.season &&
    defaultRange.week
  ) {
    redirect(`/s/${slug}?${searchParamsObj.toString()}`);
  }

  // A missing week or one without games in the chosen season (e.g. an old
  // link) falls back to "All" regular-season (else postseason) games; the
  // default week is known to have games.
  const season = searchParamsObj.get("season") ?? "";
  const week = searchParamsObj.get("week") ?? "";
  const weeks = week.split(",").map((w) => w.trim()).filter(Boolean);
  const isDefaultWeek =
    season === defaultRange.season && week === defaultRange.week;
  if (
    !isDefaultWeek &&
    (!weeks.length || !weeksAvailable(options, season, weeks))
  ) {
    const fallback = fallbackWeek(options, season);
    if (fallback && fallback !== week) {
      searchParamsObj.set("week", fallback);
      redirect(`/s/${slug}?${searchParamsObj.toString()}`);
    }
  }

  const filters = parseFilters(searchParamsObj);

  const [{ rows, total, hasMore }] = await Promise.all([
    fetchGames(filters),
  ]);

  // Querystring the infinite-scroll grid re-uses to fetch further pages.
  // "game" (detail overlay) and "page" must not affect the grid results/key.
  const gridQuery = new URLSearchParams(searchParamsObj);
  gridQuery.delete("page");
  gridQuery.delete("game");

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{sportLabel}</h1>
        <span className="text-sm text-[var(--text-muted)]">{total} games</span>
      </div>

      <Filters
        options={options}
        sportSlug={slug}
        showDivision={sportTypes.length > 1}
      />

      <GameGrid
        key={gridQuery.toString()}
        initial={rows}
        initialHasMore={hasMore}
        query={gridQuery.toString()}
      />

      <GameModal />
    </div>
  );
}
