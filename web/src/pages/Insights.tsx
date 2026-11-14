import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { get, type Insights as InsightsData } from "../api";
import { linkTo } from "../App";
import { CashFlowChart, DotColumns, DriverBars, monthColumns } from "../components/charts";
import { Card, Collapsible, Empty, Glyph, Readout, Segmented, Stepper } from "../components/instrument";
import { money, monthLabel, monthName, percent, plural, shortDate, wholeMoney } from "../lib/format";
import { navigate, useLocation } from "../router";

type Window = "rolling_3" | "rolling_6" | "rolling_12";

function monthBefore(month: string): string {
  const [year = 1970, number = 1] = month.split("-").map(Number);
  return number === 1 ? `${year - 1}-12` : `${year}-${String(number - 1).padStart(2, "0")}`;
}

export function Insights() {
  const { params } = useLocation();
  const month = params.get("month");
  const scope = params.get("scope") === "all" ? "all" : "everyday";
  const [window, setWindow] = useState<Window>("rolling_3");
  const search = new URLSearchParams({ scope });
  if (month) search.set("month", month);
  const query = useQuery({
    queryKey: ["insights", month ?? "", scope],
    queryFn: () => get<InsightsData>(`/api/insights?${search}`),
    placeholderData: (previous) => previous,
  });
  const data = query.data;

  function setParams(next: { month?: string | null; scope?: string }) {
    const value = new URLSearchParams(params);
    if (next.month !== undefined) {
      if (next.month) value.set("month", next.month);
      else value.delete("month");
    }
    if (next.scope !== undefined) {
      if (next.scope === "all") value.set("scope", "all");
      else value.delete("scope");
    }
    const text = value.toString();
    navigate(text ? `/insights?${text}` : "/insights", { replace: true });
  }

  if (query.isError) {
    return (
      <Empty title="Couldn't load insights">
        <p>{query.error instanceof Error ? query.error.message : ""}</p>
      </Empty>
    );
  }
  if (!data) return <div className="card empty">Loading…</div>;

  const index = data.months.indexOf(data.month);
  const header = (
    <div className="page-head">
      <div>
        <h1>Insights</h1>
      </div>
      <div className="row">
        <Stepper
          name="month"
          label={monthLabel(data.month).toUpperCase()}
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
    </div>
  );

  if (!data.has_transactions) {
    return (
      <div className="stack loose">
        {header}
        <Empty title="Nothing to analyze yet">
          <p>Insights appear once there are a few weeks of transactions.</p>
        </Empty>
      </div>
    );
  }

  const standouts = data.anomalies.filter((item) => item.date.startsWith(data.month)).slice(0, 8);
  const windowLabel = { rolling_3: "3-month", rolling_6: "6-month", rolling_12: "12-month" }[window];
  const savings = data.savings;
  const year = data.year;
  const forecast = data.forecast;
  const selected = data.monthly.find((item) => item.month === data.month);
  const isCurrent = data.month === data.months[data.months.length - 1];
  const thisMonth = forecast.months.find((item) => item.partial);
  // Money in and out only says something once some income is recorded.
  const hasIncome = data.cash_flow.some((item) => item.income > 0);
  const scopeWord = scope === "all" ? "" : "everyday ";
  // "$310 in a quarter, $240 on break, $200 in summer", for the kinds the forecast has seen.
  const rates = (
    [
      ["quarter", "in a quarter"],
      ["break", "on break"],
      ["summer", "in summer"],
    ] as const
  ).flatMap(([kind, words]) => {
    const rate = forecast.weekly_rates[kind];
    return rate === undefined ? [] : [`${wholeMoney(rate)} ${words}`];
  });

  return (
    <div className="stack loose">
      {header}

      <div className="readouts" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
        <Readout
          label={isCurrent ? `${monthName(data.month)} so far` : monthName(data.month)}
          value={money(selected?.spent ?? 0)}
          sub={selected ? `${windowLabel} average ${money(selected[window])}` : undefined}
        />
        {thisMonth ? (
          <Readout
            label={`${monthName(thisMonth.month)} is heading for`}
            value={wholeMoney(thisMonth.expected)}
            tone="amber"
            sub={`likely ${wholeMoney(thisMonth.low)}–${wholeMoney(thisMonth.high)} by month end`}
          />
        ) : null}
        <Readout
          label="Typical month"
          value={forecast.months.length ? wholeMoney(forecast.level) : "—"}
          tone={forecast.months.length ? undefined : "text"}
          sub={forecast.months.length ? "recent months count more" : "needs two full months"}
        />
        {data.duplicate_groups ? (
          <Readout label="Possible duplicates" value={String(data.duplicate_groups)} tone="text" sub="same date, amount, text" />
        ) : (
          <Readout label="Recurring" value={String(data.recurring.length)} tone="text" sub="merchants that repeat" />
        )}
      </div>

      <div className="spread">
        <Card title={`What changed since ${monthName(monthBefore(data.month))}`}>
          {data.drivers.length ? (
            <DriverBars
              drivers={data.drivers}
              onPick={(category) =>
                navigate(
                  `/transactions?category=${encodeURIComponent(category)}&start=${data.month}-01&end=${data.as_of}`,
                )
              }
            />
          ) : (
            <p className="muted">No category moved much.</p>
          )}
        </Card>
        <Card title="Stands out">
          {standouts.length ? (
            <div>
              {standouts.map((item, at) => (
                <div key={at} className="bill-row" style={{ gridTemplateColumns: "34px minmax(0,1fr) auto" }}>
                  <Glyph category={item.category} small />
                  <span className="stack tight" style={{ gap: 2, minWidth: 0 }}>
                    <span>{item.description}</span>
                    <span className="tiny dim">
                      {item.category} · {shortDate(item.date)} · usually {money(item.typical)}
                    </span>
                  </span>
                  <span className="num small up">{money(item.amount)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">Nothing unusual this month.</p>
          )}
        </Card>
      </div>

      <Card
        title="Trend"
        actions={
          <Segmented<Window>
            label="Average window"
            value={window}
            onChange={setWindow}
            options={[
              { value: "rolling_3", label: "3 mo" },
              { value: "rolling_6", label: "6 mo" },
              { value: "rolling_12", label: "12 mo" },
            ]}
          />
        }
      >
        <DotColumns
          data={monthColumns(data.monthly)}
          highlight={data.month}
          average={data.monthly.map((item) => item[window])}
          averageLabel={`${windowLabel} average`}
          forecast={forecast.months}
          onPick={(picked) => setParams({ month: picked })}
          pickable={data.months}
        />
      </Card>

      <div className="spread">
        <Card title="Looking ahead">
          {forecast.months.length ? (
            <>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Month</th>
                      <th className="num">Expected</th>
                      <th className="num">Likely range</th>
                    </tr>
                  </thead>
                  <tbody>
                    {forecast.months.map((item) => (
                      <tr key={item.month}>
                        <td>
                          {monthLabel(item.month)}
                          {item.partial ? <div className="tiny dim">{money(item.spent)} so far</div> : null}
                        </td>
                        <td className="num warn">~{wholeMoney(item.expected)}</td>
                        <td className="num">
                          {wholeMoney(item.low)}–{wholeMoney(item.high)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="tiny dim" style={{ margin: 0 }}>
                {rates.length
                  ? `A week costs you about ${rates.join(", ")}. Each month is your typical month scaled by how many of those days it has. `
                  : ""}
                The range is how far this was off when replayed on your last{" "}
                {plural(forecast.history_months, "full month")}
                {forecast.typical_miss ? ` (about ±${wholeMoney(forecast.typical_miss)})` : ""}.
              </p>
            </>
          ) : (
            <p className="muted">
              A forecast needs two full months of {scopeWord}spending to learn from
              {forecast.history_months ? `; there is ${forecast.history_months} so far` : ""}.
            </p>
          )}
        </Card>
        <Card title="Repeats">
          {data.recurring.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Merchant</th>
                    <th>How often</th>
                    <th className="num">Usually</th>
                    <th>Next</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recurring.map((item) => (
                    <tr key={item.merchant}>
                      <td>
                        <a
                          {...linkTo(`/transactions?q=${encodeURIComponent(item.merchant)}`)}
                          style={{ color: "inherit" }}
                        >
                          {item.merchant}
                        </a>
                        <div className="tiny dim">{plural(item.occurrences, "time")}</div>
                      </td>
                      <td className="small">{item.frequency}</td>
                      <td className="num">{money(item.average)}</td>
                      <td className="small">
                        {shortDate(item.next_expected)}
                        {item.status && item.status !== "Active" ? <div className="tiny warn">{item.status}</div> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No repeating merchants found yet.</p>
          )}
        </Card>
      </div>

      {hasIncome ? (
        <Card
          title="Cash flow"
          hint={`saved ${money(savings.savings, { signed: true })}${
            savings.rate === null ? "" : ` (${percent(savings.rate)} of income)`
          }`}
        >
          <CashFlowChart data={data.cash_flow} />
        </Card>
      ) : null}

      {data.terms.length ? (
        <Card title="By school term">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Period</th>
                  <th className="num">Weeks</th>
                  <th className="num">Spent</th>
                  <th className="num">Per week</th>
                </tr>
              </thead>
              <tbody>
                {data.terms
                  .slice()
                  .reverse()
                  .map((term) => (
                    <tr key={term.start}>
                      <td style={term.kind === "quarter" ? undefined : { color: "var(--dim)" }}>{term.period}</td>
                      <td className="num">{term.weeks}</td>
                      <td className="num">{money(term.spent)}</td>
                      <td className="num">{money(Math.round(term.spent / Math.max(1, term.weeks)))}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {year ? (
        <Collapsible title={`School year ${year.label}`}>
          <div className="readouts" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))" }}>
            <Readout label="Estimate by today" value={money(year.estimate_to_date)} tone="text" sub={`of ${money(year.estimate)}`} />
            <Readout label="Everyday spent" value={money(year.spent)} tone="coral" />
            <Readout
              label={year.estimate_to_date >= year.spent ? "Under the estimate" : "Over the estimate"}
              value={money(Math.abs(year.estimate_to_date - year.spent))}
              tone={year.estimate_to_date >= year.spent ? "sage" : "coral"}
            />
          </div>
        </Collapsible>
      ) : null}
    </div>
  );
}
