import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { type ChoiceEntry, type ChoiceKind, get, post, type SettingsInfo } from "../api";
import { RemoveDialog } from "../components/ChoiceCombo";
import { useToast } from "../components/feedback";
import { Card, Glyph, Led } from "../components/instrument";
import { plural, shortDate, weekday } from "../lib/format";
import { categoryColor } from "../lib/glyphs";
import { useChoices, useRefresh } from "../queries";

const NOUNS: Record<ChoiceKind, string> = {
  category: "category",
  account: "account",
  payment_method: "payment method",
};

function ChoiceList({ kind, title, entries }: { kind: ChoiceKind; title: string; entries: ChoiceEntry[] }) {
  const refresh = useRefresh();
  const toast = useToast();
  const [name, setName] = useState("");
  const [spendingClass, setSpendingClass] = useState("Personal");
  const [keyword, setKeyword] = useState("");
  const [renaming, setRenaming] = useState<{ source: string; value: string } | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  async function save(body: Record<string, string>, message: string) {
    try {
      await post(`/api/choices/${kind}/save`, body);
      await refresh();
      toast.show(message);
      return true;
    } catch (error) {
      toast.error(error);
      return false;
    }
  }

  async function remove(entry: ChoiceEntry) {
    if (!entry.unused) {
      setRemoving(entry.name);
      return;
    }
    try {
      const result = await post<{ undo: { name: string; spending_class: string | null } | null }>(
        `/api/choices/${kind}/delete`,
        { source: entry.name },
      );
      await refresh();
      toast.show(`Removed “${entry.name}”.`, {
        action: result.undo
          ? {
              label: "Undo",
              run: async () => {
                await post(`/api/choices/${kind}/restore`, result.undo);
                await refresh();
              },
            }
          : undefined,
      });
    } catch (error) {
      toast.error(error);
    }
  }

  return (
    <Card title={title} hint={plural(entries.length, "choice")}>
      <form
        className="row"
        onSubmit={async (event) => {
          event.preventDefault();
          const value = name.trim();
          if (!value) return;
          const body: Record<string, string> = { name: value };
          if (kind === "category") {
            body.spending_class = spendingClass;
            body.keyword = keyword.trim();
          }
          if (await save(body, `Added “${value}”.`)) {
            setName("");
            setKeyword("");
          }
        }}
      >
        <input className="input grow" style={{ width: "auto", minWidth: 120, flexBasis: 120 }} placeholder={`New ${NOUNS[kind]}`} value={name} onChange={(event) => setName(event.target.value)} aria-label="Name" />
        {kind === "category" ? (
          <>
            <input
              className="input"
              style={{ width: 140 }}
              placeholder="keyword"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              aria-label="Keyword that picks this category"
            />
            <select className="input" style={{ width: 120 }} value={spendingClass} onChange={(event) => setSpendingClass(event.target.value)} aria-label="Spending class">
              <option>Personal</option>
              <option>Fixed</option>
            </select>
          </>
        ) : null}
        <button type="submit" className="btn" disabled={!name.trim()}>
          Add
        </button>
      </form>
      <div>
        {entries.map((entry) => (
          <div key={entry.name} className="bill-row" style={{ gridTemplateColumns: kind === "category" ? "34px minmax(0,1fr) auto" : "minmax(0,1fr) auto" }}>
            {kind === "category" ? <Glyph category={entry.name} small /> : null}
            {renaming?.source === entry.name ? (
              <form
                className="row"
                onSubmit={async (event) => {
                  event.preventDefault();
                  const value = renaming.value.trim();
                  if (!value || value === entry.name) {
                    setRenaming(null);
                    return;
                  }
                  const body: Record<string, string> = { name: value, source: entry.name };
                  if (kind === "category") body.spending_class = entry.spending_class ?? "Personal";
                  if (await save(body, `Renamed to “${value}”; ${plural(entry.count, "transaction")} updated.`)) setRenaming(null);
                }}
              >
                <input
                  className="input grow"
                  style={{ width: "auto" }}
                  autoFocus
                  aria-label={`Rename ${entry.name}`}
                  value={renaming.value}
                  onChange={(event) => setRenaming({ source: entry.name, value: event.target.value })}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") setRenaming(null);
                  }}
                />
                <button type="submit" className="btn small primary">
                  Save
                </button>
              </form>
            ) : (
              <span className="stack tight" style={{ gap: 2 }}>
                <span style={kind === "category" ? { color: categoryColor(entry.name) } : undefined}>{entry.name}</span>
                <span className="tiny dim">
                  {plural(entry.count, "transaction")}
                  {entry.spending_class ? ` · ${entry.spending_class.toLowerCase()}` : ""}
                  {entry.default ? " · default" : ""}
                </span>
              </span>
            )}
            {entry.locked ? (
              <span className="tiny dim">built in</span>
            ) : (
              <span className="row" style={{ gap: 4 }}>
                {kind === "category" && renaming?.source !== entry.name ? (
                  <button
                    type="button"
                    className="btn ghost small"
                    onClick={() =>
                      void save(
                        { name: entry.name, source: entry.name, spending_class: entry.spending_class === "Fixed" ? "Personal" : "Fixed" },
                        `${entry.name} is now ${entry.spending_class === "Fixed" ? "personal" : "fixed"}.`,
                      )
                    }
                  >
                    {entry.spending_class === "Fixed" ? "Make personal" : "Make fixed"}
                  </button>
                ) : null}
                <button type="button" className="btn ghost small" onClick={() => setRenaming({ source: entry.name, value: entry.name })}>
                  Rename
                </button>
                {!entry.default ? (
                  <button type="button" className="btn ghost small" aria-label={`Remove ${entry.name}`} onClick={() => void remove(entry)}>
                    ×
                  </button>
                ) : null}
              </span>
            )}
          </div>
        ))}
      </div>
      {removing ? (
        <RemoveDialog kind={kind} name={removing} onClose={() => setRemoving(null)} onDone={() => setRemoving(null)} />
      ) : null}
    </Card>
  );
}

