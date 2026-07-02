from database import get_connection, db_pool
from embedding_service import generate_embedding
from emails_cleaner import clean_email_body

def search_similar_emails(subject, body, limit=30):

    clean_body = clean_email_body(body)

    text = f"Subject: {subject}\n\nBody:\n{clean_body}"
    text = text[:8000]

    print("Generating query embedding...")

    query_embedding = generate_embedding(text)

    print("embedding Generated")

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                id,
                sender,
                subject,
                body,
                sent_at,
                thread_id,
                message_id,
                1 - (embedding <=> %s::vector) AS similarity

            FROM historical_emails

            WHERE embedding IS NOT NULL

            ORDER BY embedding <=> %s::vector

            LIMIT %s
        """, (query_embedding, query_embedding, limit))

        return cursor.fetchall()

    finally:

        cursor.close()
        db_pool.putconn(conn)