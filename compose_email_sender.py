import base64

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

from gmail_auth import get_gmail_service


def send_new_email(
    from_email,
    token_file,
    to_email,
    subject,
    body,
    attachments=None
):
    # token_file is unused now (kept only so existing callers don't need to
    # change) - auth is via domain-wide delegation, impersonating
    # from_email directly. See gmail_auth.py.
    service = get_gmail_service(from_email)

    try:
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
    finally:
        service.close()