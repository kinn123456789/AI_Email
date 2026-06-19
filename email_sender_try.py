import smtplib
import os

from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

EMAIL = os.getenv("EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")


def send_email(to_email, subject, body):

    msg = MIMEText(body)

    msg["From"] = EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject

    server = smtplib.SMTP(
        "smtp.gmail.com",
        587
    )

    server.starttls()

    server.login(
        EMAIL,
        APP_PASSWORD
    )

    server.send_message(msg)

    server.quit()

    print("Email sent!")