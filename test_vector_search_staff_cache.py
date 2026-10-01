"""Focused tests for vector_search.py's new mailbox-accounts cache (the
mailbox history fix this follows): STAFF_EMAIL_ADDRESSES was previously a
fixed 3-element list read from EMAIL_1/EMAIL_2/EMAIL_3 at import time, which
meant a Settings-added mailbox could never have its own historical_emails
rows retrieved as style examples, no matter how much history accumulated.
_get_staff_email_addresses() replaces that with a small TTL cache over
database.get_all_email_accounts() - the exact same pattern already used and
tested by coral_class_catalog.py's get_cached_catalog() (module-level dict
behind a threading.Lock, no new infrastructure).

Matches this repo's existing test_*.py convention (see test_p0_fixes.py,
test_reasoning_token_observability.py): a plain assert-based script, no
pytest, using the same fake dotenv/openai/psycopg2 injection technique so
vector_search.py (via database.py) can actually be imported in this
sandbox, which has neither package installed.

Run with: python3 test_vector_search_staff_cache.py
"""

import os
import sys
import types
from datetime import datetime, timedelta, timezone


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


# ---------------------------------------------------------------------------
# Fake infrastructure - identical technique to test_reasoning_token_observability.py,
# so vector_search.py (and the database.py it imports) can be imported here.
# ---------------------------------------------------------------------------

def _install_fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class FakeOpenAI:
    def __init__(self, *a, **kw):
        pass

    def close(self):
        pass


class FakeSimpleConnectionPool:
    def __init__(self, *a, **kw):
        pass

    def getconn(self):
        raise AssertionError("no test here should need a real DB connection")

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
    psycopg2_mod.connect = lambda *a, **kw: None


# The 3 core mailboxes, same as production - set before importing database.py
# so CORE_EMAIL_ACCOUNTS is populated the same way it would be in production.
os.environ.setdefault("EMAIL_1", "support@coralacademy.com")
os.environ.setdefault("EMAIL_2", "lucy@coralacademy.com")
os.environ.setdefault("EMAIL_3", "engineering@coralacademy.com")

_install_fakes()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vector_search  # noqa: E402


# ---------------------------------------------------------------------------
# A. Active mailbox accounts are used instead of the old 3-address constant.
# ---------------------------------------------------------------------------

def test_old_fixed_constant_is_gone():
    check(
        "STAFF_EMAIL_ADDRESSES (the old fixed 3-element constant) no longer exists",
        not hasattr(vector_search, "STAFF_EMAIL_ADDRESSES"),
    )


def test_cache_calls_get_all_email_accounts_and_extracts_emails():
    vector_search._staff_email_cache["result"] = None
    vector_search._staff_email_cache["fetched_at"] = None

    calls = []

    def fake_get_all_email_accounts():
        calls.append(1)
        return [
            {"email": "support@coralacademy.com", "source": "support", "core": True},
            {"email": "new-mailbox@coralacademy.com", "source": "new-mailbox", "core": False, "id": 7},
        ]

    original = vector_search.get_all_email_accounts
    vector_search.get_all_email_accounts = fake_get_all_email_accounts
    try:
        result = vector_search._get_staff_email_addresses()
    finally:
        vector_search.get_all_email_accounts = original

    check(
        "the returned list is built from get_all_email_accounts()'s own 'email' field",
        result == ["support@coralacademy.com", "new-mailbox@coralacademy.com"],
        f"got {result!r}",
    )
    check("get_all_email_accounts() was actually called", len(calls) == 1)


def test_a_settings_added_mailbox_is_included():
    """The exact scenario this fix exists for: a mailbox that is NOT one of
    the 3 core addresses must still appear in the retrieval allow-list."""
    vector_search._staff_email_cache["result"] = None
    vector_search._staff_email_cache["fetched_at"] = None

    def fake_get_all_email_accounts():
        return [{"email": "a-new-settings-mailbox@coralacademy.com"}]

    original = vector_search.get_all_email_accounts
    vector_search.get_all_email_accounts = fake_get_all_email_accounts
    try:
        result = vector_search._get_staff_email_addresses()
    finally:
        vector_search.get_all_email_accounts = original

    check(
        "a Settings-added (non-core) mailbox address is included",
        "a-new-settings-mailbox@coralacademy.com" in result,
    )


# ---------------------------------------------------------------------------
# B. Cache prevents repeated get_all_email_accounts() calls inside the TTL.
# ---------------------------------------------------------------------------

