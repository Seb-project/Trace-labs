from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .ai_service import AIChatDecision, AISuggestion, TraceLabsAIService
from .bridge_ops import BridgeService
from .component_extraction import decode_candidate_choice, encode_candidate_choice, ComponentExtractionService
from .generator import CircuitGenerator, RecipeLoader, default_project_context
from .kicad_writer import KiCadWriter
from .models import (
    AccountOverview,
    AnswerQuestionsRequest,
    BackendError,
    BillingPortalResponse,
    BridgeImportRequest,
    BridgeImportResponse,
    BridgeLinkRecord,
    BridgeLinkRequest,
    ChatRequest,
    ChatResponse,
    ComponentExtractionJobResponse,
    ComponentExtractionStartRequest,
    DatasheetCandidate,
    DatasheetSearchRequest,
    DatasheetSearchResponse,
    ExportRequest,
    ExportResponse,
    GenerateRequest,
    HealthResponse,
    MissingQuestion,
    Option,
    PricingPreview,
    ProjectContext,
    RecipeSummary,
    UsageEventRequest,
    ValidationWarning,
)
from .part_intent import analyse_part_intent, extract_target_part_numbers, normalise_part_number
from .pricing import MockSolvimonService
from .settings import load_local_env, path_from_env


def _seed_recipes(source_dir: Path, target_dir: Path) -> None:
    if source_dir == target_dir or not source_dir.exists():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for source in source_dir.rglob("*"):
        relative = source.relative_to(source_dir)
        target = target_dir / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


ROOT = path_from_env("TRACELABS_APP_ROOT", Path(__file__).resolve().parents[2])
load_local_env(ROOT)
DATA_DIR = path_from_env("TRACELABS_DATA_DIR", ROOT / ".tracelabs")
PACKAGED_RECIPES_DIR = path_from_env("TRACELABS_PACKAGED_RECIPES_DIR", ROOT / "backend" / "recipes")
RECIPES_DIR = path_from_env("TRACELABS_RECIPES_DIR", PACKAGED_RECIPES_DIR)
GENERATED_BLOCKS_DIR = path_from_env("TRACELABS_GENERATED_BLOCKS_DIR", ROOT / "generated_blocks")
DATA_DIR.mkdir(parents=True, exist_ok=True)
GENERATED_BLOCKS_DIR.mkdir(parents=True, exist_ok=True)
_seed_recipes(PACKAGED_RECIPES_DIR, RECIPES_DIR)
loader = RecipeLoader(RECIPES_DIR)
generator = CircuitGenerator(loader)
pricing = MockSolvimonService(DATA_DIR)
writer = KiCadWriter(GENERATED_BLOCKS_DIR)
bridge = BridgeService(DATA_DIR)
ai_service = TraceLabsAIService(DATA_DIR)
extraction_service = ComponentExtractionService(ai_service, DATA_DIR)

CONVERTER_CLARIFICATION_INPUTS = {
    "calc_input_voltage_v": "input voltage",
    "calc_output_voltage_v": "output voltage",
    "calc_output_current_a": "maximum output current",
}
CONVERTER_REQUEST_TERMS = (
    "buck",
    "boost",
    "buck-boost",
    "buck boost",
    "step-down",
    "step down",
    "step-up",
    "step up",
    "dc-dc",
    "dcdc",
    "switching regulator",
)
CATEGORY_CLARIFICATION_INPUTS = {
    "clarify_application": "application or use case",
    "clarify_interface_preference": "interface preference",
    "clarify_supply_voltage_v": "supply or logic voltage",
    "clarify_priority": "recommendation priority",
}
CATEGORY_CLARIFICATION_IDS = tuple(CATEGORY_CLARIFICATION_INPUTS)
CATEGORY_INTERFACE_TERMS = {
    "i2c": "I2C",
    "i²c": "I2C",
    "spi": "SPI",
    "analog": "Analog",
    "uart": "UART",
    "can": "CAN",
    "usb": "USB",
}
CATEGORY_PRIORITY_TERMS = {
    "accuracy": "Highest accuracy/performance",
    "accurate": "Highest accuracy/performance",
    "precision": "Highest accuracy/performance",
    "precise": "Highest accuracy/performance",
    "low power": "Lowest power",
    "battery": "Lowest power",
    "cheap": "Lowest cost",
    "cost": "Lowest cost",
    "small": "Smallest package",
    "compact": "Smallest package",
    "simple": "Easiest integration",
}

