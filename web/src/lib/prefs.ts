"use client";

import { useSyncExternalStore } from "react";

const KEY = "cfb:showResults";
let value = true;
let initialized = false;
const listeners = new Set<() => void>();

function read(): boolean {
  if (typeof window === "undefined") return true;
  const v = window.localStorage.getItem(KEY);
  return v == null ? true : v === "1";
}

function ensureInit() {
  if (initialized || typeof window === "undefined") return;
  initialized = true;
  value = read();
  window.addEventListener("storage", (e) => {
    if (e.key === KEY) {
      value = read();
      listeners.forEach((l) => l());
    }
  });
}

export function setShowResults(next: boolean) {
  ensureInit();
  value = next;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(KEY, next ? "1" : "0");
  }
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void) {
  ensureInit();
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

// Persisted, app-wide preference used by every game detail view.
export function useShowResults(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => {
      ensureInit();
      return value;
    },
    () => true,
  );
}
