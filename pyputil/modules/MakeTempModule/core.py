#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Core module for secure module creation and management.

This module provides the mkmod function for creating Python modules
with configurable security policies, resource limits, and execution
controls.
"""

import ast
import builtins
import hashlib
import inspect
import marshal
import os
import sys
import tempfile
import threading
import time
import traceback
import warnings
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import wraps
from types import ModuleType, CodeType, FunctionType
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Import local modules
from .enums import SafeLevel, ModulePolicy
from .dataclasses import ModuleConfig, ModuleStat
from .internal_classes import _ImmutableNamespace, _ResourceMonitor
from .validator import _ASTValidator
from .builtins_wrapper import _SafeBuiltins
from .registry import _ModuleRegistry
from .utils import _execution_context, validate_module_name, safe_import_warning
from .file_operations import to_file, from_file, export_module


def mkmod(
    module_name: str,
    *,
    source: Optional[str] = None,
    attrs: Optional[Dict[str, Any]] = None,
    register: bool = True,
    config: Optional[ModuleConfig] = None,
    meta: bool = True,
    enable_cache: bool = False,
    cache_ttl: Optional[float] = None,
) -> ModuleType:
    """
    Create a new module with configurable security policies.

    Creates a Python module with configurable security policies,
    resource limits, and execution controls. The module can be
    created from source code or pre-defined attributes.

    Parameters
    ----------
    module_name : str
        Name for the new module. Must be a valid Python identifier.
    source : str, optional
        Python source code to execute in the module.
    attrs : Dict[str, Any], optional
        Pre-defined attributes for the module.
    register : bool, default=True
        Whether to register the module in sys.modules.
    config : ModuleConfig, optional
        Security and resource configuration. Defaults to ModuleConfig().
    meta : bool, default=True
        Whether to add metadata attributes to the module.
    enable_cache : bool, default=False
        Whether to cache modules by source fingerprint.
    cache_ttl : float, optional
        Time-to-live for cached modules in seconds.

    Returns
    -------
    ModuleType
        The created module object.

    Raises
    ------
    ValueError
        If module_name is invalid or attribute names are illegal.
    SyntaxError
        If source code contains security violations.
    RuntimeError
        If execution of source code fails.

    Examples
    --------
    >>> module = mkmod(
    ...     "calculator",
    ...     source="def add(a, b): return a + b",
    ...     config=ModuleConfig(Safe_level=SafeLevel.SANDBOX)
    ... )
    >>> module.add(1, 2)
    3

    >>> module = mkmod(
    ...     "constants",
    ...     attrs={"PI": 3.14159, "E": 2.71828}
    ... )
    >>> module.PI
    3.14159
    """
    # Validate module name
    if not validate_module_name(module_name):
        raise ValueError(f"Invalid module name: {module_name}")

    # Check if module already exists
    if module_name in sys.modules and register:
        safe_import_warning(module_name)

    # Use default config if none provided
    if config is None:
        config = ModuleConfig()

    # Validate attributes
    attrs = attrs or {}
    for key in attrs:
        if not isinstance(key, str) or not key.isidentifier():
            raise KeyError(f"Illegal attribute name: {key}")
        if key.startswith("__") and (not key.endswith("__")):
            raise KeyError(f"Private attribute not allowed: {key}")

    # Compute fingerprint for caching
    fingerprint = None
    if source:
        fingerprint = hashlib.sha256(
            source.encode("utf-8") + module_name.encode("utf-8")
        ).hexdigest()

    # Check cache
    if enable_cache and fingerprint:
        cache_key = f"__mkmod_cache__{fingerprint}"
        cached_info = _ModuleRegistry.get_module_info(cache_key)
        if cached_info:
            cached_module = cached_info["module"]
            if cache_ttl is None or time.time() - cached_info["created"] < cache_ttl:
                return cached_module

    # Create module object
    module = ModuleType(module_name)
    ns = module.__dict__

    # Setup builtins based on security level
    if config.Safe_level in (SafeLevel.SANDBOX, SafeLevel.FROZEN):
        ns["__builtins__"] = _SafeBuiltins(
            config.allowed_builtins, builtins.__dict__, config
        )
    else:
        ns["__builtins__"] = builtins.__dict__.copy()

    # Add factory identifier
    ns.update({"__factory__": "mkmod"})

    # Add metadata if requested
    if meta:
        ns.update(
            {
                "__name__": module_name,
                "__package__": None,
                "__file__": f"<mkmod:{module_name}>",
                "__loader__": None,
                "__spec__": None,
                "__created__": time.time(),
                "__modified__": time.time(),
                "__source__": source,
                "__fingerprint__": fingerprint,
                "__Safe_level__": config.Safe_level.name,
                "__policies__": [p.name for p in config.policies],
            }
        )

    # Add pre-defined attributes
    for key, value in attrs.items():
        ns[key] = value

    # Execute source code if provided
    if source:
        try:
            # Parse and validate AST
            tree = ast.parse(source, filename=f"<mkmod:{module_name}>")
            validator = _ASTValidator(config)
            validator.visit(tree)

            # Run custom validation if provided
            if config.validation_hook:
                code_obj = compile(tree, f"<mkmod:{module_name}>", "exec")
                if not config.validation_hook(code_obj):
                    raise ValueError("Code validation failed")

            # Execute in secure context
            with _execution_context(config, module_name):
                monitor = _ResourceMonitor(config)
                code_obj = compile(tree, f"<mkmod:{module_name}>", "exec")
                ns["__code__"] = code_obj
                exec(code_obj, ns)

        except SyntaxError as e:
            error_msg = f"Syntax error in module '{module_name}': {e}"
            traceback.print_exc()
            raise SyntaxError(error_msg) from e
        except Exception as e:
            error_msg = f"Error in module '{module_name}': {e}"
            traceback.print_exc()
            raise RuntimeError(error_msg) from e

    # Apply security restrictions
    if config.Safe_level == SafeLevel.FROZEN:
        module.__dict__ = _ImmutableNamespace(ns)
        ns["__sealed__"] = True
    elif config.Safe_level == SafeLevel.SANDBOX:
        ns["__writable__"] = True
        ns["__deletable__"] = False

    # Restrict attribute modification for secure levels
    if config.Safe_level in (SafeLevel.FROZEN, SafeLevel.SANDBOX):

        def _deny_setattr(self, name: str, value: Any) -> None:
            """
            Deny setting attributes on read-only module.

            Parameters
            ----------
            name : str
                Attribute name.
            value : Any
                Attribute value.

            Raises
            ------
            AttributeError
                Always raised.
            """
            raise AttributeError(f"Cannot set attribute '{name}' on read-only module")

        def _deny_delattr(self, name: str) -> None:
            """
            Deny deleting attributes from read-only module.

            Parameters
            ----------
            name : str
                Attribute name.

            Raises
            ------
            AttributeError
                Always raised.
            """
            raise AttributeError(
                f"Cannot delete attribute '{name}' from read-only module"
            )

        # Bind denial methods to module
        module.__setattr__ = _deny_setattr.__get__(module, ModuleType)
        module.__delattr__ = _deny_delattr.__get__(module, ModuleType)

    # Register module
    if register:
        sys.modules[module_name] = module
        _ModuleRegistry.register(module, config)

        # Cache if enabled
        if enable_cache and fingerprint:
            cache_entry = _ModuleEntry(module, config)
            _ModuleRegistry._registry[f"__mkmod_cache__{fingerprint}"] = cache_entry

    return module


def validate_module_source(
    source: str, config: Optional[ModuleConfig] = None
) -> Tuple[bool, List[str]]:
    """
    Validate Python source code against security policies.

    Parameters
    ----------
    source : str
        Python source code to validate.
    config : ModuleConfig, optional
        Security configuration. Defaults to ModuleConfig().

    Returns
    -------
    Tuple[bool, List[str]]
        Tuple containing:
        - bool: True if validation passed, False otherwise.
        - List[str]: List of warnings or error messages.

    Examples
    --------
    >>> valid, warnings = validate_module_source("import os")
    >>> print(valid, warnings)
    (False, ["Syntax error: Imports are disabled in this module"])

    >>> valid, warnings = validate_module_source("def add(a, b): return a + b")
    >>> print(valid, warnings)
    (True, [])
    """
    if config is None:
        config = ModuleConfig()

    try:
        # Parse source code
        tree = ast.parse(source)

        # Validate AST
        validator = _ASTValidator(config)
        validator.visit(tree)

        # Collect warnings
        warnings = []
        if validator.imports_found:
            warnings.append(f"Found imports: {validator.imports_found}")
        if validator.unsafe_calls:
            warnings.append(f"Unsafe calls: {validator.unsafe_calls}")

        return (True, warnings)

    except Exception as e:
        return (False, [str(e)])


def get_module_stats(module_object: ModuleType) -> ModuleStat:
    """
    Get statistics and information about a created module.

    Parameters
    ----------
    module_object : ModuleType
        Mkmod module object.

    Returns
    -------
    ModuleStat
        Statistics container containing:
        - name: Module name
        - ctime: Creation timestamp
        - safe_level: Security level
        - attrs_count: Number of attributes
        - source_available: Whether source code is available
        - is_sealed: Whether module is sealed
        - fingerprint: Source code fingerprint

    Raises
    ------
    TypeError
        If module_object is not a ModuleType.
    ValueError
        If module was not created by mkmod.

    Examples
    --------
    >>> module = mkmod("test", source="x = 1")
    >>> stats = get_module_stats(module)
    >>> print(stats.name)
    "test"
    >>> print(stats.safe_level)
    "RESTRICTED"
    """
    if not isinstance(module_object, ModuleType):
        raise TypeError(f"Expected module object, got <{type(module_object).__name__}>")

    if not is_mkmod(module_object):
        raise ValueError("Expected MkMod module")

    # Extract module information
    module = module_object
    return ModuleStat(
        name=module.__name__,
        ctime=getattr(module, "__created__", None),
        safe_level=getattr(module, "__Safe_level__", None),
        attrs_count=len(dir(module)),
        source_available=bool(getattr(module, "__source__", None)),
        is_sealed=getattr(module, "__sealed__", False),
        fingerprint=getattr(module, "__fingerprint__", None),
    )


def cleanup() -> None:
    """
    Clean up internal registry and cache.

    This function cleans up the module registry and any cached
    modules. It should be called when the system is shutting down
    or when you want to free up resources.

    Examples
    --------
    >>> cleanup()
    """
    _ModuleRegistry.cleanup()


def is_mkmod(module: ModuleType) -> bool:
    """
    Check if module object was created by mkmod.

    Parameters
    ----------
    module : ModuleType
        Module object to check.

    Returns
    -------
    bool
        True if module object has __factory__ attribute,
        Otherwise False.

    Examples
    --------
    >>> module = mkmod("test")
    >>> is_mkmod(module)
    True

    >>> import os
    >>> is_mkmod(os)
    False
    """
    return hasattr(module, "__factory__")


# Re-export file operations
to_file = to_file
from_file = from_file
export_module = export_module


def get_registered_modules() -> Dict[str, ModuleType]:
    """
    Get all registered mkmod modules.

    Returns
    -------
    Dict[str, ModuleType]
        Dictionary mapping module names to module objects.

    Examples
    --------
    >>> modules = get_registered_modules()
    >>> print(list(modules.keys()))
    ['module1', 'module2']
    """
    modules = {}
    for name in _ModuleRegistry.list_modules():
        info = _ModuleRegistry.get_module_info(name)
        if info and "module" in info:
            modules[name] = info["module"]
    return modules


def remove_module(module_name: str, force: bool = False) -> bool:
    """
    Remove a registered module.

    Parameters
    ----------
    module_name : str
        Name of module to remove.
    force : bool, default=False
        If True, remove even if module is in use.

    Returns
    -------
    bool
        True if removed successfully, False otherwise.

    Examples
    --------
    >>> remove_module("test_module")
    True
    """
    try:
        # Remove from sys.modules
        if module_name in sys.modules:
            del sys.modules[module_name]

        # Remove from registry
        # Note: Registry uses weak references, so modules are
        # automatically removed when no longer referenced

        return True
    except Exception:
        return False


def update_module_config(module: ModuleType, new_config: ModuleConfig) -> bool:
    """
    Update configuration of an existing module.

    Parameters
    ----------
    module : ModuleType
        Module to update.
    new_config : ModuleConfig
        New configuration.

    Returns
    -------
    bool
        True if updated successfully, False otherwise.

    Raises
    ------
    ValueError
        If module is not a mkmod module.

    Examples
    --------
    >>> config = ModuleConfig(Safe_level=SafeLevel.SANDBOX)
    >>> update_module_config(module, config)
    True
    """
    if not is_mkmod(module):
        raise ValueError("Module was not created with mkmod")

    # Update module metadata
    module.__dict__["__Safe_level__"] = new_config.Safe_level.name
    module.__dict__["__policies__"] = [p.name for p in new_config.policies]

    # Update registry
    try:
        _ModuleRegistry.register(module, new_config)
        return True
    except Exception:
        return False


__all__ = [
    "mkmod",
    "validate_module_source",
    "get_module_stats",
    "cleanup",
    "is_mkmod",
    "to_file",
    "from_file",
    "get_registered_modules",
    "remove_module",
    "update_module_config",
    "ModuleConfig",
    "ModuleStat",
    "SafeLevel",
    "ModulePolicy",
]
