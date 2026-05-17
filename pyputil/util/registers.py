#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module Registration 
===================================

A comprehensive, production-grade module registration system that provides
fine-grained control over Python's import system through manual module
registration, submodule management, namespace package support, and module
proxying capabilities.

This module extends Python's built-in import system with advanced features
for dynamic module creation, registration, and management. It supports
registering modules, submodules, namespace packages, and proxy modules
with full control over sys.modules and import behavior.

Examples
--------
>>> from pyputil.util import register, register_as_submodule, create_module
>>> 
>>> # Create and register a dynamic module
>>> my_module = create_module("my_module", {"VERSION": "1.0.0", "hello": lambda: "world"})
>>> register(my_module)
>>> 
>>> # Now you can import it
>>> import my_module
>>> print(my_module.VERSION)
1.0.0
>>> 
>>> # Register as submodule
>>> utils = create_module("utils", {"helper": lambda x: x * 2})
>>> register_as_submodule("my_package", utils, "utils")
>>> 
>>> # Create namespace package
>>> register_namespace("my_namespace")
>>> 
>>> # Register multiple modules
>>> modules = {"mod1": module1, "mod2": module2}
>>> register_many(modules)

References
----------
- PEP 302: New Import Hooks
- PEP 420: Implicit Namespace Packages
- PEP 451: ModuleSpec Type
- sys.modules: https://docs.python.org/3/library/sys.html#sys.modules
"""

import sys
import os
import importlib
import importlib.util
import importlib.machinery
import importlib.abc
import inspect
import warnings
import threading
import time
from types import ModuleType, SimpleNamespace
from pathlib import Path
from typing import (
    Optional, Dict, List, Set, Tuple, Union, Any, Callable,
    Iterator, TypeVar, cast, overload
)
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from functools import wraps, lru_cache
from contextlib import contextmanager
import shutil
import hashlib
import json
import weakref

# ============================================================================
# Platform Detection
# ============================================================================

_IS_WINDOWS: bool = sys.platform == "win32"
_IS_MACOS: bool = sys.platform == "darwin"
_IS_LINUX: bool = sys.platform.startswith("linux")
_IS_BSD: bool = any(sys.platform.startswith(p) for p in ("freebsd", "openbsd", "netbsd", "dragonfly"))
_IS_CYGWIN: bool = "cygwin" in sys.platform

# Platform-specific path handling
if _IS_WINDOWS:
    _PATH_SEP = '\\'
    _MODULE_SEP = '.'
else:
    _PATH_SEP = '/'
    _MODULE_SEP = '.'

# ============================================================================
# Enums for Configuration
# ============================================================================

class RegistrationMode(Enum):
    """
    Enumeration of module registration modes.
    
    Attributes
    ----------
    STRICT : str
        Fail if module already exists.
    FORCE : str
        Overwrite existing module.
    MERGE : str
        Merge attributes with existing module.
    SKIP : str
        Skip if module already exists.
    """
    STRICT = "strict"
    FORCE = "force"
    MERGE = "merge"
    SKIP = "skip"
    
    def __str__(self) -> str:
        return self.value


class ModuleSource(Enum):
    """
    Enumeration of module sources.
    
    Attributes
    ----------
    OBJECT : str
        Existing module object.
    FILE : str
        Python source file.
    BYTECODE : str
        Compiled bytecode file.
    DYNAMIC : str
        Dynamically created module.
    PROXY : str
        Proxy/lazy module.
    NAMESPACE : str
        Namespace package.
    """
    OBJECT = "object"
    FILE = "file"
    BYTECODE = "bytecode"
    DYNAMIC = "dynamic"
    PROXY = "proxy"
    NAMESPACE = "namespace"
    
    def __str__(self) -> str:
        return self.value


class ConflictResolution(Enum):
    """
    Enumeration of conflict resolution strategies.
    
    Attributes
    ----------
    ERROR : str
        Raise error on conflict.
    WARN : str
        Warn but continue.
    OVERWRITE : str
        Overwrite existing.
    MERGE : str
        Merge attributes.
    RENAME : str
        Rename with suffix.
    """
    ERROR = "error"
    WARN = "warn"
    OVERWRITE = "overwrite"
    MERGE = "merge"
    RENAME = "rename"
    
    def __str__(self) -> str:
        return self.value


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class RegistrationInfo:
    """
    Information about a registered module.
    
    Attributes
    ----------
    name : str
        Module name.
    module : ModuleType
        The module object.
    source : ModuleSource
        Source of the module.
    timestamp : float
        Registration timestamp.
    replaced : Optional[str]
        Name of replaced module if any.
    metadata : Dict[str, Any]
        Additional metadata.
    """
    name: str
    module: ModuleType
    source: ModuleSource
    timestamp: float = field(default_factory=time.time)
    replaced: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'module': f"<module '{self.name}'>",
            'source': str(self.source),
            'timestamp': self.timestamp,
            'replaced': self.replaced,
            'metadata': self.metadata,
        }


@dataclass
class RegistrationResult:
    """
    Result of a registration operation.
    
    Attributes
    ----------
    success : bool
        Whether registration succeeded.
    module : Optional[ModuleType]
        The registered module.
    name : str
        Registered module name.
    replaced : bool
        Whether an existing module was replaced.
    previous : Optional[ModuleType]
        Previously registered module if any.
    error : Optional[str]
        Error message if failed.
    warnings : List[str]
        Warning messages.
    """
    success: bool
    module: Optional[ModuleType] = None
    name: str = ""
    replaced: bool = False
    previous: Optional[ModuleType] = None
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'name': self.name,
            'replaced': self.replaced,
            'error': self.error,
            'warnings': self.warnings,
        }
    
    def __bool__(self) -> bool:
        return self.success


@dataclass
class RegisterConfig:
    """
    Configuration for module registration.
    
    Attributes
    ----------
    mode : RegistrationMode
        Registration mode.
    conflict : ConflictResolution
        Conflict resolution strategy.
    update_globals : bool
        Update caller's globals.
    set_attributes : Optional[Dict[str, Any]]
        Attributes to set on module.
    preserve_existing : bool
        Preserve existing module attributes.
    validate_name : bool
        Validate module name format.
    normalize_name : bool
        Normalize module name.
    thread_safe : bool
        Use thread-safe operations.
    track_registration : bool
        Track registration in history.
    """
    mode: RegistrationMode = RegistrationMode.STRICT
    conflict: ConflictResolution = ConflictResolution.ERROR
    update_globals: bool = False
    set_attributes: Optional[Dict[str, Any]] = None
    preserve_existing: bool = True
    validate_name: bool = True
    normalize_name: bool = True
    thread_safe: bool = False
    track_registration: bool = False


# ============================================================================
# Module Name Validation and Normalization
# ============================================================================

# Valid module name pattern (PEP 8)
_MODULE_NAME_PATTERN = r'^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$'

# Reserved module names
_RESERVED_MODULE_NAMES: Set[str] = {
    'sys', 'os', 'builtins', '__builtins__', '__main__',
    'importlib', 'types', 'inspect', 'warnings',
}

# Python keywords that shouldn't be module names
_PYTHON_KEYWORDS: Set[str] = {
    'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
    'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except',
    'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is',
    'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return',
    'try', 'while', 'with', 'yield',
}


def validate_module_name(name: str, strict: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Validate a module name according to Python naming rules.
    
    Parameters
    ----------
    name : str
        Module name to validate.
    strict : bool, default=True
        If True, also check against reserved names and keywords.
    
    Returns
    -------
    Tuple[bool, Optional[str]]
        (is_valid, error_message)
    
    Examples
    --------
    >>> validate_module_name("my_module")
    (True, None)
    
    >>> validate_module_name("123invalid")
    (False, "Module name must start with a letter or underscore")
    
    >>> validate_module_name("class", strict=True)
    (False, "Module name cannot be a Python keyword: 'class'")
    """
    if not name or not isinstance(name, str):
        return False, "Module name must be a non-empty string"
    
    name = name.strip()
    
    if not name:
        return False, "Module name cannot be empty"
    
    # Check for invalid characters
    if not all(c.isalnum() or c in '_.' for c in name):
        return False, "Module name can only contain letters, numbers, underscores, and dots"
    
    # Check for consecutive dots
    if '..' in name:
        return False, "Module name cannot contain consecutive dots"
    
    # Check start and end
    if name.startswith('.'):
        return False, "Module name cannot start with a dot"
    if name.endswith('.'):
        return False, "Module name cannot end with a dot"
    
    # Check each component
    for part in name.split('.'):
        if not part:
            return False, "Module name components cannot be empty"
        if not (part[0].isalpha() or part[0] == '_'):
            return False, f"Module name component '{part}' must start with a letter or underscore"
    
    if strict:
        # Check against reserved names
        top_level = name.split('.')[0]
        if top_level in _RESERVED_MODULE_NAMES:
            return False, f"Module name cannot be a reserved name: '{top_level}'"
        
        # Check against keywords
        if any(part in _PYTHON_KEYWORDS for part in name.split('.')):
            return False, f"Module name cannot contain Python keywords"
    
    return True, None


