"""Focused tests for coral_class_catalog.py - the Phase 1 read-only Coral
class catalog client. No real HTTP requests are made anywhere in this
file; the `requests` library is faked exactly like `openai`/`psycopg2` are
faked elsewhere in this repo's test suite, so fetch_catalog()/
get_cached_catalog() run their real code against controlled fake HTTP
responses.

Matches this repo's existing test_*.py convention: a plain script using
only assert statements, no pytest, stdlib only.

Run with: python3 test_coral_class_catalog.py
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
# Fake `requests` module - no real network access anywhere in this file.
# ---------------------------------------------------------------------------

def _install_fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, raise_json_error=False):
        self.status_code = status_code
        self._json_data = json_data
        self._raise_json_error = raise_json_error

    def json(self):
        if self._raise_json_error:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._json_data


class _FakeRequestException(Exception):
    pass


class _FakeTimeout(_FakeRequestException):
    pass


class _FakeConnectionError(_FakeRequestException):
    pass


class _FakeRequestsState:
    def __init__(self):
        self.call_count = 0
        self.calls = []
        self._next_response = None
        self._next_exception = None

    def set_response(self, response):
        self._next_response = response
        self._next_exception = None

    def set_exception(self, exc):
        self._next_exception = exc
        self._next_response = None

    def get(self, url, timeout=None):
        self.call_count += 1
        self.calls.append({"url": url, "timeout": timeout})
        if self._next_exception is not None:
            raise self._next_exception
        return self._next_response


_fake_requests_state = _FakeRequestsState()

_install_fake_module(
    "requests",
    get=_fake_requests_state.get,
    Timeout=_FakeTimeout,
    RequestException=_FakeRequestException,
    ConnectionError=_FakeConnectionError,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coral_class_catalog as ccc  # noqa: E402


def _reset():
    """Fresh fake-requests state and a fresh module-level cache before
    every test, so tests don't leak state into each other."""
    global _fake_requests_state
    _fake_requests_state = _FakeRequestsState()
    ccc._cache["result"] = None
    ccc._cache["fetched_at"] = None
    # Re-point the fake requests.get at the new state object.
    sys.modules["requests"].get = _fake_requests_state.get


_VALID_PAYLOAD = {
    "response": {
        "classes": [
            {
                "id": "aaa-111",
                "title": "Astronomy 101: Learn About Space",
                "subject": "science",
                "url_slug": "astro101",
                "pricing": {"regular": {"amount": 2500, "currency": "usd", "unit": "session"}},
                "teacher": {"name": "Amalia"},
                "frequency": {"count": 1, "interval": "weekly"},
                "session_duration": {"unit": "minutes", "count": 50},
                "batch_duration": {"count": 10, "interval": "weeks"},
                "timezone": "US Eastern Standard Time",
                "start_timestamp": "",
                "end_timestamp": "",
                "meeting_type": "camp_SDK",
                "teaching_type": "group_class",
                "is_active": True,
                "is_listed": True,
                "is_enrollment_allowed": True,
                "is_free_trial_available": True,
                "is_coral_unlimited_available": True,
                "is_ppc_available": False,
            },
            {
                "id": "bbb-222",
                "title": "Finance 101: A Practical Playbook For Mastering Money",
                "subject": "lifeskills",
                "url_slug": "finance101",
            },
        ]
    },
    "placements": [],
}


# ---------------------------------------------------------------------------
# 1-2. Successful fetch + correct parsing of response["classes"].
# ---------------------------------------------------------------------------

