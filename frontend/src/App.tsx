import {
  Check,
  Cpu,
  History,
  Home,
  Link,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  X
} from "lucide-react";
import {
  FormEvent,
  PointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8765";
const DEMO_CHAT_DELAY_MS = 900;
const DEMO_GENERATE_DELAY_MS = 1800;
const PART_LIBRARY_STORAGE_KEY = "pcbstream.partLibrary.v3";
const EXTRACT_CANDIDATE_PREFIX = "extract_candidate::";
const EXTRACTION_POLL_INTERVAL_MS = 1800;
const EXTRACTION_TIMEOUT_MS = 180000;

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
  type: "select";
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

type ComponentExtractionJob = {
  job_id: string;
  status: "queued" | "fetching_sources" | "extracting" | "acquiring_cad" | "validating" | "ready" | "failed";
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
};

function initialChatMessages(): ChatMessage[] {
  return [
    {
      id: `welcome-${Date.now()}`,
      role: "assistant",
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
};

type EditableAnswerId = "logic_voltage" | "interface_mode" | "i2c_address" | "pullups" | "pullup_value";

type AnswerSummaryItem = {
  id: EditableAnswerId;
  label: string;
  value: string;
  options: Option[];
};

type ComponentTableRow = {
  key: string;
  reference: string;
  component: Component | SupportComponent;
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
    const stored = window.localStorage.getItem(PART_LIBRARY_STORAGE_KEY);
    if (!stored) return [];
    const parsed = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((entry): entry is PartLibraryEntry =>
        Boolean(entry?.id && entry?.block?.block_name && Array.isArray(entry?.messages))
      )
      .map(normalizePartLibraryEntry);
  } catch {
    return [];
  }
}

function persistPartLibrary(entries: PartLibraryEntry[]) {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(PART_LIBRARY_STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Local storage is best effort; the generated block still remains active in the UI.
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

function normalizePartLibraryEntry(entry: PartLibraryEntry): PartLibraryEntry {
  return { ...entry, block: normalizeCircuitBlockForCurrentSchema(entry.block) };
}

function questionIsActive(question: MissingQuestion, answerValues: Record<string, string>) {
  return Object.entries(question.depends_on ?? {}).every(
    ([answerId, expected]) => answerValues[answerId] === expected
  );
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
    { key: "main", reference: block.block_slug === "bme280_i2c" ? "U1" : `U${referenceBase(block.block_slug)}`, component: block.main_component }
  ];

  if (block.block_slug === "bme280_i2c") {
    const capacitors = block.support_components.filter((component) => component.type === "capacitor");
    capacitors.forEach((component, index) => {
      rows.push({ key: `bme-cap-${index}`, reference: `C${index + 1}`, component });
    });

    const { sdaPullup, sclPullup, sdoStrap, csbStrap } = bmeResistors(block);
    const orderedResistors = [sdaPullup, sclPullup, sdoStrap, csbStrap].filter(
      (component): component is SupportComponent => Boolean(component)
    );
    orderedResistors.forEach((component, index) => {
      rows.push({ key: `bme-res-${index}`, reference: `R${index + 1}`, component });
    });

    const used = new Set<SupportComponent>([...capacitors, ...orderedResistors]);
    block.support_components
      .filter((component) => !used.has(component))
      .forEach((component, index) => {
        rows.push({ key: `bme-extra-${index}`, reference: component.reference, component });
      });
    return rows;
  }

  const base = referenceBase(block.block_slug);
  let capacitorIndex = 1;
  let resistorIndex = 1;
  block.support_components.forEach((component, index) => {
    if (component.type === "capacitor" || component.symbol === "Device:C") {
      rows.push({ key: `cap-${index}`, reference: `C${base + capacitorIndex}`, component });
      capacitorIndex += 1;
      return;
    }
    if (component.type === "resistor" || component.symbol === "Device:R") {
      rows.push({ key: `res-${index}`, reference: `R${base + resistorIndex}`, component });
      resistorIndex += 1;
      return;
    }
    rows.push({ key: `support-${index}`, reference: component.reference, component });
  });

  return rows;
}

function defaultPullupComponents(logicNet: string, value = "4.7 kOhm"): SupportComponent[] {
  const pullupValue = displayedAnswerValue(value);
  return [
    {
      reference: "R?",
      type: "resistor",
      value: pullupValue,
      purpose: "I2C SDA pull-up",
      symbol: "Device:R",
      footprint: "Resistor_SMD:R_0603_1608Metric",
      footprint_confidence: "default_selected",
      symbol_confidence: "default_selected",
      connects: ["I2C1_SDA", logicNet],
      assignment_reason: "Default selected from Trace Labs passive defaults."
    },
    {
      reference: "R?",
      type: "resistor",
      value: pullupValue,
      purpose: "I2C SCL pull-up",
      symbol: "Device:R",
      footprint: "Resistor_SMD:R_0603_1608Metric",
      footprint_confidence: "default_selected",
      symbol_confidence: "default_selected",
      connects: ["I2C1_SCL", logicNet],
      assignment_reason: "Default selected from Trace Labs passive defaults."
    }
  ];
}

function syncBlockWithAnswer(
  block: CircuitBlock,
  answerId: EditableAnswerId,
  value: string
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
      : (existingPullups.length >= 2 ? existingPullups : defaultPullupComponents(logicNet, pullupValue)).map(
          updateSupport
        );
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
  const [messages, setMessages] = useState<ChatMessage[]>(initialChatMessages);
  const messagesRef = useRef<ChatMessage[]>(messages);
  const [prompt, setPrompt] = useState("");
  const [draftBlock, setDraftBlock] = useState<CircuitBlock | null>(null);
  const [block, setBlock] = useState<CircuitBlock | null>(null);
  const [questions, setQuestions] = useState<MissingQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
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
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [activeLibraryEntryId, setActiveLibraryEntryId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"home" | "workspace">("home");
  const [homeExiting, setHomeExiting] = useState(false);

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
      const [healthResponse, pricingResponse, statusResponse] = await Promise.all([
        api<HealthResponse>("/health"),
        api<PricingPreview>("/pricing-preview"),
        api<BridgeStatus>("/bridge/status")
      ]);
      setHealth(healthResponse);
      setPricing(pricingResponse);
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

  function addMessage(role: ChatMessage["role"], text: string) {
    const message = { id: `${role}-${Date.now()}-${Math.random()}`, role, text };
    const nextMessages = [...messagesRef.current, message];
    setChatMessages(nextMessages);
    return message;
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

  function applyExtractionDraft(job: ComponentExtractionJob) {
    if (!job.draft_block) {
      throw new Error("Extraction finished without a generated draft block.");
    }

    const readyDraft = normalizeCircuitBlockForCurrentSchema(job.draft_block);
    setBlock(null);
    setDraftBlock(readyDraft);
    setQuestions(readyDraft.missing_questions);
    setAnswers(
      Object.fromEntries(
        readyDraft.missing_questions.map((question) => [question.id, question.default])
      )
    );
    setActiveQuestionIndex(0);
    setNextStepChecks({});
    setExportResult(null);
    setImportResult(null);
    setActiveLibraryEntryId(null);
    setExtractionJob(null);
  }

  async function pollExtractionJob(jobId: string, initialJob?: ComponentExtractionJob | null) {
    const deadline = Date.now() + EXTRACTION_TIMEOUT_MS;
    let currentJob = initialJob ?? null;

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
      setExtractionJob(currentJob);

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

    const message = "Datasheet extraction timed out before a reviewable circuit was ready.";
    setError(message);
    addMessage("assistant", message);
  }

  async function startExtractionFromChoice(option: Option) {
    addMessage("user", option.label);
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
      setExtractionJob(job);
      addMessage("assistant", job.message);
      await pollExtractionJob(job.job_id, job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to start datasheet extraction.");
    } finally {
      setBusy(null);
    }
  }

  function saveBlockToPartLibrary(
    savedBlock: CircuitBlock,
    answerValues: Record<string, string>,
    chatMessages = messagesRef.current
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
        messages: chatMessages
      };
      return [entry, ...current.filter((item) => item.id !== entryId)].slice(0, 30);
    });
  }

  function restorePartLibraryEntry(entry: PartLibraryEntry) {
    const normalizedEntry = normalizePartLibraryEntry(entry);
    setChatMessages(normalizedEntry.messages);
    setBlock(normalizedEntry.block);
    setDraftBlock(null);
    setQuestions([]);
    setAnswers(normalizedEntry.answers);
    setActiveQuestionIndex(0);
    setNextStepChecks(
      Object.fromEntries(normalizedEntry.block.next_steps.map((step) => [step.id, step.status === "done"]))
    );
    setExportResult(null);
    setImportResult(null);
    setExtractionJob(null);
    setActiveLibraryEntryId(normalizedEntry.id);
    setLibraryOpen(false);
    setViewMode("workspace");
    addToast("Loaded from part library", [normalizedEntry.title, normalizedEntry.summary]);
  }

  function returnToHome() {
    setBlock(null);
    setDraftBlock(null);
    setQuestions([]);
    setAnswers({});
    setActiveQuestionIndex(0);
    setNextStepChecks({});
    setExportResult(null);
    setImportResult(null);
    setExtractionJob(null);
    setPrompt("");
    setLibraryOpen(false);
    setChatMessages(initialChatMessages());
    setHomeExiting(false);
    setViewMode("home");
  }

  function startNewChat() {
    setLibraryOpen(false);
    setActiveLibraryEntryId(null);
    returnToHome();
  }

  async function submitMessage(event?: FormEvent, override?: string) {
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
    addMessage("user", message);

    try {
      if (startingFromHome) {
        await wait(420);
        setViewMode("workspace");
        setHomeExiting(false);
      }
      const startedAt = Date.now();
      const response = await api<ChatResponse>("/chat", {
        method: "POST",
        body: JSON.stringify({
          message,
          draft_block: draftBlock,
          current_block: block,
          answers,
          history: chatHistoryPayload(messagesRef.current)
        })
      });
      await wait(Math.max(0, DEMO_CHAT_DELAY_MS - (Date.now() - startedAt)));
      addMessage("assistant", response.assistant_message);
      if (response.extraction_job) {
        setBlock(null);
        setDraftBlock(null);
        setQuestions([]);
        setAnswers({});
        setExportResult(null);
        setImportResult(null);
        setNextStepChecks({});
        setActiveLibraryEntryId(null);
        setExtractionJob(response.extraction_job);
        await pollExtractionJob(response.extraction_job.job_id, response.extraction_job);
        await refreshPricing();
        return;
      }
      if (response.draft_block) {
        setBlock(null);
        setExportResult(null);
        setImportResult(null);
        setExtractionJob(null);
        setNextStepChecks({});
        setActiveLibraryEntryId(null);
        setDraftBlock(response.draft_block);
      }
      setQuestions(response.missing_questions);
      setActiveQuestionIndex(0);
      setAnswers(
        Object.fromEntries(
          response.missing_questions.map((question) => [question.id, question.default])
        )
      );
      await refreshPricing();
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
      const startedAt = Date.now();
      const response = await api<CircuitBlock>("/answer-questions", {
        method: "POST",
        body: JSON.stringify({ answers: answersOverride, draft_block: draftBlock })
      });
      const normalizedResponse = normalizeCircuitBlockForCurrentSchema(response);
      await wait(Math.max(0, DEMO_GENERATE_DELAY_MS - (Date.now() - startedAt)));
      setBlock(normalizedResponse);
      setDraftBlock(null);
      setQuestions([]);
      setExtractionJob(null);
      setActiveQuestionIndex(0);
      setNextStepChecks(
        Object.fromEntries(normalizedResponse.next_steps.map((step) => [step.id, step.status === "done"]))
      );
      addMessage(
        "assistant",
        `I generated ${normalizedResponse.block_name} with ${summarizeAnswers(answersOverride)}. It is ready to insert.`
      );
      saveBlockToPartLibrary(normalizedResponse, answersOverride, messagesRef.current);
      addToast("Saved to part library", [normalizedResponse.block_name, summarizeAnswers(answersOverride)]);
      await refreshPricing();
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
      setExportResult(response);
      setPricing(response.pricing_preview);
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
    const response = await api<PricingPreview>("/pricing-preview");
    setPricing(response);
  }

  function answerQuestion(question: MissingQuestion, option: Option) {
    if (question.id === "part_choice") {
      const nextAnswers = { ...answers, [question.id]: option.value };
      setAnswers(nextAnswers);
      setQuestions([]);
      setActiveQuestionIndex(0);
      if (option.value.startsWith(EXTRACT_CANDIDATE_PREFIX)) {
        void startExtractionFromChoice(option);
        return;
      }
      void submitMessage(undefined, `Use ${option.value} for this block`);
      return;
    }

    if (question.id === "recipe_review_confirmed" && option.value === "cancel") {
      addMessage("user", option.label);
      addMessage(
        "assistant",
        "I cancelled that draft recipe. Ask for a known supported recipe or choose another part to continue."
      );
      setDraftBlock(null);
      setQuestions([]);
      setAnswers({});
      setExtractionJob(null);
      setActiveQuestionIndex(0);
      return;
    }

    if (!draftBlock) return;

    const nextAnswers = { ...answers, [question.id]: option.value };
    setAnswers(nextAnswers);
    addMessage("user", option.label);

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
      ? syncBlockWithAnswer(sourceBlock, answerId, option.value)
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
          health={health}
          bridgeStatus={bridgeStatus}
          projectPath={projectPath}
          setProjectPath={setProjectPath}
          onLinkProject={linkProject}
          onRefreshBridge={() => refreshBridgeStatus(false)}
          busy={busy}
          pricing={pricing}
        />

        {viewMode === "workspace" ? (
          <ProgressBar
            active={progress}
            partCount={partLibrary.length}
            onHome={returnToHome}
            onOpenLibrary={() => setLibraryOpen(true)}
          />
        ) : null}

        <PartLibraryDrawer
          activeEntryId={activeLibraryEntryId}
          entries={partLibrary}
          open={libraryOpen}
          onClose={() => setLibraryOpen(false)}
          onNewChat={startNewChat}
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
            onPromptChange={setPrompt}
            onRestore={restorePartLibraryEntry}
            onSubmit={submitMessage}
          />
        ) : (
          <section
            key="workspace"
            className="workspace-shell grid flex-1 grid-cols-1 overflow-hidden border-t border-white/[0.06] lg:min-h-0 lg:grid-cols-[390px_minmax(560px,1fr)_330px] 2xl:grid-cols-[410px_minmax(680px,1fr)_360px]"
          >
            <ChatPane
              messages={messages}
              busy={chatBusy}
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
            />

            <SchematicWorkspace block={block} busy={busy} />

            <InspectorPanel
              block={currentBlock}
              exportResult={exportResult}
              importResult={importResult}
              nextStepChecks={nextStepChecks}
              setNextStepChecks={setNextStepChecks}
            />
          </section>
        )}
        <ToastStack busy={popupBusy} toasts={toasts} onToggle={toggleToast} />
      </div>
    </main>
  );
}

function HomePage({
  activeEntryId,
  busy,
  canPrompt,
  entries,
  exiting,
  prompt,
  onPromptChange,
  onRestore,
  onSubmit
}: {
  activeEntryId: string | null;
  busy: string | null;
  canPrompt: boolean;
  entries: PartLibraryEntry[];
  exiting: boolean;
  prompt: string;
  onPromptChange: (value: string) => void;
  onRestore: (entry: PartLibraryEntry) => void;
  onSubmit: (event?: FormEvent) => void;
}) {
  const [componentSearch, setComponentSearch] = useState("");
  const filteredEntries = useMemo(() => {
    const query = componentSearch.trim().toLowerCase();
    if (!query) return entries;
    return entries.filter((entry) => {
      const summaryValues = answerSummaryItems(entry.block)
        .map((item) => `${item.label} ${item.value}`)
        .join(" ");
      return [
        entry.title,
        entry.summary,
        entry.block.block_name,
        entry.block.main_component.value,
        summaryValues
      ]
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [componentSearch, entries]);
  const updateHomeDots = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
    const y = Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height));
    event.currentTarget.style.setProperty("--dot-cursor-x", `${x * 100}%`);
    event.currentTarget.style.setProperty("--dot-cursor-y", `${y * 100}%`);
    event.currentTarget.style.setProperty("--dot-pull-x", `${(x - 0.5) * 9}px`);
    event.currentTarget.style.setProperty("--dot-pull-y", `${(y - 0.5) * 9}px`);
    event.currentTarget.style.setProperty("--dot-brightness", "0.82");
  };
  const resetHomeDots = (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.style.setProperty("--dot-pull-x", "0px");
    event.currentTarget.style.setProperty("--dot-pull-y", "0px");
    event.currentTarget.style.setProperty("--dot-brightness", "0.62");
  };

  return (
    <section
      key="home"
      className="home-shell relative flex flex-1 overflow-hidden bg-[#0a0a0c] lg:min-h-0"
    >
      <aside
        className={`home-library-panel thin-scrollbar w-full max-w-[360px] overflow-y-auto border-r border-white/[0.06] ${
          exiting ? "home-library-exit" : ""
        }`}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-white/[0.06] bg-[#0d0d0f]/92 px-5 py-4 backdrop-blur-xl">
          <div>
            <h2 className="text-sm font-semibold text-slate-200">Past components</h2>
            <p className="mt-1 text-xs text-slate-600">Saved choices and generated parts</p>
          </div>
        </div>

        <div className="border-b border-white/[0.06] p-3">
          <label className="liquid-control flex items-center gap-2 rounded-lg px-3 py-2">
            <Search size={14} className="shrink-0 text-slate-500" />
            <input
              className="min-w-0 flex-1 bg-transparent text-sm text-slate-200 outline-none placeholder:text-slate-600"
              value={componentSearch}
              onChange={(event) => setComponentSearch(event.target.value)}
              placeholder="Search components"
              type="search"
            />
          </label>
        </div>

        <div className="space-y-2 p-3">
          {entries.length ? (
            filteredEntries.length ? (
              filteredEntries.map((entry) => {
                const active = entry.id === activeEntryId;
                return (
                  <button
                    key={entry.id}
                    className={`group w-full overflow-hidden rounded-xl border px-3 py-2.5 text-left transition duration-500 ${
                      active
                        ? "border-[#7d9cbd]/45 bg-[#7d9cbd]/14"
                        : "border-white/[0.06] bg-white/[0.025] hover:border-white/[0.12] hover:bg-white/[0.045]"
                    }`}
                    type="button"
                    onClick={() => onRestore(entry)}
                  >
                    <p className="truncate text-sm font-semibold text-slate-200">{entry.title}</p>
                    <div className="max-h-0 overflow-hidden opacity-0 transition-all duration-500 group-hover:mt-2 group-hover:max-h-36 group-hover:opacity-100 group-focus-visible:mt-2 group-focus-visible:max-h-36 group-focus-visible:opacity-100">
                      <p className="line-clamp-2 text-xs leading-5 text-slate-500">
                        {entry.summary}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {answerSummaryItems(entry.block).slice(0, 3).map((item) => (
                          <span
                            key={`${entry.id}-${item.id}`}
                            className="rounded-md bg-black/18 px-2 py-1 text-[11px] font-semibold text-slate-500"
                          >
                            {item.value}
                          </span>
                        ))}
                      </div>
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.025] px-4 py-5 text-sm leading-6 text-slate-500">
                No saved components match that search.
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
        <div className="w-full max-w-3xl text-center">
          <div className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-2xl bg-[#7d9cbd]/12 text-[#a8c4e0]">
            <TraceLabsLogo className="h-8 w-8" />
          </div>
          <h2 className="text-2xl font-semibold text-slate-100">What should Trace Labs add?</h2>
          <p className="mt-3 text-sm leading-6 text-slate-500">
            Ask for a supported circuit block, or open a saved component from the left.
          </p>

          <form className="mt-8" onSubmit={onSubmit}>
            <div className="liquid-control flex items-center gap-3 rounded-2xl px-3 py-3 text-left">
              <input
                className="min-w-0 flex-1 bg-transparent px-3 py-2 text-base text-slate-100 outline-none placeholder:text-slate-600"
                value={prompt}
                onChange={(event) => onPromptChange(event.target.value)}
                disabled={!canPrompt}
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
        </div>
      </div>
    </section>
  );
}

function ChatPane({
  messages,
  busy,
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
}: {
  messages: ChatMessage[];
  busy: string | null;
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
  }) {
  return (
    <aside className="flex min-h-[640px] flex-col overflow-hidden border-b border-white/[0.06] bg-[#0d0d0f] lg:min-h-0 lg:border-b-0 lg:border-r">
      <ChatView messages={messages} busy={busy} />
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
  busy
}: {
  block: CircuitBlock | null;
  busy: string | null;
}) {
  const generating = busy === "generate" || busy === "extract";

  return (
    <section className="flex min-h-[640px] flex-col overflow-hidden bg-[#0a0a0c] lg:min-h-0">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-4">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-slate-300">Schematic preview</h2>
          <span className="rounded-md border border-[#7d9cbd]/30 bg-[#7d9cbd]/15 px-2 py-0.5 text-xs font-semibold text-[#a8c4e0]">
            BETA
          </span>
        </div>
      </div>

      <div className="schematic-canvas-bg relative flex min-h-[520px] flex-1 items-center justify-center px-5 py-8">
        {block ? (
          <SchematicCanvas block={block} dimmed={generating} />
        ) : generating ? (
          <SchematicGeneratingPreview busy={busy} />
        ) : (
          <EmptySchematicPreview />
        )}
      </div>

      <DocumentationBox block={block} />
    </section>
  );
}

function SchematicGeneratingPreview({ busy }: { busy: string | null }) {
  const messages = loadingMessagesForBusy(busy === "extract" ? "extract" : "generate");
  const [messageIndex, setMessageIndex] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setMessageIndex((index) => (index + 1) % messages.length);
    }, 1300);
    return () => window.clearInterval(timer);
  }, [messages.length]);

  return (
    <div className="schematic-loading-preview animate-fade-slide w-full max-w-[620px] rounded-2xl px-8 py-8 text-center">
      <div className="mx-auto mb-5 grid h-16 w-16 place-items-center rounded-2xl bg-[#7d9cbd]/12">
        <MiniGradientLoader />
      </div>
      <div className="mx-auto mb-6 h-8 max-w-md overflow-hidden">
        <span key={`schematic-${messageIndex}`} className="loading-status-text">
          {messages[messageIndex]}
        </span>
      </div>
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
  dimmed = false
}: {
  block: CircuitBlock;
  dimmed?: boolean;
}) {
  if (block.extraction_status === "ready" && block.reference_extraction) {
    return <ExtractedSchematicCanvas block={block} dimmed={dimmed} />;
  }

  if (block.block_slug !== "bme280_i2c") {
    return <GenericDraftSchematicCanvas block={block} dimmed={dimmed} />;
  }

  const logicNet =
    block.selected_options.logic_voltage === "1.8V"
      ? "+1V8"
      : block.external_nets.find((net) => net.startsWith("+")) ?? "+3V3";
  const address = block.selected_options.i2c_address ?? "0x76";
  const sdoTarget = address === "0x76" ? "GND" : logicNet;
  const { sdaPullup, sclPullup, sdoStrap, csbStrap } = bmeResistors(block);
  const orderedResistors = [sdaPullup, sclPullup, sdoStrap, csbStrap].filter(
    (component): component is SupportComponent => Boolean(component)
  );
  const resistorRef = (component: SupportComponent) => `R${orderedResistors.indexOf(component) + 1}`;

  return (
    <div
      className={`schematic-card w-full max-w-[780px] animate-pop-in transition duration-500 ${
        dimmed ? "scale-[0.985] opacity-55" : "opacity-100"
      }`}
    >
      <svg
        viewBox="0 0 860 520"
        className="h-auto w-full"
        role="img"
        aria-label="BME280 schematic preview"
      >
        <rect x="0" y="0" width="860" height="520" rx="8" fill="transparent" />

        <g className="schematic-draw" strokeLinecap="round" strokeLinejoin="round">
          <path d="M86 78H770" stroke="#5f9277" strokeWidth="3" />
          <path d="M86 438H770" stroke="#9da3ae" strokeWidth="3" />
          <text x="68" y="68" fill="#5f9277" fontSize="16" fontWeight="700">
            {logicNet}
          </text>
          <text x="70" y="460" fill="#9da3ae" fontSize="16" fontWeight="700">
            GND
          </text>

          <path d="M164 78V142" stroke="#5f9277" strokeWidth="3" />
          <path d="M164 182V438" stroke="#9da3ae" strokeWidth="3" />
          <path d="M144 142H184M144 162H184" stroke="#9da3ae" strokeWidth="2.3" />
          <text x="190" y="151" fill="#cbd5e1" fontSize="13">
            C1
          </text>
          <text x="190" y="170" fill="#9da3ae" fontSize="12">
            100nF
          </text>

          <path d="M234 78V142" stroke="#5f9277" strokeWidth="3" />
          <path d="M234 182V438" stroke="#9da3ae" strokeWidth="3" />
          <path d="M214 142H254M214 162H254" stroke="#9da3ae" strokeWidth="2.3" />
          <text x="260" y="151" fill="#cbd5e1" fontSize="13">
            C2
          </text>
          <text x="260" y="170" fill="#9da3ae" fontSize="12">
            100nF
          </text>

          <rect x="374" y="158" width="188" height="220" rx="8" fill="#101216" stroke="#333a44" strokeWidth="2" />
          <text x="468" y="250" fill="#a8c4e0" fontSize="20" fontWeight="700" textAnchor="middle">
            U1
          </text>
          <text x="468" y="281" fill="#8290a6" fontSize="16" fontWeight="700" textAnchor="middle">
            BME280
          </text>

          <text x="388" y="190" fill="#7b8494" fontSize="12">
            VDD 8
          </text>
          <text x="388" y="218" fill="#7b8494" fontSize="12">
            VDDIO 6
          </text>
          <text x="388" y="257" fill="#7b8494" fontSize="12">
            SCK/SCL 4
          </text>
          <text x="388" y="300" fill="#7b8494" fontSize="12">
            SDI/SDA 3
          </text>
          <text x="524" y="322" fill="#7b8494" fontSize="12">
            5 SDO
          </text>
          <text x="524" y="350" fill="#7b8494" fontSize="12">
            2 CSB
          </text>
          <text x="526" y="190" fill="#7b8494" fontSize="12">
            1 GND
          </text>
          <text x="526" y="218" fill="#7b8494" fontSize="12">
            7 GND
          </text>

          <path d="M414 158V78" stroke="#5f9277" strokeWidth="3" />
          <path d="M444 158V78" stroke="#5f9277" strokeWidth="3" />
          <path d="M532 158V438" stroke="#9da3ae" strokeWidth="3" />
          <path d="M502 158V438" stroke="#9da3ae" strokeWidth="3" />

          <rect x="42" y="244" width="96" height="24" rx="4" fill="#101216" stroke="#6e8fb3" />
          <rect x="42" y="287" width="96" height="24" rx="4" fill="#101216" stroke="#6e8fb3" />
          <text x="90" y="261" textAnchor="middle" fill="#6e8fb3" fontSize="12" fontWeight="700">
            I2C1_SCL
          </text>
          <text x="90" y="304" textAnchor="middle" fill="#6e8fb3" fontSize="12" fontWeight="700">
            I2C1_SDA
          </text>
          <path d="M138 256H374" stroke="#6e8fb3" strokeWidth="3" />
          <path d="M138 299H374" stroke="#6e8fb3" strokeWidth="3" />

          {sdaPullup || sclPullup ? (
            <>
              {sdaPullup ? (
                <>
                  <path d="M300 78V168" stroke="#5f9277" strokeWidth="3" />
                  <rect x="288" y="168" width="24" height="58" rx="4" fill="#101216" stroke="#8290a6" strokeWidth="2" />
                  <path d="M300 226V299" stroke="#6e8fb3" strokeWidth="3" />
                  <text x="255" y="196" fill="#9da3ae" fontSize="13">
                    {resistorRef(sdaPullup)}
                  </text>
                  <text x="249" y="215" fill="#9da3ae" fontSize="12">
                    {compactPassiveValue(sdaPullup.value)}
                  </text>
                </>
              ) : null}
              {sclPullup ? (
                <>
                  <path d="M330 78V168" stroke="#5f9277" strokeWidth="3" />
                  <rect x="318" y="168" width="24" height="58" rx="4" fill="#101216" stroke="#8290a6" strokeWidth="2" />
                  <path d="M330 226V256" stroke="#6e8fb3" strokeWidth="3" />
                  <text x="346" y="196" fill="#9da3ae" fontSize="13">
                    {resistorRef(sclPullup)}
                  </text>
                  <text x="346" y="215" fill="#9da3ae" fontSize="12">
                    {compactPassiveValue(sclPullup.value)}
                  </text>
                </>
              ) : null}
            </>
          ) : null}

          {sdoStrap ? (
            <>
              <path d="M562 322H630" stroke="#8290a6" strokeWidth="3" />
              <rect x="630" y="310" width="58" height="24" rx="4" fill="#101216" stroke="#8290a6" strokeWidth="2" />
              <path
                d={sdoTarget === "GND" ? "M688 322H724V438" : "M688 322H724V78"}
                stroke={sdoTarget === "GND" ? "#9da3ae" : "#5f9277"}
                strokeWidth="3"
              />
              <text x="636" y="304" fill="#9da3ae" fontSize="13">
                {resistorRef(sdoStrap)} {compactPassiveValue(sdoStrap.value)}
              </text>
              <text x="728" y="328" fill={sdoTarget === "GND" ? "#9da3ae" : "#5f9277"} fontSize="12">
                SDO={address}
              </text>
            </>
          ) : (
            <>
              <path
                d={sdoTarget === "GND" ? "M562 322H724V438" : "M562 322H724V78"}
                stroke={sdoTarget === "GND" ? "#9da3ae" : "#5f9277"}
                strokeWidth="3"
              />
              <text x="728" y="328" fill={sdoTarget === "GND" ? "#9da3ae" : "#5f9277"} fontSize="12">
                SDO={address}
              </text>
            </>
          )}

          {csbStrap ? (
            <>
              <path d="M562 350H610V244" stroke="#8290a6" strokeWidth="3" />
              <rect x="598" y="212" width="58" height="24" rx="4" fill="#101216" stroke="#8290a6" strokeWidth="2" />
              <path d="M656 224H702V78" stroke="#5f9277" strokeWidth="3" />
              <text x="604" y="206" fill="#9da3ae" fontSize="13">
                {resistorRef(csbStrap)} {compactPassiveValue(csbStrap.value)}
              </text>
              <text x="706" y="229" fill="#5f9277" fontSize="12">
                CSB=I2C
              </text>
            </>
          ) : (
            <>
              <path d="M562 350H702V78" stroke="#5f9277" strokeWidth="3" />
              <text x="706" y="356" fill="#5f9277" fontSize="12">
                CSB=I2C
              </text>
            </>
          )}

          {[
            164,
            234,
            sdaPullup ? 300 : -1,
            sclPullup ? 330 : -1,
            414,
            444,
            702,
            sdoTarget !== "GND" ? 724 : -1
          ]
            .filter((x) => x > 0)
            .map((x) => (
              <circle key={`rail-${x}`} cx={x} cy="78" r="4.5" fill="#5f9277" />
            ))}
          {[164, 234, 502, 532, sdoTarget === "GND" ? 724 : -1]
            .filter((x) => x > 0)
            .map((x) => (
              <circle key={`gnd-${x}`} cx={x} cy="438" r="4.5" fill="#9da3ae" />
            ))}
          {sdaPullup ? <circle cx="300" cy="299" r="4.5" fill="#6e8fb3" /> : null}
          {sclPullup ? <circle cx="330" cy="256" r="4.5" fill="#6e8fb3" /> : null}
          <circle cx="374" cy="256" r="4.5" fill="#6e8fb3" />
          <circle cx="374" cy="299" r="4.5" fill="#6e8fb3" />
        </g>

        <g transform="translate(28 484)" fontSize="12" fontWeight="700">
          <LegendDot color="#5f9277" label="Power" x={0} />
          <LegendDot color="#6e8fb3" label="I2C" x={110} />
          <LegendDot color="#8290a6" label="Passive" x={205} />
          <LegendDot color="#9da3ae" label="GND" x={320} />
        </g>
      </svg>
    </div>
  );
}

function ExtractedSchematicCanvas({
  block,
  dimmed = false
}: {
  block: CircuitBlock;
  dimmed?: boolean;
}) {
  const extraction = block.reference_extraction;
  if (!extraction) {
    return <GenericDraftSchematicCanvas block={block} dimmed={dimmed} />;
  }

  const pins = extraction.pins.slice(0, 24);
  const leftPins = pins.filter((pin) => extractedPinSide(pin) === "left");
  const rightPins = pins.filter((pin) => extractedPinSide(pin) === "right");
  const supports = block.support_components.slice(0, 10);
  const maxPinRows = Math.max(leftPins.length, rightPins.length, 1);
  const bodyHeight = Math.max(176, maxPinRows * 24 + 48);
  const bodyTop = 92;
  const bodyBottom = bodyTop + bodyHeight;
  const bodyX = 320;
  const bodyWidth = 220;
  const pinY = (index: number, count: number) => {
    if (count <= 1) return bodyTop + bodyHeight / 2;
    const usable = bodyHeight - 52;
    return bodyTop + 26 + (usable * index) / (count - 1);
  };
  const supportTop = bodyBottom + 42;
  const svgHeight = Math.max(560, supportTop + Math.ceil(supports.length / 4) * 76 + 58);
  const packageLabel = extraction.package || "package TBD";
  const interfaceLabel = extraction.interface || "interface extracted";
  const sourceIds = extraction.source_chunks.slice(0, 4).map((chunk) => chunk.chunk_id);

  return (
    <div
      className={`schematic-card w-full max-w-[820px] animate-pop-in transition duration-500 ${
        dimmed ? "scale-[0.985] opacity-55" : "opacity-100"
      }`}
    >
      <svg
        viewBox={`0 0 860 ${svgHeight}`}
        className="h-auto w-full"
        role="img"
        aria-label={`${block.main_component.value} extracted schematic preview`}
      >
        <rect x="0" y="0" width="860" height={svgHeight} rx="8" fill="transparent" />
        <g strokeLinecap="round" strokeLinejoin="round">
          <rect x={bodyX} y={bodyTop} width={bodyWidth} height={bodyHeight} rx="8" fill="#101216" stroke="#333a44" strokeWidth="2" />
          <text x={bodyX + bodyWidth / 2} y={bodyTop + bodyHeight / 2 - 26} fill="#a8c4e0" fontSize="21" fontWeight="700" textAnchor="middle">
            {block.main_component.value}
          </text>
          <text x={bodyX + bodyWidth / 2} y={bodyTop + bodyHeight / 2 + 2} fill="#8290a6" fontSize="13" fontWeight="700" textAnchor="middle">
            {packageLabel}
          </text>
          <text x={bodyX + bodyWidth / 2} y={bodyTop + bodyHeight / 2 + 26} fill="#7b8494" fontSize="12" textAnchor="middle">
            {interfaceLabel}
          </text>

          {leftPins.map((pin, index) => {
            const y = pinY(index, leftPins.length);
            const color = extractedNetColor(pin.net_name);
            return (
              <g key={`left-${pin.number}-${pin.name}`}>
                <path d={`M${bodyX} ${y}H178`} stroke={color} strokeWidth="2.6" />
                <circle cx={bodyX} cy={y} r="4" fill={color} />
                <rect x="70" y={y - 15} width="108" height="30" rx="5" fill="#101216" stroke={color} />
                <text x="168" y={y - 3} textAnchor="end" fill="#cbd5e1" fontSize="11" fontWeight="700">
                  {pin.number} {truncateLabel(pin.name, 10)}
                </text>
                <text x="168" y={y + 11} textAnchor="end" fill={color} fontSize="10" fontWeight="700">
                  {truncateLabel(pin.net_name, 13)}
                </text>
              </g>
            );
          })}

          {rightPins.map((pin, index) => {
            const y = pinY(index, rightPins.length);
            const color = extractedNetColor(pin.net_name);
            return (
              <g key={`right-${pin.number}-${pin.name}`}>
                <path d={`M${bodyX + bodyWidth} ${y}H682`} stroke={color} strokeWidth="2.6" />
                <circle cx={bodyX + bodyWidth} cy={y} r="4" fill={color} />
                <rect x="682" y={y - 15} width="116" height="30" rx="5" fill="#101216" stroke={color} />
                <text x="692" y={y - 3} fill="#cbd5e1" fontSize="11" fontWeight="700">
                  {pin.number} {truncateLabel(pin.name, 10)}
                </text>
                <text x="692" y={y + 11} fill={color} fontSize="10" fontWeight="700">
                  {truncateLabel(pin.net_name, 13)}
                </text>
              </g>
            );
          })}

          {supports.map((component, index) => {
            const column = index % 4;
            const row = Math.floor(index / 4);
            const x = 104 + column * 176;
            const y = supportTop + row * 74;
            const color = component.type === "capacitor" ? "#5f9277" : "#8290a6";
            const citation = component.source_citations?.[0] ?? "cited";
            const topNet = component.connects[0] ?? "REVIEW_1";
            const bottomNet = component.connects[1] ?? "REVIEW_2";
            return (
              <g key={`${component.reference}-${component.purpose}-${index}`}>
                <path d={`M${x + 48} ${y - 17}V${y - 5}`} stroke={extractedNetColor(topNet)} strokeWidth="2.4" />
                <path d={`M${x + 48} ${y + 39}V${y + 53}`} stroke={extractedNetColor(bottomNet)} strokeWidth="2.4" />
                <rect x={x + 34} y={y - 5} width="28" height="44" rx="4" fill="#101216" stroke={color} strokeWidth="2" />
                <rect x={x} y={y - 33} width="126" height="18" rx="4" fill="#101216" stroke={extractedNetColor(topNet)} />
                <rect x={x} y={y + 51} width="126" height="18" rx="4" fill="#101216" stroke={extractedNetColor(bottomNet)} />
                <text x={x + 63} y={y - 20} textAnchor="middle" fill={extractedNetColor(topNet)} fontSize="10" fontWeight="700">
                  {truncateLabel(topNet, 16)}
                </text>
                <text x={x + 63} y={y + 64} textAnchor="middle" fill={extractedNetColor(bottomNet)} fontSize="10" fontWeight="700">
                  {truncateLabel(bottomNet, 16)}
                </text>
                <text x={x + 72} y={y + 13} fill="#cbd5e1" fontSize="12" fontWeight="700">
                  {component.reference.replace("?", `${index + 1}`)} {compactPassiveValue(component.value)}
                </text>
                <text x={x + 72} y={y + 29} fill="#7b8494" fontSize="10">
                  {truncateLabel(component.purpose, 18)} [{citation}]
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
      </svg>
    </div>
  );
}

function truncateLabel(value: string, maxLength: number) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
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

function extractedNetColor(netName: string) {
  const net = netName.toUpperCase();
  if (net === "GND") return "#9da3ae";
  if (net.startsWith("+") || net.includes("VDD") || net.includes("VCC")) return "#5f9277";
  if (["SDA", "SCL", "MISO", "MOSI", "SCK", "CS"].some((name) => net.includes(name))) return "#6e8fb3";
  return "#8290a6";
}

function GenericDraftSchematicCanvas({
  block,
  dimmed = false
}: {
  block: CircuitBlock;
  dimmed?: boolean;
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
      className={`schematic-card w-full max-w-[720px] animate-pop-in transition duration-500 ${
        dimmed ? "scale-[0.985] opacity-55" : "opacity-100"
      }`}
    >
      <svg viewBox="0 0 760 460" className="h-auto w-full" role="img" aria-label="Draft schematic preview">
        <rect x="0" y="0" width="760" height="460" rx="8" fill="transparent" />
        <g strokeLinecap="round" strokeLinejoin="round">
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
            <>
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
            </>
          ) : null}

          {resistors.map((resistor, index) => {
            const y = 118 + index * 62;
            const label = resistor.connects.find(
              (net) => net !== "GND" && !net.startsWith("+") && !net.toUpperCase().startsWith("VCC")
            ) ?? `REVIEW_${index + 1}`;
            return (
              <g key={`${resistor.purpose}-${index}`}>
                <path d={`M552 82V${y - 24}`} stroke="#5f9277" strokeWidth="3" />
                <rect x="540" y={y - 24} width="24" height="48" rx="4" fill="#101216" stroke="#8290a6" strokeWidth="2" />
                <path d={`M552 ${y + 24}H610`} stroke="#8290a6" strokeWidth="3" />
                <circle cx="552" cy="82" r="4.5" fill="#5f9277" />
                <rect x="610" y={y + 12} width="116" height="24" rx="4" fill="#101216" stroke="#8290a6" />
                <text x="668" y={y + 29} textAnchor="middle" fill="#a8c4e0" fontSize="12" fontWeight="700">
                  {label}
                </text>
                <text x="572" y={y - 6} fill="#cbd5e1" fontSize="13">
                  R{refBase + index + 1}
                </text>
                <text x="572" y={y + 14} fill={resistor.value === "TBD" ? "#fbbf24" : "#9da3ae"} fontSize="12">
                  {resistor.value}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
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

function ComponentTable({ block }: { block: CircuitBlock | null }) {
  const rows = componentTableRows(block);

  return (
    <InspectorSection title="Components">
      {block ? (
        <div className="overflow-hidden rounded-lg border border-white/[0.07]">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-white/[0.07] text-slate-600">
              <tr>
                <th className="px-3 py-2 font-semibold">Ref</th>
                <th className="px-3 py-2 font-semibold">Value</th>
                <th className="px-3 py-2 font-semibold">Package</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.06]">
              {rows.map((row, index) => (
                <tr
                  key={row.key}
                  className="animate-fade-slide text-slate-400"
                  style={{ animationDelay: `${index * 65}ms` }}
                >
                  <td className="px-3 py-2 font-semibold text-slate-200">
                    {row.reference}
                  </td>
                  <td className="px-3 py-2">
                    <span className="block">{row.component.value}</span>
                    {"supplier_part_number" in row.component && row.component.supplier_part_number ? (
                      <span className="mt-1 block text-[10px] uppercase tracking-[0.12em] text-amber-300/80">
                        {row.component.supplier || "Supplier"} {row.component.supplier_part_number}
                      </span>
                    ) : null}
                  </td>
                  <td className="max-w-32 px-3 py-2">
                    <span className="block truncate text-slate-500" title={row.component.footprint}>
                      {row.component.footprint}
                    </span>
                  </td>
                </tr>
              ))}
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
  block,
  exportResult,
  importResult,
  nextStepChecks,
  setNextStepChecks
}: {
  block: CircuitBlock | null;
  exportResult: ExportResponse | null;
  importResult: BridgeImportResponse | null;
  nextStepChecks: Record<string, boolean>;
  setNextStepChecks: (value: Record<string, boolean>) => void;
}) {
  return (
    <aside className="thin-scrollbar flex min-h-[640px] flex-col overflow-y-auto border-t border-white/[0.06] bg-[#0d0d0f] lg:min-h-0 lg:border-l lg:border-t-0">
      <div className="flex-1">
        <ComponentTable block={block} />

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

function DocumentationBox({ block }: { block: CircuitBlock | null }) {
  const source = block?.datasheet_sources[0];
  const hasUsableUrl = isHttpUrl(source?.url);

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
            {!hasUsableUrl ? (
              <p className="mt-2 text-xs leading-5 text-amber-200/80">
                No usable documentation URL was captured for this draft. Check `notes.md` and verify the datasheet manually.
              </p>
            ) : null}
          </>
        ) : (
          <p className="mt-2 text-sm text-slate-500">Recipe documentation appears after generation.</p>
        )}
      </div>
    </section>
  );
}

function ToastStack({
  busy,
  toasts,
  onToggle
}: {
  busy: string | null;
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
          >
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0 break-words">{toast.title}</span>
              {toast.details.length ? (
                <button
                  className="shrink-0 rounded-md px-2 py-1 text-xs font-semibold text-slate-500 transition hover:bg-white/[0.04] hover:text-slate-300"
                  type="button"
                  onClick={() => onToggle(toast.id)}
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
  onRestore
}: {
  activeEntryId: string | null;
  entries: PartLibraryEntry[];
  open: boolean;
  onClose: () => void;
  onNewChat: () => void;
  onRestore: (entry: PartLibraryEntry) => void;
}) {
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
            <p className="text-sm font-semibold text-slate-200">Past chats</p>
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
              aria-label="Close past chats"
              onClick={onClose}
            >
              <X size={17} />
            </button>
          </div>
        </div>

        <div className="thin-scrollbar flex-1 overflow-y-auto p-3">
          {entries.length ? (
            <div className="space-y-2">
              {entries.map((entry) => {
                const active = entry.id === activeEntryId;
                return (
                  <button
                    key={entry.id}
                    className={`w-full rounded-xl border px-4 py-3 text-left transition duration-500 ${
                      active
                        ? "border-[#7d9cbd]/45 bg-[#7d9cbd]/14"
                        : "border-white/[0.06] bg-white/[0.025] hover:border-white/[0.12] hover:bg-white/[0.045]"
                    }`}
                    type="button"
                    onClick={() => onRestore(entry)}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-200">
                          {entry.title}
                        </p>
                        <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                          {entry.summary}
                        </p>
                      </div>
                      <span className="shrink-0 text-[11px] font-medium text-slate-600">
                        {new Date(entry.updatedAt).toLocaleDateString(undefined, {
                          month: "short",
                          day: "numeric"
                        })}
                      </span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {answerSummaryItems(entry.block).map((item) => (
                        <span
                          key={`${entry.id}-${item.id}`}
                          className="rounded-md border border-white/[0.06] bg-black/16 px-2 py-1 text-[11px] font-semibold text-slate-500"
                        >
                          {item.label}: <span className="text-slate-300">{item.value}</span>
                        </span>
                      ))}
                    </div>
                  </button>
                );
              })}
            </div>
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
  const messages = loadingMessagesForBusy(busy);
  const [messageIndex, setMessageIndex] = useState(0);

  useEffect(() => {
    setMessageIndex(0);
    const timer = window.setInterval(() => {
      setMessageIndex((index) => (index + 1) % messages.length);
    }, 1300);
    return () => window.clearInterval(timer);
  }, [busy, messages.length]);

  return (
    <div className="animate-toast-in rounded-xl border border-white/[0.08] bg-[#141418]/95 px-4 py-3 shadow-[0_18px_60px_rgba(0,0,0,0.34)] backdrop-blur-xl">
      <div className="flex items-center gap-3">
        <MiniGradientLoader />
        <div className="loading-status-window">
          <span key={`${busy}-${messageIndex}`} className="loading-status-text">
            {messages[messageIndex]}
          </span>
        </div>
      </div>
    </div>
  );
}

function TraceLabsLogo({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 48 64"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M24 5v8M18 13h12M18 13v7M30 13v7"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="3.2"
      />
      <path
        d="M18 20v8.5L7.6 51.3C5.9 55 8.6 59 12.7 59H22V45.5l-6.6-7.9"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="3.2"
      />
      <path
        d="M30 20v8.5l10.4 22.8C42.1 55 39.4 59 35.3 59H26V45.5l6.6-7.9"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="3.2"
      />
      <path
        d="M24 33v13.5M16 59h16M19 51h10"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="3.2"
      />
      <circle cx="16" cy="37" r="2.4" fill="currentColor" />
      <circle cx="24" cy="33" r="2.4" fill="currentColor" />
      <circle cx="32" cy="37" r="2.4" fill="currentColor" />
      <circle cx="24" cy="46.5" r="2.4" fill="currentColor" />
    </svg>
  );
}

function Header({
  health,
  bridgeStatus,
  projectPath,
  setProjectPath,
  onLinkProject,
  onRefreshBridge,
  busy,
  pricing
}: {
  health: HealthResponse | null;
  bridgeStatus: BridgeStatus | null;
  projectPath: string;
  setProjectPath: (value: string) => void;
  onLinkProject: () => void;
  onRefreshBridge: () => void;
  busy: string | null;
  pricing: PricingPreview | null;
}) {
  const connected = Boolean(bridgeStatus?.connected);
  const projectName =
    bridgeStatus?.project_name ?? health?.project_name ?? "Environmental_Logger";

  return (
    <header className="grid min-h-16 grid-cols-1 items-center gap-3 border-b border-white/[0.07] bg-[#0d0d0f] px-4 py-3 lg:grid-cols-[390px_1fr_520px] lg:px-6 2xl:grid-cols-[410px_1fr_580px]">
      <div className="flex min-w-0 items-center gap-4">
        <h1
          data-testid="app-title"
          className="flex min-w-0 items-center gap-2 text-lg font-semibold text-slate-100"
        >
          <TraceLabsLogo className="h-6 w-6 shrink-0 text-[#7d9cbd]" />
          <span className="truncate">
            Trace <span className="text-[#7d9cbd]">Labs</span>
          </span>
        </h1>
        <div className="min-w-0 rounded-xl border border-white/[0.07] bg-white/[0.035] px-4 py-2 text-sm font-medium text-slate-300">
          <span className="block truncate">{projectName}</span>
        </div>
      </div>

      <div />

      <div className="flex min-w-0 items-center gap-3 lg:justify-end">
        <UsageRing pricing={pricing} />
        <div className="flex min-w-0 items-center gap-2 rounded-xl border border-white/[0.07] bg-white/[0.03] px-3 py-2">
          <div className="flex min-w-28 items-center gap-2">
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                connected ? "animate-status-pulse bg-emerald-400" : "bg-amber-400"
              }`}
            />
            <div className="leading-tight">
              <p
                className={
                  connected
                    ? "text-xs font-semibold text-emerald-300"
                    : "text-xs font-semibold text-amber-200"
                }
              >
                {connected ? "Connected" : "No project"}
              </p>
              <p className="max-w-28 truncate text-[11px] text-slate-600">
                {bridgeStatus?.project_name ?? "KiCad"}
              </p>
            </div>
          </div>
          <input
            className="min-w-0 flex-1 rounded-lg border border-white/[0.07] bg-black/20 px-3 py-2 text-xs text-slate-200 outline-none ring-[#7d9cbd]/30 placeholder:text-slate-500 focus:ring-2 lg:w-36 2xl:w-52"
            value={projectPath}
            onChange={(event) => setProjectPath(event.target.value)}
            aria-label="KiCad project folder"
            placeholder="Project folder"
          />
          <button
            className="liquid-control inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold text-slate-200 disabled:opacity-60"
            onClick={onLinkProject}
            disabled={busy === "link"}
            type="button"
          >
            {busy === "link" ? <MiniGradientLoader /> : <Link size={14} />}
            {connected ? "Change" : "Link"}
          </button>
          <button
            className="liquid-control rounded-lg p-2 text-slate-300 disabled:opacity-60"
            type="button"
            aria-label="Refresh KiCad bridge status"
            onClick={onRefreshBridge}
            disabled={busy === "link"}
          >
            {busy === "link" ? <MiniGradientLoader /> : <RefreshCw size={15} />}
          </button>
        </div>
      </div>
    </header>
  );
}

function UsageRing({ pricing }: { pricing: PricingPreview | null }) {
  const used = pricing?.used_blocks ?? 0;
  const included = pricing?.included_blocks ?? 50;
  const percent = included > 0 ? Math.min(100, Math.round((used / included) * 100)) : 0;
  const ringStyle = {
    background: `conic-gradient(#7d9cbd ${percent * 3.6}deg, rgba(255,255,255,0.09) 0deg)`
  };

  return (
    <div className="group relative hidden shrink-0 items-center gap-2 rounded-xl px-2 py-1.5 md:flex">
      <div
        className="grid h-9 w-9 place-items-center rounded-full transition duration-700 group-hover:scale-105"
        style={ringStyle}
        aria-label={`Usage ${percent}%`}
      >
        <span className="h-6 w-6 rounded-full bg-[#0d0d0f]" />
      </div>
      <div className="leading-none">
        <p className="text-sm font-semibold text-slate-200">{percent}%</p>
        <p className="mt-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-600">
          Usage
        </p>
      </div>

      <div className="pointer-events-none absolute right-0 top-[calc(100%+0.7rem)] z-40 w-64 translate-y-1 rounded-xl border border-white/[0.08] bg-[#141418]/96 p-4 text-xs opacity-0 shadow-[0_18px_60px_rgba(0,0,0,0.34)] backdrop-blur-xl transition duration-500 group-hover:translate-y-0 group-hover:opacity-100">
        {pricing ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-500">Plan</span>
              <span className="font-semibold text-slate-200">{pricing.plan_name}</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-500">Blocks used</span>
              <span className="font-semibold text-slate-200">
                {pricing.used_blocks} / {pricing.included_blocks}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-500">Remaining</span>
              <span className="font-semibold text-slate-200">{pricing.remaining_blocks}</span>
            </div>
            <div className="h-px bg-white/[0.07]" />
            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-500">Bill impact</span>
              <span className="font-semibold text-emerald-300">
                {formatCurrency(pricing.estimated_overage)}
              </span>
            </div>
          </div>
        ) : (
          <p className="leading-5 text-slate-500">Usage details are loading.</p>
        )}
      </div>
    </div>
  );
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
      <div className="grid items-center gap-4 lg:grid-cols-[220px_minmax(420px,760px)_220px]">
        <div className="flex justify-start">
          <button
            className="liquid-control inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold text-slate-300"
            type="button"
            onClick={onOpenLibrary}
          >
            <History size={15} />
            Past chats
            <span className="rounded-md bg-white/[0.08] px-1.5 py-0.5 text-[11px] text-slate-500">
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
            className="liquid-control inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold text-slate-300"
            type="button"
            onClick={onHome}
          >
            <Home size={15} />
            Home
          </button>
        </div>
      </div>
    </div>
  );
}

function ChatView({ messages, busy }: { messages: ChatMessage[]; busy: string | null }) {
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
        <ChatBubble key={message.id} message={message} />
      ))}
      {busy ? <LoadingStatusBubble busy={busy} /> : null}
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
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
        {isUser ? message.text : <AssistantMessageContent text={message.text} />}
      </div>
    </div>
  );
}

function AssistantMessageContent({ text }: { text: string }) {
  const lines = text
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

function LoadingStatusBubble({ busy }: { busy: string }) {
  const messages = loadingMessagesForBusy(busy);
  const [messageIndex, setMessageIndex] = useState(0);

  useEffect(() => {
    setMessageIndex(0);
    const timer = window.setInterval(() => {
      setMessageIndex((index) => (index + 1) % messages.length);
    }, 1300);
    return () => window.clearInterval(timer);
  }, [busy, messages.length]);

  return (
    <div className="animate-fade-slide flex justify-start">
      <div className="rounded-lg border border-white/[0.08] bg-white/[0.04] px-4 py-3">
        <div className="loading-status-window">
          <span key={`${busy}-${messageIndex}`} className="loading-status-text">
            {messages[messageIndex]}
          </span>
        </div>
      </div>
    </div>
  );
}

function loadingMessagesForBusy(busy: string) {
  if (busy === "chat") {
    return [
      "Reading your request",
      "Matching available parts",
      "Checking required choices",
      "Preparing the chat response"
    ];
  }

  if (busy === "generate") {
    return [
      "Applying your electrical choices",
      "Building the CircuitBlock",
      "Checking support components",
      "Preparing the schematic preview"
    ];
  }

  if (busy === "extract") {
    return [
      "Downloading datasheet and reference sources",
      "Reading pin tables and application circuits",
      "Extracting cited passives and nets",
      "Checking CAD asset requirements",
      "Validating evidence before drafting"
    ];
  }

  if (busy === "export") {
    return ["Adding component"];
  }

  if (busy === "insert") {
    return ["Inserting component"];
  }

  if (busy === "link") {
    return ["Linking project"];
  }

  return ["Working"];
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
  if (!question) return null;

  const selected = answers[question.id];

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
      </div>
      <p className="text-xs leading-5 text-slate-600">
        Pick an answer to continue.
      </p>
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
    <form onSubmit={onSubmit} className="border-t border-white/[0.08] p-5">
      <div className="flex gap-2">
        <input
          className="liquid-control min-w-0 flex-1 rounded-xl px-4 py-3 text-sm text-slate-100 outline-none ring-[#7d9cbd]/30 placeholder:text-slate-600 focus:ring-2"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={!canPrompt || Boolean(busy)}
          placeholder={canPrompt ? "Ask Trace Labs anything..." : "Connect a KiCad project to start"}
        />
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
