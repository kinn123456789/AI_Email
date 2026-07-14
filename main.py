from fastapi import FastAPI
from ai_classifier import ai_triage
from database import db_pool,get_latest_thread_ai
from fastapi import Request
from fastapi.templating import Jinja2Templates
from email_sender import send_email
from database import get_teacher_messages,get_last_history_id,update_last_history_id
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
    update_followup_schedule
    
    
)
from followup_email import send_email as followup_send_email
from datetime import datetime, timedelta
from gmail_history import get_gmail_history
import scheduler
import os
from gmail_message import get_message

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
    get_avg_resolution_time,
    get_conversation,
    get_conversation_messages,
    get_contact_forms,
    update_final_reply, update_reply_type,get_email_thread,get_thread,get_latest_ai_summary,
    get_support_emails
)
templates = Jinja2Templates(directory="templates")



from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()

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

    conversation = get_conversation(chat_id)

    print("CONVERSATION:")
    print(conversation)

    messages = get_conversation_messages(chat_id)

    return templates.TemplateResponse(
        "conversation_detail.html",
        {
            "request": request,
            "conversation": conversation,
            "messages": messages
        }
    )
@app.get("/emails")
def emails():

    return get_emails()

@app.get("/email/{email_id}")


def view_email(request: Request, email_id: int):

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

    conversation = get_thread(thread_id) if thread_id else []
    school_email = email_data["source"]

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
            "school_email": school_email
            
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



from fastapi import Form, Request
from fastapi.responses import RedirectResponse

@app.post("/email/{email_id}/send")
async def send_reply(
    request: Request,
    email_id: int,
    reply_body: str = Form(...)
):
    
    original_email = get_email_by_id(email_id)

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

    elif source == "shopsat19@gmail.com":
        from_email = os.getenv("EMAIL_4")
        token_file = "token_sat.json"

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
        previous_references=original_email.get("references_header")
    )
    mailbox=original_email["mailbox"]

    if sent_result:

        update_final_reply(email_id, reply_body)
        update_reply_type(email_id, "human")
        update_status(email_id, "Replied")
        set_resolved_time(email_id)
        set_first_reply_time(email_id)

        import time
        time.sleep(2)

        import sync_sent_gmail
        sync_sent_gmail.main()

        return RedirectResponse(
            url=f"/email/{email_id}?sent=true",
            status_code=303
        )

        #save_email(
          #  sender=source,
           # subject=original_email["subject"],
           # body=reply_body,
          #  category=original_email["category"],
          #  priority=original_email["priority"],
          #  ai_summary="Manual reply",
          #  ai_draft_reply=reply_body,
          #  message_id=sent_result["message_id"],
          #  thread_id=original_email["thread_id"], 
          #  in_reply_to=original_email["message_id"],
          #  source=source,
          #  status="Replied",
          #  reply_type="human",
          #  mailbox=mailbox,
          #  references_header=original_email.get("references_header")

       # )

        #update_final_reply(email_id, reply_body)
        #update_reply_type(email_id, "human")
        #update_status(email_id, "Replied")
       # set_resolved_time(email_id)
       # set_first_reply_time(email_id)

       # print(f"✅ Email {email_id} sent and saved successfully.")

        

       # return RedirectResponse(
        #    url=f"/email/{email_id}?sent=true",
        #    status_code=303
       # )

    #print(f"❌ Email sending failed for {email_id}")

   # return RedirectResponse(
    #    url=f"/email/{email_id}?error=true",
    #    status_code=303
   # )

   
@app.get("/dashboard")
def dashboard(request: Request):

    rows = get_emails()
    counts = get_category_counts()
    avg_response = get_avg_first_response_time()
    avg_resolution = get_avg_resolution_time()
    needs_review_count = len(
    [e for e in rows if e["status"] == "Needs Review"]
)
    auto_reply_count = len(
    [e for e in rows if e.get("reply_type") == "automatic"]
)
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
            "avg_resolution": avg_resolution
        }
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


