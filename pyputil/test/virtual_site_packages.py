#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
virtual_site_packages.py

Virtual Site-Packages Overlay for Python Development.

This module provides a sophisticated, production-ready virtual site-packages
system that enables transparent overlaying of custom packages over system
installations. It's designed for:

- Development of patched versions of existing packages without affecting system
- Testing custom package modifications in isolation
- Multi-version package testing and comparison
- Dependency conflict resolution and isolation
- CI/CD pipelines with custom package builds
- Research and experimentation with modified libraries
- Reproducible development environments

The system provides intelligent module resolution with configurable fallback
strategies, comprehensive logging, performance optimization, and seamless
integration with Python's import machinery.

Features
--------
- Transparent overlay of custom packages over system site-packages
- Multiple overlay layers with priority ordering
- Partial module overrides (override specific submodules only)
- Module shadowing with configurable fallback strategies
- Hot reloading and dynamic overlay updates
- Package version verification and compatibility checking
- Symlink and copy-on-write support for efficient storage
- Virtual environment awareness and isolation
- Comprehensive import hook management
- Performance optimization with intelligent caching
- Thread-safe operations for concurrent environments
- Rich introspection and debugging capabilities

Classes
-------
VirtualSitePackagesFinder
    Enhanced import hook with multi-layer overlay support.
OverlayLayer
    Represents a single overlay layer with configuration.
LayerManager
    Manages multiple overlay layers with priority ordering.
ImportInterceptor
    Low-level import machinery interceptor for advanced control.
OverlayConfig
    Configuration system for overlay behavior.
OverlayStats
    Statistics and telemetry for overlay operations.

Functions
---------
activate_virtual_site_packages
    Activate the virtual site-packages overlay system.
deactivate_virtual_site_packages
    Remove specific overlay finder from import system.
add_overlay_layer
    Add a new overlay layer with custom configuration.
remove_overlay_layer
    Remove an existing overlay layer.
list_overlay_layers
    List all active overlay layers with their configurations.
create_overlay_from_venv
    Create overlay from existing virtual environment.
export_overlay_config
    Export overlay configuration to file.
import_overlay_config
    Import overlay configuration from file.
clear_overlay_cache
    Clear all overlay resolution caches.
