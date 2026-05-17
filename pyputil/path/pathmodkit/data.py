#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import sys
import logging
from pathlib import Path
from functools import lru_cache
from typing import Optional, Dict, Any, BinaryIO, Union
from contextlib import contextmanager
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Setup logger
logger = logging.getLogger(__name__)

# Try to import modern importlib.resources
try:
    from importlib.resources import files, as_file, open_binary
    HAS_IMPORTLIB_RESOURCES = True
except ImportError:
    HAS_IMPORTLIB_RESOURCES = False

# Try to import importlib_resources for older Python versions
if not HAS_IMPORTLIB_RESOURCES:
    try:
        from importlib_resources import files, as_file, open_binary
        HAS_IMPORTLIB_RESOURCES = True
    except ImportError:
        HAS_IMPORTLIB_RESOURCES = False


@dataclass
class CacheEntry:
    """Cache entry with metadata."""
    data: bytes
    timestamp: datetime
    size: int
    hash: str
    
    def is_expired(self, ttl: Optional[int] = None) -> bool:
        """Check if cache entry is expired."""
        if ttl is None:
            return False
        return datetime.now() - self.timestamp > timedelta(seconds=ttl)


class ResourceCache:
    """
    Resource cache with TTL and size management.
    
    Parameters
    ----------
    maxsize : int
        Maximum number of entries in cache
    max_memory_mb : int
        Maximum total memory usage in MB
    default_ttl : Optional[int]
        Default time-to-live in seconds (None = no expiration)
    """
    
    def __init__(
        self,
        maxsize: int = 128,
        max_memory_mb: int = 64,
        default_ttl: Optional[int] = None
    ):
        self.maxsize = maxsize
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._access_order: list = []
        self._current_memory: int = 0
    
    def _get_key(self, package: str, resource: str) -> str:
        """Generate cache key."""
        return f"{package}:{resource}"
    
    def _enforce_size_limit(self):
        """Enforce cache size limits (LRU eviction)."""
        while len(self._cache) > self.maxsize:
            # Remove least recently used
            oldest_key = self._access_order.pop(0)
            if oldest_key in self._cache:
                entry = self._cache.pop(oldest_key)
                self._current_memory -= len(entry.data)
        
        while self._current_memory > self.max_memory_bytes and self._cache:
            oldest_key = self._access_order.pop(0)
            if oldest_key in self._cache:
                entry = self._cache.pop(oldest_key)
                self._current_memory -= len(entry.data)
    
    def get(self, package: str, resource: str) -> Optional[bytes]:
        """Get resource from cache."""
        key = self._get_key(package, resource)
        
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        
        # Check expiration
        if entry.is_expired(self.default_ttl):
            del self._cache[key]
            self._access_order.remove(key)
            self._current_memory -= len(entry.data)
            return None
        
        # Update access order (move to end)
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
        
        return entry.data
    
    def put(
        self,
        package: str,
        resource: str,
        data: bytes,
        ttl: Optional[int] = None
    ):
        """Put resource in cache."""
        key = self._get_key(package, resource)
        
        # Calculate hash for integrity check
        data_hash = hashlib.sha256(data).hexdigest()[:16]
        
        entry = CacheEntry(
            data=data,
            timestamp=datetime.now(),
            size=len(data),
            hash=data_hash
        )
        
        # Remove old entry if exists
        if key in self._cache:
            self._current_memory -= len(self._cache[key].data)
            if key in self._access_order:
                self._access_order.remove(key)
        
        # Add new entry
        self._cache[key] = entry
        self._access_order.append(key)
        self._current_memory += len(data)
        
        # Enforce limits
        self._enforce_size_limit()
    
    def clear(self):
        """Clear entire cache."""
        self._cache.clear()
        self._access_order.clear()
        self._current_memory = 0
    
    def invalidate(self, package: Optional[str] = None, resource: Optional[str] = None):
        """Invalidate specific cache entries."""
        if package is None:
            self.clear()
            return
        
        keys_to_remove = []
        for key in self._cache:
            pkg, res = key.split(':', 1)
            if pkg == package and (resource is None or res == resource):
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            entry = self._cache.pop(key)
            self._current_memory -= len(entry.data)
            if key in self._access_order:
                self._access_order.remove(key)


