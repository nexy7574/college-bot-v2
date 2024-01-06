import toml
import logging
from pathlib import Path

try:
    CONFIG = toml.load('config.toml')
    CONFIG.setdefault("logging", {})
    CONFIG.setdefault("jimmy", {})
    CONFIG.setdefault("ollama", {})
except FileNotFoundError:
    cwd = Path.cwd()
    logging.getLogger("jimmy.autoconf").critical("Unable to locate config.toml in %s.", cwd, exc_info=True)
    raise
