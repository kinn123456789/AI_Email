# subscription_cancel.py

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo
from dateutil.parser import isoparse
from openai import OpenAI

from supabase import create_client

from supabase_client import supabase
from database import get_connection, db_pool
from psycopg2.extras import RealDictCursor


def _new_supabase_client():
    """A fresh Supabase client for use inside a worker thread. The shared
    global `supabase` client's underlying HTTP/2 connection isn't safe for
    concurrent requests from multiple threads (causes ConnectionTerminated
    errors), so each concurrent branch in _fetch_all_subscription_rows gets
    its own isolated client instead.

    IMPORTANT: every client this returns wraps a real httpx.Client with its
    own connection pool. It must be closed with _close_client() after use —
    this function used to be called dozens of times per minute (once per
    query, more with chunking) with nothing ever closing the result, which
    was a real, confirmed memory leak contributing to repeated OOM kills in
    production on 2026-07-25."""

    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SECRET_KEY")
    )


def _close_client(client):
    """Closes the underlying httpx connection for a client created by
    _new_supabase_client(). Never call this on the shared global `supabase`
    client — only ever on fresh instances from _new_supabase_client()."""

    try:
        client.postgrest.session.close()
    except Exception as e:
        print("Failed to close Supabase client:", e)


_PAGE_SIZE = 1000  # PostgREST silently caps unbounded responses at 1000 rows
_IN_CHUNK_SIZE = 400  # .in_() URL-encoded queries start failing (400 Bad
                      # Request) somewhere between 500-700 UUIDs — verified
                      # empirically; 400 stays comfortably under that.


def _fetch_all_paginated(build_query, client):
    """build_query(client) -> a fresh Supabase query builder (filters
    applied, not yet ranged/executed) — called once per page rather than
    reused, since reusing a builder across multiple .range() calls isn't
    guaranteed safe. Needed because PostgREST silently caps unbounded
    responses at _PAGE_SIZE rows, which used to be invisible here (return
    sets were always well under 1000) until "all statuses" pushed the
    Subscriptions fetch past it."""

    all_rows = []
    offset = 0

    while True:
        page = (
            build_query(client)
            .range(offset, offset + _PAGE_SIZE - 1)
            .execute()
            .data
        )
        all_rows.extend(page)

        if len(page) < _PAGE_SIZE:
            break

        offset += _PAGE_SIZE

    return all_rows


def _fetch_in_chunks(table, select_cols, id_column, ids, filters=None, max_workers=3):
    """Runs `.in_(id_column, ids)` in parallel chunks of _IN_CHUNK_SIZE
    (each with its own isolated client), merging results — PostgREST's
    URL-encoded IN(...) queries fail outright somewhere around 500-700
    UUIDs. For small id lists this is just one chunk / one request, so it's
    safe to use everywhere this pattern occurs, not just where it's
    currently known to be large.

    filters: optional fn(query) -> query for additional .eq()/etc filters
    applied to every chunk."""

    ids = list(ids)

    if not ids:
        return []

    chunks = [
        ids[i:i + _IN_CHUNK_SIZE]
        for i in range(0, len(ids), _IN_CHUNK_SIZE)
    ]

    def fetch_chunk(chunk):
        client = _new_supabase_client()
        try:
            query = (
                client
                .table(table)
                .select(select_cols)
                .in_(id_column, chunk)
            )
            if filters:
                query = filters(query)
            return query.execute().data
        finally:
            _close_client(client)

    if len(chunks) == 1:
        return fetch_chunk(chunks[0])

    all_rows = []

    with ThreadPoolExecutor(max_workers=min(max_workers, len(chunks))) as executor:
        for rows in executor.map(fetch_chunk, chunks):
            all_rows.extend(rows)

    return all_rows

_ai_client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)


def _new_ai_client():
    """A fresh OpenAI/OpenRouter client for concurrent backfill use — same
    isolation reasoning as _new_supabase_client, so parallel draft generation
    doesn't share one client's connection across threads."""

    return OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )


_PARENT_PLACEHOLDER = "[PARENT_NAME]"
_LEARNER_PLACEHOLDER = "[STUDENT_NAME]"


