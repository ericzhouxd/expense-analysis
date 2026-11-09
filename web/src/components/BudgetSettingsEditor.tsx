import { useState } from "react";

import { type BillSetting, type Budget, type Cadence, put } from "../api";
import { centsToInput, money, parseCents } from "../lib/format";
import { useRefresh } from "../queries";
import { useToast } from "./feedback";
import { Card, Segmented } from "./instrument";

interface BillDraft {
  key: number;
  name: string;
  amount: string;
  categories: string;
  cadence: Cadence;
  due_day: string;
  due: string;
}

const CADENCE_TEXT: Record<Cadence, string> = {
  Monthly: "Every month",
  "Each quarter": "Each quarter",
  Once: "Once",
};

const STARTERS: { name: string; categories: string; cadence: Cadence }[] = [
  { name: "Rent", categories: "Rent", cadence: "Monthly" },
  { name: "Phone", categories: "Cell Phone", cadence: "Monthly" },
  { name: "Utilities", categories: "Utilities", cadence: "Monthly" },
  { name: "Tuition & fees", categories: "Tuition, School Fees", cadence: "Each quarter" },
];

let nextKey = 1;

function toDraft(bill: BillSetting): BillDraft {
  return {
    key: nextKey++,
    name: bill.name,
    amount: centsToInput(bill.amount_cents),
    categories: bill.categories.join(", "),
    cadence: bill.cadence,
    due_day: String(bill.due_day),
    due: bill.due ?? "",
  };
}

