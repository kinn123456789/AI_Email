import traceback
import base64
from email.message import EmailMessage
from gmail_auth import get_gmail_service

def send_email(from_email, token_file, to_email, subject, body, thread_id=None, original_msg_id=None, previous_references=None, attachments=None):
    """
    Sends an email using the Gmail API, maintaining thread continuity.

    token_file is unused now (kept only so existing callers don't need to
    change) - auth is via domain-wide delegation, impersonating from_email
    directly. See gmail_auth.py.
    """
    service = None
    try:
        service = get_gmail_service(from_email)

        # Create message
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email

        # Threading Headers
       
        if original_msg_id:
            msg["In-Reply-To"] = original_msg_id
            
        # Construct References: combine old references with the parent ID
        if previous_references and original_msg_id:
            msg["References"] = f"{previous_references} {original_msg_id}".strip()
        elif original_msg_id:
            msg["References"] = original_msg_id

        for filename, file_data, content_type in (attachments or []):
            maintype, _, subtype = (content_type or "application/octet-stream").partition("/")
            msg.add_attachment(
                file_data,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=filename
            )

        # Encode and send
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        message = {"raw": raw_message}
        
       

        print("=" * 80)
        print("Sending email...")
        print("FROM:", from_email)
        print("TO:", to_email)
        print("SUBJECT:", subject)
        print("In-Reply-To:", msg.get("In-Reply-To"))
        print("References:", msg.get("References"))
        print("=" * 80)


        message = {
                "raw": raw_message
        }
        sent_msg = service.users().messages().send(
            userId="me",
            body=message
        ).execute()

        print("Gmail Response:", sent_msg)

        return {
            "gmail_id": sent_msg["id"],
            "thread_id": sent_msg.get("threadId"),
            "gmail_api_id": sent_msg["id"]  # Gmail's own internal id — NOT the RFC-2822 Message-ID header. Callers that need the real Message-ID must fetch the sent message back and read its "Message-ID" header themselves (see main.py's reply route).
}

    except Exception as e:
        traceback.print_exc()
        print("SEND ERROR:", e)
        return None
    finally:
        if service:
            service.close()