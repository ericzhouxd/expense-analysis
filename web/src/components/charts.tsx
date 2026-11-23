import {
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import type { ForecastMonth } from "../api";
import {
  compactMoney,
  money,
  MONTH_SHORT,
  parseIso,
  rangeLabel,
  weekday,
  wholeMoney,
} from "../lib/format";
import { categoryColor, hot, LED, rgba } from "../lib/glyphs";
import { Glyph } from "./instrument";

const { accent: ACCENT, amber: AMBER, coral: CORAL, sage: SAGE } = LED;
/** Averages are drawn in plain ink: amber is for estimates and the weekly line. */
const AVERAGE = "#DDE3D2";

/** The laid-out width of a chart's box, so it can draw at one unit per pixel. */
export function useWidth(fallback: number): [(element: HTMLElement | null) => void, number] {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    if (!element) return;
    const measure = () => {
      if (element.clientWidth > 0) setWidth(element.clientWidth);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return [setElement, width];
}

/**
 * Preview and pick for the columns of a chart. A mouse previews on hover and
 * picks on click; a finger previews on the first tap and picks on the second.
 * Arrow keys move between sibling columns; Enter or Space picks.
 */
export function usePreview() {
  const [active, setActive] = useState<string | null>(null);
  const armed = useRef(true);

  function bind(key: string, pick: (() => void) | null) {
    return {
      onPointerEnter: (event: PointerEvent<SVGGElement>) => {
        if (event.pointerType === "mouse") setActive(key);
      },
      onPointerDown: (event: PointerEvent<SVGGElement>) => {
        armed.current = event.pointerType === "mouse" || active === key;
      },
      onClick: () => {
        if (!armed.current) {
          armed.current = true;
          setActive(key);
          return;
        }
        pick?.();
      },
      onFocus: () => setActive(key),
      onBlur: () => setActive(null),
      onKeyDown: (event: KeyboardEvent<SVGGElement>) => {
        if (event.key === "Enter" || event.key === " ") {
          if (!pick) return;
          event.preventDefault();
          pick();
          return;
        }
        const column = event.currentTarget;
        const next =
          event.key === "ArrowLeft"
            ? column.previousElementSibling
            : event.key === "ArrowRight"
              ? column.nextElementSibling
              : null;
        if (next instanceof SVGGElement) {
          event.preventDefault();
          next.focus();
        }
      },
    };
  }

  function leave(event: PointerEvent<SVGSVGElement>) {
    if (event.pointerType === "mouse") setActive(null);
  }

  return { active, bind, leave };
}

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
export function DotPattern({ id, color, r = 2.2, shine = 0.75 }: { id: string; color: string; r?: number; shine?: number }) {
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
export function PanelDefs({ id, top, bottom }: { id: string; top: number; bottom: number }) {
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
export function Well({ id, x, y, width, height, lit = false }: { id: string; x: number; y: number; width: number; height: number; lit?: boolean }) {
  return (
    <g>
      <rect x={x - 3} y={y - 3} width={width + 6} height={height + 6} fill={`url(#${id}well)`} />
      <rect x={x - 3} y={y - 3} width={width + 6} height="2" fill="#000" opacity="0.7" />
      <rect x={x - 3} y={y + height + 2} width={width + 6} height="1" fill="#fff" opacity="0.06" />
      <rect x={x} y={y} width={width} height={height} fill={`url(#${id}off)`} />
      {lit ? (
        <rect
          x={x - 3.5}
          y={y - 3.5}
          width={width + 7}
          height={height + 7}
          fill="none"
          stroke="#E9ECE3"
          strokeOpacity="0.4"
        />
      ) : null}
    </g>
  );
}

/** The sheen over one slot's glass, drawn last. */
export function Glass({ id, x, y, width, height }: { id: string; x: number; y: number; width: number; height: number }) {
  return (
    <rect x={x - 3} y={y - 3} width={width + 6} height={height + 6} fill={`url(#${id}sheen)`} pointerEvents="none" />
  );
}

export interface Reading {
  text: string;
  tone?: "up" | "ok" | "warn";
}

/** The line under a chart that says what is being pointed at. */
export function ReadoutBar({ parts }: { parts: Reading[] }) {
  return (
    <div className="readout-bar" aria-hidden="true">
      <span className="caret">▸</span>
      <span className="parts">
        {parts.map((part) => (
          <span key={part.text} className={part.tone}>
            {part.text}
          </span>
        ))}
      </span>
    </div>
  );
}

export function LegendDot({ color, children }: { color: string; children: ReactNode }) {
  return (
    <span>
      <i style={{ backgroundColor: color }} />
      {children}
    </span>
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
}: {
  days: Day[];
  today: string | null;
  onPick?: (date: string) => void;
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

  function describe(day: Day): Reading[] {
    const date = parseIso(day.date);
    const label = { text: `${weekday(day.date)} ${MONTH_SHORT[date.getMonth()]} ${date.getDate()}` };
    if (day.future) return [label];
    return [label, { text: money(day.spent) }, ...(day.count > 1 ? [{ text: `${day.count}×` }] : [])];
  }

  const shown = hover ?? biggest;

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
              aria-label={describe(day)
                .map((part) => part.text)
                .join(", ")}
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
      {shown ? <ReadoutBar parts={[...(hover ? [] : [{ text: "Peak" }]), ...describe(shown)]} /> : null}
    </div>
  );
}

function dotValue(largest: number, dots: number): number {
  const raw = largest / dots;
  const power = 10 ** Math.floor(Math.log10(Math.max(1, raw)));
  return Math.max(100, ([1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((size) => size * power >= raw) ?? 10) * power);
}

/** Width of one LED in a category's track. */
const DOT = 9;

/** Categories by amount as rows of LEDs, scaled so the largest fits its track. */
export function CategoryMeters({
  categories,
  onPick,
  limit = 9,
}: {
  categories: { category: string; spent: number }[];
  onPick: (category: string) => void;
  limit?: number;
}) {
  const [track, width] = useWidth(306);
  const [all, setAll] = useState(false);
  const positive = categories.filter((item) => item.spent > 0);
  if (!positive.length) return null;
  const largest = Math.max(...positive.map((item) => item.spent));
  const total = positive.reduce((sum, item) => sum + item.spent, 0);
  const unit = dotValue(largest, Math.max(8, Math.floor((width - 4) / DOT)));
  // One hidden row would cost as much space as the button that shows it.
  const shown = all || positive.length <= limit + 1 ? positive : positive.slice(0, limit);
  return (
    <div className="meters">
      {shown.map((item, index) => {
        const color = categoryColor(item.category);
        const count = Math.max(1, Math.round(item.spent / unit));
        return (
          <button
            key={item.category}
            type="button"
            className="meter-row"
            onClick={() => onPick(item.category)}
          >
            <Glyph category={item.category} />
            <span className="truncate">{item.category}</span>
            <span className="track" aria-hidden="true" ref={index ? undefined : track}>
              <span className="dots" />
              <span
                className="fill"
                style={{
                  width: `${count * DOT}px`,
                  backgroundImage: ledDots(color),
                  filter: `drop-shadow(0 0 3px ${rgba(color, 0.8)})`,
                }}
              />
            </span>
            <span className="num">
              {money(item.spent)}
              <span className="tiny dim">{Math.round((item.spent / total) * 100)}%</span>
            </span>
          </button>
        );
      })}
      {shown.length < positive.length ? (
        <div className="row meters-foot">
          <button type="button" className="link small" onClick={() => setAll(true)}>
            + {positive.length - shown.length} more
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** Narrowest column whose month and value labels still clear their neighbors'. */
const MIN_COLUMN = 38;

/** One column of a `DotColumns` chart: a month or a week. */
export interface Column {
  key: string;
  /** The label under the column. */
  name: string;
  /** A second label under it (the year, or a week's month), shown when it changes. */
  group: string;
  /** How the readout names the column. */
  title: string;
  spent: number;
}

interface TrendColumn extends Column {
  average: number | null;
  forecast: ForecastMonth | null;
  /** A month that has not started yet: forecast only. */
  ahead: boolean;
}

function monthColumn(month: string, spent: number): Column {
  const [year, number] = month.split("-").map(Number);
  const name = MONTH_SHORT[(number ?? 1) - 1]?.toUpperCase() ?? month;
  return { key: month, name, group: String(year), title: `${name} ${year}`, spent };
}

/** Months as chart columns, labeled JAN with the year under the first of each year. */
export function monthColumns(items: { month: string; spent: number }[]): Column[] {
  return items.map((item) => monthColumn(item.month, item.spent));
}

/** Weeks as chart columns, labeled by the Monday's date with the month under the first of each month. */
export function weekColumns(items: { week: string; end: string; label: string; spent: number }[]): Column[] {
  return items.map((item) => {
    const monday = parseIso(item.week);
    return {
      key: item.week,
      name: String(monday.getDate()),
      group: MONTH_SHORT[monday.getMonth()]?.toUpperCase() ?? "",
      title: `${item.label} · ${rangeLabel(item.week, item.end)}`.toUpperCase(),
      spent: item.spent,
    };
  });
}

/** What the readout under the chart says about one column. */
function describeColumn(
  item: TrendColumn,
  averageLabel: string | null,
): Reading[] {
  const title = { text: item.title };
  const plan = item.forecast;
  if (plan) {
    return [
      title,
      ...(item.ahead ? [] : [{ text: money(item.spent) }]),
      { text: `~${wholeMoney(plan.expected)}`, tone: "warn" },
      { text: `${wholeMoney(plan.low)}–${wholeMoney(plan.high)}` },
    ];
  }
  if (!averageLabel || item.average === null) return [title, { text: money(item.spent) }];
  const gap = item.spent - item.average;
  return [
    title,
    { text: money(item.spent) },
    { text: `avg ${money(Math.round(item.average))}` },
    { text: `${gap > 0 ? "▲" : "▼"} ${money(Math.abs(gap))}`, tone: gap > 0 ? "up" : "ok" },
  ];
}

/**
 * Totals per month or week as columns of lit dots with a dotted rolling-average line and,
 * when given, a forecast: amber dots up to the likely low, fainter ones up to the
 * likely high and a bar at the expected amount. Drawn at one unit per pixel, so
 * labels keep their size and only as many months as fit are shown. Pointing at a
 * column describes it in the readout below; picking one calls `onPick`.
 */
export function DotColumns({
  data,
  highlight,
  average,
  averageLabel = "3-month avg",
  unit = "month",
  forecast,
  onPick,
  pickable,
}: {
  data: Column[];
  /** What one column is: "month" or "week". */
  unit?: string;
  highlight?: string;
  average?: number[];
  averageLabel?: string;
  forecast?: ForecastMonth[];
  onPick?: (month: string) => void;
  /** Months `onPick` accepts; all of them when omitted. */
  pickable?: string[];
}) {
  const id = useId().replace(/:/g, "");
  const [box, width] = useWidth(720);
  const { active, bind, leave } = usePreview();
  const [lineOn, setLineOn] = useState(true);
  const [planOn, setPlanOn] = useState(true);
  if (!data.length) return null;

  const plan = planOn ? (forecast ?? []) : [];
  const known = new Set(data.map((item) => item.key));
  const columns: TrendColumn[] = [
    ...data.map((item, index) => ({
      ...item,
      average: average?.[index] ?? null,
      forecast: plan.find((entry) => entry.month === item.key) ?? null,
      ahead: false,
    })),
    ...plan
      .filter((entry) => !known.has(entry.month))
      .map((entry) => ({
        ...monthColumn(entry.month, entry.spent),
        average: null,
        forecast: entry,
        ahead: !entry.partial,
      })),
  ];

  // As many of the latest months as fit, moved back if the open month is older.
  const fit = Math.max(3, Math.floor(width / MIN_COLUMN));
  const latest = Math.max(0, columns.length - fit);
  const picked = columns.findIndex((item) => item.key === highlight);
  const from = picked >= 0 ? Math.min(Math.max(0, picked - 1), latest) : latest;
  const shown = columns.slice(from, from + fit);

  const height = 244;
  // Multiples of the 6-unit dot grid, so no dot is cut.
  const top = 36;
  const base = 192;
  const column = width / shown.length;
  // Bars are a whole number of dots wide. Each column draws from its own origin,
  // so the dot grid starts at its left edge and the columns stay evenly spaced.
  const barWidth = Math.max(12, Math.floor(Math.min(66, column * 0.62) / 6) * 6);
  const left = (index: number) => Math.round((index + 0.5) * column - barWidth / 2);
  const center = (index: number) => left(index) + barWidth / 2;
  const largest = Math.max(
    1,
    ...shown.map((item) => Math.max(item.spent, item.average ?? 0, item.forecast?.high ?? 0)),
  );
  const rise = (value: number) => Math.round(((base - top) * Math.max(0, value)) / largest / 6) * 6;
  /** Dot heights of a column: spent, then the likely and possible parts of a forecast. */
  const stack = (item: TrendColumn) => {
    const spent = item.ahead ? 0 : rise(item.spent);
    const low = item.forecast ? Math.max(spent, rise(item.forecast.low)) : spent;
    const high = item.forecast ? Math.max(low, rise(item.forecast.high)) : spent;
    const expected = item.forecast ? Math.min(high, Math.max(low, rise(item.forecast.expected))) : spent;
    return { spent, low, high, expected };
  };
  const everyValue = column >= 60;
  const averagePoints = lineOn
    ? shown
        .map((item, index) => (item.average === null ? null : `${center(index)},${base - rise(item.average)}`))
        .filter(Boolean)
        .join(" ")
    : "";
  const aheadAt = shown.findIndex((item) => item.ahead);
  const canPick = (item: TrendColumn) =>
    Boolean(onPick) && !item.ahead && (!pickable || pickable.includes(item.key));

  const focused = shown.find((item) => item.key === active) ?? null;
  const resting = shown.find((item) => item.key === highlight) ?? shown[shown.length - 1];
  const described = focused ?? resting;
  const stop = described?.key;

  return (
    <div className="stack" ref={box}>
      <svg
        className="chart"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label={`Net spending by ${unit}`}
        onPointerLeave={leave}
      >
        <defs>
          <PanelDefs id={id} top={top} bottom={base} />
          <DotPattern id={`${id}on`} color={ACCENT} />
          <DotPattern id={`${id}dim`} color="#5f731f" shine={0.3} />
          <DotPattern id={`${id}plan`} color={AMBER} shine={0.4} />
          <linearGradient id={`${id}fade`} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={base + 4} y2={base + 18}>
            <stop offset="0" stopColor="#fff" stopOpacity="0.32" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
          <mask id={`${id}mirror`} maskUnits="userSpaceOnUse" x="0" y={base} width={width} height="24">
            <rect x="0" y={base + 4} width={width} height="14" fill={`url(#${id}fade)`} />
          </mask>
        </defs>
        <g>
          {shown.map((item, index) => {
            const origin = left(index);
            const x = 0;
            const h = stack(item);
            const on = item.key === highlight;
            const lit = item.key === active;
            const fill = `url(#${id}${on || lit ? "on" : "dim"})`;
            const pick = canPick(item);
            return (
              <g
                key={item.key}
                className={`column ${pick ? "pick" : ""}`}
                role={pick ? "button" : "img"}
                tabIndex={item.key === stop ? 0 : -1}
                aria-label={`${describeColumn(item, lineOn ? averageLabel : null)
                  .map((part) => part.text)
                  .join(", ")}${on ? ", open" : ""}`}
                transform={`translate(${origin} 0)`}
                {...bind(item.key, pick ? () => onPick?.(item.key) : null)}
              >
                <rect x={index * column - origin} y="0" width={column} height={height} fill="transparent" />
                <Well id={id} x={x} y={top} width={barWidth} height={base - top} lit={lit} />
                {h.spent ? (
                  <>
                    <rect
                      x={x}
                      y={base - h.spent}
                      width={barWidth}
                      height={h.spent}
                      fill={fill}
                      style={on || lit ? { filter: `drop-shadow(0 0 4px ${rgba(ACCENT, on ? 0.7 : 0.4)})` } : undefined}
                    />
                    <rect
                      x={x}
                      y={base + 4}
                      width={barWidth}
                      height={14}
                      fill={fill}
                      mask={`url(#${id}mirror)`}
                      aria-hidden="true"
                    />
                  </>
                ) : null}
                {item.forecast ? (
                  <>
                    <rect
                      x={x}
                      y={base - h.low}
                      width={barWidth}
                      height={h.low - h.spent}
                      fill={`url(#${id}plan)`}
                      opacity="0.75"
                    />
                    <rect
                      x={x}
                      y={base - h.high}
                      width={barWidth}
                      height={h.high - h.low}
                      fill={`url(#${id}plan)`}
                      opacity="0.28"
                    />
                    <rect
                      x={x - 3}
                      y={base - h.expected - 1}
                      width={barWidth + 6}
                      height="2"
                      fill={AMBER}
                      style={{ filter: `drop-shadow(0 0 3px ${rgba(AMBER, 0.8)})` }}
                    />
                  </>
                ) : null}
                <Glass id={id} x={x} y={top} width={barWidth} height={base - top} />
                <text
                  x={x + barWidth / 2}
                  y={base + 30}
                  textAnchor="middle"
                  style={on ? { fill: ACCENT } : lit ? { fill: "#E9ECE3" } : undefined}
                >
                  {item.name}
                </text>
                {item.group !== shown[index - 1]?.group ? (
                  <text x={x + barWidth / 2} y={base + 43} textAnchor="middle" style={{ fontSize: 10 }}>
                    {item.group}
                  </text>
                ) : null}
              </g>
            );
          })}
        </g>
        <g pointerEvents="none">
          {aheadAt > 0 ? (
            <>
              <line
                x1={aheadAt * column}
                x2={aheadAt * column}
                y1="6"
                y2={base + 3}
                stroke="#3a4234"
                strokeDasharray="2 4"
              />
              <text x={aheadAt * column + 8} y="16" style={{ fill: AMBER, fontSize: 10, letterSpacing: 1 }}>
                FORECAST
              </text>
            </>
          ) : null}
          {averagePoints ? (
            <polyline
              points={averagePoints}
              fill="none"
              stroke={AVERAGE}
              strokeWidth="2"
              strokeDasharray="1 6"
              strokeLinecap="round"
            />
          ) : null}
          {/* Values go on last with a dark edge: above the column and the average
              line, or right on a forecast's expected bar. */}
          {shown.map((item, index) => {
            const on = item.key === highlight;
            const lit = item.key === active;
            if (!everyValue && !on && !lit) return null;
            const h = stack(item);
            const line = lineOn && item.average !== null ? rise(item.average) : 0;
            return (
              <text
                key={item.key}
                className="value"
                x={center(index)}
                y={base - (item.forecast ? h.expected : Math.max(h.spent, line)) - 8}
                textAnchor="middle"
                style={{ fill: item.forecast ? AMBER : on ? ACCENT : lit ? "#E9ECE3" : "#A7AF9E" }}
              >
                {item.forecast ? `~${compactMoney(item.forecast.expected)}` : compactMoney(item.spent)}
              </text>
            );
          })}
        </g>
      </svg>
      {described ? <ReadoutBar parts={describeColumn(described, lineOn ? averageLabel : null)} /> : null}
      <div className="legend">
        {average ? (
          <button type="button" aria-pressed={lineOn} onClick={() => setLineOn((value) => !value)}>
            <i style={{ backgroundColor: AVERAGE }} />
            {averageLabel}
          </button>
        ) : null}
        {forecast?.length ? (
          <button type="button" aria-pressed={planOn} onClick={() => setPlanOn((value) => !value)}>
            <i style={{ backgroundColor: AMBER }} />
            Forecast
          </button>
        ) : null}
      </div>
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
  const [box, width] = useWidth(720);
  const { active, bind, leave } = usePreview();
  if (!data.length) return null;
  const shown = data.slice(-Math.min(12, Math.max(3, Math.floor(width / MIN_COLUMN))));
  const most = Math.max(1, ...shown.map((item) => item.income + item.refunds));
  const least = Math.max(1, ...shown.map((item) => item.expenses));
  const top = 12;
  const dots = 32;
  // Room on each side of zero in proportion to what it has to hold, in whole dots.
  const above = Math.min(dots - 4, Math.max(4, Math.round((dots * most) / (most + least))));
  const middle = top + above * 6;
  const bottom = top + dots * 6;
  const height = bottom + 28;
  const perDot = Math.max(most / above, least / (dots - above));
  const scale = (value: number) => Math.round(value / perDot) * 6;
  const column = width / shown.length;
  const barWidth = Math.max(12, Math.floor(Math.min(54, column * 0.56) / 6) * 6);
  const described = shown.find((item) => item.month === active) ?? shown[shown.length - 1];
  const parts = (item: (typeof shown)[number]): Reading[] => [
    { text: monthColumn(item.month, 0).title },
    { text: `${money(item.income + item.refunds)} in`, tone: "ok" },
    { text: `${money(item.expenses)} out`, tone: "up" },
    { text: `net ${money(item.net, { signed: true })}`, tone: "warn" },
  ];
  return (
    <div className="stack" ref={box}>
      <svg
        className="chart"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label="Money in and out by month"
        onPointerLeave={leave}
      >
        <defs>
          <PanelDefs id={id} top={top} bottom={bottom} />
          <DotPattern id={`${id}in`} color={SAGE} />
          <DotPattern id={`${id}out`} color={CORAL} />
          <radialGradient id={`${id}net`} cx="38%" cy="34%" r="70%">
            <stop offset="0" stopColor="#fff6dc" />
            <stop offset="0.45" stopColor={AMBER} />
            <stop offset="1" stopColor="#b5861f" />
          </radialGradient>
        </defs>
        <g>
          {shown.map((item, index) => {
            const origin = Math.round((index + 0.5) * column - barWidth / 2);
            const up = scale(item.income + item.refunds);
            const down = scale(item.expenses);
            const net = Math.round(middle - (item.net / perDot) * 6);
            const on = item.month === described?.month;
            return (
              <g
                key={item.month}
                className="column"
                role="img"
                tabIndex={on ? 0 : -1}
                aria-label={parts(item)
                  .map((part) => part.text)
                  .join(", ")}
                transform={`translate(${origin} ${top})`}
                {...bind(item.month, null)}
              >
                <rect x={index * column - origin} y={-top} width={column} height={height} fill="transparent" />
                <Well id={id} x={0} y={0} width={barWidth} height={bottom - top} lit={item.month === active} />
                <rect x="0" y={middle - top - up} width={barWidth} height={up} fill={`url(#${id}in)`} />
                <rect x="0" y={middle - top} width={barWidth} height={down} fill={`url(#${id}out)`} />
                <Glass id={id} x={0} y={0} width={barWidth} height={bottom - top} />
                <circle
                  cx={barWidth / 2}
                  cy={net - top}
                  r="5"
                  fill={`url(#${id}net)`}
                  stroke="#070806"
                  strokeWidth="2"
                  style={{ filter: `drop-shadow(0 0 4px ${rgba(AMBER, 0.8)})` }}
                />
                <text
                  x={barWidth / 2}
                  y={bottom - top + 22}
                  textAnchor="middle"
                  style={on ? { fill: "#E9ECE3" } : undefined}
                >
                  {monthColumn(item.month, 0).name}
                </text>
              </g>
            );
          })}
        </g>
        <line x1="0" x2={width} y1={middle} y2={middle} stroke="#59614f" strokeDasharray="2 4" pointerEvents="none" />
      </svg>
      {described ? <ReadoutBar parts={parts(described)} /> : null}
    </div>
  );
}

/** Category changes as bars left (less) and right (more) of a center line. */
export function DriverBars({
  drivers,
  onPick,
}: {
  drivers: { category: string; current: number; previous: number; change: number; percent: number | null }[];
  onPick: (category: string) => void;
}) {
  const [track, width] = useWidth(306);
  const largest = Math.max(1, ...drivers.map((item) => Math.abs(item.change)));
  const half = Math.max(4, Math.floor((width - 4) / 2 / DOT));
  return (
    <div className="meters">
      {drivers.map((item, index) => {
        const more = item.change > 0;
        const count = Math.max(1, Math.round((Math.abs(item.change) / largest) * half));
        const color = more ? CORAL : SAGE;
        return (
          <button
            key={item.category}
            type="button"
            className="meter-row"
            onClick={() => onPick(item.category)}
          >
            <Glyph category={item.category} />
            <span className="truncate">{item.category}</span>
            <span className="track diverge" aria-hidden="true" ref={index ? undefined : track}>
              <span className="dots" />
              <span
                className="fill"
                style={{
                  left: more ? "50%" : `calc(50% - ${count * DOT}px)`,
                  width: `${count * DOT}px`,
                  backgroundImage: ledDots(color),
                  filter: `drop-shadow(0 0 3px ${rgba(color, 0.7)})`,
                }}
              />
            </span>
            <span className="num">
              <span className={more ? "up" : "ok"}>{money(item.change, { signed: true })}</span>
              <span className="tiny dim">
                {wholeMoney(item.previous)} → {wholeMoney(item.current)}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
