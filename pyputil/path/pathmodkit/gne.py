#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import sys
import functools
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing
from typing import List, Set, Tuple, Optional, Iterator
from enum import Enum, auto
import fnmatch


class ExtensionSearchDepth(Enum):
    """
    Enumeration controlling filesystem traversal depth.

    Attributes
    ----------
    SHALLOW : int
        Scan only the top-level directory (non-recursive).
    MODERATE : int
        Scan two directory levels deep (root + immediate subdirectories).
    DEEP : int
        Recursively scan all subdirectories with intelligent exclusions.
    AUTO : int
        Automatically determine optimal depth based on environment.
    """

    SHALLOW = 0
    MODERATE = 1
    DEEP = 2
    AUTO = 3


class ScanStrategy(Enum):
    """Internal scanning strategy enumeration."""
    SEQUENTIAL = auto()
    PARALLEL = auto()


def get_native_extensions(
    search_depth: ExtensionSearchDepth = ExtensionSearchDepth.AUTO,
    use_cache: bool = True,
    additional_paths: Optional[List[Path]] = None,
    exclude_patterns: Optional[List[str]] = None,
    follow_symlinks: bool = False,
    max_workers: Optional[int] = None,
) -> List[str]:
    """
    Locate native binary extension files with advanced discovery capabilities.

    This function scans platform-specific directories to discover compiled
    extension modules such as `.so`, `.pyd`, `.dll`, or `.dylib`. It employs
    intelligent path selection, parallel scanning, and configurable depth
    control for optimal performance.

    Parameters
    ----------
    search_depth : ExtensionSearchDepth, optional
        Controls how deep directory traversal should go.
        - SHALLOW: Only top-level directory
        - MODERATE: Root + immediate subdirectories
        - DEEP: Full recursion with exclusions
        - AUTO: Automatically chooses based on path count (default)
    use_cache : bool, optional
        Whether to use cached results for improved performance.
        Default is True. Cache is LRU with maxsize 128.
    additional_paths : list of Path, optional
        Extra directories to scan beyond the default system paths.
        Default is None.
    exclude_patterns : list of str, optional
        Glob patterns for directories/files to exclude (e.g., ['*.tmp', 'build/*']).
        Default excludes common patterns like __pycache__, .git, etc.
    follow_symlinks : bool, optional
        Whether to follow symbolic links during traversal.
        Default is False to avoid infinite recursion.
    max_workers : int, optional
        Maximum number of threads for parallel scanning.
        If None, defaults to min(len(paths), cpu_count()).

    Returns
    -------
    list of str
        Sorted list of absolute paths to native extension files.
        Returns empty list if no extensions found.

    Examples
    --------
    >>> # Basic usage with defaults
    >>> extensions = get_native_extensions()
    >>> 
    >>> # Deep scan with custom paths
    >>> from pathlib import Path
    >>> extensions = get_native_extensions(
    ...     search_depth=ExtensionSearchDepth.DEEP,
    ...     additional_paths=[Path('/custom/lib')],
    ...     exclude_patterns=['*.py', 'test_*']
    ... )
    >>> 
    >>> # Shallow scan without caching
    >>> extensions = get_native_extensions(
    ...     search_depth=ExtensionSearchDepth.SHALLOW,
    ...     use_cache=False
    ... )

    Notes
    -----
    The function automatically detects the operating system and uses
    appropriate file extensions:
    - Windows: .pyd, .dll
    - macOS: .so, .dylib
    - Linux/Unix: .so

    Default search paths include:
    - sys.base_prefix/DLLs (Windows)
    - sys.base_prefix/lib
    - sys.base_prefix/lib-dynload
    - sys.exec_prefix/lib
    - Directory containing os module

    See Also
    --------
    ExtensionSearchDepth : Enum controlling scan depth
    """

    # Normalize additional paths
    if additional_paths is None:
        additional_paths = []

    # Default exclude patterns
    if exclude_patterns is None:
        exclude_patterns = [
            "__pycache__",
            ".git",
            ".svn",
            ".hg",
            "node_modules",
            "site-packages",
            "dist-packages",
            "test",
            "tests",
            "*.pyc",
            "*.pyo",
            "*.tmp",
            "*.temp",
            "build",
            "dist",
            "*.egg-info",
        ]

    if use_cache:
        return _get_native_extensions_cached(
            search_depth, 
            tuple(additional_paths), 
            tuple(exclude_patterns),
            follow_symlinks,
            max_workers
        )
    
    return _get_native_extensions_impl(
        search_depth, 
        additional_paths, 
        exclude_patterns,
        follow_symlinks,
        max_workers
    )


