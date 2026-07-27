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

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

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

    except Exception as log_err:
        # A failure here (bad connection, constraint violation, etc.) must
        # never propagate to the caller - generate_reply() and friends
        # call this AFTER already successfully producing a draft, so
        # letting a logging error crash the whole function would throw
        # away a perfectly good draft over a problem with the log entry
        # itself. Print so it's still visible in Render's stdout capture,
        # but never re-raise.
        print(f"Failed to save ai_log for {gmail_message_id}:", log_err)

    finally:

        if cursor:
            cursor.close()
        if conn:
            db_pool.putconn(conn)