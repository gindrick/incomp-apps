from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import yaml
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from report.generator import save_run
from scraper.analyzer import analyze_main_message
from scraper.base import Post, ProfileResult, ScraperBase
from scraper.facebook import FacebookScraper
from scraper.instagram import InstagramScraper
from scraper.linkedin import LinkedInScraper

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("spotter")

PLATFORM_SCRAPERS: dict[str, type[ScraperBase]] = {
    "facebook.com": FacebookScraper,
    "instagram.com": InstagramScraper,
    "linkedin.com": LinkedInScraper,
}

_PLATFORM_ENV_VARS: dict[str, tuple[str, str]] = {
    "facebook":  ("FB_USERNAME",  "FB_PASSWORD"),
    "instagram": ("IG_USERNAME",  "IG_PASSWORD"),
    "linkedin":  ("LI_USERNAME",  "LI_PASSWORD"),
}

_PLACEHOLDER_PREFIXES = ("your_",)
_PLACEHOLDER_SUFFIXES = ("@example.com",)


def _is_placeholder(value: str) -> bool:
    return (
        not value
        or any(value.startswith(p) for p in _PLACEHOLDER_PREFIXES)
        or any(value.endswith(s) for s in _PLACEHOLDER_SUFFIXES)
    )


def _validate_credentials() -> set[str]:
    """Return platforms that have real (non-placeholder) credentials in the environment."""
    valid: set[str] = set()
    for platform, (user_var, pass_var) in _PLATFORM_ENV_VARS.items():
        username = os.environ.get(user_var, "")
        password = os.environ.get(pass_var, "")
        if _is_placeholder(username) or _is_placeholder(password):
            logger.warning(
                "Skipping %s — credentials not configured (set %s / %s in .env)",
                platform, user_var, pass_var,
            )
        else:
            valid.add(platform)
    return valid

SAMPLE_POSTS: dict[str, list[dict]] = {
    "facebook": [
        {"text": "We are thrilled to present our latest hinge collection at LIGNA trade fair in Hannover! Stop by Hall 12, Stand B42. #LIGNA2025 #Innovation", "reactions": 184, "comments": 16},
        {"text": "Our new push-to-open drawer systems are now available across Europe. Smooth, silent, and built to last. Request your catalogue today.", "reactions": 97, "comments": 8},
        {"text": "Fast delivery guaranteed — 98% of orders shipped within 24 hours. Your projects deserve reliable partners.", "reactions": 143, "comments": 21},
        {"text": "Behind every great kitchen is great hardware. See our full portfolio at hettich.com", "reactions": 76, "comments": 5},
    ],
    "instagram": [
        {"text": "Design meets function ✨ Our concealed hinge series — now in brushed gold finish. #InteriorDesign #Hardware #Hettich", "reactions": 312, "comments": 8},
        {"text": "Swipe to see the full transformation. Soft-close technology for every cabinet door. 🚪 #HomeDesign", "reactions": 278, "comments": 14},
        {"text": "Sustainability is in our DNA. 85% of our packaging is now recyclable. #GreenManufacturing", "reactions": 201, "comments": 6},
    ],
    "linkedin": [
        {"text": "We are proud to announce that Henkel has been recognized as a Top Employer 2025 in 16 countries. This achievement reflects our commitment to creating an inclusive and innovative workplace.", "reactions": 97, "comments": 22},
        {"text": "Innovation spotlight: Our new bio-based adhesive reduces CO₂ emissions by up to 40% compared to conventional alternatives. A milestone for sustainable manufacturing.", "reactions": 134, "comments": 31},
        {"text": "Meet Jana, Senior R&D Engineer at Henkel. 'What I love most is that my work directly impacts products used by millions of people every day.' #LifeAtHenkel #Careers", "reactions": 88, "comments": 17},
        {"text": "Henkel's Q1 2025 results: organic sales growth of 3.2%, driven by strong performance in Adhesive Technologies. Full report available on our investor relations page.", "reactions": 62, "comments": 9},
        {"text": "Proud to support STEM education initiatives across Central Europe. Last year we reached over 12,000 students through our Science for a Better World programme.", "reactions": 115, "comments": 28},
    ],
}

SAMPLE_MESSAGES: dict[str, list[str]] = {
    "HettichCR":    ["product innovation", "fast delivery", "trade fair presence", "portfolio breadth"],
    "Hafele":       ["smart home integration", "design quality", "service network"],
    "rudolfostermann_karriere": ["employer branding", "career opportunities", "team culture"],
    "hettich_official":        ["design aesthetics", "sustainability", "product launches"],
    "henkel":       ["company culture", "innovation", "sustainability", "financial results"],
    "moderne-kunststoff-technik-gebruder-eschbach-gmbh": ["precision manufacturing", "B2B partnerships", "technical expertise"],
}


def _make_sample_post(platform: str, profile: str, idx: int, data: dict) -> Post:
    return Post(
        platform=platform,
        profile=profile,
        url=f"https://www.{platform}.com/{profile}/posts/{1000 + idx}",
        published_at=datetime.now(timezone.utc) - timedelta(days=idx + 1),
        text=data["text"],
        reactions=data["reactions"],
        comments=data["comments"],
        shares=0,
        screenshot_path="",
    )


