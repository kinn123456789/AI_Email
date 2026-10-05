"""Focused tests for the Teacher Portal "✨ Polish" feature:
reply_polish.py's new channel="teacher" support, and the new
POST /teacher/polish-reply route in main.py.

Same two-kind-of-check split as test_reply_polish.py (which this file
deliberately does not modify, to keep the existing, approved email Polish
feature's own test file at zero risk):

1. reply_polish.py IS imported and exercised FOR REAL, against the same
   fake openai/dotenv/psycopg2 infrastructure test_reply_polish.py
   establishes.

2. main.py's new route can't be imported here (starts real scheduler.py
   background jobs, needs fastapi/apscheduler, neither installed in this
   sandbox) - checked via source-presence/structural checks against the
   real file, the same technique test_reply_polish.py already uses for
   the email polish route.

Run with: python3 test_teacher_polish.py
"""

import os
import sys
import types


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


# ---------------------------------------------------------------------------
# Fake infrastructure - identical technique to test_reply_polish.py.
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
        self.call_count = 0
        self.last_kwargs = None

    def set_next(self, value_or_exception):
        self._next = value_or_exception

    def create(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        v = self._next
        if isinstance(v, Exception):
            raise v
        return v


class FakeOpenAI:
    def __init__(self, *a, **kw):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())


def _fake_response(content, prompt_tokens=500, completion_tokens=80, total_tokens=580):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))],
        usage=types.SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total_tokens
        ),
    )


class FakeCursor:
    def __init__(self, pool):
        self._pool = pool

    def execute(self, sql, params=None):
        self._pool.sql_log.append(sql)
        self._pool.params_log.append(params)

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
        self.sql_log = []
        self.params_log = []

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
import reply_polish  # noqa: E402
import database  # noqa: E402


def _reset_pool():
    database.db_pool = FakeSimpleConnectionPool()


def _read_source(filename):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename), "r", encoding="utf-8") as f:
        return f.read()


def _teacher_route_body():
    src = _read_source("main.py")
    start = src.find('@app.post("/teacher/polish-reply")')
    end = src.find('@app.post("/email/{email_id}/trash")')
    assert start != -1 and end != -1 and end > start, "could not locate polish_teacher_reply()'s body"
    return src[start:end]


# ===========================================================================
# build_polish_system_prompt() - audience/channel separation.
# ===========================================================================

def test_1_default_system_prompt_is_byte_identical_to_POLISH_SYSTEM_PROMPT():
    check(
        "1. build_polish_system_prompt() with no args returns POLISH_SYSTEM_PROMPT unchanged",
        reply_polish.build_polish_system_prompt() == reply_polish.POLISH_SYSTEM_PROMPT,
    )
    check(
        "1. build_polish_system_prompt(channel='email') returns POLISH_SYSTEM_PROMPT unchanged",
        reply_polish.build_polish_system_prompt(channel="email") == reply_polish.POLISH_SYSTEM_PROMPT,
    )


def test_2_teacher_channel_appends_override_without_altering_the_base():
    teacher_prompt = reply_polish.build_polish_system_prompt(channel="teacher")
    check(
        "2. channel='teacher' prompt still starts with the exact unmodified POLISH_SYSTEM_PROMPT",
        teacher_prompt.startswith(reply_polish.POLISH_SYSTEM_PROMPT),
    )
    check(
        "2. channel='teacher' prompt appends the TEACHER PORTAL CHAT CONTEXT section",
        "TEACHER PORTAL CHAT CONTEXT" in teacher_prompt,
    )
    check(
        "2. the override explicitly says not to add a greeting or signature",
        "do not add a greeting" in teacher_prompt.lower() and "signature" in teacher_prompt.lower(),
    )
    check(
        "2. the override explicitly says this is a chat message, not an email",
        "not an email" in teacher_prompt,
    )


# ===========================================================================
# polish_draft() - channel wiring, end to end against the fake client.
# ===========================================================================

def test_3_polish_draft_default_channel_unchanged_behavior():
    _reset_pool()
    reply_polish.client.chat.completions.set_next(_fake_response("Polished email text."))

    polished, status = reply_polish.polish_draft("some draft")

    sent = reply_polish.client.chat.completions.last_kwargs["messages"]
    check("3. status is ok", status == "ok")
    check("3. default call's system prompt has no teacher override", "TEACHER PORTAL" not in sent[0]["content"])
    check("3. default call's system prompt is exactly POLISH_SYSTEM_PROMPT", sent[0]["content"] == reply_polish.POLISH_SYSTEM_PROMPT)


def test_4_polish_draft_teacher_channel_sends_teacher_system_prompt():
    _reset_pool()
    marker_draft = "MARKER_TEACHER_DRAFT_class_is_at_4pm_friday_QZ8"
    reply_polish.client.chat.completions.set_next(_fake_response("Polished chat reply."))

    polished, status = reply_polish.polish_draft(marker_draft, channel="teacher")

    sent = reply_polish.client.chat.completions.last_kwargs["messages"]
    check("4. status is ok", status == "ok")
    check("4. polished text returned verbatim", polished == "Polished chat reply.")
    check("4. exactly 2 messages sent (system + user)", len(sent) == 2)
    check("4. teacher channel's system prompt includes the TEACHER PORTAL CHAT CONTEXT override", "TEACHER PORTAL CHAT CONTEXT" in sent[0]["content"])
    check("4. the draft is passed verbatim as the user message", sent[1]["content"] == marker_draft)
    check("4. the draft never leaks into the system message", marker_draft not in sent[0]["content"])


