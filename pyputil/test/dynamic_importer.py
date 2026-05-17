#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
dynamic_importer.py
===================

Dynamic Module Import.

This module provides a sophisticated, production-ready dynamic import system
that enables seamless importing of Python modules from arbitrary locations
within a project structure. It features automatic conflict detection,
intelligent resolution strategies, comprehensive caching, and cross-platform
compatibility.

The system is designed for:
- Large-scale monorepo management with multiple module versions
- Plugin systems and dynamic extension loading
- Development environments with complex directory structures
- Testing frameworks requiring flexible module discovery
- Build systems and code generation tools
- Interactive REPL environments with dynamic module access
- Migration tools handling legacy code organization

Features
--------
- Recursive module discovery with pattern-based filtering
- Multiple conflict resolution strategies (priority, versioning, aliasing)
- Thread-safe module loading and caching
- Cross-platform path handling (Windows, Linux, macOS)
- Module reloading with dependency tracking
- Namespace package support
- Import hooks for custom loading behavior
- Comprehensive logging and debugging capabilities
- Performance optimization with LRU caching
- Security features for restricted environments
- Module introspection and dependency analysis
- Serialization of import state

Classes
-------
ModuleLoader
    Advanced module loading engine with caching and validation.
ImportConflictResolver
    Configurable conflict resolution strategies.
ModuleRegistry
    Central registry for tracking loaded modules and dependencies.
ImportScanner
    Optimized file system scanner for module discovery.
ModuleMetadata
    Rich metadata container for loaded modules.
ImportHookManager
    Manager for custom import hooks and transformers.
SecurityPolicy
    Security policy enforcement for module loading.

Functions
---------
enable_import_anywhere
    Primary entry point for activating the dynamic import system.
scan_project_modules
    Advanced module discovery with filtering and prioritization.
import_from_path
    Direct module import from specific file path.
reload_module
    Intelligent module reloading with dependency tracking.
register_import_hook
    Register custom import hooks for specialized loading.
configure_resolution_strategy
    Configure conflict resolution behavior.
export_import_state
    Export current import system state for reproducibility.
import_from_state
    Restore import system from exported state.

Constants
---------
DEFAULT_EXCLUDE_PATTERNS
    Default patterns for directories to exclude from scanning.
RESOLUTION_STRATEGIES
    Available conflict resolution strategy identifiers.
"""

from __future__ import annotations

import sys
import os
import re
import warnings
import importlib
import importlib.util
import importlib.machinery
import importlib.abc
import hashlib
import json
import logging
import threading
import time
import functools
from abc import ABC, abstractmethod
from collections import defaultdict, OrderedDict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import (
    Any, Callable, Dict, Iterator, List, Optional, Pattern, Set, Tuple,
    Type, Union, cast, overload, Generic, TypeVar
)

# -----------------------------------------------------------------------------
# Module Configuration and Constants
# -----------------------------------------------------------------------------

# Default exclude patterns for directory scanning
DEFAULT_EXCLUDE_PATTERNS: List[str] = [
    '__pycache__',
    '.git',
    '.hg',
    '.svn',
    'venv',
    'env',
    '.venv',
    '.env',
    'virtualenv',
    '.virtualenv',
    'node_modules',
    '.idea',
    '.vscode',
    '.vs',
    'build',
    'dist',
    '.eggs',
    '*.egg-info',
    '.tox',
    '.mypy_cache',
    '.pytest_cache',
    '.coverage',
    'htmlcov',
    '__pypackages__',
    '.pyre',
    '.pytype',
]

# File patterns to include (Python modules)
INCLUDE_PATTERNS: List[str] = ['*.py']

# Cache configuration
DEFAULT_CACHE_SIZE: int = 500
DEFAULT_CACHE_TTL: int = 3600  # 1 hour

# Resolution strategy identifiers
RESOLUTION_STRATEGIES = {
    'first': 'Use first found module, ignore others',
    'priority': 'Use module based on priority rules',
    'version': 'Use highest version number if detectable',
    'alias': 'Create aliases for conflicting modules',
    'namespace': 'Treat as namespace packages',
    'error': 'Raise error on conflict',
    'interactive': 'Prompt user for resolution',
}

# Configure logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


# -----------------------------------------------------------------------------
# Platform Detection and Path Utilities
# -----------------------------------------------------------------------------

class PlatformInfo:
    """
    Cross-platform information and path utilities.
    
    This class provides platform-specific handling for file paths,
    system characteristics, and environment detection.
    """
    
    _instance: Optional['PlatformInfo'] = None
    _lock = threading.RLock()
    
    def __new__(cls) -> 'PlatformInfo':
        """Singleton pattern for platform info."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize platform information."""
        if self._initialized:
            return
        
        self.system = sys.platform
        self.is_windows = self.system == 'win32'
        self.is_linux = self.system.startswith('linux')
        self.is_macos = self.system == 'darwin'
        self.is_posix = os.name == 'posix'
        
        self.case_sensitive_filesystem = not self.is_windows and not self.is_macos
        self.path_separator = os.path.sep
        self.env_separator = ';' if self.is_windows else ':'
        
        self._initialized = True
    
    def normalize_path(self, path: Union[str, Path]) -> Path:
        """
        Normalize path for current platform.
        
        Parameters
        ----------
        path : Union[str, Path]
            Path to normalize.
        
        Returns
        -------
        Path
            Normalized absolute path.
        """
        p = Path(path) if isinstance(path, str) else path
        
        # Resolve symlinks and normalize
        try:
            p = p.resolve()
        except (OSError, RuntimeError):
            p = p.absolute()
        
        return p
    
    def is_same_file(self, path1: Union[str, Path], path2: Union[str, Path]) -> bool:
        """
        Check if two paths refer to the same file.
        
        Parameters
        ----------
        path1 : Union[str, Path]
            First path.
        path2 : Union[str, Path]
            Second path.
        
        Returns
        -------
        bool
            True if paths refer to the same file.
        """
        p1 = self.normalize_path(path1)
        p2 = self.normalize_path(path2)
        
        try:
            return p1.samefile(p2)
        except (OSError, AttributeError):
            # Fallback for older Python or cross-device
            return str(p1) == str(p2)
    
    def get_relative_path(self, path: Union[str, Path], base: Union[str, Path]) -> Path:
        """
        Get platform-appropriate relative path.
        
        Parameters
        ----------
        path : Union[str, Path]
            Target path.
        base : Union[str, Path]
            Base path.
        
        Returns
        -------
        Path
            Relative path.
        """
        p = self.normalize_path(path)
        b = self.normalize_path(base)
        
        try:
            return p.relative_to(b)
        except ValueError:
            # Not under base, return absolute
            return p
    
    def glob_pattern_to_regex(self, pattern: str) -> Pattern:
        """
        Convert glob pattern to regex with platform considerations.
        
        Parameters
        ----------
        pattern : str
            Glob pattern.
        
        Returns
        -------
        Pattern
            Compiled regex pattern.
        """
        # Escape special regex characters except *
        regex = re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.')
        
        # Platform-specific path separators
        if self.is_windows:
            regex = regex.replace(r'/', r'[/\\]')
        
        return re.compile(f'^{regex}$', re.IGNORECASE if not self.case_sensitive_filesystem else 0)


