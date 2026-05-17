#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Caching system for imported modules.
"""

from typing import Dict, Optional, Any
import types
import threading
from datetime import datetime, timedelta
import hashlib
import json


class ImportCache:
    """
    Thread-safe cache for imported modules with expiration support.
    
    This class manages caching of imported modules to prevent redundant
    imports and improve performance.
    
    Attributes
    ----------
    _cache : Dict[str, types.ModuleType]
        Main cache storage.
    _timestamps : Dict[str, datetime]
        Timestamps for cache entries.
    _lock : threading.RLock
        Lock for thread-safe operations.
    """
    
    def __init__(self):
        """Initialize empty cache with thread lock."""
        self._cache: Dict[str, types.ModuleType] = {}
        self._timestamps: Dict[str, datetime] = {}
        self._lock = threading.RLock()
    
    def get(self, key: str, max_age: Optional[timedelta] = None) -> Optional[types.ModuleType]:
        """
        Get module from cache if available and not expired.
        
        Parameters
        ----------
        key : str
            Cache key (usually module name + optional attribute).
        max_age : timedelta, optional
            Maximum age of cache entry. None means no expiration.
        
        Returns
        -------
        Optional[types.ModuleType]
            Cached module or None if not found/expired.
        """
        with self._lock:
            if key not in self._cache:
                return None
            
            # Check expiration
            if max_age is not None:
                age = datetime.now() - self._timestamps[key]
                if age > max_age:
                    del self._cache[key]
                    del self._timestamps[key]
                    return None
            
            return self._cache[key]
    
    def set(self, key: str, module: types.ModuleType) -> None:
        """
        Store module in cache.
        
        Parameters
        ----------
        key : str
            Cache key.
        module : types.ModuleType
            Module to cache.
        """
        with self._lock:
            self._cache[key] = module
            self._timestamps[key] = datetime.now()
    
    def has(self, key: str) -> bool:
        """
        Check if key exists in cache.
        
        Parameters
        ----------
        key : str
            Cache key.
        
        Returns
        -------
        bool
            True if key exists.
        """
        with self._lock:
            return key in self._cache
    
    def invalidate(self, key: Optional[str] = None) -> None:
        """
        Invalidate cache entries.
        
        Parameters
        ----------
        key : str, optional
            Specific key to invalidate. If None, invalidate all.
        """
        with self._lock:
            if key is None:
                self._cache.clear()
                self._timestamps.clear()
            elif key in self._cache:
                del self._cache[key]
                del self._timestamps[key]
    
    def get_cache_key(self, module_name: str, attr: Optional[str] = None) -> str:
        """
        Generate cache key from module name and optional attribute.
        
        Parameters
        ----------
        module_name : str
            Module name.
        attr : str, optional
            Attribute name.
        
        Returns
        -------
        str
            Cache key.
        """
        return f"{module_name}.{attr}" if attr else module_name
    
    def get_file_cache_key(self, file_path: str) -> str:
        """
        Generate cache key for file-based imports including file hash.
        
        Parameters
        ----------
        file_path : str
            Path to file.
        
        Returns
        -------
        str
            Cache key with file hash for change detection.
        """
        # Add file hash to key to detect changes
        file_hash = self._get_file_hash(file_path)
        return f"file:{file_path}:{file_hash}"
    
    def _get_file_hash(self, file_path: str) -> str:
        """
        Calculate hash of file contents.
        
        Parameters
        ----------
        file_path : str
            Path to file.
        
        Returns
        -------
        str
            MD5 hash of file contents.
        """
        try:
            with open(file_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except (IOError, OSError):
            return ""


# Global cache instance
_global_cache = ImportCache()


def get_cache() -> ImportCache:
    """Get the global cache instance."""
    return _global_cache


def cached_import(func):
    """
    Decorator to cache import results.
    
    Parameters
    ----------
    func : callable
        Import function to wrap.
    
    Returns
    -------
    callable
        Wrapped function with caching.
    """
    @functools.wraps(func)
    def wrapper(module_name, *args, **kwargs):
        cache = get_cache()
        key = cache.get_cache_key(module_name)
        
        # Check if reload is requested
        reload = kwargs.get('reload', False)
        if reload:
            cache.invalidate(key)
        
        # Try cache
        cached = cache.get(key)
        if cached is not None:
            return cached
        
        # Execute import
        result = func(module_name, *args, **kwargs)
        
        # Cache result
        if result is not None and not kwargs.get('lazy', False):
            cache.set(key, result)
        
        return result
    
    return wrapper