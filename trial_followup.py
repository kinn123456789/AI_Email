from psycopg2.extras import RealDictCursor
from dateutil.parser import isoparse
from datetime import datetime, timezone, timedelta
from supabase_client import supabase
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta

from concurrent.futures import ThreadPoolExecutor

from subscription_cancel import _build_class_titles_lookup, _fetch_in_chunks, _fetch_all_paginated



from database import (

    get_connection,

    db_pool
)

def get_trial_followup_candidates():

    now = datetime.now(timezone.utc)

    # Must be wide enough to still catch a trial at its actual email-2 (3
    # days) and email-3 (7 days) marks - process_trial_followups() only
    # ever looks at candidates returned from here, so a window narrower
    # than 7+ days would let a trial "expire out" of being fetched again
    # before it ever qualifies for email 2 or 3. (This was temporarily
    # narrowed to same-day-only for quick manual testing and never
    # reverted - restored here.)
    start_date = now - timedelta(days=30)
    # --------------------------------------------------
    # 1. Get trial passes that expired in the last day
    # --------------------------------------------------

    def build_trial_query(client):
        return (
            client
            .table("FreeTrialPass")
            .select(
                "free_trial_pass_id,"
                "parent_id,"
                "enrollment_ids,"
                "expiry_at,"
                "enrollment_start_timestamp"
            )
            .gte("expiry_at", start_date.isoformat())
            .lte("expiry_at", now.isoformat())
        )

    # Paginated (not just chunked-.in_()) since this is an unbounded fetch,
    # not one filtered by a variable id list — see _fetch_all_paginated for
    # why an unbounded fetch needs this regardless of how small it usually is.
    trials = _fetch_all_paginated(build_trial_query, supabase)

    if not trials:
        return []

    # --------------------------------------------------
    # 2. Collect enrollment ids
    # --------------------------------------------------

    enrollment_ids = []

    for trial in trials:

        if trial["enrollment_ids"]:
            enrollment_ids.extend(trial["enrollment_ids"])

    enrollment_ids = list(set(enrollment_ids))

    if not enrollment_ids:
        return []

    # --------------------------------------------------
    # 3. Read enrollments
    # --------------------------------------------------

    enrollments = _fetch_in_chunks(
        "Enrollments", "enrollment_id, learner_id", "enrollment_id", enrollment_ids
    )

    enrollment_lookup = {}

    learner_ids = []

    for row in enrollments:

        enrollment_lookup[str(row["enrollment_id"])] = row

        learner_ids.append(str(row["learner_id"]))

    learner_ids = list(set(learner_ids))

    if not learner_ids:
        return []

    # --------------------------------------------------
    # 4. Class titles, active subscriptions, and learner names are all
    # independent given learner_ids — run them concurrently, same pattern
    # as _fetch_all_subscription_rows in subscription_cancel.py. Each of
    # _build_class_titles_lookup/_fetch_in_chunks already isolates its own
    # Supabase client(s) internally, so this is safe to parallelize.
    # --------------------------------------------------

    with ThreadPoolExecutor(max_workers=3) as executor:
        class_titles_future = executor.submit(_build_class_titles_lookup, learner_ids)
        # Not filtered to subscription_status == "active" - a learner who
        # converted and then cancelled/had a payment fail still converted
        # once, which is all this module cares about (subscribed_at is what
        # actually proves conversion below). Ongoing cancellation/win-back
        # handling belongs to subscription_cancel.py's module, not here.
        subscriptions_future = executor.submit(
            _fetch_in_chunks, "Subscriptions", "learner_id, subscription_status, subscribed_at", "learner_id", learner_ids
        )
        user_future = executor.submit(_fetch_in_chunks, "Users", "user_id, name", "user_id", learner_ids)

        class_titles_by_learner = class_titles_future.result()
        subscriptions = subscriptions_future.result()
        user_rows = user_future.result()

    subscription_lookup = {}

    for row in subscriptions:

        learner_id = str(row["learner_id"])

        subscription_lookup.setdefault(
            learner_id,
            []
        ).append(row)

    user_lookup = {}

    for user in user_rows:

        user_lookup[str(user["user_id"])] = user["name"]
    # --------------------------------------------------
    # 5. Build eligible learner list
    # --------------------------------------------------

    candidates = []

    for trial in trials:

        start = trial["enrollment_start_timestamp"]

        

        if isinstance(start, str) and start:
            start = isoparse(start)
        elif isinstance(start, datetime):
            pass
        else:
            start = None                

        for enrollment_id in trial["enrollment_ids"] or []:

            enrollment = enrollment_lookup.get(
                str(enrollment_id)
            )

            if not enrollment:
                continue

            learner_id = str(enrollment["learner_id"])

            converted = False

            for subscription in subscription_lookup.get(
                learner_id,
                []
            ):

                subscribed_at = subscription["subscribed_at"]

                if subscribed_at and start:

                    subscribed_at = isoparse(subscribed_at)

                    if subscribed_at >= start:
                        converted = True
                        break

            if converted:
                # No-op if no campaign row exists yet for this learner (e.g.
                # they converted before ever reaching the day-1 mark) - the
                # WHERE clause only touches a row that's actually still open.
                mark_followup_converted(learner_id)
                continue

            expiry = isoparse(trial["expiry_at"])

            candidates.append({

                "free_trial_pass_id":
                trial["free_trial_pass_id"],

                "parent_id":
                trial["parent_id"],

                "learner_id":
                learner_id,

                "learner_name":
                user_lookup.get(learner_id, ""),

                "class_title":
                class_titles_by_learner.get(learner_id, ""),

                "trial_expiry_at":
                expiry

            })
    
    return candidates

