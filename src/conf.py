import toml
import logging
from pathlib import Path

try:
    CONFIG = toml.load('config.toml')
    CONFIG.setdefault("logging", {})
    CONFIG.setdefault("jimmy", {})
    CONFIG.setdefault("ollama", {})
    CONFIG.setdefault(
        "server",
        {
            "host": "0.0.0.0",
            "port": 8080,
            "channel": 1032974266527907901
        }
    )
except FileNotFoundError:
    cwd = Path.cwd()
    logging.getLogger("jimmy.autoconf").critical("Unable to locate config.toml in %s.", cwd, exc_info=True)
    raise
