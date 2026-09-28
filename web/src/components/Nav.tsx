"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { SPORT_TABS } from "@/lib/sports";
import { ThemeToggle } from "@/components/ThemeToggle";

export function Nav() {
  const pathname = usePathname();
  const tabs = [
    ...SPORT_TABS.map((t) => ({ href: `/s/${t.slug}`, label: t.label })),
    { href: "/review", label: "Review queue" },
  ];

  return (
    <nav className="flex w-full items-center justify-between gap-3 px-4 py-3 sm:px-6">
      <div className="flex flex-wrap items-center gap-1">
        <Link
          href="/"
          className="mr-4 text-lg font-semibold tracking-tight text-[var(--text)]"
        >
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
                  ? "rounded-lg bg-[var(--surface-strong)] px-3 py-1.5 text-sm font-medium text-[var(--text)]"
                  : "rounded-lg px-3 py-1.5 text-sm text-[var(--text-muted)] hover:bg-[var(--surface-soft)] hover:text-[var(--text)]"
              }
            >
              {t.label}
            </Link>
          );
        })}
      </div>

      <ThemeToggle />
    </nav>
  );
}
