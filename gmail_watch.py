import os

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOPIC = "projects/lively-lock-500515-e4/topics/gmail-notifications"

SCOPES = ["https://mail.google.com/"]


def register_watch(token_file):

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

    service = build("gmail", "v1", credentials=creds)

    result = service.users().watch(
        userId="me",
        body={
            "topicName": TOPIC
        }
    ).execute()

    profile = service.users().getProfile(userId="me").execute()

    print("=" * 70)
    print(f"Watch registered for: {profile['emailAddress']}")
    print(result)
    print("=" * 70)
    return result

def renew_all_gmail_watches():

    tokens = [
        "token_support.json",
        "token_lucy.json",
        "token_engineering.json",
        "token_sat.json"
    ]

    for token in tokens:
        try:
            register_watch(token)
        except Exception as e:
            print(f"Failed to renew {token}: {e}")
    