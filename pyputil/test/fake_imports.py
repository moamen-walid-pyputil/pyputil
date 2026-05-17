#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
fake_imports.py

Fake Import for Python Module Mocking and Testing.

This module provides a sophisticated, production-ready fake import system that
intercepts and handles missing module imports gracefully. It's designed for
scenarios where actual module imports are unavailable, undesirable, or
intentionally mocked, such as:

- Type checking in environments without dependencies
- Testing and mocking frameworks
- Cross-platform development where optional dependencies may be missing
- CI/CD pipelines with minimal dependency installation
- Security-restricted environments
- Static analysis and linting tools
- REPL exploration of unavailable packages

The system provides intelligent module simulation with configurable behaviors,
logging capabilities, and fine-grained control over which modules are faked.

Features
--------
- Seamless interception of missing module imports
- Hierarchical fake module tree with proper package semantics
- Configurable fake behaviors (return values, callbacks, exceptions)
- Module allowlist/blocklist with pattern matching
- Comprehensive logging and debugging capabilities
- Statistics tracking for faked imports
- Thread-safe global state management
- Context manager for temporary fake import scopes
- Integration with Python's import system hooks
- Serialization support for fake module state
- Performance optimizations with lazy module creation

Classes
-------
FakeModule
    Enhanced fake module with configurable behaviors and introspection.
FakeLoader
    Advanced loader with execution hooks and module initialization.
FakeMetaPathFinder
    Configurable finder with pattern-based filtering.
FakeImportManager
    Central manager for fake import system configuration and state.
FakeModuleConfig
    Configuration for individual fake module behaviors.
FakeImportStats
    Statistics and telemetry for faked imports.

Functions
---------
enable_fake_imports
    Activate the fake import system globally.
disable_fake_imports
    Deactivate and restore original import behavior.
fake_imports_context
    Context manager for temporary fake import activation.
configure_fake_imports
    Configure global fake import behavior.
register_fake_module
    Register a custom fake module implementation.
get_fake_import_stats
    Retrieve statistics about faked imports.
reset_fake_import_stats
    Reset statistics counters.
is_fake_module
    Check if a module is a fake module.
"""

import sys
import types
import importlib.abc
import importlib.util
import importlib.machinery
import logging
import threading
import functools
import json
import re
import time
import warnings
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum, auto
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import (
    Any, Callable, Dict, List, Optional, Pattern, Set, Tuple, Type, 
    Union, Iterator, cast, overload
)
from weakref import WeakSet, WeakValueDictionary

# -----------------------------------------------------------------------------
# Module Configuration and Constants
# -----------------------------------------------------------------------------

# Default configuration
DEFAULT_LOG_LEVEL: int = logging.WARNING
DEFAULT_STATS_ENABLED: bool = True
DEFAULT_LAZY_CREATION: bool = True
DEFAULT_ALLOW_ALL: bool = True
DEFAULT_RETURN_VALUE: Any = None
DEFAULT_CALLABLE_RETURN: Any = None

# Special module names that should never be faked
PROTECTED_MODULES: Set[str] = {
    'sys', 'builtins', '__builtin__', '__main__',
    'importlib', 'types', 'typing', 'abc',
    'threading', 'logging', 'warnings', 'traceback',
    'json', 'pickle', 'marshal', 'codecs', 'encodings',
}

# Configure logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.setLevel(DEFAULT_LOG_LEVEL)


# -----------------------------------------------------------------------------
# Enumerations and Configuration Classes
# -----------------------------------------------------------------------------

class FakeBehavior(Enum):
    """
    Behavior modes for fake module operations.
    
    Attributes
    ----------
    SILENT : auto
        Return default values without any logging or errors.
    LOG : auto
        Log accesses but continue normally.
    WARN : auto
        Issue warnings when accessed.
    ERROR : auto
        Raise errors when accessed.
    CALLBACK : auto
        Invoke custom callback for each access.
    """
    
    SILENT = auto()
    LOG = auto()
    WARN = auto()
    ERROR = auto()
    CALLBACK = auto()


@dataclass
class FakeModuleConfig:
    """
    Configuration for individual fake module behaviors.
    
    Attributes
    ----------
    return_value : Any
        Default value returned for attribute access.
    callable_return : Any
        Value returned when module is called.
    behavior : FakeBehavior
        Behavior mode for this module.
    callback : Optional[Callable]
        Custom callback for CALLBACK behavior.
    log_access : bool
        Whether to log attribute accesses.
    track_usage : bool
        Whether to track usage statistics.
    raise_on_access : bool
        Whether to raise AttributeError on access.
    submodule_config : Optional['FakeModuleConfig']
        Configuration for submodules.
    """
    
    return_value: Any = DEFAULT_RETURN_VALUE
    callable_return: Any = DEFAULT_CALLABLE_RETURN
    behavior: FakeBehavior = FakeBehavior.SILENT
    callback: Optional[Callable[[str, str, tuple, dict], Any]] = None
    log_access: bool = False
    track_usage: bool = True
    raise_on_access: bool = False
    submodule_config: Optional['FakeModuleConfig'] = None
    
    def copy(self) -> 'FakeModuleConfig':
        """Create a deep copy of the configuration."""
        return FakeModuleConfig(
            return_value=self.return_value,
            callable_return=self.callable_return,
            behavior=self.behavior,
            callback=self.callback,
            log_access=self.log_access,
            track_usage=self.track_usage,
            raise_on_access=self.raise_on_access,
            submodule_config=self.submodule_config.copy() if self.submodule_config else None,
        )


@dataclass
class FakeImportStats:
    """
    Statistics and telemetry for faked imports.
    
    Attributes
    ----------
    total_faked : int
        Total number of modules faked.
    access_counts : Dict[str, int]
        Access counts per module.
    creation_times : Dict[str, float]
        Creation timestamps for modules.
    last_access : Dict[str, float]
        Last access timestamp per module.
    call_counts : Dict[str, int]
        Number of times each module was called.
    error_counts : Dict[str, int]
        Number of errors encountered per module.
    """
    
    total_faked: int = 0
    access_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    creation_times: Dict[str, float] = field(default_factory=dict)
    last_access: Dict[str, float] = field(default_factory=dict)
    call_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    error_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    
    def record_creation(self, module_name: str) -> None:
        """Record module creation."""
        with self._lock:
            self.total_faked += 1
            self.creation_times[module_name] = time.time()
    
    def record_access(self, module_name: str, attr_name: str = "__main__") -> None:
        """Record attribute access."""
        with self._lock:
            self.access_counts[f"{module_name}.{attr_name}"] += 1
            self.last_access[module_name] = time.time()
    
    def record_call(self, module_name: str) -> None:
        """Record module call."""
        with self._lock:
            self.call_counts[module_name] += 1
            self.last_access[module_name] = time.time()
    
    def record_error(self, module_name: str) -> None:
        """Record error occurrence."""
        with self._lock:
            self.error_counts[module_name] += 1
    
    def get_module_stats(self, module_name: str) -> Dict[str, Any]:
        """Get statistics for a specific module."""
        with self._lock:
            return {
                'accesses': sum(
                    v for k, v in self.access_counts.items() 
                    if k.startswith(f"{module_name}.")
                ),
                'calls': self.call_counts.get(module_name, 0),
                'errors': self.error_counts.get(module_name, 0),
                'created_at': self.creation_times.get(module_name, 0),
                'last_access': self.last_access.get(module_name, 0),
                'age_seconds': time.time() - self.creation_times.get(module_name, time.time()),
            }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert statistics to dictionary."""
        with self._lock:
            return {
                'total_faked': self.total_faked,
                'top_accessed': sorted(
                    self.access_counts.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:10],
                'top_called': sorted(
                    self.call_counts.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:10],
                'most_errors': sorted(
                    self.error_counts.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:5],
            }
    
    def reset(self) -> None:
        """Reset all statistics."""
        with self._lock:
            self.total_faked = 0
            self.access_counts.clear()
            self.creation_times.clear()
            self.last_access.clear()
            self.call_counts.clear()
            self.error_counts.clear()


