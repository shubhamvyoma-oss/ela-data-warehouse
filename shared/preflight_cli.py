from __future__ import annotations

import json

from shared.preflight import run_preflight


def main() -> int:
    report = run_preflight()
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
