"""Browser checks of shared text colors across every page and native theme."""

import base64
import json
import os
from datetime import date
from pathlib import Path

import pytest
from test_rendered_geometry import app_url, page  # noqa: F401

from expense_analysis.database import Database
from expense_analysis.models import TransactionDraft
from expense_analysis.spending_plan import Commitment, SpendingPlan

pytestmark = pytest.mark.rendered


@pytest.fixture(scope="module")
def rendered_seed():
    def seed(env):
        database = Database(Path(env["EXPENSE_ANALYSIS_DATA_DIR"]) / "expenses.sqlite3")
        database.initialize()
        for month in range(1, 9):
            for category, amount, kind in (
                ("Food", 28000 + month * 1300, "expense"),
                ("Transportation", 4200, "expense"),
                ("Rent", 80000, "expense"),
                ("Tech", 12000, "expense"),
                ("Income", 180000, "income"),
                ("Food", 2400, "refund"),
                ("Transfer", 10000, "transfer"),
            ):
                database.add_transaction(
                    TransactionDraft(
                        date(2026, month, 12),
                        f"Synthetic {category}",
                        amount,
                        category,
                        transaction_type=kind,
                        account="Synthetic account",
                    )
                )
        database.save_spending_plan(
            SpendingPlan(
                "Synthetic plan",
                date(2026, 1, 1),
                9,
                1100000,
                0,
                9000,
                (Commitment("Rent", 80000, ("Rent",)),),
                {
                    "school": "UCLA",
                    "year": "2026–27",
                    "cohort": "2024–25",
                    "housing": "Off-campus",
                    "residency": "CA resident",
                    "source": "https://financialaid.ucla.edu/go/coa",
                    "verified_on": "2026-09-08",
                    "components": {"Synthetic estimate": 1100000},
                },
            )
        )

    return seed


