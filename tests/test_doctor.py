import subprocess

import httpx

from prodpath.doctor import format_checks, run_doctor
from prodpath.llm import OLLAMA_URL

TAGS = {
    "models": [
        {"name": "small:latest", "size": 2_200_000_000},
        {"name": "big:latest", "size": 4_900_000_000},
    ]
}


def client_returning(response: httpx.Response) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: response), base_url=OLLAMA_URL)


def smi(output: str):  # type: ignore[no-untyped-def]
    def run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    return run


def no_smi(*args, **kwargs):  # type: ignore[no-untyped-def]
    raise FileNotFoundError("nvidia-smi")


def statuses(checks) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {c.name: c.status for c in checks}


def test_everything_fine() -> None:
    checks = run_doctor(
        "small",
        client_returning(httpx.Response(200, json=TAGS)),
        smi("NVIDIA GeForce GTX 1650, 4096\n"),
        lambda name: "/bin/terraform",
    )
    assert statuses(checks) == {
        "ollama": "ok", "model": "ok", "gpu": "ok", "fit": "ok", "terraform": "ok",
    }  # fmt: skip


def test_model_larger_than_vram_warns_about_cpu_spill() -> None:
    checks = run_doctor(
        "big",
        client_returning(httpx.Response(200, json=TAGS)),
        smi("GTX 1650, 4096\n"),
        lambda n: None,
    )
    assert statuses(checks)["fit"] == "warn"
    assert "spill to CPU" in format_checks(checks)
    assert statuses(checks)["terraform"] == "warn"


def test_missing_model_fails_with_pull_hint() -> None:
    checks = run_doctor(
        "nope", client_returning(httpx.Response(200, json=TAGS)), no_smi, lambda n: None
    )
    text = format_checks(checks)
    assert statuses(checks)["model"] == "fail" and "ollama pull nope" in text
    assert statuses(checks)["gpu"] == "warn"


def test_ollama_down_fails_with_start_hint() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(refuse), base_url=OLLAMA_URL)
    checks = run_doctor("small", client, no_smi, lambda n: None)
    assert statuses(checks)["ollama"] == "fail"
    assert "ollama serve" in format_checks(checks)
