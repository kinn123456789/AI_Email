"""Focused tests for the Phase 2 authentication implementation (auth.py,
plus the AuthMiddleware/login/logout wiring added to main.py).

Distinct from the pre-existing, unrelated test_auth.py (a manual Supabase
user-listing script) - not modified or touched by this file.

Matches this repo's existing test_*.py convention (see
test_accuracy_fixes.py): a plain script using only assert statements and
the standard library plus whatever's already installed - no pytest.

TWO LAYERS OF TESTING, FOR TWO DIFFERENT REASONS:

1. auth.py is imported and exercised FOR REAL - it has no exotic
   dependencies (os, hmac, secrets, time, jwt, markupsafe - all already
   installed) and no import-time side effects, so every session/CSRF/
   credential primitive here is genuine, not a reimplementation.

2. main.py cannot be imported in this environment, for a much stronger
   reason than test_accuracy_fixes.py's existing main.py constraint
   (missing fastapi/apscheduler): main.py transitively imports
   scheduler.py, which calls scheduler.start() AND runs a live
   subscription-cache warm-up AT MODULE IMPORT TIME - importing main
   here would start real background jobs and attempt real database/API
   connections, not just fail an import. So:
   - The AuthMiddleware dispatch behavior (redirect/401/403 decisions)
     is verified against a small standalone FastAPI app built in this
     file, wired to the REAL auth.py functions - genuine HTTP behavior
     via FastAPI's TestClient (httpx, already installed), just not
     literally main.py's own 58 routes.
   - main.py's actual source is then verified with plain string/regex
     checks (same technique as test_accuracy_fixes.py's M1-M3 checks)
     to confirm the real file contains the expected middleware
     registration, PUBLIC_PATHS entries, and login/logout routes.

Run with: python3 test_authentication.py
"""

import os
import re
import sys
import time

import jwt


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


# ---------------------------------------------------------------------------
# Environment isolation - auth.py reads SESSION_SECRET_KEY/DASHBOARD_USERNAME/
# DASHBOARD_PASSWORD from os.environ at call time (not at import time), so
# tests can freely set/clear them per-check without any module reload.
# Real values (if this machine happens to have a .env loaded some other
# way) are saved and restored so this test file never leaks or depends on
# whatever's actually configured for a real deployment.
# ---------------------------------------------------------------------------

_ENV_KEYS = ["SESSION_SECRET_KEY", "DASHBOARD_USERNAME", "DASHBOARD_PASSWORD"]
_saved_env = {k: os.environ.get(k) for k in _ENV_KEYS}


def _clear_auth_env():
    for k in _ENV_KEYS:
        os.environ.pop(k, None)


def _restore_env():
    for k, v in _saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _set_test_env():
    os.environ["SESSION_SECRET_KEY"] = "test-secret-key-not-a-real-deployment-value"
    os.environ["DASHBOARD_USERNAME"] = "test_operator"
    os.environ["DASHBOARD_PASSWORD"] = "test_password_123"


_clear_auth_env()
_set_test_env()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auth  # noqa: E402 - imported only after test env vars are set


# ---------------------------------------------------------------------------
# Layer 1: auth.py itself, real functions, no mocking.
# ---------------------------------------------------------------------------

def test_session_token_round_trip():
    token = auth.create_session_token()
    payload = auth.verify_session_token(token)
    check(
        "valid session token verifies and carries sub='staff'",
        payload is not None and payload.get("sub") == "staff",
        f"got {payload!r}",
    )


def test_tampered_session_token_rejected():
    token = auth.create_session_token()
    tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]
    payload = auth.verify_session_token(tampered)
    check(
        "a tampered (signature-broken) token is rejected",
        payload is None,
        f"got {payload!r}",
    )


def test_expired_session_token_rejected():
    now = int(time.time())
    expired_token = jwt.encode(
        {"sub": "staff", "iat": now - 100, "exp": now - 1},
        os.environ["SESSION_SECRET_KEY"],
        algorithm=auth.JWT_ALGORITHM,
    )
    payload = auth.verify_session_token(expired_token)
    check(
        "an expired token is rejected",
        payload is None,
        f"got {payload!r}",
    )


