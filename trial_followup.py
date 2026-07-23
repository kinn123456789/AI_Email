from psycopg2.extras import RealDictCursor
from dateutil.parser import isoparse
from datetime import datetime, timezone, timedelta
from supabase_client import supabase
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta



from database import (
    
    get_connection,
    
    db_pool
)

def get_trial_followup_candidates():

    now = datetime.now(timezone.utc)
    #yesterday = now - timedelta(days=1)
    
    #start_date = now - timedelta(days=30)
    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # --------------------------------------------------
    # 1. Get trial passes that expired in the last day
    # --------------------------------------------------

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
        .gte("expiry_at", start_date.isoformat())
        .lte("expiry_at", now.isoformat())
        .execute()
    )

    trials = trial_response.data

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

    enrollment_response = (
        supabase
        .table("Enrollments")
        .select(
            "enrollment_id,"
            "learner_id"
        )
        .in_("enrollment_id", enrollment_ids)
        .execute()
    )

    enrollments = enrollment_response.data

    enrollment_lookup = {}

    learner_ids = []

    for row in enrollments:

        enrollment_lookup[str(row["enrollment_id"])] = row

        learner_ids.append(str(row["learner_id"]))

    learner_ids = list(set(learner_ids))

    if not learner_ids:
        return []

    # --------------------------------------------------
    # 4. Read active subscriptions
    # --------------------------------------------------

    subscription_response = (
        supabase
        .table("Subscriptions")
        .select(
            "learner_id,"
            "subscription_status,"
            "subscribed_at"
        )
        .eq("subscription_status", "active")
        .in_("learner_id", learner_ids)
        .execute()
    )

    subscriptions = subscription_response.data

    subscription_lookup = {}

    for row in subscriptions:

        learner_id = str(row["learner_id"])

        subscription_lookup.setdefault(
            learner_id,
            []
        ).append(row)



# --------------------------------------------------
# 4A. Read learner names
# --------------------------------------------------

    user_response = (
        supabase
        .table("Users")
        .select("user_id, name")
        .in_("user_id", learner_ids)
        .execute()
    )

    user_lookup = {}

    for user in user_response.data:

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
    status="sent"
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
                scheduled_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
            scheduled_at
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

def get_followup_email_logs():

    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:

        # Exclude future-scheduled "pending" rows so they don't appear on the
        # dashboard until their scheduled_at time arrives. Drafts (status='draft')
        # and already-sent rows remain visible immediately.
        cursor.execute("""
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
                    scheduled_at
                FROM trial_followup_email_logs
                WHERE NOT (status = 'pending' AND scheduled_at > NOW())
                ORDER BY learner_id, email_number, id DESC
            ) latest
            ORDER BY COALESCE(sent_at, scheduled_at) DESC
        """)

        return cursor.fetchall()

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

def update_followup_email_log(email_id, gmail_message_id, status):

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE trial_followup_email_logs
            SET
                gmail_message_id = %s,
                status = %s,
                sent_at = NOW()
            WHERE id = %s
        """, (
            gmail_message_id,
            status,
            email_id
        ))

        conn.commit()

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
    status="sent"
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
                sent_at
            )
            VALUES
            (%s,%s,%s,%s,%s,%s,%s,NOW())
        """,
        (
            email_log_id,
            sender,
            subject,
            body,
            gmail_message_id,
            gmail_thread_id,
            status
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