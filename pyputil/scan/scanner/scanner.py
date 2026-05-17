#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Core scanner implementation.

This module contains the main Scanner class that orchestrates
module discovery across multiple providers.
"""

import time
import hashlib
from pathlib import Path
from typing import List, Optional, Dict, Any, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..core.enums import SearchMethod, ModuleType, ScanStatus
from ..core.models import ModuleMeta, ScanResult
from ..core.config import ScanConfig
from ..core.exceptions import SearchTimeoutError
from ..providers.base import SearchProvider
from ..providers.file_provider import FileProvider
from ..providers.import_provider import ImportProvider
from .cache import CacheManager


class Scanner:
    """
    Python module scanner with advanced discovery capabilities.

    This class orchestrates module discovery across multiple providers,
    manages caching, and provides comprehensive statistics about the
    scanning process.

    Attributes
    ----------
    providers : List[SearchProvider]
        Registered search providers for module discovery
    cache : CacheManager
        Cache manager for storing and retrieving scan results
    config : ScanConfig
        Default configuration for scan operations
    search_paths : List[Path]
        File paths included in search operations
    stats : Dict[str, Any]
        Aggregate statistics across all scan operations

    Examples
    --------
    >>> scanner = Scanner()
    >>> result = scanner.scan("json")
    >>> print(f"Found {result.total_modules_found} modules")
    Found 1 modules

    >>> config = ScanConfig(search_method=SearchMethod.PATTERN)
    >>> results = scanner.scan("test*", config)
    """

    def __init__(
        self,
        paths: Optional[List[str]] = None,
        config: Optional[ScanConfig] = None
    ) -> None:
        """
        Initialize module scanner with paths and configuration.

        Parameters
        ----------
        paths : Optional[List[str]]
            Additional file paths to include in searches
        config : Optional[ScanConfig]
            Default configuration for scan operations

        Raises
        ------
        InvalidPathError
            If any of the provided paths are invalid
        """
        # Combine user paths with system Python path
        self.search_paths = []
        if paths:
            self.search_paths.extend([Path(p).resolve() for p in paths])

        # Add system paths 
        import sys
        for p in sys.path:
            if p:
                try:
                    path_obj = Path(p).resolve()
                    # Only add if the path exists
                    if path_obj.exists():
                        self.search_paths.append(path_obj)
                except (OSError, ValueError, PermissionError):
                    continue

        # Remove duplicates while preserving order
        seen = set()
        unique_paths = []
        for p in self.search_paths:
            if p not in seen:
                seen.add(p)
                unique_paths.append(p)
        self.search_paths = unique_paths

        # Set default configuration
        self.config = config or ScanConfig()

        # Initialize providers
        self.providers: List[SearchProvider] = [
            FileProvider(self.search_paths),
            ImportProvider(),
        ]

        # Initialize cache and statistics
        self.cache = CacheManager()
        self.stats: Dict[str, Any] = {
            "total_scans": 0,
            "total_modules_found": 0,
            "total_scan_time": 0.0,
            "provider_stats": {},
        }

    def add_provider(self, provider: SearchProvider) -> None:
        """
        Register a custom search provider with the scanner.

        Parameters
        ----------
        provider : SearchProvider
            Search provider instance to add to scanner
        """
        self.providers.append(provider)

    def remove_provider(self, provider_type: type) -> None:
        """
        Remove providers of specified type from scanner.

        Parameters
        ----------
        provider_type : type
            Type of provider to remove from scanner
        """
        self.providers = [p for p in self.providers if not isinstance(p, provider_type)]

    def clear_cache(self) -> None:
        """Clear all cached scan results and reset cache statistics."""
        self.cache.clear()

    def get_cache_info(self) -> Dict[str, Any]:
        """
        Get detailed information about cache state and performance.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing cache statistics and metrics
        """
        info = self.cache.get_stats()
        info.update({
            "cached_queries": list(self.cache.keys()),
        })
        return info

    def _generate_cache_key(self, module: str, config: ScanConfig) -> str:
        """
        Generate unique cache key for scan parameters.

        Parameters
        ----------
        module : str
            Module search term
        config : ScanConfig
            Scan configuration

        Returns
        -------
        str
            Unique cache key string
        """
        key_data = (
            f"{module}:{config.search_method.value}:{config.max_depth}:"
            f"{config.analyze_dependencies}:{config.include_builtin}:"
            f"{config.include_frozen}:{config.include_c_extensions}"
        )
        return hashlib.sha256(key_data.encode()).hexdigest()

    def _calculate_result_statistics(self, results: List[ModuleMeta]) -> Dict[str, Any]:
        """
        Calculate comprehensive statistics from scan results.

        Parameters
        ----------
        results : List[ModuleMeta]
            List of module metadata to analyze

        Returns
        -------
        Dict[str, Any]
            Dictionary containing calculated statistics including:
            - total_modules: Total number of modules found
            - packages: Number of packages
            - modules_by_type: Breakdown by module type
            - average_depth: Average module depth
            - modules_with_docstrings: Count of modules with docstrings
            - modules_with_dependencies: Count of modules with dependencies
            - total_dependencies: Total number of dependencies
        """
        stats = {
            "total_modules": len(results),
            "packages": 0,
            "modules_by_type": {},
            "average_depth": 0,
            "modules_with_docstrings": 0,
            "modules_with_dependencies": 0,
            "total_dependencies": 0,
        }

        total_depth = 0

        for module in results:
            # Count packages
            if module.is_package:
                stats["packages"] += 1

            # Count by module type
            module_type = module.module_type.value
            stats["modules_by_type"][module_type] = (
                stats["modules_by_type"].get(module_type, 0) + 1
            )

            # Track depth statistics
            total_depth += module.depth

            # Track docstrings
            if module.has_docstring:
                stats["modules_with_docstrings"] += 1

            # Track dependencies
            if module.dependencies:
                stats["modules_with_dependencies"] += 1
                stats["total_dependencies"] += len(module.dependencies)

        # Calculate averages
        if results:
            stats["average_depth"] = total_depth / len(results)

        return stats

    def _deduplicate_results(self, results: List[ModuleMeta]) -> List[ModuleMeta]:
        """
        Remove duplicate modules based on name and path.

        Parameters
        ----------
        results : List[ModuleMeta]
            List of modules with potential duplicates

        Returns
        -------
        List[ModuleMeta]
            List with duplicates removed
        """
        seen: Set[Tuple[str, Optional[str]]] = set()
        unique_results = []

        for result in results:
            identifier = (result.name, result.path)
            if identifier not in seen:
                seen.add(identifier)
                unique_results.append(result)

        return unique_results

    def _run_parallel_search(
        self,
        module: str,
        config: ScanConfig,
        timeout_time: Optional[float]
    ) -> List[ModuleMeta]:
        """
        Run searches in parallel across providers.

        Parameters
        ----------
        module : str
            Module search term
        config : ScanConfig
            Scan configuration
        timeout_time : Optional[float]
            Absolute timeout time

        Returns
        -------
        List[ModuleMeta]
            Combined results from all providers

        Raises
        ------
        SearchTimeoutError
            If search exceeds timeout
        """
        all_results = []

        with ThreadPoolExecutor(max_workers=config.workers) as executor:
            futures = []
            for provider in self.providers:
                if provider.supports_method(config.search_method):
                    future = executor.submit(provider.search, module, config)
                    futures.append((provider, future))

            for provider, future in futures:
                try:
                    # Check timeout
                    if timeout_time and time.time() > timeout_time:
                        raise SearchTimeoutError(
                            config.timeout if config.timeout else 0,
                            module
                        )

                    provider_results = future.result(timeout=1.0)
                    all_results.extend(provider_results)

                except Exception as e:
                    # Log provider error but continue with others
                    self.stats.setdefault("provider_errors", []).append({
                        "provider": type(provider).__name__,
                        "error": str(e),
                    })

        return all_results

    def scan(self, module: str, config: Optional[ScanConfig] = None) -> ScanResult:
        """
        Perform comprehensive module search with detailed results.

        Parameters
        ----------
        module : str
            Module name, pattern, or prefix to search for
        config : Optional[ScanConfig]
            Configuration for this scan operation (uses default if None)

        Returns
        -------
        ScanResult
            Comprehensive scan results with metadata and statistics

        Raises
        ------
        SearchTimeoutError
            If the search exceeds the configured timeout
        """
        start_time = time.time()
        scan_config = config or self.config

        # Set timeout if configured
        timeout_time = None
        if scan_config.timeout:
            timeout_time = start_time + scan_config.timeout

        # Check cache if enabled
        cache_key = self._generate_cache_key(module, scan_config)
        if scan_config.enable_cache and cache_key in self.cache:
            cached_results = self.cache.get(cache_key)
            if cached_results:
                result_stats = self._calculate_result_statistics(cached_results)

                return ScanResult(
                    query=module,
                    results=cached_results,
                    search_paths=[str(p) for p in self.search_paths],
                    search_method=scan_config.search_method,
                    cache_used=True,
                    scan_duration=0.0,
                    total_modules_found=result_stats["total_modules"],
                    packages_found=result_stats["packages"],
                    modules_by_type=result_stats["modules_by_type"],
                    timestamp=time.time(),
                    status=ScanStatus.CACHED,
                )

        # Execute search across all providers
        all_results = []
        errors = []

        # Check if we should use parallel scanning
        if scan_config.parallel_scan:
            all_results = self._run_parallel_search(module, scan_config, timeout_time)
        else:
            for provider in self.providers:
                if provider.supports_method(scan_config.search_method):
                    try:
                        provider_results = provider.search(module, scan_config)
                        all_results.extend(provider_results)

                        # Check timeout
                        if timeout_time and time.time() > timeout_time:
                            raise SearchTimeoutError(scan_config.timeout, module)

                    except Exception as e:
                        errors.append(f"Provider {type(provider).__name__} error: {str(e)}")

        # Remove duplicates based on module name and path
        unique_results = self._deduplicate_results(all_results)

        # Cache results if enabled
        if scan_config.enable_cache:
            self.cache.set(cache_key, unique_results)

        # Calculate scan duration
        scan_duration = time.time() - start_time

        # Calculate comprehensive statistics
        result_stats = self._calculate_result_statistics(unique_results)

        # Update global statistics
        self.stats["total_scans"] += 1
        self.stats["total_modules_found"] += len(unique_results)
        self.stats["total_scan_time"] += scan_duration

        # Update provider statistics
        for provider in self.providers:
            provider_stats = provider.get_stats()
            self.stats["provider_stats"][type(provider).__name__] = provider_stats

        # Determine scan status
        status = ScanStatus.COMPLETED
        if errors:
            status = ScanStatus.PARTIAL if unique_results else ScanStatus.FAILED

        return ScanResult(
            query=module,
            results=unique_results,
            search_paths=[str(p) for p in self.search_paths],
            search_method=scan_config.search_method,
            cache_used=False,
            scan_duration=scan_duration,
            total_modules_found=result_stats["total_modules"],
            packages_found=result_stats["packages"],
            modules_by_type=result_stats["modules_by_type"],
            errors=errors,
            timestamp=time.time(),
            status=status,
        )

    def batch_scan(
        self,
        modules: List[str],
        config: Optional[ScanConfig] = None,
        parallel: bool = False
    ) -> Dict[str, ScanResult]:
        """
        Perform multiple module scans in a single operation.

        Parameters
        ----------
        modules : List[str]
            List of module names/patterns to search for
        config : Optional[ScanConfig]
            Configuration for batch scan operations
        parallel : bool
            Whether to run scans in parallel

        Returns
        -------
        Dict[str, ScanResult]
            Dictionary mapping each module to its scan results

        Examples
        --------
        >>> scanner = Scanner()
        >>> results = scanner.batch_scan(["json", "os", "sys"])
        >>> for module, result in results.items():
        ...     print(f"{module}: {result.total_modules_found} modules")
        """
        if parallel:
            return self._batch_scan_parallel(modules, config)
        else:
            return self._batch_scan_sequential(modules, config)

    def _batch_scan_sequential(
        self,
        modules: List[str],
        config: Optional[ScanConfig]
    ) -> Dict[str, ScanResult]:
        """
        Perform batch scans sequentially.

        Parameters
        ----------
        modules : List[str]
            List of modules to scan
        config : Optional[ScanConfig]
            Scan configuration

        Returns
        -------
        Dict[str, ScanResult]
            Dictionary of scan results
        """
        results = {}
        for module in modules:
            results[module] = self.scan(module, config)
        return results

    def _batch_scan_parallel(
        self,
        modules: List[str],
        config: Optional[ScanConfig]
    ) -> Dict[str, ScanResult]:
        """
        Perform batch scans in parallel.

        Parameters
        ----------
        modules : List[str]
            List of modules to scan
        config : Optional[ScanConfig]
            Scan configuration

        Returns
        -------
        Dict[str, ScanResult]
            Dictionary of scan results
        """
        results = {}
        scan_config = config or self.config

        with ThreadPoolExecutor(max_workers=scan_config.workers) as executor:
            futures = {
                executor.submit(self.scan, module, config): module
                for module in modules
            }

            for future in as_completed(futures):
                module = futures[future]
                try:
                    results[module] = future.result()
                except Exception as e:
                    # Create error result
                    results[module] = ScanResult(
                        query=module,
                        errors=[f"Batch scan error: {str(e)}"],
                        status=ScanStatus.FAILED,
                    )

        return results

    def get_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive scanner statistics.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing all scanner statistics and metrics
        """
        stats = self.stats.copy()
        stats.update({
            "cache_stats": self.cache.get_stats(),
            "search_paths": [str(p) for p in self.search_paths],
            "active_providers": [type(p).__name__ for p in self.providers],
        })
        return stats