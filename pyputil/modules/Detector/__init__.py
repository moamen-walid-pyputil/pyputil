#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Package Detector - Comprehensive Python Package Origin Detection.

This package provides tools to detect where Python packages are installed from,
with support for multiple platforms, environments, and installation methods.
"""

from .detector import (
    PackageDetector,
    detect_package_origin,
    detect_all_installed_packages,
    DetectionResult,
    DetectionMethod,
    get_package_info,
)
from .constants import (
    PackageOrigin,
    PackageInfo,
    DetectionConfidence,
    PlatformType,
    EnvironmentType,
)
from .exceptions import (
    PackageDetectorError,
    PackageNotFoundError,
    MetadataReadError,
    PathResolutionError,
    PlatformDetectionError,
    EnvironmentDetectionError,
)


__all__ = [
    # Main functions
    "detect_package_origin",
    "detect_all_installed_packages",
    "get_package_info",
    # Main classes
    "PackageDetector",
    "DetectionResult",
    "DetectionMethod",
    # Constants and types
    "PackageOrigin",
    "PackageInfo",
    "DetectionConfidence",
    "PlatformType",
    "EnvironmentType",
    # Exceptions
    "PackageDetectorError",
    "PackageNotFoundError",
    "MetadataReadError",
    "PathResolutionError",
    "PlatformDetectionError",
    "EnvironmentDetectionError",
]