@functools.lru_cache(maxsize=128)
def _get_native_extensions_cached(
    search_depth: ExtensionSearchDepth,
    additional_paths_tuple: Tuple[Path, ...],
    exclude_patterns_tuple: Tuple[str, ...],
    follow_symlinks: bool,
    max_workers: Optional[int],
) -> List[str]:
    """
    Cached wrapper for native extension discovery.

    Parameters
    ----------
    search_depth : ExtensionSearchDepth
        Desired directory traversal depth.
    additional_paths_tuple : tuple of Path
        Additional directories to scan (converted to tuple for hashing).
    exclude_patterns_tuple : tuple of str
        Exclusion patterns for filtering.
    follow_symlinks : bool
        Whether to follow symbolic links.
    max_workers : int or None
        Maximum number of worker threads.

    Returns
    -------
    list of str
        Cached list of absolute extension paths.
    """
    return _get_native_extensions_impl(
        search_depth,
        list(additional_paths_tuple),
        list(exclude_patterns_tuple),
        follow_symlinks,
        max_workers
    )


def _get_native_extensions_impl(
    search_depth: ExtensionSearchDepth,
    additional_paths: List[Path],
    exclude_patterns: List[str],
    follow_symlinks: bool,
    max_workers: Optional[int],
) -> List[str]:
    """
    Core implementation for discovering native extension files.

    Parameters
    ----------
    search_depth : ExtensionSearchDepth
        Desired directory traversal depth.
    additional_paths : list of Path
        Additional directories to scan.
    exclude_patterns : list of str
        Exclusion patterns for filtering.
    follow_symlinks : bool
        Whether to follow symbolic links.
    max_workers : int or None
        Maximum number of worker threads.

    Returns
    -------
    list of str
        Sorted list of absolute paths to native extension files.
    """
    
    # Platform-specific extension types
    extensions = _get_platform_extensions()
    
    # Build search paths
    search_paths = _build_search_paths()
    search_paths.extend(additional_paths)
    
    # Filter existing paths
    existing_paths = [p for p in search_paths if p.exists() and p.is_dir()]
    
    if not existing_paths:
        return []
    
    # Determine effective depth
    effective_depth = _resolve_effective_depth(search_depth, len(existing_paths))
    
    # Determine scanning strategy
    strategy = _determine_scan_strategy(len(existing_paths))
    
    # Prepare matcher function
    def should_exclude(path: Path) -> bool:
        """Check if path should be excluded based on patterns."""
        path_str = str(path)
        return any(fnmatch.fnmatch(path_str, pattern) for pattern in exclude_patterns)
    
    # Collect extensions
    extensions_found: Set[Path] = set()
    
    if strategy == ScanStrategy.PARALLEL and len(existing_paths) > 1:
        # Parallel execution
        workers = max_workers or min(len(existing_paths), multiprocessing.cpu_count())
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _scan_directory,
                    path,
                    extensions,
                    effective_depth,
                    should_exclude,
                    follow_symlinks
                ): path for path in existing_paths
            }
            
            for future in as_completed(futures):
                try:
                    extensions_found.update(future.result())
                except Exception:
                    continue  # Log error in production
    else:
        # Sequential execution
        for path in existing_paths:
            extensions_found.update(
                _scan_directory(
                    path,
                    extensions,
                    effective_depth,
                    should_exclude,
                    follow_symlinks
                )
            )
    
    return sorted(str(p.resolve()) for p in extensions_found)


def _get_platform_extensions() -> Tuple[str, ...]:
    """
    Get platform-specific native extension file extensions.

    Returns
    -------
    tuple of str
        File extensions for native libraries on current platform.
    """
    if sys.platform == "win32":
        return (".pyd", ".dll")
    elif sys.platform == "darwin":
        return (".so", ".dylib")
    else:  # Linux and other Unix-like
        return (".so",)


