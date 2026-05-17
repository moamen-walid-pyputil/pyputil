#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Caching for module maker.
"""

import threading
import time
from typing import Any, Optional


class MakeCache:
    """
    Thread-safe cache.

    Parameters
    ----------
    max_size : int, default=1000
        Maximum number of cache entries
    ttl : int, default=3600
        Time-to-live for cache entries in seconds

    Attributes
    ----------
    _cache : Dict[str, Any]
        Cache storage
    _access_times : Dict[str, float]
        Last access timestamps
    _max_size : int
        Maximum cache size
    _ttl : int
        Time-to-live in seconds
    _lock : threading.Lock
        Lock for thread safety
    """

    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        """
        Initialize MakeCache with size and TTL limits.
        """
        self._cache = {}
        self._access_times = {}
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """
        Retrieve a value from cache.

        Parameters
        ----------
        key : str
            Cache key

        Returns
        -------
        Optional[Any]
            Cached value or None if not found/expired
        """
        with self._lock:
            if key not in self._cache:
                return None

            # Check TTL
            if time.time() - self._access_times[key] > self._ttl:
                self._evict(key)
                return None

            # Update access time
            self._access_times[key] = time.time()
            return self._cache[key]

    def set(self, key: str, value: Any) -> None:
        """
        Store a value in cache.

        Parameters
        ----------
        key : str
            Cache key
        value : Any
            Value to cache

        Notes
        -----
        Automatically evicts oldest entry if cache is full.
        """
        with self._lock:
            # Evict if cache is full
            if len(self._cache) >= self._max_size:
                self._evict_oldest()

            # Store value
            self._cache[key] = value
            self._access_times[key] = time.time()

    def delete(self, key: str) -> None:
        """
        Delete a key from cache.

        Parameters
        ----------
        key : str
            Key to delete
        """
        with self._lock:
            self._evict(key)

    def clear(self) -> None:
        """
        Clear all cache entries.
        """
        with self._lock:
            self._cache.clear()
            self._access_times.clear()

    def _evict(self, key: str) -> None:
        """
        Evict a specific key from cache.

        Parameters
        ----------
        key : str
            Key to evict
        """
        self._cache.pop(key, None)
        self._access_times.pop(key, None)

    def _evict_oldest(self) -> None:
        """Evict the least recently accessed entry."""
        if not self._access_times:
            return

        # Find oldest key
        oldest_key = min(self._access_times.items(), key=lambda x: x[1])[0]
        self._evict(oldest_key)

    def size(self) -> int:
        """
        Get current cache size.

        Returns
        -------
        int
            Number of entries in cache
        """
        with self._lock:
            return len(self._cache)

    def keys(self):
        """
        Get all cache keys.

        Returns
        -------
        KeysView
            View of all cache keys
        """
        with self._lock:
            return self._cache.keys()
