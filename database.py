import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import re



load_dotenv()

# Increased max connections to 25 to handle bulk processing overhead
db_pool = SimpleConnectionPool(
    1, 25,
    dsn=os.environ.get("DATABASE_URL")
)



def get_connection():
    return db_pool.getconn()

# --- HELPER PATTERN: Every function now uses try/finally ---
def save_email(
    sender,
    subject,
    body,
    category,
    priority,
    ai_summary,
    ai_draft_reply,
    message_id,
    thread_id,
    in_reply_to,
    source=None,
    contact_name=None,
    phone=None,
    status="New",
    requires_review=False,
    ai_confidence=None,
    knowledge_url=None,
    reply_type=None,
    mailbox="inbox",
    references_header=None  # Ensure this is added here
):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Added 'references_header' to the column list and the %s placeholder
        cursor.execute("""
            INSERT INTO messages(
                sender, subject, body, category, priority, ai_summary, 
                ai_draft_reply, message_id, thread_id, in_reply_to, source, 
                contact_name, phone, status, requires_review, ai_confidence, 
                knowledge_url, reply_type, mailbox, references_header
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
        """, (
            sender, subject, body, category, priority, ai_summary, 
            ai_draft_reply, message_id, thread_id, in_reply_to, source, 
            contact_name, phone, status, requires_review, ai_confidence, 
            knowledge_url, reply_type, mailbox, references_header 
        ))
        result = cursor.fetchone()
        conn.commit()
        return result[0] if result else None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def email_exists(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM messages WHERE message_id = %s LIMIT 1", (message_id,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_emails():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT
                id,
                sender,
                subject,
                source,
                category,
                priority,
                status,
                reply_type,
                created_at,
                first_reply_at,
                resolved_at,
                knowledge_url,
                ai_confidence,
                ai_summary,
                ai_draft_reply,
                requires_review
            FROM messages
            WHERE mailbox = 'inbox'
            AND reply_type IS DISTINCT FROM 'gmail_manual'
            ORDER BY id DESC;
        """)

        rows = cursor.fetchall()

        for row in rows:
            
            if row["created_at"]:
                row["created_at"] = row["created_at"].strftime("%b %-d, %-I:%M %p")

            if row["first_reply_at"]:
                row["first_reply_at"] = row["first_reply_at"].strftime("%b %-d, %-I:%M %p")

            if row["resolved_at"]:
                row["resolved_at"] = row["resolved_at"].strftime("%b %-d, %-I:%M %p")
            reply_type = row["reply_type"]
            status = row["status"]

            if reply_type == "automatic":
                row["handled_by"] = "AI"

            elif reply_type == "human":
                row["handled_by"] = "Human"

            elif status in ["Replied", "Auto Replied", "No Reply Required"]:
                row["handled_by"] = "AI"

            elif row["requires_review"]:
                row["handled_by"] = "Human"

            else:
                 row["handled_by"] = "Pending"
            print(
                    row["id"],
                    row["status"],
                    row["reply_type"],
                    row["handled_by"]
            )
        return rows

    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_category_counts():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT category, COUNT(*) FROM messages GROUP BY category")
        return cursor.fetchall()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_emails_by_category(category):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT
                id,
                sender,
                subject,
                category,
                priority,
                status,
                created_at,
                ai_summary,
                ai_confidence,
                knowledge_url
            FROM messages
            WHERE category = %s
            ORDER BY id DESC
        """, (category,))

        rows = cursor.fetchall()

        for row in rows:
            if row["created_at"]:
                row["created_at"] = row["created_at"].strftime("%b %-d, %-I:%M %p")

        return rows

    finally:
        cursor.close()
        db_pool.putconn(conn)

from psycopg2.extras import RealDictCursor

