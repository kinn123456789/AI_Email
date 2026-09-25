#coral_class_catalog.py
"""Read-only client for Coral Academy's public, unauthenticated class
catalog API - the same GET https://api.coralacademy.com/browse-classes
that sync_classes.py already calls in production. Built for a future
parent-email feature that needs the CURRENT live catalog, not the
daily-synced (and potentially stale) copy in AI_Email's own `classes`
table.

Why this exists: a read-only investigation this session found a real,
live example of exactly the staleness risk this module is meant to avoid
- a class that had stopped appearing in Coral's live browse-classes
results was still sitting in AI_Email's `classes` table with
is_active=true, unnoticed, because nothing ever re-checked it against the
live catalog. Anything this module returns as "current" is either a fact
this exact request actually got back from Coral, or an explicit failure
status - never a guess, and never silently-stale data presented as live.

This module does NOT touch:
- Coral Supabase (only ever calls Coral's public HTTP API)
- AI_Email's own database
- the scheduler
- any LLM (all matching here is deterministic string comparison)

Phase 1 only: fetching, caching, and deterministic matching. Wiring this
into the actual email-generation pipeline is a separate, later phase -
nothing in this file is imported or called from the existing pipeline yet.
"""

import re
import threading
from datetime import datetime, timezone

import requests


BROWSE_URL = "https://api.coralacademy.com/browse-classes"

# No better-established timeout value exists anywhere in this codebase -
# sync_classes.py's own calls to this same API have no timeout at all
# today (a real, pre-existing gap, out of scope to fix here). 5 seconds
# is a deliberately generous but finite ceiling for a single, small,
# unauthenticated GET.
REQUEST_TIMEOUT_SECONDS = 5

# The catalog is small (under a dozen classes) and changes infrequently -
# 5 minutes keeps repeated parent emails within a short window from each
# re-fetching, while staying far fresher than the existing ~24-hour daily
# sync this is meant to improve on.
CACHE_TTL_SECONDS = 5 * 60


# ---------------------------------------------------------------------------
# Result status constants. Every public function here returns a dict with
# one of these under "status" - callers must branch on it explicitly
# rather than assuming success. This is the mechanism that satisfies the
# "never silently substitute stale data as if it were current" rule: a
# caller that ignores the status and reaches straight for a "class" or
# "classes" key gets None, not fabricated data.
# ---------------------------------------------------------------------------

SUCCESS = "SUCCESS"
API_ERROR = "API_ERROR"
INVALID_RESPONSE = "INVALID_RESPONSE"
NOT_FOUND = "NOT_FOUND"
AMBIGUOUS = "AMBIGUOUS"


def _normalize_text(text):
    """Lowercase, whitespace-collapsed, trimmed - the same normalization
    applied to both class titles/subjects/slugs and the caller's query
    text, so comparisons are consistent regardless of casing or
    incidental whitespace differences."""

    if not text:
        return ""

    return re.sub(r"\s+", " ", str(text).strip().lower())


def _normalize_class(raw):
    """Ensures the handful of identity fields this module actually
    depends on for matching (id, title, subject, url_slug) are always
    present as strings, so later code never has to special-case a
    missing/wrong-typed field. Every other field from the API is passed
    through unchanged via a shallow copy - nothing is stripped, and
    nothing beyond these four identity fields is ever defaulted or
    invented. Returns None for an entry that isn't even a dict, so a
    malformed single class in an otherwise-valid list can't crash the
    whole fetch."""

    if not isinstance(raw, dict):
        return None

    normalized = dict(raw)
    normalized["id"] = str(raw.get("id") or "")
    normalized["title"] = str(raw.get("title") or "")
    normalized["subject"] = str(raw.get("subject") or "")
    normalized["url_slug"] = str(raw.get("url_slug") or "")
    return normalized


