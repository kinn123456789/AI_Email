import re

def clean_email_body(body: str) -> str:
    """
    Removes quoted email history from Gmail, Outlook and similar clients.
    """

    if not body:
        return ""

    body = re.split(
        r"\nOn .* wrote:"
        r"|\nFrom:"
        r"|\n-----Original Message-----"
        r"|\n________________________________",
        body,
        flags=re.IGNORECASE
    )[0]

    body = "\n".join(
        line
        for line in body.splitlines()
        if not line.lstrip().startswith(">")
    )

    return body.strip()