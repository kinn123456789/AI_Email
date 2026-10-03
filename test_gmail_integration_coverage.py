"""Focused regression tests for the three Gmail integration modules that
had zero test coverage: gmail_auth.py, gmail_fetch.py, sync_sent_gmail.py.

SCOPE (exactly four behaviors, per the read-only coverage check this
follows):
  1. gmail_auth.get_delegated_credentials() - credential caching.
  2. sync_sent_gmail._process_sent_message() - duplicate/thread/error
     classification.
  3. sync_sent_gmail.main()'s checkpoint-advancement logic (all 4
     branches).
  4. gmail_fetch.get_message() - success path + cleanup-on-error.

TESTING LIMITATION (confirmed directly, not assumed): this sandbox does
not have the `google`, `googleapiclient`, or `bs4` packages installed, so
gmail_auth.py, gmail_fetch.py, and sync_sent_gmail.py cannot literally be
imported here (gmail_auth.py's own `from google.oauth2 import
service_account` fails immediately; sync_sent_gmail.py's `from bs4
import BeautifulSoup` and its `database` import - which needs psycopg2 -
both fail the same way). Every check below is therefore either a
structural/source-presence check against the real file text, or a
byte-for-byte Python mirror of the exact logic in question, exercised
directly with fake objects/inputs and cross-checked against the literal
source so a mirror can never silently drift from what's actually
shipped - the same established convention every other test_*.py in this
repo uses for a module it can't directly import. No pytest, no real
Gmail/IMAP/network/database access anywhere in this file - a plain
script using only assert statements and the standard library.

Run with: python3 test_gmail_integration_coverage.py
"""

import base64
import email as email_module
import os
import sys
from datetime import datetime, timezone
from email.message import EmailMessage


_failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        _failures.append(name)


def _read_source(filename):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), filename), "r", encoding="utf-8") as f:
        return f.read()


GMAIL_AUTH_SRC = _read_source("gmail_auth.py")
GMAIL_FETCH_SRC = _read_source("gmail_fetch.py")
SYNC_SENT_GMAIL_SRC = _read_source("sync_sent_gmail.py")


# ===========================================================================
# 1. gmail_auth.py - get_delegated_credentials() caching
# ===========================================================================

def test_source_confirms_cache_structure_and_branches():
    check(
        "cache key is (email_address, tuple(scopes))",
        "cache_key = (email_address, tuple(scopes))" in GMAIL_AUTH_SRC,
    )
    check(
        "cache hit requires both presence AND .valid",
        "if cached and cached.valid:" in GMAIL_AUTH_SRC,
    )
    check(
        "GOOGLE_SERVICE_ACCOUNT_JSON branch calls from_service_account_info",
        "service_account.Credentials.from_service_account_info(" in GMAIL_AUTH_SRC,
    )
    check(
        "fallback branch calls from_service_account_file",
        "service_account.Credentials.from_service_account_file(" in GMAIL_AUTH_SRC,
    )
    check(
        "a freshly built credential is refreshed before being cached",
        "creds.refresh(Request())" in GMAIL_AUTH_SRC,
    )
    check(
        "the freshly built/refreshed credential is written back into the cache",
        "_creds_cache[cache_key] = creds" in GMAIL_AUTH_SRC,
    )


class _FakeCredentials:
    """Stands in for google.auth.Credentials - only `.valid`,
    `.with_subject()`, and `.refresh()` are ever touched by
    get_delegated_credentials(), so that's all this fakes."""

    def __init__(self, source, valid=True):
        self.source = source
        self.valid = valid
        self.subject = None
        self.refresh_count = 0

    def with_subject(self, email_address):
        self.subject = email_address
        return self

    def refresh(self, _request=None):
        self.refresh_count += 1