def get_email_by_id(email_id):
    conn = get_connection()
    # RealDictCursor ensures this returns a dict-like object for Jinja
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # 1. Added the missing columns directly into the SELECT string
        # 2. Made sure the second parameter to execute() is strictly a tuple containing just (email_id,)
        cursor.execute(
            """
            SELECT id, sender, subject, body, category, ai_summary, 
                   ai_draft_reply, priority, status, source, knowledge_url,
                   ai_confidence, requires_review, created_at,
                   thread_id,
                   message_id,
                   in_reply_to,
                   reply_type,
                   mailbox
                   
                   
            FROM messages 
            WHERE id = %s
            """, 
            (email_id,)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_status(email_id, status):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE messages SET status = %s WHERE id = %s", (status, email_id))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def save_conversation(chat_id, parent_name, teacher_name, parent_id, teacher_id, updated_at):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO conversations(chat_id, parent_name, teacher_name, parent_id, teacher_id, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE SET
            parent_name = EXCLUDED.parent_name, teacher_name = EXCLUDED.teacher_name,
            parent_id = EXCLUDED.parent_id, teacher_id = EXCLUDED.teacher_id, updated_at = EXCLUDED.updated_at
        """, (chat_id, parent_name, teacher_name, parent_id, teacher_id, updated_at))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def save_conversation_message(chat_id, sender, body, created_at, message_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO conversation_messages(chat_id, sender, body, created_at, message_id)
            VALUES (%s, %s, %s, %s, %s) ON CONFLICT (message_id) DO NOTHING
        """, (chat_id, sender, body, created_at, message_id))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_conversation_messages(chat_id):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT * FROM conversation_messages WHERE chat_id = %s ORDER BY created_at ASC", (chat_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_conversation(chat_id):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT * FROM conversations WHERE chat_id = %s", (chat_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def conversation_message_exists(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM conversation_messages WHERE message_id = %s LIMIT 1", (message_id,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def save_attachment(message_id, filename, file_type, file_path):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO attachments(message_id, filename, file_type, file_path) VALUES (%s, %s, %s, %s)", (message_id, filename, file_type, file_path))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_attachments(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM attachments WHERE message_id = %s", (message_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def attachment_exists(message_id, filename):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM attachments WHERE message_id = %s AND filename = %s LIMIT 1", (message_id, filename))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_contact_forms():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT * FROM messages WHERE source = 'contact_form' ORDER BY created_at DESC")
        return cursor.fetchall()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_ai_results(message_id, category, priority, summary, draft_reply):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE messages SET category=%s, priority=%s, ai_summary=%s, ai_draft_reply=%s WHERE id=%s", (category, priority, summary, draft_reply, message_id))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def log_event(message_id, event_type, details):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO email_logs(message_id, event_type, details) VALUES (%s, %s, %s)", (message_id, event_type, details))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

from psycopg2.extras import RealDictCursor

