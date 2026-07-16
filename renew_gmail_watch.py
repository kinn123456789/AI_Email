import os

from dotenv import load_dotenv

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
TOPIC = f"projects/{PROJECT_ID}/topics/gmail-watch"

ACCOUNTS = [
    {
        "email": os.getenv("EMAIL_1"),
        "token": "token_support.json"
    },
    {
        "email": os.getenv("EMAIL_2"),
        "token": "token_lucy.json"
    },
    {
        "email": os.getenv("EMAIL_3"),
        "token": "token_engineering.json"
    },
    {
        "email": os.getenv("EMAIL_4"),
        "token": "token_sat.json"
    }
]


def renew_watch(account):

    token_path = os.path.join("/etc/secrets", account["token"])

    if not os.path.exists(token_path):
        token_path = account["token"]

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

    response = service.users().watch(
        userId="me",
        body={
            "topicName": TOPIC,
            "labelIds": ["INBOX"]
        }
    ).execute()

    print("=" * 60)
    print(account["email"])
    print("Watch renewed")
    print(response)
    print("=" * 60)


def main():

    for account in ACCOUNTS:

        try:

            renew_watch(account)

        except Exception as e:

            print(account["email"])
            print(e)


if __name__ == "__main__":
    main()