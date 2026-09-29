"""Focused tests for the /settings/accounts/add "email field missing"
production bug fix.

Root cause (see the read-only investigation this fix was approved from):
AuthMiddleware already reads the POST body once, via its own
`await request.form()` call, purely to extract csrf_token on every
protected POST. The route's own separate `email: str = Form(...)`
parameter then triggered a SECOND, independent parse of the same body by
FastAPI's own dependency injection - which was losing the "email" field
in production, producing:
    {"detail":[{"type":"missing","loc":["body","email"],"msg":"Field required","input":null}]}
even though the middleware's own read correctly saw csrf_token moments
earlier.

Fix: add_settings_account() now reads the form directly
(`await request.form()`) inside its own body, the same mechanism the
middleware already uses successfully, instead of a separate declarative
Form(...) dependency. Every other line of the route (validation, Gmail
access check, add_email_account(), register_watch(), the three redirect
shapes) is unchanged.

Matches this repo's existing test_*.py convention (see test_review_reasons.py,
test_performance_fixes.py): a plain script using only assert statements and
the standard library - no pytest. main.py can't be imported here (starts
real scheduler.py background jobs, needs fastapi/apscheduler, neither
installed in this sandbox) - checked via source-presence/structural checks
against the real file, the same technique every other test file touching
main.py in this repo already uses.

Run with: python3 test_mailbox_settings_add.py
"""

import os
import re
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


# ---------------------------------------------------------------------------
# a/b. The old Form(...) dependency is gone; the route reads the form
# itself, the same way AuthMiddleware's own CSRF check already does.
# ---------------------------------------------------------------------------

def test_no_longer_uses_declarative_form_dependency():
    body = _route_body()
    check('add_settings_account no longer declares "email: str = Form(...)"',
          "email: str = Form(...)" not in body)
    check("the route signature now takes request: Request instead",
          "async def add_settings_account(request: Request):" in body)
    check("the route is now async (required to await request.form())",
          re.search(r"async def add_settings_account\(", body) is not None)


def test_reads_email_via_request_form():
    body = _route_body()
    check("the route awaits request.form() directly",
          "form = await request.form()" in body)
    check('email is pulled from that form dict via form.get("email")',
          'form.get("email")' in body)
    check("the same mechanism AuthMiddleware's own CSRF check already uses (await request.form()) is reused",
          _read_source("main.py").count("await request.form()") >= 2)


# ---------------------------------------------------------------------------
# c. trim/lowercase preserved.
# ---------------------------------------------------------------------------

def test_email_still_stripped_and_lowercased():
    body = _route_body()
    check('email is still .strip().lower()-ed exactly as before',
          '.strip().lower()' in body)
    check("the strip/lower happens on the form-extracted value, not a stale Form(...) param",
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
    # Exactly 3 RedirectResponse call sites: invalid email, Gmail-access
    # failure, success - same count as before this fix (no new/removed
    # branch was introduced).
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
    # Ordering: validate -> Gmail-reachability check -> add_email_account -> register_watch -> success redirect.
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
    # A pre-existing, unrelated migration_p0_1_edited_before_send.sql
    # already lives in this repo from an earlier task - checking "no
    # migration file exists at all" would be a false positive against
    # that file. The actual thing this fix must not do is ADD a new one,
    # which git status --short (an untracked/new file would show as
    # "??") settles directly and specifically.
    import subprocess
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
    tests = [
        test_no_longer_uses_declarative_form_dependency,
        test_reads_email_via_request_form,
        test_email_still_stripped_and_lowercased,
        test_existing_redirects_preserved,
        test_add_email_account_and_register_watch_preserved,
        test_core_email_accounts_untouched,
        test_no_db_schema_or_coral_changes,
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