def get_thread(thread_id):
    conn = get_connection()
    # Using RealDictCursor allows you to access data by column name
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query = """
            SELECT sender, body, created_at 
            FROM messages 
            WHERE thread_id = %s 
            ORDER BY created_at ASC
        """
        cursor.execute(query, (thread_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_root_thread_id(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            WITH RECURSIVE thread_path AS (
                SELECT thread_id, in_reply_to FROM messages WHERE message_id = %s
                UNION ALL
                SELECT m.thread_id, m.in_reply_to FROM messages m
                INNER JOIN thread_path tp ON m.message_id = tp.in_reply_to
            )
            SELECT thread_id FROM thread_path WHERE in_reply_to IS NULL LIMIT 1;
        """, (message_id,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def set_first_reply_time(email_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE messages SET first_reply_at = NOW() WHERE id = %s AND first_reply_at IS NULL", (email_id,))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def set_resolved_time(email_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE messages SET resolved_at = NOW() WHERE id = %s AND resolved_at IS NULL", (email_id,))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def reopen_thread(thread_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE messages SET status = 'Needs Review' WHERE thread_id = %s AND status = 'Resolved'", (thread_id,))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def set_sent_time(email_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE messages SET sent_at = CURRENT_TIMESTAMP WHERE id = %s AND sent_at IS NULL", (email_id,))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_sent_message_id(email_id, sent_message_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE messages SET sent_message_id = %s WHERE id = %s", (sent_message_id, email_id))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def resolve_thread(thread_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE messages SET status = 'Resolved' WHERE thread_id = %s", (thread_id,))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_avg_first_response_time():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT AVG(first_reply_at - created_at) FROM messages WHERE first_reply_at IS NOT NULL")
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_avg_resolution_time():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT AVG(resolved_at - created_at) FROM messages WHERE resolved_at IS NOT NULL")
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_unclassified_teacher_messages():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT id, message_id, body FROM conversation_messages WHERE ai_processed = FALSE AND body IS NOT NULL AND TRIM(body) <> '' ORDER BY created_at LIMIT 3")
        return cursor.fetchall()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_teacher_ai_fields(message_id, category, priority, summary, draft_reply):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE conversation_messages SET ai_category = %s, ai_priority = %s, ai_summary = %s, ai_draft_reply = %s, ai_processed = TRUE
            WHERE message_id = %s
        """, (category, priority, summary, draft_reply, message_id))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_teacher_messages():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT id, chat_id, sender, body, ai_category, ai_priority, ai_draft_reply, ai_summary, created_at FROM conversation_messages ORDER BY created_at DESC LIMIT 100")
        return cursor.fetchall()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_email_filter_rules():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT rule_type, rule_value, category, reason FROM email_filter_rules WHERE enabled = TRUE")
        return cursor.fetchall()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def historical_email_exists(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM historical_emails WHERE message_id = %s LIMIT 1", (message_id,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_unembedded_emails():

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT id, subject, body
            FROM historical_emails
            WHERE embedded = FALSE
            ORDER BY id
        """)

        rows = cursor.fetchall()

        

        return rows

    finally:
        cursor.close()
        db_pool.putconn(conn)

def save_embedding(email_id, embedding):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            UPDATE historical_emails
            SET embedding = %s,
                embedded = TRUE
            WHERE id = %s
        """, (embedding, email_id))

        conn.commit()

    finally:

        cursor.close()
        db_pool.putconn(conn)

def     save_historical_email(
    message_id,
    thread_id,
    in_reply_to,
    sender,
    recipient,
    subject,
    body,
    sent_at,
    source_account,
    has_attachment=False,
    attachment_count=0,
    reference_ids=None
):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            INSERT INTO historical_emails (
                message_id,
                thread_id,
                in_reply_to,
                sender,
                recipient,
                subject,
                body,
                sent_at,
                source_account,
                has_attachment,
                attachment_count,
                reference_ids
            )
            VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            RETURNING id
        """, (
            message_id,
            thread_id,
            in_reply_to,
            sender,
            recipient,
            subject,
            body,
            sent_at,
            source_account,
            has_attachment,
            attachment_count,
            reference_ids
        ))

        email_id = cursor.fetchone()[0]

        conn.commit()

        return email_id

    finally:

        cursor.close()
        db_pool.putconn(conn)

def get_historical_emails(email_ids):

    if not email_ids:
        return []

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                id,
                subject,
                body
            FROM historical_emails
            WHERE id = ANY(%s)
        """, (email_ids,))

        rows = cursor.fetchall()

        email_map = {
            row[0]: {
                "id": row[0],
                "subject": row[1] or "",
                "body": row[2] or ""
            }
            for row in rows
        }

        return [
            email_map[email_id]
            for email_id in email_ids
            if email_id in email_map
        ]

    finally:

        cursor.close()
        db_pool.putconn(conn)

def update_final_reply(email_id, final_reply):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            UPDATE messages
            SET final_reply = %s
            WHERE id = %s
        """, (
            final_reply,
            email_id
        ))

        conn.commit()

    finally:

        cursor.close()
        db_pool.putconn(conn)

def update_reply_type(email_id, reply_type):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            UPDATE messages
            SET reply_type = %s
            WHERE id = %s
        """, (
            reply_type,
            email_id
        ))

        conn.commit()

    finally:

        cursor.close()
        db_pool.putconn(conn)

def get_email_thread(thread_id):

    conn = db_pool.getconn()

    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                id,
                sender,
                source,
                body,
                created_at,
                reply_type,
                status
            FROM messages
            WHERE thread_id = %s
            ORDER BY created_at ASC
        """, (thread_id,))

        rows = cur.fetchall()

        return rows

    finally:
        db_pool.putconn(conn)


from psycopg2.extras import RealDictCursor



def get_message_by_message_id(message_id):

    if not message_id:
        return None

    message_id = " ".join(message_id.split()).strip()

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute(
        """
        SELECT *
        FROM messages
        WHERE message_id = %s
        """,
        (message_id,)
    )

    row = cursor.fetchone()

    cursor.close()
    conn.close()

    return row

def get_support_emails():

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute("""
            SELECT
                id,
                sender,
                subject,
                source,
                category,
                priority,
                status,
                reply_type,
                created_at,
                ai_summary
            FROM messages
            WHERE mailbox = 'support'
            ORDER BY created_at DESC
        """)

        rows = cursor.fetchall()

        for row in rows:

            if row["created_at"]:
                row["created_at"] = row["created_at"].strftime("%b %-d, %-I:%M %p")

        return rows

    finally:
        cursor.close()
        db_pool.putconn(conn)