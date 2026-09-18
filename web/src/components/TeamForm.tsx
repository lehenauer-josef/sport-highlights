"use client";

import { useState } from "react";
import { logoSrc } from "@/lib/format";
import type { FormResult, TeamForm } from "@/lib/games";

// One shared fetch per game id, reused by both team icons and the detail view.
const cache = new Map<number, Promise<TeamForm>>();

export function loadForm(gameId: number): Promise<TeamForm> {
  let p = cache.get(gameId);
  if (!p) {
    p = fetch(`/api/games/${gameId}/form`)
      .then((r) => (r.ok ? r.json() : { home: [], away: [] }))
      .catch(() => ({ home: [], away: [] }) as TeamForm);
    cache.set(gameId, p);
  }
  return p;
}

function shortDate(d: Date | string | null): string {
  if (!d) return "";
  const dt = typeof d === "string" ? new Date(d) : d;
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function ResultBadge({ result }: { result: FormResult["result"] }) {
  return (
    <span
      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
        result === "W"
          ? "bg-emerald-500/80 text-black"
          : result === "L"
            ? "bg-red-500/80 text-black"
            : "bg-white/25 text-white"
      }`}
    >
      {result}
    </span>
  );
}

// Compact W/L squares (used as the summary strip).
export function FormBadges({ results }: { results: FormResult[] }) {
  if (!results.length) {
    return <span className="text-xs text-white/40">No recent games</span>;
  }
  return (
    <span className="flex items-center gap-1">
      {results.map((r) => (
        <ResultBadge key={r.gameId} result={r.result} />
      ))}
    </span>
  );
}

// Detailed rows: result, home/away (@), opponent logo + name, score, date.
export function FormList({ results }: { results: FormResult[] }) {
  if (!results.length) {
    return <span className="text-xs text-white/40">No recent games</span>;
  }
  return (
    <div className="flex flex-col gap-1.5">
      {results.map((r) => (
        <div key={r.gameId} className="flex items-center gap-2 text-xs">
          <ResultBadge result={r.result} />
          <span className="w-5 shrink-0 text-center text-white/40">
            {r.home ? "vs" : "@"}
          </span>
          {r.opponentLogoUrl && r.opponentId ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={logoSrc(r.opponentId, "team") ?? ""}
              alt=""
              className="h-4 w-4 shrink-0 object-contain"
            />
          ) : (
            <span className="h-4 w-4 shrink-0 rounded bg-white/10" />
          )}
          <span className="min-w-0 flex-1 truncate text-white/80">
            {r.opponent ?? "?"}
          </span>
          <span className="shrink-0 tabular-nums text-white/60">
            {r.teamPoints}
            {"\u2013"}
            {r.oppPoints}
          </span>
          <span className="shrink-0 text-white/40">{shortDate(r.date)}</span>
        </div>
      ))}
    </div>
  );
}

function ChartIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <line x1="6" y1="20" x2="6" y2="12" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="18" y1="20" x2="18" y2="9" />
    </svg>
  );
}

// Card icon: lazily loads the game's form on hover and shows the badges.
export function FormHover({
  gameId,
  side,
}: {
  gameId: number;
  side: "home" | "away";
}) {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<FormResult[] | null>(null);

  function onEnter() {
    setOpen(true);
    if (results == null) {
      loadForm(gameId).then((f) => setResults(side === "home" ? f.home : f.away));
    }
  }

  return (
    <span
      className="relative inline-flex shrink-0"
      onMouseEnter={onEnter}
      onMouseLeave={() => setOpen(false)}
      onClick={(e) => e.stopPropagation()}
    >
      <span
        className="cursor-help text-white/35 transition hover:text-white/70"
        title="Recent form"
      >
        <ChartIcon />
      </span>
      {open ? (
        <span className="absolute right-0 top-full z-30 mt-1 w-64 rounded-lg border border-white/10 bg-neutral-900 px-2.5 py-2 shadow-xl">
          <span className="mb-1.5 block text-[10px] uppercase tracking-wide text-white/40">
            Last 5
          </span>
          {results == null ? (
            <span className="text-xs text-white/40">Loading…</span>
          ) : (
            <FormList results={results} />
          )}
        </span>
      ) : null}
    </span>
  );
}