def normalize_module_name(name: str) -> str:
    """
    Normalize a module name.
    
    Parameters
    ----------
    name : str
        Module name to normalize.
    
    Returns
    -------
    str
        Normalized module name.
    
    Examples
    --------
    >>> normalize_module_name("My.Module-Name")
    'my.module_name'
    
    >>> normalize_module_name("  some.module  ")
    'some.module'
    """
    name = name.strip().lower()
    name = name.replace('-', '_')
    name = name.replace(' ', '_')
    
    # Remove invalid characters
    name = ''.join(c for c in name if c.isalnum() or c in '_.')
    
    # Ensure valid start
    if name and name[0].isdigit():
        name = '_' + name
    
    return name


# ============================================================================
# Module Creation Functions
# ============================================================================

def create_module(
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    *,
    doc: Optional[str] = None,
    package: Optional[str] = None,
    path: Optional[List[str]] = None,
    loader: Optional[Any] = None,
    spec: Optional[importlib.machinery.ModuleSpec] = None,
) -> ModuleType:
    """
    Create a new module with specified attributes.
    
    Parameters
    ----------
    name : str
        Name for the new module.
    attributes : Optional[Dict[str, Any]], default=None
        Dictionary of attributes to set on the module.
    doc : Optional[str], default=None
        Docstring for the module.
    package : Optional[str], default=None
        Package name if this is a submodule.
    path : Optional[List[str]], default=None
        __path__ for package modules.
    loader : Optional[Any], default=None
        Module loader.
    spec : Optional[importlib.machinery.ModuleSpec], default=None
        Module specification.
    
    Returns
    -------
    ModuleType
        Newly created module.
    
    Examples
    --------
    >>> mod = create_module("my_module", {"VERSION": "1.0.0", "hello": lambda: "world"})
    >>> mod.VERSION
    '1.0.0'
    >>> mod.hello()
    'world'
    
    >>> pkg = create_module("my_package", path=["/path/to/package"])
    >>> pkg.__path__
    ['/path/to/package']
    """
    module = ModuleType(name)
    
    if doc is not None:
        module.__doc__ = doc
    
    if package is not None:
        module.__package__ = package
    else:
        # Infer package from name
        if '.' in name:
            module.__package__ = name.rsplit('.', 1)[0]
        else:
            module.__package__ = ''
    
    if path is not None:
        module.__path__ = path
    elif '.' not in name:  # Top-level package
        module.__path__ = []
    
    if loader is not None:
        module.__loader__ = loader
    
    if spec is not None:
        module.__spec__ = spec
    else:
        # Create a basic spec
        module.__spec__ = importlib.machinery.ModuleSpec(
            name=name,
            loader=loader,
            origin='dynamic',
            is_package=bool(path or '.' not in name)
        )
    
    # Set custom attributes
    if attributes:
        for key, value in attributes.items():
            setattr(module, key, value)
    
    return module