export function BudgetSettingsEditor({ budget, onDone }: { budget: Budget; onDone: () => void }) {
  const refresh = useRefresh();
  const toast = useToast();
  const line = budget.line;
  const [housing, setHousing] = useState(budget.settings.housing);
  const [mode, setMode] = useState<"school" | "own">(budget.settings.weekly_cents ? "own" : "school");
  const [own, setOwn] = useState(
    budget.settings.weekly_cents ? centsToInput(budget.settings.weekly_cents) : centsToInput(line.school_weekly),
  );
  const [bills, setBills] = useState<BillDraft[]>(() => budget.settings.bills.map(toDraft));
  const [busy, setBusy] = useState(false);

  const ownCents = parseCents(own);
  const amounts = bills.map((bill) => parseCents(bill.amount));
  const invalid =
    (mode === "own" && !ownCents) ||
    amounts.some((amount) => amount === null) ||
    bills.some((bill) => !bill.name.trim() || (bill.cadence === "Once" && !bill.due));
  const usedStarters = new Set(bills.map((bill) => bill.name));
  const estimate = budget.housing_estimates[housing];

  function update(key: number, change: Partial<BillDraft>) {
    setBills((items) => items.map((item) => (item.key === key ? { ...item, ...change } : item)));
  }

  async function save() {
    setBusy(true);
    try {
      await put("/api/budget/settings", {
        housing,
        weekly_cents: mode === "own" ? ownCents : null,
        bills: bills.map((bill, index) => ({
          name: bill.name.trim(),
          amount_cents: amounts[index] ?? 0,
          categories: bill.categories
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
          cadence: bill.cadence,
          due_day: Math.min(31, Math.max(1, Number(bill.due_day) || 1)),
          due: bill.cadence === "Once" ? bill.due : null,
        })),
      });
      await refresh();
      toast.show("Budget saved.");
      onDone();
    } catch (error) {
      toast.error(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack loose">
      <Card title="1 · Your weekly line" hint="what one ordinary week should cost">
        <div className="stack tight">
          <span className="label">Where do you live this year?</span>
          <Segmented
            label="Housing"
            value={housing}
            onChange={setHousing}
            options={budget.housing_options.map((value) => ({ value, label: value }))}
          />
        </div>
        <div className="stack tight">
          <span className="label">Which line should each week use?</span>
          <Segmented<"school" | "own">
            label="Weekly line"
            value={mode}
            onChange={setMode}
            options={[
              { value: "school", label: `${line.school}'s estimate` },
              { value: "own", label: "My own amount" },
            ]}
          />
        </div>
        {mode === "own" ? (
          <label className="field" style={{ maxWidth: 220 }}>
            <span>Per week</span>
            <input inputMode="decimal" value={own} aria-invalid={!ownCents} onChange={(event) => setOwn(event.target.value)} />
          </label>
        ) : null}
        <p className="muted small" style={{ margin: 0 }}>
          {estimate
            ? `${line.school} expects ${money(estimate.school_yearly)} for food, transportation and personal costs for
          ${housing.toLowerCase()} students over the ${line.year} school year (${line.school_weeks} weeks), about
          ${money(estimate.school_weekly)} a week.`
            : null}{" "}
          It stays on the Budget page as a reference line either way.
        </p>
      </Card>

      <Card title="2 · Bills" hint="fixed costs on a schedule, kept outside the weekly line">
        {bills.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Amount</th>
                  <th>How often</th>
                  <th>Due</th>
                  <th>Paid as category</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {bills.map((bill, index) => (
                  <tr key={bill.key}>
                    <td style={{ minWidth: 130 }}>
                      <input className="input" aria-label="Bill name" value={bill.name} onChange={(event) => update(bill.key, { name: event.target.value })} />
                    </td>
                    <td style={{ minWidth: 100 }}>
                      <input
                        className="input"
                        aria-label={`${bill.name} amount`}
                        inputMode="decimal"
                        value={bill.amount}
                        aria-invalid={amounts[index] === null}
                        onChange={(event) => update(bill.key, { amount: event.target.value })}
                      />
                    </td>
                    <td>
                      <select
                        className="input"
                        aria-label={`${bill.name} how often`}
                        value={bill.cadence}
                        onChange={(event) => update(bill.key, { cadence: event.target.value as Cadence })}
                      >
                        {budget.cadences.map((value) => (
                          <option key={value} value={value}>
                            {CADENCE_TEXT[value]}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td style={{ minWidth: 130 }}>
                      {bill.cadence === "Monthly" ? (
                        <input
                          className="input"
                          aria-label={`${bill.name} day of the month`}
                          type="number"
                          min={1}
                          max={31}
                          value={bill.due_day}
                          onChange={(event) => update(bill.key, { due_day: event.target.value })}
                        />
                      ) : bill.cadence === "Once" ? (
                        <input
                          className="input"
                          type="date"
                          aria-label={`${bill.name} due date`}
                          aria-invalid={!bill.due}
                          value={bill.due}
                          onChange={(event) => update(bill.key, { due: event.target.value })}
                        />
                      ) : (
                        <span className="small dim">first day of each quarter</span>
                      )}
                    </td>
                    <td style={{ minWidth: 150 }}>
                      <input
                        className="input"
                        aria-label={`${bill.name} categories`}
                        placeholder="Rent"
                        value={bill.categories}
                        onChange={(event) => update(bill.key, { categories: event.target.value })}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn ghost small icon"
                        aria-label={`Remove ${bill.name || "bill"}`}
                        onClick={() => setBills((items) => items.filter((item) => item.key !== bill.key))}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted small" style={{ margin: 0 }}>
            No bills yet. Rent, phone and tuition are the usual ones.
          </p>
        )}
        <div className="row">
          {STARTERS.filter((starter) => !usedStarters.has(starter.name)).map((starter) => (
            <button
              key={starter.name}
              type="button"
              className="btn small"
              onClick={() =>
                setBills((items) => [
                  ...items,
                  { key: nextKey++, name: starter.name, amount: "", categories: starter.categories, cadence: starter.cadence, due_day: "1", due: "" },
                ])
              }
            >
              + {starter.name}
            </button>
          ))}
          <button
            type="button"
            className="btn small ghost"
            onClick={() =>
              setBills((items) => [
                ...items,
                { key: nextKey++, name: "", amount: "", categories: "", cadence: "Monthly", due_day: "1", due: "" },
              ])
            }
          >
            + Other bill
          </button>
        </div>
        <p className="tiny dim" style={{ margin: 0 }}>
          A bill shows as paid once purchases in its category add up to the amount around its due date. Those
          purchases count as bills, not as everyday spending.
        </p>
      </Card>

      <div className="row end">
        <button type="button" className="btn ghost" onClick={onDone}>
          Cancel
        </button>
        <button type="button" className="btn primary" disabled={busy || invalid} onClick={() => void save()}>
          Save
        </button>
      </div>
    </div>
  );
}
