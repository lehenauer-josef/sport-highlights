import { eq } from "drizzle-orm";
import { db } from "@/db";
import { teams } from "@/db/schema";

export const dynamic = "force-dynamic";

// Serves logo bytes stored in the DB so images never expire like Airtable URLs.
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const teamId = Number(id);
  if (!Number.isInteger(teamId)) {
    return new Response(null, { status: 400 });
  }

  const kind =
    new URL(request.url).searchParams.get("kind") === "conference"
      ? "conference"
      : "team";

  const row = (
    await db
      .select({
        logoData: teams.logoData,
        logoMime: teams.logoMime,
        confData: teams.conferenceLogoData,
        confMime: teams.conferenceLogoMime,
      })
      .from(teams)
      .where(eq(teams.id, teamId))
      .limit(1)
  )[0];

  const data = kind === "conference" ? row?.confData : row?.logoData;
  const mime = (kind === "conference" ? row?.confMime : row?.logoMime) ?? "image/png";
  if (!data) {
    return new Response(null, { status: 404 });
  }

  const bytes = Buffer.from(data, "base64");
  return new Response(bytes, {
    headers: {
      "Content-Type": mime,
      "Cache-Control": "public, max-age=31536000, immutable",
    },
  });
}