app = FastAPI(title="Trace Labs Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    status = bridge.status()
    return HealthResponse(kicad_bridge_status="linked" if status.get("connected") else "mocked")


@app.get("/project-context", response_model=ProjectContext)
def project_context() -> ProjectContext:
    return default_project_context()


@app.get("/recipes", response_model=list[RecipeSummary])
def recipes() -> list[RecipeSummary]:
    return [RecipeSummary(**item) for item in loader.summaries()]


@app.get("/ai/status")
def ai_status():
    return ai_service.status()


@app.post("/datasheet/search", response_model=DatasheetSearchResponse)
def datasheet_search(request: DatasheetSearchRequest) -> DatasheetSearchResponse:
    result = ai_service.search_datasheets(
        request.query,
        available_recipes=loader.summaries(),
        include_unsupported=request.include_unsupported,
    )
    _record_datasheet_usage(result)
    return result


@app.post("/component-extraction/start", response_model=ComponentExtractionJobResponse)
def component_extraction_start(request: ComponentExtractionStartRequest) -> ComponentExtractionJobResponse:
    candidate = request.candidate or decode_candidate_choice(request.choice_value or "")
    if candidate is None:
        raise HTTPException(
            status_code=400,
            detail=BackendError(message="A selected datasheet candidate is required for extraction.").model_dump(),
        )
    job = extraction_service.start(candidate)
    return _job_with_ready_draft(job)


@app.get("/component-extraction/{job_id}", response_model=ComponentExtractionJobResponse)
def component_extraction_status(job_id: str) -> ComponentExtractionJobResponse:
    return _job_with_ready_draft(extraction_service.get(job_id))


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    if "new_recipe::" in request.message:
        raise HTTPException(
            status_code=400,
            detail=BackendError(
                message="Legacy placeholder draft choices are no longer supported.",
                next_steps=["Select the part again so Trace Labs can run datasheet/reference-design extraction."],
            ).model_dump(),
        )

    clarification_response = _converter_clarification_response(request)
    if clarification_response is not None:
        return clarification_response

    clarification_response = _category_clarification_response(request)
    if clarification_response is not None:
        return clarification_response

    request_message = _message_with_presearch_context(request.message, request.answers)
    decision = ai_service.decide(
        request_message,
        available_recipes=loader.summaries(),
        current_block=request.current_block,
        draft_block=request.draft_block,
        answers=request.answers,
        history=request.history,
    )
    if decision.token_count > 0:
        pricing.record(
            UsageEventRequest(
                event_type="ai_token.used",
                quantity=decision.token_count,
                metadata={"model": ai_service.model, "action": decision.action},
            )
        )

    if decision.action == "generate_recipe" and decision.recipe_id in {"", "bme280_i2c"}:
        draft = generator.draft("bme280_i2c")
        return ChatResponse(
            assistant_message=decision.assistant_message,
            draft_block=draft,
            missing_questions=draft.missing_questions,
            project_context=default_project_context(),
            warnings=draft.validation_warnings,
            next_steps=draft.next_steps,
        )

    if decision.action == "suggest_parts":
        saved_response = _draft_response_from_saved_recipe(
            request_message,
            decision.assistant_message,
            [decision.target_part_number] if decision.target_part_number else [],
        )
        if saved_response is not None:
            return saved_response

        datasheet_result = ai_service.search_datasheets(
            request_message,
            available_recipes=loader.summaries(),
            include_unsupported=True,
        )
        _record_datasheet_usage(datasheet_result)
        assistant_message = _datasheet_assistant_message(decision.assistant_message, datasheet_result)
        direct_candidate = _candidate_for_direct_draft(
            request_message,
            datasheet_result,
            [decision.target_part_number] if decision.target_part_number else [],
        )
        if direct_candidate:
            return _draft_response_from_candidate(
                direct_candidate,
                datasheet_result,
                assistant_message,
                request_message,
            )
        part_question = _part_choice_question_from_datasheets(datasheet_result, decision, request_message)
        return ChatResponse(
            assistant_message=assistant_message,
            draft_block=None,
            missing_questions=[part_question] if part_question else [],
            project_context=default_project_context(),
            datasheet_results=datasheet_result,
        )

    if decision.action == "answer_question":
        return ChatResponse(
            assistant_message=decision.assistant_message,
            draft_block=None,
            missing_questions=[],
            project_context=default_project_context(),
        )

    if _looks_like_new_part_request(request.message, request.current_block, request.draft_block):
        saved_response = _draft_response_from_saved_recipe(
            request_message,
            decision.assistant_message,
            [decision.target_part_number] if decision.target_part_number else [],
        )
        if saved_response is not None:
            return saved_response

        datasheet_result = ai_service.search_datasheets(
            request_message,
            available_recipes=loader.summaries(),
            include_unsupported=True,
        )
        _record_datasheet_usage(datasheet_result)
        candidate = _candidate_for_direct_draft(
            request_message,
            datasheet_result,
            [decision.target_part_number] if decision.target_part_number else [],
        )
        if candidate:
            return _draft_response_from_candidate(
                candidate,
                datasheet_result,
                _datasheet_assistant_message(decision.assistant_message, datasheet_result),
                request_message,
            )
        part_question = _part_choice_question_from_datasheets(datasheet_result, decision, request_message)
        if part_question:
            return ChatResponse(
                assistant_message=_datasheet_assistant_message(decision.assistant_message, datasheet_result),
                draft_block=None,
                missing_questions=[part_question],
                project_context=default_project_context(),
                datasheet_results=datasheet_result,
            )

    return ChatResponse(
        assistant_message=decision.assistant_message,
        draft_block=None,
        missing_questions=[],
        project_context=default_project_context(),
    )


@app.post("/generate")
def generate(request: GenerateRequest):
    if not generator.is_supported_prompt(request.prompt):
        raise HTTPException(
            status_code=400,
            detail=BackendError(
                message="Trace Labs can only generate verified local recipes or reviewed AI-proposed drafts.",
                next_steps=["Use the chat endpoint to ask for a part number or circuit block."],
            ).model_dump(),
        )

    draft = generator.draft()
    if request.known_values:
        draft.selected_options.update(request.known_values)
        draft.missing_questions = [
            question for question in draft.missing_questions if question.id not in request.known_values
        ]
    if not draft.missing_questions and request.known_values:
        block = generator.finalise(AnswerQuestionsRequest(answers=request.known_values, draft_block=draft))
        pricing.record(UsageEventRequest(event_type="circuit_block.generated", metadata={"block_slug": block.block_slug}))
        return block
    return draft


@app.post("/answer-questions")
def answer_questions(request: AnswerQuestionsRequest):
    try:
        block = generator.finalise(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=BackendError(message=str(exc)).model_dump()) from exc
    pricing.record(UsageEventRequest(event_type="circuit_block.generated", metadata={"block_slug": block.block_slug}))
    return block


@app.post("/export", response_model=ExportResponse)
def export(request: ExportRequest) -> ExportResponse:
    price = pricing.preview()
    try:
        output_dir, files = writer.export(request.block, price)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=BackendError(message=str(exc)).model_dump()) from exc
    pricing.record(UsageEventRequest(event_type="kicad_export.created", metadata={"block_slug": request.block.block_slug}))
    return ExportResponse(
        success=True,
        message="Block exported successfully.",
        output_directory=str(output_dir),
        files=files,
        pricing_preview=pricing.preview(),
        bridge_action_note="Generated block exported. KiCad bridge insertion is ready.",
        block=request.block,
    )


