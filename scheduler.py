from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta

from email_reader import main as email_reader
from refresh_knowledge_base import refresh_knowledge_base
from refresh_classes import refresh_classes
from gmail_watch import renew_all_gmail_watches
from sync_sent_gmail import main as sync_sent_emails
from process_trial_followup import process_trial_followups

from teacher_api_sync import sync_teacher_portal
#from teacher_ai_processor import process_teacher_messages
import threading
import time
from teacher_ai_processor1 import process_teacher_messages
from subscription_cancel import refresh_subscription_cache, prefetch_reengagement_drafts
# -------------------------------------------------
# Locks & Queue
# -------------------------------------------------

reader_lock = threading.Lock()
pending_lock = threading.Lock()
subscription_cancel_lock = threading.Lock()

pending_mailboxes = set()


# -------------------------------------------------
# Email Reader
# -------------------------------------------------

def run_email_reader(email_address=None):

    global pending_mailboxes

    # ---------------------------------------------
    # Scheduler run (process ALL mailboxes)
    # ---------------------------------------------
    if email_address is None:

        if not reader_lock.acquire(blocking=False):
            print("Reader already running.")
            return

        try:

            start = time.time()

            print("=" * 80)
            print("EMAIL READER STARTED (ALL)")
            print("=" * 80)

            email_reader()

            print(
                f"EMAIL READER TOOK "
                f"{time.time() - start:.2f} seconds"
            )

        finally:

            reader_lock.release()

        return

    # ---------------------------------------------
    # Webhook run (single mailbox)
    # ---------------------------------------------
    if not reader_lock.acquire(blocking=False):

        print(f"Reader busy. Queuing {email_address}")

        with pending_lock:
            pending_mailboxes.add(email_address)

        return

    try:

        current_mailbox = email_address

        while True:

            start = time.time()

            print("=" * 80)
            print("EMAIL READER STARTED")
            print("Mailbox:", current_mailbox)
            print("=" * 80)

            email_reader(current_mailbox)

            with pending_lock:
                pending_mailboxes.discard(current_mailbox)

            print(
                f"{current_mailbox} TOOK "
                f"{time.time() - start:.2f} seconds"
            )

            with pending_lock:

                if not pending_mailboxes:
                    break

                current_mailbox = pending_mailboxes.pop()

            print(
                f"Processing queued mailbox: "
                f"{current_mailbox}"
            )

    finally:

        reader_lock.release()

def run_refresh_subscription_cache():
    """Shares subscription_cancel_lock with run_prefetch_reengagement_drafts so
    the two never run concurrently even if their staggered schedules ever
    drift into overlap — both are concurrency-heavy (ThreadPoolExecutor +
    several Supabase clients each), and stacking them was part of what
    caused the OOM kill on 2026-07-25."""

    if not subscription_cancel_lock.acquire(blocking=False):
        print("Subscription cache refresh skipped — draft prefetch still running.")
        return

    try:
        refresh_subscription_cache()
    finally:
        subscription_cancel_lock.release()


def run_prefetch_reengagement_drafts():
    """See run_refresh_subscription_cache — shares the same lock."""

    if not subscription_cancel_lock.acquire(blocking=False):
        print("Draft prefetch skipped — subscription cache refresh still running.")
        return

    try:
        prefetch_reengagement_drafts()
    finally:
        subscription_cancel_lock.release()


def run_teacher_sync():
    start = time.time()

    print("=" * 80)
    print("TEACHER SYNC STARTED")
    print("=" * 80)

    try:
        sync_teacher_portal()
        process_teacher_messages()

        print(
            f"TEACHER SYNC COMPLETED IN "
            f"{time.time() - start:.2f} seconds"
        )

    except Exception as e:
        print(
            f"TEACHER SYNC FAILED AFTER "
            f"{time.time() - start:.2f} seconds"
        )
        print(e)


# -------------------------------------------------
# Scheduler
# -------------------------------------------------

scheduler = BackgroundScheduler()

# Staggering offsets for the frequent jobs (subscription cache/draft prefetch
# every 1min, email reader every 5min, teacher sync every 8min) — chosen so
# no two of them can ever land in the same second (pairwise offset
# differences don't divide evenly into whichever interval they share). Before
# this, all four defaulted to firing at server-startup-time + their own
# interval, which meant they collided exactly every 40 minutes (the LCM of
# 1/5/8 min) — that pile-up was part of what caused the 2026-07-25 OOM kill.
_schedule_base = datetime.now()

# Sent Mail Sync
scheduler.add_job(
    sync_sent_emails,
    trigger="interval",
    hours=1,
    id="sent_mail_sync",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
    misfire_grace_time=300
)

# Help Center Refresh
scheduler.add_job(
    refresh_knowledge_base,
    CronTrigger(hour=2, minute=0),
    id="help_center_refresh",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
    misfire_grace_time=300
)

# Email Reader Backup
scheduler.add_job(
    run_email_reader,
    trigger="interval",
    minutes=5,
    next_run_time=_schedule_base + timedelta(seconds=40),
    id="email_reader",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
    misfire_grace_time=300
)

# Class Refresh
scheduler.add_job(
    refresh_classes,
    CronTrigger(hour=3, minute=0),
    id="classes_refresh",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
    misfire_grace_time=300
)

# Gmail Watch Renewal
scheduler.add_job(
    renew_all_gmail_watches,
    trigger="interval",
    days=1,
    id="gmail_watch",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
    misfire_grace_time=300
)

scheduler.add_job(
    run_teacher_sync,
    trigger="interval",
    minutes=8,
    next_run_time=_schedule_base + timedelta(seconds=70),
    id="teacher_sync",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
    misfire_grace_time=300
)

scheduler.add_job(
    process_trial_followups,
    CronTrigger(hour=9, minute=0),
    id="trial_followups",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
    misfire_grace_time=300
)

# Warm the cache immediately at startup so the first page load after a
# deploy/restart doesn't pay the ~5s cold-fetch cost either.
try:
    refresh_subscription_cache()
except Exception as e:
    print("Initial subscription cache warm-up failed:", e)

scheduler.add_job(
    run_refresh_subscription_cache,
    trigger="interval",
    minutes=1,
    next_run_time=_schedule_base + timedelta(seconds=60),
    id="subscription_cancel_cache",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
    misfire_grace_time=60
)

# Pre-generates re-engagement drafts for rows that don't have one cached yet, so
# clicking into a row in the UI doesn't trigger a ~20s synchronous AI call.
scheduler.add_job(
    run_prefetch_reengagement_drafts,
    trigger="interval",
    minutes=1,
    next_run_time=_schedule_base + timedelta(seconds=20),
    id="subscription_cancel_draft_prefetch",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
    misfire_grace_time=60
)

scheduler.start()

print("Scheduler started.")
print("Email Reader: Every 5 minutes")
print("Sent Mail Sync: Every 1 hour")
print("Help Center Refresh: Daily at 2:00 AM")
print("Classes Refresh: Daily at 3:00 AM")
print("Gmail Watch Renewal: Every 1 day")
print("Teacher Sync: Every 8 minutes")
print("Trial Follow-ups: Daily at 9:00 AM")
print("Subscription Cancel Cache: Every 1 minute")
print("Subscription Cancel Draft Prefetch: Every 1 minute (batch of 5)")
