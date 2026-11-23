import { describe, expect, it } from "vitest";

import type { FrequentEntry } from "../api";
import { axis, versus } from "./format";
import { matchingEntries, wordsMatch } from "./palette";

function entry(description: string, merchant = ""): FrequentEntry {
  return {
    description,
    merchant,
    amount_cents: 100,
    category: "Food",
    account: "Checking",
    payment_method: "Card",
    count: 2,
    last: "2026-11-01",
  };
}

describe("matchingEntries", () => {
  const entries = [entry("Coffee", "Kettle & Co"), entry("Lunch bowl", "Burrito Barn"), entry("Cold brew")];

  it("matches word starts in the description or merchant and keeps the server's order", () => {
    expect(matchingEntries("bur lun", entries, 5).map((item) => item.description)).toEqual(["Lunch bowl"]);
    expect(matchingEntries("co", entries, 5).map((item) => item.description)).toEqual(["Coffee", "Cold brew"]);
    expect(matchingEntries("", entries, 2)).toHaveLength(2);
    expect(matchingEntries("rent", entries, 5)).toEqual([]);
  });

  it("finds scripts without word breaks", () => {
    expect(wordsMatch("超市", "大华超市")).toBe(true);
  });
});

describe("chart and comparison formatting", () => {
  it("ends an axis on a round amount that covers the largest value", () => {
    expect(axis(170_00)).toEqual({ top: 20000, ticks: [0, 10000, 20000] });
    for (const largest of [1, 999, 43210, 1785000]) {
      const { top, ticks } = axis(largest);
      expect(top).toBeGreaterThanOrEqual(largest);
      expect(ticks.length).toBeLessThanOrEqual(5);
    }
  });

  it("words a change the same way everywhere", () => {
    expect(versus(1200, "Oct 1–14", 8.04)).toBe("▲ $12.00 (8%) more than Oct 1–14");
    expect(versus(-500, "Oct 1–14", null)).toBe("▼ $5.00 less than Oct 1–14");
    expect(versus(0, "Oct 1–14")).toBe("same as Oct 1–14");
  });
});
