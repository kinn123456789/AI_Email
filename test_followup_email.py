from followup_ai import generate_followup_email
from followup_email import send_email

candidate = {
    "learner_name": "Emma"
}

subject, body = generate_followup_email(
    candidate,
    parent_name="Q",
    email_number=1
)

success = send_email(
    #"shopsat19@gmail.com",
    "support@coralacademy.com",
    subject,
    body
)

if success:
    print("✅ Email sent successfully!")
else:
    print("❌ Email sending failed.")