#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Enumeration definitions for module classification and search methods.

This module defines all enumeration types used throughout the scanner
for categorizing modules and specifying search behavior.
"""

from enum import Enum


class SearchMethod(Enum):
    """
    Enumeration of available search methods for module discovery.

    Attributes
    ----------
    EXACT : str
        Exact match search using full module names. This method performs
        precise matching against module names without any pattern expansion.
    PATTERN : str
        Pattern-based search using glob patterns. Supports wildcards like
        '*' and '?' for flexible matching.
    PREFIX : str
        Prefix-based search for modules starting with given string. Useful
        for discovering modules that share a common namespace.
    ALL : str
        Combination of all search methods. Returns results from exact,
        pattern, and prefix searches combined with duplicates removed.
    """

    EXACT = "exact"
    PATTERN = "pattern"
    PREFIX = "prefix"
    ALL = "all"


class ModuleType(Enum):
    """
    Classification of module types for filtering and analysis.

    Attributes
    ----------
    MODULE : str
        Single Python file (.py) that is not a package.
    PACKAGE : str
        Directory containing __init__.py, making it a regular package.
    NAMESPACE_PACKAGE : str
        Directory without __init__.py following PEP 420 namespace package specification.
    BUILTIN : str
        Built-in modules compiled into Python interpreter (e.g., sys, os).
    C_EXTENSION : str
        C extension modules (.so, .pyd, .dll) that are compiled.
    FROZEN : str
        Frozen modules embedded in Python binary (e.g., frozen modules).
    """

    MODULE = "module"
    PACKAGE = "package"
    NAMESPACE_PACKAGE = "namespace_package"
    BUILTIN = "builtin"
    C_EXTENSION = "c_extension"
    FROZEN = "frozen"


class ScanStatus(Enum):
    """
    Status indicators for scan operations.

    Attributes
    ----------
    PENDING : str
        Scan is queued but not yet started.
    RUNNING : str
        Scan is currently in progress.
    COMPLETED : str
        Scan completed successfully.
    FAILED : str
        Scan failed due to errors.
    PARTIAL : str
        Scan completed partially with some errors.
    CACHED : str
        Results retrieved from cache.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CACHED = "cached"