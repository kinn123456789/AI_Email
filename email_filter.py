import re

from email.utils import parseaddr

from database import get_email_filter_rules


SENDERS = {}
DOMAINS = {}
HEADERS = {}
SUBJECTS = {}
BODIES = {}

AUTOMATED_SENDERS = {
    "no-reply@accounts.google.com",
    "noreply@accounts.google.com",
    "no-reply@github.com",
    "notifications@github.com",
    "noreply@razorpay.com",
    "notifications@github.com",
    "noreply@razorpay.com",
    "welcome@supabase.com",
    "info@retool.com",
    "no-reply@zoom.us",
    "no-reply@slack.com",
}

AUTOMATED_DOMAINS = {
    "shopify.com",
    "github.com",
    "supabase.com",
    "razorpay.com",
    "retool.com",
    "zoom.us",
    "slack.com",
}

AUTOMATED_SUBJECTS = {
    "security alert",
    "verification code",
    "verification email",
    "password reset",
    "new device",
    "payment failed",
    "payment received",
    "invoice",
    "receipt",
    "export of your products",
    "your products are ready",
    "welcome to",
    "confirm your email",
    "email verification",
    "login code",
    "sign in code",
}

def refresh_rules():

    global SENDERS
    global DOMAINS
    global HEADERS
    global SUBJECTS
    global BODIES

    SENDERS = {}
    DOMAINS = {}
    HEADERS = {}
    SUBJECTS = {}
    BODIES = {}

    rules = get_email_filter_rules()

    for rule in rules:

        rule_type = rule["rule_type"].lower()

        if rule_type == "sender":
            SENDERS[rule["rule_value"].lower()] = rule
            
        elif rule_type == "domain":
            DOMAINS[rule["rule_value"].lower()] = rule

        elif rule_type == "header":
            HEADERS[rule["rule_value"].lower()] = rule

        elif rule_type == "subject":
            SUBJECTS[rule["rule_value"].lower()] = rule

        elif rule_type == "body":
            BODIES[rule["rule_value"].lower()] = rule

try:
    refresh_rules()
    print(
    f"Loaded "
    f"{len(SENDERS)} senders, "
    f"{len(DOMAINS)} domains, "
    f"{len(HEADERS)} headers, "
    f"{len(SUBJECTS)} subjects, "
    f"{len(BODIES)} bodies"
)
except Exception as e:
    print("Failed to load email filter rules:", e)

def is_automated_email(msg):

    refresh_rules()

    # --------------------
    # Header Rules
    # --------------------

    for header_name, rule in HEADERS.items():

        value = msg.get(header_name)

        if not value:
            continue

        if header_name == "precedence":

            if value.lower() in ["bulk", "junk", "list"]:

                return (
                    True,
                    rule["category"],
                    rule["reason"] or f"Precedence={value}",
                    "support"
                )

        elif value.lower() != "no":

            return (
                True,
                rule["category"],
                rule["reason"] or f"Header: {header_name}",
                "support"
            )

    # --------------------
    # Sender Rules
    # --------------------

    sender = parseaddr(
        msg.get("From", "")
    )[1].lower()
    # --------------------
    # Built-in Automated Senders
    # --------------------

    if sender in AUTOMATED_SENDERS:

        return (
            True,
            "Notification",
            "Known automated sender",
            "support"
        )

    if sender in SENDERS:

        rule = SENDERS[sender]

        return (
            True,
            rule["category"],
            rule["reason"] or f"Blocked sender: {sender}",
            "support"
        )

    if sender.endswith("@vercel.com"):
        
        return True, "System Notification", "Vercel notification", "support"

    if sender.endswith("@retool.com"):
       
        return True, "Billing Notification", "Retool notification", "support"

    if sender.endswith("@linkedin.com"):
        return True, "Social Media", "LinkedIn notification", "support"

    #if sender.endswith("@mailchimp.com"):
       # return True, "Marketing", "Mailchimp notification"
    # --------------------
    # Domain Rules
    # --------------------

    if "@" in sender:

        domain = sender.split("@")[1]

        # --------------------
        # Built-in Automated Domains
        # --------------------

        if (
            domain in AUTOMATED_DOMAINS
            or any(domain.endswith("." + d) for d in AUTOMATED_DOMAINS)
        ):

            return (
                True,
                "Notification",
                "Known automated domain",
                "support"
            )

        for blocked_domain, rule in DOMAINS.items():

            if (
                domain == blocked_domain
                or
                domain.endswith("." + blocked_domain)
            ):

                return (
                    True,
                    rule["category"],
                    rule["reason"] or f"Blocked domain: {domain}",
                    "support"
                )

    # --------------------
    # Subject Rules
    # --------------------

    subject = msg.get(
        "Subject",
        ""
    ).lower()

    # --------------------
    # Built-in Automated Subjects
    # --------------------

    for keyword in AUTOMATED_SUBJECTS:

        if keyword in subject:

            return (
                True,
                "Notification",
                f"Known automated subject: {keyword}",
                "support"
            )

    for pattern, rule in SUBJECTS.items():

        if re.search(pattern, subject):

            return (
                    True,
                    rule["category"],
                    rule["reason"] or f"Subject matched '{pattern}'",
                    "support"
            )

    # --------------------
    # Body Rules
    # --------------------

    body = ""

    try:

        if msg.is_multipart():

            for part in msg.walk():

                if part.get_content_type() == "text/plain":

                    payload = part.get_payload(
                        decode=True
                    )

                    if payload:

                        body += payload.decode(
                            errors="ignore"
                        )

        else:

            payload = msg.get_payload(
                decode=True
            )

            if payload:

                body = payload.decode(
                    errors="ignore"
                )

    except Exception:

        pass

    body = body.lower()

    for pattern, rule in BODIES.items():

        if re.search(pattern, body):

            return (
                    True,
                    rule["category"],
                    rule["reason"] or f"Body matched '{pattern}'",
                    "support"
            )

    return False, "", "", "inbox"