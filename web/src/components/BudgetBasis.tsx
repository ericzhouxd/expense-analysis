import { type ReactNode, useState } from "react";

import {
  type AutoBill,
  type BillSetting,
  type Budget,
  type BudgetChoices,
  type Cadence,
  type Fact,
  type FactKey,
  type FactValue,
  put,
} from "../api";
import { centsToInput, money, parseCents, shortDate, wholeMoney } from "../lib/format";
import { LED } from "../lib/glyphs";
import { useRefresh } from "../queries";
import { useToast } from "./feedback";
import { Led } from "./instrument";
import { DatePicker, MultiSelect, namesOf, Select } from "./pickers";
import { LineSource } from "./budgetBits";
import { Card, Fold, Info, Menu } from "./ui";

const CADENCE_TEXT: Record<Cadence, string> = {
  Monthly: "every month",
  "Each quarter": "each quarter",
  Once: "once",
};

function sentence(text: string): string {
  return text ? `${text[0]?.toUpperCase()}${text.slice(1)}` : text;
}

function setting(bill: BillSetting): BillSetting {
  const { name, amount_cents, categories, cadence, due_day, due, pinned, match } = bill;
  return { name, amount_cents, categories, cadence, due_day, due, pinned, match };
}

/** Everything the student has settled so far, ready to send back with one change. */
function choicesOf(budget: Budget): BudgetChoices {
  const chosen = <T extends FactValue>(key: FactKey): T | null => {
    const fact = budget.auto.facts.find((item) => item.key === key);
    return fact?.source === "yours" ? (fact.value as T) : null;
  };
  return {
    housing: chosen<string>("housing"),
    cohort: chosen<string>("cohort"),
    residency: chosen<boolean>("residency"),
    insurance: chosen<boolean>("insurance"),
    weekly_cents: budget.auto.weekly_cents,
    total_cents: budget.auto.total_cents,
    bills: budget.auto.bills.filter((bill) => !bill.key).map(setting),
    dismissed: budget.auto.dismissed_keys,
  };
}