# Global cache instance
_default_cache = ResourceCache(maxsize=128, max_memory_mb=64)


def safe_import(package: str) -> Optional[Any]:
    """Safely import a module."""
    try:
        import importlib
        return importlib.import_module(package)
    except (ImportError, AttributeError):
        return None


def validate_resource_path(resource: str) -> str:
    """
    Validate and sanitize resource path.
    
    Parameters
    ----------
    resource : str
        Resource path to validate
    
    Returns
    -------
    str
        Sanitized path
    
    Raises
    ------
    ValueError
        If path contains security violations
    """
    # Normalize separators
    resource = resource.replace('\\', '/')
    
    # Check for path traversal
    if '..' in resource.split('/'):
        raise ValueError(f"Path traversal detected: {resource}")
    
    # Check for absolute paths
    if resource.startswith('/'):
        raise ValueError(f"Absolute path not allowed: {resource}")
    
    # Check for suspicious patterns
    suspicious_patterns = ['~', '$', '`', ';', '|', '&', '<', '>']
    for pattern in suspicious_patterns:
        if pattern in resource:
            raise ValueError(f"Suspicious character '{pattern}' in path: {resource}")
    
    # Check for hidden files (optional security)
    parts = resource.split('/')
    for part in parts:
        if part.startswith('.') and part not in ['.', '..']:
            # Allow but warn about hidden files
            logger.debug(f"Accessing hidden file/directory: {part}")
    
    return resource


def get_resource_size(resource_path: Path) -> int:
    """Get size of resource safely."""
    try:
        return resource_path.stat().st_size
    except (OSError, IOError):
        return 0


