from prodpath.models import Architecture, Prefs, Step, SystemModel
from prodpath.providers.aws.iac import iac_gaps, render_iac
from prodpath.providers.aws.rules import choose_architecture
from prodpath.providers.aws.steps import build_steps


class AwsProvider:
    name = "aws"

    def choose(self, system: SystemModel, prefs: Prefs) -> Architecture:
        return choose_architecture(system, prefs)

    def steps(self, arch: Architecture) -> list[Step]:
        return build_steps(arch)

    def iac_gaps(self, arch: Architecture) -> list[str]:
        return iac_gaps(arch)

    def render_iac(self, arch: Architecture) -> dict[str, str]:
        return render_iac(arch)