function useSave(budget: Budget) {
  const refresh = useRefresh();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function save(change: Partial<BudgetChoices>, message: string): Promise<boolean> {
    setBusy(true);
    try {
      await put("/api/budget/settings", { ...choicesOf(budget), ...change });
      await refresh();
      toast.show(message);
      return true;
    } catch (error) {
      toast.error(error);
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { save, busy };
}

/** Lime is learned, blue is yours, amber earlier settings, gray a guess. */
const SOURCE_COLOR: Record<Fact["source"], string> = {
  learned: LED.accent,
  yours: LED.blue,
  earlier: LED.amber,
  default: LED.dim,
};

/** Where an answer came from, said only when it isn't simply learned. */
function Source({ source }: { source: Fact["source"] }) {
  if (source === "yours") return <span className="tag">Yours</span>;
  if (source === "earlier") return <span className="tag">Earlier settings</span>;
  if (source === "default") return <span className="tag">Assumed</span>;
  return null;
}

/** The lamp says where an answer came from; pressing it says why. */
function Lamp({ source, label, children }: { source: Fact["source"]; label: string; children?: ReactNode }) {
  const led = <Led color={SOURCE_COLOR[source]} lit={source !== "default"} />;
  return children ? (
    <Info label={label} lamp={led}>
      {children}
    </Info>
  ) : (
    led
  );
}

function Row({
  label,
  value,
  why,
  source = "learned",
  children,
}: {
  label: string;
  value: ReactNode;
  /** Shown when the lamp is pressed. */
  why?: ReactNode;
  source?: Fact["source"];
  children?: ReactNode;
}) {
  return (
    <div className="basis-row">
      <Lamp source={source} label={label}>
        {why}
      </Lamp>
      <div className="lines">
        <span className="label">{label}</span>
        <span className="row basis-value">
          {value}
          {/* Its control already shows what is yours. */}
          {source === "yours" ? null : <Source source={source} />}
        </span>
      </div>
      <div className="basis-control">{children}</div>
    </div>
  );
}

function FactRow({ budget, fact }: { budget: Budget; fact: Fact }) {
  const { save, busy } = useSave(budget);
  const differs = fact.source === "yours" && fact.auto_text !== fact.text && fact.auto_text !== "Unknown";
  return (
    <Row
      label={fact.label}
      value={
        fact.value === null ? (
          <span className="tag warn">Not set</span>
        ) : (
          <>
            {fact.text}
            {differs ? <span className="tag warn">Records: {fact.auto_text}</span> : null}
          </>
        )
      }
      source={fact.value === null ? "learned" : fact.source}
      why={fact.value === null ? undefined : sentence(differs ? fact.auto_why : fact.why)}
    >
      <Select
        look="small"
        aria-label={fact.label}
        disabled={busy}
        value={fact.source === "yours" ? String(fact.value) : ""}
        options={[
          { value: "", label: "Automatic" },
          ...fact.options.map((option) => ({ value: String(option.value), label: option.text, group: "Always" })),
        ]}
        onChange={(value) => {
          const option = fact.options.find((item) => String(item.value) === value);
          void save(
            { [fact.key]: option ? option.value : null },
            option ? `${fact.label}: ${option.text}.` : `${fact.label} is automatic again.`,
          );
        }}
      />
    </Row>
  );
}

/** A dollar amount that is automatic until one is typed. */
function AmountRow({
  budget,
  field,
  label,
  value,
  why,
}: {
  budget: Budget;
  field: "weekly_cents" | "total_cents";
  label: string;
  value: ReactNode;
  why: string;
}) {
  const { save, busy } = useSave(budget);
  const own = budget.auto[field];
  const [draft, setDraft] = useState<string | null>(null);
  const cents = draft?.trim() ? parseCents(draft) : null;
  return (
    <Row label={label} value={value} why={why} source={own ? "yours" : "learned"}>
      {draft === null ? (
        <>
          {own ? (
            <button
              type="button"
              className="btn ghost small"
              disabled={busy}
              onClick={() => void save({ [field]: null }, `${label} is automatic again.`)}
            >
              Use automatic
            </button>
          ) : null}
          <button type="button" className="btn small" onClick={() => setDraft(own ? centsToInput(own) : "")}>
            {own ? "Change" : "Set my own"}
          </button>
        </>
      ) : (
        <form
          className="row end"
          onSubmit={(event) => {
            event.preventDefault();
            if (!cents) return;
            void save({ [field]: cents }, `${label} set to ${money(cents)}.`).then((saved) => {
              if (saved) setDraft(null);
            });
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") setDraft(null);
          }}
        >
          <input
            className="input small"
            inputMode="decimal"
            placeholder="0.00"
            aria-label={label}
            aria-invalid={Boolean(draft.trim()) && !cents}
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button type="submit" className="btn primary small" disabled={busy || !cents}>
            Save
          </button>
          <button type="button" className="btn ghost small" onClick={() => setDraft(null)}>
            Cancel
          </button>
        </form>
      )}
    </Row>
  );
}

function WeeklyRow({ budget }: { budget: Budget }) {
  const line = budget.line;
  const school = money(line.school_weekly);
  const why = {
    own: `${line.school}: ${school}`,
    coa: `${line.school}: ${school}, lowered on Monday to keep the year under the cost of attendance`,
    school: `${line.school}: ${wholeMoney(line.school_yearly)} over ${line.school_weeks} weeks`,
  }[line.source];
  return (
    <AmountRow
      budget={budget}
      field="weekly_cents"
      label="Weekly line"
      value={
        <>
          {money(line.weekly)}
          <LineSource source={line.source} />
        </>
      }
      why={why}
    />
  );
}

function TotalRow({ budget }: { budget: Budget }) {
  const coa = budget.coa;
  if (!coa.ready) return null;
  return (
    <AmountRow
      budget={budget}
      field="total_cents"
      label="Cost of attendance"
      value={wholeMoney(coa.line)}
      why={
        coa.own_total
          ? "Your total from MyUCLA"
          : `${coa.school}'s published ${coa.year} total, checked ${shortDate(budget.line.verified_on)}`
      }
    />
  );
}

interface BillDraft {
  name: string;
  amount: string;
  cadence: Cadence;
  due_day: string;
  due: string;
  categories: string[];
  match: string;
}

const BLANK: BillDraft = {
  name: "",
  amount: "",
  cadence: "Monthly",
  due_day: "1",
  due: "",
  categories: [],
  match: "",
};

function draftOfBill(bill: AutoBill): BillDraft {
  return {
    name: bill.name,
    amount: centsToInput(bill.amount_cents),
    cadence: bill.cadence,
    due_day: String(bill.due_day),
    due: bill.due ?? "",
    categories: bill.categories,
    match: bill.match.join(" "),
  };
}

function BillForm({
  budget,
  start,
  busy,
  onSave,
  onCancel,
}: {
  budget: Budget;
  start: BillDraft;
  busy: boolean;
  onSave: (bill: BillSetting) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(start);
  const change = (part: Partial<BillDraft>) => setDraft((current) => ({ ...current, ...part }));
  const cents = parseCents(draft.amount);
  const valid = draft.name.trim() && cents !== null && draft.categories.length && (draft.cadence !== "Once" || draft.due);
  return (
    <form
      className="bill-form form-grid"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid || cents === null) return;
        onSave({
          name: draft.name.trim(),
          amount_cents: cents,
          categories: draft.categories,
          cadence: draft.cadence,
          due_day: Math.min(31, Math.max(1, Number(draft.due_day) || 1)),
          due: draft.cadence === "Once" ? draft.due : null,
          pinned: true,
          match: draft.match.split(/\s+/).filter(Boolean),
        });
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") onCancel();
      }}
    >
      <label className="field">
        <span>Name</span>
        <input autoFocus value={draft.name} onChange={(event) => change({ name: event.target.value })} />
      </label>
      <label className="field">
        <span>Amount</span>
        <input
          inputMode="decimal"
          value={draft.amount}
          aria-invalid={Boolean(draft.amount) && cents === null}
          onChange={(event) => change({ amount: event.target.value })}
        />
      </label>
      <Select
        label="How often"
        value={draft.cadence}
        options={budget.cadences.map((value) => ({ value, label: sentence(CADENCE_TEXT[value]) }))}
        onChange={(value) => change({ cadence: value as Cadence })}
      />
      {draft.cadence === "Monthly" ? (
        <label className="field">
          <span>Day of the month</span>
          <input
            inputMode="numeric"
            value={draft.due_day}
            aria-invalid={!/^([1-9]|[12]\d|3[01])$/.test(draft.due_day.trim())}
            onChange={(event) => change({ due_day: event.target.value })}
          />
        </label>
      ) : draft.cadence === "Once" ? (
        <DatePicker label="Due" value={draft.due} onChange={(value) => change({ due: value })} />
      ) : null}
      <MultiSelect
        label="Category"
        placeholder="Choose one or more"
        values={draft.categories}
        options={namesOf([...new Set([...budget.treatments.map((item) => item.category), ...draft.categories])], true)}
        onChange={(values) => change({ categories: values })}
      />
      <label className="field">
        <span>Only purchases named</span>
        <input placeholder="Any name" value={draft.match} onChange={(event) => change({ match: event.target.value })} />
      </label>
      <div className="row end wide">
        <button type="button" className="btn ghost small" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="btn primary small" disabled={busy || !valid}>
          Save bill
        </button>
      </div>
    </form>
  );
}

