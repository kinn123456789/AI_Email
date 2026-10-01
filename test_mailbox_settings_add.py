"""Focused tests for the /settings/accounts/add "email field missing"
production bug fix.

Root cause history (see the two read-only investigations this fix was
approved from):

1. AuthMiddleware.dispatch() reads the POST body once, via its own
   `await request.form()` call, purely to extract csrf_token on every
   protected POST. The route originally declared a separate
   `email: str = Form(...)` parameter, which triggered a SECOND,
   independent parse of the same body by FastAPI's own dependency
   injection - and that second parse was losing the "email" field in
   production, producing a raw 422:
       {"detail":[{"type":"missing","loc":["body","email"],"msg":"Field required","input":null}]}

2. A first fix (commit 41d718c) changed the route to call
   `await request.form()` itself instead of declaring `Form(...)`. This
   did NOT actually remove the second, independent body read - it just
   changed how that second read was written, and a missing "email"
   field was now caught gracefully instead of raising, producing a
   DIFFERENT but still-wrong symptom: the app's own "Enter a valid
   email address" message, even for a genuinely valid address.

THE ACTUAL FIX (this file tests): eliminate the second read entirely.
AuthMiddleware.dispatch() now stashes its own already-successful parsed
form on `request.state.form` right after computing it. add_settings_account()
reads `request.state.form` instead of ever calling `request.form()`
itself - so the request body is read exactly once per request, by the
middleware, and reused everywhere downstream that needs it.

Every other line of the route (validation, Gmail access check,
add_email_account(), register_watch(), the three redirect shapes) is
unchanged.

TESTING LIMITATION (explicitly documented, not worked around): this
sandbox has neither `fastapi` nor `starlette` installed (verified via
`python3 -c "import fastapi"` / `import starlette` at review time - both
raise ModuleNotFoundError), so no `TestClient`/real HTTP request-level
test is possible here, and none was added. Per instructions, no package
was installed to work around this. Every check below is a structural/
source-presence check against the real main.py/database.py/
templates/settings.html files - the same technique every other test file
touching main.py in this repo already uses (main.py itself can't be
imported: it starts real scheduler.py background jobs and needs
fastapi/apscheduler). A genuine integration test (a real TestClient POST
with `csrf_token`/`email` form data, asserting the response, that
`get_gmail_service`/`add_email_account`/`register_watch` were called
with the expected value via mocks, and that no real Gmail/DB call
occurred) would be materially stronger and is recommended as a follow-up
once those packages are available in whatever environment actually runs
this suite in CI/production.

Matches this repo's existing test_*.py convention: a plain script using
only assert statements and the standard library - no pytest.

Run with: python3 test_mailbox_settings_add.py
"""

import os
import re
import subprocess
import sys


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


def _read_source(filename):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename), "r", encoding="utf-8") as f:
        return f.read()


def _route_body():
    src = _read_source("main.py")
    start = src.find('@app.post("/settings/accounts/add")')
    end = src.find('@app.post("/settings/accounts/{account_id}/delete")')
    assert start != -1 and end != -1 and end > start, "could not locate add_settings_account()'s body"
    return src[start:end]


def _middleware_body():
    src = _read_source("main.py")
    start = src.find("class AuthMiddleware(BaseHTTPMiddleware):")
    end = src.find("app.add_middleware(AuthMiddleware)")
    assert start != -1 and end != -1 and end > start, "could not locate AuthMiddleware's body"
    return src[start:end]


# ---------------------------------------------------------------------------
# a. The old Form(...) dependency is gone.
# ---------------------------------------------------------------------------

def test_no_longer_uses_declarative_form_dependency():
    body = _route_body()
    check('add_settings_account no longer declares "email: str = Form(...)"',
          "email: str = Form(...)" not in body)
    # Signature updated by the mailbox history onboarding fix (a later,
    # separately-approved task): add_settings_account() now also takes
    # background_tasks: BackgroundTasks, used to schedule one-time history
    # onboarding for a genuinely new mailbox. Still takes request: Request
    # first, unchanged - only a second parameter was added.
    check("the route signature still takes request: Request (now alongside background_tasks: BackgroundTasks)",
          "async def add_settings_account(request: Request, background_tasks: BackgroundTasks):" in body)


# ---------------------------------------------------------------------------
# b. The route reads email using request.state.form - NOT a second
# request.form() call of its own.
# ---------------------------------------------------------------------------

