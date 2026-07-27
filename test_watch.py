import os
from dotenv import load_dotenv
from gmail_watch import register_watch

load_dotenv()

register_watch(os.getenv("EMAIL_1"))