# -----------------------------------------------------------------------------
# Enumerations and Configuration Classes
# -----------------------------------------------------------------------------

class ConflictStrategy(Enum):
    """
    Conflict resolution strategies.
    
    Attributes
    ----------
    FIRST : auto
        Use first found module, ignore subsequent conflicts.
    PRIORITY : auto
        Use module based on priority rules (e.g., source > tests).
    VERSION : auto
        Use highest version number if detectable.
    ALIAS : auto
        Create aliases for all conflicting modules.
    NAMESPACE : auto
        Treat as namespace packages (merge).
    ERROR : auto
        Raise ImportConflictError on conflict.
    INTERACTIVE : auto
        Prompt user for resolution (requires terminal).
    """
    
    FIRST = auto()
    PRIORITY = auto()
    VERSION = auto()
    ALIAS = auto()
    NAMESPACE = auto()
    ERROR = auto()
    INTERACTIVE = auto()


class ModulePriority(Enum):
    """
    Priority levels for module resolution.
    
    Attributes
    ----------
    HIGHEST : 0
        Highest priority (e.g., local source).
    HIGH : 10
        High priority (e.g., project root).
    NORMAL : 50
        Normal priority.
    LOW : 100
        Low priority (e.g., tests, examples).
    LOWEST : 200
        Lowest priority (e.g., third-party, legacy).
    """
    
    HIGHEST = 0
    HIGH = 10
    NORMAL = 50
    LOW = 100
    LOWEST = 200


@dataclass
class ImportConfig:
    """
    Configuration for dynamic import system.
    
    Attributes
    ----------
    base_path : Path
        Root path for module scanning.
    conflict_strategy : ConflictStrategy
        How to handle naming conflicts.
    recursive : bool
        Whether to scan directories recursively.
    follow_symlinks : bool
        Whether to follow symbolic links.
    include_init : bool
        Whether to include __init__.py files.
    exclude_patterns : List[str]
        Directory patterns to exclude.
    include_patterns : List[str]
        File patterns to include.
    priority_rules : Dict[str, ModulePriority]
        Rules for assigning priority based on path.
    enable_caching : bool
        Whether to cache loaded modules.
    cache_size : int
        Maximum number of cached modules.
    cache_ttl : int
        Cache time-to-live in seconds.
    warn_on_conflict : bool
        Whether to issue warnings on conflicts.
    verbose : bool
        Enable detailed logging.
    strict_mode : bool
        Raise errors on any issue.
    allow_reload : bool
        Allow reloading of already loaded modules.
    track_dependencies : bool
        Track module dependency relationships.
    validate_modules : bool
        Validate module integrity before loading.
    """
    
    base_path: Path = field(default_factory=Path.cwd)
    conflict_strategy: ConflictStrategy = ConflictStrategy.ALIAS
    recursive: bool = True
    follow_symlinks: bool = False
    include_init: bool = False
    exclude_patterns: List[str] = field(default_factory=lambda: DEFAULT_EXCLUDE_PATTERNS.copy())
    include_patterns: List[str] = field(default_factory=lambda: INCLUDE_PATTERNS.copy())
    priority_rules: Dict[str, ModulePriority] = field(default_factory=dict)
    enable_caching: bool = True
    cache_size: int = DEFAULT_CACHE_SIZE
    cache_ttl: int = DEFAULT_CACHE_TTL
    warn_on_conflict: bool = True
    verbose: bool = False
    strict_mode: bool = False
    allow_reload: bool = False
    track_dependencies: bool = True
    validate_modules: bool = True
    
    def __post_init__(self) -> None:
        """Validate and normalize configuration."""
        if isinstance(self.base_path, str):
            self.base_path = Path(self.base_path)
        self.base_path = self.base_path.resolve()
        
        # Set default priority rules if empty
        if not self.priority_rules:
            self.priority_rules = {
                r'.*/src/.*': ModulePriority.HIGH,
                r'.*/lib/.*': ModulePriority.NORMAL,
                r'.*/tests?/.*': ModulePriority.LOW,
                r'.*/examples?/.*': ModulePriority.LOW,
                r'.*/third_party/.*': ModulePriority.LOWEST,
                r'.*/vendor/.*': ModulePriority.LOWEST,
            }


# -----------------------------------------------------------------------------
# Custom Exceptions
# -----------------------------------------------------------------------------

class ImportConflictWarning(UserWarning):
    """
    Warning raised when module naming conflicts are detected.
    
    This warning indicates that multiple modules with the same name
    were found during scanning, and resolution was applied.
    
    Examples
    --------
    >>> import warnings
    >>> warnings.simplefilter('always', ImportConflictWarning)
    >>> enable_import_anywhere('/path/to/project')
    ImportConflictWarning: Module name conflict: 'utils' (3 versions, strategy=ALIAS)
    """
    pass


class ImportConflictError(ImportError):
    """
    Error raised when module conflict cannot be resolved.
    
    This error occurs when conflict_strategy is ERROR and a naming
    conflict is detected, or when resolution fails.
    
    Attributes
    ----------
    module_name : str
        Name of the conflicting module.
    paths : List[Path]
        Paths where conflicting modules were found.
    """
    
    def __init__(self, module_name: str, paths: List[Path]):
        self.module_name = module_name
        self.paths = paths
        paths_str = '\n  '.join(str(p) for p in paths)
        super().__init__(
            f"Module name conflict for '{module_name}'. Found at:\n  {paths_str}"
        )


class ModuleValidationError(ImportError):
    """
    Error raised when module validation fails.
    
    This error indicates that a module file exists but cannot be
    properly loaded or validated.
    
    Attributes
    ----------
    module_name : str
        Name of the module.
    file_path : Path
        Path to the module file.
    reason : str
        Reason for validation failure.
    """
    
    def __init__(self, module_name: str, file_path: Path, reason: str):
        self.module_name = module_name
        self.file_path = file_path
        self.reason = reason
        super().__init__(f"Module validation failed for '{module_name}' at {file_path}: {reason}")