function billText(bill: AutoBill): string {
  const often = bill.yearly ? "every year" : CADENCE_TEXT[bill.cadence];
  return [sentence(often), bill.next_due ? shortDate(bill.next_due) : ""].filter(Boolean).join(" · ");
}

function BillRows({ budget }: { budget: Budget }) {
  const { save, busy } = useSave(budget);
  /** The bill being edited, by its place in the list; -1 is a new one. */
  const [open, setOpen] = useState<number | null>(null);
  const { bills, dismissed, dismissed_keys: ignored } = budget.auto;
  const own = bills.filter((bill) => !bill.key);

  async function keep(bill: BillSetting, replaces: AutoBill | null) {
    const rest = own.filter((item) => item !== replaces).map(setting);
    if (await save({ bills: [...rest, bill] }, `Saved ${bill.name}.`)) setOpen(null);
  }

  return (
    <Card
      id="bills"
      title="Bills"
      actions={
        <button type="button" className="btn small" onClick={() => setOpen(-1)} disabled={open === -1}>
          + Add a bill
        </button>
      }
    >
      {open === -1 ? (
        <BillForm
          budget={budget}
          start={BLANK}
          busy={busy}
          onSave={(value) => void keep(value, null)}
          onCancel={() => setOpen(null)}
        />
      ) : null}
      <div className="list">
        {bills.map((bill, index) =>
          open === index ? (
            <BillForm
              key={`${bill.key}${bill.name}`}
              budget={budget}
              start={draftOfBill(bill)}
              busy={busy}
              onSave={(value) => void keep(value, bill)}
              onCancel={() => setOpen(null)}
            />
          ) : (
            <div className="item bill-setting" key={`${bill.key}${bill.name}`}>
              <Lamp source={bill.key ? "learned" : bill.pinned ? "yours" : "earlier"} label={bill.name}>
                {bill.key ? sentence(bill.why) : null}
              </Lamp>
              <span className="lines">
                <span className="row">
                  <span className="title">{bill.name}</span>
                  {bill.key ? null : <Source source={bill.pinned ? "yours" : "earlier"} />}
                </span>
                <span className="meta">
                  {billText(bill)} · {bill.categories.join(", ")}
                </span>
              </span>
              <span className="num">{money(bill.amount_cents)}</span>
              <Menu
                label={`Actions for ${bill.name}`}
                items={[
                  { label: "Edit", icon: "pencil", run: () => setOpen(index) },
                  {
                    label: bill.key ? "Not a bill" : "Remove",
                    icon: "close",
                    danger: !bill.key,
                    run: () =>
                      void save(
                        bill.key
                          ? { dismissed: [...ignored, bill.key] }
                          : { bills: own.filter((item) => item !== bill).map(setting) },
                        bill.key ? `${bill.name} is no longer a bill.` : `Removed ${bill.name}.`,
                      ),
                  },
                ]}
              />
            </div>
          ),
        )}
        {!bills.length && open === null ? (
          <p className="muted">No bills yet</p>
        ) : null}
      </div>
      {dismissed.length ? (
        <Fold title={`${dismissed.length} set aside`}>
          <div className="list">
            {dismissed.map((bill) => (
              <div className="item plain-item" key={bill.key}>
                <span className="muted">
                  {bill.name} <span className="dim">{money(bill.amount_cents)}</span>
                </span>
                <button
                  type="button"
                  className="btn ghost small"
                  disabled={busy}
                  onClick={() =>
                    void save({ dismissed: ignored.filter((key) => key !== bill.key) }, `${bill.name} is a bill again.`)
                  }
                >
                  Bring back
                </button>
              </div>
            ))}
          </div>
        </Fold>
      ) : null}
    </Card>
  );
}

/** What the app worked out by itself, with the reason behind its lamp and a way to overrule it. */
export function BudgetSetup({ budget }: { budget: Budget }) {
  return (
    <>
      <Card
        id="basis"
        title="Basis"
        actions={
          <a className="link small" href={budget.line.source_url} target="_blank" rel="noreferrer">
            {budget.line.school} figures ↗
          </a>
        }
      >
        <div className="list">
          {budget.auto.facts.map((fact) => (
            <FactRow key={fact.key} budget={budget} fact={fact} />
          ))}
          <TotalRow budget={budget} />
          <WeeklyRow budget={budget} />
        </div>
      </Card>
      <BillRows budget={budget} />
    </>
  );
}
