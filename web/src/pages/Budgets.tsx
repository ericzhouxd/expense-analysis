import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { type Budget, get, put } from "../api";
import { linkTo, openQuickAdd } from "../App";
import { BudgetSettingsEditor } from "../components/BudgetSettingsEditor";
import { BillList, treatmentLabel, WeekBars } from "../components/budgetBits";
import { useToast } from "../components/feedback";
import {
  Card,
  Collapsible,
  Empty,
  HeroNumber,
  Housing,
  PaceMeter,
  Readout,
  Stepper,
} from "../components/instrument";
import { dayLabel, money, plural, rangeLabel, shortDate } from "../lib/format";
import { useRefresh } from "../queries";
import { navigate, useLocation } from "../router";

function TreatmentEditor({ budget }: { budget: Budget }) {
  const refresh = useRefresh();
  const toast = useToast();
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    setValues(Object.fromEntries(budget.treatments.map((item) => [item.category, item.treatment])));
  }, [budget.treatments]);
  const changed = budget.treatments.some((item) => values[item.category] !== item.treatment);

  async function save() {
    try {
      await put("/api/spending-rules/categories", { categories: values });
      await refresh();
      toast.show("Saved how categories count.");
    } catch (error) {
      toast.error(error);
    }
  }

  return (
    <Collapsible
      id="treatments"
      title="How categories count"
      hint="everyday, bills or big stuff"
      open={typeof window !== "undefined" && window.location.hash === "#treatments"}
    >
      <p className="muted small" style={{ margin: 0 }}>
        Everyday spending counts against the weekly line. Bills and big stuff are tracked beside it, so a $600
        flight home doesn't wreck one week.
      </p>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Category</th>
              <th>Counts as</th>
            </tr>
          </thead>
          <tbody>
            {budget.treatments.map((item) => (
              <tr key={item.category}>
                <td>
                  {item.category}
                  {!item.saved ? <span className="tiny dim"> · default</span> : null}
                </td>
                <td style={{ width: 220 }}>
                  <select
                    className="input"
                    aria-label={`${item.category} counts as`}
                    value={values[item.category] ?? item.treatment}
                    onChange={(event) => setValues((current) => ({ ...current, [item.category]: event.target.value }))}
                  >
                    {budget.treatment_options.map((option) => (
                      <option key={option} value={option}>
                        {treatmentLabel(option)}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row end">
        <button type="button" className="btn primary" disabled={!changed} onClick={() => void save()}>
          Save
        </button>
      </div>
    </Collapsible>
  );
}

function WeekPanel({ budget }: { budget: Budget }) {
  const week = budget.week;
  const totals = budget.totals;
  const line = budget.line;
  if (!week) {
    const saved = totals.saved;
    return (
      <Housing label="Term panel">
        <div className="row between">
          <span className="led-label">
            <span className="led-dot" aria-hidden="true" />
            {saved >= 0 ? "SAVED THIS TERM" : "OVER THE LINE THIS TERM"}
          </span>
          <span className="tiny dim caps">{rangeLabel(budget.period.start, budget.period.end)}</span>
        </div>
        <HeroNumber value={money(Math.abs(saved))} tone={saved >= 0 ? "accent" : "over"} />
        <div className="muted small" style={{ marginTop: -10 }}>
          {totals.weeks_done
            ? `${money(totals.everyday)} of everyday spending against ${money(totals.line_to_date)} of weekly lines`
            : "This period hasn't started yet."}
        </div>
        <div className="readouts" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
          <Readout label="Weeks" value={String(budget.weeks.length)} tone="text" />
          <Readout label="Everyday" value={money(totals.everyday)} tone="coral" />
          <Readout label="Bills" value={money(totals.bills)} tone="text" />
          <Readout label="Big stuff" value={money(totals.big_stuff)} tone="text" />
        </div>
      </Housing>
    );
  }
  const over = week.left < 0;
  const gap = week.spent - week.pace;
  return (
    <Housing label="This week panel">
      <div className="row between">
        <span className="led-label">
          <span className="led-dot pulse" aria-hidden="true" />
          {over ? `OVER THE LINE · ${week.label.toUpperCase()}` : `LEFT THIS WEEK · ${week.label.toUpperCase()}`}
        </span>
        <span className="tiny dim caps">
          {rangeLabel(week.start, week.end)} · resets monday
        </span>
      </div>
      <HeroNumber value={money(Math.abs(week.left))} tone={over ? "over" : "accent"} />
      <div className="muted small" style={{ marginTop: -10 }}>
        {over
          ? `${money(week.spent)} spent against a ${money(week.line)} line. Next week starts fresh.`
          : `about ${money(week.per_day)} a day for ${plural(week.days_left, "day")} · whatever's left gets saved`}
      </div>
      <div className="readouts" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        <Readout
          label="Weekly line"
          value={money(week.line)}
          tone="text"
          sub={line.source === "school" ? `${line.school} estimate` : `yours · ${line.school} says ${money(line.school_weekly)}`}
        />
        <Readout label="Spent this week" value={money(week.spent)} tone="coral" />
        <Readout
          label="Vs pace"
          value={money(gap, { signed: true })}
          tone={gap > 0 ? "coral" : "sage"}
          sub={gap > 0 ? "ahead of an even week" : "under an even week"}
        />
        <Readout
          label="Saved this term"
          value={money(totals.saved, { signed: true })}
          tone={totals.saved >= 0 ? "sage" : "coral"}
          sub={`over ${plural(totals.weeks_done, "finished week")}`}
        />
      </div>
      <PaceMeter
        value={week.spent}
        capacity={week.line}
        pace={week.pace}
        segments={28}
        label={`${money(week.spent)} of ${money(week.line)} this week`}
        paceLabel={`EVEN PACE ${money(week.pace)}`}
      />
    </Housing>
  );
}

function YearCard({ budget }: { budget: Budget }) {
  const year = budget.year;
  const line = budget.line;
  if (!year) return null;
  const under = year.estimate_to_date - year.spent;
  return (
    <Card title={`School year ${year.label}`} hint={`${line.school}'s estimate as the reference line`}>
      <div className="readouts" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
        <Readout
          label={`${line.school} estimate by today`}
          value={money(year.estimate_to_date)}
          tone="text"
          sub={`of ${money(year.estimate)} for the year`}
        />
        <Readout label="Everyday spent" value={money(year.spent)} tone="coral" sub={`${year.weeks_done} of ${year.weeks} weeks`} />
        <Readout
          label={under >= 0 ? "Under the estimate" : "Over the estimate"}
          value={money(Math.abs(under))}
          tone={under >= 0 ? "sage" : "coral"}
        />
        <Readout
          label="Saved vs weekly line"
          value={money(year.saved, { signed: true })}
          tone={year.saved >= 0 ? "sage" : "coral"}
          sub="finished weeks this year"
        />
      </div>
      <PaceMeter
        value={year.spent}
        capacity={Math.max(1, year.estimate)}
        pace={year.estimate_to_date}
        label={`${money(year.spent)} of ${line.school}'s ${money(year.estimate)} estimate`}
        paceLabel={`ESTIMATE BY TODAY ${money(year.estimate_to_date)}`}
      />
    </Card>
  );
}

export function Budgets() {
  const { params } = useLocation();
  const period = params.get("period");
  const [editing, setEditing] = useState(false);
  const query = useQuery({
    queryKey: ["budget", period ?? ""],
    queryFn: () => get<Budget>(`/api/budget${period ? `?period=${encodeURIComponent(period)}` : ""}`),
    placeholderData: (previous) => previous,
  });
  const budget = query.data;

  useEffect(() => {
    if (budget && window.location.hash) {
      document.querySelector(window.location.hash)?.scrollIntoView({ block: "start" });
    }
  }, [budget]);

  if (query.isError) {
    return (
      <Empty title="Couldn't load the budget">
        <p>{query.error instanceof Error ? query.error.message : ""}</p>
      </Empty>
    );
  }
  if (!budget) return <div className="card empty">Loading…</div>;

  if (editing) {
    return (
      <div className="stack loose">
        <div className="page-head">
          <div>
            <h1>Budget settings</h1>
            <p>Pick the weekly line and list your bills. Everything else is automatic.</p>
          </div>
        </div>
        <BudgetSettingsEditor budget={budget} onDone={() => setEditing(false)} />
      </div>
    );
  }

  function go(start: string | null) {
    if (!start || !budget) return;
    const current = budget.periods.find((item) => item.start <= budget.as_of && budget.as_of <= item.end);
    navigate(current?.start === start ? "/budgets" : `/budgets?period=${start}`, { replace: true });
  }

  const { period: info, line, totals } = budget;
  const quarter = info.kind === "quarter";

  return (
    <div className="stack loose">
      <div className="page-head">
        <div>
          <h1>Budget</h1>
          <p>
            {quarter && info.first_day ? `Quarter began ${shortDate(info.first_day)}` : rangeLabel(info.start, info.end)}
            {info.finals ? ` · finals ${shortDate(info.finals)}` : ""} · {plural(budget.weeks.length, "week")}
          </p>
        </div>
        <div className="row">
          <Stepper
            name="term"
            label={info.name.toUpperCase()}
            canPrevious={Boolean(info.previous)}
            canNext={Boolean(info.next) && (info.next ?? "") <= budget.as_of}
            onPrevious={() => go(info.previous)}
            onNext={() => go(info.next)}
          />
          <button type="button" className="btn ghost" onClick={() => setEditing(true)}>
            Settings
          </button>
        </div>
      </div>

      {!budget.saved_settings ? (
        <div className="signal info">
          <span className="mark">●</span>
          <span className="grow">
            Using {line.school}'s {line.housing.toLowerCase()} estimate: {money(line.weekly)} a week. Add rent and other
            bills so they stay out of the weekly line.
          </span>
          <button type="button" className="link small" onClick={() => setEditing(true)}>
            Set up
          </button>
        </div>
      ) : null}

      <WeekPanel budget={budget} />

      <Card
        title={quarter ? "Weeks this quarter" : "Weeks"}
        hint={info.is_current ? "each week starts fresh at the line" : info.name}
      >
        <WeekBars weeks={budget.weeks} line={line.weekly} school={line.source === "own" ? line.school_weekly : undefined} />
        <p className="tiny dim" style={{ margin: 0 }}>
          A good week doesn't raise next week's line. It just adds to what you've saved:{" "}
          {money(totals.saved, { signed: true })} so far{info.is_current ? " this term" : ""}.
        </p>
      </Card>

      <div className="spread">
        <Card title="Bills" hint={info.kind === "month" ? "this month" : `this ${info.kind}`}>
          {budget.bills.length ? (
            <BillList bills={budget.bills} />
          ) : budget.settings.bills.length ? (
            <p className="muted">Nothing due in this period.</p>
          ) : (
            <p className="muted">
              No bills yet.{" "}
              <button type="button" className="link" onClick={() => setEditing(true)}>
                Add rent, phone or tuition
              </button>
            </p>
          )}
        </Card>
        <Card title="Big stuff" hint={totals.big_stuff ? money(totals.big_stuff) : "outside the weekly line"}>
          {budget.big_stuff.length ? (
            <div>
              {budget.big_stuff.map((row) => (
                <div key={row.id} className="bill-row" style={{ gridTemplateColumns: "minmax(0,1fr) auto" }}>
                  <span className="stack tight" style={{ gap: 2 }}>
                    <span>{row.description}</span>
                    <span className="tiny dim">
                      {row.category} · {dayLabel(row.transaction_date)}
                    </span>
                  </span>
                  <span className="num small">{money(row.amount_cents * (row.transaction_type === "refund" ? -1 : 1))}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted small" style={{ margin: 0 }}>
              Flights home, textbooks, a new laptop. Anything you mark as big stuff shows here instead of eating one
              week's line.
            </p>
          )}
          <p className="tiny dim" style={{ margin: 0 }}>
            {quarter ? `${line.school} budgets about ${money(line.books_per_quarter)} a quarter for books. ` : ""}
            Mark a purchase from{" "}
            <a className="link" {...linkTo("/transactions")}>
              Transactions
            </a>{" "}
            → select → Count as → Big stuff, or{" "}
            <button type="button" className="link" onClick={() => openQuickAdd("")}>
              add one
            </button>
            .
          </p>
        </Card>
      </div>

      <YearCard budget={budget} />

      <TreatmentEditor budget={budget} />

      <Collapsible title="How it works">
        <ol className="small muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.8 }}>
          <li>
            {line.school} estimates {money(line.school_yearly)} for food, transportation and personal costs
            for a {line.housing.toLowerCase()} student in {line.year}. Spread over the {line.school_weeks} weeks
            from fall Week 0 to spring finals, that's {money(line.school_weekly)} a week.
            {line.source === "own" ? ` You chose your own line of ${money(line.weekly)} instead.` : ""}
          </li>
          <li>Every Monday starts fresh at the line. Money left on Sunday is saved and doesn't carry into next week.</li>
          <li>
            Weeks follow the {line.school} calendar: Week 0 when classes start mid-week, Weeks 1–10, then finals
            week. Breaks and summer use the same line.
          </li>
          <li>Bills and big stuff are tracked beside the line, never inside it.</li>
          <li>Categories you haven't sorted count as everyday until you do. Transfers never count, and refunds reduce spending.</li>
        </ol>
        <p className="tiny dim" style={{ margin: 0 }}>
          Estimate:{" "}
          <a className="link" href={line.source_url} target="_blank" rel="noreferrer">
            {line.school} cost of attendance
          </a>
          , checked {shortDate(line.verified_on)}.
        </p>
      </Collapsible>
    </div>
  );
}
