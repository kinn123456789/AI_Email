import os
import base64

from dotenv import load_dotenv

from email.mime.text import MIMEText

from gmail_auth import get_gmail_service

load_dotenv()

EMAIL_ACCOUNT = {
    "email": os.getenv("EMAIL_1"),
    "token": "token_support.json"
}


def send_email(to_email, subject, body, in_reply_to=None, references=None):

    service = None
    try:

        service = get_gmail_service(EMAIL_ACCOUNT["email"])

        message = MIMEText(
            body,
            "plain",
            "utf-8"
        )

        message["To"] = to_email
        message["From"] = EMAIL_ACCOUNT["email"]
        message["Subject"] = subject

        # Threading headers - chains follow-up #2/#3 (and manual replies) to
        # the earlier email(s) in this learner's campaign as real RFC-5322
        # replies, instead of each arriving as a disconnected email. See
        # trial_followup.get_previous_followup_messages() for how the caller
        # builds these from the campaign's prior sent messages.
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to

        if references:
            message["References"] = references
        elif in_reply_to:
            message["References"] = in_reply_to

        raw = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode("utf-8")

        response=service.users().messages().send(
            userId="me",
            body={"raw": raw}
        ).execute()

        return response["id"]

    except Exception as e:

        print(f"Send Email Error: {e}")

        return None

    finally:

        if service:
            service.close()