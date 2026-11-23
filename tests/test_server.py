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


def test_suggestions_say_why_and_learn_from_corrections(
    client: TestClient, database: Database
) -> None:
    for day in (2, 3, 4):
        database.add_transaction(_draft(date(2026, 11, day), "Boba", 6_00, "Food"))

    def suggest(description: str) -> dict:
        body = {"description": description}
        return client.post("/api/suggest", json=body, headers=HEADERS).json()

    assert suggest("boba") == {
        "category": "Food",
        "source": "name",
        "evidence": [{"text": "boba", "category": "Food", "count": 3}],
        "share": 1.0,
    }
    # Left alone, or picked to match, nothing is corrected.
    assert _create(client, description="Boba", category="")["category"] == "Food"
    _create(
        client,
        description="Boba",
        amount_cents=7_00,
        category="Food",
        category_manual=True,
        category_chosen=True,
    )
    # Repeating an earlier entry carries its category over; that is not a correction.
    _create(
        client, description="Boba", amount_cents=8_00, category="Dining Out", category_manual=True
    )
    assert database.category_corrections() == {}
    assert suggest("Boba")["category"] == "Food"
    fixed = _create(
        client,
        description="Boba",
        amount_cents=9_00,
        category="Dining Out",
        category_manual=True,
        category_chosen=True,
    )
    assert list(database.category_corrections()) == [fixed["id"]]
    assert suggest("Boba")["category"] == "Dining Out"


