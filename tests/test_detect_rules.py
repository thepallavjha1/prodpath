from pathlib import Path

from tests.helpers import scan_and_detect, write_files


def detect(tmp_path: Path, files: dict[str, str]) -> dict[str, str]:
    repo = tmp_path / "repo"
    write_files(repo, files)
    services, _, _ = scan_and_detect(repo, tmp_path / "c.sqlite")
    return {s.id: s.kind for s in services}


def test_compose_build_context_beats_dockerfile(tmp_path: Path) -> None:
    files = {
        "docker-compose.yml": "services:\n  svc:\n    build: ./code\n    ports: ['80:80']\n"
        "  db:\n    image: postgres:16\n",
        "code/Dockerfile": "FROM python:3.12\n",
    }
    # ports in compose make it web even though the Dockerfile has no EXPOSE
    assert detect(tmp_path, files) == {"code": "web"}


def test_compose_build_dict_context(tmp_path: Path) -> None:
    files = {
        "deploy/compose.yaml": "services:\n  w:\n    build:\n      context: ../w\n",
        "w/Dockerfile": "FROM python:3.12\n",
    }
    assert detect(tmp_path, files) == {"w": "worker"}


def test_kubernetes_manifests(tmp_path: Path) -> None:
    files = {"k8s/job.yaml": "apiVersion: batch/v1\nkind: CronJob\nmetadata:\n  name: nightly\n"}
    assert detect(tmp_path, files) == {"k8s": "cron"}


def test_helm_template_does_not_crash(tmp_path: Path) -> None:
    files = {"chart/templates/d.yaml": "kind: {{ .Values.kind }}\nreplicas: {{ .Values.n }}\n"}
    assert detect(tmp_path, files) == {}


def test_package_json_workspaces_and_server_member(tmp_path: Path) -> None:
    files = {
        "package.json": '{"name": "root", "workspaces": ["services/*"]}',
        "services/api/package.json": '{"name": "api"}',
        "services/api/server.js": "require('http').createServer().listen(3000)\n",
        "services/shared/package.json": '{"name": "shared"}',
    }
    assert detect(tmp_path, files) == {"services-api": "web", "services-shared": "lib"}


def test_procfile_and_serverless(tmp_path: Path) -> None:
    files = {
        "a/Procfile": "worker: python run.py\n",
        "b/Procfile": "web: gunicorn app:app\n",
        "c/serverless.yml": "service: fn\n",
    }
    assert detect(tmp_path, files) == {"a": "worker", "b": "web", "c": "web"}


def test_entrypoint_needs_a_server_marker(tmp_path: Path) -> None:
    files = {"tool/main.py": "print('hi')\n", "srv/main.py": "app = Flask(__name__)\n"}
    assert detect(tmp_path, files) == {"srv": "web"}


def test_leftover_manifests(tmp_path: Path) -> None:
    files = {"x/requirements.txt": "requests\n", "y/go.mod": "module y\n"}
    assert detect(tmp_path, files) == {"x": "unknown", "y": "lib"}


def test_code_inside_a_claimed_service_is_not_a_second_service(tmp_path: Path) -> None:
    files = {
        "Dockerfile": "FROM python:3.12\n",
        "pkg/main.py": "app = Flask(__name__)\n",
        "pkg/requirements.txt": "flask\n",
    }
    assert detect(tmp_path, files) == {"root": "worker"}
