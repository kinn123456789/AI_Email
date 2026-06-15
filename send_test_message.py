import requests
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TEACHER_PORTAL_TOKEN")

BASE_URL = "https://api.coralacademy.com"

chat_id = "43189768-0124-453e-ac80-457c807b2d03"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Ca-Id": "e04e5250-0abf-4429-aa07-1b66d03269af",
    "Ca-Teacher-Id": "e3caeaa9-e754-4462-ac33-09b8fd4b23d6",
    "Content-Type": "application/json"
}

payload = {
    "text": "AI_TEST_001"
}

response = requests.post(
    f"{BASE_URL}/chats/{chat_id}/messages",
    headers=headers,
    json=payload
)

print("STATUS:", response.status_code)
print(response.text)