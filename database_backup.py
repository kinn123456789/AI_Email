import psycopg2
import time



def get_connection():
    return psycopg2.connect(
        dbname="ai_email",
        user="kinnu"
    )

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
    conn.close()
    
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
    conn.close()

    return exists
def get_emails():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            sender,
            subject,
            source,
            category,
            priority,
            status,
            is_read,
            created_at,
            email_date
        FROM messages
        ORDER BY
            is_read ASC,
            CASE priority
                WHEN 'Urgent' THEN 1
                WHEN 'High' THEN 2
                WHEN 'Medium' THEN 3
                WHEN 'Low' THEN 4
                ELSE 5
            END,
            email_date DESC NULLS LAST,
            created_at DESC;
    """)
    rows = cursor.fetchall()

    cursor.close()
    conn.close()

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
    conn.close()

    return counts

def get_emails_by_category(category):
    conn = get_connection()
    cursor = conn.cursor() 
    cursor.execute("""
        SELECT id, sender, subject, category, status
        FROM messages
        WHERE category = %s
        ORDER BY id DESC
    """, (category,))
    rows= cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def get_email_by_id(email_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, sender, subject, body, category
        FROM messages
        WHERE id = %s
    """, (email_id,))
    
    rows= cursor.fetchone()
    cursor.close()
    conn.close()
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
    conn.close()
def save_conversation(
    chat_id,
    parent_name,
    teacher_name,
    updated_at
):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO conversations(
            chat_id,
            parent_name,
            teacher_name,
            updated_at
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (chat_id)
        DO NOTHING
    """, (
        chat_id,
        parent_name,
        teacher_name,
        updated_at
    ))

    conn.commit()
    cursor.close()
    conn.close()

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
    conn.close()

def get_conversations():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT *
        FROM conversations
        ORDER BY updated_at DESC
    """)

    rows= cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def get_conversation_messages(chat_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""

        SELECT *
        FROM conversation_messages
        WHERE chat_id = %s
        ORDER BY created_at ASC
    """, (chat_id,))
    
    rows= cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

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
    conn.close()
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
    conn.close()

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
    conn.close()
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
    conn.close()
    return rows


def get_unprocessed_contact_forms():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            subject,
            body
        FROM messages
        WHERE source = 'contact_form'
        AND ai_summary IS NULL
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {
            "id": r[0],
            "subject": r[1],
            "body": r[2]
        }
        for r in rows
    ]


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
    conn.close()

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
    conn.close()


def get_thread(thread_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sender,
               subject,
               body,
               created_at,reply_type,source
        FROM messages
        WHERE thread_id = %s
        ORDER BY created_at
    """, (thread_id,))

    rows= cursor.fetchall()
    cursor.close()
    conn.close()

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
    conn.close()
    if row:
        return row[0]

    return None

def mark_email_read(email_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE messages
        SET is_read = TRUE
        WHERE id = %s
    """, (email_id,))

    conn.commit()
    cursor.close()
    conn.close()