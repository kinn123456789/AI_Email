import base64

from email.mime.text import MIMEText
from email.utils import make_msgid

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


SCOPES = ["https://mail.google.com/"]


def send_email(from_email, token_file, to_email, subject, body, thread_id=None, original_msg_id=None):
    try:
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as token:
                token.write(creds.to_json())

        service = build("gmail", "v1", credentials=creds)

        message = MIMEText(body, "plain", "utf-8")
        message["To"] = to_email
        message["From"] = from_email
        
        # Ensure the subject matches standard reply format
        if not subject.lower().startswith("re:"):
            message["Subject"] = f"Re: {subject}"
        else:
            message["Subject"] = subject

        # Clean up and add the local message identifiers
        message_id = make_msgid()
        message["Message-ID"] = message_id
        
        if original_msg_id:
            message["In-Reply-To"] = original_msg_id
            message["References"] = original_msg_id

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        # Build the payload mapping
        payload = {"raw": raw_message}
        if thread_id:
            payload["threadId"] = thread_id  # Enforces grouping inside Gmail's interface

        # Send email
        response = service.users().messages().send(
            userId="me",
            body=payload
        ).execute()
        
        return message_id

    except Exception as e:
        print(f"Send Email Error: {e}")
        return None