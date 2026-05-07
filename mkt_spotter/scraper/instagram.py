from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from .base import Post, ScraperBase

logger = logging.getLogger(__name__)


class InstagramScraper(ScraperBase):
    PLATFORM = "instagram"

    @classmethod
    def login(cls, page, config: dict) -> bool:
        username = os.environ.get("IG_USERNAME", "")
        password = os.environ.get("IG_PASSWORD", "")

        if not username or not password or "your_instagram" in username:
            logger.warning("Instagram: credentials not set — set IG_USERNAME / IG_PASSWORD in .env")
            return False

        logger.info("Instagram: logging in as %s", username)
        try:
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(2_000)

            # Cookie consent
            for selector in [
                'button:has-text("Allow all cookies")',
                'button:has-text("Accept all")',
            ]:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=3_000):
                        btn.click()
                        page.wait_for_timeout(1_000)
                        break
                except Exception:
                    pass

            page.fill('input[name="username"]', username)
            page.fill('input[name="password"]', password)
            page.click('button[type="submit"]')

            page.wait_for_url(
                re.compile(r"instagram\.com/(?!accounts/login)"),
                timeout=15_000,
            )
            page.wait_for_timeout(2_000)

            # Dismiss "Save login info?"
            for selector in ['button:has-text("Not now")', 'button:has-text("Not Now")']:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=3_000):
                        btn.click()
                        page.wait_for_timeout(1_000)
                        break
                except Exception:
                    pass

            # Dismiss "Turn on notifications?"
            for selector in ['button:has-text("Not now")', 'button:has-text("Not Now")']:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=3_000):
                        btn.click()
                        page.wait_for_timeout(1_000)
                        break
                except Exception:
                    pass

            logger.info("Instagram: login successful")
            return True
        except Exception as exc:
            logger.warning("Instagram: login failed — %s", exc)
            return False

    def get_profile_name(self) -> str:
        return self.url.rstrip("/").split("/")[-1].lstrip("@")

    def get_posts(self) -> list[Post]:
        profile_name = self.get_profile_name()
        logger.info("Instagram: scraping %s", self.url)

        try:
            self.page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
            self.random_delay(2, 3)
            html = self.page.content()
        except Exception as exc:
            logger.warning("Instagram: failed to load %s — %s", self.url, exc)
            return []

        soup = BeautifulSoup(html, "html.parser")

        # Post grid links: /p/<id>/
        post_links = soup.find_all("a", href=re.compile(r"/p/[A-Za-z0-9_-]+/"))
        seen: set[str] = set()
        unique_links: list[str] = []
        for a in post_links:
            href = a.get("href", "")
            if href not in seen:
                seen.add(href)
                unique_links.append(href)

        if not unique_links:
            logger.warning("Instagram: no post links found on %s", self.url)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_back)
        base_url = "https://www.instagram.com"
        posts: list[Post] = []

        for i, href in enumerate(unique_links[:12]):
            post_url = base_url + href
            try:
                self.page.goto(post_url, wait_until="domcontentloaded", timeout=20_000)
                self.random_delay(1.5, 3)
                post_html = self.page.content()
            except Exception as exc:
                logger.warning("Instagram: failed to load post %s — %s", post_url, exc)
                continue

            post_soup = BeautifulSoup(post_html, "html.parser")

            # Timestamp
            time_el = post_soup.find("time")
            published_at: datetime | None = None
            if time_el:
                try:
                    published_at = datetime.fromisoformat(
                        time_el.get("datetime", "").replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            if published_at and published_at < cutoff:
                continue

            # Caption via og:description meta
            meta = post_soup.find("meta", attrs={"property": "og:description"})
            text = meta.get("content", "") if meta else ""

            # Like / comment counts (Instagram often hides exact numbers)
            reactions, comments = 0, 0
            for span in post_soup.find_all("span"):
                t = span.get_text(strip=True)
                if re.match(r"^\d[\d,]*$", t):
                    val = int(t.replace(",", ""))
                    if reactions == 0:
                        reactions = val
                    elif comments == 0:
                        comments = val

            screenshot_file = ""
            try:
                article = self.page.locator("article").first
                screenshot_file = self.take_screenshot(article, f"instagram_{profile_name}_{i + 1}.png")
            except Exception:
                pass

            posts.append(Post(
                platform=self.PLATFORM,
                profile=profile_name,
                url=post_url,
                published_at=published_at or datetime.now(timezone.utc),
                text=text[:500],
                reactions=reactions,
                comments=comments,
                shares=0,
                screenshot_path=screenshot_file,
            ))
            self.random_delay(2, 4)

        logger.info("Instagram: collected %d posts from %s", len(posts), profile_name)
        return posts
