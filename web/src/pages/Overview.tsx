import { useMemo } from "react";

import type { Overview as OverviewData, Signal, Transaction } from "../api";
import { LeftThisWeek, SavedThisTerm, Spent, Versus, WeekMeter } from "../components/budgetBits";
import { CategoryMeters, DotCalendar, DotColumns, monthColumns, weekColumns } from "../components/charts";
import { Delta, Glyph, HeroNumber, Housing, Led, PaceMeter, Readout, Readouts, Ticker } from "../components/instrument";
import { Card, Loading, LoadError, PageHead, ScopeSwitch, Segmented, Stepper } from "../components/ui";
import { dayLabel, money, monthLabel, monthName } from "../lib/format";
import { categoryColor, LED } from "../lib/glyphs";
import { usePref, useScope } from "../lib/prefs";
import { useOverview } from "../queries";
import { linkTo, navigate, openQuickAdd, transactionsUrl, useLocation } from "../router";

/** Where a warning sends you to fix it. */
function signalLink(signal: Signal): string | null {
  switch (signal.action) {
    case "bills":
      return "/budgets/setup#bills";
    case "coa":
      return "/budgets/year";
    case "uncategorized":
      return transactionsUrl({ category: "Uncategorized" });
    case "duplicates":
      return signal.filter ? transactionsUrl(signal.filter) : null;
    default:
      return null;
  }
}

/** A caution panel: one lit tile for each thing that needs doing. */
function Signals({ signals }: { signals: Signal[] }) {
  if (!signals.length) return null;
  return (
    <section className="annunciator" aria-label="Needs a look">
      {signals.map((signal) => {
        const to = signalLink(signal);
        const inside = (
          <>
            <Led color={signal.tone === "up" ? LED.coral : LED.amber} lit pulse={signal.tone === "up"} />
            <span className="label">{signal.label}</span>
            <span className="value">{signal.value}</span>
          </>
        );
        return to ? (
          <a key={signal.text} className={`tile ${signal.tone}`} aria-label={signal.text} {...linkTo(to)}>
            {inside}
          </a>
        ) : (
          <span key={signal.text} className={`tile ${signal.tone}`} role="note" aria-label={signal.text}>
            {inside}
          </span>
        );
      })}
    </section>
  );
}

/**
 * The week and the month lead with the same thing in the same format: what was
 * spent, against the same days of the week or month before. What is left of
 * the weekly line comes second.
 */
function Panel({ data }: { data: OverviewData }) {
  const { budget, baseline, ticker } = data;
  const week = budget?.week ?? null;
  const { month, week: thisWeek, year } = data.comparisons;
  const everyday = data.scope === "everyday";
  const lastYear = year.previous !== null && year.change !== null;
  const items = useMemo(
    () =>
      ticker.items.map((item, index) => (
        <span key={index}>
          {item.name} <b className={item.refund ? "ok" : ""}>{item.refund ? `+${money(item.amount)}` : money(item.amount)}</b>
        </span>
      )),
    [ticker.items],
  );
  return (
    <Housing label="Spending panel">
      <div className={week || lastYear ? "hero-pair" : undefined}>
        {week ? (
          <Spent
            live
            label={week.label}
            cents={thisWeek.current}
            tone={everyday && week.left < 0 ? "over" : "accent"}
            comparison={<Versus comparison={thisWeek} />}
          />
        ) : null}
        <Spent
          live={data.is_current}
          label={monthName(data.month)}
          cents={data.spent}
          comparison={<Versus comparison={month} />}
        />
        {/* A finished month has no week to show, so last year stands beside it. */}
        {!week && year.previous !== null && year.change !== null ? (
          <Spent
            tone="plain"
            label="Year before"
            cents={year.previous}
            comparison={<Delta change={year.change} percent={year.percent} />}
          />
        ) : null}
      </div>
      {week ? (
        <Readouts>
          <LeftThisWeek week={week} />
          <SavedThisTerm weeks={budget?.weeks ?? []} />
          {year.previous !== null && year.change !== null ? (
            <Readout
              label="Last year"
              value={money(year.previous)}
              tone="plain"
              sub={<Delta brief change={year.change} percent={year.percent} />}
            />
          ) : null}
        </Readouts>
      ) : null}
      {week ? (
        <WeekMeter week={week} cap />
      ) : baseline && baseline.total > 0 ? (
        <PaceMeter
          value={data.spent}
          capacity={Math.max(baseline.total, data.spent)}
          pace={baseline.total}
          label={`${money(data.spent)} against ${money(baseline.total)} spent in ${monthLabel(baseline.month)}`}
          mark={monthName(baseline.month).slice(0, 3)}
        />
      ) : null}
      {items.length ? (
        <Ticker label={data.is_current ? "Today" : "Latest"} total={money(ticker.total)} items={items} />
      ) : null}
    </Housing>
  );
}

function FirstRun() {
  return (
    <Housing label="Spending panel">
      <span className="led-label">
        <span className="led-dot pulse" aria-hidden="true" />
        Ready
      </span>
      <HeroNumber value={money(0)} />
      <button type="button" className="prompt" onClick={() => openQuickAdd()} aria-label="Add the first one">
        <b>&gt;</b> 12.50 chipotle lunch<i className="pulse" aria-hidden="true" />
      </button>
      <div className="row">
        <button type="button" className="btn primary" onClick={() => openQuickAdd()}>
          + Add
        </button>
        <a className="btn" {...linkTo("/settings/data")}>
          Import a CSV
        </a>
      </div>
    </Housing>
  );
}

