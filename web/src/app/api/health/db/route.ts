import { NextResponse } from "next/server";
import { db } from "@/db";
import { sql } from "drizzle-orm";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const rows = await db.execute(sql`
      select
        current_database() as database,
        current_user as user_name,
        current_schema() as schema_name,
        current_setting('search_path') as search_path,
        to_regclass('games') as games_unqualified,
        to_regclass('public.games') as games_public,
        to_regclass('teams') as teams_unqualified,
        to_regclass('public.teams') as teams_public
    `);

    return NextResponse.json(
      {
        ok: true,
        env: process.env.VERCEL_ENV ?? process.env.NODE_ENV ?? "unknown",
        db: rows[0] ?? null,
      },
      { status: 200 },
    );
  } catch (error) {
    const detail =
      error && typeof error === "object"
        ? {
            message:
              "message" in error && typeof error.message === "string"
                ? error.message
                : String(error),
            code: "code" in error ? String(error.code ?? "") : undefined,
          }
        : { message: String(error) };

    return NextResponse.json(
      {
        ok: false,
        env: process.env.VERCEL_ENV ?? process.env.NODE_ENV ?? "unknown",
        error: detail,
      },
      { status: 500 },
    );
  }
}