def test_1_2_successful_fetch_and_parsing():
    _reset()
    _fake_requests_state.set_response(_FakeResponse(200, _VALID_PAYLOAD))

    result = ccc.fetch_catalog()

    check("1. successful fetch returns status SUCCESS", result["status"] == ccc.SUCCESS)
    check("2. classes list has the expected length", len(result["classes"]) == 2)
    check(
        "2. first class's title is parsed correctly from response.classes",
        result["classes"][0]["title"] == "Astronomy 101: Learn About Space",
    )
    check("fetched_at is populated", isinstance(result["fetched_at"], datetime))
    check("error is None on success", result["error"] is None)
    check(
        "the request used the documented BROWSE_URL",
        _fake_requests_state.calls[-1]["url"] == ccc.BROWSE_URL,
    )
    check(
        "the request used an explicit finite timeout",
        _fake_requests_state.calls[-1]["timeout"] == ccc.REQUEST_TIMEOUT_SECONDS
        and ccc.REQUEST_TIMEOUT_SECONDS > 0,
    )


# ---------------------------------------------------------------------------
# 3. HTTP error (non-200 status).
# ---------------------------------------------------------------------------

def test_3_http_error():
    _reset()
    _fake_requests_state.set_response(_FakeResponse(503, {"error": "unavailable"}))

    result = ccc.fetch_catalog()

    check("3. non-200 status returns API_ERROR", result["status"] == ccc.API_ERROR)
    check("3. classes is None on API_ERROR", result["classes"] is None)
    check("3. error message mentions the status code", "503" in result["error"])


# ---------------------------------------------------------------------------
# 4. Network exception.
# ---------------------------------------------------------------------------

def test_4_network_exception():
    _reset()
    _fake_requests_state.set_exception(_FakeConnectionError("connection refused"))

    result = ccc.fetch_catalog()

    check("4. a network exception returns API_ERROR, not a raised exception", result["status"] == ccc.API_ERROR)
    check("4. classes is None", result["classes"] is None)
    check("4. no exception propagated out of fetch_catalog() - reaching this line proves it", True)


# ---------------------------------------------------------------------------
# 5. Timeout.
# ---------------------------------------------------------------------------

def test_5_timeout():
    _reset()
    _fake_requests_state.set_exception(_FakeTimeout("timed out"))

    result = ccc.fetch_catalog()

    check("5. a timeout returns API_ERROR, not a raised exception", result["status"] == ccc.API_ERROR)
    check("5. error message mentions timeout", "timed out" in result["error"] or "timeout" in result["error"])


# ---------------------------------------------------------------------------
# 6. Malformed JSON.
# ---------------------------------------------------------------------------

def test_6_malformed_json():
    _reset()
    _fake_requests_state.set_response(_FakeResponse(200, raise_json_error=True))

    result = ccc.fetch_catalog()

    check("6. malformed JSON returns INVALID_RESPONSE", result["status"] == ccc.INVALID_RESPONSE)
    check("6. classes is None", result["classes"] is None)


# ---------------------------------------------------------------------------
# 7. Missing "response".
# ---------------------------------------------------------------------------

def test_7_missing_response_key():
    _reset()
    _fake_requests_state.set_response(_FakeResponse(200, {"placements": []}))

    result = ccc.fetch_catalog()

    check("7. missing 'response' key returns INVALID_RESPONSE", result["status"] == ccc.INVALID_RESPONSE)


# ---------------------------------------------------------------------------
# 8. Missing "classes".
# ---------------------------------------------------------------------------

def test_8_missing_classes_key():
    _reset()
    _fake_requests_state.set_response(_FakeResponse(200, {"response": {}}))

    result = ccc.fetch_catalog()

    check("8. missing 'classes' key returns INVALID_RESPONSE", result["status"] == ccc.INVALID_RESPONSE)


# ---------------------------------------------------------------------------
# 9. Invalid classes type.
# ---------------------------------------------------------------------------

def test_9_invalid_classes_type():
    _reset()
    _fake_requests_state.set_response(_FakeResponse(200, {"response": {"classes": "not-a-list"}}))

    result = ccc.fetch_catalog()

    check("9. non-list 'classes' returns INVALID_RESPONSE", result["status"] == ccc.INVALID_RESPONSE)


# ---------------------------------------------------------------------------
# 10. Empty catalog.
# ---------------------------------------------------------------------------

