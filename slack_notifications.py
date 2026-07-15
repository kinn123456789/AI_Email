import os
import requests
from dotenv import load_dotenv

load_dotenv()


def send_slack_notification(title, sender, subject, priority, category, link=None):

    if os.getenv("ENABLE_SLACK_NOTIFICATIONS", "false").lower() != "true":
        return

    webhook = os.getenv("SLACK_WEBHOOK_URL")

    if not webhook:
        return

    message = {
        "text":
            f"📩 *{title}*\n\n"
            f"*Sender:* {sender}\n"
            f"*Subject:* {subject}\n"
            f"*Priority:* {priority}\n"
            f"*Category:* {category}"
            + (f"\n<{link}|Open in Dashboard>" if link else "")
    }

    try:
        requests.post(webhook, json=message, timeout=10)
    except Exception as e:
        print("Slack notification failed:", e)