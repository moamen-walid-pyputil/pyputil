#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Target string parsing utilities for the import system.
"""

from typing import Tuple, Optional
import os
import re


def parse_target(target: str) -> Tuple[str, Optional[str]]:
    """
    Parse import target string into module name and optional attribute.
    
    Supports multiple formats:
    - "module" -> ("module", None)
    - "module:attr" -> ("module", "attr")
    - "module.submodule" -> ("module.submodule", None)
    - "module.submodule:attr" -> ("module.submodule", "attr")
    - "./path/module.py" -> ("./path/module.py", None) (for file mode)
    
    Parameters
    ----------
    target : str
        Target string to parse.
    
    Returns
    -------
    Tuple[str, Optional[str]]
        A tuple of (module_name, attribute_name).
        attribute_name may be None if not specified.
    
    Examples
    --------
    >>> parse_target("os")
    ('os', None)
    >>> parse_target("json:loads")
    ('json', 'loads')
    >>> parse_target("pathlib:Path")
    ('pathlib', 'Path')
    """
    # Check for attribute separator
    if ':' in target:
        module_part, attr_part = target.split(':', 1)
        return module_part.strip(), attr_part.strip()
    
    return target.strip(), None


def is_file_path(target: str) -> bool:
    """
    Check if target appears to be a file path.
    
    Parameters
    ----------
    target : str
        Target string to check.
    
    Returns
    -------
    bool
        True if target looks like a file path.
    
    Examples
    --------
    >>> is_file_path("./module.py")
    True
    >>> is_file_path("os")
    False
    """
    # Check for path indicators
    path_indicators = ['./', '.\\', '/', '\\', '..']
    return any(target.startswith(ind) for ind in path_indicators) or \
           target.endswith('.py') or \
           os.path.sep in target


def extract_module_name(target: str) -> str:
    """
    Extract just the module name from target, ignoring attribute.
    
    Parameters
    ----------
    target : str
        Target string (e.g., "json:loads").
    
    Returns
    -------
    str
        Module name part only.
    
    Examples
    --------
    >>> extract_module_name("json:loads")
    'json'
    >>> extract_module_name("os.path")
    'os.path'
    """
    return parse_target(target)[0]


def normalize_module_path(path: str) -> str:
    """
    Normalize a module file path for consistent caching.
    
    Parameters
    ----------
    path : str
        File path to normalize.
    
    Returns
    -------
    str
        Absolute, normalized path.
    """
    return os.path.abspath(os.path.normpath(path))


def split_dotted_path(dotted_path: str) -> list:
    """
    Split a dotted module path into components.
    
    Parameters
    ----------
    dotted_path : str
        Dotted module path (e.g., "os.path.join").
    
    Returns
    -------
    list
        List of path components.
    
    Examples
    --------
    >>> split_dotted_path("os.path.join")
    ['os', 'path', 'join']
    """
    return dotted_path.split('.')