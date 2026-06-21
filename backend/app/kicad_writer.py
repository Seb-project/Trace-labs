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
            self.library_assets.attach_footprint_asset(block)
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
        library_name = f"TraceLabs_{safe_part}"
        expected_symbol = f"{library_name}:{safe_part}"
        expected_footprint = f"{library_name}:{library_name}_PLACEHOLDER"
        if not block.main_component.symbol or block.main_component.symbol.startswith("TraceLabs_Draft:"):
            block.main_component.symbol = expected_symbol
        if not block.main_component.footprint or block.main_component.footprint.startswith("TraceLabs_Draft:"):
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
            f"# Trace Labs Export: {block.block_name}",
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
                self._placed_symbol("Device:C", "C1", "100 nF", 86.36, 64.77, support[0].footprint),
                self._placed_symbol("Device:C", "C2", "100 nF", 116.84, 64.77, support[1].footprint),
        ]
        resistors = [component for component in support if component.symbol == "Device:R"]
        sda_pullup = next((component for component in resistors if "SDA pull-up" in component.purpose), None)
        scl_pullup = next((component for component in resistors if "SCL pull-up" in component.purpose), None)
        address = block.selected_options.get("i2c_address", "0x76")
        sdo_target = "GND" if address == "0x76" else "+3V3"

        next_resistor = 1
        if sda_pullup:
            symbol_entries.append(
                self._placed_symbol("Device:R", f"R{next_resistor}", sda_pullup.value, 132.08, 74.93, sda_pullup.footprint)
            )
            next_resistor += 1
        if scl_pullup:
            symbol_entries.append(
                self._placed_symbol("Device:R", f"R{next_resistor}", scl_pullup.value, 139.7, 69.85, scl_pullup.footprint)
            )
            next_resistor += 1
        wires = "\n".join(
            [
                self._wire(83.82, 50.8, 147.32, 50.8),
                self._wire(83.82, 91.44, 147.32, 91.44),
                self._wire(99.06, 50.8, 99.06, 60.96),
                self._wire(104.14, 50.8, 104.14, 60.96),
                self._wire(99.06, 60.96, 86.36, 60.96),
                self._wire(104.14, 60.96, 116.84, 60.96),
                self._wire(86.36, 68.58, 86.36, 91.44),
                self._wire(116.84, 68.58, 116.84, 91.44),
                self._wire(116.84, 73.66, 144.78, 73.66),
                self._wire(116.84, 78.74, 144.78, 78.74),
                self._wire(116.84, 68.58, 137.16, 68.58),
                self._wire(116.84, 83.82, 137.16, 83.82),
                *(self._pullup_wires(sda_pullup, scl_pullup)),
            ]
        )
        labels = "\n".join(
            [
                self._hierarchical_label("+3V3", "input", 91.44, 50.8),
                self._hierarchical_label("GND", "input", 91.44, 91.44),
                self._hierarchical_label("I2C1_SCL", "input", 121.92, 73.66),
                self._hierarchical_label("I2C1_SDA", "bidirectional", 121.92, 78.74),
                self._label(sdo_target, 137.16, 68.58),
                self._label("+3V3", 137.16, 83.82),
                self._text(f"SDO={address}", 124.46, 66.04),
                self._text("CSB=I2C", 124.46, 81.28),
            ]
        )
        junctions = "\n".join(
            [
                self._junction(99.06, 50.8),
                self._junction(104.14, 50.8),
                self._junction(86.36, 60.96),
                self._junction(116.84, 60.96),
                self._junction(86.36, 91.44),
                self._junction(99.06, 91.44),
                self._junction(104.14, 91.44),
                self._junction(116.84, 91.44),
                *(self._pullup_junctions(sda_pullup, scl_pullup)),
            ]
        )
        return f"""(kicad_sch (version 20230121) (generator "Trace Labs")
  (uuid "{uuid4()}")
  (paper "A4")
  (title_block
    (title "{block.block_name}")
    (company "Trace Labs")
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
                self._diode_library_symbol(),
                self._inductor_library_symbol(),
                self._resistor_library_symbol(),
            ]
        )

    def _generic_review_schematic(self, block: CircuitBlock) -> str:
        capacitors = [component for component in block.support_components if component.symbol == "Device:C"]
        resistors = [component for component in block.support_components if component.symbol == "Device:R"]
        diodes = [component for component in block.support_components if self._is_diode(component)]
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
        for index, diode in enumerate(diodes[:6], start=1):
            x, y = self._generic_resistor_position(len(resistors[:8]) + index)
            symbol_entries.append(
                self._placed_symbol("Device:D", f"D{ref_base + index}", diode.value, x, y, diode.footprint)
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
        for index, diode in enumerate(diodes[:6], start=1):
            x, y = self._generic_resistor_position(len(resistors[:8]) + index)
            top_net = diode.connects[0] if diode.connects else f"REVIEW_D{index}_1"
            bottom_net = diode.connects[1] if len(diode.connects) > 1 else f"REVIEW_D{index}_2"
            wires.extend(self._support_terminal_wires(x, y))
            signal_labels.extend(self._support_terminal_labels(x, y, top_net, bottom_net))
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
        return f"""(kicad_sch (version 20230121) (generator "Trace Labs")
  (uuid "{uuid4()}")
  (paper "A4")
  (title_block
    (title "{block.block_name}")
    (company "Trace Labs")
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
        main_x = 101.6
        main_y = 81.28
        pin_layout = self._extracted_pin_layout(extraction.pins, main_x, main_y)
        no_connect_pin_rows = [row for row in pin_layout["pins"] if self._is_no_connect_pin(row[0])]
        pin_rows = [row for row in pin_layout["pins"] if not self._is_no_connect_pin(row[0])]
        external_nets = set(block.external_nets)
        net_roles = {net.name: net.role for net in extraction.nets}
        is_ground_net = lambda net: net_roles.get(net) == "ground" or self._is_ground_net(net)
        is_power_net = lambda net: net_roles.get(net) in {"power", "ground"} or self._is_power_net(net)
        all_nets = self._unique_strings(
            [
                *block.external_nets,
                *(pin.net_name for pin, _side, _x, _y in pin_rows),
                *(net for component in block.support_components for net in component.connects),
            ]
        )
        power_nets = [net for net in all_nets if is_power_net(net) and not is_ground_net(net)][:4]
        power_rail_y = {net: 35.56 + index * 10.16 for index, net in enumerate(power_nets)}
        capacitor_supports = [
            component
            for component in block.support_components[:16]
            if component.symbol == "Device:C" or component.type == "capacitor"
        ]
        grounded_capacitors = sum(
            1
            for component in capacitor_supports
            if any(is_ground_net(net) for net in component.connects)
        )
        ground_clearance = 45.72 + max(0, grounded_capacitors - 1) * 5.08
        ground_rail_y = max(111.76, main_y + pin_layout["half_height"] + ground_clearance)
        def rail_y_for_net(net: str) -> float | None:
            if is_ground_net(net):
                return ground_rail_y
            return power_rail_y.get(net)

        rail_x1 = 22.86
        rail_x2 = 187.96
        symbol_entries = [
            self._placed_symbol(
                block.main_component.symbol,
                "U1",
                block.main_component.value,
                main_x,
                main_y,
                block.main_component.footprint,
            )
        ]
        wires = []
        labels = []
        junctions = []
        no_connects = []

        for net, y in power_rail_y.items():
            wires.append(self._wire(rail_x1, y, rail_x2, y))
            labels.append(self._label(net, rail_x1, y))
        wires.append(self._wire(rail_x1, ground_rail_y, rail_x2, ground_rail_y))
        labels.append(self._label("GND", rail_x1, ground_rail_y))

        pin_rows_by_net: dict[str, list[tuple[object, str, float, float]]] = {}
        signal_line_bounds: dict[str, tuple[float, float, float]] = {}
        for index, (pin, side, x, y) in enumerate(pin_rows):
            net = pin.net_name
            pin_rows_by_net.setdefault(net, []).append((pin, side, x, y))
            rail_y = rail_y_for_net(net)
            if rail_y is not None:
                trunk_x = x - 10.16 - (index % 2) * 2.54 if side == "left" else x + 10.16 + (index % 2) * 2.54
                wires.append(self._wire(x, y, trunk_x, y))
                wires.append(self._wire(trunk_x, y, trunk_x, rail_y))
                junctions.append(self._junction(trunk_x, rail_y))
                continue

            label_x = 35.56 if side == "left" else 167.64
            wire_start = min(x, label_x)
            wire_end = max(x, label_x)
            wires.append(self._wire(x, y, label_x, y))
            signal_line_bounds[net] = (wire_start, wire_end, y)
            labels.append(self._label(net, label_x, y))

        for _pin, _side, x, y in no_connect_pin_rows:
            no_connects.append(self._no_connect(x, y))

        capacitor_side_slots = {"left": 0, "right": 0}
        pullup_side_slots = {"left": 0, "right": 0}
        anchored_side_slots = {"left": 0, "right": 0}
        generic_index = 0
        for index, component in enumerate(block.support_components[:16], start=1):
            ref = self._support_ref(component, index)
            top_net = component.connects[0] if component.connects else f"REVIEW_{ref}_1"
            bottom_net = component.connects[1] if len(component.connects) > 1 else f"REVIEW_{ref}_2"
            if self._is_capacitor(component):
                active_net = next((net for net in component.connects if not is_ground_net(net)), None) or top_net
                active_rail_y = rail_y_for_net(active_net)
                active_pin = pin_rows_by_net.get(active_net, [None])[0]
                side = active_pin[1] if active_pin else "left"
                if active_pin and any(is_ground_net(net) for net in component.connects):
                    _pin, side, pin_x, pin_y = active_pin
                    slot = capacitor_side_slots[side]
                    capacitor_side_slots[side] += 1
                    x = self._support_x_for_pin(pin_x, side, slot)
                    lane = slot // 2
                    y = self._snap_mm(pin_y + 3.81 + lane * 5.08)
                    top_terminal_y = self._snap_mm(y - 3.81)
                    symbol_entries.append(
                        self._placed_symbol(self._support_symbol(component), ref, component.value, x, y, component.footprint)
                    )
                    wires.append(self._wire(pin_x, pin_y, x, pin_y))
                    if top_terminal_y != pin_y:
                        wires.append(self._wire(x, pin_y, x, top_terminal_y))
                    wires.append(self._wire(x, y + 3.81, x, ground_rail_y))
                    junctions.append(self._junction(x, pin_y))
                    junctions.append(self._junction(x, ground_rail_y))
                    continue
                if active_rail_y is not None and any(is_ground_net(net) for net in component.connects):
                    slot = capacitor_side_slots[side]
                    capacitor_side_slots[side] += 1
                    x = self._snap_mm(rail_x1 + 25.4 + slot * 6.35)
                    y = self._snap_mm(active_rail_y + 3.81)
                    symbol_entries.append(
                        self._placed_symbol(self._support_symbol(component), ref, component.value, x, y, component.footprint)
                    )
                    wires.append(self._wire(x, y + 3.81, x, ground_rail_y))
                    junctions.append(self._junction(x, active_rail_y))
                    junctions.append(self._junction(x, ground_rail_y))
                    continue

            power_net = next((net for net in component.connects if is_power_net(net) and not is_ground_net(net)), None)
            signal_net = next((net for net in component.connects if not is_power_net(net) and not is_ground_net(net)), None)
            if self._is_resistor(component) and self._is_pull_resistor(component) and power_net and signal_net:
                signal_pin = pin_rows_by_net.get(signal_net, [None])[0]
                if signal_pin:
                    _pin, side, pin_x, signal_y = signal_pin
                    rail_y = rail_y_for_net(power_net)
                    if rail_y is not None:
                        slot = pullup_side_slots[side]
                        pullup_side_slots[side] += 1
                        x = self._support_x_for_pin(pin_x, side, slot)
                        y = self._snap_mm(signal_y - 3.81 if rail_y <= signal_y else signal_y + 3.81)
                        rail_terminal_y = y - 3.81 if rail_y <= signal_y else y + 3.81
                        symbol_entries.append(
                            self._placed_symbol(self._support_symbol(component), ref, component.value, x, y, component.footprint)
                        )
                        wires.append(self._wire(x, rail_y, x, rail_terminal_y))
                        bounds = signal_line_bounds.get(signal_net)
                        if bounds:
                            start, end, line_y = bounds
                            extension = self._line_extension_to_x(start, end, x, line_y)
                            if extension:
                                wires.append(extension)
                        power_extension = self._line_extension_to_x(rail_x1, rail_x2, x, rail_y)
                        if power_extension:
                            wires.append(power_extension)
                        junctions.append(self._junction(x, rail_y))
                        junctions.append(self._junction(x, signal_y))
                        continue

            anchor_net = next((net for net in component.connects if pin_rows_by_net.get(net)), None)
            anchor_pin = pin_rows_by_net.get(anchor_net or "", [None])[0]
            other_net = next((net for net in component.connects if net != anchor_net), bottom_net)
            other_rail_y = rail_y_for_net(other_net)
            if anchor_pin and other_rail_y is not None and self._should_shunt_to_rail(component, other_net):
                _pin, side, pin_x, pin_y = anchor_pin
                slot = anchored_side_slots[side]
                anchored_side_slots[side] += 1
                x = self._support_x_for_pin(pin_x, side, slot)
                lane = slot // 2
                terminal_offset = 3.81 + lane * 5.08
                y = self._snap_mm(pin_y - terminal_offset if other_rail_y <= pin_y else pin_y + terminal_offset)
                anchor_terminal_y = self._snap_mm(y + 3.81 if other_rail_y <= pin_y else y - 3.81)
                rail_terminal_y = y - 3.81 if other_rail_y <= pin_y else y + 3.81
                symbol_entries.append(
                    self._placed_symbol(self._support_symbol(component), ref, component.value, x, y, component.footprint)
                )
                wires.append(self._wire(pin_x, pin_y, x, pin_y))
                if anchor_terminal_y != pin_y:
                    wires.append(self._wire(x, pin_y, x, anchor_terminal_y))
                wires.append(self._wire(x, other_rail_y, x, rail_terminal_y))
                junctions.append(self._junction(x, pin_y))
                junctions.append(self._junction(x, other_rail_y))
                continue
            if anchor_pin:
                _pin, side, pin_x, pin_y = anchor_pin
                slot = anchored_side_slots[side]
                anchored_side_slots[side] += 1
                x = self._support_x_for_pin(pin_x, side, slot)
                near_x = x + 3.81 if side == "left" else x - 3.81
                far_x = x - 3.81 if side == "left" else x + 3.81
                label_x = far_x - 10.16 if side == "left" else far_x + 10.16
                symbol_entries.append(
                    self._placed_symbol(
                        self._support_symbol(component),
                        ref,
                        component.value,
                        x,
                        pin_y,
                        component.footprint,
                        rotation=self._inline_support_rotation(component),
                    )
                )
                wires.append(self._wire(pin_x, pin_y, near_x, pin_y))
                wires.append(self._wire(far_x, pin_y, label_x, pin_y))
                labels.append(self._label(other_net, label_x, pin_y))
                junctions.append(self._junction(near_x, pin_y))
                continue

            x = 45.72 + (generic_index % 3) * 45.72
            y = ground_rail_y + 25.4 + (generic_index // 3) * 22.86
            generic_index += 1
            symbol_entries.append(
                self._placed_symbol(self._support_symbol(component), ref, component.value, x, y, component.footprint)
            )
            labels.extend(self._support_terminal_labels(x, y, top_net, bottom_net))
            wires.extend(self._support_terminal_wires(x, y))
            if len(component.connects) > 2:
                labels.append(self._text(f"{ref} extra nets: {', '.join(component.connects[2:])}", x + 7.62, y + 10.16))

        return f"""(kicad_sch (version 20230121) (generator "Trace Labs")
  (uuid "{uuid4()}")
  (paper "A4")
  (title_block
    (title "{block.block_name}")
    (company "Trace Labs")
    (comment 1 "Generated from cited datasheet/reference extraction")
    (comment 2 "Review extracted pins, passives, symbol and footprint")
  )
  (lib_symbols
{self._generic_library_symbols(block)}
  )
{chr(10).join(wires)}
{chr(10).join(junctions)}
{chr(10).join(no_connects)}
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

    def _support_x_for_pin(self, pin_x: float, side: str, slot: int) -> float:
        offset = 20.32 + slot * 7.62
        if side == "left":
            return self._snap_mm(pin_x - offset)
        return self._snap_mm(pin_x + offset)

    def _line_extension_to_x(self, start_x: float, end_x: float, target_x: float, y: float) -> str | None:
        left = min(start_x, end_x)
        right = max(start_x, end_x)
        if target_x < left:
            return self._wire(target_x, y, left, y)
        if target_x > right:
            return self._wire(right, y, target_x, y)
        return None

    def _no_connect(self, x: float, y: float) -> str:
        return f'  (no_connect (at {self._format_mm(x)} {self._format_mm(y)}) (uuid "{uuid4()}"))'

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

    def _support_ref(self, component, index: int) -> str:
        prefix = (
            "C"
            if self._is_capacitor(component)
            else "D"
            if self._is_diode(component)
            else "L"
            if self._is_inductor(component)
            else "R"
            if self._is_resistor(component)
            else "X"
        )
        ref = str(component.reference or "").replace("?", "").strip()
        if ref and ref != prefix:
            return ref
        return f"{prefix}{index}"

    def _support_symbol(self, component) -> str:
        if self._is_capacitor(component):
            return "Device:C"
        if self._is_diode(component):
            return "Device:D"
        if self._is_inductor(component):
            return "Device:L"
        if self._is_resistor(component):
            return "Device:R"
        return component.symbol

    def _inline_support_rotation(self, component) -> int:
        return 90

    def _rail_y_for_net(
        self,
        net: str,
        power_rail_y: dict[str, float],
        ground_rail_y: float,
    ) -> float | None:
        if self._is_ground_net(net):
            return ground_rail_y
        return power_rail_y.get(net)

    def _preferred_non_ground_net(self, nets: list[str]) -> str | None:
        return next((net for net in nets if not self._is_ground_net(net)), None)

    def _is_resistor(self, component) -> bool:
        return "resistor" in str(component.type).lower() or str(component.symbol).lower() == "device:r"

    def _is_capacitor(self, component) -> bool:
        return "capacitor" in str(component.type).lower() or str(component.symbol).lower() == "device:c"

    def _is_inductor(self, component) -> bool:
        return "inductor" in str(component.type).lower() or str(component.symbol).lower() == "device:l"

    def _is_pull_resistor(self, component) -> bool:
        purpose = str(component.purpose).lower()
        return bool(re.search(r"pull[-\s]?(?:up|down)", purpose))

    def _should_shunt_to_rail(self, component, other_net: str) -> bool:
        if self._is_ground_net(other_net):
            return True
        if self._is_pull_resistor(component):
            return True
        return "capacitor" in str(component.type).lower() and any(
            self._is_ground_net(net) for net in component.connects
        )

    def _unique_strings(self, values) -> list[str]:
        result = []
        for value in values:
            if not value or value in result:
                continue
            result.append(value)
        return result

    def _is_ground_net(self, net: str) -> bool:
        upper = net.upper()
        return upper in {"GND", "DGND", "AGND"} or upper.endswith("_GND")

    def _is_no_connect_pin(self, pin) -> bool:
        name = (pin.name or "").upper()
        net = (pin.net_name or "").upper()
        role = (pin.electrical_type or "").lower()
        return (
            "no_connect" in role
            or "do not connect" in role
            or name in {"NC", "DNC", "RESV"}
            or net.startswith("NC_")
            or net.startswith("DNC_")
            or "DNC_FLOAT" in net
        )

    def _is_power_net(self, net: str) -> bool:
        upper = net.upper()
        return (
            self._is_ground_net(net)
            or upper.startswith("+")
            or upper.startswith("VDD")
            or upper.startswith("VCC")
            or upper.startswith("VIO")
            or upper == "VPU"
            or upper == "IOVDD"
            or upper.startswith("VBAT")
            or upper.endswith("_VDD")
            or upper.endswith("_VCC")
        )

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
        return 127 + column * 17.78, 63.5 + row * 10.16

    def _reference_base(self, block_slug: str) -> int:
        total = sum((index + 1) * ord(char) for index, char in enumerate(block_slug))
        return 100 + (total % 800)

    def _generic_library_symbols(self, block: CircuitBlock) -> str:
        return "\n".join(
            [
                self.draft_library_assets.schematic_cached_symbol(block),
                self._capacitor_library_symbol(),
                self._diode_library_symbol(),
                self._inductor_library_symbol(),
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

    def _diode_library_symbol(self) -> str:
        return """    (symbol "Device:D" (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "D" (at 2.54 0 90) (effects (font (size 1.27 1.27))))
      (property "Value" "D" (at -2.54 0 90) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at 0 -3.81 0) (effects (font (size 1.27 1.27)) hide))
      (symbol "D_0_1"
        (polyline (pts (xy 0 -1.905) (xy -1.27 1.905) (xy 1.27 1.905) (xy 0 -1.905)) (stroke (width 0.254) (type default)) (fill (type none)))
        (polyline (pts (xy -1.27 -1.905) (xy 1.27 -1.905)) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "D_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27) (name "") (number "1"))
        (pin passive line (at 0 -3.81 90) (length 1.27) (name "") (number "2"))
      )
    )"""

    def _inductor_library_symbol(self) -> str:
        return """    (symbol "Device:L" (pin_numbers hide) (pin_names (offset 0)) (in_bom yes) (on_board yes)
      (property "Reference" "L" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
      (property "Value" "L" (at 0 0 90) (effects (font (size 1.27 1.27))))
      (property "Footprint" "" (at -1.778 0 90) (effects (font (size 1.27 1.27)) hide))
      (symbol "L_0_1"
        (polyline (pts (xy 0 -2.54) (xy 0 -1.27) (xy -1.016 -0.635) (xy 1.016 0) (xy -1.016 0.635) (xy 1.016 1.27) (xy 0 1.905) (xy 0 2.54)) (stroke (width 0.254) (type default)) (fill (type none)))
      )
      (symbol "L_1_1"
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

        if lib_id in {"Device:R", "Device:D", "Device:L"} and rotation == 90:
            return (x - 3.81, y - 5.08, 0, x - 3.81, y + 5.08, 0, x, y + 7.62)

        if lib_id == "Device:R":
            return (x + 7.62, y - 3.81, 0, x + 7.62, y, 0, x, y + 7.62)

        return (x, y - 8.0, 0, x, y + 8.0, 0, x, y + 10.0)

    def _is_diode(self, component) -> bool:
        return "diode" in str(component.type).lower() or str(component.symbol).lower() == "device:d"

    def _format_mm(self, value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")

    def _snap_mm(self, value: float) -> float:
        return round(value, 2)

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
                    self._wire(132.08, 50.8, 132.08, 71.12),
                ]
            )
        if scl_pullup:
            wires.extend(
                [
                    self._wire(139.7, 50.8, 139.7, 66.04),
                ]
            )
        return wires

    def _pullup_junctions(self, sda_pullup, scl_pullup) -> list[str]:
        junctions = []
        if sda_pullup:
            junctions.extend([self._junction(132.08, 50.8), self._junction(132.08, 78.74)])
        if scl_pullup:
            junctions.extend([self._junction(139.7, 50.8), self._junction(139.7, 73.66)])
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
