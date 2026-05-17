#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
PyUtil Scan Module - A comprehensive tool for discovering and analyzing Python modules.

This package provides module discovery capabilities with support for
multiple search strategies, caching, and detailed metadata extraction.

The scanner can discover modules through file system scanning and Python's import
system, providing rich metadata including dependencies, docstrings, and file
properties.

Examples
--------
Basic usage:

>>> from pyputil.scan import Scanner, SearchMethod, ScanConfig
>>> 
>>> # Create scanner instance
>>> scanner = Scanner()
>>> 
>>> # Simple scan for a module
>>> result = scanner.scan("json")
>>> print(f"Found {result.total_modules_found} modules")
Found 1 modules
>>> 
>>> # Pattern-based search
>>> config = ScanConfig(search_method=SearchMethod.PATTERN)
>>> results = scanner.scan("test*", config)
>>> 
>>> # Batch scan multiple modules
>>> batch_results = scanner.batch_scan(["os", "sys", "json"])
>>> for module, result in batch_results.items():
...     print(f"{module}: {result.total_modules_found} modules")
...
os: 1 modules
sys: 1 modules
json: 1 modules

Advanced configuration:

>>> config = ScanConfig(
...     search_method=SearchMethod.ALL,
...     analyze_dependencies=True,
...     include_builtin=True,
...     parallel_scan=True,
...     workers=4,
...     max_depth=5,
...     timeout=30.0
... )
>>> 
>>> result = scanner.scan("pytest", config)
>>> 
>>> # Access detailed module metadata
>>> for module in result.results:
...     print(f"Module: {module.name}")
...     print(f"  Type: {module.module_type.value}")
...     print(f"  Dependencies: {len(module.dependencies)}")
...     print(f"  Has docstring: {module.has_docstring}")

Using custom search paths:

>>> scanner = Scanner(paths=["/custom/project/src", "/another/path"])
>>> result = scanner.scan("my_module")

Cache management:

>>> scanner.clear_cache()
>>> cache_info = scanner.get_cache_info()
>>> print(f"Cache size: {cache_info['size']}")
>>> print(f"Hit ratio: {cache_info['hit_ratio']:.2%}")

Statistics:

>>> stats = scanner.get_stats()
>>> print(f"Total scans: {stats['total_scans']}")
>>> print(f"Total modules found: {stats['total_modules_found']}")

Error handling:

