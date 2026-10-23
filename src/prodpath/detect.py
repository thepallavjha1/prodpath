"""Stage 2: turn an inventory into service candidates. Deterministic, no LLM.

Rule order follows ARCHITECTURE section 6; the first rule to claim a root wins.
"""

import fnmatch
import json
import logging
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from prodpath.models import Evidence, Inventory, ServiceCandidate

log = logging.getLogger(__name__)

Kind = Literal["web", "worker", "cron", "static", "lib", "unknown"]
Certainty = Literal["parsed", "heuristic"]

MAX_READ_BYTES = 1024 * 1024
ENTRYPOINT_FILES = {"main.py", "app.py", "streamlit_app.py", "server.js", "main.go"}
SERVER_MARKERS = (
    ".listen(",
    "app.run(",
    "uvicorn",
    "Flask(",
    "FastAPI(",
    "ListenAndServe",
    "createServer",
    # Python UI frameworks that serve themselves (default ports in providers/aws/rules.py)
    "import streamlit",
    "from streamlit",
    "import gradio",
    "from gradio",
    "import dash",
    "from dash",
    "import chainlit",
    "from nicegui",
    "import nicegui",
)
DEPENDENCY_MANIFESTS = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
}
STATIC_BUILD_TOOLS = {
    "@angular/cli",
    "@docusaurus/core",
    "@sveltejs/adapter-static",
    "@vue/cli-service",
    "astro",
    "gatsby",
    "react-scripts",
    "vite",
    "vitepress",
    "vuepress",
}
# Where nginx/httpd serve files from: a Dockerfile copying a build here is a static site.
STATIC_HTML_DIRS = ("/usr/share/nginx/html", "/usr/local/apache2/htdocs", "/var/www/html")
STATIC_SERVER_IMAGES = ("nginx", "httpd", "caddy")
NEXT_CONFIGS = {"next.config.js", "next.config.mjs", "next.config.cjs", "next.config.ts"}
NEXT_EXPORT = re.compile(r"""output\s*:\s*["']export["']""")
K8S_KINDS: dict[str, Kind] = {"Deployment": "worker", "StatefulSet": "worker", "CronJob": "cron"}


@dataclass
class Repo:
    root: Path
    by_dir: dict[str, set[str]]  # dir -> file basenames directly inside it
    claimed: dict[str, ServiceCandidate] = field(default_factory=dict)  # service root -> candidate

    @property
    def paths(self) -> list[str]:
        return sorted(_join(d, name) for d, names in self.by_dir.items() for name in names)

    def read(self, rel_path: str) -> str:
        data = (self.root / rel_path).read_bytes()[:MAX_READ_BYTES]
        return data.decode("utf-8", errors="replace")

    def is_inside_claimed(self, root: str) -> bool:
        return any(_is_within(root, other) for other in self.claimed)

    def claim(self, root: str, kind: Kind, certainty: Certainty, evidence: Evidence) -> None:
        if root in self.claimed:
            return
        self.claimed[root] = ServiceCandidate(
            id=slugify(root), root=root, kind=kind, certainty=certainty, evidence=[evidence]
        )


def slugify(root: str) -> str:
    return "root" if root == "." else root.strip("/").replace("/", "-")


def _join(directory: str, name: str) -> str:
    return name if directory == "." else f"{directory}/{name}"


def _is_within(path: str, ancestor: str) -> bool:
    return ancestor == "." or path == ancestor or path.startswith(ancestor + "/")


def _evidence(repo: Repo, path: str, needle: str, fallback: str) -> Evidence:
    lines = repo.read(path).splitlines()
    for number, line in enumerate(lines, start=1):
        if needle in line:
            return Evidence(path=path, line=number, snippet=line.strip()[:200])
    return Evidence(path=path, line=None, snippet=fallback[:200])


def _is_dockerfile(name: str) -> bool:
    return name == "Dockerfile" or name.startswith("Dockerfile.")


def _serves_static_files(dockerfile: str) -> bool:
    """The final stage is a plain web server and a build is copied into its html directory."""
    images = [
        line.split()[1].lower()
        for line in dockerfile.splitlines()
        if line.strip().upper().startswith("FROM ") and len(line.split()) > 1
    ]
    final_is_server = bool(images) and images[-1].startswith(STATIC_SERVER_IMAGES)
    return final_is_server and any(d in dockerfile for d in STATIC_HTML_DIRS)