def fetch_catalog(timeout=REQUEST_TIMEOUT_SECONDS):
    """Fetches the live Coral class catalog with a single, unauthenticated
    GET. Never raises - every failure mode (network error, timeout, a
    non-200 status, malformed JSON, an unexpected response shape) is
    caught here and turned into a {"status": ...} result instead, so a
    Coral outage can never crash whatever calls this. No retry - a caller
    that wants to retry can call this again itself.

    Returns a dict:
        status:     SUCCESS, API_ERROR, or INVALID_RESPONSE
        classes:    list of normalized class dicts on SUCCESS, else None
        fetched_at: UTC datetime of this attempt
        error:      short, secret-free description on failure, else None

    Never logs or includes the raw response body or any request headers -
    there are no credentials on this endpoint to begin with, but failure
    messages here are deliberately kept to short, generic descriptions
    rather than dumping response content.
    """

    fetched_at = datetime.now(timezone.utc)

    try:
        response = requests.get(BROWSE_URL, timeout=timeout)
    except requests.Timeout:
        return {
            "status": API_ERROR,
            "classes": None,
            "fetched_at": fetched_at,
            "error": "request timed out",
        }
    except requests.RequestException as e:
        return {
            "status": API_ERROR,
            "classes": None,
            "fetched_at": fetched_at,
            "error": f"network error ({type(e).__name__})",
        }

    if response.status_code != 200:
        return {
            "status": API_ERROR,
            "classes": None,
            "fetched_at": fetched_at,
            "error": f"unexpected HTTP status {response.status_code}",
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "status": INVALID_RESPONSE,
            "classes": None,
            "fetched_at": fetched_at,
            "error": "response body was not valid JSON",
        }

    if not isinstance(payload, dict) or "response" not in payload:
        return {
            "status": INVALID_RESPONSE,
            "classes": None,
            "fetched_at": fetched_at,
            "error": "missing top-level 'response' key",
        }

    inner = payload["response"]

    if not isinstance(inner, dict) or "classes" not in inner:
        return {
            "status": INVALID_RESPONSE,
            "classes": None,
            "fetched_at": fetched_at,
            "error": "missing 'response.classes' key",
        }

    raw_classes = inner["classes"]

    if not isinstance(raw_classes, list):
        return {
            "status": INVALID_RESPONSE,
            "classes": None,
            "fetched_at": fetched_at,
            "error": "'response.classes' was not a list",
        }

    normalized_classes = [
        nc for nc in (_normalize_class(item) for item in raw_classes)
        if nc is not None
    ]

    return {
        "status": SUCCESS,
        "classes": normalized_classes,
        "fetched_at": fetched_at,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Process-local, in-memory cache. Deliberately simple - a single dict
# behind a lock, no Redis, no database, no new infrastructure. Guarded by
# a lock in the same style as gmail_auth.py's existing _creds_cache_lock,
# since this module may eventually be called from concurrently-running
# mailbox workers once wired into the pipeline (not yet, in this phase).
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache = {"result": None, "fetched_at": None}


def get_cached_catalog(ttl_seconds=CACHE_TTL_SECONDS, now=None):
    """Returns the cached catalog if it holds a SUCCESS result younger
    than ttl_seconds; otherwise calls fetch_catalog() for a fresh one.

    A failed fetch is never written into the cache - only a genuine
    SUCCESS result is ever reused. This means an empty/expired/never-
    successful cache always attempts a fresh fetch, and a failure is
    simply returned as-is (whatever fetch_catalog() produced) without
    being cached - so a Coral outage can never get "stuck" being served
    from a stale successful entry from before the outage, and a run of
    failures never poisons the cache for later successful attempts.

    now is only for tests - defaults to the real current time.
    """

    current_time = now or datetime.now(timezone.utc)

    with _cache_lock:
        cached = _cache["result"]
        cached_at = _cache["fetched_at"]

        if cached is not None and cached_at is not None:
            age_seconds = (current_time - cached_at).total_seconds()
            if age_seconds < ttl_seconds:
                return cached

    fresh = fetch_catalog()

    if fresh["status"] == SUCCESS:
        with _cache_lock:
            _cache["result"] = fresh
            _cache["fetched_at"] = current_time

    return fresh


def find_matching_class(classes, query_text):
    """Deterministic (no LLM) matching of query_text against a list of
    normalized class dicts (as returned in fetch_catalog()'s "classes").

    Matching is tiered, strongest signal first, and stops at the first
    tier that produces any match at all:

      1. Exact normalized title match.
      2. The class title appears as a substring of the query, or the
         query appears as a substring of the title (titles shorter than
         4 normalized characters are skipped here, to avoid an
         unhelpfully generic title matching almost anything).
      3. Only if no title match exists at all: a weaker fallback against
         subject or url_slug (slug words treated as space-separated),
         same minimum-length guard.

    At each tier: exactly one match -> SUCCESS with that class. More than
    one -> AMBIGUOUS with every candidate, rather than guessing which one
    was meant. Nothing at any tier -> NOT_FOUND.

    Returns a dict: {"status": ..., "class": <dict or None>,
    "candidates": [...]} - "candidates" is only ever non-empty on
    AMBIGUOUS.
    """

    classes = classes or []
    normalized_query = _normalize_text(query_text)

    if not normalized_query or not classes:
        return {"status": NOT_FOUND, "class": None, "candidates": []}

    exact_title_matches = [
        c for c in classes
        if _normalize_text(c.get("title")) == normalized_query
    ]
    if len(exact_title_matches) == 1:
        return {"status": SUCCESS, "class": exact_title_matches[0], "candidates": []}
    if len(exact_title_matches) > 1:
        return {"status": AMBIGUOUS, "class": None, "candidates": exact_title_matches}

    title_matches = []
    for c in classes:
        title = _normalize_text(c.get("title"))
        if len(title) < 4:
            continue
        if title in normalized_query or normalized_query in title:
            title_matches.append(c)

    if len(title_matches) == 1:
        return {"status": SUCCESS, "class": title_matches[0], "candidates": []}
    if len(title_matches) > 1:
        return {"status": AMBIGUOUS, "class": None, "candidates": title_matches}

    weak_matches = []
    for c in classes:
        subject = _normalize_text(c.get("subject"))
        slug = _normalize_text((c.get("url_slug") or "").replace("-", " "))

        subject_hit = len(subject) >= 4 and subject in normalized_query
        slug_hit = len(slug) >= 4 and slug in normalized_query

        if subject_hit or slug_hit:
            weak_matches.append(c)

    if len(weak_matches) == 1:
        return {"status": SUCCESS, "class": weak_matches[0], "candidates": []}
    if len(weak_matches) > 1:
        return {"status": AMBIGUOUS, "class": None, "candidates": weak_matches}

    return {"status": NOT_FOUND, "class": None, "candidates": []}


# The exact, explicit set of fields a caller is allowed to see as "live
# class context" - deliberately an allow-list, not a blanket copy of the
# class dict. This is what guarantees a field the Coral API has never been
# observed to return (e.g. a seat-availability count) can never leak
# through even if some future response happened to include one under an
# unexpected key: it's simply not in this list.
_LIVE_CONTEXT_FIELDS = (
    "title",
    "subject",
    "pricing",
    "teacher",
    "frequency",
    "session_duration",
    "batch_duration",
    "timezone",
    "start_timestamp",
    "end_timestamp",
    "meeting_type",
    "teaching_type",
    "is_active",
    "is_listed",
    "is_enrollment_allowed",
    "is_free_trial_available",
    "is_coral_unlimited_available",
    "is_ppc_available",
    "url_slug",
)


def build_live_class_context(class_data):
    """Returns only the fields in _LIVE_CONTEXT_FIELDS, and only when
    actually present (and not None) in class_data - never invents a
    missing field, never copies anything outside this explicit allow-list.
    Empty string values for start_timestamp/end_timestamp (as Coral's API
    already returns for ongoing/rolling classes, per the earlier
    investigation) are passed through as-is rather than omitted - an
    empty string is itself real, current information ("no fixed start/end
    date"), not a missing field."""

    if not isinstance(class_data, dict):
        return {}

    return {
        field: class_data[field]
        for field in _LIVE_CONTEXT_FIELDS
        if field in class_data and class_data[field] is not None
    }
