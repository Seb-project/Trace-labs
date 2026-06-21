from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .core import detect_project_context


DEFAULT_BACKEND_URL = "http://127.0.0.1:8765"


class BridgeClient:
    def __init__(self, backend_url: str | None = None):
        self.backend_url = (backend_url or os.environ.get("TRACELABS_BACKEND_URL") or DEFAULT_BACKEND_URL).rstrip("/")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/bridge/status")

    def link_project(self, project_path: str | Path, kicad_version: str | None = None) -> dict[str, Any]:
        context = detect_project_context(project_path, kicad_version)
        return self._request("POST", "/bridge/link", context.to_backend_payload())

    def import_block(
        self,
        generated_block_dir: str | Path,
        link_id: str | None = None,
        import_mode: str = "hierarchical_sheet",
        open_after_import: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"generated_block_dir": str(Path(generated_block_dir).expanduser().resolve())}
        payload["import_mode"] = import_mode
        if open_after_import:
            payload["open_after_import"] = True
        if link_id:
            payload["link_id"] = link_id
        return self._request("POST", "/bridge/import", payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.backend_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Trace Labs backend returned HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Trace Labs backend is not reachable at {self.backend_url}: {exc.reason}") from exc