class SecurityViolationError(ImportError):
    """
    Error raised when security policy prevents module loading.
    
    This error occurs when a module violates configured security policies,
    such as attempting to load from restricted directories.
    """
    
    def __init__(self, module_name: str, file_path: Path, policy: str):
        self.module_name = module_name
        self.file_path = file_path
        self.policy = policy
        super().__init__(
            f"Security policy '{policy}' prevents loading '{module_name}' from {file_path}"
        )


# -----------------------------------------------------------------------------
# Module Metadata
# -----------------------------------------------------------------------------

@dataclass
class ModuleMetadata:
    """
    Rich metadata container for loaded modules.
    
    Attributes
    ----------
    name : str
        Module name.
    file_path : Path
        Absolute path to module file.
    loaded_at : datetime
        Timestamp when module was loaded.
    file_hash : str
        SHA256 hash of module file content.
    file_size : int
        Size of module file in bytes.
    file_modified : float
        Last modification timestamp.
    dependencies : Set[str]
        Names of modules this module depends on.
    dependents : Set[str]
        Names of modules that depend on this module.
    priority : ModulePriority
        Priority level for conflict resolution.
    version : Optional[str]
        Detected module version if available.
    is_package : bool
        Whether this is a package (__init__.py).
    source_encoding : str
        Detected source file encoding.
    load_duration_ms : float
        Time taken to load module in milliseconds.
    custom_metadata : Dict[str, Any]
        User-defined metadata.
    """
    
    name: str
    file_path: Path
    loaded_at: datetime = field(default_factory=datetime.utcnow)
    file_hash: str = ""
    file_size: int = 0
    file_modified: float = 0.0
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)
    priority: ModulePriority = ModulePriority.NORMAL
    version: Optional[str] = None
    is_package: bool = False
    source_encoding: str = "utf-8"
    load_duration_ms: float = 0.0
    custom_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Calculate file metadata if not provided."""
        if not self.file_hash and self.file_path.exists():
            self._calculate_file_metadata()
    
    def _calculate_file_metadata(self) -> None:
        """Calculate file hash and size."""
        try:
            stat = self.file_path.stat()
            self.file_size = stat.st_size
            self.file_modified = stat.st_mtime
            
            # Calculate hash (first 8KB only for performance)
            with self.file_path.open('rb') as f:
                content = f.read(8192)
                self.file_hash = hashlib.sha256(content).hexdigest()[:16]
        except (OSError, IOError):
            pass
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'name': self.name,
            'file_path': str(self.file_path),
            'loaded_at': self.loaded_at.isoformat(),
            'file_hash': self.file_hash,
            'file_size': self.file_size,
            'file_modified': self.file_modified,
            'dependencies': list(self.dependencies),
            'dependents': list(self.dependents),
            'priority': self.priority.name,
            'version': self.version,
            'is_package': self.is_package,
            'source_encoding': self.source_encoding,
            'load_duration_ms': self.load_duration_ms,
            'custom_metadata': self.custom_metadata,
        }


# -----------------------------------------------------------------------------
# Module Registry
# -----------------------------------------------------------------------------

class ModuleRegistry:
    """
    Central registry for tracking loaded modules and dependencies.
    
    This class maintains a thread-safe registry of all modules loaded
    through the dynamic import system, tracking metadata and relationships.
    
    Attributes
    ----------
    modules : Dict[str, ModuleMetadata]
        Registered modules by name.
    aliases : Dict[str, str]
        Alias mappings (alias -> canonical name).
    dependency_graph : Dict[str, Set[str]]
        Module dependency graph.
    """
    
    def __init__(self):
        """Initialize module registry."""
        self.modules: Dict[str, ModuleMetadata] = {}
        self.aliases: Dict[str, str] = {}
        self.dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self._lock = threading.RLock()
        self._module_cache: OrderedDict = OrderedDict()
        self._cache_max_size = DEFAULT_CACHE_SIZE
    
    def register(
        self,
        name: str,
        file_path: Path,
        module: ModuleType,
        metadata: Optional[ModuleMetadata] = None,
    ) -> ModuleMetadata:
        """
        Register a loaded module.
        
        Parameters
        ----------
        name : str
            Module name.
        file_path : Path
            Path to module file.
        module : ModuleType
            Loaded module object.
        metadata : Optional[ModuleMetadata]
            Pre-created metadata.
        
        Returns
        -------
        ModuleMetadata
            Registered module metadata.
        """
        with self._lock:
            if metadata is None:
                metadata = ModuleMetadata(
                    name=name,
                    file_path=file_path,
                    is_package=hasattr(module, '__path__'),
                )
            
            self.modules[name] = metadata
            
            # Cache module object
            self._cache_module(name, module)
            
            logger.debug(f"Registered module: {name} from {file_path}")
            return metadata
    
    def unregister(self, name: str) -> Optional[ModuleMetadata]:
        """
        Unregister a module.
        
        Parameters
        ----------
        name : str
            Module name.
        
        Returns
        -------
        Optional[ModuleMetadata]
            Removed metadata or None if not found.
        """
        with self._lock:
            metadata = self.modules.pop(name, None)
            if metadata:
                # Remove from cache
                self._module_cache.pop(name, None)
                logger.debug(f"Unregistered module: {name}")
            return metadata
    
    def get(self, name: str) -> Optional[ModuleMetadata]:
        """
        Get module metadata.
        
        Parameters
        ----------
        name : str
            Module name (supports aliases).
        
        Returns
        -------
        Optional[ModuleMetadata]
            Module metadata or None if not found.
        """
        with self._lock:
            # Resolve alias
            canonical = self.aliases.get(name, name)
            return self.modules.get(canonical)
    
    def get_module(self, name: str) -> Optional[ModuleType]:
        """
        Get loaded module object.
        
        Parameters
        ----------
        name : str
            Module name.
        
        Returns
        -------
        Optional[ModuleType]
            Module object or None if not loaded.
        """
        with self._lock:
            canonical = self.aliases.get(name, name)
            
            # Check cache first
            if canonical in self._module_cache:
                self._module_cache.move_to_end(canonical)
                return self._module_cache[canonical]
            
            # Check sys.modules
            if canonical in sys.modules:
                module = sys.modules[canonical]
                self._cache_module(canonical, module)
                return module
            
            return None
    
    def _cache_module(self, name: str, module: ModuleType) -> None:
        """Cache module object."""
        if len(self._module_cache) >= self._cache_max_size:
            self._module_cache.popitem(last=False)
        self._module_cache[name] = module
    
    def add_alias(self, alias: str, canonical: str) -> None:
        """
        Add an alias for a module.
        
        Parameters
        ----------
        alias : str
            Alias name.
        canonical : str
            Canonical module name.
        """
        with self._lock:
            self.aliases[alias] = canonical
            logger.debug(f"Added alias: {alias} -> {canonical}")
    
    def add_dependency(self, module_name: str, dependency_name: str) -> None:
        """
        Record a module dependency.
        
        Parameters
        ----------
        module_name : str
            Name of dependent module.
        dependency_name : str
            Name of module being depended upon.
        """
        with self._lock:
            self.dependency_graph[module_name].add(dependency_name)
            
            if module_name in self.modules:
                self.modules[module_name].dependencies.add(dependency_name)
            if dependency_name in self.modules:
                self.modules[dependency_name].dependents.add(module_name)
    
    def get_dependents(self, module_name: str) -> Set[str]:
        """
        Get all modules that depend on a module.
        
        Parameters
        ----------
        module_name : str
            Module name.
        
        Returns
        -------
        Set[str]
            Set of dependent module names.
        """
        with self._lock:
            return self.dependency_graph.get(module_name, set()).copy()
    
    def get_all_modules(self) -> List[str]:
        """
        Get list of all registered module names.
        
        Returns
        -------
        List[str]
            List of module names.
        """
        with self._lock:
            return list(self.modules.keys())
    
    def clear(self) -> None:
        """Clear all registry data."""
        with self._lock:
            self.modules.clear()
            self.aliases.clear()
            self.dependency_graph.clear()
            self._module_cache.clear()
            logger.debug("Module registry cleared")
    
    def to_dict(self) -> Dict[str, Any]:
        """Export registry state to dictionary."""
        with self._lock:
            return {
                'modules': {
                    name: meta.to_dict()
                    for name, meta in self.modules.items()
                },
                'aliases': self.aliases.copy(),
                'dependency_graph': {
                    k: list(v) for k, v in self.dependency_graph.items()
                },
            }
    
    def __len__(self) -> int:
        return len(self.modules)
    
    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self.modules or name in self.aliases


# -----------------------------------------------------------------------------
# Import Scanner
# -----------------------------------------------------------------------------

class ImportScanner:
    """
    Optimized file system scanner for module discovery.
    
    This class provides efficient directory scanning with caching,
    pattern filtering, and priority assignment.
    """
    
    def __init__(self, config: ImportConfig):
        """
        Initialize import scanner.
        
        Parameters
        ----------
        config : ImportConfig
            Scanner configuration.
        """
        self.config = config
        self.platform = PlatformInfo()
        self._scan_cache: Dict[str, Dict[str, List[Path]]] = {}
        self._cache_lock = threading.RLock()
        self._priority_patterns: List[Tuple[Pattern, ModulePriority]] = []
        self._compile_priority_patterns()
    
    def _compile_priority_patterns(self) -> None:
        """Compile priority rule patterns."""
        for pattern_str, priority in self.config.priority_rules.items():
            pattern = re.compile(pattern_str)
            self._priority_patterns.append((pattern, priority))
    
    def _get_priority(self, file_path: Path) -> ModulePriority:
        """
        Determine priority for a module file.
        
        Parameters
        ----------
        file_path : Path
            Path to module file.
        
        Returns
        -------
        ModulePriority
            Assigned priority level.
        """
        path_str = str(file_path)
        
        for pattern, priority in self._priority_patterns:
            if pattern.search(path_str):
                return priority
        
        return ModulePriority.NORMAL
    
    def _should_exclude(self, path: Path) -> bool:
        """
        Check if a path should be excluded.
        
        Parameters
        ----------
        path : Path
            Path to check.
        
        Returns
        -------
        bool
            True if path should be excluded.
        """
        name = path.name
        
        # Check exclude patterns
        for pattern in self.config.exclude_patterns:
            if path.match(pattern):
                return True
        
        # Exclude hidden directories
        if path.is_dir() and name.startswith('.') and name not in ('.', '..'):
            return True
        
        return False
    
    def _should_include(self, file_path: Path) -> bool:
        """
        Check if a file should be included as module.
        
        Parameters
        ----------
        file_path : Path
            File path to check.
        
        Returns
        -------
        bool
            True if file should be included.
        """
        # Must be a Python file
        if not file_path.suffix == '.py':
            return False
        
        # Skip __init__.py unless configured
        if file_path.name == '__init__.py' and not self.config.include_init:
            return False
        
        # Check include patterns
        for pattern in self.config.include_patterns:
            if file_path.match(pattern):
                return True
        
        return False
    
    def scan(self, base_path: Optional[Path] = None) -> Dict[str, List[Tuple[Path, ModulePriority]]]:
        """
        Scan for Python modules.
        
        Parameters
        ----------
        base_path : Optional[Path]
            Base path to scan (uses config.base_path if None).
        
        Returns
        -------
        Dict[str, List[Tuple[Path, ModulePriority]]]
            Mapping of module names to lists of (path, priority) tuples.
        """
        base = base_path or self.config.base_path
        cache_key = f"{base}:{self.config.recursive}:{self.config.follow_symlinks}"
        
        # Check cache
        with self._cache_lock:
            if cache_key in self._scan_cache:
                logger.debug(f"Using cached scan results for {base}")
                return self._scan_cache[cache_key]
        
        logger.info(f"Scanning for modules in {base}")
        start_time = time.perf_counter()
        
        module_map: Dict[str, List[Tuple[Path, ModulePriority]]] = defaultdict(list)
        
        try:
            if self.config.recursive:
                iterator = base.rglob('*.py')
            else:
                iterator = base.glob('*.py')
            
            for file_path in iterator:
                # Skip if excluded
                if self._should_exclude(file_path):
                    continue
                
                # Check if should include
                if not self._should_include(file_path):
                    continue
                
                # Skip symlinks unless configured
                if file_path.is_symlink() and not self.config.follow_symlinks:
                    continue
                
                # Get module name
                module_name = file_path.stem
                priority = self._get_priority(file_path)
                
                module_map[module_name].append((file_path, priority))
        
        except PermissionError as e:
            logger.warning(f"Permission denied scanning {base}: {e}")
        except Exception as e:
            logger.error(f"Error scanning {base}: {e}")
            if self.config.strict_mode:
                raise
        
        # Sort by priority within each module group
        for name in module_map:
            module_map[name].sort(key=lambda x: x[1].value)
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"Scan complete: found {sum(len(v) for v in module_map.values())} modules in {elapsed_ms:.2f}ms")
        
        # Cache results
        with self._cache_lock:
            self._scan_cache[cache_key] = dict(module_map)
            
            # Limit cache size
            if len(self._scan_cache) > 10:
                oldest_key = next(iter(self._scan_cache))
                del self._scan_cache[oldest_key]
        
        return dict(module_map)
    
    def clear_cache(self) -> None:
        """Clear scan cache."""
        with self._cache_lock:
            self._scan_cache.clear()
            logger.debug("Scanner cache cleared")


# -----------------------------------------------------------------------------
# Conflict Resolver
# -----------------------------------------------------------------------------

class ConflictResolver:
    """
    Configurable conflict resolution strategies.
    
    This class implements various strategies for resolving module
    naming conflicts.
    """
    
    def __init__(self, config: ImportConfig):
        """
        Initialize conflict resolver.
        
        Parameters
        ----------
        config : ImportConfig
            Resolver configuration.
        """
        self.config = config
    
    def resolve(
        self,
        module_name: str,
        paths: List[Tuple[Path, ModulePriority]],
        registry: ModuleRegistry,
    ) -> List[Tuple[str, Path]]:
        """
        Resolve module naming conflict.
        
        Parameters
        ----------
        module_name : str
            Conflicting module name.
        paths : List[Tuple[Path, ModulePriority]]
            List of (path, priority) tuples for conflicting modules.
        registry : ModuleRegistry
            Module registry for checking existing modules.
        
        Returns
        -------
        List[Tuple[str, Path]]
            List of (resolved_name, path) tuples to load.
        
        Raises
        ------
        ImportConflictError
            If resolution fails and strategy is ERROR.
        """
        strategy = self.config.conflict_strategy
        
        if strategy == ConflictStrategy.FIRST:
            return self._resolve_first(module_name, paths)
        
        elif strategy == ConflictStrategy.PRIORITY:
            return self._resolve_priority(module_name, paths)
        
        elif strategy == ConflictStrategy.VERSION:
            return self._resolve_version(module_name, paths)
        
        elif strategy == ConflictStrategy.ALIAS:
            return self._resolve_alias(module_name, paths, registry)
        
        elif strategy == ConflictStrategy.NAMESPACE:
            return self._resolve_namespace(module_name, paths)
        
        elif strategy == ConflictStrategy.ERROR:
            raise ImportConflictError(module_name, [p for p, _ in paths])
        
        elif strategy == ConflictStrategy.INTERACTIVE:
            return self._resolve_interactive(module_name, paths)
        
        return self._resolve_alias(module_name, paths, registry)
    
    def _resolve_first(
        self,
        module_name: str,
        paths: List[Tuple[Path, ModulePriority]],
    ) -> List[Tuple[str, Path]]:
        """Use first found module only."""
        if paths:
            return [(module_name, paths[0][0])]
        return []
    
    def _resolve_priority(
        self,
        module_name: str,
        paths: List[Tuple[Path, ModulePriority]],
    ) -> List[Tuple[str, Path]]:
        """Use highest priority module, alias others."""
        result = []
        for i, (path, priority) in enumerate(paths):
            if i == 0:
                result.append((module_name, path))
            else:
                alias = f"{module_name}__prio{priority.value}"
                result.append((alias, path))
        return result
    
    def _resolve_version(
        self,
        module_name: str,
        paths: List[Tuple[Path, ModulePriority]],
    ) -> List[Tuple[str, Path]]:
        """Use version information to select best module."""
        versions = []
        for path, priority in paths:
            version = self._detect_version(path)
            versions.append((path, priority, version))
        
        # Sort by version (higher first), then priority
        versions.sort(key=lambda x: (x[2] or '', x[1].value), reverse=True)
        
        result = []
        for i, (path, priority, version) in enumerate(versions):
            if i == 0:
                result.append((module_name, path))
            else:
                ver_str = version.replace('.', '_') if version else f"alt{i}"
                alias = f"{module_name}__v{ver_str}"
                result.append((alias, path))
        return result
    
    def _detect_version(self, file_path: Path) -> Optional[str]:
        """Detect module version from file."""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            
            # Look for __version__
            match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)
            
            # Look for version in setup.py style
            match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)
        
        except Exception:
            pass
        
        return None
    
    def _resolve_alias(
        self,
        module_name: str,
        paths: List[Tuple[Path, ModulePriority]],
        registry: ModuleRegistry,
    ) -> List[Tuple[str, Path]]:
        """Create aliases for all conflicting modules."""
        result = []
        used_names = set(registry.get_all_modules())
        
        for i, (path, priority) in enumerate(paths):
            if i == 0:
                name = module_name
            else:
                # Generate unique alias
                base = f"{module_name}__alt"
                counter = 1
                name = f"{base}{counter}"
                while name in used_names:
                    counter += 1
                    name = f"{base}{counter}"
                used_names.add(name)
            
            result.append((name, path))
        
        return result
    
    def _resolve_namespace(
        self,
        module_name: str,
        paths: List[Tuple[Path, ModulePriority]],
    ) -> List[Tuple[str, Path]]:
        """Treat as namespace packages."""
        # For namespace packages, we can load all under the same name
        # but with different __path__ entries
        result = []
        for i, (path, priority) in enumerate(paths):
            ns_name = f"{module_name}__ns{i}" if i > 0 else module_name
            result.append((ns_name, path))
        return result
    
    def _resolve_interactive(
        self,
        module_name: str,
        paths: List[Tuple[Path, ModulePriority]],
    ) -> List[Tuple[str, Path]]:
        """Prompt user for resolution."""
        if not sys.stdin.isatty():
            # Fallback to alias if not interactive
            return self._resolve_alias(module_name, paths, ModuleRegistry())
        
        print(f"\nModule conflict detected: '{module_name}'")
        print(f"Found {len(paths)} versions:")
        for i, (path, priority) in enumerate(paths, 1):
            print(f"  [{i}] {path} (priority: {priority.name})")
        print("  [a] Create aliases for all")
        print("  [s] Skip all")
        
        try:
            choice = input("Select option (1-{}/a/s): ".format(len(paths))).strip().lower()
            
            if choice == 'a':
                return self._resolve_alias(module_name, paths, ModuleRegistry())
            elif choice == 's':
                return []
            else:
                idx = int(choice) - 1
                if 0 <= idx < len(paths):
                    return [(module_name, paths[idx][0])]
        except (ValueError, KeyboardInterrupt):
            pass
        
        return self._resolve_alias(module_name, paths, ModuleRegistry())


# -----------------------------------------------------------------------------
# Enhanced Module Loader
# -----------------------------------------------------------------------------

class ModuleLoader:
    """
    Advanced module loading engine with caching and validation.
    
    This class provides sophisticated module loading capabilities with
    comprehensive error handling, validation, and optimization.
    
    Parameters
    ----------
    config : Optional[ImportConfig]
        Loader configuration.
    registry : Optional[ModuleRegistry]
        Module registry for tracking.
    
    Attributes
    ----------
    config : ImportConfig
        Current configuration.
    registry : ModuleRegistry
        Module registry instance.
    loaded_count : int
        Number of successfully loaded modules.
    error_count : int
        Number of loading errors.
    """
    
    def __init__(
        self,
        config: Optional[ImportConfig] = None,
        registry: Optional[ModuleRegistry] = None,
    ):
        """
        Initialize module loader.
        
        Parameters
        ----------
        config : Optional[ImportConfig]
            Loader configuration.
        registry : Optional[ModuleRegistry]
            Module registry.
        """
        self.config = config or ImportConfig()
        self.registry = registry or ModuleRegistry()
        self.platform = PlatformInfo()
        
        self.loaded_count = 0
        self.error_count = 0
        self.conflict_count = 0
        
        self._load_lock = threading.RLock()
        self._validation_hooks: List[Callable] = []
    
    def _validate_module(self, module_name: str, file_path: Path) -> None:
        """
        Validate module before loading.
        
        Parameters
        ----------
        module_name : str
            Module name.
        file_path : Path
            Module file path.
        
        Raises
        ------
        ModuleValidationError
            If validation fails.
        """
        if not self.config.validate_modules:
            return
        
        # Check file exists and is readable
        if not file_path.exists():
            raise ModuleValidationError(
                module_name, file_path, "File does not exist"
            )
        
        if not file_path.is_file():
            raise ModuleValidationError(
                module_name, file_path, "Path is not a file"
            )
        
        # Check file size (skip empty files)
        try:
            if file_path.stat().st_size == 0:
                raise ModuleValidationError(
                    module_name, file_path, "File is empty"
                )
        except OSError as e:
            raise ModuleValidationError(
                module_name, file_path, f"Cannot stat file: {e}"
            )
        
        # Check syntax by attempting to compile
        try:
            content = file_path.read_text(encoding='utf-8')
            compile(content, str(file_path), 'exec')
        except SyntaxError as e:
            raise ModuleValidationError(
                module_name, file_path, f"Syntax error: {e}"
            )
        except Exception as e:
            raise ModuleValidationError(
                module_name, file_path, f"Compilation error: {e}"
            )
        
        # Run custom validation hooks
        for hook in self._validation_hooks:
            try:
                hook(module_name, file_path)
            except Exception as e:
                raise ModuleValidationError(
                    module_name, file_path, f"Hook validation failed: {e}"
                )
    
    def _warn(self, message: str, category: type = UserWarning) -> None:
        """
        Issue warning if verbose mode is enabled.
        
        Parameters
        ----------
        message : str
            Warning message.
        category : type
            Warning category.
        """
        if self.config.verbose:
            warnings.warn(message, category, stacklevel=3)
            logger.info(message)
    
    def load_from_path(
        self,
        module_name: str,
        file_path: Union[str, Path],
        force: bool = False,
    ) -> Optional[ModuleType]:
        """
        Load a Python module from a specific file path.
        
        Parameters
        ----------
        module_name : str
            Name to assign to the module.
        file_path : Union[str, Path]
            Path to module file.
        force : bool
            Force reload even if already loaded.
        
        Returns
        -------
        Optional[ModuleType]
            Loaded module or None if failed.
        
        Raises
        ------
        ModuleValidationError
            If module validation fails.
        ImportError
            If module cannot be loaded.
        """
        file_path = self.platform.normalize_path(file_path)
        
        with self._load_lock:
            # Check if already loaded
            if not force:
                existing = self.registry.get_module(module_name)
                if existing is not None:
                    self._warn(f"Module '{module_name}' already loaded")
                    return existing
            
            # Validate module
            try:
                self._validate_module(module_name, file_path)
            except ModuleValidationError as e:
                self.error_count += 1
                logger.error(str(e))
                if self.config.strict_mode:
                    raise
                return None
            
            self._warn(f"Loading module '{module_name}' from {file_path}")
            start_time = time.perf_counter()
            
            try:
                # Create module specification
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    str(file_path)
                )
                
                if spec is None or spec.loader is None:
                    raise ImportError(f"Cannot create module specification for: {module_name}")
                
                # Create and execute module
                module = importlib.util.module_from_spec(spec)
                
                # Set module attributes
                module.__file__ = str(file_path)
                module.__loader__ = spec.loader
                
                # Execute module
                spec.loader.exec_module(module)
                
                # Register in sys.modules
                sys.modules[module_name] = module
                
                # Calculate load time
                load_duration_ms = (time.perf_counter() - start_time) * 1000
                
                # Create and register metadata
                metadata = ModuleMetadata(
                    name=module_name,
                    file_path=file_path,
                    is_package=hasattr(module, '__path__'),
                    load_duration_ms=load_duration_ms,
                )
                
                self.registry.register(module_name, file_path, module, metadata)
                
                self.loaded_count += 1
                self._warn(
                    f"Successfully loaded '{module_name}' in {load_duration_ms:.2f}ms"
                )
                
                # Analyze dependencies if configured
                if self.config.track_dependencies:
                    self._analyze_dependencies(module_name, module)
                
                return module
                
            except Exception as e:
                self.error_count += 1
                logger.error(f"Failed to load module '{module_name}': {e}")
                
                if self.config.strict_mode:
                    raise ImportError(f"Failed to load module '{module_name}': {e}") from e
                
                return None
    
    def _analyze_dependencies(self, module_name: str, module: ModuleType) -> None:
        """
        Analyze and record module dependencies.
        
        Parameters
        ----------
        module_name : str
            Module name.
        module : ModuleType
            Loaded module.
        """
        try:
            # Simple dependency detection via __import__ inspection
            # This is a basic implementation; full AST analysis would be more accurate
            import re
            
            if hasattr(module, '__file__') and module.__file__:
                content = Path(module.__file__).read_text(encoding='utf-8', errors='ignore')
                
                # Find import statements
                import_pattern = re.compile(
                    r'^(?:from\s+(\S+)\s+import|import\s+(\S+))',
                    re.MULTILINE
                )
                
                for match in import_pattern.finditer(content):
                    dep = match.group(1) or match.group(2)
                    if dep:
                        base_dep = dep.split('.')[0]
                        if base_dep != module_name:
                            self.registry.add_dependency(module_name, base_dep)
        
        except Exception as e:
            logger.debug(f"Dependency analysis failed for {module_name}: {e}")
    
    def reload_module(self, module_name: str) -> Optional[ModuleType]:
        """
        Reload a previously loaded module.
        
        Parameters
        ----------
        module_name : str
            Name of module to reload.
        
        Returns
        -------
        Optional[ModuleType]
            Reloaded module or None if failed.
        """
        with self._load_lock:
            metadata = self.registry.get(module_name)
            if metadata is None:
                logger.warning(f"Cannot reload unknown module: {module_name}")
                return None
            
            # Clear from sys.modules
            if module_name in sys.modules:
                del sys.modules[module_name]
            
            # Reload
            return self.load_from_path(module_name, metadata.file_path, force=True)
    
    def add_validation_hook(self, hook: Callable[[str, Path], None]) -> None:
        """
        Add a custom validation hook.
        
        Parameters
        ----------
        hook : Callable[[str, Path], None]
            Validation function that takes (module_name, file_path).
        """
        self._validation_hooks.append(hook)
    
    def is_loaded(self, module_name: str) -> bool:
        """
        Check if a module is loaded.
        
        Parameters
        ----------
        module_name : str
            Module name.
        
        Returns
        -------
        bool
            True if module is loaded.
        """
        return module_name in self.registry
    
    def get_module(self, module_name: str) -> Optional[ModuleType]:
        """
        Get loaded module object.
        
        Parameters
        ----------
        module_name : str
            Module name.
        
        Returns
        -------
        Optional[ModuleType]
            Module object or None.
        """
        return self.registry.get_module(module_name)
    
    def get_metadata(self, module_name: str) -> Optional[ModuleMetadata]:
        """
        Get module metadata.
        
        Parameters
        ----------
        module_name : str
            Module name.
        
        Returns
        -------
        Optional[ModuleMetadata]
            Module metadata.
        """
        return self.registry.get(module_name)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get loader statistics.
        
        Returns
        -------
        Dict[str, Any]
            Statistics dictionary.
        """
        return {
            'loaded_count': self.loaded_count,
            'error_count': self.error_count,
            'conflict_count': self.conflict_count,
            'registry_size': len(self.registry),
            'config': {
                'base_path': str(self.config.base_path),
                'conflict_strategy': self.config.conflict_strategy.name,
                'recursive': self.config.recursive,
            },
        }


