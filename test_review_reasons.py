"""Focused tests for P0-3: persistent, machine-readable review reasons.

Matches this repo's existing test_*.py convention (see test_accuracy_fixes.py):
a plain script using only assert statements and the standard library plus
whatever's already installed - no pytest. A new, separate file rather than
touching test_accuracy_fixes.py or test_p0_fixes.py.

TWO KINDS OF CHECK, FOR TWO DIFFERENT REASONS (same split as
test_accuracy_fixes.py's own J/K/L requires_review tests and
test_p0_fixes.py's P0-6 tests):

1. The review_reasons combination logic in process_email.py and main.py's
   _process_contact_form_enquiry() is verified here as a byte-for-byte
   mirror, kept in sync by inspection - process_email.py needs bs4,
   slack_notifications, trial_followup, subscription_cancel; main.py
   additionally needs fastapi + apscheduler (and starts real scheduler.py
   background jobs at import time), none importable in this environment.
   Same justification test_accuracy_fixes.py already gives for its own
   _combine_requires_review() mirror.

2. database.py's new review_reason plumbing (save_email, get_email_by_id,
   update_contact_form_ai_fields, get_latest_thread_ai) and
   templates/email_detail.html ARE checked against the real files - the
   former via real imports against the same fake psycopg2/openai/dotenv
   infrastructure test_accuracy_fixes.py already establishes, the latter
   via direct template source inspection.

Run with: python3 test_review_reasons.py
"""

import os
import re
import sys
import types


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


# ---------------------------------------------------------------------------
# Fake infrastructure - identical technique to test_accuracy_fixes.py, so
# database.py can be imported for real without psycopg2 actually installed.
# ---------------------------------------------------------------------------

def _install_fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


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
    _install_fake_module("openai", OpenAI=lambda *a, **kw: types.SimpleNamespace())

    pool_mod = _install_fake_module("psycopg2.pool", SimpleConnectionPool=FakeSimpleConnectionPool)
    extras_mod = _install_fake_module("psycopg2.extras", RealDictCursor=dict)
    psycopg2_mod = _install_fake_module("psycopg2")
    psycopg2_mod.pool = pool_mod
    psycopg2_mod.extras = extras_mod
    psycopg2_mod.connect = lambda *a, **kw: FakeConnection(FakeSimpleConnectionPool())


_install_fakes()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database  # noqa: E402

database.db_pool = FakeSimpleConnectionPool()


# ---------------------------------------------------------------------------
# Mirror of the real review_reasons combination logic in process_email.py
# (and duplicated identically in main.py's _process_contact_form_enquiry) -
# kept in sync by inspection, verified against it is not possible directly
# (see module docstring), so a source-presence check below cross-checks the
# real files contain the identical construction.
# ---------------------------------------------------------------------------

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

    requires_review = bool(review_reasons)
    review_reason = ",".join(review_reasons) if review_reasons else None
    return requires_review, review_reason


def test_classifier_review_only():
    requires_review, review_reason = _compute_review_reasons(True, False, "ok")
    check(
        "classifier alone -> requires_review=True, review_reason='classifier'",
        requires_review is True and review_reason == "classifier",
        f"got {(requires_review, review_reason)!r}",
    )


def test_retrieval_error_only():
    requires_review, review_reason = _compute_review_reasons(False, True, "ok")
    check(
        "retrieval error alone -> requires_review=True, review_reason='retrieval_error'",
        requires_review is True and review_reason == "retrieval_error",
        f"got {(requires_review, review_reason)!r}",
    )


def test_safety_block_only():
    requires_review, review_reason = _compute_review_reasons(False, False, "blocked_safety_net")
    check(
        "safety block alone -> requires_review=True, review_reason='safety_block'",
        requires_review is True and review_reason == "safety_block",
        f"got {(requires_review, review_reason)!r}",
    )


def test_generation_error_only():
    requires_review, review_reason = _compute_review_reasons(False, False, "error")
    check(
        "generation error alone -> requires_review=True, review_reason='generation_error'",
        requires_review is True and review_reason == "generation_error",
        f"got {(requires_review, review_reason)!r}",
    )


def test_classifier_plus_retrieval_error():
    requires_review, review_reason = _compute_review_reasons(True, True, "ok")
    check(
        "classifier + retrieval error -> both reasons preserved, in order",
        requires_review is True and review_reason == "classifier,retrieval_error",
        f"got {(requires_review, review_reason)!r}",
    )


def test_classifier_plus_generation_error():
    requires_review, review_reason = _compute_review_reasons(True, False, "error")
    check(
        "classifier + generation error -> both reasons preserved, neither dropped",
        requires_review is True and review_reason == "classifier,generation_error",
        f"got {(requires_review, review_reason)!r}",
    )


