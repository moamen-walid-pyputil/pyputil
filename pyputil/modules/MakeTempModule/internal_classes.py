#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from collections.abc import MutableMapping
import threading
import time
from typing import Any, Dict, Optional

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from .dataclasses import ModuleConfig


class _ImmutableNamespace(MutableMapping):
    """
    Immutable namespace for module dictionaries.

    Provides a read-only wrapper around a dictionary that prevents
    modifications to module attributes.

    Parameters
    ----------
    data : Dict[str, Any]
        Initial dictionary data.

    Raises
    ------
    PermissionError
        When attempting to modify or delete items.

    Examples
    --------
    >>> ns = _ImmutableNamespace({"a": 1, "b": 2})
    >>> ns["a"]
    1
    >>> ns["a"] = 3  # Raises PermissionError
    PermissionError: Namespace is immutable
    """

    def __init__(self, data: Dict[str, Any]):
        """
        Initialize immutable namespace with data.

        Parameters
        ----------
        data : Dict[str, Any]
            Initial data for the namespace.
        """
        self._data = data.copy()
        self._lock = threading.RLock()

    def __getitem__(self, key: str) -> Any:
        """
        Get item from namespace.

        Parameters
        ----------
        key : str
            Key to retrieve.

        Returns
        -------
        Any
            Value associated with key.

        Raises
        ------
        KeyError
            If key is not in namespace.
        """
        with self._lock:
            return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """
        Set item in namespace (not allowed).

        Parameters
        ----------
        key : str
            Key to set.
        value : Any
            Value to set.

        Raises
        ------
        PermissionError
            Always, as namespace is immutable.
        """
        raise PermissionError("Namespace is immutable")

    def __delitem__(self, key: str) -> None:
        """
        Delete item from namespace (not allowed).

        Parameters
        ----------
        key : str
            Key to delete.

        Raises
        ------
        PermissionError
            Always, as namespace is immutable.
        """
        raise PermissionError("Namespace is immutable")

    def __iter__(self):
        """
        Return iterator over namespace keys.

        Returns
        -------
        iterator
            Iterator over keys.
        """
        with self._lock:
            return iter(self._data.copy())

    def __len__(self) -> int:
        """
        Get number of items in namespace.

        Returns
        -------
        int
            Number of items.
        """
        with self._lock:
            return len(self._data)

    def __contains__(self, key: str) -> bool:
        """
        Check if key is in namespace.

        Parameters
        ----------
        key : str
            Key to check.

        Returns
        -------
        bool
            True if key exists, False otherwise.
        """
        with self._lock:
            return key in self._data

    def __repr__(self) -> str:
        """
        String representation of namespace.

        Returns
        -------
        str
            Representation string.
        """
        return f"ImmutableNamespace({self._data})"

    def copy(self) -> Dict[str, Any]:
        """
        Return a copy of the underlying dictionary.

        Returns
        -------
        Dict[str, Any]
            Copy of the namespace data.
        """
        with self._lock:
            return self._data.copy()


class _ResourceMonitor:
    """
    Monitor resource usage during module execution.

    Tracks time, memory, recursion depth, and operation count
    against configured limits.

    Parameters
    ----------
    config : ModuleConfig
        Configuration with resource limits.

    Raises
    ------
    TimeoutError
        When execution exceeds timeout limit.
    MemoryError
        When memory usage exceeds limit.
    ResourceWarning
        When operation count exceeds limit.

    Examples
    --------
    >>> monitor = _ResourceMonitor(config)
    >>> monitor.check_resources()
    """

    def __init__(self, config: ModuleConfig):
        """
        Initialize resource monitor.

        Parameters
        ----------
        config : ModuleConfig
            Configuration with resource limits.
        """
        self.config = config
        self.start_time = time.time()
        self.start_memory = self._get_memory_usage()
        self.recursion_depth = 0
        self.operation_count = 0
        self.lock = threading.RLock()

    def _get_memory_usage(self) -> int:
        """
        Get current memory usage.

        Uses psutil if available, otherwise returns 0.

        Returns
        -------
        int
            Memory usage in bytes, or 0 if psutil not available.
        """
        if PSUTIL_AVAILABLE:
            try:
                process = psutil.Process()
                return process.memory_info().rss
            except Exception:
                return 0
        return 0

    def check_resources(self) -> None:
        """
        Check if resource usage exceeds configured limits.

        Raises
        ------
        TimeoutError
            If execution time exceeds timeout_seconds.
        MemoryError
            If memory usage exceeds memory_limit_mb.
        ResourceWarning
            If operation count exceeds 1,000,000.
        """
        with self.lock:
            # Check time limit
            current_time = time.time()
            if self.config.timeout_seconds:
                elapsed = current_time - self.start_time
                if elapsed > self.config.timeout_seconds:
                    raise TimeoutError(f"Execution timeout after {elapsed:.2f} seconds")

            # Check memory limit
            if self.config.memory_limit_mb:
                current_memory = self._get_memory_usage()
                used_mb = (current_memory - self.start_memory) / (1024 * 1024)
                if used_mb > self.config.memory_limit_mb:
                    raise MemoryError(
                        f"Memory limit exceeded: {used_mb:.1f}MB > "
                        f"{self.config.memory_limit_mb}MB"
                    )

            # Check operation count
            self.operation_count += 1
            if self.operation_count > 1000000:
                raise ResourceWarning("Operation limit exceeded")