def test_changing_a_category_later_is_a_correction(client: TestClient, database: Database) -> None:
    ids = [
        database.add_transaction(_draft(date(2026, 11, day), "Boba", 6_00, "Food"))
        for day in (2, 3, 4)
    ]
    row = next(r for r in client.get("/api/transactions").json()["rows"] if r["id"] == ids[0])
    before = {
        key: row[key]
        for key in (
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
    }

    def change(old: dict, **values) -> dict:
        new = {**old, **values}
        body = {"id": ids[0], "before": old, "after": new}
        assert client.post("/api/transactions/edit", json=body, headers=HEADERS).status_code == 200
        return new

    edited = change(before, notes="nothing to do with it")
    assert database.category_corrections() == {}
    edited = change(edited, category="Dining Out")
    assert list(database.category_corrections()) == [ids[0]]
    body = {"description": "Boba"}
    learned = client.post("/api/suggest", json=body, headers=HEADERS).json()
    assert learned["category"] == "Dining Out"
    # A deleted entry that is brought back is still a correction.
    deleted = client.post("/api/transactions/delete", json={"ids": [ids[0]]}, headers=HEADERS)
    client.post("/api/transactions/restore", json={"rows": deleted.json()["rows"]}, headers=HEADERS)
    learned = client.post("/api/suggest", json=body, headers=HEADERS).json()
    assert learned["category"] == "Dining Out"
    # Taking the category away takes the correction with it.
    change(edited, category="Uncategorized")
    assert database.category_corrections() == {}


def test_entry_defaults_can_be_changed(client: TestClient, database: Database) -> None:
    assert client.get("/api/bootstrap").json()["defaults"] == {
        "category": "Uncategorized",
        "payment_method": "Apple Pay",
        "account": "Checking",
        "transaction_type": "expense",
    }

    def change(kind: str, value: str):
        return client.put(f"/api/defaults/{kind}", json={"value": value}, headers=HEADERS)

    assert change("account", "Cash").json() == {"previous": "Checking"}
    assert change("payment_method", "Card").json() == {"previous": "Apple Pay"}
    assert change("category", "Food").status_code == 200
    assert change("transaction_type", "income").status_code == 200
    chosen = client.get("/api/bootstrap").json()["defaults"]
    assert list(chosen.values()) == ["Food", "Card", "Cash", "income"]
    listed = client.get("/api/choices").json()
    assert listed["defaults"] == chosen
    for kind in ("account", "payment_method", "category"):
        assert [c["name"] for c in listed[kind] if c["default"]] == [chosen[kind]]
        # A default is in use, so it is not removed by accident.
        removal = client.post(
            f"/api/choices/{kind}/delete", json={"source": chosen[kind]}, headers=HEADERS
        )
        assert removal.status_code == 400
    # A rule still wins, and only spending nothing matches takes the default category.
    assert _create(client)["category"] == "Dining Out"
    assert _create(client, description="Zzz")["category"] == "Food"
    paid = _create(client, description="Zzz", transaction_type="income")
    assert paid["category"] == "Uncategorized"
    assert change("account", "Nowhere").status_code == 400
    assert change("notes", "x").status_code == 400
    # A rename takes the default with it.
    client.post(
        "/api/choices/category/save", json={"name": "Eats", "source": "Food"}, headers=HEADERS
    )
    client.post(
        "/api/choices/account/save", json={"name": "Wallet", "source": "Cash"}, headers=HEADERS
    )
    chosen = client.get("/api/bootstrap").json()["defaults"]
    assert (chosen["category"], chosen["account"]) == ("Eats", "Wallet")


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


def test_bootstrap_offers_repeat_purchases(client: TestClient, seeded: Database) -> None:
    frequent = client.get("/api/bootstrap").json()["frequent"]
    assert [item["description"] for item in frequent] == ["Chipotle lunch", "Ralphs groceries"]
    assert frequent[0]["amount_cents"] == 12_85
    assert frequent[0]["last"] == "2026-11-09"


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
    month = data["comparisons"]["month"]
    assert (month["prior_start"], month["prior_end"]) == ("2026-10-01", "2026-10-09")
    assert month["change"] == data["spent"] - 52_00
    assert [w["week"] for w in data["weekly"]][-2:] == ["2026-11-02", "2026-11-09"]
    assert data["weekly"][-1]["label"] == "Week 7"
    assert data["weekly"][-1]["spent"] == week["spent"]
    term = client.get("/api/budget").json()["weeks"]
    finished = [w["saved"] for w in term if w["saved"] is not None]
    assert finished and data["budget"]["weeks"] == finished
    # Nothing here needs doing, sorting categories least of all.
    assert data["signals"] == []
    # The last 30 days' largest purchases: no phone bill, no refund, whatever the scope.
    largest = [(r["description"], r["amount_cents"]) for r in data["largest"]]
    assert largest == [
        ("Metro card", 46_20),
        ("Ralphs groceries", 18_40),
        ("Target", 16_40),
        ("Chipotle lunch", 12_85),
    ]
    assert data["largest_days"] == 30
    every = client.get("/api/overview", params={"scope": "all"}).json()
    assert every["spent"] == data["spent"] + 35_00
    assert every["largest"] == data["largest"]


def test_overview_of_a_past_month_has_no_weekly_line(client: TestClient, seeded: Database) -> None:
    data = client.get("/api/overview", params={"month": "2026-10"}).json()
    assert data["is_current"] is False
    assert data["as_of"] == "2026-10-31"
    assert data["budget"] is None
    assert data["ticker"]["label"] == "LATEST"
    assert [r["amount_cents"] for r in data["largest"]] == [40_00, 12_00]
    assert data["largest_days"] is None


def test_empty_ledger_overview_is_predictable(client: TestClient) -> None:
    data = client.get("/api/overview").json()
    assert data["has_transactions"] is False
    # The school's estimate works before any setup.
    assert data["budget"]["source"] == "school"
    assert data["budget"]["week"]["spent"] == 0
    assert data["categories"] == []
    assert data["monthly"] == []
    assert data["largest"] == []


def test_insights_forecast_is_integer_cents(client: TestClient, seeded: Database) -> None:
    for month in (8, 9):
        seeded.add_transaction(_draft(date(2026, month, 3), "Ralphs groceries", 52_00, "Food"))
    forecast = client.get("/api/insights", params={"scope": "all"}).json()["forecast"]
    assert forecast["history_months"] == 3
    assert [item["month"] for item in forecast["months"]] == [
        "2026-11",
        "2026-12",
        "2027-01",
        "2027-02",
    ]
    this_month, next_month = forecast["months"][:2]
    assert this_month["partial"] is True
    assert this_month["spent"] == 124_85
    assert this_month["low"] >= this_month["spent"]
    # November to January are mostly quarter days, which the calendar knows about.
    assert set(forecast["weekly_rates"]) == {"quarter", "summer"}
    assert next_month["low"] <= next_month["expected"] <= next_month["high"]
    assert all(type(next_month[key]) is int for key in ("expected", "low", "high", "spent"))


def test_insights_and_budget_payloads(client: TestClient, seeded: Database) -> None:
    insights = client.get("/api/insights").json()
    assert insights["cash_flow"][-1]["month"] == "2026-11"
    assert insights["year"]["label"] == "2026–27"
    assert insights["terms"][-1]["period"] == "Fall quarter 2026"
    # One complete month is not enough to predict from.
    assert insights["forecast"]["months"] == []
    assert insights["forecast"]["history_months"] == 1
    # The trend and forecast look from today whichever month is open.
    october = client.get("/api/insights", params={"month": "2026-10"}).json()
    assert october["month"] == "2026-10"
    assert [item["month"] for item in october["monthly"]] == ["2026-10", "2026-11"]
    assert october["forecast"] == insights["forecast"]
    overview = client.get("/api/overview", params={"month": "2026-10"}).json()
    assert [item["month"] for item in overview["monthly"]] == ["2026-10", "2026-11"]
    budget = client.get("/api/budget").json()
    assert budget["period"]["name"] == "Fall quarter 2026"
    assert budget["period"]["is_current"] is True
    assert [w["label"] for w in budget["weeks"]][:2] == ["Week 0", "Week 1"]
    assert budget["week"]["label"] == "Week 7"
    assert budget["line"]["source"] == "own"
    assert {fact["key"] for fact in budget["auto"]["facts"]} == {
        "housing",
        "cohort",
        "residency",
        "insurance",
    }
    assert {p["name"] for p in budget["periods"]} >= {"Fall quarter 2026", "Summer 2026"}
    earlier = client.get("/api/budget", params={"period": budget["period"]["previous"]}).json()
    assert earlier["period"]["name"] == "Summer 2026"
    assert earlier["week"] is None


def _save(client: TestClient, **change):
    """Send the settings page's whole state back with one change, as the page does."""
    auto = client.get("/api/budget").json()["auto"]
    chosen = {f["key"]: f["value"] if f["source"] == "yours" else None for f in auto["facts"]}
    fields = ("name", "amount_cents", "categories", "cadence", "due_day", "due", "pinned", "match")
    body = {
        **chosen,
        "weekly_cents": auto["weekly_cents"],
        "total_cents": auto["total_cents"],
        "bills": [{k: b[k] for k in fields} for b in auto["bills"] if not b["key"]],
        "dismissed": auto["dismissed_keys"],
        **change,
    }
    return client.put("/api/budget/settings", json=body, headers=HEADERS)


def test_budget_settings_save_and_validate(client: TestClient, database: Database) -> None:
    empty = client.get("/api/budget").json()
    assert empty["line"]["source"] == "school"
    housing = next(f for f in empty["auto"]["facts"] if f["key"] == "housing")
    assert (housing["text"], housing["source"]) == ("Off-campus", "default")
    assert {o["value"] for o in housing["options"]} == {"On-campus", "Off-campus", "Commuter"}
    bills = [
        {"name": "Rent", "amount_cents": 1450_00, "categories": ["Rent"], "due_day": 1},
        {"name": "Books", "amount_cents": 200_00, "cadence": "Once", "due": "2027-01-04"},
        {
            "name": "Music",
            "amount_cents": 9_99,
            "categories": ["Entertainment"],
            "match": ["Music Plan 2026"],
        },
    ]
    saved = _save(client, housing="On-campus", weekly_cents=250_00, bills=bills)
    assert saved.status_code == 200, saved.text
    settings = database.get_budget_settings()
    assert settings is not None
    assert settings.housing == "On-campus" and settings.pinned == ("housing",)
    assert [b.name for b in settings.bills] == ["Rent", "Books", "Music"]
    assert all(b.pinned for b in settings.bills)
    assert settings.bills[2].match == {"music", "plan"}
    assert settings.weekly_cents == 250_00 and settings.coa is None
    # One change later everything else is still as it was.
    assert _save(client, total_cents=60_000_00).status_code == 200
    again = database.get_budget_settings()
    assert again is not None and again.coa is not None
    assert (again.bills, again.weekly_cents) == (settings.bills, 250_00)
    assert again.coa.total_cents == 60_000_00
    assert _save(client, housing=None, weekly_cents=None).status_code == 200
    automatic = database.get_budget_settings()
    assert automatic is not None and automatic.pinned == () and automatic.weekly_cents is None
    for wrong in (
        {"bills": [{"name": "X", "amount_cents": 1, "cadence": "Once"}]},
        {"housing": "Houseboat"},
        {"cohort": "1999–00"},
        {"residency": "maybe"},
        {"bills": [bills[0], {**bills[0], "name": "Other"}]},
    ):
        assert _save(client, **wrong).status_code in (400, 422)


def test_the_budget_needs_no_setup(client: TestClient, database: Database) -> None:
    for index, month in enumerate(("09", "10", "11")):
        database.add_transaction(_draft(date(2026, int(month), 1), f"Rent {month}", 900_00, "Rent"))
        database.add_transaction(
            _draft(date(2026, int(month), 5), "Music plan", 11_99, "Entertainment")
        )
        database.add_transaction(
            _draft(date(2026, int(month), 7 + index), "Film", 15_00 + 400 * index, "Fun")
        )
    database.add_transaction(_draft(date(2026, 9, 1), "Fall tuition", 18_600_00, "Tuition"))
    budget = client.get("/api/budget").json()
    facts = {f["key"]: f for f in budget["auto"]["facts"]}
    assert facts["housing"]["value"] == "Off-campus" and facts["housing"]["source"] == "learned"
    assert (facts["cohort"]["value"], facts["residency"]["value"]) == ("2026–27", True)
    assert facts["insurance"]["text"] == "Waived UC SHIP"
    assert budget["coa"]["ready"] is True
    learned = {b["name"]: b for b in budget["auto"]["bills"]}
    assert set(learned) == {"Rent", "Music plan", "Tuition & fees"}
    assert learned["Rent"]["next_due"] == "2026-12-01" and learned["Rent"]["why"]
    assert {b["name"] for b in budget["bills"] if b["learned"]} >= {"Rent", "Music plan"}
    table = {t["category"]: t for t in budget["treatments"]}
    assert table["Rent"]["treatment"] == "Commitments" and not table["Rent"]["pinned"]
    # Purchases show how they count on the transactions page too, whatever is filtered.
    rows = client.get("/api/transactions", params={"category": "Entertainment"}).json()["rows"]
    assert {r["spending_treatment"] for r in rows} == {"Commitments"}
    # Set aside, a bill is an ordinary purchase again; brought back, it is a bill.
    key = learned["Music plan"]["key"]
    assert _save(client, dismissed=[key]).status_code == 200
    budget = client.get("/api/budget").json()
    assert "Music plan" not in {b["name"] for b in budget["auto"]["bills"]}
    assert [b["name"] for b in budget["auto"]["dismissed"]] == ["Music plan"]
    assert _save(client, dismissed=[]).status_code == 200
    # Changing a learned bill makes it the student's own.
    own = {"name": "Rent", "amount_cents": 950_00, "categories": ["Rent"], "due_day": 3}
    assert _save(client, bills=[own]).status_code == 200
    rents = [b for b in client.get("/api/budget").json()["auto"]["bills"] if b["name"] == "Rent"]
    assert [(b["amount_cents"], b["key"], b["pinned"]) for b in rents] == [(950_00, "", True)]


def test_a_learned_bill_that_does_not_show_up_is_mentioned_gently(
    client: TestClient, database: Database
) -> None:
    for month in (8, 9, 10):
        database.add_transaction(_draft(date(2026, month, 1), "Landlord rent", 900_00, "Rent"))
    signal = client.get("/api/overview").json()["signals"][0]
    assert (signal["tone"], signal["action"]) == ("warn", "bills")
    assert (signal["label"], signal["value"]) == ("Not seen yet", "Rent · Nov 1")
    assert "Rent was expected around Nov 1" in signal["text"]


def test_cost_of_attendance_profile_parts_and_banner(client: TestClient, seeded: Database) -> None:
    budget = client.get("/api/budget").json()
    assert (budget["coa"]["ready"], budget["coa"]["reason"]) == (False, "profile")
    # Nothing nags before a profile is known.
    actions = [s.get("action") for s in client.get("/api/overview").json()["signals"]]
    assert "coa" not in actions
    saved = _save(client, cohort="2025–26", residency=False, total_cents=1000_00)
    assert saved.status_code == 200, saved.text
    settings = seeded.get_budget_settings()
    assert settings is not None and settings.coa is not None
    # Insurance was left automatic, which counts UC SHIP until something shows otherwise.
    assert settings.coa.insurance is None and settings.pinned == ("cohort", "residency")
    coa = client.get("/api/budget").json()["coa"]
    assert coa["ready"] is True and coa["verdict"] == "over" and coa["line"] == 1000_00
    assert coa["start"] == "2026-09-21"
    assert coa["projected"] == sum(coa["layers"].values())
    signals = client.get("/api/overview").json()["signals"]
    banner = next(s for s in signals if s.get("action") == "coa")
    assert banner["tone"] == "up" and "cost of attendance" in banner["text"]
    assert banner["label"] == "Cost of attendance" and banner["value"].endswith(" over")
    past = client.get("/api/overview", params={"month": "2026-10"}).json()["signals"]
    assert "coa" not in [s.get("action") for s in past]

    saved = client.put(
        "/api/spending-rules/categories",
        json={"categories": {"Food": "Everyday"}, "parts": {"Cell Phone": "Housing"}},
        headers=HEADERS,
    )
    assert saved.status_code == 200
    table = {t["category"]: t for t in client.get("/api/budget").json()["treatments"]}
    assert (table["Cell Phone"]["part"], table["Cell Phone"]["part_pinned"]) == ("Housing", True)
    assert (table["Food"]["part"], table["Food"]["part_pinned"]) == ("Food", False)
    assert table["Food"]["pinned"] and not table["Transportation"]["pinned"]
    assert seeded.get_spending_rules()["auto"] is True
    # Saving treatments alone keeps the parts, and a rename carries them along.
    client.put("/api/spending-rules/categories", json={"categories": {}}, headers=HEADERS)
    client.post(
        "/api/choices/category/save",
        json={"name": "Mobile", "source": "Cell Phone", "spending_class": "Personal"},
        headers=HEADERS,
    )
    assert seeded.get_spending_rules()["parts"] == {"Mobile": "Housing"}
    bad = client.put(
        "/api/spending-rules/categories",
        json={"categories": {}, "parts": {"Food": "Yachts"}},
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
