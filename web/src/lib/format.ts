/** Money and dates, formatted the same way as `models.format_dollars` in Python. */

const MINUS = "−";

export function money(cents: number, options: { signed?: boolean; plain?: boolean } = {}): string {
  const sign = cents < 0 ? MINUS : options.signed && cents > 0 ? "+" : "";
  const dollars = (Math.abs(cents) / 100).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${sign}${options.plain ? "" : "$"}${dollars}`;
}

/** Whole dollars for tight spots such as chart labels: $1.2k, $640. */
export function compactMoney(cents: number): string {
  const dollars = Math.abs(cents) / 100;
  const sign = cents < 0 ? MINUS : "";
  if (dollars >= 10000) return `${sign}$${Math.round(dollars / 1000)}k`;
  if (dollars >= 1000) return `${sign}$${(dollars / 1000).toFixed(1)}k`;
  return `${sign}$${Math.round(dollars)}`;
}

/** Whole dollars in full, for estimates where cents would claim too much: $1,240. */
export function wholeMoney(cents: number): string {
  const sign = cents < 0 ? MINUS : "";
  return `${sign}$${Math.round(Math.abs(cents) / 100).toLocaleString("en-US")}`;
}

export function percent(value: number | null | undefined, signed = true): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const text = `${Math.abs(value).toFixed(1)}%`;
  if (!signed) return text;
  return value < 0 ? `${MINUS}${text}` : value > 0 ? `+${text}` : text;
}

/**
 * A change against an earlier figure, worded the same way wherever it appears:
 * "▲ $12.00 (8.0%) more than Oct 1–14".
 */
export function versus(change: number, than: string, percentChange?: number | null): string {
  if (change === 0) return `same as ${than}`;
  const share =
    percentChange === null || percentChange === undefined || !Number.isFinite(percentChange)
      ? ""
      : ` (${percent(Math.abs(percentChange), false)})`;
  return `${change > 0 ? "▲" : "▼"} ${money(Math.abs(change))}${share} ${change > 0 ? "more" : "less"} than ${than}`;
}

/** Parse what someone typed as dollars into positive integer cents, or null. */
export function parseCents(input: string): number | null {
  const cleaned = input.replace(/[$,\s]/g, "");
  if (!/^\d+(\.\d{0,2})?$|^\.\d{1,2}$/.test(cleaned)) return null;
  const [whole = "0", fraction = ""] = cleaned.split(".");
  const cents = Number(whole || "0") * 100 + Number((fraction + "00").slice(0, 2));
  return Number.isSafeInteger(cents) ? cents : null;
}

export function centsToInput(cents: number): string {
  return (cents / 100).toFixed(2);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Parse YYYY-MM-DD as a local calendar date (never through UTC). */
export function parseIso(value: string): Date {
  const [year = 1970, month = 1, day = 1] = value.slice(0, 10).split("-").map(Number);
  return new Date(year, month - 1, day);
}

export function iso(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

export function shortDate(value: string): string {
  const date = parseIso(value);
  return `${MONTHS[date.getMonth()]} ${date.getDate()}`;
}

export function dayLabel(value: string, today?: string): string {
  const date = parseIso(value);
  const base = `${WEEKDAYS[date.getDay()]}, ${MONTHS[date.getMonth()]} ${date.getDate()}`;
  if (today) {
    const difference = Math.round((parseIso(today).getTime() - date.getTime()) / 86400000);
    if (difference === 0) return `Today · ${base}`;
    if (difference === 1) return `Yesterday · ${base}`;
  }
  return date.getFullYear() === (today ? parseIso(today).getFullYear() : date.getFullYear())
    ? base
    : `${base}, ${date.getFullYear()}`;
}

export function weekday(value: string): string {
  return WEEKDAYS[parseIso(value).getDay()] ?? "";
}

export function monthLabel(month: string, long = true): string {
  const [year, number] = month.split("-").map(Number);
  const names = long ? MONTHS_LONG : MONTHS;
  return `${names[(number ?? 1) - 1]} ${year}`;
}

export function monthName(month: string): string {
  const number = Number(month.split("-")[1]);
  return MONTHS_LONG[number - 1] ?? month;
}

export function rangeLabel(start: string, end: string): string {
  const a = parseIso(start);
  const b = parseIso(end);
  if (a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear()) {
    return `${MONTHS[a.getMonth()]} ${a.getDate()}–${b.getDate()}`;
  }
  return `${shortDate(start)}–${shortDate(end)}`;
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count.toLocaleString("en-US")} ${count === 1 ? one : many}`;
}

export const MONTH_NAMES = MONTHS_LONG;
export const MONTH_SHORT = MONTHS;
