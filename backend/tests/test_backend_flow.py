import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.ai_service import TraceLabsAIService
from backend.app.bridge_ops import BridgeService
from backend.app.component_extraction import ComponentExtractionService
from backend.app.library_acquisition import DownloadedLibraryAssets, DownloadedSource, EasyEDALCSCProvider
from backend.app.library_assets import DraftLibraryAssets
from backend.app.kicad_writer import KiCadWriter
from backend.app.main import (
    _datasheet_assistant_message,
    _short_chat_text,
    ai_service,
    app,
    extraction_service,
    generator,
    writer,
)
from backend.app.models import (
    AnswerQuestionsRequest,
    BridgeLinkRequest,
    CircuitBlock,
    CircuitNet,
    DatasheetCandidate,
    DatasheetSource,
    DatasheetSearchResponse,
    PinDefinition,
    PricingPreview,
    ReferenceCircuitExtraction,
    SourceChunk,
    SupportComponent,
    SupportRequirement,
    UsageEventRequest,
)
from backend.app.pricing import AccountBillingService


client = TestClient(app)
ai_service.api_key = ""
ai_service.live_datasheet_search_enabled = False
ai_service.search_cache = None
extraction_service.extraction_cache = None
generator.loader.use_saved_drafts = False
writer.draft_library_assets.acquisition_service.enabled = False


def extracted_test_block(
    part_number: str = "VL53L1X",
    manufacturer: str = "STMicroelectronics",
    supplier: str = "",
    supplier_part_number: str = "",
    supplier_url: str = "",
) -> CircuitBlock:
    extraction = ReferenceCircuitExtraction(
        part_number=part_number,
        manufacturer=manufacturer,
        package="QFN",
        supply_range="2.8 V to 3.3 V",
        interface="I2C",
        pins=[
            PinDefinition(
                number="1",
                name="VDD",
                electrical_type="power_in",
                net_name="+3V3",
                source_citations=["S1P1C1"],
            ),
            PinDefinition(
                number="2",
                name="GND",
                electrical_type="power_in",
                net_name="GND",
                source_citations=["S1P1C1"],
            ),
            PinDefinition(
                number="3",
                name="SDA",
                electrical_type="bidirectional",
                net_name="SDA",
                source_citations=["S1P1C1"],
            ),
            PinDefinition(
                number="4",
                name="SCL",
                electrical_type="input",
                net_name="SCL",
                source_citations=["S1P1C1"],
            ),
        ],
        support_requirements=[
            SupportRequirement(
                reference_prefix="C",
                type="capacitor",
                value="100 nF",
                purpose="supply decoupling",
                connects=["+3V3", "GND"],
                footprint="Capacitor_SMD:C_0603_1608Metric",
                source_citations=["S1P1C1"],
            )
        ],
        nets=[
            CircuitNet(name="+3V3", role="power", external=True, connected_pins=["VDD"]),
            CircuitNet(name="GND", role="ground", external=True, connected_pins=["GND"]),
            CircuitNet(name="SDA", role="interface", external=True, connected_pins=["SDA"]),
            CircuitNet(name="SCL", role="interface", external=True, connected_pins=["SCL"]),
        ],
        source_chunks=[
            SourceChunk(
                chunk_id="S1P1C1",
                source_url="https://example.com/datasheet.pdf",
                title=f"{part_number} datasheet",
                page=1,
                text="Pin table and typical application circuit.",
            )
        ],
        source_urls=["https://example.com/datasheet.pdf"],
        confidence="high",
    )
    block = generator.ai_extracted_draft(
        extraction,
        supplier=supplier,
        supplier_part_number=supplier_part_number,
        supplier_url=supplier_url,
    )
    block.status = "final"
    block.missing_questions = []
    block.recipe_review_confirmed = True
    block.selected_options = {"recipe_review_confirmed": "confirm"}
    return block


def test_bme280_flow_exports_files():
    chat = client.post("/chat", json={"message": "Can you add a BME280 temperature sensor?"})
    assert chat.status_code == 200
    draft = chat.json()["draft_block"]
    assert len(chat.json()["missing_questions"]) == 5
    assert chat.json()["missing_questions"][-1]["id"] == "pullup_value"
    assert chat.json()["missing_questions"][-1]["depends_on"] == {"pullups": "add"}

    generate = client.post("/generate", json={"prompt": "temperature sensor", "known_values": {}})
    assert generate.status_code == 200
    assert generate.json()["status"] == "awaiting_answers"

    answers = {
        "logic_voltage": "3.3V",
        "interface_mode": "I2C",
        "i2c_address": "0x76",
        "pullups": "add",
        "pullup_value": "4.7 kOhm",
    }
    final = client.post("/answer-questions", json={"answers": answers, "draft_block": draft})
    assert final.status_code == 200
    block = final.json()
    assert block["status"] == "final"
    assert block["main_component"]["symbol"] == "TraceLabs_BME280:BME280"
    assert block["main_component"]["footprint"] == "TraceLabs_BME280:TraceLabs_BME280_LGA8_2.5x2.5mm_P0.65mm"
    assert block["main_component"]["footprint_confidence"] == "needs_review"
    resistors = [component for component in block["support_components"] if component["symbol"] == "Device:R"]
    assert [component["purpose"] for component in resistors] == ["I2C SDA pull-up", "I2C SCL pull-up"]

    export = client.post("/export", json={"block": block})
    assert export.status_code == 200
    exported = export.json()
    files = exported["files"]
    assert Path(files["block.json"]).exists()
    assert Path(files["bme280_i2c.kicad_sch"]).exists()
    schematic = Path(files["bme280_i2c.kicad_sch"]).read_text(encoding="utf-8")
    assert "TraceLabs_BME280:BME280" in schematic
    assert Path(files["TraceLabs_BME280.kicad_sym"]).exists()
    assert Path(files["TraceLabs_BME280_LGA8_2.5x2.5mm_P0.65mm.kicad_mod"]).exists()
    footprint_asset = exported["block"]["main_component"]["footprint_asset"]
    assert footprint_asset["footprint_id"] == "TraceLabs_BME280:TraceLabs_BME280_LGA8_2.5x2.5mm_P0.65mm"
    assert footprint_asset["source_kind"] == "bundled_footprint"
    assert "(pad " in footprint_asset["kicad_mod"]
    assert "Device:R" in schematic
    assert schematic.count('(symbol (lib_id "Device:R")') == 2
    assert "0 Ohm / strap" not in schematic
    assert "Device:C" in schematic
    assert "hierarchical_label" in schematic
    assert '(hierarchical_label "I2C1_SCL" (shape input) (at 121.92 73.66 0)' in schematic
    assert '(hierarchical_label "I2C1_SDA" (shape bidirectional) (at 121.92 78.74 0)' in schematic
    assert '(hierarchical_label "I2C1_SCL" (shape input) (at 177.8 73.66 0)' not in schematic


def test_bme280_can_leave_dependent_pullup_value_unspecified():
    chat = client.post("/chat", json={"message": "Can you add a BME280 temperature sensor?"})
    draft = chat.json()["draft_block"]
    final = client.post(
        "/answer-questions",
        json={
            "answers": {
                "logic_voltage": "3.3V",
                "interface_mode": "I2C",
                "i2c_address": "0x76",
                "pullups": "add",
                "pullup_value": "unspecified",
            },
            "draft_block": draft,
        },
    )
    assert final.status_code == 200
    block = final.json()
    pullups = [component for component in block["support_components"] if "pull-up" in component["purpose"]]
    assert pullups
    assert all(component["value"] == "TBD" for component in pullups)
    assert any("without a numeric value" in warning["message"] for warning in block["validation_warnings"])


def test_extracted_tbd_support_values_get_reviewable_starters():
    extraction = ReferenceCircuitExtraction(
        part_number="SENSOR123",
        manufacturer="Fixture Semiconductor",
        package="QFN",
        interface="I2C",
        pins=[
            PinDefinition(number="1", name="VDD", net_name="+3V3", source_citations=["S1P1C1"]),
            PinDefinition(number="2", name="GND", net_name="GND", source_citations=["S1P1C1"]),
            PinDefinition(number="3", name="SDA", net_name="SDA", source_citations=["S1P1C1"]),
            PinDefinition(number="4", name="SCL", net_name="SCL", source_citations=["S1P1C1"]),
        ],
        support_requirements=[
            SupportRequirement(
                reference_prefix="R",
                type="resistor",
                value="TBD",
                purpose="I2C SDA pull-up",
                connects=["SDA", "+3V3"],
                source_citations=["S1P1C1"],
            )
        ],
        source_chunks=[
            SourceChunk(
                chunk_id="S1P1C1",
                source_url="https://example.com/sensor123.pdf",
                title="Sensor fixture",
                text="Pin table and I2C pull-up reference.",
            )
        ],
    )

    draft = generator.ai_extracted_draft(extraction)

    assert draft.support_components[0].value == "4.7 kOhm"
    assert draft.reference_extraction is not None
    assert draft.reference_extraction.support_requirements[0].value == "4.7 kOhm"
    assert "Starter value selected" in draft.reference_extraction.support_requirements[0].placement_note