# -----------------------------------------------------------------------------
# Enhanced Fake Module
# -----------------------------------------------------------------------------

class FakeModule(types.ModuleType):
    """
    Advanced fake module with configurable behaviors and introspection.
    
    This enhanced fake module provides sophisticated mocking capabilities
    with configurable return values, callbacks, logging, and statistics
    tracking. It maintains proper module semantics while allowing complete
    control over its behavior.
    
    Attributes
    ----------
    __fake__ : bool
        Flag indicating this is a fake module.
    _config : FakeModuleConfig
        Configuration for this module's behavior.
    _stats : FakeImportStats
        Reference to global statistics tracker.
    _created_at : float
        Timestamp when module was created.
    _access_history : deque
        History of attribute accesses.
    
    Examples
    --------
    >>> fake = FakeModule("my_missing_module")
    >>> fake.some_attribute
    None
    >>> fake.some_function()
    None
    >>> fake.submodule.nested.attribute
    <FakeModule my_missing_module.submodule.nested>
    """
    
    def __init__(
        self,
        name: str,
        config: Optional[FakeModuleConfig] = None,
        stats: Optional[FakeImportStats] = None,
    ):
        """
        Initialize fake module.
        
        Parameters
        ----------
        name : str
            Module name.
        config : Optional[FakeModuleConfig]
            Configuration for this module's behavior.
        stats : Optional[FakeImportStats]
            Statistics tracker reference.
        """
        super().__init__(name)
        
        self.__dict__["__fake__"] = True
        self.__dict__["_config"] = config or FakeModuleConfig()
        self.__dict__["_stats"] = stats
        self.__dict__["_created_at"] = time.time()
        self.__dict__["_access_history"] = deque(maxlen=100)
        self.__dict__["_submodules"] = {}
        self.__dict__["_lock"] = threading.RLock()
        
        # Record creation
        if self._stats and self._config.track_usage:
            self._stats.record_creation(name)
    
    def _get_submodule_config(self) -> FakeModuleConfig:
        """Get configuration for submodules."""
        if self._config.submodule_config:
            return self._config.submodule_config
        return self._config
    
    def _handle_access(self, attr_name: str, is_call: bool = False) -> Any:
        """
        Handle attribute access with configured behavior.
        
        Parameters
        ----------
        attr_name : str
            Name of attribute being accessed.
        is_call : bool
            Whether this is a call operation.
        
        Returns
        -------
        Any
            Value based on configuration.
        
        Raises
        ------
        AttributeError
            If raise_on_access is True.
        RuntimeError
            If behavior is ERROR.
        """
        with self._lock:
            # Record access
            if self._stats and self._config.track_usage:
                self._stats.record_access(self.__name__, attr_name)
            
            self._access_history.append({
                'attr': attr_name,
                'is_call': is_call,
                'timestamp': time.time(),
            })
            
            # Log access
            if self._config.log_access:
                logger.debug(
                    f"Fake module access: {self.__name__}.{attr_name} "
                    f"({'call' if is_call else 'attribute'})"
                )
            
            # Handle based on behavior
            if self._config.behavior == FakeBehavior.ERROR:
                error_msg = f"Fake module '{self.__name__}' configured to error on access"
                if self._stats:
                    self._stats.record_error(self.__name__)
                raise RuntimeError(error_msg)
            
            elif self._config.behavior == FakeBehavior.WARN:
                warnings.warn(
                    f"Accessing fake module: {self.__name__}.{attr_name}",
                    UserWarning,
                    stacklevel=3,
                )
            
            elif self._config.behavior == FakeBehavior.LOG:
                logger.info(f"Fake module accessed: {self.__name__}.{attr_name}")
            
            elif self._config.behavior == FakeBehavior.CALLBACK:
                if self._config.callback:
                    return self._config.callback(
                        self.__name__,
                        attr_name,
                        (),
                        {},
                    )
            
            # Handle raise_on_access
            if self._config.raise_on_access:
                if self._stats:
                    self._stats.record_error(self.__name__)
                raise AttributeError(
                    f"Fake module '{self.__name__}' has no attribute '{attr_name}'"
                )
            
            # Return configured value
            if is_call:
                return self._config.callable_return
            return self._config.return_value
    
    def __getattr__(self, name: str) -> Any:
        """
        Get attribute with fake module behavior.
        
        Special attributes (starting with __) are handled normally.
        All other attributes trigger fake module behavior.
        """
        # Handle special methods normally
        if name.startswith('__') and name.endswith('__'):
            return super().__getattribute__(name)
        
        # Handle internal attributes
        if name.startswith('_'):
            try:
                return super().__getattribute__(name)
            except AttributeError:
                pass
        
        fullname = f"{self.__name__}.{name}"
        
        # Check existing submodule
        with self._lock:
            if name in self._submodules:
                return self._submodules[name]
        
        # Check sys.modules
        if fullname in sys.modules:
            existing = sys.modules[fullname]
            if hasattr(existing, '__fake__'):
                with self._lock:
                    self._submodules[name] = existing
                return existing
        
        # Handle access
        self._handle_access(name, is_call=False)
        
        # Create new fake submodule
        sub_config = self._get_submodule_config()
        fake = FakeModule(fullname, sub_config, self._stats)
        sys.modules[fullname] = fake
        
        with self._lock:
            self._submodules[name] = fake
        
        # Set as attribute
        try:
            super().__setattr__(name, fake)
        except:
            pass
        
        return fake
    
    def __setattr__(self, name: str, value: Any) -> None:
        """Set attribute with tracking."""
        super().__setattr__(name, value)
        
        if not name.startswith('_'):
            with self._lock:
                if name in self._submodules:
                    self._submodules[name] = value
    
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """
        Call module with configured behavior.
        
        Parameters
        ----------
        *args : Any
            Positional arguments.
        **kwargs : Any
            Keyword arguments.
        
        Returns
        -------
        Any
            Value based on configuration.
        """
        # Record call
        if self._stats and self._config.track_usage:
            self._stats.record_call(self.__name__)
        
        # Handle based on behavior
        if self._config.behavior == FakeBehavior.CALLBACK and self._config.callback:
            return self._config.callback(self.__name__, "__call__", args, kwargs)
        
        return self._handle_access("__call__", is_call=True)
    
    def __repr__(self) -> str:
        """Enhanced representation with configuration info."""
        behavior = self._config.behavior.name.lower()
        return f"<FakeModule '{self.__name__}' ({behavior})>"
    
    def __dir__(self) -> List[str]:
        """Return directory including submodules."""
        base = super().__dir__()
        with self._lock:
            base.extend(self._submodules.keys())
        return sorted(set(base))
    
    def get_config(self) -> FakeModuleConfig:
        """Get current configuration."""
        return self._config
    
    def update_config(self, **kwargs) -> None:
        """
        Update module configuration.
        
        Parameters
        ----------
        **kwargs
            Configuration parameters to update.
        """
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
    
    def get_access_history(self) -> List[Dict[str, Any]]:
        """Get recent access history."""
        with self._lock:
            return list(self._access_history)
    
    def get_submodules(self) -> Dict[str, 'FakeModule']:
        """Get dictionary of submodules."""
        with self._lock:
            return self._submodules.copy()
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize module state to dictionary."""
        with self._lock:
            return {
                'name': self.__name__,
                'fake': True,
                'created_at': self._created_at,
                'config': asdict(self._config),
                'submodule_count': len(self._submodules),
                'access_count': len(self._access_history),
            }


# -----------------------------------------------------------------------------
# Enhanced Fake Loader
# -----------------------------------------------------------------------------

class FakeLoader(importlib.abc.Loader):
    """
    Advanced loader with execution hooks and module initialization.
    
    This loader provides sophisticated module creation with support for
    custom initialization, post-creation hooks, and package structure.
    """
    
    def __init__(
        self,
        fullname: str,
        config: Optional[FakeModuleConfig] = None,
        stats: Optional[FakeImportStats] = None,
        is_package: bool = True,
    ):
        """
        Initialize fake loader.
        
        Parameters
        ----------
        fullname : str
            Full module name.
        config : Optional[FakeModuleConfig]
            Module configuration.
        stats : Optional[FakeImportStats]
            Statistics tracker.
        is_package : bool
            Whether this is a package.
        """
        self.fullname = fullname
        self.config = config or FakeModuleConfig()
        self.stats = stats
        self.is_package = is_package
        self._pre_create_hooks: List[Callable] = []
        self._post_create_hooks: List[Callable] = []
    
    def add_pre_create_hook(self, hook: Callable[[str, ModuleSpec], None]) -> None:
        """Add hook called before module creation."""
        self._pre_create_hooks.append(hook)
    
    def add_post_create_hook(self, hook: Callable[[FakeModule], None]) -> None:
        """Add hook called after module creation."""
        self._post_create_hooks.append(hook)
    
    def create_module(self, spec: ModuleSpec) -> FakeModule:
        """
        Create fake module instance.
        
        Parameters
        ----------
        spec : ModuleSpec
            Module specification.
        
        Returns
        -------
        FakeModule
            Created fake module.
        """
        # Execute pre-create hooks
        for hook in self._pre_create_hooks:
            try:
                hook(self.fullname, spec)
            except Exception as e:
                logger.error(f"Pre-create hook failed for {self.fullname}: {e}")
        
        # Create module
        module = FakeModule(self.fullname, self.config, self.stats)
        
        # Set basic attributes
        module.__loader__ = self
        module.__package__ = self.fullname.rpartition('.')[0] if self.is_package else self.fullname
        module.__path__ = [] if self.is_package else None
        
        return module
    
    def exec_module(self, module: FakeModule) -> None:
        """
        Execute module initialization.
        
        Parameters
        ----------
        module : FakeModule
            Module to initialize.
        """
        # Set specification
        module.__spec__ = importlib.util.spec_from_loader(
            module.__name__,
            self,
            origin="fake",
            is_package=self.is_package,
        )
        
        # Execute post-create hooks
        for hook in self._post_create_hooks:
            try:
                hook(module)
            except Exception as e:
                logger.error(f"Post-create hook failed for {module.__name__}: {e}")
    
    def __repr__(self) -> str:
        return f"<FakeLoader '{self.fullname}'>"


# -----------------------------------------------------------------------------
# Enhanced MetaPath Finder
# -----------------------------------------------------------------------------

class FakeMetaPathFinder(importlib.abc.MetaPathFinder):
    """
    Configurable finder with pattern-based filtering.
    
    This finder provides sophisticated control over which modules are faked
    using allowlist/blocklist patterns, package detection, and custom rules.
    """
    
    def __init__(
        self,
        config: Optional[FakeModuleConfig] = None,
        stats: Optional[FakeImportStats] = None,
        allow_patterns: Optional[List[Union[str, Pattern]]] = None,
        block_patterns: Optional[List[Union[str, Pattern]]] = None,
        allow_all: bool = DEFAULT_ALLOW_ALL,
    ):
        """
        Initialize meta path finder.
        
        Parameters
        ----------
        config : Optional[FakeModuleConfig]
            Default configuration for faked modules.
        stats : Optional[FakeImportStats]
            Statistics tracker.
        allow_patterns : Optional[List[Union[str, Pattern]]]
            Patterns for modules to allow faking.
        block_patterns : Optional[List[Union[str, Pattern]]]
            Patterns for modules to never fake.
        allow_all : bool
            Whether to fake all modules by default.
        """
        self.config = config or FakeModuleConfig()
        self.stats = stats
        self.allow_all = allow_all
        
        # Compile patterns
        self.allow_patterns = self._compile_patterns(allow_patterns or [])
        self.block_patterns = self._compile_patterns(block_patterns or [])
        
        # Custom module configs
        self._module_configs: Dict[str, FakeModuleConfig] = {}
        
        # Protected modules that should never be faked
        self.protected_modules = PROTECTED_MODULES.copy()
        
        # Statistics
        self._find_attempts = 0
        self._find_successes = 0
        self._lock = threading.RLock()
    
    @staticmethod
    def _compile_patterns(patterns: List[Union[str, Pattern]]) -> List[Pattern]:
        """Compile string patterns to regex."""
        compiled = []
        for p in patterns:
            if isinstance(p, str):
                compiled.append(re.compile(p))
            else:
                compiled.append(p)
        return compiled
    
    def _matches_pattern(self, name: str, patterns: List[Pattern]) -> bool:
        """Check if name matches any pattern."""
        return any(p.search(name) for p in patterns)
    
    def _should_fake(self, fullname: str) -> bool:
        """
        Determine if a module should be faked.
        
        Parameters
        ----------
        fullname : str
            Full module name.
        
        Returns
        -------
        bool
            True if module should be faked.
        """
        # Never fake protected modules
        if fullname in self.protected_modules:
            return False
        
        # Check blocklist first
        if self.block_patterns and self._matches_pattern(fullname, self.block_patterns):
            logger.debug(f"Module '{fullname}' blocked by pattern")
            return False
        
        # Check allowlist
        if self.allow_patterns:
            allowed = self._matches_pattern(fullname, self.allow_patterns)
            if not allowed:
                logger.debug(f"Module '{fullname}' not in allowlist")
            return allowed
        
        # Default behavior
        return self.allow_all
    
    def _get_module_config(self, fullname: str) -> FakeModuleConfig:
        """Get configuration for a specific module."""
        # Check exact match
        if fullname in self._module_configs:
            return self._module_configs[fullname]
        
        # Check pattern matches
        for pattern, config in self._pattern_configs.items():
            if pattern.search(fullname):
                return config
        
        return self.config
    
    def add_protected_module(self, module_name: str) -> None:
        """Add module to protected list."""
        with self._lock:
            self.protected_modules.add(module_name)
    
    def remove_protected_module(self, module_name: str) -> None:
        """Remove module from protected list."""
        with self._lock:
            self.protected_modules.discard(module_name)
    
    def set_module_config(self, module_name: str, config: FakeModuleConfig) -> None:
        """Set custom configuration for a module."""
        with self._lock:
            self._module_configs[module_name] = config
    
    _pattern_configs: Dict[Pattern, FakeModuleConfig] = {}
    
    def set_pattern_config(self, pattern: Union[str, Pattern], config: FakeModuleConfig) -> None:
        """Set custom configuration for modules matching pattern."""
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        with self._lock:
            self._pattern_configs[pattern] = config
    
    def find_spec(
        self,
        fullname: str,
        path: Optional[Any] = None,
        target: Optional[Any] = None,
    ) -> Optional[ModuleSpec]:
        """
        Find module specification for fake modules.
        
        Parameters
        ----------
        fullname : str
            Fully qualified module name.
        path : Optional[Any]
            Path to search for modules.
        target : Optional[Any]
            Target module.
        
        Returns
        -------
        Optional[ModuleSpec]
            Module specification if module should be faked, None otherwise.
        """
        with self._lock:
            self._find_attempts += 1
        
        # Skip if already loaded
        if fullname in sys.modules:
            return None
        
        # Skip builtins
        if fullname in sys.builtin_module_names:
            return None
        
        # Check if should fake
        if not self._should_fake(fullname):
            return None
        
        logger.debug(f"Faking import for: {fullname}")
        
        # Get configuration
        module_config = self._get_module_config(fullname)
        
        # Determine if package
        is_package = '.' not in fullname or fullname.count('.') > 0
        
        # Create loader
        loader = FakeLoader(fullname, module_config, self.stats, is_package)
        
        # Create spec
        spec = ModuleSpec(
            name=fullname,
            loader=loader,
            origin=f"fake://{fullname}",
            is_package=is_package,
        )
        
        if is_package:
            spec.submodule_search_locations = []
        
        with self._lock:
            self._find_successes += 1
        
        return spec
    
    def get_stats(self) -> Dict[str, Any]:
        """Get finder statistics."""
        with self._lock:
            return {
                'find_attempts': self._find_attempts,
                'find_successes': self._find_successes,
                'success_rate': f"{(self._find_successes / max(1, self._find_attempts)) * 100:.1f}%",
                'protected_count': len(self.protected_modules),
                'allow_patterns': len(self.allow_patterns),
                'block_patterns': len(self.block_patterns),
                'custom_configs': len(self._module_configs),
            }
    
    def reset_stats(self) -> None:
        """Reset finder statistics."""
        with self._lock:
            self._find_attempts = 0
            self._find_successes = 0


# -----------------------------------------------------------------------------
# Fake Import Manager
# -----------------------------------------------------------------------------

class FakeImportManager:
    """
    Central manager for fake import system configuration and state.
    
    This singleton class provides unified control over the fake import system,
    managing the finder, configuration, statistics, and lifecycle.
    
    Attributes
    ----------
    _instance : Optional[FakeImportManager]
        Singleton instance.
    enabled : bool
        Whether fake imports are currently enabled.
    finder : FakeMetaPathFinder
        Active meta path finder.
    stats : FakeImportStats
        Global statistics tracker.
    """
    
    _instance: Optional['FakeImportManager'] = None
    _lock = threading.RLock()
    
    def __new__(cls) -> 'FakeImportManager':
        """Singleton pattern for global manager."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize fake import manager."""
        if self._initialized:
            return
        
        self.enabled = False
        self.finder: Optional[FakeMetaPathFinder] = None
        self.stats = FakeImportStats()
        self._original_meta_path: List[Any] = []
        self._initialized = True
        self._creation_time = datetime.utcnow()
        self._event_hooks: Dict[str, List[Callable]] = defaultdict(list)
        
        logger.info("FakeImportManager initialized")
    
    def configure(
        self,
        config: Optional[FakeModuleConfig] = None,
        allow_patterns: Optional[List[Union[str, Pattern]]] = None,
        block_patterns: Optional[List[Union[str, Pattern]]] = None,
        allow_all: bool = DEFAULT_ALLOW_ALL,
        log_level: int = DEFAULT_LOG_LEVEL,
    ) -> None:
        """
        Configure fake import system.
        
        Parameters
        ----------
        config : Optional[FakeModuleConfig]
            Default configuration for faked modules.
        allow_patterns : Optional[List[Union[str, Pattern]]]
            Patterns for modules to allow.
        block_patterns : Optional[List[Union[str, Pattern]]]
            Patterns for modules to block.
        allow_all : bool
            Whether to fake all modules by default.
        log_level : int
            Logging level.
        """
        logger.setLevel(log_level)
        
        # Create finder with configuration
        self.finder = FakeMetaPathFinder(
            config=config or FakeModuleConfig(),
            stats=self.stats,
            allow_patterns=allow_patterns,
            block_patterns=block_patterns,
            allow_all=allow_all,
        )
        
        logger.info("Fake import system configured")
    
    def enable(self) -> None:
        """Enable fake import system globally."""
        if self.enabled:
            logger.warning("Fake imports already enabled")
            return
        
        if self.finder is None:
            self.configure()
        
        with self._lock:
            self._original_meta_path = sys.meta_path.copy()
            sys.meta_path.insert(0, self.finder)
            self.enabled = True
        
        self._trigger_event('enabled')
        logger.info("Fake import system enabled")
    
    def disable(self) -> None:
        """Disable fake import system and restore original behavior."""
        if not self.enabled:
            logger.warning("Fake imports not enabled")
            return
        
        with self._lock:
            # Remove our finder
            if self.finder in sys.meta_path:
                sys.meta_path.remove(self.finder)
            
            # Restore original if we have it
            if self._original_meta_path:
                sys.meta_path = self._original_meta_path
                self._original_meta_path = []
            
            self.enabled = False
        
        self._trigger_event('disabled')
        logger.info("Fake import system disabled")
    
    def register_module_config(self, module_name: str, config: FakeModuleConfig) -> None:
        """Register custom configuration for a module."""
        if self.finder:
            self.finder.set_module_config(module_name, config)
    
    def register_pattern_config(self, pattern: Union[str, Pattern], config: FakeModuleConfig) -> None:
        """Register configuration for modules matching pattern."""
        if self.finder:
            self.finder.set_pattern_config(pattern, config)
    
    def add_protected_module(self, module_name: str) -> None:
        """Add module to protected list."""
        if self.finder:
            self.finder.add_protected_module(module_name)
    
    def add_event_hook(self, event: str, hook: Callable) -> None:
        """
        Add hook for system events.
        
        Events: 'enabled', 'disabled', 'module_created', 'module_accessed'
        """
        self._event_hooks[event].append(hook)
    
    def _trigger_event(self, event: str, **kwargs) -> None:
        """Trigger event hooks."""
        for hook in self._event_hooks.get(event, []):
            try:
                hook(**kwargs)
            except Exception as e:
                logger.error(f"Event hook failed for {event}: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        stats = {
            'enabled': self.enabled,
            'uptime_seconds': (datetime.utcnow() - self._creation_time).total_seconds(),
            'import_stats': self.stats.to_dict(),
        }
        
        if self.finder:
            stats['finder_stats'] = self.finder.get_stats()
        
        return stats
    
    def reset_stats(self) -> None:
        """Reset all statistics."""
        self.stats.reset()
        if self.finder:
            self.finder.reset_stats()
    
    def get_fake_modules(self) -> List[str]:
        """Get list of all fake modules currently loaded."""
        return [
            name for name, mod in sys.modules.items()
            if hasattr(mod, '__fake__') and mod.__fake__
        ]
    
    def clear_fake_modules(self) -> None:
        """Remove all fake modules from sys.modules."""
        fake_names = self.get_fake_modules()
        for name in fake_names:
            del sys.modules[name]
        logger.info(f"Cleared {len(fake_names)} fake modules")
    
    @contextmanager
    def temporary_context(self, **config):
        """
        Context manager for temporary fake import activation.
        
        Parameters
        ----------
        **config
            Temporary configuration overrides.
        
        Yields
        ------
        FakeImportManager
            Self reference.
        """
        was_enabled = self.enabled
        
        # Apply temporary config
        if config:
            original_config = None
            if self.finder:
                original_config = self.finder.config
                temp_config = original_config.copy()
                for key, value in config.items():
                    if hasattr(temp_config, key):
                        setattr(temp_config, key, value)
                self.finder.config = temp_config
        
        if not was_enabled:
            self.enable()
        
        try:
            yield self
        finally:
            if config and self.finder and original_config:
                self.finder.config = original_config
            
            if not was_enabled:
                self.disable()


