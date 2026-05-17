#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Python Package Initialization Utilities
=======================================

A lightweight, utility module for working with Python package
``__init__.py`` files and package directory structures. This module provides
functions to read package initialization files, prepare package directories,
and ensure proper package structure.

Examples
--------
>>> from pyputil.util import init, init_package
>>> 
>>> # Read __init__.py from a package
>>> content = init("requests")
>>> if content:
...     print(f"Found __init__.py with {len(content)} chars")
>>> 
>>> # Prepare a package directory
>>> init_package("my_package")  # Removes __pycache__, adds __init__.py files

Notes
-----
- Namespace packages (PEP 420) without ``__init__.py`` are handled gracefully
- Built-in modules return ``None`` for ``init()``
- Operations are idempotent and safe for repeated execution
"""

import sys
import os
import shutil
import importlib.util
from types import ModuleType
from pathlib import Path
from typing import Optional, Union, List, Set

# ============================================================================
# Platform Detection
# ============================================================================

_IS_WINDOWS: bool = sys.platform == "win32"
_IS_MACOS: bool = sys.platform == "darwin"
_IS_LINUX: bool = sys.platform.startswith("linux")

# Platform-specific path separator (for display only, pathlib handles internally)
_PATH_SEP: str = "\\" if _IS_WINDOWS else "/"

# ============================================================================
# Constants
# ============================================================================

# Directories to skip during package preparation
_SKIP_DIRECTORIES: Set[str] = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".venv",
    "venv",
    "env",
    ".env",
    "build",
    "dist",
    "*.egg-info",
    "*.dist-info",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "node_modules",
}

# Files to ignore when checking for Python files
_IGNORE_FILES: Set[str] = {
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dll",
    "*.dylib",
}


def _is_python_file(filename: str) -> bool:
    """
    Check if a filename represents a Python source file.
    
    Parameters
    ----------
    filename : str
        Filename to check.
    
    Returns
    -------
    bool
        True if it's a .py file (excluding special files).
    """
    if not filename.endswith(".py"):
        return False
    
    # Exclude special files
    if filename.startswith(".") or filename.startswith("_"):
        return False
    
    return True


def _should_skip_directory(dir_path: Path) -> bool:
    """
    Check if a directory should be skipped during package preparation.
    
    Parameters
    ----------
    dir_path : Path
        Directory path to check.
    
    Returns
    -------
    bool
        True if the directory should be skipped.
    """
    name = dir_path.name
    
    # Skip hidden directories (except those that are valid packages)
    if name.startswith(".") and name not in (".", ".."):
        return True
    
    # Skip known non-package directories
    if name in _SKIP_DIRECTORIES:
        return True
    
    # Skip directories that match patterns
    for pattern in _SKIP_DIRECTORIES:
        if "*" in pattern:
            if Path(name).match(pattern):
                return True
    
    return False


def _has_python_files(directory: Path) -> bool:
    """
    Check if a directory contains any Python source files.
    
    Parameters
    ----------
    directory : Path
        Directory to check.
    
    Returns
    -------
    bool
        True if directory contains at least one .py file.
    """
    try:
        for item in directory.iterdir():
            if item.is_file() and item.suffix == ".py":
                return True
            # Also check one level deep for common patterns
            if item.is_dir() and not _should_skip_directory(item):
                for subitem in item.iterdir():
                    if subitem.is_file() and subitem.suffix == ".py":
                        return True
    except (PermissionError, OSError):
        pass
    
    return False


def get_package_parent(module: Union[str, ModuleType]) -> Optional[Path]:
    """
    Get the parent directory of a package or module.
    
    Parameters
    ----------
    module : str or ModuleType
        Module name or imported module object.
    
    Returns
    -------
    Path or None
        Parent directory path, or None if not found.
    
    Examples
    --------
    >>> get_package_parent("os")
    None  # Built-in module
    
    >>> get_package_parent("requests")
    PosixPath('/path/to/site-packages/requests')
    
    >>> get_package_parent("my_package.submodule")
    PosixPath('/path/to/my_package')
    """
    # Import if string provided
    if isinstance(module, str):
        try:
            spec = importlib.util.find_spec(module)
            if spec is None or spec.origin is None:
                return None
            origin = Path(spec.origin)
        except (ImportError, AttributeError):
            return None
    else:
        if not isinstance(module, ModuleType):
            raise TypeError(f"Expected str or ModuleType, got {type(module).__name__}")
        file_path = getattr(module, "__file__", None)
        if file_path is None:
            return None
        origin = Path(file_path)
    
    # Handle __init__.py
    if origin.is_file() and origin.name == "__init__.py":
        return origin.parent
    
    # Handle regular module
    if origin.is_file():
        return origin.parent
    
    return origin if origin.is_dir() else None


def init(module: Union[str, ModuleType]) -> Optional[str]:
    """
    Read and return the contents of a module's ``__init__.py`` file.
    
    This function locates the package directory for a given module and
    reads its ``__init__.py`` file if it exists.
    
    Parameters
    ----------
    module : str or ModuleType
        Module name (e.g., ``"requests"``) or an already imported module object.
    
    Returns
    -------
    str or None
        Contents of the ``__init__.py`` file if the module is a package
        with a physical ``__init__.py`` file. Returns ``None`` if:
        
        - The module is not a package
        - The module is a built-in module
        - The module is a namespace package (PEP 420)
        - The ``__init__.py`` file cannot be read
    
    Raises
    ------
    TypeError
        If ``module`` is not a string or ``ModuleType``.
    ImportError
        If the module name cannot be imported.
    
    Examples
    --------
    >>> # Using module name
    >>> content = init("requests")
    >>> if content:
    ...     print(f"Found __init__.py ({len(content)} characters)")
    
    >>> # Using imported module
    >>> import json
    >>> content = init(json)
    
    >>> # Built-in modules return None
    >>> init("sys") is None
    True
    
    >>> # Namespace packages return None
    >>> init("namespace_package") is None
    True
    
    Notes
    -----
    - Only packages with a physical ``__init__.py`` file are supported.
    - Built-in and namespace packages (PEP 420) return ``None``.
    - The file is read with UTF-8 encoding.
    - Line endings are preserved as in the original file.
    
    See Also
    --------
    init_package : Prepare and clean a package directory
    get_package_parent : Get parent directory of a package
    """
    # Import if string provided
    if isinstance(module, str):
        try:
            module = importlib.import_module(module)
        except ImportError as exc:
            raise ImportError(f"Failed to import module '{module}'") from exc
    
    # Validate module type
    if not isinstance(module, ModuleType):
        raise TypeError(
            f"Expected module name or ModuleType, got {type(module).__name__}"
        )
    
    # Get module file path
    file_path = getattr(module, "__file__", None)
    if file_path is None:
        # Built-in or namespace package
        return None
    
    path = Path(file_path)
    
    # Check if this is an __init__.py file
    if path.name != "__init__.py":
        # Could be a module inside a package, check parent
        parent_init = path.parent / "__init__.py"
        if parent_init.exists():
            path = parent_init
        else:
            return None
    
    # Verify file exists and is readable
    if not path.is_file():
        return None
    
    # Read the file
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # File exists but cannot be read (permissions or encoding issues)
        return None


def init_package(
    pkg_name: str,
    *,
    clean_cache: bool = True,
    create_missing: bool = True,
    dry_run: bool = False,
) -> Optional[ModuleType]:
    """
    Prepare and normalize a Python package directory structure.
    
    This function performs maintenance operations on a package directory:
    
    1. **Remove bytecode cache**: Recursively deletes all ``__pycache__`` 
       directories within the package.
    2. **Create missing __init__.py**: Ensures every directory containing 
       Python source files has an ``__init__.py`` file.
    
    Parameters
    ----------
    pkg_name : str
        Name of the target package to prepare (e.g., ``"my_package"``).
    clean_cache : bool, default=True
        If True, remove all ``__pycache__`` directories in the package.
    create_missing : bool, default=True
        If True, create ``__init__.py`` files in directories that contain
        Python files but lack an ``__init__.py``.
    dry_run : bool, default=False
        If True, simulate operations without actually modifying the filesystem.
        Returns the operations that would be performed.
    
    Returns
    -------
    ModuleType or None
        The initialized module instance, or None if:
        
        - Package cannot be found
        - Package is a single file module
        - dry_run is True (returns None)
    
    Raises
    ------
    ImportError
        If the package cannot be found or imported.
    
    Examples
    --------
    >>> # Basic usage - clean and prepare package
    >>> init_package("my_package")
    <module 'my_package' from '/path/to/my_package/__init__.py'>
    
    >>> # Only remove __pycache__, don't create __init__.py
    >>> init_package("my_package", create_missing=False)
    
    >>> # Preview what would be done
    >>> init_package("my_package", dry_run=True)
    Would remove: /path/to/my_package/__pycache__
    Would create: /path/to/my_package/subdir/__init__.py
    
    >>> # Handle single-file modules gracefully
    >>> init_package("my_module")  # Returns None if not a package
    
    Notes
    -----
    - This function modifies files and directories directly on disk.
    - Operations are idempotent - safe to run multiple times.
    - Namespace packages (PEP 420) are handled correctly.
    - Hidden directories and common non-package directories are skipped.
    
    See Also
    --------
    init : Read __init__.py contents
    """
    # Find package specification
    spec = importlib.util.find_spec(pkg_name)
    if spec is None or spec.origin is None:
        raise ImportError(f"Package '{pkg_name}' not found")
    
    # Get package root directory
    origin = Path(spec.origin)
    
    # Handle __init__.py file
    if origin.is_file() and origin.name == "__init__.py":
        package_root = origin.parent
    elif origin.is_file():
        # Single-file module, not a package
        return None
    else:
        package_root = origin
    
    # Verify it's a directory
    if not package_root.is_dir():
        return None
    
    # Track operations for dry run
    removed_dirs: List[Path] = []
    created_files: List[Path] = []
    
    # Walk the package directory
    for path in package_root.rglob("*"):
        # Skip directories that should be ignored
        if path.is_dir() and _should_skip_directory(path):
            continue
        
        # Remove __pycache__ directories
        if clean_cache and path.is_dir() and path.name == "__pycache__":
            if dry_run:
                removed_dirs.append(path)
            else:
                try:
                    shutil.rmtree(path)
                except (PermissionError, OSError):
                    # Skip if cannot remove (permissions, locked files)
                    pass
            continue
        
        # Check directories that need __init__.py
        if create_missing and path.is_dir():
            init_file = path / "__init__.py"
            
            # Skip if __init__.py already exists
            if init_file.exists():
                continue
            
            # Check if directory contains Python files
            if _has_python_files(path):
                if dry_run:
                    created_files.append(init_file)
                else:
                    try:
                        # Create empty __init__.py
                        init_file.write_text("", encoding="utf-8")
                    except (PermissionError, OSError):
                        # Skip if cannot write
                        pass
    
    # Report dry run results
    if dry_run:
        if removed_dirs:
            print("Would remove __pycache__ directories:")
            for d in removed_dirs:
                print(f"  {d}")
        if created_files:
            print("Would create __init__.py files:")
            for f in created_files:
                print(f"  {f}")
        if not removed_dirs and not created_files:
            print("No changes needed - package is already clean.")
        return None
    
    # Import and return the package
    return importlib.import_module(pkg_name)


def has_init(module: Union[str, ModuleType]) -> bool:
    """
    Check if a module has an __init__.py file.
    
    Parameters
    ----------
    module : str or ModuleType
        Module name or imported module object.
    
    Returns
    -------
    bool
        True if the module has a physical __init__.py file.
    
    Examples
    --------
    >>> has_init("requests")
    True
    
    >>> has_init("sys")
    False  # Built-in module
    
    >>> has_init("my_namespace")
    False  # Namespace package
    """
    content = init(module)
    return content is not None


def get_init_path(module: Union[str, ModuleType]) -> Optional[str]:
    """
    Get the path to a module's __init__.py file.
    
    Parameters
    ----------
    module : str or ModuleType
        Module name or imported module object.
    
    Returns
    -------
    str or None
        Path to __init__.py file, or None if not found.
    
    Examples
    --------
    >>> get_init_path("requests")
    '/path/to/site-packages/requests/__init__.py'
    
    >>> get_init_path("sys") is None
    True
    """
    if isinstance(module, str):
        try:
            module = importlib.import_module(module)
        except ImportError:
            return None
    
    if not isinstance(module, ModuleType):
        return None
    
    file_path = getattr(module, "__file__", None)
    if file_path is None:
        return None
    
    path = Path(file_path)
    
    if path.name == "__init__.py" and path.is_file():
        return str(path)
    
    # Check if parent has __init__.py
    parent_init = path.parent / "__init__.py"
    if parent_init.is_file():
        return str(parent_init)
    
    return None


def create_init(
    directory: Union[str, Path],
    *,
    content: str = "",
    exist_ok: bool = True,
) -> Optional[str]:
    """
    Create an __init__.py file in a directory.
    
    Parameters
    ----------
    directory : str or Path
        Directory where __init__.py should be created.
    content : str, default=""
        Content to write to the __init__.py file.
    exist_ok : bool, default=True
        If False, raise error when file already exists.
    
    Returns
    -------
    str or None
        Path to created file, or None if skipped.
    
    Raises
    ------
    FileExistsError
        If exist_ok=False and file already exists.
    NotADirectoryError
        If directory is not a directory.
    
    Examples
    --------
    >>> create_init("./my_package/subdir")
    './my_package/subdir/__init__.py'
    
    >>> create_init("./my_package", content='__version__ = "1.0.0"')
    './my_package/__init__.py'
    
    >>> create_init("./my_package", exist_ok=False)
    FileExistsError: __init__.py already exists
    """
    directory = Path(directory).resolve()
    
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
    
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")
    
    init_file = directory / "__init__.py"
    
    if init_file.exists():
        if exist_ok:
            return None
        raise FileExistsError(f"__init__.py already exists: {init_file}")
    
    init_file.write_text(content, encoding="utf-8")
    return str(init_file)


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    "init",
    "init_package",
    "has_init",
    "get_init_path",
    "create_init",
]
