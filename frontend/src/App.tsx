import {
  Check,
  ChevronDown,
  ChevronLeft,
  Cpu,
  CreditCard,
  ExternalLink,
  Home,
  Info,
  Link,
  ListFilter,
  Menu,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  Trash2,
  UserRound,
  X
} from "lucide-react";
import {
  CSSProperties,
  FormEvent,
  KeyboardEvent,
  PointerEvent,
  ReactNode,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  WheelEvent
} from "react";
import { createPortal } from "react-dom";
import traceLabsLogoUrl from "../logo.svg";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8765";
const PART_LIBRARY_STORAGE_KEY = "tracelabs.partLibrary.v3";
const PART_LIBRARY_LEGACY_KEY = "pcbstream.partLibrary.v3";
const USER_PREFERENCES_STORAGE_KEY = "tracelabs.userPreferences.v1";
const EXTRACT_CANDIDATE_PREFIX = "extract_candidate::";
const EXTRACTION_POLL_INTERVAL_MS = 600;
const EXTRACTION_TIMEOUT_MS = 180000;
const ASSISTANT_TYPE_INTERVAL_MS = 10;
const ASSISTANT_TYPE_CHARS_PER_TICK = 2;
const SCHEMATIC_MIN_ZOOM = 0.65;
const SCHEMATIC_MAX_ZOOM = 3.4;
const SCHEMATIC_ZOOM_STEP = 1.18;

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

type Option = {
  label: string;
  value: string;
};

type MissingQuestion = {
  id: string;
  question: string;
  type: "select" | "number" | "text";
  options: Option[];
  required: boolean;
  default: string;
  depends_on: Record<string, string>;
};

type Component = {
  reference: string;
  type: string;
  value: string;
  mpn?: string;
  manufacturer?: string;
  supplier?: string;
  supplier_part_number?: string;
  supplier_url?: string;
  symbol: string;
  footprint: string;
  model_3d?: string;
  purpose: string;
  connects: string[];
  footprint_confidence: string;
  symbol_confidence: string;
  assignment_reason: string;
  status: string;
  footprint_asset?: FootprintAsset | null;
};

type FootprintAsset = {
  name: string;
  footprint_id: string;
  source_kind: string;
  source_project: string;
  source_path: string;
  source_url: string;
  confidence: string;
  kicad_mod: string;
  warnings: string[];
};

type SupportComponent = {
  reference: string;
  type: string;
  value: string;
  supplier?: string;
  supplier_part_number?: string;
  supplier_url?: string;
  purpose: string;
  symbol: string;
  footprint: string;
  footprint_confidence: string;
  symbol_confidence: string;
  connects: string[];
  assignment_reason: string;
  source_citations?: string[];
};

type ValidationWarning = {
  severity: "info" | "warning" | "critical";
  message: string;
  related_component?: string;
  fix_hint?: string;
};

type NextStep = {
  id: string;
  category: string;
  task: string;
  required: boolean;
  status: "todo" | "done" | "blocked";
  reason?: string;
};

type DatasheetSource = {
  title: string;
  source_type: string;
  url: string;
  confidence: string;
  notes?: string;
};

type DatasheetCandidate = {
  part_number: string;
  manufacturer: string;
  description: string;
  supplier: string;
  supplier_part_number: string;
  supplier_url: string;
  supported_recipe_id: string;
  confidence: string;
  complexity: "simple" | "moderate" | "complex" | "unknown";
  source_coverage: string[];
  capability_notes: string[];
  datasheet_sources: DatasheetSource[];
  extraction_notes: string[];
  warnings: string[];
};

type DatasheetSearchResponse = {
  query: string;
  live_search_used: boolean;
  provider: string;
  summary: string;
  target_part_number: string;
  context_part_numbers: string[];
  search_audit: string[];
  candidates: DatasheetCandidate[];
  warnings: string[];
  token_count: number;
};

type SourceChunk = {
  chunk_id: string;
  source_url: string;
  title: string;
  page?: number | null;
  text: string;
};

type PinDefinition = {
  number: string;
  name: string;
  electrical_type: string;
  net_name: string;
  required: boolean;
  notes: string;
  source_citations: string[];
};

type SupportRequirement = {
  reference_prefix: string;
  type: string;
  value: string;
  purpose: string;
  connects: string[];
  footprint: string;
  required: boolean;
  placement_note: string;
  source_citations: string[];
};

type CircuitNet = {
  name: string;
  role: "power" | "ground" | "interface" | "reset" | "interrupt" | "configuration" | "internal" | "other";
  external: boolean;
  connected_pins: string[];
  notes: string;
};

type ReferenceCircuitExtraction = {
  part_number: string;
  manufacturer: string;
  package: string;
  supply_range: string;
  interface: string;
  pins: PinDefinition[];
  support_requirements: SupportRequirement[];
  nets: CircuitNet[];
  source_chunks: SourceChunk[];
  source_urls: string[];
  unanswered_questions: string[];
  validation_warnings: string[];
  extraction_notes: string[];
  confidence: "high" | "medium" | "low";
};

type SchematicPreview = {
  title: string;
  description: string;
  ascii_preview: string;
  connections: string[];
  notes: string[];
};

type UsageEvent = {
  reference?: string;
  event_type: string;
  quantity: number;
  metadata: Record<string, unknown>;
  timestamp: string;
};

type PricingPreview = {
  plan_name: string;
  monthly_price: number;
  included_blocks: number;
  used_blocks: number;
  remaining_blocks: number;
  overage_rate: number;
  estimated_overage: number;
  estimated_monthly_bill: number;
  recent_events: UsageEvent[];
  message: string;
};

type PreviewMode = "schematic" | "footprint";

type AccountProfile = {
  account_id: string;
  display_name: string;
  email: string;
  status: "local" | "active";
  created_at: string;
  solvimon_customer_reference: string;
  solvimon_subscription_reference: string;
};

type BillingIntegrationStatus = {
  provider: "solvimon";
  mode: "disabled" | "test" | "live";
  configured: boolean;
  customer_reference: string;
  subscription_reference: string;
  meter_references: Record<string, string>;
  last_sync_status: "not_configured" | "synced" | "failed";
  last_synced_at?: string | null;
  last_error?: string | null;
  setup_required: string[];
};

type AccountOverview = {
  account: AccountProfile;
  pricing_preview: PricingPreview;
  billing: BillingIntegrationStatus;
};

type CircuitBlock = {
  id: string;
  block_name: string;
  block_slug: string;
  summary: string;
  main_component: Component;
  support_components: SupportComponent[];
  external_nets: string[];
  internal_nets: string[];
  assumptions: string[];
  missing_questions: MissingQuestion[];
  validation_warnings: ValidationWarning[];
  next_steps: NextStep[];
  datasheet_sources: DatasheetSource[];
  schematic_preview: SchematicPreview;
  usage_events: UsageEvent[];
  selected_options: Record<string, string>;
  status: "draft" | "awaiting_answers" | "final" | "exported" | "error";
  recipe_source: "local_verified" | "ai_proposed" | "saved_draft";
  recipe_status: "verified" | "needs_review" | "draft";
  recipe_review_confirmed: boolean;
  recipe_saved_path?: string | null;
  extraction_status?: "not_required" | "pending" | "ready" | "failed";
  reference_extraction?: ReferenceCircuitExtraction | null;
};

export type ComponentExtractionJob = {
  job_id: string;
  status:
    | "queued"
    | "fetching_sources"
    | "sources_found"
    | "extracting"
    | "acquiring_cad"
    | "validating"
    | "ready"
    | "failed";
  progress: number;
  message: string;
  candidate?: DatasheetCandidate | null;
  extraction?: ReferenceCircuitExtraction | null;
  draft_block?: CircuitBlock | null;
  errors: string[];
};

type ChatResponse = {
  assistant_message: string;
  draft_block: CircuitBlock | null;
  missing_questions: MissingQuestion[];
  warnings: ValidationWarning[];
  next_steps: NextStep[];
  datasheet_results?: DatasheetSearchResponse | null;
  extraction_job?: ComponentExtractionJob | null;
};

type HealthResponse = {
  status: string;
  app_name: string;
  project_name: string;
  kicad_bridge_status: string;
};

type ExportResponse = {
  success: boolean;
  message: string;
  output_directory: string;
  files: Record<string, string>;
  pricing_preview: PricingPreview;
  bridge_action_note: string;
  block: CircuitBlock;
};

type BridgeLinkRecord = {
  link_id: string;
  project_path: string;
  project_name: string;
  schematic_path: string;
  connected: boolean;
};

type BridgeStatus = {
  connected: boolean;
  project_path?: string;
  project_name?: string;
  schematic_path?: string;
  kicad_bridge_status: string;
};

type ImportMode = "hierarchical_sheet" | "inline_main";

type BridgeImportResponse = {
  success: boolean;
  mode: ImportMode;
  import_status: string;
  project_path: string;
  root_schematic: string;
  opened_sheet_path?: string;
  open_error?: string;
  imported_directory: string;
  copied_files: string[];
  modified_files: string[];
  backups: string[];
  message: string;
  next_steps: string[];
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  animate?: boolean;
};

function initialChatMessages(): ChatMessage[] {
  return [
    {
      id: `welcome-${Date.now()}`,
      role: "assistant",
      animate: false,
      text:
        "Open a KiCad project beside Trace Labs, then ask for the part or circuit block you want to add."
    }
  ];
}

type ToastMessage = {
  id: string;
  title: string;
  details: string[];
  expanded: boolean;
  held: boolean;
  leaving: boolean;
};

type PartLibraryEntry = {
  id: string;
  blockId: string;
  title: string;
  summary: string;
  createdAt: string;
  updatedAt: string;
  block: CircuitBlock;
  answers: Record<string, string>;
  messages: ChatMessage[];
  nextStepChecks?: Record<string, boolean>;
};

type EditableAnswerId = "logic_voltage" | "interface_mode" | "i2c_address" | "pullups" | "pullup_value";

type AnswerSummaryItem = {
  id: EditableAnswerId;
  label: string;
  value: string;
  options: Option[];
};

type PackagePreferenceId = "0402" | "0603" | "0805" | "1206";

type PassiveKind = "resistor" | "capacitor";

type UserPreferences = {
  standardPackageSize: PackagePreferenceId;
};

type ComponentTableRow = {
  key: string;
  reference: string;
  component: Component | SupportComponent;
  supportIndex?: number;
  supportKind: "main" | "support";
};

type PartLibraryFilterId = "all" | "logic_3v3" | "logic_1v8" | "i2c" | "spi";

const PART_LIBRARY_FILTERS: Array<{
  id: PartLibraryFilterId;
  label: string;
  tokens: string[];
}> = [
  { id: "all", label: "All", tokens: [] },
  { id: "logic_3v3", label: "3.3V", tokens: ["3.3v", "3v3", "+3v3"] },
  { id: "logic_1v8", label: "1.8V", tokens: ["1.8v", "1v8", "+1v8"] },
  { id: "i2c", label: "I2C", tokens: ["i2c"] },
  { id: "spi", label: "SPI", tokens: ["spi"] }
];

const GENERIC_LIBRARY_QUERY_WORDS = new Set(["component", "components", "part", "parts", "saved"]);

const PASSIVE_PACKAGE_OPTIONS: Array<{
  id: PackagePreferenceId;
  label: string;
  metric: string;
}> = [
  { id: "0402", label: "0402", metric: "1005 metric" },
  { id: "0603", label: "0603", metric: "1608 metric" },
  { id: "0805", label: "0805", metric: "2012 metric" },
  { id: "1206", label: "1206", metric: "3216 metric" }
];

const DEFAULT_USER_PREFERENCES: UserPreferences = {
  standardPackageSize: "0603"
};

const EDITABLE_ANSWER_FIELDS: Array<{
  id: EditableAnswerId;
  label: string;
  defaultValue: string;
  options: Option[];
}> = [
  {
    id: "logic_voltage",
    label: "Logic",
    defaultValue: "3.3V",
    options: [
      { label: "1.8V", value: "1.8V" },
      { label: "3.3V", value: "3.3V" }
    ]
  },
  {
    id: "interface_mode",
    label: "Interface",
    defaultValue: "I2C",
    options: [
      { label: "I2C", value: "I2C" },
      { label: "SPI", value: "SPI" }
    ]
  },
  {
    id: "i2c_address",
    label: "Address",
    defaultValue: "0x76",
    options: [
      { label: "0x76", value: "0x76" },
      { label: "0x77", value: "0x77" }
    ]
  },
  {
    id: "pullups",
    label: "Pull-ups",
    defaultValue: "add",
    options: [
      { label: "Add 4.7k", value: "add" },
      { label: "Board has them", value: "skip" }
    ]
  },
  {
    id: "pullup_value",
    label: "Pull-up value",
    defaultValue: "4.7 kOhm",
    options: [
      { label: "4.7 kOhm", value: "4.7 kOhm" },
      { label: "Not sure / TBD", value: "unspecified" }
    ]
  }
];

function chatHistoryPayload(messages: ChatMessage[]) {
  return messages.slice(-8).map((message) => ({
    role: message.role,
    content: message.text
  }));
}

function normalizeChatMessage(message: ChatMessage): ChatMessage {
  return { ...message, animate: false };
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message =
        body?.detail?.message ??
        body?.detail?.[0]?.msg ??
        body?.message ??
        JSON.stringify(body);
    } catch {
      message = await response.text();
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

function loadPartLibrary(): PartLibraryEntry[] {
  if (typeof window === "undefined") return [];

  try {
    const stored = window.localStorage.getItem(PART_LIBRARY_STORAGE_KEY) ||
      window.localStorage.getItem(PART_LIBRARY_LEGACY_KEY);
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    const entries = parsed
      .filter((entry): entry is PartLibraryEntry =>
        Boolean(entry?.id && entry?.block?.block_name && Array.isArray(entry?.messages))
      )
      .map(normalizePartLibraryEntry);
    if (entries.length && !window.localStorage.getItem(PART_LIBRARY_STORAGE_KEY)) {
      try {
        window.localStorage.setItem(PART_LIBRARY_STORAGE_KEY, JSON.stringify(entries));
        window.localStorage.removeItem(PART_LIBRARY_LEGACY_KEY);
      } catch {
        // Migration is best effort
      }
    }
    return entries;
  } catch {
    return [];
  }
}

function persistPartLibrary(entries: PartLibraryEntry[]) {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(
      PART_LIBRARY_STORAGE_KEY,
      JSON.stringify(entries.map(normalizePartLibraryEntry))
    );
  } catch {
    // Local storage is best effort; the generated block still remains active in the UI.
  }
}

function loadUserPreferences(): UserPreferences {
  if (typeof window === "undefined") return DEFAULT_USER_PREFERENCES;

  try {
    const stored = window.localStorage.getItem(USER_PREFERENCES_STORAGE_KEY);
    if (!stored) return DEFAULT_USER_PREFERENCES;
    const parsed = JSON.parse(stored);
    const preferredPackage = parsed?.standardPackageSize;
    if (PASSIVE_PACKAGE_OPTIONS.some((option) => option.id === preferredPackage)) {
      return { standardPackageSize: preferredPackage };
    }
  } catch {
    // Preference storage is best effort. Defaults keep the generated block exportable.
  }

  return DEFAULT_USER_PREFERENCES;
}

function persistUserPreferences(preferences: UserPreferences) {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(USER_PREFERENCES_STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // Preference storage is best effort. The active block still carries the selected footprints.
  }
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP"
  }).format(value);
}

