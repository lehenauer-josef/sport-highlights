"use client";

import { useCallback, useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { GameView } from "@/lib/games";
import { ReviewCard } from "@/components/ReviewCard";

// Server renders the first page; further pages are appended as the sentinel
// scrolls into view. `query` is the filter querystring (incl. "all").
export function ReviewList({
  initial,
  initialHasMore,
  query,
  showAll,
  validatableTotal,
}: {
  initial: GameView[];
  initialHasMore: boolean;
  query: string;
  showAll: boolean;
  // Unchecked games with a video matching the filters ("Validate all").
  validatableTotal: number;
}) {
  const router = useRouter();
  const [refreshing, startTransition] = useTransition();
  const [rows, setRows] = useState<GameView[]>(initial);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [hasMore, setHasMore] = useState(initialHasMore);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const loadingRef = useRef(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const loadMore = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      // Offset = cards shown: reviewed cards dropped from the unchecked queue
      // no longer match the filter, so this doesn't skip any games.
      const offset = rowsRef.current.length;
      const res = await fetch(`/api/review?${query}&offset=${offset}`);
      if (!res.ok) throw new Error("failed");
      const data: { rows: GameView[]; hasMore: boolean } = await res.json();
      setRows((prev) => {
        const seen = new Set(prev.map((g) => g.id));
        return [...prev, ...data.rows.filter((g) => !seen.has(g.id))];
      });
      setHasMore(data.hasMore);
    } catch {
      setHasMore(false);
    } finally {
      loadingRef.current = false;
    }
  }, [query]);

  useEffect(() => {
    if (!hasMore) return;
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) loadMore();
      },
      { rootMargin: "800px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasMore, loadMore, rows.length]);

  // Reviewed games leave the default (unchecked) queue; otherwise refresh the card.
  const onUpdated = useCallback(
    (game: GameView) => {
      setRows((prev) =>
        !showAll && game.highlightsChecked
          ? prev.filter((g) => g.id !== game.id)
          : prev.map((g) => (g.id === game.id ? game : g)),
      );
      // A checked game can no longer be bulk-validated.
      if (game.highlightsChecked) {
        setSelected((prev) => {
          if (!prev.has(game.id)) return prev;
          const next = new Set(prev);
          next.delete(game.id);
          return next;
        });
      }
    },
    [showAll],
  );

  // Validated games leave the default (unchecked) queue; with "Show all" they stay, marked approved.
  const applyValidated = useCallback(
    (ids: number[]) => {
      const done = new Set(ids);
      setRows((prev) =>
        showAll
          ? prev.map((g) =>
              done.has(g.id)
                ? { ...g, reviewStatus: "approved", highlightsValid: true, highlightsChecked: true }
                : g,
            )
          : prev.filter((g) => !done.has(g.id)),
      );
      setSelected((prev) => new Set([...prev].filter((id) => !done.has(id))));
    },
    [showAll],
  );

  async function bulkValidate(body: Record<string, unknown>) {
    setBulkBusy(true);
    try {
      const res = await fetch("/api/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data: { ids?: number[] } = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error("failed");
      applyValidated(data.ids ?? []);
    } catch {
      window.alert("Validation failed. Please try again.");
    } finally {
      setBulkBusy(false);
    }
    // Refresh the server counts ("to check", "Validate all").
    startTransition(() => router.refresh());
  }

  const selectable = rows.filter((g) => g.videoId && !g.highlightsChecked);
  const allLoadedSelected =
    selectable.length > 0 && selectable.every((g) => selected.has(g.id));
  const busy = bulkBusy || refreshing;

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAllLoaded() {
    setSelected(allLoadedSelected ? new Set() : new Set(selectable.map((g) => g.id)));
  }

  function validateSelected() {
    if (!selected.size) return;
    bulkValidate({ action: "validate_many", ids: [...selected] });
  }

  function validateAll() {
    if (!validatableTotal) return;
    bulkValidate({ action: "validate_all", query });
  }

  const btn =
    "rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-40";

  const toolbar =
    selectable.length > 0 || validatableTotal > 0 ? (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--input-border)] bg-[var(--surface)] px-4 py-2">
        <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text-muted)]">
          <input
            type="checkbox"
            checked={allLoadedSelected}
            disabled={!selectable.length || busy}
            onChange={toggleSelectAllLoaded}
            className="h-4 w-4 accent-emerald-500"
          />
          Select all loaded ({selectable.length})
        </label>
        <button
          type="button"
          disabled={!validatableTotal || busy}
          onClick={validateAll}
          title="Approve the current video of every unchecked game matching the filters (games without a video and rejected games are skipped)"
          className={`${btn} bg-emerald-500 text-black hover:bg-emerald-400`}
        >
          ✓ Validate all matching ({validatableTotal})
        </button>
      </div>
    ) : null;

  if (rows.length === 0 && !hasMore) {
    return (
      <p className="py-16 text-center text-white/40">
        {showAll ? "No games match these filters." : "Nothing to review. 🎉"}
      </p>
    );
  }

  return (
    <>
      {toolbar}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {rows.map((game) => (
          <ReviewCard
            key={game.id}
            game={game}
            onUpdated={onUpdated}
            selected={selected.has(game.id)}
            onToggleSelect={
              game.videoId && !game.highlightsChecked ? toggleSelect : undefined
            }
          />
        ))}
      </div>
      {hasMore ? (
        <div
          ref={sentinelRef}
          className="py-8 text-center text-sm text-[var(--text-subtle)]"
        >
          Loading more…
        </div>
      ) : null}
      {selected.size > 0 ? (
        <div className="fixed inset-x-0 bottom-4 z-20 mx-auto flex w-fit items-center gap-3 rounded-xl border border-[var(--input-border)] bg-[var(--surface)] px-4 py-2 shadow-lg">
          <span className="text-sm text-[var(--text)]">{selected.size} selected</span>
          <button
            type="button"
            disabled={busy}
            onClick={() => setSelected(new Set())}
            className={`${btn} bg-[var(--chip-strong)] text-[var(--text)] hover:bg-[var(--surface-strong)]`}
          >
            Clear
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={validateSelected}
            className={`${btn} bg-emerald-500 text-black hover:bg-emerald-400`}
          >
            {busy ? "Validating…" : `✓ Validate selected (${selected.size})`}
          </button>
        </div>
      ) : null}
    </>
  );
}
