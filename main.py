from fastapi import FastAPI
import csv
import io
from urllib.parse import urlencode
import scheduler
from scheduler import _run_logged_job
from ai_classifier import ai_triage
from database import db_pool,get_latest_thread_ai,get_latest_reply_sources
from fastapi import Request
from fastapi.templating import Jinja2Templates
from email_sender import send_email
from database import (get_teacher_messages,get_last_history_id,update_last_history_id,mark_conversation_read,
                    get_teacher_conversations,mark_chat_read,move_to_trash,get_trash_emails,delete_email,
                    restore_emails_from_trash)
from fastapi import Form
from trial_followup import (
    get_trial_followup_dashboard,
    get_followup_email_logs,
    get_followup_email,
    complete_followup_campaign,
    get_completed_campaign_count,
    get_completed_campaigns,
    update_followup_email_log,
    update_followup_email_log,
    update_followup_email1_sent,
    update_followup_email2_sent,
    update_followup_email3_sent,
    complete_followup_campaign,
    save_followup_reply,
    get_followup_replies,
    get_due_followups,
    update_followup_schedule,
    move_followup_to_trash,
    restore_followup_from_trash,
    get_trashed_followup_email_logs

)
from fastapi import Request
from fastapi.responses import HTMLResponse

from subscription_cancel import (
    get_cancelled_subscriptions,
    get_all_time_cancelled_subscriptions,
    get_subscription_types,
    get_subscription_statuses,
    dismiss_subscription_rows,
    get_dismissed_subscriptions,
    restore_subscription_rows,
    get_subscription_row,
    get_or_generate_reengagement_email,
    save_sent_subscription_email,
    get_sent_subscription_email,
    get_sent_subscriptions
)
from followup_email import send_email as reengagement_send_email
#from database import delete_teacher_message_db
import sync_sent_gmail
from fastapi import BackgroundTasks
import time
from teacher_api_sync import sync_teacher_portal
from fastapi import Form
from fastapi.responses import RedirectResponse
from datetime import datetime

from teacher_api_sender import send_teacher_reply, delete_teacher_message
import requests

from database import (mark_email_read,get_connection,save_conversation_message,
                       get_teachers,get_teacher_conversations,
                       get_conversation,
                       get_conversation_messages,save_teacher_reply,
                       delete_conversation_message)

from fastapi import BackgroundTasks
from save_composed_email import save_composed_email
from gmail_fetch import get_message
from compose_email_sender import send_new_email
from followup_email import send_email as followup_send_email
from datetime import datetime, timedelta
from gmail_history import get_gmail_history, run_history_reader


from sync_sent_gmail import main as sync_sent_emails

import os


from emails_cleaner import clean_email_body

from process_email import process_email

from fastapi import Request
import json
import base64
from database import (
    get_emails,
    get_category_counts,
    get_emails_by_category,
    get_email_by_id,
    update_status,
    save_email,
    set_first_reply_time,
    set_resolved_time,
    get_avg_first_response_time,
    get_conversation,
    get_conversation_messages,
    get_contact_forms,
    update_final_reply, update_reply_type,get_email_thread,get_thread,get_latest_ai_summary,
    get_support_emails,
    save_historical_email,
    save_embedding
)
from embedding_service import generate_embedding
from historical_email_redaction import redact_pii
templates = Jinja2Templates(directory="templates")



from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from database import get_attachments, get_attachment_by_id, find_recipient_name, save_attachment
from database import get_ai_insights, get_ai_log_by_message_id
from database import get_failed_sync_messages, delete_failed_sync_message
from database import get_composed_sent_emails

app = FastAPI()

from logger import logger


@app.exception_handler(Exception)
async def log_unhandled_exceptions(request: Request, exc: Exception):
    """Catches anything that isn't already handled by a specific route and
    logs it via logger.py (file + stdout) - previously an unhandled error
    here only ever showed up as a bare traceback in Render's stdout
    capture, with no durable, host-independent record at all. Doesn't
    change behavior for errors routes already handle themselves; this
    only fires for genuinely unhandled exceptions."""

    logger.exception(f"Unhandled exception on {request.method} {request.url.path}: {exc}")

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


print("MAIN.PY LOADED")
print("########## THIS IS MY MAIN.PY ##########")
for route in app.routes:
    print(route.path, route.methods)

from fastapi.staticfiles import StaticFiles

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)

@app.get("/")
def home(request: Request):
    due_followups = get_due_followups() 
    return templates.TemplateResponse(
        "home.html",
        {"request": request,
        "due_followups": due_followups
        }
    )




@app.get("/conversation/{chat_id}")
def conversation_detail(
    request: Request,
    chat_id: str
):
    mark_conversation_read(chat_id)
    conversation = get_conversation(chat_id)

    print("CONVERSATION:")
    print(conversation)
    mark_chat_read(
        chat_id,
        conversation["teacher_id"]
    )

    messages = get_conversation_messages(chat_id)
    
    latest_parent_message = None

    for msg in reversed(messages):
        if (
            msg["sender"] == conversation["parent_id"]
            and msg.get("ai_draft_reply")
        ):
            latest_parent_message = msg
            break
        print("Latest Parent Message:")
        print(latest_parent_message)
    return templates.TemplateResponse(
        "conversation_detail.html",
        {
            "request": request,
            "conversation": conversation,
            "messages": messages,
            "latest_parent_message": latest_parent_message
        }
    )

@app.get("/emails")
def emails():

    return get_emails()["rows"]


