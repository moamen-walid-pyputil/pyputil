#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Deep Package Inspection System
=======================================

A comprehensive, production-grade package introspection system that provides
deep recursive inspection of Python packages with sophisticated filtering,
searching, and metadata collection capabilities.

This module extends Python's built-in `dir()` functionality to provide
recursive exploration of package hierarchies with fine-grained control
over what is included and how results are presented.

Features
--------
- **Deep Recursive Inspection**: Explore entire package hierarchies
- **Type-Based Filtering**: Filter by modules, functions, classes, variables
- **Regex Pattern Matching**: Filter results using regular expressions
- **Custom Filter Functions**: Apply arbitrary filtering logic
- **Import Prefix Filtering**: Limit to specific import paths
- **Exclusion Patterns**: Exclude specific modules or patterns
- **Depth Control**: Limit recursion depth for large packages
- **Path-Based Filtering**: Restrict to specific filesystem locations
- **Public/Private Filtering**: Control visibility of underscore-prefixed items
- **Nested Class Support**: Include classes defined inside other classes
- **Property Support**: Include or exclude property descriptors
- **Stub File Support**: Handle .pyi type stub files
- **Metadata Collection**: Gather additional information about modules
- **Thread-Safe**: Optional caching for repeated queries

Examples
--------
>>> from pyputil.util import deep_dir, DeepDirResult
>>> 
>>> # Basic inspection
>>> result = deep_dir('numpy', max_depth=2)
>>> print(f"Found {len(result.modules)} modules, {len(result.functions)} functions")
>>> 
>>> # Filter by import prefix
>>> result = deep_dir('pandas', import_prefix='pandas.core')
>>> 'pandas.core.frame' in result.modules
True
>>> 
>>> # Search for specific functionality
>>> result = deep_dir('numpy', name_pattern=r'.*linalg.*')
>>> result.functions
{'numpy.linalg.solve', 'numpy.linalg.eig', ...}
>>> 
>>> # Custom filtering
>>> result = deep_dir('sklearn', name_filter=lambda n: 'Classifier' in n)
>>> 
>>> # Exclude test modules
>>> result = deep_dir('scipy', exclude_imports=['scipy.test', 'scipy._lib'])
>>> 
>>> # Get only classes
>>> classes_only = result.by_type('classes')
>>> 
>>> # Chain operations
>>> result = deep_dir('matplotlib', public_only=True, max_depth=3)
>>> filtered = result.filter(r'Figure').search('plot', case_sensitive=False)
>>> 
>>> # Collect metadata
>>> result = deep_dir('requests', collect_metadata=True, max_depth=2)

