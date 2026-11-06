from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

from .parser import parse_text

ROOT = Path(__file__).resolve().parents[1]
GROUPS_FILE = ROOT / "config" / "groups.txt"
OUTPUT_FILE = ROOT / "data" / "fids.json"
CONFIG_FILE = ROOT / "config" / "match_windows.json"

RECENT_MARKERS = (
    "just now", "minute ago", "minutes ago", "hour ago", "hours ago", "today",
    "الآن", "منذ دقيقة", "منذ دقائق", "منذ ساعة", "منذ ساعات", "اليوم",
)
OLD_MARKERS = ("yesterday", "أمس", "منذ يوم", "منذ يومين")
FEED_HINT = re.compile(r"\b\d{3,5}\s*[/|,:;\-]?\s*[HVLR]\s*[/|,:;\-]?\s*\d{3,6}\b", re.I)
HEX_HINT = re.compile(r"(?:[0-9A-F]{2}[\s:,-]*){6,32}", re.I)


def load_groups() -> list[str]:
    return list(dict.fromkeys(
        line.strip() for line in GROUPS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ))


def load_records() -> list[dict]:
    if not OUTPUT_FILE.exists():
        return []
    try:
        value = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"max_articles_per_group": 20, "delay_between_groups_seconds": [5, 10]}


def recent_enough(text: str) -> bool:
    """Use timestamps when readable; otherwise trust the newest visible cards only."""
    lowered = text.lower()
    if any(marker in lowered for marker in OLD_MARKERS):
        return False
    if any(marker in lowered for marker in RECENT_MARKERS):
        return True
    # Facebook sometimes hides the timestamp from inner_text. The page is not scrolled,
    # so a feed-looking item in the first visible cards is treated as recent candidate.
    return bool(FEED_HINT.search(text) and HEX_HINT.search(text))


def recent_url(url: str) -> str:
    parts = urlsplit(url)
    query = "sorting_setting=CHRONOLOGICAL"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def collect_page(page, url: str, max_articles: int) -> list[dict]:
    target = recent_url(url)
    print(f"Opening: {target}")
    page.goto(target, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)

    cards = page.locator("div[role='article']")
    card_count = cards.count()
    results: list[dict] = []
    if card_count:
        for index in range(min(card_count, max_articles)):
            try:
                card_text = cards.nth(index).inner_text(timeout=3000).strip()
                if card_text and recent_enough(card_text):
                    results.extend(parse_text(card_text, url))
            except Exception as exc:
                print(f"WARN: card {index}: {exc}")
    else:
        # Anonymous Facebook layouts can omit role=article; use the first visible text.
        body_text = page.locator("body").inner_text(timeout=20000)[:30000]
        if recent_enough(body_text):
            results.extend(parse_text(body_text, url))

    unique: dict[str, dict] = {item["id"]: item for item in results}
    print(f"Candidates from group: {len(unique)}")
    return list(unique.values())


def main() -> None:
    groups = load_groups()
    if not groups:
        raise SystemExit("No public group URLs found in config/groups.txt")
    config = load_config()
    max_articles = int(config.get("max_articles_per_group", 20))
    bounds = config.get("delay_between_groups_seconds", [5, 10])
    min_delay, max_delay = int(bounds[0]), int(bounds[1])

    records = load_records()
    known = {item.get("id") for item in records}
    timestamp = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-US",
            viewport={"width": 1280, "height": 900},
            java_script_enabled=True,
        )
        page = context.new_page()
        for position, url in enumerate(groups):
            try:
                for item in collect_page(page, url, max_articles):
                    if item["id"] not in known:
                        item["first_seen_utc"] = timestamp
                        item["collection_window"] = "last_12_hours"
                        records.append(item)
                        known.add(item["id"])
                        print(f"NEW FEED: {item['satellite']} | {item['frequency']} | {url}")
            except Exception as exc:
                print(f"WARN: failed to read {url}: {exc}")
            if position < len(groups) - 1:
                # Short sequential pause only; no random startup sleep.
                time.sleep(max(0, min_delay))
        browser.close()

    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(records)} unique records to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
