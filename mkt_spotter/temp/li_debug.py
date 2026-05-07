"""Run after setting LI_USERNAME / LI_PASSWORD in .env to inspect LinkedIn Voyager API responses."""
import json
import os
import re

from dotenv import load_dotenv
load_dotenv()

from playwright.sync_api import sync_playwright

voyager_responses: list[tuple[str, str]] = []


def handle_response(response):
    try:
        if "/voyager/api/" not in response.url:
            return
        body = response.body()
        text = body.decode("utf-8", errors="replace")
        if len(text) > 200:
            voyager_responses.append((response.url, text))
    except Exception:
        pass


TARGET = "https://www.linkedin.com/company/henkel/posts/?feedView=all"

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900},
    )
    page = ctx.new_page()

    page.goto("https://www.linkedin.com/login", wait_until="networkidle", timeout=30_000)
    page.wait_for_selector("#username", timeout=10_000)
    page.fill("#username", os.environ["LI_USERNAME"])
    page.fill("#password", os.environ["LI_PASSWORD"])
    page.click('[type="submit"]')
    try:
        page.wait_for_url(re.compile(r"linkedin\.com/(feed|in/|mynetwork|jobs)"), timeout=15_000)
    except Exception as e:
        print("Login may have failed:", e)

    page.on("response", handle_response)
    page.goto(TARGET, wait_until="networkidle", timeout=30_000)
    page.wait_for_timeout(3_000)
    for _ in range(3):
        page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        page.wait_for_timeout(2_000)

    print(f"\nCaptured {len(voyager_responses)} Voyager API responses:\n")
    for url, text in voyager_responses:
        short_url = url.split("linkedin.com")[-1][:80]
        print(f"URL: {short_url} (len={len(text)})")
        try:
            data = json.loads(text)

            def show_elements(elements, label="elements"):
                if not elements or not isinstance(elements, list):
                    return
                print(f"  {label}: {len(elements)} items")
                el = elements[0]
                print(f"  first item keys: {list(el.keys())[:12]}")
                # Text
                text_val = (
                    (el.get("commentary") or {}).get("text", {}).get("text")
                    or (el.get("value") or {}).get(
                        "com.linkedin.voyager.feed.render.UpdateV2", {}
                    ).get("commentary", {}).get("text", {}).get("text")
                )
                if text_val:
                    print(f"  text: {repr(text_val[:80])}")
                # Timestamp
                ts = el.get("createdAt") or el.get("publishedAt")
                if ts:
                    from datetime import datetime, timezone
                    try:
                        dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
                        print(f"  createdAt: {ts} → {dt}")
                    except Exception:
                        print(f"  createdAt raw: {ts}")
                # Reactions / comments
                rs = el.get("reactionSummary") or {}
                cs = el.get("commentSummary") or {}
                print(f"  reactions: {rs.get('count')}  comments: {cs.get('count')}")
                # URN
                urn = el.get("updateUrn") or el.get("entityUrn", "")
                print(f"  urn: {urn}")

            # Try several known response shapes
            if "elements" in data:
                show_elements(data["elements"])
            elif isinstance(data.get("data"), dict):
                inner = data["data"]
                if "elements" in inner:
                    show_elements(inner["elements"], "data.elements")
                else:
                    for k, v in inner.items():
                        if isinstance(v, dict) and "elements" in v:
                            show_elements(v["elements"], f"data.{k}.elements")
                            break
        except Exception:
            print(f"  (non-JSON or parse error)")
            print(f"  preview: {repr(text[:200])}")
        print()

    if voyager_responses:
        largest = max(voyager_responses, key=lambda x: len(x[1]))
        with open("temp/li_voyager_largest.json", "w", encoding="utf-8") as f:
            f.write(largest[1])
        print(f"Saved largest response ({len(largest[1])} chars) to temp/li_voyager_largest.json")

    browser.close()
