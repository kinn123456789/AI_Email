"""Focused tests for two P0 dashboard-audit fixes:

P0-2 - misleading classification confidence display (templates/email_detail.html,
       templates/category.html)
P0-6 - PII logged to stdout (main.py, reply_generator.py)

Matches this repo's existing test_*.py convention (see test_accuracy_fixes.py):
a plain script using only assert statements and the standard library plus
whatever's already installed - no pytest. A separate, new file rather than
touching test_accuracy_fixes.py.

TWO KINDS OF CHECK HERE, FOR TWO DIFFERENT REASONS:

1. reply_generator.py IS imported and exercised FOR REAL, with the same
   fake openai/dotenv/psycopg2 modules test_accuracy_fixes.py already
   uses - generate_reply() is actually called with a body/subject/reply
   containing a unique marker string, stdout is captured for the whole
   call, and the test asserts the marker never appears in it. This is a
   genuine runtime check, not a source-text search.

2. main.py cannot be imported in this environment (it transitively starts
   real scheduler.py background jobs at module import time - see
   test_authentication.py's own docstring for the full reasoning), so its
   fixes are verified with plain source-level string checks: the specific
   unsafe print(...) statements that used to exist are confirmed absent,
   and their safe replacements are confirmed present. Same technique as
   test_accuracy_fixes.py's own M1-M3 checks and test_authentication.py's
   Layer 3 checks.

Run with: python3 test_p0_fixes.py
"""

import io
import os
import sys
import types
from contextlib import redirect_stdout


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


# ---------------------------------------------------------------------------
# P0-2: templates/email_detail.html and templates/category.html, checked
# as plain text - these are Jinja templates, not Python, so a runtime
# import isn't applicable here.
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


def _read_template(name):
    with open(os.path.join(_TEMPLATES_DIR, name), "r", encoding="utf-8") as f:
        return f.read()


def test_email_detail_uses_classification_confidence_label():
    src = _read_template("email_detail.html")
    check(
        'email_detail.html labels the metric exactly "Classification confidence"',
        "Classification confidence" in src,
    )


def test_email_detail_confidence_value_expression_preserved():
    src = _read_template("email_detail.html")
    check(
        "email_detail.html still renders the real email.ai_confidence value (not a new/invented metric)",
        "{{ email.ai_confidence }}%" in src,
    )


def test_email_detail_no_trust_implying_color_tiers():
    src = _read_template("email_detail.html")
    # The old version color-coded the SAME confidence number
    # emerald/cyan/red by threshold, which is exactly the "safe/risky"
    # visual signal this fix removes. A neutral stone-* class is fine;
    # none of the old trust-implying colors should remain near this metric.
    confidence_block_start = src.find("Classification confidence")
    confidence_block = src[confidence_block_start:confidence_block_start + 400]
    check(
        "no green/red/emerald/cyan trust-implying styling remains around the confidence value",
        not any(
            bad in confidence_block
            for bad in ["text-emerald-600", "text-cyan-700", "text-red-600", "bg-emerald", "bg-rose", "bg-amber"]
        ),
        f"found trust-implying class in: {confidence_block!r}",
    )


def test_email_detail_no_misleading_wording():
    src = _read_template("email_detail.html").lower()
    # None of these phrasings should exist anywhere near a confidence
    # display - they'd imply the classifier's confidence measures whether
    # the drafted ANSWER is correct, which is the exact bug this fix
    # targets (verified live: 92% confidence, requires_review=false, and
    # the drafted price was still wrong).
    for phrase in ["ai confidence", "answer confidence", "accuracy:", "trust:"]:
        check(f'no misleading phrase "{phrase}" in email_detail.html', phrase not in src)


def test_category_html_uses_classification_label():
    src = _read_template("category.html")
    check(
        'category.html labels the metric with "Classification" (honest terminology applied there too)',
        "Classification" in src,
    )


def test_category_html_value_expression_preserved():
    src = _read_template("category.html")
    check(
        "category.html still renders the real email.ai_confidence value",
        "{{ email.ai_confidence }}%" in src,
    )


