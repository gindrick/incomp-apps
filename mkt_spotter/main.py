from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict
from datetime import datetime

import yaml
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from report.generator import save_run
from scraper.analyzer import analyze_main_message
from scraper.base import ProfileResult, ScraperBase
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

    run_id = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
    run_dir = os.path.join(output_dir, run_id)
    screenshots_dir = os.path.join(run_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)

    # Group profiles by platform so we log in once per platform
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

    logger.info(
        "Starting Spotter run %s — %d profiles across %d platforms",
        run_id, len(profiles) - len(unknown), len(platform_groups),
    )

    results: list[ProfileResult] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)

        for platform, entries in platform_groups.items():
            ScraperClass = scraper_classes[platform]

            # One browser context per platform — cookies are isolated between platforms
            context = browser.new_context(
                viewport={"width": screenshot_width, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )

            # Log in once for this platform
            login_page = context.new_page()
            logged_in = ScraperClass.login(login_page, config)
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

            # Scrape each profile in this platform's context (session cookies shared)
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

    # Main message analysis via LiteLLM (one call per profile)
    messages: dict[str, list[str]] = {}
    for result in results:
        if result.posts and not result.error:
            texts = [p.text for p in result.posts if p.text]
            messages[result.profile] = analyze_main_message(texts)

    save_run(run_dir, results, messages)
    logger.info("Run complete. Report saved to %s", run_dir)


def main() -> None:
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    run_scraper(config)


if __name__ == "__main__":
    main()
