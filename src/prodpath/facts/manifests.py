"""Dependency manifests and env files -> facts.

Only packages in KNOWN_PACKAGES produce facts; everything else is ignored on purpose, because
hundreds of unclassified dependencies would drown the signal. Env files yield variable
*names* only; values are dropped as the line is parsed (SECURITY.md section 3).
"""

import json
import re
import tomllib

from prodpath.facts import ExtractionError, find_line, make_fact
from prodpath.models import Fact, FactKind

KNOWN_PACKAGES: dict[str, tuple[FactKind, str]] = {
    "flask": ("framework", "flask"),
    "fastapi": ("framework", "fastapi"),
    "django": ("framework", "django"),
    "starlette": ("framework", "starlette"),
    "express": ("framework", "express"),
    "koa": ("framework", "koa"),
    "fastify": ("framework", "fastify"),
    "next": ("framework", "next.js"),
    "@nestjs/core": ("framework", "nestjs"),
    # Frontends (Phase 7). Build tools usually sit in devDependencies; see FRONTEND_DEV_TOOLS.
    "react": ("framework", "react"),
    "vue": ("framework", "vue"),
    "vite": ("framework", "vite"),
    "react-scripts": ("framework", "create-react-app"),
    "@vue/cli-service": ("framework", "vue-cli"),
    "@angular/cli": ("framework", "angular"),
    "@angular/core": ("framework", "angular"),
    "astro": ("framework", "astro"),
    "gatsby": ("framework", "gatsby"),
    "@docusaurus/core": ("framework", "docusaurus"),
    "vitepress": ("framework", "vitepress"),
    "vuepress": ("framework", "vuepress"),
    "@sveltejs/adapter-static": ("framework", "sveltekit-static"),
    "gunicorn": ("runtime", "gunicorn"),
    "uvicorn": ("runtime", "uvicorn"),
    "psycopg2": ("datastore", "postgres"),
    "psycopg2-binary": ("datastore", "postgres"),
    "psycopg": ("datastore", "postgres"),
    "asyncpg": ("datastore", "postgres"),
    "pg": ("datastore", "postgres"),
    "pymysql": ("datastore", "mysql"),
    "mysqlclient": ("datastore", "mysql"),
    "mysql-connector-python": ("datastore", "mysql"),
    "mysql2": ("datastore", "mysql"),
    "pymongo": ("datastore", "mongodb"),
    "motor": ("datastore", "mongodb"),
    "mongodb": ("datastore", "mongodb"),
    "mongoose": ("datastore", "mongodb"),
    "@aws-sdk/client-dynamodb": ("datastore", "dynamodb"),
    "redis": ("cache", "redis"),
    "aioredis": ("cache", "redis"),
    "ioredis": ("cache", "redis"),
    "pymemcache": ("cache", "memcached"),
    "celery": ("worker", "celery"),
    "rq": ("worker", "rq"),
    "bullmq": ("queue", "bullmq"),
    "bull": ("queue", "bull"),
    "pika": ("queue", "rabbitmq"),
    "kombu": ("queue", "kombu"),
    "kafka-python": ("queue", "kafka"),
    "confluent-kafka": ("queue", "kafka"),
    "kafkajs": ("queue", "kafka"),
    "@aws-sdk/client-sqs": ("queue", "sqs"),
    "@aws-sdk/client-s3": ("object_store", "s3"),
    "boto3": ("external_call", "aws-sdk"),
    "requests": ("external_call", "http-client"),
    "httpx": ("external_call", "http-client"),
    "axios": ("external_call", "http-client"),
    "node-fetch": ("external_call", "http-client"),
}


# Only these are read from devDependencies: production dependencies shape the deployment, but
# a frontend's build tool is a dev dependency and is exactly what makes it a static site.
FRONTEND_DEV_TOOLS = {
    "vite", "react-scripts", "@vue/cli-service", "@angular/cli", "astro", "gatsby",
    "@docusaurus/core", "vitepress", "vuepress", "@sveltejs/adapter-static", "next",
}  # fmt: skip


def classify_package(name: str) -> tuple[FactKind, str] | None:
    key = name.lower().replace("_", "-")
    if key in KNOWN_PACKAGES:
        return KNOWN_PACKAGES[key]
    if key.startswith("@aws-sdk/"):
        return ("external_call", "aws-sdk")
    return None


def parse_requirement(spec: str) -> list[str]:
    """'celery[redis]>=5' -> ['celery', 'redis']: the package plus its extras."""
    spec = spec.split("#")[0].strip()
    if not spec or spec.startswith(("-", ".", "/")):
        return []
    match = re.match(r"([A-Za-z0-9_.-]+)\s*(?:\[([^\]]*)\])?", spec)
    if not match:
        return []
    extras = [e.strip() for e in (match.group(2) or "").split(",") if e.strip()]
    return [match.group(1), *extras]


def _facts_for_names(names: list[str], path: str, lines: list[str]) -> list[Fact]:
    facts = []
    for name in names:
        known = classify_package(name)
        if known is None:
            continue
        line = find_line(lines, name)
        snippet = lines[line - 1] if line else name
        facts.append(make_fact(known[0], known[1], path, line, snippet))
    return facts


def extract_requirements(path: str, source: str) -> list[Fact]:
    lines = source.splitlines()
    names: list[str] = []
    for raw in lines:
        names += parse_requirement(raw)
    return _facts_for_names(names, path, lines)


def extract_pyproject(path: str, source: str) -> list[Fact]:
    try:
        data = tomllib.loads(source)
    except tomllib.TOMLDecodeError as error:
        raise ExtractionError(f"invalid TOML: {error}") from error
    specs: list[str] = list(data.get("project", {}).get("dependencies", []))
    for group in data.get("project", {}).get("optional-dependencies", {}).values():
        specs += group
    specs += list(data.get("tool", {}).get("poetry", {}).get("dependencies", {}))
    names = [name for spec in specs for name in parse_requirement(spec)]
    return _facts_for_names(names, path, source.splitlines())


def extract_package_json(path: str, source: str) -> list[Fact]:
    try:
        data = json.loads(source)
    except json.JSONDecodeError as error:
        raise ExtractionError(f"invalid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ExtractionError("package.json is not an object")
    names: list[str] = []
    for section in ("dependencies", "optionalDependencies"):
        names += list(data.get(section, {}))
    names += [n for n in data.get("devDependencies", {}) if n in FRONTEND_DEV_TOOLS]
    # Quote the name so 'pg' does not match inside '"pg-pool"'.
    return _facts_for_quoted(names, path, source.splitlines())


def _facts_for_quoted(names: list[str], path: str, lines: list[str]) -> list[Fact]:
    facts = []
    for name in names:
        known = classify_package(name)
        if known is None:
            continue
        line = find_line(lines, f'"{name}"')
        snippet = lines[line - 1] if line else name
        facts.append(make_fact(known[0], known[1], path, line, snippet))
    return facts


def extract_env_file(path: str, source: str) -> list[Fact]:
    """Names only. The value is never kept, not even in the evidence snippet."""
    facts = []
    for number, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            facts.append(make_fact("env_var", name, path, number, f"{name}="))
    return facts