@app.post("/usage-event")
def usage_event(request: UsageEventRequest):
    event = pricing.record(request)
    return {"event": event, "pricing_preview": pricing.preview()}


@app.get("/pricing-preview", response_model=PricingPreview)
def pricing_preview() -> PricingPreview:
    return pricing.preview()


@app.get("/account", response_model=AccountOverview)
def account() -> AccountOverview:
    return pricing.overview()


@app.post("/account/billing-portal", response_model=BillingPortalResponse)
def account_billing_portal() -> BillingPortalResponse:
    status = pricing.integration_status()
    if not status.configured:
        return BillingPortalResponse(
            available=False,
            message="Solvimon billing is not fully configured on this backend.",
            actions=status.setup_required,
        )
    return BillingPortalResponse(
        available=False,
        message=(
            "Usage sync is configured. Manage customers, subscriptions, invoices, "
            "and payment methods in Solvimon Desk for now."
        ),
        actions=[
            "Open the Solvimon sandbox or live Desk environment.",
            "Use the displayed customer reference to find this account.",
        ],
    )


@app.post("/bridge/link", response_model=BridgeLinkRecord)
def bridge_link(request: BridgeLinkRequest) -> BridgeLinkRecord:
    return bridge.link(request)


@app.get("/bridge/status")
def bridge_status():
    return bridge.status()


@app.post("/bridge/import", response_model=BridgeImportResponse)
def bridge_import(request: BridgeImportRequest) -> BridgeImportResponse:
    try:
        return bridge.import_block(
            request.generated_block_dir,
            request.link_id,
            request.import_mode,
            request.open_after_import,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=BackendError(message=str(exc)).model_dump()) from exc


