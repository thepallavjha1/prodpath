import pytest

from prodpath.facts import ExtractionError, compose, docker, javascript, manifests
from prodpath.facts import python as python_facts
from prodpath.models import Fact


def pairs(facts: list[Fact]) -> set[tuple[str, str]]:
    return {(f.kind, f.value) for f in facts}


def test_python_env_var_forms_and_default_never_leaks() -> None:
    source = (
        "import os\n"
        'A = os.environ["A_VAR"]\n'
        'B = os.environ.get("B_VAR", "hunter2-default")\n'
        'C = os.getenv("C_VAR")\n'
    )
    facts = python_facts.extract("x.py", source)
    assert {f.value for f in facts if f.kind == "env_var"} == {"A_VAR", "B_VAR", "C_VAR"}
    assert "hunter2" not in "".join(e.snippet for f in facts for e in f.evidence)


def test_python_imports_calls_and_decorators() -> None:
    source = (
        "import boto3\nimport redis\nfrom celery import Celery\nfrom flask import Flask\n"
        "app = Flask(__name__)\n"
        'q = boto3.client("sqs")\n'
        'with open("/tmp/a", "wb") as h:\n    pass\n'
        'with open("/tmp/b") as h:\n    pass\n'
        '@app.get("/healthz")\ndef health():\n    pass\n'
        "@celery.task\ndef job():\n    pass\n"
        "app.run(port=5000)\n"
    )
    facts = pairs(python_facts.extract("x.py", source))
    assert {
        ("cache", "redis"),
        ("worker", "celery"),
        ("framework", "flask"),
        ("queue", "sqs"),
        ("local_state", "/tmp/a"),
        ("health_endpoint", "/healthz"),
        ("worker", "celery task"),
        ("port", "5000"),
    } <= facts
    assert ("local_state", "/tmp/b") not in facts  # read-only open is not local state


def test_python_syntax_error_is_reported_not_swallowed() -> None:
    with pytest.raises(ExtractionError, match="syntax error"):
        python_facts.extract("bad.py", "def (:\n")


def test_javascript_facts() -> None:
    source = (
        'const express = require("express");\nimport pg from "pg";\n'
        'import { S3Client } from "@aws-sdk/client-s3";\nimport local from "./local";\n'
        'const url = process.env.DB_URL || "secret=hunter2";\n'
        'const other = process.env["OTHER"];\n'
        'fs.writeFileSync("/tmp/x", "y");\n'
        'app.get("/health", (req, res) => res.send("ok"));\n'
        "app.listen(process.env.PORT || 4000);\n"
    )
    facts = javascript.extract("s.js", source)
    assert {
        ("framework", "express"),
        ("datastore", "postgres"),
        ("object_store", "s3"),
        ("env_var", "DB_URL"),
        ("env_var", "OTHER"),
        ("env_var", "PORT"),
        ("local_state", "<file write>"),
        ("health_endpoint", "/health"),
        ("port", "4000"),
    } <= pairs(facts)
    assert "hunter2" not in "".join(e.snippet for f in facts for e in f.evidence)


def test_typescript_is_parsed() -> None:
    facts = javascript.extract("a.ts", 'import express from "express";\nconst n: number = 1;\n')
    assert ("framework", "express") in pairs(facts)


def test_dockerfile_facts_keep_env_names_only() -> None:
    source = (
        "FROM node:20 AS build\nRUN npm ci\nFROM node:20-slim\n"
        "ENV API_KEY=supersecret MODE=prod\nENV LEGACY value\nEXPOSE 3000/tcp 9229\n"
    )
    facts = docker.extract("Dockerfile", source)
    assert {
        ("runtime", "node:20-slim"),
        ("port", "3000"),
        ("port", "9229"),
        ("env_var", "API_KEY"),
        ("env_var", "MODE"),
        ("env_var", "LEGACY"),
    } <= pairs(facts)
    assert "supersecret" not in "".join(e.snippet for f in facts for e in f.evidence)


def test_requirements_extras_and_unknown_packages() -> None:
    facts = manifests.extract_requirements(
        "requirements.txt", "# c\ncelery[redis]>=5\nrequests==2\nsomething-obscure\n-r other.txt\n"
    )
    assert pairs(facts) == {
        ("worker", "celery"),
        ("cache", "redis"),
        ("external_call", "http-client"),
    }


