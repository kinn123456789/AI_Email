#process_email.py
from email.utils import parseaddr
from email.header import decode_header
from bs4 import BeautifulSoup
import base64
import email
import os
import re

from emails_cleaner import clean_email_body
from email_filter import is_automated_email
from ai_classifier import ai_triage
from vector_search import search_similar_emails
from rag_reranker import rerank_emails
from knowledge_search import search_knowledge_base
from reply_generator import generate_reply
from slack_notifications import send_slack_notification
from trial_followup import find_trial_followup_by_message_ids, save_followup_reply
from subscription_cancel import find_subscription_by_message_ids, save_subscription_reply
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor
from embedding_service import new_embedding_client, close_embedding_client


from database import (
    email_exists,
    save_email,
    attachment_exists,
    save_attachment,
    get_message_by_message_id,
    reopen_thread,
    get_thread,
    log_event,
    reopen_thread,
    find_recipient_name,
)


ATTACHMENT_DIR = "attachments"

# Attachments larger than this are saved to disk as usual but skipped for
# in-memory image analysis (base64 encoding roughly adds 33% on top of the
# already-decoded bytes) - large attachments piling up in a single poll run
# were a contributor to repeated OOM kills on the 512MB instance.
MAX_IMAGE_ANALYSIS_BYTES = 5 * 1024 * 1024


