"""Focused tests for reasoning-token observability in reply_generator.py.

Background (see the generation-latency read-only investigation this
follows): completion-token count, not prompt size, correlates strongly
with generation latency in production. gpt-5-nano is a reasoning model,
and its completion_tokens figure appears to include invisible reasoning
tokens never surfaced in the visible reply text. openai==2.41.1's own
CompletionUsage type (verified against that exact pinned version's real
source on GitHub) declares:

    completion_tokens_details: Optional[CompletionTokensDetails] = None
    # and on CompletionTokensDetails:
    reasoning_tokens: Optional[int] = None

Change under test: generate_reply() now extracts
usage.completion_tokens_details.reasoning_tokens defensively (via
getattr() with a default at every step) and logs it as a new, separate
log line - purely additive observability. No ai_logs column exists for
this value (confirmed by schema inspection), so nothing is persisted to
the database and save_ai_log() is called with exactly the same arguments
as before this change.

Follow-up (this file): the reasoning-token line now goes through
logger.py's existing logger (logger.info(...)) instead of print() - a
read-only investigation found this module's prints weren't showing up in
Render's log viewer, most plausibly because of default stdout buffering,
while logging.StreamHandler flushes on every record by design. This is a
transport change only: the message text/format and the reasoning_tokens
value itself are completely unchanged. reply_generator.logger is
monkey-patched with a small fake (FakeLogger below) for the duration of
each call in this file, the same lightweight-fake philosophy this file
already uses for openai/psycopg2/dotenv - real logging.Handler plumbing
isn't needed just to assert on one captured message string.

Matches this repo's existing test_*.py convention (see test_p0_fixes.py,
whose exact fake-OpenAI-client/fake-psycopg2 infrastructure this file
reuses) - a plain script using only assert statements and the standard
library - no pytest.

Run with: python3 test_reasoning_token_observability.py
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
# Fake infrastructure - identical technique to test_p0_fixes.py, so
# reply_generator.py can be imported and generate_reply() actually called,
# with a controllable fake OpenAI-family response.
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


class FakeOpenAI:
    def __init__(self, *a, **kw):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())


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


class FakeLogger:
    """Stands in for logger.py's real `logger` - only .info() is exercised
    by the code under test, but .error()/.warning()/.exception() are
    included as harmless no-ops so this fake stays safe to use even if a
    future change adds another log level here."""

    def __init__(self):
        self.messages = []

    def info(self, msg, *a, **kw):
        self.messages.append(str(msg))

    def error(self, msg, *a, **kw):
        self.messages.append(str(msg))

    def warning(self, msg, *a, **kw):
        self.messages.append(str(msg))

    def exception(self, msg, *a, **kw):
        self.messages.append(str(msg))


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


# ---------------------------------------------------------------------------
# Response builders - one per scenario the task asked for.
# ---------------------------------------------------------------------------

def _response_with_reasoning_tokens(content, reasoning_tokens):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))],
        usage=types.SimpleNamespace(
            prompt_tokens=6523,
            completion_tokens=1172,
            total_tokens=7695,
            completion_tokens_details=types.SimpleNamespace(reasoning_tokens=reasoning_tokens),
        ),
    )


def _response_without_completion_tokens_details(content):
    """Mirrors a real usage object from an SDK/provider that never
    populates this optional field at all - no completion_tokens_details
    attribute present, exactly like this repo's other fake responses
    (e.g. test_p0_fixes.py's _fake_chat_response) already construct."""
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))],
        usage=types.SimpleNamespace(prompt_tokens=6523, completion_tokens=1172, total_tokens=7695),
    )


def _response_with_malformed_usage_structure(content):
    """usage.completion_tokens_details exists but is NOT the expected
    object shape (a bare int here, standing in for "some genuinely
    unexpected type") - reasoning_tokens must not be an attribute of an
    int, so getattr(..., "reasoning_tokens", None) must safely fall back
    to None rather than raising."""
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))],
        usage=types.SimpleNamespace(
            prompt_tokens=6523,
            completion_tokens=1172,
            total_tokens=7695,
            completion_tokens_details=12345,
        ),
    )


