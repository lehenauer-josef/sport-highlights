"use client";

import { useRouter, useSearchParams } from "next/navigation";

// Toggles between the default queue (only unchecked highlights) and all games.
export function ReviewShowAll({ showAll }: { showAll: boolean }) {
  const router = useRouter();
  const params = useSearchParams();

  function toggle() {
    const next = new URLSearchParams(params.toString());
    if (showAll) next.delete("all");
    else next.set("all", "1");
    const qs = next.toString();
    router.push(qs ? `?${qs}` : "?");
  }

  return (
    <label className="flex cursor-pointer select-none items-center gap-2 text-xs text-white/60">
      <span>Show all</span>
      <button
        type="button"
        role="switch"
        aria-checked={showAll}
        onClick={toggle}
        className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition ${
          showAll ? "bg-emerald-500" : "bg-white/20"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
            showAll ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
    </label>
  );
}
