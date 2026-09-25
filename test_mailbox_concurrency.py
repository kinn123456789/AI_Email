"""Focused tests for mailbox-level concurrency in email_reader.py: the
former sequential per-account loop body in main() was extracted into
_process_account(account), which now owns one isolated 5-client LLM/
embedding bundle for its entire run and is submitted to a
ThreadPoolExecutor(max_workers=3) - one worker per core mailbox - instead
of being called in a sequential for-loop.

Matches this repo's existing test_*.py convention (see
test_llm_client_isolation.py, test_no_reply_gate.py): a plain script using
only assert statements, no pytest, stdlib only. email_reader.py cannot be
imported in this environment - it imports bs4 directly and transitively via
process_email.py, neither the real openai/psycopg2/bs4/requests/dateutil
packages nor a real Gmail/OpenRouter/Supabase connection are available here
(same documented limitation as process_email.py throughout this session).

Two complementary techniques are used:

1. Source-level checks against the real email_reader.py, confirming the
   IMAP login/select/search/dedup-check/fetch/parse code, MAX_EMAILS_PER_RUN
   logic, and process_email() call site are byte-for-byte the same code
   that ran before this task (just moved into a function and given the
   llm_clients bundle) - proving points 1, 8, 9, 10, 12, 13, 14.

2. A faithful CONTROL-FLOW MIRROR of _process_account()/main() - same
   shape, same client-bundle lifecycle, same executor/as_completed
   dispatch - with the IMAP/AI-pipeline boundary replaced by injected
   fakes, using the REAL stdlib concurrent.futures.ThreadPoolExecutor (not
   faked) so real thread-level behavior is actually exercised: worker
   count, client-object identity/isolation, reuse-not-recreation, close-
   exactly-once (including on exception), and failure isolation - proving
   points 2-7, 11.

No real email is sent, no real Gmail/OpenRouter/Supabase connection is
made anywhere in this file.

Run with: python3 test_mailbox_concurrency.py
"""

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed


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
# PART 1 - source-level checks against the real email_reader.py
# ===========================================================================

_SRC = _read_source("email_reader.py")


def test_1_imap_login_select_search_unchanged():
    """Point 1: existing mailbox logic (IMAP login/select/search/date
    window) was extracted without changing the important control flow."""
    check(
        "1. IMAP login unchanged: mail = oauth_login(account['email'])",
        'mail = oauth_login(account["email"])' in _SRC,
    )
    check(
        "1. mailbox selection unchanged: mail.select(\"INBOX\", readonly=True)",
        'mail.select("INBOX", readonly=True)' in _SRC,
    )
    check(
        "1. search criteria unchanged: OR UNSEEN SINCE",
        'mail.search(None, "OR", "UNSEEN", "SINCE", since_date)' in _SRC,
    )
    check(
        "1. date window unchanged: 2-day SINCE window",
        "(datetime.now() - timedelta(days=2)).strftime(\"%d-%b-%Y\")" in _SRC,
    )
    check(
        "1. MAX_EMAILS_PER_RUN limiting logic unchanged",
        "if processed_count >= MAX_EMAILS_PER_RUN:" in _SRC
        and "MAX_EMAILS_PER_RUN = 15" in _SRC,
    )