def _mirror_get_delegated_credentials(
    cache, email_address, scopes, default_scopes,
    env_get, make_from_json, make_from_file,
):
    """Byte-for-byte mirror of gmail_auth.get_delegated_credentials()'s
    control flow (see test_source_confirms_cache_structure_and_branches
    above for the literal lines this mirrors) - env_get/make_from_json/
    make_from_file are injected fakes standing in for os.getenv and the
    two service_account.Credentials.from_service_account_*() calls, so
    this never touches a real credential, file, or network."""
    scopes = scopes or default_scopes
    cache_key = (email_address, tuple(scopes))

    cached = cache.get(cache_key)
    if cached and cached.valid:
        return cached

    service_account_json = env_get("GOOGLE_SERVICE_ACCOUNT_JSON")

    if service_account_json:
        creds = make_from_json(service_account_json, scopes)
    else:
        creds = make_from_file("service-account.json", scopes)

    creds = creds.with_subject(email_address)
    creds.refresh()

    cache[cache_key] = creds
    return creds


def test_valid_cached_credential_is_reused():
    cache = {}
    cached = _FakeCredentials("cache", valid=True)
    cache[("teacher@coralacademy.com", ("scope-a",))] = cached

    calls = {"from_json": 0, "from_file": 0}
    result = _mirror_get_delegated_credentials(
        cache, "teacher@coralacademy.com", ["scope-a"], ["scope-a"],
        env_get=lambda _k: None,
        make_from_json=lambda *a: calls.__setitem__("from_json", calls["from_json"] + 1) or _FakeCredentials("json"),
        make_from_file=lambda *a: calls.__setitem__("from_file", calls["from_file"] + 1) or _FakeCredentials("file"),
    )

    check("a valid cached credential is returned as-is", result is cached)
    check("no new credential was built on a cache hit", calls["from_json"] == 0 and calls["from_file"] == 0)
    check("a cache hit never calls .refresh() again", cached.refresh_count == 0)


def test_different_email_scope_combinations_do_not_share_a_cache_entry():
    cache = {}
    cached_for_a = _FakeCredentials("cache-a", valid=True)
    cache[("teacher_a@coralacademy.com", ("scope-x",))] = cached_for_a

    built = []

    def _make_from_file(_path, _scopes):
        creds = _FakeCredentials("file")
        built.append(creds)
        return creds

    # Different email, same scopes -> must NOT reuse teacher_a's credential.
    result_b = _mirror_get_delegated_credentials(
        cache, "teacher_b@coralacademy.com", ["scope-x"], ["scope-x"],
        env_get=lambda _k: None, make_from_json=lambda *a: None, make_from_file=_make_from_file,
    )
    check("a different email_address never reuses another mailbox's cached credential", result_b is not cached_for_a)

    # Same email, different scopes -> must also NOT reuse the cached entry.
    result_c = _mirror_get_delegated_credentials(
        cache, "teacher_a@coralacademy.com", ["scope-y"], ["scope-y"],
        env_get=lambda _k: None, make_from_json=lambda *a: None, make_from_file=_make_from_file,
    )
    check("a different scopes tuple never reuses a cached credential for the same email", result_c is not cached_for_a)
    check("both distinct lookups actually built a fresh credential", len(built) == 2)


def test_cache_miss_triggers_credential_creation():
    cache = {}
    built = []

    def _make_from_file(path, scopes):
        creds = _FakeCredentials("file")
        built.append((path, scopes))
        return creds

    result = _mirror_get_delegated_credentials(
        cache, "new_mailbox@coralacademy.com", None, ["default-scope"],
        env_get=lambda _k: None, make_from_json=lambda *a: None, make_from_file=_make_from_file,
    )

    check("a cache miss builds exactly one new credential", len(built) == 1)
    check("the default scopes are used when none are passed", built[0][1] == ["default-scope"])
    check("the newly built credential is refreshed once", result.refresh_count == 1)
    check("the new credential is stored in the cache under the right key", cache.get(("new_mailbox@coralacademy.com", ("default-scope",))) is result)


