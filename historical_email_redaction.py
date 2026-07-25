import re

_EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


def redact_pii(text):
    """Applied before text is stored in historical_emails and before it's
    sent for embedding — replaces email addresses and phone-number-shaped
    strings with placeholders, since these become "style examples" the AI
    sees while drafting replies to other, unrelated families.

    Scope is deliberately narrow: standard email syntax and common phone
    number formats only. Names are not redacted here — see the PII audit
    discussion this was scoped from."""

    if not text:
        return text

    text = _EMAIL_PATTERN.sub("[EMAIL]", text)
    text = _PHONE_PATTERN.sub("[PHONE]", text)

    return text