function isHttpUrl(value?: string) {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function logicNetForOptions(options: Record<string, string>) {
  return options.logic_voltage === "1.8V" ? "+1V8" : "+3V3";
}

function optionLabelForAnswer(id: EditableAnswerId, value: string) {
  return (
    EDITABLE_ANSWER_FIELDS.find((field) => field.id === id)?.options.find(
      (option) => option.value === value
    )?.label ?? value
  );
}

function answerSummaryItems(block: CircuitBlock): AnswerSummaryItem[] {
  return EDITABLE_ANSWER_FIELDS.filter(
    (field) =>
      !(field.id === "pullup_value" && block.selected_options.pullups === "skip") &&
      (block.block_slug === "bme280_i2c" || block.selected_options[field.id] !== undefined)
  ).map((field) => {
    const value = block.selected_options[field.id] ?? field.defaultValue;
    return {
      id: field.id,
      label: field.label,
      options: field.options,
      value: optionLabelForAnswer(field.id, value)
    };
  });
}

function displayedAnswerValue(value: string) {
  return value === "unspecified" ? "TBD" : value;
}

function compactPassiveValue(value: string) {
  const displayed = displayedAnswerValue(value);
  if (displayed.toLowerCase().includes("strap")) return "0R";
  return displayed.replace(/\s*kOhm/i, "k").replace(/\s*Ohm/i, "R");
}

function passiveKindForComponent(component: Component | SupportComponent): PassiveKind | null {
  const type = component.type.toLowerCase();
  const symbol = component.symbol.toLowerCase();
  if (type.includes("resistor") || symbol === "device:r") return "resistor";
  if (type.includes("capacitor") || symbol === "device:c" || symbol === "device:cp") {
    return "capacitor";
  }
  return null;
}

function passiveFootprint(kind: PassiveKind, packageSize: PackagePreferenceId) {
  const metricByPackage: Record<PackagePreferenceId, string> = {
    "0402": "1005Metric",
    "0603": "1608Metric",
    "0805": "2012Metric",
    "1206": "3216Metric"
  };
  const prefix = kind === "resistor" ? "Resistor_SMD:R" : "Capacitor_SMD:C";
  return `${prefix}_${packageSize}_${metricByPackage[packageSize]}`;
}

function packageSizeFromFootprint(footprint: string): PackagePreferenceId | null {
  const match = footprint.match(/(?:^|[:_])(?:R|C)?_?(0402|0603|0805|1206)(?:_|$)/i);
  return (match?.[1] as PackagePreferenceId | undefined) ?? null;
}

function componentPackageLabel(component: Component | SupportComponent) {
  return packageSizeFromFootprint(component.footprint) ?? "Custom";
}

function applyStandardPackagePreference(
  block: CircuitBlock,
  preferences: UserPreferences
): CircuitBlock {
  const supportComponents = block.support_components.map((component) => {
    const kind = passiveKindForComponent(component);
    if (!kind) return component;
    const footprint = passiveFootprint(kind, preferences.standardPackageSize);
    if (component.footprint === footprint) return component;
    return {
      ...component,
      footprint,
      footprint_confidence: "default_selected",
      assignment_reason: `Default ${preferences.standardPackageSize} package selected from user preferences.`
    };
  });

  return { ...block, support_components: supportComponents };
}

function purposeIncludes(component: SupportComponent, needle: string) {
  return component.purpose.toLowerCase().includes(needle.toLowerCase());
}

function isLegacyAiDraftPullup(block: CircuitBlock, component: SupportComponent) {
  return (
    block.block_slug !== "bme280_i2c" &&
    block.recipe_source === "ai_proposed" &&
    block.extraction_status !== "ready" &&
    component.type === "resistor" &&
    purposeIncludes(component, "pull-up")
  );
}

function isDeprecatedBmeStrap(block: CircuitBlock, component: SupportComponent) {
  return (
    block.block_slug === "bme280_i2c" &&
    component.type === "resistor" &&
    (purposeIncludes(component, "SDO address strap") || purposeIncludes(component, "CSB strap"))
  );
}

function normalizeCircuitBlockForCurrentSchema(block: CircuitBlock): CircuitBlock {
  const support_components = block.support_components.filter(
    (component) => !isLegacyAiDraftPullup(block, component) && !isDeprecatedBmeStrap(block, component)
  );

  if (support_components.length === block.support_components.length) {
    return block;
  }

  return { ...block, support_components };
}

function nextStepChecksFromBlock(block: CircuitBlock) {
  return Object.fromEntries(block.next_steps.map((step) => [step.id, step.status === "done"]));
}

function normalizeNextStepChecks(
  block: CircuitBlock,
  checks: Record<string, boolean> | undefined
) {
  const fallbackChecks = nextStepChecksFromBlock(block);
  return Object.fromEntries(
    block.next_steps.map((step) => [step.id, Boolean(checks?.[step.id] ?? fallbackChecks[step.id])])
  );
}

function normalizePartLibraryEntry(entry: PartLibraryEntry): PartLibraryEntry {
  const block = normalizeCircuitBlockForCurrentSchema(entry.block);
  return {
    ...entry,
    block,
    messages: entry.messages.map(normalizeChatMessage),
    nextStepChecks: normalizeNextStepChecks(block, entry.nextStepChecks)
  };
}

function questionIsActive(question: MissingQuestion, answerValues: Record<string, string>) {
  return Object.entries(question.depends_on ?? {}).every(
    ([answerId, expected]) => answerValues[answerId] === expected
  );
}

const PRE_SEARCH_REQUIREMENT_QUESTION_IDS = new Set([
  "calc_input_voltage_v",
  "calc_output_voltage_v",
  "calc_output_current_a",
  "clarify_application",
  "clarify_interface_preference",
  "clarify_supply_voltage_v",
  "clarify_priority"
]);

function isPreSearchClarificationQuestion(question: MissingQuestion) {
  return PRE_SEARCH_REQUIREMENT_QUESTION_IDS.has(question.id);
}

function messageWithClarificationAnswers(message: string, answerValues: Record<string, string>) {
  const lines = [
    ["calc_input_voltage_v", "Input voltage"],
    ["calc_output_voltage_v", "Output voltage"],
    ["calc_output_current_a", "Maximum output current"],
    ["clarify_application", "Application or use case"],
    ["clarify_interface_preference", "Interface preference"],
    ["clarify_supply_voltage_v", "Supply or logic voltage"],
    ["clarify_priority", "Recommendation priority"]
  ]
    .map(([id, label]) => {
      const value = answerValues[id]?.trim();
      if (!value) return "";
      const unit =
        id === "calc_output_current_a"
          ? " A"
          : id === "calc_input_voltage_v" || id === "calc_output_voltage_v"
            ? " V"
            : "";
      return `${label}: ${value}${unit}`;
    })
    .filter(Boolean);
  if (!lines.length) return message;
  return `${message}\n\nUse this recommendation context:\n${lines.join("\n")}`;
}

function answeredQuestionUserText(question: MissingQuestion, option: Option) {
  const label = option.label.trim();
  const value = option.value.trim();
  if (question.type === "select") return label || value;
  return value || label;
}

function referenceBase(blockSlug: string) {
  const total = Array.from(blockSlug).reduce(
    (sum, char, index) => sum + (index + 1) * char.charCodeAt(0),
    0
  );
  return 100 + (total % 800);
}

function bmeResistors(block: CircuitBlock) {
  const resistors = block.support_components.filter(
    (component) => component.type === "resistor" || component.symbol === "Device:R"
  );
  const sdaPullup = resistors.find((component) => purposeIncludes(component, "SDA pull-up"));
  const sclPullup = resistors.find((component) => purposeIncludes(component, "SCL pull-up"));
  const sdoStrap = resistors.find((component) => purposeIncludes(component, "SDO address strap"));
  const csbStrap = resistors.find((component) => purposeIncludes(component, "CSB strap"));
  return { sdaPullup, sclPullup, sdoStrap, csbStrap };
}

function componentTableRows(block: CircuitBlock | null): ComponentTableRow[] {
  if (!block) return [];

  const rows: ComponentTableRow[] = [
    {
      key: "main",
      reference: block.block_slug === "bme280_i2c" ? "U1" : `U${referenceBase(block.block_slug)}`,
      component: block.main_component,
      supportKind: "main"
    }
  ];
  const indexedSupportComponents = block.support_components.map((component, supportIndex) => ({
    component,
    supportIndex
  }));

  if (block.block_slug === "bme280_i2c") {
    const capacitors = indexedSupportComponents.filter(({ component }) => component.type === "capacitor");
    capacitors.forEach(({ component, supportIndex }, index) => {
      rows.push({
        key: `bme-cap-${supportIndex}`,
        reference: `C${index + 1}`,
        component,
        supportIndex,
        supportKind: "support"
      });
    });

    const { sdaPullup, sclPullup, sdoStrap, csbStrap } = bmeResistors(block);
    const orderedResistors = [sdaPullup, sclPullup, sdoStrap, csbStrap]
      .filter((component): component is SupportComponent => Boolean(component))
      .map((component) => ({
        component,
        supportIndex: block.support_components.indexOf(component)
      }))
      .filter(({ supportIndex }) => supportIndex >= 0);
    orderedResistors.forEach(({ component, supportIndex }, index) => {
      rows.push({
        key: `bme-res-${supportIndex}`,
        reference: `R${index + 1}`,
        component,
        supportIndex,
        supportKind: "support"
      });
    });

    const used = new Set<SupportComponent>([
      ...capacitors.map(({ component }) => component),
      ...orderedResistors.map(({ component }) => component)
    ]);
    indexedSupportComponents
      .filter(({ component }) => !used.has(component))
      .forEach(({ component, supportIndex }) => {
        rows.push({
          key: `bme-extra-${supportIndex}`,
          reference: component.reference,
          component,
          supportIndex,
          supportKind: "support"
        });
      });
    return rows;
  }

  const base = referenceBase(block.block_slug);
  let capacitorIndex = 1;
  let resistorIndex = 1;
  indexedSupportComponents.forEach(({ component, supportIndex }) => {
    if (component.type === "capacitor" || component.symbol === "Device:C") {
      rows.push({
        key: `cap-${supportIndex}`,
        reference: `C${base + capacitorIndex}`,
        component,
        supportIndex,
        supportKind: "support"
      });
      capacitorIndex += 1;
      return;
    }
    if (component.type === "resistor" || component.symbol === "Device:R") {
      rows.push({
        key: `res-${supportIndex}`,
        reference: `R${base + resistorIndex}`,
        component,
        supportIndex,
        supportKind: "support"
      });
      resistorIndex += 1;
      return;
    }
    if (component.type.toLowerCase() === "diode" || component.symbol.toLowerCase() === "device:d") {
      rows.push({
        key: `diode-${supportIndex}`,
        reference: `D${base + supportIndex + 1}`,
        component,
        supportIndex,
        supportKind: "support"
      });
      return;
    }
    rows.push({
      key: `support-${supportIndex}`,
      reference: component.reference,
      component,
      supportIndex,
      supportKind: "support"
    });
  });

  return rows;
}

function libraryTextWithVoltageAliases(value: string) {
  const aliases: string[] = [];
  if (/(^|\W)(\+?3v3|3\.3\s*v)(\W|$)/i.test(value)) {
    aliases.push("3.3v", "3v3", "+3v3");
  }
  if (/(^|\W)(\+?1v8|1\.8\s*v)(\W|$)/i.test(value)) {
    aliases.push("1.8v", "1v8", "+1v8");
  }
  return aliases.join(" ");
}

function partLibrarySearchText(entry: PartLibraryEntry) {
  const block = entry.block;
  const main = block.main_component;
  const answers = { ...entry.answers, ...block.selected_options };
  const answerText = [
    ...answerSummaryItems(block).flatMap((item) => [item.label, item.value]),
    ...Object.entries(answers).flatMap(([key, value]) => [key, value])
  ];
  const supportText = block.support_components.flatMap((component) => [
    component.reference,
    component.type,
    component.value,
    component.supplier ?? "",
    component.supplier_part_number ?? "",
    component.purpose,
    component.symbol,
    component.footprint,
    component.connects.join(" "),
    component.assignment_reason
  ]);
  const text = [
    entry.title,
    entry.summary,
    block.block_name,
    block.block_slug,
    block.summary,
    main.reference,
    main.type,
    main.value,
    main.mpn ?? "",
    main.manufacturer ?? "",
    main.supplier ?? "",
    main.supplier_part_number ?? "",
    main.purpose,
    main.symbol,
    main.footprint,
    main.connects.join(" "),
    block.external_nets.join(" "),
    block.internal_nets.join(" "),
    ...block.assumptions,
    ...answerText,
    ...supportText
  ]
    .filter(Boolean)
    .join(" ");

  return `${text} ${libraryTextWithVoltageAliases(text)}`.toLowerCase();
}

function entryMatchesPartLibraryQuery(entry: PartLibraryEntry, query: string) {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return true;

  const searchText = partLibrarySearchText(entry);
  const compactSearchText = searchText.replace(/\s+/g, "");
  const compactQuery = normalizedQuery.replace(/\s+/g, "");
  return (
    searchText.includes(normalizedQuery) ||
    compactSearchText.includes(compactQuery) ||
    normalizedQuery
      .split(/\s+/)
      .filter((token) => !GENERIC_LIBRARY_QUERY_WORDS.has(token))
      .every((token) => searchText.includes(token) || compactSearchText.includes(token))
  );
}

function entryMatchesPartLibraryFilter(entry: PartLibraryEntry, filterId: PartLibraryFilterId) {
  const filter = PART_LIBRARY_FILTERS.find((item) => item.id === filterId);
  if (!filter || filter.id === "all") return true;

  const searchText = partLibrarySearchText(entry);
  return filter.tokens.some((token) => searchText.includes(token));
}

function filteredPartLibraryEntries(
  entries: PartLibraryEntry[],
  query: string,
  filterId: PartLibraryFilterId
) {
  return entries.filter(
    (entry) =>
      entryMatchesPartLibraryQuery(entry, query) &&
      entryMatchesPartLibraryFilter(entry, filterId)
  );
}

function defaultPullupComponents(
  logicNet: string,
  value = "4.7 kOhm",
  packageSize: PackagePreferenceId = DEFAULT_USER_PREFERENCES.standardPackageSize
): SupportComponent[] {
  const pullupValue = displayedAnswerValue(value);
  const footprint = passiveFootprint("resistor", packageSize);
  return [
    {
      reference: "R?",
      type: "resistor",
      value: pullupValue,
      purpose: "I2C SDA pull-up",
      symbol: "Device:R",
      footprint,
      footprint_confidence: "default_selected",
      symbol_confidence: "default_selected",
      connects: ["I2C1_SDA", logicNet],
      assignment_reason: `Default ${packageSize} package selected from user preferences.`
    },
    {
      reference: "R?",
      type: "resistor",
      value: pullupValue,
      purpose: "I2C SCL pull-up",
      symbol: "Device:R",
      footprint,
      footprint_confidence: "default_selected",
      symbol_confidence: "default_selected",
      connects: ["I2C1_SCL", logicNet],
      assignment_reason: `Default ${packageSize} package selected from user preferences.`
    }
  ];
}

function syncBlockWithAnswer(
  block: CircuitBlock,
  answerId: EditableAnswerId,
  value: string,
  preferences: UserPreferences = DEFAULT_USER_PREFERENCES
): CircuitBlock {
  const selectedOptions = { ...block.selected_options, [answerId]: value };
  const logicNet = logicNetForOptions(selectedOptions);
  const address = selectedOptions.i2c_address ?? "0x76";
  const pullupValue = selectedOptions.pullup_value ?? "4.7 kOhm";

  const replaceLogicNet = (net: string) => (net.startsWith("+") ? logicNet : net);
  const updateMainConnect = (net: string) => {
    if (net.startsWith("SDO=")) return `SDO=${address}`;
    return replaceLogicNet(net);
  };
  const updateSupport = (component: SupportComponent): SupportComponent => {
    if (component.purpose.startsWith("SDO address strap")) {
      return {
        ...component,
        purpose: `SDO address strap for ${address}`,
        connects: ["SDO", address === "0x76" ? "GND" : logicNet]
      };
    }
    if (component.purpose === "CSB strap for I2C mode") {
      return { ...component, connects: ["CSB", logicNet] };
    }
    if (component.purpose.toLowerCase().includes("pull-up")) {
      return {
        ...component,
        value: displayedAnswerValue(pullupValue),
        connects: component.connects.map(replaceLogicNet)
      };
    }
    return { ...component, connects: component.connects.map(replaceLogicNet) };
  };

  const isPullup = (component: SupportComponent) =>
    component.purpose.toLowerCase().includes("pull-up");
  const nonPullups = block.support_components.filter((component) => !isPullup(component));
  const existingPullups = block.support_components.filter(isPullup);
  const pullups =
    selectedOptions.pullups === "skip"
      ? []
      : (existingPullups.length >= 2
          ? existingPullups
          : defaultPullupComponents(logicNet, pullupValue, preferences.standardPackageSize)
        ).map(updateSupport);
  const decoupling = nonPullups
    .filter((component) => component.type === "capacitor")
    .map(updateSupport);
  const straps = nonPullups
    .filter((component) => component.type !== "capacitor")
    .map(updateSupport);

  return {
    ...block,
    selected_options: selectedOptions,
    external_nets: block.external_nets.map(replaceLogicNet),
    main_component: {
      ...block.main_component,
      connects: block.main_component.connects.map(updateMainConnect)
    },
    support_components: [...decoupling, ...pullups, ...straps]
  };
}

function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [bridgeStatus, setBridgeStatus] = useState<BridgeStatus | null>(null);
  const [pricing, setPricing] = useState<PricingPreview | null>(null);
  const [accountOverview, setAccountOverview] = useState<AccountOverview | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>(initialChatMessages);
  const messagesRef = useRef<ChatMessage[]>(messages);
  const [prompt, setPrompt] = useState("");
  const [draftBlock, setDraftBlock] = useState<CircuitBlock | null>(null);
  const [block, setBlock] = useState<CircuitBlock | null>(null);
  const [questions, setQuestions] = useState<MissingQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [pendingClarificationPrompt, setPendingClarificationPrompt] = useState<string | null>(null);
  const [nextStepChecks, setNextStepChecks] = useState<Record<string, boolean>>({});
  const [projectPath, setProjectPath] = useState("demo_kicad_project");
  const [exportResult, setExportResult] = useState<ExportResponse | null>(null);
  const [importResult, setImportResult] = useState<BridgeImportResponse | null>(null);
  const [insertMode, setInsertMode] = useState<ImportMode>("hierarchical_sheet");
  const [extractionJob, setExtractionJob] = useState<ComponentExtractionJob | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [activeQuestionIndex, setActiveQuestionIndex] = useState(0);
  const [partLibrary, setPartLibrary] = useState<PartLibraryEntry[]>(loadPartLibrary);
  const [userPreferences, setUserPreferences] = useState<UserPreferences>(loadUserPreferences);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [activeLibraryEntryId, setActiveLibraryEntryId] = useState<string | null>(null);
  const [entryPendingDelete, setEntryPendingDelete] = useState<PartLibraryEntry | null>(null);
  const [viewMode, setViewMode] = useState<"home" | "workspace">("home");
  const [homeExiting, setHomeExiting] = useState(false);
  const [narrowInspectorOpen, setNarrowInspectorOpen] = useState(false);
  const extractionRunIdRef = useRef(0);

  const currentBlock = block ?? draftBlock;
  const projectConnected = Boolean(bridgeStatus?.connected);
  const activeQuestions = useMemo(
    () => questions.filter((question) => questionIsActive(question, answers)),
    [questions, answers]
  );
  const chatBusy = busy === "chat" || busy === "generate" || busy === "extract" ? busy : null;
  const popupBusy = busy && !["chat", "generate", "extract"].includes(busy) ? busy : null;

  const progress = useMemo(() => {
    if (importResult) return "Verify";
    if (exportResult) return "Insert";
    if (block) return "Preview";
    if (draftBlock) return "Configure";
    return "Identify";
  }, [block, draftBlock, exportResult, importResult]);

  useEffect(() => {
    void refreshBackendStatus();
  }, []);

  useEffect(() => {
    persistPartLibrary(partLibrary);
  }, [partLibrary]);

  useEffect(() => {
    persistUserPreferences(userPreferences);
  }, [userPreferences]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshBridgeStatus(true);
    }, 2500);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (activeQuestions.length === 0) {
      setActiveQuestionIndex(0);
      return;
    }
    setActiveQuestionIndex((index) => Math.min(index, activeQuestions.length - 1));
  }, [activeQuestions.length]);

  async function refreshBackendStatus() {
    try {
      const [healthResponse, accountResponse, statusResponse] = await Promise.all([
        api<HealthResponse>("/health"),
        api<AccountOverview>("/account"),
        api<BridgeStatus>("/bridge/status")
      ]);
      setHealth(healthResponse);
      setAccountOverview(accountResponse);
      setPricing(accountResponse.pricing_preview);
      applyBridgeStatus(statusResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backend is not reachable.");
    }
  }

  async function refreshBridgeStatus(silent = false) {
    try {
      const statusResponse = await api<BridgeStatus>("/bridge/status");
      applyBridgeStatus(statusResponse);
      if (!silent) {
        addToast(
          statusResponse.connected ? "Bridge linked" : "Bridge not linked",
          statusResponse.project_path ? [statusResponse.project_path] : []
        );
      }
    } catch (err) {
      if (!silent) {
        setError(err instanceof Error ? err.message : "Unable to refresh KiCad bridge status.");
      }
    }
  }

  function applyBridgeStatus(statusResponse: BridgeStatus) {
    setBridgeStatus(statusResponse);
    if (statusResponse.connected && statusResponse.project_path) {
      setProjectPath(statusResponse.project_path);
    }
  }

  function setChatMessages(nextMessages: ChatMessage[]) {
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
  }

  function addMessage(
    role: ChatMessage["role"],
    text: string,
    options: { animate?: boolean } = {}
  ) {
    const message: ChatMessage = {
      id: `${role}-${Date.now()}-${Math.random()}`,
      role,
      text,
      animate: role === "assistant" ? Boolean(options.animate) : false
    };
    const nextMessages = [...messagesRef.current, message];
    setChatMessages(nextMessages);
    return message;
  }

  function addAnsweredQuestionMessages(question: MissingQuestion, option: Option) {
    const questionText = question.question.trim();
    const answerText = answeredQuestionUserText(question, option) || "No answer provided";
    if (questionText) {
      addMessage("assistant", questionText);
    }
    addMessage("user", answerText);
  }

  function completeMessageAnimation(messageId: string) {
    let changed = false;
    const nextMessages = messagesRef.current.map((message) => {
      if (message.id !== messageId || !message.animate) return message;
      changed = true;
      return { ...message, animate: false };
    });
    if (changed) {
      setChatMessages(nextMessages);
    }
  }

  function addToast(title: string, details: string[] = []) {
    const id = `toast-${Date.now()}-${Math.random()}`;
    setToasts((current) => [
      ...current,
      { id, title, details, expanded: false, held: false, leaving: false }
    ]);
    window.setTimeout(() => {
      setToasts((current) =>
        current.map((toast) => {
          if (toast.id !== id) return toast;
          if (toast.expanded) return { ...toast, held: true, leaving: false };
          return { ...toast, leaving: true };
        })
      );
    }, 6200);
    window.setTimeout(() => {
      setToasts((current) =>
        current.filter((toast) => toast.id !== id || toast.expanded || toast.held)
      );
    }, 7000);
  }

  function toggleToast(id: string) {
    setToasts((current) =>
      current.map((toast) => {
        if (toast.id !== id) return toast;
        if (toast.expanded) {
          const shouldDismiss = toast.held || toast.leaving;
          return {
            ...toast,
            expanded: false,
            held: false,
            leaving: shouldDismiss
          };
        }
        return {
          ...toast,
          expanded: true,
          held: toast.leaving ? true : toast.held,
          leaving: false
        };
      })
    );

    window.setTimeout(() => {
      setToasts((current) =>
        current.filter((toast) => toast.id !== id || !toast.leaving || toast.expanded)
      );
    }, 700);
  }

  function dismissToast(id: string) {
    setToasts((current) =>
      current.map((toast) => {
        if (toast.id !== id || toast.leaving) return toast;
        return { ...toast, expanded: false, held: false, leaving: true };
      })
    );

    window.setTimeout(() => {
      setToasts((current) =>
        current.filter((toast) => toast.id !== id || !toast.leaving || toast.expanded)
      );
    }, 700);
  }

  function beginExtractionRun() {
    extractionRunIdRef.current += 1;
    return extractionRunIdRef.current;
  }

  function cancelExtractionRun() {
    extractionRunIdRef.current += 1;
  }

  function extractionRunIsCurrent(runId: number) {
    return extractionRunIdRef.current === runId;
  }

  function applyExtractionDraft(job: ComponentExtractionJob) {
    if (!job.draft_block) {
      throw new Error("Extraction finished without a generated draft block.");
    }

    const readyDraft = prepareIncomingBlock(job.draft_block);
    setBlock(null);
    setDraftBlock(readyDraft);
    setQuestions(readyDraft.missing_questions);
    setAnswers({});
    setActiveQuestionIndex(0);
    setNextStepChecks({});
    setExportResult(null);
    setImportResult(null);
    setActiveLibraryEntryId(null);
    setExtractionJob(null);
  }

  async function pollExtractionJob(
    jobId: string,
    initialJob: ComponentExtractionJob | null | undefined,
    runId: number
  ) {
    const deadline = Date.now() + EXTRACTION_TIMEOUT_MS;
    let currentJob = initialJob ?? null;
    let notifiedReadableSources = Boolean(currentJob && jobHasReadableSources(currentJob));

    setBusy("extract");
    setError(null);
    setQuestions([]);
    setActiveQuestionIndex(0);
    if (currentJob) {
      setExtractionJob(currentJob);
    }

    while (Date.now() < deadline) {
      if (!currentJob || currentJob.status !== "ready") {
        currentJob = await api<ComponentExtractionJob>(`/component-extraction/${jobId}`);
      }
      if (!extractionRunIsCurrent(runId)) return;
      setExtractionJob(currentJob);

      if (
        !notifiedReadableSources &&
        jobHasReadableSources(currentJob) &&
        currentJob.status !== "ready" &&
        currentJob.status !== "failed"
      ) {
        notifiedReadableSources = true;
        addMessage("assistant", datasheetFoundNotification(currentJob));
      }

      if (currentJob.status === "ready") {
        applyExtractionDraft(currentJob);
        addMessage(
          "assistant",
          `${currentJob.message}\n\nReview the extracted sources and confirm before Trace Labs generates KiCad insertion files.`
        );
        return;
      }

      if (currentJob.status === "failed") {
        const details = currentJob.errors.length ? `\n\n${currentJob.errors.join("\n")}` : "";
        const message = `${currentJob.message}${details}`;
        setError(message);
        addMessage("assistant", message);
        return;
      }

      await wait(EXTRACTION_POLL_INTERVAL_MS);
    }

    const message = extractionTimeoutMessage(currentJob);
    if (!extractionRunIsCurrent(runId)) return;
    setError(message);
    addMessage("assistant", message);
  }

  async function startExtractionFromChoice(option: Option) {
    const extractionRunId = beginExtractionRun();
    setBusy("extract");
    setError(null);
    setQuestions([]);
    setAnswers({});
    setActiveQuestionIndex(0);

    try {
      const job = await api<ComponentExtractionJob>("/component-extraction/start", {
        method: "POST",
        body: JSON.stringify({ choice_value: option.value })
      });
      if (!extractionRunIsCurrent(extractionRunId)) return;
      setExtractionJob(job);
      addMessage("assistant", job.message);
      await pollExtractionJob(job.job_id, job, extractionRunId);
    } catch (err) {
      if (extractionRunIsCurrent(extractionRunId)) {
        setError(err instanceof Error ? err.message : "Unable to start datasheet extraction.");
      }
    } finally {
      if (extractionRunIsCurrent(extractionRunId)) {
        setBusy(null);
      }
    }
  }

  function saveBlockToPartLibrary(
    savedBlock: CircuitBlock,
    answerValues: Record<string, string>,
    chatMessages = messagesRef.current,
    checkValues: Record<string, boolean> = nextStepChecks
  ) {
    const now = new Date().toISOString();
    const entryId =
      activeLibraryEntryId ?? savedBlock.id ?? `${savedBlock.block_slug}-${Date.now()}`;
    const normalizedBlock = normalizeCircuitBlockForCurrentSchema({
      ...savedBlock,
      selected_options: { ...savedBlock.selected_options, ...answerValues }
    });

    setActiveLibraryEntryId(entryId);
    setPartLibrary((current) => {
      const existing = current.find((entry) => entry.id === entryId);
      const entry: PartLibraryEntry = {
        id: entryId,
        blockId: normalizedBlock.id,
        title: normalizedBlock.block_name,
        summary: summarizeAnswers(answerValues),
        createdAt: existing?.createdAt ?? now,
        updatedAt: now,
        block: normalizedBlock,
        answers: answerValues,
        messages: chatMessages.map(normalizeChatMessage),
        nextStepChecks: normalizeNextStepChecks(normalizedBlock, checkValues)
      };
      return [entry, ...current.filter((item) => item.id !== entryId)].slice(0, 30);
    });
  }

  function updateNextStepChecks(checkValues: Record<string, boolean>) {
    setNextStepChecks(checkValues);
    if (block) {
      saveBlockToPartLibrary(block, answers, messagesRef.current, checkValues);
    }
  }

  function prepareIncomingBlock(incomingBlock: CircuitBlock) {
    return applyStandardPackagePreference(
      normalizeCircuitBlockForCurrentSchema(incomingBlock),
      userPreferences
    );
  }

  function updateStandardPackagePreference(packageSize: PackagePreferenceId) {
    const nextPreferences = { ...userPreferences, standardPackageSize: packageSize };
    setUserPreferences(nextPreferences);

    const updateBlock = (sourceBlock: CircuitBlock) =>
      applyStandardPackagePreference(sourceBlock, nextPreferences);

    if (block) {
      const updatedBlock = updateBlock(block);
      setBlock(updatedBlock);
      saveBlockToPartLibrary(
        updatedBlock,
        { ...answers, ...updatedBlock.selected_options },
        messagesRef.current
      );
    }
    if (draftBlock) {
      setDraftBlock(updateBlock(draftBlock));
    }
    setExportResult(null);
    setImportResult(null);
  }

  function updateSupportComponent(
    supportIndex: number,
    updates: Partial<Pick<SupportComponent, "value" | "footprint">>
  ) {
    const updateBlock = (sourceBlock: CircuitBlock) => ({
      ...sourceBlock,
      support_components: sourceBlock.support_components.map((component, index) => {
        if (index !== supportIndex) return component;
        const nextComponent = { ...component, ...updates };
        if (updates.footprint !== undefined) {
          nextComponent.footprint_confidence = "user_selected";
        }
        if (updates.value !== undefined || updates.footprint !== undefined) {
          nextComponent.assignment_reason = "Edited by the user in Trace Labs before KiCad export.";
        }
        return nextComponent;
      })
    });

    if (block) {
      const updatedBlock = updateBlock(block);
      setBlock(updatedBlock);
      saveBlockToPartLibrary(
        updatedBlock,
        { ...answers, ...updatedBlock.selected_options },
        messagesRef.current
      );
    }
    if (draftBlock) {
      setDraftBlock(updateBlock(draftBlock));
    }
    setExportResult(null);
    setImportResult(null);
  }

  function restorePartLibraryEntry(entry: PartLibraryEntry) {
    cancelExtractionRun();
    const normalizedEntry = normalizePartLibraryEntry(entry);
    setChatMessages(normalizedEntry.messages);
    setBlock(normalizedEntry.block);
    setDraftBlock(null);
    setQuestions([]);
    setAnswers(normalizedEntry.answers);
    setActiveQuestionIndex(0);
    setNextStepChecks(normalizeNextStepChecks(normalizedEntry.block, normalizedEntry.nextStepChecks));
    setExportResult(null);
    setImportResult(null);
    setExtractionJob(null);
    setActiveLibraryEntryId(normalizedEntry.id);
    setLibraryOpen(false);
    setNarrowInspectorOpen(false);
    setError(null);
    setViewMode("workspace");
    addToast("Loaded from part library", [normalizedEntry.title, normalizedEntry.summary]);
  }

  function requestPartLibraryDelete(entry: PartLibraryEntry) {
    setEntryPendingDelete(entry);
  }

  function confirmPartLibraryDelete() {
    if (!entryPendingDelete) return;

    const deletedEntry = entryPendingDelete;
    setPartLibrary((current) => current.filter((entry) => entry.id !== deletedEntry.id));
    if (activeLibraryEntryId === deletedEntry.id) {
      setActiveLibraryEntryId(null);
    }
    setEntryPendingDelete(null);
    addToast("Deleted from part library", [deletedEntry.title]);
  }

  function returnToHome() {
    cancelExtractionRun();
    setBlock(null);
    setDraftBlock(null);
    setQuestions([]);
    setAnswers({});
    setActiveQuestionIndex(0);
    setNextStepChecks({});
    setExportResult(null);
    setImportResult(null);
    setExtractionJob(null);
    setError(null);
    setPrompt("");
    setLibraryOpen(false);
    setNarrowInspectorOpen(false);
    setChatMessages(initialChatMessages());
    setHomeExiting(false);
    setViewMode("home");
  }

  function startNewChat() {
    setLibraryOpen(false);
    setActiveLibraryEntryId(null);
    returnToHome();
  }

  function openPartLibrary() {
    setError(null);
    setLibraryOpen(true);
  }

  useEffect(() => {
    if (!narrowInspectorOpen) return;

    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setNarrowInspectorOpen(false);
      }
    };

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [narrowInspectorOpen]);

  async function submitMessage(
    event?: FormEvent,
    override?: string,
    answersOverride: Record<string, string> = answers,
    userMessageOverride?: string | null
  ) {
    event?.preventDefault();
    const message = (override ?? prompt).trim();
    if (!message) return;
    if (!projectConnected) {
      setError("Connect a KiCad project before asking Trace Labs to generate a part.");
      return;
    }

    const startingFromHome = viewMode === "home";
    if (startingFromHome) {
      setHomeExiting(true);
    } else {
      setViewMode("workspace");
    }
    setBusy("chat");
    setError(null);
    setPrompt("");
    setActiveQuestionIndex(0);
    if (userMessageOverride !== null) {
      addMessage("user", userMessageOverride ?? message);
    }

    try {
      const responsePromise = api<ChatResponse>("/chat", {
        method: "POST",
        body: JSON.stringify({
          message,
          draft_block: draftBlock,
          current_block: block,
          answers: answersOverride,
          history: chatHistoryPayload(messagesRef.current)
        })
      });
      if (startingFromHome) {
        await wait(420);
        setViewMode("workspace");
        setHomeExiting(false);
      }
      const response = await responsePromise;
      addMessage("assistant", response.assistant_message, { animate: true });
      if (response.extraction_job) {
        const extractionRunId = beginExtractionRun();
        setBlock(null);
        setDraftBlock(null);
        setQuestions([]);
        setAnswers({});
        setPendingClarificationPrompt(null);
        setExportResult(null);
        setImportResult(null);
        setNextStepChecks({});
        setActiveLibraryEntryId(null);
        setExtractionJob(response.extraction_job);
        await pollExtractionJob(response.extraction_job.job_id, response.extraction_job, extractionRunId);
        void refreshPricing().catch(() => undefined);
        return;
      }
      if (response.draft_block) {
        setBlock(null);
        setExportResult(null);
        setImportResult(null);
        setExtractionJob(null);
        setPendingClarificationPrompt(null);
        setNextStepChecks({});
        setActiveLibraryEntryId(null);
        setDraftBlock(prepareIncomingBlock(response.draft_block));
      }
      setPendingClarificationPrompt(
        !response.draft_block &&
          !response.extraction_job &&
          response.missing_questions.some(isPreSearchClarificationQuestion)
          ? message
          : null
      );
      setQuestions(response.missing_questions);
      setActiveQuestionIndex(0);
      setAnswers({});
      void refreshPricing().catch(() => undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to process prompt.");
    } finally {
      setBusy(null);
    }
  }

  async function finaliseBlock(answersOverride: Record<string, string> = answers) {
    if (!draftBlock) return;

    setBusy("generate");
    setError(null);
    try {
      const response = await api<CircuitBlock>("/answer-questions", {
        method: "POST",
        body: JSON.stringify({ answers: answersOverride, draft_block: draftBlock })
      });
      const normalizedResponse = prepareIncomingBlock(response);
      const initialNextStepChecks = nextStepChecksFromBlock(normalizedResponse);
      setBlock(normalizedResponse);
      setDraftBlock(null);
      setQuestions([]);
      setExtractionJob(null);
      setActiveQuestionIndex(0);
      setPendingClarificationPrompt(null);
      setNextStepChecks(initialNextStepChecks);
      addMessage(
        "assistant",
        `I generated ${normalizedResponse.block_name} with ${summarizeAnswers(answersOverride)}. It is ready to insert.`
      );
      saveBlockToPartLibrary(
        normalizedResponse,
        answersOverride,
        messagesRef.current,
        initialNextStepChecks
      );
      addToast("Saved to part library", [normalizedResponse.block_name, summarizeAnswers(answersOverride)]);
      void refreshPricing().catch(() => undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to generate block.");
    } finally {
      setBusy(null);
    }
  }

  async function exportBlock() {
    if (!block) return null;

    setBusy("export");
    setError(null);
    try {
      const response = await api<ExportResponse>("/export", {
        method: "POST",
        body: JSON.stringify({ block })
      });
      const exportedBlock = prepareIncomingBlock(response.block);
      setBlock(exportedBlock);
      saveBlockToPartLibrary(
        exportedBlock,
        exportedBlock.selected_options,
        messagesRef.current,
        nextStepChecks
      );
      setExportResult(response);
      setPricing(response.pricing_preview);
      void refreshPricing();
      addToast("Component added", [
        response.output_directory,
        ...Object.entries(response.files).map(([label, path]) => `${label}: ${path}`)
      ]);
      return response;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to export block.");
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function linkProject() {
    setBusy("link");
    setError(null);
    try {
      const linked = await api<BridgeLinkRecord>("/bridge/link", {
        method: "POST",
        body: JSON.stringify({
          project_path: projectPath,
          project_name: "weather_station.kicad_pro",
          bridge_mode: "mock"
        })
      });
      setBridgeStatus({
        connected: linked.connected,
        project_path: linked.project_path,
        project_name: linked.project_name,
        schematic_path: linked.schematic_path,
        kicad_bridge_status: "mocked"
      });
      addToast("Project linked", [linked.project_path, linked.schematic_path]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to link project.");
    } finally {
      setBusy(null);
    }
  }

  async function insertIntoKicad(mode: ImportMode = insertMode) {
    const exported = exportResult ?? (await exportBlock());
    if (!exported) return;

    setBusy("insert");
    setError(null);
    try {
      const response = await api<BridgeImportResponse>("/bridge/import", {
        method: "POST",
        body: JSON.stringify({
          generated_block_dir: exported.output_directory,
          import_mode: mode,
          open_after_import: true
        })
      });
      setImportResult(response);
      addToast("Inserted in KiCad", [
        response.message,
        response.opened_sheet_path ? `Opened: ${response.opened_sheet_path}` : "Open requested",
        ...(response.open_error ? [`Open warning: ${response.open_error}`] : []),
        response.root_schematic,
        ...response.modified_files
      ]);
      await refreshBackendStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to insert into KiCad.");
    } finally {
      setBusy(null);
    }
  }

  async function refreshPricing() {
    const response = await api<AccountOverview>("/account");
    setAccountOverview(response);
    setPricing(response.pricing_preview);
  }

  function answerQuestion(question: MissingQuestion, option: Option) {
    if (question.id === "part_choice") {
      const nextAnswers = { ...answers, [question.id]: option.value };
      setAnswers(nextAnswers);
      addAnsweredQuestionMessages(question, option);
      setQuestions([]);
      setActiveQuestionIndex(0);
      if (option.value.startsWith(EXTRACT_CANDIDATE_PREFIX)) {
        void startExtractionFromChoice(option);
        return;
      }
      void submitMessage(undefined, `Use ${option.value} for this block`, nextAnswers, null);
      return;
    }

    if (question.id === "recipe_review_confirmed" && option.value === "cancel") {
      addAnsweredQuestionMessages(question, option);
      addMessage(
        "assistant",
        "I cancelled that draft recipe. Ask for a known supported recipe or choose another part to continue."
      );
      setDraftBlock(null);
      setQuestions([]);
      setAnswers({});
      setPendingClarificationPrompt(null);
      setExtractionJob(null);
      setActiveQuestionIndex(0);
      return;
    }

    if (!draftBlock && pendingClarificationPrompt && isPreSearchClarificationQuestion(question)) {
      const nextAnswers = { ...answers, [question.id]: option.value };
      setAnswers(nextAnswers);
      addAnsweredQuestionMessages(question, option);

      const nextActiveQuestions = questions.filter((item) => questionIsActive(item, nextAnswers));
      const currentIndex = nextActiveQuestions.findIndex((item) => item.id === question.id);
      const nextIndex = currentIndex + 1;
      if (nextIndex < nextActiveQuestions.length) {
        setActiveQuestionIndex(nextIndex);
        return;
      }

      const clarifiedMessage = messageWithClarificationAnswers(pendingClarificationPrompt, nextAnswers);
      setQuestions([]);
      setPendingClarificationPrompt(null);
      setActiveQuestionIndex(0);
      void submitMessage(undefined, clarifiedMessage, nextAnswers, null);
      return;
    }

    if (!draftBlock) return;

    const nextAnswers = { ...answers, [question.id]: option.value };
    setAnswers(nextAnswers);
    addAnsweredQuestionMessages(question, option);

    const nextActiveQuestions = questions.filter((item) => questionIsActive(item, nextAnswers));
    const currentIndex = nextActiveQuestions.findIndex((item) => item.id === question.id);
    const nextIndex = currentIndex + 1;
    if (nextIndex < nextActiveQuestions.length) {
      setActiveQuestionIndex(nextIndex);
      return;
    }

    void finaliseBlock(nextAnswers);
  }

  function updateAnswer(answerId: EditableAnswerId, option: Option) {
    const nextAnswers = { ...answers, [answerId]: option.value };
    const sourceBlock = block ?? draftBlock;
    const updatedBlock = sourceBlock
      ? syncBlockWithAnswer(sourceBlock, answerId, option.value, userPreferences)
      : null;

    setAnswers(nextAnswers);
    if (block && updatedBlock) {
      setBlock(updatedBlock);
    }
    if (draftBlock && updatedBlock) {
      setDraftBlock(updatedBlock);
    }
    if (updatedBlock) {
      saveBlockToPartLibrary(updatedBlock, nextAnswers, messagesRef.current);
    }
    setExportResult(null);
    setImportResult(null);
  }

  function insertWithMode(mode: ImportMode) {
    const label = mode === "inline_main" ? "Insert on main sheet" : "Insert as subsheet";
    setInsertMode(mode);
    addMessage("user", label);
    void insertIntoKicad(mode);
  }

  function summarizeAnswers(answerValues: Record<string, string>) {
    const logic = answerValues.logic_voltage ?? "3.3V";
    const interfaceMode = answerValues.interface_mode ?? "I2C";
    if (!("i2c_address" in answerValues) && !("pullups" in answerValues)) {
      if (answerValues.calc_input_voltage_v && answerValues.calc_output_voltage_v) {
        const current = answerValues.calc_output_current_a
          ? ` at ${answerValues.calc_output_current_a} A`
          : "";
        return `${answerValues.calc_input_voltage_v}V to ${answerValues.calc_output_voltage_v}V${current}, calculated from extracted formulas`;
      }
      if (answerValues.recipe_review_confirmed === "confirm") {
        return "extracted circuit confirmed for review";
      }
      return `${logic} logic, ${interfaceMode}`;
    }
    const address = answerValues.i2c_address ?? "0x76";
    if (answerValues.pullups === "skip") {
      return `${logic} logic, ${interfaceMode}, address ${address}, and existing bus pull-ups`;
    }
    const pullups = "added 4.7k pull-ups";
    const pullupValue =
      answerValues.pullup_value === "unspecified"
        ? "pull-up value TBD"
        : `${answerValues.pullup_value ?? "4.7 kOhm"} pull-ups`;
    if (answerValues.pullup_value) {
      return `${logic} logic, ${interfaceMode}, address ${address}, and ${pullups} (${pullupValue})`;
    }
    return `${logic} logic, ${interfaceMode}, address ${address}, and ${pullups}`;
  }

  return (
    <main className="trace-labs-theme min-h-screen bg-[#0a0a0c] text-slate-100 lg:h-screen lg:overflow-hidden">
      <div className="flex min-h-screen flex-col lg:h-screen">
        <Header
          accountOverview={accountOverview}
          canGoHome={viewMode === "workspace"}
          partCount={partLibrary.length}
          pricing={pricing}
          userPreferences={userPreferences}
          onHome={returnToHome}
          onOpenLibrary={openPartLibrary}
          onPackagePreferenceChange={updateStandardPackagePreference}
        />

        {viewMode === "workspace" ? (
          <ProgressBar
            active={progress}
            partCount={partLibrary.length}
            onHome={returnToHome}
            onOpenLibrary={openPartLibrary}
          />
        ) : null}

        <PartLibraryDrawer
          activeEntryId={activeLibraryEntryId}
          entries={partLibrary}
          open={libraryOpen}
          onClose={() => setLibraryOpen(false)}
          onNewChat={startNewChat}
          onRequestDelete={requestPartLibraryDelete}
          onRestore={restorePartLibraryEntry}
        />

        {error ? (
          <div className="mx-4 mt-3 animate-fade-slide rounded-lg border border-amber-400/35 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
            {error}
          </div>
        ) : null}

        {viewMode === "home" ? (
          <HomePage
            activeEntryId={activeLibraryEntryId}
            busy={chatBusy}
            canPrompt={projectConnected}
            entries={partLibrary}
            exiting={homeExiting}
            prompt={prompt}
            bridgeStatus={bridgeStatus}
            projectPath={projectPath}
            onPromptChange={setPrompt}
            setProjectPath={setProjectPath}
            onRequestDelete={requestPartLibraryDelete}
            onRestore={restorePartLibraryEntry}
            onLinkProject={linkProject}
            onRefreshBridge={() => refreshBridgeStatus(false)}
            onSubmit={submitMessage}
            bridgeBusy={busy}
          />
        ) : (
          <section
            key="workspace"
            className={`workspace-shell grid flex-1 grid-cols-1 overflow-hidden border-t border-white/[0.06] lg:min-h-0 lg:grid-cols-[390px_minmax(560px,1fr)_330px] 2xl:grid-cols-[410px_minmax(680px,1fr)_360px] ${
              narrowInspectorOpen ? "narrow-inspector-open" : ""
            }`}
          >
            <ChatPane
              messages={messages}
              busy={chatBusy}
              extractionJob={extractionJob}
              questions={activeQuestions}
              answers={answers}
              onAnswerQuestion={answerQuestion}
              activeQuestionIndex={activeQuestionIndex}
              canPrompt={projectConnected}
              prompt={prompt}
              onPromptChange={setPrompt}
              onSubmit={submitMessage}
              blockReady={Boolean(block)}
              block={block}
              importResult={importResult}
              onInsertMode={insertWithMode}
              onNewPart={startNewChat}
              onUpdateAnswer={updateAnswer}
              onMessageAnimationComplete={completeMessageAnimation}
            />

            <SchematicWorkspace
              block={block}
              documentationBlock={currentBlock}
              busy={busy}
              extractionJob={extractionJob}
            />

            <InspectorPanel
              bridgeStatus={bridgeStatus}
              bridgeBusy={busy}
              block={currentBlock}
              exportResult={exportResult}
              importResult={importResult}
              nextStepChecks={nextStepChecks}
              projectPath={projectPath}
              userPreferences={userPreferences}
              onUpdateSupportComponent={updateSupportComponent}
              setProjectPath={setProjectPath}
              onLinkProject={linkProject}
              onRefreshBridge={() => refreshBridgeStatus(false)}
              setNextStepChecks={updateNextStepChecks}
            />

            <button
              className={`narrow-inspector-scrim ${
                narrowInspectorOpen ? "narrow-inspector-scrim-open" : ""
              }`}
              type="button"
              aria-label="Close review panel"
              onClick={() => setNarrowInspectorOpen(false)}
            />

            <button
              className="narrow-inspector-toggle"
              type="button"
              aria-controls="narrow-review-panel"
              aria-expanded={narrowInspectorOpen}
              onClick={() => setNarrowInspectorOpen((open) => !open)}
            >
              {narrowInspectorOpen ? "Close review" : "Review"}
            </button>
          </section>
        )}
        <ToastStack
          busy={popupBusy}
          toasts={toasts}
          onDismiss={dismissToast}
          onToggle={toggleToast}
        />
        <DeletePartLibraryEntryDialog
          entry={entryPendingDelete}
          onCancel={() => setEntryPendingDelete(null)}
          onConfirm={confirmPartLibraryDelete}
        />
      </div>
    </main>
  );
}

type HomeDotCursor = {
  x: number;
  y: number;
  active: boolean;
};

const HOME_DOTS = Array.from({ length: 20 * 14 }, (_, index) => {
  const columns = 20;
  const rows = 14;
  return {
    id: index,
    x: (index % columns + 0.5) / columns,
    y: (Math.floor(index / columns) + 0.5) / rows
  };
});

function HomePage({
  activeEntryId,
  busy,
  canPrompt,
  entries,
  exiting,
  prompt,
  bridgeStatus,
  projectPath,
  onPromptChange,
  setProjectPath,
  onRequestDelete,
  onRestore,
  onLinkProject,
  onRefreshBridge,
  onSubmit,
  bridgeBusy
}: {
  activeEntryId: string | null;
  busy: string | null;
  canPrompt: boolean;
  entries: PartLibraryEntry[];
  exiting: boolean;
  prompt: string;
  bridgeStatus: BridgeStatus | null;
  projectPath: string;
  onPromptChange: (value: string) => void;
  setProjectPath: (value: string) => void;
  onRequestDelete: (entry: PartLibraryEntry) => void;
  onRestore: (entry: PartLibraryEntry) => void;
  onLinkProject: () => void;
  onRefreshBridge: () => void;
  onSubmit: (event?: FormEvent) => void;
  bridgeBusy: string | null;
}) {
  const [componentSearch, setComponentSearch] = useState("");
  const [componentFilter, setComponentFilter] = useState<PartLibraryFilterId>("all");
  const [homeLibraryCollapsed, setHomeLibraryCollapsed] = useState(true);
  const [dotCursor, setDotCursor] = useState<HomeDotCursor>({
    x: 0.5,
    y: 0.5,
    active: false
  });
  const filteredEntries = useMemo(
    () => filteredPartLibraryEntries(entries, componentSearch, componentFilter),
    [componentFilter, componentSearch, entries]
  );
  const updateHomeDots = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
    const y = Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height));
    setDotCursor({ x, y, active: true });
  };
  const resetHomeDots = () => {
    setDotCursor((current) => ({ ...current, active: false }));
  };

  return (
    <section
      key="home"
      className="home-shell relative flex flex-1 overflow-hidden bg-[#0a0a0c] lg:min-h-0"
    >
      <button
        className={`library-action-button home-library-floating ${
          homeLibraryCollapsed ? "home-library-floating-visible" : "home-library-floating-hidden"
        }`}
        type="button"
        aria-label="Open past components"
        onClick={() => setHomeLibraryCollapsed(false)}
      >
        <Cpu size={18} className="text-white" />
        <span className="font-body text-sm font-semibold text-[#7d9cbd]">Past components</span>
      </button>

      <aside
        className={`home-library-panel thin-scrollbar shrink-0 overflow-y-auto border-r border-white/[0.06] ${
          homeLibraryCollapsed ? "home-library-panel-collapsed" : "home-library-panel-open"
        } ${exiting ? "home-library-exit" : ""}`}
        aria-hidden={homeLibraryCollapsed}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-white/[0.06] bg-[#0d0d0f]/92 px-5 py-4 backdrop-blur-xl">
          <div>
            <h2 className="font-heading text-sm font-semibold text-slate-200">Past components</h2>
            <p className="mt-1 text-xs text-slate-600">Saved choices and generated parts</p>
          </div>
          <button
            aria-label="Collapse past components"
            className="liquid-control grid h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-300"
            type="button"
            onClick={() => setHomeLibraryCollapsed(true)}
            tabIndex={homeLibraryCollapsed ? -1 : 0}
          >
            <ChevronLeft size={15} />
          </button>
        </div>

        <PartLibrarySearchControls
          filterId={componentFilter}
          onFilterChange={setComponentFilter}
          onSearchChange={setComponentSearch}
          search={componentSearch}
          tabIndex={homeLibraryCollapsed ? -1 : 0}
        />

        <div className="space-y-2 p-3">
          {entries.length ? (
            filteredEntries.length ? (
              filteredEntries.map((entry) => {
                const active = entry.id === activeEntryId;
                return (
                  <PartLibraryEntryCard
                    key={entry.id}
                    active={active}
                    entry={entry}
                    variant="home"
                    onRequestDelete={onRequestDelete}
                    onRestore={onRestore}
                    tabIndex={homeLibraryCollapsed ? -1 : 0}
                  />
                );
              })
            ) : (
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.025] px-4 py-5 text-sm leading-6 text-slate-500">
                No saved components match that search or filter.
              </div>
            )
          ) : (
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.025] px-4 py-5 text-sm leading-6 text-slate-500">
              Finished components will appear here so you can reuse them later.
            </div>
          )}
        </div>
      </aside>

      <div
        className={`home-main-panel home-dotted-bg flex min-w-0 flex-1 items-center justify-center px-8 ${
          exiting ? "home-main-exit" : ""
        }`}
        onPointerLeave={resetHomeDots}
        onPointerMove={updateHomeDots}
      >
        <HomeDotField cursor={dotCursor} />
        <div className="w-full max-w-3xl text-center">
          <div className="home-logo-mark mx-auto mb-5 grid h-28 w-28 place-items-center rounded-2xl bg-[#7d9cbd]/12 text-[#a8c4e0]">
            <TraceLabsLogo className="h-20 w-16" />
          </div>
          <h2 className="text-2xl font-semibold text-slate-100">What should Trace Labs add?</h2>
          <p className="mt-3 text-sm leading-6 text-slate-500">
            Ask for a supported circuit block, or open a saved component from the left.
          </p>

          <form className="mt-8" onSubmit={onSubmit}>
            <div className="liquid-control prompt-glow-control flex items-center gap-3 rounded-2xl px-3 py-3 text-left">
              <input
                className="min-w-0 flex-1 bg-transparent px-3 py-2 text-base text-slate-100 outline-none placeholder:text-slate-600"
                value={prompt}
                onChange={(event) => onPromptChange(event.target.value)}
                disabled={!canPrompt || Boolean(busy)}
                placeholder={
                  canPrompt
                    ? "Ask Trace Labs to add a component..."
                    : "Connect a KiCad project to start"
                }
              />
              <button
                className="rounded-xl bg-[#7d9cbd] px-4 py-3 text-sm font-semibold text-white shadow-[0_16px_40px_rgba(125,156,189,0.24)] transition duration-700 hover:bg-[#8aa8c5] disabled:opacity-50"
                disabled={!canPrompt || Boolean(busy) || prompt.trim().length === 0}
                type="submit"
              >
                {busy ? <MiniGradientLoader /> : <Send size={18} />}
              </button>
            </div>
          </form>
          <ProjectConnectionControl
            bridgeStatus={bridgeStatus}
            busy={bridgeBusy}
            projectPath={projectPath}
            setProjectPath={setProjectPath}
            onLinkProject={onLinkProject}
            onRefreshBridge={onRefreshBridge}
          />
        </div>
      </div>
    </section>
  );
}

