from database import save_email
from database import email_exists

def save_composed_email(
    msg,
    from_email
    
):
    
    subject = msg.get("Subject", "")

    message_id = msg.get("Message-ID")

    references = msg.get("References")

    in_reply_to = msg.get("In-Reply-To")

    body = ""

    if msg.is_multipart():

        for part in msg.walk():

            if (
                part.get_content_type() == "text/plain"
                and "attachment" not in str(part.get("Content-Disposition"))
            ):

                body = part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8",
                    errors="ignore"
                )

                break

    else:

        body = msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8",
            errors="ignore"
        )


    if email_exists(message_id):
        return
    save_email(

        sender=from_email,

        subject=subject,

        body=body,

        category="General",

        priority="Low",

        ai_summary="Manual compose email",

        ai_draft_reply=body,

        message_id=message_id,

        thread_id=message_id,

        in_reply_to=in_reply_to,

        source=from_email,

        status="Replied",

        reply_type="gmail_manual",

        mailbox="sent",

        references_header=references

    )