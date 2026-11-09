import { type CSSProperties, useId, useState } from "react";

import { compactMoney, money, MONTH_SHORT, parseIso, plural, weekday } from "../lib/format";
import { categoryColor, hot, rgba } from "../lib/glyphs";
import { Glyph } from "./instrument";

const ACCENT = "#D4F53C";

/**
 * Background layers for a row of lit LED domes: a specular highlight up and to the
 * left, the lit body, and a shadow just below so each dot sits above its socket.
 */
function ledDots(color: string, body = 1.8): string {
  return [
    `radial-gradient(circle at 40% 36%, rgba(255,255,255,.9) 0, rgba(255,255,255,0) ${(body * 0.55).toFixed(2)}px)`,
    `radial-gradient(circle, ${hot(color, 0.5)} 0, ${color} ${body}px, ${rgba(color, 0.6)} ${(body + 1).toFixed(2)}px, transparent ${(body + 1.4).toFixed(2)}px)`,
    `radial-gradient(circle at 50% 64%, rgba(0,0,0,.75) ${(body + 0.6).toFixed(2)}px, transparent ${(body + 1.5).toFixed(2)}px)`,
  ].join(", ");
}

/** SVG defs for a domed LED dot in one color, tiled every 6 units. */
function DotPattern({ id, color, r = 2.2, shine = 0.75 }: { id: string; color: string; r?: number; shine?: number }) {
  return (
    <>
      <radialGradient id={`${id}g`} cx="38%" cy="34%" r="70%">
        <stop offset="0" stopColor={hot(color, shine)} />
        <stop offset="0.45" stopColor={color} />
        <stop offset="1" stopColor={rgba(color, 0.55)} />
      </radialGradient>
      <pattern id={id} width="6" height="6" patternUnits="userSpaceOnUse">
        <circle cx="3" cy="3.5" r={r} fill="rgba(0,0,0,.7)" />
        <circle cx="3" cy="3" r={r} fill={`url(#${id}g)`} />
      </pattern>
    </>
  );
}

/** Shared SVG defs: sunken sockets for unlit dots, a recessed well, glass sheen. */
function PanelDefs({ id, top, bottom }: { id: string; top: number; bottom: number }) {
  return (
    <>
      <pattern id={`${id}off`} width="6" height="6" patternUnits="userSpaceOnUse">
        <circle cx="3" cy="3.4" r="1.5" fill="#20261b" />
        <circle cx="3" cy="3" r="1.3" fill="#0b0d09" />
      </pattern>
      <linearGradient id={`${id}well`} x1="0" x2="0" y1="0" y2="1">
        <stop offset="0" stopColor="#030402" />
        <stop offset="1" stopColor="#0b0d09" />
      </linearGradient>
      <linearGradient id={`${id}sheen`} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={top} y2={bottom}>
        <stop offset="0" stopColor="#fff" stopOpacity="0.06" />
        <stop offset="0.45" stopColor="#fff" stopOpacity="0" />
      </linearGradient>
    </>
  );
}

/** A recessed slot: dark well, shadowed top lip, lit bottom edge. */
function Well({ id, x, y, width, height }: { id: string; x: number; y: number; width: number; height: number }) {
  return (
    <g>
      <rect x={x - 3} y={y - 3} width={width + 6} height={height + 6} fill={`url(#${id}well)`} />
      <rect x={x - 3} y={y - 3} width={width + 6} height="2" fill="#000" opacity="0.7" />
      <rect x={x - 3} y={y + height + 2} width={width + 6} height="1" fill="#fff" opacity="0.06" />
      <rect x={x} y={y} width={width} height={height} fill={`url(#${id}off)`} />
    </g>
  );
}

interface Day {
  date: string;
  spent: number;
  count: number;
  future: boolean;
}

