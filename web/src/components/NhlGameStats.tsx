"use client";

import { useState, type CSSProperties, type ReactNode } from "react";
import { logoSrc } from "@/lib/format";
import type { GameView } from "@/lib/games";

interface NhlPerson {
  id: string | null;
  name: string;
  headshot: string | null;
  total?: number | null;
}

interface NhlGoal {
  time: string | null;
  strength: string | null;
  modifier: string | null;
  team: string | null;
  isHome: boolean;
  homeScore: number | null;
  awayScore: number | null;
  scorer: NhlPerson;
  assists: NhlPerson[];
  clipUrl: string | null;
}

interface NhlPeriod {
  number: number | null;
  type: string | null;
  goals: NhlGoal[];
}

interface NhlShootoutAttempt {
  sequence: number | null;
  team: string | null;
  isHome: boolean;
  id: string | null;
  name: string;
  headshot: string | null;
  result: string | null;
  gameWinner: boolean;
}

interface NhlStar {
  star: number;
  id?: string;
  name: string;
  headshot?: string;
  team?: string;
  isHome?: boolean;
  position?: string;
  sweaterNo?: number;
  goals?: number;
  assists?: number;
  points?: number;
  savePct?: number;
  gaa?: number;
}

export interface NhlStory {
  sport: "NHL";
  homeTeam: string | null;
  awayTeam: string | null;
  periods: NhlPeriod[];
  shootout: NhlShootoutAttempt[];
  threeStars: NhlStar[];
}

export function nhlStory(game: GameView): NhlStory | null {
  const raw = game.gameLeaders as Partial<NhlStory> | null;
  if (!raw || raw.sport !== "NHL") return null;
  return {
    sport: "NHL",
    homeTeam: raw.homeTeam ?? null,
    awayTeam: raw.awayTeam ?? null,
    periods: Array.isArray(raw.periods) ? raw.periods : [],
    shootout: Array.isArray(raw.shootout) ? raw.shootout : [],
    threeStars: Array.isArray(raw.threeStars) ? raw.threeStars : [],
  };
}

function ordinal(n: number): string {
  const suffix = n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] ?? "th";
  return `${n}${suffix}`;
}

function periodLabel(period: NhlPeriod): string {
  const n = period.number ?? 0;
  if (period.type === "OT") {
    const ot = n - 3;
    return ot > 1 ? `${ordinal(ot)} Overtime` : "Overtime";
  }
  return n ? `${ordinal(n)} Period` : "Period";
}

const POSITIONS: Record<string, string> = { L: "LW", R: "RW" };

const STAR_COLORS = ["#f5b301", "#a3acb9", "#cd7f32"];

function Panel({
  title,
  collapsed,
  onToggle,
  children,
}: {
  title: string;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
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
            {title}
          </div>
          <span className="text-xs text-[var(--text-subtle)]">{collapsed ? "Show" : "Hide"}</span>
        </button>
      </div>
      {collapsed ? null : <div className="px-4 py-3">{children}</div>}
    </div>
  );
}

