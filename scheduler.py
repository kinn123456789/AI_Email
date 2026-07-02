from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from refresh_knowledge_base import refresh_knowledge_base

scheduler = BackgroundScheduler()

scheduler.add_job(
    refresh_knowledge_base,
    CronTrigger(hour=2, minute=0)
)

scheduler.start()