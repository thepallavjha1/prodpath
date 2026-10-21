import os

from fastapi import FastAPI
from worker_client import enqueue

app = FastAPI()
REDIS_URL = os.getenv("REDIS_URL")


@app.post("/jobs")
def create_job() -> dict[str, str]:
    enqueue()
    return {"status": "queued"}
