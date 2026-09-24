"""
Focused tests for the P0-2 (retrieval error vs. genuine empty result) and
P0-3 (safety-net block -> requires_review) accuracy fixes, plus the pure
edited-before-send comparison and the requires_review combination formula.

Matches this repo's existing test_*.py convention: a plain script using
only assert statements and the standard library (no pytest - this repo has
no test framework configured, and none is installed in the environment
this was written in: openai, psycopg2, fastapi, dotenv, bs4, apscheduler
are all ModuleNotFoundError here).

Because those packages aren't installed, this file installs minimal fake
modules for openai/dotenv/psycopg2 into sys.modules BEFORE importing the
real reply_generator.py, rag_reranker.py, and knowledge_search.py - so the
REAL business logic in those three files runs against fake infrastructure,
not a re-implementation of it. main.py could not be exercised the same way
(it additionally needs fastapi + apscheduler, neither installed, and
main.py has no seam to import just one helper function in isolation) - the
two pieces that live there (_compute_edited_before_send, and the
requires_review combination formula duplicated in
_process_contact_form_enquiry) are instead verified as clearly-labeled
mirrors of the real code, kept byte-for-byte identical to what's in
main.py/process_email.py. Run with: python3 test_accuracy_fixes.py
"""

import json
import sys
import types


# ---------------------------------------------------------------------------
# Fake infrastructure - installed into sys.modules before importing any real
# repo file, so `from openai import OpenAI` / `from dotenv import
# load_dotenv` / `import psycopg2` etc. succeed without the real packages.
# ---------------------------------------------------------------------------

def _install_fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class FakeChatCompletions:
    """Controllable stand-in for client.chat.completions. Call
    set_next(value_or_exception) before invoking the code under test to
    control what the next .create(...) call returns or raises."""

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
        return types.SimpleNamespace(
            data=[types.SimpleNamespace(embedding=[0.1] * 8)]
        )


class FakeOpenAI:
    """Stand-in for openai.OpenAI. reply_generator.py and rag_reranker.py
    each construct their own instance at import time (module-level
    `client = OpenAI(...)`), so each real module ends up with its own
    independent FakeOpenAI - reply_generator.client and rag_reranker.client
    never share state, matching the real modules' own isolation."""

    def __init__(self, *a, **kw):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())
        self.embeddings = FakeEmbeddings()


def _fake_chat_response(content):
    """Builds the minimal shape reply_generator.py/rag_reranker.py actually
    read off a chat.completions.create(...) response."""
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
        # embed_classes.py calls conn.close() directly instead of
        # returning it to the pool via db_pool.putconn() - a no-op here,
        # same as every other fake teardown method.
        pass


class FakeSimpleConnectionPool:
    """Stand-in for psycopg2.pool.SimpleConnectionPool. database.py builds
    one of these at import time (`db_pool = SimpleConnectionPool(1, 25,
    dsn=...)`) - this fake accepts the same call signature without ever
    touching a real database, and exposes next_fetchall/next_fetchone as
    plain attributes a test can set right before calling the function
    under test."""

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

    pool_mod = _install_fake_module(
        "psycopg2.pool", SimpleConnectionPool=FakeSimpleConnectionPool
    )
    extras_mod = _install_fake_module("psycopg2.extras", RealDictCursor=dict)
    psycopg2_mod = _install_fake_module("psycopg2")
    psycopg2_mod.pool = pool_mod
    psycopg2_mod.extras = extras_mod
    psycopg2_mod.connect = lambda *a, **kw: FakeConnection(FakeSimpleConnectionPool())


_install_fakes()

# Real target modules - imported only after the fakes above are in place.
import reply_generator          # noqa: E402
import rag_reranker              # noqa: E402
import knowledge_search          # noqa: E402
import database                  # noqa: E402
import teacher_reply_generator1  # noqa: E402

# embed_classes.py has no `if __name__ == "__main__":` guard - importing it
# runs its whole top-level backfill loop immediately (against the fake DB
# pool set up above). Setting next_fetchall to [] first makes that one-time
# run a harmless no-op ("Found 0 classes.") so only format_pricing()/
# insert_chunk() get exercised deliberately, in the tests below.
database.db_pool.next_fetchall = []
import embed_classes             # noqa: E402


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


