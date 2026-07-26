import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import re
from psycopg2.extras import RealDictCursor
from datetime import timezone

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
    references_header=None,
    email_date=None,
    is_read=False,
    has_attachment=False,
    sender_name=None
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
                knowledge_url, reply_type, mailbox, references_header,email_date,is_read,has_attachment,
                sender_name
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING id
        """, (
            sender, subject, body, category, priority, ai_summary,
            ai_draft_reply, message_id, thread_id, in_reply_to, source,
            contact_name, phone, status, requires_review, ai_confidence,
            knowledge_url, reply_type, mailbox, references_header, email_date, is_read , has_attachment,
            sender_name
        ))
        result = cursor.fetchone()
        conn.commit()
        return result[0] if result else None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def find_recipient_name(email):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT parent_name FROM trial_followup_email_logs WHERE recipient_email = %s AND parent_name IS NOT NULL LIMIT 1",
            (email,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        cursor.execute(
            "SELECT sender_name FROM messages WHERE sender = %s AND sender_name IS NOT NULL LIMIT 1",
            (email,)
        )
        row = cursor.fetchone()
        if row:
            return row[0]

        return None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def email_exists(message_id, source):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id FROM messages WHERE message_id = %s AND source = %s LIMIT 1",
            (message_id, source)
        )
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_emails(source=None, search=None, status=None, date_from=None, date_to=None, page=1, page_size=50):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Added a CASE statement to order by priority weight before ID
        params = []
        filters = ""

        if source:
            filters += " AND source = %s"
            params.append(source)

        if status:
            filters += " AND status = %s"
            params.append(status)

        if date_from:
            filters += " AND created_at::date >= %s"
            params.append(date_from)

        if date_to:
            filters += " AND created_at::date <= %s"
            params.append(date_to)

        if search:
            filters += " AND (subject ILIKE %s OR sender ILIKE %s OR body ILIKE %s)"
            like = f"%{search}%"
            params.extend([like, like, like])

        cursor.execute(f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'Needs Review') AS needs_review_count,
                COUNT(*) FILTER (WHERE reply_type = 'automatic') AS auto_reply_count
            FROM messages
            WHERE mailbox = 'inbox'
            AND status != 'Resolved'
            AND reply_type IS DISTINCT FROM 'gmail_manual'
            {filters}
        """, params)

        counts_row = cursor.fetchone()
        total = counts_row["total"]

        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size

        cursor.execute(f"""
            SELECT
                id, sender, subject, source, category, priority, status,
                reply_type, created_at, first_reply_at, resolved_at,
                knowledge_url, ai_confidence, ai_summary, ai_draft_reply, requires_review, is_read, has_attachment
            FROM messages
            WHERE mailbox = 'inbox'
            AND status != 'Resolved'
            AND reply_type IS DISTINCT FROM 'gmail_manual'
            {filters}
            ORDER BY
                is_read ASC,

                CASE status
                    WHEN 'Needs Review' THEN 1
                    WHEN 'Replied' THEN 2
                    ELSE 3
                END,

                CASE priority
                    WHEN 'Urgent' THEN 1
                    WHEN 'High' THEN 2
                    WHEN 'Medium' THEN 3
                    WHEN 'Low' THEN 4
                    ELSE 5
                END,
                email_date DESC NULLS LAST,
                created_at DESC
            LIMIT %s OFFSET %s;
        """, params + [page_size, offset])

        rows = cursor.fetchall()
        # ... (rest of your existing logic for date formatting and handled_by)
        for row in rows:
            print(row["id"], row["is_read"])

            #if row["created_at"]:
               # row["created_at"] = row["created_at"].strftime("%b %-d, %-I:%M %p")
            if row["created_at"]:
                # Raw UTC ISO timestamp, formatted client-side into the
                # viewer's own local timezone by static/local-time.js —
                # not fixed to IST server-side anymore.
                row["created_at"] = row["created_at"].replace(tzinfo=timezone.utc).isoformat()
            # NEW
            if row["reply_type"] == "automatic":
                row["handled_by"] = "AI"

            elif row["reply_type"] in ("human", "gmail_manual"):
                row["handled_by"] = "Human"

            else:
                row["handled_by"] = None

        return {
            "rows": rows,
            "total": total,
            "needs_review_count": counts_row["needs_review_count"],
            "auto_reply_count": counts_row["auto_reply_count"],
            "page": page,
            "total_pages": total_pages,
        }

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
            #if row["created_at"]:
                #row["created_at"] = row["created_at"].strftime("%b %-d, %-I:%M %p")
            if row["created_at"]:
                # Raw UTC ISO timestamp, formatted client-side into the
                # viewer's own local timezone by static/local-time.js —
                # not fixed to IST server-side anymore.
                row["created_at"] = row["created_at"].replace(tzinfo=timezone.utc).isoformat()

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

