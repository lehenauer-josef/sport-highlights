import { and, asc, ilike, inArray, sql } from "drizzle-orm";
import { NextResponse } from "next/server";
import { db } from "@/db";
import { teams } from "@/db/schema";
import { conferenceTypesForSport, slugToSport } from "@/lib/sports";

type TeamSuggestion = { name: string | null; logo: string | null };

// Teams matching the query, scoped to a sport when given.
export async function GET(request: Request) {
  const url = new URL(request.url);
  const q = url.searchParams.get("q")?.trim() ?? "";
  if (q.length < 2) return NextResponse.json([]);

  const sportLabel = slugToSport(url.searchParams.get("sport") ?? "");
  const types = sportLabel ? conferenceTypesForSport(sportLabel) : null;

  const rows = await db
    .select({ id: teams.id, name: teams.name, logoUrl: teams.logoUrl })
    .from(teams)
    .where(
      and(
        ilike(teams.name, `%${q}%`),
        types && types.length
          ? inArray(teams.conferenceType, types)
          : undefined,
      ),
    )
    .orderBy(sql`(lower(${teams.name}) = lower(${q})) desc`, asc(teams.name))
    .limit(8);

  const suggestions: TeamSuggestion[] = rows.map((r) => ({
    name: r.name,
    logo: r.logoUrl ? `/api/logo/${r.id}?kind=team` : null,
  }));

  return NextResponse.json(suggestions);
}
