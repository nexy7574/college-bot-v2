import toml
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("jimmy.autoconf")

if (Path.cwd() / ".git").exists():
    try:
        log.debug("Attempting to auto-detect running version using git.")
        VERSION = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True
        ).stdout.strip()
    except subprocess.CalledProcessError:
        log.debug("Unable to auto-detect running version using git.", exc_info=True)
        VERSION = "unknown"
else:
    log.debug("Unable to auto-detect running version using git, no .git directory exists.")
    VERSION = "unknown"

try:
    CONFIG = toml.load('config.toml')
    CONFIG.setdefault("logging", {})
    CONFIG.setdefault("jimmy", {})
    CONFIG.setdefault("ollama", {})
    CONFIG.setdefault("rss", {"meta": {"channel": None}})
    CONFIG.setdefault("screenshot", {})
    CONFIG.setdefault("quote_a", {"channel": None})
    CONFIG.setdefault(
        "server",
        {
            "host": "0.0.0.0",
            "port": 8080,
            "channel": 1032974266527907901
        }
    )
    CONFIG.setdefault(
        "redis",
        {
            "host": "redis",
            "port": 6379,
            "decode_responses": True
        }
    )
except FileNotFoundError:
    cwd = Path.cwd()
    log.critical("Unable to locate config.toml in %s.", cwd, exc_info=True)
    raise