def test_token_signed_with_wrong_key_rejected():
    forged = jwt.encode(
        {"sub": "staff", "iat": int(time.time()), "exp": int(time.time()) + 3600},
        "a-completely-different-attacker-controlled-key",
        algorithm=auth.JWT_ALGORITHM,
    )
    payload = auth.verify_session_token(forged)
    check(
        "a token signed with a different key is rejected",
        payload is None,
        f"got {payload!r}",
    )


def test_missing_or_empty_token_rejected():
    check("None token -> None", auth.verify_session_token(None) is None)
    check("empty-string token -> None", auth.verify_session_token("") is None)
    check("garbage-string token -> None", auth.verify_session_token("not.a.jwt") is None)


def test_missing_session_secret_key_fails_safely():
    """The core "fail closed, not open" requirement: with no
    SESSION_SECRET_KEY configured, verifying ANY token - even one that
    would otherwise be valid under a real key - must return None, never
    raise past this call site to somehow be treated as "auth disabled,
    let it through", and never fall back to a default/hardcoded key."""

    valid_looking_token = auth.create_session_token()  # signed while key IS set

    del os.environ["SESSION_SECRET_KEY"]
    try:
        payload = auth.verify_session_token(valid_looking_token)
        check(
            "verify_session_token with no SESSION_SECRET_KEY set returns None (fails closed)",
            payload is None,
            f"got {payload!r}",
        )
    finally:
        _set_test_env()


def test_verify_credentials_correct():
    check(
        "correct username+password -> True",
        auth.verify_credentials("test_operator", "test_password_123") is True,
    )


def test_verify_credentials_wrong_password():
    check(
        "correct username, wrong password -> False",
        auth.verify_credentials("test_operator", "wrong") is False,
    )


def test_verify_credentials_wrong_username():
    check(
        "wrong username, correct password -> False",
        auth.verify_credentials("someone_else", "test_password_123") is False,
    )


def test_verify_credentials_empty_input():
    check(
        "empty username/password -> False, no crash",
        auth.verify_credentials("", "") is False,
    )


def test_missing_dashboard_credentials_fails_safely():
    """Same fail-closed requirement as the session secret, for the
    credential env vars: a login attempt against a misconfigured
    deployment must be rejected, never silently accepted."""

    del os.environ["DASHBOARD_USERNAME"]
    del os.environ["DASHBOARD_PASSWORD"]
    try:
        raised = False
        try:
            result = auth.verify_credentials("anyone", "anything")
        except auth.AuthConfigError:
            raised = True
            result = None
        check(
            "verify_credentials with missing env vars never returns True (raises or returns False)",
            raised or result is False,
            f"raised={raised} result={result!r}",
        )
    finally:
        _set_test_env()


def test_csrf_valid_pair_accepted():
    token = auth.generate_csrf_token()
    check(
        "matching cookie+form CSRF tokens verify",
        auth.verify_csrf(token, token) is True,
    )


def test_csrf_mismatched_pair_rejected():
    check(
        "different cookie vs form CSRF tokens are rejected",
        auth.verify_csrf(auth.generate_csrf_token(), auth.generate_csrf_token()) is False,
    )


def test_csrf_missing_pieces_rejected():
    token = auth.generate_csrf_token()
    check("missing cookie token -> False", auth.verify_csrf(None, token) is False)
    check("missing form token -> False", auth.verify_csrf(token, None) is False)
    check("both missing -> False", auth.verify_csrf(None, None) is False)


def test_csrf_tokens_are_distinct_per_call():
    check(
        "two generated CSRF tokens are not identical (real randomness, not a fixed value)",
        auth.generate_csrf_token() != auth.generate_csrf_token(),
    )


def test_csrf_input_renders_expected_hidden_field():
    class FakeRequest:
        cookies = {auth.CSRF_COOKIE_NAME: "abc123"}

    html = str(auth.csrf_input(FakeRequest()))
    check(
        "csrf_input() renders a hidden input with the cookie's token value",
        'name="csrf_token"' in html and 'value="abc123"' in html and "type=\"hidden\"" in html,
        f"got {html!r}",
    )