# -----------------------------------------------------------------------------
# Public API Functions
# -----------------------------------------------------------------------------

# Global manager instance
_manager = FakeImportManager()


def enable_fake_imports(
    config: Optional[FakeModuleConfig] = None,
    allow_patterns: Optional[List[Union[str, Pattern]]] = None,
    block_patterns: Optional[List[Union[str, Pattern]]] = None,
    allow_all: bool = DEFAULT_ALLOW_ALL,
    log_level: int = DEFAULT_LOG_LEVEL,
) -> None:
    """
    Enable fake import system globally.
    
    Parameters
    ----------
    config : Optional[FakeModuleConfig]
        Default configuration for faked modules.
    allow_patterns : Optional[List[Union[str, Pattern]]]
        Patterns for modules to allow faking.
    block_patterns : Optional[List[Union[str, Pattern]]]
        Patterns for modules to never fake.
    allow_all : bool
        Whether to fake all modules by default.
    log_level : int
        Logging level for fake import operations.
    
    Examples
    --------
    >>> # Enable with default settings
    >>> enable_fake_imports()
    
    >>> # Enable with custom configuration
    >>> config = FakeModuleConfig(behavior=FakeBehavior.LOG, return_value=[])
    >>> enable_fake_imports(
    ...     config=config,
    ...     allow_patterns=[r"^my_package\."],
    ...     block_patterns=[r"^os$", r"^sys$"],
    ... )
    
    >>> # Enable with logging
    >>> enable_fake_imports(log_level=logging.DEBUG)
    """
    _manager.configure(
        config=config,
        allow_patterns=allow_patterns,
        block_patterns=block_patterns,
        allow_all=allow_all,
        log_level=log_level,
    )
    _manager.enable()


