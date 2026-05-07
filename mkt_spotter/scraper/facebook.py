from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from .base import Post, ScraperBase

logger = logging.getLogger(__name__)

_RELATIVE_RE = re.compile(
    r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago", re.IGNORECASE
)


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
    text = text.strip().replace(",", "").replace(".", "")
    m = re.search(r"([\d]+)\s*([KkMm]?)", text)
    if not m:
        return 0
    num = float(m.group(1))
    suffix = m.group(2).upper()
    if suffix == "K":
        num *= 1_000
    elif suffix == "M":
        num *= 1_000_000
    return int(num)


class FacebookScraper(ScraperBase):
    PLATFORM = "facebook"

    @classmethod
    def login(cls, page, config: dict) -> bool:
        username = os.environ.get("FB_USERNAME", "")
        password = os.environ.get("FB_PASSWORD", "")

        if not username or not password or "your_facebook" in username:
            logger.warning("Facebook: credentials not set — set FB_USERNAME / FB_PASSWORD in .env")
            return False

        logger.info("Facebook: logging in as %s", username)
        try:
            page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=20_000)

            # Cookie consent before login form appears
            for selector in [
                'button:has-text("Allow all cookies")',
                'button:has-text("Accept all")',
                '[data-cookiebanner="accept_button"]',
            ]:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=3_000):
                        btn.click()
                        page.wait_for_timeout(1_000)
                        break
                except Exception:
                    pass

            page.fill("#email", username)
            page.fill("#pass", password)
            page.click('[name="login"]')

            page.wait_for_url(
                re.compile(r"facebook\.com/(home|feed|\?|$)"),
                timeout=15_000,
            )
            logger.info("Facebook: login successful")
            return True
        except Exception as exc:
            logger.warning("Facebook: login failed — %s", exc)
            return False

    def get_profile_name(self) -> str:
        return self.url.rstrip("/").split("/")[-1]

    def get_posts(self) -> list[Post]:
        profile_name = self.get_profile_name()
        logger.info("Facebook: scraping %s", self.url)

        try:
            self.page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
            self.random_delay(2, 4)

            # Scroll to load more posts
            for _ in range(4):
                self.page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                self.random_delay(1.5, 3)

            html = self.page.content()
        except Exception as exc:
            logger.warning("Facebook: failed to load %s — %s", self.url, exc)
            return []

        soup = BeautifulSoup(html, "html.parser")
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_back)
        posts: list[Post] = []

        articles = soup.find_all("div", attrs={"role": "article"})
        if not articles:
            logger.warning("Facebook: no articles found on %s", self.url)
            return []

        for i, article in enumerate(articles[:15]):
            # Timestamp — Facebook uses <abbr> with title or <a> with relative text
            time_el = article.find("abbr") or article.find(
                "a", href=re.compile(r"/posts/|/videos/|/photos/")
            )
            published_at = None
            if time_el:
                ts_text = time_el.get("title") or time_el.get_text()
                published_at = _parse_relative_date(ts_text)

            if published_at and published_at < cutoff:
                continue

            # Post text
            text_div = (
                article.find("div", attrs={"data-ad-comet-preview": "message"})
                or article.find("div", attrs={"data-testid": "post_message"})
            )
            text = text_div.get_text(separator=" ", strip=True) if text_div else ""

            # Engagement counts
            reactions, comments = 0, 0
            for span in article.find_all(["span", "a"]):
                aria = span.get("aria-label", "")
                t = span.get_text(strip=True)
                if re.search(r"react|like|love|haha|wow|sad|angry", aria, re.I) and re.search(r"\d", t):
                    if reactions == 0:
                        reactions = _parse_count(t)
                if re.search(r"comment", aria, re.I) and re.search(r"\d", t):
                    if comments == 0:
                        comments = _parse_count(t)

            screenshot_file = ""
            try:
                locator = self.page.locator('[role="article"]').nth(i)
                screenshot_file = self.take_screenshot(locator, f"facebook_{profile_name}_{i + 1}.png")
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

        logger.info("Facebook: collected %d posts from %s", len(posts), profile_name)
        return posts
