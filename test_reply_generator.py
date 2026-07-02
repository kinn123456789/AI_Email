from reply_generator import generate_reply

similar_emails = [
    {
        "subject": "Child absent",
        "body": "My son has a fever and will miss tomorrow's class."
    },
    {
        "subject": "Reschedule request",
        "body": "Can we move Friday's class to next Monday?"
    },
    {
        "subject": "Vacation notice",
        "body": "Our family will be away next week."
    }
]

reply = generate_reply(
    subject="Child absent tomorrow",
    body="My daughter has a fever and won't be able to attend tomorrow's class.",
    category="Attendance",
    priority="Medium",
    thread_history="No previous messages.",
    similar_emails=similar_emails
)

print("\nGenerated Reply:\n")
print(reply)