def disable_fake_imports() -> None:
    """
    Disable fake import system and restore original behavior.
    
    Examples
    --------
    >>> enable_fake_imports()
    >>> # ... do work with fake imports ...
    >>> disable_fake_imports()
    """
    _manager.disable()


@contextmanager
def fake_imports_context(
    config: Optional[FakeModuleConfig] = None,
    allow_patterns: Optional[List[Union[str, Pattern]]] = None,
    block_patterns: Optional[List[Union[str, Pattern]]] = None,
    allow_all: bool = DEFAULT_ALLOW_ALL,
    **temp_config,
) -> Iterator[FakeImportManager]:
    """
    Context manager for temporary fake import activation.
    
    Parameters
    ----------
    config : Optional[FakeModuleConfig]
        Default configuration for faked modules.
    allow_patterns : Optional[List[Union[str, Pattern]]]
        Patterns for modules to allow faking.
    block_patterns : Optional[List[Union[str, Pattern]]]
        Patterns for modules to never fake.
    allow_all : bool
        Whether to fake all modules by default.
    **temp_config
        Temporary configuration overrides.
    
    Yields
    ------
    FakeImportManager
        Manager instance for the context.
    
    Examples
    --------
    >>> with fake_imports_context(allow_all=True) as manager:
    ...     import missing_module
    ...     print(missing_module.some_function())
    ...     stats = manager.get_stats()
    >>> # Fake imports disabled after context
    
    >>> # With temporary config
    >>> with fake_imports_context(behavior=FakeBehavior.WARN) as manager:
    ...     import missing_module  # Will warn on access
    """
    # Store original state
    was_enabled = _manager.enabled
    original_finder = _manager.finder
    
    try:
        # Apply configuration
        _manager.configure(
            config=config,
            allow_patterns=allow_patterns,
            block_patterns=block_patterns,
            allow_all=allow_all,
        )
        
        # Apply temporary config overrides
        if temp_config and _manager.finder:
            for key, value in temp_config.items():
                if hasattr(_manager.finder.config, key):
                    setattr(_manager.finder.config, key, value)
        
        _manager.enable()
        yield _manager
        
    finally:
        # Restore original state
        _manager.disable()
        
        if original_finder:
            _manager.finder = original_finder
        
        if was_enabled:
            _manager.enable()


