#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Utility functions for the API management system.

Provides helper functions for type detection, metadata extraction,
and other common operations.
"""

import inspect
import asyncio
import warnings
import importlib
import sys
import re
from pathlib import Path
from typing import Any, Optional, Tuple
from .enums import PrivacyLevel, APIMemberType


def determine_member_type(name: str, obj: Any) -> APIMemberType:
    """
    Determine the type of API member.

    Parameters
    ----------
    name : str
        Name of the API member
    obj : Any
        The object to inspect

    Returns
    -------
    APIMemberType
        Type of API member

    Examples
    --------
    >>> determine_member_type("calculate", lambda x: x*2)
    <APIMemberType.FUNCTION: 'function'>
    """
    if obj is None:
        return APIMemberType.VARIABLE

    if inspect.isfunction(obj):
        if asyncio.iscoroutinefunction(obj):
            return APIMemberType.ASYNC_FUNCTION
        return APIMemberType.FUNCTION

    if inspect.isclass(obj):
        return APIMemberType.CLASS

    if inspect.ismodule(obj):
        return APIMemberType.MODULE

    if isinstance(obj, property):
        return APIMemberType.PROPERTY

    if inspect.isgeneratorfunction(obj):
        return APIMemberType.GENERATOR

    if hasattr(obj, "__enter__") and hasattr(obj, "__exit__"):
        return APIMemberType.CONTEXT_MANAGER

    # Check if it's a constant (uppercase)
    if name.isupper():
        return APIMemberType.CONSTANT

    return APIMemberType.VARIABLE


def extract_docstring(obj: Any) -> Optional[str]:
    """
    Extract docstring from object.

    Parameters
    ----------
    obj : Any
        Object to extract docstring from

    Returns
    -------
    str or None
        Docstring if available

    Examples
    --------
    >>> def func():
    ...     '''Documentation'''
    ...     pass
    >>> extract_docstring(func)
    'Documentation'
    """
    if hasattr(obj, "__doc__"):
        return inspect.getdoc(obj)
    return None


def extract_signature(obj: Any) -> Optional[str]:
    """
    Extract signature from callable.

    Parameters
    ----------
    obj : Any
        Callable object

    Returns
    -------
    str or None
        Signature string

    Notes
    -----
    Returns None for non-callables or objects without valid signatures.
    """
    if callable(obj) and not isinstance(obj, type):
        try:
            sig = inspect.signature(obj)
            return str(sig)
        except (ValueError, TypeError):
            pass
    return None


def get_source_file(obj: Any) -> Optional[str]:
    """
    Get source file path for object.

    Parameters
    ----------
    obj : Any
        Object to inspect

    Returns
    -------
    str or None
        Source file path

    Notes
    -----
    Returns None for built-in objects or objects without source.
    """
    try:
        return inspect.getsourcefile(obj)
    except (TypeError, OSError):
        return None


def check_privacy_level(name: str, globals_ns: dict) -> PrivacyLevel:
    """
    Enhanced privacy level detection with additional patterns.

    Parameters
    ----------
    name : str
        Name of the API member
    globals_ns : dict
        Global namespace

    Returns
    -------
    PrivacyLevel
        Privacy level

    Examples
    --------
    >>> check_privacy_level("public_func", globals())
    <PrivacyLevel.PUBLIC: 'public'>
    >>> check_privacy_level("_private_func", globals())
    <PrivacyLevel.PRIVATE: 'private'>
    """
    if name.startswith("__") and name.endswith("__"):
        # Special check for API metadata names
        if name in ("__api_metadata__", "__api_systems__", "__api_config__"):
            return PrivacyLevel.INTERNAL
        return PrivacyLevel.INTERNAL
    elif name.startswith("__"):
        # Check if it's name-mangled private attribute
        if len(name) > 2 and not name.endswith("_"):
            if "_" in name[2:]:
                return PrivacyLevel.PRIVATE
        return PrivacyLevel.PRIVATE
    elif name.startswith("_"):
        # Single underscore - protected
        common_semi_public = {
            "_version",
            "_metadata",
            "_config",
            "_settings",
            "_constants",
            "_types",
            "_typing",
            "_utils",
        }
        if name in common_semi_public:
            return PrivacyLevel.PROTECTED
        return PrivacyLevel.PROTECTED
    else:
        # Public name
        if name.endswith("_api") or name.startswith("api_"):
            return PrivacyLevel.PUBLIC

        if name.startswith("test_") or name.endswith("_test"):
            return PrivacyLevel.PUBLIC

        return PrivacyLevel.PUBLIC


def is_submodule_access(name: str, module_name: str) -> bool:
    """
    Check if this is a request for a submodule with enhanced heuristics.

    Parameters
    ----------
    name : str
        Name being accessed
    module_name : str
        Parent module name

    Returns
    -------
    bool
        True if likely submodule access

    Notes
    -----
    Uses multiple heuristics to determine if name represents a submodule
    rather than a regular attribute.
    """
    # Basic identifier check
    if not name.isidentifier():
        return False

    # Don't treat underscore names as submodules
    if name.startswith("_"):
        return False

    # Don't treat names that look like constants as submodules
    if name.isupper():
        return False

    # Check if name resembles a module
    if not all(c.isalnum() or c == "_" for c in name):
        return False

    # Avoid common attribute names
    common_attrs = {
        "name",
        "version",
        "author",
        "license",
        "url",
        "description",
        "path",
        "file",
        "dir",
        "package",
        "module",
        "class",
        "function",
        "attr",
        "method",
        "property",
        "config",
        "settings",
        "options",
    }
    if name.lower() in common_attrs:
        return False

    # Check if it's likely a Python file in the package
    try:
        parent_module_obj = sys.modules[module_name]
        if hasattr(parent_module_obj, "__file__"):
            parent_dir = Path(parent_module_obj.__file__).parent

            # Check for .py file
            py_file = parent_dir / f"{name}.py"
            if py_file.exists():
                return True

            # Check for directory with __init__.py
            dir_with_init = parent_dir / name / "__init__.py"
            if dir_with_init.exists():
                return True

            # Check for namespace packages
            namespace_dir = parent_dir / name
            if namespace_dir.exists() and namespace_dir.is_dir():
                init_file = namespace_dir / "__init__.py"
                if not init_file.exists():
                    for item in namespace_dir.iterdir():
                        if item.suffix == ".py":
                            return True

        # Check if importable
        try:
            spec = importlib.util.find_spec(f"{module_name}.{name}")
            if spec is not None and spec.origin is not None:
                return True
        except (ImportError, ModuleNotFoundError, AttributeError):
            pass

        # Check if already imported
        full_name = f"{module_name}.{name}"
        if full_name in sys.modules:
            return True

    except (KeyError, AttributeError, TypeError, OSError):
        pass

    return False


def lazy_load_submodule(name: str, parent_module: str) -> Any:
    """
    Lazily load a submodule with enhanced error handling and caching.

    Parameters
    ----------
    name : str
        Submodule name
    parent_module : str
        Parent module name

    Returns
    -------
    Any
        Loaded module

    Raises
    ------
    AccessError
        If submodule cannot be loaded
    ImportError
        If import fails

    Notes
    -----
    Tries multiple strategies to load submodules including direct import,
    relative import, file loading, and namespace packages.
    """
    import importlib
    import importlib.util

    # Check if already loaded
    full_name = f"{parent_module}.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    try:
        # Try direct import
        module = importlib.import_module(full_name)
        return module
    except ImportError:
        pass

    # Try relative import
    try:
        module = importlib.import_module(f".{name}", parent_module)
        return module
    except ImportError:
        pass

    # Check parent module for file-based loading
    parent_module_obj = sys.modules.get(parent_module)
    if parent_module_obj and hasattr(parent_module_obj, "__file__"):
        parent_path = Path(parent_module_obj.__file__).parent

        # Check for .py file
        py_file = parent_path / f"{name}.py"
        if py_file.exists():
            try:
                spec = importlib.util.spec_from_file_location(full_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[full_name] = module
                    spec.loader.exec_module(module)
                    return module
            except Exception as file_error:
                raise ImportError(
                    f"Cannot load module from file {py_file}: {file_error}"
                )

        # Check for directory package
        dir_path = parent_path / name
        init_file = dir_path / "__init__.py"
        if init_file.exists():
            try:
                spec = importlib.util.spec_from_file_location(
                    full_name, init_file, submodule_search_locations=[str(dir_path)]
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[full_name] = module
                    spec.loader.exec_module(module)
                    return module
            except Exception as dir_error:
                raise ImportError(f"Cannot load package from {dir_path}: {dir_error}")

    # Try as top-level module
    try:
        module = importlib.import_module(name)
        warnings.warn(
            f"'{name}' is a top-level module, not a submodule of '{parent_module}'",
            ImportWarning,
            stacklevel=3,
        )
        return module
    except ImportError:
        pass

    # Find available submodules for better error message
    available = find_available_submodules(parent_module)

    if available:
        suggestion = f" Available submodules: {', '.join(sorted(available))}"
    else:
        suggestion = " No submodules available."

    raise ImportError(
        f"Cannot load submodule '{name}' from '{parent_module}'.{suggestion}"
    )


def find_available_submodules(parent_module: str) -> list:
    """
    Find available submodules in a package.

    Parameters
    ----------
    parent_module : str
        Parent module name

    Returns
    -------
    list
        List of available submodule names
    """
    try:
        parent_module_obj = sys.modules.get(parent_module)
        if not parent_module_obj or not hasattr(parent_module_obj, "__file__"):
            return []

        parent_path = Path(parent_module_obj.__file__).parent
        submodules = []

        # Look for .py files
        for py_file in parent_path.glob("*.py"):
            if py_file.stem != "__init__" and not py_file.stem.startswith("_"):
                submodules.append(py_file.stem)

        # Look for directories with __init__.py
        for item in parent_path.iterdir():
            if item.is_dir():
                init_file = item / "__init__.py"
                if init_file.exists() and not item.name.startswith("_"):
                    submodules.append(item.name)

        return sorted(submodules)

    except Exception:
        return []
