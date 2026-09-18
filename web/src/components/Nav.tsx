"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SPORT_TABS } from "@/lib/sports";

export function Nav() {
  const pathname = usePathname();
  const tabs = [
    ...SPORT_TABS.map((t) => ({ href: `/s/${t.slug}`, label: t.label })),
    { href: "/review", label: "Review queue" },
  ];

  return (
    <nav className="flex w-full flex-wrap items-center gap-1 px-4 py-3 sm:px-6">
      <Link href="/" className="mr-4 text-lg font-semibold tracking-tight">
        🎬 Highlights
      </Link>
      {tabs.map((t) => {
        const active = pathname === t.href || pathname.startsWith(`${t.href}/`);
        return (
          <Link
            key={t.href}
            href={t.href}
            className={
              active
                ? "rounded-lg bg-white/10 px-3 py-1.5 text-sm font-medium text-white"
                : "rounded-lg px-3 py-1.5 text-sm text-white/60 hover:bg-white/5 hover:text-white"
            }
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
