from celery import Celery
from celery.schedules import crontab
from stroyhub.core.config import settings

celery_app = Celery(
    "stroyhub",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    timezone=settings.timezone,
    enable_utc=True,
    beat_schedule={
        "scrape-due-shops-daily-midnight-yakutsk": {
            "task": "stroyhub.scrape_due_shops",
            "schedule": crontab(minute=0, hour=0),
        },
    },
)

import apps.worker.tasks  # noqa: E402,F401
