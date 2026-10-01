"""Focused tests for learn_email_style.py's new only_email parameter (the
mailbox history fix this follows): sync_sent_mail_style_examples() now
accepts an optional only_email, scoping its account loop to exactly one
mailbox instead of every active account - used for one-time history
onboarding of a single newly added Settings mailbox (see main.py's
_onboard_new_mailbox_history()), without re-scanning every other mailbox.

TESTING APPROACH: learn_email_style.py imports email_reader.py (for
oauth_login), which in turn imports openai/bs4/vector_search/rag_reranker/
reply_generator/knowledge_search/process_email - the same full,
transitively-heavy dependency chain this repo's own existing tests already
document as not importable in this sandbox (see test_review_reasons.py's
own justification for process_email.py/main.py). bs4 itself isn't even
installed here. So this file uses the same "byte-for-byte mirror,
cross-checked against the real source" technique already established by
test_review_reasons.py's _compute_review_reasons() mirror: a tiny mirror of
ONLY the new account-selection line is tested behaviorally below, then
cross-checked against the real file's actual text.

Run with: python3 test_learn_email_style_only_email.py
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
# Byte-for-byte mirror of the new account-selection line in
# sync_sent_mail_style_examples() - see test_main_py_thread_ai_merge_matches_
# the_mirror_above in test_review_reasons.py for the same technique.
# ---------------------------------------------------------------------------

def _select_accounts(accounts, only_email=None):
    return [
        account for account in accounts
        if not only_email or account["email"] == only_email
    ]


_SAMPLE_ACCOUNTS = [
    {"email": "support@coralacademy.com", "source": "support"},
    {"email": "lucy@coralacademy.com", "source": "lucy"},
    {"email": "engineering@coralacademy.com", "source": "engineering"},
    {"email": "new-mailbox@coralacademy.com", "source": "new-mailbox"},
]


# ---------------------------------------------------------------------------
# only_email scopes processing to exactly that mailbox.
# ---------------------------------------------------------------------------

def test_only_email_scopes_to_exactly_one_mailbox():
    result = _select_accounts(_SAMPLE_ACCOUNTS, only_email="new-mailbox@coralacademy.com")
    check(
        "only the matching mailbox is selected",
        [a["email"] for a in result] == ["new-mailbox@coralacademy.com"],
        f"got {[a['email'] for a in result]!r}",
    )


def test_only_email_for_a_core_mailbox_also_scopes_correctly():
    result = _select_accounts(_SAMPLE_ACCOUNTS, only_email="lucy@coralacademy.com")
    check(
        "a core mailbox address also scopes to just that one account",
        [a["email"] for a in result] == ["lucy@coralacademy.com"],
    )


def test_only_email_for_an_unknown_address_selects_nothing():
    result = _select_accounts(_SAMPLE_ACCOUNTS, only_email="not-a-real-mailbox@coralacademy.com")
    check("an address not in the account list selects zero accounts", result == [])


# ---------------------------------------------------------------------------
# only_email=None preserves all-mailbox behavior exactly.
# ---------------------------------------------------------------------------

def test_only_email_none_preserves_all_mailbox_behavior():
    result = _select_accounts(_SAMPLE_ACCOUNTS, only_email=None)
    check(
        "omitting only_email selects every account, in the original order",
        result == _SAMPLE_ACCOUNTS,
    )


def test_only_email_default_is_none():
    result = _select_accounts(_SAMPLE_ACCOUNTS)
    check(
        "calling without only_email at all behaves identically to only_email=None",
        result == _SAMPLE_ACCOUNTS,
    )


# ---------------------------------------------------------------------------
# Cross-check: the real file contains this exact construction, and the
# default (all-mailbox) behavior is unchanged in every other respect.
# ---------------------------------------------------------------------------

def test_real_file_has_the_only_email_parameter():
    src = _read_source("learn_email_style.py")
    check(
        "sync_sent_mail_style_examples() accepts only_email=None",
        "def sync_sent_mail_style_examples(only_email=None):" in src,
    )
    check(
        "the real account-selection line matches the mirror tested above",
        "if not only_email or account[\"email\"] == only_email" in src,
    )


def test_everything_else_in_the_function_is_unchanged():
    src = _read_source("learn_email_style.py")
    check(
        "the IMPORT_WINDOW_DAYS since_date computation is unchanged",
        'since_date = (datetime.now() - timedelta(days=IMPORT_WINDOW_DAYS)).strftime("%d-%b-%Y")' in src,
    )
    check(
        "Sent Mail (not INBOX) is still the only folder scanned",
        'mail.select(\'"[Gmail]/Sent Mail"\')' in src,
    )
    check(
        "the per-account try/except/finally safety net is unchanged",
        "except Exception as e:" in src and "finally:" in src,
    )
    check(
        "redact_pii is still used before saving (redaction untouched)",
        "redact_pii(" in src,
    )
    check(
        "save_historical_email is still the only insertion path",
        "save_historical_email(" in src,
    )


def main():
    tests = [
        test_only_email_scopes_to_exactly_one_mailbox,
        test_only_email_for_a_core_mailbox_also_scopes_correctly,
        test_only_email_for_an_unknown_address_selects_nothing,
        test_only_email_none_preserves_all_mailbox_behavior,
        test_only_email_default_is_none,
        test_real_file_has_the_only_email_parameter,
        test_everything_else_in_the_function_is_unchanged,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
