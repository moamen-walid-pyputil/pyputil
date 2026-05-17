#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
API convenience functions.

This module provides high-level convenience functions for the enhanced
PyPI search capabilities with sensible defaults and automatic resource management
"""

import asyncio
from typing import List, Optional

from .searcher import Searcher
from .models import PackageInfo


async def search_package(
    query: str,
    max_results: int = 20,
    include_details: bool = True,
    timeout: int = 30,
    **kwargs,
) -> List[PackageInfo]:
    """
    High-level convenience function for PyPI package search.

    This function provides a simple interface for the enhanced PyPI search
    capabilities with sensible defaults and automatic resource management.

    Parameters
    ----------
    query : str
        Search query string
    max_results : int, optional
        Maximum number of results, by default 20
    include_details : bool, optional
        Whether to fetch detailed package information, by default True
    timeout : int, optional
        Request timeout in seconds, by default 30
    **kwargs : dict
        Additional arguments for Searcher

    Returns
    -------
    List[PackageInfo]
        List of PackageInfo objects sorted by relevance

    Examples
    --------
    >>> import asyncio
    >>>
    >>> async def main():
    >>>     results = await search_package("web framework", max_results=5)
    >>>     for package in results:
    >>>         print(f"{package.name} v{package.version}")
    >>>         print(f"   Health: {package.health_score:.2f}")
    >>>         print(f"   Downloads: {package.downloads.get('total_downloads', 0):,}")
    >>>
    >>> asyncio.run(main())
    """
    async with Searcher(timeout=timeout, **kwargs) as searcher:
        return await searcher.search(query, max_results, include_details)


def search_sync(
    query: str,
    max_results: int = 20,
    include_details: bool = True,
    timeout: int = 30,
    **kwargs,
) -> List[PackageInfo]:
    """
    Synchronous wrapper for PyPI package search.

    Note: This function creates a new event loop and should not be used
    in async contexts. For async code, use search_package instead.

    Parameters
    ----------
    query : str
        Search query string
    max_results : int, optional
        Maximum number of results, by default 20
    include_details : bool, optional
        Whether to fetch detailed package information, by default True
    timeout : int, optional
        Request timeout in seconds, by default 30
    **kwargs : dict
        Additional arguments for Searcher

    Returns
    -------
    List[PackageInfo]
        List of PackageInfo objects sorted by relevance
    """
    return asyncio.run(
        search_package(query, max_results, include_details, timeout, **kwargs)
    )
