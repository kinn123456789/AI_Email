"""Focused tests for Candidate 1 from the IMAP-bottleneck investigation:
batching email_reader.py's pre-check duplicate lookup into one DB round
trip per mailbox per run, via the new database.email_ids_exist(), instead
of calling database.email_exists() once per candidate.

Matches this repo's existing test_*.py convention (see
test_mailbox_concurrency.py, test_rerank_empty_guard.py): a plain script
using only assert statements, no pytest, stdlib only. database.py IS
importable via the established fake psycopg2 infrastructure, so
email_ids_exist() is tested behaviorally, for real. email_reader.py cannot
be imported in this environment (needs bs4, transitively via
process_email.py - same documented limitation as every other test file
covering it this session) - its Stage 1/2/3 restructuring is verified as a
faithful control-flow mirror (same shape, same decisions, IMAP/DB replaced
with injected fakes) plus source-level checks against the real file.

No real database, Gmail, or network connection is made anywhere in this
file.

Run with: python3 test_email_reader_batch_duplicate_check.py
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
# PART 1 - database.email_ids_exist(), real behavior via fake psycopg2.
# ===========================================================================

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
        self._pool.execute_calls.append((sql, params))

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
        self.execute_calls = []
        self.getconn_count = 0
        self.putconn_count = 0

    def getconn(self):
        self.getconn_count += 1
        return FakeConnection(self)

    def putconn(self, conn):
        self.putconn_count += 1


_install_fake_module("dotenv", load_dotenv=lambda *a, **kw: None)
pool_mod = _install_fake_module("psycopg2.pool", SimpleConnectionPool=FakeSimpleConnectionPool)
extras_mod = _install_fake_module("psycopg2.extras", RealDictCursor=dict)
psycopg2_mod = _install_fake_module("psycopg2")
psycopg2_mod.pool = pool_mod
psycopg2_mod.extras = extras_mod
psycopg2_mod.connect = lambda *a, **kw: FakeConnection(FakeSimpleConnectionPool())

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database  # noqa: E402

database.db_pool = FakeSimpleConnectionPool()


def test_empty_candidate_list_no_db_query_empty_result():
    database.db_pool = FakeSimpleConnectionPool()  # fresh pool, no getconn() calls yet

    result = database.email_ids_exist([], "support@coralacademy.com")

    check("empty input -> empty set returned", result == set())
    check(
        "empty input -> no DB connection is checked out at all (no getconn() call)",
        database.db_pool.getconn_count == 0,
    )


def test_all_candidates_already_exist():
    database.db_pool = FakeSimpleConnectionPool()
    database.db_pool.next_fetchall = [("<a@x>",), ("<b@x>",)]

    result = database.email_ids_exist(["<a@x>", "<b@x>"], "support@coralacademy.com")

    check("all candidates already exist -> both returned", result == {"<a@x>", "<b@x>"})


def test_none_exist():
    database.db_pool = FakeSimpleConnectionPool()
    database.db_pool.next_fetchall = []

    result = database.email_ids_exist(["<a@x>", "<b@x>"], "support@coralacademy.com")

    check("none exist -> empty set returned (all treated as new)", result == set())


def test_mixed_existing_and_new():
    database.db_pool = FakeSimpleConnectionPool()
    database.db_pool.next_fetchall = [("<b@x>",)]  # only b exists

    result = database.email_ids_exist(["<a@x>", "<b@x>", "<c@x>"], "support@coralacademy.com")

    check("mixed candidates -> only the existing one is returned", result == {"<b@x>"})


def test_one_batched_query_not_n_calls():
    database.db_pool = FakeSimpleConnectionPool()
    database.db_pool.next_fetchall = []

    database.email_ids_exist(["<a@x>", "<b@x>", "<c@x>", "<d@x>"], "support@coralacademy.com")

    check(
        "exactly one execute() call regardless of candidate count (batched, not N calls)",
        len(database.db_pool.execute_calls) == 1,
        f"got {len(database.db_pool.execute_calls)} execute() calls",
    )
    check(
        "exactly one connection checked out and one returned (not N)",
        database.db_pool.getconn_count == 1 and database.db_pool.putconn_count == 1,
    )


def test_source_and_query_shape():
    database.db_pool = FakeSimpleConnectionPool()
    database.db_pool.next_fetchall = []

    database.email_ids_exist(["<a@x>"], "lucy@coralacademy.com")

    sql, params = database.db_pool.execute_calls[0]
    check(
        "query shape uses source = %s AND message_id = ANY(%s)",
        "source = %s" in sql and "message_id = ANY(%s)" in sql and "FROM messages" in sql,
        f"got sql={sql!r}",
    )
    check(
        "source is passed correctly as the first parameter",
        params[0] == "lucy@coralacademy.com",
    )
    check(
        "the candidate id list is passed as the second parameter",
        params[1] == ["<a@x>"],
    )


def test_falsy_entries_filtered_before_query():
    database.db_pool = FakeSimpleConnectionPool()
    database.db_pool.next_fetchall = []

    database.email_ids_exist(["<a@x>", "", None, "<b@x>"], "support@coralacademy.com")

    sql, params = database.db_pool.execute_calls[0]
    check(
        "empty/None entries are filtered out before the query is built",
        params[1] == ["<a@x>", "<b@x>"],
        f"got {params[1]!r}",
    )


def test_email_exists_itself_unchanged():
    check(
        "database.py still defines email_exists() unchanged (authoritative single-message check, "
        "still available for process_email.py's own guard)",
        "def email_exists(message_id, source):\n    conn = get_connection()\n    cursor = conn.cursor()\n    try:\n        cursor.execute(\n            \"SELECT id FROM messages WHERE message_id = %s AND source = %s LIMIT 1\","
        in _read_source("database.py"),
    )


# ===========================================================================
# PART 2 - control-flow mirror of email_reader.py's 3-stage restructuring.
# ===========================================================================

def _mirror_process_account_loop(
    mail_ids,
    header_fetch_fn,
    email_ids_exist_fn,
    process_email_fn,
    source,
    max_emails_per_run,
):
    """Faithful mirror of the real _process_account()'s Stage 1/2/3 shape:

    Stage 1: per-candidate header fetch + Message-ID parse, in order,
    dropping candidates whose fetch itself fails.
    Stage 2: one batched lookup for all non-empty candidate ids.
    Stage 3: walk candidates in original order, applying MAX_EMAILS_PER_RUN
    and skipping ids present in the batched-lookup result.

    header_fetch_fn(email_id) -> (ok: bool, message_id_or_None: str|None)
    mirrors the real mail.fetch()+parse step: ok=False mirrors a failed/
    malformed header fetch (dropped entirely); message_id_or_None=None or
    "" mirrors a missing Message-ID header (kept as a candidate, never
    treated as existing).
    """
    candidates = []
    for email_id in mail_ids:
        ok, candidate_message_id = header_fetch_fn(email_id)
        if not ok:
            continue
        candidates.append((email_id, candidate_message_id or ""))

    existing = email_ids_exist_fn(
        [cmid for _, cmid in candidates if cmid],
        source,
    )

    processed = []
    processed_count = 0
    hit_limit = False

    for email_id, candidate_message_id in candidates:
        if processed_count >= max_emails_per_run:
            hit_limit = True
            break
        if candidate_message_id and candidate_message_id in existing:
            continue
        process_email_fn(email_id)
        processed.append(email_id)
        processed_count += 1

    return processed, hit_limit


def test_mixed_existing_new_only_new_proceed():
    mail_ids = [b"1", b"2", b"3", b"4"]
    headers = {
        b"1": (True, "<dup1@x>"),
        b"2": (True, "<new1@x>"),
        b"3": (True, "<dup2@x>"),
        b"4": (True, "<new2@x>"),
    }
    lookup_calls = []

    def fake_lookup(ids, source):
        lookup_calls.append((list(ids), source))
        return {"<dup1@x>", "<dup2@x>"}

    processed_ids = []
    processed, hit_limit = _mirror_process_account_loop(
        mail_ids,
        header_fetch_fn=lambda eid: headers[eid],
        email_ids_exist_fn=fake_lookup,
        process_email_fn=lambda eid: processed_ids.append(eid),
        source="support@coralacademy.com",
        max_emails_per_run=15,
    )

    check("mixed candidates: only the 2 non-duplicate ones are processed", processed_ids == [b"2", b"4"])
    check("duplicates (1, 3) are correctly skipped, not processed", b"1" not in processed_ids and b"3" not in processed_ids)


def test_ordering_preserved():
    mail_ids = [b"1", b"2", b"3", b"4", b"5"]
    headers = {eid: (True, f"<{eid.decode()}@x>") for eid in mail_ids}

    processed_ids = []
    processed, hit_limit = _mirror_process_account_loop(
        mail_ids,
        header_fetch_fn=lambda eid: headers[eid],
        email_ids_exist_fn=lambda ids, source: set(),  # nothing pre-exists
        process_email_fn=lambda eid: processed_ids.append(eid),
        source="support@coralacademy.com",
        max_emails_per_run=15,
    )

    check(
        "candidates are processed in the exact original SEARCH-returned order",
        processed_ids == mail_ids,
        f"got {processed_ids!r}",
    )


def test_source_passed_correctly_to_batched_lookup():
    seen_sources = []

    def fake_lookup(ids, source):
        seen_sources.append(source)
        return set()

    _mirror_process_account_loop(
        [b"1"],
        header_fetch_fn=lambda eid: (True, "<a@x>"),
        email_ids_exist_fn=fake_lookup,
        process_email_fn=lambda eid: None,
        source="engineering@coralacademy.com",
        max_emails_per_run=15,
    )

    check(
        "the batched lookup receives this mailbox's own source, unchanged",
        seen_sources == ["engineering@coralacademy.com"],
    )


def test_one_batched_lookup_call_not_n():
    lookup_call_count = [0]

    def counting_lookup(ids, source):
        lookup_call_count[0] += 1
        return set()

    _mirror_process_account_loop(
        [b"1", b"2", b"3", b"4", b"5"],
        header_fetch_fn=lambda eid: (True, f"<{eid.decode()}@x>"),
        email_ids_exist_fn=counting_lookup,
        process_email_fn=lambda eid: None,
        source="support@coralacademy.com",
        max_emails_per_run=15,
    )

    check(
        "the batched lookup is called exactly once per mailbox per run, not once per candidate",
        lookup_call_count[0] == 1,
        f"got {lookup_call_count[0]} calls for 5 candidates",
    )


def test_failed_header_fetch_dropped_entirely():
    """A candidate whose header fetch itself fails must be dropped
    entirely - never enters the batched lookup, never gets processed."""
    mail_ids = [b"1", b"2"]

    def header_fetch(eid):
        if eid == b"1":
            return (False, None)  # simulated fetch failure
        return (True, "<ok@x>")

    lookup_ids_seen = []

    def fake_lookup(ids, source):
        lookup_ids_seen.extend(ids)
        return set()

    processed_ids = []
    _mirror_process_account_loop(
        mail_ids,
        header_fetch_fn=header_fetch,
        email_ids_exist_fn=fake_lookup,
        process_email_fn=lambda eid: processed_ids.append(eid),
        source="support@coralacademy.com",
        max_emails_per_run=15,
    )

    check("a failed header fetch never reaches the batched lookup", "1" not in "".join(lookup_ids_seen))
    check("the failed candidate is never processed", b"1" not in processed_ids)
    check("the other candidate is still processed normally", processed_ids == [b"2"])


def test_missing_message_id_treated_as_new_unchanged():
    """A candidate with a successful header fetch but no Message-ID header
    (empty string) must NOT be checked against the batched lookup and must
    still proceed to full processing - matching the original
    `if candidate_message_id and email_exists(...)` short-circuit."""
    mail_ids = [b"1"]

    lookup_ids_seen = []

    def fake_lookup(ids, source):
        lookup_ids_seen.extend(ids)
        return {"should never match anything"}

    processed_ids = []
    _mirror_process_account_loop(
        mail_ids,
        header_fetch_fn=lambda eid: (True, ""),  # fetch OK, but no Message-ID
        email_ids_exist_fn=fake_lookup,
        process_email_fn=lambda eid: processed_ids.append(eid),
        source="support@coralacademy.com",
        max_emails_per_run=15,
    )

    check("an empty Message-ID is never passed into the batched lookup's id list", lookup_ids_seen == [])
    check("a candidate with no Message-ID still proceeds to full processing, unchanged", processed_ids == [b"1"])


def test_max_emails_per_run_unchanged():
    mail_ids = [f"{i}".encode() for i in range(5)]
    headers = {eid: (True, f"<{eid.decode()}@x>") for eid in mail_ids}

    processed_ids = []
    processed, hit_limit = _mirror_process_account_loop(
        mail_ids,
        header_fetch_fn=lambda eid: headers[eid],
        email_ids_exist_fn=lambda ids, source: set(),
        process_email_fn=lambda eid: processed_ids.append(eid),
        source="support@coralacademy.com",
        max_emails_per_run=3,
    )

    check("MAX_EMAILS_PER_RUN still caps the number of newly-processed messages", len(processed_ids) == 3)
    check("the cap stops at the first 3 candidates, in order", processed_ids == mail_ids[:3])
    check("the limit-reached condition is still signaled", hit_limit is True)


def test_authoritative_duplicate_guard_in_process_email_untouched():
    """process_email.py's own duplicate guard - the authoritative,
    race-safe check - must be completely untouched by this task."""
    process_email_src = _read_source("process_email.py")
    check(
        "process_email.py still opens with its own email_exists() duplicate guard, unchanged",
        'if not message_id or email_exists(message_id, account["source"]):' in process_email_src,
    )
    check(
        "process_email.py still imports email_exists (its own authoritative check, separate from "
        "email_reader.py's new pre-check)",
        "email_exists," in process_email_src or "email_exists\n" in process_email_src,
    )
    check(
        "save_email()'s ON CONFLICT DO NOTHING race-safe dedup guarantee is untouched",
        "ON CONFLICT (message_id, source) DO NOTHING" in _read_source("database.py"),
    )


# ===========================================================================
# PART 3 - source-level checks against the real email_reader.py.
# ===========================================================================

def test_real_email_reader_py_three_stage_structure():
    src = _read_source("email_reader.py")

    check("email_reader.py imports email_ids_exist from database", "from database import email_ids_exist" in src)
    check(
        "email_reader.py no longer imports the per-candidate email_exists "
        "(replaced by the batched helper for this file's own use)",
        "from database import email_exists" not in src,
    )
    check(
        "IMAP SEARCH criteria is unchanged",
        'mail.search(None, "OR", "UNSEEN", "SINCE", since_date)' in src,
    )
    check(
        "Stage 1 header-only fetch is byte-for-byte the same IMAP call as before",
        '"(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"' in src,
    )
    check(
        "Stage 1 collects (email_id, candidate_message_id) pairs into an ordered list",
        "candidates.append((email_id, candidate_message_id))" in src,
    )
    check(
        "Stage 2 performs exactly one batched lookup call",
        "existing_message_ids = email_ids_exist(\n                [cmid for _, cmid in candidates if cmid],\n                account[\"source\"],\n            )" in src,
    )
    check(
        "Stage 3 walks the pre-collected candidates, not mail_ids directly",
        "for email_id, candidate_message_id in candidates:" in src,
    )
    check(
        "Stage 3 still enforces MAX_EMAILS_PER_RUN exactly as before",
        "if processed_count >= MAX_EMAILS_PER_RUN:" in src,
    )
    check(
        "Stage 3 still skips using the same truthiness + membership check shape as the original",
        "if candidate_message_id and candidate_message_id in existing_message_ids:" in src,
    )
    check(
        "the full-body fetch is unchanged",
        '"(BODY.PEEK[])"' in src,
    )
    check(
        "process_email() is still called with the same arguments, including the llm_clients bundle "
        "from the mailbox-concurrency task",
        "process_email(\n                        msg=msg,\n                        account=account,\n                        ingested_via=\"imap_poll\",\n                        llm_clients=llm_clients,\n                    )" in src,
    )
    check(
        "process_email() is called exactly once (one call site, not duplicated)",
        src.count("process_email(\n                        msg=msg,") == 1,
    )


def test_mailbox_concurrency_and_client_isolation_untouched():
    src = _read_source("email_reader.py")
    check(
        "ThreadPoolExecutor(max_workers=3) for mailbox concurrency is unchanged",
        "with ThreadPoolExecutor(max_workers=3) as executor:" in src,
    )
    check(
        "the per-worker 5-client bundle construction is unchanged",
        '"classifier": _new_llm_client(),\n        "reranker": _new_llm_client(),\n        "generator": _new_llm_client(),\n        "similar_embedding": new_embedding_client(),\n        "knowledge_embedding": new_embedding_client(),' in src,
    )
    check(
        "the bundle is still closed exactly once in the outer finally",
        'close_embedding_client(llm_clients["classifier"])\n        close_embedding_client(llm_clients["reranker"])\n        close_embedding_client(llm_clients["generator"])\n        close_embedding_client(llm_clients["similar_embedding"])\n        close_embedding_client(llm_clients["knowledge_embedding"])' in src,
    )


def test_no_out_of_scope_changes():
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    )
    changed = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    check("scheduler.py was not modified", "scheduler.py" not in changed)
    check("main.py was not modified", "main.py" not in changed)
    check("process_email.py was not modified", "process_email.py" not in changed)
    check("ai_classifier.py was not modified by this task", "ai_classifier.py" not in changed)
    check("prompt_builder.py was not modified", "prompt_builder.py" not in changed)
    non_test_files = {f for f in changed if not f.startswith("test_")}
    check(
        "production changes are scoped to exactly database.py and email_reader.py "
        "(test-file updates, e.g. fixing a stale pin elsewhere, are expected and excluded here)",
        non_test_files == {"database.py", "email_reader.py"},
        f"got {non_test_files!r} (full changed set: {changed!r})",
    )


def main():
    test_empty_candidate_list_no_db_query_empty_result()
    test_all_candidates_already_exist()
    test_none_exist()
    test_mixed_existing_and_new()
    test_one_batched_query_not_n_calls()
    test_source_and_query_shape()
    test_falsy_entries_filtered_before_query()
    test_email_exists_itself_unchanged()

    test_mixed_existing_new_only_new_proceed()
    test_ordering_preserved()
    test_source_passed_correctly_to_batched_lookup()
    test_one_batched_lookup_call_not_n()
    test_failed_header_fetch_dropped_entirely()
    test_missing_message_id_treated_as_new_unchanged()
    test_max_emails_per_run_unchanged()
    test_authoritative_duplicate_guard_in_process_email_untouched()

    test_real_email_reader_py_three_stage_structure()
    test_mailbox_concurrency_and_client_isolation_untouched()
    test_no_out_of_scope_changes()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
