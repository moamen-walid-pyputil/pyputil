#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Dynamic Python Module Importer with Path Resolution
===================================================
"""

import sys
import importlib
from pathlib import Path
from typing import List, Union, Optional, Dict, Any, Set
from types import ModuleType
import importlib.util
from contextlib import contextmanager
import hashlib
import logging

# Configure module logger
logger = logging.getLogger(__name__)

# Cache for included modules with integrity checking
_INCLUDED_CACHE: Dict[str, Dict[str, Any]] = {}
_IMPORT_LOCK: Set[str] = set()  # Prevent circular imports


def resolve_import_paths(
    level: Union[int, str],
    base: Optional[Union[str, Path]] = None,
    *,
    add: bool = True,
    mode: str = "prepend",
    unique: bool = True,
    validate: bool = True
) -> List[str]:
    """
    Resolve parent directory paths relative to a base path and optionally add to sys.path.

    Parameters
    ----------
    level : int | str
        Number of directory levels to ascend:
        - int: 1 = one level up (parent), 2 = two levels up, etc.
        - str: "." = current, ".." = parent, "..." = grandparent, etc.
    base : str | Path, optional
        Starting point for path resolution. If None, uses current working directory.
    add : bool, default True
        If True, adds resolved paths to sys.path. If False, only returns paths.
    mode : str, default "prepend"
        Where to insert paths when add=True:
        - "prepend": Insert at beginning (highest priority for imports)
        - "append": Add to end (lowest priority)
        - "none": Don't modify sys.path (same as add=False)
    unique : bool, default True
        Prevents duplicate paths in both return list and sys.path modifications.
    validate : bool, default True
        If True, verifies that resolved paths exist and are directories.

    Returns
    -------
    List[str]
        List of resolved absolute paths as strings, ordered from closest to farthest.

    Raises
    ------
    ValueError
        If level string contains invalid characters, level is negative,
        mode is invalid, or no valid paths can be resolved.
    TypeError
        If level is neither int nor str.

    Examples
    --------
    >>> resolve_import_paths(1)  # Get parent directory
    ['/home/user/project']
    
    >>> resolve_import_paths("..", base="/home/user/project/src")
    ['/home/user/project']
    
    >>> paths = resolve_import_paths(2, add=False)
    >>> print(paths)
    ['/home/user/project', '/home/user']
    """
    # Validate inputs
    if mode not in ("prepend", "append", "none"):
        raise ValueError(f"mode must be 'prepend', 'append', or 'none', got '{mode}'")
    
    # Determine base path
    if base is None:
        base_path = Path.cwd().resolve()
    else:
        base_path = Path(base).resolve()
        if validate and not base_path.exists():
            raise ValueError(f"Base path does not exist: {base_path}")
    
    # Parse level
    if isinstance(level, str):
        # Validate dot string
        if not level or not all(ch == '.' for ch in level):
            raise ValueError(f"String level must contain only '.' characters, got '{level}'")
        levels = len(level)  # "." = 1, ".." = 2, "..." = 3, etc.
    elif isinstance(level, int):
        if level < 0:
            raise ValueError(f"level must be >= 0, got {level}")
        levels = level
    else:
        raise TypeError(f"level must be int or str, got {type(level).__name__}")
    
    paths: List[str] = []
    added_to_syspath: List[str] = []
    
    try:
        for i in range(levels):
            try:
                # Get parent at level i+1 (since parents[0] is immediate parent)
                parent_dir = base_path.parents[i]
            except IndexError:
                logger.debug(f"Reached filesystem root after {i} levels")
                break
            
            path_str = str(parent_dir)
            
            # Skip if already in our list (when unique=True)
            if unique and path_str in paths:
                continue
            
            # Validate directory exists
            if validate and not parent_dir.is_dir():
                logger.warning(f"Path does not exist or is not a directory: {path_str}")
                continue
            
            paths.append(path_str)
            
            # Add to sys.path if requested
            if add and mode != "none":
                if unique and path_str in sys.path:
                    logger.debug(f"Path already in sys.path: {path_str}")
                else:
                    if mode == "prepend":
                        sys.path.insert(0, path_str)
                        added_to_syspath.insert(0, path_str)
                    elif mode == "append":
                        sys.path.append(path_str)
                        added_to_syspath.append(path_str)
                    
                    logger.debug(f"Added to sys.path ({mode}): {path_str}")
        
        if not paths and levels > 0:
            logger.warning(f"No valid paths resolved for level={level}, base={base}")
        
        return paths
        
    except Exception as e:
        # Rollback sys.path modifications on error if mode is not "none"
        if add and mode != "none" and added_to_syspath:
            for p in added_to_syspath:
                while p in sys.path:
                    sys.path.remove(p)
            logger.error(f"Rolled back sys.path modifications due to error: {e}")
        raise


@contextmanager
def temporary_syspath(paths: List[str], prepend: bool = True):
    """
    Context manager for temporarily adding paths to sys.path.
    
    Parameters
    ----------
    paths : List[str]
        List of paths to add temporarily.
    prepend : bool, default True
        If True, adds at beginning of sys.path. If False, appends at end.
    
    Yields
    ------
    None
    
    Examples
    --------
    >>> with temporary_syspath(['/tmp/my_modules']):
    ...     import my_module  # Imports from /tmp/my_modules
    >>> # sys.path is restored after the context
    """
    original_path = sys.path.copy()
    added_paths = []
    
    try:
        for path in paths:
            if path not in sys.path:
                if prepend:
                    sys.path.insert(0, path)
                    added_paths.insert(0, path)
                else:
                    sys.path.append(path)
                    added_paths.append(path)
        yield
    finally:
        # Restore original sys.path
        sys.path[:] = original_path


def compute_module_hash(file_path: Path) -> str:
    """
    Compute SHA-256 hash of a Python file for integrity checking.
    
    Parameters
    ----------
    file_path : Path
        Path to the Python file.
    
    Returns
    -------
    str
        Hexadecimal SHA-256 hash of the file contents.
    
    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    IOError
        If the file cannot be read.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    try:
        with open(file_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception as e:
        raise IOError(f"Cannot read file {file_path}: {e}")


def include(
    path: str,
    *,
    name: Optional[str] = None,
    reload: bool = False,
    inject_globals: bool = False,
    target_globals: Optional[Dict[str, Any]] = None,
    check_integrity: bool = False,
    raise_on_error: bool = True,
    suppress_warnings: bool = False
) -> Optional[ModuleType]:
    """
    Dynamically import a Python module from a file path with enhanced safety features.

    Parameters
    ----------
    path : str
        Path to the Python file (.py extension recommended but not required).
    name : str, optional
        Module name for registration in sys.modules. If None, uses the file stem.
    reload : bool, default False
        If True, forces reload even if module was previously imported.
        Useful for development with frequently changing files.
    inject_globals : bool, default False
        If True, injects all module attributes into target_globals.
        Warning: This can cause namespace pollution.
    target_globals : dict, optional
        Dictionary to inject globals into (e.g., globals()).
        If None and inject_globals=True, uses calling frame's globals.
    check_integrity : bool, default False
        If True, verifies file hash to detect changes and reload automatically.
        Useful for preventing stale module imports.
    raise_on_error : bool, default True
        If True, raises exceptions on failure. If False, returns None and logs error.
    suppress_warnings : bool, default False
        If True, suppresses warning logs (errors still raised if raise_on_error=True).

    Returns
    -------
    ModuleType or None
        The imported module object, or None if raise_on_error=False and an error occurred.

    Raises
    ------
    FileNotFoundError
        If the specified file does not exist.
    ImportError
        If the module cannot be loaded (invalid Python, missing dependencies, etc.).
    RuntimeError
        If a circular import is detected.

    Notes
    -----
    - Modules are cached by default to prevent redundant loading.
    - Circular imports are detected and prevented.
    - The module is added to sys.modules with the specified name.
    - If check_integrity=True, the cache checks file hashes to detect changes.

    Examples
    --------
    >>> # Basic usage
    >>> my_module = include('path/to/my_module.py')
    >>> my_module.some_function()
    
    >>> # With custom name and auto-reload on changes
    >>> utils = include('utils.py', name='my_utils', check_integrity=True)
    
    >>> # Inject into global namespace (use cautiously!)
    >>> include('config.py', inject_globals=True, target_globals=globals())
    >>> print(DATABASE_URL)  # From config.py
    
    >>> # Safe import without crashing
    >>> module = include('optional.py', raise_on_error=False)
    >>> if module:
    ...     module.optional_feature()
    """
    # Resolve and validate file path
    try:
        file_path = Path(path).resolve()
    except Exception as e:
        error_msg = f"Cannot resolve path '{path}': {e}"
        if raise_on_error:
            raise ValueError(error_msg)
        if not suppress_warnings:
            logger.error(error_msg)
        return None
    
    if not file_path.exists():
        error_msg = f"File not found: {file_path}"
        if raise_on_error:
            raise FileNotFoundError(error_msg)
        if not suppress_warnings:
            logger.error(error_msg)
        return None
    
    if not file_path.is_file():
        error_msg = f"Path exists but is not a file: {file_path}"
        if raise_on_error:
            raise ValueError(error_msg)
        if not suppress_warnings:
            logger.error(error_msg)
        return None
    
    # Determine module name
    module_name = name or file_path.stem
    
    # Check for circular import
    if module_name in _IMPORT_LOCK:
        error_msg = f"Circular import detected for module '{module_name}' from {file_path}"
        if raise_on_error:
            raise RuntimeError(error_msg)
        if not suppress_warnings:
            logger.error(error_msg)
        return None
    
    # Check cache with integrity verification
    cached = _INCLUDED_CACHE.get(module_name)
    if not reload and cached:
        cached_module = cached['module']
        cached_hash = cached['hash']
        
        if check_integrity:
            try:
                current_hash = compute_module_hash(file_path)
                if current_hash != cached_hash:
                    logger.info(f"Module '{module_name}' changed, reloading...")
                    reload = True  # Force reload on hash mismatch
                else:
                    logger.debug(f"Using cached module '{module_name}' (hash verified)")
                    return cached_module
            except Exception as e:
                logger.warning(f"Cannot verify module integrity: {e}")
                return cached_module
        else:
            logger.debug(f"Using cached module '{module_name}'")
            return cached_module
    
    # Acquire lock for this module
    _IMPORT_LOCK.add(module_name)
    
    try:
        # Create module specification
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module specification for {file_path}")
        
        # Create module
        module = importlib.util.module_from_spec(spec)
        
        # Handle reload of existing module
        old_module = sys.modules.get(module_name)
        if old_module is not None and reload:
            logger.debug(f"Reloading module '{module_name}'")
            # Preserve module if reload fails
            try:
                module = importlib.reload(old_module)
                _INCLUDED_CACHE[module_name] = {
                    'module': module,
                    'hash': compute_module_hash(file_path) if check_integrity else None,
                    'path': str(file_path)
                }
                return module
            except Exception as e:
                error_msg = f"Failed to reload module '{module_name}': {e}"
                if raise_on_error:
                    raise ImportError(error_msg)
                logger.error(error_msg)
                return None
        
        # Register in sys.modules before execution (important for circular imports)
        sys.modules[module_name] = module
        
        # Execute module
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            # Clean up on execution failure
            del sys.modules[module_name]
            error_msg = f"Error executing module '{module_name}': {e}"
            if raise_on_error:
                raise ImportError(error_msg)
            if not suppress_warnings:
                logger.error(error_msg)
            return None
        
        # Cache the module
        _INCLUDED_CACHE[module_name] = {
            'module': module,
            'hash': compute_module_hash(file_path) if check_integrity else None,
            'path': str(file_path)
        }
        
        # Inject into globals if requested
        if inject_globals:
            if target_globals is None:
                # Get caller's globals
                import inspect
                frame = inspect.currentframe()
                try:
                    caller_frame = frame.f_back if frame else None
                    if caller_frame:
                        target_globals = caller_frame.f_globals
                    else:
                        raise RuntimeError("Cannot determine caller's globals")
                finally:
                    del frame
            
            if target_globals is not None:
                # Filter out special attributes (__builtins__, __name__, etc.)
                filtered_vars = {
                    k: v for k, v in vars(module).items()
                    if not k.startswith('__') or k in ('__all__',)
                }
                target_globals.update(filtered_vars)
                logger.debug(f"Injected {len(filtered_vars)} symbols from '{module_name}'")
        
        logger.info(f"Successfully imported module '{module_name}' from {file_path}")
        return module
        
    except Exception as e:
        if raise_on_error:
            raise
        if not suppress_warnings:
            logger.exception(f"Unexpected error importing '{module_name}': {e}")
        return None
        
    finally:
        # Release lock
        _IMPORT_LOCK.discard(module_name)


def clear_cache(module_name: Optional[str] = None):
    """
    Clear the module import cache.
    
    Parameters
    ----------
    module_name : str, optional
        If provided, clears only the specified module from cache.
        If None, clears the entire cache.
    
    Examples
    --------
    >>> clear_cache()  # Clear all cached modules
    >>> clear_cache('my_module')  # Clear only 'my_module'
    """
    if module_name:
        _INCLUDED_CACHE.pop(module_name, None)
        logger.debug(f"Removed module '{module_name}' from cache")
    else:
        _INCLUDED_CACHE.clear()
        logger.debug("Cleared entire module cache")


def get_cached_modules() -> Dict[str, Dict[str, Any]]:
    """
    Get information about currently cached modules.
    
    Returns
    -------
    Dict[str, Dict[str, Any]]
        Dictionary mapping module names to their cache info including:
        - 'path': Original file path
        - 'hash': File hash (if check_integrity was used)
        
    Examples
    --------
    >>> cache_info = get_cached_modules()
    >>> for name, info in cache_info.items():
    ...     print(f"{name}: {info['path']}")
    """
    return {
        name: {
            'path': info['path'],
            'has_hash': info['hash'] is not None
        }
        for name, info in _INCLUDED_CACHE.items()
    }
