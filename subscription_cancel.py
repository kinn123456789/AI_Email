# subscription_cancel.py

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dateutil.parser import isoparse
from openai import OpenAI

from supabase_client import supabase
from database import get_connection, db_pool
from psycopg2.extras import RealDictCursor

_ai_client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)


def generate_winback_email(row):

    parent_name = row.get("parent_name") or "there"
    learner_name = row.get("learner_name") or "your child"
    sessions_attended = row.get("sessions_attended") or 0

    if row["subscription_status"] == "trial_expired":
        subject = f"We'd love to have {learner_name} back at Coral Academy"
        context = f"{learner_name}'s free trial expired without continuing to a paid membership."
    else:
        subject = f"We miss {learner_name} at Coral Academy"
        context = f"{learner_name}'s subscription ({row.get('subscription_type')}) was recently cancelled."

    session_note = (
        f"{learner_name} attended {sessions_attended} class session(s) before this."
        if sessions_attended > 0
        else ""
    )

    prompt = f"""
Write a warm, professional win-back email.

Parent name: {parent_name}
Learner name: {learner_name}

{context}
{session_note}

Gently invite the parent to come back and continue learning with Coral Academy.

Ask if there was anything that didn't work well, and offer to help.

Keep it around 100 words.

Return ONLY the email body.

Do not include:
- Subject
- Markdown
- Bullet points
- Explanations
"""

    try:
        response = _ai_client.chat.completions.create(
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
        return subject, body

    except Exception as e:
        print("AI Error:", e)

        return subject, f"""
Hi {parent_name},

{context} We'd love to have {learner_name} continue learning with us.

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
        .eq("subscription_status", "canceled")
        .execute()
    )

    types = {
        row["subscription_type"]
        for row in response.data
        if row["subscription_type"]
    }

    types.add("free_trial_pass")

    return sorted(types)


def _get_expired_unconverted_trials():
    """
    Trial passes that expired without the learner ever subscribing —
    same "converted" check trial_followup.py uses, but over all history
    (not just today's expirations) since this is a cumulative list.
    """

    now = datetime.now(timezone.utc)

    trial_response = (
        supabase
        .table("FreeTrialPass")
        .select(
            "free_trial_pass_id,"
            "parent_id,"
            "enrollment_ids,"
            "expiry_at,"
            "enrollment_start_timestamp"
        )
        .lte("expiry_at", now.isoformat())
        .execute()
    )

    trials = trial_response.data

    if not trials:
        return []

    enrollment_ids = list({
        eid
        for trial in trials
        for eid in (trial["enrollment_ids"] or [])
    })

    if not enrollment_ids:
        return []

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
        return []

    # Any subscription at all (regardless of current status) means the
    # learner converted at some point — exclude them so they aren't
    # double-counted alongside the real Subscriptions-cancelled rows.
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


def get_cancelled_subscriptions(search=None, date_from=None, date_to=None, page=1, page_size=50):

    subscription_response = (
        supabase
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
        .eq("subscription_status", "canceled")
        .execute()
    )

    subscriptions = subscription_response.data
    trial_candidates = _get_expired_unconverted_trials()

    if not subscriptions and not trial_candidates:
        return {
            "rows": [],
            "total": 0,
            "page": 1,
            "total_pages": 1,
        }

    learner_ids = list({
        s["learner_id"]
        for s in subscriptions
        if s["learner_id"]
    } | {
        t["learner_id"]
        for t in trial_candidates
        if t["learner_id"]
    })

    learner_response = (
        supabase
        .table("Learners")
        .select("learner_id, parent_id")
        .in_("learner_id", learner_ids)
        .execute()
    )

    parent_by_learner = {
        row["learner_id"]: row["parent_id"]
        for row in learner_response.data
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

    learner_name_response = (
        supabase
        .table("Users")
        .select("user_id, name")
        .in_("user_id", learner_ids)
        .execute()
    )

    learner_name_lookup = {
        row["user_id"]: row["name"]
        for row in learner_name_response.data
    }

    parent_email_lookup = {}

    if parent_ids:

        email_response = (
            supabase
            .table("EmailDeliveryStatus")
            .select("parent_id, parent_name, parent_email, created_at")
            .in_("parent_id", parent_ids)
            .not_.is_("parent_email", "null")
            .order("created_at", desc=True)
            .execute()
        )

        for row in email_response.data:

            pid = row["parent_id"]

            # First occurrence per parent is the most recent, since rows
            # are ordered by created_at DESC.
            if pid not in parent_email_lookup:
                parent_email_lookup[pid] = row

    session_response = (
        supabase
        .table("SessionInteraction")
        .select("learner_id")
        .in_("learner_id", learner_ids)
        .eq("did_attend", True)
        .execute()
    )

    session_counts = {}

    for row in session_response.data:

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
            "sessions_attended": session_counts.get(learner_id, 0)
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
            "sessions_attended": session_counts.get(learner_id, 0)
        })

    dismissed_keys = get_dismissed_row_keys()

    results = [
        r for r in results
        if r["row_key"] not in dismissed_keys
    ]

    if search:
        search_lower = search.lower()
        results = [
            r for r in results
            if search_lower in (r["parent_name"] or "").lower()
            or search_lower in (r["parent_email"] or "").lower()
            or search_lower in (r["subscription_type"] or "").lower()
            or search_lower in (r["learner_name"] or "").lower()
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
    parent_name, parent_email, learner_name, canceled_at_display."""

    conn = get_connection()
    cursor = conn.cursor()

    try:
        for row in rows:
            cursor.execute("""
                INSERT INTO subscription_cancel_dismissed
                (row_key, subscription_type, subscription_status, parent_name, parent_email, learner_name, canceled_at_display)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (row_key) DO NOTHING
            """, (
                row["row_key"],
                row.get("subscription_type"),
                row.get("subscription_status"),
                row.get("parent_name"),
                row.get("parent_email"),
                row.get("learner_name"),
                row.get("canceled_at_display"),
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


def _build_row(learner_id, parent_id, subscription_id, subscription_type,
               subscription_status, subscribed_at, canceled_at, row_key):

    learner_name = None
    learner_response = (
        supabase.table("Users").select("name").eq("user_id", learner_id).execute()
    )
    if learner_response.data:
        learner_name = learner_response.data[0]["name"]

    parent_name = None
    parent_email = None

    if parent_id:
        email_response = (
            supabase
            .table("EmailDeliveryStatus")
            .select("parent_name, parent_email, created_at")
            .eq("parent_id", parent_id)
            .not_.is_("parent_email", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if email_response.data:
            parent_name = email_response.data[0]["parent_name"]
            parent_email = email_response.data[0]["parent_email"]

    session_response = (
        supabase
        .table("SessionInteraction")
        .select("session_interaction_id")
        .eq("learner_id", learner_id)
        .eq("did_attend", True)
        .execute()
    )

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
        "sessions_attended": len(session_response.data)
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
            .select("free_trial_pass_id, parent_id, expiry_at")
            .eq("free_trial_pass_id", raw_id)
            .execute()
        )

        if not response.data:
            return None

        trial = response.data[0]

        # Dismissed/sent tracking only keys on the trial pass, not the
        # learner, so re-derive the matching learner the same way
        # _get_expired_unconverted_trials() does.
        matching = [
            c for c in _get_expired_unconverted_trials()
            if c["free_trial_pass_id"] == raw_id
        ]

        if not matching:
            return None

        candidate = matching[0]

        return _build_row(
            candidate["learner_id"], trial["parent_id"], None,
            "free_trial_pass", "trial_expired", None, trial["expiry_at"], row_key
        )

    return None


def save_sent_subscription_email(row, subject, body, gmail_message_id):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO subscription_cancel_sent
            (row_key, parent_name, parent_email, learner_name, subscription_type, subscription_status, subject, body, gmail_message_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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


def get_or_generate_winback_email(row):
    """Generate the AI draft only once per row_key — cache it locally so
    revisiting the page (or re-clicking after a slow first load) is instant."""

    cached = get_cached_draft(row["row_key"])

    if cached:
        return cached["subject"], cached["body"]

    subject, body = generate_winback_email(row)
    save_draft(row["row_key"], subject, body)

    return subject, body


if __name__ == "__main__":
    result = get_cancelled_subscriptions(page_size=1000)

    print(f"Found {result['total']} cancelled subscriptions\n")

    for row in result["rows"]:
        print(
            f"{row['subscription_type']:18} | "
            f"{row['parent_email']} | "
            f"{row['sessions_attended']} sessions"
        )
