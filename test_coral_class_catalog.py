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
import live_class_intent as lci  # noqa: E402 - only used by test F, for build_prompt_block()


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
                "enrollment_type": "ongoing",
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


# ---------------------------------------------------------------------------
# Pricing/teacher price-bug fix: production sent a parent "$2,000 USD per
# session" for a class actually priced at $20.00 - Coral's raw
# pricing.regular.amount (2000) is in cents, and build_live_class_context()
# used to pass that raw dict straight into the prompt. These tests exercise
# the real, fixed build_live_class_context()/_format_pricing()/
# _format_teacher(), not a mirror.
# ---------------------------------------------------------------------------

def test_A_pricing_cents_converted_to_dollars():
    class_data = {
        "title": "Astronomy 101: Learn About Space",
        "pricing": {
            "regular": {
                "unit": "session",
                "amount": 2000,
                "currency": "usd",
            }
        },
    }
    context = ccc.build_live_class_context(class_data)
    check(
        "A. amount=2000 cents is converted to '$20.00 per session', matching the verified live price",
        context.get("pricing") == "$20.00 per session",
        f"got {context.get('pricing')!r}",
    )


def test_B_no_raw_pricing_leaks_into_context():
    class_data = {
        "title": "Astronomy 101: Learn About Space",
        "pricing": {
            "regular": {
                "unit": "session",
                "amount": 2000,
                "currency": "usd",
            }
        },
    }
    context = ccc.build_live_class_context(class_data)
    pricing_value = context.get("pricing")

    check("B. pricing value is a plain string, not the raw dict", isinstance(pricing_value, str))
    check("B. context does not contain the literal word 'amount' anywhere", "amount" not in str(context))
    check(
        "B. context does not contain a raw pricing-dict representation (e.g. \"{'regular':\")",
        "{'regular'" not in str(context) and '{"regular"' not in str(context),
    )
    check(
        "B. context does not contain the incorrect '$2,000' reading of the unconverted cents value",
        "$2,000" not in str(context),
    )


def test_C_multiple_pricing_tiers_labeled():
    class_data = {
        "title": "Finance 101",
        "pricing": {
            "regular": {"unit": "session", "amount": 2500, "currency": "usd"},
            "sibling_discount": {"unit": "session", "amount": 2000, "currency": "usd"},
        },
    }
    context = ccc.build_live_class_context(class_data)
    check(
        "C. multiple pricing tiers are each converted and labeled on their own line",
        context.get("pricing") == "Regular: $25.00 per session\nSibling Discount: $20.00 per session",
        f"got {context.get('pricing')!r}",
    )


def test_D_teacher_reduced_to_name_only():
    class_data = {
        "title": "Astronomy 101: Learn About Space",
        "teacher": {
            "id": "9fbeef67-7e48-415f-9205-c3a53d10cc34",
            "name": "Amalia",
            "bio": "As a nature teacher and world explorer, I have worked with children...",
            "headline": "Building a Love for Science Through Exploration!",
            "profile_image_url": "https://backend.coralacademy.com/storage/v1/object/public/profile_images//Amalia.png",
            "reviews": {"value": 0, "count": 0},
            "is_saved": False,
            "is_messaging_available": True,
        },
    }
    context = ccc.build_live_class_context(class_data)

    check(
        "D. teacher field is reduced to exactly the teacher's name",
        context.get("teacher") == "Amalia",
        f"got {context.get('teacher')!r}",
    )
    check("D. teacher bio does not leak into the context", "nature teacher and world explorer" not in str(context))
    check("D. teacher headline does not leak into the context", "Building a Love for Science" not in str(context))
    check("D. teacher profile_image_url does not leak into the context", "profile_images" not in str(context))
    check("D. teacher internal id does not leak into the context", "9fbeef67-7e48-415f-9205-c3a53d10cc34" not in str(context))
    check("D. teacher reviews data does not leak into the context", "reviews" not in str(context))
    check("D. teacher is_saved flag does not leak into the context", "is_saved" not in str(context))
    check("D. teacher is_messaging_available flag does not leak into the context", "is_messaging_available" not in str(context))