def process_email(msg, account, ingested_via=None, gmail_internal_id=None):
    """ingested_via/gmail_internal_id identify which pipeline (the Gmail
    History API webhook reader, or the independent IMAP backup poller)
    fetched this message, and Gmail's own internal message id where
    available (only the API-based path has it - IMAP has no equivalent).
    Both are purely for diagnosis and stored as-is; the actual
    duplicate-prevention guarantee is the UNIQUE(message_id, source)
    constraint in save_email() below, not this early check - two pipelines
    racing to process the same new message can both pass this check before
    either has saved anything, so this is a fast-path to skip expensive AI
    calls on known duplicates, not the real safety net."""

    message_id = " ".join((msg.get("Message-ID") or "").split())

    if not message_id or email_exists(message_id, account["source"]):
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
    sender_name = parseaddr(msg.get("From", ""))[0]

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

    has_attachment = False

    for part in msg.walk():

        content_type = part.get_content_type()
        filename = part.get_filename()

        if filename:

            has_attachment = True

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

                if "image" in content_type and len(file_data) <= MAX_IMAGE_ANALYSIS_BYTES:

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
                    filepath,
                    file_data=file_data
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

    parent = None

    if in_reply_to:
        parent = get_message_by_message_id(
            in_reply_to, account["source"]
        )

    # Checked whenever the In-Reply-To lookup didn't find a parent — whether
    # that's because In-Reply-To pointed to something we don't have, or
    # because In-Reply-To was missing entirely but References was still
    # present (happens with some mail clients/forwarded threads). Previously
    # this only ran nested inside the `if in_reply_to:` branch, so a message
    # with References but no In-Reply-To at all skipped it completely and
    # got fragmented into a disconnected new thread.
    if not parent and references_header:

        for ref in reversed(
            references_header.split()
        ):

            parent = get_message_by_message_id(ref, account["source"])

            if parent:
                break

    if parent:

        thread_id = parent["thread_id"]
        reopen_thread(thread_id)

    else:

        thread_id = message_id

    # Additive check, independent of the thread_id resolution above: does
    # this email also happen to be a reply to a trial-followup or
    # subscription-reengagement email this app sent? If so, log it into that
    # module's own reply table too, so a genuine parent reply shows up on
    # that dashboard instead of only being visible in the general inbox.
    # This never changes thread_id, mailbox routing, or anything below -
    # it's purely an extra record, best-effort (a lookup failure here must
    # never block normal email processing).
    try:

        candidate_message_ids = [in_reply_to] + references_header.split()
        candidate_message_ids = [m for m in candidate_message_ids if m]

        if candidate_message_ids:

            followup_match = find_trial_followup_by_message_ids(candidate_message_ids)

            if followup_match:

                save_followup_reply(
                    email_log_id=followup_match["id"],
                    subject=subject,
                    body=body,
                    gmail_message_id=None,
                    sender="parent",
                    real_message_id=message_id
                )

            subscription_match = find_subscription_by_message_ids(candidate_message_ids)

            if subscription_match:

                save_subscription_reply(
                    row_key=subscription_match["row_key"],
                    subject=subject,
                    body=body,
                    gmail_message_id=None,
                    sender="parent",
                    real_message_id=message_id
                )

    except Exception as e:

        print(f"Trial-followup/subscription reply-matching failed (non-blocking): {e}")

    skip, category, reason, mailbox = is_automated_email(msg)

    contact_phone = None

    if mailbox == "contact_form":

        name_match = re.search(r"Name:\s*(.*)", body)
        email_match = re.search(r"Email:\s*(\S+)", body)
        phone_match = re.search(r"Phone:\s*(.*)", body)
        message_match = re.search(
            r"Message:\s*(.*?)\s*(?:\n\s*Submitted at:|$)",
            body,
            re.DOTALL
        )

        if name_match:
            sender_name = name_match.group(1).strip() or sender_name

        if email_match and "@" in email_match.group(1):
            sender_email = email_match.group(1).strip()

        if phone_match:
            contact_phone = phone_match.group(1).strip()

        if message_match:
            body = message_match.group(1).strip()

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
            email_date=email_date,
            has_attachment=has_attachment,
            sender_name=sender_name,
            gmail_internal_id=gmail_internal_id,
            ingested_via=ingested_via
        )

        return

    history = get_thread(thread_id) if in_reply_to else []

    history_text = "\n".join(
        f"{m['sender']}:\n{m['body']}"
        for m in history
    )

    # ai_triage, search_similar_emails, and search_knowledge_base are
    # independent of each other (none needs another's result), so they run
    # concurrently instead of one after another — cuts the time before an
    # email shows up fully processed on the dashboard. The two embedding
    # calls each get their own isolated client: embedding_service's shared
    # default client isn't safe to use from two threads at once (same class
    # of issue already found and fixed for the Supabase client elsewhere in
    # this app).
    similar_client = new_embedding_client()
    knowledge_client = new_embedding_client()

    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            triage_future = executor.submit(
                ai_triage, subject, body, history=history_text, images=image_data_list, gmail_message_id=message_id
            )
            similar_future = executor.submit(
                search_similar_emails, subject, body, embedding_client=similar_client
            )
            knowledge_future = executor.submit(
                search_knowledge_base, subject, body, embedding_client=knowledge_client, rerank=True
            )

            result = triage_future.result()
            similar = similar_future.result()
            knowledge = knowledge_future.result()
    finally:
        close_embedding_client(similar_client)
        close_embedding_client(knowledge_client)

    reranked = rerank_emails(
        subject,
        body,
        similar
    )
    selected_ids = {
        item["id"]
        for item in reranked["selected"]
    }

    historical_emails = [
        email
        for email in similar
        if email[0] in selected_ids
    ]
    print("Selected IDs:", selected_ids)
    print("Historical Emails Count:", len(historical_emails))

    
    draft = generate_reply(
        message_id,
        subject,
        body,
        result["category"],
        result["priority"],
        history_text,
        #similar,
        #reranked,
        historical_emails,
        knowledge,
        source=account["source"],
        customer_name=find_recipient_name(sender_email),
        email_date=email_date,
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
        requires_review=result["requires_review"],
        ai_confidence=result["confidence"],
        #reply_type="human",
        reply_type=result["reply_type"],
        mailbox=mailbox,
        references_header=references_header,
        email_date=email_date,
        has_attachment=has_attachment,
        sender_name=sender_name,
        contact_name=sender_name if mailbox == "contact_form" else None,
        phone=contact_phone,
        gmail_internal_id=gmail_internal_id,
        ingested_via=ingested_via
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