import { type MouseEvent, useSyncExternalStore } from "react";

export const ROUTES = [
  { path: "/", label: "Overview", short: "Today", icon: "overview", key: "1" },
  { path: "/transactions", label: "Transactions", short: "List", icon: "list", key: "2" },
  { path: "/budgets", label: "Budget", short: "Budget", icon: "budget", key: "3" },
  { path: "/insights", label: "Insights", short: "Trends", icon: "insights", key: "4" },
  { path: "/settings", label: "Settings", short: "Settings", icon: "settings", key: "5" },
] as const;

export type RoutePath = (typeof ROUTES)[number]["path"];

export const BUDGET_TABS = [
  { to: "/budgets", label: "Term" },
  { to: "/budgets/year", label: "School year" },
  { to: "/budgets/setup", label: "Setup" },
];

export const SETTINGS_TABS = [
  { to: "/settings", label: "Categories" },
  { to: "/settings/accounts", label: "Accounts" },
  { to: "/settings/data", label: "Import & export" },
  { to: "/settings/app", label: "App" },
];

/** The page a path belongs to: `/budgets/year` is part of Budget. */
export function routeOf(path: string) {
  return ROUTES.find((item) => item.path === path || (item.path !== "/" && path.startsWith(`${item.path}/`)));
}

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
  if (to === snapshot() + window.location.hash) return;
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  window.dispatchEvent(new Event(EVENT));
  if (!replace) window.scrollTo({ top: 0 });
}

/** Follow in-app links without a page load; let modified clicks open new tabs. */
export function linkTo(to: string) {
  return {
    href: to,
    onClick: (event: MouseEvent<HTMLAnchorElement>) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
      event.preventDefault();
      navigate(to);
    },
  };
}

/** Transactions narrowed to a filter. */
export function transactionsUrl(filter: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(filter)) if (value) search.set(key, value);
  const text = search.toString();
  return text ? `/transactions?${text}` : "/transactions";
}

export function openQuickAdd(text = "") {
  window.dispatchEvent(new CustomEvent("jizhang:quick-add", { detail: text }));
}
