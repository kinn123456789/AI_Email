import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("TEACHER_PORTAL_API_KEY")
BASE_URL = "https://api.preprod.coralacademy.com"


def send_teacher_reply(chat_id, teacher_id, message):
    """
    Sends a reply to a Teacher Portal chat.

    Returns:
        {
            "success": True/False,
            "status_code": int,
            "data": response_json_or_text
        }
    """

    if not API_KEY:
        raise ValueError(
            "TEACHER_PORTAL_API_KEY is not configured. Set it in your environment or .env file."
        )

    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "teacher_id": teacher_id,
        "chat_id": chat_id,
        "text": message
    }

    print("\n" + "=" * 60)
    print("SENDING TEACHER REPLY")
    print("=" * 60)
    print("Chat ID    :", chat_id)
    print("Teacher ID :", teacher_id)
    print("Message    :", message)
    print("=" * 60)

    try:
        response = requests.post(
            f"{BASE_URL}/ai-email/reply",
            headers=headers,
            json=payload,
            timeout=20
        )

        print("Status Code :", response.status_code)

        try:
            response_data = response.json()
        except Exception:
            response_data = response.text

        print("Response :", response_data)

        return {
            "success": response.ok,
            "status_code": response.status_code,
            "data": response_data
        }

    except requests.RequestException as e:
        print("Teacher Portal Error:", e)

        return {
            "success": False,
            "status_code": None,
            "data": str(e)
        }
    
    
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
from email.utils import parsedate_to_datetime
from database import set_sent_time

load_dotenv()

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
    },
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
        logger.info(f"Checking sent mail for {account['source']}")
        mail = None
        try:
            mail = oauth_login(account["email"], account["token"])
            status, _ = mail.select('"[Gmail]/Sent Mail"')
            if status != "OK":
                logger.error(f"Could not open Sent Mail for {account['source']}")
                continue

            status, search_data = mail.search(None, '(SINCE "20-Jul-2026")')
            
            if status != "OK": continue

            
            message_ids = search_data[0].split()[-100:]
            imported, skipped = 0, 0

            for sent_id in message_ids:
                try:
                    status, msg_data = mail.fetch(sent_id, "(RFC822)")
                    if status != "OK": continue

                    

                    

                    msg = email.message_from_bytes(msg_data[0][1])

                    email_date = parsedate_to_datetime(msg["Date"])

                    message_id = " ".join((msg.get("Message-ID") or "").split())

                    #if not message_id or email_exists(message_id):
                       # skipped += 1
                        #logger.info(f"Duplicate skipped: {message_id}")
                       # continue#}

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
                        set_sent_time(parent["id"])
                        logger.info(f"Thread linked: {message_id} -> {thread_id}")
                    else:
                        logger.info(f"New thread: {message_id}")

                    if not message_id or email_exists(message_id):
                        skipped += 1
                        logger.info(f"Duplicate skipped: {message_id}")
                        continue


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
                    
                    has_attachment = any(
                        part.get_filename()
                        for part in msg.walk()
                    )
                    
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
                        references_header=references,
                        email_date=email_date,
                        has_attachment=has_attachment
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