def _converter_clarification_response(request: ChatRequest) -> ChatResponse | None:
    if not _looks_like_converter_requirements_request(request.message, request.current_block, request.draft_block):
        return None

    requirements = _converter_requirements(request.message, request.answers)
    question_text = {
        "calc_input_voltage_v": "What input voltage should the converter accept (V)?",
        "calc_output_voltage_v": "What output voltage should it generate (V)?",
        "calc_output_current_a": "What maximum output current should it supply (A)?",
    }
    missing_questions = [
        MissingQuestion(
            id=input_id,
            question=question_text[input_id],
            type="number",
            default=requirements.get(input_id, ""),
            required=True,
        )
        for input_id in CONVERTER_CLARIFICATION_INPUTS
        if not requirements.get(input_id)
    ]
    if not missing_questions:
        return None

    missing_labels = ", ".join(CONVERTER_CLARIFICATION_INPUTS[item.id] for item in missing_questions)
    return ChatResponse(
        assistant_message=(
            "Before I recommend converter parts or start datasheet extraction, I need the operating "
            f"requirements Trace Labs uses to filter candidates and calculate support values: {missing_labels}."
        ),
        draft_block=None,
        missing_questions=missing_questions,
        project_context=default_project_context(),
    )


def _category_clarification_response(request: ChatRequest) -> ChatResponse | None:
    if not _looks_like_category_clarification_request(request):
        return None

    missing_questions = _category_clarification_questions(request.message, request.answers)
    if not missing_questions:
        return None

    missing_labels = ", ".join(CATEGORY_CLARIFICATION_INPUTS[item.id] for item in missing_questions)
    return ChatResponse(
        assistant_message=(
            "Before I recommend parts, I need a little more context so the options fit the design: "
            f"{missing_labels}."
        ),
        draft_block=None,
        missing_questions=missing_questions,
        project_context=default_project_context(),
    )


def _looks_like_category_clarification_request(request: ChatRequest) -> bool:
    if request.current_block is not None or request.draft_block is not None:
        return False
    text = request.message.lower()
    if any(term in text for term in CONVERTER_REQUEST_TERMS):
        return False
    intent = analyse_part_intent(request.message)
    if not intent.has_category_request or intent.target_part_numbers:
        return False
    if not (intent.has_generation_intent or intent.has_exploratory_intent):
        return False
    if _has_explicit_category_clarification_answers(request.answers):
        return False
    if re.search(r"\b(?:what\s+is|what's|explain|how\s+does|how\s+do)\b", text):
        return False
    return bool(_category_clarification_questions(request.message, request.answers))


def _has_explicit_category_clarification_answers(answers: dict[str, str]) -> bool:
    return any(str(answers.get(input_id, "")).strip() for input_id in CATEGORY_CLARIFICATION_IDS)


def _category_clarification_questions(message: str, answers: dict[str, str]) -> list[MissingQuestion]:
    inferred = _category_context_from_message(message)
    questions: list[MissingQuestion] = []
    if not _answer_or_inferred("clarify_application", answers, inferred):
        questions.append(
            MissingQuestion(
                id="clarify_application",
                question=(
                    "What should this part do in the project? For example: weather station, wearable motion, "
                    "battery monitor, or motor control."
                ),
                type="text",
                default="General-purpose prototype",
                required=True,
            )
        )
    if not _answer_or_inferred("clarify_interface_preference", answers, inferred):
        questions.append(
            MissingQuestion(
                id="clarify_interface_preference",
                question="Which interface should recommendations prefer?",
                options=[
                    Option(label="Let Trace Labs choose", value="Let Trace Labs choose a common interface"),
                    Option(label="I2C", value="I2C"),
                    Option(label="SPI", value="SPI"),
                    Option(label="Analog", value="Analog"),
                    Option(label="UART/CAN/other", value="UART/CAN/other"),
                ],
                default="Let Trace Labs choose a common interface",
            )
        )
    if not _answer_or_inferred("clarify_supply_voltage_v", answers, inferred):
        default_voltage = _default_supply_voltage(message)
        questions.append(
            MissingQuestion(
                id="clarify_supply_voltage_v",
                question="What supply or logic voltage should it support?",
                options=[
                    Option(label=default_voltage, value=default_voltage),
                    Option(label="5V", value="5V"),
                    Option(label="1.8V", value="1.8V"),
                    Option(label="Not sure", value="not sure"),
                ],
                default=default_voltage,
            )
        )
    if not _answer_or_inferred("clarify_priority", answers, inferred):
        questions.append(
            MissingQuestion(
                id="clarify_priority",
                question="What should Trace Labs prioritize when comparing options?",
                options=[
                    Option(label="Easy integration", value="Easiest integration"),
                    Option(label="Lowest power", value="Lowest power"),
                    Option(label="Lowest cost", value="Lowest cost"),
                    Option(label="Highest performance", value="Highest accuracy/performance"),
                ],
                default="Easiest integration",
            )
        )
    return questions[:3]


