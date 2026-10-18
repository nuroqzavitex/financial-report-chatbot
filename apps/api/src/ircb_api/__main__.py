"""`python -m ircb_api`: serve the API on API_HOST / API_PORT from Settings."""

from __future__ import annotations

import uvicorn
from ircb.settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run("ircb_api.main:app", host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