References
----------
- inspect: https://docs.python.org/3/library/inspect.html
- pkgutil: https://docs.python.org/3/library/pkgutil.html
- importlib: https://docs.python.org/3/library/importlib.html
"""

import sys
import os
import importlib
import importlib.util
import pkgutil
import inspect
import re
import warnings
import threading
import time
from types import ModuleType, FunctionType, MethodType
from typing import (
    Optional, List, Set, Dict, Tuple, Union, Any, Callable,
    Pattern, Iterator, FrozenSet, TypeVar, overload, Mapping
)
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from enum import Enum, auto, Flag
from pathlib import Path
from functools import lru_cache, wraps
from contextlib import contextmanager
from collections import defaultdict
import weakref

# ============================================================================
# Platform Detection
# ============================================================================

_IS_WINDOWS: bool = sys.platform == "win32"
_IS_MACOS: bool = sys.platform == "darwin"
_IS_LINUX: bool = sys.platform.startswith("linux")
_IS_BSD: bool = any(sys.platform.startswith(p) for p in ("freebsd", "openbsd", "netbsd", "dragonfly"))
_IS_CYGWIN: bool = "cygwin" in sys.platform
_IS_MSYS: bool = "msys" in sys.platform

# Platform-specific path handling
if _IS_WINDOWS:
    _PATH_SEP = ';'
    _CASE_SENSITIVE = False
else:
    _PATH_SEP = ':'
    _CASE_SENSITIVE = True

# ============================================================================
# Enums for Configuration
# ============================================================================

class ItemType(Enum):
    """
    Enumeration of inspectable item types.
    
    Attributes
    ----------
    MODULE : str
        Python module or submodule.
    FUNCTION : str
        Function or method.
    CLASS : str
        Class or type.
    VARIABLE : str
        Variable, constant, or attribute.
    PROPERTY : str
        Property descriptor.
    METHOD : str
        Instance/class/static method.
    ALL : str
        All types (for filtering).
    """
    MODULE = "modules"
    FUNCTION = "functions"
    CLASS = "classes"
    VARIABLE = "variables"
    PROPERTY = "properties"
    METHOD = "methods"
    ALL = "all"
    
    def __str__(self) -> str:
        return self.value


class InspectionMode(Enum):
    """
    Enumeration of inspection modes.
    
    Attributes
    ----------
    LIVE : str
        Inspect live imported modules (may execute code).
    STATIC : str
        Static analysis only (no imports, limited info).
    HYBRID : str
        Mix of live and static analysis.
    """
    LIVE = "live"
    STATIC = "static"
    HYBRID = "hybrid"
    
    def __str__(self) -> str:
        return self.value


class SortOrder(Enum):
    """
    Enumeration of result sorting orders.
    
    Attributes
    ----------
    ALPHABETICAL : str
        Sort alphabetically.
    DISCOVERY : str
        Preserve discovery order.
    HIERARCHICAL : str
        Sort by package hierarchy depth.
    TYPE_FIRST : str
        Group by type then alphabetical.
    """
    ALPHABETICAL = "alphabetical"
    DISCOVERY = "discovery"
    HIERARCHICAL = "hierarchical"
    TYPE_FIRST = "type_first"
    
    def __str__(self) -> str:
        return self.value


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ItemMetadata:
    """
    Metadata for an inspected item.
    
    Attributes
    ----------
    name : str
        Full qualified name.
    item_type : ItemType
        Type of the item.
    file_path : Optional[Path]
        Filesystem path to the source file.
    line_number : Optional[int]
        Line number where item is defined.
    docstring : Optional[str]
        Item docstring (truncated).
    has_docstring : bool
        Whether item has a docstring.
    is_public : bool
        Whether item is public (no leading underscore).
    is_dunder : bool
        Whether item is a dunder method.
    is_deprecated : bool
        Whether item is marked deprecated.
    source_size : Optional[int]
        Size of source file in bytes.
    import_time : Optional[float]
        Time taken to import (if measured).
    """
    name: str
    item_type: ItemType
    file_path: Optional[Path] = None
    line_number: Optional[int] = None
    docstring: Optional[str] = None
    has_docstring: bool = False
    is_public: bool = True
    is_dunder: bool = False
    is_deprecated: bool = False
    source_size: Optional[int] = None
    import_time: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        result['item_type'] = str(self.item_type)
        if self.file_path:
            result['file_path'] = str(self.file_path)
        return result


@dataclass
class InspectionStatistics:
    """
    Statistics for an inspection operation.
    
    Attributes
    ----------
    start_time : float
        When inspection started.
    end_time : Optional[float]
        When inspection completed.
    duration : Optional[float]
        Total duration in seconds.
    modules_processed : int
        Number of modules processed.
    modules_failed : int
        Number of modules that failed to import.
    items_found : int
        Total items found.
    items_filtered : int
        Items after filtering.
    cache_hits : int
        Number of cache hits.
    cache_misses : int
        Number of cache misses.
    """
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration: Optional[float] = None
    modules_processed: int = 0
    modules_failed: int = 0
    items_found: int = 0
    items_filtered: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    
    def finish(self) -> None:
        """Mark inspection as finished and calculate duration."""
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class DeepDirResult:
    """
    Container for deep directory inspection results.
    
    This class holds the collected items from a deep inspection and provides
    methods for filtering, searching, and analyzing the results.
    
    Attributes
    ----------
    modules : Set[str]
        Set of module names.
    functions : Set[str]
        Set of function names with full paths.
    classes : Set[str]
        Set of class names with full paths.
    variables : Set[str]
        Set of variable/attribute names with full paths.
    properties : Set[str]
        Set of property names.
    methods : Set[str]
        Set of method names.
    metadata : Dict[str, ItemMetadata]
        Additional metadata for collected items.
    stats : InspectionStatistics
        Statistics about the inspection.
    root_package : str
        Name of the root package inspected.
    """
    
    modules: Set[str] = field(default_factory=set)
    functions: Set[str] = field(default_factory=set)
    classes: Set[str] = field(default_factory=set)
    variables: Set[str] = field(default_factory=set)
    properties: Set[str] = field(default_factory=set)
    methods: Set[str] = field(default_factory=set)
    metadata: Dict[str, ItemMetadata] = field(default_factory=dict)
    stats: InspectionStatistics = field(default_factory=InspectionStatistics)
    root_package: str = ""
    
    def __post_init__(self) -> None:
        """Calculate totals after initialization."""
        self._update_totals()
    
    def _update_totals(self) -> None:
        """Update total counts."""
        self.stats.items_found = len(self.all())
    
    def all(self) -> Set[str]:
        """
        Return all collected names (flat set).
        
        Returns
        -------
        Set[str]
            Union of all collected item names.
        """
        return (
            self.modules
            | self.functions
            | self.classes
            | self.variables
            | self.properties
            | self.methods
        )
    
    def count_by_type(self) -> Dict[str, int]:
        """
        Get count of items by type.
        
        Returns
        -------
        Dict[str, int]
            Dictionary mapping type names to counts.
        """
        return {
            'modules': len(self.modules),
            'functions': len(self.functions),
            'classes': len(self.classes),
            'variables': len(self.variables),
            'properties': len(self.properties),
            'methods': len(self.methods),
            'total': len(self.all()),
        }
    
    def filter(self, pattern: Union[str, Pattern]) -> 'DeepDirResult':
        """
        Filter results by regex pattern.
        
        Parameters
        ----------
        pattern : Union[str, Pattern]
            Regex pattern to filter results by.
        
        Returns
        -------
        DeepDirResult
            New result object containing only items matching the pattern.
        """
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        
        new_result = DeepDirResult(root_package=self.root_package)
        
        new_result.modules = {m for m in self.modules if pattern.search(m)}
        new_result.functions = {f for f in self.functions if pattern.search(f)}
        new_result.classes = {c for c in self.classes if pattern.search(c)}
        new_result.variables = {v for v in self.variables if pattern.search(v)}
        new_result.properties = {p for p in self.properties if pattern.search(p)}
        new_result.methods = {m for m in self.methods if pattern.search(m)}
        
        # Copy matching metadata
        for name, meta in self.metadata.items():
            if pattern.search(name):
                new_result.metadata[name] = meta
        
        new_result.stats.items_filtered = len(new_result.all())
        
        return new_result
    
    def search(self, term: str, case_sensitive: bool = True) -> 'DeepDirResult':
        """
        Search for items containing a specific term.
        
        Parameters
        ----------
        term : str
            Term to search for.
        case_sensitive : bool, default=True
            Whether the search should be case-sensitive.
        
        Returns
        -------
        DeepDirResult
            New result object containing only items matching the search term.
        """
        if case_sensitive:
            pattern = re.compile(re.escape(term))
        else:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
        
        return self.filter(pattern)
    
    def by_type(self, *types: Union[str, ItemType]) -> 'DeepDirResult':
        """
        Filter results by specific types.
        
        Parameters
        ----------
        *types : Union[str, ItemType]
            Types to include.
        
        Returns
        -------
        DeepDirResult
            New result object containing only the specified types.
        """
        new_result = DeepDirResult(root_package=self.root_package)
        
        type_map = {
            'modules': self.modules,
            'functions': self.functions,
            'classes': self.classes,
            'variables': self.variables,
            'properties': self.properties,
            'methods': self.methods,
        }
        
        for t in types:
            if isinstance(t, ItemType):
                t = t.value
            if t in type_map:
                setattr(new_result, t, type_map[t].copy())
        
        # Copy matching metadata
        all_names = new_result.all()
        for name, meta in self.metadata.items():
            if name in all_names:
                new_result.metadata[name] = meta
        
        return new_result
    
    def public_only(self) -> 'DeepDirResult':
        """
        Filter to only public items (no leading underscore).
        
        Returns
        -------
        DeepDirResult
            New result with only public items.
        """
        new_result = DeepDirResult(root_package=self.root_package)
        
        for attr in ['modules', 'functions', 'classes', 'variables', 'properties', 'methods']:
            items = getattr(self, attr)
            # Filter out items with underscore in any part
            filtered = {
                item for item in items
                if not any(part.startswith('_') for part in item.split('.'))
            }
            setattr(new_result, attr, filtered)
        
        # Copy public metadata
        for name, meta in self.metadata.items():
            if meta.is_public:
                new_result.metadata[name] = meta
        
        return new_result
    
    def with_docstring(self) -> 'DeepDirResult':
        """
        Filter to only items that have docstrings.
        
        Returns
        -------
        DeepDirResult
            New result with only items that have docstrings.
        """
        new_result = DeepDirResult(root_package=self.root_package)
        
        for name, meta in self.metadata.items():
            if meta.has_docstring:
                # Add to appropriate type set
                if meta.item_type == ItemType.MODULE:
                    new_result.modules.add(name)
                elif meta.item_type == ItemType.FUNCTION:
                    new_result.functions.add(name)
                elif meta.item_type == ItemType.CLASS:
                    new_result.classes.add(name)
                elif meta.item_type == ItemType.VARIABLE:
                    new_result.variables.add(name)
                elif meta.item_type == ItemType.PROPERTY:
                    new_result.properties.add(name)
                elif meta.item_type == ItemType.METHOD:
                    new_result.methods.add(name)
                
                new_result.metadata[name] = meta
        
        return new_result
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert result to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of results.
        """
        return {
            'root_package': self.root_package,
            'modules': sorted(self.modules),
            'functions': sorted(self.functions),
            'classes': sorted(self.classes),
            'variables': sorted(self.variables),
            'properties': sorted(self.properties),
            'methods': sorted(self.methods),
            'counts': self.count_by_type(),
            'stats': self.stats.to_dict(),
            'metadata': {k: v.to_dict() for k, v in self.metadata.items()},
        }
    
    def summary(self) -> str:
        """
        Get a human-readable summary of results.
        
        Returns
        -------
        str
            Formatted summary string.
        """
        lines = [
            f"Deep Inspection Results for '{self.root_package}'",
            "=" * 50,
            f"Modules:    {len(self.modules):>6}",
            f"Functions:  {len(self.functions):>6}",
            f"Classes:    {len(self.classes):>6}",
            f"Variables:  {len(self.variables):>6}",
            f"Properties: {len(self.properties):>6}",
            f"Methods:    {len(self.methods):>6}",
            "-" * 50,
            f"Total:      {len(self.all()):>6}",
        ]
        
        if self.stats.duration:
            lines.append(f"Duration:   {self.stats.duration:>6.2f}s")
        
        if self.stats.modules_failed:
            lines.append(f"Failed:     {self.stats.modules_failed:>6} modules")
        
        return "\n".join(lines)
    
    def __len__(self) -> int:
        """Return total number of items."""
        return len(self.all())
    
    def __contains__(self, item: str) -> bool:
        """Check if an item is in the results."""
        return item in self.all()
    
    def __iter__(self) -> Iterator[str]:
        """Iterate over all items."""
        return iter(self.all())
    
    def __repr__(self) -> str:
        return f"<DeepDirResult '{self.root_package}' ({len(self)} items)>"


