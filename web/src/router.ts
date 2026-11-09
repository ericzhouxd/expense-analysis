import { useSyncExternalStore } from "react";

export const ROUTES = [
  { path: "/", label: "Overview", key: "1" },
  { path: "/transactions", label: "Transactions", key: "2" },
  { path: "/budgets", label: "Budgets", key: "3" },
  { path: "/insights", label: "Insights", key: "4" },
  { path: "/import", label: "Import / Export", key: "5" },
  { path: "/settings", label: "Settings", key: "6" },
] as const;

export type RoutePath = (typeof ROUTES)[number]["path"];

const EVENT = "jizhang:navigate";

function subscribe(callback: () => void): () => void {
  window.addEventListener("popstate", callback);
  window.addEventListener(EVENT, callback);
  return () => {
    window.removeEventListener("popstate", callback);
    window.removeEventListener(EVENT, callback);
  };
}

function snapshot(): string {
  return window.location.pathname + window.location.search;
}

export function useLocation(): { path: string; params: URLSearchParams } {
  const location = useSyncExternalStore(subscribe, snapshot, () => "/");
  const [path = "/", search = ""] = location.split("?");
  return { path, params: new URLSearchParams(search) };
}

export function navigate(to: string, { replace = false } = {}): void {
  if (to === snapshot()) return;
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  window.dispatchEvent(new Event(EVENT));
  if (!replace) window.scrollTo({ top: 0 });
}
