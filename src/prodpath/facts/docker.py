"""Dockerfile -> runtime image, exposed ports and ENV variable names (never their values)."""

import re

from prodpath.facts import make_fact
from prodpath.models import Fact

ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _env_names(arguments: str) -> list[str]:
    """ENV accepts 'KEY=value KEY2=value' or the legacy 'KEY value'. Keep names only."""
    if "=" not in arguments.split(None, 1)[0]:
        return [arguments.split(None, 1)[0]]
    return [pair.split("=", 1)[0] for pair in re.findall(r'\S+=(?:"[^"]*"|\S*)', arguments)]


def extract(path: str, source: str) -> list[Fact]:
    facts: list[Fact] = []
    last_from: tuple[int, str] | None = None
    for number, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip()
        keyword, _, arguments = line.partition(" ")
        keyword = keyword.upper()
        if keyword == "FROM" and arguments:
            image = [part for part in arguments.split() if not part.startswith("--")][0]
            last_from = (number, image)  # multi-stage builds: the last stage is what runs
        elif keyword == "EXPOSE":
            for token in arguments.split():
                port = token.split("/")[0]
                if port.isdigit():
                    facts.append(make_fact("port", port, path, number, f"EXPOSE {token}"))
        elif keyword == "ENV" and arguments.strip():
            for name in _env_names(arguments.strip()):
                if ENV_NAME.fullmatch(name):
                    facts.append(make_fact("env_var", name, path, number, f"ENV {name}"))
    if last_from:
        number, image = last_from
        facts.append(make_fact("runtime", image, path, number, f"FROM {image}"))
    return facts
