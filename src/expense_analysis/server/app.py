"""Local FastAPI app: a JSON API over the ledger plus the built web interface.

The server binds to 127.0.0.1 only (see ``main.py``). Two guards keep other
websites out even though the port is reachable from the browser:

* the ``Host`` header must name this machine, which defeats DNS rebinding;
* every state-changing API call must carry ``X-Jizhang: 1``. Browsers only send
  custom headers cross-origin after a CORS preflight, which this server never
  approves, so a page elsewhere cannot submit forms or fetches against the ledger.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..categories import delete_keyword_rules, effective_config, save_category, suggested_category
from ..choices import delete_choice, restore_choice, save_choice
from ..config import PROJECT_ROOT, AppConfig, load_config
from ..database import Database, DuplicateTransactionError
from ..import_export import SIGN_CONVENTIONS, CsvDecodeError, export_csv, preview_csv
from ..models import TransactionDraft, parse_date, validate_transaction_date
from ..spending_treatment import apply_transaction_treatment
from ..term_budget import Bill, BudgetSettings
from ..transaction_edits import TransactionChange, apply_changes
from . import views

WEB_DIST = PROJECT_ROOT / "web" / "dist"
FONTS_DIR = PROJECT_ROOT / "static" / "fonts"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "testserver"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
REQUEST_HEADER = "x-jizhang"
MAX_IMPORT_BYTES = 20 * 1024 * 1024
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; font-src 'self'; "
    "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


class DraftIn(BaseModel):
    transaction_date: str
    description: str
    amount_cents: int
    category: str = ""
    account: str = ""
    payment_method: str = ""
    merchant: str = ""
    transaction_type: str = "expense"
    notes: str = ""

    def draft(self, *, strict_date: bool = True) -> TransactionDraft:
        day = (
            validate_transaction_date(self.transaction_date)
            if strict_date
            else parse_date(self.transaction_date)
        )
        return TransactionDraft(
            transaction_date=day,
            description=self.description,
            amount_cents=self.amount_cents,
            category=self.category,
            account=self.account,
            payment_method=self.payment_method,
            merchant=self.merchant,
            transaction_type=self.transaction_type,
            notes=self.notes,
        ).validated()


class CreateIn(DraftIn):
    category_manual: bool = False
    allow_duplicate: bool = False


class EditIn(BaseModel):
    id: str
    before: DraftIn
    after: DraftIn | None = None


class BatchIn(BaseModel):
    changes: list[EditIn]


class IdsIn(BaseModel):
    ids: list[str]


class RestoreRow(DraftIn):
    id: str
    created_at: str | None = None


class RestoreIn(BaseModel):
    rows: list[RestoreRow]


class TreatmentIn(BaseModel):
    ids: list[str]
    treatment: str


class CategoryTreatmentsIn(BaseModel):
    categories: dict[str, str]


class ChoiceSaveIn(BaseModel):
    name: str
    source: str = ""
    spending_class: str = "Personal"
    keyword: str = ""


class ChoiceDeleteIn(BaseModel):
    source: str
    replacement: str = ""


class ChoiceRestoreIn(BaseModel):
    name: str
    spending_class: str | None = None


class KeywordRuleIn(BaseModel):
    keyword: str
    category: str


class KeywordDeleteIn(BaseModel):
    keywords: list[str]


class BillIn(BaseModel):
    name: str
    amount_cents: int = Field(ge=0)
    categories: list[str] = []
    cadence: str = "Monthly"
    due_day: int = 1
    due: str | None = None


class BudgetSettingsIn(BaseModel):
    housing: str = "Off-campus"
    weekly_cents: int | None = None
    bills: list[BillIn] = []


def _host_name(host: str) -> str:
    if host.startswith("["):
        return host[: host.find("]") + 1]
    return host.split(":", 1)[0]


def create_app(
    *,
    database: Database | None = None,
    config_loader: Callable[[], AppConfig] = load_config,
    today: Callable[[], date] = date.today,
    dist_dir: Path = WEB_DIST,
    fonts_dir: Path = FONTS_DIR,
) -> FastAPI:
    db = database or Database()
    db.initialize()
    app = FastAPI(title="記帳", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if _host_name(request.headers.get("host", "")) not in LOCAL_HOSTS:
            return JSONResponse({"detail": "This app only answers on 127.0.0.1."}, 403)
        if (
            request.url.path.startswith("/api/")
            and request.method not in SAFE_METHODS
            and request.headers.get(REQUEST_HEADER) != "1"
        ):
            return JSONResponse({"detail": "Missing the local request header."}, 403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DuplicateTransactionError)
    async def duplicate_error(_: Request, error: DuplicateTransactionError) -> JSONResponse:
        return JSONResponse({"detail": str(error), "code": "duplicate"}, 409)

    @app.exception_handler(ValueError)
    async def value_error(_: Request, error: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, 400)

    @app.exception_handler(sqlite3.Error)
    async def database_error(_: Request, __: sqlite3.Error) -> JSONResponse:
        return JSONResponse(
            {"detail": "Nothing was saved. The database could not complete the change."}, 500
        )

    def config() -> AppConfig:
        return effective_config(db, config_loader())

    def row_out(transaction_id: str) -> dict[str, Any]:
        row = db.get_transaction(transaction_id)
        if row is None:
            raise HTTPException(404, "Transaction not found")
        return views.serialize_row(row)

    api = APIRouter(prefix="/api")

    @api.get("/bootstrap")
    def bootstrap() -> dict[str, Any]:
        return views.bootstrap(db, config(), today())

    @api.get("/transactions")
    def transactions(
        request: Request, start: str | None = None, end: str | None = None, q: str = ""
    ) -> dict[str, Any]:
        params = request.query_params
        rows = db.list_transactions(
            start=date.fromisoformat(start) if start else None,
            end=date.fromisoformat(end) if end else None,
            categories=params.getlist("category"),
            transaction_types=params.getlist("type"),
            accounts=params.getlist("account"),
            search=q,
        )
        from ..spending_treatment import classify_spending

        classified = classify_spending(rows, db.get_budget_settings(), db.get_spending_rules())
        return {
            "rows": [views.serialize_row(row) for row in classified],
            "total": db.count_transactions(),
        }

    @api.post("/transactions", status_code=201)
    def create_transaction(body: CreateIn) -> dict[str, Any]:
        settings = config()
        draft = body.draft()
        if not body.category_manual or not body.category.strip():
            category = suggested_category(db, settings, body.description, body.merchant)
            draft = TransactionDraft(**{**draft.__dict__, "category": category}).validated()
        transaction_id = db.add_transaction(draft, allow_duplicate=body.allow_duplicate)
        return row_out(transaction_id)

    @api.post("/transactions/edit")
    def edit_transaction(body: EditIn) -> dict[str, Any]:
        apply_changes(
            db,
            [
                TransactionChange(
                    body.id,
                    body.before.draft(strict_date=False),
                    body.after.draft() if body.after else None,
                )
            ],
        )
        return row_out(body.id) if body.after else {"deleted": body.id}

    @api.post("/transactions/batch")
    def batch(body: BatchIn) -> dict[str, Any]:
        apply_changes(
            db,
            [
                TransactionChange(
                    change.id,
                    change.before.draft(strict_date=False),
                    change.after.draft() if change.after else None,
                )
                for change in body.changes
            ],
        )
        return {"saved": len(body.changes)}

    @api.post("/transactions/delete")
    def delete(body: IdsIn) -> dict[str, Any]:
        rows = [row for row in (db.get_transaction(i) for i in body.ids) if row]
        deleted = db.delete_transactions([str(row["id"]) for row in rows])
        return {"deleted": deleted, "rows": [views.serialize_row(row) for row in rows]}

    @api.post("/transactions/restore")
    def restore(body: RestoreIn) -> dict[str, Any]:
        restored = db.restore_transactions(
            (row.id, row.created_at or "", row.draft(strict_date=False)) for row in body.rows
        )
        return {"restored": restored}

    @api.get("/overview")
    def overview(month: str | None = None, scope: str = "everyday") -> dict[str, Any]:
        return views.overview(db, config(), month=month, scope=scope, today=today())

    @api.get("/insights")
    def insights(month: str | None = None, scope: str = "everyday") -> dict[str, Any]:
        return views.insights(db, config(), month=month, scope=scope, today=today())

    @api.get("/budget")
    def budget(period: str | None = None) -> dict[str, Any]:
        return views.budget(db, config(), today=today(), period=period)

    @api.put("/budget/settings")
    def save_budget_settings(body: BudgetSettingsIn) -> dict[str, Any]:
        settings = BudgetSettings(
            housing=body.housing,
            weekly_cents=body.weekly_cents or None,
            bills=tuple(
                Bill(
                    name=item.name.strip(),
                    amount_cents=item.amount_cents,
                    categories=tuple(c.strip() for c in item.categories if c.strip()),
                    cadence=item.cadence,
                    due_day=item.due_day,
                    due=date.fromisoformat(item.due) if item.due else None,
                )
                for item in body.bills
            ),
        ).validate()
        db.save_budget_settings(settings)
        return {"saved": True}

    @api.put("/spending-rules/categories")
    def save_category_treatments(body: CategoryTreatmentsIn) -> dict[str, Any]:
        rules = db.get_spending_rules()
        rules["categories"] = dict(body.categories)
        db.save_spending_rules(rules)
        return {"saved": len(body.categories)}

    @api.post("/spending-rules/transactions")
    def save_transaction_treatments(body: TreatmentIn) -> dict[str, Any]:
        rules = apply_transaction_treatment(db.get_spending_rules(), body.ids, body.treatment)
        db.save_spending_rules(rules)
        return {"saved": len(body.ids)}

    @api.get("/choices")
    def list_choices() -> dict[str, Any]:
        return views.choices(db, config())

    @api.get("/choices/{kind}/usage")
    def choice_usage(kind: str, name: str) -> dict[str, Any]:
        return views.choice_usage(db, config(), kind, name)

    @api.post("/choices/{kind}/save")
    def choice_save(kind: str, body: ChoiceSaveIn) -> dict[str, Any]:
        settings = config()
        if kind == "category":
            changed = save_category(
                db,
                settings,
                body.name,
                body.spending_class,
                source=body.source,
                keyword=body.keyword,
            )
        elif kind in ("account", "payment_method"):
            changed = save_choice(db, settings, kind, body.name, source=body.source)
        else:
            raise ValueError("This field uses fixed choices")
        return {"changed": changed}

    @api.post("/choices/{kind}/delete")
    def choice_delete(kind: str, body: ChoiceDeleteIn) -> dict[str, Any]:
        settings = config()
        spending_class = settings.spending_class(body.source) if kind == "category" else None
        delete_choice(db, settings, kind, body.source, replacement=body.replacement)
        return {
            "removed": body.source,
            "replacement": body.replacement,
            "undo": None
            if body.replacement
            else {"kind": kind, "name": body.source, "spending_class": spending_class},
        }

    @api.post("/choices/{kind}/restore")
    def choice_restore(kind: str, body: ChoiceRestoreIn) -> dict[str, Any]:
        if kind not in views.CHOICE_KINDS:
            raise ValueError("This field uses fixed choices")
        restore_choice(db, kind, body.name, body.spending_class)
        return {"restored": body.name}

    @api.post("/keyword-rules")
    def add_keyword_rule(body: KeywordRuleIn) -> dict[str, Any]:
        settings = config()
        if not body.keyword.strip():
            raise ValueError("Enter a keyword or phrase.")
        if body.category not in settings.categories or body.category == "Uncategorized":
            raise ValueError("Choose an existing named category.")
        save_category(
            db,
            settings,
            body.category,
            "Fixed" if settings.spending_class(body.category) == "Fixed" else "Personal",
            keyword=body.keyword,
        )
        return {"saved": True}

    @api.post("/keyword-rules/delete")
    def remove_keyword_rules(body: KeywordDeleteIn) -> dict[str, Any]:
        if not body.keywords:
            raise ValueError("Choose at least one rule to remove.")
        delete_keyword_rules(db, body.keywords)
        return {"removed": len(body.keywords)}

    async def _import_preview(request: Request, sign: str, mapping: str) -> tuple[Any, Any, Any]:
        content = await request.body()
        if not content:
            raise ValueError("Choose a CSV file first.")
        if len(content) > MAX_IMPORT_BYTES:
            raise ValueError("This file is larger than 20 MB. Split it and import each part.")
        if sign not in SIGN_CONVENTIONS:
            raise ValueError("Choose how amounts are signed.")
        try:
            category_mapping = {str(k): str(v) for k, v in json.loads(mapping or "{}").items()}
        except (json.JSONDecodeError, AttributeError) as error:
            raise ValueError("The category mapping could not be read.") from error
        settings = config()
        try:
            unknown = views.unknown_import_categories(content, settings)
            from ..categories import suggestion_data

            preview = preview_csv(
                content,
                settings,
                db.existing_fingerprints(),
                category_mapping,
                suggestion_data(db, settings)["merchants"],
                sign_convention=sign,
            )
        except CsvDecodeError as error:
            raise ValueError(str(error)) from error
        return preview, unknown, settings

    @api.post("/import/preview")
    async def import_preview(
        request: Request, sign: str = "positive_expense", mapping: str = "{}"
    ) -> dict[str, Any]:
        preview, unknown, settings = await _import_preview(request, sign, mapping)
        return views.import_preview(preview, unknown, settings)

    @api.post("/import/commit")
    async def import_commit(
        request: Request, sign: str = "positive_expense", mapping: str = "{}"
    ) -> dict[str, Any]:
        preview, _, _ = await _import_preview(request, sign, mapping)
        result = db.import_transactions(preview.valid_drafts)
        return {"imported": result.imported, "duplicates_skipped": result.duplicates_skipped}

    @api.get("/export.csv")
    def export() -> Response:
        filename = f"expenses-{today().isoformat()}.csv"
        return Response(
            export_csv(db.list_transactions()),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @api.get("/settings")
    def settings() -> dict[str, Any]:
        return views.settings(db, config())

    app.include_router(api)

    if fonts_dir.is_dir():
        app.mount("/fonts", StaticFiles(directory=fonts_dir), name="fonts")
    index = dist_dir / "index.html"
    if (dist_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = (dist_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist_dir.resolve()):
            return FileResponse(candidate)
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><title>記帳</title>"
            "<body style='font:16px monospace;background:#0B0D0A;color:#E9ECE3;padding:40px'>"
            "<h1>The web interface has not been built yet.</h1>"
            "<p>Run <code>npm --prefix web ci &amp;&amp; npm --prefix web run build</code>, "
            "then reload this page.</p></body>",
            status_code=503,
        )

    return app
