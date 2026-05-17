#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import threading
import time
from typing import Dict, Tuple, Optional, Any


class APICache:
    """
    Caching for API members.

    Parameters
    ----------
    max_size : int, default=1000
        Maximum number of items in cache
    ttl : int, default=3600
        Time to live in seconds

    Attributes
    ----------
    max_size : int
        Maximum cache size
    ttl : int
        Time to live (seconds)
    _cache : Dict[str, Tuple[Any, float]]
        Cache storage with timestamps
    _hits : int
        Cache hit count
    _misses : int
        Cache miss count
    _lock : threading.RLock
        Thread lock

    Examples
    --------
    >>> cache = APICache(max_size=100, ttl=300)
    >>> cache.set("key", "value")
    >>> value = cache.get("key")
    """

    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        """
        Initialize cache with configuration.

        Parameters
        ----------
        max_size : int
            Maximum items in cache
        ttl : int
            Time to live in seconds
        """
        self.max_size = max_size
        self.ttl = ttl
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._hits = 0
        self._misses = 0
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        """
        Get cached value if fresh.

        Parameters
        ----------
        key : str
            Cache key

        Returns
        -------
        Any or None
            Cached value if fresh, None otherwise

        Notes
        -----
        Automatically evicts expired items.
        Updates hit/miss statistics.
        """
        with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]

                # Check if still valid
                if time.time() - timestamp < self.ttl:
                    self._hits += 1
                    return value
                else:
                    # Evict expired item
                    del self._cache[key]

            # Cache miss
            self._misses += 1
            return None

    def set(self, key: str, value: Any):
        """
        Cache a value.

        Parameters
        ----------
        key : str
            Cache key
        value : Any
            Value to cache

        Notes
        -----
        Implements LRU eviction when cache is full.
        Thread-safe operation.
        """
        with self._lock:
            # Evict oldest if cache full
            if len(self._cache) >= self.max_size:
                oldest_key = min(self._cache.items(), key=lambda x: x[1][1])[0]
                del self._cache[oldest_key]

            # Store with current timestamp
            self._cache[key] = (value, time.time())

    def clear(self):
        """Clear all cached items."""
        with self._lock:
            self._cache.clear()

    def clear_specific(self, key: str):
        """
        Clear specific cached item.

        Parameters
        ----------
        key : str
            Key to clear
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]

    def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns
        -------
        Dict[str, Any]
            Statistics including size, hits, misses, hit rate

        Examples
        --------
        >>> cache.stats()
        {
            'size': 50,
            'hits': 100,
            'misses': 20,
            'hit_rate': 0.833,
            'ttl': 3600,
            'max_size': 1000
        }
        """
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / max(total, 1),
                "ttl": self.ttl,
                "max_size": self.max_size,
            }