def test_10_empty_catalog():
    _reset()
    _fake_requests_state.set_response(_FakeResponse(200, {"response": {"classes": []}}))

    result = ccc.fetch_catalog()

    check("10. an empty class list is still a valid SUCCESS", result["status"] == ccc.SUCCESS)
    check("10. classes is an empty list, not None or an error", result["classes"] == [])


def test_malformed_single_class_entry_does_not_crash():
    """A malformed individual class entry (not a dict) is dropped rather
    than crashing the whole fetch."""
    _reset()
    _fake_requests_state.set_response(_FakeResponse(200, {
        "response": {"classes": [_VALID_PAYLOAD["response"]["classes"][0], "not-a-dict", None]}
    }))

    result = ccc.fetch_catalog()

    check("a malformed entry doesn't crash the fetch", result["status"] == ccc.SUCCESS)
    check("only the valid entry survives normalization", len(result["classes"]) == 1)


# ---------------------------------------------------------------------------
# 11. Cache hit avoids another HTTP request.
# ---------------------------------------------------------------------------

def test_11_cache_hit_avoids_another_request():
    _reset()
    _fake_requests_state.set_response(_FakeResponse(200, _VALID_PAYLOAD))

    now = datetime.now(timezone.utc)
    first = ccc.get_cached_catalog(now=now)
    check("11. first call fetches (1 HTTP call so far)", _fake_requests_state.call_count == 1)
    check("11. first call succeeds", first["status"] == ccc.SUCCESS)

    second = ccc.get_cached_catalog(now=now + timedelta(seconds=30))
    check(
        "11. a call within the TTL reuses the cache - no second HTTP request",
        _fake_requests_state.call_count == 1,
    )
    check("11. the cached result is returned unchanged", second is first)


# ---------------------------------------------------------------------------
# 12. Cache expires after TTL.
# ---------------------------------------------------------------------------

def test_12_cache_expires_after_ttl():
    _reset()
    _fake_requests_state.set_response(_FakeResponse(200, _VALID_PAYLOAD))

    now = datetime.now(timezone.utc)
    ccc.get_cached_catalog(ttl_seconds=300, now=now)
    check("12. first call fetches", _fake_requests_state.call_count == 1)

    ccc.get_cached_catalog(ttl_seconds=300, now=now + timedelta(seconds=301))
    check(
        "12. a call after the TTL has elapsed fetches again",
        _fake_requests_state.call_count == 2,
    )


# ---------------------------------------------------------------------------
# 13. Failed fetch is not treated as valid cached catalog.
# ---------------------------------------------------------------------------

def test_13_failed_fetch_not_cached():
    _reset()
    _fake_requests_state.set_response(_FakeResponse(503, {}))

    now = datetime.now(timezone.utc)
    first = ccc.get_cached_catalog(now=now)
    check("13. a failed fetch is returned as API_ERROR", first["status"] == ccc.API_ERROR)
    check("13. a failed fetch is not cached", ccc._cache["result"] is None)

    _fake_requests_state.set_response(_FakeResponse(200, _VALID_PAYLOAD))
    second = ccc.get_cached_catalog(now=now + timedelta(seconds=1))
    check(
        "13. the very next call retries immediately rather than reusing the failure "
        "(2 HTTP calls total, not skipped)",
        _fake_requests_state.call_count == 2,
    )
    check("13. that retry succeeds once the API recovers", second["status"] == ccc.SUCCESS)


# ===========================================================================
# find_matching_class()
# ===========================================================================

_CLASSES = _VALID_PAYLOAD["response"]["classes"]


# ---------------------------------------------------------------------------
# 14. Exact class-title match.
# ---------------------------------------------------------------------------

def test_14_exact_title_match():
    result = ccc.find_matching_class(_CLASSES, "Astronomy 101: Learn About Space")
    check("14. exact title match returns SUCCESS", result["status"] == ccc.SUCCESS)
    check("14. the correct class is returned", result["class"]["id"] == "aaa-111")


# ---------------------------------------------------------------------------
# 15. Case-insensitive matching.
# ---------------------------------------------------------------------------

