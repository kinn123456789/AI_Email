import os
import json
import imaplib

from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.send",
]


def get_delegated_credentials(email_address, scopes=None):
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

    if service_account_json:
        service_account_info = json.loads(service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=scopes or SCOPES,
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            "service-account.json",
            scopes=scopes or SCOPES,
        )

    creds = creds.with_subject(email_address)
    creds.refresh(Request())
    return creds

def get_gmail_service(email_address, scopes=None):
    return build(
        "gmail",
        "v1",
        credentials=get_delegated_credentials(email_address, scopes),
    )


def imap_login(email_address, scopes=None):
    creds = get_delegated_credentials(email_address, scopes)

    auth_string = f"user={email_address}\1auth=Bearer {creds.token}\1\1"

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.authenticate("XOAUTH2", lambda x: auth_string.encode())
    return mail