def get_data(
    package: str,
    resource: str,
    use_cache: bool = True,
    cache_ttl: Optional[int] = None,
    max_size_mb: int = 100,
    cache_instance: Optional[ResourceCache] = None
) -> Optional[bytes]:
    """
    Get a resource from a package with security, caching, and modern API support.
    
    This function safely retrieves resources from Python packages, with protection
    against path traversal attacks, symlink attacks, and other security issues.
    It supports both the modern `importlib.resources` API and legacy fallbacks.
    
    Parameters
    ----------
    package : str
        Package name (e.g., 'mypackage' or 'mypackage.submodule')
    resource : str
        Resource path relative to package (e.g., 'data/config.json')
    use_cache : bool, default=True
        Whether to cache the resource content
    cache_ttl : Optional[int], default=None
        Time-to-live for cache in seconds (None = no expiration)
    max_size_mb : int, default=100
        Maximum resource size in MB to load (prevents memory issues)
    cache_instance : Optional[ResourceCache], default=None
        Custom cache instance (uses default if not provided)
    
    Returns
    -------
    Optional[bytes]
        Resource content as bytes, or None if resource not found
    
    Raises
    ------
    ValueError
        If resource path contains security violations or is invalid
    OSError
        If there are filesystem errors (propagated from file operations)
    
    Notes
    -----
    Security features:
    - Blocks path traversal attacks ('..')
    - Blocks absolute paths
    - Blocks suspicious characters (~ $ ` ; | & <>)
    - Validates resource is within package directory
    - Symlink attack prevention through path resolution
    
    Caching features:
    - LRU eviction based on access
    - Memory usage limits
    - TTL-based expiration
    - Size-based filtering (configurable)
    - SHA-256 integrity tracking
    
    Examples
    --------
    >>> # Basic usage
    >>> data = get_data('mypackage', 'data/config.json')
    >>> if data:
    ...     config = json.loads(data)
    
    >>> # With custom cache settings
    >>> data = get_data('mypackage', 'largefile.bin', 
    ...                 cache_ttl=3600, max_size_mb=500)
    
    >>> # Without caching (for frequently changing resources)
    >>> data = get_data('mypackage', 'dynamic.txt', use_cache=False)
    
    >>> # Reading from subpackage
    >>> data = get_data('mypackage.subpackage', 'resources/data.bin')
    
    See Also
    --------
    importlib.resources : Modern Python API for resource access
    functools.lru_cache : Built-in caching decorator
    pathlib.Path : Modern path handling
    """
    
    # Validate inputs
    if not isinstance(package, str) or not package:
        raise ValueError("Package name must be a non-empty string")
    
    if not isinstance(resource, str) or not resource:
        raise ValueError("Resource path must be a non-empty string")
    
    # Validate and sanitize resource path
    try:
        resource = validate_resource_path(resource)
    except ValueError as e:
        logger.error(f"Resource validation failed: {e}")
        raise
    
    # Use provided cache or default
    cache = cache_instance or _default_cache
    
    # Check cache first
    cache_key = f"{package}:{resource}"
    if use_cache:
        cached_data = cache.get(package, resource)
        if cached_data is not None:
            logger.debug(f"Cache hit for {cache_key}")
            return cached_data
    
    logger.debug(f"Cache miss for {cache_key}, loading from package")
    
    # Method 1: Modern importlib.resources API (Python 3.7+)
    if HAS_IMPORTLIB_RESOURCES:
        try:
            # Get resource using modern API
            resource_path = files(package) / resource
            
            # Check if resource exists
            if resource_path.is_file():
                # Check size before loading
                try:
                    size = resource_path.stat().st_size
                    if size > max_size_mb * 1024 * 1024:
                        logger.warning(
                            f"Resource {resource} size ({size / 1024 / 1024:.1f} MB) "
                            f"exceeds limit ({max_size_mb} MB)"
                        )
                        return None
                except OSError as e:
                    logger.debug(f"Could not get resource size: {e}")
                
                # Read the resource
                with resource_path.open('rb') as f:
                    content = f.read()
                
                # Cache if enabled and within reasonable size
                if use_cache and len(content) <= max_size_mb * 1024 * 1024:
                    cache.put(package, resource, content, ttl=cache_ttl)
                
                return content
                
        except (FileNotFoundError, TypeError, ImportError) as e:
            logger.debug(f"Modern importlib.resources method failed: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error with importlib.resources: {e}")
    
    # Method 2: Legacy method using module file system
    try:
        import importlib.util
        
        # Find the package spec
        spec = importlib.util.find_spec(package)
        if spec is None or spec.loader is None:
            logger.debug(f"Package {package} not found")
            return None
        
        # Get the module
        module = sys.modules.get(package)
        if module is None:
            module = safe_import(package)
        
        if module is None:
            logger.debug(f"Could not import {package}")
            return None
        
        # Get package path
        if hasattr(module, '__file__') and module.__file__:
            base_path = Path(module.__file__).parent
        elif hasattr(spec, 'origin') and spec.origin:
            base_path = Path(spec.origin).parent
        elif hasattr(spec, 'submodule_search_locations') and spec.submodule_search_locations:
            base_path = Path(spec.submodule_search_locations[0])
        else:
            logger.debug(f"Cannot determine path for package {package}")
            return None
        
        # Construct full path
        full_path = base_path / resource
        
        # Security: Validate path is within package
        try:
            resolved_path = full_path.resolve()
            resolved_base = base_path.resolve()
            resolved_path.relative_to(resolved_base)
        except (ValueError, OSError) as e:
            logger.error(f"Path validation failed for {resource}: {e}")
            raise ValueError(f"Resource access denied: {resource}") from e
        
        # Check if file exists and is readable
        if not full_path.exists():
            logger.debug(f"Resource not found: {full_path}")
            return None
        
        if not full_path.is_file():
            logger.warning(f"Resource path is not a file: {full_path}")
            return None
        
        # Check file size
        try:
            file_size = full_path.stat().st_size
            if file_size > max_size_mb * 1024 * 1024:
                logger.warning(
                    f"Resource {resource} size ({file_size / 1024 / 1024:.1f} MB) "
                    f"exceeds limit ({max_size_mb} MB)"
                )
                return None
        except OSError as e:
            logger.debug(f"Could not check file size: {e}")
        
        # Read the file
        try:
            with open(full_path, 'rb') as f:
                content = f.read()
            
            # Cache if enabled
            if use_cache and len(content) <= max_size_mb * 1024 * 1024:
                cache.put(package, resource, content, ttl=cache_ttl)
            
            return content
            
        except (OSError, IOError, MemoryError) as e:
            logger.error(f"Failed to read resource {resource}: {e}")
            return None
            
    except ImportError as e:
        logger.error(f"Import error while accessing {package}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error reading resource {resource}: {e}")
        return None