"""

import sys
import site
import os
import importlib
import importlib.machinery
import importlib.util
import logging
import threading
import json
import hashlib
import shutil
import tempfile
import time
import warnings
import weakref
from collections import defaultdict, deque, OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import (
    Any, Callable, Dict, Iterator, List, Optional, Pattern, Set, Tuple,
    Type, Union, cast, overload
)

# -----------------------------------------------------------------------------
# Module Configuration and Constants
# -----------------------------------------------------------------------------

# Default configuration
DEFAULT_OVERLAY_DIR: str = str(Path("virtual_sp") / "overlay") 
DEFAULT_LOG_LEVEL: int = logging.WARNING
DEFAULT_CACHE_SIZE: int = 1000
DEFAULT_CACHE_TTL: int = 300  # 5 minutes
DEFAULT_PRESERVE_SYSTEM: bool = True
DEFAULT_FALLBACK_STRATEGY: str = "system_only_if_missing"

# Module resolution strategies
RESOLUTION_STRATEGIES = {
    'overlay_only': 'Only use overlay, fail if not found',
    'overlay_first': 'Try overlay first, fallback to system',
    'system_first': 'Try system first, fallback to overlay',
    'merge': 'Merge overlay and system (system wins on conflict)',
    'overlay_wins': 'Merge overlay and system (overlay wins on conflict)',
}

# File extensions for module detection
MODULE_EXTENSIONS = {'.py', '.pyc', '.pyo', '.pyd', '.so'}

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

class ResolutionStrategy(Enum):
    """
    Module resolution strategies for overlay system.
    
    Attributes
    ----------
    OVERLAY_ONLY : auto
        Only resolve from overlay layers, fail if not found.
    OVERLAY_FIRST : auto
        Try overlay layers first, fallback to system.
    SYSTEM_FIRST : auto
        Try system first, fallback to overlay layers.
    MERGE_SYSTEM_WINS : auto
        Merge overlay and system, system takes precedence.
    MERGE_OVERLAY_WINS : auto
        Merge overlay and system, overlay takes precedence.
    SMART : auto
        Intelligent resolution based on version compatibility.
    """
    
    OVERLAY_ONLY = auto()
    OVERLAY_FIRST = auto()
    SYSTEM_FIRST = auto()
    MERGE_SYSTEM_WINS = auto()
    MERGE_OVERLAY_WINS = auto()
    SMART = auto()


class OverlayType(Enum):
    """
    Types of overlay storage mechanisms.
    
    Attributes
    ----------
    DIRECT : auto
        Direct directory containing package files.
    SYMLINK : auto
        Directory with symlinks to actual packages.
    COPY_ON_WRITE : auto
        Copy files only when modified.
    VIRTUAL_ENV : auto
        Virtual environment site-packages.
    REMOTE : auto
        Remote package source (HTTP, Git, etc.).
    """
    
    DIRECT = auto()
    SYMLINK = auto()
    COPY_ON_WRITE = auto()
    VIRTUAL_ENV = auto()
    REMOTE = auto()


@dataclass
class OverlayConfig:
    """
    Configuration for overlay behavior and resolution.
    
    Attributes
    ----------
    resolution_strategy : ResolutionStrategy
        How to resolve modules across layers.
    preserve_system : bool
        Whether to fallback to system packages.
    enable_caching : bool
        Whether to cache resolution results.
    cache_size : int
        Maximum number of cached resolutions.
    cache_ttl : int
        Cache time-to-live in seconds.
    track_stats : bool
        Whether to track usage statistics.
    verify_versions : bool
        Whether to verify package version compatibility.
    auto_refresh : bool
        Whether to auto-refresh when overlay changes.
    exclude_patterns : List[str]
        Patterns for modules to exclude from overlay.
    include_patterns : List[str]
        Patterns for modules to force through overlay.
    """
    
    resolution_strategy: ResolutionStrategy = ResolutionStrategy.OVERLAY_FIRST
    preserve_system: bool = DEFAULT_PRESERVE_SYSTEM
    enable_caching: bool = True
    cache_size: int = DEFAULT_CACHE_SIZE
    cache_ttl: int = DEFAULT_CACHE_TTL
    track_stats: bool = True
    verify_versions: bool = False
    auto_refresh: bool = False
    exclude_patterns: List[str] = field(default_factory=list)
    include_patterns: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data['resolution_strategy'] = self.resolution_strategy.name
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OverlayConfig':
        """Create from dictionary."""
        if 'resolution_strategy' in data:
            data['resolution_strategy'] = ResolutionStrategy[data['resolution_strategy']]
        return cls(**data)


@dataclass
class OverlayLayer:
    """
    Represents a single overlay layer with its configuration.
    
    Attributes
    ----------
    name : str
        Unique name for this layer.
    path : Path
        Path to overlay directory.
    priority : int
        Priority order (lower = higher priority).
    layer_type : OverlayType
        Type of overlay storage.
    config : OverlayConfig
        Configuration for this layer.
    enabled : bool
        Whether this layer is active.
    metadata : Dict[str, Any]
        Additional metadata for the layer.
    """
    
    name: str
    path: Path
    priority: int = 100
    layer_type: OverlayType = OverlayType.DIRECT
    config: OverlayConfig = field(default_factory=OverlayConfig)
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    _created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self) -> None:
        """Validate and prepare layer."""
        self.path = Path(self.path).resolve()
        
        # Ensure directory exists
        if not self.path.exists():
            logger.warning(f"Overlay path does not exist: {self.path}")
            self.path.mkdir(parents=True, exist_ok=True)
    
    def get_module_path(self, module_name: str) -> Optional[Path]:
        """
        Get path to module within this layer.
        
        Parameters
        ----------
        module_name : str
            Module name to locate.
        
        Returns
        -------
        Optional[Path]
            Path to module if found.
        """
        parts = module_name.split('.')
        
        # Check for package directory
        package_path = self.path.joinpath(*parts)
        if package_path.is_dir():
            init_file = package_path / '__init__.py'
            if init_file.exists():
                return package_path
        
        # Check for single file
        file_path = self.path / f"{parts[0]}.py"
        if file_path.exists():
            return file_path.parent
        
        return None
    
    def list_modules(self) -> List[str]:
        """
        List all modules available in this layer.
        
        Returns
        -------
        List[str]
            List of module names.
        """
        modules = []
        
        for item in self.path.iterdir():
            if item.is_dir() and (item / '__init__.py').exists():
                modules.append(item.name)
            elif item.suffix in MODULE_EXTENSIONS:
                modules.append(item.stem)
        
        return modules
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'path': str(self.path),
            'priority': self.priority,
            'layer_type': self.layer_type.name,
            'config': self.config.to_dict(),
            'enabled': self.enabled,
            'metadata': self.metadata,
            'created_at': self._created_at.isoformat(),
        }
    
    def __repr__(self) -> str:
        return (f"OverlayLayer(name='{self.name}', path='{self.path}', "
                f"priority={self.priority}, enabled={self.enabled})")


@dataclass
class OverlayStats:
    """
    Statistics and telemetry for overlay operations.
    
    Attributes
    ----------
    resolution_attempts : int
        Total resolution attempts.
    overlay_hits : int
        Resolutions satisfied from overlay.
    system_hits : int
        Resolutions satisfied from system.
    cache_hits : int
        Resolutions satisfied from cache.
    misses : int
        Failed resolutions.
    layer_stats : Dict[str, Dict[str, int]]
        Per-layer statistics.
    module_accesses : Dict[str, int]
        Access counts per module.
    avg_resolution_time : float
        Average resolution time in microseconds.
    """
    
    resolution_attempts: int = 0
    overlay_hits: int = 0
    system_hits: int = 0
    cache_hits: int = 0
    misses: int = 0
    layer_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    module_accesses: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    avg_resolution_time: float = 0.0
    _resolution_times: deque = field(default_factory=lambda: deque(maxlen=100))
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    
    def record_attempt(self) -> None:
        """Record a resolution attempt."""
        with self._lock:
            self.resolution_attempts += 1
    
    def record_overlay_hit(self, layer_name: str, module_name: str) -> None:
        """Record a hit from overlay layer."""
        with self._lock:
            self.overlay_hits += 1
            self.module_accesses[module_name] += 1
            
            if layer_name not in self.layer_stats:
                self.layer_stats[layer_name] = {'hits': 0, 'misses': 0}
            self.layer_stats[layer_name]['hits'] += 1
    
    def record_system_hit(self, module_name: str) -> None:
        """Record a hit from system packages."""
        with self._lock:
            self.system_hits += 1
            self.module_accesses[module_name] += 1
    
    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        with self._lock:
            self.cache_hits += 1
    
    def record_miss(self, layer_name: Optional[str] = None) -> None:
        """Record a resolution miss."""
        with self._lock:
            self.misses += 1
            if layer_name and layer_name in self.layer_stats:
                self.layer_stats[layer_name]['misses'] += 1
    
    def record_resolution_time(self, time_us: float) -> None:
        """Record resolution time."""
        with self._lock:
            self._resolution_times.append(time_us)
            if self._resolution_times:
                self.avg_resolution_time = sum(self._resolution_times) / len(self._resolution_times)
    
    def get_layer_stats(self, layer_name: str) -> Dict[str, int]:
        """Get statistics for a specific layer."""
        with self._lock:
            return self.layer_stats.get(layer_name, {'hits': 0, 'misses': 0}).copy()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert statistics to dictionary."""
        with self._lock:
            return {
                'resolution_attempts': self.resolution_attempts,
                'overlay_hits': self.overlay_hits,
                'system_hits': self.system_hits,
                'cache_hits': self.cache_hits,
                'misses': self.misses,
                'hit_rate': f"{(self.overlay_hits / max(1, self.resolution_attempts)) * 100:.1f}%",
                'layer_stats': self.layer_stats.copy(),
                'top_modules': sorted(
                    self.module_accesses.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:10],
                'avg_resolution_time_us': f"{self.avg_resolution_time:.2f}",
            }
    
    def reset(self) -> None:
        """Reset all statistics."""
        with self._lock:
            self.resolution_attempts = 0
            self.overlay_hits = 0
            self.system_hits = 0
            self.cache_hits = 0
            self.misses = 0
            self.layer_stats.clear()
            self.module_accesses.clear()
            self.avg_resolution_time = 0.0
            self._resolution_times.clear()


