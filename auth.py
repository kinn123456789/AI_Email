"""Authentication for the AI_Email dashboard.

The dashboard previously had no authentication at all - any request to
any route (including ones that send real email or return customer PII)
was served unconditionally. This module implements a stateless,
signed-cookie session using PyJWT (already an existing dependency - no
new package added), plus per-session CSRF protection for the ~50 POST
forms across the app's templates.

Session model: a single shared operator login (DASHBOARD_USERNAME /
DASHBOARD_PASSWORD), not per-user accounts - matches the "keep it small"
scope of this fix. The session itself carries no secret data, only
`sub` and `exp`, so the cookie's confidentiality doesn't matter - only
its *integrity* does, which is what the HS256 signature protects.

Fails closed, not open: if SESSION_SECRET_KEY, DASHBOARD_USERNAME, or
DASHBOARD_PASSWORD is missing from the environment, every login attempt
and every session-verification call raises AuthConfigError rather than
silently treating the app as open - the opposite of the bug this module
exists to fix.
"""

import hmac
import os
import secrets
import time

import jwt
from markupsafe import Markup, escape

SESSION_COOKIE_NAME = "ai_email_session"
CSRF_COOKIE_NAME = "ai_email_csrf"
CSRF_FORM_FIELD = "csrf_token"

SESSION_TTL_SECONDS = 60 * 60 * 12  # 12 hours - long enough for a work day
JWT_ALGORITHM = "HS256"


class AuthConfigError(RuntimeError):
    """Required auth configuration (SESSION_SECRET_KEY, DASHBOARD_USERNAME,
    or DASHBOARD_PASSWORD) is missing from the environment. Raised instead
    of falling back to any default, so a misconfigured deploy fails loudly
    at the moment auth is needed rather than quietly serving the dashboard
    unauthenticated."""


def _get_required_env(name):
    value = os.environ.get(name)
    if not value:
        raise AuthConfigError(
            f"{name} is not set - authentication cannot be enforced without it."
        )
    return value


def _session_secret():
    return _get_required_env("SESSION_SECRET_KEY")


def verify_credentials(username, password):
    """Constant-time comparison against DASHBOARD_USERNAME/DASHBOARD_PASSWORD.
    Returns True/False - never logs or echoes either the submitted or the
    configured value, and never distinguishes "bad username" from "bad
    password" in its return value (that distinction is what the generic
    login-failure message in main.py relies on)."""

    expected_username = _get_required_env("DASHBOARD_USERNAME")
    expected_password = _get_required_env("DASHBOARD_PASSWORD")

    username_ok = hmac.compare_digest(username or "", expected_username)
    password_ok = hmac.compare_digest(password or "", expected_password)

    return username_ok and password_ok


def create_session_token(subject="staff"):
    """Signs a stateless session JWT. Payload is intentionally minimal -
    just who (a fixed subject, since this is a single shared login) and
    until when - nothing here is sensitive if decoded, only the
    signature's validity matters."""

    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + SESSION_TTL_SECONDS,
    }
    return jwt.encode(payload, _session_secret(), algorithm=JWT_ALGORITHM)


def verify_session_token(token):
    """Returns the decoded payload if the token is valid (correct
    signature, not expired), or None for any failure - expired, tampered,
    malformed, wrong algorithm, or a missing signing key. Callers only
    need to know "session valid or not"; they never see why it failed,
    which is what a bare None communicates without leaking detail an
    attacker could use to narrow down a forgery attempt."""

    if not token:
        return None

    try:
        secret = _session_secret()
    except AuthConfigError:
        return None

    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def generate_csrf_token():
    """A fresh random token, independent of the session JWT - stored in
    its own cookie (readable by JS-free template code via request.cookies,
    unlike the HttpOnly session cookie) and compared against whatever the
    submitted form field carries. The classic double-submit-cookie
    pattern: an attacker's cross-site form can make the browser attach
    the session cookie automatically, but cannot read or set this
    non-HttpOnly cookie value for a different origin, so it can't forge a
    matching form field."""

    return secrets.token_urlsafe(32)


def verify_csrf(cookie_token, form_token):
    """True only if both a cookie token and a form token are present and
    equal (constant-time). Either being missing, or the two not
    matching, is a rejection - there is no "trust the form's value alone"
    path, since that would defeat the double-submit design entirely."""

    if not cookie_token or not form_token:
        return False
    return hmac.compare_digest(cookie_token, form_token)


def set_session_cookie(response, token):
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=SESSION_TTL_SECONDS,
    )


def set_csrf_cookie(response, token):
    # Deliberately NOT httponly - Jinja templates need to read it via
    # request.cookies to render the hidden form field. Its value is
    # never treated as a secret on its own (see verify_csrf's docstring);
    # only the cookie/form-field match matters.
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
        max_age=SESSION_TTL_SECONDS,
    )


def clear_auth_cookies(response):
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


def csrf_input(request):
    """Registered as a Jinja global (see main.py) so every template can
    write `{{ csrf_input(request) }}` inside a <form method="post"> and
    get a correctly-named hidden field for whatever CSRF cookie value is
    actually present - one call site to get right instead of the literal
    field/cookie name copy-pasted into ~20 templates, where a typo in any
    one of them would silently leave that specific form unprotected."""

    token = request.cookies.get(CSRF_COOKIE_NAME, "")
    return Markup(
        f'<input type="hidden" name="{CSRF_FORM_FIELD}" value="{escape(token)}">'
    )