def test_middleware_stashes_form_on_request_state():
    mw = _middleware_body()
    check("AuthMiddleware still does its own single await request.form() call for CSRF",
          "form = await request.form()" in mw)
    check("that exact parsed form is stashed onto request.state.form",
          "request.state.form = form" in mw)
    # Ordering: the stash must happen using the SAME `form` variable CSRF
    # itself uses, and before CSRF is verified (so even a CSRF failure
    # doesn't matter - the stash is unconditional on the request having
    # reached this point at all, which is what add_settings_account()
    # depends on).
    idx_form = mw.index("form = await request.form()")
    idx_stash = mw.index("request.state.form = form")
    idx_csrf_get = mw.index("csrf_form_value = form.get(auth.CSRF_FORM_FIELD)")
    check("stash happens right after the parse, before the csrf_form_value lookup",
          idx_form < idx_stash < idx_csrf_get)
    check("CSRF validation logic itself is byte-for-byte unchanged",
          "csrf_form_value = form.get(auth.CSRF_FORM_FIELD)" in mw
          and "if not auth.verify_csrf(csrf_cookie, csrf_form_value):" in mw
          and 'return JSONResponse(status_code=403, content={"detail": "Invalid CSRF token"})' in mw)


def test_route_reuses_request_state_form_not_a_second_read():
    body = _route_body()
    check("the route reads form = request.state.form",
          "form = request.state.form" in body)
    # Checks the actual executable code shape ("<name> = await
    # request.form()") rather than a bare "request.form()" substring,
    # which would also match this route's own explanatory comment
    # describing what the middleware does elsewhere - a real second read
    # would appear as exactly this assignment pattern.
    check("the route does NOT itself call `= await request.form()` anywhere (no second body read)",
          "= await request.form()" not in body)
    check('email is pulled from the reused form via form.get("email")',
          'form.get("email")' in body)


# ---------------------------------------------------------------------------
# c. trim/lowercase preserved.
# ---------------------------------------------------------------------------

def test_email_still_stripped_and_lowercased():
    body = _route_body()
    check('email is still .strip().lower()-ed exactly as before',
          '.strip().lower()' in body)
    check("the strip/lower happens on the reused-form-extracted value",
          'email = (form.get("email") or "").strip().lower()' in body)


# ---------------------------------------------------------------------------
# d. existing error/success redirect behavior is byte-for-byte preserved.
# ---------------------------------------------------------------------------

def test_existing_redirects_preserved():
    body = _route_body()
    check('invalid-email redirect unchanged ("Enter a valid email address")',
          'url="/settings?error=Enter a valid email address"' in body
          and "status_code=303" in body)
    check("the invalid-email guard condition is unchanged",
          'if not email or "@" not in email:' in body)
    check("Gmail-access-failure redirect unchanged (same f-string shape)",
          'url=f"/settings?error=Could not access {email} - {str(e)[:150]}"' in body)
    check("success redirect unchanged (?added=)",
          'url=f"/settings?added={email}"' in body)
    check("exactly 3 RedirectResponse(...) call sites remain in this route",
          body.count("RedirectResponse(") == 3, f"got {body.count('RedirectResponse(')}")


# ---------------------------------------------------------------------------
# e. add_email_account()/register_watch() (and the Gmail-reachability
# check that gates them) are still present and in the same order.
# ---------------------------------------------------------------------------

def test_add_email_account_and_register_watch_preserved():
    body = _route_body()
    check("get_gmail_service(email) reachability check is still present",
          "service = get_gmail_service(email)" in body
          and "service.users().getProfile(userId=" in body)
    check("add_email_account(email) is still called", "add_email_account(email)" in body)
    check("register_watch(email) is still called, still best-effort "
          '(wrapped in its own try/except that only prints on failure)',
          "register_watch(email)" in body
          and 'print(f"Could not register watch for new account {email}: {e}")' in body)
    idx_validate = body.index('if not email or "@" not in email:')
    idx_gmail = body.index("get_gmail_service(email)")
    idx_add = body.index("add_email_account(email)")
    idx_watch = body.index("register_watch(email)")
    idx_success = body.index('url=f"/settings?added={email}"')
    check("call order is unchanged: validate -> Gmail check -> add_email_account -> register_watch -> success redirect",
          idx_validate < idx_gmail < idx_add < idx_watch < idx_success)


# ---------------------------------------------------------------------------
# f. CORE_EMAIL_ACCOUNTS (the 3 existing hardcoded mailboxes) untouched.
# ---------------------------------------------------------------------------

def test_core_email_accounts_untouched():
    db_src = _read_source("database.py")
    check('CORE_EMAIL_ACCOUNTS still hardcodes exactly EMAIL_1/EMAIL_2/EMAIL_3',
          '{"email": os.getenv("EMAIL_1"), "source": "support@coralacademy.com", "core": True}' in db_src
          and '{"email": os.getenv("EMAIL_2"), "source": "lucy@coralacademy.com", "core": True}' in db_src
          and '{"email": os.getenv("EMAIL_3"), "source": "engineering@coralacademy.com", "core": True}' in db_src)
    check("add_settings_account never references CORE_EMAIL_ACCOUNTS or EMAIL_1/2/3 directly",
          all(s not in _route_body() for s in ["CORE_EMAIL_ACCOUNTS", "EMAIL_1", "EMAIL_2", "EMAIL_3"]))
    check("database.py itself was not touched by this fix",
          "def add_email_account(email, source_label=None):" in db_src
          and 'INSERT INTO email_accounts (email, source_label)' in db_src)


