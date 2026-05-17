#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Temp Module - Code to create temporary modules during runtime.

This package provides tools for creating Python modules with
configurable security policies, resource limits, and execution controls.

Main Features:
-------------
- Create modules from source code with security validation
- Configurable security levels (NONE, RESTRICTED, SANDBOX, FROZEN)
- Resource monitoring (time, memory, CPU limits)
- AST-based security validation
- Safe builtins wrapper
- Module registry and caching
- Export/import modules to/from files
"""

from .core import (
    mkmod,
    validate_module_source,
    get_module_stats,
    cleanup,
    is_mkmod,
    to_file,
    from_file,
    get_registered_modules,
    remove_module,
    update_module_config,
)
from .enums import SafeLevel, ModulePolicy
from .dataclasses import ModuleConfig, ModuleStat


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
