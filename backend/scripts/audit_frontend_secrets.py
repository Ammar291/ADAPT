"""Check browser source and build output without printing credential values.

Run from the repository root with the backend Python and this script's path.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")


def main() -> int:
    configured = os.environ.get("OPENAI_API_KEY") or dotenv_values(ROOT / ".env").get(
        "OPENAI_API_KEY"
    )
    roots = [ROOT / "frontend" / name for name in ("src", "public", "dist")]
    failures = []
    checked = 0
    for directory in roots:
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            contents = path.read_bytes()
            checked += 1
            text = contents.decode("utf-8", errors="ignore")
            if (configured and configured.encode() in contents) or KEY.search(text):
                failures.append(str(path.relative_to(ROOT)))
    if failures:
        print("Server credential found in browser artifacts: " + ", ".join(failures))
        return 1
    print(f"PASS: {checked} browser files scanned; no primary OpenAI key exposed.")
    if not configured:
        print("No configured primary key was available; pattern scan only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
