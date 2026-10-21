"""Python source -> facts, using stdlib `ast`.

Evidence snippets for env vars are rebuilt from the variable name, never copied from the
source line, because the line may carry a default secret (`environ.get("X", "hunter2")`).
"""

import ast

from prodpath.facts import ExtractionError, make_fact
from prodpath.facts.manifests import classify_package
from prodpath.models import Fact, FactKind

ENV_GETTERS = {"os.getenv", "os.environ.get", "environ.get", "getenv"}
ENV_MAPPINGS = {"os.environ", "environ"}
HEALTH_PATHS = ("/health", "/healthz", "/ping", "/ready", "/status")
ROUTE_METHODS = {"route", "get", "post", "put", "delete", "patch", "api_route"}
AWS_SERVICES: dict[str, tuple[FactKind, str]] = {
    "s3": ("object_store", "s3"),
    "sqs": ("queue", "sqs"),
    "sns": ("queue", "sns"),
    "dynamodb": ("datastore", "dynamodb"),
}
WRITE_MODE_CHARS = "wax+"


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _string_arg(node: ast.Call, index: int) -> str | None:
    if len(node.args) > index:
        arg = node.args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _import_facts(node: ast.Import | ast.ImportFrom, path: str, lines: list[str]) -> list[Fact]:
    if isinstance(node, ast.ImportFrom):
        modules = [] if node.level or not node.module else [node.module]
    else:
        modules = [alias.name for alias in node.names]
    facts = []
    for module in modules:
        known = classify_package(module.split(".")[0])
        if known:
            facts.append(make_fact(known[0], known[1], path, node.lineno, lines[node.lineno - 1]))
    return facts


def _open_mode(node: ast.Call) -> str | None:
    mode = _string_arg(node, 1)
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = str(keyword.value.value)
    return mode


def _call_facts(node: ast.Call, path: str) -> list[Fact]:
    name = dotted_name(node.func)
    if name is None:
        return []
    line = node.lineno
    if name in ENV_GETTERS and (var := _string_arg(node, 0)):
        return [make_fact("env_var", var, path, line, f'{name}("{var}")')]
    if name == "open":
        mode = _open_mode(node)
        if mode and any(char in mode for char in WRITE_MODE_CHARS):
            target = _string_arg(node, 0) or "<dynamic path>"
            snippet = f'open(..., "{mode}")'
            return [make_fact("local_state", target, path, line, snippet, "heuristic")]
    if name.endswith((".write_text", ".write_bytes")):
        return [make_fact("local_state", "<dynamic path>", path, line, f"{name}(...)", "heuristic")]
    if name in {"boto3.client", "boto3.resource"} and (service := _string_arg(node, 0)):
        kind, value = AWS_SERVICES.get(service, ("external_call", f"aws:{service}"))
        return [make_fact(kind, value, path, line, f'{name}("{service}")')]
    if name.endswith("run"):
        return _port_facts(node, name, path)
    return []


def _port_facts(node: ast.Call, name: str, path: str) -> list[Fact]:
    for keyword in node.keywords:
        value = keyword.value
        if (
            keyword.arg == "port"
            and isinstance(value, ast.Constant)
            and isinstance(value.value, int)
        ):
            return [
                make_fact(
                    "port", str(value.value), path, node.lineno, f"{name}(port={value.value})"
                )
            ]
    return []


def _decorator_facts(node: ast.FunctionDef | ast.AsyncFunctionDef, path: str) -> list[Fact]:
    facts = []
    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        name = dotted_name(call.func if call else decorator)
        if name is None:
            continue
        last = name.rsplit(".", 1)[-1]
        if last in {"task", "shared_task"}:
            snippet = f"@{name}"
            facts.append(make_fact("worker", "celery task", path, decorator.lineno, snippet))
        route = _string_arg(call, 0) if call else None
        if last in ROUTE_METHODS and route and route.startswith(HEALTH_PATHS):
            snippet = f'@{name}("{route}")'
            facts.append(make_fact("health_endpoint", route, path, decorator.lineno, snippet))
    return facts


def extract(path: str, source: str) -> list[Fact]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        raise ExtractionError(f"python syntax error at line {error.lineno}") from error
    lines = source.splitlines()
    facts: list[Fact] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            facts += _import_facts(node, path, lines)
        elif isinstance(node, ast.Call):
            facts += _call_facts(node, path)
        elif isinstance(node, ast.Subscript):
            base = dotted_name(node.value)
            key = node.slice
            if (
                base in ENV_MAPPINGS
                and isinstance(key, ast.Constant)
                and isinstance(key.value, str)
            ):
                facts.append(
                    make_fact("env_var", key.value, path, node.lineno, f'{base}["{key.value}"]')
                )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            facts += _decorator_facts(node, path)
    return facts