def dry_run(config: dict) -> None:
    output_dir: str = config.get("output_dir", "reports")
    profiles: list[dict] = config.get("profiles", [])

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M") + "_dry"
    run_dir = os.path.join(output_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)

    logger.info("DRY RUN — generating sample data for %d profiles (no browser, no credentials)", len(profiles))

    results: list[ProfileResult] = []

    for entry in profiles:
        url = entry["url"]
        label = entry.get("label", url)
        cls = next((c for d, c in PLATFORM_SCRAPERS.items() if d in url), None)
        if cls is None:
            continue

        platform = cls.PLATFORM
        profile_name = url.rstrip("/").split("/")[-1]
        sample_pool = SAMPLE_POSTS.get(platform, SAMPLE_POSTS["linkedin"])

        posts = [
            _make_sample_post(platform, profile_name, i, data)
            for i, data in enumerate(sample_pool)
        ]

        results.append(ProfileResult(
            platform=platform,
            profile=profile_name,
            label=label,
            url=url,
            posts=posts,
        ))
        logger.info("Sample: %s (%s) — %d posts", label, platform, len(posts))

    messages = {
        r.profile: SAMPLE_MESSAGES.get(r.profile, ["product quality", "customer service", "innovation"])
        for r in results
    }

    save_run(run_dir, results, messages)
    logger.info("Dry run complete. Open http://localhost:8013 to preview the report.")


SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")


def _session_path(platform: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{platform}_state.json")


def detect_scraper(url: str) -> type[ScraperBase] | None:
    for domain, cls in PLATFORM_SCRAPERS.items():
        if domain in url:
            return cls
    return None


def run_scraper(config: dict) -> None:
    days_back: int = config.get("days_back", 7)
    headless: bool = config.get("headless", True)
    output_dir: str = config.get("output_dir", "reports")
    screenshot_width: int = config.get("screenshot_width", 1280)
    profiles: list[dict] = config.get("profiles", [])

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    run_dir = os.path.join(output_dir, run_id)
    screenshots_dir = os.path.join(run_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    valid_platforms = _validate_credentials()

    platform_groups: dict[str, list[dict]] = defaultdict(list)
    scraper_classes: dict[str, type[ScraperBase]] = {}
    unknown: list[dict] = []

    for entry in profiles:
        cls = detect_scraper(entry["url"])
        if cls is None:
            logger.warning("Unknown platform for URL: %s — skipping", entry["url"])
            unknown.append(entry)
        else:
            platform_groups[cls.PLATFORM].append(entry)
            scraper_classes[cls.PLATFORM] = cls

    # Separate out profiles whose platform has no credentials configured.
    unconfigured_results: list[ProfileResult] = []
    for platform in list(platform_groups.keys()):
        if platform not in valid_platforms:
            user_var, pass_var = _PLATFORM_ENV_VARS.get(platform, ("?", "?"))
            for entry in platform_groups.pop(platform):
                unconfigured_results.append(ProfileResult(
                    platform=platform,
                    profile=entry["url"].rstrip("/").split("/")[-1],
                    label=entry.get("label", entry["url"]),
                    url=entry["url"],
                    error=f"Credentials not configured — set {user_var} / {pass_var} in .env",
                ))
            scraper_classes.pop(platform, None)

    logger.info(
        "Starting Spotter run %s — %d profiles across %d platforms (%d skipped: no credentials)",
        run_id,
        len(profiles) - len(unknown) - len(unconfigured_results),
        len(platform_groups),
        len(unconfigured_results),
    )

    results: list[ProfileResult] = list(unconfigured_results)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)

        for platform, entries in platform_groups.items():
            ScraperClass = scraper_classes[platform]

            session_file = _session_path(platform)
            context_kwargs: dict = {
                "viewport": {"width": screenshot_width, "height": 900},
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            }
            if os.path.exists(session_file):
                context_kwargs["storage_state"] = session_file
                logger.info("%s: loading saved session from %s", platform, session_file)

            context = browser.new_context(**context_kwargs)

            if os.path.exists(session_file):
                # Trust the saved session — skip login entirely.
                logged_in = True
                logger.info("%s: using saved session (skipping login)", platform)
            else:
                login_page = context.new_page()
                logged_in = ScraperClass.login(login_page, config)
                if logged_in:
                    os.makedirs(SESSIONS_DIR, exist_ok=True)
                    context.storage_state(path=session_file)
                    logger.info("%s: session saved to %s", platform, session_file)
                login_page.close()

            if not logged_in:
                logger.warning(
                    "%s: login failed — skipping all %d %s profiles",
                    platform, len(entries), platform,
                )
                for entry in entries:
                    results.append(ProfileResult(
                        platform=platform,
                        profile=entry["url"].rstrip("/").split("/")[-1],
                        label=entry.get("label", entry["url"]),
                        url=entry["url"],
                        error="Login failed — check credentials in .env",
                    ))
                context.close()
                continue

            for entry in entries:
                url = entry["url"]
                label = entry.get("label", url)
                result = ProfileResult(platform=platform, profile="", label=label, url=url)

                try:
                    page = context.new_page()
                    scraper = ScraperClass(
                        url=url,
                        label=label,
                        page=page,
                        days_back=days_back,
                        screenshot_dir=screenshots_dir,
                    )
                    result.profile = scraper.get_profile_name()
                    result.posts = scraper.get_posts()
                    page.close()
                    logger.info("Done: %s (%s) — %d posts", label, platform, result.new_posts_count)
                except Exception as exc:
                    logger.error("Failed scraping %s: %s", url, exc)
                    result.error = str(exc)

                results.append(result)

            context.close()

        browser.close()

    messages: dict[str, list[str]] = {}
    for result in results:
        if result.posts and not result.error:
            texts = [p.text for p in result.posts if p.text]
            messages[result.profile] = analyze_main_message(texts)

    save_run(run_dir, results, messages)
    logger.info("Run complete. Report saved to %s", run_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Spotter — competitor social media monitor")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate a sample report with realistic fake data — no browser, no credentials required",
    )
    args = parser.parse_args()

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if args.dry_run:
        dry_run(config)
    else:
        run_scraper(config)


if __name__ == "__main__":
    main()
