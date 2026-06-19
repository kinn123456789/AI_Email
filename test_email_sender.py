##from email_sender import send_email

##send_email(
  ##  "Shopsat19@gmail.com",
   ## "SMTP Test",
   ## "Hello from Python"
##)
from email_sender import send_email
from dotenv import load_dotenv
import os

load_dotenv()

send_email(
    os.getenv("EMAIL_2"),
    os.getenv("APP_PASSWORD_2"),
    "shopsat19@gmail.com",
    "Test from Inbox 2",
    "Hello from Inbox 2"
)
