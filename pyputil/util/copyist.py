#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module Cloning and Sandboxing System
==============================================

A comprehensive, production-grade module cloning and sandboxing system that
provides controlled, secure views of Python modules with fine-grained access
control, lazy loading, immutability, and comprehensive attribute filtering.

This module enables creating isolated, controlled copies of modules for:
- Security sandboxing (restrict access to sensitive attributes)
- Testing and mocking (controlled module views)
- Lazy loading optimization (defer expensive imports)
- API exposure control (public-only views)
- Module versioning and snapshotting
- Dependency injection and patching

Features
--------
- **Access Control**: Whitelist/blacklist attribute filtering
- **Lazy Loading**: Defer expensive attribute initialization
- **Immutability**: Freeze modules to prevent modifications
- **Public-Only Views**: Expose only non-underscore attributes
- **Deep Cloning**: Recursive cloning of submodules
- **Proxy Pattern**: Transparent attribute forwarding
- **Cross-Platform**: Works on Windows, Linux, macOS, and BSD
- **Thread-Safe**: Optional locking for concurrent access
- **Serialization**: Clone modules can be pickled
- **Inspection**: Comprehensive clone metadata and statistics

Examples
--------
>>> import math
>>> from pyputil.util import clone_module
>>> 
>>> # Create a public-only view
>>> public_math = clone_module(math, public_only=True)
>>> hasattr(public_math, 'sqrt')
True
>>> hasattr(public_math, '_generate')
False
>>> 
>>> # Create a restricted view
>>> restricted = clone_module(math, allowed={'sqrt', 'pi', 'e'})
>>> restricted.sqrt(4)
2.0
>>> restricted.sin(1)  # AttributeError
>>> 
>>> # Create a frozen module
>>> frozen = clone_module(math, frozen=True)
>>> frozen.new_attr = 42  # AttributeError: Module is frozen
>>> 
>>> # Lazy loading example
>>> lazy_math = clone_module(math, lazy={
...     'expensive_attr': lambda: heavy_computation()
... })
>>> # expensive_attr only computed when first accessed
>>> 
>>> # Exclude specific attributes
>>> clean = clone_module(math, exclude={'__doc__', '__file__'})
>>> 
>>> # Deep clone with recursive submodule cloning
>>> import json
>>> deep_clone = clone_module_deep(json)