function KeywordRules({ rules, categories }: { rules: { keyword: string; category: string; source: string }[]; categories: string[] }) {
  const refresh = useRefresh();
  const toast = useToast();
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState("");
  const [filter, setFilter] = useState("");
  const shown = rules.filter((rule) => `${rule.keyword} ${rule.category}`.toLowerCase().includes(filter.trim().toLowerCase()));

  async function removeRule(word: string) {
    try {
      await post("/api/keyword-rules/delete", { keywords: [word] });
      await refresh();
      toast.show(`Removed the “${word}” rule.`);
    } catch (error) {
      toast.error(error);
    }
  }

  return (
    <Card title="Auto-category rules" hint="a word in the description picks the category">
      <form
        className="row"
        onSubmit={async (event) => {
          event.preventDefault();
          try {
            await post("/api/keyword-rules", { keyword: keyword.trim(), category });
            await refresh();
            toast.show(`“${keyword.trim()}” → ${category}.`);
            setKeyword("");
          } catch (error) {
            toast.error(error);
          }
        }}
      >
        <input className="input grow" style={{ width: "auto" }} placeholder="keyword or phrase, e.g. trader joe" value={keyword} onChange={(event) => setKeyword(event.target.value)} aria-label="Keyword" />
        <select className="input" style={{ width: 190 }} value={category} onChange={(event) => setCategory(event.target.value)} aria-label="Category">
          <option value="">Category…</option>
          {categories
            .filter((name) => name !== "Uncategorized")
            .map((name) => (
              <option key={name}>{name}</option>
            ))}
        </select>
        <button type="submit" className="btn" disabled={!keyword.trim() || !category}>
          Add rule
        </button>
      </form>
      {rules.length > 8 ? (
        <input className="input" placeholder="Filter rules" value={filter} onChange={(event) => setFilter(event.target.value)} aria-label="Filter rules" />
      ) : null}
      <div className="table-wrap" style={{ maxHeight: 380, overflowY: "auto" }}>
        <table className="table">
          <tbody>
            {shown.map((rule) => (
              <tr key={rule.keyword}>
                <td>“{rule.keyword}”</td>
                <td>
                  <span style={{ color: categoryColor(rule.category) }}>→ {rule.category}</span>
                </td>
                <td className="tiny dim">{rule.source}</td>
                <td style={{ width: 40 }}>
                  <button type="button" className="btn ghost small icon" aria-label={`Remove rule ${rule.keyword}`} onClick={() => void removeRule(rule.keyword)}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
            {!shown.length ? (
              <tr>
                <td className="muted">No rules{filter ? " match" : " yet"}.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export function Settings() {
  const choices = useChoices();
  const info = useQuery({ queryKey: ["settings"], queryFn: () => get<SettingsInfo>("/api/settings") });
  const data = choices.data;

  return (
    <div className="stack loose">
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Categories, rules and where everything is stored.</p>
        </div>
      </div>

      {data ? (
        <>
          <div className="spread">
            <ChoiceList kind="category" title="Categories" entries={data.category} />
            <KeywordRules rules={data.keyword_rules} categories={data.category.map((entry) => entry.name)} />
          </div>
          <div className="spread">
            <ChoiceList kind="account" title="Accounts" entries={data.account} />
            <ChoiceList kind="payment_method" title="Payment methods" entries={data.payment_method} />
          </div>
        </>
      ) : (
        <div className="card empty">Loading…</div>
      )}

      {info.data ? (
        <div className="spread">
          <Card title="Privacy" hint="everything stays on this computer">
            <div>
              {[
                { label: "Server answers only on", value: `${info.data.binding} (this computer)` },
                { label: "Database", value: info.data.database_path },
                {
                  label: "Personal config",
                  value: info.data.config_exists ? info.data.config_path : "not created (using defaults)",
                },
                { label: "Transactions stored", value: info.data.transaction_count.toLocaleString("en-US") },
              ].map((item) => (
                <div key={item.label} className="bill-row">
                  <Led color="#9FD39B" lit />
                  <span className="stack tight" style={{ gap: 2, minWidth: 0 }}>
                    <span className="tiny dim caps">{item.label}</span>
                    <span className="small" style={{ overflowWrap: "anywhere" }}>
                      {item.value}
                    </span>
                  </span>
                  <span />
                </div>
              ))}
            </div>
            <p className="tiny dim" style={{ margin: 0 }}>
              No analytics, no network calls. Other websites can't write here: every change needs a header browsers
              only send from this app.
            </p>
          </Card>
          <Card title="School calendar" hint="UCLA quarters used for weeks and terms">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Quarter</th>
                    <th>Classes start</th>
                    <th>Finals</th>
                  </tr>
                </thead>
                <tbody>
                  {info.data.school_calendar.quarters
                    .slice()
                    .reverse()
                    .map((quarter) => (
                      <tr key={quarter.name}>
                        <td>{quarter.name}</td>
                        <td className="small">
                          {weekday(quarter.instruction_begins)} {shortDate(quarter.instruction_begins)}
                        </td>
                        <td className="small">
                          {shortDate(quarter.finals_begin)} – {shortDate(quarter.quarter_ends)}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            <p className="tiny dim" style={{ margin: 0 }}>
              From the{" "}
              <a className="link" href={info.data.school_calendar.source} target="_blank" rel="noreferrer">
                UCLA Registrar
              </a>
              . Ten weeks of classes plus finals week; fall also has a Week 0.
            </p>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
