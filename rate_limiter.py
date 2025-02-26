# rate_limiter.py
"""
Rate limiter implementation to protect database from excessive load.
"""

import time
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Implements a simple rate limiter to control database access frequency.
    """

    def __init__(self, operations_per_second: float):
        """
        Initialize the rate limiter.

        Args:
            operations_per_second: Maximum number of operations allowed per second
        """
        self.min_interval = 1.0 / operations_per_second
        self.last_operation_time = 0

    def wait(self):
        """
        Wait if necessary to respect the rate limit.

        This method ensures that at least min_interval seconds have passed
        since the last operation before allowing a new operation.
        """
        current_time = time.time()
        time_since_last = current_time - self.last_operation_time

        if time_since_last < self.min_interval:
            sleep_time = self.min_interval - time_since_last
            logger.debug(f"Rate limiting: sleeping for {sleep_time:.4f}s")
            time.sleep(sleep_time)

        self.last_operation_time = time.time()