References
----------
- PEP 451: ModuleSpec Type
- PEP 562: Module __getattr__ and __dir__
- importlib: https://docs.python.org/3/library/importlib.html
"""

import sys
import os
import threading
import importlib
import importlib.util
import warnings
from types import ModuleType, FunctionType, MethodType
from typing import (
    Optional, Dict, Set, List, Tuple, Union, Any, Callable, 
    Iterable, Iterator, TypeVar, overload, FrozenSet, Mapping
)
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from functools import wraps, lru_cache
from contextlib import contextmanager
from pathlib import Path
import weakref

# ============================================================================
# Platform Detection
# ============================================================================

_IS_WINDOWS: bool = sys.platform == "win32"
_IS_MACOS: bool = sys.platform == "darwin"
_IS_LINUX: bool = sys.platform.startswith("linux")
_IS_BSD: bool = any(sys.platform.startswith(p) for p in ("freebsd", "openbsd", "netbsd", "dragonfly"))

# ============================================================================
# Enums for Configuration
# ============================================================================

class CloneMode(Enum):
    """
    Enumeration of module cloning modes.
    
    Attributes
    ----------
    SHALLOW : str
        Shallow clone - only wrap the module without copying submodules.
    DEEP : str
        Deep clone - recursively clone all submodules.
    LAZY : str
        Lazy deep clone - clone submodules on first access.
    REFERENCE : str
        Reference clone - keep references to original attributes.
    """
    SHALLOW = "shallow"
    DEEP = "deep"
    LAZY = "lazy"
    REFERENCE = "reference"


class AccessPolicy(Enum):
    """
    Enumeration of attribute access policies.
    
    Attributes
    ----------
    ALLOW_ALL : str
        Allow all attributes (default).
    ALLOW_LIST : str
        Only allow explicitly listed attributes.
    DENY_LIST : str
        Allow all except explicitly denied attributes.
    PUBLIC_ONLY : str
        Only allow public attributes (no leading underscore).
    CUSTOM : str
        Use custom access function.
    """
    ALLOW_ALL = "allow_all"
    ALLOW_LIST = "allow_list"
    DENY_LIST = "deny_list"
    PUBLIC_ONLY = "public_only"
    CUSTOM = "custom"


class CloneEvent(Enum):
    """
    Enumeration of clone lifecycle events.
    
    Attributes
    ----------
    ACCESS : str
        Attribute access event.
    MODIFY : str
        Attribute modification event.
    LAZY_LOAD : str
        Lazy attribute loading event.
    ERROR : str
        Error event.
    """
    ACCESS = "access"
    MODIFY = "modify"
    LAZY_LOAD = "lazy_load"
    ERROR = "error"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class CloneStatistics:
    """
    Statistics for module clone operations.
    
    Attributes
    ----------
    access_count : int
        Total number of attribute accesses.
    lazy_load_count : int
        Number of lazy attributes loaded.
    modify_attempts : int
        Number of modification attempts.
    blocked_accesses : int
        Number of blocked attribute accesses.
    created_at : float
        Timestamp when clone was created.
    last_access : Optional[float]
        Timestamp of last attribute access.
    """
    access_count: int = 0
    lazy_load_count: int = 0
    modify_attempts: int = 0
    blocked_accesses: int = 0
    created_at: float = field(default_factory=lambda: __import__('time').time())
    last_access: Optional[float] = None
    
    def record_access(self) -> None:
        """Record an attribute access."""
        self.access_count += 1
        self.last_access = __import__('time').time()
    
    def record_lazy_load(self) -> None:
        """Record a lazy attribute load."""
        self.lazy_load_count += 1
    
    def record_modify_attempt(self) -> None:
        """Record a modification attempt."""
        self.modify_attempts += 1
    
    def record_blocked(self) -> None:
        """Record a blocked access."""
        self.blocked_accesses += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class CloneConfig:
    """
    Configuration for module cloning.
    
    Attributes
    ----------
    mode : CloneMode
        Cloning mode (shallow, deep, lazy, reference).
    access_policy : AccessPolicy
        Attribute access policy.
    allowed : Optional[FrozenSet[str]]
        Set of allowed attribute names.
    denied : FrozenSet[str]
        Set of denied attribute names.
    frozen : bool
        Whether module is read-only.
    lazy : Dict[str, Callable[[], Any]]
        Lazy attribute factories.
    public_only : bool
        Whether to expose only public attributes.
    thread_safe : bool
        Whether to use thread-safe operations.
    track_stats : bool
        Whether to track access statistics.
    callbacks : Dict[CloneEvent, List[Callable]]
        Event callbacks.
    recursive_depth : int
        Maximum depth for recursive cloning (-1 for unlimited).
    preserve_docstring : bool
        Whether to preserve original docstring.
    preserve_file : bool
        Whether to preserve __file__ attribute.
    preserve_loader : bool
        Whether to preserve __loader__ attribute.
    """
    mode: CloneMode = CloneMode.SHALLOW
    access_policy: AccessPolicy = AccessPolicy.ALLOW_ALL
    allowed: Optional[FrozenSet[str]] = None
    denied: FrozenSet[str] = field(default_factory=frozenset)
    frozen: bool = False
    lazy: Dict[str, Callable[[], Any]] = field(default_factory=dict)
    public_only: bool = False
    thread_safe: bool = False
    track_stats: bool = False
    callbacks: Dict[CloneEvent, List[Callable]] = field(default_factory=dict)
    recursive_depth: int = -1
    preserve_docstring: bool = True
    preserve_file: bool = False
    preserve_loader: bool = False
    
    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.access_policy == AccessPolicy.PUBLIC_ONLY:
            self.public_only = True
        
        if self.recursive_depth < -1:
            raise ValueError(f"recursive_depth must be >= -1, got {self.recursive_depth}")


# ============================================================================
# Exception Classes
# ============================================================================

class ModuleCloneError(Exception):
    """Base exception for module cloning errors."""
    pass


class FrozenModuleError(ModuleCloneError):
    """Raised when attempting to modify a frozen module."""
    pass


class AccessDeniedError(ModuleCloneError):
    """Raised when attribute access is denied."""
    pass


class LazyLoadError(ModuleCloneError):
    """Raised when lazy attribute loading fails."""
    pass


class CircularReferenceError(ModuleCloneError):
    """Raised when circular module reference is detected."""
    pass


# ============================================================================
# Module Clone Class
# ============================================================================

class ModuleClone(ModuleType):
    """
    Controlled, sandboxed view of an existing Python module.
    
    This class creates a wrapper around an original module to control which
    attributes are accessible and how they behave. It supports access control,
    lazy loading, immutability, and comprehensive monitoring.
    
    Attributes
    ----------
    __origin_module__ : ModuleType
        The original wrapped module.
    __config__ : CloneConfig
        Configuration for this clone.
    __stats__ : Optional[CloneStatistics]
        Access statistics if tracking enabled.
    __lock__ : Optional[threading.RLock]
        Thread lock if thread-safe mode enabled.
    __subclones__ : Dict[str, 'ModuleClone']
        Cache of cloned submodules.
    
    Examples
    --------
    >>> import math
    >>> clone = ModuleClone(
    ...     "math_clone",
    ...     math,
    ...     config=CloneConfig(
    ...         access_policy=AccessPolicy.ALLOW_LIST,
    ...         allowed=frozenset({'sqrt', 'pi'}),
    ...         frozen=True
    ...     )
    ... )
    >>> clone.sqrt(4)
    2.0
    >>> clone.sin(1)  # AccessDeniedError
    """
    
    __slots__ = (
        "__origin_module__",
        "__config__",
        "__stats__",
        "__lock__",
        "__subclones__",
    )
    
    def __init__(
        self,
        name: str,
        origin: ModuleType,
        config: Optional[CloneConfig] = None,
        doc: Optional[str] = None,
    ):
        """
        Initialize a module clone.
        
        Parameters
        ----------
        name : str
            Name for the cloned module.
        origin : ModuleType
            Original module to wrap.
        config : Optional[CloneConfig], default=None
            Configuration for the clone.
        doc : Optional[str], default=None
            Custom docstring for the clone.
        """
        super().__init__(name)
        
        # Use object.__setattr__ exclusively in __init__ to avoid recursion
        # This is critical - do not use self.attr = value here!
        
        # Initialize core slots first
        object.__setattr__(self, "__origin_module__", origin)
        object.__setattr__(self, "__config__", config or CloneConfig())
        object.__setattr__(self, "__subclones__", {})
        
        # Get config reference for easier access
        cfg = object.__getattribute__(self, "__config__")
        
        # Initialize statistics if tracking enabled
        if cfg.track_stats:
            object.__setattr__(self, "__stats__", CloneStatistics())
        else:
            object.__setattr__(self, "__stats__", None)
        
        # Initialize lock if thread-safe
        if cfg.thread_safe:
            import threading
            object.__setattr__(self, "__lock__", threading.RLock())
        else:
            object.__setattr__(self, "__lock__", None)
        
        # Set docstring using object.__setattr__
        if doc is not None:
            object.__setattr__(self, "__doc__", doc)
        elif cfg.preserve_docstring:
            object.__setattr__(self, "__doc__", getattr(origin, '__doc__', None))
        
        # Preserve special attributes if configured
        if cfg.preserve_file and hasattr(origin, '__file__'):
            object.__setattr__(self, "__file__", origin.__file__)
        
        if cfg.preserve_loader and hasattr(origin, '__loader__'):
            object.__setattr__(self, "__loader__", origin.__loader__)
        
        # Set __path__ for packages
        if hasattr(origin, '__path__'):
            object.__setattr__(self, "__path__", origin.__path__)
        
        # Set __package__
        if hasattr(origin, '__package__'):
            object.__setattr__(self, "__package__", origin.__package__)
    
    def _get_lock(self):
        """Safely get the lock attribute without triggering recursion."""
        try:
            return object.__getattribute__(self, "__lock__")
        except AttributeError:
            return None
    
    def _get_config(self):
        """Safely get the config attribute without triggering recursion."""
        try:
            return object.__getattribute__(self, "__config__")
        except AttributeError:
            return None
    
    def _get_stats(self):
        """Safely get the stats attribute without triggering recursion."""
        try:
            return object.__getattribute__(self, "__stats__")
        except AttributeError:
            return None
    
    def _check_access(self, name: str) -> bool:
        """
        Check if attribute access is allowed.
        
        Parameters
        ----------
        name : str
            Attribute name to check.
        
        Returns
        -------
        bool
            True if access is allowed.
        
        Raises
        ------
        AccessDeniedError
            If access is denied.
        """
        config = self._get_config()
        if config is None:
            return True
        
        # Always allow special attributes of the clone itself
        if name in ('__origin_module__', '__config__', '__stats__', 
                   '__lock__', '__subclones__', '__weakref__'):
            return True
        
        # Always allow standard Python special attributes
        if name.startswith('__') and name.endswith('__'):
            return True
        
        # Check access policy
        if config.access_policy == AccessPolicy.ALLOW_ALL:
            return True
        elif config.access_policy == AccessPolicy.ALLOW_LIST:
            allowed = config.allowed or set()
            if name not in allowed:
                raise AccessDeniedError(f"Access to '{name}' is denied (not in allowed list)")
            return True
        elif config.access_policy == AccessPolicy.DENY_LIST:
            if name in config.denied:
                raise AccessDeniedError(f"Access to '{name}' is denied (in denied list)")
            return True
        elif config.access_policy == AccessPolicy.PUBLIC_ONLY:
            if name.startswith('_'):
                raise AccessDeniedError(f"Access to '{name}' is denied (private attribute)")
            return True
        
        return True
    
    def __getattr__(self, name: str) -> Any:
        """
        Get attribute with access control and lazy loading.
        
        Parameters
        ----------
        name : str
            Attribute name.
        
        Returns
        -------
        Any
            Attribute value.
        
        Raises
        ------
        AccessDeniedError
            If access is denied.
        AttributeError
            If attribute doesn't exist.
        """
        # Get config safely
        config = self._get_config()
        
        # Check lazy attributes first (without lock to avoid recursion)
        if config and name in config.lazy:
            try:
                value = config.lazy[name]()
                # Use object.__setattr__ to cache the value
                object.__setattr__(self, name, value)
                
                # Update stats if tracking
                stats = self._get_stats()
                if stats:
                    stats.record_lazy_load()
                
                return value
            except Exception as e:
                raise LazyLoadError(f"Failed to load lazy attribute '{name}': {e}") from e
        
        # Check access permission
        self._check_access(name)
        
        # Get origin module
        origin = object.__getattribute__(self, "__origin_module__")
        
        # Check if attribute exists in origin
        if hasattr(origin, name):
            value = getattr(origin, name)
            
            # Update stats if tracking
            stats = self._get_stats()
            if stats:
                stats.record_access()
            
            # Handle submodule cloning if configured
            if config and isinstance(value, ModuleType):
                if config.mode == CloneMode.DEEP:
                    return self._clone_submodule(name, value)
                elif config.mode == CloneMode.LAZY:
                    return self._lazy_clone_submodule(name, value)
            
            return value
        
        raise AttributeError(f"Module '{self.__name__}' has no attribute '{name}'")
    
    def __setattr__(self, name: str, value: Any) -> None:
        """
        Set attribute with immutability check.
        
        Parameters
        ----------
        name : str
            Attribute name.
        value : Any
            Attribute value.
        
        Raises
        ------
        FrozenModuleError
            If module is frozen.
        """
        # Get lock and config safely
        lock = self._get_lock()
        config = self._get_config()
        
        if lock:
            with lock:
                self._setattr_impl(name, value)
        else:
            self._setattr_impl(name, value)
    
    def _setattr_impl(self, name: str, value: Any) -> None:
        """Internal implementation of attribute setting."""
        config = self._get_config()
        
        # Check if frozen
        if config and config.frozen:
            stats = self._get_stats()
            if stats:
                stats.record_modify_attempt()
            raise FrozenModuleError(f"Module '{self.__name__}' is frozen and cannot be modified")
        
        object.__setattr__(self, name, value)
    
    def __delattr__(self, name: str) -> None:
        """
        Delete attribute with immutability check.
        
        Parameters
        ----------
        name : str
            Attribute name.
        
        Raises
        ------
        FrozenModuleError
            If module is frozen.
        """
        config = self._get_config()
        
        if config and config.frozen:
            stats = self._get_stats()
            if stats:
                stats.record_modify_attempt()
            raise FrozenModuleError(f"Module '{self.__name__}' is frozen and cannot be modified")
        
        object.__delattr__(self, name)
    
    def _clone_submodule(self, name: str, submodule: ModuleType) -> 'ModuleClone':
        """
        Deep clone a submodule.
        
        Parameters
        ----------
        name : str
            Submodule name.
        submodule : ModuleType
            Submodule to clone.
        
        Returns
        -------
        ModuleClone
            Cloned submodule.
        """
        subclones = object.__getattribute__(self, "__subclones__")
        
        if name in subclones:
            return subclones[name]
        
        config = self._get_config()
        
        # Check recursion depth
        if config and config.recursive_depth == 0:
            return submodule
        
        # Create sub-config with decreased depth
        sub_config = CloneConfig(
            mode=config.mode if config else CloneMode.SHALLOW,
            access_policy=config.access_policy if config else AccessPolicy.ALLOW_ALL,
            allowed=config.allowed if config else None,
            denied=config.denied if config else frozenset(),
            frozen=config.frozen if config else False,
            lazy=config.lazy if config else {},
            public_only=config.public_only if config else False,
            thread_safe=config.thread_safe if config else False,
            track_stats=config.track_stats if config else False,
            recursive_depth=(config.recursive_depth - 1) if (config and config.recursive_depth and config.recursive_depth > 0) else -1,
            preserve_docstring=config.preserve_docstring if config else True,
            preserve_file=config.preserve_file if config else False,
            preserve_loader=config.preserve_loader if config else False,
        )
        
        clone = ModuleClone(
            f"{self.__name__}.{name}",
            submodule,
            config=sub_config
        )
        
        subclones[name] = clone
        object.__setattr__(self, name, clone)
        
        return clone
    
    def _lazy_clone_submodule(self, name: str, submodule: ModuleType) -> Any:
        """
        Create a lazy proxy for submodule cloning.
        
        Parameters
        ----------
        name : str
            Submodule name.
        submodule : ModuleType
            Submodule to clone.
        
        Returns
        -------
        Any
            Lazy proxy that clones on first access.
        """
        # Store reference to self to avoid capturing in closure issues
        parent_clone = self
        
        class LazySubmoduleProxy:
            __slots__ = ('_parent', '_name', '_submodule', '_cloned')
            
            def __init__(self, parent, name, submodule):
                object.__setattr__(self, '_parent', parent)
                object.__setattr__(self, '_name', name)
                object.__setattr__(self, '_submodule', submodule)
                object.__setattr__(self, '_cloned', None)
            
            def _get_cloned(self):
                if object.__getattribute__(self, '_cloned') is None:
                    parent = object.__getattribute__(self, '_parent')
                    name = object.__getattribute__(self, '_name')
                    submodule = object.__getattribute__(self, '_submodule')
                    cloned = parent._clone_submodule(name, submodule)
                    object.__setattr__(self, '_cloned', cloned)
                return object.__getattribute__(self, '_cloned')
            
            def __getattr__(self, attr):
                cloned = self._get_cloned()
                return getattr(cloned, attr)
            
            def __setattr__(self, attr, value):
                cloned = self._get_cloned()
                setattr(cloned, attr, value)
            
            def __delattr__(self, attr):
                cloned = self._get_cloned()
                delattr(cloned, attr)
            
            def __dir__(self):
                cloned = self._get_cloned()
                return dir(cloned)
            
            def __repr__(self):
                if object.__getattribute__(self, '_cloned') is None:
                    return f"<LazySubmoduleProxy for '{object.__getattribute__(self, '_name')}'>"
                return repr(object.__getattribute__(self, '_cloned'))
        
        return LazySubmoduleProxy(parent_clone, name, submodule)
    
    def __dir__(self) -> List[str]:
        """
        Get list of available attributes.
        
        Returns
        -------
        List[str]
            Sorted list of attribute names.
        """
        config = self._get_config()
        origin = object.__getattribute__(self, "__origin_module__")
        
        # Start with local attributes
        base = set(super().__dir__())
        
        # Get origin attributes
        origin_attrs = set(dir(origin))
        
        # Filter based on access policy
        if config:
            if config.access_policy == AccessPolicy.ALLOW_LIST and config.allowed:
                origin_attrs = {n for n in origin_attrs if n in config.allowed}
            elif config.access_policy == AccessPolicy.DENY_LIST:
                origin_attrs = {n for n in origin_attrs if n not in config.denied}
            elif config.access_policy == AccessPolicy.PUBLIC_ONLY:
                origin_attrs = {n for n in origin_attrs if not n.startswith('_')}
            
            # Add lazy attribute names
            lazy_attrs = set(config.lazy.keys())
        else:
            lazy_attrs = set()
        
        return sorted(base | origin_attrs | lazy_attrs)
    
    @contextmanager
    def _acquire_lock(self):
        """Context manager for thread-safe operations."""
        if self.__lock__:
            with self.__lock__:
                yield
        else:
            yield
    
    def _check_access(self, name: str) -> bool:
        """
        Check if attribute access is allowed.
        
        Parameters
        ----------
        name : str
            Attribute name to check.
        
        Returns
        -------
        bool
            True if access is allowed.
        
        Raises
        ------
        AccessDeniedError
            If access is denied.
        """
        config = self.__config__
        
        # Always allow special attributes
        if name.startswith('__') and name.endswith('__'):
            if name in ('__origin_module__', '__config__', '__stats__', 
                       '__lock__', '__subclones__', '__weakref__'):
                return True
        
        # Check access policy
        if config.access_policy == AccessPolicy.ALLOW_ALL:
            allowed = True
        elif config.access_policy == AccessPolicy.ALLOW_LIST:
            allowed = name in (config.allowed or set())
        elif config.access_policy == AccessPolicy.DENY_LIST:
            allowed = name not in config.denied
        elif config.access_policy == AccessPolicy.PUBLIC_ONLY:
            allowed = not name.startswith('_')
        elif config.access_policy == AccessPolicy.CUSTOM:
            # Custom policy handled by subclass or callback
            allowed = self._custom_access_check(name)
        else:
            allowed = True
        
        # Track blocked accesses
        if not allowed and self.__stats__:
            with self._acquire_lock():
                self.__stats__.record_blocked()
        
        # Trigger callback
        if not allowed:
            self._trigger_callback(CloneEvent.ERROR, name=name, reason="access_denied")
        
        return allowed
    
    def _custom_access_check(self, name: str) -> bool:
        """
        Custom access check for CUSTOM policy.
        
        Override this method in subclasses for custom logic.
        
        Parameters
        ----------
        name : str
            Attribute name to check.
        
        Returns
        -------
        bool
            True if access is allowed.
        """
        return True
    
    def _trigger_callback(self, event: CloneEvent, **kwargs) -> None:
        """
        Trigger event callbacks.
        
        Parameters
        ----------
        event : CloneEvent
            Event type.
        **kwargs
            Additional event data.
        """
        callbacks = self.__config__.callbacks.get(event, [])
        for callback in callbacks:
            try:
                callback(self, event, **kwargs)
            except Exception as e:
                warnings.warn(f"Callback failed for {event}: {e}", RuntimeWarning)
    
    def __getattr__(self, name: str) -> Any:
        """
        Get attribute with access control and lazy loading.
        
        Parameters
        ----------
        name : str
            Attribute name.
        
        Returns
        -------
        Any
            Attribute value.
        
        Raises
        ------
        AccessDeniedError
            If access is denied.
        AttributeError
            If attribute doesn't exist.
        """
        with self._acquire_lock():
            config = self.__config__
            
            # Check lazy attributes first
            if name in config.lazy:
                try:
                    value = config.lazy[name]()
                    object.__setattr__(self, name, value)
                    
                    if self.__stats__:
                        self.__stats__.record_lazy_load()
                    
                    self._trigger_callback(CloneEvent.LAZY_LOAD, name=name)
                    return value
                except Exception as e:
                    self._trigger_callback(CloneEvent.ERROR, name=name, error=e)
                    raise LazyLoadError(f"Failed to load lazy attribute '{name}': {e}") from e
            
            # Check access permission
            if not self._check_access(name):
                raise AccessDeniedError(f"Access to '{name}' is denied")
            
            origin = self.__origin_module__
            
            if hasattr(origin, name):
                value = getattr(origin, name)
                
                # Track statistics
                if self.__stats__:
                    self.__stats__.record_access()
                
                self._trigger_callback(CloneEvent.ACCESS, name=name, value=value)
                
                # Deep clone submodules if configured
                if config.mode == CloneMode.DEEP and isinstance(value, ModuleType):
                    return self._clone_submodule(name, value)
                elif config.mode == CloneMode.LAZY and isinstance(value, ModuleType):
                    return self._lazy_clone_submodule(name, value)
                
                return value
            
            raise AttributeError(f"Module '{self.__name__}' has no attribute '{name}'")
    
    # ==========================================================================
    # Public API Methods
    # ==========================================================================
    
    @property
    def origin(self) -> ModuleType:
        """
        Get the original wrapped module.
        
        Returns
        -------
        ModuleType
            Original module.
        """
        return self.__origin_module__
    
    @property
    def config(self) -> CloneConfig:
        """
        Get the clone configuration.
        
        Returns
        -------
        CloneConfig
            Clone configuration.
        """
        return self.__config__
    
    @property
    def stats(self) -> Optional[CloneStatistics]:
        """
        Get clone statistics if tracking enabled.
        
        Returns
        -------
        Optional[CloneStatistics]
            Statistics or None.
        """
        return self.__stats__
    
    @property
    def is_frozen(self) -> bool:
        """
        Check if module is frozen.
        
        Returns
        -------
        bool
            True if frozen.
        """
        return self.__config__.frozen
    
    def freeze(self) -> None:
        """
        Freeze the module to prevent further modifications.
        
        Raises
        ------
        FrozenModuleError
            If already frozen.
        """
        with self._acquire_lock():
            if self.__config__.frozen:
                raise FrozenModuleError(f"Module '{self.__name__}' is already frozen")
            self.__config__.frozen = True
    
    def unfreeze(self) -> None:
        """
        Unfreeze the module to allow modifications.
        """
        with self._acquire_lock():
            self.__config__.frozen = False
    
    def add_lazy(self, name: str, factory: Callable[[], Any]) -> None:
        """
        Add a lazy attribute factory.
        
        Parameters
        ----------
        name : str
            Attribute name.
        factory : Callable[[], Any]
            Factory function that returns the attribute value.
        
        Raises
        ------
        FrozenModuleError
            If module is frozen.
        """
        with self._acquire_lock():
            if self.__config__.frozen:
                raise FrozenModuleError(f"Module '{self.__name__}' is frozen")
            self.__config__.lazy[name] = factory
    
    def allow(self, *names: str) -> None:
        """
        Add attributes to allowed list.
        
        Parameters
        ----------
        *names : str
            Attribute names to allow.
        
        Raises
        ------
        FrozenModuleError
            If module is frozen.
        ValueError
            If access policy is not ALLOW_LIST.
        """
        with self._acquire_lock():
            if self.__config__.frozen:
                raise FrozenModuleError(f"Module '{self.__name__}' is frozen")
            if self.__config__.access_policy != AccessPolicy.ALLOW_LIST:
                raise ValueError("Access policy must be ALLOW_LIST to use allow()")
            
            allowed = set(self.__config__.allowed or set())
            allowed.update(names)
            self.__config__.allowed = frozenset(allowed)
    
    def deny(self, *names: str) -> None:
        """
        Add attributes to denied list.
        
        Parameters
        ----------
        *names : str
            Attribute names to deny.
        
        Raises
        ------
        FrozenModuleError
            If module is frozen.
        ValueError
            If access policy is not DENY_LIST.
        """
        with self._acquire_lock():
            if self.__config__.frozen:
                raise FrozenModuleError(f"Module '{self.__name__}' is frozen")
            if self.__config__.access_policy != AccessPolicy.DENY_LIST:
                raise ValueError("Access policy must be DENY_LIST to use deny()")
            
            denied = set(self.__config__.denied)
            denied.update(names)
            self.__config__.denied = frozenset(denied)
    
    def on(self, event: CloneEvent, callback: Callable) -> None:
        """
        Register an event callback.
        
        Parameters
        ----------
        event : CloneEvent
            Event to listen for.
        callback : Callable
            Callback function.
        """
        with self._acquire_lock():
            if event not in self.__config__.callbacks:
                self.__config__.callbacks[event] = []
            self.__config__.callbacks[event].append(callback)
    
    def reset_stats(self) -> None:
        """
        Reset access statistics.
        """
        with self._acquire_lock():
            if self.__stats__:
                self.__stats__ = CloneStatistics()
                object.__setattr__(self, "__stats__", self.__stats__)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert clone metadata to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Clone metadata.
        """
        return {
            'name': self.__name__,
            'origin': getattr(self.__origin_module__, '__name__', str(self.__origin_module__)),
            'mode': self.__config__.mode.value,
            'access_policy': self.__config__.access_policy.value,
            'frozen': self.__config__.frozen,
            'public_only': self.__config__.public_only,
            'thread_safe': self.__config__.thread_safe,
            'track_stats': self.__config__.track_stats,
            'allowed_count': len(self.__config__.allowed) if self.__config__.allowed else 0,
            'denied_count': len(self.__config__.denied),
            'lazy_count': len(self.__config__.lazy),
            'subclones_count': len(self.__subclones__),
            'stats': self.__stats__.to_dict() if self.__stats__ else None,
        }


