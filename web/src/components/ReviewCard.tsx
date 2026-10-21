"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { youtubeThumb, youtubeUrl } from "@/lib/format";
import { LocalDateTime } from "@/components/LocalDateTime";
import type { GameView } from "@/lib/games";
import { shortSportLabel } from "@/lib/sports";
import { weekLabel } from "@/lib/rounds";
import type { YouTubeResult, YouTubeVideoInfo } from "@/lib/youtube";

function VideoPreview({
  label,
  videoId,
  accent,
  score,
}: {
  label: string;
  videoId: string | null;
  accent: string;
  score?: number | null;
}) {
  const thumb = youtubeThumb(videoId);
  const [info, setInfo] = useState<YouTubeVideoInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  // Reset when the video changes; info is only fetched on demand.
  useEffect(() => {
    setInfo(null);
    setFailed(false);
  }, [videoId]);

  async function loadInfo() {
    if (!videoId) return;
    setLoading(true);
    setFailed(false);
    try {
      const res = await fetch(
        `/api/youtube-video?v=${encodeURIComponent(videoId)}`,
      );
      if (!res.ok) throw new Error("failed");
      setInfo((await res.json()) as YouTubeVideoInfo);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex-1">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className={`text-xs font-medium ${accent}`}>{label}</span>
        {videoId && score != null ? (
          <span
            title="Highlight scorer score of the auto-picked video (picked at 130+)"
            className="rounded bg-[var(--chip-strong)] px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-[var(--text-muted)]"
          >
            Score {score}
          </span>
        ) : null}
      </div>
      {videoId ? (
        <>
          <a
            href={youtubeUrl(videoId) ?? "#"}
            target="_blank"
            rel="noreferrer"
            className="relative block"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={thumb ?? ""}
              alt=""
              className="aspect-video w-full rounded-lg object-cover"
            />
            {info?.duration ? (
              <span className="absolute bottom-1 right-1 rounded bg-black/80 px-1 text-[10px] font-medium tabular-nums text-white">
                {info.duration}
              </span>
            ) : null}
          </a>
          <div className="mt-1 space-y-0.5 text-[10px] text-[var(--text-subtle)]">
            {info ? (
              <>
                {info.title ? (
                  <div
                    className="line-clamp-2 text-xs text-[var(--text)]"
                    title={info.title}
                  >
                    {info.title}
                  </div>
                ) : null}
                <div className="flex flex-wrap gap-x-1">
                  <span className="truncate">{info.channel ?? "Unknown channel"}</span>
                  {info.views ? <span>· {info.views}</span> : null}
                </div>
              </>
            ) : (
              <button
                type="button"
                onClick={loadInfo}
                disabled={loading}
                title="Load channel, duration and views from YouTube"
                className="rounded bg-[var(--chip-strong)] px-2 py-0.5 text-[10px] text-[var(--text-muted)] transition hover:bg-[var(--surface-strong)] hover:text-[var(--text)] disabled:opacity-40"
              >
                {loading
                  ? "Loading…"
                  : failed
                    ? "ⓘ Info unavailable – retry"
                    : "ⓘ Load video info"}
              </button>
            )}
          </div>
        </>
      ) : (
        <div className="flex aspect-video w-full items-center justify-center rounded-lg bg-[var(--surface-soft)] text-xs text-[var(--text-subtle)]">
          none
        </div>
      )}
    </div>
  );
}

export function ReviewCard({
  game,
  onUpdated,
  selected = false,
  onToggleSelect,
}: {
  game: GameView;
  onUpdated?: (game: GameView) => void;
  selected?: boolean;
  // Present when the card can be bulk-validated.
  onToggleSelect?: (id: number) => void;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [refreshing, startTransition] = useTransition();
  const [searchUrl, setSearchUrl] = useState<string | null>(null);
  const [results, setResults] = useState<YouTubeResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [manual, setManual] = useState("");

  async function loadResults() {
    setSearching(true);
    try {
      const res = await fetch(`/api/youtube-search?id=${game.id}`);
      if (!res.ok) throw new Error("failed");
      const data: { url: string; items: YouTubeResult[] } = await res.json();
      setSearchUrl(data.url);
      setResults(data.items);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  async function act(action: string, extra?: Record<string, unknown>) {
    setBusy(true);
    try {
      const res = await fetch("/api/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: game.id, action, ...extra }),
      });
      const data: { game?: GameView | null } = await res
        .json()
        .catch(() => ({}));
      if (res.ok && data.game) onUpdated?.(data.game);
    } finally {
      setBusy(false);
    }
    // Refresh server data (e.g. the queue count); keep the card disabled until it arrives.
    startTransition(() => router.refresh());
  }

  const pending = busy || refreshing;

  const btn =
    "rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-40";

  return (
    <div
      className={`rounded-xl border bg-[var(--surface)] p-4 ${
        selected
          ? "border-emerald-500 ring-1 ring-emerald-500"
          : "border-[var(--input-border)]"
      }`}
    >
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="flex min-w-0 items-baseline gap-2 font-medium text-[var(--text)]">
          {onToggleSelect ? (
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelect(game.id)}
              title="Select for bulk validate or unvalidate"
              aria-label={`Select ${game.awayTeamName} @ ${game.homeTeamName}`}
              className="h-4 w-4 shrink-0 cursor-pointer self-center accent-emerald-500"
            />
          ) : null}
          <span className="truncate">
            {game.awayTeamName} @ {game.homeTeamName}
          </span>
        </h3>
        <span className="shrink-0 text-xs text-[var(--text-muted)]">
          {shortSportLabel(game.conferenceType)} · {game.season}
          {game.type === "postseason"
            ? ` · ${weekLabel(game)}`
            : game.week
              ? ` · Wk ${game.week}`
              : ""}
          <LocalDateTime date={game.gameDate} prefix=" · " />
        </span>
      </div>

      {game.reason ? (
        <p className="mb-3 rounded-lg bg-[var(--danger-soft)] px-3 py-2 text-xs text-red-500">
          {game.reason}
        </p>
      ) : null}

      <div className="flex gap-4">
        <VideoPreview
          label="Current"
          videoId={game.videoId}
          score={game.highlightScore}
          accent="text-[var(--text-muted)]"
        />

        <div className="flex-1">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-emerald-500">
              YouTube results
            </span>
            {searchUrl ? (
              <a
                href={searchUrl}
                target="_blank"
                rel="noreferrer"
                className="text-[11px] text-[var(--text-subtle)] hover:text-[var(--text)]"
              >
                Open search ↗
              </a>
            ) : null}
          </div>

          {results === null ? (
            <button
              type="button"
              onClick={loadResults}
              disabled={searching}
              className="flex aspect-video w-full items-center justify-center rounded-lg border border-dashed border-[var(--input-border)] bg-[var(--surface-soft)] text-xs text-[var(--text-muted)] transition hover:bg-[var(--surface-strong)] disabled:opacity-40"
            >
              {searching ? "Searching…" : "🔍 Search YouTube"}
            </button>
          ) : results.length === 0 ? (
            <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-lg bg-[var(--surface-soft)] px-3 text-center text-xs text-[var(--text-subtle)]">
              <span>No results found.</span>
              <button
                type="button"
                onClick={loadResults}
                disabled={searching}
                className="rounded bg-[var(--chip-strong)] px-2 py-1 text-[var(--text)] hover:bg-[var(--surface-strong)] disabled:opacity-40"
              >
                Retry
              </button>
            </div>
          ) : (
            <ul className="space-y-2">
              {results.map((r) => (
                <li key={r.videoId} className="flex gap-2">
                  <a
                    href={youtubeUrl(r.videoId) ?? "#"}
                    target="_blank"
                    rel="noreferrer"
                    className="relative shrink-0"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={r.thumbnail}
                      alt=""
                      className="h-12 w-20 rounded object-cover"
                    />
                    {r.duration ? (
                      <span className="absolute bottom-0.5 right-0.5 rounded bg-black/80 px-1 text-[9px] font-medium tabular-nums text-white">
                        {r.duration}
                      </span>
                    ) : null}
                  </a>
                  <div className="min-w-0 flex-1">
                    <a
                      href={youtubeUrl(r.videoId) ?? "#"}
                      target="_blank"
                      rel="noreferrer"
                      className="line-clamp-2 text-xs text-[var(--text)] hover:text-[var(--text-muted)]"
                      title={r.title}
                    >
                      {r.title}
                    </a>
                    <div className="mt-0.5 flex items-center gap-2">
                      {r.channel || r.views ? (
                        <span className="truncate text-[10px] text-[var(--text-subtle)]">
                          {[r.channel, r.views].filter(Boolean).join(" · ")}
                        </span>
                      ) : null}
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          act("set_video", { videoId: r.videoId })
                        }
                        className="ml-auto shrink-0 rounded bg-emerald-500/90 px-2 py-0.5 text-[10px] font-medium text-black transition hover:bg-emerald-400 disabled:opacity-40"
                      >
                        Use this
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder="Paste a YouTube URL or video ID"
          className="min-w-0 flex-1 rounded-lg border border-[var(--input-border)] bg-[var(--surface-soft)] px-3 py-1.5 text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--text-subtle)] focus:outline-none"
        />
        <button
          type="button"
          disabled={busy || !manual.trim()}
          onClick={() => act("set_video", { videoId: manual.trim() })}
          className={`${btn} bg-emerald-500 text-black hover:bg-emerald-400`}
        >
          Set video
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {game.betterVideoId ? (
          <button
            disabled={busy}
            onClick={() => act("accept_better")}
            className={`${btn} bg-emerald-500/80 text-black hover:bg-emerald-400`}
          >
            ✓ Use proposed ({game.betterVideoId})
          </button>
        ) : null}
        <button
          disabled={busy}
          onClick={() => act("approve")}
          className={`${btn} bg-emerald-500 text-black hover:bg-emerald-400`}
        >
          Keep current
        </button>
        {game.highlightsChecked ? (
          <button
            disabled={busy}
            onClick={() => act("unvalidate")}
            className={`${btn} bg-red-500 text-white hover:bg-red-400`}
          >
            Unvalidate
          </button>
        ) : null}
      </div>
    </div>
  );
}