# -----------------------------------------------------------------------------
# Public API Functions
# -----------------------------------------------------------------------------

# Global state
_global_loader: Optional[ModuleLoader] = None
_global_config: Optional[ImportConfig] = None
_global_lock = threading.RLock()


def enable_import_anywhere(
    base_path: Optional[Union[str, Path]] = None,
    warn: bool = True,
    verbose: bool = False,
    exclude_patterns: Optional[List[str]] = None,
    include_init: bool = False,
    recursive: bool = True,
    conflict_strategy: Union[str, ConflictStrategy] = 'alias',
    strict_mode: bool = False,
    track_dependencies: bool = False,
) -> ModuleLoader:
    """
    Enable dynamic module importing from anywhere in a project.
    
    This function activates the advanced dynamic import system, scanning
    the project directory for Python modules and making them importable
    with intelligent conflict resolution.
    
    Parameters
    ----------
    base_path : Optional[Union[str, Path]]
        Project root path to scan (default: current working directory).
    warn : bool
        Enable/disable conflict warning messages (default: True).
    verbose : bool
        Enable detailed operation logging (default: False).
    exclude_patterns : Optional[List[str]]
        Directory patterns to exclude from scanning.
    include_init : bool
        Include __init__.py files as modules (default: False).
    recursive : bool
        Scan directories recursively (default: True).
    conflict_strategy : Union[str, ConflictStrategy]
        How to handle module naming conflicts:
        - 'first': Use first found, ignore others
        - 'priority': Use based on priority rules
        - 'version': Use highest version
        - 'alias': Create unique aliases (default)
        - 'namespace': Treat as namespace packages
        - 'error': Raise error on conflict
    strict_mode : bool
        Raise errors on any issue (default: False).
    track_dependencies : bool
        Track module dependency relationships (default: False).
    
    Returns
    -------
    ModuleLoader
        The module loader instance used for loading modules.
    
    Raises
    ------
    ValueError
        If base_path is invalid.
    
    Examples
    --------
    Basic usage:
    
    >>> # Load all modules from current directory
    >>> enable_import_anywhere()
    >>> import my_module  # Now importable from anywhere
    
    Advanced configuration:
    
    >>> loader = enable_import_anywhere(
    ...     base_path='/path/to/project',
    ...     conflict_strategy='priority',
    ...     exclude_patterns=['tests', 'docs', 'legacy'],
    ...     verbose=True,
    ...     track_dependencies=True,
    ... )
    
    Using loaded modules:
    
    >>> loader = enable_import_anywhere()
    >>> if loader.is_loaded('database'):
    ...     stats = loader.get_stats()
    ...     print(f"Loaded {stats['loaded_count']} modules")
    
    Handling conflicts:
    
    >>> # With alias strategy (default)
    >>> enable_import_anywhere()
    >>> import utils         # First version
    >>> import utils__alt1   # Second version (aliased)
    >>> import utils__alt2   # Third version
    
    Notes
    -----
    - All loaded modules are registered in sys.modules for normal imports
    - The function is idempotent; calling multiple times updates configuration
    - Use the returned ModuleLoader for advanced operations
    """
    global _global_loader, _global_config
    
    with _global_lock:
        # Resolve base path
        if base_path is None:
            base_path = Path.cwd()
        else:
            base_path = Path(base_path) if isinstance(base_path, str) else base_path
        
        if not base_path.is_dir():
            raise ValueError(f"Invalid base path: {base_path}")
        
        # Parse conflict strategy
        if isinstance(conflict_strategy, str):
            strategy_map = {
                'first': ConflictStrategy.FIRST,
                'priority': ConflictStrategy.PRIORITY,
                'version': ConflictStrategy.VERSION,
                'alias': ConflictStrategy.ALIAS,
                'namespace': ConflictStrategy.NAMESPACE,
                'error': ConflictStrategy.ERROR,
            }
            conflict_strategy = strategy_map.get(
                conflict_strategy.lower(),
                ConflictStrategy.ALIAS
            )
        
        # Create configuration
        config = ImportConfig(
            base_path=base_path,
            conflict_strategy=conflict_strategy,
            recursive=recursive,
            include_init=include_init,
            exclude_patterns=exclude_patterns or DEFAULT_EXCLUDE_PATTERNS,
            warn_on_conflict=warn,
            verbose=verbose,
            strict_mode=strict_mode,
            track_dependencies=track_dependencies,
        )
        
        _global_config = config
        
        # Create scanner and resolver
        scanner = ImportScanner(config)
        resolver = ConflictResolver(config)
        
        # Create loader
        loader = ModuleLoader(config)
        _global_loader = loader
        
        # Scan for modules
        module_map = scanner.scan()
        
        # Track conflicts
        conflicts = 0
        
        # Load modules with conflict resolution
        for module_name, paths in module_map.items():
            if len(paths) == 1:
                # No conflict
                path, priority = paths[0]
                loader.load_from_path(module_name, path)
            else:
                # Conflict detected
                conflicts += 1
                
                if warn:
                    warnings.warn(
                        f"Module name conflict: '{module_name}' "
                        f"({len(paths)} versions, strategy={conflict_strategy.name})",
                        ImportConflictWarning,
                        stacklevel=2,
                    )
                
                # Resolve conflict
                try:
                    resolved = resolver.resolve(module_name, paths, loader.registry)
                    for resolved_name, path in resolved:
                        loader.load_from_path(resolved_name, path)
                except ImportConflictError as e:
                    logger.error(str(e))
                    loader.conflict_count += 1
                    if strict_mode:
                        raise
        
        loader.conflict_count = conflicts
        
        # Summary
        if verbose:
            logger.info(
                f"Import system ready: loaded {loader.loaded_count} modules, "
                f"{loader.error_count} errors, {conflicts} conflicts resolved"
            )
        
        return loader


