"""Dump the OpenAPI schema without starting the app: `python -m ircb_api.openapi <out.json>`."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ircb_api.main import create_app


def main(argv: list[str]) -> None:
    if len(argv) != 1:
        raise SystemExit("usage: python -m ircb_api.openapi <out.json>")
    spec = create_app(state=None).openapi()
    out = Path(argv[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    out.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main(sys.argv[1:])