def test_extracted_diode_support_uses_diode_defaults_and_exports(tmp_path: Path):
    extraction = ReferenceCircuitExtraction(
        part_number="CLAMP123",
        manufacturer="Fixture Semiconductor",
        package="QFN",
        interface="I2C",
        pins=[
            PinDefinition(number="1", name="VDD", net_name="+3V3", source_citations=["S1P1C1"]),
            PinDefinition(number="2", name="GND", net_name="GND", source_citations=["S1P1C1"]),
            PinDefinition(number="3", name="SDA", net_name="SDA", source_citations=["S1P1C1"]),
            PinDefinition(number="4", name="SCL", net_name="SCL", source_citations=["S1P1C1"]),
        ],
        support_requirements=[
            SupportRequirement(
                reference_prefix="D",
                type="diode",
                value="1N4148W",
                purpose="SDA clamp diode",
                connects=["SDA", "GND"],
                source_citations=["S1P1C1"],
            )
        ],
        nets=[
            CircuitNet(name="+3V3", role="power", external=True, connected_pins=["VDD"]),
            CircuitNet(name="GND", role="ground", external=True, connected_pins=["GND"]),
            CircuitNet(name="SDA", role="interface", external=True, connected_pins=["SDA"]),
            CircuitNet(name="SCL", role="interface", external=True, connected_pins=["SCL"]),
        ],
        source_chunks=[
            SourceChunk(
                chunk_id="S1P1C1",
                source_url="https://example.com/clamp123.pdf",
                title="Clamp fixture",
                text="Typical application circuit shows D1 as an SDA clamp diode to GND.",
            )
        ],
        source_urls=["https://example.com/clamp123.pdf"],
        confidence="high",
    )

    block = generator.ai_extracted_draft(extraction)
    diode = block.support_components[0]
    assert diode.reference == "D?"
    assert diode.symbol == "Device:D"
    assert diode.footprint == "Diode_SMD:D_SOD-123"

    class FakeAcquisitionService:
        def acquire_for_block(self, block, *, library_name, symbol_name, footprint_name, footprint_id):
            return DownloadedLibraryAssets(
                footprint_text=f"""(footprint "{footprint_name}"
  (version 20240108)
  (generator "Trace Labs")
  (property "Reference" "U?" (at 0 -1 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
)""",
                footprint_name=footprint_name,
            )

    block.status = "final"
    block.missing_questions = []
    block.recipe_review_confirmed = True
    local_writer = KiCadWriter(tmp_path / "generated_blocks")
    local_writer.draft_library_assets = DraftLibraryAssets(FakeAcquisitionService())
    _, files = local_writer.export(block, PricingPreview())
    schematic_path = next(Path(path) for name, path in files.items() if name.endswith(".kicad_sch"))
    schematic = schematic_path.read_text(encoding="utf-8")

    assert '(symbol "Device:D"' in schematic
    assert '(symbol (lib_id "Device:D")' in schematic
    assert '(property "Reference" "D1"' in schematic
    assert "1N4148W" in schematic


def test_bme280_skips_pullups_without_adding_address_strap_resistors():
    chat = client.post("/chat", json={"message": "Can you add a BME280 temperature sensor?"})
    draft = chat.json()["draft_block"]
    final = client.post(
        "/answer-questions",
        json={
            "answers": {
                "logic_voltage": "3.3V",
                "interface_mode": "I2C",
                "i2c_address": "0x76",
                "pullups": "skip",
            },
            "draft_block": draft,
        },
    )
    assert final.status_code == 200
    block = final.json()
    assert [component for component in block["support_components"] if component["symbol"] == "Device:R"] == []

    export = client.post("/export", json={"block": block})
    assert export.status_code == 200
    schematic = Path(export.json()["files"]["bme280_i2c.kicad_sch"]).read_text(encoding="utf-8")
    assert '(symbol (lib_id "Device:R")' not in schematic
    assert 'label "GND"' in schematic
    assert 'label "+3V3"' in schematic


def test_extracted_pullup_resistors_extend_signal_and_power_rails(tmp_path: Path):
    class FakeAcquisitionService:
        def acquire_for_block(self, block, *, library_name, symbol_name, footprint_name, footprint_id):
            return DownloadedLibraryAssets(
                footprint_text=f"""(footprint "{footprint_name}"
  (version 20240108)
  (generator "Trace Labs")
  (property "Reference" "U?" (at 0 -1 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
)""",
                footprint_name=footprint_name,
            )

    block = extracted_test_block()
    block.support_components = [
        *block.support_components,
        *[
            SupportComponent(
                reference="R?",
                type="resistor",
                value="4.7 kOhm",
                purpose=f"I2C pull-up {index + 1}",
                symbol="Device:R",
                footprint="Resistor_SMD:R_0603_1608Metric",
                connects=["+3V3", "SDA" if index % 2 == 0 else "SCL"],
                assignment_reason="Regression fixture for spread-out extracted pull-ups.",
                source_citations=["S1P1C1"],
            )
            for index in range(8)
        ],
    ]

    local_writer = KiCadWriter(tmp_path / "generated_blocks")
    local_writer.draft_library_assets = DraftLibraryAssets(FakeAcquisitionService())
    _, files = local_writer.export(block, PricingPreview())
    schematic_path = next(Path(path) for name, path in files.items() if name.endswith(".kicad_sch"))
    schematic = schematic_path.read_text(encoding="utf-8")

    assert schematic.count('(symbol (lib_id "Device:R")') == 8
    assert '(symbol (lib_id "Device:R") (at 134.62 74.93 0)' in schematic
    assert '(symbol (lib_id "Device:R") (at 187.96 77.47 0)' in schematic
    assert "(junction (at 134.62 35.56)" in schematic
    assert "(junction (at 134.62 78.74)" in schematic
    assert '(symbol (lib_id "Device:R") (at 195.58' not in schematic


def test_extracted_series_resistors_follow_horizontal_pin_wires(tmp_path: Path):
    class FakeAcquisitionService:
        def acquire_for_block(self, block, *, library_name, symbol_name, footprint_name, footprint_id):
            return DownloadedLibraryAssets(
                footprint_text=f"""(footprint "{footprint_name}"
  (version 20240108)
  (generator "Trace Labs")
  (property "Reference" "U?" (at 0 -1 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
)""",
                footprint_name=footprint_name,
            )

    block = extracted_test_block()
    block.support_components = [
        *block.support_components,
        SupportComponent(
            reference="R?",
            type="resistor",
            value="33 Ohm",
            purpose="SDA series resistor",
            symbol="Device:R",
            footprint="Resistor_SMD:R_0603_1608Metric",
            connects=["SDA", "HOST_SDA"],
            assignment_reason="Regression fixture for horizontal series resistor placement.",
            source_citations=["S1P1C1"],
        ),
    ]

    local_writer = KiCadWriter(tmp_path / "generated_blocks")
    local_writer.draft_library_assets = DraftLibraryAssets(FakeAcquisitionService())
    _, files = local_writer.export(block, PricingPreview())
    schematic_path = next(Path(path) for name, path in files.items() if name.endswith(".kicad_sch"))
    schematic = schematic_path.read_text(encoding="utf-8")

    assert '(symbol (lib_id "Device:R") (at 134.62 78.74 90)' in schematic
    assert "(xy 114.3 78.74) (xy 130.81 78.74)" in schematic
    assert "(xy 138.43 78.74) (xy 148.59 78.74)" in schematic
    assert '(label "HOST_SDA" (at 148.59 78.74 0)' in schematic


def test_extracted_inline_inductors_rotate_horizontally_in_kicad(tmp_path: Path):
    class FakeAcquisitionService:
        def acquire_for_block(self, block, *, library_name, symbol_name, footprint_name, footprint_id):
            return DownloadedLibraryAssets(
                footprint_text=f"""(footprint "{footprint_name}"
  (version 20240108)
  (generator "Trace Labs")
  (property "Reference" "U?" (at 0 -1 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
)""",
                footprint_name=footprint_name,
            )

    block = extracted_test_block()
    block.support_components = [
        *block.support_components,
        SupportComponent(
            reference="L?",
            type="buck output inductor",
            value="4.7 uH",
            purpose="buck output inductor",
            symbol="Device:R",
            footprint="Inductor_SMD:L_6.3x6.3mm",
            connects=["SDA", "HOST_SDA"],
            assignment_reason="Regression fixture for horizontal inline inductor placement.",
            source_citations=["S1P1C1"],
        ),
    ]

    local_writer = KiCadWriter(tmp_path / "generated_blocks")
    local_writer.draft_library_assets = DraftLibraryAssets(FakeAcquisitionService())
    _, files = local_writer.export(block, PricingPreview())
    schematic_path = next(Path(path) for name, path in files.items() if name.endswith(".kicad_sch"))
    schematic = schematic_path.read_text(encoding="utf-8")

    assert '(symbol (lib_id "Device:L") (at 134.62 78.74 90)' in schematic
    assert '(symbol (lib_id "Device:R") (at 134.62 78.74' not in schematic
    assert "(xy 114.3 78.74) (xy 130.81 78.74)" in schematic
    assert "(xy 138.43 78.74) (xy 148.59 78.74)" in schematic


def test_generic_temperature_sensor_request_clarifies_before_recommending_parts():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post("/chat", json={"message": "I need a temperature sensor"})
    assert chat.status_code == 200
    body = chat.json()

    assert body["draft_block"] is None
    assert body["datasheet_results"] is None
    assert [question["id"] for question in body["missing_questions"]] == [
        "clarify_application",
        "clarify_interface_preference",
        "clarify_supply_voltage_v",
    ]

    clarified = client.post(
        "/chat",
        json={
            "message": "I need a temperature sensor",
            "answers": {
                "clarify_application": "weather station",
                "clarify_interface_preference": "I2C",
                "clarify_supply_voltage_v": "3.3V",
            },
        },
    )
    assert clarified.status_code == 200
    body = clarified.json()
    assert body["missing_questions"][0]["id"] == "part_choice"
    assert body["missing_questions"][0]["options"][0]["value"] == "bme280_i2c"
    assert body["datasheet_results"]["candidates"][0]["part_number"] == "BME280"
    assert "Application or use case: weather station." in body["datasheet_results"]["query"]

    selected = client.post("/chat", json={"message": "Use BME280 for this block"})
    assert selected.status_code == 200
    assert selected.json()["draft_block"]["block_slug"] == "bme280_i2c"


