import os

from database import get_connection, db_pool
from embedding_service import generate_embedding
from emails_cleaner import clean_email_body

# Style examples must only ever be Coral Academy's own past replies, never
# customer-authored content — otherwise one customer's email (with their
# personal details) could be pulled in verbatim while drafting a reply to a
# different customer. Restrict retrieval to these known staff addresses
# regardless of what ended up in historical_emails historically.
STAFF_EMAIL_ADDRESSES = [
    e for e in (os.getenv("EMAIL_1"), os.getenv("EMAIL_2"), os.getenv("EMAIL_3"))
    if e
]


def search_similar_emails(subject, body, limit=30, embedding_client=None):

    clean_body = clean_email_body(body)

    text = f"Subject: {subject}\n\nBody:\n{clean_body}"
    text = text[:8000]

    print("Generating query embedding...")

    query_embedding = generate_embedding(text, client=embedding_client)

    print("embedding Generated")

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # Filter to staff senders in a MATERIALIZED CTE first (uses the plain
        # btree index on sender — exact, not approximate), then sort that
        # already-small result by vector distance. A plain subquery isn't
        # enough here — Postgres flattens it back into one query and still
        # uses the approximate HNSW index for the ORDER BY, which only
        # examines a limited candidate window and can come back with zero
        # rows after the sender filter is applied even though matching rows
        # exist elsewhere in the table. MATERIALIZED forces the filter to
        # actually run first, verified via EXPLAIN.
        cursor.execute("""
            WITH staff_authored AS MATERIALIZED (
                SELECT id, sender, subject, body, sent_at, thread_id, message_id, embedding
                FROM historical_emails
                WHERE embedding IS NOT NULL
                AND sender = ANY(%s)
            )
            SELECT
                id,
                sender,
                subject,
                body,
                sent_at,
                thread_id,
                message_id,
                1 - (embedding <=> %s::vector) AS similarity
            FROM staff_authored

            ORDER BY embedding <=> %s::vector

            LIMIT %s
        """, (STAFF_EMAIL_ADDRESSES, query_embedding, query_embedding, limit))

        return cursor.fetchall()

    finally:

        cursor.close()
        db_pool.putconn(conn)