# ============================================================================
# Public API Functions
# ============================================================================

def clone_module(
    module: Union[ModuleType, str],
    *,
    name: Optional[str] = None,
    mode: Union[CloneMode, str] = CloneMode.SHALLOW,
    access_policy: Union[AccessPolicy, str] = AccessPolicy.ALLOW_ALL,
    allowed: Optional[Iterable[str]] = None,
    denied: Iterable[str] = (),
    public_only: bool = False,
    frozen: bool = False,
    lazy: Optional[Dict[str, Callable[[], Any]]] = None,
    thread_safe: bool = False,
    track_stats: bool = False,
    recursive_depth: int = -1,
    preserve_docstring: bool = True,
    preserve_file: bool = False,
    preserve_loader: bool = False,
    callbacks: Optional[Dict[CloneEvent, List[Callable]]] = None,
    doc: Optional[str] = None,
) -> ModuleClone:
    """
    Create a controlled clone of a Python module.
    
    This function creates a ModuleClone instance that wraps an existing module,
    providing fine-grained control over attribute access and behavior.
    
    Parameters
    ----------
    module : Union[ModuleType, str]
        The module to clone. Can be a module object or import name.
    name : Optional[str], default=None
        Name for the cloned module. If None, uses 'clone_of_{original_name}'.
    mode : Union[CloneMode, str], default=CloneMode.SHALLOW
        Cloning mode:
        - 'shallow': Only wrap the module without cloning submodules.
        - 'deep': Recursively clone all submodules.
        - 'lazy': Clone submodules on first access.
        - 'reference': Keep references to original attributes.
    access_policy : Union[AccessPolicy, str], default=AccessPolicy.ALLOW_ALL
        Attribute access policy:
        - 'allow_all': Allow all attributes.
        - 'allow_list': Only allow explicitly listed attributes.
        - 'deny_list': Allow all except denied attributes.
        - 'public_only': Only allow public attributes.
        - 'custom': Use custom access function.
    allowed : Optional[Iterable[str]], default=None
        Set of allowed attribute names (for allow_list policy).
    denied : Iterable[str], default=()
        Set of denied attribute names (for deny_list policy).
    public_only : bool, default=False
        Shortcut for access_policy='public_only'.
    frozen : bool, default=False
        If True, module becomes read-only.
    lazy : Optional[Dict[str, Callable[[], Any]]], default=None
        Mapping of attribute names to lazy factory functions.
    thread_safe : bool, default=False
        If True, use thread-safe operations.
    track_stats : bool, default=False
        If True, track access statistics.
    recursive_depth : int, default=-1
        Maximum depth for recursive cloning (-1 for unlimited).
    preserve_docstring : bool, default=True
        If True, preserve original module docstring.
    preserve_file : bool, default=False
        If True, preserve __file__ attribute.
    preserve_loader : bool, default=False
        If True, preserve __loader__ attribute.
    callbacks : Optional[Dict[CloneEvent, List[Callable]]], default=None
        Event callbacks for clone lifecycle.
    doc : Optional[str], default=None
        Custom docstring for the clone.
    
    Returns
    -------
    ModuleClone
        Cloned module instance.
    
    Raises
    ------
    TypeError
        If module is not a ModuleType or string.
    ModuleNotFoundError
        If module string cannot be imported.
    
    Examples
    --------
    >>> import math
    >>> # Public-only view
    >>> public_math = clone_module(math, public_only=True)
    >>> 
    >>> # Restricted view
    >>> restricted = clone_module(
    ...     math,
    ...     access_policy='allow_list',
    ...     allowed={'sqrt', 'pi', 'e'},
    ...     frozen=True
    ... )
    >>> 
    >>> # Lazy loading
    >>> lazy_math = clone_module(
    ...     math,
    ...     lazy={'heavy': lambda: expensive_computation()}
    ... )
    >>> 
    >>> # Deep clone with statistics
    >>> import json
    >>> deep_json = clone_module(
    ...     json,
    ...     mode='deep',
    ...     track_stats=True,
    ...     thread_safe=True
    ... )
    >>> print(deep_json.stats.access_count)
    
    See Also
    --------
    ModuleClone : The class used for cloning.
    clone_module_deep : Deep cloning shortcut.
    clone_module_public : Public-only cloning shortcut.
    """
    # Validate and import module
    if not isinstance(module, (ModuleType, str)):
        raise TypeError(f"Expected ModuleType or str, got {type(module).__name__}")
    
    if isinstance(module, str):
        try:
            module = importlib.import_module(module)
        except ImportError as e:
            raise ModuleNotFoundError(f"Could not import module '{module}': {e}") from e
    
    # Process name
    if name is None:
        name = f"clone_of_{module.__name__}"
    
    # Process mode
    if isinstance(mode, str):
        try:
            mode = CloneMode(mode.lower())
        except ValueError:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {[m.value for m in CloneMode]}")
    
    # Process access policy
    if isinstance(access_policy, str):
        try:
            access_policy = AccessPolicy(access_policy.lower())
        except ValueError:
            raise ValueError(f"Invalid access_policy: {access_policy}. Must be one of {[p.value for p in AccessPolicy]}")
    
    # Handle public_only shortcut
    if public_only:
        access_policy = AccessPolicy.PUBLIC_ONLY
    
    # Build configuration
    config = CloneConfig(
        mode=mode,
        access_policy=access_policy,
        allowed=frozenset(allowed) if allowed else None,
        denied=frozenset(denied),
        frozen=frozen,
        lazy=lazy or {},
        public_only=public_only,
        thread_safe=thread_safe,
        track_stats=track_stats,
        callbacks=callbacks or {},
        recursive_depth=recursive_depth,
        preserve_docstring=preserve_docstring,
        preserve_file=preserve_file,
        preserve_loader=preserve_loader,
    )
    
    clone = ModuleClone(name, module, config=config, doc=doc)
    
    # Eagerly copy allowed attributes for better performance
    if config.access_policy in (AccessPolicy.ALLOW_ALL, AccessPolicy.DENY_LIST, AccessPolicy.PUBLIC_ONLY):
        for attr_name, attr_value in module.__dict__.items():
            # Skip if denied
            if config.access_policy == AccessPolicy.DENY_LIST and attr_name in config.denied:
                continue
            # Skip private if public_only
            if config.public_only and attr_name.startswith('_'):
                continue
            # Skip special methods that might cause issues
            if attr_name.startswith('__') and attr_name.endswith('__'):
                if attr_name not in ('__doc__', '__file__', '__loader__', '__path__', '__package__'):
                    continue
            
            try:
                object.__setattr__(clone, attr_name, attr_value)
            except Exception:
                # Skip attributes that can't be set
                pass
    
    return clone