# ---------------------------------------------------------------------------
# H / I / no_reply / error - reply_generator.generate_reply()'s new status
# ---------------------------------------------------------------------------

def test_generate_reply_normal():
    """I: a clean draft, no safety-net pattern present."""
    reply_generator.client.chat.completions.set_next(
        _fake_chat_response("Thanks for reaching out - your class starts Monday at 4pm.")
    )
    text, status = reply_generator.generate_reply(
        gmail_message_id="test-1", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
    )
    check(
        "I. normal generation returns ('<text>', 'ok')",
        status == "ok" and text == "Thanks for reaching out - your class starts Monday at 4pm.",
        f"got status={status!r} text={text!r}",
    )


def test_generate_reply_safety_net_blocked():
    """H: response contains a known staff-only leak phrase."""
    reply_generator.client.chat.completions.set_next(
        _fake_chat_response(
            "Our coordination team will identify a suitable rescheduled time."
        )
    )
    text, status = reply_generator.generate_reply(
        gmail_message_id="test-2", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
    )
    check(
        "H. safety-net trigger returns ('', 'blocked_safety_net')",
        status == "blocked_safety_net" and text == "",
        f"got status={status!r} text={text!r}",
    )


def test_generate_reply_no_reply_sentinel():
    """The model's own considered 'not enough info' outcome - distinct from
    a safety-net block or an error."""
    reply_generator.client.chat.completions.set_next(_fake_chat_response("NO_REPLY"))
    text, status = reply_generator.generate_reply(
        gmail_message_id="test-3", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
    )
    check(
        "generate_reply NO_REPLY sentinel returns ('', 'no_reply')",
        status == "no_reply" and text == "",
        f"got status={status!r} text={text!r}",
    )


def test_generate_reply_error():
    """A genuine API failure at the generation call itself."""
    reply_generator.client.chat.completions.set_next(RuntimeError("simulated API failure"))
    text, status = reply_generator.generate_reply(
        gmail_message_id="test-4", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
    )
    check(
        "generate_reply API error returns ('', 'error')",
        status == "error" and text == "",
        f"got status={status!r} text={text!r}",
    )


# ---------------------------------------------------------------------------
# Regression test for the Critical finding from the code review:
# teacher_reply_generator1.py's generate_teacher_reply() is a live Teacher
# Portal caller of generate_reply() (scheduler.py -> teacher_ai_processor1.py
# -> teacher_reply_generator1.py) that was not updated when generate_reply()
# started returning a (text, status) tuple instead of a bare string - its
# result flows straight into database.update_teacher_ai_fields()'s
# draft_reply text-column parameter, so it must never receive the tuple.
# ---------------------------------------------------------------------------

def test_teacher_reply_returns_plain_string_not_tuple():
    """The exact regression: generate_teacher_reply() must return only the
    reply text (a str), never the (text, status) tuple, for every
    generation outcome - since its return value is passed directly into a
    SQL text-column parameter by teacher_ai_processor1.py."""
    database.db_pool.next_fetchall = []  # no KB rows -> no rerank call needed

    reply_generator.client.chat.completions.set_next(
        _fake_chat_response("Hi, thanks for the update - noted.")
    )
    result = teacher_reply_generator1.generate_teacher_reply(
        subject="Teacher Portal Message", body="Running 5 minutes late to class.",
        category="General", priority="Medium", thread_history="", message_id="t-1",
    )
    check(
        "Teacher Portal: normal reply is a plain str, not a tuple",
        isinstance(result, str) and result == "Hi, thanks for the update - noted.",
        f"got {result!r} (type={type(result).__name__})",
    )