def configure_fake_imports(
    module_configs: Optional[Dict[str, FakeModuleConfig]] = None,
    pattern_configs: Optional[Dict[Union[str, Pattern], FakeModuleConfig]] = None,
    protected_modules: Optional[List[str]] = None,
    **global_config,
) -> None:
    """
    Configure fake import system behavior.
    
    Parameters
    ----------
    module_configs : Optional[Dict[str, FakeModuleConfig]]
        Custom configurations for specific modules.
    pattern_configs : Optional[Dict[Union[str, Pattern], FakeModuleConfig]]
        Custom configurations for module patterns.
    protected_modules : Optional[List[str]]
        Additional modules to protect from faking.
    **global_config
        Global configuration options for FakeModuleConfig.
    
    Examples
    --------
    >>> # Configure specific module behavior
    >>> config = FakeModuleConfig(return_value={"mocked": True})
    >>> configure_fake_imports(
    ...     module_configs={"my_package.api": config},
    ...     protected_modules=["my_critical_module"],
    ...     behavior=FakeBehavior.LOG,
    ... )
    """
    if not _manager.finder:
        _manager.configure()
    
    # Apply global config
    if global_config:
        for key, value in global_config.items():
            if hasattr(_manager.finder.config, key):
                setattr(_manager.finder.config, key, value)
    
    # Apply module-specific configs
    if module_configs:
        for module_name, config in module_configs.items():
            _manager.register_module_config(module_name, config)
    
    # Apply pattern configs
    if pattern_configs:
        for pattern, config in pattern_configs.items():
            _manager.register_pattern_config(pattern, config)
    
    # Add protected modules
    if protected_modules:
        for module_name in protected_modules:
            _manager.add_protected_module(module_name)