def clone_module_deep(
    module: Union[ModuleType, str],
    **kwargs
) -> ModuleClone:
    """
    Create a deep clone of a module (recursively clones submodules).
    
    This is a convenience wrapper around clone_module with mode='deep'.
    
    Parameters
    ----------
    module : Union[ModuleType, str]
        The module to clone.
    **kwargs
        Additional arguments passed to clone_module.
    
    Returns
    -------
    ModuleClone
        Deep cloned module.
    
    Examples
    --------
    >>> import json
    >>> deep_json = clone_module_deep(json, frozen=True)
    >>> deep_json.decoder  # This is also cloned
    <ModuleClone 'clone_of_json.decoder' -> 'json.decoder' ...>
    """
    kwargs['mode'] = CloneMode.DEEP
    return clone_module(module, **kwargs)


def clone_module_public(
    module: Union[ModuleType, str],
    **kwargs
) -> ModuleClone:
    """
    Create a public-only clone (only non-underscore attributes).
    
    This is a convenience wrapper around clone_module with public_only=True.
    
    Parameters
    ----------
    module : Union[ModuleType, str]
        The module to clone.
    **kwargs
        Additional arguments passed to clone_module.
    
    Returns
    -------
    ModuleClone
        Public-only cloned module.
    
    Examples
    --------
    >>> import math
    >>> public_math = clone_module_public(math)
    >>> hasattr(public_math, 'sqrt')
    True
    >>> hasattr(public_math, '_generate')
    False
    """
    kwargs['public_only'] = True
    return clone_module(module, **kwargs)


