import smtplib
from email.mime.text import MIMEText
from email.utils import make_msgid

def send_email(
    from_email,
    password,
    to_email,
    subject,
    body
):

    try:

        msg = MIMEText(body)

        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email

        message_id = make_msgid()
        msg["Message-ID"] = message_id

        with smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465
        ) as server:

            server.login(
                from_email,
                password
            )

            server.send_message(msg)

        print(
            f"Email sent from {from_email} to {to_email}"
        )

        return message_id

    except Exception as e:

        print(
            f"Send Email Error: {e}"
        )

        return None