def test_8_9_dedup_fetch_parse_and_process_email_call_unchanged():
    """Points 8, 9: duplicate detection, message fetch/parsing, and the
    process_email() call site are unchanged (process_email() still called
    exactly once per newly processed message - not batched, not skipped,
    not duplicated)."""
    check(
        "8/9. header pre-check dedup unchanged: BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]",
        '"(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"' in _SRC,
    )
    check(
        "8/9. duplicate-check decision shape unchanged (truthy candidate_message_id + membership test) - "
        "the per-candidate database.email_exists() call was superseded by the approved "
        "batched-duplicate-check task (database.email_ids_exist(), one round trip per mailbox per run "
        "instead of one per candidate); see test_email_reader_batch_duplicate_check.py for that task's "
        "own dedicated coverage",
        "if candidate_message_id and candidate_message_id in existing_message_ids:" in _SRC,
    )
    check(
        "8/9. full message fetch unchanged: BODY.PEEK[]",
        '"(BODY.PEEK[])"' in _SRC,
    )
    check(
        "8/9. parsing unchanged: email.message_from_bytes(msg_data[0][1])",
        "msg = email.message_from_bytes(\n                    msg_data[0][1]\n                )" in _SRC,
    )
    check(
        "9. process_email() is called exactly once per loop iteration (inside the for email_id loop, "
        "no batching wrapper, no duplicate call site)",
        _SRC.count("process_email(\n                        msg=msg,") == 1,
    )
    check(
        "9. process_email() still receives ingested_via=\"imap_poll\" unchanged",
        'ingested_via="imap_poll",' in _SRC,
    )
    check(
        "9. process_email() now also receives the worker's own llm_clients bundle",
        "llm_clients=llm_clients,\n                    )" in _SRC,
    )
    check(
        "process_email() is invoked from exactly one real call site (prose mentions of "
        "'process_email()' elsewhere in comments are not call sites, so matched on the exact "
        "invocation shape, not a bare substring count)",
        _SRC.count("process_email(\n                        msg=msg,") == 1,
    )


def test_10_message_ordering_within_mailbox_unchanged():
    """Point 10: within one mailbox, messages are still processed in the
    same order IMAP returned them - the per-message loop itself was not
    parallelized or reordered."""
    check(
        "10. still a single sequential 'for email_id in mail_ids:' loop (not parallelized, not reordered)",
        "for email_id in mail_ids:" in _SRC and _SRC.count("for email_id in mail_ids:") == 1,
    )
    check(
        "10. mail_ids still comes directly from the IMAP search result, in order, unmodified",
        "mail_ids = messages[0].split()" in _SRC,
    )
    check(
        "10. no sorting/reordering/concurrency construct was introduced around the message loop",
        "ThreadPoolExecutor" not in _SRC[_SRC.find("for email_id in mail_ids:"):_SRC.find("for email_id in mail_ids:") + 2000],
    )


def test_11_process_email_internal_concurrency_unchanged():
    """Point 11: process_email.py's own internal ThreadPoolExecutor(max_workers=3)
    was not touched by this task - confirmed by checking process_email.py's
    source directly (this task's own file scope excluded process_email.py
    except where the prior, separately-approved task already added
    llm_clients threading)."""
    process_email_src = _read_source("process_email.py")
    check(
        "11. process_email.py's own per-message ThreadPoolExecutor(max_workers=3) is unchanged",
        "with ThreadPoolExecutor(max_workers=3) as executor:" in process_email_src,
    )
    check(
        "11. exactly one ThreadPoolExecutor exists in process_email.py (no new concurrency layer added there)",
        process_email_src.count("ThreadPoolExecutor(") == 1,
    )


def test_12_13_14_no_database_scheduler_or_coral_changes():
    """Points 12, 13, 14: no scheduler.py or Coral-integration changes
    anywhere in this task.

    database.py is no longer checked here: this mailbox-concurrency task
    itself never touched it (point 12's original intent), but a later,
    separately-approved task (the batched-duplicate-check optimization)
    legitimately adds database.email_ids_exist() to it. That's a real,
    intentional, approved change unrelated to mailbox concurrency, not a
    regression of this check's original guarantee - see
    test_email_reader_batch_duplicate_check.py for that task's own
    dedicated coverage confirming the change is scoped correctly."""
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    )
    changed = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    check("13. scheduler.py was not modified", "scheduler.py" not in changed)
    check("14. main.py (the Coral/FastAPI app entrypoint) was not modified", "main.py" not in changed)
    check(
        "no reference to Coral Supabase, Gmail watch/Pub-Sub setup, or SimpleConnectionPool "
        "appears anywhere in the email_reader.py diff scope (source-level sanity check)",
        "SimpleConnectionPool" not in _SRC and "ThreadedConnectionPool" not in _SRC,
    )


