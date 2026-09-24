"""Focused tests for the teacher-facing content leak fix: an explicit
audience="parent"/"teacher" signal on search_knowledge_base() that keeps
category="Teaching" knowledge-base rows out of parent-facing retrieval
entirely (the primary protection), plus a strengthened
_TEACHER_FACING_LEAK_PATTERNS regex in reply_generator.py as defense in
depth against paraphrased leaks the retrieval filter doesn't apply to.

Matches this repo's existing test_*.py convention (see test_accuracy_fixes.py):
a plain script using only assert statements, no pytest. knowledge_search.py,
reply_generator.py, and teacher_reply_generator1.py ARE importable for real
here (same fake psycopg2/openai/dotenv infrastructure test_accuracy_fixes.py
already establishes), so the retrieval filter and the regex are both
exercised behaviorally, not mirrored. process_email.py cannot be imported
(needs bs4, slack_notifications, trial_followup, subscription_cancel - same
documented limitation as the other process_email.py test files), so P0-1/
P0-2/P0-3 regression checks there are source-level, consistent with how
those were already verified in test_no_reply_gate.py/test_priority_override.py/
test_internal_alert_shortcircuit.py.

Run with: python3 test_teacher_leak_fix.py
"""

import json
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
# knowledge_search.py, reply_generator.py, and teacher_reply_generator1.py
# can be imported and run for real without openai/psycopg2 actually
# installed.
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
import knowledge_search  # noqa: E402
import reply_generator   # noqa: E402

database.db_pool = FakeSimpleConnectionPool()


# Row shape: (article_title, section_title, category, content, url, source, source_id, similarity)
_TEACHING_ROW = (
    "Class Cancellation & Rescheduling", "", "Teaching",
    "Email teachers@coralacademy.com with the reason for cancellation.",
    "https://help/cancel", "help_center", "43", 0.55,
)
_PARENT_ROW = (
    "Finance 101: A Practical Playbook For Mastering Money", "Pricing", "lifeskills",
    "$25.00 per session", "https://help/finance", "help_center", "1526", 0.60,
)
_SCIENCE_ROW = (
    "Astronomy 101: Learn About Space", "Description", "science",
    "Explore the solar system with hands-on activities.",
    "https://help/astro", "help_center", "900", 0.58,
)


# ---------------------------------------------------------------------------
# A. Parent audience + Teaching KB: filtered out, cannot reach generation.
# ---------------------------------------------------------------------------

def test_A_parent_audience_filters_out_teaching_content():
    database.db_pool.next_fetchall = [_TEACHING_ROW, _PARENT_ROW]
    results = knowledge_search.search_knowledge_base("s", "b", audience="parent", rerank=False)
    titles = [r["title"] for r in results]
    check(
        "A. Teaching-category row is filtered out for audience='parent'",
        "Class Cancellation & Rescheduling" not in titles,
    )
    check(
        "A. the non-Teaching row still comes through normally",
        "Finance 101: A Practical Playbook For Mastering Money" in titles,
    )
    check(
        "A. Teaching content therefore cannot reach generate_reply() at all (never in the returned list)",
        all(r["category"] != "Teaching" for r in results),
    )


# ---------------------------------------------------------------------------
# B. Teacher audience + Teaching KB: remains available.
# ---------------------------------------------------------------------------

def test_B_teacher_audience_keeps_teaching_content():
    database.db_pool.next_fetchall = [_TEACHING_ROW, _PARENT_ROW]
    results = knowledge_search.search_knowledge_base("s", "b", audience="teacher", rerank=False)
    titles = [r["title"] for r in results]
    check(
        "B. Teaching-category row remains available for audience='teacher'",
        "Class Cancellation & Rescheduling" in titles,
    )
    check(
        "B. non-Teaching rows are still present too (unfiltered for teacher audience)",
        "Finance 101: A Practical Playbook For Mastering Money" in titles,
    )


# ---------------------------------------------------------------------------
# C. Parent audience + parent-facing KB: still works normally.
# ---------------------------------------------------------------------------