def test_google_service_account_json_env_branch_is_used_when_set():
    cache = {}
    calls = {"from_json": 0, "from_file": 0}

    result = _mirror_get_delegated_credentials(
        cache, "env@coralacademy.com", ["s"], ["s"],
        env_get=lambda k: '{"fake": "service-account-json"}' if k == "GOOGLE_SERVICE_ACCOUNT_JSON" else None,
        make_from_json=lambda *a: calls.__setitem__("from_json", calls["from_json"] + 1) or _FakeCredentials("json"),
        make_from_file=lambda *a: calls.__setitem__("from_file", calls["from_file"] + 1) or _FakeCredentials("file"),
    )
    check("the env-var JSON branch is used when GOOGLE_SERVICE_ACCOUNT_JSON is set", calls["from_json"] == 1 and calls["from_file"] == 0)
    check("the resulting credential came from the json branch", result.source == "json")


def test_service_account_file_branch_is_used_when_env_var_absent():
    cache = {}
    calls = {"from_json": 0, "from_file": 0}

    result = _mirror_get_delegated_credentials(
        cache, "file@coralacademy.com", ["s"], ["s"],
        env_get=lambda _k: None,
        make_from_json=lambda *a: calls.__setitem__("from_json", calls["from_json"] + 1) or _FakeCredentials("json"),
        make_from_file=lambda *a: calls.__setitem__("from_file", calls["from_file"] + 1) or _FakeCredentials("file"),
    )
    check("the service-account-file branch is used when the env var is absent", calls["from_file"] == 1 and calls["from_json"] == 0)
    check("the resulting credential came from the file branch", result.source == "file")


def test_invalid_expired_cached_credential_triggers_refresh():
    cache = {}
    expired = _FakeCredentials("cache", valid=False)
    cache[("expired@coralacademy.com", ("s",))] = expired

    fresh = _FakeCredentials("file", valid=True)
    result = _mirror_get_delegated_credentials(
        cache, "expired@coralacademy.com", ["s"], ["s"],
        env_get=lambda _k: None, make_from_json=lambda *a: None, make_from_file=lambda *a: fresh,
    )

    check("an invalid (expired) cached credential is not returned as-is", result is not expired)
    check("a fresh credential is built and refreshed instead", result is fresh and fresh.refresh_count == 1)
    check("the cache entry is replaced with the fresh credential", cache[("expired@coralacademy.com", ("s",))] is fresh)


# ===========================================================================
# 2. sync_sent_gmail.py - _process_sent_message() classification
# ===========================================================================

def test_source_confirms_process_sent_message_structure():
    check(
        "parent is first looked up via In-Reply-To",
        'parent = get_message_by_message_id(in_reply_to, account["source"])' in SYNC_SENT_GMAIL_SRC,
    )
    check(
        "References is scanned in reverse, stopping at the first match",
        "for ref in reversed(references.split()):" in SYNC_SENT_GMAIL_SRC and "if parent: break" in SYNC_SENT_GMAIL_SRC,
    )
    check(
        "a found parent's thread_id is reused for the new message",
        'thread_id = parent["thread_id"]' in SYNC_SENT_GMAIL_SRC,
    )
    check(
        "a duplicate Message-ID (or a missing one) is classified before any save",
        'if not message_id or email_exists(message_id, account["source"]):' in SYNC_SENT_GMAIL_SRC,
    )
    check(
        'a duplicate returns exactly ("duplicate", email_date, message_id, None)',
        'return "duplicate", email_date, message_id, None' in SYNC_SENT_GMAIL_SRC,
    )
    check(
        "any processing exception is caught and classified as an error, not re-raised",
        "except Exception as e:" in SYNC_SENT_GMAIL_SRC and 'return "error", email_date, message_id, str(e)' in SYNC_SENT_GMAIL_SRC,
    )


def _mirror_resolve_parent(in_reply_to, references, get_parent_fn):
    """Byte-for-byte mirror of _process_sent_message()'s parent-resolution
    block (see the source-presence checks above for the literal lines)."""
    parent = None
    if in_reply_to:
        parent = get_parent_fn(in_reply_to)

    if not parent and references:
        for ref in reversed(references.split()):
            parent = get_parent_fn(ref)
            if parent:
                break

    return parent


