from __future__ import annotations

import sys
import urllib.error
import urllib.request


def main() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:5100/live", timeout=3) as response:
            return 0 if response.status == 200 else 1
    except urllib.error.URLError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