# ============================================================================
# Configuration Class
# ============================================================================

@dataclass
class DeepDirConfig:
    """
    Configuration for deep directory inspection.
    
    Attributes
    ----------
    public_only : bool
        Exclude private/dunder attributes.
    include_submodules : bool
        Recursively explore submodules.
    include_types : FrozenSet[str]
        Types to include.
    ignore_errors : bool
        Skip modules that fail to import.
    name_pattern : Optional[Pattern]
        Regex pattern to filter names.
    name_filter : Optional[Callable[[str], bool]]
        Custom filter function.
    import_prefix : Optional[str]
        Filter to include only items with this prefix.
    exclude_patterns : List[Pattern]
        Patterns to exclude.
    max_depth : Optional[int]
        Maximum recursion depth.
    include_package_path : Optional[Path]
        Restrict to this filesystem path.
    include_dunder : bool
        Include dunder methods.
    include_nested_classes : bool
        Include nested classes.
    include_properties : bool
        Include property descriptors.
    follow_links : bool
        Follow symbolic links.
    include_stubs : bool
        Include .pyi stub files.
    sort_order : SortOrder
        Result sorting order.
    collect_metadata : bool
        Collect additional metadata.
    inspection_mode : InspectionMode
        Live vs static inspection.
    use_cache : bool
        Use caching for repeated queries.
    cache_ttl : Optional[float]
        Cache time-to-live in seconds.
    timeout : Optional[float]
        Timeout for inspection in seconds.
    """
    public_only: bool = True
    include_submodules: bool = True
    include_types: FrozenSet[str] = field(default_factory=lambda: frozenset({
        'modules', 'functions', 'classes', 'variables'
    }))
    ignore_errors: bool = True
    name_pattern: Optional[Pattern] = None
    name_filter: Optional[Callable[[str], bool]] = None
    import_prefix: Optional[str] = None
    exclude_patterns: List[Pattern] = field(default_factory=list)
    max_depth: Optional[int] = None
    include_package_path: Optional[Path] = None
    include_dunder: bool = False
    include_nested_classes: bool = False
    include_properties: bool = False
    follow_links: bool = True
    include_stubs: bool = False
    sort_order: SortOrder = SortOrder.ALPHABETICAL
    collect_metadata: bool = False
    inspection_mode: InspectionMode = InspectionMode.LIVE
    use_cache: bool = True
    cache_ttl: Optional[float] = None
    timeout: Optional[float] = None
    
    def __post_init__(self) -> None:
        """Validate and process configuration."""
        if self.import_prefix and self.name_pattern is None:
            self.name_pattern = re.compile(rf'^{re.escape(self.import_prefix)}\.')
        
        if self.include_package_path and isinstance(self.include_package_path, str):
            self.include_package_path = Path(self.include_package_path).resolve()


