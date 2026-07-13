import uuid
from datetime import datetime, timezone, timedelta

from config import (
    supabase,
    DEFAULT_BATCH_ID,
    DEFAULT_BATCH_VERSION,
    DEFAULT_PASSWORD,
    TEST_PREFIX
)

def create_auth_user(email):
    """
    Creates a Supabase Auth user.
    """

    response = supabase.auth.admin.create_user(
        {
            "email": email,
            "password": DEFAULT_PASSWORD,
            "email_confirm": True,
        }
    )

    return response.user

def generate_test_email(index):
    return f"trialtest{index}@yopmail.com"

def generate_parent_name(index):
    
    return f"{TEST_PREFIX}_Parent_{index}_{uuid.uuid4().hex[:6]}"

def generate_learner_name(index):
    return f"{TEST_PREFIX}_Learner_{index}_{uuid.uuid4().hex[:6]}"

def new_uuid():
    return str(uuid.uuid4())

def get_trial_dates(days_ago):
    """
    Creates realistic trial dates.

    Trial started 7 days before expiry.
    """

    expiry = datetime.now(timezone.utc) - timedelta(days=days_ago)

    start = expiry - timedelta(days=7)

    return start, expiry

def insert_user(user_id, name, user_type):
    """
    Inserts into Users table.
    user_type should be ["parent"] or ["learner"]
    """

    response = (
        supabase
        .table("Users")
        .insert({
            "user_id": user_id,
            "name": name,
            "type": user_type,
            "is_password_setup": True,
            "is_messaging_available": True,
            "is_deleted": False,
            "is_prelaunch": False,
            "is_prelaunch_verified": False,
            "is_referral_user": False,
            "is_referral_modal_shown": False,
            "marketing_campaign": False
        })
        .execute()
    )

    return response.data

def insert_parent(parent_id):
    """
    Inserts into Parents table.
    """

    response = (
        supabase
        .table("Parents")
        .insert({
            "parent_id": parent_id,
            "is_loyal": False
        })
        .execute()
    )

    return response.data

def insert_learner(
    learner_id,
    parent_id,
    learner_name
):
    """
    Inserts into Learners table.
    """

    response = (
        supabase
        .table("Learners")
        .insert({
            "learner_id": learner_id,
            "parent_id": parent_id,
            "zoom_displayname": learner_name,
            "has_coral_unlimited": False,
            "has_enrolled_ppc": False,
            "is_deleted": False
        })
        .execute()
    )

    return response.data

from datetime import datetime, timezone

def insert_enrollment(learner_id):
    enrollment_id = str(uuid.uuid4())

    response = (
        supabase
        .table("Enrollments")
        .insert({
            "enrollment_id": enrollment_id,
            "batch_id": DEFAULT_BATCH_ID,
            "batch_version": DEFAULT_BATCH_VERSION,
            "learner_id": learner_id,
            "start_timestamp": (
                datetime.now(timezone.utc) - timedelta(days=8)
            ).isoformat(),

            "end_timestamp": (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat(),
            "enrollment_method": "free_trial",
            "enrollment_status": "withdrawn",
            "has_ever_enrolled": True,
            "is_latest": True,
            "is_temporarily_inactive": False
        })
        .execute()
    )

    return enrollment_id
def insert_free_trial(parent_id, enrollment_id):

    trial_id = str(uuid.uuid4())

    response = (
        supabase
        .table("FreeTrialPass")
        .insert({
            "free_trial_pass_id": trial_id,
            "parent_id": parent_id,
            "status": "redeemed",

            "created_at": (
                datetime.now(timezone.utc) - timedelta(days=8)
            ).isoformat(),

            "expiry_at": (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat(),

            "updated_at": datetime.now(timezone.utc).isoformat(),

            # ADD THIS BACK
            "enrollment_ids": [
                enrollment_id
            ],

            "enrollment_start_timestamp": (
                datetime.now(timezone.utc) - timedelta(days=8)
            ).isoformat(),

            "enrollment_end_timestamp": (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat(),
        })
        .execute()
    )

    return trial_id