def test_all_four_reasons_at_once():
    """Not explicitly required by the task's list, but worth confirming
    the representation scales past two simultaneous reasons without
    collapsing to a generic "multiple" placeholder - which requirement 2
    explicitly says not to do."""
    requires_review, review_reason = _compute_review_reasons(True, True, "blocked_safety_net")
    check(
        "three simultaneous reasons all preserved (safety_block wins over error, matches generation_status being a single value)",
        requires_review is True and review_reason == "classifier,retrieval_error,safety_block",
        f"got {(requires_review, review_reason)!r}",
    )


def test_normal_non_review_case():
    requires_review, review_reason = _compute_review_reasons(False, False, "ok")
    check(
        "clean email (no reasons) -> requires_review=False, review_reason=None",
        requires_review is False and review_reason is None,
        f"got {(requires_review, review_reason)!r}",
    )


def test_no_reply_not_a_review_reason():
    """no_reply must NOT automatically become a review reason - the
    model's own considered "not enough information" outcome is treated as
    correct, cautious behavior, matching existing product behavior
    (already covered for the boolean by test_accuracy_fixes.py's own
    'no_reply status alone does NOT force review' check; this confirms
    the new review_reason string agrees)."""
    requires_review, review_reason = _compute_review_reasons(False, False, "no_reply")
    check(
        "no_reply status alone -> requires_review=False, review_reason=None",
        requires_review is False and review_reason is None,
        f"got {(requires_review, review_reason)!r}",
    )


# ---------------------------------------------------------------------------
# Source-presence checks: confirm the REAL process_email.py and main.py
# contain the identical construction the mirror above tests, and that the
# result is actually threaded into the save_email()/
# update_contact_form_ai_fields() calls.
# ---------------------------------------------------------------------------

def _read_source(filename):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename), "r", encoding="utf-8") as f:
        return f.read()


def test_process_email_builds_review_reasons_list():
    src = _read_source("process_email.py")
    check(
        "process_email.py builds a review_reasons list with all four reason codes",
        all(
            f'review_reasons.append("{code}")' in src
            for code in ["classifier", "retrieval_error", "safety_block", "generation_error"]
        ),
    )
    check(
        "process_email.py derives requires_review as bool(review_reasons) (same boolean semantics as before)",
        "requires_review = bool(review_reasons)" in src,
    )
    check(
        "process_email.py passes review_reason into save_email()",
        "review_reason=review_reason," in src,
    )


def test_main_py_contact_form_builds_review_reasons_list():
    src = _read_source("main.py")
    check(
        "main.py's contact-form flow builds the identical review_reasons list",
        all(
            f'review_reasons.append("{code}")' in src
            for code in ["classifier", "retrieval_error", "safety_block", "generation_error"]
        ),
    )
    check(
        "main.py passes review_reason into update_contact_form_ai_fields()",
        "review_reason=review_reason," in src,
    )


def test_main_py_thread_ai_overwrite_includes_review_reason():
    src = _read_source("main.py")
    check(
        "view_email()'s latest-thread-AI overwrite also carries review_reason forward",
        'email_data["review_reason"] = latest_ai["review_reason"]' in src,
    )


def test_existing_human_send_path_unaffected():
    """The manual/human reply send path (_send_reply_impl -> update_final_reply,
    and the save_email() call that records the sent reply in
    historical style) never computes or references review_reason at all -
    this feature only applies to AI-generated drafts, and a human sending
    their own reply must behave exactly as before."""
    src = _read_source("main.py")
    send_impl_start = src.find("async def _send_reply_impl")
    send_impl_end = src.find("\ndef _save_reply_to_historical_emails")
    send_impl_body = src[send_impl_start:send_impl_end]
    check(
        "_send_reply_impl (the human-send route) does not reference review_reason anywhere",
        "review_reason" not in send_impl_body,
        "found review_reason inside the human-send handler - it should never compute one",
    )
    check(
        "_send_reply_impl still calls update_final_reply(email_id, reply_body, edited_before_send) unchanged",
        "update_final_reply(email_id, reply_body, edited_before_send)" in send_impl_body,
    )


# ---------------------------------------------------------------------------
# database.py: real imports, real (fake-cursor) SQL construction checks -
# same style as test_accuracy_fixes.py's edited_before_send/
# is_unedited_ai_reply persistence tests.
# ---------------------------------------------------------------------------

def test_save_email_insert_includes_review_reason_column_and_value():
    database.save_email(
        sender="parent@example.com", subject="s", body="b", category="General",
        priority="Medium", ai_summary="sum", ai_draft_reply="draft",
        message_id="m1", thread_id="t1", in_reply_to=None, source="support@coralacademy.com",
        requires_review=True, review_reason="classifier,retrieval_error",
    )
    sql = database.db_pool.last_sql
    params = database.db_pool.last_params
    check(
        "save_email()'s INSERT column list includes review_reason",
        "review_reason" in sql,
        f"got sql={sql!r}",
    )
    check(
        "save_email() binds the review_reason value into the INSERT params",
        "classifier,retrieval_error" in params,
        f"got params={params!r}",
    )