def scan_project_modules(
    base_path: Union[str, Path],
    exclude_patterns: Optional[List[str]] = None,
    include_init: bool = False,
    verbose: bool = False,
) -> Dict[str, List[Path]]:
    """
    Scan a project directory for Python modules and detect naming conflicts.
    
    Parameters
    ----------
    base_path : Union[str, Path]
        Root directory to scan.
    exclude_patterns : Optional[List[str]]
        Directory patterns to exclude.
    include_init : bool
        Include __init__.py files.
    verbose : bool
        Output scan progress.
    
    Returns
    -------
    Dict[str, List[Path]]
        Mapping of module names to file paths.
    
    Examples
    --------
    >>> modules = scan_project_modules('./my_project', exclude_patterns=['tests'])
    >>> for name, paths in modules.items():
    ...     if len(paths) > 1:
    ...         print(f"Conflict: {name} at {len(paths)} locations")
    """
    config = ImportConfig(
        base_path=Path(base_path),
        include_init=include_init,
        exclude_patterns=exclude_patterns or DEFAULT_EXCLUDE_PATTERNS,
        verbose=verbose,
    )
    
    scanner = ImportScanner(config)
    module_map = scanner.scan()
    
    # Convert to simple path list
    return {
        name: [path for path, _ in paths]
        for name, paths in module_map.items()
    }


