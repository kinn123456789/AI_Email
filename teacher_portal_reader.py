import requests#Used to call APIs requests.get,requets.post
import os#Used to read environment variables:os.getenv("TEACHER_PORTAL_TOKEN")
from dotenv import load_dotenv

print("Current Directory:", os.getcwd())

load_dotenv(dotenv_path=".env")#Loads values from .env

TOKEN = os.getenv("TEACHER_PORTAL_TOKEN")

print("TOKEN EXISTS:", TOKEN is not None)
print("TOKEN LENGTH:", len(TOKEN) if TOKEN else 0)#Shows length of token example 989

BASE_URL = "https://api.preprod.coralacademy.com"
#BASE_URL
#= Destination
#= Where the request goes

#Origin
#= Identity
#= Who is making the request


def get_chats(teacher_id):

    headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Ca-Id": "a88e2aaa-a02b-40b8-9385-f26827f3820d",
    "Ca-Teacher-Id": teacher_id,
    "Origin": "https://teacher.preprod.coralacademy.com",
    "Website-Base-Url": "https://teacher.preprod.coralacademy.com"
}

    response = requests.get(
        f"{BASE_URL}/chats?user_role=teacher",
        headers=headers
    )
    print("STATUS:", response.status_code)

    print("\nSTATUS CODE:", response.status_code)

    data = response.json()# convverts json to python rescponse

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
        "Origin": "https://teacher.preprod.coralacademy.com",
        "Website-Base-Url": "https://teacher.preprod.coralacademy.com"
    }
    print("TOKEN:", os.getenv("TEACHER_PORTAL_TOKEN")[:20])

    response = requests.get(
        f"{BASE_URL}/chats/{chat_id}/messages?page=0",
        headers=headers
    )

    print("=" * 60)
    print("Status:", response.status_code)
    print("Response:")
    print(response.text)
    print("=" * 60)

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
        "Origin": "https://teacher.preprod.coralacademy.com",
        "Website-Base-Url": "https://teacher.preprod.coralacademy.com"
    }

    response = requests.get(
        f"{BASE_URL}/teachers",
        headers=headers
    )

    print("STATUS:", response.status_code)

    data = response.json()

    if response.status_code != 200:
        print(data)
        return []

    return data["response"]["teachers"]


if __name__ == "__main__": #Run only when file executed directly Not when imported.

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