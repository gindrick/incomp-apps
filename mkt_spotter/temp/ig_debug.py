"""Run after setting IG_USERNAME / IG_PASSWORD in .env to inspect Instagram API responses."""
import json
import os
import re

from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright

api_responses: list[tuple[str, str]] = []  # (url, body)


def handle_response(response):
    try:
        if not any(k in response.url for k in ("web_profile_info", "/graphql", "/api/v1/feed")):
            return
        body = response.body()
        text = body.decode("utf-8", errors="replace")
        if len(text) > 100:
            api_responses.append((response.url, text))
    except Exception:
        pass


TARGET = "https://www.instagram.com/hettich_official/"

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900},
    )
    page = ctx.new_page()

    # Login
    page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle", timeout=30_000)
    page.wait_for_timeout(2_000)
    for btn in page.locator("button, [role=button]").all():
        try:
            t = btn.inner_text()
            if any(kw in t.lower() for kw in ("allow", "accept", "povolit", "alle cookies")):
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1_500)
                    break
        except Exception:
            pass

    page.wait_for_selector('input[name="username"]', timeout=10_000)
    page.fill('input[name="username"]', os.environ["IG_USERNAME"])
    page.fill('input[name="password"]', os.environ["IG_PASSWORD"])
    page.click('button[type="submit"]')
    try:
        page.wait_for_url(re.compile(r"instagram\.com/(?!accounts/login)"), timeout=15_000)
    except Exception as e:
        print("Login may have failed:", e)
    page.wait_for_timeout(3_000)

    # Dismiss dialogs
    for _ in range(2):
        for btn in page.locator("button").all():
            try:
                t = btn.inner_text().lower()
                if any(kw in t for kw in ("not now", "teď ne", "pas maintenant", "jetzt nicht", "skip")):
                    if btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(1_000)
                        break
            except Exception:
                pass

    # Load profile page and capture API responses
    page.on("response", handle_response)
    page.goto(TARGET, wait_until="networkidle", timeout=30_000)
    page.wait_for_timeout(3_000)

    print(f"\nCaptured {len(api_responses)} API responses:\n")
    for url, text in api_responses:
        print(f"URL: {url}")
        try:
            data = json.loads(text)
            print(f"  Keys: {list(data.keys())}")
            # Try to find edge lists
            if "data" in data and isinstance(data["data"], dict):
                user = data["data"].get("user", {})
                if user:
                    print(f"  data.user keys: {list(user.keys())[:10]}")
                    tl = user.get("edge_owner_to_timeline_media", {})
                    edges = tl.get("edges", [])
                    print(f"  timeline edges: {len(edges)}")
                    if edges:
                        node = edges[0]["node"]
                        print(f"  first post keys: {list(node.keys())[:15]}")
                        print(f"  shortcode: {node.get('shortcode')}")
                        print(f"  taken_at: {node.get('taken_at_timestamp')}")
                        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
                        print(f"  caption: {caption_edges[0]['node']['text'][:80] if caption_edges else '(none)'}")
                        print(f"  likes: {node.get('edge_liked_by', {}).get('count')}")
                        print(f"  comments: {node.get('edge_media_to_comment', {}).get('count')}")
        except Exception:
            print(f"  (non-JSON or parse error, len={len(text)})")
            print(f"  preview: {repr(text[:200])}")
        print()

    # Save largest for full analysis
    if api_responses:
        largest = max(api_responses, key=lambda x: len(x[1]))
        with open("temp/ig_api_largest.json", "w", encoding="utf-8") as f:
            f.write(largest[1])
        print(f"Saved largest response ({len(largest[1])} chars) to temp/ig_api_largest.json")

    browser.close()