@app.post("/submit-enquiry")
def submit_enquiry(data: dict):

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
        ai_draft_reply=result["draft_reply"],

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
def contact_dashboard(request: Request):

    contacts = get_contact_forms()

    return templates.TemplateResponse(
        "contact_dashboard.html",
        {
            "request": request,
            "contacts": contacts
        }
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
def trial_followups(request: Request):

    rows = get_followup_email_logs()
    completed_campaigns = get_completed_campaign_count()
    
    due_followups = get_due_followups() 
    return templates.TemplateResponse(
        "trial_followup.html",
        {
            "request": request,
            "rows": rows,
            "completed_campaigns": completed_campaigns,
            "due_followups": due_followups 
        }
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
def notification_mailbox(request: Request):
    rows = get_support_emails()

    return templates.TemplateResponse(
        "notifications.html",
        {
            "request": request,
            "emails": rows
        }
    )

@app.get("/trial-followup/send/{email_id}")
def send_followup(email_id: int):

    email = get_followup_email(email_id)

    if not email:
        return {"success": False, "message": "Email not found"}

    if email["status"].lower() == "sent":
        return {
            "success": False,
            "message": "Email already sent."
        }

    gmail_message_id = send_email(
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

        update_followup_schedule(
            email_id=email_id,
             scheduled_at=datetime.now() + timedelta(days=3)
        )

    elif email["email_number"] == 2:
        update_followup_email2_sent(email["learner_id"])

        update_followup_schedule(
            email_id=email_id,
            scheduled_at=datetime.now() + timedelta(days=7)
        )

    elif email["email_number"] == 3:
        update_followup_email3_sent(email["learner_id"])
        complete_followup_campaign(email["learner_id"])



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
async def gmail_webhook(request: Request):

    body = await request.json()

    print("=" * 80)
    print("RAW PUBSUB")
    print(json.dumps(body, indent=2))

    # Decode Pub/Sub payload
    encoded = body["message"]["data"]
    decoded = base64.b64decode(encoded).decode("utf-8")
    data = json.loads(decoded)

    email_address = data["emailAddress"]
    history_id = str(data["historyId"])

    print("Mailbox:", email_address)
    print("History ID:", history_id)

    # Select token
    if email_address == "support@coralacademy.com":
        token_file = "token_support.json"

    elif email_address == "lucy@coralacademy.com":
        token_file = "token_lucy.json"

    elif email_address == "engineering@coralacademy.com":
        token_file = "token_engineering.json"

    elif email_address == "shopsat19@gmail.com":
        token_file = "token_sat.json"

    else:
        print("Unknown mailbox:", email_address)
        return {"success": True}

    print("Token:", token_file)

    # Read last processed history
    last_history = get_last_history_id(
        email_address
    )

    print("Last History:", last_history)

    # First notification
    if last_history is None:

        print("Initializing history for", email_address)

        update_last_history_id(
            email_address,
            history_id
        )

        return {"success": True}

    page_token = None
    processed_ok = True

    while True:

        history = get_gmail_history(
            token_file=token_file,
            history_id=last_history,
            page_token=page_token
        )

        print(history)

        if not history.get("history"):
            break

        # Process THIS page
        for record in history["history"]:

            for item in record.get("messagesAdded", []):

                message_info = item["message"]

                labels = message_info.get("labelIds", [])

                if "DRAFT" in labels:
                    print("Skipping draft")
                    continue

                gmail_message_id = message_info["id"]

                print("=" * 80)
                print("MESSAGE:", gmail_message_id)
                print("=" * 80)

                try:

                    msg = get_message(
                        token_file,
                        gmail_message_id
                    )

                    if msg is None:
                        continue

                    process_email(
                        msg,
                        {
                            "email": email_address,
                            "source": email_address,
                            "token": token_file
                        }
                    )

                except Exception as e:

                    processed_ok = False

                    print(f"Failed to process {gmail_message_id}")
                    print(e)

        page_token = history.get("nextPageToken")

        if not page_token:
            break

    # Update checkpoint once, after ALL pages are processed
    if processed_ok:

        print("=" * 80)
        print("CHECKPOINT:", history["historyId"])
        print("=" * 80)

        update_last_history_id(
            email_address,
            history["historyId"]
        )

    return {"success": True}