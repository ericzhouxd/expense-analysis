import { type ReactNode, useEffect, useId, useRef } from "react";

import type { Budget, Comparison, Week } from "../api";
import { compactMoney, money, plural, rangeLabel, wholeMoney } from "../lib/format";
import { LED, rgba } from "../lib/glyphs";
import { DotPattern, Glass, PanelDefs, type Reading, ReadoutBar, usePreview, useWidth, Well } from "./charts";
import { Delta, HeroNumber, Lamps, PaceMeter, Pips, Readout } from "./instrument";

/** Storage keeps the original treatment names; people see these. */
export const TREATMENT_LABEL: Record<string, string> = {
  Everyday: "Everyday",
  Commitments: "Bills",
  Irregular: "Big stuff",
};

export function treatmentLabel(value: string): string {
  return TREATMENT_LABEL[value] ?? value;
}

/** Against an earlier stretch; blank when there is none. */
export function Versus({ comparison }: { comparison: Comparison | null }) {
  if (!comparison || comparison.change === null) return null;
  return (
    <Delta
      change={comparison.change}
      percent={comparison.percent}
      than={rangeLabel(comparison.prior_start, comparison.prior_end)}
    />
  );
}

/** One of the panel's leading numbers: what was spent, and how that compares. */
export function Spent({
  label,
  cents,
  tone = "accent",
  live = false,
  whole = false,
  comparison,
}: {
  label: string;
  cents: number;
  tone?: "accent" | "over" | "amber" | "plain";
  /** An estimate, where cents would claim too much. */
  whole?: boolean;
  /** Still counting. */
  live?: boolean;
  comparison: ReactNode;
}) {
  return (
    <div className="spent">
      <span className="led-label">
        <span className={`led-dot ${live ? "pulse" : ""}`} aria-hidden="true" />
        {label}
      </span>
      <HeroNumber value={whole ? wholeMoney(cents) : money(cents)} tone={tone} />
      <div className="small">{comparison}</div>
    </div>
  );
}

interface LineWeek {
  spent: number;
  line: number;
  pace: number;
  left: number;
  per_day: number;
  days_left: number;
}

/** What the weekly line leaves, and what that is a day. */
export function LeftThisWeek({ week }: { week: LineWeek }) {
  const over = week.left < 0;
  return (
    <>
      <Readout label={over ? "Over line" : "Left"} value={money(Math.abs(week.left))} tone={over ? "coral" : "sage"} />
      <Readout label="Per day" value={money(week.per_day)} tone={over ? "coral" : "sage"} />
    </>
  );
}

/** What a term's finished weeks came to against the line, with an LED for each. */
export function SavedThisTerm({ weeks }: { weeks: number[] }) {
  if (!weeks.length) return null;
  const saved = weeks.reduce((sum, week) => sum + week, 0);
  const good = weeks.filter((week) => week >= 0).length;
  return (
    <Readout
      label={saved >= 0 ? "Term saved" : "Term over"}
      // Cents would push the pips out of the window.
      value={Math.abs(saved) < 1000_00 ? money(Math.abs(saved)) : wholeMoney(Math.abs(saved))}
      tone={saved >= 0 ? "sage" : "coral"}
      sub={
        <Pips
          label={`${good} of ${plural(weeks.length, "finished week")} inside the line`}
          pips={weeks.map((week) => (week >= 0 ? "ok" : "up"))}
        />
      }
    />
  );
}

/** Where the weekly line comes from. */
export function LineSource({ source }: { source: Budget["line"]["source"] }) {
  return (
    <Lamps
      label="Weekly line from"
      value={source}
      tone={source === "own" ? "blue" : "amber"}
      options={[
        { value: "school", label: "UCLA" },
        { value: "coa", label: "Auto" },
        { value: "own", label: "Own" },
      ]}
    />
  );
}

/** Spending against the weekly line. Each day owns a seventh of it, so the scale is the week. */
export function WeekMeter({ week, cap = false }: { week: LineWeek; cap?: boolean }) {
  return (
    <PaceMeter
      value={week.spent}
      capacity={week.line}
      pace={week.pace}
      segments={28}
      label={`${money(week.spent)} of ${money(week.line)} this week`}
      cap={cap ? money(week.line) : undefined}
      today={7 - week.days_left}
    />
  );
}

function shortWeek(label: string): string {
  if (label === "Finals week") return "FIN";
  const quarter = /^Week (\d+)$/.exec(label);
  if (quarter) return `W${quarter[1]}`;
  const numbered = /^Week (\d+) of/.exec(label);
  if (numbered) return `W${numbered[1]}`;
  return label.replace("Week of ", "").toUpperCase();
}

/**
 * One LED column per week against the dotted amber line that week had: lime up
 * to the line and coral above it. Under each finished week is what it saved (or
 * went over), which never carries into the next week.
 */