def test_csrf_input_escapes_cookie_value():
    """The CSRF cookie is attacker-uncontrollable in practice (server-set,
    random), but csrf_input() still escapes it before interpolating into
    HTML - defense in depth against any future caller that feeds it an
    unexpected value."""

    class FakeRequest:
        cookies = {auth.CSRF_COOKIE_NAME: '"><script>alert(1)</script>'}

    html = str(auth.csrf_input(FakeRequest()))
    check(
        "csrf_input() HTML-escapes the token value",
        "<script>" not in html,
        f"got {html!r}",
    )


# ---------------------------------------------------------------------------
# Layer 2: end-to-end HTTP behavior via a small standalone FastAPI app,
# wired to the REAL auth.py functions the same way main.py's own
# AuthMiddleware is (see its docstring in main.py for why main.py itself
# can't be imported here).
# ---------------------------------------------------------------------------

def _build_test_app():
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    app = FastAPI()

    PUBLIC_PATHS = {"/login", "/submit-enquiry", "/gmail/webhook"}
    JSON_UNAUTHENTICATED_PATHS = {"/emails", "/dashboard-data"}

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path
            if path in PUBLIC_PATHS or path.startswith("/static/"):
                return await call_next(request)

            session = auth.verify_session_token(request.cookies.get(auth.SESSION_COOKIE_NAME))
            if not session:
                if path in JSON_UNAUTHENTICATED_PATHS:
                    return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
                return RedirectResponse(url="/login", status_code=303)

            if request.method == "POST":
                csrf_cookie = request.cookies.get(auth.CSRF_COOKIE_NAME)
                form = await request.form()
                if not auth.verify_csrf(csrf_cookie, form.get(auth.CSRF_FORM_FIELD)):
                    return JSONResponse(status_code=403, content={"detail": "Invalid CSRF token"})

            return await call_next(request)

    app.add_middleware(AuthMiddleware)

    @app.get("/login")
    def login_get():
        return PlainTextResponse("login form")

    @app.post("/login")
    async def login_post(request: Request):
        form = await request.form()
        if auth.verify_credentials(form.get("username", ""), form.get("password", "")):
            response = RedirectResponse(url="/dashboard", status_code=303)
            auth.set_session_cookie(response, auth.create_session_token())
            auth.set_csrf_cookie(response, auth.generate_csrf_token())
            return response
        return RedirectResponse(url="/login?error=1", status_code=303)

    @app.post("/logout")
    def logout():
        response = RedirectResponse(url="/login", status_code=303)
        auth.clear_auth_cookies(response)
        return response

    @app.get("/dashboard")
    def dashboard():
        return PlainTextResponse("protected dashboard content")

    @app.get("/emails")
    def emails_json():
        return {"rows": ["would be real customer data"]}

    @app.get("/dashboard-data")
    def dashboard_data_json():
        return {"emails": []}

    @app.post("/email/1/send")
    async def send_email_route(request: Request):
        return PlainTextResponse("sent")

    @app.post("/submit-enquiry")
    async def submit_enquiry():
        return {"message": "Enquiry saved"}

    @app.post("/gmail/webhook")
    async def gmail_webhook():
        return {"success": True}

    return app


def _get_test_client():
    from fastapi.testclient import TestClient
    return TestClient(_build_test_app())


def test_unauthenticated_html_route_redirects_to_login():
    client = _get_test_client()
    resp = client.get("/dashboard", follow_redirects=False)
    check(
        "unauthenticated GET /dashboard redirects toward /login",
        resp.status_code in (302, 303, 307) and resp.headers.get("location", "").startswith("/login"),
        f"status={resp.status_code} location={resp.headers.get('location')!r}",
    )


def test_unauthenticated_emails_json_returns_401():
    client = _get_test_client()
    resp = client.get("/emails")
    check(
        "unauthenticated GET /emails returns 401, not the data",
        resp.status_code == 401 and "would be real customer data" not in resp.text,
        f"status={resp.status_code} body={resp.text!r}",
    )