def save_conversation(
    chat_id,
    parent_name,
    teacher_name,
    parent_id,
    teacher_id,
    updated_at,
    last_message,
    last_message_id,
    unread_count=0,
    ai_summary=None,
    ai_priority=None,
):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO conversations (
                chat_id,
                parent_name,
                teacher_name,
                parent_id,
                teacher_id,
                updated_at,
                last_message,
                last_message_id,
                unread_count,
                ai_summary,
                ai_priority
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

            ON CONFLICT (chat_id)
            DO UPDATE SET
                parent_name = EXCLUDED.parent_name,
                teacher_name = EXCLUDED.teacher_name,
                parent_id = EXCLUDED.parent_id,
                teacher_id = EXCLUDED.teacher_id,
                updated_at = EXCLUDED.updated_at,
                last_message = EXCLUDED.last_message,
                last_message_id = EXCLUDED.last_message_id,
                unread_count = EXCLUDED.unread_count,
                ai_summary = EXCLUDED.ai_summary,
                ai_priority = EXCLUDED.ai_priority
            """,
            (
                chat_id,
                parent_name,
                teacher_name,
                parent_id,
                teacher_id,
                updated_at,
                last_message,
                last_message_id,
                unread_count,
                ai_summary,
                ai_priority,
            ),
        )

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
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT
            chat_id,
            parent_name,
            teacher_name,
            teacher_id,
            parent_id
        FROM conversations
        WHERE chat_id = %s
    """, (chat_id,))

    row = cur.fetchone()

    cur.close()
    db_pool.putconn(conn)

    return row

