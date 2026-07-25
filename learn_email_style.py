#learn_email_style.py
import os
import email
from email.utils import parseaddr, parsedate_to_datetime
from email.header import decode_header
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime, timedelta
import socket

# Your custom modules
from email_filter import is_automated_email
from database import historical_email_exists, save_historical_email, get_root_thread_id
from email_reader import oauth_login
from historical_email_redaction import redact_pii

load_dotenv()

socket.setdefaulttimeout(60)

IMPORT_WINDOW_DAYS = 90
since_date = (datetime.now() - timedelta(days=IMPORT_WINDOW_DAYS)).strftime("%d-%b-%Y")

EMAIL_ACCOUNTS = [
    {"email": os.getenv("EMAIL_1"), "token": "token_support.json", "source": "support@coralacademy.com"},
    {"email": os.getenv("EMAIL_2"), "token": "token_lucy.json", "source": "lucy@coralacademy.com"},
    {"email": os.getenv("EMAIL_3"), "token": "token_engineering.json", "source": "engineering@coralacademy.com"}
]

for account in EMAIL_ACCOUNTS:
    if not account["email"] or not account["token"]:
        continue

    print(f"\n===== {account['source']} =====")
    mail = None  # Initialize mail as None to handle in finally block

    try:
        mail = oauth_login(account["email"], account["token"])

        # Sent Mail, not INBOX — this table is used to teach the AI Coral
        # Academy's own writing style. Pulling from INBOX would store
        # customer-authored emails (with their personal details), which
        # could then get surfaced as "style examples" while drafting a
        # reply to a *different* customer.
        status, _ = mail.select('"[Gmail]/Sent Mail"')

        if status != "OK":
            print(f"Could not open Sent Mail for {account['source']}")
            continue

        status, messages = mail.search(None, f'(SINCE "{since_date}")')
        if status != "OK":
            print("Search failed")
            continue

        mail_ids = messages[0].split()
        print(f"Found {len(mail_ids)} emails")

        for uid in mail_ids:
            try:
                status, data = mail.fetch(uid, "(RFC822)")
            except Exception as e:
                uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
                print(f"[{account['source']}] Fetch failed for UID {uid_str}: {e}")
                continue
            if status != "OK" or not data or not isinstance(data[0], tuple):
                continue

            msg = email.message_from_bytes(data[0][1])
            message_id = msg.get("Message-ID")
            
            if not message_id:
                continue

            # Decode subject
            subject_raw, encoding = decode_header(msg.get("Subject", ""))[0]
            subject = subject_raw.decode(encoding or "utf-8", errors="ignore") if isinstance(subject_raw, bytes) else subject_raw

            # Body & Attachment Processing
            body = ""
            html_body = ""
            attachment_count = 0

            for part in msg.walk():
                if part.get_filename():
                    attachment_count += 1
                    continue
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload: body += payload.decode(errors="ignore")
                elif part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload: html_body += payload.decode(errors="ignore")

            if not body.strip() and html_body:
                body = BeautifulSoup(html_body, "html.parser").get_text(separator=" ", strip=True)

            # Filter Check
            skip, category, reason, mailbox = is_automated_email(msg)
            if skip:
                print(f"Skipping automated: {subject[:30]}... ({reason})")
                continue

            # Duplicate check
            if historical_email_exists(message_id):
                print(f"Already imported: {subject[:30]}...")
                continue

            # Threading Logic
            in_reply_to = msg.get("In-Reply-To")
            references = msg.get("References")
            reference_ids = " ".join(references.split()) if references else None
            
            if in_reply_to:
                root_thread_id = get_root_thread_id(in_reply_to) 
                thread_id = root_thread_id or in_reply_to
            else:
                thread_id = message_id

            # Meta data
            sender = parseaddr(msg.get("From", ""))[1]
            recipient = parseaddr(msg.get("To", ""))[1]
            date_header = msg.get("Date")
            try:
                sent_at = parsedate_to_datetime(date_header) if date_header else None
            except Exception:
                sent_at = None

            # Belt-and-suspenders: only ever store emails actually sent BY
            # a Coral Academy staff address, even though we're now reading
            # from Sent Mail — guards against forwarded/odd messages ending
            # up in this folder and leaking customer content as "style".
            staff_addresses = {a["email"] for a in EMAIL_ACCOUNTS if a["email"]}
            if sender not in staff_addresses:
                print(f"Skipping non-staff sender in Sent Mail: {sender}")
                continue

            # Redact known names/emails/phone numbers before this becomes a
            # "style example" the AI sees while drafting replies to other,
            # unrelated families.
            redacted_subject = redact_pii(subject)
            redacted_body = redact_pii(body)

            try:# Save to DB
                email_id = save_historical_email(
                    message_id=message_id,
                    thread_id=thread_id,
                    in_reply_to=in_reply_to,
                    reference_ids=reference_ids,
                    sender=sender,
                    recipient=recipient,
                    subject=redacted_subject,
                    body=redacted_body,
                    sent_at=sent_at,
                    source_account=account["source"],
                    has_attachment=attachment_count > 0,
                    attachment_count=attachment_count
                )
            except Exception as e:
                print(f"Database error for {subject}: {e}")
                continue

            if email_id:
                print(f"Saved: {subject[:50]}")
            else:
                print(f"Failed to save: {subject[:50]}")

    except Exception as e:
        print(f"Error processing account {account['source']}: {e}")
    
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass