import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# Increased max connections to 25 to handle bulk processing overhead
db_pool = SimpleConnectionPool(
    1, 25,
    dsn=os.environ.get("DATABASE_URL")
)

def get_connection():
    return db_pool.getconn()

# --- HELPER PATTERN: Every function now uses try/finally ---

def save_email(sender, subject, body, category, priority, ai_summary, ai_draft_reply, message_id, thread_id, in_reply_to, source=None, contact_name=None, phone=None, status="New"):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO messages(sender, subject, body, category, priority, ai_summary, ai_draft_reply, message_id, thread_id, in_reply_to, source, contact_name, phone, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (sender, subject, body, category, priority, ai_summary, ai_draft_reply, message_id, thread_id, in_reply_to, source, contact_name, phone, status))
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
        cursor.execute("SELECT id, sender, subject, category, priority, status, created_at, first_reply_at, resolved_at FROM messages ORDER BY id DESC")
        return cursor.fetchall()
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
        cursor.execute("SELECT id, sender, subject, category, status FROM messages WHERE category = %s ORDER BY id DESC", (category,))
        return cursor.fetchall()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_email_by_id(email_id):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute("SELECT id, sender, subject, body, category, ai_summary, ai_draft_reply, priority, status, source FROM messages WHERE id = %s", (email_id,))
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

def get_thread(thread_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT sender, subject, body, created_at FROM messages WHERE thread_id = %s ORDER BY created_at", (thread_id,))
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

def save_historical_email(message_id, thread_id, in_reply_to, reference_ids, sender, recipient, subject, body, sent_at, source_account, has_attachment, attachment_count):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO historical_emails (message_id, thread_id, in_reply_to, reference_ids, sender, recipient, subject, body, sent_at, source_account, has_attachment, attachment_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (message_id) DO NOTHING
            RETURNING id
        """, (message_id, thread_id, in_reply_to, reference_ids, sender, recipient, subject, body, sent_at, source_account, has_attachment, attachment_count))
        result = cursor.fetchone()
        conn.commit()
        return result[0] if result else None
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        db_pool.putconn(conn)