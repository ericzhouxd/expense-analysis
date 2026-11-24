import type { CSSProperties } from "react";

import type { AutoBudget, Budget, CoaLayer, CoaOutlook } from "../api";
import { money, wholeMoney } from "../lib/format";
import { LED } from "../lib/glyphs";
import { linkTo } from "../router";
import { LegendDot } from "./charts";
import { Spent } from "./budgetBits";
import { Band, Delta, Housing, Lamps, PaceMeter, Pips, Readout, Readouts } from "./instrument";
import { Card, Empty, Info } from "./ui";

/** From certain to guessed. */
const LAYERS: { key: CoaLayer; label: string; color: string }[] = [
  { key: "recorded", label: "Recorded", color: LED.accent },
  { key: "due", label: "Bills due", color: LED.blue },
  { key: "everyday", label: "Day-to-day", color: LED.amber },
  { key: "one_offs", label: "Big stuff", color: LED.violet },
  { key: "assumed", label: "Not recorded", color: LED.dim },
];
const SEGMENTS = 48;

type Ready = Extract<CoaOutlook, { ready: true }>;

/** The odds; the ends are capped because the model can't be that sure. */
function chanceText(chance: number): string {
  if (chance < 0.1) return "<10%";
  if (chance > 0.9) return ">90%";
  return `~${Math.round(chance * 20) * 5}%`;
}

/** The whole year as one row of segments colored by layer, with the cost of attendance and the likely range marked on it. */
function YearMeter({ coa }: { coa: Ready }) {
  const scale = Math.max(1, coa.line, coa.high, coa.projected) * 1.04;
  let reached = 0;
  const ends = LAYERS.map((layer) => {
    reached += Math.max(0, coa.layers[layer.key]);
    return { ...layer, end: reached };
  });
  const at = (cents: number) => Math.min(100, (cents / scale) * 100);
  return (
    <div className="year-meter">
      <div className="coa-mark" aria-hidden="true">
        <span style={{ right: `${100 - at(coa.line)}%` }}>
          {coa.school} {wholeMoney(coa.line)} ▼
        </span>
      </div>
      <div
        className="coa-meter"
        role="img"
        aria-label={`Expected ${money(coa.projected)} against a cost of attendance of ${money(coa.line)}. ${ends
          .map((layer) => `${layer.label} ${money(coa.layers[layer.key])}`)
          .join(", ")}.`}
      >
        <div className="segments" style={{ "--count": SEGMENTS } as CSSProperties}>
          {Array.from({ length: SEGMENTS }, (_, index) => {
            const middle = ((index + 0.5) / SEGMENTS) * scale;
            const layer = ends.find((item) => middle < item.end);
            return (
              <span
                key={index}
                className={`segment ${layer ? "tinted" : ""}`}
                style={layer ? ({ "--tint": layer.color } as CSSProperties) : undefined}
              />
            );
          })}
        </div>
        <span className="coa-line" style={{ left: `${at(coa.line)}%` }} aria-hidden="true" />
      </div>
      {coa.complete ? null : (
        <div className="coa-range" aria-hidden="true">
          <i style={{ left: `${at(coa.low)}%`, right: `${100 - at(coa.high)}%` }} />
        </div>
      )}
      <div className="legend">
        {ends
          .filter((layer) => coa.layers[layer.key] > 0)
          .map((layer) => (
            <LegendDot key={layer.key} color={layer.color}>
              {layer.label} <b>{wholeMoney(coa.layers[layer.key])}</b>
            </LegendDot>
          ))}
      </div>
    </div>
  );
}

function Outlook({ coa }: { coa: Ready }) {
  const tone = coa.verdict === "over" ? "coral" : coa.verdict === "under" ? "sage" : "amber";
  const hero = coa.verdict === "over" ? "over" : coa.verdict === "under" ? "accent" : "amber";
  const weekly = coa.weekly;
  return (
    <Housing label="Cost of attendance">
      <div className="hero-pair">
        <Spent
          whole
          live={!coa.complete}
          tone={hero}
          label={`${coa.margin >= 0 ? "Under" : "Over"} ${coa.school}`}
          cents={Math.abs(coa.margin)}
          comparison={
            <Lamps
              label="Verdict"
              value={coa.verdict}
              tone={tone}
              options={[
                { value: "under", label: "Under" },
                { value: "close", label: "Close" },
                { value: "over", label: "Over" },
              ]}
            />
          }
        />
        <Spent
          whole
          tone="plain"
          label={coa.complete ? "Year" : "Heading for"}
          cents={coa.projected}
          comparison={
            coa.complete ? null : <Band low={coa.low} at={coa.projected} high={coa.high} format={wholeMoney} />
          }
        />
      </div>
      {coa.complete ? null : (
        <Readouts>
          {weekly ? (
            <>
              <Readout label="Now / week" value={wholeMoney(weekly.typical)} tone="plain" />
              <Readout
                label="Max / week"
                value={wholeMoney(weekly.possible ? weekly.safe : 0)}
                tone={weekly.possible && weekly.safe >= weekly.typical ? "sage" : "coral"}
              />
              <Readout label="Weeks left" value={String(Math.round(weekly.weeks_left))} tone="plain" />
            </>
          ) : null}
          <Readout
            label="Odds over"
            value={chanceText(coa.chance)}
            tone={tone}
            sub={
              <Pips
                label={`Chance of going over ${chanceText(coa.chance)}`}
                pips={Array.from({ length: 10 }, (_, index) => (index < Math.round(coa.chance * 10) ? "up" : "off"))}
              />
            }
          />
        </Readouts>
      )}
      <YearMeter coa={coa} />
    </Housing>
  );
}