# ============================================================================
# Cache Management
# ============================================================================

class InspectionCache:
    """
    Thread-safe cache for inspection results.
    
    Attributes
    ----------
    max_size : int
        Maximum number of cached results.
    ttl : Optional[float]
        Time-to-live for cache entries.
    """
    
    def __init__(self, max_size: int = 100, ttl: Optional[float] = None):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: Dict[str, Tuple[DeepDirResult, float]] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[DeepDirResult]:
        """
        Get cached result if valid.
        
        Parameters
        ----------
        key : str
            Cache key.
        
        Returns
        -------
        Optional[DeepDirResult]
            Cached result or None.
        """
        with self._lock:
            if key in self._cache:
                result, timestamp = self._cache[key]
                
                # Check TTL
                if self.ttl and time.time() - timestamp > self.ttl:
                    del self._cache[key]
                    self._misses += 1
                    return None
                
                self._hits += 1
                return result
            
            self._misses += 1
            return None
    
    def set(self, key: str, value: DeepDirResult) -> None:
        """
        Store result in cache.
        
        Parameters
        ----------
        key : str
            Cache key.
        value : DeepDirResult
            Result to cache.
        """
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_size:
                oldest_key = min(self._cache.keys(), 
                                key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            
            self._cache[key] = (value, time.time())
    
    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
    
    @property
    def stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        with self._lock:
            return {
                'size': len(self._cache),
                'hits': self._hits,
                'misses': self._misses,
                'max_size': self.max_size,
            }


# Global cache instance
_inspection_cache = InspectionCache()


# ============================================================================
# Helper Functions
# ============================================================================

def _is_public(name: str, include_dunder: bool = False) -> bool:
    """
    Determine if a name should be considered public.
    
    Parameters
    ----------
    name : str
        Name to check.
    include_dunder : bool, default=False
        Whether to include dunder methods.
    
    Returns
    -------
    bool
        True if name is public.
    """
    if include_dunder:
        return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))
    return not name.startswith("_")


