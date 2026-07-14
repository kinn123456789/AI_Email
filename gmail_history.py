import os

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://mail.google.com/"]


def get_gmail_history(token_file, history_id):

    token_path = os.path.join("/etc/secrets", token_file)

    # Local fallback
    if not os.path.exists(token_path):
        token_path = token_file

    creds = Credentials.from_authorized_user_file(
        token_path,
        SCOPES
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        # Save refreshed token locally only
        if not token_path.startswith("/etc/secrets"):
            with open(token_path, "w") as f:
                f.write(creds.to_json())

    service = build(
        "gmail",
        "v1",
        credentials=creds
    )

    result = service.users().history().list(
        userId="me",
        startHistoryId=history_id
    ).execute()

    print("=" * 80)
    print("GMAIL HISTORY")
    print(result)
    print("=" * 80)

    return result