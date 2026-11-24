import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  type Budget,
  type ChoiceEntry,
  type ChoiceKind,
  type Choices,
  type EntryDefaults,
  get,
  post,
  put,
  type SettingsInfo,
} from "../api";
import { treatmentLabel } from "../components/budgetBits";
import { RemoveDialog } from "../components/ChoiceCombo";
import { useToast } from "../components/feedback";
import { Icon } from "../components/icons";
import { ImportCsv } from "../components/ImportCsv";
import { Glyph } from "../components/instrument";
import { namesOf, Select, typeOptions } from "../components/pickers";
import { Card, Fold, Loading, LoadError, Menu, PageHead, Tabs } from "../components/ui";
import { plural, shortDate, weekday, wholeMoney } from "../lib/format";
import { categoryColor } from "../lib/glyphs";
import { useChoices, useRefresh } from "../queries";
import { linkTo, SETTINGS_TABS, transactionsUrl, useLocation } from "../router";

const NOUNS: Record<ChoiceKind, string> = {
  category: "category",
  account: "account",
  payment_method: "payment method",
};

/** Adding, renaming and removing the choices of one kind. */
function useChoiceActions(kind: ChoiceKind) {
  const refresh = useRefresh();
  const toast = useToast();

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
    try {
      const result = await post<{ undo: { name: string; spending_class: string | null } | null }>(
        `/api/choices/${kind}/delete`,
        { source: entry.name },
      );
      await refresh();
      toast.show(`Removed “${entry.name}”.`, {
        actions: [
          result.undo
            ? {
                label: "Undo",
                run: async () => {
                  await post(`/api/choices/${kind}/restore`, result.undo);
                  await refresh();
                },
              }
            : null,
        ],
      });
    } catch (error) {
      toast.error(error);
    }
  }

  return { save, remove };
}

const DEFAULT_LABELS: Record<keyof EntryDefaults, string> = {
  category: "If no match",
  payment_method: "Paid with",
  account: "Account",
  transaction_type: "Type",
};

/** Changing what new entries start with. */
function useSetDefault() {
  const refresh = useRefresh();
  const toast = useToast();

  return async function set(kind: keyof EntryDefaults, value: string) {
    try {
      const { previous } = await put<{ previous: string }>(`/api/defaults/${kind}`, { value });
      await refresh();
      if (previous === value) return;
      toast.show(`Default ${kind === "transaction_type" ? "type" : NOUNS[kind]}: ${value}.`, {
        actions: [
          {
            label: "Undo",
            run: async () => {
              await put(`/api/defaults/${kind}`, { value: previous });
              await refresh();
            },
          },
        ],
      });
    } catch (error) {
      toast.error(error);
    }
  };
}

/** The same cells as Quick Add, holding what it starts with. */
function Defaults({ choices }: { choices: Choices }) {
  const set = useSetDefault();
  const options: Record<keyof EntryDefaults, ReturnType<typeof namesOf>> = {
    category: namesOf(
      choices.category.map((entry) => entry.name),
      true,
    ),
    payment_method: namesOf(choices.payment_method.map((entry) => entry.name)),
    account: namesOf(choices.account.map((entry) => entry.name)),
    transaction_type: typeOptions(choices.transaction_types),
  };
  return (
    <Card title="New entry defaults">
      <div className="fields">
        {(Object.keys(DEFAULT_LABELS) as (keyof EntryDefaults)[]).map((kind) => (
          <Select
            key={kind}
            look="cell"
            label={DEFAULT_LABELS[kind]}
            value={choices.defaults[kind]}
            options={options[kind]}
            onChange={(value) => void set(kind, value)}
          />
        ))}
      </div>
    </Card>
  );
}