function Avatar({
  src,
  name,
  className,
  style,
}: {
  src: string | null | undefined;
  name: string;
  className: string;
  style?: CSSProperties;
}) {
  const [failed, setFailed] = useState(false);
  const initials = name
    .split(/\s+/)
    .map((part) => part[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  const base = `shrink-0 rounded-full border border-[var(--input-border)] ${className}`;

  if (!src || failed) {
    return (
      <div
        className={`${base} flex items-center justify-center bg-[var(--surface-strong)] text-[10px] font-black text-[var(--text-muted)]`}
        style={style}
      >
        {initials}
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={name}
      onError={() => setFailed(true)}
      className={`${base} bg-[var(--surface-strong)] object-cover object-top`}
      style={style}
    />
  );
}

function TeamLogo({ game, isHome, className }: { game: GameView; isHome: boolean; className: string }) {
  const url = isHome
    ? game.homeLogoUrl && logoSrc(game.homeTeamId, "team")
    : game.awayLogoUrl && logoSrc(game.awayTeamId, "team");
  if (!url) return null;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt="" className={`object-contain ${className}`} />;
}

function Badge({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "warning" | "success" }) {
  const color =
    tone === "warning"
      ? "text-[var(--warning)]"
      : tone === "success"
        ? "text-[var(--success)]"
        : "text-[var(--text-muted)]";
  return (
    <span
      className={`rounded bg-[var(--chip-strong)] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${color}`}
    >
      {children}
    </span>
  );
}

function goalBadges(goal: NhlGoal) {
  const badges: ReactNode[] = [];
  if (goal.strength === "pp") badges.push(<Badge key="pp" tone="warning">PPG</Badge>);
  if (goal.strength === "sh") badges.push(<Badge key="sh" tone="success">SHG</Badge>);
  if (goal.modifier === "empty-net") badges.push(<Badge key="en">EN</Badge>);
  if (goal.modifier === "penalty-shot") badges.push(<Badge key="ps">PS</Badge>);
  if (goal.modifier === "own-goal") badges.push(<Badge key="og">OG</Badge>);
  return badges;
}

function RunningScore({ goal, story }: { goal: NhlGoal; story: NhlStory }) {
  const strong = "text-[var(--text)]";
  const weak = "text-[var(--text-subtle)]";
  return (
    <div className="whitespace-nowrap text-sm font-black tabular-nums">
      {story.awayTeam ? (
        <span className={`mr-1 text-[10px] font-bold tracking-wide ${goal.isHome ? weak : strong}`}>
          {story.awayTeam}
        </span>
      ) : null}
      <span className={goal.isHome ? weak : strong}>{goal.awayScore ?? "–"}</span>
      <span className="mx-1 text-[var(--text-subtle)]">–</span>
      <span className={goal.isHome ? strong : weak}>{goal.homeScore ?? "–"}</span>
      {story.homeTeam ? (
        <span className={`ml-1 text-[10px] font-bold tracking-wide ${goal.isHome ? strong : weak}`}>
          {story.homeTeam}
        </span>
      ) : null}
    </div>
  );
}

function GoalRow({ goal, game, story }: { goal: NhlGoal; game: GameView; story: NhlStory }) {
  return (
    <div className="flex items-center gap-3 rounded-lg px-1 py-2 transition hover:bg-[var(--surface-soft)]">
      <div className="w-10 shrink-0 text-xs font-medium tabular-nums text-[var(--text-muted)]">
        {goal.time ?? ""}
      </div>

      <div className="relative shrink-0">
        <Avatar src={goal.scorer.headshot} name={goal.scorer.name} className="h-11 w-11" />
        <span className="absolute -bottom-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full border border-[var(--input-border)] bg-[var(--surface)] p-0.5">
          <TeamLogo game={game} isHome={goal.isHome} className="h-full w-full" />
        </span>
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
          <span className="text-sm font-bold leading-tight text-[var(--text)]">{goal.scorer.name}</span>
          {goal.scorer.total != null ? (
            <span className="text-xs tabular-nums text-[var(--text-muted)]">({goal.scorer.total})</span>
          ) : null}
          {goalBadges(goal)}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          {goal.assists.length ? (
            goal.assists.map((assist, index) => (
              <span key={`${assist.id ?? assist.name}-${index}`} className="flex items-center gap-1.5">
                <Avatar src={assist.headshot} name={assist.name} className="h-5 w-5 text-[7px]" />
                <span className="text-[11px] text-[var(--text-muted)]">
                  {assist.name}
                  {assist.total != null ? <span className="tabular-nums"> ({assist.total})</span> : null}
                </span>
              </span>
            ))
          ) : (
            <span className="text-[11px] italic text-[var(--text-subtle)]">Unassisted</span>
          )}
        </div>
      </div>

      <div className="flex shrink-0 flex-col items-end gap-1">
        <RunningScore goal={goal} story={story} />
        {goal.clipUrl ? (
          <a
            href={goal.clipUrl}
            target="_blank"
            rel="noreferrer"
            className="text-[10px] font-semibold uppercase tracking-wide text-[var(--text-subtle)] hover:text-[var(--text)]"
          >
            ▶ Clip
          </a>
        ) : null}
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 pb-1">
      <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-[var(--text-subtle)]">
        {children}
      </span>
      <div className="h-px flex-1 bg-[var(--input-border)]" />
    </div>
  );
}

export function NhlScoring({
  game,
  story,
  showResults,
  collapsed,
  onToggle,
}: {
  game: GameView;
  story: NhlStory;
  showResults: boolean;
  collapsed: boolean;
  onToggle: () => void;
}) {
  if (!story.periods.length && !story.shootout.length) return null;

  return (
    <Panel title="Scoring" collapsed={collapsed} onToggle={onToggle}>
      {!showResults ? (
        <div className="py-3 text-center text-xs text-[var(--text-subtle)]">
          Goals are hidden. Turn on “Show result” to see the scoring summary.
        </div>
      ) : (
        <div className="space-y-3">
          {story.periods.map((period) => (
            <section key={`${period.type}-${period.number}`}>
              <SectionLabel>{periodLabel(period)}</SectionLabel>
              {period.goals.length ? (
                period.goals.map((goal, index) => (
                  <GoalRow key={index} goal={goal} game={game} story={story} />
                ))
              ) : (
                <div className="px-1 py-2 text-xs text-[var(--text-subtle)]">No goals</div>
              )}
            </section>
          ))}

          {story.shootout.length ? (
            <section>
              <SectionLabel>Shootout</SectionLabel>
              <div className="grid gap-x-6 sm:grid-cols-2">
                {story.shootout.map((attempt, index) => {
                  const scored = attempt.result === "goal";
                  return (
                    <div
                      key={`${attempt.sequence}-${index}`}
                      className="flex items-center gap-2 border-b border-[var(--input-border)]/50 py-1.5 last:border-b-0"
                    >
                      <span className="w-4 text-right text-[10px] tabular-nums text-[var(--text-subtle)]">
                        {attempt.sequence ?? index + 1}
                      </span>
                      <TeamLogo game={game} isHome={attempt.isHome} className="h-4 w-4 shrink-0" />
                      <Avatar src={attempt.headshot} name={attempt.name} className="h-7 w-7 text-[8px]" />
                      <span
                        className={`min-w-0 flex-1 truncate text-xs ${scored ? "font-bold text-[var(--text)]" : "text-[var(--text-muted)]"}`}
                      >
                        {attempt.name}
                      </span>
                      {attempt.gameWinner ? <Badge tone="warning">Winner</Badge> : null}
                      <span
                        className={`w-10 text-right text-[10px] font-bold uppercase tracking-wide ${scored ? "text-[var(--success)]" : "text-[var(--text-subtle)]"}`}
                      >
                        {scored ? "Goal" : attempt.result === "save" ? "Save" : "Miss"}
                      </span>
                    </div>
                  );
                })}
              </div>
            </section>
          ) : null}
        </div>
      )}
    </Panel>
  );
}

function StarStat({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="flex flex-col items-center px-1">
      <span className="text-base font-black leading-tight tabular-nums text-[var(--text)]">{value}</span>
      <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-[var(--text-subtle)]">{label}</span>
    </div>
  );
}

export function NhlThreeStars({
  game,
  story,
  collapsed,
  onToggle,
}: {
  game: GameView;
  story: NhlStory;
  collapsed: boolean;
  onToggle: () => void;
}) {
  if (!story.threeStars.length) return null;

  return (
    <Panel title="Three Stars" collapsed={collapsed} onToggle={onToggle}>
      <div className="grid gap-3 sm:grid-cols-3">
        {story.threeStars.map((star) => {
          const color = STAR_COLORS[star.star - 1] ?? STAR_COLORS[2];
          const goalie = star.position === "G";
          const position = star.position ? POSITIONS[star.position] ?? star.position : null;
          const meta = [star.sweaterNo != null ? `#${star.sweaterNo}` : null, position, star.team]
            .filter(Boolean)
            .join(" · ");
          type StarStatValue = { label: string; value: string | number } | null;
          const stats: StarStatValue[] = goalie
            ? [
                star.savePct != null
                  ? { label: "SV%", value: star.savePct.toFixed(3).replace(/^0/, "") }
                  : null,
                star.gaa != null ? { label: "GAA", value: star.gaa.toFixed(2) } : null,
              ]
            : [
                star.goals != null ? { label: "G", value: star.goals } : null,
                star.assists != null ? { label: "A", value: star.assists } : null,
                star.points != null ? { label: "P", value: star.points } : null,
              ];
          const visible = stats.filter((s) => s != null);

          return (
            <div
              key={`${star.star}-${star.id ?? star.name}`}
              className="flex flex-col items-center rounded-xl border border-[var(--input-border)] bg-[var(--surface-soft)] px-3 pb-3 pt-3 text-center"
            >
              <div className="mb-2 flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.16em]">
                <span style={{ color }} aria-hidden>
                  ★
                </span>
                <span className="text-[var(--text-subtle)]">{ordinal(star.star)} Star</span>
              </div>

              <div className="relative">
                <Avatar
                  src={star.headshot}
                  name={star.name}
                  className="h-20 w-20 border-2 text-base"
                  style={{ borderColor: color }}
                />
                {star.isHome != null ? (
                  <span className="absolute -bottom-1 -right-1 flex h-7 w-7 items-center justify-center rounded-full border border-[var(--input-border)] bg-[var(--surface)] p-1">
                    <TeamLogo game={game} isHome={star.isHome} className="h-full w-full" />
                  </span>
                ) : null}
              </div>

              <div className="mt-2 text-sm font-bold leading-tight text-[var(--text)]">{star.name}</div>
              {meta ? (
                <div className="mt-0.5 text-[10px] uppercase tracking-wide text-[var(--text-subtle)]">{meta}</div>
              ) : null}

              {visible.length ? (
                <div
                  className={`mt-3 grid w-full divide-x divide-[var(--input-border)] rounded-lg bg-[var(--chip)] py-1.5 ${visible.length === 3 ? "grid-cols-3" : visible.length === 2 ? "grid-cols-2" : "grid-cols-1"}`}
                >
                  {visible.map((stat) => (
                    <StarStat key={stat.label} value={stat.value} label={stat.label} />
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