def test_5_teacher_channel_error_path_unchanged():
    _reset_pool()
    reply_polish.client.chat.completions.set_next(RuntimeError("upstream boom"))

    try:
        polished, status = reply_polish.polish_draft("a normal reply", channel="teacher")
        raised = False
    except Exception:
        raised = True
        polished, status = None, None

    check("5. no exception leaks out for channel='teacher' either", not raised)
    check('5. status is "error"', status == "error")
    check('5. polished text is ""', polished == "")


def test_6_teacher_channel_logging_still_never_contains_draft_or_polished_text():
    _reset_pool()
    marker_draft = "MARKER_TEACHER_call_the_parent_at_555_0199_YK2"
    marker_polished = "MARKER_POLISHED_TEACHER_please_call_555_0199_ZB8"
    reply_polish.client.chat.completions.set_next(_fake_response(marker_polished))

    reply_polish.polish_draft(marker_draft, channel="teacher")

    check(
        "6. the draft text never appears in any SQL params sent to the database",
        not any(marker_draft in str(p) for p in database.db_pool.params_log),
    )
    check(
        "6. the polished text never appears in any SQL params sent to the database",
        not any(marker_polished in str(p) for p in database.db_pool.params_log),
    )
    check(
        "6. the ai_logs INSERT still uses category='Polish' for the teacher channel too",
        any("Polish" in (params or ()) for params in database.db_pool.params_log),
    )


# ===========================================================================
# /teacher/polish-reply route - source-presence checks.
# ===========================================================================

def test_7_route_exists_and_uses_request_state_form():
    body = _teacher_route_body()
    check('7. the route is registered at POST /teacher/polish-reply', '@app.post("/teacher/polish-reply")' in body)
    check("7. the route reads form = request.state.form", "form = request.state.form" in body)
    check(
        "7. the route does NOT itself call `= await request.form()` (no second body read)",
        "= await request.form()" not in body,
    )
    check("7. polish_draft is called with channel=\"teacher\"", 'polish_draft(draft, channel="teacher")' in body)


def test_8_route_rejects_empty_and_whitespace_draft_before_calling_polish_draft():
    body = _teacher_route_body()
    check('8. the draft is stripped for validation', '.strip()' in body)
    check(
        "8. an empty (post-strip) draft is rejected with a 400 JSON error",
        'if not draft:' in body and 'status_code=400' in body,
    )
    idx_strip = body.index('draft = (form.get("draft") or "").strip()')
    idx_guard = body.index("if not draft:")
    idx_call = body.index('polish_draft(draft, channel="teacher")')
    check(
        "8. validation happens strictly before polish_draft() is ever called - "
        "an empty/whitespace-only draft never reaches the LLM",
        idx_strip < idx_guard < idx_call,
    )


def test_9_route_failure_response_never_exposes_raw_provider_error():
    body = _teacher_route_body()
    check(
        '9. on a non-"ok" status, a clean, fixed error message is returned - never the raw exception/provider text',
        'content={"error": "Unable to polish the reply right now."}' in body,
    )
    check("9. the failure path returns a non-2xx status", "status_code=502" in body)


def test_10_route_never_sends_or_persists_anything():
    body = _teacher_route_body()
    for forbidden in [
        "send_teacher_reply(", "save_teacher_reply(", "mark_reply_sent(",
        "save_conversation_message(", "delete_teacher_message(", "update_teacher_ai_fields(",
    ]:
        check(f"10. the polish route never calls {forbidden!r}", forbidden not in body)


def test_11_route_success_response_shape():
    body = _teacher_route_body()
    check('11. a successful polish returns {"polished": polished}', 'content={"polished": polished}' in body)


def test_12_existing_email_polish_route_is_untouched():
    """Sanity check that adding the new teacher route didn't disturb the
    existing email polish route's own exact text (test_reply_polish.py
    already re-verifies this in full by being re-run - this is a quick
    extra confirmation at the source level)."""
    src = _read_source("main.py")
    check(
        '12. the original /email/{email_id}/polish route is still present, unmodified',
        'content={"error": "Unable to polish the draft right now."}' in src,
    )
    check(
        "12. the email route still calls polish_draft(draft) with no channel override (unchanged default)",
        "polish_draft(draft)\n" in src,
    )


def main():
    tests = [
        test_1_default_system_prompt_is_byte_identical_to_POLISH_SYSTEM_PROMPT,
        test_2_teacher_channel_appends_override_without_altering_the_base,
        test_3_polish_draft_default_channel_unchanged_behavior,
        test_4_polish_draft_teacher_channel_sends_teacher_system_prompt,
        test_5_teacher_channel_error_path_unchanged,
        test_6_teacher_channel_logging_still_never_contains_draft_or_polished_text,
        test_7_route_exists_and_uses_request_state_form,
        test_8_route_rejects_empty_and_whitespace_draft_before_calling_polish_draft,
        test_9_route_failure_response_never_exposes_raw_provider_error,
        test_10_route_never_sends_or_persists_anything,
        test_11_route_success_response_shape,
        test_12_existing_email_polish_route_is_untouched,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
