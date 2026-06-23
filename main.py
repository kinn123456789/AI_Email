from fastapi import FastAPI
from ai_classifier import ai_triage
from database import db_pool
from fastapi import Request
from fastapi.templating import Jinja2Templates
from email_sender import send_email
from database import get_teacher_messages


import os
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
    get_contact_forms
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

    return templates.TemplateResponse(
        "home.html",
        {"request": request}
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
    # Fetch the full email details including the AI draft
    
    email_data = get_email_by_id(email_id) # Ensure this returns [id, sender, subject, body, category, ai_summary, ai_draft_reply]
    
    return templates.TemplateResponse(
        "email_detail.html",
        {
            "request": request,
            "email": email_data
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

@app.post("/email/{email_id}/send")
    
# 1. Fetch the final edited reply from a form
# 2. Call your send_email function
# # 3. Redirect back to /dashboard
async def send_reply(
    email_id: int,
    request: Request
):

    form = await request.form()

    reply_body = form["reply_body"]
    
    email = get_email_by_id(email_id)
    source = email["source"]
    recipient = email["sender"]
    subject = "Re: " + email["subject"]
    if source == "Inbox 1":
        from_email = os.getenv("EMAIL_1")
        password = os.getenv("APP_PASSWORD_1")

    elif source == "Inbox 2":
        from_email = os.getenv("EMAIL_2")
        password = os.getenv("APP_PASSWORD_2")

    elif source == "Inbox 3":
        from_email = os.getenv("EMAIL_3")
        password = os.getenv("APP_PASSWORD_3")
    else:
    
        return RedirectResponse(
            url="/dashboard",
            status_code=303
        )
    send_email(
        from_email=from_email,
        password=password,
        to_email=recipient,
        subject=subject,
        body=reply_body
    )

    set_first_reply_time(email_id)


    set_resolved_time(email_id)

    update_status(
        email_id,
        "Resolved"
    )


   
    
    return RedirectResponse(
        url="/dashboard",
        status_code=303
    )




   
@app.get("/dashboard")
def dashboard(request: Request):

    rows = get_emails()
    counts = get_category_counts()
    avg_response = get_avg_first_response_time()
    avg_resolution = get_avg_resolution_time()
    needs_review_count = len(
    [e for e in rows if e["status"] == "Needs Review"]
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

@app.get("/resolve/{email_id}")
def resolve_email(email_id):

    update_status(email_id, "Resolved")

    return RedirectResponse(url="/dashboard")

@app.get("/start/{email_id}")
def start_email(email_id):

    update_status(email_id, "In Progress")

    return RedirectResponse(url=f"/email/{email_id}")
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

##db_pool.closeall()