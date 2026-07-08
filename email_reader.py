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

        print(f"\n--- Checking {account['source']} ---")
        mail = None
        
        try:
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
                print("\n" + "="*80)
                print("NEW EMAIL RECEIVED")
                print("="*80)

                for key, value in msg.items():
                    print(f"{key}: {value}")

                print("="*80)
                sender_email = parseaddr(msg.get("From", ""))[1]

                print("Message-ID :", msg.get("Message-ID"))
                print("In-Reply-To:", msg.get("In-Reply-To"))
                print("References :", msg.get("References"))
                
                message_id = msg.get("Message-ID")
                
                if not message_id or email_exists(message_id):
                    continue

                subject_raw, encoding = decode_header(msg.get("Subject", "No Subject"))[0]
                subject = subject_raw.decode(encoding or "utf-8", errors="ignore") if isinstance(subject_raw, bytes) else subject_raw

                print(f"Processing {subject} from {sender_email}")
                log_event(message_id, "EMAIL_RECEIVED", f"Received at: {msg.get('Date')}")
                
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
                
                

                in_reply_to = msg.get("In-Reply-To")
                
                if in_reply_to:
                    parent = get_message_by_message_id(in_reply_to)

                    # Fallback: search through References
                    if not parent:
                        references = msg.get("References")
                        if references:
                            print("RAW REFERENCES:", repr(references))
                            for ref in references.split():
                                print("Trying:", repr(ref))
                                parent = get_message_by_message_id(ref)
                                print("Lookup:", parent)
                                if parent:
                                    print("Found parent via References:", ref)
                                    break

                    print("Searching for:", in_reply_to)
                    print("Parent found :", parent)
                    
                    if parent:
                        thread_id = parent["thread_id"]
                        reopen_thread(thread_id)
                    else:
                        thread_id = message_id
                else:
                    thread_id = message_id

                print("Saving with thread_id:", thread_id)
                print("="*80)
                
                # ... (rest of your logic starts here at the same indentation level)

                skip, category, reason, mailbox = is_automated_email(msg)
                if skip:
                    save_email(sender=sender_email, subject=subject, body=body, category=category,
                               priority="Low", ai_summary=reason, ai_draft_reply="",
                               message_id=message_id, thread_id=thread_id, in_reply_to=in_reply_to,
                               source=account["source"], status="No Reply Required", ai_confidence=None,reply_type="none",
                               mailbox=mailbox)
                                
                    log_event(message_id, "FILTERED", reason)
                    mail.store(email_id, '+FLAGS', '\\Seen')
                    continue

                draft_reply, knowledge_url = "", None
                
                try:
                    start_time = time.time()
                    history = get_thread(thread_id) if in_reply_to else []
                    history_text = "\n".join([
                            f"{m['sender']}:\n{m['body'] or ''}\n{'-'*40}"
                            for m in history
                    ])
                        
                    clean_body = clean_email_body(body)
                    result = ai_triage(subject, clean_body, history=history_text, images=image_data_list)
                    
                    similar_results = search_similar_emails(subject=subject, body=clean_body)
                    reranked = rerank_emails(subject, clean_body, similar_results)
                    selected_ids = [item["id"] for item in reranked.get("selected", [])]
                    similar_emails = get_historical_emails(selected_ids)

                    if result["requires_review"]:
                        knowledge = []
                        knowledge_url = None
                    else:
                        knowledge = search_knowledge_base(subject, clean_body, limit=3)
                        knowledge_url = knowledge[0]["url"] if knowledge else None


                    # TEMPORARY - remove after testing
                    # ===============================
                    # TEMPORARY TEST MODE
                    # Route ALL emails to Human Review

                    # ===============================
                    result["requires_review"] = True
                    result["needs_reply"] = True

                    # AI classifier has the final say
                    requires_review = result["requires_review"]

                    

                    if requires_review:
                        status = "Needs Review"
                    else:
                        if result["needs_reply"]:
                            status = "Auto Replied"
                        else:
                            status = "No Reply Required"
                    
                    if requires_review:
                            reply_type = "human"
                    elif result["needs_reply"]:
                            reply_type = "automatic"
                    else:
                            reply_type = "none"
               

                    draft_reply = generate_reply(
                        subject=subject, body=clean_body, category=result["category"],
                        priority=result["priority"], thread_history=history_text,
                        similar_emails=similar_emails, knowledge=knowledge
                    )
                    log_event(message_id, "AI_CLASSIFIED", f"Category={result['category']}, Processing={round(time.time()-start_time,2)}s")
                
                except Exception as e:
                    print("AI ERROR:", repr(e))
                    traceback.print_exc()
                    log_event(message_id, "AI_ERROR", str(e))
                    result = {"category": "Unclassified", "priority": "Low", "summary": "Error", "confidence": None}
                    draft_reply = ""
                    status = "Awaiting Review"
                    requires_review = True
                    reply_type = "human" 
                
                try:
                    db_email_id = save_email(
                        sender_email, subject, body, result["category"], result["priority"],
                        result["summary"], draft_reply, message_id, thread_id, in_reply_to,
                        account["source"], status=status, requires_review=requires_review,
                        ai_confidence=result.get("confidence"), knowledge_url=knowledge_url,
                        reply_type=reply_type,mailbox=mailbox
                    )
                    
                    if (
                        draft_reply
                        and result["needs_reply"]
                        and not result["requires_review"]
                    ):
                        clean_subject = subject.strip()
                        while clean_subject.lower().startswith("re:"):
                            clean_subject = clean_subject[3:].strip()
                        if in_reply_to:
                            clean_subject = f"Re: {clean_subject}"
                        
                        sent_msg_id = send_email(
                            from_email=account["source"], token_file=account["token"],
                            to_email=sender_email, subject=clean_subject, body=draft_reply,
                            thread_id=thread_id, original_msg_id=message_id    
                        )
                        
                        if sent_msg_id:
                            update_final_reply(db_email_id, draft_reply)
                            update_reply_type(db_email_id, "automatic")
                            update_status(db_email_id, "Replied")

                            

                            log_event(message_id, "EMAIL_SENT", f"Outbound response dispatched: {sent_msg_id}")
                    
                    mail.store(email_id, '+FLAGS', '\\Seen')
                except Exception as e:
                    log_event(message_id, "DATABASE_ERROR", str(e))

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