def test_teacher_reply_staff_phrase_returns_plain_string_not_blocked():
    """Same return-type regression check (str, never a tuple), using a
    phrase that matches _TEACHER_FACING_LEAK_PATTERNS.

    This phrase used to trigger blocked_safety_net here (generate_reply()
    applied the regex unconditionally). The teacher-leak-fix task's senior
    review found that was itself a bug: this exact kind of internal-process
    wording is normal, correct Teacher Portal content, and blocking it
    silently emptied a legitimate draft (Teacher Portal has no
    requires_review field to surface the block). generate_reply() now only
    evaluates the regex for audience="parent"; teacher_reply_generator1.py
    passes audience="teacher", so this phrase must come through normally."""
    database.db_pool.next_fetchall = []
    reply_generator.client.chat.completions.set_next(
        _fake_chat_response("Our coordination team will identify a suitable rescheduled time.")
    )
    result = teacher_reply_generator1.generate_teacher_reply(
        subject="Teacher Portal Message", body="Can we reschedule?",
        category="General", priority="Medium", thread_history="", message_id="t-2",
    )
    check(
        "Teacher Portal: staff-process phrase is returned normally (str, not blocked, not a tuple)",
        isinstance(result, str) and result == "Our coordination team will identify a suitable rescheduled time.",
        f"got {result!r} (type={type(result).__name__})",
    )


def test_teacher_reply_no_reply_returns_empty_string_not_tuple():
    """Same regression check for the no_reply path."""
    database.db_pool.next_fetchall = []
    reply_generator.client.chat.completions.set_next(_fake_chat_response("NO_REPLY"))
    result = teacher_reply_generator1.generate_teacher_reply(
        subject="Teacher Portal Message", body="???",
        category="General", priority="Medium", thread_history="", message_id="t-3",
    )
    check(
        "Teacher Portal: no_reply returns '' (str), not a tuple",
        isinstance(result, str) and result == "",
        f"got {result!r} (type={type(result).__name__})",
    )


def test_teacher_reply_error_returns_empty_string_not_tuple():
    """Same regression check for the error path."""
    database.db_pool.next_fetchall = []
    reply_generator.client.chat.completions.set_next(RuntimeError("simulated failure"))
    result = teacher_reply_generator1.generate_teacher_reply(
        subject="Teacher Portal Message", body="Anything?",
        category="General", priority="Medium", thread_history="", message_id="t-4",
    )
    check(
        "Teacher Portal: generation error returns '' (str), not a tuple",
        isinstance(result, str) and result == "",
        f"got {result!r} (type={type(result).__name__})",
    )


def test_update_teacher_ai_fields_rolls_back_on_failure():
    """The other regression-review finding: a failed UPDATE must roll back
    before the connection returns to the pool, so a bad write can't poison
    the next borrower with an aborted transaction. Force cursor.execute()
    to raise, and confirm rollback() was called (and the exception still
    propagates, and the connection still gets returned to the pool
    exactly once, matching the existing try/except/finally convention
    already used elsewhere in database.py)."""
    calls = {"rollback": 0, "putconn": 0}

    class RaisingCursor:
        def execute(self, *a, **kw):
            raise RuntimeError("simulated bad parameter (e.g. a tuple, not text)")
        def close(self):
            pass

    class RaisingConnection:
        def cursor(self, cursor_factory=None):
            return RaisingCursor()
        def commit(self):
            pass
        def rollback(self):
            calls["rollback"] += 1

    real_getconn = database.db_pool.getconn
    real_putconn = database.db_pool.putconn
    database.db_pool.getconn = lambda: RaisingConnection()
    database.db_pool.putconn = lambda conn: calls.__setitem__("putconn", calls["putconn"] + 1)

    raised = False
    try:
        database.update_teacher_ai_fields(
            message_id="t-5", category="General", priority="Medium",
            summary="s", draft_reply="not a tuple, just checking rollback", row_id=1,
        )
    except RuntimeError:
        raised = True
    finally:
        database.db_pool.getconn = real_getconn
        database.db_pool.putconn = real_putconn

    check(
        "update_teacher_ai_fields rolls back and still raises on a failed write",
        raised and calls["rollback"] == 1 and calls["putconn"] == 1,
        f"raised={raised} rollback_calls={calls['rollback']} putconn_calls={calls['putconn']}",
    )


# ---------------------------------------------------------------------------
# D / E / F / G - rag_reranker.py's explicit error flag, both functions
# ---------------------------------------------------------------------------

