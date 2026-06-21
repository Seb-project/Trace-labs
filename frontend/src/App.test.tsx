import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App, {
  ComponentExtractionJob,
  documentationSourceForState,
  extractionLoadingSteps,
  extractionTimeoutMessage
} from "./App";

const pricingPreview = {
  plan_name: "Maker",
  monthly_price: 12,
  included_blocks: 50,
  used_blocks: 0,
  remaining_blocks: 50,
  overage_rate: 0.2,
  estimated_overage: 0,
  estimated_monthly_bill: 12,
  recent_events: [],
  message: "No bill impact yet."
};

const accountOverview = {
  account: {
    account_id: "local-dev",
    display_name: "Local developer",
    email: "",
    status: "local",
    created_at: "2026-06-20T00:00:00Z",
    solvimon_customer_reference: "",
    solvimon_subscription_reference: ""
  },
  pricing_preview: pricingPreview,
  billing: {
    provider: "solvimon",
    mode: "disabled",
    configured: false,
    customer_reference: "",
    subscription_reference: "",
    meter_references: {},
    last_sync_status: "not_configured",
    last_synced_at: null,
    last_error: null,
    setup_required: ["Set SOLVIMON_API_KEY on the backend."]
  }
};

const savedCircuitBlock = {
  id: "saved-block-1",
  block_name: "Saved Sensor",
  block_slug: "saved_sensor",
  summary: "Saved sensor block",
  main_component: {
    reference: "U?",
    type: "sensor",
    value: "SAVED123",
    mpn: "SAVED123",
    manufacturer: "Trace Labs",
    symbol: "Device:U",
    footprint: "Package_SO:SOIC-8",
    footprint_asset: {
      name: "SOIC-8_Test",
      footprint_id: "Package_SO:SOIC-8",
      source_kind: "supplier_footprint",
      source_project: "fixture",
      source_path: "SOIC-8_Test.kicad_mod",
      source_url: "https://example.com/SOIC-8_Test.kicad_mod",
      confidence: "downloaded_needs_review",
      warnings: [],
      kicad_mod: `(footprint "SOIC-8_Test"
  (version 20240108)
  (generator "Trace Labs")
  (fp_line (start -2.5 -3) (end 2.5 -3) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (fp_line (start -2.5 3) (end 2.5 3) (stroke (width 0.12) (type solid)) (layer "F.SilkS"))
  (fp_rect (start -2.2 -2.7) (end 2.2 2.7) (stroke (width 0.1) (type solid)) (layer "F.Fab"))
  (pad "1" smd rect (at -3.05 -1.905) (size 0.6 1.55) (layers "F.Cu" "F.Paste" "F.Mask") (net 1 "+3V3"))
  (pad "2" smd rect (at -3.05 -0.635) (size 0.6 1.55) (layers "F.Cu" "F.Paste" "F.Mask") (net 2 "GND"))
  (pad "3" smd rect (at -3.05 0.635) (size 0.6 1.55) (layers "F.Cu" "F.Paste" "F.Mask") (net 3 "I2C1_SDA"))
  (pad "4" smd rect (at -3.05 1.905) (size 0.6 1.55) (layers "F.Cu" "F.Paste" "F.Mask") (net 4 "I2C1_SCL"))
  (pad "5" smd rect (at 3.05 1.905 180) (size 0.6 1.55) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "6" smd rect (at 3.05 0.635 180) (size 0.6 1.55) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "7" smd rect (at 3.05 -0.635 180) (size 0.6 1.55) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "8" smd rect (at 3.05 -1.905 180) (size 0.6 1.55) (layers "F.Cu" "F.Paste" "F.Mask"))
)`
    },
    purpose: "saved test sensor",
    connects: ["+3V3", "GND", "I2C1_SDA", "I2C1_SCL"],
    footprint_confidence: "needs_review",
    symbol_confidence: "default_selected",
    assignment_reason: "Fixture part for saved checklist state.",
    status: "ready"
  },
  support_components: [
    {
      reference: "C?",
      type: "capacitor",
      value: "100 nF",
      purpose: "local decoupling capacitor",
      symbol: "Device:C",
      footprint: "Capacitor_SMD:C_0603_1608Metric",
      footprint_confidence: "default_selected",
      symbol_confidence: "default_selected",
      connects: ["+3V3", "GND"],
      assignment_reason: "Fixture support component for table editing.",
      status: "ready"
    }
  ],
  external_nets: ["+3V3", "GND", "I2C1_SDA", "I2C1_SCL"],
  internal_nets: [],
  assumptions: ["Review the saved block before export."],
  missing_questions: [],
  validation_warnings: [],
  next_steps: [
    {
      id: "verify_package",
      category: "review",
      task: "Verify package",
      required: true,
      status: "todo",
      reason: "User review required."
    }
  ],
  datasheet_sources: [],
  schematic_preview: {
    title: "Saved Sensor",
    description: "Saved sensor preview",
    ascii_preview: "SAVED123",
    connections: ["+3V3", "GND", "I2C1_SDA", "I2C1_SCL"],
    notes: []
  },
  usage_events: [],
  selected_options: {
    logic_voltage: "3.3V",
    interface_mode: "I2C",
    i2c_address: "0x76",
    pullups: "skip"
  },
  status: "final",
  recipe_source: "local_verified",
  recipe_status: "verified",
  recipe_review_confirmed: true,
  extraction_status: "not_required",
  reference_extraction: null
};

