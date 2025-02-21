from celery import Celery

from configs import (
    RABBITMQ_DEFAULT_PASS,
    RABBITMQ_DEFAULT_USER,
    RABBITMQ_HOST,
    RABBITMQ_PORT,
)

rabbitmq_url = f"{RABBITMQ_DEFAULT_USER}:{RABBITMQ_DEFAULT_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}"

tasks = ["processing"]

app = Celery(
    "bg",
    broker=f"pyamqp://{rabbitmq_url}//",
    backend=f"rpc://{rabbitmq_url}//",
    include=tasks,
)

app.autodiscover_tasks(tasks, force=True)
