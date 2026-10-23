"""Small retry helper for transient database outages."""
import time
from typing import Callable, TypeVar

from app.errors import DatabaseUnavailable
from config.logging_config import get_logger

log = get_logger(__name__)
T = TypeVar("T")


def run_with_retry(fn: Callable[[], T], attempts: int = 3, delay: float = 0.3) -> T:
    """Retry ONLY DatabaseUnavailable (connection problems). Other errors surface at once."""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except DatabaseUnavailable:
            if i == attempts:
                raise
            log.warning("db_retry", attempt=i)
            time.sleep(delay * i)
    raise AssertionError("unreachable")
