import json

from database import get_connection
from embedding_service import generate_embedding


# classes.pricing stores "amount" in the currency's minor unit (cents) -
# e.g. 2500 means $25.00, not $2,500 - matching every class in the catalog
# (all cluster in the 2000-2500 range, which only makes sense as cents for
# a per-session kids' class). Embedding the raw amount unconverted let the
# LLM read "amount": 2500 as if it were already whole dollars.
_CURRENCY_SYMBOLS = {"usd": "$", "eur": "€", "gbp": "£"}


def _format_price_entry(entry):
    """One pricing tier, e.g. {"unit": "session", "amount": 2500,
    "currency": "usd"} -> "$25.00 per session". Returns None if the entry
    doesn't have a usable amount, so callers can skip it like any other
    empty field."""

    amount = entry.get("amount")

    if not isinstance(amount, (int, float)):
        return None

    unit = entry.get("unit") or "session"
    currency = (entry.get("currency") or "").lower()
    dollars = amount / 100
    symbol = _CURRENCY_SYMBOLS.get(currency)

    if symbol:
        return f"{symbol}{dollars:.2f} per {unit}"

    return f"{dollars:.2f} {currency.upper()} per {unit}".strip()


def format_pricing(pricing):
    """Converts the stored cents-based pricing dict into a plain,
    human-readable string the LLM can quote directly - e.g.
    {"regular": {"unit": "session", "amount": 2500, "currency": "usd"}}
    -> "$25.00 per session". Handles the pricing structure generically
    (any tier name, missing/malformed entries) rather than assuming any
    one class's shape. Returns None for missing/empty/unusable pricing,
    same as any other empty field insert_chunk() already skips."""

    if not isinstance(pricing, dict) or not pricing:
        return None

    lines = []

    for tier, entry in pricing.items():

        if not isinstance(entry, dict):
            continue

        formatted = _format_price_entry(entry)

        if not formatted:
            continue

        if len(pricing) > 1:
            lines.append(f"{tier.replace('_', ' ').title()}: {formatted}")
        else:
            lines.append(formatted)

    return "\n".join(lines) if lines else None


def insert_chunk(
    cursor,
    class_id,
    title,
    subject,
    section,
    content,
    url=""
):
    """Create one semantic chunk and store it."""

    if not content:
        return

    if isinstance(content, (list, tuple)):
        if len(content) == 0:
            return
        content = "\n".join(f"• {item}" for item in content)

    elif isinstance(content, dict):
        if len(content) == 0:
            return
        content = json.dumps(content, indent=2)

    content = str(content).strip()

    if not content:
        return

    chunk = f"""
Class: {title}

Subject: {subject}

Section: {section}

Content:
{content}
""".strip()

    embedding = generate_embedding(chunk)

    cursor.execute(
        """
        INSERT INTO knowledge_base
        (
            article_title,
            section_title,
            category,
            content,
            url,
            embedding,
            source,
            source_id
        )
        VALUES
        (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            'class',
            %s
        )
        """,
        (
            title,
            section,
            subject,
            chunk,
            url,
            embedding,
            str(class_id)
        )
    )


conn = get_connection()
cursor = conn.cursor()

try:

    cursor.execute("""
    SELECT
        class_id,
        title,
        url_slug,
        subject,
        summary_parent,
        summary_learner,
        description,
        learning_goals,
        prerequisites,
        resources,
        parental_guidance,
        pricing
    FROM classes
    """)

    rows = cursor.fetchall()

    print(f"\nFound {len(rows)} classes.\n")

    for row in rows:

        (
            class_id,
            title,
            url_slug,
            subject,
            summary_parent,
            summary_learner,
            description,
            learning_goals,
            prerequisites,
            resources,
            parental_guidance,
            pricing
        ) = row

        print(f"Embedding: {title}")

        try:

            # Delete previous chunks for this class
            cursor.execute(
                """
                DELETE
                FROM knowledge_base
                WHERE source = 'class'
                AND source_id = %s
                """,
                (str(class_id),)
            )

            class_url = (
                f"https://www.coralacademy.com/class/"
                f"{url_slug}-{class_id}"
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Parent Summary",
                summary_parent,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Learner Summary",
                summary_learner,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Description",
                description,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Learning Goals",
                learning_goals,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Prerequisites",
                prerequisites,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Resources",
                resources,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Parental Guidance",
                parental_guidance,
                class_url
            )

            insert_chunk(
                cursor,
                class_id,
                title,
                subject,
                "Pricing",
                format_pricing(pricing),
                class_url
            )

            conn.commit()

            print("✓ Done")

        except Exception as e:

            conn.rollback()

            print(f"✗ Failed: {title}")
            print(e)

finally:

    cursor.close()
    conn.close()

print("\n✅ Class Knowledge Base embedding complete.")