#gmail_history.py
import os
import base64
import email
import traceback

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from database import get_last_history_id, update_last_history_id

SCOPES = ["https://mail.google.com/"]


def _build_service(token_file):

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

        if not token_path.startswith("/etc/secrets"):
            with open(token_path, "w") as f:
                f.write(creds.to_json())

    return build(
        "gmail",
        "v1",
        credentials=creds
    )


def get_gmail_history(token_file, history_id, page_token=None):

    service = _build_service(token_file)

    kwargs = {
        "userId": "me",
        "startHistoryId": history_id,
        "historyTypes": ["messageAdded"]
    }

    if page_token:
        kwargs["pageToken"] = page_token

    result = service.users().history().list(
        **kwargs
    ).execute()

    print("=" * 80)
    print("GMAIL HISTORY")
    print(result)
    print("=" * 80)

    return result


def _resync_from_scratch(account):

    from email_reader import main as imap_full_sync

    print(f"[{account['source']}] No/expired history id — running full IMAP sync as fallback")

    imap_full_sync(account["email"])

    service = _build_service(account["token"])
    profile = service.users().getProfile(userId="me").execute()

    update_last_history_id(account["email"], profile["historyId"])

    print(f"[{account['source']}] Captured fresh historyId: {profile['historyId']}")


def run_history_reader(email_address, webhook_history_id=None):

    from email_reader import EMAIL_ACCOUNTS
    from process_email import process_email

    account = next(
        (a for a in EMAIL_ACCOUNTS if a["email"] == email_address),
        None
    )

    if not account:
        print("Unknown mailbox in history webhook:", email_address)
        return

    last_history_id = get_last_history_id(account["email"])

    if not last_history_id:
        _resync_from_scratch(account)
        return

    added_ids = set()
    page_token = None
    newest_history_id = int(last_history_id)

    try:
        while True:
            response = get_gmail_history(
                account["token"],
                last_history_id,
                page_token=page_token
            )

            for record in response.get("history", []):
                for added in record.get("messagesAdded", []):
                    added_ids.add(added["message"]["id"])

            if "historyId" in response:
                newest_history_id = max(
                    newest_history_id,
                    int(response["historyId"])
                )

            page_token = response.get("nextPageToken")

            if not page_token:
                break

    except HttpError as e:
        if e.resp.status == 404:
            _resync_from_scratch(account)
            return
        raise

    print(f"[{account['source']}] History API: {len(added_ids)} new message(s)")

    service = _build_service(account["token"])

    for msg_id in added_ids:
        try:
            raw = service.users().messages().get(
                userId="me",
                id=msg_id,
                format="raw"
            ).execute()

            msg = email.message_from_bytes(
                base64.urlsafe_b64decode(raw["raw"])
            )

            process_email(msg=msg, account=account)

        except Exception:
            traceback.print_exc()
            continue

    if webhook_history_id:
        newest_history_id = max(newest_history_id, int(webhook_history_id))

    update_last_history_id(account["email"], newest_history_id)