def _make_hashable(obj: Any) -> Any:
    """
    Convert arbitrary Python objects into immutable, hashable structures.

    This function recursively transforms mutable or non-hashable objects
    into deterministic immutable representations suitable for:

    - cache keys
    - memoization
    - hashing
    - equality comparisons
    - persistent object fingerprints

    Supported transformations
    -------------------------
    - list            -> tuple
    - tuple           -> tuple (recursive normalization)
    - set             -> frozenset
    - dict/mapping    -> sorted tuple of key-value pairs
    - dataclass       -> normalized dictionary representation
    - pathlib.Path    -> string path
    - Enum            -> enum value
    - bytes-like      -> immutable bytes
    - iterables       -> tuple
    - custom objects  -> normalized ``__dict__``

    Notes
    -----
    - Dictionary keys are sorted to ensure deterministic hashing.
    - Objects with ``__dict__`` are recursively normalized.
    - Circular references are detected safely.
    - NaN values are normalized into a stable representation.
    - Already hashable immutable primitives are returned unchanged.

    Parameters
    ----------
    obj : Any
        The object to normalize into a hashable structure.

    Returns
    -------
    Any
        A recursively normalized immutable representation.

    Raises
    ------
    TypeError
        If the object cannot be safely converted.

    Examples
    --------
    Basic usage:

    >>> make_hashable([1, 2, 3])
    (1, 2, 3)

    Nested structures:

    >>> make_hashable({"a": [1, 2], "b": {"x": 5}})
    (('a', (1, 2)), ('b', (('x', 5),)))

    Dataclass support:

    >>> from dataclasses import dataclass
    >>> @dataclass
    ... class Config:
    ...     debug: bool
    ...     ports: list[int]
    ...
    >>> make_hashable(Config(True, [80, 443]))
    (('debug', True), ('ports', (80, 443)))

    Cache key generation:

    >>> cache_key = hash(make_hashable(config))
    """

    visited: dict[int, str] = {}

    def _convert(value: Any) -> Any:
        """
        Internal recursive normalizer.
        """

        obj_id = id(value)

        # Circular reference detection
        if obj_id in visited:
            return f"<CIRCULAR_REF:{visited[obj_id]}>"

        primitive_types = (
            str,
            int,
            bool,
            type(None),
            bytes,
        )

        # Fast path
        if isinstance(value, primitive_types):
            return value

        # Stable float handling
        if isinstance(value, float):
            if math.isnan(value):
                return "<NaN>"
            if math.isinf(value):
                return "<Infinity>" if value > 0 else "<-Infinity>"
            return value

        # Enum support
        if isinstance(value, Enum):
            return _convert(value.value)

        # pathlib.Path
        if isinstance(value, Path):
            return str(value)

        # Dataclass support
        if is_dataclass(value):
            visited[obj_id] = value.__class__.__name__
            return _convert(asdict(value))

        # Mapping support
        if isinstance(value, (dict, Mapping)):
            visited[obj_id] = "dict"

            normalized = tuple(
                sorted(
                    (
                        _convert(k),
                        _convert(v),
                    )
                    for k, v in value.items()
                )
            )

            visited.pop(obj_id, None)
            return normalized

        # Set support
        if isinstance(value, (set, frozenset)):
            visited[obj_id] = "set"

            normalized = frozenset(_convert(v) for v in value)

            visited.pop(obj_id, None)
            return normalized

        # Sequence support
        if isinstance(value, (list, tuple)):
            visited[obj_id] = "sequence"

            normalized = tuple(_convert(v) for v in value)

            visited.pop(obj_id, None)
            return normalized

        # Generic iterables (except strings/bytes already handled)
        if isinstance(value, Iterable):
            visited[obj_id] = "iterable"

            normalized = tuple(_convert(v) for v in value)

            visited.pop(obj_id, None)
            return normalized

        # Custom object support
        if hasattr(value, "__dict__"):
            visited[obj_id] = value.__class__.__name__

            normalized = (
                value.__class__.__name__,
                _convert(vars(value)),
            )

            visited.pop(obj_id, None)
            return normalized

        # Final fallback
        try:
            hash(value)
            return value
        except Exception as exc:
            raise TypeError(
                f"Object of type '{type(value).__name__}' "
                f"is not hashable and cannot be normalized."
            ) from exc

    return _convert(obj)

def _should_include(name: str, config: DeepDirConfig) -> bool:
    """
    Apply all filters to determine if an item should be included.
    
    Parameters
    ----------
    name : str
        Item name to check.
    config : DeepDirConfig
        Configuration with filters.
    
    Returns
    -------
    bool
        True if item should be included.
    """
    # Apply name pattern filter
    if config.name_pattern is not None and not config.name_pattern.search(name):
        return False
    
    # Apply custom filter
    if config.name_filter is not None and not config.name_filter(name):
        return False
    
    # Apply exclude patterns
    for pattern in config.exclude_patterns:
        if pattern.match(name):
            return False
    
    return True


def _is_within_path(module: ModuleType, path: Optional[Path], follow_links: bool) -> bool:
    """
    Check if module is within the specified package path.
    
    Parameters
    ----------
    module : ModuleType
        Module to check.
    path : Optional[Path]
        Target path.
    follow_links : bool
        Whether to follow symlinks.
    
    Returns
    -------
    bool
        True if module is within path.
    """
    if path is None:
        return True
    
    module_file = getattr(module, '__file__', None)
    if module_file is None:
        return False
    
    try:
        module_path = Path(module_file)
        if follow_links:
            module_path = module_path.resolve()
        
        # Check if path is ancestor
        return path in module_path.parents or module_path.parent == path
    except Exception:
        return False


def _get_full_name(module_name: str, attr_name: str) -> str:
    """
    Construct full qualified name for an attribute.
    
    Parameters
    ----------
    module_name : str
        Module name.
    attr_name : str
        Attribute name.
    
    Returns
    -------
    str
        Full qualified name.
    """
    return f"{module_name}.{attr_name}"


def _extract_metadata(
    obj: Any,
    name: str,
    item_type: ItemType,
    module: ModuleType
) -> ItemMetadata:
    """
    Extract metadata for an item.
    
    Parameters
    ----------
    obj : Any
        Object to inspect.
    name : str
        Full qualified name.
    item_type : ItemType
        Type of the item.
    module : ModuleType
        Parent module.
    
    Returns
    -------
    ItemMetadata
        Extracted metadata.
    """
    metadata = ItemMetadata(
        name=name,
        item_type=item_type,
        is_public=_is_public(name.split('.')[-1]),
        is_dunder=name.split('.')[-1].startswith('__') and name.split('.')[-1].endswith('__'),
    )
    
    # Get docstring
    doc = inspect.getdoc(obj)
    if doc:
        metadata.has_docstring = True
        metadata.docstring = doc[:200] + "..." if len(doc) > 200 else doc
    
    # Get source file
    try:
        source_file = inspect.getfile(obj)
        if source_file:
            metadata.file_path = Path(source_file)
            if metadata.file_path.exists():
                metadata.source_size = metadata.file_path.stat().st_size
    except (TypeError, OSError):
        pass
    
    # Get line number
    try:
        _, line = inspect.getsourcelines(obj)
        metadata.line_number = line
    except (TypeError, OSError):
        pass
    
    # Check for deprecation
    if doc and ('deprecated' in doc.lower() or 'deprecation' in doc.lower()):
        metadata.is_deprecated = True
    
    return metadata