def _answer_or_inferred(input_id: str, answers: dict[str, str], inferred: dict[str, str]) -> str:
    return str(answers.get(input_id, "") or inferred.get(input_id, "")).strip()


def _category_context_from_message(message: str) -> dict[str, str]:
    text = message.lower()
    context: dict[str, str] = {}
    application = _extract_application_context(message)
    if not application and re.search(r"\b(?:time\s+of\s+flight|tof)\b", text):
        application = "distance/proximity sensing"
    if application:
        context["clarify_application"] = application
    for term, label in CATEGORY_INTERFACE_TERMS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text):
            context["clarify_interface_preference"] = label
            break
    voltage = _supply_voltage_from_text(message)
    if voltage:
        context["clarify_supply_voltage_v"] = voltage
    else:
        host_voltage = _host_supply_voltage(message)
        if host_voltage:
            context["clarify_supply_voltage_v"] = host_voltage
    for term, label in CATEGORY_PRIORITY_TERMS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text):
            context["clarify_priority"] = label
            break
    return context


def _extract_application_context(message: str) -> str:
    match = re.search(
        r"\b(?:for|in|inside|on)\s+(?:an?\s+|the\s+|my\s+)?([a-z0-9][a-z0-9 /\-]{2,80})",
        message,
        re.I,
    )
    if not match:
        return ""
    application = match.group(1).strip(" .?!,;:")
    if re.search(r"\b(?:kicad|what\s+are\s+my\s+options|options?)\b", application, re.I):
        return ""
    if re.fullmatch(r"(?:esp32|esp8266|stm32|rp2040|arduino|raspberry pi|rpi)(?:\s+project)?", application, re.I):
        return ""
    return application


def _supply_voltage_from_text(message: str) -> str:
    match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*V\b", message, re.I)
    if not match:
        return ""
    return f"{_normalised_positive_number(match.group(1))}V"


def _default_supply_voltage(message: str) -> str:
    return _host_supply_voltage(message) or "3.3V"


def _host_supply_voltage(message: str) -> str:
    text = message.lower()
    if any(term in text for term in ["esp32", "esp8266", "rp2040", "stm32", "nrf52", "raspberry pi", "rpi"]):
        return "3.3V"
    if any(term in text for term in ["arduino uno", "atmega328", "5v"]):
        return "5V"
    return ""


def _looks_like_converter_requirements_request(message: str, current_block, draft_block) -> bool:
    if current_block is not None or draft_block is not None:
        return False
    text = message.lower()
    if re.search(r"\b(?:what\s+is|what's|explain|how\s+does|how\s+do)\b", text):
        return False
    if not any(term in text for term in CONVERTER_REQUEST_TERMS):
        return False
    intent = analyse_part_intent(message)
    return intent.has_generation_intent or intent.has_exploratory_intent or intent.has_category_request


def _message_with_presearch_context(message: str, answers: dict[str, str]) -> str:
    requirements = _converter_requirements("", answers)
    notes = []
    vin = requirements.get("calc_input_voltage_v", "")
    vout = requirements.get("calc_output_voltage_v", "")
    current = requirements.get("calc_output_current_a", "")
    if vin and vout:
        notes.append(f"Requested conversion: {vin}V to {vout}V.")
    if current:
        notes.append(f"Requested output current: {current} A.")
    for input_id, label in CATEGORY_CLARIFICATION_INPUTS.items():
        value = str(answers.get(input_id, "")).strip()
        if not value:
            continue
        notes.append(f"{label.capitalize()}: {value}.")
    if not notes:
        return message
    return f"{message}\n\nRecommendation context:\n" + "\n".join(notes)


def _converter_requirements(message: str, answers: dict[str, str]) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for input_id in CONVERTER_CLARIFICATION_INPUTS:
        value = _normalised_positive_number(answers.get(input_id, ""))
        if value:
            requirements[input_id] = value

    vin, vout = _converter_voltage_pair(message)
    if vin and "calc_input_voltage_v" not in requirements:
        requirements["calc_input_voltage_v"] = vin
    if vout and "calc_output_voltage_v" not in requirements:
        requirements["calc_output_voltage_v"] = vout

    output_current = _converter_output_current(message)
    if output_current and "calc_output_current_a" not in requirements:
        requirements["calc_output_current_a"] = output_current
    return requirements


