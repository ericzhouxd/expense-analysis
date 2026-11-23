/** Typed access to the local API. Every amount is integer cents. */

import type { TransactionType } from "./lib/quickParse";

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") headers.set("X-Jizhang", "1");
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    let code: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown; code?: string };
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "Some fields are missing or invalid.";
      code = body.code;
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail, response.status, code);
  }
  return (await response.json()) as T;
}

export const get = <T>(path: string) => request<T>(path);
export const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const postBytes = <T>(path: string, body: ArrayBuffer) =>
  request<T>(path, {
    method: "POST",
    body,
    headers: { "Content-Type": "text/csv" },
  });

export interface Transaction {
  id: string;
  transaction_date: string;
  description: string;
  amount_cents: number;
  category: string;
  account: string;
  payment_method: string;
  merchant: string;
  transaction_type: TransactionType;
  notes: string;
  created_at?: string;
  updated_at?: string;
  spending_treatment?: string;
}

export type DraftFields = Pick<
  Transaction,
  | "transaction_date"
  | "description"
  | "amount_cents"
  | "category"
  | "account"
  | "payment_method"
  | "merchant"
  | "transaction_type"
  | "notes"
>;

export function draftOf(row: Transaction): DraftFields {
  return {
    transaction_date: row.transaction_date,
    description: row.description,
    amount_cents: row.amount_cents,
    category: row.category,
    account: row.account,
    payment_method: row.payment_method,
    merchant: row.merchant,
    transaction_type: row.transaction_type,
    notes: row.notes,
  };
}

export interface Bootstrap {
  today: string;
  categories: { name: string; spending_class: string }[];
  accounts: string[];
  payment_methods: string[];
  defaults: EntryDefaults;
  transaction_types: TransactionType[];
  treatments: string[];
  transaction_count: number;
  /** Purchases made more than once, likeliest to be repeated first, as last recorded. */
  frequent: FrequentEntry[];
  merchant_names: Record<string, string>;
}

/** What a new entry starts with; the category is for purchases nothing else sorts. */
export interface EntryDefaults {
  category: string;
  payment_method: string;
  account: string;
  transaction_type: TransactionType;
}

/** The category a new entry gets unless one is chosen, and why. */
export interface Suggestion {
  category: string;
  source: "rule" | "name" | "words" | "merchant" | "built-in" | "default" | "none";
  evidence: { text: string; category: string; count: number }[];
  /** How much of the evidence agrees, from 0 to 1. */
  share: number;
}

export interface FrequentEntry {
  description: string;
  merchant: string;
  amount_cents: number;
  category: string;
  account: string;
  payment_method: string;
  count: number;
  last: string;
}

export interface Comparison {
  current: number;
  previous: number | null;
  change: number | null;
  percent: number | null;
  start: string;
  end: string;
  prior_start: string;
  prior_end: string;
}

export type Cadence = "Monthly" | "Each quarter" | "Once";

export interface Week {
  start: string;
  end: string;
  label: string;
  state: "past" | "current" | "future";
  line: number;
  spent: number;
  left: number;
  saved: number | null;
}

export interface CurrentWeek extends Week {
  days_left: number;
  per_day: number;
  pace: number;
  days: { date: string; spent: number; future: boolean }[];
}

/** A warning tile for something that needs doing; `action` says where to fix it. */
export interface Signal {
  tone: "up" | "warn" | "ok" | "info";
  label: string;
  value: string;
  /** The whole of it, for screen readers. */
  text: string;
  action?: "uncategorized" | "bills" | "duplicates" | "coa";
  /** Transactions filter for the `duplicates` action. */
  filter?: { start: string; end: string; q: string };
}