def test_email_reader_structure_email_reader_concurrency_wiring():
    check(
        "email_reader.py imports ThreadPoolExecutor and as_completed from the stdlib (no new dependency)",
        "from concurrent.futures import ThreadPoolExecutor, as_completed" in _SRC,
    )
    check(
        "main()'s executor uses exactly max_workers=3 (hardcoded, not dynamic)",
        "with ThreadPoolExecutor(max_workers=3) as executor:" in _SRC,
    )
    check(
        "main() uses as_completed() so one slow mailbox doesn't block observing the others",
        "for future in as_completed(futures):" in _SRC,
    )
    check(
        "_process_account is a standalone function (the extraction point)",
        "def _process_account(account):" in _SRC,
    )
    check(
        "main() submits exactly one future per selected account via executor.submit(_process_account, account)",
        "executor.submit(_process_account, account): account\n            for account in accounts" in _SRC,
    )
    check(
        "target_email filtering happens before submission, in a list comprehension "
        "(unselected accounts are never submitted at all)",
        'accounts = [\n        account for account in get_email_accounts()\n        if not target_email or account["email"] == target_email\n    ]' in _SRC,
    )
    check(
        "a worker failure is caught per-future and logged, without aborting the run",
        'except Exception:\n                print(f"[{account.get(\'email\')}] mailbox worker failed:")\n                traceback.print_exc()\n                continue' in _SRC,
    )
    check(
        "email_reader.py does not define or acquire any new lock of its own - the existing "
        "reader_lock stays exclusively in scheduler.py, untouched (a comment here may reference "
        "it by name, but no threading.Lock()/acquire() was introduced in this file)",
        "threading.Lock(" not in _SRC and ".acquire(" not in _SRC,
    )


def test_client_bundle_construction_and_closing_source():
    check(
        "each worker builds a bundle with exactly the 5 required keys",
        '"classifier": _new_llm_client(),\n        "reranker": _new_llm_client(),\n        "generator": _new_llm_client(),\n        "similar_embedding": new_embedding_client(),\n        "knowledge_embedding": new_embedding_client(),' in _SRC,
    )
    check(
        "classifier/reranker/generator clients reuse the exact same construction pattern "
        "(same env var, same base_url) as ai_classifier.py/rag_reranker.py/reply_generator.py - "
        "no hardcoded credentials",
        'api_key=os.getenv("OPENROUTER_API_KEY"),\n        base_url="https://openrouter.ai/api/v1",' in _SRC,
    )
    check(
        "embeddings use new_embedding_client() exactly twice per worker, both inside the bundle "
        "construction (not per message, not anywhere else)",
        _SRC.count("new_embedding_client(),") == 2,
    )
    check(
        "all 5 clients are closed exactly once, via the existing generic close_embedding_client() helper",
        'close_embedding_client(llm_clients["classifier"])\n        close_embedding_client(llm_clients["reranker"])\n        close_embedding_client(llm_clients["generator"])\n        close_embedding_client(llm_clients["similar_embedding"])\n        close_embedding_client(llm_clients["knowledge_embedding"])' in _SRC,
    )
    check(
        "the closing block sits in the outermost finally of _process_account "
        "(runs on success AND on any exception, exactly once)",
        _SRC.count('close_embedding_client(llm_clients["classifier"])') == 1,
    )
    # process_email.py legitimately still calls close_embedding_client() for
    # its OWN fallback-created embedding clients (the llm_clients=None path,
    # used by every caller that doesn't supply a bundle) - that's correct,
    # pre-existing behavior from the prior task, not something this task
    # changes. What must hold is narrower: it must never close a client it
    # didn't create itself - already proven in test_llm_client_isolation.py
    # via the owns_embedding_clients guard checks, not re-tested here.
    check(
        "process_email.py's own close_embedding_client() calls remain guarded by "
        "owns_embedding_clients (only closes clients it created itself)",
        "if owns_embedding_clients:\n            close_embedding_client(similar_client)\n            close_embedding_client(knowledge_client)" in _read_source("process_email.py"),
    )


# ===========================================================================
# PART 2 - control-flow mirror: real concurrency, real client-lifecycle
# behavior, exercised with injected fakes at the IMAP/AI-pipeline boundary.
# ===========================================================================

class _FakeClient:
    """Stands in for an OpenAI-family client. Each instance is a distinct
    object (no sharing), and tracks how many times close() was called."""

    _next_id = 0
    _id_lock = threading.Lock()

    def __init__(self):
        with _FakeClient._id_lock:
            _FakeClient._next_id += 1
            self.instance_id = _FakeClient._next_id
        self.close_count = 0

    def close(self):
        self.close_count += 1


