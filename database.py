import psycopg2
import time


from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

db_pool = SimpleConnectionPool(
    1,   # min connections
    10,  # max connections
    dbname="ai_email",
    user="kinnu"
)

def get_connection():
    return db_pool.getconn()
##def get_connection():
   ## return psycopg2.connect(
     ##   dbname="ai_email",
     ##   user="kinnu"
   ## )

##conn = psycopg2.connect(
 ##   dbname="ai_email",
   ## user="kinnu"
##)

##cursor = conn.cursor() # creates a tool that can execute SQL commands from Python

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
    phone=None
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages(
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
            source,
            contact_name,
            phone
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        
        RETURNING id
    """, (
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
        source,
        contact_name,
        phone
    ))

    result = cursor.fetchone()

    if result:
        email_id = result[0]
    else:
        email_id = None

    conn.commit()
    cursor.close()
    db_pool.putconn(conn)
    
    return email_id

def email_exists(message_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id
        FROM messages
        WHERE message_id = %s
        LIMIT 1
        """,
        (message_id,)
    )

    exists= cursor.fetchone() is not None
    cursor.close()
    db_pool.putconn(conn)

    return exists
def get_emails():
    conn = get_connection()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cursor.execute("""
        SELECT
            id,
            sender,
            subject,
            category,
            priority,
            status,
            created_at,
            first_reply_at,
            resolved_at
        FROM messages
        ORDER BY id DESC
    """)

    rows = cursor.fetchall()

    cursor.close()
    db_pool.putconn(conn)

    return rows

    

def get_category_counts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT category, COUNT(*)
        FROM messages
        GROUP BY category
    """)
    
    counts= cursor.fetchall()
    cursor.close()
    db_pool.putconn(conn)

    return counts

def get_emails_by_category(category):
    conn = get_connection()
    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    ) 
    cursor.execute("""
        SELECT id, sender, subject, category, status
        FROM messages
        WHERE category = %s
        ORDER BY id DESC
    """, (category,))
    rows= cursor.fetchall()
    cursor.close()
    db_pool.putconn(conn)
    return rows

def get_email_by_id(email_id):
    conn = get_connection()
    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cursor.execute("""
        SELECT id,
        sender,
        subject,
        body,
        category,
        ai_summary,
        ai_draft_reply,
        priority,
        status,
        source
        FROM messages
        WHERE id = %s
    """, (email_id,))
    
    rows= cursor.fetchone()
    cursor.close()
    db_pool.putconn(conn)
    return rows
def update_status(email_id, status):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE messages
        SET status = %s
        WHERE id = %s
    """, (status, email_id))

    conn.commit()
    cursor.close()
    db_pool.putconn(conn)
def save_conversation(
    chat_id,
    parent_name,
    teacher_name,
    parent_id,
    teacher_id,
    updated_at
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO conversations(
            chat_id,
            parent_name,
            teacher_name,
            parent_id,
            teacher_id,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (chat_id)
    DO UPDATE SET
        parent_name = EXCLUDED.parent_name,
        teacher_name = EXCLUDED.teacher_name,
        parent_id = EXCLUDED.parent_id,
        teacher_id = EXCLUDED.teacher_id,
        updated_at = EXCLUDED.updated_at

""", (
    chat_id,
    parent_name,
    teacher_name,
    parent_id,
    teacher_id,
    updated_at
))

    conn.commit()
    cursor.close()
    db_pool.putconn(conn)

def save_conversation_message(
    chat_id,
    sender,
    body,
    created_at,
    message_id
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO conversation_messages(
            chat_id,
            sender,
            body,
            created_at,
            message_id
                   
        )
        VALUES (%s, %s, %s, %s,%s)
        ON CONFLICT (message_id)
        DO NOTHING
    """, (
        chat_id,
        sender,
        body,
        created_at,
        message_id
    ))
    
    conn.commit()
    cursor.close()
    db_pool.putconn(conn)

from psycopg2.extras import RealDictCursor


def get_conversation_messages(chat_id):
    conn = get_connection()
    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )
    cursor.execute("""

        SELECT *
        FROM conversation_messages
        WHERE chat_id = %s
        ORDER BY created_at ASC
    """, (chat_id,))
    
    rows= cursor.fetchall()
    cursor.close()
    db_pool.putconn(conn)
    return rows

from psycopg2.extras import RealDictCursor

def get_conversation(chat_id):
    conn = get_connection()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cursor.execute("""
        SELECT *
        FROM conversations
        WHERE chat_id = %s
    """, (chat_id,))

    row = cursor.fetchone()

    cursor.close()
    db_pool.putconn(conn)

    return row

def conversation_message_exists(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id
        FROM conversation_messages
        WHERE message_id = %s
        LIMIT 1
    """, (message_id,))

    exists= cursor.fetchone() is not None
    cursor.close()
    db_pool.putconn(conn)
    return exists

def save_attachment(
    message_id,
    filename,
    file_type,
    file_path
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO attachments(
            message_id,
            filename,
            file_type,
            file_path
        )
        VALUES (%s, %s, %s, %s)
    """, (
        message_id,
        filename,
        file_type,
        file_path
    ))

    conn.commit()
    cursor.close()
    db_pool.putconn(conn)