MEASURE_TEXT = r"""
JSON.stringify((() => {
  const rgb = value => (value.match(/[\d.]+/g) || []).map(Number);
  const luminance = channels => channels.slice(0, 3).map(channel => {
    const n = channel / 255;
    return n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4;
  }).reduce((sum, n, i) => sum + n * [.2126, .7152, .0722][i], 0);
  const background = el => {
    const c = rgb(getComputedStyle(el).backgroundColor);
    if (c.length === 3 || c[3] === 1) return c;
    const parent = el.parentElement ? background(el.parentElement) : [255, 255, 255];
    const a = c[3] || 0;
    return parent.map((n, i) => a * c[i] + (1 - a) * n);
  };
  const selectors = '.page-heading h1, .page-description, .kpi-label, .kpi-value, '
    + '.kpi-foot > span, .transaction-title, .transaction-note, .transaction-meta, '
    + '.transaction-amount, .transaction-empty-message, .privacy-hero strong, '
    + '.privacy-hero span, .privacy-strip, [data-testid=stCaptionContainer], '
    + '[data-testid=stCaptionContainer] p, '
    + '[data-testid=stAlert] p, .soft-empty span, .empty-card p, '
    + '.balance-panel h2, .balance-panel p, .balance-value, .summary-row dt, '
    + '.summary-row dd, .usage-label, .usage-note, .theme-control-label, '
    + '.section-heading h2, .section-heading span';
  return [...document.querySelectorAll(selectors)]
    .filter(el => el.getClientRects().length && el.textContent.trim())
    .map(el => {
      const s = getComputedStyle(el);
      const bg = background(el);
      const color = rgb(s.color);
      const alpha = color.length === 4 ? color[3] : 1;
      const fg = color.slice(0, 3).map((n, i) => alpha * n + (1-alpha) * bg[i]);
      const a = luminance(fg), b = luminance(bg);
      return {text: el.textContent.trim().slice(0, 70),
        contrast: (Math.max(a,b)+.05)/(Math.min(a,b)+.05),
        minimum: parseFloat(s.fontSize) >= 24 ? 3 : 4.5};
    });
})())
"""


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_all_pages_text_contrast_and_theme_switching(page, theme):  # noqa: F811
    titles = {
        "Overview": "Overview",
        "Transactions": "Transactions",
        "Import / Export": "Import and export",
        "Budgets": "Budgets",
        "Advanced insights": "Advanced insights",
        "Settings": "Settings and privacy",
    }
    page.click(f"document.querySelector('[data-jizhang-theme-choice={theme}]')")
    page.wait_js(f"document.documentElement.dataset.jizhangTheme === '{theme.lower()}'")
    failures: list[tuple[str, dict]] = []
    for name, title in titles.items():
        page.select_page(name)
        page.wait_js(
            "document.querySelector('.page-heading h1')?.textContent === " + json.dumps(title)
        )
        page.wait_js("document.querySelector('.stApp').dataset.testScriptState === 'notRunning'")
        if name in {"Overview", "Advanced insights"}:
            page.wait_js("!!document.querySelector('.js-plotly-plot .main-svg')")
        page.evaluate(
            "document.querySelector('[data-testid=stMain]').scrollTo({top: 0, behavior: 'instant'})"
        )
        page.evaluate("document.fonts.ready")
        page.evaluate(
            "new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )
        error = page.evaluate("document.querySelector('[data-testid=stException]')?.textContent")
        assert not error, (name, error)
        page.evaluate("new Promise(resolve => setTimeout(resolve, 350))")
        measurements = page.measure(MEASURE_TEXT)
        assert len(measurements) >= 2
        failures.extend((name, item) for item in measurements if item["contrast"] < item["minimum"])
        if destination := os.environ.get("THEME_AUDIT_SCREENSHOTS"):
            folder = Path(destination)
            folder.mkdir(parents=True, exist_ok=True)
            screenshot = page._command("Page.captureScreenshot", {"format": "png"})
            (folder / f"{theme.lower()}-{name.lower().replace(' / ', '-')}.png").write_bytes(
                base64.b64decode(screenshot["result"]["data"])
            )
            page.evaluate(
                "const main = document.querySelector('[data-testid=stMain]');"
                "main.scrollTo({top: main.scrollHeight, behavior: 'instant'});"
            )
            page.evaluate(
                "new Promise(resolve => requestAnimationFrame("
                "() => requestAnimationFrame(resolve)))"
            )
            screenshot = page._command("Page.captureScreenshot", {"format": "png"})
            (folder / f"{theme.lower()}-{name.lower().replace(' / ', '-')}-bottom.png").write_bytes(
                base64.b64decode(screenshot["result"]["data"])
            )
    assert not failures, failures


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_mobile_pages_keep_content_inside_viewport(page, theme):  # noqa: F811
    page.click(f"document.querySelector('[data-jizhang-theme-choice={theme}]')")
    page.wait_js(f"document.documentElement.dataset.jizhangTheme === '{theme.lower()}'")
    for name in (
        "Overview",
        "Transactions",
        "Import / Export",
        "Budgets",
        "Advanced insights",
        "Settings",
    ):
        page.select_page(name)
        page.wait_js("document.querySelector('.stApp').dataset.testScriptState === 'notRunning'")
        try:
            page._command(
                "Emulation.setDeviceMetricsOverride",
                {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": False},
            )
            page.evaluate("new Promise(resolve => setTimeout(resolve, 350))")
            # Streamlit can collapse the sidebar automatically at mobile widths.
            if page.evaluate(
                "document.querySelector('[data-testid=stSidebar]')"
                ".getAttribute('aria-expanded') === 'true'"
            ):
                page.click("document.querySelector('[data-testid=stSidebarCollapseButton] button')")
            page.wait_js(
                "document.querySelector('[data-testid=stSidebar]')"
                ".getAttribute('aria-expanded') === 'false'",
                timeout=5,
            )
            page.evaluate("new Promise(resolve => setTimeout(resolve, 350))")
            sizes = page.measure("""
                JSON.stringify([...document.querySelectorAll(
                  '.page-heading, .kpi-card, .budget-top-grid, .privacy-strip, .privacy-hero, '
                  + '.transaction-list, [data-testid=stForm]')].map(el => {
                    const r = el.getBoundingClientRect();
                    return {element: el.className, left: r.left, right: r.right};
                  }))
            """)
            assert sizes
            assert all(item["left"] >= 0 and item["right"] <= 390.5 for item in sizes), sizes
            if destination := os.environ.get("THEME_AUDIT_SCREENSHOTS"):
                page.evaluate(
                    "document.querySelector('[data-testid=stMain]')"
                    ".scrollTo({top:0, behavior:'instant'})"
                )
                screenshot = page._command("Page.captureScreenshot", {"format": "png"})
                path = Path(destination) / f"mobile-{theme.lower()}-{name.replace(' / ', '-')}.png"
                path.write_bytes(base64.b64decode(screenshot["result"]["data"]))
        finally:
            page._command("Emulation.clearDeviceMetricsOverride")
            page.evaluate("document.querySelector('[data-testid=stExpandSidebarButton]')?.click()")
            page.wait_js(
                "document.querySelector('[data-testid=stSidebar]')"
                ".getAttribute('aria-expanded') === 'true'"
            )
            page.evaluate("new Promise(resolve => setTimeout(resolve, 350))")