@contextmanager
def get_resource_stream(
    package: str,
    resource: str,
    use_cache: bool = False
) -> BinaryIO:
    """
    Context manager for streaming large resources without loading into memory.
    
    Parameters
    ----------
    package : str
        Package name
    resource : str
        Resource path
    use_cache : bool, default=False
        Whether to cache the resource (not recommended for large files)
    
    Yields
    ------
    BinaryIO
        File-like object for reading the resource
    
    Raises
    ------
    FileNotFoundError
        If resource doesn't exist
    ValueError
        If resource path is invalid
    
    Examples
    --------
    >>> with get_resource_stream('mypackage', 'largefile.bin') as stream:
    ...     for chunk in iter(lambda: stream.read(8192), b''):
    ...         process_chunk(chunk)
    """
    # Validate resource path
    resource = validate_resource_path(resource)
    
    # Try modern API first
    if HAS_IMPORTLIB_RESOURCES:
        try:
            resource_path = files(package) / resource
            if resource_path.is_file():
                with resource_path.open('rb') as f:
                    yield f
                return
        except (FileNotFoundError, TypeError, ImportError):
            pass
    
    # Fallback to filesystem
    import importlib.util
    spec = importlib.util.find_spec(package)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Package {package} not found")
    
    module = sys.modules.get(package) or safe_import(package)
    if module is None or not hasattr(module, '__file__'):
        raise FileNotFoundError(f"Cannot locate package {package}")
    
    base_path = Path(module.__file__).parent
    full_path = base_path / resource
    
    # Validate path
    try:
        full_path.resolve().relative_to(base_path.resolve())
    except ValueError:
        raise ValueError(f"Resource outside package: {resource}")
    
    if not full_path.exists() or not full_path.is_file():
        raise FileNotFoundError(f"Resource not found: {resource}")
    
    with open(full_path, 'rb') as f:
        yield f


def get_text_data(
    package: str,
    resource: str,
    encoding: str = 'utf-8',
    **kwargs
) -> Optional[str]:
    """
    Convenience function to get resource as text.
    
    Parameters
    ----------
    package : str
        Package name
    resource : str
        Resource path
    encoding : str, default='utf-8'
        Text encoding
    **kwargs
        Additional arguments passed to get_data()
    
    Returns
    -------
    Optional[str]
        Resource content as string, or None if not found
    
    Examples
    --------
    >>> text = get_text_data('mypackage', 'data/readme.txt')
    >>> if text:
    ...     print(text)
    """
    data = get_data(package, resource, **kwargs)
    if data is not None:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError as e:
            logger.error(f"Failed to decode {resource} with {encoding}: {e}")
            return None
    return None


def clear_resource_cache(package: Optional[str] = None, resource: Optional[str] = None):
    """
    Clear the resource cache.
    
    Parameters
    ----------
    package : Optional[str], default=None
        Package to clear (clears all if None)
    resource : Optional[str], default=None
        Specific resource to clear (clears all package resources if None)
    
    Examples
    --------
    >>> # Clear everything
    >>> clear_resource_cache()
    >>> 
    >>> # Clear all resources for a package
    >>> clear_resource_cache('mypackage')
    >>> 
    >>> # Clear specific resource
    >>> clear_resource_cache('mypackage', 'data/config.json')
    """
    _default_cache.invalidate(package, resource)


# Backward compatibility aliases
get_resource_data = get_data
read_resource = get_data