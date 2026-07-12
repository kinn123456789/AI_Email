import traceback
import base64
from email.message import EmailMessage
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os
def send_email(from_email, token_file, to_email, subject, body, thread_id=None, original_msg_id=None, previous_references=None):
    """
    Sends an email using the Gmail API, maintaining thread continuity.
    """
    try:
        # Load credentials
    
       
        

        token_path = os.path.join("/etc/secrets", token_file)

        # Local fallback
        if not os.path.exists(token_path):
            token_path = token_file

        creds = Credentials.from_authorized_user_file(
            token_path,
            ["https://mail.google.com/"]
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
            with open(token_path, "w") as token:
                token.write(creds.to_json())
                
        service = build("gmail", "v1", credentials=creds)

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
            "message_id": sent_msg["id"]
}

    except Exception as e:
        traceback.print_exc()
        print("SEND ERROR:", e)
        return None