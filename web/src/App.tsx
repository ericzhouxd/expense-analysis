import { type MouseEvent, useEffect, useState } from "react";

import { QuickAdd } from "./components/QuickAdd";
import { Budgets } from "./pages/Budgets";
import { ImportExport } from "./pages/ImportExport";
import { Insights } from "./pages/Insights";
import { Overview } from "./pages/Overview";
import { Settings } from "./pages/Settings";
import { Transactions } from "./pages/Transactions";
import { navigate, ROUTES, useLocation } from "./router";

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

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName);
}

export function openQuickAdd(text = "") {
  window.dispatchEvent(new CustomEvent("jizhang:quick-add", { detail: text }));
}

const MOBILE = ["/", "/transactions", "add", "/budgets", "/insights"] as const;
const MOBILE_LABELS: Record<string, string> = {
  "/": "Today",
  "/transactions": "List",
  "/budgets": "Budget",
  "/insights": "Trends",
};

export function App() {
  const { path } = useLocation();
  const [adding, setAdding] = useState<string | null>(null);
  const route = ROUTES.find((item) => item.path === path);

  useEffect(() => {
    document.title = route && route.path !== "/" ? `${route.label} · 记账` : "记账";
  }, [route]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setAdding((current) => (current === null ? "" : current));
        return;
      }
      if (isTyping(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
      if (document.querySelector("[aria-modal='true']")) return;
      if (event.key === "n" || event.key === "a") {
        event.preventDefault();
        setAdding("");
        return;
      }
      const target = ROUTES.find((item) => item.key === event.key);
      if (target) navigate(target.path);
    }
    function onOpen(event: Event) {
      setAdding((event as CustomEvent<string>).detail ?? "");
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("jizhang:quick-add", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("jizhang:quick-add", onOpen);
    };
  }, []);

  let page;
  switch (path) {
    case "/transactions":
      page = <Transactions />;
      break;
    case "/budgets":
      page = <Budgets />;
      break;
    case "/insights":
      page = <Insights />;
      break;
    case "/import":
      page = <ImportExport />;
      break;
    case "/settings":
      page = <Settings />;
      break;
    case "/":
      page = <Overview />;
      break;
    default:
      page = (
        <div className="card empty">
          <h2>Nothing here</h2>
          <a {...linkTo("/")}>Back to the overview</a>
        </div>
      );
  }

  return (
    <>
      <a className="visually-hidden" href="#main">
        Skip to content
      </a>
      <div className="shell">
        <header className="topbar">
          <div className="brand">
            <a className="wordmark" lang="zh-Hant" {...linkTo("/")} aria-label="记账 home">
              记账
            </a>
            <nav className="nav" aria-label="Pages">
              {ROUTES.map((item) => (
                <a
                  key={item.path}
                  {...linkTo(item.path)}
                  aria-current={item.path === path ? "page" : undefined}
                  title={`${item.label} (${item.key})`}
                >
                  {item.label}
                </a>
              ))}
            </nav>
          </div>
          <button type="button" className="btn primary add-desktop" onClick={() => setAdding("")}>
            + Add <kbd>⌘K</kbd>
          </button>
        </header>
        <main id="main" key={path}>
          {page}
        </main>
      </div>
      <nav className="mobile-tabs" aria-label="Pages">
        {MOBILE.map((item) =>
          item === "add" ? (
            <button key="add" type="button" className="add" aria-label="Add a transaction" onClick={() => setAdding("")}>
              +
            </button>
          ) : (
            <a key={item} {...linkTo(item)} aria-current={item === path ? "page" : undefined}>
              {MOBILE_LABELS[item]}
            </a>
          ),
        )}
      </nav>
      {adding !== null ? <QuickAdd initialText={adding} onClose={() => setAdding(null)} /> : null}
    </>
  );
}
