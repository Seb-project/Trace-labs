from __future__ import annotations

import os
from pathlib import Path


def load_local_env(root: Path) -> None:
    paths: list[Path] = []
    explicit_env_file = os.environ.get("TRACELABS_ENV_FILE", "").strip()
    if explicit_env_file:
        paths.append(Path(explicit_env_file).expanduser())
    paths.extend([root / ".env", root / "backend" / ".env"])

    for path in paths:
        if path.exists():
            _load_env_file(path)


def path_from_env(name: str, fallback: Path) -> Path:
    value = os.environ.get(name, "").strip()
    if value:
        return Path(value).expanduser().resolve()
    return fallback.expanduser().resolve()


def _load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
