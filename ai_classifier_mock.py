def ai_triage(subject, body,images=None):

    text = (subject + " " + body).lower()

    if "teacher" in text or "homework" in text:
        category = "Teacher"
        priority = "High"
        summary = "Teacher related enquiry"
        draft_reply = "Thank you for Contacting"

    elif "admission" in text:
        category = "Admissions"
        priority = "Medium"
        summary = "Admissions enquiry"
        draft_reply = "Thank you for your interest in our school."

    elif "fee" in text or "payment" in text:
        category = "Billing"
        priority = "Medium"
        summary = "Payment related"
        draft_reply = "Thank you for contacting us regarding billing."

    else:
        category = "General"
        priority = "Low"
        summary = "General enquiry"
        draft_reply = "Thank you for contacting us."

    return {
        "category": category,
        "priority": priority,
        "summary": summary,
        "draft_reply": draft_reply
    }