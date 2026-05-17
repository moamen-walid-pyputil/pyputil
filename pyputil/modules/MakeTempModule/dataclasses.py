#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Data classes for module configuration and statistics.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Set, Any
from types import CodeType
from .enums import SafeLevel, ModulePolicy


@dataclass
class ModuleConfig:
    """
    Configuration for module security and execution limits.

    Parameters
    ----------
    Safe_level : SafeLevel, default=SafeLevel.RESTRICTED
        Security level for the module.
    policies : Set[ModulePolicy], default_factory=set
        Set of allowed operation policies.
    timeout_seconds : float, optional
        Maximum execution time in seconds.
    memory_limit_mb : int, optional
        Maximum memory usage in MB.
    cpu_limit_percent : int, optional
        Maximum CPU usage percentage.
    max_recursion_depth : int, default=100
        Maximum recursion depth.
    allowed_modules : Set[str], default_factory=set
        Set of module names that can be imported.
    allowed_builtins : Set[str], default_factory
        Set of built-in functions that can be used.
    audit_hook : Callable[[str, Dict], None], optional
        Hook function for auditing module operations.
    validation_hook : Callable[[CodeType], bool], optional
        Custom validation function for compiled code.

    Examples
    --------
    >>> config = ModuleConfig(
    ...     Safe_level=SafeLevel.SANDBOX,
    ...     timeout_seconds=10,
    ...     memory_limit_mb=100
    ... )
    """

    Safe_level: SafeLevel = SafeLevel.RESTRICTED
    policies: Set[ModulePolicy] = field(default_factory=set)
    timeout_seconds: Optional[float] = None
    memory_limit_mb: Optional[int] = None
    cpu_limit_percent: Optional[int] = None
    max_recursion_depth: int = 100
    allowed_modules: Set[str] = field(default_factory=set)
    allowed_builtins: Set[str] = field(
        default_factory=lambda: {
            "len",
            "range",
            "print",
            "str",
            "int",
            "float",
            "bool",
            "dict",
            "list",
            "set",
            "tuple",
            "enumerate",
            "zip",
            "filter",
            "map",
            "sorted",
            "reversed",
            "isinstance",
            "issubclass",
            "type",
            "object",
            "property",
            "staticmethod",
            "classmethod",
            "super",
            "Exception",
            "Warning",
        }
    )
    audit_hook: Optional[Callable[[str, Dict], None]] = None
    validation_hook: Optional[Callable[[CodeType], bool]] = None


@dataclass
class ModuleStat:
    """
    Module statistics container.

    Parameters
    ----------
    name : str
        Module name.
    ctime : float
        Creation time of module.
    safe_level : SafeLevel
        Module safety level.
    attrs_count : int
        Number of attributes in the module.
    source_available : bool
        Whether source code is available.
    is_sealed : bool
        Whether the module object is sealed.
    fingerprint : str
        Source code hash fingerprint.
    """

    name: str
    ctime: float
    safe_level: SafeLevel
    attrs_count: int
    source_available: bool
    is_sealed: bool
    fingerprint: str
