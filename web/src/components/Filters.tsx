"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { TeamSearch } from "@/components/TeamSearch";
import type { FilterOptions } from "@/lib/games";
import { weekOptionsFor, weeksAvailable } from "@/lib/weeks";

function splitList(value: string | null): string[] {
  return (value ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function Filters({
  options,
  sportSlug,
  showDivision,
}: {
  options: FilterOptions;
  sportSlug: string;
  showDivision: boolean;
}) {
  const router = useRouter();
  const params = useSearchParams();
  const [open, setOpen] = useState(false);

  function apply(mutate: (next: URLSearchParams) => void) {
    const next = new URLSearchParams(params.toString());
    mutate(next);
    next.delete("page");
    next.delete("conference");
    router.push(`?${next.toString()}`);
  }

  function update(key: string, value: string) {
    apply((next) => {
      if (value || key === "week") next.set(key, value);
      else next.delete(key);
      // Fall back to "All weeks" when the new season lacks the chosen week.
      if (key === "season") {
        if (!weeksAvailable(options, value, splitList(next.get("week")))) {
          next.set("week", "");
        }
      }
    });
  }

  function updateList(key: string, values: string[]) {
    apply((next) => {
      if (values.length) next.set(key, values.join(","));
      else next.delete(key);
    });
  }

  const select =
    "w-full rounded-lg border border-[var(--input-border)] bg-[var(--surface-soft)] px-3 py-1.5 text-sm text-[var(--text)] outline-none focus:border-[var(--text-subtle)] sm:w-auto";

  const teams = splitList(params.get("team"));
  const week = splitList(params.get("week"))[0] ?? "";
  const activeCount = ["season", "week", "division", "highlights"]
    .filter((k) => params.get(k)).length;

  const seasonWeeks = weekOptionsFor(options, params.get("season") ?? "");
  const weekOptions = [
    ...seasonWeeks.weeks.map((w) => ({ value: String(w), label: `Week ${w}` })),
    ...(seasonWeeks.hasPostseason
      ? [{ value: "postseason", label: "Postseason" }]
      : []),
  ];

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
      <div className="flex items-start gap-2 sm:contents">
        <div className="min-w-0 flex-1 sm:flex-none">
          <TeamSearch
            selected={teams}
            sportSlug={sportSlug}
            onChange={(v) => updateList("team", v)}
          />
        </div>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="shrink-0 rounded-lg border border-[var(--input-border)] bg-[var(--surface-soft)] px-3 py-2 text-sm text-[var(--text)] sm:hidden"
        >
          Filters{activeCount ? ` (${activeCount})` : ""} {open ? "▴" : "▾"}
        </button>
      </div>

      <div className={`${open ? "grid" : "hidden"} grid-cols-2 gap-2 sm:contents`}>
      <select
        className={select}
        value={params.get("season") ?? ""}
        onChange={(e) => update("season", e.target.value)}
      >
        <option value="">All seasons</option>
        {options.seasons.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      {weekOptions.length ? (
        <select
          aria-label="Week"
          className={select}
          value={week}
          onChange={(e) => update("week", e.target.value)}
        >
          <option value="">All weeks</option>
          {weekOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : null}
      {showDivision ? (
        <select
          className={select}
          value={params.get("division") ?? ""}
          onChange={(e) => update("division", e.target.value)}
        >
          <option value="">All games</option>
          <option value="top25">Top 25</option>
          <option value="FBS">FBS</option>
          <option value="FCS">FCS</option>
        </select>
      ) : null}
      <select
        className={select}
        value={params.get("highlights") ?? ""}
        onChange={(e) => update("highlights", e.target.value)}
      >
        <option value="">All highlights</option>
        <option value="with">With highlights</option>
        <option value="without">Without highlights</option>
        <option value="checked">Highlights checked</option>
      </select>

      <div className="col-span-2 flex items-center gap-2 sm:ml-auto">
        <span className="text-sm text-[var(--text-muted)]">Sort</span>
        <select
          className={select}
          value={params.get("sort") ?? "date"}
          onChange={(e) => update("sort", e.target.value)}
        >
          <option value="date">Date</option>
          <option value="excitement">Excitement</option>
          <option value="rank">Rank</option>
        </select>
        <select
          className={select}
          value={params.get("dir") ?? "desc"}
          onChange={(e) => update("dir", e.target.value)}
        >
          <option value="desc">Desc</option>
          <option value="asc">Asc</option>
        </select>
      </div>
      </div>
    </div>
  );
}
