/** What the ⌘K panel offers besides the line being typed. */

import type { FrequentEntry } from "../api";
import { normalizeText } from "./keyword";

/** Every typed word must start some word of the text, so "bur lun" finds "Burrito lunch". */
export function wordsMatch(query: string, text: string): boolean {
  const words = normalizeText(text).split(/[^\p{L}\p{N}]+/u);
  return normalizeText(query)
    .split(" ")
    .filter(Boolean)
    .every((part) => words.some((word) => word.startsWith(part)) || normalizeText(text).includes(part));
}

/** Earlier purchases matching what is typed, in the order the server ranked them. */
export function matchingEntries(query: string, entries: FrequentEntry[], limit: number): FrequentEntry[] {
  return entries
    .filter((entry) => wordsMatch(query, `${entry.description} ${entry.merchant}`))
    .slice(0, limit);
}
