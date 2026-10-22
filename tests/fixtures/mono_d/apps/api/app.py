import os

from flask import Flask

app = Flask(__name__)
DATABASE_URL = os.environ["DATABASE_URL"]


@app.route("/health")
def health() -> str:
    return "ok"
