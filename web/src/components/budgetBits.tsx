import { useEffect, useId, useRef } from "react";

import type { BillDue, Week } from "../api";
import { compactMoney, money, shortDate } from "../lib/format";
import { hot, rgba } from "../lib/glyphs";
import { Led } from "./instrument";

/** Storage keeps the original treatment names; people see these. */
export const TREATMENT_LABEL: Record<string, string> = {
  Everyday: "Everyday",
  Commitments: "Bills",
  Irregular: "Big stuff",
};

export function treatmentLabel(value: string): string {
  return TREATMENT_LABEL[value] ?? value;
}

const BILL_COLORS: Record<BillDue["status"], string> = {
  paid: "#9FD39B",
  late: "#FF8A70",
  soon: "#F2C14E",
  upcoming: "#59614F",
};

const BILL_TEXT: Record<BillDue["status"], string> = {
  paid: "paid",
  late: "not paid yet",
  soon: "due this week",
  upcoming: "upcoming",
};

export function BillList({ bills }: { bills: BillDue[] }) {
  return (
    <div>
      {bills.map((bill) => (
        <div key={`${bill.name}${bill.due}`} className="bill-row">
          <Led color={BILL_COLORS[bill.status]} lit={bill.status !== "upcoming"} pulse={bill.status === "soon"} />
          <span className="stack tight" style={{ gap: 2 }}>
            <span>{bill.name}</span>
            <span className="tiny dim caps">
              {BILL_TEXT[bill.status]} · due {shortDate(bill.due)}
            </span>
          </span>
          <span className="num small" style={{ textAlign: "right" }}>
            {bill.paid ? (
              <>
                {money(bill.paid)} <span className="dim">/ {money(bill.amount)}</span>
              </>
            ) : (
              money(bill.amount)
            )}
          </span>
        </div>
      ))}
    </div>
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

const ACCENT = "#D4F53C";
const CORAL = "#FF8A70";

/**
 * One LED column per week. The dashed amber line is the weekly line; a week's
 * column lights green up to the line and coral above it. Under each finished week
 * is what it saved (or went over), which never carries into the next week.
 */
export function WeekBars({ weeks, line, school }: { weeks: Week[]; line: number; school?: number }) {
  const id = useId().replace(/:/g, "");
  const scroller = useRef<HTMLDivElement>(null);
  const currentIndex = weeks.findIndex((week) => week.state === "current");
  useEffect(() => {
    // On a phone the chart scrolls sideways; start with this week in view.
    const element = scroller.current;
    if (!element || currentIndex < 0 || element.scrollWidth <= element.clientWidth) return;
    const right = (element.scrollWidth * (currentIndex + 1.5)) / weeks.length;
    element.scrollLeft = Math.max(0, right - element.clientWidth);
  }, [currentIndex, weeks.length]);
  if (!weeks.length) return null;
  const width = 720;
  const height = 250;
  const top = 26;
  const base = 186;
  const largest = Math.max(1, line * 1.4, ...weeks.map((week) => week.spent), school ?? 0);
  const column = width / weeks.length;
  const barWidth = Math.min(40, column * 0.6);
  const y = (value: number) => base - Math.round(((base - top) * Math.max(0, value)) / largest / 6) * 6;
  const lineY = y(line);
  const schoolY = school && school !== line ? y(school) : null;

  function pattern(name: string, color: string, shine: number) {
    return (
      <>
        <radialGradient id={`${id}${name}g`} cx="38%" cy="34%" r="70%">
          <stop offset="0" stopColor={hot(color, shine)} />
          <stop offset="0.45" stopColor={color} />
          <stop offset="1" stopColor={rgba(color, 0.55)} />
        </radialGradient>
        <pattern id={`${id}${name}`} width="6" height="6" patternUnits="userSpaceOnUse">
          <circle cx="3" cy="3.5" r="2.2" fill="rgba(0,0,0,.7)" />
          <circle cx="3" cy="3" r="2.2" fill={`url(#${id}${name}g)`} />
        </pattern>
      </>
    );
  }

  return (
    <div className="stack tight">
      <div className="chart-scroll" ref={scroller}>
        <svg
          className="chart"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={weeks
            .map((week) => `${week.label}: ${week.state === "future" ? "ahead" : `${money(week.spent)} spent`}`)
            .join("; ")}
        >
          <defs>
            {pattern("on", ACCENT, 0.75)}
            {pattern("past", "#7f972a", 0.35)}
            {pattern("over", CORAL, 0.6)}
            <pattern id={`${id}off`} width="6" height="6" patternUnits="userSpaceOnUse">
              <circle cx="3" cy="3.4" r="1.5" fill="#20261b" />
              <circle cx="3" cy="3" r="1.3" fill="#0b0d09" />
            </pattern>
            <linearGradient id={`${id}well`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#030402" />
              <stop offset="1" stopColor="#0b0d09" />
            </linearGradient>
            <linearGradient id={`${id}sheen`} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={top} y2={base}>
              <stop offset="0" stopColor="#fff" stopOpacity="0.06" />
              <stop offset="0.45" stopColor="#fff" stopOpacity="0" />
            </linearGradient>
          </defs>
          {weeks.map((week, index) => {
            const x = Math.round((index + 0.5) * column - barWidth / 2);
            const current = week.state === "current";
            const spentY = y(week.spent);
            const under = Math.max(spentY, lineY);
            return (
              <g key={week.start} opacity={week.state === "future" ? 0.55 : 1}>
                <rect x={x - 3} y={top - 3} width={barWidth + 6} height={base - top + 6} fill={`url(#${id}well)`} />
                <rect x={x - 3} y={top - 3} width={barWidth + 6} height="2" fill="#000" opacity="0.7" />
                <rect x={x - 3} y={base + 2} width={barWidth + 6} height="1" fill="#fff" opacity="0.06" />
                <rect x={x} y={top} width={barWidth} height={base - top} fill={`url(#${id}off)`} />
                {week.spent > 0 ? (
                  <>
                    <rect
                      x={x}
                      y={under}
                      width={barWidth}
                      height={base - under}
                      fill={`url(#${id}${current ? "on" : "past"})`}
                      style={current ? { filter: `drop-shadow(0 0 4px ${rgba(ACCENT, 0.7)})` } : undefined}
                    />
                    {spentY < lineY ? (
                      <rect
                        x={x}
                        y={spentY}
                        width={barWidth}
                        height={lineY - spentY}
                        fill={`url(#${id}over)`}
                        style={{ filter: `drop-shadow(0 0 4px ${rgba(CORAL, 0.6)})` }}
                      />
                    ) : null}
                  </>
                ) : null}
                <text
                  x={x + barWidth / 2}
                  y={base + 22}
                  textAnchor="middle"
                  style={current ? { fill: ACCENT } : undefined}
                >
                  {shortWeek(week.label)}
                </text>
                {week.saved !== null ? (
                  <text
                    x={x + barWidth / 2}
                    y={base + 40}
                    textAnchor="middle"
                    style={{ fill: week.saved >= 0 ? "#9FD39B" : CORAL, fontSize: 10 }}
                  >
                    {week.saved >= 0 ? "+" : "−"}
                    {compactMoney(Math.abs(week.saved))}
                  </text>
                ) : current ? (
                  <text x={x + barWidth / 2} y={base + 40} textAnchor="middle" style={{ fill: ACCENT, fontSize: 10 }}>
                    NOW
                  </text>
                ) : null}
              </g>
            );
          })}
          <rect x="0" y={top - 3} width={width} height={base - top + 6} fill={`url(#${id}sheen)`} pointerEvents="none" />
          {schoolY !== null ? (
            <line x1="0" x2={width} y1={schoolY} y2={schoolY} stroke="#7CB8FF" strokeWidth="1.5" strokeDasharray="1 5" strokeLinecap="round" />
          ) : null}
          <line x1="0" x2={width} y1={lineY} y2={lineY} stroke="#F2C14E" strokeWidth="2" strokeDasharray="1 6" strokeLinecap="round" />
          <text x={width - 4} y={lineY - 6} textAnchor="end" style={{ fill: "#F2C14E" }}>
            {compactMoney(line)}/wk
          </text>
        </svg>
      </div>
      <div className="legend">
        <span>
          <i style={{ backgroundColor: "#F2C14E" }} />
          Weekly line
        </span>
        {schoolY !== null ? (
          <span>
            <i style={{ backgroundColor: "#7CB8FF" }} />
            UCLA estimate
          </span>
        ) : null}
        <span>
          <i style={{ backgroundColor: "#9FD39B" }} />
          Saved that week
        </span>
        <span>
          <i style={{ backgroundColor: CORAL }} />
          Over the line
        </span>
      </div>
    </div>
  );
}