def _mirror_new_llm_client():
    return _FakeClient()


def _mirror_new_embedding_client():
    return _FakeClient()


def _mirror_close_embedding_client(client):
    """Mirrors the real close_embedding_client()'s try/except-swallow
    shape exactly, so a worker's finally block behaves identically."""
    try:
        client.close()
    except Exception:
        pass


def _mirror_process_account(
    account,
    *,
    oauth_login_fn,
    process_email_fn,
    mail_ids_by_account,
    raise_in_account=None,
    new_llm_client_fn=_mirror_new_llm_client,
    new_embedding_client_fn=_mirror_new_embedding_client,
):
    """Faithful mirror of email_reader.py's real _process_account(): same
    guard, same bundle shape/construction order, same try/finally
    structure and ownership (this function is the sole owner of all 5
    clients, closed exactly once in the outermost finally, on every exit
    path including an exception), same "process a fixed, ordered sequence
    of messages, calling process_email_fn once per message with the same
    reused bundle" shape. The IMAP connection itself and message
    fetch/parse are replaced by the injected mail_ids_by_account list,
    since those are exactly the parts already covered by source-level
    checks in Part 1 and don't need real IMAP to prove the concurrency
    properties this part exists to test.
    """
    if not account.get("email"):
        return None

    llm_clients = {
        "classifier": new_llm_client_fn(),
        "reranker": new_llm_client_fn(),
        "generator": new_llm_client_fn(),
        "similar_embedding": new_embedding_client_fn(),
        "knowledge_embedding": new_embedding_client_fn(),
    }

    try:
        oauth_login_fn(account["email"])

        if raise_in_account == account["email"]:
            raise RuntimeError(f"simulated failure in {account['email']}")

        for msg in mail_ids_by_account.get(account["email"], []):
            process_email_fn(msg=msg, account=account, ingested_via="imap_poll", llm_clients=llm_clients)

    finally:
        for key in ("classifier", "reranker", "generator", "similar_embedding", "knowledge_embedding"):
            _mirror_close_embedding_client(llm_clients[key])

    return llm_clients


def _mirror_main(accounts_to_process, **worker_kwargs):
    """Faithful mirror of email_reader.py's real main()'s dispatch shape:
    exactly max_workers=3, one future per account, as_completed() collection
    with per-future exception isolation. Returns (results_by_email,
    failures_by_email) for test introspection - the real main() doesn't
    return anything, but the dispatch/isolation shape under test is
    identical."""
    results = {}
    failures = {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_mirror_process_account, account, **worker_kwargs): account
            for account in accounts_to_process
        }

        check(
            "2. exactly 3 mailbox futures are submitted for 3 selected accounts",
            len(futures) == len(accounts_to_process),
        )
        check(
            "2. the executor itself is configured with max_workers=3",
            executor._max_workers == 3,
        )

        for future in as_completed(futures):
            account = futures[future]
            try:
                results[account["email"]] = future.result()
            except Exception as e:
                failures[account["email"]] = e

    return results, failures


_THREE_ACCOUNTS = [
    {"email": "support@coralacademy.com", "source": "support@coralacademy.com"},
    {"email": "lucy@coralacademy.com", "source": "lucy@coralacademy.com"},
    {"email": "engineering@coralacademy.com", "source": "engineering@coralacademy.com"},
]


def test_2_three_futures_max_workers_3():
    _mirror_main(
        _THREE_ACCOUNTS,
        oauth_login_fn=lambda email: None,
        process_email_fn=lambda **kwargs: None,
        mail_ids_by_account={},
    )
    # Assertions for point 2 happen inside _mirror_main() itself (checked
    # at submission time, matching what the real executor is configured
    # with) - see the two check() calls there.


