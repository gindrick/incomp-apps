from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .base import Post, ScraperBase

logger = logging.getLogger(__name__)


def _deep_get(obj: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
        if obj is None:
            return None
    return obj


def _extract_posts(responses: list[str]) -> list[dict]:
    for text in responses:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue

        # Try several known Voyager API response shapes
        elements = (
            data.get("elements")
            or _deep_get(data, "data", "elements")
            or _deep_get(data, "data", "feedDashUpdatesByOrganization", "elements")
            or _deep_get(data, "data", "organizationDashUpdatesByOrganization", "elements")
        )
        if elements and isinstance(elements, list):
            posts = _parse_elements(elements)
            if posts:
                return posts

        # Nested: search one level deeper for any key containing "elements"
        if isinstance(data.get("data"), dict):
            for v in data["data"].values():
                if isinstance(v, dict):
                    els = v.get("elements")
                    if els and isinstance(els, list):
                        posts = _parse_elements(els)
                        if posts:
                            return posts

    return []


def _parse_elements(elements: list) -> list[dict]:
    posts = []
    for el in elements:
        # Text — try current and legacy Voyager paths
        text = (
            _deep_get(el, "commentary", "text", "text")
            or _deep_get(el, "value", "com.linkedin.voyager.feed.render.UpdateV2", "commentary", "text", "text")
            or ""
        )

        # Timestamp in milliseconds
        created_ms = (
            el.get("createdAt")
            or el.get("publishedAt")
            or _deep_get(el, "value", "com.linkedin.voyager.feed.render.UpdateV2", "updateMetadata", "publishedAt")
        )
        published_at = None
        if created_ms:
            try:
                published_at = datetime.fromtimestamp(int(created_ms) / 1000, tz=timezone.utc)
            except (ValueError, OSError):
                pass

        reactions = int(_deep_get(el, "reactionSummary", "count") or 0)
        comments = int(_deep_get(el, "commentSummary", "count") or 0)

        # Post URN → URL
        urn = (
            el.get("updateUrn")
            or el.get("entityUrn")
            or _deep_get(el, "value", "com.linkedin.voyager.feed.render.UpdateV2", "updateMetadata", "updateUrn")
            or ""
        )
        post_url = f"https://www.linkedin.com/feed/update/{urn}/" if urn else ""

        if not text and not post_url:
            continue

        posts.append({
            "url": post_url,
            "published_at": published_at,
            "text": text,
            "reactions": reactions,
            "comments": comments,
        })

    return posts


def _parse_relative_date(text: str) -> datetime | None:
    """Fallback for DOM timestamps that are relative strings."""
    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago", text, re.IGNORECASE)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    delta_map = {
        "second": timedelta(seconds=n), "minute": timedelta(minutes=n),
        "hour": timedelta(hours=n), "day": timedelta(days=n),
        "week": timedelta(weeks=n), "month": timedelta(days=n * 30),
        "year": timedelta(days=n * 365),
    }
    return datetime.now(timezone.utc) - delta_map[unit]


