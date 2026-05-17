#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Base provider interfaces and protocols.

This module defines the base protocols and abstract base classes
for all search providers in the system.
"""

from typing import Protocol, List, Dict, Any
import sys
from pathlib import Path

from ..core.enums import SearchMethod
from ..core.models import ModuleMeta
from ..core.config import ScanConfig


class SearchProvider(Protocol):
    """
    Protocol defining the interface for module search providers.

    Search providers implement specific strategies for discovering Python
    modules through different mechanisms (file system, import system, etc.).

    Methods
    -------
    search(module: str, config: ScanConfig) -> List[ModuleMeta]
        Search for modules using the provider's specific method.
    get_stats() -> Dict[str, Any]
        Return statistics about provider usage and performance.
    supports_method(method: SearchMethod) -> bool
        Check if provider supports a specific search method.
    """

    def search(self, module: str, config: ScanConfig) -> List[ModuleMeta]:
        """
        Search for modules based on name and configuration.

        Parameters
        ----------
        module : str
            Module name, pattern, or prefix to search for
        config : ScanConfig
            Configuration options controlling search behavior

        Returns
        -------
        List[ModuleMeta]
            List of discovered modules with complete metadata

        Raises
        ------
        SearchTimeoutError
            If the search exceeds the configured timeout
        InvalidSearchMethodError
            If the provider doesn't support the requested search method
        """
        ...

    def get_stats(self) -> Dict[str, Any]:
        """
        Get provider statistics and performance metrics.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing provider statistics including:
            - searches_performed: Number of searches executed
            - modules_found: Total modules discovered
            - total_scan_time: Cumulative search time
            - last_search_time: Timestamp of last search
        """
        ...

    def supports_method(self, method: SearchMethod) -> bool:
        """
        Check if provider supports specific search method.

        Parameters
        ----------
        method : SearchMethod
            Search method to check support for

        Returns
        -------
        bool
            True if provider supports the specified method
        """
        ...


class BaseProvider:
    """
    Abstract base class for search providers.

    Provides common functionality and utilities for all providers.
    """

    def __init__(self):
        """Initialize base provider with common attributes."""
        self.stats: Dict[str, Any] = {
            "searches_performed": 0,
            "modules_found": 0,
            "total_scan_time": 0.0,
            "last_search_time": 0.0,
        }

    def _update_stats(self, modules_found: int, scan_time: float) -> None:
        """
        Update provider statistics.

        Parameters
        ----------
        modules_found : int
            Number of modules found in this search
        scan_time : float
            Time taken for this search in seconds
        """
        self.stats["searches_performed"] += 1
        self.stats["modules_found"] += modules_found
        self.stats["total_scan_time"] += scan_time
        self.stats["last_search_time"] = __import__("time").time()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get provider statistics and metrics.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing search statistics and performance data
        """
        return self.stats.copy()