def test_converter_category_request_asks_operating_requirements_before_search():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post("/chat", json={"message": "I want to add a buck converter"})
    assert chat.status_code == 200
    body = chat.json()

    assert body["draft_block"] is None
    assert body["extraction_job"] is None
    assert body["datasheet_results"] is None
    assert "Before I recommend converter parts" in body["assistant_message"]
    assert [question["id"] for question in body["missing_questions"]] == [
        "calc_input_voltage_v",
        "calc_output_voltage_v",
        "calc_output_current_a",
    ]
    assert {question["type"] for question in body["missing_questions"]} == {"number"}


def test_converter_category_request_uses_supplied_voltage_before_search():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post("/chat", json={"message": "I want to add a 12V to 5V buck converter"})
    assert chat.status_code == 200
    body = chat.json()

    assert [question["id"] for question in body["missing_questions"]] == ["calc_output_current_a"]
    assert body["datasheet_results"] is None


def test_converter_category_answers_resume_part_search():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post(
        "/chat",
        json={
            "message": "I want to add a buck converter",
            "answers": {
                "calc_input_voltage_v": "12",
                "calc_output_voltage_v": "5",
                "calc_output_current_a": "2",
            },
        },
    )
    assert chat.status_code == 200
    body = chat.json()

    assert body["datasheet_results"] is not None
    assert "Requested conversion: 12V to 5V." in body["datasheet_results"]["query"]
    assert "Requested output current: 2 A." in body["datasheet_results"]["query"]
    assert "calc_input_voltage_v" not in {question["id"] for question in body["missing_questions"]}


def test_obvious_part_search_does_not_need_openai_intent_classifier(monkeypatch):
    service = TraceLabsAIService()
    service.api_key = "sk-test"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("intent classifier should not be called for obvious part searches")

    monkeypatch.setattr(service, "_call_openai", fail_if_called)
    decision = service.decide(
        "I want to add a time of flight sensor for an ESP32 project, what are my options?",
        available_recipes=generator.loader.summaries(),
    )

    assert decision.action == "suggest_parts"
    assert decision.context_part_numbers == ["ESP32"]


