from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from .parser import parse_text

ROOT = Path(__file__).resolve().parents[1]
GROUPS_FILE = ROOT / "config" / "groups.txt"
OUTPUT_FILE = ROOT / "data" / "fids.json"


def load_groups() -> list[str]:
    return list(dict.fromkeys(
        line.strip() for line in GROUPS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ))


def load_state() -> list[dict]:
    if not OUTPUT_FILE.exists():
        return []
    try:
        value = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def collect_page(page, url: str) -> list[dict]:
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5000)
    # Load a few recent posts without attempting to bypass any access control.
    for _ in range(3):
        page.mouse.wheel(0, 2600)
        page.wait_for_timeout(1500)
    text = page.locator("body").inner_text(timeout=30000)
    return parse_text(text, url)


def main() -> None:
    groups = load_groups()
    records = load_state()
    known = {item.get("id") for item in records}
    now = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        # Anonymous browser context: no Facebook account, cookies, or login secret.
        context = browser.new_context(locale="en-US")
        page = context.new_page()
        for url in groups:
            try:
                for item in collect_page(page, url):
                    if item["id"] not in known:
                        item["first_seen_utc"] = now
                        records.append(item)
                        known.add(item["id"])
                        print(f"New: {item['satellite']} | {item['frequency']}")
            except Exception as exc:
                print(f"WARN: failed to read {url}: {exc}")
        browser.close()

    OUTPUT_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(records)} unique records to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
