import { NextResponse } from "next/server";
import { fetchVideoInfo, parseVideoId } from "@/lib/youtube";

export const dynamic = "force-dynamic";

// Channel, duration and view count for a single YouTube video.
export async function GET(request: Request) {
  const raw = new URL(request.url).searchParams.get("v") ?? "";
  const videoId = parseVideoId(raw);
  if (!videoId) {
    return NextResponse.json({ error: "invalid video id" }, { status: 400 });
  }

  const info = await fetchVideoInfo(videoId);
  if (!info) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json(info);
}
