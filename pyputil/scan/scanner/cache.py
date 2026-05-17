#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Cache management for module scanner results.

This module provides caching functionality to improve performance
by storing and retrieving scan results.
"""

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from ..core.models import ModuleMeta


@dataclass
class CacheEntry:
    """
    Cache entry with metadata and results.

    Attributes
    ----------
    results : List[ModuleMeta]
        Cached module metadata
    timestamp : float
        When the entry was cached
    access_count : int
        Number of times this entry has been accessed
    last_access : float
        Timestamp of last access
    """

    results: List[ModuleMeta]
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0
    last_access: float = field(default_factory=time.time)

    def update_access(self) -> None:
        """Update access statistics for this cache entry."""
        self.access_count += 1
        self.last_access = time.time()


class CacheManager:
    """
    Manages caching of module scan results.

    This class handles storing, retrieving, and managing cache entries
    for module scan results, with support for cache eviction policies.

    Attributes
    ----------
    cache : Dict[str, CacheEntry]
        Dictionary storing cache entries by key
    max_size : Optional[int]
        Maximum number of entries in cache
    ttl : Optional[float]
        Time-to-live for cache entries in seconds
    """

    def __init__(self, max_size: Optional[int] = 100, ttl: Optional[float] = 3600):
        """
        Initialize cache manager with optional limits.

        Parameters
        ----------
        max_size : Optional[int]
            Maximum number of entries (None for unlimited)
        ttl : Optional[float]
            Time-to-live in seconds (None for no expiration)
        """
        self.cache: Dict[str, CacheEntry] = {}
        self.max_size = max_size
        self.ttl = ttl
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expirations": 0,
        }

    def __contains__(self, key: str) -> bool:
        """
        Check if key exists and is valid in cache.

        Parameters
        ----------
        key : str
            Cache key to check

        Returns
        -------
        bool
            True if key exists and is not expired
        """
        if key not in self.cache:
            return False

        entry = self.cache[key]

        # Check expiration
        if self.ttl and time.time() - entry.timestamp > self.ttl:
            self._expire_entry(key)
            return False

        return True

    def __len__(self) -> int:
        """
        Get number of entries in cache.

        Returns
        -------
        int
            Number of cache entries
        """
        return len(self.cache)

    def keys(self) -> List[str]:
        """
        Get all cache keys.

        Returns
        -------
        List[str]
            List of current cache keys
        """
        return list(self.cache.keys())

    def _expire_entry(self, key: str) -> None:
        """
        Remove an expired entry from cache.

        Parameters
        ----------
        key : str
            Key of entry to expire
        """
        if key in self.cache:
            del self.cache[key]
            self.stats["expirations"] += 1

    def _evict_if_needed(self) -> None:
        """
        Evict oldest entry if cache size exceeds maximum.
        """
        if self.max_size is None or len(self.cache) <= self.max_size:
            return

        # Find oldest entry by timestamp
        oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k].timestamp)
        del self.cache[oldest_key]
        self.stats["evictions"] += 1

    def get(self, key: str) -> Optional[List[ModuleMeta]]:
        """
        Retrieve cached results for a key.

        Parameters
        ----------
        key : str
            Cache key to retrieve

        Returns
        -------
        Optional[List[ModuleMeta]]
            Cached results if available and valid, None otherwise
        """
        if key not in self.cache:
            self.stats["misses"] += 1
            return None

        entry = self.cache[key]

        # Check expiration
        if self.ttl and time.time() - entry.timestamp > self.ttl:
            self._expire_entry(key)
            self.stats["misses"] += 1
            return None

        # Update statistics
        entry.update_access()
        self.stats["hits"] += 1

        return entry.results

    def set(self, key: str, results: List[ModuleMeta]) -> None:
        """
        Store results in cache.

        Parameters
        ----------
        key : str
            Cache key to store under
        results : List[ModuleMeta]
            Results to cache
        """
        self.cache[key] = CacheEntry(results=results)
        self._evict_if_needed()

    def clear(self) -> None:
        """Clear all entries from cache."""
        self.cache.clear()
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expirations": 0,
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing cache performance metrics
        """
        hit_ratio = 0
        total_accesses = self.stats["hits"] + self.stats["misses"]
        if total_accesses > 0:
            hit_ratio = self.stats["hits"] / total_accesses

        return {
            **self.stats,
            "size": len(self.cache),
            "max_size": self.max_size,
            "ttl": self.ttl,
            "hit_ratio": hit_ratio,
            "total_accesses": total_accesses,
        }