def _sort_results(result: DeepDirResult, sort_order: SortOrder) -> None:
    """
    Sort results according to specified order.
    
    Parameters
    ----------
    result : DeepDirResult
        Result to sort (modified in place).
    sort_order : SortOrder
        Sorting order.
    """
    if sort_order == SortOrder.ALPHABETICAL:
        result.modules = set(sorted(result.modules))
        result.functions = set(sorted(result.functions))
        result.classes = set(sorted(result.classes))
        result.variables = set(sorted(result.variables))
        result.properties = set(sorted(result.properties))
        result.methods = set(sorted(result.methods))
    
    elif sort_order == SortOrder.HIERARCHICAL:
        # Sort by depth (number of dots)
        def depth_key(name: str) -> int:
            return name.count('.')
        
        result.modules = set(sorted(result.modules, key=depth_key))
        result.functions = set(sorted(result.functions, key=depth_key))
        result.classes = set(sorted(result.classes, key=depth_key))
        result.variables = set(sorted(result.variables, key=depth_key))
        result.properties = set(sorted(result.properties, key=depth_key))
        result.methods = set(sorted(result.methods, key=depth_key))
    
    # DISCOVERY: keep original order (no sorting)
    # TYPE_FIRST: already grouped by type


# ============================================================================
# Core Inspection Function
# ============================================================================

def _process_module(
    module: ModuleType,
    config: DeepDirConfig,
    result: DeepDirResult,
    visited: Set[str],
    depth: int = 0
) -> None:
    """
    Recursively process a module and its contents.
    
    Parameters
    ----------
    module : ModuleType
        Module to process.
    config : DeepDirConfig
        Inspection configuration.
    result : DeepDirResult
        Result container to populate.
    visited : Set[str]
        Set of already visited module names.
    depth : int, default=0
        Current recursion depth.
    """
    module_name = module.__name__
    
    # Check depth limit
    if config.max_depth is not None and depth > config.max_depth:
        return
    
    # Avoid circular imports
    if module_name in visited:
        return
    visited.add(module_name)
    
    result.stats.modules_processed += 1
    
    # Filter by path if needed
    if not _is_within_path(module, config.include_package_path, config.follow_links):
        return
    
    # Add module itself
    if "modules" in config.include_types and _should_include(module_name, config):
        result.modules.add(module_name)
        
        if config.collect_metadata:
            result.metadata[module_name] = _extract_metadata(
                module, module_name, ItemType.MODULE, module
            )
    
    # Get module members
    try:
        members = inspect.getmembers(module)
    except Exception:
        if not config.ignore_errors:
            raise
        result.stats.modules_failed += 1
        return
    
    for name, obj in members:
        # Apply public filter
        if config.public_only and not _is_public(name, config.include_dunder):
            continue
        
        # Skip dunder methods if not requested
        if not config.include_dunder and name.startswith('__') and name.endswith('__'):
            continue
        
        full_name = _get_full_name(module_name, name)
        
        # Apply filters
        if not _should_include(full_name, config):
            continue
        
        # Classify and add
        if inspect.ismodule(obj):
            if "modules" in config.include_types:
                # Skip self-reference
                if obj is not module:
                    result.modules.add(obj.__name__)
            
            # Recursively process submodule
            if config.include_submodules and hasattr(obj, '__path__'):
                _process_module(obj, config, result, visited, depth + 1)
        
        elif inspect.isfunction(obj) or inspect.isbuiltin(obj):
            if "functions" in config.include_types:
                result.functions.add(full_name)
                
                if config.collect_metadata:
                    result.metadata[full_name] = _extract_metadata(
                        obj, full_name, ItemType.FUNCTION, module
                    )
        
        elif inspect.isclass(obj):
            if "classes" in config.include_types:
                result.classes.add(full_name)
                
                if config.collect_metadata:
                    result.metadata[full_name] = _extract_metadata(
                        obj, full_name, ItemType.CLASS, module
                    )
                
                # Process nested classes
                if config.include_nested_classes:
                    for nested_name, nested_obj in inspect.getmembers(obj):
                        if inspect.isclass(nested_obj):
                            nested_full = f"{full_name}.{nested_name}"
                            if _should_include(nested_full, config):
                                result.classes.add(nested_full)
                                
                                if config.collect_metadata:
                                    result.metadata[nested_full] = _extract_metadata(
                                        nested_obj, nested_full, ItemType.CLASS, module
                                    )
            
            # Process class methods
            if "methods" in config.include_types:
                for method_name, method_obj in inspect.getmembers(obj):
                    if inspect.isfunction(method_obj) or inspect.ismethod(method_obj):
                        if config.public_only and not _is_public(method_name, config.include_dunder):
                            continue
                        method_full = f"{full_name}.{method_name}"
                        if _should_include(method_full, config):
                            result.methods.add(method_full)
                            
                            if config.collect_metadata:
                                result.metadata[method_full] = _extract_metadata(
                                    method_obj, method_full, ItemType.METHOD, module
                                )
        
        elif inspect.isdatadescriptor(obj):
            if config.include_properties and "properties" in config.include_types:
                result.properties.add(full_name)
                
                if config.collect_metadata:
                    result.metadata[full_name] = _extract_metadata(
                        obj, full_name, ItemType.PROPERTY, module
                    )
        
        else:  # Variable/attribute
            if "variables" in config.include_types:
                result.variables.add(full_name)
                
                if config.collect_metadata:
                    result.metadata[full_name] = _extract_metadata(
                        obj, full_name, ItemType.VARIABLE, module
                    )