def test_C_parent_audience_parent_facing_kb_unaffected():
    database.db_pool.next_fetchall = [_PARENT_ROW, _SCIENCE_ROW]
    results = knowledge_search.search_knowledge_base("s", "b", audience="parent", rerank=False)
    titles = [r["title"] for r in results]
    check(
        "C. parent-facing (lifeskills) content still returned for audience='parent'",
        "Finance 101: A Practical Playbook For Mastering Money" in titles,
    )
    check(
        "C. parent-facing (science) content still returned for audience='parent'",
        "Astronomy 101: Learn About Space" in titles,
    )
    check("C. nothing was dropped (2 in, 2 out)", len(results) == 2)


# ---------------------------------------------------------------------------
# D. Parent audience + only Teaching results: genuine empty, not
# retrieval_error. Tested both with rerank=False and rerank=True - the
# rerank=True path must return [] (never None, which process_email.py
# treats as a retrieval error) without even calling the reranker, since
# `results` is already empty by the time that call would happen.
# ---------------------------------------------------------------------------

def test_D_parent_audience_all_teaching_is_genuine_empty_not_error():
    database.db_pool.next_fetchall = [_TEACHING_ROW]

    results_no_rerank = knowledge_search.search_knowledge_base("s", "b", audience="parent", rerank=False)
    check("D. rerank=False: filtered-to-empty returns [] (not None)", results_no_rerank == [])

    database.db_pool.next_fetchall = [_TEACHING_ROW]
    results_rerank = knowledge_search.search_knowledge_base("s", "b", audience="parent", rerank=True)
    check(
        "D. rerank=True: filtered-to-empty still returns [] (genuine empty), never None (which means retrieval_error)",
        results_rerank == [],
        f"got {results_rerank!r}",
    )


# ---------------------------------------------------------------------------
# E. Existing safety net still blocks known exact patterns.
# ---------------------------------------------------------------------------

def test_E_existing_exact_patterns_still_blocked():
    for phrase in [
        "Please email teachers@coralacademy.com with the reason.",
        "Our coordination team will follow up.",
        "We will post an announcement shortly.",
        "Rescheduling builds your credibility as an instructor.",
    ]:
        check(
            f"E. existing pattern still matches: {phrase!r}",
            reply_generator._TEACHER_FACING_LEAK_PATTERNS.search(phrase) is not None,
        )


# ---------------------------------------------------------------------------
# F. Known Anika paraphrase blocked.
# ---------------------------------------------------------------------------

def test_F_anika_paraphrase_blocked():
    text = (
        "Once we have these details, our platform team will identify a "
        "suitable Friday time and update the enrolled parents."
    )
    check(
        "F. the real Anika leak text is now caught by the strengthened regex",
        reply_generator._TEACHER_FACING_LEAK_PATTERNS.search(text) is not None,
    )
    check(
        "F. 'platform team will <verb>' catches variants beyond the old literal 'assist'",
        reply_generator._TEACHER_FACING_LEAK_PATTERNS.search("our platform team will help you") is not None,
    )


# ---------------------------------------------------------------------------
# G. "update the enrolled parents" variant blocked.
# ---------------------------------------------------------------------------

def test_G_enrolled_parents_variant_blocked():
    for phrase in [
        "We will update the enrolled parents once this is confirmed.",
        "Our team will notify enrolled parents about the change.",
        "We'll inform the enrolled families as soon as possible.",
    ]:
        check(
            f"G. enrolled-parents/families variant blocked: {phrase!r}",
            reply_generator._TEACHER_FACING_LEAK_PATTERNS.search(phrase) is not None,
        )


# ---------------------------------------------------------------------------
# H. Ordinary legitimate parent language must NOT be blocked just because
# it contains words like teacher/class/parent/enrolled/schedule/reschedule.
# ---------------------------------------------------------------------------

def test_H_ordinary_language_not_blocked():
    for phrase in [
        "Your child's teacher will be in touch soon.",
        "We can help you reschedule your class.",
        "Please let us know if you have any questions.",
        "Your learner is currently enrolled in this class.",
        "The new schedule starts next week.",
        "As a parent, you can view your child's progress anytime.",
        "This class covers economic systems and compounding.",
    ]:
        check(
            f"H. ordinary language NOT blocked: {phrase!r}",
            reply_generator._TEACHER_FACING_LEAK_PATTERNS.search(phrase) is None,
        )


