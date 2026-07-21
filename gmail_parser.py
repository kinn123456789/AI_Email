#gmail_parser.py
import base64


def get_header(headers, name):

    for header in headers:
        if header["name"].lower() == name.lower():
            return header["value"]

    return ""


def decode_body(data):

    if not data:
        return ""

    data += "=" * (-len(data) % 4)

    return base64.urlsafe_b64decode(
        data.encode("utf-8")
    ).decode(
        "utf-8",
        errors="ignore"
    )


def extract_body(payload):

    # Plain text
    if payload.get("mimeType") == "text/plain":
        return decode_body(
            payload["body"].get("data")
        )

    # HTML
    if payload.get("mimeType") == "text/html":
        return decode_body(
            payload["body"].get("data")
        )

    # Multipart
    for part in payload.get("parts", []):

        body = extract_body(part)

        if body:
            return body

    return ""


def parse_email(message):

    payload = message["payload"]

    headers = payload.get("headers", [])

    body = extract_body(payload)

    return {

        "gmail_id": message["id"],

        "thread_id": message["threadId"],

        "message_id": get_header(
            headers,
            "Message-ID"
        ),

        "subject": get_header(
            headers,
            "Subject"
        ),

        "from": get_header(
            headers,
            "From"
        ),

        "to": get_header(
            headers,
            "To"
        ),

        "cc": get_header(
            headers,
            "Cc"
        ),

        "date": get_header(
            headers,
            "Date"
        ),

        "in_reply_to": get_header(
            headers,
            "In-Reply-To"
        ),

        "references": get_header(
            headers,
            "References"
        ),

        "body": body,

        "snippet": message.get("snippet", "")
    }