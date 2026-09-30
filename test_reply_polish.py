"""Focused tests for Phase 1 of the AI Polish feature (see the read-only
architecture investigation this follows): the isolated reply_polish.py
module and the new POST /email/{email_id}/polish route in main.py.

TWO KINDS OF CHECK, SAME SPLIT AS EVERY OTHER test_*.py FILE IN THIS
REPO THAT TOUCHES main.py:

1. reply_polish.py IS imported and exercised FOR REAL, against the same
   fake openai/dotenv/psycopg2 infrastructure test_p0_fixes.py and
   test_reasoning_token_observability.py already establish - a fake
   OpenAI-family client stands in for the real provider, and
   database.db_pool captures the exact SQL/params save_ai_log() sends,
   so this file can assert on real behavior, not just source text.

2. main.py's new route can't be imported here (starts real scheduler.py
   background jobs, needs fastapi/apscheduler, neither installed in
   this sandbox) - checked via source-presence/structural checks
   against the real file, the same technique every other test file
   touching main.py in this repo already uses.

Run with: python3 test_reply_polish.py
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
# Fake infrastructure - identical technique to test_p0_fixes.py /
# test_reasoning_token_observability.py, with a call counter added so
# "exactly one chat.completions.create() call" can be asserted directly.
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


def _route_body():
    src = _read_source("main.py")
    start = src.find('@app.post("/email/{email_id}/polish")')
    end = src.find('def _save_reply_to_historical_emails(')
    assert start != -1 and end != -1 and end > start, "could not locate polish_reply()'s body"
    return src[start:end]


# ---------------------------------------------------------------------------
# 1/13. Successful polish - fake OpenAI returns text, function returns it,
# exactly one LLM call occurs.
# ---------------------------------------------------------------------------

def test_successful_polish_returns_text_and_makes_exactly_one_call():
    _reset_pool()
    reply_polish.client.chat.completions.set_next(_fake_response("Thanks so much for reaching out!"))

    polished, status = reply_polish.polish_draft("thanks for reaching out")

    check("status is ok", status == "ok")
    check("the polished text is returned unchanged", polished == "Thanks so much for reaching out!")
    check(
        "exactly one chat.completions.create() call was made",
        reply_polish.client.chat.completions.call_count == 1,
        f"got {reply_polish.client.chat.completions.call_count}",
    )


# ---------------------------------------------------------------------------
# 4. Provider exception -> explicit error, no exception leaks, no
# messages-table mutation.
# ---------------------------------------------------------------------------

def test_provider_exception_returns_error_without_raising():
    _reset_pool()
    reply_polish.client.chat.completions.set_next(RuntimeError("upstream boom"))

    try:
        polished, status = reply_polish.polish_draft("a perfectly normal draft")
        raised = False
    except Exception:
        raised = True
        polished, status = None, None

    check("no exception leaks out of polish_draft()", not raised)
    check('status is "error"', status == "error")
    check('polished text is ""', polished == "")
    check(
        "no SQL statement touching the messages table was executed (only ai_logs)",
        not any("messages" in (sql or "").lower() for sql in database.db_pool.sql_log),
        f"got sql_log={database.db_pool.sql_log!r}",
    )


# ---------------------------------------------------------------------------
# 5. Empty provider response treated as error.
# ---------------------------------------------------------------------------

def test_empty_provider_response_is_treated_as_error():
    _reset_pool()
    reply_polish.client.chat.completions.set_next(_fake_response(""))
    polished, status = reply_polish.polish_draft("some draft text")
    check('an empty completion is treated as "error", not a valid empty result', status == "error")
    check('polished text is ""', polished == "")

    _reset_pool()
    reply_polish.client.chat.completions.set_next(_fake_response("   "))
    polished2, status2 = reply_polish.polish_draft("some draft text")
    check("a whitespace-only completion is also treated as error", status2 == "error")


# ---------------------------------------------------------------------------
# 6/7. Exact draft passed as the user message; system prompt kept separate.
# ---------------------------------------------------------------------------

def test_draft_passed_verbatim_as_user_message_system_prompt_separate():
    _reset_pool()
    marker_draft = "MARKER_DRAFT_the_class_starts_at_5pm_QZ9"
    reply_polish.client.chat.completions.set_next(_fake_response("Polished version."))

    reply_polish.polish_draft(marker_draft)

    sent_messages = reply_polish.client.chat.completions.last_kwargs["messages"]
    check("exactly 2 messages are sent (system + user)", len(sent_messages) == 2)
    check('the first message has role "system"', sent_messages[0]["role"] == "system")
    check('the second message has role "user"', sent_messages[1]["role"] == "user")
    check(
        "the user message content is the draft, verbatim, with no wrapping/formatting",
        sent_messages[1]["content"] == marker_draft,
    )
    check(
        "the system message contains the real Polish instructions, not the draft",
        "polishing assistant" in sent_messages[0]["content"].lower()
        and marker_draft not in sent_messages[0]["content"],
    )
    check(
        "the draft never appears inside the system message (no string concatenation of the two)",
        marker_draft not in sent_messages[0]["content"],
    )


# ---------------------------------------------------------------------------
# 8/9. Logging category is "Polish"; draft/polished text never logged.
# ---------------------------------------------------------------------------

def test_logging_category_is_polish_and_never_contains_draft_or_polished_text():
    _reset_pool()
    marker_draft = "MARKER_DRAFT_call_me_at_555_0100_XK3"
    marker_polished = "MARKER_POLISHED_please_call_555_0100_YB7"
    reply_polish.client.chat.completions.set_next(_fake_response(marker_polished))

    polished, status = reply_polish.polish_draft(marker_draft)

    check("polish succeeded (sanity check for this test)", status == "ok" and polished == marker_polished)
    check(
        'the ai_logs INSERT uses category="Polish"',
        any("Polish" in (params or ()) for params in database.db_pool.params_log),
        f"got params_log={database.db_pool.params_log!r}",
    )
    check(
        "the draft text never appears in any SQL params sent to the database",
        not any(marker_draft in str(p) for p in database.db_pool.params_log),
    )
    check(
        "the polished text never appears in any SQL params sent to the database",
        not any(marker_polished in str(p) for p in database.db_pool.params_log),
    )


# ---------------------------------------------------------------------------
# 10/11/12. reply_polish.py never touches the database beyond ai_logger,
# never sends email, never imports/invokes reply_generator.py.
# ---------------------------------------------------------------------------

def test_polish_module_never_imports_database_send_or_reply_generator():
    src = _read_source("reply_polish.py")
    check(
        "reply_polish.py never imports database.py directly "
        "(the only DB access allowed is indirectly, through ai_logger.save_ai_log())",
        "import database" not in src and "from database" not in src,
    )
    for forbidden in ["get_email_by_id", "update_final_reply", "save_email", "update_status", "update_reply_type"]:
        check(f"reply_polish.py never references database.{forbidden}()", forbidden not in src)
    check("reply_polish.py never imports or calls send_email()", "send_email" not in src and "email_sender" not in src)
    # Checks the exact executable import syntax ("import reply_generator"
    # or "from reply_generator import ...") rather than a bare
    # "reply_generator" substring, which would also match this module's
    # own explanatory prose (e.g. "Deliberately separate FROM
    # REPLY_GENERATOR.py") describing the relationship without actually
    # importing anything.
    # Checked via import-absence alone, not a substring search for
    # "generate_reply"/"reply_generator.generate_reply(" - this module's
    # own docstring legitimately mentions reply_generator.generate_reply()
    # BY NAME as prose, explaining the relationship without calling it,
    # and that qualified-name mention is textually indistinguishable from
    # a real call site by substring matching alone. Proving no import of
    # reply_generator exists at all (checked above and reconfirmed here)
    # is sufficient: a qualified call like reply_generator.generate_reply(...)
    # is impossible without either "import reply_generator" or
    # "from reply_generator import generate_reply" first - both already
    # confirmed absent.
    check(
        "reply_polish.py never imports reply_generator.py (which would be required for any real call to it)",
        "import reply_generator" not in src and "from reply_generator import" not in src,
    )
    check("the only database-adjacent import is ai_logger.save_ai_log", "from ai_logger import save_ai_log" in src)


# ---------------------------------------------------------------------------
# main.py route - source-presence checks (main.py isn't importable here).
# Covers scenarios 2, 3, 10, 11, 12 at the route/wiring level.
# ---------------------------------------------------------------------------

def test_route_exists_and_uses_request_state_form():
    body = _route_body()
    check('the route is registered at POST /email/{email_id}/polish', '@app.post("/email/{email_id}/polish")' in body)
    check("the route reads form = request.state.form", "form = request.state.form" in body)
    check(
        "the route does NOT itself call `= await request.form()` (no second body read)",
        "= await request.form()" not in body,
    )
    check("polish_draft is imported from reply_polish", "from reply_polish import polish_draft" in body or "from reply_polish import polish_draft" in _read_source("main.py"))


def test_route_rejects_empty_and_whitespace_draft_before_calling_polish_draft():
    body = _route_body()
    check('the draft is stripped for validation', '.strip()' in body)
    check(
        "an empty (post-strip) draft is rejected with a 400 JSON error",
        'if not draft:' in body and 'status_code=400' in body,
    )
    idx_strip = body.index('draft = (form.get("draft") or "").strip()')
    idx_guard = body.index("if not draft:")
    idx_call = body.index("polish_draft(draft)")
    check(
        "validation happens strictly before polish_draft() is ever called - "
        "an empty/whitespace-only draft never reaches the LLM",
        idx_strip < idx_guard < idx_call,
    )
    check(
        'the empty-draft error response never claims success ("polished" key absent from that branch)',
        body[idx_guard:idx_call].count('"polished"') == 0,
    )


def test_route_failure_response_never_exposes_raw_provider_error():
    body = _route_body()
    check(
        'on a non-"ok" status, a clean, fixed error message is returned - never the raw exception/provider text',
        'content={"error": "Unable to polish the draft right now."}' in body,
    )
    check("the failure path returns a non-2xx status", "status_code=502" in body)


def test_route_never_sends_email_or_persists_the_draft():
    body = _route_body()
    for forbidden in ["send_email(", "update_final_reply(", "update_status(", "save_email(", "ai_draft_reply ="]:
        check(f"the polish route never calls/sets {forbidden!r}", forbidden not in body)


def test_route_success_response_shape():
    body = _route_body()
    check('a successful polish returns {"polished": polished}', 'content={"polished": polished}' in body)


def main():
    tests = [
        test_successful_polish_returns_text_and_makes_exactly_one_call,
        test_provider_exception_returns_error_without_raising,
        test_empty_provider_response_is_treated_as_error,
        test_draft_passed_verbatim_as_user_message_system_prompt_separate,
        test_logging_category_is_polish_and_never_contains_draft_or_polished_text,
        test_polish_module_never_imports_database_send_or_reply_generator,
        test_route_exists_and_uses_request_state_form,
        test_route_rejects_empty_and_whitespace_draft_before_calling_polish_draft,
        test_route_failure_response_never_exposes_raw_provider_error,
        test_route_never_sends_email_or_persists_the_draft,
        test_route_success_response_shape,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
