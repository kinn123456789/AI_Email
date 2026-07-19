import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TEACHER_PORTAL_TOKEN")

BASE_URL = "https://api.preprod.coralacademy.com"

CA_ID = "a88e2aaa-a02b-40b8-9385-f26827f3820d"

WEBSITE_URL = "https://teacher.preprod.coralacademy.com"


def get_headers(teacher_id=None):
    """
    Common headers used for every Teacher Portal request.
    """

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Ca-Id": CA_ID,
        "Origin": WEBSITE_URL,
        "Website-Base-Url": WEBSITE_URL
    }

    if teacher_id:
        headers["Ca-Teacher-Id"] = teacher_id

    return headers


# ----------------------------------------------------
# Teachers
# ----------------------------------------------------

def get_teachers():

    response = requests.get(
        f"{BASE_URL}/teachers",
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
        f"{BASE_URL}/chats?user_role=teacher",
        headers=get_headers(teacher_id),
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
        f"{BASE_URL}/chats/{chat_id}/messages?page=0",
        headers=get_headers(teacher_id),
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