import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TEACHER_PORTAL_TOKEN")
BASE_URL = "https://api.preprod.coralacademy.com"


def send_teacher_reply(chat_id, teacher_id, message):
    """
    Sends a reply to a Teacher Portal chat.

    Returns:
        {
            "success": True/False,
            "status_code": int,
            "data": response_json_or_text
        }
    """

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

    print("\n" + "=" * 60)
    print("SENDING TEACHER REPLY")
    print("=" * 60)
    print("Chat ID    :", chat_id)
    print("Teacher ID :", teacher_id)
    print("Message    :", message)
    print("=" * 60)

    try:
        response = requests.post(
            f"{BASE_URL}/chats/{chat_id}/messages",
            headers=headers,
            json=payload,
            timeout=20
        )

        print("Status Code :", response.status_code)

        try:
            response_data = response.json()
        except Exception:
            response_data = response.text

        print("Response :", response_data)

        return {
            "success": response.ok,
            "status_code": response.status_code,
            "data": response_data
        }

    except requests.RequestException as e:
        print("Teacher Portal Error:", e)

        return {
            "success": False,
            "status_code": None,
            "data": str(e)
        }