def generate_reengagement_email(row, ai_client=None):

    ai_client = ai_client or _ai_client

    parent_name = row.get("parent_name") or "there"
    learner_name = row.get("learner_name") or "your child"
    sessions_attended = row.get("sessions_attended") or 0

    if row["subscription_status"] == "trial_expired":
        subject = f"We'd love to have {learner_name} back at Coral Academy"
        redacted_context = f"{_LEARNER_PLACEHOLDER}'s free trial expired without continuing to a paid membership."
    else:
        subject = f"We miss {learner_name} at Coral Academy"
        redacted_context = f"{_LEARNER_PLACEHOLDER}'s subscription ({row.get('subscription_type')}) was recently cancelled."

    redacted_session_note = (
        f"{_LEARNER_PLACEHOLDER} attended {sessions_attended} class session(s) before this."
        if sessions_attended > 0
        else ""
    )

    # Real parent/learner names never leave the process — the AI only ever
    # sees the placeholder tokens, and the real names are substituted back
    # in after the response comes back (see below).
    prompt = f"""
Write a warm, professional re-engagement email.

Parent name: {_PARENT_PLACEHOLDER}
Learner name: {_LEARNER_PLACEHOLDER}

{redacted_context}
{redacted_session_note}

Gently invite the parent to come back and continue learning with Coral Academy.

Ask if there was anything that didn't work well, and offer to help.

Keep it around 100 words.

Return ONLY the email body.

{_PARENT_PLACEHOLDER} and {_LEARNER_PLACEHOLDER} are literal placeholder
tokens — reproduce them EXACTLY as written, including the square brackets,
everywhere a name would go. Do not translate, rename, or remove them.

Do not include:
- Subject
- Markdown
- Bullet points
- Explanations
"""

    try:
        response = ai_client.chat.completions.create(
            model="gpt-5-nano",
            messages=[
                {
                    "role": "system",
                    "content": """
                    You are Coral Academy's parent communication assistant.

                    Write warm, professional and trustworthy emails to parents.

                    Never exaggerate. Never make promises you cannot verify.

                    Always end the email with:

                    Warm regards,

                    Coral Academy
                    """
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        body = response.choices[0].message.content.strip()
        body = body.replace(_PARENT_PLACEHOLDER, parent_name).replace(_LEARNER_PLACEHOLDER, learner_name)
        return subject, body

    except Exception as e:
        print("AI Error:", e)

        return subject, f"""
Hi {parent_name},

{redacted_context.replace(_LEARNER_PLACEHOLDER, learner_name)} We'd love to have {learner_name} continue learning with us.

If anything didn't work well for you, please reply and let us know — we're happy to help.

Warm regards,

Coral Academy
"""


def _format_ist(iso_string):

    if not iso_string:
        return None

    return (
        isoparse(iso_string)
        .astimezone(ZoneInfo("Asia/Kolkata"))
        .strftime("%b %-d, %Y %-I:%M %p")
    )


def get_subscription_types():

    response = (
        supabase
        .table("Subscriptions")
        .select("subscription_type")
        .execute()
    )

    types = {
        row["subscription_type"]
        for row in response.data
        if row["subscription_type"]
    }

    types.add("free_trial_pass")

    return sorted(types)


def get_subscription_statuses():
    """All distinct subscription_status values, plus the synthetic
    "trial_expired" pseudo-status used for expired-trial rows — for the
    dashboard's status filter dropdown."""

    response = (
        supabase
        .table("Subscriptions")
        .select("subscription_status")
        .execute()
    )

    statuses = {
        row["subscription_status"]
        for row in response.data
        if row["subscription_status"]
    }

    statuses.add("trial_expired")

    return sorted(statuses)


def _get_expired_unconverted_trials(client=None, since=None):
    """
    Trial passes that expired without the learner ever subscribing —
    same "converted" check trial_followup.py uses, but over all history
    (not just today's expirations) since this is a cumulative list.

    Accepts an optional client so callers running this concurrently
    alongside other queries (see _fetch_all_subscription_rows) can pass
    an isolated client instead of sharing the global one — the shared
    client's underlying HTTP/2 connection isn't safe for concurrent use
    from multiple threads.

    since: optional ISO timestamp lower bound on expiry_at, so the default
    (recent-only) dashboard view doesn't have to fetch every trial that's
    ever expired — pass None for the full, unbounded history.
    """

    client = client or supabase
    now = datetime.now(timezone.utc)

    def build_trial_query(c):
        query = (
            c
            .table("FreeTrialPass")
            .select(
                "free_trial_pass_id,"
                "parent_id,"
                "enrollment_ids,"
                "expiry_at,"
                "enrollment_start_timestamp"
            )
            .lte("expiry_at", now.isoformat())
        )

        if since:
            query = query.gte("expiry_at", since)

        return query

    trials = _fetch_all_paginated(build_trial_query, client)

    if not trials:
        return []

    enrollment_ids = list({
        eid
        for trial in trials
        for eid in (trial["enrollment_ids"] or [])
    })

    if not enrollment_ids:
        return []

    enrollment_rows = _fetch_in_chunks(
        "Enrollments", "enrollment_id, learner_id", "enrollment_id", enrollment_ids
    )

    enrollment_lookup = {
        str(row["enrollment_id"]): row
        for row in enrollment_rows
    }

    learner_ids = list({
        str(row["learner_id"])
        for row in enrollment_rows
    })

    if not learner_ids:
        return []

    # Any subscription at all (regardless of current status) means the
    # learner converted at some point — exclude them so they aren't
    # double-counted alongside the real Subscriptions-cancelled rows.
    subscription_rows = _fetch_in_chunks(
        "Subscriptions", "learner_id, subscribed_at", "learner_id", learner_ids
    )

    subscriptions_by_learner = {}

    for row in subscription_rows:
        subscriptions_by_learner.setdefault(
            str(row["learner_id"]), []
        ).append(row)

    candidates = []
    seen = set()

    for trial in trials:

        start = trial["enrollment_start_timestamp"]
        start = isoparse(start) if isinstance(start, str) and start else None

        for enrollment_id in trial["enrollment_ids"] or []:

            enrollment = enrollment_lookup.get(str(enrollment_id))

            if not enrollment:
                continue

            learner_id = str(enrollment["learner_id"])

            if (trial["free_trial_pass_id"], learner_id) in seen:
                continue

            converted = False

            for subscription in subscriptions_by_learner.get(learner_id, []):

                subscribed_at = subscription["subscribed_at"]

                if subscribed_at and start and isoparse(subscribed_at) >= start:
                    converted = True
                    break

            if converted:
                continue

            seen.add((trial["free_trial_pass_id"], learner_id))

            candidates.append({
                "learner_id": learner_id,
                "parent_id": trial["parent_id"],
                "expiry_at": trial["expiry_at"],
                "free_trial_pass_id": trial["free_trial_pass_id"],
            })

    return candidates


_cache = {"rows": None, "loaded_at": 0}
_CACHE_TTL_SECONDS = 60
_DEFAULT_WINDOW_MONTHS = 3

_all_time_cache = {"rows": None, "loaded_at": 0}
_ALL_TIME_CACHE_TTL_SECONDS = 300


def _default_window_cutoff():
    return (
        datetime.now(timezone.utc) - relativedelta(months=_DEFAULT_WINDOW_MONTHS)
    ).isoformat()


def refresh_subscription_cache():
    """Rebuild the cached base dataset (Subscriptions/FreeTrialPass joined
    against Learners/Users/EmailDeliveryStatus/SessionInteraction), bounded
    to the last _DEFAULT_WINDOW_MONTHS. Meant to be called proactively from
    scheduler.py every minute, so page loads read an already-warm cache
    instead of triggering the rebuild themselves. Older rows are still
    reachable via the separate, on-demand all-time view (see
    _get_all_time_base_rows) — they just aren't kept warm in this cache."""

    _cache["rows"] = _fetch_all_subscription_rows(since=_default_window_cutoff())
    _cache["loaded_at"] = time.time()

    return _cache["rows"]


def _get_base_rows():
    """Lazy fallback for the case the scheduler hasn't populated the cache
    yet (e.g. right after deploy) — normally this just reads the cache the
    scheduler already refreshed."""

    cache_age = time.time() - _cache["loaded_at"]

    if _cache["rows"] is None or cache_age > _CACHE_TTL_SECONDS:
        return refresh_subscription_cache()

    return _cache["rows"]


def _get_all_time_base_rows():
    """On-demand full-history dataset (no date bound) — deliberately not
    kept warm by the scheduler since it's rarely requested and only grows
    over time. Cached briefly so repeated clicks within a session don't
    each re-pay the full, growing fetch cost."""

    cache_age = time.time() - _all_time_cache["loaded_at"]

    if _all_time_cache["rows"] is None or cache_age > _ALL_TIME_CACHE_TTL_SECONDS:
        _all_time_cache["rows"] = _fetch_all_subscription_rows(since=None)
        _all_time_cache["loaded_at"] = time.time()

    return _all_time_cache["rows"]


def _build_class_titles_lookup(learner_ids):
    """learner_id -> "Title1, Title2" for their current (is_latest) classes.
    One shared lookup for both subscription and trial rows, since both key
    on learner_id via the same Enrollments -> Batches -> Classes chain.
    Uses _fetch_in_chunks throughout, which already isolates its own
    clients per request, so no client needs to be passed in here."""

    if not learner_ids:
        return {}

    enrollments = _fetch_in_chunks(
        "Enrollments", "learner_id, batch_id", "learner_id", learner_ids,
        filters=lambda q: q.eq("is_latest", True)
    )

    if not enrollments:
        return {}

    batch_ids = list({
        e["batch_id"]
        for e in enrollments
        if e["batch_id"]
    })

    if not batch_ids:
        return {}

    batch_rows = _fetch_in_chunks(
        "Batches", "batch_id, class_id", "batch_id", batch_ids
    )

    class_id_by_batch = {
        b["batch_id"]: b["class_id"]
        for b in batch_rows
    }

    class_ids = list({
        cid
        for cid in class_id_by_batch.values()
        if cid
    })

    if not class_ids:
        return {}

    class_rows = _fetch_in_chunks(
        "Classes", "class_id, title", "class_id", class_ids
    )

    title_by_class = {
        c["class_id"]: c["title"]
        for c in class_rows
    }

    titles_by_learner = {}

    for e in enrollments:

        class_id = class_id_by_batch.get(e["batch_id"])
        title = title_by_class.get(class_id)

        if not title:
            continue

        learner_id = e["learner_id"]
        titles_by_learner.setdefault(learner_id, [])

        if title not in titles_by_learner[learner_id]:
            titles_by_learner[learner_id].append(title)

    return {
        learner_id: ", ".join(titles)
        for learner_id, titles in titles_by_learner.items()
    }


def _fetch_subscriptions(client, since=None):
    """All Subscriptions rows regardless of status — canceled_at is null for
    most rows (falls back to updated_at — see below), so the since bound has
    to match on whichever is populated. Paginated since this can exceed 1000
    rows once every status (not just "canceled") is included."""

    def build(c):
        query = (
            c
            .table("Subscriptions")
            .select(
                "id,"
                "learner_id,"
                "subscription_type,"
                "subscription_status,"
                "subscribed_at,"
                "canceled_at,"
                "updated_at"
            )
        )

        if since:
            query = query.or_(
                f"canceled_at.gte.{since},"
                f"and(canceled_at.is.null,updated_at.gte.{since})"
            )

        return query

    return _fetch_all_paginated(build, client)


def _fetch_all_subscription_rows(since=None):
    """The expensive part: fetch + join Subscriptions/FreeTrialPass against
    Learners/Users/EmailDeliveryStatus/SessionInteraction. Returns the full,
    unpaginated row list for everything since the given cutoff (or all time
    if since is None) — this is what gets cached."""

    # Subscriptions and the trial-candidates lookup don't depend on each
    # other, and used to run concurrently here — but every concurrent
    # Supabase connection adds to peak memory at the exact moment this
    # runs (every 60s, forever), and that peak was contributing to
    # repeated OOM kills on Render's 512Mi free tier even after fixing the
    # scheduling collision and the connection leak. Running sequentially
    # trades some speed (back toward the pre-optimization ~7s total) for
    # meaningfully lower peak memory — one connection open at a time here
    # instead of two.
    subscriptions_client = _new_supabase_client()
    try:
        subscriptions = _fetch_subscriptions(subscriptions_client, since)
    finally:
        _close_client(subscriptions_client)

    trials_client = _new_supabase_client()
    try:
        trial_candidates = _get_expired_unconverted_trials(trials_client, since)
    finally:
        _close_client(trials_client)

    if not subscriptions and not trial_candidates:
        return []

    learner_ids = list({
        s["learner_id"]
        for s in subscriptions
        if s["learner_id"]
    } | {
        t["learner_id"]
        for t in trial_candidates
        if t["learner_id"]
    })

    # These four all depend only on learner_ids, not on each other. Capped
    # at 2 concurrent workers (was 4) — same peak-memory reasoning as Stage
    # A above: fewer simultaneous open connections during this once-a-minute
    # cycle, at the cost of this stage taking longer. Each uses
    # _fetch_in_chunks, which internally parallel-chunks + isolates clients
    # when learner_ids is large (see _fetch_in_chunks for why that's needed).
    with ThreadPoolExecutor(max_workers=2) as executor:
        learner_future = executor.submit(
            _fetch_in_chunks, "Learners", "learner_id, parent_id", "learner_id", learner_ids
        )
        class_titles_future = executor.submit(_build_class_titles_lookup, learner_ids)
        learner_name_future = executor.submit(
            _fetch_in_chunks, "Users", "user_id, name", "user_id", learner_ids
        )
        session_future = executor.submit(
            _fetch_in_chunks, "SessionInteraction", "learner_id", "learner_id", learner_ids,
            lambda q: q.eq("did_attend", True)
        )

        learner_rows = learner_future.result()
        class_titles_by_learner = class_titles_future.result()
        learner_name_rows = learner_name_future.result()
        session_rows = session_future.result()

    parent_by_learner = {
        row["learner_id"]: row["parent_id"]
        for row in learner_rows
    }

    parent_ids = list({
        pid
        for pid in parent_by_learner.values()
        if pid
    } | {
        t["parent_id"]
        for t in trial_candidates
        if t["parent_id"]
    })

    learner_name_lookup = {
        row["user_id"]: row["name"]
        for row in learner_name_rows
    }

    parent_email_lookup = {}

    if parent_ids:

        email_rows = _fetch_in_chunks(
            "EmailDeliveryStatus", "parent_id, parent_name, parent_email, created_at", "parent_id", parent_ids,
            lambda q: q.not_.is_("parent_email", "null").order("created_at", desc=True)
        )

        for row in email_rows:

            pid = row["parent_id"]

            # First occurrence per parent is the most recent, since rows
            # are ordered by created_at DESC within each chunk, and each
            # parent_id is entirely contained in one chunk (chunking splits
            # the id list, not the result rows).
            if pid not in parent_email_lookup:
                parent_email_lookup[pid] = row

    session_counts = {}

    for row in session_rows:

        learner_id = row["learner_id"]
        session_counts[learner_id] = session_counts.get(learner_id, 0) + 1

    results = []

    for s in subscriptions:

        learner_id = s["learner_id"]
        parent_id = parent_by_learner.get(learner_id)
        parent_info = parent_email_lookup.get(parent_id, {})

        # canceled_at is null for most rows (only ~25% populated) —
        # fall back to updated_at (when the status last changed) so
        # sorting/filtering/display has a usable date for every row.
        effective_canceled_at = s["canceled_at"] or s["updated_at"]

        results.append({
            "row_key": f"sub:{s['id']}",
            "subscription_id": s["id"],
            "learner_id": learner_id,
            "learner_name": learner_name_lookup.get(learner_id),
            "subscription_type": s["subscription_type"],
            "subscription_status": s["subscription_status"],
            "subscribed_at": s["subscribed_at"],
            "canceled_at": effective_canceled_at,
            "canceled_at_display": _format_ist(effective_canceled_at),
            "parent_id": parent_id,
            "parent_name": parent_info.get("parent_name"),
            "parent_email": parent_info.get("parent_email"),
            "sessions_attended": session_counts.get(learner_id, 0),
            "class_title": class_titles_by_learner.get(learner_id)
        })

    for t in trial_candidates:

        learner_id = t["learner_id"]
        parent_id = t["parent_id"]
        parent_info = parent_email_lookup.get(parent_id, {})

        results.append({
            "row_key": f"trial:{t['free_trial_pass_id']}",
            "subscription_id": None,
            "learner_id": learner_id,
            "learner_name": learner_name_lookup.get(learner_id),
            "subscription_type": "free_trial_pass",
            "subscription_status": "trial_expired",
            "subscribed_at": None,
            "canceled_at": t["expiry_at"],
            "canceled_at_display": _format_ist(t["expiry_at"]),
            "parent_id": parent_id,
            "parent_name": parent_info.get("parent_name"),
            "parent_email": parent_info.get("parent_email"),
            "sessions_attended": session_counts.get(learner_id, 0),
            "class_title": class_titles_by_learner.get(learner_id)
        })

    return results


def _filter_sort_paginate(results, search, date_from, date_to, status, page, page_size):
    """Shared by get_cancelled_subscriptions and get_all_time_cancelled_subscriptions
    — applies dismissed-row filtering, status/search/date range filtering,
    sort and pagination fresh on every call. These are cheap regardless of
    dataset size, unlike the expensive Supabase joins that produce `results`."""

    results = list(results)

    dismissed_keys = get_dismissed_row_keys()

    results = [
        r for r in results
        if r["row_key"] not in dismissed_keys
    ]

    if status:
        results = [
            r for r in results
            if r["subscription_status"] == status
        ]

    if search:
        search_lower = search.lower()
        results = [
            r for r in results
            if search_lower in (r["parent_name"] or "").lower()
            or search_lower in (r["parent_email"] or "").lower()
            or search_lower in (r["subscription_type"] or "").lower()
            or search_lower in (r["learner_name"] or "").lower()
            or search_lower in (r["class_title"] or "").lower()
        ]

    if date_from:
        results = [
            r for r in results
            if r["canceled_at"] and r["canceled_at"][:10] >= date_from
        ]

    if date_to:
        results = [
            r for r in results
            if r["canceled_at"] and r["canceled_at"][:10] <= date_to
        ]

    results.sort(
        key=lambda r: r["canceled_at"] or "",
        reverse=True
    )

    total = len(results)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * page_size

    return {
        "rows": results[offset:offset + page_size],
        "total": total,
        "page": page,
        "total_pages": total_pages,
    }


def get_cancelled_subscriptions(search=None, date_from=None, date_to=None, status=None, page=1, page_size=50):
    """Default (last _DEFAULT_WINDOW_MONTHS) view — reads the cache the
    scheduler keeps warm every minute (see _get_base_rows/refresh_subscription_cache)."""

    return _filter_sort_paginate(_get_base_rows(), search, date_from, date_to, status, page, page_size)


def get_all_time_cancelled_subscriptions(search=None, date_from=None, date_to=None, status=None, page=1, page_size=50):
    """Full-history view, deliberately separate from the default cache —
    see _get_all_time_base_rows for why. Slower, especially the first call
    after the 5-minute cache expires, since it fetches every cancellation
    and expired trial ever, not just the recent window."""

    return _filter_sort_paginate(_get_all_time_base_rows(), search, date_from, date_to, status, page, page_size)


def get_dismissed_row_keys():

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT row_key FROM subscription_cancel_dismissed")
        return {row[0] for row in cursor.fetchall()}

    finally:
        cursor.close()
        db_pool.putconn(conn)


def dismiss_subscription_rows(rows):
    """rows: list of dicts with row_key, subscription_type, subscription_status,
    parent_name, parent_email, learner_name, canceled_at_display, class_title."""

    conn = get_connection()
    cursor = conn.cursor()

    try:
        for row in rows:
            cursor.execute("""
                INSERT INTO subscription_cancel_dismissed
                (row_key, subscription_type, subscription_status, parent_name, parent_email, learner_name, canceled_at_display, class_title)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (row_key) DO NOTHING
            """, (
                row["row_key"],
                row.get("subscription_type"),
                row.get("subscription_status"),
                row.get("parent_name"),
                row.get("parent_email"),
                row.get("learner_name"),
                row.get("canceled_at_display"),
                row.get("class_title"),
            ))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def get_dismissed_subscriptions():

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT * FROM subscription_cancel_dismissed
            ORDER BY dismissed_at DESC
        """)
        return cursor.fetchall()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def restore_subscription_rows(row_keys):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            DELETE FROM subscription_cancel_dismissed
            WHERE row_key = ANY(%s)
        """, (row_keys,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def _fetch_learner_name(learner_id, client):
    response = client.table("Users").select("name").eq("user_id", learner_id).execute()
    return response.data[0]["name"] if response.data else None


def _fetch_parent_info(parent_id, client):
    if not parent_id:
        return None, None

    response = (
        client
        .table("EmailDeliveryStatus")
        .select("parent_name, parent_email, created_at")
        .eq("parent_id", parent_id)
        .not_.is_("parent_email", "null")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]["parent_name"], response.data[0]["parent_email"]

    return None, None


def _fetch_session_count(learner_id, client):
    response = (
        client
        .table("SessionInteraction")
        .select("session_interaction_id")
        .eq("learner_id", learner_id)
        .eq("did_attend", True)
        .execute()
    )
    return len(response.data)


def _build_row(learner_id, parent_id, subscription_id, subscription_type,
               subscription_status, subscribed_at, canceled_at, row_key):
    """These 4 lookups are all independent given learner_id/parent_id, so
    run them concurrently — same reasoning (and isolated-client pattern) as
    _fetch_all_subscription_rows. This is what makes single-row detail
    pages (e.g. clicking into a re-engagement email) fast instead of paying 4+
    sequential round trips."""

    learner_name_client = _new_supabase_client()
    parent_info_client = _new_supabase_client()
    session_count_client = _new_supabase_client()

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            learner_name_future = executor.submit(_fetch_learner_name, learner_id, learner_name_client)
            parent_info_future = executor.submit(_fetch_parent_info, parent_id, parent_info_client)
            session_count_future = executor.submit(_fetch_session_count, learner_id, session_count_client)
            class_titles_future = executor.submit(_build_class_titles_lookup, [learner_id])

            learner_name = learner_name_future.result()
            parent_name, parent_email = parent_info_future.result()
            sessions_attended = session_count_future.result()
            class_title = class_titles_future.result().get(learner_id)
    finally:
        _close_client(learner_name_client)
        _close_client(parent_info_client)
        _close_client(session_count_client)

    return {
        "row_key": row_key,
        "subscription_id": subscription_id,
        "learner_id": learner_id,
        "learner_name": learner_name,
        "subscription_type": subscription_type,
        "subscription_status": subscription_status,
        "subscribed_at": subscribed_at,
        "canceled_at": canceled_at,
        "canceled_at_display": _format_ist(canceled_at),
        "parent_id": parent_id,
        "parent_name": parent_name,
        "parent_email": parent_email,
        "sessions_attended": sessions_attended,
        "class_title": class_title
    }


def get_subscription_row(row_key):
    """Look up a single non-dismissed row by its row_key, fetching only
    that one row's data instead of the whole ~500+ row dataset."""

    kind, _, raw_id = row_key.partition(":")

    if kind == "sub":

        response = (
            supabase
            .table("Subscriptions")
            .select("id, learner_id, subscription_type, subscription_status, subscribed_at, canceled_at, updated_at")
            .eq("id", raw_id)
            .execute()
        )

        if not response.data:
            return None

        s = response.data[0]
        learner_id = s["learner_id"]

        learner_response = (
            supabase.table("Learners").select("parent_id").eq("learner_id", learner_id).execute()
        )
        parent_id = learner_response.data[0]["parent_id"] if learner_response.data else None

        return _build_row(
            learner_id, parent_id, s["id"], s["subscription_type"],
            s["subscription_status"], s["subscribed_at"],
            s["canceled_at"] or s["updated_at"], row_key
        )

    if kind == "trial":

        response = (
            supabase
            .table("FreeTrialPass")
            .select("free_trial_pass_id, parent_id, expiry_at, enrollment_ids, enrollment_start_timestamp")
            .eq("free_trial_pass_id", raw_id)
            .execute()
        )

        if not response.data:
            return None

        trial = response.data[0]

        # Dismissed/sent tracking only keys on the trial pass, not the
        # learner, so re-derive the matching (non-converted) learner the
        # same way _get_expired_unconverted_trials() does — but scoped to
        # just this one trial's enrollment_ids instead of calling that
        # function unbounded, which would re-scan every trial ever.
        learner_id = _resolve_unconverted_trial_learner(trial)

        if not learner_id:
            return None

        return _build_row(
            learner_id, trial["parent_id"], None,
            "free_trial_pass", "trial_expired", None, trial["expiry_at"], row_key
        )

    return None


def _resolve_unconverted_trial_learner(trial):
    """Same conversion check as _get_expired_unconverted_trials(), scoped to
    a single trial's enrollment_ids — used by get_subscription_row so a
    single-row detail lookup doesn't have to scan every trial ever."""

    enrollment_ids = trial["enrollment_ids"] or []

    if not enrollment_ids:
        return None

    enrollment_response = (
        supabase
        .table("Enrollments")
        .select("enrollment_id, learner_id")
        .in_("enrollment_id", enrollment_ids)
        .execute()
    )

    enrollment_lookup = {
        str(row["enrollment_id"]): row
        for row in enrollment_response.data
    }

    learner_ids = list({
        str(row["learner_id"])
        for row in enrollment_response.data
    })

    if not learner_ids:
        return None

    subscription_response = (
        supabase
        .table("Subscriptions")
        .select("learner_id, subscribed_at")
        .in_("learner_id", learner_ids)
        .execute()
    )

    subscriptions_by_learner = {}

    for row in subscription_response.data:
        subscriptions_by_learner.setdefault(
            str(row["learner_id"]), []
        ).append(row)

    start = trial["enrollment_start_timestamp"]
    start = isoparse(start) if isinstance(start, str) and start else None

    for enrollment_id in enrollment_ids:

        enrollment = enrollment_lookup.get(str(enrollment_id))

        if not enrollment:
            continue

        learner_id = str(enrollment["learner_id"])
        converted = False

        for subscription in subscriptions_by_learner.get(learner_id, []):

            subscribed_at = subscription["subscribed_at"]

            if subscribed_at and start and isoparse(subscribed_at) >= start:
                converted = True
                break

        if not converted:
            return learner_id

    return None


def save_sent_subscription_email(row, subject, body, gmail_message_id):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO subscription_cancel_sent
            (row_key, parent_name, parent_email, learner_name, subscription_type, subscription_status, subject, body, gmail_message_id, class_title)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (row_key) DO UPDATE
            SET subject = EXCLUDED.subject,
                body = EXCLUDED.body,
                gmail_message_id = EXCLUDED.gmail_message_id,
                sent_at = NOW()
        """, (
            row["row_key"],
            row.get("parent_name"),
            row.get("parent_email"),
            row.get("learner_name"),
            row.get("subscription_type"),
            row.get("subscription_status"),
            subject,
            body,
            gmail_message_id,
            row.get("class_title"),
        ))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def get_sent_subscription_email(row_key):

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT * FROM subscription_cancel_sent WHERE row_key = %s
        """, (row_key,))

        return cursor.fetchone()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def get_sent_subscriptions():

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT * FROM subscription_cancel_sent ORDER BY sent_at DESC
        """)

        return cursor.fetchall()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def get_cached_draft(row_key):

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT subject, body FROM subscription_cancel_drafts WHERE row_key = %s
        """, (row_key,))

        return cursor.fetchone()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def save_draft(row_key, subject, body):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO subscription_cancel_drafts (row_key, subject, body)
            VALUES (%s, %s, %s)
            ON CONFLICT (row_key) DO UPDATE
            SET subject = EXCLUDED.subject,
                body = EXCLUDED.body,
                generated_at = NOW()
        """, (row_key, subject, body))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def get_or_generate_reengagement_email(row, ai_client=None):
    """Generate the AI draft only once per row_key — cache it locally so
    revisiting the page (or re-clicking after a slow first load) is instant."""

    cached = get_cached_draft(row["row_key"])

    if cached:
        return cached["subject"], cached["body"]

    subject, body = generate_reengagement_email(row, ai_client=ai_client)
    save_draft(row["row_key"], subject, body)

    return subject, body


def _get_draft_row_keys():

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT row_key FROM subscription_cancel_drafts")
        return {row[0] for row in cursor.fetchall()}

    finally:
        cursor.close()
        db_pool.putconn(conn)


def prefetch_reengagement_drafts(batch_size=5):
    """Generate+cache AI drafts for non-dismissed rows that don't have one
    yet, so opening a row is instant instead of triggering a ~20s synchronous
    AI call on first click. Meant to be called periodically from
    scheduler.py — bounded by batch_size per call so a large backlog doesn't
    turn one run into an hours-long block."""

    rows = get_cancelled_subscriptions(page_size=100000)["rows"]
    existing = _get_draft_row_keys()

    missing = [r for r in rows if r["row_key"] not in existing]

    for row in missing[:batch_size]:
        try:
            get_or_generate_reengagement_email(row)
        except Exception as e:
            print(f"Draft prefetch failed for {row['row_key']}:", e)

    return len(missing)


def backfill_reengagement_drafts(concurrency=10):
    """One-time catch-up: generate+cache every missing draft right now using
    several concurrent AI calls (each with its own client — see
    _new_ai_client) instead of waiting on prefetch_reengagement_drafts' slow
    5/minute background trickle. Meant to be run manually/once, not on a
    schedule — safe to re-run since it only targets rows still missing a
    cached draft."""

    rows = get_cancelled_subscriptions(page_size=100000)["rows"]
    existing = _get_draft_row_keys()

    missing = [r for r in rows if r["row_key"] not in existing]

    print(f"Backfilling {len(missing)} drafts with concurrency={concurrency}")

    done = 0
    failed = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(get_or_generate_reengagement_email, row, _new_ai_client()): row
            for row in missing
        }

        for future in futures:
            row = futures[future]
            try:
                future.result()
                done += 1
                if done % 10 == 0:
                    print(f"  {done}/{len(missing)} done")
            except Exception as e:
                failed.append(row["row_key"])
                print(f"Backfill failed for {row['row_key']}:", e)

    print(f"Backfill complete: {done} succeeded, {len(failed)} failed")

    return {"done": done, "failed": failed}


if __name__ == "__main__":
    result = get_cancelled_subscriptions(page_size=1000)

    print(f"Found {result['total']} cancelled subscriptions\n")

    for row in result["rows"]:
        print(
            f"{row['subscription_type']:18} | "
            f"{row['parent_email']} | "
            f"{row['sessions_attended']} sessions"
        )
