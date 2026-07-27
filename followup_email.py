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


def send_email(to_email, subject, body):

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