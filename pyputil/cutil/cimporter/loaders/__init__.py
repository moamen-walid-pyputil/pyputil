#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    MODULE LOADERS
==================================

Advanced module loading system for C/C++ and Cython extensions
with cross-platform compilation, intelligent caching, dependency
resolution, and hot reloading capabilities.

This module provides a comprehensive solution for compiling and loading
native code as Python modules with enterprise-grade features.

Module Structure:
----------------
- base.py: Abstract base classes and common infrastructure
- c_loader.py: C/C++ extension module loader
- cython_loader.py: Cython module loader with .pyx compilation

Core Components:
---------------
BaseLoader: Abstract base class defining the loader interface
CLoader: C/C++ loader with multi-compiler support
CythonLoader: Cython loader with multiple backends
LoaderConfig: Comprehensive loader configuration
CompilationConfig: C/C++ compilation settings
CythonConfig: Cython-specific compilation settings
ModuleMetadata: Loaded module metadata and tracking
BatchLoader: Parallel batch loading with dependency resolution
ModuleProxy: Lazy loading proxy for deferred imports

Features:
--------
- Cross-platform compilation (GCC, Clang, MSVC, ICC)
- Intelligent caching with platform-aware keys
- Automatic header dependency resolution
- Incremental compilation (only recompile changed files)
- Parallel compilation of multiple source files
- Hot reloading with file watching
- Python C API integration
- Cython compilation with multiple backends
- Support for precompiled headers
- Unity/jumbo builds support
- Compilation database generation