def _call_generate_reply(response):
    """Returns (reply_text, status, output), where `output` merges the
    real stdout print() lines (e.g. "Reply generated - ...", unchanged by
    this task) with the fake logger's captured .info() lines (e.g.
    "Reasoning tokens - ...", now logged rather than printed) into one
    string, so every existing "<expected text> in output" assertion below
    still works unchanged regardless of which transport a given line uses."""
    reply_generator.client.chat.completions.set_next(response)
    fake_logger = FakeLogger()
    original_logger = reply_generator.logger
    reply_generator.logger = fake_logger
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            reply_text, status = reply_generator.generate_reply(
                gmail_message_id="test-msg-1",
                subject="How much is the class?",
                body="Can you tell me the price?",
                category="Billing",
                priority="Medium",
                thread_history="",
                historical_emails=[],
                knowledge=[],
            )
    finally:
        reply_generator.logger = original_logger
    output = buf.getvalue() + "\n".join(fake_logger.messages)
    return reply_text, status, output


# ---------------------------------------------------------------------------
# 1. reasoning-token field present.
# ---------------------------------------------------------------------------

def test_reasoning_tokens_present_is_captured_and_logged():
    reply_text, status, output = _call_generate_reply(
        _response_with_reasoning_tokens("Thanks for your question. It's $20 per session.", 900)
    )
    check("reply generation still succeeds", status == "ok")
    check("the reply text is unchanged", reply_text == "Thanks for your question. It's $20 per session.")
    check(
        "the new log line reports the real reasoning_tokens value (900)",
        "Reasoning tokens - gmail_message_id=test-msg-1 reasoning_tokens=900" in output,
        f"got output={output!r}",
    )


# ---------------------------------------------------------------------------
# 2. reasoning-token field absent (no completion_tokens_details at all).
# ---------------------------------------------------------------------------

def test_reasoning_tokens_absent_defaults_to_none_and_does_not_crash():
    reply_text, status, output = _call_generate_reply(
        _response_without_completion_tokens_details("No reasoning-token metadata here.")
    )
    check("reply generation still succeeds even with no completion_tokens_details at all", status == "ok")
    check("the reply text is unchanged", reply_text == "No reasoning-token metadata here.")
    check(
        "the new log line reports reasoning_tokens=None rather than raising",
        "Reasoning tokens - gmail_message_id=test-msg-1 reasoning_tokens=None" in output,
        f"got output={output!r}",
    )


# ---------------------------------------------------------------------------
# 3. malformed/unexpected usage structure.
# ---------------------------------------------------------------------------

def test_malformed_completion_tokens_details_does_not_crash():
    reply_text, status, output = _call_generate_reply(
        _response_with_malformed_usage_structure("Still a normal reply.")
    )
    check("reply generation still succeeds even with a malformed completion_tokens_details shape", status == "ok")
    check("the reply text is unchanged", reply_text == "Still a normal reply.")
    check(
        "getattr() safely falls back to reasoning_tokens=None instead of raising on the unexpected int shape",
        "Reasoning tokens - gmail_message_id=test-msg-1 reasoning_tokens=None" in output,
        f"got output={output!r}",
    )


def test_usage_object_itself_missing_is_handled_by_existing_code_path():
    """Not a new guarantee this change adds - generate_reply() already
    wraps the whole call in try/except, so if `usage` itself were ever
    absent/broken enough to raise inside the try block, the existing
    error path (status="error", reply_text="") already handles it,
    unchanged by this task. Confirmed here so the two failure modes
    (missing sub-field vs. missing usage entirely) are both accounted for."""
    broken_response = types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="x"))],
        usage=None,
    )
    reply_generator.client.chat.completions.set_next(broken_response)
    buf = io.StringIO()
    with redirect_stdout(buf):
        reply_text, status = reply_generator.generate_reply(
            gmail_message_id="test-msg-2",
            subject="s", body="b", category="c", priority="p",
            thread_history="", historical_emails=[], knowledge=[],
        )
    check(
        "a genuinely absent usage object (usage=None) still falls into the pre-existing error path, "
        "not a new crash introduced by this task",
        status == "error" and reply_text == "",
    )


# ---------------------------------------------------------------------------
# 4/5. Reply/status and existing token metrics are completely unchanged.
# ---------------------------------------------------------------------------