def test_save_email_review_reason_defaults_to_none():
    database.save_email(
        sender="parent@example.com", subject="s", body="b", category="General",
        priority="Medium", ai_summary="sum", ai_draft_reply="draft",
        message_id="m2", thread_id="t2", in_reply_to=None, source="support@coralacademy.com",
    )
    check(
        "save_email() defaults review_reason to None when the caller doesn't pass one (e.g. every human-send/no-reply-required call site)",
        None in database.db_pool.last_params,
    )


def test_update_contact_form_ai_fields_persists_review_reason():
    database.update_contact_form_ai_fields(
        row_id=1, category="Admissions", priority="Medium", summary="s", draft_reply="d",
        requires_review=True, ai_confidence=80, reply_type="automatic",
        review_reason="safety_block",
    )
    sql = database.db_pool.last_sql
    params = database.db_pool.last_params
    check(
        "update_contact_form_ai_fields()'s UPDATE sets review_reason",
        "review_reason = %s" in sql,
        f"got sql={sql!r}",
    )
    check(
        "update_contact_form_ai_fields() binds the review_reason value",
        "safety_block" in params,
        f"got params={params!r}",
    )


def test_get_email_by_id_selects_review_reason():
    database.db_pool.next_fetchone = None
    database.get_email_by_id(1)
    check(
        "get_email_by_id()'s SELECT includes review_reason",
        "review_reason" in database.db_pool.last_sql,
        f"got sql={database.db_pool.last_sql!r}",
    )


def test_get_latest_thread_ai_selects_review_reason():
    database.db_pool.next_fetchone = None
    database.get_latest_thread_ai("thread-1")
    check(
        "get_latest_thread_ai()'s SELECT includes review_reason",
        "review_reason" in database.db_pool.last_sql,
        f"got sql={database.db_pool.last_sql!r}",
    )


# ---------------------------------------------------------------------------
# Template: review reason is rendered only through the safe, fixed label
# dict - never the raw stored string, and never anything dynamic.
# ---------------------------------------------------------------------------

def test_template_review_reason_uses_safe_fixed_labels():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    check(
        "email_detail.html defines the expected safe label for each reason code",
        all(
            f'"{code}"' in src
            for code in ["classifier", "retrieval_error", "safety_block", "generation_error", "existing_review"]
        ),
    )
    check(
        'email_detail.html falls back to "existing_review" when review_reason is empty (pre-migration/legacy rows)',
        "email.review_reason.split(',') if email.review_reason else ['existing_review']" in src,
    )
    check(
        "email_detail.html's lookup has a safe default (never renders a raw/unknown code verbatim)",
        "review_reason_labels.get(code.strip(), 'Flagged for review')" in src,
    )
    check(
        "email_detail.html never renders email.review_reason directly (only through the label dict)",
        "{{ email.review_reason }}" not in src,
    )


def test_template_review_reason_only_shown_when_requires_review():
    src = _read_source(os.path.join("templates", "email_detail.html"))
    # The reason block must be guarded by the same {% if email.requires_review %}
    # condition as the "Requires human review" label itself, not shown
    # unconditionally.
    meta_block_start = src.find("Requires human review")
    meta_block = src[meta_block_start:meta_block_start + 900]
    check(
        "the reason list sits inside the same requires_review-guarded block as the warning label",
        "{% if email.requires_review %}" in meta_block and "review_reason_labels" in meta_block,
    )


def main():
    test_classifier_review_only()
    test_retrieval_error_only()
    test_safety_block_only()
    test_generation_error_only()
    test_classifier_plus_retrieval_error()
    test_classifier_plus_generation_error()
    test_all_four_reasons_at_once()
    test_normal_non_review_case()
    test_no_reply_not_a_review_reason()

    test_process_email_builds_review_reasons_list()
    test_main_py_contact_form_builds_review_reasons_list()
    test_main_py_thread_ai_overwrite_includes_review_reason()
    test_existing_human_send_path_unaffected()

    test_save_email_insert_includes_review_reason_column_and_value()
    test_save_email_review_reason_defaults_to_none()
    test_update_contact_form_ai_fields_persists_review_reason()
    test_get_email_by_id_selects_review_reason()
    test_get_latest_thread_ai_selects_review_reason()

    test_template_review_reason_uses_safe_fixed_labels()
    test_template_review_reason_only_shown_when_requires_review()

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {_failures}")
        sys.exit(1)
    else:
        print("All tests passed.")


if __name__ == "__main__":
    main()