def test_extracted_recipe_requires_confirmation_then_exports_cited_schematic(tmp_path: Path):
    ai_service.live_datasheet_search_enabled = False
    original_recipes_dir = generator.loader.recipes_dir
    generator.loader.recipes_dir = tmp_path / "recipes"
    generator.loader.recipes_dir.mkdir()
    (generator.loader.recipes_dir / "bme280_i2c.json").write_text(
        original_recipes_dir.joinpath("bme280_i2c.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    source_path = tmp_path / "vl53_fixture.txt"
    source_path.write_text(
        "VL53L1X reference design. Pin 1 AVDD supply. Pin 2 GND ground. "
        "Pin 3 SDA I2C data. Pin 4 SCL I2C clock. Pin 5 XSHUT shutdown input. "
        "Pin 6 GPIO1 interrupt output. Typical application schematic: place 100 nF "
        "capacitor between AVDD and GND. I2C pull-up resistors on SDA and SCL are required.",
        encoding="utf-8",
    )
    candidate = DatasheetCandidate(
        part_number="VL53L1X",
        manufacturer="STMicroelectronics",
        description="ToF sensor",
        supplier="LCSC",
        supplier_part_number="C2924337",
        supplier_url="https://www.lcsc.com/product-detail/C2924337.html",
        confidence="high",
        datasheet_sources=[
            DatasheetSource(
                title="VL53L1X fixture datasheet",
                source_type="manufacturer_datasheet",
                url=str(source_path),
                confidence="official",
                notes="test fixture",
            )
        ],
    )

    class FakeAcquisitionService:
        def acquire_for_block(self, block, *, library_name, symbol_name, footprint_name, footprint_id):
            return DownloadedLibraryAssets(
                footprint_text=f"""(footprint "{footprint_name}"
  (version 20240108)
  (generator "Trace Labs")
  (property "Reference" "U?" (at 0 -1 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (property "Value" "{block.main_component.value}" (at 0 1 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
)""",
                footprint_name="TraceLabs_VL53L1X_LCSC_C2924337",
                sources=[
                    DownloadedSource(
                        kind="supplier_footprint",
                        project="LCSC/EasyEDA via easyeda2kicad",
                        path="C2924337",
                        url="https://www.lcsc.com/product-detail/C2924337.html",
                    )
                ],
            )

    try:
        extraction_service = ComponentExtractionService(ai_service)
        job = extraction_service.start(candidate, run_inline=True)
        assert job.status == "ready"
        assert job.extraction is not None
        assert [pin.name for pin in job.extraction.pins[:4]] == ["AVDD", "GND", "SDA", "SCL"]
        draft = generator.ai_extracted_draft(
            job.extraction,
            supplier=candidate.supplier,
            supplier_part_number=candidate.supplier_part_number,
            supplier_url=candidate.supplier_url,
        ).model_dump()
        assert draft["recipe_source"] == "ai_proposed"
        assert draft["extraction_status"] == "ready"
        assert draft["missing_questions"][0]["id"] == "recipe_review_confirmed"

        rejected = client.post(
            "/answer-questions",
            json={"answers": {"recipe_review_confirmed": "cancel"}, "draft_block": draft},
        )
        assert rejected.status_code == 400

        final = client.post(
            "/answer-questions",
            json={
                "answers": {
                    "recipe_review_confirmed": "confirm",
                },
                "draft_block": draft,
            },
        )
        assert final.status_code == 200
        block = final.json()
        assert block["recipe_source"] == "ai_proposed"
        assert block["extraction_status"] == "ready"
        assert block["recipe_review_confirmed"] is True
        assert block["recipe_saved_path"]
        assert Path(block["recipe_saved_path"]).exists()
        assert any(component["value"] == "100 nF" for component in block["support_components"])
        assert any("SDA" in component["connects"] for component in block["support_components"])
        assert block["main_component"]["symbol"].startswith("TraceLabs_VL53L1X:")

        local_writer = KiCadWriter(tmp_path / "generated_blocks")
        local_writer.draft_library_assets = DraftLibraryAssets(FakeAcquisitionService())
        _, files = local_writer.export(CircuitBlock.model_validate(block), PricingPreview())
        schematic_path = next(Path(path) for name, path in files.items() if name.endswith(".kicad_sch"))
        schematic = schematic_path.read_text(encoding="utf-8")
        assert "Generated from cited datasheet/reference extraction" in schematic
        assert '(label "+3V3"' in schematic
        assert '(label "SDA"' in schematic
        assert '(label "SCL"' in schematic
        assert "100 nF" in schematic
        assert "SIGNALS" not in schematic
        assert "_CONFIG" not in schematic

        project = tmp_path / "draft_project"
        project.mkdir()
        (project / "weather_station.kicad_pro").write_text("{}", encoding="utf-8")
        (project / "weather_station.kicad_sch").write_text(
            '(kicad_sch (version 20230121) (generator "Trace Labs")\n'
            '  (uuid "00000000-0000-0000-0000-000000000000")\n'
            ")\n",
            encoding="utf-8",
        )
        service = BridgeService(tmp_path / ".tracelabs_draft")
        link = service.link(BridgeLinkRequest(project_path=str(project), project_name="weather_station.kicad_pro"))
        imported = service.import_block(str(schematic_path.parent), link.link_id, import_mode="inline_main")
        assert imported.success is True
        assert (project / "tracelabs_libs" / "TraceLabs_VL53L1X.kicad_sym").exists()
        assert (project / "tracelabs_libs" / "TraceLabs_VL53L1X.pretty" / "TraceLabs_VL53L1X_LCSC_C2924337.kicad_mod").exists()
    finally:
        generator.loader.recipes_dir = original_recipes_dir


def test_draft_library_assets_can_use_downloaded_online_candidates(tmp_path: Path):
    class FakeAcquisitionService:
        def acquire_for_block(self, block, *, library_name, symbol_name, footprint_name, footprint_id):
            return DownloadedLibraryAssets(
                symbol_text=f"""    (symbol "{symbol_name}" (pin_names (offset 0.762)) (in_bom yes) (on_board yes)
      (property "Reference" "U" (at 0 -5.08 0) (effects (font (size 1.27 1.27))))
      (property "Value" "{block.main_component.value}" (at 0 5.08 0) (effects (font (size 1.27 1.27))))
      (property "Footprint" "{footprint_id}" (at 0 7.62 0) (effects (font (size 1.27 1.27)) hide))
    )""",
                footprint_text=f"""(footprint "{footprint_name}"
  (version 20240108)
  (generator "Trace Labs")
  (property "Reference" "U?" (at 0 -1 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (property "Value" "{block.main_component.value}" (at 0 1 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
)""",
                footprint_name="TraceLabs_VL53L1X_LCSC_C2924337",
                sources=[
                    DownloadedSource(
                        kind="supplier_footprint",
                        project="LCSC/EasyEDA via easyeda2kicad",
                        path="C2924337",
                        url="https://www.lcsc.com/datasheet/C2924337.pdf",
                    )
                ],
            )

    block = extracted_test_block(
        part_number="VL53L1X",
        manufacturer="STMicroelectronics",
    )
    assets = DraftLibraryAssets(FakeAcquisitionService())
    paths = assets.write_export_libraries(tmp_path, block)

    assert block.main_component.symbol_confidence == "datasheet_extracted_needs_review"
    assert block.main_component.footprint_confidence == "downloaded_needs_review"
    assert block.main_component.footprint == "TraceLabs_VL53L1X:TraceLabs_VL53L1X_LCSC_C2924337"
    assert block.main_component.footprint_asset is not None
    assert block.main_component.footprint_asset.footprint_id == "TraceLabs_VL53L1X:TraceLabs_VL53L1X_LCSC_C2924337"
    assert '(footprint "TraceLabs_VL53L1X_LCSC_C2924337"' in block.main_component.footprint_asset.kicad_mod
    assert block.main_component.supplier == "LCSC"
    assert block.main_component.supplier_part_number == "C2924337"
    assert paths.symbol_library.exists()
    assert paths.footprint_file.exists()
    assert paths.footprint_file.name == "TraceLabs_VL53L1X_LCSC_C2924337.kicad_mod"
    assert 'name "SDA"' in paths.symbol_library.read_text(encoding="utf-8")
    assert "C2924337" in paths.sources_file.read_text(encoding="utf-8")
    assert "TraceLabs_VL53L1X:VL53L1X" in assets.schematic_cached_symbol(block)


def test_draft_library_assets_attach_real_footprint_preview_asset(tmp_path: Path):
    class FakeAcquisitionService:
        def acquire_for_block(self, block, *, library_name, symbol_name, footprint_name, footprint_id):
            return DownloadedLibraryAssets(
                footprint_text=f"""(footprint "{footprint_name}"
  (version 20240108)
  (generator "Trace Labs")
  (fp_line (start -1 -1) (end 1 -1) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (pad "1" smd rect (at -0.7 0) (size 0.4 0.8) (layers "F.Cu" "F.Paste" "F.Mask"))
)""",
                footprint_name="TraceLabs_VL53L1X_LCSC_C2924337",
                sources=[
                    DownloadedSource(
                        kind="supplier_footprint",
                        project="LCSC/EasyEDA via easyeda2kicad",
                        path="C2924337",
                        url="https://www.lcsc.com/datasheet/C2924337.pdf",
                    )
                ],
            )

    block = extracted_test_block(
        part_number="VL53L1X",
        manufacturer="STMicroelectronics",
    )
    assets = DraftLibraryAssets(FakeAcquisitionService())
    asset = assets.attach_preview_footprint(block)

    assert asset is not None
    assert block.main_component.footprint_asset is not None
    assert block.main_component.footprint == "TraceLabs_VL53L1X:TraceLabs_VL53L1X_LCSC_C2924337"
    assert block.main_component.footprint_confidence == "downloaded_needs_review"
    assert '(pad "1" smd rect' in block.main_component.footprint_asset.kicad_mod
    assert block.main_component.footprint_asset.source_path == "C2924337"

    class FailingAcquisitionService:
        def acquire_for_block(self, block, *, library_name, symbol_name, footprint_name, footprint_id):
            raise AssertionError("export should reuse the attached footprint asset")

    export_assets = DraftLibraryAssets(FailingAcquisitionService())
    paths = export_assets.write_export_libraries(tmp_path, block, require_downloaded_footprint=True)
    assert paths.footprint_file.read_text(encoding="utf-8") == block.main_component.footprint_asset.kicad_mod


def test_exact_unknown_part_request_starts_extraction_instead_of_draft():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post("/chat", json={"message": "Can you add an MPU6050 IMU?"})
    assert chat.status_code == 200
    body = chat.json()
    assert body["draft_block"] is None
    assert body["missing_questions"] == []
    assert body["extraction_job"] is not None
    assert body["extraction_job"]["candidate"]["part_number"] == "MPU6050"
    assert body["datasheet_results"]["candidates"][0]["part_number"] == "MPU6050"


def test_component_extraction_follows_linked_reference_design(tmp_path: Path):
    datasheet = tmp_path / "datasheet.html"
    reference = tmp_path / "vl53_reference_design.txt"
    datasheet.write_text(
        '<html><body><a href="vl53_reference_design.txt">reference design schematic</a></body></html>',
        encoding="utf-8",
    )
    reference.write_text(
        "\n".join(
            [
                "Reference design schematic",
                "Pin 1 AVDD power supply",
                "Pin 2 GND ground",
                "Pin 3 SDA I2C data",
                "Pin 4 SCL I2C clock",
                "Place a 100 nF capacitor between AVDD and GND.",
                "I2C pull-up resistors may be required on SDA and SCL.",
            ]
        ),
        encoding="utf-8",
    )
    candidate = DatasheetCandidate(
        part_number="VL53L1X",
        manufacturer="STMicroelectronics",
        description="Time-of-flight sensor.",
        confidence="test",
        datasheet_sources=[
            DatasheetSource(
                title="VL53L1X datasheet",
                source_type="manufacturer_datasheet",
                url=datasheet.as_uri(),
                confidence="test",
            )
        ],
    )

    service = ComponentExtractionService(ai_service)
    job = service.start(candidate, run_inline=True)

    assert job.status == "ready"
    assert job.extraction is not None
    assert any(chunk.source_url.endswith("vl53_reference_design.txt") for chunk in job.extraction.source_chunks)
    assert {pin.name for pin in job.extraction.pins} >= {"AVDD", "GND", "SDA", "SCL"}
    assert any(requirement.value == "100 nF" for requirement in job.extraction.support_requirements)
    pullups = [
        requirement
        for requirement in job.extraction.support_requirements
        if "pull-up" in requirement.purpose
    ]
    assert pullups
    assert all(requirement.value == "4.7 kOhm" for requirement in pullups)


def test_component_extraction_parses_bme688_pin_table_without_unit_false_positives(
    monkeypatch,
    tmp_path: Path,
):
    source_path = tmp_path / "bme688_fixture.txt"
    source_path.write_text(
        "Technical data 2.1 uA at 1 Hz humidity and temperature 9 mA current. "
        "Table 26: Pin description Pin Name I/O type Description Connection SPI 4W SPI 3W I2C "
        "1 GND Supply Ground GND "
        "2 CSB In Chip select CSB CSB VDDIO "
        "3 SDI In/Out Serial data input SDI SDI/SDO SDA "
        "4 SCK In Serial clock input SCK SCK SCL "
        "5 SDO In/Out Serial data output SDO DNC GND for default address "
        "6 VDDIO Supply Digital / Interface supply VDDIO "
        "7 GND Supply Ground GND "
        "8 VDD Supply Analog supply VDD. "
        "Voltage at any interface pin -0.3 VDDIO + 0.3 V. "
        "For the I2C connection, it is recommended to use 100 nF for C 1 and C 2. "
        "The value for the pull-up resistors R 1 and R2 should be based on the bus load; "
        "a normal value is 4.7 kOhm.",
        encoding="utf-8",
    )
    candidate = DatasheetCandidate(
        part_number="BME688",
        manufacturer="Bosch Sensortec",
        description="Gas, pressure, humidity, and temperature sensor.",
        confidence="test",
        datasheet_sources=[
            DatasheetSource(
                title="BME688 fixture datasheet",
                source_type="manufacturer_datasheet",
                url=str(source_path),
                confidence="test",
            )
        ],
    )

    service = ComponentExtractionService(ai_service)
    updates = []
    original_update = service._update

    def record_update(job_id, status, progress, message):
        updates.append((status, message))
        original_update(job_id, status, progress, message)

    monkeypatch.setattr(service, "_update", record_update)
    job = service.start(candidate, run_inline=True)

    assert job.status == "ready"
    assert any(status == "sources_found" for status, _ in updates)
    assert any("Found readable datasheet/reference text" in message for _, message in updates)
    assert job.extraction is not None
    assert [(pin.number, pin.name, pin.net_name) for pin in job.extraction.pins] == [
        ("1", "GND", "GND"),
        ("2", "CSB", "+3V3"),
        ("3", "SDI", "SDA"),
        ("4", "SCK", "SCL"),
        ("5", "SDO", "GND"),
        ("6", "VDDIO", "+3V3"),
        ("7", "GND", "GND"),
        ("8", "VDD", "+3V3"),
    ]
    assert "HZ" not in {pin.name for pin in job.extraction.pins}
    assert "MA" not in {pin.name for pin in job.extraction.pins}
    assert [item.value for item in job.extraction.support_requirements].count("100 nF") == 2
    assert {tuple(item.connects) for item in job.extraction.support_requirements} >= {
        ("SDA", "+3V3"),
        ("SCL", "+3V3"),
    }


def test_component_extraction_pin_failure_says_datasheet_was_found(tmp_path: Path):
    source_path = tmp_path / "incomplete_fixture.txt"
    source_path.write_text(
        "Official datasheet text. Typical application recommends a 100 nF capacitor. "
        "Electrical characteristics are present, but this fixture has no pin table.",
        encoding="utf-8",
    )
    candidate = DatasheetCandidate(
        part_number="NO_PIN_TABLE",
        manufacturer="Fixture Semiconductor",
        description="Fixture part with incomplete source text.",
        confidence="test",
        datasheet_sources=[
            DatasheetSource(
                title="Incomplete fixture datasheet",
                source_type="manufacturer_datasheet",
                url=str(source_path),
                confidence="test",
            )
        ],
    )

    service = ComponentExtractionService(ai_service)
    job = service.start(candidate, run_inline=True)

    assert job.status == "failed"
    assert "found readable datasheet/reference text" in job.message
    assert "could not extract a complete cited pin map" in job.message
    assert "No cited pin map was extracted." in job.errors


def test_component_extraction_supply_failure_says_which_evidence_was_missing(tmp_path: Path):
    source_path = tmp_path / "missing_supply_fixture.txt"
    source_path.write_text(
        "Official datasheet text. Pin description table: pin 1 GND ground, "
        "pin 2 SDA serial data, pin 3 SCL serial clock. "
        "Typical application schematic recommends a 100 nF capacitor and "
        "4.7 kOhm pull-up resistors for SDA and SCL.",
        encoding="utf-8",
    )
    candidate = DatasheetCandidate(
        part_number="NO_SUPPLY_PIN",
        manufacturer="Fixture Semiconductor",
        description="Fixture part with a readable datasheet but no supply pin evidence.",
        confidence="test",
        datasheet_sources=[
            DatasheetSource(
                title="Missing supply fixture datasheet",
                source_type="manufacturer_datasheet",
                url=str(source_path),
                confidence="test",
            )
        ],
    )

    service = ComponentExtractionService(ai_service)
    job = service.start(candidate, run_inline=True)

    assert job.status == "failed"
    assert "found readable datasheet/reference text" in job.message
    assert "extracted circuit evidence was incomplete" in job.message
    assert "No supply pin was extracted." in job.message
    assert "No supply pin was extracted." in job.errors


def test_component_extraction_handles_buck_converter_simplified_schematic(tmp_path: Path):
    source_path = tmp_path / "tps54302_fixture.txt"
    source_path.write_text(
        "Texas Instruments TPS54302 datasheet. Simplified Schematic. "
        "VIN 3 connects to C_IN and the input supply. GND 1 connects to ground. "
        "EN 5 connects to enable. BOOT 6 connects to C_BOOT. "
        "SW 2 connects to L_O and the bootstrap capacitor. "
        "L_O connects from SW to VOUT. C_O connects from VOUT to GND. "
        "FB 4 connects to the feedback divider. R_FB1 connects VOUT to FB. "
        "R_FB2 connects FB to GND. The device is a buck step-down converter. "
        "The switching frequency is 500 kHz. The feedback reference voltage is 0.596 V.",
        encoding="utf-8",
    )
    candidate = DatasheetCandidate(
        part_number="TPS54302DDCR",
        manufacturer="Texas Instruments",
        description="3A synchronous buck converter.",
        confidence="test",
        extraction_notes=[
            "Requested conversion: 12V to 5V.",
            "Requested output current: 3 A.",
        ],
        datasheet_sources=[
            DatasheetSource(
                title="TPS54302 fixture datasheet",
                source_type="manufacturer_datasheet",
                url=str(source_path),
                confidence="test",
            )
        ],
    )

    service = ComponentExtractionService(ai_service)
    job = service.start(candidate, run_inline=True)

    assert job.status == "ready"
    assert job.extraction is not None
    assert {(pin.number, pin.name, pin.net_name) for pin in job.extraction.pins} >= {
        ("1", "GND", "GND"),
        ("2", "SW", "SW"),
        ("3", "VIN", "VIN"),
        ("4", "FB", "FB"),
        ("5", "EN", "EN"),
        ("6", "BOOT", "BOOT"),
    }
    support_by_purpose = {item.purpose: item for item in job.extraction.support_requirements}
    assert support_by_purpose["buck output inductor"].type == "inductor"
    assert support_by_purpose["buck output inductor"].calculation_role == "buck_output_inductor"
    assert support_by_purpose["buck output inductor"].connects == ["SW", "VOUT"]
    assert support_by_purpose["input bypass capacitor"].value == "10 uF"
    assert support_by_purpose["bootstrap capacitor"].connects == ["BOOT", "SW"]
    assert support_by_purpose["bootstrap capacitor"].value == "100 nF"
    assert support_by_purpose["buck output inductor"].value == "4.7 uH"
    assert support_by_purpose["output capacitor"].value == "22 uF"
    assert support_by_purpose["upper feedback divider resistor"].connects == ["VOUT", "FB"]
    assert support_by_purpose["lower feedback divider resistor"].connects == ["FB", "GND"]
    assert all(item.value != "TBD" for item in job.extraction.support_requirements)
    assert {net.name for net in job.extraction.nets} >= {"VIN", "VOUT", "SW", "FB", "BOOT", "EN", "GND"}

    draft = generator.ai_extracted_draft(job.extraction)
    question_defaults = {question.id: question.default for question in draft.missing_questions}
    assert question_defaults["calc_input_voltage_v"] == "12"
    assert question_defaults["calc_output_voltage_v"] == "5"
    assert question_defaults["calc_output_current_a"] == "3"
    assert question_defaults["calc_switching_frequency_khz"] == "500"
    assert question_defaults["calc_feedback_reference_voltage_v"] == "0.596"

    final = generator.finalise(
        AnswerQuestionsRequest(
            draft_block=draft,
            answers={
                "calc_input_voltage_v": "12",
                "calc_output_voltage_v": "5",
                "calc_output_current_a": "3",
                "calc_switching_frequency_khz": "500",
                "calc_inductor_ripple_percent": "30",
                "calc_feedback_reference_voltage_v": "0.596",
                "calc_feedback_lower_resistance_kohm": "100",
                "recipe_review_confirmed": "confirm",
            },
        )
    )
    final_supports = {item.purpose: item for item in final.support_components}
    assert final_supports["buck output inductor"].value == "6.48 uH"
    assert final_supports["upper feedback divider resistor"].value == "739 kOhm"
    assert final_supports["lower feedback divider resistor"].value == "100 kOhm"


def test_component_extraction_parses_regulator_pin_functions_table(tmp_path: Path):
    source_path = tmp_path / "lt8609s_fixture.txt"
    source_path.write_text(
        "Analog Devices LT8609S datasheet. Pin Functions. "
        "RUN 1 enable input. SYNC 2 synchronization input. RT 3 switching frequency resistor. "
        "VIN 4 input supply. SW 5 switch node. GND 6 ground. BST (Pin 7) bootstrap supply. "
        "FB 8 feedback input. BIAS 9 bias input. INTVCC 10 internal regulator output. "
        "Typical Application buck step-down regulator. CIN is the input capacitor from VIN to GND. "
        "CBOOT is the bootstrap capacitor from BST to SW. LO is the output inductor from SW to VOUT. "
        "CO is the output capacitor from VOUT to GND. RFB1 connects VOUT to FB. "
        "RFB2 connects FB to GND. Switching frequency is 700 kHz. "
        "Feedback reference voltage is 0.782 V.",
        encoding="utf-8",
    )
    candidate = DatasheetCandidate(
        part_number="LT8609SIV#PBF",
        manufacturer="Analog Devices",
        description="2A synchronous buck regulator.",
        confidence="test",
        extraction_notes=[
            "Requested conversion: 12V to 5V.",
            "Requested output current: 2 A.",
        ],
        datasheet_sources=[
            DatasheetSource(
                title="LT8609S fixture datasheet",
                source_type="manufacturer_datasheet",
                url=str(source_path),
                confidence="test",
            )
        ],
    )

    service = ComponentExtractionService(ai_service)
    job = service.start(candidate, run_inline=True)

    assert job.status == "ready"
    assert job.extraction is not None
    assert {(pin.number, pin.name, pin.net_name) for pin in job.extraction.pins} >= {
        ("1", "RUN", "EN"),
        ("4", "VIN", "VIN"),
        ("5", "SW", "SW"),
        ("6", "GND", "GND"),
        ("7", "BOOT", "BOOT"),
        ("8", "FB", "FB"),
    }
    support_by_purpose = {item.purpose: item for item in job.extraction.support_requirements}
    assert support_by_purpose["buck output inductor"].calculation_role == "buck_output_inductor"
    assert support_by_purpose["upper feedback divider resistor"].calculation_role == "feedback_divider_upper"


def test_short_chat_text_ends_long_descriptions_at_natural_phrase_boundaries():
    description = (
        "6-axis iNEMO IMU with 3-axis accelerometer, 3-axis gyroscope, "
        "I2C/SPI/MIPI I3C interface support, 9 KB FIFO, embedded finite-state "
        "machine and machine-learning core."
    )

    summary = _short_chat_text(description, limit=130)

    assert summary == (
        "6-axis iNEMO IMU with 3-axis accelerometer, 3-axis gyroscope, "
        "I2C/SPI/MIPI I3C interface support, 9 KB FIFO."
    )
    assert "finite-st" not in summary
    assert "..." not in summary


def test_datasheet_assistant_message_formats_candidate_cards_without_fragments():
    result = DatasheetSearchResponse(
        query="imu options",
        summary="Found IMU options.",
        candidates=[
            DatasheetCandidate(
                part_number="LSM6DSOXTR",
                manufacturer="STMicroelectronics",
                description=(
                    "6-axis iNEMO IMU with 3-axis accelerometer, 3-axis gyroscope, "
                    "I2C/SPI/MIPI I3C interface support, 9 KB FIFO, embedded finite-state "
                    "machine and machine-learning core."
                ),
                confidence="high",
                complexity="moderate",
            )
        ],
    )

    message = _datasheet_assistant_message(
        "I can search for candidate parts and discuss tradeoffs.",
        result,
    )

    assert (
        "- STMicroelectronics LSM6DSOXTR: 6-axis iNEMO IMU with 3-axis accelerometer, "
        "3-axis gyroscope, I2C/SPI/MIPI I3C interface support, 9 KB FIFO; "
        "moderate integration."
    ) in message
    assert ".;" not in message
    assert "finite-st" not in message
    assert "..." not in message


def test_datasheet_search_reuses_cached_exact_part(monkeypatch, tmp_path: Path):
    service = TraceLabsAIService(tmp_path)
    service.api_key = "sk-test"
    service.live_datasheet_search_enabled = True
    calls = []

    def fake_search(query, available_recipes, include_unsupported, deepening=False, timeout_seconds=None):
        calls.append((query, deepening))
        return {
            "_token_count": 321,
            "summary": "Found MPU-6050 sources.",
            "target_part_number": "MPU-6050",
            "context_part_numbers": [],
            "search_audit": ["Searched the official datasheet and evaluation-board material."],
            "candidates": [
                {
                    "part_number": "MPU-6050",
                    "manufacturer": "TDK InvenSense",
                    "description": "6-axis IMU.",
                    "supplier": "LCSC",
                    "supplier_part_number": "C24112",
                    "supplier_url": "https://www.lcsc.com/product-detail/C24112.html",
                    "supported_recipe_id": "",
                    "confidence": "high",
                    "complexity": "moderate",
                    "source_coverage": ["datasheet", "evaluation board"],
                    "capability_notes": ["Can create a reviewable extracted draft."],
                    "datasheet_sources": [
                        {
                            "title": "MPU-6050 product specification",
                            "source_type": "manufacturer_datasheet",
                            "url": "https://example.com/mpu6050.pdf",
                            "confidence": "official",
                            "notes": "test source",
                        },
                        {
                            "title": "MPU-6050 evaluation board",
                            "source_type": "evaluation_board",
                            "url": "https://example.com/mpu6050-evb",
                            "confidence": "official",
                            "notes": "test source",
                        },
                    ],
                    "extraction_notes": ["Use cited sources before generating."],
                    "warnings": [],
                }
            ],
            "warnings": [],
        }

    monkeypatch.setattr(service, "_call_openai_datasheet_search", fake_search)

    first = service.search_datasheets("Can you add an MPU-6050 IMU?", [], include_unsupported=True)
    second = service.search_datasheets("Use MPU6050 for this block", [], include_unsupported=True)

    assert first.provider == "openai_web_search"
    assert second.provider == "local_cache"
    assert second.live_search_used is False
    assert second.token_count == 0
    assert second.candidates[0].part_number == "MPU-6050"
    assert len(calls) == 1


def test_broad_datasheet_search_skips_deep_reference_followup(monkeypatch, tmp_path: Path):
    service = TraceLabsAIService(tmp_path)
    service.api_key = "sk-test"
    service.live_datasheet_search_enabled = True
    calls = []

    def fake_search(query, available_recipes, include_unsupported, deepening=False, timeout_seconds=None):
        calls.append((deepening, timeout_seconds))
        return {
            "_token_count": 123,
            "summary": "Found IMU options.",
            "target_part_number": "",
            "context_part_numbers": ["ESP32"],
            "search_audit": ["Initial broad search completed."],
            "candidates": [
                {
                    "part_number": "MPU-6050",
                    "manufacturer": "TDK InvenSense",
                    "description": "6-axis IMU.",
                    "supplier": "",
                    "supplier_part_number": "",
                    "supplier_url": "",
                    "supported_recipe_id": "",
                    "confidence": "medium",
                    "complexity": "moderate",
                    "source_coverage": ["datasheet"],
                    "capability_notes": ["Candidate option for comparison."],
                    "datasheet_sources": [
                        {
                            "title": "MPU-6050 product specification",
                            "source_type": "manufacturer_datasheet",
                            "url": "https://example.com/mpu6050.pdf",
                            "confidence": "official",
                            "notes": "test source",
                        }
                    ],
                    "extraction_notes": ["Selection requires cited extraction before generation."],
                    "warnings": [],
                }
            ],
            "warnings": [],
        }

    monkeypatch.setattr(service, "_call_openai_datasheet_search", fake_search)

    result = service.search_datasheets("I want IMU options for an ESP32 project", [], include_unsupported=True)

    assert calls == [(False, service.broad_datasheet_timeout_seconds)]
    assert result.candidates[0].part_number == "MPU-6050"
    assert any("No linked reference design" in warning for warning in result.warnings)


def test_exact_datasheet_search_deepens_missing_reference_sources(monkeypatch, tmp_path: Path):
    service = TraceLabsAIService(tmp_path)
    service.api_key = "sk-test"
    service.live_datasheet_search_enabled = True
    calls = []

    def fake_search(query, available_recipes, include_unsupported, deepening=False, timeout_seconds=None):
        calls.append((deepening, timeout_seconds))
        sources = [
            {
                "title": "MPU-6050 product specification",
                "source_type": "manufacturer_datasheet",
                "url": "https://example.com/mpu6050.pdf",
                "confidence": "official",
                "notes": "test source",
            }
        ]
        if deepening:
            sources.append(
                {
                    "title": "MPU-6050 evaluation board",
                    "source_type": "evaluation_board",
                    "url": "https://example.com/mpu6050-evb",
                    "confidence": "official",
                    "notes": "test source",
                }
            )
        return {
            "_token_count": 123,
            "summary": "Found MPU-6050 sources.",
            "target_part_number": "MPU-6050",
            "context_part_numbers": [],
            "search_audit": ["Search completed."],
            "candidates": [
                {
                    "part_number": "MPU-6050",
                    "manufacturer": "TDK InvenSense",
                    "description": "6-axis IMU.",
                    "supplier": "",
                    "supplier_part_number": "",
                    "supplier_url": "",
                    "supported_recipe_id": "",
                    "confidence": "high",
                    "complexity": "moderate",
                    "source_coverage": ["datasheet"],
                    "capability_notes": ["Can create a reviewable extracted draft."],
                    "datasheet_sources": sources,
                    "extraction_notes": ["Use cited sources before generating."],
                    "warnings": [],
                }
            ],
            "warnings": [],
        }

    monkeypatch.setattr(service, "_call_openai_datasheet_search", fake_search)

    result = service.search_datasheets("Can you add an MPU-6050 IMU?", [], include_unsupported=True)

    assert calls == [
        (False, service.datasheet_timeout_seconds),
        (True, service.datasheet_timeout_seconds),
    ]
    assert any(source.source_type == "evaluation_board" for source in result.candidates[0].datasheet_sources)


def test_component_extraction_reuses_cached_ready_extraction(monkeypatch, tmp_path: Path):
    source_path = tmp_path / "vl53_fixture.txt"
    source_path.write_text(
        "Pin 1 AVDD supply. Pin 2 GND ground. Pin 3 SDA I2C data. Pin 4 SCL I2C clock. "
        "Typical application schematic: place 100 nF capacitor between AVDD and GND.",
        encoding="utf-8",
    )
    candidate = DatasheetCandidate(
        part_number="VL53L1X",
        manufacturer="STMicroelectronics",
        description="Time-of-flight sensor.",
        confidence="high",
        datasheet_sources=[
            DatasheetSource(
                title="VL53L1X fixture datasheet",
                source_type="manufacturer_datasheet",
                url=str(source_path),
                confidence="official",
            )
        ],
    )
    service = ComponentExtractionService(ai_service, tmp_path)

    first = service.start(candidate, run_inline=True)
    assert first.status == "ready"

    def fail_read_url(url):
        raise AssertionError("cached extraction should not re-read source URLs")

    monkeypatch.setattr(service, "_read_url", fail_read_url)
    second = service.start(candidate, run_inline=True)

    assert second.status == "ready"
    assert "cached" in second.message.lower()
    assert second.extraction is not None
    assert {pin.name for pin in second.extraction.pins} >= {"AVDD", "GND", "SDA", "SCL"}


def test_exact_part_request_reuses_saved_draft_without_datasheet_search(monkeypatch, tmp_path: Path):
    ai_service.live_datasheet_search_enabled = False
    original_recipes_dir = generator.loader.recipes_dir
    original_use_saved_drafts = generator.loader.use_saved_drafts
    generator.loader.recipes_dir = tmp_path / "recipes"
    generator.loader.use_saved_drafts = True
    generator.loader.recipes_dir.mkdir()
    (generator.loader.recipes_dir / "bme280_i2c.json").write_text(
        original_recipes_dir.joinpath("bme280_i2c.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    saved_block = extracted_test_block(part_number="MPU6050", manufacturer="TDK InvenSense")
    try:
        saved_path = generator.loader.save_draft_from_block(saved_block)

        def fail_search(*args, **kwargs):
            raise AssertionError("saved draft should be used before datasheet search")

        monkeypatch.setattr(ai_service, "search_datasheets", fail_search)
        chat = client.post("/chat", json={"message": "Can you add an MPU6050 IMU?"})

        assert chat.status_code == 200
        body = chat.json()
        assert body["datasheet_results"] is None
        assert body["extraction_job"] is None
        assert body["draft_block"]["main_component"]["mpn"] == "MPU6050"
        assert body["draft_block"]["recipe_saved_path"] == str(saved_path)
        assert body["missing_questions"][0]["id"] == "recipe_review_confirmed"

        final = client.post(
            "/answer-questions",
            json={
                "answers": {"recipe_review_confirmed": "confirm"},
                "draft_block": body["draft_block"],
            },
        )
        assert final.status_code == 200
        assert final.json()["status"] == "final"
        assert final.json()["reference_extraction"] is not None
    finally:
        generator.loader.recipes_dir = original_recipes_dir
        generator.loader.use_saved_drafts = original_use_saved_drafts


def test_exact_part_request_ignores_host_context_part_numbers():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post("/chat", json={"message": "For an ESP32 project, can you add an MPU6050 IMU?"})
    assert chat.status_code == 200
    body = chat.json()
    assert body["draft_block"] is None
    assert body["extraction_job"]["candidate"]["part_number"] == "MPU6050"
    assert body["datasheet_results"]["target_part_number"] == "MPU6050"
    assert body["datasheet_results"]["context_part_numbers"] == ["ESP32"]


def test_time_of_flight_category_does_not_fall_back_to_environmental_sensor():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post(
        "/chat",
        json={
            "message": (
                "I want to add a time of flight sensor to my project that will be connected "
                "to an esp32 in my kicad project what are my options"
            )
        },
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["draft_block"] is None
    assert body["datasheet_results"] is None
    assert [question["id"] for question in body["missing_questions"]] == [
        "clarify_interface_preference",
        "clarify_priority",
    ]

    clarified = client.post(
        "/chat",
        json={
            "message": (
                "I want to add a time of flight sensor to my project that will be connected "
                "to an esp32 in my kicad project what are my options"
            ),
            "answers": {
                "clarify_interface_preference": "I2C",
                "clarify_priority": "Easiest integration",
            },
        },
    )
    assert clarified.status_code == 200
    body = clarified.json()
    assert body["datasheet_results"]["context_part_numbers"] == ["ESP32"]
    assert body["datasheet_results"]["candidates"] == []
    assert "BME280" not in body["assistant_message"]


def test_context_only_supported_part_mention_does_not_generate_recipe():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post("/chat", json={"message": "What microcontroller works well with a BME280?"})
    assert chat.status_code == 200
    body = chat.json()
    assert body["draft_block"] is None
    assert body["missing_questions"] == []
    assert body["datasheet_results"] is None


def test_account_endpoint_reports_local_meter_when_solvimon_is_not_configured(monkeypatch):
    monkeypatch.delenv("SOLVIMON_API_KEY", raising=False)
    monkeypatch.delenv("SOLVIMON_CUSTOMER_REFERENCE", raising=False)
    monkeypatch.delenv("SOLVIMON_CIRCUIT_BLOCK_METER_REFERENCE", raising=False)

    response = client.get("/account")

    assert response.status_code == 200
    body = response.json()
    assert body["account"]["account_id"]
    assert body["pricing_preview"]["plan_name"] == "Maker"
    assert body["billing"]["provider"] == "solvimon"
    assert body["billing"]["configured"] is False
    assert "Set SOLVIMON_API_KEY on the backend." in body["billing"]["setup_required"]


def test_configured_solvimon_sync_posts_meter_event(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SOLVIMON_API_KEY", "test-key")
    monkeypatch.setenv("SOLVIMON_CUSTOMER_REFERENCE", "customer_tracelabs_local")
    monkeypatch.setenv("SOLVIMON_CIRCUIT_BLOCK_METER_REFERENCE", "meter_generated_blocks")

    service = AccountBillingService(tmp_path / ".tracelabs")
    posted = {}

    def fake_post(path, payload):
        posted["path"] = path
        posted["payload"] = payload
        return {}

    monkeypatch.setattr(service, "_post_solvimon", fake_post)

    event = service.record(
        UsageEventRequest(
            reference="usage-test-1",
            event_type="circuit_block.generated",
            quantity=2,
            metadata={"block_slug": "demo"},
        )
    )

    assert event.solvimon_sync_status == "synced"
    assert posted["path"] == "/v1/ingest/meter-data"
    assert posted["payload"]["meter_reference"] == "meter_generated_blocks"
    assert posted["payload"]["customer_reference"] == "customer_tracelabs_local"
    assert posted["payload"]["reference"] == "usage-test-1"
    assert posted["payload"]["meter_values"] == [{"reference": "quantity", "number": "2.0"}]
    assert service.integration_status().configured is True


def test_exploratory_imu_request_clarifies_before_part_search():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post(
        "/chat",
        json={"message": "I want to add an IMU to my project for an esp32, what are my options?"},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["draft_block"] is None
    assert body["datasheet_results"] is None
    assert [question["id"] for question in body["missing_questions"]] == [
        "clarify_application",
        "clarify_interface_preference",
        "clarify_priority",
    ]

    clarified = client.post(
        "/chat",
        json={
            "message": "I want to add an IMU to my project for an esp32, what are my options?",
            "answers": {
                "clarify_application": "wearable motion tracking",
                "clarify_interface_preference": "I2C",
                "clarify_priority": "Lowest power",
            },
        },
    )
    assert clarified.status_code == 200
    body = clarified.json()
    assert body["missing_questions"] == []
    candidate_parts = [candidate["part_number"] for candidate in body["datasheet_results"]["candidates"]]
    assert candidate_parts == []
    assert "Application or use case: wearable motion tracking." in body["datasheet_results"]["query"]


def test_unknown_part_request_preserves_lcsc_supplier_id():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post("/chat", json={"message": "Can you add an MPU6050 IMU using LCSC C24112?"})
    assert chat.status_code == 200
    job = chat.json()["extraction_job"]
    assert job["candidate"]["part_number"] == "MPU6050"
    assert job["candidate"]["supplier"] == "LCSC"
    assert job["candidate"]["supplier_part_number"] == "C24112"


def test_lcsc_provider_imports_easyeda2kicad_footprint(monkeypatch, tmp_path: Path):
    def fake_run(command, cwd, capture_output, text, timeout, check):
        output_arg = next(item for item in command if item.startswith("--output="))
        output_base = Path(output_arg.split("=", 1)[1])
        pretty_dir = output_base.with_suffix(".pretty")
        pretty_dir.mkdir(parents=True)
        (pretty_dir / "EasyEDA_Footprint.kicad_mod").write_text(
            """(module easyeda2kicad:EasyEDA_Footprint
  (generator "easyeda2kicad")
  (fp_text value "OLD" (at 0 0 0) (layer "F.Fab"))
)""",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("backend.app.library_acquisition.subprocess.run", fake_run)
    block = extracted_test_block(
        part_number="MPU6050",
        manufacturer="TDK InvenSense",
        supplier="LCSC",
        supplier_part_number="C24112",
        supplier_url="https://www.lcsc.com/datasheet/C24112.pdf",
    )
    result = EasyEDALCSCProvider(enabled=True).acquire_for_block(
        block,
        symbol_name="MPU6050",
        footprint_name="TraceLabs_MPU6050_LCSC_C24112",
        footprint_id="TraceLabs_MPU6050:TraceLabs_MPU6050_LCSC_C24112",
    )

    assert result is not None
    assert result.footprint_text is not None
    assert '(footprint "TraceLabs_MPU6050_LCSC_C24112"' in result.footprint_text
    assert '(fp_text value "MPU6050"' in result.footprint_text
    assert result.sources[0].kind == "supplier_footprint"
    assert result.sources[0].path == "C24112"


def test_lcsc_provider_can_resolve_supplier_id_from_mpn_search(monkeypatch):
    def fake_search(self, keyword, page_size):
        assert keyword == "MPU6050"
        return {
            "results": [
                {
                    "lcsc": "C9900035575",
                    "name": "MPU6050 module without CAD",
                    "model": "MPU6050",
                    "brand": "JLCPCB Assembly",
                    "package": "LCC-8",
                    "url": "",
                },
                {
                    "lcsc": "C24112",
                    "name": "MPU6050 IMU",
                    "model": "MPU6050",
                    "brand": "TDK InvenSense",
                    "package": "QFN-24",
                    "url": "https://www.lcsc.com/product-detail/C24112.html",
                }
            ]
        }

    def fake_run(command, cwd, capture_output, text, timeout, check):
        lcsc_arg = next(item for item in command if item.startswith("--lcsc_id="))
        if lcsc_arg.endswith("C9900035575"):
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="[ERROR] no CAD data")
        output_arg = next(item for item in command if item.startswith("--output="))
        output_base = Path(output_arg.split("=", 1)[1])
        pretty_dir = output_base.with_suffix(".pretty")
        pretty_dir.mkdir(parents=True)
        (pretty_dir / "EasyEDA_Footprint.kicad_mod").write_text(
            '(module easyeda2kicad:MPU6050 (fp_text value "OLD" (at 0 0 0) (layer "F.Fab")))',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(
        "easyeda2kicad.easyeda.easyeda_api.EasyedaApi.search_jlcpcb_components",
        fake_search,
    )
    monkeypatch.setattr("backend.app.library_acquisition.subprocess.run", fake_run)
    block = extracted_test_block(
        part_number="MPU6050",
        manufacturer="TDK InvenSense",
    )

    result = EasyEDALCSCProvider(enabled=True).acquire_for_block(
        block,
        symbol_name="MPU6050",
        footprint_name="TraceLabs_MPU6050_SEARCHED",
        footprint_id="TraceLabs_MPU6050:TraceLabs_MPU6050_SEARCHED",
    )

    assert result is not None
    assert result.footprint_text is not None
    assert "TraceLabs_MPU6050_SEARCHED" in result.footprint_text
    assert result.sources[0].path == "C24112"
    assert result.sources[0].url == "https://www.lcsc.com/product-detail/C24112.html"


def test_datasheet_search_endpoint_returns_reviewable_sources_without_kicad_generation():
    ai_service.live_datasheet_search_enabled = False
    result = client.post("/datasheet/search", json={"query": "temperature sensor"})
    assert result.status_code == 200
    body = result.json()
    assert body["live_search_used"] is False
    assert body["provider"] == "local_fallback"
    assert body["candidates"][0]["part_number"] == "BME280"
    assert body["candidates"][0]["datasheet_sources"]


def test_legacy_placeholder_draft_choice_is_rejected():
    response = client.post("/chat", json={"message": "Use new_recipe::Legacy::Part for this block"})
    assert response.status_code == 400
    assert "Legacy placeholder draft choices are no longer supported" in response.json()["detail"]["message"]


def test_follow_up_question_returns_answer_without_resetting_block():
    chat = client.post("/chat", json={"message": "Can you add a BME280 temperature sensor?"})
    block = chat.json()["draft_block"]
    follow_up = client.post(
        "/chat",
        json={
            "message": "Why this one?",
            "draft_block": block,
        },
    )
    assert follow_up.status_code == 200
    body = follow_up.json()
    assert body["draft_block"] is None
    assert body["missing_questions"] == []
    assert "BME280" in body["assistant_message"]


def test_bridge_import_installs_project_libraries(tmp_path: Path):
    chat = client.post("/chat", json={"message": "Can you add a BME280 temperature sensor?"})
    block = client.post(
        "/answer-questions",
        json={
            "answers": {
                "logic_voltage": "3.3V",
                "interface_mode": "I2C",
                "i2c_address": "0x76",
                "pullups": "add",
            },
            "draft_block": chat.json()["draft_block"],
        },
    ).json()
    export = client.post("/export", json={"block": block})
    assert export.status_code == 200

    project = tmp_path / "weather_station"
    project.mkdir()
    (project / "weather_station.kicad_pro").write_text("{}", encoding="utf-8")
    (project / "weather_station.kicad_sch").write_text(
        '(kicad_sch (version 20230121) (generator "Trace Labs")\n'
        '  (uuid "00000000-0000-0000-0000-000000000000")\n'
        ")\n",
        encoding="utf-8",
    )

    service = BridgeService(tmp_path / ".tracelabs")
    link = service.link(BridgeLinkRequest(project_path=str(project), project_name="weather_station.kicad_pro"))
    service.import_block(export.json()["output_directory"], link.link_id)

    assert (project / "tracelabs_libs" / "TraceLabs_BME280.kicad_sym").exists()
    assert (
        project
        / "tracelabs_libs"
        / "TraceLabs_BME280.pretty"
        / "TraceLabs_BME280_LGA8_2.5x2.5mm_P0.65mm.kicad_mod"
    ).exists()
    symbol_table = (project / "sym-lib-table").read_text(encoding="utf-8")
    footprint_table = (project / "fp-lib-table").read_text(encoding="utf-8")
    assert '(name "TraceLabs_BME280")' in symbol_table
    assert '(uri "${KIPRJMOD}/tracelabs_libs/TraceLabs_BME280.kicad_sym")' in symbol_table
    assert '(name "TraceLabs_BME280")' in footprint_table
    assert '(uri "${KIPRJMOD}/tracelabs_libs/TraceLabs_BME280.pretty")' in footprint_table


def test_bridge_import_replaces_stale_footprint_library_table_entry(tmp_path: Path):
    chat = client.post("/chat", json={"message": "Can you add a BME280 temperature sensor?"})
    block = client.post(
        "/answer-questions",
        json={
            "answers": {
                "logic_voltage": "3.3V",
                "interface_mode": "I2C",
                "i2c_address": "0x76",
                "pullups": "add",
            },
            "draft_block": chat.json()["draft_block"],
        },
    ).json()
    export = client.post("/export", json={"block": block})
    assert export.status_code == 200

    project = tmp_path / "weather_station"
    project.mkdir()
    (project / "weather_station.kicad_pro").write_text("{}", encoding="utf-8")
    (project / "weather_station.kicad_sch").write_text(
        '(kicad_sch (version 20230121) (generator "Trace Labs")\n'
        '  (uuid "00000000-0000-0000-0000-000000000000")\n'
        ")\n",
        encoding="utf-8",
    )
    (project / "fp-lib-table").write_text(
        '(fp_lib_table\n'
        '\t(version 7)\n'
        '  (lib (name "TraceLabs_BME280") (type "KiCad") '
        '(uri "/tmp/missing/TraceLabs_BME280.pretty") '
        '(options "") (descr "stale Trace Labs footprint library"))\n'
        ')\n',
        encoding="utf-8",
    )

    service = BridgeService(tmp_path / ".tracelabs")
    link = service.link(BridgeLinkRequest(project_path=str(project), project_name="weather_station.kicad_pro"))
    service.import_block(export.json()["output_directory"], link.link_id)

    footprint_table = (project / "fp-lib-table").read_text(encoding="utf-8")
    assert "/tmp/missing" not in footprint_table
    assert footprint_table.count('(name "TraceLabs_BME280")') == 1
    assert '(uri "${KIPRJMOD}/tracelabs_libs/TraceLabs_BME280.pretty")' in footprint_table


def test_bridge_import_opens_root_schematic_for_hierarchical_import_when_requested(tmp_path: Path, monkeypatch):
    chat = client.post("/chat", json={"message": "Can you add a BME280 temperature sensor?"})
    block = client.post(
        "/answer-questions",
        json={
            "answers": {
                "logic_voltage": "3.3V",
                "interface_mode": "I2C",
                "i2c_address": "0x76",
                "pullups": "add",
            },
            "draft_block": chat.json()["draft_block"],
        },
    ).json()
    export = client.post("/export", json={"block": block})
    assert export.status_code == 200

    project = tmp_path / "weather_station"
    project.mkdir()
    (project / "weather_station.kicad_pro").write_text("{}", encoding="utf-8")
    (project / "weather_station.kicad_sch").write_text(
        '(kicad_sch (version 20230121) (generator "Trace Labs")\n'
        '  (uuid "00000000-0000-0000-0000-000000000000")\n'
        ")\n",
        encoding="utf-8",
    )

    opened_paths = []
    service = BridgeService(tmp_path / ".tracelabs")
    monkeypatch.setattr(service, "_open_sheet", lambda sheet_path: opened_paths.append(sheet_path))
    link = service.link(BridgeLinkRequest(project_path=str(project), project_name="weather_station.kicad_pro"))
    result = service.import_block(export.json()["output_directory"], link.link_id, open_after_import=True)

    expected_sheet = project / "weather_station.kicad_sch"
    assert opened_paths == [expected_sheet]
    assert result.opened_sheet_path == str(expected_sheet)
    assert result.open_error is None


def test_bridge_import_can_insert_directly_into_root_schematic(tmp_path: Path):
    chat = client.post("/chat", json={"message": "Can you add a BME280 temperature sensor?"})
    block = client.post(
        "/answer-questions",
        json={
            "answers": {
                "logic_voltage": "3.3V",
                "interface_mode": "I2C",
                "i2c_address": "0x76",
                "pullups": "add",
            },
            "draft_block": chat.json()["draft_block"],
        },
    ).json()
    export = client.post("/export", json={"block": block})
    assert export.status_code == 200

    project = tmp_path / "weather_station"
    project.mkdir()
    root_schematic = project / "weather_station.kicad_sch"
    (project / "weather_station.kicad_pro").write_text("{}", encoding="utf-8")
    root_schematic.write_text(
        '(kicad_sch (version 20230121) (generator "Trace Labs")\n'
        '  (uuid "00000000-0000-0000-0000-000000000000")\n'
        '  (paper "A4")\n'
        ")\n",
        encoding="utf-8",
    )

    service = BridgeService(tmp_path / ".tracelabs")
    link = service.link(BridgeLinkRequest(project_path=str(project), project_name="weather_station.kicad_pro"))
    result = service.import_block(export.json()["output_directory"], link.link_id, import_mode="inline_main")

    schematic = root_schematic.read_text(encoding="utf-8")
    assert result.mode == "inline_main"
    assert '(symbol (lib_id "TraceLabs_BME280:BME280")' in schematic
    assert '(symbol (lib_id "power:+3V3")' in schematic
    assert '(symbol (lib_id "power:GND")' in schematic
    assert schematic.count('(symbol (lib_id "power:+3V3")') >= 2
    assert schematic.count('(symbol (lib_id "power:GND")') >= 2
    assert "global_label" in schematic
    assert '(global_label "I2C1_SCL" (shape input) (at 142.24 93.98 0)' in schematic
    assert '(global_label "I2C1_SDA" (shape bidirectional) (at 142.24 99.06 0)' in schematic
    assert 'global_label "+3V3"' not in schematic
    assert 'global_label "GND"' not in schematic
    assert 'label "+3V3"' not in schematic
    assert 'label "GND"' not in schematic
    assert "hierarchical_label" not in schematic
    assert "Sheet file" not in schematic
    assert "TraceLabs_BME280:TraceLabs_BME280_LGA8_2.5x2.5mm_P0.65mm" in schematic
    label_rotations = re.findall(
        r"\((?:global_label|label)\s+\"[^\"]+\".*?\(at\s+-?\d+(?:\.\d+)?\s+-?\d+(?:\.\d+)?\s+(-?\d+(?:\.\d+)?)\)",
        schematic,
        flags=re.DOTALL,
    )
    assert label_rotations
    assert set(label_rotations) == {"0"}
    assert result.backups
    assert Path(result.backups[0]).exists()
