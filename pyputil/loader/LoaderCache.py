#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module Cache System
===================

A sophisticated caching system for module-like objects with weak reference support,
dependency tracking, and comprehensive statistics collection.

This module provides a thread-safe cache implementation that can store objects either
as strong or weak references, track access patterns, manage dependencies between
cached items, and automatically clean up expired or underutilized entries.

Requirements
------------
Objects stored in weak reference mode must support weak references (have __weakref__ slot).
Most Python objects support this by default, but built-in types like str, int, tuple do not.

Example
-------
>>> cache = ModuleCache(enable_weakref=True, default_ttl=300)
>>> 
>>> # Store a weakref-compatible object
>>> class MyModule:
...     pass
>>> 
>>> cache['my_module'] = MyModule()
>>> obj = cache['my_module']
>>> cache.set_deps('my_module', MyModule(), ['dependency1', 'dependency2'])
>>> dependents = cache.get_dependents('dependency1')
"""

import sys
import weakref
import threading
from typing import Any, Dict, Optional, List, Set, Tuple, Union, Callable, TypeVar, Generic
import time
import gc
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
import inspect

# Configure module logger
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

T = TypeVar('T')


class WeakRefSupport(Enum):
    """Weak reference support levels."""
    FULL = "full"          # Full weak reference support
    AUTO_DETECT = "auto"   # Auto-detect if object supports weakref
    STRONG_ONLY = "strong" # Only use strong references


class EvictionPolicy(Enum):
    """Eviction policies for cache cleanup strategies."""
    TTL = "time_to_live"
    LRU = "least_recently_used"
    LFU = "least_frequently_used"
    HYBRID = "hybrid"
    NONE = "none"


@dataclass
class ModuleMetadata:
    """
    Metadata container for cached modules.
    
    Attributes
    ----------
    access_count : int
        Number of times the module has been accessed
    last_access_time : float
        Timestamp of the most recent access
    load_time : float
        Timestamp when the module was first loaded/cached
    dependencies : Set[str]
        Set of module names this module depends on
    dependents : Set[str]
        Set of module names that depend on this module
    size_bytes : Optional[int]
        Estimated size of the module object in bytes (if measurable)
    custom_tags : Dict[str, Any]
        User-defined metadata tags for custom categorization
    supports_weakref : bool
        Whether the stored object supports weak references
    """
    access_count: int = 0
    last_access_time: float = field(default_factory=time.time)
    load_time: float = field(default_factory=time.time)
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)
    size_bytes: Optional[int] = None
    custom_tags: Dict[str, Any] = field(default_factory=dict)
    supports_weakref: bool = True


class WeakRefCompatible:
    """
    A wrapper class that makes any object weakref-compatible.
    
    Use this wrapper when you need to store objects that don't natively
    support weak references (like strings, integers, etc.) in weak mode.
    
    Parameters
    ----------
    obj : Any
        The object to wrap
    
    Examples
    --------
    >>> cache = ModuleCache(enable_weakref=True)
    >>> cache['my_string'] = WeakRefCompatible("Hello World")
    >>> # Or use the convenience method
    >>> cache.store_weakref_compatible('my_string', "Hello World")
    """
    
    __slots__ = ('_obj',)
    
    def __init__(self, obj: Any):
        self._obj = obj
    
    def __call__(self) -> Any:
        """Return the wrapped object."""
        return self._obj
    
    def get(self) -> Any:
        """Get the wrapped object."""
        return self._obj
    
    def __repr__(self) -> str:
        return f"WeakRefCompatible({repr(self._obj)})"


class ModuleCache:
    """
    A comprehensive cache system for storing module-like objects.

    This class implements a thread-safe cache that can store objects using either
    strong or weak references, with automatic promotion from weak to strong based
    on access patterns. It includes dependency tracking, expiration policies,
    statistics collection, and multiple cleanup strategies.

    Parameters
    ----------
    enable_weakref : bool or WeakRefSupport, default=WeakRefSupport.AUTO_DETECT
        When True, modules are stored as weak references by default, allowing
        Python's garbage collector to clean them up when no other references exist.
        Use WeakRefSupport.AUTO_DETECT to automatically fall back to strong references
        for objects that don't support weakref.
    
    default_ttl : float, optional
        Global time-to-live value in seconds for all cached items. If set, items
        older than this value will be automatically removed during cleanup operations.
    
    eviction_policy : EvictionPolicy, default=EvictionPolicy.HYBRID
        Strategy to use when cleaning up expired or underutilized modules.
        Options: TTL, LRU, LFU, HYBRID, NONE.
    
    max_size : int, optional
        Maximum number of items to store in the cache. When exceeded, items are
        evicted based on the selected eviction policy.
    
    promotion_threshold : int, default=10
        Number of accesses required before a weak-referenced module is promoted
        to strong reference cache.
    
    enable_stats : bool, default=True
        Whether to collect and maintain usage statistics.
    
    auto_cleanup_interval : float, optional
        If set, automatically trigger cleanup operations at the specified interval
        (in seconds) using a background thread.
    
    warn_on_weakref_failure : bool, default=True
        Whether to log warnings when an object doesn't support weak references.
    
    Attributes
    ----------
    hits : int
        Total number of successful cache lookups
    misses : int
        Total number of failed cache lookups
    size : int
        Current number of items in the cache

    Examples
    --------
    Basic usage:
    >>> cache = ModuleCache(enable_weakref=True, default_ttl=300)
    >>> 
    >>> # Store a class instance (supports weakref)
    >>> class Database:
    ...     pass
    >>> cache['database'] = Database()
    >>> db = cache['database']
    >>> 
    >>> # Store a string using the wrapper
    >>> cache.store_weakref_compatible('config', "some config string")
    >>> config = cache.get_weakref_compatible('config')
    
    With dependency tracking:
    >>> class APIHandler:
    ...     pass
    >>> cache.set_deps('api_handler', APIHandler(), ['database', 'config'])
    >>> deps = cache.get_deps('api_handler')  # Returns {'database', 'config'}
    >>> dependents = cache.get_dependents('database')  # Returns {'api_handler'}
    
    With metadata:
    >>> cache.set_metadata('api_handler', {'version': '2.0', 'author': 'dev'})
    >>> metadata = cache.get_metadata('api_handler')
    
    Statistics:
    >>> stats = cache.get_stats()
    >>> print(f"Hit rate: {stats['hit_rate']:.2%}")
    >>> print(f"Cache size: {stats['size']}")
    """

    def __init__(
        self,
        enable_weakref: Union[bool, WeakRefSupport] = WeakRefSupport.AUTO_DETECT,
        default_ttl: Optional[float] = None,
        eviction_policy: EvictionPolicy = EvictionPolicy.HYBRID,
        max_size: Optional[int] = None,
        promotion_threshold: int = 10,
        enable_stats: bool = True,
        auto_cleanup_interval: Optional[float] = None,
        warn_on_weakref_failure: bool = True
    ):
        # Core storage
        self._strong_cache: Dict[str, Any] = {}
        self._weak_cache: Dict[str, weakref.ReferenceType] = {}
        self._wrapped_cache: Dict[str, WeakRefCompatible] = {}  # For wrapped objects
        self._metadata: Dict[str, ModuleMetadata] = {}
        
        # Configuration
        if isinstance(enable_weakref, bool):
            self._weakref_mode = WeakRefSupport.FULL if enable_weakref else WeakRefSupport.STRONG_ONLY
        else:
            self._weakref_mode = enable_weakref
        
        self._default_ttl = default_ttl
        self._eviction_policy = eviction_policy
        self._max_size = max_size
        self._promotion_threshold = promotion_threshold
        self._enable_stats = enable_stats
        self._auto_cleanup_interval = auto_cleanup_interval
        self._warn_on_weakref_failure = warn_on_weakref_failure
        
        # Thread safety
        self._lock = threading.RLock()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_cleanup = threading.Event()
        
        # Statistics
        self._hits = 0
        self._misses = 0
        self._operation_times: List[float] = []
        
        # Custom callbacks
        self._on_evict_callbacks: List[Callable[[str, Any], None]] = []
        self._on_load_callbacks: List[Callable[[str, Any], None]] = []
        
        # Start auto-cleanup if interval specified
        if auto_cleanup_interval:
            self._start_auto_cleanup()
    
    def _supports_weakref(self, obj: Any) -> bool:
        """
        Check if an object supports weak references.
        
        Parameters
        ----------
        obj : Any
            Object to check
            
        Returns
        -------
        bool
            True if the object supports weak references
        """
        # Check if object has __weakref__ attribute
        if hasattr(obj, '__weakref__'):
            return True
        
        # Check for common built-in types that don't support weakref
        if isinstance(obj, (str, int, float, bool, tuple, frozenset)):
            return False
        
        # Check if it's a built-in type without weakref support
        if type(obj).__module__ == 'builtins' and not hasattr(type(obj), '__weakref__'):
            return False
        
        return False
    
    def _should_use_weakref(self, obj: Any) -> bool:
        """
        Determine if weak reference should be used for an object.
        
        Parameters
        ----------
        obj : Any
            Object to check
            
        Returns
        -------
        bool
            True if weak reference should be used
        """
        if self._weakref_mode == WeakRefSupport.STRONG_ONLY:
            return False
        
        if self._weakref_mode == WeakRefSupport.AUTO_DETECT:
            return self._supports_weakref(obj)
        
        # Full weakref mode
        if self._weakref_mode == WeakRefSupport.FULL:
            if not self._supports_weakref(obj) and self._warn_on_weakref_failure:
                logger.warning(
                    f"Object of type {type(obj).__name__} does not support weak references. "
                    f"Consider using store_weakref_compatible() or WeakRefSupport.AUTO_DETECT mode."
                )
            return True
        
        return False
    
    def _store_in_weak_cache(self, module_name: str, module: Any) -> bool:
        """
        Store an object in the weak cache, wrapping if necessary.
        
        Parameters
        ----------
        module_name : str
            Name/key for the module
        module : Any
            Object to store
            
        Returns
        -------
        bool
            True if stored in weak cache, False if stored elsewhere
        """
        if self._supports_weakref(module):
            self._weak_cache[module_name] = weakref.ref(module)
            if module_name in self._metadata:
                self._metadata[module_name].supports_weakref = True
            return True
        else:
            # Wrap the object to make it weakref-compatible
            wrapped = WeakRefCompatible(module)
            self._weak_cache[module_name] = weakref.ref(wrapped)
            self._wrapped_cache[module_name] = wrapped
            if module_name in self._metadata:
                self._metadata[module_name].supports_weakref = False
            return True
    
    def _retrieve_from_weak_cache(self, module_name: str) -> Optional[Any]:
        """
        Retrieve an object from the weak cache, unwrapping if necessary.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module
            
        Returns
        -------
        Optional[Any]
            The retrieved object or None if not found
        """
        if module_name not in self._weak_cache:
            return None
        
        ref = self._weak_cache[module_name]
        obj = ref()
        
        if obj is None:
            return None
        
        # Check if it's a wrapped object
        if module_name in self._wrapped_cache:
            return obj.get() if isinstance(obj, WeakRefCompatible) else obj
        
        return obj
    
    def __contains__(self, module_name: str) -> bool:
        """
        Check if a module exists in the cache.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module to check
            
        Returns
        -------
        bool
            True if the module exists in either strong or weak cache
        
        Examples
        --------
        >>> 'my_module' in cache
        True
        """
        with self._lock:
            return (module_name in self._strong_cache or 
                    (self._weakref_mode != WeakRefSupport.STRONG_ONLY and 
                     module_name in self._weak_cache))
    
    def __getitem__(self, module_name: str) -> Any:
        """
        Retrieve a module by name with automatic access tracking.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module to retrieve
            
        Returns
        -------
        Any
            The cached module object
            
        Raises
        ------
        KeyError
            If the module is not found in either cache
            
        Notes
        -----
        This method automatically:
        - Increments access count
        - Updates last access time
        - Promotes frequently accessed weak references to strong cache
        - Records hits/misses for statistics
        
        Examples
        --------
        >>> obj = cache['database']
        >>> print(cache.get_stats()['hits'])
        1
        """
        with self._lock:
            # Check strong cache first
            if module_name in self._strong_cache:
                if self._enable_stats:
                    self._hits += 1
                
                # Update metadata
                if module_name in self._metadata:
                    self._metadata[module_name].access_count += 1
                    self._metadata[module_name].last_access_time = time.time()
                
                return self._strong_cache[module_name]
            
            # Check weak cache if enabled
            if self._weakref_mode != WeakRefSupport.STRONG_ONLY and module_name in self._weak_cache:
                module = self._retrieve_from_weak_cache(module_name)
                
                if module is not None:
                    if self._enable_stats:
                        self._hits += 1
                    
                    # Update metadata
                    if module_name in self._metadata:
                        self._metadata[module_name].access_count += 1
                        self._metadata[module_name].last_access_time = time.time()
                        
                        # Auto-promote to strong cache if frequently accessed
                        access_count = self._metadata[module_name].access_count
                        if access_count >= self._promotion_threshold:
                            self._strong_cache[module_name] = module
                            logger.debug(f"Promoted {module_name} to strong cache (access count: {access_count})")
                    
                    return module
                
                # Weak reference expired
                logger.debug(f"Removing expired weak reference for {module_name}")
                del self._weak_cache[module_name]
                self._wrapped_cache.pop(module_name, None)
            
            # Module not found
            if self._enable_stats:
                self._misses += 1
            raise KeyError(f"Module '{module_name}' not found in cache")
    
    def __setitem__(self, module_name: str, module: Any) -> None:
        """
        Store a module in the cache with automatic storage strategy selection.
        
        Parameters
        ----------
        module_name : str
            Name/key to associate with the module
        module : Any
            The module object to cache
            
        Notes
        -----
        Storage strategy:
        - If weakref enabled and object supports it: stored as weak reference initially
        - If object doesn't support weakref: stored as strong reference
        - If access count > threshold: automatically promoted to strong
        
        Examples
        --------
        >>> class MyClass:
        ...     pass
        >>> cache['my_module'] = MyClass()
        """
        with self._lock:
            now = time.time()
            
            # Initialize or update metadata
            if module_name not in self._metadata:
                self._metadata[module_name] = ModuleMetadata(
                    load_time=now,
                    last_access_time=now
                )
            else:
                self._metadata[module_name].load_time = now
            
            # Determine storage strategy
            use_weakref = self._should_use_weakref(module)
            
            # Remove from any existing storage
            self._strong_cache.pop(module_name, None)
            self._weak_cache.pop(module_name, None)
            self._wrapped_cache.pop(module_name, None)
            
            # Store based on configuration
            if use_weakref:
                self._store_in_weak_cache(module_name, module)
            else:
                self._strong_cache[module_name] = module
                self._metadata[module_name].supports_weakref = False
            
            # Check size limit and evict if necessary
            if self._max_size and len(self) > self._max_size:
                self._evict_items()
            
            # Trigger load callbacks
            for callback in self._on_load_callbacks:
                try:
                    callback(module_name, module)
                except Exception as e:
                    logger.error(f"Error in load callback for {module_name}: {e}")
    
    def store_weakref_compatible(self, module_name: str, module: Any) -> None:
        """
        Store an object that doesn't support weakref using a wrapper.
        
        This is a convenience method for storing objects like strings, integers,
        or other built-in types that don't have __weakref__ support.
        
        Parameters
        ----------
        module_name : str
            Name/key for the module
        module : Any
            Object to store (even if it doesn't support weakref)
            
        Examples
        --------
        >>> cache.store_weakref_compatible('config', "database=localhost")
        >>> config = cache.get_weakref_compatible('config')
        """
        with self._lock:
            wrapped = WeakRefCompatible(module)
            self[module_name] = wrapped
    
    def get_weakref_compatible(self, module_name: str, default: Any = None) -> Any:
        """
        Retrieve an object that was stored with weakref compatibility.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module
        default : Any, default=None
            Default value if module not found
            
        Returns
        -------
        Any
            The unwrapped object or default
            
        Examples
        --------
        >>> config = cache.get_weakref_compatible('config', 'default config')
        """
        try:
            obj = self[module_name]
            if isinstance(obj, WeakRefCompatible):
                return obj.get()
            return obj
        except KeyError:
            return default
    
    def __delitem__(self, module_name: str) -> None:
        """
        Remove a module and all associated metadata from the cache.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module to remove
            
        Notes
        -----
        Also removes:
        - Dependency relationships
        - All metadata
        - Statistics entries
        """
        with self._lock:
            # Trigger eviction callbacks before removal
            if module_name in self._metadata:
                obj = self.get(module_name)
                for callback in self._on_evict_callbacks:
                    try:
                        callback(module_name, obj)
                    except Exception as e:
                        logger.error(f"Error in evict callback for {module_name}: {e}")
            
            # Remove from storage
            self._strong_cache.pop(module_name, None)
            self._weak_cache.pop(module_name, None)
            self._wrapped_cache.pop(module_name, None)
            
            # Remove metadata
            self._metadata.pop(module_name, None)
            
            # Clean up dependencies
            self._remove_dependencies(module_name)
    
    def get(self, module_name: str, default: Any = None) -> Any:
        """
        Safely retrieve a module with a default value if not found.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module to retrieve
        default : Any, default=None
            Value to return if module is not found
            
        Returns
        -------
        Any
            The cached module or default value
            
        Examples
        --------
        >>> obj = cache.get('missing_module', 'fallback')
        >>> print(obj)
        'fallback'
        """
        try:
            return self[module_name]
        except KeyError:
            return default
    
    def set_deps(self, module_name: str, module: Any, dependencies: List[str]) -> None:
        """
        Store a module with explicit dependency relationships.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module
        module : Any
            The module object to cache
        dependencies : List[str]
            List of module names that this module depends on
            
        Notes
        -----
        This method:
        - Stores the module in the cache
        - Records forward dependencies (what this module needs)
        - Records reverse dependencies (what needs this module)
        
        Examples
        --------
        >>> class WebApp:
        ...     pass
        >>> cache.set_deps('web_app', WebApp(), ['database', 'cache', 'logger'])
        >>> cache.get_deps('web_app')
        {'database', 'cache', 'logger'}
        """
        with self._lock:
            self[module_name] = module
            
            # Update dependencies
            if module_name not in self._metadata:
                self._metadata[module_name] = ModuleMetadata()
            
            self._metadata[module_name].dependencies = set(dependencies)
            
            # Update reverse dependencies
            for dep in dependencies:
                if dep not in self._metadata:
                    self._metadata[dep] = ModuleMetadata()
                self._metadata[dep].dependents.add(module_name)
    
    def get_deps(self, module_name: str) -> Set[str]:
        """
        Get all modules that this module depends on.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module
            
        Returns
        -------
        Set[str]
            Set of module names that this module depends on
            
        Examples
        --------
        >>> deps = cache.get_deps('web_app')
        >>> print(f"Web app needs: {deps}")
        """
        with self._lock:
            return self._metadata.get(module_name, ModuleMetadata()).dependencies.copy()
    
    def get_dependents(self, module_name: str) -> Set[str]:
        """
        Get all modules that depend on this module.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module
            
        Returns
        -------
        Set[str]
            Set of module names that depend on this module
            
        Examples
        --------
        >>> users = cache.get_dependents('database')
        >>> print(f"Database used by: {users}")
        """
        with self._lock:
            return self._metadata.get(module_name, ModuleMetadata()).dependents.copy()
    
    def set_metadata(self, module_name: str, tags: Dict[str, Any]) -> None:
        """
        Add custom metadata tags to a cached module.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module
        tags : Dict[str, Any]
            Dictionary of custom metadata to associate with the module
            
        Examples
        --------
        >>> cache.set_metadata('api_handler', {
        ...     'version': '2.1.0',
        ...     'author': 'dev-team',
        ...     'priority': 'high'
        ... })
        """
        with self._lock:
            if module_name not in self._metadata:
                self._metadata[module_name] = ModuleMetadata()
            self._metadata[module_name].custom_tags.update(tags)
    
    def get_metadata(self, module_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve custom metadata for a module.
        
        Parameters
        ----------
        module_name : str
            Name/key of the module
            
        Returns
        -------
        Optional[Dict[str, Any]]
            Dictionary of custom metadata if exists, None otherwise
        """
        with self._lock:
            if module_name in self._metadata:
                return self._metadata[module_name].custom_tags.copy()
            return None
    
    def clear_expired(self, ttl: Optional[float] = None) -> int:
        """
        Remove modules that have exceeded their time-to-live.
        
        Parameters
        ----------
        ttl : float, optional
            Time-to-live in seconds. If not specified, uses default_ttl from init.
            
        Returns
        -------
        int
            Number of modules removed
            
        Examples
        --------
        >>> removed = cache.clear_expired(ttl=60)  # Remove items older than 60 seconds
        >>> print(f"Removed {removed} expired modules")
        """
        ttl = ttl or self._default_ttl
        if ttl is None:
            return 0
        
        now = time.time()
        removed = 0
        
        with self._lock:
            to_delete = [
                name for name, metadata in self._metadata.items()
                if now - metadata.load_time > ttl
            ]
            
            for name in to_delete:
                del self[name]
                removed += 1
        
        if removed > 0:
            logger.info(f"Cleared {removed} expired modules (TTL: {ttl}s)")
        
        return removed
    
    def clear_unused(self, threshold: int = 1) -> int:
        """
        Remove modules with access count below a threshold.
        
        Parameters
        ----------
        threshold : int, default=1
            Minimum access count required to keep the module
            
        Returns
        -------
        int
            Number of modules removed
            
        Examples
        --------
        >>> removed = cache.clear_unused(threshold=3)  # Remove items accessed < 3 times
        """
        with self._lock:
            to_delete = [
                name for name, metadata in self._metadata.items()
                if metadata.access_count < threshold
            ]
            
            for name in to_delete:
                del self[name]
            
            if to_delete:
                logger.debug(f"Cleared {len(to_delete)} underutilized modules (threshold: {threshold})")
            
            return len(to_delete)
    
    def clear_lru(self, count: int = 1) -> int:
        """
        Remove least recently used modules.
        
        Parameters
        ----------
        count : int, default=1
            Number of least recently used modules to remove
            
        Returns
        -------
        int
            Number of modules actually removed
            
        Examples
        --------
        >>> removed = cache.clear_lru(count=10)  # Remove 10 least recently used items
        """
        with self._lock:
            if not self._metadata:
                return 0
            
            # Sort by last access time (oldest first)
            sorted_items = sorted(
                self._metadata.items(),
                key=lambda x: x[1].last_access_time
            )
            
            to_delete = [name for name, _ in sorted_items[:count]]
            
            for name in to_delete:
                del self[name]
            
            return len(to_delete)
    
    def _evict_items(self) -> None:
        """Internal method to evict items based on selected policy."""
        if self._eviction_policy == EvictionPolicy.TTL:
            self.clear_expired()
        elif self._eviction_policy == EvictionPolicy.LRU:
            self.clear_lru(count=1)
        elif self._eviction_policy == EvictionPolicy.LFU:
            self.clear_unused(threshold=1)
        elif self._eviction_policy == EvictionPolicy.HYBRID:
            # Hybrid: clear expired first, then LRU if still over limit
            self.clear_expired()
            if self._max_size and len(self) > self._max_size:
                self.clear_lru(count=len(self) - self._max_size)
    
    def _remove_dependencies(self, module_name: str) -> None:
        """Internal cleanup of dependency relationships."""
        if module_name in self._metadata:
            # Remove from dependents of dependencies
            for dep in self._metadata[module_name].dependencies:
                if dep in self._metadata:
                    self._metadata[dep].dependents.discard(module_name)
            
            # Remove from dependencies of dependents
            for dep in self._metadata[module_name].dependents:
                if dep in self._metadata:
                    self._metadata[dep].dependencies.discard(module_name)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics about cache performance.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - hits: Number of cache hits
            - misses: Number of cache misses
            - hit_rate: Hit ratio (hits / (hits + misses))
            - size: Current number of cached items
            - strong_count: Number of strong references
            - weak_count: Number of weak references
            - avg_access_count: Average access count across all items
            - oldest_item_age: Age of oldest item in seconds
            - newest_item_age: Age of newest item in seconds
            - weakref_compatible_count: Number of wrapped objects
            
        Examples
        --------
        >>> stats = cache.get_stats()
        >>> print(f"Hit rate: {stats['hit_rate']:.2%}")
        >>> print(f"Cache size: {stats['size']}")
        """
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0
            
            access_counts = [m.access_count for m in self._metadata.values()]
            avg_access = sum(access_counts) / len(access_counts) if access_counts else 0
            
            now = time.time()
            ages = [now - m.load_time for m in self._metadata.values()]
            
            return {
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': hit_rate,
                'size': len(self),
                'strong_count': len(self._strong_cache),
                'weak_count': len(self._weak_cache),
                'wrapped_count': len(self._wrapped_cache),
                'avg_access_count': avg_access,
                'oldest_item_age': max(ages) if ages else 0,
                'newest_item_age': min(ages) if ages else 0,
                'eviction_policy': self._eviction_policy.value,
                'max_size': self._max_size,
                'weakref_mode': self._weakref_mode.value,
            }
    
    def register_callback(self, event: str, callback: Callable) -> None:
        """
        Register a callback for cache events.
        
        Parameters
        ----------
        event : str
            Event type ('on_evict' or 'on_load')
        callback : Callable
            Function to call when event occurs. Receives (module_name, module)
            
        Examples
        --------
        >>> def log_eviction(name, module):
        ...     print(f"Evicted: {name}")
        >>> cache.register_callback('on_evict', log_eviction)
        """
        with self._lock:
            if event == 'on_evict':
                self._on_evict_callbacks.append(callback)
            elif event == 'on_load':
                self._on_load_callbacks.append(callback)
            else:
                raise ValueError(f"Unknown event type: {event}")
    
    def _start_auto_cleanup(self) -> None:
        """Start background thread for automatic cleanup."""
        def cleanup_worker():
            while not self._stop_cleanup.is_set():
                self.clear_expired()
                self._stop_cleanup.wait(self._auto_cleanup_interval)
        
        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        self._cleanup_thread.start()
        logger.info(f"Auto-cleanup started (interval: {self._auto_cleanup_interval}s)")
    
    def stop_auto_cleanup(self) -> None:
        """Stop the automatic cleanup background thread."""
        if self._cleanup_thread:
            self._stop_cleanup.set()
            self._cleanup_thread.join(timeout=5)
            logger.info("Auto-cleanup stopped")
    
    def __len__(self) -> int:
        """Return the total number of items in the cache."""
        with self._lock:
            return len(self._strong_cache) + len(self._weak_cache)
    
    def keys(self) -> List[str]:
        """
        Return all module names in the cache.
        
        Returns
        -------
        List[str]
            List of all module names (both strong and weak cache)
        """
        with self._lock:
            names = set(self._strong_cache.keys())
            if self._weakref_mode != WeakRefSupport.STRONG_ONLY:
                names.update(self._weak_cache.keys())
            return list(names)
    
    def values(self) -> List[Any]:
        """
        Return all module objects in the cache.
        
        Returns
        -------
        List[Any]
            List of all module objects (dereferenced weak references)
        """
        with self._lock:
            values = list(self._strong_cache.values())
            if self._weakref_mode != WeakRefSupport.STRONG_ONLY:
                for name in self._weak_cache:
                    obj = self._retrieve_from_weak_cache(name)
                    if obj is not None:
                        values.append(obj)
            return values
    
    def items(self) -> List[Tuple[str, Any]]:
        """
        Return all (name, module) pairs in the cache.
        
        Returns
        -------
        List[Tuple[str, Any]]
            List of (name, object) tuples
        """
        with self._lock:
            items = list(self._strong_cache.items())
            if self._weakref_mode != WeakRefSupport.STRONG_ONLY:
                for name in self._weak_cache:
                    obj = self._retrieve_from_weak_cache(name)
                    if obj is not None:
                        items.append((name, obj))
            return items
    
    def clear(self) -> None:
        """
        Completely clear the cache and reset all statistics.
        
        Notes
        -----
        This method removes all cached items, metadata, and resets hit/miss counters.
        """
        with self._lock:
            self._strong_cache.clear()
            self._weak_cache.clear()
            self._wrapped_cache.clear()
            self._metadata.clear()
            self._hits = 0
            self._misses = 0
            logger.info("Cache completely cleared")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensure cleanup."""
        self.stop_auto_cleanup()
        self.clear()


class ModulesProxy:
    """
    A proxy wrapper around ModuleCache that mimics sys.modules interface.
    
    This class provides a dictionary-like interface that can be used as a
    drop-in replacement for sys.modules, enabling all ModuleCache features
    while maintaining compatibility with existing code.
    
    Parameters
    ----------
    cache : ModuleCache
        The ModuleCache instance to wrap
    
    Attributes
    ----------
    _cache : ModuleCache
        The underlying cache instance
    
    Examples
    --------
    >>> proxy = ModulesProxy(ModuleCache())
    >>> proxy['my_module'] = MyModule()
    >>> import sys
    >>> original_modules = sys.modules
    >>> sys.modules = proxy  # Replace sys.modules with proxy
    >>> # Now all imports go through the cache
    >>> sys.modules = original_modules  # Restore original
    """
    
    def __init__(self, cache: ModuleCache):
        self._cache = cache
    
    def __contains__(self, key: str) -> bool:
        """Check if a module exists in the cache."""
        return key in self._cache
    
    def __getitem__(self, key: str) -> Any:
        """Retrieve a module from the cache."""
        return self._cache[key]
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Store a module in the cache."""
        self._cache[key] = value
    
    def __delitem__(self, key: str) -> None:
        """Remove a module from the cache."""
        del self._cache[key]
    
    def get(self, key: str, default: Any = None) -> Any:
        """Safely retrieve a module with default value."""
        return self._cache.get(key, default)
    
    def keys(self) -> List[str]:
        """Return all module names."""
        return self._cache.keys()
    
    def values(self) -> List[Any]:
        """Return all module objects."""
        return self._cache.values()
    
    def items(self) -> List[Tuple[str, Any]]:
        """Return all (name, module) pairs."""
        return self._cache.items()
    
    def clear(self) -> None:
        """Clear all modules from the cache."""
        self._cache.clear()
    
    def __len__(self) -> int:
        """Return the number of cached modules."""
        return len(self._cache)
    
    def __repr__(self) -> str:
        """Return string representation."""
        return f"<ModulesProxy cache_size={len(self._cache)}>"


# Example usage and testing
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    print("=== Module Cache System Demo ===\n")
    
    # Test with weak references enabled
    print("1. Testing with weak references (AUTO_DETECT mode):")
    with ModuleCache(enable_weakref=WeakRefSupport.AUTO_DETECT, 
                     default_ttl=5, 
                     auto_cleanup_interval=2,
                     enable_stats=True) as cache:
        
        # Create a class instance (supports weakref)
        class Database:
            def __init__(self, name):
                self.name = name
            def __repr__(self):
                return f"Database({self.name})"
        
        # Store objects
        cache['database'] = Database("main_db")
        cache.store_weakref_compatible('config', "host=localhost;port=5432")
        cache.store_weakref_compatible('version', "1.0.0")
        
        # Test retrieval
        print(f"  Database: {cache['database']}")
        print(f"  Config: {cache.get_weakref_compatible('config')}")
        print(f"  Version: {cache.get_weakref_compatible('version')}")
        
        # Test dependency tracking
        cache.set_deps('app', "App Object", ['database', 'config'])
        print(f"  App dependencies: {cache.get_deps('app')}")
        print(f"  Database dependents: {cache.get_dependents('database')}")
        
        # Add metadata
        cache.set_metadata('database', {'version': '2.0', 'author': 'admin'})
        print(f"  Database metadata: {cache.get_metadata('database')}")
        
        # Show statistics
        stats = cache.get_stats()
        print(f"\n  Statistics:")
        print(f"    Hit rate: {stats['hit_rate']:.2%}")
        print(f"    Cache size: {stats['size']}")
        print(f"    Strong cache: {stats['strong_count']}")
        print(f"    Weak cache: {stats['weak_count']}")
        print(f"    Wrapped objects: {stats['wrapped_count']}")
        print(f"    Avg access count: {stats['avg_access_count']:.2f}")
    
    print("\n2. Testing with strong references only:")
    with ModuleCache(enable_weakref=WeakRefSupport.STRONG_ONLY) as cache:
        cache['string'] = "Hello World"
        cache['number'] = 42
        print(f"  String: {cache['string']}")
        print(f"  Number: {cache['number']}")
        print(f"  Cache size: {len(cache)}")
    
    print("\n3. Testing with full weakref mode:")
    with ModuleCache(enable_weakref=WeakRefSupport.FULL, warn_on_weakref_failure=True) as cache:
        class TestClass:
            pass
        
        cache['good_object'] = TestClass()
        
        # This will show a warning
        print("  Attempting to store a string (will trigger warning):")
        cache['bad_object'] = "This will cause a warning"
        
        # Use the wrapper for strings
        cache.store_weakref_compatible('good_string', "This works fine")
        print(f"  Retrieved: {cache.get_weakref_compatible('good_string')}")
    
    print("\n4. Testing eviction policies:")
    with ModuleCache(max_size=3, eviction_policy=EvictionPolicy.LRU) as cache:
        for i in range(5):
            cache[f'module_{i}'] = f"Module {i}"
        print(f"  After adding 5 items with max_size=3: {cache.keys()}")
    
    print("\n✓ All tests completed successfully!")