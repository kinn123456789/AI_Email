# teacher_portal_sender.py

import requests
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TEACHER_PORTAL_TOKEN")
BASE_URL = "https://api.coralacademy.com"

def send_teacher_reply(
    chat_id,
    teacher_id,
    message
):

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Ca-Id": "e04e5250-0abf-4429-aa07-1b66d03269af",
        "Ca-Teacher-Id": teacher_id,
        "Content-Type": "application/json"
    }

    payload = {
        "text": message
    }

    response = requests.post(
        f"{BASE_URL}/chats/{chat_id}/messages",
        headers=headers,
        json=payload
    )

    return response.status_code in [200, 201]