def register_fake_module(
    module_name: str,
    config: Optional[FakeModuleConfig] = None,
) -> None:
    """
    Register a custom fake module implementation.
    
    Parameters
    ----------
    module_name : str
        Name of module to register custom configuration for.
    config : Optional[FakeModuleConfig]
        Custom configuration for this module.
    
    Examples
    --------
    >>> config = FakeModuleConfig(
    ...     behavior=FakeBehavior.CALLBACK,
    ...     callback=lambda name, attr, args, kwargs: f"Called {name}.{attr}"
    ... )
    >>> register_fake_module("my_service.client", config)
    """
    if config is None:
        config = FakeModuleConfig()
    
    _manager.register_module_config(module_name, config)


def get_fake_import_stats() -> Dict[str, Any]:
    """
    Retrieve statistics about faked imports.
    
    Returns
    -------
    Dict[str, Any]
        Comprehensive statistics dictionary.
    
    Examples
    --------
    >>> stats = get_fake_import_stats()
    >>> print(f"Total faked modules: {stats['import_stats']['total_faked']}")
    >>> print(f"Enabled: {stats['enabled']}")
    """
    return _manager.get_stats()


def reset_fake_import_stats() -> None:
    """
    Reset all fake import statistics.
    
    Examples
    --------
    >>> reset_fake_import_stats()
    """
    _manager.reset_stats()


