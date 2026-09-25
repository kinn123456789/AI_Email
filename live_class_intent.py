#live_class_intent.py
"""Phase 2 of the live Coral class-data feature: deterministic detection
of whether a PARENT email is asking for a current class-specific fact
(price, schedule, teacher, enrollment/listing status), plus the small
orchestration that turns that into either a ready-to-use prompt block or
an explicit review requirement - never a silent fallback to stale RAG
data presented as current.

This module is the only thing process_email.py's parent pipeline needs to
call. It builds entirely on Phase 1 (coral_class_catalog.py) without
modifying it - fetching, caching, and matching all stay there; this file
only adds intent detection and prompt formatting on top.

No LLM call anywhere in this file - detection is plain regex/keyword
matching, and the only network call this can ever trigger is
coral_class_catalog.get_cached_catalog()'s single, cached, unauthenticated
GET to Coral's public API.
"""

import re

from coral_class_catalog import (
    get_cached_catalog,
    find_matching_class,
    build_live_class_context,
    SUCCESS,
    AMBIGUOUS,
    NOT_FOUND,
)


# ---------------------------------------------------------------------------
# Deterministic current-fact intent detection. Deliberately simple, plain
# keyword/phrase matching - no NLP, no LLM. Tuned against the exact
# positive/negative examples this feature was specced against: matches
# price, schedule, teacher, and enrollment/availability questions, and
# does NOT match general class-content questions (how it works, what's
# taught, age group, homework, refund policy).
# ---------------------------------------------------------------------------

_INTENT_PATTERNS = (
    r"\bhow much\b",
    r"\bprice\b",
    r"\bprices\b",
    r"\bpricing\b",
    r"\bcosts?\b",
    r"\bfees?\b",
    r"\bschedule\b",
    r"\bwhat\s+days?\b",
    r"\bwhich\s+days?\b",
    r"\bwhat\s+times?\b",
    r"\bhow often\b",
    r"\bfrequency\b",
    r"\bwho\s+teaches\b",
    r"\bwho\s+is\s+the\s+teacher\b",
    r"\bwho'?s\s+the\s+teacher\b",
    r"\bwhich\s+teacher\b",
    r"\binstructor\b",
    r"\benroll(ment)?\b",
    r"\bsign\s+up\b",
    r"\bavailab(le|ility)\b",
    r"\bstill\s+running\b",
    r"\bstill\s+offered\b",
    r"\bcurrently\s+running\b",
    r"\bcurrently\s+offered\b",
)

_INTENT_REGEX = re.compile("|".join(_INTENT_PATTERNS), re.IGNORECASE)


def detect_current_class_intent(subject, body):
    """True if the email's subject/body contains any current-fact
    keyword/phrase (price, schedule, teacher, enrollment/availability).
    Pure string matching - no I/O, no LLM, effectively free to call on
    every email."""

    text = f"{subject or ''} {body or ''}"
    return bool(_INTENT_REGEX.search(text))


# ---------------------------------------------------------------------------
# Review-reason tokens, in the same short-snake-case style
# process_email.py's own review_reasons list already uses ("classifier",
# "retrieval_error", "safety_block", "generation_error").
# ---------------------------------------------------------------------------

REVIEW_REASON_UNAVAILABLE = "live_class_unavailable"
REVIEW_REASON_AMBIGUOUS = "live_class_ambiguous"
REVIEW_REASON_NOT_FOUND = "live_class_not_found"


_FIELD_LABELS = (
    ("title", "Class title"),
    ("subject", "Subject"),
    ("pricing", "Pricing"),
    ("teacher", "Teacher"),
    ("frequency", "Meeting frequency"),
    ("session_duration", "Session duration"),
    ("batch_duration", "Program duration"),
    ("timezone", "Timezone"),
    ("start_timestamp", "Start date/time (empty means no fixed start date - ongoing/rolling enrollment)"),
    ("end_timestamp", "End date/time (empty means no fixed end date)"),
    ("meeting_type", "Meeting type"),
    ("teaching_type", "Teaching type"),
    ("is_active", "Currently active"),
    ("is_listed", "Currently listed/published"),
    ("is_enrollment_allowed", "Enrollment currently allowed"),
    ("is_free_trial_available", "Free trial currently available"),
    ("is_coral_unlimited_available", "Available on Coral Unlimited"),
    ("is_ppc_available", "Available on Pay Per Class"),
    ("url_slug", "Class URL slug"),
)


