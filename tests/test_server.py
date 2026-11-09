"""The local web API, exercised against temporary synthetic ledgers only."""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from expense_analysis.config import AppConfig
from expense_analysis.database import Database
from expense_analysis.models import TransactionDraft
from expense_analysis.server import create_app
from expense_analysis.term_budget import Bill, BudgetSettings

TODAY = date(2026, 11, 9)
HEADERS = {"X-Jizhang": "1"}


def _draft(day: date, description: str, cents: int, category: str, **extra) -> TransactionDraft:
    return TransactionDraft(day, description, cents, category, account="Checking", **extra)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "ledger.sqlite3")
    db.initialize()
    return db


@pytest.fixture
def client(database: Database, tmp_path: Path) -> TestClient:
    app = create_app(
        database=database,
        config_loader=AppConfig,
        today=lambda: TODAY,
        dist_dir=tmp_path / "no-dist",
    )
    return TestClient(app)


@pytest.fixture
def seeded(database: Database) -> Database:
    rows = [
        _draft(date(2026, 10, 2), "Ralphs groceries", 40_00, "Food", merchant="Ralphs"),
        _draft(date(2026, 10, 5), "Chipotle lunch", 12_00, "Dining Out", merchant="Chipotle"),
        _draft(date(2026, 11, 1), "Ralphs groceries", 18_40, "Food", merchant="Ralphs"),
        _draft(date(2026, 11, 3), "Metro card", 46_20, "Transportation"),
        _draft(date(2026, 11, 9), "Chipotle lunch", 12_85, "Dining Out", merchant="Chipotle"),
        _draft(date(2026, 11, 9), "Target", 16_40, "Daily Necessities", merchant="Target"),
        _draft(
            date(2026, 11, 9),
            "Target return",
            4_00,
            "Daily Necessities",
            merchant="Target",
            transaction_type="refund",
        ),
        _draft(date(2026, 11, 2), "Phone bill", 35_00, "Cell Phone"),
    ]
    for row in rows:
        database.add_transaction(row)
    database.save_budget_settings(
        BudgetSettings(
            weekly_cents=100_00,
            bills=(Bill("Phone", 35_00, ("Cell Phone",), "Monthly", due_day=2),),
        )
    )
    return database