def create_module_from_file(
    file_path: Union[str, Path],
    module_name: Optional[str] = None,
    *,
    load: bool = False,
) -> ModuleType:
    """
    Create a module from a Python source file.
    
    Parameters
    ----------
    file_path : Union[str, Path]
        Path to the Python file.
    module_name : Optional[str], default=None
        Name for the module. If None, inferred from file name.
    load : bool, default=False
        If True, execute the module code.
    
    Returns
    -------
    ModuleType
        Created module.
    
    Raises
    ------
    FileNotFoundError
        If file does not exist.
    
    Examples
    --------
    >>> mod = create_module_from_file("/path/to/module.py")
    >>> # With execution
    >>> mod = create_module_from_file("/path/to/module.py", load=True)
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if module_name is None:
        module_name = file_path.stem
    
    # Create spec from file
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None:
        raise ValueError(f"Could not create spec for {file_path}")
    
    module = importlib.util.module_from_spec(spec)
    
    if load and spec.loader:
        spec.loader.exec_module(module)
    
    return module


def create_module_from_dict(
    name: str,
    data: Dict[str, Any],
    *,
    deep: bool = False,
) -> ModuleType:
    """
    Create a module from a dictionary.
    
    Parameters
    ----------
    name : str
        Module name.
    data : Dict[str, Any]
        Dictionary of attributes.
    deep : bool, default=False
        If True, recursively convert nested dicts to modules.
    
    Returns
    -------
    ModuleType
        Created module.
    
    Examples
    --------
    >>> data = {
    ...     "VERSION": "1.0.0",
    ...     "config": {"debug": True, "port": 8080}
    ... }
    >>> mod = create_module_from_dict("my_module", data, deep=True)
    >>> mod.config.debug
    True
    """
    attributes = {}
    
    for key, value in data.items():
        if deep and isinstance(value, dict):
            sub_name = f"{name}.{key}"
            attributes[key] = create_module_from_dict(sub_name, value, deep=True)
        else:
            attributes[key] = value
    
    return create_module(name, attributes)


def create_namespace_module(
    name: str,
    paths: Optional[List[Union[str, Path]]] = None,
    *,
    create_paths: bool = False,
) -> ModuleType:
    """
    Create a PEP 420 namespace package module.
    
    Parameters
    ----------
    name : str
        Namespace package name.
    paths : Optional[List[Union[str, Path]]], default=None
        Search paths for the namespace.
    create_paths : bool, default=False
        If True, create directories that don't exist.
    
    Returns
    -------
    ModuleType
        Namespace package module.
    
    Examples
    --------
    >>> ns = create_namespace_module("my_namespace", paths=["/path1", "/path2"])
    >>> ns.__path__
    ['/path1', '/path2']
    """
    if paths is None:
        paths = []
    
    resolved_paths = []
    for p in paths:
        path = Path(p)
        if create_paths and not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        if path.exists():
            resolved_paths.append(str(path.absolute()))
    
    module = ModuleType(name)
    module.__package__ = name
    module.__path__ = resolved_paths
    module.__file__ = None  # Namespace packages have no file 
    module.__loader__ = None  # Namespace packages have no specified loader 
    
    # Create a ModuleSpec without submodule_search_locations in the constructor
    module.__spec__ = importlib.machinery.ModuleSpec(
        name=name,
        loader=None,
        origin='namespace',
        is_package=True,
    )

    if resolved_paths:
        module.__spec__.submodule_search_locations = resolved_paths
    
    return module


def create_proxy_module(
    name: str,
    factory: Callable[[], ModuleType],
    *,
    cache: bool = True,
) -> ModuleType:
    """
    Create a lazy-loading proxy module.
    
    The module is only loaded when its attributes are first accessed.
    
    Parameters
    ----------
    name : str
        Module name.
    factory : Callable[[], ModuleType]
        Factory function that returns the real module.
    cache : bool, default=True
        If True, cache the loaded module.
    
    Returns
    -------
    ModuleType
        Proxy module.
    
    Examples
    --------
    >>> def load_heavy_module():
    ...     # Expensive import
    ...     import numpy as np
    ...     return np
    >>> 
    >>> proxy = create_proxy_module("numpy", load_heavy_module)
    >>> # numpy is only loaded when accessed
    >>> proxy.array([1, 2, 3])
    """
    class ProxyModule(ModuleType):
        def __init__(self, name, factory, cache):
            super().__init__(name)
            self._factory = factory
            self._cache = cache
            self._module = None
            self.__doc__ = f"Proxy module for {name}"
        
        def _load(self):
            if self._module is None:
                self._module = self._factory()
                if not self._cache:
                    self._factory = None
            return self._module
        
        def __getattr__(self, name):
            return getattr(self._load(), name)
        
        def __dir__(self):
            return dir(self._load())
        
        def __repr__(self):
            if self._module is None:
                return f"<ProxyModule '{self.__name__}' (unloaded)>"
            return repr(self._module)
    
    return ProxyModule(name, factory, cache)


# ============================================================================
# Registration Functions
# ============================================================================

# Registration history for tracking
_registration_history: List[RegistrationInfo] = []
_registration_lock = threading.RLock()


def register(
    module: ModuleType,
    name: Optional[str] = None,
    *,
    mode: Union[str, RegistrationMode] = RegistrationMode.STRICT,
    conflict: Union[str, ConflictResolution] = ConflictResolution.ERROR,
    update_globals: bool = False,
    set_attributes: Optional[Dict[str, Any]] = None,
    preserve_existing: bool = True,
    validate_name: bool = True,
    normalize_name: bool = True,
    track: bool = True,
) -> RegistrationResult:
    """
    Register a module in sys.modules with advanced options.
    
    Parameters
    ----------
    module : ModuleType
        Module object to register.
    name : str, optional
        Custom name to register under. If None, uses module.__name__.
    mode : Union[str, RegistrationMode], default='strict'
        Registration mode:
        - 'strict': Fail if module exists
        - 'force': Always overwrite
        - 'merge': Merge attributes
        - 'skip': Skip if exists
    conflict : Union[str, ConflictResolution], default='error'
        Conflict resolution when module exists:
        - 'error': Raise error
        - 'warn': Warn but continue
        - 'overwrite': Overwrite existing
        - 'merge': Merge attributes
        - 'rename': Rename with suffix
    update_globals : bool, default=False
        Update caller's globals with the module.
    set_attributes : Optional[Dict[str, Any]], default=None
        Attributes to set on the module before registration.
    preserve_existing : bool, default=True
        Preserve existing module attributes when merging.
    validate_name : bool, default=True
        Validate module name format.
    normalize_name : bool, default=True
        Normalize module name before registration.
    track : bool, default=True
        Track registration in history.
    
    Returns
    -------
    RegistrationResult
        Result of the registration operation.
    
    Raises
    ------
    TypeError
        If module is not a ModuleType.
    ValueError
        If module name is invalid or registration fails.
    
    Examples
    --------
    >>> mod = create_module("my_module", {"VERSION": "1.0"})
    >>> result = register(mod)
    >>> result.success
    True
    >>> 
    >>> # Register with force mode
    >>> register(mod, mode="force")
    >>> 
    >>> # Register with merge mode
    >>> existing = sys.modules.get("my_module")
    >>> register(mod, mode="merge", preserve_existing=True)
    """
    # Validate module
    if not isinstance(module, ModuleType):
        raise TypeError(f"Expected ModuleType, got {type(module).__name__}")
    
    # Process mode
    if isinstance(mode, str):
        try:
            mode = RegistrationMode(mode.lower())
        except ValueError:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {[m.value for m in RegistrationMode]}")
    
    # Process conflict
    if isinstance(conflict, str):
        try:
            conflict = ConflictResolution(conflict.lower())
        except ValueError:
            raise ValueError(f"Invalid conflict: {conflict}. Must be one of {[c.value for c in ConflictResolution]}")
    
    # Determine module name
    module_name = name or getattr(module, "__name__", None)
    if not module_name:
        raise ValueError("Module must have a __name__ attribute or provide a name parameter")
    
    # Validate and normalize name
    if validate_name:
        is_valid, error = validate_module_name(module_name)
        if not is_valid:
            raise ValueError(f"Invalid module name '{module_name}': {error}")
    
    if normalize_name:
        module_name = normalize_module_name(module_name)
        module.__name__ = module_name
    
    result = RegistrationResult(success=False, name=module_name)
    warnings_list = []
    
    with _registration_lock:
        existing = sys.modules.get(module_name)
        
        if existing is not None:
            if mode == RegistrationMode.SKIP:
                result.success = True
                result.module = existing
                result.warnings.append(f"Module '{module_name}' already exists, skipped")
                return result
            
            if mode == RegistrationMode.STRICT and conflict == ConflictResolution.ERROR:
                raise ValueError(f"Module '{module_name}' already exists in sys.modules")
            
            # Handle conflict resolution
            if conflict == ConflictResolution.RENAME:
                suffix = 1
                while f"{module_name}_{suffix}" in sys.modules:
                    suffix += 1
                module_name = f"{module_name}_{suffix}"
                module.__name__ = module_name
                result.name = module_name
                warnings_list.append(f"Renamed to '{module_name}' due to conflict")
            
            elif conflict == ConflictResolution.WARN:
                warnings_list.append(f"Replacing existing module '{module_name}'")
                result.replaced = True
                result.previous = existing
            
            elif conflict == ConflictResolution.OVERWRITE:
                result.replaced = True
                result.previous = existing
            
            elif conflict == ConflictResolution.MERGE:
                if preserve_existing:
                    # Copy existing attributes to new module
                    for attr in dir(existing):
                        if not attr.startswith('__') or attr in ('__doc__', '__file__', '__path__'):
                            try:
                                setattr(module, attr, getattr(existing, attr))
                            except (AttributeError, TypeError):
                                pass
                result.replaced = True
                result.previous = existing
        
        # Set additional attributes
        if set_attributes:
            for key, value in set_attributes.items():
                setattr(module, key, value)
        
        # Ensure __name__ is set
        if not hasattr(module, '__name__') or module.__name__ != module_name:
            module.__name__ = module_name
        
        # Register the module
        sys.modules[module_name] = module
        result.success = True
        result.module = module
        
        # Track registration
        if track:
            _registration_history.append(RegistrationInfo(
                name=module_name,
                module=module,
                source=ModuleSource.DYNAMIC if not hasattr(module, '__file__') else ModuleSource.OBJECT,
                replaced=result.previous.__name__ if result.previous else None,
            ))
    
    # Update caller's globals
    if update_globals:
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_globals = frame.f_back.f_globals
            caller_globals[module_name.split('.')[0]] = module
    
    # Emit warnings
    for warning in warnings_list:
        warnings.warn(warning, RuntimeWarning, stacklevel=2)
        result.warnings.append(warning)
    
    return result


def register_as_submodule(
    parent_module_name: str,
    module: ModuleType,
    submodule_name: Optional[str] = None,
    *,
    create_parent: bool = False,
    parent_paths: Optional[List[str]] = None,
    **kwargs,
) -> RegistrationResult:
    """
    Register a module as a submodule of another module.
    
    Parameters
    ----------
    parent_module_name : str
        Name of the parent module.
    module : ModuleType
        Module object to register as submodule.
    submodule_name : str, optional
        Name for the submodule. If None, uses module.__name__.
    create_parent : bool, default=False
        If True, create parent module if it doesn't exist.
    parent_paths : Optional[List[str]], default=None
        __path__ for parent package if created.
    **kwargs : dict
        Additional arguments passed to `register()`.
    
    Returns
    -------
    RegistrationResult
        Result of the registration operation.
    
    Examples
    --------
    >>> utils = create_module("utils", {"helper": lambda x: x * 2})
    >>> result = register_as_submodule("my_package", utils, "utils")
    >>> 
    >>> # With parent creation
    >>> register_as_submodule("new_package", utils, "utils", create_parent=True)
    """
    # Determine submodule name
    sub_name = submodule_name or getattr(module, "__name__", None)
    if not sub_name:
        raise ValueError("Submodule must have a name")
    
    full_name = f"{parent_module_name}.{sub_name}"
    
    # Ensure parent exists
    if parent_module_name not in sys.modules:
        if create_parent:
            parent = create_namespace_module(parent_module_name, paths=parent_paths)
            register(parent, mode=RegistrationMode.FORCE, track=False)
        else:
            raise ValueError(f"Parent module '{parent_module_name}' does not exist. Use create_parent=True.")
    
    # Set package attribute
    module.__package__ = parent_module_name
    
    # Register with full name
    return register(module, name=full_name, **kwargs)


def register_many(
    modules: Dict[str, ModuleType],
    *,
    parent: Optional[str] = None,
    **kwargs,
) -> Dict[str, RegistrationResult]:
    """
    Register multiple modules at once.
    
    Parameters
    ----------
    modules : Dict[str, ModuleType]
        Dictionary mapping names to module objects.
    parent : Optional[str], default=None
        Parent package name for all modules.
    **kwargs : dict
        Additional arguments passed to `register()`.
    
    Returns
    -------
    Dict[str, RegistrationResult]
        Registration results keyed by module name.
    
    Examples
    --------
    >>> mod1 = create_module("mod1", {"value": 1})
    >>> mod2 = create_module("mod2", {"value": 2})
    >>> results = register_many({"mod1": mod1, "mod2": mod2})
    >>> results["mod1"].success
    True
    """
    results = {}
    
    for name, module in modules.items():
        full_name = f"{parent}.{name}" if parent else name
        module.__name__ = full_name
        
        try:
            results[name] = register(module, **kwargs)
        except Exception as e:
            results[name] = RegistrationResult(
                success=False,
                name=full_name,
                error=str(e),
            )
    
    return results


def register_namespace(
    name: str,
    paths: Optional[List[Union[str, Path]]] = None,
    *,
    create_paths: bool = False,
    **kwargs,
) -> RegistrationResult:
    """
    Register a PEP 420 namespace package.
    
    Parameters
    ----------
    name : str
        Namespace package name.
    paths : Optional[List[Union[str, Path]]], default=None
        Search paths for the namespace.
    create_paths : bool, default=False
        If True, create directories that don't exist.
    **kwargs : dict
        Additional arguments passed to `register()`.
    
    Returns
    -------
    RegistrationResult
        Result of the registration operation.
    
    Examples
    --------
    >>> result = register_namespace("my_namespace", paths=["/path1", "/path2"])
    >>> result.success
    True
    """
    namespace = create_namespace_module(name, paths, create_paths=create_paths)
    return register(namespace, **kwargs)


def register_from_file(
    file_path: Union[str, Path],
    module_name: Optional[str] = None,
    *,
    load: bool = False,
    **kwargs,
) -> RegistrationResult:
    """
    Register a module from a Python source file.
    
    Parameters
    ----------
    file_path : Union[str, Path]
        Path to the Python file.
    module_name : Optional[str], default=None
        Name for the module. If None, inferred from file name.
    load : bool, default=False
        If True, execute the module code.
    **kwargs : dict
        Additional arguments passed to `register()`.
    
    Returns
    -------
    RegistrationResult
        Result of the registration operation.
    
    Examples
    --------
    >>> result = register_from_file("/path/to/module.py")
    >>> result.success
    True
    """
    module = create_module_from_file(file_path, module_name, load=load)
    return register(module, **kwargs)


# ============================================================================
# Unregistration and Management Functions
# ============================================================================

def unregister(
    name: str,
    *,
    recursive: bool = False,
    ignore_missing: bool = True,
) -> Optional[ModuleType]:
    """
    Remove a module from sys.modules.
    
    Parameters
    ----------
    name : str
        Module name to unregister.
    recursive : bool, default=False
        If True, also unregister all submodules.
    ignore_missing : bool, default=True
        If True, return None for missing modules.
    
    Returns
    -------
    Optional[ModuleType]
        The removed module, or None if not found.
    
    Raises
    ------
    KeyError
        If module not found and ignore_missing=False.
    
    Examples
    --------
    >>> unregister("my_module")
    >>> 
    >>> # Unregister package and all submodules
    >>> unregister("my_package", recursive=True)
    """
    if name not in sys.modules:
        if ignore_missing:
            return None
        raise KeyError(f"Module '{name}' not found in sys.modules")
    
    if recursive:
        prefix = name + '.'
        to_remove = [n for n in sys.modules if n == name or n.startswith(prefix)]
        
        removed = None
        for n in to_remove:
            if n == name:
                removed = sys.modules.pop(n)
            else:
                sys.modules.pop(n, None)
        return removed
    
    return sys.modules.pop(name)


def unregister_many(
    names: List[str],
    *,
    recursive: bool = False,
    ignore_missing: bool = True,
) -> Dict[str, Optional[ModuleType]]:
    """
    Unregister multiple modules.
    
    Parameters
    ----------
    names : List[str]
        Module names to unregister.
    recursive : bool, default=False
        If True, also unregister submodules.
    ignore_missing : bool, default=True
        If True, ignore missing modules.
    
    Returns
    -------
    Dict[str, Optional[ModuleType]]
        Dictionary mapping names to removed modules.
    """
    return {
        name: unregister(name, recursive=recursive, ignore_missing=ignore_missing)
        for name in names
    }


def reload_module(name: str) -> Optional[ModuleType]:
    """
    Reload a registered module.
    
    Parameters
    ----------
    name : str
        Module name to reload.
    
    Returns
    -------
    Optional[ModuleType]
        Reloaded module, or None if not found.
    
    Examples
    --------
    >>> reload_module("my_module")
    """
    if name not in sys.modules:
        return None
    
    module = sys.modules[name]
    return importlib.reload(module)


def is_registered(name: str) -> bool:
    """
    Check if a module is registered in sys.modules.
    
    Parameters
    ----------
    name : str
        Module name to check.
    
    Returns
    -------
    bool
        True if registered.
    """
    return name in sys.modules


def get_registered_module(name: str) -> Optional[ModuleType]:
    """
    Get a registered module from sys.modules.
    
    Parameters
    ----------
    name : str
        Module name.
    
    Returns
    -------
    Optional[ModuleType]
        The module or None if not found.
    """
    return sys.modules.get(name)


def list_registered_modules(
    prefix: Optional[str] = None,
    *,
    include_builtins: bool = False,
) -> List[str]:
    """
    List registered modules.
    
    Parameters
    ----------
    prefix : Optional[str], default=None
        Filter by module name prefix.
    include_builtins : bool, default=False
        Include built-in modules.
    
    Returns
    -------
    List[str]
        List of module names.
    """
    modules = list(sys.modules.keys())
    
    if prefix is not None:
        modules = [m for m in modules if m.startswith(prefix)]
    
    if not include_builtins:
        modules = [m for m in modules if not m.startswith('_')]
    
    return sorted(modules)


def get_registration_history() -> List[RegistrationInfo]:
    """
    Get the registration history.
    
    Returns
    -------
    List[RegistrationInfo]
        List of registration records.
    """
    with _registration_lock:
        return _registration_history.copy()


def clear_registration_history() -> None:
    """Clear the registration history."""
    with _registration_lock:
        _registration_history.clear()


# ============================================================================
# Import Hooks
# ============================================================================

class DynamicModuleFinder(importlib.abc.MetaPathFinder):
    """
    Meta path finder for dynamically registered modules.
    
    This finder allows modules to be created on-demand when imported.
    
    Parameters
    ----------
    factories : Dict[str, Callable[[], ModuleType]]
        Mapping of module names to factory functions.
    """
    
    def __init__(self, factories: Optional[Dict[str, Callable[[], ModuleType]]] = None):
        self.factories = factories or {}
        self._lock = threading.RLock()
    
    def register_factory(self, name: str, factory: Callable[[], ModuleType]) -> None:
        """Register a module factory."""
        with self._lock:
            self.factories[name] = factory
    
    def unregister_factory(self, name: str) -> None:
        """Unregister a module factory."""
        with self._lock:
            self.factories.pop(name, None)
    
    def find_spec(self, fullname: str, path=None, target=None):
        """Find module spec."""
        with self._lock:
            if fullname in self.factories:
                return importlib.machinery.ModuleSpec(
                    fullname,
                    DynamicModuleLoader(self.factories[fullname]),
                    is_package=False,
                )
        return None


class DynamicModuleLoader(importlib.abc.Loader):
    """
    Loader for dynamically created modules.
    """
    
    def __init__(self, factory: Callable[[], ModuleType]):
        self.factory = factory
    
    def create_module(self, spec):
        """Create the module."""
        return None  # Use default module creation
    
    def exec_module(self, module):
        """Execute the module."""
        real_module = self.factory()
        module.__dict__.update(real_module.__dict__)


def install_dynamic_importer(
    factories: Optional[Dict[str, Callable[[], ModuleType]]] = None,
) -> DynamicModuleFinder:
    """
    Install a dynamic module importer in sys.meta_path.
    
    Parameters
    ----------
    factories : Optional[Dict[str, Callable[[], ModuleType]]], default=None
        Initial module factories.
    
    Returns
    -------
    DynamicModuleFinder
        The installed finder.
    
    Examples
    --------
    >>> def create_my_module():
    ...     return create_module("my_module", {"value": 42})
    >>> 
    >>> finder = install_dynamic_importer({"my_module": create_my_module})
    >>> # Now 'import my_module' will work
    """
    finder = DynamicModuleFinder(factories)
    sys.meta_path.insert(0, finder)
    return finder


# ============================================================================
# Convenience Functions
# ============================================================================

def register_function(
    name: str,
    func: Callable,
    *,
    module_name: str = "__dynamic__",
    **kwargs,
) -> RegistrationResult:
    """
    Register a single function as an importable module.
    
    Parameters
    ----------
    name : str
        Module name.
    func : Callable
        Function to make available.
    module_name : str, default="__dynamic__"
        Base module name.
    **kwargs : dict
        Additional arguments passed to `register()`.
    
    Returns
    -------
    RegistrationResult
        Registration result.
    
    Examples
    --------
    >>> def hello(name): return f"Hello, {name}!"
    >>> register_function("greet.hello", hello)
    >>> # Now you can: from greet import hello
    """
    parts = name.split('.')
    if len(parts) > 1:
        package = '.'.join(parts[:-1])
        func_name = parts[-1]
        full_name = f"{module_name}.{name}"
    else:
        package = ''
        func_name = name
        full_name = f"{module_name}.{name}"
    
    mod = create_module(full_name, {func_name: func})
    return register(mod, **kwargs)


def register_value(
    name: str,
    value: Any,
    *,
    module_name: str = "__dynamic__",
    **kwargs,
) -> RegistrationResult:
    """
    Register a value as an importable module attribute.
    
    Parameters
    ----------
    name : str
        Module/attribute name.
    value : Any
        Value to make available.
    module_name : str, default="__dynamic__"
        Base module name.
    **kwargs : dict
        Additional arguments passed to `register()`.
    
    Returns
    -------
    RegistrationResult
        Registration result.
    
    Examples
    --------
    >>> register_value("config.DEBUG", True)
    >>> # Now you can: from config import DEBUG
    """
    parts = name.split('.')
    if len(parts) > 1:
        module = '.'.join(parts[:-1])
        attr = parts[-1]
        full_name = f"{module_name}.{module}"
    else:
        attr = name
        full_name = module_name
    
    # Check if module exists
    if full_name in sys.modules:
        mod = sys.modules[full_name]
    else:
        mod = create_module(full_name)
        register(mod, **kwargs)
    
    setattr(mod, attr, value)
    return RegistrationResult(success=True, module=mod, name=full_name)


def register_alias(
    original_name: str,
    alias_name: str,
    **kwargs,
) -> RegistrationResult:
    """
    Create an alias for an existing module.
    
    Parameters
    ----------
    original_name : str
        Original module name.
    alias_name : str
        Alias name.
    **kwargs : dict
        Additional arguments passed to `register()`.
    
    Returns
    -------
    RegistrationResult
        Registration result.
    
    Examples
    --------
    >>> register_alias("numpy", "np")
    >>> # Now 'import np' works as alias for numpy
    """
    if original_name not in sys.modules:
        raise ValueError(f"Original module '{original_name}' not registered")
    
    original = sys.modules[original_name]
    return register(original, name=alias_name, **kwargs)


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    'RegistrationMode',
    'ModuleSource',
    'ConflictResolution',
    
    # Data Classes
    'RegistrationInfo',
    'RegistrationResult',
    'RegisterConfig',
    
    # Validation
    'validate_module_name',
    'normalize_module_name',
    
    # Module Creation
    'create_module',
    'create_module_from_file',
    'create_module_from_dict',
    'create_namespace_module',
    'create_proxy_module',
    
    # Registration
    'register',
    'register_as_submodule',
    'register_many',
    'register_namespace',
    'register_from_file',
    
    # Unregistration
    'unregister',
    'unregister_many',
    'reload_module',
    'is_registered',
    'get_registered_module',
    'list_registered_modules',
    
    # History
    'get_registration_history',
    'clear_registration_history',
    
    # Import Hooks
    'DynamicModuleFinder',
    'DynamicModuleLoader',
    'install_dynamic_importer',
    
    # Convenience
    'register_function',
    'register_value',
    'register_alias',
]