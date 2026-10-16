import { redirect } from "next/navigation";
import {
  conferenceTypesForSport,
  DEFAULT_REVIEW_SPORT,
  REVIEW_SPORTS,
  slugToSport,
  sportToSlug,
} from "@/lib/sports";
import {
  fetchReviewGames,
  loadDefaultSeasonAndWeek,
  loadFilterOptions,
  parseFilters,
} from "@/lib/games";
import { fallbackWeek, weeksAvailable } from "@/lib/weeks";
import { Filters } from "@/components/Filters";
import { ReviewCard } from "@/components/ReviewCard";
import { ReviewFilter } from "@/components/ReviewFilter";
import { ReviewShowAll } from "@/components/ReviewShowAll";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

// Next's searchParams object -> URLSearchParams.
function toParams(
  sp: Record<string, string | string[] | undefined>,
): URLSearchParams {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) {
    if (v == null || k === "conference") continue;
    u.set(k, Array.isArray(v) ? (v[0] ?? "") : v);
  }
  return u;
}

// Games needing highlight review, scoped to the selected sport and the shared
// grid filters. Defaults to unchecked highlights; "Show all" reveals the rest.
export default async function ReviewPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const sp = await searchParams;
  const rawSport = Array.isArray(sp.sport) ? sp.sport[0] : sp.sport;
  // Accept the tab label ("NBA") as well as the slug ("nba") that this page
  // writes into its own redirects.
  const requested = rawSport
    ? REVIEW_SPORTS.includes(rawSport)
      ? rawSport
      : slugToSport(rawSport)
    : null;
  const sport =
    requested && REVIEW_SPORTS.includes(requested)
      ? requested
      : DEFAULT_REVIEW_SPORT;
  const sportSlug = sportToSlug(sport) ?? "college-football";
  const types = conferenceTypesForSport(sport);
  const showAll = (Array.isArray(sp.all) ? sp.all[0] : sp.all) === "1";

  const params = toParams(sp);
  params.set("sport", sportSlug);

  const [options, defaultRange] = await Promise.all([
    loadFilterOptions(types),
    loadDefaultSeasonAndWeek(types),
  ]);

  if (!params.has("season") && defaultRange.season) {
    params.set("season", defaultRange.season);
  }
  if (!params.has("week") && defaultRange.week) {
    params.set("week", defaultRange.week);
  }
  if (!params.has("sort")) {
    params.set("sort", "date");
  }
  if (!params.has("dir")) {
    params.set("dir", "asc");
  }

  if (
    sp.season == null &&
    sp.week == null &&
    sp.sort == null &&
    sp.dir == null &&
    defaultRange.season &&
    defaultRange.week
  ) {
    redirect(`/review?${params.toString()}`);
  }

  // A missing week or one without games in the chosen season (e.g. an old
  // link) falls back to "All" regular-season (else postseason) games; the
  // default week is known to have games.
  const season = params.get("season") ?? "";
  const week = params.get("week") ?? "";
  const weeks = week.split(",").map((w) => w.trim()).filter(Boolean);
  const isDefaultWeek =
    season === defaultRange.season && week === defaultRange.week;
  if (
    !isDefaultWeek &&
    (!weeks.length || !weeksAvailable(options, season, weeks))
  ) {
    const fallback = fallbackWeek(options, season);
    if (fallback && fallback !== week) {
      params.set("week", fallback);
      redirect(`/review?${params.toString()}`);
    }
  }

  const filters = parseFilters(params);
  filters.sportLabel = sport;

  const [{ rows, total }] = await Promise.all([
    fetchReviewGames(filters, { showAll }),
  ]);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Review queue</h1>
        <div className="flex items-center gap-4">
          <ReviewShowAll showAll={showAll} />
          <span className="text-sm text-white/50">
            {total} {showAll ? "games" : "to check"}
          </span>
        </div>
      </div>

      <ReviewFilter active={sport} />

      <Filters
        options={options}
        sportSlug={sportSlug}
        showDivision={types.length > 1}
      />

      {rows.length === 0 ? (
        <p className="py-16 text-center text-white/40">
          {showAll ? "No games match these filters." : "Nothing to review. 🎉"}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {rows.map((game) => (
            <ReviewCard key={game.id} game={game} />
          ))}
        </div>
      )}
    </div>
  );
}
