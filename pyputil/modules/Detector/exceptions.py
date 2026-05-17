#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Custom exceptions for packet detection.

This module defines all custom exceptions used in the packet detection system and provides information about errors and context for debugging.
"""

from typing import Optional, Any, Dict, List
from pathlib import Path


class PackageDetectorError(Exception):
    """Base exception for all package detector errors."""

    def __init__(self, message: str, package_name: Optional[str] = None, **context):
        self.package_name = package_name
        self.context = context
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        base = f"PackageDetectorError: {self.message}"
        if self.package_name:
            base += f" (package: {self.package_name})"
        return base


class PackageNotFoundError(PackageDetectorError):
    """Raised when a package cannot be found."""

    def __init__(self, package_name: str, search_paths: Optional[List[str]] = None):
        self.search_paths = search_paths or []
        super().__init__(
            f"Package '{package_name}' not found",
            package_name=package_name,
            search_paths=search_paths,
        )


class MetadataReadError(PackageDetectorError):
    """Raised when package metadata cannot be read."""

    def __init__(
        self,
        package_name: str,
        metadata_file: Optional[Path] = None,
        error: Optional[Exception] = None,
    ):
        self.metadata_file = metadata_file
        self.original_error = error
        error_msg = str(error) if error else "Unknown error"
        super().__init__(
            f"Failed to read metadata for '{package_name}': {error_msg}",
            package_name=package_name,
            metadata_file=str(metadata_file) if metadata_file else None,
            original_error=error_msg,
        )


class PathResolutionError(PackageDetectorError):
    """Raised when a path cannot be resolved."""

    def __init__(self, path: Path, error: Optional[Exception] = None):
        self.path = path
        self.original_error = error
        error_msg = str(error) if error else "Unknown error"
        super().__init__(
            f"Failed to resolve path '{path}': {error_msg}",
            path=str(path),
            original_error=error_msg,
        )


class PlatformDetectionError(PackageDetectorError):
    """Raised when platform detection fails."""

    def __init__(self, error: Optional[Exception] = None):
        self.original_error = error
        error_msg = str(error) if error else "Unknown error"
        super().__init__(
            f"Failed to detect platform: {error_msg}", original_error=error_msg
        )


class EnvironmentDetectionError(PackageDetectorError):
    """Raised when environment detection fails."""

    def __init__(self, error: Optional[Exception] = None):
        self.original_error = error
        error_msg = str(error) if error else "Unknown error"
        super().__init__(
            f"Failed to detect environment: {error_msg}", original_error=error_msg
        )


class ConfidenceCalculationError(PackageDetectorError):
    """Raised when confidence calculation fails."""

    def __init__(self, package_name: str, error: Optional[Exception] = None):
        self.original_error = error
        error_msg = str(error) if error else "Unknown error"
        super().__init__(
            f"Failed to calculate confidence for '{package_name}': {error_msg}",
            package_name=package_name,
            original_error=error_msg,
        )


class CircularImportError(PackageDetectorError):
    """Raised when circular import is detected during analysis."""

    def __init__(self, package_name: str, import_chain: List[str]):
        self.import_chain = import_chain
        chain_str = " -> ".join(import_chain)
        super().__init__(
            f"Circular import detected for '{package_name}': {chain_str}",
            package_name=package_name,
            import_chain=import_chain,
        )


class PermissionError(PackageDetectorError):
    """Raised when permission is denied for file operations."""

    def __init__(self, path: Path, operation: str = "access"):
        self.path = path
        self.operation = operation
        super().__init__(
            f"Permission denied to {operation} '{path}'",
            path=str(path),
            operation=operation,
        )


class CompatibilityError(PackageDetectorError):
    """Raised when compatibility issues are detected."""

    def __init__(
        self, package_name: str, issue: str, details: Optional[Dict[str, Any]] = None
    ):
        self.issue = issue
        self.details = details or {}
        super().__init__(
            f"Compatibility issue with '{package_name}': {issue}",
            package_name=package_name,
            issue=issue,
            details=details,
        )


class CacheError(PackageDetectorError):
    """Raised when cache operations fail."""

    def __init__(self, operation: str, error: Optional[Exception] = None):
        self.operation = operation
        self.original_error = error
        error_msg = str(error) if error else "Unknown error"
        super().__init__(
            f"Cache {operation} failed: {error_msg}",
            operation=operation,
            original_error=error_msg,
        )