def conversation_message_exists(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM conversation_messages WHERE message_id = %s LIMIT 1", (message_id,))
        return cursor.fetchone() is not None
    finally:
        cursor.close()
        db_pool.putconn(conn)

def delete_conversation_message(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM conversation_messages WHERE message_id = %s", (message_id,))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def save_attachment(message_id, filename, file_type, file_path, file_data=None):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO attachments(message_id, filename, file_type, file_path, file_data) VALUES (%s, %s, %s, %s, %s)",
            (message_id, filename, file_type, file_path, psycopg2.Binary(file_data) if file_data else None)
        )
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_attachments(message_id):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            "SELECT id, message_id, filename, file_type, created_at FROM attachments WHERE message_id = %s",
            (message_id,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_attachment_by_id(attachment_id):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            "SELECT filename, file_type, file_data FROM attachments WHERE id = %s",
            (attachment_id,)
        )
        return cursor.fetchone()
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

def get_contact_forms(search=None, date_from=None, date_to=None, page=1, page_size=50, status=None):

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        params = []
        filters = ""

        if date_from:
            filters += " AND (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata')::date >= %s"
            params.append(date_from)

        if date_to:
            filters += " AND (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata')::date <= %s"
            params.append(date_to)

        if status:
            filters += " AND status = %s"
            params.append(status)

        if search:
            filters += " AND (contact_name ILIKE %s OR sender ILIKE %s OR phone ILIKE %s OR body ILIKE %s)"
            like = f"%{search}%"
            params.extend([like, like, like, like])

        own_accounts = (
            "support@coralacademy.com",
            "lucy@coralacademy.com",
            "engineering@coralacademy.com"
        )

        cursor.execute(f"""
            SELECT COUNT(*) AS total
            FROM messages
            WHERE mailbox = 'contact_form'
            AND sender NOT IN %s
            {filters}
        """, [own_accounts] + params)

        total = cursor.fetchone()["total"]
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size

        cursor.execute(f"""
            SELECT *
            FROM messages
            WHERE mailbox = 'contact_form'
            AND sender NOT IN %s
            {filters}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, [own_accounts] + params + [page_size, offset])

        rows = cursor.fetchall()

        for row in rows:
            if row["created_at"]:
                # Raw UTC ISO timestamp, formatted client-side into the
                # viewer's own local timezone by static/local-time.js —
                # not fixed to IST server-side anymore.
                row["created_at"] = row["created_at"].replace(tzinfo=timezone.utc).isoformat()

        return {
            "rows": rows,
            "total": total,
            "page": page,
            "total_pages": total_pages,
        }

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
            ORDER BY COALESCE(email_date, created_at) ASC
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
        cursor.execute("""
            SELECT AVG(
                EXTRACT(EPOCH FROM (sent_at - created_at)) / 60
            )
            FROM messages
            WHERE sent_at IS NOT NULL
        """)

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

        cursor.execute("""
            SELECT DISTINCT ON (cm.chat_id)
                cm.id,
                cm.message_id,
                cm.chat_id,
                cm.sender,
                cm.body
            FROM conversation_messages cm
            JOIN conversations c
              ON cm.chat_id = c.chat_id
            WHERE cm.ai_processed = FALSE
              AND cm.sender = c.parent_id
              AND cm.body IS NOT NULL
              AND TRIM(cm.body) <> ''
            ORDER BY cm.chat_id, cm.created_at DESC
        """)

        return cursor.fetchall()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_teacher_ai_fields(message_id, category, priority, summary, draft_reply, row_id=None):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        if row_id is not None:
            cursor.execute("""
                UPDATE conversation_messages
                SET ai_category = %s,
                    ai_priority = %s,
                    ai_summary = %s,
                    ai_draft_reply = %s,
                    ai_processed = TRUE
                WHERE id = %s
            """, (category, priority, summary, draft_reply, row_id))
        else:
            cursor.execute("""
                UPDATE conversation_messages
                SET ai_category = %s,
                    ai_priority = %s,
                    ai_summary = %s,
                    ai_draft_reply = %s,
                    ai_processed = TRUE
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
        cursor.execute("""
            SELECT *
            FROM (
                SELECT DISTINCT ON (cm.chat_id)
                    cm.id,
                    cm.chat_id,
                    cm.sender,
                    cm.body,
                    cm.ai_category,
                    cm.ai_priority,
                    cm.ai_draft_reply,
                    cm.ai_summary,
                    cm.created_at,
                    cm.is_read,

                    c.parent_name,
                    c.teacher_name,
                    c.parent_id,
                    c.teacher_id

                FROM conversation_messages cm

                JOIN conversations c
                    ON cm.chat_id = c.chat_id

                ORDER BY
                    cm.chat_id,
                    cm.created_at DESC,
                    cm.id DESC
            ) latest

            ORDER BY
                latest.created_at DESC,

                CASE latest.ai_priority
                    WHEN 'Urgent' THEN 1
                    WHEN 'High' THEN 2
                    WHEN 'Medium' THEN 3
                    WHEN 'Low' THEN 4
                    ELSE 5
                END,

                latest.created_at DESC;
        """)

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
            ON CONFLICT (message_id) DO NOTHING
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

        row = cursor.fetchone()

        conn.commit()

        return row[0] if row else None

    except Exception:

        conn.rollback()
        raise

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
            ORDER BY email_date ASC
        """, (thread_id,))

        rows = cur.fetchall()

        return rows

    finally:
        db_pool.putconn(conn)


from psycopg2.extras import RealDictCursor


def get_message_by_message_id(message_id, source):

    if not message_id:
        return None

    message_id = " ".join(message_id.split()).strip()

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute(
            """
            SELECT *
            FROM messages
            WHERE message_id = %s AND source = %s
            """,
            (message_id, source)
        )

        return cursor.fetchone()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_support_emails(source=None, search=None, date_from=None, date_to=None, page=1, page_size=50):

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        params = []
        filters = ""

        if source:
            filters += " AND source = %s"
            params.append(source)

        if date_from:
            filters += " AND (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata')::date >= %s"
            params.append(date_from)

        if date_to:
            filters += " AND (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Kolkata')::date <= %s"
            params.append(date_to)

        if search:
            filters += " AND (subject ILIKE %s OR sender ILIKE %s OR body ILIKE %s)"
            like = f"%{search}%"
            params.extend([like, like, like])

        cursor.execute(f"""
            SELECT COUNT(*) AS total
            FROM messages
            WHERE mailbox = 'support'
            {filters}
        """, params)

        total = cursor.fetchone()["total"]
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size

        cursor.execute(f"""
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
                ai_summary,
                has_attachment
            FROM messages
            WHERE mailbox = 'support'
            {filters}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [page_size, offset])

        rows = cursor.fetchall()

        for row in rows:

            #if row["created_at"]:
                #row["created_at"] = row["created_at"].strftime("%b %-d, %-I:%M %p")

            if row["created_at"]:
                # Raw UTC ISO timestamp, formatted client-side into the
                # viewer's own local timezone by static/local-time.js —
                # not fixed to IST server-side anymore.
                row["created_at"] = row["created_at"].replace(tzinfo=timezone.utc).isoformat()

        return {
            "rows": rows,
            "total": total,
            "page": page,
            "total_pages": total_pages,
        }



    finally:
        cursor.close()
        db_pool.putconn(conn)

from psycopg2.extras import RealDictCursor

def get_latest_ai_summary(thread_id):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT ai_summary
            FROM messages
            WHERE thread_id = %s
              AND reply_type <> 'gmail_manual'
              AND ai_summary IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
        """, (thread_id,))

        row = cursor.fetchone()

        if row:
            return row["ai_summary"]

        return None

    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_latest_thread_ai(thread_id):

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cur.execute("""
            SELECT
                ai_summary,
                ai_draft_reply,
                category,
                priority,
                ai_confidence,
                requires_review
            FROM messages
            WHERE thread_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (thread_id,))

        return cur.fetchone()

    finally:
        cur.close()
        db_pool.putconn(conn)

