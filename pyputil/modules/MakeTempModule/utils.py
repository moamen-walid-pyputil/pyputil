#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Utility functions and context managers for module execution.
"""

import sys
import warnings
from contextlib import contextmanager
from typing import Optional
from .dataclasses import ModuleConfig


@contextmanager
def _execution_context(config: ModuleConfig, module_name: str):
    """
    Context manager for module execution.

    Sets up execution context with configured recursion limit
    and audit hooks, restoring original state on exit.

    Parameters
    ----------
    config : ModuleConfig
        Module configuration.
    module_name : str
        Name of the module being executed.

    Yields
    ------
    None

    Examples
    --------
    >>> with _execution_context(config, "my_module"):
    ...     exec(code, namespace)
    """
    # Save original settings
    original_recursion_limit = sys.getrecursionlimit()
    original_audit_hook = (
        getattr(sys, "audit_hook", None) if hasattr(sys, "audit_hook") else None
    )

    try:
        # Apply new settings
        sys.setrecursionlimit(config.max_recursion_depth)

        if config.audit_hook and hasattr(sys, "addaudithook"):
            sys.addaudithook(config.audit_hook)

        # Execute code
        yield

    finally:
        # Restore original settings
        sys.setrecursionlimit(original_recursion_limit)

        if original_audit_hook and hasattr(sys, "audit_hook"):
            sys.audit_hook = original_audit_hook


def validate_module_name(module_name: str) -> bool:
    """
    Validate Python module name.

    Parameters
    ----------
    module_name : str
        Module name to validate.

    Returns
    -------
    bool
        True if valid, False otherwise.

    Examples
    --------
    >>> validate_module_name("my_module")
    True
    >>> validate_module_name("123module")
    False
    """
    return isinstance(module_name, str) and module_name.isidentifier()


def safe_import_warning(module_name: str) -> None:
    """
    Issue warning when module already exists in sys.modules.

    Parameters
    ----------
    module_name : str
        Module name that already exists.

    Examples
    --------
    >>> safe_import_warning("os")
    RuntimeWarning: Module 'os' already exists in sys.modules
    """
    warnings.warn(
        f"Module '{module_name}' already exists in sys.modules",
        RuntimeWarning,
        stacklevel=3,
    )


def get_safe_builtins_config(config: ModuleConfig) -> set:
    """
    Get safe builtins configuration.

    Parameters
    ----------
    config : ModuleConfig
        Module configuration.

    Returns
    -------
    set
        Set of allowed built-in functions.

    Examples
    --------
    >>> config = ModuleConfig()
    >>> builtins = get_safe_builtins_config(config)
    """
    if hasattr(config, "allowed_builtins"):
        return config.allowed_builtins
    return set()
