"""Presentation regressions use synthetic amounts and public asset metadata only."""

import tomllib
from pathlib import Path

import pytest

from expense_analysis.presentation import budget_hero_markup, summary_markup, usage_markup


@pytest.mark.parametrize("remaining", [12345, 0, -12345, 123456789012])
def test_budget_panel_preserves_amount_and_state(remaining):
    markup = budget_hero_markup(
        dict(
            remaining=remaining,
            target=100000,
            reserved=30000,
            buffer=1000,
            allowance=69000,
            flexible_spent=1234,
        )
    )
    assert f"${abs(remaining) / 100:,.2f}" in markup
    assert ("Over allowance" if remaining < 0 else "Left to spend") in markup
    assert "balance-panel" in markup
    assert "Everyday spent" in markup
    assert "<img" not in markup


def test_summary_escapes_all_dynamic_content():
    markup = summary_markup([("<script>x</script>", "<img src=x>")], title="<b>Summary</b>")
    assert "<script>" not in markup and "<img" not in markup
    assert "&lt;script&gt;" in markup and "&lt;b&gt;Summary" in markup


@pytest.mark.parametrize(
    "spent,ratio,width", [(150, "150%", "100.00"), (-50, "-50%", "0.00"), (25, "25%", "25.00")]
)
def test_usage_reports_actual_ratio_and_clamps_only_graphic(spent, ratio, width):
    markup = usage_markup(spent, 100)
    assert f'aria-valuetext="{ratio} used"' in markup
    assert f'aria-valuenow="{width}"' in markup


@pytest.mark.parametrize("available", [0, -100])
def test_usage_handles_nonpositive_allowance(available):
    assert "No positive everyday allowance" in usage_markup(100, available)


def test_both_native_themes_and_three_local_font_families():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / ".streamlit/config.toml").read_text())
    theme = config["theme"]
    assert theme["font"] == "Departure Mono, monospace"
    assert theme["headingFont"] == "Departure Mono, monospace"
    assert theme["codeFont"] == "Departure Mono, monospace"
    assert theme["light"]["backgroundColor"] != theme["dark"]["backgroundColor"]
    assert theme["baseRadius"] == "none"
    assert theme["baseFontSize"] == 14
    assert len({face["family"] for face in theme["fontFaces"]}) == 3
    for face in theme["fontFaces"]:
        assert face["url"].startswith("app/static/fonts/")
        assert (root / face["url"].removeprefix("app/")).is_file()
    assert "IBM Plex Mono" not in (root / "src/expense_analysis/assets/theme.css").read_text()
    assert config["server"]["address"] == "127.0.0.1"
    assert config["browser"]["gatherUsageStats"] is False


def test_theme_css_preserves_native_sidebar_and_readable_neon_controls():
    root = Path(__file__).resolve().parents[1]
    css = (root / "src/expense_analysis/assets/theme.css").read_text()
    bridge = (root / "src/expense_analysis/assets/theme_bridge.html").read_text()

    assert "max-width: 244px" in css
    assert "[data-testid='stExpandSidebarButton']" in css
    assert "[data-testid='stBaseButton-primaryFormSubmit']" in css
    assert "[aria-label^='Selected']" in css
    assert "border-radius: 0 !important" in css
    assert ".jizhang-chart-fullscreen" in css
    assert "stFullScreenFrame']:has([data-testid='stDataEditor'], [data-testid='stDataFrame'])" in css
    assert "data-jizhang-theme-choice" in bridge
    assert "stMainMenuItem-theme-${theme}" in bridge
    assert "addFieldSelectors" in bridge
    assert "add_transaction_notes" in bridge
    assert "scrollIntoView" in bridge
    assert "stNumberInputStepDown" in css
    assert "stNumberInputClearButton" in css
    assert "InputInstructions" in css


def test_add_transaction_form_boxes_share_one_height():
    root = Path(__file__).resolve().parents[1]
    css = (root / "src/expense_analysis/assets/theme.css").read_text()

    for selector in (
        ".st-key-add_transaction_date [data-baseweb='input']",
        ".st-key-add_transaction_description [data-testid='stTextInputRootElement']",
        ".st-key-add_transaction_merchant [data-testid='stTextInputRootElement']",
        ".st-key-add_transaction_amount [data-testid='stNumberInputContainer']",
        "[data-testid='stSelectbox'] .react-aria-ComboBox > [role='group']",
        ".st-key-add_transaction_submit [data-testid='stBaseButton-primaryFormSubmit']",
    ):
        start = css.index(selector)
        rule = css[start : css.index("}", start)]
        assert "height: 42px" in rule
        assert "min-height: 42px" in rule
