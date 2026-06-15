import requests
import os
from dotenv import load_dotenv

print("Current Directory:", os.getcwd())

load_dotenv(dotenv_path=".env")

TOKEN = os.getenv("TEACHER_PORTAL_TOKEN")

print("TOKEN EXISTS:", TOKEN is not None)
print("TOKEN LENGTH:", len(TOKEN) if TOKEN else 0)

BASE_URL = "https://api.coralacademy.com"


def get_chats(teacher_id):

    headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Ca-Id": "e04e5250-0abf-4429-aa07-1b66d03269af",
    "Ca-Teacher-Id": teacher_id,
    "Origin": "https://www.teacher.coralacademy.com",
    "Website-Base-Url": "https://www.teacher.coralacademy.com"
}

    response = requests.get(
        f"{BASE_URL}/chats?user_role=teacher",
        headers=headers
    )

    print("\nSTATUS CODE:", response.status_code)

    data = response.json()

    #print("\nFULL RESPONSE:")
    #print(data)

    chats = data["response"]["chats"]

    print("\nNUMBER OF CHATS:", len(chats))

    for chat in chats:
        print(chat)

    return chats


def get_messages(chat_id, teacher_id):

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Ca-Id": "e04e5250-0abf-4429-aa07-1b66d03269af",
        "Ca-Teacher-Id": teacher_id,
        "Origin": "https://www.teacher.coralacademy.com",
        "Website-Base-Url": "https://www.teacher.coralacademy.com"
    }

    response = requests.get(
        f"{BASE_URL}/chats/{chat_id}/messages?page=0",
        headers=headers
    )

    print("\nMESSAGES STATUS CODE:", response.status_code)

    try:
        data = response.json()

        print("\nMESSAGES RESPONSE:")
        print(data)

        return data

    except Exception as e:
        print("Error:", e)
        print(response.text)

        return None
    
def get_teachers():

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Ca-Id": "e04e5250-0abf-4429-aa07-1b66d03269af",
        "Origin": "https://www.teacher.coralacademy.com",
        "Website-Base-Url": "https://www.teacher.coralacademy.com"
    }

    response = requests.get(
        f"{BASE_URL}/teachers",
        headers=headers
    )

    print("STATUS:", response.status_code)

    data = response.json()

    return data["response"]["teachers"]


if __name__ == "__main__":

    teachers = get_teachers()

    for teacher in teachers:

        print("\n====================")
        print("Teacher:", teacher["name"])

        chats = get_chats(teacher["id"])

        print("Chats found:", len(chats))

        if chats:
            participants = chats[0]["participants"]

            for p in participants:
                if p["user_role"] == "teacher":
                    print(
                        "Teacher in first chat:",
                        p["user"]["name"]
                    )