def is_fake_module(module: Any) -> bool:
    """
    Check if an object is a fake module.
    
    Parameters
    ----------
    module : Any
        Object to check.
    
    Returns
    -------
    bool
        True if object is a fake module.
    
    Examples
    --------
    >>> import missing_module
    >>> is_fake_module(missing_module)
    True
    >>> import os
    >>> is_fake_module(os)
    False
    """
    return hasattr(module, '__fake__') and getattr(module, '__fake__', False)


def get_fake_modules() -> List[str]:
    """
    Get list of all currently loaded fake modules.
    
    Returns
    -------
    List[str]
        List of fake module names.
    
    Examples
    --------
    >>> modules = get_fake_modules()
    >>> print(f"Loaded fake modules: {', '.join(modules)}")
    """
    return _manager.get_fake_modules()


def clear_fake_modules() -> None:
    """
    Remove all fake modules from sys.modules.
    
    Examples
    --------
    >>> clear_fake_modules()
    """
    _manager.clear_fake_modules()


def create_fake_module(
    name: str,
    config: Optional[FakeModuleConfig] = None,
) -> FakeModule:
    """
    Create a standalone fake module.
    
    Parameters
    ----------
    name : str
        Module name.
    config : Optional[FakeModuleConfig]
        Module configuration.
    
    Returns
    -------
    FakeModule
        Created fake module.
    
    Examples
    --------
    >>> fake = create_fake_module("my_mock_module")
    >>> fake.some_attribute = "value"
    >>> fake.some_function()
    None
    """
    stats = _manager.stats if _manager else None
    return FakeModule(name, config, stats)


