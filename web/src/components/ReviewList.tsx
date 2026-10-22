"use client";

import { useCallback, useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { GameView } from "@/lib/games";
import { ReviewCard } from "@/components/ReviewCard";

type BulkKind = "validate" | "unvalidate";

// Cards that can be bulk-validated (unchecked, with a video) or bulk-unvalidated (checked).
function canSelect(g: GameView) {
  return Boolean(g.highlightsChecked || g.videoId);
}

// Server renders the first page; further pages are appended as the sentinel
// scrolls into view. `query` is the filter querystring (incl. "all").
export function ReviewList({
  initial,
  initialHasMore,
  query,
  showAll,
  validatableTotal,
  unvalidatableTotal,
}: {
  initial: GameView[];
  initialHasMore: boolean;
  query: string;
  showAll: boolean;
  // Unchecked games with a video matching the filters ("Validate all").
  validatableTotal: number;
  // Checked games matching the filters ("Unvalidate all"); 0 unless "Show all".
  unvalidatableTotal: number;
}) {
  const router = useRouter();
  const [refreshing, startTransition] = useTransition();
  const [rows, setRows] = useState<GameView[]>(initial);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkBusy, setBulkBusy] = useState<BulkKind | null>(null);
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

  // Unvalidated games go back to pending; they stay listed (only "Show all" shows checked games).
  const applyUnvalidated = useCallback((ids: number[]) => {
    const done = new Set(ids);
    setRows((prev) =>
      prev.map((g) =>
        done.has(g.id) ? { ...g, reviewStatus: "pending", highlightsChecked: false } : g,
      ),
    );
    setSelected((prev) => new Set([...prev].filter((id) => !done.has(id))));
  }, []);

  async function bulkRequest(kind: BulkKind, body: Record<string, unknown>) {
    setBulkBusy(kind);
    try {
      const res = await fetch("/api/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data: { ids?: number[] } = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error("failed");
      if (kind === "validate") applyValidated(data.ids ?? []);
      else applyUnvalidated(data.ids ?? []);
    } catch {
      window.alert(
        kind === "validate"
          ? "Validation failed. Please try again."
          : "Unvalidation failed. Please try again.",
      );
    } finally {
      setBulkBusy(null);
    }
    // Refresh the server counts ("to check", "Validate all", "Unvalidate all").
    startTransition(() => router.refresh());
  }

  const selectable = rows.filter(canSelect);
  const allLoadedSelected =
    selectable.length > 0 && selectable.every((g) => selected.has(g.id));
  // Each bulk action applies only to its own kind of selected card.
  const selectedRows = rows.filter((g) => selected.has(g.id));
  const toValidate = selectedRows.filter((g) => !g.highlightsChecked).map((g) => g.id);
  const toUnvalidate = selectedRows.filter((g) => g.highlightsChecked).map((g) => g.id);
  const busy = bulkBusy !== null || refreshing;

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
    if (!toValidate.length) return;
    bulkRequest("validate", { action: "validate_many", ids: toValidate });
  }

  function validateAll() {
    if (!validatableTotal) return;
    bulkRequest("validate", { action: "validate_all", query });
  }

  function unvalidateSelected() {
    if (!toUnvalidate.length) return;
    bulkRequest("unvalidate", { action: "unvalidate_many", ids: toUnvalidate });
  }

  function unvalidateAll() {
    if (!unvalidatableTotal) return;
    bulkRequest("unvalidate", { action: "unvalidate_all", query });
  }

  const btn =
    "rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-40";

  const toolbar =
    selectable.length > 0 || validatableTotal > 0 || unvalidatableTotal > 0 ? (
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
        {unvalidatableTotal > 0 ? (
          <button
            type="button"
            disabled={busy}
            onClick={unvalidateAll}
            title="Mark every checked game matching the filters as unchecked and pending"
            className={`${btn} bg-red-500 text-white hover:bg-red-400`}
          >
            Unvalidate all matching ({unvalidatableTotal})
          </button>
        ) : null}
      </div>
    ) : null;

  if (rows.length === 0 && !hasMore) {
    return (
      <p className="py-16 text-center text-[var(--text-subtle)]">
        {showAll ? "No games match these filters." : "Nothing to review. 🎉"}
      </p>
    );
  }

  return (
    <>
      {toolbar}
      <div className="grid grid-cols-1 gap-4 min-[1024px]:grid-cols-2 min-[1900px]:grid-cols-3">
        {rows.map((game) => (
          <ReviewCard
            key={game.id}
            game={game}
            onUpdated={onUpdated}
            selected={selected.has(game.id)}
            onToggleSelect={canSelect(game) ? toggleSelect : undefined}
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
          {toValidate.length > 0 ? (
            <button
              type="button"
              disabled={busy}
              onClick={validateSelected}
              className={`${btn} bg-emerald-500 text-black hover:bg-emerald-400`}
            >
              {bulkBusy === "validate"
                ? "Validating…"
                : `✓ Validate selected (${toValidate.length})`}
            </button>
          ) : null}
          {toUnvalidate.length > 0 ? (
            <button
              type="button"
              disabled={busy}
              onClick={unvalidateSelected}
              className={`${btn} bg-red-500 text-white hover:bg-red-400`}
            >
              {bulkBusy === "unvalidate"
                ? "Unvalidating…"
                : `Unvalidate selected (${toUnvalidate.length})`}
            </button>
          ) : null}
        </div>
      ) : null}
    </>
  );
}
