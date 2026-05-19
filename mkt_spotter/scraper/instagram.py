from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from .base import Post, ScraperBase

logger = logging.getLogger(__name__)


def _extract_posts(responses: list[str]) -> list[dict]:
    for text in responses:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            continue

        # New format (2025+): xdt_api__v1__feed__user_timeline_graphql_connection
        posts = _parse_timeline_graphql_connection(data)
        if posts:
            return posts

        # Legacy format: web_profile_info → data.user.edge_owner_to_timeline_media.edges
        user = (data.get("data") or {}).get("user") or {}
        edges = (user.get("edge_owner_to_timeline_media") or {}).get("edges") or []
        if edges:
            return _parse_timeline_edges(edges)

        # Legacy: /api/v1/feed/user/{id}/ format: {"items": [...]}
        items = data.get("items") or []
        if items and isinstance(items[0], dict) and "taken_at" in items[0]:
            return _parse_feed_items(items)

    return []


def _parse_timeline_graphql_connection(data: dict) -> list[dict]:
    conn = ((data.get("data") or {}).get("xdt_api__v1__feed__user_timeline_graphql_connection") or {})
    edges = conn.get("edges") or []
    posts = []
    for edge in edges:
        node = edge.get("node") or {}
        shortcode = node.get("code") or node.get("shortcode") or ""
        taken_at = node.get("taken_at")
        published_at = datetime.fromtimestamp(taken_at, tz=timezone.utc) if taken_at else None
        caption = node.get("caption") or {}
        text = caption.get("text", "") if isinstance(caption, dict) else str(caption or "")
        reactions = node.get("like_count") or 0
        comments = node.get("comment_count") or 0
        if shortcode:
            posts.append({
                "shortcode": shortcode,
                "published_at": published_at,
                "text": text,
                "reactions": reactions,
                "comments": comments,
            })
    return posts


def _parse_timeline_edges(edges: list) -> list[dict]:
    posts = []
    for edge in edges:
        node = edge.get("node", {})
        shortcode = node.get("shortcode", "")
        taken_at = node.get("taken_at_timestamp")
        published_at = datetime.fromtimestamp(taken_at, tz=timezone.utc) if taken_at else None
        caption_edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
        text = caption_edges[0]["node"]["text"] if caption_edges else ""
        reactions = (node.get("edge_liked_by") or {}).get("count", 0)
        comments = (node.get("edge_media_to_comment") or {}).get("count", 0)
        posts.append({
            "shortcode": shortcode,
            "published_at": published_at,
            "text": text,
            "reactions": reactions,
            "comments": comments,
        })
    return posts


def _parse_feed_items(items: list) -> list[dict]:
    posts = []
    for item in items:
        shortcode = item.get("code") or item.get("shortcode", "")
        taken_at = item.get("taken_at")
        published_at = datetime.fromtimestamp(taken_at, tz=timezone.utc) if taken_at else None
        caption = item.get("caption") or {}
        text = caption.get("text", "") if isinstance(caption, dict) else ""
        reactions = item.get("like_count", 0)
        comments = item.get("comment_count", 0)
        posts.append({
            "shortcode": shortcode,
            "published_at": published_at,
            "text": text,
            "reactions": reactions,
            "comments": comments,
        })
    return posts


