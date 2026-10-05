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
REQUEST_TIMEOUT = get_timeout(20)


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

    if not API_KEY:
        return {
            "success": False,
            "status_code": None,
            "data": "TEACHER_PORTAL_API_KEY is not configured"
        }

    headers = build_headers(API_KEY, extra={"Content-Type": "application/json"})

    payload = {
        "teacher_id": teacher_id,
        "chat_id": chat_id,
        "text": message
    }

    url = f"{BASE_URL}/ai-email/reply"

    print("\n" + "=" * 60)
    print("SENDING TEACHER REPLY")
    print("=" * 60)
    print("Chat ID    :", chat_id)
    print("Teacher ID :", teacher_id)
    print("URL        :", url)
    print("Payload    :", payload)
    print("=" * 60)

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT
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


def delete_teacher_message(chat_id, message_id, teacher_id):
    """
    Deletes a Teacher Portal message.
    """

    if not API_KEY:
        raise ValueError("TEACHER_PORTAL_API_KEY is not configured")

    headers = build_headers(API_KEY)
    # Previously-trialled extra headers, left disabled - not required by the
    # current /ai-email/* wrapper's auth:
    # headers["Ca-Id"] = "a88e2aaa-a02b-40b8-9385-f26827f3820d"
    # headers["Ca-Teacher-Id"] = teacher_id
    # headers["Origin"] = "https://teacher.preprod.coralacademy.com"
    # headers["Website-Base-Url"] = "https://teacher.preprod.coralacademy.com"

    response = requests.delete(
        f"{BASE_URL}/ai-email/chats/{chat_id}/messages/{message_id}?teacher_id={teacher_id}",
        headers=headers,
        timeout=REQUEST_TIMEOUT
    )

    print("DELETE STATUS:", response.status_code)
    print(response.text)

    response.raise_for_status()

    if response.text:
        return response.json()

    return {}


if __name__ == "__main__":
    result = send_teacher_reply(
        chat_id="0e3583ec-47ce-4fca-866c-f423bbdc3ae1",
        teacher_id="d92f780c-dfb5-4e60-8104-7eb976eb4583",
        message="Hello from API"
    )

    print(result)
