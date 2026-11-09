"""``expense-app``: serve the local web interface on 127.0.0.1."""

from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from .app import WEB_DIST, create_app

DEFAULT_PORT = 8765


def main() -> None:
    parser = argparse.ArgumentParser(description="Open the local 記帳 web app.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--no-browser", action="store_true", help="Start the server without opening a tab."
    )
    arguments = parser.parse_args()
    url = f"http://127.0.0.1:{arguments.port}"
    if not (WEB_DIST / "index.html").is_file():
        print(
            "The web interface is not built yet. Run:\n"
            "  npm --prefix web ci && npm --prefix web run build"
        )
    print(f"記帳 is running at {url} (local only). Press Ctrl+C to stop.")
    if not arguments.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    # The address is fixed: the ledger is private and must never listen on a network.
    uvicorn.run(create_app(), host="127.0.0.1", port=arguments.port, log_level="warning")


if __name__ == "__main__":
    main()
