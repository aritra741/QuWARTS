from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple


DEFAULT_API_KEY_PATH = Path(__file__).resolve().parent.parent / "conf" / "api_key.yaml"


def load_api_keys(provider: str, config_path: Optional[Path] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Load api_key and api_base for the given provider from ``api_key.yaml``.

    Returns a tuple of (api_key, api_base). Missing values are returned as None.
    """
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependency
        raise RuntimeError("PyYAML is required to load API keys.") from exc

    path = Path(config_path) if config_path else DEFAULT_API_KEY_PATH
    if not path.exists():
        return None, None

    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    providers = config.get("api_keys") or {}
    provider_config = providers.get(provider) or providers.get(provider.lower()) or providers.get(provider.upper())
    if not isinstance(provider_config, dict):
        return None, None

    api_key = provider_config.get("api_key")
    api_base = provider_config.get("api_base") or provider_config.get("api_base_url")
    return api_key, api_base
