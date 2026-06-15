import imaplib
import email
import os
import base64
from dotenv import load_dotenv
from email.header import decode_header
from bs4 import BeautifulSoup

from database import (
    save_email,
    email_exists,
    save_attachment,
    attachment_exists
)
from ai_classifier_mock import ai_triage

# Configuration
load_dotenv()
EMAIL = os.getenv("EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")
ATTACHMENT_DIR = "attachments"

if not os.path.exists(ATTACHMENT_DIR):
    os.makedirs(ATTACHMENT_DIR)

# Connect
mail = imaplib.IMAP4_SSL("imap.gmail.com")
mail.login(EMAIL, APP_PASSWORD)
mail.select("inbox")

status, messages = mail.search(None, "UNSEEN")
mail_ids = messages[0].split()

for email_id in mail_ids:
    _, msg_data = mail.fetch(email_id, "(RFC822)")
    
    for response_part in msg_data:
        if not isinstance(response_part, tuple):
            continue

        msg = email.message_from_bytes(response_part[1])
        message_id = msg.get("Message-ID")

        if not message_id:
            print("No Message-ID. Skipping...")
            continue

        if email_exists(message_id):
            print("Already exists. Skipping...")
            continue

        # Subject Parsing
        subject_raw, encoding = decode_header(msg.get("Subject", "No Subject"))[0]
        subject = subject_raw.decode(encoding or "utf-8", errors="ignore") if isinstance(subject_raw, bytes) else subject_raw
        
        print(f"\nProcessing: {subject}")

        body = ""
        html_body = ""
        image_data_list = []

        # Sanitize ID for file paths
        safe_message_id = message_id.replace("<", "").replace(">", "").replace("/", "_")

        # Content Parsing (Single Walk)
        for part in msg.walk():
            content_type = part.get_content_type()
            filename = part.get_filename()

            # 1. Handle Attachments
            if filename:
                # Sanitize filename
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
                    image_b64 = base64.b64encode(file_data).decode('utf-8')
                    image_data_list.append({"filename": filename, "data": image_b64})

                save_attachment(message_id, filename, content_type, filepath)
                print(f"Saved attachment: {filename}")

            # 2. Handle Body
            else:
                if content_type == "text/plain":
                    body += part.get_payload(decode=True).decode(errors="ignore")
                elif content_type == "text/html":
                    html_body += part.get_payload(decode=True).decode(errors="ignore")

        # Fallback to HTML if plain body is empty
        if not body.strip() and html_body:
            soup = BeautifulSoup(html_body, "html.parser")
            body = soup.get_text(separator=" ", strip=True)

        # AI Triage
        try:
            result = ai_triage(subject, body, images=image_data_list)
        except Exception as e:
            print(f"AI Triage failed: {e}")
            result = {
                "category": "Unclassified",
                "priority": "Low",
                "summary": "AI processing error",
                "draft_reply": ""
            }

        # Save to Database
        save_email(
            msg["From"],
            subject,
            body,
            result["category"],
            result["priority"],
            result["summary"],
            result["draft_reply"],
            message_id,
            source="email"
        )
        print(f"Email saved: {subject}")