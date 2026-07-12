from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from email_reader import main as email_reader
from refresh_knowledge_base import refresh_knowledge_base
from refresh_classes import refresh_classes

import traceback

def run_email_reader():
    try:
        email_reader()
    except Exception:
        traceback.print_exc()

scheduler = BackgroundScheduler()



# Refresh Help Center
scheduler.add_job(
    refresh_knowledge_base,
    CronTrigger(hour=2, minute=0),
    id="help_center_refresh",
    replace_existing=True,
    max_instances=1
)
scheduler.add_job(
    email_reader,
    "interval",
    minutes=5
)
# Refresh Classes
scheduler.add_job(
    refresh_classes,
    CronTrigger(hour=3, minute=0),
    id="classes_refresh",
    replace_existing=True,
    max_instances=1
)

scheduler.start()

print("Scheduler started.")
print("Help Center Refresh: Daily at 2:00 AM")
print("Classes Refresh: Daily at 3:00 AM")