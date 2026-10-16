"use client";

import { useEffect, useRef, useState } from "react";

type Suggestion = { name: string; logo: string | null };

// Multi-team autocomplete: picked teams show as removable chips. Only teams
// from the suggestion list can be added (free text is never submitted).
export function TeamSearch({
  selected,
  sportSlug,
  onChange,
}: {
  selected: string[];
  sportSlug: string;
  onChange: (next: string[]) => void;
}) {
  const [value, setValue] = useState("");
  const [items, setItems] = useState<Suggestion[]>([]);
  // Query the current items belong to, so Enter never picks a stale result.
  const [itemsQuery, setItemsQuery] = useState("");
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = value.trim();
    if (q.length < 2) {
      setItems([]);
      setItemsQuery("");
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const res = await fetch(
          `/api/teams?q=${encodeURIComponent(value)}&sport=${encodeURIComponent(sportSlug)}`,
          { signal: ctrl.signal },
        );
        setItems(await res.json());
        setItemsQuery(q);
        setActive(0);
      } catch {
        /* aborted */
      }
    }, 180);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [value, sportSlug]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function add(name: string) {
    if (name && !selected.includes(name)) onChange([...selected, name]);
    setValue("");
    setItems([]);
    setItemsQuery("");
    setOpen(false);
  }

  function remove(name: string) {
    onChange(selected.filter((t) => t !== name));
  }

  const suggestions = items.filter((it) => !selected.includes(it.name));
  const fresh = itemsQuery !== "" && itemsQuery === value.trim();
  const activeIndex = Math.min(active, Math.max(suggestions.length - 1, 0));

  function addActive() {
    // Enter only adds a team from the (current) suggestion list.
    const pick = fresh ? suggestions[activeIndex] : undefined;
    if (pick) add(pick.name);
  }

  return (
    <div ref={boxRef} className="relative sm:min-w-56">
      <div className="flex flex-wrap items-center gap-1 rounded-lg border border-[var(--input-border)] bg-[var(--surface-soft)] px-2 py-1 focus-within:border-[var(--text-subtle)]">
        {selected.map((t) => (
          <span
            key={t}
            className="flex items-center gap-1 rounded bg-[var(--chip)] px-1.5 py-0.5 text-xs text-[var(--text)]"
          >
            {t}
            <button
              type="button"
              aria-label={`Remove ${t}`}
              onClick={() => remove(t)}
              className="text-[var(--text-subtle)] hover:text-[var(--text)]"
            >
              ×
            </button>
          </span>
        ))}
        <input
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addActive();
            }
            if (e.key === "ArrowDown" && suggestions.length) {
              e.preventDefault();
              setOpen(true);
              setActive((activeIndex + 1) % suggestions.length);
            }
            if (e.key === "ArrowUp" && suggestions.length) {
              e.preventDefault();
              setActive((activeIndex - 1 + suggestions.length) % suggestions.length);
            }
            if (e.key === "Escape") setOpen(false);
            if (e.key === "Backspace" && !value && selected.length) {
              remove(selected[selected.length - 1]!);
            }
          }}
          placeholder={selected.length ? "" : "Search teams…"}
          className="min-w-24 flex-1 bg-transparent px-1 py-0.5 text-base text-[var(--text)] outline-none placeholder:text-[var(--text-subtle)] sm:text-sm"
        />
      </div>

      {open && suggestions.length > 0 ? (
        <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-auto rounded-lg border border-[var(--input-border)] bg-[var(--surface-alt)] py-1 shadow-xl shadow-[var(--shadow)]">
          {suggestions.map((it, i) => (
            <li key={it.name}>
              <button
                type="button"
                onClick={() => add(it.name)}
                onMouseEnter={() => setActive(i)}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-[var(--text)] hover:bg-[var(--surface-soft)] ${
                  i === activeIndex ? "bg-[var(--surface-soft)]" : ""
                }`}
              >
                {it.logo ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={it.logo}
                    alt=""
                    className="h-5 w-5 shrink-0 object-contain"
                  />
                ) : (
                  <span className="h-5 w-5 shrink-0 rounded bg-[var(--chip-strong)]" />
                )}
                <span className="truncate">{it.name}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