# -----------------------------------------------------------------------------
# Decorator for Function-Level Fake Imports
# -----------------------------------------------------------------------------

def with_fake_imports(
    modules: Optional[List[str]] = None,
    **config,
) -> Callable:
    """
    Decorator to temporarily enable fake imports for a function.
    
    Parameters
    ----------
    modules : Optional[List[str]]
        Specific modules to configure with custom behavior.
    **config
        Configuration options for fake imports.
    
    Returns
    -------
    Callable
        Decorated function.
    
    Examples
    --------
    >>> @with_fake_imports(
    ...     modules=["requests", "boto3"],
    ...     behavior=FakeBehavior.LOG,
    ... )
    ... def test_function():
    ...     import requests
    ...     return requests.get("https://example.com")
    >>> 
    >>> result = test_function()  # Fake imports only active inside function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with fake_imports_context(**config) as manager:
                if modules:
                    for module_name in modules:
                        module_config = FakeModuleConfig(**config)
                        manager.register_module_config(module_name, module_config)
                
                return func(*args, **kwargs)
        return wrapper
    return decorator


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Main classes
    'FakeModule',
    'FakeLoader',
    'FakeMetaPathFinder',
    'FakeImportManager',
    'FakeModuleConfig',
    'FakeImportStats',
    'FakeBehavior',
    
    # Primary functions
    'enable_fake_imports',
    'disable_fake_imports',
    'fake_imports_context',
    'configure_fake_imports',
    'register_fake_module',
    'get_fake_import_stats',
    'reset_fake_import_stats',
    'is_fake_module',
    'get_fake_modules',
    'clear_fake_modules',
    'create_fake_module',
    
    # Decorator
    'with_fake_imports',
    
    # Legacy compatibility (accessible via module)
    # Note: These are intentionally not exported in __all__ to encourage new API usage
    
    # Constants
    'PROTECTED_MODULES',
]