function Parts({ coa }: { coa: Ready }) {
  return (
    <Card
      title="By part"
      actions={
        coa.notes.length ? (
          <Info label="these figures">
            {coa.notes.map((note) => (
              <p key={note}>{note}</p>
            ))}
          </Info>
        ) : null
      }
    >
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Part</th>
              <th className="num wide-only">Recorded</th>
              <th className="num">Expected</th>
              <th className="num wide-only">{coa.school}</th>
              <th className="num">Difference</th>
            </tr>
          </thead>
          <tbody>
            {coa.parts.map((item) => (
              <tr key={item.part}>
                <td>
                  {item.part}
                  {item.assumed ? <span className="tag">{coa.school}</span> : null}
                </td>
                <td className="num muted wide-only">{wholeMoney(item.recorded)}</td>
                <td className="num">{wholeMoney(item.projected)}</td>
                <td className="num muted wide-only">{wholeMoney(item.published)}</td>
                <td className={`num ${item.difference < 0 ? "up" : item.difference > 0 ? "ok" : "dim"}`}>
                  {item.difference === 0 ? "=" : `${item.difference < 0 ? "▲" : "▼"} ${wholeMoney(Math.abs(item.difference))}`}
                </td>
              </tr>
            ))}
            {coa.adjustment ? (
              <tr className="wide-only">
                <td className="dim">{coa.own_total ? "Own total" : "Rounding"}</td>
                <td className="wide-only" />
                <td />
                <td className="num dim">{wholeMoney(coa.adjustment)}</td>
                <td />
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/** Everyday spending this school year against the school's estimate for as many weeks. */
function Everyday({ budget }: { budget: Budget }) {
  const { year, line } = budget;
  if (!year) return null;
  const under = year.estimate_to_date - year.spent;
  return (
    <Card title={`Everyday ${year.label}`} hint={`${year.weeks_done} / ${year.weeks} wk`}>
      <Readouts>
        <Readout label="Spent" value={money(year.spent)} sub={<Delta change={-under} than={line.school} />} />
        <Readout
          label={`${line.school} by today`}
          value={money(year.estimate_to_date)}
          tone="amber"
        />
        <Readout
          label={year.saved >= 0 ? "Year saved" : "Year over"}
          value={money(Math.abs(year.saved))}
          tone={year.saved >= 0 ? "sage" : "coral"}
        />
      </Readouts>
      <PaceMeter
        value={year.spent}
        capacity={Math.max(1, year.estimate)}
        pace={year.estimate_to_date}
        label={`${money(year.spent)} of ${line.school}'s ${money(year.estimate)} estimate`}
        mark="Today"
        cap={money(year.estimate)}
      />
    </Card>
  );
}

/** How the same method did at this point of earlier years, which is what its word is worth. */
function Record({ auto }: { auto: AutoBudget }) {
  if (!auto.record.length) return null;
  return (
    <Card title="Track record">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>School year</th>
              <th className="num">Said</th>
              <th className="num">Was</th>
              <th className="num">Off</th>
            </tr>
          </thead>
          <tbody>
            {auto.record.map((item) => (
              <tr key={item.label}>
                <td>{item.label}</td>
                <td className="num muted">{wholeMoney(item.projected)}</td>
                <td className="num">{wholeMoney(item.actual)}</td>
                <td className="num">{item.percent < 0.5 ? "<1%" : `${Math.round(item.percent)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/** Will everything this school year, tuition and rent included, pass UCLA's cost of attendance? */
export function SchoolYear({ budget, empty }: { budget: Budget; empty: boolean }) {
  const { coa, auto } = budget;
  return (
    <>
      {coa.ready ? (
        <>
          <Outlook coa={coa} />
          <Parts coa={coa} />
        </>
      ) : coa.reason === "profile" ? (
        <Empty title="Entry year and residency needed">
          <a className="btn" {...linkTo("/budgets/setup")}>
            Setup
          </a>
        </Empty>
      ) : (
        <Empty title={`No ${coa.school} figures for this date`} />
      )}
      {empty ? null : <Everyday budget={budget} />}
      <Record auto={auto} />
    </>
  );
}
