import json

from database import get_connection, db_pool


# Maps a raw ai_logs.error value (an OpenRouter/API error dump, or an
# internal safety-check message) to a short, plain sentence a non-technical
# staff member can act on. The raw text stays in the database untouched -
# this is only for what gets shown on the /ai-insights errors view, so
# whoever fixes the underlying bug can still see the real error.
def humanize_ai_error(raw_error):

    if not raw_error:
        return None

    text = str(raw_error).lower()

    if "context length" in text or "context_length" in text:
        return "This conversation was too long for AI to process. Please reply manually."

    if "teacher/staff-only wording" in text or "content leak" in text:
        return "AI couldn't safely write a draft for this one. Please reply manually."

    if "rate limit" in text or "429" in text:
        return "AI was too busy to respond right now. Please reply manually or try again shortly."

    if "timeout" in text or "timed out" in text:
        return "AI took too long to respond. Please reply manually."

    return "AI couldn't generate a draft for this. Please reply manually."


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