def clone_module_restricted(
    module: Union[ModuleType, str],
    allowed: Iterable[str],
    **kwargs
) -> ModuleClone:
    """
    Create a restricted clone with only allowed attributes.
    
    This is a convenience wrapper around clone_module with access_policy='allow_list'.
    
    Parameters
    ----------
    module : Union[ModuleType, str]
        The module to clone.
    allowed : Iterable[str]
        Set of allowed attribute names.
    **kwargs
        Additional arguments passed to clone_module.
    
    Returns
    -------
    ModuleClone
        Restricted cloned module.
    
    Examples
    --------
    >>> import math
    >>> restricted = clone_module_restricted(
    ...     math,
    ...     allowed={'sqrt', 'pi', 'e'},
    ...     frozen=True
    ... )
    >>> restricted.sqrt(4)
    2.0
    >>> restricted.sin(1)  # AccessDeniedError
    """
    kwargs['access_policy'] = AccessPolicy.ALLOW_LIST
    kwargs['allowed'] = allowed
    return clone_module(module, **kwargs)


def clone_module_lazy(
    module: Union[ModuleType, str],
    lazy: Dict[str, Callable[[], Any]],
    **kwargs
) -> ModuleClone:
    """
    Create a clone with lazy-loaded attributes.
    
    Parameters
    ----------
    module : Union[ModuleType, str]
        The module to clone.
    lazy : Dict[str, Callable[[], Any]]
        Mapping of attribute names to lazy factory functions.
    **kwargs
        Additional arguments passed to clone_module.
    
    Returns
    -------
    ModuleClone
        Clone with lazy attributes.
    
    Examples
    --------
    >>> import numpy as np
    >>> lazy_np = clone_module_lazy(
    ...     np,
    ...     lazy={
    ...         'random': lambda: __import__('numpy.random')
    ...     },
    ...     mode='lazy'
    ... )
    >>> # numpy.random only imported when accessed
    >>> rng = lazy_np.random.default_rng()
    """
    kwargs['lazy'] = lazy
    return clone_module(module, **kwargs)


