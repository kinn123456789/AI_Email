from database import save_email

email_id = save_email(
    sender="mytest@gmail.com",
    subject="Refund Request",
    body="I'd like a refund for my child's classes.",
    category="General",
    priority="Medium",
    ai_summary="Parent is requesting a refund.",
    ai_draft_reply="""Hi,

Thank you for contacting Coral Academy.

We'll review your refund request and get back to you shortly.

Regards,
Coral Academy""",
    message_id="test_refund_001",
    thread_id="test_thread_001",
    in_reply_to=None,
    source="support@coralacademy.com",
    status="Needs Review",
    requires_review=True,
    ai_confidence=72,
    knowledge_url=None
)

print(email_id)