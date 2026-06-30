import base64

from email.mime.text import MIMEText
from email.utils import make_msgid

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


SCOPES = ["https://mail.google.com/"]


def send_email(
    from_email,
    token_file,
    to_email,
    subject,
    body
):
    try:
        # Load OAuth credentials
        creds = Credentials.from_authorized_user_file(
            token_file,
            SCOPES
        )

        # Refresh token if needed
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

            with open(token_file, "w") as token:
                token.write(creds.to_json())

        # Build Gmail service
        service = build(
            "gmail",
            "v1",
            credentials=creds
        )

        # Create email
        message = MIMEText(body)

        message["To"] = to_email
        message["From"] = from_email
        message["Subject"] = subject

        message_id = make_msgid()
        message["Message-ID"] = message_id

        raw_message = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode()

        # Send email
        service.users().messages().send(
            userId="me",
            body={
                "raw": raw_message
            }
        ).execute()

        print(
            f"Email sent from {from_email} to {to_email}"
        )

        return message_id

    except Exception as e:

        print(f"Send Email Error: {e}")

        return None