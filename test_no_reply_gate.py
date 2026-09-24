"""Focused tests for P0-1: gating generate_reply() on the classifier's
needs_reply signal in process_email.py, so internal Coral alerts (e.g. Low
Enrollment / Schedule Ending, which the classifier already correctly marks
needs_reply=false) no longer get a misleading customer-style AI draft
generated and shown on the dashboard.

Matches this repo's existing test_*.py convention (see test_accuracy_fixes.py,
test_review_reasons.py): a plain script using only assert statements, no
pytest. process_email.py cannot be imported in this environment - it needs
bs4, slack_notifications, trial_followup, and subscription_cancel, none
installed here (same limitation already documented in
test_review_reasons.py's module docstring) - so the new conditional is
verified as a byte-for-byte mirror of the real code, kept in sync by
inspection, PLUS source-level checks against the real file confirming the
mirror matches exactly what's actually in process_email.py.

Run with: python3 test_no_reply_gate.py
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
# Mirror of the new generation-gating logic added to process_email.py -
# byte-for-byte equivalent to:
#
#     if result["needs_reply"]:
#         draft, generation_status = generate_reply(...)
#     else:
#         draft, generation_status = "", "skipped"
#
# generate_reply_fn is injected here (instead of importing the real
# reply_generator.generate_reply) purely so call-count/call-arguments can be
# observed - the branching logic itself is what's under test, not
# generate_reply()'s own internals (already covered by test_accuracy_fixes.py
# and test_p0_fixes.py).
# ---------------------------------------------------------------------------

def _run_generation_gate(needs_reply, generate_reply_fn, *args, **kwargs):
    if needs_reply:
        draft, generation_status = generate_reply_fn(*args, **kwargs)
    else:
        draft, generation_status = "", "skipped"
    return draft, generation_status


# Mirror of the review_reasons combination immediately downstream, unchanged
# by this fix - same mirror technique already established in
# test_review_reasons.py's _compute_review_reasons, reproduced here so the
# interaction with the new "skipped" status can be verified directly.
def _compute_review_reasons(classifier_requires_review, retrieval_error, generation_status):
    review_reasons = []
    if classifier_requires_review:
        review_reasons.append("classifier")
    if retrieval_error:
        review_reasons.append("retrieval_error")
    if generation_status == "blocked_safety_net":
        review_reasons.append("safety_block")
    if generation_status == "error":
        review_reasons.append("generation_error")
    return review_reasons


class _CallRecorder:
    """Stands in for generate_reply(): records every call and returns a
    fixed (draft, status) tuple, so tests can assert exactly how many times
    it was invoked and with what arguments."""

    def __init__(self, return_value=("a real draft", "ok")):
        self.calls = []
        self._return_value = return_value

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._return_value


# ---------------------------------------------------------------------------
# 1. needs_reply=True - existing behavior must be exactly unchanged.
# ---------------------------------------------------------------------------

def test_needs_reply_true_calls_generate_reply_once_with_same_arguments():
    recorder = _CallRecorder(return_value=("Hi there, ...", "ok"))

    draft, generation_status = _run_generation_gate(
        True, recorder,
        "msg-1", "Subject", "Body", "General", "Medium", "history text",
        ["hist1"], ["kb1"],
        source="support@coralacademy.com",
        customer_name="Alex",
        email_date="2026-09-24",
    )

    check("generate_reply() is called exactly once when needs_reply=True", len(recorder.calls) == 1)
    check(
        "the call's positional arguments are preserved unchanged",
        recorder.calls[0][0] == ("msg-1", "Subject", "Body", "General", "Medium", "history text", ["hist1"], ["kb1"]),
    )
    check(
        "the call's keyword arguments are preserved unchanged",
        recorder.calls[0][1] == {
            "source": "support@coralacademy.com",
            "customer_name": "Alex",
            "email_date": "2026-09-24",
        },
    )
    check("the returned draft is used unchanged", draft == "Hi there, ...")
    check("the returned generation_status is used unchanged", generation_status == "ok")


# ---------------------------------------------------------------------------
# 2. needs_reply=False - generate_reply() must not be called at all.
# ---------------------------------------------------------------------------

def test_needs_reply_false_skips_generate_reply():
    recorder = _CallRecorder(return_value=("this should never be returned", "ok"))

    draft, generation_status = _run_generation_gate(
        False, recorder,
        "msg-2", "Low Enrollment Alert", "body", "General", "Medium", "",
        [], [],
        source="support@coralacademy.com",
        customer_name=None,
        email_date=None,
    )

    check("generate_reply() is NOT called when needs_reply=False", len(recorder.calls) == 0)
    check('draft == "" when needs_reply=False', draft == "")
    check('generation_status == "skipped" when needs_reply=False', generation_status == "skipped")


# ---------------------------------------------------------------------------
# 3. Review behavior: "skipped" must not create safety_block or
#    generation_error, and must not independently force requires_review.
#    result["requires_review"] and retrieval_error remain authoritative.
# ---------------------------------------------------------------------------

def test_skipped_status_does_not_create_safety_block():
    reasons = _compute_review_reasons(False, False, "skipped")
    check('"skipped" does not add "safety_block" to review_reasons', "safety_block" not in reasons)


def test_skipped_status_does_not_create_generation_error():
    reasons = _compute_review_reasons(False, False, "skipped")
    check('"skipped" does not add "generation_error" to review_reasons', "generation_error" not in reasons)


def test_skipped_status_alone_does_not_force_review():
    reasons = _compute_review_reasons(False, False, "skipped")
    check(
        "a clean email (classifier False, no retrieval error) with generation skipped -> requires_review stays False",
        bool(reasons) is False,
    )


def test_classifier_requires_review_still_authoritative_when_skipped():
    reasons = _compute_review_reasons(True, False, "skipped")
    check(
        "result[\"requires_review\"]=True still forces review even when generation was skipped",
        reasons == ["classifier"],
    )


def test_retrieval_error_still_authoritative_when_skipped():
    reasons = _compute_review_reasons(False, True, "skipped")
    check(
        "a retrieval_error still forces review even when generation was skipped",
        reasons == ["retrieval_error"],
    )


# ---------------------------------------------------------------------------
# 4. Regression: needs_reply=True path, and the pre-existing no_reply/
#    blocked_safety_net/error statuses, must remain exactly as they were.
# ---------------------------------------------------------------------------

def test_existing_no_reply_status_behavior_unchanged():
    """generate_reply() itself can still return ("", "no_reply") on its own
    (the model's own considered "not enough info" outcome, when
    needs_reply=True but the model still can't answer) - deliberately
    distinct from the new needs_reply=False "skipped" path, and its
    behavior (does not force review) must be unaffected by this change."""
    reasons = _compute_review_reasons(False, False, "no_reply")
    check('pre-existing "no_reply" status still does not force review (unaffected by this fix)', bool(reasons) is False)


def test_existing_blocked_safety_net_behavior_unchanged():
    reasons = _compute_review_reasons(False, False, "blocked_safety_net")
    check('pre-existing "blocked_safety_net" status still forces review via "safety_block" (unaffected)', reasons == ["safety_block"])


def test_existing_error_status_behavior_unchanged():
    reasons = _compute_review_reasons(False, False, "error")
    check('pre-existing "error" status still forces review via "generation_error" (unaffected)', reasons == ["generation_error"])


def test_existing_ok_status_behavior_unchanged():
    reasons = _compute_review_reasons(False, False, "ok")
    check('pre-existing "ok" status still does not force review on its own (unaffected)', bool(reasons) is False)


# ---------------------------------------------------------------------------
# Source-level checks against the REAL process_email.py, confirming the
# mirror above matches what's actually in the file (see module docstring for
# why process_email.py can't be imported directly here).
# ---------------------------------------------------------------------------

def test_process_email_py_gates_generate_reply_on_needs_reply():
    src = _read_source("process_email.py")
    check(
        'process_email.py wraps the generate_reply() call in "if result[\"needs_reply\"]:"',
        'if result["needs_reply"]:\n        draft, generation_status = generate_reply(' in src,
    )
    check(
        'process_email.py sets draft="" and generation_status="skipped" in the else branch',
        'else:\n        draft, generation_status = "", "skipped"' in src,
    )


def test_process_email_py_preserves_generate_reply_call_arguments():
    """Byte-for-byte pin on the P0-1 call block, updated once (and only
    once) for the teacher-leak-fix task's approved addition of an explicit
    trailing audience="parent" kwarg - every other argument, and their
    order, is unchanged from the original P0-1 fix."""
    src = _read_source("process_email.py")
    call_block = (
        'draft, generation_status = generate_reply(\n'
        '            message_id,\n'
        '            subject,\n'
        '            body,\n'
        '            result["category"],\n'
        '            result["priority"],\n'
        '            history_text,\n'
        '            #similar,\n'
        '            #reranked,\n'
        '            historical_emails,\n'
        '            knowledge,\n'
        '            source=account["source"],\n'
        '            customer_name=find_recipient_name(sender_email),\n'
        '            email_date=email_date,\n'
        '            audience="parent",\n'
        '        )'
    )
    check(
        "the generate_reply() call arguments are unchanged from P0-1 except for the approved trailing audience=\"parent\"",
        call_block in src,
    )


def test_process_email_py_downstream_review_logic_unchanged():
    src = _read_source("process_email.py")
    for expected in [
        'if generation_status == "blocked_safety_net":\n        review_reasons.append("safety_block")',
        'if generation_status == "error":\n        review_reasons.append("generation_error")',
        'requires_review = bool(review_reasons)',
        'review_reason = ",".join(review_reasons) if review_reasons else None',
    ]:
        check(f"downstream review_reasons logic unchanged: {expected.splitlines()[0]}...", expected in src)


def test_process_email_py_save_email_call_unchanged():
    src = _read_source("process_email.py")
    check(
        "save_email() is still called with the same requires_review/review_reason/reply_type wiring",
        "requires_review=requires_review,\n        review_reason=review_reason," in src
        and 'reply_type=result["reply_type"],' in src,
    )


# ---------------------------------------------------------------------------
# 5. Scope confirmation.
#
# These two checks used to inspect the LIVE `git status --short` output and
# assert the working tree contained only P0-1's own files. That's a
# moment-in-time snapshot, not a fact about P0-1 itself - it necessarily
# breaks the instant any later, unrelated task (e.g. P0-2) makes its own
# legitimate changes on top, with no bearing on whether P0-1 is still
# intact. Replaced with two content/history-based checks that stay true
# regardless of what any future task touches: (a) the P0-1 gate is still
# actually present in process_email.py, both in the commit that introduced
# it and in the current working-tree file, and (b) commit 4ad2c186 itself -
# a fixed, permanent historical fact - only ever touched its approved
# files. Neither assumes anything about which other files a later task may
# legitimately modify.
# ---------------------------------------------------------------------------

_P0_1_COMMIT = "4ad2c1860ef82d9689de2ecee902b35592258b74"
_P0_1_GATE_PATTERN = 'if result["needs_reply"]:\n        draft, generation_status = generate_reply('
_P0_1_SKIP_PATTERN = 'else:\n        draft, generation_status = "", "skipped"'


def test_p0_1_gate_present_at_commit_and_in_working_tree():
    """Confirms the P0-1 needs_reply gate has not been accidentally removed
    or reverted - checked both against the commit that actually introduced
    it (the fixed, permanent historical baseline) and against whatever is
    currently on disk (which may carry later, unrelated changes on top,
    e.g. P0-2's priority edit further down the same file)."""
    import subprocess

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    committed_content = subprocess.run(
        ["git", "show", f"{_P0_1_COMMIT}:process_email.py"],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    ).stdout

    check(
        f"the P0-1 gate is present in process_email.py as committed at {_P0_1_COMMIT[:10]}",
        _P0_1_GATE_PATTERN in committed_content and _P0_1_SKIP_PATTERN in committed_content,
    )

    working_tree_content = _read_source("process_email.py")
    check(
        "the P0-1 gate is still present in the current working-tree process_email.py",
        _P0_1_GATE_PATTERN in working_tree_content and _P0_1_SKIP_PATTERN in working_tree_content,
    )


def test_p0_1_commit_only_touched_its_approved_files():
    """What commit 4ad2c186 (the P0-1 commit) actually changed is a fixed,
    permanent historical fact - unlike the live working tree, it can never
    be altered by a later task, so asserting against it stays meaningful
    forever instead of breaking on the next unrelated change. Also confirms
    this test file's own P0-1 behavioral tests are still defined and still
    invoked from main() - i.e. not silently gutted or excluded."""
    import subprocess

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        ["git", "show", "--name-only", "--format=", _P0_1_COMMIT],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    )
    files_in_commit = {line.strip() for line in result.stdout.splitlines() if line.strip()}

    check(
        f"commit {_P0_1_COMMIT[:10]} (P0-1) touched exactly its approved files",
        files_in_commit == {"process_email.py", "test_no_reply_gate.py"},
        f"found: {sorted(files_in_commit)}",
    )

    own_source = _read_source("test_no_reply_gate.py")
    core_p0_1_tests = [
        "test_needs_reply_true_calls_generate_reply_once_with_same_arguments",
        "test_needs_reply_false_skips_generate_reply",
    ]
    for test_name in core_p0_1_tests:
        check(
            f"{test_name} is still defined in this file",
            f"def {test_name}(" in own_source,
        )
        check(
            f"{test_name} is still invoked from main()",
            f"    {test_name}()" in own_source,
        )


def main():
    test_needs_reply_true_calls_generate_reply_once_with_same_arguments()
    test_needs_reply_false_skips_generate_reply()

    test_skipped_status_does_not_create_safety_block()
    test_skipped_status_does_not_create_generation_error()
    test_skipped_status_alone_does_not_force_review()
    test_classifier_requires_review_still_authoritative_when_skipped()
    test_retrieval_error_still_authoritative_when_skipped()

    test_existing_no_reply_status_behavior_unchanged()
    test_existing_blocked_safety_net_behavior_unchanged()
    test_existing_error_status_behavior_unchanged()
    test_existing_ok_status_behavior_unchanged()

    test_process_email_py_gates_generate_reply_on_needs_reply()
    test_process_email_py_preserves_generate_reply_call_arguments()
    test_process_email_py_downstream_review_logic_unchanged()
    test_process_email_py_save_email_call_unchanged()

    test_p0_1_gate_present_at_commit_and_in_working_tree()
    test_p0_1_commit_only_touched_its_approved_files()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
