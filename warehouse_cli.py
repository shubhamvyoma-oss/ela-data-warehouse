from __future__ import annotations

import argparse
import json
from pathlib import Path

from api_scripts.runner import collector_registry, run_collector
from database.migrate import apply_migrations
from manual_imports.import_file import import_file
from shared.config import DatabaseSettings, WarehouseSettings
from shared.database import Database
from shared.logging import configure_logging
from shared.preflight import run_preflight


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ELA Data Warehouse operator CLI")
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser("preflight", help="validate storage, database, and schemas")
    preflight.add_argument("--require-api", action="store_true")

    commands.add_parser("migrate", help="apply ordered database migrations")

    collect = commands.add_parser("collect", help="run one dedicated API collector")
    collect.add_argument("collector", choices=sorted(collector_registry()))
    collect.add_argument("--run-type", default="manual", choices=("manual", "scheduled", "replay"))

    manual_import = commands.add_parser("import-file", help="load an approved file into Bronze")
    manual_import.add_argument("--source", required=True)
    manual_import.add_argument("--file", required=True, type=Path)
    manual_import.add_argument("--sheet")
    manual_import.add_argument("--required-column", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    warehouse = WarehouseSettings.from_environment()
    configure_logging(warehouse.log_level)

    if args.command == "preflight":
        report = run_preflight(require_api=args.require_api)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "pass" else 1

    if args.command == "migrate":
        applied = apply_migrations(DatabaseSettings.from_environment())
        print(json.dumps({"status": "ok", "applied": applied}))
        return 0

    if args.command == "collect":
        return run_collector(args.collector, args.run_type)

    if args.command == "import-file":
        database = Database(DatabaseSettings.from_environment(), "ela-manual-import")
        try:
            import_id = import_file(
                database,
                source_name=args.source,
                path=args.file,
                required_columns=tuple(args.required_column),
                sheet_name=args.sheet,
            )
            print(json.dumps({"status": "ok", "import_id": str(import_id)}))
            return 0
        finally:
            database.close()

    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
