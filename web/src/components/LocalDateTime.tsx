"use client";

import { useSyncExternalStore } from "react";
import { formatDateTime } from "@/lib/format";

const subscribe = () => () => {};

// Locale/time-zone formatting differs between the server and the viewer's
// browser, so the date is only rendered on the client after hydration.
export function LocalDateTime({
  date,
  prefix = "",
}: {
  date: Date | string | null;
  prefix?: string;
}) {
  const isClient = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
  if (!date || !isClient) return null;
  const iso = (typeof date === "string" ? new Date(date) : date).toISOString();
  return (
    <>
      {prefix}
      <time dateTime={iso}>{formatDateTime(date)}</time>
    </>
  );
}
