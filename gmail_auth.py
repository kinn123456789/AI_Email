import os
import json
import imaplib
import threading

from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.send",
]

# Every caller of get_delegated_credentials() used to pay for a live network
# round-trip to Google's OAuth token endpoint on every single call, even for
# the same mailbox seconds apart - e.g. a single /email/{id}/send request
# does this twice (once via send_email(), once via get_message() fetching
# the sent message back), which was slow enough to occasionally trip a
# proxy/timeout in front of the app and close the client's connection while
# the request kept running server-side regardless. Cached per (email,
# scopes) here instead - a service-account token is valid ~1 hour, and
# google.auth.Credentials.valid already accounts for expiry, so this only
# actually refreshes over the network when truly needed.
_creds_cache = {}
_creds_cache_lock = threading.Lock()


def get_delegated_credentials(email_address, scopes=None):
    scopes = scopes or SCOPES
    cache_key = (email_address, tuple(scopes))

    with _creds_cache_lock:
        cached = _creds_cache.get(cache_key)
        if cached and cached.valid:
            return cached

    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

    if service_account_json:
        service_account_info = json.loads(service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=scopes,
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            "service-account.json",
            scopes=scopes,
        )

    creds = creds.with_subject(email_address)
    creds.refresh(Request())

    with _creds_cache_lock:
        _creds_cache[cache_key] = creds

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