const TRENDS = ["week", "month"] as const;

/** Weeks or months: the same chart at two scales. The weeks are the latest ones, so an older month shows months. */
function Trend({ data, openMonth }: { data: OverviewData; openMonth: (month: string) => void }) {
  const [chosen, setUnit] = usePref("trend", TRENDS);
  const unit = data.is_current ? chosen : "month";
  if (data.monthly.length < 2 && data.weekly.length < 2) return null;
  return (
    <Card
      title="Trend"
      actions={
        data.is_current ? (
          <Segmented
            label="Trend by"
            value={unit}
            onChange={setUnit}
            options={[
              { value: "week", label: "Weeks" },
              { value: "month", label: "Months" },
            ]}
          />
        ) : null
      }
    >
      {unit === "week" ? (
        <DotColumns
          data={weekColumns(data.weekly)}
          unit="week"
          highlight={data.weekly.find((item) => item.end >= data.as_of)?.week}
          average={data.weekly.map((item) => item.rolling_4)}
          averageLabel="4-week avg"
          onPick={(picked) => {
            const week = data.weekly.find((item) => item.week === picked);
            if (week) navigate(transactionsUrl({ start: week.week, end: week.end }));
          }}
        />
      ) : (
        <DotColumns
          data={monthColumns(data.monthly)}
          highlight={data.month}
          average={data.monthly.map((item) => item.rolling_3)}
          onPick={openMonth}
          pickable={data.months}
        />
      )}
    </Card>
  );
}

/** Transactions as rows; each opens itself on Transactions. */
function Entries({ rows, asOf }: { rows: Transaction[]; asOf?: string }) {
  if (!rows.length) return <p className="muted">Nothing yet</p>;
  return (
    <div className="list">
      {rows.map((row) => (
        <a
          key={row.id}
          className="item"
          {...linkTo(transactionsUrl({ start: row.transaction_date, end: row.transaction_date, q: row.description }))}
        >
          <Glyph category={row.category} />
          <span className="lines">
            <span className="title truncate">{row.description}</span>
            <span className="meta truncate">
              <span style={{ color: categoryColor(row.category) }}>{row.category}</span> ·{" "}
              {dayLabel(row.transaction_date, asOf).split(" · ")[0]}
            </span>
          </span>
          <span className={`num ${row.transaction_type === "refund" ? "ok" : ""}`}>
            {row.transaction_type === "refund" ? "+" : ""}
            {money(row.amount_cents)}
          </span>
        </a>
      ))}
    </div>
  );
}

/** The newest entries and the largest purchases, side by side. */
function Entered({ data }: { data: OverviewData }) {
  const asOf = data.is_current ? data.as_of : undefined;
  const within = data.is_current ? "" : ` in ${monthName(data.month)}`;
  return (
    <div className="spread">
      <Card
        title={`Latest${within}`}
        actions={
          <a
            className="link small"
            {...linkTo(
              data.is_current ? "/transactions" : transactionsUrl({ start: `${data.month}-01`, end: data.as_of }),
            )}
          >
            All transactions →
          </a>
        }
      >
        <Entries rows={data.recent} asOf={asOf} />
      </Card>
      <Card
        title={`Largest${within}`}
        hint={data.largest_days ? `${data.largest_days} days` : undefined}
      >
        <Entries rows={data.largest} asOf={asOf} />
      </Card>
    </div>
  );
}

export function Overview() {
  const { params } = useLocation();
  const month = params.get("month");
  const [scope, setScope] = useScope();
  const query = useOverview(month, scope);
  const data = query.data;

  if (!data) {
    return (
      <>
        <PageHead title="Overview" />
        {query.isError ? (
          <LoadError what="the overview" error={query.error} retry={() => void query.refetch()} />
        ) : (
          <Loading />
        )}
      </>
    );
  }

  const index = data.months.indexOf(data.month);
  const openMonth = (next: string | undefined) => {
    if (!next) return;
    navigate(next === data.months[data.months.length - 1] ? "/" : `/?month=${next}`, { replace: true });
  };
  const pickDay = (date: string) => navigate(transactionsUrl({ start: date, end: date }));

  return (
    <>
      <PageHead
        title={
          <Stepper
            heading
            name="month"
            label={monthLabel(data.month)}
            canPrevious={index > 0}
            canNext={index >= 0 && index < data.months.length - 1}
            onPrevious={() => openMonth(data.months[index - 1])}
            onNext={() => openMonth(data.months[index + 1])}
          />
        }
      >
        {data.has_transactions ? <ScopeSwitch value={scope} onChange={setScope} /> : null}
      </PageHead>

      {!data.has_transactions ? (
        <FirstRun />
      ) : (
        <>
          <Panel data={data} />
          <Signals signals={data.signals} />
          <div className="spread">
            <Card title="Day by day">
              <DotCalendar
                days={data.days}
                today={data.is_current ? data.as_of : null}
                onPick={pickDay}
              />
            </Card>
            <Card title="Where it went">
              {data.categories.some((item) => item.spent > 0) ? (
                <CategoryMeters
                  categories={data.categories}
                  onPick={(category) =>
                    navigate(transactionsUrl({ category, start: `${data.month}-01`, end: data.as_of }))
                  }
                />
              ) : (
                <p className="muted">No spending yet</p>
              )}
            </Card>
          </div>
          <Trend data={data} openMonth={openMonth} />
          <Entered data={data} />
        </>
      )}
    </>
  );
}
