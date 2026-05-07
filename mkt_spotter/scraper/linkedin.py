from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from .base import Post, ScraperBase

logger = logging.getLogger(__name__)

_RELATIVE_RE = re.compile(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago", re.IGNORECASE)


def _parse_relative_date(text: str) -> datetime | None:
    m = _RELATIVE_RE.search(text)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    delta_map = {
        "second": timedelta(seconds=n),
        "minute": timedelta(minutes=n),
        "hour": timedelta(hours=n),
        "day": timedelta(days=n),
        "week": timedelta(weeks=n),
        "month": timedelta(days=n * 30),
        "year": timedelta(days=n * 365),
    }
    return datetime.now(timezone.utc) - delta_map[unit]


def _parse_count(text: str) -> int:
    text = text.strip().replace(",", "")
    m = re.search(r"([\d.]+)\s*([KkMm]?)", text)
    if not m:
        return 0
    num = float(m.group(1))
    suffix = m.group(2).upper()
    if suffix == "K":
        num *= 1_000
    elif suffix == "M":
        num *= 1_000_000
    return int(num)


class LinkedInScraper(ScraperBase):
    PLATFORM = "linkedin"

    @classmethod
    def login(cls, page, config: dict) -> bool:
        username = os.environ.get("LI_USERNAME", "")
        password = os.environ.get("LI_PASSWORD", "")

        if not username or not password or "your_linkedin" in username:
            logger.warning("LinkedIn: credentials not set — set LI_USERNAME / LI_PASSWORD in .env")
            return False

        logger.info("LinkedIn: logging in as %s", username)
        try:
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(1_000)
            page.fill("#username", username)
            page.fill("#password", password)
            page.click('[type="submit"]')
            page.wait_for_url(
                re.compile(r"linkedin\.com/(feed|in/|mynetwork|jobs)"),
                timeout=15_000,
            )
            logger.info("LinkedIn: login successful")
            return True
        except Exception as exc:
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

        try:
            self.page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
            self.random_delay(2, 4)

            for _ in range(3):
                self.page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                self.random_delay(1.5, 3)

            html = self.page.content()
        except Exception as exc:
            logger.warning("LinkedIn: failed to load %s — %s", self.url, exc)
            return []

        soup = BeautifulSoup(html, "html.parser")
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_back)
        posts: list[Post] = []

        articles = soup.find_all("div", class_=re.compile(r"feed-shared-update-v2|occludable-update"))
        if not articles:
            articles = soup.find_all("li", class_=re.compile(r"profile-creator-shared-feed-update"))

        if not articles:
            logger.warning("LinkedIn: no posts found on %s", self.url)
            return []

        for i, article in enumerate(articles[:15]):
            time_el = article.find("time") or article.find(
                "span", class_=re.compile(r"time-badge|visually-hidden")
            )
            published_at = None
            if time_el:
                ts = time_el.get("datetime") or time_el.get_text()
                try:
                    published_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    published_at = _parse_relative_date(ts)

            if published_at and published_at < cutoff:
                continue

            text_el = article.find("span", class_=re.compile(r"break-words|update-components-text"))
            text = text_el.get_text(separator=" ", strip=True) if text_el else ""

            reactions, comments = 0, 0
            for btn in article.find_all(["button", "span"]):
                aria = btn.get("aria-label", "")
                t = btn.get_text(strip=True)
                if re.search(r"reaction", aria, re.I) and re.search(r"\d", t) and reactions == 0:
                    reactions = _parse_count(t)
                if re.search(r"comment", aria, re.I) and re.search(r"\d", t) and comments == 0:
                    comments = _parse_count(t)

            screenshot_file = ""
            try:
                locator = self.page.locator(
                    'div[class*="feed-shared-update-v2"], div[class*="occludable-update"], li[class*="profile-creator-shared-feed-update"]'
                ).nth(i)
                screenshot_file = self.take_screenshot(locator, f"linkedin_{profile_name}_{i + 1}.png")
            except Exception:
                pass

            posts.append(Post(
                platform=self.PLATFORM,
                profile=profile_name,
                url=self.url,
                published_at=published_at or datetime.now(timezone.utc),
                text=text[:500],
                reactions=reactions,
                comments=comments,
                shares=0,
                screenshot_path=screenshot_file,
            ))

        logger.info("LinkedIn: collected %d posts from %s", len(posts), profile_name)
        return posts