def test_15_case_insensitive():
    result = ccc.find_matching_class(_CLASSES, "astronomy 101: learn about space")
    check("15. case-insensitive exact match still succeeds", result["status"] == ccc.SUCCESS)
    check("15. the correct class is returned", result["class"]["id"] == "aaa-111")


# ---------------------------------------------------------------------------
# 16. Whitespace normalization.
# ---------------------------------------------------------------------------

def test_16_whitespace_normalization():
    result = ccc.find_matching_class(_CLASSES, "  Astronomy   101:  Learn About   Space  ")
    check("16. extra/irregular whitespace is normalized away", result["status"] == ccc.SUCCESS)
    check("16. the correct class is returned", result["class"]["id"] == "aaa-111")


# ---------------------------------------------------------------------------
# 17. Strong title matching (title as substring of a full email-style query).
# ---------------------------------------------------------------------------

def test_17_strong_title_matching():
    query = "Hi, I wanted to ask about the price for Astronomy 101: Learn About Space, thanks!"
    result = ccc.find_matching_class(_CLASSES, query)
    check("17. a title embedded in a longer query is matched strongly", result["status"] == ccc.SUCCESS)
    check("17. the correct class is returned", result["class"]["id"] == "aaa-111")


# ---------------------------------------------------------------------------
# 18. No match returns NOT_FOUND.
# ---------------------------------------------------------------------------

def test_18_no_match_returns_not_found():
    result = ccc.find_matching_class(_CLASSES, "Do you offer any pottery classes?")
    check("18. an unrelated query returns NOT_FOUND", result["status"] == ccc.NOT_FOUND)
    check("18. class is None", result["class"] is None)


def test_18b_no_classes_or_empty_query_returns_not_found():
    check(
        "18b. empty class list returns NOT_FOUND, not a crash",
        ccc.find_matching_class([], "Astronomy 101")["status"] == ccc.NOT_FOUND,
    )
    check(
        "18b. empty query text returns NOT_FOUND",
        ccc.find_matching_class(_CLASSES, "")["status"] == ccc.NOT_FOUND,
    )
    check(
        "18b. None query text returns NOT_FOUND, not a crash",
        ccc.find_matching_class(_CLASSES, None)["status"] == ccc.NOT_FOUND,
    )


# ---------------------------------------------------------------------------
# 19. Multiple plausible matches returns AMBIGUOUS.
# ---------------------------------------------------------------------------

def test_19_multiple_matches_ambiguous():
    classes = [
        {"id": "1", "title": "Astronomy 101: Learn About Space", "subject": "science", "url_slug": "a1"},
        {"id": "2", "title": "Astronomy 201: Deep Space Exploration", "subject": "science", "url_slug": "a2"},
    ]
    # "Astronomy" alone doesn't substring-match either full title (titles
    # are longer than the query and the query is shorter than either
    # title), so use a query that legitimately contains both titles'
    # distinguishing text to exercise the ambiguous path cleanly instead.
    result = ccc.find_matching_class(classes, "science")
    check(
        "19. a query matching more than one class by subject returns AMBIGUOUS, not a guess",
        result["status"] == ccc.AMBIGUOUS,
    )
    check("19. class is None on AMBIGUOUS (never guesses)", result["class"] is None)
    check("19. both candidates are listed", len(result["candidates"]) == 2)


# ---------------------------------------------------------------------------
# 20. Missing optional fields do not crash.
# ---------------------------------------------------------------------------

def test_20_missing_optional_fields_no_crash():
    sparse_classes = [{"id": "x", "title": "Only A Title"}]
    result = ccc.find_matching_class(sparse_classes, "Only A Title")
    check("20. a class with only a title still matches without crashing", result["status"] == ccc.SUCCESS)

    empty_class = [{}]
    result2 = ccc.find_matching_class(empty_class, "anything")
    check("20. a completely empty class dict doesn't crash matching", result2["status"] == ccc.NOT_FOUND)


# ===========================================================================
# build_live_class_context()
# ===========================================================================

# ---------------------------------------------------------------------------
# 21. build_live_class_context does not invent fields.
# ---------------------------------------------------------------------------

