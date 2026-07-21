import os
import requests
from dotenv import load_dotenv

load_dotenv()
loaded = load_dotenv()
print("Loaded .env:", loaded)
print("Current directory:", os.getcwd())
print("API_KEY:", os.getenv("TEACHER_PORTAL_API_KEY"))
# Read API Key from .env
API_KEY = os.getenv("TEACHER_PORTAL_TOKEN")

BASE_URL = "https://api.preprod.coralacademy.com/ai_email"


def get_headers(teacher_id=None):
    print("API_KEY:", API_KEY)
    print("Headers:", get_headers())
    if not API_KEY:
        raise ValueError(
            "TEACHER_PORTAL_API_KEY is not configured. Set it in your environment or .env file."
        )

    return {
        "x-api-key": API_KEY,
    }
# ----------------------------------------------------
# Teachers

def get_teachers():

    response = requests.get(
        f"{BASE_URL}/ai-email/teachers",
        headers=get_headers(),
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    return data["response"]["teachers"]


# ----------------------------------------------------
# Chats
# ----------------------------------------------------

def get_chats(teacher_id):

    response = requests.get(
        f"{BASE_URL}/ai-email/chats?teacher_id={teacher_id}",
        headers=get_headers(),
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    return data["response"]["chats"]


# ----------------------------------------------------
# Messages
# ----------------------------------------------------

def get_messages(chat_id, teacher_id):

    response = requests.get(
        f"{BASE_URL}/ai-email/chats/{chat_id}/messages?teacher_id={teacher_id}&page=0",
        headers=get_headers(),
        timeout=30
    )

    response.raise_for_status()

    return response.json()


# ----------------------------------------------------
# Health Check
# ----------------------------------------------------

def test_connection():

    try:

        teachers = get_teachers()

        print("=" * 60)
        print("Teacher Portal Connected")
        print("Teachers:", len(teachers))
        print("=" * 60)

        return True

    except Exception as e:

        print("=" * 60)
        print("Teacher Portal Connection Failed")
        print(e)
        print("=" * 60)

        return False


if __name__ == "__main__":

    if not test_connection():
        exit()

    teachers = get_teachers()

    for teacher in teachers:

        print(f"\nTeacher: {teacher['name']}")

        chats = get_chats(teacher["id"])

        print(f"Chats: {len(chats)}")