def _converter_voltage_pair(message: str) -> tuple[str, str]:
    patterns = [
        re.compile(
            r"\b(\d+(?:[.,]\d+)?)\s*V\s*(?:to|->|→|-)\s*(\d+(?:[.,]\d+)?)\s*V\b",
            re.I,
        ),
        re.compile(
            r"\bfrom\s+(\d+(?:[.,]\d+)?)\s*V\s+(?:to|down\s+to|up\s+to)\s+(\d+(?:[.,]\d+)?)\s*V\b",
            re.I,
        ),
    ]
    for pattern in patterns:
        match = pattern.search(message)
        if match:
            return _normalised_positive_number(match.group(1)), _normalised_positive_number(match.group(2))

    input_match = re.search(
        r"\b(?:vin|input|in|from)\s*(?:voltage)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*V\b|\b(\d+(?:[.,]\d+)?)\s*V\s*(?:in|input|vin)\b",
        message,
        re.I,
    )
    output_match = re.search(
        r"\b(?:vout|output|out|to)\s*(?:voltage)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*V\b|\b(\d+(?:[.,]\d+)?)\s*V\s*(?:out|output|vout)\b",
        message,
        re.I,
    )
    vin = _normalised_positive_number(next((group for group in (input_match.groups() if input_match else []) if group), ""))
    vout = _normalised_positive_number(next((group for group in (output_match.groups() if output_match else []) if group), ""))
    return vin, vout


def _converter_output_current(message: str) -> str:
    match = re.search(
        r"\b(\d+(?:[.,]\d+)?)\s*(mA|A|amps?|milliamps?)\b",
        message,
        re.I,
    )
    if not match:
        return ""
    value = _normalised_positive_number(match.group(1))
    if not value:
        return ""
    numeric = float(value)
    unit = match.group(2).lower()
    if unit in {"ma", "milliamp", "milliamps"}:
        numeric /= 1000.0
    return f"{numeric:g}"


def _normalised_positive_number(value: str) -> str:
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    if not match:
        return ""
    try:
        numeric = float(match.group(0).replace(",", "."))
    except ValueError:
        return ""
    if numeric <= 0:
        return ""
    return f"{numeric:g}"


def _part_choice_question(decision: AIChatDecision) -> MissingQuestion:
    supported = [item for item in decision.suggestions if item.status == "supported" and item.recipe_id]
    if not supported:
        supported = [
            AISuggestion(
                recipe_id="bme280_i2c",
                label="Bosch BME280 over I2C",
                reason="Supported local recipe with deterministic KiCad export.",
            )
        ]
    return MissingQuestion(
        id="part_choice",
        question="Which supported part should Trace Labs use?",
        options=[Option(label=item.label, value=item.recipe_id) for item in supported],
        default=supported[0].recipe_id,
    )


def _part_choice_question_from_datasheets(
    result: DatasheetSearchResponse,
    decision: AIChatDecision,
    request_message: str = "",
) -> MissingQuestion | None:
    options = []
    for candidate in result.candidates:
        candidate = _candidate_with_request_context(candidate, request_message)
        if candidate.supported_recipe_id:
            value = candidate.supported_recipe_id
        else:
            value = encode_candidate_choice(candidate)
        options.append(Option(label=f"{candidate.manufacturer} {candidate.part_number}", value=value))
    if not options and decision.suggestions:
        return _part_choice_question(decision)
    if not options:
        return None
    return MissingQuestion(
        id="part_choice",
        question="Which part should Trace Labs use?",
        options=options,
        default=options[0].value,
    )


def _looks_like_new_part_request(
    message: str,
    current_block,
    draft_block,
) -> bool:
    if current_block is not None or draft_block is not None:
        return False
    intent = analyse_part_intent(message)
    return bool(intent.target_part_numbers) and (
        intent.has_generation_intent or intent.has_category_request
    )


def _normalise_part(value: str) -> str:
    return normalise_part_number(value)


def _candidate_for_direct_draft(
    message: str,
    result: DatasheetSearchResponse,
    extra_target_parts: list[str] | None = None,
) -> DatasheetCandidate | None:
    requested_parts = {
        _normalise_part(part)
        for part in [*extract_target_part_numbers(message), *(extra_target_parts or [])]
        if part
    }
    if not requested_parts:
        return None

    for candidate in result.candidates:
        if _normalise_part(candidate.part_number) in requested_parts:
            return candidate
    return None


