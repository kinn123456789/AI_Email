# teacher_portal_sender.py

import requests
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TEACHER_PORTAL_TOKEN")
BASE_URL = "https://api.preprod.coralacademy.com"

def send_teacher_reply(
    chat_id,
    teacher_id,
    message
):

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Ca-Id": "a88e2aaa-a02b-40b8-9385-f26827f3820d",
        "Ca-Teacher-Id": teacher_id,
        "Origin": "https://teacher.preprod.coralacademy.com",
        "Website-Base-Url": "https://teacher.preprod.coralacademy.com",
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