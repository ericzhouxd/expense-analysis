/**
 * Category keyword rules, matched exactly like `models.keyword_matches` in Python:
 * ASCII word edges plus plural endings; other scripts match as plain substrings.
 * Change both together.
 */

const SUFFIXES = new Set(["", "s", "es", "y", "ies"]);

export function normalizeText(value: string): string {
  return value.toLocaleLowerCase("en-US").split(/\s+/).filter(Boolean).join(" ");
}

function isWordChar(character: string | undefined): boolean {
  return !!character && /^[A-Za-z0-9]$/.test(character);
}

export function keywordMatches(keyword: string, text: string): boolean {
  const needle = normalizeText(keyword);
  const haystack = normalizeText(text);
  if (!needle) return false;
  let start = haystack.indexOf(needle);
  while (start !== -1) {
    const end = start + needle.length;
    const beforeOk =
      !isWordChar(needle[0]) || start === 0 || !isWordChar(haystack[start - 1]);
    let tailEnd = end;
    while (tailEnd < haystack.length && isWordChar(haystack[tailEnd])) tailEnd += 1;
    const afterOk =
      !isWordChar(needle[needle.length - 1]) || SUFFIXES.has(haystack.slice(end, tailEnd));
    if (beforeOk && afterOk) return true;
    start = haystack.indexOf(needle, start + 1);
  }
  return false;
}