def get_last_history_id(email_address):

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT history_id
            FROM gmail_watch_state
            WHERE email_address = %s
        """, (email_address,))

        row = cur.fetchone()

        if row:
            return row[0]

        return None

    finally:
        cur.close()
        db_pool.putconn(conn)

def update_last_history_id(email_address, history_id):

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO gmail_watch_state (
                email_address,
                history_id
            )
            VALUES (%s, %s)
            ON CONFLICT (email_address)
            DO UPDATE
            SET history_id = EXCLUDED.history_id
        """, (email_address, history_id))

        conn.commit()

    finally:
        cur.close()
        db_pool.putconn(conn)


def reopen_thread(thread_id):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            UPDATE messages
            SET status = 'Needs Review'
            WHERE thread_id = %s
              AND status = 'Resolved'
            """,
            (thread_id,)
        )

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def mark_email_read(email_id):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE messages
        SET is_read = TRUE
        WHERE id = %s
    """, (email_id,))

    conn.commit()

    cur.close()
    db_pool.putconn(conn)

def set_sent_time(email_id):
    conn = db_pool.getconn()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE messages
                SET sent_at = NOW()
                WHERE id = %s
                AND sent_at IS NULL
            """, (email_id,))
            conn.commit()
    finally:
        db_pool.putconn(conn)

def mark_conversation_read(chat_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE conversation_messages
            SET is_read = TRUE
            WHERE chat_id = %s
              AND is_read = FALSE
        """, (chat_id,))

        print("Rows updated:", cursor.rowcount)
        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_teacher_conversations(teacher_id):

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute("""
            SELECT *
            FROM (
                SELECT DISTINCT ON (cm.chat_id)

                    cm.chat_id,
                    cm.body,
                    cm.created_at,
                    cm.ai_priority,
                    cm.is_read,

                    c.parent_name,
                    c.parent_id,
                    c.teacher_name,
                    c.teacher_id,

                    EXISTS (
                        SELECT 1
                        FROM conversation_messages x
                        WHERE x.chat_id = cm.chat_id
                          AND x.sender = c.parent_id
                          AND x.is_read = FALSE
                    ) AS unread

                FROM conversation_messages cm

                JOIN conversations c
                  ON cm.chat_id = c.chat_id

                WHERE c.teacher_id = %s

                ORDER BY
                    cm.chat_id,
                    cm.created_at DESC,
                    cm.id DESC

            ) latest

            ORDER BY
                latest.unread DESC,
                latest.created_at DESC,
                CASE latest.ai_priority
                    WHEN 'Urgent' THEN 1
                    WHEN 'High' THEN 2
                    WHEN 'Medium' THEN 3
                    WHEN 'Low' THEN 4
                    ELSE 5
                END

        """, (teacher_id,))

        return cursor.fetchall()

    finally:

        cursor.close()
        db_pool.putconn(conn)