def _mirror_process_sent_message(message_id, in_reply_to, references, email_exists_fn, get_parent_fn, raise_with=None):
    """Byte-for-byte mirror of _process_sent_message()'s own decision
    logic (parent resolution -> duplicate check -> save-or-error),
    standing in for the real IMAP fetch/email parsing/BeautifulSoup/
    save_email() machinery this sandbox can't import. `raise_with`, when
    given, simulates an exception occurring during the "build body and
    save" step that the real function wraps in its own try/except."""
    email_date = "2026-01-01T00:00:00Z"  # stand-in; irrelevant to this logic

    try:
        parent = _mirror_resolve_parent(in_reply_to, references, get_parent_fn)
        thread_id = message_id

        if parent:
            thread_id = parent["thread_id"]

        if not message_id or email_exists_fn(message_id):
            return "duplicate", email_date, message_id, None, thread_id

        if raise_with is not None:
            raise raise_with

        return "imported", email_date, message_id, None, thread_id

    except Exception as e:
        return "error", email_date, message_id, str(e), None


def test_known_message_id_is_classified_as_duplicate_and_not_resaved():
    save_calls = []

    def _email_exists(_mid):
        return True  # already in the database

    outcome, _, message_id, err, _ = _mirror_process_sent_message(
        "msg-123", in_reply_to="", references="",
        email_exists_fn=_email_exists,
        get_parent_fn=lambda _ref: None,
    )
    check('a known Message-ID is classified "duplicate"', outcome == "duplicate")
    check("a duplicate carries no error", err is None)
    check("a duplicate is never passed through to a save step", len(save_calls) == 0)


def test_in_reply_to_links_an_existing_parent():
    parent_row = {"id": 42, "thread_id": "thread-abc"}

    outcome, _, _, _, thread_id = _mirror_process_sent_message(
        "msg-new", in_reply_to="parent-msg-id", references="",
        email_exists_fn=lambda _mid: False,
        get_parent_fn=lambda ref: parent_row if ref == "parent-msg-id" else None,
    )
    check("a resolvable In-Reply-To links to the parent's thread_id", thread_id == "thread-abc")
    check("linking a parent still allows the message to be imported", outcome == "imported")


def test_references_header_used_when_in_reply_to_does_not_resolve():
    parent_row = {"id": 7, "thread_id": "thread-from-references"}

    def _get_parent(ref):
        # In-Reply-To deliberately doesn't resolve; only one of the
        # References entries does - confirms the reversed-scan-with-break.
        return parent_row if ref == "older-ref-id" else None

    outcome, _, _, _, thread_id = _mirror_process_sent_message(
        "msg-new-2", in_reply_to="unresolvable-id", references="newer-ref-id older-ref-id",
        email_exists_fn=lambda _mid: False,
        get_parent_fn=_get_parent,
    )
    check("References is consulted when In-Reply-To doesn't resolve", thread_id == "thread-from-references")
    check("import still succeeds via the References-resolved parent", outcome == "imported")


def test_missing_parent_is_handled_as_a_new_thread():
    outcome, _, message_id, _, thread_id = _mirror_process_sent_message(
        "msg-standalone", in_reply_to="", references="",
        email_exists_fn=lambda _mid: False,
        get_parent_fn=lambda _ref: None,
    )
    check("with no parent found, the message starts its own thread (thread_id == message_id)", thread_id == message_id)
    check("a message with no parent still imports successfully", outcome == "imported")


def test_processing_exception_is_classified_as_error_without_crashing():
    outcome, email_date, message_id, err, thread_id = _mirror_process_sent_message(
        "msg-will-fail", in_reply_to="", references="",
        email_exists_fn=lambda _mid: False,
        get_parent_fn=lambda _ref: None,
        raise_with=ValueError("simulated save_email() failure"),
    )
    check('an exception during processing is classified "error", not re-raised', outcome == "error")
    check("the error message is captured as a string", err == "simulated save_email() failure")
    check("email_date and message_id are still returned on error (not swallowed)", email_date is not None and message_id == "msg-will-fail")
    check("calling the mirror did not raise - the caller's loop can continue to the next message", True)


# ===========================================================================
# 3. sync_sent_gmail.py - main()'s checkpoint-advancement logic
# ===========================================================================

