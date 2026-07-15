import os
import base64
import email

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://mail.google.com/"]


def get_message(token_file, message_id):

    token_path = os.path.join("/etc/secrets", token_file)

    if not os.path.exists(token_path):
        token_path = token_file

    creds = Credentials.from_authorized_user_file(
        token_path,
        SCOPES
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    service = build(
        "gmail",
        "v1",
        credentials=creds
    )

    response = service.users().messages().get(
        userId="me",
        id=message_id,
        format="raw"
    ).execute()

    msg = email.message_from_bytes(
        base64.urlsafe_b64decode(response["raw"])
    )

    return msg