def test_E_missing_teacher_name_omits_field():
    no_name = {"title": "Astronomy 101", "teacher": {"id": "aaa", "bio": "..."}}
    empty_name = {"title": "Astronomy 101", "teacher": {"name": "   "}}
    not_a_dict = {"title": "Astronomy 101", "teacher": "Amalia"}

    check(
        "E. a teacher object with no 'name' key omits the teacher field entirely (not the raw object)",
        "teacher" not in ccc.build_live_class_context(no_name),
    )
    check(
        "E. a teacher object with a blank/whitespace-only name omits the teacher field",
        "teacher" not in ccc.build_live_class_context(empty_name),
    )
    check(
        "E. a non-dict teacher value omits the teacher field rather than passing it through raw",
        "teacher" not in ccc.build_live_class_context(not_a_dict),
    )


def test_F_prompt_block_has_formatted_price_not_raw_cents():
    class_data = {
        "title": "Astronomy 101: Learn About Space",
        "pricing": {
            "regular": {
                "unit": "session",
                "amount": 2000,
                "currency": "usd",
            }
        },
    }
    context = ccc.build_live_class_context(class_data)
    block = lci.build_prompt_block(context)

    check("F. build_prompt_block() contains the correctly converted price", "$20.00 per session" in block)
    check("F. build_prompt_block() does not contain the raw 'amount' key", "amount" not in block)
    check("F. build_prompt_block() does not contain the bare unconverted cents value '2000'", "2000" not in block)
    check("F. build_prompt_block() does not contain the incorrect '$2,000' reading", "$2,000" not in block)


# ===========================================================================
# Class browsing (multi-class) support - Phase 3.
# ===========================================================================

# ---------------------------------------------------------------------------
# G/H. Deduplication - strictly by id (fallback url_slug), never by title.
# ---------------------------------------------------------------------------

def test_G_dedupe_by_id_removes_duplicate():
    classes = [
        {"id": "aaa-111", "title": "Astronomy 101", "url_slug": "astro"},
        {"id": "aaa-111", "title": "Astronomy 101 (duplicate)", "url_slug": "astro-dup"},
        {"id": "bbb-222", "title": "Finance 101", "url_slug": "finance"},
    ]
    deduped = ccc._dedupe_classes(classes)
    check("G. duplicate id is removed, only one entry per id remains", len(deduped) == 2)
    check("G. the FIRST occurrence of a duplicate id is kept", deduped[0]["title"] == "Astronomy 101")


def test_H_dedupe_same_title_different_id_both_kept():
    classes = [
        {"id": "aaa-111", "title": "Into the Wild: Young Zoologists Club", "url_slug": "wild-1"},
        {"id": "ccc-333", "title": "Into the Wild: Young Zoologists Club", "url_slug": "wild-2"},
    ]
    deduped = ccc._dedupe_classes(classes)
    check(
        "H. two entries with the SAME title but different ids are both kept "
        "(dedup must never use title as the key)",
        len(deduped) == 2,
    )


def test_H2_dedupe_fallback_to_url_slug_when_id_missing():
    classes = [
        {"title": "A", "url_slug": "slug-a"},
        {"title": "A duplicate", "url_slug": "slug-a"},
        {"title": "B", "url_slug": "slug-b"},
    ]
    deduped = ccc._dedupe_classes(classes)
    check("H2. falls back to url_slug when id is absent", len(deduped) == 2)


# ---------------------------------------------------------------------------
# I-L. Current availability filtering - real API semantics (is_active is a
# STRING, not a boolean).
# ---------------------------------------------------------------------------

def test_I_is_active_string_false_excluded():
    c = {"is_active": "false", "is_listed": True, "approval_status": "approved"}
    check(
        "I. is_active='false' (string) is correctly excluded - a naive truthiness "
        "check would incorrectly treat this non-empty string as truthy",
        ccc._is_class_currently_available(c) is False,
    )


def test_J_is_active_string_true_included():
    c = {"is_active": "true", "is_listed": True, "approval_status": "approved"}
    check("J. is_active='true' + is_listed=True + approved is currently available", ccc._is_class_currently_available(c) is True)


def test_K_is_listed_false_excluded():
    c = {"is_active": "true", "is_listed": False, "approval_status": "approved"}
    check("K. is_listed=False excludes the class even when active+approved", ccc._is_class_currently_available(c) is False)


def test_L_approval_status_not_approved_excluded():
    for status in ("pending", "rejected", "", None):
        c = {"is_active": "true", "is_listed": True, "approval_status": status}
        check(
            f"L. approval_status={status!r} (not 'approved') excludes the class",
            ccc._is_class_currently_available(c) is False,
        )


