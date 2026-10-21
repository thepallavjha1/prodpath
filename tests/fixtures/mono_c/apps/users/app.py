import redis
from flask import Flask

app = Flask(__name__)
cache = redis.Redis()