_CANDIDATE_EMAIL = (23, "sender@x.com", "Sick child", "My child is sick today.", None, None, None, 0.91)
_CANDIDATE_KB = {"title": "Attendance Policy", "section": "Sick days", "content": "Notify us by 9am.", "similarity": 0.88}


def test_rerank_emails_success_with_results():
    """D: success, model selects a real candidate."""
    rag_reranker.client.chat.completions.set_next(
        _fake_chat_response(json.dumps({"selected": [{"id": 23, "reason": "Similar sick-day notice.", "confidence": 92}]}))
    )
    result = rag_reranker.rerank_emails("s", "b", [_CANDIDATE_EMAIL])
    check(
        "D. rerank_emails success-with-results has error=False and a selection",
        result["error"] is False and len(result["selected"]) == 1,
        f"got {result!r}",
    )


def test_rerank_emails_success_zero_results():
    """E: a genuine, correctly-empty selection must NOT be flagged as an error."""
    rag_reranker.client.chat.completions.set_next(
        _fake_chat_response(json.dumps({"selected": []}))
    )
    result = rag_reranker.rerank_emails("s", "b", [_CANDIDATE_EMAIL])
    check(
        "E. rerank_emails genuine empty selection has error=False (NOT True)",
        result["error"] is False and result["selected"] == [],
        f"got {result!r}",
    )


def test_rerank_emails_exception():
    """F: the call itself fails."""
    rag_reranker.client.chat.completions.set_next(RuntimeError("simulated network error"))
    result = rag_reranker.rerank_emails("s", "b", [_CANDIDATE_EMAIL])
    check(
        "F. rerank_emails exception has error=True and empty selection",
        result["error"] is True and result["selected"] == [],
        f"got {result!r}",
    )


def test_rerank_knowledge_success_and_exception():
    rag_reranker.client.chat.completions.set_next(
        _fake_chat_response(json.dumps({"selected": [{"index": 0, "reason": "Direct match.", "confidence": 95}]}))
    )
    ok_result = rag_reranker.rerank_knowledge("s", "b", [_CANDIDATE_KB])
    check(
        "rerank_knowledge success has error=False",
        ok_result["error"] is False and len(ok_result["selected"]) == 1,
        f"got {ok_result!r}",
    )

    rag_reranker.client.chat.completions.set_next(RuntimeError("simulated failure"))
    err_result = rag_reranker.rerank_knowledge("s", "b", [_CANDIDATE_KB])
    check(
        "rerank_knowledge exception has error=True",
        err_result["error"] is True and err_result["selected"] == [],
        f"got {err_result!r}",
    )


def test_search_knowledge_base_rerank_error_returns_none():
    """G: search_knowledge_base(rerank=True) must return None - not an
    empty list - when the underlying rerank_knowledge() call itself
    failed, so process_email.py can tell an infra failure apart from a
    real 'nothing relevant in the KB' outcome."""
    database.db_pool.next_fetchall = [
        ("Attendance Policy", "Sick days", "General", "Notify us by 9am.", "https://x", "help_center", "42", 0.9)
    ]
    rag_reranker.client.chat.completions.set_next(RuntimeError("simulated failure"))

    result = knowledge_search.search_knowledge_base("s", "b", rerank=True)
    check(
        "G. search_knowledge_base returns None on a rerank error (not [])",
        result is None,
        f"got {result!r}",
    )


def test_search_knowledge_base_genuine_empty_selection_returns_list():
    """Contrast case for G: a real 'nothing relevant' outcome from the
    reranker must still return a normal (empty) list, not None."""
    database.db_pool.next_fetchall = [
        ("Attendance Policy", "Sick days", "General", "Notify us by 9am.", "https://x", "help_center", "42", 0.9)
    ]
    rag_reranker.client.chat.completions.set_next(
        _fake_chat_response(json.dumps({"selected": []}))
    )

    result = knowledge_search.search_knowledge_base("s", "b", rerank=True)
    check(
        "search_knowledge_base genuine empty selection returns [] (not None)",
        result == [],
        f"got {result!r}",
    )


