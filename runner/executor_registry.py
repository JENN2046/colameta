from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExecutorProviderInfo:
    provider: str
    display_name: str
    enabled: bool = True
    supports_model_selection: bool = False
    supports_probe: bool = False


SUPPORTED_EXECUTOR_PROVIDERS: dict[str, ExecutorProviderInfo] = {
    "pi": ExecutorProviderInfo(provider="pi", display_name="Pi", enabled=True),
    "codex": ExecutorProviderInfo(provider="codex", display_name="Codex", enabled=True),
    "opencode": ExecutorProviderInfo(provider="opencode", display_name="OpenCode", enabled=True, supports_model_selection=True, supports_probe=True),
}

DEFAULT_EXECUTION_PROVIDER = "codex"

def normalize_execution_provider(value: Any, default: str = DEFAULT_EXECUTION_PROVIDER) -> str:
    if not isinstance(value, str):
        return default
    norm = value.strip().lower()
    if norm in SUPPORTED_EXECUTOR_PROVIDERS:
        return norm
    return default


def is_supported_execution_provider(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().lower() in SUPPORTED_EXECUTOR_PROVIDERS


def get_executor_provider_info(provider: Any) -> ExecutorProviderInfo:
    if isinstance(provider, str):
        norm = provider.strip().lower()
        info = SUPPORTED_EXECUTOR_PROVIDERS.get(norm)
        if info is not None:
            return info
    return SUPPORTED_EXECUTOR_PROVIDERS[DEFAULT_EXECUTION_PROVIDER]


def get_executor_provider_display(provider: Any) -> str:
    return get_executor_provider_info(provider).display_name