def _build_search_paths() -> List[Path]:
    """
    Build list of default search paths for native extensions.

    Returns
    -------
    list of Path
        Candidate directories to scan for native extensions.
    """
    paths = []
    
    # Standard Python paths
    base_prefix = Path(sys.base_prefix)
    exec_prefix = Path(sys.exec_prefix)
    
    # Platform-specific additions
    if sys.platform == "win32":
        paths.extend([
            base_prefix / "DLLs",
            base_prefix / "Lib" / "site-packages",
            base_prefix / "lib" / "site-packages",
        ])
    
    paths.extend([
        base_prefix / "lib",
        base_prefix / "lib-dynload",
        exec_prefix / "lib",
        Path(sys.prefix) / "lib",
    ])
    
    # Python's os module location
    try:
        import os
        os_path = Path(os.__file__).parent
        if os_path not in paths:
            paths.append(os_path)
    except Exception:
        pass
    
    # Conda/venv specific paths
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        paths.append(Path(sys.prefix) / "lib")
        if sys.platform == "win32":
            paths.append(Path(sys.prefix) / "DLLs")
            paths.append(Path(sys.prefix) / "Library" / "bin")
    
    return paths


def _resolve_effective_depth(
    search_depth: ExtensionSearchDepth, 
    path_count: int
) -> ExtensionSearchDepth:
    """
    Resolve effective search depth, handling AUTO mode.

    Parameters
    ----------
    search_depth : ExtensionSearchDepth
        Requested search depth.
    path_count : int
        Number of directories to scan.

    Returns
    -------
    ExtensionSearchDepth
        Effective depth to use for scanning.
    """
    if search_depth == ExtensionSearchDepth.AUTO:
        # Use DEEP for small path sets, MODERATE for larger ones
        return ExtensionSearchDepth.DEEP if path_count <= 2 else ExtensionSearchDepth.MODERATE
    return search_depth


def _determine_scan_strategy(path_count: int) -> ScanStrategy:
    """
    Determine whether to use parallel or sequential scanning.

    Parameters
    ----------
    path_count : int
        Number of directories to scan.

    Returns
    -------
    ScanStrategy
        Strategy to use for scanning.
    """
    # Use parallel for multiple paths, sequential for single path
    return ScanStrategy.PARALLEL if path_count > 1 else ScanStrategy.SEQUENTIAL


def _scan_directory(
    root: Path,
    extensions: Tuple[str, ...],
    depth: ExtensionSearchDepth,
    exclude_func: callable,
    follow_symlinks: bool,
    current_depth: int = 0,
) -> Set[Path]:
    """
    Recursively scan directory for native extensions with depth control.

    Parameters
    ----------
    root : Path
        Root directory to scan.
    extensions : tuple of str
        File extensions to match.
    depth : ExtensionSearchDepth
        Maximum search depth.
    exclude_func : callable
        Function to test if a path should be excluded.
    follow_symlinks : bool
        Whether to follow symbolic links.
    current_depth : int
        Current recursion depth (used internally).

    Returns
    -------
    set of Path
        Set of absolute paths to matching extension files.
    """
    
    found: Set[Path] = set()
    
    # Check depth limit
    if depth == ExtensionSearchDepth.SHALLOW and current_depth > 0:
        return found
    if depth == ExtensionSearchDepth.MODERATE and current_depth > 1:
        return found
    
    try:
        # Use pathlib's modern iteration
        for item in root.iterdir():
            # Skip excluded items
            if exclude_func(item):
                continue
            
            # Handle files
            if item.is_file() or (follow_symlinks and item.is_symlink() and item.resolve().is_file()):
                if item.suffix in extensions:
                    found.add(item.resolve())
            
            # Handle directories
            elif item.is_dir() or (follow_symlinks and item.is_symlink() and item.resolve().is_dir()):
                # Skip hidden directories (starting with .)
                if item.name.startswith('.'):
                    continue
                
                # Skip common excluded directories
                if item.name in {'__pycache__', 'site-packages', 'dist-packages', 
                                'node_modules', '.git', '.svn', '.hg'}:
                    continue
                
                # Recurse if not at max depth
                if depth == ExtensionSearchDepth.DEEP or current_depth < depth.value:
                    found.update(
                        _scan_directory(
                            item,
                            extensions,
                            depth,
                            exclude_func,
                            follow_symlinks,
                            current_depth + 1
                        )
                    )
                    
    except (PermissionError, OSError, NotADirectoryError):
        # Silently skip inaccessible directories
        pass
    
    return found