# ---------------------------------------------------------------------------
# A / B / C - edited_before_send comparison
#
# Mirrors main.py's _compute_edited_before_send() verbatim - kept in sync
# by inspection, not by import, because main.py additionally needs fastapi
# and apscheduler, neither of which are installed in this environment, and
# main.py has no seam to import just this one helper in isolation.
# ---------------------------------------------------------------------------

def _compute_edited_before_send(reply_body, ai_draft_reply):
    return (reply_body or "").strip() != (ai_draft_reply or "").strip()


def test_edited_before_send_unchanged():
    """A: human sent the AI draft exactly as generated."""
    draft = "Hi there,\n\nYour class starts Monday.\n\nBest,\nCoral Academy"
    check(
        "A. unchanged draft -> edited_before_send is False",
        _compute_edited_before_send(draft, draft) is False,
    )


def test_edited_before_send_edited():
    """B: human changed the wording before sending."""
    draft = "Hi there,\n\nYour class starts Monday.\n\nBest,\nCoral Academy"
    edited = "Hi there,\n\nYour class actually starts Tuesday.\n\nBest,\nCoral Academy"
    check(
        "B. edited draft -> edited_before_send is True",
        _compute_edited_before_send(edited, draft) is True,
    )


def test_edited_before_send_empty_or_null_draft():
    """C: no draft ever existed (None/empty) - must not crash, and a real
    reply differs from nothing."""
    check(
        "C1. None draft + real reply -> True, no crash",
        _compute_edited_before_send("A real hand-written reply.", None) is True,
    )
    check(
        "C2. empty-string draft + real reply -> True, no crash",
        _compute_edited_before_send("A real hand-written reply.", "") is True,
    )
    check(
        "C3. None draft + empty reply -> False (both are 'nothing'), no crash",
        _compute_edited_before_send("", None) is False,
    )


# ---------------------------------------------------------------------------
# P0-1: persisting edited_before_send / is_unedited_ai_reply
#
# database.update_final_reply, database.save_historical_email, and
# vector_search.search_similar_emails are the REAL functions (imported
# directly, not mirrored) - these exercise the actual SQL/params built by
# the new code, via the same FakeCursor/FakeConnection pool already used
# above.
# ---------------------------------------------------------------------------

def test_update_final_reply_persists_edited_before_send():
    """Unchanged/edited AI draft cases, at the persistence layer: the value
    _compute_edited_before_send() produces must actually be written to
    messages.edited_before_send alongside final_reply, not dropped."""
    database.update_final_reply(42, "The actual sent text.", True)
    sql = database.db_pool.last_sql
    params = database.db_pool.last_params
    check(
        "update_final_reply's UPDATE sets both final_reply and edited_before_send",
        "final_reply = %s" in sql and "edited_before_send = %s" in sql,
        f"got sql={sql!r}",
    )
    check(
        "update_final_reply binds (final_reply, edited_before_send, email_id) in order",
        params == ("The actual sent text.", True, 42),
        f"got params={params!r}",
    )


def test_update_final_reply_defaults_edited_before_send_to_none():
    """A call site that hasn't computed edited_before_send yet must record
    NULL/unknown, never a false 'sent unchanged' (FALSE)."""
    database.update_final_reply(7, "Some reply.")
    check(
        "update_final_reply defaults edited_before_send to None (unknown) when omitted",
        database.db_pool.last_params == ("Some reply.", None, 7),
        f"got params={database.db_pool.last_params!r}",
    )


def test_save_historical_email_defaults_to_trusted():
    """Existing human historical emails remain eligible: every current
    caller (learn_email_style.py's Sent Mail import) does not pass
    is_unedited_ai_reply - it must default to False (trusted)."""
    database.save_historical_email(
        message_id="m1", thread_id="t1", in_reply_to=None,
        sender="staff@coralacademy.com", recipient="parent@example.com",
        subject="s", body="b", sent_at=None, source_account="staff@coralacademy.com",
    )
    params = database.db_pool.last_params
    check(
        "save_historical_email defaults is_unedited_ai_reply to False (trusted) when omitted",
        params[-1] is False,
        f"got last param={params[-1]!r}",
    )