def test_L2_availability_non_dict_input_safe():
    check("L2. non-dict input returns False, not a crash", ccc._is_class_currently_available(None) is False)
    check("L2. a list input returns False, not a crash", ccc._is_class_currently_available([1, 2]) is False)


# ---------------------------------------------------------------------------
# M-O. Schedule formatter - only frequency/session_duration/batch_duration/
# start_timestamp/end_timestamp/enrollment_type; never day-of-week or
# time-of-day, which no live field provides.
# ---------------------------------------------------------------------------

def test_M_schedule_facts_formatted_cleanly():
    class_data = {
        "frequency": {"count": 1, "interval": "weekly", "value_type": "default"},
        "session_duration": {"unit": "minutes", "count": 50, "value_type": "default"},
        "batch_duration": {"count": 3, "interval": "weeks", "max_count": 78, "value_type": "minimum"},
        "enrollment_type": "ongoing",
        "start_timestamp": None,
        "end_timestamp": None,
    }
    facts = ccc._format_schedule_facts(class_data)
    check("M. frequency formatted as '1 session per week'", facts.get("frequency") == "1 session per week")
    check("M. session_duration formatted as '50 minutes per session'", facts.get("session_duration") == "50 minutes per session")
    check("M. batch_duration formatted as 'Minimum 3 weeks'", facts.get("batch_duration") == "Minimum 3 weeks")
    check("M. enrollment_type 'ongoing' formatted as 'Ongoing enrollment'", facts.get("enrollment_type") == "Ongoing enrollment")
    check(
        "M. no fixed start/end timestamps produces the 'rolling enrollment' dates fact",
        facts.get("dates") == "No fixed start/end date (rolling enrollment)",
    )


def test_M2_schedule_facts_plural_sessions():
    class_data = {"frequency": {"count": 2, "interval": "weekly", "value_type": "default"}}
    facts = ccc._format_schedule_facts(class_data)
    check("M2. count=2 correctly pluralizes 'sessions'", facts.get("frequency") == "2 sessions per week")


def test_M3_schedule_facts_start_end_dates_when_present():
    class_data = {"start_timestamp": "2026-04-01T00:00:00Z", "end_timestamp": "2026-06-01T00:00:00Z"}
    facts = ccc._format_schedule_facts(class_data)
    check("M3. a real start_timestamp produces a start_date fact, not the rolling-enrollment fallback", "start_date" in facts and "dates" not in facts)
    check("M3. a real end_timestamp produces an end_date fact", "end_date" in facts)


def test_N_missing_schedule_fields_omitted():
    facts = ccc._format_schedule_facts({"title": "X"})
    check("N. a class with no schedule-related fields at all produces only the rolling-enrollment dates fact", set(facts.keys()) == {"dates"})

    facts2 = ccc._format_schedule_facts({"frequency": {"count": 1, "interval": "weekly"}})
    check("N. missing session_duration/batch_duration are simply absent, not errored or invented", "session_duration" not in facts2 and "batch_duration" not in facts2)

    check("N. non-dict input returns {} rather than crashing", ccc._format_schedule_facts(None) == {})
    check("N. malformed frequency (not a dict) is skipped rather than crashing", "frequency" not in ccc._format_schedule_facts({"frequency": "weekly"}))


def test_O_no_day_or_time_ever_invented():
    class_data = {
        "frequency": {"count": 1, "interval": "weekly", "value_type": "default"},
        "session_duration": {"unit": "minutes", "count": 50, "value_type": "default"},
        "batch_duration": {"count": 3, "interval": "weeks", "value_type": "minimum"},
        "enrollment_type": "ongoing",
    }
    facts = ccc._format_schedule_facts(class_data)
    facts_text = " ".join(str(v) for v in facts.values()).lower()
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    check(
        "O. no weekday name ever appears in formatted schedule facts - no live field provides one",
        not any(day in facts_text for day in weekdays),
    )
    check(
        "O. no clock-time pattern (am/pm) ever appears in formatted schedule facts",
        "am" not in facts_text.split() and "pm" not in facts_text.split(),
    )


# ---------------------------------------------------------------------------
# P/Q. build_browsing_class_context() reuses the existing pricing/teacher
# formatters unchanged - no regression on the 14b8ec6 fix.
# ---------------------------------------------------------------------------

