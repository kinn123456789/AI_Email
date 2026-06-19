from fastapi import FastAPI
from ai_classifier import ai_triage
from database import db_pool
from fastapi import Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

from database import (
    get_emails,
    get_category_counts,
    get_emails_by_category,
    get_email_by_id,
    update_status,
    save_email
)

from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()

@app.get("/")
def home():
    return {"message": "AI Email Agent Running"}

@app.get("/emails")
def emails():

    rows = get_emails()

    result = []

    for row in rows:

        result.append({
            "id": row[0],
            "sender": row[1],
            "subject": row[2],
            "category": row[3]
        })

    return result

@app.get("/dashboard")
def dashboard(request: Request):

    rows = get_emails()
    counts = get_category_counts()

    return templates.TemplateResponse( #Everything below this line will never run:
                                        #Because Python exits the function as soon as it hits:
                                        #return templates.TemplateResponse
                                        #it sends that response to the browser and finishes the function—which is exactly what you want it to do!
        "dashboard.html",
        {
            "request": request,
            "emails": rows,
            "counts": counts
        }
    )
    rows = get_emails()
    counts = get_category_counts()

    html = "<h1>AI Email Dashboard</h1>"
    html += "<h2>Category Summary</h2>"

    for category, count in counts:
        html += f"""
        <p>
            <a href="/category/{category}">
                {category}: {count}
            </a>
        </p>
        """

    for row in rows:

        html += f"""
        <div style='border:1px solid #ccc;padding:10px;margin:10px'>
            <h3>
                <a href="/email/{row[0]}">
                    {row[2]}
                </a>
            </h3>

            <p>{row[1]}</p>
            <p>{row[3]}</p>
            <p>Status: {row[4]}</p>
        """

        if row[4] == "New":
            html += f'<a href="/start/{row[0]}">Start Work</a>'

        elif row[4] == "In Progress":
            html += f'<a href="/resolve/{row[0]}">Resolve</a>'

        html += "</div>"

    return html

@app.get("/category/{category}", response_class=HTMLResponse)
def category_view(category):

    rows = get_emails_by_category(category)

    html = f"<h1>{category} Emails</h1>"

    for row in rows:

        html += f"""
        <div style='border:1px solid #ccc;padding:10px;margin:10px'>
            <h3>
            <a href="/email/{row[0]}">
             {row[2]}
            </a>
            </h3>
            <p>{row[1]}</p>
            <p>{row[3]}</p>
            <p>Status: {row[4]}</p>
        </div>
        """

    return html
@app.get("/email/{email_id}", response_class=HTMLResponse)
def email_detail(email_id):

    row = get_email_by_id(email_id)

    html = f"""

    <a href="/dashboard">← Back to Dashboard</a>
    <br><br>

    <h1>{row[2]}</h1>

    <p><b>Sender:</b> {row[1]}</p>

    <p><b>Category:</b> {row[4]}</p>

    <hr>

    <pre>{row[3]}</pre>
    """

    return html
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
##db_pool.closeall()