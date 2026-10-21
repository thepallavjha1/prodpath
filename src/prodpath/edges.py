"""Edges between services and shared infra, derived from facts. Pure functions, no I/O."""

import re

from prodpath.models import Edge, Fact, Service

URL_SUFFIX = re.compile(r"_(URL|URI|HOST|ADDR|ENDPOINT)$")
INFRA_VIA = {"datastore": "db", "cache": "cache", "queue": "queue", "object_store": "storage"}


def infra_id(name: str) -> str:
    return f"infra:{name}"


def http_edges(services: list[Service]) -> list[Edge]:
    """An env var like BILLING_URL in service A points at service B when B's id ends in 'billing'.

    Heuristic by nature: names are the only signal available without reading values.
    """
    edges = []
    for source in services:
        for fact in source.facts:
            if fact.kind != "env_var" or not URL_SUFFIX.search(fact.value):
                continue
            token = URL_SUFFIX.sub("", fact.value).lower().replace("_", "-")
            for target in services:
                if target.id != source.id and target.id.endswith(token) and token:
                    edges.append(
                        Edge(src=source.id, dst=target.id, via="http", evidence=fact.evidence)
                    )
    return edges


def infra_edges(shared: dict[str, tuple[Fact, list[str]]]) -> list[Edge]:
    """shared maps infra name -> (its fact, ids of services using it)."""
    edges = []
    for name, (fact, users) in sorted(shared.items()):
        via = INFRA_VIA.get(fact.kind)
        if via is None:
            continue
        for user in sorted(users):
            edges.append(Edge(src=user, dst=infra_id(name), via=via, evidence=fact.evidence))
    return edges
