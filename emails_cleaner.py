import re

def clean_email_body(body):

    if not body:
        return ""

    body = re.split(
        r"\nOn .* wrote:|\nFrom:|\n-----Original Message-----",
        body,
        flags=re.IGNORECASE
    )[0]

    body = "\n".join(
        line
        for line in body.splitlines()
        if not line.strip().startswith(">")
    )

    return body.strip()