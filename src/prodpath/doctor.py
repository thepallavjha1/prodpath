"""`prodpath doctor`: checks the local setup. Talks to localhost Ollama and runs nvidia-smi only."""

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from prodpath.iac_check import DEFAULT_MIRROR, MIRROR_COMMAND
from prodpath.llm import OLLAMA_URL

VRAM_FIT_RATIO = 0.85  # leave room for the KV cache and the desktop's own GPU use


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "fail"
    detail: str


def read_vram(run: Callable[..., subprocess.CompletedProcess[str]]) -> tuple[str, int] | None:
    """(gpu name, total MiB) of the first NVIDIA GPU, or None when nvidia-smi is unavailable."""
    try:
        result = run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        )  # fmt: skip
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    first = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    name, _, total = first.rpartition(",")
    return (name.strip(), int(total)) if total.strip().isdigit() else None


def _model_checks(client: httpx.Client, model: str) -> tuple[list[Check], int | None]:
    try:
        response = client.get("/api/tags")
        response.raise_for_status()
    except httpx.HTTPError as error:
        detail = f"cannot reach {OLLAMA_URL} ({type(error).__name__}). Run `ollama serve`."
        return [Check("ollama", "fail", detail)], None
    models = {m["name"]: int(m.get("size", 0)) for m in response.json().get("models", [])}
    checks = [Check("ollama", "ok", f"reachable, {len(models)} models installed")]
    wanted = model if ":" in model else f"{model}:latest"
    if wanted not in models:
        installed = ", ".join(sorted(models)) or "none"
        detail = f"{model} is not installed (installed: {installed}). Run `ollama pull {model}`."
        return [*checks, Check("model", "fail", detail)], None
    size = models[wanted]
    checks.append(Check("model", "ok", f"{wanted} installed ({size / 1e9:.1f} GB)"))
    return checks, size


def run_doctor(
    model: str,
    client: httpx.Client | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    mirror: Path = DEFAULT_MIRROR,
) -> list[Check]:
    client = client or httpx.Client(base_url=OLLAMA_URL, timeout=5.0)
    checks, model_bytes = _model_checks(client, model)
    gpu = read_vram(run)
    if gpu is None:
        checks.append(Check("gpu", "warn", "no NVIDIA GPU found via nvidia-smi; models run on CPU"))
    else:
        name, vram_mib = gpu
        checks.append(Check("gpu", "ok", f"{name}, {vram_mib} MiB VRAM"))
        if model_bytes and model_bytes > vram_mib * 1024 * 1024 * VRAM_FIT_RATIO:
            checks.append(
                Check(
                    "fit",
                    "warn",
                    f"{model} ({model_bytes / 1e9:.1f} GB) is larger than "
                    f"{VRAM_FIT_RATIO:.0%} of VRAM; it will spill to CPU and be slow",
                )
            )
        elif model_bytes:
            checks.append(Check("fit", "ok", f"{model} fits in VRAM"))
    if which("terraform"):
        checks.append(Check("terraform", "ok", "found on PATH"))
    else:
        checks.append(
            Check(
                "terraform", "warn", "not on PATH; fmt and validate of generated code are skipped"
            )
        )
    if mirror.is_dir():
        checks.append(Check("tf-mirror", "ok", f"provider mirror found at {mirror}"))
    else:
        detail = f"no provider mirror at {mirror}; validate is skipped. " + MIRROR_COMMAND.format(
            mirror=mirror
        )
        checks.append(Check("tf-mirror", "warn", detail))
    return checks


def format_checks(checks: list[Check]) -> str:
    return "\n".join(f"[{c.status:<4}] {c.name:<9} {c.detail}" for c in checks)
