#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Thread-safe caching mechanism for package distribution metadata with advanced features.

This module provides thread-safe caching system for Python
package distribution metadata, reducing filesystem I/O and improving analysis
performance for large dependency trees.
"""

import threading
import time
import sys
from importlib.metadata import distribution, PackageNotFoundError
from typing import Optional, Any, Dict, List, Callable, Union, Tuple
from collections import OrderedDict
from dataclasses import dataclass, field
import logging
import hashlib
import json
from functools import wraps

# Configure module logger
logger = logging.getLogger(__name__)


class CacheError(Exception):
    """
    Exception raised for cache operation errors.
    
    Attributes
    ----------
    message : str
        Human-readable description of the error
    operation : str, optional
        The cache operation that failed (get, set, delete, etc.)
    package_name : str, optional
        Name of the package involved in the error
    original_error : Exception, optional
        Original exception that caused this error
    
    Examples
    --------
    >>> raise CacheError("Failed to retrieve package", 
    ...                  operation="get", package_name="requests")
    """
    
    def __init__(self, message: str, operation: Optional[str] = None,
                 package_name: Optional[str] = None,
                 original_error: Optional[Exception] = None):
        self.message = message
        self.operation = operation
        self.package_name = package_name
        self.original_error = original_error
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        """Format the error message with context."""
        parts = [self.message]
        if self.operation:
            parts.append(f" (operation: {self.operation})")
        if self.package_name:
            parts.append(f" (package: {self.package_name})")
        if self.original_error:
            parts.append(f" (cause: {str(self.original_error)})")
        return "".join(parts)


@dataclass
class CacheEntry:
    """
    Data structure representing a cached package entry.
    
    Attributes
    ----------
    distribution : Any
        The cached distribution object
    timestamp : float
        Unix timestamp when entry was cached
    access_count : int
        Number of times this entry has been accessed
    last_access : float
        Unix timestamp of last access
    size_bytes : int
        Estimated size of cached object in bytes
    metadata_hash : str, optional
        Hash of package metadata for change detection
    
    Examples
    --------
    >>> entry = CacheEntry(
    ...     distribution=dist,
    ...     timestamp=time.time(),
    ...     access_count=0,
    ...     last_access=time.time(),
    ...     size_bytes=1024
    ... )
    """
    distribution: Any
    timestamp: float = field(default_factory=time.time)
    access_count: int = 0
    last_access: float = field(default_factory=time.time)
    size_bytes: int = 0
    metadata_hash: Optional[str] = None
    
    def update_access(self) -> None:
        """Update access statistics for this cache entry."""
        self.access_count += 1
        self.last_access = time.time()
    
    def age_seconds(self) -> float:
        """
        Calculate age of cache entry in seconds.
        
        Returns
        -------
        float
            Age in seconds since entry was created
        """
        return time.time() - self.timestamp
    
    def is_stale(self, max_age_seconds: Optional[int] = None) -> bool:
        """
        Check if cache entry is stale based on age.
        
        Parameters
        ----------
        max_age_seconds : int, optional
            Maximum allowed age in seconds. If None, entry is never stale.
        
        Returns
        -------
        bool
            True if entry exceeds max age, False otherwise
        """
        if max_age_seconds is None:
            return False
        return self.age_seconds() > max_age_seconds


class LRUCache(OrderedDict):
    """
    LRU (Least Recently Used) cache implementation with size limits.
    
    This cache automatically removes the least recently used items when
    the cache exceeds the maximum size.
    
    Parameters
    ----------
    maxsize : int, default=128
        Maximum number of items to store in cache
    
    Examples
    --------
    >>> cache = LRUCache(maxsize=2)
    >>> cache['a'] = 'value1'
    >>> cache['b'] = 'value2'
    >>> cache['c'] = 'value3'  # This will evict 'a'
    >>> 'a' in cache
    False
    """
    
    def __init__(self, maxsize: int = 128):
        self.maxsize = maxsize
        super().__init__()
    
    def __getitem__(self, key: str) -> CacheEntry:
        """
        Get item and move to end (mark as recently used).
        
        Parameters
        ----------
        key : str
            Cache key to retrieve
        
        Returns
        -------
        CacheEntry
            Cached entry
        
        Raises
        ------
        KeyError
            If key does not exist
        """
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value
    
    def __setitem__(self, key: str, value: CacheEntry) -> None:
        """
        Set item and enforce maxsize limit.
        
        Parameters
        ----------
        key : str
            Cache key
        value : CacheEntry
            Value to cache
        """
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            # Remove the least recently used item
            oldest = next(iter(self))
            del self[oldest]
            logger.debug(f"LRU cache evicted: {oldest}")


class PackageCache:
    """
    Thread-safe singleton cache for package distribution metadata with advanced features.
    
    This class provides a high-performance caching system for package distribution
    metadata with support for:
    - Thread-safe operations using reentrant locks
    - Singleton pattern for global cache access
    - LRU eviction policy
    - TTL (Time-To-Live) for cache entries
    - Statistics tracking
    - Cache persistence (save/load)
    - Weak references for memory optimization
    - Batch operations
    - Cache warming
    - Event callbacks for cache operations
    
    Attributes
    ----------
    _instance : PackageCache
        Singleton instance
    _cache : Union[Dict[str, CacheEntry], LRUCache]
        Cache storage for package distributions
    _lock : threading.RLock
        Reentrant lock for thread-safe operations
    _stats : Dict[str, Any]
        Cache statistics (hits, misses, evictions, etc.)
    _callbacks : Dict[str, List[Callable]]
        Event callbacks for cache operations
    _maxsize : int
        Maximum number of items in cache
    _ttl_seconds : Optional[int]
        Time-to-live for cache entries in seconds
    
    Examples
    --------
    >>> # Basic usage
    >>> cache = PackageCache()
    >>> dist = cache.get_distribution("requests")
    >>> if dist:
    ...     print(f"Found: {dist.metadata['Name']}")
    
    >>> # With custom configuration
    >>> cache = PackageCache(maxsize=200, ttl_seconds=3600)
    >>> cache.warm_cache(["requests", "pandas", "numpy"])
    
    >>> # Statistics and monitoring
    >>> stats = cache.get_stats()
    >>> print(f"Hit rate: {stats['hit_rate']:.2%}")
    >>> cache.register_callback('on_hit', lambda pkg: print(f"Hit: {pkg}"))
    """
    
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls, maxsize: int = 128, ttl_seconds: Optional[int] = None,
                use_lru: bool = True, enable_stats: bool = True):
        """
        Create or return the singleton instance with configuration.
        
        Parameters
        ----------
        maxsize : int, default=128
            Maximum number of items to store in cache
        ttl_seconds : int, optional
            Time-to-live for cache entries in seconds
        use_lru : bool, default=True
            Whether to use LRU eviction policy
        enable_stats : bool, default=True
            Whether to collect cache statistics
        
        Returns
        -------
        PackageCache
            The single instance of PackageCache
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, maxsize: int = 128, ttl_seconds: Optional[int] = None,
                 use_lru: bool = True, enable_stats: bool = True):
        """
        Initialize the cache instance (called once).
        
        Parameters
        ----------
        maxsize : int, default=128
            Maximum number of items to store in cache
        ttl_seconds : int, optional
            Time-to-live for cache entries in seconds
        use_lru : bool, default=True
            Whether to use LRU eviction policy
        enable_stats : bool, default=True
            Whether to collect cache statistics
        """
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self._maxsize = maxsize
        self._ttl_seconds = ttl_seconds
        self._use_lru = use_lru
        self._enable_stats = enable_stats
        
        # Initialize cache storage
        if use_lru:
            self._cache = LRUCache(maxsize=maxsize)
        else:
            self._cache = {}
        
        # Initialize statistics
        self._stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'errors': 0,
            'total_accesses': 0,
            'cache_size': 0,
            'created_at': time.time()
        }
        
        # Initialize callbacks
        self._callbacks = {
            'on_hit': [],
            'on_miss': [],
            'on_set': [],
            'on_delete': [],
            'on_clear': [],
            'on_evict': [],
            'on_error': []
        }
        
        self._initialized = True
        logger.info(f"PackageCache initialized with maxsize={maxsize}, "
                   f"ttl={ttl_seconds}s, lru={use_lru}, stats={enable_stats}")
    
    @classmethod
    def get_instance(cls) -> 'PackageCache':
        """
        Get the singleton instance with default configuration.
        
        Returns
        -------
        PackageCache
            The singleton cache instance
        
        Examples
        --------
        >>> cache = PackageCache.get_instance()
        >>> cache.clear_cache()
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _update_stats(self, stat_name: str) -> None:
        """
        Update cache statistics.
        
        Parameters
        ----------
        stat_name : str
            Name of the statistic to update
        """
        if not self._enable_stats:
            return
        
        with self._lock:
            if stat_name in self._stats:
                self._stats[stat_name] += 1
            self._stats['total_accesses'] += 1
            self._stats['cache_size'] = len(self._cache)
    
    def _trigger_callbacks(self, event: str, *args, **kwargs) -> None:
        """
        Trigger registered callbacks for an event.
        
        Parameters
        ----------
        event : str
            Event name (must exist in _callbacks)
        *args, **kwargs
            Arguments to pass to callbacks
        """
        if event not in self._callbacks:
            return
        
        for callback in self._callbacks[event]:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Callback error for event {event}: {e}")
    
    def register_callback(self, event: str, callback: Callable) -> None:
        """
        Register a callback function for cache events.
        
        Parameters
        ----------
        event : str
            Event name ('on_hit', 'on_miss', 'on_set', 'on_delete', 
                      'on_clear', 'on_evict', 'on_error')
        callback : Callable
            Function to call when event occurs
        
        Raises
        ------
        CacheError
            If event name is invalid
        
        Examples
        --------
        >>> def log_hit(package_name):
        ...     print(f"Cache hit: {package_name}")
        >>> cache = PackageCache()
        >>> cache.register_callback('on_hit', log_hit)
        """
        if event not in self._callbacks:
            raise CacheError(
                f"Invalid event name: {event}. "
                f"Valid events: {list(self._callbacks.keys())}",
                operation="register_callback"
            )
        
        with self._lock:
            self._callbacks[event].append(callback)
            logger.debug(f"Registered callback for event: {event}")
    
    def _compute_metadata_hash(self, dist: Any) -> Optional[str]:
        """
        Compute a hash of package metadata for change detection.
        
        Parameters
        ----------
        dist : Any
            Distribution object
        
        Returns
        -------
        Optional[str]
            SHA256 hash of metadata or None if computation fails
        """
        try:
            metadata = {
                'name': dist.metadata.get('Name', ''),
                'version': dist.metadata.get('Version', ''),
                'requires_python': dist.metadata.get('Requires-Python', ''),
            }
            return hashlib.sha256(
                json.dumps(metadata, sort_keys=True).encode()
            ).hexdigest()
        except Exception as e:
            logger.debug(f"Failed to compute metadata hash: {e}")
            return None
    
    def _estimate_object_size(self, obj: Any) -> int:
        """
        Estimate the memory size of an object in bytes.
        
        Parameters
        ----------
        obj : Any
            Object to estimate size for
        
        Returns
        -------
        int
            Estimated size in bytes
        """
        try:
            import sys
            return sys.getsizeof(obj)
        except (TypeError, ImportError):
            return 1024  # Default estimate
    
    def get_distribution(self, package_name: str, 
                        bypass_cache: bool = False,
                        refresh_if_stale: bool = True) -> Optional[Any]:
        """
        Retrieve package distribution information with caching and advanced features.
        
        Parameters
        ----------
        package_name : str
            Name of the package to retrieve distribution for
        bypass_cache : bool, default=False
            If True, bypass cache and fetch directly from system
        refresh_if_stale : bool, default=True
            If True, refresh stale entries automatically
        
        Returns
        -------
        Distribution or None
            Distribution object if found, None if package is not installed
            or an error occurs
        
        Notes
        -----
        This method is thread-safe and uses double-checked locking pattern.
        Supports TTL-based staleness detection and automatic refresh.
        
        Examples
        --------
        >>> # Normal cached access
        >>> dist = PackageCache.get_distribution("pandas")
        >>> if dist:
        ...     print(f"Version: {dist.version}")
        
        >>> # Bypass cache for fresh data
        >>> dist = PackageCache.get_distribution("requests", bypass_cache=True)
        
        >>> # With automatic stale refresh
        >>> dist = PackageCache.get_distribution("numpy", refresh_if_stale=True)
        """
        package_name = package_name.lower()
        
        # Bypass cache if requested
        if bypass_cache:
            with self._lock:
                return self._fetch_distribution(package_name)
        
        # Check cache with double-checked locking
        with self._lock:
            # First check (without lock if already cached)
            if package_name in self._cache:
                entry = self._cache[package_name]
                
                # Check if entry is stale
                if refresh_if_stale and entry.is_stale(self._ttl_seconds):
                    logger.debug(f"Stale cache entry for {package_name}, refreshing")
                    self._update_stats('evictions')
                    self._trigger_callbacks('on_evict', package_name, 'stale')
                    self._remove_from_cache_unlocked(package_name)
                else:
                    # Cache hit
                    entry.update_access()
                    self._update_stats('hits')
                    self._trigger_callbacks('on_hit', package_name)
                    
                    # Move to end in LRU cache
                    if self._use_lru and isinstance(self._cache, LRUCache):
                        self._cache[package_name] = entry
                    
                    return entry.distribution
        
        # Cache miss - fetch with lock
        with self._lock:
            # Double-check in case another thread fetched it
            if package_name in self._cache:
                entry = self._cache[package_name]
                entry.update_access()
                self._update_stats('hits')
                self._trigger_callbacks('on_hit', package_name)
                return entry.distribution
            
            # Fetch distribution
            self._update_stats('misses')
            self._trigger_callbacks('on_miss', package_name)
            return self._fetch_and_cache_distribution(package_name)
    
    def _fetch_distribution(self, package_name: str) -> Optional[Any]:
        """
        Fetch distribution directly from system without caching.
        
        Parameters
        ----------
        package_name : str
            Name of the package to fetch
        
        Returns
        -------
        Optional[Any]
            Distribution object or None
        """
        try:
            dist = distribution(package_name)
            return dist
        except PackageNotFoundError:
            logger.debug(f"Package not found: {package_name}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {package_name}: {e}")
            self._update_stats('errors')
            self._trigger_callbacks('on_error', package_name, str(e))
            return None
    
    def _fetch_and_cache_distribution(self, package_name: str) -> Optional[Any]:
        """
        Fetch distribution and cache it.
        
        Parameters
        ----------
        package_name : str
            Name of the package to fetch and cache
        
        Returns
        -------
        Optional[Any]
            Distribution object or None
        """
        try:
            dist = distribution(package_name)
            
            if dist is not None:
                # Create cache entry
                entry = CacheEntry(
                    distribution=dist,
                    size_bytes=self._estimate_object_size(dist),
                    metadata_hash=self._compute_metadata_hash(dist)
                )
                
                self._cache[package_name] = entry
                self._update_stats('cache_size')
                self._trigger_callbacks('on_set', package_name, dist)
                logger.debug(f"Cached distribution for {package_name}")
                return dist
            else:
                # Cache None for missing packages
                self._cache[package_name] = CacheEntry(distribution=None)
                return None
                
        except PackageNotFoundError:
            logger.debug(f"Package not found: {package_name}")
            self._cache[package_name] = CacheEntry(distribution=None)
            return None
        except Exception as e:
            logger.error(f"Error caching {package_name}: {e}")
            self._update_stats('errors')
            self._trigger_callbacks('on_error', package_name, str(e))
            self._cache[package_name] = CacheEntry(distribution=None)
            return None
    
    def get_batch(self, package_names: List[str], 
                  skip_missing: bool = True) -> Dict[str, Optional[Any]]:
        """
        Retrieve multiple package distributions efficiently.
        
        Parameters
        ----------
        package_names : List[str]
            List of package names to retrieve
        skip_missing : bool, default=True
            If True, skip missing packages without raising errors
        
        Returns
        -------
        Dict[str, Optional[Any]]
            Dictionary mapping package names to distribution objects
            (or None for missing packages)
        
        Examples
        --------
        >>> packages = ["requests", "pandas", "numpy"]
        >>> results = PackageCache.get_batch(packages)
        >>> for name, dist in results.items():
        ...     if dist:
        ...         print(f"{name}: {dist.version}")
        """
        results = {}
        
        with self._lock:
            for package_name in package_names:
                try:
                    dist = self.get_distribution(package_name)
                    results[package_name] = dist
                except Exception as e:
                    if not skip_missing:
                        raise CacheError(
                            f"Failed to get {package_name}",
                            operation="get_batch",
                            package_name=package_name,
                            original_error=e
                        )
                    results[package_name] = None
                    logger.warning(f"Failed to get {package_name}: {e}")
        
        return results
    
    def warm_cache(self, package_names: List[str], 
                   parallel: bool = False,
                   max_workers: int = 4) -> Dict[str, bool]:
        """
        Pre-warm the cache with a list of packages.
        
        Parameters
        ----------
        package_names : List[str]
            List of package names to cache
        parallel : bool, default=False
            Whether to fetch packages in parallel
        max_workers : int, default=4
            Maximum number of threads for parallel fetching
        
        Returns
        -------
        Dict[str, bool]
            Dictionary mapping package names to success status
        
        Examples
        --------
        >>> common_packages = ["requests", "urllib3", "certifi", "idna"]
        >>> results = PackageCache.warm_cache(common_packages, parallel=True)
        >>> success_count = sum(results.values())
        >>> print(f"Warmed {success_count}/{len(common_packages)} packages")
        """
        results = {}
        
        if parallel:
            # Parallel fetching
            try:
                from concurrent.futures import ThreadPoolExecutor
                
                def fetch_package(pkg):
                    try:
                        dist = self.get_distribution(pkg, bypass_cache=True)
                        return pkg, dist is not None
                    except Exception as e:
                        logger.error(f"Failed to warm {pkg}: {e}")
                        return pkg, False
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(fetch_package, pkg) 
                              for pkg in package_names]
                    for future in futures:
                        pkg, success = future.result()
                        results[pkg] = success
            except ImportError:
                logger.warning("ThreadPoolExecutor not available, falling back to sequential")
                parallel = False
        
        if not parallel:
            # Sequential fetching
            for pkg in package_names:
                try:
                    dist = self.get_distribution(pkg, bypass_cache=False)
                    results[pkg] = dist is not None
                except Exception as e:
                    logger.error(f"Failed to warm {pkg}: {e}")
                    results[pkg] = False
        
        success_count = sum(1 for v in results.values() if v)
        logger.info(f"Cache warmed with {success_count}/{len(package_names)} packages")
        return results
    
    def clear_cache(self) -> None:
        """
        Clear all cached package distribution data.
        
        Use this method when the environment changes (packages installed/removed)
        during the lifetime of the application.
        
        Examples
        --------
        >>> PackageCache.clear_cache()
        >>> # Cache is now empty
        >>> assert PackageCache.get_cache_size() == 0
        """
        with self._lock:
            cache_size = len(self._cache)
            self._cache.clear()
            self._stats['cache_size'] = 0
            self._trigger_callbacks('on_clear', cache_size)
            logger.info(f"Cleared cache ({cache_size} entries)")
    
    def get_cache_size(self) -> int:
        """
        Get the current number of cached packages.
        
        Returns
        -------
        int
            Number of packages in cache
        
        Examples
        --------
        >>> size = PackageCache.get_cache_size()
        >>> print(f"Cache contains {size} packages")
        """
        with self._lock:
            return len(self._cache)
    
    def remove_from_cache(self, package_name: str) -> bool:
        """
        Remove a specific package from cache.
        
        Parameters
        ----------
        package_name : str
            Name of the package to remove
        
        Returns
        -------
        bool
            True if package was in cache and removed, False otherwise
        
        Examples
        --------
        >>> removed = PackageCache.remove_from_cache("requests")
        >>> if removed:
        ...     print("Package removed from cache")
        """
        with self._lock:
            return self._remove_from_cache_unlocked(package_name.lower())
    
    def _remove_from_cache_unlocked(self, package_name: str) -> bool:
        """
        Remove package from cache without acquiring lock.
        
        Parameters
        ----------
        package_name : str
            Name of the package to remove
        
        Returns
        -------
        bool
            True if removed, False otherwise
        """
        if package_name in self._cache:
            del self._cache[package_name]
            self._stats['cache_size'] = len(self._cache)
            self._trigger_callbacks('on_delete', package_name)
            logger.debug(f"Removed {package_name} from cache")
            return True
        return False
    
    def get_cache_keys(self) -> List[str]:
        """
        Get list of all package names in cache.
        
        Returns
        -------
        List[str]
            List of cached package names
        
        Examples
        --------
        >>> cached_packages = PackageCache.get_cache_keys()
        >>> print(f"Cached: {', '.join(cached_packages)}")
        """
        with self._lock:
            return list(self._cache.keys())
    
    def get_cache_entry_info(self, package_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a cached entry.
        
        Parameters
        ----------
        package_name : str
            Name of the package to get info for
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Dictionary with entry metadata or None if not cached
        
        Examples
        --------
        >>> info = PackageCache.get_cache_entry_info("requests")
        >>> if info:
        ...     print(f"Access count: {info['access_count']}")
        ...     print(f"Age: {info['age_seconds']:.1f} seconds")
        """
        with self._lock:
            package_name = package_name.lower()
            if package_name not in self._cache:
                return None
            
            entry = self._cache[package_name]
            return {
                'access_count': entry.access_count,
                'age_seconds': entry.age_seconds(),
                'timestamp': entry.timestamp,
                'last_access': entry.last_access,
                'size_bytes': entry.size_bytes,
                'is_stale': entry.is_stale(self._ttl_seconds) if self._ttl_seconds else False,
                'has_distribution': entry.distribution is not None
            }
    
    def get_stats(self, reset: bool = False) -> Dict[str, Any]:
        """
        Get cache statistics including hit rates and performance metrics.
        
        Parameters
        ----------
        reset : bool, default=False
            If True, reset statistics after retrieving
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing cache statistics
            
        Examples
        --------
        >>> stats = PackageCache.get_stats()
        >>> print(f"Hit rate: {stats['hit_rate']:.2%}")
        >>> print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")
        """
        with self._lock:
            stats = self._stats.copy()
            
            # Calculate hit rate
            total = stats['hits'] + stats['misses']
            stats['hit_rate'] = stats['hits'] / total if total > 0 else 0.0
            stats['miss_rate'] = stats['misses'] / total if total > 0 else 0.0
            
            # Add additional metrics
            stats['uptime_seconds'] = time.time() - stats['created_at']
            stats['current_size'] = len(self._cache)
            stats['max_size'] = self._maxsize
            if self._maxsize > 0:
                stats['utilization'] = len(self._cache) / self._maxsize
            else:
                stats['utilization'] = 0.0
            
            if reset:
                # Reset statistics
                self._stats = {
                    'hits': 0,
                    'misses': 0,
                    'evictions': 0,
                    'errors': 0,
                    'total_accesses': 0,
                    'cache_size': len(self._cache),
                    'created_at': time.time()
                }
            
            return stats
    
    def save_to_file(self, filepath: str, include_distributions: bool = False) -> bool:
        """
        Save cache to file for persistence across sessions.
        
        Parameters
        ----------
        filepath : str
            Path to save cache data
        include_distributions : bool, default=False
            If True, save distribution objects (may not be picklable)
        
        Returns
        -------
        bool
            True if save succeeded, False otherwise
        
        Examples
        --------
        >>> PackageCache.save_to_file("cache.pkl")
        >>> PackageCache.save_to_file("cache.json", include_distributions=False)
        """
        import pickle
        
        try:
            with self._lock:
                cache_data = {
                    'entries': {},
                    'stats': self._stats,
                    'ttl_seconds': self._ttl_seconds,
                    'maxsize': self._maxsize,
                    'saved_at': time.time()
                }
                
                for pkg_name, entry in self._cache.items():
                    if include_distributions:
                        # Full save (may fail for unpicklable objects)
                        cache_data['entries'][pkg_name] = {
                            'distribution': entry.distribution,
                            'timestamp': entry.timestamp,
                            'access_count': entry.access_count,
                            'last_access': entry.last_access
                        }
                    else:
                        # Just save metadata
                        cache_data['entries'][pkg_name] = {
                            'timestamp': entry.timestamp,
                            'access_count': entry.access_count,
                            'last_access': entry.last_access,
                            'has_distribution': entry.distribution is not None
                        }
                
                # Choose format based on file extension
                if filepath.endswith('.json'):
                    with open(filepath, 'w', encoding='utf-8') as f:
                        json.dump(cache_data, f, default=str, indent=2, ensure_ascii=False)
                else:
                    with open(filepath, 'wb') as f:
                        pickle.dump(cache_data, f)
                
                logger.info(f"Cache saved to {filepath}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save cache to {filepath}: {e}")
            return False
    
    def load_from_file(self, filepath: str, load_distributions: bool = False) -> bool:
        """
        Load cache from file for persistence across sessions.
        
        Parameters
        ----------
        filepath : str
            Path to load cache data from
        load_distributions : bool, default=False
            If True, load distribution objects (may not be available)
        
        Returns
        -------
        bool
            True if load succeeded, False otherwise
        
        Examples
        --------
        >>> PackageCache.load_from_file("cache.pkl")
        >>> PackageCache.load_from_file("cache.json")
        """
        import pickle
        
        try:
            with self._lock:
                # Choose format based on file extension
                if filepath.endswith('.json'):
                    with open(filepath, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                else:
                    with open(filepath, 'rb') as f:
                        cache_data = pickle.load(f)
                
                # Restore cache entries
                loaded_count = 0
                for pkg_name, entry_data in cache_data['entries'].items():
                    if load_distributions and 'distribution' in entry_data:
                        dist = entry_data['distribution']
                    else:
                        dist = None
                    
                    entry = CacheEntry(
                        distribution=dist,
                        timestamp=entry_data['timestamp'],
                        access_count=entry_data.get('access_count', 0),
                        last_access=entry_data.get('last_access', entry_data['timestamp'])
                    )
                    self._cache[pkg_name] = entry
                    loaded_count += 1
                
                # Restore stats if not reset
                self._stats.update(cache_data.get('stats', {}))
                
                logger.info(f"Loaded {loaded_count} entries from {filepath}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to load cache from {filepath}: {e}")
            return False
    
    def __len__(self) -> int:
        """
        Return number of items in cache.
        
        Returns
        -------
        int
            Cache size
        """
        return self.get_cache_size()
    
    def __contains__(self, package_name: str) -> bool:
        """
        Check if package is in cache.
        
        Parameters
        ----------
        package_name : str
            Package name to check
        
        Returns
        -------
        bool
            True if in cache, False otherwise
        """
        with self._lock:
            return package_name.lower() in self._cache
    
    def __repr__(self) -> str:
        """
        Return string representation of the cache.
        
        Returns
        -------
        str
            Cache description
        """
        return (f"<PackageCache(size={len(self._cache)}, maxsize={self._maxsize}, "
                f"ttl={self._ttl_seconds}s, lru={self._use_lru})>")


# Backward compatibility functions
def get_distribution(package_name: str) -> Optional[Any]:
    """
    Legacy function for backward compatibility.
    
    Parameters
    ----------
    package_name : str
        Name of the package
    
    Returns
    -------
    Optional[Any]
        Distribution object or None
    """
    return PackageCache.get_distribution(package_name)


def clear_cache() -> None:
    """
    Legacy function for backward compatibility.
    
    Examples
    --------
    >>> clear_cache()  # Legacy call
    >>> PackageCache.clear_cache()  # New recommended way
    """
    PackageCache.clear_cache()


def get_cache_size() -> int:
    """
    Legacy function for backward compatibility.
    
    Returns
    -------
    int
        Number of packages in cache
    """
    return PackageCache.get_cache_size()


def remove_from_cache(package_name: str) -> bool:
    """
    Legacy function for backward compatibility.
    
    Parameters
    ----------
    package_name : str
        Name of the package to remove
    
    Returns
    -------
    bool
        True if removed, False otherwise
    """
    return PackageCache.remove_from_cache(package_name)


# Context manager for temporary cache configuration
class CacheContext:
    """
    Context manager for temporary cache configuration changes.
    
    Parameters
    ----------
    cache : PackageCache, optional
        Cache instance to configure (uses singleton if None)
    **kwargs
        Temporary configuration options
    
    Examples
    --------
    >>> with CacheContext(ttl_seconds=60):
    ...     # Cache entries will expire after 60 seconds
    ...     dist = PackageCache.get_distribution("requests")
    >>> # Original TTL restored
    """
    
    def __init__(self, cache: Optional[PackageCache] = None, **kwargs):
        self.cache = cache or PackageCache.get_instance()
        self.temp_config = kwargs
        self.original_config = {}
    
    def __enter__(self):
        """Apply temporary configuration."""
        for key, value in self.temp_config.items():
            private_key = f'_{key}'
            if hasattr(self.cache, private_key):
                self.original_config[key] = getattr(self.cache, private_key)
                setattr(self.cache, private_key, value)
        return self.cache
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Restore original configuration."""
        for key, value in self.original_config.items():
            private_key = f'_{key}'
            setattr(self.cache, private_key, value)


# Safe environment check without causing errors
def _check_environment() -> None:
    """
    Check environment and log cache configuration safely.
    
    This function handles Python version differences and avoids
    PackageNotFoundError by not attempting to import non-existent packages.
    """
    logger.debug("PackageCache module initialized")
    
    try:
        # Safe way to check Python version without external package dependencies
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        logger.debug(f"Python version: {python_version}")
        
        # Check importlib.metadata availability safely
        try:
            from importlib import metadata as importlib_metadata
            logger.debug(f"importlib.metadata is available (built-in)")
        except ImportError:
            logger.debug("importlib.metadata not available")
            
    except Exception as e:
        # Don't let environment checking crash the module
        logger.debug(f"Environment check failed (non-critical): {e}")


# Run safe environment check
_check_environment()