def test_unauthenticated_dashboard_data_returns_401():
    client = _get_test_client()
    resp = client.get("/dashboard-data")
    check(
        "unauthenticated GET /dashboard-data returns 401",
        resp.status_code == 401,
        f"status={resp.status_code}",
    )


def test_login_page_is_public():
    client = _get_test_client()
    resp = client.get("/login")
    check("GET /login succeeds with no session", resp.status_code == 200)


def test_login_with_correct_credentials_succeeds_and_sets_cookie():
    client = _get_test_client()
    resp = client.post(
        "/login",
        data={"username": "test_operator", "password": "test_password_123"},
        follow_redirects=False,
    )
    check(
        "correct login redirects to /dashboard",
        resp.status_code == 303 and resp.headers.get("location") == "/dashboard",
        f"status={resp.status_code} location={resp.headers.get('location')!r}",
    )
    check(
        "correct login sets the session cookie",
        auth.SESSION_COOKIE_NAME in resp.cookies,
    )


def test_login_with_wrong_credentials_rejected_no_cookie():
    client = _get_test_client()
    resp = client.post(
        "/login",
        data={"username": "test_operator", "password": "wrong_password"},
        follow_redirects=False,
    )
    check(
        "wrong password redirects back to /login (not /dashboard)",
        resp.status_code == 303 and resp.headers.get("location", "").startswith("/login"),
        f"status={resp.status_code} location={resp.headers.get('location')!r}",
    )
    check(
        "failed login does NOT set a session cookie",
        auth.SESSION_COOKIE_NAME not in resp.cookies,
    )


def test_authenticated_request_succeeds():
    client = _get_test_client()
    client.cookies.set(auth.SESSION_COOKIE_NAME, auth.create_session_token())
    resp = client.get("/dashboard")
    check(
        "a request carrying a valid session cookie reaches the protected route",
        resp.status_code == 200 and "protected dashboard content" in resp.text,
        f"status={resp.status_code}",
    )


def test_logout_clears_session_and_blocks_further_access():
    # Goes through the real POST /login flow (rather than directly
    # injecting a cookie into the client, as other tests above do for
    # brevity) so the session/CSRF cookies carry the same domain/path
    # httpx's cookie jar would actually assign in a real browser session -
    # only then does a later delete_cookie() genuinely match and remove
    # them, exactly as it would for a real logged-in user clicking log out.
    client = _get_test_client()
    login_resp = client.post(
        "/login",
        data={"username": "test_operator", "password": "test_password_123"},
        follow_redirects=False,
    )
    csrf_token = client.cookies.get(auth.CSRF_COOKIE_NAME)

    logout_resp = client.post(
        "/logout", data={auth.CSRF_FORM_FIELD: csrf_token}, follow_redirects=False
    )
    check("logout redirects to /login", logout_resp.status_code == 303)

    after_logout = client.get("/dashboard", follow_redirects=False)
    check(
        "a request after logout is denied again (redirected to /login)",
        after_logout.status_code in (302, 303, 307)
        and after_logout.headers.get("location", "").startswith("/login"),
        f"status={after_logout.status_code}",
    )


def test_tampered_cookie_rejected_end_to_end():
    client = _get_test_client()
    real_token = auth.create_session_token()
    client.cookies.set(auth.SESSION_COOKIE_NAME, real_token + "tampered")
    resp = client.get("/dashboard", follow_redirects=False)
    check(
        "a tampered session cookie is treated as unauthenticated",
        resp.status_code in (302, 303, 307),
        f"status={resp.status_code}",
    )


def test_mutation_without_csrf_token_rejected():
    client = _get_test_client()
    client.cookies.set(auth.SESSION_COOKIE_NAME, auth.create_session_token())
    # Deliberately no CSRF cookie/form field at all.
    resp = client.post("/email/1/send", data={"reply_body": "hello"})
    check(
        "an authenticated POST with no CSRF token at all is rejected with 403",
        resp.status_code == 403,
        f"status={resp.status_code}",
    )


