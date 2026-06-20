from __future__ import annotations

import argparse
import json
from pathlib import Path

from .client import BridgeClient
from .core import detect_project_context


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pcbstream-bridge", description="PCBStream KiCad bridge CLI")
    parser.add_argument("--backend", default=None, help="Backend URL, default http://127.0.0.1:8765")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect_parser = subparsers.add_parser("detect", help="Detect KiCad project context")
    detect_parser.add_argument("project_path", type=Path)

    link_parser = subparsers.add_parser("link", help="Link a KiCad project to PCBStream")
    link_parser.add_argument("project_path", type=Path)
    link_parser.add_argument("--kicad-version", default=None)

    subparsers.add_parser("status", help="Show linked project status")

    import_parser = subparsers.add_parser("import-block", help="Import an exported PCBStream block")
    import_parser.add_argument("generated_block_dir", type=Path)
    import_parser.add_argument("--link-id", default=None)
    import_parser.add_argument(
        "--mode",
        choices=["hierarchical_sheet", "inline_main"],
        default="hierarchical_sheet",
        help="KiCad import mode. Use inline_main to edit the root schematic directly.",
    )

    args = parser.parse_args(argv)
    client = BridgeClient(args.backend)

    if args.command == "detect":
        print_json(detect_project_context(args.project_path).to_backend_payload())
        return 0

    if args.command == "link":
        print_json(client.link_project(args.project_path, args.kicad_version))
        return 0

    if args.command == "status":
        print_json(client.status())
        return 0

    if args.command == "import-block":
        print_json(client.import_block(args.generated_block_dir, args.link_id, args.mode))
        return 0

    parser.error("Unknown command")
    return 2


def print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
