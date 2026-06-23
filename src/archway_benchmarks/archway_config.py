"""Public Archway benchmark configuration.

The public harness should be able to call either a local development server,
a private/Tailscale server, or a future public Archway analysis endpoint without
knowing anything about internal secret stores. This module resolves only the
server URL and reports where it came from so run metadata can preserve
provenance.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_SERVER_URL = "http://localhost:8788"
ENV_SERVER_URL = "ARCHWAY_SERVER_URL"
DEFAULT_CONFIG_NAME = "archway.toml"


@dataclass(frozen=True)
class ArchwayServerConfig:
    server_url: str
    source: str
    config_path: str | None = None


def resolve_archway_server_config(
    *,
    cli_server_url: str | None = None,
    config_path: str | Path | None = None,
    start_dir: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ArchwayServerConfig:
    """Resolve the Archway analysis server URL.

    Precedence is explicit CLI value, environment override, ``archway.toml``,
    then the local development default. The environment wins over config so CI,
    private machines, and Tailscale wrappers can redirect a checked-out public
    benchmark without editing files.
    """

    if cli_server_url:
        return ArchwayServerConfig(
            server_url=_normalize_url(cli_server_url),
            source="cli",
        )

    env_map = env if env is not None else os.environ
    env_url = env_map.get(ENV_SERVER_URL)
    if env_url:
        return ArchwayServerConfig(
            server_url=_normalize_url(env_url),
            source=f"env:{ENV_SERVER_URL}",
        )

    path = _resolve_config_path(config_path=config_path, start_dir=start_dir)
    if path is not None:
        value = _read_server_url(path)
        if value:
            return ArchwayServerConfig(
                server_url=_normalize_url(value),
                source="config",
                config_path=str(path),
            )

    return ArchwayServerConfig(server_url=DEFAULT_SERVER_URL, source="default")


def _normalize_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise ValueError("Archway server URL cannot be empty")
    return value.rstrip("/")


def _resolve_config_path(
    *,
    config_path: str | Path | None,
    start_dir: str | Path | None,
) -> Path | None:
    if config_path:
        path = Path(config_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Archway config not found: {path}")
        return path

    cur = Path(start_dir or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for base in (cur, *cur.parents):
        candidate = base / DEFAULT_CONFIG_NAME
        if candidate.exists():
            return candidate
    return None


def _read_server_url(path: Path) -> str | None:
    data = tomllib.loads(path.read_text())
    archway = data.get("archway")
    if isinstance(archway, dict):
        value = archway.get("server_url") or archway.get("url")
        if isinstance(value, str):
            return value
    value = data.get("server_url")
    return value if isinstance(value, str) else None
