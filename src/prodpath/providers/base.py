from typing import Protocol

from prodpath.forecast import UsageBook
from prodpath.models import Architecture, Forecast, Prefs, Step, SystemModel, Trap


class Provider(Protocol):
    """Everything cloud-specific lives behind this (ADR-005)."""

    name: str

    def choose(self, system: SystemModel, prefs: Prefs) -> Architecture: ...

    def steps(self, arch: Architecture) -> list[Step]: ...

    def iac_gaps(self, arch: Architecture) -> list[str]: ...

    def render_iac(self, arch: Architecture) -> dict[str, str]: ...

    def forecast(self, arch: Architecture, system: SystemModel, usage: UsageBook) -> Forecast: ...

    def traps(self, arch: Architecture, system: SystemModel, forecast: Forecast) -> list[Trap]: ...
