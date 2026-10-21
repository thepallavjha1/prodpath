import os

from flask import Flask

app = Flask(__name__)
DB = os.environ["DATABASE_URL"]
