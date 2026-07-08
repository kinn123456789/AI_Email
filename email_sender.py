import base64
from email.mime.text import MIMEText
from email.utils import make_msgid
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://mail.google.com/"]

def send_email(from_email, token_file, to_email, subject, body,
               thread_id=None, original_msg_id=None):
    try:
        # Credential Setup
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_file, "w") as token:
                token.write(creds.to_json())

        service = build("gmail", "v1", credentials=creds)

        # Message Creation
        message = MIMEText(body, "plain", "utf-8")
        message["To"] = to_email
        message["From"] = from_email

        if not subject.lower().startswith("re:"):
            message["Subject"] = f"Re: {subject}"
        else:
            message["Subject"] = subject

        # Generate and set RFC Message-ID
        generated_msg_id = make_msgid()
        message["Message-ID"] = generated_msg_id

        if original_msg_id:
            message["In-Reply-To"] = original_msg_id
            message["References"] = original_msg_id

        # Encode and Send
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        payload = {"raw": raw_message}

        # Handle Gmail Threading
        #if thread_id and not thread_id.startswith("<"):
         #   payload["threadId"] = thread_id

        response = service.users().messages().send(userId="me", body=payload).execute()

        print(f"✅ Email sent successfully. Gmail ID: {response['id']}")
        
        # Return both IDs for database storage
        return {
            "gmail_id": response["id"],
            "message_id": generated_msg_id
        }

    except Exception as e:
        print(f"❌ Send Email Error: {e}")
        return None