def test_P_browsing_context_pricing_regression():
    class_data = {
        "title": "Astronomy 101: Learn About Space",
        "pricing": {"regular": {"unit": "session", "amount": 2000, "currency": "usd"}},
    }
    context = ccc.build_browsing_class_context(class_data)
    check(
        "P. browsing context pricing is '$20.00 per session', not raw cents or '$2,000'",
        context.get("pricing") == "$20.00 per session",
        f"got {context.get('pricing')!r}",
    )


def test_Q_browsing_context_teacher_sanitized():
    class_data = {
        "title": "Astronomy 101: Learn About Space",
        "teacher": {
            "id": "9fbeef67-7e48-415f-9205-c3a53d10cc34",
            "name": "Amalia",
            "bio": "As a nature teacher and world explorer...",
            "profile_image_url": "https://backend.coralacademy.com/storage/.../Amalia.png",
        },
    }
    context = ccc.build_browsing_class_context(class_data)
    check("Q. browsing context teacher is reduced to just the name", context.get("teacher") == "Amalia")
    check("Q. browsing context never exposes teacher bio", "nature teacher and world explorer" not in str(context))
    check("Q. browsing context never exposes teacher profile_image_url", "profile_images" not in str(context) and "backend.coralacademy.com" not in str(context))


# ---------------------------------------------------------------------------
# R. enrollment_type is now an allow-listed single-class field too.
# ---------------------------------------------------------------------------

def test_R_enrollment_type_in_single_class_context():
    class_data = {"title": "X", "enrollment_type": "ongoing"}
    context = ccc.build_live_class_context(class_data)
    check("R. 'enrollment_type' is present in _LIVE_CONTEXT_FIELDS", "enrollment_type" in ccc._LIVE_CONTEXT_FIELDS)
    check("R. enrollment_type passes through the single-class context", context.get("enrollment_type") == "ongoing")


# ---------------------------------------------------------------------------
# S. The known "Into the Wild" incident: a rich, multi-topic description
# (containing what looks like a second class, "Scales and Slime") must
# never leak into a browsing context - build_browsing_class_context()
# simply never reads description at all.
# ---------------------------------------------------------------------------

def test_S_rich_description_never_leaks_into_browsing_context():
    class_data = {
        "id": "d8a4adf3-941f-4944-b278-378544601ecc",
        "title": "Into the Wild: Young Zoologists Club",
        "url_slug": "scalesandslime",
        "description": (
            "Live science classes featuring real animals...\n\n"
            "SQUAMATA\nAbout 90% of all reptiles are squamates...\n"
            "April 2: Colubrids & Constrictors\nApril 9: Vipers & Cobras"
        ),
        "pricing": {"regular": {"unit": "session", "amount": 2000, "currency": "usd"}},
    }
    context = ccc.build_browsing_class_context(class_data)
    context_text = str(context)
    check("S. browsing context never contains the raw description text", "SQUAMATA" not in context_text)
    check("S. browsing context never contains description-derived dated schedule text", "Colubrids" not in context_text and "April 2" not in context_text)
    check("S. build_browsing_class_context() has exactly one title in its output", context.get("title") == "Into the Wild: Young Zoologists Club")


# ---------------------------------------------------------------------------
# T/U. find_matching_classes_for_browsing() - exact word-boundary subject
# match, never a loose substring; generic query returns everything.
# ---------------------------------------------------------------------------

_BROWSING_CLASSES = [
    {"id": "s1", "title": "Astronomy 101: Learn About Space", "subject": "science", "url_slug": "astro"},
    {"id": "s2", "title": "Geology & Earth Science Explorers", "subject": "science", "url_slug": "geology"},
    {"id": "f1", "title": "Finance 101: A Practical Playbook", "subject": "lifeskills", "url_slug": "finance"},
]


def test_T_browsing_subject_word_boundary_match():
    result = ccc.find_matching_classes_for_browsing(_BROWSING_CLASSES, "What science classes are currently available?")
    check("T. subject match returns only the 'science' classes", {c["id"] for c in result} == {"s1", "s2"})


def test_T2_browsing_no_loose_substring_match():
    # "art" must not match inside an unrelated word like "started" or "part" -
    # word-boundary matching only.
    classes_with_short_subject = [
        {"id": "a1", "title": "Art Explorers", "subject": "art", "url_slug": "art-1"},
        {"id": "s1", "title": "Astronomy 101", "subject": "science", "url_slug": "astro"},
    ]
    result = ccc.find_matching_classes_for_browsing(
        classes_with_short_subject, "We started this program part-way through the year, what classes are available?"
    )
    check(
        "T2. 'art' does not accidentally match inside 'started'/'part' - no subject "
        "term is actually present, so every class is returned as a generic candidate",
        {c["id"] for c in result} == {"a1", "s1"},
    )