function savedPartLibraryEntry(nextStepChecks: Record<string, boolean> = {}) {
  return {
    id: "saved-entry-1",
    blockId: savedCircuitBlock.id,
    title: savedCircuitBlock.block_name,
    summary: "3.3V logic, I2C, address 0x76, and existing bus pull-ups",
    createdAt: "2026-06-20T12:00:00Z",
    updatedAt: "2026-06-20T12:00:00Z",
    block: savedCircuitBlock,
    answers: savedCircuitBlock.selected_options,
    messages: [],
    nextStepChecks
  };
}

async function openPastComponents() {
  fireEvent.click(await screen.findByRole("button", { name: "Open past components" }));
}

describe("App", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        let payload;
        if (url.includes("/health")) {
          payload = {
            status: "ok",
            app_name: "Trace Labs",
            project_name: "weather_station.kicad_pro",
            kicad_bridge_status: "mocked"
          };
        } else if (url.includes("/account")) {
          payload = accountOverview;
        } else if (url.includes("/bridge/status")) {
          payload = {
            connected: false,
            kicad_bridge_status: "mocked",
            next_steps: ["Link a KiCad project folder before inserting a block."]
          };
        } else {
          payload = pricingPreview;
        }
        return {
          ok: true,
          json: async () => payload
        } as Response;
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the Trace Labs shell", async () => {
    render(<App />);

    expect(await screen.findByTestId("app-title")).toHaveTextContent("Trace Labs");
    expect(screen.getByText("What should Trace Labs add?")).toBeInTheDocument();
  });

  it("dismisses the project setup info when the homepage is clicked", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: /Show KiCad setup steps/i }));
    expect(screen.getByText("KiCad setup")).toBeInTheDocument();

    fireEvent.click(screen.getByText("What should Trace Labs add?"));

    await waitFor(() => {
      expect(screen.queryByText("KiCad setup")).not.toBeInTheDocument();
    });
  });

  it("dismisses toast notifications when clicked but keeps Show more interactive", async () => {
    window.localStorage.setItem(
      "tracelabs.partLibrary.v3",
      JSON.stringify([savedPartLibraryEntry()])
    );

    render(<App />);
    await openPastComponents();
    fireEvent.click(await screen.findByRole("button", { name: "Open Saved Sensor" }));

    const toastTitle = await screen.findByText("Loaded from part library");
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));

    expect(screen.getByRole("button", { name: "Hide" })).toBeInTheDocument();
    expect(toastTitle).toBeInTheDocument();

    fireEvent.click(toastTitle);

    await waitFor(() => {
      expect(screen.queryByText("Loaded from part library")).not.toBeInTheDocument();
    });
  });

  it("keeps checked next steps saved after reopening a part", async () => {
    window.localStorage.setItem(
      "tracelabs.partLibrary.v3",
      JSON.stringify([savedPartLibraryEntry()])
    );

    const firstRender = render(<App />);
    await openPastComponents();
    fireEvent.click(await screen.findByRole("button", { name: "Open Saved Sensor" }));

    const checkbox = await screen.findByLabelText("Verify package");
    fireEvent.click(checkbox);

    await waitFor(() => {
      const savedEntries = JSON.parse(window.localStorage.getItem("tracelabs.partLibrary.v3") ?? "[]");
      expect(savedEntries[0].nextStepChecks.verify_package).toBe(true);
    });

    firstRender.unmount();
    render(<App />);
    await openPastComponents();
    fireEvent.click(await screen.findByRole("button", { name: "Open Saved Sensor" }));

    expect(await screen.findByLabelText("Verify package")).toBeChecked();
  });

  it("keeps past component filters behind a dropdown", async () => {
    window.localStorage.setItem(
      "tracelabs.partLibrary.v3",
      JSON.stringify([savedPartLibraryEntry()])
    );

    render(<App />);
    await openPastComponents();

    expect(screen.queryByRole("menuitemradio", { name: "SPI" })).not.toBeInTheDocument();

    fireEvent.click(
      await screen.findByRole("button", { name: "Filter saved components: All" })
    );

    const filterMenu = await screen.findByRole("menu", { name: "Filter saved components" });
    fireEvent.click(within(filterMenu).getByRole("menuitemradio", { name: "SPI" }));

    await waitFor(() => {
      expect(screen.queryByRole("menu", { name: "Filter saved components" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Filter saved components: SPI" })).toBeInTheDocument();
    expect(screen.getByText("No saved components match that search or filter.")).toBeInTheDocument();
  });

  it("deletes a saved component only after confirmation", async () => {
    window.localStorage.setItem(
      "tracelabs.partLibrary.v3",
      JSON.stringify([savedPartLibraryEntry()])
    );

    render(<App />);
    await openPastComponents();

    fireEvent.click(
      await screen.findByRole("button", { name: "Delete Saved Sensor from past components" })
    );

    const cancelDialog = await screen.findByRole("dialog", {
      name: "Delete saved component?"
    });
    expect(within(cancelDialog).getByText("Saved Sensor")).toBeInTheDocument();

    fireEvent.click(within(cancelDialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Delete saved component?" })
      ).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Open Saved Sensor" })).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Delete Saved Sensor from past components" })
    );
    const confirmDialog = await screen.findByRole("dialog", {
      name: "Delete saved component?"
    });
    fireEvent.click(within(confirmDialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(JSON.parse(window.localStorage.getItem("tracelabs.partLibrary.v3") ?? "[]")).toEqual(
        []
      );
    });
    expect(screen.getByText("Finished components will appear here so you can reuse them later.")).toBeInTheDocument();
  });

  it("swaps the schematic area to a footprint preview for the component of interest", async () => {
    window.localStorage.setItem(
      "tracelabs.partLibrary.v3",
      JSON.stringify([savedPartLibraryEntry()])
    );

    render(<App />);
    await openPastComponents();
    fireEvent.click(await screen.findByRole("button", { name: "Open Saved Sensor" }));

    expect(await screen.findByRole("heading", { name: "Schematic preview" })).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "Show footprint preview" }));

    expect(await screen.findByRole("heading", { name: "Footprint preview" })).toBeInTheDocument();
    const footprintView = screen.getByRole("img", { name: "SAVED123 footprint preview" });
    expect(footprintView).toBeInTheDocument();
    expect(within(footprintView).getByText("Package_SO:SOIC-8")).toBeInTheDocument();
    expect(within(footprintView).getByText(/Downloaded supplier KiCad footprint/)).toBeInTheDocument();
    expect(within(footprintView).getByText(/Real KiCad footprint geometry/)).toBeInTheDocument();
    expect(within(footprintView).getByLabelText(/Pad 1 - \+3V3/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show schematic preview" }));

    expect(await screen.findByRole("heading", { name: "Schematic preview" })).toBeInTheDocument();
  });

  it("shows diode support components with diode references", async () => {
    const diodeBlock = {
      ...savedCircuitBlock,
      id: "saved-diode-block",
      block_name: "Saved Clamp",
      block_slug: "saved_clamp",
      support_components: [
        ...savedCircuitBlock.support_components,
        {
          reference: "D?",
          type: "diode",
          value: "1N4148W",
          purpose: "SDA clamp diode",
          symbol: "Device:D",
          footprint: "Diode_SMD:D_SOD-123",
          footprint_confidence: "default_selected",
          symbol_confidence: "default_selected",
          connects: ["I2C1_SDA", "GND"],
          assignment_reason: "Fixture diode support component.",
          status: "ready"
        }
      ]
    };
    const entry = {
      ...savedPartLibraryEntry(),
      id: "saved-diode-entry",
      blockId: diodeBlock.id,
      title: diodeBlock.block_name,
      block: diodeBlock
    };
    window.localStorage.setItem("tracelabs.partLibrary.v3", JSON.stringify([entry]));

    render(<App />);
    await openPastComponents();
    fireEvent.click(await screen.findByRole("button", { name: "Open Saved Clamp" }));

    expect(await screen.findByText(/^D\d+$/)).toBeInTheDocument();
    expect(screen.getAllByText("1N4148W").length).toBeGreaterThan(0);
    expect(screen.getByText("Diode_SMD:D_SOD-123")).toBeInTheDocument();
  });

  it("collects converter requirements before resuming part search", async () => {
    const chatBodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        let payload;
        if (url.includes("/health")) {
          payload = {
            status: "ok",
            app_name: "Trace Labs",
            project_name: "weather_station.kicad_pro",
            kicad_bridge_status: "linked"
          };
        } else if (url.includes("/account")) {
          payload = accountOverview;
        } else if (url.includes("/bridge/status")) {
          payload = {
            connected: true,
            project_path: "demo_kicad_project",
            project_name: "weather_station.kicad_pro",
            schematic_path: "weather_station.kicad_sch",
            kicad_bridge_status: "linked",
            next_steps: []
          };
        } else if (url.includes("/chat")) {
          chatBodies.push(JSON.parse(String(init?.body ?? "{}")));
          payload =
            chatBodies.length === 1
              ? {
                  assistant_message:
                    "Before I recommend converter parts or start datasheet extraction, I need the operating requirements.",
                  draft_block: null,
                  missing_questions: [
                    {
                      id: "calc_input_voltage_v",
                      question: "What input voltage should the converter accept (V)?",
                      type: "number",
                      options: [],
                      required: true,
                      default: "",
                      depends_on: {}
                    },
                    {
                      id: "calc_output_voltage_v",
                      question: "What output voltage should it generate (V)?",
                      type: "number",
                      options: [],
                      required: true,
                      default: "",
                      depends_on: {}
                    },
                    {
                      id: "calc_output_current_a",
                      question: "What maximum output current should it supply (A)?",
                      type: "number",
                      options: [],
                      required: true,
                      default: "",
                      depends_on: {}
                    }
                  ],
                  warnings: [],
                  next_steps: [],
                  datasheet_results: null,
                  extraction_job: null
                }
              : {
                  assistant_message: "Searching with the supplied converter requirements.",
                  draft_block: null,
                  missing_questions: [],
                  warnings: [],
                  next_steps: [],
                  datasheet_results: {
                    query: "buck converter with requirements",
                    live_search_used: false,
                    provider: "test",
                    summary: "Search resumed.",
                    target_part_number: "",
                    context_part_numbers: [],
                    search_audit: [],
                    candidates: [],
                    warnings: [],
                    token_count: 0
                  },
                  extraction_job: null
                };
        } else {
          payload = pricingPreview;
        }
        return {
          ok: true,
          json: async () => payload
        } as Response;
      })
    );

    render(<App />);
    const promptInput = await screen.findByPlaceholderText("Ask Trace Labs to add a component...");
    fireEvent.change(promptInput, { target: { value: "I want to add a buck converter" } });
    fireEvent.submit(promptInput.closest("form") as HTMLFormElement);

    expect(
      await screen.findByText("What input voltage should the converter accept (V)?", {}, { timeout: 3000 })
    ).toBeInTheDocument();
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("What input voltage should the converter accept (V)?")).toBeInTheDocument();
    expect(await screen.findByText("What output voltage should it generate (V)?")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("What maximum output current should it supply (A)?")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => {
      expect(chatBodies).toHaveLength(2);
    });
    expect(chatBodies[1].answers).toEqual({
      calc_input_voltage_v: "12",
      calc_output_voltage_v: "5",
      calc_output_current_a: "2"
    });
    expect(String(chatBodies[1].message)).toContain("Input voltage: 12 V");
    expect(String(chatBodies[1].message)).toContain("Output voltage: 5 V");
    expect(String(chatBodies[1].message)).toContain("Maximum output current: 2 A");
    expect(chatBodies[1].history).toEqual(
      expect.arrayContaining([
        { role: "assistant", content: "What input voltage should the converter accept (V)?" },
        { role: "user", content: "12" },
        { role: "assistant", content: "What output voltage should it generate (V)?" },
        { role: "user", content: "5" },
        { role: "assistant", content: "What maximum output current should it supply (A)?" },
        { role: "user", content: "2" }
      ])
    );
  });

  it("collects vague category context before resuming recommendations", async () => {
    const chatBodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        let payload;
        if (url.includes("/health")) {
          payload = {
            status: "ok",
            app_name: "Trace Labs",
            project_name: "weather_station.kicad_pro",
            kicad_bridge_status: "linked"
          };
        } else if (url.includes("/account")) {
          payload = accountOverview;
        } else if (url.includes("/bridge/status")) {
          payload = {
            connected: true,
            project_path: "demo_kicad_project",
            project_name: "weather_station.kicad_pro",
            schematic_path: "weather_station.kicad_sch",
            kicad_bridge_status: "linked",
            next_steps: []
          };
        } else if (url.includes("/chat")) {
          chatBodies.push(JSON.parse(String(init?.body ?? "{}")));
          payload =
            chatBodies.length === 1
              ? {
                  assistant_message:
                    "Before I recommend parts, I need a little more context so the options fit the design.",
                  draft_block: null,
                  missing_questions: [
                    {
                      id: "clarify_application",
                      question:
                        "What should this part do in the project? For example: weather station, wearable motion, battery monitor, or motor control.",
                      type: "text",
                      options: [],
                      required: true,
                      default: "General-purpose prototype",
                      depends_on: {}
                    },
                    {
                      id: "clarify_interface_preference",
                      question: "Which interface should recommendations prefer?",
                      type: "select",
                      options: [
                        { label: "Let Trace Labs choose", value: "Let Trace Labs choose a common interface" },
                        { label: "I2C", value: "I2C" },
                        { label: "SPI", value: "SPI" }
                      ],
                      required: true,
                      default: "Let Trace Labs choose a common interface",
                      depends_on: {}
                    },
                    {
                      id: "clarify_supply_voltage_v",
                      question: "What supply or logic voltage should it support?",
                      type: "select",
                      options: [
                        { label: "3.3V", value: "3.3V" },
                        { label: "5V", value: "5V" },
                        { label: "Not sure", value: "not sure" }
                      ],
                      required: true,
                      default: "3.3V",
                      depends_on: {}
                    }
                  ],
                  warnings: [],
                  next_steps: [],
                  datasheet_results: null,
                  extraction_job: null
                }
              : {
                  assistant_message: "Searching with the supplied recommendation context.",
                  draft_block: null,
                  missing_questions: [],
                  warnings: [],
                  next_steps: [],
                  datasheet_results: {
                    query: "temperature sensor with recommendation context",
                    live_search_used: false,
                    provider: "test",
                    summary: "Search resumed.",
                    target_part_number: "",
                    context_part_numbers: [],
                    search_audit: [],
                    candidates: [],
                    warnings: [],
                    token_count: 0
                  },
                  extraction_job: null
                };
        } else {
          payload = pricingPreview;
        }
        return {
          ok: true,
          json: async () => payload
        } as Response;
      })
    );

    render(<App />);
    const promptInput = await screen.findByPlaceholderText("Ask Trace Labs to add a component...");
    fireEvent.change(promptInput, { target: { value: "I need a temperature sensor" } });
    fireEvent.submit(promptInput.closest("form") as HTMLFormElement);

    expect(
      await screen.findByText(/What should this part do in the project\?/, {}, { timeout: 3000 })
    ).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("General-purpose prototype"), {
      target: { value: "weather station" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByText("weather station")).toBeInTheDocument();
    expect(await screen.findByText("Which interface should recommendations prefer?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "I2C" }));

    expect(screen.getByText("I2C")).toBeInTheDocument();
    expect(screen.getByText("Which interface should recommendations prefer?")).toBeInTheDocument();
    expect(await screen.findByText("What supply or logic voltage should it support?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "3.3V" }));

    await waitFor(() => {
      expect(chatBodies).toHaveLength(2);
    });
    expect(chatBodies[1].answers).toEqual({
      clarify_application: "weather station",
      clarify_interface_preference: "I2C",
      clarify_supply_voltage_v: "3.3V"
    });
    expect(String(chatBodies[1].message)).toContain("Application or use case: weather station");
    expect(String(chatBodies[1].message)).toContain("Interface preference: I2C");
    expect(String(chatBodies[1].message)).toContain("Supply or logic voltage: 3.3V");
    expect(chatBodies[1].history).toEqual(
      expect.arrayContaining([
        {
          role: "assistant",
          content:
            "What should this part do in the project? For example: weather station, wearable motion, battery monitor, or motor control."
        },
        { role: "user", content: "weather station" },
        { role: "assistant", content: "Which interface should recommendations prefer?" },
        { role: "user", content: "I2C" },
        { role: "assistant", content: "What supply or logic voltage should it support?" },
        { role: "user", content: "3.3V" }
      ])
    );
  });

  it("opens the small editor from Edit and the full table from row click", async () => {
    window.localStorage.setItem(
      "tracelabs.partLibrary.v3",
      JSON.stringify([savedPartLibraryEntry()])
    );

    render(<App />);
    await openPastComponents();
    fireEvent.click(await screen.findByRole("button", { name: "Open Saved Sensor" }));

    const table = await screen.findByRole("table");
    const initialRowCount = within(table).getAllByRole("row").length;
    const valueCell = within(table).getByText("100 nF").closest("td");
    const componentRow = valueCell?.closest("tr");
    expect(valueCell).not.toBeNull();
    expect(componentRow).not.toBeNull();

    fireEvent.click(within(valueCell as HTMLElement).getByRole("button", { name: "Edit" }));

    const editDialog = await screen.findByRole("dialog");
    const valueInput = await screen.findByDisplayValue("100 nF");
    expect(editDialog).toHaveClass("component-edit-dialog");
    expect(editDialog.parentElement).toHaveClass("component-edit-backdrop");
    expect(within(editDialog).queryByRole("table")).not.toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(initialRowCount);
    expect(within(table).queryByDisplayValue("100 nF")).not.toBeInTheDocument();

    fireEvent.pointerDown(valueInput);
    expect(screen.getByDisplayValue("100 nF")).toBeInTheDocument();

    fireEvent.pointerDown(document.body);

    await waitFor(() => {
      expect(screen.queryByDisplayValue("100 nF")).not.toBeInTheDocument();
    });

    fireEvent.click(componentRow as HTMLElement);

    const tableDialog = await screen.findByRole("dialog");
    const expandedTable = within(tableDialog).getByRole("table");
    expect(tableDialog).toHaveClass("component-table-dialog");
    expect(tableDialog.parentElement).toHaveClass("component-table-backdrop");
    expect(within(tableDialog).getByText("SAVED123")).toBeInTheDocument();
    expect(await screen.findByDisplayValue("100 nF")).toBeInTheDocument();
    expect(within(expandedTable).getAllByRole("row")).toHaveLength(initialRowCount);
    expect(within(table).getAllByRole("row")).toHaveLength(initialRowCount);
  });

  it("explains that datasheet content was found during extraction", () => {
    const job: ComponentExtractionJob = {
      job_id: "job-source-found",
      status: "sources_found",
      progress: 0.32,
      message:
        "Found readable datasheet/reference text for Bosch Sensortec BME688 from 1 source. Extracting pins and support circuit next.",
      candidate: {
        part_number: "BME688",
        manufacturer: "Bosch Sensortec",
        description: "Environmental sensor",
        supplier: "",
        supplier_part_number: "",
        supplier_url: "",
        supported_recipe_id: "",
        confidence: "high",
        complexity: "moderate",
        source_coverage: ["datasheet"],
        capability_notes: [],
        datasheet_sources: [
          {
            title: "BME688 datasheet",
            source_type: "manufacturer_datasheet",
            url: "https://example.com/bme688.pdf",
            confidence: "high",
            notes: "Fixture datasheet source."
          }
        ],
        extraction_notes: [],
        warnings: []
      },
      extraction: null,
      draft_block: null,
      errors: []
    };

    const stepTexts = extractionLoadingSteps(job).map((step) => step.text);
    expect(stepTexts[0]).toContain("Found readable datasheet/reference text");
    expect(stepTexts).toContain("Found readable datasheet content for Bosch Sensortec BME688");
    expect(stepTexts).toContain("Documentation is available while extraction continues");
    expect(documentationSourceForState(null, job)?.title).toBe("BME688 datasheet");
    expect(extractionTimeoutMessage({ ...job, status: "extracting" })).toContain(
      "already found readable datasheet content"
    );
    expect(extractionTimeoutMessage({ ...job, status: "extracting" })).toContain(
      "worth waiting"
    );
  });

  it("distinguishes source fetching from datasheet extraction", () => {
    const job: ComponentExtractionJob = {
      job_id: "job-fetching",
      status: "fetching_sources",
      progress: 0.15,
      message:
        "Opening selected datasheet and reference URLs for Texas Instruments TPS54302DDCR. Trace Labs is still looking for readable source text.",
      candidate: {
        part_number: "TPS54302DDCR",
        manufacturer: "Texas Instruments",
        description: "3A synchronous buck converter",
        supplier: "",
        supplier_part_number: "",
        supplier_url: "",
        supported_recipe_id: "",
        confidence: "high",
        complexity: "moderate",
        source_coverage: ["datasheet"],
        capability_notes: [],
        datasheet_sources: [
          {
            title: "TPS54302 datasheet",
            source_type: "manufacturer_datasheet",
            url: "https://example.com/tps54302.pdf",
            confidence: "high",
            notes: "Fixture datasheet source."
          }
        ],
        extraction_notes: [],
        warnings: []
      },
      extraction: null,
      draft_block: null,
      errors: []
    };

    const stepTexts = extractionLoadingSteps(job).map((step) => step.text);
    expect(stepTexts).toContain("Opening TPS54302 datasheet for Texas Instruments TPS54302DDCR");
    expect(stepTexts).toContain("Still looking for readable datasheet or reference text");
    expect(stepTexts).toContain("No pins or support parts have been extracted yet");
    expect(documentationSourceForState(null, job)?.url).toBe("https://example.com/tps54302.pdf");
  });
});