def test_save_historical_email_persists_unedited_ai_reply_flag():
    """The AI-draft-send path in main.py passes is_unedited_ai_reply
    explicitly - confirm it flows straight through to the INSERT."""
    database.save_historical_email(
        message_id="m2", thread_id="t2", in_reply_to=None,
        sender="staff@coralacademy.com", recipient="parent@example.com",
        subject="s", body="b", sent_at=None, source_account="staff@coralacademy.com",
        is_unedited_ai_reply=True,
    )
    check(
        "save_historical_email persists is_unedited_ai_reply=True through to the INSERT",
        database.db_pool.last_params[-1] is True,
        f"got last param={database.db_pool.last_params[-1]!r}",
    )
    check(
        "save_historical_email's INSERT column list includes is_unedited_ai_reply",
        "is_unedited_ai_reply" in database.db_pool.last_sql,
    )


def test_vector_search_excludes_unedited_ai_replies():
    """The actual enforcement point: search_similar_emails() must exclude
    is_unedited_ai_reply = TRUE rows from trusted style-example retrieval,
    while leaving the existing staff-sender restriction untouched."""
    import vector_search

    database.db_pool.next_fetchall = []
    vector_search.search_similar_emails("s", "b", embedding_client=FakeOpenAI())

    sql = database.db_pool.last_sql
    check(
        "search_similar_emails filters out is_unedited_ai_reply = TRUE rows",
        "is_unedited_ai_reply = FALSE" in sql,
        f"got sql={sql!r}",
    )
    check(
        "search_similar_emails still restricts to known staff senders (unrelated behavior preserved)",
        "sender = ANY(%s)" in sql,
        f"got sql={sql!r}",
    )


# ---------------------------------------------------------------------------
# Pricing knowledge-chunk fix: classes.pricing stores "amount" in cents
# (e.g. 2500 = $25.00), but embed_classes.py's Pricing chunk used to embed
# that raw JSON unconverted, letting the LLM read 2500 as $2,500. These
# tests exercise the real format_pricing()/insert_chunk() from
# embed_classes.py, not a mirror.
# ---------------------------------------------------------------------------

def test_format_pricing_2500_cents_usd_session():
    """Finance 101's actual stored value: amount=2500 -> $25.00/session,
    not $2,500."""
    result = embed_classes.format_pricing(
        {"regular": {"unit": "session", "amount": 2500, "currency": "usd", "value_type": "default"}}
    )
    check(
        "amount 2500 + USD + session -> '$25.00 per session'",
        result == "$25.00 per session",
        f"got {result!r}",
    )


def test_format_pricing_2000_cents_usd_session():
    """Every other class in the catalog: amount=2000 -> $20.00/session."""
    result = embed_classes.format_pricing(
        {"regular": {"unit": "session", "amount": 2000, "currency": "usd", "value_type": "default"}}
    )
    check(
        "amount 2000 + USD + session -> '$20.00 per session'",
        result == "$20.00 per session",
        f"got {result!r}",
    )


def test_pricing_chunk_no_longer_exposes_raw_cents_as_dollars():
    """The actual INSERT content (via the real insert_chunk()) must contain
    the converted dollar string, not the raw cents amount or a JSON dump -
    the exact regression this fix targets."""
    pricing = {"regular": {"unit": "session", "amount": 2500, "currency": "usd", "value_type": "default"}}

    cursor = database.db_pool.getconn().cursor()
    embed_classes.insert_chunk(
        cursor, "class-1", "Finance 101", "lifeskills",
        "Pricing", embed_classes.format_pricing(pricing), "https://example.com/finance-101",
    )
    chunk_content = database.db_pool.last_params[3]  # (title, section, subject, content, url, embedding, source_id)

    check(
        "Pricing chunk content contains the converted dollar amount",
        "$25.00 per session" in chunk_content,
        f"got content={chunk_content!r}",
    )
    check(
        "Pricing chunk content does NOT contain the raw cents value as a bare number",
        "2500" not in chunk_content and '"amount"' not in chunk_content,
        f"got content={chunk_content!r}",
    )


