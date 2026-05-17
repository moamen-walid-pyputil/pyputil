#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Data models for module metadata and scan results.

This module defines the core data structures used to represent
module information and scan operation results.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import time

from .enums import ModuleType, ScanStatus


@dataclass
class ModuleMeta:
    """
    Comprehensive metadata for discovered Python modules and packages.

    This class provides detailed information about modules discovered through
    various search methods, including file properties and import characteristics.

    Attributes
    ----------
    name : str
        Full qualified name of the module (e.g., 'package.submodule.utils')
    path : Optional[str]
        Absolute file path to module file or package directory
    is_package : bool
        True if this represents a package (contains submodules)
    module_type : ModuleType
        Classification of the module type for filtering and analysis
    file_size : Optional[int]
        Size of module file in bytes, None for built-in modules
    encoding : Optional[str]
        File encoding detected or assumed for the module
    init_exists : bool
        For packages, indicates presence of __init__.py file
    modified_time : Optional[float]
        Last modification timestamp from file
    created_time : Optional[float]
        Creation timestamp from file (platform dependent)
    depth : int
        Number of dot-separated components in module name
    loader : str
        Type of loader that discovered this module
    has_docstring : bool
        Indicates if module contains a docstring
    source_available : bool
        True if Python source code is available for inspection
    dependencies : List[str]
        List of imported module names found in source code
    hash : Optional[str]
        SHA-256 hash of module content for change detection
    line_count : Optional[int]
        Number of lines in the module file (if source available)
    """

    name: str
    path: Optional[str]
    is_package: bool
    module_type: ModuleType
    file_size: Optional[int] = None
    encoding: Optional[str] = None
    init_exists: bool = False
    modified_time: Optional[float] = None
    created_time: Optional[float] = None
    depth: int = 0
    loader: str = ""
    has_docstring: bool = False
    source_available: bool = True
    dependencies: List[str] = field(default_factory=list)
    hash: Optional[str] = None
    line_count: Optional[int] = None

    def __post_init__(self) -> None:
        """Calculate depth if not provided."""
        if self.depth == 0 and self.name:
            self.depth = len(self.name.split("."))

    @property
    def is_namespace_package(self) -> bool:
        """
        Check if module is a namespace package.

        Returns
        -------
        bool
            True if module_type is NAMESPACE_PACKAGE
        """
        return self.module_type == ModuleType.NAMESPACE_PACKAGE

    @property
    def is_c_extension(self) -> bool:
        """
        Check if module is a C extension.

        Returns
        -------
        bool
            True if module_type is C_EXTENSION
        """
        return self.module_type == ModuleType.C_EXTENSION

    @property
    def is_builtin(self) -> bool:
        """
        Check if module is built-in.

        Returns
        -------
        bool
            True if module_type is BUILTIN
        """
        return self.module_type == ModuleType.BUILTIN


@dataclass
class ScanResult:
    """
    Comprehensive container for module search operation results.

    Provides detailed information about search execution including timing,
    statistics, and discovered modules with their metadata.

    Attributes
    ----------
    query : str
        Original search string or pattern used for scanning
    results : List[ModuleMeta]
        List of discovered modules with complete metadata
    search_paths : List[str]
        All directories and paths that were searched
    search_method : SearchMethod
        Method used for the search operation
    cache_used : bool
        Indicates if results were served from cache
    scan_duration : float
        Time taken to complete the scan in seconds
    total_modules_found : int
        Count of all modules discovered
    packages_found : int
        Count of packages discovered
    modules_by_type : Dict[ModuleType, int]
        Breakdown of modules by type classification
    errors : List[str]
        Any errors encountered during scanning
    timestamp : float
        When the scan was performed (Unix timestamp)
    status : ScanStatus
        Status of the scan operation
    warnings : List[str]
        Warning messages generated during scanning
    """

    query: str
    results: List[ModuleMeta] = field(default_factory=list)
    search_paths: List[str] = field(default_factory=list)
    search_method: "SearchMethod" = None  # type: ignore
    cache_used: bool = False
    scan_duration: float = 0.0
    total_modules_found: int = 0
    packages_found: int = 0
    modules_by_type: Dict[ModuleType, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    status: ScanStatus = ScanStatus.COMPLETED
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize default values for optional fields."""
        if self.search_method is None:
            from .enums import SearchMethod
            self.search_method = SearchMethod.EXACT

    @property
    def success_rate(self) -> float:
        """
        Calculate success rate of the scan operation.

        Returns
        -------
        float
            Percentage of successful operations (0-100)
        """
        total_operations = self.total_modules_found + len(self.errors)
        if total_operations == 0:
            return 100.0
        return (self.total_modules_found / total_operations) * 100

    @property
    def has_errors(self) -> bool:
        """
        Check if scan encountered any errors.

        Returns
        -------
        bool
            True if errors list is not empty
        """
        return len(self.errors) > 0