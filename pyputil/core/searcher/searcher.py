#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Enhanced PyPI search utility.

This module provides the main Searcher class for searching PyPI packages.
"""

import aiohttp
import asyncio
import backoff
import hashlib
import json
import logging
import re
import time
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set, Union
from urllib.parse import quote, urljoin
from dataclasses import dataclass, field, asdict
from aiolimiter import AsyncLimiter

from .enums import SearchStrategy, CacheStrategy
from .models import (
    SearchMetrics,
    PackageInfo,
    SearchStatistics,
    PackageComparison,
    DownloadStats,
    RecentActivity,
    ExportData,
)


# Configure structured logging
logger = logging.getLogger(__name__)


class Searcher:
    """
    PyPI search utility.

    Parameters
    ----------
    cache_ttl : int, optional
        Time-to-live for cache entries in seconds, by default 3600
    max_concurrent : int, optional
        Maximum concurrent requests, by default 10
    timeout : int, optional
        Request timeout in seconds, by default 15
    cache_strategy : CacheStrategy, optional
        Cache storage strategy, by default CacheStrategy.HYBRID
    cache_dir : Optional[str], optional
        Directory for disk cache (required for disk/hybrid), by default ".pypi_cache"
    requests_per_second : int, optional
        Rate limit for requests, by default 5
    enable_health_scoring : bool, optional
        Enable package health scoring, by default True
    enable_metrics : bool, optional
        Enable performance metrics collection, by default True
    enable_validation : bool, optional
        Enable validation of package names and data, by default True

    Examples
    --------
    >>> async with Searcher() as searcher:
    >>>     # Single search
    >>>     results = await searcher.search("requests", max_results=10)
    >>>
    >>>     # Batch search
    >>>     batch_results = await searcher.batch_search(["numpy", "pandas"])
    >>>
    >>>     # Package comparison
    >>>     comparison = await searcher.compare_packages(["package1", "package2"])
    """

    # PyPI API endpoints
    PYPI_BASE_URL = "https://pypi.org"
    PYPI_JSON_API_URL = f"{PYPI_BASE_URL}/pypi"
    PYPI_SEARCH_URL = f"{PYPI_BASE_URL}/search"
    PYPI_SIMPLE_URL = f"{PYPI_BASE_URL}/simple"

    # Validation patterns
    PACKAGE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
    VALID_VERSION_PATTERN = re.compile(r"^[0-9a-zA-Z\.\+\-]+$")

    def __init__(
        self,
        cache_ttl: int = 3600,  # Increased from 300 to 3600 (1 hour)
        max_concurrent: int = 10,  # Reduced from 20 to 10
        timeout: int = 15,  # Reduced from 30 to 15
        cache_strategy: CacheStrategy = CacheStrategy.HYBRID,
        cache_dir: Optional[str] = ".pypi_cache",
        requests_per_second: int = 5,  # Reduced from 10 to 5
        enable_health_scoring: bool = True,
        enable_metrics: bool = True,
        enable_validation: bool = True,
    ):
        """
        Initialize the PyPI searcher.

        Parameters
        ----------
        cache_ttl : int
            Time-to-live for cache entries in seconds
        max_concurrent : int
            Maximum concurrent requests
        timeout : int
            Request timeout in seconds
        cache_strategy : CacheStrategy
            Cache storage strategy
        cache_dir : Optional[str]
            Directory for disk cache (required for disk/hybrid)
        requests_per_second : int
            Rate limit for requests
        enable_health_scoring : bool
            Enable package health scoring
        enable_metrics : bool
            Enable performance metrics collection
        enable_validation : bool
            Enable validation of package names and data
        """
        self.cache_ttl = cache_ttl
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.cache_strategy = cache_strategy
        self.enable_health_scoring = enable_health_scoring
        self.enable_metrics = enable_metrics
        self.enable_validation = enable_validation

        # Initialize cache based on strategy
        self._cache = {}
        self._cache_dir = Path(cache_dir) if cache_dir else Path(".pypi_cache")
        if cache_strategy in [CacheStrategy.DISK, CacheStrategy.HYBRID]:
            self._cache_dir.mkdir(exist_ok=True, parents=True)  # Added parents=True

        # Rate limiting - more conservative to avoid IP blocking
        self.rate_limiter = AsyncLimiter(requests_per_second, 1)

        # Session management
        self._session = None
        self._session_lock = asyncio.Lock()

        # Metrics and statistics
        self.metrics: List[SearchMetrics] = []
        self._search_stats = {
            "total_searches": 0,
            "cache_hits": 0,
            "average_response_time": 0.0,
            "successful_searches": 0,
            "failed_searches": 0,
        }

        # Performance optimization
        self._compression_enabled = True

        # Request tracking for debugging
        self._request_times = []

        logger.info(
            f"Searcher initialized with {max_concurrent} max concurrent requests, {requests_per_second} req/sec limit"
        )

    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _ensure_session(self) -> None:
        """
        Ensure aiohttp session is available with connection pooling.

        Creates a new aiohttp session if one doesn't exist, with
        optimized connection pooling and timeout settings.

        Returns
        -------
        None
        """
        async with self._session_lock:
            if self._session is None:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                connector = aiohttp.TCPConnector(
                    limit=self.max_concurrent,
                    limit_per_host=self.max_concurrent // 2,
                    keepalive_timeout=30,
                    ttl_dns_cache=300,  # DNS cache TTL
                )
                self._session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                    headers={
                        "User-Agent": "Searcher/2.1 (Enhanced Search Toolkit)",
                        "Accept": "application/json,text/html",
                        "Accept-Encoding": "gzip, deflate, br",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Connection": "keep-alive",
                    },
                )
                logger.debug("HTTP session initialized")

    async def close(self) -> None:
        """
        Close the aiohttp session and cleanup resources.

        Closes the HTTP session and saves metrics if enabled.

        Returns
        -------
        None
        """
        async with self._session_lock:
            if self._session:
                await self._session.close()
                self._session = None
                logger.debug("HTTP session closed")

        # Save metrics if enabled
        if self.enable_metrics and self.metrics:
            await self._save_metrics()

    def _get_cache_key(self, query: str, search_type: str) -> str:
        """
        Generate deterministic cache key with hash for consistency.

        Parameters
        ----------
        query : str
            The search query
        search_type : str
            Type of search (e.g., "search", "details")

        Returns
        -------
        str
            MD5 hash of the normalized key data
        """
        key_data = f"{search_type}:{(query or '').lower().strip()}:v2"  # Added version marker
        return hashlib.md5(key_data.encode()).hexdigest()

    async def _get_cached_result(self, cache_key: str) -> Optional[Any]:
        """
        Retrieve cached result with strategy-specific implementation.

        Parameters
        ----------
        cache_key : str
            The cache key to lookup

        Returns
        -------
        Optional[Any]
            Cached result if found and valid, None otherwise
        """
        if self.cache_strategy == CacheStrategy.MEMORY:
            return self._get_memory_cached(cache_key)
        elif self.cache_strategy == CacheStrategy.DISK:
            return await self._get_disk_cached(cache_key)
        elif self.cache_strategy == CacheStrategy.HYBRID:
            memory_result = self._get_memory_cached(cache_key)
            if memory_result is not None:
                return memory_result
            return await self._get_disk_cached(cache_key)
        return None

    def _get_memory_cached(self, cache_key: str) -> Optional[Any]:
        """
        Retrieve from memory cache.

        Parameters
        ----------
        cache_key : str
            The cache key to lookup

        Returns
        -------
        Optional[Any]
            Cached data if found and not expired, None otherwise
        """
        if cache_key in self._cache:
            timestamp, data = self._cache[cache_key]
            current_time = time.time()
            if (current_time - timestamp) < self.cache_ttl:
                self._search_stats["cache_hits"] += 1
                logger.debug(f"Memory cache hit for key: {cache_key}")
                return data
            else:
                # Expired entry
                del self._cache[cache_key]
                logger.debug(f"Memory cache expired for key: {cache_key}")
        return None

    async def _get_disk_cached(self, cache_key: str) -> Optional[Any]:
        """
        Retrieve from disk cache with compression support.

        Parameters
        ----------
        cache_key : str
            The cache key to lookup

        Returns
        -------
        Optional[Any]
            Cached data if found and not expired, None otherwise
        """
        cache_file = self._cache_dir / f"{cache_key}.cache"
        if cache_file.exists():
            try:
                # Check file age
                current_time = time.time()
                file_mtime = cache_file.stat().st_mtime
                file_age = current_time - file_mtime

                if file_age < self.cache_ttl:
                    data = cache_file.read_bytes()
                    if self._compression_enabled:
                        try:
                            data = zlib.decompress(data)
                        except zlib.error:
                            pass  # Not compressed or corrupted

                    result = json.loads(data.decode())
                    self._search_stats["cache_hits"] += 1

                    # Populate memory cache in hybrid mode
                    if self.cache_strategy == CacheStrategy.HYBRID:
                        self._cache[cache_key] = (file_mtime, result)

                    logger.debug(f"Disk cache hit for key: {cache_key}")
                    return result
                else:
                    # Expired cache file
                    cache_file.unlink()
                    logger.debug(f"Disk cache expired for key: {cache_key}")
            except (IOError, json.JSONDecodeError, PermissionError) as e:
                logger.warning(f"Failed to read cache file {cache_file}: {e}")
                try:
                    cache_file.unlink()  # Remove corrupted cache
                except (IOError, PermissionError):
                    pass
        return None

    async def _set_cached_result(self, cache_key: str, data: Any) -> None:
        """
        Store result in cache with strategy-specific implementation.

        Parameters
        ----------
        cache_key : str
            The cache key to use for storage
        data : Any
            The data to cache

        Returns
        -------
        None
        """
        timestamp = time.time()
        if self.cache_strategy in [CacheStrategy.MEMORY, CacheStrategy.HYBRID]:
            self._cache[cache_key] = (timestamp, data)
            logger.debug(f"Cached in memory: {cache_key}")

        if self.cache_strategy in [CacheStrategy.DISK, CacheStrategy.HYBRID]:
            await self._set_disk_cached(cache_key, data, timestamp)

    async def _set_disk_cached(
        self, cache_key: str, data: Any, timestamp: float
    ) -> None:
        """
        Store result in disk cache with compression.

        Parameters
        ----------
        cache_key : str
            The cache key to use for storage
        data : Any
            The data to cache
        timestamp : float
            Timestamp for cache entry

        Returns
        -------
        None
        """
        cache_file = self._cache_dir / f"{cache_key}.cache"
        try:
            # Convert PackageInfo to dict for serialization
            if isinstance(data, PackageInfo):
                serializable_data = self._package_to_dict(data)
            elif isinstance(data, list) and data and isinstance(data[0], PackageInfo):
                serializable_data = [self._package_to_dict(pkg) for pkg in data]
            else:
                serializable_data = data

            serialized_data = json.dumps(
                serializable_data, separators=(",", ":")
            ).encode()
            if self._compression_enabled:
                serialized_data = zlib.compress(serialized_data, level=6)
            cache_file.write_bytes(serialized_data)
            logger.debug(f"Cached on disk: {cache_key}")
        except (IOError, TypeError, PermissionError) as e:
            logger.warning(f"Failed to write cache file {cache_file}: {e}")

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, asyncio.TimeoutError),
        max_tries=3,
        max_time=30,
        jitter=backoff.full_jitter,
    )
    async def _make_request(self, url: str, method: str = "GET") -> Tuple[int, Any]:
        """
        Make HTTP request with retry logic and rate limiting.

        Parameters
        ----------
        url : str
            Target URL
        method : str, optional
            HTTP method, by default "GET"

        Returns
        -------
        Tuple[int, Any]
            Tuple of (status_code, response_data)

        Raises
        ------
        aiohttp.ClientError
            If the request fails after all retries
        asyncio.TimeoutError
            If the request times out after all retries
        """
        start_time = time.time()
        async with self.rate_limiter:
            await self._ensure_session()
            try:
                async with self._session.request(method, url) as response:
                    response_time = time.time() - start_time
                    self._request_times.append(response_time)

                    if len(self._request_times) > 100:
                        self._request_times.pop(0)

                    if response.status == 200:
                        content_type = response.headers.get("content-type", "")
                        if "application/json" in content_type:
                            try:
                                data = await response.json()
                            except json.JSONDecodeError:
                                data = await response.text()
                        else:
                            data = await response.text()
                        logger.debug(
                            f"Request to {url} succeeded in {response_time:.2f}s"
                        )
                        return response.status, data
                    else:
                        logger.warning(
                            f"Request to {url} failed with status {response.status}"
                        )
                        return response.status, None
            except asyncio.TimeoutError:
                logger.warning(f"Request timeout for {url} after {self.timeout}s")
                return 408, None
            except aiohttp.ClientError as e:
                logger.warning(f"Request failed for {url}: {e}")
                return 500, None

    async def search(
        self,
        query: str,
        max_results: int = 20,
        include_details: bool = True,
        strategy_priority: List[SearchStrategy] = None,
        min_score_threshold: float = 0.3,  # Added threshold for better filtering
    ) -> List[PackageInfo]:
        """
        Perform PyPI package search.

        Implements a tiered search approach:
        1. Primary JSON API
        2. Web scraping search
        3. Simple index scanning
        4. Direct package lookup

        Parameters
        ----------
        query : str
            Search query string
        max_results : int, optional
            Maximum number of results, by default 20
        include_details : bool, optional
            Fetch detailed package information, by default True
        strategy_priority : List[SearchStrategy], optional
            Custom search strategy order, by default None
        min_score_threshold : float, optional
            Minimum relevance score to include, by default 0.3

        Returns
        -------
        List[PackageInfo]
            List of PackageInfo objects sorted by relevance

        Raises
        ------
        ValueError
            For invalid queries
        aiohttp.ClientError
            For network failures

        Examples
        --------
        >>> results = await searcher.search("web framework", max_results=10)
        >>> for package in results:
        >>>     print(f"{package.name} ({package.health_score:.2f})")
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty or whitespace")

        query = query.strip()
        start_time = time.time()

        # Update statistics
        self._search_stats["total_searches"] += 1

        # Check cache first
        cache_key = self._get_cache_key(
            f"{query}:{max_results}:{include_details}", "search"
        )
        cached_result = await self._get_cached_result(cache_key)

        if cached_result is not None:
            logger.info(f"Cache hit for query: {query}")
            results = cached_result[:max_results]

            # Convert dict back to PackageInfo objects if needed
            if results and isinstance(results[0], dict):
                results = [PackageInfo(**pkg_dict) for pkg_dict in results]

            # Record metrics
            if self.enable_metrics:
                self.metrics.append(
                    SearchMetrics(
                        query=query,
                        strategy_used=SearchStrategy.CACHE,
                        response_time=time.time() - start_time,
                        results_count=len(results),
                        cache_hit=True,
                    )
                )
            return results

        logger.info(f"Performing search for: {query}")
        await self._ensure_session()

        # Default strategy priority - optimized order
        if strategy_priority is None:
            strategy_priority = [
                SearchStrategy.DIRECT_PACKAGE_LOOKUP,  # Try direct lookup first for exact matches
                SearchStrategy.PRIMARY_JSON_API,
                SearchStrategy.SECONDARY_WEB_SCRAPING,
                SearchStrategy.FALLBACK_SIMPLE_INDEX,
            ]

        packages = []
        used_strategy = SearchStrategy.PRIMARY_JSON_API

        # Try strategies in order until results are found
        for strategy in strategy_priority:
            try:
                strategy_start = time.time()

                if strategy == SearchStrategy.PRIMARY_JSON_API:
                    packages = await self._search_primary(query, max_results)
                elif strategy == SearchStrategy.SECONDARY_WEB_SCRAPING:
                    packages = await self._search_secondary(query, max_results)
                elif strategy == SearchStrategy.FALLBACK_SIMPLE_INDEX:
                    packages = await self._search_fallback(query, max_results)
                elif strategy == SearchStrategy.DIRECT_PACKAGE_LOOKUP:
                    packages = await self._search_direct_lookup(query, max_results)

                strategy_time = time.time() - strategy_start

                if packages:
                    used_strategy = strategy
                    logger.debug(
                        f"Strategy {strategy} succeeded with {len(packages)} results in {strategy_time:.2f}s"
                    )
                    break
                else:
                    logger.debug(
                        f"Strategy {strategy} returned no results in {strategy_time:.2f}s"
                    )

            except Exception as e:
                logger.warning(f"Strategy {strategy} failed: {e}")
                self._search_stats["failed_searches"] += 1
                continue

        # Filter packages by name validity and relevance
        filtered_packages = []
        for package in packages:
            if self.enable_validation:
                # Validate package name
                if not self._validate_package_name(package.name):
                    logger.debug(f"Filtered invalid package name: {package.name}")
                    continue

            # Calculate relevance score
            package.score = self._calculate_relevance_score(
                query, package.name, package.summary
            )

            # Apply score threshold
            if package.score >= min_score_threshold:
                filtered_packages.append(package)

        packages = filtered_packages

        # Enrich with detailed information if requested
        if include_details and packages:
            packages = await self._enrich_package_details(packages)

        # Sort by relevance and health score
        packages.sort(key=lambda x: (x.score, x.health_score), reverse=True)
        final_results = packages[:max_results]

        # Cache the results
        await self._set_cached_result(cache_key, final_results)

        # Update success statistics
        self._search_stats["successful_searches"] += 1

        # Calculate response time for metrics
        response_time = time.time() - start_time
        self._search_stats["average_response_time"] = (
            self._search_stats["average_response_time"]
            * (self._search_stats["total_searches"] - 1)
            + response_time
        ) / self._search_stats["total_searches"]

        # Record metrics
        if self.enable_metrics:
            self.metrics.append(
                SearchMetrics(
                    query=query,
                    strategy_used=used_strategy,
                    response_time=response_time,
                    results_count=len(final_results),
                    cache_hit=False,
                )
            )

        logger.info(
            f"Search completed: {len(final_results)} results in {response_time:.2f}s"
        )
        return final_results

    async def _search_primary(self, query: str, max_results: int) -> List[PackageInfo]:
        """
        Primary search using PyPI's JSON API with enhanced parsing.

        Parameters
        ----------
        query : str
            Search query
        max_results : int
            Maximum results to return

        Returns
        -------
        List[PackageInfo]
            List of PackageInfo objects
        """
        try:
            encoded_query = quote(query)
            # FIXED: Using PYPI_SEARCH_URL instead of PYPI_SEARCH
            url = f"{self.PYPI_SEARCH_URL}/?q={encoded_query}"
            status, data = await self._make_request(url)

            if status == 200 and data:
                packages = self._parse_primary_results(data, query, max_results)

                # Filter out low-quality results
                filtered_packages = []
                for package in packages:
                    # Skip packages with obviously bad names
                    if self._is_low_quality_package(package.name):
                        continue
                    filtered_packages.append(package)

                return filtered_packages[:max_results]

        except Exception as e:
            logger.warning(f"Primary search failed: {e}")
        return []

    def _parse_primary_results(
        self, html: str, query: str, max_results: int
    ) -> List[PackageInfo]:
        """
        Parse enhanced HTML response from primary search.

        Parameters
        ----------
        html : str
            HTML content
        query : str
            Original search query
        max_results : int
            Maximum results to return

        Returns
        -------
        List[PackageInfo]
            List of parsed PackageInfo objects
        """
        packages = []
        # Enhanced regex patterns for better parsing
        patterns = [
            # Pattern for modern PyPI search results
            r'<a[^>]*class="package-snippet"[^>]*href="/project/([^"/]+)/?"[^>]*>.*?<span[^>]*class="package-snippet__name"[^>]*>([^<]+)</span>.*?<span[^>]*class="package-snippet__version"[^>]*>([^<]+)</span>.*?<p[^>]*class="package-snippet__description"[^>]*>([^<]*)</p>',
            # Fallback pattern
            r'<a[^>]*href="/project/([^"/]+)/?"[^>]*>.*?>([^<]+)<.*?>([^<]+)<.*?>([^<]*)<',
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, html, re.DOTALL | re.IGNORECASE)
            for match in matches:
                if len(packages) >= max_results * 2:  # Parse extra for filtering
                    break

                if len(match.groups()) >= 4:
                    package_name = self._clean_text(match.group(1))
                    display_name = self._clean_text(match.group(2))
                    version = self._clean_text(match.group(3))
                    summary = self._clean_text(match.group(4))

                    # Use the more reliable package name from URL
                    if package_name and self._validate_package_name(package_name):
                        score = self._calculate_relevance_score(
                            query, package_name, summary
                        )
                        package = PackageInfo(
                            name=package_name,
                            version=(
                                version
                                if self._validate_version(version)
                                else "unknown"
                            ),
                            summary=summary,
                            score=score,
                        )
                        packages.append(package)

            if packages:  # Use first pattern that yields results
                break

        return packages[:max_results]

    async def _search_secondary(
        self, query: str, max_results: int
    ) -> List[PackageInfo]:
        """
        Secondary search using PyPI search API with web scraping.

        Parameters
        ----------
        query : str
            Search query
        max_results : int
            Maximum results to return

        Returns
        -------
        List[PackageInfo]
            List of PackageInfo objects
        """
        try:
            encoded_query = quote(query)
            url = f"{self.PYPI_SEARCH_URL}/?q={encoded_query}"
            status, data = await self._make_request(url)
            if status == 200 and data:
                packages = self._parse_secondary_results(data, query, max_results)

                # Filter out obviously incorrect results
                filtered_packages = []
                for package in packages:
                    if not self._is_low_quality_package(package.name):
                        filtered_packages.append(package)

                return filtered_packages[:max_results]

        except Exception as e:
            logger.warning(f"Secondary search failed: {e}")
        return []

    def _parse_secondary_results(
        self, html: str, query: str, max_results: int
    ) -> List[PackageInfo]:
        """
        Parse search results from secondary search.

        Parameters
        ----------
        html : str
            HTML content
        query : str
            Original search query
        max_results : int
            Maximum results to return

        Returns
        -------
        List[PackageInfo]
            List of parsed PackageInfo objects
        """
        packages = []
        # Improved pattern for search results
        pattern = r'<a[^>]*class="package-snippet"[^>]*href="[^"]*/([^"/]+)/?"[^>]*>.*?<span[^>]*class="[^"]*snippet__name[^"]*"[^>]*>([^<]+)</span>.*?<span[^>]*class="[^"]*snippet__version[^"]*"[^>]*>([^<]+)</span>.*?<p[^>]*class="[^"]*snippet__description[^"]*"[^>]*>([^<]*)</p>'
        matches = re.finditer(pattern, html, re.DOTALL)

        for match in matches:
            if len(packages) >= max_results * 2:
                break

            name_from_url = self._clean_text(match.group(1))
            display_name = self._clean_text(match.group(2))
            version = self._clean_text(match.group(3))
            summary = self._clean_text(match.group(4))

            # Prefer name from URL as it's more reliable
            package_name = name_from_url if name_from_url else display_name

            if package_name and self._validate_package_name(package_name):
                score = self._calculate_relevance_score(query, package_name, summary)
                package = PackageInfo(
                    name=package_name,
                    version=version if self._validate_version(version) else "unknown",
                    summary=summary,
                    score=score,
                )
                packages.append(package)

        return packages[:max_results]

    async def _search_fallback(self, query: str, max_results: int) -> List[PackageInfo]:
        """
        Fallback search using PyPI simple index.

        Parameters
        ----------
        query : str
            Search query
        max_results : int
            Maximum results to return

        Returns
        -------
        List[PackageInfo]
            List of PackageInfo objects
        """
        try:
            status, data = await self._make_request(self.PYPI_SIMPLE_URL)
            if status == 200 and data:
                packages = self._parse_fallback_results(data, query, max_results)

                # Filter packages
                filtered_packages = []
                for package in packages:
                    if not self._is_low_quality_package(package.name):
                        filtered_packages.append(package)

                return filtered_packages[:max_results]

        except Exception as e:
            logger.warning(f"Fallback search failed: {e}")
        return []

    def _parse_fallback_results(
        self, html: str, query: str, max_results: int
    ) -> List[PackageInfo]:
        """
        Parse simple index for package names matching query.

        Parameters
        ----------
        html : str
            HTML content
        query : str
            Original search query
        max_results : int
            Maximum results to return

        Returns
        -------
        List[PackageInfo]
            List of PackageInfo objects
        """
        packages = []
        query_lower = query.lower()

        # Extract package names from simple index
        pattern = r'<a[^>]*href="[^"]*/([^"/]+)/?"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, html)

        for name_from_url, display_name in matches:
            if len(packages) >= max_results * 3:  # Get more for filtering
                break

            package_name = self._clean_text(name_from_url) or self._clean_text(
                display_name
            )

            # Check if package name contains query (case-insensitive)
            if package_name and query_lower in package_name.lower():
                if self._validate_package_name(package_name):
                    score = self._calculate_relevance_score(query, package_name, "")
                    package = PackageInfo(
                        name=package_name, version="unknown", summary="", score=score
                    )
                    packages.append(package)

        return packages[:max_results]

    async def _search_direct_lookup(
        self, query: str, max_results: int
    ) -> List[PackageInfo]:
        """
        Direct package lookup as final fallback strategy.

        Parameters
        ----------
        query : str
            Search query (treated as package name)
        max_results : int
            Maximum results to return

        Returns
        -------
        List[PackageInfo]
            List of PackageInfo objects
        """
        try:
            # Clean and validate the query as a package name
            clean_query = self._clean_text(query)
            if not self._validate_package_name(clean_query):
                return []

            package = await self.get_package_details(clean_query)
            if package:
                package.score = 1.0  # Exact match gets highest score
                return [package]
        except Exception as e:
            logger.debug(f"Direct lookup failed for {query}: {e}")
        return []

    async def get_package_details(self, package_name: str) -> Optional[PackageInfo]:
        """
        Get comprehensive details for a specific package.

        Parameters
        ----------
        package_name : str
            Exact package name

        Returns
        -------
        Optional[PackageInfo]
            PackageInfo object or None if not found

        Examples
        --------
        >>> package = await searcher.get_package_details("requests")
        >>> print(f"Health score: {package.health_score:.2f}")
        >>> print(f"Dependencies: {package.dependencies}")
        """
        # Validate package name
        if not package_name or not self._validate_package_name(package_name):
            logger.warning(f"Invalid package name: {package_name}")
            return None

        cache_key = self._get_cache_key(package_name, "details")
        cached_result = await self._get_cached_result(cache_key)

        if cached_result is not None:
            # Convert dict back to PackageInfo if needed
            if isinstance(cached_result, dict):
                return PackageInfo(**cached_result)
            return cached_result

        try:
            url = f"{self.PYPI_JSON_API_URL}/{package_name}/json"
            status, data = await self._make_request(url)

            if status == 200 and data:
                package = self._parse_package_details(data)
                # Cache the result
                await self._set_cached_result(cache_key, package)
                return package
            elif status == 404:
                logger.info(f"Package not found: {package_name}")
                # Cache negative result to avoid repeated lookups
                await self._set_cached_result(cache_key, None)
            else:
                logger.warning(
                    f"Failed to get details for {package_name}: HTTP {status}"
                )

        except Exception as e:
            logger.error(f"Failed to get details for {package_name}: {e}")

        return None

    def _parse_package_details(self, data: Dict[str, Any]) -> PackageInfo:
        """
        Parse comprehensive package information from JSON API response.

        Parameters
        ----------
        data : Dict[str, Any]
            JSON API response data

        Returns
        -------
        PackageInfo
            Parsed PackageInfo object
        """
        info = data["info"]
        releases = data.get("releases", {})

        # Calculate enhanced download statistics with validation
        downloads = self._calculate_download_stats(releases)

        # Extract dependencies
        dependencies = self._extract_dependencies(info)

        # Calculate recent activity
        recent_activity = self._calculate_recent_activity(releases)

        # Find first release
        first_release = self._find_first_release(releases)

        # Calculate health score
        health_score = self._calculate_health_score(
            info, releases, downloads, recent_activity
        )

        package = PackageInfo(
            name=info.get("name") or "",
            version=info.get("version") or "",
            summary=info.get("summary") or "",
            description=info.get("description") or "",
            author=info.get("author") or "",
            author_email=info.get("author_email") or "",
            maintainer=info.get("maintainer") or "",
            maintainer_email=info.get("maintainer_email") or "",
            home_page=info.get("home_page") or "",
            project_url=info.get("project_url") or "",
            license=info.get("license") or "",
            requires_python=info.get("requires_python") or "",
            download_url=info.get("download_url") or "",
            project_urls=info.get("project_urls") or {},
            releases=releases,
            classifiers=info.get("classifiers") or [],
            downloads=downloads,
            dependencies=dependencies,
            first_release=first_release,
            recent_activity=recent_activity,
            last_updated=self._extract_last_updated(releases),
            health_score=health_score,
            score=0.0,  # Will be set by search method
        )

        return package

    def _calculate_download_stats(
        self, releases: Dict[str, List[Dict]]
    ) -> DownloadStats:
        """
        Calculate comprehensive download statistics with validation.

        Parameters
        ----------
        releases : Dict[str, List[Dict]]
            Releases information

        Returns
        -------
        DownloadStats
            Download statistics object
        """
        stats = DownloadStats(release_count=len(releases) if releases else 0)

        # Validate releases data
        if not releases:
            return stats

        recent_cutoff = datetime.now() - timedelta(days=30)
        recent_downloads = 0
        release_downloads = []

        for version, files in releases.items():
            if not isinstance(files, list):
                continue

            version_downloads = 0
            stats.file_count += len(files)

            for file_info in files:
                if not isinstance(file_info, dict):
                    continue

                file_downloads = file_info.get("downloads", 0)

                # Validate downloads count
                if isinstance(file_downloads, (int, float)) and file_downloads >= 0:
                    stats.total_downloads += int(file_downloads)
                    version_downloads += int(file_downloads)

                    # Check if this is a recent upload
                    upload_time_str = file_info.get("upload_time", "")
                    if upload_time_str:
                        try:
                            upload_time = datetime.fromisoformat(
                                upload_time_str.replace("Z", "+00:00")
                            )
                            if upload_time > recent_cutoff:
                                recent_downloads += int(file_downloads)
                        except (ValueError, TypeError, AttributeError):
                            pass  # Skip invalid date formats

            release_downloads.append(version_downloads)

        # Ensure non-negative values
        stats.total_downloads = max(0, stats.total_downloads)
        stats.recent_downloads = max(0, recent_downloads)

        if release_downloads:
            avg_downloads = sum(release_downloads) / len(release_downloads)
            stats.average_downloads_per_release = max(0.0, avg_downloads)

        return stats

    def _extract_dependencies(self, info: Dict[str, Any]) -> List[str]:
        """
        Extract package dependencies from info data.

        Parameters
        ----------
        info : Dict[str, Any]
            Package information dictionary

        Returns
        -------
        List[str]
            List of dependency package names
        """
        dependencies = []
        requires_dist = info.get("requires_dist")

        if requires_dist and isinstance(requires_dist, list):
            for requirement in requires_dist:
                if isinstance(requirement, str):
                    # Extract package name from requirement spec
                    match = re.match(r"^([a-zA-Z0-9_-]+)", requirement)
                    if match:
                        dep_name = match.group(1)
                        if self._validate_package_name(dep_name):
                            dependencies.append(dep_name)

        return dependencies

    def _calculate_recent_activity(
        self, releases: Dict[str, List[Dict]]
    ) -> RecentActivity:
        """
        Calculate recent release activity metrics.

        Parameters
        ----------
        releases : Dict[str, List[Dict]]
            Releases information

        Returns
        -------
        RecentActivity
            Recent activity metrics object
        """
        recent_cutoff = datetime.now() - timedelta(days=90)  # 3 months
        recent_releases = 0
        latest_upload = None

        if not releases:
            return RecentActivity(
                recent_releases=0,
                latest_upload=None,
                days_since_last_release=None,
            )

        for files in releases.values():
            if not isinstance(files, list):
                continue

            for file_info in files:
                if not isinstance(file_info, dict):
                    continue

                upload_time_str = file_info.get("upload_time")
                if upload_time_str and isinstance(upload_time_str, str):
                    try:
                        upload_time = datetime.fromisoformat(
                            upload_time_str.replace("Z", "+00:00")
                        )
                        if upload_time > recent_cutoff:
                            recent_releases += 1
                        if latest_upload is None or upload_time > latest_upload:
                            latest_upload = upload_time
                    except (ValueError, TypeError, AttributeError):
                        continue

        days_since_last = None
        if latest_upload:
            days_since_last = (datetime.now() - latest_upload).days
            days_since_last = max(0, days_since_last)  # Ensure non-negative

        return RecentActivity(
            recent_releases=recent_releases,
            latest_upload=latest_upload.isoformat() if latest_upload else None,
            days_since_last_release=days_since_last,
        )

    def _find_first_release(self, releases: Dict[str, List[Dict]]) -> str:
        """
        Find the date of the first release.

        Parameters
        ----------
        releases : Dict[str, List[Dict]]
            Releases information

        Returns
        -------
        str
            ISO format string of first release date, or empty string if not found
        """
        first_upload = None

        if not releases:
            return ""

        for files in releases.values():
            if not isinstance(files, list):
                continue

            for file_info in files:
                if not isinstance(file_info, dict):
                    continue

                upload_time_str = file_info.get("upload_time")
                if upload_time_str and isinstance(upload_time_str, str):
                    try:
                        upload_time = datetime.fromisoformat(
                            upload_time_str.replace("Z", "+00:00")
                        )
                        if first_upload is None or upload_time < first_upload:
                            first_upload = upload_time
                    except (ValueError, TypeError, AttributeError):
                        continue

        return first_upload.isoformat() if first_upload else ""

    def _extract_last_updated(self, releases: Dict[str, List[Dict]]) -> str:
        """
        Extract the last update timestamp from releases.

        Parameters
        ----------
        releases : Dict[str, List[Dict]]
            Releases information

        Returns
        -------
        str
            ISO format string of last update timestamp, or empty string if not found
        """
        latest_upload = None

        if not releases:
            return ""

        for files in releases.values():
            if not isinstance(files, list):
                continue

            for file_info in files:
                if not isinstance(file_info, dict):
                    continue

                upload_time_str = file_info.get("upload_time")
                if upload_time_str and isinstance(upload_time_str, str):
                    try:
                        upload_time = datetime.fromisoformat(
                            upload_time_str.replace("Z", "+00:00")
                        )
                        if latest_upload is None or upload_time > latest_upload:
                            latest_upload = upload_time
                    except (ValueError, TypeError, AttributeError):
                        continue

        return latest_upload.isoformat() if latest_upload else ""

    def _calculate_health_score(
        self,
        info: Dict[str, Any],
        releases: Dict[str, List[Dict]],
        downloads: DownloadStats,
        recent_activity: RecentActivity,
    ) -> float:
        """
        Calculate package health score based on multiple factors.

        Parameters
        ----------
        info : Dict[str, Any]
            Package info
        releases : Dict[str, List[Dict]]
            Releases data
        downloads : DownloadStats
            Download statistics
        recent_activity : RecentActivity
            Recent activity metrics

        Returns
        -------
        float
            Health score between 0.0 and 1.0
        """
        if not self.enable_health_scoring:
            return 0.0

        score_components = []

        # 1. Release frequency (weight: 0.2)
        release_count = downloads.release_count
        if release_count > 10:
            score_components.append(0.2)
        elif release_count > 5:
            score_components.append(0.15)
        elif release_count > 1:
            score_components.append(0.1)
        else:
            score_components.append(0.05)

        # 2. Recent activity (weight: 0.3)
        days_since_last = recent_activity.days_since_last_release
        if days_since_last is None:
            score_components.append(0.0)
        elif days_since_last <= 30:
            score_components.append(0.3)
        elif days_since_last <= 90:
            score_components.append(0.2)
        elif days_since_last <= 180:
            score_components.append(0.1)
        else:
            score_components.append(0.05)

        # 3. Documentation quality (weight: 0.2)
        has_description = bool(info.get("description") or "")
        has_home_page = bool(info.get("home_page") or "")
        has_classifiers = bool(info.get("classifiers") or [])

        doc_score = 0.0
        if has_description:
            doc_score += 0.1
        if has_home_page:
            doc_score += 0.05
        if has_classifiers:
            doc_score += 0.05
        score_components.append(doc_score)

        # 4. Downloads volume (weight: 0.3)
        total_downloads = downloads.total_downloads
        if total_downloads > 1000000:
            score_components.append(0.3)
        elif total_downloads > 100000:
            score_components.append(0.25)
        elif total_downloads > 10000:
            score_components.append(0.2)
        elif total_downloads > 1000:
            score_components.append(0.15)
        elif total_downloads > 100:
            score_components.append(0.1)
        elif total_downloads > 0:
            score_components.append(0.05)
        else:
            score_components.append(0.0)

        # Calculate weighted average
        total_weight = 1.0  # Sum of weights above
        health_score = sum(score_components) / total_weight if score_components else 0.0

        # Ensure score is between 0 and 1
        return max(0.0, min(1.0, health_score))

    async def _enrich_package_details(
        self, packages: List[PackageInfo]
    ) -> List[PackageInfo]:
        """
        Enrich package list with detailed information using concurrent requests.

        Parameters
        ----------
        packages : List[PackageInfo]
            List of basic package information

        Returns
        -------
        List[PackageInfo]
            List of enriched package information
        """
        if not packages:
            return packages

        # Limit concurrent requests to avoid overwhelming PyPI
        semaphore = asyncio.Semaphore(
            min(5, self.max_concurrent)
        )  # Reduced from max_concurrent

        async def get_details(package: PackageInfo) -> PackageInfo:
            async with semaphore:
                try:
                    detailed_package = await self.get_package_details(package.name)
                    if detailed_package:
                        # Preserve original score and merge additional data
                        detailed_package.score = package.score
                        return detailed_package
                except Exception as e:
                    logger.debug(f"Failed to enrich {package.name}: {e}")
                return package

        # Process in smaller batches for better rate limiting
        batch_size = min(5, len(packages))
        enriched_packages = []

        for i in range(0, len(packages), batch_size):
            batch = packages[i : i + batch_size]
            tasks = [get_details(package) for package in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in batch_results:
                if isinstance(result, PackageInfo):
                    enriched_packages.append(result)
                elif isinstance(result, Exception):
                    logger.debug(f"Enrichment task failed: {result}")

            # Small delay between batches to respect rate limits
            if i + batch_size < len(packages):
                await asyncio.sleep(0.5)

        return enriched_packages

    def _calculate_relevance_score(self, query: str, name: str, summary: str) -> float:
        """
        Calculate advanced relevance score for search results.

        Uses multiple factors:
        - Exact matches
        - Partial matches
        - Word position
        - Term frequency
        - Field weighting

        Parameters
        ----------
        query : str
            Search query
        name : str
            Package name
        summary : str
            Package summary

        Returns
        -------
        float
            Relevance score between 0.0 and 1.0
        """
        if not query:
            return 0.0

        query_lower = query.lower().strip()
        name_lower = name.lower().strip() if name else ""
        summary_lower = summary.lower().strip() if summary else ""

        if not name_lower:
            return 0.0

        score = 0.0
        max_possible_score = 1.0

        # 1. Exact name match (highest priority)
        if query_lower == name_lower:
            return 1.0

        # 2. Name contains query or query contains name
        if query_lower in name_lower or name_lower in query_lower:
            score += 0.6

        # 3. Name starts with query
        if name_lower.startswith(query_lower):
            score += 0.3

        # 4. Name ends with query
        if name_lower.endswith(query_lower):
            score += 0.2

        # 5. Word-based matching in name
        query_words = set(word for word in query_lower.split() if len(word) > 1)
        name_words = set(word for word in name_lower.split() if len(word) > 1)

        if query_words:
            # Exact word matches
            exact_matches = len(query_words.intersection(name_words))
            if exact_matches > 0:
                score += (exact_matches / len(query_words)) * 0.4

            # Partial word matches (substring)
            partial_matches = 0
            for q_word in query_words:
                for n_word in name_words:
                    if q_word in n_word or n_word in q_word:
                        partial_matches += 1
                        break
            if partial_matches > 0:
                score += (partial_matches / len(query_words)) * 0.3

        # 6. Summary-based scoring (if summary exists)
        if summary_lower:
            summary_score = 0.0

            # Check if query appears in summary
            if query_lower in summary_lower:
                summary_score += 0.5

            # Word matches in summary
            summary_words = set(word for word in summary_lower.split() if len(word) > 1)
            if query_words and summary_words:
                summary_word_matches = len(query_words.intersection(summary_words))
                if summary_word_matches > 0:
                    summary_score += (summary_word_matches / len(query_words)) * 0.3

            # Apply summary weight (lower than name weight)
            score += summary_score * 0.3

        # Normalize and cap score
        normalized_score = min(score, max_possible_score)

        # Apply exponential decay for very low scores
        if normalized_score < 0.1:
            normalized_score = normalized_score**0.5

        return normalized_score

    def _clean_text(self, text: str) -> str:
        """
        Clean and normalize text data.

        Parameters
        ----------
        text : str
            Text to clean

        Returns
        -------
        str
            Cleaned text
        """
        if text is None:
            return ""

        if not isinstance(text, str):
            return ""

        # Remove HTML tags
        text = re.sub(r"<[^>]*>", " ", text)
        # Remove extra whitespace
        text = re.sub(r"\s+", " ", text)
        # Strip leading/trailing whitespace
        text = text.strip()
        # Remove control characters but keep valid unicode
        text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
        # Normalize quotes and dashes
        text = text.replace('"', "'").replace("`", "'")
        text = text.replace("–", "-").replace("—", "-")

        return text

    def _validate_package_name(self, name: str) -> bool:
        """
        Validate package name format.

        Parameters
        ----------
        name : str
            Package name to validate

        Returns
        -------
        bool
            True if valid package name
        """
        if not name or not isinstance(name, str):
            return False

        name = name.strip()

        # Check against PyPI package name rules
        if not name:
            return False

        # Check length
        if len(name) > 100:
            return False

        # Check pattern
        if not self.PACKAGE_NAME_PATTERN.match(name):
            return False

        # Check for obviously invalid names
        invalid_patterns = [
            r"^\d+$",  # Only numbers
            r"^[^a-zA-Z]",  # Doesn't start with letter
            r"[^a-zA-Z0-9_-]",  # Invalid characters
        ]

        for pattern in invalid_patterns:
            if re.match(pattern, name):
                return False

        return True

    def _validate_version(self, version: str) -> bool:
        """
        Validate version string format.

        Parameters
        ----------
        version : str
            Version string to validate

        Returns
        -------
        bool
            True if valid version format
        """
        if not version or version == "unknown":
            return False

        if not isinstance(version, str):
            return False

        return bool(self.VALID_VERSION_PATTERN.match(version))

    def _is_low_quality_package(self, package_name: str) -> bool:
        """
        Identify low-quality or spam package names.

        Parameters
        ----------
        package_name : str
            Package name to check

        Returns
        -------
        bool
            True if likely low-quality/spam package
        """
        if not package_name:
            return True

        name_lower = package_name.lower()

        # Patterns indicating low-quality packages
        low_quality_patterns = [
            r"^\d",  # Starts with number (often spam)
            r"^test",  # Test packages
            r"^example",  # Example packages
            r"-test$",  # Ends with -test
            r"^aaa",  # Trying to be first in alphabetical lists
            r"^zzz",  # Trying to be last
            r"[0-9]{8,}",  # Many numbers (often dates as names)
            r"^[0-9]+[a-z]+$",  # Number followed by letters (common spam pattern)
        ]

        for pattern in low_quality_patterns:
            if re.search(pattern, name_lower):
                return True

        # Check for suspicious character patterns
        suspicious_chars = ["__", "--", ".."]
        for chars in suspicious_chars:
            if chars in package_name:
                return True

        return False

    async def batch_search(
        self,
        queries: List[str],
        max_results: int = 10,
        include_details: bool = True,
        concurrent_limit: Optional[int] = None,
    ) -> Dict[str, List[PackageInfo]]:
        """
        Perform multiple searches concurrently with optimized resource usage.

        Parameters
        ----------
        queries : List[str]
            List of search queries
        max_results : int, optional
            Maximum results per query, by default 10
        include_details : bool, optional
            Whether to include detailed package information, by default True
        concurrent_limit : Optional[int], optional
            Custom concurrent limit, by default None

        Returns
        -------
        Dict[str, List[PackageInfo]]
            Dictionary mapping queries to search results

        Examples
        --------
        >>> results = await searcher.batch_search(["requests", "numpy", "pandas"])
        >>> for query, packages in results.items():
        >>>     print(f"{query}: {len(packages)} packages")
        """
        if not queries:
            return {}

        # Use custom limit or default to a conservative value
        limit = concurrent_limit or min(3, self.max_concurrent)  # Reduced concurrency
        semaphore = asyncio.Semaphore(limit)

        async def search_with_limit(query: str) -> Tuple[str, List[PackageInfo]]:
            async with semaphore:
                try:
                    results = await self.search(
                        query,
                        max_results,
                        include_details,
                        min_score_threshold=0.4,  # Higher threshold for batch
                    )
                    return query, results
                except Exception as e:
                    logger.error(f"Batch search failed for {query}: {e}")
                    return query, []

        # Stagger task creation to avoid overwhelming the system
        tasks = []
        for i, query in enumerate(queries):
            # Add small delay between task creation
            if i > 0 and i % 2 == 0:
                await asyncio.sleep(0.1)
            tasks.append(search_with_limit(query))

        results_list = await asyncio.gather(*tasks)

        return dict(results_list)

    async def compare_packages(self, package_names: List[str]) -> PackageComparison:
        """
        Compare multiple packages across various metrics.

        Parameters
        ----------
        package_names : List[str]
            List of package names to compare

        Returns
        -------
        PackageComparison
            Comparison data object

        Examples
        --------
        >>> comparison = await searcher.compare_packages(["requests", "httpx"])
        >>> print(f"Health scores: {comparison.health_scores}")
        """
        packages = {}

        # Fetch package details with limited concurrency
        semaphore = asyncio.Semaphore(min(3, self.max_concurrent))

        async def fetch_package(name: str) -> Tuple[str, Optional[PackageInfo]]:
            async with semaphore:
                try:
                    package = await self.get_package_details(name)
                    return name, package
                except Exception as e:
                    logger.warning(f"Failed to get details for {name}: {e}")
                    return name, None

        tasks = [fetch_package(name) for name in package_names]
        results = await asyncio.gather(*tasks)

        for name, result in results:
            if isinstance(result, PackageInfo):
                packages[name] = result

        # Generate comparison data
        comparison = PackageComparison(
            health_scores={name: pkg.health_score for name, pkg in packages.items()},
            downloads={
                name: pkg.downloads.total_downloads if pkg.downloads else 0
                for name, pkg in packages.items()
            },
            latest_versions={name: pkg.version for name, pkg in packages.items()},
            dependencies_count={
                name: len(pkg.dependencies) for name, pkg in packages.items()
            },
            development_status={
                name: pkg.development_status for name, pkg in packages.items()
            },
            recent_activity={
                name: pkg.recent_activity.recent_releases if pkg.recent_activity else 0
                for name, pkg in packages.items()
            },
            days_since_last_release={
                name: (
                    pkg.recent_activity.days_since_last_release
                    if pkg.recent_activity
                    else None
                )
                for name, pkg in packages.items()
            },
        )

        return comparison

    def get_search_statistics(self) -> SearchStatistics:
        """
        Get search performance and usage statistics.

        Returns
        -------
        SearchStatistics
            Search statistics object
        """
        total_searches = self._search_stats["total_searches"]
        cache_hits = self._search_stats["cache_hits"]

        stats = SearchStatistics(
            total_searches=total_searches,
            successful_searches=self._search_stats["successful_searches"],
            failed_searches=self._search_stats["failed_searches"],
            cache_hits=cache_hits,
            cache_hit_rate=(cache_hits / total_searches if total_searches > 0 else 0),
            average_response_time=self._search_stats["average_response_time"],
            current_cache_size=len(self._cache),
            cache_directory=str(self._cache_dir),
            cache_strategy=(
                self.cache_strategy.value
                if hasattr(self.cache_strategy, "value")
                else self.cache_strategy
            ),
        )

        # Add request timing statistics if available
        if self._request_times:
            stats.average_request_time = sum(self._request_times) / len(
                self._request_times
            )
            stats.min_request_time = min(self._request_times)
            stats.max_request_time = max(self._request_times)
            stats.total_requests_timed = len(self._request_times)

        return stats

    async def export_results(
        self,
        packages: List[PackageInfo],
        format: str = "json",
        include_all_fields: bool = False,
    ) -> ExportData:
        """
        Export search results to various formats.

        Parameters
        ----------
        packages : List[PackageInfo]
            List of packages to export
        format : str, optional
            Export format (json, csv, text), by default "json"
        include_all_fields : bool, optional
            Include all fields in export (for JSON only), by default False

        Returns
        -------
        ExportData
            Export data object containing format and content

        Raises
        ------
        ValueError
            If the format is not supported
        """
        content = ""

        if format == "json":
            if include_all_fields:
                data = [self._package_to_dict(pkg) for pkg in packages]
            else:
                # Simplified export for common use cases
                data = []
                for pkg in packages:
                    simple_dict = {
                        "name": pkg.name,
                        "version": pkg.version,
                        "score": round(pkg.score, 3),
                        "health_score": round(pkg.health_score, 3),
                        "downloads": (
                            pkg.downloads.total_downloads if pkg.downloads else 0
                        ),  # FIXED
                        "author": pkg.author,
                        "license": pkg.license,
                        "python_version": pkg.requires_python,
                        "summary": pkg.summary[:200] if pkg.summary else "",  # Truncate
                        "dependencies_count": len(pkg.dependencies),
                        "last_updated": pkg.last_updated,
                    }
                    data.append(simple_dict)
            content = json.dumps(data, indent=2, ensure_ascii=False)

        elif format == "csv":
            import csv
            import io

            output = io.StringIO()
            writer = csv.writer(output)

            # Write header
            writer.writerow(
                [
                    "Name",
                    "Version",
                    "Score",
                    "Health",
                    "Downloads",
                    "Author",
                    "License",
                    "Python",
                    "Dependencies",
                    "Summary",
                ]
            )

            # Write data
            for pkg in packages:
                writer.writerow(
                    [
                        pkg.name,
                        pkg.version,
                        f"{pkg.score:.3f}",
                        f"{pkg.health_score:.3f}",
                        pkg.downloads.total_downloads if pkg.downloads else 0,  # FIXED
                        pkg.author[:50] if pkg.author else "",  # Truncate
                        pkg.license[:30] if pkg.license else "",  # Truncate
                        pkg.requires_python or "",
                        len(pkg.dependencies),
                        (
                            pkg.summary[:100].replace("\n", " ").replace("\r", "")
                            if pkg.summary
                            else ""
                        ),  # Truncate and clean
                    ]
                )
            content = output.getvalue()

        elif format == "text":
            lines = []
            for i, pkg in enumerate(packages, 1):
                lines.extend(
                    [
                        f"{i}. {pkg.name} v{pkg.version}",
                        f"   Score: {pkg.score:.3f}, Health: {pkg.health_score:.3f}",
                        f"   Downloads: {(pkg.downloads.total_downloads if pkg.downloads else 0):,}",  # FIXED
                        f"   Dependencies: {len(pkg.dependencies)}",
                        f"   Author: {pkg.author or 'Unknown'}",
                        f"   License: {pkg.license or 'Unknown'}",
                        f"   Python: {pkg.requires_python or 'Any'}",
                        f"   Last Updated: {pkg.last_updated or 'Unknown'}",
                        f"   Summary: {pkg.summary[:150] if pkg.summary else 'No summary'}",
                        "-" * 60,
                    ]
                )
            content = "\n".join(lines)

        else:
            raise ValueError(
                f"Unsupported format: {format}. Use 'json', 'csv', or 'text'."
            )

        return ExportData(format=format, content=content, package_count=len(packages))

    def _package_to_dict(self, package: PackageInfo) -> Dict[str, Any]:
        """
        Convert PackageInfo to dictionary for serialization.

        Parameters
        ----------
        package : PackageInfo
            Package information object

        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the package
        """
        return asdict(package)

    async def _save_metrics(self) -> None:
        """
        Save search metrics to disk for analysis.

        Returns
        -------
        None
        """
        if not self.metrics or not self.enable_metrics:
            return

        metrics_file = self._cache_dir / "search_metrics.json"
        try:
            # Ensure directory exists
            metrics_file.parent.mkdir(exist_ok=True, parents=True)

            # Load existing metrics if any
            existing_metrics = []
            if metrics_file.exists():
                try:
                    existing_data = json.loads(metrics_file.read_text())
                    if isinstance(existing_data, list):
                        existing_metrics = existing_data
                except (json.JSONDecodeError, IOError):
                    pass  # Start fresh if file is corrupted

            # Add new metrics
            metrics_data = existing_metrics + [
                {
                    "query": m.query,
                    "strategy_used": m.strategy_used.value,
                    "response_time": round(m.response_time, 3),
                    "results_count": m.results_count,
                    "cache_hit": m.cache_hit,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in self.metrics
            ]

            # Keep only last 1000 entries to prevent file bloat
            if len(metrics_data) > 1000:
                metrics_data = metrics_data[-1000:]

            # Write to file
            metrics_file.write_text(json.dumps(metrics_data, indent=2))
            logger.info(
                f"Saved {len(self.metrics)} metrics records (total: {len(metrics_data)})"
            )

            # Clear in-memory metrics after saving
            self.metrics.clear()

        except (IOError, PermissionError, OSError) as e:
            logger.warning(f"Failed to save metrics to {metrics_file}: {e}")

    def clear_cache(
        self, older_than: Optional[float] = None, clear_disk: bool = True
    ) -> None:
        """
        Clear cache with optional age-based filtering.

        Parameters
        ----------
        older_than : Optional[float], optional
            Clear entries older than this timestamp (seconds), by default None
        clear_disk : bool, optional
            Whether to clear disk cache, by default True
        """
        current_time = time.time()
        cleared_memory = 0
        cleared_disk = 0

        # Clear memory cache
        if older_than is None:
            cleared_memory = len(self._cache)
            self._cache.clear()
        else:
            expired_keys = [
                key
                for key, (timestamp, _) in self._cache.items()
                if current_time - timestamp > older_than
            ]
            cleared_memory = len(expired_keys)
            for key in expired_keys:
                del self._cache[key]

        # Clear disk cache
        if clear_disk and self.cache_strategy in [
            CacheStrategy.DISK,
            CacheStrategy.HYBRID,
        ]:
            cache_files = list(self._cache_dir.glob("*.cache"))
            for cache_file in cache_files:
                try:
                    if older_than is None:
                        cache_file.unlink()
                        cleared_disk += 1
                    else:
                        file_age = current_time - cache_file.stat().st_mtime
                        if file_age > older_than:
                            cache_file.unlink()
                            cleared_disk += 1
                except (OSError, PermissionError) as e:
                    logger.warning(f"Failed to delete cache file {cache_file}: {e}")

        logger.info(
            f"Cache cleared: {cleared_memory} memory entries, {cleared_disk} disk files"
            + (f" (older than {older_than}s)" if older_than else "")
        )
