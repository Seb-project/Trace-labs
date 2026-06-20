# PCBStream

PCBStream is an AI-assisted KiCad helper MVP. It generates a reviewable BME280
I2C schematic block from local verified recipe data, exports deterministic files,
and inserts the block into a linked KiCad project either as a hierarchical sheet
or directly into the root schematic.

The app is intentionally split into three parts:

- `backend/` - FastAPI backend, Pydantic schemas, recipe loader, deterministic KiCad writer and bridge endpoints.
- `frontend/` - Electron, React, TypeScript, Tailwind chat-first desktop app.
- `bridge/` - KiCad bridge CLI and ActionPlugin wrapper.
- `specs/` - retained Codeplain spec reference only. The app is now implemented manually.

## Run The Backend

Optional OpenAI setup:

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set:

```bash
OPENAI_API_KEY=sk-your-openai-api-key-here
OPENAI_MODEL=gpt-5.5
DATASHEET_LIVE_SEARCH_ENABLED=true
PCBSTREAM_LCSC_LOOKUP_ENABLED=true
```

You need a normal OpenAI Platform API key from the API dashboard. The key is
read only by the local backend. It is used for chat intent, suggestions,
follow-up answers and live datasheet search. Deterministic backend code still
generates CircuitBlock data and KiCad files. If no key is present, PCBStream
uses a local fallback.

Supplier footprint lookup is enabled by default. When a draft part has an LCSC
ID such as `C2040`, PCBStream uses `easyeda2kicad` to download/convert the
LCSC/EasyEDA footprint into the project-local `pcbstream_libs/` folder. The
downloaded footprint is marked `supplier_downloaded_needs_review`. Supplier
symbol import is off by default because unknown symbols need pin-map-aware
wiring before they are safe to insert automatically.

```bash
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8765 --reload
```

Health check:

```bash
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/ai/status
curl -X POST http://127.0.0.1:8765/datasheet/search \
  -H "Content-Type: application/json" \
  -d '{"query":"temperature sensor"}'
```

## Run The Frontend

```bash
cd frontend
npm start
```

The frontend expects the backend at `http://127.0.0.1:8765`.

## Test The KiCad Bridge

From the repo root, with the backend running:

```bash
python -m bridge.pcbstream_bridge.cli link demo_kicad_project
python -m bridge.pcbstream_bridge.cli import-block generated_blocks/bme280_i2c
python -m bridge.pcbstream_bridge.cli import-block generated_blocks/bme280_i2c --mode inline_main
```

To install the KiCad add-on, copy `bridge/pcbstream_bridge` and
`bridge/pcbstream_kicad_plugin.py` into KiCad's scripting plugins folder, then
restart KiCad. The plugin is named `PCBStream Bridge`.

The exported `notes.md` file is only the human-readable report. The schematic
file is `bme280_i2c.kicad_sch`; the bridge copies that file into the KiCad
project. The frontend asks whether to insert it as a linked subsheet or merge it
directly into the main schematic. If the schematic was already open in KiCad,
reload or reopen it after insertion.

The BME280 symbol and footprint are installed into the linked project under
`pcbstream_libs/` as `PCBStream_BME280`. The bridge updates project-local
`sym-lib-table` and `fp-lib-table`, so the generated schematic links to
PCBStream-provided project libraries rather than relying on KiCad's global
stock BME280 symbol/footprint.

## Tests

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m pytest bridge/tests -q
cd frontend && npm test
cd frontend && npm run build
```

## Current Scope

- Supports BME280 over I2C.
- Uses local recipe data for supported generation.
- OpenAI can assist chat intent, part suggestions, follow-up explanations and live datasheet search when `OPENAI_API_KEY` is set.
- Live datasheet search returns reviewable sources/candidates. Verified local recipes generate full deterministic KiCad output; AI-proposed draft recipes can export a deterministic review schematic with placeholders and `needs_review` labels.
- AI-proposed drafts can carry supplier metadata such as `supplier: LCSC` and `supplier_part_number: C2040`. If present, export tries LCSC/EasyEDA footprint conversion before falling back to official KiCad libraries or PCBStream placeholders.
- Unsupported/live-search candidates can become AI-proposed draft recipes after an extra user confirmation step.
- Confirmed draft recipes are saved under `backend/recipes/drafts/` with `recipe_status: needs_review`.
- If a support resistor value depends on current, load, bus capacitance, output level, timing or another external condition, PCBStream asks for the relevant choice. Selecting "Not sure" places the component with value `TBD` instead of guessing.
- AI never writes KiCad files directly.
- Main IC symbols/footprints are always generated or imported with review labels.
- Passive parts use KiCad `Device:*` symbols and generic 0603 footprints.

## AI Search Behavior And Limits

- PCBStream separates the requested target part from context parts such as MCUs,
  processors, dev boards and host controllers. For example, in "add MPU6050 for
  an ESP32 project", MPU6050 is the target and ESP32 is context.
- Broad requests such as "temperature sensor" ask the user to choose a specific
  part before generation. Exact unsupported part requests can create an
  AI-proposed draft, but only after the review-confirmation question remains in
  the flow.
- Live datasheet search is expected to look for the official datasheet plus
  linked or separately published application notes, reference designs,
  evaluation-board pages, design files and layout guidance. If it cannot verify
  those deeper sources, the response is marked incomplete.
- Complex parts such as PMICs, switching regulators, chargers, RF parts,
  high-speed interfaces, MCUs and processors are review skeletons only until the
  manufacturer reference design, pins, passives, layout guidance and operating
  conditions are checked.
