import os
import email
import base64
import time
import imaplib
import traceback
from datetime import datetime, timedelta


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
from email.utils import parsedate_to_datetime

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
    }
]

def oauth_login(email_address, token_file=None):
    # token_file is unused now (kept only so existing callers don't need to
    # change) - auth is via domain-wide delegation, impersonating
    # email_address directly. See gmail_auth.py.
    from gmail_auth import imap_login
    return imap_login(email_address)

def main(target_email=None):
    for account in EMAIL_ACCOUNTS:
        if (
            target_email
            and account["email"] != target_email
        ):
            continue
        
        print("=" * 60)
        print("Checking:", account["source"])
        print("Token:", account["token"])
        print("=" * 60)
        if not account.get("email") or not account.get("token"):
            continue

        mail = None
        
        try:
            mail = oauth_login(account["email"], account["token"])
            mail.select("INBOX", readonly=True)

            since_date = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
            status, messages = mail.search(None, "OR", "UNSEEN", "SINCE", since_date)
            print(account["source"], "Unread/recent emails:", len(messages[0].split()))
            if status != "OK":
                continue

            # EXACT ORIGINAL LIMITING LOGIC RESTORED
            mail_ids = messages[0].split()

            for email_id in mail_ids:

                status, msg_data = mail.fetch(
                    email_id,
                    "(BODY.PEEK[])"
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
                

                email_date = parsedate_to_datetime(msg["Date"])
                try:
                    process_email(
                        msg=msg,
                        account=account
                    )
                except Exception:
                    traceback.print_exc()
                    continue

                

        finally:
            if mail:
                try:
                    mail.logout()
                except Exception:
                    pass

    print("=" * 60)
    print("ABOUT TO START SENT MAIL SYNC")
    print("=" * 60)

   # try:
       # sync_sent_mail()

        #print("=" * 60)
       # print("SENT MAIL SYNC FINISHED")
       # print("=" * 60)

    #except Exception:
       # print("=" * 60)
       # print("SENT MAIL SYNC FAILED")
       # traceback.print_exc()

    print("=" * 60)


if __name__ == "__main__":
    main()