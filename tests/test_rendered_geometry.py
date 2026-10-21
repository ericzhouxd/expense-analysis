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

import base64
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
# The Edit table option is one nested node inside the segmented control; the
# shortest match is the element that actually wraps the option.
EDIT_TABLE_SELECTOR = (
    "[...document.querySelectorAll('label, button, p, div')]"
    ".filter((el) => el.textContent.trim() === 'Edit table')"
    ".sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length)[0]"
)
REVIEW_CHANGES_READY = (
    "[...document.querySelectorAll('button')]"
    ".some((b) => b.textContent.trim().startsWith('Review changes'))"
)

# Exactly the selectors theme.css sizes, so a passing check means the rule reached
# the rendered control rather than merely existing in the stylesheet.
FORM_SELECTORS = {
    "date": ".st-key-add_transaction_date [data-testid='stTextInputRootElement']",
    "description": ".category-entry input[name=description]",
    "merchant": ".category-entry input[name=merchant]",
    "amount": ".st-key-add_transaction_amount [data-testid='stNumberInputContainer']",
    "category": ".category-entry .category-input-group",
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

MEASURE_DISABLED_PRIMARY = """
(() => {
  // color(...) channels are 0-1; rgb() channels are 0-255.
  const parse = (value) => {
    const scale = value.startsWith('color(') ? 255 : 1;
    return (value.match(/[\\d.]+/g) || []).map((n, i) => (i < 3 ? Number(n) * scale : Number(n)));
  };
  const luminance = (rgb) => rgb.slice(0, 3).map((v) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  }).reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
  const button = [...document.querySelectorAll('button')]
    .find((el) => el.textContent.trim().startsWith('Review changes'));
  if (!button) return null;
  const style = getComputedStyle(button);
  const foreground = parse(style.color);
  const background = parse(style.backgroundColor);
  const alpha = foreground.length > 3 ? foreground[3] : 1;
  const base = background.length > 3 && background[3] === 0
    ? parse(getComputedStyle(document.querySelector('.stApp')).backgroundColor)
    : background;
  const composited = foreground.slice(0, 3).map((v, i) => alpha * v + (1 - alpha) * base[i]);
  const first = luminance(composited);
  const second = luminance(base);
  return JSON.stringify({
    disabled: button.disabled,
    backgroundAlpha: background.length > 3 ? background[3] : 1,
    contrast: (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05),
  });
})()
"""


MEASURE_ACTION_ROW = """
(() => {
  const box = (el) => {
    const r = el.getBoundingClientRect();
    return {x: +r.x.toFixed(2), y: +r.y.toFixed(2), right: +r.right.toFixed(2),
            w: +r.width.toFixed(2), h: +r.height.toFixed(2)};
  };
  const button = (label) => [...document.querySelectorAll('button')]
    .find((el) => el.textContent.trim() === label)
    || [...document.querySelectorAll('button')]
      .find((el) => el.textContent.trim().startsWith(label));
  const editor = document.querySelector("[data-testid='stDataFrame']");
  const add = button('Add transaction');
  const review = button('Review changes');
  const discard = button('Discard edits / reload');
  return JSON.stringify({
    editor: editor ? box(editor) : null,
    add: add ? box(add) : null,
    review: review ? box(review) : null,
    discard: discard ? box(discard) : null,
  });
})()
"""


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


def _wait_for(
    url: str,
    *,
    timeout: float,
    interval: float = 0.25,
    process: subprocess.Popen[bytes] | None = None,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise AssertionError(
                f"Process exited with code {process.returncode} before {url} became reachable"
            )
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
                if "error" in message:
                    raise AssertionError(f"CDP command {method} failed: {message['error']}")
                return message

    def evaluate(self, expression: str):
        result = self._command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if "exceptionDetails" in result["result"]:
            raise AssertionError(
                f"Browser JavaScript failed: {result['result']['exceptionDetails']}"
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
        """Wait until the target is stationary and its centre receives pointer events."""
        deadline = time.monotonic() + timeout
        previous = None
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            centre = self.evaluate(
                "(() => { const el = " + expression + "; if (!el) return null;"
                " const r = el.getBoundingClientRect();"
                " if (!r.width || !r.height) return null;"
                " const x = r.x + r.width / 2, y = r.y + r.height / 2;"
                " const hit = document.elementFromPoint(x, y);"
                " if (!hit || !(el === hit || el.contains(hit))) return null;"
                " return [x, y]; })()"
            )
            if centre is None or centre != previous:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= 0.2:
                return float(centre[0]), float(centre[1])
            previous = centre
            time.sleep(0.05)
        raise AssertionError(f"element never became stable and clickable: {expression}")

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
        native_key = virtual_key
        if sys.platform == "darwin":
            native_key = {
                "Enter": 36,
                "Escape": 53,
                "ArrowLeft": 123,
                "ArrowRight": 124,
                "ArrowDown": 125,
                "ArrowUp": 126,
            }[code]
        for event_type in ("keyDown", "keyUp"):
            self._command(
                "Input.dispatchKeyEvent",
                {
                    "type": event_type,
                    "key": key,
                    "code": code,
                    "windowsVirtualKeyCode": virtual_key,
                    "nativeVirtualKeyCode": native_key,
                },
            )

    def page_for(self, name: str) -> str:
        return f"{NAV_ROWS}.find((el) => el.textContent.trim() === {json.dumps(name)})"

    def select_page(self, name: str, *, timeout: float = 45.0) -> None:
        self.click(self.page_for(name))
        title = {"Import / Export": "Import and export", "Settings": "Settings and privacy"}.get(
            name, name
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.measure(MEASURE_PAGE)["checkedPage"] == name and self.evaluate(
                "document.querySelector('.page-heading h1')?.textContent === "
                + json.dumps(title)
                + " && document.querySelector('.stApp')?.dataset.testScriptState === 'notRunning'"
            ):
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
def rendered_seed():
    return _seed_database


@pytest.fixture(scope="module")
def app_url(rendered_seed):
    """Boot the real app on a free port against a throwaway data directory."""
    with tempfile.TemporaryDirectory(
        prefix="expense-rendered-", ignore_cleanup_errors=True
    ) as work:
        env = {
            **os.environ,
            "EXPENSE_ANALYSIS_DATA_DIR": str(Path(work) / "data"),
            "EXPENSE_ANALYSIS_OUTPUT_DIR": str(Path(work) / "output"),
        }
        Path(env["EXPENSE_ANALYSIS_DATA_DIR"]).mkdir(parents=True)
        rendered_seed(env)

        # The browser audit must not load the user's private config.toml either.
        entrypoint = Path(work) / "audit_app.py"
        entrypoint.write_text(
            "from expense_analysis import ui\n"
            "from expense_analysis.config import AppConfig\n"
            "ui.load_config = AppConfig\n"
            "ui.render_app()\n"
        )
        (Path(work) / "static").symlink_to(PROJECT_ROOT / "static", target_is_directory=True)

        port = _free_port()
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(entrypoint),
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
            _wait_for(f"http://127.0.0.1:{port}/_stcore/health", timeout=60, process=server)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=15)


@pytest.fixture(scope="module")
def page(app_url):
    """A headless Chromium page parked on the running app."""
    binary = _find_chromium()
    debug_port = _free_port()
    with tempfile.TemporaryDirectory(
        prefix="expense-chromium-", ignore_cleanup_errors=True
    ) as profile:
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
            _wait_for(f"http://127.0.0.1:{debug_port}/json/list", timeout=30, process=browser)
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
                browser.wait(timeout=15)


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


@pytest.mark.parametrize("theme", ["Light", "Dark"])
@pytest.mark.parametrize("width", [1400, 390])
def test_budget_controls_match_date_field_proportions(page, theme, width):
    try:
        page.select_page("Budgets")
        page.wait_js("document.querySelectorAll('[data-testid=stNumberInput]').length === 3")
        page.click(f"document.querySelector('[data-jizhang-theme-choice={theme}]')")
        page.wait_js(
            f"document.querySelector('[data-jizhang-theme-choice={theme}]')"
            ".getAttribute('aria-checked') === 'true'"
        )
        page._command(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": 1000, "deviceScaleFactor": 1, "mobile": False},
        )
        measurements = page.measure("""
        JSON.stringify((() => {
          const date = document.querySelector('[data-testid=stDateInputField]');
          const reference = date.getBoundingClientRect().height /
            parseFloat(getComputedStyle(date.querySelector('[role=spinbutton]')).fontSize);
          const controls = [...document.querySelectorAll(
            '[data-testid=stTextInputRootElement], [data-testid=stNumberInputContainer], '
            + '[data-testid=stSelectbox] .react-aria-ComboBox > [role=group]')];
          return {reference, ratios: controls.map(el => el.getBoundingClientRect().height /
            parseFloat(getComputedStyle(el.querySelector('input')).fontSize))};
        })())
        """)
        assert len(measurements["ratios"]) == 8, measurements
        for ratio in measurements["ratios"]:
            assert ratio == pytest.approx(measurements["reference"], abs=0.05)
    finally:
        page._command("Emulation.clearDeviceMetricsOverride")
        page.evaluate(
            "new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
        )


def test_add_transaction_controls_all_reach_the_height_theme_css_declares(page):
    """Transaction controls share the native budget date field's compact height."""
    page.select_page("Transactions")
    page.click(
        "[...document.querySelectorAll('button')]"
        ".find((el) => el.textContent.trim() === 'Add transaction')"
    )
    page.wait_js(f"!!document.querySelector({json.dumps(FORM_SELECTORS['submit'])})", timeout=45)
    page.wait_js("!!document.querySelector('.category-entry input[name=description]')", timeout=45)

    heights = page.measure(MEASURE_FORM)
    assert None not in heights.values(), heights
    assert len(set(heights.values())) == 1, heights
    assert next(iter(heights.values())) == pytest.approx(35, abs=TOLERANCE), heights
    styles = page.measure("""JSON.stringify((() => {
      const native = document.querySelector(
        '.st-key-add_transaction_account [data-testid=stWidgetLabel] p');
      const custom = document.querySelector('.category-choice > span');
      return [native,custom].map(el => {
        const s = getComputedStyle(el); return [s.fontSize,s.textTransform,s.letterSpacing];
      });
    })())""")
    assert styles[0] == styles[1], styles
    if destination := os.environ.get("THEME_AUDIT_SCREENSHOTS"):
        folder = Path(destination)
        folder.mkdir(parents=True, exist_ok=True)
        screenshot = page._command("Page.captureScreenshot", {"format": "png"})
        (folder / "add-transaction.png").write_bytes(base64.b64decode(screenshot["result"]["data"]))


def test_disabled_primary_button_stays_readable_in_dark_mode(page):
    """A disabled primary button must not paint its dark label on the dark canvas.

    Streamlit paints disabled primary buttons with a transparent fill, but the
    theme still forced the dark ink colour, so the label vanished on the near-black
    canvas. The theme must keep a visible fill and a readable label in both themes.
    """
    # The previous check may have left the Add transaction dialog open.
    page.press("Escape", "Escape", 27)
    page.select_page("Transactions")
    page.wait_js("document.body.innerText.includes('Edit table')", timeout=45)
    page.click(EDIT_TABLE_SELECTOR)
    page.wait_js(REVIEW_CHANGES_READY, timeout=45)

    page.click(
        "[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Dark')"
    )
    page.wait_js("document.documentElement.dataset.jizhangTheme === 'dark'", timeout=30)
    page.wait_js(REVIEW_CHANGES_READY, timeout=45)

    measurement = json.loads(page.evaluate(MEASURE_DISABLED_PRIMARY))
    assert measurement is not None, "the Review changes button never rendered"
    assert measurement["disabled"] is True, measurement
    assert measurement["backgroundAlpha"] == 1, measurement
    assert measurement["contrast"] >= 4.5, measurement

    page.click(
        "[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'System')"
    )


def test_edit_table_actions_cluster_and_size_to_content(page):
    """The editor sizes to its rows and the actions sit right-aligned beneath it.

    A fixed 520px editor left blank space with few rows and pushed the actions
    down with many; half-width action columns stranded "Discard edits" in the
    middle of the page while the header button stayed right-aligned.
    """
    page.press("Escape", "Escape", 27)
    page.select_page("Transactions")
    page.wait_js("document.body.innerText.includes('Edit table')", timeout=45)
    page.click(EDIT_TABLE_SELECTOR)
    page.wait_js(REVIEW_CHANGES_READY, timeout=45)
    page.wait_js("!!document.querySelector(\"[data-testid='stDataFrame']\")", timeout=45)

    boxes = page.measure(MEASURE_ACTION_ROW)
    assert None not in boxes.values(), boxes
    # Two seeded rows: 48px chrome + 2 * 35px rows, floored at 120.
    assert boxes["editor"]["h"] == pytest.approx(120, abs=TOLERANCE), boxes
    # Discard shares the header button's right edge; Review sits just beside it.
    assert boxes["discard"]["right"] == pytest.approx(boxes["add"]["right"], abs=4), boxes
    assert 0 <= boxes["discard"]["x"] - boxes["review"]["right"] <= 40, boxes
    # The actions stay next to the data instead of drifting below a taller grid.
    assert boxes["review"]["y"] - (boxes["editor"]["y"] + boxes["editor"]["h"]) <= 40, boxes


def test_table_date_editor_keeps_iso_order_without_extra_text_outlines(page):
    page.select_page("Transactions")
    page.wait_js("document.body.innerText.includes('Edit table')")
    if not page.evaluate(REVIEW_CHANGES_READY):
        page.click(EDIT_TABLE_SELECTOR)
    page.wait_js(REVIEW_CHANGES_READY)
    canvas = "document.querySelector('[data-testid=stDataFrame] canvas')"
    page.wait_js(
        f"!!{canvas} && {canvas}.getBoundingClientRect().width > 0"
        f" && {canvas}.getBoundingClientRect().height > 0"
    )
    page.centre_of("document.querySelector('[data-testid=stDataFrame] .dvn-scroller')")
    box = page.measure(f"JSON.stringify({canvas}.getBoundingClientRect().toJSON())")
    # Delete is the first column; select Date in the first synthetic row.
    for event_type in ("mousePressed", "mouseReleased"):
        page._command(
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": box["x"] + 70,
                "y": box["y"] + 49,
                "button": "left",
                "clickCount": 1,
                "buttons": 1 if event_type == "mousePressed" else 0,
            },
        )
    page.wait_js(f"document.activeElement === {canvas}")
    page.evaluate(
        "new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    page.press("Enter", "Enter", 13)
    page.wait_js("!!document.querySelector('.gdg-clip-region textarea, .gdg-clip-region input')")
    geometry = page.measure("""
    JSON.stringify((() => {
      const input = document.querySelector('.gdg-clip-region textarea, .gdg-clip-region input');
      return {value:input.value, outline:getComputedStyle(input).outlineStyle};
    })())
    """)
    assert geometry["value"] == "2026-07-30", geometry
    assert geometry["outline"] == "none", geometry
    page.press("Escape", "Escape", 27)


def test_calendar_selection_updates_validated_date_and_saves(page):
    page.press("Escape", "Escape", 27)
    page.select_page("Transactions")
    page.click("document.querySelector('.st-key-open_add_transaction button')")
    page.wait_js("!!document.querySelector('.date-calendar-button')")
    text = "document.querySelector('.st-key-add_transaction_date input')"
    # Open the themed calendar with Enter, choose the previous day, and save.
    # This exercises both keyboard interception and the browser's input events.
    page.evaluate(
        "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call("
        f"{text}, '2026-07-23'); {text}.dispatchEvent(new Event('input', {{bubbles:true}}))"
    )
    page.evaluate("document.querySelector('.date-calendar-button').focus()")
    page.press("Enter", "Enter", 13)
    page.wait_js("document.activeElement.getAttribute('aria-label') === '2026-07-23'")
    page.press("ArrowLeft", "ArrowLeft", 37)
    page.press("Enter", "Enter", 13)
    page.wait_js(f"{text}.value === '2026-07-22'")
    for selector, value in (
        (".category-entry input[name=description]", "Synthetic calendar purchase"),
        (".st-key-add_transaction_amount input", "19.25"),
    ):
        page.evaluate(f"document.querySelector({json.dumps(selector)}).focus()")
        page._command("Input.insertText", {"text": value})
    page.click("document.querySelector('.st-key-add_transaction_submit button')")
    page.wait_js("!document.querySelector('.date-calendar-button')")
    page.wait_js("document.body.innerText.includes('Transaction saved.')")
    # View reveals the persisted record, including when the table was selected.
    page.click("document.querySelector('.st-key-view_saved_transaction button')")
    page.wait_js("document.body.innerText.includes('Synthetic calendar purchase')")
    page.wait_js("document.body.textContent.includes('Jul 22')")


def test_live_category_suggestions_manual_override_and_save(page):
    page.select_page("Transactions")
    page.click("document.querySelector('.st-key-open_add_transaction button')")
    page.wait_js("!!document.querySelector('.category-entry input[name=description]')")

    def type_field(name, value):
        page.evaluate(f"document.querySelector('.category-entry input[name={name}]').focus()")
        page.evaluate(f"document.querySelector('.category-entry input[name={name}]').select()")
        page._command("Input.insertText", {"text": value})

    type_field("description", "groceries")
    assert page.evaluate("document.activeElement.name === 'description'")
    assert page.evaluate(
        "document.querySelector('.category-entry input[name=category]').value === 'Food'"
    )
    page.wait_js("document.querySelector('.category-entry input[name=category]').value === 'Food'")
    type_field("description", "coffee")
    page.wait_js(
        "document.querySelector('.category-entry input[name=category]').value === 'Dining Out'"
    )
    type_field("category", "Special purchases")
    type_field("merchant", "Synthetic coffee shop")
    page.evaluate("new Promise(resolve => setTimeout(resolve, 400))")
    assert (
        page.evaluate("document.querySelector('.category-entry input[name=category]').value")
        == "Special purchases"
    )
    page.evaluate("document.querySelector('.st-key-add_transaction_amount input').focus()")
    page._command("Input.insertText", {"text": "5.25"})
    type_field("description", "Synthetic live category purchase")
    page.click("document.querySelector('.st-key-add_transaction_submit button')")
    page.wait_js("document.body.innerText.includes('Transaction saved.')")
    page.click("document.querySelector('.st-key-view_saved_transaction button')")
    page.wait_js("document.body.innerText.includes('Synthetic live category purchase')")
    assert "special purchases" in page.evaluate("document.body.innerText").lower()
    page.click("document.querySelector('.st-key-open_add_transaction button')")
    page.wait_js("!!document.querySelector('.category-entry input[name=description]')")
    assert (
        page.evaluate("document.querySelector('.category-entry input[name=description]').value")
        == ""
    )
    page.press("Escape", "Escape", 27)


# Every page that groups content under a heading, and the fewest panels it shows
# with the synthetic seed. Transactions is a single list with no sections.
SECTION_PAGES = {
    "Overview": 4,
    "Import / Export": 2,
    "Budgets": 1,
    "Advanced insights": 5,
    "Settings": 1,
}

MEASURE_SECTIONS = r"""
JSON.stringify([...document.querySelectorAll('.section-heading')].map(el => {
  const panel = el.closest("[class*='st-key-section-']");
  const title = el.querySelector('h2');
  const note = el.querySelector('span');
  const panelStyle = panel ? getComputedStyle(panel) : null;
  const titleStyle = title ? getComputedStyle(title) : null;
  const titleBox = title ? title.getBoundingClientRect() : null;
  const noteBox = note ? note.getBoundingClientRect() : null;
  return {
    title: title ? title.textContent.trim() : '',
    inPanel: !!panel,
    panelPadding: panelStyle ? parseFloat(panelStyle.paddingTop) : 0,
    panelBorder: panelStyle ? parseFloat(panelStyle.borderTopWidth) : 0,
    titleSize: titleStyle ? titleStyle.fontSize : '',
    titleBottom: titleBox ? titleBox.bottom : null,
    noteTop: noteBox ? noteBox.top : null,
  };
}))
"""


def test_sections_paint_as_one_panel_with_a_stacked_heading(page):
    """#10: section labels were chopped strips, so each section is now one surface."""
    measured: dict[str, list[dict]] = {}
    for name, minimum in SECTION_PAGES.items():
        page.select_page(name)
        page.wait_js("document.querySelector('.stApp').dataset.testScriptState === 'notRunning'")
        # Poll for the panels rather than awaiting animation frames: this tab paints
        # lazily, and a pending frame request would block the whole suite.
        page.wait_js(f"document.querySelectorAll('.section-heading').length >= {minimum}")
        sections = page.measure(MEASURE_SECTIONS)
        assert len(sections) >= minimum, (name, sections)
        measured[name] = sections

    for name, sections in measured.items():
        for section in sections:
            # The heading lives inside the painted panel rather than floating on the page.
            assert section["inPanel"], (name, section)
            assert section["panelPadding"] > 0, (name, section)
            assert section["panelBorder"] > 0, (name, section)
            assert section["title"], (name, section)
            if section["noteTop"] is not None:
                # The note sits under the title instead of competing for its line.
                assert section["noteTop"] >= section["titleBottom"] - TOLERANCE, (name, section)

    # One title size everywhere: the tabs share a single section language.
    assert (
        len({section["titleSize"] for sections in measured.values() for section in sections}) == 1
    )


def test_entry_shortcuts_dropdown_and_fast_save(page):
    page.press("Escape", "Escape", 27)
    page.select_page("Transactions")
    page.evaluate("document.activeElement.blur()")

    def key(name, code, number, modifiers=0):
        for event_type in ("keyDown", "keyUp"):
            page._command(
                "Input.dispatchKeyEvent",
                {
                    "type": event_type,
                    "key": name,
                    "code": code,
                    "windowsVirtualKeyCode": number,
                    "modifiers": modifiers,
                },
            )

    page.wait_js("typeof window.jizhangUiKeyHandler === 'function'")
    key("n", "KeyN", 78)
    page.wait_js("!!document.querySelector('.category-entry input[name=description]')")
    page.evaluate("document.querySelector('.category-entry input[name=description]').focus()")
    page._command("Input.insertText", {"text": "Synthetic coffee shortcut"})
    page.press("Enter", "Enter", 13)
    page.wait_js("document.activeElement.name === 'merchant'")
    key("Enter", "Enter", 13, 8)
    page.wait_js("document.activeElement.name === 'description'")
    page.press("Enter", "Enter", 13)
    page.press("Enter", "Enter", 13)
    page.wait_js("document.activeElement.name === 'category'")
    page.wait_js("document.activeElement.getAttribute('aria-expanded') === 'true'")
    page.press("Escape", "Escape", 27)
    page.wait_js("document.activeElement.getAttribute('aria-expanded') === 'false'")
    assert page.evaluate("!!document.querySelector('.st-key-add_transaction_submit button')")
    page.press("Enter", "Enter", 13)
    page.wait_js("!!document.activeElement.closest('.st-key-add_transaction_amount')")
    page._command("Input.insertText", {"text": "3.75"})
    assert page.evaluate(
        "document.querySelector('.st-key-add_transaction_payment_method input')"
        ".value === 'Apple Pay'"
    )
    key("Enter", "Enter", 13, 4 if sys.platform == "darwin" else 2)
    page.wait_js("!document.querySelector('.st-key-add_transaction_submit button')")
    page.wait_js("!!document.querySelector('.st-key-view_saved_transaction button')")
    page.click("document.querySelector('.st-key-view_saved_transaction button')")
    page.wait_js(
        "document.querySelector('.transaction-row.is-focused')?.textContent"
        ".includes('Synthetic coffee shortcut')"
    )
    assert page.evaluate(
        "document.querySelector('.transaction-row.is-focused').textContent.includes('Dining Out')"
    )


def test_editor_adapts_to_phone_and_restores_desktop_columns(page):
    page.press("Escape", "Escape", 27)
    page.select_page("Transactions")
    page.click(EDIT_TABLE_SELECTOR)
    page.wait_js(REVIEW_CHANGES_READY)
    try:
        page._command(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 390,
                "height": 844,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )
        page.wait_js("document.body.innerText.includes('Compact view')")
        sizes = page.measure("""JSON.stringify((() => {
            const box = document.querySelector('[data-testid=stDataFrame]').getBoundingClientRect();
            return {left:box.left, right:box.right, width:window.innerWidth};
        })())""")
        assert sizes["left"] >= 0 and sizes["right"] <= sizes["width"], sizes
    finally:
        page._command("Emulation.clearDeviceMetricsOverride")
    page.wait_js("!document.body.innerText.includes('Compact view')")


def test_date_feedback_and_separator_free_typing(page):
    page.press("Escape", "Escape", 27)
    page.select_page("Transactions")
    page.click("document.querySelector('.st-key-open_add_transaction button')")
    page.wait_js("!!document.querySelector('.date-calendar-button svg')")
    field = "document.querySelector('.st-key-add_transaction_date input')"
    page.evaluate(f"{field}.focus(); {field}.select()")
    page._command("Input.insertText", {"text": "20260230"})
    assert page.evaluate(f"{field}.value") == "2026-02-30"
    assert page.evaluate(f"{field}.getAttribute('aria-invalid')") == "true"
    assert "does not exist" in page.evaluate(
        "document.querySelector('.date-validation').textContent"
    )
    page.evaluate(f"{field}.select()")
    page._command("Input.insertText", {"text": "20261021"})
    assert page.evaluate(f"{field}.value") == "2026-10-21"
    assert page.evaluate(f"{field}.getAttribute('aria-invalid')") == "false"
    # Delete across a separator, then replace the date without typing punctuation.
    page.evaluate(f"{field}.setSelectionRange(5,5)")
    for kind in ("keyDown", "keyUp"):
        page._command(
            "Input.dispatchKeyEvent",
            {
                "type": kind,
                "key": "Backspace",
                "code": "Backspace",
                "windowsVirtualKeyCode": 8,
            },
        )
    assert page.evaluate(f"{field}.value") == "2021-02-1"
    page._command("Input.insertText", {"text": "6"})
    assert page.evaluate(f"{field}.value") == "2026-10-21"
    page.press("Escape", "Escape", 27)
