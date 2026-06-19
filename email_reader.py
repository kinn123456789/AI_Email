import imaplib
import email
import os
import base64
import time

from database import log_event
from dotenv import load_dotenv
from email.header import decode_header
from bs4 import BeautifulSoup
from ai_classifier import ai_triage
from email_sender import send_email
from email.utils import parseaddr
from database import update_status
from database import get_thread
from database import get_root_thread_id
from database import db_pool

from database import (
    save_email,
    email_exists,
    save_attachment,
    attachment_exists
)


# Configuration
load_dotenv()
EMAIL_ACCOUNTS = [
    {"email": os.getenv("EMAIL_1"), "password": os.getenv("APP_PASSWORD_1"), "source": "Inbox 1"},
    {"email": os.getenv("EMAIL_2"), "password": os.getenv("APP_PASSWORD_2"), "source": "Inbox 2"},
    {"email": os.getenv("EMAIL_3"), "password": os.getenv("APP_PASSWORD_3"), "source": "Inbox 3"}
]
ATTACHMENT_DIR = "attachments"


if not os.path.exists(ATTACHMENT_DIR):
    os.makedirs(ATTACHMENT_DIR)

for account in EMAIL_ACCOUNTS:
    # Skip if environment variables are not set
    if not account["email"] or not account["password"]:
        continue

    print(f"\n--- Checking {account['source']} ---")

    # Connect and Login
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(account["email"], account["password"])
        mail.select("inbox")
    except Exception as e:
        print(f"Failed to connect to {account['source']}: {e}")
        continue

    # Fetch Emails
    status, messages = mail.search(None, "UNSEEN")
    

    
    mail_ids = messages[0].split()
    
    for email_id in mail_ids:
        _, msg_data = mail.fetch(email_id, "(RFC822)")

        for response_part in msg_data:
            if not isinstance(response_part, tuple):
                continue

            msg = email.message_from_bytes(response_part[1])
            sender_email = parseaddr(msg.get("From", ""))[1]
            in_reply_to = msg.get("In-Reply-To") ##email it responded to

            ##if sender_email and sender_email.lower() == account["email"].lower():
              ##  print("Skipping own email") # Prevent replying to emails sent from the same inbox
               ## continue
            message_id = msg.get("Message-ID")
            if not message_id:
                print("No Message-ID. Skipping...")
                continue

            if email_exists(message_id):
                print("Already exists. Skipping...")
                continue

            

            # If it's not a reply, it's a new email, so always process it

            # Subject Parsing
            subject_raw, encoding = decode_header(msg.get("Subject", "No Subject"))[0]
            subject = subject_raw.decode(encoding or "utf-8", errors="ignore") if isinstance(subject_raw, bytes) else subject_raw
            
            # Prevent reply loops
            ##if subject.lower().startswith("re:"):
                ##print(f"Skipping reply email: {subject}")
                ##continue
            ##print(f"Processing: {subject}")
            email_received_time = msg.get("Date")

            log_event(
                    message_id,
                    "EMAIL_RECEIVED",
                    f"Received at: {email_received_time}"
            )
            body = ""
            html_body = ""
            image_data_list = []
            safe_message_id = message_id.replace("<", "").replace(">", "").replace("/", "_")

            for part in msg.walk():
                content_type = part.get_content_type()
                filename = part.get_filename()

                # Handle Attachments
                if filename:
                    filename = os.path.basename(filename).replace(" ", "_")
                    if attachment_exists(message_id, filename):
                        continue

                    allowed_types = ["image/jpeg", "image/png", "application/pdf"]
                    if content_type not in allowed_types:
                        continue

                    file_data = part.get_payload(decode=True)
                    filepath = os.path.join(ATTACHMENT_DIR, f"{safe_message_id}_{filename}")

                    with open(filepath, "wb") as f:
                        f.write(file_data)

                    if "image" in content_type:
                        image_b64 = base64.b64encode(file_data).decode("utf-8")
                        image_data_list.append({"filename": filename, "data": image_b64})

                    save_attachment(message_id, filename, content_type, filepath)
                    print(f"Saved attachment: {filename}")

                # Handle Body
                else:
                    if content_type == "text/plain":
                        body += part.get_payload(decode=True).decode(errors="ignore")
                    elif content_type == "text/html":
                        html_body += part.get_payload(decode=True).decode(errors="ignore")

            # Fallback to HTML
            if not body.strip() and html_body:
                soup = BeautifulSoup(html_body, "html.parser")
                body = soup.get_text(separator=" ", strip=True)

            in_reply_to = msg.get("In-Reply-To")

            if in_reply_to:
                root_thread = get_root_thread_id(in_reply_to)

                thread_id = root_thread or in_reply_to

            else:
                thread_id = message_id
            # AI Triage
            try:
                start_time = time.time()
                history = get_thread(thread_id)

                print("\nTHREAD HISTORY")
                print(history)
                print("END THREAD HISTORY\n")

                if history:
                     print(f"Found {len(history)} previous messages in thread")

                result = ai_triage(
                    subject,
                    body,
                    history=history,
                    images=image_data_list
                )
                processing_time = round(
                    time.time() - start_time,
                    2
                )
                log_event(
                    message_id,
                    "AI_CLASSIFIED",
                    f"Category={result['category']}, Priority={result['priority']}, Processing={processing_time}s"
                )
            except Exception as e:
                print(f"AI Triage failed: {e}")
                log_event(
                        message_id,
                        "AI_ERROR",
                        str(e)
                )
                result = {"category": "Unclassified", "priority": "Low", "summary": "Error", "draft_reply": ""}
           
            
            # Save to Database
            try:
                    db_email_id = save_email(
                        msg["From"],
                        subject,
                        body,
                        result["category"],
                        result["priority"],
                        result["summary"],
                        result["draft_reply"],
                        message_id,
                        thread_id,
                        in_reply_to,
                        source=account["source"]
                    )

                    mail.store(email_id, '+FLAGS', '\\Seen')
                    print("Marked email as Seen")
            except Exception as e:
                print(e)
                continue
            

           ## sender_email = parseaddr(msg["From"])[1]

           ## print(f"Email saved: {subject}")
            requires_review = (
                result["priority"] in ["High", "Urgent"]
            )
            if requires_review:

                update_status(db_email_id, "Needs Review")

            else:

                success = send_email(
                    account["email"],
                    account["password"],
                    sender_email,
                    f"Re: {subject}",
                    result["draft_reply"]
                )

                if success:
                    print("Reply sent successfully")

                    log_event(
                        message_id,
                        "REPLY_SENT",
                        f"Reply sent to {sender_email}"
                    )
                    if db_email_id:
                        update_status(db_email_id, "Resolved")

                        log_event(
                            message_id,
                            "STATUS_UPDATED",
                            "Status changed to Resolved"
                        )

                else:
                    log_event(
                        message_id,
                        "REPLY_FAILED",
                        f"Failed sending to {sender_email}"
                    )

    

         
    # Logout to free up connection
    mail.logout()
db_pool.closeall()