def get_last_message_id(chat_id):

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT last_message_id
            FROM conversations
            WHERE chat_id = %s
        """, (chat_id,))

        row = cursor.fetchone()

        if row:
            return row["last_message_id"]

        return None

    finally:
        cursor.close()
        db_pool.putconn(conn)

from psycopg2.extras import RealDictCursor

def get_teachers():

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute("""
            SELECT
                c.teacher_id,
                c.teacher_name,

                COUNT(DISTINCT c.chat_id) AS total_chats,

                COUNT(
                    DISTINCT CASE
                        WHEN cm.is_read = FALSE
                        THEN c.chat_id
                    END
                ) AS unread_chats,

                MAX(cm.created_at) AS last_activity

            FROM conversations c

            LEFT JOIN conversation_messages cm
                ON c.chat_id = cm.chat_id

            GROUP BY
                c.teacher_id,
                c.teacher_name

            ORDER BY
                MAX(cm.created_at) DESC NULLS LAST,
                c.teacher_name;
        """)

        return cursor.fetchall()

    finally:

        cursor.close()
        db_pool.putconn(conn)

def mark_reply_sent(message_id):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE conversation_messages
            SET
                reply_sent = TRUE,
                reply_sent_at = NOW()
            WHERE id = %s
        """, (message_id,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def save_teacher_reply(chat_id, teacher_id, body, message_id=None, created_at=None):

    print("SAVE_TEACHER_REPLY CALLED")

    conn = get_connection()
    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO conversation_messages
            (
                chat_id,
                sender,
                body,
                created_at,
                source,
                message_id,
                is_read
            )
            VALUES (%s, %s, %s, COALESCE(%s, NOW()), 'teacher_portal', %s, TRUE)
            ON CONFLICT (message_id) DO NOTHING
        """, (
            chat_id,
            teacher_id,
            body,
            created_at,
            message_id
        ))

        cur.execute("""
            UPDATE conversations
            SET
                updated_at = COALESCE(%s, NOW()),
                last_message = %s,
                last_message_id = COALESCE(%s, last_message_id)
            WHERE chat_id = %s
        """, (
            created_at,
            body,
            message_id,
            chat_id
        ))

        conn.commit()

        print("INSERT SUCCESS")

    except Exception as e:

        print("INSERT ERROR:", e)
        conn.rollback()
        raise

    finally:

        cur.close()
        db_pool.putconn(conn)

def mark_chat_read(chat_id, teacher_id):

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            UPDATE conversation_messages
            SET is_read = TRUE
            WHERE chat_id = %s
              AND sender <> %s
              AND is_read = FALSE
        """, (chat_id, teacher_id))

        conn.commit()

    finally:
        cur.close()
        db_pool.putconn(conn)

def move_to_trash(email_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Remember whichever mailbox this came from (inbox/support/contact_form)
        # so Restore can put it back where it actually belongs, instead of
        # guessing or dumping everything into one bucket.
        cursor.execute("""
            UPDATE messages
            SET previous_mailbox = mailbox, mailbox = 'trash'
            WHERE id = %s AND mailbox != 'trash'
        """, (email_id,))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)


def restore_emails_from_trash(email_ids):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE messages
            SET mailbox = COALESCE(previous_mailbox, 'inbox'), previous_mailbox = NULL
            WHERE id = ANY(%s) AND mailbox = 'trash'
        """, (email_ids,))
        conn.commit()
    finally:
        cursor.close()
        db_pool.putconn(conn)
from psycopg2.extras import RealDictCursor

def get_trash_emails():
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
                created_at
            FROM messages
            WHERE mailbox = 'trash'
            ORDER BY created_at DESC;
        """)

        rows = cursor.fetchall()

        for row in rows:
            #if row["created_at"]:
               # row["created_at"] = row["created_at"].strftime("%b %-d, %-I:%M %p")
            if row["created_at"]:
                # Raw UTC ISO timestamp, formatted client-side into the
                # viewer's own local timezone by static/local-time.js —
                # not fixed to IST server-side anymore.
                row["created_at"] = row["created_at"].replace(tzinfo=timezone.utc).isoformat()

            if row["reply_type"] == "automatic":
                row["handled_by"] = "AI"
            elif row["reply_type"] in ("human", "gmail_manual"):
                row["handled_by"] = "Human"
            else:
                row["handled_by"] = None

        return rows

    finally:
        cursor.close()
        db_pool.putconn(conn)