def test_mutation_with_invalid_csrf_token_rejected():
    client = _get_test_client()
    client.cookies.set(auth.SESSION_COOKIE_NAME, auth.create_session_token())
    client.cookies.set(auth.CSRF_COOKIE_NAME, "real-cookie-value")
    resp = client.post(
        "/email/1/send",
        data={"reply_body": "hello", auth.CSRF_FORM_FIELD: "a-different-forged-value"},
    )
    check(
        "an authenticated POST with a mismatched CSRF token is rejected with 403",
        resp.status_code == 403,
        f"status={resp.status_code}",
    )


def test_mutation_with_valid_csrf_token_allowed():
    client = _get_test_client()
    client.cookies.set(auth.SESSION_COOKIE_NAME, auth.create_session_token())
    token = auth.generate_csrf_token()
    client.cookies.set(auth.CSRF_COOKIE_NAME, token)
    resp = client.post(
        "/email/1/send",
        data={"reply_body": "hello", auth.CSRF_FORM_FIELD: token},
    )
    check(
        "an authenticated POST with a matching CSRF token succeeds",
        resp.status_code == 200 and "sent" in resp.text,
        f"status={resp.status_code} body={resp.text!r}",
    )


def test_submit_enquiry_remains_public_no_session_no_csrf():
    client = _get_test_client()
    resp = client.post("/submit-enquiry", json={})
    check(
        "POST /submit-enquiry works with no session and no CSRF token",
        resp.status_code == 200,
        f"status={resp.status_code}",
    )


def test_gmail_webhook_remains_public_no_session_no_csrf():
    client = _get_test_client()
    resp = client.post("/gmail/webhook", json={})
    check(
        "POST /gmail/webhook works with no session and no CSRF token",
        resp.status_code == 200,
        f"status={resp.status_code}",
    )


# ---------------------------------------------------------------------------
# Layer 3: static verification of the REAL main.py source - confirms the
# actual file (not this test's standalone mirror app) contains the
# expected wiring. Same technique as test_accuracy_fixes.py's M1-M3 checks.
# ---------------------------------------------------------------------------

def _read_main_source():
    with open(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"),
        "r", encoding="utf-8",
    ) as f:
        return f.read()


def test_main_py_registers_auth_middleware():
    src = _read_main_source()
    check(
        "main.py registers AuthMiddleware on the app",
        "app.add_middleware(AuthMiddleware)" in src,
    )


def test_main_py_public_paths_contains_exactly_the_required_set():
    src = _read_main_source()
    match = re.search(r"PUBLIC_PATHS\s*=\s*\{([^}]*)\}", src, re.DOTALL)
    check("main.py defines PUBLIC_PATHS", match is not None)
    if match:
        body = match.group(1)
        required = ["/login", "/submit-enquiry", "/gmail/webhook"]
        for path in required:
            check(
                f'PUBLIC_PATHS includes "{path}"',
                f'"{path}"' in body,
            )
        check(
            "PUBLIC_PATHS does NOT include a protected route by accident "
            "(e.g. /dashboard, /emails, /settings)",
            not any(
                bad in body
                for bad in ['"/dashboard"', '"/emails"', '"/settings"', '"/email/', '"/trash"']
            ),
            f"PUBLIC_PATHS body={body!r}",
        )


def test_main_py_defines_login_and_logout_routes():
    src = _read_main_source()
    check('main.py defines GET "/login"', '@app.get("/login")' in src)
    check('main.py defines POST "/login"', '@app.post("/login")' in src)
    check('main.py defines POST "/logout"', '@app.post("/logout")' in src)


def test_main_py_static_mount_unchanged():
    """Confirms the auth work didn't touch how /static is served - it
    should still be the same StaticFiles mount pointing at the local
    static/ directory, nothing broader."""
    src = _read_main_source()
    check(
        "static files are still mounted via StaticFiles(directory=\"static\")",
        'StaticFiles(\n    directory="static"' in src or 'StaticFiles(directory="static"' in src,
    )