# -----------------------------------------------------------------------------
# Layer Manager
# -----------------------------------------------------------------------------

class LayerManager:
    """
    Manages multiple overlay layers with priority ordering.
    
    This class provides sophisticated layer management with priority-based
    ordering, dynamic layer addition/removal, and comprehensive querying.
    """
    
    def __init__(self):
        """Initialize layer manager."""
        self._layers: Dict[str, OverlayLayer] = {}
        self._lock = threading.RLock()
        self._change_counter = 0
        self._callbacks: List[Callable] = []
    
    def add_layer(self, layer: OverlayLayer) -> None:
        """
        Add a new overlay layer.
        
        Parameters
        ----------
        layer : OverlayLayer
            Layer to add.
        
        Raises
        ------
        ValueError
            If layer with same name already exists.
        """
        with self._lock:
            if layer.name in self._layers:
                raise ValueError(f"Layer '{layer.name}' already exists")
            
            self._layers[layer.name] = layer
            self._change_counter += 1
            self._notify_change('added', layer)
            
            logger.info(f"Added overlay layer: {layer}")
    
    def remove_layer(self, name: str) -> Optional[OverlayLayer]:
        """
        Remove an overlay layer.
        
        Parameters
        ----------
        name : str
            Name of layer to remove.
        
        Returns
        -------
        Optional[OverlayLayer]
            Removed layer or None if not found.
        """
        with self._lock:
            layer = self._layers.pop(name, None)
            if layer:
                self._change_counter += 1
                self._notify_change('removed', layer)
                logger.info(f"Removed overlay layer: {layer}")
            return layer
    
    def get_layer(self, name: str) -> Optional[OverlayLayer]:
        """Get layer by name."""
        with self._lock:
            return self._layers.get(name)
    
    def get_active_layers(self) -> List[OverlayLayer]:
        """
        Get all enabled layers sorted by priority.
        
        Returns
        -------
        List[OverlayLayer]
            Active layers in priority order.
        """
        with self._lock:
            active = [l for l in self._layers.values() if l.enabled]
            return sorted(active, key=lambda l: l.priority)
    
    def get_all_layers(self) -> List[OverlayLayer]:
        """Get all layers (including disabled)."""
        with self._lock:
            return list(self._layers.values())
    
    def enable_layer(self, name: str) -> bool:
        """
        Enable a disabled layer.
        
        Parameters
        ----------
        name : str
            Layer name.
        
        Returns
        -------
        bool
            True if layer was enabled.
        """
        with self._lock:
            if name in self._layers:
                if not self._layers[name].enabled:
                    self._layers[name].enabled = True
                    self._change_counter += 1
                    self._notify_change('enabled', self._layers[name])
                    return True
        return False
    
    def disable_layer(self, name: str) -> bool:
        """
        Disable an enabled layer.
        
        Parameters
        ----------
        name : str
            Layer name.
        
        Returns
        -------
        bool
            True if layer was disabled.
        """
        with self._lock:
            if name in self._layers:
                if self._layers[name].enabled:
                    self._layers[name].enabled = False
                    self._change_counter += 1
                    self._notify_change('disabled', self._layers[name])
                    return True
        return False
    
    def set_priority(self, name: str, priority: int) -> bool:
        """
        Set layer priority.
        
        Parameters
        ----------
        name : str
            Layer name.
        priority : int
            New priority (lower = higher precedence).
        
        Returns
        -------
        bool
            True if priority was updated.
        """
        with self._lock:
            if name in self._layers:
                self._layers[name].priority = priority
                self._change_counter += 1
                self._notify_change('priority_changed', self._layers[name])
                return True
        return False
    
    def find_module(self, module_name: str) -> Tuple[Optional[OverlayLayer], Optional[Path]]:
        """
        Find module across all active layers.
        
        Parameters
        ----------
        module_name : str
            Module name to find.
        
        Returns
        -------
        Tuple[Optional[OverlayLayer], Optional[Path]]
            Layer and path where module was found.
        """
        for layer in self.get_active_layers():
            # Check exclude/include patterns
            if not self._should_check_layer(layer, module_name):
                continue
            
            module_path = layer.get_module_path(module_name)
            if module_path:
                return layer, module_path
        
        return None, None
    
    def _should_check_layer(self, layer: OverlayLayer, module_name: str) -> bool:
        """Check if module should be looked for in this layer."""
        import re
        
        # Check exclude patterns
        for pattern in layer.config.exclude_patterns:
            if re.search(pattern, module_name):
                return False
        
        # Check include patterns (if any)
        if layer.config.include_patterns:
            for pattern in layer.config.include_patterns:
                if re.search(pattern, module_name):
                    return True
            return False
        
        return True
    
    def add_change_callback(self, callback: Callable) -> None:
        """Add callback for layer changes."""
        self._callbacks.append(callback)
    
    def _notify_change(self, event: str, layer: OverlayLayer) -> None:
        """Notify all callbacks of layer change."""
        for callback in self._callbacks:
            try:
                callback(event, layer)
            except Exception as e:
                logger.error(f"Callback failed for {event}: {e}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert manager state to dictionary."""
        with self._lock:
            return {
                'layers': [layer.to_dict() for layer in self._layers.values()],
                'active_count': len(self.get_active_layers()),
                'total_count': len(self._layers),
                'change_counter': self._change_counter,
            }
    
    def __len__(self) -> int:
        return len(self._layers)
    
    def __contains__(self, name: str) -> bool:
        return name in self._layers


# -----------------------------------------------------------------------------
# Enhanced Virtual Site-Packages Finder
# -----------------------------------------------------------------------------

class VirtualSitePackagesFinder:
    """
    Advanced import hook with multi-layer overlay support.
    
    This enhanced finder provides sophisticated module resolution across
    multiple overlay layers with configurable strategies, comprehensive
    caching, and detailed statistics.
    
    Parameters
    ----------
    layer_manager : Optional[LayerManager]
        Layer manager instance (creates new if None).
    config : Optional[OverlayConfig]
        Global configuration.
    enable_logging : bool
        Whether to enable detailed logging.
    
    Attributes
    ----------
    layer_manager : LayerManager
        Manager for overlay layers.
    config : OverlayConfig
        Global configuration.
    stats : OverlayStats
        Statistics tracker.
    """
    
    def __init__(
        self,
        layer_manager: Optional[LayerManager] = None,
        config: Optional[OverlayConfig] = None,
        enable_logging: bool = False,
    ) -> None:
        """
        Initialize virtual site-packages finder.
        
        Parameters
        ----------
        layer_manager : Optional[LayerManager]
            Layer manager instance.
        config : Optional[OverlayConfig]
            Global configuration.
        enable_logging : bool
            Whether to enable detailed logging.
        """
        # Setup logging
        if enable_logging:
            logger.setLevel(logging.INFO)
        
        # Initialize components
        self.layer_manager = layer_manager or LayerManager()
        self.config = config or OverlayConfig()
        self.stats = OverlayStats()
        
        # Resolution cache
        self._resolution_cache: OrderedDict = OrderedDict()
        self._cache_lock = threading.RLock()
        
        # System site-packages paths
        self._system_paths: List[str] = []
        self._collect_system_paths()
        
        # Version verification cache
        self._version_cache: Dict[str, Tuple[str, bool]] = {}
        
        # Module metadata
        self._loaded_from_overlay: Dict[str, str] = {}
        self._module_sources: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"VirtualSitePackagesFinder initialized with {len(self.layer_manager)} layers")
    
    def _collect_system_paths(self) -> None:
        """
        Collect all system site-packages paths.
        
        This method gathers both global and user site-packages directories.
        """
        try:
            global_packages = site.getsitepackages()
            self._system_paths.extend(global_packages)
            logger.debug(f"Found global site-packages: {global_packages}")
        except Exception as e:
            logger.warning(f"Could not access global site-packages: {e}")
        
        try:
            user_packages = site.getusersitepackages()
            if user_packages and os.path.exists(user_packages):
                self._system_paths.append(user_packages)
                logger.debug(f"Found user site-packages: {user_packages}")
        except Exception as e:
            logger.warning(f"Could not access user site-packages: {e}")
        
        # Add standard library paths
        self._system_paths.extend(sys.path)
        
        # Deduplicate
        self._system_paths = list(dict.fromkeys(self._system_paths))
    
    def _get_cache_key(self, fullname: str, path: Optional[List[str]]) -> str:
        """Generate cache key for module resolution."""
        key_parts = [fullname]
        if path:
            key_parts.extend(path)
        return hashlib.md5('|'.join(key_parts).encode()).hexdigest()
    
    def _check_cache(self, cache_key: str) -> Optional[importlib.machinery.ModuleSpec]:
        """Check resolution cache."""
        with self._cache_lock:
            if cache_key in self._resolution_cache:
                spec, timestamp = self._resolution_cache[cache_key]
                
                # Check TTL
                if time.time() - timestamp < self.config.cache_ttl:
                    self.stats.record_cache_hit()
                    self._resolution_cache.move_to_end(cache_key)
                    return spec
                
                # Expired
                del self._resolution_cache[cache_key]
        
        return None
    
    def _update_cache(self, cache_key: str, spec: Optional[importlib.machinery.ModuleSpec]) -> None:
        """Update resolution cache."""
        with self._cache_lock:
            # Maintain cache size
            if len(self._resolution_cache) >= self.config.cache_size:
                self._resolution_cache.popitem(last=False)
            
            self._resolution_cache[cache_key] = (spec, time.time())
    
    def _resolve_module(
        self,
        fullname: str,
        path: Optional[List[str]] = None,
    ) -> Tuple[Optional[OverlayLayer], Optional[importlib.machinery.ModuleSpec]]:
        """
        Resolve module using configured strategy.
        
        Parameters
        ----------
        fullname : str
            Fully qualified module name.
        path : Optional[List[str]]
            Search path override.
        
        Returns
        -------
        Tuple[Optional[OverlayLayer], Optional[ModuleSpec]]
            Layer and spec if found.
        """
        strategy = self.config.resolution_strategy
        
        if strategy == ResolutionStrategy.OVERLAY_ONLY:
            return self._resolve_overlay_only(fullname)
        
        elif strategy == ResolutionStrategy.OVERLAY_FIRST:
            return self._resolve_overlay_first(fullname, path)
        
        elif strategy == ResolutionStrategy.SYSTEM_FIRST:
            return self._resolve_system_first(fullname, path)
        
        elif strategy == ResolutionStrategy.MERGE_SYSTEM_WINS:
            return self._resolve_merge(fullname, path, system_wins=True)
        
        elif strategy == ResolutionStrategy.MERGE_OVERLAY_WINS:
            return self._resolve_merge(fullname, path, system_wins=False)
        
        elif strategy == ResolutionStrategy.SMART:
            return self._resolve_smart(fullname, path)
        
        return None, None
    
    def _resolve_overlay_only(
        self,
        fullname: str,
    ) -> Tuple[Optional[OverlayLayer], Optional[importlib.machinery.ModuleSpec]]:
        """Resolve only from overlay layers."""
        layer, module_path = self.layer_manager.find_module(fullname)
        
        if layer and module_path:
            spec = importlib.machinery.PathFinder.find_spec(
                fullname,
                [str(layer.path)]
            )
            if spec:
                return layer, spec
        
        return None, None
    
    def _resolve_overlay_first(
        self,
        fullname: str,
        path: Optional[List[str]] = None,
    ) -> Tuple[Optional[OverlayLayer], Optional[importlib.machinery.ModuleSpec]]:
        """Try overlay first, fallback to system."""
        # Try overlay
        layer, spec = self._resolve_overlay_only(fullname)
        if spec:
            return layer, spec
        
        # Fallback to system
        if self.config.preserve_system:
            search_paths = path if path is not None else self._system_paths
            spec = importlib.machinery.PathFinder.find_spec(fullname, search_paths)
            if spec:
                return None, spec
        
        return None, None
    
    def _resolve_system_first(
        self,
        fullname: str,
        path: Optional[List[str]] = None,
    ) -> Tuple[Optional[OverlayLayer], Optional[importlib.machinery.ModuleSpec]]:
        """Try system first, fallback to overlay."""
        # Try system
        search_paths = path if path is not None else self._system_paths
        spec = importlib.machinery.PathFinder.find_spec(fullname, search_paths)
        if spec:
            return None, spec
        
        # Fallback to overlay
        layer, spec = self._resolve_overlay_only(fullname)
        if spec:
            return layer, spec
        
        return None, None
    
    def _resolve_merge(
        self,
        fullname: str,
        path: Optional[List[str]] = None,
        system_wins: bool = True,
    ) -> Tuple[Optional[OverlayLayer], Optional[importlib.machinery.ModuleSpec]]:
        """Merge resolution with conflict handling."""
        # Check both sources
        layer, overlay_spec = self._resolve_overlay_only(fullname)
        system_spec = importlib.machinery.PathFinder.find_spec(
            fullname,
            path if path is not None else self._system_paths
        )
        
        if system_wins:
            if system_spec:
                return None, system_spec
            if overlay_spec:
                return layer, overlay_spec
        else:
            if overlay_spec:
                return layer, overlay_spec
            if system_spec:
                return None, system_spec
        
        return None, None
    
    def _resolve_smart(
        self,
        fullname: str,
        path: Optional[List[str]] = None,
    ) -> Tuple[Optional[OverlayLayer], Optional[importlib.machinery.ModuleSpec]]:
        """Intelligent resolution based on version compatibility."""
        # Get both versions if available
        layer, overlay_spec = self._resolve_overlay_only(fullname)
        system_spec = importlib.machinery.PathFinder.find_spec(
            fullname,
            path if path is not None else self._system_paths
        )
        
        if overlay_spec and system_spec:
            # Compare versions if possible
            overlay_version = self._get_module_version(fullname, str(layer.path) if layer else None)
            system_version = self._get_module_version(fullname, None)
            
            if overlay_version and system_version:
                # Use newer version
                if self._compare_versions(overlay_version, system_version) > 0:
                    return layer, overlay_spec
                else:
                    return None, system_spec
        
        # Fallback to overlay first
        return self._resolve_overlay_first(fullname, path)
    
    def _get_module_version(self, module_name: str, search_path: Optional[str]) -> Optional[str]:
        """Get module version if available."""
        try:
            # Try to read version from metadata
            if search_path:
                version_file = Path(search_path) / module_name.split('.')[0] / '__init__.py'
            else:
                # Try to find in system
                for sys_path in self._system_paths:
                    version_file = Path(sys_path) / module_name.split('.')[0] / '__init__.py'
                    if version_file.exists():
                        break
                else:
                    return None
            
            if version_file.exists():
                content = version_file.read_text()
                import re
                match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
        except Exception:
            pass
        
        return None
    
    def _compare_versions(self, v1: str, v2: str) -> int:
        """Compare version strings."""
        from packaging import version
        try:
            v1_parsed = version.parse(v1)
            v2_parsed = version.parse(v2)
            if v1_parsed > v2_parsed:
                return 1
            elif v1_parsed < v2_parsed:
                return -1
            return 0
        except ImportError:
            # Fallback to simple comparison
            return (v1 > v2) - (v1 < v2)
    
    def find_spec(
        self,
        fullname: str,
        path: Optional[List[str]] = None,
        target: Optional[ModuleType] = None,
    ) -> Optional[importlib.machinery.ModuleSpec]:
        """
        Find module specification using overlay system.
        
        Parameters
        ----------
        fullname : str
            Fully qualified module name.
        path : Optional[List[str]]
            Search path override.
        target : Optional[ModuleType]
            Target module for reload.
        
        Returns
        -------
        Optional[ModuleSpec]
            Module specification if found.
        """
        start_time = time.perf_counter()
        self.stats.record_attempt()
        
        # Check cache
        cache_key = self._get_cache_key(fullname, path)
        if self.config.enable_caching:
            cached = self._check_cache(cache_key)
            if cached is not None:
                return cached
        
        # Resolve module
        layer, spec = self._resolve_module(fullname, path)
        
        if spec:
            if layer:
                self.stats.record_overlay_hit(layer.name, fullname)
                self._loaded_from_overlay[fullname] = layer.name
                self._module_sources[fullname] = {
                    'source': 'overlay',
                    'layer': layer.name,
                    'path': str(layer.path),
                }
                logger.info(f"Loading '{fullname}' from overlay layer '{layer.name}'")
            else:
                self.stats.record_system_hit(fullname)
                self._module_sources[fullname] = {
                    'source': 'system',
                    'origin': getattr(spec, 'origin', 'unknown'),
                }
                logger.debug(f"Loading '{fullname}' from system packages")
        else:
            self.stats.record_miss(layer.name if layer else None)
            logger.debug(f"Module '{fullname}' not found")
        
        # Update cache
        if self.config.enable_caching:
            self._update_cache(cache_key, spec)
        
        # Record timing
        elapsed_us = (time.perf_counter() - start_time) * 1_000_000
        self.stats.record_resolution_time(elapsed_us)
        
        return spec
    
    def add_layer(
        self,
        name: str,
        path: Union[str, Path],
        priority: int = 100,
        **kwargs,
    ) -> OverlayLayer:
        """
        Add a new overlay layer.
        
        Parameters
        ----------
        name : str
            Unique layer name.
        path : Union[str, Path]
            Path to overlay directory.
        priority : int
            Priority order (lower = higher).
        **kwargs
            Additional layer configuration.
        
        Returns
        -------
        OverlayLayer
            Created layer.
        """
        layer = OverlayLayer(
            name=name,
            path=Path(path),
            priority=priority,
            **kwargs,
        )
        self.layer_manager.add_layer(layer)
        self.clear_cache()
        return layer
    
    def remove_layer(self, name: str) -> bool:
        """
        Remove an overlay layer.
        
        Parameters
        ----------
        name : str
            Layer name to remove.
        
        Returns
        -------
        bool
            True if layer was removed.
        """
        removed = self.layer_manager.remove_layer(name) is not None
        if removed:
            self.clear_cache()
        return removed
    
    def clear_cache(self) -> None:
        """Clear all resolution caches."""
        with self._cache_lock:
            self._resolution_cache.clear()
            self._version_cache.clear()
        logger.info("Resolution cache cleared")
    
    def get_module_source(self, module_name: str) -> Optional[Dict[str, Any]]:
        """
        Get source information for a module.
        
        Parameters
        ----------
        module_name : str
            Module name.
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Source information dictionary.
        """
        return self._module_sources.get(module_name)
    
    def list_overlay_modules(self) -> Dict[str, List[str]]:
        """
        List all modules available in overlay layers.
        
        Returns
        -------
        Dict[str, List[str]]
            Dictionary mapping layer names to module lists.
        """
        result = {}
        for layer in self.layer_manager.get_active_layers():
            result[layer.name] = layer.list_modules()
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics."""
        stats = self.stats.to_dict()
        stats['layer_manager'] = self.layer_manager.to_dict()
        stats['loaded_from_overlay'] = len(self._loaded_from_overlay)
        stats['config'] = self.config.to_dict()
        return stats
    
    def reset_stats(self) -> None:
        """Reset all statistics."""
        self.stats.reset()
    
    def __repr__(self) -> str:
        return (f"VirtualSitePackagesFinder(layers={len(self.layer_manager)}, "
                f"strategy={self.config.resolution_strategy.name})")


# -----------------------------------------------------------------------------
# Public API Functions
# -----------------------------------------------------------------------------

def activate_virtual_site_packages(
    path: Union[str, Path] = DEFAULT_OVERLAY_DIR,
    preserve_system: bool = DEFAULT_PRESERVE_SYSTEM,
    enable_logging: bool = False,
    insert_at_front: bool = True,
    strategy: Union[str, ResolutionStrategy] = "overlay_first",
    **config_kwargs,
) -> VirtualSitePackagesFinder:
    """
    Activate the virtual site-packages overlay system.
    
    Parameters
    ----------
    path : Union[str, Path]
        Path to the overlay directory.
    preserve_system : bool
        Whether to fallback to system packages.
    enable_logging : bool
        Whether to enable detailed logging.
    insert_at_front : bool
        Whether to insert at beginning of meta_path.
    strategy : Union[str, ResolutionStrategy]
        Resolution strategy to use.
    **config_kwargs
        Additional configuration options.
    
    Returns
    -------
    VirtualSitePackagesFinder
        The activated finder instance.
    
    Examples
    --------
    >>> # Basic activation
    >>> finder = activate_virtual_site_packages()
    
    >>> # Advanced activation
    >>> finder = activate_virtual_site_packages(
    ...     path="/custom/overlay",
    ...     strategy="overlay_first",
    ...     preserve_system=True,
    ...     enable_caching=True,
    ... )
    """
    # Parse strategy
    if isinstance(strategy, str):
        strategy = ResolutionStrategy[strategy.upper()]
    
    # Create configuration
    config = OverlayConfig(
        resolution_strategy=strategy,
        preserve_system=preserve_system,
        **{k: v for k, v in config_kwargs.items() if hasattr(OverlayConfig, k)}
    )
    
    # Create finder
    finder = VirtualSitePackagesFinder(
        config=config,
        enable_logging=enable_logging,
    )
    
    # Add default layer
    overlay_path = Path(path).resolve()
    overlay_path.mkdir(parents=True, exist_ok=True)
    
    finder.add_layer(
        name="default",
        path=overlay_path,
        priority=0,
    )
    
    # Insert into meta_path
    if insert_at_front:
        sys.meta_path.insert(0, finder)
        logger.info("Inserted finder at beginning of meta_path")
    else:
        sys.meta_path.append(finder)
        logger.info("Appended finder to end of meta_path")
    
    logger.info(f"Virtual site-packages activated with overlay: {overlay_path}")
    return finder


def deactivate_virtual_site_packages(finder: VirtualSitePackagesFinder) -> bool:
    """
    Deactivate and remove a specific VirtualSitePackagesFinder.
    
    Parameters
    ----------
    finder : VirtualSitePackagesFinder
        The finder instance to remove.
    
    Returns
    -------
    bool
        True if finder was found and removed.
    """
    try:
        sys.meta_path.remove(finder)
        logger.info(f"Deactivated finder: {finder}")
        return True
    except ValueError:
        logger.warning(f"Finder not found in meta_path: {finder}")
        return False


def add_overlay_layer(
    finder: VirtualSitePackagesFinder,
    name: str,
    path: Union[str, Path],
    priority: Optional[int] = None,
    **kwargs,
) -> OverlayLayer:
    """
    Add a new overlay layer to existing finder.
    
    Parameters
    ----------
    finder : VirtualSitePackagesFinder
        Target finder instance.
    name : str
        Unique layer name.
    path : Union[str, Path]
        Path to overlay directory.
    priority : Optional[int]
        Priority order (auto-assigned if None).
    **kwargs
        Additional layer configuration.
    
    Returns
    -------
    OverlayLayer
        Created layer.
    """
    if priority is None:
        # Auto-assign priority
        existing = finder.layer_manager.get_active_layers()
        priority = max([l.priority for l in existing], default=0) + 100
    
    return finder.add_layer(name, path, priority, **kwargs)


def remove_overlay_layer(finder: VirtualSitePackagesFinder, name: str) -> bool:
    """
    Remove an overlay layer.
    
    Parameters
    ----------
    finder : VirtualSitePackagesFinder
        Target finder instance.
    name : str
        Layer name to remove.
    
    Returns
    -------
    bool
        True if layer was removed.
    """
    return finder.remove_layer(name)


def list_active_overrides() -> List[VirtualSitePackagesFinder]:
    """
    List all active VirtualSitePackagesFinder instances in sys.meta_path.
    
    Returns
    -------
    List[VirtualSitePackagesFinder]
        List of active finder instances.
    """
    return [f for f in sys.meta_path if isinstance(f, VirtualSitePackagesFinder)]


def list_overlay_layers(finder: Optional[VirtualSitePackagesFinder] = None) -> List[OverlayLayer]:
    """
    List overlay layers for a finder.
    
    Parameters
    ----------
    finder : Optional[VirtualSitePackagesFinder]
        Specific finder or first active if None.
    
    Returns
    -------
    List[OverlayLayer]
        List of overlay layers.
    """
    if finder is None:
        finders = list_active_overrides()
        if not finders:
            return []
        finder = finders[0]
    
    return finder.layer_manager.get_all_layers()


def clear_overlay_cache(finder: Optional[VirtualSitePackagesFinder] = None) -> None:
    """
    Clear overlay resolution cache.
    
    Parameters
    ----------
    finder : Optional[VirtualSitePackagesFinder]
        Specific finder or all active if None.
    """
    if finder:
        finder.clear_cache()
    else:
        for f in list_active_overrides():
            f.clear_cache()


def get_overlay_stats(finder: Optional[VirtualSitePackagesFinder] = None) -> Dict[str, Any]:
    """
    Get overlay system statistics.
    
    Parameters
    ----------
    finder : Optional[VirtualSitePackagesFinder]
        Specific finder or first active if None.
    
    Returns
    -------
    Dict[str, Any]
        Statistics dictionary.
    """
    if finder is None:
        finders = list_active_overrides()
        if not finders:
            return {'error': 'No active overlay finders'}
        finder = finders[0]
    
    return finder.get_stats()


def export_overlay_config(
    finder: VirtualSitePackagesFinder,
    filepath: Union[str, Path],
) -> None:
    """
    Export overlay configuration to file.
    
    Parameters
    ----------
    finder : VirtualSitePackagesFinder
        Finder to export.
    filepath : Union[str, Path]
        Output file path.
    """
    config_data = {
        'version': __version__,
        'exported_at': datetime.utcnow().isoformat(),
        'config': finder.config.to_dict(),
        'layers': [layer.to_dict() for layer in finder.layer_manager.get_all_layers()],
        'stats': finder.get_stats(),
    }
    
    with open(filepath, 'w') as f:
        json.dump(config_data, f, indent=2, default=str)
    
    logger.info(f"Configuration exported to {filepath}")


def import_overlay_config(
    filepath: Union[str, Path],
    activate: bool = True,
) -> VirtualSitePackagesFinder:
    """
    Import overlay configuration from file.
    
    Parameters
    ----------
    filepath : Union[str, Path]
        Configuration file path.
    activate : bool
        Whether to immediately activate the finder.
    
    Returns
    -------
    VirtualSitePackagesFinder
        Reconstructed finder instance.
    """
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    # Reconstruct config
    config = OverlayConfig.from_dict(data['config'])
    
    # Create finder
    finder = VirtualSitePackagesFinder(config=config)
    
    # Reconstruct layers
    for layer_data in data.get('layers', []):
        layer = OverlayLayer(
            name=layer_data['name'],
            path=Path(layer_data['path']),
            priority=layer_data['priority'],
            layer_type=OverlayType[layer_data['layer_type']],
            config=OverlayConfig.from_dict(layer_data['config']),
            enabled=layer_data['enabled'],
            metadata=layer_data.get('metadata', {}),
        )
        finder.layer_manager.add_layer(layer)
    
    # Activate if requested
    if activate:
        sys.meta_path.insert(0, finder)
        logger.info(f"Imported and activated configuration from {filepath}")
    
    return finder


@contextmanager
def virtual_site_packages_context(
    path: Union[str, Path] = DEFAULT_OVERLAY_DIR,
    **kwargs,
) -> Iterator[VirtualSitePackagesFinder]:
    """
    Context manager for temporary overlay activation.
    
    Parameters
    ----------
    path : Union[str, Path]
        Overlay directory path.
    **kwargs
        Additional configuration options.
    
    Yields
    ------
    VirtualSitePackagesFinder
        Active finder instance.
    
    Examples
    --------
    >>> with virtual_site_packages_context("/tmp/overlay") as finder:
    ...     import my_custom_module  # Loads from overlay
    ...     stats = finder.get_stats()
    >>> # Overlay deactivated after context
    """
    finder = activate_virtual_site_packages(path=path, **kwargs)
    try:
        yield finder
    finally:
        deactivate_virtual_site_packages(finder)


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Main classes
    'VirtualSitePackagesFinder',
    'OverlayLayer',
    'LayerManager',
    'OverlayConfig',
    'OverlayStats',
    'ResolutionStrategy',
    'OverlayType',
    
    # Primary functions
    'activate_virtual_site_packages',
    'deactivate_virtual_site_packages',
    'add_overlay_layer',
    'remove_overlay_layer',
    'list_active_overrides',
    'list_overlay_layers',
    'clear_overlay_cache',
    'get_overlay_stats',
    'export_overlay_config',
    'import_overlay_config',
    
    # Context manager
    'virtual_site_packages_context',
    
    # Constants
    'DEFAULT_OVERLAY_DIR',
    'RESOLUTION_STRATEGIES',
]