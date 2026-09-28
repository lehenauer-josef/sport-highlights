"use client";

import { useEffect, useState } from "react";

const THEME_STORAGE_KEY = "theme";
type ThemeMode = "dark" | "light";

export function ThemeToggle() {
  const [theme, setTheme] = useState<ThemeMode>("dark");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY) as
      | ThemeMode
      | null;
    const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)")
      .matches;
    const nextTheme = savedTheme || (systemPrefersDark ? "dark" : "light");

    setTheme(nextTheme);
    document.documentElement.setAttribute("data-theme", nextTheme);
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [mounted, theme]);

  const isDark = theme === "dark";

  return (
    <button
      type="button"
      aria-label={`Switch to ${isDark ? "light" : "dark"} theme`}
      aria-pressed={!isDark}
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="group inline-flex items-center"
    >
      <span className="relative inline-flex h-7 w-12 items-center rounded-full border border-[var(--border)] bg-[var(--surface-soft)] p-1 shadow-inner">
        <span
          className={`absolute left-1 h-5 w-5 rounded-full bg-gradient-to-br from-amber-200 to-yellow-400 text-[10px] shadow-sm transition-transform duration-200 ${
            isDark ? "translate-x-0" : "translate-x-5"
          }`}
          aria-hidden="true"
        >
          <span className="flex h-full items-center justify-center">
            {isDark ? "☾" : "☀"}
          </span>
        </span>
        <span className="flex w-full justify-between px-1 text-[9px] text-[var(--text-muted)]">
          <span aria-hidden="true">☀</span>
          <span aria-hidden="true">☾</span>
        </span>
      </span>
    </button>
  );
}