def test_main_py_registers_csrf_jinja_global_on_both_templates_instances():
    """Confirms every template - including the ones rendered by routes
    after the second `templates = Jinja2Templates(...)` reassignment
    later in the file - has csrf_input available. Missing this on the
    second instance would leave that block of templates able to render
    {{ csrf_input(request) }} as a Jinja UndefinedError instead of a
    working hidden field."""
    src = _read_main_source()
    occurrences = src.count('templates.env.globals["csrf_input"] = auth.csrf_input')
    check(
        "csrf_input is registered on both Jinja2Templates instances",
        occurrences == 2,
        f"found {occurrences} registration(s), expected 2",
    )


# ---------------------------------------------------------------------------
# Layer 4: every existing POST form in templates/ has the CSRF field,
# except the explicitly-exempt public ones. Same search the implementation
# itself was required to perform (method="post", method='post', <form).
# ---------------------------------------------------------------------------

def test_every_protected_post_form_has_csrf_field():
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    exempt_actions = ("/login",)  # the only public POST form

    missing = []
    checked = 0

    for filename in sorted(os.listdir(templates_dir)):
        if not filename.endswith((".html", ".hmtl")):
            continue
        path = os.path.join(templates_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        for form_match in re.finditer(
            r'<form\b[^>]*\bmethod\s*=\s*["\']post["\'][^>]*>', content, re.IGNORECASE
        ):
            action_match = re.search(r'action\s*=\s*["\']([^"\']*)["\']', form_match.group(0))
            action = action_match.group(1) if action_match else ""

            if action in exempt_actions:
                continue

            checked += 1
            # The CSRF field must appear somewhere after this <form ...>
            # tag and before the corresponding </form> - a generous but
            # sufficient check is "appears within the next 800 characters",
            # since every form in this codebase is short.
            window = content[form_match.end():form_match.end() + 800]
            if "csrf_input(request)" not in window:
                missing.append(f"{filename}: <form action=\"{action}\">")

    check(
        f"every protected POST form across templates/ has csrf_input(request) ({checked} forms checked)",
        len(missing) == 0,
        f"missing CSRF field in: {missing}",
    )
    check(
        "at least the expected number of protected POST forms were actually found (sanity check against a no-op scan)",
        checked >= 20,
        f"only found {checked} protected POST forms - expected at least 20",
    )


def main():
    test_session_token_round_trip()
    test_tampered_session_token_rejected()
    test_expired_session_token_rejected()
    test_token_signed_with_wrong_key_rejected()
    test_missing_or_empty_token_rejected()
    test_missing_session_secret_key_fails_safely()

    test_verify_credentials_correct()
    test_verify_credentials_wrong_password()
    test_verify_credentials_wrong_username()
    test_verify_credentials_empty_input()
    test_missing_dashboard_credentials_fails_safely()

    test_csrf_valid_pair_accepted()
    test_csrf_mismatched_pair_rejected()
    test_csrf_missing_pieces_rejected()
    test_csrf_tokens_are_distinct_per_call()
    test_csrf_input_renders_expected_hidden_field()
    test_csrf_input_escapes_cookie_value()

    test_unauthenticated_html_route_redirects_to_login()
    test_unauthenticated_emails_json_returns_401()
    test_unauthenticated_dashboard_data_returns_401()
    test_login_page_is_public()
    test_login_with_correct_credentials_succeeds_and_sets_cookie()
    test_login_with_wrong_credentials_rejected_no_cookie()
    test_authenticated_request_succeeds()
    test_logout_clears_session_and_blocks_further_access()
    test_tampered_cookie_rejected_end_to_end()
    test_mutation_without_csrf_token_rejected()
    test_mutation_with_invalid_csrf_token_rejected()
    test_mutation_with_valid_csrf_token_allowed()
    test_submit_enquiry_remains_public_no_session_no_csrf()
    test_gmail_webhook_remains_public_no_session_no_csrf()

    test_main_py_registers_auth_middleware()
    test_main_py_public_paths_contains_exactly_the_required_set()
    test_main_py_defines_login_and_logout_routes()
    test_main_py_static_mount_unchanged()
    test_main_py_registers_csrf_jinja_global_on_both_templates_instances()

    test_every_protected_post_form_has_csrf_field()

    _restore_env()

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {_failures}")
        sys.exit(1)
    else:
        print("All tests passed.")


if __name__ == "__main__":
    main()
