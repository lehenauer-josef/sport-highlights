import { NextResponse } from "next/server";
import { fetchTeamForm } from "@/lib/games";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const n = Number(id);
  if (!Number.isInteger(n) || n <= 0) {
    return NextResponse.json({ error: "invalid id" }, { status: 400 });
  }
  const form = await fetchTeamForm(n);
  return NextResponse.json(form);
}
