"""One-time session setup for platforms that require 2FA or manual login.

Run this script once on a machine with a visible display (not headless):
    uv run python setup_session.py

A browser window will open for each platform. Complete the login (including
any 2FA prompts), then press Enter in this terminal to save the session.
Sessions are stored in sessions/ and reused automatically by main.py.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

PLATFORMS = {
    "facebook": {
        "url": "https://www.facebook.com/login",
        "check_url": "facebook.com",
        "hint": "Log in to Facebook (complete any 2FA), then confirm you see your feed.",
    },
    "instagram": {
        "url": "https://www.instagram.com/accounts/login/",
        "check_url": "instagram.com",
        "hint": "Log in to Instagram (complete any 2FA), then confirm you see your home feed.",
    },
    "linkedin": {
        "url": "https://www.linkedin.com/login",
        "check_url": "linkedin.com/feed",
        "hint": "Log in to LinkedIn (complete any verification), then confirm you see your feed.",
    },
}


def setup_platform(name: str, info: dict) -> None:
    print(f"\n{'='*50}")
    print(f"  {name.upper()}")
    print(f"{'='*50}")
    print(info["hint"])
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=USER_AGENT,
        )
        page = context.new_page()
        page.goto(info["url"])

        input(f"Press Enter after you are fully logged in to {name.capitalize()}... ")

        state_path = str(SESSIONS_DIR / f"{name}_state.json")
        context.storage_state(path=state_path)
        print(f"✓  Session saved to {state_path}")
        browser.close()


def main() -> None:
    print("Spotter — Session Setup")
    print("This will open a browser for each platform.")
    print("Complete the login manually, then press Enter to save the session.\n")

    platforms_to_setup = []
    for name in PLATFORMS:
        existing = SESSIONS_DIR / f"{name}_state.json"
        if existing.exists():
            answer = input(f"Session for {name} already exists. Re-setup? [y/N]: ").strip().lower()
            if answer == "y":
                platforms_to_setup.append(name)
        else:
            platforms_to_setup.append(name)

    if not platforms_to_setup:
        print("All sessions already configured. Nothing to do.")
        return

    for name in platforms_to_setup:
        setup_platform(name, PLATFORMS[name])

    print("\nDone. Run 'uv run python main.py' to start scraping.")


if __name__ == "__main__":
    main()
