from celery import Celery
from config import REDIS_URL

celery_app = Celery(
    "tasks",
    broker=REDIS_URL,
    backend=REDIS_URL
)