def test_format_pricing_multiple_tiers_labeled():
    """Not hardcoded to Finance 101's single "regular" tier - a pricing
    dict with more than one tier labels each line so they stay
    distinguishable."""
    result = embed_classes.format_pricing({
        "regular": {"unit": "session", "amount": 2500, "currency": "usd"},
        "sibling_discount": {"unit": "session", "amount": 2000, "currency": "usd"},
    })
    check(
        "multiple pricing tiers each get a labeled line",
        result == "Regular: $25.00 per session\nSibling Discount: $20.00 per session",
        f"got {result!r}",
    )


def test_format_pricing_missing_or_malformed_returns_none():
    """Handled safely (matches insert_chunk's existing empty-field
    behavior) rather than crashing on missing/empty/malformed pricing."""
    check("format_pricing(None) -> None", embed_classes.format_pricing(None) is None)
    check("format_pricing({}) -> None", embed_classes.format_pricing({}) is None)
    check(
        "format_pricing with non-numeric amount -> None",
        embed_classes.format_pricing({"regular": {"unit": "session", "amount": "call for price"}}) is None,
    )


def test_non_pricing_chunks_unaffected_by_the_fix():
    """Regression check: a normal string field (e.g. Description) still
    flows through insert_chunk() completely unchanged - the fix only
    touches the Pricing call site's argument, not insert_chunk() itself."""
    cursor = database.db_pool.getconn().cursor()
    embed_classes.insert_chunk(
        cursor, "class-1", "Finance 101", "lifeskills",
        "Description", "A fun intro to money basics.", "https://example.com/finance-101",
    )
    chunk_content = database.db_pool.last_params[3]
    check(
        "non-pricing chunk content is passed through unchanged",
        "A fun intro to money basics." in chunk_content,
        f"got content={chunk_content!r}",
    )


def test_is_unedited_ai_reply_derivation_matches_edited_before_send():
    """Mirrors main.py's wiring (is_unedited_ai_reply = not
    edited_before_send) for all three required cases at once."""
    check(
        "unedited AI reply (unchanged draft) -> is_unedited_ai_reply=True -> excluded from retrieval",
        (not _compute_edited_before_send("same text", "same text")) is True,
    )
    check(
        "edited AI reply -> is_unedited_ai_reply=False -> remains eligible for retrieval",
        (not _compute_edited_before_send("edited text", "original text")) is False,
    )
    check(
        "no draft ever existed -> treated as edited -> is_unedited_ai_reply=False -> remains eligible",
        (not _compute_edited_before_send("A real hand-written reply.", None)) is False,
    )


# ---------------------------------------------------------------------------
# J / K / L - the requires_review combination formula
#
# Mirrors the formula in process_email.py / main.py's _process_contact_form_
# enquiry() verbatim (same reasoning as above for why this isn't imported
# directly - process_email.py's full dependency chain, e.g. bs4/
# slack_notifications/trial_followup/subscription_cancel, is heavier still).
# ---------------------------------------------------------------------------

def _combine_requires_review(classifier_requires_review, retrieval_error, generation_status):
    return (
        classifier_requires_review
        or retrieval_error
        or generation_status in ("blocked_safety_net", "error")
    )


def test_requires_review_classifier_true():
    """J: classifier already said review is needed - must stay True."""
    check(
        "J. classifier requires_review=True -> final True",
        _combine_requires_review(True, False, "ok") is True,
    )


def test_requires_review_safety_block_forces_true():
    """K: classifier said False, but the safety net fired downstream - the
    bug this whole fix targets. Final value must be True."""
    check(
        "K. classifier False + safety-net block -> final True",
        _combine_requires_review(False, False, "blocked_safety_net") is True,
    )


def test_requires_review_retrieval_error_forces_true():
    """L: classifier said False, but retrieval/reranking errored."""
    check(
        "L. classifier False + retrieval error -> final True",
        _combine_requires_review(False, True, "ok") is True,
    )


