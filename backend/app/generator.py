from __future__ import annotations

import json
import re
from pathlib import Path

from .models import (
    AnswerQuestionsRequest,
    CircuitBlock,
    Component,
    DatasheetSource,
    MissingQuestion,
    NextStep,
    Option,
    ProjectContext,
    ReferenceCircuitExtraction,
    SchematicPreview,
    SupportComponent,
    UsageEvent,
    ValidationWarning,
)


class RecipeLoader:
    def __init__(self, recipes_dir: Path):
        self.recipes_dir = recipes_dir

    def bme280(self) -> dict:
        path = self.recipes_dir / "bme280_i2c.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def recipe(self, recipe_id: str) -> dict:
        if recipe_id != "bme280_i2c":
            raise ValueError(f"Unsupported recipe: {recipe_id}")
        return self.bme280()

    def save_draft_from_block(self, block: CircuitBlock) -> Path:
        drafts_dir = self.recipes_dir / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)
        path = drafts_dir / f"{block.block_slug}.json"
        recipe = {
            "id": f"draft_{block.block_slug}",
            "block_name": block.block_name,
            "block_slug": block.block_slug,
            "summary": block.summary,
            "recipe_source": block.recipe_source,
            "recipe_status": "needs_review",
            "recipe_review_confirmed": block.recipe_review_confirmed,
            "main_component": block.main_component.model_dump(),
            "support_components": [component.model_dump() for component in block.support_components],
            "external_nets": block.external_nets,
            "internal_nets": block.internal_nets,
            "assumptions": block.assumptions,
            "selected_options": block.selected_options,
            "validation_warnings": [warning.model_dump() for warning in block.validation_warnings],
            "next_steps": [step.model_dump() for step in block.next_steps],
            "datasheet_sources": [source.model_dump() for source in block.datasheet_sources],
        }
        path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
        return path

    def summaries(self) -> list[dict]:
        summaries = []
        for path in sorted(self.recipes_dir.glob("*.json")):
            recipe = json.loads(path.read_text(encoding="utf-8"))
            summaries.append(
                {
                    "id": recipe.get("block_slug", recipe["id"]),
                    "display_name": recipe["block_name"],
                    "manufacturer": recipe["main_component"]["manufacturer"],
                    "mpn": recipe["main_component"]["mpn"],
                    "interface": "I2C",
                }
            )
        return summaries


