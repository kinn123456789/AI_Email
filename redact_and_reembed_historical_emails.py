from database import get_connection, db_pool
from embedding_service import generate_embedding
from historical_email_redaction import redact_pii
from emails_cleaner import clean_email_body
import time

PAGE_SIZE = 200


def _process_page(last_id):
    """One connection per page (fetch + all updates in that page), not one
    connection for the whole table (crashed with "SSL connection has been
    closed unexpectedly" holding it open too long) and not a fresh
    connection per row (establishing a new connection was observed taking
    minutes under this session's pooler load — doing that ~10,857 times
    would be far worse than either extreme). Returns (rows_seen, new_last_id).
    """

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT id, subject, body FROM historical_emails WHERE id > %s ORDER BY id LIMIT %s",
            (last_id, PAGE_SIZE)
        )
        rows = cursor.fetchall()

        if not rows:
            return [], last_id

        results = []

        for email_id, subject, body in rows:
            redacted_subject = redact_pii(subject or "")
            redacted_body = redact_pii(body or "")
            clean_body = clean_email_body(redacted_body)
            text = f"Subject: {redacted_subject}\n\nBody:\n{clean_body}"

            try:
                cursor.execute("SAVEPOINT email_sp")

                embedding = None
                MAX_RETRIES = 3

                for attempt in range(MAX_RETRIES):
                    try:
                        embedding = generate_embedding(text)
                        break
                    except Exception as e:
                        if attempt == MAX_RETRIES - 1:
                            raise
                        print(f"Retry {attempt + 1} for email {email_id}: {e}")
                        time.sleep(2)

                cursor.execute(
                    """
                    UPDATE historical_emails
                    SET subject = %s, body = %s, embedding = %s, embedded = TRUE
                    WHERE id = %s
                    """,
                    (redacted_subject, redacted_body, embedding, email_id)
                )

                cursor.execute("RELEASE SAVEPOINT email_sp")
                results.append((email_id, True, None))

            except Exception as e:
                cursor.execute("ROLLBACK TO SAVEPOINT email_sp")
                results.append((email_id, False, str(e)))

        conn.commit()
        return results, rows[-1][0]

    finally:
        cursor.close()
        db_pool.putconn(conn)


def main():
    print("PROGRAM STARTED — redact + re-embed all historical_emails rows", flush=True)

    last_id = 0
    processed = 0
    failed = 0
    total_seen = 0

    while True:
        try:
            results, last_id = _process_page(last_id)
        except Exception as e:
            print(f"Failed to process page after id {last_id}: {e}", flush=True)
            time.sleep(5)
            continue

        if not results:
            break

        for email_id, ok, err in results:
            total_seen += 1
            if ok:
                processed += 1
            else:
                failed += 1
                print(f"Failed email {email_id}: {err}", flush=True)

        print(f"[{total_seen}] processed so far — {processed} ok, {failed} failed (last_id={last_id})", flush=True)

    print(f"\nFinished. Success: {processed}, Failed: {failed}, Total seen: {total_seen}", flush=True)


if __name__ == "__main__":
    main()
