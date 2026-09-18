"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { formatDate, logoSrc, youtubeUrl } from "@/lib/format";
import type { FormResult, GameView } from "@/lib/games";
import { shortSportLabel } from "@/lib/sports";
import { setShowResults, useShowResults } from "@/lib/prefs";
import { FormList, loadForm } from "@/components/TeamForm";

function TeamRow({
  name,
  rank,
  logo,
  conference,
  conferenceLogo,
  record,
  points,
  showPoints,
  form,
}: {
  name: string | null;
  rank: number | null;
  logo: string | null;
  conference: string | null;
  conferenceLogo: string | null;
  record: string | null;
  points: number | null;
  showPoints: boolean;
  form: FormResult[] | null;
}) {
  return (
    <div className="flex items-center gap-3">
      {logo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={logo} alt="" className="h-10 w-10 shrink-0 object-contain" />
      ) : (
        <div className="h-10 w-10 shrink-0 rounded bg-white/10" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">
            {rank ? <span className="text-white/50">#{rank} </span> : null}
            {name ?? "TBD"}
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
        <div className="text-xs text-white/40">
          {[conference, record ? `(${record})` : null]
            .filter(Boolean)
            .join(" · ")}
        </div>
        {form && form.length ? (
          <div className="mt-2">
            <span className="mb-1.5 block text-[10px] uppercase tracking-wide text-white/30">
              Last 5
            </span>
            <FormList results={form} />
          </div>
        ) : null}
      </div>
      {showPoints && points != null ? (
        <span className="text-2xl font-semibold tabular-nums">{points}</span>
      ) : null}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-white/40">
        {label}
      </div>
      <div className="text-sm text-white/80">{value}</div>
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
  const meta: { label: string; value: string }[] = [];
  if (game) {
    if (game.season) meta.push({ label: "Season", value: game.season });
    if (game.type === "postseason") {
      meta.push({ label: "Week", value: "Postseason" });
    } else if (game.week) {
      meta.push({ label: "Week", value: `Week ${game.week}` });
    }
    if (game.gameDate) {
      meta.push({ label: "Date", value: formatDate(game.gameDate) });
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
        className="relative my-auto w-full max-w-6xl overflow-hidden rounded-2xl border border-white/10 bg-neutral-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={close}
          aria-label="Close"
          className="absolute right-3 top-3 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-black/60 text-lg text-white/80 transition hover:bg-black/80 hover:text-white"
        >
          ✕
        </button>

        <div className="relative aspect-video bg-black">
          {videoId ? (
            <iframe
              className="h-full w-full"
              src={`https://www.youtube.com/embed/${videoId}?autoplay=1`}
              title={game?.name ?? "highlight"}
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
              allowFullScreen
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-white/30">
              {loading ? "Loading…" : error ? "Game not found" : "No video"}
            </div>
          )}
        </div>

        {game ? (
          <div className="space-y-4 p-5">
            <div className="flex flex-wrap items-center gap-2">
              {shortSportLabel(game.conferenceType) ? (
                <span className="rounded bg-white/10 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-white/70">
                  {shortSportLabel(game.conferenceType)}
                </span>
              ) : null}
              {!game.highlightsChecked ? (
                <span className="rounded bg-red-500/80 px-2 py-0.5 text-[11px] font-semibold text-black">
                  needs review
                </span>
              ) : null}
              <label className="ml-auto flex cursor-pointer select-none items-center gap-2 text-xs text-white/60">
                <span>Show result</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={showResults}
                  onClick={() => setShowResults(!showResults)}
                  className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition ${
                    showResults ? "bg-emerald-500" : "bg-white/20"
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
                showPoints={showResults}
                form={form?.away ?? null}
              />
              <div className="text-center text-[11px] uppercase tracking-widest text-white/30">
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
                showPoints={showResults}
                form={form?.home ?? null}
              />
            </div>

            {meta.length ? (
              <div className="grid grid-cols-2 gap-3 border-t border-white/10 pt-4 sm:grid-cols-3">
                {meta.map((m) => (
                  <Meta key={m.label} label={m.label} value={m.value} />
                ))}
              </div>
            ) : null}

            {game.reason ? (
              <div className="border-t border-white/10 pt-4">
                <div className="text-[11px] uppercase tracking-wide text-white/40">
                  Note
                </div>
                <div className="text-sm text-white/70">{game.reason}</div>
              </div>
            ) : null}

            {videoId ? (
              <div className="border-t border-white/10 pt-4">
                <a
                  href={youtubeUrl(videoId) ?? "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-white/60 hover:text-white"
                >
                  Watch on YouTube ↗
                </a>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="p-6 text-center text-sm text-white/50">
            {loading ? "Loading game…" : error ? "Game not found." : null}
          </div>
        )}
      </div>
    </div>
  );
}
