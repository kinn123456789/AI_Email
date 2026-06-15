import psycopg2

conn = psycopg2.connect(
    dbname="ai_email",
    user="kinnu"
)

cursor = conn.cursor() # creates a tool that can execute SQL commands from Python

def save_email(
    sender,
    subject,
    body,
    category,
    message_id,
    source=None,
    contact_name=None,
    phone=None
):

    cursor.execute("""
        INSERT INTO messages(
            sender,
            subject,
            body,
            category,
            message_id,
            source,
            contact_name,
            phone
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        sender,
        subject,
        body,
        category,
        message_id,
        source,
        contact_name,
        phone
    ))

    conn.commit()

def email_exists(message_id):

    cursor.execute(
        """
        SELECT id
        FROM messages
        WHERE message_id = %s
        LIMIT 1
        """,
        (message_id,)
    )

    return cursor.fetchone() is not None
def get_emails():

    cursor.execute("""
        SELECT id, sender, subject, category, status
        FROM messages
        ORDER BY id DESC
    """)
    return cursor.fetchall()
def get_category_counts():

    cursor.execute("""
        SELECT category, COUNT(*)
        FROM messages
        GROUP BY category
    """)

    return cursor.fetchall()

def get_emails_by_category(category):

    cursor.execute("""
        SELECT id, sender, subject, category, status
        FROM messages
        WHERE category = %s
        ORDER BY id DESC
    """, (category,))
    return cursor.fetchall()

def get_email_by_id(email_id):

    cursor.execute("""
        SELECT id, sender, subject, body, category
        FROM messages
        WHERE id = %s
    """, (email_id,))

    return cursor.fetchone()
def update_status(email_id, status):

    cursor.execute("""
        UPDATE messages
        SET status = %s
        WHERE id = %s
    """, (status, email_id))

    conn.commit()
def save_conversation(
    chat_id,
    parent_name,
    teacher_name,
    updated_at
):

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


def save_conversation_message(
    chat_id,
    sender,
    body,
    created_at,
    message_id
):

    cursor.execute("""
        INSERT INTO conversation_messages(
            chat_id,
            sender,
            body,
            created_at,
            message_id
                   
        )
        VALUES (%s, %s, %s, %s,%s)
    """, (
        chat_id,
        sender,
        body,
        created_at,
        message_id
    ))

    conn.commit()
def get_conversations():

    cursor.execute("""
        SELECT *
        FROM conversations
        ORDER BY updated_at DESC
    """)

    return cursor.fetchall()


def get_conversation_messages(chat_id):

    cursor.execute("""
        SELECT *
        FROM conversation_messages
        WHERE chat_id = %s
        ORDER BY created_at ASC
    """, (chat_id,))

    return cursor.fetchall()

def conversation_message_exists(message_id):

    cursor.execute("""
        SELECT id
        FROM conversation_messages
        WHERE message_id = %s
        LIMIT 1
    """, (message_id,))

    return cursor.fetchone() is not None
