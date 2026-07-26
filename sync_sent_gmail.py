import os
import email
import imaplib
from datetime import datetime, timedelta, timezone
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
from database import set_sent_time, save_sync_log, get_last_successful_sync_time

load_dotenv()

# Fallback window used only when there's no prior clean sync recorded yet
# (first-ever run for this account). Once a checkpoint exists, the actual
# last-successful-sync time is used instead — see main().
BOOTSTRAP_WINDOW_DAYS = 7

# IMAP's SINCE search is date-only (no time-of-day precision), so the
# checkpoint is backed off by a day regardless of the exact finish time —
# a message from earlier the same calendar day as the last sync would
# match SINCE anyway, and email_exists() correctly skips it as a
# duplicate; this just guards against any edge case near a day boundary.
CHECKPOINT_BUFFER_DAYS = 1

# Sanity cap only — not the primary correctness mechanism anymore (the
# checkpoint is). Guards against a pathological case (checkpoint broken
# for a long time, huge backlog) rather than normal operation, where a
# run typically finds only a handful of genuinely new messages.
MAX_MESSAGES_PER_RUN = 500

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
        started_at = datetime.now(timezone.utc)
        imported, skipped, error_count = 0, 0, 0
        error_message = None

        try:
            mail = oauth_login(account["email"], account["token"])
            status, _ = mail.select('"[Gmail]/Sent Mail"')
            if status != "OK":
                logger.error(f"Could not open Sent Mail for {account['source']}")
                error_count += 1
                error_message = "Could not open Sent Mail"
                continue

            # Real checkpoint (the finish time of the last CLEAN run for
            # this account) instead of a fixed lookback window or a
            # count-based "last N" slice — either of those could silently
            # miss messages if volume in the window ever exceeded the
            # slice size. Falls back to a 7-day bootstrap window only on
            # the very first run, when there's no prior clean sync yet.
            last_success = get_last_successful_sync_time("sync_sent_gmail", account["source"])

            if last_success:
                since_dt = last_success - timedelta(days=CHECKPOINT_BUFFER_DAYS)
            else:
                since_dt = datetime.now(timezone.utc) - timedelta(days=BOOTSTRAP_WINDOW_DAYS)

            since_date = since_dt.strftime("%d-%b-%Y")
            status, search_data = mail.search(None, f'(SINCE "{since_date}")')

            if status != "OK": continue

            message_ids = search_data[0].split()[-MAX_MESSAGES_PER_RUN:]

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
                        parent = get_message_by_message_id(in_reply_to, account["source"])

                    if not parent and references:
                        for ref in reversed(references.split()):
                            parent = get_message_by_message_id(ref, account["source"])
                            if parent: break
                    
                    if parent:
                        thread_id = parent["thread_id"]
                        set_sent_time(parent["id"])
                        logger.info(f"Thread linked: {message_id} -> {thread_id}")
                    else:
                        logger.info(f"New thread: {message_id}")

                    if not message_id or email_exists(message_id, account["source"]):
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

                except Exception as e:
                    logger.exception(f"Failed processing sent email {sent_id}")
                    error_count += 1
                    error_message = str(e)
                    continue

            logger.info(f"{account['source']} sync complete. Imported={imported}, Skipped={skipped}")

        except Exception as e:
            logger.exception(f"Failed to process {account['source']}")
            error_count += 1
            error_message = str(e)
        finally:
            if mail:
                try: mail.logout()
                except Exception: pass

            try:
                save_sync_log(
                    job_name="sync_sent_gmail",
                    account=account["source"],
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    imported_count=imported,
                    skipped_count=skipped,
                    error_count=error_count,
                    error_message=error_message,
                )
            except Exception as e:
                logger.error(f"Failed to save sync_log for {account['source']}: {e}")

if __name__ == "__main__":
    main()