def test_category_html_no_trust_implying_color_tiers():
    src = _read_template("category.html")
    check(
        "no green/red/emerald/amber/rose trust-implying styling remains around the confidence badge in category.html",
        not any(bad in src for bad in ["bg-emerald-100", "bg-amber-100", "bg-rose-100"]),
    )


def test_dashboard_html_does_not_display_confidence_at_all():
    """Sanity check matching the investigation: dashboard.html never showed
    ai_confidence in the first place, so there's nothing to rename there -
    confirming the fix didn't need to (and didn't) touch it."""
    src = _read_template("dashboard.html")
    check(
        "dashboard.html has no ai_confidence display (unaffected by this fix, as expected)",
        "ai_confidence" not in src,
    )


def test_no_other_template_has_confidence_wording():
    """The full templates/ sweep required by the task - confirms
    email_detail.html and category.html are the ONLY two templates that
    ever mentioned confidence, so no third location was missed."""
    offenders = []
    for filename in sorted(os.listdir(_TEMPLATES_DIR)):
        if not filename.endswith((".html", ".hmtl")):
            continue
        if filename in ("email_detail.html", "category.html"):
            continue
        content = open(os.path.join(_TEMPLATES_DIR, filename), encoding="utf-8").read()
        if "confidence" in content.lower():
            offenders.append(filename)
    check(
        "no template other than email_detail.html/category.html mentions confidence",
        len(offenders) == 0,
        f"found in: {offenders}",
    )


# ---------------------------------------------------------------------------
# P0-6: reply_generator.py - real import, real call, real captured stdout.
# ---------------------------------------------------------------------------

def _install_fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class FakeChatCompletions:
    def __init__(self):
        self._next = None

    def set_next(self, value_or_exception):
        self._next = value_or_exception

    def create(self, **kwargs):
        v = self._next
        if isinstance(v, Exception):
            raise v
        return v


class FakeEmbeddings:
    def create(self, **kwargs):
        return types.SimpleNamespace(data=[types.SimpleNamespace(embedding=[0.1] * 8)])


class FakeOpenAI:
    def __init__(self, *a, **kw):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())
        self.embeddings = FakeEmbeddings()


def _fake_chat_response(content):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))],
        usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20),
    )


class FakeCursor:
    def __init__(self, pool):
        self._pool = pool

    def execute(self, sql, params=None):
        self._pool.last_sql = sql
        self._pool.last_params = params

    def fetchall(self):
        return self._pool.next_fetchall

    def fetchone(self):
        return self._pool.next_fetchone

    def close(self):
        pass


class FakeConnection:
    def __init__(self, pool):
        self._pool = pool

    def cursor(self, cursor_factory=None):
        return FakeCursor(self._pool)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class FakeSimpleConnectionPool:
    def __init__(self, *a, **kw):
        self.next_fetchall = []
        self.next_fetchone = None
        self.last_sql = None
        self.last_params = None

    def getconn(self):
        return FakeConnection(self)

    def putconn(self, conn):
        pass


def _install_fakes():
    _install_fake_module("dotenv", load_dotenv=lambda *a, **kw: None)
    _install_fake_module("openai", OpenAI=FakeOpenAI)

    pool_mod = _install_fake_module("psycopg2.pool", SimpleConnectionPool=FakeSimpleConnectionPool)
    extras_mod = _install_fake_module("psycopg2.extras", RealDictCursor=dict)
    psycopg2_mod = _install_fake_module("psycopg2")
    psycopg2_mod.pool = pool_mod
    psycopg2_mod.extras = extras_mod
    psycopg2_mod.connect = lambda *a, **kw: FakeConnection(FakeSimpleConnectionPool())


_install_fakes()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import reply_generator  # noqa: E402
import database  # noqa: E402

database.db_pool = FakeSimpleConnectionPool()