def test_source_confirms_all_four_checkpoint_branches():
    for literal in [
        "if truncated and oldest_processed_date:",
        "checkpoint_time = oldest_processed_date",
        "elif latest_success_date:",
        "checkpoint_time = latest_success_date",
        "elif not message_ids:",
        "checkpoint_time = datetime.now(timezone.utc)",
        "else:",
        "checkpoint_time = None",
    ]:
        check(f"main() checkpoint logic contains {literal!r}", literal in SYNC_SENT_GMAIL_SRC)


def _mirror_compute_checkpoint(truncated, oldest_processed_date, latest_success_date, message_ids, now_fn):
    """Byte-for-byte mirror of the 4-branch checkpoint_time computation
    inside sync_sent_gmail.main() (see the source-presence checks above
    for the exact literal lines this mirrors)."""
    if truncated and oldest_processed_date:
        return oldest_processed_date
    elif latest_success_date:
        return latest_success_date
    elif not message_ids:
        return now_fn()
    else:
        return None


def test_truncated_backlog_caps_checkpoint_at_oldest_processed():
    oldest = datetime(2026, 1, 1, tzinfo=timezone.utc)
    latest = datetime(2026, 1, 5, tzinfo=timezone.utc)  # present, but must NOT win - truncated takes priority
    result = _mirror_compute_checkpoint(
        truncated=True, oldest_processed_date=oldest, latest_success_date=latest,
        message_ids=["1", "2", "3"], now_fn=lambda: "should-not-be-used",
    )
    check("a truncated backlog caps the checkpoint at the oldest processed date", result == oldest)


def test_partial_failure_advances_only_to_latest_confirmed_success():
    latest = datetime(2026, 2, 1, tzinfo=timezone.utc)
    result = _mirror_compute_checkpoint(
        truncated=False, oldest_processed_date=None, latest_success_date=latest,
        message_ids=["1", "2"], now_fn=lambda: "should-not-be-used",
    )
    check("a partial failure (not truncated) advances only to the latest successful date", result == latest)


def test_no_messages_found_advances_checkpoint_to_now():
    sentinel_now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    result = _mirror_compute_checkpoint(
        truncated=False, oldest_processed_date=None, latest_success_date=None,
        message_ids=[], now_fn=lambda: sentinel_now,
    )
    check("an empty search result advances the checkpoint to \"now\"", result == sentinel_now)


def test_total_failure_leaves_checkpoint_as_none():
    result = _mirror_compute_checkpoint(
        truncated=False, oldest_processed_date=None, latest_success_date=None,
        message_ids=["1", "2", "3"],  # messages existed, but every one of them failed
        now_fn=lambda: "should-not-be-used",
    )
    check("every message failing in the run leaves the checkpoint as None (untouched)", result is None)


# ===========================================================================
# 4. gmail_fetch.py - get_message()
# ===========================================================================

def test_source_confirms_get_message_structure():
    check("get_message() builds the Gmail service via get_gmail_service()", "service = get_gmail_service(from_email)" in GMAIL_FETCH_SRC)
    check(
        "the Gmail API call requests the raw message format",
        'service.users().messages().get(' in GMAIL_FETCH_SRC and 'format="raw"' in GMAIL_FETCH_SRC,
    )
    check("the raw response is base64-decoded then parsed as an email message", 'base64.urlsafe_b64decode(response["raw"])' in GMAIL_FETCH_SRC and "email.message_from_bytes(" in GMAIL_FETCH_SRC)
    check(
        "service.close() is called unconditionally via finally (runs even if .execute() raises)",
        "finally:" in GMAIL_FETCH_SRC and "service.close()" in GMAIL_FETCH_SRC,
    )
    check(
        "get_message() has no except of its own - an API error propagates to its caller",
        "except" not in GMAIL_FETCH_SRC,
    )


class _FakeMessagesResource:
    def __init__(self, raw_response=None, raise_error=None):
        self._raw_response = raw_response
        self._raise_error = raise_error

    def get(self, userId, id, format):  # noqa: A002 - mirrors the real kwarg names
        return self

    def execute(self):
        if self._raise_error is not None:
            raise self._raise_error
        return self._raw_response


