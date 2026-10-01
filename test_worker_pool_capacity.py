"""Focused tests for the final pre-freeze worker-pool capacity fix:
email_reader.py's mailbox-level ThreadPoolExecutor was hardcoded to
max_workers=3 (sized for the original 3 core mailboxes), while production
now has 4 active mailboxes (3 core + 1 added via Settings) - the 4th was
being serialized behind the first 3 on every poll instead of running
concurrently. Raised to max_workers=4, a fixed/hardcoded capacity exactly
as before, not a dynamic count derived from the account list.

Matches this repo's existing test_*.py convention - a plain assert-based
script, no pytest. email_reader.py cannot be imported in this sandbox (see
test_mailbox_concurrency.py's own documented limitation), so this is a
source-presence check against the real file, the same technique
test_mailbox_concurrency.py already uses for this exact executor.

Run with: python3 test_worker_pool_capacity.py
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


_SRC = _read_source("email_reader.py")


def test_executor_capacity_is_4():
    check(
        "email_reader.py's mailbox-level executor is now ThreadPoolExecutor(max_workers=4)",
        "with ThreadPoolExecutor(max_workers=4) as executor:" in _SRC,
    )
    check(
        "the old max_workers=3 construction no longer exists",
        "with ThreadPoolExecutor(max_workers=3) as executor:" not in _SRC,
    )
    check(
        "exactly one ThreadPoolExecutor exists in email_reader.py's main() (no new concurrency layer added)",
        _SRC.count("ThreadPoolExecutor(max_workers=4)") == 1,
    )


def test_capacity_is_still_a_fixed_constant_not_dynamic():
    """The task explicitly requires a simple, fixed capacity - not one
    derived from get_all_email_accounts() or any other dynamic count."""
    main_start = _SRC.index("def main(target_email=None):")
    main_end = _SRC.index("print(\"=\" * 60)\n    print(\"ABOUT TO START SENT MAIL SYNC\")")
    main_body = _SRC[main_start:main_end]
    check(
        "max_workers is a literal integer (4), not computed from len(accounts) or similar",
        "ThreadPoolExecutor(max_workers=4)" in main_body
        and "max_workers=len(" not in main_body,
    )


def test_everything_else_in_main_is_unchanged():
    """Per-mailbox isolation, as_completed() dispatch, and per-future error
    handling must be byte-for-byte unchanged - only the capacity number
    changed."""
    check(
        "as_completed() dispatch is unchanged",
        "for future in as_completed(futures):" in _SRC,
    )
    check(
        "per-future exception isolation (one bad mailbox doesn't stop the others) is unchanged",
        "except Exception:\n                print(f\"[{account.get('email')}] mailbox worker failed:\")\n                traceback.print_exc()\n                continue" in _SRC,
    )
    check(
        "each worker still submits _process_account per account (one isolated client bundle per mailbox, unchanged)",
        "executor.submit(_process_account, account): account" in _SRC,
    )


def test_scheduler_level_concurrency_controls_untouched():
    """max_instances/coalesce/the 1-minute interval all live in
    scheduler.py, not email_reader.py - this fix must not touch any of
    them."""
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    )
    changed = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    check("scheduler.py was not modified by this fix", "scheduler.py" not in changed)


def main():
    tests = [
        test_executor_capacity_is_4,
        test_capacity_is_still_a_fixed_constant_not_dynamic,
        test_everything_else_in_main_is_unchanged,
        test_scheduler_level_concurrency_controls_untouched,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
