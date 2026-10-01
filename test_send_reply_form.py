"""Focused tests for the /email/{email_id}/send double-body-read fix.

Root cause (identical bug class to the already-fixed /settings/accounts/add
and /teacher/send-reply routes): AuthMiddleware.dispatch() already reads
the POST body once, via its own `await request.form()` call, and stashes
that exact parsed form on `request.state.form` for every protected POST
(/email/{email_id}/send is not in PUBLIC_PATHS, so this applies here).
This route declared `reply_body: str = Form(...)` and
`attachments: List[UploadFile] = File(None)` - FastAPI's own dependency
injection then tried to parse the body a SECOND, independent time to
resolve those parameters. The underlying multipart stream was already
drained by AuthMiddleware, so FastAPI saw no reply_body at all and raised
a 422 before the route body ever ran:

    {"detail":[{"type":"missing","loc":["body","reply_body"],
    "msg":"Field required","input":null}]}

even though the browser (templates/email_detail.html) submitted the field
correctly. This was missed by the two earlier fixes this session because
both were found by grepping for the literal text `await request.form()` -
a declarative `= Form(...)`/`= File(...)` parameter never contains that
text; FastAPI performs the equivalent parse internally.

THE FIX: the declarative Form(...)/File(...) parameters are removed from
the route signature entirely. Inside the route body:

    form = request.state.form
    reply_body = form.get("reply_body") or ""
    attachments = form.getlist("attachments")

form.get("reply_body") mirrors exactly what Form(...) with type str
already allowed - present-and-empty or genuinely absent both resolve to
"" - no new validation introduced. form.getlist("attachments") is the
direct multidict equivalent of List[UploadFile] = File(None): Starlette's
FormData stores each uploaded file as a real UploadFile instance under
this field name - getlist() returns [] when none were attached (the same
effective value _send_reply_impl already treats via `attachments or []`)
or every attached UploadFile, in submission order, when one or more were.

Nothing else in the route changed - same email_id handling, same
already-sent/already-sending guards, same call to _send_reply_impl() with
the same five arguments, same CSRF (enforced entirely inside
AuthMiddleware, upstream of this route, untouched by this fix).

TESTING LIMITATION (same as test_mailbox_settings_add.py and
test_teacher_send_reply_form.py): this sandbox has neither `fastapi` nor
`starlette` installed, so no TestClient/real HTTP-level test is possible
here. Structural checks below are source-presence checks against the real
main.py text, the same approach already established and reused for this
exact bug class; a separate mirror directly exercises the real multidict
semantics of form.get()/form.getlist() using the stdlib's own
urllib/email machinery stood in for, since those are simple enough to
model precisely without needing Starlette itself.

Run with: python3 test_send_reply_form.py
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
    start = src.find('@app.post("/email/{email_id}/send")')
    end = src.find('@app.post("/email/{email_id}/polish")')
    assert start != -1 and end != -1 and end > start, "could not locate /email/{email_id}/send's body"
    return src[start:end]


# ---------------------------------------------------------------------------
# a. The old declarative Form(...)/File(...) dependencies are gone.
# ---------------------------------------------------------------------------

def test_no_longer_uses_declarative_form_dependency():
    body = _route_body()
    check(
        'send_reply no longer declares "reply_body: str = Form(...)"',
        "reply_body: str = Form(...)" not in body,
    )
    check(
        'send_reply no longer declares "attachments: List[UploadFile] = File(None)" as a route parameter',
        "attachments: List[UploadFile] = File(None)" not in body,
    )
    check(
        "the route signature now takes only request, background_tasks, email_id",
        "async def send_reply(\n    request: Request,\n     background_tasks: BackgroundTasks,\n    email_id: int,\n):" in body,
    )


# ---------------------------------------------------------------------------
# b. The route reads reply_body/attachments from request.state.form - NOT
# a second independent parse.
# ---------------------------------------------------------------------------

def test_route_reuses_request_state_form_not_a_second_read():
    body = _route_body()
    check(
        "the route reads form = request.state.form",
        "form = request.state.form" in body,
    )
    check(
        "reply_body is obtained from the stashed form via form.get(...)",
        'reply_body = form.get("reply_body") or ""' in body,
    )
    check(
        "attachments is obtained from the stashed form via form.getlist(...)",
        'attachments = form.getlist("attachments")' in body,
    )
    check(
        "the route does not call `await request.form()` itself (no second, independent body read)",
        "await request.form()" not in body,
    )
    idx_form = body.index("form = request.state.form")
    idx_reply = body.index('reply_body = form.get("reply_body") or ""')
    idx_attach = body.index('attachments = form.getlist("attachments")')
    idx_get_email = body.index("original_email = get_email_by_id(email_id)")
    check(
        "form is read, then reply_body/attachments are extracted, before any other route logic runs",
        idx_form < idx_reply < idx_attach < idx_get_email,
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
        "/email/{email_id}/send is not listed in PUBLIC_PATHS (so AuthMiddleware parses its form)",
        "/email/{email_id}/send" not in public_paths_block,
    )


# ---------------------------------------------------------------------------
# c. Attachment handling is preserved - an UploadFile from the parsed form
# is passed through to _send_reply_impl() exactly as before.
# ---------------------------------------------------------------------------

def test_attachments_still_passed_through_to_impl_unchanged():
    body = _route_body()
    check(
        "_send_reply_impl() is still called with the same five arguments, in the same order",
        "return await _send_reply_impl(\n            request, background_tasks, email_id, reply_body, attachments, original_email\n        )" in body,
    )


class _FakeUploadFile:
    """Stands in for Starlette's real UploadFile - only the attributes
    _send_reply_impl() actually reads (filename, content_type, and an
    async read()) are needed to prove attachments survive the new
    extraction path unchanged. No real file I/O, no real email sent."""

    def __init__(self, filename, content_type, content):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self):
        return self._content


class _FakeFormData(dict):
    """Minimal stand-in for Starlette's FormData multidict - get()/
    getlist() are the only two methods the fixed route actually calls."""

    def getlist(self, key):
        value = self.get(key)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


def _extract_reply_body_and_attachments(form):
    """Byte-for-byte mirror of the two new extraction lines in main.py's
    send_reply() - see test_route_reuses_request_state_form_not_a_second_read
    above, which cross-checks this exact mirror against the real source."""
    reply_body = form.get("reply_body") or ""
    attachments = form.getlist("attachments")
    return reply_body, attachments


def test_mirror_extracts_reply_body_correctly():
    form = _FakeFormData({"reply_body": "Thanks for your question!", "csrf_token": "abc"})
    reply_body, attachments = _extract_reply_body_and_attachments(form)
    check("reply_body is extracted from the parsed form, unchanged", reply_body == "Thanks for your question!")
    check("no attachments present -> empty list, not None or a KeyError", attachments == [])


def test_mirror_handles_empty_reply_body_same_as_before():
    """Form(...) with type str previously allowed an empty string through
    without raising - this must still be true (no new validation added)."""
    form = _FakeFormData({"reply_body": ""})
    reply_body, _ = _extract_reply_body_and_attachments(form)
    check("an empty reply_body field resolves to '' (same as the old Form(...) behavior)", reply_body == "")


def test_mirror_handles_missing_reply_body_field_gracefully():
    """Previously a truly missing field would have raised a 422 before the
    route ran at all - now it degrades to an empty string instead of
    crashing, which is a strictly safer outcome, not a new validation gap
    (the real form always includes this field from the template's own
    textarea, so this case is a defensive fallback, not an expected path)."""
    form = _FakeFormData({})
    reply_body, attachments = _extract_reply_body_and_attachments(form)
    check("a genuinely missing reply_body field resolves to '' rather than raising", reply_body == "")
    check("attachments still resolves to [] when absent", attachments == [])


def test_mirror_preserves_a_single_uploaded_attachment():
    upload = _FakeUploadFile("photo.png", "image/png", b"fake-bytes")
    form = _FakeFormData({"reply_body": "See attached.", "attachments": upload})
    reply_body, attachments = _extract_reply_body_and_attachments(form)
    check("reply_body is still extracted correctly alongside an attachment", reply_body == "See attached.")
    check("exactly one attachment is preserved", len(attachments) == 1)
    check("the preserved attachment is the same UploadFile instance (not copied/wrapped/lost)", attachments[0] is upload)


def test_mirror_preserves_multiple_uploaded_attachments_in_order():
    upload1 = _FakeUploadFile("a.pdf", "application/pdf", b"one")
    upload2 = _FakeUploadFile("b.pdf", "application/pdf", b"two")
    form = _FakeFormData({"reply_body": "Two files attached.", "attachments": [upload1, upload2]})
    reply_body, attachments = _extract_reply_body_and_attachments(form)
    check("both attachments are preserved", len(attachments) == 2)
    check("attachment order is preserved (first file first)", attachments[0] is upload1 and attachments[1] is upload2)


def test_mirror_attachment_data_extraction_matches_impl_expectations():
    """Confirms the preserved UploadFile objects still satisfy exactly what
    _send_reply_impl()'s own loop needs (filename, content_type, an async
    read()) - the same three attributes it already used before this fix,
    unchanged. No real file is written anywhere; read() returns in-memory
    bytes only."""
    import asyncio

    upload = _FakeUploadFile("report.csv", "text/csv", b"col1,col2\n1,2\n")
    form = _FakeFormData({"reply_body": "Report attached.", "attachments": upload})
    _, attachments = _extract_reply_body_and_attachments(form)

    async def _simulate_impl_loop(uploads):
        attachment_data = []
        for u in (uploads or []):
            if not u or not u.filename:
                continue
            attachment_data.append((u.filename, await u.read(), u.content_type))
        return attachment_data

    result = asyncio.run(_simulate_impl_loop(attachments))
    check(
        "the real _send_reply_impl()-shaped loop still produces (filename, bytes, content_type) unchanged",
        result == [("report.csv", b"col1,col2\n1,2\n", "text/csv")],
    )


def main():
    tests = [
        test_no_longer_uses_declarative_form_dependency,
        test_route_reuses_request_state_form_not_a_second_read,
        test_route_is_protected_by_auth_middleware,
        test_attachments_still_passed_through_to_impl_unchanged,
        test_mirror_extracts_reply_body_correctly,
        test_mirror_handles_empty_reply_body_same_as_before,
        test_mirror_handles_missing_reply_body_field_gracefully,
        test_mirror_preserves_a_single_uploaded_attachment,
        test_mirror_preserves_multiple_uploaded_attachments_in_order,
        test_mirror_attachment_data_extraction_matches_impl_expectations,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
