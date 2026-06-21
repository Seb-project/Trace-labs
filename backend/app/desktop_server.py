from __future__ import annotations

import os

import uvicorn

from backend.app.main import app


def main() -> None:
    host = os.environ.get("TRACELABS_BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("TRACELABS_BACKEND_PORT", "8765"))
    log_level = os.environ.get("TRACELABS_BACKEND_LOG_LEVEL", "info")
    try:
        uvicorn.run(app, host=host, port=port, log_level=log_level, access_log=False)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
