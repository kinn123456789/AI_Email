import os
import base64

from dotenv import load_dotenv

from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://mail.google.com/"]

EMAIL_ACCOUNTS = [
    {
        "email": os.getenv("EMAIL_1"),
        "token": "token_support.json",
        "source": "support@coralacademy.com"
    }
]

def send_email(to_email, subject, body):

    try:
        account = EMAIL_ACCOUNTS[0]

        creds = Credentials.from_authorized_user_file(
            account["token"],
            SCOPES
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

            with open(account["token"], "w") as token:
                token.write(creds.to_json())

        service = build(
            "gmail",
            "v1",
            credentials=creds
        )

        message = MIMEText(body, "plain", "utf-8")
        message["To"] = to_email
        message["From"] = account["email"]
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
        print(f"Send Email Error: {type(e).__name__}: {e}")
        return None