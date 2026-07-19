from ai_classifier import ai_triage
from teacher_reply_generator1 import generate_teacher_reply

from database import (
    get_unclassified_teacher_messages,
    update_teacher_ai_fields,
    get_conversation_messages
)


def build_thread_history(chat_id, teacher_id):

    messages = get_conversation_messages(chat_id)

    history = []

    for msg in messages:

        sender = "Teacher" if msg["sender"] == teacher_id else "Parent"

        history.append(
            f"{sender}: {msg['body']}"
        )

    return "\n".join(history)

def process_teacher_messages():

    messages = get_unclassified_teacher_messages()

    print("\n" + "=" * 60)
    print("TEACHER AI PROCESSOR")
    print("=" * 60)

    print(f"Messages waiting for AI: {len(messages)}")

    processed = 0
    failed = 0

    for msg in messages:

        message_id = msg["message_id"]
        chat_id = msg["chat_id"]
        teacher_id = msg["sender"]
        body = (msg["body"] or "").strip()

        if not body:
            continue

        try:

            print(f"\nProcessing Message: {message_id}")

            # ------------------------
            # AI Classification
            # ------------------------

            result = ai_triage(
                subject="Teacher Portal Message",
                body=body
            )

            # ------------------------
            # Build Thread History
            # ------------------------

            thread_history = build_thread_history(
                chat_id,
                teacher_id
            )

            # ------------------------
            # Generate AI Reply
            # ------------------------

            draft_reply = None

            if result.get("needs_reply", False):

                draft_reply = generate_teacher_reply(
                    subject="Teacher Portal Message",
                    body=body,
                    category=result["category"],
                    priority=result["priority"],
                    thread_history=thread_history
                )

            # ------------------------
            # Save AI Results
            # ------------------------

            update_teacher_ai_fields(
                message_id=message_id,
                category=result["category"],
                priority=result["priority"],
                summary=result["summary"],
                draft_reply=draft_reply
            )

            processed += 1

            print("✓ Database Updated")
            print("Category :", result["category"])
            print("Priority :", result["priority"])

        except Exception as e:

            failed += 1

            print(f"✗ Failed : {message_id}")
            print("Error:", e)

    print("\n" + "=" * 60)
    print("PROCESSING COMPLETE")
    print("=" * 60)
    print(f"Processed : {processed}")
    print(f"Failed    : {failed}")


if __name__ == "__main__":
    process_teacher_messages()