def test_existing_token_metrics_and_status_unaffected():
    reply_text, status, output = _call_generate_reply(
        _response_with_reasoning_tokens("A perfectly normal reply.", 42)
    )
    check('status is still exactly "ok"', status == "ok")
    check("reply text is passed through unchanged", reply_text == "A perfectly normal reply.")
    check(
        "the pre-existing 'Reply generated' log line (length/elapsed_ms) is still present and unchanged in shape",
        "Reply generated - gmail_message_id=test-msg-1 length=" in output and "elapsed_ms=" in output,
    )
    check(
        "save_ai_log's own DB write (via FakeCursor) was not skipped and still used the real prompt/completion/total tokens",
        database.db_pool.last_params is not None
        and 6523 in database.db_pool.last_params
        and 1172 in database.db_pool.last_params
        and 7695 in database.db_pool.last_params,
        f"got last_params={database.db_pool.last_params!r}",
    )


def test_no_reasoning_token_value_is_ever_passed_to_save_ai_log():
    """No ai_logs column exists for this value (schema inspected before
    this change) - confirms the DB write path itself carries exactly the
    same parameter count/shape as before, with no new value silently
    smuggled into an existing column."""
    _call_generate_reply(_response_with_reasoning_tokens("Reply text.", 500))
    check(
        "500 (the reasoning-token test value) never appears in the SQL params passed to the database",
        500 not in database.db_pool.last_params,
        f"got last_params={database.db_pool.last_params!r}",
    )


# ---------------------------------------------------------------------------
# 6. Source-level scope check: confirm the print()->logger.info() swap is
#    exactly as narrow as this task requires - only the one reasoning-token
#    line changed, every other print() in this file is untouched, and the
#    import follows this repo's own established convention.
# ---------------------------------------------------------------------------

def _read_source(filename):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename), "r", encoding="utf-8") as f:
        return f.read()


def test_reasoning_token_line_uses_logger_not_print():
    src = _read_source("reply_generator.py")
    check(
        "the reasoning-token line calls logger.info(...), not print(...)",
        'logger.info(f"Reasoning tokens - gmail_message_id={gmail_message_id} reasoning_tokens={reasoning_tokens}")' in src,
    )
    check(
        "the old print()-based reasoning-token line no longer exists",
        'print(f"Reasoning tokens - gmail_message_id={gmail_message_id} reasoning_tokens={reasoning_tokens}")' not in src,
    )
    check(
        "the logger is imported the same way every other caller in this repo already does it",
        "from logger import logger" in src,
    )


def _code_lines(src):
    """Non-comment source lines only - this file's own new explanatory
    comment mentions "print()" and "logger.info()" several times in
    prose, which would otherwise inflate a naive whole-file substring
    count (the same class of false positive this repo's test suite has
    hit before whenever a comment happens to name the exact thing a check
    is looking for)."""
    return [line for line in src.splitlines() if not line.strip().startswith("#")]


def test_no_other_print_statement_was_touched():
    src = _read_source("reply_generator.py")
    code_lines = _code_lines(src)
    real_print_calls = sum(line.count("print(") for line in code_lines)
    real_logger_info_calls = sum(line.count("logger.info(") for line in code_lines)
    check(
        "the pre-existing 'Reply generated' line is still a print(), unchanged by this task",
        'print(f"Reply generated - gmail_message_id={gmail_message_id} length={len(reply)} elapsed_ms={elapsed_ms}")' in src,
    )
    check(
        "reply_generator.py still has exactly 10 other print() calls in real code (11 total before this task, minus the one converted)",
        real_print_calls == 10,
        f"got {real_print_calls}",
    )
    check(
        "exactly one real logger.info(...) call exists in reply_generator.py - no other line was converted",
        real_logger_info_calls == 1,
        f"got {real_logger_info_calls}",
    )
    check(
        "reasoning_tokens is still computed exactly as before (getattr chain unchanged)",
        'completion_tokens_details = getattr(usage, "completion_tokens_details", None)' in src
        and 'reasoning_tokens = getattr(completion_tokens_details, "reasoning_tokens", None)' in src,
    )


def main():
    tests = [
        test_reasoning_tokens_present_is_captured_and_logged,
        test_reasoning_tokens_absent_defaults_to_none_and_does_not_crash,
        test_malformed_completion_tokens_details_does_not_crash,
        test_usage_object_itself_missing_is_handled_by_existing_code_path,
        test_existing_token_metrics_and_status_unaffected,
        test_no_reasoning_token_value_is_ever_passed_to_save_ai_log,
        test_reasoning_token_line_uses_logger_not_print,
        test_no_other_print_statement_was_touched,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