# ============================================================================
# Public API Functions
# ============================================================================

def deep_dir(
    package_name: str,
    *,
    public_only: bool = True,
    include_submodules: bool = True,
    include_types: Optional[Set[str]] = None,
    ignore_errors: bool = True,
    # Advanced filtering options
    name_pattern: Optional[Union[str, Pattern]] = None,
    name_filter: Optional[Callable[[str], bool]] = None,
    import_prefix: Optional[str] = None,
    exclude_imports: Optional[List[str]] = None,
    max_depth: Optional[int] = None,
    include_package_path: Optional[Union[str, Path]] = None,
    include_dunder: bool = False,
    include_nested_classes: bool = False,
    include_properties: bool = False,
    follow_links: bool = True,
    include_stubs: bool = False,
    sort_order: Union[SortOrder, str] = SortOrder.ALPHABETICAL,
    collect_metadata: bool = False,
    inspection_mode: Union[InspectionMode, str] = InspectionMode.LIVE,
    use_cache: bool = True,
    cache_ttl: Optional[float] = None,
    timeout: Optional[float] = None,
) -> DeepDirResult:
    """
    Deep version of dir() for packages with advanced filtering and search capabilities.
    
    This function recursively explores Python packages and modules, collecting
    information about modules, functions, classes, and variables with sophisticated
    filtering options.
    
    Parameters
    ----------
    package_name : str
        Package name to inspect (e.g., 'numpy', 'pandas.core').
    
    public_only : bool, default=True
        If True, exclude private/dunder attributes.
    
    include_submodules : bool, default=True
        Recursively explore submodules and subpackages.
    
    include_types : Optional[Set[str]], default=None
        Filter types to include. Available types:
        - "modules": Python modules and submodules
        - "functions": Functions and methods
        - "classes": Classes and types
        - "variables": Variables, constants, and other attributes
        - "properties": Property descriptors
        - "methods": Class/instance methods
    
    ignore_errors : bool, default=True
        Skip modules that fail to import.
    
    name_pattern : Optional[Union[str, Pattern]], default=None
        Regex pattern to filter names.
    
    name_filter : Optional[Callable[[str], bool]], default=None
        Custom filter function.
    
    import_prefix : Optional[str], default=None
        Filter to include only items with this prefix.
    
    exclude_imports : Optional[List[str]], default=None
        List of import patterns to exclude.
    
    max_depth : Optional[int], default=None
        Maximum recursion depth for submodule exploration.
    
    include_package_path : Optional[Union[str, Path]], default=None
        Restrict inspection to modules in this directory.
    
    include_dunder : bool, default=False
        Include dunder/magic methods.
    
    include_nested_classes : bool, default=False
        Include nested classes.
    
    include_properties : bool, default=False
        Include property descriptors.
    
    follow_links : bool, default=True
        Follow symbolic links.
    
    include_stubs : bool, default=False
        Include .pyi stub files.
    
    sort_order : Union[SortOrder, str], default=SortOrder.ALPHABETICAL
        Result sorting order.
    
    collect_metadata : bool, default=False
        Collect additional metadata about items.
    
    inspection_mode : Union[InspectionMode, str], default=InspectionMode.LIVE
        Live vs static inspection mode.
    
    use_cache : bool, default=True
        Use caching for repeated queries.
    
    cache_ttl : Optional[float], default=None
        Cache time-to-live in seconds.
    
    timeout : Optional[float], default=None
        Timeout for inspection in seconds.
    
    Returns
    -------
    DeepDirResult
        Container with collected results and metadata.
    
    Examples
    --------
    >>> result = deep_dir('numpy', max_depth=2)
    >>> print(result.summary())
    
    >>> result = deep_dir('pandas', import_prefix='pandas.core')
    
    >>> result = deep_dir('sklearn', name_filter=lambda n: 'Classifier' in n)
    
    >>> result = deep_dir('matplotlib', collect_metadata=True)
    >>> for name, meta in result.metadata.items():
    ...     if meta.has_docstring:
    ...         print(name)
    """
    
    # Build configuration
    if include_types is None:
        include_types = {"modules", "functions", "classes", "variables"}
    
    # Process name pattern
    if name_pattern and isinstance(name_pattern, str):
        name_pattern = re.compile(name_pattern)
    
    # Process exclude patterns
    exclude_patterns = []
    if exclude_imports:
        exclude_patterns = [re.compile(rf'^{re.escape(ex)}') for ex in exclude_imports]
    
    # Process sort order
    if isinstance(sort_order, str):
        sort_order = SortOrder(sort_order.lower())
    
    # Process inspection mode
    if isinstance(inspection_mode, str):
        inspection_mode = InspectionMode(inspection_mode.lower())
    
    # Create config
    config = DeepDirConfig(
        public_only=public_only,
        include_submodules=include_submodules,
        include_types=frozenset(include_types),
        ignore_errors=ignore_errors,
        name_pattern=name_pattern,
        name_filter=name_filter,
        import_prefix=import_prefix,
        exclude_patterns=exclude_patterns,
        max_depth=max_depth,
        include_package_path=Path(include_package_path) if include_package_path else None,
        include_dunder=include_dunder,
        include_nested_classes=include_nested_classes,
        include_properties=include_properties,
        follow_links=follow_links,
        include_stubs=include_stubs,
        sort_order=sort_order,
        collect_metadata=collect_metadata,
        inspection_mode=inspection_mode,
        use_cache=use_cache,
        cache_ttl=cache_ttl,
        timeout=timeout,
    )
    
    # Generate cache key
    cache_key = f"{package_name}:{hash(_make_hashable(getattr(config, '__dict__', {})))}"
    
    # Check cache
    if use_cache:
        cached = _inspection_cache.get(cache_key)
        if cached:
            cached.stats.cache_hits = _inspection_cache.stats['hits']
            return cached
    
    # Create result container
    result = DeepDirResult(root_package=package_name)
    result.stats.start_time = time.time()
    
    try:
        # Static inspection mode (limited)
        if inspection_mode == InspectionMode.STATIC:
            # Only use pkgutil for static discovery
            try:
                package = importlib.import_module(package_name)
                if hasattr(package, '__path__'):
                    for mod in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
                        if not include_stubs and mod.name.endswith('.pyi'):
                            continue
                        if _should_include(mod.name, config):
                            result.modules.add(mod.name)
            except Exception as e:
                if not ignore_errors:
                    raise
                result.stats.modules_failed += 1
        
        else:
            # Live inspection
            visited = set()
            
            # Load root package
            package = importlib.import_module(package_name)
            _process_module(package, config, result, visited, depth=0)
            
            # Handle submodules via pkgutil for namespace packages
            if include_submodules and hasattr(package, "__path__"):
                for mod in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
                    try:
                        if not include_stubs and mod.name.endswith('.pyi'):
                            continue
                        
                        submod = importlib.import_module(mod.name)
                        _process_module(submod, config, result, visited, depth=1)
                    except Exception:
                        if not ignore_errors:
                            raise
                        result.stats.modules_failed += 1
    
    except Exception as e:
        if not ignore_errors:
            raise ImportError(f"Failed to import package '{package_name}': {e}") from e
        result.stats.modules_failed += 1
    
    # Sort results
    _sort_results(result, config.sort_order)
    
    # Finalize statistics
    result.stats.finish()
    result.stats.items_filtered = len(result.all())
    
    # Cache result
    if use_cache:
        _inspection_cache.set(cache_key, result)
    
    return result


