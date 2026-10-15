"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  formatDate,
  formatDateTime,
  logoSrc,
  youtubeThumb,
  youtubeUrl,
} from "@/lib/format";
import type { FormResult, GameView } from "@/lib/games";
import { shortSportLabel } from "@/lib/sports";
import { setShowResults, useShowResults } from "@/lib/prefs";
import { FormList, loadForm } from "@/components/TeamForm";
import { GameLeaders } from "@/components/GameLeaders";
import { NhlScoring, NhlThreeStars, nhlStory } from "@/components/NhlGameStats";

function TeamRow({
  name,
  rank,
  logo,
  conference,
  conferenceLogo,
  record,
  points,
  lineScores,
  showPoints,
  form,
  quarterScores,
}: {
  name: string | null;
  rank: number | null;
  logo: string | null;
  conference: string | null;
  conferenceLogo: string | null;
  record: string | null;
  points: number | null;
  lineScores: number[] | null;
  showPoints: boolean;
  form: FormResult[] | null;
  quarterScores: boolean;
}) {
  const hasLineScores = quarterScores && Array.isArray(lineScores) && lineScores.length > 0;
  const scoreLabels = ["1", "2", "3", "4"];
  if (hasLineScores && lineScores.length > 4) scoreLabels.push("OT");
  scoreLabels.push("T");

  const scoreCells = hasLineScores
    ? [...lineScores.slice(0, 4), ...(lineScores.length > 4 ? [lineScores.slice(4).reduce((sum, n) => sum + n, 0)] : []), points ?? lineScores.reduce((sum, n) => sum + n, 0)]
    : [];

  const scoreGrid = hasLineScores && (lineScores?.length ?? 0) > 4 ? "grid-cols-6" : "grid-cols-5";

  return (
    <div className="flex items-center gap-3">
      {logo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={logo} alt="" className="h-10 w-10 shrink-0 object-contain" />
      ) : (
        <div className="h-10 w-10 shrink-0 rounded bg-[var(--chip-strong)]" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium text-[var(--text)]">
            {rank ? <span className="text-[var(--text-subtle)]">#{rank} </span> : null}
            {name ?? "TBD"}
            {record ? (
              <span className="ml-1 text-xs font-normal text-[var(--text-muted)]">
                ({record})
              </span>
            ) : null}
          </span>
          {conferenceLogo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={conferenceLogo}
              alt=""
              title={conference ?? "Conference"}
              className="h-4 w-4 shrink-0 object-contain opacity-80"
            />
          ) : null}
        </div>
        <div className="text-xs text-[var(--text-muted)]">{conference ?? ""}</div>
        {form && form.length ? (
          <div className="mt-2">
            <span className="mb-1.5 block text-[10px] uppercase tracking-wide text-[var(--text-subtle)]">
              Last 5
            </span>
            <FormList results={form} />
          </div>
        ) : null}
      </div>
      {showPoints && hasLineScores ? (
        <div className="ml-auto flex shrink-0 flex-col items-end">
          <div className={`grid ${scoreGrid} gap-2 text-center text-[11px] font-medium text-[var(--text-subtle)]`}>
            {scoreLabels.map((label) => (
              <span key={`${name}-${label}`} className="w-6 text-center">
                {label}
              </span>
            ))}
          </div>
          <div className={`mt-1 grid ${scoreGrid} gap-2 text-center text-base font-semibold tabular-nums text-[var(--text)]`}>
            {scoreCells.map((value, index) => (
              <span key={`${name}-cell-${index}`} className="w-6 text-center">
                {value ?? ""}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {!hasLineScores && showPoints && points != null ? (
        <span className="text-2xl font-semibold tabular-nums text-[var(--text)]">{points}</span>
      ) : null}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-[var(--text-subtle)]">
        {label}
      </div>
      <div className="text-sm text-[var(--text)]">{value}</div>
    </div>
  );
}

type TeamStats = Record<string, number | null> | null;

type TeamStatDef = {
  key: string;
  label: string;
  format?: (value: number, stats: TeamStats) => string;
};

const FOOTBALL_STATS: TeamStatDef[] = [
  { key: "passingYards", label: "Pass Yds" },
  { key: "rushingYards", label: "Rush Yds" },
  { key: "totalYards", label: "Total Yds" },
  { key: "tackles", label: "Tackles" },
  { key: "sacks", label: "Sacks" },
  { key: "interceptions", label: "Interceptions" },
  { key: "fumbles", label: "Fumbles" },
];

const NHL_STATS: TeamStatDef[] = [
  { key: "shotsOnGoal", label: "Shots" },
  { key: "faceoffPct", label: "Faceoff %", format: (v) => `${v.toFixed(1)}%` },
  {
    key: "powerPlayPct",
    label: "Power Play",
    format: (v, s) =>
      s?.powerPlayGoals != null && s?.powerPlayOpportunities != null
        ? `${s.powerPlayGoals}/${s.powerPlayOpportunities}`
        : `${v}%`,
  },
  { key: "pim", label: "Penalty Min" },
  { key: "hits", label: "Hits" },
  { key: "blockedShots", label: "Blocked" },
  { key: "giveaways", label: "Giveaways" },
  { key: "takeaways", label: "Takeaways" },
];

const pct = (v: number) => `${v.toFixed(1)}%`;

const NBA_STATS: TeamStatDef[] = [
  { key: "fieldGoalPct", label: "FG %", format: pct },
  { key: "threePointPct", label: "3PT %", format: pct },
  { key: "freeThrowPct", label: "FT %", format: pct },
  { key: "rebounds", label: "Rebounds" },
  { key: "offensiveRebounds", label: "Off Rebounds" },
  { key: "assists", label: "Assists" },
  { key: "steals", label: "Steals" },
  { key: "blocks", label: "Blocks" },
  { key: "turnovers", label: "Turnovers" },
  { key: "pointsInPaint", label: "Pts in Paint" },
  { key: "fastBreakPoints", label: "Fast Break Pts" },
  { key: "fouls", label: "Fouls" },
  { key: "largestLead", label: "Largest Lead" },
];

function TeamStatChart({
  game,
  collapsed,
  onToggle,
  statDefs = FOOTBALL_STATS,
}: {
  game: GameView;
  collapsed: boolean;
  onToggle: () => void;
  statDefs?: TeamStatDef[];
}) {
  function chartColor(raw: string | null | undefined, fallback: string): string {
    const value = String(raw ?? "").trim();
    if (!value) return fallback;
    const normalized = value.startsWith("#") ? value : `#${value}`;
    if (/^#[0-9a-fA-F]{6}$/.test(normalized) || /^#[0-9a-fA-F]{3}$/.test(normalized)) {
      return normalized;
    }
    return fallback;
  }

  const values = statDefs
    .map((stat) => ({
      ...stat,
      home: game.homeTeamStats?.[stat.key] ?? null,
      away: game.awayTeamStats?.[stat.key] ?? null,
    }))
    .filter((stat) => stat.home != null || stat.away != null);

  if (!values.length) return null;

  const homeName = game.homeTeamName ?? "Home";
  const awayName = game.awayTeamName ?? "Away";
  const homeBarColor = chartColor(game.homeTeamColor, "#1d4ed8");
  const awayBarColor = chartColor(game.awayTeamColor, "#d8362f");

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--input-border)] bg-[var(--surface)] shadow-[0_1px_0_rgba(0,0,0,0.04)]">
      <div className="border-b border-[var(--input-border)] px-4 py-2.5">
        <button
          type="button"
          onClick={onToggle}
          className="flex w-full items-center justify-between text-left"
          aria-expanded={!collapsed}
        >
          <div className="text-[14px] font-black uppercase tracking-[0.12em] text-[var(--text)]">
            Team Stats
          </div>
          <span className="text-xs text-[var(--text-subtle)]">
            {collapsed ? "Show" : "Hide"}
          </span>
        </button>
      </div>

      {collapsed ? null : (
        <div className="space-y-1.5 px-4 py-2.5">
        <div className="flex items-center justify-between pb-1.5">
          <div className="flex items-center gap-2 text-left">
            {game.homeLogoUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={logoSrc(game.homeTeamId, "team") || game.homeLogoUrl} alt="" className="h-8 w-8 object-contain" />
            ) : (
              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[var(--surface-strong)] text-[10px] font-black uppercase text-[var(--text)]">
                {homeName.slice(0, 2)}
              </div>
            )}
            <div className="text-[11px] font-bold uppercase tracking-wide text-[var(--text)]">
              {homeName}
            </div>
          </div>

          <div className="flex items-center gap-2 text-right">
            <div className="text-[11px] font-bold uppercase tracking-wide text-[var(--text)]">
              {awayName}
            </div>
            {game.awayLogoUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={logoSrc(game.awayTeamId, "team") || game.awayLogoUrl} alt="" className="h-8 w-8 object-contain" />
            ) : (
              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[var(--surface-strong)] text-[10px] font-black uppercase text-[var(--text)]">
                {awayName.slice(0, 2)}
              </div>
            )}
          </div>
        </div>

        {values.map((stat) => {
          const homeValue = stat.home ?? 0;
          const awayValue = stat.away ?? 0;
          const max = Math.max(homeValue, awayValue, 1);
          const homeWidth = Math.max(0, (homeValue / max) * 100);
          const awayWidth = Math.max(0, (awayValue / max) * 100);
          const homeLabel =
            stat.home == null ? "—" : stat.format ? stat.format(stat.home, game.homeTeamStats) : stat.home;
          const awayLabel =
            stat.away == null ? "—" : stat.format ? stat.format(stat.away, game.awayTeamStats) : stat.away;

          return (
            <div key={stat.key} className="border-t border-[var(--input-border)] pt-2 first:border-t-0 first:pt-0">
              <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
                <div className="text-right text-[clamp(1rem,1.5vw,1.5rem)] font-black leading-none tracking-[-0.04em] text-[var(--text)] tabular-nums">
                  {homeLabel}
                </div>

                <div className="min-w-[92px] text-center text-[9px] font-bold uppercase tracking-[0.16em] text-[var(--text-subtle)]">
                  {stat.label}
                </div>

                <div className="text-left text-[clamp(1rem,1.5vw,1.5rem)] font-black leading-none tracking-[-0.04em] text-[var(--text)] tabular-nums">
                  {awayLabel}
                </div>
              </div>

              <div className="mt-1 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
                <div className="relative h-2 overflow-hidden rounded-full bg-[var(--chip-strong)]">
                  <div
                    className="absolute inset-y-0 left-0 rounded-full"
                    style={{
                      backgroundColor: homeBarColor,
                      width: `${homeWidth}%`,
                      backgroundImage:
                        "repeating-linear-gradient(135deg, rgba(255,255,255,0.18) 0, rgba(255,255,255,0.18) 2px, transparent 2px, transparent 6px)",
                    }}
                  />
                </div>

                <div className="w-0" />

                <div className="relative h-2 overflow-hidden rounded-full bg-[var(--chip-strong)]">
                  <div
                    className="absolute inset-y-0 right-0 rounded-full"
                    style={{
                      backgroundColor: awayBarColor,
                      width: `${awayWidth}%`,
                      backgroundImage:
                        "repeating-linear-gradient(135deg, rgba(255,255,255,0.18) 0, rgba(255,255,255,0.18) 2px, transparent 2px, transparent 6px)",
                    }}
                  />
                </div>
              </div>
            </div>
          );
        })}
        </div>
      )}
    </div>
  );
}

export function GameModal() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const gameId = params.get("game");

  const [game, setGame] = useState<GameView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [form, setForm] = useState<{
    home: FormResult[];
    away: FormResult[];
  } | null>(null);
  const showResults = useShowResults();
  const [teamStatsCollapsed, setTeamStatsCollapsed] = useState(false);
  const [gameLeadersCollapsed, setGameLeadersCollapsed] = useState(false);
  const [scoringCollapsed, setScoringCollapsed] = useState(false);
  const [threeStarsCollapsed, setThreeStarsCollapsed] = useState(false);

  const close = useCallback(() => {
    const next = new URLSearchParams(params.toString());
    next.delete("game");
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [params, pathname, router]);

  useEffect(() => {
    if (!gameId) {
      setGame(null);
      setError(false);
      setForm(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(false);
    setGame(null);
    setForm(null);
    fetch(`/api/games/${gameId}`, { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("not found"))))
      .then((data: GameView) => setGame(data))
      .catch((err) => {
        if (err?.name !== "AbortError") setError(true);
      })
      .finally(() => setLoading(false));
    loadForm(Number(gameId)).then((f) => setForm(f));
    return () => ctrl.abort();
  }, [gameId]);

  useEffect(() => {
    if (!gameId) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [gameId, close]);

  if (!gameId) return null;

  const videoId = game?.videoId ?? null;
  const isNflGame = game?.conferenceType === "NFL";
  const isFootballGame = isNflGame || game?.conferenceType === "FBS" || game?.conferenceType === "FCS";
  const isNbaGame = game?.conferenceType === "NBA";
  const story = game?.conferenceType === "NHL" ? nhlStory(game) : null;
  const meta: { label: string; value: string }[] = [];
  if (game) {
    if (game.season) meta.push({ label: "Season", value: game.season });
    if (game.type === "postseason") {
      meta.push({ label: "Week", value: "Postseason" });
    } else if (game.week) {
      meta.push({ label: "Week", value: `Week ${game.week}` });
    }
    if (game.gameDate) {
      meta.push({ label: "Date", value: formatDateTime(game.gameDate) });
    }
    if (game.location) meta.push({ label: "Location", value: game.location });
    if (game.excitementIndex != null) {
      meta.push({
        label: "Excitement",
        value: `🔥 ${Number(game.excitementIndex).toFixed(1)}`,
      });
    }
    if (game.overtime) meta.push({ label: "Overtime", value: "Yes" });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm sm:items-center"
      role="dialog"
      aria-modal="true"
      onClick={close}
    >
      <div
        className="relative my-auto w-full max-w-6xl overflow-hidden rounded-2xl border border-[var(--input-border)] bg-[var(--surface-alt)] shadow-2xl shadow-[var(--shadow)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-end border-b border-[var(--input-border)] bg-[var(--surface)]/80 px-3 py-3 backdrop-blur-sm">
          <button
            type="button"
            onClick={close}
            aria-label="Close"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--chip-strong)] text-lg text-[var(--text-muted)] transition hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"
          >
            ✕
          </button>
        </div>

        <div className="relative aspect-video bg-[var(--surface-alt)]">
          {videoId ? (
            isNflGame ? (
              <a
                href={youtubeUrl(videoId) ?? "#"}
                target="_blank"
                rel="noreferrer"
                className="group block h-full w-full"
                aria-label="Open highlight on YouTube"
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={youtubeThumb(videoId) ?? ""}
                  alt={game?.name ?? "highlight thumbnail"}
                  className="h-full w-full object-cover"
                />
                <div className="absolute inset-0 flex items-center justify-center bg-black/25 transition group-hover:bg-black/15">
                  <div className="flex h-16 w-16 items-center justify-center rounded-full bg-black/60 text-2xl text-white shadow-lg">
                    ▶
                  </div>
                </div>
              </a>
            ) : (
              <iframe
                className="h-full w-full"
                src={`https://www.youtube.com/embed/${videoId}?autoplay=1`}
                title={game?.name ?? "highlight"}
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            )
          ) : (
            <div className="flex h-full w-full items-center justify-center text-[var(--text-subtle)]">
              {loading ? "Loading…" : error ? "Game not found" : "No video"}
            </div>
          )}
        </div>

        {game ? (
          <div className="space-y-4 p-5">
            <div className="flex flex-wrap items-center gap-2">
              {shortSportLabel(game.conferenceType) ? (
                <span className="rounded bg-[var(--chip)] px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
                  {shortSportLabel(game.conferenceType)}
                </span>
              ) : null}
              {!game.highlightsChecked ? (
                <span className="rounded bg-red-500/80 px-2 py-0.5 text-[11px] font-semibold text-black">
                  needs review
                </span>
              ) : null}
              <label className="ml-auto flex cursor-pointer select-none items-center gap-2 text-xs text-[var(--text-muted)]">
                <span>Show result</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={showResults}
                  onClick={() => setShowResults(!showResults)}
                  className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition ${
                    showResults ? "bg-emerald-500" : "bg-[var(--chip-strong)]"
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
                      showResults ? "translate-x-4" : "translate-x-0.5"
                    }`}
                  />
                </button>
              </label>
            </div>

            <div className="space-y-3">
              <TeamRow
                name={game.awayTeamName}
                rank={game.awayRank}
                logo={game.awayLogoUrl ? logoSrc(game.awayTeamId, "team") : null}
                conference={game.awayConference}
                conferenceLogo={
                  game.awayConferenceLogoUrl
                    ? logoSrc(game.awayTeamId, "conference")
                    : null
                }
                record={game.awayRecord}
                points={game.awayPoints}
                lineScores={game.awayLineScores}
                showPoints={showResults}
                form={form?.away ?? null}
                quarterScores={isFootballGame || isNbaGame}
              />
              <div className="text-center text-[11px] uppercase tracking-widest text-[var(--text-subtle)]">
                at
              </div>
              <TeamRow
                name={game.homeTeamName}
                rank={game.homeRank}
                logo={game.homeLogoUrl ? logoSrc(game.homeTeamId, "team") : null}
                conference={game.homeConference}
                conferenceLogo={
                  game.homeConferenceLogoUrl
                    ? logoSrc(game.homeTeamId, "conference")
                    : null
                }
                record={game.homeRecord}
                points={game.homePoints}
                lineScores={game.homeLineScores}
                showPoints={showResults}
                form={form?.home ?? null}
                quarterScores={isFootballGame || isNbaGame}
              />
            </div>

            {game.location ? (
              <div className="mt-2 text-center text-base text-[var(--text)]">
                {game.location}
              </div>
            ) : null}

            {isFootballGame || isNbaGame ? (
              <TeamStatChart
                game={game}
                statDefs={isNbaGame ? NBA_STATS : FOOTBALL_STATS}
                collapsed={teamStatsCollapsed}
                onToggle={() => setTeamStatsCollapsed((v) => !v)}
              />
            ) : null}

            {isFootballGame || isNbaGame ? (
              <GameLeaders
                game={game}
                collapsed={gameLeadersCollapsed}
                onToggle={() => setGameLeadersCollapsed((v) => !v)}
              />
            ) : null}

            {story ? (
              <>
                <NhlScoring
                  game={game}
                  story={story}
                  showResults={showResults}
                  collapsed={scoringCollapsed}
                  onToggle={() => setScoringCollapsed((v) => !v)}
                />
                <NhlThreeStars
                  game={game}
                  story={story}
                  collapsed={threeStarsCollapsed}
                  onToggle={() => setThreeStarsCollapsed((v) => !v)}
                />
              </>
            ) : null}

            {game.conferenceType === "NHL" ? (
              <TeamStatChart
                game={game}
                statDefs={NHL_STATS}
                collapsed={teamStatsCollapsed}
                onToggle={() => setTeamStatsCollapsed((v) => !v)}
              />
            ) : null}

            {meta.length ? (
              <div className="grid grid-cols-2 gap-3 border-t border-[var(--input-border)] pt-4 sm:grid-cols-3">
                {meta.map((m) => (
                  <Meta key={m.label} label={m.label} value={m.value} />
                ))}
              </div>
            ) : null}

            {game.reason ? (
              <div className="border-t border-[var(--input-border)] pt-4">
                <div className="text-[11px] uppercase tracking-wide text-[var(--text-subtle)]">
                  Note
                </div>
                <div className="text-sm text-[var(--text-muted)]">{game.reason}</div>
              </div>
            ) : null}

            {videoId ? (
              <div className="border-t border-[var(--input-border)] pt-4">
                <a
                  href={youtubeUrl(videoId) ?? "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-[var(--text-muted)] hover:text-[var(--text)]"
                >
                  Watch on YouTube ↗
                </a>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="p-6 text-center text-sm text-[var(--text-muted)]">
            {loading ? "Loading game…" : error ? "Game not found." : null}
          </div>
        )}
      </div>
    </div>
  );
}