# Unique, obviously-not-a-real-word markers so a plain substring check in
# captured stdout can't accidentally false-positive on ordinary log text.
_SECRET_SUBJECT = "MARKER_SUBJECT_XK9Q7"
_SECRET_BODY = "MARKER_BODY_child_is_named_Zephyrine_Bloomquist_QZ4"
_SECRET_DRAFT_REPLY = "MARKER_DRAFT_your_account_balance_is_ZQ8"


def test_generate_reply_never_prints_subject_or_body():
    reply_generator.client.chat.completions.set_next(
        _fake_chat_response(f"Thanks for your question. {_SECRET_DRAFT_REPLY}")
    )

    captured = io.StringIO()
    with redirect_stdout(captured):
        reply_text, status = reply_generator.generate_reply(
            gmail_message_id="test-p06-1",
            subject=_SECRET_SUBJECT,
            body=_SECRET_BODY,
            category="General",
            priority="Medium",
            thread_history="",
            historical_emails=[],
            knowledge=[],
        )
    output = captured.getvalue()

    check(
        "generate_reply() still returns the real draft (fix didn't change behavior)",
        status == "ok" and _SECRET_DRAFT_REPLY in reply_text,
        f"got status={status!r} reply_text={reply_text!r}",
    )
    check(
        "the customer's subject is never printed to stdout",
        _SECRET_SUBJECT not in output,
    )
    check(
        "the customer's body (containing a child's name) is never printed to stdout",
        _SECRET_BODY not in output,
    )
    check(
        "the generated draft reply is never printed to stdout",
        _SECRET_DRAFT_REPLY not in output,
    )


def test_generate_reply_safety_block_never_prints_full_draft():
    """The teacher-facing-leak safety net still fires and still forces
    review, but the log line for it must name only the matched phrase,
    never the surrounding draft (which is built from the customer's own
    email)."""

    reply_generator.client.chat.completions.set_next(
        _fake_chat_response(f"{_SECRET_BODY} Our coordination team will identify a suitable rescheduled time.")
    )

    captured = io.StringIO()
    with redirect_stdout(captured):
        reply_text, status = reply_generator.generate_reply(
            gmail_message_id="test-p06-2",
            subject=_SECRET_SUBJECT,
            body=_SECRET_BODY,
            category="General",
            priority="Medium",
            thread_history="",
            historical_emails=[],
            knowledge=[],
        )
    output = captured.getvalue()

    check(
        "safety-net block still works exactly as before (fix didn't change behavior)",
        status == "blocked_safety_net" and reply_text == "",
        f"got status={status!r} reply_text={reply_text!r}",
    )
    check(
        "the matched staff-only phrase IS logged (useful signal preserved)",
        "coordination team" in output,
    )
    check(
        "the customer's body is NOT logged even on a safety-net block",
        _SECRET_BODY not in output,
    )


def test_generate_reply_error_path_still_works():
    reply_generator.client.chat.completions.set_next(RuntimeError("simulated API failure"))

    captured = io.StringIO()
    with redirect_stdout(captured):
        reply_text, status = reply_generator.generate_reply(
            gmail_message_id="test-p06-3",
            subject=_SECRET_SUBJECT,
            body=_SECRET_BODY,
            category="General",
            priority="Medium",
            thread_history="",
            historical_emails=[],
            knowledge=[],
        )

    check(
        "error path still returns ('', 'error') unchanged",
        status == "error" and reply_text == "",
        f"got status={status!r} reply_text={reply_text!r}",
    )


# ---------------------------------------------------------------------------
# P0-6: main.py - source-level checks (see module docstring for why).
# ---------------------------------------------------------------------------

def _read_main_source():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"), "r", encoding="utf-8") as f:
        return f.read()


def test_main_py_no_longer_prints_full_email_data_dict():
    src = _read_main_source()
    check(
        "view_email() no longer prints the full email_data dict",
        "print(email_data)" not in src,
    )
    check(
        "the safe replacement (id/category/status only) is present",
        "Loaded email: id=" in src,
    )