/** A choice's name, turning into a field while it is being renamed. */
function Rename({ entry, onSave, onCancel }: { entry: ChoiceEntry; onSave: (name: string) => Promise<boolean>; onCancel: () => void }) {
  const [value, setValue] = useState(entry.name);
  return (
    <form
      className="row rename"
      onSubmit={(event) => {
        event.preventDefault();
        const name = value.trim();
        if (!name || name === entry.name) onCancel();
        else
          void onSave(name).then((saved) => {
            if (saved) onCancel();
          });
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") onCancel();
      }}
    >
      <input
        className="input"
        autoFocus
        aria-label={`Rename ${entry.name}`}
        value={value}
        onFocus={(event) => event.target.select()}
        onChange={(event) => setValue(event.target.value)}
      />
      <button type="submit" className="btn small primary">
        Save
      </button>
      <button type="button" className="btn small ghost" onClick={onCancel}>
        Cancel
      </button>
    </form>
  );
}

function AddName({ kind, onAdd }: { kind: ChoiceKind; onAdd: (name: string) => Promise<boolean> }) {
  const [name, setName] = useState("");
  return (
    <form
      className="row add-row"
      onSubmit={(event) => {
        event.preventDefault();
        const value = name.trim();
        if (value)
          void onAdd(value).then((saved) => {
            if (saved) setName("");
          });
      }}
    >
      <input
        className="input"
        placeholder={`New ${NOUNS[kind]}`}
        aria-label={`New ${NOUNS[kind]}`}
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <button type="submit" className="btn" disabled={!name.trim()}>
        Add
      </button>
    </form>
  );
}

function Count({ entry, filter }: { entry: ChoiceEntry; filter: Record<string, string> | null }) {
  if (!entry.count) return <>Unused</>;
  const text = plural(entry.count, "transaction");
  return filter ? (
    <a className="plain" {...linkTo(transactionsUrl(filter))}>
      {text}
    </a>
  ) : (
    <>{text}</>
  );
}