export function WeekBars({
  weeks,
  school,
  onPick,
}: {
  weeks: Week[];
  /** The school's own weekly estimate, when it isn't the line. */
  school?: number;
  /** Called with a week that has started when it is clicked. */
  onPick: (week: Week) => void;
}) {
  const id = useId().replace(/:/g, "");
  const [box, room] = useWidth(720);
  const { active, bind, leave } = usePreview();
  const scroller = useRef<HTMLDivElement>(null);
  const currentIndex = weeks.findIndex((week) => week.state === "current");
  const width = Math.max(room, weeks.length * 46);
  useEffect(() => {
    // On a phone the chart scrolls sideways; start with this week in view.
    const element = scroller.current;
    if (!element || currentIndex < 0 || element.scrollWidth <= element.clientWidth) return;
    const right = (element.scrollWidth * (currentIndex + 1.5)) / weeks.length;
    element.scrollLeft = Math.max(0, right - element.clientWidth);
  }, [currentIndex, weeks.length, width]);
  if (!weeks.length) return null;

  // Multiples of the 6-unit dot grid, so no dot is cut.
  const top = 24;
  const base = 198;
  const height = base + 46;
  const line = weeks[currentIndex]?.line ?? weeks[weeks.length - 1]?.line ?? 0;
  const largest = Math.max(1, ...weeks.map((week) => Math.max(week.spent, week.line * 1.25)), school ?? 0);
  const column = width / weeks.length;
  const barWidth = Math.max(18, Math.floor(Math.min(54, column * 0.6) / 6) * 6);
  const rise = (value: number) => Math.round(((base - top) * Math.max(0, value)) / largest / 6) * 6;
  const y = (value: number) => base - rise(value);
  const described = weeks.find((week) => week.start === active) ?? weeks[currentIndex] ?? weeks[weeks.length - 1];

  function describe(week: Week): Reading[] {
    const title = {
      text: `${week.label.startsWith("Week of") ? "" : `${week.label} · `}${rangeLabel(week.start, week.end)}`,
    };
    if (week.state === "future") return [title, { text: money(week.line) }];
    const kept = week.saved ?? week.left;
    return [
      title,
      { text: `${money(week.spent)} / ${money(week.line)}` },
      { text: money(kept, { signed: true }), tone: kept >= 0 ? "ok" : "up" },
    ];
  }

  const steps = weeks
    .map((week, index) => `${index ? "L" : "M"}${index * column} ${y(week.line)}H${(index + 1) * column}`)
    .join("");

  return (
    <div className="stack" ref={box}>
      <div className="chart-scroll" ref={scroller}>
        <svg
          className="chart"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="group"
          aria-label="Spending by week against the weekly line"
          onPointerLeave={leave}
        >
          <defs>
            <PanelDefs id={id} top={top} bottom={base} />
            <DotPattern id={`${id}on`} color={LED.accent} />
            <DotPattern id={`${id}past`} color="#7f972a" shine={0.35} />
            <DotPattern id={`${id}over`} color={LED.coral} shine={0.6} />
          </defs>
          <g>
            {weeks.map((week, index) => {
              const origin = Math.round((index + 0.5) * column - barWidth / 2);
              const current = week.state === "current";
              const lit = week.start === active;
              const spent = rise(week.spent);
              const under = Math.min(spent, rise(week.line));
              const pick = week.state === "future" ? null : () => onPick(week);
              return (
                <g
                  key={week.start}
                  className={`column ${pick ? "pick" : ""}`}
                  role={pick ? "button" : "img"}
                  tabIndex={week.start === described?.start ? 0 : -1}
                  aria-label={describe(week)
                    .map((part) => part.text)
                    .join(", ")}
                  opacity={week.state === "future" ? 0.55 : 1}
                  transform={`translate(${origin} 0)`}
                  {...bind(week.start, pick)}
                >
                  <rect x={index * column - origin} y="0" width={column} height={height} fill="transparent" />
                  <Well id={id} x={0} y={top} width={barWidth} height={base - top} lit={lit} />
                  {spent ? (
                    <rect
                      x="0"
                      y={base - under}
                      width={barWidth}
                      height={under}
                      fill={`url(#${id}${current || lit ? "on" : "past"})`}
                      style={current ? { filter: `drop-shadow(0 0 4px ${rgba(LED.accent, 0.7)})` } : undefined}
                    />
                  ) : null}
                  {spent > under ? (
                    <rect
                      x="0"
                      y={base - spent}
                      width={barWidth}
                      height={spent - under}
                      fill={`url(#${id}over)`}
                      style={{ filter: `drop-shadow(0 0 4px ${rgba(LED.coral, 0.6)})` }}
                    />
                  ) : null}
                  <Glass id={id} x={0} y={top} width={barWidth} height={base - top} />
                  <text
                    x={barWidth / 2}
                    y={base + 20}
                    textAnchor="middle"
                    style={current ? { fill: LED.accent } : lit ? { fill: "#E9ECE3" } : undefined}
                  >
                    {shortWeek(week.label)}
                  </text>
                  {week.saved !== null ? (
                    <text
                      x={barWidth / 2}
                      y={base + 38}
                      textAnchor="middle"
                      style={{ fill: week.saved >= 0 ? LED.sage : LED.coral }}
                    >
                      {week.saved >= 0 ? "+" : "−"}
                      {compactMoney(Math.abs(week.saved))}
                    </text>
                  ) : current ? (
                    <text x={barWidth / 2} y={base + 38} textAnchor="middle" style={{ fill: LED.accent }}>
                      NOW
                    </text>
                  ) : null}
                </g>
              );
            })}
          </g>
          <g pointerEvents="none">
            {school ? (
              <>
                <line
                  x1="0"
                  x2={width}
                  y1={y(school)}
                  y2={y(school)}
                  stroke={LED.blue}
                  strokeWidth="1.5"
                  strokeDasharray="1 5"
                  strokeLinecap="round"
                />
                <text className="value" x="4" y={y(school) - 8} style={{ fill: LED.blue }}>
                  UCLA {compactMoney(school)}
                </text>
              </>
            ) : null}
            <path d={steps} fill="none" stroke={LED.amber} strokeWidth="2" strokeDasharray="1 6" strokeLinecap="round" />
            <text className="value" x={width - 4} y={y(line) - 8} textAnchor="end" style={{ fill: LED.amber }}>
              {compactMoney(line)}/wk
            </text>
          </g>
        </svg>
      </div>
      {described ? <ReadoutBar parts={describe(described)} /> : null}
    </div>
  );
}
