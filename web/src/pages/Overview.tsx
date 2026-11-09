import { useEffect, useMemo, useState } from "react";

import type { Overview as OverviewData, Signal } from "../api";
import { linkTo, openQuickAdd } from "../App";
import { BillList } from "../components/budgetBits";
import { CategoryMeters, DotCalendar, DotColumns } from "../components/charts";
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
import { dayLabel, money, monthLabel, parseIso, percent, plural } from "../lib/format";
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

function signalLink(signal: Signal): string | null {
  if (signal.action === "uncategorized") return "/transactions?category=Uncategorized";
  if (signal.action === "treatments") return "/budgets#treatments";
  if (signal.action === "budgets") return "/budgets";
  return null;
}

function Panel({ data }: { data: OverviewData }) {
  const budget = data.budget;
  const asOf = parseIso(data.as_of);
  const monthName = monthLabel(data.month).toUpperCase();
  const comparison = data.comparisons.month;

  let label: string;
  let hero: string;
  let tone: "accent" | "over" = "accent";
  let sub: string;
  const week = budget?.week ?? null;
  if (budget && week) {
    if (week.left < 0) {
      label = `OVER THE LINE · ${week.label.toUpperCase()}`;
      hero = money(-week.left);
      tone = "over";
      sub = `${money(week.spent)} spent of the ${money(week.line)} weekly line · next week starts fresh`;
    } else {
      label = `LEFT THIS WEEK · ${week.label.toUpperCase()}`;
      hero = money(week.left);
      sub = `about ${money(week.per_day)} a day for ${plural(week.days_left, "day")} · ${budget.period.toLowerCase()}`;
    }
  } else {
    label = data.is_current ? "SPENT THIS MONTH" : `SPENT · ${monthName}`;
    hero = money(data.spent);
    sub =
      comparison.change === null
        ? "no earlier month to compare yet"
        : `${money(comparison.change, { signed: true })} vs same days last month`;
  }

  const paceGap = week ? week.spent - week.pace : null;
  const tickerItems = data.ticker.items.map((item, index) => (
    <span key={index}>
      {item.name.toUpperCase()}{" "}
      <b className={item.refund ? "ok" : ""}>{item.refund ? `+${money(item.amount)}` : money(item.amount)}</b>
    </span>
  ));

  return (
    <Housing label="Spending panel">
      <div className="row between">
        <span className="led-label">
          <span className="led-dot pulse" aria-hidden="true" />
          {label}
        </span>
        <span className="tiny dim caps">
          {week ? "everyday spending" : data.scope === "everyday" ? "everyday spending" : "all spending"} · as of{" "}
          {dayLabel(data.as_of)}
        </span>
      </div>
      <HeroNumber value={hero} tone={tone} />
      <div className="muted small" style={{ marginTop: -10 }}>
        {sub}
      </div>
      <div className="readouts" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
        {week ? (
          <Readout label="Week" value={week.label} tone="text" sub={`${money(week.line)} line`} />
        ) : (
          <Readout label="Day" value={`${asOf.getDate()} / ${data.days_in_month}`} tone="text" />
        )}
        <Readout label={week ? "Spent this week" : "Spent"} value={money(week ? week.spent : data.spent)} tone="coral" />
        {week && paceGap !== null ? (
          <Readout
            label="Vs pace"
            value={money(paceGap, { signed: true })}
            tone={paceGap > 0 ? "coral" : "sage"}
            sub={paceGap > 0 ? "ahead of an even week" : "under an even week"}
          />
        ) : (
          <Readout
            label="Vs last month"
            value={comparison.percent === null ? "—" : percent(comparison.percent)}
            tone={(comparison.change ?? 0) > 0 ? "coral" : "sage"}
            sub="same days"
          />
        )}
        {budget ? (
          <Readout
            label="Saved this term"
            value={money(budget.saved, { signed: true })}
            tone={budget.saved >= 0 ? "sage" : "coral"}
            sub={`over ${plural(budget.weeks_done, "finished week")}`}
          />
        ) : (
          <Readout
            label="This week"
            value={money(data.comparisons.week.current)}
            tone="text"
            sub={
              data.comparisons.week.change === null
                ? undefined
                : `${money(data.comparisons.week.change, { signed: true })} vs last week`
            }
          />
        )}
      </div>
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
                  <a className="link small" {...linkTo(to)}>
                    Review →
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
            <Card title="Day by day" hint="click a day to see it">
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
            {data.bills.length ? (
              <Card title="Bills" hint="this month">
                <BillList bills={data.bills} />
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

          {data.monthly.length > 1 ? (
            <Card title="Month by month" hint="net spending, last 12 months">
              <DotColumns
                data={data.monthly}
                highlight={data.month}
                average={data.monthly.map((item) => item.rolling_3)}
              />
            </Card>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
