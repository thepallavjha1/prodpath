from typing import Protocol

from prodpath.models import Architecture, Prefs, Step, SystemModel


class Provider(Protocol):
    """Everything cloud-specific lives behind this (ADR-005).

    Only the methods implemented so far are declared. forecast and traps join in Phase 6
    (see ARCHITECTURE section 8).
    """

    name: str

    def choose(self, system: SystemModel, prefs: Prefs) -> Architecture: ...

    def steps(self, arch: Architecture) -> list[Step]: ...

    def iac_gaps(self, arch: Architecture) -> list[str]: ...

    def render_iac(self, arch: Architecture) -> dict[str, str]: ...
