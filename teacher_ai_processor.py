from ai_classifier import ai_triage

from database import (
    get_unclassified_teacher_messages,
    update_teacher_ai_fields
)


def process_teacher_messages():

    messages = get_unclassified_teacher_messages()

    print("\n==========================")
    print("TEACHER AI PROCESSOR")
    print("==========================")

    print(
        f"Messages waiting for AI: {len(messages)}"
    )

    processed = 0
    failed = 0
    
    for msg in messages:

        
        message_id = msg["message_id"]
        body = msg["body"]
        if not body:
            continue
        try:

            print(
                f"\nProcessing: {message_id}"
            )

            result = ai_triage(
                subject="Teacher Portal Message",
                body=body
            )

            update_teacher_ai_fields(
                message_id=message_id,
                category=result["category"],
                priority=result["priority"],
                summary=result["summary"],
                draft_reply=result["draft_reply"]
            )

            processed += 1

            print(
                f"✓ Category: {result['category']}"
            )

            print(
                f"✓ Priority: {result['priority']}"
            )

        except Exception as e:

            failed += 1

            print(
                f"✗ Failed: {message_id}"
            )

            print(
                f"Error: {e}"
            )

    print("\n==========================")
    print("PROCESSING COMPLETE")
    print("==========================")

    print(
        f"Processed: {processed}"
    )

    print(
        f"Failed: {failed}"
    )


if __name__ == "__main__":

    process_teacher_messages()