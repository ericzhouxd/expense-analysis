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
  treatment_review?: boolean;
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
  default_account: string;
  default_payment_method: string;
  transaction_types: TransactionType[];
  treatments: string[];
  transaction_count: number;
  rules: [string, string][];
  merchants: Record<string, string>;
  merchant_names: Record<string, string>;
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

/** One due date of a bill inside the period being viewed. */
export interface BillDue {
  name: string;
  amount: number;
  due: string;
  paid: number;
  status: "paid" | "late" | "soon" | "upcoming";
  categories: string[];
  cadence: Cadence;
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

export interface Signal {
  tone: "up" | "warn" | "ok" | "info";
  text: string;
  action?: "uncategorized" | "treatments" | "budgets";
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
  review_count: number;
  budget: null | {
    week: Pick<CurrentWeek, "label" | "start" | "end" | "line" | "spent" | "left" | "days_left" | "per_day" | "pace" | "days">;
    period: string;
    saved: number;
    weeks_done: number;
    source: "school" | "own";
  };
  baseline: null | { total: number; month: string };
  comparisons: { month: Comparison; week: Comparison; year: Comparison };
  days: { date: string; spent: number; count: number; future: boolean }[];
  categories: { category: string; spent: number }[];
  bills: BillDue[];
  ticker: { label: string; items: { name: string; amount: number; refund: boolean }[]; total: number };
  recent: Transaction[];
  monthly: { month: string; spent: number; rolling_3: number }[];
  signals: Signal[];
}

export interface Insights {
  month: string;
  months: string[];
  scope: "everyday" | "all";
  as_of: string;
  has_transactions: boolean;
  drivers: { category: string; current: number; previous: number; change: number; percent: number | null }[];
  recurring: {
    merchant: string;
    frequency: string;
    occurrences: number;
    average: number;
    interval_days: number;
    last_seen: string;
    next_expected: string;
    status: string;
  }[];
  anomalies: {
    date: string;
    description: string;
    category: string;
    amount: number;
    typical: number;
    score: number;
  }[];
  cash_flow: { month: string; income: number; expenses: number; refunds: number; net: number }[];
  terms: { period: string; kind: PeriodKind; start: string; spent: number; weeks: number }[];
  monthly: { month: string; spent: number; rolling_3: number; rolling_6: number; rolling_12: number }[];
  savings: { income: number; net_outflow: number; savings: number; rate: number | null };
  year: SchoolYear | null;
  duplicate_groups: number;
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

export interface BillSetting {
  name: string;
  amount_cents: number;
  categories: string[];
  cadence: Cadence;
  due_day: number;
  due: string | null;
}

export interface BudgetSettings {
  housing: string;
  weekly_cents: number | null;
  bills: BillSetting[];
}

export interface Budget {
  as_of: string;
  line: {
    weekly: number;
    source: "school" | "own";
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
  settings: BudgetSettings;
  saved_settings: boolean;
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
  bills: BillDue[];
  big_stuff: Transaction[];
  year: SchoolYear | null;
  periods: { name: string; kind: PeriodKind; start: string; end: string }[];
  housing_options: string[];
  housing_estimates: Record<string, { school_weekly: number; school_yearly: number }>;
  cadences: Cadence[];
  treatments: { category: string; treatment: string; saved: boolean }[];
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
