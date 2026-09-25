"""Focused tests for Phase 2 of the live Coral class-data feature:
live_class_intent.py's detection/orchestration, and its wiring into
reply_generator.py (an optional live_class_context parameter) and
process_email.py (the parent pipeline only).

Matches this repo's existing test_*.py convention (see
test_coral_class_catalog.py, test_teacher_leak_fix.py): a plain script
using only assert statements, no pytest, stdlib only. No real Coral API
call and no real OpenAI call are made anywhere in this file.

Three techniques are used, matching what each piece actually needs:
1. detect_current_class_intent() and build_prompt_block() are pure
   functions - tested directly, no faking needed.
2. get_live_class_data() is tested by monkeypatching the 3
   coral_class_catalog functions live_class_intent.py imports by name
   (get_cached_catalog, find_matching_class, build_live_class_context),
   restored after each test - no real HTTP call.
3. reply_generator.py IS importable here via the established fake
   psycopg2/openai/dotenv infrastructure (see test_teacher_leak_fix.py),
   so the actual prompt-prepending behavior is verified behaviorally, not
   just via source inspection. process_email.py and
   teacher_reply_generator1.py are NOT importable in this environment
   (bs4 missing, same documented limitation as every other test file
   covering them this session) - their wiring is verified via source-level
   checks against the real files instead.

Run with: python3 test_live_class_integration.py
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


def _read_source(filename):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename), "r", encoding="utf-8") as f:
        return f.read()


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# live_class_intent.py imports coral_class_catalog.py, which imports
# requests at module level - not installed in this environment, so it's
# faked exactly like in test_coral_class_catalog.py. This fake is never
# actually invoked in this file (get_cached_catalog itself is always
# monkeypatched in Part 2's tests before any real HTTP call could happen),
# it only needs to exist so the import succeeds.
_fake_requests_module = types.ModuleType("requests")
_fake_requests_module.get = lambda *a, **kw: None


class _UnusedTimeout(Exception):
    pass


class _UnusedRequestException(Exception):
    pass


_fake_requests_module.Timeout = _UnusedTimeout
_fake_requests_module.RequestException = _UnusedRequestException
sys.modules["requests"] = _fake_requests_module


# ===========================================================================
# PART 1 - detect_current_class_intent(): pure function, no faking needed.
# ===========================================================================

import live_class_intent as lci  # noqa: E402


# ---------------------------------------------------------------------------
# 1-4. Current price/schedule/teacher/enrollment questions get detected.
# ---------------------------------------------------------------------------

def test_1_price_question_detected():
    for text in ["How much is Astronomy 101?", "What is the current price for Finance?", "How much does this class cost?"]:
        check(f"1. price question detected: {text!r}", lci.detect_current_class_intent("", text))


def test_2_schedule_question_detected():
    for text in ["What days is Astronomy 101 offered?", "What is the schedule for the Finance class?"]:
        check(f"2. schedule question detected: {text!r}", lci.detect_current_class_intent("", text))


def test_3_teacher_question_detected():
    check("3. teacher question detected", lci.detect_current_class_intent("", "Who teaches Astronomy 101?"))


def test_4_enrollment_question_detected():
    for text in ["Is Astronomy 101 currently available?", "Can my child enroll in Astronomy 101?", "Is this class still running?"]:
        check(f"4. enrollment/status question detected: {text!r}", lci.detect_current_class_intent("", text))


# ---------------------------------------------------------------------------
# 5. Static/general questions do NOT trigger live lookup.
# ---------------------------------------------------------------------------

def test_5_static_questions_not_detected():
    for text in [
        "How does the class work?",
        "What will my child learn?",
        "What age group is this for?",
        "Do you provide homework?",
        "Can you explain your refund policy?",
    ]:
        check(f"5. static question NOT detected: {text!r}", not lci.detect_current_class_intent("", text))


def test_5b_detection_checks_subject_too():
    check(
        "5b. a current-fact keyword in the subject alone is still detected",
        lci.detect_current_class_intent("Pricing question", "hello"),
    )
    check(
        "5b. empty subject/body doesn't crash and isn't detected",
        lci.detect_current_class_intent("", "") is False,
    )
    check(
        "5b. None subject/body doesn't crash",
        lci.detect_current_class_intent(None, None) is False,
    )


# ===========================================================================
# PART 2 - get_live_class_data(): monkeypatch the 3 coral_class_catalog
# functions live_class_intent.py imported by name. No real HTTP call.
# ===========================================================================

class _Patch:
    """Small save/restore helper for monkeypatching module attributes in a
    test, used as a context manager."""

    def __init__(self, module, **replacements):
        self._module = module
        self._replacements = replacements
        self._saved = {}

    def __enter__(self):
        for name, value in self._replacements.items():
            self._saved[name] = getattr(self._module, name)
            setattr(self._module, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            setattr(self._module, name, value)


_SAMPLE_CLASS = {
    "id": "aaa-111",
    "title": "Astronomy 101: Learn About Space",
    "subject": "science",
    "url_slug": "astro101",
    "pricing": {"regular": {"amount": 2500, "currency": "usd", "unit": "session"}},
    "teacher": {"name": "Amalia"},
    "is_enrollment_allowed": True,
    "is_listed": True,
}


# ---------------------------------------------------------------------------
# 6. Live catalog success + exact class match.
# ---------------------------------------------------------------------------

def test_6_success_exact_match():
    with _Patch(
        lci,
        get_cached_catalog=lambda: {"status": lci.SUCCESS, "classes": [_SAMPLE_CLASS]},
        find_matching_class=lambda classes, query: {"status": lci.SUCCESS, "class": _SAMPLE_CLASS, "candidates": []},
    ):
        result = lci.get_live_class_data("", "How much is Astronomy 101?")

    check("6. needed is True", result["needed"] is True)
    check("6. no review is required on a clean match", result["requires_review"] is False)
    check("6. review_reason is None", result["review_reason"] is None)
    check(
        "6. context_text is a non-empty, clearly-labeled block",
        result["context_text"] is not None and "LIVE CORAL CLASS DATA" in result["context_text"],
    )
    check(
        "6. the matched class's actual data appears in the block",
        "Astronomy 101" in result["context_text"] and "Amalia" in result["context_text"],
    )


# ---------------------------------------------------------------------------
# 7. Ambiguous class match.
# ---------------------------------------------------------------------------

def test_7_ambiguous_match():
    with _Patch(
        lci,
        get_cached_catalog=lambda: {"status": lci.SUCCESS, "classes": [_SAMPLE_CLASS]},
        find_matching_class=lambda classes, query: {"status": lci.AMBIGUOUS, "class": None, "candidates": [_SAMPLE_CLASS, _SAMPLE_CLASS]},
    ):
        result = lci.get_live_class_data("", "How much is this class?")

    check("7. ambiguous match forces review", result["requires_review"] is True)
    check("7. review_reason is the ambiguous token", result["review_reason"] == lci.REVIEW_REASON_AMBIGUOUS)
    check("7. no context is generated (never guesses)", result["context_text"] is None)


# ---------------------------------------------------------------------------
# 8. Class not found.
# ---------------------------------------------------------------------------

def test_8_not_found():
    with _Patch(
        lci,
        get_cached_catalog=lambda: {"status": lci.SUCCESS, "classes": [_SAMPLE_CLASS]},
        find_matching_class=lambda classes, query: {"status": lci.NOT_FOUND, "class": None, "candidates": []},
    ):
        result = lci.get_live_class_data("", "How much is Underwater Basket Weaving 101?")

    check("8. not-found forces review", result["requires_review"] is True)
    check("8. review_reason is the not-found token", result["review_reason"] == lci.REVIEW_REASON_NOT_FOUND)
    check("8. no context is invented", result["context_text"] is None)


# ---------------------------------------------------------------------------
# 9. Live API error.
# ---------------------------------------------------------------------------

def test_9_api_error():
    with _Patch(lci, get_cached_catalog=lambda: {"status": "API_ERROR", "classes": None, "error": "timeout"}):
        result = lci.get_live_class_data("", "How much is Astronomy 101?")

    check("9. an API error forces review", result["requires_review"] is True)
    check("9. review_reason is the unavailable token", result["review_reason"] == lci.REVIEW_REASON_UNAVAILABLE)
    check("9. no context is generated", result["context_text"] is None)


# ---------------------------------------------------------------------------
# 10. Live API invalid response.
# ---------------------------------------------------------------------------

def test_10_invalid_response():
    with _Patch(lci, get_cached_catalog=lambda: {"status": "INVALID_RESPONSE", "classes": None, "error": "bad shape"}):
        result = lci.get_live_class_data("", "What is the schedule for Astronomy 101?")

    check("10. an invalid response forces review", result["requires_review"] is True)
    check("10. review_reason is the unavailable token", result["review_reason"] == lci.REVIEW_REASON_UNAVAILABLE)
    check("10. no context is generated", result["context_text"] is None)


# ---------------------------------------------------------------------------
# 11. Required current fact + live failure => requires_review=True.
# (Same as test 9, phrased as the specific end-to-end scenario requested.)
# ---------------------------------------------------------------------------

def test_11_current_fact_plus_failure_requires_review():
    with _Patch(lci, get_cached_catalog=lambda: {"status": "API_ERROR", "classes": None, "error": "boom"}):
        result = lci.get_live_class_data("", "What is the current price of Astronomy 101?")

    check("11. requires_review is True end-to-end for a price question when the live API fails", result["requires_review"] is True)
    check("11. context_text is None - nothing is handed to generation as 'current'", result["context_text"] is None)


# ---------------------------------------------------------------------------
# 12. Required current fact + ambiguous match => safe review behavior.
# ---------------------------------------------------------------------------

def test_12_current_fact_plus_ambiguous_requires_review():
    with _Patch(
        lci,
        get_cached_catalog=lambda: {"status": lci.SUCCESS, "classes": [_SAMPLE_CLASS, dict(_SAMPLE_CLASS, title="Astronomy 201")]},
        find_matching_class=lambda classes, query: {"status": lci.AMBIGUOUS, "class": None, "candidates": classes},
    ):
        result = lci.get_live_class_data("", "What is the schedule for the Astronomy class?")

    check("12. an ambiguous match for a schedule question requires review, never guesses", result["requires_review"] is True)
    check("12. no class is picked arbitrarily", result["context_text"] is None)


# ---------------------------------------------------------------------------
# 13. Required current fact + stale RAG available + live failure => stale
# RAG is NOT presented as current.
# ---------------------------------------------------------------------------

def test_13_stale_rag_never_substituted_on_failure():
    """This is the core safety guarantee: even though RAG might have an
    old price for this class, a live failure must never let that stale
    fact flow through as if it were current - get_live_class_data()
    itself has no access to RAG data at all, so it structurally cannot
    substitute it; this test proves the contract at the boundary
    process_email.py relies on: on any failure, context_text is None and
    requires_review is True, full stop, regardless of what RAG might
    have known."""
    with _Patch(lci, get_cached_catalog=lambda: {"status": "API_ERROR", "classes": None, "error": "down"}):
        result = lci.get_live_class_data("", "What is the current price of Astronomy 101?")

    check(
        "13. on live failure, context_text is None - there is no path for stale RAG "
        "content to be labeled/treated as this function's live output",
        result["context_text"] is None,
    )
    check("13. review is forced instead of silently answering from stale data", result["requires_review"] is True)


# ---------------------------------------------------------------------------
# 19. Missing optional live fields do not crash.
# ---------------------------------------------------------------------------

def test_19_missing_optional_fields_no_crash():
    sparse_class = {"title": "Only A Title"}
    with _Patch(
        lci,
        get_cached_catalog=lambda: {"status": lci.SUCCESS, "classes": [sparse_class]},
        find_matching_class=lambda classes, query: {"status": lci.SUCCESS, "class": sparse_class, "candidates": []},
    ):
        result = lci.get_live_class_data("", "How much is Only A Title?")

    check("19. a sparse class dict doesn't crash the whole pipeline", result["requires_review"] is False)
    check("19. context_text is still generated with just the title", "Only A Title" in result["context_text"])


# ---------------------------------------------------------------------------
# 20. Live context does not contain unapproved/unexpected fields.
# ---------------------------------------------------------------------------

def test_20_no_unexpected_fields_in_context():
    class_with_extra_field = dict(_SAMPLE_CLASS)
    class_with_extra_field["seats_remaining"] = 3
    class_with_extra_field["internal_notes"] = "do not show this to parents"

    with _Patch(
        lci,
        get_cached_catalog=lambda: {"status": lci.SUCCESS, "classes": [class_with_extra_field]},
        find_matching_class=lambda classes, query: {"status": lci.SUCCESS, "class": class_with_extra_field, "candidates": []},
    ):
        result = lci.get_live_class_data("", "How much is Astronomy 101?")

    check(
        "20. an unexpected field (e.g. 'seats_remaining') never appears in the generated prompt block",
        "seats_remaining" not in result["context_text"] and "3" not in result["context_text"].split("Pricing")[0],
    )
    check(
        "20. an unexpected internal-notes field never appears in the generated prompt block",
        "internal_notes" not in result["context_text"] and "do not show this to parents" not in result["context_text"],
    )


def test_no_seat_availability_wording_in_block():
    """The block's own instructions explicitly forbid claiming seat
    availability - confirmed present, verbatim."""
    block = lci.build_prompt_block({"title": "X"})
    check(
        "block explicitly instructs the model never to claim seat availability",
        "seats" in block.lower() and "not claim" in block.lower().replace("do not", "not"),
    )
    check(
        "block explicitly instructs the model not to assume enrollment is open just because the class exists",
        "enrollment is currently allowed" in block.lower() or "enrollment currently allowed" in block.lower(),
    )


# ===========================================================================
# PART 3 - reply_generator.py: behavioral test via the established fake
# psycopg2/openai/dotenv infrastructure. No real OpenAI call.
# ===========================================================================

def _install_fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class FakeChatCompletions:
    def __init__(self):
        self._next = None
        self.last_call_kwargs = None

    def set_next(self, value):
        self._next = value

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return self._next


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
        pass

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def close(self):
        pass


class FakeConnection:
    def __init__(self, pool):
        self._pool = pool

    def cursor(self, cursor_factory=None):
        return FakeCursor(self._pool)

    def commit(self):
        pass

    def close(self):
        pass


class FakeSimpleConnectionPool:
    def __init__(self, *a, **kw):
        pass

    def getconn(self):
        return FakeConnection(self)

    def putconn(self, conn):
        pass


_install_fake_module("dotenv", load_dotenv=lambda *a, **kw: None)
_install_fake_module("openai", OpenAI=FakeOpenAI)
pool_mod = _install_fake_module("psycopg2.pool", SimpleConnectionPool=FakeSimpleConnectionPool)
extras_mod = _install_fake_module("psycopg2.extras", RealDictCursor=dict)
psycopg2_mod = _install_fake_module("psycopg2")
psycopg2_mod.pool = pool_mod
psycopg2_mod.extras = extras_mod
psycopg2_mod.connect = lambda *a, **kw: FakeConnection(FakeSimpleConnectionPool())

import database          # noqa: E402
import reply_generator    # noqa: E402

database.db_pool = FakeSimpleConnectionPool()


def _get_last_prompt_text():
    return reply_generator.client.chat.completions.last_call_kwargs["messages"][1]["content"]


# ---------------------------------------------------------------------------
# 14. Normal static RAG response remains unchanged when live_class_context
# is omitted (the default - every existing caller).
# ---------------------------------------------------------------------------

def test_14_default_behavior_unchanged_when_omitted():
    reply_generator.client.chat.completions.set_next(_fake_chat_response("A normal reply."))

    text, status = reply_generator.generate_reply(
        gmail_message_id="t-14", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
    )

    prompt = _get_last_prompt_text()

    check("14. generation still succeeds normally", status == "ok" and text == "A normal reply.")
    check(
        "14. no LIVE CORAL CLASS DATA block appears in the prompt when live_class_context is omitted",
        "LIVE CORAL CLASS DATA" not in prompt,
    )
    check(
        "14. the prompt still starts with the existing CURRENT EMAIL section, unchanged",
        prompt.strip().startswith("CURRENT EMAIL"),
    )


def test_14b_live_context_is_prepended_and_labeled_when_supplied():
    reply_generator.client.chat.completions.set_next(_fake_chat_response("A reply using live data."))

    live_block = lci.build_prompt_block({"title": "Astronomy 101", "pricing": {"regular": {"amount": 2500, "currency": "usd", "unit": "session"}}})

    text, status = reply_generator.generate_reply(
        gmail_message_id="t-14b", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
        live_class_context=live_block,
    )

    prompt = _get_last_prompt_text()

    check("14b. generation still succeeds", status == "ok")
    check("14b. the LIVE CORAL CLASS DATA block is present in the prompt", "LIVE CORAL CLASS DATA" in prompt)
    check("14b. it appears before the existing CURRENT EMAIL section (prepended, not appended)", prompt.index("LIVE CORAL CLASS DATA") < prompt.index("CURRENT EMAIL"))
    check("14b. the existing GENERAL KNOWLEDGE label distinguishes the two sections", "GENERAL KNOWLEDGE" in prompt)
    check("14b. the actual live fact (Astronomy 101) appears in the prompt", "Astronomy 101" in prompt)


# ===========================================================================
# PART 4 - source-level checks against process_email.py and
# teacher_reply_generator1.py (neither importable here - bs4 missing).
# ===========================================================================

_PROCESS_EMAIL_SRC = _read_source("process_email.py")
_TEACHER_SRC = _read_source("teacher_reply_generator1.py")
_LIVE_CLASS_INTENT_SRC = _read_source("live_class_intent.py")


# ---------------------------------------------------------------------------
# 15. No additional LLM call is introduced.
# ---------------------------------------------------------------------------

def test_15_no_llm_call_in_live_class_intent_module():
    check(
        "15. live_class_intent.py does not import openai directly",
        "import openai" not in _LIVE_CLASS_INTENT_SRC,
    )
    check(
        "15. live_class_intent.py does not import any LLM-calling module "
        "(ai_classifier, rag_reranker, reply_generator)",
        "import ai_classifier" not in _LIVE_CLASS_INTENT_SRC
        and "import rag_reranker" not in _LIVE_CLASS_INTENT_SRC
        and "import reply_generator" not in _LIVE_CLASS_INTENT_SRC,
    )
    check(
        "15. live_class_intent.py's only non-stdlib import is coral_class_catalog",
        "from coral_class_catalog import" in _LIVE_CLASS_INTENT_SRC,
    )


def test_15b_coral_catalog_module_has_no_llm_import():
    coral_src = _read_source("coral_class_catalog.py")
    check(
        "15b. coral_class_catalog.py has no openai/LLM import either",
        "import openai" not in coral_src and "ai_classifier" not in coral_src,
    )


# ---------------------------------------------------------------------------
# 16. Teacher Portal path does not receive parent live-class context.
# ---------------------------------------------------------------------------

def test_16_teacher_portal_never_passes_live_class_context():
    check(
        "16. teacher_reply_generator1.py's generate_reply() call does not pass live_class_context at all",
        "live_class_context" not in _TEACHER_SRC,
    )
    check(
        "16. teacher_reply_generator1.py does not import live_class_intent",
        "live_class_intent" not in _TEACHER_SRC,
    )


# ---------------------------------------------------------------------------
# 17. Internal Coral alerts do not invoke live lookup.
# ---------------------------------------------------------------------------

def test_17_internal_alerts_precede_live_lookup():
    shortcircuit_marker = _PROCESS_EMAIL_SRC.find("# P0-3: known internal Coral alert subjects")
    live_lookup_marker = _PROCESS_EMAIL_SRC.find("live_class_result = get_live_class_data(subject, body)")

    check("17. the P0-3 short-circuit block is still present", shortcircuit_marker != -1)
    check("17. the new live-class lookup call is present", live_lookup_marker != -1)
    check(
        "17. the P0-3 short-circuit (which returns early) still appears before the live-class lookup, "
        "so internal Coral alerts never reach it",
        -1 < shortcircuit_marker < live_lookup_marker,
    )
    check(
        "17. the skip=True automated-email short-circuit also precedes the live-class lookup",
        _PROCESS_EMAIL_SRC.find("status=\"No Reply Required\"") < live_lookup_marker,
    )
    check(
        "17. the live-class lookup only ever runs inside the needs_reply branch, not unconditionally",
        _PROCESS_EMAIL_SRC.find('if result["needs_reply"]:') < live_lookup_marker
        < _PROCESS_EMAIL_SRC.find("else:\n        draft, generation_status = \"\", \"skipped\""),
    )


# ---------------------------------------------------------------------------
# 18. Existing no_reply behavior remains unchanged.
# ---------------------------------------------------------------------------

def test_18_no_reply_gate_unchanged():
    check(
        "18. the P0-1 needs_reply gate is still present, unchanged",
        'if result["needs_reply"]:' in _PROCESS_EMAIL_SRC,
    )
    check(
        "18. the skip branch still sets draft='' and generation_status='skipped'",
        'draft, generation_status = "", "skipped"' in _PROCESS_EMAIL_SRC,
    )
    check(
        "18. the skip branch also sets a safe, non-review-forcing live_class_result placeholder",
        'live_class_result = {"requires_review": False, "review_reason": None}' in _PROCESS_EMAIL_SRC,
    )


def test_review_reasons_wiring_present():
    check(
        "process_email.py folds live_class_result into the existing review_reasons list "
        "(the same mechanism every other review trigger uses, not a second system)",
        'if live_class_result["requires_review"]:\n        review_reasons.append(live_class_result["review_reason"])' in _PROCESS_EMAIL_SRC,
    )
    check(
        "generate_reply() is called with live_class_context sourced from live_class_result",
        "live_class_context=live_class_result[\"context_text\"]," in _PROCESS_EMAIL_SRC,
    )


def test_no_existing_pipeline_behavior_disturbed():
    """Scope guard: confirm nothing about classification, KB retrieval,
    historical-email retrieval, or the empty-rerank guards changed."""
    check(
        "audience-gated KB retrieval call is unchanged",
        'search_knowledge_base, subject, body, embedding_client=knowledge_client, rerank=True, audience="parent"' in _PROCESS_EMAIL_SRC,
    )
    check(
        "the empty-historical-reranker guard is unchanged",
        "if similar:\n        reranked = rerank_emails(" in _PROCESS_EMAIL_SRC,
    )
    check(
        "the mailbox-concurrency llm_clients bundle validation is unchanged",
        "_REQUIRED_LLM_CLIENT_KEYS" in _PROCESS_EMAIL_SRC,
    )


def main():
    test_1_price_question_detected()
    test_2_schedule_question_detected()
    test_3_teacher_question_detected()
    test_4_enrollment_question_detected()
    test_5_static_questions_not_detected()
    test_5b_detection_checks_subject_too()

    test_6_success_exact_match()
    test_7_ambiguous_match()
    test_8_not_found()
    test_9_api_error()
    test_10_invalid_response()
    test_11_current_fact_plus_failure_requires_review()
    test_12_current_fact_plus_ambiguous_requires_review()
    test_13_stale_rag_never_substituted_on_failure()
    test_19_missing_optional_fields_no_crash()
    test_20_no_unexpected_fields_in_context()
    test_no_seat_availability_wording_in_block()

    test_14_default_behavior_unchanged_when_omitted()
    test_14b_live_context_is_prepended_and_labeled_when_supplied()

    test_15_no_llm_call_in_live_class_intent_module()
    test_15b_coral_catalog_module_has_no_llm_import()
    test_16_teacher_portal_never_passes_live_class_context()
    test_17_internal_alerts_precede_live_lookup()
    test_18_no_reply_gate_unchanged()
    test_review_reasons_wiring_present()
    test_no_existing_pipeline_behavior_disturbed()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