# ---------------------------------------------------------------------------
# I, J, K - P0-1 / P0-2 / P0-3 regression, source-level (process_email.py /
# ai_classifier.py cannot be imported here - see module docstring).
# ---------------------------------------------------------------------------

def test_I_p0_1_no_reply_gate_intact():
    src = _read_source("process_email.py")
    check(
        'I. P0-1 gate still present: "if result["needs_reply"]:"',
        'if result["needs_reply"]:\n        draft, generation_status = generate_reply(' in src,
    )
    check(
        'I. P0-1 skip branch still present: draft="", generation_status="skipped"',
        'else:\n        draft, generation_status = "", "skipped"' in src,
    )


def test_J_p0_2_priority_logic_intact():
    ai_classifier_src = _read_source("ai_classifier.py")
    check(
        "J. ai_classifier.py's P0-2 override block is untouched",
        'schedule_alert_keywords = ["low enrollment", "schedule ending", "session ending"]' in ai_classifier_src
        and 'if any(kw in subject_lower for kw in schedule_alert_keywords):' in ai_classifier_src,
    )
    process_email_src = _read_source("process_email.py")
    check(
        "J. process_email.py's skip=True priority override is untouched",
        'skip_priority = "High" if any(kw in subject_lower for kw in schedule_alert_keywords) else "Low"' in process_email_src,
    )


def test_K_p0_3_short_circuit_still_precedes_retrieval():
    src = _read_source("process_email.py")
    shortcircuit_marker = src.find("# P0-3: known internal Coral alert subjects")
    retrieval_marker = src.find("search_knowledge_base, subject, body, embedding_client=knowledge_client")
    check(
        "K. P0-3 short-circuit block is still present",
        shortcircuit_marker != -1,
    )
    check(
        "K. P0-3 short-circuit still appears before the retrieval call site",
        -1 < shortcircuit_marker < retrieval_marker,
    )
    check(
        "K. the retrieval call site now passes the explicit parent audience",
        'search_knowledge_base, subject, body, embedding_client=knowledge_client, rerank=True, audience="parent"' in src,
    )


# ---------------------------------------------------------------------------
# L. Teacher Portal still receives Teaching-category content - behavioral
# (same mechanism as B, since teacher_reply_generator1.py's own retrieval
# call is what audience="teacher" protects) plus a source check confirming
# the wiring itself.
# ---------------------------------------------------------------------------

def test_L_teacher_portal_retrieval_wiring_passes_teacher_audience():
    src = _read_source("teacher_reply_generator1.py")
    check(
        'L. teacher_reply_generator1.py passes audience="teacher" to search_knowledge_base()',
        'audience="teacher"' in src,
    )


def test_L_teacher_portal_behaviorally_still_gets_teaching_content():
    """Same underlying mechanism Teacher Portal relies on (audience="teacher"
    passed to search_knowledge_base) - re-confirmed behaviorally here, not
    just via source text, to prove Teacher Portal's real code path is not
    accidentally degraded by the new filter's default."""
    database.db_pool.next_fetchall = [_TEACHING_ROW]
    results = knowledge_search.search_knowledge_base(
        subject="Teacher Dashboard: question", body="How do I check attendance?", audience="teacher"
    )
    check(
        "L. Teacher Portal's own audience value still returns Teaching-category content",
        any(r["category"] == "Teaching" for r in results),
    )


# ---------------------------------------------------------------------------
# generate_reply() audience-gated safety net (the fix from the final senior
# review: the leak regex must only ever apply for audience="parent" - a
# teacher-audience draft must never be blocked by it, since that same
# staff-only wording is normal, correct Teacher Portal content).
#
# Scenarios A-J per the review's required fix list. A-C use generate_reply()
# directly with audience="parent" (known leak / Anika wording / enrolled-
# parent variants all still blocked_safety_net). D-G use audience="teacher"
# with the exact same wording (none blocked). H re-confirms ordinary
# parent-safe language is unaffected. I/J re-confirm the retrieval-level
# filter from knowledge_search.py (tests A/B above) still holds - listed
# again here under their own names so this task's required scenario list is
# satisfied explicitly, not just by inference from the earlier tests.
# ---------------------------------------------------------------------------

