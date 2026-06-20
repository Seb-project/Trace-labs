# PCBStream Codeplain Specs

This folder contains the new PCBStream specification pack. It is spec-only:
do not render it until you are ready for Codeplain to generate the MVP.

## Files

- `00_product_overview.plain`: product name, scope, safety rules, and MVP non-goals.
- `01_architecture.plain`: intended monorepo structure, local API contract, and mock project context.
- `02_backend.plain`: renderable FastAPI backend spec.
- `03_frontend_ui.plain`: renderable Electron + React frontend spec.
- `04_circuit_block_schema.plain`: shared CircuitBlock and pricing schema contract.
- `05_component_recipes.plain`: BME280 I2C local recipe requirements and optional SHT31 note.
- `06_passive_defaults.plain`: passive symbol, footprint, and confidence defaults.
- `07_kicad_export.plain`: deterministic export writer and mocked KiCad insertion contract.
- `08_mock_solvimon_pricing.plain`: mock Solvimon-style usage and pricing rules.
- `09_future_ai_datasheet_services.plain`: placeholder-only future AI and datasheet services.
- `10_acceptance_criteria.plain`: full MVP acceptance criteria and test expectations.
- `11_kicad_bridge_addon.plain`: renderable lightweight KiCad bridge and mock linking spec.

## Render Order

The renderable top-level specs are:

1. `02_backend.plain`
2. `03_frontend_ui.plain`
3. `11_kicad_bridge_addon.plain`

The other `.plain` files are shared import specs. Do not render them directly
unless you intentionally want Codeplain to treat a shared spec as its own
generated module.

For the first full MVP render, run backend first, then frontend, then bridge.
This keeps the API and export shape stable before the bridge is generated.

Example dry-runs:

```bash
cd specs
codeplain 02_backend.plain --dry-run --config-name ../config.backend.yaml
codeplain 03_frontend_ui.plain --dry-run --config-name ../config.frontend.yaml
codeplain 11_kicad_bridge_addon.plain --dry-run --config-name ../config.kicad_bridge.yaml
```

Example full renders:

```bash
cd specs
codeplain 02_backend.plain --config-name ../config.backend.yaml
codeplain 03_frontend_ui.plain --config-name ../config.frontend.yaml
codeplain 11_kicad_bridge_addon.plain --config-name ../config.kicad_bridge.yaml
```

If your Codeplain setup uses different config names or output folders, replace
the config flags with your local equivalents.

## Can Renders Run In Parallel?

For the first render, prefer one after the other. Codeplain commonly writes to
shared folders such as `plain_modules`, `conformance_tests`, and log files, so
parallel renders can collide unless each render has isolated output folders.

After the first clean render, backend and frontend changes can be rendered more
selectively. Parallel rendering is reasonable only when the modules are
independent and you pass separate build folders, conformance folders, and log
file names for each process.

## Working Notes

- Commit before a render so generated changes are easy to inspect.
- Commit again after a good render and test pass.
- Keep edits in `.plain` specs, not in generated files.
- The MVP intentionally avoids real AI calls, internet datasheet search, real
  billing, and live KiCad project editing.
