import { eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { revalidatePath } from "next/cache";
import { db } from "@/db";
import { games } from "@/db/schema";
import {
  fetchGameById,
  fetchReviewGames,
  parseFilters,
  validateReviewGames,
} from "@/lib/games";
import { parseVideoId } from "@/lib/youtube";

export const dynamic = "force-dynamic";

// Further review-queue pages for infinite scroll: same filters as the page,
// plus "all=1" (include checked games) and "offset" (cards already shown).
export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const filters = parseFilters(params);
  const { rows, hasMore } = await fetchReviewGames(filters, {
    showAll: params.get("all") === "1",
    offset: Number(params.get("offset")) || 0,
  });
  return NextResponse.json({ rows, hasMore });
}

// Update a game's review outcome: approve current, reject, accept the scorer's
// proposed better match, or set a hand-picked video id as the current highlight.
// Bulk: "validate_many" approves the given ids; "validate_all" approves every
// validatable game matching the queue filters in "query".
export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const action = String(body?.action ?? "");

  if (action === "validate_many" || action === "validate_all") {
    let ids: number[];
    if (action === "validate_many") {
      const raw: unknown[] = Array.isArray(body?.ids) ? body.ids : [];
      const requested = raw.map(Number).filter((n) => Number.isInteger(n) && n > 0);
      if (!requested.length) {
        return NextResponse.json({ error: "no ids" }, { status: 400 });
      }
      ids = await validateReviewGames({ ids: requested });
    } else {
      const filters = parseFilters(new URLSearchParams(String(body?.query ?? "")));
      if (!filters.sportLabel) {
        return NextResponse.json({ error: "invalid filters" }, { status: 400 });
      }
      ids = await validateReviewGames({ filters });
    }
    revalidatePath("/review");
    return NextResponse.json({ ok: true, ids });
  }

  const id = Number(body?.id);
  if (
    !id ||
    !["approve", "reject", "accept_better", "set_video", "unvalidate"].includes(
      action,
    )
  ) {
    return NextResponse.json({ error: "invalid request" }, { status: 400 });
  }

  if (action === "approve") {
    await db
      .update(games)
      .set({
        reviewStatus: "approved",
        highlightsValid: true,
        highlightsChecked: true,
      })
      .where(eq(games.id, id));
  } else if (action === "unvalidate") {
    await db
      .update(games)
      .set({ highlightsChecked: false, reviewStatus: "pending" })
      .where(eq(games.id, id));
  } else if (action === "reject") {
    await db
      .update(games)
      .set({ reviewStatus: "rejected" })
      .where(eq(games.id, id));
  } else if (action === "set_video") {
    const videoId = parseVideoId(String(body?.videoId ?? ""));
    if (!videoId) {
      return NextResponse.json({ error: "invalid video id" }, { status: 400 });
    }
    await db
      .update(games)
      .set({
        videoId,
        highlightScore: null,
        betterVideoId: null,
        highlightsValid: true,
        highlightsChecked: true,
        reviewStatus: "approved",
      })
      .where(eq(games.id, id));
  } else {
    const [game] = await db
      .select({ betterVideoId: games.betterVideoId })
      .from(games)
      .where(eq(games.id, id));
    if (!game?.betterVideoId) {
      return NextResponse.json({ error: "no better match" }, { status: 400 });
    }
    await db
      .update(games)
      .set({
        videoId: game.betterVideoId,
        highlightScore: null,
        betterVideoId: null,
        highlightsValid: true,
        reviewStatus: "approved",
      })
      .where(eq(games.id, id));
  }

  revalidatePath("/review");

  // The queue updates (or drops) this card from the returned row.
  return NextResponse.json({ ok: true, game: await fetchGameById(id) });
}