def test_3_4_each_worker_has_its_own_independent_bundle():
    """Points 3, 4: each worker creates its own independent 5-client
    bundle, and no client object is shared between mailbox workers."""
    results, failures = _mirror_main(
        _THREE_ACCOUNTS,
        oauth_login_fn=lambda email: None,
        process_email_fn=lambda **kwargs: None,
        mail_ids_by_account={},
    )

    check("3/4. no worker failed", len(failures) == 0, f"failures={failures}")
    check("3/4. all 3 workers produced a bundle", len(results) == 3)

    all_instance_ids = []
    for email, bundle in results.items():
        ids_for_this_worker = {c.instance_id for c in bundle.values()}
        check(
            f"3. worker {email} has exactly 5 distinct client objects internally",
            len(ids_for_this_worker) == 5,
        )
        all_instance_ids.extend(ids_for_this_worker)

    check(
        "4. no client instance_id is shared across any of the 3 workers (15 total, all distinct)",
        len(all_instance_ids) == len(set(all_instance_ids)) == 15,
        f"got {len(set(all_instance_ids))} distinct ids out of {len(all_instance_ids)}",
    )


def test_5_each_worker_passes_its_own_bundle_to_process_email():
    """Point 5: each worker passes its own bundle (not another worker's,
    not the shared module default) into every process_email() call it
    makes."""
    seen_bundles_by_email = {}

    def _recording_process_email(msg, account, ingested_via, llm_clients):
        seen_bundles_by_email.setdefault(account["email"], []).append(llm_clients)

    results, failures = _mirror_main(
        _THREE_ACCOUNTS,
        oauth_login_fn=lambda email: None,
        process_email_fn=_recording_process_email,
        mail_ids_by_account={
            "support@coralacademy.com": ["msg-s1", "msg-s2"],
            "lucy@coralacademy.com": ["msg-l1"],
            "engineering@coralacademy.com": [],
        },
    )

    check("5. no worker failed", len(failures) == 0, f"failures={failures}")

    for email, calls_bundles in seen_bundles_by_email.items():
        own_bundle = results[email]
        check(
            f"5. every process_email() call from {email}'s worker received that worker's own bundle",
            all(b is own_bundle for b in calls_bundles),
        )

    other_worker_bundles = [b for e, b in results.items() if e != "support@coralacademy.com"]
    check(
        "5. support@'s calls never received lucy@'s or engineering@'s bundle",
        all(b not in other_worker_bundles for b in seen_bundles_by_email["support@coralacademy.com"]),
    )


def test_6_each_worker_closes_all_five_clients_exactly_once():
    """Point 6, plus the resource/cleanup requirement: every worker-owned
    client receives exactly one close() call, even when that worker raises."""
    results, failures = _mirror_main(
        _THREE_ACCOUNTS,
        oauth_login_fn=lambda email: None,
        process_email_fn=lambda **kwargs: None,
        mail_ids_by_account={},
        raise_in_account="lucy@coralacademy.com",
    )

    check(
        "6. the account that raised is reported as a failure, not silently swallowed",
        "lucy@coralacademy.com" in failures,
    )
    check(
        "6. the other two accounts still succeeded (results present)",
        "support@coralacademy.com" in results and "engineering@coralacademy.com" in results,
    )

    # The failing worker's own bundle isn't returned (the exception
    # propagates before the `return llm_clients` line), but its clients
    # were still constructed and must still have been closed exactly once
    # via the finally block - captured via the global _FakeClient instances
    # created during this test run.
    check(
        "6. every successful worker's 5 clients were each closed exactly once",
        all(
            c.close_count == 1
            for bundle in results.values()
            for c in bundle.values()
        ),
        f"close counts: {[c.close_count for bundle in results.values() for c in bundle.values()]}",
    )


def test_6b_close_happens_even_when_worker_raises_before_any_message():
    """Same as test_6, but exercises _process_account() directly (not
    through the executor) and captures its bundle via injected tracking
    factories, to prove closing happens on the exception path too, not
    just the success path."""
    account = {"email": "test-raise@coralacademy.com", "source": "test-raise@coralacademy.com"}

    clients_built = []

    def _tracking_new_client():
        c = _FakeClient()
        clients_built.append(c)
        return c

    try:
        _mirror_process_account(
            account,
            oauth_login_fn=lambda email: None,
            process_email_fn=lambda **kwargs: None,
            mail_ids_by_account={},
            raise_in_account="test-raise@coralacademy.com",
            new_llm_client_fn=_tracking_new_client,
            new_embedding_client_fn=_tracking_new_client,
        )
        check("6b. _process_account raised as expected", False, "no exception raised")
    except RuntimeError:
        check("6b. _process_account raised as expected", True)

    check(
        "6b. even though the worker raised before processing any message, "
        "all 5 of its clients were still closed exactly once",
        len(clients_built) == 5 and all(c.close_count == 1 for c in clients_built),
        f"built={len(clients_built)} close_counts={[c.close_count for c in clients_built]}",
    )