export interface Overview {
  month: string;
  months: string[];
  scope: "everyday" | "all";
  as_of: string;
  is_current: boolean;
  days_in_month: number;
  has_transactions: boolean;
  spent: number;
  month_spent: number;
  treatment_totals: Record<string, number>;
  budget: null | {
    week: Pick<CurrentWeek, "label" | "start" | "end" | "line" | "spent" | "left" | "days_left" | "per_day" | "pace" | "days">;
    period: string;
    /** What each finished week of the term came to against its line. */
    weeks: number[];
    source: LineSource;
  };
  baseline: null | { total: number; month: string };
  comparisons: { month: Comparison; week: Comparison; year: Comparison };
  days: { date: string; spent: number; count: number; future: boolean }[];
  categories: { category: string; spent: number }[];
  ticker: { label: string; items: { name: string; amount: number; refund: boolean }[]; total: number };
  recent: Transaction[];
  /** The largest purchases, bills left out: the last `largest_days`, or the whole of a finished month. */
  largest: Transaction[];
  largest_days: number | null;
  monthly: { month: string; spent: number; rolling_3: number }[];
  weekly: { week: string; end: string; label: string; spent: number; rolling_4: number }[];
  signals: Signal[];
}

export interface Insights {
  month: string;
  months: string[];
  scope: "everyday" | "all";
  as_of: string;
  has_transactions: boolean;
  drivers: { category: string; current: number; previous: number; change: number; percent: number | null }[];
  cash_flow: { month: string; income: number; expenses: number; refunds: number; net: number }[];
  terms: { period: string; kind: PeriodKind; start: string; spent: number; weeks: number }[];
  monthly: { month: string; spent: number; rolling_3: number; rolling_6: number; rolling_12: number }[];
  forecast: Forecast;
  savings: { income: number; net_outflow: number; savings: number; rate: number | null };
  year: SchoolYear | null;
  duplicate_groups: number;
}

/** One month of the spending forecast; `partial` is the month in progress. */
export interface ForecastMonth {
  month: string;
  expected: number;
  low: number;
  high: number;
  spent: number;
  partial: boolean;
}

/** `months` is empty until there are two complete months to learn from. */
export interface Forecast {
  level: number;
  typical_miss: number | null;
  history_months: number;
  /** What a week of quarter, break or summer days costs, in cents. */
  weekly_rates: Partial<Record<PeriodKind, number>>;
  months: ForecastMonth[];
}

export type PeriodKind = "quarter" | "break" | "summer" | "month";

export interface SchoolYear {
  start: string;
  end: string;
  label: string;
  spent: number;
  estimate: number;
  estimate_to_date: number;
  line_to_date: number;
  saved: number;
  weeks_done: number;
  weeks: number;
}

/** A bill the student entered, as it is saved. */
export interface BillSetting {
  name: string;
  amount_cents: number;
  categories: string[];
  cadence: Cadence;
  due_day: number;
  due: string | null;
  pinned: boolean;
  /** Words naming the purchase, when the category holds other things too. */
  match: string[];
}

/** Any bill in use. Ones found in the ledger have a `key`; the student's own don't. */
export interface AutoBill extends BillSetting {
  key: string;
  yearly: boolean;
  why: string;
  next_due: string | null;
}

export type FactKey = "housing" | "cohort" | "residency" | "insurance";
export type FactValue = string | boolean;

/** One answer the app worked out, unless the source is `yours`. */
export interface Fact {
  key: FactKey;
  label: string;
  value: FactValue | null;
  text: string;
  source: "yours" | "learned" | "earlier" | "default";
  why: string;
  auto_text: string;
  auto_why: string;
  options: { value: FactValue; text: string }[];
}

/** How the projection did at this point of an earlier school year. */
export interface TrackRecord {
  label: string;
  projected: number;
  actual: number;
  miss: number;
  percent: number;
}

export interface AutoBudget {
  facts: Fact[];
  bills: AutoBill[];
  /** Found in the ledger, but the student said they aren't bills. */
  dismissed: AutoBill[];
  dismissed_keys: string[];
  weekly_cents: number | null;
  total_cents: number | null;
  /** Purchases from this amount on count as big stuff. */
  big_cents: number;
  record: TrackRecord[];
}

/** What the student settles by hand; null is automatic. */
export interface BudgetChoices {
  housing: string | null;
  cohort: string | null;
  residency: boolean | null;
  insurance: boolean | null;
  weekly_cents: number | null;
  total_cents: number | null;
  bills: BillSetting[];
  dismissed: string[];
}

