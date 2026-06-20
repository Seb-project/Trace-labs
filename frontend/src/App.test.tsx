import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

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

describe("App", () => {
  beforeEach(() => {
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
});
