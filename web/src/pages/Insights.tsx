import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { get, type Insights as InsightsData } from "../api";
import { linkTo } from "../App";
import { CashFlowChart, DotColumns, DriverBars } from "../components/charts";
import { Card, Collapsible, Empty, Glyph, Readout, Segmented, Stepper } from "../components/instrument";
import { money, monthLabel, percent, plural, shortDate } from "../lib/format";
import { navigate, useLocation } from "../router";

type Window = "rolling_3" | "rolling_6" | "rolling_12";

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
        <p>What changed, what repeats and what stands out.</p>
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

  return (
    <div className="stack loose">
      {header}

      <div className="readouts" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))" }}>
        <Readout label="Income to date" value={money(savings.income)} tone="sage" />
        <Readout label="Net spending to date" value={money(savings.net_outflow)} tone="coral" />
        <Readout
          label="Saved"
          value={money(savings.savings, { signed: true })}
          tone={savings.savings >= 0 ? "sage" : "coral"}
          sub={savings.rate === null ? "no income recorded" : `${percent(savings.rate)} of income`}
        />
        {data.duplicate_groups ? (
          <Readout label="Possible duplicates" value={String(data.duplicate_groups)} tone="text" sub="same date, amount, text" />
        ) : (
          <Readout label="Recurring" value={String(data.recurring.length)} tone="text" sub="merchants that repeat" />
        )}
      </div>

      <div className="spread">
        <Card title="What changed" hint={`${monthLabel(data.month)} vs the month before, same days`}>
          {data.drivers.length ? (
            <DriverBars drivers={data.drivers} />
          ) : (
            <p className="muted">No category moved much.</p>
          )}
        </Card>
        <Card title="Stands out" hint={`unusually large for their category in ${monthLabel(data.month)}`}>
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
        hint={`net spending with the ${windowLabel} average`}
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
          data={data.monthly}
          highlight={data.month}
          average={data.monthly.map((item) => item[window])}
          averageLabel={`${windowLabel} average`}
        />
      </Card>

      <div className="spread">
        <Card title="Cash flow" hint="money in vs out by month">
          {data.cash_flow.length ? <CashFlowChart data={data.cash_flow} /> : <p className="muted">No months yet.</p>}
        </Card>
        <Card title="Repeats" hint="subscriptions and regular stops">
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

      {data.terms.length ? (
        <Card title="By school term" hint="quarters, breaks and summer on the UCLA calendar">
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
        <Collapsible title={`School year ${year.label}`} hint="against UCLA's estimate">
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