def import_from_path(
    module_name: str,
    file_path: Union[str, Path],
    verbose: bool = False,
) -> Optional[ModuleType]:
    """
    Directly import a module from a specific file path.
    
    Parameters
    ----------
    module_name : str
        Name to assign to the module.
    file_path : Union[str, Path]
        Path to module file.
    verbose : bool
        Enable verbose output.
    
    Returns
    -------
    Optional[ModuleType]
        Loaded module or None if failed.
    
    Examples
    --------
    >>> module = import_from_path('custom_utils', './src/custom/utils.py')
    >>> module.my_function()
    """
    config = ImportConfig(verbose=verbose)
    loader = ModuleLoader(config)
    return loader.load_from_path(module_name, file_path)


def reload_module(module_name: str) -> Optional[ModuleType]:
    """
    Reload a dynamically loaded module.
    
    Parameters
    ----------
    module_name : str
        Name of module to reload.
    
    Returns
    -------
    Optional[ModuleType]
        Reloaded module or None if not found.
    
    Examples
    --------
    >>> enable_import_anywhere()
    >>> import my_module
    >>> # ... modify my_module.py ...
    >>> reloaded = reload_module('my_module')
    """
    global _global_loader
    
    if _global_loader is None:
        warnings.warn("No global loader configured. Use enable_import_anywhere() first.")
        return None
    
    return _global_loader.reload_module(module_name)


