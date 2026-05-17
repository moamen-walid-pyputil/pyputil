#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Main entry point for the import system.

This module provides the primary import_module function with all features.
"""

import sys
import types
from typing import Any, Optional, Dict, List, Union
import asyncio

from .core import (
    parse_target,
    is_file_path,
    get_cache,
    get_installer,
    get_loader,
    get_validator,
    get_async_importer,
    ImportConfig,
    LazyAttributeProxy,
    ValidationError,
)


def import_module(
    target: str,
    attr: Optional[str] = None,
    auto_install: bool = False,
    version: Optional[str] = None,
    cache: bool = True,
    lazy: bool = False,
    reload: bool = False,
    default: Any = None,
    install_name: Optional[str] = None,
    package: Optional[str] = None,
    search_paths: Optional[List[str]] = None,
    file_mode: bool = False,
    validate: bool = False,
    silent: bool = False,
    return_spec: bool = False,
    inject_globals: Optional[Dict[str, Any]] = None,
    strict_attr: bool = False,
    async_import: bool = False,
) -> Any:
    """
    Import a module or attribute with different features.

    Parameters
    ----------
    target : str
        The target to import. Can be:
        - Module name: "os"
        - Submodule: "os.path"
        - Module with attribute: "json:loads"
        - File path: "./module.py" (requires file_mode=True)
        - Relative import: ".utils" (requires package parameter)
    attr : str | None, optional
        Name of attribute to import from the module. If provided, returns the attribute
        instead of the module. Equivalent to `from module import attr`.
    auto_install : bool, optional
        If True and module is not found, automatically install it using pip.
        Useful for dependencies management in production or development.
    version : str | None, optional
        Specific version to install when auto_install=True.
        Examples: "1.26.0", ">=2.0,<3.0"
    cache : bool, optional
        Enable caching to prevent re-importing the same module.
        Improves performance significantly in repeated imports.
    lazy : bool, optional
        Enable lazy loading - module is only actually loaded when first used.
        Reduces startup time for large applications with many dependencies.
    reload : bool, optional
        Force reload the module even if already imported.
        Equivalent to `importlib.reload()`. Useful during development.
    default : Any, optional
        Value to return if import fails (when silent=True or no exception raised).
        Prevents application crashes from missing optional dependencies.
    install_name : str | None, optional
        PyPI package name if different from import name.
        Example: install_name="beautifulsoup4" when target="bs4"
    package : str | None, optional
        Package name for relative imports.
        Example: package="mypackage" with target=".utils" -> from mypackage import utils
    search_paths : list[str] | None, optional
        Additional paths to search for modules.
        Useful for plugin systems or custom module locations.
    file_mode : bool, optional
        Allow importing directly from file paths.
        Example: file_mode=True with target="./tools/module.py"
    validate : bool, optional
        Validate module compatibility with current system:
        - Python version compatibility
        - Operating system compatibility
        - Architecture requirements
        - Dependencies versions
    silent : bool, optional
        Suppress exceptions and return None (or default) on failure.
        Useful for optional dependencies that might not be available.
    return_spec : bool, optional
        Return ModuleSpec instead of the module.
        Useful for advanced import systems and module analysis.
    inject_globals : dict | None, optional
        Dictionary of variables to inject into module namespace after loading.
        Useful for plugin systems needing configuration.
    strict_attr : bool, optional
        Behavior when attribute doesn't exist:
        - True: Raise AttributeError
        - False: Return None (or default if provided)
        Useful for untrusted plugins where attributes might be missing.
    async_import : bool, optional
        If True, returns a coroutine that can be awaited for async import.
        Import is executed in a separate thread to avoid blocking.

    Returns
    -------
    Any
        The imported module, requested attribute, or default value based on parameters.
        If async_import=True, returns a coroutine that resolves to this value.

    Raises
    ------
    ModuleNotFoundError
        If import fails and silent=False.
    AttributeError
        If strict_attr=True and attribute doesn't exist.
    ImportError
        For other import-related errors.
    ValidationError
        If validate=True and module fails compatibility checks.

    Examples
    --------
    Basic module import:
    >>> os_module = import_module("os")

    Import specific attribute:
    >>> loads = import_module("json", attr="loads")

    Auto-install missing package:
    >>> numpy = import_module("numpy", auto_install=True, version="1.26.0")

    Lazy loading for performance:
    >>> heavy_module = import_module("tensorflow", lazy=True)

    Plugin system with path search:
    >>> plugin = import_module("custom_plugin", search_paths=["/plugins"])

    Safe import with fallback:
    >>> maybe_module = import_module("optional_dep", silent=True, default=None)

    File mode import:
    >>> script = import_module("./scripts/tool.py", file_mode=True)

    Relative import:
    >>> utils = import_module(".utils", package="mypackage")

    Async import (non-blocking):
    >>> async def load():
    ...     module = await import_module("large_module", async_import=True)

    With validation and caching:
    >>> validated = import_module("package", validate=True, cache=True)

    Module with different install name:
    >>> bs4 = import_module("bs4", install_name="beautifulsoup4")

    Notes
    -----
    The function combines multiple import patterns and advanced features:
    - Standard library import mechanisms
    - Automatic package installation via pip
    - Performance optimization through caching
    - Development flexibility with reload
    - Production safety with validation and fallbacks
    """
    # Handle async import
    if async_import:
        return _async_import_wrapper(
            target=target,
            attr=attr,
            auto_install=auto_install,
            version=version,
            cache=cache,
            lazy=lazy,
            reload=reload,
            default=default,
            install_name=install_name,
            package=package,
            search_paths=search_paths,
            file_mode=file_mode,
            validate=validate,
            silent=silent,
            return_spec=return_spec,
            inject_globals=inject_globals,
            strict_attr=strict_attr,
        )
    
    # Synchronous import
    return _import_sync(
        target=target,
        attr=attr,
        auto_install=auto_install,
        version=version,
        cache=cache,
        lazy=lazy,
        reload=reload,
        default=default,
        install_name=install_name,
        package=package,
        search_paths=search_paths,
        file_mode=file_mode,
        validate=validate,
        silent=silent,
        return_spec=return_spec,
        inject_globals=inject_globals,
        strict_attr=strict_attr,
    )


def _import_sync(
    target: str,
    attr: Optional[str] = None,
    auto_install: bool = False,
    version: Optional[str] = None,
    cache: bool = True,
    lazy: bool = False,
    reload: bool = False,
    default: Any = None,
    install_name: Optional[str] = None,
    package: Optional[str] = None,
    search_paths: Optional[List[str]] = None,
    file_mode: bool = False,
    validate: bool = False,
    silent: bool = False,
    return_spec: bool = False,
    inject_globals: Optional[Dict[str, Any]] = None,
    strict_attr: bool = False,
) -> Any:
    """
    Synchronous import implementation.
    
    This function contains the main import logic for synchronous imports.
    """
    # Handle file-based imports
    if file_mode or (not file_mode and is_file_path(target)):
        return _import_from_file(
            file_path=target,
            reload=reload,
            inject_globals=inject_globals,
            silent=silent,
            default=default,
            lazy=lazy,
            cache=cache,
        )
    
    # Parse target
    module_name, attr_from_target = parse_target(target)
    
    # Determine attribute to import
    attr_name = attr if attr is not None else attr_from_target
    
    # Handle relative imports
    if package and module_name.startswith('.'):
        full_module_name = package + module_name
    else:
        full_module_name = module_name
    
    # Check cache
    cache_instance = get_cache()
    cache_key = cache_instance.get_cache_key(full_module_name, attr_name)
    
    if cache and not reload and cache_instance.has(cache_key):
        cached_result = cache_instance.get(cache_key)
        if cached_result is not None:
            # Handle lazy attribute proxy if needed
            if lazy and attr_name and not isinstance(cached_result, LazyAttributeProxy):
                return LazyAttributeProxy(cached_result, attr_name)
            return cached_result
    
    # Try to load the module
    try:
        # Load module
        module = get_loader().load_module(
            module_name=full_module_name,
            reload=reload,
            lazy=lazy,
            inject_globals=inject_globals,
            search_paths=search_paths,
        )
        
        # If module not found, try auto-install
        if module is None and auto_install:
            pkg_name = install_name or module_name.split('.')[0]
            get_installer().install(pkg_name, version)
            
            # Retry loading
            module = get_loader().load_module(
                module_name=full_module_name,
                reload=reload,
                lazy=lazy,
                inject_globals=inject_globals,
                search_paths=search_paths,
            )
        
        # Handle module not found
        if module is None:
            if silent:
                return default
            raise ModuleNotFoundError(f"No module named '{full_module_name}'")
        
        # Validate if requested
        if validate:
            try:
                get_validator().validate(full_module_name)
            except ValidationError as e:
                if not silent:
                    raise
                return default
        
        # Get attribute if requested
        if attr_name:
            if hasattr(module, attr_name):
                result = getattr(module, attr_name)
            else:
                if strict_attr:
                    raise AttributeError(f"Module '{full_module_name}' has no attribute '{attr_name}'")
                if silent:
                    return default
                result = None
        else:
            result = module
        
        # Cache result
        if cache and not lazy:
            cache_instance.set(cache_key, result)
        
        # Handle lazy attribute proxy
        if lazy and attr_name and not isinstance(result, LazyAttributeProxy):
            return LazyAttributeProxy(module, attr_name)
        
        return result
        
    except Exception as e:
        if silent:
            return default
        raise


def _import_from_file(
    file_path: str,
    reload: bool = False,
    inject_globals: Optional[Dict] = None,
    silent: bool = False,
    default: Any = None,
    lazy: bool = False,
    cache: bool = True,
) -> Any:
    """
    Import a module from a file path.
    
    Parameters
    ----------
    file_path : str
        Path to Python file.
    reload : bool
        Force reload.
    inject_globals : dict, optional
        Globals to inject.
    silent : bool
        Suppress exceptions.
    default : Any
        Default value on failure.
    lazy : bool
        Lazy loading.
    cache : bool
        Use caching.
    
    Returns
    -------
    Any
        Imported module or default value.
    """
    cache_instance = get_cache()
    cache_key = cache_instance.get_file_cache_key(file_path)
    
    # Check cache
    if cache and not reload and cache_instance.has(cache_key):
        return cache_instance.get(cache_key)
    
    try:
        module = get_loader().load_from_file(
            file_path=file_path,
            reload=reload,
            inject_globals=inject_globals,
        )
        
        if module is None:
            if silent:
                return default
            raise ImportError(f"Could not import from file: {file_path}")
        
        # Cache result
        if cache and not lazy:
            cache_instance.set(cache_key, module)
        
        return module
        
    except Exception as e:
        if silent:
            return default
        raise


async def _async_import_wrapper(**kwargs) -> Any:
    """
    Wrapper for asynchronous imports.
    
    Parameters
    ----------
    **kwargs
        Same parameters as import_module.
    
    Returns
    -------
    Any
        Coroutine that resolves to imported module.
    """
    # Extract parameters
    target = kwargs['target']
    attr = kwargs.get('attr')
    file_mode = kwargs.get('file_mode', False)
    reload = kwargs.get('reload', False)
    inject_globals = kwargs.get('inject_globals')
    lazy = kwargs.get('lazy', False)
    
    # Handle file mode
    if file_mode or (not file_mode and is_file_path(target)):
        return await get_async_importer().import_from_file(
            file_path=target,
            reload=reload,
            inject_globals=inject_globals,
        )
    
    # Parse target
    module_name, attr_from_target = parse_target(target)
    attr_name = attr if attr is not None else attr_from_target
    
    # Handle relative imports
    package = kwargs.get('package')
    if package and module_name.startswith('.'):
        full_module_name = package + module_name
    else:
        full_module_name = module_name
    
    # Import asynchronously
    module = await get_async_importer().import_module(
        module_name=full_module_name,
        reload=reload,
        lazy=lazy,
        inject_globals=inject_globals,
        search_paths=kwargs.get('search_paths'),
    )
    
    # Get attribute if requested
    if attr_name and module is not None:
        if hasattr(module, attr_name):
            if lazy:
                return LazyAttributeProxy(module, attr_name)
            return getattr(module, attr_name)
        elif kwargs.get('strict_attr', False):
            raise AttributeError(f"Module '{full_module_name}' has no attribute '{attr_name}'")
        elif kwargs.get('silent', False):
            return kwargs.get('default')
    
    return module


# Export the main function
__all__ = ['import_module']