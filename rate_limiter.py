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

    def __init__(self, operations_per_second: float, enabled: bool = True):
        """
        Initialize the rate limiter.

        Args:
            operations_per_second: Maximum number of operations allowed per second
            enabled: Whether rate limiting is enabled
        """
        self.min_interval = 1.0 / operations_per_second
        self.last_operation_time = 0
        self.enabled = enabled

        if not self.enabled:
            logger.info("Rate limiting is disabled")

    def wait(self) -> None:
        """
        Wait if necessary to respect the rate limit.

        This method ensures that at least min_interval seconds have passed
        since the last operation before allowing a new operation.
        """
        # Skip if rate limiting is disabled
        if not self.enabled:
            return

        current_time = time.time()
        time_since_last = current_time - self.last_operation_time

        if time_since_last < self.min_interval:
            sleep_time = self.min_interval - time_since_last
            logger.debug(f"Rate limiting: sleeping for {sleep_time:.4f}s")
            time.sleep(sleep_time)

        self.last_operation_time = time.time()

    def set_enabled(self, enabled: bool) -> None:
        """
        Enable or disable rate limiting.

        Args:
            enabled: Whether to enable rate limiting
        """
        self.enabled = enabled
        if not self.enabled:
            logger.info("Rate limiting disabled")
        else:
            logger.info("Rate limiting enabled")
            self.last_operation_time = time.time()