# ============================================================================
# Convenience Functions
# ============================================================================

def quick_dir(
    package_name: str,
    *,
    public_only: bool = True,
    max_depth: int = 1,
) -> DeepDirResult:
    """
    Quick inspection with sensible defaults.
    
    Parameters
    ----------
    package_name : str
        Package name to inspect.
    public_only : bool, default=True
        Exclude private attributes.
    max_depth : int, default=1
        Maximum recursion depth.
    
    Returns
    -------
    DeepDirResult
        Inspection results.
    """
    return deep_dir(
        package_name,
        public_only=public_only,
        max_depth=max_depth,
        include_submodules=max_depth > 1,
        ignore_errors=True,
        collect_metadata=False,
    )


def find_in_package(
    package_name: str,
    pattern: Union[str, Pattern],
    *,
    item_types: Optional[Set[str]] = None,
    max_depth: int = 2,
) -> DeepDirResult:
    """
    Find items matching a pattern in a package.
    
    Parameters
    ----------
    package_name : str
        Package name to search.
    pattern : Union[str, Pattern]
        Pattern to search for.
    item_types : Optional[Set[str]], default=None
        Types of items to include.
    max_depth : int, default=2
        Maximum recursion depth.
    
    Returns
    -------
    DeepDirResult
        Matching items.
    """
    return deep_dir(
        package_name,
        name_pattern=pattern,
        include_types=item_types,
        max_depth=max_depth,
        public_only=True,
        ignore_errors=True,
    )


def get_public_api(package_name: str, max_depth: int = 1) -> DeepDirResult:
    """
    Get the public API of a package.
    
    Parameters
    ----------
    package_name : str
        Package name.
    max_depth : int, default=1
        Maximum recursion depth.
    
    Returns
    -------
    DeepDirResult
        Public API items.
    """
    return deep_dir(
        package_name,
        public_only=True,
        max_depth=max_depth,
        include_dunder=False,
        include_nested_classes=False,
        collect_metadata=True,
    )


def list_submodules(package_name: str) -> List[str]:
    """
    List all submodules of a package.
    
    Parameters
    ----------
    package_name : str
        Package name.
    
    Returns
    -------
    List[str]
        List of submodule names.
    """
    result = deep_dir(
        package_name,
        include_types={'modules'},
        include_submodules=True,
        max_depth=None,
        public_only=False,
    )
    return sorted(result.modules)


def clear_cache() -> None:
    """Clear the inspection cache."""
    _inspection_cache.clear()


def get_cache_stats() -> Dict[str, int]:
    """Get cache statistics."""
    return _inspection_cache.stats


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    'ItemType',
    'InspectionMode',
    'SortOrder',
    
    # Data Classes
    'ItemMetadata',
    'InspectionStatistics',
    'DeepDirResult',
    'DeepDirConfig',
    
    # Cache
    'InspectionCache',
    
    # Main Function
    'deep_dir',
    
    # Convenience Functions
    'quick_dir',
    'find_in_package',
    'get_public_api',
    'list_submodules',
    'clear_cache',
    'get_cache_stats',
]

