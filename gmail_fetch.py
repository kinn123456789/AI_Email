import base64
import email

from gmail_auth import get_gmail_service


def get_message(from_email, message_id):

    service = get_gmail_service(from_email)

    try:
        response = service.users().messages().get(
            userId="me",
            id=message_id,
            format="raw"
        ).execute()

        msg = email.message_from_bytes(
            base64.urlsafe_b64decode(response["raw"])
        )

        return msg
    finally:
        service.close()