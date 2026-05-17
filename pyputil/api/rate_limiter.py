#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import threading
import time
from typing import Dict, List


class RateLimiter:
    """
    Rate limiter for API calls.

    Implements token bucket algorithm for rate limiting API access.

    Parameters
    ----------
    calls_per_second : int, default=10
        Maximum number of calls allowed per second

    Attributes
    ----------
    calls_per_second : int
        Calls per second limit
    lock : threading.RLock
        Thread lock for thread safety
    calls : Dict[str, List[float]]
        Call history per API endpoint

    Examples
    --------
    >>> limiter = RateLimiter(calls_per_second=5)
    >>> if limiter.check_limit("api_endpoint"):
    ...     make_api_call()
    """

    def __init__(self, calls_per_second: int = 10):
        """
        Initialize rate limiter.

        Parameters
        ----------
        calls_per_second : int
            Maximum calls per second
        """
        self.calls_per_second = calls_per_second
        self.lock = threading.RLock()
        self.calls: Dict[str, List[float]] = {}

    def check_limit(self, name: str) -> bool:
        """
        Check if call is within rate limit.

        Parameters
        ----------
        name : str
            API endpoint name

        Returns
        -------
        bool
            True if within limit, False otherwise

        Notes
        -----
        Uses sliding window algorithm with one-second windows.
        Thread-safe implementation.
        """
        with self.lock:
            now = time.time()

            # Initialize if first call
            if name not in self.calls:
                self.calls[name] = []

            # Remove calls older than 1 second
            self.calls[name] = [t for t in self.calls[name] if now - t < 1]

            # Check if within limit
            if len(self.calls[name]) >= self.calls_per_second:
                return False

            # Record new call
            self.calls[name].append(now)
            return True

    def get_remaining(self, name: str) -> int:
        """
        Get remaining calls for this second.

        Parameters
        ----------
        name : str
            API endpoint name

        Returns
        -------
        int
            Number of remaining calls in current second

        Examples
        --------
        >>> limiter.get_remaining("api_endpoint")
        3
        """
        with self.lock:
            now = time.time()

            if name not in self.calls:
                return self.calls_per_second

            # Clean old calls
            self.calls[name] = [t for t in self.calls[name] if now - t < 1]

            return self.calls_per_second - len(self.calls[name])
