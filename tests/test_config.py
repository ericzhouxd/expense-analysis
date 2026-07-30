from datetime import date

from expense_analysis.config import load_config


def test_local_config_supports_rules_and_exact_academic_dates(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[category_rules]
cafe = "Dining Out"

[[academic_periods]]
label = "Special Term"
start = "2026-09-20"
end = "2026-12-10"
""".strip()
    )
    config = load_config(config_path)
    assert config.category_for("Campus cafe") == "Dining Out"
    assert config.academic_calendar.label_for(date(2026, 10, 1)) == "Special Term"
