#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
MakeModule - A Python module maker.

This package provides tools for creating, modifying, building,
publishing, and profiling Python modules with thread-safe.
"""

from .core import MakeModule
from .dataclasses import ModuleMetadata, ModuleStats, ProfileModule
from .enums import ModuleState
from .hasher import CryptographicHasher
from .registry import ThreadSafeRegistry
from .cache import MakeCache


__all__ = [
    "MakeModule",
    "ModuleMetadata",
    "ModuleStats",
    "ProfileModule",
    "ModuleState",
    "CryptographicHasher",
    "ThreadSafeRegistry",
    "MakeCache",
]