# ---------------------------------------------------------------------------
# g. No DB/schema/Coral changes were introduced by this fix.
# ---------------------------------------------------------------------------

def test_no_db_schema_or_coral_changes():
    check("database.py contains no ALTER/CREATE/DROP TABLE statement touching email_accounts",
          not re.search(r"(ALTER|CREATE|DROP)\s+TABLE\s+.*email_accounts", _read_source("database.py"), re.IGNORECASE))
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    )
    new_or_changed_sql_files = [
        line for line in result.stdout.splitlines()
        if line.strip().lower().endswith(".sql")
    ]
    check("this fix did not add or modify any .sql migration file",
          not new_or_changed_sql_files, f"got {new_or_changed_sql_files!r}")
    check("the fixed route contains no SQL of its own (all DB access still goes through add_email_account())",
          "cursor.execute" not in _route_body() and "INSERT INTO" not in _route_body())


# ---------------------------------------------------------------------------
# Other protected POST routes are not accidentally affected by the new
# request.state.form stash - it's purely additive to the middleware, and
# every other route's own Form(...)-based parameter handling is untouched.
# ---------------------------------------------------------------------------

def test_other_post_routes_unaffected():
    src = _read_source("main.py")
    # Checks the actual executable code shapes (not a bare substring
    # count, which would also match this fix's own explanatory comments)
    # so the assertion stays precise regardless of prose wording: exactly
    # one real write (the middleware's stash) exists anywhere in main.py -
    # no route was wired to write request.state, accidentally or otherwise
    # (there is, and should only ever be, one place that parses the body
    # and stashes it).
    check("exactly one real write to request.state.form in the whole file (the middleware's stash)",
          src.count("request.state.form = form") == 1, f"got {src.count('request.state.form = form')}")
    # Reads are a different story: 2 is correct here, not 1 - the AI
    # Polish Phase 1 route (a later, separately-approved task) legitimately
    # reuses the exact same request.state.form pattern this fix
    # established, for the exact same reason (avoiding a second,
    # independent body read). Any additional protected POST route that
    # needs the parsed form is expected to keep reusing this pattern
    # rather than reading the body itself - the count is expected to grow
    # as more routes adopt it, not stay pinned at 1 forever.
    check("at least one real read of request.state.form exists (this fix's own route)",
          src.count("form = request.state.form") >= 1, f"got {src.count('form = request.state.form')}")
    # A representative sample of other Form(...)-based protected POST
    # routes, confirmed still declared exactly as before - this change
    # only ever ADDS an attribute to request.state; it never alters how
    # FastAPI resolves any other route's own parameters.
    for signature in [
        "reply_body: str = Form(...)",
        "email_ids: list[int] = Form(...)",
        "chat_id: str = Form(...)",
        "row_keys: list[str] = Form(...), show_all: str = Form(None)",
    ]:
        check(f'other route signature "{signature}" is untouched',
              signature in src)
    check("AuthMiddleware's own dispatch() still ends by calling call_next(request) unconditionally "
          "for every authenticated request (public-path and non-POST requests never touch request.state.form)",
          "return await call_next(request)" in _middleware_body())


# ---------------------------------------------------------------------------
# Settings.html itself was not touched (explicit safety rule).
# ---------------------------------------------------------------------------

def test_settings_html_untouched():
    html = _read_source("templates/settings.html")
    check('the form still posts to /settings/accounts/add',
          '<form method="post" action="/settings/accounts/add"' in html)
    check('the email input is still named "email"',
          '<input type="email" name="email" required' in html)
    check("csrf_input(request) is still emitted inside the form",
          "{{ csrf_input(request) }}" in html)


def main():
    print("NOTE: fastapi/starlette are not installed in this environment "
          "(verified at review time) - no TestClient/real-request test was "
          "possible or attempted. All checks below are structural/source "
          "checks. See this file's module docstring for the recommended "
          "follow-up integration test.\n")

    tests = [
        test_no_longer_uses_declarative_form_dependency,
        test_middleware_stashes_form_on_request_state,
        test_route_reuses_request_state_form_not_a_second_read,
        test_email_still_stripped_and_lowercased,
        test_existing_redirects_preserved,
        test_add_email_account_and_register_watch_preserved,
        test_core_email_accounts_untouched,
        test_no_db_schema_or_coral_changes,
        test_other_post_routes_unaffected,
        test_settings_html_untouched,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
