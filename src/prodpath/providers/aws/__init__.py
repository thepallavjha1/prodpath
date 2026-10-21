from pathlib import Path

from prodpath.forecast import UsageBook
from prodpath.models import Architecture, Forecast, Prefs, Step, SystemModel, Trap
from prodpath.providers.aws.costs import build_forecast
from prodpath.providers.aws.iac import iac_gaps, render_iac
from prodpath.providers.aws.pricing import DEFAULT_PRICE_DIR, PriceBook, snapshot_path
from prodpath.providers.aws.rules import choose_architecture
from prodpath.providers.aws.steps import build_steps
from prodpath.providers.aws.traps import TrapContext, find_traps


class AwsProvider:
    name = "aws"

    def __init__(self, price_dir: Path = DEFAULT_PRICE_DIR) -> None:
        self._price_dir = price_dir
        self._books: dict[str, PriceBook] = {}

    def price_book(self, region: str) -> PriceBook:
        if region not in self._books:
            self._books[region] = PriceBook.load(snapshot_path(self._price_dir, region))
        return self._books[region]

    def choose(self, system: SystemModel, prefs: Prefs) -> Architecture:
        return choose_architecture(system, prefs)

    def steps(self, arch: Architecture) -> list[Step]:
        return build_steps(arch)

    def iac_gaps(self, arch: Architecture) -> list[str]:
        return iac_gaps(arch)

    def render_iac(self, arch: Architecture) -> dict[str, str]:
        return render_iac(arch)

    def forecast(self, arch: Architecture, system: SystemModel, usage: UsageBook) -> Forecast:
        return build_forecast(arch, system, usage, self.price_book(arch.region))

    def traps(self, arch: Architecture, system: SystemModel, forecast: Forecast) -> list[Trap]:
        context = TrapContext(arch, system, forecast, self.price_book(arch.region))
        return find_traps(context)
