#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Virtual Package System with Complete Python Package Emulation.

This module provides a comprehensive virtual package management system that
fully emulates Python's package import system with support for nested modules,
__init__.py execution, namespace packages, relative imports, and complete
package lifecycle management.

The virtual package system enables:
- Dynamic creation of package hierarchies without filesystem operations
- Complete __init__.py support with full execution semantics
- Namespace package compatibility (PEP 420)
- Relative import resolution within virtual packages
- Package-level dependency injection and configuration
- Package discovery and introspection
- Cross-package references and circular dependency handling
- Package versioning and metadata management
- Import hooks and custom importers
- Package serialization and deserialization

Features:
---------
- Full Python package semantics emulation
- Nested subpackage support with arbitrary depth
- __init__.py module with complete execution support
- __all__ and __path__ attribute management
- Relative imports between sibling modules
- Namespace package compatibility
- Package-level dependency injection
- Circular import detection and resolution
- Package discovery and traversal utilities
- Serialization to/from filesystem
- Import hook registration
- Package aliasing and symlinking
- Hot reloading of package modules
- Package-level event system

Examples
--------
>>> # Create a complete package hierarchy
>>> pkg = VirtualPackage("myapp")
>>> 
>>> # Add __init__.py content
>>> pkg.get_init().write('''
... __version__ = "1.0.0"
... __all__ = ["core", "utils"]
... 
... def get_version():
...     return __version__
... ''')
>>> 
>>> # Create submodules
>>> core = pkg.create_module("core")
>>> core.write('''
... class Application:
...     def run(self):
...         return "Running..."
... ''')
>>> 
>>> # Create subpackage
>>> plugins = pkg.create_subpackage("plugins")
>>> 
>>> # Create module in subpackage
>>> db_plugin = plugins.create_module("database")
>>> db_plugin.write('''
... from ..core import Application
... 
... class DatabasePlugin:
...     def connect(self):
...         return "Connected"
... ''')
>>> 
>>> # Execute the package
>>> pkg.exec_all()
>>> 
>>> # Access modules normally
>>> from myapp.core import Application
>>> app = Application()
>>> print(app.run())

