from knowledge_search import search_knowledge_base
from reply_generator import generate_reply


def generate_teacher_reply(
    subject,
    body,
    category,
    priority,
    thread_history=""
):
    knowledge = search_knowledge_base(
        subject,
        body
    )

    return generate_reply(
        gmail_message_id="teacher_portal",
        subject=subject,
        body=body,
        category=category,
        priority=priority,
        thread_history=thread_history,
        similar_emails=[],
        knowledge=knowledge
    )