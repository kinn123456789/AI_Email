import requests

from teacher_portal_config import (
    get_base_url,
    get_api_key,
    get_timeout,
    build_headers,
)

# Read once at import time, same as before - mutate these directly (e.g. in
# tests) to override. BASE_URL now comes from TEACHER_PORTAL_BASE_URL if set,
# defaulting to preprod exactly as before.
API_KEY = get_api_key()
BASE_URL = get_base_url()
REQUEST_TIMEOUT = get_timeout(30)


def get_headers(teacher_id=None):
    return build_headers(API_KEY)


# ----------------------------------------------------
# Teachers
# ----------------------------------------------------

def get_teachers():

    response = requests.get(
        f"{BASE_URL}/ai-email/teachers",
        headers=get_headers(),
        timeout=REQUEST_TIMEOUT
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
        timeout=REQUEST_TIMEOUT
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
        timeout=REQUEST_TIMEOUT
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
