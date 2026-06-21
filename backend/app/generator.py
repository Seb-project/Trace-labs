from __future__ import annotations

import json
import math
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
    SupportRequirement,
    UsageEvent,
    ValidationWarning,
)
from .part_intent import normalise_part_number


class RecipeLoader:
    def __init__(self, recipes_dir: Path):
        self.recipes_dir = recipes_dir
        self.use_saved_drafts = True

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
            "schematic_preview": block.schematic_preview.model_dump(),
            "extraction_status": block.extraction_status,
        }
        if block.reference_extraction is not None:
            recipe["reference_extraction"] = block.reference_extraction.model_dump()
        path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
        return path

    def saved_draft_for_part(self, part_numbers: list[str]) -> dict | None:
        if not self.use_saved_drafts:
            return None
        targets = {normalise_part_number(part) for part in part_numbers if part}
        if not targets:
            return None
        drafts_dir = self.recipes_dir / "drafts"
        for path in sorted(drafts_dir.glob("*.json")):
            try:
                recipe = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            main_component = recipe.get("main_component", {})
            values = [
                main_component.get("mpn"),
                main_component.get("value"),
                recipe.get("block_slug"),
                recipe.get("block_name"),
            ]
            normalized_values = [normalise_part_number(str(value)) for value in values if value]
            if any(
                value in targets or any(target and target in value for target in targets)
                for value in normalized_values
            ):
                recipe["_path"] = str(path)
                return recipe
        return None

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

    def saved_draft(self, part_numbers: list[str]) -> CircuitBlock | None:
        recipe = self.loader.saved_draft_for_part(part_numbers)
        if recipe is None:
            return None
        return self._build_from_saved_recipe(recipe)

    def finalise(self, request: AnswerQuestionsRequest) -> CircuitBlock:
        if request.draft_block and request.draft_block.recipe_source == "ai_proposed":
            return self._finalise_ai_proposed(request)
        if request.draft_block and request.draft_block.recipe_source == "saved_draft":
            return self._finalise_saved_draft(request)

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
            assignment_reason="Selected from Trace Labs project library assets cached from official KiCad library sources.",
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
                    "What I2C pull-up value should Trace Labs place? This depends on bus capacitance, "
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
            description="Reviewable Trace Labs schematic block for a Bosch BME280 over I2C.",
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
                    notes="Mock manufacturer source bundled with Trace Labs MVP.",
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
        if draft.main_component.footprint_asset is not None:
            block.main_component.footprint_asset = draft.main_component.footprint_asset
            block.main_component.footprint = draft.main_component.footprint
            block.main_component.footprint_confidence = draft.main_component.footprint_confidence
            block.main_component.assignment_reason = draft.main_component.assignment_reason
        block.missing_questions = []
        block.recipe_review_confirmed = True
        block.usage_events.append(
            UsageEvent(event_type="circuit_block.generated", metadata={"block_slug": block.block_slug})
        )
        saved_path = self.loader.save_draft_from_block(block)
        block.recipe_saved_path = str(saved_path)
        return block

    def _finalise_saved_draft(self, request: AnswerQuestionsRequest) -> CircuitBlock:
        draft = request.draft_block
        if draft is None:
            raise ValueError("A saved draft recipe is required.")

        answers = {
            "recipe_review_confirmed": "confirm",
            **request.answers,
        }
        if answers.get("recipe_review_confirmed") != "confirm":
            raise ValueError("Saved draft recipes must be explicitly confirmed before generation.")

        block = draft.model_copy(deep=True)
        block.status = "final"
        block.missing_questions = []
        block.selected_options = answers
        block.recipe_review_confirmed = True
        block.usage_events.append(
            UsageEvent(event_type="circuit_block.generated", metadata={"block_slug": block.block_slug})
        )
        return block

    def _build_from_saved_recipe(self, recipe: dict) -> CircuitBlock:
        main = Component.model_validate(recipe["main_component"])
        clean_part = main.mpn or main.value or "UnknownPart"
        clean_manufacturer = main.manufacturer or "Unknown manufacturer"
        extraction = None
        if isinstance(recipe.get("reference_extraction"), dict):
            extraction = ReferenceCircuitExtraction.model_validate(recipe["reference_extraction"])
        preview = self._saved_recipe_preview(recipe, main)
        recipe_source = "ai_proposed" if extraction is not None else "saved_draft"
        return CircuitBlock(
            block_name=str(recipe.get("block_name") or f"{clean_manufacturer} {clean_part} Saved Draft"),
            block_slug=str(recipe.get("block_slug") or _slugify(f"{clean_manufacturer}_{clean_part}_saved_draft")),
            summary=str(recipe.get("summary") or f"Saved local draft for {clean_manufacturer} {clean_part}."),
            main_component=main,
            support_components=[
                self._support_component_with_reviewable_value(
                    SupportComponent.model_validate(component),
                    allow_tbd=self._answers_indicate_not_sure(recipe.get("selected_options", {})),
                )
                for component in recipe.get("support_components", [])
                if isinstance(component, dict)
            ],
            external_nets=[str(net) for net in recipe.get("external_nets", [])],
            internal_nets=[str(net) for net in recipe.get("internal_nets", [])],
            assumptions=[str(item) for item in recipe.get("assumptions", [])],
            missing_questions=[self._recipe_review_question(clean_manufacturer, clean_part)],
            validation_warnings=[
                ValidationWarning.model_validate(warning)
                for warning in recipe.get("validation_warnings", [])
                if isinstance(warning, dict)
            ],
            next_steps=[
                NextStep.model_validate(step)
                for step in recipe.get("next_steps", [])
                if isinstance(step, dict)
            ],
            datasheet_sources=[
                DatasheetSource.model_validate(source)
                for source in recipe.get("datasheet_sources", [])
                if isinstance(source, dict)
            ],
            schematic_preview=preview,
            selected_options={},
            status="awaiting_answers",
            recipe_source=recipe_source,
            recipe_status="needs_review",
            recipe_review_confirmed=False,
            recipe_saved_path=recipe.get("_path"),
            extraction_status="ready" if extraction is not None else "not_required",
            reference_extraction=extraction,
        )

    def _saved_recipe_preview(self, recipe: dict, main: Component) -> SchematicPreview:
        if isinstance(recipe.get("schematic_preview"), dict):
            try:
                return SchematicPreview.model_validate(recipe["schematic_preview"])
            except ValueError:
                pass
        return SchematicPreview(
            title=f"{main.value} Saved Draft Preview",
            description="Reviewable Trace Labs schematic block loaded from a saved local draft.",
            ascii_preview="\n".join(main.connects[:12]) or main.value,
            connections=main.connects,
            notes=["Loaded from backend/recipes/drafts; review before KiCad insertion."],
        )

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
        extraction = self._resolve_calculated_requirements(extraction, answers)
        extraction = self._with_reviewable_support_values(
            extraction,
            allow_tbd=self._answers_indicate_not_sure(answers),
        )
        clean_part = extraction.part_number.strip() or "UnknownPart"
        clean_manufacturer = extraction.manufacturer.strip() or "Unknown manufacturer"
        safe_part = _library_safe(clean_part)
        library_name = f"TraceLabs_{safe_part}"
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
            *self._calculation_questions(extraction),
            self._recipe_review_question(clean_manufacturer, clean_part),
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
            description="Trace Labs schematic block generated from cited datasheet/reference-design extraction.",
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

    def _with_reviewable_support_values(
        self,
        extraction: ReferenceCircuitExtraction,
        *,
        allow_tbd: bool,
    ) -> ReferenceCircuitExtraction:
        support_requirements = []
        notes = list(extraction.extraction_notes)
        for requirement in extraction.support_requirements:
            if not self._is_unspecified_value(requirement.value) or allow_tbd:
                support_requirements.append(requirement)
                continue
            starter_value = self._starter_value_for_support(
                requirement.type,
                requirement.purpose,
                requirement.calculation_role,
            )
            support_requirements.append(
                requirement.model_copy(
                    update={
                        "value": starter_value,
                        "placement_note": self._starter_placement_note(requirement, starter_value),
                    }
                )
            )
            notes.append(
                f"Selected reviewable starter value {starter_value} for {requirement.purpose}; verify before fabrication."
            )
        return extraction.model_copy(
            update={
                "support_requirements": support_requirements,
                "extraction_notes": list(dict.fromkeys(notes)),
            }
        )

    def _support_component_with_reviewable_value(
        self,
        component: SupportComponent,
        *,
        allow_tbd: bool,
    ) -> SupportComponent:
        if not self._is_unspecified_value(component.value) or allow_tbd:
            return component
        starter_value = self._starter_value_for_support(component.type, component.purpose)
        assignment_reason = (
            f"{component.assignment_reason} Starter value {starter_value} selected because the cached draft "
            "did not include a value; verify before fabrication."
        )
        return component.model_copy(
            update={
                "value": starter_value,
                "assignment_reason": assignment_reason,
            }
        )

    def _starter_placement_note(self, requirement: SupportRequirement, starter_value: str) -> str:
        base = requirement.placement_note or "Verify this starter value against the datasheet."
        return f"{base} Starter value selected: {starter_value}; verify before fabrication."

    def _starter_value_for_support(
        self,
        component_type: str,
        purpose: str,
        calculation_role: str = "",
    ) -> str:
        role = calculation_role.lower()
        purpose_text = purpose.lower()
        type_text = component_type.lower()
        if role == "buck_output_inductor" or "inductor" in type_text:
            return "4.7 uH"
        if role in {"feedback_divider_upper", "feedback_divider_lower"}:
            return "100 kOhm"
        if "bootstrap" in purpose_text:
            return "100 nF"
        if "pull-up" in purpose_text or "pullup" in purpose_text:
            return "4.7 kOhm"
        if "output capacitor" in purpose_text:
            return "22 uF"
        if "input" in purpose_text and "capacitor" in type_text:
            return "10 uF"
        if "decoupl" in purpose_text or "bypass" in purpose_text:
            return "100 nF"
        if "capacitor" in type_text or type_text == "cap":
            return "100 nF"
        if "resistor" in type_text or type_text == "res":
            return "10 kOhm"
        if "diode" in type_text or type_text == "d":
            return "review diode"
        return "review value"

    def _is_unspecified_value(self, value: str) -> bool:
        return value.strip().lower() in {"tbd", "not specified", "unspecified", ""}

    def _answers_indicate_not_sure(self, answers: dict | None) -> bool:
        if not isinstance(answers, dict):
            return False
        not_sure_values = {"unspecified", "not sure", "unknown", "don't know", "do not know"}
        return any(str(value).strip().lower() in not_sure_values for value in answers.values())

    def _calculation_questions(self, extraction: ReferenceCircuitExtraction) -> list[MissingQuestion]:
        input_ids = []
        for requirement in extraction.support_requirements:
            if not requirement.calculation_inputs:
                continue
            if not self._requirement_needs_calculation_inputs(requirement):
                continue
            for input_id in requirement.calculation_inputs:
                if input_id not in input_ids:
                    input_ids.append(input_id)

        defaults = self._calculation_defaults(extraction)
        labels = {
            "calc_input_voltage_v": "Input voltage in volts",
            "calc_output_voltage_v": "Output voltage in volts",
            "calc_output_current_a": "Maximum output current in amps",
            "calc_switching_frequency_khz": "Switching frequency in kHz",
            "calc_inductor_ripple_percent": "Inductor ripple current target in percent",
            "calc_feedback_reference_voltage_v": "Feedback reference voltage in volts",
            "calc_feedback_lower_resistance_kohm": "Lower feedback resistor in kOhm",
            "calc_voltage_gain": "Voltage gain",
            "calc_gain_reference_resistance_kohm": "Reference gain resistor in kOhm",
        }
        questions = []
        for input_id in input_ids:
            label = labels.get(input_id, input_id.replace("_", " "))
            questions.append(
                MissingQuestion(
                    id=input_id,
                    question=f"{label}?",
                    type="number",
                    default=defaults.get(input_id, ""),
                    required=True,
                )
            )
        return questions

    def _requirement_needs_calculation_inputs(self, requirement: SupportRequirement) -> bool:
        value = requirement.value.strip().lower()
        if value in {"tbd", "not specified"}:
            return True
        return "starter value selected" in requirement.placement_note.lower()

    def _calculation_defaults(self, extraction: ReferenceCircuitExtraction) -> dict[str, str]:
        text = "\n".join([*extraction.extraction_notes, *(chunk.text for chunk in extraction.source_chunks)])
        defaults: dict[str, str] = {}
        requested_vin, requested_vout = self._requested_voltage_pair(text)
        if requested_vin:
            defaults["calc_input_voltage_v"] = self._fmt_number(requested_vin)
        if requested_vout:
            defaults["calc_output_voltage_v"] = self._fmt_number(requested_vout)

        output_current = self._extract_output_current(text)
        if output_current:
            defaults["calc_output_current_a"] = self._fmt_number(output_current)

        frequency_khz = self._extract_frequency_khz(text)
        if frequency_khz:
            defaults["calc_switching_frequency_khz"] = self._fmt_number(frequency_khz)

        reference_voltage = self._extract_reference_voltage(text)
        if reference_voltage:
            defaults["calc_feedback_reference_voltage_v"] = self._fmt_number(reference_voltage)

        defaults.setdefault("calc_inductor_ripple_percent", "30")
        defaults.setdefault("calc_feedback_lower_resistance_kohm", "100")
        defaults.setdefault("calc_gain_reference_resistance_kohm", "10")
        return defaults

    def _resolve_calculated_requirements(
        self,
        extraction: ReferenceCircuitExtraction,
        answers: dict[str, str],
    ) -> ReferenceCircuitExtraction:
        answers = {
            **self._calculation_defaults(extraction),
            **answers,
        }
        resolved: list[SupportRequirement] = []
        notes = list(extraction.extraction_notes)
        for requirement in extraction.support_requirements:
            calculated_value = self._calculated_requirement_value(requirement, answers)
            if not calculated_value:
                resolved.append(requirement)
                continue
            resolved.append(
                requirement.model_copy(
                    update={
                        "value": calculated_value,
                        "placement_note": self._calculated_placement_note(requirement, calculated_value),
                    }
                )
            )
            notes.append(
                f"Calculated {requirement.purpose} as {calculated_value} using {requirement.calculation_formula}."
            )
        return extraction.model_copy(
            update={
                "support_requirements": resolved,
                "extraction_notes": list(dict.fromkeys(notes)),
            }
        )

    def _calculated_requirement_value(
        self,
        requirement: SupportRequirement,
        answers: dict[str, str],
    ) -> str:
        role = requirement.calculation_role
        if not role:
            return ""
        if role == "buck_output_inductor":
            return self._calculate_buck_inductor_value(answers)
        if role == "feedback_divider_upper":
            return self._calculate_feedback_upper_value(answers)
        if role == "feedback_divider_lower":
            lower = self._answer_float(answers, "calc_feedback_lower_resistance_kohm")
            return self._format_resistance_kohm(lower) if lower else ""
        if role == "non_inverting_gain_feedback":
            return self._calculate_non_inverting_feedback_value(answers)
        if role == "non_inverting_gain_ground":
            lower = self._answer_float(answers, "calc_gain_reference_resistance_kohm")
            return self._format_resistance_kohm(lower) if lower else ""
        if role == "inverting_gain_feedback":
            return self._calculate_inverting_feedback_value(answers)
        if role == "inverting_gain_input":
            lower = self._answer_float(answers, "calc_gain_reference_resistance_kohm")
            return self._format_resistance_kohm(lower) if lower else ""
        return ""

    def _calculate_buck_inductor_value(self, answers: dict[str, str]) -> str:
        vin = self._answer_float(answers, "calc_input_voltage_v")
        vout = self._answer_float(answers, "calc_output_voltage_v")
        iout = self._answer_float(answers, "calc_output_current_a")
        frequency_khz = self._answer_float(answers, "calc_switching_frequency_khz")
        ripple_percent = self._answer_float(answers, "calc_inductor_ripple_percent")
        if not all([vin, vout, iout, frequency_khz, ripple_percent]):
            return ""
        if vin <= vout or iout <= 0 or frequency_khz <= 0 or ripple_percent <= 0:
            return ""
        ripple_current = iout * ripple_percent / 100.0
        inductance_h = (vout * (vin - vout)) / (vin * frequency_khz * 1000.0 * ripple_current)
        return self._format_inductance_h(inductance_h)

    def _calculate_feedback_upper_value(self, answers: dict[str, str]) -> str:
        vout = self._answer_float(answers, "calc_output_voltage_v")
        vref = self._answer_float(answers, "calc_feedback_reference_voltage_v")
        lower_kohm = self._answer_float(answers, "calc_feedback_lower_resistance_kohm")
        if not all([vout, vref, lower_kohm]):
            return ""
        if vout <= vref or vref <= 0 or lower_kohm <= 0:
            return ""
        return self._format_resistance_kohm(lower_kohm * (vout / vref - 1.0))

    def _calculate_non_inverting_feedback_value(self, answers: dict[str, str]) -> str:
        gain = self._answer_float(answers, "calc_voltage_gain")
        lower_kohm = self._answer_float(answers, "calc_gain_reference_resistance_kohm")
        if not all([gain, lower_kohm]) or gain <= 1 or lower_kohm <= 0:
            return ""
        return self._format_resistance_kohm(lower_kohm * (gain - 1.0))

    def _calculate_inverting_feedback_value(self, answers: dict[str, str]) -> str:
        gain = self._answer_float(answers, "calc_voltage_gain")
        input_kohm = self._answer_float(answers, "calc_gain_reference_resistance_kohm")
        if not all([gain, input_kohm]) or gain <= 0 or input_kohm <= 0:
            return ""
        return self._format_resistance_kohm(input_kohm * gain)

    def _calculated_placement_note(self, requirement: SupportRequirement, value: str) -> str:
        base = requirement.placement_note or "Review calculated value against the datasheet."
        return f"{base} Calculated value: {value}; verify voltage, current, tolerance, and thermal limits."

    def _answer_float(self, answers: dict[str, str], key: str) -> float | None:
        raw = str(answers.get(key, "")).strip()
        if not raw:
            return None
        match = re.search(r"-?\d+(?:[.,]\d+)?", raw)
        if not match:
            return None
        try:
            return float(match.group(0).replace(",", "."))
        except ValueError:
            return None

    def _format_inductance_h(self, value_h: float) -> str:
        if value_h <= 0 or not math.isfinite(value_h):
            return ""
        value_uh = value_h * 1_000_000.0
        if value_uh >= 1000:
            return f"{self._fmt_number(value_uh / 1000.0)} mH"
        if value_uh >= 1:
            return f"{self._fmt_number(value_uh)} uH"
        return f"{self._fmt_number(value_uh * 1000.0)} nH"

    def _format_resistance_kohm(self, value_kohm: float | None) -> str:
        if value_kohm is None or value_kohm <= 0 or not math.isfinite(value_kohm):
            return ""
        if value_kohm >= 1000:
            return f"{self._fmt_number(value_kohm / 1000.0)} MOhm"
        if value_kohm >= 1:
            return f"{self._fmt_number(value_kohm)} kOhm"
        return f"{self._fmt_number(value_kohm * 1000.0)} Ohm"

    def _fmt_number(self, value: float) -> str:
        if abs(value) >= 100:
            return f"{value:.0f}"
        if abs(value) >= 10:
            return f"{value:.1f}".rstrip("0").rstrip(".")
        if abs(value) < 1:
            return f"{value:.3f}".rstrip("0").rstrip(".")
        return f"{value:.2f}".rstrip("0").rstrip(".")

    def _requested_voltage_pair(self, text: str) -> tuple[float | None, float | None]:
        match = re.search(
            r"\b(\d+(?:[.,]\d+)?)\s*V\s*(?:to|->|→|-)\s*(\d+(?:[.,]\d+)?)\s*V\b",
            text,
            re.I,
        )
        if not match:
            return None, None
        return float(match.group(1).replace(",", ".")), float(match.group(2).replace(",", "."))

    def _extract_frequency_khz(self, text: str) -> float | None:
        match = re.search(
            r"(?:switching\s+frequency|f\s*sw|fsw)[^\d]{0,24}(\d+(?:[.,]\d+)?)\s*(MHz|kHz|Hz)",
            text,
            re.I,
        )
        if not match:
            return None
        value = float(match.group(1).replace(",", "."))
        unit = match.group(2).lower()
        if unit == "mhz":
            return value * 1000.0
        if unit == "hz":
            return value / 1000.0
        return value

    def _extract_output_current(self, text: str) -> float | None:
        match = re.search(r"(?:output\s+current|load\s+current)[^\d]{0,24}(\d+(?:[.,]\d+)?)\s*(A|mA)", text, re.I)
        if not match:
            return None
        value = float(match.group(1).replace(",", "."))
        return value / 1000.0 if match.group(2).lower() == "ma" else value

    def _extract_reference_voltage(self, text: str) -> float | None:
        match = re.search(
            r"(?:feedback\s+reference|reference\s+voltage|v\s*ref|vref)[^\d]{0,24}(\d+(?:[.,]\d+)?)\s*V",
            text,
            re.I,
        )
        if not match:
            return None
        return float(match.group(1).replace(",", "."))

    def _recipe_review_question(self, manufacturer: str, part: str) -> MissingQuestion:
        return MissingQuestion(
            id="recipe_review_confirmed",
            question=(
                f"{manufacturer} {part} was loaded from saved or extracted datasheet/reference sources. "
                "Confirm that Trace Labs should generate a reviewable KiCad block from this cached circuit."
            ),
            options=[
                Option(label="Confirm cached circuit", value="confirm"),
                Option(label="Cancel", value="cancel"),
            ],
            default="cancel",
        )

    def _symbol_for_support(self, component_type: str) -> str:
        lowered = component_type.lower()
        if "cap" in lowered:
            return "Device:C"
        if "diode" in lowered or lowered == "d":
            return "Device:D"
        if "inductor" in lowered:
            return "Device:L"
        if "res" in lowered or "pull" in lowered:
            return "Device:R"
        return "Device:R"

    def _footprint_for_support(self, component_type: str) -> str:
        lowered = component_type.lower()
        if "cap" in lowered:
            return "Capacitor_SMD:C_0603_1608Metric"
        if "diode" in lowered or lowered == "d":
            return "Diode_SMD:D_SOD-123"
        if "inductor" in lowered:
            return "Inductor_SMD:L_4.0x4.0mm"
        return "Resistor_SMD:R_0603_1608Metric"


def default_project_context() -> ProjectContext:
    return ProjectContext()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "ai_proposed_recipe"


def _library_safe(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_")
    return safe or "DraftPart"