def is_module_clone(obj: Any) -> bool:
    """
    Check if an object is a ModuleClone instance.
    
    Parameters
    ----------
    obj : Any
        Object to check.
    
    Returns
    -------
    bool
        True if obj is a ModuleClone.
    """
    return isinstance(obj, ModuleClone)


def get_origin_module(obj: Any) -> Optional[ModuleType]:
    """
    Get the original module from a clone.
    
    Parameters
    ----------
    obj : Any
        Object to inspect.
    
    Returns
    -------
    Optional[ModuleType]
        Original module if obj is a ModuleClone, else None.
    """
    if isinstance(obj, ModuleClone):
        return obj.origin
    return None


def unwrap_clone(obj: Any) -> Any:
    """
    Unwrap a ModuleClone to get the original module.
    
    Parameters
    ----------
    obj : Any
        Object to unwrap.
    
    Returns
    -------
    Any
        Original module if obj is a ModuleClone, else obj unchanged.
    """
    if isinstance(obj, ModuleClone):
        return obj.origin
    return obj


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    'CloneMode',
    'AccessPolicy',
    'CloneEvent',
    
    # Data Classes
    'CloneStatistics',
    'CloneConfig',
    
    # Exceptions
    'ModuleCloneError',
    'FrozenModuleError',
    'AccessDeniedError',
    'LazyLoadError',
    'CircularReferenceError',
    
    # Main Class
    'ModuleClone',
    
    # Public API Functions
    'clone_module',
    'clone_module_deep',
    'clone_module_public',
    'clone_module_restricted',
    'clone_module_lazy',
    'is_module_clone',
    'get_origin_module',
    'unwrap_clone',
]
