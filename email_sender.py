import smtplib
from email.mime.text import MIMEText

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

        with smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465#smtp port number
        ) as server:

            server.login(
                from_email,
                password
            )

            server.send_message(msg)

        print(
            f"Email sent from {from_email} to {to_email}"
        )

        return True

    except Exception as e:

        print(
            f"Send Email Error: {e}"
        )

        return False