#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module reloading utilities with dependency tracking and safe reloading.

This module provides robust utilities for reloading Python modules and packages
at runtime, with support for recursive reloading, dependency management,
and error recovery.
"""

import importlib
import importlib.util
import sys
import shutil
import weakref
from pathlib import Path
from types import ModuleType
from typing import List, Optional, Union, Dict, Set, Any, Callable
from functools import wraps
import inspect
import logging
import time

# Configure module-level logger
logger = logging.getLogger(__name__)


class ReloadError(Exception):
    """Base exception for reload operations."""
    pass


class ModuleNotFoundError(ReloadError):
    """Raised when a module cannot be located."""
    pass


class ReloadDependencyError(ReloadError):
    """Raised when reloading fails due to dependency issues."""
    pass


class ReloadCache:
    """
    Cache for tracking module dependencies and reload state.
    
    This cache maintains a directed graph of module dependencies to enable
    safe and efficient reloading of related modules.
    
    Attributes
    ----------
    dependencies : Dict[str, Set[str]]
        Mapping from module names to sets of modules that depend on them.
    reverse_deps : Dict[str, Set[str]]
        Mapping from module names to sets of modules they depend on.
    last_reload : Dict[str, float]
        Timestamp of last reload for each module.
    """
    
    def __init__(self):
        self.dependencies: Dict[str, Set[str]] = {}
        self.reverse_deps: Dict[str, Set[str]] = {}
        self.last_reload: Dict[str, float] = {}
        self._lock = False  # Simple lock to prevent recursion
    
    def add_dependency(self, module_name: str, depends_on: str) -> None:
        """Record that module_name depends on depends_on."""
        if module_name == depends_on:
            return
        
        self.dependencies.setdefault(module_name, set()).add(depends_on)
        self.reverse_deps.setdefault(depends_on, set()).add(module_name)
    
    def get_dependents(self, module_name: str) -> Set[str]:
        """Get all modules that depend on the given module."""
        return self.reverse_deps.get(module_name, set()).copy()
    
    def get_dependencies(self, module_name: str) -> Set[str]:
        """Get all modules that the given module depends on."""
        return self.dependencies.get(module_name, set()).copy()
    
    def get_reload_order(self, module_names: Set[str]) -> List[str]:
        """
        Get topological sort order for reloading modules.
        
        Returns modules in order where dependencies are loaded before dependents.
        
        Parameters
        ----------
        module_names : Set[str]
            Set of module names to order.
            
        Returns
        -------
        List[str]
            Modules in dependency order (dependencies first).
        """
        # Build subgraph of dependencies
        graph = {name: self.get_dependencies(name) & module_names 
                 for name in module_names}
        
        # Kahn's algorithm for topological sort
        in_degree = {name: len(deps) for name, deps in graph.items()}
        queue = [name for name, degree in in_degree.items() if degree == 0]
        ordered = []
        
        while queue:
            node = queue.pop(0)
            ordered.append(node)
            
            # Update dependents
            for dependent in self.get_dependents(node) & module_names:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        # If there are cycles, return in arbitrary order
        if len(ordered) != len(module_names):
            logger.warning(f"Circular dependencies detected among {module_names}")
            return sorted(module_names)
        
        return ordered
    
    def mark_reloaded(self, module_name: str) -> None:
        """Mark module as reloaded with current timestamp."""
        self.last_reload[module_name] = time.time()
    
    def was_reloaded_recently(self, module_name: str, threshold: float = 0.1) -> bool:
        """Check if module was reloaded within threshold seconds."""
        if module_name not in self.last_reload:
            return False
        return (time.time() - self.last_reload[module_name]) < threshold


# Global cache instance
_reload_cache = ReloadCache()


def analyze_dependencies(module: ModuleType) -> Set[str]:
    """
    Analyze module dependencies by inspecting imports.
    
    Parameters
    ----------
    module : ModuleType
        Module to analyze.
        
    Returns
    -------
    Set[str]
        Set of module names this module depends on.
    """
    dependencies = set()
    module_name = module.__name__
    
    # Check __dict__ for imported modules
    for attr_name, attr_value in module.__dict__.items():
        if isinstance(attr_value, ModuleType):
            dep_name = attr_value.__name__
            if dep_name != module_name and not dep_name.startswith('_'):
                dependencies.add(dep_name)
                _reload_cache.add_dependency(module_name, dep_name)
    
    # Check __globals__ if it exists (for functions)
    for item_name, item_value in module.__dict__.items():
        if hasattr(item_value, '__globals__'):
            for dep_name, dep_value in item_value.__globals__.items():
                if isinstance(dep_value, ModuleType):
                    dep_module = dep_value.__name__
                    if dep_module != module_name and not dep_module.startswith('_'):
                        dependencies.add(dep_module)
                        _reload_cache.add_dependency(module_name, dep_module)
    
    return dependencies


def reload_module(
    module: ModuleType,
    recursive: bool = False,
    deep: bool = False,
    clean_cache: bool = True,
    preserve_attributes: Optional[List[str]] = None,
    on_error: Optional[Callable[[str, Exception], None]] = None
) -> ModuleType:
    """
    Reload a Python module or package from disk with advanced options.
    
    This function provides robust module reloading with support for recursive
    reloading of submodules, dependency tracking, and attribute preservation.
    
    Parameters
    ----------
    module : ModuleType
        The loaded Python module or package to reload.
    recursive : bool, default=False
        If True, reload all submodules recursively.
    deep : bool, default=False
        If True, also reload modules that depend on this module.
    clean_cache : bool, default=True
        If True, clean __pycache__ directories and .pyc files.
    preserve_attributes : List[str], optional
        List of attribute names to preserve from the old module.
    on_error : Callable[[str, Exception], None], optional
        Error callback function called when a submodule fails to reload.
        
    Returns
    -------
    ModuleType
        The reloaded module (fresh instance).
        
    Raises
    ------
    ModuleNotFoundError
        If the module cannot be located or loaded.
    ReloadDependencyError
        If dependency analysis or reloading fails.
        
    Examples
    --------
    >>> import mymodule
    >>> reload_module(mymodule, recursive=True)
    >>> 
    >>> # Preserve specific attributes
    >>> reload_module(mymodule, preserve_attributes=['config', 'cache'])
    
    Notes
    -----
    - Preserved attributes are copied from the old module to the new one
    - Deep reloading triggers reload of all modules that depend on this one
    - The function maintains a global dependency cache for better performance
    """
    name = module.__name__
    file_path = getattr(module, "__file__", None)
    preserve_attrs = preserve_attributes or []
    
    # Validate module
    if not name:
        raise ModuleNotFoundError("Anonymous module cannot be reloaded")
    
    if not file_path:
        raise ModuleNotFoundError(
            f"Cannot reload '{name}', no file associated (built-in module?)"
        )
    
    # Extract old attributes to preserve
    old_attrs = {}
    for attr in preserve_attrs:
        if hasattr(module, attr):
            old_attrs[attr] = getattr(module, attr)
    
    # Clean cache files if requested
    if clean_cache:
        module_path = Path(file_path).parent
        try:
            # Clean __pycache__ directories
            for cache_dir in module_path.rglob("__pycache__"):
                try:
                    shutil.rmtree(cache_dir)
                    logger.debug(f"Removed cache directory: {cache_dir}")
                except (OSError, PermissionError) as e:
                    logger.warning(f"Could not remove {cache_dir}: {e}")
            
            # Clean .pyc files
            for pyc_file in module_path.rglob("*.pyc"):
                try:
                    pyc_file.unlink()
                    logger.debug(f"Removed pyc file: {pyc_file}")
                except (OSError, PermissionError) as e:
                    logger.warning(f"Could not remove {pyc_file}: {e}")
        except Exception as e:
            logger.debug(f"Cache cleaning error (non-critical): {e}")
    
    # Analyze dependencies before reload
    if deep:
        try:
            dependencies = analyze_dependencies(module)
        except Exception as e:
            logger.warning(f"Could not analyze dependencies for {name}: {e}")
    
    # Store old module and remove from sys.modules
    old_module = sys.modules.get(name)
    sys.modules.pop(name, None)
    
    # Find and load the new module
    spec = importlib.util.find_spec(name)
    if spec is None or spec.loader is None:
        sys.modules[name] = old_module  # Restore old module on failure
        raise ModuleNotFoundError(f"Cannot find spec or loader for '{name}'")
    
    try:
        new_module = importlib.util.module_from_spec(spec)
        sys.modules[name] = new_module
        spec.loader.exec_module(new_module)
        
        # Restore preserved attributes
        for attr_name, attr_value in old_attrs.items():
            setattr(new_module, attr_name, attr_value)
        
        logger.debug(f"Reloaded module: {name}")
        
    except Exception as e:
        # Restore old module on failure
        if old_module:
            sys.modules[name] = old_module
        raise ReloadDependencyError(f"Failed to reload module '{name}': {e}") from e
    
    # Update dependency cache
    _reload_cache.mark_reloaded(name)
    
    # Handle submodules recursively
    if recursive:
        prefix = name + "."
        submodules = []
        
        # Collect all submodules that exist
        for sub_name, sub_mod in list(sys.modules.items()):
            if sub_name.startswith(prefix) and isinstance(sub_mod, ModuleType):
                submodules.append(sub_name)
        
        # Sort submodules by depth (deeper first for proper reloading)
        submodules.sort(key=lambda x: x.count('.'), reverse=True)
        
        for sub_name in submodules:
            try:
                sub_mod = sys.modules.get(sub_name)
                if sub_mod and isinstance(sub_mod, ModuleType):
                    # Avoid recursion by setting recursive=False for submodules
                    reload_module(sub_mod, recursive=False, clean_cache=False)
            except Exception as e:
                error_msg = f"Failed to reload submodule '{sub_name}': {e}"
                if on_error:
                    on_error(sub_name, e)
                else:
                    logger.warning(error_msg)
    
    # Handle deep reloading (dependents)
    if deep:
        dependents = _reload_cache.get_dependents(name)
        if dependents:
            logger.info(f"Reloading {len(dependents)} modules that depend on {name}")
            ordered_dependents = _reload_cache.get_reload_order(dependents)
            
            for dep_name in ordered_dependents:
                if dep_name in sys.modules:
                    try:
                        dep_module = sys.modules[dep_name]
                        reload_module(dep_module, recursive=False, deep=False)
                    except Exception as e:
                        error_msg = f"Failed to reload dependent '{dep_name}': {e}"
                        if on_error:
                            on_error(dep_name, e)
                        else:
                            logger.warning(error_msg)
    
    return new_module


def reload_name(
    module_name: str,
    recursive: bool = False,
    deep: bool = False,
    **kwargs
) -> ModuleType:
    """
    Reload a module by its name.
    
    Parameters
    ----------
    module_name : str
        Name of the module to reload.
    recursive : bool, default=False
        If True, reload all submodules recursively.
    deep : bool, default=False
        If True, also reload modules that depend on this module.
    **kwargs
        Additional keyword arguments passed to reload_module.
        
    Returns
    -------
    ModuleType
        The reloaded module.
        
    Raises
    ------
    ModuleNotFoundError
        If module is not found in sys.modules.
        
    Examples
    --------
    >>> reload_name('mypackage.mymodule', recursive=True, deep=True)
    """
    if module_name not in sys.modules:
        raise ModuleNotFoundError(f"Module '{module_name}' not found in sys.modules")
    
    return reload_module(
        sys.modules[module_name],
        recursive=recursive,
        deep=deep,
        **kwargs
    )


def reload_package(
    package_name: str,
    deep: bool = False,
    **kwargs
) -> ModuleType:
    """
    Reload an entire package and all its submodules.
    
    Parameters
    ----------
    package_name : str
        Name of the package to reload.
    deep : bool, default=False
        If True, also reload modules that depend on this package.
    **kwargs
        Additional keyword arguments passed to reload_module.
        
    Returns
    -------
    ModuleType
        The reloaded package.
        
    Examples
    --------
    >>> reload_package('mypackage', clean_cache=True)
    """
    return reload_name(package_name, recursive=True, deep=deep, **kwargs)


def safe_reload(
    module: Union[ModuleType, str],
    fallback: Optional[Any] = None,
    **kwargs
) -> Optional[ModuleType]:
    """
    Safely reload a module, returning a fallback value on error.
    
    Parameters
    ----------
    module : Union[ModuleType, str]
        Module instance or module name to reload.
    fallback : Any, optional
        Value to return if reload fails.
    **kwargs
        Additional keyword arguments passed to reload_module/reload_name.
        
    Returns
    -------
    Optional[ModuleType]
        Reloaded module or fallback value if provided and reload fails.
        
    Examples
    --------
    >>> result = safe_reload('mymodule', fallback=None)
    >>> if result is None:
    ...     print("Reload failed")
    """
    try:
        if isinstance(module, str):
            return reload_name(module, **kwargs)
        else:
            return reload_module(module, **kwargs)
    except Exception as e:
        logger.warning(f"Safe reload failed for {module}: {e}")
        return fallback


def reload_matching(
    pattern: str,
    attribute: str = "name",
    recursive: bool = True,
    **kwargs
) -> List[str]:
    """
    Reload modules matching a pattern.
    
    Parameters
    ----------
    pattern : str
        Pattern to match against module names or file paths.
    attribute : str, default='name'
        Attribute to match against: 'name', 'file', or 'both'.
    recursive : bool, default=True
        If True, reload matching modules recursively.
    **kwargs
        Additional keyword arguments passed to reload_module.
        
    Returns
    -------
    List[str]
        List of reloaded module names.
        
    Examples
    --------
    >>> # Reload all modules containing 'utils' in name
    >>> reload_matching('utils', attribute='name')
    >>> 
    >>> # Reload all modules in '/project/src' directory
    >>> reload_matching('/project/src', attribute='file')
    """
    reloaded = []
    
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        
        match = False
        
        if attribute in ('name', 'both'):
            if pattern in name:
                match = True
        
        if attribute in ('file', 'both'):
            file_path = getattr(module, "__file__", "")
            if file_path and pattern in file_path:
                match = True
        
        if match:
            try:
                reload_module(module, recursive=recursive, **kwargs)
                reloaded.append(name)
                logger.debug(f"Reloaded matching module: {name}")
            except Exception as e:
                logger.warning(f"Failed to reload {name}: {e}")
    
    return reloaded


def reload_current_module(
    recursive: bool = False,
    **kwargs
) -> ModuleType:
    """
    Reload the module from which this function is called.
    
    Parameters
    ----------
    recursive : bool, default=False
        If True, reload submodules recursively.
    **kwargs
        Additional keyword arguments passed to reload_module.
        
    Returns
    -------
    ModuleType
        The reloaded module.
        
    Raises
    ------
    RuntimeError
        If cannot determine the calling module.
        
    Examples
    --------
    >>> # Inside a module, reload itself
    >>> reload_current_module(recursive=True)
    """
    frame = inspect.currentframe()
    if frame is None:
        raise RuntimeError("Cannot get current frame")
    
    try:
        caller_frame = frame.f_back
        if caller_frame is None:
            raise RuntimeError("Cannot get caller frame")
        
        module_name = caller_frame.f_globals.get("__name__")
        if not module_name:
            raise RuntimeError("Cannot determine module name")
        
        return reload_name(module_name, recursive=recursive, **kwargs)
    finally:
        del frame


def get_reloadable_modules(
    include_stdlib: bool = False,
    prefix: Optional[str] = None
) -> List[str]:
    """
    List all modules that can be reloaded.
    
    Parameters
    ----------
    include_stdlib : bool, default=False
        If True, include standard library modules.
    prefix : str, optional
        Only include modules starting with this prefix.
        
    Returns
    -------
    List[str]
        Sorted list of reloadable module names.
        
    Examples
    --------
    >>> reloadable = get_reloadable_modules(prefix='myproject')
    >>> print(f"Can reload {len(reloadable)} modules")
    """
    reloadable = []
    stdlib_path = Path(sys.executable).parent / 'lib'
    
    for name, module in sys.modules.items():
        if not isinstance(module, ModuleType):
            continue
        
        if not hasattr(module, "__file__") or not module.__file__:
            continue
        
        # Skip internal modules
        if name.startswith('_') or name.startswith('importlib.'):
            continue
        
        # Filter by prefix
        if prefix and not name.startswith(prefix):
            continue
        
        # Skip stdlib unless requested
        if not include_stdlib:
            try:
                file_path = Path(module.__file__)
                if stdlib_path in file_path.parents:
                    continue
            except (TypeError, ValueError):
                pass
        
        reloadable.append(name)
    
    return sorted(reloadable)


def clear_reload_cache() -> None:
    """Clear the module dependency cache."""
    _reload_cache.dependencies.clear()
    _reload_cache.reverse_deps.clear()
    _reload_cache.last_reload.clear()
    logger.debug("Reload cache cleared")


# Convenience aliases
reload = safe_reload
reload_all = lambda prefix='', **kwargs: reload_matching(prefix, attribute='name', **kwargs)
reload_by_file = lambda pattern, **kwargs: reload_matching(pattern, attribute='file', **kwargs)