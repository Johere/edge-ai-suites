"""Entry point for videostream-analytics microservice."""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from .shared.config import load_config
from .service import create_app


def main():
    parser = argparse.ArgumentParser(description="videostream-analytics microservice")
    parser.add_argument(
        "--config", "-c", default=None, help="Path to config.yaml"
    )
    parser.add_argument("--host", default=None, help="Override listen host")
    parser.add_argument("--port", type=int, default=None, help="Override listen port")
    args = parser.parse_args()

    config = load_config(args.config)

    # Setup logging
    log_level = config.logging.get("level", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    host = args.host or config.server.host
    port = args.port or config.server.port

    app = create_app(config)
    uvicorn.run(app, host=host, port=port, log_level=log_level.lower())


if __name__ == "__main__":
    main()