function PartLibrarySearchControls({
  filterId,
  onFilterChange,
  onSearchChange,
  search,
  tabIndex = 0
}: {
  filterId: PartLibraryFilterId;
  onFilterChange: (filterId: PartLibraryFilterId) => void;
  onSearchChange: (value: string) => void;
  search: string;
  tabIndex?: 0 | -1;
}) {
  const [filterOpen, setFilterOpen] = useState(false);
  const controlsRef = useRef<HTMLDivElement | null>(null);
  const activeFilter =
    PART_LIBRARY_FILTERS.find((filter) => filter.id === filterId) ?? PART_LIBRARY_FILTERS[0];

  useEffect(() => {
    if (tabIndex === -1) setFilterOpen(false);
  }, [tabIndex]);

  useEffect(() => {
    if (!filterOpen) return;

    function handleMouseDown(event: MouseEvent) {
      if (controlsRef.current?.contains(event.target as Node)) return;
      setFilterOpen(false);
    }

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") setFilterOpen(false);
    }

    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [filterOpen]);

  return (
    <div className="border-b border-white/[0.06] p-3" ref={controlsRef}>
      <div className="flex items-center gap-2">
        <label className="liquid-control flex min-w-0 flex-1 items-center gap-2 rounded-lg px-3 py-2">
          <Search size={14} className="shrink-0 text-slate-500" />
          <input
            className="min-w-0 flex-1 bg-transparent text-sm text-slate-200 outline-none placeholder:text-slate-600"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search components"
            type="search"
            tabIndex={tabIndex}
          />
        </label>

        <div className="relative shrink-0">
          <button
            className={`liquid-control flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold text-slate-300 transition hover:text-slate-100 ${
              filterOpen ? "border-[#7d9cbd]/45 bg-[#7d9cbd]/12" : ""
            }`}
            type="button"
            aria-expanded={filterOpen}
            aria-haspopup="menu"
            aria-label={`Filter saved components: ${activeFilter.label}`}
            onClick={() => setFilterOpen((current) => !current)}
            tabIndex={tabIndex}
          >
            <ListFilter size={14} className="text-[#7d9cbd]" />
            <span className="max-w-[3.2rem] truncate">{activeFilter.label}</span>
            <ChevronDown
              size={13}
              className={`text-slate-500 transition-transform ${filterOpen ? "rotate-180" : ""}`}
            />
          </button>

          {filterOpen ? (
            <div
              className="library-filter-dropdown absolute right-0 top-[calc(100%+0.45rem)] z-30 w-44 rounded-lg border border-[#7d9cbd]/25 bg-[#101013] p-1.5 shadow-[0_18px_50px_rgba(0,0,0,0.42)]"
              role="menu"
              aria-label="Filter saved components"
            >
              {PART_LIBRARY_FILTERS.map((filter) => {
                const active = filter.id === filterId;
                return (
                  <button
                    key={filter.id}
                    className={`flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left text-xs font-semibold transition ${
                      active
                        ? "bg-[#7d9cbd]/14 text-[#a8c4e0]"
                        : "text-slate-500 hover:bg-white/[0.045] hover:text-slate-200"
                    }`}
                    type="button"
                    role="menuitemradio"
                    aria-checked={active}
                    onClick={() => {
                      onFilterChange(filter.id);
                      setFilterOpen(false);
                    }}
                    tabIndex={tabIndex}
                  >
                    <span>{filter.label}</span>
                    {active ? <Check size={13} /> : null}
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function PartLibraryEntryCard({
  active,
  entry,
  variant,
  onRequestDelete,
  onRestore,
  tabIndex = 0
}: {
  active: boolean;
  entry: PartLibraryEntry;
  variant: "home" | "drawer";
  onRequestDelete: (entry: PartLibraryEntry) => void;
  onRestore: (entry: PartLibraryEntry) => void;
  tabIndex?: 0 | -1;
}) {
  const isHome = variant === "home";

  return (
    <div
      className={`group relative overflow-hidden rounded-xl border transition duration-500 ${
        active
          ? "border-[#7d9cbd]/45 bg-[#7d9cbd]/14"
          : "border-white/[0.06] bg-white/[0.025] hover:border-white/[0.12] hover:bg-white/[0.045]"
      }`}
    >
      <button
        aria-label={`Open ${entry.title}`}
        className={`w-full text-left transition duration-500 ${
          isHome ? "px-3 py-2.5 pr-12" : "px-4 py-3 pr-12"
        }`}
        type="button"
        onClick={() => onRestore(entry)}
        tabIndex={tabIndex}
      >
        <p className="font-heading truncate text-sm font-semibold text-slate-200">{entry.title}</p>
        <div
          className={`max-h-0 overflow-hidden opacity-0 transition-all duration-500 group-hover:mt-2 group-hover:opacity-100 group-focus-within:mt-2 group-focus-within:opacity-100 ${
            isHome
              ? "group-hover:max-h-36 group-focus-within:max-h-36"
              : "group-hover:max-h-44 group-focus-within:max-h-44"
          }`}
        >
          {!isHome ? (
            <p className="mb-1 text-[11px] font-medium text-slate-600">
              {new Date(entry.updatedAt).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric"
              })}
            </p>
          ) : null}
          <p className="line-clamp-2 text-xs leading-5 text-slate-500">{entry.summary}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {answerSummaryItems(entry.block)
              .slice(0, isHome ? 3 : undefined)
              .map((item) => (
                <span
                  key={`${entry.id}-${item.id}`}
                  className={`font-heading rounded-md px-2 py-1 text-[11px] font-semibold text-slate-500 ${
                    isHome ? "bg-black/18" : "border border-white/[0.06] bg-black/16"
                  }`}
                >
                  {isHome ? (
                    item.value
                  ) : (
                    <>
                      {item.label}: <span className="text-slate-300">{item.value}</span>
                    </>
                  )}
                </span>
              ))}
          </div>
        </div>
      </button>

      <button
        aria-label={`Delete ${entry.title} from past components`}
        className="absolute right-2 top-1/2 z-10 grid h-8 w-8 -translate-y-1/2 translate-x-1 place-items-center rounded-lg border border-red-300/20 bg-red-500/10 text-red-200/80 opacity-0 shadow-[0_10px_24px_rgba(0,0,0,0.28)] transition duration-300 hover:border-red-300/45 hover:bg-red-500/16 hover:text-red-100 hover:opacity-100 focus-visible:translate-x-0 focus-visible:opacity-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-200/35 group-hover:translate-x-0 group-hover:opacity-100 group-focus-within:translate-x-0 group-focus-within:opacity-100"
        title={`Delete ${entry.title}`}
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onRequestDelete(entry);
        }}
        tabIndex={tabIndex}
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}

function DeletePartLibraryEntryDialog({
  entry,
  onCancel,
  onConfirm
}: {
  entry: PartLibraryEntry | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  useEffect(() => {
    if (!entry) return;

    const dismissOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };

    document.addEventListener("keydown", dismissOnEscape);
    return () => document.removeEventListener("keydown", dismissOnEscape);
  }, [entry, onCancel]);

  if (!entry || typeof document === "undefined") return null;

  return createPortal(
    <div
      className="trace-labs-theme component-edit-backdrop fixed inset-0 z-[10000] grid place-items-center bg-black/30 px-4 py-6"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        aria-labelledby="part-library-delete-title"
        aria-modal="true"
        className="component-edit-dialog grid w-full max-w-sm gap-4 rounded-xl border border-red-300/25 bg-[#0d0d0f]/95 p-4 text-sm shadow-[0_22px_70px_rgba(0,0,0,0.62)]"
        role="dialog"
      >
        <div className="flex items-start gap-3">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-red-300/25 bg-red-500/10 text-red-200">
            <Trash2 size={16} />
          </span>
          <div className="min-w-0">
            <h2 id="part-library-delete-title" className="font-heading text-sm font-semibold text-slate-100">
              Delete saved component?
            </h2>
            <p className="mt-2 text-xs leading-5 text-slate-500">
              This removes <span className="font-semibold text-slate-300">{entry.title}</span> from
              past components. The current workspace will stay open.
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <button
            autoFocus
            className="liquid-control rounded-lg px-4 py-2 text-sm font-semibold text-slate-200"
            type="button"
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            className="liquid-control rounded-lg border-red-300/25 bg-red-500/10 px-4 py-2 text-sm font-semibold text-red-100 hover:border-red-300/45 hover:bg-red-500/16"
            type="button"
            onClick={onConfirm}
          >
            Delete
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

function HomeDotField({ cursor }: { cursor: HomeDotCursor }) {
  const influenceRadius = 0.17;

  return (
    <div className="home-dot-field" aria-hidden="true">
      {HOME_DOTS.map((dot) => {
        const dx = cursor.x - dot.x;
        const dy = cursor.y - dot.y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        const influence = cursor.active ? Math.max(0, 1 - distance / influenceRadius) : 0;
        const eased = influence * influence;
        const style = {
          left: `${dot.x * 100}%`,
          top: `${dot.y * 100}%`,
          "--dot-x": `${dx * eased * 82}px`,
          "--dot-y": `${dy * eased * 82}px`,
          "--dot-scale": `${1 + eased * 1.55}`,
          "--dot-opacity": `${0.34 + eased * 0.6}`,
          "--dot-glow": `${eased * 16}px`,
          "--dot-glow-opacity": `${eased * 0.72}`
        } as CSSProperties;

        return <span key={dot.id} className="home-dot" style={style} />;
      })}
    </div>
  );
}

function ChatPane({
  messages,
  busy,
  extractionJob,
  questions,
  answers,
  onAnswerQuestion,
  activeQuestionIndex,
  canPrompt,
  prompt,
  onPromptChange,
  onSubmit,
  blockReady,
  block,
  importResult,
  onInsertMode,
  onNewPart,
  onUpdateAnswer,
  onMessageAnimationComplete
}: {
  messages: ChatMessage[];
  busy: string | null;
  extractionJob: ComponentExtractionJob | null;
  questions: MissingQuestion[];
  answers: Record<string, string>;
  onAnswerQuestion: (question: MissingQuestion, option: Option) => void;
  activeQuestionIndex: number;
  canPrompt: boolean;
  prompt: string;
  onPromptChange: (value: string) => void;
  onSubmit: (event?: FormEvent) => void;
  blockReady: boolean;
  block: CircuitBlock | null;
  importResult: BridgeImportResponse | null;
  onInsertMode: (mode: ImportMode) => void;
  onNewPart: () => void;
  onUpdateAnswer: (answerId: EditableAnswerId, option: Option) => void;
  onMessageAnimationComplete: (messageId: string) => void;
}) {
  return (
    <aside className="flex min-h-[640px] flex-col overflow-hidden border-b border-white/[0.06] bg-[#0d0d0f] lg:min-h-0 lg:border-b-0 lg:border-r">
      <ChatView
        messages={messages}
        busy={busy}
        extractionJob={extractionJob}
        onMessageAnimationComplete={onMessageAnimationComplete}
      />
      {questions.length > 0 ? (
        <div className="animate-fade-slide border-t border-white/[0.08] px-5 py-4">
          <OptionForm
            questions={questions}
            answers={answers}
            onAnswerQuestion={onAnswerQuestion}
            activeQuestionIndex={activeQuestionIndex}
            busy={busy}
          />
        </div>
      ) : blockReady ? (
        <ReadyInsertPanel
          block={block}
          busy={busy}
          importResult={importResult}
          onInsertMode={onInsertMode}
          onNewPart={onNewPart}
          onUpdateAnswer={onUpdateAnswer}
        />
      ) : null}
      {blockReady || questions.length > 0 ? null : (
        <PromptInput
          value={prompt}
          canPrompt={canPrompt}
          onChange={onPromptChange}
          onSubmit={onSubmit}
          busy={busy}
        />
      )}
    </aside>
  );
}

function SchematicWorkspace({
  block,
  documentationBlock,
  busy,
  extractionJob
}: {
  block: CircuitBlock | null;
  documentationBlock: CircuitBlock | null;
  busy: string | null;
  extractionJob: ComponentExtractionJob | null;
}) {
  const generating = busy === "generate" || busy === "extract";
  const [previewMode, setPreviewMode] = useState<PreviewMode>("schematic");
  const [schematicTransform, setSchematicTransform] = useState<SchematicViewportTransform>({ x: 0, y: 0, scale: 1 });
  const activePreviewLabel = previewMode === "footprint" ? "Footprint preview" : "Schematic preview";

  useEffect(() => {
    setPreviewMode("schematic");
    setSchematicTransform({ x: 0, y: 0, scale: 1 });
  }, [block?.id]);

  const zoomSchematic = (factor: number) => {
    setSchematicTransform((current) => ({
      ...current,
      scale: clampNumber(current.scale * factor, SCHEMATIC_MIN_ZOOM, SCHEMATIC_MAX_ZOOM)
    }));
  };

  const resetSchematicViewport = () => {
    setSchematicTransform({ x: 0, y: 0, scale: 1 });
  };

  return (
    <section className="flex min-h-[640px] flex-col overflow-hidden bg-[#0a0a0c] lg:min-h-0">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-4">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-300">{activePreviewLabel}</h2>
        </div>
        {block ? (
          <SchematicViewportControls
            label={activePreviewLabel}
            scale={schematicTransform.scale}
            onZoomOut={() => zoomSchematic(1 / SCHEMATIC_ZOOM_STEP)}
            onZoomIn={() => zoomSchematic(SCHEMATIC_ZOOM_STEP)}
            onReset={resetSchematicViewport}
          />
        ) : null}
      </div>

      <div className="schematic-canvas-bg relative flex min-h-[520px] flex-1 items-center justify-center overflow-hidden px-5 py-8">
        {block ? (
          <button
            type="button"
            className="schematic-preview-toggle"
            aria-label={previewMode === "schematic" ? "Show footprint preview" : "Show schematic preview"}
            onClick={() => setPreviewMode((current) => (current === "schematic" ? "footprint" : "schematic"))}
          >
            {previewMode === "schematic" ? "Footprint" : "Schematic"}
          </button>
        ) : null}
        {block ? (
          previewMode === "footprint" ? (
            <FootprintCanvas
              block={block}
              dimmed={generating}
              transform={schematicTransform}
              onTransformChange={setSchematicTransform}
            />
          ) : (
            <SchematicCanvas
              block={block}
              dimmed={generating}
              transform={schematicTransform}
              onTransformChange={setSchematicTransform}
            />
          )
        ) : generating ? (
          <SchematicGeneratingPreview busy={busy} extractionJob={extractionJob} />
        ) : (
          <EmptySchematicPreview />
        )}
      </div>

      <DocumentationBox block={documentationBlock} extractionJob={extractionJob} />
    </section>
  );
}

function SchematicViewportControls({
  label,
  scale,
  onZoomOut,
  onZoomIn,
  onReset
}: {
  label: string;
  scale: number;
  onZoomOut: () => void;
  onZoomIn: () => void;
  onReset: () => void;
}) {
  const controlLabel = label.toLowerCase();
  return (
    <div className="schematic-viewport-controls" aria-label={`${label} zoom controls`}>
      <button type="button" onClick={onZoomOut} aria-label={`Zoom out ${controlLabel}`}>
        -
      </button>
      <span aria-live="polite">{Math.round(scale * 100)}%</span>
      <button type="button" onClick={onZoomIn} aria-label={`Zoom in ${controlLabel}`}>
        +
      </button>
      <button type="button" onClick={onReset} aria-label={`Reset ${controlLabel} zoom and position`}>
        Reset
      </button>
    </div>
  );
}

function SchematicGeneratingPreview({
  busy,
  extractionJob
}: {
  busy: string | null;
  extractionJob: ComponentExtractionJob | null;
}) {
  return (
    <div className="schematic-loading-preview animate-fade-slide w-full max-w-[620px] rounded-2xl px-8 py-8 text-center">
      <InlineLoadingStatus
        busy={busy === "extract" ? "extract" : "generate"}
        extractionJob={extractionJob}
        className="mx-auto mb-6 justify-center"
      />
      <div className="mx-auto grid max-w-md gap-3">
        <div className="gentle-skeleton h-3 rounded-full" />
        <div className="gentle-skeleton mx-auto h-3 w-4/5 rounded-full" />
        <div className="gentle-skeleton mx-auto h-3 w-2/3 rounded-full" />
      </div>
    </div>
  );
}

function EmptySchematicPreview() {
  return (
    <div className="animate-fade-slide text-center">
      <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-lg border border-white/[0.08] bg-white/[0.04] text-[#7d9cbd]">
        <Cpu />
      </div>
      <h2 className="text-base font-semibold text-slate-200">Waiting for a block</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">
        Answer the required choices and the generated preview will appear here.
      </p>
    </div>
  );
}

function SchematicCanvas({
  block,
  dimmed = false,
  transform,
  onTransformChange
}: {
  block: CircuitBlock;
  dimmed?: boolean;
  transform: SchematicViewportTransform;
  onTransformChange: SchematicViewportTransformUpdater;
}) {
  if (block.extraction_status === "ready" && block.reference_extraction) {
    return (
      <ExtractedSchematicCanvas
        block={block}
        dimmed={dimmed}
        transform={transform}
        onTransformChange={onTransformChange}
      />
    );
  }

  return (
    <GenericDraftSchematicCanvas
      block={block}
      dimmed={dimmed}
      transform={transform}
      onTransformChange={onTransformChange}
    />
  );
}

type KicadSexprNode = string | KicadSexprNode[];

type ParsedFootprintPad = {
  name: string;
  title: string;
  shape: string;
  x: number;
  y: number;
  width: number;
  height: number;
  rotation: number;
  roundRatio: number;
  layer: string;
};

type ParsedFootprintLine = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  width: number;
  layer: string;
};

type ParsedFootprintRect = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  width: number;
  layer: string;
};

type ParsedFootprintCircle = {
  cx: number;
  cy: number;
  radius: number;
  width: number;
  layer: string;
};

type ParsedFootprintArc = {
  startX: number;
  startY: number;
  midX: number;
  midY: number;
  endX: number;
  endY: number;
  width: number;
  layer: string;
};

type ParsedFootprintPoly = {
  points: Array<{ x: number; y: number }>;
  width: number;
  layer: string;
};

type ParsedKicadFootprint = {
  name: string;
  pads: ParsedFootprintPad[];
  lines: ParsedFootprintLine[];
  rects: ParsedFootprintRect[];
  circles: ParsedFootprintCircle[];
  arcs: ParsedFootprintArc[];
  polys: ParsedFootprintPoly[];
  bounds: FootprintBounds;
};

type FootprintBounds = {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
};

function FootprintCanvas({
  block,
  dimmed = false,
  transform,
  onTransformChange
}: {
  block: CircuitBlock;
  dimmed?: boolean;
  transform: SchematicViewportTransform;
  onTransformChange: SchematicViewportTransformUpdater;
}) {
  const component = block.main_component;
  const asset = component.footprint_asset;
  const parsed = useMemo(() => {
    if (!asset?.kicad_mod) return null;
    return parseKicadModFootprint(asset.kicad_mod, block.reference_extraction?.pins ?? []);
  }, [asset?.kicad_mod, block.reference_extraction?.pins]);
  const confidence = (asset?.confidence || component.footprint_confidence).replace(/_/g, " ");
  const sourceLabel = footprintSourceLabel(block);
  const sourceDetail = asset?.source_path || asset?.source_project || "KiCad footprint source";

  return (
    <div
      className={`schematic-card w-full max-w-[900px] animate-pop-in transition duration-500 ${
        dimmed ? "scale-[0.985] opacity-55" : "opacity-100"
      }`}
    >
      <InteractiveSchematicViewport
        width={760}
        height={520}
        ariaLabel={`${component.value} footprint preview`}
        transform={transform}
        onTransformChange={onTransformChange}
      >
        <rect x="0" y="0" width="760" height="520" rx="8" fill="transparent" />
        <g fill="none" strokeLinecap="round" strokeLinejoin="round">
          <text x="380" y="48" textAnchor="middle" fill="#a8c4e0" fontSize="22" fontWeight="800">
            {component.value}
          </text>
          <text x="380" y="72" textAnchor="middle" fill="#cbd5e1" fontSize="13" fontWeight="700">
            {truncateLabel(asset?.footprint_id || component.footprint || "Footprint pending", 66)}
          </text>
          <text x="380" y="94" textAnchor="middle" fill="#7b8494" fontSize="11">
            {sourceLabel} - {confidence}
          </text>

          {parsed ? <RealKicadFootprintDrawing footprint={parsed} /> : <MissingFootprintGeometry component={component} />}

          <g transform="translate(102 474)" fontSize="11" fontWeight="700">
            <LegendDot color="#fbbf24" label="Pin 1" x={0} />
            <LegendDot color="#7d9cbd" label="Pads" x={94} />
            <LegendDot color="#9da3ae" label="Silk/Fab" x={188} />
          </g>
          <text x="658" y="477" textAnchor="end" fill="#7b8494" fontSize="11">
            {truncateLabel(sourceDetail, 54)}
          </text>
        </g>
      </InteractiveSchematicViewport>
    </div>
  );
}

function RealKicadFootprintDrawing({ footprint }: { footprint: ParsedKicadFootprint }) {
  const bounds = footprint.bounds;
  const width = Math.max(1, bounds.maxX - bounds.minX);
  const height = Math.max(1, bounds.maxY - bounds.minY);
  const scale = Math.min(58, 560 / width, 330 / height);
  const centerX = bounds.minX + width / 2;
  const centerY = bounds.minY + height / 2;

  return (
    <g aria-label="Real KiCad footprint geometry">
      <text x="380" y="126" textAnchor="middle" fill="#687386" fontSize="10" fontWeight="700">
        Real KiCad footprint geometry from .kicad_mod
      </text>
      <g transform={`translate(380 292) scale(${scale}) translate(${-centerX} ${-centerY})`}>
        {footprint.rects.map((rect, index) => (
          <rect
            key={`rect-${index}`}
            x={Math.min(rect.x1, rect.x2)}
            y={Math.min(rect.y1, rect.y2)}
            width={Math.abs(rect.x2 - rect.x1)}
            height={Math.abs(rect.y2 - rect.y1)}
            fill="none"
            stroke={footprintLayerColor(rect.layer)}
            strokeWidth={Math.max(rect.width, 0.05)}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {footprint.polys.map((poly, index) => (
          <polygon
            key={`poly-${index}`}
            points={poly.points.map((point) => `${point.x},${point.y}`).join(" ")}
            fill="rgba(157, 163, 174, 0.05)"
            stroke={footprintLayerColor(poly.layer)}
            strokeWidth={Math.max(poly.width, 0.05)}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {footprint.circles.map((circle, index) => (
          <circle
            key={`circle-${index}`}
            cx={circle.cx}
            cy={circle.cy}
            r={circle.radius}
            fill="none"
            stroke={footprintLayerColor(circle.layer)}
            strokeWidth={Math.max(circle.width, 0.05)}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {footprint.arcs.map((arc, index) => (
          <path
            key={`arc-${index}`}
            d={`M${arc.startX} ${arc.startY} Q${arc.midX} ${arc.midY} ${arc.endX} ${arc.endY}`}
            fill="none"
            stroke={footprintLayerColor(arc.layer)}
            strokeWidth={Math.max(arc.width, 0.05)}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {footprint.lines.map((line, index) => (
          <line
            key={`line-${index}`}
            x1={line.x1}
            y1={line.y1}
            x2={line.x2}
            y2={line.y2}
            stroke={footprintLayerColor(line.layer)}
            strokeWidth={Math.max(line.width, 0.05)}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {footprint.pads.map((pad, index) => (
          <KicadFootprintPad key={`${pad.name}-${index}`} pad={pad} pinOne={pad.name === "1" || index === 0} />
        ))}
      </g>
    </g>
  );
}

function KicadFootprintPad({ pad, pinOne }: { pad: ParsedFootprintPad; pinOne: boolean }) {
  const fill = pinOne ? "#fbbf24" : "#7d9cbd";
  const stroke = pinOne ? "#fde68a" : "#a8c4e0";
  const rx = pad.shape === "circle" || pad.shape === "oval" ? Math.min(pad.width, pad.height) / 2 : pad.width * pad.roundRatio;
  const fontSize = clampNumber(Math.min(pad.width, pad.height) * 0.38, 0.22, 0.72);
  return (
    <g
      className="footprint-pad-group"
      tabIndex={0}
      aria-label={pad.title}
      transform={`translate(${pad.x} ${pad.y}) rotate(${pad.rotation})`}
    >
      <title>{pad.title}</title>
      {pad.shape === "circle" ? (
        <ellipse
          className="footprint-pad"
          cx="0"
          cy="0"
          rx={pad.width / 2}
          ry={pad.height / 2}
          fill={fill}
          fillOpacity="0.9"
          stroke={stroke}
          strokeWidth="0.05"
          vectorEffect="non-scaling-stroke"
        />
      ) : (
        <rect
          className="footprint-pad"
          x={-pad.width / 2}
          y={-pad.height / 2}
          width={pad.width}
          height={pad.height}
          rx={rx}
          fill={fill}
          fillOpacity={pinOne ? "0.95" : "0.82"}
          stroke={stroke}
          strokeWidth="0.05"
          vectorEffect="non-scaling-stroke"
        />
      )}
      <text
        x="0"
        y={fontSize * 0.34}
        textAnchor="middle"
        fill="#071018"
        fontSize={fontSize}
        fontWeight="800"
        pointerEvents="none"
      >
        {truncateLabel(pad.name, 5)}
      </text>
    </g>
  );
}

function MissingFootprintGeometry({ component }: { component: Component }) {
  return (
    <g transform="translate(380 286)" textAnchor="middle">
      <rect x="-220" y="-84" width="440" height="168" rx="12" fill="#101216" stroke="#333a44" />
      <text x="0" y="-26" fill="#fbbf24" fontSize="16" fontWeight="800">
        No real footprint geometry attached
      </text>
      <text x="0" y="2" fill="#cbd5e1" fontSize="12" fontWeight="700">
        {truncateLabel(component.footprint || "Footprint pending", 54)}
      </text>
      <text x="0" y="28" fill="#7b8494" fontSize="11">
        Download a KiCad footprint candidate before visual verification.
      </text>
    </g>
  );
}

function parseKicadModFootprint(text: string, pins: PinDefinition[]): ParsedKicadFootprint | null {
  const root = parseKicadSexpr(text).find((node) => sexprHead(node) === "footprint");
  if (!isSexprList(root)) return null;
  const pinByNumber = new Map(pins.map((pin) => [pin.number, pin]));
  const pads = sexprChildren(root, "pad").map((node) => parseKicadPad(node, pinByNumber)).filter(isDefined);
  const lines = sexprChildren(root, "fp_line").map(parseKicadLine).filter(isDefined);
  const rects = sexprChildren(root, "fp_rect").map(parseKicadRect).filter(isDefined);
  const circles = sexprChildren(root, "fp_circle").map(parseKicadCircle).filter(isDefined);
  const arcs = sexprChildren(root, "fp_arc").map(parseKicadArc).filter(isDefined);
  const polys = sexprChildren(root, "fp_poly").map(parseKicadPoly).filter(isDefined);
  const bounds = footprintBounds(pads, lines, rects, circles, arcs, polys);

  return {
    name: sexprAtom(root[1]) ?? "footprint",
    pads,
    lines,
    rects,
    circles,
    arcs,
    polys,
    bounds
  };
}

function parseKicadSexpr(text: string): KicadSexprNode[] {
  const tokens = tokenizeKicadSexpr(text);
  const nodes: KicadSexprNode[] = [];
  let index = 0;
  while (index < tokens.length) {
    const parsed = parseKicadNode(tokens, index);
    if (!parsed) break;
    nodes.push(parsed.node);
    index = parsed.nextIndex;
  }
  return nodes;
}

function tokenizeKicadSexpr(text: string) {
  const tokens = text.match(/"(?:(?:\\.)|[^"\\])*"|[()]|[^\s()]+/g) ?? [];
  return tokens.map((token) => {
    if (!token.startsWith('"')) return token;
    return token.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  });
}

function parseKicadNode(
  tokens: string[],
  startIndex: number
): { node: KicadSexprNode; nextIndex: number } | null {
  const token = tokens[startIndex];
  if (!token) return null;
  if (token !== "(") return { node: token, nextIndex: startIndex + 1 };
  const list: KicadSexprNode[] = [];
  let index = startIndex + 1;
  while (index < tokens.length && tokens[index] !== ")") {
    const parsed = parseKicadNode(tokens, index);
    if (!parsed) return null;
    list.push(parsed.node);
    index = parsed.nextIndex;
  }
  return { node: list, nextIndex: index + 1 };
}

function parseKicadPad(
  node: KicadSexprNode[],
  pinByNumber: Map<string, PinDefinition>
): ParsedFootprintPad | null {
  const name = sexprAtom(node[1]);
  const shape = sexprAtom(node[3]) ?? "rect";
  const at = sexprChild(node, "at");
  const size = sexprChild(node, "size");
  if (!name || !at || !size) return null;
  const x = sexprNumber(at[1]) ?? 0;
  const y = sexprNumber(at[2]) ?? 0;
  const width = Math.max(0.05, sexprNumber(size[1]) ?? 0.4);
  const height = Math.max(0.05, sexprNumber(size[2]) ?? width);
  const pin = pinByNumber.get(name);
  const net = sexprChild(node, "net");
  const netName = sexprAtom(net?.[2]) ?? pin?.net_name ?? "";
  const pinName = pin?.name ? ` ${pin.name}` : "";
  const netLabel = netName ? ` - ${netName}` : "";
  return {
    name,
    title: `Pad ${name}${pinName}${netLabel}`,
    shape,
    x,
    y,
    width,
    height,
    rotation: sexprNumber(at[3]) ?? 0,
    roundRatio: sexprNumber(sexprChild(node, "roundrect_rratio")?.[1]) ?? (shape === "roundrect" ? 0.25 : 0),
    layer: sexprAtom(sexprChild(node, "layers")?.[1]) ?? "F.Cu"
  };
}

function parseKicadLine(node: KicadSexprNode[]): ParsedFootprintLine | null {
  const start = sexprChild(node, "start");
  const end = sexprChild(node, "end");
  if (!start || !end) return null;
  return {
    x1: sexprNumber(start[1]) ?? 0,
    y1: sexprNumber(start[2]) ?? 0,
    x2: sexprNumber(end[1]) ?? 0,
    y2: sexprNumber(end[2]) ?? 0,
    width: sexprNumber(sexprChild(sexprChild(node, "stroke"), "width")?.[1]) ?? 0.12,
    layer: sexprAtom(sexprChild(node, "layer")?.[1]) ?? "F.Fab"
  };
}

function parseKicadRect(node: KicadSexprNode[]): ParsedFootprintRect | null {
  const start = sexprChild(node, "start");
  const end = sexprChild(node, "end");
  if (!start || !end) return null;
  return {
    x1: sexprNumber(start[1]) ?? 0,
    y1: sexprNumber(start[2]) ?? 0,
    x2: sexprNumber(end[1]) ?? 0,
    y2: sexprNumber(end[2]) ?? 0,
    width: sexprNumber(sexprChild(sexprChild(node, "stroke"), "width")?.[1]) ?? 0.1,
    layer: sexprAtom(sexprChild(node, "layer")?.[1]) ?? "F.Fab"
  };
}

function parseKicadCircle(node: KicadSexprNode[]): ParsedFootprintCircle | null {
  const center = sexprChild(node, "center");
  const end = sexprChild(node, "end");
  if (!center || !end) return null;
  const cx = sexprNumber(center[1]) ?? 0;
  const cy = sexprNumber(center[2]) ?? 0;
  const ex = sexprNumber(end[1]) ?? cx;
  const ey = sexprNumber(end[2]) ?? cy;
  return {
    cx,
    cy,
    radius: Math.hypot(ex - cx, ey - cy),
    width: sexprNumber(sexprChild(sexprChild(node, "stroke"), "width")?.[1]) ?? 0.1,
    layer: sexprAtom(sexprChild(node, "layer")?.[1]) ?? "F.Fab"
  };
}

function parseKicadArc(node: KicadSexprNode[]): ParsedFootprintArc | null {
  const start = sexprChild(node, "start");
  const mid = sexprChild(node, "mid");
  const end = sexprChild(node, "end");
  if (!start || !mid || !end) return null;
  return {
    startX: sexprNumber(start[1]) ?? 0,
    startY: sexprNumber(start[2]) ?? 0,
    midX: sexprNumber(mid[1]) ?? 0,
    midY: sexprNumber(mid[2]) ?? 0,
    endX: sexprNumber(end[1]) ?? 0,
    endY: sexprNumber(end[2]) ?? 0,
    width: sexprNumber(sexprChild(sexprChild(node, "stroke"), "width")?.[1]) ?? 0.1,
    layer: sexprAtom(sexprChild(node, "layer")?.[1]) ?? "F.Fab"
  };
}

function parseKicadPoly(node: KicadSexprNode[]): ParsedFootprintPoly | null {
  const pts = sexprChild(node, "pts");
  if (!pts) return null;
  const points = sexprChildren(pts, "xy")
    .map((point) => ({
      x: sexprNumber(point[1]) ?? 0,
      y: sexprNumber(point[2]) ?? 0
    }))
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (!points.length) return null;
  return {
    points,
    width: sexprNumber(sexprChild(sexprChild(node, "stroke"), "width")?.[1]) ?? 0.1,
    layer: sexprAtom(sexprChild(node, "layer")?.[1]) ?? "F.Fab"
  };
}

function footprintBounds(
  pads: ParsedFootprintPad[],
  lines: ParsedFootprintLine[],
  rects: ParsedFootprintRect[],
  circles: ParsedFootprintCircle[],
  arcs: ParsedFootprintArc[],
  polys: ParsedFootprintPoly[]
): FootprintBounds {
  const points: Array<{ x: number; y: number }> = [];
  pads.forEach((pad) => {
    points.push(
      { x: pad.x - pad.width / 2, y: pad.y - pad.height / 2 },
      { x: pad.x + pad.width / 2, y: pad.y + pad.height / 2 }
    );
  });
  lines.forEach((line) => {
    points.push({ x: line.x1, y: line.y1 }, { x: line.x2, y: line.y2 });
  });
  rects.forEach((rect) => {
    points.push({ x: rect.x1, y: rect.y1 }, { x: rect.x2, y: rect.y2 });
  });
  circles.forEach((circle) => {
    points.push(
      { x: circle.cx - circle.radius, y: circle.cy - circle.radius },
      { x: circle.cx + circle.radius, y: circle.cy + circle.radius }
    );
  });
  arcs.forEach((arc) => {
    points.push(
      { x: arc.startX, y: arc.startY },
      { x: arc.midX, y: arc.midY },
      { x: arc.endX, y: arc.endY }
    );
  });
  polys.forEach((poly) => points.push(...poly.points));
  if (!points.length) {
    return { minX: -3, minY: -3, maxX: 3, maxY: 3 };
  }
  return {
    minX: Math.min(...points.map((point) => point.x)) - 0.8,
    minY: Math.min(...points.map((point) => point.y)) - 0.8,
    maxX: Math.max(...points.map((point) => point.x)) + 0.8,
    maxY: Math.max(...points.map((point) => point.y)) + 0.8
  };
}

function sexprHead(node: KicadSexprNode | undefined) {
  return isSexprList(node) ? sexprAtom(node[0]) : null;
}

function sexprAtom(node: KicadSexprNode | undefined) {
  return typeof node === "string" ? node : null;
}

function sexprNumber(node: KicadSexprNode | undefined) {
  const atom = sexprAtom(node);
  if (atom === null) return null;
  const value = Number(atom);
  return Number.isFinite(value) ? value : null;
}

function sexprChild(node: KicadSexprNode[] | undefined, head: string) {
  return node?.find((child): child is KicadSexprNode[] => sexprHead(child) === head);
}

function sexprChildren(node: KicadSexprNode[] | undefined, head: string) {
  return (node ?? []).filter((child): child is KicadSexprNode[] => sexprHead(child) === head);
}

function isSexprList(node: KicadSexprNode | undefined): node is KicadSexprNode[] {
  return Array.isArray(node);
}

function isDefined<T>(value: T | null | undefined): value is T {
  return value !== null && value !== undefined;
}

function footprintLayerColor(layer: string) {
  if (layer.includes("Cu") || layer.includes("Mask") || layer.includes("Paste")) return "#7d9cbd";
  if (layer.includes("Silk")) return "#cbd5e1";
  if (layer.includes("Fab")) return "#9da3ae";
  if (layer.includes("CrtYd")) return "#5f9277";
  return "#8290a6";
}

function footprintSourceLabel(block: CircuitBlock) {
  const asset = block.main_component.footprint_asset;
  if (asset?.kicad_mod) {
    if (asset.source_kind.includes("bundled")) return "Bundled KiCad footprint";
    return asset.source_kind.includes("supplier")
      ? "Downloaded supplier KiCad footprint"
      : "Downloaded KiCad footprint";
  }
  const confidence = block.main_component.footprint_confidence.toLowerCase();
  const reason = block.main_component.assignment_reason.toLowerCase();
  if (confidence.includes("downloaded") || reason.includes("downloaded")) {
    return "Downloaded KiCad footprint candidate";
  }
  if (block.recipe_source === "ai_proposed") {
    return "Online CAD lookup footprint candidate";
  }
  return "Assigned KiCad footprint candidate";
}

type SchematicViewportTransform = {
  x: number;
  y: number;
  scale: number;
};

type SchematicViewportTransformUpdater = (
  next: SchematicViewportTransform | ((current: SchematicViewportTransform) => SchematicViewportTransform)
) => void;

function InteractiveSchematicViewport({
  width,
  height,
  ariaLabel,
  transform,
  onTransformChange,
  children
}: {
  width: number;
  height: number;
  ariaLabel: string;
  transform: SchematicViewportTransform;
  onTransformChange: SchematicViewportTransformUpdater;
  children: ReactNode;
}) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    pointerId: number;
    startClientX: number;
    startClientY: number;
    originX: number;
    originY: number;
    unitsPerPixel: number;
  } | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    onTransformChange({ x: 0, y: 0, scale: 1 });
    setDragging(false);
    dragRef.current = null;
  }, [ariaLabel, width, height, onTransformChange]);

  const unitsPerPixel = () => {
    const rect = viewportRef.current?.getBoundingClientRect();
    if (!rect?.width || !rect.height) return 1;
    return Math.max(width / rect.width, height / rect.height);
  };

  const zoomTo = (nextScale: number, anchor?: { clientX: number; clientY: number }) => {
    onTransformChange((current) => {
      const scale = clampNumber(nextScale, SCHEMATIC_MIN_ZOOM, SCHEMATIC_MAX_ZOOM);
      const rect = viewportRef.current?.getBoundingClientRect();
      if (!anchor || !rect?.width || !rect.height) {
        return { ...current, scale };
      }
      const units = Math.max(width / rect.width, height / rect.height);
      const anchorX = (anchor.clientX - rect.left - rect.width / 2) * units;
      const anchorY = (anchor.clientY - rect.top - rect.height / 2) * units;
      const ratio = scale / current.scale;
      return {
        scale,
        x: anchorX - (anchorX - current.x) * ratio,
        y: anchorY - (anchorY - current.y) * ratio
      };
    });
  };

  const zoomBy = (factor: number) => {
    zoomTo(transform.scale * factor);
  };

  const resetViewport = () => {
    onTransformChange({ x: 0, y: 0, scale: 1 });
  };

  const handleWheel = (event: WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    const factor = event.deltaY < 0 ? SCHEMATIC_ZOOM_STEP : 1 / SCHEMATIC_ZOOM_STEP;
    zoomTo(transform.scale * factor, { clientX: event.clientX, clientY: event.clientY });
  };

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement | null;
    if (event.button !== 0 || target?.closest("button")) return;
    dragRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originX: transform.x,
      originY: transform.y,
      unitsPerPixel: unitsPerPixel()
    };
    setDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    onTransformChange((current) => ({
      ...current,
      x: drag.originX + (event.clientX - drag.startClientX) * drag.unitsPerPixel,
      y: drag.originY + (event.clientY - drag.startClientY) * drag.unitsPerPixel
    }));
  };

  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) {
      dragRef.current = null;
      setDragging(false);
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const panAmount = 24 * unitsPerPixel();
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoomBy(SCHEMATIC_ZOOM_STEP);
      return;
    }
    if (event.key === "-" || event.key === "_") {
      event.preventDefault();
      zoomBy(1 / SCHEMATIC_ZOOM_STEP);
      return;
    }
    if (event.key === "0") {
      event.preventDefault();
      resetViewport();
      return;
    }
    const panByKey: Record<string, [number, number]> = {
      ArrowLeft: [panAmount, 0],
      ArrowRight: [-panAmount, 0],
      ArrowUp: [0, panAmount],
      ArrowDown: [0, -panAmount]
    };
    const delta = panByKey[event.key];
    if (!delta) return;
    event.preventDefault();
    onTransformChange((current) => ({ ...current, x: current.x + delta[0], y: current.y + delta[1] }));
  };

  const svgTransform = `translate(${width / 2 + transform.x} ${height / 2 + transform.y}) scale(${transform.scale}) translate(${
    -width / 2
  } ${-height / 2})`;

  return (
    <div
      ref={viewportRef}
      className={`schematic-viewport ${dragging ? "schematic-viewport-dragging" : ""}`}
      role="region"
      aria-label={`${ariaLabel}. Drag to pan, use the mouse wheel or buttons to zoom, and double-click to reset.`}
      tabIndex={0}
      onWheel={handleWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={resetViewport}
      onKeyDown={handleKeyDown}
    >
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="schematic-viewport-svg"
        role="img"
        aria-label={ariaLabel}
      >
        <g transform={svgTransform}>{children}</g>
      </svg>
    </div>
  );
}

function ExtractedSchematicCanvas({
  block,
  dimmed = false,
  transform,
  onTransformChange
}: {
  block: CircuitBlock;
  dimmed?: boolean;
  transform: SchematicViewportTransform;
  onTransformChange: SchematicViewportTransformUpdater;
}) {
  const extraction = block.reference_extraction;
  if (!extraction) {
    return (
      <GenericDraftSchematicCanvas
        block={block}
        dimmed={dimmed}
        transform={transform}
        onTransformChange={onTransformChange}
      />
    );
  }

  const pins = extraction.pins.slice(0, 32);
  const noConnectPins = pins.filter(isNoConnectPin);
  const renderedPins = pins.filter((pin) => !isNoConnectPin(pin));
  const supports = block.support_components.slice(0, 10);
  const leftPins = renderedPins.filter((pin) => extractedPinSide(pin) === "left");
  const rightPins = renderedPins.filter((pin) => extractedPinSide(pin) === "right");
  const maxPinRows = Math.max(leftPins.length, rightPins.length, 1);
  const densePins = maxPinRows > 10;
  const longestPinText = Math.max(
    0,
    ...renderedPins.map((pin) => `${pin.number} ${pin.name} ${pin.net_name}`.length)
  );
  const bodyWidth = Math.min(360, Math.max(276, 168 + longestPinText * (densePins ? 4.4 : 5.1)));
  const pinPitch = densePins ? 28 : 36;
  const headerHeight = 74;
  const bodyHeight = Math.min(560, Math.max(280, headerHeight + maxPinRows * pinPitch + 52));
  const bodyTop = 104;
  const bodyBottom = bodyTop + bodyHeight;
  const bodyX = 430 - bodyWidth / 2;
  const bodyCenterX = bodyX + bodyWidth / 2;
  const railStartX = 84;
  const railEndX = 790;
  const pinY = (index: number, count: number) => {
    const start = bodyTop + headerHeight + 12;
    if (count <= 1) return start;
    const usable = Math.max(pinPitch, bodyHeight - headerHeight - 32);
    return start + (usable * index) / (count - 1);
  };
  const pinRows = [
    ...leftPins.map((pin, index) => ({
      pin,
      side: "left" as const,
      x: bodyX,
      y: pinY(index, leftPins.length)
    })),
    ...rightPins.map((pin, index) => ({
      pin,
      side: "right" as const,
      x: bodyX + bodyWidth,
      y: pinY(index, rightPins.length)
    }))
  ];
  const pinRowsByNet = new Map<string, typeof pinRows>();
  pinRows.forEach((row) => {
    pinRowsByNet.set(row.pin.net_name, [...(pinRowsByNet.get(row.pin.net_name) ?? []), row]);
  });
  const netRoleByName = new Map(extraction.nets.map((net) => [net.name, net.role]));
  const roleForNet = (net: string): CircuitNet["role"] => netRoleByName.get(net) ?? "other";
  const netIsGround = (net: string) => roleForNet(net) === "ground" || isGroundNet(net);
  const netIsPower = (net: string) => {
    const role = roleForNet(net);
    return role === "power" || role === "ground" || isPowerNet(net);
  };
  const netColor = (net: string) => extractedNetColor(net, roleForNet(net));
  const supportNets = supports.flatMap((component) => component.connects);
  const powerNets = uniqueStrings([...block.external_nets, ...supportNets, ...renderedPins.map((pin) => pin.net_name)])
    .filter((net) => netIsPower(net) && !netIsGround(net))
    .slice(0, 3);
  const powerRailYs = new Map(powerNets.map((net, index) => [net, 36 + index * 22]));
  const isResistorSupport = (component: SupportComponent) =>
    component.type.toLowerCase().includes("resistor") || component.symbol.toLowerCase() === "device:r";
  const isCapacitorSupport = (component: SupportComponent) =>
    component.type.toLowerCase().includes("capacitor") || component.symbol.toLowerCase() === "device:c";
  const isInductorSupport = (component: SupportComponent) =>
    component.type.toLowerCase().includes("inductor") || component.symbol.toLowerCase() === "device:l";
  const isPullResistorSupport = (component: SupportComponent) => {
    const purpose = component.purpose.toLowerCase();
    return /pull[-\s]?up|pull[-\s]?down/.test(purpose);
  };
  const isGroundedSupport = (component: SupportComponent) => component.connects.some(netIsGround);
  const isShuntCapacitor = (component: SupportComponent) =>
    isCapacitorSupport(component) && isGroundedSupport(component);
  const capacitorSupports = supports.filter(isShuntCapacitor);
  const pullResistorSupports = supports.filter((component) => {
    if (!isResistorSupport(component)) return false;
    return Boolean(
      isPullResistorSupport(component) &&
        component.connects.find((net) => netIsPower(net) && !netIsGround(net)) &&
        component.connects.find((net) => !netIsPower(net) && !netIsGround(net))
    );
  });
  const shouldRailShuntSupport = (component: SupportComponent, otherNet: string) =>
    netIsGround(otherNet) ||
    isPullResistorSupport(component) ||
    (isCapacitorSupport(component) && isGroundedSupport(component));
  const genericSupports = supports.filter(
    (component) => !capacitorSupports.includes(component) && !pullResistorSupports.includes(component)
  );
  const supportAnchorFor = (component: SupportComponent) => {
    for (const net of component.connects) {
      const row = pinRowsByNet.get(net)?.[0];
      if (row) return { net, row };
    }
    return null;
  };
  const bottomGenericSupports = genericSupports
    .map((component, index) => ({ component, index }))
    .filter(({ component }) => !supportAnchorFor(component));
  const groundRailY = bodyBottom + 154;
  const genericRowY = groundRailY + 110;
  const svgHeight = Math.max(620, genericRowY + Math.ceil(bottomGenericSupports.length / 3) * 82 + 58);
  const packageLabel = extraction.package || "package TBD";
  const interfaceLabel = extraction.interface || "interface extracted";
  const sourceIds = extraction.source_chunks.slice(0, 4).map((chunk) => chunk.chunk_id);
  const railYForNet = (net: string) => {
    if (netIsGround(net)) return groundRailY;
    return powerRailYs.get(net);
  };
  const signalLabelX = (side: "left" | "right") => (side === "left" ? 76 : 784);
  const wireLaneGap = 32;
  const supportWireX = (pinX: number, side: "left" | "right", index: number) =>
    side === "left"
      ? clampNumber(pinX - 142 - index * 84, 48, pinX - wireLaneGap * 4)
      : clampNumber(pinX + 142 + index * 84, pinX + wireLaneGap * 4, 820);
  const capacitorPlacements = (() => {
    const sideSlots = { left: 0, right: 0 };
    return capacitorSupports.map((component, index) => {
      const topNet = component.connects.find((net) => !netIsGround(net)) ?? component.connects[0] ?? "REVIEW";
      const bottomNet = component.connects.find(netIsGround) ?? component.connects[1] ?? "GND";
      const topRailY = railYForNet(topNet);
      const topPin = pinRowsByNet.get(topNet)?.[0];
      const side = topPin?.side ?? "left";
      const slot = sideSlots[side]++;
      const topConnectY = topPin?.y ?? topRailY ?? bodyBottom + 24;
      const x = topPin ? supportWireX(topPin.x, side, slot) : clampNumber(railStartX + 72 + slot * 34, 104, 756);
      const lane = Math.floor(slot / 2);
      return {
        component,
        index,
        topNet,
        bottomNet,
        topPin,
        side,
        x,
        topConnectY,
        y: topConnectY + 52 + lane * 62
      };
    });
  })();
  const pinNameFontSize = densePins ? 10 : 11;
  const pinNetFontSize = densePins ? 9 : 10;
  const noConnectSummary = noConnectPins.length
    ? `NC/DNC omitted: ${noConnectPins.map((pin) => pin.number).join(", ")}`
    : "";

  return (
    <div
      className={`schematic-card w-full max-w-[960px] animate-pop-in transition duration-500 ${
        dimmed ? "scale-[0.985] opacity-55" : "opacity-100"
      }`}
    >
      <InteractiveSchematicViewport
        width={860}
        height={svgHeight}
        ariaLabel={`${block.main_component.value} extracted schematic preview`}
        transform={transform}
        onTransformChange={onTransformChange}
      >
        <rect x="0" y="0" width="860" height={svgHeight} rx="8" fill="transparent" />
        <g fill="none" strokeLinecap="round" strokeLinejoin="round">
          {powerNets.map((net) => {
            const y = powerRailYs.get(net) ?? 48;
            return (
              <g key={`rail-${net}`}>
                <path d={`M${railStartX} ${y}H${railEndX}`} stroke={netColor(net)} strokeWidth="2.6" />
                <text x={railStartX - 16} y={y - 7} fill={netColor(net)} fontSize="14" fontWeight="700">
                  {net}
                </text>
              </g>
            );
          })}
          <path d={`M${railStartX} ${groundRailY}H${railEndX}`} stroke={netColor("GND")} strokeWidth="2.6" />
          <text x={railStartX - 14} y={groundRailY + 20} fill={netColor("GND")} fontSize="14" fontWeight="700">
            GND
          </text>

          <rect x={bodyX} y={bodyTop} width={bodyWidth} height={bodyHeight} rx="8" fill="#101216" stroke="#333a44" strokeWidth="2" />
          <text x={bodyCenterX} y={bodyTop + 30} fill="#a8c4e0" fontSize="22" fontWeight="700" textAnchor="middle">
            {block.main_component.value}
          </text>
          <text x={bodyCenterX} y={bodyTop + 52} fill="#8290a6" fontSize="12" fontWeight="700" textAnchor="middle">
            {truncateLabel(packageLabel, 44)}
          </text>
          <text x={bodyCenterX} y={bodyTop + 68} fill="#7b8494" fontSize="10" textAnchor="middle">
            {truncateLabel(interfaceLabel, 52)}
          </text>

          {pinRows.map((row, rowIndex) => {
            const { pin, side, x, y } = row;
            const color = netColor(pin.net_name);
            const labelX = side === "left" ? bodyX + 14 : bodyX + bodyWidth - 14;
            const labelAnchor = side === "left" ? "start" : "end";
            const railY = railYForNet(pin.net_name);
            const outsideX =
              side === "left"
                ? bodyX - 42 - (rowIndex % 3) * wireLaneGap
                : bodyX + bodyWidth + 42 + (rowIndex % 3) * wireLaneGap;
            const externalX = signalLabelX(side);
            const signal = railY === undefined;
            return (
              <g key={`${side}-${pin.number}-${pin.name}`}>
                {signal ? (
                  <>
                    <path d={`M${x} ${y}H${externalX}`} stroke={color} strokeWidth="2.5" />
                    <text
                      x={side === "left" ? externalX - 8 : externalX + 8}
                      y={y - 7}
                      textAnchor={side === "left" ? "end" : "start"}
                      fill={color}
                      fontSize="12"
                      fontWeight="700"
                    >
                      {truncateLabel(pin.net_name, 18)}
                    </text>
                  </>
                ) : (
                  <>
                    <path d={`M${x} ${y}H${outsideX}V${railY}`} stroke={color} strokeWidth="2.5" />
                    <circle cx={outsideX} cy={railY} r="4" fill={color} />
                  </>
                )}
                <circle cx={x} cy={y} r="4" fill={color} />
                <text x={labelX} y={y - 4} textAnchor={labelAnchor} fill="#cbd5e1" fontSize={pinNameFontSize} fontWeight="700">
                  {pin.number} {truncateLabel(pin.name, 16)}
                </text>
                <text x={labelX} y={y + 10} textAnchor={labelAnchor} fill={color} fontSize={pinNetFontSize} fontWeight="700">
                  {truncateLabel(pin.net_name, 18)}
                </text>
              </g>
            );
          })}

          {noConnectSummary ? (
            <text x={bodyCenterX} y={bodyBottom - 12} fill="#687386" fontSize="10" textAnchor="middle">
              {truncateLabel(noConnectSummary, 70)}
            </text>
          ) : null}

          {capacitorPlacements.map(({ component, index, topNet, bottomNet, topPin, side, x, topConnectY, y }) => {
            const bottomRailY = railYForNet(bottomNet) ?? groundRailY;
            const reference = supportReference(component, index);
            const labelX = side === "left" ? x - 34 : x + 34;
            const labelAnchor = side === "left" ? "end" : "start";
            return (
              <g
                key={`${component.reference}-${component.purpose}-${index}`}
                className="schematic-support-hover"
                tabIndex={0}
                aria-label={supportComponentTooltip(component, reference)}
              >
                <title>{supportComponentTooltip(component, reference)}</title>
                {topPin ? (
                  <path d={`M${topPin.x} ${topPin.y}H${x}V${y - 28}`} stroke={netColor(topNet)} strokeWidth="2.4" />
                ) : (
                  <path d={`M${x} ${topConnectY}V${y - 28}`} stroke={netColor(topNet)} strokeWidth="2.4" />
                )}
                <path d={`M${x} ${y + 28}V${bottomRailY}`} stroke={netColor(bottomNet)} strokeWidth="2.4" />
                <circle cx={x} cy={topConnectY} r="4" fill={netColor(topNet)} />
                <circle cx={x} cy={bottomRailY} r="4" fill={netColor(bottomNet)} />
                <PreviewCapacitorGlyph x={x} y={y} color="#9da3ae" />
                <text x={labelX} y={y - 4} textAnchor={labelAnchor} fill="#cbd5e1" fontSize="12" fontWeight="700">
                  {reference} {compactPassiveValue(component.value)}
                </text>
              </g>
            );
          })}

          {pullResistorSupports.map((component, index) => {
            const powerNet = component.connects.find((net) => netIsPower(net) && !netIsGround(net)) ?? powerNets[0] ?? "VDD";
            const signalNet =
              component.connects.find((net) => !netIsPower(net) && !netIsGround(net)) ??
              component.connects[0] ??
              `REVIEW_${index + 1}`;
            const signalPin =
              pinRowsByNet.get(signalNet)?.[0] ??
              pinRows.find((row) => row.pin.name.toUpperCase() === signalNet.toUpperCase());
            const side = signalPin?.side ?? "right";
            const signalY = signalPin?.y ?? genericRowY + index * 28;
            const powerY = railYForNet(powerNet) ?? powerRailYs.values().next().value ?? 48;
            const x = signalPin ? supportWireX(signalPin.x, side, index) : supportWireX(bodyX + bodyWidth, side, index);
            const signalStartX = signalPin ? Math.min(signalPin.x, signalLabelX(side)) : x;
            const signalEndX = signalPin ? Math.max(signalPin.x, signalLabelX(side)) : x;
            const resistorCenterY = powerY <= signalY ? signalY - 28 : signalY + 28;
            const powerTerminalY = powerY <= signalY ? resistorCenterY - 28 : resistorCenterY + 28;
            const reference = supportReference(component, index);
            return (
              <g
                key={`${component.reference}-${component.purpose}-${index}`}
                className="schematic-support-hover"
                tabIndex={0}
                aria-label={supportComponentTooltip(component, reference)}
              >
                <title>{supportComponentTooltip(component, reference)}</title>
                <path d={`M${x} ${powerY}V${powerTerminalY}`} stroke={netColor(powerNet)} strokeWidth="2.4" />
                {x < signalStartX ? (
                  <path d={`M${x} ${signalY}H${signalStartX}`} stroke={netColor(signalNet)} strokeWidth="2.4" />
                ) : x > signalEndX ? (
                  <path d={`M${signalEndX} ${signalY}H${x}`} stroke={netColor(signalNet)} strokeWidth="2.4" />
                ) : null}
                <circle cx={x} cy={powerY} r="4" fill={netColor(powerNet)} />
                <circle cx={x} cy={signalY} r="4" fill={netColor(signalNet)} />
                <PreviewResistorGlyph x={x} y={resistorCenterY} color="#8290a6" />
                <text
                  x={side === "left" ? x - 26 : x + 26}
                  y={resistorCenterY - 3}
                  textAnchor={side === "left" ? "end" : "start"}
                  fill="#cbd5e1"
                  fontSize="12"
                  fontWeight="700"
                >
                  {reference}
                </text>
                <text
                  x={side === "left" ? x - 26 : x + 26}
                  y={resistorCenterY + 14}
                  textAnchor={side === "left" ? "end" : "start"}
                  fill={component.value === "TBD" || component.value === "not specified" ? "#fbbf24" : "#9da3ae"}
                  fontSize="11"
                >
                  {compactPassiveValue(component.value)}
                </text>
              </g>
            );
          })}

          {genericSupports.map((component, index) => {
            const anchor = supportAnchorFor(component);
            if (!anchor) return null;
            const { row: pinRow, net: anchorNet } = anchor;
            const otherNet = component.connects.find((net) => net !== anchorNet) ?? "REVIEW_2";
            const otherRailY = railYForNet(otherNet);
            const x = supportWireX(pinRow.x, pinRow.side, index);
            const railShunt = otherRailY !== undefined && shouldRailShuntSupport(component, otherNet);
            const horizontal = !railShunt;
            const horizontalWidth = isInductorSupport(component) ? 76 : isResistorSupport(component) ? 58 : 52;
            const wireEndX = horizontal
              ? pinRow.side === "left"
                ? x + horizontalWidth / 2
                : x - horizontalWidth / 2
              : x;
            const farX = pinRow.side === "left" ? x - horizontalWidth / 2 : x + horizontalWidth / 2;
            const labelWireEndX = pinRow.side === "left" ? farX - 42 : farX + 42;
            const seriesLabelX = pinRow.side === "left" ? labelWireEndX - 10 : labelWireEndX + 10;
            const y = horizontal ? pinRow.y : otherRailY <= pinRow.y ? pinRow.y - 28 : pinRow.y + 28;
            const railTerminalY = !railShunt ? y : otherRailY <= pinRow.y ? y - 28 : y + 28;
            const reference = supportReference(component, index);
            return (
              <g
                key={`${component.reference}-${component.purpose}-anchored-${index}`}
                className="schematic-support-hover"
                tabIndex={0}
                aria-label={supportComponentTooltip(component, reference)}
              >
                <title>{supportComponentTooltip(component, reference)}</title>
                <path d={`M${pinRow.x} ${pinRow.y}H${wireEndX}`} stroke={netColor(anchorNet)} strokeWidth="2.4" />
                {railShunt ? (
                  <>
                    <path d={`M${x} ${otherRailY}V${railTerminalY}`} stroke={netColor(otherNet)} strokeWidth="2.4" />
                    <circle cx={x} cy={otherRailY} r="4" fill={netColor(otherNet)} />
                  </>
                ) : (
                  <>
                    <path d={`M${farX} ${pinRow.y}H${labelWireEndX}`} stroke={netColor(otherNet)} strokeWidth="2.4" />
                    <text
                      x={seriesLabelX}
                      y={pinRow.y - 8}
                      textAnchor={pinRow.side === "left" ? "end" : "start"}
                      fill={netColor(otherNet)}
                      fontSize="10"
                      fontWeight="700"
                    >
                      {truncateLabel(otherNet, 18)}
                    </text>
                  </>
                )}
                <circle cx={wireEndX} cy={pinRow.y} r="4" fill={netColor(anchorNet)} />
                {isCapacitorSupport(component) && horizontal ? (
                  <PreviewHorizontalCapacitorGlyph x={x} y={y} width={horizontalWidth} color="#9da3ae" />
                ) : isCapacitorSupport(component) ? (
                  <PreviewCapacitorGlyph x={x} y={y} color="#9da3ae" />
                ) : component.type.toLowerCase() === "diode" || component.symbol.toLowerCase() === "device:d" ? (
                  horizontal ? (
                    <PreviewHorizontalDiodeGlyph x={x} y={y} width={horizontalWidth} color="#8290a6" />
                  ) : (
                    <PreviewDiodeGlyph x={x} y={y} color="#8290a6" />
                  )
                ) : isInductorSupport(component) && horizontal ? (
                  <PreviewHorizontalInductorGlyph x={x} y={y} width={horizontalWidth} color="#8290a6" />
                ) : isInductorSupport(component) ? (
                  <PreviewInductorGlyph x={x} y={y} color="#8290a6" />
                ) : horizontal ? (
                  <PreviewHorizontalResistorGlyph x={x} y={y} width={horizontalWidth} color="#8290a6" />
                ) : (
                  <PreviewResistorGlyph x={x} y={y} color="#8290a6" />
                )}
                <text
                  x={horizontal ? seriesLabelX : pinRow.side === "left" ? farX - 18 : farX + 18}
                  y={horizontal ? y + 24 : y - 4}
                  textAnchor={pinRow.side === "left" ? "end" : "start"}
                  fill="#cbd5e1"
                  fontSize="12"
                  fontWeight="700"
                >
                  {reference} {compactPassiveValue(component.value)}
                </text>
              </g>
            );
          })}

          {bottomGenericSupports.map(({ component, index }, bottomIndex) => {
            const column = bottomIndex % 3;
            const row = Math.floor(bottomIndex / 3);
            const x = 168 + column * 210;
            const y = genericRowY + row * 82;
            const topNet = component.connects[0] ?? "REVIEW_1";
            const bottomNet = component.connects[1] ?? "REVIEW_2";
            const reference = supportReference(component, index);
            return (
              <g
                key={`${component.reference}-${component.purpose}-${index}`}
                className="schematic-support-hover"
                tabIndex={0}
                aria-label={supportComponentTooltip(component, reference)}
              >
                <title>{supportComponentTooltip(component, reference)}</title>
                <text x={x} y={y - 16} fill={netColor(topNet)} fontSize="10" fontWeight="700">
                  {truncateLabel(topNet, 20)}
                </text>
                {isCapacitorSupport(component) ? (
                  <PreviewCapacitorGlyph x={x + 36} y={y + 20} color="#9da3ae" />
                ) : component.type.toLowerCase() === "diode" || component.symbol.toLowerCase() === "device:d" ? (
                  <PreviewDiodeGlyph x={x + 36} y={y + 20} color="#8290a6" />
                ) : isInductorSupport(component) ? (
                  <PreviewInductorGlyph x={x + 36} y={y + 20} color="#8290a6" />
                ) : (
                  <PreviewResistorGlyph x={x + 36} y={y + 20} color="#8290a6" />
                )}
                <text x={x + 68} y={y + 18} fill="#cbd5e1" fontSize="12" fontWeight="700">
                  {reference} {compactPassiveValue(component.value)}
                </text>
                <text x={x + 68} y={y + 34} fill="#7b8494" fontSize="10">
                  {truncateLabel(bottomNet, 20)}
                </text>
              </g>
            );
          })}

          <g transform={`translate(82 ${svgHeight - 30})`} fontSize="11" fontWeight="700">
            <LegendDot color="#5f9277" label="Power" x={0} />
            <LegendDot color="#6e8fb3" label="Interface" x={105} />
            <LegendDot color="#8290a6" label="Support" x={220} />
            <LegendDot color="#fbbf24" label={sourceIds.length ? `Sources ${sourceIds.join(", ")}` : "Cited sources"} x={340} />
          </g>
        </g>
      </InteractiveSchematicViewport>
    </div>
  );
}

function PreviewCapacitorGlyph({ x, y, color }: { x: number; y: number; color: string }) {
  return (
    <g fill="none">
      <path d={`M${x} ${y - 28}V${y - 10}`} stroke={color} strokeWidth="2.4" />
      <path d={`M${x} ${y + 10}V${y + 28}`} stroke={color} strokeWidth="2.4" />
      <path d={`M${x - 18} ${y - 10}H${x + 18}M${x - 18} ${y + 10}H${x + 18}`} stroke={color} strokeWidth="2.6" />
    </g>
  );
}

function PreviewHorizontalCapacitorGlyph({
  x,
  y,
  width,
  color
}: {
  x: number;
  y: number;
  width: number;
  color: string;
}) {
  return (
    <g fill="none">
      <path d={`M${x - width / 2} ${y}H${x - 10}`} stroke={color} strokeWidth="2.4" />
      <path d={`M${x + 10} ${y}H${x + width / 2}`} stroke={color} strokeWidth="2.4" />
      <path d={`M${x - 10} ${y - 18}V${y + 18}M${x + 10} ${y - 18}V${y + 18}`} stroke={color} strokeWidth="2.6" />
    </g>
  );
}

function PreviewResistorGlyph({ x, y, color }: { x: number; y: number; color: string }) {
  return (
    <g fill="none">
      <path d={`M${x} ${y - 28}V${y - 20}`} stroke={color} strokeWidth="2.4" />
      <path d={`M${x} ${y + 20}V${y + 28}`} stroke={color} strokeWidth="2.4" />
      <rect x={x - 12} y={y - 20} width="24" height="40" rx="4" fill="#101216" stroke={color} strokeWidth="2.4" />
    </g>
  );
}

function PreviewHorizontalResistorGlyph({
  x,
  y,
  width,
  color
}: {
  x: number;
  y: number;
  width: number;
  color: string;
}) {
  const half = width / 2;
  const bodyHalf = half - 8;
  return (
    <g fill="none">
      <path d={`M${x - half} ${y}H${x - bodyHalf}`} stroke={color} strokeWidth="2.4" />
      <path d={`M${x + bodyHalf} ${y}H${x + half}`} stroke={color} strokeWidth="2.4" />
      <rect x={x - bodyHalf} y={y - 12} width={bodyHalf * 2} height="24" rx="4" fill="#101216" stroke={color} strokeWidth="2.4" />
    </g>
  );
}

function PreviewInductorGlyph({ x, y, color }: { x: number; y: number; color: string }) {
  return (
    <g fill="none" stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.4">
      <path d={`M${x} ${y - 28}V${y - 18}`} />
      <path d={`M${x} ${y + 18}V${y + 28}`} />
      <path d={`M${x} ${y - 18}c-14 5 -14 11 0 16c14 5 14 11 0 16c-14 5 -14 11 0 18`} />
    </g>
  );
}

function PreviewHorizontalInductorGlyph({
  x,
  y,
  width,
  color
}: {
  x: number;
  y: number;
  width: number;
  color: string;
}) {
  return (
    <g fill="none" stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.4">
      <path d={`M${x - width / 2} ${y}H${x - 26}`} />
      <path d={`M${x + 26} ${y}H${x + width / 2}`} />
      <path d={`M${x - 26} ${y}c5 -14 11 -14 16 0c5 14 11 14 16 0c5 -14 11 -14 20 0`} />
    </g>
  );
}

function PreviewDiodeGlyph({ x, y, color }: { x: number; y: number; color: string }) {
  return (
    <g fill="none" stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.4">
      <path d={`M${x} ${y - 28}V${y - 11}`} />
      <path d={`M${x - 12} ${y - 11}L${x + 12} ${y - 11}L${x} ${y + 11}Z`} />
      <path d={`M${x - 14} ${y + 11}H${x + 14}`} />
      <path d={`M${x} ${y + 11}V${y + 28}`} />
    </g>
  );
}

function PreviewHorizontalDiodeGlyph({
  x,
  y,
  width,
  color
}: {
  x: number;
  y: number;
  width: number;
  color: string;
}) {
  const half = width / 2;
  const bodyHalf = half - 10;
  return (
    <g fill="none" stroke={color} strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.4">
      <path d={`M${x - half} ${y}H${x - bodyHalf}`} />
      <path d={`M${x - bodyHalf} ${y - 12}L${x + bodyHalf} ${y}L${x - bodyHalf} ${y + 12}Z`} />
      <path d={`M${x + bodyHalf} ${y - 14}V${y + 14}`} />
      <path d={`M${x + bodyHalf} ${y}H${x + half}`} />
    </g>
  );
}

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values.filter(Boolean)));
}

function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function supportReference(component: SupportComponent, index: number) {
  const prefix =
    component.type === "capacitor"
      ? "C"
      : component.type === "resistor"
        ? "R"
        : component.type.toLowerCase() === "diode" || component.symbol.toLowerCase() === "device:d"
          ? "D"
          : component.type === "inductor"
            ? "L"
            : "X";
  const normalized = component.reference.replace("?", "").trim();
  if (normalized && normalized !== prefix) return normalized;
  return `${prefix}${index + 1}`;
}

function supportComponentTooltip(component: SupportComponent | undefined, reference?: string) {
  if (!component) return reference ? `${reference} support component` : "Support component";
  const label = reference ?? component.reference;
  return [
    `${label} ${component.purpose}`,
    `Value: ${component.value}`,
    `Package: ${componentPackageLabel(component)}`,
    `Footprint: ${component.footprint}`,
    `Symbol: ${component.symbol}`,
    `Nets: ${component.connects.join(", ") || "Review required"}`,
    `Confidence: ${component.footprint_confidence}`,
    component.assignment_reason
  ].join("\n");
}

function preferredNonGroundNet(nets: string[]) {
  return nets.find((net) => !isGroundNet(net));
}

function truncateLabel(value: string, maxLength: number) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}

function isNoConnectPin(pin: PinDefinition) {
  const name = pin.name.toUpperCase();
  const net = pin.net_name.toUpperCase();
  const role = pin.electrical_type.toLowerCase();
  return (
    role.includes("no_connect") ||
    role.includes("do not connect") ||
    name === "NC" ||
    name === "DNC" ||
    name === "RESV" ||
    net.startsWith("NC_") ||
    net.startsWith("DNC_") ||
    net.includes("DNC_FLOAT")
  );
}

function extractedPinSide(pin: PinDefinition) {
  const name = pin.name.toUpperCase();
  const net = pin.net_name.toUpperCase();
  const role = pin.electrical_type.toLowerCase();
  if (
    net === "GND" ||
    net.startsWith("+") ||
    ["GND", "VSS", "VDD", "VCC", "AVDD", "DVDD", "AVSS", "DVSS"].some((token) => name.includes(token))
  ) {
    return "left";
  }
  if (["output", "bidirectional", "tri_state", "open_collector", "open_emitter"].includes(role)) {
    return "right";
  }
  if (isSignalPinName(name)) {
    return "right";
  }
  return "left";
}

function isSignalPinName(name: string) {
  const exact = new Set(["SDA", "SCL", "MISO", "MOSI", "SCK", "SCLK", "CS", "CSB", "CSN", "NCS", "SS", "XSHUT", "RESET"]);
  if (exact.has(name)) return true;
  return ["GPIO", "INT", "IRQ", "DRDY"].some((prefix) => name.startsWith(prefix));
}

function extractedNetColor(netName: string, role: CircuitNet["role"] = "other") {
  const net = netName.toUpperCase();
  if (role === "ground") return "#9da3ae";
  if (role === "power") return "#5f9277";
  if (role === "interface" || role === "reset" || role === "interrupt") return "#6e8fb3";
  if (isGroundNet(net)) return "#9da3ae";
  if (isPowerNet(net)) return "#5f9277";
  if (["SDA", "SCL", "MISO", "MOSI", "SCK", "CS"].some((name) => net.includes(name))) return "#6e8fb3";
  return "#8290a6";
}

function isGroundNet(netName: string) {
  const net = netName.toUpperCase();
  return net === "GND" || net === "DGND" || net === "AGND" || net.endsWith("_GND");
}

function isPowerNet(netName: string) {
  const net = netName.toUpperCase();
  return (
    isGroundNet(net) ||
    net.startsWith("+") ||
    net.startsWith("VDD") ||
    net.startsWith("VCC") ||
    net.startsWith("VIO") ||
    net === "VPU" ||
    net === "IOVDD" ||
    net.startsWith("VBAT") ||
    net.endsWith("_VDD") ||
    net.endsWith("_VCC")
  );
}

function GenericDraftSchematicCanvas({
  block,
  dimmed = false,
  transform,
  onTransformChange
}: {
  block: CircuitBlock;
  dimmed?: boolean;
  transform: SchematicViewportTransform;
  onTransformChange: SchematicViewportTransformUpdater;
}) {
  const powerNet = block.external_nets.find((net) => net.startsWith("+")) ?? "VCC/TBD";
  const signalNet =
    block.external_nets.find((net) => net.includes("SIGNALS") || net.includes("I2C") || net.includes("SPI")) ??
    "SIGNALS/TBD";
  const resistors = block.support_components.filter((component) => component.type === "resistor").slice(0, 4);
  const capacitor = block.support_components.find((component) => component.type === "capacitor");
  const refBase = referenceBase(block.block_slug);

  return (
    <div
      className={`schematic-card w-full max-w-[860px] animate-pop-in transition duration-500 ${
        dimmed ? "scale-[0.985] opacity-55" : "opacity-100"
      }`}
    >
      <InteractiveSchematicViewport
        width={760}
        height={460}
        ariaLabel="Draft schematic preview"
        transform={transform}
        onTransformChange={onTransformChange}
      >
        <rect x="0" y="0" width="760" height="460" rx="8" fill="transparent" />
        <g fill="none" strokeLinecap="round" strokeLinejoin="round">
          <path d="M80 82H680" stroke="#5f9277" strokeWidth="3" />
          <path d="M80 374H680" stroke="#9da3ae" strokeWidth="3" />
          <text x="74" y="68" fill="#5f9277" fontSize="16" fontWeight="700">
            {powerNet}
          </text>
          <text x="76" y="398" fill="#9da3ae" fontSize="16" fontWeight="700">
            GND
          </text>

          <rect x="292" y="150" width="178" height="150" rx="8" fill="#101216" stroke="#333a44" strokeWidth="2" />
          <text x="381" y="215" fill="#a8c4e0" fontSize="20" fontWeight="700" textAnchor="middle">
            U?
          </text>
          <text x="381" y="246" fill="#8290a6" fontSize="16" fontWeight="700" textAnchor="middle">
            {block.main_component.value}
          </text>
          <text x="381" y="272" fill="#7b8494" fontSize="12" textAnchor="middle">
            AI draft - review pin map
          </text>

          <path d="M292 188H250V82" stroke="#5f9277" strokeWidth="3" />
          <path d="M292 262H250V374" stroke="#9da3ae" strokeWidth="3" />
          <path d="M470 225H610" stroke="#6e8fb3" strokeWidth="3" />
          <circle cx="250" cy="82" r="4.5" fill="#5f9277" />
          <circle cx="250" cy="374" r="4.5" fill="#9da3ae" />
          <rect x="610" y="213" width="104" height="24" rx="4" fill="#101216" stroke="#6e8fb3" />
          <text x="662" y="230" textAnchor="middle" fill="#6e8fb3" fontSize="12" fontWeight="700">
            {signalNet}
          </text>
          <text x="306" y="192" fill="#7b8494" fontSize="12">VCC</text>
          <text x="306" y="266" fill="#7b8494" fontSize="12">GND</text>
          <text x="422" y="217" fill="#7b8494" fontSize="12">SIGNALS</text>

          {capacitor ? (
            <g
              className="schematic-support-hover"
              tabIndex={0}
              aria-label={supportComponentTooltip(capacitor, `C${refBase + 1}`)}
            >
              <title>{supportComponentTooltip(capacitor, `C${refBase + 1}`)}</title>
              <path d="M150 82V150" stroke="#5f9277" strokeWidth="3" />
              <path d="M150 190V374" stroke="#9da3ae" strokeWidth="3" />
              <path d="M130 150H170M130 170H170" stroke="#9da3ae" strokeWidth="2.3" />
              <circle cx="150" cy="82" r="4.5" fill="#5f9277" />
              <circle cx="150" cy="374" r="4.5" fill="#9da3ae" />
              <text x="178" y="160" fill="#cbd5e1" fontSize="13">
                C?
              </text>
              <text x="178" y="180" fill="#9da3ae" fontSize="12">
                {capacitor.value}
              </text>
            </g>
          ) : null}

          {resistors.map((resistor, index) => {
            const y = 118 + index * 62;
            const label = resistor.connects.find(
              (net) => net !== "GND" && !net.startsWith("+") && !net.toUpperCase().startsWith("VCC")
            ) ?? `REVIEW_${index + 1}`;
            const reference = `R${refBase + index + 1}`;
            return (
              <g
                key={`${resistor.purpose}-${index}`}
                className="schematic-support-hover"
                tabIndex={0}
                aria-label={supportComponentTooltip(resistor, reference)}
              >
                <title>{supportComponentTooltip(resistor, reference)}</title>
                <path d={`M552 82V${y - 24}`} stroke="#5f9277" strokeWidth="3" />
                <rect x="540" y={y - 24} width="24" height="48" rx="4" fill="#101216" stroke="#8290a6" strokeWidth="2" />
                <path d={`M552 ${y + 24}H610`} stroke="#8290a6" strokeWidth="3" />
                <circle cx="552" cy="82" r="4.5" fill="#5f9277" />
                <rect x="610" y={y + 12} width="116" height="24" rx="4" fill="#101216" stroke="#8290a6" />
                <text x="668" y={y + 29} textAnchor="middle" fill="#a8c4e0" fontSize="12" fontWeight="700">
                  {label}
                </text>
                <text x="572" y={y - 6} fill="#cbd5e1" fontSize="13">
                  {reference}
                </text>
                <text x="572" y={y + 14} fill={resistor.value === "TBD" ? "#fbbf24" : "#9da3ae"} fontSize="12">
                  {resistor.value}
                </text>
              </g>
            );
          })}
        </g>
      </InteractiveSchematicViewport>
    </div>
  );
}

function LegendDot({ color, label, x }: { color: string; label: string; x: number }) {
  return (
    <g transform={`translate(${x} 0)`}>
      <circle cx="0" cy="0" r="6" fill={color} />
      <text x="14" y="4" fill="#7b8494">
        {label}
      </text>
    </g>
  );
}

function ComponentTable({
  block,
  userPreferences,
  onUpdateSupportComponent
}: {
  block: CircuitBlock | null;
  userPreferences: UserPreferences;
  onUpdateSupportComponent: (
    supportIndex: number,
    updates: Partial<Pick<SupportComponent, "value" | "footprint">>
  ) => void;
}) {
  const rows = componentTableRows(block);
  const [tableExpanded, setTableExpanded] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const activeEditRow =
    editingKey !== null ? rows.find((row) => row.key === editingKey) : undefined;
  const activeSupportIndex = activeEditRow?.supportIndex;
  const activeSupportComponent =
    activeEditRow?.supportKind === "support" && activeSupportIndex !== undefined
      ? (activeEditRow.component as SupportComponent)
      : null;
  const activePassiveKind = activeSupportComponent
    ? passiveKindForComponent(activeSupportComponent)
    : null;

  useEffect(() => {
    setTableExpanded(false);
    setEditingKey(null);
  }, [block?.id, block?.support_components.length]);

  useEffect(() => {
    if (!tableExpanded) return;

    const dismissEditor = (event: globalThis.PointerEvent) => {
      if (!(event.target instanceof Element)) return;
      if (event.target.closest("[data-component-table-toggle], [data-component-table-dialog]")) return;
      setTableExpanded(false);
    };

    document.addEventListener("pointerdown", dismissEditor);
    return () => document.removeEventListener("pointerdown", dismissEditor);
  }, [tableExpanded]);

  useEffect(() => {
    if (!editingKey) return;

    const dismissEditor = (event: globalThis.PointerEvent) => {
      if (!(event.target instanceof Element)) return;
      if (event.target.closest("[data-component-edit-toggle], [data-component-edit-dialog]")) return;
      setEditingKey(null);
    };

    document.addEventListener("pointerdown", dismissEditor);
    return () => document.removeEventListener("pointerdown", dismissEditor);
  }, [editingKey]);

  useEffect(() => {
    if (!tableExpanded && !editingKey) return;

    const dismissOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setTableExpanded(false);
        setEditingKey(null);
      }
    };

    document.addEventListener("keydown", dismissOnEscape);
    return () => document.removeEventListener("keydown", dismissOnEscape);
  }, [editingKey, tableExpanded]);

  const expandedTableDialog =
    tableExpanded && block && typeof document !== "undefined"
      ? createPortal(
          <div
            className="trace-labs-theme component-table-backdrop fixed inset-0 z-[10000] grid place-items-center bg-black/20 px-4 py-6"
            data-component-table-backdrop
          >
            <div
              className="component-table-dialog grid w-[96vw] max-w-none gap-4 rounded-xl border border-[#7d9cbd]/25 bg-[#0d0d0f]/92 p-4 text-sm shadow-[0_28px_90px_rgba(0,0,0,0.72)]"
              data-component-table-dialog
              role="dialog"
              aria-modal="true"
              aria-label="Expanded components table"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-heading text-sm font-semibold text-slate-200">
                    Components
                  </p>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {block.block_name}
                  </p>
                </div>
                <button
                  className="liquid-control shrink-0 rounded-lg p-2 text-slate-300"
                  type="button"
                  aria-label="Close expanded components table"
                  data-component-table-toggle
                  onClick={() => setTableExpanded(false)}
                >
                  <X size={14} />
                </button>
              </div>

              <div className="component-table-surface overflow-y-auto overflow-x-hidden rounded-lg border border-white/[0.07] bg-[#0a0a0c]/88">
                <table className="w-full table-fixed text-left text-sm">
                  <colgroup>
                    <col className="w-[7%]" />
                    <col className="w-[13%]" />
                    <col className="w-[12%]" />
                    <col className="w-[10%]" />
                    <col className="w-[58%]" />
                  </colgroup>
                  <thead className="border-b border-white/[0.07] text-slate-600">
                    <tr>
                      <th className="break-words px-4 py-3 font-semibold">Ref</th>
                      <th className="break-words border-l border-white/[0.08] px-4 py-3 font-semibold">Value</th>
                      <th className="break-words border-l border-white/[0.08] px-4 py-3 font-semibold">Package</th>
                      <th className="break-words border-l border-white/[0.08] px-3 py-3 font-semibold">Footprint</th>
                      <th className="break-words border-l border-white/[0.08] px-4 py-3 font-semibold">Nets / purpose</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.06]">
                    {rows.map((row) => {
                      const supportIndex = row.supportIndex;
                      const supportComponent =
                        row.supportKind === "support" && supportIndex !== undefined
                          ? (row.component as SupportComponent)
                          : null;
                      const passiveKind = supportComponent
                        ? passiveKindForComponent(supportComponent)
                        : null;
                      const packageLabel = componentPackageLabel(row.component);

                      return (
                        <tr key={row.key} className="align-top text-slate-400">
                          <td className="px-4 py-3 font-semibold text-slate-200">{row.reference}</td>
                          <td className="border-l border-white/[0.08] px-3 py-3">
                            {supportComponent && supportIndex !== undefined ? (
                              <input
                                className="liquid-control w-full min-w-0 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none"
                                value={supportComponent.value}
                                onChange={(event) =>
                                  onUpdateSupportComponent(supportIndex, { value: event.target.value })
                                }
                              />
                            ) : (
                              <span className="font-semibold text-slate-300">{row.component.value}</span>
                            )}
                            {"supplier_part_number" in row.component && row.component.supplier_part_number ? (
                              <span className="mt-1 block text-[10px] uppercase tracking-[0.12em] text-amber-300/80">
                                {row.component.supplier || "Supplier"} {row.component.supplier_part_number}
                              </span>
                            ) : null}
                          </td>
                          <td className="border-l border-white/[0.08] px-4 py-3">
                            {supportComponent && supportIndex !== undefined && passiveKind ? (
                              <select
                                className="liquid-control w-full min-w-0 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none"
                                value={
                                  packageSizeFromFootprint(supportComponent.footprint) ??
                                  userPreferences.standardPackageSize
                                }
                                onChange={(event) =>
                                  onUpdateSupportComponent(supportIndex, {
                                    footprint: passiveFootprint(
                                      passiveKind,
                                      event.target.value as PackagePreferenceId
                                    )
                                  })
                                }
                              >
                                {PASSIVE_PACKAGE_OPTIONS.map((option) => (
                                  <option key={option.id} value={option.id}>
                                    {option.label} - {option.metric}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <span className="font-semibold text-slate-300">{packageLabel}</span>
                            )}
                          </td>
                          <td className="border-l border-white/[0.08] px-4 py-3">
                            {supportComponent && supportIndex !== undefined && !passiveKind ? (
                              <input
                                className="liquid-control w-full min-w-0 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none"
                                value={supportComponent.footprint}
                                onChange={(event) =>
                                  onUpdateSupportComponent(supportIndex, { footprint: event.target.value })
                                }
                              />
                            ) : (
                              <span className="block break-words text-slate-400">
                                {row.component.footprint}
                              </span>
                            )}
                          </td>
                          <td className="border-l border-white/[0.08] px-4 py-3">
                            <span className="block text-slate-300">
                              {row.component.connects.join(", ") || "Review required"}
                            </span>
                            <span className="mt-1 block break-words text-xs leading-5 text-slate-500">
                              {row.component.purpose}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>,
          document.body
        )
      : null;

  const editPopover =
    editingKey &&
    activeEditRow &&
    activeSupportComponent &&
    activeSupportIndex !== undefined &&
    typeof document !== "undefined"
      ? createPortal(
          <div className="trace-labs-theme component-edit-backdrop fixed inset-0 z-[10000] grid place-items-center bg-black/20 px-4 py-6">
            <div
              className="component-edit-dialog grid w-full max-w-sm gap-3 rounded-xl border border-[#7d9cbd]/25 bg-[#0d0d0f]/92 p-4 text-sm shadow-[0_22px_70px_rgba(0,0,0,0.62)]"
              data-component-edit-dialog
              role="dialog"
              aria-modal="true"
              aria-label={`Edit ${activeEditRow.reference}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-heading text-sm font-semibold text-slate-200">
                    Edit {activeEditRow.reference}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-500">
                    {activeSupportComponent.purpose}
                  </p>
                </div>
                <button
                  className="liquid-control shrink-0 rounded-lg p-2 text-slate-300"
                  type="button"
                  aria-label="Close component editor"
                  data-component-edit-toggle
                  onClick={() => setEditingKey(null)}
                >
                  <X size={14} />
                </button>
              </div>

              <label className="grid gap-1 text-[11px] font-semibold text-slate-500">
                Value
                <input
                  className="liquid-control rounded-lg px-3 py-2 text-sm text-slate-100 outline-none"
                  value={activeSupportComponent.value}
                  onChange={(event) =>
                    onUpdateSupportComponent(activeSupportIndex, { value: event.target.value })
                  }
                />
              </label>

              {activePassiveKind ? (
                <label className="grid gap-1 text-[11px] font-semibold text-slate-500">
                  Package
                  <select
                    className="liquid-control rounded-lg px-3 py-2 text-sm text-slate-100 outline-none"
                    value={
                      packageSizeFromFootprint(activeSupportComponent.footprint) ??
                      userPreferences.standardPackageSize
                    }
                    onChange={(event) =>
                      onUpdateSupportComponent(activeSupportIndex, {
                        footprint: passiveFootprint(
                          activePassiveKind,
                          event.target.value as PackagePreferenceId
                        )
                      })
                    }
                  >
                    {PASSIVE_PACKAGE_OPTIONS.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label} - {option.metric}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <label className="grid gap-1 text-[11px] font-semibold text-slate-500">
                  Footprint
                  <input
                    className="liquid-control rounded-lg px-3 py-2 text-sm text-slate-100 outline-none"
                    value={activeSupportComponent.footprint}
                    onChange={(event) =>
                      onUpdateSupportComponent(activeSupportIndex, { footprint: event.target.value })
                    }
                  />
                </label>
              )}
            </div>
          </div>,
          document.body
        )
      : null;

  return (
    <InspectorSection title="Components">
      {expandedTableDialog}
      {editPopover}
      {block ? (
        <div className="overflow-hidden rounded-lg border border-white/[0.07]">
          <table className="w-full table-fixed text-left text-xs">
            <colgroup>
              <col className="w-[20%]" />
              <col className="w-[52%]" />
              <col className="w-[28%]" />
            </colgroup>
            <thead className="border-b border-white/[0.07] text-slate-600">
              <tr>
                <th className="px-3 py-2 font-semibold">Ref</th>
                <th className="px-3 py-2 font-semibold">Value</th>
                <th className="px-3 py-2 font-semibold">Package</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.06]">
              {rows.map((row, index) => {
                const supportIndex = row.supportIndex;
                const supportComponent =
                  row.supportKind === "support" && supportIndex !== undefined
                    ? (row.component as SupportComponent)
                    : null;
                const packageLabel = componentPackageLabel(row.component);

                return (
                  <tr
                    key={row.key}
                    className="group animate-fade-slide cursor-pointer text-slate-400 outline-none transition hover:bg-white/[0.025] focus-within:bg-white/[0.025]"
                    style={{ animationDelay: `${index * 65}ms` }}
                    tabIndex={0}
                    onClick={() => setTableExpanded(true)}
                    onKeyDown={(event) => {
                      if (
                        event.target instanceof Element &&
                        event.target.closest("[data-component-edit-toggle]")
                      ) {
                        return;
                      }
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.preventDefault();
                      setTableExpanded(true);
                    }}
                  >
                    <td className="min-w-0 px-3 py-2 font-semibold text-slate-200">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <span className="min-w-0 truncate">{row.reference}</span>
                      </div>
                    </td>
                    <td
                      className={`relative min-w-0 py-2 pl-3 ${
                        supportComponent ? "pr-16" : "pr-3"
                      } group-hover:z-20 group-focus-within:z-20`}
                    >
                      <span className="block min-w-0 truncate" title={row.component.value}>
                        {row.component.value}
                      </span>
                      {"supplier_part_number" in row.component && row.component.supplier_part_number ? (
                        <span
                          className="mt-1 block min-w-0 truncate text-[10px] uppercase tracking-[0.12em] text-amber-300/80"
                          title={`${row.component.supplier || "Supplier"} ${row.component.supplier_part_number}`}
                        >
                          {row.component.supplier || "Supplier"} {row.component.supplier_part_number}
                        </span>
                      ) : null}
                      {supportComponent ? (
                        <button
                          className="absolute right-2 top-1/2 z-40 -translate-y-1/2 rounded-md bg-[#141a21] px-2 py-1 text-[10px] font-semibold text-[#7d9cbd] shadow-[0_8px_24px_rgba(0,0,0,0.32)] transition hover:bg-[#7d9cbd]/10"
                          type="button"
                          data-component-edit-toggle
                          onClick={(event) => {
                            event.stopPropagation();
                            setTableExpanded(false);
                            setEditingKey(row.key);
                          }}
                        >
                          Edit
                        </button>
                      ) : null}
                    </td>
                    <td className="min-w-0 px-3 py-2">
                      <span className="block min-w-0 truncate font-semibold text-slate-300" title={packageLabel}>
                        {packageLabel}
                      </span>
                      <span className="block min-w-0 truncate text-slate-500" title={row.component.footprint}>
                        {row.component.footprint}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-2">
          {[0, 1, 2].map((item) => (
            <div key={item} className="gentle-skeleton h-8 rounded-lg" />
          ))}
        </div>
      )}
    </InspectorSection>
  );
}

function InspectorPanel({
  bridgeStatus,
  bridgeBusy,
  block,
  exportResult,
  importResult,
  nextStepChecks,
  projectPath,
  userPreferences,
  onUpdateSupportComponent,
  setProjectPath,
  onLinkProject,
  onRefreshBridge,
  setNextStepChecks
}: {
  bridgeStatus: BridgeStatus | null;
  bridgeBusy: string | null;
  block: CircuitBlock | null;
  exportResult: ExportResponse | null;
  importResult: BridgeImportResponse | null;
  nextStepChecks: Record<string, boolean>;
  projectPath: string;
  userPreferences: UserPreferences;
  onUpdateSupportComponent: (
    supportIndex: number,
    updates: Partial<Pick<SupportComponent, "value" | "footprint">>
  ) => void;
  setProjectPath: (value: string) => void;
  onLinkProject: () => void;
  onRefreshBridge: () => void;
  setNextStepChecks: (value: Record<string, boolean>) => void;
}) {
  return (
    <aside
      id="narrow-review-panel"
      className="flex min-h-[640px] flex-col overflow-hidden border-t border-white/[0.06] bg-[#0d0d0f] lg:min-h-0 lg:border-l lg:border-t-0"
    >
      <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
        <ComponentTable
          block={block}
          userPreferences={userPreferences}
          onUpdateSupportComponent={onUpdateSupportComponent}
        />

        <InspectorSection title="Assumptions">
          {block ? (
            <ul className="space-y-3 text-sm leading-5 text-slate-400">
              {block.assumptions.map((assumption, index) => (
                <li
                  key={assumption}
                  className="animate-fade-slide flex gap-3"
                  style={{ animationDelay: `${index * 55}ms` }}
                >
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-500" />
                  <span>{assumption}</span>
                </li>
              ))}
            </ul>
          ) : (
            <InspectorEmpty text="Assumptions appear after the generated block loads." />
          )}
        </InspectorSection>

        <InspectorSection count={block?.next_steps.length} title="Next steps" tone="success">
          {block ? (
            <div className="space-y-3">
              {block.next_steps.map((step, index) => (
                <label
                  key={step.id}
                  className="animate-fade-slide flex cursor-pointer items-start gap-3 text-sm leading-5 text-slate-400"
                  style={{ animationDelay: `${index * 45}ms` }}
                >
                  <input
                    className="mt-0.5 h-4 w-4 rounded border-white/[0.12] bg-transparent accent-[#7d9cbd]"
                    type="checkbox"
                    checked={Boolean(nextStepChecks[step.id])}
                    onChange={(event) =>
                      setNextStepChecks({ ...nextStepChecks, [step.id]: event.target.checked })
                    }
                  />
                  <span>{step.task}</span>
                </label>
              ))}
            </div>
          ) : (
            <InspectorEmpty text="Action items appear with the generated block." />
          )}
        </InspectorSection>

        {exportResult || importResult ? (
          <InspectorSection title="Export result">
            <ExportResultSummary exportResult={exportResult} importResult={importResult} />
          </InspectorSection>
        ) : null}

      </div>
      <div className="workspace-project-connection">
        <ProjectConnectionControl
          bridgeStatus={bridgeStatus}
          busy={bridgeBusy}
          projectPath={projectPath}
          setProjectPath={setProjectPath}
          onLinkProject={onLinkProject}
          onRefreshBridge={onRefreshBridge}
          compact
        />
      </div>
    </aside>
  );
}

function InspectorSection({
  title,
  count,
  tone = "neutral",
  children
}: {
  title: string;
  count?: number;
  tone?: "neutral" | "warning" | "success";
  children: React.ReactNode;
}) {
  const toneClass =
    tone === "warning"
      ? "bg-amber-400/15 text-amber-300"
      : tone === "success"
        ? "bg-emerald-400/15 text-emerald-300"
        : "bg-white/[0.08] text-slate-400";

  return (
    <section className="border-b border-white/[0.06] px-5 py-5">
      <div className="mb-4 flex items-center gap-2">
        <h2 className="text-sm font-semibold text-slate-300">{title}</h2>
        {typeof count === "number" ? (
          <span className={`rounded-md px-2 py-0.5 text-xs font-semibold ${toneClass}`}>
            {count}
          </span>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function InspectorEmpty({ text }: { text: string }) {
  return <p className="text-sm leading-6 text-slate-600">{text}</p>;
}

function ExportResultSummary({
  exportResult,
  importResult
}: {
  exportResult: ExportResponse | null;
  importResult: BridgeImportResponse | null;
}) {
  return (
    <div className="space-y-3 text-sm leading-5 text-slate-400">
      {exportResult ? (
        <>
          <p className="text-slate-300">{exportResult.message}</p>
          <p className="break-all text-xs text-slate-500">{exportResult.output_directory}</p>
        </>
      ) : null}
      {importResult ? (
        <div className="rounded-lg border border-emerald-300/20 bg-emerald-400/10 px-3 py-3 text-emerald-100">
          <p>{importResult.message}</p>
          <p className="mt-2 text-xs text-emerald-100/70">
            Mode: {importResult.mode === "inline_main" ? "Main schematic" : "Subsheet"}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function DocumentationBox({
  block,
  extractionJob
}: {
  block: CircuitBlock | null;
  extractionJob: ComponentExtractionJob | null;
}) {
  const source = documentationSourceForState(block, extractionJob);
  const hasUsableUrl = isHttpUrl(source?.url);
  const contextText = documentationContextText(block, extractionJob, source);

  return (
    <section className="border-t border-white/[0.06] px-5 py-4">
      <div className="liquid-control rounded-xl px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-600">
          Documentation
        </p>
        {source ? (
          <>
            {hasUsableUrl ? (
              <a
                className="mt-2 block text-sm font-semibold text-[#a8c4e0] hover:text-white"
                href={source.url}
                rel="noreferrer"
                target="_blank"
              >
                {source.title}
              </a>
            ) : (
              <p className="mt-2 text-sm font-semibold text-[#a8c4e0]">{source.title}</p>
            )}
            <p className="mt-2 text-xs leading-5 text-slate-500">
              {source.notes ?? source.confidence}
            </p>
            {contextText ? (
              <p className="mt-2 text-xs leading-5 text-emerald-200/80">{contextText}</p>
            ) : null}
            {!hasUsableUrl ? (
              <p className="mt-2 text-xs leading-5 text-amber-200/80">
                No usable documentation URL was captured for this draft. Check `notes.md` and verify the datasheet manually.
              </p>
            ) : null}
          </>
        ) : (
          <p className="mt-2 text-sm text-slate-500">
            {documentationEmptyText(extractionJob)}
          </p>
        )}
      </div>
    </section>
  );
}

function ToastStack({
  busy,
  onDismiss,
  toasts,
  onToggle
}: {
  busy: string | null;
  onDismiss: (id: string) => void;
  toasts: ToastMessage[];
  onToggle: (id: string) => void;
}) {
  if (!busy && toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-5 z-50 flex justify-center px-4 sm:justify-end">
      <div className="flex w-full max-w-sm flex-col gap-2">
        {busy ? <OperationToast busy={busy} /> : null}
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`pointer-events-auto rounded-xl border border-white/[0.08] bg-[#141418]/95 px-4 py-3 text-sm font-medium leading-5 text-slate-200 shadow-[0_18px_60px_rgba(0,0,0,0.34)] backdrop-blur-xl ${
              toast.leaving ? "animate-toast-out" : "animate-toast-in"
            }`}
            onClick={() => onDismiss(toast.id)}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0 break-words">{toast.title}</span>
              {toast.details.length ? (
                <button
                  className="shrink-0 rounded-md px-2 py-1 text-xs font-semibold text-slate-500 transition hover:bg-white/[0.04] hover:text-slate-300"
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onToggle(toast.id);
                  }}
                >
                  {toast.expanded ? "Hide" : "Show more"}
                </button>
              ) : null}
            </div>
            {toast.expanded ? (
              <div className="mt-3 max-h-40 space-y-2 overflow-y-auto border-t border-white/[0.07] pt-3 text-xs leading-5 text-slate-500">
                {toast.details.map((detail, index) => (
                  <p key={`${toast.id}-${index}`} className="break-all">
                    {detail}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function PartLibraryDrawer({
  activeEntryId,
  entries,
  open,
  onClose,
  onNewChat,
  onRequestDelete,
  onRestore
}: {
  activeEntryId: string | null;
  entries: PartLibraryEntry[];
  open: boolean;
  onClose: () => void;
  onNewChat: () => void;
  onRequestDelete: (entry: PartLibraryEntry) => void;
  onRestore: (entry: PartLibraryEntry) => void;
}) {
  const [componentSearch, setComponentSearch] = useState("");
  const [componentFilter, setComponentFilter] = useState<PartLibraryFilterId>("all");
  const filteredEntries = useMemo(
    () => filteredPartLibraryEntries(entries, componentSearch, componentFilter),
    [componentFilter, componentSearch, entries]
  );

  return (
    <>
      <div
        className={`fixed inset-0 z-40 bg-black/45 transition-opacity duration-700 ${
          open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
      />
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-[390px] max-w-[92vw] flex-col border-r border-white/[0.08] bg-[#0d0d0f] shadow-[28px_0_80px_rgba(0,0,0,0.38)] transition-transform duration-700 ease-out ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
        aria-hidden={!open}
      >
        <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-4">
          <div>
            <p className="font-heading text-sm font-semibold text-slate-200">Past components</p>
            <p className="mt-1 text-xs text-slate-600">Saved component choices</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="liquid-control rounded-xl px-5 py-3 text-sm font-semibold text-slate-200"
              type="button"
              onClick={onNewChat}
            >
              New chat
            </button>
            <button
              className="liquid-control rounded-xl p-2 text-slate-400"
              type="button"
              aria-label="Close past components"
              onClick={onClose}
            >
              <X size={17} />
            </button>
          </div>
        </div>

        <PartLibrarySearchControls
          filterId={componentFilter}
          onFilterChange={setComponentFilter}
          onSearchChange={setComponentSearch}
          search={componentSearch}
        />

        <div className="thin-scrollbar flex-1 overflow-y-auto p-3">
          {entries.length ? (
            filteredEntries.length ? (
              <div className="space-y-2">
                {filteredEntries.map((entry) => {
                  const active = entry.id === activeEntryId;
                  return (
                    <PartLibraryEntryCard
                      key={entry.id}
                      active={active}
                      entry={entry}
                      variant="drawer"
                      onRequestDelete={onRequestDelete}
                      onRestore={onRestore}
                    />
                  );
                })}
              </div>
            ) : (
              <div className="mt-10 rounded-xl border border-white/[0.06] bg-white/[0.025] px-4 py-5 text-sm leading-6 text-slate-500">
                No saved components match that search or filter.
              </div>
            )
          ) : (
            <div className="mt-10 rounded-xl border border-white/[0.06] bg-white/[0.025] px-4 py-5 text-sm leading-6 text-slate-500">
              Completed components will appear here after generation.
            </div>
          )}
        </div>
      </aside>
    </>
  );
}

function OperationToast({ busy }: { busy: string }) {
  return (
    <div className="animate-toast-in rounded-xl border border-white/[0.08] bg-[#141418]/95 px-4 py-3 shadow-[0_18px_60px_rgba(0,0,0,0.34)] backdrop-blur-xl">
      <InlineLoadingStatus busy={busy} />
    </div>
  );
}

function TraceLabsLogo({ className = "h-6 w-6" }: { className?: string }) {
  const logoStyle = {
    WebkitMaskImage: `url(${traceLabsLogoUrl})`,
    maskImage: `url(${traceLabsLogoUrl})`
  } as CSSProperties;

  return (
    <span
      aria-hidden="true"
      className={`trace-logo ${className}`}
      style={logoStyle}
    />
  );
}

function TracePromptMark({
  active,
  compact = false
}: {
  active: boolean;
  compact?: boolean;
}) {
  return (
    <span
      className={`trace-prompt-mark ${active ? "trace-prompt-mark-active" : ""} ${
        compact ? "trace-prompt-mark-compact" : ""
      }`}
      aria-hidden="true"
    >
      <TraceLabsLogo className="h-5 w-4 text-[#a8c4e0]" />
    </span>
  );
}

function Header({
  accountOverview,
  canGoHome,
  partCount,
  pricing,
  userPreferences,
  onHome,
  onOpenLibrary,
  onPackagePreferenceChange
}: {
  accountOverview: AccountOverview | null;
  canGoHome: boolean;
  partCount: number;
  pricing: PricingPreview | null;
  userPreferences: UserPreferences;
  onHome: () => void;
  onOpenLibrary: () => void;
  onPackagePreferenceChange: (packageSize: PackagePreferenceId) => void;
}) {
  return (
    <header className="grid min-h-16 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-white/[0.07] bg-[#0d0d0f] px-4 py-3 lg:px-6">
      <div className="flex min-w-0 items-center gap-4">
        <h1
          data-testid="app-title"
          className="flex min-w-0 items-center gap-2 text-lg font-semibold text-slate-100"
        >
          <TraceLabsLogo className="h-10 w-8 shrink-0 text-[#7d9cbd]" />
          <span className="truncate">
            Trace <span className="text-[#7d9cbd]">Labs</span>
          </span>
        </h1>
      </div>

      <div className="header-actions flex min-w-0 items-center justify-end">
        <div className="desktop-account-menu">
          <AccountMenu
            accountOverview={accountOverview}
            pricing={pricing}
            userPreferences={userPreferences}
            onPackagePreferenceChange={onPackagePreferenceChange}
          />
        </div>
        <NarrowHeaderMenu
          accountOverview={accountOverview}
          canGoHome={canGoHome}
          partCount={partCount}
          pricing={pricing}
          userPreferences={userPreferences}
          onHome={onHome}
          onOpenLibrary={onOpenLibrary}
          onPackagePreferenceChange={onPackagePreferenceChange}
        />
      </div>
    </header>
  );
}

function NarrowHeaderMenu({
  accountOverview,
  canGoHome,
  partCount,
  pricing,
  userPreferences,
  onHome,
  onOpenLibrary,
  onPackagePreferenceChange
}: {
  accountOverview: AccountOverview | null;
  canGoHome: boolean;
  partCount: number;
  pricing: PricingPreview | null;
  userPreferences: UserPreferences;
  onHome: () => void;
  onOpenLibrary: () => void;
  onPackagePreferenceChange: (packageSize: PackagePreferenceId) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) {
      setAccountOpen(false);
      return;
    }

    const closeMenu = (event: globalThis.PointerEvent) => {
      if (event.target instanceof Element && menuRef.current?.contains(event.target)) return;
      setMenuOpen(false);
    };
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
      }
    };

    document.addEventListener("pointerdown", closeMenu);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeMenu);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

  return (
    <div className="narrow-header-menu" ref={menuRef}>
      <button
        className="narrow-header-menu-button"
        type="button"
        aria-label="Open navigation menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen((open) => !open)}
      >
        <Menu size={20} />
      </button>

      {menuOpen ? (
        <div className="narrow-header-dropdown animate-fade-slide">
          <button
            className="narrow-header-menu-item"
            type="button"
            onClick={() => {
              setMenuOpen(false);
              onOpenLibrary();
            }}
          >
            <span className="inline-flex min-w-0 items-center gap-2">
              <Cpu size={16} />
              Past components
            </span>
            <span className="rounded-md bg-white/[0.08] px-1.5 py-0.5 text-[11px] text-slate-500">
              {partCount}
            </span>
          </button>

          {canGoHome ? (
            <button
              className="narrow-header-menu-item"
              type="button"
              onClick={() => {
                setMenuOpen(false);
                onHome();
              }}
            >
              <span className="inline-flex min-w-0 items-center gap-2">
                <Home size={16} />
                Home
              </span>
            </button>
          ) : null}

          <button
            className="narrow-header-menu-item"
            type="button"
            aria-expanded={accountOpen}
            onClick={() => setAccountOpen((open) => !open)}
          >
            <span className="inline-flex min-w-0 items-center gap-2">
              <UserRound size={16} />
              Account
            </span>
            <ChevronDown
              className={`transition-transform ${accountOpen ? "rotate-180" : ""}`}
              size={15}
            />
          </button>

          {accountOpen ? (
            <NarrowAccountPanel
              accountOverview={accountOverview}
              pricing={pricing}
              userPreferences={userPreferences}
              onPackagePreferenceChange={onPackagePreferenceChange}
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function NarrowAccountPanel({
  accountOverview,
  pricing,
  userPreferences,
  onPackagePreferenceChange
}: {
  accountOverview: AccountOverview | null;
  pricing: PricingPreview | null;
  userPreferences: UserPreferences;
  onPackagePreferenceChange: (packageSize: PackagePreferenceId) => void;
}) {
  const account = accountOverview?.account;
  const billing = accountOverview?.billing;
  const billingConfigured = Boolean(billing?.configured);
  const billingDeskUrl = billing?.mode === "live" ? "https://desk.solvimon.com" : "https://test.desk.solvimon.com";

  return (
    <div className="narrow-account-panel">
      {pricing ? (
        <>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-100">
              {account?.display_name ?? "Local account"}
            </p>
            <p className="mt-1 truncate text-xs text-slate-500">
              {account?.email || account?.account_id || "No account loaded"}
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <UsageMetric label="Plan" value={pricing.plan_name} />
            <UsageMetric label="Used" value={`${pricing.used_blocks}/${pricing.included_blocks}`} />
            <UsageMetric label="Left" value={String(pricing.remaining_blocks)} />
          </div>
          <label className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2 text-xs">
            <span className="font-semibold text-slate-400">Package</span>
            <select
              aria-label="Preferred standard component package size"
              className="liquid-control rounded-lg px-2 py-1.5 font-semibold text-slate-200 outline-none"
              value={userPreferences.standardPackageSize}
              onChange={(event) =>
                onPackagePreferenceChange(event.target.value as PackagePreferenceId)
              }
            >
              {PASSIVE_PACKAGE_OPTIONS.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <button
            className="narrow-header-menu-item"
            type="button"
            disabled={!billingConfigured}
            onClick={() => window.open(billingDeskUrl, "_blank", "noopener,noreferrer")}
          >
            <span className="inline-flex min-w-0 items-center gap-2">
              <CreditCard size={15} />
              Manage billing
            </span>
            <ExternalLink size={13} />
          </button>
        </>
      ) : (
        <p className="text-sm leading-5 text-slate-500">Usage details are loading.</p>
      )}
    </div>
  );
}

function AccountMenu({
  accountOverview,
  pricing,
  userPreferences,
  onPackagePreferenceChange
}: {
  accountOverview: AccountOverview | null;
  pricing: PricingPreview | null;
  userPreferences: UserPreferences;
  onPackagePreferenceChange: (packageSize: PackagePreferenceId) => void;
}) {
  const used = pricing?.used_blocks ?? 0;
  const included = pricing?.included_blocks ?? 50;
  const percent = included > 0 ? Math.min(100, Math.round((used / included) * 100)) : 0;
  const ringStyle = {
    background: `conic-gradient(#7d9cbd ${percent * 3.6}deg, rgba(255,255,255,0.09) 0deg)`
  };
  const account = accountOverview?.account;
  const billing = accountOverview?.billing;
  const billingConfigured = Boolean(billing?.configured);
  const billingDeskUrl = billing?.mode === "live" ? "https://desk.solvimon.com" : "https://test.desk.solvimon.com";
  const recentEvents = pricing?.recent_events ?? [];

  return (
    <div className="group relative flex shrink-0 items-center">
      <button
        className="flex h-10 max-w-[14rem] items-center gap-2 rounded-full px-2.5 text-slate-300 transition duration-300 hover:bg-white/[0.06] hover:text-slate-100 focus:outline-none focus:ring-2 focus:ring-white/[0.16]"
        type="button"
        aria-label="Account and usage"
      >
        <UserRound className="shrink-0" size={21} aria-hidden="true" />
        <span className="truncate text-sm font-semibold text-slate-200">
          {account?.display_name ?? "Local account"}
        </span>
      </button>

      <div className="pointer-events-none invisible absolute right-0 top-[calc(100%+0.7rem)] z-40 w-[min(22rem,calc(100vw-2rem))] translate-y-1 rounded-xl border border-white/[0.08] bg-[#141418]/96 p-4 text-xs opacity-0 shadow-[0_18px_60px_rgba(0,0,0,0.34)] backdrop-blur-xl transition duration-300 group-hover:pointer-events-auto group-hover:visible group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:opacity-100">
        {pricing ? (
          <div className="space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <div
                  className="grid h-12 w-12 shrink-0 place-items-center rounded-full"
                  style={ringStyle}
                  aria-hidden="true"
                >
                  <div className="grid h-9 w-9 place-items-center rounded-full bg-[#141418]">
                    <span className="text-[11px] font-bold text-slate-200">{percent}%</span>
                  </div>
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-100">
                    {account?.display_name ?? "Local account"}
                  </p>
                  <p className="mt-1 truncate text-slate-500">
                    {account?.email || account?.account_id || "No account loaded"}
                  </p>
                  <p className="mt-1 text-[10px] font-bold uppercase tracking-[0.12em] text-slate-600">
                    Usage this month
                  </p>
                </div>
              </div>
              <span
                className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${
                  billingConfigured
                    ? "bg-emerald-400/10 text-emerald-300"
                    : "bg-amber-400/10 text-amber-300"
                }`}
              >
                {billingConfigured ? "Solvimon on" : "Local meter"}
              </span>
            </div>

            <div className="grid grid-cols-3 gap-2">
              <UsageMetric label="Plan" value={pricing.plan_name} />
              <UsageMetric label="Used" value={`${pricing.used_blocks}/${pricing.included_blocks}`} />
              <UsageMetric label="Left" value={String(pricing.remaining_blocks)} />
            </div>

            <div className="space-y-2 rounded-lg border border-white/[0.07] bg-white/[0.025] p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">Estimated bill</span>
                <span className="font-semibold text-slate-200">
                  {formatCurrency(pricing.estimated_monthly_bill)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">Estimated overage</span>
                <span className="font-semibold text-emerald-300">
                  {formatCurrency(pricing.estimated_overage)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">Billing sync</span>
                <span className="font-semibold text-slate-300">
                  {billingStatusLabel(billing)}
                </span>
              </div>
            </div>

            <div className="space-y-2 rounded-lg border border-white/[0.07] bg-white/[0.025] p-3">
              <label className="flex items-center justify-between gap-3">
                <span className="font-semibold text-slate-400">Standard package</span>
                <select
                  aria-label="Preferred standard component package size"
                  className="liquid-control rounded-lg px-2 py-1.5 font-semibold text-slate-200 outline-none"
                  value={userPreferences.standardPackageSize}
                  onChange={(event) =>
                    onPackagePreferenceChange(event.target.value as PackagePreferenceId)
                  }
                >
                  {PASSIVE_PACKAGE_OPTIONS.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <p className="leading-5 text-slate-600">
                Used for generated resistors and capacitors.
              </p>
            </div>

            {recentEvents.length ? (
              <div>
                <p className="mb-2 font-semibold text-slate-400">Recent usage</p>
                <div className="space-y-1.5">
                  {recentEvents.slice(-3).reverse().map((event) => (
                    <div
                      className="flex items-center justify-between gap-3 rounded-md bg-white/[0.025] px-2 py-1.5"
                      key={event.reference ?? `${event.event_type}-${event.timestamp}`}
                    >
                      <span className="truncate text-slate-400">{formatUsageEvent(event.event_type)}</span>
                      <span className="font-semibold text-slate-200">{event.quantity}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2 text-slate-500">
                No usage events recorded yet.
              </p>
            )}

            <div className="h-px bg-white/[0.07]" />

            <div className="grid gap-2">
              <button
                className="flex items-center justify-between rounded-lg border border-white/[0.08] bg-white/[0.035] px-3 py-2 font-semibold text-slate-200 transition hover:border-[#7d9cbd]/45 hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-50"
                type="button"
                disabled={!billingConfigured}
                onClick={() => window.open(billingDeskUrl, "_blank", "noopener,noreferrer")}
              >
                <span className="inline-flex items-center gap-2">
                  <CreditCard size={14} />
                  Manage billing
                </span>
                <ExternalLink size={13} />
              </button>
              <button
                className="rounded-lg border border-white/[0.08] bg-white/[0.02] px-3 py-2 text-left font-semibold text-slate-500"
                type="button"
                disabled
              >
                Account settings are local-only in this build
              </button>
              {!billingConfigured && billing?.setup_required.length ? (
                <p className="leading-5 text-amber-200/80">
                  {billing.setup_required[0]}
                </p>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="leading-5 text-slate-500">Usage details are loading.</p>
        )}
      </div>
    </div>
  );
}

function UsageMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2">
      <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-600">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-slate-200">{value}</p>
    </div>
  );
}

function billingStatusLabel(status?: BillingIntegrationStatus | null) {
  if (!status || !status.configured) return "Not configured";
  if (status.last_sync_status === "failed") return "Sync failed";
  if (status.last_sync_status === "synced") return "Synced";
  return status.mode === "live" ? "Live ready" : "Test ready";
}

function formatUsageEvent(eventType: string) {
  return eventType
    .split(".")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).replace(/_/g, " "))
    .join(" ");
}

function ProgressBar({
  active,
  partCount,
  onHome,
  onOpenLibrary
}: {
  active: string;
  partCount: number;
  onHome: () => void;
  onOpenLibrary: () => void;
}) {
  const steps = ["Identify", "Source", "Configure", "Preview", "Export"];
  const visibleActive = active === "Insert" || active === "Verify" ? "Export" : active;
  const activeIndex = Math.max(0, steps.indexOf(visibleActive));

  return (
    <div className="progress-banner border-b border-white/[0.06] bg-[#0f0f11] px-4 py-4">
      <div className="grid w-full items-center gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(420px,760px)_minmax(0,1fr)]">
        <div className="flex justify-start">
          <button
            className="library-action-button progress-nav-button"
            type="button"
            onClick={onOpenLibrary}
          >
            <Cpu size={18} className="text-white" />
            <span className="font-body text-sm font-semibold text-[#7d9cbd]">Past components</span>
            <span className="font-heading rounded-md bg-white/[0.08] px-1.5 py-0.5 text-[11px] text-slate-500">
              {partCount}
            </span>
          </button>
        </div>

        <div className="mx-auto flex w-full max-w-[760px] items-center justify-between">
          {steps.map((step, index) => {
            const done = index < activeIndex;
            const isActive = step === visibleActive;
            return (
              <div
                key={step}
                className="flex flex-1 items-center last:flex-none"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`grid h-8 w-8 place-items-center rounded-full text-sm font-semibold transition-all duration-500 ${
                      isActive
                        ? "bg-[#7d9cbd]/90 text-white shadow-[0_0_26px_rgba(125,156,189,0.36)]"
                        : done
                          ? "bg-[#7d9cbd]/74 text-white"
                          : "border border-white/[0.12] bg-white/[0.055] text-slate-500"
                    }`}
                  >
                    {done ? <Check size={15} /> : index + 1}
                  </span>
                  <span
                    className={`hidden text-sm font-semibold transition-colors duration-500 sm:inline ${
                      isActive ? "text-slate-100" : done ? "text-slate-300" : "text-slate-600"
                    }`}
                  >
                    {step}
                  </span>
                </div>
                {index < steps.length - 1 ? (
                  <span
                    className={`mx-3 h-px flex-1 transition-colors duration-500 ${
                      index < activeIndex ? "bg-[#7d9cbd]/70" : "bg-white/[0.08]"
                    }`}
                  />
                ) : null}
              </div>
            );
          })}
        </div>

        <div className="flex justify-end">
          <button
            className="library-action-button progress-nav-button"
            type="button"
            onClick={onHome}
          >
            <Home size={18} className="text-white" />
            <span className="font-body text-sm font-semibold text-[#7d9cbd]">Home</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function ChatView({
  messages,
  busy,
  extractionJob,
  onMessageAnimationComplete
}: {
  messages: ChatMessage[];
  busy: string | null;
  extractionJob: ComponentExtractionJob | null;
  onMessageAnimationComplete: (messageId: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) return;
    if (typeof scrollElement.scrollTo === "function") {
      scrollElement.scrollTo({
        top: scrollElement.scrollHeight,
        behavior: "smooth"
      });
    } else {
      scrollElement.scrollTop = scrollElement.scrollHeight;
    }
  }, [messages.length, busy]);

  return (
    <div ref={scrollRef} className="thin-scrollbar flex-1 space-y-5 overflow-y-auto p-5">
      {messages.map((message) => (
        <ChatBubble
          key={message.id}
          message={message}
          onAnimationComplete={onMessageAnimationComplete}
        />
      ))}
      {busy ? <LoadingStatusBubble busy={busy} extractionJob={extractionJob} /> : null}
    </div>
  );
}

function ChatBubble({
  message,
  onAnimationComplete
}: {
  message: ChatMessage;
  onAnimationComplete: (messageId: string) => void;
}) {
  const isUser = message.role === "user";

  return (
    <div className={`animate-fade-slide flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[92%] rounded-lg px-4 py-3 text-sm leading-6 ${
          isUser
            ? "whitespace-pre-line border border-[#7d9cbd]/25 bg-[#7d9cbd]/14 font-medium text-[#cdd9e6]"
            : "text-slate-300"
        }`}
      >
        {isUser ? (
          message.text
        ) : (
          <AssistantMessageContent
            text={message.text}
            animate={Boolean(message.animate)}
            onAnimationComplete={() => onAnimationComplete(message.id)}
          />
        )}
      </div>
    </div>
  );
}

function AssistantMessageContent({
  text,
  animate,
  onAnimationComplete
}: {
  text: string;
  animate: boolean;
  onAnimationComplete: () => void;
}) {
  const [visibleLength, setVisibleLength] = useState(animate ? 0 : text.length);
  const completedRef = useRef(false);
  const onAnimationCompleteRef = useRef(onAnimationComplete);

  useEffect(() => {
    onAnimationCompleteRef.current = onAnimationComplete;
  }, [onAnimationComplete]);

  useEffect(() => {
    completedRef.current = false;
    setVisibleLength(animate ? 0 : text.length);
  }, [animate, text]);

  useEffect(() => {
    if (!animate) return;

    if (visibleLength >= text.length) {
      if (!completedRef.current) {
        completedRef.current = true;
        onAnimationCompleteRef.current();
      }
      return;
    }

    const timer = window.setTimeout(() => {
      setVisibleLength((length) =>
        Math.min(text.length, length + ASSISTANT_TYPE_CHARS_PER_TICK)
      );
    }, ASSISTANT_TYPE_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [animate, text.length, visibleLength]);

  const displayedText = animate ? text.slice(0, visibleLength) : text;
  const lines = displayedText
    .split(/\n+/)
    .map((line) => cleanAssistantLine(line))
    .filter(Boolean);
  let activeSection = "";

  return (
    <div className="assistant-message">
      {lines.map((line, index) => {
        const section = sectionTitle(line);
        if (section) {
          activeSection = section.toLowerCase();
          return (
            <p key={`${line}-${index}`} className="assistant-section font-heading">
              {section}
            </p>
          );
        }

        const labeled = labeledLine(line);
        if (labeled) {
          activeSection = labeled.label.toLowerCase();
          return (
            <div key={`${line}-${index}`} className="assistant-labeled">
              <p className="assistant-label font-heading">{labeled.label}</p>
              <p>{labeled.text}</p>
            </div>
          );
        }

        const componentIntro = componentIntroLine(line);
        if (componentIntro) {
          return (
            <div key={`${line}-${index}`} className="assistant-component">
              <p className="assistant-component-name font-heading">{componentIntro.name}</p>
              <p>{componentIntro.detail}</p>
            </div>
          );
        }

        const bullet = bulletLine(line);
        if (bullet) {
          const tone = activeSection.includes("con") || activeSection.includes("warning")
            ? "warning"
            : activeSection.includes("pro") || activeSection.includes("good")
              ? "success"
              : "neutral";
          if (bullet.title) {
            return (
              <div key={`${line}-${index}`} className={`assistant-option assistant-option-${tone}`}>
                <p className="assistant-option-title font-heading">{bullet.title}</p>
                <p>{bullet.text}</p>
              </div>
            );
          }
          return (
            <p key={`${line}-${index}`} className={`assistant-bullet assistant-bullet-${tone}`}>
              {bullet.text}
            </p>
          );
        }

        return (
          <p key={`${line}-${index}`} className="assistant-body">
            {line}
          </p>
        );
      })}
    </div>
  );
}

function cleanAssistantLine(line: string) {
  return line.replace(/\*\*/g, "").trim();
}

function sectionTitle(line: string) {
  const match = line.match(/^(Good options|Pros|Cons|Advantages|Disadvantages|Tradeoffs|Comparison|Recommendation|Warnings|Next steps|Summary):$/i);
  if (!match) return null;
  return match[1];
}

function labeledLine(line: string) {
  const match = line.match(/^(Context|Pros|Cons|Recommendation|Summary|Warnings|Next steps|Comparison|Tradeoffs):\s+(.+)$/i);
  if (!match) return null;
  return { label: match[1], text: match[2] };
}

function componentIntroLine(line: string) {
  const identified = line.match(/^(.+?) identified\.\s*(.*)$/i);
  if (identified) {
    return {
      name: identified[1],
      detail: identified[2] || "Identified as the target component."
    };
  }

  const generated = line.match(/^I generated (.+?)(?= with |\.|,)(.*)$/i);
  if (generated) {
    return {
      name: generated[1],
      detail: `Generated${generated[2] || "."}`
    };
  }

  const found = line.match(/^I found (.+?)(?=\.|,)(.*)$/i);
  if (found) {
    return {
      name: found[1],
      detail: `Found${found[2] || "."}`
    };
  }

  const selected = line.match(/^(.+?) was selected because (.+)$/i);
  if (selected) {
    return {
      name: selected[1],
      detail: `Selected because ${selected[2]}`
    };
  }

  return null;
}

function bulletLine(line: string) {
  const match = line.match(/^[-*]\s+(.+)$/);
  if (!match) return null;
  const content = match[1].trim();
  const colonIndex = content.indexOf(":");
  if (colonIndex > 0 && colonIndex < 90) {
    return {
      title: content.slice(0, colonIndex).trim(),
      text: content.slice(colonIndex + 1).trim()
    };
  }
  return { title: "", text: content };
}

function LoadingStatusBubble({
  busy,
  extractionJob
}: {
  busy: string;
  extractionJob: ComponentExtractionJob | null;
}) {
  return (
    <div className="animate-fade-slide flex justify-start">
      <div className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-4 py-3">
        <InlineLoadingStatus busy={busy} extractionJob={extractionJob} />
      </div>
    </div>
  );
}

function InlineLoadingStatus({
  busy,
  extractionJob,
  className = ""
}: {
  busy: string | null;
  extractionJob?: ComponentExtractionJob | null;
  className?: string;
}) {
  const statusText = useLoadingStatus(busy, extractionJob);

  return (
    <div
      className={`loading-status-row ${className}`}
      role="status"
      aria-live="polite"
    >
      <TracePromptMark active compact />
      <div className="loading-status-window">
        <span key={`${busy ?? "busy"}-${statusText}`} className="loading-status-text">
          {statusText}
        </span>
      </div>
    </div>
  );
}

type LoadingStep = {
  text: string;
  holdMs?: number;
};

function useLoadingStatus(busy: string | null, extractionJob?: ComponentExtractionJob | null) {
  const steps = useMemo(
    () => loadingStepsForBusy(busy, extractionJob),
    [
      busy,
      extractionJob?.job_id,
      extractionJob?.status,
      extractionJob?.progress,
      extractionJob?.message,
      extractionJob?.candidate?.manufacturer,
      extractionJob?.candidate?.part_number,
      extractionJob?.candidate?.datasheet_sources?.[0]?.title,
      extractionJob?.candidate?.datasheet_sources?.[0]?.url
    ]
  );
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    setStepIndex(0);
  }, [steps]);

  useEffect(() => {
    if (stepIndex >= steps.length - 1) return;
    const timer = window.setTimeout(() => {
      setStepIndex((index) => Math.min(index + 1, steps.length - 1));
    }, steps[stepIndex]?.holdMs ?? 1500);
    return () => window.clearTimeout(timer);
  }, [stepIndex, steps]);

  return steps[Math.min(stepIndex, steps.length - 1)]?.text ?? "Working";
}

function loadingStepsForBusy(
  busy: string | null,
  extractionJob?: ComponentExtractionJob | null
): LoadingStep[] {
  if (busy === "chat") {
    return [
      { text: "Sending request to /chat", holdMs: 900 },
      { text: "Waiting for backend part matching", holdMs: 1800 },
      { text: "Reading returned draft choices", holdMs: 1600 },
      { text: "Still waiting for the backend response" }
    ];
  }

  if (busy === "generate") {
    return [
      { text: "Posting selected answers to /answer-questions", holdMs: 900 },
      { text: "Waiting for CircuitBlock generation", holdMs: 1600 },
      { text: "Checking components, warnings, and next steps", holdMs: 1700 },
      { text: "Preparing schematic preview and part library entry" }
    ];
  }

  if (busy === "extract") {
    return extractionLoadingSteps(extractionJob);
  }

  if (busy === "export") {
    return [
      { text: "Preparing generated KiCad files", holdMs: 900 },
      { text: "Writing block export bundle", holdMs: 1500 },
      { text: "Refreshing usage meter" }
    ];
  }

  if (busy === "insert") {
    return [
      { text: "Checking exported block before insert", holdMs: 900 },
      { text: "Sending import request to KiCad bridge", holdMs: 1600 },
      { text: "Waiting for KiCad bridge confirmation" }
    ];
  }

  if (busy === "link") {
    return [
      { text: "Linking KiCad project folder", holdMs: 900 },
      { text: "Checking bridge status", holdMs: 1400 },
      { text: "Waiting for project connection" }
    ];
  }

  return [{ text: "Working" }];
}

export function documentationSourceForState(
  block: CircuitBlock | null,
  job?: ComponentExtractionJob | null
) {
  return (
    preferredDatasheetSource(block?.datasheet_sources) ??
    preferredDatasheetSource(job?.candidate?.datasheet_sources) ??
    null
  );
}

function preferredDatasheetSource(sources?: DatasheetSource[] | null) {
  if (!sources?.length) return null;
  const usableSources = sources.filter((source) => source.title || source.url);
  if (!usableSources.length) return null;
  return (
    usableSources.find((source) => source.source_type === "manufacturer_datasheet") ??
    usableSources.find((source) => isHttpUrl(source.url)) ??
    usableSources[0]
  );
}

function documentationContextText(
  block: CircuitBlock | null,
  job: ComponentExtractionJob | null,
  source: DatasheetSource | null
) {
  if (!source) return "";
  if (block) {
    return "This documentation is attached to the current review block.";
  }
  if (!job) return "";

  if (job.status === "queued") {
    return "Candidate documentation is selected. Trace Labs has not opened it for extraction yet.";
  }
  if (job.status === "fetching_sources") {
    return "Trace Labs is opening this source and still looking for readable datasheet text.";
  }
  if (job.status === "failed") {
    return "This source was used for the failed extraction attempt. Review it before trying again.";
  }
  if (job.status === "ready") {
    return "Readable documentation and cited circuit evidence are ready for review.";
  }
  if (jobHasReadableSources(job)) {
    return "Readable datasheet text was found. Pin and reference-circuit extraction is still running.";
  }
  return "";
}

function documentationEmptyText(job: ComponentExtractionJob | null) {
  if (!job) return "Recipe documentation appears after generation.";
  if (job.status === "fetching_sources" || job.status === "queued") {
    return "Trace Labs is still looking for a readable datasheet source.";
  }
  if (jobHasReadableSources(job)) {
    return "Readable datasheet text was found, but no displayable documentation URL was captured.";
  }
  return "No documentation source is available for this extraction yet.";
}

function documentationSourceDisplayName(source?: DatasheetSource | null) {
  if (!source) return "";
  return source.title || source.url || "selected documentation source";
}

function datasheetFoundNotification(job: ComponentExtractionJob) {
  const source = documentationSourceForState(null, job);
  const sourceLine = source
    ? `Documentation is now listed in the Documentation panel: ${documentationSourceDisplayName(source)}.`
    : "Trace Labs found readable datasheet text, but no displayable documentation URL was captured.";
  return (
    `${sentenceWithProgress(job.message, job.progress)}\n\n` +
    `${sourceLine} Pin and support-circuit extraction is still running before schematic creation.`
  );
}

export function extractionLoadingSteps(job?: ComponentExtractionJob | null): LoadingStep[] {
  const subject = extractionSubject(job);
  const liveMessage = job?.message ? sentenceWithProgress(job.message, job.progress) : "";
  const stage = job?.status ?? "queued";
  const source = documentationSourceForState(null, job);
  const sourceName = documentationSourceDisplayName(source) || "selected documentation";
  const stageSteps: Record<ComponentExtractionJob["status"], LoadingStep[]> = {
    queued: [
      { text: `Queued extraction for ${subject}; documentation links are selected`, holdMs: 1100 },
      { text: "Waiting for the extraction worker to open the sources", holdMs: 2200 },
      { text: "No readable datasheet text has been confirmed yet" }
    ],
    fetching_sources: [
      { text: `Opening ${sourceName} for ${subject}`, holdMs: 1400 },
      { text: "Still looking for readable datasheet or reference text", holdMs: 2200 },
      { text: "No pins or support parts have been extracted yet" }
    ],
    sources_found: [
      { text: `Found readable datasheet content for ${subject}`, holdMs: 1500 },
      { text: "Documentation is available while extraction continues", holdMs: 2200 },
      { text: "Extracting pin and reference-circuit evidence from the source text" }
    ],
    extracting: [
      { text: `Inside readable datasheet/reference text for ${subject}`, holdMs: 1600 },
      { text: "Extracting required passives, nets, and citations", holdMs: 2400 },
      { text: "Schematic creation is waiting for cited circuit evidence" }
    ],
    acquiring_cad: [
      { text: `Datasheet evidence extracted for ${subject}`, holdMs: 1500 },
      { text: "Matching package notes to KiCad assets", holdMs: 2200 },
      { text: "Flagging CAD items that need review" }
    ],
    validating: [
      { text: `Validating datasheet citations for ${subject}`, holdMs: 1400 },
      { text: "Checking unanswered questions and warnings", holdMs: 2200 },
      { text: "Preparing the reviewable draft circuit" }
    ],
    ready: [
      { text: `Extraction ready for ${subject}`, holdMs: 1200 },
      { text: "Preparing confirmation choices" }
    ],
    failed: [
      { text: `Extraction failed for ${subject}`, holdMs: 1200 },
      { text: "Collecting backend error details" }
    ]
  };

  return uniqueLoadingSteps([
    ...(liveMessage ? [{ text: liveMessage, holdMs: 1600 }] : []),
    ...(stageSteps[stage] ?? stageSteps.queued)
  ]);
}

export function extractionTimeoutMessage(job?: ComponentExtractionJob | null) {
  const base = "Datasheet extraction timed out before a reviewable circuit was ready.";
  if (!job) {
    return `${base} Trace Labs did not receive a backend status update before the timeout.`;
  }

  const subject = extractionSubject(job);
  const lastStatus = job.message
    ? `Last status: ${sentenceWithProgress(job.message, job.progress)}`
    : `Last backend stage: ${job.status}.`;

  if (job.status === "queued" || job.status === "fetching_sources") {
    return `${base} Trace Labs was still looking for readable datasheet text for ${subject}. ${lastStatus}`;
  }

  if (jobHasReadableSources(job)) {
    return (
      `${base} Trace Labs had already found readable datasheet content for ${subject}, ` +
      `so the request may be worth waiting on. ${lastStatus}`
    );
  }

  return `${base} ${lastStatus}`;
}

function jobHasReadableSources(job: ComponentExtractionJob) {
  return ["sources_found", "extracting", "acquiring_cad", "validating"].includes(job.status);
}

function extractionSubject(job?: ComponentExtractionJob | null) {
  const candidate = job?.candidate;
  const manufacturer = candidate?.manufacturer?.trim();
  const partNumber = candidate?.part_number?.trim();
  if (manufacturer && partNumber) return `${manufacturer} ${partNumber}`;
  if (partNumber) return partNumber;
  return "the selected part";
}

function sentenceWithProgress(message: string, progress?: number) {
  const text = message.trim().replace(/[.!?]+$/, "");
  const progressText = progressPercent(progress);
  return progressText ? `${text} (${progressText}).` : `${text}.`;
}

function progressPercent(progress?: number) {
  if (typeof progress !== "number" || Number.isNaN(progress) || progress <= 0 || progress >= 1) {
    return "";
  }
  return `${Math.round(progress * 100)}%`;
}

function uniqueLoadingSteps(steps: LoadingStep[]) {
  const seen = new Set<string>();
  return steps.filter((step) => {
    const key = step.text.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function OptionForm({
  questions,
  answers,
  onAnswerQuestion,
  activeQuestionIndex,
  busy
}: {
  questions: MissingQuestion[];
  answers: Record<string, string>;
  onAnswerQuestion: (question: MissingQuestion, option: Option) => void;
  activeQuestionIndex: number;
  busy: string | null;
}) {
  const question = questions[activeQuestionIndex] ?? questions[0];
  const selected = question ? answers[question.id] : "";
  const [inputValue, setInputValue] = useState(selected ?? question?.default ?? "");

  useEffect(() => {
    setInputValue(selected ?? question?.default ?? "");
  }, [question?.id, question?.default, selected]);

  if (!question) return null;

  const submitInputAnswer = () => {
    const value = inputValue.trim();
    if (question.required && !value) return;
    onAnswerQuestion(question, {
      label: value || "No answer provided",
      value
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-300">
          <Sparkles size={16} className="text-[#7d9cbd]" />
          Configure choice
        </div>
        <span className="text-xs text-slate-600">
          Question {activeQuestionIndex + 1} of {questions.length}
        </span>
      </div>
      <div key={question.id} className="animate-question-swap space-y-3">
        <div className="flex justify-start">
          <div className="max-w-[92%] rounded-lg px-4 py-3 text-sm font-semibold leading-6 text-slate-300">
            {question.question}
          </div>
        </div>
        {question.type === "select" ? (
          <div className="grid grid-cols-2 gap-2">
            {question.options.map((option) => {
              const optionSelected = selected === option.value;
              return (
                <button
                  key={option.value}
                  className={`rounded-xl px-3 py-2 text-sm font-semibold transition duration-500 ${
                    optionSelected
                      ? "border border-[#a8c4e0] bg-[#7d9cbd] text-white shadow-[0_0_0_1px_rgba(255,255,255,0.16)_inset,0_12px_30px_rgba(125,156,189,0.24)]"
                      : "liquid-control text-slate-500 hover:text-slate-300"
                  }`}
                  disabled={Boolean(busy)}
                  onClick={() => onAnswerQuestion(question, option)}
                  type="button"
                >
                  <span className="flex items-center justify-center gap-2">
                    {optionSelected ? <Check size={15} /> : null}
                    {option.label}
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="flex gap-2">
            <input
              className="liquid-control min-w-0 flex-1 rounded-xl px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600"
              type={question.type === "number" ? "number" : "text"}
              inputMode={question.type === "number" ? "decimal" : "text"}
              value={inputValue}
              disabled={Boolean(busy)}
              placeholder={question.default || "Enter value"}
              onChange={(event) => setInputValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  submitInputAnswer();
                }
              }}
            />
            <button
              className="rounded-xl bg-[#7d9cbd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#8aa8c5] disabled:opacity-60"
              type="button"
              disabled={Boolean(busy) || (question.required && !inputValue.trim())}
              onClick={submitInputAnswer}
            >
              Continue
            </button>
          </div>
        )}
      </div>
      <p className="text-xs leading-5 text-slate-600">
        {question.type === "select" ? "Pick an answer to continue." : "Enter a value to continue."}
      </p>
    </div>
  );
}

function ProjectConnectionControl({
  bridgeStatus,
  busy,
  projectPath,
  setProjectPath,
  onLinkProject,
  onRefreshBridge,
  compact = false
}: {
  bridgeStatus: BridgeStatus | null;
  busy: string | null;
  projectPath: string;
  setProjectPath: (value: string) => void;
  onLinkProject: () => void;
  onRefreshBridge: () => void;
  compact?: boolean;
}) {
  const [showSetup, setShowSetup] = useState(false);
  const [setupPopoverStyle, setSetupPopoverStyle] = useState<CSSProperties | null>(null);
  const setupButtonRef = useRef<HTMLButtonElement | null>(null);
  const connected = Boolean(bridgeStatus?.connected);
  const projectName = bridgeStatus?.project_name ?? "KiCad";
  const disabled = busy === "link";

  useLayoutEffect(() => {
    if (!showSetup) {
      setSetupPopoverStyle(null);
      return;
    }

    const updateSetupPopoverPosition = () => {
      if (typeof window === "undefined") return;

      const rect = setupButtonRef.current?.getBoundingClientRect();
      if (!rect) return;

      const margin = 12;
      const gap = 8;
      const width = Math.min(288, window.innerWidth * 0.72);
      const left = Math.min(
        window.innerWidth - width - margin,
        Math.max(margin, rect.right - width)
      );
      const placeAbove = compact || rect.bottom + 180 > window.innerHeight;
      const nextStyle: CSSProperties = {
        left,
        width,
        zIndex: 10000
      };

      if (placeAbove) {
        nextStyle.bottom = Math.max(margin, window.innerHeight - rect.top + gap);
      } else {
        nextStyle.top = Math.min(window.innerHeight - margin, rect.bottom + gap);
      }

      setSetupPopoverStyle(nextStyle);
    };

    updateSetupPopoverPosition();
    window.addEventListener("resize", updateSetupPopoverPosition);
    window.addEventListener("scroll", updateSetupPopoverPosition, true);

    return () => {
      window.removeEventListener("resize", updateSetupPopoverPosition);
      window.removeEventListener("scroll", updateSetupPopoverPosition, true);
    };
  }, [compact, showSetup]);

  useEffect(() => {
    if (!showSetup) {
      return;
    }

    const dismissSetup = (event: MouseEvent) => {
      if (
        event.target instanceof Element &&
        event.target.closest("[data-project-setup-toggle], [data-project-setup-popover]")
      ) {
        return;
      }

      setShowSetup(false);
    };
    document.addEventListener("click", dismissSetup);

    return () => document.removeEventListener("click", dismissSetup);
  }, [showSetup]);

  const setupPopover =
    showSetup && setupPopoverStyle && typeof document !== "undefined"
      ? createPortal(
          <div
            className="trace-labs-theme project-setup-popover project-setup-popover-floating"
            data-project-setup-popover
            style={setupPopoverStyle}
          >
            <p className="font-heading text-xs font-semibold text-slate-200">KiCad setup</p>
            <ol className="mt-2 space-y-1.5 text-left text-xs leading-5 text-slate-500">
              <li>1. Open KiCad and launch the project you want Trace Labs to edit.</li>
              <li>2. Paste or choose that project folder here.</li>
              <li>3. Click Link, then Refresh if KiCad was opened after this app.</li>
              <li>4. Keep KiCad open while inserting generated blocks.</li>
            </ol>
          </div>,
          document.body
        )
      : null;

  return (
    <div className={`project-connection-card ${compact ? "project-connection-card-compact" : ""}`}>
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <div className="flex min-w-32 items-center gap-2">
          <span
            className={`h-2.5 w-2.5 shrink-0 rounded-full ${
              connected ? "animate-status-pulse bg-emerald-400" : "bg-amber-400"
            }`}
          />
          <div className="min-w-0 text-left leading-tight">
            <p className={connected ? "text-xs font-semibold text-emerald-300" : "text-xs font-semibold text-amber-200"}>
              {connected ? "Project connected" : "No project connected"}
            </p>
            <p className="truncate text-[11px] text-slate-600">{projectName}</p>
          </div>
        </div>

        <input
          className="project-path-input min-w-0 flex-1 rounded-lg px-3 py-2 text-xs text-slate-200 outline-none placeholder:text-slate-500"
          value={projectPath}
          onChange={(event) => setProjectPath(event.target.value)}
          aria-label="KiCad project folder"
          placeholder="Project folder"
        />

        <button
          className="liquid-control inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold text-slate-200 disabled:opacity-60"
          onClick={onLinkProject}
          disabled={disabled}
          type="button"
        >
          {disabled ? <MiniGradientLoader /> : <Link size={14} />}
          {connected ? "Change" : "Link"}
        </button>

        <button
          className="liquid-control rounded-lg p-2 text-slate-300 disabled:opacity-60"
          type="button"
          aria-label="Refresh KiCad bridge status"
          onClick={onRefreshBridge}
          disabled={disabled}
        >
          {disabled ? <MiniGradientLoader /> : <RefreshCw size={15} />}
        </button>

        <div className="relative">
          <button
            ref={setupButtonRef}
            className="liquid-control rounded-lg p-2 text-[#7d9cbd]"
            type="button"
            aria-label="Show KiCad setup steps"
            data-project-setup-toggle
            onClick={() => setShowSetup((value) => !value)}
          >
            <Info size={15} />
          </button>
          {setupPopover}
        </div>
      </div>
    </div>
  );
}

function PromptInput({
  value,
  canPrompt,
  onChange,
  onSubmit,
  busy
}: {
  value: string;
  canPrompt: boolean;
  onChange: (value: string) => void;
  onSubmit: (event?: FormEvent) => void;
  busy: string | null;
}) {
  return (
    <div className="border-t border-white/[0.08] p-5">
      <form onSubmit={onSubmit}>
        <div className="flex gap-2">
          <div className="liquid-control prompt-glow-input flex min-w-0 flex-1 items-center gap-2 rounded-xl px-3 py-2">
            <input
              className="min-w-0 flex-1 bg-transparent px-1 py-1 text-sm text-slate-100 outline-none placeholder:text-slate-600"
              value={value}
              onChange={(event) => onChange(event.target.value)}
              disabled={!canPrompt || Boolean(busy)}
              placeholder={canPrompt ? "Ask Trace Labs anything..." : "Connect a KiCad project to start"}
            />
          </div>
          <button
            className="inline-flex items-center gap-2 rounded-xl bg-[#7d9cbd] px-4 py-3 text-sm font-semibold text-white transition duration-700 hover:bg-[#8aa8c5] disabled:opacity-60"
            disabled={!canPrompt || Boolean(busy) || value.trim().length === 0}
            type="submit"
          >
            {busy ? <MiniGradientLoader /> : <Send size={17} />}
            Send
          </button>
        </div>
      </form>
    </div>
  );
}

function ReadyInsertPanel({
  block,
  busy,
  importResult,
  onInsertMode,
  onNewPart,
  onUpdateAnswer
}: {
  block: CircuitBlock | null;
  busy: string | null;
  importResult: BridgeImportResponse | null;
  onInsertMode: (mode: ImportMode) => void;
  onNewPart: () => void;
  onUpdateAnswer: (answerId: EditableAnswerId, option: Option) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [activeEditId, setActiveEditId] = useState<EditableAnswerId | null>(null);

  useEffect(() => {
    if (!editing) {
      setActiveEditId(null);
    }
  }, [editing]);

  if (!block) return null;

  const summaryItems = answerSummaryItems(block);
  const disabled = busy === "export" || busy === "insert";

  return (
    <div className="animate-fade-slide border-t border-white/[0.08] p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-300">
          <Sparkles size={16} className="text-[#7d9cbd]" />
          Ready to insert
        </div>
      </div>
      <div className="mt-4 rounded-2xl border border-white/[0.08] bg-white/[0.035] p-4">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm font-semibold text-slate-300">Answer summary</p>
          <button
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition duration-500 ${
              editing
                ? "bg-[#7d9cbd] text-white shadow-[0_10px_26px_rgba(125,156,189,0.22)]"
                : "liquid-control text-slate-400"
            }`}
            type="button"
            onClick={() => setEditing((value) => !value)}
          >
            {editing ? "Done" : "Edit"}
          </button>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {summaryItems.map((item) => (
            <div key={item.id} className="relative">
              <button
                className={`w-full rounded-lg border px-3 py-2 text-left transition duration-500 ${
                  editing
                    ? "border-[#7d9cbd]/35 bg-[#7d9cbd]/10 hover:border-[#a8c4e0]/55 hover:bg-[#7d9cbd]/16"
                    : "border-white/[0.06] bg-black/15"
                }`}
                type="button"
                disabled={!editing}
                onClick={() => setActiveEditId((active) => (active === item.id ? null : item.id))}
              >
                <p className="text-xs text-slate-600">{item.label}</p>
                <p className="mt-1 text-sm font-semibold text-slate-200">{item.value}</p>
              </button>

              {editing && activeEditId === item.id ? (
                <div className="absolute left-0 right-0 top-[calc(100%+0.45rem)] z-30 animate-fade-slide rounded-xl border border-white/[0.1] bg-[#141418]/95 p-2 shadow-[0_18px_46px_rgba(0,0,0,0.32)] backdrop-blur-xl">
                  {item.options.map((option) => {
                    const selected = block.selected_options[item.id] === option.value;
                    return (
                      <button
                        key={option.value}
                        className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-xs font-semibold transition duration-500 ${
                          selected
                            ? "bg-[#7d9cbd]/22 text-[#cdd9e6]"
                            : "text-slate-400 hover:bg-white/[0.05] hover:text-slate-200"
                        }`}
                        type="button"
                        onClick={() => {
                          onUpdateAnswer(item.id, option);
                          setActiveEditId(null);
                        }}
                      >
                        <span>{option.label}</span>
                        {selected ? <Check size={14} /> : null}
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </div>
      {importResult ? (
        <div className="mt-4 grid gap-2">
          <div className="rounded-xl border border-emerald-300/18 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">
            Component added to KiCad.
          </div>
          <button
            className="rounded-xl bg-[#7d9cbd] px-4 py-3 text-sm font-semibold text-white shadow-[0_16px_40px_rgba(125,156,189,0.2)] transition duration-700 hover:bg-[#8aa8c5]"
            onClick={onNewPart}
            type="button"
          >
            New part
          </button>
        </div>
      ) : (
        <div className="mt-4 grid gap-2">
          <button
            className="rounded-xl bg-[#7d9cbd] px-4 py-3 text-sm font-semibold text-white shadow-[0_16px_40px_rgba(125,156,189,0.2)] transition duration-700 hover:bg-[#8aa8c5] disabled:opacity-50"
            disabled={disabled}
            onClick={() => onInsertMode("hierarchical_sheet")}
            type="button"
          >
            Insert as subsheet
          </button>
          <button
            className="liquid-control rounded-xl px-4 py-3 text-sm font-semibold text-slate-200 disabled:opacity-50"
            disabled={disabled}
            onClick={() => onInsertMode("inline_main")}
            type="button"
          >
            Insert on main sheet
          </button>
        </div>
      )}
    </div>
  );
}

function MiniGradientLoader() {
  return <span className="mini-gradient-loader" aria-hidden="true" />;
}

export default App;
