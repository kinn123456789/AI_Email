from database import get_connection, db_pool
from embedding_service import generate_embedding
import time
from emails_cleaner import clean_email_body

BATCH_SIZE = 100

def main():
    print("PROGRAM STARTED")
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id, subject, body FROM historical_emails WHERE embedded = FALSE ORDER BY id")
        emails = cursor.fetchall()
        total = len(emails)
        
        processed = 0
        failed = 0

        for i, email in enumerate(emails, 1):
            email_id, subject, body = email[0], email[1] or "", email[2] or ""
            
            clean_body = clean_email_body(body)

            text = f"Subject: {subject}\n\nBody:\n{clean_body}"

            try:
                # 1. Create a savepoint before the operation
                cursor.execute("SAVEPOINT email_sp")
                
                MAX_RETRIES = 3

                for attempt in range(MAX_RETRIES):
                
                    try:
                        embedding = generate_embedding(text)
                        break

                    except Exception as e:

                        if attempt == MAX_RETRIES - 1:
                            raise

                            print(f"Retry {attempt + 1} for Email {email_id}")

                            time.sleep(2)

                cursor.execute("""
                    UPDATE historical_emails
                    SET embedding = %s, embedded = TRUE
                    WHERE id = %s
                """, (embedding, email_id))
                
                # 2. Release the savepoint on success (optional, but good practice)
                cursor.execute("RELEASE SAVEPOINT email_sp")
                processed += 1
                
            except Exception as e:
                # 3. Rollback ONLY to the savepoint on failure
                cursor.execute("ROLLBACK TO SAVEPOINT email_sp")
                failed += 1
                print(f"Failed Email {email_id}: {e}")

            # Commit batch
            if processed % BATCH_SIZE == 0:
                conn.commit()
                print(f"Committed {i} emails...")
                print(f"[{processed}/{total}] Email {email_id}")

        conn.commit()
        print(f"\nFinished. Success: {processed}, Failed: {failed}")

    finally:
        cursor.close()
        db_pool.putconn(conn)
if __name__ == "__main__":
    main()