def _create(client: TestClient, **fields) -> dict:
    body = {
        "transaction_date": "2026-11-09",
        "description": "Blue Bottle coffee",
        "amount_cents": 6_50,
        "account": "Checking",
        "payment_method": "Apple Pay",
        **fields,
    }
    response = client.post("/api/transactions", json=body, headers=HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def test_writes_need_the_local_header(client: TestClient) -> None:
    response = client.post("/api/transactions", json={})
    assert response.status_code == 403
    assert client.get("/api/bootstrap").status_code == 200


def test_foreign_hosts_are_refused(client: TestClient) -> None:
    response = client.get("/api/bootstrap", headers={"Host": "attacker.example:8765"})
    assert response.status_code == 403
    allowed = client.get("/api/bootstrap", headers={"Host": "127.0.0.1:8765"})
    assert allowed.status_code == 200
    assert "frame-ancestors 'none'" in allowed.headers["content-security-policy"]
    assert allowed.headers["cache-control"] == "no-store"


def test_create_suggests_a_category_unless_chosen(client: TestClient) -> None:
    assert _create(client)["category"] == "Dining Out"
    manual = _create(client, description="Coffee beans", category="Food", category_manual=True)
    assert manual["category"] == "Food"


def test_duplicates_conflict_until_confirmed(client: TestClient) -> None:
    _create(client)
    body = {
        "transaction_date": "2026-11-09",
        "description": "Blue Bottle coffee",
        "amount_cents": 6_50,
        "account": "Checking",
        "payment_method": "Apple Pay",
    }
    duplicate = client.post("/api/transactions", json=body, headers=HEADERS)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "duplicate"
    again = client.post(
        "/api/transactions", json={**body, "allow_duplicate": True}, headers=HEADERS
    )
    assert again.status_code == 201


def test_invalid_entries_explain_the_problem(client: TestClient) -> None:
    response = client.post(
        "/api/transactions",
        json={"transaction_date": "2026-11-09", "description": " ", "amount_cents": 100},
        headers=HEADERS,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Description is required"


def test_edit_checks_the_row_was_not_changed_elsewhere(client: TestClient) -> None:
    row = _create(client)
    before = {key: row[key] for key in _draft_keys()}
    after = {**before, "amount_cents": 7_25, "notes": "oat milk"}
    edited = client.post(
        "/api/transactions/edit",
        json={"id": row["id"], "before": before, "after": after},
        headers=HEADERS,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["amount_cents"] == 7_25
    stale = client.post(
        "/api/transactions/edit",
        json={"id": row["id"], "before": before, "after": {**before, "notes": "again"}},
        headers=HEADERS,
    )
    assert stale.status_code == 400
    assert "changed elsewhere" in stale.json()["detail"]


def _draft_keys() -> tuple[str, ...]:
    return (
        "transaction_date",
        "description",
        "amount_cents",
        "category",
        "account",
        "payment_method",
        "merchant",
        "transaction_type",
        "notes",
    )


def test_delete_returns_rows_that_undo_restores(client: TestClient, database: Database) -> None:
    row = _create(client)
    deleted = client.post("/api/transactions/delete", json={"ids": [row["id"]]}, headers=HEADERS)
    assert deleted.json()["deleted"] == 1
    assert database.count_transactions() == 0
    restored = client.post(
        "/api/transactions/restore", json={"rows": deleted.json()["rows"]}, headers=HEADERS
    )
    assert restored.json()["restored"] == 1
    restored_row = database.get_transaction(row["id"])
    assert restored_row is not None
    assert restored_row["created_at"] == row["created_at"]
    repeat = client.post(
        "/api/transactions/restore", json={"rows": deleted.json()["rows"]}, headers=HEADERS
    )
    assert repeat.json()["restored"] == 0


def test_transaction_filters_and_amount_search(client: TestClient, seeded: Database) -> None:
    rows = client.get("/api/transactions", params={"q": "12.85"}).json()["rows"]
    assert [row["description"] for row in rows] == ["Chipotle lunch"]
    food = client.get(
        "/api/transactions", params=[("category", "Food"), ("start", "2026-11-01")]
    ).json()["rows"]
    assert [row["amount_cents"] for row in food] == [18_40]
    assert food[0]["spending_treatment"] == "Everyday"


def test_overview_shows_this_weeks_line_and_the_month(client: TestClient, seeded: Database) -> None:
    data = client.get("/api/overview").json()
    assert data["month"] == "2026-11"
    assert len(data["days"]) == 30
    assert data["days"][8] == {"date": "2026-11-09", "spent": 25_25, "count": 3, "future": False}
    assert data["days"][9]["future"] is True
    budget = data["budget"]
    assert budget["period"] == "Fall quarter 2026"
    week = budget["week"]
    assert week["label"] == "Week 7"
    assert week["line"] == 100_00
    assert week["spent"] == 12_85 + 16_40 - 4_00
    assert week["left"] == 100_00 - week["spent"]
    assert week["days_left"] == 7
    assert week["pace"] == round(100_00 / 7)
    # Phone is a commitment, so the everyday view leaves it out.
    assert data["spent"] == 18_40 + 46_20 + 12_85 + 16_40 - 4_00
    assert [c["category"] for c in data["categories"]][0] == "Transportation"
    assert data["ticker"]["label"] == "TODAY"
    assert data["ticker"]["total"] == 12_85 + 16_40 - 4_00
    phone = next(b for b in data["bills"] if b["due"] == "2026-11-02")
    assert phone["name"] == "Phone"
    assert phone["status"] == "paid"
    assert any("vs Oct 1–9" in signal["text"] for signal in data["signals"])
    every = client.get("/api/overview", params={"scope": "all"}).json()
    assert every["spent"] == data["spent"] + 35_00


def test_overview_of_a_past_month_has_no_weekly_line(client: TestClient, seeded: Database) -> None:
    data = client.get("/api/overview", params={"month": "2026-10"}).json()
    assert data["is_current"] is False
    assert data["as_of"] == "2026-10-31"
    assert data["budget"] is None
    assert data["ticker"]["label"] == "LATEST"


def test_empty_ledger_overview_is_predictable(client: TestClient) -> None:
    data = client.get("/api/overview").json()
    assert data["has_transactions"] is False
    # The school's estimate works before any setup.
    assert data["budget"]["source"] == "school"
    assert data["budget"]["week"]["spent"] == 0
    assert data["categories"] == []
    assert data["monthly"] == []


def test_insights_and_budget_payloads(client: TestClient, seeded: Database) -> None:
    insights = client.get("/api/insights").json()
    assert insights["cash_flow"][-1]["month"] == "2026-11"
    assert insights["year"]["label"] == "2026–27"
    assert insights["terms"][-1]["period"] == "Fall quarter 2026"
    budget = client.get("/api/budget").json()
    assert budget["period"]["name"] == "Fall quarter 2026"
    assert budget["period"]["is_current"] is True
    assert [w["label"] for w in budget["weeks"]][:2] == ["Week 0", "Week 1"]
    assert budget["week"]["label"] == "Week 7"
    assert budget["line"]["source"] == "own"
    assert budget["saved_settings"] is True
    assert {p["name"] for p in budget["periods"]} >= {"Fall quarter 2026", "Summer 2026"}
    earlier = client.get("/api/budget", params={"period": budget["period"]["previous"]}).json()
    assert earlier["period"]["name"] == "Summer 2026"
    assert earlier["week"] is None


def test_budget_settings_save_and_validate(client: TestClient, database: Database) -> None:
    empty = client.get("/api/budget").json()
    assert empty["saved_settings"] is False
    assert empty["line"]["source"] == "school"
    assert "Off-campus" in empty["housing_options"]
    body = {
        "housing": "On-campus",
        "weekly_cents": None,
        "bills": [
            {"name": "Rent", "amount_cents": 1450_00, "categories": ["Rent"], "due_day": 1},
            {"name": "Books", "amount_cents": 200_00, "cadence": "Once", "due": "2027-01-04"},
        ],
    }
    saved = client.put("/api/budget/settings", json=body, headers=HEADERS)
    assert saved.status_code == 200, saved.text
    settings = database.get_budget_settings()
    assert settings is not None
    assert settings.housing == "On-campus"
    assert [b.name for b in settings.bills] == ["Rent", "Books"]
    bad = client.put(
        "/api/budget/settings",
        json={**body, "bills": [{"name": "X", "amount_cents": 1, "cadence": "Once"}]},
        headers=HEADERS,
    )
    assert bad.status_code == 400


def test_transaction_treatment_exceptions(client: TestClient, seeded: Database) -> None:
    metro = next(r for r in seeded.list_transactions() if r["description"] == "Metro card")
    response = client.post(
        "/api/spending-rules/transactions",
        json={"ids": [metro["id"]], "treatment": "Irregular"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    rows = client.get("/api/transactions", params={"q": "Metro"}).json()["rows"]
    assert rows[0]["spending_treatment"] == "Irregular"
    nothing = client.post(
        "/api/spending-rules/transactions",
        json={"ids": [], "treatment": "Irregular"},
        headers=HEADERS,
    )
    assert nothing.status_code == 400


def test_choices_rename_remove_and_restore(client: TestClient, seeded: Database) -> None:
    listed = client.get("/api/choices").json()
    cash = next(item for item in listed["account"] if item["name"] == "Cash")
    assert cash["unused"] is True
    removed = client.post(
        "/api/choices/account/delete", json={"source": "Cash"}, headers=HEADERS
    ).json()
    assert removed["undo"] == {"kind": "account", "name": "Cash", "spending_class": None}
    names = [item["name"] for item in client.get("/api/choices").json()["account"]]
    assert "Cash" not in names
    client.post("/api/choices/account/restore", json={"name": "Cash"}, headers=HEADERS)
    names = [item["name"] for item in client.get("/api/choices").json()["account"]]
    assert "Cash" in names
    usage = client.get("/api/choices/account/usage", params={"name": "Checking"}).json()
    assert usage["count"] == 8
    assert usage["unused"] is False
    renamed = client.post(
        "/api/choices/account/save",
        json={"name": "Everyday Checking", "source": "Checking"},
        headers=HEADERS,
    )
    assert renamed.json()["changed"] == 8


def test_keyword_rules_round_trip(client: TestClient) -> None:
    added = client.post(
        "/api/keyword-rules", json={"keyword": "Trader Joe", "category": "Food"}, headers=HEADERS
    )
    assert added.status_code == 200
    rules = client.get("/api/choices").json()["keyword_rules"]
    assert {"keyword": "trader joe", "category": "Food", "source": "Settings"} in rules
    assert _create(client, description="Trader Joe's run")["category"] == "Food"
    client.post("/api/keyword-rules/delete", json={"keywords": ["trader joe"]}, headers=HEADERS)
    assert client.get("/api/choices").json()["keyword_rules"] == []


def _csv(rows: list[list[str]]) -> bytes:
    output = io.StringIO()
    csv.writer(output).writerows(rows)
    return output.getvalue().encode()


def test_import_preview_mapping_and_commit(client: TestClient, database: Database) -> None:
    content = _csv(
        [
            ["Date", "Description", "Amount", "Category"],
            ["2026-11-02", "Corner store", "-8.50", "Snacks"],
            ["2026-11-03", "Paycheck", "500", ""],
            ["not a date", "Broken", "3", ""],
        ]
    )
    preview = client.post(
        "/api/import/preview",
        params={"sign": "negative_expense_income"},
        content=content,
        headers=HEADERS,
    ).json()
    assert preview["unknown_categories"] == ["Snacks"]
    assert (preview["ready"], preview["invalid"]) == (2, 1)
    assert [row["type"] for row in preview["rows"][:2]] == ["expense", "income"]
    committed = client.post(
        "/api/import/commit",
        params={"sign": "negative_expense_income", "mapping": '{"Snacks": "Food"}'},
        content=content,
        headers=HEADERS,
    ).json()
    assert committed == {"imported": 2, "duplicates_skipped": 0}
    categories = {row["description"]: row["category"] for row in database.list_transactions()}
    assert categories["Corner store"] == "Food"


def test_import_rejects_binary_files(client: TestClient) -> None:
    response = client.post("/api/import/preview", content=b"\x00\x01", headers=HEADERS)
    assert response.status_code == 400
    assert "text CSV" in response.json()["detail"]


def test_export_is_a_dated_reimportable_csv(client: TestClient) -> None:
    _create(client)
    response = client.get("/api/export.csv")
    assert response.headers["content-disposition"] == (
        'attachment; filename="expenses-2026-11-09.csv"'
    )
    assert response.content.startswith(b"\xef\xbb\xbfID,Date,Description")


def test_interface_explains_how_to_build_when_missing(client: TestClient) -> None:
    response = client.get("/transactions")
    assert response.status_code == 503
    assert "npm --prefix web" in response.text


def test_built_interface_is_served_for_every_page(database: Database, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    client = TestClient(create_app(database=database, config_loader=AppConfig, dist_dir=dist))
    assert client.get("/budgets").text.endswith("<div id=root></div>")
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/missing").status_code == 404
    # Only files inside the build folder are served; anything else gets the app shell.
    (tmp_path / "secret.txt").write_text("private")
    assert "private" not in client.get("/../secret.txt").text
    assert "private" not in client.get("/%2e%2e/secret.txt").text
