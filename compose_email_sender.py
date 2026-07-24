import base64

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


def send_new_email(
    from_email,
    token_file,
    to_email,
    subject,
    body,
    attachments=None
):

    creds = Credentials.from_authorized_user_file(
        token_file,
        ["https://www.googleapis.com/auth/gmail.send"]
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        with open(token_file, "w") as token:
            token.write(creds.to_json())

    service = build(
        "gmail",
        "v1",
        credentials=creds
    )

    if attachments:

        message = MIMEMultipart()
        message.attach(MIMEText(body))

        for filename, file_data, content_type in attachments:

            maintype, _, subtype = (content_type or "application/octet-stream").partition("/")

            part = MIMEBase(maintype or "application", subtype or "octet-stream")
            part.set_payload(file_data)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"'
            )
            message.attach(part)

    else:
        message = MIMEText(body)

    message["To"] = to_email
    message["From"] = from_email
    message["Subject"] = subject

    raw = base64.urlsafe_b64encode(
        message.as_bytes()
    ).decode()

    sent = service.users().messages().send(
        userId="me",
        body={
            "raw": raw
        }
    ).execute()

    return sent