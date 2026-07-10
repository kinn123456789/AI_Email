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

# Custom modules
from email_filter import is_automated_email
from ai_classifier import ai_triage
from database import (
    log_event, update_status, get_thread, get_root_thread_id, 
    db_pool, save_email, email_exists, save_attachment, 
    attachment_exists, reopen_thread, get_historical_emails,
    update_final_reply,
    update_reply_type,get_message_by_message_id
)

# Configuration
load_dotenv()
ATTACHMENT_DIR = "attachments"
if not os.path.exists(ATTACHMENT_DIR):
    os.makedirs(ATTACHMENT_DIR)

EMAIL_ACCOUNTS = [
    {"email": os.getenv("EMAIL_4"), "token": "token_sat.json", "source": "shopsat19@gmail.com"},
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

        mail = None
        
        try:
            mail = oauth_login(account["email"], account["token"])
            mail.select("INBOX")
            
            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                continue

            # EXACT ORIGINAL LIMITING LOGIC RESTORED
            mail_ids = messages[0].split()[:1]

            for email_id in mail_ids:
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                
                msg = email.message_from_bytes(msg_data[0][1])
                message_id = " ".join((msg.get("Message-ID") or "").split())

                print("=" * 80)
                print("MESSAGE ID :", message_id)       
                
                if not message_id or email_exists(message_id):
                    continue

                subject_raw, encoding = decode_header(msg.get("Subject", "No Subject"))[0]
                subject = subject_raw.decode(encoding or "utf-8", errors="ignore") if isinstance(subject_raw, bytes) else subject_raw
                sender_email = parseaddr(msg.get("From", ""))[1]
                
                body, html_body, image_data_list = "", "", []
                safe_message_id = message_id.replace("<", "").replace(">", "").replace("/", "_")

                for part in msg.walk():
                    content_type = part.get_content_type()
                    filename = part.get_filename()
                    if filename:
                        filename = os.path.basename(filename).replace(" ", "_")
                        if not attachment_exists(message_id, filename):
                            file_data = part.get_payload(decode=True)
                            filepath = os.path.join(ATTACHMENT_DIR, f"{safe_message_id}_{filename}")
                            with open(filepath, "wb") as f:
                                f.write(file_data)
                            if "image" in content_type:
                                image_data_list.append({"filename": filename, "data": base64.b64encode(file_data).decode("utf-8")})
                            save_attachment(message_id, filename, content_type, filepath)
                    else:
                        if content_type == "text/plain":
                            body += part.get_payload(decode=True).decode(errors="ignore")
                        elif content_type == "text/html":
                            html_body += part.get_payload(decode=True).decode(errors="ignore")

                if not body.strip() and html_body:
                    body = BeautifulSoup(html_body, "html.parser").get_text(separator=" ", strip=True)
                
                in_reply_to = " ".join((msg.get("In-Reply-To") or "").split())

                print("IN-REPLY-TO :", in_reply_to)
                # THREADING FIX: Normalized header passed correctly
                references_header = " ".join((msg.get("References") or "").split())
                print("REFERENCES :", references_header)
                
                if in_reply_to:
                    parent = get_message_by_message_id(in_reply_to)
                    if not parent and references_header:
                        for ref in reversed(references_header.split()):
                            parent = get_message_by_message_id(ref)
                            if parent: break
                    
                    if parent:
                        thread_id = parent["thread_id"]
                        reopen_thread(thread_id)
                    else:
                        thread_id = message_id
                else:
                    thread_id = message_id
                
                skip, category, reason, mailbox = is_automated_email(msg)
                if skip:
                    save_email(sender=sender_email, subject=subject, body=body, category=category,
                               priority="Low", ai_summary=reason, ai_draft_reply="",
                               message_id=message_id, thread_id=thread_id, in_reply_to=in_reply_to,
                               source=account["source"], status="No Reply Required", ai_confidence=None,reply_type="none",
                               mailbox=mailbox, references_header=references_header)
                                
                    log_event(message_id, "FILTERED", reason)
                    mail.store(email_id, '+FLAGS', '\\Seen')
                    continue

                try:
                    history = get_thread(thread_id) if in_reply_to else []
                    history_text = "\n".join([f"{m['sender']}:\n{m['body'] or ''}\n{'-'*40}" for m in history])
                    clean_body = clean_email_body(body)
                    result = ai_triage(subject, clean_body, history=history_text, images=image_data_list)
                    print("=" * 80)
                    print("AI RESULT")
                    print(result)
                    print("=" * 80)
                    requires_review = True
                    status = "Needs Review"
                    reply_type = "human"
                    
                    #requires_review = result["requires_review"]
                    #status = "Needs Review" if requires_review else ("Auto Replied" if result["needs_reply"] else "No Reply Required")
                    #reply_type = "human" if requires_review else ("automatic" if result["needs_reply"] else "none")
                    similar_emails = search_similar_emails(
                            subject,
                            clean_body
                    )
                    draft_reply = generate_reply(subject=subject, body=clean_body, category=result["category"],
                        priority=result["priority"], thread_history=history_text,similar_emails=similar_emails)


                    print("ABOUT TO SAVE EMAIL")
                    print("Thread :", thread_id)
                    print("Mailbox:", mailbox)
                    print("Status :", status)

                    db_email_id = save_email(
                        sender_email, subject, body, result["category"], result["priority"],
                        result["summary"], draft_reply, message_id, thread_id, in_reply_to,
                        account["source"], status=status, requires_review=requires_review,
                        reply_type=reply_type, mailbox=mailbox, references_header=references_header
                    )


                    print("SAVE SUCCESS")
                    print("DB ID:", db_email_id)
                    
                    #if draft_reply and result["needs_reply"] and not requires_review:
                      #  sent_msg_id = send_email(
                         #   from_email=account["source"], token_file=account["token"],
                          #  to_email=sender_email, subject=f"Re: {subject}", body=draft_reply,
                          #  thread_id=thread_id, original_msg_id=message_id, previous_references=references_header    
                       # )

                    
                        #if sent_msg_id:
                          #  update_final_reply(db_email_id, draft_reply)
                          # update_reply_type(db_email_id, "automatic")
                          #  update_status(db_email_id, "Replied")
                    
                    mail.store(email_id, '+FLAGS', '\\Seen')
                except Exception as e:
                    import traceback

                    print()
                    print("=" * 80)
                    print("EXCEPTION OCCURRED")
                    traceback.print_exc()
                    print("ERROR:", e)
                    print("=" * 80)

                    log_event(message_id, "AI_ERROR", str(e))

        finally:
            if mail:
                mail.logout()
    print("Syncing sent mails...")
    sync_sent_mail()
if __name__ == "__main__":
    main()