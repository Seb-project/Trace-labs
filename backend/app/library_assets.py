from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .library_acquisition import DownloadedLibraryAssets, OnlineLibraryAcquisitionService


BME280_LIBRARY_NAME = "PCBStream_BME280"
BME280_SYMBOL_NAME = "BME280"
BME280_SYMBOL_ID = f"{BME280_LIBRARY_NAME}:{BME280_SYMBOL_NAME}"
BME280_FOOTPRINT_NAME = "PCBStream_BME280_LGA8_2.5x2.5mm_P0.65mm"
BME280_FOOTPRINT_ID = f"{BME280_LIBRARY_NAME}:{BME280_FOOTPRINT_NAME}"


@dataclass(frozen=True)
class InstalledLibraryPaths:
    library_root: Path
    symbol_library: Path
    footprint_library: Path
    footprint_file: Path
    sources_file: Path


class BME280LibraryAssets:
    def __init__(self, source_dir: Path | None = None):
        backend_root = Path(__file__).resolve().parents[1]
        self.source_dir = source_dir or backend_root / "library_sources" / "bme280"
        self.symbol_source = self.source_dir / "Sensor.kicad_sym"
        self.footprint_source = (
            self.source_dir / "Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering.kicad_mod"
        )
        self.sources_source = self.source_dir / "sources.json"

    def write_export_libraries(self, export_dir: Path) -> InstalledLibraryPaths:
        library_root = export_dir / "pcbstream_libs"
        paths = self._target_paths(library_root)
        self._write_libraries(paths)
        return paths

    def install_project_libraries(self, project_path: Path, exported_library_root: Path) -> InstalledLibraryPaths:
        project_library_root = project_path / "pcbstream_libs"
        project_library_root.mkdir(parents=True, exist_ok=True)
        if exported_library_root.exists():
            shutil.copytree(exported_library_root, project_library_root, dirs_exist_ok=True)
        else:
            self._write_libraries(self._target_paths(project_library_root))

        paths = self._target_paths(project_library_root)
        self.ensure_project_tables(project_path)
        return paths

    def ensure_project_tables(self, project_path: Path) -> None:
        self._ensure_table_entry(
            project_path / "sym-lib-table",
            "sym_lib_table",
            f'(lib (name "{BME280_LIBRARY_NAME}") (type "KiCad") '
            f'(uri "${{KIPRJMOD}}/pcbstream_libs/{BME280_LIBRARY_NAME}.kicad_sym") '
            f'(options "") (descr "PCBStream downloaded BME280 symbol"))',
        )
        self._ensure_table_entry(
            project_path / "fp-lib-table",
            "fp_lib_table",
            f'(lib (name "{BME280_LIBRARY_NAME}") (type "KiCad") '
            f'(uri "${{KIPRJMOD}}/pcbstream_libs/{BME280_LIBRARY_NAME}.pretty") '
            f'(options "") (descr "PCBStream downloaded BME280 footprint"))',
        )

    def schematic_cached_symbol(self) -> str:
        symbol = self.project_symbol()
        return symbol.replace(f'(symbol "{BME280_SYMBOL_NAME}"', f'(symbol "{BME280_SYMBOL_ID}"', 1)

    def project_symbol(self) -> str:
        symbol = self._extract_symbol(self.symbol_source.read_text(encoding="utf-8"), BME280_SYMBOL_NAME)
        return self._rewrite_symbol_footprint(symbol)

    def _write_libraries(self, paths: InstalledLibraryPaths) -> None:
        paths.library_root.mkdir(parents=True, exist_ok=True)
        paths.footprint_library.mkdir(parents=True, exist_ok=True)
        paths.symbol_library.write_text(
            "(kicad_symbol_lib\n"
            "\t(version 20240114)\n"
            "\t(generator \"PCBStream\")\n"
            "\t(generator_version \"0.1\")\n"
            f"{self.project_symbol()}\n"
            ")\n",
            encoding="utf-8",
        )
        paths.footprint_file.write_text(self._project_footprint(), encoding="utf-8")
        if self.sources_source.exists():
            shutil.copy2(self.sources_source, paths.sources_file)
        else:
            paths.sources_file.write_text(json.dumps({"source": "unknown"}, indent=2), encoding="utf-8")

    def _target_paths(self, library_root: Path) -> InstalledLibraryPaths:
        footprint_library = library_root / f"{BME280_LIBRARY_NAME}.pretty"
        return InstalledLibraryPaths(
            library_root=library_root,
            symbol_library=library_root / f"{BME280_LIBRARY_NAME}.kicad_sym",
            footprint_library=footprint_library,
            footprint_file=footprint_library / f"{BME280_FOOTPRINT_NAME}.kicad_mod",
            sources_file=library_root / "pcbstream_library_sources.json",
        )

    def _project_footprint(self) -> str:
        text = self.footprint_source.read_text(encoding="utf-8")
        text = re.sub(r'^\(footprint "[^"]+"', f'(footprint "{BME280_FOOTPRINT_NAME}"', text, count=1)
        text = re.sub(
            r'\(property "Value" "[^"]+"',
            f'(property "Value" "{BME280_FOOTPRINT_NAME}"',
            text,
            count=1,
        )
        return text

    def _rewrite_symbol_footprint(self, symbol: str) -> str:
        return re.sub(
            r'\(property "Footprint" "[^"]+"',
            f'(property "Footprint" "{BME280_FOOTPRINT_ID}"',
            symbol,
            count=1,
        )

    def _extract_symbol(self, library_text: str, symbol_name: str) -> str:
        marker = f'(symbol "{symbol_name}"'
        start = library_text.find(marker)
        if start < 0:
            raise ValueError(f"Could not find symbol {symbol_name} in {self.symbol_source}")

        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(library_text)):
            char = library_text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return library_text[start : index + 1]
        raise ValueError(f"Symbol {symbol_name} was not balanced in {self.symbol_source}")

    def _ensure_table_entry(self, table_path: Path, table_name: str, entry: str) -> None:
        if table_path.exists():
            text = table_path.read_text(encoding="utf-8")
        else:
            text = f"({table_name}\n\t(version 7)\n)\n"

        text = self._normalise_library_table(text, table_name)

        if f'(name "{BME280_LIBRARY_NAME}")' in text:
            table_path.write_text(text, encoding="utf-8")
            return

        stripped = text.rstrip()
        if stripped.endswith(")"):
            text = f"{stripped[:-1]}  {entry}\n)\n"
        else:
            text = f"({table_name}\n  {entry}\n)\n"
        table_path.write_text(text, encoding="utf-8")

    def _normalise_library_table(self, text: str, table_name: str) -> str:
        stripped = text.strip()
        if not stripped:
            return f"({table_name}\n\t(version 7)\n)\n"
        if f"({table_name}" not in stripped:
            return f"({table_name}\n\t(version 7)\n)\n"
        if "(version " in stripped:
            return text
        insert_at = text.find("\n", text.find(f"({table_name}"))
        if insert_at == -1:
            return f"({table_name}\n\t(version 7)\n)\n"
        return text[: insert_at + 1] + "\t(version 7)\n" + text[insert_at + 1 :]