def get_followup_history(learner_ids):
    if not learner_ids:
        return {}

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
    SELECT
        parent_id,
        learner_id,
        email1_sent_at,
        email2_sent_at,
        email3_sent_at,
        email1_drafted_at,
        email2_drafted_at,
        email3_drafted_at,
        status
    FROM trial_followup_campaigns
    WHERE learner_id = ANY(%s::uuid[])
""", (learner_ids,))

        rows = cursor.fetchall()

        return {
            row["learner_id"]: row
            for row in rows
        }

    finally:
        cursor.close()
        db_pool.putconn(conn)

def create_followup(
    parent_id,
    learner_id,
    free_trial_pass_id,
    trial_expiry_at
):
    
    conn = get_connection()
    cursor = conn.cursor()

    print("Creating campaign for:", learner_id)

    cursor.execute("SELECT current_database();")
    print("Database:", cursor.fetchone()[0])

    try:
        cursor.execute("""
            INSERT INTO trial_followup_campaigns
            (
                parent_id,
                learner_id,
                free_trial_pass_id,
                trial_expiry_at
            )
            VALUES (%s,%s,%s,%s)

            ON CONFLICT (parent_id, learner_id)

            DO NOTHING
        """,
        (
            parent_id,
            learner_id,
            free_trial_pass_id,
            trial_expiry_at
        ))

        print("Rows inserted:", cursor.rowcount)

        conn.commit()
        

    finally:
        cursor.close()
        db_pool.putconn(conn)

def mark_followup_converted(learner_id):
    """Closes out a candidate's campaign the moment they're found to have
    converted (an active subscription starting at/after their trial began)
    - without this, a converted learner's campaign row just silently sat
    at status='active' forever, since a converted learner is excluded from
    get_trial_followup_candidates()'s results and so never gets touched
    again by anything else. Only updates a row that's still 'active', so
    it never overwrites an already-completed campaign."""

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_campaigns
            SET
                status = 'converted',
                updated_at = NOW()
            WHERE learner_id = %s
              AND status = 'active'
        """, (learner_id,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def update_followup_email1_sent(learner_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_campaigns
            SET
                email1_sent_at = NOW(),
                updated_at = NOW()
            WHERE learner_id=%s
        """,(learner_id,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_followup_email2_sent(learner_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_campaigns
            SET
                email2_sent_at=NOW(),
                updated_at=NOW()
            WHERE learner_id = %s
        """,(learner_id,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_followup_email3_sent(learner_id):
    conn =  get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_campaigns
            SET
                email3_sent_at=NOW(),
                status='completed',
                updated_at=NOW()
            WHERE learner_id=%s
        """,(learner_id,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)


# emailN_drafted_at tracks when the AI draft for that step was generated -
# distinct from emailN_sent_at above, which only advances once a staff member
# actually clicks Send on that draft (see main.py's manual-send route).
def update_followup_email1_drafted(learner_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_campaigns
            SET
                email1_drafted_at = NOW(),
                updated_at = NOW()
            WHERE learner_id=%s
        """,(learner_id,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_followup_email2_drafted(learner_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_campaigns
            SET
                email2_drafted_at=NOW(),
                updated_at=NOW()
            WHERE learner_id = %s
        """,(learner_id,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_followup_email3_drafted(learner_id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_campaigns
            SET
                email3_drafted_at=NOW(),
                updated_at=NOW()
            WHERE learner_id=%s
        """,(learner_id,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)






def get_parent_email(parent_id):
    try:
        response = supabase.auth.admin.get_user_by_id(parent_id)

        

        return response.user.email

    except Exception as e:
        print(f"Error fetching parent email: {e}")
        return None
    
def get_parent_details(parent_id):

    try:
        response = supabase.auth.admin.get_user_by_id(parent_id)

        email = response.user.email

        user = (
            supabase
            .table("Users")
            .select("name")
            .eq("user_id", parent_id)
            .single()
            .execute()
        )

        name = user.data["name"]

        return {
            "email": email,
            "name": name
        }

    except Exception as e:
        print(e)
        return None
    
def get_learner_details(learner_id):

    response = (
        supabase.table("Users")
        .select("user_id, name, email")
        .eq("user_id", learner_id)
        .single()
        .execute()
    )

    if response.data:
        return response.data

    return None
    
def save_followup_email_log(
    learner_id,
    learner_name,
    parent_id,
    parent_name,
    email_number,
    recipient_email,
    subject,
    email_body,
    gmail_message_id,
    scheduled_at=None,
    status="sent",
    class_title=None
):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            INSERT INTO trial_followup_email_logs
            (
                learner_id,
                learner_name,
                parent_id,
                parent_name,
                email_number,
                recipient_email,
                subject,
                email_body,
                gmail_message_id,
                status,
                scheduled_at,
                class_title
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            learner_id,
            learner_name,
            parent_id,
            parent_name,
            email_number,
            recipient_email,
            subject,
            email_body,
            gmail_message_id,
            status,
            scheduled_at,
            class_title
        ))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)



def get_trial_followup_dashboard():

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute("""
            SELECT
                learner_name,
                parent_name,
                email_number,
                recipient_email,
                subject,
                sent_at
            FROM trial_followup_email_logs
            ORDER BY sent_at DESC
        """)

        return cursor.fetchall()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_active_campaign_count():

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT COUNT(*)
            FROM trial_followup_campaigns
            WHERE status = 'active'
        """)

        return cursor.fetchone()[0]

    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_followup_email_logs(search=None, date_from=None, date_to=None, page=1, page_size=50, status=None):

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        params = []
        filters = ""

        if search:
            filters += " AND (subject ILIKE %s OR recipient_email ILIKE %s OR learner_name ILIKE %s OR parent_name ILIKE %s OR class_title ILIKE %s)"
            like = f"%{search}%"
            params.extend([like, like, like, like, like])

        if date_from:
            filters += " AND COALESCE(sent_at, scheduled_at)::date >= %s"
            params.append(date_from)

        if date_to:
            filters += " AND COALESCE(sent_at, scheduled_at)::date <= %s"
            params.append(date_to)

        if status:
            filters += " AND status = %s"
            params.append(status)

        # Exclude future-scheduled "pending" rows so they don't appear on the
        # dashboard until their scheduled_at time arrives. Drafts (status='draft')
        # and already-sent rows remain visible immediately.
        cursor.execute(f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE email_number = 1) AS followup1_count,
                COUNT(*) FILTER (WHERE email_number = 2) AS followup2_count,
                COUNT(*) FILTER (WHERE email_number = 3) AS followup3_count
            FROM (
                SELECT DISTINCT ON (learner_id, email_number)
                    id, email_number
                FROM trial_followup_email_logs
                WHERE NOT (status = 'pending' AND scheduled_at > NOW())
                AND is_trashed = FALSE
                {filters}
                ORDER BY learner_id, email_number, id DESC
            ) latest
        """, params)

        counts_row = cursor.fetchone()
        total = counts_row["total"]

        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size

        cursor.execute(f"""
            SELECT * FROM (
                SELECT DISTINCT ON (learner_id, email_number)
                    id,
                    learner_id,
                    learner_name,
                    parent_id,
                    parent_name,
                    email_number,
                    recipient_email,
                    subject,
                    email_body,
                    gmail_message_id,
                    status,
                    sent_at,
                    scheduled_at,
                    class_title
                FROM trial_followup_email_logs
                WHERE NOT (status = 'pending' AND scheduled_at > NOW())
                AND is_trashed = FALSE
                {filters}
                ORDER BY learner_id, email_number, id DESC
            ) latest
            ORDER BY (status = 'sent') ASC, COALESCE(sent_at, scheduled_at) DESC
            LIMIT %s OFFSET %s
        """, params + [page_size, offset])

        rows = cursor.fetchall()

        return {
            "rows": rows,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "followup1_count": counts_row["followup1_count"],
            "followup2_count": counts_row["followup2_count"],
            "followup3_count": counts_row["followup3_count"],
        }

    finally:
        cursor.close()
        db_pool.putconn(conn)
def get_followup_email(email_id):

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute("""
            SELECT *
            FROM trial_followup_email_logs
            WHERE id = %s
        """, (email_id,))

        return cursor.fetchone()

    finally:

        cursor.close()
        db_pool.putconn(conn)


def get_previous_followup_messages(learner_id, before_email_number):
    """Earlier sent emails in this learner's follow-up campaign (email_number
    less than the one being sent now), oldest first - used to chain
    In-Reply-To/References so follow-up #2 and #3 thread as real replies to
    the earlier ones instead of arriving as disconnected emails."""

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute("""
            SELECT gmail_message_id
            FROM trial_followup_email_logs
            WHERE learner_id = %s
            AND email_number < %s
            AND gmail_message_id IS NOT NULL
            ORDER BY email_number ASC
        """, (learner_id, before_email_number))

        return [row["gmail_message_id"] for row in cursor.fetchall()]

    finally:

        cursor.close()
        db_pool.putconn(conn)


def complete_followup_campaign(learner_id):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            UPDATE trial_followup_campaigns
            SET
                status = 'completed',
                updated_at = NOW()
            WHERE learner_id = %s
        """, (learner_id,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_completed_campaign_count():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT COUNT(*)
            FROM trial_followup_campaigns
            WHERE status = 'completed'
        """)

        result = cursor.fetchone()

        return result[0]

    finally:

        cursor.close()
        db_pool.putconn(conn)

def get_completed_campaigns():

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute("""
            SELECT *
            FROM trial_followup_campaigns
            WHERE status = 'completed'
            ORDER BY email3_sent_at DESC
        """)

        campaigns = cursor.fetchall()

        if not campaigns:
            return []

        learner_ids = list(set(c["learner_id"] for c in campaigns))
        parent_ids = list(set(c["parent_id"] for c in campaigns))

        learners = (
            supabase.table("Users")
            .select("user_id,name")
            .in_("user_id", learner_ids)
            .execute()
        )

        parents = (
            supabase.table("Users")
            .select("user_id,name")
            .in_("user_id", parent_ids)
            .execute()
        )

        learner_map = {
            row["user_id"]: row["name"]
            for row in learners.data
        }

        parent_map = {
            row["user_id"]: row["name"]
            for row in parents.data
        }

        for campaign in campaigns:

            campaign["learner_name"] = learner_map.get(
                campaign["learner_id"],
                "Unknown"
            )

            campaign["parent_name"] = parent_map.get(
                campaign["parent_id"],
                "Unknown"
            )

        return campaigns

    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_followup_email_log(email_id, gmail_message_id, status, real_message_id=None):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_email_logs
            SET
                gmail_message_id = %s,
                status = %s,
                real_message_id = COALESCE(%s, real_message_id),
                sent_at = NOW()
            WHERE id = %s
        """, (
            gmail_message_id,
            status,
            real_message_id,
            email_id
        ))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def find_trial_followup_by_message_ids(candidate_message_ids):
    """Given the In-Reply-To/References message-ids from an inbound email,
    check whether any of them match a real Message-ID this app sent as part
    of a trial-followup campaign. Returns the matching email_log row (id,
    learner_id, etc.) or None. Used by process_email.py to link a genuine
    parent reply back to the trial-followup dashboard - see
    trial_followup_replies."""

    candidate_message_ids = [m for m in (candidate_message_ids or []) if m]

    if not candidate_message_ids:
        return None

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT *
            FROM trial_followup_email_logs
            WHERE real_message_id = ANY(%s)
            ORDER BY email_number DESC
            LIMIT 1
        """, (candidate_message_ids,))

        match = cursor.fetchone()

        if match:
            return match

        # Also check manual staff replies (trial_followup_replies) - a
        # parent may be replying to an ad-hoc reply rather than to one of
        # the 3 scheduled campaign emails directly.
        cursor.execute("""
            SELECT *
            FROM trial_followup_email_logs
            WHERE id = (
                SELECT email_log_id
                FROM trial_followup_replies
                WHERE real_message_id = ANY(%s)
                ORDER BY sent_at DESC
                LIMIT 1
            )
        """, (candidate_message_ids,))

        return cursor.fetchone()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def update_followup_reply(
    email_id,
    ai_reply,
    manual_reply,
    gmail_message_id,
    status
):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            UPDATE trial_followup_email_logs
            SET
                ai_reply = %s,
                manual_reply = %s,
                reply_gmail_message_id = %s,
                reply_status = %s,
                reply_sent_at = NOW()
            WHERE id = %s
        """,(
            ai_reply,
            manual_reply,
            gmail_message_id,
            status,
            email_id
        ))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def save_followup_reply(
    email_log_id,
    subject,
    body,
    gmail_message_id,
    gmail_thread_id=None,
    sender="staff",
    status="sent",
    real_message_id=None
):

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            INSERT INTO trial_followup_replies
            (
                email_log_id,
                sender,
                subject,
                body,
                gmail_message_id,
                gmail_thread_id,
                status,
                real_message_id,
                sent_at
            )
            VALUES
            (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        """,
        (
            email_log_id,
            sender,
            subject,
            body,
            gmail_message_id,
            gmail_thread_id,
            status,
            real_message_id
        ))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_followup_replies(email_log_id):

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        cursor.execute("""
            SELECT *
            FROM trial_followup_replies
            WHERE email_log_id=%s
            ORDER BY created_at
        """,(email_log_id,))

        return cursor.fetchall()

    finally:
        cursor.close()
        db_pool.putconn(conn)