def _draft_response_from_candidate(
    candidate: DatasheetCandidate,
    result: DatasheetSearchResponse,
    assistant_message: str,
    request_message: str = "",
) -> ChatResponse:
    candidate = _candidate_with_request_context(candidate, request_message)
    if candidate.supported_recipe_id:
        try:
            draft = generator.draft(candidate.supported_recipe_id)
            return ChatResponse(
                assistant_message=assistant_message,
                draft_block=draft,
                missing_questions=draft.missing_questions,
                project_context=default_project_context(),
                warnings=draft.validation_warnings,
                next_steps=draft.next_steps,
                datasheet_results=result,
            )
        except ValueError:
            pass

    job = _job_with_ready_draft(extraction_service.start(candidate))
    if job.status == "ready" and "cached" in job.message.lower():
        extraction_message = (
            f"{assistant_message}\n\n"
            f"{job.message} Review the cached circuit before Trace Labs generates KiCad insertion files."
        )
    else:
        extraction_message = (
            f"{assistant_message}\n\n"
            f"I started datasheet/reference-design extraction for {candidate.manufacturer} {candidate.part_number}. "
            "Trace Labs will not generate insertion files until it has cited pins, support components, and CAD assets."
        )
    return ChatResponse(
        assistant_message=extraction_message,
        draft_block=None,
        missing_questions=[],
        project_context=default_project_context(),
        datasheet_results=result,
        extraction_job=job,
    )


def _candidate_with_request_context(candidate: DatasheetCandidate, message: str) -> DatasheetCandidate:
    notes = [*candidate.extraction_notes]
    voltage_match = re.search(
        r"\b(\d+(?:[.,]\d+)?)\s*V\s*(?:to|->|→|-)\s*(\d+(?:[.,]\d+)?)\s*V\b",
        message,
        re.I,
    )
    if voltage_match:
        notes.append(
            "Requested conversion: "
            f"{voltage_match.group(1).replace(',', '.')}V to {voltage_match.group(2).replace(',', '.')}V."
        )
    current_match = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(A|mA)\b", message, re.I)
    if current_match:
        value = float(current_match.group(1).replace(",", "."))
        if current_match.group(2).lower() == "ma":
            value = value / 1000.0
        notes.append(f"Requested output current: {value:g} A.")
    if notes == candidate.extraction_notes:
        return candidate
    return candidate.model_copy(update={"extraction_notes": list(dict.fromkeys(notes))})


def _draft_response_from_saved_recipe(
    message: str,
    assistant_message: str,
    extra_target_parts: list[str] | None = None,
) -> ChatResponse | None:
    target_parts = [
        *extract_target_part_numbers(message),
        *(extra_target_parts or []),
    ]
    draft = generator.saved_draft(target_parts)
    if draft is None:
        return None
    return ChatResponse(
        assistant_message=(
            f"{_short_chat_text(assistant_message)}\n\n"
            f"Loaded {draft.block_name} from the local component cache. "
            "Review the cached circuit confirmation before generating KiCad insertion files."
        ),
        draft_block=draft,
        missing_questions=draft.missing_questions,
        project_context=default_project_context(),
        warnings=draft.validation_warnings,
        next_steps=draft.next_steps,
    )


def _job_with_ready_draft(job: ComponentExtractionJobResponse) -> ComponentExtractionJobResponse:
    if job.status != "ready" or job.extraction is None or job.candidate is None:
        return job
    if job.draft_block is not None:
        return job
    job.draft_block = generator.ai_extracted_draft(
        job.extraction,
        supplier=job.candidate.supplier,
        supplier_part_number=job.candidate.supplier_part_number,
        supplier_url=job.candidate.supplier_url,
    )
    try:
        asset = writer.draft_library_assets.attach_preview_footprint(job.draft_block)
        if asset is not None:
            job.message = f"{job.message} Downloaded a KiCad footprint candidate for review."
        else:
            job.draft_block.validation_warnings.append(
                ValidationWarning(
                    severity="warning",
                    message="No downloaded KiCad footprint geometry is available for the preview.",
                    related_component="U?",
                    fix_hint="Verify the footprint in KiCad after export or choose a candidate with downloadable CAD assets.",
                )
            )
    except Exception as exc:
        job.draft_block.validation_warnings.append(
            ValidationWarning(
                severity="warning",
                message=f"KiCad footprint preview acquisition failed: {exc}",
                related_component="U?",
                fix_hint="Verify the footprint in KiCad after export before fabrication.",
            )
        )
    return job