def test_requires_review_no_false_positive():
    """Sanity check: a genuinely clean email must NOT be force-flagged."""
    check(
        "clean email (classifier False, no error, status ok) -> final False",
        _combine_requires_review(False, False, "ok") is False,
    )


def test_requires_review_no_reply_not_forced():
    """The model's own NO_REPLY sentinel is deliberately NOT in the
    forced-review set - it's treated as correct, cautious behavior, not a
    fault (see process_email.py's comment on this exact point)."""
    check(
        "no_reply status alone does NOT force review",
        _combine_requires_review(False, False, "no_reply") is False,
    )


# ---------------------------------------------------------------------------
# M - existing human-send path / no-auto-send regression (structural check)
#
# main.py itself can't be imported in this environment (fastapi/apscheduler
# not installed, see module docstring), so this is a source-level check
# rather than a runtime one: confirms the send route still requires a real
# submitted reply_body, and that generate_reply()'s new tuple return didn't
# leave a stale single-value unpack anywhere that would silently break the
# send path.
# ---------------------------------------------------------------------------

def test_send_route_still_requires_form_field():
    with open("main.py", "r", encoding="utf-8") as f:
        source = f.read()

    check(
        "M1. POST /email/{email_id}/send route still present",
        '@app.post("/email/{email_id}/send")' in source,
    )
    check(
        "M2. reply_body is still a required Form(...) field (no auto-send input)",
        "reply_body: str = Form(...)" in source,
    )
    check(
        "M3. generate_reply() call site unpacks the new (draft, status) tuple",
        "draft, generation_status = generate_reply(" in source,
    )


def test_process_email_unpacks_tuple_too():
    with open("process_email.py", "r", encoding="utf-8") as f:
        source = f.read()

    check(
        "process_email.py's generate_reply() call site unpacks (draft, status)",
        "draft, generation_status = generate_reply(" in source,
    )
    check(
        "process_email.py still calls save_email() with the combined requires_review",
        "requires_review=requires_review," in source,
    )


def main():
    test_generate_reply_normal()
    test_generate_reply_safety_net_blocked()
    test_generate_reply_no_reply_sentinel()
    test_generate_reply_error()

    test_teacher_reply_returns_plain_string_not_tuple()
    test_teacher_reply_staff_phrase_returns_plain_string_not_blocked()
    test_teacher_reply_no_reply_returns_empty_string_not_tuple()
    test_teacher_reply_error_returns_empty_string_not_tuple()
    test_update_teacher_ai_fields_rolls_back_on_failure()

    test_rerank_emails_success_with_results()
    test_rerank_emails_success_zero_results()
    test_rerank_emails_exception()
    test_rerank_knowledge_success_and_exception()

    test_search_knowledge_base_rerank_error_returns_none()
    test_search_knowledge_base_genuine_empty_selection_returns_list()

    test_edited_before_send_unchanged()
    test_edited_before_send_edited()
    test_edited_before_send_empty_or_null_draft()

    test_update_final_reply_persists_edited_before_send()
    test_update_final_reply_defaults_edited_before_send_to_none()
    test_save_historical_email_defaults_to_trusted()
    test_save_historical_email_persists_unedited_ai_reply_flag()
    test_vector_search_excludes_unedited_ai_replies()

    test_format_pricing_2500_cents_usd_session()
    test_format_pricing_2000_cents_usd_session()
    test_pricing_chunk_no_longer_exposes_raw_cents_as_dollars()
    test_format_pricing_multiple_tiers_labeled()
    test_format_pricing_missing_or_malformed_returns_none()
    test_non_pricing_chunks_unaffected_by_the_fix()

    test_is_unedited_ai_reply_derivation_matches_edited_before_send()

    test_requires_review_classifier_true()
    test_requires_review_safety_block_forces_true()
    test_requires_review_retrieval_error_forces_true()
    test_requires_review_no_false_positive()
    test_requires_review_no_reply_not_forced()

    test_send_route_still_requires_form_field()
    test_process_email_unpacks_tuple_too()

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {_failures}")
        sys.exit(1)
    else:
        print("All tests passed.")


if __name__ == "__main__":
    main()
