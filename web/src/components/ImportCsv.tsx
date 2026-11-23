import { useEffect, useRef, useState } from "react";

import { type ImportPreview, postBytes } from "../api";
import { money, plural, shortDate } from "../lib/format";
import { useRefresh } from "../queries";
import { linkTo } from "../router";
import { useToast } from "./feedback";
import { Icon } from "./icons";
import { namesOf, Select } from "./pickers";
import { Card, Loading, Notice, Segmented } from "./ui";

type Sign = "positive_expense" | "negative_expense_refund" | "negative_expense_income";
type Show = "all" | "ready" | "duplicate" | "invalid";

const SIGNS: { value: Sign; label: string }[] = [
  { value: "positive_expense", label: "Purchases are positive, refunds negative" },
  { value: "negative_expense_refund", label: "Purchases are negative, refunds positive" },
  { value: "negative_expense_income", label: "Bank account: spending negative, income positive" },
];

const MAX_BYTES = 20 * 1024 * 1024;

/** Read a CSV, show what each row would become, and save only when asked. */
export function ImportCsv() {
  const toast = useToast();
  const refresh = useRefresh();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<{ name: string; bytes: ArrayBuffer } | null>(null);
  const [sign, setSign] = useState<Sign>("positive_expense");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [show, setShow] = useState<Show>("all");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [imported, setImported] = useState("");

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

  function clear() {
    setFile(null);
    setPreview(null);
    setProblem("");
    setMapping({});
    setShow("all");
  }

  async function choose(chosen: File | undefined) {
    if (!chosen) return;
    clear();
    setImported("");
    if (chosen.size > MAX_BYTES) {
      setProblem("This file is larger than 20 MB. Split it and import each part.");
      return;
    }
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
      setImported(
        `Imported ${plural(result.imported, "transaction")}${
          result.duplicates_skipped ? `, skipped ${result.duplicates_skipped} already saved` : ""
        }.`,
      );
      clear();
    } catch (error) {
      toast.error(error);
    } finally {
      setBusy(false);
    }
  }

  const rows = preview ? preview.rows.filter((row) => show === "all" || row.status === show) : [];
  const views = preview
    ? (
        [
          ["all", "All", preview.rows.length],
          ["ready", "Ready", preview.ready],
          ["duplicate", "Already saved", preview.duplicates],
          ["invalid", "Problems", preview.invalid],
        ] as const
      ).filter(([value, , count]) => value === "all" || count > 0)
    : [];

  return (
    <Card title="Import a CSV">
      <div
        className={`dropzone ${over ? "over" : ""} ${file ? "chosen" : ""}`}
        role="button"
        tabIndex={0}
        aria-label={file ? `${file.name}. Choose another CSV file` : "Choose a CSV file"}
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
        <Icon name="upload" size={24} />
        <span className="lines">
          <span className="title">{file ? file.name : "Drop a CSV"}</span>
          {file ? null : (
            <span className="row columns" aria-label="Columns it needs">
              {["Date", "Description", "Amount"].map((name) => (
                <span key={name} className="tag">
                  {name}
                </span>
              ))}
            </span>
          )}
        </span>
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          hidden
          onClick={(event) => event.stopPropagation()}
          onChange={(event) => {
            void choose(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </div>

      {problem ? (
        <Notice tone="up" role="alert">
          {problem}
        </Notice>
      ) : null}
      {imported ? (
        <Notice
          tone="ok"
          role="status"
          action={
            <a className="link small" {...linkTo("/transactions")}>
              See transactions →
            </a>
          }
        >
          {imported}
        </Notice>
      ) : null}

      {file ? (
        <div className="form-grid import-options">
          <Select
            label="How amounts are written"
            value={sign}
            options={SIGNS}
            onChange={(value) => setSign(value as Sign)}
          />
          {preview?.unknown_categories.map((name) => (
            <Select
              key={name}
              label={`“${name}” in the file becomes`}
              value={mapping[name] ?? ""}
              options={[
                { value: "", label: "Suggest from description" },
                ...namesOf(preview.category_options, true),
              ]}
              onChange={(value) => setMapping((current) => ({ ...current, [name]: value }))}
            />
          ))}
        </div>
      ) : null}

      {preview ? (
        <>
          <div className="row between">
            <Segmented<Show>
              label="Show rows"
              value={show}
              onChange={setShow}
              options={views.map(([value, label, count]) => ({ value, label: `${label} ${count}` }))}
            />
            <div className="row">
              <button type="button" className="btn ghost" onClick={clear}>
                Cancel
              </button>
              <button
                type="button"
                className="btn primary"
                disabled={busy || !preview.ready}
                onClick={() => void commit()}
              >
                Import {plural(preview.ready, "row")}
              </button>
            </div>
          </div>
          <div className="table-wrap preview">
            <table className="table sticky">
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
                  <tr key={row.row} className={row.status === "duplicate" ? "dim" : ""}>
                    <td className="dim">{row.row}</td>
                    <td className="nowrap">{row.date ? shortDate(row.date) : "—"}</td>
                    <td>{row.description || <span className="dim">—</span>}</td>
                    <td>{row.category}</td>
                    <td className="muted">{row.type}</td>
                    <td className="num">{row.amount_cents === null ? "—" : money(row.amount_cents)}</td>
                    <td>
                      {row.status === "ready" ? (
                        <span className="dim">Ready</span>
                      ) : row.status === "duplicate" ? (
                        <span className="tag">Already saved</span>
                      ) : (
                        <span className="up">{row.issue || "Can't be read"}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length > 500 ? <span className="small dim">500 / {rows.length}</span> : null}
        </>
      ) : busy ? (
        <Loading />
      ) : null}
    </Card>
  );
}