def get_due_followups():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT *
            FROM trial_followup_email_logs
            WHERE status='pending'
            AND scheduled_at <= NOW()
            ORDER BY scheduled_at
        """)
        return cursor.fetchall()

    finally:
        cursor.close()
        db_pool.putconn(conn)




#scheduled_at = datetime.now() + timedelta(days=7)
def update_followup_schedule(email_id, scheduled_at):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_email_logs
            SET
                status = 'pending',
                scheduled_at = %s
            WHERE id = %s
        """, (
            scheduled_at,
            email_id
        ))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def move_followup_to_trash(email_ids):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_email_logs
            SET is_trashed = TRUE
            WHERE id = ANY(%s)
        """, (email_ids,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def restore_followup_from_trash(email_ids):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_email_logs
            SET is_trashed = FALSE
            WHERE id = ANY(%s)
        """, (email_ids,))

        conn.commit()

    finally:
        cursor.close()
        db_pool.putconn(conn)


def get_trashed_followup_email_logs():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cursor.execute("""
            SELECT
                id,
                learner_name,
                parent_name,
                email_number,
                recipient_email,
                subject,
                status,
                sent_at,
                scheduled_at,
                class_title
            FROM trial_followup_email_logs
            WHERE is_trashed = TRUE
            ORDER BY id DESC
        """)

        return cursor.fetchall()

    finally:
        cursor.close()
        db_pool.putconn(conn)