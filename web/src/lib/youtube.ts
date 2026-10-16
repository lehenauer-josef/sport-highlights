import { sportForConferenceType } from "@/lib/sports";

export type YouTubeResult = {
  videoId: string;
  title: string;
  channel: string | null;
  duration: string | null;
  views: string | null;
  thumbnail: string;
};

export type YouTubeVideoInfo = {
  videoId: string;
  title: string | null;
  channel: string | null;
  duration: string | null;
  views: string | null;
};

const FETCH_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
  "Accept-Language": "en-US,en;q=0.9",
  // Skip the EU consent interstitial so we get real results markup.
  cookie: "CONSENT=YES+1",
};

function ymd(d: Date): string {
  return d.toISOString().slice(0, 10);
}

// YouTube search URL: away vs home + sport + highlights,
// windowed to the days around the game (before: +10d, after: -1d).
export function youtubeSearchUrl(opts: {
  awayTeamName: string | null;
  homeTeamName: string | null;
  gameDate: Date | string | null;
  conferenceType: string | null;
}): string {
  const away = encodeURIComponent(opts.awayTeamName ?? "");
  const home = encodeURIComponent(opts.homeTeamName ?? "");
  const sport = sportForConferenceType(opts.conferenceType) ?? "";
  const sportTerm = encodeURIComponent(sport).replace(/%20/g, "+");
  const base = opts.gameDate ? new Date(opts.gameDate) : new Date();
  const before = new Date(base);
  before.setDate(before.getDate() + 10);
  const after = new Date(base);
  after.setDate(after.getDate() - 1);
  const query =
    `${away}+vs+${home}+${sportTerm}+highlights` +
    `+before%3A${ymd(before)}+after%3A${ymd(after)}`;
  return `https://www.youtube.com/results?search_query=${query}`;
}

type VideoRenderer = {
  videoId?: string;
  title?: { runs?: { text?: string }[]; simpleText?: string };
  ownerText?: { runs?: { text?: string }[] };
  longBylineText?: { runs?: { text?: string }[] };
  lengthText?: { simpleText?: string; runs?: { text?: string }[] };
  viewCountText?: { simpleText?: string; runs?: { text?: string }[] };
  shortViewCountText?: { simpleText?: string; runs?: { text?: string }[] };
};

function textOf(
  v: { simpleText?: string; runs?: { text?: string }[] } | undefined,
): string | null {
  if (!v) return null;
  if (v.simpleText) return v.simpleText;
  const joined = (v.runs ?? []).map((r) => r.text ?? "").join("");
  return joined || null;
}

function formatSeconds(total: number): string {
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

function formatViews(count: number): string {
  const n = new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(count);
  return `${n} ${count === 1 ? "view" : "views"}`;
}

function collectVideos(
  node: unknown,
  out: YouTubeResult[],
  seen: Set<string>,
  limit: number,
): void {
  if (out.length >= limit || node == null || typeof node !== "object") return;
  const obj = node as Record<string, unknown>;
  const vr = obj.videoRenderer as VideoRenderer | undefined;
  if (vr?.videoId && !seen.has(vr.videoId)) {
    const title =
      vr.title?.runs?.[0]?.text ?? vr.title?.simpleText ?? "(untitled)";
    const channel =
      vr.ownerText?.runs?.[0]?.text ??
      vr.longBylineText?.runs?.[0]?.text ??
      null;
    const duration =
      vr.lengthText?.simpleText ?? vr.lengthText?.runs?.[0]?.text ?? null;
    const rawViews =
      textOf(vr.shortViewCountText) ?? textOf(vr.viewCountText) ?? null;
    const views =
      rawViews && !/view/i.test(rawViews) ? `${rawViews} views` : rawViews;
    seen.add(vr.videoId);
    out.push({
      videoId: vr.videoId,
      title,
      channel,
      duration,
      views,
      thumbnail: `https://i.ytimg.com/vi/${vr.videoId}/hqdefault.jpg`,
    });
  }
  for (const value of Object.values(obj)) {
    if (out.length >= limit) return;
    if (value && typeof value === "object") {
      collectVideos(value, out, seen, limit);
    }
  }
}

// Best-effort scrape of the first N results from a YouTube search page.
// YouTube can change its markup at any time, so callers must handle [].
export async function searchYouTube(
  url: string,
  limit = 3,
): Promise<YouTubeResult[]> {
  let html: string;
  try {
    const res = await fetch(url, {
      headers: FETCH_HEADERS,
      cache: "no-store",
    });
    if (!res.ok) return [];
    html = await res.text();
  } catch {
    return [];
  }

  const match =
    html.match(/var ytInitialData\s*=\s*(\{.+?\})\s*;\s*<\/script>/s) ??
    html.match(/ytInitialData\s*=\s*(\{.+?\})\s*;\s*<\/script>/s);
  if (!match) return [];

  let data: unknown;
  try {
    data = JSON.parse(match[1]);
  } catch {
    return [];
  }

  const out: YouTubeResult[] = [];
  collectVideos(data, out, new Set<string>(), limit);
  return out.slice(0, limit);
}

type PlayerResponse = {
  videoDetails?: {
    title?: string;
    author?: string;
    lengthSeconds?: string;
    viewCount?: string;
  };
};

// Best-effort scrape of a single video's channel, duration and view count
// from its watch page. Returns null if YouTube's markup can't be parsed.
export async function fetchVideoInfo(
  videoId: string,
): Promise<YouTubeVideoInfo | null> {
  let html: string;
  try {
    const res = await fetch(
      `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`,
      { headers: FETCH_HEADERS, cache: "no-store" },
    );
    if (!res.ok) return null;
    html = await res.text();
  } catch {
    return null;
  }

  const match = html.match(
    /ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;\s*(?:var\s|<\/script>)/s,
  );
  if (!match) return null;

  let data: PlayerResponse;
  try {
    data = JSON.parse(match[1]);
  } catch {
    return null;
  }

  const vd = data.videoDetails;
  if (!vd) return null;
  const seconds = Number(vd.lengthSeconds);
  const views = Number(vd.viewCount);
  return {
    videoId,
    title: vd.title ?? null,
    channel: vd.author ?? null,
    duration: seconds > 0 ? formatSeconds(seconds) : null,
    views:
      vd.viewCount != null && Number.isFinite(views) ? formatViews(views) : null,
  };
}

// Extract an 11-char video id from a raw id or any common YouTube URL form.
export function parseVideoId(input: string): string | null {
  const s = input.trim();
  if (!s) return null;
  const patterns = [
    /[?&]v=([\w-]{11})/,
    /youtu\.be\/([\w-]{11})/,
    /youtube\.com\/embed\/([\w-]{11})/,
    /youtube\.com\/shorts\/([\w-]{11})/,
  ];
  for (const re of patterns) {
    const m = s.match(re);
    if (m) return m[1];
  }
  return /^[\w-]{11}$/.test(s) ? s : null;
}
