#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Enumerations for module security and policy management.
"""

from enum import Enum, auto


class SafeLevel(Enum):
    """
    Security levels for module execution.

    Defines the level of security restrictions applied to a module.
    Higher levels provide more restrictions and isolation.

    Attributes
    ----------
    NONE : int
        No security restrictions. Full Python capabilities.
    RESTRICTED : int
        Basic security restrictions applied.
    SANDBOX : int
        Isolated environment with limited access.
    FROZEN : int
        Read-only module with maximum restrictions.
    """

    NONE = auto()
    RESTRICTED = auto()
    SANDBOX = auto()
    FROZEN = auto()


class ModulePolicy(Enum):
    """
    Policies controlling what operations are allowed in a module.

    Each policy enables or disables specific categories of operations.

    Attributes
    ----------
    ALLOW_IMPORTS : int
        Allow import statements.
    ALLOW_NATIVE : int
        Allow native/C extensions.
    ALLOW_FILE_IO : int
        Allow file operations.
    ALLOW_NETWORK : int
        Allow network operations.
    ALLOW_SUBPROCESS : int
        Allow subprocess creation.
    ALLOW_REFLECTION : int
        Allow reflection operations.
    ALLOW_MEMORY_ACCESS : int
        Allow direct memory access.
    """

    ALLOW_IMPORTS = auto()
    ALLOW_NATIVE = auto()
    ALLOW_FILE_IO = auto()
    ALLOW_NETWORK = auto()
    ALLOW_SUBPROCESS = auto()
    ALLOW_REFLECTION = auto()
    ALLOW_MEMORY_ACCESS = auto()
