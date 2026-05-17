#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Configuration management for the module scanner.

This module defines configuration classes that control scanner behavior,
including search strategies, filtering options, and performance settings.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path

from .enums import SearchMethod


@dataclass
class ScanConfig:
    """
    Configuration options for module scanning operations.

    Provides fine-grained control over search behavior, performance,
    and resource utilization during module discovery.

    Attributes
    ----------
    search_method : SearchMethod
        Primary search method to use for module discovery
    enable_cache : bool
        Enable result caching for improved performance
    max_depth : int
        Maximum depth for recursive package exploration (0 = unlimited)
    parallel_scan : bool
        Enable parallel file scanning for faster results
    workers : int
        Number of worker threads for parallel scanning
    include_builtin : bool
        Include built-in modules in search results
    include_frozen : bool
        Include frozen modules in search results
    include_c_extensions : bool
        Include C extension modules in search results
    analyze_dependencies : bool
        Perform dependency analysis on discovered modules
    follow_symlinks : bool
        Follow symbolic links during file scanning
    exclude_patterns : List[str]
        Glob patterns to exclude from search results
    timeout : Optional[float]
        Maximum time in seconds for scan operation (None = no timeout)
    case_sensitive : bool
        Whether to use case-sensitive matching
    max_file_size : Optional[int]
        Maximum file size to analyze in bytes (None = unlimited)
    include_hidden : bool
        Whether to include hidden files and directories
    custom_paths : List[Path]
        Additional custom paths to include in search
    exclude_paths : List[Path]
        Paths to exclude from search
    """

    search_method: SearchMethod = SearchMethod.EXACT
    enable_cache: bool = True
    max_depth: int = 10
    parallel_scan: bool = False
    workers: int = 4
    include_builtin: bool = True
    include_frozen: bool = True
    include_c_extensions: bool = True
    analyze_dependencies: bool = False
    follow_symlinks: bool = True
    exclude_patterns: List[str] = field(default_factory=list)
    timeout: Optional[float] = None
    case_sensitive: bool = True
    max_file_size: Optional[int] = None
    include_hidden: bool = False
    custom_paths: List[Path] = field(default_factory=list)
    exclude_paths: List[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.workers < 1:
            raise ValueError(f"workers must be at least 1, got {self.workers}")

        if self.max_depth < 0:
            raise ValueError(f"max_depth cannot be negative, got {self.max_depth}")

        if self.max_file_size is not None and self.max_file_size < 0:
            raise ValueError(
                f"max_file_size cannot be negative, got {self.max_file_size}"
            )

        if self.timeout is not None and self.timeout <= 0:
            raise ValueError(f"timeout must be positive, got {self.timeout}")

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary representation.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing all configuration parameters
        """
        return {
            "search_method": self.search_method.value,
            "enable_cache": self.enable_cache,
            "max_depth": self.max_depth,
            "parallel_scan": self.parallel_scan,
            "workers": self.workers,
            "include_builtin": self.include_builtin,
            "include_frozen": self.include_frozen,
            "include_c_extensions": self.include_c_extensions,
            "analyze_dependencies": self.analyze_dependencies,
            "follow_symlinks": self.follow_symlinks,
            "exclude_patterns": self.exclude_patterns.copy(),
            "timeout": self.timeout,
            "case_sensitive": self.case_sensitive,
            "max_file_size": self.max_file_size,
            "include_hidden": self.include_hidden,
            "custom_paths": [str(p) for p in self.custom_paths],
            "exclude_paths": [str(p) for p in self.exclude_paths],
        }