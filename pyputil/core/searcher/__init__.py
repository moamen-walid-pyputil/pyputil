#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Enhanced PyPI Search Toolkit.

A comprehensive toolkit for searching PyPI packages with features
including multi-strategy search, caching, health scoring, and performance metrics.

Modules
-------
enums : Search and cache strategy enumerations
models : Data models for packages and metrics
searcher : Main search implementation
api : Convenience functions for simplified usage
"""

from .enums import SearchStrategy, CacheStrategy
from .models import PackageInfo, SearchMetrics
from .searcher import Searcher
from .api import search_package, search_sync


__all__ = [
    "SearchStrategy",
    "CacheStrategy",
    "PackageInfo",
    "SearchMetrics",
    "Searcher",
    "search_package",
    "search_sync",
]
