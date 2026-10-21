from pathlib import Path

from prodpath.providers.aws import AwsProvider
from prodpath.providers.aws.pricing import DEFAULT_PRICE_DIR
from prodpath.providers.base import Provider

PROVIDER_NAMES = ["aws"]


def get_provider(name: str, price_dir: Path = DEFAULT_PRICE_DIR) -> Provider:
    if name == "aws":
        return AwsProvider(price_dir)
    available = ", ".join(PROVIDER_NAMES)
    raise ValueError(f"unknown provider {name!r}; available: {available}")
