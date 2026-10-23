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


VITE_PACKAGE = (
    '{"name": "site", "scripts": {"build": "vite build"}, '
    '"dependencies": {"react": "^18"}, "devDependencies": {"vite": "^5"}}'
)


def test_standalone_vite_app_is_a_static_site(tmp_path: Path) -> None:
    files = {"frontend/package.json": VITE_PACKAGE, "frontend/src/main.jsx": "render()\n"}
    assert detect(tmp_path, files) == {"frontend": "static"}


def test_vite_app_at_the_repo_root_is_static(tmp_path: Path) -> None:
    assert detect(tmp_path, {"package.json": VITE_PACKAGE}) == {"root": "static"}


def test_workspace_member_with_a_build_tool_is_static_and_plain_packages_stay_libs(
    tmp_path: Path,
) -> None:
    files = {
        "pnpm-workspace.yaml": 'packages:\n  - "apps/*"\n  - "packages/*"\n',
        "package.json": '{"name": "root", "private": true}',
        "apps/web/package.json": VITE_PACKAGE,
        "packages/ui/package.json": '{"name": "ui", "dependencies": {"react": "^18"}}',
    }
    assert detect(tmp_path, files) == {"apps-web": "static", "packages-ui": "lib"}


def test_a_build_tool_without_a_build_script_is_not_a_site(tmp_path: Path) -> None:
    files = {"tool/package.json": '{"name": "t", "devDependencies": {"vite": "^5"}}'}
    assert detect(tmp_path, files) == {"tool": "lib"}


def test_a_frontend_with_its_own_server_stays_web(tmp_path: Path) -> None:
    files = {
        "app/package.json": VITE_PACKAGE,
        "app/server.js": "require('http').createServer().listen(3000)\n",
    }
    assert detect(tmp_path, files) == {"app": "web"}


def test_next_with_static_export_is_static_and_ssr_next_is_web(tmp_path: Path) -> None:
    next_package = (
        '{"name": "n", "scripts": {"build": "next build"}, "dependencies": {"next": "14"}}'
    )
    files = {
        "marketing/package.json": next_package,
        "marketing/next.config.js": 'module.exports = { output: "export" };\n',
        "dashboard/package.json": next_package,
        "dashboard/next.config.js": "module.exports = {};\n",
    }
    assert detect(tmp_path, files) == {"dashboard": "web", "marketing": "static"}


def test_a_dockerfile_that_copies_a_build_into_nginx_html_is_static(tmp_path: Path) -> None:
    dockerfile = (
        "FROM node:20 AS build\nRUN npm run build\n"
        "FROM nginx:1.27\nCOPY --from=build /app/dist /usr/share/nginx/html\nEXPOSE 80\n"
    )
    assert detect(tmp_path, {"docs/Dockerfile": dockerfile}) == {"docs": "static"}


def test_nginx_as_a_reverse_proxy_is_not_a_static_site(tmp_path: Path) -> None:
    dockerfile = "FROM nginx:1.27\nCOPY proxy.conf /etc/nginx/conf.d/default.conf\nEXPOSE 80\n"
    assert detect(tmp_path, {"proxy/Dockerfile": dockerfile}) == {"proxy": "web"}


def test_static_detection_records_the_matching_line_as_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_files(repo, {"frontend/package.json": VITE_PACKAGE.replace(", ", ",\n")})
    services, _, _ = scan_and_detect(repo, tmp_path / "c.sqlite")
    evidence = services[0].evidence[0]
    assert evidence.path == "frontend/package.json" and "vite" in evidence.snippet
    assert services[0].certainty == "heuristic"


STREAMLIT_APP = (
    "import streamlit as st\n\nst.set_page_config(layout='wide')\nst.title('Simulator')\n"
)


def test_a_streamlit_app_is_a_web_service(tmp_path: Path) -> None:
    files = {
        "simulator/app.py": STREAMLIT_APP,
        "simulator/requirements.txt": "pandas\nstreamlit\ntorch\n",
        "train.py": "import torch\n",
    }
    assert detect(tmp_path, files) == {"simulator": "web"}  # the training script is not a service


def test_other_python_ui_frameworks_are_web_services_too(tmp_path: Path) -> None:
    files = {
        "demo/app.py": "import gradio as gr\ngr.Interface(lambda x: x, 'text', 'text').launch()\n",
        "dash_app/app.py": "from dash import Dash\napp = Dash(__name__)\n",
        "bot/app.py": "import chainlit as cl\n",
    }
    assert detect(tmp_path, files) == {"bot": "web", "dash_app": "web", "demo": "web"}


def test_streamlit_app_py_is_also_recognised_by_its_conventional_name(tmp_path: Path) -> None:
    files = {"ui/streamlit_app.py": STREAMLIT_APP}
    assert detect(tmp_path, files) == {"ui": "web"}
