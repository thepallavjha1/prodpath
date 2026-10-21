import os

from celery import Celery

app = Celery("tasks", broker=os.environ["REDIS_URL"])


@app.task
def process() -> None:
    pass