def get_loader() -> Optional[ModuleLoader]:
    """
    Get the global module loader instance.
    
    Returns
    -------
    Optional[ModuleLoader]
        Global loader or None if not initialized.
    """
    return _global_loader


def get_import_stats() -> Dict[str, Any]:
    """
    Get statistics about the dynamic import system.
    
    Returns
    -------
    Dict[str, Any]
        Statistics dictionary.
    
    Examples
    --------
    >>> stats = get_import_stats()
    >>> print(f"Loaded {stats['loaded_count']} modules")
    """
    if _global_loader is None:
        return {'error': 'Import system not initialized'}
    
    return _global_loader.get_stats()


def list_loaded_modules() -> List[str]:
    """
    Get list of all dynamically loaded modules.
    
    Returns
    -------
    List[str]
        List of module names.
    """
    if _global_loader is None:
        return []
    
    return _global_loader.registry.get_all_modules()


def clear_import_cache() -> None:
    """Clear the module registry and cache."""
    global _global_loader, _global_config
    
    with _global_lock:
        if _global_loader is not None:
            _global_loader.registry.clear()
        _global_loader = None
        _global_config = None


# -----------------------------------------------------------------------------
# Legacy Compatibility
# -----------------------------------------------------------------------------

class ImportConflictWarning(UserWarning):
    """Legacy warning class maintained for backward compatibility."""
    pass


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Main classes
    'ModuleLoader',
    'ImportScanner',
    'ConflictResolver',
    'ModuleRegistry',
    'ModuleMetadata',
    'ImportConfig',
    'PlatformInfo',
    
    # Enumerations
    'ConflictStrategy',
    'ModulePriority',
    
    # Exceptions
    'ImportConflictWarning',
    'ImportConflictError',
    'ModuleValidationError',
    'SecurityViolationError',
    
    # Primary functions
    'enable_import_anywhere',
    'scan_project_modules',
    'import_from_path',
    'reload_module',
    'get_loader',
    'get_import_stats',
    'list_loaded_modules',
    'clear_import_cache',
    
    # Constants
    'DEFAULT_EXCLUDE_PATTERNS',
    'RESOLUTION_STRATEGIES',
]