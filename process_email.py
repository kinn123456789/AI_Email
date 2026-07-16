from email.utils import parseaddr
from email.header import decode_header
from bs4 import BeautifulSoup
import base64
import email
import os

from emails_cleaner import clean_email_body
from email_filter import is_automated_email
from ai_classifier import ai_triage
from vector_search import search_similar_emails
from rag_reranker import rerank_emails
from knowledge_search import search_knowledge_base
from reply_generator import generate_reply
from slack_notifications import send_slack_notification
from email.utils import parsedate_to_datetime


from database import (
    email_exists,
    save_email,
    attachment_exists,
    save_attachment,
    get_message_by_message_id,
    reopen_thread,
    get_thread,
    log_event,
    reopen_thread
)


ATTACHMENT_DIR = "attachments"


def process_email(msg, account):

    message_id = " ".join((msg.get("Message-ID") or "").split())

    if not message_id or email_exists(message_id):
        print("Duplicate:", message_id)
        return

    subject_raw, encoding = decode_header(
        msg.get("Subject", "No Subject")
    )[0]

    subject = (
        subject_raw.decode(
            encoding or "utf-8",
            errors="ignore"
        )
        if isinstance(subject_raw, bytes)
        else subject_raw
    )

    sender_email = parseaddr(msg.get("From", ""))[1]
    
    email_date = parsedate_to_datetime(msg["Date"])
    

    body = ""
    html_body = ""
    image_data_list = []

    safe_message_id = (
        message_id
        .replace("<", "")
        .replace(">", "")
        .replace("/", "_")
    )

    for part in msg.walk():

        content_type = part.get_content_type()
        filename = part.get_filename()

        if filename:

            filename = os.path.basename(filename)

            if not attachment_exists(
                message_id,
                filename
            ):

                file_data = part.get_payload(decode=True)

                filepath = os.path.join(
                    ATTACHMENT_DIR,
                    f"{safe_message_id}_{filename}"
                )

                with open(filepath, "wb") as f:
                    f.write(file_data)

                if "image" in content_type:

                    image_data_list.append(
                        {
                            "filename": filename,
                            "data": base64.b64encode(file_data).decode()
                        }
                    )

                save_attachment(
                    message_id,
                    filename,
                    content_type,
                    filepath
                )

        else:

            if content_type == "text/plain":

                body += part.get_payload(
                    decode=True
                ).decode(errors="ignore")

            elif content_type == "text/html":

                html_body += part.get_payload(
                    decode=True
                ).decode(errors="ignore")

    if not body.strip() and html_body:

        body = BeautifulSoup(
            html_body,
            "html.parser"
        ).get_text(
            separator=" ",
            strip=True
        )

    body = clean_email_body(body)

    in_reply_to = " ".join(
        (msg.get("In-Reply-To") or "").split()
    )

    references_header = " ".join(
        (msg.get("References") or "").split()
    )

    if in_reply_to:

        parent = get_message_by_message_id(
            in_reply_to
        )

        if not parent and references_header:

            for ref in reversed(
                references_header.split()
            ):

                parent = get_message_by_message_id(ref)

                if parent:
                    break

        if parent:

            thread_id = parent["thread_id"]
            reopen_thread(thread_id)

        else:

            thread_id = message_id

    else:

        thread_id = message_id

    skip, category, reason, mailbox = is_automated_email(msg)
    
    if skip:
        
        save_email(
            sender=sender_email,
            subject=subject,
            body=body,
            category=category,
            priority="Low",
            ai_summary=reason,
            ai_draft_reply="",
            message_id=message_id,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            source=account["source"],
            status="No Reply Required",
            mailbox=mailbox,
            references_header=references_header,
            email_date=email_date
        )

        return

    history = get_thread(thread_id) if in_reply_to else []

    history_text = "\n".join(
        f"{m['sender']}:\n{m['body']}"
        for m in history
    )

    result = ai_triage(
        subject,
        body,
        history=history_text,
        images=image_data_list
    )

    similar = search_similar_emails(
        subject,
        body
    )

    reranked = rerank_emails(
        subject,
        body,
        similar
    )

    knowledge = search_knowledge_base(
        subject,
        body
    )

    draft = generate_reply(
        message_id,
        subject,
        body,
        result["category"],
        result["priority"],
        history_text,
        similar,
        knowledge
    )

    save_email(
        sender_email,
        subject,
        body,
        result["category"],
        result["priority"],
        result["summary"],
        draft,
        message_id,
        thread_id,
        in_reply_to,
        account["source"],
        status="Needs Review",
        requires_review=True,
        ai_confidence=result["confidence"],
        reply_type="human",
        mailbox=mailbox,
        references_header=references_header,
        email_date=email_date
    )

    print("Processed:", message_id)
    #send_slack_notification(
      #  title="New Email Received",
      #  sender=sender_email,
       # subject=subject,
      #  priority=result["priority"],
      #  category=result["category"],
      #  link=f"https://ai-email-2.onrender.com/email/{email_id}"
   # )