class DraftLibraryAssets:
    def __init__(self, acquisition_service: OnlineLibraryAcquisitionService | None = None):
        self.acquisition_service = acquisition_service or OnlineLibraryAcquisitionService()
        self._cached_symbols: dict[str, str] = {}

    def write_export_libraries(
        self,
        export_dir: Path,
        block: Any,
        *,
        require_downloaded_footprint: bool = False,
    ) -> InstalledLibraryPaths:
        library_root = export_dir / "pcbstream_libs"
        library_name, symbol_name = self._symbol_parts(block.main_component.symbol, block.main_component.value)
        footprint_name = self._footprint_name(block.main_component.footprint, library_name)
        footprint_id = f"{library_name}:{footprint_name}"
        downloaded = self.acquisition_service.acquire_for_block(
            block,
            library_name=library_name,
            symbol_name=symbol_name,
            footprint_name=footprint_name,
            footprint_id=footprint_id,
        )
        if downloaded and downloaded.footprint_name:
            footprint_name = self._safe_name(downloaded.footprint_name)
            footprint_id = f"{library_name}:{footprint_name}"
            block.main_component.footprint = footprint_id
        if require_downloaded_footprint and not (downloaded and downloaded.footprint_text):
            warnings = "; ".join(downloaded.warnings) if downloaded and downloaded.warnings else "no matching CAD footprint found"
            raise ValueError(f"AI-proposed export blocked: could not download a reviewed footprint candidate ({warnings}).")
        self._apply_supplier_source_metadata(block, downloaded)
        paths = self._target_paths(library_root, library_name, footprint_name)
        symbol_text = self._symbol_text(symbol_name, block, footprint_id, downloaded)
        footprint_text = self._footprint_text(footprint_name, block, downloaded)

        paths.library_root.mkdir(parents=True, exist_ok=True)
        paths.footprint_library.mkdir(parents=True, exist_ok=True)
        paths.symbol_library.write_text(
            "(kicad_symbol_lib\n"
            "\t(version 20240114)\n"
            "\t(generator \"PCBStream\")\n"
            "\t(generator_version \"0.1\")\n"
            f"{symbol_text}\n"
            ")\n",
            encoding="utf-8",
        )
        paths.footprint_file.write_text(footprint_text, encoding="utf-8")
        paths.sources_file.write_text(json.dumps(self._sources_metadata(block, downloaded), indent=2), encoding="utf-8")
        self._cached_symbols[block.main_component.symbol] = symbol_text.replace(
            f'(symbol "{symbol_name}"',
            f'(symbol "{block.main_component.symbol}"',
            1,
        )
        return paths

    def schematic_cached_symbol(self, block: Any) -> str:
        cached = self._cached_symbols.get(block.main_component.symbol)
        if cached:
            return cached
        _, symbol_name = self._symbol_parts(block.main_component.symbol, block.main_component.value)
        return self._project_symbol(symbol_name, block.main_component.value, block.main_component.footprint).replace(
            f'(symbol "{symbol_name}"',
            f'(symbol "{block.main_component.symbol}"',
            1,
        )

    def _symbol_text(
        self,
        symbol_name: str,
        block: Any,
        footprint_id: str,
        downloaded: DownloadedLibraryAssets | None,
    ) -> str:
        if downloaded and downloaded.symbol_text:
            symbol_text = re.sub(
                r'\(property "Footprint" "[^"]*"',
                f'(property "Footprint" "{footprint_id}"',
                downloaded.symbol_text,
                count=1,
            )
            block.main_component.symbol_confidence = "downloaded_needs_review"
            if downloaded.footprint_text:
                block.main_component.footprint_confidence = "downloaded_needs_review"
            block.main_component.assignment_reason = (
                "PCBStream downloaded candidate KiCad library assets from an online KiCad library source; "
                "review symbol pins and footprint land pattern before fabrication."
            )
            return symbol_text
        if getattr(block, "reference_extraction", None) and block.reference_extraction.pins:
            block.main_component.symbol_confidence = "datasheet_extracted_needs_review"
            block.main_component.assignment_reason = (
                "PCBStream generated a project-local symbol from extracted datasheet pin definitions; review before fabrication."
            )
            return self._project_symbol_from_extraction(symbol_name, block, footprint_id)
        return self._project_symbol(symbol_name, block.main_component.value, footprint_id)

    def _footprint_text(
        self,
        footprint_name: str,
        block: Any,
        downloaded: DownloadedLibraryAssets | None,
    ) -> str:
        if downloaded and downloaded.footprint_text:
            block.main_component.footprint_confidence = "downloaded_needs_review"
            block.main_component.assignment_reason = (
                "PCBStream downloaded a candidate KiCad footprint from an online KiCad library source; "
                "review package, pads, and pin-1 orientation before fabrication."
            )
            text = re.sub(
                r'^\(module\s+(?:"[^"]+"|[^\s)]+)',
                f'(footprint "{footprint_name}"',
                downloaded.footprint_text,
                count=1,
            )
            return re.sub(r'^\(footprint\s+"[^"]+"', f'(footprint "{footprint_name}"', text, count=1)
        return self._placeholder_footprint(footprint_name, block.main_component.value)

    def _sources_metadata(self, block: Any, downloaded: DownloadedLibraryAssets | None) -> dict[str, Any]:
        sources = [source.__dict__ for source in downloaded.sources] if downloaded else []
        warnings = list(downloaded.warnings) if downloaded else []
        if sources:
            library_type = "online_download_needs_review"
            warning = (
                "PCBStream downloaded one or more candidate KiCad library assets from online KiCad libraries. "
                "They are not manufacturer-certified by PCBStream and must be reviewed before fabrication."
            )
        else:
            library_type = "ai_proposed_placeholder"
            warning = (
                "PCBStream generated this placeholder library deterministically for review. "
                "It is not a verified manufacturer footprint."
            )
        return {
            "library_type": library_type,
            "part_number": block.main_component.mpn or block.main_component.value,
            "manufacturer": block.main_component.manufacturer,
            "supplier": getattr(block.main_component, "supplier", None),
            "supplier_part_number": getattr(block.main_component, "supplier_part_number", None),
            "supplier_url": getattr(block.main_component, "supplier_url", None),
            "symbol_confidence": block.main_component.symbol_confidence,
            "footprint_confidence": block.main_component.footprint_confidence,
            "warning": warning,
            "lookup_sources": sources,
            "lookup_warnings": warnings,
            "datasheet_sources": [source.model_dump() for source in block.datasheet_sources],
        }

    def _apply_supplier_source_metadata(self, block: Any, downloaded: DownloadedLibraryAssets | None) -> None:
        if not downloaded:
            return
        supplier_source = next((source for source in downloaded.sources if source.kind.startswith("supplier_")), None)
        if not supplier_source:
            return
        block.main_component.supplier = block.main_component.supplier or "LCSC"
        block.main_component.supplier_part_number = block.main_component.supplier_part_number or supplier_source.path
        block.main_component.supplier_url = block.main_component.supplier_url or supplier_source.url

    def _symbol_parts(self, symbol_id: str, value: str) -> tuple[str, str]:
        if ":" in symbol_id:
            library_name, symbol_name = symbol_id.split(":", 1)
        else:
            symbol_name = self._safe_name(value)
            library_name = f"PCBStream_{symbol_name}"
        return self._safe_name(library_name), self._safe_name(symbol_name)

    def _footprint_name(self, footprint_id: str, library_name: str) -> str:
        if ":" in footprint_id:
            return self._safe_name(footprint_id.split(":", 1)[1])
        return f"{library_name}_PLACEHOLDER"

    def _target_paths(self, library_root: Path, library_name: str, footprint_name: str) -> InstalledLibraryPaths:
        footprint_library = library_root / f"{library_name}.pretty"
        return InstalledLibraryPaths(
            library_root=library_root,
            symbol_library=library_root / f"{library_name}.kicad_sym",
            footprint_library=footprint_library,
            footprint_file=footprint_library / f"{footprint_name}.kicad_mod",
            sources_file=library_root / "pcbstream_library_sources.json",
        )

    def _project_symbol(self, symbol_name: str, value: str, footprint_id: str) -> str:
        return f"""    (symbol "{symbol_name}" (pin_numbers hide) (pin_names (offset 0.762)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at -5.08 -13.97 0) (effects (font (size 1.27 1.27))))
      (property "Value" "{value}" (at -5.08 13.97 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "{footprint_id}" (at 0 16.51 0) (effects (font (size 1.27 1.27)) hide))
      (property "Datasheet" "" (at 0 19.05 0) (effects (font (size 1.27 1.27)) hide))
      (property "Description" "PCBStream AI-proposed draft symbol; review before fabrication" (at 0 21.59 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "{symbol_name}_0_1"
        (rectangle (start -10.16 -10.16) (end 10.16 10.16) (stroke (width 0.254) (type default)) (fill (type background)))
        (text "REVIEW" (at 0 0 0) (effects (font (size 1.27 1.27))))
      )
      (symbol "{symbol_name}_1_1"
        (pin power_in line (at -12.7 -7.62 0) (length 2.54) (name "VCC") (number "1"))
        (pin power_in line (at -12.7 7.62 0) (length 2.54) (name "GND") (number "2"))
        (pin bidirectional line (at 12.7 0 180) (length 2.54) (name "SIGNALS") (number "3"))
      )
    )"""

    def _project_symbol_from_extraction(self, symbol_name: str, block: Any, footprint_id: str) -> str:
        pins = list(block.reference_extraction.pins)
        left_pins = [pin for pin in pins if self._pin_side(pin) == "left"]
        right_pins = [pin for pin in pins if self._pin_side(pin) == "right"]
        height = max(10.16, (max(len(left_pins), len(right_pins), 1) + 1) * 2.54)
        top = height / 2
        bottom = -height / 2
        pin_lines = []
        for index, pin in enumerate(left_pins):
            y = top - 2.54 * (index + 1)
            pin_lines.append(self._symbol_pin(pin.electrical_type, pin.name, pin.number, -12.7, y, 0))
        for index, pin in enumerate(right_pins):
            y = top - 2.54 * (index + 1)
            pin_lines.append(self._symbol_pin(pin.electrical_type, pin.name, pin.number, 12.7, y, 180))
        return f"""    (symbol "{symbol_name}" (pin_names (offset 0.762)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at -5.08 {self._fmt(bottom - 3.81)} 0) (effects (font (size 1.27 1.27))))
      (property "Value" "{self._escape(block.main_component.value)}" (at -5.08 {self._fmt(top + 3.81)} 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "{self._escape(footprint_id)}" (at 0 {self._fmt(top + 6.35)} 0) (effects (font (size 1.27 1.27)) hide))
      (property "Description" "PCBStream symbol generated from cited datasheet extraction; review before fabrication" (at 0 {self._fmt(top + 8.89)} 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "{symbol_name}_0_1"
        (rectangle (start -10.16 {self._fmt(top)}) (end 10.16 {self._fmt(bottom)}) (stroke (width 0.254) (type default)) (fill (type background)))
      )
      (symbol "{symbol_name}_1_1"
{chr(10).join(pin_lines)}
      )
    )"""

    def _pin_side(self, pin: Any) -> str:
        role = (pin.electrical_type or "").lower()
        name = (pin.name or "").upper()
        if any(token in name for token in ["GND", "VSS", "VDD", "VCC", "AVDD", "DVDD", "AVSS", "DVSS"]):
            return "left"
        if role in {"output", "bidirectional", "tri_state", "open_collector", "open_emitter"}:
            return "right"
        if self._is_signal_pin_name(name):
            return "right"
        return "left"

    def _is_signal_pin_name(self, name: str) -> bool:
        exact = {"SDA", "SCL", "MISO", "MOSI", "SCK", "SCLK", "CS", "CSB", "CSN", "NCS", "SS", "XSHUT", "RESET"}
        if name in exact:
            return True
        return name.startswith(("GPIO", "INT", "IRQ", "DRDY"))

    def _symbol_pin(self, electrical_type: str, name: str, number: str, x: float, y: float, rotation: int) -> str:
        safe_type = electrical_type if electrical_type in {
            "input",
            "output",
            "bidirectional",
            "tri_state",
            "passive",
            "free",
            "unspecified",
            "power_in",
            "power_out",
            "open_collector",
            "open_emitter",
            "no_connect",
        } else "passive"
        return (
            f'        (pin {safe_type} line (at {self._fmt(x)} {self._fmt(y)} {rotation}) '
            f'(length 2.54) (name "{self._escape(name)}") (number "{self._escape(number)}"))'
        )

    def _escape(self, value: str) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    def _fmt(self, value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")

    def _placeholder_footprint(self, footprint_name: str, value: str) -> str:
        return f"""(footprint "{footprint_name}"
  (version 20240108)
  (generator "PCBStream")
  (descr "PCBStream AI-proposed placeholder footprint for {value}; replace with verified footprint before fabrication")
  (tags "PCBStream placeholder needs_review")
  (layer "F.Cu")
  (property "Reference" "U?" (at 0 -4.2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (property "Value" "{value}" (at 0 4.2 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
  (property "Footprint" "{footprint_name}" (at 0 0 0) (layer "F.Fab") hide (effects (font (size 1 1) (thickness 0.15))))
  (fp_text user "PLACEHOLDER - REVIEW FOOTPRINT" (at 0 0 0) (layer "F.SilkS") (effects (font (size 0.7 0.7) (thickness 0.12))))
  (fp_rect (start -3 -3) (end 3 3) (stroke (width 0.12) (type default)) (fill none) (layer "F.SilkS"))
  (fp_rect (start -3.25 -3.25) (end 3.25 3.25) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))
  (fp_rect (start -3 -3) (end 3 3) (stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))
  (pad "1" smd roundrect (at -1.5 -2.2) (size 0.8 1.2) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.2))
  (pad "2" smd roundrect (at 0 -2.2) (size 0.8 1.2) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.2))
  (pad "3" smd roundrect (at 1.5 -2.2) (size 0.8 1.2) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.2))
  (pad "4" smd roundrect (at -1.5 2.2) (size 0.8 1.2) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.2))
  (pad "5" smd roundrect (at 0 2.2) (size 0.8 1.2) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.2))
  (pad "6" smd roundrect (at 1.5 2.2) (size 0.8 1.2) (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.2))
)"""

    def _safe_name(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_")
        return safe or "PCBStream_Draft"
