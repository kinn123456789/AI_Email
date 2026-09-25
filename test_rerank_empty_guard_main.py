"""Focused tests for the same empty-candidate rerank guard applied to the
second call site: main.py::_process_contact_form_enquiry(). Identical fix
and identical reasoning to test_rerank_empty_guard.py's process_email.py
coverage - rerank_emails() used to be called unconditionally here too, even
when the historical-email retrieval result `similar` was empty, paying for
a full LLM round-trip just to rerank nothing.

Matches this repo's existing test_*.py convention (see
test_rerank_empty_guard.py, test_no_reply_gate.py): a plain script using
only assert statements, no pytest. main.py cannot be imported in this
environment (same documented limitation as process_email.py - it needs the
full FastAPI app plus every route dependency) - so the new guard is
verified as a byte-for-byte mirror of the real code, kept in sync by
inspection, PLUS source-level checks against the real file confirming the
mirror matches exactly what's actually in main.py.

Run with: python3 test_rerank_empty_guard_main.py
"""

import os


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
# Mirror of the new guard added to main.py::_process_contact_form_enquiry() -
# byte-for-byte equivalent to:
#
#     if similar:
#         reranked = rerank_emails(subject, body, similar)
#     else:
#         reranked = {"selected": [], "error": False}
#     historical_retrieval_error = reranked.get("error", False)
#     selected_ids = {item["id"] for item in reranked["selected"]}
#     historical_emails = [email for email in similar if email[0] in selected_ids]
#
# rerank_emails_fn is injected here (instead of importing the real
# rag_reranker.rerank_emails) purely so call-count/call-arguments can be
# observed - the branching logic is what's under test.
# ---------------------------------------------------------------------------

def _run_historical_rerank_gate(subject, body, similar, rerank_emails_fn):
    if similar:
        reranked = rerank_emails_fn(subject, body, similar)
    else:
        reranked = {"selected": [], "error": False}

    historical_retrieval_error = reranked.get("error", False)
    selected_ids = {item["id"] for item in reranked["selected"]}
    historical_emails = [email for email in similar if email[0] in selected_ids]

    return reranked, historical_retrieval_error, historical_emails


class _CallRecordingReranker:
    """Stands in for rag_reranker.rerank_emails - records whether/how it
    was called instead of making a real LLM call."""

    def __init__(self, return_value):
        self.call_count = 0
        self.last_args = None
        self._return_value = return_value

    def __call__(self, subject, body, candidates):
        self.call_count += 1
        self.last_args = (subject, body, candidates)
        return self._return_value


# ---------------------------------------------------------------------------
# A: empty `similar` skips rerank_emails.
# ---------------------------------------------------------------------------

def test_empty_similar_skips_reranker_call():
    reranker = _CallRecordingReranker({"selected": [], "error": True})  # would prove itself wrong if called

    reranked, historical_retrieval_error, historical_emails = _run_historical_rerank_gate(
        "s", "b", [], reranker
    )

    check(
        "A. rerank_emails is not called at all when similar=[]",
        reranker.call_count == 0,
        f"call_count={reranker.call_count}",
    )
    check(
        "A. reranked shape for the skipped case is {'selected': [], 'error': False} - a genuine empty result, not an error",
        reranked == {"selected": [], "error": False},
        f"got {reranked!r}",
    )


# ---------------------------------------------------------------------------
# B: non-empty `similar` still calls rerank_emails exactly once with
# unchanged arguments.
# ---------------------------------------------------------------------------

def test_nonempty_similar_still_invokes_reranker_exactly_as_before():
    candidate_emails = [(202, "thread-2", "Enrollment question", "body text", 0, 0, 0, 0.88)]
    fake_llm_result = {"selected": [{"id": 202, "reason": "similar case", "confidence": 90}], "error": False}
    reranker = _CallRecordingReranker(fake_llm_result)

    reranked, historical_retrieval_error, historical_emails = _run_historical_rerank_gate(
        "Contact form subject", "Contact form body", candidate_emails, reranker
    )

    check(
        "B. rerank_emails IS called exactly once when similar is non-empty",
        reranker.call_count == 1,
        f"call_count={reranker.call_count}",
    )
    check(
        "B. rerank_emails is called with the same (subject, body, similar) arguments as before",
        reranker.last_args == ("Contact form subject", "Contact form body", candidate_emails),
        f"got {reranker.last_args!r}",
    )
    check(
        "B. the reranker's real return value is used unchanged (not overridden by the empty-case shape)",
        reranked is fake_llm_result,
    )
    check(
        "B. non-empty candidates still get selected/mapped into historical_emails as before",
        historical_emails == candidate_emails,
        f"got {historical_emails!r}",
    )


# ---------------------------------------------------------------------------
# C: empty result remains error=False and does not become a retrieval error.
# ---------------------------------------------------------------------------

def test_empty_result_is_not_a_retrieval_error():
    reranker = _CallRecordingReranker({"selected": [], "error": True})

    reranked, historical_retrieval_error, historical_emails = _run_historical_rerank_gate(
        "s", "b", [], reranker
    )

    check(
        "C. historical_retrieval_error is False for the skipped/empty case - never treated as a retrieval failure",
        historical_retrieval_error is False,
    )
    check(
        "C. historical_emails is [] when there were no candidates (same as before this change)",
        historical_emails == [],
    )


# ---------------------------------------------------------------------------
# D: the real main.py contains this exact guard, positioned correctly.
# ---------------------------------------------------------------------------

def test_real_main_py_contains_the_guard():
    src = _read_source("main.py")

    check(
        "D. main.py guards the rerank_emails() call with 'if similar:'",
        "if similar:\n        reranked = rerank_emails(subject, body, similar)" in src,
    )
    check(
        "D. the empty-case branch returns the genuine-empty shape, error=False (never True)",
        'else:\n        reranked = {"selected": [], "error": False}' in src,
    )
    check(
        "D. downstream historical_retrieval_error/selected_ids/historical_emails derivation is unchanged",
        'historical_retrieval_error = reranked.get("error", False)' in src
        and 'selected_ids = {item["id"] for item in reranked["selected"]}' in src
        and 'historical_emails = [email for email in similar if email[0] in selected_ids]' in src,
    )
    check(
        "D. generate_reply() call immediately after is unchanged (still receives historical_emails, audience=\"parent\")",
        'historical_emails,\n        knowledge,\n        source="contact_form",\n        customer_name=customer_name,\n        audience="parent",' in src,
    )


def main():
    test_empty_similar_skips_reranker_call()
    test_nonempty_similar_still_invokes_reranker_exactly_as_before()
    test_empty_result_is_not_a_retrieval_error()
    test_real_main_py_contains_the_guard()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        import sys
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
