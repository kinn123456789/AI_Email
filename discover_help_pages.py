from playwright.sync_api import sync_playwright

HELP_CENTER = "https://www.coralacademy.com/help"

with sync_playwright() as p:

    browser = p.chromium.launch(headless=False)

    page = browser.new_page()

    page.goto(
        HELP_CENTER,
        wait_until="domcontentloaded",
        timeout=120000
    )

    page.wait_for_timeout(5000)

    links = page.locator("a").links = page.locator("a").evaluate_all("""
els => {
    const seen = new Set();

    return els
        .map(e => ({
            title: e.innerText.trim(),
            href: e.href
        }))
        .filter(x =>
            x.href.includes('/help/') &&
            x.title.length > 5 &&
            !seen.has(x.href) &&
            seen.add(x.href)
        );
}
""")

    print("\nFound Help Center Pages:\n")

    for link in links:

        print(link["title"])
        print(link["href"])
        print()

    browser.close()