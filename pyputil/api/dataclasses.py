#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
from typing import Optional, Set, List, Any, Callable
from datetime import datetime
from .enums import PrivacyLevel, APIMemberType


@dataclass
class APIMetadata:
    """
    Comprehensive metadata.

    Attributes
    ----------
    name : str
        Name of the API member
    type : APIMemberType
        Type of API member
    privacy_level : PrivacyLevel
        Privacy/access level
    docstring : str, optional
        Documentation string
    signature : str, optional
        Function signature
    source_file : str, optional
        Source file path
    line_number : int, optional
        Line number in source
    added_in_version : str, optional
        Version when added
    deprecated_in_version : str, optional
        Version when deprecated
    removed_in_version : str, optional
        Version when removed
    deprecated_message : str, optional
        Deprecation message
    experimental : bool
        Whether experimental feature
    thread_safe : bool, optional
        Thread safety indicator
    async_safe : bool, optional
        Async safety indicator
    requires_auth : bool
        Requires authentication
    rate_limit : int, optional
        Rate limit (calls per second)
    tags : Set[str]
        Categorization tags
    dependencies : Set[str]
        Dependencies
    return_type : str, optional
        Return type hint
    exceptions : Set[str]
        Possible exceptions
    examples : List[str]
        Usage examples
    performance : float, optional
        Average execution time (seconds)
    memory_usage : int, optional
        Memory usage in bytes
    last_accessed : float, optional
        Last access timestamp
    access_count : int
        Total access count
    is_lazy_loaded : bool
        Whether lazy-loaded
    lazy_loader : Callable[[], Any], optional
        Lazy loader function
    cached_value : Any, optional
        Cached value
    cache_hits : int
        Cache hit count
    cache_misses : int
        Cache miss count
    """

    name: str
    type: APIMemberType
    privacy_level: PrivacyLevel
    docstring: Optional[str] = None
    signature: Optional[str] = None
    source_file: Optional[str] = None
    line_number: Optional[int] = None
    added_in_version: Optional[str] = None
    deprecated_in_version: Optional[str] = None
    removed_in_version: Optional[str] = None
    deprecated_message: Optional[str] = None
    experimental: bool = False
    thread_safe: Optional[bool] = None
    async_safe: Optional[bool] = None
    requires_auth: bool = False
    rate_limit: Optional[int] = None
    tags: Set[str] = field(default_factory=set)
    dependencies: Set[str] = field(default_factory=set)
    return_type: Optional[str] = None
    exceptions: Set[str] = field(default_factory=set)
    examples: List[str] = field(default_factory=list)
    performance: Optional[float] = None  # Average execution time in seconds
    memory_usage: Optional[int] = None  # Memory usage in bytes
    last_accessed: Optional[float] = None
    access_count: int = 0
    is_lazy_loaded: bool = False
    lazy_loader: Optional[Callable[[], Any]] = None
    cached_value: Optional[Any] = None
    cache_hits: int = 0
    cache_misses: int = 0
