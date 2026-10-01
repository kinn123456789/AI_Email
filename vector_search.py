import threading
from datetime import datetime, timezone

from database import get_connection, db_pool, get_all_email_accounts
from embedding_service import generate_embedding
from emails_cleaner import clean_email_body

# Style examples must only ever be Coral Academy's own past replies, never
# customer-authored content — otherwise one customer's email (with their
# personal details) could be pulled in verbatim while drafting a reply to a
# different customer. Restrict retrieval to known staff addresses regardless
# of what ended up in historical_emails historically.
#
# Previously a fixed 3-element list read from EMAIL_1/EMAIL_2/EMAIL_3 - that
# meant any mailbox added later via Settings could never have its own
# history retrieved here, no matter how much accumulated (see the mailbox
# onboarding investigation this follows). Now derived from
# database.get_all_email_accounts() (the 3 core mailboxes plus every active
# Settings-added one) instead, through the small TTL cache below so this
# doesn't add a database round trip to every single email processed -
# same pattern already used by coral_class_catalog.py's get_cached_catalog()
# for the same reason (a process-local dict behind a lock, no new
# infrastructure).

STAFF_EMAIL_CACHE_TTL_SECONDS = 5 * 60

_staff_email_cache_lock = threading.Lock()
_staff_email_cache = {"result": None, "fetched_at": None}


def _get_staff_email_addresses(ttl_seconds=STAFF_EMAIL_CACHE_TTL_SECONDS, now=None):
    """Returns the cached list of active mailbox addresses if younger than
    ttl_seconds; otherwise calls get_all_email_accounts() for a fresh one
    and caches that. now is only for tests - defaults to the real current
    time."""

    current_time = now or datetime.now(timezone.utc)

    with _staff_email_cache_lock:
        cached = _staff_email_cache["result"]
        cached_at = _staff_email_cache["fetched_at"]

        if cached is not None and cached_at is not None:
            age_seconds = (current_time - cached_at).total_seconds()
            if age_seconds < ttl_seconds:
                return cached

    fresh = [a["email"] for a in get_all_email_accounts() if a.get("email")]

    with _staff_email_cache_lock:
        _staff_email_cache["result"] = fresh
        _staff_email_cache["fetched_at"] = current_time

    return fresh


def search_similar_emails(subject, body, limit=30, embedding_client=None):

    clean_body = clean_email_body(body)

    text = f"Subject: {subject}\n\nBody:\n{clean_body}"
    text = text[:8000]

    print("Generating query embedding...")

    query_embedding = generate_embedding(text, client=embedding_client)

    print("embedding Generated")

    staff_email_addresses = _get_staff_email_addresses()

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
                -- An AI draft a staff member sent unchanged isn't a genuine
                -- example of Coral Academy's own writing style - excluding
                -- it here stops the AI from being trained on its own output.
                AND is_unedited_ai_reply = FALSE
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
        """, (staff_email_addresses, query_embedding, query_embedding, limit))

        return cursor.fetchall()

    finally:

        cursor.close()
        db_pool.putconn(conn)