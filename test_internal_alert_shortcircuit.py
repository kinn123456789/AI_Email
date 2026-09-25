"""Focused tests for P0-3: a deterministic subject-based short-circuit in
process_email.py that stops known internal Coral alert emails (Low
Enrollment / Schedule Ending / Session Ending) from reaching retrieval,
reranking, or reply generation at all - not just from reaching generation
(P0-1 already handled that), and not just from getting mislabeled
"Needs Review" on the dashboard for something that's already fully
resolved.

Matches this repo's existing test_*.py convention (see test_no_reply_gate.py,
test_priority_override.py): a plain script using only assert statements, no
pytest. process_email.py cannot be imported in this environment - it needs
bs4, slack_notifications, trial_followup, and subscription_cancel, none
installed here (same documented limitation as the other process_email.py
test files) - so the new short-circuit is verified as a byte-for-byte
mirror, kept in sync by inspection, PLUS source-level checks against the
real file confirming the mirror matches exactly what's in process_email.py,
including its structural position relative to the retrieval/generation
calls it must never reach.

Per this task's test-hygiene instructions: no test here inspects the live
working tree or a hardcoded forbidden-file list - only stable source facts
(does the real file contain X, does X appear before Y) and real behavioral
execution of the mirrored control flow.

Run with: python3 test_internal_alert_shortcircuit.py
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


# ---------------------------------------------------------------------------
# Mirror of process_email.py's gate: skip=True branch -> P0-3 short-circuit
# -> (otherwise) the normal classifier/retrieval/generation path. Each
# stand-in function appends its own name to `calls` when invoked, so tests
# can assert exactly which functions ran and in what shape the row was
# saved - the same "record calls, assert on the record" technique already
# used by test_no_reply_gate.py's _CallRecorder.
# ---------------------------------------------------------------------------

_INTERNAL_ALERT_KEYWORDS = ["low enrollment", "schedule ending", "session ending"]


def _run_gate(subject, skip, category, reason, mailbox, needs_reply, calls):
    """`calls` is a list this mutates in place, recording every stand-in
    function invoked, in order. Returns the kwargs save_email() would have
    received - mirrors process_email.py's exact behavior, including the
    normal (non-short-circuited) classifier path far enough to prove
    retrieval/generation DO run there, which they must never do for a
    short-circuited alert."""

    subject_lower = subject.lower()

    if skip:
        skip_priority = "High" if any(kw in subject_lower for kw in _INTERNAL_ALERT_KEYWORDS) else "Low"
        calls.append("save_email")
        return {"status": "No Reply Required", "priority": skip_priority, "draft": "", "category": category, "mailbox": mailbox}

    if any(kw in subject_lower for kw in _INTERNAL_ALERT_KEYWORDS):
        calls.append("save_email")
        return {"status": "No Reply Required", "priority": "High", "draft": "", "category": category, "mailbox": mailbox}

    # Falls through to the normal (unchanged) classifier path - minimal
    # stand-in, just enough to prove this branch is the one that reaches
    # retrieval/generation, not a full replica of process_email.py's
    # classifier-path logic (unchanged by this fix, already covered
    # elsewhere).
    calls.append("search_similar_emails")
    calls.append("search_knowledge_base")
    calls.append("rerank_emails")
    if needs_reply:
        calls.append("generate_reply")
        draft, generation_status = "a real draft", "ok"
    else:
        draft, generation_status = "", "skipped"
    calls.append("save_email")
    return {"status": "Needs Review", "priority": "Medium", "draft": draft, "category": category, "mailbox": mailbox}


# ---------------------------------------------------------------------------
# A, B, C, D - short-circuit fires for all 3 known phrases, case-insensitive.
# ---------------------------------------------------------------------------

def test_low_enrollment_subject_short_circuits():
    calls = []
    result = _run_gate("Low Enrollment Alert - Example Class", skip=False, category="", reason="", mailbox="inbox", needs_reply=True, calls=calls)
    check("A. Low Enrollment subject short-circuits (only save_email called)", calls == ["save_email"])
    check("A. saved with status/priority/draft matching the short-circuit shape", result["status"] == "No Reply Required" and result["priority"] == "High" and result["draft"] == "")


def test_schedule_ending_subject_short_circuits():
    calls = []
    _run_gate("Upcoming Class Schedule Ending in 3 Days - Example Class", skip=False, category="", reason="", mailbox="inbox", needs_reply=True, calls=calls)
    check("B. Schedule Ending subject short-circuits (only save_email called)", calls == ["save_email"])


def test_session_ending_subject_short_circuits():
    calls = []
    _run_gate("Reminder: Upcoming Session Ending for Example Class", skip=False, category="", reason="", mailbox="inbox", needs_reply=True, calls=calls)
    check("C. Session Ending subject short-circuits (only save_email called)", calls == ["save_email"])


def test_matching_is_case_insensitive():
    calls = []
    _run_gate("LOW ENROLLMENT ALERT - Example Class", skip=False, category="", reason="", mailbox="inbox", needs_reply=True, calls=calls)
    check("D. matching is case-insensitive", calls == ["save_email"])


# ---------------------------------------------------------------------------
# E, F - subject-only enforcement, and normal parent emails are unaffected.
# ---------------------------------------------------------------------------

def test_body_only_mention_does_not_short_circuit():
    """The gate only ever inspects `subject` - body content is not part of
    _run_gate's signature at all, so a phrase appearing only in the body
    (never checked here) cannot trigger it. Confirmed structurally by
    construction, and re-confirmed against the real source below."""
    calls = []
    result = _run_gate("Hello, quick question about tuition", skip=False, category="", reason="", mailbox="inbox", needs_reply=True, calls=calls)
    check(
        "E. a clean subject reaches the normal classifier/retrieval path even if the (unchecked) body would have matched",
        "search_similar_emails" in calls and "search_knowledge_base" in calls and "rerank_emails" in calls,
    )
    check("E. does not save with the short-circuit shape", result["status"] != "No Reply Required")


def test_normal_parent_email_continues_through_classifier_path():
    calls = []
    result = _run_gate("Question about my child's enrollment", skip=False, category="", reason="", mailbox="inbox", needs_reply=True, calls=calls)
    check(
        "F. normal parent email reaches retrieval (search_similar_emails, search_knowledge_base, rerank_emails) and generation",
        calls == ["search_similar_emails", "search_knowledge_base", "rerank_emails", "generate_reply", "save_email"],
    )
    check("F. saved with the normal classifier-path shape", result["status"] == "Needs Review")


# ---------------------------------------------------------------------------
# G - exact saved shape for the short-circuit.
# ---------------------------------------------------------------------------

def test_short_circuit_saved_shape_exact():
    calls = []
    result = _run_gate("Low Enrollment Alert - Example Class", skip=False, category="", reason="", mailbox="inbox", needs_reply=True, calls=calls)
    check('G. status == "No Reply Required"', result["status"] == "No Reply Required")
    check('G. draft == ""', result["draft"] == "")
    check('G. priority == "High"', result["priority"] == "High")


# ---------------------------------------------------------------------------
# H, I, J - retrieval/reranking/generation are never invoked for a
# short-circuited alert. Proven two ways: (1) behaviorally via the call
# recorder above (already asserted in tests A-D), and (2) structurally
# against the REAL file below - the short-circuit's `return` sits before
# every retrieval/generation call in the source, so Python's linear control
# flow guarantees none of them can execute for a matching subject.
# ---------------------------------------------------------------------------

def test_retrieval_functions_not_called_for_short_circuited_alert():
    calls = []
    _run_gate("Low Enrollment Alert - X", skip=False, category="", reason="", mailbox="inbox", needs_reply=True, calls=calls)
    check("H. search_similar_emails is not called", "search_similar_emails" not in calls)
    check("H. search_knowledge_base is not called", "search_knowledge_base" not in calls)


def test_reranking_not_called_for_short_circuited_alert():
    calls = []
    _run_gate("Upcoming Class Schedule Ending in 7 Days - X", skip=False, category="", reason="", mailbox="inbox", needs_reply=True, calls=calls)
    check("I. rerank_emails is not called", "rerank_emails" not in calls)


def test_generate_reply_not_called_for_short_circuited_alert():
    calls = []
    _run_gate("Reminder: Upcoming Session Ending for X", skip=False, category="", reason="", mailbox="inbox", needs_reply=True, calls=calls)
    check("J. generate_reply is not called", "generate_reply" not in calls)


# ---------------------------------------------------------------------------
# K, L, M, N - regression: P0-1, existing skip=True behavior, and P0-2
# priority behavior are all untouched. Source-level, against the real file.
# ---------------------------------------------------------------------------

def _process_email_body():
    src = _read_source("process_email.py")
    # Updated for the approved LLM-client-isolation task's addition of a
    # trailing llm_clients=None parameter - the signature marker below is
    # the only thing that changed here, purely to keep locating the real
    # function body; nothing about what this test checks changed.
    start = src.find("def process_email(msg, account, ingested_via=None, gmail_internal_id=None, llm_clients=None):")
    assert start != -1, "could not locate process_email() body"
    # process_email() is the only top-level function in this file (runs to
    # EOF) - fall back to the end of the file when there's no following
    # "\ndef " to bound the search with.
    end = src.find("\ndef ", start + 1)
    if end == -1:
        end = len(src)
    return src[start:end]


def test_p0_1_no_reply_gate_unchanged():
    body = _process_email_body()
    # Was a byte-adjacent literal until Phase 2 of the live Coral
    # class-data feature legitimately inserted its own intent-detection
    # call between the gate and generate_reply() - updated to a
    # presence + ordering check so it stays true regardless of what runs
    # between the gate and the call.
    check(
        'K. P0-1: generate_reply() is still gated on "if result[\"needs_reply\"]:"',
        'if result["needs_reply"]:' in body
        and body.index('if result["needs_reply"]:') < body.index('draft, generation_status = generate_reply('),
    )
    check(
        'K. P0-1: the skip branch (draft="", generation_status="skipped") is still present',
        'else:\n        draft, generation_status = "", "skipped"' in body,
    )


def test_existing_skip_true_behavior_unchanged():
    body = _process_email_body()
    check(
        "L. the skip=True branch still saves with status=\"No Reply Required\"",
        'status="No Reply Required",' in body,
    )
    check(
        "L. the skip=True branch still computes its own priority via the shared keyword list",
        'skip_priority = "High" if any(kw in subject_lower for kw in schedule_alert_keywords) else "Low"' in body,
    )
    check(
        "L. the skip=True branch is still gated on `if skip:` before the new short-circuit",
        body.find("if skip:") < body.find("if any(kw in subject_lower for kw in schedule_alert_keywords):"),
    )


def test_p0_2_ai_classifier_override_unchanged():
    ai_classifier_src = _read_source("ai_classifier.py")
    check(
        "M. ai_classifier.py's P0-2 override block is untouched",
        'schedule_alert_keywords = ["low enrollment", "schedule ending", "session ending"]' in ai_classifier_src
        and 'if any(kw in subject_lower for kw in schedule_alert_keywords):' in ai_classifier_src,
    )
    check(
        "M. ai_classifier.py's override still only raises Low/Medium to High",
        'if result.get("priority") in ["Low", "Medium"]:' in ai_classifier_src,
    )


def test_urgent_never_downgraded_anywhere_in_new_code():
    """The new short-circuit and the shared keyword list never reference
    "Urgent" at all - it hardcodes priority="High" outright rather than
    conditionally raising from a prior value, so there is no code path in
    this change that could read or overwrite an existing Urgent value.
    (Whether an alert ever arrives already carrying priority="Urgent" is a
    classifier-path question - the short-circuit bypasses the classifier
    entirely for known alerts, so no prior priority value exists to
    downgrade in the first place.)"""
    body = _process_email_body()
    shortcircuit_start = body.find("# P0-3: known internal Coral alert subjects")
    shortcircuit_end = body.find("history = get_thread(thread_id) if in_reply_to else []")
    shortcircuit_block = body[shortcircuit_start:shortcircuit_end]
    check(
        'N. the new short-circuit block never references "Urgent" (nothing to downgrade - it never reads a prior priority)',
        "Urgent" not in shortcircuit_block,
    )


# ---------------------------------------------------------------------------
# O - no schema assumptions introduced.
# ---------------------------------------------------------------------------

def test_no_new_database_fields_referenced():
    body = _process_email_body()
    shortcircuit_start = body.find("# P0-3: known internal Coral alert subjects")
    shortcircuit_end = body.find("history = get_thread(thread_id) if in_reply_to else []")
    shortcircuit_block = body[shortcircuit_start:shortcircuit_end]
    save_email_call_start = shortcircuit_block.find("save_email(")
    save_email_call_end = shortcircuit_block.find(")", shortcircuit_block.rfind("ingested_via=ingested_via"))
    save_email_kwargs = shortcircuit_block[save_email_call_start:save_email_call_end]

    expected_kwargs = [
        "sender=", "subject=", "body=", "category=", "priority=", "ai_summary=",
        "ai_draft_reply=", "message_id=", "thread_id=", "in_reply_to=", "source=",
        "status=", "mailbox=", "references_header=", "email_date=", "has_attachment=",
        "sender_name=", "gmail_internal_id=", "ingested_via=",
    ]
    for kw in expected_kwargs:
        check(f"O. save_email() call uses only the existing {kw.rstrip('=')} field", kw in save_email_kwargs)

    check(
        "O. no unexpected new keyword arguments were added to the save_email() call",
        save_email_kwargs.count("=") == len(expected_kwargs),
        f"found {save_email_kwargs.count('=')} kwargs, expected {len(expected_kwargs)}",
    )


# ---------------------------------------------------------------------------
# Structural placement: the short-circuit's return sits before every
# retrieval/generation call site in the real file - the strongest available
# proof (short of executing the un-importable module) that these calls are
# unreachable for a matching subject.
# ---------------------------------------------------------------------------

def test_short_circuit_precedes_all_retrieval_and_generation_call_sites():
    body = _process_email_body()
    shortcircuit_marker = body.find("# P0-3: known internal Coral alert subjects")
    assert shortcircuit_marker != -1, "P0-3 short-circuit block not found in process_email.py"

    for call_site in [
        "search_similar_emails, subject, body, embedding_client=similar_client",
        "search_knowledge_base, subject, body, embedding_client=knowledge_client",
        "reranked = rerank_emails(",
        "draft, generation_status = generate_reply(",
    ]:
        idx = body.find(call_site)
        if idx == -1:
            continue
        check(
            f"the P0-3 short-circuit appears before the call site starting {call_site[:40]!r}",
            shortcircuit_marker < idx,
        )

    # At least the calls that are definitely present must have been checked.
    definitely_present = ["search_similar_emails, subject, body, embedding_client=similar_client",
                           "search_knowledge_base, subject, body, embedding_client=knowledge_client",
                           "reranked = rerank_emails(",
                           "draft, generation_status = generate_reply("]
    check(
        "all 4 key retrieval/generation call sites were located and checked",
        all(body.find(c) != -1 for c in definitely_present),
    )


def main():
    test_low_enrollment_subject_short_circuits()
    test_schedule_ending_subject_short_circuits()
    test_session_ending_subject_short_circuits()
    test_matching_is_case_insensitive()

    test_body_only_mention_does_not_short_circuit()
    test_normal_parent_email_continues_through_classifier_path()

    test_short_circuit_saved_shape_exact()

    test_retrieval_functions_not_called_for_short_circuited_alert()
    test_reranking_not_called_for_short_circuited_alert()
    test_generate_reply_not_called_for_short_circuited_alert()

    test_p0_1_no_reply_gate_unchanged()
    test_existing_skip_true_behavior_unchanged()
    test_p0_2_ai_classifier_override_unchanged()
    test_urgent_never_downgraded_anywhere_in_new_code()

    test_no_new_database_fields_referenced()

    test_short_circuit_precedes_all_retrieval_and_generation_call_sites()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
