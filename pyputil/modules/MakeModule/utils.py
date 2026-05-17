#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Utility functions and constants for module management.
"""

import sys
from pathlib import Path
from typing import Optional
import site


def validate_module_name(name: str) -> bool:
    """
    Validate a Python module name.

    Parameters
    ----------
    name : str
        Module name to validate

    Returns
    -------
    bool
        True if name is valid

    Notes
    -----
    Valid module names must follow Python identifier rules.
    """
    import keyword
    import re

    if not isinstance(name, str):
        return False

    if keyword.iskeyword(name):
        return False

    # Check for valid identifier
    if not name.isidentifier():
        return False

    # Additional validation
    if re.search(r"[^a-zA-Z0-9_]", name.replace(".", "")):
        return False

    return True


def atomic_write(file_path: Path, content: str) -> None:
    """
    Write content to file atomically.

    Parameters
    ----------
    file_path : Path
        Target file path
    content : str
        Content to write

    Raises
    ------
    OSError
        If file operation fails
    """
    temp_file = file_path.with_suffix(".tmp")

    try:
        # Write to temporary file
        temp_file.write_text(content, encoding="utf-8")

        # Atomic replace
        temp_file.replace(file_path)
    finally:
        # Cleanup temporary file if it still exists
        if temp_file.exists():
            temp_file.unlink()


def compute_directory_size(path: Path) -> int:
    """
    Compute total size of all files in a directory recursively.

    Parameters
    ----------
    path : Path
        Directory path

    Returns
    -------
    int
        Total size in bytes
    """
    total_size = 0

    for file_path in path.rglob("*"):
        if file_path.is_file():
            try:
                total_size += file_path.stat().st_size
            except OSError:
                continue

    return total_size


def get_file_count(path: Path) -> int:
    """
    Count files in a directory recursively.

    Parameters
    ----------
    path : Path
        Directory path

    Returns
    -------
    int
        Number of files
    """
    return len([f for f in path.rglob("*") if f.is_file()])


def get_directory_count(path: Path) -> int:
    """
    Count directories in a directory recursively.

    Parameters
    ----------
    path : Path
        Directory path

    Returns
    -------
    int
        Number of directories (excluding the root)
    """
    return len([d for d in path.rglob("*") if d.is_dir()])


# Global constants
sites = site.getsitepackages()
SITE_PATH = sites[0] if sites else None