def test_21_context_does_not_invent_fields():
    sparse = {"title": "Astronomy 101", "id": "aaa-111", "subject": "science"}
    context = ccc.build_live_class_context(sparse)

    check("21. only actually-present allow-listed fields appear", set(context.keys()) == {"title", "subject"})
    check(
        "21. a field the class dict doesn't have at all is not invented "
        "(e.g. 'pricing' is absent here, and absent from the context too)",
        "pricing" not in context,
    )
    check("21. 'id' is not part of the live-context allow-list and is correctly excluded", "id" not in context)


def test_21b_context_full_class_returns_all_allowed_fields():
    context = ccc.build_live_class_context(_CLASSES[0])
    expected_present = set(ccc._LIVE_CONTEXT_FIELDS) - {"start_timestamp", "end_timestamp"}
    # start_timestamp/end_timestamp are present but empty strings ("") in
    # the fixture - build_live_class_context correctly keeps an empty
    # string (it's real information: "no fixed date"), only None is
    # treated as absent.
    check(
        "21b. every allow-listed field present in the source class dict appears in the context",
        expected_present.issubset(context.keys()),
    )
    check(
        "21b. an empty-string field (start_timestamp) is preserved, not treated as missing",
        context.get("start_timestamp") == "",
    )
    check(
        "21b. no field outside the allow-list leaks through (e.g. raw 'id')",
        "id" not in context,
    )


def test_21c_context_handles_non_dict_input():
    check("21c. non-dict input returns an empty context, not a crash", ccc.build_live_class_context(None) == {})
    check("21c. a list input returns an empty context, not a crash", ccc.build_live_class_context([1, 2]) == {})


# ---------------------------------------------------------------------------
# 22. No seat-availability claim is generated unless the API actually
# provides such a field.
# ---------------------------------------------------------------------------

def test_22_no_seat_availability_field_ever_generated():
    check(
        "22. the live-context allow-list contains no seat/availability-count field at all "
        "(confirmed absent from the real API by the prior investigation)",
        not any(
            "seat" in f.lower() or "remaining" in f.lower() or "capacity" in f.lower() or f == "size"
            for f in ccc._LIVE_CONTEXT_FIELDS
        ),
    )

    # Even if a class dict somehow carried an unexpected seat-count-shaped
    # field (e.g. a future or malformed API response), the allow-list
    # design means it can never leak into the generated context.
    class_with_unexpected_field = dict(_CLASSES[0])
    class_with_unexpected_field["seats_remaining"] = 3
    class_with_unexpected_field["size"] = {"max": 10, "min": 1}

    context = ccc.build_live_class_context(class_with_unexpected_field)

    check(
        "22. an unexpected 'seats_remaining'-style field never appears in the generated context",
        "seats_remaining" not in context,
    )
    check(
        "22. 'size' (class-size design range, not a live seat count) is also correctly excluded",
        "size" not in context,
    )


def main():
    test_1_2_successful_fetch_and_parsing()
    test_3_http_error()
    test_4_network_exception()
    test_5_timeout()
    test_6_malformed_json()
    test_7_missing_response_key()
    test_8_missing_classes_key()
    test_9_invalid_classes_type()
    test_10_empty_catalog()
    test_malformed_single_class_entry_does_not_crash()
    test_11_cache_hit_avoids_another_request()
    test_12_cache_expires_after_ttl()
    test_13_failed_fetch_not_cached()

    test_14_exact_title_match()
    test_15_case_insensitive()
    test_16_whitespace_normalization()
    test_17_strong_title_matching()
    test_18_no_match_returns_not_found()
    test_18b_no_classes_or_empty_query_returns_not_found()
    test_19_multiple_matches_ambiguous()
    test_20_missing_optional_fields_no_crash()

    test_21_context_does_not_invent_fields()
    test_21b_context_full_class_returns_all_allowed_fields()
    test_21c_context_handles_non_dict_input()
    test_22_no_seat_availability_field_ever_generated()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
