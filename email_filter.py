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
    "no-reply@github.com",
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
    "email verification",
    "login code",
    "sign in code",
}
AUTOMATED_LOCAL_PARTS = {
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "notifications",
    "notification",
    "updates",
    "alerts",
    "mailer",
    "system",
    "newsletter",
    
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
    # Auto-generated email
    auto_submitted = msg.get("Auto-Submitted", "").lower()
    if auto_submitted and auto_submitted != "no":
        return (
            True,
            "Notification",
            f"Auto-Submitted={auto_submitted}",
            "support"
        )

    # Mailing list
    if msg.get("List-Id"):
        return (
            True,
            "Notification",
            "Mailing List",
            "support"
        )

    # Has unsubscribe header (newsletter/marketing)
    if msg.get("List-Unsubscribe"):
        return (
            True,
            "Notification",
            "List-Unsubscribe header",
            "support"
        )

    # Auto response suppression
    if msg.get("X-Auto-Response-Suppress"):
        return (
            True,
            "Notification",
            "Auto Response Suppress",
            "support"
        )
    # --------------------
    # Header Rules
    # --------------------
    # --------------------
    # Sender Rules
    # --------------------

    # --------------------
    # Extract sender details
    # --------------------
    sender = parseaddr(msg.get("From", ""))[1].lower()

    local_part = ""
    domain = ""

    if "@" in sender:
        local_part, domain = sender.split("@", 1)

    # --------------------
    # Website Contact Form
    # --------------------
    if (
        sender == "no-reply@coralacademy.com"
        and msg.get("Subject", "").lower().startswith("new contact form enquiry")
    ):
        return (
            False,
            "Contact Form Enquiry",
            "",
            "contact_form"
        )

    # --------------------
    # Reply Detection
    # --------------------
    is_reply = bool(
        msg.get("In-Reply-To") or
        msg.get("References")
    )

    if is_reply:

        is_known_automated = (
            sender in AUTOMATED_SENDERS or
            domain in AUTOMATED_DOMAINS or
            any(domain.endswith("." + d) for d in AUTOMATED_DOMAINS)
        )

        if not is_known_automated:
            return (
                False,
                "",
                "",
                "inbox"
            )



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
    # Automated Local Part
    # --------------------
    if local_part in AUTOMATED_LOCAL_PARTS:
        return (
            True,
            "Notification",
            f"Automated sender ({local_part})",
            "support"
        )

    

    # --------------------
    # Built-in Automated Senders
    # --------------------

    # If this is a reply from a sender that is NOT a known automated sender,
    # let AI decide instead of filtering it as a notification.

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

    # if sender.endswith("@mailchimp.com"):
        # return True, "Marketing", "Mailchimp notification"
    # --------------------
    # Domain Rules
    # --------------------

    if domain:

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

    subject = msg.get("Subject", "").lower()

    # If this is a reply/forward, don't classify based on subject keywords
    if subject.startswith(("re:", "fw:", "fwd:")):
        pass
    else:
        for keyword in AUTOMATED_SUBJECTS:

            if keyword in subject:

                return (
                    True,
                    "Notification",
                    f"Known automated subject: {keyword}",
                    "support"
                )

    # --------------------
    # Built-in Automated Subjects
    # --------------------

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

