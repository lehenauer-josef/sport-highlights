"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { GameView } from "@/lib/games";
import { HighlightCard } from "@/components/HighlightCard";

// Server renders page 1; this component appends further pages as the sentinel
// scrolls into view. `query` is the filter querystring (without `page`).
export function GameGrid({
  initial,
  initialHasMore,
  query,
}: {
  initial: GameView[];
  initialHasMore: boolean;
  query: string;
}) {
  const [rows, setRows] = useState<GameView[]>(initial);
  const [hasMore, setHasMore] = useState(initialHasMore);
  const pageRef = useRef(1);
  const loadingRef = useRef(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const loadMore = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    const next = pageRef.current + 1;
    try {
      const res = await fetch(`/api/games?${query}&page=${next}`);
      const data: { rows: GameView[]; hasMore: boolean } = await res.json();
      setRows((prev) => [...prev, ...data.rows]);
      setHasMore(data.hasMore);
      pageRef.current = next;
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
  }, [hasMore, loadMore]);

  if (rows.length === 0) {
    return <p className="py-16 text-center text-[var(--text-muted)]">No games found.</p>;
  }

  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 min-[1900px]:grid-cols-6">
        {rows.map((game) => (
          <HighlightCard key={game.id} game={game} />
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
    </>
  );
}
