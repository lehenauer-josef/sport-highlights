"use client";

import { useEffect, useRef, useState } from "react";

export type Option = { value: string; label: string };

// Checkbox dropdown for choosing several values at once.
export function MultiSelect({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: Option[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function toggle(value: string) {
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value],
    );
  }

  const summary =
    selected.length === 0 ? label : `${label}: ${selected.length}`;

  return (
    <div ref={boxRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-lg border border-[var(--input-border)] bg-[var(--surface-soft)] px-3 py-1.5 text-sm outline-none focus:border-[var(--text-subtle)]"
      >
        <span className={selected.length ? "text-[var(--text)]" : "text-[var(--text-muted)]"}>
          {summary}
        </span>
        <span className="text-[var(--text-subtle)]">▾</span>
      </button>
      {open ? (
        <div className="absolute z-20 mt-1 max-h-72 w-44 overflow-auto rounded-lg border border-[var(--input-border)] bg-[var(--surface-alt)] p-1 shadow-xl shadow-[var(--shadow)]">
          {selected.length > 0 ? (
            <button
              type="button"
              onClick={() => onChange([])}
              className="mb-1 w-full rounded px-2 py-1 text-left text-xs text-[var(--text-muted)] hover:bg-[var(--surface-soft)]"
            >
              Clear
            </button>
          ) : null}
          {options.map((o) => (
            <label
              key={o.value}
              className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm text-[var(--text)] hover:bg-[var(--surface-soft)]"
            >
              <input
                type="checkbox"
                checked={selected.includes(o.value)}
                onChange={() => toggle(o.value)}
                className="accent-[var(--text)]"
              />
              <span>{o.label}</span>
            </label>
          ))}
        </div>
      ) : null}
    </div>
  );
}
