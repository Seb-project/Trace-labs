from __future__ import annotations

import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

try:
    import pcbnew  # type: ignore
    import wx  # type: ignore
except ImportError:
    pcbnew = None
    wx = None

from pcbstream_bridge.client import BridgeClient
from pcbstream_bridge.core import resolve_project_root


def _message(title: str, body: str) -> None:
    if wx is not None:
        wx.MessageBox(body, title)
    else:
        print(f"{title}: {body}")


def _current_project_path() -> Path:
    candidates: list[str] = []
    if pcbnew is not None:
        board = pcbnew.GetBoard()
        if board is not None and board.GetFileName():
            candidates.append(board.GetFileName())

        for owner in [board, pcbnew]:
            for attr in ["GetProjectFileName", "GetProjectFullName", "GetFileName"]:
                value = _call_optional(owner, attr)
                if value:
                    candidates.append(str(value))

    for env_name in ["KIPRJMOD", "PCBNEW_PROJECT_PATH"]:
        value = os.environ.get(env_name)
        if value:
            candidates.append(value)

    candidates.append(str(Path.cwd()))

    for candidate in candidates:
        try:
            return resolve_project_root(candidate, strict=True)
        except ValueError:
            continue

    raise RuntimeError(
        "PCBStream could not detect a saved KiCad project folder. "
        "Open the project PCB editor from a saved .kicad_pro file, or link the folder manually in PCBStream."
    )


def _call_optional(owner: object, attr: str) -> object | None:
    if owner is None:
        return None
    method = getattr(owner, attr, None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception:
        return None


def run_bridge_action() -> None:
    backend_url = os.environ.get("PCBSTREAM_BACKEND_URL", "http://127.0.0.1:8765")
    generated_dir = os.environ.get("PCBSTREAM_GENERATED_BLOCK_DIR")
    import_mode = os.environ.get("PCBSTREAM_IMPORT_MODE", "hierarchical_sheet")
    client = BridgeClient(backend_url)
    project_path = _current_project_path()
    link = client.link_project(project_path)

    if generated_dir:
        imported = client.import_block(generated_dir, link.get("link_id"), import_mode)
        _message(
            "PCBStream Bridge",
            f"{imported['message']}\n\nRoot schematic:\n{imported['root_schematic']}",
        )
        return

    _message(
        "PCBStream Bridge",
        "Linked this KiCad project to PCBStream.\n\n"
        f"Project: {link['project_name']}\n"
        f"Folder: {link['project_path']}\n\n"
        "Export a block in PCBStream, then click Mock Insert into KiCad in the app.",
    )


if pcbnew is not None:

    class PCBStreamBridgePlugin(pcbnew.ActionPlugin):  # type: ignore[misc]
        def defaults(self) -> None:
            self.name = "PCBStream Bridge"
            self.category = "PCBStream"
            self.description = "Link the current KiCad project to PCBStream and import generated blocks."
            self.show_toolbar_button = True

        def Run(self) -> None:
            try:
                run_bridge_action()
            except Exception as exc:  # KiCad plugin boundary should show actionable failures.
                _message("PCBStream Bridge Error", str(exc))


    PCBStreamBridgePlugin().register()
