from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .ai_service import AIChatDecision, AISuggestion, PCBStreamAIService
from .bridge_ops import BridgeService
from .component_extraction import decode_candidate_choice, encode_candidate_choice, ComponentExtractionService
from .generator import CircuitGenerator, RecipeLoader, default_project_context
from .kicad_writer import KiCadWriter
from .models import (
    AnswerQuestionsRequest,
    BackendError,
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
)
from .part_intent import analyse_part_intent, extract_target_part_numbers, normalise_part_number
from .pricing import MockSolvimonService
from .settings import load_local_env


ROOT = Path(__file__).resolve().parents[2]
load_local_env(ROOT)
DATA_DIR = ROOT / ".pcbstream"
loader = RecipeLoader(ROOT / "backend" / "recipes")
generator = CircuitGenerator(loader)
pricing = MockSolvimonService(DATA_DIR)
writer = KiCadWriter(ROOT / "generated_blocks")
bridge = BridgeService(DATA_DIR)
ai_service = PCBStreamAIService()
extraction_service = ComponentExtractionService(ai_service)

app = FastAPI(title="PCBStream Backend", version="0.1.0")
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
                next_steps=["Select the part again so PCBStream can run datasheet/reference-design extraction."],
            ).model_dump(),
        )

    decision = ai_service.decide(
        request.message,
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
        datasheet_result = ai_service.search_datasheets(
            request.message,
            available_recipes=loader.summaries(),
            include_unsupported=True,
        )
        _record_datasheet_usage(datasheet_result)
        assistant_message = _datasheet_assistant_message(decision.assistant_message, datasheet_result)
        direct_candidate = _candidate_for_direct_draft(
            request.message,
            datasheet_result,
            [decision.target_part_number] if decision.target_part_number else [],
        )
        if direct_candidate:
            return _draft_response_from_candidate(
                direct_candidate,
                datasheet_result,
                assistant_message,
            )
        part_question = _part_choice_question_from_datasheets(datasheet_result, decision)
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
        datasheet_result = ai_service.search_datasheets(
            request.message,
            available_recipes=loader.summaries(),
            include_unsupported=True,
        )
        _record_datasheet_usage(datasheet_result)
        candidate = _candidate_for_direct_draft(
            request.message,
            datasheet_result,
            [decision.target_part_number] if decision.target_part_number else [],
        )
        if candidate:
            return _draft_response_from_candidate(
                candidate,
                datasheet_result,
                _datasheet_assistant_message(decision.assistant_message, datasheet_result),
            )
        part_question = _part_choice_question_from_datasheets(datasheet_result, decision)
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
                message="PCBStream can only generate verified local recipes or reviewed AI-proposed drafts.",
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
    )


@app.post("/usage-event")
def usage_event(request: UsageEventRequest):
    event = pricing.record(request)
    return {"event": event, "pricing_preview": pricing.preview()}


@app.get("/pricing-preview", response_model=PricingPreview)
def pricing_preview() -> PricingPreview:
    return pricing.preview()


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
        question="Which supported part should PCBStream use?",
        options=[Option(label=item.label, value=item.recipe_id) for item in supported],
        default=supported[0].recipe_id,
    )


def _part_choice_question_from_datasheets(
    result: DatasheetSearchResponse,
    decision: AIChatDecision,
) -> MissingQuestion | None:
    options = []
    for candidate in result.candidates:
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
        question="Which part should PCBStream use?",
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
) -> ChatResponse:
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

    job = extraction_service.start(candidate)
    return ChatResponse(
        assistant_message=(
            f"{assistant_message}\n\n"
            f"I started datasheet/reference-design extraction for {candidate.manufacturer} {candidate.part_number}. "
            "PCBStream will not generate insertion files until it has cited pins, support components, and CAD assets."
        ),
        draft_block=None,
        missing_questions=[],
        project_context=default_project_context(),
        datasheet_results=result,
        extraction_job=_job_with_ready_draft(job),
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
        traits = [_short_chat_text(candidate.description, limit=130)]
        if candidate.complexity in {"moderate", "complex"}:
            traits.append(f"{candidate.complexity} integration")
        if candidate.supported_recipe_id:
            traits.append("verified local recipe")
        line = f"- {candidate.manufacturer} {candidate.part_number}: {'; '.join(item for item in traits if item)}"
        lines.append(line)

    lines.append("Pick one below and PCBStream will extract the cited sources before generating the schematic.")
    return "\n".join(lines)


def _short_chat_text(value: str, *, limit: int = 180) -> str:
    text = " ".join(value.split())
    if not text:
        return ""
    sentence = text.split(". ", 1)[0].strip()
    if len(sentence) > limit:
        sentence = f"{sentence[: limit - 3].rstrip()}..."
    return sentence


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
