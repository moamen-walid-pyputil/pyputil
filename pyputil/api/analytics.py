#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Analytics and monitoring for API usage.

Tracks API usage patterns, errors, and performance metrics.
"""

import threading
import time
from typing import Dict, List, Any
from datetime import datetime


class APIAnalytics:
    """
    Analytics and monitoring for API usage.

    Collects comprehensive statistics on API usage including access patterns,
    errors, and performance metrics.

    Attributes
    ----------
    usage_stats : Dict[str, Dict[str, Any]]
        Usage statistics per API member
    error_log : List[Dict[str, Any]]
        Error log entries
    performance_log : List[Dict[str, Any]]
        Performance metrics log
    _lock : threading.RLock
        Thread lock for thread safety

    Examples
    --------
    >>> analytics = APIAnalytics()
    >>> analytics.record_access("api_function", success=True, duration=0.1)
    >>> stats = analytics.get_usage_stats("api_function")
    """

    def __init__(self):
        """Initialize analytics system."""
        self.usage_stats: Dict[str, Dict[str, Any]] = {}
        self.error_log: List[Dict[str, Any]] = []
        self.performance_log: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

    def record_access(self, name: str, success: bool, duration: float):
        """
        Record API access.

        Parameters
        ----------
        name : str
            API member name
        success : bool
            Whether access was successful
        duration : float
            Access duration in seconds

        Notes
        -----
        Updates running averages and statistics.
        Thread-safe operation.
        """
        with self._lock:
            # Initialize if first access
            if name not in self.usage_stats:
                self.usage_stats[name] = {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "failed_calls": 0,
                    "total_duration": 0.0,
                    "avg_duration": 0.0,
                    "last_called": time.time(),
                    "first_called": time.time(),
                }

            stats = self.usage_stats[name]
            stats["total_calls"] += 1

            if success:
                stats["successful_calls"] += 1
            else:
                stats["failed_calls"] += 1

            # Update duration statistics
            stats["total_duration"] += duration
            stats["avg_duration"] = stats["total_duration"] / stats["total_calls"]
            stats["last_called"] = time.time()

    def record_error(self, name: str, error: Exception, traceback: str):
        """
        Record error.

        Parameters
        ----------
        name : str
            API member name
        error : Exception
            Error that occurred
        traceback : str
            Full traceback

        Notes
        -----
        Maintains rolling log of last 1000 errors.
        """
        with self._lock:
            self.error_log.append(
                {
                    "timestamp": time.time(),
                    "name": name,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    "traceback": traceback,
                }
            )

            # Keep only last 1000 errors
            if len(self.error_log) > 1000:
                self.error_log.pop(0)

    def record_performance(self, name: str, duration: float, memory_delta: int):
        """
        Record performance metrics.

        Parameters
        ----------
        name : str
            API member name
        duration : float
            Execution duration in seconds
        memory_delta : int
            Memory usage delta in bytes

        Notes
        -----
        Maintains rolling log of last 10,000 performance samples.
        """
        with self._lock:
            self.performance_log.append(
                {
                    "timestamp": time.time(),
                    "name": name,
                    "duration": duration,
                    "memory_delta": memory_delta,
                }
            )

            # Keep only last 10,000 samples
            if len(self.performance_log) > 10000:
                self.performance_log = self.performance_log[-10000:]

    def get_usage_stats(self, name: str = None) -> Dict[str, Any]:
        """
        Get usage statistics.

        Parameters
        ----------
        name : str, optional
            Specific API member name

        Returns
        -------
        Dict[str, Any]
            Usage statistics

        Examples
        --------
        >>> analytics.get_usage_stats("api_function")
        {
            'total_calls': 100,
            'successful_calls': 95,
            'failed_calls': 5,
            'avg_duration': 0.1,
            'last_called': 1634567890.123
        }
        """
        with self._lock:
            if name:
                return self.usage_stats.get(name, {}).copy()
            return {k: v.copy() for k, v in self.usage_stats.items()}
