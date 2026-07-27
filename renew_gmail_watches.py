import os
from dotenv import load_dotenv
from gmail_watch import register_watch

load_dotenv()

EMAILS = [
    os.getenv("EMAIL_1"),
    os.getenv("EMAIL_2"),
    os.getenv("EMAIL_3"),
]

for email in EMAILS:
    try:
        register_watch(email)
    except Exception as e:
        print(f"Failed: {email}")
        print(e)
