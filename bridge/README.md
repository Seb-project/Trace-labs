# Trace Labs KiCad Bridge

This bridge is intentionally lightweight. It does not call AI services and it does
not generate KiCad files itself. It links a KiCad project folder to the local
Trace Labs backend, then asks the backend to insert an exported block as a
hierarchical sheet or directly into the root schematic.

## CLI Smoke Test

From the repo root, with the backend running on port `8765`:

```bash
python -m bridge.tracelabs_bridge.cli detect demo_kicad_project
python -m bridge.tracelabs_bridge.cli link demo_kicad_project
python -m bridge.tracelabs_bridge.cli status
python -m bridge.tracelabs_bridge.cli import-block generated_blocks/bme280_i2c
python -m bridge.tracelabs_bridge.cli import-block generated_blocks/bme280_i2c --mode inline_main
```

## KiCad Add-On Install

Copy the `bridge/tracelabs_bridge` package and `bridge/tracelabs_kicad_plugin.py`
into KiCad's scripting plugins folder, then restart KiCad.

The plugin appears as `Trace Labs Bridge`. When run from KiCad it links the
current project to `http://127.0.0.1:8765`. The frontend's Insert action can then
import the latest exported block.

The exported `notes.md` file is only a review report. The file that gets inserted
into KiCad is `bme280_i2c.kicad_sch`. The backend copies that schematic into
`<project>/tracelabs_blocks/bme280_i2c/`. In the default mode it patches the root
schematic with a hierarchical sheet reference. In `inline_main` mode it merges the
generated symbols, labels, wires and placed components directly into the root
schematic after creating a backup.

The bridge also installs BME280 project libraries under
`<project>/tracelabs_libs/` and updates `sym-lib-table` / `fp-lib-table` with a
`TraceLabs_BME280` library entry. The generated BME280 symbol and footprint are
therefore project-local Trace Labs assets sourced from cached KiCad library data,
not references to KiCad's global stock libraries.

If the schematic is already open in KiCad, reload or reopen it after insertion.
This MVP edits the KiCad files on disk; it does not drive KiCad's live schematic
editor UI.

If you set `TRACELABS_GENERATED_BLOCK_DIR` to an exported block directory before
launching KiCad, the plugin also attempts to import that block immediately. Set
`TRACELABS_IMPORT_MODE=inline_main` to use direct root-schematic insertion for
that path; otherwise it defaults to the hierarchical sheet mode.
