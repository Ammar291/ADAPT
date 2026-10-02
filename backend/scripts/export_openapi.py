"""Write the OpenAPI document used to generate `packages/contracts` TypeScript types.

    uv run python scripts/export_openapi.py [output-path]

Builds the app without connecting to any service (no database, Redis or OpenAI needed).
Adapters are forced to demo mode so the output never depends on local credentials.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT.parent / "packages" / "contracts" / "openapi.json"


def main() -> None:
    sys.path.insert(0, str(ROOT))
    for capability in ("LLM", "EMBEDDINGS", "OCR", "VOICE", "WEB_SEARCH"):
        os.environ[f"ADAPTER_{capability}"] = "demo"
    os.environ["ADAPT_ENV"] = "development"

    from app.core.config import Settings
    from app.main import create_app

    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(app.openapi(), indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {output.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
