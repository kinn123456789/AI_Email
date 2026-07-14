import os
import email
import base64
import time
import imaplib
import traceback


from email.utils import parseaddr
from email.header import decode_header
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from email_sender import send_email
from sync_sent_gmail import main as sync_sent_mail

# Vector & Knowledge Search
from vector_search import search_similar_emails
from rag_reranker import rerank_emails
from reply_generator import generate_reply
from emails_cleaner import clean_email_body
from knowledge_search import search_knowledge_base
from process_email import process_email

# Custom modules
from email_filter import is_automated_email
from ai_classifier import ai_triage


# Configuration
load_dotenv()
ATTACHMENT_DIR = "attachments"
if not os.path.exists(ATTACHMENT_DIR):
    os.makedirs(ATTACHMENT_DIR)

EMAIL_ACCOUNTS = [
    
    {
        "email": os.getenv("EMAIL_1"),
        "token": "token_support.json",
        "source": "support@coralacademy.com",
    },
    {
        "email": os.getenv("EMAIL_2"),
        "token": "token_lucy.json",
        "source": "lucy@coralacademy.com",
    },
    {
        "email": os.getenv("EMAIL_3"),
        "token": "token_engineering.json",
        "source": "engineering@coralacademy.com",
    },
    {
        "email": os.getenv("EMAIL_4"),
        "token": "token_sat.json",
        "source": "shopsat19@gmail.com",
    }
]

import os

def oauth_login(email_address, token_file):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    token_path = os.path.join("/etc/secrets", token_file)

    # Local fallback
    if not os.path.exists(token_path):
        token_path = token_file

    creds = Credentials.from_authorized_user_file(
        token_path,
        ["https://mail.google.com/"]
    )

    print("=" * 60)
    print("Using token:", token_path)
    print("Email:", email_address)
    print("Token expires:", creds.expiry)
    print("Has refresh token:", bool(creds.refresh_token))
    print("=" * 60)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        # Save refreshed token only when running locally
        if not token_path.startswith("/etc/secrets"):
            with open(token_path, "w") as token:
                token.write(creds.to_json())

    
    auth_string = f"user={email_address}\1auth=Bearer {creds.token}\1\1"
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.authenticate("XOAUTH2", lambda x: auth_string.encode())
    return mail

def main():
    for account in EMAIL_ACCOUNTS:
        
        print("=" * 60)
        print("Checking:", account["source"])
        print("Token:", account["token"])
        print("=" * 60)
        if not account.get("email") or not account.get("token"):
            continue

        mail = None
        
        try:
            mail = oauth_login(account["email"], account["token"])
            mail.select("INBOX")
            
            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                continue

            # EXACT ORIGINAL LIMITING LOGIC RESTORED
            mail_ids = messages[0].split()

            for email_id in mail_ids:

                status, msg_data = mail.fetch(
                    email_id,
                    "(RFC822)"
                )

                if (
                    status != "OK"
                    or not msg_data
                    or not isinstance(msg_data[0], tuple)
                ):
                    continue

                msg = email.message_from_bytes(
                    msg_data[0][1]
                )

                try:

                    process_email(
                        msg=msg,
                        account=account
                    )

                    mail.store(
                        email_id,
                        '+FLAGS',
                        '\\Seen'
                    )

                except Exception:
                    traceback.print_exc()

        finally:
            if mail:
                mail.logout()

    print("=" * 60)
    print("ABOUT TO START SENT MAIL SYNC")
    print("=" * 60)

    try:
        sync_sent_mail()

        print("=" * 60)
        print("SENT MAIL SYNC FINISHED")
        print("=" * 60)

    except Exception:
        print("=" * 60)
        print("SENT MAIL SYNC FAILED")
        traceback.print_exc()

    print("=" * 60)


if __name__ == "__main__":
    main()