/** A Monday-first month where each day's dot size and glow show what was spent. */
export function DotCalendar({
  days,
  today,
  onPick,
  dailyAllowance,
}: {
  days: Day[];
  today: string | null;
  onPick?: (date: string) => void;
  dailyAllowance?: number | null;
}) {
  const [hover, setHover] = useState<Day | null>(null);
  if (!days.length) return null;
  const first = parseIso(days[0]?.date ?? "2000-01-01");
  const blanks = (first.getDay() + 6) % 7;
  const largest = Math.max(1, ...days.map((day) => day.spent));
  const biggest = days.reduce<Day | null>(
    (best, day) => (!day.future && day.spent > (best?.spent ?? 0) ? day : best),
    null,
  );
  const quiet = days.filter((day) => !day.future && day.count === 0).length;

  function describe(day: Day): string {
    const date = parseIso(day.date);
    const label = `${weekday(day.date)} ${MONTH_SHORT[date.getMonth()]} ${date.getDate()}`;
    if (day.future) {
      return dailyAllowance
        ? `${label} · ahead · ${money(dailyAllowance)}/day keeps you on plan`
        : `${label} · ahead`;
    }
    if (!day.count) return `${label} · no spending ✓`;
    return `${label} · ${money(day.spent)} · ${plural(day.count, "purchase")}${day.date === today ? " · today" : ""}`;
  }

  const summary = hover
    ? describe(hover)
    : [
        biggest ? `Biggest day · ${weekday(biggest.date)} ${parseIso(biggest.date).getDate()} · ${money(biggest.spent)}` : "No spending yet",
        plural(quiet, "no-spend day"),
        "point at a day",
      ].join("  ·  ");

  return (
    <div className="stack">
      <div className="cal-head" aria-hidden="true">
        {["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"].map((name) => (
          <span key={name}>{name}</span>
        ))}
      </div>
      <div className="cal" onMouseLeave={() => setHover(null)}>
        {Array.from({ length: blanks }, (_, index) => (
          <span key={`blank${index}`} aria-hidden="true" />
        ))}
        {days.map((day) => {
          const share = day.spent > 0 ? Math.sqrt(day.spent / largest) : 0;
          const radius = 0.9 + 2.6 * share;
          const lit: CSSProperties | undefined =
            day.spent > 0
              ? {
                  backgroundImage: `radial-gradient(circle at 44% 40%, rgba(255,255,255,.85) 0, rgba(255,255,255,0) ${(radius * 0.4).toFixed(2)}px), radial-gradient(circle, ${hot(ACCENT, 0.55)} 0, ${ACCENT} ${(radius * 0.55).toFixed(2)}px, ${rgba(ACCENT, 0.7)} ${radius.toFixed(2)}px, transparent ${(radius + 0.6).toFixed(2)}px)`,
                  filter: `drop-shadow(0 0 ${(2 + 3 * share).toFixed(1)}px ${rgba(ACCENT, 0.75)})`,
                }
              : undefined;
          const background =
            day.spent > 0
              ? `radial-gradient(90% 90% at 50% 60%, ${rgba(ACCENT, 0.03 + 0.1 * share)}, transparent 70%), #060705`
              : undefined;
          return (
            <button
              key={day.date}
              type="button"
              className={`cell ${day.date === today ? "today" : ""} ${day.future ? "future" : ""}`}
              style={background ? { background } : undefined}
              aria-label={describe(day)}
              onMouseEnter={() => setHover(day)}
              onFocus={() => setHover(day)}
              onBlur={() => setHover(null)}
              onClick={() => onPick?.(day.date)}
            >
              <span className="day">{parseIso(day.date).getDate()}</span>
              <span className="matrix" aria-hidden="true" />
              {lit ? <span className="lit" style={lit} aria-hidden="true" /> : null}
            </button>
          );
        })}
      </div>
      <div className="readout-bar" role="status">
        <span className="caret" aria-hidden="true">
          ▸
        </span>
        <span>{summary}</span>
      </div>
    </div>
  );
}

function dotValue(largest: number, dots: number): number {
  const steps = [100, 200, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000, 100000, 250000, 500000];
  return steps.find((step) => largest / step <= dots) ?? Math.ceil(largest / dots);
}

