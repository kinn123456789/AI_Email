"""Focused tests for the Supabase write guard added to the
trial_followup_test/ developer tooling (trial_followup_test/helpers.py,
trial_followup_test/test_insert.py).

WHAT THIS FIXES: trial_followup_test/config.py builds its Supabase client
from the exact same SUPABASE_URL/SUPABASE_SECRET_KEY environment
variables the rest of this app uses - there is no separate "test"
Supabase project. test_insert.py (no __main__ guard, fires immediately on
execution) creates a real Supabase Auth user plus real Users/Parents/
Learners/Enrollments/FreeTrialPass rows the instant it's run, with no
check on which project it's actually about to write to. A developer
running it against a misconfigured local .env had no safeguard.

THE FIX: every Supabase-writing function in helpers.py
(create_auth_user, insert_user, insert_parent, insert_learner,
insert_enrollment, insert_free_trial) now calls
require_test_write_opt_in() as its first statement - before touching
`supabase` at all - which raises TestSupabaseWritesNotAllowed unless
the environment variable AI_EMAIL_ALLOW_TEST_SUPABASE_WRITES is set to
exactly the string "true". test_insert.py also calls it once at the top
of the script, before importing anything that would construct the
Supabase client's auth-user-creation call, for a fast top-level failure.
No hardcoded test password is referenced anywhere in this guard or in
this test file.

TESTING LIMITATION (same class of limitation as every other test_*.py
in this repo touching a module with an external dependency): this
sandbox has neither the `supabase` nor `dotenv` package installed, so
`trial_followup_test/helpers.py` and `trial_followup_test/config.py`
cannot actually be imported here (config.py's own `from supabase import
create_client` fails immediately). Every check below is therefore either
a structural/source-presence check against the real file text, or a
byte-for-byte Python mirror of require_test_write_opt_in()'s own logic
(it only uses `os.environ` and a plain `raise` - nothing supabase-
specific - so the mirror is exact, not approximate) exercised directly
with a fake environment dict. No pytest, no real network/database access
anywhere in this file - a plain script using only assert statements and
the standard library, per this repo's existing test_*.py convention.

Run with: python3 test_trial_followup_test_write_guard.py
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


HELPERS_SRC = _read_source(os.path.join("trial_followup_test", "helpers.py"))
TEST_INSERT_SRC = _read_source(os.path.join("trial_followup_test", "test_insert.py"))

ENV_VAR_NAME = "AI_EMAIL_ALLOW_TEST_SUPABASE_WRITES"


# ---------------------------------------------------------------------------
# A. Source-level confirmation: the guard exists and runs before every
#    actual Supabase write/auth call, in both files.
# ---------------------------------------------------------------------------

def test_guard_function_defined_with_the_exact_required_env_var():
    check("helpers.py defines require_test_write_opt_in()", "def require_test_write_opt_in():" in HELPERS_SRC)
    check(
        f'the guard checks for exactly "{ENV_VAR_NAME}"',
        f'ALLOW_TEST_SUPABASE_WRITES_ENV_VAR = "{ENV_VAR_NAME}"' in HELPERS_SRC,
    )
    check(
        'the guard requires the value to be exactly "true" (not merely truthy)',
        'os.environ.get(ALLOW_TEST_SUPABASE_WRITES_ENV_VAR) != "true"' in HELPERS_SRC,
    )
    check(
        "the guard never references the hardcoded test password",
        "DEFAULT_PASSWORD" not in HELPERS_SRC[HELPERS_SRC.index("def require_test_write_opt_in"):HELPERS_SRC.index("def create_auth_user")],
    )


def _function_body(src, func_name, next_marker):
    start = src.index(f"def {func_name}(")
    end = src.index(next_marker, start)
    return src[start:end]


def test_every_write_function_calls_the_guard_before_touching_supabase():
    write_functions = [
        ("create_auth_user", "def generate_test_email"),
        ("insert_user", "def insert_parent"),
        ("insert_parent", "def insert_learner"),
        ("insert_learner", "def insert_enrollment"),
        ("insert_enrollment", "def insert_free_trial"),
    ]
    for func_name, next_marker in write_functions:
        body = _function_body(HELPERS_SRC, func_name, next_marker)
        check(f"{func_name}() calls require_test_write_opt_in()", "require_test_write_opt_in()" in body)
        guard_idx = body.find("require_test_write_opt_in()")
        # The real code sometimes chains as `supabase\n    .table(...)`
        # across lines (not a single "supabase." substring), so this
        # looks for the bare identifier reference instead.
        first_supabase_idx = body.find("supabase")
        check(
            f"{func_name}(): the guard runs strictly before the first real `supabase.` call",
            guard_idx != -1 and first_supabase_idx != -1 and guard_idx < first_supabase_idx,
        )

    # insert_free_trial is the last function in the file - no next-function
    # marker to bound it, so it's checked separately against EOF.
    body = HELPERS_SRC[HELPERS_SRC.index("def insert_free_trial("):]
    check("insert_free_trial() calls require_test_write_opt_in()", "require_test_write_opt_in()" in body)
    guard_idx = body.find("require_test_write_opt_in()")
    first_supabase_idx = body.find("supabase")
    check(
        "insert_free_trial(): the guard runs strictly before the first real `supabase.` call",
        guard_idx != -1 and first_supabase_idx != -1 and guard_idx < first_supabase_idx,
    )


def test_test_insert_script_calls_the_guard_before_any_helper_call():
    check(
        "test_insert.py imports require_test_write_opt_in from helpers",
        "require_test_write_opt_in," in TEST_INSERT_SRC or "require_test_write_opt_in" in TEST_INSERT_SRC,
    )
    guard_idx = TEST_INSERT_SRC.find("require_test_write_opt_in()")
    first_create_user_call_idx = TEST_INSERT_SRC.find("create_auth_user(")
    # The first occurrence of "create_auth_user(" is inside the import
    # statement itself - the real *call* is the next occurrence.
    first_create_user_call_idx = TEST_INSERT_SRC.find("create_auth_user(", first_create_user_call_idx + 1)
    check(
        "the top-level guard call appears before the first create_auth_user(...) call",
        guard_idx != -1 and first_create_user_call_idx != -1 and guard_idx < first_create_user_call_idx,
    )


def test_guard_never_prints_the_hardcoded_password():
    check(
        "require_test_write_opt_in()'s error message never references DEFAULT_PASSWORD",
        "DEFAULT_PASSWORD" not in _function_body(HELPERS_SRC, "require_test_write_opt_in", "def create_auth_user"),
    )


# ---------------------------------------------------------------------------
# B. Behavioral mirror of require_test_write_opt_in() - exercised directly,
#    not just asserted as source text.
# ---------------------------------------------------------------------------

class _MirrorTestSupabaseWritesNotAllowed(Exception):
    pass


def _mirror_require_test_write_opt_in(env):
    """Byte-for-byte mirror of helpers.py's require_test_write_opt_in() -
    it only touches os.environ and raises; nothing supabase-specific, so
    this mirror is exact rather than approximate."""
    if env.get(ENV_VAR_NAME) != "true":
        raise _MirrorTestSupabaseWritesNotAllowed(
            "Refusing to write to Supabase: set "
            f"{ENV_VAR_NAME}=true to confirm you intend to run this."
        )


def _simulate_a_write_function(env):
    """Mirrors the shape of every real write function: call the guard
    first, and only then would a real Supabase call happen. Returns
    whether a (simulated) real write was reached."""
    _mirror_require_test_write_opt_in(env)
    return "real_supabase_write_happened"


def test_missing_opt_in_blocks_execution():
    env = {}  # AI_EMAIL_ALLOW_TEST_SUPABASE_WRITES not set at all
    try:
        _simulate_a_write_function(env)
        raised = False
    except _MirrorTestSupabaseWritesNotAllowed:
        raised = True
    check("a completely missing opt-in variable blocks execution", raised is True)


def test_incorrect_opt_in_blocks_execution():
    for bad_value in ("True", "TRUE", "1", "yes", "false", "", " true", "true "):
        env = {ENV_VAR_NAME: bad_value}
        try:
            _simulate_a_write_function(env)
            raised = False
        except _MirrorTestSupabaseWritesNotAllowed:
            raised = True
        check(f"opt-in value {bad_value!r} (not exactly \"true\") blocks execution", raised is True)


def test_exact_true_opt_in_allows_execution_to_proceed():
    env = {ENV_VAR_NAME: "true"}
    result = _simulate_a_write_function(env)
    check(
        'opt-in value exactly "true" allows the function to proceed past the guard',
        result == "real_supabase_write_happened",
    )


def test_no_real_supabase_call_occurs_when_blocked():
    """The strongest claim this sandbox can make without the `supabase`
    package installed: the guard raises and returns control to the
    caller *before* the simulated write marker is ever reached - i.e.
    structurally, nothing after the guard (where the real .execute()/
    .admin.create_user() calls live in helpers.py) can run when blocked."""
    reached_the_write_marker = False

    def _simulated_write_with_tracking(env):
        _mirror_require_test_write_opt_in(env)
        nonlocal reached_the_write_marker
        reached_the_write_marker = True  # mirrors the real supabase.*.execute() call site

    try:
        _simulated_write_with_tracking({})
    except _MirrorTestSupabaseWritesNotAllowed:
        pass

    check("the real-write marker is never reached when the opt-in is missing/wrong", reached_the_write_marker is False)


def main():
    tests = [
        test_guard_function_defined_with_the_exact_required_env_var,
        test_every_write_function_calls_the_guard_before_touching_supabase,
        test_test_insert_script_calls_the_guard_before_any_helper_call,
        test_guard_never_prints_the_hardcoded_password,
        test_missing_opt_in_blocks_execution,
        test_incorrect_opt_in_blocks_execution,
        test_exact_true_opt_in_allows_execution_to_proceed,
        test_no_real_supabase_call_occurs_when_blocked,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