def test_pyproject_and_package_json() -> None:
    py = manifests.extract_pyproject(
        "pyproject.toml", '[project]\nname = "x"\ndependencies = ["fastapi>=0.1", "asyncpg"]\n'
    )
    assert pairs(py) == {("framework", "fastapi"), ("datastore", "postgres")}
    js = manifests.extract_package_json(
        "package.json",
        '{"dependencies": {"pg": "1", "pg-pool": "1"}, "devDependencies": {"koa": "1"}}',
    )
    assert pairs(js) == {("datastore", "postgres")}  # dev dependencies do not shape production


def test_env_file_keeps_names_never_values() -> None:
    facts = manifests.extract_env_file(
        ".env", "# c\nexport A=1\nB=postgres://u:hunter2@h/d\nbad line\n"
    )
    assert {f.value for f in facts} == {"A", "B"}
    assert "hunter2" not in "".join(e.snippet for f in facts for e in f.evidence)


def test_compose_ports_env_and_infra_usage() -> None:
    source = (
        "services:\n"
        "  api:\n    build: ./api\n    ports: ['80:8000']\n"
        "    environment:\n      CACHE_URL: redis://redis:6379\n      DB_PASSWORD: hunter2\n"
        "  other:\n    build: ./other\n    depends_on: [redis]\n"
        "  redis:\n    image: redis:7\n"
    )
    result = compose.extract("docker-compose.yml", source)
    assert ("port", "8000") in pairs(result.per_root["api"])
    assert {"CACHE_URL", "DB_PASSWORD"} <= {f.value for f in result.per_root["api"]}
    assert ("cache", "redis") in pairs(result.per_root["api"])
    assert ("cache", "redis") in pairs(result.per_root["other"])
    assert sorted(result.users["redis"]) == ["api", "other"]
    dumped = "".join(e.snippet for fs in result.per_root.values() for f in fs for e in f.evidence)
    assert "hunter2" not in dumped


def test_invalid_compose_raises() -> None:
    with pytest.raises(ExtractionError):
        compose.extract("docker-compose.yml", "services: [unclosed")


def test_frontend_build_tools_in_dev_dependencies_become_framework_facts() -> None:
    source = (
        '{"dependencies": {"react": "18", "pg": "8"}, '
        '"devDependencies": {"vite": "5", "koa": "2", "eslint": "9"}}'
    )
    facts = manifests.extract_package_json("package.json", source)
    assert pairs(facts) == {
        ("framework", "react"),
        ("framework", "vite"),
        ("datastore", "postgres"),
    }  # koa is a dev dependency and not a frontend tool; eslint is unknown


def test_each_static_site_generator_is_named() -> None:
    names = {
        "react-scripts": "create-react-app",
        "@vue/cli-service": "vue-cli",
        "@angular/cli": "angular",
        "astro": "astro",
        "gatsby": "gatsby",
        "@docusaurus/core": "docusaurus",
        "next": "next.js",
    }
    for package, value in names.items():
        facts = manifests.extract_package_json(
            "package.json", f'{{"devDependencies": {{"{package}": "1"}}}}'
        )
        assert ("framework", value) in pairs(facts), package


def test_python_ui_frameworks_and_outbound_libraries_are_classified() -> None:
    source = "import streamlit as st\nimport yfinance as yf\nimport torch\nimport pandas\n"
    facts = pairs(python_facts.extract("app.py", source))
    assert ("framework", "streamlit") in facts
    assert ("external_call", "http-client") in facts  # yfinance downloads market data over HTTP
    assert ("dependency", "torch") in facts  # a heavy ML framework: image size and memory matter
    assert not any(value == "pandas" for _, value in facts)


def test_requirements_list_the_same_things() -> None:
    facts = manifests.extract_requirements(
        "requirements.txt", "pandas\nyfinance\nmatplotlib\nstreamlit\ntorch\n"
    )
    assert pairs(facts) == {
        ("external_call", "http-client"),
        ("framework", "streamlit"),
        ("dependency", "torch"),
    }
