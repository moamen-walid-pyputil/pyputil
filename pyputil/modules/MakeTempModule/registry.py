#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Registry for tracking created modules.
"""

import threading
import time
import weakref
from typing import Any, Dict, Optional, List
from types import ModuleType
from .dataclasses import ModuleConfig


class _ModuleEntry:
    """
    Internal container for module registry entries.

    Holds module reference, configuration, creation time,
    and fingerprint for caching purposes.

    Attributes
    ----------
    module : ModuleType
        Module object.
    config : ModuleConfig
        Module configuration.
    created : float
        Creation timestamp.
    fingerprint : Optional[str]
        Source code fingerprint.
    """

    __slots__ = ("module", "config", "created", "fingerprint", "__weakref__")

    def __init__(self, module: ModuleType, config: ModuleConfig):
        """
        Initialize module entry.

        Parameters
        ----------
        module : ModuleType
            Module object.
        config : ModuleConfig
            Module configuration.
        """
        self.module = module
        self.config = config
        self.created = time.time()
        self.fingerprint = getattr(module, "__fingerprint__", None)


class _ModuleRegistry:
    """
    Registry for tracking created modules.

    Maintains weak references to module entries so they
    are automatically cleaned when no longer used.

    Attributes
    ----------
    _registry : weakref.WeakValueDictionary
        Weak reference registry.
    _lock : threading.RLock
        Lock for thread safety.

    Examples
    --------
    >>> _ModuleRegistry.register(module, config)
    >>> info = _ModuleRegistry.get_module_info("module_name")
    """

    _registry = weakref.WeakValueDictionary()
    _lock = threading.RLock()

    @classmethod
    def register(cls, module: ModuleType, config: ModuleConfig) -> None:
        """
        Register a module in the registry.

        Parameters
        ----------
        module : ModuleType
            Module to register.
        config : ModuleConfig
            Module configuration.

        Raises
        ------
        TypeError
            If module is not a ModuleType.

        Examples
        --------
        >>> _ModuleRegistry.register(module, config)
        """
        if not isinstance(module, ModuleType):
            raise TypeError("module must be a ModuleType")

        entry = _ModuleEntry(module, config)

        with cls._lock:
            cls._registry[module.__name__] = entry

    @classmethod
    def get_module_info(cls, module_name: str) -> Optional[Dict[str, Any]]:
        """
        Get module information from registry.

        Parameters
        ----------
        module_name : str
            Name of the module.

        Returns
        -------
        Optional[Dict[str, Any]]
            Module information dictionary or None if not found.
            Contains keys: 'module', 'config', 'created', 'fingerprint'.

        Examples
        --------
        >>> info = _ModuleRegistry.get_module_info("my_module")
        """
        with cls._lock:
            entry = cls._registry.get(module_name)
            if entry is None:
                return None

            return {
                "module": entry.module,
                "config": entry.config,
                "created": entry.created,
                "fingerprint": entry.fingerprint,
            }

    @classmethod
    def list_modules(cls) -> List[str]:
        """
        List all registered module names.

        Returns
        -------
        List[str]
            List of registered module names.

        Examples
        --------
        >>> modules = _ModuleRegistry.list_modules()
        ['module1', 'module2']
        """
        with cls._lock:
            return list(cls._registry.keys())

    @classmethod
    def cleanup(cls) -> None:
        """
        Force cleanup of dead references.

        WeakValueDictionary cleans itself automatically,
        but this method can be called to force cleanup.

        Examples
        --------
        >>> _ModuleRegistry.cleanup()
        """
        with cls._lock:
            # Accessing items triggers cleanup of dead references
            _ = list(cls._registry.items())
