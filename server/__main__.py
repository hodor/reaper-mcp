"""Entry point: python -m server"""

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)

from server.app import mcp

mcp.run()