export function CategoryMeters({
  categories,
  onPick,
}: {
  categories: { category: string; spent: number }[];
  onPick?: (category: string) => void;
}) {
  const positive = categories.filter((item) => item.spent > 0);
  if (!positive.length) return null;
  const largest = Math.max(...positive.map((item) => item.spent));
  const unit = dotValue(largest, 34);
  return (
    <div className="stack tight">
      <span className="small dim">
        one lit dot = {money(unit)}
      </span>
      {positive.map((item) => {
        const color = categoryColor(item.category);
        const count = Math.max(1, Math.round(item.spent / unit));
        return (
          <button
            key={item.category}
            type="button"
            className="meter-row"
            style={{ cursor: onPick ? "pointer" : "default" }}
            onClick={() => onPick?.(item.category)}
            aria-label={`${item.category}: ${money(item.spent)}`}
          >
            <Glyph category={item.category} />
            <span className="small">{item.category}</span>
            <span className="track" aria-hidden="true">
              <span className="dots" />
              <span
                className="fill"
                style={{
                  width: `${count * 9}px`,
                  backgroundImage: ledDots(color),
                  filter: `drop-shadow(0 0 3px ${rgba(color, 0.8)})`,
                }}
              />
            </span>
            <span className="num small" style={{ textAlign: "right" }}>
              {money(item.spent)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function monthShort(month: string): string {
  const [year, number] = month.split("-").map(Number);
  return `${MONTH_SHORT[(number ?? 1) - 1]?.toUpperCase()}${number === 1 ? ` ${String(year).slice(2)}` : ""}`;
}

/** Monthly totals as columns of lit dots, with a dotted rolling-average line. */
export function DotColumns({
  data,
  highlight,
  average,
  averageLabel = "3-month average",
}: {
  data: { month: string; spent: number }[];
  highlight?: string;
  average?: number[];
  averageLabel?: string;
}) {
  const id = useId().replace(/:/g, "");
  if (!data.length) return null;
  const width = 720;
  const height = 230;
  const base = 196;
  const top = 26;
  const largest = Math.max(1, ...data.map((item) => item.spent), ...(average ?? []));
  const column = width / data.length;
  const barWidth = Math.min(54, column * 0.62);
  const scale = (value: number) => Math.round(((base - top) * Math.max(0, value)) / largest / 6) * 6;
  const averagePoints = average
    ?.map((value, index) => `${(index + 0.5) * column},${base - scale(value)}`)
    .join(" ");
  return (
    <div className="stack tight">
      <svg
        className="chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={data.map((item) => `${item.month}: ${money(item.spent)}`).join("; ")}
      >
        <defs>
          <PanelDefs id={id} top={top} bottom={base} />
          <DotPattern id={`${id}on`} color={ACCENT} />
          <DotPattern id={`${id}dim`} color="#5f731f" shine={0.3} />
          <linearGradient id={`${id}fade`} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={base + 4} y2={base + 18}>
            <stop offset="0" stopColor="#fff" stopOpacity="0.32" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
          <mask id={`${id}mirror`} maskUnits="userSpaceOnUse" x="0" y={base} width={width} height="24">
            <rect x="0" y={base + 4} width={width} height="14" fill={`url(#${id}fade)`} />
          </mask>
        </defs>
        {data.map((item, index) => {
          const x = Math.round((index + 0.5) * column - barWidth / 2);
          const h = scale(item.spent);
          const on = item.month === highlight;
          const fill = `url(#${id}${on ? "on" : "dim"})`;
          return (
            <g key={item.month}>
              <Well id={id} x={x} y={top} width={barWidth} height={base - top} />
              <rect
                x={x}
                y={base - h}
                width={barWidth}
                height={h}
                fill={fill}
                style={on ? { filter: `drop-shadow(0 0 4px ${rgba(ACCENT, 0.7)})` } : undefined}
              />
              {h ? (
                <rect
                  x={x}
                  y={base + 4}
                  width={barWidth}
                  height={14}
                  fill={fill}
                  mask={`url(#${id}mirror)`}
                  aria-hidden="true"
                />
              ) : null}
              {on || data.length <= 6 ? (
                <text x={x + barWidth / 2} y={base - h - 8} textAnchor="middle" style={{ fill: on ? ACCENT : "#A7AF9E" }}>
                  {compactMoney(item.spent)}
                </text>
              ) : null}
              <text x={x + barWidth / 2} y={height - 10} textAnchor="middle">
                {monthShort(item.month)}
              </text>
            </g>
          );
        })}
        <rect x="0" y={top - 3} width={width} height={base - top + 6} fill={`url(#${id}sheen)`} pointerEvents="none" />
        {averagePoints ? (
          <polyline
            points={averagePoints}
            fill="none"
            stroke="#F2C14E"
            strokeWidth="2"
            strokeDasharray="1 6"
            strokeLinecap="round"
          />
        ) : null}
      </svg>
      {averagePoints ? (
        <div className="legend">
          <span>
            <i style={{ backgroundColor: ACCENT, boxShadow: `0 0 6px ${ACCENT}` }} />
            Net spent
          </span>
          <span>
            <i style={{ backgroundColor: "#F2C14E" }} />
            {averageLabel}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/** Money in (up, sage) and out (down, coral) per month with the net as amber LEDs. */
export function CashFlowChart({
  data,
}: {
  data: { month: string; income: number; expenses: number; refunds: number; net: number }[];
}) {
  const id = useId().replace(/:/g, "");
  if (!data.length) return null;
  const width = 720;
  const height = 260;
  const middle = 120;
  const reach = 96;
  const shown = data.slice(-12);
  const largest = Math.max(
    1,
    ...shown.map((item) => Math.max(item.income + item.refunds, item.expenses, Math.abs(item.net))),
  );
  const column = width / shown.length;
  const barWidth = Math.min(46, column * 0.56);
  const scale = (value: number) => Math.round((reach * value) / largest / 6) * 6;
  return (
    <div className="stack tight">
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Monthly cash flow">
        <defs>
          <PanelDefs id={id} top={middle - reach} bottom={middle + reach} />
          <DotPattern id={`${id}in`} color="#9FD39B" />
          <DotPattern id={`${id}out`} color="#FF8A70" />
          <radialGradient id={`${id}net`} cx="38%" cy="34%" r="70%">
            <stop offset="0" stopColor="#fff6dc" />
            <stop offset="0.45" stopColor="#F2C14E" />
            <stop offset="1" stopColor="#b5861f" />
          </radialGradient>
        </defs>
        {shown.map((item, index) => {
          const x = Math.round((index + 0.5) * column - barWidth / 2);
          const up = scale(item.income + item.refunds);
          const down = scale(item.expenses);
          const net = middle - Math.round((reach * item.net) / largest);
          return (
            <g key={item.month}>
              <Well id={id} x={x} y={middle - reach} width={barWidth} height={reach * 2} />
              <rect x={x} y={middle - up} width={barWidth} height={up} fill={`url(#${id}in)`} />
              <rect x={x} y={middle} width={barWidth} height={down} fill={`url(#${id}out)`} />
              <circle
                cx={x + barWidth / 2}
                cy={net}
                r="4.5"
                fill={`url(#${id}net)`}
                style={{ filter: "drop-shadow(0 0 4px rgba(242,193,78,.8))" }}
              >
                <title>{`${item.month}: net ${money(item.net, { signed: true })}`}</title>
              </circle>
              <text x={x + barWidth / 2} y={height - 8} textAnchor="middle">
                {monthShort(item.month)}
              </text>
            </g>
          );
        })}
        <line x1="0" x2={width} y1={middle} y2={middle} stroke="#3a4234" strokeDasharray="2 4" />
        <rect
          x="0"
          y={middle - reach - 3}
          width={width}
          height={reach * 2 + 6}
          fill={`url(#${id}sheen)`}
          pointerEvents="none"
        />
      </svg>
      <div className="legend">
        <span>
          <i style={{ backgroundColor: "#9FD39B" }} />
          Income + refunds
        </span>
        <span>
          <i style={{ backgroundColor: "#FF8A70" }} />
          Expenses
        </span>
        <span>
          <i style={{ backgroundColor: "#F2C14E" }} />
          Net
        </span>
      </div>
    </div>
  );
}

/** Category changes as bars left (less) and right (more) of a center line. */
export function DriverBars({
  drivers,
}: {
  drivers: { category: string; current: number; previous: number; change: number; percent: number | null }[];
}) {
  const largest = Math.max(1, ...drivers.map((item) => Math.abs(item.change)));
  return (
    <div className="stack tight">
      {drivers.map((item) => {
        const share = (Math.abs(item.change) / largest) * 50;
        const color = item.change > 0 ? "#FF8A70" : "#9FD39B";
        return (
          <div
            key={item.category}
            className="meter-row"
            style={{ gridTemplateColumns: "26px minmax(90px,150px) minmax(0,1fr) 150px" }}
          >
            <Glyph category={item.category} small />
            <span className="small">{item.category}</span>
            <span className="track" aria-hidden="true">
              <span
                style={{
                  position: "absolute",
                  top: 0,
                  bottom: 0,
                  left: "50%",
                  width: 1,
                  background: "#2F352B",
                  zIndex: 1,
                }}
              />
              <span
                style={{
                  position: "absolute",
                  top: 2,
                  bottom: 2,
                  left: item.change > 0 ? "50%" : `${50 - share}%`,
                  width: `${share}%`,
                  backgroundImage: ledDots(color, 1.9),
                  backgroundSize: "7px 10px",
                  filter: `drop-shadow(0 0 3px ${rgba(color, 0.7)})`,
                }}
              />
            </span>
            <span className="num small" style={{ textAlign: "right", whiteSpace: "nowrap" }}>
              <span className={item.change > 0 ? "up" : "ok"}>{money(item.change, { signed: true })}</span>
              <br />
              <span className="dim tiny">
                {money(item.previous)} → {money(item.current)}
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