def test_U_browsing_generic_query_returns_all_classes():
    result = ccc.find_matching_classes_for_browsing(_BROWSING_CLASSES, "What classes do you have available?")
    check("U. a fully generic query with no recognized subject returns every class", len(result) == 3)


# ---------------------------------------------------------------------------
# V-Z. Parent-facing context cleanup: url_slug removed from both LLM
# contexts (but still available internally for matching/dedup), and every
# boolean fact reshaped to "Yes"/"No" instead of a raw Python bool - the
# fix for the confirmed "scalesandslime" / "Enrollment currently allowed:
# True" production leak.
# ---------------------------------------------------------------------------

def test_V_url_slug_not_in_live_context_allow_list():
    check("V. url_slug is not in _LIVE_CONTEXT_FIELDS", "url_slug" not in ccc._LIVE_CONTEXT_FIELDS)
    check("V. url_slug is not in _BROWSING_CONTEXT_FIELDS", "url_slug" not in ccc._BROWSING_CONTEXT_FIELDS)


def test_V2_url_slug_never_in_single_class_context():
    context = ccc.build_live_class_context(_CLASSES[0])
    check(
        "V2. build_live_class_context() output never contains 'url_slug', even for a class whose raw data has it",
        "url_slug" not in context,
        f"got keys {sorted(context.keys())}",
    )
    check("V2. the source fixture actually has url_slug (proves this isn't a vacuous pass)", "url_slug" in _CLASSES[0])


def test_V3_url_slug_never_in_browsing_context():
    context = ccc.build_browsing_class_context(_CLASSES[0])
    check(
        "V3. build_browsing_class_context() output never contains 'url_slug', even for a class whose raw data has it",
        "url_slug" not in context,
        f"got keys {sorted(context.keys())}",
    )


def test_V4_url_slug_still_available_internally_for_matching_and_dedup():
    """url_slug must remain on the raw catalog data and keep working for
    _dedupe_classes()'s fallback key - only its presence in the two
    LLM-facing context builders was removed."""
    raw = _CLASSES[0]
    check("V4. url_slug is still present on the raw class dict", raw.get("url_slug") == "astro101")

    classes = [
        {"title": "A", "url_slug": "slug-a"},
        {"title": "A duplicate", "url_slug": "slug-a"},
        {"title": "B", "url_slug": "slug-b"},
    ]
    deduped = ccc._dedupe_classes(classes)
    check("V4. _dedupe_classes() still falls back to url_slug when id is missing (unchanged behavior)", len(deduped) == 2)

    check(
        "V4. find_matching_classes_for_browsing() still receives/operates on raw dicts that still carry url_slug",
        all("url_slug" in c for c in ccc.find_matching_classes_for_browsing(_BROWSING_CLASSES, "science")),
    )


def test_W_format_bool_fact_direct():
    check('W. _format_bool_fact(True) == "Yes"', ccc._format_bool_fact(True) == "Yes")
    check('W. _format_bool_fact(False) == "No"', ccc._format_bool_fact(False) == "No")
    check("W. a non-boolean value passes through unchanged (string)", ccc._format_bool_fact("hello") == "hello")
    check("W. a non-boolean value passes through unchanged (int)", ccc._format_bool_fact(5) == 5)
    check("W. a non-boolean value passes through unchanged (None)", ccc._format_bool_fact(None) is None)


def test_X_all_booleans_in_single_class_context_are_yes_no():
    # _CLASSES[0] has a deliberate mix: is_ppc_available=False, every
    # other boolean field=True - proves both directions are formatted,
    # not just a hardcoded "always Yes".
    context = ccc.build_live_class_context(_CLASSES[0])

    check("X. is_active=True -> 'Yes'", context.get("is_active") == "Yes")
    check("X. is_listed=True -> 'Yes'", context.get("is_listed") == "Yes")
    check("X. is_enrollment_allowed=True -> 'Yes'", context.get("is_enrollment_allowed") == "Yes")
    check("X. is_free_trial_available=True -> 'Yes'", context.get("is_free_trial_available") == "Yes")
    check("X. is_coral_unlimited_available=True -> 'Yes'", context.get("is_coral_unlimited_available") == "Yes")
    check("X. is_ppc_available=False -> 'No' (proves False also formats correctly, not just True)", context.get("is_ppc_available") == "No")

    check(
        "X. no value anywhere in the single-class context is a raw Python bool",
        all(not isinstance(v, bool) for v in context.values()),
        f"got {[(k, type(v).__name__) for k, v in context.items() if isinstance(v, bool)]}",
    )