/** The school's estimate, the student's own amount, or lowered to stay inside the cost of attendance. */
export type LineSource = "school" | "own" | "coa";

/** From certain to guessed: what makes up the projected year. */
export type CoaLayer = "recorded" | "due" | "everyday" | "one_offs" | "assumed";

interface CoaBase {
  school: string;
  year: string;
  source_url: string;
  verified_on: string;
}

/** The whole school year against the cost of attendance, or why there is no answer. */
export type CoaOutlook =
  | (CoaBase & { ready: false; reason: "year" | "profile" })
  | (CoaBase & {
      ready: true;
      start: string;
      end: string;
      /** The last day the ledger covers; later days are forecast. */
      through: string;
      complete: boolean;
      line: number;
      own_total: boolean;
      adjustment: number;
      layers: Record<CoaLayer, number>;
      projected: number;
      low: number;
      high: number;
      margin: number;
      /** 0 to 1. */
      chance: number;
      verdict: "over" | "close" | "under";
      weekly: null | {
        typical: number;
        /** Lands on the line if everything else goes as expected. */
        safe: number;
        /** Leaves room for costs that can't be known yet. */
        sure: number;
        possible: boolean;
        weeks_left: number;
      };
      changed_on: string | null;
      history_weeks: number;
      parts: {
        part: string;
        recorded: number;
        projected: number;
        published: number;
        difference: number;
        assumed: number;
      }[];
      notes: string[];
    });

export interface Budget {
  as_of: string;
  line: {
    weekly: number;
    source: LineSource;
    school_weekly: number;
    school_yearly: number;
    school_weeks: number;
    housing: string;
    components: Record<string, number>;
    books_per_quarter: number;
    school: string;
    year: string;
    source_url: string;
    verified_on: string;
  };
  auto: AutoBudget;
  period: {
    name: string;
    kind: PeriodKind;
    start: string;
    end: string;
    is_current: boolean;
    first_day: string | null;
    finals: string | null;
    previous: string | null;
    next: string | null;
  };
  weeks: Week[];
  week: CurrentWeek | null;
  totals: {
    everyday: number;
    bills: number;
    big_stuff: number;
    saved: number;
    line_to_date: number;
    weeks_done: number;
  };
  /** This week against the same weekdays of last week; null outside the current period. */
  comparison: Comparison | null;
  year: SchoolYear | null;
  periods: { name: string; kind: PeriodKind; start: string; end: string }[];
  coa: CoaOutlook;
  coa_parts: string[];
  cadences: Cadence[];
  treatments: {
    category: string;
    treatment: string;
    pinned: boolean;
    why: string;
    part: string;
    part_pinned: boolean;
  }[];
  treatment_options: string[];
  category_default: string;
}

export interface ChoiceEntry {
  name: string;
  count: number;
  unused: boolean;
  spending_class?: string;
  locked?: boolean;
  default?: boolean;
}

export type ChoiceKind = "category" | "account" | "payment_method";

export interface Choices {
  category: ChoiceEntry[];
  account: ChoiceEntry[];
  payment_method: ChoiceEntry[];
  defaults: EntryDefaults;
  transaction_types: TransactionType[];
  keyword_rules: { keyword: string; category: string; source: string }[];
}

export interface ChoiceUsage {
  kind: ChoiceKind;
  name: string;
  count: number;
  unused: boolean;
  latest: Transaction[];
  replacements: string[];
}

export interface ImportPreview {
  rows: {
    row: number;
    status: "ready" | "duplicate" | "invalid";
    date: string | null;
    description: string;
    amount_cents: number | null;
    category: string;
    type: string;
    merchant: string;
    issue: string;
  }[];
  ready: number;
  duplicates: number;
  invalid: number;
  unknown_categories: string[];
  category_options: string[];
}

export interface SettingsInfo {
  database_path: string;
  config_path: string;
  config_exists: boolean;
  transaction_count: number;
  binding: string;
  school_calendar: {
    source: string;
    quarters: {
      name: string;
      quarter_begins: string;
      instruction_begins: string;
      finals_begin: string;
      quarter_ends: string;
    }[];
  };
}
