"use client";

import { logoSrc } from "@/lib/format";
import type { GameView } from "@/lib/games";

interface Leader {
  id: string;
  name: string;
  stat: number;
  statType: string;
  detail?: string;
}

interface GameLeadersData {
  home: Record<string, Leader | undefined>;
  away: Record<string, Leader | undefined>;
}

const CATEGORY_LABELS: Record<string, string> = {
  passingYards: "Passing Yards",
  rushingYards: "Rushing Yards",
  receivingYards: "Receiving Yards",
  tackles: "Tackles",
  sacks: "Sacks",
  interceptions: "Interceptions",
};

function playerImageSrc(playerId: string): string | null {
  const id = String(playerId || "").trim();
  if (!id) return null;
  return `https://a.espncdn.com/combiner/i?img=/i/headshots/college-football/players/full/${id}.png&h=144&w=144&scale=crop&transparent=true`;
}

export function GameLeaders({
  game,
  collapsed = false,
  onToggle,
}: {
  game: GameView;
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  if (!game.gameLeaders || typeof game.gameLeaders !== "object") {
    return null;
  }

  const leaders = game.gameLeaders as unknown as GameLeadersData;
  if (!leaders.home && !leaders.away) {
    return null;
  }

  // Collect all categories that have at least one leader
  const categories = new Set<string>();
  Object.keys(leaders.home || {}).forEach((k) => categories.add(k));
  Object.keys(leaders.away || {}).forEach((k) => categories.add(k));

  if (categories.size === 0) return null;

  const categoryOrder = [
    "passingYards",
    "rushingYards",
    "receivingYards",
    "tackles",
    "sacks",
    "interceptions",
  ];
  const sortedCategories = Array.from(categories).sort(
    (a, b) => categoryOrder.indexOf(a) - categoryOrder.indexOf(b),
  );

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--input-border)] bg-[var(--surface)]">
      <div className="border-b border-[var(--input-border)] px-4 py-3">
        <button
          type="button"
          onClick={onToggle}
          className="flex w-full items-center justify-between text-left"
          aria-expanded={!collapsed}
        >
          <div className="text-[15px] font-black uppercase tracking-[0.12em] text-[var(--text)]">
            Game Leaders
          </div>
          <span className="text-xs text-[var(--text-subtle)]">
            {collapsed ? "Show" : "Hide"}
          </span>
        </button>
      </div>

      {collapsed ? null : (
        <div className="space-y-0 px-4 py-2.5">
          {/* Team header */}
          <div className="flex items-center justify-between pb-3">
            <div className="flex items-center gap-2 text-left">
              {game.homeLogoUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={logoSrc(game.homeTeamId, "team") || game.homeLogoUrl}
                  alt=""
                  className="h-6 w-6 object-contain"
                />
              ) : (
                <div className="flex h-6 w-6 items-center justify-center rounded text-[9px] font-black uppercase text-[var(--text)]">
                  {(game.homeTeamName || "").slice(0, 2)}
                </div>
              )}
              <div className="text-xs font-bold uppercase tracking-wide text-[var(--text)]">
                {game.homeTeamName}
              </div>
            </div>

            <div className="flex items-center gap-2 text-right">
              <div className="text-xs font-bold uppercase tracking-wide text-[var(--text)]">
                {game.awayTeamName}
              </div>
              {game.awayLogoUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={logoSrc(game.awayTeamId, "team") || game.awayLogoUrl}
                  alt=""
                  className="h-6 w-6 object-contain"
                />
              ) : (
                <div className="flex h-6 w-6 items-center justify-center rounded text-[9px] font-black uppercase text-[var(--text)]">
                  {(game.awayTeamName || "").slice(0, 2)}
                </div>
              )}
            </div>
          </div>

          {/* Leaders by category */}
          {sortedCategories.map((category) => {
            const homeLeader = (leaders.home || {})[category];
            const awayLeader = (leaders.away || {})[category];
            const categoryLabel = CATEGORY_LABELS[category] || category;
            const homeHeadshot = homeLeader ? playerImageSrc(homeLeader.id) : null;
            const awayHeadshot = awayLeader ? playerImageSrc(awayLeader.id) : null;

            return (
              <div
                key={category}
                className="border-t border-[var(--input-border)] py-2.5 first:border-t-0 first:pt-0"
              >
                <div className="mb-1.5 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
                  {/* Home leader */}
                  {homeLeader ? (
                    <div className="flex items-end justify-end gap-2 text-right">
                      <div className="w-[150px] min-w-0 text-right">
                        <div className="text-xs font-bold leading-tight text-[var(--text)]">
                          {homeLeader.name}
                        </div>
                        <div className="text-[10px] text-[var(--text-muted)]">
                          {homeLeader.detail || homeLeader.statType}
                        </div>
                      </div>
                      {homeHeadshot ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={homeHeadshot}
                          alt={homeLeader.name}
                          className="h-11 w-11 shrink-0 rounded-full border border-[var(--input-border)] bg-[var(--surface)] object-cover"
                        />
                      ) : (
                        <div className="h-11 w-11 shrink-0 rounded-full border border-[var(--input-border)] bg-[var(--surface-strong)]" />
                      )}
                      <div className="shrink-0 text-lg font-black tabular-nums text-[var(--text)]">
                        {homeLeader.stat}
                      </div>
                    </div>
                  ) : (
                    <div />
                  )}

                  {/* Category label */}
                  <div className="min-w-[100px] text-center text-[10px] font-bold uppercase tracking-[0.16em] text-[var(--text-subtle)]">
                    {categoryLabel}
                  </div>

                  {/* Away leader */}
                  {awayLeader ? (
                    <div className="flex items-end gap-2 text-left">
                      <div className="shrink-0 text-lg font-black tabular-nums text-[var(--text)]">
                        {awayLeader.stat}
                      </div>
                      {awayHeadshot ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={awayHeadshot}
                          alt={awayLeader.name}
                          className="h-11 w-11 shrink-0 rounded-full border border-[var(--input-border)] bg-[var(--surface)] object-cover"
                        />
                      ) : (
                        <div className="h-11 w-11 shrink-0 rounded-full border border-[var(--input-border)] bg-[var(--surface-strong)]" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-bold leading-tight text-[var(--text)]">
                          {awayLeader.name}
                        </div>
                        <div className="text-[10px] text-[var(--text-muted)]">
                          {awayLeader.detail || awayLeader.statType}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
