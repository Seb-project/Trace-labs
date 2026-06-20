import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.ai_service import PCBStreamAIService
from backend.app.bridge_ops import BridgeService
from backend.app.component_extraction import ComponentExtractionService
from backend.app.library_acquisition import DownloadedLibraryAssets, DownloadedSource, EasyEDALCSCProvider
from backend.app.library_assets import DraftLibraryAssets
from backend.app.kicad_writer import KiCadWriter
from backend.app.main import ai_service, app, generator, writer
from backend.app.models import (
    BridgeLinkRequest,
    CircuitBlock,
    CircuitNet,
    DatasheetCandidate,
    DatasheetSource,
    PinDefinition,
    PricingPreview,
    ReferenceCircuitExtraction,
    SourceChunk,
    SupportRequirement,
)


client = TestClient(app)
ai_service.api_key = ""
ai_service.live_datasheet_search_enabled = False
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
    assert block["main_component"]["symbol"] == "PCBStream_BME280:BME280"
    assert block["main_component"]["footprint"] == "PCBStream_BME280:PCBStream_BME280_LGA8_2.5x2.5mm_P0.65mm"
    assert block["main_component"]["footprint_confidence"] == "needs_review"
    resistors = [component for component in block["support_components"] if component["symbol"] == "Device:R"]
    assert [component["purpose"] for component in resistors] == ["I2C SDA pull-up", "I2C SCL pull-up"]

    export = client.post("/export", json={"block": block})
    assert export.status_code == 200
    files = export.json()["files"]
    assert Path(files["block.json"]).exists()
    assert Path(files["bme280_i2c.kicad_sch"]).exists()
    schematic = Path(files["bme280_i2c.kicad_sch"]).read_text(encoding="utf-8")
    assert "PCBStream_BME280:BME280" in schematic
    assert Path(files["PCBStream_BME280.kicad_sym"]).exists()
    assert Path(files["PCBStream_BME280_LGA8_2.5x2.5mm_P0.65mm.kicad_mod"]).exists()
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


def test_generic_temperature_sensor_request_asks_to_choose_a_specific_part():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post("/chat", json={"message": "I need a temperature sensor"})
    assert chat.status_code == 200
    body = chat.json()
    assert body["draft_block"] is None
    assert body["missing_questions"][0]["id"] == "part_choice"
    assert body["missing_questions"][0]["options"][0]["value"] == "bme280_i2c"
    assert body["datasheet_results"]["candidates"][0]["part_number"] == "BME280"

    selected = client.post("/chat", json={"message": "Use BME280 for this block"})
    assert selected.status_code == 200
    assert selected.json()["draft_block"]["block_slug"] == "bme280_i2c"


