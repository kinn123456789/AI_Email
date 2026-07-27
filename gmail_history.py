#gmail_history.py
import os
import base64
import email
import threading
import traceback

from googleapiclient.errors import HttpError

from gmail_auth import get_gmail_service
from database import get_last_history_id, update_last_history_id

_locks_guard = threading.Lock()
_reader_locks = {}

_pending_lock = threading.Lock()
_pending_mailboxes = set()


def _get_lock(email_address):

    with _locks_guard:

        if email_address not in _reader_locks:
            _reader_locks[email_address] = threading.Lock()

        return _reader_locks[email_address]


def _build_service(email_address):

    return get_gmail_service(email_address)


def get_gmail_history(email_address, history_id, page_token=None):

    service = _build_service(email_address)

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

    service = _build_service(account["email"])
    profile = service.users().getProfile(userId="me").execute()

    update_last_history_id(account["email"], profile["historyId"])

    print(f"[{account['source']}] Captured fresh historyId: {profile['historyId']}")


def run_history_reader(email_address, webhook_history_id=None):

    lock = _get_lock(email_address)

    if not lock.acquire(blocking=False):

        with _pending_lock:
            _pending_mailboxes.add(email_address)

        print(f"History reader busy for {email_address}, queued.")
        return

    try:

        while True:

            _run_history_reader_once(email_address, webhook_history_id)

            # Only the triggering webhook's historyId hint applies to the
            # first pass; a queued re-run re-derives everything from the DB.
            webhook_history_id = None

            with _pending_lock:

                if email_address not in _pending_mailboxes:
                    break

                _pending_mailboxes.discard(email_address)

            print(f"Re-running history reader for {email_address} (caught up while busy)")

    finally:
        lock.release()


def _run_history_reader_once(email_address, webhook_history_id=None):

    from email_reader import get_email_accounts
    from process_email import process_email

    account = next(
        (a for a in get_email_accounts() if a["email"] == email_address),
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
                account["email"],
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

    if webhook_history_id:
        newest_history_id = max(newest_history_id, int(webhook_history_id))

    service = _build_service(account["email"])

    any_failed = False

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
            any_failed = True
            continue

    # Only advance the checkpoint if every message in this batch was
    # actually processed. If we advanced it unconditionally and one message
    # failed, the History API would never report that message again on a
    # future run — it would be permanently skipped. Leaving the checkpoint
    # behind means this whole batch gets re-fetched next run instead;
    # already-succeeded messages are cheaply no-op'd by process_email()'s
    # own message_id dedup check at the top, so only the failed one(s)
    # actually get retried.
    if not any_failed:
        update_last_history_id(account["email"], newest_history_id)
    else:
        print(f"[{account['source']}] Not advancing history checkpoint — at least one message failed and will be retried next run.")