class CircuitGenerator:
    def __init__(self, loader: RecipeLoader):
        self.loader = loader

    def is_supported_prompt(self, message: str) -> bool:
        text = message.lower()
        return any(
            term in text
            for term in [
                "bme280",
                "temperature sensor",
                "temp sensor",
                "temperature",
                "environmental sensor",
                "humidity sensor",
                "pressure sensor",
            ]
        )

    def draft(self, recipe_id: str = "bme280_i2c") -> CircuitBlock:
        if recipe_id != "bme280_i2c":
            raise ValueError(f"Unsupported recipe: {recipe_id}")
        return self._build(status="awaiting_answers", answers={})

    def finalise(self, request: AnswerQuestionsRequest) -> CircuitBlock:
        if request.draft_block and request.draft_block.recipe_source == "ai_proposed":
            return self._finalise_ai_proposed(request)

        answers = {
            "logic_voltage": "3.3V",
            "interface_mode": "I2C",
            "i2c_address": "0x76",
            "pullups": "add",
            "pullup_value": "4.7 kOhm",
            **request.answers,
        }
        block = self._build(status="final", answers=answers)
        block.missing_questions = []
        block.selected_options = answers
        block.recipe_review_confirmed = True
        block.usage_events.append(
            UsageEvent(event_type="circuit_block.generated", metadata={"block_slug": block.block_slug})
        )
        return block

    def ai_extracted_draft(
        self,
        extraction: ReferenceCircuitExtraction,
        supplier: str = "",
        supplier_part_number: str = "",
        supplier_url: str = "",
    ) -> CircuitBlock:
        return self._build_from_extraction(
            extraction=extraction,
            status="awaiting_answers",
            answers={},
            saved_path=None,
            supplier=supplier,
            supplier_part_number=supplier_part_number,
            supplier_url=supplier_url,
        )

    def _build(self, status: str, answers: dict[str, str]) -> CircuitBlock:
        recipe = self.loader.bme280()
        main_raw = recipe["main_component"]
        logic = answers.get("logic_voltage", "3.3V")
        logic_net = "+3V3" if logic == "3.3V" else "+1V8"
        address = answers.get("i2c_address", "0x76")
        add_pullups = answers.get("pullups", "add") == "add"
        pullup_value = answers.get("pullup_value", "4.7 kOhm")
        rendered_pullup_value = "TBD" if pullup_value == "unspecified" else pullup_value

        main = Component(
            reference="U?",
            type="IC",
            value="BME280",
            mpn=main_raw["mpn"],
            manufacturer=main_raw["manufacturer"],
            symbol=main_raw["symbol"],
            footprint=main_raw["footprint"],
            purpose=main_raw["purpose"],
            connects=[logic_net, "GND", "I2C1_SDA", "I2C1_SCL", f"SDO={address}", "CSB=I2C"],
            footprint_confidence="needs_review",
            symbol_confidence="recipe_suggested",
            assignment_reason="Selected from PCBStream project library assets cached from official KiCad library sources.",
        )

        support = [
            SupportComponent(
                reference="C?",
                type="capacitor",
                value="100 nF",
                purpose="VDD decoupling",
                symbol="Device:C",
                footprint="Capacitor_SMD:C_0603_1608Metric",
                connects=[logic_net, "GND"],
            ),
            SupportComponent(
                reference="C?",
                type="capacitor",
                value="100 nF",
                purpose="VDDIO decoupling",
                symbol="Device:C",
                footprint="Capacitor_SMD:C_0603_1608Metric",
                connects=[logic_net, "GND"],
            ),
        ]
        if add_pullups:
            support.extend(
                [
                    SupportComponent(
                        reference="R?",
                        type="resistor",
                        value=rendered_pullup_value,
                        purpose="I2C SDA pull-up",
                        symbol="Device:R",
                        footprint="Resistor_SMD:R_0603_1608Metric",
                        connects=["I2C1_SDA", logic_net],
                    ),
                    SupportComponent(
                        reference="R?",
                        type="resistor",
                        value=rendered_pullup_value,
                        purpose="I2C SCL pull-up",
                        symbol="Device:R",
                        footprint="Resistor_SMD:R_0603_1608Metric",
                        connects=["I2C1_SCL", logic_net],
                    ),
                ]
            )
        questions = [
            MissingQuestion(
                id="logic_voltage",
                question="What logic voltage should be used?",
                options=[Option(label="1.8V", value="1.8V"), Option(label="3.3V", value="3.3V")],
                default="3.3V",
            ),
            MissingQuestion(
                id="interface_mode",
                question="Which interface should be used?",
                options=[Option(label="I2C", value="I2C"), Option(label="SPI", value="SPI")],
                default="I2C",
            ),
            MissingQuestion(
                id="i2c_address",
                question="Which I2C address should be used?",
                options=[Option(label="0x76", value="0x76"), Option(label="0x77", value="0x77")],
                default="0x76",
            ),
            MissingQuestion(
                id="pullups",
                question="Should pull-ups be added or does the board already have I2C pull-ups?",
                options=[
                    Option(label="Add 4.7k pull-ups", value="add"),
                    Option(label="Board already has pull-ups", value="skip"),
                ],
                default="add",
            ),
            MissingQuestion(
                id="pullup_value",
                question=(
                    "What I2C pull-up value should PCBStream place? This depends on bus capacitance, "
                    "I2C speed, and how many devices are on the bus."
                ),
                options=[
                    Option(label="Use 4.7 kOhm", value="4.7 kOhm"),
                    Option(label="Not sure - leave value unspecified", value="unspecified"),
                ],
                default="4.7 kOhm",
                depends_on={"pullups": "add"},
            ),
        ]

        warnings = [
            ValidationWarning(
                severity="critical",
                message="Verify exact BME280 package and footprint before ordering the PCB.",
                related_component="U?",
                fix_hint="Confirm the Bosch ordering code and footprint in KiCad.",
            ),
            ValidationWarning(
                severity="warning",
                message="Pull-up value depends on bus capacitance and I2C speed.",
                fix_hint="Use 4.7 kOhm as a starting point, then review the bus.",
            ),
            ValidationWarning(
                severity="warning",
                message="Avoid duplicate I2C pull-ups if the bus already has them.",
                fix_hint="Remove generated pull-ups if board-level pull-ups exist.",
            ),
            ValidationWarning(
                severity="info",
                message="Run ERC in KiCad after insertion.",
                fix_hint="Use KiCad Inspect > Electrical Rules Checker.",
            ),
        ]
        if add_pullups and pullup_value == "unspecified":
            warnings.append(
                ValidationWarning(
                    severity="critical",
                    message="I2C pull-up resistors were placed without a numeric value.",
                    fix_hint="Calculate pull-ups from bus capacitance and target I2C rise time before fabrication.",
                )
            )
        next_steps = [
            NextStep(id="footprint", category="review", task="Verify BME280 footprint."),
            NextStep(id="gpio", category="connect", task="Connect SDA/SCL to MCU I2C-capable GPIO pins."),
            NextStep(id="pullups", category="review", task="Check duplicate I2C pull-ups."),
            NextStep(id="erc", category="verify", task="Run ERC."),
            NextStep(id="layout", category="layout", task="Place decoupling capacitors close to the sensor."),
            NextStep(id="firmware", category="firmware", task=f"Add firmware driver with I2C address {address}."),
        ]
        preview = SchematicPreview(
            title="BME280 I2C Schematic Preview",
            description="Reviewable PCBStream schematic block for a Bosch BME280 over I2C.",
            ascii_preview=(
                f"{logic_net} --+-- BME280 VDD/VDDIO\n"
                "        |-- C 100nF -- GND\n"
                "I2C1_SDA -- BME280 SDA\n"
                "I2C1_SCL -- BME280 SCL\n"
                f"SDO strapped for {address}"
            ),
            connections=[logic_net, "GND", "I2C1_SDA", "I2C1_SCL", f"address {address}"],
            notes=["Preview is generated from local recipe data and must be reviewed in KiCad."],
        )

        return CircuitBlock(
            block_name=recipe["block_name"],
            block_slug=recipe["block_slug"],
            summary=recipe["summary"],
            main_component=main,
            support_components=support,
            external_nets=[logic_net, "GND", "I2C1_SDA", "I2C1_SCL"],
            internal_nets=["BME280_SDO", "BME280_CSB"],
            assumptions=recipe["assumptions"],
            missing_questions=questions if status != "final" else [],
            validation_warnings=warnings,
            next_steps=next_steps,
            datasheet_sources=[
                DatasheetSource(
                    title="Bosch BME280 Datasheet (Local Recipe)",
                    confidence="local_recipe_verified",
                    notes="Mock manufacturer source bundled with PCBStream MVP.",
                )
            ],
            schematic_preview=preview,
            selected_options=answers,
            status=status,
            recipe_source="local_verified",
            recipe_status="verified",
            recipe_review_confirmed=True,
        )

    def _finalise_ai_proposed(self, request: AnswerQuestionsRequest) -> CircuitBlock:
        draft = request.draft_block
        if draft is None:
            raise ValueError("A proposed recipe draft is required.")

        answers = {
            "recipe_review_confirmed": "confirm",
            **request.answers,
        }
        if answers.get("recipe_review_confirmed") != "confirm":
            raise ValueError("New AI-proposed recipes must be explicitly confirmed before generation.")

        if draft.reference_extraction is None or draft.extraction_status != "ready":
            raise ValueError(
                "AI-proposed recipes require completed datasheet/reference-design extraction before generation."
            )

        block = self._build_from_extraction(
            extraction=draft.reference_extraction,
            status="final",
            answers=answers,
            saved_path=None,
            supplier=draft.main_component.supplier or "",
            supplier_part_number=draft.main_component.supplier_part_number or "",
            supplier_url=draft.main_component.supplier_url or "",
        )
        block.missing_questions = []
        block.recipe_review_confirmed = True
        block.usage_events.append(
            UsageEvent(event_type="circuit_block.generated", metadata={"block_slug": block.block_slug})
        )
        saved_path = self.loader.save_draft_from_block(block)
        block.recipe_saved_path = str(saved_path)
        return block

    def _build_from_extraction(
        self,
        extraction: ReferenceCircuitExtraction,
        status: str,
        answers: dict[str, str],
        saved_path: str | None,
        supplier: str = "",
        supplier_part_number: str = "",
        supplier_url: str = "",
    ) -> CircuitBlock:
        clean_part = extraction.part_number.strip() or "UnknownPart"
        clean_manufacturer = extraction.manufacturer.strip() or "Unknown manufacturer"
        safe_part = _library_safe(clean_part)
        library_name = f"PCBStream_{safe_part}"
        symbol_id = f"{library_name}:{safe_part}"
        footprint_id = f"{library_name}:{library_name}_PLACEHOLDER"
        slug = _slugify(f"{clean_manufacturer}_{clean_part}_ai_draft")

        support_components = []
        prefix_counts: dict[str, int] = {}
        for requirement in extraction.support_requirements:
            prefix = (requirement.reference_prefix or requirement.type[:1] or "?").upper()
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
            support_components.append(
                SupportComponent(
                    reference=f"{prefix}?",
                    type=requirement.type,
                    value=requirement.value,
                    purpose=requirement.purpose,
                    symbol=self._symbol_for_support(requirement.type),
                    footprint=requirement.footprint or self._footprint_for_support(requirement.type),
                    connects=requirement.connects,
                    assignment_reason=(
                        f"Extracted from datasheet/reference-design evidence: {', '.join(requirement.source_citations)}"
                    ),
                    source_citations=requirement.source_citations,
                )
            )

        net_names = [net.name for net in extraction.nets] or sorted({pin.net_name for pin in extraction.pins})
        external_nets = [net.name for net in extraction.nets if net.external] or [
            net for net in net_names if net == "GND" or net.startswith("+") or net.upper() in {"SDA", "SCL", "MISO", "MOSI", "SCK", "CS"}
        ]
        internal_nets = [net for net in net_names if net not in external_nets]
        questions = [
            MissingQuestion(
                id="recipe_review_confirmed",
                question=(
                    f"{clean_manufacturer} {clean_part} was extracted from downloaded datasheet/reference sources. "
                    "Confirm that PCBStream should generate a reviewable KiCad block from the cited pin map."
                ),
                options=[
                    Option(label="Confirm extracted circuit", value="confirm"),
                    Option(label="Cancel", value="cancel"),
                ],
                default="cancel",
            )
        ]
        warnings = [
            ValidationWarning(
                severity="critical",
                message="This AI-proposed circuit was extracted from datasheet/reference sources and still needs review.",
                related_component="U?",
                fix_hint="Check every cited pin, passive value, symbol, footprint, and package before fabrication.",
            )
        ]
        warnings.extend(
            ValidationWarning(
                severity="warning",
                message=warning,
                related_component="U?",
                fix_hint="Open the cited source chunk in the export notes and verify manually.",
            )
            for warning in extraction.validation_warnings
        )
        next_steps = [
            NextStep(id="source-review", category="review", task="Review extracted source citations for pins and passives."),
            NextStep(id="cad-assets", category="library", task="Review downloaded symbol and footprint assets."),
            NextStep(id="erc", category="verify", task="Run ERC after insertion."),
        ]
        preview = SchematicPreview(
            title=f"{clean_part} Extracted Schematic Preview",
            description="PCBStream schematic block generated from cited datasheet/reference-design extraction.",
            ascii_preview="\n".join(
                [
                    f"{pin.number} {pin.name} -> {pin.net_name}"
                    for pin in extraction.pins[:12]
                ]
            ),
            connections=net_names,
            notes=[
                "Pins and support components were extracted from downloaded source chunks.",
                "Export is blocked if extraction evidence is incomplete.",
            ],
        )
        source_map = {chunk.source_url: chunk for chunk in extraction.source_chunks}
        datasheet_sources = [
            DatasheetSource(
                title=chunk.title or f"{clean_part} source",
                source_type="manufacturer_datasheet",
                url=url,
                confidence="extracted_with_citations",
                notes="Used for pin/support extraction.",
            )
            for url, chunk in source_map.items()
        ]

        return CircuitBlock(
            block_name=f"{clean_manufacturer} {clean_part} Extracted Draft",
            block_slug=slug,
            summary=(
                f"Datasheet-derived draft for {clean_manufacturer} {clean_part}. "
                f"Interface: {extraction.interface or 'unspecified'}. Package: {extraction.package or 'unspecified'}."
            ),
            main_component=Component(
                reference="U?",
                type="IC",
                value=clean_part,
                mpn=clean_part,
                manufacturer=clean_manufacturer,
                supplier=supplier or None,
                supplier_part_number=supplier_part_number or None,
                supplier_url=supplier_url or None,
                symbol=symbol_id,
                footprint=footprint_id,
                purpose=f"Main IC extracted from datasheet/reference sources for {clean_part}.",
                connects=net_names,
                footprint_confidence="needs_review",
                symbol_confidence="datasheet_extracted_needs_review",
                assignment_reason="Symbol pin map is generated from cited datasheet/reference-design extraction.",
            ),
            support_components=support_components,
            external_nets=external_nets,
            internal_nets=internal_nets,
            assumptions=[
                "This recipe was extracted from downloaded datasheet/reference-design sources.",
                "Every generated pin and support component must keep a source citation.",
                "KiCad export is blocked if the extracted evidence is incomplete.",
            ],
            missing_questions=questions if status != "final" else [],
            validation_warnings=warnings,
            next_steps=next_steps,
            datasheet_sources=datasheet_sources,
            schematic_preview=preview,
            selected_options=answers,
            status=status,
            recipe_source="ai_proposed",
            recipe_status="needs_review",
            recipe_review_confirmed=answers.get("recipe_review_confirmed") == "confirm",
            recipe_saved_path=saved_path,
            extraction_status="ready",
            reference_extraction=extraction,
        )

    def _symbol_for_support(self, component_type: str) -> str:
        lowered = component_type.lower()
        if "cap" in lowered:
            return "Device:C"
        if "res" in lowered or "pull" in lowered:
            return "Device:R"
        return "Device:R"

    def _footprint_for_support(self, component_type: str) -> str:
        lowered = component_type.lower()
        if "cap" in lowered:
            return "Capacitor_SMD:C_0603_1608Metric"
        return "Resistor_SMD:R_0603_1608Metric"


def default_project_context() -> ProjectContext:
    return ProjectContext()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "ai_proposed_recipe"


def _library_safe(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_")
    return safe or "DraftPart"
