from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from .parser import parse_text

ROOT = Path(__file__).resolve().parents[1]
GROUPS_FILE = ROOT / "config" / "groups.txt"
OUTPUT_FILE = ROOT / "data" / "fids.json"
CONFIG_FILE = ROOT / "config" / "match_windows.json"


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
        return {"delay_between_groups_seconds": [45, 90], "max_articles_per_group": 8}


def looks_like_today(text: str, now: datetime) -> bool:
    """Conservative check: keep relative/today labels and today's numeric dates."""
    lowered = text.lower()
    today_tokens = (
        "today", "just now", "minute", "minutes", "hour", "hours", "now",
        "اليوم", "الآن", "منذ دقيقة", "منذ دقائق", "منذ ساعة", "منذ ساعات",
    )
    if any(token in lowered for token in today_tokens):
        return True
    patterns = [
        rf"\b{now.day:02d}[./-]{now.month:02d}(?:[./-]{now.year})?\b",
        rf"\b{now.month:02d}[./-]{now.day:02d}(?:[./-]{now.year})?\b",
        rf"\b{now.day}\s+(?:nov|november|نوفمبر)\b",
        rf"\b(?:nov|november|نوفمبر)\s+{now.day}\b",
    ]
    return any(re.search(pattern, lowered) for pattern in patterns)


def collect_page(page, url: str, max_articles: int, now: datetime) -> list[dict]:
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5000)

    # Do not scroll: only the newest visible article cards are inspected.
    cards = page.locator("div[role='article']")
    results: list[dict] = []
    for index in range(min(cards.count(), max_articles)):
        try:
            card_text = cards.nth(index).inner_text(timeout=5000).strip()
            if card_text and looks_like_today(card_text, now):
                results.extend(parse_text(card_text, url))
        except Exception:
            continue

    # If Facebook's anonymous HTML has no article roles, use only a short visible text fallback.
    if not results and cards.count() == 0:
        text = page.locator("body").inner_text(timeout=30000)[:12000]
        if looks_like_today(text, now):
            results.extend(parse_text(text, url))
    return results


def main() -> None:
    groups = load_groups()
    if not groups:
        raise SystemExit("No public group URLs found in config/groups.txt")
    config = load_config()
    bounds = config.get("delay_between_groups_seconds", [45, 90])
    min_delay, max_delay = int(bounds[0]), int(bounds[1])
    max_articles = int(config.get("max_articles_per_group", 8))
    records = load_records()
    known = {item.get("id") for item in records}
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()

    random.SystemRandom().shuffle(groups)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        # One anonymous context and one page; no parallel requests and no login bypass.
        context = browser.new_context(locale="en-US")
        page = context.new_page()
        for position, url in enumerate(groups):
            try:
                for item in collect_page(page, url, max_articles, now):
                    if item["id"] not in known:
                        item["first_seen_utc"] = timestamp
                        item["post_date_filter"] = "today"
                        records.append(item)
                        known.add(item["id"])
                        print(f"New today: {item['satellite']} | {item['frequency']} | {url}")
            except Exception as exc:
                print(f"WARN: failed to read {url}: {exc}")
            if position < len(groups) - 1:
                delay = random.SystemRandom().randint(min_delay, max_delay)
                print(f"Waiting {delay}s before the next public group")
                time.sleep(delay)
        browser.close()

    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(records)} unique records to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
