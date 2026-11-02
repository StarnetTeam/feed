from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "storage_state.json"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(locale="en-US")
    page = context.new_page()
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
    print("سجّل الدخول يدويًا في النافذة، ثم اضغط Enter هنا بعد اكتمال تسجيل الدخول.")
    input()
    context.storage_state(path=str(OUT))
    browser.close()
    print(f"Saved {OUT}")
