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
    find_matching_classes_for_browsing,
    build_live_class_context,
    build_browsing_class_context,
    _is_class_currently_available,
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
# Class-browsing intent detection - a separate, deterministic detector for
# broad/multi-class questions ("what science classes are currently
# available?"), distinct from detect_current_class_intent() above (which
# is about a current FACT for one already-named class). Two independent
# checks, both plain regex, no LLM, no I/O:
#
#   1. A small set of self-contained phrasings ("which classes do you
#      offer?", "what programs do you have?") matched as one contiguous
#      pattern each.
#   2. A looser "subject term anywhere + offer/availability term anywhere"
#      check, needed because real parent emails rarely phrase this as one
#      tidy sentence - the production email that motivated this feature
#      said "...one of your science classes... what options are currently
#      available?", with "classes" and "available" in different clauses.
#
# Deliberately does NOT include a bare "which" as an offer-term on its own
# (too broad - would false-positive on "Which of my classes is being
# cancelled?", an unrelated support question that also contains "classes").
# ---------------------------------------------------------------------------

_BROWSING_EXPLICIT_PATTERNS = (
    r"\bwhich\s+classes\s+(do\s+you|are)\b",
    r"\bwhich\s+programs\s+(do\s+you|are)\b",
    r"\bwhat\s+classes\s+do\s+you\s+(have|offer)\b",
    r"\bwhat\s+programs\s+do\s+you\s+(have|offer)\b",
)
_BROWSING_EXPLICIT_REGEX = re.compile("|".join(_BROWSING_EXPLICIT_PATTERNS), re.IGNORECASE)

_BROWSING_SUBJECT_TERMS_REGEX = re.compile(
    r"\bclasses\b|\bprograms\b|\bcourses\b|\boptions\b",
    re.IGNORECASE,
)

_BROWSING_OFFER_TERMS_REGEX = re.compile(
    r"\bavailable\b|\boffer(?:ed|ing)?\b|\bcurrently\s+running\b|\bcurrently\s+offered\b|\bshow\s+me\b|\blist\b",
    re.IGNORECASE,
)


def detect_class_browsing_intent(subject, body):
    """True if the email looks like a broad, multi-class browsing
    question rather than a question about one already-named class. Pure
    string matching - no I/O, no LLM. Checked BEFORE
    detect_current_class_intent() in get_live_class_data() below, so a
    genuinely broad question (e.g. "what science classes are currently
    available?") routes to the browsing flow instead of falling into the
    single-class matcher and coming back AMBIGUOUS."""

    text = f"{subject or ''} {body or ''}"

    if _BROWSING_EXPLICIT_REGEX.search(text):
        return True

    return bool(
        _BROWSING_SUBJECT_TERMS_REGEX.search(text)
        and _BROWSING_OFFER_TERMS_REGEX.search(text)
    )


# ---------------------------------------------------------------------------
# Review-reason tokens, in the same short-snake-case style
# process_email.py's own review_reasons list already uses ("classifier",
# "retrieval_error", "safety_block", "generation_error").
# ---------------------------------------------------------------------------

REVIEW_REASON_UNAVAILABLE = "live_class_unavailable"
REVIEW_REASON_AMBIGUOUS = "live_class_ambiguous"
REVIEW_REASON_NOT_FOUND = "live_class_not_found"
REVIEW_REASON_BROWSING_UNAVAILABLE = "live_class_browsing_unavailable"
REVIEW_REASON_BROWSING_NO_MATCH = "live_class_browsing_no_match"


# No "url_slug" entry here - coral_class_catalog.py's _LIVE_CONTEXT_FIELDS
# no longer includes it in the context this renders, so a label for it
# would be permanently dead (never matched by the `if field in context`
# check below). See that constant's own comment for why.
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


# ---------------------------------------------------------------------------
# Browsing prompt formatting - multi-class version of build_prompt_block()
# above. Same "only ever state a fact that's actually listed" contract,
# extended with explicit rules against inventing a class, a day of the
# week, a time of day, or weekly topics - none of which any live field
# ever carries (confirmed against a real fetch of the current catalog).
# ---------------------------------------------------------------------------

# No "url_slug" entry here either - coral_class_catalog.py's
# _BROWSING_CONTEXT_FIELDS no longer includes it, for the same reason.
_BROWSING_FIELD_LABELS = (
    ("title", "Class title"),
    ("subject", "Subject"),
    ("pricing", "Pricing"),
    ("teacher", "Teacher"),
    ("is_enrollment_allowed", "Enrollment currently allowed"),
)

