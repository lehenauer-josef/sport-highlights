"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { formatDate, logoSrc, youtubeThumb, youtubeUrl } from "@/lib/format";
import type { GameView } from "@/lib/games";
import { shortSportLabel } from "@/lib/sports";
import { FormHover } from "@/components/TeamForm";

function TeamLine({
  name,
  rank,
  logo,
  conferenceLogo,
  record,
  gameId,
  side,
}: {
  name: string | null;
  rank: number | null;
  logo: string | null;
  conferenceLogo: string | null;
  record: string | null;
  gameId: number;
  side: "home" | "away";
}) {
  return (
    <div className="flex items-center gap-2">
      {logo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={logo} alt="" className="h-7 w-7 shrink-0 object-contain" />
      ) : (
        <div className="h-7 w-7 shrink-0 rounded bg-white/10" />
      )}
      <span className="truncate text-[15px] font-semibold">
        {rank ? <span className="text-white/50">#{rank} </span> : null}
        {name}
        {record ? (
          <span className="text-sm font-normal text-white/40"> ({record})</span>
        ) : null}
      </span>
      {conferenceLogo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={conferenceLogo}
          alt=""
          title="Conference"
          className="h-4 w-4 shrink-0 object-contain opacity-80"
        />
      ) : null}
      <span className="ml-auto">
        <FormHover gameId={gameId} side={side} />
      </span>
    </div>
  );
}

export function HighlightCard({ game }: { game: GameView }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const videoId = game.videoId;
  const thumb = youtubeThumb(videoId) ?? game.thumbnailUrl;

  function openDetail() {
    const next = new URLSearchParams(params.toString());
    next.set("game", String(game.id));
    router.push(`${pathname}?${next.toString()}`, { scroll: false });
  }

  return (
    <div
      onClick={openDetail}
      className="group/card cursor-pointer rounded-xl border border-white/10 bg-white/[0.03] transition hover:border-white/25 hover:bg-white/[0.06]"
    >
      <div className="relative h-24 overflow-hidden rounded-t-xl bg-black sm:h-28">
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-white/30">
            No video
          </div>
        )}
        <div className="absolute left-2 top-2 flex gap-1">
          {shortSportLabel(game.conferenceType) ? (
            <span className="rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-white/80">
              {shortSportLabel(game.conferenceType)}
            </span>
          ) : null}
          {game.overtime ? (
            <span className="rounded bg-amber-500/80 px-1.5 py-0.5 text-[10px] font-semibold text-black">
              OT
            </span>
          ) : null}
          {!game.highlightsChecked ? (
            <span className="rounded bg-red-500/80 px-1.5 py-0.5 text-[10px] font-semibold text-black">
              needs review
            </span>
          ) : null}
        </div>
      </div>

      <div className="space-y-3 p-4">
        <div className="space-y-1.5">
          <TeamLine
            name={game.awayTeamName}
            rank={game.awayRank}
            logo={game.awayLogoUrl ? logoSrc(game.awayTeamId, "team") : null}
            conferenceLogo={
              game.awayConferenceLogoUrl
                ? logoSrc(game.awayTeamId, "conference")
                : null
            }
            record={game.awayRecord}
            gameId={game.id}
            side="away"
          />
          <TeamLine
            name={game.homeTeamName}
            rank={game.homeRank}
            logo={game.homeLogoUrl ? logoSrc(game.homeTeamId, "team") : null}
            conferenceLogo={
              game.homeConferenceLogoUrl
                ? logoSrc(game.homeTeamId, "conference")
                : null
            }
            record={game.homeRecord}
            gameId={game.id}
            side="home"
          />
        </div>

        <div className="flex items-center justify-between text-sm text-white/60">
          <span>
            {game.season ? `${game.season}` : ""}
            {game.week ? ` · Wk ${game.week}` : ""}
            {game.gameDate ? ` · ${formatDate(game.gameDate)}` : ""}
          </span>
          {game.excitementIndex != null ? (
            <span title="Excitement Index">
              🔥 {Number(game.excitementIndex).toFixed(1)}
            </span>
          ) : null}
        </div>

        <div className="flex items-center justify-between border-t border-white/10 pt-3 text-xs">
          <span className="font-medium text-white/70 transition group-hover/card:text-white">
            View details →
          </span>
          {videoId ? (
            <a
              href={youtubeUrl(videoId) ?? "#"}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="text-white/50 hover:text-white"
            >
              YouTube ↗
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );
}
