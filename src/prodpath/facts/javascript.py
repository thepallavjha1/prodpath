"""JavaScript/TypeScript source -> facts, using tree-sitter.

As in python.py, env var snippets are rebuilt from the name so `|| "default-secret"` never
reaches the output.
"""

from collections.abc import Iterator

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from prodpath.facts import ExtractionError, make_fact
from prodpath.facts.manifests import classify_package
from prodpath.models import Fact

HEALTH_PATHS = ("/health", "/healthz", "/ping", "/ready", "/status")
ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "all", "use"}
FILE_WRITERS = {
    "fs.writeFile", "fs.writeFileSync", "fs.appendFile", "fs.appendFileSync",
    "fs.promises.writeFile", "fs.createWriteStream",
}  # fmt: skip
PARSER_BY_SUFFIX = {".ts": "typescript", ".tsx": "tsx"}


def _walk(root: Node) -> Iterator[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", errors="replace") if node and node.text else ""


def _string_value(node: Node | None) -> str | None:
    if node is None or node.type not in {"string", "template_string"}:
        return None
    return _text(node)[1:-1]


def _package_name(specifier: str) -> str | None:
    if specifier.startswith((".", "/")) or not specifier:
        return None
    parts = specifier.split("/")
    return "/".join(parts[:2]) if specifier.startswith("@") else parts[0].removeprefix("node:")


def _line(node: Node) -> int:
    return int(node.start_point[0]) + 1


def _package_fact(specifier: str | None, path: str, node: Node, lines: list[str]) -> list[Fact]:
    name = _package_name(specifier or "")
    known = classify_package(name) if name else None
    if not known:
        return []
    return [make_fact(known[0], known[1], path, _line(node), lines[_line(node) - 1])]


def _call_facts(node: Node, path: str, lines: list[str]) -> list[Fact]:
    function = node.child_by_field_name("function")
    arguments = node.child_by_field_name("arguments")
    first = arguments.named_children[0] if arguments and arguments.named_children else None
    callee = _text(function)
    if callee == "require":
        return _package_fact(_string_value(first), path, node, lines)
    if callee in FILE_WRITERS:
        return [
            make_fact(
                "local_state", "<file write>", path, _line(node), f"{callee}(...)", "heuristic"
            )
        ]
    if function is not None and function.type == "member_expression":
        method = _text(function.child_by_field_name("property"))
        route = _string_value(first)
        if method == "listen" and first is not None:
            port = next((n for n in _walk(first) if n.type == "number"), None)
            if port is not None:
                snippet = f"{callee}({_text(port)})"
                return [make_fact("port", _text(port), path, _line(node), snippet, "heuristic")]
        if method in ROUTE_METHODS and route and route.startswith(HEALTH_PATHS):
            snippet = f'{callee}("{route}")'
            return [make_fact("health_endpoint", route, path, _line(node), snippet)]
    return []


def _env_fact(node: Node, path: str) -> list[Fact]:
    """process.env.NAME and process.env["NAME"]."""
    if (
        node.type == "member_expression"
        and _text(node.child_by_field_name("object")) == "process.env"
    ):
        name = _text(node.child_by_field_name("property"))
        return [make_fact("env_var", name, path, _line(node), f"process.env.{name}")]
    if (
        node.type == "subscript_expression"
        and _text(node.child_by_field_name("object")) == "process.env"
    ):
        key = _string_value(node.child_by_field_name("index"))
        if key:
            return [make_fact("env_var", key, path, _line(node), f'process.env["{key}"]')]
    return []


def extract(path: str, source: str) -> list[Fact]:
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    parser = get_parser(PARSER_BY_SUFFIX.get(suffix, "javascript"))
    tree = parser.parse(source.encode("utf-8"))
    if tree.root_node.has_error and not tree.root_node.children:
        raise ExtractionError("javascript parse failed")
    lines = source.splitlines()
    facts: list[Fact] = []
    for node in _walk(tree.root_node):
        if node.type == "import_statement":
            facts += _package_fact(
                _string_value(node.child_by_field_name("source")), path, node, lines
            )
        elif node.type == "call_expression":
            facts += _call_facts(node, path, lines)
        elif node.type in {"member_expression", "subscript_expression"}:
            facts += _env_fact(node, path)
    return facts
