"""The command-line tools share the app's Settings-aware categories."""

import sys

from expense_analysis import cli
from expense_analysis.categories import save_category
from expense_analysis.config import AppConfig
from expense_analysis.database import Database


def test_cli_add_accepts_categories_created_in_settings(tmp_path, monkeypatch, capsys):
    database = Database(tmp_path / "cli.sqlite3")
    database.initialize()
    save_category(database, AppConfig(), "Hobbies", "Personal")
    monkeypatch.setattr(cli, "Database", lambda: database)
    monkeypatch.setattr(cli, "load_config", AppConfig)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "expense-add",
            "--description",
            "Synthetic yarn",
            "--date",
            "2026-07-01",
            "--amount",
            "8.50",
            "--category",
            "hobbies",
            "--account",
            "Cash",
            "--method",
            "Cash",
        ],
    )
    cli.add_main()

    assert "Unknown category" not in capsys.readouterr().out
    assert database.list_transactions()[0]["category"] == "Hobbies"
