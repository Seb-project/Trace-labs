from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_NETS = ["+3V3", "GND", "I2C1_SDA", "I2C1_SCL"]
PROJECT_EXTENSIONS = {".kicad_pro", ".kicad_pcb", ".kicad_sch"}


@dataclass(frozen=True)
class KicadProjectContext:
    project_path: str
    project_name: str
    schematic_path: str
    bridge_mode: str = "kicad_plugin"
    available_nets: list[str] | None = None
    detected_mcu: str = "STM32L072"
    kicad_version: str | None = None

    def to_backend_payload(self) -> dict:
        payload = asdict(self)
        payload["available_nets"] = self.available_nets or DEFAULT_NETS
        return payload


def detect_project_context(project_path: str | Path, kicad_version: str | None = None) -> KicadProjectContext:
    path = resolve_project_root(project_path, strict=False)
    project_name = _find_project_name(path)
    schematic_path = _find_root_schematic(path, project_name)
    return KicadProjectContext(
        project_path=str(path),
        project_name=project_name,
        schematic_path=str(schematic_path),
        available_nets=DEFAULT_NETS,
        kicad_version=kicad_version,
    )


def resolve_project_root(path: str | Path, strict: bool = True) -> Path:
    candidate = Path(path).expanduser().resolve()
    if candidate.is_file() or candidate.suffix in PROJECT_EXTENSIONS:
        candidate = candidate.parent

    for folder in [candidate, *candidate.parents]:
        if list(folder.glob("*.kicad_pro")):
            return folder

    if strict:
        raise ValueError(
            f"Could not find a .kicad_pro file from {candidate}. "
            "Open a saved KiCad project, or link the project folder manually in PCBStream."
        )
    return candidate


def _find_project_name(project_path: Path) -> str:
    candidates = sorted(project_path.glob("*.kicad_pro"))
    return candidates[0].name if candidates else "weather_station.kicad_pro"


def _find_root_schematic(project_path: Path, project_name: str) -> Path:
    stem = project_name.removesuffix(".kicad_pro")
    preferred = project_path / f"{stem}.kicad_sch"
    if preferred.exists():
        return preferred
    candidates = sorted(project_path.glob("*.kicad_sch"))
    return candidates[0] if candidates else preferred