def test_obvious_part_search_does_not_need_openai_intent_classifier(monkeypatch):
    service = PCBStreamAIService()
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
  (generator "PCBStream")
  (property "Reference" "U?" (at 0 -1 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (property "Value" "{block.main_component.value}" (at 0 1 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
)""",
                footprint_name="PCBStream_VL53L1X_LCSC_C2924337",
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
        assert block["main_component"]["symbol"].startswith("PCBStream_VL53L1X:")

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
            '(kicad_sch (version 20230121) (generator "PCBStream")\n'
            '  (uuid "00000000-0000-0000-0000-000000000000")\n'
            ")\n",
            encoding="utf-8",
        )
        service = BridgeService(tmp_path / ".pcbstream_draft")
        link = service.link(BridgeLinkRequest(project_path=str(project), project_name="weather_station.kicad_pro"))
        imported = service.import_block(str(schematic_path.parent), link.link_id, import_mode="inline_main")
        assert imported.success is True
        assert (project / "pcbstream_libs" / "PCBStream_VL53L1X.kicad_sym").exists()
        assert (project / "pcbstream_libs" / "PCBStream_VL53L1X.pretty" / "PCBStream_VL53L1X_LCSC_C2924337.kicad_mod").exists()
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
  (generator "PCBStream")
  (property "Reference" "U?" (at 0 -1 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (property "Value" "{block.main_component.value}" (at 0 1 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
)""",
                footprint_name="PCBStream_VL53L1X_LCSC_C2924337",
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

    assert block.main_component.symbol_confidence == "downloaded_needs_review"
    assert block.main_component.footprint_confidence == "downloaded_needs_review"
    assert block.main_component.footprint == "PCBStream_VL53L1X:PCBStream_VL53L1X_LCSC_C2924337"
    assert block.main_component.supplier == "LCSC"
    assert block.main_component.supplier_part_number == "C2924337"
    assert paths.symbol_library.exists()
    assert paths.footprint_file.exists()
    assert paths.footprint_file.name == "PCBStream_VL53L1X_LCSC_C2924337.kicad_mod"
    assert "C2924337" in paths.sources_file.read_text(encoding="utf-8")
    assert "PCBStream_VL53L1X:VL53L1X" in assets.schematic_cached_symbol(block)


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
    assert body["missing_questions"] == []
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


def test_exploratory_imu_request_suggests_options_without_creating_draft():
    ai_service.live_datasheet_search_enabled = False
    chat = client.post(
        "/chat",
        json={"message": "I want to add an IMU to my project for an esp32, what are my options?"},
    )
    assert chat.status_code == 200
    body = chat.json()
    assert body["draft_block"] is None
    assert body["missing_questions"] == []
    candidate_parts = [candidate["part_number"] for candidate in body["datasheet_results"]["candidates"]]
    assert candidate_parts == []


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
        footprint_name="PCBStream_MPU6050_LCSC_C24112",
        footprint_id="PCBStream_MPU6050:PCBStream_MPU6050_LCSC_C24112",
    )

    assert result is not None
    assert result.footprint_text is not None
    assert '(footprint "PCBStream_MPU6050_LCSC_C24112"' in result.footprint_text
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
        footprint_name="PCBStream_MPU6050_SEARCHED",
        footprint_id="PCBStream_MPU6050:PCBStream_MPU6050_SEARCHED",
    )

    assert result is not None
    assert result.footprint_text is not None
    assert "PCBStream_MPU6050_SEARCHED" in result.footprint_text
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
        '(kicad_sch (version 20230121) (generator "PCBStream")\n'
        '  (uuid "00000000-0000-0000-0000-000000000000")\n'
        ")\n",
        encoding="utf-8",
    )

    service = BridgeService(tmp_path / ".pcbstream")
    link = service.link(BridgeLinkRequest(project_path=str(project), project_name="weather_station.kicad_pro"))
    service.import_block(export.json()["output_directory"], link.link_id)

    assert (project / "pcbstream_libs" / "PCBStream_BME280.kicad_sym").exists()
    assert (
        project
        / "pcbstream_libs"
        / "PCBStream_BME280.pretty"
        / "PCBStream_BME280_LGA8_2.5x2.5mm_P0.65mm.kicad_mod"
    ).exists()
    assert "PCBStream_BME280" in (project / "sym-lib-table").read_text(encoding="utf-8")
    assert "PCBStream_BME280" in (project / "fp-lib-table").read_text(encoding="utf-8")


def test_bridge_import_opens_inserted_hierarchical_sheet_when_requested(tmp_path: Path, monkeypatch):
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
        '(kicad_sch (version 20230121) (generator "PCBStream")\n'
        '  (uuid "00000000-0000-0000-0000-000000000000")\n'
        ")\n",
        encoding="utf-8",
    )

    opened_paths = []
    service = BridgeService(tmp_path / ".pcbstream")
    monkeypatch.setattr(service, "_open_sheet", lambda sheet_path: opened_paths.append(sheet_path))
    link = service.link(BridgeLinkRequest(project_path=str(project), project_name="weather_station.kicad_pro"))
    result = service.import_block(export.json()["output_directory"], link.link_id, open_after_import=True)

    expected_sheet = project / "pcbstream_blocks" / "bme280_i2c" / "bme280_i2c.kicad_sch"
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
        '(kicad_sch (version 20230121) (generator "PCBStream")\n'
        '  (uuid "00000000-0000-0000-0000-000000000000")\n'
        '  (paper "A4")\n'
        ")\n",
        encoding="utf-8",
    )

    service = BridgeService(tmp_path / ".pcbstream")
    link = service.link(BridgeLinkRequest(project_path=str(project), project_name="weather_station.kicad_pro"))
    result = service.import_block(export.json()["output_directory"], link.link_id, import_mode="inline_main")

    schematic = root_schematic.read_text(encoding="utf-8")
    assert result.mode == "inline_main"
    assert '(symbol (lib_id "PCBStream_BME280:BME280")' in schematic
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
    assert "PCBStream_BME280:PCBStream_BME280_LGA8_2.5x2.5mm_P0.65mm" in schematic
    label_rotations = re.findall(
        r"\((?:global_label|label)\s+\"[^\"]+\".*?\(at\s+-?\d+(?:\.\d+)?\s+-?\d+(?:\.\d+)?\s+(-?\d+(?:\.\d+)?)\)",
        schematic,
        flags=re.DOTALL,
    )
    assert label_rotations
    assert set(label_rotations) == {"0"}
    assert result.backups
    assert Path(result.backups[0]).exists()
