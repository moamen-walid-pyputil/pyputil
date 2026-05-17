#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Utility functions for the package detector.

This module contains helper functions for path manipulation,
error handling, caching, and other common operations.
"""

import sys
import os
import warnings
import functools
import hashlib
import json
import inspect
import tempfile
import shutil
import zipfile
import time
import tarfile
from contextlib import contextmanager
from pathlib import Path, PurePath
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
    Iterator,
    TypeVar,
    Generic,
    cast,
)
try:
	from typing_extensions import ParamSpec
except ImportError:
	from typing import ParamSpec

from .exceptions import (
    PathResolutionError,
    PermissionError,
    CacheError,
    PackageDetectorError,
)
from .constants import PlatformType

T = TypeVar("T")
P = ParamSpec("P")


class SafePath:
    """Safe path operations with error handling."""

    @staticmethod
    def resolve(path: Union[str, Path], strict: bool = False) -> Optional[Path]:
        """
        Safely resolve a path, returning None on failure.

        Args:
            path: Path to resolve.
            strict: If True, raise exceptions on failure.

        Returns:
            Resolved path or None if failed and strict=False.

        Raises:
            PathResolutionError: If strict=True and resolution fails.
        """
        try:
            if isinstance(path, str):
                path = Path(path)

            # Try to resolve, but handle symlinks carefully
            try:
                resolved = path.resolve(strict=strict)
                # Check if path exists (if strict=False, resolve doesn't check)
                if not strict and not resolved.exists():
                    return None
                return resolved
            except RuntimeError:
                # Handle symlink loops
                return path.absolute()

        except (OSError, PermissionError) as e:
            if strict:
                raise PathResolutionError(path, e) from e
            return None
        except Exception as e:
            if strict:
                raise PathResolutionError(path, e) from e
            return None

    @staticmethod
    def is_relative_to(path: Path, other: Union[str, Path]) -> bool:
        """
        Safely check if path is relative to another path.

        Args:
            path: Path to check.
            other: Potential parent path.

        Returns:
            True if path is relative to other, False otherwise.
        """
        try:
            if isinstance(other, str):
                other = Path(other)

            # Handle case-insensitive file systems
            if sys.platform in ("win32", "darwin"):
                path_str = str(path).lower()
                other_str = str(other).lower()
                return path_str.startswith(other_str)

            return path.is_relative_to(other)
        except (ValueError, AttributeError, TypeError):
            return False

    @staticmethod
    def exists(path: Union[str, Path]) -> bool:
        """Safely check if path exists."""
        try:
            if isinstance(path, str):
                path = Path(path)
            return path.exists()
        except (OSError, PermissionError):
            return False


class ErrorHandler:
    """Context manager and decorator for error handling."""

    @staticmethod
    @contextmanager
    def suppress_errors(
        *exceptions: type, default: Any = None, log_message: Optional[str] = None
    ) -> Iterator[Any]:
        """
        Context manager to suppress specified exceptions.

        Args:
            exceptions: Exception types to suppress.
            default: Value to return if exception occurs.
            log_message: Optional message to log when suppressing.
        """
        try:
            yield
        except exceptions as e:
            if log_message:
                warnings.warn(f"{log_message}: {e}", RuntimeWarning)
            return default
        except Exception as e:
            if log_message:
                warnings.warn(f"Unexpected error {log_message}: {e}", RuntimeWarning)
            return default

    @staticmethod
    def safe_execute(
        func: Callable[P, T],
        default: Any = None,
        exceptions: Tuple[type, ...] = (Exception,),
        finally_func: Optional[Callable] = None,
        **kwargs: Any,
    ) -> Union[T, Any]:
        """
        Safely execute a function with error handling.

        Args:
            func: Function to execute.
            default: Default value if function fails.
            exceptions: Exception types to catch.
            finally_func: Function to call in finally block.
            **kwargs: Arguments to pass to function.

        Returns:
            Function result or default value.
        """
        try:
            return func(**kwargs)
        except exceptions as e:
            warnings.warn(f"Function {func.__name__} failed: {e}", RuntimeWarning)
            return default
        finally:
            if finally_func:
                try:
                    finally_func()
                except Exception as e:
                    warnings.warn(f"Finally function failed: {e}", RuntimeWarning)


class CacheManager:
    """Simple cache manager with TTL and persistence."""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """
        Initialize cache manager.

        Args:
            max_size: Maximum number of cache entries.
            ttl_seconds: Time to live for cache entries in seconds.
        """
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache if not expired.

        Args:
            key: Cache key.

        Returns:
            Cached value or None.
        """
        if key not in self._cache:
            return None

        timestamp, value = self._cache[key]
        if (time.time() - timestamp) > self.ttl_seconds:
            del self._cache[key]
            return None

        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set value in cache.

        Args:
            key: Cache key.
            value: Value to cache.
        """
        # Remove oldest entry if cache is full
        if len(self._cache) >= self.max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[key] = (time.time(), value)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def delete(self, key: str) -> bool:
        """
        Delete entry from cache.

        Args:
            key: Cache key.

        Returns:
            True if deleted, False if not found.
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False


