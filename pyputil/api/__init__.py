#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Main Components
--------------
clean : Main decorator.
APIMetadata : Data class for API metadata
RateLimiter : Rate limiting system
APIAnalytics : Usage analytics and monitoring
APIObserver : Event observer system

Usage
-----
>>> from pyputil.api import clean
>>> clean(expose=['public_func'], block=['private_func'])
>>> clean(
...     expose=['api1', 'api2'],
...     cache=True,
...     rate_limit={'api1': 5},
...     enable_analytics=True
... )

For more details, see individual module documentation.
"""

from .main import clean
from .dataclasses import APIMetadata
from .rate_limiter import RateLimiter
from .cache import APICache
from .analytics import APIAnalytics
from .observer import APIObserver
from .enums import PrivacyLevel, APIMemberType
from .decorators import profile_api, validate_types, deprecated, experimental

__all__ = [
    "clean",
    "APIMetadata",
    "RateLimiter",
    "APICache",
    "APIAnalytics",
    "APIObserver",
    "PrivacyLevel",
    "APIMemberType",
    "profile_api",
    "validate_types",
    "deprecated",
    "experimental",
]

clean(expose=__all__)
