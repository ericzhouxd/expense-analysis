"""Exercise browser-test failures without starting an app or Chrome."""

import json
from unittest.mock import Mock

import pytest
import test_rendered_geometry as browser_tests


class ReplySocket:
    def __init__(self, reply):
        self.reply = reply
        self.sent = []

    def send(self, message):
        self.sent.append(json.loads(message))

    def recv(self, *, timeout):
        return json.dumps({"id": self.sent[-1]["id"], **self.reply})


@pytest.mark.parametrize(
    "platform,key,windows_code,native_code",
    [
        ("darwin", "Enter", 13, 36),
        ("darwin", "Escape", 27, 53),
        ("darwin", "ArrowLeft", 37, 123),
        ("darwin", "ArrowRight", 39, 124),
        ("darwin", "ArrowDown", 40, 125),
        ("darwin", "ArrowUp", 38, 126),
        ("linux", "Enter", 13, 13),
        ("win32", "ArrowLeft", 37, 37),
    ],
)
def test_key_events_use_the_platform_native_code(
    monkeypatch, platform, key, windows_code, native_code
):
    monkeypatch.setattr(browser_tests.sys, "platform", platform)
    socket = ReplySocket({"result": {}})
    browser_tests.Cdp(socket).press(key, key, windows_code)

    assert [message["params"]["type"] for message in socket.sent] == ["keyDown", "keyUp"]
    for message in socket.sent:
        assert message["method"] == "Input.dispatchKeyEvent"
        assert message["params"]["windowsVirtualKeyCode"] == windows_code
        assert message["params"]["nativeVirtualKeyCode"] == native_code


def test_browser_command_reports_protocol_errors():
    socket = ReplySocket({"error": {"code": -32602, "message": "Invalid parameters"}})
    with pytest.raises(AssertionError, match="Input.dispatchKeyEvent failed.*Invalid parameters"):
        browser_tests.Cdp(socket).press("Enter", "Enter", 13)


def test_browser_evaluation_reports_javascript_errors():
    socket = ReplySocket(
        {"result": {"result": {}, "exceptionDetails": {"text": "Uncaught TypeError"}}}
    )
    with pytest.raises(AssertionError, match="Browser JavaScript failed.*Uncaught TypeError"):
        browser_tests.Cdp(socket).evaluate("document.querySelector('.missing').value")


def test_startup_stops_waiting_when_the_process_exits(monkeypatch):
    process = Mock()
    process.poll.return_value = -6
    process.returncode = -6
    get = Mock(return_value=None)
    monkeypatch.setattr(browser_tests, "_get", get)

    with pytest.raises(AssertionError, match="Process exited with code -6"):
        browser_tests._wait_for("http://127.0.0.1:12345", timeout=30, process=process)
    get.assert_not_called()


def test_click_waits_for_a_stationary_unobstructed_target(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(browser_tests.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        browser_tests.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay)
    )
    socket = ReplySocket({"result": {}})
    page = browser_tests.Cdp(socket)
    # The button moves, then is briefly obscured, before settling at its final position.
    positions = iter([[10, 20], [15, 20], None, [30, 20]])
    monkeypatch.setattr(page, "evaluate", lambda expression: next(positions, [30, 20]))

    page.click("document.querySelector('button')")

    assert clock[0] >= 0.35
    assert len(socket.sent) == 2
    assert all(message["params"]["x"] == 30 for message in socket.sent)
    assert all(message["params"]["y"] == 20 for message in socket.sent)