def test_cache_prevents_repeated_calls_within_ttl():
    vector_search._staff_email_cache["result"] = None
    vector_search._staff_email_cache["fetched_at"] = None

    calls = []

    def fake_get_all_email_accounts():
        calls.append(1)
        return [{"email": "a@coralacademy.com"}]

    original = vector_search.get_all_email_accounts
    vector_search.get_all_email_accounts = fake_get_all_email_accounts
    try:
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

        first = vector_search._get_staff_email_addresses(now=t0)
        second = vector_search._get_staff_email_addresses(
            now=t0 + timedelta(seconds=1)
        )
        third = vector_search._get_staff_email_addresses(
            now=t0 + timedelta(seconds=vector_search.STAFF_EMAIL_CACHE_TTL_SECONDS - 1)
        )
    finally:
        vector_search.get_all_email_accounts = original

    check("first call fetches fresh data", first == ["a@coralacademy.com"])
    check("second call (1s later) reuses the cache, same result", second == first)
    check("third call (just under the TTL) still reuses the cache", third == first)
    check(
        "get_all_email_accounts() was only called once across all three calls",
        len(calls) == 1,
        f"got {len(calls)} calls",
    )


# ---------------------------------------------------------------------------
# C. Cache refreshes after the TTL.
# ---------------------------------------------------------------------------

def test_cache_refreshes_after_ttl():
    vector_search._staff_email_cache["result"] = None
    vector_search._staff_email_cache["fetched_at"] = None

    calls = []

    def fake_get_all_email_accounts():
        calls.append(1)
        return [{"email": f"call-{len(calls)}@coralacademy.com"}]

    original = vector_search.get_all_email_accounts
    vector_search.get_all_email_accounts = fake_get_all_email_accounts
    try:
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

        first = vector_search._get_staff_email_addresses(now=t0)
        after_ttl = vector_search._get_staff_email_addresses(
            now=t0 + timedelta(seconds=vector_search.STAFF_EMAIL_CACHE_TTL_SECONDS + 1)
        )
    finally:
        vector_search.get_all_email_accounts = original

    check("the first call returns the first fetch's data", first == ["call-1@coralacademy.com"])
    check(
        "a call made after the TTL window fetches fresh data again (a different result)",
        after_ttl == ["call-2@coralacademy.com"],
        f"got {after_ttl!r}",
    )
    check("get_all_email_accounts() was called exactly twice", len(calls) == 2, f"got {len(calls)} calls")


# ---------------------------------------------------------------------------
# D. The original 3 core mailboxes remain included (via the real, unfaked
# get_all_email_accounts()/CORE_EMAIL_ACCOUNTS from database.py).
# ---------------------------------------------------------------------------

def test_core_mailboxes_still_included_via_real_get_all_email_accounts():
    vector_search._staff_email_cache["result"] = None
    vector_search._staff_email_cache["fetched_at"] = None

    # Uses the REAL vector_search.get_all_email_accounts (imported from the
    # real database.py, with only psycopg2 faked) - get_additional_email_accounts()
    # will try a real SQL call via the fake pool and fail, so this exercises
    # CORE_EMAIL_ACCOUNTS specifically by monkeypatching just the additional-
    # accounts half, the same way main.py's own get_all_email_accounts() is
    # structured (core list + additional rows).
    import database

    original_additional = database.get_additional_email_accounts
    database.get_additional_email_accounts = lambda: []
    try:
        result = vector_search._get_staff_email_addresses()
    finally:
        database.get_additional_email_accounts = original_additional

    for core_email in ("support@coralacademy.com", "lucy@coralacademy.com", "engineering@coralacademy.com"):
        check(f"core mailbox {core_email} is included", core_email in result)


def test_search_similar_emails_still_calls_the_cache_not_a_fixed_constant():
    import inspect

    src = inspect.getsource(vector_search.search_similar_emails)
    check(
        "search_similar_emails() reads the sender allow-list via the cache function",
        "_get_staff_email_addresses()" in src,
    )
    check(
        "the query parameters still pass that list as the sender filter, not a literal constant",
        "staff_email_addresses, query_embedding, query_embedding, limit" in src,
    )


def main():
    tests = [
        test_old_fixed_constant_is_gone,
        test_cache_calls_get_all_email_accounts_and_extracts_emails,
        test_a_settings_added_mailbox_is_included,
        test_cache_prevents_repeated_calls_within_ttl,
        test_cache_refreshes_after_ttl,
        test_core_mailboxes_still_included_via_real_get_all_email_accounts,
        test_search_similar_emails_still_calls_the_cache_not_a_fixed_constant,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