def delete_email(email_id):
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Get the Gmail Message-ID
        cursor.execute("""
            SELECT message_id
            FROM messages
            WHERE id = %s
        """, (email_id,))

        row = cursor.fetchone()

        if row and row["message_id"]:
            cursor.execute("""
                DELETE FROM attachments
                WHERE message_id = %s
            """, (row["message_id"],))

        cursor.execute("""
            DELETE FROM messages
            WHERE id = %s
        """, (email_id,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)
from psycopg2.extras import RealDictCursor

def get_notification_emails():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT
            id,
            subject,
            source,
            sender,
            category,
            created_at
        FROM messages
        WHERE status = 'No Reply Required'
          AND mailbox != 'trash'
        ORDER BY created_at DESC
    """)
    emails = cursor.fetchall()

    for row in emails:
        if row["created_at"]:
            # Raw UTC ISO timestamp, formatted client-side into the
            # viewer's own local timezone by static/local-time.js — not
            # fixed to IST server-side anymore.
            row["created_at"] = row["created_at"].replace(tzinfo=timezone.utc).isoformat()
    

    cursor.close()
    db_pool.putconn(conn)

    return emails

def has_attachments(message):
    payload = message.get("payload", {})

    for part in payload.get("parts", []):
        body = part.get("body", {})

        if body.get("attachmentId"):
            return True

    return False


def get_ai_insights():
    """Summary stats + recent errors from ai_logs — cost/performance/error
    tracking. This table is written on every AI draft attempt but had no
    reader anywhere in the app until this."""

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT
                COUNT(*) AS total_calls,
                COUNT(*) FILTER (WHERE error IS NOT NULL) AS error_count,
                COALESCE(SUM(prompt_tokens), 0) AS total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS total_completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(AVG(response_time_ms) FILTER (WHERE error IS NULL), 0) AS avg_response_time_ms
            FROM ai_logs
        """)
        summary = cursor.fetchone()

        cursor.execute("""
            SELECT category, COUNT(*) AS calls, COUNT(*) FILTER (WHERE error IS NOT NULL) AS errors
            FROM ai_logs
            GROUP BY category
            ORDER BY calls DESC
        """)
        by_category = cursor.fetchall()

        cursor.execute("""
            SELECT id, gmail_message_id, category, error, created_at
            FROM ai_logs
            WHERE error IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 20
        """)
        recent_errors = cursor.fetchall()

        for row in recent_errors:
            if row["created_at"]:
                row["created_at"] = row["created_at"].replace(tzinfo=timezone.utc).isoformat()

        return {
            "summary": summary,
            "by_category": by_category,
            "recent_errors": recent_errors,
        }

    finally:
        cursor.close()
        db_pool.putconn(conn)


def get_ai_log_by_message_id(gmail_message_id):
    """Look up the exact AI log entry for one email — what knowledge/
    historical examples it used, tokens, timing, and the raw draft — so a
    weird-looking reply can be traced back to why the AI wrote it."""

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT *
            FROM ai_logs
            WHERE gmail_message_id = %s
            ORDER BY created_at DESC
        """, (gmail_message_id,))
        rows = cursor.fetchall()

        for row in rows:
            if row["created_at"]:
                row["created_at"] = row["created_at"].replace(tzinfo=timezone.utc).isoformat()

        return rows

    finally:
        cursor.close()
        db_pool.putconn(conn)


HISTORICAL_EMAIL_RETENTION_MONTHS = 18


def prune_old_historical_emails():
    """Deletes historical_emails rows older than
    HISTORICAL_EMAIL_RETENTION_MONTHS — keeps the AI style-example pool
    from growing forever. Search speed doesn't meaningfully need this
    (the vector index stays fast regardless of table size at this scale),
    this is purely to bound storage/maintenance-script cost long-term.
    Returns the number of rows deleted."""

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "DELETE FROM historical_emails WHERE sent_at < NOW() - INTERVAL %s",
            (f"{HISTORICAL_EMAIL_RETENTION_MONTHS} months",)
        )
        deleted = cursor.rowcount
        conn.commit()
        return deleted

    finally:
        cursor.close()
        db_pool.putconn(conn)


def save_sync_log(job_name, account, started_at, finished_at, imported_count, skipped_count, error_count, error_message=None):
    """Durable, host-independent record of a sync job run — replaces
    relying on file/stdout logging (which depends on whichever platform
    happens to be capturing it) for basic "what happened during this run"
    visibility. Queryable regardless of hosting."""

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO sync_log
            (job_name, account, started_at, finished_at, imported_count, skipped_count, error_count, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (job_name, account, started_at, finished_at, imported_count, skipped_count, error_count, error_message)
        )
        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)