def test_gr_A_parent_audience_known_leak_blocked():
    reply_generator.client.chat.completions.set_next(
        _fake_chat_response("Our coordination team will identify a suitable rescheduled time.")
    )
    text, status = reply_generator.generate_reply(
        gmail_message_id="gr-A", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
        audience="parent",
    )
    check(
        "A. parent audience + known teacher-facing leak -> blocked_safety_net",
        status == "blocked_safety_net" and text == "",
        f"got status={status!r} text={text!r}",
    )


def test_gr_B_parent_audience_anika_wording_blocked():
    reply_generator.client.chat.completions.set_next(
        _fake_chat_response(
            "Once we have these details, our platform team will identify a "
            "suitable Friday time and update the enrolled parents."
        )
    )
    text, status = reply_generator.generate_reply(
        gmail_message_id="gr-B", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
        audience="parent",
    )
    check(
        "B. parent audience + Anika 'platform team will identify...' wording -> blocked_safety_net",
        status == "blocked_safety_net" and text == "",
        f"got status={status!r} text={text!r}",
    )


def test_gr_C_parent_audience_enrolled_parent_variant_blocked():
    reply_generator.client.chat.completions.set_next(
        _fake_chat_response("We will update the enrolled parents once this is confirmed.")
    )
    text, status = reply_generator.generate_reply(
        gmail_message_id="gr-C", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
        audience="parent",
    )
    check(
        "C. parent audience + enrolled-parent variant -> blocked_safety_net",
        status == "blocked_safety_net" and text == "",
        f"got status={status!r} text={text!r}",
    )


def test_gr_D_teacher_audience_platform_team_not_blocked():
    reply_text = (
        "Once you confirm the new date, our platform team will identify a "
        "suitable makeup time."
    )
    reply_generator.client.chat.completions.set_next(_fake_chat_response(reply_text))
    text, status = reply_generator.generate_reply(
        gmail_message_id="gr-D", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
        audience="teacher",
    )
    check(
        "D. teacher audience + 'platform team will identify...' -> NOT blocked",
        status == "ok" and text == reply_text,
        f"got status={status!r} text={text!r}",
    )


def test_gr_E_teacher_audience_update_enrolled_parents_not_blocked():
    reply_text = "We will update the enrolled parents once this is confirmed."
    reply_generator.client.chat.completions.set_next(_fake_chat_response(reply_text))
    text, status = reply_generator.generate_reply(
        gmail_message_id="gr-E", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
        audience="teacher",
    )
    check(
        "E. teacher audience + 'update the enrolled parents' -> NOT blocked",
        status == "ok" and text == reply_text,
        f"got status={status!r} text={text!r}",
    )


def test_gr_F_teacher_audience_notify_enrolled_parents_not_blocked():
    reply_text = "You do not need to notify the enrolled parents yourself."
    reply_generator.client.chat.completions.set_next(_fake_chat_response(reply_text))
    text, status = reply_generator.generate_reply(
        gmail_message_id="gr-F", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
        audience="teacher",
    )
    check(
        "F. teacher audience + 'notify the enrolled parents' -> NOT blocked",
        status == "ok" and text == reply_text,
        f"got status={status!r} text={text!r}",
    )


def test_gr_G_teacher_audience_inform_enrolled_families_not_blocked():
    reply_text = (
        "Our platform team will handle rescheduling and inform enrolled families."
    )
    reply_generator.client.chat.completions.set_next(_fake_chat_response(reply_text))
    text, status = reply_generator.generate_reply(
        gmail_message_id="gr-G", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
        audience="teacher",
    )
    check(
        "G. teacher audience + 'inform enrolled families' -> NOT blocked",
        status == "ok" and text == reply_text,
        f"got status={status!r} text={text!r}",
    )


def test_gr_H_parent_audience_ordinary_language_unaffected():
    reply_text = "Thanks for reaching out - your class starts Monday at 4pm."
    reply_generator.client.chat.completions.set_next(_fake_chat_response(reply_text))
    text, status = reply_generator.generate_reply(
        gmail_message_id="gr-H", subject="s", body="b", category="General",
        priority="Medium", thread_history="", historical_emails=[], knowledge=[],
        audience="parent",
    )
    check(
        "H. parent audience + ordinary safe language -> unchanged 'ok' behavior",
        status == "ok" and text == reply_text,
        f"got status={status!r} text={text!r}",
    )


