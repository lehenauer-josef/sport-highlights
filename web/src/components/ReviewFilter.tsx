"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { DEFAULT_REVIEW_SPORT, REVIEW_SPORT_TABS } from "@/lib/sports";

export function ReviewFilter({ active }: { active: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  function select(label: string) {
    const next = new URLSearchParams(params.toString());
    if (label === DEFAULT_REVIEW_SPORT) next.delete("sport");
    else next.set("sport", label);
    const qs = next.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname);
  }

  return (
    <div className="flex flex-wrap gap-1">
      {REVIEW_SPORT_TABS.map((t) => {
        const isActive = t.label === active;
        return (
          <button
            key={t.label}
            type="button"
            onClick={() => select(t.label)}
            className={
              isActive
                ? "rounded-lg bg-white/10 px-3 py-1.5 text-sm font-medium text-white"
                : "rounded-lg px-3 py-1.5 text-sm text-white/60 hover:bg-white/5 hover:text-white"
            }
          >
            {t.short}
          </button>
        );
      })}
    </div>
  );
}