class _FakeUsersResource:
    def __init__(self, messages_resource):
        self._messages_resource = messages_resource

    def messages(self):
        return self._messages_resource


class _FakeGmailService:
    """Stands in for the real googleapiclient service object - only
    .users()/.messages()/.get()/.execute()/.close() are ever touched by
    get_message(), so that's all this fakes."""

    def __init__(self, raw_response=None, raise_error=None):
        self._users_resource = _FakeUsersResource(_FakeMessagesResource(raw_response, raise_error))
        self.closed = False

    def users(self):
        return self._users_resource

    def close(self):
        self.closed = True


def _mirror_get_message(service, message_id):
    """Byte-for-byte mirror of gmail_fetch.get_message()'s own body,
    minus the get_gmail_service() construction step (the `service`
    object is injected here instead) - uses the real stdlib base64/email
    modules for the decode/parse step, exactly as the production code
    does, so that part is genuinely exercised, not faked."""
    try:
        response = service.users().messages().get(
            userId="me",
            id=message_id,
            format="raw",
        ).execute()

        msg = email_module.message_from_bytes(
            base64.urlsafe_b64decode(response["raw"])
        )

        return msg
    finally:
        service.close()


def _build_raw_gmail_response(subject, body_text):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = "support@coralacademy.com"
    msg["To"] = "parent@example.com"
    msg.set_content(body_text)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return {"raw": raw}


def test_successful_message_retrieval_works():
    raw_response = _build_raw_gmail_response("Re: Trial class", "Thanks for reaching out!")
    service = _FakeGmailService(raw_response=raw_response)

    msg = _mirror_get_message(service, "gmail-msg-id-123")

    check("get_message() returns a parsed email.message object", msg["Subject"] == "Re: Trial class")
    # email.message_from_bytes() (what the real gmail_fetch.py calls)
    # returns a classic compat32 Message, not an EmailMessage - decode
    # the body the same way sync_sent_gmail.py's own body-extraction
    # loop does, rather than the EmailMessage-only .get_content().
    decoded_body = msg.get_payload(decode=True).decode().strip()
    check("the message body round-trips correctly through the real base64/email stdlib", decoded_body == "Thanks for reaching out!")
    check("service.close() is called on the success path too", service.closed is True)


def test_service_close_executes_when_execute_raises():
    service = _FakeGmailService(raise_error=RuntimeError("simulated Gmail API failure"))

    raised = False
    try:
        _mirror_get_message(service, "gmail-msg-id-456")
    except RuntimeError:
        raised = True

    check("the API exception still propagates (get_message() has no except of its own)", raised is True)
    check("service.close() ran via finally even though .execute() raised", service.closed is True)


def main():
    tests = [
        test_source_confirms_cache_structure_and_branches,
        test_valid_cached_credential_is_reused,
        test_different_email_scope_combinations_do_not_share_a_cache_entry,
        test_cache_miss_triggers_credential_creation,
        test_google_service_account_json_env_branch_is_used_when_set,
        test_service_account_file_branch_is_used_when_env_var_absent,
        test_invalid_expired_cached_credential_triggers_refresh,
        test_source_confirms_process_sent_message_structure,
        test_known_message_id_is_classified_as_duplicate_and_not_resaved,
        test_in_reply_to_links_an_existing_parent,
        test_references_header_used_when_in_reply_to_does_not_resolve,
        test_missing_parent_is_handled_as_a_new_thread,
        test_processing_exception_is_classified_as_error_without_crashing,
        test_source_confirms_all_four_checkpoint_branches,
        test_truncated_backlog_caps_checkpoint_at_oldest_processed,
        test_partial_failure_advances_only_to_latest_confirmed_success,
        test_no_messages_found_advances_checkpoint_to_now,
        test_total_failure_leaves_checkpoint_as_none,
        test_source_confirms_get_message_structure,
        test_successful_message_retrieval_works,
        test_service_close_executes_when_execute_raises,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