class PlatformUtils:
    """Platform-specific utilities."""

    @staticmethod
    def detect_platform() -> PlatformType:
        """
        Detect the current platform.

        Returns:
            PlatformType enum.
        """
        platform = sys.platform

        if platform == "win32":
            return PlatformType.WINDOWS
        elif platform.startswith("linux"):
            # Check for WSL
            if "microsoft" in platform or "wsl" in platform.lower():
                return PlatformType.WSL
            return PlatformType.LINUX
        elif platform == "darwin":
            return PlatformType.MACOS
        elif platform == "cygwin":
            return PlatformType.CYGWIN
        else:
            return PlatformType.UNKNOWN

    @staticmethod
    def get_home_dir() -> Path:
        """
        Get user's home directory in a cross-platform way.

        Returns:
            Path to home directory.
        """
        try:
            return Path.home()
        except (RuntimeError, KeyError):
            # Fallback for older Python versions
            home = os.environ.get("HOME")
            if home:
                return Path(home)

            # Windows fallback
            if sys.platform == "win32":
                home = os.environ.get("USERPROFILE")
                if home:
                    return Path(home)

            # Last resort
            return Path.cwd()

    @staticmethod
    def normalize_path_case(path: Path) -> Path:
        """
        Normalize path case for case-insensitive systems.

        Args:
            path: Path to normalize.

        Returns:
            Normalized path.
        """
        platform = PlatformUtils.detect_platform()

        if platform in (PlatformType.WINDOWS, PlatformType.MACOS):
            # Case-insensitive file systems
            return Path(str(path).lower())
        else:
            # Case-sensitive file systems
            return path


class FileUtils:
    """File operation utilities with error handling."""

    @staticmethod
    def read_text_safe(
        path: Union[str, Path], encoding: str = "utf-8", errors: str = "replace"
    ) -> Optional[str]:
        """
        Safely read text from file.

        Args:
            path: Path to file.
            encoding: File encoding.
            errors: Error handling strategy.

        Returns:
            File contents or None if failed.
        """
        try:
            with open(path, "r", encoding=encoding, errors=errors) as f:
                return f.read()
        except (OSError, PermissionError, UnicodeDecodeError):
            return None

    @staticmethod
    def read_json_safe(path: Union[str, Path]) -> Optional[Dict[str, Any]]:
        """
        Safely read JSON from file.

        Args:
            path: Path to JSON file.

        Returns:
            Parsed JSON or None if failed.
        """
        content = FileUtils.read_text_safe(path)
        if content is None:
            return None

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def find_files(
        directory: Union[str, Path], pattern: str = "*", recursive: bool = True
    ) -> List[Path]:
        """
        Find files matching pattern with error handling.

        Args:
            directory: Directory to search.
            pattern: Glob pattern.
            recursive: Whether to search recursively.

        Returns:
            List of matching files.
        """
        try:
            if isinstance(directory, str):
                directory = Path(directory)

            if recursive:
                return list(directory.rglob(pattern))
            else:
                return list(directory.glob(pattern))
        except (OSError, PermissionError):
            return []


class HashUtils:
    """Hash calculation utilities."""

    @staticmethod
    def file_hash(
        path: Union[str, Path], algorithm: str = "sha256", chunk_size: int = 8192
    ) -> Optional[str]:
        """
        Calculate hash of a file.

        Args:
            path: Path to file.
            algorithm: Hash algorithm.
            chunk_size: Read chunk size.

        Returns:
            Hash string or None if failed.
        """
        try:
            hash_func = hashlib.new(algorithm)

            with open(path, "rb") as f:
                while chunk := f.read(chunk_size):
                    hash_func.update(chunk)

            return hash_func.hexdigest()
        except (OSError, PermissionError, ValueError):
            return None


# Global cache instance
_CACHE = CacheManager(max_size=2000, ttl_seconds=600)

# Global utilities instances
safe_path = SafePath()
error_handler = ErrorHandler()
platform_utils = PlatformUtils()
file_utils = FileUtils()
hash_utils = HashUtils()
