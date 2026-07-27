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
    """

    knowledge = search_knowledge_base(
        subject=f"{category}: {subject}",
        body=body
    )

    return generate_reply(
        gmail_message_id=f"teacher_portal:{message_id}" if message_id else "teacher_portal",
        subject=subject,
        body=body,
        category=category,
        priority=priority,
        thread_history=thread_history,
        historical_emails=[],
        knowledge=knowledge
    )
