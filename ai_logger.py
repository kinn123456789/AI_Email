import json

from database import get_connection, db_pool


def save_ai_log(
    gmail_message_id,
    model,
    category,
    priority,
    reply_type,
    requires_review,
    prompt_tokens,
    completion_tokens,
    total_tokens,
    response_time_ms,
    knowledge_used,
    historical_examples,
    thread_history_length,
    ai_reply,
    error=None
):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            INSERT INTO ai_logs
            (
                gmail_message_id,
                model,
                category,
                priority,
                reply_type,
                requires_review,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                response_time_ms,
                knowledge_used,
                historical_examples,
                thread_history_length,
                ai_reply,
                error
            )

            VALUES
            (
                %s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,
                %s::jsonb,
                %s::jsonb,
                %s,
                %s,
                %s
            )
            """,
            (
                gmail_message_id,
                model,
                category,
                priority,
                reply_type,
                requires_review,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                response_time_ms,
                json.dumps(knowledge_used),
                json.dumps(historical_examples),
                thread_history_length,
                ai_reply,
                error,
            )
        )

        conn.commit()

    finally:

        cursor.close()
        db_pool.putconn(conn)