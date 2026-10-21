"""docker-compose -> facts per build-context root, plus which infra services each one uses.

Environment *values* are never stored. They are tested for a hostname reference (to find which
service talks to which image-only service like redis) only on URL-like keys, then dropped.
"""

import posixpath
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from prodpath.facts import ExtractionError, find_line, make_fact
from prodpath.models import Fact, FactKind

IMAGE_KINDS: dict[str, tuple[FactKind, str]] = {
    "postgres": ("datastore", "postgres"),
    "mysql": ("datastore", "mysql"),
    "mariadb": ("datastore", "mysql"),
    "mongo": ("datastore", "mongodb"),
    "redis": ("cache", "redis"),
    "valkey": ("cache", "redis"),
    "memcached": ("cache", "memcached"),
    "rabbitmq": ("queue", "rabbitmq"),
    "kafka": ("queue", "kafka"),
    "minio": ("object_store", "minio"),
}
URL_LIKE_KEY = re.compile(r"(_URL|_URI|_HOST|_ADDR|_DSN|_ENDPOINT)$", re.IGNORECASE)


@dataclass
class ComposeResult:
    per_root: dict[str, list[Fact]] = field(default_factory=dict)  # build-context root -> facts
    infra: dict[str, Fact] = field(default_factory=dict)  # infra service name -> its Fact
    users: dict[str, list[str]] = field(default_factory=dict)  # infra service name -> roots


def _environment_names(spec: dict[str, Any]) -> dict[str, bool]:
    """Variable name -> True when its value is a URL-like reference worth host-matching."""
    env = spec.get("environment") or {}
    pairs: list[tuple[str, str]] = []
    if isinstance(env, dict):
        pairs = [(str(k), str(v)) for k, v in env.items()]
    elif isinstance(env, list):
        pairs = [(str(i).split("=", 1)[0], str(i).split("=", 1)[-1]) for i in env]
    return {name: URL_LIKE_KEY.search(name) is not None for name, _ in pairs}


def _references_host(spec: dict[str, Any], infra_name: str) -> bool:
    env = spec.get("environment") or {}
    items = (
        env.items()
        if isinstance(env, dict)
        else [str(i).split("=", 1) for i in env if "=" in str(i)]
    )
    pattern = re.compile(rf"(//|@){re.escape(infra_name)}([:/]|$)|^{re.escape(infra_name)}$")
    return any(URL_LIKE_KEY.search(str(k)) and pattern.search(str(v)) for k, v in items)


def _depends_on(spec: dict[str, Any]) -> list[str]:
    depends = spec.get("depends_on") or []
    return list(depends) if isinstance(depends, list | dict) else []


def _port_values(spec: dict[str, Any]) -> list[str]:
    ports: list[str] = []
    for entry in [*(spec.get("ports") or []), *(spec.get("expose") or [])]:
        container = str(entry).split(":")[-1].split("/")[0]
        if container.isdigit():
            ports.append(container)
    return ports


def build_context_root(compose_path: str, build: Any) -> str:
    context = build if isinstance(build, str) else build.get("context", ".")
    # Same resolution as detect.py; duplicated on purpose because stages never import each other.
    return posixpath.normpath(posixpath.join(posixpath.dirname(compose_path) or ".", context))


def extract(path: str, source: str) -> ComposeResult:
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as error:
        raise ExtractionError(f"invalid YAML: {error}") from error
    services = data.get("services") if isinstance(data, dict) else None
    result = ComposeResult()
    if not isinstance(services, dict):
        return result
    lines = source.splitlines()

    for name, spec in sorted(services.items()):
        image = str(spec.get("image", "")) if isinstance(spec, dict) else ""
        kind = IMAGE_KINDS.get(image.split("/")[-1].split(":")[0])
        if isinstance(spec, dict) and not spec.get("build") and kind:
            line = find_line(lines, f"{name}:")
            result.infra[name] = make_fact(kind[0], kind[1], path, line, f"{name}: image {image}")

    for name, spec in sorted(services.items()):
        if not isinstance(spec, dict) or not spec.get("build"):
            continue
        root = build_context_root(path, spec["build"])
        facts = result.per_root.setdefault(root, [])
        for port in _port_values(spec):
            facts.append(
                make_fact("port", port, path, find_line(lines, port), f"{name}: port {port}")
            )
        for var in sorted(_environment_names(spec)):
            line = find_line(lines, var)
            facts.append(make_fact("env_var", var, path, line, f"{name}: environment {var}"))
        for infra_name, fact in result.infra.items():
            if infra_name in _depends_on(spec) or _references_host(spec, infra_name):
                result.users.setdefault(infra_name, []).append(root)
                facts.append(fact)
    return result
