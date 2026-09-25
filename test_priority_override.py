"""Focused tests for P0-2: Low Enrollment / Schedule Ending alerts must
receive HIGH priority, whether they reach ai_classifier.py's normal
classification path or process_email.py's skip=True automated-email path.

Matches this repo's existing test_*.py convention (see test_accuracy_fixes.py):
a plain script using only assert statements, no pytest.

TWO KINDS OF CHECK, SAME SPLIT AS test_no_reply_gate.py:

1. ai_classifier.py IS imported for real (same fake openai/dotenv/psycopg2
   infrastructure test_accuracy_fixes.py already establishes) - the actual
   ai_triage() function runs against a controlled fake LLM response, so the
   new override, the existing Teacher Portal override, and the existing
   human_keywords override are all exercised behaviorally, not mirrored.

2. process_email.py cannot be imported (needs bs4, slack_notifications,
   trial_followup, subscription_cancel - same documented limitation as
   test_no_reply_gate.py and test_review_reasons.py), so its skip=True
   priority logic is verified as a byte-for-byte mirror, kept in sync by
   inspection, PLUS source-level checks against the real file confirming
   the mirror matches exactly what's in process_email.py - and that this
   commit's P0-1 no-reply gate is untouched by this change.

Run with: python3 test_priority_override.py
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
# Fake infrastructure - identical technique to test_accuracy_fixes.py, so
# ai_classifier.py can be imported and run for real without openai/psycopg2
# actually installed.
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
        self.embeddings = types.SimpleNamespace(create=lambda **kw: types.SimpleNamespace(
            data=[types.SimpleNamespace(embedding=[0.1] * 8)]
        ))


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
import ai_classifier  # noqa: E402


def _fake_chat_response(content_dict):
    import json as _json
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=_json.dumps(content_dict)))],
        usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=10, total_tokens=20),
    )


def _classify(subject, body="Some internal system content.", llm_result=None):
    """Runs the REAL ai_classifier.ai_triage() against a controlled fake LLM
    response representing what the model itself decided, before any
    business-rule override runs."""
    base = {
        "category": "General",
        "priority": "Medium",
        "summary": "s",
        "requires_review": False,
        "confidence": 90,
        "needs_reply": True,
        "reply_type": "automatic",
    }
    if llm_result:
        base.update(llm_result)
    ai_classifier.client.chat.completions.set_next(_fake_chat_response(base))
    return ai_classifier.ai_triage(subject, body)


# ---------------------------------------------------------------------------
# 1. ai_classifier.py - the new override, exercised for real.
# ---------------------------------------------------------------------------

def test_low_enrollment_subject_raises_to_high():
    result = _classify("Low Enrollment Alert - Example Class", llm_result={"priority": "Medium"})
    check('"Low Enrollment Alert - Example Class" -> priority High', result["priority"] == "High")


def test_schedule_ending_subject_raises_to_high():
    result = _classify("Upcoming Class Schedule Ending in 2 Days - Example Class", llm_result={"priority": "Low"})
    check('"Upcoming Class Schedule Ending in 2 Days - Example Class" -> priority High', result["priority"] == "High")


def test_session_ending_subject_raises_to_high():
    result = _classify("Reminder: Upcoming Session Ending for Example Class", llm_result={"priority": "Medium"})
    check('"Reminder: Upcoming Session Ending for Example Class" -> priority High', result["priority"] == "High")


def test_matching_is_case_insensitive():
    result = _classify("LOW ENROLLMENT ALERT - Example Class", llm_result={"priority": "Low"})
    check("matching is case-insensitive (uppercase subject still raises to High)", result["priority"] == "High")


def test_urgent_priority_is_never_downgraded():
    result = _classify("Low Enrollment Alert - Example Class", llm_result={"priority": "Urgent"})
    check("an existing Urgent priority is never downgraded by this override", result["priority"] == "Urgent")


def test_medium_priority_raised_to_high():
    result = _classify("Reminder: Upcoming Session Ending for Example Class", llm_result={"priority": "Medium"})
    check("Medium is raised to High", result["priority"] == "High")


def test_low_priority_raised_to_high():
    result = _classify("Upcoming Class Schedule Ending in 7 Days - Example Class", llm_result={"priority": "Low"})
    check("Low is raised to High", result["priority"] == "High")


def test_override_only_changes_priority():
    result = _classify(
        "Low Enrollment Alert - Example Class",
        llm_result={
            "priority": "Medium", "category": "General", "confidence": 77,
            "needs_reply": False, "requires_review": False, "reply_type": "none",
        },
    )
    check("category is unchanged by the priority override", result["category"] == "General")
    check("confidence is unchanged by the priority override", result["confidence"] == 77)
    check("needs_reply is unchanged by the priority override", result["needs_reply"] is False)
    check("requires_review is unchanged by the priority override", result["requires_review"] is False)
    check("reply_type is unchanged by the priority override", result["reply_type"] == "none")


def test_body_only_match_does_not_raise_priority():
    """The three approved phrases must only be checked in the subject -
    never the body."""
    result = _classify(
        "Hello there",
        body="This message mentions low enrollment, schedule ending, and session ending in passing.",
        llm_result={"priority": "Medium"},
    )
    check(
        "a clean subject with the phrases only in the body does NOT raise priority",
        result["priority"] == "Medium",
    )


# ---------------------------------------------------------------------------
# 2. Existing overrides remain exactly as before.
# ---------------------------------------------------------------------------

def test_teacher_portal_override_unaffected():
    result = _classify("New message from Amber - Coral Academy", llm_result={"priority": "Low", "category": "General"})
    check("Teacher Portal override still sets category=Teacher", result["category"] == "Teacher")
    check("Teacher Portal override still sets priority=Medium (unaffected by the new rule)", result["priority"] == "Medium")
    check("Teacher Portal override still sets needs_reply=True", result["needs_reply"] is True)


def test_human_keywords_override_unaffected():
    result = _classify(
        "Question about my child's class",
        body="I would like to request a refund for last month.",
        llm_result={"priority": "Low", "requires_review": False, "needs_reply": True, "reply_type": "automatic"},
    )
    check("human_keywords override still forces requires_review=True", result["requires_review"] is True)
    check("human_keywords override still forces reply_type=human", result["reply_type"] == "human")
    check("human_keywords override still raises priority to High", result["priority"] == "High")


def test_new_rule_does_not_interfere_with_human_keywords():
    """A contrived case where both the new subject rule and human_keywords
    would independently push toward High/review - confirms no conflict or
    exception when both apply at once."""
    result = _classify(
        "Low Enrollment Alert - Example Class",
        body="Please note this also mentions a refund situation.",
        llm_result={"priority": "Low"},
    )
    check("both overrides applying together still results in priority High", result["priority"] == "High")
    check("human_keywords' own effect (requires_review) still applies alongside the new rule", result["requires_review"] is True)


# ---------------------------------------------------------------------------
# 3 & 4. process_email.py's skip=True path - mirror + source-presence
# checks (process_email.py itself can't be imported here - see module
# docstring).
# ---------------------------------------------------------------------------

_SCHEDULE_ALERT_KEYWORDS = ["low enrollment", "schedule ending", "session ending"]


def _compute_skip_priority(subject):
    subject_lower = subject.lower()
    return "High" if any(kw in subject_lower for kw in _SCHEDULE_ALERT_KEYWORDS) else "Low"


def test_skip_true_low_enrollment_subject_is_high():
    check('skip=True, "Low Enrollment Alert - X" -> High', _compute_skip_priority("Low Enrollment Alert - X") == "High")


def test_skip_true_schedule_ending_subject_is_high():
    check(
        'skip=True, "Upcoming Class Schedule Ending in 10 Days - X" -> High',
        _compute_skip_priority("Upcoming Class Schedule Ending in 10 Days - X") == "High",
    )


def test_skip_true_session_ending_subject_is_high():
    check(
        'skip=True, "Reminder: Upcoming Session Ending for X" -> High',
        _compute_skip_priority("Reminder: Upcoming Session Ending for X") == "High",
    )


def test_skip_true_matching_is_case_insensitive():
    check(
        'skip=True matching is case-insensitive ("SESSION ENDING")',
        _compute_skip_priority("SESSION ENDING reminder for X") == "High",
    )


def test_skip_true_unrelated_automated_email_stays_low():
    check(
        'skip=True, unrelated automated email ("Your OTP code is 123456") stays Low',
        _compute_skip_priority("Your OTP code is 123456") == "Low",
    )


def test_skip_true_password_reset_stays_low():
    check(
        'skip=True, password-reset notification stays Low',
        _compute_skip_priority("Password Reset Requested") == "Low",
    )


def test_skip_true_github_notification_stays_low():
    check(
        'skip=True, GitHub-style automated notification stays Low',
        _compute_skip_priority("[GitHub] New activity on your repository") == "Low",
    )


def test_process_email_py_skip_branch_uses_the_keyword_check():
    src = _read_source("process_email.py")
    check(
        "process_email.py's skip=True branch computes skip_priority via the keyword check",
        'skip_priority = "High" if any(kw in subject_lower for kw in schedule_alert_keywords) else "Low"' in src,
    )
    check(
        "save_email() in the skip=True branch is passed priority=skip_priority, not a literal",
        "priority=skip_priority," in src,
    )
    check(
        'the old unconditional priority="Low" literal is gone from the skip branch',
        'priority="Low",\n            ai_summary=reason,' not in src,
    )


def test_process_email_py_skip_branch_keyword_list_matches_approved_phrases():
    src = _read_source("process_email.py")
    check(
        "process_email.py's skip=True branch uses exactly the 3 approved phrases",
        'schedule_alert_keywords = ["low enrollment", "schedule ending", "session ending"]' in src,
    )


def test_process_email_py_skip_branch_other_fields_unchanged():
    src = _read_source("process_email.py")
    for expected in [
        "category=category,", "ai_summary=reason,", "mailbox=mailbox,",
        'status="No Reply Required",', "sender=sender_email,",
    ]:
        check(f"skip=True save_email() still passes {expected} unchanged", expected in src)


def test_ai_classifier_py_uses_subject_lower_not_text_content():
    src = _read_source("ai_classifier.py")
    override_start = src.find("# Low Enrollment / Schedule Ending override")
    override_end = src.find("print(json.dumps(result, indent=2))")
    override_body = src[override_start:override_end]
    check(
        "ai_classifier.py's new override checks subject_lower (not text_content/body)",
        "subject_lower" in override_body and "text_content" not in override_body,
    )
    check(
        "ai_classifier.py's new override uses exactly the 3 approved phrases",
        'schedule_alert_keywords = ["low enrollment", "schedule ending", "session ending"]' in override_body,
    )
    check(
        "ai_classifier.py's new override only raises Low/Medium to High (same guard as human_keywords)",
        'if result.get("priority") in ["Low", "Medium"]:' in override_body,
    )


def test_ai_classifier_py_existing_overrides_untouched():
    src = _read_source("ai_classifier.py")
    for expected in [
        'if (\n            "new message from" in subject_lower\n            and "coral academy" in subject_lower\n        ):',
        'result["category"] = "Teacher"',
        'result["priority"] = "Medium"',
        'if any(word in text_content for word in human_keywords):',
        'result["reply_type"] = "human"',
    ]:
        check(f"existing override logic unchanged: {expected.splitlines()[0][:50]}...", expected in src)


# ---------------------------------------------------------------------------
# 5. P0-1 regression: the no-reply gate from the previous commit must be
# completely untouched by this change.
# ---------------------------------------------------------------------------

def test_p0_1_no_reply_gate_still_present_unchanged():
    src = _read_source("process_email.py")
    # Was a byte-adjacent literal until Phase 2 of the live Coral
    # class-data feature legitimately inserted its own intent-detection
    # call between the gate and generate_reply() - updated to a
    # presence + ordering check so it stays true regardless of what runs
    # between the gate and the call.
    check(
        'P0-1: generate_reply() is still gated on "if result[\"needs_reply\"]:"',
        'if result["needs_reply"]:' in src
        and src.index('if result["needs_reply"]:') < src.index('draft, generation_status = generate_reply('),
    )
    check(
        'P0-1: the skip branch (draft="", generation_status="skipped") is still present',
        'else:\n        draft, generation_status = "", "skipped"' in src,
    )


def test_needs_reply_true_still_calls_generate_reply_mirror():
    """Same mirror already established in test_no_reply_gate.py, re-asserted
    here as a direct regression guard specific to this P0-2 change."""
    def _gate(needs_reply, fn, *a, **kw):
        if needs_reply:
            return fn(*a, **kw)
        return "", "skipped"

    calls = []

    def _recorder(*a, **kw):
        calls.append((a, kw))
        return "a draft", "ok"

    draft, status = _gate(True, _recorder, "arg1")
    check("needs_reply=True still calls generate_reply()", len(calls) == 1)
    check("needs_reply=True still returns the real draft/status", (draft, status) == ("a draft", "ok"))


def test_needs_reply_false_still_skips_generate_reply_mirror():
    def _gate(needs_reply, fn, *a, **kw):
        if needs_reply:
            return fn(*a, **kw)
        return "", "skipped"

    calls = []

    def _recorder(*a, **kw):
        calls.append((a, kw))
        return "a draft", "ok"

    draft, status = _gate(False, _recorder, "arg1")
    check("needs_reply=False still skips generate_reply()", len(calls) == 0)
    check('needs_reply=False still returns ("", "skipped")', (draft, status) == ("", "skipped"))


# ---------------------------------------------------------------------------
# Scope confirmation.
#
# This used to inspect live `git status --short` and assert the entire
# working tree contained only P0-2's own three files - a moment-in-time
# snapshot, not a fact about P0-2 itself. It broke the instant any later,
# unrelated task (e.g. the test-hygiene fix to test_no_reply_gate.py) made
# its own legitimate change on top, with no bearing on whether P0-2's own
# code is actually present and correct. P0-2 has no commit yet (unlike
# P0-1, which could be checked against a fixed historical commit - see
# test_no_reply_gate.py's equivalent fix), so the stable replacement here
# checks the two intended files' own current content directly: a fact
# about those two files, true regardless of what else the working tree
# contains, before or after this change is eventually committed.
# ---------------------------------------------------------------------------

def test_p0_2_change_present_in_both_intended_files():
    ai_classifier_src = _read_source("ai_classifier.py")
    process_email_src = _read_source("process_email.py")

    check(
        "ai_classifier.py contains the P0-2 Low Enrollment/Schedule Ending override",
        'schedule_alert_keywords = ["low enrollment", "schedule ending", "session ending"]' in ai_classifier_src,
    )
    check(
        "process_email.py contains the P0-2 skip=True priority override",
        'skip_priority = "High" if any(kw in subject_lower for kw in schedule_alert_keywords) else "Low"' in process_email_src,
    )


def main():
    test_low_enrollment_subject_raises_to_high()
    test_schedule_ending_subject_raises_to_high()
    test_session_ending_subject_raises_to_high()
    test_matching_is_case_insensitive()
    test_urgent_priority_is_never_downgraded()
    test_medium_priority_raised_to_high()
    test_low_priority_raised_to_high()
    test_override_only_changes_priority()
    test_body_only_match_does_not_raise_priority()

    test_teacher_portal_override_unaffected()
    test_human_keywords_override_unaffected()
    test_new_rule_does_not_interfere_with_human_keywords()

    test_skip_true_low_enrollment_subject_is_high()
    test_skip_true_schedule_ending_subject_is_high()
    test_skip_true_session_ending_subject_is_high()
    test_skip_true_matching_is_case_insensitive()
    test_skip_true_unrelated_automated_email_stays_low()
    test_skip_true_password_reset_stays_low()
    test_skip_true_github_notification_stays_low()
    test_process_email_py_skip_branch_uses_the_keyword_check()
    test_process_email_py_skip_branch_keyword_list_matches_approved_phrases()
    test_process_email_py_skip_branch_other_fields_unchanged()
    test_ai_classifier_py_uses_subject_lower_not_text_content()
    test_ai_classifier_py_existing_overrides_untouched()

    test_p0_1_no_reply_gate_still_present_unchanged()
    test_needs_reply_true_still_calls_generate_reply_mirror()
    test_needs_reply_false_still_skips_generate_reply_mirror()

    test_p0_2_change_present_in_both_intended_files()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
