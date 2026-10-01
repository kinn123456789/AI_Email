"""Focused tests for the /teacher/send-reply double-body-read fix (final
pre-freeze audit finding A1).

Root cause (identical bug class to the already-fixed /settings/accounts/add
and /email/{email_id}/polish routes): AuthMiddleware.dispatch() already
reads the POST body once, via its own `await request.form()` call, and
stashes that exact parsed form on `request.state.form` for every protected
POST (/teacher/send-reply is not in PUBLIC_PATHS, so this applies here).
This route ignored that and called `await request.form()` again itself -
a second, independent read of an already-consumed ASGI body stream. Unlike
the original mailbox-add bug (which surfaced as a raised 422 via a
declarative Form(...) dependency), this route reads fields via
form.get(...), so the failure mode was silent: empty/None values rather
than a visible error.

THE FIX: `form = await request.form()` -> `form = request.state.form`.
Nothing else in the route changed - same field reads (chat_id, teacher_id,
message_id, reply), same fallback-from-referer logic, same
send_teacher_reply()/mark_reply_sent() calls, same CSRF/auth (both already
enforced entirely inside AuthMiddleware, upstream of this route, and
untouched by this fix).

TESTING LIMITATION (same as test_mailbox_settings_add.py and
test_reply_polish.py): this sandbox has neither `fastapi` nor `starlette`
installed, so no TestClient/real HTTP-level test is possible here. Every
check below is a structural/source-presence check against the real
main.py text - the same approach already established and reused twice in
this codebase for this exact bug class.

Run with: python3 test_teacher_send_reply_form.py
"""

import os
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
    start = src.find('@app.post("/teacher/send-reply")')
    end = src.find('@app.post("/teacher/delete-message")')
    assert start != -1 and end != -1 and end > start, "could not locate /teacher/send-reply's body"
    return src[start:end]


# ---------------------------------------------------------------------------
# The fix itself: reuses request.state.form, never reads the body again.
# ---------------------------------------------------------------------------

def test_route_uses_request_state_form():
    body = _route_body()
    check(
        "the route reads form = request.state.form (reuses AuthMiddleware's already-parsed form)",
        "form = request.state.form" in body,
    )


def test_route_does_not_call_request_form_again():
    body = _route_body()
    check(
        "the route no longer calls `await request.form()` itself (no second, independent body read)",
        "await request.form()" not in body,
    )


def test_route_is_protected_by_auth_middleware():
    """Confirms the premise the fix relies on: this route is NOT a public
    path, so AuthMiddleware.dispatch() does in fact parse its form and
    stash request.state.form before this route ever runs."""
    src = _read_source("main.py")
    public_paths_start = src.index("PUBLIC_PATHS = {")
    public_paths_end = src.index("}", public_paths_start)
    public_paths_block = src[public_paths_start:public_paths_end]
    check(
        "/teacher/send-reply is not listed in PUBLIC_PATHS (so AuthMiddleware parses its form)",
        "/teacher/send-reply" not in public_paths_block,
    )


# ---------------------------------------------------------------------------
# Every existing field read and the surrounding logic is preserved exactly.
# ---------------------------------------------------------------------------

def test_all_existing_field_reads_preserved():
    body = _route_body()
    for expected in [
        'chat_id = form.get("chat_id")',
        'teacher_id = form.get("teacher_id")',
        'message_id = form.get("message_id")',
        'reply = form.get("reply", "").strip()',
    ]:
        check(f"field read preserved: {expected}", expected in body)


def test_referer_fallback_logic_preserved():
    body = _route_body()
    check(
        "the chat_id/teacher_id referer-recovery fallback is unchanged",
        'if chat_id in (None, "", "None") or teacher_id in (None, "", "None"):' in body
        and 'query = parse_qs(urlparse(referer).query)' in body,
    )


def test_send_logic_unchanged():
    body = _route_body()
    check(
        "empty-reply short-circuit (no send attempted) is unchanged",
        "if not reply:" in body
        and 'url=f"/teacher-inbox?teacher_id={teacher_id}&chat_id={chat_id}"' in body,
    )
    check(
        "send_teacher_reply() is still called with the same three arguments",
        "result = send_teacher_reply(" in body
        and "chat_id=chat_id," in body
        and "teacher_id=teacher_id," in body
        and "message=reply" in body,
    )
    check(
        "mark_reply_sent(message_id) is still called on success when message_id is present",
        "mark_reply_sent(message_id)" in body,
    )
    check(
        "the raw Teacher Portal API response is still never logged (pre-existing privacy guard, untouched)",
        'result["data"]' not in body or "Never log result[\"data\"]" in body,
    )


def test_missing_ids_error_response_unchanged():
    body = _route_body()
    check(
        "the missing chat_id/teacher_id error response is unchanged",
        '"error": "Missing chat_id or teacher_id. Open a specific chat before sending."' in body,
    )


# ---------------------------------------------------------------------------
# Scope guard: only the one intended line changed in main.py for this fix.
# CSRF/auth logic (AuthMiddleware itself) and database.py are untouched.
# ---------------------------------------------------------------------------

def test_auth_middleware_itself_is_unmodified_by_this_fix():
    """This fix only changes how /teacher/send-reply CONSUMES the already-
    parsed form - it must not touch AuthMiddleware's own parsing/stashing
    logic at all."""
    src = _read_source("main.py")
    check(
        "AuthMiddleware still stashes the parsed form exactly once, the same way it already did",
        src.count("request.state.form = form") == 1,
        f"got {src.count('request.state.form = form')}",
    )


def test_no_db_schema_or_coral_changes():
    """This is a request-parsing fix only - no new database call, no new
    import, no reference to Coral/Supabase anywhere in the changed route."""
    body = _route_body()
    check("no new database import/call introduced in this route", "database." not in body and "db_pool" not in body)
    check("no Coral/Supabase reference anywhere in this route", "coral" not in body.lower() and "supabase" not in body.lower())


def main():
    tests = [
        test_route_uses_request_state_form,
        test_route_does_not_call_request_form_again,
        test_route_is_protected_by_auth_middleware,
        test_all_existing_field_reads_preserved,
        test_referer_fallback_logic_preserved,
        test_send_logic_unchanged,
        test_missing_ids_error_response_unchanged,
        test_auth_middleware_itself_is_unmodified_by_this_fix,
        test_no_db_schema_or_coral_changes,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