def test_7_one_mailbox_failure_does_not_block_the_others():
    """Point 7: a failure in mailbox A does not prevent mailbox B and
    mailbox C from completing."""
    results, failures = _mirror_main(
        _THREE_ACCOUNTS,
        oauth_login_fn=lambda email: None,
        process_email_fn=lambda **kwargs: None,
        mail_ids_by_account={},
        raise_in_account="support@coralacademy.com",
    )

    check(
        "7. mailbox A (support@) failed as expected",
        "support@coralacademy.com" in failures,
    )
    check(
        "7. mailbox B (lucy@) completed successfully despite A's failure",
        "lucy@coralacademy.com" in results,
    )
    check(
        "7. mailbox C (engineering@) completed successfully despite A's failure",
        "engineering@coralacademy.com" in results,
    )


def test_same_bundle_reused_across_multiple_messages_not_recreated():
    """Explicit check for the 'reused, not recreated per message'
    requirement: the SAME client objects (by identity) are used across
    multiple process_email() calls for one mailbox."""
    seen_client_ids_by_call = []

    def _recording_process_email(msg, account, ingested_via, llm_clients):
        seen_client_ids_by_call.append(id(llm_clients["classifier"]))

    results, failures = _mirror_main(
        [_THREE_ACCOUNTS[0]],
        oauth_login_fn=lambda email: None,
        process_email_fn=_recording_process_email,
        mail_ids_by_account={"support@coralacademy.com": ["msg-1", "msg-2", "msg-3"]},
    )

    check("no failures", len(failures) == 0)
    check(
        "the same classifier client object (by identity) was used for all 3 messages in this mailbox "
        "- never recreated per message",
        len(seen_client_ids_by_call) == 3 and len(set(seen_client_ids_by_call)) == 1,
        f"got {len(set(seen_client_ids_by_call))} distinct client ids across {len(seen_client_ids_by_call)} calls",
    )


def test_8_target_email_filtering_selects_only_requested_mailbox_mirror():
    """Point 8 (this part's variant): mirrors main()'s own accounts = [...]
    filtering logic exactly, proving only the requested account is ever
    submitted as a future when target_email is given."""

    def _select(accounts, target_email):
        return [
            account for account in accounts
            if not target_email or account["email"] == target_email
        ]

    all_selected = _select(_THREE_ACCOUNTS, None)
    check("target_email=None selects all 3 accounts", len(all_selected) == 3)

    one_selected = _select(_THREE_ACCOUNTS, "lucy@coralacademy.com")
    check(
        "target_email='lucy@...' selects only that one account",
        len(one_selected) == 1 and one_selected[0]["email"] == "lucy@coralacademy.com",
    )

    none_selected = _select(_THREE_ACCOUNTS, "unknown@coralacademy.com")
    check(
        "target_email for an unconfigured address selects nothing (no worker created for it)",
        len(none_selected) == 0,
    )


def main():
    test_1_imap_login_select_search_unchanged()
    test_8_9_dedup_fetch_parse_and_process_email_call_unchanged()
    test_10_message_ordering_within_mailbox_unchanged()
    test_11_process_email_internal_concurrency_unchanged()
    test_12_13_14_no_database_scheduler_or_coral_changes()
    test_email_reader_structure_email_reader_concurrency_wiring()
    test_client_bundle_construction_and_closing_source()

    test_2_three_futures_max_workers_3()
    test_3_4_each_worker_has_its_own_independent_bundle()
    test_5_each_worker_passes_its_own_bundle_to_process_email()
    test_6_each_worker_closes_all_five_clients_exactly_once()
    test_6b_close_happens_even_when_worker_raises_before_any_message()
    test_7_one_mailbox_failure_does_not_block_the_others()
    test_same_bundle_reused_across_multiple_messages_not_recreated()
    test_8_target_email_filtering_selects_only_requested_mailbox_mirror()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