@app.get("/email/{email_id}")
def view_email(request: Request, email_id: int):

    print(">>> VIEW_EMAIL START", email_id)

    mark_email_read(email_id)

    print(">>> AFTER mark_email_read")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT is_read FROM messages WHERE id = %s",
        (email_id,)
    )

    print("AFTER UPDATE:", cur.fetchone())

    cur.close()
    db_pool.putconn(conn)

    email_data = get_email_by_id(email_id)

    print("=" * 50)
    print("EMAIL DATA")
    print(email_data)

    thread_id = email_data.get("thread_id")
    print("THREAD:", thread_id)
    # -------------------------------------------------
    # Show latest AI summary & draft for the thread
    # -------------------------------------------------

    if thread_id:

        latest_ai = get_latest_thread_ai(thread_id)

        if latest_ai:

            email_data["ai_summary"] = latest_ai["ai_summary"]
            email_data["ai_draft_reply"] = latest_ai["ai_draft_reply"]

            # Optional (recommended)
            email_data["category"] = latest_ai["category"]
            email_data["priority"] = latest_ai["priority"]
            email_data["ai_confidence"] = latest_ai["ai_confidence"]
            email_data["requires_review"] = latest_ai["requires_review"]

    #latest_summary = get_latest_ai_summary(thread_id)

    #if latest_summary:
      #  email_data["ai_summary"] = latest_summary

    reply_sources = get_latest_reply_sources(email_data.get("message_id"))

    if reply_sources:
        email_data["knowledge_used"] = reply_sources["knowledge_used"]
        email_data["historical_examples"] = reply_sources["historical_examples"]

    conversation = get_thread(thread_id) if thread_id else []
    school_email = email_data["source"]
    attachments = get_attachments(email_data["message_id"]) if email_data.get("message_id") else []

    print("Thread:", thread_id)
    print("CONVERSATION:")
    print(conversation)
    print("=" * 50)

    return templates.TemplateResponse(
        "email_detail.html",
        {
            "request": request,
            "email": email_data,
            "conversation": conversation,
            "school_email": school_email,
            "attachments": attachments
        }
    )

@app.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: int):

    attachment = get_attachment_by_id(attachment_id)

    if not attachment or not attachment.get("file_data"):
        return Response(content="Attachment not found", status_code=404)

    return Response(
        content=bytes(attachment["file_data"]),
        media_type=attachment["file_type"] or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{attachment["filename"]}"'
        }
    )

@app.get("/teacher-dashboard")
def teacher_dashboard(request: Request):

    messages = get_teacher_messages()

    return templates.TemplateResponse(
        "teacher_dashboard.html",
        {
            "request": request,
            "messages": messages
            
        }
    )


    
# 1. Fetch the final edited reply from a form
# 2. Call your send_email function
# # 3. Redirect back to /dashboard



from fastapi import Form, Request, File, UploadFile
from typing import List


@app.post("/email/{email_id}/send")
async def send_reply(
    request: Request,
     background_tasks: BackgroundTasks,
    email_id: int,
    reply_body: str = Form(...),
    attachments: List[UploadFile] = File(None)
):

    original_email = get_email_by_id(email_id)

    attachment_data = []
    for upload in (attachments or []):
        if not upload or not upload.filename:
            continue
        attachment_data.append(
            (upload.filename, await upload.read(), upload.content_type)
        )

    source = original_email["source"]

    if source == "support@coralacademy.com":
        from_email = os.getenv("EMAIL_1")
        token_file = "token_support.json"

    elif source == "lucy@coralacademy.com":
        from_email = os.getenv("EMAIL_2")
        token_file = "token_lucy.json"

    elif source == "engineering@coralacademy.com":
        from_email = os.getenv("EMAIL_3")
        token_file = "token_engineering.json"

    else:
        return RedirectResponse(
            "/dashboard",
            status_code=303
        )

    sent_result = send_email(
        from_email=from_email,
        token_file=token_file,
        to_email=original_email["sender"],
        subject=original_email["subject"],   # send_email() adds "Re:" automatically
        body=reply_body,
       
        original_msg_id=original_email["message_id"],
        previous_references=original_email.get("references_header"),
        attachments=attachment_data
    )
    mailbox=original_email["mailbox"]

    if sent_result:

        update_final_reply(email_id, reply_body)
        update_reply_type(email_id, "human")
        update_status(email_id, "Replied")
        set_resolved_time(email_id)
        set_first_reply_time(email_id)

        sent_msg = get_message(token_file, sent_result["gmail_id"])
        real_message_id = " ".join((sent_msg.get("Message-ID") or "").split())

        save_email(
            sender=source,
            subject=original_email["subject"],
            body=reply_body,
            category=original_email["category"],
            priority=original_email["priority"],
            ai_summary="Manual reply",
            ai_draft_reply=reply_body,
            message_id=real_message_id,
            thread_id=original_email["thread_id"],
            in_reply_to=original_email["message_id"],
            source=source,
            status="Replied",
            reply_type="human",
            mailbox=mailbox,
            references_header=original_email.get("references_header"),
            has_attachment=bool(attachment_data)
        )

        for filename, file_data, content_type in attachment_data:
            save_attachment(
                message_id=real_message_id,
                filename=filename,
                file_type=content_type,
                file_path="",
                file_data=file_data
            )

        background_tasks.add_task(sync_sent_gmail.main)
        background_tasks.add_task(
            _run_logged_job,
            "save_reply_to_historical_emails",
            lambda: _save_reply_to_historical_emails(
                message_id=real_message_id,
                thread_id=original_email["thread_id"],
                in_reply_to=original_email["message_id"],
                sender=source,
                recipient=original_email["sender"],
                subject=original_email["subject"],
                body=reply_body
            )
        )

        return RedirectResponse(
            url=f"/email/{email_id}?sent=true",
            status_code=303
        )


