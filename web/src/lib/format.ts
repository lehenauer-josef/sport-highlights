import type { Game } from "@/db/schema";

export function youtubeUrl(videoId: string | null): string | null {
  return videoId ? `https://www.youtube.com/watch?v=${videoId}` : null;
}

export function youtubeThumb(videoId: string | null): string | null {
  return videoId ? `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg` : null;
}

// Stable logo URL backed by bytes stored in the DB (never expires).
export function logoSrc(
  teamId: number | null | undefined,
  kind: "team" | "conference",
): string | null {
  return teamId ? `/api/logo/${teamId}?kind=${kind}` : null;
}

export function scoreLine(game: Game): string | null {
  if (game.homePoints == null || game.awayPoints == null) return null;
  return `${game.awayPoints} – ${game.homePoints}`;
}

export function formatDate(date: Date | string | null): string {
  if (!date) return "";
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// A game needs review when it has no valid highlight, or the scorer proposed a
// better match, unless it was manually approved/rejected.
export function needsReview(game: Game): boolean {
  if (game.reviewStatus === "approved" || game.reviewStatus === "rejected") {
    return false;
  }
  return !game.highlightsValid || Boolean(game.betterVideoId);
}
