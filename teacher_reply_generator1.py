# teacher_reply_generator.py

from knowledge_search import search_knowledge_base
from reply_generator import generate_reply


def generate_teacher_reply(
    subject,
    body,
    category,
    priority,
    thread_history="",
    message_id=None
):
    """
    Generates an AI reply for Teacher Portal conversations.

    This function's own return contract is unchanged - callers (e.g.
    teacher_ai_processor1.py) still get back just the reply text, exactly
    as before. generate_reply() itself now returns (reply_text, status);
    that status is captured and logged here for visibility, but not
    propagated further, since Teacher Portal has no requires_review-style
    field to put it in today - adding one would be a separate change, not
    part of unpacking this return value correctly.
    """

    knowledge = search_knowledge_base(
        subject=f"{category}: {subject}",
        body=body,
        audience="teacher"
    )

    reply_text, generation_status = generate_reply(
        gmail_message_id=f"teacher_portal:{message_id}" if message_id else "teacher_portal",
        subject=subject,
        body=body,
        category=category,
        priority=priority,
        thread_history=thread_history,
        historical_emails=[],
        knowledge=knowledge,
        audience="teacher"
    )

    if generation_status != "ok":
        print(
            f"Teacher Portal reply generation status='{generation_status}' "
            f"for message_id={message_id!r} (reply_text will be empty, same "
            "as this status's behavior before generate_reply() returned a tuple)"
        )

    return reply_text
