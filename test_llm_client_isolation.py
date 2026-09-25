"""Focused tests for the LLM-client-isolation plumbing: ai_triage(),
rerank_knowledge(), rerank_emails(), generate_reply(), and
search_knowledge_base() all gained an optional llm_client parameter (and
process_email() an optional llm_clients bundle), so a future mailbox
worker can supply its own isolated OpenAI-family clients instead of
sharing the module-level singletons across concurrently-running mailbox
workers - the same concurrency hazard embedding_service.py already solved
for embeddings via new_embedding_client(), extended here to
classification/reranking/generation.

Matches this repo's existing test_*.py convention (see
test_teacher_leak_fix.py, test_rerank_empty_guard.py): a plain script using
only assert statements, no pytest. ai_classifier.py, rag_reranker.py,
reply_generator.py, and knowledge_search.py ARE importable via the
established fake psycopg2/openai/dotenv infrastructure, so sections A-E are
genuine behavioral tests, not mirrors. process_email.py cannot be imported
in this environment (needs bs4, slack_notifications, trial_followup,
subscription_cancel, none installed here - same documented limitation as
test_rerank_empty_guard.py) - section F verifies its bundle-validation
logic as a byte-for-byte mirror, kept in sync by inspection, PLUS
source-level checks against the real file.

Run with: python3 test_llm_client_isolation.py
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


# ---------------------------------------------------------------------------
# Fake infrastructure - identical technique to test_teacher_leak_fix.py /
# test_accuracy_fixes.py, so ai_classifier.py, rag_reranker.py,
# reply_generator.py, and knowledge_search.py can be imported and run for
# real without openai/psycopg2 actually installed.
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
        return types.SimpleNamespace(
            data=[types.SimpleNamespace(embedding=[0.1] * 8)]
        )


class FakeOpenAI:
    def __init__(self, *a, **kw):
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())
        self.embeddings = FakeEmbeddings()

    def close(self):
        pass


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
import database          # noqa: E402
import ai_classifier     # noqa: E402
import rag_reranker      # noqa: E402
import reply_generator   # noqa: E402
import knowledge_search  # noqa: E402

database.db_pool = FakeSimpleConnectionPool()


class _CallRecordingClient:
    """A fake OpenAI-family client that records whether/how its chat
    completions endpoint was invoked, distinct from the module-level
    FakeOpenAI() instance each module already has - so tests can prove
    *which* client object actually made the call."""

    def __init__(self, response_content):
        self.call_count = 0
        self.chat = types.SimpleNamespace(completions=self)
        self._response_content = response_content

    def create(self, **kwargs):
        self.call_count += 1
        return _fake_chat_response(self._response_content)


# ---------------------------------------------------------------------------
# A: ai_classifier.ai_triage()
# ---------------------------------------------------------------------------

_CLASSIFY_JSON = (
    '{"category": "General", "priority": "Low", "summary": "s", '
    '"requires_review": false, "confidence": 90, "needs_reply": true, '
    '"reply_type": "automatic"}'
)


def test_A_ai_triage_uses_injected_client():
    injected = _CallRecordingClient(_CLASSIFY_JSON)
    ai_classifier.client.chat.completions.set_next(
        _fake_chat_response("SHOULD NOT BE USED")
    )

    result = ai_classifier.ai_triage("s", "b", llm_client=injected)

    check(
        "A. ai_triage() uses the injected llm_client when supplied",
        injected.call_count == 1,
        f"call_count={injected.call_count}",
    )
    check(
        "A. ai_triage() returns the injected client's response, not the module client's",
        result["category"] == "General",
    )


def test_A_ai_triage_default_uses_module_client():
    ai_classifier.client.chat.completions.set_next(_fake_chat_response(_CLASSIFY_JSON))

    result = ai_classifier.ai_triage("s", "b")

    check(
        "A. ai_triage() with no llm_client still uses the module-level client (unchanged default behavior)",
        result["category"] == "General",
    )


# ---------------------------------------------------------------------------
# B: rag_reranker.rerank_knowledge()
# ---------------------------------------------------------------------------

_KNOWLEDGE_CANDIDATE = {
    "title": "Attendance Policy", "section": "Sick days", "category": "General",
    "content": "Notify us by 9am.", "url": "https://x", "source": "help_center",
    "source_id": "1", "similarity": 0.9,
}


def test_B_rerank_knowledge_uses_injected_client():
    injected = _CallRecordingClient('{"selected": [{"index": 0, "reason": "r", "confidence": 90}]}')
    rag_reranker.client.chat.completions.set_next(
        _fake_chat_response("SHOULD NOT BE USED")
    )

    result = rag_reranker.rerank_knowledge("s", "b", [_KNOWLEDGE_CANDIDATE], llm_client=injected)

    check(
        "B. rerank_knowledge() uses the injected llm_client when supplied",
        injected.call_count == 1,
        f"call_count={injected.call_count}",
    )
    check(
        "B. rerank_knowledge() result reflects the injected client's response",
        result["selected"] == [{"index": 0, "reason": "r", "confidence": 90}] and result["error"] is False,
    )


def test_B_rerank_knowledge_default_uses_module_client():
    rag_reranker.client.chat.completions.set_next(
        _fake_chat_response('{"selected": []}')
    )

    result = rag_reranker.rerank_knowledge("s", "b", [_KNOWLEDGE_CANDIDATE])

    check(
        "B. rerank_knowledge() with no llm_client still uses the module-level client (unchanged default behavior)",
        result == {"selected": [], "error": False},
    )


# ---------------------------------------------------------------------------
# C: rag_reranker.rerank_emails()
# ---------------------------------------------------------------------------

_EMAIL_CANDIDATE = (101, "thread-1", "Absence notice", "body text", 0, 0, 0, 0.91)


def test_C_rerank_emails_uses_injected_client():
    injected = _CallRecordingClient('{"selected": [{"id": 101, "reason": "r", "confidence": 95}]}')
    rag_reranker.client.chat.completions.set_next(
        _fake_chat_response("SHOULD NOT BE USED")
    )

    result = rag_reranker.rerank_emails("s", "b", [_EMAIL_CANDIDATE], llm_client=injected)

    check(
        "C. rerank_emails() uses the injected llm_client when supplied",
        injected.call_count == 1,
        f"call_count={injected.call_count}",
    )
    check(
        "C. rerank_emails() result reflects the injected client's response",
        result["selected"] == [{"id": 101, "reason": "r", "confidence": 95}] and result["error"] is False,
    )


def test_C_rerank_emails_default_uses_module_client():
    rag_reranker.client.chat.completions.set_next(
        _fake_chat_response('{"selected": []}')
    )

    result = rag_reranker.rerank_emails("s", "b", [_EMAIL_CANDIDATE])

    check(
        "C. rerank_emails() with no llm_client still uses the module-level client (unchanged default behavior)",
        result == {"selected": [], "error": False},
    )


# ---------------------------------------------------------------------------
# D: reply_generator.generate_reply()
# ---------------------------------------------------------------------------

def test_D_generate_reply_uses_injected_client():
    injected = _CallRecordingClient("Thanks for reaching out.")
    reply_generator.client.chat.completions.set_next(
        _fake_chat_response("SHOULD NOT BE USED")
    )

    text, status = reply_generator.generate_reply(
        gmail_message_id="gr-1", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
        llm_client=injected,
    )

    check(
        "D. generate_reply() uses the injected llm_client when supplied",
        injected.call_count == 1,
        f"call_count={injected.call_count}",
    )
    check(
        "D. generate_reply() returns the injected client's response",
        status == "ok" and text == "Thanks for reaching out.",
    )


def test_D_generate_reply_default_uses_module_client():
    reply_generator.client.chat.completions.set_next(
        _fake_chat_response("Default draft.")
    )

    text, status = reply_generator.generate_reply(
        gmail_message_id="gr-2", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
    )

    check(
        "D. generate_reply() with no llm_client still uses the module-level client (unchanged default behavior)",
        status == "ok" and text == "Default draft.",
    )


# ---------------------------------------------------------------------------
# E: knowledge_search.search_knowledge_base() forwards llm_client to
# rerank_knowledge().
# ---------------------------------------------------------------------------

_TEACHING_ROW_TUPLE = (
    "Attendance Policy", "Sick days", "General", "Notify us by 9am.",
    "https://x", "help_center", "42", 0.9,
)


def test_E_search_knowledge_base_forwards_llm_client():
    injected = _CallRecordingClient('{"selected": [{"index": 0, "reason": "r", "confidence": 90}]}')
    database.db_pool.next_fetchall = [_TEACHING_ROW_TUPLE]

    results = knowledge_search.search_knowledge_base(
        "s", "b", rerank=True, llm_client=injected
    )

    check(
        "E. search_knowledge_base() forwards llm_client to rerank_knowledge(), which uses it",
        injected.call_count == 1,
        f"call_count={injected.call_count}",
    )
    check(
        "E. the reranked selection (via the injected client) is reflected in the returned results",
        len(results) == 1 and results[0]["title"] == "Attendance Policy",
    )


# ---------------------------------------------------------------------------
# F: process_email.py - source-level checks + a byte-for-byte mirror of the
# bundle-validation logic (process_email.py cannot be imported here - see
# module docstring).
# ---------------------------------------------------------------------------

_REQUIRED_LLM_CLIENT_KEYS = frozenset({
    "classifier",
    "reranker",
    "generator",
    "similar_embedding",
    "knowledge_embedding",
})


def _mirror_validate_llm_clients(llm_clients):
    """Byte-for-byte mirror of process_email()'s validation block:

        if llm_clients is not None:
            if set(llm_clients.keys()) != _REQUIRED_LLM_CLIENT_KEYS:
                raise ValueError(
                    "Invalid mailbox LLM client bundle: expected "
                    + ", ".join(sorted(_REQUIRED_LLM_CLIENT_KEYS))
                )
            ...
            owns_embedding_clients = False
        else:
            ...
            owns_embedding_clients = True

    Returns owns_embedding_clients for a valid bundle (or None); raises
    ValueError for an invalid one, exactly like the real function.
    """
    if llm_clients is not None:
        if set(llm_clients.keys()) != _REQUIRED_LLM_CLIENT_KEYS:
            raise ValueError(
                "Invalid mailbox LLM client bundle: expected "
                + ", ".join(sorted(_REQUIRED_LLM_CLIENT_KEYS))
            )
        return False
    return True


_COMPLETE_BUNDLE = {
    "classifier": object(),
    "reranker": object(),
    "generator": object(),
    "similar_embedding": object(),
    "knowledge_embedding": object(),
}


def test_F_llm_clients_none_preserves_existing_behavior():
    owns = _mirror_validate_llm_clients(None)
    check(
        "F. llm_clients=None -> owns_embedding_clients=True (fresh clients created/closed exactly as before)",
        owns is True,
    )


def test_F_complete_bundle_is_accepted():
    owns = _mirror_validate_llm_clients(dict(_COMPLETE_BUNDLE))
    check(
        "F. a complete 5-key bundle is accepted -> owns_embedding_clients=False (caller owns closing)",
        owns is False,
    )


def test_F_incomplete_bundle_raises_valueerror():
    incomplete = dict(_COMPLETE_BUNDLE)
    del incomplete["reranker"]

    try:
        _mirror_validate_llm_clients(incomplete)
        check("F. an incomplete bundle (missing 'reranker') raises ValueError", False, "no exception raised")
    except ValueError as e:
        check(
            "F. an incomplete bundle (missing 'reranker') raises ValueError",
            True,
        )
        check(
            "F. the ValueError message names the expected keys",
            "expected" in str(e) and "reranker" in str(e),
            f"got: {e}",
        )


def test_F_extra_key_bundle_raises_valueerror():
    malformed = dict(_COMPLETE_BUNDLE)
    malformed["unexpected_extra_key"] = object()

    try:
        _mirror_validate_llm_clients(malformed)
        check("F. a bundle with an extra/unexpected key raises ValueError", False, "no exception raised")
    except ValueError:
        check("F. a bundle with an extra/unexpected key raises ValueError", True)


def test_F_empty_bundle_raises_valueerror():
    try:
        _mirror_validate_llm_clients({})
        check("F. an empty bundle raises ValueError (not silently treated as 'no bundle')", False, "no exception raised")
    except ValueError:
        check("F. an empty bundle raises ValueError (not silently treated as 'no bundle')", True)


def test_F_real_process_email_py_contains_the_validation():
    src = _read_source("process_email.py")

    check(
        "F. process_email.py defines _REQUIRED_LLM_CLIENT_KEYS with exactly the 5 expected keys",
        '_REQUIRED_LLM_CLIENT_KEYS = frozenset({\n    "classifier",\n    "reranker",\n    "generator",\n    "similar_embedding",\n    "knowledge_embedding",\n})' in src,
    )
    check(
        "F. process_email() signature gains llm_clients=None as the final parameter",
        "def process_email(msg, account, ingested_via=None, gmail_internal_id=None, llm_clients=None):" in src,
    )
    check(
        "F. an incomplete/malformed bundle raises ValueError with the exact expected message shape",
        'if set(llm_clients.keys()) != _REQUIRED_LLM_CLIENT_KEYS:\n            raise ValueError(\n                "Invalid mailbox LLM client bundle: expected "' in src,
    )
    check(
        "F. owns_embedding_clients=False is set on the injected-bundle path",
        'owns_embedding_clients = False' in src,
    )
    check(
        "F. owns_embedding_clients=True is set on the default (llm_clients=None) path",
        'owns_embedding_clients = True' in src,
    )
    check(
        "F. the finally block only closes embedding clients when this call owns them "
        "(externally supplied clients are never closed here)",
        "finally:\n        if owns_embedding_clients:\n            close_embedding_client(similar_client)\n            close_embedding_client(knowledge_client)" in src,
    )


def test_F_bundle_clients_reach_the_correct_downstream_calls():
    src = _read_source("process_email.py")

    check(
        "F. classifier_client is extracted from llm_clients['classifier']",
        'classifier_client = llm_clients["classifier"]' in src,
    )
    check(
        "F. reranker_client is extracted from llm_clients['reranker']",
        'reranker_client = llm_clients["reranker"]' in src,
    )
    check(
        "F. generator_client is extracted from llm_clients['generator']",
        'generator_client = llm_clients["generator"]' in src,
    )
    check(
        "F. similar_client is extracted from llm_clients['similar_embedding']",
        'similar_client = llm_clients["similar_embedding"]' in src,
    )
    check(
        "F. knowledge_client is extracted from llm_clients['knowledge_embedding']",
        'knowledge_client = llm_clients["knowledge_embedding"]' in src,
    )
    check(
        "F. ai_triage() is submitted with llm_client=classifier_client",
        "ai_triage, subject, body, history=history_text, images=image_data_list, gmail_message_id=message_id, llm_client=classifier_client" in src,
    )
    check(
        "F. search_knowledge_base() is submitted with llm_client=reranker_client",
        'search_knowledge_base, subject, body, embedding_client=knowledge_client, rerank=True, audience="parent", llm_client=reranker_client' in src,
    )
    check(
        "F. rerank_emails() is called with llm_client=reranker_client",
        "similar,\n            llm_client=reranker_client,\n        )" in src,
    )
    check(
        "F. generate_reply() is called with llm_client=generator_client",
        "audience=\"parent\",\n            llm_client=generator_client,\n        )" in src,
    )


def test_F_threadpoolexecutor_structurally_unchanged():
    """The existing 3-way per-message concurrency must remain exactly as
    it was - same max_workers, same 3 submitted calls, no new layer of
    concurrency added."""
    src = _read_source("process_email.py")

    check(
        "F. ThreadPoolExecutor(max_workers=3) is unchanged - still exactly 3 workers",
        "with ThreadPoolExecutor(max_workers=3) as executor:" in src,
    )
    check(
        "F. exactly one ThreadPoolExecutor is used in process_email.py (no new concurrency layer added)",
        src.count("ThreadPoolExecutor(") == 1,
    )


def main():
    test_A_ai_triage_uses_injected_client()
    test_A_ai_triage_default_uses_module_client()
    test_B_rerank_knowledge_uses_injected_client()
    test_B_rerank_knowledge_default_uses_module_client()
    test_C_rerank_emails_uses_injected_client()
    test_C_rerank_emails_default_uses_module_client()
    test_D_generate_reply_uses_injected_client()
    test_D_generate_reply_default_uses_module_client()
    test_E_search_knowledge_base_forwards_llm_client()
    test_F_llm_clients_none_preserves_existing_behavior()
    test_F_complete_bundle_is_accepted()
    test_F_incomplete_bundle_raises_valueerror()
    test_F_extra_key_bundle_raises_valueerror()
    test_F_empty_bundle_raises_valueerror()
    test_F_real_process_email_py_contains_the_validation()
    test_F_bundle_clients_reach_the_correct_downstream_calls()
    test_F_threadpoolexecutor_structurally_unchanged()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
