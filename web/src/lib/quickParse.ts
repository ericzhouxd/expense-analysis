/**
 * Turn one typed line ("12.50 chipotle lunch yesterday apple pay") into a draft.
 * Runs locally on every keystroke; the server still validates and categorizes on save.
 */

import { addDays, iso, parseIso } from "./format";
import { keywordMatches, normalizeText } from "./keyword";

export type TransactionType = "expense" | "refund" | "income" | "transfer";

export interface Vocabulary {
  today: string;
  categories: string[];
  accounts: string[];
  paymentMethods: string[];
  rules: [string, string][];
  merchants: Record<string, string>;
  merchantNames: Record<string, string>;
}

export type Role =
  | "amount"
  | "date"
  | "type"
  | "category"
  | "payment"
  | "account"
  | "note"
  | "text"
  | "filler";

export interface Token {
  text: string;
  role: Role;
}

export interface ParsedDraft {
  amountCents: number | null;
  date: string;
  dateWords: string | null;
  type: TransactionType;
  description: string;
  merchant: string;
  category: string | null;
  categorySource: "tag" | "rule" | "merchant" | null;
  categoryReason: string;
  paymentMethod: string | null;
  account: string | null;
  notes: string;
  tokens: Token[];
}

const WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const WEEKDAY_FORMS = [
  ["sun", "sunday"],
  ["mon", "monday"],
  ["tue", "tues", "tuesday"],
  ["wed", "weds", "wednesday"],
  ["thu", "thur", "thurs", "thursday"],
  ["fri", "friday"],
  ["sat", "saturday"],
];
const MONTHS = [
  "january",
  "february",
  "march",
  "april",
  "may",
  "june",
  "july",
  "august",
  "september",
  "october",
  "november",
  "december",
];
const TYPE_WORDS: Record<string, TransactionType> = {
  refund: "refund",
  refunded: "refund",
  return: "refund",
  returned: "refund",
  income: "income",
  salary: "income",
  paycheck: "income",
  payday: "income",
  transfer: "transfer",
  transferred: "transfer",
};
const PAYMENT_SYNONYMS: Record<string, string[]> = {
  "apple pay": ["apple pay", "applepay", "apay"],
  card: ["card", "debit", "credit"],
  cash: ["cash"],
  "bank transfer": ["bank transfer", "zelle", "ach"],
  online: ["online"],
  venmo: ["venmo"],
};
const FILLERS = new Set(["on", "with", "via", "at", "for", "paid", "using", "from", "by"]);