class InstagramScraper(ScraperBase):
    PLATFORM = "instagram"

    @classmethod
    def login(cls, page, config: dict) -> bool:
        username = os.environ.get("IG_USERNAME", "")
        password = os.environ.get("IG_PASSWORD", "")

        if not username or not password:
            logger.warning("Instagram: credentials not set — set IG_USERNAME / IG_PASSWORD in .env")
            return False

        logger.info("Instagram: logging in as %s", username)
        try:
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3_000)

            # Cookie consent must be dismissed before the login form becomes interactive.
            for btn in page.locator("button, [role=button]").all():
                try:
                    text = btn.inner_text()
                    if any(kw in text.lower() for kw in ("allow", "accept", "decline", "odmítnout", "povolit", "erlauben", "accepter", "alle cookies")):
                        if btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(2_000)
                            break
                except Exception:
                    pass

            # Instagram login form uses input[name="username"] or input[name="email"] depending on variant.
            username_sel = None
            for sel in ('input[name="username"]', 'input[name="email"]'):
                try:
                    page.wait_for_selector(sel, timeout=5_000)
                    username_sel = sel
                    break
                except Exception:
                    pass

            if username_sel is None:
                raise RuntimeError("Login form not found — cookie consent may not have been dismissed")

            page.fill(username_sel, username)
            page.fill('input[type="password"]', password)

            # Submit: try type=submit button, fall back to Enter key
            submit = page.locator('button[type="submit"]')
            if submit.count() > 0 and submit.is_visible():
                submit.click()
            else:
                page.press('input[type="password"]', "Enter")

            page.wait_for_url(
                re.compile(r"instagram\.com/(?!accounts/login)"),
                timeout=20_000,
            )
            page.wait_for_timeout(2_000)

            # Dismiss post-login modals ("Save login info?", "Turn on notifications?")
            for _ in range(2):
                dismissed = False
                for btn in page.locator("button").all():
                    try:
                        text = btn.inner_text()
                        if any(kw in text.lower() for kw in ("not now", "teď ne", "jetzt nicht", "pas maintenant", "skip")):
                            if btn.is_visible():
                                btn.click()
                                page.wait_for_timeout(1_500)
                                dismissed = True
                                break
                    except Exception:
                        pass
                if not dismissed:
                    break

            logger.info("Instagram: login successful")
            return True
        except Exception as exc:
            if "challenge" in page.url or "two_factor" in page.url:
                logger.warning(
                    "Instagram: 2FA/challenge required — run 'uv run python setup_session.py' once to save your session"
                )
            else:
                logger.warning("Instagram: login failed — %s", exc)
            return False

    def get_profile_name(self) -> str:
        return self.url.rstrip("/").split("/")[-1].lstrip("@")

    def get_posts(self) -> list[Post]:
        profile_name = self.get_profile_name()
        logger.info("Instagram: scraping %s", self.url)

        api_responses: list[str] = []

        def handle_response(response):
            try:
                if not any(k in response.url for k in ("web_profile_info", "/graphql", "/api/v1/feed/user")):
                    return
                body = response.body()
                text = body.decode("utf-8", errors="replace")
                if len(text) > 100:
                    api_responses.append(text)
            except Exception:
                pass

        try:
            self.page.on("response", handle_response)
            self.page.goto(self.url, wait_until="domcontentloaded", timeout=30_000)
            self.random_delay(2, 4)
            # Scroll to trigger lazy-loaded API calls
            for _ in range(3):
                self.page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                self.random_delay(1, 2)
        except Exception as exc:
            logger.warning("Instagram: failed to load %s — %s", self.url, exc)
            return []
        finally:
            self.page.remove_listener("response", handle_response)

        logger.info("Instagram: captured %d API responses for %s", len(api_responses), profile_name)

        raw_posts = _extract_posts(api_responses)
        logger.info("Instagram: extracted %d raw posts for %s", len(raw_posts), profile_name)

        if not raw_posts:
            logger.warning("Instagram: no posts found in API responses for %s — run temp/ig_debug.py to diagnose", profile_name)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_back)
        posts: list[Post] = []

        for i, raw in enumerate(raw_posts[:12]):
            published_at = raw["published_at"]
            if published_at and published_at < cutoff:
                continue

            shortcode = raw["shortcode"]
            post_url = f"https://www.instagram.com/p/{shortcode}/" if shortcode else self.url
            screenshot_file = self._screenshot_post(post_url, f"instagram_{profile_name}_{i + 1}.png")

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

        logger.info("Instagram: collected %d posts from %s", len(posts), profile_name)
        return posts

    def _screenshot_post(self, post_url: str, filename: str) -> str:
        if not self.screenshot_dir or not post_url:
            return ""
        try:
            self.page.goto(post_url, wait_until="domcontentloaded", timeout=15_000)
            self.random_delay(1, 2)
            path = os.path.join(self.screenshot_dir, filename)
            self.page.screenshot(path=path, full_page=False)
            return filename
        except Exception as exc:
            logger.debug("Instagram: screenshot failed for %s — %s", post_url, exc)
            return ""
