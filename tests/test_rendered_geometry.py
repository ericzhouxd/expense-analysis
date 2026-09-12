"""Rendered-geometry checks measured in a real browser.

The assertions in ``test_presentation.py`` read ``theme.css`` as text: they can
prove a declaration is present, but not that the browser applies it to the element
it is meant for, and not that two pages paint the same box. The sidebar layout
bug in #22 (the nav highlight growing a focus ring and changing size on switch)
and the misalignment in #23 both passed a suite built on exactly those substring
checks.

These checks boot the real Streamlit app against a throwaway data directory,
drive it over the Chrome DevTools Protocol, and assert on geometry the browser
computes. They need Chromium, so they are excluded from the default run:

    uv run pytest -m rendered

Point ``EXPECT_CHROMIUM`` at a binary if ``chromium`` is not on ``PATH``; when it
is set, a missing browser fails the run instead of skipping it. The throwaway
directory is supplied through ``EXPENSE_ANALYSIS_DATA_DIR``, so a run never opens
the real ledger.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("websockets")

from websockets.sync.client import connect  # noqa: E402

pytestmark = pytest.mark.rendered

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHROMIUM_CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "chrome")

# Geometry the browser computes rarely lands on exact integers, so compare with a
# tolerance well below one CSS pixel.
TOLERANCE = 0.5
# The radio widget renders its own (visually hidden) label as a sibling, so keep
# only the labels that wrap an input, and read textContent: the theme uppercases
# the visible text with text-transform, which innerText reflects.
NAV_ROWS = (
    "[...document.querySelectorAll(\".st-key-main_navigation [role='radiogroup'] label\")]"
    ".filter((el) => el.querySelector('input'))"
)
# A plain selector for readiness checks, where an element expression will not do.
NAV_SELECTOR = ".st-key-main_navigation [role='radiogroup'] label input"
THEME_CHOICES = "[data-jizhang-theme-choice]"

# Exactly the selectors theme.css sizes, so a passing check means the rule reached
# the rendered control rather than merely existing in the stylesheet.
FORM_SELECTORS = {
    "date": ".st-key-add_transaction_date [data-baseweb='input']",
    "description": ".st-key-add_transaction_description [data-testid='stTextInputRootElement']",
    "merchant": ".st-key-add_transaction_merchant [data-testid='stTextInputRootElement']",
    "amount": ".st-key-add_transaction_amount [data-testid='stNumberInputContainer']",
    "category": "[data-testid='stSelectbox'] .react-aria-ComboBox > [role='group']",
    "submit": ".st-key-add_transaction_submit [data-testid='stBaseButton-primaryFormSubmit']",
}

MEASURE_PAGE = """
(() => {
  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return [r.x, r.y, r.width, r.height].map((n) => +n.toFixed(2));
  };
  // Everything the browser paints for the element: the border box plus any
  // outline drawn outside it. An inset ring leaves this equal to the border box,
  // and outline-width is meaningless while outline-style is none.
  const painted = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    const outward =
      s.outlineStyle === 'none'
        ? 0
        : (parseFloat(s.outlineWidth) || 0) + (parseFloat(s.outlineOffset) || 0);
    const w = Math.max(outward, 0);
    return [r.x - w, r.y - w, r.width + 2 * w, r.height + 2 * w].map((n) => +n.toFixed(2));
  };
  const labels = NAV_LABELS_PLACEHOLDER;
  const selected = labels.find((el) => el.querySelector('input:checked')) || null;
  const options = document.querySelector('.theme-options');
  const divider = document.querySelector("[data-testid='stSidebarUserContent'] hr");
  const innerInput = selected ? getComputedStyle(selected.querySelector('input')) : null;
  return JSON.stringify({
    pages: labels.map((el) => el.textContent.trim()),
    rects: labels.map(rect),
    painted: labels.map(painted),
    checkedPage: selected ? selected.textContent.trim() : null,
    innerInputOutlineStyle: innerInput ? innerInput.outlineStyle : null,
    themeOptions: options ? rect(options) : null,
    themeChoices: [...document.querySelectorAll(THEME_CHOICES_PLACEHOLDER)].map((el) => ({
      value: el.getAttribute('data-jizhang-theme-choice'),
      checked: el.getAttribute('aria-checked'),
      tabindex: el.getAttribute('tabindex'),
      rect: rect(el),
    })),
    divider: divider ? rect(divider) : null,
  });
})()
""".replace("NAV_LABELS_PLACEHOLDER", NAV_ROWS).replace(
    "THEME_CHOICES_PLACEHOLDER", json.dumps(THEME_CHOICES)
)

MEASURE_FORM = """
(() => {
  const out = {};
  for (const [name, selector] of Object.entries(FORM_SELECTORS_PLACEHOLDER)) {
    const el = document.querySelector(selector);
    out[name] = el ? +el.getBoundingClientRect().height.toFixed(2) : null;
  }
  return JSON.stringify(out);
})()
""".replace("FORM_SELECTORS_PLACEHOLDER", json.dumps(FORM_SELECTORS))


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _get(url: str, timeout: float = 2.0) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError):
        return None


def _wait_for(url: str, *, timeout: float, interval: float = 0.25) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _get(url) is not None:
            return
        time.sleep(interval)
    raise AssertionError(f"{url} never became reachable within {timeout:.0f}s")


class Cdp:
    """Minimal Chrome DevTools Protocol client: evaluate JS and dispatch input."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self._counter = 0

    def _command(self, method: str, params: dict | None = None, *, timeout: float = 30.0):
        self._counter += 1
        message_id = self._counter
        self._ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"CDP command {method} timed out")
            message = json.loads(self._ws.recv(timeout=remaining))
            if message.get("id") == message_id:
                return message

    def evaluate(self, expression: str):
        result = self._command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        return result["result"]["result"].get("value")

    def measure(self, expression: str) -> dict:
        return json.loads(self.evaluate(expression))

    def wait_js(self, expression: str, *, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.evaluate(expression):
                return
            time.sleep(0.25)
        raise AssertionError(f"condition never held: {expression}")

    def centre_of(self, expression: str, *, timeout: float = 30.0) -> tuple[float, float]:
        """Centre of the first match, waiting out a Streamlit re-render if needed."""
        deadline = time.monotonic() + timeout
        while True:
            centre = self.evaluate(
                "(() => { const el = " + expression + "; if (!el) return null;"
                " const r = el.getBoundingClientRect();"
                " return [r.x + r.width / 2, r.y + r.height / 2]; })()"
            )
            if centre:
                return float(centre[0]), float(centre[1])
            if time.monotonic() >= deadline:
                raise AssertionError(f"element not found: {expression}")
            time.sleep(0.25)

    def click(self, expression: str) -> None:
        """Click with real mouse events, so Streamlit sees a trusted gesture."""
        x, y = self.centre_of(expression)
        for event_type in ("mousePressed", "mouseReleased"):
            self._command(
                "Input.dispatchMouseEvent",
                {
                    "type": event_type,
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1,
                    "buttons": 1 if event_type == "mousePressed" else 0,
                },
            )

    def press(self, key: str, code: str, virtual_key: int) -> None:
        for event_type in ("keyDown", "keyUp"):
            self._command(
                "Input.dispatchKeyEvent",
                {
                    "type": event_type,
                    "key": key,
                    "code": code,
                    "windowsVirtualKeyCode": virtual_key,
                    "nativeVirtualKeyCode": virtual_key,
                },
            )

    def page_for(self, name: str) -> str:
        return f"{NAV_ROWS}.find((el) => el.textContent.trim() === {json.dumps(name)})"

    def select_page(self, name: str, *, timeout: float = 45.0) -> None:
        self.click(self.page_for(name))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.measure(MEASURE_PAGE)["checkedPage"] == name:
                return
            time.sleep(0.3)
        raise AssertionError(f"clicking {name!r} never selected it")


def _find_chromium() -> str:
    override = os.environ.get("EXPECT_CHROMIUM")
    for candidate in (override, *CHROMIUM_CANDIDATES) if override else CHROMIUM_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
    if override:
        # CI sets EXPECT_CHROMIUM precisely so a missing browser fails the run
        # instead of quietly turning the checks into a no-op.
        pytest.fail(f"EXPECT_CHROMIUM={override!r} does not point at an executable browser")
    pytest.skip("no Chromium binary found; set EXPECT_CHROMIUM to run the rendered checks")


def _seed_database(env: dict) -> None:
    """Write synthetic transactions through the app's own API, never real data."""
    seed = (
        "from datetime import date\n"
        "from expense_analysis.database import Database\n"
        "from expense_analysis.models import TransactionDraft\n"
        "database = Database()\n"
        "database.initialize()\n"
        "database.add_transaction("
        "TransactionDraft(date(2026, 7, 30), 'Synthetic entry', 1250, 'Food'))\n"
        "database.add_transaction("
        "TransactionDraft(date(2026, 7, 12), 'Synthetic fare', 480, 'Transportation'))\n"
    )
    subprocess.run(
        [sys.executable, "-c", seed],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="module")
def app_url():
    """Boot the real app on a free port against a throwaway data directory."""
    with tempfile.TemporaryDirectory(prefix="expense-rendered-") as work:
        env = {
            **os.environ,
            "EXPENSE_ANALYSIS_DATA_DIR": str(Path(work) / "data"),
            "EXPENSE_ANALYSIS_OUTPUT_DIR": str(Path(work) / "output"),
        }
        Path(env["EXPENSE_ANALYSIS_DATA_DIR"]).mkdir(parents=True)
        _seed_database(env)

        port = _free_port()
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "app.py",
                "--server.headless=true",
                "--server.address=127.0.0.1",
                f"--server.port={port}",
                "--browser.gatherUsageStats=false",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for(f"http://127.0.0.1:{port}/_stcore/health", timeout=60)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()


@pytest.fixture(scope="module")
def page(app_url):
    """A headless Chromium page parked on the running app."""
    binary = _find_chromium()
    debug_port = _free_port()
    with tempfile.TemporaryDirectory(prefix="expense-chromium-") as profile:
        browser = subprocess.Popen(
            [
                binary,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--user-data-dir={profile}",
                f"--remote-debugging-port={debug_port}",
                "--remote-allow-origins=*",
                "--window-size=1400,1000",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_for(f"http://127.0.0.1:{debug_port}/json/list", timeout=30)
            targets = json.loads(_get(f"http://127.0.0.1:{debug_port}/json/list") or "[]")
            ws_url = next(
                entry["webSocketDebuggerUrl"] for entry in targets if entry.get("type") == "page"
            )
            with connect(ws_url, max_size=20_000_000, open_timeout=20) as ws:
                cdp = Cdp(ws)
                cdp._command("Page.enable")
                cdp._command("Runtime.enable")
                cdp._command("Page.navigate", {"url": app_url})
                cdp.wait_js(f"!!document.querySelector({json.dumps(NAV_SELECTOR)})", timeout=60)
                yield cdp
        finally:
            browser.terminate()
            try:
                browser.wait(timeout=15)
            except subprocess.TimeoutExpired:
                browser.kill()


def _selected_box(measurement: dict) -> list[float]:
    return measurement["painted"][measurement["pages"].index(measurement["checkedPage"])]


def test_nav_highlight_keeps_one_size_on_every_page(page):
    """#22: switching pages grew the selected row a focus ring and resized it."""
    first = page.measure(MEASURE_PAGE)
    # Keep the first paint under its own key: it is the only measurement taken
    # before any click, so it is the unfocused box every clicked box must match.
    boxes = {"first paint": _selected_box(first)}

    for name in first["pages"]:
        page.select_page(name)
        current = page.measure(MEASURE_PAGE)
        boxes[name] = _selected_box(current)

    widths = {name: box[2] for name, box in boxes.items()}
    heights = {name: box[3] for name, box in boxes.items()}
    assert max(widths.values()) - min(widths.values()) <= TOLERANCE, widths
    assert max(heights.values()) - min(heights.values()) <= TOLERANCE, heights


def test_clicking_a_page_does_not_resize_the_highlight(page):
    """#22 from the other side: first paint and post-click must match."""
    page.select_page("Overview")
    first = page.measure(MEASURE_PAGE)
    before = _selected_box(first)

    page.select_page("Advanced insights")
    after_measurement = page.measure(MEASURE_PAGE)
    after = _selected_box(after_measurement)

    assert after[2] == pytest.approx(before[2], abs=TOLERANCE), (before, after)
    assert after[3] == pytest.approx(before[3], abs=TOLERANCE), (before, after)

    # The hidden native radio must not paint a second, mismatched ring.
    assert after_measurement["innerInputOutlineStyle"] == "none", after_measurement[
        "innerInputOutlineStyle"
    ]


def test_nav_rows_and_theme_switcher_share_one_width(page):
    """#23: the Appearance buttons and the divider overhung the nav rows."""
    measurement = page.measure(MEASURE_PAGE)
    options = measurement["themeOptions"]
    assert options is not None, "the theme switcher did not render"
    assert measurement["divider"] is not None, "the sidebar divider did not render"

    left = min(rect[0] for rect in measurement["rects"])
    right = max(rect[0] + rect[2] for rect in measurement["rects"])
    for label, rect in (("theme switcher", options), ("divider", measurement["divider"])):
        assert rect[0] == pytest.approx(left, abs=TOLERANCE), (label, left, rect)
        assert rect[0] + rect[2] == pytest.approx(right, abs=TOLERANCE), (label, right, rect)


def test_theme_switcher_follows_the_radio_keyboard_pattern(page):
    """The three theme buttons are a radiogroup; only the checked one is a tab stop."""
    measurement = page.measure(MEASURE_PAGE)
    choices = measurement["themeChoices"]
    assert [choice["value"] for choice in choices] == ["System", "Light", "Dark"], choices

    checked = [choice for choice in choices if choice["checked"] == "true"]
    assert len(checked) == 1, choices
    assert checked[0]["tabindex"] == "0", choices
    assert all(choice["tabindex"] == "-1" for choice in choices if choice["checked"] != "true"), (
        choices
    )

    for key, code, virtual_key, step in (
        ("ArrowRight", "ArrowRight", 39, 1),
        ("ArrowLeft", "ArrowLeft", 37, -1),
    ):
        # Each press makes the app switch its real theme and re-render, so a press
        # can land mid-render. Retry rather than treat that as a broken key.
        for _ in range(5):
            before = page.measure(MEASURE_PAGE)["themeChoices"]
            values = [choice["value"] for choice in before]
            index = values.index(
                next(choice["value"] for choice in before if choice["checked"] == "true")
            )
            expected = values[(index + step) % len(values)]

            choice_selector = json.dumps(f"[data-jizhang-theme-choice={json.dumps(values[index])}]")
            page.wait_js(
                f"(() => {{ const el = document.querySelector({choice_selector});"
                " if (!el) return false; el.focus();"
                " return document.activeElement === el; })()",
                timeout=30,
            )
            page.press(key, code, virtual_key)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                after = page.measure(MEASURE_PAGE)["themeChoices"]
                if any(
                    choice["value"] == expected and choice["checked"] == "true" for choice in after
                ):
                    break
                time.sleep(0.3)
            else:
                continue
            assert next(c for c in after if c["value"] == expected)["tabindex"] == "0", after
            break
        else:
            raise AssertionError(f"{key} did not move the selection: {after}")


def test_streamlit_theme_menu_still_matches_what_theme_bridge_drives(page):
    """The coupling safety net for the theme switcher.

    ``theme_bridge.html`` has no public API to reach Streamlit's theme menu, so it
    clicks ``stMainMenuButton`` and the ``stMainMenuItem-theme-*`` items. A Streamlit
    upgrade that renames either test id breaks the switcher silently. This fails
    loudly instead, and the fix is confined to ``chooseTheme``/``readThemeChoice``.
    """
    page.wait_js("!!document.querySelector(\"[data-testid='stMainMenuButton']\")", timeout=30)
    page.press("Escape", "Escape", 27)
    opened = False
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        page.evaluate("document.querySelector(\"[data-testid='stMainMenuButton']\").click()")
        time.sleep(0.5)
        if page.evaluate(
            "!!document.querySelector(\"[data-testid='stMainMenuItem-theme-Light']\")"
        ):
            opened = True
            break
    assert opened, "Streamlit's theme menu never exposed stMainMenuItem-theme-* to the bridge"

    hooks = page.evaluate(
        "['stMainMenuButton', 'stMainMenuItem-theme-System', 'stMainMenuItem-theme-Light',"
        " 'stMainMenuItem-theme-Dark'].map((testid) => Boolean(document.querySelector("
        '`[data-testid="${testid}"]`)))'
    )
    assert hooks == [True, True, True, True], hooks
    page.press("Escape", "Escape", 27)


def test_add_transaction_controls_all_reach_the_height_theme_css_declares(page):
    """The 42px rule must reach six different rendered widgets, not just the file."""
    page.select_page("Transactions")
    page.click(
        "[...document.querySelectorAll('button')]"
        ".find((el) => el.textContent.trim() === 'Add transaction')"
    )
    page.wait_js(f"!!document.querySelector({json.dumps(FORM_SELECTORS['submit'])})", timeout=45)

    heights = page.measure(MEASURE_FORM)
    assert None not in heights.values(), heights
    assert len(set(heights.values())) == 1, heights
    assert next(iter(heights.values())) == pytest.approx(42, abs=TOLERANCE), heights
