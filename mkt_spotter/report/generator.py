from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime

from scraper.base import Post, ProfileResult

logger = logging.getLogger(__name__)


def _post_to_dict(post: Post) -> dict:
    d = asdict(post)
    d["published_at"] = post.published_at.isoformat()
    return d


def _profile_to_dict(result: ProfileResult, main_message: list[str]) -> dict:
    top = result.top_post
    return {
        "platform": result.platform,
        "profile": result.profile,
        "label": result.label,
        "url": result.url,
        "new_posts_count": result.new_posts_count,
        "top_post": _post_to_dict(top) if top else None,
        "main_message": main_message,
        "posts": [_post_to_dict(p) for p in result.posts],
        "error": result.error,
    }


def save_run(
    run_dir: str,
    results: list[ProfileResult],
    messages: dict[str, list[str]],
) -> str:
    os.makedirs(run_dir, exist_ok=True)

    data = {
        "run_at": datetime.utcnow().isoformat(),
        "profiles": [
            _profile_to_dict(r, messages.get(r.profile, []))
            for r in results
        ],
    }

    path = os.path.join(run_dir, "data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info("Saved run data to %s", path)
    return path