def classify_kind(repo: Repo, root: str, has_ports: bool = False) -> Kind:
    """cron with a crontab; static for a build in nginx html; web if exposed; else worker."""
    files = repo.by_dir.get(root, set())
    if "crontab" in files:
        return "cron"
    dockerfiles = [_join(root, name) for name in sorted(files) if _is_dockerfile(name)]
    if any(_serves_static_files(repo.read(path)) for path in dockerfiles):
        return "static"
    if any("EXPOSE" in repo.read(path) for path in dockerfiles):
        return "web"
    return "web" if has_ports else "worker"


def detect_from_compose(repo: Repo) -> None:
    for path in repo.paths:
        base = posixpath.basename(path)
        is_compose = base.startswith(("docker-compose", "compose"))
        if not (is_compose and base.endswith((".yml", ".yaml"))):
            continue
        try:
            data = yaml.safe_load(repo.read(path))
        except yaml.YAMLError as error:
            log.warning("skipping unparsable compose file %s: %s", path, error)
            continue
        services = data.get("services") if isinstance(data, dict) else None
        for name, spec in sorted((services or {}).items()):
            build = spec.get("build") if isinstance(spec, dict) else None
            if not build:
                continue  # image-only services (redis, postgres) are infra, not our code
            context = build if isinstance(build, str) else build.get("context", ".")
            root = posixpath.normpath(posixpath.join(posixpath.dirname(path) or ".", context))
            kind = classify_kind(repo, root, has_ports=bool(spec.get("ports")))
            repo.claim(root, kind, "parsed", _evidence(repo, path, f"{name}:", f"service {name}"))


def detect_from_dockerfiles(repo: Repo) -> None:
    for path in repo.paths:
        if not _is_dockerfile(posixpath.basename(path)):
            continue
        root = posixpath.dirname(path) or "."
        needle = "EXPOSE" if "EXPOSE" in repo.read(path) else "FROM"
        repo.claim(root, classify_kind(repo, root), "parsed", _evidence(repo, path, needle, path))


def detect_from_k8s(repo: Repo) -> None:
    for path in repo.paths:
        base = posixpath.basename(path)
        if not base.endswith((".yaml", ".yml")) or base.startswith(("docker-compose", "compose")):
            continue
        try:
            documents = list(yaml.safe_load_all(repo.read(path)))
        except yaml.YAMLError:
            continue  # Helm templates ({{ }}) and non-manifest YAML land here; not an error
        for doc in documents:
            if isinstance(doc, dict) and doc.get("kind") in K8S_KINDS and "apiVersion" in doc:
                root = posixpath.dirname(path) or "."
                evidence = _evidence(repo, path, f"kind: {doc['kind']}", doc["kind"])
                repo.claim(root, K8S_KINDS[doc["kind"]], "parsed", evidence)


def _workspace_globs(repo: Repo) -> list[tuple[str, str, str]]:
    """(manifest path, workspace dir, glob) from pnpm-workspace.yaml and package.json."""
    found: list[tuple[str, str, str]] = []
    for path in repo.paths:
        base, where = posixpath.basename(path), posixpath.dirname(path) or "."
        if base == "pnpm-workspace.yaml":
            data = yaml.safe_load(repo.read(path)) or {}
            found += [(path, where, g) for g in data.get("packages", [])]
        elif base == "package.json":
            try:
                data = json.loads(repo.read(path))
            except json.JSONDecodeError:
                continue
            workspaces: Any = data.get("workspaces", []) if isinstance(data, dict) else []
            globs = workspaces.get("packages", []) if isinstance(workspaces, dict) else workspaces
            found += [(path, where, g) for g in globs]
    return found


def _find_entrypoint(repo: Repo, root: str) -> Evidence | None:
    for name in sorted(repo.by_dir.get(root, set()) & ENTRYPOINT_FILES):
        path = _join(root, name)
        text = repo.read(path)
        for marker in SERVER_MARKERS:
            if marker in text:
                return _evidence(repo, path, marker, name)
    return None


