#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Utility functions for the metadata builder.

Provides helper functions for hashing, timing, and various operations.
"""

import hashlib
import time
import inspect
import sys
import os
from typing import Any, Optional, List, Dict, Callable
from pathlib import Path
import importlib.util
import warnings


def hash_bytes(data: bytes, algorithm: str = "sha256") -> str:
    """Hash bytes using specified algorithm.

    Parameters
    ----------
    data : bytes
        Data to hash
    algorithm : str, optional
        Hash algorithm (default='sha256')
        Options: 'md5', 'sha1', 'sha256', 'sha512'

    Returns
    -------
    str
        Hexadecimal hash string

    Raises
    ------
    ValueError
        If algorithm is not supported

    Examples
    --------
    >>> hash_bytes(b'hello', 'sha256')
    '2cf24dba5fb0a30e...'
    """
    if algorithm not in hashlib.algorithms_available:
        raise ValueError(f"Algorithm '{algorithm}' not available")

    hasher = hashlib.new(algorithm)
    hasher.update(data)
    return hasher.hexdigest()


def hash_string(text: str, algorithm: str = "sha256") -> str:
    """Hash a string using specified algorithm.

    Parameters
    ----------
    text : str
        String to hash
    algorithm : str, optional
        Hash algorithm (default='sha256')

    Returns
    -------
    str
        Hexadecimal hash string
    """
    return hash_bytes(text.encode("utf-8"), algorithm)


def safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    """Safely get attribute with error handling.

    Parameters
    ----------
    obj : Any
        Object to get attribute from
    name : str
        Attribute name
    default : Any, optional
        Default value if attribute access fails

    Returns
    -------
    Any
        Attribute value or default

    Examples
    --------
    >>> safe_getattr(sys, 'version')
    '3.9.0'
    >>> safe_getattr(None, 'missing', 'default')
    'default'
    """
    try:
        return inspect.getattr_static(obj, name)
    except (AttributeError, TypeError):
        return default


def time_function(func: Callable) -> Callable:
    """Decorator to measure function execution time.

    Parameters
    ----------
    func : Callable
        Function to time

    Returns
    -------
    Callable
        Wrapped function that returns (result, execution_time_ms)

    Examples
    --------
    >>> @time_function
    ... def slow_function():
    ...     time.sleep(0.1)
    >>> result, exec_time = slow_function()
    >>> exec_time > 100  # milliseconds
    True
    """

    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        exec_time_ms = (end - start) * 1000
        return result, exec_time_ms

    return wrapper


def get_module_size(module) -> Optional[int]:
    """Estimate module memory size.

    Parameters
    ----------
    module : ModuleType
        Module to estimate size for

    Returns
    -------
    Optional[int]
        Estimated size in bytes, None if cannot estimate

    Notes
    -----
    This is an approximation using sys.getsizeof() on attributes.
    It may not be accurate for all module types.
    """
    try:
        total = sys.getsizeof(module)
        for attr_name in dir(module):
            try:
                attr = getattr(module, attr_name)
                total += sys.getsizeof(attr)
            except:
                continue
        return total
    except:
        return None


def extract_examples_from_doc(docstring: Optional[str]) -> List[str]:
    """Extract code examples from docstring.

    Parameters
    ----------
    docstring : Optional[str]
        Docstring to parse

    Returns
    -------
    List[str]
        List of code examples

    Notes
    -----
    Looks for lines starting with '>>>' or '...' (doctest format).
    """
    if not docstring:
        return []

    examples = []
    lines = docstring.split("\n")
    example_lines = []
    in_example = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">>>") or stripped.startswith("..."):
            in_example = True
            example_lines.append(stripped)
        elif in_example and stripped and not stripped.startswith("#"):
            example_lines.append(stripped)
        elif in_example and not stripped:
            if example_lines:
                examples.append("\n".join(example_lines))
                example_lines = []
            in_example = False

    if example_lines:
        examples.append("\n".join(example_lines))

    return examples


def is_private_attr(name: str) -> bool:
    """Check if attribute name is private.

    Parameters
    ----------
    name : str
        Attribute name

    Returns
    -------
    bool
        True if name starts with '_' (private convention)

    Examples
    --------
    >>> is_private_attr('_private')
    True
    >>> is_private_attr('public')
    False
    >>> is_private_attr('__magic__')
    True
    """
    return name.startswith("_")


def normalize_module_name(name: str) -> str:
    """Normalize module name for consistent hashing.

    Parameters
    ----------
    name : str
        Module name

    Returns
    -------
    str
        Normalized module name
    """
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def get_source_file(module) -> Optional[str]:
    """Get source file path for module.

    Parameters
    ----------
    module : ModuleType
        Module to inspect

    Returns
    -------
    Optional[str]
        Path to source file, None if not available
    """
    # Try __file__ first
    file = getattr(module, "__file__", None)
    if file:
        return file

    # Try __spec__.origin
    spec = getattr(module, "__spec__", None)
    if spec and spec.origin and spec.origin != "builtin":
        return spec.origin

    # Try inspect
    try:
        source_file = inspect.getsourcefile(module)
        return source_file
    except (TypeError, OSError):
        return None


def get_package_info(module) -> Optional[str]:
    """Get package information for module.

    Parameters
    ----------
    module : ModuleType
        Module to inspect

    Returns
    -------
    Optional[str]
        Package name if module is part of a package
    """
    name = getattr(module, "__name__", "")
    if "." in name:
        return name.rsplit(".", 1)[0]

    spec = getattr(module, "__spec__", None)
    if spec and spec.parent:
        return spec.parent

    return None
