from prodpath.providers.aws import AwsProvider
from prodpath.providers.base import Provider

PROVIDERS: dict[str, Provider] = {"aws": AwsProvider()}


def get_provider(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"unknown provider {name!r}; available: {', '.join(sorted(PROVIDERS))}"
        ) from None
