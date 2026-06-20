from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from .library_assets import BME280LibraryAssets, DraftLibraryAssets
from .models import CircuitBlock, PricingPreview


class KiCadWriter:
    def __init__(self, output_root: Path):
        self.output_root = output_root
        self.library_assets = BME280LibraryAssets()
        self.draft_library_assets = DraftLibraryAssets()

    def export(self, block: CircuitBlock, pricing: PricingPreview) -> tuple[Path, dict[str, str]]:
        if block.status not in {"final", "exported"}:
            raise ValueError("Only a final block can be exported.")
        self._normalise_block_for_export(block)
        self._validate_exportable_block(block)

        target = self.output_root / block.block_slug
        target.mkdir(parents=True, exist_ok=True)
        block.status = "exported"

        if block.block_slug == "bme280_i2c":
            library_paths = self.library_assets.write_export_libraries(target)
        else:
            library_paths = self.draft_library_assets.write_export_libraries(
                target,
                block,
                require_downloaded_footprint=block.recipe_source == "ai_proposed",
            )

        files = {
            "block_json": target / "block.json",
            "notes_md": target / "notes.md",
            "kicad_sch": target / f"{block.block_slug}.kicad_sch",
            "pricing_usage_json": target / "pricing_usage.json",
            "symbol_library": library_paths.symbol_library,
            "footprint_library": library_paths.footprint_file,
            "library_sources": library_paths.sources_file,
        }
        files["block_json"].write_text(block.model_dump_json(indent=2), encoding="utf-8")
        files["notes_md"].write_text(self._notes(block, pricing), encoding="utf-8")
        files["kicad_sch"].write_text(self._schematic(block), encoding="utf-8")
        files["pricing_usage_json"].write_text(pricing.model_dump_json(indent=2), encoding="utf-8")
        return target, {path.name: str(path) for path in files.values()}

    def _normalise_block_for_export(self, block: CircuitBlock) -> None:
        if block.block_slug == "bme280_i2c":
            return
        if block.recipe_source == "ai_proposed" and block.extraction_status == "ready":
            return
        safe_part = self._safe_library_name(block.main_component.value or block.main_component.mpn or "DraftPart")
        library_name = f"PCBStream_{safe_part}"
        expected_symbol = f"{library_name}:{safe_part}"
        expected_footprint = f"{library_name}:{library_name}_PLACEHOLDER"
        if not block.main_component.symbol or block.main_component.symbol.startswith("PCBStream_Draft:"):
            block.main_component.symbol = expected_symbol
        if not block.main_component.footprint or block.main_component.footprint.startswith("PCBStream_Draft:"):
            block.main_component.footprint = expected_footprint
        block.main_component.symbol_confidence = "needs_review"
        block.main_component.footprint_confidence = "needs_review"
        block.main_component.assignment_reason = (
            "Project-local draft symbol and placeholder footprint generated deterministically; "
            "replace with verified assets before fabrication."
        )

    def _validate_exportable_block(self, block: CircuitBlock) -> None:
        if block.block_slug == "bme280_i2c" or block.recipe_source != "ai_proposed":
            return
        extraction = block.reference_extraction
        if block.extraction_status != "ready" or extraction is None:
            raise ValueError(
                "AI-proposed blocks cannot be exported until datasheet/reference-design extraction is complete."
            )
        if not extraction.pins:
            raise ValueError("AI-proposed block export blocked: no extracted pin map is available.")
        if not extraction.support_requirements:
            raise ValueError("AI-proposed block export blocked: no extracted support components are available.")
        if any(not pin.source_citations for pin in extraction.pins):
            raise ValueError("AI-proposed block export blocked: every pin must include a source citation.")
        if any(not item.source_citations for item in extraction.support_requirements):
            raise ValueError("AI-proposed block export blocked: every support component must include a source citation.")

    def _safe_library_name(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_")
        return safe or "DraftPart"

    def _notes(self, block: CircuitBlock, pricing: PricingPreview) -> str:
        lines = [
            f"# PCBStream Export: {block.block_name}",
            "",
            block.summary,
            "",
            "## Generated Components",
            f"- {block.main_component.reference} {block.main_component.value}",
            f"  - Symbol: {block.main_component.symbol} ({block.main_component.symbol_confidence})",
            f"  - Footprint: {block.main_component.footprint} ({block.main_component.footprint_confidence})",
        ]
        if block.main_component.supplier_part_number:
            lines.append(
                f"  - Supplier CAD source: {block.main_component.supplier or 'supplier'} "
                f"{block.main_component.supplier_part_number}"
            )
        for component in block.support_components:
            lines.append(
                f"- {component.reference} {component.value} {component.purpose}: "
                f"{component.symbol}, {component.footprint}"
            )
        lines.extend(["", "## Selected Options"])
        for key, value in block.selected_options.items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Assumptions"])
        lines.extend(f"- {item}" for item in block.assumptions)
        lines.extend(["", "## Validation Warnings"])
        lines.extend(f"- [{warning.severity}] {warning.message}" for warning in block.validation_warnings)
        lines.extend(["", "## Next Steps"])
        lines.extend(f"- {step.task}" for step in block.next_steps)
        lines.extend(["", "## Documentation Sources"])
        lines.extend(f"- {source.title}: {source.confidence}" for source in block.datasheet_sources)
        if block.reference_extraction:
            lines.extend(["", "## Extracted Pins"])
            lines.extend(
                f"- Pin {pin.number} {pin.name}: {pin.net_name} ({', '.join(pin.source_citations)})"
                for pin in block.reference_extraction.pins
            )
            lines.extend(["", "## Extracted Support Components"])
            lines.extend(
                f"- {item.type} {item.value} {item.purpose}: {', '.join(item.connects)} "
                f"({', '.join(item.source_citations)})"
                for item in block.reference_extraction.support_requirements
            )
            lines.extend(["", "## Source Chunks"])
            lines.extend(
                f"- {chunk.chunk_id}: {chunk.title or chunk.source_url}"
                f"{' page ' + str(chunk.page) if chunk.page else ''}"
                for chunk in block.reference_extraction.source_chunks
            )
        lines.extend(
            [
                "",
                "## Usage and Pricing",
                f"- Plan: {pricing.plan_name}",
                f"- Used blocks: {pricing.used_blocks}",
                f"- Remaining blocks: {pricing.remaining_blocks}",
                f"- Estimated monthly bill: GBP {pricing.estimated_monthly_bill:.2f}",
                "",
                "## KiCad Review",
                "- This file is generated deterministically from CircuitBlock JSON.",
                f"- Recipe source: {block.recipe_source}.",
                f"- Recipe status: {block.recipe_status}.",
                "- Review symbol and footprint assignments before fabrication.",
                "- Run ERC after inserting the block.",
            ]
        )
        if block.recipe_saved_path:
            lines.append(f"- Saved draft recipe: {block.recipe_saved_path}")
        if any(component.value == "TBD" for component in block.support_components):
            lines.append("- One or more support components have value TBD because the user selected Not sure.")
        return "\n".join(lines) + "\n"

    def _schematic(self, block: CircuitBlock) -> str:
        if block.block_slug != "bme280_i2c" and block.reference_extraction is not None:
            return self._extracted_reference_schematic(block)
        if block.block_slug != "bme280_i2c":
            return self._generic_review_schematic(block)

        support = block.support_components
        symbol_entries = [
                self._placed_symbol(block.main_component.symbol, "U1", "BME280", 101.6, 76.2, block.main_component.footprint),
                self._placed_symbol("Device:C", "C1", "100 nF", 45.72, 68.58, support[0].footprint),
                self._placed_symbol("Device:C", "C2", "100 nF", 60.96, 68.58, support[1].footprint),
        ]
        resistors = [component for component in support if component.symbol == "Device:R"]
        sda_pullup = next((component for component in resistors if "SDA pull-up" in component.purpose), None)
        scl_pullup = next((component for component in resistors if "SCL pull-up" in component.purpose), None)
        address = block.selected_options.get("i2c_address", "0x76")
        sdo_target = "GND" if address == "0x76" else "+3V3"

        next_resistor = 1
        if sda_pullup:
            symbol_entries.append(
                self._placed_symbol("Device:R", f"R{next_resistor}", sda_pullup.value, 149.86, 74.93, sda_pullup.footprint)
            )
            next_resistor += 1
        if scl_pullup:
            symbol_entries.append(
                self._placed_symbol("Device:R", f"R{next_resistor}", scl_pullup.value, 162.56, 69.85, scl_pullup.footprint)
            )
            next_resistor += 1
        wires = "\n".join(
            [
                self._wire(40.64, 50.8, 172.72, 50.8),
                self._wire(40.64, 101.6, 172.72, 101.6),
                self._wire(99.06, 50.8, 99.06, 60.96),
                self._wire(104.14, 50.8, 104.14, 60.96),
                self._wire(99.06, 91.44, 99.06, 101.6),
                self._wire(104.14, 91.44, 104.14, 101.6),
                self._wire(45.72, 50.8, 45.72, 64.77),
                self._wire(45.72, 72.39, 45.72, 101.6),
                self._wire(60.96, 50.8, 60.96, 64.77),
                self._wire(60.96, 72.39, 60.96, 101.6),
                self._wire(116.84, 73.66, 167.64, 73.66),
                self._wire(116.84, 78.74, 154.94, 78.74),
                self._wire(116.84, 68.58, 152.4, 68.58),
                self._wire(116.84, 83.82, 152.4, 83.82),
                *(self._pullup_wires(sda_pullup, scl_pullup)),
            ]
        )
        labels = "\n".join(
            [
                self._hierarchical_label("+3V3", "input", 91.44, 50.8),
                self._hierarchical_label("GND", "input", 91.44, 101.6),
                self._hierarchical_label("I2C1_SCL", "input", 121.92, 73.66),
                self._hierarchical_label("I2C1_SDA", "bidirectional", 121.92, 78.74),
                self._label(sdo_target, 152.4, 68.58),
                self._label("+3V3", 152.4, 83.82),
                self._text(f"SDO={address}", 124.46, 66.04),
                self._text("CSB=I2C", 124.46, 81.28),
            ]
        )
        junctions = "\n".join(
            [
                self._junction(45.72, 50.8),
                self._junction(60.96, 50.8),
                self._junction(99.06, 50.8),
                self._junction(104.14, 50.8),
                self._junction(45.72, 101.6),
                self._junction(60.96, 101.6),
                self._junction(99.06, 101.6),
                self._junction(104.14, 101.6),
                *(self._pullup_junctions(sda_pullup, scl_pullup)),
            ]
        )
        return f"""(kicad_sch (version 20230121) (generator "PCBStream")
  (uuid "{uuid4()}")
  (paper "A4")
  (title_block
    (title "{block.block_name}")
    (company "PCBStream")
    (comment 1 "Generated from local verified BME280 recipe")
    (comment 2 "Review footprints and run ERC before fabrication")
  )
  (lib_symbols
{self._library_symbols(block)}
  )
{wires}
{junctions}
{labels}
{chr(10).join(symbol_entries)}
)"""

    def _library_symbols(self, block: CircuitBlock) -> str:
        return "\n".join(
            [
                self.library_assets.schematic_cached_symbol(),
                self._capacitor_library_symbol(),
                self._resistor_library_symbol(),
            ]
        )

    def _generic_review_schematic(self, block: CircuitBlock) -> str:
        capacitors = [component for component in block.support_components if component.symbol == "Device:C"]
        resistors = [component for component in block.support_components if component.symbol == "Device:R"]
        ref_base = self._reference_base(block.block_slug)
        symbol_entries = [
            self._placed_symbol(
                block.main_component.symbol,
                f"U{ref_base}",
                block.main_component.value,
                101.6,
                76.2,
                block.main_component.footprint,
            ),
        ]
        for index, capacitor in enumerate(capacitors[:6], start=1):
            x = 50.8 + (index - 1) * 12.7
            symbol_entries.append(
                self._placed_symbol("Device:C", f"C{ref_base + index}", capacitor.value, x, 76.2, capacitor.footprint)
            )
        for index, resistor in enumerate(resistors[:8], start=1):
            x, y = self._generic_resistor_position(index)
            symbol_entries.append(
                self._placed_symbol("Device:R", f"R{ref_base + index}", resistor.value, x, y, resistor.footprint)
            )

        power_net = next((net for net in block.external_nets if net.startswith("+")), "VCC_UNSPECIFIED")
        interface_net = next((net for net in block.external_nets if "SIGNALS" in net or "I2C" in net or "SPI" in net), "SIGNALS")
        wires = [
            self._wire(40.64, 50.8, 172.72, 50.8),
            self._wire(40.64, 101.6, 172.72, 101.6),
            self._wire(88.9, 50.8, 88.9, 68.58),
            self._wire(88.9, 83.82, 88.9, 101.6),
            self._wire(114.3, 76.2, 162.56, 76.2),
        ]
        junctions = [
            self._junction(88.9, 50.8),
            self._junction(88.9, 101.6),
        ]
        for index, capacitor in enumerate(capacitors[:6], start=1):
            x = 50.8 + (index - 1) * 12.7
            wires.extend(
                [
                    self._wire(x, 50.8, x, 72.39),
                    self._wire(x, 80.01, x, 101.6),
                ]
            )
            junctions.extend([self._junction(x, 50.8), self._junction(x, 101.6)])
        signal_labels = []
        for index, resistor in enumerate(resistors[:8], start=1):
            x, y = self._generic_resistor_position(index)
            top_y = y - 3.81
            bottom_y = y + 3.81
            label_x = x + 25.4
            label = self._passive_signal_label(resistor, index)
            wires.extend(
                [
                    self._wire(x, 50.8, x, top_y),
                    self._wire(x, bottom_y, label_x, bottom_y),
                ]
            )
            junctions.append(self._junction(x, 50.8))
            signal_labels.append(self._label(label, label_x, bottom_y))
        wires_text = "\n".join(wires)
        junctions_text = "\n".join(junctions)
        labels = "\n".join(
            [
                self._hierarchical_label(power_net, "input", 43.18, 50.8),
                self._hierarchical_label("GND", "input", 43.18, 101.6),
                self._hierarchical_label(interface_net, "bidirectional", 162.56, 76.2),
                *signal_labels,
                self._text("Review pin map and package before layout", 101.6, 114.3),
            ]
        )
        return f"""(kicad_sch (version 20230121) (generator "PCBStream")
  (uuid "{uuid4()}")
  (paper "A4")
  (title_block
    (title "{block.block_name}")
    (company "PCBStream")
    (comment 1 "Generated from AI-proposed draft recipe")
    (comment 2 "Review all values, pin maps, symbols and footprints")
  )
  (lib_symbols
{self._generic_library_symbols(block)}
  )
{wires_text}
{junctions_text}
{labels}
{chr(10).join(symbol_entries)}
)"""

    def _extracted_reference_schematic(self, block: CircuitBlock) -> str:
        extraction = block.reference_extraction
        assert extraction is not None
        ref_base = self._reference_base(block.block_slug)
        main_x = 101.6
        main_y = 76.2
        pin_layout = self._extracted_pin_layout(extraction.pins, main_x, main_y)
        external_nets = set(block.external_nets)
        symbol_entries = [
            self._placed_symbol(
                block.main_component.symbol,
                f"U{ref_base}",
                block.main_component.value,
                main_x,
                main_y,
                block.main_component.footprint,
            )
        ]
        support_positions = []
        support_start_y = max(116.84, main_y + pin_layout["half_height"] + 22.86)
        for index, component in enumerate(block.support_components[:16], start=1):
            prefix = "C" if component.symbol == "Device:C" else "R"
            x = 45.72 + ((index - 1) % 3) * 53.34
            y = support_start_y + ((index - 1) // 3) * 22.86
            support_positions.append((component, f"{prefix}{ref_base + index}", x, y))
            symbol_entries.append(
                self._placed_symbol(
                    component.symbol,
                    f"{prefix}{ref_base + index}",
                    component.value,
                    x,
                    y,
                    component.footprint,
                )
            )

        wires = []
        labels = []
        junctions = []

        for pin, side, x, y in pin_layout["pins"]:
            if side == "left":
                label_x = x - 10.16
                wires.append(self._wire(x, y, label_x, y))
                labels.append(self._label(pin.net_name, label_x, y))
            else:
                label_x = x + 10.16
                wires.append(self._wire(x, y, label_x, y))
                labels.append(self._label(pin.net_name, label_x, y))

        for index, net in enumerate(block.external_nets[:12]):
            y = 35.56 + index * 5.08
            wires.append(self._wire(170.18, y, 180.34, y))
            labels.append(self._hierarchical_label(net, self._label_shape(net), 180.34, y))

        for component, _ref, x, y in support_positions:
            top_net = component.connects[0] if component.connects else f"REVIEW_{_ref}_1"
            bottom_net = component.connects[1] if len(component.connects) > 1 else f"REVIEW_{_ref}_2"
            labels.extend(self._support_terminal_labels(x, y, top_net, bottom_net))
            wires.extend(self._support_terminal_wires(x, y))
            if len(component.connects) > 2:
                labels.append(self._text(f"{_ref} extra nets: {', '.join(component.connects[2:])}", x + 7.62, y + 10.16))

        for net, points in self._net_points(pin_layout["pins"], support_positions).items():
            if len(points) > 1 and net not in external_nets:
                first = points[0]
                junctions.append(self._junction(first[0], first[1]))
        return f"""(kicad_sch (version 20230121) (generator "PCBStream")
  (uuid "{uuid4()}")
  (paper "A4")
  (title_block
    (title "{block.block_name}")
    (company "PCBStream")
    (comment 1 "Generated from cited datasheet/reference extraction")
    (comment 2 "Review extracted pins, passives, symbol and footprint")
  )
  (lib_symbols
{self._generic_library_symbols(block)}
  )
{chr(10).join(wires)}
{chr(10).join(junctions)}
{chr(10).join(labels)}
{chr(10).join(symbol_entries)}
)"""

    def _extracted_pin_layout(self, pins, main_x: float, main_y: float) -> dict:
        left_pins = [pin for pin in pins if self._extracted_pin_side(pin) == "left"]
        right_pins = [pin for pin in pins if self._extracted_pin_side(pin) == "right"]
        half_height = max(10.16, (max(len(left_pins), len(right_pins), 1) + 1) * 2.54) / 2
        rows = []
        for side, side_pins, x_offset in (("left", left_pins, -12.7), ("right", right_pins, 12.7)):
            for index, pin in enumerate(side_pins):
                local_y = half_height - 2.54 * (index + 1)
                y = main_y - local_y
                rows.append((pin, side, main_x + x_offset, y))
        return {"pins": rows, "half_height": half_height}

    def _extracted_pin_side(self, pin) -> str:
        role = (pin.electrical_type or "").lower()
        name = (pin.name or "").upper()
        net = (pin.net_name or "").upper()
        if net == "GND" or net.startswith("+") or any(
            token in name for token in ["GND", "VSS", "VDD", "VCC", "AVDD", "DVDD", "AVSS", "DVSS"]
        ):
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

    def _support_terminal_wires(self, x: float, y: float) -> list[str]:
        top_pin_y = y - 3.81
        bottom_pin_y = y + 3.81
        top_label_y = y - 8.89
        bottom_label_y = y + 8.89
        label_x = x + 7.62
        return [
            self._wire(x, top_pin_y, x, top_label_y),
            self._wire(x, top_label_y, label_x, top_label_y),
            self._wire(x, bottom_pin_y, x, bottom_label_y),
            self._wire(x, bottom_label_y, label_x, bottom_label_y),
        ]

    def _support_terminal_labels(self, x: float, y: float, top_net: str, bottom_net: str) -> list[str]:
        label_x = x + 7.62
        return [
            self._label(top_net, label_x, y - 8.89),
            self._label(bottom_net, label_x, y + 8.89),
        ]

    def _net_points(self, pin_rows, support_positions) -> dict[str, list[tuple[float, float]]]:
        points: dict[str, list[tuple[float, float]]] = {}
        for pin, _side, x, y in pin_rows:
            points.setdefault(pin.net_name, []).append((x, y))
        for component, _ref, x, y in support_positions:
            if component.connects:
                points.setdefault(component.connects[0], []).append((x, y - 3.81))
            if len(component.connects) > 1:
                points.setdefault(component.connects[1], []).append((x, y + 3.81))
        return points

    def _label_shape(self, net: str) -> str:
        upper = net.upper()
        if net == "GND" or net.startswith("+") or upper.startswith("V"):
            return "input"
        if "INT" in upper:
            return "output"
        return "bidirectional"

    def _passive_signal_label(self, component, index: int) -> str:
        for net in component.connects:
            upper = net.upper()
            if net in {"GND"} or net.startswith("+") or upper.startswith("VCC"):
                continue
            return net
        return f"REVIEW_CONFIG_{index}"

    def _generic_resistor_position(self, index: int) -> tuple[float, float]:
        zero_index = index - 1
        column = zero_index // 3
        row = zero_index % 3
        return 129.54 + column * 35.56, 60.96 + row * 15.24

    def _reference_base(self, block_slug: str) -> int:
        total = sum((index + 1) * ord(char) for index, char in enumerate(block_slug))
        return 100 + (total % 800)

    def _generic_library_symbols(self, block: CircuitBlock) -> str:
        return "\n".join(
            [
                self.draft_library_assets.schematic_cached_symbol(block),
                self._capacitor_library_symbol(),
                self._resistor_library_symbol(),
            ]
        )

    def _generic_ic_library_symbol(self, block: CircuitBlock) -> str:
        lib_id = block.main_component.symbol
        value = block.main_component.value
        return f"""    (symbol "{lib_id}" (pin_numbers hide) (pin_names (offset 0.762)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at -5.08 -11.43 0) (effects (font (size 1.27 1.27))))
      (property "Value" "{value}" (at -5.08 11.43 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at 0 13.97 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "{value}_0_1"
        (rectangle (start -10.16 -10.16) (end 10.16 10.16) (stroke (width 0.254) (type default)) (fill (type background)))
      )
      (symbol "{value}_1_1"
        (pin power_in line (at -12.7 -5.08 0) (length 2.54) (name "VCC") (number "1"))
        (pin power_in line (at -12.7 5.08 0) (length 2.54) (name "GND") (number "2"))
        (pin bidirectional line (at 12.7 0 180) (length 2.54) (name "SIGNALS") (number "3"))
      )
    )"""

    def _capacitor_library_symbol(self) -> str:
        return """    (symbol "Device:C" (pin_numbers hide) (pin_names (offset 0.254)) (in_bom yes) (on_board yes)
      (property "Reference" "C" (at 0.635 2.54 0) (effects (font (size 1.27 1.27)) (justify left)))
      (property "Value" "C" (at 0.635 -2.54 0) (effects (font (size 1.27 1.27)) (justify left)))
      (property "Footprint" "" (at 0.9652 -3.81 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "C_0_1"
        (polyline (pts (xy -2.032 0.762) (xy 2.032 0.762)) (stroke (width 0.508) (type default)) (fill (type none)))
        (polyline (pts (xy -2.032 -0.762) (xy 2.032 -0.762)) (stroke (width 0.508) (type default)) (fill (type none)))
      )
      (symbol "C_1_1"
        (pin passive line (at 0 3.81 270) (length 2.794) (name "") (number "1"))
        (pin passive line (at 0 -3.81 90) (length 2.794) (name "") (number "2"))
      )
    )"""

    def _resistor_library_symbol(self) -> str:
        return """    (symbol "Device:R" (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
      (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at -1.778 0 90) (effects (font (size 1.27 1.27)) hide))
      (symbol "R_0_1"
        (rectangle (start -1.016 -2.54) (end 1.016 2.54) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27) (name "") (number "1"))
        (pin passive line (at 0 -3.81 90) (length 1.27) (name "") (number "2"))
      )
    )"""

    def _placed_symbol(
        self,
        lib_id: str,
        ref: str,
        value: str,
        x: float,
        y: float,
        footprint: str,
        rotation: int = 0,
    ) -> str:
        ref_x, ref_y, ref_rotation, value_x, value_y, value_rotation, footprint_x, footprint_y = (
            self._property_positions(lib_id, x, y, rotation)
        )
        x_text = self._format_mm(x)
        y_text = self._format_mm(y)
        ref_x_text = self._format_mm(ref_x)
        ref_y_text = self._format_mm(ref_y)
        value_x_text = self._format_mm(value_x)
        value_y_text = self._format_mm(value_y)
        footprint_x_text = self._format_mm(footprint_x)
        footprint_y_text = self._format_mm(footprint_y)
        return f"""  (symbol (lib_id "{lib_id}") (at {x_text} {y_text} {rotation}) (unit 1) (in_bom yes) (on_board yes)
    (uuid "{uuid4()}")
    (property "Reference" "{ref}" (at {ref_x_text} {ref_y_text} {ref_rotation}) (effects (font (size 1.27 1.27))))
    (property "Value" "{value}" (at {value_x_text} {value_y_text} {value_rotation}) (effects (font (size 1.27 1.27))))
    (property "Footprint" "{footprint}" (at {footprint_x_text} {footprint_y_text} 0) (effects (font (size 1.27 1.27)) hide))
  )"""

    def _property_positions(
        self,
        lib_id: str,
        x: float,
        y: float,
        rotation: int,
    ) -> tuple[float, float, int, float, float, int, float, float]:
        if "BME280" in lib_id:
            return (x - 6.35, y - 17.78, 0, x - 8.89, y + 17.78, 0, x, y + 20.32)

        if lib_id == "Device:C":
            return (x + 6.35, y - 3.81, 0, x + 6.35, y + 3.81, 0, x, y + 8.89)

        if lib_id == "Device:R" and rotation == 90:
            return (x - 3.81, y - 5.08, 0, x - 3.81, y + 5.08, 0, x, y + 7.62)

        if lib_id == "Device:R":
            return (x + 7.62, y - 3.81, 0, x + 7.62, y, 0, x, y + 7.62)

        return (x, y - 8.0, 0, x, y + 8.0, 0, x, y + 10.0)

    def _format_mm(self, value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")


    def _wire(self, x1: float, y1: float, x2: float, y2: float) -> str:
        return (
            f'  (wire (pts (xy {self._format_mm(x1)} {self._format_mm(y1)}) '
            f'(xy {self._format_mm(x2)} {self._format_mm(y2)})) '
            f'(stroke (width 0) (type default)) (uuid "{uuid4()}"))'
        )

    def _pullup_wires(self, sda_pullup, scl_pullup) -> list[str]:
        wires = []
        if sda_pullup:
            wires.extend(
                [
                    self._wire(149.86, 50.8, 149.86, 71.12),
                ]
            )
        if scl_pullup:
            wires.extend(
                [
                    self._wire(162.56, 50.8, 162.56, 66.04),
                ]
            )
        return wires

    def _pullup_junctions(self, sda_pullup, scl_pullup) -> list[str]:
        junctions = []
        if sda_pullup:
            junctions.extend([self._junction(149.86, 50.8), self._junction(149.86, 78.74)])
        if scl_pullup:
            junctions.extend([self._junction(162.56, 50.8), self._junction(162.56, 73.66)])
        return junctions

    def _label(self, text: str, x: float, y: float) -> str:
        return (
            f'  (label "{self._escape_text(text)}" (at {self._format_mm(x)} {self._format_mm(y)} 0) '
            f'(effects (font (size 1.27 1.27))) (uuid "{uuid4()}"))'
        )

    def _text(self, text: str, x: float, y: float) -> str:
        return (
            f'  (text "{self._escape_text(text)}" (at {self._format_mm(x)} {self._format_mm(y)} 0) '
            f'(effects (font (size 1.27 1.27))) (uuid "{uuid4()}"))'
        )

    def _hierarchical_label(self, text: str, shape: str, x: float, y: float) -> str:
        return (
            f'  (hierarchical_label "{self._escape_text(text)}" (shape {shape}) '
            f'(at {self._format_mm(x)} {self._format_mm(y)} 0) '
            f'(effects (font (size 1.27 1.27))) (uuid "{uuid4()}"))'
        )

    def _junction(self, x: float, y: float) -> str:
        return (
            f'  (junction (at {self._format_mm(x)} {self._format_mm(y)}) '
            f'(diameter 0) (color 0 0 0 0) (uuid "{uuid4()}"))'
        )

    def _escape_text(self, value: str) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')
