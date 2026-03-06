#!/usr/bin/env python3
"""Export FastAPI OpenAPI spec to schema/openapi.json.

Run from repo root: python scripts/export_openapi.py
Or via:            make schema
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add backend/ to sys.path so `import app` resolves without an install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.main import app  # noqa: E402 — must come after sys.path mutation

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "openapi.json"


def main() -> None:
    SCHEMA_PATH.parent.mkdir(exist_ok=True)
    schema = app.openapi()
    SCHEMA_PATH.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Schema written → {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
