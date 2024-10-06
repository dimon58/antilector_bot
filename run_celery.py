import logging.config

from celery import Celery

from configs import (
    LOGGING_CONFIG,
    RABBITMQ_DEFAULT_PASS,
    RABBITMQ_DEFAULT_USER,
    RABBITMQ_HOST,
    RABBITMQ_PORT,
)
from system_init import system_init

logging.config.dictConfig(LOGGING_CONFIG)

rabbitmq_url = f"{RABBITMQ_DEFAULT_USER}:{RABBITMQ_DEFAULT_PASS}@{RABBITMQ_HOST}:{RABBITMQ_PORT}"

tasks = ["processing"]

app = Celery(
    "bg",
    broker=f"pyamqp://{rabbitmq_url}//",
    backend=f"rpc://{rabbitmq_url}//",
    include=tasks,
)

app.autodiscover_tasks(tasks, force=True)

system_init()
