#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Enumerations for the enhanced PyPI search toolkit.

This module defines enumerations used throughout the search toolkit,
including search strategies and cache strategies.
"""

from enum import Enum


class SearchStrategy(Enum):
    """
    Available search strategies in order of preference.

    Attributes
    ----------
    PRIMARY_JSON_API : str
        Primary strategy using PyPI's JSON API (fastest, most accurate)
    SECONDARY_WEB_SCRAPING : str
        Secondary strategy using web scraping (comprehensive)
    FALLBACK_SIMPLE_INDEX : str
        Fallback strategy using simple index scanning
    DIRECT_PACKAGE_LOOKUP : str
        Direct package lookup as last resort
    """

    PRIMARY_JSON_API = "primary_json_api"
    SECONDARY_WEB_SCRAPING = "secondary_web_scraping"
    FALLBACK_SIMPLE_INDEX = "fallback_simple_index"
    DIRECT_PACKAGE_LOOKUP = "direct_package_lookup"
    CACHE = "cache"


class CacheStrategy(Enum):
    """
    Cache storage strategies.

    Attributes
    ----------
    MEMORY : str
        Store cache only in memory
    DISK : str
        Store cache only on disk
    HYBRID : str
        Store cache in both memory and disk
    """

    MEMORY = "memory"
    DISK = "disk"
    HYBRID = "hybrid"
