from pathlib import Path

import pytest

from bridge.pcbstream_bridge.client import BridgeClient
from bridge.pcbstream_bridge.core import detect_project_context, resolve_project_root


def test_detect_project_context_uses_existing_project_files(tmp_path: Path):
    (tmp_path / "weather_station.kicad_pro").write_text("{}", encoding="utf-8")
    (tmp_path / "weather_station.kicad_sch").write_text("(kicad_sch)", encoding="utf-8")

    context = detect_project_context(tmp_path, "8.0")

    assert context.project_name == "weather_station.kicad_pro"
    assert context.schematic_path.endswith("weather_station.kicad_sch")
    assert context.kicad_version == "8.0"
    assert context.to_backend_payload()["available_nets"] == ["+3V3", "GND", "I2C1_SDA", "I2C1_SCL"]


def test_detect_project_context_defaults_for_empty_folder(tmp_path: Path):
    context = detect_project_context(tmp_path)

    assert context.project_name == "weather_station.kicad_pro"
    assert context.schematic_path == str(tmp_path / "weather_station.kicad_sch")


def test_resolve_project_root_from_board_file(tmp_path: Path):
    project = tmp_path / "actual_project"
    project.mkdir()
    board = project / "actual_project.kicad_pcb"
    (project / "actual_project.kicad_pro").write_text("{}", encoding="utf-8")
    board.write_text("(kicad_pcb)", encoding="utf-8")

    assert resolve_project_root(board) == project


def test_resolve_project_root_rejects_non_project_folder(tmp_path: Path):
    with pytest.raises(ValueError):
        resolve_project_root(tmp_path)


def test_bridge_client_can_request_open_after_import(tmp_path: Path, monkeypatch):
    captured = {}
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    client = BridgeClient("http://127.0.0.1:8765")

    def fake_request(method, path, payload=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return {"success": True}

    monkeypatch.setattr(client, "_request", fake_request)

    client.import_block(generated_dir, "link-1", "hierarchical_sheet", open_after_import=True)

    assert captured["method"] == "POST"
    assert captured["path"] == "/bridge/import"
    assert captured["payload"]["generated_block_dir"] == str(generated_dir.resolve())
    assert captured["payload"]["link_id"] == "link-1"
    assert captured["payload"]["import_mode"] == "hierarchical_sheet"
    assert captured["payload"]["open_after_import"] is True
