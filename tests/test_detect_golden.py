import json
from pathlib import Path

import pytest

from tests.helpers import scan_and_detect

GOLDEN = Path(__file__).parent / "golden"


@pytest.mark.parametrize("name", ["mono_a", "mono_b", "mono_c"])
def test_services_match_golden(
    name: str, fixtures_dir: Path, tmp_path: Path, update_golden: bool
) -> None:
    services, _, _ = scan_and_detect(fixtures_dir / name, tmp_path / "cache.sqlite")
    actual = json.dumps([s.model_dump() for s in services], indent=2, sort_keys=True) + "\n"
    golden_file = GOLDEN / f"services_{name}.json"
    if update_golden:
        golden_file.write_text(actual, encoding="utf-8")
    assert actual == golden_file.read_text(encoding="utf-8")


def test_every_candidate_has_evidence(fixtures_dir: Path, tmp_path: Path) -> None:
    for name in ("mono_a", "mono_b", "mono_c"):
        services, _, _ = scan_and_detect(fixtures_dir / name, tmp_path / f"{name}.sqlite")
        assert services and all(s.evidence for s in services)


def test_mono_c_kinds(fixtures_dir: Path, tmp_path: Path) -> None:
    services, _, _ = scan_and_detect(fixtures_dir / "mono_c", tmp_path / "cache.sqlite")
    kinds = {s.id: s.kind for s in services}
    assert kinds["apps-reports"] == "cron"
    assert kinds["packages-shared-utils"] == "lib"
    assert sum(1 for k in kinds.values() if k == "web") == 5
