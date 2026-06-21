from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .library_assets import BME280LibraryAssets
from .models import BridgeImportResponse, BridgeLinkRecord, BridgeLinkRequest, ImportMode
from .storage import JsonStore


REQUIRED_EXPORT_FILES = ["block.json", "notes.md", "pricing_usage.json"]
VALID_IMPORT_MODES = {"hierarchical_sheet", "inline_main"}


class BridgeService:
    def __init__(self, data_dir: Path):
        self.store = JsonStore(data_dir / "bridge_link.json")
        self.library_assets = BME280LibraryAssets()

    def link(self, request: BridgeLinkRequest) -> BridgeLinkRecord:
        project_path = Path(request.project_path).expanduser().resolve()
        project_name = request.project_name or self._find_project_name(project_path)
        schematic_path = request.schematic_path or str(self._find_root_schematic(project_path, project_name))
        record = BridgeLinkRecord(
            project_path=str(project_path),
            project_name=project_name,
            schematic_path=str(Path(schematic_path).expanduser().resolve()),
            bridge_mode=request.bridge_mode,
            available_nets=request.available_nets,
            detected_mcu=request.detected_mcu,
            kicad_version=request.kicad_version,
        )
        self.store.write_dict(record.model_dump())
        return record

    def status(self) -> dict:
        data = self.store.read_dict()
        if not data:
            return {
                "connected": False,
                "kicad_bridge_status": "mocked",
                "next_steps": ["Link a KiCad project folder before inserting a block."],
            }
        return {**data, "connected": True, "kicad_bridge_status": "mocked"}

    def import_block(
        self,
        generated_block_dir: str,
        link_id: str | None = None,
        import_mode: ImportMode = "hierarchical_sheet",
        open_after_import: bool = False,
    ) -> BridgeImportResponse:
        if import_mode not in VALID_IMPORT_MODES:
            raise ValueError(f"Unsupported import mode: {import_mode}")

        link = self._latest_link(link_id)
        source = Path(generated_block_dir).expanduser().resolve()
        if not source.exists():
            raise ValueError(f"Generated block folder does not exist: {source}")
        missing = [name for name in REQUIRED_EXPORT_FILES if not (source / name).exists()]
        if missing:
            raise ValueError(f"Generated block folder is missing required files: {', '.join(missing)}")
        schematic_files = sorted(source.glob("*.kicad_sch"))
        if not schematic_files:
            raise ValueError("Generated block folder is missing a .kicad_sch file.")
        schematic_file = schematic_files[0]
        block_data = json.loads((source / "block.json").read_text(encoding="utf-8"))
        block_slug = str(block_data.get("block_slug") or source.name)
        block_name = str(block_data.get("block_name") or block_slug)
        main_symbol = str(block_data.get("main_component", {}).get("symbol") or "")
        external_nets = [str(net) for net in block_data.get("external_nets", []) if str(net).strip()]

        project_path = Path(link.project_path)
        root_schematic = Path(link.schematic_path)
        project_path.mkdir(parents=True, exist_ok=True)
        if not root_schematic.exists():
            root_schematic.parent.mkdir(parents=True, exist_ok=True)
            root_schematic.write_text(self._minimal_root_schematic(link.project_name), encoding="utf-8")

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        target_dir = project_path / "tracelabs_blocks" / block_slug
        target_dir.mkdir(parents=True, exist_ok=True)

        copied = []
        for name in [*REQUIRED_EXPORT_FILES, schematic_file.name]:
            target = target_dir / name
            shutil.copy2(source / name, target)
            copied.append(str(target))

        exported_libraries = source / "tracelabs_libs"
        if exported_libraries.exists():
            copied.extend(self._install_exported_libraries(project_path, exported_libraries, block_slug))

        backups = []
        root_backup = root_schematic.with_suffix(root_schematic.suffix + f".tracelabs_backup_{timestamp}")
        shutil.copy2(root_schematic, root_backup)
        backups.append(str(root_backup))

        root_text = root_schematic.read_text(encoding="utf-8")
        opened_sheet_path: str | None = None
        open_error: str | None = None
        path_to_open = root_schematic
        if import_mode == "hierarchical_sheet":
            rel_child = target_dir.relative_to(project_path) / schematic_file.name
            if str(rel_child) not in root_text:
                root_schematic.write_text(
                    self._insert_sheet(
                        root_text,
                        str(rel_child),
                        self._sheet_name(block_slug, block_name),
                        external_nets,
                    ),
                    encoding="utf-8",
                )
            message = f"Generated {block_name} block inserted as a KiCad hierarchical sheet."
            next_steps = [
                "Open or reload the root schematic so KiCad rereads the Trace Labs library tables.",
                "Open the Trace Labs hierarchical sheet from the root schematic.",
                "Review symbol and footprint assignments; the footprint library is registered in fp-lib-table.",
                "Run ERC before fabrication.",
            ]
        else:
            child_text = (target_dir / schematic_file.name).read_text(encoding="utf-8")
            duplicate_marker = f'(symbol (lib_id "{main_symbol}")' if main_symbol else f'(title "{block_name}")'
            if duplicate_marker not in root_text:
                root_schematic.write_text(self._insert_inline_block(root_text, child_text), encoding="utf-8")
            message = f"Generated {block_name} block inserted directly into the root schematic."
            next_steps = [
                "Reload the root schematic in KiCad if it was already open so library tables are re-read.",
                "Review the inserted Trace Labs components in the main sheet.",
                "Review symbol and footprint assignments.",
                "Run ERC before fabrication.",
            ]

        manifest_path = target_dir / "bridge_import_manifest.json"
        manifest = {
            "import_id": str(uuid4()),
            "project_name": link.project_name,
            "project_path": str(project_path),
            "root_schematic": str(root_schematic),
            "generated_block_dir": str(source),
            "copied_files": copied,
            "backups": backups,
            "mode": import_mode,
            "created_at": datetime.now().isoformat(),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        copied.append(str(manifest_path))

        if open_after_import:
            opened_sheet_path = str(path_to_open)
            try:
                self._open_sheet(path_to_open)
            except OSError as exc:
                open_error = str(exc)

        return BridgeImportResponse(
            success=True,
            mode=import_mode,
            import_status="ready_for_review",
            project_path=str(project_path),
            root_schematic=str(root_schematic),
            opened_sheet_path=opened_sheet_path,
            open_error=open_error,
            imported_directory=str(target_dir),
            copied_files=copied,
            modified_files=[str(root_schematic)],
            backups=backups,
            message=message,
            next_steps=next_steps,
        )

    def _open_sheet(self, sheet_path: Path) -> None:
        if not sheet_path.exists():
            raise OSError(f"Inserted schematic does not exist: {sheet_path}")

        system = platform.system()
        if system == "Darwin":
            subprocess.Popen(["open", str(sheet_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if system == "Windows":
            os.startfile(str(sheet_path))  # type: ignore[attr-defined]
            return
        subprocess.Popen(["xdg-open", str(sheet_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _latest_link(self, link_id: str | None) -> BridgeLinkRecord:
        data = self.store.read_dict()
        if not data:
            raise ValueError("No KiCad project is linked. Link a project before importing.")
        record = BridgeLinkRecord(**data)
        if link_id and record.link_id != link_id:
            raise ValueError("Bridge link id does not match the currently linked project.")
        return record

    def _find_project_name(self, project_path: Path) -> str:
        candidates = sorted(project_path.glob("*.kicad_pro"))
        return candidates[0].name if candidates else "weather_station.kicad_pro"

    def _find_root_schematic(self, project_path: Path, project_name: str) -> Path:
        stem = project_name.removesuffix(".kicad_pro")
        preferred = project_path / f"{stem}.kicad_sch"
        if preferred.exists():
            return preferred
        candidates = sorted(project_path.glob("*.kicad_sch"))
        return candidates[0] if candidates else preferred

    def _minimal_root_schematic(self, project_name: str) -> str:
        return f"""(kicad_sch (version 20230121) (generator "Trace Labs")
  (uuid "{uuid4()}")
  (paper "A4")
  (title_block (title "{project_name}"))
)"""

    def _install_exported_libraries(
        self,
        project_path: Path,
        exported_library_root: Path,
        block_slug: str,
    ) -> list[str]:
        project_library_root = project_path / "tracelabs_libs"
        project_library_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(exported_library_root, project_library_root, dirs_exist_ok=True)

        copied: list[str] = []
        for path in sorted(project_library_root.rglob("*")):
            if path.is_file():
                copied.append(str(path))

        symbol_table = project_path / "sym-lib-table"
        footprint_table = project_path / "fp-lib-table"
        for symbol_library in sorted(project_library_root.glob("*.kicad_sym")):
            library_name = symbol_library.stem
            self._ensure_table_entry(
                symbol_table,
                "sym_lib_table",
                library_name,
                f'(lib (name "{library_name}") (type "KiCad") '
                f'(uri "${{KIPRJMOD}}/tracelabs_libs/{symbol_library.name}") '
                f'(options "") (descr "Trace Labs {block_slug} symbol library"))',
            )
        for footprint_library in sorted(project_library_root.glob("*.pretty")):
            library_name = footprint_library.stem
            self._ensure_table_entry(
                footprint_table,
                "fp_lib_table",
                library_name,
                f'(lib (name "{library_name}") (type "KiCad") '
                f'(uri "${{KIPRJMOD}}/tracelabs_libs/{footprint_library.name}") '
                f'(options "") (descr "Trace Labs {block_slug} footprint library"))',
            )

        copied.extend([str(symbol_table), str(footprint_table)])
        return copied

    def _ensure_table_entry(self, table_path: Path, table_name: str, library_name: str, entry: str) -> None:
        if table_path.exists():
            text = table_path.read_text(encoding="utf-8")
        else:
            text = f"({table_name}\n\t(version 7)\n)\n"

        text = self._normalise_library_table(text, table_name)

        existing_span = self._library_entry_span(text, library_name)
        if existing_span is not None:
            start, end = existing_span
            text = f"{text[:start].rstrip()}\n  {entry}\n{text[end:].lstrip()}"
            table_path.write_text(text, encoding="utf-8")
            return

        stripped = text.rstrip()
        if stripped.endswith(")"):
            text = f"{stripped[:-1].rstrip()}\n  {entry}\n)\n"
        else:
            text = f"({table_name}\n  {entry}\n)\n"
        table_path.write_text(text, encoding="utf-8")

    def _library_entry_span(self, text: str, library_name: str) -> tuple[int, int] | None:
        pattern = re.compile(rf'\(name\s+(?:"{re.escape(library_name)}"|{re.escape(library_name)})\)')
        index = 0
        while True:
            start = text.find("(lib", index)
            if start == -1:
                return None
            try:
                _, end = self._balanced_span(text, start)
            except ValueError:
                return None
            if pattern.search(text[start:end]):
                return start, end
            index = end

    def _normalise_library_table(self, text: str, table_name: str) -> str:
        stripped = text.strip()
        if not stripped:
            return f"({table_name}\n\t(version 7)\n)\n"
        if f"({table_name}" not in stripped:
            return f"({table_name}\n\t(version 7)\n)\n"
        if "(version " in stripped:
            return text
        marker = f"({table_name}"
        start = text.find(marker)
        insert_at = text.find("\n", start)
        if insert_at == -1:
            return f"({table_name}\n\t(version 7)\n)\n"
        return text[: insert_at + 1] + "\t(version 7)\n" + text[insert_at + 1 :]

    def _sheet_name(self, block_slug: str, block_name: str) -> str:
        raw = re.sub(r"[^A-Za-z0-9_]+", "_", block_slug or block_name).strip("_")
        return f"TraceLabs_{raw or 'block'}"

    def _insert_sheet(
        self,
        root_text: str,
        child_file: str,
        sheet_name: str = "TraceLabs_BME280",
        external_nets: list[str] | None = None,
    ) -> str:
        pins = self._sheet_pins(external_nets or ["+3V3", "GND", "I2C1_SDA", "I2C1_SCL"])
        sheet = f"""
  (sheet (at 40 40) (size 70 45) (fields_autoplaced)
    (stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0))
    (uuid "{uuid4()}")
    (property "Sheet name" "{sheet_name}" (at 40 38 0) (effects (font (size 1.27 1.27))))
    (property "Sheet file" "{child_file}" (at 40 87 0) (effects (font (size 1.27 1.27))))
{pins}
  )
"""
        stripped = root_text.rstrip()
        if stripped.endswith(")"):
            return stripped[:-1] + sheet + ")\n"
        return root_text + sheet

    def _sheet_pins(self, external_nets: list[str]) -> str:
        lines = []
        for index, net in enumerate(external_nets[:8]):
            y = 48 + index * 6
            shape = "bidirectional" if any(term in net.upper() for term in ["SDA", "SIGNAL", "GPIO", "IO"]) else "input"
            lines.append(f'    (pin "{net}" {shape} (at 40 {y} 180) (uuid "{uuid4()}"))')
        return "\n".join(lines)

    def _insert_inline_block(self, root_text: str, child_text: str) -> str:
        body = self._child_schematic_body(child_text)
        body, power_nets = self._rewrite_inline_labels(body)
        merged_root = self._merge_lib_symbols(root_text, child_text)
        if power_nets:
            merged_root = self._merge_symbol_blocks(
                merged_root,
                [self._power_library_symbol(net) for net in sorted(power_nets)],
            )
        body = self._offset_inline_body(body, 20.32, 20.32)
        return self._append_before_final_paren(merged_root, body)

    def _merge_lib_symbols(self, root_text: str, child_text: str) -> str:
        child_span = self._find_block_span(child_text, "(lib_symbols")
        if child_span is None:
            return root_text

        child_block = child_text[child_span[0] : child_span[1]]
        child_symbols = self._top_level_blocks(child_block[len("(lib_symbols") : -1])
        root_span = self._find_block_span(root_text, "(lib_symbols")

        if root_span is None:
            lib_symbols = "\n  (lib_symbols\n" + "\n".join(child_symbols) + "\n  )\n"
            insert_at = self._header_insert_index(root_text)
            return root_text[:insert_at].rstrip() + lib_symbols + root_text[insert_at:].lstrip("\n")

        start, end = root_span
        root_block = root_text[start:end]
        missing_symbols = []
        for symbol in child_symbols:
            symbol_id = self._top_symbol_id(symbol)
            if symbol_id and f'(symbol "{symbol_id}"' not in root_block:
                missing_symbols.append(symbol)

        if not missing_symbols:
            return root_text

        return root_text[: end - 1].rstrip() + "\n" + "\n".join(missing_symbols) + "\n  " + root_text[end - 1 :]

    def _merge_symbol_blocks(self, root_text: str, symbols: list[str]) -> str:
        root_span = self._find_block_span(root_text, "(lib_symbols")
        if root_span is None:
            lib_symbols = "\n  (lib_symbols\n" + "\n".join(symbols) + "\n  )\n"
            insert_at = self._header_insert_index(root_text)
            return root_text[:insert_at].rstrip() + lib_symbols + root_text[insert_at:].lstrip("\n")

        start, end = root_span
        root_block = root_text[start:end]
        missing_symbols = []
        for symbol in symbols:
            symbol_id = self._top_symbol_id(symbol)
            if symbol_id and f'(symbol "{symbol_id}"' not in root_block:
                missing_symbols.append(symbol)

        if not missing_symbols:
            return root_text
        return root_text[: end - 1].rstrip() + "\n" + "\n".join(missing_symbols) + "\n  " + root_text[end - 1 :]

    def _child_schematic_body(self, child_text: str) -> str:
        lib_span = self._find_block_span(child_text, "(lib_symbols")
        if lib_span is None:
            raise ValueError("Generated schematic is missing lib_symbols.")
        body = child_text[lib_span[1] :].strip()
        if body.endswith(")"):
            body = body[:-1].rstrip()
        if not body:
            raise ValueError("Generated schematic does not contain insertable schematic objects.")
        return body

    def _rewrite_inline_labels(self, body: str) -> tuple[str, set[str]]:
        blocks = self._top_level_blocks(body)
        rewritten = []
        power_nets: set[str] = set()

        for block in blocks:
            stripped = block.lstrip()
            if stripped.startswith("(hierarchical_label"):
                label = self._parse_label_block(stripped)
                if label and self._is_supported_power_net(label["net"]):
                    net = label["net"]
                    power_nets.add(net)
                    rewritten.append(self._power_symbol(net, label["x"], label["y"]))
                else:
                    rewritten.append(
                        self._force_label_horizontal(stripped.replace("(hierarchical_label", "(global_label", 1))
                    )
                continue

            if stripped.startswith("(label") or stripped.startswith("(global_label"):
                label = self._parse_label_block(stripped)
                if label and self._is_supported_power_net(label["net"]):
                    net = label["net"]
                    power_nets.add(net)
                    rewritten.append(self._power_symbol(net, label["x"], label["y"]))
                    continue
                rewritten.append(self._force_label_horizontal(stripped))
                continue

            rewritten.append(stripped)

        return "\n".join(rewritten), power_nets

    def _force_label_horizontal(self, block: str) -> str:
        return re.sub(
            r"\(at\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+-?\d+(?:\.\d+)?\)",
            r"(at \1 \2 0)",
            block,
            count=1,
        )

    def _parse_label_block(self, block: str) -> dict[str, float | str] | None:
        net_match = re.match(r'\((?:hierarchical_label|global_label|label)\s+"([^"]+)"', block)
        at_match = re.search(r"\(at\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\)", block)
        if not net_match or not at_match:
            return None
        return {
            "net": net_match.group(1),
            "x": float(at_match.group(1)),
            "y": float(at_match.group(2)),
        }

    def _is_supported_power_net(self, net: str) -> bool:
        return net == "GND" or net.startswith("+")

    def _power_symbol(self, net: str, x: float, y: float) -> str:
        reference = f"#PWR{uuid4().hex[:6].upper()}"
        if net == "GND":
            value_y = y + 5.08
            reference_y = y + 2.54
        else:
            value_y = y - 5.08
            reference_y = y + 3.81
        return f"""(symbol (lib_id "power:{net}") (at {self._format_mm(x)} {self._format_mm(y)} 0) (unit 1)
    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)
    (uuid "{uuid4()}")
    (property "Reference" "{reference}" (at {self._format_mm(x)} {self._format_mm(reference_y)} 0) (effects (font (size 1.27 1.27)) hide))
    (property "Value" "{net}" (at {self._format_mm(x)} {self._format_mm(value_y)} 0) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at {self._format_mm(x)} {self._format_mm(y)} 0) (effects (font (size 1.27 1.27)) hide))
    (property "Datasheet" "" (at {self._format_mm(x)} {self._format_mm(y)} 0) (effects (font (size 1.27 1.27)) hide))
    (pin "1" (uuid "{uuid4()}"))
  )"""

    def _power_library_symbol(self, net: str) -> str:
        if net == "GND":
            return """    (symbol "power:GND" (power) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
      (property "Reference" "#PWR" (at 0 -6.35 0) (effects (font (size 1.27 1.27)) hide))
      (property "Value" "GND" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (property "Description" "Power symbol creates a global label with name GND" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "GND_0_1"
        (polyline (pts (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27)) (stroke (width 0) (type default)) (fill (type none)))
      )
      (symbol "GND_1_1"
        (pin power_in line (at 0 0 270) (length 0) hide (name "GND") (number "1"))
      )
    )"""

        return f"""    (symbol "power:{net}" (power) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
      (property "Reference" "#PWR" (at 0 -3.81 0) (effects (font (size 1.27 1.27)) hide))
      (property "Value" "{net}" (at 0 3.556 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (property "Description" "Power symbol creates a global label with name {net}" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "{net}_0_1"
        (polyline (pts (xy -0.762 1.27) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))
        (polyline (pts (xy 0 2.54) (xy 0.762 1.27)) (stroke (width 0) (type default)) (fill (type none)))
        (polyline (pts (xy 0 0) (xy 0 2.54)) (stroke (width 0) (type default)) (fill (type none)))
      )
      (symbol "{net}_1_1"
        (pin power_in line (at 0 0 90) (length 0) hide (name "{net}") (number "1"))
      )
    )"""

    def _offset_inline_body(self, body: str, dx: float, dy: float) -> str:
        coord_pattern = re.compile(
            r"\((xy|at|start|end)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)(?=[\s\)])"
        )

        def replace(match: re.Match[str]) -> str:
            token = match.group(1)
            x = self._format_mm(float(match.group(2)) + dx)
            y = self._format_mm(float(match.group(3)) + dy)
            return f"({token} {x} {y}"

        return coord_pattern.sub(replace, body)

    def _append_before_final_paren(self, root_text: str, payload: str) -> str:
        stripped = root_text.rstrip()
        if stripped.endswith(")"):
            return stripped[:-1].rstrip() + "\n" + payload.strip() + "\n)\n"
        return stripped + "\n" + payload.strip() + "\n"

    def _find_block_span(self, text: str, token: str) -> tuple[int, int] | None:
        start = text.find(token)
        if start == -1:
            return None
        return self._balanced_span(text, start)

    def _balanced_span(self, text: str, start: int) -> tuple[int, int]:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
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
                    return start, index + 1

        raise ValueError("Schematic S-expression is not balanced.")

    def _top_level_blocks(self, text: str) -> list[str]:
        blocks = []
        index = 0
        while index < len(text):
            start = text.find("(", index)
            if start == -1:
                break
            block_start, block_end = self._balanced_span(text, start)
            blocks.append(text[block_start:block_end])
            index = block_end
        return blocks

    def _top_symbol_id(self, symbol_block: str) -> str | None:
        match = re.match(r'\s*\(symbol\s+"([^"]+)"', symbol_block)
        return match.group(1) if match else None

    def _header_insert_index(self, root_text: str) -> int:
        for token in ("(title_block", "(paper", "(uuid"):
            span = self._find_block_span(root_text, token)
            if span is not None:
                return span[1]
        first_line = root_text.find("\n")
        return first_line + 1 if first_line != -1 else len(root_text)

    def _format_mm(self, value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")
