"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { MultiSelect } from "@/components/MultiSelect";
import { TeamSearch } from "@/components/TeamSearch";
import type { FilterOptions } from "@/lib/games";

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

  function apply(mutate: (next: URLSearchParams) => void) {
    const next = new URLSearchParams(params.toString());
    mutate(next);
    next.delete("page");
    router.push(`?${next.toString()}`);
  }

  function update(key: string, value: string) {
    apply((next) => {
      if (value) next.set(key, value);
      else next.delete(key);
    });
  }

  function updateList(key: string, values: string[]) {
    apply((next) => {
      if (values.length) next.set(key, values.join(","));
      else next.delete(key);
    });
  }

  const select =
    "rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-sm outline-none focus:border-white/30";

  const teams = splitList(params.get("team"));
  const weeks = splitList(params.get("week"));

  const weekOptions = [
    ...options.weeks.map((w) => ({ value: String(w), label: `Week ${w}` })),
    ...(options.hasPostseason
      ? [{ value: "postseason", label: "Postseason" }]
      : []),
  ];

  return (
    <div className="flex flex-wrap items-center gap-2">
      <TeamSearch
        selected={teams}
        sportSlug={sportSlug}
        onChange={(v) => updateList("team", v)}
      />
      <select
        className={select}
        value={params.get("conference") ?? ""}
        onChange={(e) => update("conference", e.target.value)}
      >
        <option value="">All conferences</option>
        {options.conferences.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
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
        <MultiSelect
          label="Week"
          options={weekOptions}
          selected={weeks}
          onChange={(v) => updateList("week", v)}
        />
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
      </select>

      <div className="ml-auto flex items-center gap-2">
        <span className="text-sm text-white/40">Sort</span>
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
  );
}
