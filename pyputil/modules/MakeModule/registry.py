#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Thread-safe registry for module maker.
"""

import threading
import weakref
from typing import Any, Callable


class ThreadSafeRegistry:
    """
    Thread-safe registry with observer pattern support.

    Attributes
    ----------
    _registry : Dict[str, Any]
        Internal registry storage
    _lock : threading.RLock
        Reentrant lock for thread safety
    _observers : weakref.WeakSet
        Set of observer callbacks
    """

    def __init__(self):
        """Initialize an empty thread-safe registry."""
        self._registry = {}
        self._lock = threading.RLock()
        self._observers = weakref.WeakSet()

    def register(self, key: str, value: Any) -> None:
        """
        Register a key-value pair in the registry.

        Parameters
        ----------
        key : str
            Registration key
        value : Any
            Value to register

        Notes
        -----
        Notifies all observers of the registration.
        """
        with self._lock:
            self._registry[key] = value
            self._notify_observers("register", key, value)

    def unregister(self, key: str) -> None:
        """
        Unregister a key from the registry.

        Parameters
        ----------
        key : str
            Key to unregister

        Notes
        -----
        Notifies all observers of the unregistration.
        """
        with self._lock:
            if key in self._registry:
                value = self._registry.pop(key)
                self._notify_observers("unregister", key, value)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value from the registry.

        Parameters
        ----------
        key : str
            Key to retrieve
        default : Any, default=None
            Default value if key not found

        Returns
        -------
        Any
            Retrieved value or default
        """
        with self._lock:
            return self._registry.get(key, default)

    def add_observer(self, observer: Callable) -> None:
        """
        Add an observer callback.

        Parameters
        ----------
        observer : Callable
            Callback function that takes (action, key, value) arguments
        """
        with self._lock:
            self._observers.add(observer)

    def remove_observer(self, observer: Callable) -> None:
        """
        Remove an observer callback.

        Parameters
        ----------
        observer : Callable
            Observer to remove
        """
        with self._lock:
            self._observers.discard(observer)

    def _notify_observers(self, action: str, key: str, value: Any) -> None:
        """
        Notify all observers of a registry change.

        Parameters
        ----------
        action : str
            Type of action ("register" or "unregister")
        key : str
            Key involved in the action
        value : Any
            Value involved in the action
        """
        for observer in list(self._observers):
            try:
                observer(action, key, value)
            except Exception:
                # Silently fail on observer errors
                continue

    def clear(self) -> None:
        """
        Clear all entries from the registry.
        """
        with self._lock:
            self._registry.clear()

    def keys(self):
        """
        Get all registry keys.

        Returns
        -------
        KeysView
            View of all registry keys
        """
        with self._lock:
            return self._registry.keys()

    def values(self):
        """
        Get all registry values.

        Returns
        -------
        ValuesView
            View of all registry values
        """
        with self._lock:
            return self._registry.values()

    def items(self):
        """
        Get all registry key-value pairs.

        Returns
        -------
        ItemsView
            View of all registry items
        """
        with self._lock:
            return self._registry.items()
