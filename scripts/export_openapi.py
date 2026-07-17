#!/usr/bin/env python3
"""Export OpenAPI schema to docs/openapi.json for offline MCP / client generation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wlanpi_core.app import create_app  # noqa: E402


def main() -> int:
    app = create_app(debug=False)
    schema = app.openapi()
    out = ROOT / "docs" / "openapi.json"
    out.write_text(json.dumps(schema, indent=2) + "\n")
    paths = len(schema.get("paths", {}))
    print(f"Wrote {out} ({paths} path entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
