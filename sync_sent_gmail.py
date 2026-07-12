import os
import email
import imaplib
from email.utils import parseaddr
from email.header import decode_header, make_header
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from emails_cleaner import clean_email_body
# Project modules
from logger import logger
from database import (
    db_pool,
    save_email,
    email_exists,
    get_message_by_message_id,
)

load_dotenv()

EMAIL_ACCOUNTS = [
    {"email": os.getenv("EMAIL_4"), "token": "token_sat.json", "source": "shopsat19@gmail.com"},
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

    
    
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        with open(token_path, "w") as token:
            token.write(creds.to_json())

  
    auth_string = f"user={email_address}\1auth=Bearer {creds.token}\1\1"
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.authenticate("XOAUTH2", lambda x: auth_string.encode())
    return mail

def main():
    for account in EMAIL_ACCOUNTS:
        logger.info(f"Checking sent mail for {account['source']}")
        mail = None
        try:
            mail = oauth_login(account["email"], account["token"])
            status, _ = mail.select('"[Gmail]/Sent Mail"')
            if status != "OK":
                logger.error(f"Could not open Sent Mail for {account['source']}")
                continue

            status, search_data = mail.search(None, "ALL")
            
            if status != "OK": continue

            
            message_ids = search_data[0].split()[-20:]
            imported, skipped = 0, 0

            for sent_id in message_ids:
                try:
                    status, msg_data = mail.fetch(sent_id, "(RFC822)")
                    if status != "OK": continue

                    msg = email.message_from_bytes(msg_data[0][1])
                    message_id = " ".join((msg.get("Message-ID") or "").split())

                    if not message_id or email_exists(message_id):
                        skipped += 1
                        logger.info(f"Duplicate skipped: {message_id}")
                        continue

                    # Normalization & Threading
                    in_reply_to = " ".join((msg.get("In-Reply-To") or "").split())
                    references = " ".join((msg.get("References") or "").split())
                    
                    thread_id, parent = message_id, None
                    if in_reply_to:
                        parent = get_message_by_message_id(in_reply_to)
                    
                    if not parent and references:
                        for ref in reversed(references.split()):
                            parent = get_message_by_message_id(ref)
                            if parent: break
                    
                    if parent:
                        thread_id = parent["thread_id"]
                        logger.info(f"Thread linked: {message_id} -> {thread_id}")
                    else:
                        logger.info(f"New thread: {message_id}")


                    ai_summary = "Reply sent"
                    reply_type = "human"
                    
                    # Body Extraction
                    body, html_body = "", ""
                    for part in msg.walk():
                        if part.get_filename(): continue
                        content_type = part.get_content_type()
                        payload = part.get_payload(decode=True)
                        if not payload: continue
                        if content_type == "text/plain": body += payload.decode(errors="ignore")
                        elif content_type == "text/html": html_body += payload.decode(errors="ignore")

                    if not body.strip() and html_body:
                        body = BeautifulSoup(html_body, "html.parser").get_text(separator=" ", strip=True)

                    # Remove quoted reply history
                    body = clean_email_body(body)

                    save_email(
                        sender=parseaddr(msg.get("From", ""))[1],
                        subject=str(make_header(decode_header(msg.get("Subject", "")))),
                        body=body,
                        category="Human Reply",
                        priority="Low",
                        ai_summary="Reply sent manually from Gmail",
                        ai_draft_reply=body,
                        message_id=message_id,
                        thread_id=thread_id,
                        in_reply_to=in_reply_to,
                        source=account["source"],
                        status="Replied",
                        requires_review=False,
                        reply_type="gmail_manual",
                        references_header=references
                    )
                    imported += 1
                    logger.info(f"Imported: {message_id}")
                    mail.store(sent_id, '+FLAGS', '\\Seen')

                except Exception:
                    logger.exception(f"Failed processing sent email {sent_id}")
                    continue

            logger.info(f"{account['source']} sync complete. Imported={imported}, Skipped={skipped}")

        except Exception:
            logger.exception(f"Failed to process {account['source']}")
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass

if __name__ == "__main__":
    main()