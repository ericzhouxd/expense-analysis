import { describe, expect, it } from "vitest";

import { money, parseCents, percent } from "./format";
import { keywordMatches } from "./keyword";
import { parseQuickEntry, type Vocabulary } from "./quickParse";

const vocabulary: Vocabulary = {
  today: "2026-11-09",
  categories: ["Food", "Dining Out", "Transportation", "Daily Necessities", "Entertainment", "Rent"],
  accounts: ["Checking", "Credit Card", "Cash"],
  paymentMethods: ["Apple Pay", "Card", "Bank Transfer", "Online", "Cash"],
  rules: [
    ["coffee", "Dining Out"],
    ["uber", "Transportation"],
    ["uber eats", "Dining Out"],
    ["grocer", "Food"],
    ["rent", "Rent"],
  ],
  merchants: { chipotle: "Dining Out", ralphs: "Food" },
  merchantNames: { chipotle: "Chipotle", ralphs: "Ralphs", "trader joe's": "Trader Joe's" },
};

describe("parseQuickEntry", () => {
  it("reads amount, relative date, merchant and category", () => {
    const draft = parseQuickEntry("12.50 chipotle lunch yesterday", vocabulary);
    expect(draft.amountCents).toBe(1250);
    expect(draft.date).toBe("2026-11-08");
    expect(draft.merchant).toBe("Chipotle");
    expect(draft.category).toBe("Dining Out");
    expect(draft.categorySource).toBe("merchant");
    expect(draft.description).toBe("Chipotle lunch");
  });

  it("prefers the longest rule and reads weekdays and payment methods", () => {
    const draft = parseQuickEntry("uber eats 23 fri apple pay", vocabulary);
    expect(draft.amountCents).toBe(2300);
    expect(draft.date).toBe("2026-11-06");
    expect(draft.category).toBe("Dining Out");
    expect(draft.paymentMethod).toBe("Apple Pay");
    expect(draft.description).toBe("Uber eats");
  });

  it("marks refunds and keeps word-edge rules", () => {
    const refund = parseQuickEntry("refund 16.40 target", vocabulary);
    expect(refund.type).toBe("refund");
    expect(refund.amountCents).toBe(1640);
    expect(parseQuickEntry("parent gift 20", vocabulary).category).toBeNull();
    expect(parseQuickEntry("groceries 40", vocabulary).category).toBe("Food");
  });

  it("understands calendar dates without jumping into the future", () => {
    expect(parseQuickEntry("nov 3 market 40", vocabulary).date).toBe("2026-11-03");
    expect(parseQuickEntry("3 nov market 40", vocabulary).amountCents).toBe(4000);
    expect(parseQuickEntry("12/28 gift 30", vocabulary).date).toBe("2025-12-28");
    expect(parseQuickEntry("2026-10-01 rent 1450", vocabulary).date).toBe("2026-10-01");
    expect(parseQuickEntry("last mon movie 15", vocabulary).date).toBe("2026-11-02");
    expect(parseQuickEntry("mon movie 15", vocabulary).date).toBe("2026-11-09");
    expect(parseQuickEntry("2 days ago bus 2.75", vocabulary).date).toBe("2026-11-07");
  });

  it("takes tags, accounts, cash and notes", () => {
    const draft = parseQuickEntry("$1,200.5 #ent concert from credit card note: with Sam", vocabulary);
    expect(draft.amountCents).toBe(120050);
    expect(draft.category).toBe("Entertainment");
    expect(draft.categorySource).toBe("tag");
    expect(draft.account).toBe("Credit Card");
    expect(draft.notes).toBe("with Sam");
    expect(draft.description).toBe("Concert");
    const cash = parseQuickEntry("coffee 4 cash", vocabulary);
    expect(cash.paymentMethod).toBe("Cash");
    expect(cash.account).toBe("Cash");
  });

  it("leaves an empty line empty", () => {
    const draft = parseQuickEntry("   ", vocabulary);
    expect(draft.amountCents).toBeNull();
    expect(draft.tokens).toEqual([]);
    expect(draft.date).toBe("2026-11-09");
  });
});

describe("keywordMatches mirrors Python", () => {
  it("matches word edges and plural endings", () => {
    expect(keywordMatches("rent", "Monthly rent")).toBe(true);
    expect(keywordMatches("rent", "parent")).toBe(false);
    expect(keywordMatches("rent", "rental car")).toBe(false);
    expect(keywordMatches("grocer", "Groceries")).toBe(true);
    expect(keywordMatches("記帳", "我的記帳本")).toBe(true);
  });
});

describe("format", () => {
  it("formats cents like format_dollars", () => {
    expect(money(123450)).toBe("$1,234.50");
    expect(money(-500)).toBe("−$5.00");
    expect(money(500, { signed: true })).toBe("+$5.00");
    expect(percent(13.94)).toBe("+13.9%");
    expect(percent(null)).toBe("—");
  });

  it("parses typed dollars into cents", () => {
    expect(parseCents("12.5")).toBe(1250);
    expect(parseCents("$1,200")).toBe(120000);
    expect(parseCents(".99")).toBe(99);
    expect(parseCents("12.345")).toBeNull();
    expect(parseCents("abc")).toBeNull();
  });
});
