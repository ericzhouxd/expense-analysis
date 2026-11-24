/** Small choices remembered in this browser. Losing them only resets a view. */

import { useSyncExternalStore } from "react";

const EVENT = "jizhang:prefs";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(`jizhang:${key}`);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    window.localStorage.setItem(`jizhang:${key}`, value);
  } catch {
    /* private window: the choice lasts until reload */
  }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(callback: () => void) {
  window.addEventListener(EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

/** One of a few known values, remembered between visits. */
export function usePref<T extends string>(key: string, values: readonly [T, ...T[]]): [T, (value: T) => void] {
  const stored = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null,
  );
  const value = values.find((item) => item === stored) ?? values[0];
  return [value, (next) => write(key, next)];
}

/** Everyday spending only, or all of it; shared by Overview and Insights. */
export function useScope() {
  return usePref("scope", ["everyday", "all"] as const);
}
