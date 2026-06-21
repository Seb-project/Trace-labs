from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

ImportMode = Literal["hierarchical_sheet", "inline_main"]


class Option(BaseModel):
    label: str
    value: str


class MissingQuestion(BaseModel):
    id: str
    question: str
    type: Literal["select", "number", "text"] = "select"
    options: list[Option] = Field(default_factory=list)
    required: bool = True
    default: str
    depends_on: dict[str, str] = Field(default_factory=dict)


class Component(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    reference: str
    type: str
    value: str
    mpn: str | None = None
    manufacturer: str | None = None
    supplier: str | None = None
    supplier_part_number: str | None = None
    supplier_url: str | None = None
    symbol: str
    footprint: str
    model_3d: str | None = "needs_review"
    purpose: str
    connects: list[str] = Field(default_factory=list)
    footprint_confidence: str
    symbol_confidence: str
    assignment_reason: str
    status: str = "draft"
    footprint_asset: "FootprintAsset | None" = None


class FootprintAsset(BaseModel):
    name: str
    footprint_id: str = ""
    source_kind: str = ""
    source_project: str = ""
    source_path: str = ""
    source_url: str = ""
    confidence: str = "downloaded_needs_review"
    kicad_mod: str
    warnings: list[str] = Field(default_factory=list)


class SupportComponent(BaseModel):
    reference: str
    type: str
    value: str
    purpose: str
    symbol: str
    footprint: str
    footprint_confidence: str = "default_selected"
    symbol_confidence: str = "default_selected"
    connects: list[str] = Field(default_factory=list)
    assignment_reason: str = "Default selected from Trace Labs passive defaults."
    source_citations: list[str] = Field(default_factory=list)


class ValidationWarning(BaseModel):
    severity: Literal["info", "warning", "critical"]
    message: str
    related_component: str | None = None
    fix_hint: str | None = None


class NextStep(BaseModel):
    id: str
    category: str
    task: str
    required: bool = True
    status: Literal["todo", "done", "blocked"] = "todo"
    reason: str | None = None


class DatasheetSource(BaseModel):
    title: str
    source_type: str = "local_recipe"
    url: str = ""
    confidence: str = "local_recipe_verified"
    notes: str | None = None


class DatasheetCandidate(BaseModel):
    part_number: str
    manufacturer: str
    description: str
    supplier: str = ""
    supplier_part_number: str = ""
    supplier_url: str = ""
    supported_recipe_id: str = ""
    confidence: str
    complexity: Literal["simple", "moderate", "complex", "unknown"] = "unknown"
    source_coverage: list[str] = Field(default_factory=list)
    capability_notes: list[str] = Field(default_factory=list)
    datasheet_sources: list[DatasheetSource] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DatasheetSearchRequest(BaseModel):
    query: str
    include_unsupported: bool = True


class DatasheetSearchResponse(BaseModel):
    query: str
    live_search_used: bool = False
    provider: str = "local_fallback"
    summary: str
    target_part_number: str = ""
    context_part_numbers: list[str] = Field(default_factory=list)
    search_audit: list[str] = Field(default_factory=list)
    candidates: list[DatasheetCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    token_count: int = 0


class SourceChunk(BaseModel):
    chunk_id: str
    source_url: str
    title: str = ""
    page: int | None = None
    text: str


class PinDefinition(BaseModel):
    number: str
    name: str
    electrical_type: str = "passive"
    net_name: str
    required: bool = True
    notes: str = ""
    source_citations: list[str] = Field(default_factory=list)


class SupportRequirement(BaseModel):
    reference_prefix: str
    type: str
    value: str
    purpose: str
    connects: list[str]
    footprint: str = ""
    required: bool = True
    placement_note: str = ""
    source_citations: list[str] = Field(default_factory=list)
    calculation_role: str = ""
    calculation_inputs: list[str] = Field(default_factory=list)
    calculation_formula: str = ""


class CircuitNet(BaseModel):
    name: str
    role: Literal["power", "ground", "interface", "reset", "interrupt", "configuration", "internal", "other"] = "other"
    external: bool = False
    connected_pins: list[str] = Field(default_factory=list)
    notes: str = ""


class ReferenceCircuitExtraction(BaseModel):
    part_number: str
    manufacturer: str
    package: str = ""
    supply_range: str = ""
    interface: str = ""
    pins: list[PinDefinition] = Field(default_factory=list)
    support_requirements: list[SupportRequirement] = Field(default_factory=list)
    nets: list[CircuitNet] = Field(default_factory=list)
    source_chunks: list[SourceChunk] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    unanswered_questions: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    extraction_notes: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class ComponentExtractionStartRequest(BaseModel):
    candidate: DatasheetCandidate | None = None
    choice_value: str | None = None


class ComponentExtractionJobResponse(BaseModel):
    job_id: str
    status: Literal[
        "queued",
        "fetching_sources",
        "sources_found",
        "extracting",
        "acquiring_cad",
        "validating",
        "ready",
        "failed",
    ]
    progress: float = 0.0
    message: str = ""
    candidate: DatasheetCandidate | None = None
    extraction: ReferenceCircuitExtraction | None = None
    draft_block: "CircuitBlock | None" = None
    errors: list[str] = Field(default_factory=list)


class SchematicPreview(BaseModel):
    title: str
    description: str
    ascii_preview: str
    connections: list[str]
    notes: list[str] = Field(default_factory=list)


class UsageEvent(BaseModel):
    reference: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    event_type: str
    quantity: float = 1
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    account_id: str = "local-dev"
    solvimon_sync_status: Literal["not_configured", "pending", "synced", "failed"] = "not_configured"
    solvimon_synced_at: str | None = None
    solvimon_error: str | None = None


class PricingPreview(BaseModel):
    plan_name: str = "Maker"
    monthly_price: float = 12.0
    included_blocks: int = 50
    used_blocks: int = 0
    remaining_blocks: int = 50
    overage_rate: float = 0.20
    estimated_overage: float = 0.0
    estimated_monthly_bill: float = 12.0
    recent_events: list[UsageEvent] = Field(default_factory=list)
    message: str = (
        "This generation recorded 1 circuit block and 1 KiCad export. "
        "On the Maker plan, 49 included blocks remain. Estimated bill impact: GBP 0.00."
    )


class AccountProfile(BaseModel):
    account_id: str = "local-dev"
    display_name: str = "Local developer"
    email: str = ""
    status: Literal["local", "active"] = "local"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    solvimon_customer_reference: str = ""
    solvimon_subscription_reference: str = ""


class BillingIntegrationStatus(BaseModel):
    provider: Literal["solvimon"] = "solvimon"
    mode: Literal["disabled", "test", "live"] = "disabled"
    configured: bool = False
    customer_reference: str = ""
    subscription_reference: str = ""
    meter_references: dict[str, str] = Field(default_factory=dict)
    last_sync_status: Literal["not_configured", "synced", "failed"] = "not_configured"
    last_synced_at: str | None = None
    last_error: str | None = None
    setup_required: list[str] = Field(default_factory=list)


class AccountOverview(BaseModel):
    account: AccountProfile
    pricing_preview: PricingPreview
    billing: BillingIntegrationStatus


class BillingPortalResponse(BaseModel):
    available: bool = False
    message: str
    actions: list[str] = Field(default_factory=list)


class CircuitBlock(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    block_name: str
    block_slug: str
    summary: str
    main_component: Component
    support_components: list[SupportComponent]
    external_nets: list[str]
    internal_nets: list[str] = Field(default_factory=list)
    assumptions: list[str]
    missing_questions: list[MissingQuestion]
    validation_warnings: list[ValidationWarning]
    next_steps: list[NextStep]
    datasheet_sources: list[DatasheetSource]
    schematic_preview: SchematicPreview
    usage_events: list[UsageEvent] = Field(default_factory=list)
    selected_options: dict[str, str] = Field(default_factory=dict)
    status: Literal["draft", "awaiting_answers", "final", "exported", "error"] = "draft"
    recipe_source: Literal["local_verified", "ai_proposed", "saved_draft"] = "local_verified"
    recipe_status: Literal["verified", "needs_review", "draft"] = "verified"
    recipe_review_confirmed: bool = False
    recipe_saved_path: str | None = None
    extraction_status: Literal["not_required", "pending", "ready", "failed"] = "not_required"
    reference_extraction: ReferenceCircuitExtraction | None = None


class RecipeSummary(BaseModel):
    id: str
    display_name: str
    manufacturer: str
    mpn: str
    interface: str


class ProjectContext(BaseModel):
    project_name: str = "weather_station.kicad_pro"
    connected: bool = True
    available_nets: list[str] = Field(default_factory=lambda: ["+3V3", "GND", "I2C1_SDA", "I2C1_SCL"])
    detected_mcu: str = "STM32L072"
    kicad_bridge_status: str = "mocked"


class HealthResponse(BaseModel):
    status: str = "ok"
    app_name: str = "Trace Labs"
    project_name: str = "weather_station.kicad_pro"
    kicad_bridge_status: str = "mocked"


class ChatRequest(BaseModel):
    message: str
    draft_block: CircuitBlock | None = None
    current_block: CircuitBlock | None = None
    answers: dict[str, str] = Field(default_factory=dict)
    history: list[dict[str, str]] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    prompt: str
    known_values: dict[str, str] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    assistant_message: str
    draft_block: CircuitBlock | None = None
    missing_questions: list[MissingQuestion] = Field(default_factory=list)
    project_context: ProjectContext
    warnings: list[ValidationWarning] = Field(default_factory=list)
    next_steps: list[NextStep] = Field(default_factory=list)
    datasheet_results: DatasheetSearchResponse | None = None
    extraction_job: ComponentExtractionJobResponse | None = None


class AnswerQuestionsRequest(BaseModel):
    answers: dict[str, str]
    draft_block: CircuitBlock | None = None


class ExportRequest(BaseModel):
    block: CircuitBlock


class ExportResponse(BaseModel):
    success: bool
    message: str
    output_directory: str
    files: dict[str, str]
    pricing_preview: PricingPreview
    bridge_action_note: str
    block: CircuitBlock


class UsageEventRequest(BaseModel):
    reference: str | None = None
    event_type: str
    quantity: float = 1
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str | None = None


class BridgeLinkRequest(BaseModel):
    project_path: str
    project_name: str | None = None
    schematic_path: str | None = None
    bridge_mode: str = "mock"
    available_nets: list[str] = Field(default_factory=lambda: ["+3V3", "GND", "I2C1_SDA", "I2C1_SCL"])
    detected_mcu: str = "STM32L072"
    kicad_version: str | None = None


class BridgeLinkRecord(BaseModel):
    link_id: str = Field(default_factory=lambda: str(uuid4()))
    project_path: str
    project_name: str
    schematic_path: str
    bridge_mode: str
    available_nets: list[str]
    detected_mcu: str
    kicad_version: str | None = None
    connected: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BridgeImportRequest(BaseModel):
    link_id: str | None = None
    generated_block_dir: str
    import_mode: ImportMode = "hierarchical_sheet"
    open_after_import: bool = False


class BridgeImportResponse(BaseModel):
    success: bool
    mode: ImportMode
    import_status: str
    project_path: str
    root_schematic: str
    opened_sheet_path: str | None = None
    open_error: str | None = None
    imported_directory: str
    copied_files: list[str]
    modified_files: list[str]
    backups: list[str]
    message: str
    next_steps: list[str]


class BackendError(BaseModel):
    message: str
    warnings: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