>>> from pyputil.scan import ModuleNotFoundError, SearchTimeoutError
>>> 
>>> try:
...     result = scanner.scan("non_existent_module")
... except ModuleNotFoundError as e:
...     print(f"Module not found: {e}")
... except SearchTimeoutError as e:
...     print(f"Search timed out: {e}")
"""


# Core classes and enums
from .core.enums import SearchMethod, ModuleType, ScanStatus
from .core.models import ModuleMeta, ScanResult
from .core.config import ScanConfig
from .scanner.scanner import Scanner

# Exceptions
from .core.exceptions import (
    ScannerError,
    SearchTimeoutError,
    InvalidSearchMethodError,
    ModuleNotFoundError,
    InvalidPathError,
    AnalysisError,
)

# Provider classes 
from .providers.base import SearchProvider
from .providers.file_provider import FileProvider
from .providers.import_provider import ImportProvider

__all__ = [
    # Main scanner class
    "Scanner",
    # Configuration and enums
    "ScanConfig",
    "SearchMethod",
    "ModuleType",
    "ScanStatus",
    # Result models
    "ModuleMeta",
    "ScanResult",
    # Exceptions
    "ScannerError",
    "SearchTimeoutError",
    "InvalidSearchMethodError",
    "ModuleNotFoundError",
    "InvalidPathError",
    "AnalysisError",
    # Providers 
    "SearchProvider",
    "FileProvider",
    "ImportProvider",
    # High-level functions
    "create_scanner",
    "quick_scan",
    "batch_quick_scan",
]


def create_scanner(
    paths: list = None,
    config: ScanConfig = None,
    enable_cache: bool = True,
    cache_size: int = 100,
    cache_ttl: float = 3600.0
) -> Scanner:
    """
    Convenience function to create a configured scanner instance.

    Parameters
    ----------
    paths : list, optional
        Additional file paths to include in searches
    config : ScanConfig, optional
        Default configuration for scan operations
    enable_cache : bool, default=True
        Enable result caching for performance
    cache_size : int, default=100
        Maximum number of cache entries
    cache_ttl : float, default=3600.0
        Cache time-to-live in seconds

    Returns
    -------
    Scanner
        Configured scanner instance ready for use

    Examples
    --------
    >>> from pyputil.scan import create_scanner
    >>> 
    >>> # Create scanner with default settings
    >>> scanner = create_scanner()
    >>> 
    >>> # Create scanner with custom paths and large cache
    >>> scanner = create_scanner(
    ...     paths=["/my/project/src"],
    ...     cache_size=500,
    ...     cache_ttl=7200.0
    ... )
    >>> 
    >>> # Create scanner with custom configuration
    >>> from pyputil.scan import ScanConfig, SearchMethod
    >>> config = ScanConfig(search_method=SearchMethod.ALL)
    >>> scanner = create_scanner(config=config)
    """
    scanner = Scanner(paths=paths, config=config)
    
    # Configure cache settings
    if not enable_cache:
        scanner.clear_cache()
    
    return scanner


def quick_scan(module: str, paths: list = None, **kwargs) -> ScanResult:
    """
    Quick one-off module scan with minimal configuration.

    This is a convenience function for simple scans without creating
    a scanner instance manually.

    Parameters
    ----------
    module : str
        Module name, pattern, or prefix to search for
    paths : list, optional
        Additional file paths to include in searches
    **kwargs : dict
        Additional configuration options passed to ScanConfig

    Returns
    -------
    ScanResult
        Scan results with discovered modules

    Examples
    --------
    >>> from pyputil.scan import quick_scan
    >>> 
    >>> # Quick scan for a module
    >>> result = quick_scan("json")
    >>> print(result.total_modules_found)
    1
    >>> 
    >>> # Quick pattern scan with custom paths
    >>> result = quick_scan(
    ...     "test*",
    ...     paths=["/my/project"],
    ...     search_method="pattern"
    ... )
    >>> 
    >>> # Quick scan with dependency analysis
    >>> result = quick_scan(
    ...     "my_module",
    ...     analyze_dependencies=True,
    ...     max_depth=3
    ... )
    
    Notes
    -----
    Available kwargs include:
    - search_method: str ('exact', 'pattern', 'prefix', 'all')
    - max_depth: int
    - analyze_dependencies: bool
    - include_builtin: bool
    - include_frozen: bool
    - include_c_extensions: bool
    - parallel_scan: bool
    - workers: int
    - timeout: float
    """
    from .core.enums import SearchMethod
    
    # Convert string search method to enum if provided
    if 'search_method' in kwargs and isinstance(kwargs['search_method'], str):
        method_map = {
            'exact': SearchMethod.EXACT,
            'pattern': SearchMethod.PATTERN,
            'prefix': SearchMethod.PREFIX,
            'all': SearchMethod.ALL,
        }
        kwargs['search_method'] = method_map.get(
            kwargs['search_method'].lower(),
            SearchMethod.EXACT
        )
    
    config = ScanConfig(**kwargs)
    scanner = Scanner(paths=paths, config=config)
    return scanner.scan(module)


def batch_quick_scan(
    modules: list,
    paths: list = None,
    parallel: bool = False,
    **kwargs
) -> dict:
    """
    Quick batch scan of multiple modules.

    Parameters
    ----------
    modules : list
        List of module names/patterns to search for
    paths : list, optional
        Additional file paths to include in searches
    parallel : bool, default=False
        Whether to run scans in parallel
    **kwargs : dict
        Additional configuration options passed to ScanConfig

    Returns
    -------
    dict
        Dictionary mapping module names to their ScanResult objects

    Examples
    --------
    >>> from pyputil.scan import batch_quick_scan
    >>> 
    >>> # Batch scan multiple modules
    >>> results = batch_quick_scan(["json", "os", "sys"])
    >>> for module, result in results.items():
    ...     print(f"{module}: {result.total_modules_found}")
    ...
    json: 1
    os: 1
    sys: 1
    >>> 
    >>> # Parallel batch scan
    >>> results = batch_quick_scan(
    ...     ["pytest", "numpy", "requests"],
    ...     parallel=True,
    ...     workers=4
    ... )
    """
    config = ScanConfig(**kwargs)
    scanner = Scanner(paths=paths, config=config)
    return scanner.batch_scan(modules, parallel=parallel)


# Version compatibility check
def _check_version_compatibility() -> None:
    """
    Check if the current Python version is compatible.
    
    Raises
    ------
    RuntimeError
        If Python version is below 3.7
    """
    import sys
    
    if sys.version_info < (3, 7):
        raise RuntimeError(
            f"Python 3.7 or higher is required. Current version: {sys.version}"
        )


_check_version_compatibility()


from ..api import clean
clean(expose=__all__)