import { useEffect, useMemo, useState } from "react";

import type { Comparison, Overview as OverviewData, Signal } from "../api";
import { linkTo, openQuickAdd } from "../App";
import { BillList, billsSummary, Versus } from "../components/budgetBits";
import { CategoryMeters, DotCalendar, DotColumns, monthColumns, weekColumns } from "../components/charts";
import {
  Card,
  Empty,
  Glyph,
  HeroNumber,
  Housing,
  PaceMeter,
  Readout,
  Segmented,
  Stepper,
  Ticker,
} from "../components/instrument";
import { dayLabel, money, monthLabel, monthName, plural, versus } from "../lib/format";
import { categoryColor } from "../lib/glyphs";
import { useOverview } from "../queries";
import { navigate, useLocation } from "../router";

const LAST_MONTH_KEY = "jizhang:lastMonth";

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private window: the flip just won't replay */
  }
}

/** Where a banner sends you to fix what it reports. */
function signalLink(signal: Signal): { to: string; label: string } | null {
  switch (signal.action) {
    case "bills":
      return { to: "/budgets#bills", label: "See bills" };
    case "uncategorized":
      return { to: "/transactions?category=Uncategorized", label: "Add categories" };
    case "treatments":
      return { to: "/budgets#treatments", label: "Sort them" };
    case "duplicates":
      return signal.filter
        ? { to: `/transactions?${new URLSearchParams(signal.filter)}`, label: "Check them" }
        : null;
    default:
      return null;
  }
}

/** One of the panel's leading numbers: what was spent, and how that compares. */
function Spent({
  label,
  value,
  over = false,
  comparison,
}: {
  label: string;
  value: number;
  over?: boolean;
  comparison: Comparison;
}) {
  return (
    <div className="stack tight">
      <span className="led-label">
        <span className="led-dot pulse" aria-hidden="true" />
        {label}
      </span>
      <HeroNumber value={money(value)} tone={over ? "over" : "accent"} />
      <div className="small">
        <Versus comparison={comparison} />
      </div>
    </div>
  );
}

/**
 * The week and the month lead with the same thing in the same format: what was
 * spent, against the same days of the week or month before. What is left of
 * the weekly line comes second.
 */
function Panel({ data }: { data: OverviewData }) {
  const budget = data.budget;
  const week = budget?.week ?? null;
  const { month, week: thisWeek, year } = data.comparisons;
  const everyday = data.scope === "everyday";
  const over = week !== null && week.left < 0;
  const tickerItems = data.ticker.items.map((item, index) => (
    <span key={index}>
      {item.name.toUpperCase()}{" "}
      <b className={item.refund ? "ok" : ""}>{item.refund ? `+${money(item.amount)}` : money(item.amount)}</b>
    </span>
  ));

  return (
    <Housing label="Spending panel">
      <div className="tiny dim caps">
        {everyday ? "everyday spending" : "all spending"} · as of {dayLabel(data.as_of)}
      </div>
      <div className={week ? "hero-pair" : undefined}>
        {week ? (
          <Spent
            label={`SPENT THIS WEEK · ${week.label.toUpperCase()}`}
            value={thisWeek.current}
            over={everyday && over}
            comparison={thisWeek}
          />
        ) : null}
        <Spent
          label={
            data.is_current
              ? `SPENT THIS MONTH · ${monthName(data.month).toUpperCase()}`
              : `SPENT · ${monthLabel(data.month).toUpperCase()}`
          }
          value={data.spent}
          comparison={month}
        />
      </div>
      {week || year.previous !== null ? (
        <div className="readouts" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
          {week ? (
            <Readout
              label={over ? "Over this week's line" : "Left this week"}
              value={money(Math.abs(week.left))}
              tone={over ? "coral" : "sage"}
              sub={
                over
                  ? `past a ${money(week.line)} line · next week starts fresh`
                  : `of a ${money(week.line)} line · about ${money(week.per_day)} a day`
              }
            />
          ) : null}
          {year.previous !== null && year.change !== null ? (
            <Readout
              label="Same days last year"
              value={money(year.previous)}
              tone="text"
              sub={`now ${versus(year.change, "that", year.percent)}`}
            />
          ) : null}
          {budget ? (
            <Readout
              label="Saved this term"
              value={money(budget.saved, { signed: true })}
              tone={budget.saved >= 0 ? "sage" : "coral"}
              sub={`over ${plural(budget.weeks_done, "finished week")}`}
            />
          ) : null}
        </div>
      ) : null}
      {week ? (
        <PaceMeter
          value={week.spent}
          capacity={week.line}
          pace={week.pace}
          segments={28}
          label={`${money(week.spent)} of ${money(week.line)} this week`}
          paceLabel={`EVEN PACE ${money(week.pace)}`}
        />
      ) : data.baseline && data.baseline.total > 0 ? (
        <PaceMeter
          value={data.spent}
          capacity={Math.max(data.baseline.total, data.spent)}
          pace={null}
          label={`${money(data.spent)} against ${money(data.baseline.total)} spent in ${monthLabel(data.baseline.month)}`}
        />
      ) : null}
      {tickerItems.length ? <Ticker label={`${data.ticker.label} purchases`} items={tickerItems} /> : null}
    </Housing>
  );
}

