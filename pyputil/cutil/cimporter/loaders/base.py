#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    BASE LOADER ABSTRACTIONS
==================================

Abstract base classes and interfaces for module loading systems.
Provides the foundation for both C/C++ and Cython loaders with
cross-platform compatibility and advanced features.
"""

import importlib
import importlib.util
import sys
import threading
import time
import weakref
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

# Import core components
from ..core.exceptions import (
    ImportModuleError,
    CImporterBaseException,
    ErrorCategory,
    ErrorSeverity,
    DependencyError,
)
from ..core.enums import (
    LinkType,
    CacheStrategy,
    ParallelStrategy,
    LogLevel,
    DependencyType,
    SandboxPolicy
)
from ..core.cache import CacheKey, CacheManager


class LoaderState(Enum):
    """
    State enumeration for loader lifecycle management.

    Attributes
    ----------
    UNINITIALIZED : str
        Loader created but not configured.
    INITIALIZED : str
        Loader configured and ready.
    LOADING : str
        Currently loading a module.
    LOADED : str
        Module loaded successfully.
    FAILED : str
        Loading failed.
    RELOADING : str
        Currently reloading a module.
    UNLOADED : str
        Module has been unloaded.
    DESTROYED : str
        Loader destroyed, cannot be used.
    """

    UNINITIALIZED = "uninitialized"
    INITIALIZED = "initialized"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"
    RELOADING = "reloading"
    UNLOADED = "unloaded"
    DESTROYED = "destroyed"


class ModuleOrigin(Enum):
    """
    Origin of a loaded module.

    Attributes
    ----------
    SOURCE : str
        Compiled from source file.
    CACHE : str
        Retrieved from cache.
    PREBUILT : str
        Pre-built binary loaded directly.
    SYSTEM : str
        System-installed module.
    VIRTUAL : str
        Virtual module created programmatically.
    """

    SOURCE = "source"
    CACHE = "cache"
    PREBUILT = "prebuilt"
    SYSTEM = "system"
    VIRTUAL = "virtual"


class LoaderEventType(Enum):
    """
    Event types for loader callbacks.

    Attributes
    ----------
    PRE_COMPILE : str
        Before compilation starts.
    POST_COMPILE : str
        After compilation completes.
    PRE_LOAD : str
        Before module loading.
    POST_LOAD : str
        After module loaded.
    PRE_RELOAD : str
        Before module reload.
    POST_RELOAD : str
        After module reloaded.
    COMPILE_ERROR : str
        Compilation error occurred.
    LOAD_ERROR : str
        Loading error occurred.
    CACHE_HIT : str
        Cache hit occurred.
    CACHE_MISS : str
        Cache miss occurred.
    DEPENDENCY_RESOLVED : str
        Dependency resolved.
    STATE_CHANGED : str
        Loader state changed.
    """

    PRE_COMPILE = "pre_compile"
    POST_COMPILE = "post_compile"
    PRE_LOAD = "pre_load"
    POST_LOAD = "post_load"
    PRE_RELOAD = "pre_reload"
    POST_RELOAD = "post_reload"
    COMPILE_ERROR = "compile_error"
    LOAD_ERROR = "load_error"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    DEPENDENCY_RESOLVED = "dependency_resolved"
    STATE_CHANGED = "state_changed"
    PROGRESS = "progress"


@dataclass
class LoaderEvent:
    """
    Event data structure for loader callbacks.

    Parameters
    ----------
    event_type : LoaderEventType
        Type of event.
    module_name : str
        Name of the module involved.
    timestamp : float
        Unix timestamp of the event.
    data : Dict[str, Any]
        Additional event data.
    error : Optional[Exception]
        Error if event is error-related.

    Attributes
    ----------
    event_type : LoaderEventType
        Event type.
    module_name : str
        Module name.
    timestamp : float
        Event timestamp.
    data : Dict[str, Any]
        Event data.
    error : Optional[Exception]
        Associated error.
    """

    event_type: LoaderEventType
    module_name: str
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Exception] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert event to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "event_type": self.event_type.value,
            "module_name": self.module_name,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat(),
            "data": self.data,
            "error": str(self.error) if self.error else None,
        }


@dataclass
class ModuleMetadata:
    """
    Metadata for a loaded module.

    Parameters
    ----------
    name : str
        Module name.
    source_path : Path
        Path to source file.
    library_path : Path
        Path to compiled library.
    origin : ModuleOrigin
        Origin of the module.
    load_time : float
        Time taken to load in seconds.
    compile_time : float
        Time taken to compile in seconds (0 if from cache).
    cache_key : Optional[CacheKey]
        Cache key if cached.
    dependencies : List[str]
        List of module dependencies.
    dependents : List[str]
        List of modules that depend on this module.
    version : Optional[str]
        Module version if available.
    checksum : str
        Source file checksum.
    loaded_at : float
        Timestamp when module was loaded.
    access_count : int
        Number of times module has been accessed.
    last_accessed : float
        Timestamp of last access.
    attributes : Dict[str, Any]
        Additional module attributes.
    symbol_table : Dict[str, Any]
        Exported symbols information.

    Attributes
    ----------
    name : str
        Module name.
    source_path : Path
        Source file path.
    library_path : Path
        Library file path.
    origin : ModuleOrigin
        Module origin.
    load_time : float
        Load time in seconds.
    compile_time : float
        Compile time in seconds.
    cache_key : Optional[CacheKey]
        Cache key.
    dependencies : List[str]
        Dependencies.
    dependents : List[str]
        Dependent modules.
    version : Optional[str]
        Version string.
    checksum : str
        Source checksum.
    loaded_at : float
        Load timestamp.
    access_count : int
        Access counter.
    last_accessed : float
        Last access timestamp.
    attributes : Dict[str, Any]
        Additional attributes.
    symbol_table : Dict[str, Any]
        Symbol table.
    """

    name: str
    source_path: Path
    library_path: Path
    origin: ModuleOrigin = ModuleOrigin.SOURCE
    load_time: float = 0.0
    compile_time: float = 0.0
    cache_key: Optional[CacheKey] = None
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    version: Optional[str] = None
    checksum: str = ""
    loaded_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    attributes: Dict[str, Any] = field(default_factory=dict)
    symbol_table: Dict[str, Any] = field(default_factory=dict)

    def record_access(self) -> None:
        """
        Record a module access, updating counters.
        """
        self.access_count += 1
        self.last_accessed = time.time()

    def add_dependent(self, module_name: str) -> None:
        """
        Add a dependent module.

        Parameters
        ----------
        module_name : str
            Name of module that depends on this one.
        """
        if module_name not in self.dependents:
            self.dependents.append(module_name)

    def remove_dependent(self, module_name: str) -> None:
        """
        Remove a dependent module.

        Parameters
        ----------
        module_name : str
            Name of dependent module to remove.
        """
        if module_name in self.dependents:
            self.dependents.remove(module_name)

    def get_age_seconds(self) -> float:
        """
        Get age of the loaded module in seconds.

        Returns
        -------
        float
            Age in seconds.
        """
        return time.time() - self.loaded_at

    def is_stale(self, source_modification_time: Optional[float] = None) -> bool:
        """
        Check if module is stale (source file modified after load).

        Parameters
        ----------
        source_modification_time : Optional[float]
            Modification timestamp of source file.

        Returns
        -------
        bool
            True if module is stale.
        """
        if not self.source_path.exists():
            return True

        mtime = source_modification_time or self.source_path.stat().st_mtime
        return mtime > self.loaded_at

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "name": self.name,
            "source_path": str(self.source_path),
            "library_path": str(self.library_path),
            "origin": self.origin.value,
            "load_time": self.load_time,
            "compile_time": self.compile_time,
            "cache_key": self.cache_key.generate() if self.cache_key else None,
            "dependencies": self.dependencies,
            "dependents": self.dependents,
            "version": self.version,
            "checksum": self.checksum,
            "loaded_at": self.loaded_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "attributes": self.attributes,
        }


@dataclass
class LoaderConfig:
    """
    Configuration for module loaders.

    Parameters
    ----------
    cache_enabled : bool
        Whether caching is enabled.
    cache_strategy : CacheStrategy
        Caching strategy.
    parallel_strategy : ParallelStrategy
        Parallel compilation strategy.
    auto_reload : bool
        Whether to automatically reload stale modules.
    lazy_load : bool
        Whether to lazy-load dependencies.
    isolate_modules : bool
        Whether to isolate modules in separate namespaces.
    track_dependencies : bool
        Whether to track module dependencies.
    enable_hot_reload : bool
        Whether hot reloading is enabled.
    log_level : LogLevel
        Logging verbosity level.
    timeout_load : Optional[float]
        Timeout for module loading in seconds.
    retry_count : int
        Number of retries for failed operations.
    retry_delay : float
        Delay between retries in seconds.
    max_modules_in_memory : Optional[int]
        Maximum number of modules to keep loaded.
    unload_policy : str
        Policy for unloading modules ('lru', 'lfu', 'fifo', 'never').
    sandbox_policy : SandboxPolicy
        Sandboxing policy.
    custom_cache_dir : Optional[Path]
        Custom cache directory.
    environment_vars : Dict[str, str]
        Environment variables for compilation/loading.
    callbacks : Dict[LoaderEventType, List[Callable]]
        Event callbacks.

    Attributes
    ----------
    cache_enabled : bool
        Cache enabled flag.
    cache_strategy : CacheStrategy
        Cache strategy.
    parallel_strategy : ParallelStrategy
        Parallel strategy.
    auto_reload : bool
        Auto-reload flag.
    lazy_load : bool
        Lazy load flag.
    isolate_modules : bool
        Module isolation flag.
    track_dependencies : bool
        Dependency tracking flag.
    enable_hot_reload : bool
        Hot reload flag.
    log_level : LogLevel
        Log level.
    timeout_load : Optional[float]
        Load timeout.
    retry_count : int
        Retry count.
    retry_delay : float
        Retry delay.
    max_modules_in_memory : Optional[int]
        Max modules limit.
    unload_policy : str
        Unload policy.
    sandbox_policy : SandboxPolicy
        Sandbox policy.
    custom_cache_dir : Optional[Path]
        Custom cache directory.
    environment_vars : Dict[str, str]
        Environment variables.
    callbacks : Dict[LoaderEventType, List[Callable]]
        Event callbacks.
    """

    # Cache settings
    cache_enabled: bool = True
    cache_strategy: CacheStrategy = CacheStrategy.NORMAL
    custom_cache_dir: Optional[Path] = None

    # Loading settings
    auto_reload: bool = False
    lazy_load: bool = False
    isolate_modules: bool = False
    track_dependencies: bool = True
    enable_hot_reload: bool = False

    # Parallel settings
    parallel_strategy: ParallelStrategy = ParallelStrategy.AUTO

    # Performance settings
    timeout_load: Optional[float] = 30.0
    retry_count: int = 3
    retry_delay: float = 1.0

    # Memory management
    max_modules_in_memory: Optional[int] = 100
    unload_policy: str = "lru"

    # Security settings
    sandbox_policy: SandboxPolicy = SandboxPolicy.BASIC

    # Logging
    log_level: LogLevel = LogLevel.INFO

    # Environment
    environment_vars: Dict[str, str] = field(default_factory=dict)

    # Callbacks
    callbacks: Dict[LoaderEventType, List[Callable]] = field(default_factory=dict)

    def add_callback(self, event_type: LoaderEventType, callback: Callable) -> None:
        """
        Add an event callback.

        Parameters
        ----------
        event_type : LoaderEventType
            Event type to listen for.
        callback : Callable
            Callback function taking a LoaderEvent.
        """
        if event_type not in self.callbacks:
            self.callbacks[event_type] = []
        self.callbacks[event_type].append(callback)

    def remove_callback(self, event_type: LoaderEventType, callback: Callable) -> bool:
        """
        Remove an event callback.

        Parameters
        ----------
        event_type : LoaderEventType
            Event type.
        callback : Callable
            Callback to remove.

        Returns
        -------
        bool
            True if callback was removed.
        """
        if event_type in self.callbacks:
            try:
                self.callbacks[event_type].remove(callback)
                return True
            except ValueError:
                pass
        return False

    def trigger_event(self, event: LoaderEvent) -> None:
        """
        Trigger callbacks for an event.

        Parameters
        ----------
        event : LoaderEvent
            Event to trigger.
        """
        callbacks = self.callbacks.get(event.event_type, [])
        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                # Log but don't propagate callback errors
                import logging
                logging.getLogger(__name__).debug(
                    f"Callback error for {event.event_type}: {e}"
                )

    def validate(self) -> List[str]:
        """
        Validate configuration settings.

        Returns
        -------
        List[str]
            List of validation warnings (empty if valid).
        """
        warnings = []

        if self.unload_policy not in ("lru", "lfu", "fifo", "never"):
            warnings.append(f"Invalid unload_policy: {self.unload_policy}")

        if self.timeout_load is not None and self.timeout_load <= 0:
            warnings.append("timeout_load must be positive")

        if self.retry_count < 0:
            warnings.append("retry_count cannot be negative")

        if self.retry_delay < 0:
            warnings.append("retry_delay cannot be negative")

        return warnings


class BaseLoader(ABC):
    """
    Abstract base class for all module loaders.

    This class defines the interface and common functionality for
    loading compiled modules (C/C++ extensions, Cython modules) with
    support for caching, dependency tracking, hot reloading, and
    parallel compilation.

    Parameters
    ----------
    config : Optional[LoaderConfig]
        Loader configuration. If None, default config is used.
    cache_manager : Optional[CacheManager]
        Cache manager instance. If None, created from config.

    Attributes
    ----------
    config : LoaderConfig
        Loader configuration.
    cache_manager : CacheManager
        Cache manager.
    state : LoaderState
        Current loader state.
    _loaded_modules : Dict[str, ModuleType]
        Dictionary of loaded modules.
    _module_metadata : Dict[str, ModuleMetadata]
        Metadata for loaded modules.
    _dependency_graph : Dict[str, Set[str]]
        Module dependency graph.
    _reverse_dependency_graph : Dict[str, Set[str]]
        Reverse dependency graph.
    _state_lock : threading.RLock
        Thread lock for state changes.
    _module_lock : threading.RLock
        Thread lock for module operations.
    _weak_refs : Dict[str, weakref.ref]
        Weak references to modules for cleanup.
    _stats : Dict[str, Any]
        Loader statistics.

    Examples
    --------
    >>> config = LoaderConfig(
    ...     cache_enabled=True,
    ...     auto_reload=True,
    ...     track_dependencies=True
    ... )
    >>> loader = CLoader(config=config)
    >>> module = loader.load("my_extension.c")
    >>> loader.get_stats()
    """

    def __init__(
        self,
        config: Optional[LoaderConfig] = None,
        cache_manager: Optional[CacheManager] = None,
    ):
        self.config = config or LoaderConfig()
        self.state = LoaderState.UNINITIALIZED
        self._state_lock = threading.RLock()
        self._module_lock = threading.RLock()

        # Module storage
        self._loaded_modules: Dict[str, ModuleType] = {}
        self._module_metadata: Dict[str, ModuleMetadata] = {}
        self._weak_refs: Dict[str, weakref.ref] = {}

        # Dependency tracking
        self._dependency_graph: Dict[str, Set[str]] = {}
        self._reverse_dependency_graph: Dict[str, Set[str]] = {}

        # Cache management
        self.cache_manager = cache_manager
        if not self.cache_manager and self.config.cache_enabled:
            self.cache_manager = CacheManager(
                cache_dir=self.config.custom_cache_dir,
                strategy=self.config.cache_strategy,
            )

        # Statistics
        self._stats: Dict[str, Any] = {
            "total_loads": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "compile_count": 0,
            "total_compile_time": 0.0,
            "total_load_time": 0.0,
            "reload_count": 0,
            "error_count": 0,
            "bytes_loaded": 0,
        }

        # Initialize state
        self._set_state(LoaderState.INITIALIZED)

    def _set_state(self, new_state: LoaderState) -> None:
        """
        Change loader state with locking.

        Parameters
        ----------
        new_state : LoaderState
            New state to transition to.
        """
        with self._state_lock:
            old_state = self.state
            self.state = new_state

            # Trigger state change event
            self._trigger_event(
                LoaderEventType.STATE_CHANGED,
                "",
                data={
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                },
            )

    def _check_state(self, *allowed_states: LoaderState) -> bool:
        """
        Check if current state is allowed.

        Parameters
        ----------
        *allowed_states : LoaderState
            Allowed states.

        Returns
        -------
        bool
            True if current state is allowed.

        Raises
        ------
        CImporterBaseException
            If state is not allowed.
        """
        if self.state in allowed_states:
            return True

        raise CImporterBaseException(
            message=f"Invalid state: {self.state.value}, expected one of {[s.value for s in allowed_states]}",
            category=ErrorCategory.CONFIGURATION_ERROR,
            severity=ErrorSeverity.ERROR,
            context={"current_state": self.state.value},
        )

    def _trigger_event(
        self,
        event_type: LoaderEventType,
        module_name: str,
        data: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
    ) -> None:
        """
        Trigger an event to registered callbacks.

        Parameters
        ----------
        event_type : LoaderEventType
            Type of event.
        module_name : str
            Module name involved.
        data : Optional[Dict[str, Any]]
            Additional event data.
        error : Optional[Exception]
            Error if applicable.
        """
        event = LoaderEvent(
            event_type=event_type,
            module_name=module_name,
            data=data or {},
            error=error,
        )
        self.config.trigger_event(event)

    @abstractmethod
    def load(self, source: Union[str, Path], **kwargs) -> ModuleType:
        """
        Load a module from source.

        Parameters
        ----------
        source : Union[str, Path]
            Path to source file.
        **kwargs : Any
            Additional loading options.

        Returns
        -------
        ModuleType
            Loaded Python module.

        Raises
        ------
        ImportModuleError
            If loading fails.
        """
        pass

    @abstractmethod
    def unload(self, module_name: str) -> bool:
        """
        Unload a previously loaded module.

        Parameters
        ----------
        module_name : str
            Name of module to unload.

        Returns
        -------
        bool
            True if unloaded successfully.
        """
        pass

    @abstractmethod
    def reload(self, module_name: str) -> ModuleType:
        """
        Reload a module.

        Parameters
        ----------
        module_name : str
            Name of module to reload.

        Returns
        -------
        ModuleType
            Reloaded module.
        """
        pass

    @abstractmethod
    def is_loaded(self, module_name: str) -> bool:
        """
        Check if a module is currently loaded.

        Parameters
        ----------
        module_name : str
            Module name to check.

        Returns
        -------
        bool
            True if module is loaded.
        """
        pass

    @abstractmethod
    def get_metadata(self, module_name: str) -> Optional[ModuleMetadata]:
        """
        Get metadata for a loaded module.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        Optional[ModuleMetadata]
            Module metadata or None if not loaded.
        """
        pass

    def get_module(self, module_name: str) -> Optional[ModuleType]:
        """
        Get a reference to a loaded module.

        Parameters
        ----------
        module_name : str
            Name of module to retrieve.

        Returns
        -------
        Optional[ModuleType]
            Module object or None if not loaded.
        """
        with self._module_lock:
            module = self._loaded_modules.get(module_name)

            if module and self.config.track_dependencies:
                metadata = self._module_metadata.get(module_name)
                if metadata:
                    metadata.record_access()

            return module

    def list_loaded_modules(self) -> List[str]:
        """
        List all currently loaded module names.

        Returns
        -------
        List[str]
            List of module names.
        """
        with self._module_lock:
            return list(self._loaded_modules.keys())

    def add_dependency(self, module_name: str, dependency_name: str) -> None:
        """
        Register a dependency relationship between modules.

        Parameters
        ----------
        module_name : str
            Module that has the dependency.
        dependency_name : str
            Module that is depended upon.
        """
        with self._module_lock:
            if module_name not in self._dependency_graph:
                self._dependency_graph[module_name] = set()
            self._dependency_graph[module_name].add(dependency_name)

            if dependency_name not in self._reverse_dependency_graph:
                self._reverse_dependency_graph[dependency_name] = set()
            self._reverse_dependency_graph[dependency_name].add(module_name)

            # Update metadata
            if module_name in self._module_metadata:
                if dependency_name not in self._module_metadata[module_name].dependencies:
                    self._module_metadata[module_name].dependencies.append(dependency_name)

            if dependency_name in self._module_metadata:
                if module_name not in self._module_metadata[dependency_name].dependents:
                    self._module_metadata[dependency_name].dependents.append(module_name)

    def get_dependencies(self, module_name: str) -> List[str]:
        """
        Get all dependencies of a module.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        List[str]
            List of dependency module names.
        """
        with self._module_lock:
            return list(self._dependency_graph.get(module_name, set()))

    def get_dependents(self, module_name: str) -> List[str]:
        """
        Get all modules that depend on this module.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        List[str]
            List of dependent module names.
        """
        with self._module_lock:
            return list(self._reverse_dependency_graph.get(module_name, set()))

    def get_dependency_tree(self, module_name: str, depth: int = -1) -> Dict[str, Any]:
        """
        Get the dependency tree for a module.

        Parameters
        ----------
        module_name : str
            Root module name.
        depth : int, optional
            Maximum depth to traverse (-1 for unlimited).

        Returns
        -------
        Dict[str, Any]
            Tree structure of dependencies.
        """
        visited: Set[str] = set()

        def _build_tree(name: str, current_depth: int) -> Dict[str, Any]:
            if name in visited:
                return {"name": name, "circular": True}
            if depth >= 0 and current_depth >= depth:
                return {"name": name, "truncated": True}

            visited.add(name)
            deps = self.get_dependencies(name)

            tree: Dict[str, Any] = {
                "name": name,
                "loaded": self.is_loaded(name),
                "dependencies": [
                    _build_tree(dep, current_depth + 1) for dep in deps
                ],
            }

            if name in self._module_metadata:
                metadata = self._module_metadata[name]
                tree["metadata"] = {
                    "origin": metadata.origin.value,
                    "load_time": metadata.load_time,
                    "compile_time": metadata.compile_time,
                }

            return tree

        with self._module_lock:
            return _build_tree(module_name, 0)

    def find_circular_dependencies(self) -> List[List[str]]:
        """
        Find all circular dependencies in the dependency graph.

        Returns
        -------
        List[List[str]]
            List of circular dependency chains.
        """
        circular_chains: List[List[str]] = []
        visited: Set[str] = set()
        stack: List[str] = []

        def _dfs(node: str) -> None:
            if node in stack:
                # Found a cycle
                cycle_start = stack.index(node)
                circular_chains.append(stack[cycle_start:] + [node])
                return

            if node in visited:
                return

            visited.add(node)
            stack.append(node)

            for dep in self._dependency_graph.get(node, set()):
                _dfs(dep)

            stack.pop()

        with self._module_lock:
            for module in self._dependency_graph:
                _dfs(module)

        return circular_chains

    def _validate_dependencies(self, module_name: str) -> Tuple[List[str], List[List[str]]]:
        """
        Validate dependencies for a module.

        Parameters
        ----------
        module_name : str
            Module to validate.

        Returns
        -------
        Tuple[List[str], List[List[str]]]
            Tuple of (missing_deps, circular_chains).
        """
        missing: List[str] = []
        circular: List[List[str]] = []

        # Check for missing dependencies
        for dep in self.get_dependencies(module_name):
            if not self.is_loaded(dep) and not self._can_load(dep):
                missing.append(dep)

        # Check for circular dependencies
        circular = self.find_circular_dependencies()

        return missing, circular

    def _can_load(self, module_name: str) -> bool:
        """
        Check if a module can potentially be loaded.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        bool
            True if module can be loaded.
        """
        # Override in subclasses
        return True

    def _register_module(
        self,
        name: str,
        module: ModuleType,
        metadata: ModuleMetadata,
    ) -> None:
        """
        Register a loaded module.

        Parameters
        ----------
        name : str
            Module name.
        module : ModuleType
            Module object.
        metadata : ModuleMetadata
            Module metadata.
        """
        with self._module_lock:
            self._loaded_modules[name] = module
            self._module_metadata[name] = metadata

            # Create weak reference for cleanup
            self._weak_refs[name] = weakref.ref(
                module, lambda ref: self._on_module_collected(name)
            )

            # Update stats
            self._stats["total_loads"] += 1
            if metadata.origin == ModuleOrigin.CACHE:
                self._stats["cache_hits"] += 1
            else:
                self._stats["cache_misses"] += 1

            if metadata.compile_time > 0:
                self._stats["compile_count"] += 1
                self._stats["total_compile_time"] += metadata.compile_time

            self._stats["total_load_time"] += metadata.load_time

            try:
                if metadata.library_path.exists():
                    self._stats["bytes_loaded"] += metadata.library_path.stat().st_size
            except OSError:
                pass

            # Check module limit
            if self.config.max_modules_in_memory:
                self._enforce_module_limit()

    def _unregister_module(self, name: str) -> bool:
        """
        Unregister a module.

        Parameters
        ----------
        name : str
            Module name.

        Returns
        -------
        bool
            True if module was unregistered.
        """
        with self._module_lock:
            removed = False

            if name in self._loaded_modules:
                del self._loaded_modules[name]
                removed = True

            if name in self._module_metadata:
                del self._module_metadata[name]

            if name in self._weak_refs:
                del self._weak_refs[name]

            # Clean up dependency graph
            if name in self._dependency_graph:
                # Remove from reverse dependencies
                for dep in self._dependency_graph[name]:
                    if dep in self._reverse_dependency_graph:
                        self._reverse_dependency_graph[dep].discard(name)
                del self._dependency_graph[name]

            # Remove as dependent from other modules
            for deps in self._dependency_graph.values():
                deps.discard(name)

            return removed

    def _on_module_collected(self, name: str) -> None:
        """
        Callback when a module is garbage collected.

        Parameters
        ----------
        name : str
            Module name.
        """
        self._unregister_module(name)

    def _enforce_module_limit(self) -> None:
        """
        Enforce maximum number of loaded modules.
        """
        if not self.config.max_modules_in_memory:
            return

        with self._module_lock:
            current_count = len(self._loaded_modules)
            if current_count <= self.config.max_modules_in_memory:
                return

            excess = current_count - self.config.max_modules_in_memory

            # Sort modules by policy
            if self.config.unload_policy == "lru":
                # Least Recently Used
                sorted_modules = sorted(
                    self._module_metadata.items(),
                    key=lambda x: x[1].last_accessed,
                )
            elif self.config.unload_policy == "lfu":
                # Least Frequently Used
                sorted_modules = sorted(
                    self._module_metadata.items(),
                    key=lambda x: x[1].access_count,
                )
            elif self.config.unload_policy == "fifo":
                # First In First Out
                sorted_modules = sorted(
                    self._module_metadata.items(),
                    key=lambda x: x[1].loaded_at,
                )
            else:
                return

            # Unload excess modules (skip those with dependents)
            unloaded = 0
            for name, metadata in sorted_modules:
                if unloaded >= excess:
                    break

                # Don't unload if other modules depend on it
                if self.get_dependents(name):
                    continue

                try:
                    if self.unload(name):
                        unloaded += 1
                except Exception:
                    pass

    def get_stats(self) -> Dict[str, Any]:
        """
        Get loader statistics.

        Returns
        -------
        Dict[str, Any]
            Dictionary of statistics.
        """
        with self._module_lock:
            stats = self._stats.copy()
            stats["loaded_modules_count"] = len(self._loaded_modules)
            stats["dependency_graph_size"] = len(self._dependency_graph)
            stats["circular_dependencies"] = len(self.find_circular_dependencies())
            stats["state"] = self.state.value

            if self._stats["total_loads"] > 0:
                stats["cache_hit_rate"] = (
                    self._stats["cache_hits"] / self._stats["total_loads"]
                )
            else:
                stats["cache_hit_rate"] = 0.0

            if self._stats["compile_count"] > 0:
                stats["avg_compile_time"] = (
                    self._stats["total_compile_time"] / self._stats["compile_count"]
                )
            else:
                stats["avg_compile_time"] = 0.0

            if stats["loaded_modules_count"] > 0:
                stats["avg_load_time"] = (
                    self._stats["total_load_time"] / stats["loaded_modules_count"]
                )
            else:
                stats["avg_load_time"] = 0.0

            # Cache stats
            if self.cache_manager:
                stats["cache"] = self.cache_manager.get_stats()

            return stats

    def clear_cache(self) -> int:
        """
        Clear the compilation cache.

        Returns
        -------
        int
            Number of items removed.
        """
        if self.cache_manager:
            return self.cache_manager.clear()
        return 0

    def preload_dependencies(self, module_name: str) -> List[str]:
        """
        Preload all dependencies for a module.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        List[str]
            List of dependencies that were loaded.
        """
        loaded: List[str] = []
        deps = self.get_dependencies(module_name)

        for dep in deps:
            if not self.is_loaded(dep):
                try:
                    self.load(dep)
                    loaded.append(dep)
                except Exception:
                    pass

        return loaded

    def invalidate(self, module_name: str) -> bool:
        """
        Invalidate a loaded module (mark for reload).

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        bool
            True if invalidated.
        """
        with self._module_lock:
            if module_name in self._module_metadata:
                metadata = self._module_metadata[module_name]
                # Mark as needing reload by setting loaded_at to 0
                metadata.loaded_at = 0
                return True
        return False

    def invalidate_dependents(self, module_name: str) -> List[str]:
        """
        Invalidate all modules that depend on this module.

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        List[str]
            List of invalidated module names.
        """
        invalidated: List[str] = []
        dependents = self.get_dependents(module_name)

        for dep in dependents:
            if self.invalidate(dep):
                invalidated.append(dep)
                # Recursively invalidate
                invalidated.extend(self.invalidate_dependents(dep))

        return invalidated

    def __contains__(self, module_name: str) -> bool:
        """
        Check if a module is loaded (supports 'in' operator).

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        bool
            True if module is loaded.
        """
        return self.is_loaded(module_name)

    def __getitem__(self, module_name: str) -> ModuleType:
        """
        Get a loaded module (supports dict-like access).

        Parameters
        ----------
        module_name : str
            Module name.

        Returns
        -------
        ModuleType
            Module object.

        Raises
        ------
        KeyError
            If module is not loaded.
        """
        module = self.get_module(module_name)
        if module is None:
            raise KeyError(f"Module '{module_name}' is not loaded")
        return module

    def __len__(self) -> int:
        """
        Get number of loaded modules.

        Returns
        -------
        int
            Number of loaded modules.
        """
        return len(self._loaded_modules)

    def __iter__(self):
        """
        Iterate over loaded module names.

        Returns
        -------
        Iterator[str]
            Iterator of module names.
        """
        return iter(self._loaded_modules.keys())

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"state={self.state.value} "
            f"modules={len(self._loaded_modules)} "
            f"cache={'enabled' if self.config.cache_enabled else 'disabled'}>"
        )

    def close(self) -> None:
        """
        Close the loader and release resources.
        """
        if self.state == LoaderState.DESTROYED:
            return

        # Unload all modules
        for name in list(self._loaded_modules.keys()):
            try:
                self.unload(name)
            except Exception:
                pass

        self._set_state(LoaderState.DESTROYED)

    def __enter__(self):
        """
        Context manager entry.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Context manager exit.
        """
        self.close()
        return False


class ModuleProxy:
    """
    Proxy object for lazy-loaded modules.

    This class provides lazy loading capabilities, deferring actual
    module loading until an attribute is accessed.

    Parameters
    ----------
    loader : BaseLoader
        Loader instance to use.
    module_name : str
        Name of module to load.
    source_path : Path
        Path to source file.

    Attributes
    ----------
    _loader : BaseLoader
        Loader reference.
    _module_name : str
        Module name.
    _source_path : Path
        Source path.
    _module : Optional[ModuleType]
        Cached module reference.
    _loading : bool
        Whether currently loading.
    _lock : threading.RLock
        Thread lock.

    Examples
    --------
    >>> proxy = ModuleProxy(loader, "my_module", Path("my_module.c"))
    >>> result = proxy.some_function()  # Loads on first access
    """

    def __init__(self, loader: BaseLoader, module_name: str, source_path: Path):
        self._loader = loader
        self._module_name = module_name
        self._source_path = source_path
        self._module: Optional[ModuleType] = None
        self._loading = False
        self._lock = threading.RLock()

    def _ensure_loaded(self) -> ModuleType:
        """
        Ensure the module is loaded.

        Returns
        -------
        ModuleType
            Loaded module.

        Raises
        ------
        ImportModuleError
            If loading fails.
        """
        with self._lock:
            if self._module is not None:
                return self._module

            if self._loading:
                # Prevent recursive loading
                raise ImportModuleError(
                    module_name=self._module_name,
                    library_path=self._source_path,
                    message="Circular dependency detected during lazy loading",
                )

            self._loading = True
            try:
                self._module = self._loader.load(self._source_path)
                return self._module
            finally:
                self._loading = False

    def __getattr__(self, name: str) -> Any:
        """
        Proxy attribute access to the loaded module.

        Parameters
        ----------
        name : str
            Attribute name.

        Returns
        -------
        Any
            Attribute value.
        """
        module = self._ensure_loaded()
        return getattr(module, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """
        Proxy attribute setting to the loaded module.

        Parameters
        ----------
        name : str
            Attribute name.
        value : Any
            Attribute value.
        """
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            module = self._ensure_loaded()
            setattr(module, name, value)

    def __call__(self, *args, **kwargs) -> Any:
        """
        Allow the proxy to be called if the module is callable.

        Parameters
        ----------
        *args : Any
            Positional arguments.
        **kwargs : Any
            Keyword arguments.

        Returns
        -------
        Any
            Call result.
        """
        module = self._ensure_loaded()
        return module(*args, **kwargs)

    def __repr__(self) -> str:
        if self._module is not None:
            return f"<ModuleProxy loaded={self._module_name}>"
        return f"<ModuleProxy pending={self._module_name}>"


class BatchLoader:
    """
    Batch loader for loading multiple modules in parallel.

    This class provides efficient batch loading of multiple modules
    with dependency resolution and parallel compilation.

    Parameters
    ----------
    loader : BaseLoader
        Loader instance to use.
    parallel_strategy : Optional[ParallelStrategy]
        Parallel strategy override.

    Attributes
    ----------
    loader : BaseLoader
        Loader instance.
    parallel_strategy : ParallelStrategy
        Parallel strategy.
    _executor : Optional[Any]
        Parallel executor.
    _results : Dict[str, Any]
        Batch results.

    Examples
    --------
    >>> batch = BatchLoader(loader, ParallelStrategy.PROCESSES)
    >>> results = batch.load(["module1.c", "module2.c", "module3.c"])
    >>> for name, result in results.items():
    ...     if result.success:
    ...         print(f"{name} loaded in {result.time}s")
    """

    @dataclass
    class BatchResult:
        """
        Result of a single module load in a batch.

        Attributes
        ----------
        name : str
            Module name.
        success : bool
            Whether loading succeeded.
        module : Optional[ModuleType]
            Loaded module if successful.
        error : Optional[Exception]
            Error if failed.
        time : float
            Time taken in seconds.
        cached : bool
            Whether loaded from cache.
        """

        name: str
        success: bool
        module: Optional[ModuleType] = None
        error: Optional[Exception] = None
        time: float = 0.0
        cached: bool = False

    def __init__(
        self,
        loader: BaseLoader,
        parallel_strategy: Optional[ParallelStrategy] = None,
    ):
        self.loader = loader
        self.parallel_strategy = parallel_strategy or loader.config.parallel_strategy
        self._executor = None
        self._results: Dict[str, "BatchLoader.BatchResult"] = {}

    def _get_executor(self):
        """
        Get or create the parallel executor.

        Returns
        -------
        Executor
            Parallel executor instance.
        """
        if self._executor is None:
            executor_class = self.parallel_strategy.get_executor_class()
            worker_count = self.parallel_strategy.get_worker_count()
            self._executor = executor_class(max_workers=worker_count)
        return self._executor

    def load(
        self,
        sources: List[Union[str, Path]],
        resolve_dependencies: bool = True,
        continue_on_error: bool = True,
    ) -> Dict[str, "BatchLoader.BatchResult"]:
        """
        Load multiple modules in parallel.

        Parameters
        ----------
        sources : List[Union[str, Path]]
            List of source file paths.
        resolve_dependencies : bool, optional
            Whether to resolve and load dependencies first.
        continue_on_error : bool, optional
            Whether to continue after individual failures.

        Returns
        -------
        Dict[str, BatchResult]
            Dictionary mapping module names to results.
        """
        from concurrent.futures import as_completed

        # Build dependency graph if needed
        if resolve_dependencies:
            sources = self._resolve_load_order(sources)

        results: Dict[str, "BatchLoader.BatchResult"] = {}
        executor = self._get_executor()

        # Submit all loads
        futures = {}
        for source in sources:
            source_path = Path(source)
            name = source_path.stem
            future = executor.submit(self._load_one, source_path)
            futures[future] = name

        # Collect results
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result(timeout=self.loader.config.timeout_load)
                results[name] = result
            except Exception as e:
                if not continue_on_error:
                    # Cancel remaining futures
                    for f in futures:
                        f.cancel()
                    raise

                results[name] = self.BatchResult(
                    name=name,
                    success=False,
                    error=e,
                )

        self._results.update(results)
        return results

    def _resolve_load_order(self, sources: List[Union[str, Path]]) -> List[Path]:
        """
        Resolve load order based on dependencies.

        Parameters
        ----------
        sources : List[Union[str, Path]]
            Source files.

        Returns
        -------
        List[Path]
            Ordered list of source paths.
        """
        # Build dependency graph for all sources
        graph: Dict[str, Set[str]] = {}
        source_paths: Dict[str, Path] = {}

        for source in sources:
            path = Path(source)
            name = path.stem
            source_paths[name] = path
            # Parse dependencies from source file
            deps = self._parse_dependencies(path)
            graph[name] = deps

        # Topological sort
        visited: Set[str] = set()
        temp_mark: Set[str] = set()
        order: List[str] = []

        def visit(node: str) -> None:
            if node in temp_mark:
                # Circular dependency detected
                return
            if node in visited:
                return

            temp_mark.add(node)
            for dep in graph.get(node, set()):
                if dep in source_paths:  # Only include dependencies in the batch
                    visit(dep)
            temp_mark.remove(node)
            visited.add(node)
            order.append(node)

        for name in source_paths:
            if name not in visited:
                visit(name)

        return [source_paths[name] for name in order]

    def _parse_dependencies(self, source_path: Path) -> Set[str]:
        """
        Parse dependencies from a source file.

        Parameters
        ----------
        source_path : Path
            Source file path.

        Returns
        -------
        Set[str]
            Set of dependency module names.
        """
        # Basic implementation - override in subclasses
        deps: Set[str] = set()

        if not source_path.exists():
            return deps

        try:
            with open(source_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Look for import/include patterns
            import re

            # C/C++ includes
            include_pattern = re.compile(r'#include\s+[<"]([^>"]+)[>"]')
            for match in include_pattern.finditer(content):
                header = match.group(1)
                # Extract module name from header
                name = Path(header).stem
                deps.add(name)

            # Python/Cython imports
            import_pattern = re.compile(r"(?:c?import|from)\s+(\w+)", re.IGNORECASE)
            for match in import_pattern.finditer(content):
                deps.add(match.group(1))

        except Exception:
            pass

        return deps

    def _load_one(self, source_path: Path) -> "BatchLoader.BatchResult":
        """
        Load a single module (for parallel execution).

        Parameters
        ----------
        source_path : Path
            Source file path.

        Returns
        -------
        BatchResult
            Loading result.
        """
        import time

        name = source_path.stem
        start_time = time.time()

        try:
            # Check cache first
            cached = False
            if self.loader.cache_manager:
                # Check if already cached
                pass  # Implement cache check

            module = self.loader.load(source_path)
            elapsed = time.time() - start_time

            return self.BatchResult(
                name=name,
                success=True,
                module=module,
                time=elapsed,
                cached=cached,
            )
        except Exception as e:
            elapsed = time.time() - start_time
            return self.BatchResult(
                name=name,
                success=False,
                error=e,
                time=elapsed,
            )

    def get_result(self, name: str) -> Optional["BatchLoader.BatchResult"]:
        """
        Get result for a specific module.

        Parameters
        ----------
        name : str
            Module name.

        Returns
        -------
        Optional[BatchResult]
            Batch result or None.
        """
        return self._results.get(name)

    def get_successful(self) -> List[str]:
        """
        Get list of successfully loaded module names.

        Returns
        -------
        List[str]
            List of module names.
        """
        return [name for name, result in self._results.items() if result.success]

    def get_failed(self) -> Dict[str, Exception]:
        """
        Get failed modules and their errors.

        Returns
        -------
        Dict[str, Exception]
            Dictionary of module names to errors.
        """
        return {
            name: result.error
            for name, result in self._results.items()
            if not result.success and result.error is not None
        }

    def close(self) -> None:
        """
        Close the batch loader and release resources.
        """
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._results.clear()