def test_Y_enrollment_allowed_true_and_false_in_browsing_context():
    context_true = ccc.build_browsing_class_context({"title": "T", "is_enrollment_allowed": True})
    context_false = ccc.build_browsing_class_context({"title": "T", "is_enrollment_allowed": False})

    check('Y. is_enrollment_allowed=True -> "Yes" in browsing context', context_true.get("is_enrollment_allowed") == "Yes")
    check('Y. is_enrollment_allowed=False -> "No" in browsing context', context_false.get("is_enrollment_allowed") == "No")
    check(
        "Y. no value anywhere in either browsing context is a raw Python bool",
        all(not isinstance(v, bool) for v in context_true.values())
        and all(not isinstance(v, bool) for v in context_false.values()),
    )


def test_Z_non_boolean_special_formatting_unaffected():
    """Sanity check that the new bool-reshaping pass doesn't touch
    pricing/teacher/schedule/enrollment_type - all still exactly as
    their own dedicated formatters produce."""
    context = ccc.build_live_class_context(_CLASSES[0])
    check("Z. pricing is still the formatted string, untouched by bool-reshaping", context.get("pricing") == "$25.00 per session")
    check("Z. teacher is still reduced to just the name, untouched by bool-reshaping", context.get("teacher") == "Amalia")
    check("Z. enrollment_type still passes through as the raw string ('ongoing'), not reshaped as if it were boolean", context.get("enrollment_type") == "ongoing")

    browsing_context = ccc.build_browsing_class_context(_CLASSES[0])
    check("Z. browsing pricing is still the formatted string", browsing_context.get("pricing") == "$25.00 per session")
    check("Z. browsing schedule facts are still the dict _format_schedule_facts() produces, not stringified/reshaped", isinstance(browsing_context.get("schedule"), dict))


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

    test_A_pricing_cents_converted_to_dollars()
    test_B_no_raw_pricing_leaks_into_context()
    test_C_multiple_pricing_tiers_labeled()
    test_D_teacher_reduced_to_name_only()
    test_E_missing_teacher_name_omits_field()
    test_F_prompt_block_has_formatted_price_not_raw_cents()

    test_G_dedupe_by_id_removes_duplicate()
    test_H_dedupe_same_title_different_id_both_kept()
    test_H2_dedupe_fallback_to_url_slug_when_id_missing()
    test_I_is_active_string_false_excluded()
    test_J_is_active_string_true_included()
    test_K_is_listed_false_excluded()
    test_L_approval_status_not_approved_excluded()
    test_L2_availability_non_dict_input_safe()
    test_M_schedule_facts_formatted_cleanly()
    test_M2_schedule_facts_plural_sessions()
    test_M3_schedule_facts_start_end_dates_when_present()
    test_N_missing_schedule_fields_omitted()
    test_O_no_day_or_time_ever_invented()
    test_P_browsing_context_pricing_regression()
    test_Q_browsing_context_teacher_sanitized()
    test_R_enrollment_type_in_single_class_context()
    test_S_rich_description_never_leaks_into_browsing_context()
    test_T_browsing_subject_word_boundary_match()
    test_T2_browsing_no_loose_substring_match()
    test_U_browsing_generic_query_returns_all_classes()

    test_V_url_slug_not_in_live_context_allow_list()
    test_V2_url_slug_never_in_single_class_context()
    test_V3_url_slug_never_in_browsing_context()
    test_V4_url_slug_still_available_internally_for_matching_and_dedup()
    test_W_format_bool_fact_direct()
    test_X_all_booleans_in_single_class_context_are_yes_no()
    test_Y_enrollment_allowed_true_and_false_in_browsing_context()
    test_Z_non_boolean_special_formatting_unaffected()

    if _failures:
        print(f"\n{len(_failures)} FAILURE(S): {_failures}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")


if __name__ == "__main__":
    main()
