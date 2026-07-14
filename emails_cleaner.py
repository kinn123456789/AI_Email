import re

def clean_email_body(body: str) -> str:

    if not body:
        return ""

    patterns = [
        r"\nOn .* wrote:",
        r"\nFrom:",
        r"\nSent:",
        r"\nTo:",
        r"\nSubject:",
        r"\n-----Original Message-----",
        r"\n________________________________",
        r"\n--- Forwarded message ---",
        r"\nBegin forwarded message:"
    ]

    body = re.split(
        "|".join(patterns),
        body,
        flags=re.IGNORECASE
    )[0]

    body = "\n".join(
        line
        for line in body.splitlines()
        if not line.lstrip().startswith(">")
    )

    return body.strip()