class LinkedInScraper(ScraperBase):
    PLATFORM = "linkedin"

    @classmethod
    def login(cls, page, config: dict) -> bool:
        username = os.environ.get("LI_USERNAME", "")
        password = os.environ.get("LI_PASSWORD", "")

        if not username or not password:
            logger.warning("LinkedIn: credentials not set — set LI_USERNAME / LI_PASSWORD in .env")
            return False

        logger.info("LinkedIn: logging in as %s", username)
        try:
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)

            # LinkedIn serves two login page variants — try both selectors.
            email_field = None
            for sel in ("#username", 'input[type="email"]', 'input[name="session_key"]'):
                try:
                    page.wait_for_selector(sel, timeout=5_000)
                    email_field = sel
                    break
                except Exception:
                    pass

            if email_field is None:
                if "checkpoint" in page.url or "challenge" in page.url:
                    logger.warning(
                        "LinkedIn: verification challenge — run 'uv run python setup_session.py' to complete login manually"
                    )
                else:
                    logger.warning("LinkedIn: login form not found at %s", page.url)
                return False

            page.fill(email_field, username)
            page.fill("#password", password)
            page.click('[type="submit"]')
            page.wait_for_url(
                re.compile(r"linkedin\.com/(feed|in/|mynetwork|jobs)"),
                timeout=20_000,
            )
            logger.info("LinkedIn: login successful")
            return True
        except Exception as exc:
            if "checkpoint" in page.url or "challenge" in page.url:
                logger.warning(
                    "LinkedIn: verification challenge after login — run 'uv run python setup_session.py' to complete login manually"
                )
            else:
                logger.warning("LinkedIn: login failed — %s", exc)
            return False

    def get_profile_name(self) -> str:
        parts = self.url.rstrip("/").split("/")
        for i, part in enumerate(parts):
            if part == "company" and i + 1 < len(parts):
                return parts[i + 1]
        return parts[-1]

    def get_posts(self) -> list[Post]:
        profile_name = self.get_profile_name()
        logger.info("LinkedIn: scraping %s", self.url)

        voyager_responses: list[str] = []

        def handle_response(response):
            try:
                if "/voyager/api/" not in response.url:
                    return
                body = response.body()
                text = body.decode("utf-8", errors="replace")
                if len(text) > 200:
                    voyager_responses.append(text)
            except Exception:
                pass

        try:
            self.page.on("response", handle_response)
            self.page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)
            self.page.wait_for_timeout(3_000)
            self.random_delay(2, 4)

            for _ in range(4):
                self.page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                self.random_delay(1.5, 3)
        except Exception as exc:
            logger.warning("LinkedIn: failed to load %s — %s", self.url, exc)
            return []
        finally:
            self.page.remove_listener("response", handle_response)

        logger.info("LinkedIn: captured %d Voyager responses for %s", len(voyager_responses), profile_name)

        raw_posts = _extract_posts(voyager_responses)

        if not raw_posts:
            logger.warning("LinkedIn: no posts in API responses for %s — falling back to DOM", profile_name)
            raw_posts = self._extract_from_dom()

        if not raw_posts:
            logger.warning("LinkedIn: no posts found for %s — run temp/li_debug.py to diagnose", profile_name)
            return []

        logger.info("LinkedIn: extracted %d raw posts for %s", len(raw_posts), profile_name)

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_back)
        posts: list[Post] = []

        for i, raw in enumerate(raw_posts[:12]):
            published_at = raw["published_at"]
            if published_at and published_at < cutoff:
                continue

            post_url = raw["url"] or self.url
            screenshot_file = self._screenshot_post(post_url, f"linkedin_{profile_name}_{i + 1}.png") if raw["url"] else ""

            posts.append(Post(
                platform=self.PLATFORM,
                profile=profile_name,
                url=post_url,
                published_at=published_at or datetime.now(timezone.utc),
                text=raw["text"][:500],
                reactions=raw["reactions"],
                comments=raw["comments"],
                shares=0,
                screenshot_path=screenshot_file,
            ))

        logger.info("LinkedIn: collected %d posts from %s", len(posts), profile_name)
        return posts

    def _extract_from_dom(self) -> list[dict]:
        """DOM fallback — used if Voyager API responses don't yield posts."""
        try:
            html_content = self.page.content()
        except Exception:
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")

        # Posts have data-urn="urn:li:activity:..." — more stable than class names
        containers = soup.find_all(attrs={"data-urn": re.compile(r"urn:li:activity:")})
        if not containers:
            # Fallback class-based selectors
            containers = soup.find_all("div", class_=re.compile(r"feed-shared-update-v2|occludable-update"))

        posts = []
        for el in containers[:15]:
            urn = el.get("data-urn", "")
            post_url = f"https://www.linkedin.com/feed/update/{urn}/" if urn else ""

            time_el = el.find("time")
            published_at = None
            if time_el:
                ts = time_el.get("datetime", "")
                try:
                    published_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    published_at = _parse_relative_date(time_el.get_text())

            text_el = el.find("span", class_=re.compile(r"break-words|update-components-text"))
            text = text_el.get_text(separator=" ", strip=True) if text_el else ""

            reactions, comments = 0, 0
            for btn in el.find_all(["button", "span"]):
                aria = btn.get("aria-label", "")
                t = btn.get_text(strip=True)
                if re.search(r"reaction", aria, re.I) and re.search(r"\d", t) and reactions == 0:
                    try:
                        reactions = int(re.sub(r"[^\d]", "", t))
                    except ValueError:
                        pass
                if re.search(r"comment", aria, re.I) and re.search(r"\d", t) and comments == 0:
                    try:
                        comments = int(re.sub(r"[^\d]", "", t))
                    except ValueError:
                        pass

            if not text and not post_url:
                continue

            posts.append({
                "url": post_url,
                "published_at": published_at,
                "text": text,
                "reactions": reactions,
                "comments": comments,
            })

        return posts

    def _screenshot_post(self, post_url: str, filename: str) -> str:
        if not self.screenshot_dir or not post_url or "linkedin.com" not in post_url:
            return ""
        try:
            self.page.goto(post_url, wait_until="domcontentloaded", timeout=15_000)
            self.random_delay(1, 2)
            path = os.path.join(self.screenshot_dir, filename)
            self.page.screenshot(path=path, full_page=False)
            return filename
        except Exception as exc:
            logger.debug("LinkedIn: screenshot failed for %s — %s", post_url, exc)
            return ""
