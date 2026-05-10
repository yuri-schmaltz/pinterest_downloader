from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://br.pinterest.com/yuri_schmaltz/boards/", wait_until="networkidle")
    page.wait_for_timeout(3000)
    page.screenshot(path="pinterest_debug.png")
    text = page.evaluate("document.body.innerText")
    print("Page text:", text[:500])
    browser.close()