def test_gr_I_parent_retrieval_still_filters_teaching():
    database.db_pool.next_fetchall = [_TEACHING_ROW, _PARENT_ROW]
    results = knowledge_search.search_knowledge_base("s", "b", audience="parent", rerank=False)
    check(
        "I. parent retrieval filter still removes category='Teaching'",
        all(r["category"] != "Teaching" for r in results) and len(results) == 1,
    )


def test_gr_J_teacher_retrieval_still_allows_teaching():
    database.db_pool.next_fetchall = [_TEACHING_ROW, _PARENT_ROW]
    results = knowledge_search.search_knowledge_base("s", "b", audience="teacher", rerank=False)
    check(
        "J. teacher retrieval still allows category='Teaching'",
        any(r["category"] == "Teaching" for r in results) and len(results) == 2,
    )


# ---------------------------------------------------------------------------
# Scope confirmation: the 3 real call sites all pass an explicit audience,
# nothing relies on the default silently.
# ---------------------------------------------------------------------------

def test_all_call_sites_pass_explicit_audience():
    """Both the search_knowledge_base() call AND the generate_reply() call
    must each pass an explicit audience in every live production file - so
    this checks for 2 occurrences per file, not just 1."""
    process_email_src = _read_source("process_email.py")
    main_src = _read_source("main.py")
    teacher_src = _read_source("teacher_reply_generator1.py")

    check(
        'process_email.py: both search_knowledge_base() and generate_reply() explicitly pass audience="parent"',
        process_email_src.count('audience="parent"') >= 2,
        f"found {process_email_src.count('audience=\"parent\"')} occurrence(s)",
    )
    check(
        'main.py: both search_knowledge_base() and generate_reply() explicitly pass audience="parent"',
        main_src.count('audience="parent"') >= 2,
        f"found {main_src.count('audience=\"parent\"')} occurrence(s)",
    )
    check(
        'teacher_reply_generator1.py: both search_knowledge_base() and generate_reply() explicitly pass audience="teacher"',
        teacher_src.count('audience="teacher"') >= 2,
        f"found {teacher_src.count('audience=\"teacher\"')} occurrence(s)",
    )


def test_ai_classifier_and_prompt_builder_untouched():
    """Explicitly out of scope for this task per its own instructions."""
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    )
    changed = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    check("ai_classifier.py was not modified by this task", "ai_classifier.py" not in changed)
    check("prompt_builder.py was not modified by this task", "prompt_builder.py" not in changed)


def main():
    test_A_parent_audience_filters_out_teaching_content()
    test_B_teacher_audience_keeps_teaching_content()
    test_C_parent_audience_parent_facing_kb_unaffected()
    test_D_parent_audience_all_teaching_is_genuine_empty_not_error()
    test_E_existing_exact_patterns_still_blocked()
    test_F_anika_paraphrase_blocked()
    test_G_enrolled_parents_variant_blocked()
    test_H_ordinary_language_not_blocked()
    test_I_p0_1_no_reply_gate_intact()
    test_J_p0_2_priority_logic_intact()
    test_K_p0_3_short_circuit_still_precedes_retrieval()
    test_L_teacher_portal_retrieval_wiring_passes_teacher_audience()
    test_L_teacher_portal_behaviorally_still_gets_teaching_content()
    test_gr_A_parent_audience_known_leak_blocked()
    test_gr_B_parent_audience_anika_wording_blocked()
    test_gr_C_parent_audience_enrolled_parent_variant_blocked()
    test_gr_D_teacher_audience_platform_team_not_blocked()
    test_gr_E_teacher_audience_update_enrolled_parents_not_blocked()
    test_gr_F_teacher_audience_notify_enrolled_parents_not_blocked()
    test_gr_G_teacher_audience_inform_enrolled_families_not_blocked()
    test_gr_H_parent_audience_ordinary_language_unaffected()
    test_gr_I_parent_retrieval_still_filters_teaching()
    test_gr_J_teacher_retrieval_still_allows_teaching()
    test_all_call_sites_pass_explicit_audience()
    test_ai_classifier_and_prompt_builder_untouched()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
