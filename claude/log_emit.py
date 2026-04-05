import logging
import threading
import requests
from runenv import LOG_SERVER_URL, LOG_API_TOKEN

logger = logging.getLogger(__name__)

VERIFY = "/app/certs/ca.crt"


def _emit_log_event(event: dict) -> None:
    """Fire-and-forget: POST event to log-server /ingest in a background thread."""
    if not LOG_SERVER_URL:
        return

    def _post():
        try:
            requests.post(
                f"{LOG_SERVER_URL}/ingest",
                json=event,
                headers={"Authorization": f"Bearer {LOG_API_TOKEN}"},
                verify=VERIFY,
                timeout=5,
            )
        except Exception as e:
            logger.debug("log_emit failed: %s", e)

    t = threading.Thread(target=_post, daemon=True)
    t.start()