def _datasheet_assistant_message(prefix: str, result: DatasheetSearchResponse) -> str:
    lines = [_short_chat_text(prefix)]
    if result.context_part_numbers:
        lines.append(f"Context: {', '.join(result.context_part_numbers)}.")

    if not result.candidates:
        lines.append("I could not find usable candidates from the current search. Try again once live search is available.")
        return "\n".join(line for line in lines if line)

    lines.append("Good options:")
    for candidate in result.candidates[:4]:
        traits = [_sentence_fragment(_short_chat_text(candidate.description, limit=130))]
        if candidate.complexity in {"moderate", "complex"}:
            traits.append(f"{candidate.complexity} integration")
        if candidate.supported_recipe_id:
            traits.append("verified local recipe")
        trait_text = _ensure_sentence_end("; ".join(item for item in traits if item))
        line = f"- {candidate.manufacturer} {candidate.part_number}: {trait_text}"
        lines.append(line)

    lines.append("Pick one below and Trace Labs will extract the cited sources before generating the schematic.")
    return "\n".join(lines)


def _short_chat_text(value: str, *, limit: int = 180) -> str:
    text = " ".join(value.split())
    if not text:
        return ""
    first_sentence_end = _first_sentence_end(text)
    if first_sentence_end is not None and first_sentence_end + 1 <= limit:
        return text[: first_sentence_end + 1].strip()
    if len(text) <= limit:
        return _ensure_sentence_end(text)
    return _trim_to_natural_boundary(text, limit)


def _first_sentence_end(text: str) -> int | None:
    for index in range(len(text)):
        if _is_sentence_boundary(text, index):
            return index
    return None


def _is_sentence_boundary(text: str, index: int) -> bool:
    if text[index] not in ".!?":
        return False
    if index + 1 < len(text) and not text[index + 1].isspace():
        return False
    abbreviations = {"e.g.", "i.e.", "etc.", "fig.", "inc.", "ltd.", "no.", "rev.", "vs."}
    token_start = text.rfind(" ", 0, index) + 1
    token = text[token_start : index + 1].lower()
    return token not in abbreviations


def _trim_to_natural_boundary(text: str, limit: int) -> str:
    if limit <= 1:
        return text[:limit].strip()
    window = text[:limit].rstrip()
    minimum = max(24, limit // 2)

    sentence_end = _last_sentence_end(window, minimum)
    if sentence_end is not None:
        return window[: sentence_end + 1].strip()

    for delimiter in ("; ", ": ", ", "):
        index = window.rfind(delimiter)
        if index >= minimum:
            return _ensure_sentence_end(window[:index])

    space_index = window.rfind(" ")
    if space_index >= minimum:
        return _ensure_sentence_end(window[:space_index])
    return _ensure_sentence_end(window)


def _last_sentence_end(text: str, minimum: int) -> int | None:
    for index in range(len(text) - 1, minimum - 1, -1):
        if _is_sentence_boundary(text, index):
            return index
    return None


def _ensure_sentence_end(text: str) -> str:
    cleaned = text.strip().rstrip(" ,;:-")
    if not cleaned or cleaned.endswith((".", "!", "?")):
        return cleaned
    return f"{cleaned}."


def _sentence_fragment(text: str) -> str:
    return text.strip().rstrip(".!?")


def _best_candidate_source(candidate: DatasheetCandidate):
    for source_type in ["manufacturer_datasheet", "reference_design", "application_note", "evaluation_board", "design_file"]:
        for source in candidate.datasheet_sources:
            if source.source_type == source_type and source.url:
                return source
    for source in candidate.datasheet_sources:
        if source.url:
            return source
    return candidate.datasheet_sources[0] if candidate.datasheet_sources else None


def _display_sources(candidate: DatasheetCandidate):
    ranked = sorted(candidate.datasheet_sources, key=_source_rank)
    shown = []
    for source in ranked:
        key = source.url or f"{source.title}:{source.source_type}"
        if key not in {item.url or f"{item.title}:{item.source_type}" for item in shown}:
            shown.append(source)
        if len(shown) >= 3:
            break
    return shown


def _source_rank(source) -> int:
    order = {
        "manufacturer_datasheet": 0,
        "reference_design": 1,
        "application_note": 2,
        "evaluation_board": 3,
        "design_file": 4,
        "manufacturer_product_page": 5,
        "distributor": 6,
    }
    return order.get(source.source_type, 9)


def _record_datasheet_usage(result: DatasheetSearchResponse) -> None:
    if result.token_count > 0:
        pricing.record(
            UsageEventRequest(
                event_type="ai_token.used",
                quantity=result.token_count,
                metadata={"model": ai_service.model, "action": "datasheet_search"},
            )
        )
    page_count = sum(len(candidate.datasheet_sources) for candidate in result.candidates)
    if page_count > 0:
        pricing.record(
            UsageEventRequest(
                event_type="datasheet_page.processed",
                quantity=page_count,
                metadata={"provider": result.provider, "live_search_used": result.live_search_used},
            )
        )