>>> # Namespace package support
>>> ns_pkg = create_namespace_package("mycompany.shared")
>>> ns_pkg.add_module("common", "def helper(): return 'shared'")
"""

import sys
import os
import importlib
import importlib.util
import importlib.abc
import importlib.machinery
import threading
import time
import json
import hashlib
import weakref
from types import ModuleType, SimpleNamespace
from typing import (
    Dict, Optional, List, Set, Any, Union, Tuple, Callable,
    Iterator, Type, cast, overload, TypeVar, NamedTuple
)
from pathlib import Path
from enum import Enum, auto
from dataclasses import dataclass, field
from functools import wraps, lru_cache
from contextlib import contextmanager
from collections import defaultdict, OrderedDict
import warnings
import logging

# Import related modules
from ..core.module import (
    IOTextModule, ModuleStorageMode, ModuleState, ModuleEvent,
    open_module, create_virtual_module
)
from ..core.metadata import ModuleMetadata, DependencySpec, DependencyType
from ..ast_editor.editor import ASTEditor


class PackageType(Enum):
    """
    Types of virtual packages with different behaviors.
    
    Attributes
    ----------
    STANDARD : str
        Standard package with full __init__.py support
    
    NAMESPACE : str
        Namespace package (PEP 420) without __init__.py
    
    MODULE_ALIAS : str
        Package that aliases another module/package
    
    PROXY : str
        Proxy package that delegates to underlying implementation
    
    HYBRID : str
        Hybrid package combining virtual and filesystem modules
    """
    STANDARD = "standard"
    NAMESPACE = "namespace"
    MODULE_ALIAS = "module_alias"
    PROXY = "proxy"
    HYBRID = "hybrid"


class ImportMode(Enum):
    """
    Import resolution modes for virtual packages.
    
    Attributes
    ----------
    LAZY : str
        Modules are imported only when accessed
    
    EAGER : str
        All modules are imported immediately
    
    ON_DEMAND : str
        Modules imported on first access then cached
    
    PRELOAD : str
        Preload specified modules, lazy for others
    """
    LAZY = "lazy"
    EAGER = "eager"
    ON_DEMAND = "on_demand"
    PRELOAD = "preload"


class PackageEvent(Enum):
    """
    Events emitted during package lifecycle.
    
    Attributes
    ----------
    CREATED : auto
        Package created
    
    MODULE_ADDED : auto
        New module added to package
    
    MODULE_REMOVED : auto
        Module removed from package
    
    SUBPACKAGE_ADDED : auto
        Subpackage created
    
    SUBPACKAGE_REMOVED : auto
        Subpackage removed
    
    INIT_EXECUTED : auto
        __init__.py executed
    
    PACKAGE_LOADED : auto
        Package fully loaded
    
    PACKAGE_UNLOADED : auto
        Package unloaded from sys.modules
    
    MODULE_EXECUTED : auto
        Module executed
    
    IMPORT_RESOLVED : auto
        Import resolved through package
    
    CIRCULAR_IMPORT_DETECTED : auto
        Circular import detected
    """
    CREATED = auto()
    MODULE_ADDED = auto()
    MODULE_REMOVED = auto()
    SUBPACKAGE_ADDED = auto()
    SUBPACKAGE_REMOVED = auto()
    INIT_EXECUTED = auto()
    PACKAGE_LOADED = auto()
    PACKAGE_UNLOADED = auto()
    MODULE_EXECUTED = auto()
    IMPORT_RESOLVED = auto()
    CIRCULAR_IMPORT_DETECTED = auto()
    STATE_CHANGED = auto()


@dataclass
class PackageConfig:
    """
    Configuration for virtual package behavior.
    
    Attributes
    ----------
    package_type : PackageType
        Type of package to create
    
    import_mode : ImportMode
        How modules should be imported
    
    auto_create_modules : bool
        Automatically create modules on import attempt
    
    allow_external_imports : bool
        Allow importing from filesystem modules
    
    isolate_namespace : bool
        Isolate package namespace from parent
    
    enable_circular_detection : bool
        Detect and warn about circular imports
    
    max_recursion_depth : int
        Maximum package nesting depth
    
    enable_events : bool
        Enable event emission
    
    enable_logging : bool
        Enable package logging
    
    cache_modules : bool
        Cache imported modules
    
    lazy_init_execution : bool
        Delay __init__.py execution until needed
    
    preload_modules : List[str]
        Modules to preload if import_mode is PRELOAD
    """
    package_type: PackageType = PackageType.STANDARD
    import_mode: ImportMode = ImportMode.ON_DEMAND
    auto_create_modules: bool = False
    allow_external_imports: bool = True
    isolate_namespace: bool = False
    enable_circular_detection: bool = True
    max_recursion_depth: int = 100
    enable_events: bool = True
    enable_logging: bool = False
    cache_modules: bool = True
    lazy_init_execution: bool = False
    preload_modules: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'package_type': self.package_type.value,
            'import_mode': self.import_mode.value,
            'auto_create_modules': self.auto_create_modules,
            'allow_external_imports': self.allow_external_imports,
            'isolate_namespace': self.isolate_namespace,
            'enable_circular_detection': self.enable_circular_detection,
            'max_recursion_depth': self.max_recursion_depth,
            'enable_events': self.enable_events,
            'enable_logging': self.enable_logging,
            'cache_modules': self.cache_modules,
            'lazy_init_execution': self.lazy_init_execution,
            'preload_modules': self.preload_modules
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PackageConfig':
        """Create from dictionary."""
        return cls(
            package_type=PackageType(data.get('package_type', 'standard')),
            import_mode=ImportMode(data.get('import_mode', 'on_demand')),
            auto_create_modules=data.get('auto_create_modules', False),
            allow_external_imports=data.get('allow_external_imports', True),
            isolate_namespace=data.get('isolate_namespace', False),
            enable_circular_detection=data.get('enable_circular_detection', True),
            max_recursion_depth=data.get('max_recursion_depth', 100),
            enable_events=data.get('enable_events', True),
            enable_logging=data.get('enable_logging', False),
            cache_modules=data.get('cache_modules', True),
            lazy_init_execution=data.get('lazy_init_execution', False),
            preload_modules=data.get('preload_modules', [])
        )


@dataclass
class ImportRecord:
    """
    Record of an import operation through the virtual package.
    
    Attributes
    ----------
    module_name : str
        Full module name being imported
    
    resolved_path : List[str]
        Resolution path through package hierarchy
    
    timestamp : float
        When import occurred
    
    success : bool
        Whether import succeeded
    
    error : Optional[str]
        Error message if failed
    
    source_module : Optional[str]
        Module that triggered the import
    """
    module_name: str
    resolved_path: List[str]
    timestamp: float = field(default_factory=time.time)
    success: bool = True
    error: Optional[str] = None
    source_module: Optional[str] = None


class CircularImportError(ImportError):
    """
    Exception raised when circular import is detected.
    
    Attributes
    ----------
    cycle_path : List[str]
        The detected import cycle
    """
    
    def __init__(self, cycle_path: List[str]):
        self.cycle_path = cycle_path
        cycle_str = " -> ".join(cycle_path)
        super().__init__(f"Circular import detected: {cycle_str}")


class VirtualImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """
    Custom meta path finder and loader for virtual packages.
    
    This class implements PEP 302 import hooks to seamlessly integrate
    virtual packages with Python's import system.
    
    Attributes
    ----------
    package : VirtualPackage
        The virtual package this importer serves
    
    config : PackageConfig
        Importer configuration
    """
    
    def __init__(self, package: 'VirtualPackage', config: PackageConfig):
        """
        Initialize virtual importer.
        
        Parameters
        ----------
        package : VirtualPackage
            The virtual package to serve
        
        config : PackageConfig
            Importer configuration
        """
        self.package = package
        self.config = config
        self._logger = logging.getLogger(f"VirtualImporter.{package.full_name}")
    
    def find_spec(self, fullname: str, path: Any, target: Any = None):
        """
        Find module specification for virtual modules.
        
        Parameters
        ----------
        fullname : str
            Fully qualified module name
        
        path : Any
            Search path
        
        target : Any
            Target module
        
        Returns
        -------
        Optional[importlib.machinery.ModuleSpec]
            Module spec if found
        """
        # Check if module belongs to this package
        if not fullname.startswith(self.package.full_name):
            return None
        
        # Resolve module within package
        relative_path = fullname[len(self.package.full_name) + 1:]
        
        try:
            module = self.package.resolve_module(relative_path)
            if module:
                # Create module spec
                spec = importlib.machinery.ModuleSpec(
                    fullname,
                    self,
                    origin=f"<virtual:{fullname}>",
                    is_package=isinstance(module, VirtualPackage)
                )
                
                # Record import
                if self.config.enable_events:
                    self.package._record_import(fullname, relative_path.split('.'))
                
                return spec
        except Exception as e:
            self._logger.debug(f"Failed to resolve {fullname}: {e}")
        
        # Auto-create if configured
        if self.config.auto_create_modules:
            module = self.package.create_module(relative_path)
            if module:
                return importlib.machinery.ModuleSpec(
                    fullname,
                    self,
                    origin=f"<virtual:{fullname}>"
                )
        
        return None
    
    def create_module(self, spec):
        """
        Create module object.
        
        Parameters
        ----------
        spec : importlib.machinery.ModuleSpec
            Module specification
        
        Returns
        -------
        Optional[ModuleType]
            Module object
        """
        # Return existing module if already imported
        if spec.name in sys.modules:
            return sys.modules[spec.name]
        
        # Get or create module
        relative_path = spec.name[len(self.package.full_name) + 1:]
        module = self.package.resolve_module(relative_path)
        
        if module:
            return module.module
        elif spec.name == self.package.full_name:
            return self.package.package_module
        
        return None
    
    def exec_module(self, module):
        """
        Execute module code.
        
        Parameters
        ----------
        module : ModuleType
            Module to execute
        """
        # Module is already populated by VirtualPackage
        pass
    
    def __repr__(self):
        return f"<VirtualImporter package='{self.package.full_name}'>"


class VirtualPackage:
    """
    Advanced virtual package system with complete Python package emulation.
    
    This class provides comprehensive virtual package management with full
    support for nested modules, __init__.py execution, namespace packages,
    relative imports, and complete package lifecycle management.
    
    Attributes
    ----------
    name : str
        Package name (last component)
    
    parent : Optional['VirtualPackage']
        Parent package for nested packages
    
    full_name : str
        Fully qualified package name
    
    config : PackageConfig
        Package configuration
    
    package_module : ModuleType
        The package module object
    
    modules : Dict[str, IOTextModule]
        Modules in this package
    
    subpackages : Dict[str, 'VirtualPackage']
        Subpackages in this package
    
    _init_module : Optional[IOTextModule]
        __init__.py module
    
    _importer : VirtualImporter
        Custom importer for this package
    
    Methods
    -------
    create_module(name)
        Create a new module in this package
    
    create_subpackage(name)
        Create a nested subpackage
    
    get_init()
        Get the __init__ module
    
    exec_init()
        Execute the __init__ module
    
    exec_all()
        Execute all modules in package
    
    resolve_module(path)
        Resolve module by dot-separated path
    
    add_alias(alias_name, target)
        Create module alias
    
    export_structure()
        Export package structure as dictionary
    
    serialize(path)
        Serialize package to filesystem
    
    deserialize(path)
        Deserialize package from filesystem
    
    register_importer()
        Register custom import hook
    
    unregister_importer()
        Unregister import hook
    
    Examples
    --------
    >>> # Create a package with custom configuration
    >>> config = PackageConfig(
    ...     package_type=PackageType.STANDARD,
    ...     import_mode=ImportMode.ON_DEMAND,
    ...     enable_circular_detection=True
    ... )
    >>> pkg = VirtualPackage("myapp", config=config)
    >>> 
    >>> # Setup __init__.py
    >>> pkg.get_init().write('''
    ... __version__ = "1.0.0"
    ... 
    ... from .core import Application
    ... from .utils import helpers
    ... 
    ... __all__ = ["Application", "helpers"]
    ... ''')
    >>> 
    >>> # Create module hierarchy
    >>> core = pkg.create_module("core")
    >>> core.write('''
    ... class Application:
    ...     def __init__(self):
    ...         self.name = "MyApp"
    ... ''')
    >>> 
    >>> utils = pkg.create_module("utils")
    >>> utils.write('''
    ... def helper():
    ...     return "Utility function"
    ... ''')
    >>> 
    >>> # Register with import system
    >>> pkg.register_importer()
    >>> 
    >>> # Now can be imported normally
    >>> import myapp
    >>> from myapp.core import Application
    >>> app = Application()
    """
    
    # Class-level registry of all virtual packages
    _registry: Dict[str, weakref.ref] = {}
    _registry_lock = threading.RLock()
    
    # Class-level logger
    _logger: Optional[logging.Logger] = None
    
    def __init__(
        self,
        name: str,
        parent: Optional['VirtualPackage'] = None,
        config: Optional[PackageConfig] = None,
        module_factory: Optional[Callable[[str], IOTextModule]] = None
    ):
        """
        Initialize virtual package with comprehensive configuration.
        
        Parameters
        ----------
        name : str
            Package name (last component only, not full path)
            
        parent : Optional[VirtualPackage], optional
            Parent package for nested packages, by default None
            
        config : Optional[PackageConfig], optional
            Package configuration, by default None
            
        module_factory : Optional[Callable[[str], IOTextModule]], optional
            Custom module factory function, by default None
            
        Raises
        ------
        ValueError
            If package name is invalid
            
        Examples
        --------
        >>> # Root package
        >>> root = VirtualPackage("myapp")
        >>> 
        >>> # Subpackage (nested)
        >>> sub = VirtualPackage("plugins", parent=root)
        >>> 
        >>> # With custom configuration
        >>> config = PackageConfig(import_mode=ImportMode.EAGER)
        >>> pkg = VirtualPackage("eager_pkg", config=config)
        """
        # Validate name
        if not name or '.' in name:
            raise ValueError(f"Invalid package name: '{name}'. Use simple name without dots.")
        
        self.name = name
        self.parent = parent
        self.full_name = f"{parent.full_name}.{name}" if parent else name
        self.config = config or PackageConfig()
        self.module_factory = module_factory or self._default_module_factory
        
        # Initialize containers
        self.modules: Dict[str, IOTextModule] = OrderedDict()
        self.subpackages: Dict[str, 'VirtualPackage'] = OrderedDict()
        self._init_module: Optional[IOTextModule] = None
        self._importer: Optional[VirtualImporter] = None
        self._import_records: List[ImportRecord] = []
        self._event_handlers: Dict[PackageEvent, List[Callable]] = defaultdict(list)
        self._aliases: Dict[str, str] = {}
        self._injected_dependencies: Dict[str, Any] = {}
        self._import_stack: List[str] = []  # For circular import detection
        self._executed_init = False
        self._state_lock = threading.RLock()
        
        # Setup logging
        self._setup_logging()
        
        # Create package module
        self.package_module = self._create_package_module()
        
        # Register in sys.modules
        self._register_in_sys_modules()
        
        # Create __init__.py based on package type
        if self.config.package_type == PackageType.STANDARD:
            self._create_init_module()
        elif self.config.package_type == PackageType.NAMESPACE:
            self._setup_namespace_package()
        
        # Register in global registry
        self._register()
        
        # Create importer
        self._importer = VirtualImporter(self, self.config)
        
        # Emit creation event
        self._emit_event(PackageEvent.CREATED, package=self)
        
        self._logger.info(
            f"VirtualPackage '{self.full_name}' created "
            f"(type={self.config.package_type.value})"
        )
    
    def _setup_logging(self) -> None:
        """Setup package-specific logging."""
        if VirtualPackage._logger is None and self.config.enable_logging:
            VirtualPackage._logger = logging.getLogger("VirtualPackage")
            VirtualPackage._logger.setLevel(logging.DEBUG)
            
            if not VirtualPackage._logger.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                )
                handler.setFormatter(formatter)
                VirtualPackage._logger.addHandler(handler)
        
        self._logger = VirtualPackage._logger or logging.getLogger(__name__)
        self._logger.disabled = not self.config.enable_logging
    
    def _default_module_factory(self, name: str) -> IOTextModule:
        """
        Default factory for creating modules.
        
        Parameters
        ----------
        name : str
            Full module name
            
        Returns
        -------
        IOTextModule
            Created module
        """
        return create_virtual_module(name)
    
    def _create_package_module(self) -> ModuleType:
        """
        Create the package module object.
        
        Returns
        -------
        ModuleType
            Package module
        """
        module = ModuleType(self.full_name)
        module.__package__ = self.full_name
        module.__path__ = [f"<virtual-package:{self.full_name}>"]
        module.__file__ = f"<virtual-package:{self.full_name}>"
        module.__loader__ = self._importer
        
        # Add package metadata
        module.__virtual_package__ = True
        module.__package_config__ = self.config
        
        return module
    
    def _register_in_sys_modules(self) -> None:
        """Register package module in sys.modules."""
        if self.full_name in sys.modules:
            existing = sys.modules[self.full_name]
            if not getattr(existing, '__virtual_package__', False):
                warnings.warn(
                    f"Overwriting existing module '{self.full_name}' in sys.modules",
                    RuntimeWarning,
                    stacklevel=2
                )
        
        sys.modules[self.full_name] = self.package_module
    
    def _unregister_from_sys_modules(self) -> None:
        """Unregister package from sys.modules."""
        if self.full_name in sys.modules:
            module = sys.modules[self.full_name]
            if getattr(module, '__virtual_package__', False):
                del sys.modules[self.full_name]
    
    def _register(self) -> None:
        """Register package in global registry."""
        with self._registry_lock:
            VirtualPackage._registry[self.full_name] = weakref.ref(self)
    
    def _unregister(self) -> None:
        """Unregister package from global registry."""
        with self._registry_lock:
            VirtualPackage._registry.pop(self.full_name, None)
    
    def _create_init_module(self) -> None:
        """
        Create __init__ module for the package.
        
        This method creates a virtual __init__.py module that behaves
        exactly like a real Python package __init__.py file.
        """
        init_module = ModuleType(f"{self.full_name}.__init__")
        init_module.__package__ = self.full_name
        init_module.__file__ = f"<virtual-init:{self.full_name}>"
        init_module.__loader__ = self._importer
        
        self._init_module = IOTextModule(
            init_module,
            is_virtual=True,
            storage_mode=ModuleStorageMode.VIRTUAL
        )
        
        # Register __init__ module
        sys.modules[f"{self.full_name}.__init__"] = init_module
        
        # Set default __init__.py content
        if not self._init_module._source:
            self._init_module.write("# Virtual package __init__.py\n")
        
        # Link to package module
        self._sync_init_to_package()
    
    def _setup_namespace_package(self) -> None:
        """
        Setup namespace package according to PEP 420.
        
        Namespace packages don't have __init__.py files.
        """
        # Ensure __path__ is a list (PEP 420 requirement)
        if not hasattr(self.package_module, '__path__'):
            self.package_module.__path__ = []
        elif not isinstance(self.package_module.__path__, list):
            self.package_module.__path__ = list(self.package_module.__path__)
        
        # Add virtual path marker
        self.package_module.__path__.append(f"<virtual-namespace:{self.full_name}>")
    
    def _sync_init_to_package(self) -> None:
        """
        Synchronize __init__ module attributes to package module.
        
        This ensures that attributes defined in __init__.py are available
        directly on the package module.
        """
        if not self._init_module:
            return
        
        # Clear existing attributes (except special ones)
        preserved_keys = {
            '__name__', '__package__', '__path__', '__file__',
            '__loader__', '__spec__', '__virtual_package__',
            '__package_config__', '__doc__'
        }
        
        for key in list(self.package_module.__dict__.keys()):
            if key not in preserved_keys and not key.startswith('__'):
                delattr(self.package_module, key)
        
        # Copy init module attributes
        for key, value in self._init_module.module.__dict__.items():
            if not key.startswith('_') or key in {'__all__', '__version__', '__author__'}:
                setattr(self.package_module, key, value)
    
    def _resolve_import_path(self, import_path: str) -> List[str]:
        """
        Resolve an import path through package hierarchy.
        
        Parameters
        ----------
        import_path : str
            Dot-separated import path
            
        Returns
        -------
        List[str]
            Resolved path components
        """
        # Handle relative imports
        if import_path.startswith('.'):
            depth = len(import_path) - len(import_path.lstrip('.'))
            path_parts = import_path.lstrip('.')
            
            # Navigate up the hierarchy
            current = self
            for _ in range(depth):
                if current.parent:
                    current = current.parent
                else:
                    raise ImportError(f"Relative import beyond top-level package: {import_path}")
            
            if path_parts:
                return [current.full_name] + path_parts.split('.')
            else:
                return [current.full_name]
        
        # Absolute import
        return import_path.split('.')
    
    def _detect_circular_import(self, module_name: str) -> Optional[List[str]]:
        """
        Detect circular imports in the import stack.
        
        Parameters
        ----------
        module_name : str
            Module being imported
            
        Returns
        -------
        Optional[List[str]]
            Cycle path if detected, None otherwise
        """
        if not self.config.enable_circular_detection:
            return None
        
        if module_name in self._import_stack:
            cycle_start = self._import_stack.index(module_name)
            cycle = self._import_stack[cycle_start:] + [module_name]
            return cycle
        
        return None
    
    def _record_import(self, module_name: str, resolved_path: List[str]) -> None:
        """
        Record an import operation.
        
        Parameters
        ----------
        module_name : str
            Full module name
        
        resolved_path : List[str]
            Resolution path
        """
        source_module = self._import_stack[-1] if self._import_stack else None
        
        record = ImportRecord(
            module_name=module_name,
            resolved_path=resolved_path,
            source_module=source_module
        )
        
        self._import_records.append(record)
        
        # Limit record size
        if len(self._import_records) > 1000:
            self._import_records = self._import_records[-1000:]
        
        self._emit_event(
            PackageEvent.IMPORT_RESOLVED,
            module_name=module_name,
            resolved_path=resolved_path,
            source_module=source_module
        )
    
    @contextmanager
    def _import_context(self, module_name: str):
        """
        Context manager for import tracking and circular detection.
        
        Parameters
        ----------
        module_name : str
            Module being imported
            
        Yields
        ------
        None
            
        Raises
        ------
        CircularImportError
            If circular import detected
        """
        # Check for circular import
        cycle = self._detect_circular_import(module_name)
        if cycle:
            self._emit_event(
                PackageEvent.CIRCULAR_IMPORT_DETECTED,
                cycle_path=cycle
            )
            raise CircularImportError(cycle)
        
        self._import_stack.append(module_name)
        
        try:
            yield
        finally:
            self._import_stack.pop()
    
    def create_module(
        self,
        module_name: str,
        source_code: Optional[str] = None,
        metadata: Optional[ModuleMetadata] = None,
        auto_execute: bool = False
    ) -> IOTextModule:
        """
        Create a new module in this package.
        
        Parameters
        ----------
        module_name : str
            Name of the module to create (simple name, not full path)
            
        source_code : Optional[str], optional
            Initial module source code, by default None
            
        metadata : Optional[ModuleMetadata], optional
            Module metadata, by default None
            
        auto_execute : bool, optional
            Automatically execute module after creation, by default False
            
        Returns
        -------
        IOTextModule
            The created module
            
        Raises
        ------
        ValueError
            If module name contains dots or already exists
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> 
        >>> # Create simple module
        >>> mod = pkg.create_module("utils")
        >>> 
        >>> # Create with source code
        >>> mod = pkg.create_module(
        ...     "config",
        ...     source_code='''
        ...     DEBUG = True
        ...     VERSION = "1.0.0"
        ...     '''
        ... )
        >>> 
        >>> # Create with metadata
        >>> from iotext.core.metadata import ModuleMetadata
        >>> meta = ModuleMetadata("models", version="2.0.0")
        >>> mod = pkg.create_module("models", metadata=meta)
        """
        with self._state_lock:
            # Validate module name
            if '.' in module_name:
                raise ValueError(f"Module name cannot contain dots: '{module_name}'")
            
            if module_name in self.modules:
                self._logger.warning(f"Module '{module_name}' already exists, returning existing")
                return self.modules[module_name]
            
            if module_name in self.subpackages:
                raise ValueError(f"Cannot create module: '{module_name}' is a subpackage")
            
            full_module_name = f"{self.full_name}.{module_name}"
            
            # Create module object
            module = ModuleType(full_module_name)
            module.__package__ = self.full_name
            module.__file__ = f"<virtual-module:{full_module_name}>"
            module.__loader__ = self._importer
            
            # Create IOTextModule
            iotext_module = IOTextModule(
                module,
                is_virtual=True,
                storage_mode=ModuleStorageMode.VIRTUAL,
                enable_sandbox=self.config.package_type == PackageType.PROXY
            )
            
            # Set metadata if provided
            if metadata:
                iotext_module.metadata = metadata
            else:
                iotext_module.metadata.name = full_module_name
            
            # Write initial source
            if source_code:
                iotext_module.write(source_code)
            else:
                iotext_module.write(f"# Module: {full_module_name}\n")
            
            # Store module
            self.modules[module_name] = iotext_module
            sys.modules[full_module_name] = module
            
            # Add to package namespace
            setattr(self.package_module, module_name, module)
            
            # Auto-execute if requested
            if auto_execute:
                iotext_module.exec()
                self._emit_event(PackageEvent.MODULE_EXECUTED, module=iotext_module)
            
            # Emit event
            self._emit_event(
                PackageEvent.MODULE_ADDED,
                module_name=module_name,
                module=iotext_module
            )
            
            self._logger.info(f"Created module '{full_module_name}'")
            
            return iotext_module
    
    def create_subpackage(
        self,
        name: str,
        config: Optional[PackageConfig] = None,
        as_namespace: bool = False
    ) -> 'VirtualPackage':
        """
        Create a nested subpackage.
        
        Parameters
        ----------
        name : str
            Name of the subpackage (simple name, not full path)
            
        config : Optional[PackageConfig], optional
            Subpackage configuration, inherits from parent if None
            
        as_namespace : bool, optional
            Create as namespace package, by default False
            
        Returns
        -------
        VirtualPackage
            The created subpackage
            
        Raises
        ------
        ValueError
            If name contains dots or already exists
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> 
        >>> # Create standard subpackage
        >>> plugins = pkg.create_subpackage("plugins")
        >>> 
        >>> # Create namespace subpackage
        >>> extensions = pkg.create_subpackage("extensions", as_namespace=True)
        >>> 
        >>> # Create with custom config
        >>> config = PackageConfig(import_mode=ImportMode.EAGER)
        >>> core = pkg.create_subpackage("core", config=config)
        >>> 
        >>> # Create module in subpackage
        >>> db_plugin = plugins.create_module("database")
        """
        with self._state_lock:
            # Validate name
            if '.' in name:
                raise ValueError(f"Subpackage name cannot contain dots: '{name}'")
            
            if name in self.subpackages:
                self._logger.warning(f"Subpackage '{name}' already exists, returning existing")
                return self.subpackages[name]
            
            if name in self.modules:
                raise ValueError(f"Cannot create subpackage: '{name}' is a module")
            
            # Create subpackage configuration
            if config is None:
                config = PackageConfig(
                    package_type=PackageType.NAMESPACE if as_namespace else self.config.package_type,
                    import_mode=self.config.import_mode,
                    enable_events=self.config.enable_events,
                    enable_logging=self.config.enable_logging
                )
            elif as_namespace:
                config.package_type = PackageType.NAMESPACE
            
            # Check recursion depth
            depth = len(self.full_name.split('.'))
            if depth >= self.config.max_recursion_depth:
                raise ValueError(
                    f"Maximum package nesting depth ({self.config.max_recursion_depth}) exceeded"
                )
            
            # Create subpackage
            subpackage = VirtualPackage(
                name=name,
                parent=self,
                config=config,
                module_factory=self.module_factory
            )
            
            self.subpackages[name] = subpackage
            
            # Add to package namespace
            setattr(self.package_module, name, subpackage.package_module)
            
            # Emit event
            self._emit_event(
                PackageEvent.SUBPACKAGE_ADDED,
                subpackage_name=name,
                subpackage=subpackage
            )
            
            self._logger.info(f"Created subpackage '{subpackage.full_name}'")
            
            return subpackage
    
    def get_or_create_module(self, module_path: str) -> IOTextModule:
        """
        Get existing module or create if it doesn't exist.
        
        Parameters
        ----------
        module_path : str
            Dot-separated module path relative to this package
            
        Returns
        -------
        IOTextModule
            Existing or newly created module
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> 
        >>> # Gets existing or creates new module
        >>> utils = pkg.get_or_create_module("utils")
        >>> sub_mod = pkg.get_or_create_module("plugins.database")
        """
        parts = module_path.split('.')
        current = self
        
        # Navigate/create subpackages for all but last part
        for part in parts[:-1]:
            if part not in current.subpackages:
                current.create_subpackage(part)
            current = current.subpackages[part]
        
        # Get or create module
        module_name = parts[-1]
        if module_name not in current.modules:
            return current.create_module(module_name)
        
        return current.modules[module_name]
    
    def get_init(self) -> IOTextModule:
        """
        Get the __init__ module for this package.
        
        Returns
        -------
        IOTextModule
            The __init__ module
            
        Raises
        ------
        ValueError
            If package type doesn't support __init__.py
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> init = pkg.get_init()
        >>> init.write('''
        ... __version__ = "1.0.0"
        ... __all__ = ["core", "utils"]
        ... ''')
        >>> pkg.exec_init()
        """
        if self.config.package_type == PackageType.NAMESPACE:
            raise ValueError(f"Namespace package '{self.full_name}' has no __init__.py")
        
        if self._init_module is None:
            self._create_init_module()
        
        return self._init_module
    
    def exec_init(self, force: bool = False) -> None:
        """
        Execute the __init__ module.
        
        Parameters
        ----------
        force : bool, optional
            Force re-execution even if already executed, by default False
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> pkg.get_init().write("print('Initializing package')")
        >>> pkg.exec_init()
        Initializing package
        """
        with self._state_lock:
            if self.config.package_type == PackageType.NAMESPACE:
                self._logger.debug(f"Namespace package '{self.full_name}' has no __init__.py")
                return
            
            if self._executed_init and not force:
                self._logger.debug(f"__init__.py already executed for '{self.full_name}'")
                return
            
            if not self._init_module:
                self._create_init_module()
            
            # Apply injected dependencies
            for name, value in self._injected_dependencies.items():
                self._init_module.inject({name: value})
            
            # Execute __init__.py
            try:
                self._init_module.exec()
                self._sync_init_to_package()
                self._executed_init = True
                
                self._emit_event(PackageEvent.INIT_EXECUTED, package=self)
                self._logger.info(f"Executed __init__.py for '{self.full_name}'")
                
            except Exception as e:
                self._logger.error(f"Failed to execute __init__.py for '{self.full_name}': {e}")
                raise
    
    def exec_all(
        self,
        recursive: bool = True,
        include_init: bool = True,
        parallel: bool = False
    ) -> Dict[str, bool]:
        """
        Execute all modules in the package.
        
        Parameters
        ----------
        recursive : bool, optional
            Execute modules in subpackages too, by default True
            
        include_init : bool, optional
            Execute __init__.py, by default True
            
        parallel : bool, optional
            Execute modules in parallel threads, by default False
            
        Returns
        -------
        Dict[str, bool]
            Execution results mapping module names to success status
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> pkg.create_module("module1").write("x = 1")
        >>> pkg.create_module("module2").write("y = 2")
        >>> results = pkg.exec_all()
        >>> print(results)
        {'myapp.module1': True, 'myapp.module2': True}
        """
        results = {}
        
        # Execute __init__ first
        if include_init and self.config.package_type != PackageType.NAMESPACE:
            try:
                self.exec_init()
                results[f"{self.full_name}.__init__"] = True
            except Exception as e:
                results[f"{self.full_name}.__init__"] = False
                self._logger.error(f"__init__.py execution failed: {e}")
        
        if parallel:
            results.update(self._exec_modules_parallel())
        else:
            results.update(self._exec_modules_sequential())
        
        # Execute subpackages recursively
        if recursive:
            for subpkg in self.subpackages.values():
                sub_results = subpkg.exec_all(
                    recursive=True,
                    include_init=include_init,
                    parallel=parallel
                )
                results.update(sub_results)
        
        self._emit_event(PackageEvent.PACKAGE_LOADED, results=results)
        
        return results
    
    def _exec_modules_sequential(self) -> Dict[str, bool]:
        """Execute modules sequentially."""
        results = {}
        for name, module in self.modules.items():
            try:
                module.exec()
                results[f"{self.full_name}.{name}"] = True
                self._emit_event(PackageEvent.MODULE_EXECUTED, module=module)
            except Exception as e:
                results[f"{self.full_name}.{name}"] = False
                self._logger.error(f"Module '{name}' execution failed: {e}")
        return results
    
    def _exec_modules_parallel(self) -> Dict[str, bool]:
        """Execute modules in parallel threads."""
        import concurrent.futures
        
        results = {}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {}
            for name, module in self.modules.items():
                future = executor.submit(self._safe_exec_module, module)
                futures[future] = name
            
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    success = future.result(timeout=30)
                    results[f"{self.full_name}.{name}"] = success
                except Exception as e:
                    results[f"{self.full_name}.{name}"] = False
                    self._logger.error(f"Module '{name}' parallel execution failed: {e}")
        
        return results
    
    def _safe_exec_module(self, module: IOTextModule) -> bool:
        """
        Safely execute a module.
        
        Parameters
        ----------
        module : IOTextModule
            Module to execute
            
        Returns
        -------
        bool
            True if successful
        """
        try:
            module.exec()
            return True
        except Exception:
            return False
    
    def resolve_module(self, module_path: str) -> Optional[Union[IOTextModule, 'VirtualPackage']]:
        """
        Resolve a module or subpackage by dot-separated path.
        
        Parameters
        ----------
        module_path : str
            Dot-separated module path (e.g., "subpackage.module")
            
        Returns
        -------
        Optional[Union[IOTextModule, VirtualPackage]]
            The resolved module/subpackage or None if not found
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> plugins = pkg.create_subpackage("plugins")
        >>> db = plugins.create_module("database")
        >>> 
        >>> # Resolve module
        >>> mod = pkg.resolve_module("plugins.database")
        >>> 
        >>> # Resolve subpackage
        >>> subpkg = pkg.resolve_module("plugins")
        """
        if not module_path:
            return self
        
        with self._import_context(module_path):
            parts = module_path.split('.')
            current = self
            
            for i, part in enumerate(parts):
                if part in current.subpackages:
                    current = current.subpackages[part]
                elif part in current.modules and i == len(parts) - 1:
                    return current.modules[part]
                elif part in current._aliases:
                    alias_target = current._aliases[part]
                    return current.resolve_module(alias_target)
                else:
                    # Check if external import allowed
                    if self.config.allow_external_imports and i == 0:
                        try:
                            module = importlib.import_module(part)
                            return open_module(module)
                        except ImportError:
                            pass
                    
                    return None
            
            return current
    
    def get_module(self, module_path: str) -> Optional[IOTextModule]:
        """
        Get a module by dot-separated path.
        
        Parameters
        ----------
        module_path : str
            Dot-separated module path
            
        Returns
        -------
        Optional[IOTextModule]
            The module if found, None otherwise
        """
        result = self.resolve_module(module_path)
        if isinstance(result, IOTextModule):
            return result
        return None
    
    def get_subpackage(self, subpackage_path: str) -> Optional['VirtualPackage']:
        """
        Get a subpackage by dot-separated path.
        
        Parameters
        ----------
        subpackage_path : str
            Dot-separated subpackage path
            
        Returns
        -------
        Optional[VirtualPackage]
            The subpackage if found, None otherwise
        """
        result = self.resolve_module(subpackage_path)
        if isinstance(result, VirtualPackage):
            return result
        return None
    
    def add_alias(self, alias_name: str, target_path: str) -> None:
        """
        Create a module alias within the package.
        
        Parameters
        ----------
        alias_name : str
            Alias name to create
            
        target_path : str
            Target module path to alias
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> pkg.create_module("very_long_module_name")
        >>> pkg.add_alias("short", "very_long_module_name")
        >>> 
        >>> # Now can import as myapp.short
        """
        with self._state_lock:
            self._aliases[alias_name] = target_path
            
            # Create property for dynamic resolution
            def make_getter(target):
                def getter(obj):
                    resolved = self.resolve_module(target)
                    if resolved:
                        if isinstance(resolved, IOTextModule):
                            return resolved.module
                        elif isinstance(resolved, VirtualPackage):
                            return resolved.package_module
                    raise AttributeError(f"Cannot resolve alias target: {target}")
                return getter
            
            setattr(
                type(self.package_module),
                alias_name,
                property(make_getter(target_path))
            )
            
            self._logger.info(f"Added alias '{alias_name}' -> '{target_path}'")
    
    def inject_dependencies(self, dependencies: Dict[str, Any], recursive: bool = True) -> None:
        """
        Inject dependencies into all modules in the package.
        
        Parameters
        ----------
        dependencies : Dict[str, Any]
            Dictionary of dependency names to values
            
        recursive : bool, optional
            Inject into subpackages too, by default True
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> 
        >>> # Inject configuration and database connection
        >>> pkg.inject_dependencies({
        ...     "config": {"debug": True},
        ...     "db": database_connection,
        ...     "logger": custom_logger
        ... })
        """
        with self._state_lock:
            self._injected_dependencies.update(dependencies)
            
            # Inject into __init__
            if self._init_module:
                self._init_module.inject(dependencies)
            
            # Inject into all modules
            for module in self.modules.values():
                module.inject(dependencies)
            
            # Inject into subpackages recursively
            if recursive:
                for subpkg in self.subpackages.values():
                    subpkg.inject_dependencies(dependencies, recursive=True)
            
            self._logger.info(f"Injected {len(dependencies)} dependencies into '{self.full_name}'")
    
    def remove_module(self, module_name: str) -> bool:
        """
        Remove a module from the package.
        
        Parameters
        ----------
        module_name : str
            Name of the module to remove
            
        Returns
        -------
        bool
            True if module was removed
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> pkg.create_module("temp_module")
        >>> pkg.remove_module("temp_module")
        True
        """
        with self._state_lock:
            if module_name in self.modules:
                full_name = f"{self.full_name}.{module_name}"
                
                # Remove from sys.modules
                if full_name in sys.modules:
                    del sys.modules[full_name]
                
                # Remove from package namespace
                if hasattr(self.package_module, module_name):
                    delattr(self.package_module, module_name)
                
                # Remove module
                del self.modules[module_name]
                
                self._emit_event(
                    PackageEvent.MODULE_REMOVED,
                    module_name=module_name
                )
                
                self._logger.info(f"Removed module '{full_name}'")
                return True
            
            return False
    
    def remove_subpackage(self, subpackage_name: str) -> bool:
        """
        Remove a subpackage from the package.
        
        Parameters
        ----------
        subpackage_name : str
            Name of the subpackage to remove
            
        Returns
        -------
        bool
            True if subpackage was removed
        """
        with self._state_lock:
            if subpackage_name in self.subpackages:
                subpkg = self.subpackages[subpackage_name]
                
                # Unregister subpackage
                subpkg._unregister()
                subpkg._unregister_from_sys_modules()
                
                # Remove from package namespace
                if hasattr(self.package_module, subpackage_name):
                    delattr(self.package_module, subpackage_name)
                
                # Remove subpackage
                del self.subpackages[subpackage_name]
                
                self._emit_event(
                    PackageEvent.SUBPACKAGE_REMOVED,
                    subpackage_name=subpackage_name
                )
                
                self._logger.info(f"Removed subpackage '{subpkg.full_name}'")
                return True
            
            return False
    
    def list_modules(self, recursive: bool = False) -> List[str]:
        """
        List all modules in this package.
        
        Parameters
        ----------
        recursive : bool, optional
            Include modules from subpackages, by default False
            
        Returns
        -------
        List[str]
            List of module names (full paths if recursive)
        """
        modules = []
        
        if recursive:
            for name in self.modules.keys():
                modules.append(f"{self.full_name}.{name}")
            
            for subpkg in self.subpackages.values():
                modules.extend(subpkg.list_modules(recursive=True))
        else:
            modules = list(self.modules.keys())
        
        return modules
    
    def list_subpackages(self, recursive: bool = False) -> List[str]:
        """
        List all subpackages.
        
        Parameters
        ----------
        recursive : bool, optional
            Include nested subpackages, by default False
            
        Returns
        -------
        List[str]
            List of subpackage names (full paths if recursive)
        """
        subpackages = []
        
        if recursive:
            for name, subpkg in self.subpackages.items():
                subpackages.append(subpkg.full_name)
                subpackages.extend(subpkg.list_subpackages(recursive=True))
        else:
            subpackages = list(self.subpackages.keys())
        
        return subpackages
    
    def on(
        self,
        event: Union[PackageEvent, str],
        callback: Callable
    ) -> Callable:
        """
        Register event handler.
        
        Parameters
        ----------
        event : Union[PackageEvent, str]
            Event to listen for
            
        callback : Callable
            Function to call when event occurs
            
        Returns
        -------
        Callable
            The registered callback (for decorator use)
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> 
        >>> @pkg.on(PackageEvent.MODULE_ADDED)
        ... def on_module_added(module_name, module, **kwargs):
        ...     print(f"Module added: {module_name}")
        >>> 
        >>> @pkg.on(PackageEvent.PACKAGE_LOADED)
        ... def on_loaded(results, **kwargs):
        ...     success_count = sum(results.values())
        ...     print(f"Loaded {success_count} modules")
        """
        if self.config.enable_events:
            if isinstance(event, str):
                event = PackageEvent[event.upper()]
            
            self._event_handlers[event].append(callback)
        
        return callback
    
    def off(
        self,
        event: Union[PackageEvent, str],
        callback: Optional[Callable] = None
    ) -> None:
        """
        Remove event handler.
        
        Parameters
        ----------
        event : Union[PackageEvent, str]
            Event to remove handler from
            
        callback : Optional[Callable], optional
            Specific callback to remove, None to remove all
        """
        if isinstance(event, str):
            event = PackageEvent[event.upper()]
        
        if callback is None:
            self._event_handlers[event].clear()
        else:
            self._event_handlers[event] = [
                cb for cb in self._event_handlers[event] if cb != callback
            ]
    
    def _emit_event(self, event: PackageEvent, **kwargs) -> None:
        """
        Emit event to registered handlers.
        
        Parameters
        ----------
        event : PackageEvent
            Event to emit
            
        **kwargs
            Additional event data
        """
        if not self.config.enable_events:
            return
        
        for handler in self._event_handlers[event]:
            try:
                handler(package=self, event=event, **kwargs)
            except Exception as e:
                self._logger.error(f"Event handler error for {event}: {e}")
    
    def register_importer(self, position: int = 0) -> None:
        """
        Register custom import hook with sys.meta_path.
        
        Parameters
        ----------
        position : int, optional
            Position in sys.meta_path to insert importer, by default 0
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> pkg.register_importer()
        >>> 
        >>> # Now can be imported normally
        >>> import myapp
        >>> from myapp.module import something
        """
        if self._importer and self._importer not in sys.meta_path:
            sys.meta_path.insert(position, self._importer)
            self._logger.info(f"Registered importer for '{self.full_name}' at position {position}")
    
    def unregister_importer(self) -> None:
        """
        Unregister custom import hook.
        
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> pkg.unregister_importer()
        """
        if self._importer in sys.meta_path:
            sys.meta_path.remove(self._importer)
            self._logger.info(f"Unregistered importer for '{self.full_name}'")
    
    def export_structure(self) -> Dict[str, Any]:
        """
        Export package structure as a nested dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of package structure
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> pkg.create_module("core")
        >>> plugins = pkg.create_subpackage("plugins")
        >>> plugins.create_module("database")
        >>> 
        >>> structure = pkg.export_structure()
        >>> print(structure)
        {
            "name": "myapp",
            "type": "standard",
            "modules": {"core": {...}},
            "subpackages": {"plugins": {...}}
        }
        """
        structure = {
            "name": self.name,
            "full_name": self.full_name,
            "type": self.config.package_type.value,
            "modules": {},
            "subpackages": {},
            "aliases": self._aliases,
            "config": self.config.to_dict()
        }
        
        # Export modules
        for name, module in self.modules.items():
            structure["modules"][name] = {
                "source": module._source,
                "metadata": module.metadata.to_dict(),
                "executed": module.state == ModuleState.EXECUTED
            }
        
        # Export subpackages
        for name, subpkg in self.subpackages.items():
            structure["subpackages"][name] = subpkg.export_structure()
        
        # Export __init__.py
        if self._init_module and self._init_module._source:
            structure["init_source"] = self._init_module._source
        
        return structure
    
    def import_structure(self, structure: Dict[str, Any]) -> None:
        """
        Import package structure from dictionary.
        
        Parameters
        ----------
        structure : Dict[str, Any]
            Structure dictionary from export_structure()
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> pkg.import_structure(saved_structure)
        """
        with self._state_lock:
            # Import modules
            for name, module_data in structure.get("modules", {}).items():
                mod = self.create_module(name)
                if module_data.get("source"):
                    mod.write(module_data["source"])
                
                if module_data.get("metadata"):
                    mod.metadata = ModuleMetadata.from_dict(module_data["metadata"])
            
            # Import subpackages
            for name, subpkg_data in structure.get("subpackages", {}).items():
                subpkg = self.create_subpackage(name)
                subpkg.import_structure(subpkg_data)
            
            # Import __init__.py
            if "init_source" in structure:
                self.get_init().write(structure["init_source"])
            
            # Import aliases
            for alias, target in structure.get("aliases", {}).items():
                self.add_alias(alias, target)
    
    def serialize(self, path: Union[str, Path], include_metadata: bool = True) -> None:
        """
        Serialize package to filesystem.
        
        Parameters
        ----------
        path : Union[str, Path]
            Output directory path
            
        include_metadata : bool, optional
            Include metadata files, by default True
            
        Examples
        --------
        >>> pkg = VirtualPackage("myapp")
        >>> pkg.create_module("core").write("class App: pass")
        >>> 
        >>> # Serialize to disk
        >>> pkg.serialize("/output/myapp")
        """
        output_path = Path(path).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Write __init__.py
        if self._init_module and self._init_module._source:
            init_file = output_path / "__init__.py"
            init_file.write_text(self._init_module._source, encoding='utf-8')
        
        # Write modules
        for name, module in self.modules.items():
            module_file = output_path / f"{name}.py"
            module_file.write_text(module._source or "", encoding='utf-8')
            
            if include_metadata:
                meta_file = output_path / f"{name}.meta.json"
                meta_file.write_text(
                    json.dumps(module.metadata.to_dict(), indent=2),
                    encoding='utf-8'
                )
        
        # Write subpackages
        for name, subpkg in self.subpackages.items():
            subpkg.serialize(output_path / name, include_metadata)
        
        # Write package metadata
        if include_metadata:
            pkg_meta = output_path / "__package__.json"
            pkg_meta.write_text(
                json.dumps(self.export_structure(), indent=2, default=str),
                encoding='utf-8'
            )
        
        self._logger.info(f"Serialized package '{self.full_name}' to '{output_path}'")
    
    @classmethod
    def deserialize(
        cls,
        path: Union[str, Path],
        package_name: Optional[str] = None
    ) -> 'VirtualPackage':
        """
        Deserialize package from filesystem.
        
        Parameters
        ----------
        path : Union[str, Path]
            Input directory path
            
        package_name : Optional[str], optional
            Package name, derived from path if None
            
        Returns
        -------
        VirtualPackage
            Deserialized package
            
        Examples
        --------
        >>> pkg = VirtualPackage.deserialize("/input/myapp")
        >>> pkg.exec_all()
        """
        input_path = Path(path).resolve()
        
        if not input_path.exists():
            raise FileNotFoundError(f"Package directory not found: {input_path}")
        
        package_name = package_name or input_path.name
        pkg = cls(package_name)
        
        # Read package metadata if exists
        pkg_meta_file = input_path / "__package__.json"
        if pkg_meta_file.exists():
            structure = json.loads(pkg_meta_file.read_text(encoding='utf-8'))
            pkg.import_structure(structure)
        else:
            # Scan directory for modules
            for item in input_path.iterdir():
                if item.is_file() and item.suffix == '.py' and item.stem != '__init__':
                    module = pkg.create_module(item.stem)
                    module.write(item.read_text(encoding='utf-8'))
                
                elif item.is_dir():
                    subpkg = cls.deserialize(item, item.name)
                    pkg.subpackages[item.name] = subpkg
            
            # Read __init__.py
            init_file = input_path / "__init__.py"
            if init_file.exists():
                pkg.get_init().write(init_file.read_text(encoding='utf-8'))
        
        return pkg
    
    def get_import_records(self) -> List[ImportRecord]:
        """
        Get import operation records.
        
        Returns
        -------
        List[ImportRecord]
            List of import records
        """
        return self._import_records.copy()
    
    def clear_import_records(self) -> None:
        """Clear import operation records."""
        self._import_records.clear()
    
    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate package structure and dependencies.
        
        Returns
        -------
        Tuple[bool, List[str]]
            (is_valid, list_of_issues)
        """
        issues = []
        
        # Validate module names
        for name in self.modules.keys():
            if not name.isidentifier():
                issues.append(f"Invalid module name: '{name}'")
        
        # Validate subpackage names
        for name in self.subpackages.keys():
            if not name.isidentifier():
                issues.append(f"Invalid subpackage name: '{name}'")
        
        # Validate no name collisions
        collisions = set(self.modules.keys()) & set(self.subpackages.keys())
        if collisions:
            issues.append(f"Name collisions: {collisions}")
        
        # Validate nested packages
        for subpkg in self.subpackages.values():
            sub_valid, sub_issues = subpkg.validate()
            if not sub_valid:
                issues.extend(sub_issues)
        
        return len(issues) == 0, issues
    
    def destroy(self) -> None:
        """
        Destroy the virtual package and all its contents.
        
        This method completely removes the package from memory,
        unregisters import hooks, and cleans up sys.modules.
        
        Examples
        --------
        >>> pkg = VirtualPackage("temp_package")
        >>> # ... use package ...
        >>> pkg.destroy()  # Clean up completely
        """
        with self._state_lock:
            # Unregister importer
            self.unregister_importer()
            
            # Destroy subpackages recursively
            for subpkg in list(self.subpackages.values()):
                subpkg.destroy()
            
            # Remove modules from sys.modules
            for name, module in self.modules.items():
                full_name = f"{self.full_name}.{name}"
                if full_name in sys.modules:
                    del sys.modules[full_name]
            
            # Remove __init__ from sys.modules
            init_name = f"{self.full_name}.__init__"
            if init_name in sys.modules:
                del sys.modules[init_name]
            
            # Remove package from sys.modules
            if self.full_name in sys.modules:
                del sys.modules[self.full_name]
            
            # Clear containers
            self.modules.clear()
            self.subpackages.clear()
            self._aliases.clear()
            self._event_handlers.clear()
            
            # Unregister from global registry
            self._unregister()
            
            self._emit_event(PackageEvent.PACKAGE_UNLOADED, package=self)
            self._logger.info(f"Destroyed package '{self.full_name}'")
    
    def __getitem__(self, key: str) -> Union[IOTextModule, 'VirtualPackage']:
        """
        Get module or subpackage by name.
        
        Parameters
        ----------
        key : str
            Module or subpackage name
            
        Returns
        -------
        Union[IOTextModule, VirtualPackage]
            The requested item
            
        Raises
        ------
        KeyError
            If item not found
        """
        if key in self.modules:
            return self.modules[key]
        elif key in self.subpackages:
            return self.subpackages[key]
        else:
            raise KeyError(f"No module or subpackage named '{key}'")
    
    def __contains__(self, key: str) -> bool:
        """Check if module or subpackage exists."""
        return key in self.modules or key in self.subpackages
    
    def __iter__(self) -> Iterator[str]:
        """Iterate over module and subpackage names."""
        for name in self.modules:
            yield name
        for name in self.subpackages:
            yield name
    
    def __len__(self) -> int:
        """Return total number of modules and subpackages."""
        return len(self.modules) + len(self.subpackages)
    
    def __repr__(self) -> str:
        """Return string representation."""
        return (f"<VirtualPackage '{self.full_name}' "
                f"type={self.config.package_type.value} "
                f"modules={len(self.modules)} "
                f"subpackages={len(self.subpackages)}>")
    
    def __str__(self) -> str:
        """Return user-friendly string."""
        return f"VirtualPackage('{self.full_name}')"


