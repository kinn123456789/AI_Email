"""Focused tests for the mailbox history onboarding fix:

1. database.add_email_account() now returns (id, is_new) instead of just
   id, using RETURNING id, (xmax = 0) AS inserted - the standard Postgres
   idiom for "this row came from the INSERT branch, not the ON CONFLICT
   UPDATE branch." Tested behaviorally below via a fake psycopg2 cursor,
   since database.py can actually be imported here once psycopg2 is faked
   (the same technique test_vector_search_staff_cache.py already uses).

2. main.py's add_settings_account() schedules a one-time history-onboarding
   background task - sync_sent_mail_style_examples(only_email=email) then
   embed_historical_emails.main() - only when is_new is True, never on a
   re-add/reactivation. main.py itself needs fastapi + apscheduler (and
   starts real scheduler.py background jobs at import time), not
   importable in this sandbox - same justification test_review_reasons.py
   and test_mailbox_settings_add.py already give for this exact file, so
   this half is covered via direct source inspection, matching this
   repo's established convention for main.py.

Run with: python3 test_mailbox_history_onboarding.py
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


# ===========================================================================
# Part 1: database.add_email_account() - real behavioral test.
# ===========================================================================

def _install_fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class FakeOpenAI:
    def __init__(self, *a, **kw):
        pass


class FakeCursor:
    """Returns dict-like rows (mirroring RealDictCursor) whose "inserted"
    key is controlled per-test, standing in for Postgres's real
    (xmax = 0) AS inserted computation."""

    def __init__(self, pool):
        self._pool = pool

    def execute(self, sql, params=None):
        self._pool.last_sql = sql
        self._pool.last_params = params

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
        self._pool.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


class FakeSimpleConnectionPool:
    def __init__(self, *a, **kw):
        self.next_fetchone = None
        self.last_sql = None
        self.last_params = None
        self.committed = False

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
    psycopg2_mod.connect = lambda *a, **kw: None


_install_fakes()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database  # noqa: E402

database.db_pool = FakeSimpleConnectionPool()


def test_add_email_account_returns_id_and_is_new_true_on_fresh_insert():
    database.db_pool.next_fetchone = {"id": 42, "inserted": True}
    result = database.add_email_account("brand-new@coralacademy.com")
    check("add_email_account() returns a 2-tuple", isinstance(result, tuple) and len(result) == 2)
    check("the id is passed through unchanged", result[0] == 42)
    check("is_new is True for a genuine INSERT", result[1] is True)
    check("the connection was committed", database.db_pool.committed is True)


def test_add_email_account_returns_is_new_false_on_conflict_reactivation():
    database.db_pool.next_fetchone = {"id": 42, "inserted": False}
    result = database.add_email_account("already-existing@coralacademy.com")
    check("the same id is returned for a re-add", result[0] == 42)
    check("is_new is False when the ON CONFLICT branch fired", result[1] is False)


def test_add_email_account_sql_uses_the_xmax_idiom():
    database.db_pool.next_fetchone = {"id": 1, "inserted": True}
    database.add_email_account("x@coralacademy.com")
    check(
        "the query's RETURNING clause uses (xmax = 0) AS inserted",
        "RETURNING id, (xmax = 0) AS inserted" in database.db_pool.last_sql,
    )
    check(
        "the INSERT/ON CONFLICT/status='active' shape is otherwise unchanged",
        "INSERT INTO email_accounts (email, source_label)" in database.db_pool.last_sql
        and "ON CONFLICT (email) DO UPDATE SET status = 'active'" in database.db_pool.last_sql,
    )


def test_add_email_account_still_defaults_source_label_to_email():
    database.db_pool.next_fetchone = {"id": 1, "inserted": True}
    database.add_email_account("defaultlabel@coralacademy.com")
    check(
        "source_label still defaults to the email address itself when omitted",
        database.db_pool.last_params == ("defaultlabel@coralacademy.com", "defaultlabel@coralacademy.com"),
    )


# ===========================================================================
# Part 2: main.py's add_settings_account() - source-presence checks.
# ===========================================================================

def _route_body():
    src = _read_source("main.py")
    start = src.index("def _onboard_new_mailbox_history(email):")
    end = src.index('@app.post("/settings/accounts/{account_id}/delete")')
    assert start != -1 and end != -1 and end > start, "could not locate add_settings_account()'s body"
    return src[start:end]


def test_route_accepts_background_tasks():
    body = _route_body()
    check(
        "add_settings_account() now declares a BackgroundTasks parameter",
        "async def add_settings_account(request: Request, background_tasks: BackgroundTasks):" in body,
    )


def test_route_captures_is_new_from_add_email_account():
    body = _route_body()
    check(
        "the route captures (account_id, is_new) from add_email_account()",
        "account_id, is_new = add_email_account(email)" in body,
    )


def test_onboarding_scheduled_only_when_is_new():
    body = _route_body()
    check(
        "the background task is only scheduled inside an `if is_new:` guard",
        "if is_new:\n        background_tasks.add_task(_onboard_new_mailbox_history, email)" in body,
    )


def test_register_watch_behavior_unchanged():
    body = _route_body()
    check(
        "register_watch() is still called unconditionally (not gated by is_new)",
        "register_watch(email)" in body
        and 'print(f"Could not register watch for new account {email}: {e}")' in body,
    )
    idx_register = body.index("register_watch(email)")
    idx_guard = body.index("if is_new:")
    check(
        "register_watch() still runs before the onboarding scheduling (call order preserved)",
        idx_register < idx_guard,
    )


def test_onboarding_wrapper_calls_the_right_functions_in_order():
    src = _read_source("main.py")
    start = src.index("def _onboard_new_mailbox_history(email):")
    end = src.index("@app.post(\"/settings/accounts/add\")")
    wrapper_body = src[start:end]

    check(
        "the wrapper imports sync_sent_mail_style_examples from learn_email_style",
        "from learn_email_style import sync_sent_mail_style_examples" in wrapper_body,
    )
    check(
        "the wrapper imports embed_historical_emails.main unchanged (aliased, not modified)",
        "from embed_historical_emails import main as embed_historical_emails" in wrapper_body,
    )
    check(
        "sync is scoped to only this one mailbox via only_email=email",
        "sync_sent_mail_style_examples(only_email=email)" in wrapper_body,
    )
    check(
        "embed_historical_emails() is called with no arguments (reused completely unmodified)",
        "embed_historical_emails()" in wrapper_body,
    )

    idx_sync = wrapper_body.index("sync_sent_mail_style_examples(only_email=email)")
    idx_embed = wrapper_body.index("embed_historical_emails()")
    check("sync runs before embed (correct order)", idx_sync < idx_embed)


def test_onboarding_failure_is_caught_and_logged_not_raised():
    src = _read_source("main.py")
    start = src.index("def _onboard_new_mailbox_history(email):")
    end = src.index("@app.post(\"/settings/accounts/add\")")
    wrapper_body = src[start:end]

    check(
        "the wrapper's sync+embed calls are wrapped in their own try/except",
        "try:\n        sync_sent_mail_style_examples(only_email=email)\n        embed_historical_emails()\n    except Exception as e:" in wrapper_body,
    )
    check(
        "a failure is logged, not silently swallowed and not re-raised",
        'print(f"Mailbox history onboarding failed for {email}: {e}")' in wrapper_body,
    )
    check(
        "no bare `raise` exists inside this wrapper (a failure must never propagate)",
        "raise" not in wrapper_body,
    )


def _route_only_body():
    """Just the add_settings_account() route itself, excluding the
    _onboard_new_mailbox_history() wrapper defined above it."""
    src = _read_source("main.py")
    start = src.index('@app.post("/settings/accounts/add")')
    end = src.index('@app.post("/settings/accounts/{account_id}/delete")')
    return src[start:end]


def test_mailbox_creation_unaffected_by_onboarding_whatsoever():
    """Structural proof that onboarding can never block or fail mailbox
    creation: add_email_account() and the success redirect are both outside
    _onboard_new_mailbox_history() entirely, and the background task is
    only ever *scheduled* (non-blocking registration), never awaited or
    called inline, inside add_settings_account()."""
    wrapper_src = _read_source("main.py")[
        _read_source("main.py").index("def _onboard_new_mailbox_history(email):"):
        _read_source("main.py").index('@app.post("/settings/accounts/add")')
    ]
    check(
        "add_email_account(email) is NOT called inside the onboarding wrapper itself",
        "add_email_account(email)" not in wrapper_src,
    )

    route_body = _route_only_body()
    check(
        "the success redirect still exists in the route, unconditional on onboarding",
        'url=f"/settings?added={email}"' in route_body,
    )
    check(
        "the only real call to _onboard_new_mailbox_history in the route is via background_tasks.add_task(...)",
        "background_tasks.add_task(_onboard_new_mailbox_history, email)" in route_body,
    )
    check(
        "it is never awaited or called directly (the only executable call syntax is add_task(...), never a bare function call)",
        "await _onboard_new_mailbox_history" not in route_body
        and "_onboard_new_mailbox_history(email)" not in route_body.replace(
            "background_tasks.add_task(_onboard_new_mailbox_history, email)", ""
        ),
    )


def main():
    tests = [
        test_add_email_account_returns_id_and_is_new_true_on_fresh_insert,
        test_add_email_account_returns_is_new_false_on_conflict_reactivation,
        test_add_email_account_sql_uses_the_xmax_idiom,
        test_add_email_account_still_defaults_source_label_to_email,
        test_route_accepts_background_tasks,
        test_route_captures_is_new_from_add_email_account,
        test_onboarding_scheduled_only_when_is_new,
        test_register_watch_behavior_unchanged,
        test_onboarding_wrapper_calls_the_right_functions_in_order,
        test_onboarding_failure_is_caught_and_logged_not_raised,
        test_mailbox_creation_unaffected_by_onboarding_whatsoever,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
