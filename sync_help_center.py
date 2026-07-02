from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from database import get_connection


def split_into_chunks(text, max_chars=1200):
    paragraphs = text.split("\n")
    chunks = []
    current = ""

    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(current) + len(p) <= max_chars:
            current += "\n" + p
        else:
            chunks.append(current.strip())
            current = p

    if current:
        chunks.append(current.strip())

    return chunks


conn = get_connection()
cursor = conn.cursor()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    print("Opening Help Center...")
    page.goto(
        "https://www.coralacademy.com/help",
        wait_until="domcontentloaded",
        timeout=120000
    )
    page.wait_for_selector("h1")

    links = page.locator("a").evaluate_all("""
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

    print(f"\nFound {len(links)} help articles\n")

    for item in links:
        url = item["href"]
        title = item["title"]

        print(f"Reading: {title}")
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=120000
        )
        page.wait_for_selector("h1")

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

        content = []
        for tag in soup.find_all(["h2", "h3", "p", "li"]):
            text = tag.get_text(" ", strip=True)
            if text:
                content.append(text)

        article = "\n".join(content)
        chunks = split_into_chunks(article)

        print(f"  Scraped {len(chunks)} chunks from live page")

        # ----------------------------------------------------
        # NEW LOOKUP & COMPARE STEP (FIXED CONDITIONAL)
        # ----------------------------------------------------
        cursor.execute(
            """
            SELECT content
            FROM knowledge_base
            WHERE url = %s
            ORDER BY id
            """, 
            (url,)
        )
        existing = cursor.fetchall()
        existing_chunks = [row[0] for row in existing]

        existing_chunks = [c.strip() for c in existing_chunks]
        chunks = [c.strip() for c in chunks]
        
        # FIXED: Put back the matching check condition here
        if existing_chunks == chunks:
            print("  ✨ No changes detected in content — skipping database write")
            continue
        # ----------------------------------------------------

        print("  ⚠️ Content changed or new page. Updating database...")

        # Categorization logic
        if "/subscription-payments/" in url:
            category = "Subscription"
        elif "/teaching/" in url:
            category = "Teaching"
        elif "/legal/" in url:
            category = "Legal"
        elif "/getting-started/" in url:
            category = "Getting Started"
        else:
            category = "General"

        # Only wipe old chunks if the content actually diverged
        cursor.execute(
            """
            DELETE FROM knowledge_base
            WHERE url = %s
            """,
            (url,)
        )

        for chunk in chunks:
            cursor.execute(
                """
                INSERT INTO knowledge_base
                (
                    article_title,
                    section_title,
                    category,
                    content,
                    url
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (title, "", category, chunk, url)
            )

        conn.commit()

    browser.close()

cursor.close()
conn.close()

print("\nKnowledge Base Updated!")