def create_package(
    package_name: str,
    config: Optional[PackageConfig] = None,
    as_namespace: bool = False,
    auto_register: bool = True
) -> VirtualPackage:
    """
    Create a virtual package with full hierarchy support.
    
    Parameters
    ----------
    package_name : str
        Name of the package to create (can be dot-separated for nested packages)
        
    config : Optional[PackageConfig], optional
        Package configuration, by default None
        
    as_namespace : bool, optional
        Create as namespace package, by default False
        
    auto_register : bool, optional
        Automatically register import hook, by default True
        
    Returns
    -------
    VirtualPackage
        The created virtual package (returns innermost package for nested names)
        
    Examples
    --------
    >>> # Create simple package
    >>> pkg = create_package("myapp")
    >>> 
    >>> # Create nested package hierarchy
    >>> pkg = create_package("myapp.plugins.database")
    >>> # This creates myapp, myapp.plugins, and myapp.plugins.database
    >>> 
    >>> # Create with custom configuration
    >>> config = PackageConfig(
    ...     package_type=PackageType.STANDARD,
    ...     import_mode=ImportMode.EAGER,
    ...     enable_events=True
    ... )
    >>> pkg = create_package("myapp", config=config)
    >>> 
    >>> # Create namespace package
    >>> ns_pkg = create_package("mycompany.shared", as_namespace=True)
    """
    parts = package_name.split('.')
    
    # Create root package
    root_config = config
    if as_namespace and root_config:
        root_config.package_type = PackageType.NAMESPACE
    elif as_namespace:
        root_config = PackageConfig(package_type=PackageType.NAMESPACE)
    
    root = VirtualPackage(parts[0], config=root_config)
    current = root
    
    # Create nested packages
    for part in parts[1:]:
        if part not in current.subpackages:
            sub_config = config
            if as_namespace and sub_config:
                sub_config = PackageConfig(
                    **{**sub_config.to_dict(), 'package_type': PackageType.NAMESPACE.value}
                )
            current = current.create_subpackage(part, config=sub_config)
        else:
            current = current.subpackages[part]
    
    # Register importer for root
    if auto_register:
        root.register_importer()
    
    return current


