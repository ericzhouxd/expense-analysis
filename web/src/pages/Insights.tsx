import { useQuery } from "@tanstack/react-query";

import { type ForecastMonth, get, type Insights as InsightsData } from "../api";
import { CashFlowChart, DotColumns, DriverBars, monthColumns } from "../components/charts";
import { Spent } from "../components/budgetBits";
import { Band, Delta, Housing, Pips, Readout, Readouts } from "../components/instrument";
import {
  Card,
  Empty,
  Fold,
  Loading,
  LoadError,
  PageHead,
  ScopeSwitch,
  Segmented,
  Stepper,
} from "../components/ui";
import { money, monthLabel, monthName, wholeMoney } from "../lib/format";
import { usePref, useScope } from "../lib/prefs";
import { navigate, transactionsUrl, useLocation } from "../router";

const WINDOWS = ["rolling_3", "rolling_6", "rolling_12"] as const;
const KINDS = [
  ["quarter", "Quarter"],
  ["break", "Break"],
  ["summer", "Summer"],
] as const;
const WINDOW_LABEL = { rolling_3: "3-month avg", rolling_6: "6-month avg", rolling_12: "12-month avg" };

function monthBefore(month: string): string {
  const [year = 1970, number = 1] = month.split("-").map(Number);
  return number === 1 ? `${year - 1}-12` : `${year}-${String(number - 1).padStart(2, "0")}`;
}

function ForecastTable({ months }: { months: ForecastMonth[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Month</th>
            <th className="num">So far</th>
            <th className="num">Expected</th>
            <th className="num">Range</th>
          </tr>
        </thead>
        <tbody>
          {months.map((item) => (
            <tr key={item.month}>
              <td>{monthLabel(item.month)}</td>
              <td className="num muted">{item.partial ? money(item.spent) : ""}</td>
              <td className="num">{wholeMoney(item.expected)}</td>
              <td className="num muted">
                {wholeMoney(item.low)}–{wholeMoney(item.high)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Trend({
  data,
  openMonth,
}: {
  data: InsightsData;
  openMonth: (month: string) => void;
}) {
  const [window, setWindow] = usePref("average", WINDOWS);
  const { forecast } = data;
  const rates = forecast.weekly_rates;
  return (
    <Card
      title="Trend"
      actions={
        <Segmented
          label="Average over"
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
        averageLabel={WINDOW_LABEL[window]}
        forecast={forecast.months}
        onPick={openMonth}
        pickable={data.months}
      />
      {forecast.months.length ? (
        <Fold title="Table">
          <ForecastTable months={forecast.months} />
          <Readouts>
            {KINDS.map(([kind, label]) =>
              rates[kind] === undefined ? null : (
                <Readout key={kind} label={label} value={`${wholeMoney(rates[kind])}/wk`} tone="amber" />
              ),
            )}
            {forecast.typical_miss ? (
              <Readout label="Usual miss" value={`±${wholeMoney(forecast.typical_miss)}`} tone="plain" />
            ) : null}
          </Readouts>
        </Fold>
      ) : (
        <span className="label row">
          Forecast
          <Pips
            label={`${forecast.history_months} of 2 full months`}
            pips={[0, 1].map((index) => (index < forecast.history_months ? "warn" : "off"))}
          />
        </span>
      )}
    </Card>
  );
}

function Changes({ data }: { data: InsightsData }) {
  return (
    <Card title={`Against ${monthName(monthBefore(data.month))}`}>
      {data.drivers.length ? (
        <DriverBars
          drivers={data.drivers}
          onPick={(category) =>
            navigate(transactionsUrl({ category, start: `${data.month}-01`, end: data.as_of }))
          }
        />
      ) : (
        <p className="muted">No change</p>
      )}
    </Card>
  );
}

function Terms({ data }: { data: InsightsData }) {
  if (!data.terms.length) return null;
  return (
    <Card title="By school term">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Term</th>
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
                  <td className={term.kind === "quarter" ? "" : "muted"}>{term.period}</td>
                  <td className="num muted">{term.weeks}</td>
                  <td className="num">{money(term.spent)}</td>
                  <td className="num">{money(Math.round(term.spent / Math.max(1, term.weeks)))}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function CashFlow({ data }: { data: InsightsData }) {
  // Money in and out only says something once some income is recorded.
  if (!data.cash_flow.some((item) => item.income > 0)) return null;
  const { savings, rate } = data.savings;
  return (
    <Card
      title="Cash flow"
      hint={`${money(savings, { signed: true })}${rate === null || savings < 0 ? "" : ` · ${Math.round(rate)}%`}`}
    >
      <CashFlowChart data={data.cash_flow} />
    </Card>
  );
}

export function Insights() {
  const { params } = useLocation();
  const month = params.get("month");
  const [scope, setScope] = useScope();
  const search = new URLSearchParams({ scope });
  if (month) search.set("month", month);
  const query = useQuery({
    queryKey: ["insights", month ?? "", scope],
    queryFn: () => get<InsightsData>(`/api/insights?${search}`),
    placeholderData: (previous) => previous,
  });
  const data = query.data;

  if (!data) {
    return (
      <>
        <PageHead title="Insights" />
        {query.isError ? (
          <LoadError what="insights" error={query.error} retry={() => void query.refetch()} />
        ) : (
          <Loading />
        )}
      </>
    );
  }
  if (!data.has_transactions) {
    return (
      <>
        <PageHead title="Insights" />
        <Empty title="No spending yet" />
      </>
    );
  }

  const index = data.months.indexOf(data.month);
  const last = data.months[data.months.length - 1];
  const openMonth = (next: string | undefined) => {
    if (next) navigate(next === last ? "/insights" : `/insights?month=${next}`, { replace: true });
  };
  const { forecast } = data;
  const selected = data.monthly.find((item) => item.month === data.month);
  const before = data.monthly.find((item) => item.month === monthBefore(data.month));
  const typical = forecast.months.length ? wholeMoney(forecast.level) : null;
  const isCurrent = data.month === last;
  const thisMonth = isCurrent ? forecast.months.find((item) => item.partial) : undefined;

  return (
    <>
      <PageHead title="Insights">
        <Stepper
          name="month"
          label={monthLabel(data.month)}
          canPrevious={index > 0}
          canNext={index >= 0 && index < data.months.length - 1}
          onPrevious={() => openMonth(data.months[index - 1])}
          onNext={() => openMonth(data.months[index + 1])}
        />
        <ScopeSwitch value={scope} onChange={setScope} />
      </PageHead>

      <Housing label="Month panel">
        <div className="hero-pair">
          <Spent
            live={isCurrent}
            label={monthName(data.month)}
            cents={selected?.spent ?? 0}
            comparison={
              !isCurrent && before && selected ? (
                <Delta change={selected.spent - before.spent} than={monthName(before.month)} />
              ) : typical ? (
                <span className="stat">
                  <i>Typical</i> {typical}
                </span>
              ) : null
            }
          />
          {thisMonth ? (
            <Spent
              whole
              tone="amber"
              label="Heading for"
              cents={thisMonth.expected}
              comparison={
                <Band low={thisMonth.low} at={thisMonth.expected} high={thisMonth.high} format={wholeMoney} />
              }
            />
          ) : typical ? (
            <Spent
              whole
              tone="plain"
              label="Typical month"
              cents={forecast.level}
              comparison={null}
            />
          ) : null}
        </div>
      </Housing>
      <Trend data={data} openMonth={openMonth} />
      <div className="spread">
        <Changes data={data} />
        <Terms data={data} />
      </div>
      <CashFlow data={data} />
    </>
  );
}
