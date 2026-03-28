import logging
import os

# Allow runtime override via LOG_LEVEL env var (default: INFO).
# Accepted values: DEBUG, INFO, WARNING, ERROR, CRITICAL (case-insensitive).
_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
_level = getattr(logging, _level_name, logging.INFO)

# Configure logging to use a 24-hour clock format
logging.basicConfig(
    level=_level,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)