def create_namespace_package(
    package_name: str,
    auto_register: bool = True
) -> VirtualPackage:
    """
    Create a namespace package (PEP 420 compatible).
    
    Parameters
    ----------
    package_name : str
        Name of the namespace package
        
    auto_register : bool, optional
        Automatically register import hook, by default True
        
    Returns
    -------
    VirtualPackage
        The created namespace package
        
    Examples
    --------
    >>> ns_pkg = create_namespace_package("mycompany.shared")
    >>> ns_pkg.create_module("common").write("VERSION = '1.0.0'")
    >>> 
    >>> # Can be extended with more paths later
    """
    return create_package(
        package_name,
        config=PackageConfig(package_type=PackageType.NAMESPACE),
        as_namespace=True,
        auto_register=auto_register
    )


def get_package(package_name: str) -> Optional[VirtualPackage]:
    """
    Get a registered virtual package by name.
    
    Parameters
    ----------
    package_name : str
        Fully qualified package name
        
    Returns
    -------
    Optional[VirtualPackage]
        Package if found, None otherwise
    """
    with VirtualPackage._registry_lock:
        ref = VirtualPackage._registry.get(package_name)
        if ref:
            return ref()
    return None


def list_packages() -> List[str]:
    """
    List all registered virtual packages.
    
    Returns
    -------
    List[str]
        List of package names
    """
    with VirtualPackage._registry_lock:
        return list(VirtualPackage._registry.keys())


# Export public interface
__all__ = [
    'VirtualPackage',
    'PackageConfig',
    'PackageType',
    'ImportMode',
    'PackageEvent',
    'ImportRecord',
    'CircularImportError',
    'VirtualImporter',
    'create_package',
    'create_namespace_package',
    'get_package',
    'list_packages',
]