def _package_json(repo: Repo, root: str) -> dict[str, Any] | None:
    if "package.json" not in repo.by_dir.get(root, set()):
        return None
    try:
        data = json.loads(repo.read(_join(root, "package.json")))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _frontend_kind(repo: Repo, root: str) -> tuple[Kind, Evidence] | None:
    """static for a built site, web for server-rendered Next.js, None when it is not a frontend."""
    data = _package_json(repo, root)
    if data is None or _find_entrypoint(repo, root) is not None:
        return None  # not a package, or it brings its own server (then it is a web service)
    path = _join(root, "package.json")
    dependencies = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    if "next" in dependencies:
        for name in sorted(repo.by_dir.get(root, set()) & NEXT_CONFIGS):
            config = _join(root, name)
            if NEXT_EXPORT.search(repo.read(config)):
                return "static", _evidence(repo, config, "export", config)
        return "web", _evidence(repo, path, '"next"', path)
    scripts = data.get("scripts")
    tool = next((t for t in sorted(STATIC_BUILD_TOOLS) if t in dependencies), None)
    if tool and isinstance(scripts, dict) and "build" in scripts:
        return "static", _evidence(repo, path, f'"{tool}"', path)
    return None


def detect_from_workspaces(repo: Repo) -> set[str]:
    """Claim workspace members; return workspace root dirs (never services themselves)."""
    workspace_roots: set[str] = set()
    package_dirs = sorted(d for d, files in repo.by_dir.items() if "package.json" in files)
    for manifest, where, pattern in _workspace_globs(repo):
        workspace_roots.add(where)
        for directory in package_dirs:
            if directory == where or not _is_within(directory, where):
                continue
            relative = directory if where == "." else directory.removeprefix(where + "/")
            if fnmatch.fnmatch(relative, pattern.removeprefix("./")):
                if (frontend := _frontend_kind(repo, directory)) is not None:
                    repo.claim(directory, frontend[0], "heuristic", frontend[1])
                    continue
                # A member with a listening server is deployable; the rest are libraries.
                kind: Kind = "web" if _find_entrypoint(repo, directory) else "lib"
                evidence = _evidence(repo, manifest, pattern.split("*")[0].rstrip("/"), manifest)
                repo.claim(directory, kind, "heuristic", evidence)
    for directory, files in sorted(repo.by_dir.items()):
        if "pyproject.toml" in files and directory not in workspace_roots:
            path = _join(directory, "pyproject.toml")
            repo.claim(directory, "lib", "heuristic", _evidence(repo, path, "name", path))
    return workspace_roots


def detect_from_entrypoints(repo: Repo) -> None:
    for directory, files in sorted(repo.by_dir.items()):
        if repo.is_inside_claimed(directory):
            continue  # code inside an already-claimed service is part of it
        if "Procfile" in files:
            path = _join(directory, "Procfile")
            kind: Kind = "worker" if repo.read(path).lstrip().startswith("worker") else "web"
            repo.claim(directory, kind, "parsed", _evidence(repo, path, ":", path))
        elif "serverless.yml" in files:
            path = _join(directory, "serverless.yml")
            repo.claim(directory, "web", "heuristic", _evidence(repo, path, "service", path))
        elif (found := _find_entrypoint(repo, directory)) is not None:
            repo.claim(directory, "web", "heuristic", found)


def detect_leftover_manifests(repo: Repo, workspace_roots: set[str]) -> None:
    for directory, files in sorted(repo.by_dir.items()):
        manifests = sorted(files & DEPENDENCY_MANIFESTS)
        if not manifests or directory in workspace_roots or repo.is_inside_claimed(directory):
            continue
        if (frontend := _frontend_kind(repo, directory)) is not None:
            repo.claim(directory, frontend[0], "heuristic", frontend[1])
            continue
        kind: Kind = "unknown" if manifests == ["requirements.txt"] else "lib"
        path = _join(directory, manifests[0])
        repo.claim(directory, kind, "heuristic", Evidence(path=path, snippet=manifests[0]))


def detect_services(repo_path: Path, inventory: Inventory) -> list[ServiceCandidate]:
    by_dir: dict[str, set[str]] = {}
    for entry in inventory.files:
        by_dir.setdefault(posixpath.dirname(entry.path) or ".", set()).add(
            posixpath.basename(entry.path)
        )
    repo = Repo(root=repo_path, by_dir=by_dir)
    detect_from_compose(repo)
    detect_from_dockerfiles(repo)
    detect_from_k8s(repo)
    workspace_roots = detect_from_workspaces(repo)
    detect_from_entrypoints(repo)
    detect_leftover_manifests(repo, workspace_roots)
    services = sorted(repo.claimed.values(), key=lambda c: c.root)
    log.info("detected %d services", len(services))
    return services
