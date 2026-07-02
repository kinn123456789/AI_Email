import os
import email
import base64
import time
import imaplib
from email.utils import parseaddr
from email.header import decode_header
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from email_sender import send_email

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
    attachment_exists, reopen_thread, get_historical_emails
)

# Configuration
load_dotenv()
ATTACHMENT_DIR = "attachments"
if not os.path.exists(ATTACHMENT_DIR):
    os.makedirs(ATTACHMENT_DIR)

EMAIL_ACCOUNTS = [
    #{"email": os.getenv("EMAIL_1"), "token": "token_support.json", "source": "support@coralacademy.com"},
    {"email": os.getenv("EMAIL_2"), "token": "token_lucy.json", "source": "lucy@coralacademy.com"},
    #{"email": os.getenv("EMAIL_3"), "token": "token_engineering.json", "source": "engineering@coralacademy.com"}
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
            # Single connection per account
            mail = oauth_login(account["email"], account["token"])
            mail.select("INBOX")
            
            status, messages = mail.search(None, "UNSEEN")
            if status != "OK":
                continue

            mail_ids = messages[0].split()[-1:]
            print(f"Unread emails: {len(mail_ids)}")

            for email_id in mail_ids:
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                
                msg = email.message_from_bytes(msg_data[0][1])
                sender_email = parseaddr(msg.get("From", ""))[1]
                message_id = msg.get("Message-ID")
                
                if not message_id or email_exists(message_id):
                    continue

                # Subject Parsing
                subject_raw, encoding = decode_header(msg.get("Subject", "No Subject"))[0]
                subject = subject_raw.decode(encoding or "utf-8", errors="ignore") if isinstance(subject_raw, bytes) else subject_raw

                print(f"Processing {subject} from {sender_email}")
                log_event(message_id, "EMAIL_RECEIVED", f"Received at: {msg.get('Date')}")
                
                # Body & Attachment Processing
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
                
                # Threading Logic
                in_reply_to = msg.get("In-Reply-To")
                root_thread = get_root_thread_id(in_reply_to) if in_reply_to else None
                thread_id = root_thread or in_reply_to or message_id
                if root_thread:
                    reopen_thread(root_thread)

                # Automated Email Filter
                skip, category, reason = is_automated_email(msg)
                if skip:
                    save_email(sender=sender_email, subject=subject, body=body, category=category,
                               priority="Low", ai_summary=reason, ai_draft_reply="",
                               message_id=message_id, thread_id=thread_id, in_reply_to=in_reply_to,
                               source=account["source"], status="No Reply Required", ai_confidence=None)
                    log_event(message_id, "FILTERED", reason)
                    mail.store(email_id, '+FLAGS', '\\Seen')
                    continue

                draft_reply = ""
                knowledge_url = None
                
                # AI Triage
                try:
                    start_time = time.time()
                    history = get_thread(thread_id) if in_reply_to else []
                    history_text = ""

                    for message in history:
                        history_sender = message[0]
                        history_body = message[2] or ""
                        history_text += f"\n{history_sender}:\n{history_body}\n{'-'*40}\n"
                        
                    clean_body = clean_email_body(body)
                    result = ai_triage(subject, clean_body, history=history_text, images=image_data_list)
                    print("AI Triage:", result)
                    print("Reached Step 1")
                    
                    # Vector Search
                    print("Starting historical search...")
                    similar_results = search_similar_emails(subject=subject, body=clean_body)
                    print("Historical search complete")
                    
                    # Rerank
                    print("Starting rerank...")
                    reranked = rerank_emails(subject, clean_body, similar_results)
                    print("Rerank complete")
                    
                    # Get selected IDs
                    selected_ids = [item["id"] for item in reranked.get("selected", [])]

                    print("Fetching historical emails...")
                    similar_emails = get_historical_emails(selected_ids)
                    print("Historical emails fetched")

                    print("Searching knowledge base...")
                    knowledge = search_knowledge_base(subject, clean_body, limit=3)

                    if knowledge:
                        knowledge_url = knowledge[0]["url"]
                        status = "Resolved"
                        requires_review = False

                        print("Knowledge Retrieved:")
                        for item in knowledge:
                            print(f"- {item['title']} ({item['url']})")
                    else:
                        knowledge_url = None
                        status = "Needs Review"
                        requires_review = True

                    print("-" * 40)

                    print("Generating reply...")
                    draft_reply = generate_reply(
                        subject=subject,
                        body=clean_body,
                        category=result["category"],
                        priority=result["priority"],
                        thread_history=history_text,
                        similar_emails=similar_emails,
                        knowledge=knowledge
                    )
                    log_event(message_id, "AI_CLASSIFIED", f"Category={result['category']}, Processing={round(time.time()-start_time,2)}s")
                
                except Exception as e:
                    print("AI ERROR:", repr(e))
                    import traceback
                    traceback.printexc()
                    log_event(message_id, "AI_ERROR", str(e))
                    result = {"category": "Unclassified", "priority": "Low", "summary": "Error", "draft_reply": "", "confidence": None}
                    draft_reply = ""
                
                print("Reply generated")
                if draft_reply:
                    print("\n========== GENERATED REPLY ==========")
                    print(draft_reply)
                    print("=====================================\n")
                else:
                    print("\n========== NO REPLY GENERATED ==========\n")
                
                # Database Save & Outbound Delivery Execution
                try:
                    db_email_id = save_email(
                        sender_email,
                        subject,
                        body,
                        result["category"],
                        result["priority"],
                        result["summary"],
                        draft_reply,
                        message_id,
                        thread_id,
                        in_reply_to,
                        account["source"],
                        status=status,
                        requires_review=requires_review,
                        ai_confidence=result.get("confidence"),
                        knowledge_url=knowledge_url
                    )
                    
                    # Enhanced Dispatch Block with Threading & Safety Checks
                    if draft_reply and status == "Resolved":
                        print(f"Routing live outbound email via OAuth...")
                        
                        # Apply your custom "Re:" cleaning strategy
                        clean_subject = subject.strip()

                        if not in_reply_to:
                            # First reply: remove any leading "Re:"
                            while clean_subject.lower().startswith("re:"):
                                clean_subject = clean_subject[3:].strip()
                        else:
                            # Existing thread: ensure exactly one "Re:"
                            while clean_subject.lower().startswith("re:"):
                                clean_subject = clean_subject[3:].strip()

                            clean_subject = f"Re: {clean_subject}"
                        
                        sent_msg_id = send_email(
                            from_email=account["source"],
                            token_file=account["token"],
                            to_email=sender_email,
                            subject=clean_subject,        # Outbound delivery with fixed clean_subject
                            body=draft_reply,
                            thread_id=thread_id,          
                            original_msg_id=message_id    
                        )
                        
                        if sent_msg_id:
                            update_status(db_email_id, "Replied")
                            log_event(message_id, "EMAIL_SENT", f"Outbound response dispatched: {sent_msg_id}")
                        else:
                            log_event(message_id, "DELIVERY_FAILURE", "Gmail API failed to route message.")

                    mail.store(email_id, '+FLAGS', '\\Seen')
                except Exception as e:
                    log_event(message_id, "DATABASE_ERROR", str(e))
                    continue

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

