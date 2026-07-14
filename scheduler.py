from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from email_reader import main as email_reader
from refresh_knowledge_base import refresh_knowledge_base
from refresh_classes import refresh_classes
from gmail_watch import renew_all_gmail_watches
import traceback

import datetime



def run_email_reader():
    print("=" * 80)
    print(f"EMAIL READER STARTED: {datetime.datetime.now()}")
    print("=" * 80)

    try:
        email_reader()
        print("EMAIL READER COMPLETED SUCCESSFULLY")
    except Exception:
        print("EMAIL READER FAILED")
        traceback.print_exc()

    print("=" * 80)

scheduler = BackgroundScheduler()



# Refresh Help Center
scheduler.add_job(
    refresh_knowledge_base,
    CronTrigger(hour=2, minute=0),
    id="help_center_refresh",
    replace_existing=True,
    max_instances=1
)

#runs email_reader
scheduler.add_job(
    run_email_reader,
    "interval",
    minutes=5,
    id="email_reader",
    replace_existing=True,
    max_instances=1
)

# Refresh Classes
scheduler.add_job(
    refresh_classes,
    CronTrigger(hour=3, minute=0),
    id="classes_refresh",
    replace_existing=True,
    max_instances=1
)



#gmail_watch
scheduler.add_job(
    renew_all_gmail_watches,
    trigger="interval",
    days=1
)
scheduler.start()
print("Scheduler started.")
print("Help Center Refresh: Daily at 2:00 AM")
print("Classes Refresh: Daily at 3:00 AM")