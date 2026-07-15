import base64

from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


def send_new_email(
    from_email,
    token_file,
    to_email,
    subject,
    body
):

    creds = Credentials.from_authorized_user_file(
        token_file,
        ["https://www.googleapis.com/auth/gmail.send"]
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        with open(token_file, "w") as token:
            token.write(creds.to_json())

    service = build(
        "gmail",
        "v1",
        credentials=creds
    )

    message = MIMEText(body)

    message["To"] = to_email
    message["From"] = from_email
    message["Subject"] = subject

    raw = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode()

    sent = service.users().messages().send(
        userId="me",
        body={
            "raw": raw
        }
    ).execute()

    return sent