_SCHEDULE_FACT_LABELS = (
    ("frequency", "Meeting frequency"),
    ("session_duration", "Session duration"),
    ("batch_duration", "Program duration"),
    ("enrollment_type", "Enrollment type"),
    ("dates", "Start/end dates"),
    ("start_date", "Start date"),
    ("end_date", "End date"),
)

# How many classes a single browsing reply is allowed to list in detail -
# see build_browsing_prompt_block()'s "and N more" note for anything past
# this. Keeps a broad "what classes do you have?" question from producing
# an unbounded, sprawling reply.
MAX_BROWSING_RESULTS = 6


def build_browsing_prompt_block(class_contexts, total_available_count):
    """Formats a list of build_browsing_class_context() dicts (already
    capped to MAX_BROWSING_RESULTS by the caller) into a ready-to-prepend
    prompt block. Returns None for an empty list, so callers can treat
    that the same as "nothing to add"."""

    if not class_contexts:
        return None

    lines = [
        "LIVE CORAL CLASS LISTING (fetched directly from Coral Academy's "
        "live class catalog for this email - this is the authoritative, "
        "current list of classes; do not add, remove, or rename any "
        "class beyond what is listed below):"
    ]

    for i, context in enumerate(class_contexts, 1):
        lines.append(f"\nClass {i}:")
        for field, label in _BROWSING_FIELD_LABELS:
            if field in context:
                lines.append(f"- {label}: {context[field]}")
        schedule = context.get("schedule") or {}
        for field, label in _SCHEDULE_FACT_LABELS:
            if field in schedule:
                lines.append(f"- {label}: {schedule[field]}")

    remaining = total_available_count - len(class_contexts)
    if remaining > 0:
        lines.append(f"\n(and {remaining} more classes are currently available)")

    lines.append(
        "\nRULES FOR THIS DATA: this class list is authoritative for any "
        "current class-browsing, listing, price, schedule, teacher, or "
        "enrollment/listing-status question. Never invent, infer, or "
        "guess a class that is not listed above. Never invent a day of "
        "the week, a time of day, or weekly topics/lesson agendas - none "
        "of that information is provided here or anywhere in the live "
        "data. Do not use any class description text as schedule data. "
        "If the parent asks for a fact not listed above (for example, "
        "which day or time a class meets, or its weekly topics), say "
        "plainly that this information is not available in the current "
        "data rather than guessing. Do NOT claim seats/spots are "
        "available or state a specific number of open seats - no such "
        "field is provided above. Do NOT claim enrollment is currently "
        "possible just because a class is listed above - only say "
        "enrollment is open if 'Enrollment currently allowed' above "
        "explicitly says so for that class. Keep the response concise: "
        "one short entry per class, not a long paragraph."
    )

    return "\n".join(lines)


def _get_browsing_class_data(subject, body):
    """The browsing counterpart to the single-class flow below -
    fetches the cached live catalog, selects and deduplicates candidate
    classes for a broad question, filters to currently-available ones,
    and builds a capped, live-data-only prompt block. Never touches RAG/
    the knowledge base, and never falls back to it: a catalog failure or
    a genuine zero-match result both come back as requires_review=True
    with context_text=None, the same "never silently substitute stale
    data as current" contract the single-class flow already uses."""

    catalog_result = get_cached_catalog()

    if catalog_result["status"] != SUCCESS:
        return {
            "needed": True,
            "context_text": None,
            "requires_review": True,
            "review_reason": REVIEW_REASON_BROWSING_UNAVAILABLE,
        }

    query_text = f"{subject or ''} {body or ''}"
    candidates = find_matching_classes_for_browsing(catalog_result["classes"], query_text)
    available = [c for c in candidates if _is_class_currently_available(c)]

    if not available:
        return {
            "needed": True,
            "context_text": None,
            "requires_review": True,
            "review_reason": REVIEW_REASON_BROWSING_NO_MATCH,
        }

    trimmed = available[:MAX_BROWSING_RESULTS]
    class_contexts = [build_browsing_class_context(c) for c in trimmed]

    return {
        "needed": True,
        "context_text": build_browsing_prompt_block(class_contexts, len(available)),
        "requires_review": False,
        "review_reason": None,
    }


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

    # Checked first: a genuinely broad/multi-class question (e.g. "what
    # science classes are currently available?") is routed to the
    # browsing flow and never falls through to the single-class matcher
    # below - which would otherwise resolve multiple weakly-matching
    # classes to AMBIGUOUS and force review instead of answering the
    # question the parent actually asked.
    if detect_class_browsing_intent(subject, body):
        return _get_browsing_class_data(subject, body)

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