Examples
--------
>>> from cimporter.loaders import CLoader, CythonLoader, LoaderConfig
>>> 
>>> # C/C++ loader
>>> loader = CLoader()
>>> module = loader.load("my_extension.c")
>>> result = module.my_function(42)
>>> 
>>> # Cython loader
>>> cython_loader = CythonLoader()
>>> module = cython_loader.load("fast_module.pyx")
>>> 
>>> # Advanced configuration
>>> config = LoaderConfig(
...     cache_enabled=True,
...     auto_reload=True,
...     track_dependencies=True,
... )
>>> loader = CLoader(config=config)
>>> 
>>> # Batch loading
>>> from cimporter.loaders import BatchLoader
>>> batch = BatchLoader(loader)
>>> results = batch.load(["kernel.c", "utils.c", "math.c"])
"""

import logging
from typing import Optional, List, Dict, Any, Union
from pathlib import Path

# ============================================================================
# Logger Setup
# ============================================================================

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# ============================================================================
# Base Loader Imports
# ============================================================================

from .base import (
    # Abstract base class
    BaseLoader,
    
    # Configuration
    LoaderConfig,
    
    # Enumerations
    LoaderState,
    LoaderEventType,
    ModuleOrigin,
    
    # Data structures
    LoaderEvent,
    ModuleMetadata,
    
    # Utilities
    ModuleProxy,
    BatchLoader,
)

# ============================================================================
# C/C++ Loader Imports
# ============================================================================

from .c_loader import (
    # Main loader class
    CLoader,
    
    # Configuration
    CompilationConfig,
    
    # Enumerations
    CSourceType,
    
    # Data structures
    CompilationUnit,
    LinkUnit,
    
    # Utilities
    DependencyParser,
)

# ============================================================================
# Cython Loader Imports
# ============================================================================

from .cython_loader import (
    # Main loader class
    CythonLoader,
    
    # Configuration
    CythonConfig,
    
    # Enumerations
    CythonDirective,
    CythonBackend,
    
    # Utilities
    CythonDependencyParser,
    CythonCompiler,
)

# ============================================================================
# Conditional Imports (Optional Features)
# ============================================================================


# Try to import sandbox for isolated compilation
try:
    from ..sandbox import SandboxManager
    _SANDBOX_AVAILABLE = True
except ImportError:
    _SANDBOX_AVAILABLE = False
    SandboxManager = None


# ============================================================================
# Global Loader Registry
# ============================================================================

# Global registry for managing multiple loader instances
_loader_registry: Dict[str, BaseLoader] = {}
_registry_lock = None

try:
    import threading
    _registry_lock = threading.RLock()
except ImportError:
    _registry_lock = None


def register_loader(name: str, loader: BaseLoader) -> None:
    """
    Register a loader instance in the global registry.
    
    Parameters
    ----------
    name : str
        Unique name for the loader.
    loader : BaseLoader
        Loader instance to register.
        
    Raises
    ------
    ValueError
        If a loader with the same name is already registered.
        
    Examples
    --------
    >>> loader = CLoader()
    >>> register_loader("default", loader)
    """
    if _registry_lock:
        with _registry_lock:
            if name in _loader_registry:
                raise ValueError(f"Loader '{name}' is already registered")
            _loader_registry[name] = loader
    else:
        if name in _loader_registry:
            raise ValueError(f"Loader '{name}' is already registered")
        _loader_registry[name] = loader


def unregister_loader(name: str) -> Optional[BaseLoader]:
    """
    Unregister a loader from the global registry.
    
    Parameters
    ----------
    name : str
        Name of the loader to unregister.
        
    Returns
    -------
    Optional[BaseLoader]
        The unregistered loader, or None if not found.
        
    Examples
    --------
    >>> loader = unregister_loader("default")
    >>> if loader:
    ...     loader.close()
    """
    if _registry_lock:
        with _registry_lock:
            return _loader_registry.pop(name, None)
    else:
        return _loader_registry.pop(name, None)


def get_loader(name: str) -> Optional[BaseLoader]:
    """
    Get a registered loader by name.
    
    Parameters
    ----------
    name : str
        Name of the loader to retrieve.
        
    Returns
    -------
    Optional[BaseLoader]
        The loader instance, or None if not found.
        
    Examples
    --------
    >>> loader = get_loader("default")
    >>> if loader:
    ...     module = loader.load("extension.c")
    """
    if _registry_lock:
        with _registry_lock:
            return _loader_registry.get(name)
    else:
        return _loader_registry.get(name)


def list_loaders() -> List[str]:
    """
    List all registered loader names.
    
    Returns
    -------
    List[str]
        List of registered loader names.
        
    Examples
    --------
    >>> names = list_loaders()
    >>> print(f"Registered loaders: {names}")
    """
    if _registry_lock:
        with _registry_lock:
            return list(_loader_registry.keys())
    else:
        return list(_loader_registry.keys())


def clear_registry() -> None:
    """
    Clear all registered loaders.
    
    Notes
    -----
    This does not close the loaders. Use close_all() to close them.
    
    Examples
    --------
    >>> clear_registry()
    """
    if _registry_lock:
        with _registry_lock:
            _loader_registry.clear()
    else:
        _loader_registry.clear()


def close_all() -> None:
    """
    Close all registered loaders and clear the registry.
    
    Examples
    --------
    >>> close_all()
    """
    if _registry_lock:
        with _registry_lock:
            for loader in _loader_registry.values():
                try:
                    loader.close()
                except Exception:
                    pass
            _loader_registry.clear()
    else:
        for loader in _loader_registry.values():
            try:
                loader.close()
            except Exception:
                pass
        _loader_registry.clear()


# ============================================================================
# Convenience Functions
# ============================================================================

def create_c_loader(
    cache_enabled: bool = True,
    cache_dir: Optional[Path] = None,
    auto_reload: bool = False,
    track_dependencies: bool = True,
    parallel: bool = True,
    compiler: Optional[str] = None,
    optimization: str = "balanced",
    simd: str = "auto",
    openmp: bool = False,
    lto: bool = False,
    debug: bool = False,
    verbose: bool = False,
) -> CLoader:
    """
    Create a configured C/C++ loader instance.
    
    This is a convenience function that creates a CLoader with common
    configuration options.
    
    Parameters
    ----------
    cache_enabled : bool
        Enable compilation cache (default: True).
    cache_dir : Optional[Path]
        Custom cache directory path.
    auto_reload : bool
        Enable automatic reloading on source changes.
    track_dependencies : bool
        Track and resolve header dependencies.
    parallel : bool
        Enable parallel compilation.
    compiler : Optional[str]
        Preferred compiler ('gcc', 'clang', 'msvc', 'icc').
    optimization : str
        Optimization level ('none', 'size', 'balanced', 'speed', 'aggressive').
    simd : str
        SIMD level ('none', 'auto', 'sse2', 'sse4', 'avx', 'avx2', 'avx512').
    openmp : bool
        Enable OpenMP parallelization.
    lto : bool
        Enable Link-Time Optimization.
    debug : bool
        Include debug symbols.
    verbose : bool
        Enable verbose output.
        
    Returns
    -------
    CLoader
        Configured C/C++ loader instance.
        
    Examples
    --------
    >>> loader = create_c_loader(
    ...     compiler="clang",
    ...     optimization="speed",
    ...     simd="avx2",
    ...     openmp=True,
    ... )
    >>> module = loader.load("extension.c")
    """
    from ..core.enums import CacheStrategy, ParallelStrategy
    
    # Build loader config
    loader_config = LoaderConfig(
        cache_enabled=cache_enabled,
        cache_strategy=CacheStrategy.NORMAL,
        parallel_strategy=ParallelStrategy.AUTO if parallel else ParallelStrategy.NONE,
        auto_reload=auto_reload,
        track_dependencies=track_dependencies,
        enable_hot_reload=auto_reload,
    )
    
    if cache_dir:
        loader_config.custom_cache_dir = cache_dir
    
    # Build compilation config
    opt_map = {
        "none": "none",
        "size": "size",
        "balanced": "balanced",
        "speed": "speed",
        "aggressive": "aggressive",
        "debug": "debug",
    }
    
    simd_map = {
        "none": "none",
        "auto": "auto",
        "sse2": "sse2",
        "sse4": "sse4.2",
        "avx": "avx",
        "avx2": "avx2",
        "avx512": "avx512",
    }
    
    from ..compilers import OptimizationPreset, SIMDPreset
    
    opt_preset = OptimizationPreset(opt_map.get(optimization, "balanced"))
    simd_preset = SIMDPreset(simd_map.get(simd, "auto"))
    
    compile_config = CompilationConfig(
        optimization_preset=opt_preset,
        simd_preset=simd_preset,
        openmp=openmp,
        lto=lto,
        debug_symbols=debug,
        verbose=verbose,
    )
    
    # Create cache manager if needed
    cache_manager = None
    if cache_enabled:
        from ..core.cache import CacheManager
        cache_manager = CacheManager(
            cache_dir=cache_dir,
            strategy=CacheStrategy.NORMAL,
        )
    
    # Detect compiler
    compiler_backend = None
    if compiler:
        from ..compilers import detect_compiler
        compiler_backend = detect_compiler(compiler)
    
    # Create loader
    loader = CLoader(
        config=loader_config,
        compile_config=compile_config,
        cache_manager=cache_manager,
        compiler_backend=compiler_backend,
    )
    
    # Register with default name
    register_loader("default", loader)
    
    return loader


def create_cython_loader(
    cache_enabled: bool = True,
    cache_dir: Optional[Path] = None,
    auto_reload: bool = False,
    track_dependencies: bool = True,
    language_level: Union[int, str] = 3,
    annotate: bool = False,
    backend: str = "cython",
    verbose: bool = False,
) -> CythonLoader:
    """
    Create a configured Cython loader instance.
    
    Parameters
    ----------
    cache_enabled : bool
        Enable compilation cache.
    cache_dir : Optional[Path]
        Custom cache directory path.
    auto_reload : bool
        Enable automatic reloading.
    track_dependencies : bool
        Track and resolve .pxd dependencies.
    language_level : Union[int, str]
        Python language level (2, 3, '3str').
    annotate : bool
        Generate HTML annotation.
    backend : str
        Cython backend ('cython', 'cythonize', 'pyximport').
    verbose : bool
        Enable verbose output.
        
    Returns
    -------
    CythonLoader
        Configured Cython loader instance.
        
    Examples
    --------
    >>> loader = create_cython_loader(
    ...     language_level=3,
    ...     annotate=True,
    ... )
    >>> module = loader.load("module.pyx")
    """
    from ..core.enums import CacheStrategy
    
    # Build loader config
    loader_config = LoaderConfig(
        cache_enabled=cache_enabled,
        cache_strategy=CacheStrategy.NORMAL,
        auto_reload=auto_reload,
        track_dependencies=track_dependencies,
        enable_hot_reload=auto_reload,
    )
    
    if cache_dir:
        loader_config.custom_cache_dir = cache_dir
    
    # Build cython config
    backend_map = {
        "cython": CythonBackend.CYTHON,
        "cythonize": CythonBackend.CYTHONIZE,
        "pyximport": CythonBackend.PYXIMPORT,
    }
    
    cython_config = CythonConfig(
        backend=backend_map.get(backend, CythonBackend.CYTHON),
        language_level=language_level,
        annotate=annotate,
    )
    
    # Create cache manager if needed
    cache_manager = None
    if cache_enabled:
        from ..core.cache import CacheManager
        cache_manager = CacheManager(
            cache_dir=cache_dir,
            strategy=CacheStrategy.NORMAL,
        )
    
    # Create loader
    loader = CythonLoader(
        config=loader_config,
        cython_config=cython_config,
        cache_manager=cache_manager,
    )
    
    # Register with default name
    register_loader("cython", loader)
    
    return loader


def get_default_loader() -> CLoader:
    """
    Get or create the default C/C++ loader.
    
    Returns
    -------
    CLoader
        Default C/C++ loader instance.
        
    Examples
    --------
    >>> loader = get_default_loader()
    >>> module = loader.load("extension.c")
    """
    loader = get_loader("default")
    if loader is None:
        loader = create_c_loader()
    if not isinstance(loader, CLoader):
        raise TypeError("Default loader is not a CLoader")
    return loader


def get_default_cython_loader() -> CythonLoader:
    """
    Get or create the default Cython loader.
    
    Returns
    -------
    CythonLoader
        Default Cython loader instance.
        
    Examples
    --------
    >>> loader = get_default_cython_loader()
    >>> module = loader.load("module.pyx")
    """
    loader = get_loader("cython")
    if loader is None:
        loader = create_cython_loader()
    if not isinstance(loader, CythonLoader):
        raise TypeError("Default loader is not a CythonLoader")
    return loader



# ============================================================================
# Module Exports
# ============================================================================

__all__ = [    
    # Base loader
    "BaseLoader",
    "LoaderConfig",
    "LoaderState",
    "LoaderEventType",
    "ModuleOrigin",
    "LoaderEvent",
    "ModuleMetadata",
    "ModuleProxy",
    "BatchLoader",
    
    # C/C++ loader
    "CLoader",
    "CompilationConfig",
    "CSourceType",
    "CompilationUnit",
    "LinkUnit",
    "DependencyParser",
    
    # Cython loader
    "CythonLoader",
    "CythonConfig",
    "CythonDirective",
    "CythonBackend",
    "CythonDependencyParser",
    "CythonCompiler",
    
    # Registry functions
    "register_loader",
    "unregister_loader",
    "get_loader",
    "list_loaders",
    "clear_registry",
    "close_all",
    
    # Convenience functions
    "create_c_loader",
    "create_cython_loader",
    "get_default_loader",
    "get_default_cython_loader",
]



# ============================================================================
# Module Cleanup
# ============================================================================

def _cleanup() -> None:
    """
    Clean up global resources on module exit.
    """
    try:
        close_all()
    except Exception:
        pass


import atexit
atexit.register(_cleanup)


# ============================================================================
# Module Information
# ============================================================================

def print_info() -> None:
    """
    Print information about the loaders module.
    
    Examples
    --------
    >>> from cimporter import loaders
    >>> loaders.print_info()
    """    
    print("Registered Loaders:")
    for name in list_loaders():
        loader = get_loader(name)
        if loader:
            stats = loader.get_stats()
            print(f"  - {name}: {loader.__class__.__name__}")
            print(f"      State: {stats.get('state', 'unknown')}")
            print(f"      Modules: {stats.get('loaded_modules_count', 0)}")
    print()
    
    print("Available Features:")
    print(f"  Hot Reload: {'✓' if _HOT_RELOAD_AVAILABLE else '✗'}")
    print(f"  Sandbox: {'✓' if _SANDBOX_AVAILABLE else '✗'}")


if __name__ == "__main__":
    print_info()