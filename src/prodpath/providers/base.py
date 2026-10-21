from typing import Protocol

from prodpath.models import Architecture, Prefs, Step, SystemModel


class Provider(Protocol):
    """Everything cloud-specific lives behind this (ADR-005).

    Only the methods implemented so far are declared. forecast, traps and render_iac join
    in Phases 5 and 6 (see ARCHITECTURE section 8).
    """

    name: str

    def choose(self, system: SystemModel, prefs: Prefs) -> Architecture: ...

    def steps(self, arch: Architecture) -> list[Step]: ...
