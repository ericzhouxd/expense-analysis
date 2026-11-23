import { useEffect, useState } from "react";

import { Icon } from "./components/icons";
import { QuickAdd } from "./components/QuickAdd";
import { Empty } from "./components/ui";
import { Budgets } from "./pages/Budgets";
import { Insights } from "./pages/Insights";
import { Overview } from "./pages/Overview";
import { Settings } from "./pages/Settings";
import { Transactions } from "./pages/Transactions";
import { linkTo, navigate, ROUTES, routeOf, useLocation } from "./router";

const NAME = "記帳";
const [OVERVIEW, TRANSACTIONS, BUDGET, INSIGHTS, SETTINGS] = ROUTES;

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  // An open list or calendar takes letters and digits for itself.
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA"].includes(target.tagName) ||
    target.closest(".popover, [role='combobox'][aria-expanded='true']") !== null
  );
}

export function App() {
  const { path } = useLocation();
  const [adding, setAdding] = useState<string | null>(null);
  const route = routeOf(path);

  // Import and export moved under Settings; old bookmarks still work.
  useEffect(() => {
    if (path === "/import") navigate("/settings/data", { replace: true });
  }, [path]);

  useEffect(() => {
    document.title = route && route.path !== "/" ? `${route.label} · ${NAME}` : NAME;
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
      if (event.key === "/") {
        event.preventDefault();
        const search = () => document.querySelector<HTMLInputElement>("input[type='search']");
        if (search()) search()?.focus();
        else {
          navigate(TRANSACTIONS.path);
          window.setTimeout(() => search()?.focus(), 60);
        }
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
  switch (route?.path) {
    case "/":
      page = <Overview />;
      break;
    case "/transactions":
      page = <Transactions />;
      break;
    case "/budgets":
      page = <Budgets />;
      break;
    case "/insights":
      page = <Insights />;
      break;
    case "/settings":
      page = <Settings />;
      break;
    default:
      page =
        path === "/import" ? null : (
          <Empty title="Nothing here">
            <a className="btn" {...linkTo("/")}>
              Go to Overview
            </a>
          </Empty>
        );
  }

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="shell">
        <header className="topbar">
          <a className="wordmark" lang="zh-Hant" {...linkTo("/")} aria-label={`${NAME} home`}>
            {NAME}
          </a>
          <nav className="nav" aria-label="Pages">
            {ROUTES.map((item) => (
              <a
                key={item.path}
                {...linkTo(item.path)}
                aria-current={item === route ? "page" : undefined}
                title={`${item.label} (${item.key})`}
              >
                {item.label}
              </a>
            ))}
          </nav>
          <button type="button" className="btn primary add-desktop" onClick={() => setAdding("")}>
            + Add <kbd>⌘K</kbd>
          </button>
          <a
            className="btn ghost icon settings-mobile"
            {...linkTo(SETTINGS.path)}
            aria-label={SETTINGS.label}
            aria-current={route === SETTINGS ? "page" : undefined}
          >
            <Icon name={SETTINGS.icon} size={16} />
          </a>
        </header>
        <main id="main" tabIndex={-1} key={route?.path ?? path}>
          {page}
        </main>
      </div>
      <nav className="mobile-tabs" aria-label="Pages">
        {[OVERVIEW, TRANSACTIONS, null, BUDGET, INSIGHTS].map((item) =>
          item === null ? (
            <button key="add" type="button" className="add" aria-label="Add a transaction" onClick={() => setAdding("")}>
              <Icon name="plus" size={16} />
            </button>
          ) : (
            <a key={item.path} {...linkTo(item.path)} aria-current={item === route ? "page" : undefined}>
              <Icon name={item.icon} size={16} />
              {item.short}
            </a>
          ),
        )}
      </nav>
      {adding !== null ? <QuickAdd initialText={adding} onClose={() => setAdding(null)} /> : null}
    </>
  );
}