def _save_reply_to_historical_emails(message_id, thread_id, in_reply_to, sender, recipient, subject, body):
    """Every real staff-sent reply feeds back into the RAG example pool used
    by search_similar_emails/rag_reranker.py, so the AI's style examples
    keep growing from genuine Coral Academy replies instead of only the
    one-time Sent Mail import. Runs as a background task — failures here
    must never affect the actual email send, which has already succeeded
    by the time this runs."""

    try:
        # Redact known names/emails/phone numbers before this text is ever
        # sent for embedding or stored — this becomes a "style example" the
        # AI sees while drafting replies to other, unrelated families.
        redacted_subject = redact_pii(subject)
        redacted_body = redact_pii(body)

        text = f"Subject: {redacted_subject}\n\nBody:\n{clean_email_body(redacted_body)}"
        embedding = generate_embedding(text[:8000])

        historical_id = save_historical_email(
            message_id=message_id,
            thread_id=thread_id,
            in_reply_to=in_reply_to,
            sender=sender,
            recipient=recipient,
            subject=redacted_subject,
            body=redacted_body,
            sent_at=datetime.utcnow(),
            source_account=sender
        )

        if historical_id:
            save_embedding(historical_id, embedding)

    except Exception as e:
        print("Failed to save reply to historical_emails:", e)


