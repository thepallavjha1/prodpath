import os

from flask import Flask

app = Flask(__name__)
DATABASE_URL = os.environ["DATABASE_URL"]
SECRET = os.environ.get("FLASK_SECRET", "hunter2-default")


@app.route("/health")
def health() -> str:
    return "ok"


if __name__ == "__main__":
    app.run(port=8000)
