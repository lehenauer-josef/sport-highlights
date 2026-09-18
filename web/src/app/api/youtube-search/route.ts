import { eq } from "drizzle-orm";
import { NextResponse } from "next/server";
import { db } from "@/db";
import { games } from "@/db/schema";
import { awayTeam, gameColumns, homeTeam } from "@/lib/games";
import { searchYouTube, youtubeSearchUrl } from "@/lib/youtube";

export const dynamic = "force-dynamic";

// First few YouTube search results for a game's highlights, plus the search URL.
export async function GET(request: Request) {
  const id = Number(new URL(request.url).searchParams.get("id"));
  if (!id) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }

  const [game] = await db
    .select(gameColumns)
    .from(games)
    .leftJoin(homeTeam, eq(games.homeTeamId, homeTeam.id))
    .leftJoin(awayTeam, eq(games.awayTeamId, awayTeam.id))
    .where(eq(games.id, id));

  if (!game) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  const url = youtubeSearchUrl({
    awayTeamName: game.awayTeamName,
    homeTeamName: game.homeTeamName,
    gameDate: game.gameDate,
    conferenceType: game.conferenceType,
  });
  const items = await searchYouTube(url, 5);
  return NextResponse.json({ url, items });
}