def get_attachments(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM attachments
        WHERE message_id = %s
    """, (message_id,))

    rows= cursor.fetchall()
    cursor.close()
    db_pool.putconn(conn)
    return rows
def attachment_exists(
    message_id,
    filename
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id
        FROM attachments
        WHERE message_id = %s
        AND filename = %s
        LIMIT 1
    """, (
        message_id,
        filename
    ))
    
    rows= cursor.fetchone() is not None
    cursor.close()
    db_pool.putconn(conn)
    return rows


def get_contact_forms():
    conn = get_connection()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cursor.execute("""
        SELECT *
        FROM messages
        WHERE source = 'contact_form'
        ORDER BY created_at DESC
    """)

    rows = cursor.fetchall()

    cursor.close()
    db_pool.putconn(conn)

    return rows


def update_ai_results(
    message_id,
    category,
    priority,
    summary,
    draft_reply
):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE messages
        SET
            category=%s,
            priority=%s,
            ai_summary=%s,
            ai_draft_reply=%s
        WHERE id=%s
    """, (
        category,
        priority,
        summary,
        draft_reply,
        message_id
    ))

    conn.commit()

    cur.close()
    db_pool.putconn(conn)

def log_event(
    message_id,
    event_type,
    details
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO email_logs(
            message_id,
            event_type,
            details
        )
        VALUES (%s, %s, %s)
    """, (
        message_id,
        event_type,
        details
    ))

    conn.commit()
    cursor.close()
    db_pool.putconn(conn)


def get_thread(thread_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sender,
               subject,
               body,
               created_at
        FROM messages
        WHERE thread_id = %s
        ORDER BY created_at
    """, (thread_id,))

    rows= cursor.fetchall()
    cursor.close()
    db_pool.putconn(conn)

    return rows

def get_root_thread_id(message_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT thread_id
        FROM messages
        WHERE message_id = %s
        LIMIT 1
    """, (message_id,))

    row = cursor.fetchone()
    cursor.close()
    db_pool.putconn(conn)
    if row:
        return row[0]

    return None

def set_first_reply_time(email_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE messages
        SET first_reply_at = NOW()
        WHERE id = %s
        AND first_reply_at IS NULL
    """, (email_id,))

    conn.commit()
    cursor.close()
    db_pool.putconn(conn)

def set_resolved_time(email_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE messages
        SET resolved_at = NOW()
        WHERE id = %s
        AND resolved_at IS NULL
    """, (email_id,))

    conn.commit()
    cursor.close()
    db_pool.putconn(conn)

def reopen_thread(thread_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE messages
        SET status = 'Needs Review'
        WHERE thread_id = %s
        AND status = 'Resolved'
    """, (thread_id,))

    conn.commit()

    cursor.close()
    db_pool.putconn(conn)
def set_sent_time(email_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE messages
        SET sent_at = CURRENT_TIMESTAMP
        WHERE id = %s
        AND sent_at IS NULL
    """, (email_id,))

    conn.commit()

    cur.close()
    db_pool.putconn(conn)

def update_sent_message_id(
    email_id,
    sent_message_id
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE messages
        SET sent_message_id = %s
        WHERE id = %s
    """, (
        sent_message_id,
        email_id
    ))

    conn.commit()

    cursor.close()
    db_pool.putconn(conn)
def resolve_thread(thread_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE messages
        SET status = 'Resolved'
        WHERE thread_id = %s
    """, (thread_id,))

    conn.commit()

    cursor.close()
    db_pool.putconn(conn)

def get_avg_first_response_time():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT AVG(first_reply_at - created_at)
        FROM messages
        WHERE first_reply_at IS NOT NULL
    """)

    result = cursor.fetchone()[0]

    cursor.close()
    db_pool.putconn(conn)

    return result
   
def get_avg_resolution_time():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT AVG(resolved_at - created_at)
        FROM messages
        WHERE resolved_at IS NOT NULL
    """)

    result = cursor.fetchone()[0]

    cursor.close()
    db_pool.putconn(conn)

    return result

def get_unclassified_teacher_messages():

    conn = get_connection()
    
    cursor = conn.cursor(
    cursor_factory=RealDictCursor
)

    cursor.execute("""
        SELECT
            id,
            message_id,
            body
        FROM conversation_messages
    WHERE
        ai_processed = FALSE
        AND body IS NOT NULL
        AND TRIM(body) <> ''
        ORDER BY created_at
        LIMIT 3
    """)

    rows = cursor.fetchall()

    cursor.close()
    db_pool.putconn(conn)

    return rows

def update_teacher_ai_fields(
    message_id,
    category,
    priority,
    summary,
    draft_reply
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE conversation_messages
        SET
            ai_category = %s,
            ai_priority = %s,
            ai_summary = %s,
            ai_draft_reply = %s,
            ai_processed = TRUE
        WHERE message_id = %s
    """, (
        category,
        priority,
        summary,
        draft_reply,
        message_id
    ))

    conn.commit()

    cursor.close()

from psycopg2.extras import RealDictCursor

def get_teacher_messages():

    conn = get_connection()

    cursor = conn.cursor(
        cursor_factory=RealDictCursor
    )

    cursor.execute("""
        SELECT
            id,
            chat_id,
            sender,
            body,
            ai_category,
            ai_priority,
            ai_summary,
            created_at
        FROM conversation_messages
        ORDER BY created_at DESC
        LIMIT 100
    """)

    rows = cursor.fetchall()

    cursor.close()
    db_pool.putconn(conn)

    return rows
    db_pool.putconn(conn)