export function Overview() {
  const { params } = useLocation();
  const month = params.get("month");
  const scope = params.get("scope") === "all" ? "all" : "everyday";
  const query = useOverview(month, scope);
  const data = query.data;

  const [flapFrom] = useState(() => readStorage(LAST_MONTH_KEY));
  useEffect(() => {
    if (data?.is_current) writeStorage(LAST_MONTH_KEY, monthLabel(data.month).toUpperCase());
  }, [data?.is_current, data?.month]);

  const index = data ? data.months.indexOf(data.month) : -1;
  const setParams = (next: { month?: string | null; scope?: string }) => {
    const search = new URLSearchParams(params);
    if (next.month !== undefined) {
      if (next.month && data && next.month !== data.months[data.months.length - 1]) search.set("month", next.month);
      else search.delete("month");
    }
    if (next.scope !== undefined) {
      if (next.scope === "all") search.set("scope", "all");
      else search.delete("scope");
    }
    const text = search.toString();
    navigate(text ? `/?${text}` : "/", { replace: true });
  };

  const dailyAllowance = useMemo(() => {
    if (!data?.budget) return null;
    return data.budget.week.per_day;
  }, [data]);

  if (query.isError) {
    return (
      <Empty title="Couldn't load the overview">
        <p>{query.error instanceof Error ? query.error.message : "Try again."}</p>
        <button type="button" className="btn" onClick={() => void query.refetch()}>
          Retry
        </button>
      </Empty>
    );
  }
  if (!data) return <div className="card empty">Warming up the panel…</div>;

  const label = monthLabel(data.month).toUpperCase();
  const pickDay = (date: string) => navigate(`/transactions?start=${date}&end=${date}`);

  return (
    <div className="stack loose">
      <div className="page-head">
        <Stepper
          name="month"
          label={label}
          from={data.is_current && flapFrom && flapFrom !== label ? flapFrom : undefined}
          canPrevious={index > 0}
          canNext={index >= 0 && index < data.months.length - 1}
          onPrevious={() => setParams({ month: data.months[index - 1] ?? null })}
          onNext={() => setParams({ month: data.months[index + 1] ?? null })}
        />
        <Segmented
          label="Which spending"
          value={scope}
          onChange={(value) => setParams({ scope: value })}
          options={[
            { value: "everyday", label: "Everyday" },
            { value: "all", label: "Everything" },
          ]}
        />
      </div>

      {!data.has_transactions ? (
        <Housing label="Spending panel">
          <span className="led-label">
            <span className="led-dot pulse" aria-hidden="true" />
            READY
          </span>
          <HeroNumber value={money(0)} />
          <p className="muted" style={{ margin: 0 }}>
            Nothing recorded yet. Press <kbd>⌘K</kbd> and type something like{" "}
            <span style={{ color: "var(--accent)" }}>“12.50 chipotle lunch”</span>, or bring in a bank CSV.
          </p>
          <div className="row">
            <button type="button" className="btn primary" onClick={() => openQuickAdd()}>
              + Add the first one
            </button>
            <a className="btn" {...linkTo("/import")}>
              Import a CSV
            </a>
          </div>
        </Housing>
      ) : (
        <Panel data={data} />
      )}

      {data.signals.length ? (
        <div className="stack tight" aria-label="Things to look at">
          {data.signals.map((signal, at) => {
            const to = signalLink(signal);
            return (
              <div key={at} className={`signal ${signal.tone}`}>
                <span className="mark" aria-hidden="true">
                  {signal.tone === "up" ? "▲" : signal.tone === "ok" ? "✓" : signal.tone === "warn" ? "!" : "●"}
                </span>
                <span className="grow">{signal.text}</span>
                {to ? (
                  <a className="link small" {...linkTo(to.to)}>
                    {to.label} →
                  </a>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}

      {data.has_transactions ? (
        <>
          <div className="spread">
            <Card title="Day by day">
              <DotCalendar
                days={data.days}
                today={data.is_current ? data.as_of : null}
                onPick={pickDay}
                dailyAllowance={dailyAllowance}
              />
            </Card>
            <Card title="Where it went" hint={money(data.spent)}>
              {data.categories.some((item) => item.spent > 0) ? (
                <CategoryMeters
                  categories={data.categories}
                  onPick={(category) =>
                    navigate(
                      `/transactions?category=${encodeURIComponent(category)}&start=${data.month}-01&end=${data.as_of}`,
                    )
                  }
                />
              ) : (
                <p className="muted">No spending in this month yet.</p>
              )}
            </Card>
          </div>

          <div className="spread">
            {data.bills.length || data.upcoming.length ? (
              <Card title={data.bills.length ? "Bills" : "Coming up"} hint={billsSummary(data.bill_totals)}>
                <BillList bills={data.bills} upcoming={data.upcoming} />
              </Card>
            ) : null}
            <Card
              title="Latest"
              actions={
                <a className="link small" {...linkTo("/transactions")}>
                  All transactions →
                </a>
              }
            >
              {data.recent.length ? (
                <div>
                  {data.recent.map((row) => (
                    <div key={row.id} className="bill-row" style={{ gridTemplateColumns: "34px minmax(0,1fr) auto" }}>
                      <Glyph category={row.category} small />
                      <span className="stack tight" style={{ gap: 2, minWidth: 0 }}>
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {row.description}
                        </span>
                        <span className="tiny dim">
                          <span style={{ color: categoryColor(row.category) }}>{row.category}</span> ·{" "}
                          {dayLabel(row.transaction_date, data.is_current ? data.as_of : undefined)}
                        </span>
                      </span>
                      <span className={`num small ${row.transaction_type === "refund" ? "ok" : ""}`}>
                        {row.transaction_type === "refund" ? "+" : ""}
                        {money(row.amount_cents)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted">Nothing this month yet.</p>
              )}
            </Card>
          </div>

          {/* Weeks and months side by side, drawn and read the same way. */}
          <div className="spread">
            {data.weekly.length > 1 ? (
              <Card title="Week by week">
                <DotColumns
                  data={weekColumns(data.weekly)}
                  unit="week"
                  highlight={data.is_current ? data.weekly.find((item) => item.end >= data.as_of)?.week : undefined}
                  average={data.weekly.map((item) => item.rolling_4)}
                  averageLabel="4-week average"
                  onPick={(picked) => {
                    const week = data.weekly.find((item) => item.week === picked);
                    if (week) navigate(`/transactions?start=${week.week}&end=${week.end}`);
                  }}
                />
              </Card>
            ) : null}
            {data.monthly.length > 1 ? (
              <Card title="Month by month">
                <DotColumns
                  data={monthColumns(data.monthly)}
                  highlight={data.month}
                  average={data.monthly.map((item) => item.rolling_3)}
                  onPick={(picked) => setParams({ month: picked })}
                  pickable={data.months}
                />
              </Card>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
