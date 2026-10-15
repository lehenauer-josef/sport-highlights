import { eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { revalidatePath } from "next/cache";
import { db } from "@/db";
import { games } from "@/db/schema";
import { parseVideoId } from "@/lib/youtube";

// Update a game's review outcome: approve current, reject, accept the scorer's
// proposed better match, or set a hand-picked video id as the current highlight.
export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const id = Number(body?.id);
  const action = String(body?.action ?? "");
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
        betterVideoId: null,
        highlightsValid: true,
        reviewStatus: "approved",
      })
      .where(eq(games.id, id));
  }

  revalidatePath("/review");

  return NextResponse.json({ ok: true });
}