def test_main_py_no_longer_prints_full_conversation():
    src = _read_main_source()
    check(
        'no remaining bare print(conversation) in main.py',
        "print(conversation)" not in src,
    )
    check(
        "the safe conversation-length replacement is present",
        "conversation_length=" in src,
    )


def test_main_py_no_longer_prints_raw_form_dict():
    src = _read_main_source()
    check(
        "the teacher send-reply route no longer dumps the raw submitted form (which includes the reply text)",
        "print(dict(form))" not in src,
    )


def test_main_py_no_longer_prints_reply_text_directly():
    src = _read_main_source()
    check(
        'no remaining print("reply:", reply) in main.py',
        'print("reply:", reply)' not in src,
    )
    check(
        "the safe reply_length replacement is present",
        "reply_length=" in src,
    )


def test_main_py_no_longer_prints_teacher_api_result_or_extracted_message():
    src = _read_main_source()
    check(
        "the raw Teacher Portal API result (which echoes back sent message content) is no longer logged",
        'print("API RESULT:", result)' not in src,
    )
    check(
        "the extracted teacher API message is no longer logged in full",
        'print("EXTRACTED TEACHER API MESSAGE:", sent_message)' not in src,
    )


def test_main_py_no_longer_prints_bulk_send_subject():
    src = _read_main_source()
    check(
        "bulk compose-send no longer prints each recipient's (often personalized) subject line",
        'print(msg["Subject"])' not in src,
    )


def test_main_py_no_longer_prints_full_teacher_list_or_message_dump():
    src = _read_main_source()
    check(
        "teacher_inbox no longer prints the full teachers list",
        "print(teachers)" not in src,
    )
    check(
        "teacher_inbox no longer dumps every conversation message",
        "for m in messages:\n            print(m)" not in src,
    )
    check(
        "teacher_inbox no longer prints the full latest-parent-message object",
        'print("LATEST PARENT MESSAGE ="' not in src,
    )


def test_main_py_followup_email_row_no_longer_printed():
    src = _read_main_source()
    check(
        "the trial-followup reply route no longer prints the full email row (includes recipient_email)",
        "email = get_followup_email(email_id)\n    print(email)" not in src,
    )


def test_main_py_operational_logs_still_present():
    """Confirms this was a targeted removal, not a wholesale deletion of
    useful logging - the safe operational signals should still exist."""
    src = _read_main_source()
    for safe_marker in [
        "VIEW_EMAIL START",
        "Bulk send complete:",
        "Teacher API: elapsed=",
        "Reply route called: email_id=",
    ]:
        check(f'safe operational log "{safe_marker}" still present', safe_marker in src)


def main():
    test_email_detail_uses_classification_confidence_label()
    test_email_detail_confidence_value_expression_preserved()
    test_email_detail_no_trust_implying_color_tiers()
    test_email_detail_no_misleading_wording()
    test_category_html_uses_classification_label()
    test_category_html_value_expression_preserved()
    test_category_html_no_trust_implying_color_tiers()
    test_dashboard_html_does_not_display_confidence_at_all()
    test_no_other_template_has_confidence_wording()

    test_generate_reply_never_prints_subject_or_body()
    test_generate_reply_safety_block_never_prints_full_draft()
    test_generate_reply_error_path_still_works()

    test_main_py_no_longer_prints_full_email_data_dict()
    test_main_py_no_longer_prints_full_conversation()
    test_main_py_no_longer_prints_raw_form_dict()
    test_main_py_no_longer_prints_reply_text_directly()
    test_main_py_no_longer_prints_teacher_api_result_or_extracted_message()
    test_main_py_no_longer_prints_bulk_send_subject()
    test_main_py_no_longer_prints_full_teacher_list_or_message_dump()
    test_main_py_followup_email_row_no_longer_printed()
    test_main_py_operational_logs_still_present()

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {_failures}")
        sys.exit(1)
    else:
        print("All tests passed.")


if __name__ == "__main__":
    main()