/** Categories in use, with how each counts; the rest fold away. A change saves at once. */
function Categories({ choices, budget }: { choices: Choices; budget: Budget | undefined }) {
  const { save, remove } = useChoiceActions("category");
  const refresh = useRefresh();
  const toast = useToast();
  const [renaming, setRenaming] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const treatments = budget?.treatments ?? [];
  const inUse = (entry: ChoiceEntry) => entry.count > 0 || treatments.some((item) => item.category === entry.name);
  const used = choices.category.filter(inUse);
  const unused = choices.category.filter((entry) => !inUse(entry));

  async function count(category: string, change: { treatment?: string; part?: string }, message: string) {
    const categories = Object.fromEntries(
      treatments.filter((item) => item.pinned).map((item) => [item.category, item.treatment]),
    );
    const parts = Object.fromEntries(
      treatments.filter((item) => item.part_pinned).map((item) => [item.category, item.part]),
    );
    if (change.treatment === "") delete categories[category];
    else if (change.treatment) categories[category] = change.treatment;
    if (change.part === "") delete parts[category];
    else if (change.part) parts[category] = change.part;
    try {
      await put("/api/spending-rules/categories", { categories, parts });
      await refresh();
      toast.show(message);
    } catch (error) {
      toast.error(error);
    }
  }

  const name = (entry: ChoiceEntry) =>
    renaming === entry.name ? (
      <Rename
        entry={entry}
        onCancel={() => setRenaming(null)}
        onSave={(name) =>
          save(
            { name, source: entry.name, spending_class: entry.spending_class ?? "Personal" },
            `Renamed to “${name}”; ${plural(entry.count, "transaction")} updated.`,
          )
        }
      />
    ) : (
      <span className="choice-name">
        <Glyph category={entry.name} />
        <span className="lines">
          <span>
            {entry.name}
            {entry.spending_class === "Fixed" ? <span className="tag">Fixed</span> : null}
            {entry.default && !entry.locked ? <span className="tag">Default</span> : null}
          </span>
          <span className="small dim">
            <Count entry={entry} filter={{ category: entry.name }} />
          </span>
        </span>
      </span>
    );

  const menu = (entry: ChoiceEntry) =>
    entry.locked || renaming === entry.name ? null : (
      <Menu
        label={`Actions for ${entry.name}`}
        items={[
          { label: "Rename", icon: "pencil", run: () => setRenaming(entry.name) },
          {
            label: entry.spending_class === "Fixed" ? "Make personal" : "Make fixed",
            icon: "swap",
            run: () =>
              void save(
                {
                  name: entry.name,
                  source: entry.name,
                  spending_class: entry.spending_class === "Fixed" ? "Personal" : "Fixed",
                },
                `${entry.name} is now ${entry.spending_class === "Fixed" ? "personal" : "fixed"}.`,
              ),
          },
          ...(entry.default
            ? []
            : [
                {
                  label: "Remove",
                  icon: "close" as const,
                  danger: true,
                  run: () => (entry.unused ? void remove(entry) : setRemoving(entry.name)),
                },
              ]),
        ]}
      />
    );

  return (
    <Card title="Categories" hint={budget ? `Big stuff ≥ ${wholeMoney(budget.auto.big_cents)}` : undefined}>
      <AddName
        kind="category"
        onAdd={(name) => save({ name, spending_class: "Personal", keyword: "" }, `Added “${name}”.`)}
      />
      {used.length ? (
        <div className="table-wrap open">
          <table className="table category-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Counts as</th>
                <th>Cost of attendance</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {used.map((entry) => {
                const rule = treatments.find((item) => item.category === entry.name);
                return (
                  <tr key={entry.name}>
                    <td>
                      {name(entry)}
                    </td>
                    <td>
                      {rule && budget ? (
                        <span title={rule.why}>
                          <Select
                            look="small"
                            className={rule.pinned ? "" : "automatic"}
                            aria-label={`${entry.name} counts as`}
                            value={rule.pinned ? rule.treatment : ""}
                            options={[
                              {
                                value: "",
                                label: rule.pinned ? "Decide for me" : treatmentLabel(rule.treatment),
                                group: "Automatic",
                              },
                              ...budget.treatment_options.map((option) => ({
                                value: option,
                                label: treatmentLabel(option),
                                group: "Always",
                              })),
                            ]}
                            onChange={(value) =>
                              void count(
                                entry.name,
                                { treatment: value },
                                value
                                  ? `${entry.name} counts as ${treatmentLabel(value).toLowerCase()}.`
                                  : `${entry.name} is sorted automatically again.`,
                              )
                            }
                          />
                        </span>
                      ) : null}
                    </td>
                    <td>
                      {rule && budget ? (
                        <Select
                          look="small"
                          className={rule.part_pinned ? "" : "automatic"}
                          aria-label={`${entry.name} cost of attendance part`}
                          value={rule.part_pinned ? rule.part : ""}
                          options={[
                            { value: "", label: rule.part_pinned ? "Decide for me" : rule.part, group: "Automatic" },
                            ...budget.coa_parts.map((option) => ({ value: option, label: option, group: "Always" })),
                          ]}
                          onChange={(value) =>
                            void count(
                              entry.name,
                              { part: value },
                              value ? `${entry.name} lands in ${value}.` : `${entry.name}'s part is automatic again.`,
                            )
                          }
                        />
                      ) : null}
                    </td>
                    <td className="num">
                      {menu(entry)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {unused.length ? (
        <Fold title={`${unused.length} unused`} open={!used.length}>
          <div className="list">
            {unused.map((entry) => (
              <div key={entry.name} className="item plain-item">
                {name(entry)}
                {menu(entry)}
              </div>
            ))}
          </div>
        </Fold>
      ) : null}
      {removing ? (
        <RemoveDialog
          kind="category"
          name={removing}
          onClose={() => setRemoving(null)}
          onDone={() => setRemoving(null)}
        />
      ) : null}
    </Card>
  );
}

function KeywordRules({ choices }: { choices: Choices }) {
  const refresh = useRefresh();
  const toast = useToast();
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState("");
  const [filter, setFilter] = useState("");
  const rules = choices.keyword_rules;
  const needle = filter.trim().toLowerCase();
  const shown = rules.filter((rule) => `${rule.keyword} ${rule.category}`.toLowerCase().includes(needle));

  async function remove(word: string) {
    try {
      await post("/api/keyword-rules/delete", { keywords: [word] });
      await refresh();
      toast.show(`Removed the “${word}” rule.`);
    } catch (error) {
      toast.error(error);
    }
  }

  return (
    <Card title="Auto-category rules" hint={rules.length ? plural(rules.length, "rule") : undefined}>
      <form
        className="row add-row"
        onSubmit={async (event) => {
          event.preventDefault();
          const word = keyword.trim();
          try {
            await post("/api/keyword-rules", { keyword: word, category });
            await refresh();
            toast.show(`Entries with “${word}” go to ${category}.`);
            setKeyword("");
          } catch (error) {
            toast.error(error);
          }
        }}
      >
        <input
          className="input"
          placeholder="Word or phrase, e.g. trader joe"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          aria-label="Keyword"
        />
        <Select
          aria-label="Category"
          placeholder="Category"
          value={category}
          options={namesOf(
            choices.category.map((entry) => entry.name).filter((name) => name !== "Uncategorized"),
            true,
          )}
          onChange={setCategory}
        />
        <button type="submit" className="btn" disabled={!keyword.trim() || !category}>
          Add
        </button>
      </form>
      {rules.length ? (
        <Fold title="Show rules" open={rules.length <= 8}>
          {rules.length > 8 ? (
            <input
              className="input"
              placeholder="Filter rules"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              aria-label="Filter rules"
            />
          ) : null}
          <div className="rules">
            {shown.map((rule) => (
              <div className="rule-row" key={rule.keyword}>
                <Glyph category={rule.category} small />
                <span className="truncate">{rule.keyword}</span>
                <Icon name="arrow" />
                <span className="truncate" style={{ color: categoryColor(rule.category) }}>{rule.category}</span>
                <button
                  type="button"
                  className="btn ghost small icon"
                  aria-label={`Remove rule ${rule.keyword}`}
                  onClick={() => void remove(rule.keyword)}
                >
                  <Icon name="close" size={8} />
                </button>
              </div>
            ))}
            {!shown.length ? <p className="muted small">No rules match.</p> : null}
          </div>
        </Fold>
      ) : (
        <p className="muted small">No rules yet</p>
      )}
    </Card>
  );
}

function ChoiceList({ kind, title, entries }: { kind: "account" | "payment_method"; title: string; entries: ChoiceEntry[] }) {
  const { save, remove } = useChoiceActions(kind);
  const setDefault = useSetDefault();
  const [renaming, setRenaming] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  return (
    <Card title={title}>
      <AddName kind={kind} onAdd={(name) => save({ name }, `Added “${name}”.`)} />
      <div className="list">
        {entries.map((entry) => (
          <div key={entry.name} className="item plain-item">
            {renaming === entry.name ? (
              <Rename
                entry={entry}
                onCancel={() => setRenaming(null)}
                onSave={(name) =>
                  save(
                    { name, source: entry.name },
                    `Renamed to “${name}”; ${plural(entry.count, "transaction")} updated.`,
                  )
                }
              />
            ) : (
              <>
                <span className="lines">
                  <span className="title">
                    {entry.name}
                    {entry.default ? <span className="tag">Default</span> : null}
                  </span>
                  <span className="meta">
                    <Count entry={entry} filter={kind === "account" ? { account: entry.name } : null} />
                  </span>
                </span>
                {entry.locked ? null : (
                  <Menu
                    label={`Actions for ${entry.name}`}
                    items={[
                      { label: "Rename", icon: "pencil", run: () => setRenaming(entry.name) },
                      ...(entry.default
                        ? []
                        : [
                            {
                              label: "Make default",
                              icon: "check" as const,
                              run: () => void setDefault(kind, entry.name),
                            },
                            {
                              label: "Remove",
                              icon: "close" as const,
                              danger: true,
                              run: () => (entry.unused ? void remove(entry) : setRemoving(entry.name)),
                            },
                          ]),
                    ]}
                  />
                )}
              </>
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

function Data({ info }: { info: SettingsInfo | undefined }) {
  return (
    <>
      <ImportCsv />
      <Card title="Export" hint={info ? plural(info.transaction_count, "transaction") : undefined}>
        <div className="row">
          <a className="btn" href="/api/export.csv" download aria-disabled={info ? !info.transaction_count : undefined}>
            <Icon name="download" />
            Download CSV
          </a>
        </div>
      </Card>
    </>
  );
}

const SHORTCUTS: [string[], string][] = [
  [["⌘K"], "Add or find"],
  [["1–5"], "Go to a page"],
  [["/"], "Search transactions"],
  [["↑", "↓"], "Move through transactions"],
  [["Enter"], "Edit a transaction"],
  [["Space"], "Select it"],
  [["Delete"], "Delete it, or the selection"],
  [["Esc"], "Close or clear"],
];

function AppTab({ info }: { info: SettingsInfo | undefined }) {
  return (
    <>
      <Card title="Keyboard">
        <dl className="shortcuts">
          {SHORTCUTS.map(([keys, what]) => (
            <div key={what}>
              <dt>
                {keys.map((key) => (
                  <kbd key={key}>{key}</kbd>
                ))}
              </dt>
              <dd>{what}</dd>
            </div>
          ))}
        </dl>
      </Card>
      {info ? (
        <>
          <Card title="Privacy">
            <dl className="facts">
              {[
                ["Answers on", `${info.binding} only`],
                ["Sends", "Nothing"],
                ["Database", info.database_path],
                ["Config", info.config_exists ? info.config_path : "None"],
                ["Transactions", info.transaction_count.toLocaleString("en-US")],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </Card>
          <Card
            title="School calendar"
            actions={
              <a className="link small" href={info.school_calendar.source} target="_blank" rel="noreferrer">
                UCLA Registrar
              </a>
            }
          >
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
                  {info.school_calendar.quarters
                    .slice()
                    .reverse()
                    .map((quarter) => (
                      <tr key={quarter.name}>
                        <td>{quarter.name}</td>
                        <td>
                          {weekday(quarter.instruction_begins)} {shortDate(quarter.instruction_begins)}
                        </td>
                        <td>
                          {shortDate(quarter.finals_begin)} – {shortDate(quarter.quarter_ends)}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      ) : null}
    </>
  );
}

export function Settings() {
  const { path } = useLocation();
  const choices = useChoices();
  const info = useQuery({ queryKey: ["settings"], queryFn: () => get<SettingsInfo>("/api/settings") });
  const budget = useQuery({
    queryKey: ["budget", ""],
    queryFn: () => get<Budget>("/api/budget"),
    enabled: path === "/settings",
  });

  function tab() {
    if (path === "/settings/data") return <Data info={info.data} />;
    if (path === "/settings/app") return <AppTab info={info.data} />;
    if (!choices.data) {
      return choices.isError ? (
        <LoadError what="settings" error={choices.error} retry={() => void choices.refetch()} />
      ) : (
        <Loading />
      );
    }
    if (path === "/settings/accounts") {
      return (
        <>
          <Defaults choices={choices.data} />
          <div className="spread">
            <ChoiceList kind="account" title="Accounts" entries={choices.data.account} />
            <ChoiceList kind="payment_method" title="Payment methods" entries={choices.data.payment_method} />
          </div>
        </>
      );
    }
    return (
      <>
        <Categories choices={choices.data} budget={budget.data} />
        <KeywordRules choices={choices.data} />
      </>
    );
  }

  return (
    <>
      <PageHead title="Settings" tabs={<Tabs label="Settings" items={SETTINGS_TABS} current={path} />} />
      {tab()}
    </>
  );
}
