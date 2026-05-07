from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Post:
    platform: str
    profile: str
    url: str
    published_at: datetime
    text: str
    reactions: int
    comments: int
    shares: int
    screenshot_path: str = ""


@dataclass
class ProfileResult:
    platform: str
    profile: str
    label: str
    url: str
    posts: list[Post] = field(default_factory=list)
    error: str | None = None

    @property
    def new_posts_count(self) -> int:
        return len(self.posts)

    @property
    def top_post(self) -> Post | None:
        if not self.posts:
            return None
        return max(self.posts, key=lambda p: p.reactions + p.comments)


class ScraperBase(ABC):
    PLATFORM: str = ""

    def __init__(self, url: str, label: str, page, days_back: int = 7, screenshot_dir: str = "") -> None:
        self.url = url
        self.label = label
        self.page = page
        self.days_back = days_back
        self.screenshot_dir = screenshot_dir

    @classmethod
    def login(cls, page, config: dict) -> bool:
        """Log in once per platform using a temporary page. Override in each scraper.
        Returns True on success, False if credentials missing or login failed."""
        return True

    @abstractmethod
    def get_posts(self) -> list[Post]: ...

    @abstractmethod
    def get_profile_name(self) -> str: ...

    def random_delay(self, min_s: float = 2.0, max_s: float = 5.0) -> None:
        time.sleep(random.uniform(min_s, max_s))

    def take_screenshot(self, locator, filename: str) -> str:
        if not self.screenshot_dir or locator is None:
            return ""
        import os
        path = os.path.join(self.screenshot_dir, filename)
        try:
            locator.screenshot(path=path)
            return filename
        except Exception:
            return ""
