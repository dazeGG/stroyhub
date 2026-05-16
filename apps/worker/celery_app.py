from celery import Celery
from stroyhub.core.config import settings

celery_app = Celery(
    "stroyhub",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
