def classify_email(subject, body):

    text = (subject + " " + body).lower()

    if "fee" in text or "admission" in text:
        return "Admissions"

    elif "teacher" in text or "homework" in text:
        return "Teacher"

    elif "payment" in text or "refund" in text:
        return "Billing"

    elif "complaint" in text:
        return "Urgent"

    return "General"