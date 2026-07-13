import imaplib
import email
print("PROGRAM STARTED")

from dotenv import load_dotenv
import os
from database import save_email, email_exists
from email.header import decode_header
from bs4 import BeautifulSoup

from classifier import classify_email



load_dotenv()

EMAIL = os.getenv("EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")

mail = imaplib.IMAP4_SSL("imap.gmail.com")

mail.login(EMAIL, APP_PASSWORD)

mail.select("inbox")

status, messages = mail.search(None, "ALL")

#from dotenv import load_dotenv
#import os

#load_dotenv()

#TOKEN = os.getenv("TEACHER_PORTAL_TOKEN")

#headers = {
 #   "Authorization": f"Bearer {TOKEN}"
#}

print("STATUS:", status)
print("RAW MESSAGES:", messages)


mail_ids = messages[0].split()

print(mail_ids)

for email_id in mail_ids:

    status, msg_data = mail.fetch(email_id, "(RFC822)")

    for response_part in msg_data:

        if isinstance(response_part, tuple):

            msg = email.message_from_bytes(response_part[1])

            print("\n-------------------")
            print("FROM:", msg["From"])
            
            subject, encoding = decode_header(msg["Subject"])[0]

            if isinstance(subject, bytes):
                subject = subject.decode(encoding or "utf-8", errors="ignore")

            print("SUBJECT:", subject)
            print("MESSAGE ID:", msg["Message-ID"])
            message_id = msg["Message-ID"]
            
            body = ""

            if msg.is_multipart():

                for part in msg.walk():

                    if part.get_content_type() == "text/plain":

                        body = part.get_payload(decode=True).decode(errors="ignore")

                        print("BODY:")
                        print(body)

                        break

            else:

                body = msg.get_payload(decode=True).decode(errors="ignore")

                print("BODY:")
                print(body)

            if "<html" in body.lower():

                    soup = BeautifulSoup(body, "html.parser")

                    body = soup.get_text(separator=" ", strip=True)

            category = classify_email(subject, body)

            print("CATEGORY:", category)

            if not email_exists(message_id):

                save_email(
                    msg["From"],
                    subject,
                    body,
                    category,
                    message_id,
                    source="email"
                )

                print("Saved to database!")

            else:

                print("Already exists. Skipping...")