@app.get("/dashboard")
def dashboard(request: Request, source: str = None, q: str = None, status: str = None, date_from: str = None, date_to: str = None, page: int = 1, read_status: str = None):

    page_size = 50
    result = get_emails(source=source, search=q, status=status, date_from=date_from, date_to=date_to, page=page, page_size=page_size, read_status=read_status)
    rows = result["rows"]
    total_count = result["total"]
    needs_review_count = result["needs_review_count"]
    auto_reply_count = result["auto_reply_count"]
    page = result["page"]
    total_pages = result["total_pages"]

    counts = get_category_counts()

    avg_minutes = get_avg_first_response_time()

    if avg_minutes is not None:
        avg_minutes = float(avg_minutes)

        days = int(avg_minutes // 1440)
        hours = int((avg_minutes % 1440) // 60)
        minutes = int(avg_minutes % 60)

        if days > 0:
            avg_response = f"{days}d {hours}h"
        elif hours > 0:
            avg_response = f"{hours}h {minutes}m"
        else:
            avg_response = f"{minutes}m"
    else:
        avg_response = "-"

    

    return templates.TemplateResponse( #Everything below this line will never run:(in this function)
                                        #Because Python exits the function as soon as it hits:
                                        #return templates.TemplateResponse
                                        #it sends that response to the browser and finishes the function—which is exactly what you want it to do!
        "dashboard.html",
        {
            "request": request,
            "emails": rows,
            "counts": counts,
            "needs_review_count": needs_review_count,
            "auto_reply_count": auto_reply_count,
            "avg_response": avg_response,
            "trashed": request.query_params.get("trashed"),
            "selected_source": source,
            "search_query": q,
            "selected_status": status,
            "selected_date_from": date_from,
            "selected_date_to": date_to,
            "selected_read_status": read_status,
            "current_page": page,
            "total_pages": total_pages,
            "total_count": total_count,
            "page_size": page_size,
            "is_sent_view": status == "Replied",
            "failed_syncs": get_failed_sync_messages(),
        }
    )

@app.get("/dashboard/sent")
def dashboard_sent(source: str = None, q: str = None, date_from: str = None, date_to: str = None, page: int = 1):

    params = {
        "status": "Replied",
        "source": source or "",
        "q": q or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
        "page": page
    }

    return RedirectResponse(
        url=f"/dashboard?{urlencode(params)}",
        status_code=303
    )

@app.get("/dashboard-data")
def dashboard_data(source: str = None, q: str = None, status: str = None, date_from: str = None, date_to: str = None, page: int = 1, read_status: str = None):

    page_size = 50
    result = get_emails(source=source, search=q, status=status, date_from=date_from, date_to=date_to, page=page, page_size=page_size, read_status=read_status)

    emails = [
        {
            "id": e["id"],
            "subject": e["subject"],
            "sender": e["sender"],
            "source": e["source"],
            "category": e["category"],
            "priority": e["priority"],
            "status": e["status"],
            "created_at": e["created_at"],
            "is_read": e["is_read"],
            "has_attachment": e["has_attachment"],
        }
        for e in result["rows"]
    ]

    return {
        "emails": emails,
        "total": result["total"],
        "needs_review_count": result["needs_review_count"],
        "auto_reply_count": result["auto_reply_count"],
        "current_page": result["page"],
        "total_pages": result["total_pages"],
        "page_size": page_size,
    }

    
@app.get("/category/{category}")
def category_view(
    request: Request,
    category: str
):

    rows = get_emails_by_category(category)

    return templates.TemplateResponse(
        "category.html",
        {
            "request": request,
            "category": category,
            "emails": rows
        }
    )


@app.get("/ai-insights")
def ai_insights(
    request: Request,
    q: str = None,
):

    data = get_ai_insights()
    searched_logs = get_ai_log_by_message_id(q) if q else None

    return templates.TemplateResponse(
        "ai_insights.html",
        {
            "request": request,
            "summary": data["summary"],
            "by_category": data["by_category"],
            "recent_errors": data["recent_errors"],
            "search_query": q,
            "searched_logs": searched_logs,
        }
    )


@app.post("/dashboard/failed-sync/{row_id}/delete")
def delete_failed_sync(row_id: int):

    delete_failed_sync_message(row_id)

    return RedirectResponse(
        url="/dashboard",
        status_code=303
    )


@app.post("/dashboard/failed-sync/{row_id}/retry")
def retry_failed_sync(row_id: int):

    from sync_sent_gmail import retry_one_now
    outcome = retry_one_now(row_id)
    print(f"Manual retry for failed-sync row {row_id}: {outcome}")

    return RedirectResponse(
        url="/dashboard",
        status_code=303
    )


@app.get("/compose/sent")
def compose_sent(request: Request, q: str = None, date_from: str = None, date_to: str = None, page: int = 1):

    page_size = 50
    result = get_composed_sent_emails(search=q, date_from=date_from, date_to=date_to, page=page, page_size=page_size)

    return templates.TemplateResponse(
        "compose_sent.html",
        {
            "request": request,
            "emails": result["rows"],
            "search_query": q,
            "selected_date_from": date_from,
            "selected_date_to": date_to,
            "current_page": result["page"],
            "total_pages": result["total_pages"],
            "total_count": result["total"],
        }
    )


# In-memory rate limit for the public contact form — this endpoint calls
# ai_triage() (a paid AI request) on every single submission with no auth,
# so an unthrottled flood of fake submissions could run up an unbounded AI
# bill. Simple per-IP sliding window; resets on process restart, which is
# fine here since the goal is stopping a burst, not perfect long-term
# tracking.
_contact_form_submission_times = {}
_CONTACT_FORM_RATE_LIMIT = 5
_CONTACT_FORM_RATE_WINDOW_SECONDS = 600  # 10 minutes


def _contact_form_rate_limited(client_ip):
    now = time.time()
    timestamps = _contact_form_submission_times.setdefault(client_ip, [])

    timestamps[:] = [
        t for t in timestamps
        if now - t < _CONTACT_FORM_RATE_WINDOW_SECONDS
    ]

    if len(timestamps) >= _CONTACT_FORM_RATE_LIMIT:
        return True

    timestamps.append(now)
    return False


@app.post("/submit-enquiry")
def submit_enquiry(request: Request, data: dict):

    client_ip = request.client.host if request.client else "unknown"

    if _contact_form_rate_limited(client_ip):
        return JSONResponse(
            status_code=429,
            content={"message": "Too many submissions. Please try again later."}
        )

    result = ai_triage(
        data.get("subject", "Website Enquiry"),
        data["message"]
    )

    save_email(
        sender=data["email"],
        subject=data.get("subject", "Website Enquiry"),
        body=data["message"],

        category=result["category"],
        priority=result["priority"],
        ai_summary=result["summary"],
        # ai_triage() never returns a "draft_reply" key (confirmed by
        # reading every return path in ai_classifier.py) — this was a
        # KeyError crashing every single contact-form submission with a
        # 500 error, unrelated to the rate limiting added above. Contact
        # form doesn't run the full generate_reply() pipeline (that needs
        # thread history/knowledge/historical-email lookups too), so this
        # just stops the crash rather than fabricating a draft.
        ai_draft_reply=result.get("draft_reply", ""),

        message_id=None,
        source="contact_form",

        contact_name=data.get("name"),
        phone=data.get("phone_number")
    )

    return {
        "message": "Enquiry saved",
        "category": result["category"],
        "priority": result["priority"]
    }
@app.get("/contact-dashboard")
def contact_dashboard(request: Request, q: str = None, date_from: str = None, date_to: str = None, page: int = 1, status: str = None):

    page_size = 50
    result = get_contact_forms(search=q, date_from=date_from, date_to=date_to, page=page, page_size=page_size, status=status)

    return templates.TemplateResponse(
        "contact_dashboard.html",
        {
            "request": request,
            "contacts": result["rows"],
            "trashed": request.query_params.get("trashed"),
            "search_query": q,
            "selected_date_from": date_from,
            "selected_date_to": date_to,
            "current_page": result["page"],
            "total_pages": result["total_pages"],
            "total_count": result["total"],
            "page_size": page_size,
            "is_sent_view": status == "Replied"
        }
    )

@app.get("/contact-dashboard/sent")
def contact_dashboard_sent(request: Request, q: str = None, date_from: str = None, date_to: str = None, page: int = 1):
    return contact_dashboard(request, q=q, date_from=date_from, date_to=date_to, page=page, status="Replied")

@app.post("/contact-dashboard/delete-selected")
def delete_contact_forms(email_ids: list[int] = Form(...)):
    count = len(email_ids)

    for email_id in email_ids:
        move_to_trash(email_id)

    return RedirectResponse(
        url=f"/contact-dashboard?trashed={count}",
        status_code=303
    )

@app.get("/category/{category}")
def category_view(
    request: Request,
    category: str
):

    rows = get_emails_by_category(category)

    return templates.TemplateResponse(
        "category.html",
        {
            "request": request,
            "category": category,
            "emails": rows
        }
    )

@app.get("/trial-followup", response_class=HTMLResponse)
def trial_followups(request: Request, q: str = None, date_from: str = None, date_to: str = None, page: int = 1, status: str = None):

    page_size = 50
    result = get_followup_email_logs(search=q, date_from=date_from, date_to=date_to, page=page, page_size=page_size, status=status)
    completed_campaigns = get_completed_campaign_count()

    due_followups = get_due_followups()
    return templates.TemplateResponse(
        "trial_followup.html",
        {
            "request": request,
            "rows": result["rows"],
            "completed_campaigns": completed_campaigns,
            "due_followups": due_followups,
            "trashed": request.query_params.get("trashed"),
            "total_count": result["total"],
            "followup1_count": result["followup1_count"],
            "followup2_count": result["followup2_count"],
            "followup3_count": result["followup3_count"],
            "search_query": q,
            "selected_date_from": date_from,
            "selected_date_to": date_to,
            "current_page": result["page"],
            "total_pages": result["total_pages"],
            "page_size": page_size,
            "is_sent_view": status == "sent"
        }
    )

@app.get("/trial-followup/sent", response_class=HTMLResponse)
def trial_followups_sent(request: Request, q: str = None, date_from: str = None, date_to: str = None, page: int = 1):
    return trial_followups(request, q=q, date_from=date_from, date_to=date_to, page=page, status="sent")

@app.post("/trial-followup/delete-selected")
def trial_followup_delete_selected(email_ids: list[int] = Form(...)):

    move_followup_to_trash(email_ids)

    return RedirectResponse(
        url=f"/trial-followup?trashed={len(email_ids)}",
        status_code=303
    )

@app.get("/trial-followup/trash", response_class=HTMLResponse)
def trial_followup_trash(request: Request):

    rows = get_trashed_followup_email_logs()

    return templates.TemplateResponse(
        "trial_followup_trash.html",
        {
            "request": request,
            "rows": rows,
            "restored": request.query_params.get("restored")
        }
    )

@app.post("/trial-followup/trash/restore")
def trial_followup_trash_restore(email_ids: list[int] = Form(...)):

    restore_followup_from_trash(email_ids)

    return RedirectResponse(
        url=f"/trial-followup/trash?restored={len(email_ids)}",
        status_code=303
    )

@app.get("/trial-followup/email/{email_id}")
def view_followup_email(
    request: Request,
    email_id: int
):

    email = get_followup_email(email_id)

    replies = get_followup_replies(email_id)

  

    return templates.TemplateResponse(
        "trial_followup_emaildetail.html",
        {
            "request": request,
            "email": email,
            "replies": replies
        }
       
    )
@app.get("/trial-followup/completed")
def completed_campaigns(request: Request):

    rows = get_completed_campaigns()

    return templates.TemplateResponse(
        "completed_campaigns.html",
        {
            "request": request,
            "rows": rows
        }
    )
@app.get("/email/{email_id}/dismiss")
def dismiss_email(email_id: int):

    update_reply_type(
            email_id,
            "none"
    )

    update_status(
            email_id,
            "Closed"
    )
    set_resolved_time(email_id)

    update_reply_type(email_id, "none")

    update_status(email_id, "Closed")

    return RedirectResponse(
        url=f"/email/{email_id}?dismissed=true",
        status_code=303
    )


@app.get("/notifications")
def notification_mailbox(request: Request, source: str = None, q: str = None, date_from: str = None, date_to: str = None, page: int = 1):
    page_size = 50
    result = get_support_emails(source=source, search=q, date_from=date_from, date_to=date_to, page=page, page_size=page_size)

    return templates.TemplateResponse(
        "notifications.html",
        {
            "request": request,
            "emails": result["rows"],
            "trashed": request.query_params.get("trashed"),
            "selected_source": source,
            "search_query": q,
            "selected_date_from": date_from,
            "selected_date_to": date_to,
            "current_page": result["page"],
            "total_pages": result["total_pages"],
            "total_count": result["total"],
            "page_size": page_size
        }
    )

@app.post("/trial-followup/send/{email_id}")
def send_followup(email_id: int):

    email = get_followup_email(email_id)

    if not email:
        return {"success": False, "message": "Email not found"}

    if email["status"].lower() == "sent":
        return {
            "success": False,
            "message": "Email already sent."
        }

    gmail_message_id = followup_send_email(
        email["recipient_email"],
        email["subject"],
        email["email_body"]
    )

    if not gmail_message_id:
        return {"success": False}

    update_followup_email_log(
        email_id=email_id,
        gmail_message_id=gmail_message_id,
        status="sent"
    )

    

    if email["email_number"] == 1:
        update_followup_email1_sent(email["learner_id"])
        # Do not create the next pending row here. The processor will create
        # a draft for the next follow-up when its timing condition is met.

    elif email["email_number"] == 2:
        update_followup_email2_sent(email["learner_id"])
        # Do not create the next pending row here. The processor will create
        # a draft for the next follow-up when its timing condition is met.

    elif email["email_number"] == 3:
        update_followup_email3_sent(email["learner_id"])
        complete_followup_campaign(email["learner_id"])

    return RedirectResponse(
        url=f"/trial-followup/email/{email_id}?sent=true",
        status_code=303
    )

@app.post("/trial-followup/reply/{email_id}")

def reply_again(
    email_id: int,
    subject: str = Form(...),
    body: str = Form(...)
):

    print("Reply route called")

    email = get_followup_email(email_id)
    print(email)

    gmail_message_id =  followup_send_email(
        email["recipient_email"],
        subject,
        body
    )

    print("Gmail ID:", gmail_message_id)

    if not gmail_message_id:
        print("Email failed")
        return {"success": False}

    save_followup_reply(
        email_log_id=email_id,
        subject=subject,
        body=body,
        gmail_message_id=gmail_message_id
    )

 

    print("Saved reply")

    return RedirectResponse(
        url=f"/trial-followup/email/{email_id}?reply=sent",
        status_code=303
    )    

@app.post("/gmail/webhook")
async def gmail_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    print("=" * 80)
    print("WEBHOOK RECEIVED")

    body = await request.body()
    print(body.decode())

    try:
        payload = json.loads(body)

        encoded = payload["message"]["data"]
        decoded = base64.b64decode(encoded).decode("utf-8")
        data = json.loads(decoded)

        email_address = data["emailAddress"]
        history_id = data.get("historyId")

        print("Mailbox:", email_address)
        print("History ID:", history_id)
        print("Scheduling background task...")

        background_tasks.add_task(
            _run_logged_job,
            "gmail_history_webhook",
            lambda: run_history_reader(email_address, history_id)
        )

        return {"success": True}

    except Exception as e:
        print("WEBHOOK ERROR:", repr(e))
        return {"success": False, "error": str(e)}




@app.get("/sync-sent/{email_id}")
def sync_sent(email_id: int):

    try:
        sync_sent_emails()
        print("Gmail Sent synchronized.")

    except Exception as e:
        print("Sent sync failed:", e)

    return RedirectResponse(
        url=f"/email/{email_id}?synced=1",
        status_code=303
    )

@app.get("/compose")
def compose(request: Request):

    return templates.TemplateResponse(
        "compose.html",
        {
            "request": request
        }
    )

from fastapi import Form, Request, File, UploadFile
from typing import List

import time
import sync_sent_gmail


MAX_BULK_RECIPIENTS = 100


def parse_csv_recipients(text):
    rows = list(csv.reader(io.StringIO(text)))

    if not rows:
        return []

    if rows[0] and rows[0][0].strip().lower() in ("email", "e-mail", "email address"):
        rows = rows[1:]

    recipients = []
    for row in rows:
        if not row or not row[0].strip():
            continue
        email = row[0].strip()
        name = row[1].strip() if len(row) > 1 else ""
        recipients.append({"email": email, "name": name})

    return recipients


def _send_bulk_emails(recipients, subject, body, from_email, token_file, attachment_data):
    """Runs the actual send loop as a background task instead of inline in
    the request handler — a 100-recipient send does up to 200 sequential
    Gmail API calls (send + refetch per recipient) plus 100 DB writes,
    which could take minutes and risk the request timing out before the
    browser ever gets a response, even though the sends themselves would
    still be succeeding. This way the page responds immediately and the
    sending continues after."""

    sent_count = 0

    for recipient in recipients:

        personalized_subject = subject
        personalized_body = body

        if recipient["name"]:
            personalized_subject = personalized_subject.replace("{{name}}", recipient["name"])
            personalized_body = personalized_body.replace("{{name}}", recipient["name"])

        result = send_new_email(
            from_email=from_email,
            token_file=token_file,
            to_email=recipient["email"],
            attachments=attachment_data,
            subject=personalized_subject,
            body=personalized_body
        )

        if not result:
            continue

        sent_count += 1

        msg = get_message(token_file, result["id"])
        if msg:
            save_composed_email(msg, from_email)
            print(msg["Message-ID"])
            print(msg["Subject"])
            print(msg["From"])

    print(f"Bulk send complete: {sent_count}/{len(recipients)} sent")


@app.post("/compose")
async def compose_email(

    request: Request,

    background_tasks: BackgroundTasks,

    from_account: str = Form(...),

    to_email: str = Form(None),

    bulk_recipients: str = Form(None),

    recipients_csv: UploadFile = File(None),

    recipients_csv_text: str = Form(None),

    subject: str = Form(...),

    body: str = Form(...),

    attachments: List[UploadFile] = File(None)

):

    if from_account == "support":

        from_email = os.getenv("EMAIL_1")
        token_file = "token_support.json"

    elif from_account == "lucy":

        from_email = os.getenv("EMAIL_2")
        token_file = "token_lucy.json"

    elif from_account == "engineering":

        from_email = os.getenv("EMAIL_3")
        token_file = "token_engineering.json"

    else:

        return RedirectResponse(
            "/compose",
            status_code=303
        )

    csv_bytes = await recipients_csv.read() if (recipients_csv and recipients_csv.filename) else None

    if csv_bytes:
        raw_recipients = parse_csv_recipients(csv_bytes.decode("utf-8-sig", errors="ignore"))
    elif recipients_csv_text and recipients_csv_text.strip():
        raw_recipients = parse_csv_recipients(recipients_csv_text)
    elif bulk_recipients and bulk_recipients.strip():
        raw_recipients = []
        for line in bulk_recipients.splitlines():
            line = line.strip()
            if not line:
                continue
            email_part, _, name_part = line.partition(",")
            raw_recipients.append(
                {"email": email_part.strip(), "name": name_part.strip()}
            )
    elif to_email and to_email.strip():
        raw_recipients = [{"email": to_email.strip(), "name": ""}]
    else:
        return RedirectResponse(
            "/compose",
            status_code=303
        )

    if len(raw_recipients) > MAX_BULK_RECIPIENTS:
        return RedirectResponse(
            f"/compose?error=too_many_recipients&limit={MAX_BULK_RECIPIENTS}",
            status_code=303
        )

    recipients = []
    for r in raw_recipients:
        name = r["name"] or find_recipient_name(r["email"]) or ""
        recipients.append({"email": r["email"], "name": name})

    attachment_data = []
    for upload in (attachments or []):
        if upload.filename:
            attachment_data.append(
                (upload.filename, await upload.read(), upload.content_type)
            )

    # A single recipient sends synchronously — fast (one send + one
    # refetch), and staff expect an immediate "was it sent" answer. Bulk
    # sends run as a background task instead — up to 100 recipients means
    # up to 200 sequential Gmail API calls, which could take minutes and
    # risk the request itself timing out before the browser gets a
    # response, even though the sends would still be succeeding server-side.
    if len(recipients) == 1:
        _send_bulk_emails(recipients, subject, body, from_email, token_file, attachment_data)

        return RedirectResponse(
            "/compose?sent=true&count=1",
            status_code=303
        )

    background_tasks.add_task(
        _run_logged_job,
        "send_bulk_emails",
        lambda: _send_bulk_emails(recipients, subject, body, from_email, token_file, attachment_data)
    )

    return RedirectResponse(
        f"/compose?queued=true&count={len(recipients)}",
        status_code=303
    )

#@app.get("/resolve/{email_id}")
#def resolve_email(email_id: int):

    #update_status(email_id, "Resolved")

    #return RedirectResponse(
     #   "/dashboard",
     #   status_code=303
   # )

@app.post("/send-teacher-reply")
def send_teacher_reply_route(
    chat_id: str = Form(...),
    teacher_id: str = Form(...),
    message: str = Form(...)
):

    result = send_teacher_reply(
        chat_id=chat_id,
        teacher_id=teacher_id,
        message=message
    )

    if result is None:
        return RedirectResponse(
            url=f"/conversation/{chat_id}?error=connection",
            status_code=303
        )

    status_code = result.get("status_code")
    if not result.get("success"):
        return RedirectResponse(
            url=f"/conversation/{chat_id}?error={status_code or 'connection'}",
            status_code=303
        )

    # Default in case API doesn't return one
    message_id = f"teacher-{datetime.utcnow().timestamp()}"
    data = result.get("data")
    if isinstance(data, dict) and "response" in data:
        message_id = data["response"].get("id", message_id)

    save_conversation_message(
        chat_id,
        teacher_id,
        message,
        datetime.utcnow(),
        message_id
    )

    return RedirectResponse(
        url=f"/conversation/{chat_id}",
        status_code=303
    )

@app.get("/teacher/{teacher_id}")
def teacher_conversations(request: Request, teacher_id: str):

    t = time.time()
    conversations = get_teacher_conversations(teacher_id)
    print("conversations:", time.time() - t)

    teacher_name = ""

    if conversations:
        teacher_name = conversations[0]["teacher_name"]

    return templates.TemplateResponse(
        "teacher_conversation_list.html",
        {
            "request": request,
            "teacher_name": teacher_name,
            "teacher_id": teacher_id,
            "conversations": conversations
        }
    )

@app.get("/sync-teacher")
def sync_teacher():

    sync_teacher_portal()

    return {
        "status": "success",
        "message": "Teacher Portal sync completed."
    }


from fastapi import Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


@app.get("/teacher-inbox")
def teacher_inbox(
    request: Request,
    teacher_id: str = None,
    chat_id: str = None
):

    teachers = get_teachers()
    print(teachers)

    conversations = []

    conversation = None
    messages = []

    if teacher_id:
        t = time.time()
        conversations = get_teacher_conversations(teacher_id)
        print("conversations:", time.time() - t)
    if chat_id:
        t = time.time()

        conversation = get_conversation(chat_id)

        mark_conversation_read(chat_id)

        t = time.time()

        messages = get_conversation_messages(chat_id)
        for m in messages:
            print(m)
        print("messages:", time.time() - t)

        for msg in reversed(messages):
            if msg["sender"] == conversation["parent_id"]:
                latest_parent_message = msg
                break
        print("LATEST PARENT MESSAGE =", latest_parent_message)
        print("ID =", latest_parent_message.get("id") if latest_parent_message else None)
        if latest_parent_message:
            print("ID =", latest_parent_message.get("id"))
            print("KEYS =", latest_parent_message.keys())
    else:
        latest_parent_message = None

    return templates.TemplateResponse(
        "teacher_inbox.html",
        {
            "request": request,
            "teachers": teachers,
            "selected_teacher": teacher_id,
            "conversations": conversations,
            "selected_chat": chat_id,
            "conversation": conversation,
            "messages": messages,
            "latest_parent_message": latest_parent_message
        }
    )

from fastapi import Form
from teacher_api_sender import send_teacher_reply
from database import mark_reply_sent

from fastapi import Request

def extract_teacher_api_message(result, fallback_body, fallback_teacher_id):
    data = result.get("data") if isinstance(result, dict) else None
    response = data.get("response") if isinstance(data, dict) else None

    if isinstance(response, dict):
        message = response.get("message") or response.get("data") or response
    else:
        message = None

    if not isinstance(message, dict):
        return {
            "message_id": None,
            "sender": fallback_teacher_id,
            "body": fallback_body,
            "created_at": None,
        }

    return {
        "message_id": str(message["id"]) if message.get("id") else None,
        "sender": str(message.get("user_id") or message.get("sender") or fallback_teacher_id),
        "body": message.get("text") or message.get("body") or fallback_body,
        "created_at": message.get("created_at"),
    }

#@app.middleware("http")
#sync def log_request(request: Request, call_next):
#    print("METHOD:", request.method)
 #   print("URL:", request.url)

   # if request.method == "POST":
    #    form = await request.form()
     #   print("FORM DATA:", dict(form))

    #response = await call_next(request)
    # return response

@app.post("/teacher/send-reply")
async def send_reply(request: Request):
#def send_reply(
#
 #   chat_id: str = Form(...),
  #  teacher_id: str = Form(...),
   # message_id: int = Form(...),
    #reply: str = Form("")

#):
    print(">>> ENTERED send_reply")
    form = await request.form()

    print("=" * 80)
    print("RAW FORM")
    print(dict(form))
    print("=" * 80)

    chat_id = form.get("chat_id")
    teacher_id = form.get("teacher_id")
    message_id = form.get("message_id")
    reply = form.get("reply", "").strip()

    # Recover IDs from the inbox URL if the browser submits empty or literal
    # "None" hidden fields from a stale/rendered form.
    if chat_id in (None, "", "None") or teacher_id in (None, "", "None"):
        from urllib.parse import parse_qs, urlparse

        referer = request.headers.get("referer", "")
        query = parse_qs(urlparse(referer).query)
        chat_id = chat_id if chat_id not in (None, "", "None") else query.get("chat_id", [None])[0]
        teacher_id = teacher_id if teacher_id not in (None, "", "None") else query.get("teacher_id", [None])[0]

    print("chat_id:", chat_id)
    print("teacher_id:", teacher_id)
    print("message_id:", message_id)
    print("reply:", reply)

    if not chat_id or not teacher_id:
        return {
            "success": False,
            "error": "Missing chat_id or teacher_id. Open a specific chat before sending."
        }

    reply = reply.strip()

    # Don't send empty messages
    if not reply:
        return RedirectResponse(
            url=f"/teacher-inbox?teacher_id={teacher_id}&chat_id={chat_id}",
            status_code=303
        )
    import time

    t = time.time() 
    result = send_teacher_reply(
        chat_id=chat_id,
        teacher_id=teacher_id,
        message=reply
    )
    print("Teacher API:", time.time() - t)
    print("API RESULT:", result)

    if result["success"]:
        print("Calling save_teacher_reply()")
        sent_message = extract_teacher_api_message(result, reply, teacher_id)
        print("EXTRACTED TEACHER API MESSAGE:", sent_message)

        if message_id:
            mark_reply_sent(message_id)

        save_teacher_reply(
            chat_id=chat_id,
            teacher_id=sent_message["sender"],
            body=sent_message["body"],
            message_id=sent_message["message_id"],
            created_at=sent_message["created_at"]
        )

        print("Finished save_teacher_reply()")
    else:
        print("API FAILED")
        return RedirectResponse(
            url=f"/teacher-inbox?teacher_id={teacher_id}&chat_id={chat_id}&error=teacher_api_send_failed",
            status_code=303
        )

    return RedirectResponse(
        url=f"/teacher-inbox?teacher_id={teacher_id}&chat_id={chat_id}",
        status_code=303
    )

@app.post("/teacher/delete-message")
def delete_message_route(
    chat_id: str = Form(...),
    teacher_id: str = Form(...),
    message_id: str = Form(...)
):
    try:
        delete_teacher_message(chat_id, message_id, teacher_id)
    except requests.RequestException:
        return RedirectResponse(
            url=f"/teacher-inbox?teacher_id={teacher_id}&chat_id={chat_id}&error=delete_failed",
            status_code=303
        )

    delete_conversation_message(message_id)

    return RedirectResponse(
        url=f"/teacher-inbox?teacher_id={teacher_id}&chat_id={chat_id}",
        status_code=303
    )

@app.post("/email/{email_id}/trash")
def trash_email(email_id: int):

    move_to_trash(email_id)

    return RedirectResponse(
        url="/dashboard?trashed=1",
        status_code=303
    )



@app.post("/emails/delete-selected")
def delete_selected(email_ids: list[int] = Form(...)):
    count = len(email_ids)

    for email_id in email_ids:
        move_to_trash(email_id)

    return RedirectResponse(
        url=f"/dashboard?trashed={count}",
        status_code=303
    )

@app.get("/trash")
def trash(request: Request):
    emails = get_trash_emails()

    return templates.TemplateResponse(
        "trash.html",
        {
            "request": request,
            "emails": emails,
            "deleted": request.query_params.get("deleted"),
            "restored": request.query_params.get("restored")
        }
    )

@app.post("/emails/restore-selected")
def restore_selected(email_ids: list[int] = Form(...)):
    count = len(email_ids)

    restore_emails_from_trash(email_ids)

    return RedirectResponse(
        url=f"/trash?restored={count}",
        status_code=303
    )

@app.post("/emails/delete-permanently")
def delete_permanently(email_ids: list[int] = Form(...)):
    count = len(email_ids)

    for email_id in email_ids:
        delete_email(email_id)

    return RedirectResponse(
        url=f"/trash?deleted={count}",
        status_code=303
    )

@app.post("/notifications/delete-selected")
def delete_notifications(email_ids: list[int] = Form(...)):
    count = len(email_ids)

    for email_id in email_ids:
        move_to_trash(email_id)

    return RedirectResponse(
        url=f"/notifications?trashed={count}",
        status_code=303
    )




@app.get("/subscription-cancel", response_class=HTMLResponse)
async def subscription_cancel_dashboard(request: Request, q: str = None, date_from: str = None, date_to: str = None, status: str = None, page: int = 1, show_all: str = None):

    page_size = 50
    show_all_time = show_all == "true"
    fetch = get_all_time_cancelled_subscriptions if show_all_time else get_cancelled_subscriptions
    result = fetch(search=q, date_from=date_from, date_to=date_to, status=status, page=page, page_size=page_size)
    subscription_types = get_subscription_types()
    subscription_statuses = get_subscription_statuses()

    return templates.TemplateResponse(
        "subscription_cancel.html",
        {
            "request": request,
            "subscriptions": result["rows"],
            "subscription_types": subscription_types,
            "subscription_statuses": subscription_statuses,
            "trashed": request.query_params.get("trashed"),
            "search_query": q,
            "selected_date_from": date_from,
            "selected_date_to": date_to,
            "selected_status": status,
            "current_page": result["page"],
            "total_pages": result["total_pages"],
            "total": result["total"],
            "page_size": page_size,
            "show_all_time": show_all_time
        }
    )

@app.post("/subscription-cancel/delete-selected")
async def subscription_cancel_delete_selected(row_keys: list[str] = Form(...), show_all: str = Form(None)):

    fetch = get_all_time_cancelled_subscriptions if show_all == "true" else get_cancelled_subscriptions
    all_rows = fetch(page_size=100000)["rows"]
    selected = [r for r in all_rows if r["row_key"] in set(row_keys)]

    dismiss_subscription_rows(selected)

    return RedirectResponse(
        url=f"/subscription-cancel?trashed={len(selected)}",
        status_code=303
    )

@app.get("/subscription-cancel/trash", response_class=HTMLResponse)
async def subscription_cancel_trash(request: Request):

    dismissed = get_dismissed_subscriptions()

    return templates.TemplateResponse(
        "subscription_cancel_trash.html",
        {
            "request": request,
            "dismissed": dismissed,
            "restored": request.query_params.get("restored")
        }
    )

@app.post("/subscription-cancel/trash/restore")
async def subscription_cancel_trash_restore(row_keys: list[str] = Form(...)):

    restore_subscription_rows(row_keys)

    return RedirectResponse(
        url=f"/subscription-cancel/trash?restored={len(row_keys)}",
        status_code=303
    )

@app.get("/subscription-cancel/email/{row_key}", response_class=HTMLResponse)
async def subscription_cancel_email(request: Request, row_key: str):

    sent = get_sent_subscription_email(row_key)

    if sent:
        return templates.TemplateResponse(
            "subscription_cancel_email.html",
            {
                "request": request,
                "row": sent,
                "sent": sent,
                "subject": sent["subject"],
                "body": sent["body"]
            }
        )

    row = get_subscription_row(row_key)

    if not row:
        return Response(content="Not found", status_code=404)

    subject, body = get_or_generate_reengagement_email(row)

    return templates.TemplateResponse(
        "subscription_cancel_email.html",
        {
            "request": request,
            "row": row,
            "sent": None,
            "subject": subject,
            "body": body
        }
    )

@app.post("/subscription-cancel/email/{row_key}/send")
async def subscription_cancel_email_send(row_key: str, subject: str = Form(...), body: str = Form(...)):

    row = get_subscription_row(row_key)

    if not row or not row.get("parent_email"):
        return RedirectResponse(url=f"/subscription-cancel/email/{row_key}", status_code=303)

    gmail_message_id = reengagement_send_email(row["parent_email"], subject, body)

    save_sent_subscription_email(row, subject, body, gmail_message_id)

    return RedirectResponse(
        url=f"/subscription-cancel/email/{row_key}?sent=true",
        status_code=303
    )

@app.get("/subscription-cancel/sent", response_class=HTMLResponse)
async def subscription_cancel_sent(request: Request):

    rows = get_sent_subscriptions()

    return templates.TemplateResponse(
        "subscription_cancel_sent.html",
        {
            "request": request,
            "rows": rows
        }
    )