def build_prompt_block(context):
    """Formats build_live_class_context()'s already-filtered dict into a
    ready-to-prepend prompt block, clearly labeled and carrying its own
    usage rules - only fields actually present in `context` are listed
    (never invented), and the block itself instructs the model never to
    claim a fact beyond what's listed, never to claim seat availability
    (no such field is ever in `context` - see coral_class_catalog.py's
    _LIVE_CONTEXT_FIELDS), and never to treat "this class exists" as
    "enrollment is open" without checking is_enrollment_allowed.

    Returns None for an empty/falsy context, so callers can treat that
    the same as "no live data to add"."""

    if not context:
        return None

    lines = [
        "LIVE CORAL CLASS DATA (fetched directly from Coral Academy's live "
        "class catalog for this email - more current than anything else "
        "below, and authoritative for any current price, schedule, "
        "teacher, or enrollment/listing-status question):"
    ]

    for field, label in _FIELD_LABELS:
        if field in context:
            lines.append(f"- {label}: {context[field]}")

    lines.append(
        "\nRULES FOR THIS DATA: prefer it over any older/general knowledge "
        "for current price/schedule/teacher/enrollment/listing-status "
        "facts. Only state a fact that actually appears above - never "
        "invent, infer, or guess a value for a field not listed here. Do "
        "NOT claim seats/spots are available or state a specific number of "
        "open seats - no such field is provided above. Do NOT claim "
        "enrollment is currently possible just because the class is "
        "listed above - only say enrollment is open if 'Enrollment "
        "currently allowed' above explicitly says so."
    )

    return "\n".join(lines)


def get_live_class_data(subject, body):
    """The single entry point the parent pipeline (process_email.py)
    calls. Runs entirely inertly (no Coral call at all) unless
    detect_current_class_intent() finds a current-fact question - so a
    normal email that doesn't need this pays literally nothing beyond one
    fast regex check.

    Returns a dict:
        needed:          bool - whether this looked like a current-fact
                          question at all
        context_text:    a ready-to-pass prompt block (see
                          build_prompt_block()), or None
        requires_review: bool
        review_reason:   one of the REVIEW_REASON_* tokens above, or None

    Never silently substitutes stale RAG-style data as "current" - any
    failure to safely resolve exactly one live, matching class for a
    detected current-fact question comes back as requires_review=True
    with context_text=None, not a guess.
    """

    if not detect_current_class_intent(subject, body):
        return {
            "needed": False,
            "context_text": None,
            "requires_review": False,
            "review_reason": None,
        }

    catalog_result = get_cached_catalog()

    if catalog_result["status"] != SUCCESS:
        return {
            "needed": True,
            "context_text": None,
            "requires_review": True,
            "review_reason": REVIEW_REASON_UNAVAILABLE,
        }

    query_text = f"{subject or ''} {body or ''}"
    match_result = find_matching_class(catalog_result["classes"], query_text)

    if match_result["status"] == AMBIGUOUS:
        return {
            "needed": True,
            "context_text": None,
            "requires_review": True,
            "review_reason": REVIEW_REASON_AMBIGUOUS,
        }

    if match_result["status"] == NOT_FOUND:
        return {
            "needed": True,
            "context_text": None,
            "requires_review": True,
            "review_reason": REVIEW_REASON_NOT_FOUND,
        }

    context = build_live_class_context(match_result["class"])

    return {
        "needed": True,
        "context_text": build_prompt_block(context),
        "requires_review": False,
        "review_reason": None,
    }
