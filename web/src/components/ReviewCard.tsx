"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { formatDate, youtubeThumb, youtubeUrl } from "@/lib/format";
import type { GameView } from "@/lib/games";
import { shortSportLabel } from "@/lib/sports";

type YouTubeResult = {
  videoId: string;
  title: string;
  channel: string | null;
  duration: string | null;
  thumbnail: string;
};

function VideoPreview({
  label,
  videoId,
  accent,
}: {
  label: string;
  videoId: string | null;
  accent: string;
}) {
  const thumb = youtubeThumb(videoId);
  return (
    <div className="flex-1">
      <div className={`mb-1 text-xs font-medium ${accent}`}>{label}</div>
      {videoId ? (
        <a href={youtubeUrl(videoId) ?? "#"} target="_blank" rel="noreferrer">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={thumb ?? ""}
            alt=""
            className="aspect-video w-full rounded-lg object-cover"
          />
        </a>
      ) : (
        <div className="flex aspect-video w-full items-center justify-center rounded-lg bg-white/5 text-xs text-white/30">
          none
        </div>
      )}
    </div>
  );
}

export function ReviewCard({ game }: { game: GameView }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
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
    await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: game.id, action, ...extra }),
    });
    setBusy(false);
    router.refresh();
  }

  const btn =
    "rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-40";

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="truncate font-medium">
          {game.awayTeamName} @ {game.homeTeamName}
        </h3>
        <span className="shrink-0 text-xs text-white/40">
          {shortSportLabel(game.conferenceType)} · {game.season}
          {game.week ? ` · Wk ${game.week}` : ""} ·{" "}
          {formatDate(game.gameDate)}
        </span>
      </div>

      {game.reason ? (
        <p className="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {game.reason}
        </p>
      ) : null}

      <div className="flex gap-4">
        <VideoPreview
          label="Current"
          videoId={game.videoId}
          accent="text-white/60"
        />

        <div className="flex-1">
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-emerald-300">
              YouTube results
            </span>
            {searchUrl ? (
              <a
                href={searchUrl}
                target="_blank"
                rel="noreferrer"
                className="text-[11px] text-white/50 hover:text-white"
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
              className="flex aspect-video w-full items-center justify-center rounded-lg border border-dashed border-white/15 bg-white/5 text-xs text-white/60 transition hover:bg-white/10 disabled:opacity-40"
            >
              {searching ? "Searching…" : "🔍 Search YouTube"}
            </button>
          ) : results.length === 0 ? (
            <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-lg bg-white/5 px-3 text-center text-xs text-white/30">
              <span>No results found.</span>
              <button
                type="button"
                onClick={loadResults}
                disabled={searching}
                className="rounded bg-white/10 px-2 py-1 text-white/70 hover:bg-white/20 disabled:opacity-40"
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
                      className="line-clamp-2 text-xs text-white/80 hover:text-white"
                      title={r.title}
                    >
                      {r.title}
                    </a>
                    <div className="mt-0.5 flex items-center gap-2">
                      {r.channel ? (
                        <span className="truncate text-[10px] text-white/40">
                          {r.channel}
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
          className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-sm text-white placeholder:text-white/30 focus:border-white/30 focus:outline-none"
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