function clean(word: string): string {
  return word.toLowerCase().replace(/^[("']+|[)"',;.!?]+$/g, "");
}

function monthIndex(word: string): number {
  const bare = word.replace(/\.$/, "");
  if (bare.length < 3) return -1;
  return MONTHS.findIndex((month) => month.startsWith(bare));
}

function weekdayIndex(word: string): number {
  return WEEKDAY_FORMS.findIndex((forms) => forms.includes(word));
}

/** Pick the year that keeps a month/day from landing more than a week ahead. */
function resolveYear(today: Date, month: number, day: number, year?: number): Date | null {
  if (month < 0 || month > 11 || day < 1 || day > 31) return null;
  if (year !== undefined) {
    const full = year < 100 ? 2000 + year : year;
    const date = new Date(full, month, day);
    return date.getMonth() === month ? date : null;
  }
  let date = new Date(today.getFullYear(), month, day);
  if (date.getMonth() !== month) return null;
  if (date.getTime() > addDays(today, 7).getTime()) {
    date = new Date(today.getFullYear() - 1, month, day);
  }
  return date;
}

interface DateHit {
  date: Date;
  used: number;
}

export function readDate(words: string[], index: number, today: Date): DateHit | null {
  const word = clean(words[index] ?? "");
  const next = clean(words[index + 1] ?? "");
  const after = clean(words[index + 2] ?? "");
  if (!word) return null;
  if (["today", "tod", "now"].includes(word)) return { date: today, used: 1 };
  if (["yesterday", "yday", "yest"].includes(word)) return { date: addDays(today, -1), used: 1 };
  if (word === "last" || word === "this") {
    const day = weekdayIndex(next);
    if (day >= 0) {
      let back = (today.getDay() - day + 7) % 7;
      if (word === "last" && back === 0) back = 7;
      return { date: addDays(today, -back), used: 2 };
    }
    return null;
  }
  const day = weekdayIndex(word);
  if (day >= 0) {
    return { date: addDays(today, -((today.getDay() - day + 7) % 7)), used: 1 };
  }
  const ago = /^(\d{1,2})d$/.exec(word);
  if (ago) return { date: addDays(today, -Number(ago[1])), used: 1 };
  if (/^\d{1,2}$/.test(word) && /^days?$/.test(next) && after === "ago") {
    return { date: addDays(today, -Number(word)), used: 3 };
  }
  const isoMatch = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(word);
  if (isoMatch) {
    const date = resolveYear(
      today,
      Number(isoMatch[2]) - 1,
      Number(isoMatch[3]),
      Number(isoMatch[1]),
    );
    return date ? { date, used: 1 } : null;
  }
  const slash = /^(\d{1,2})\/(\d{1,2})(?:\/(\d{2}|\d{4}))?$/.exec(word);
  if (slash) {
    const date = resolveYear(
      today,
      Number(slash[1]) - 1,
      Number(slash[2]),
      slash[3] ? Number(slash[3]) : undefined,
    );
    return date ? { date, used: 1 } : null;
  }
  const month = monthIndex(word);
  if (month >= 0 && /^\d{1,2}(st|nd|rd|th)?$/.test(next)) {
    const date = resolveYear(today, month, parseInt(next, 10));
    return date ? { date, used: 2 } : null;
  }
  if (/^\d{1,2}(st|nd|rd|th)?$/.test(word) && monthIndex(next) >= 0) {
    const date = resolveYear(today, monthIndex(next), parseInt(word, 10));
    return date ? { date, used: 2 } : null;
  }
  return null;
}

function readAmount(word: string): number | null {
  const match = /^[+-]?\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\$?$/.exec(word.replace(/[,;]$/, ""));
  if (!match) return null;
  const whole = Number((match[1] ?? "0").replace(/,/g, ""));
  const fraction = Number(((match[2] ?? "") + "00").slice(0, 2));
  const cents = whole * 100 + fraction;
  return Number.isSafeInteger(cents) ? cents : null;
}

function findPhrase(
  words: string[],
  index: number,
  phrases: [string, string][],
): { value: string; used: number } | null {
  for (const [phrase, value] of phrases) {
    const parts = phrase.split(" ");
    const slice = words.slice(index, index + parts.length).map(clean);
    if (slice.length === parts.length && slice.every((part, i) => part === parts[i])) {
      return { value, used: parts.length };
    }
  }
  return null;
}

function paymentPhrases(methods: string[]): [string, string][] {
  const phrases: [string, string][] = [];
  for (const method of methods) {
    const key = method.toLowerCase();
    phrases.push([key, method]);
    for (const synonym of PAYMENT_SYNONYMS[key] ?? []) phrases.push([synonym, method]);
  }
  return phrases.sort((a, b) => b[0].split(" ").length - a[0].split(" ").length);
}

function categoryFromTag(tag: string, categories: string[]): string | null {
  const wanted = tag.toLowerCase().replace(/[-_]/g, " ");
  const squashed = wanted.replace(/\s/g, "");
  return (
    categories.find((name) => name.toLowerCase() === wanted) ??
    categories.find((name) => name.toLowerCase().replace(/\s/g, "") === squashed) ??
    categories.find((name) => name.toLowerCase().startsWith(wanted)) ??
    categories.find((name) => name.toLowerCase().replace(/\s/g, "").startsWith(squashed)) ??
    null
  );
}

export function suggestCategory(
  description: string,
  merchant: string,
  vocabulary: Pick<Vocabulary, "rules" | "merchants">,
): { category: string; keyword: string; source: "rule" | "merchant" } | null {
  const rules = [...vocabulary.rules].sort((a, b) => b[0].length - a[0].length);
  for (const text of [description, merchant]) {
    for (const [keyword, category] of rules) {
      if (keywordMatches(keyword, text)) return { category, keyword, source: "rule" };
    }
  }
  const known = vocabulary.merchants[normalizeText(merchant)];
  return known ? { category: known, keyword: merchant, source: "merchant" } : null;
}

function findMerchant(text: string, names: Record<string, string>): string {
  const keys = Object.keys(names).sort((a, b) => b.length - a.length);
  const hit = keys.find((key) => key && keywordMatches(key, text));
  return hit ? (names[hit] ?? "") : "";
}

export function parseQuickEntry(input: string, vocabulary: Vocabulary): ParsedDraft {
  const today = parseIso(vocabulary.today);
  const noteAt = input.search(/(^|\s)(note|notes):/i);
  const main = noteAt >= 0 ? input.slice(0, noteAt) : input;
  const notes = noteAt >= 0 ? input.slice(noteAt).replace(/^\s*notes?:\s*/i, "").trim() : "";
  const words = main.split(/\s+/).filter(Boolean);
  const payments = paymentPhrases(vocabulary.paymentMethods);
  const accounts: [string, string][] = vocabulary.accounts
    .map((account): [string, string] => [account.toLowerCase(), account])
    .sort((a, b) => b[0].split(" ").length - a[0].split(" ").length);

  const result: ParsedDraft = {
    amountCents: null,
    date: vocabulary.today,
    dateWords: null,
    type: "expense",
    description: "",
    merchant: "",
    category: null,
    categorySource: null,
    categoryReason: "",
    paymentMethod: null,
    account: null,
    notes,
    tokens: [],
  };
  const text: string[] = [];

  for (let index = 0; index < words.length; index += 1) {
    const raw = words[index] ?? "";
    const word = clean(raw);
    if (raw.startsWith("@") || raw.startsWith("#")) {
      const category = categoryFromTag(raw.slice(1), vocabulary.categories);
      if (category) {
        result.category = category;
        result.categorySource = "tag";
        result.categoryReason = `tagged ${raw}`;
        result.tokens.push({ text: raw, role: "category" });
        continue;
      }
    }
    if (!result.dateWords) {
      const hit = readDate(words, index, today);
      if (hit) {
        result.date = iso(hit.date);
        result.dateWords = words.slice(index, index + hit.used).join(" ");
        result.tokens.push({ text: result.dateWords, role: "date" });
        index += hit.used - 1;
        continue;
      }
    }
    if (result.amountCents === null) {
      const amount = readAmount(raw);
      if (amount !== null) {
        result.amountCents = amount;
        result.tokens.push({ text: raw, role: "amount" });
        continue;
      }
    }
    const type = TYPE_WORDS[word];
    if (type && result.type === "expense") {
      result.type = type;
      result.tokens.push({ text: raw, role: "type" });
      continue;
    }
    if (!result.account) {
      const account = findPhrase(words, index, accounts);
      const afterFiller = index > 0 && FILLERS.has(clean(words[index - 1] ?? ""));
      if (account && (afterFiller || account.used > 1)) {
        result.account = account.value;
        const method = vocabulary.paymentMethods.find(
          (name) => name.toLowerCase() === account.value.toLowerCase(),
        );
        if (method && !result.paymentMethod) result.paymentMethod = method;
        result.tokens.push({
          text: words.slice(index, index + account.used).join(" "),
          role: "account",
        });
        index += account.used - 1;
        continue;
      }
    }
    if (!result.paymentMethod) {
      const payment = findPhrase(words, index, payments);
      if (payment) {
        result.paymentMethod = payment.value;
        const account = accounts.find(([key]) => key === payment.value.toLowerCase());
        if (account && !result.account) result.account = account[1];
        result.tokens.push({
          text: words.slice(index, index + payment.used).join(" "),
          role: "payment",
        });
        index += payment.used - 1;
        continue;
      }
    }
    if (FILLERS.has(word) && index + 1 < words.length) {
      result.tokens.push({ text: raw, role: "filler" });
      continue;
    }
    text.push(raw);
    result.tokens.push({ text: raw, role: "text" });
  }

  const description = text.join(" ").trim();
  result.description = description ? description.charAt(0).toUpperCase() + description.slice(1) : "";
  result.merchant = findMerchant(description, vocabulary.merchantNames);
  if (!result.category) {
    const suggestion = suggestCategory(description, result.merchant, vocabulary);
    if (suggestion && vocabulary.categories.includes(suggestion.category)) {
      result.category = suggestion.category;
      result.categorySource = suggestion.source;
      result.categoryReason =
        suggestion.source === "rule"
          ? `matched “${suggestion.keyword}”`
          : `usual for ${result.merchant}`;
    }
  }
  return result;
}

export const WEEKDAY_NAMES = WEEKDAYS;
