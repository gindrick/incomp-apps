from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

from .base import Post, ScraperBase

logger = logging.getLogger(__name__)


def _deep_get(obj, *keys):
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
        if obj is None:
            return None
    return obj


def _find_timeline_edges(data: dict) -> list | None:
    """Search for timeline feed edges across known GraphQL response shapes."""
    root = data.get("data") or {}
    # Try well-known root keys first
    for root_key in ("node", "page", "viewer", "media"):
        node = root.get(root_key)
        if isinstance(node, dict):
            edges = _deep_get(node, "timeline_list_feed_units", "edges")
            if edges:
                return edges
            # viewer wraps timeline differently
            edges = _deep_get(node, "feed", "edges") or _deep_get(node, "feed_stories", "edges")
            if edges:
                return edges
    # Generic scan one level deep for any key containing "timeline" or "feed_units"
    for v in root.values():
        if isinstance(v, dict):
            edges = _deep_get(v, "timeline_list_feed_units", "edges")
            if edges:
                return edges
    return None


def _extract_stories(responses: list[str]) -> list[dict]:
    seen: set[str] = set()
    stories: list[dict] = []

    for response_text in responses:
        for line in response_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            edges = _find_timeline_edges(data)
            if not edges:
                continue

            for edge in edges:
                node = edge.get("node", {})
                if node.get("__typename") != "Story":
                    continue

                post_id = node.get("post_id", "")
                if not post_id or post_id in seen:
                    continue
                seen.add(post_id)

                permalink = node.get("permalink_url", "")
                text = _deep_get(node, "comet_sections", "content", "story", "message", "text") or ""

                creation_time = _deep_get(node, "comet_sections", "timestamp", "story", "creation_time")
                published_at = (
                    datetime.fromtimestamp(creation_time, tz=timezone.utc) if creation_time else None
                )

                feedback = _deep_get(
                    node,
                    "comet_sections", "feedback", "story", "story_ufi_container", "story",
                    "feedback_context", "feedback_target_with_context",
                    "comet_ufi_summary_and_actions_renderer", "feedback",
                ) or {}
                reactions = sum(
                    e.get("reaction_count", 0)
                    for e in (feedback.get("top_reactions") or {}).get("edges") or []
                )

                comment_instance = _deep_get(
                    node,
                    "comet_sections", "feedback", "story", "story_ufi_container", "story",
                    "feedback_context", "feedback_target_with_context",
                    "comment_rendering_instance",
                ) or {}
                comments = (comment_instance.get("comments") or {}).get("total_count", 0)

                stories.append({
                    "post_id": post_id,
                    "url": permalink,
                    "text": text,
                    "published_at": published_at,
                    "reactions": reactions,
                    "comments": comments,
                })

    return stories


class FacebookScraper(ScraperBase):
    PLATFORM = "facebook"

    @classmethod
    def login(cls, page, config: dict) -> bool:
        username = os.environ.get("FB_USERNAME", "")
        password = os.environ.get("FB_PASSWORD", "")

        if not username or not password:
            logger.warning("Facebook: credentials not set — set FB_USERNAME / FB_PASSWORD in .env")
            return False

        logger.info("Facebook: logging in as %s", username)
        try:
            page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30_000)

            for btn in page.locator("button, [role=button]").all():
                try:
                    text = btn.inner_text()
                    if any(kw in text.lower() for kw in ("allow", "accept", "povolit", "erlauben", "accepter", "alle zulassen")):
                        if btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(1_500)
                            break
                except Exception:
                    pass

            page.wait_for_selector("[name=email]", timeout=10_000)
            page.fill("[name=email]", username)
            page.fill("[name=pass]", password)
            page.press("[name=pass]", "Enter")

            page.wait_for_url(
                re.compile(r"facebook\.com/(feed|home)"),
                timeout=15_000,
            )
            logger.info("Facebook: login successful")
            return True
        except Exception as exc:
            if "two_step_verification" in page.url:
                logger.warning(
                    "Facebook: 2FA required — run 'uv run python setup_session.py' once to save your session"
                )
            else:
                logger.warning("Facebook: login failed — %s", exc)
            return False

    def get_profile_name(self) -> str:
        return self.url.rstrip("/").split("/")[-1]

    def get_posts(self) -> list[Post]:
        profile_name = self.get_profile_name()
        logger.info("Facebook: scraping %s", self.url.rstrip("/") + "/posts/")

        graphql_responses: list[str] = []

        def handle_response(response):
            try:
                if "/api/graphql" not in response.url:
                    return
                body = response.body()
                text = body.decode("utf-8", errors="replace")
                if len(text) > 100:
                    graphql_responses.append(text)
            except Exception:
                pass

        posts_url = self.url.rstrip("/") + "/posts/"
        try:
            self.page.on("response", handle_response)
            self.page.goto(posts_url, wait_until="domcontentloaded", timeout=30_000)
            self.random_delay(3, 5)

            for _ in range(8):
                self.page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
                self.random_delay(2, 3)
        except Exception as exc:
            logger.warning("Facebook: failed to load %s — %s", posts_url, exc)
            return []
        finally:
            self.page.remove_listener("response", handle_response)

        logger.info("Facebook: captured %d GraphQL responses for %s", len(graphql_responses), profile_name)

        # Detect 2FA checkpoint — all responses are verification queries, no feed content.
        if graphql_responses and all(
            "two_step_verification" in r or "xfb_two_step" in r
            for r in graphql_responses
        ):
            logger.warning(
                "Facebook: session requires 2FA re-verification for %s — "
                "run 'uv run python setup_session.py' and re-login to Facebook",
                profile_name,
            )
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_back)
        stories = _extract_stories(graphql_responses)
        logger.info("Facebook: extracted %d unique stories for %s", len(stories), profile_name)

        posts: list[Post] = []
        for i, story in enumerate(stories[:15]):
            published_at = story["published_at"]
            if published_at and published_at < cutoff:
                continue

            screenshot_file = self._screenshot_post(story["url"], f"facebook_{profile_name}_{i + 1}.png")

            posts.append(Post(
                platform=self.PLATFORM,
                profile=profile_name,
                url=story["url"] or self.url,
                published_at=published_at or datetime.now(timezone.utc),
                text=story["text"][:500],
                reactions=story["reactions"],
                comments=story["comments"],
                shares=0,
                screenshot_path=screenshot_file,
            ))

        logger.info("Facebook: collected %d posts from %s", len(posts), profile_name)
        return posts

    def _screenshot_post(self, permalink: str, filename: str) -> str:
        if not self.screenshot_dir or not permalink or "facebook.com" not in permalink:
            return ""
        try:
            self.page.goto(permalink, wait_until="domcontentloaded", timeout=15_000)
            self.random_delay(1, 2)
            path = os.path.join(self.screenshot_dir, filename)
            self.page.screenshot(path=path, full_page=False)
            return filename
        except Exception as exc:
            logger.debug("Facebook: screenshot failed for %s — %s", permalink, exc)
            return ""
