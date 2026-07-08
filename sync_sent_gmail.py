import os
import email


import imaplib

from email.utils import parseaddr
from email.header import decode_header, make_header
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from database import (
    db_pool,
    save_email,
    email_exists,
    get_message_by_message_id,
)

# Configuration
load_dotenv()


EMAIL_ACCOUNTS = [
    {"email": os.getenv("EMAIL_4"), "token": "token_sat.json", "source": "satshop19@gmail.com"},
]

def oauth_login(email_address, token_file):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    
    creds = Credentials.from_authorized_user_file(token_file, ["https://mail.google.com/"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w") as token:
            token.write(creds.to_json())

    auth_string = f"user={email_address}\1auth=Bearer {creds.token}\1\1"
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.authenticate("XOAUTH2", lambda x: auth_string.encode())
    return mail

def main():
    for account in EMAIL_ACCOUNTS:
        if not account.get("email") or not account.get("token"):
            continue

        print(f"\n--- Checking {account['source']} ---")
        mail = None
        
        try:
            mail = oauth_login(account["email"], account["token"])
            

                # =====================================================
            # SYNC SENT MAIL (Human replies sent from Gmail)
            # =====================================================

            mail.select('"[Gmail]/Sent Mail"')

            status, messages = mail.search(None, "ALL")

            if status == "OK":

                sent_ids = messages[0].split()[-20:]

                print(f"Unread sent emails: {len(sent_ids)}")

                for sent_id in sent_ids:

                    status, msg_data = mail.fetch(sent_id, "(RFC822)")

                    if status != "OK":
                        continue

                    msg = email.message_from_bytes(msg_data[0][1])

                    message_id = msg.get("Message-ID")

                    if not message_id or email_exists(message_id):
                        continue

                    subject = str(make_header(decode_header(msg.get("Subject", ""))))

                    body = ""
                    html_body = ""

                    for part in msg.walk():

                        if part.get_filename():
                            continue

                        if part.get_content_type() == "text/plain":

                            payload = part.get_payload(decode=True)

                            if payload:
                                body += payload.decode(errors="ignore")

                        elif part.get_content_type() == "text/html":

                            payload = part.get_payload(decode=True)

                            if payload:
                                html_body += payload.decode(errors="ignore")

                    if not body.strip() and html_body:
                        body = BeautifulSoup(
                            html_body,
                            "html.parser"
                        ).get_text(separator=" ", strip=True)

                    sender_email = parseaddr(msg.get("From", ""))[1]

                    in_reply_to = msg.get("In-Reply-To")

                    thread_id = message_id

                    if in_reply_to:

                        parent = get_message_by_message_id(in_reply_to)

                        if not parent:

                            references = msg.get("References")

                            if references:

                                for ref in references.split():

                                    parent = get_message_by_message_id(ref)

                                    if parent:
                                        break

                        if parent:
                            thread_id = parent["thread_id"]

                    save_email(
                        sender=sender_email,
                        subject=subject,
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
                        reply_type="gmail_manual"
                    )

                    print(f"Imported sent email: {subject}")

                    mail.store(sent_id, '+FLAGS', '\\Seen')

        except Exception as e:
            print(f"Failed to process {account['source']}: {e}")
        finally:
            if mail:
                try:
                    mail.logout()
                except:
                    pass




if __name__ == "__main__":
    main()
    db_pool.closeall()