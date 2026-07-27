# gmail_auth.py
"""
Centralized Gmail authentication via Domain-Wide Delegation.

Replaces the old per-account interactive-consent token files
(token_support.json, token_lucy.json, token_engineering.json - each
requiring its own manual consent flow via generate_oauthtoken.py) with a
single service account that can impersonate any @coralacademy.com mailbox
via .with_subject(email). One credential file, one auth path, for every
account and any future account, instead of a separate token file (and
separate one-time consent) per mailbox.

Confirmed working end-to-end (both the Gmail REST API and IMAP XOAUTH2,
all three mailboxes) before this migration touched any live file.
"""
import os
import imaplib

from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Confirmed complete for everything this app does with Gmail - verified by
# an exhaustive grep of every Google API call in the codebase before the
# domain-wide-delegation setup was requested in Google Admin.
SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.send",
]

_SERVICE_ACCOUNT_FILENAME = "service-account.json"


def _service_account_path():
    """Render secret files are mounted under /etc/secrets/ in production -
    same fallback pattern already used for the old token_*.json files, so
    local development just needs the file sitting in the project root."""

    render_path = os.path.join("/etc/secrets", _SERVICE_ACCOUNT_FILENAME)
    return render_path if os.path.exists(render_path) else _SERVICE_ACCOUNT_FILENAME


def get_delegated_credentials(email_address, scopes=None):
    """Refreshed, ready-to-use credentials impersonating one mailbox
    (support@/lucy@/engineering@coralacademy.com, or any future mailbox -
    no separate token file or consent step needed for a new one)."""

    creds = service_account.Credentials.from_service_account_file(
        _service_account_path(),
        scopes=scopes or SCOPES,
    ).with_subject(email_address)

    creds.refresh(Request())
    return creds


def get_gmail_service(email_address, scopes=None):
    """A ready-to-use Gmail API client for one mailbox."""

    return build(
        "gmail", "v1",
        credentials=get_delegated_credentials(email_address, scopes)
    )


def imap_login(email_address, scopes=None):
    """An authenticated IMAP4_SSL connection for one mailbox, via XOAUTH2 -
    drop-in replacement for the old oauth_login(email, token_file) helpers
    that used to live duplicated across several files."""

    creds = get_delegated_credentials(email_address, scopes)
    auth_string = f"user={email_address}\1auth=Bearer {creds.token}\1\1"

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.authenticate("XOAUTH2", lambda x: auth_string.encode())
    return mail
