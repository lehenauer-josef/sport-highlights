import { NextResponse } from "next/server";
import { fetchGames, parseFilters } from "@/lib/games";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const filters = parseFilters(new URL(request.url).searchParams);
  const { rows, hasMore } = await fetchGames(filters);
  return NextResponse.json({ rows, hasMore });
}
