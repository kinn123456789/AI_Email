import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from process_trial_followup import process_trial_followups

scheduler = BackgroundScheduler()

scheduler.add_job(
    process_trial_followups,
    CronTrigger(hour=9, minute=0)
)

scheduler.start()

print("Trial Follow-up Scheduler Started")

try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    scheduler.shutdown()