"""Focused tests for the final pre-freeze contact-form background exception
guard: _process_contact_form_enquiry() (the function submit_enquiry()'s
background task actually invokes) previously had no top-level exception
guard - an unexpected exception from its ThreadPoolExecutor block or
anything after it would propagate as an unlogged stderr traceback, leaving
that contact-form row stuck at its placeholder state with no durable
record of why.

Fixed by splitting the original function into:
- _process_contact_form_enquiry_impl() - the real logic, moved verbatim,
  byte-for-byte unchanged (same review/generation logic, same database
  writes, same cleanup/finally behavior).
- _process_contact_form_enquiry() - a thin wrapper, now what the
  background task actually calls, that invokes _impl() inside a
  try/except and logs any failure via this app's existing logger.py
  logger (logger.exception(), never print()) with safe, non-sensitive
  context only (row_id - never subject/body/customer_name).

TESTING APPROACH: main.py cannot be imported in this sandbox (needs
fastapi + apscheduler, starts real scheduler.py background jobs at import
time - same documented limitation as every other main.py test this
session). Behavioral confidence comes from a mirror of the new wrapper
(tested directly against fake implementations/loggers below), cross-
checked against the real source for exact correspondence - the same
"byte-for-byte mirror kept in sync by inspection" technique test_review_reasons.py
and test_rerank_empty_guard_main.py already established for this exact file.

Run with: python3 test_contact_form_exception_guard.py
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
# Mirror of the new wrapper - byte-for-byte equivalent to:
#
#     def _process_contact_form_enquiry(row_id, subject, body, customer_name):
#         try:
#             _process_contact_form_enquiry_impl(row_id, subject, body, customer_name)
#         except Exception:
#             logger.exception(f"Contact-form background processing failed for row_id={row_id}")
#
# A FakeLogger stands in for logger.py's real logger (same lightweight-fake
# philosophy already used elsewhere this session, e.g.
# test_reasoning_token_observability.py's own FakeLogger) - real logging
# plumbing isn't needed just to assert on one captured message.
# ---------------------------------------------------------------------------

class FakeLogger:
    def __init__(self):
        self.exceptions = []

    def exception(self, msg, *a, **kw):
        self.exceptions.append(str(msg))


def _wrapper(row_id, subject, body, customer_name, impl_fn, logger):
    try:
        impl_fn(row_id, subject, body, customer_name)
    except Exception:
        logger.exception(f"Contact-form background processing failed for row_id={row_id}")


# ---------------------------------------------------------------------------
# Successful background processing remains unchanged.
# ---------------------------------------------------------------------------

def test_successful_processing_calls_impl_once_with_the_same_arguments():
    calls = []

    def fake_impl(row_id, subject, body, customer_name):
        calls.append((row_id, subject, body, customer_name))

    fake_logger = FakeLogger()
    _wrapper(42, "Help with enrollment", "My child wants to join...", "Pat Smith", fake_impl, fake_logger)

    check(
        "the real implementation is called exactly once, with the same arguments, unchanged",
        calls == [(42, "Help with enrollment", "My child wants to join...", "Pat Smith")],
    )
    check("nothing is logged on success", fake_logger.exceptions == [])


# ---------------------------------------------------------------------------
# Unexpected exception is caught/logged; does not propagate.
# ---------------------------------------------------------------------------

def test_unexpected_exception_is_caught_and_logged():
    def failing_impl(row_id, subject, body, customer_name):
        raise RuntimeError("knowledge base search timed out")

    fake_logger = FakeLogger()

    try:
        _wrapper(99, "s", "b", "c", failing_impl, fake_logger)
        raised = False
    except Exception:
        raised = True

    check("the wrapper itself never raises - the background task cannot crash the application", raised is False)
    check("exactly one exception was logged", len(fake_logger.exceptions) == 1)
    check(
        "the logged message includes the row_id for useful debugging context",
        "row_id=99" in fake_logger.exceptions[0],
    )


def test_different_exception_types_are_all_caught():
    for exc in [ValueError("bad value"), KeyError("missing"), ConnectionError("network down")]:
        def failing_impl(row_id, subject, body, customer_name, _exc=exc):
            raise _exc

        fake_logger = FakeLogger()
        try:
            _wrapper(1, "s", "b", "c", failing_impl, fake_logger)
            raised = False
        except Exception:
            raised = True

        check(f"{type(exc).__name__} is caught, not propagated", raised is False)
        check(f"{type(exc).__name__} is logged", len(fake_logger.exceptions) == 1)


# ---------------------------------------------------------------------------
# No sensitive email body/subject/customer name is ever logged.
# ---------------------------------------------------------------------------

def test_no_sensitive_content_is_ever_logged():
    sensitive_subject = "My daughter Jane Doe has a rare medical condition"
    sensitive_body = "Please call me at 555-1234, her diagnosis is..."
    sensitive_name = "Jane Doe"

    def failing_impl(row_id, subject, body, customer_name):
        raise RuntimeError("boom")

    fake_logger = FakeLogger()
    _wrapper(7, sensitive_subject, sensitive_body, sensitive_name, failing_impl, fake_logger)

    logged_text = " ".join(fake_logger.exceptions)
    check("the customer's subject is never logged", sensitive_subject not in logged_text)
    check("the customer's body is never logged", sensitive_body not in logged_text)
    check("the customer's name is never logged", sensitive_name not in logged_text)
    check("only row_id appears as identifying context", "row_id=7" in logged_text)


# ---------------------------------------------------------------------------
# Cross-check: the real main.py matches this mirror exactly.
# ---------------------------------------------------------------------------

def test_real_main_py_has_the_wrapper_and_impl_split():
    src = _read_source("main.py")
    check(
        "the thin wrapper exists with the original function's exact name/signature "
        "(so the existing background_tasks.add_task(...) call site needs no change)",
        "def _process_contact_form_enquiry(row_id, subject, body, customer_name):" in src,
    )
    check(
        "the real implementation was renamed, not duplicated",
        "def _process_contact_form_enquiry_impl(row_id, subject, body, customer_name):" in src,
    )
    check(
        "the wrapper calls the impl function inside a try/except",
        "try:\n        _process_contact_form_enquiry_impl(row_id, subject, body, customer_name)\n    except Exception:" in src,
    )
    check(
        "a failure is logged via the existing logger.py logger (logger.exception), not print()",
        'logger.exception(f"Contact-form background processing failed for row_id={row_id}")' in src,
    )


def test_background_task_call_site_unchanged():
    src = _read_source("main.py")
    check(
        "submit_enquiry()'s background_tasks.add_task(...) call site is unchanged - "
        "still calls _process_contact_form_enquiry (now the guarded wrapper) with the same arguments",
        "_process_contact_form_enquiry, row_id, subject, body, data.get(\"name\")" in src,
    )


def test_impl_body_is_unchanged_database_writes_and_cleanup_preserved():
    src = _read_source("main.py")
    impl_start = src.index("def _process_contact_form_enquiry_impl(row_id, subject, body, customer_name):")
    impl_end = src.index('@app.post("/submit-enquiry")')
    impl_body = src[impl_start:impl_end]

    check(
        "the embedding-client try/finally cleanup is unchanged",
        "try:\n        with ThreadPoolExecutor(max_workers=3) as executor:" in impl_body
        and "finally:\n        close_embedding_client(similar_client)\n        close_embedding_client(knowledge_client)" in impl_body,
    )
    check(
        "the review_reasons combination logic is unchanged",
        'review_reasons.append("classifier")' in impl_body
        and 'review_reasons.append("retrieval_error")' in impl_body
        and 'review_reasons.append("safety_block")' in impl_body
        and 'review_reasons.append("generation_error")' in impl_body,
    )
    check(
        "the final database write (update_contact_form_ai_fields) is unchanged",
        "update_contact_form_ai_fields(\n        row_id=row_id," in impl_body,
    )
    check(
        "no retry logic was introduced inside the implementation",
        "max_retries" not in impl_body and "for attempt in range" not in impl_body,
    )


def test_no_sensitive_content_in_the_real_wrapper_source():
    """Static confirmation that the real wrapper's log line can never
    contain subject/body/customer_name - it only ever interpolates
    row_id."""
    src = _read_source("main.py")
    wrapper_start = src.index("def _process_contact_form_enquiry(row_id, subject, body, customer_name):")
    wrapper_end = src.index("def _process_contact_form_enquiry_impl(")
    wrapper_body = src[wrapper_start:wrapper_end]

    check(
        "the wrapper's only logger call interpolates row_id only, not subject/body/customer_name",
        "logger.exception(f\"Contact-form background processing failed for row_id={row_id}\")" in wrapper_body,
    )
    check(
        "subject/body/customer_name are never referenced inside the wrapper itself "
        "(only passed through to the impl function, never logged)",
        "{subject}" not in wrapper_body and "{body}" not in wrapper_body and "{customer_name}" not in wrapper_body,
    )


def main():
    tests = [
        test_successful_processing_calls_impl_once_with_the_same_arguments,
        test_unexpected_exception_is_caught_and_logged,
        test_different_exception_types_are_all_caught,
        test_no_sensitive_content_is_ever_logged,
        test_real_main_py_has_the_wrapper_and_impl_split,
        test_background_task_call_site_unchanged,
        test_impl_body_is_unchanged_database_writes_and_cleanup_preserved,
        test_no_sensitive_content_in_the_real_wrapper_source,
    ]
    for t in tests:
        t()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    print("\nAll tests passed.")


if __name__ == "__main__":
    main()
