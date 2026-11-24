import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { type Budget, get } from "../api";
import { BudgetSetup } from "../components/BudgetBasis";
import { LeftThisWeek, LineSource, SavedThisTerm, Spent, Versus, WeekBars, WeekMeter } from "../components/budgetBits";
import { SchoolYear } from "../components/CoaCard";
import { Delta, Housing, Readout, Readouts } from "../components/instrument";
import { Card, Empty, Loading, LoadError, PageHead, Stepper, Tabs } from "../components/ui";
import { money } from "../lib/format";
import { useBootstrap } from "../queries";
import { BUDGET_TABS, linkTo, navigate, openQuickAdd, transactionsUrl, useLocation } from "../router";

/** This week against the line, or what a finished (or coming) term came to. */
function Panel({ budget }: { budget: Budget }) {
  const { week, totals, line } = budget;
  const done = budget.weeks.flatMap((item) => (item.saved === null ? [] : [item.saved]));
  if (!week) {
    return (
      <Housing label="Term panel">
        <Spent
          label="Spent"
          cents={totals.everyday}
          tone={totals.saved < 0 ? "over" : "accent"}
          comparison={totals.weeks_done ? <Delta change={-totals.saved} than="Line" /> : null}
        />
        <Readouts>
          <SavedThisTerm weeks={done} />
          <Readout label="Line" value={money(totals.line_to_date)} tone="amber" />
          <Readout label="Bills" value={money(totals.bills)} tone="plain" />
          <Readout label="Big stuff" value={money(totals.big_stuff)} tone="plain" />
        </Readouts>
      </Housing>
    );
  }
  return (
    <Housing label="This week panel">
      <Spent
        live
        label={week.label}
        cents={week.spent}
        tone={week.left < 0 ? "over" : "accent"}
        comparison={<Versus comparison={budget.comparison} />}
      />
      <Readouts>
        <LeftThisWeek week={week} />
        <Readout
          label="Weekly line"
          value={money(line.weekly)}
          tone="amber"
          sub={<LineSource source={line.source} />}
        />
        <SavedThisTerm weeks={done} />
      </Readouts>
      <WeekMeter week={week} />
    </Housing>
  );
}

function Term({ budget }: { budget: Budget }) {
  const { period: info, line } = budget;
  return (
    <>
      <Panel budget={budget} />
      <Card title={info.kind === "quarter" ? "Weeks this quarter" : "Weeks"}>
        <WeekBars
          weeks={budget.weeks}
          school={line.source === "school" ? undefined : line.school_weekly}
          onPick={(week) => navigate(transactionsUrl({ start: week.start, end: week.end, counts: "Everyday" }))}
        />
      </Card>
    </>
  );
}

export function Budgets() {
  const { path, params } = useLocation();
  const period = params.get("period");
  const query = useQuery({
    queryKey: ["budget", period ?? ""],
    queryFn: () => get<Budget>(`/api/budget${period ? `?period=${encodeURIComponent(period)}` : ""}`),
    placeholderData: (previous) => previous,
  });
  const budget = query.data;
  const empty = useBootstrap().data?.transaction_count === 0;
  const loaded = Boolean(budget);

  // Once, when a link names a section; not again on every refetch.
  useEffect(() => {
    if (loaded && window.location.hash) {
      document.querySelector(window.location.hash)?.scrollIntoView({ block: "start" });
    }
  }, [loaded, path]);

  const tabs = <Tabs label="Budget" items={BUDGET_TABS} current={path} />;

  if (!budget) {
    return (
      <>
        <PageHead title="Budget" tabs={tabs} />
        {query.isError ? <LoadError what="the budget" error={query.error} retry={() => void query.refetch()} /> : <Loading />}
      </>
    );
  }

  function go(start: string | null) {
    if (!start || !budget) return;
    const current = budget.periods.find((item) => item.start <= budget.as_of && budget.as_of <= item.end);
    navigate(current?.start === start ? "/budgets" : `/budgets?period=${start}`, { replace: true });
  }

  const info = budget.period;
  return (
    <>
      <PageHead title="Budget" tabs={tabs}>
        {path === "/budgets" && !empty ? (
          <Stepper
            name="term"
            label={info.name}
            canPrevious={Boolean(info.previous)}
            canNext={Boolean(info.next) && (info.next ?? "") <= budget.as_of}
            onPrevious={() => go(info.previous)}
            onNext={() => go(info.next)}
          />
        ) : null}
      </PageHead>
      {path === "/budgets/year" ? (
        <SchoolYear budget={budget} empty={empty} />
      ) : path === "/budgets/setup" ? (
        <BudgetSetup budget={budget} />
      ) : empty ? (
        <Empty title="No spending yet">
          <Readout label="Weekly line" value={money(budget.line.weekly)} tone="amber" sub={<LineSource source={budget.line.source} />} />
          <div className="row">
            <button type="button" className="btn primary" onClick={() => openQuickAdd()}>
              + Add
            </button>
            <a className="btn" {...linkTo("/budgets/setup")}>
              Setup
            </a>
          </div>
        </Empty>
      ) : (
        <Term budget={budget} />
      )}
    </>
  );
}
