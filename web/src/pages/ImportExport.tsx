import { useEffect, useRef, useState } from "react";

import { type ImportPreview, postBytes } from "../api";
import { linkTo } from "../App";
import { useToast } from "../components/feedback";
import { Card, Readout, Segmented } from "../components/instrument";
import { money, plural, shortDate } from "../lib/format";
import { useBootstrap, useRefresh } from "../queries";

type Sign = "positive_expense" | "negative_expense_refund" | "negative_expense_income";
type Show = "all" | "ready" | "duplicate" | "invalid";

const SIGNS: { value: Sign; label: string; hint: string }[] = [
  { value: "positive_expense", label: "Purchases are positive", hint: "negative rows become refunds" },
  { value: "negative_expense_refund", label: "Purchases are negative", hint: "positive rows become refunds" },
  { value: "negative_expense_income", label: "Bank account export", hint: "negative = spent, positive = income" },
];

const MAX_BYTES = 20 * 1024 * 1024;

export function ImportExport() {
  const toast = useToast();
  const refresh = useRefresh();
  const bootstrap = useBootstrap();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<{ name: string; bytes: ArrayBuffer } | null>(null);
  const [sign, setSign] = useState<Sign>("positive_expense");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [show, setShow] = useState<Show>("all");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  function query(): string {
    return new URLSearchParams({ sign, mapping: JSON.stringify(mapping) }).toString();
  }

  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    setBusy(true);
    setProblem("");
    postBytes<ImportPreview>(`/api/import/preview?${query()}`, file.bytes)
      .then((result) => {
        if (!cancelled) setPreview(result);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setPreview(null);
          setProblem(error instanceof Error ? error.message : "Could not read this file.");
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file, sign, JSON.stringify(mapping)]);

  async function choose(chosen: File | undefined) {
    if (!chosen) return;
    if (chosen.size > MAX_BYTES) {
      setProblem("This file is larger than 20 MB. Split it and import each part.");
      return;
    }
    setMapping({});
    setShow("all");
    setFile({ name: chosen.name, bytes: await chosen.arrayBuffer() });
  }

  async function commit() {
    if (!file || !preview?.ready) return;
    setBusy(true);
    try {
      const result = await postBytes<{ imported: number; duplicates_skipped: number }>(
        `/api/import/commit?${query()}`,
        file.bytes,
      );
      await refresh();
      toast.show(
        `Imported ${plural(result.imported, "transaction")}${result.duplicates_skipped ? `, skipped ${result.duplicates_skipped} already saved` : ""}.`,
      );
      setFile(null);
      setPreview(null);
    } catch (error) {
      toast.error(error);
    } finally {
      setBusy(false);
    }
  }

  const rows = preview ? preview.rows.filter((row) => show === "all" || row.status === show) : [];
  const count = bootstrap.data?.transaction_count ?? 0;

  return (
    <div className="stack loose">
      <div className="page-head">
        <div>
          <h1>Import / Export</h1>
        </div>
      </div>

      <Card title="Import a CSV" hint="nothing is saved until you press Import">
        <div
          className={`dropzone ${over ? "over" : ""}`}
          role="button"
          tabIndex={0}
          aria-label="Choose a CSV file"
          onClick={() => input.current?.click()}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              input.current?.click();
            }
          }}
          onDragOver={(event) => {
            event.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setOver(false);
            void choose(event.dataTransfer.files[0]);
          }}
        >
          <span style={{ fontSize: 28, color: "var(--accent)", textShadow: "0 0 12px var(--accent)" }} aria-hidden="true">
            ⇣
          </span>
          <span>{file ? file.name : "Drop a CSV here or click to choose"}</span>
          <span className="tiny dim">Needs date, description and amount columns · up to 20 MB</span>
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            hidden
            onChange={(event) => {
              void choose(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </div>

        <div className="stack tight">
          <span className="label">How are amounts signed?</span>
          <Segmented<Sign> label="Amount signs" value={sign} onChange={setSign} options={SIGNS} />
          <span className="tiny dim">{SIGNS.find((item) => item.value === sign)?.hint}</span>
        </div>

        {problem ? (
          <div className="signal up" role="alert">
            <span className="mark">▲</span>
            <span className="grow">{problem}</span>
          </div>
        ) : null}

        {preview?.unknown_categories.length ? (
          <div className="stack tight">
            <span className="label">Match these categories from the file</span>
            <div className="form-grid">
              {preview.unknown_categories.map((label) => (
                <label key={label} className="field">
                  <span>{label}</span>
                  <select
                    value={mapping[label] ?? ""}
                    onChange={(event) => setMapping((current) => ({ ...current, [label]: event.target.value }))}
                  >
                    <option value="">Suggest from description</option>
                    {preview.category_options.map((option) => (
                      <option key={option}>{option}</option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          </div>
        ) : null}

        {preview ? (
          <>
            <div className="readouts" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))" }}>
              <Readout label="Ready" value={String(preview.ready)} tone="sage" />
              <Readout label="Already saved" value={String(preview.duplicates)} tone="text" />
              <Readout label="Can't read" value={String(preview.invalid)} tone={preview.invalid ? "coral" : "text"} />
            </div>
            <div className="row between">
              <Segmented<Show>
                label="Show rows"
                value={show}
                onChange={setShow}
                options={[
                  { value: "all", label: "All" },
                  { value: "ready", label: "Ready" },
                  { value: "duplicate", label: "Duplicates" },
                  { value: "invalid", label: "Problems" },
                ]}
              />
              <button type="button" className="btn primary" disabled={busy || !preview.ready} onClick={() => void commit()}>
                Import {plural(preview.ready, "row")}
              </button>
            </div>
            <div className="table-wrap" style={{ maxHeight: 460, overflowY: "auto" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Date</th>
                    <th>Description</th>
                    <th>Category</th>
                    <th>Type</th>
                    <th className="num">Amount</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 500).map((row) => (
                    <tr key={row.row}>
                      <td className="dim small">{row.row}</td>
                      <td className="small">{row.date ? shortDate(row.date) : "—"}</td>
                      <td>{row.description || <span className="dim">—</span>}</td>
                      <td className="small">{row.category}</td>
                      <td className="small">{row.type}</td>
                      <td className="num">{row.amount_cents === null ? "—" : money(row.amount_cents)}</td>
                      <td>
                        {row.status === "ready" ? (
                          <span className="tag lime">ready</span>
                        ) : row.status === "duplicate" ? (
                          <span className="tag">already saved</span>
                        ) : (
                          <span className="tag coral" title={row.issue}>
                            {row.issue || "invalid"}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {rows.length > 500 ? <span className="tiny dim">Showing the first 500 of {rows.length}.</span> : null}
          </>
        ) : busy ? (
          <p className="muted">Reading the file…</p>
        ) : null}
      </Card>

      <Card title="Export" hint={plural(count, "transaction")}>
        <p className="muted small" style={{ margin: 0 }}>
          One CSV with every transaction. It re-imports cleanly here and opens in any spreadsheet.
        </p>
        <div className="row">
          <a className="btn" href="/api/export.csv" download aria-disabled={!count}>
            Download CSV
          </a>
          <a className="link small" {...linkTo("/settings")}>
            Where the data lives →
          </a>
        </div>
      </Card>
    </div>
  );
}
