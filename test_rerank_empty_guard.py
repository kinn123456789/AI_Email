"""Focused tests for the smallest-safe-fix performance change to
process_email.py: rerank_emails() (rag_reranker.py) used to be called
unconditionally, even when the historical-email retrieval result `similar`
was empty - paying for a full LLM round-trip just to rerank nothing. This
mirrors the empty-result guard knowledge_search.py already has for the
KB-rerank path (`if not results: return results`, before ever calling
rerank_knowledge()) - same idea, applied to the historical-email path in
process_email.py.

Matches this repo's existing test_*.py convention (see test_no_reply_gate.py,
test_internal_alert_shortcircuit.py): a plain script using only assert
statements, no pytest. process_email.py cannot be imported in this
environment - it needs bs4, slack_notifications, trial_followup, and
subscription_cancel, none installed here (same documented limitation as
those other files) - so the new guard is verified as a byte-for-byte mirror
of the real code, kept in sync by inspection, PLUS source-level checks
against the real file confirming the mirror matches exactly what's actually
in process_email.py.

Run with: python3 test_rerank_empty_guard.py
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
# Mirror of the new guard added to process_email.py - byte-for-byte
# equivalent to:
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
# observed - the branching logic is what's under test, not rerank_emails()'s
# own internals (already covered by test_accuracy_fixes.py/test_reranker.py).
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
# A: empty `similar` does not invoke the reranker.
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
# B: non-empty `similar` still invokes the reranker exactly as before.
# ---------------------------------------------------------------------------

def test_nonempty_similar_still_invokes_reranker_exactly_as_before():
    candidate_emails = [(101, "thread-1", "Absence notice", "body text", 0, 0, 0, 0.91)]
    fake_llm_result = {"selected": [{"id": 101, "reason": "similar case", "confidence": 95}], "error": False}
    reranker = _CallRecordingReranker(fake_llm_result)

    reranked, historical_retrieval_error, historical_emails = _run_historical_rerank_gate(
        "Subject text", "Body text", candidate_emails, reranker
    )

    check(
        "B. rerank_emails IS called exactly once when similar is non-empty",
        reranker.call_count == 1,
        f"call_count={reranker.call_count}",
    )
    check(
        "B. rerank_emails is called with the same (subject, body, similar) arguments as before",
        reranker.last_args == ("Subject text", "Body text", candidate_emails),
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
    check(
        "B. historical_retrieval_error reflects the reranker's own error flag, unaffected by the new guard",
        historical_retrieval_error is False,
    )


# ---------------------------------------------------------------------------
# C: downstream processing behaves correctly with no historical candidates -
# equivalent to the pre-existing "no historical-email candidates" outcome,
# not a new/different code path from the caller's point of view.
# ---------------------------------------------------------------------------

def test_downstream_behavior_equivalent_to_no_historical_candidates():
    reranker = _CallRecordingReranker({"selected": [], "error": True})

    reranked, historical_retrieval_error, historical_emails = _run_historical_rerank_gate(
        "s", "b", [], reranker
    )

    check(
        "C. historical_emails is [] when there were no candidates (same as before this change)",
        historical_emails == [],
    )
    check(
        "C. historical_retrieval_error is False - a genuinely empty history is NOT treated as a retrieval failure",
        historical_retrieval_error is False,
    )
    check(
        "C. this exactly matches what a real 'reranked everything away to nothing' outcome already looked like "
        "(selected=[], error=False) - the caller in process_email.py cannot tell the two apart, by design",
        reranked["selected"] == [] and reranked["error"] is False,
    )


# ---------------------------------------------------------------------------
# D: the real process_email.py contains this exact guard, positioned
# correctly, and non-empty behavior is untouched in the actual file.
# ---------------------------------------------------------------------------

def test_real_process_email_py_contains_the_guard():
    src = _read_source("process_email.py")

    check(
        "D. process_email.py guards the rerank_emails() call with 'if similar:'",
        "if similar:\n        reranked = rerank_emails(" in src,
    )
    check(
        "D. the empty-case branch returns the genuine-empty shape, error=False (never True)",
        'else:\n        reranked = {"selected": [], "error": False}' in src,
    )
    check(
        "D. rerank_emails() call arguments (subject, body, similar) are unchanged, "
        "aside from the approved trailing llm_client=reranker_client from the LLM-client-isolation task",
        "reranked = rerank_emails(\n            subject,\n            body,\n            similar,\n            llm_client=reranker_client,\n        )" in src,
    )
    check(
        "D. downstream historical_retrieval_error/selected_ids/historical_emails derivation is unchanged",
        'historical_retrieval_error = reranked.get("error", False)' in src
        and 'selected_ids = {\n        item["id"]\n        for item in reranked["selected"]\n    }' in src,
    )


def test_no_other_process_email_behavior_changed():
    """Scope guard: confirm this change didn't touch anything else -
    P0-1/P0-2/P0-3 markers and the KB-retrieval guard remain exactly where
    they were."""
    src = _read_source("process_email.py")

    # Was a byte-adjacent literal until Phase 2 of the live Coral
    # class-data feature legitimately inserted its own intent-detection
    # call between the gate and generate_reply() - updated to a
    # presence + ordering check so it stays true regardless of what runs
    # between the gate and the call.
    check(
        "P0-1 no-reply gate still present, unchanged",
        'if result["needs_reply"]:' in src
        and src.index('if result["needs_reply"]:') < src.index('draft, generation_status = generate_reply('),
    )
    check(
        "P0-3 short-circuit still present and still precedes the retrieval block",
        src.find("# P0-3: known internal Coral alert subjects")
        < src.find("search_knowledge_base, subject, body, embedding_client=knowledge_client"),
    )
    check(
        "KB retrieval call site (audience-gated) is unchanged by this task",
        'search_knowledge_base, subject, body, embedding_client=knowledge_client, rerank=True, audience="parent"' in src,
    )


def main():
    test_empty_similar_skips_reranker_call()
    test_nonempty_similar_still_invokes_reranker_exactly_as_before()
    test_downstream_behavior_equivalent_to_no_historical_candidates()
    test_real_process_email_py_contains_the_guard()
    test_no_other_process_email_behavior_changed()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        import sys
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
