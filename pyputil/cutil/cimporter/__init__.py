#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
            PYPUTIL EXTENSION CIMPORTER PROJECT
==================================

Advanced C/C++ and Cython module loader with cross-platform compilation,
intelligent caching, dependency resolution, and hot reloading.

cimporter provides a comprehensive solution for compiling and loading
C/C++ and Cython extensions as Python modules with enterprise-grade features:

Core Features:
- Cross-platform compilation (GCC, Clang, MSVC, ICC)
- Intelligent caching with platform-aware cache keys
- Automatic dependency resolution and incremental builds
- Hot reloading with file watching
- Parallel batch compilation
- Sandboxed compilation for security
- Python C API and Cython integration

Architecture:
-------------
cimporter/
├── core/           # Core abstractions and data structures
├── compilers/      # Compiler abstraction layer
├── loaders/        # Module loaders (C/C++, Cython)
├── sandbox/        # Process isolation and security
├── utils/          # Cross-platform utilities


Quick Start:
-----------
>>> import pyputil.cutil.cimporter
>>> 
>>> # Load a C module
>>> module = cimporter.load("my_extension.c")
>>> result = module.my_function(42)
>>> 
>>> # Load with optimizations
>>> module = cimporter.load(
...     "neural_net.cpp",
...     optimization="speed",
...     simd="avx2",
...     openmp=True,
... )
>>> 
>>> # Load Cython module
>>> module = cimporter.load_cython("fast_module.pyx")
>>> 
>>> # Batch loading
>>> modules = cimporter.load_batch(["kernel.c", "utils.c", "math.c"])
>>> 
>>> # Get platform information
>>> info = cimporter.get_platform_info()
>>> print(f"Running on {info.platform_type.value} {info.architecture.value}")
"""

import sys
import os
import logging
from pathlib import Path
from typing import Optional, List, Union, Dict, Any


# ============================================================================
# Setup Logging
# ============================================================================

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def setup_logging(
    level: Union[int, str] = logging.INFO,
    format_string: Optional[str] = None,
    log_file: Optional[Path] = None,
) -> None:
    """
    Setup logging for the cimporter system.
    
    Parameters
    ----------
    level : Union[int, str]
        Logging level (default: INFO).
    format_string : Optional[str]
        Custom format string for log messages.
    log_file : Optional[Path]
        Path to log file (logs to stderr if None).
        
    Examples
    --------
    >>> import pyputil.cutil.cimporter
    >>> cimporter.setup_logging(level="DEBUG", log_file=Path("cimporter.log"))
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    
    if format_string is None:
        format_string = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
    
    handlers = []
    
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(str(log_file)))
    else:
        handlers.append(logging.StreamHandler(sys.stderr))
    
    logging.basicConfig(
        level=level,
        format=format_string,
        handlers=handlers,
    )


# ============================================================================
# Core Imports
# ============================================================================

# Core enums and exceptions
from .core.enums import (
    OptimizationLevel,
    SIMDLevel,
    CompilerFamily,
    BuildMode,
    CacheStrategy,
    ParallelStrategy,
    LanguageStandard,
    LinkType,
    SandboxPolicy,
    LogLevel,
    DependencyType,
)

from .core.exceptions import (
    CImporterBaseException,
    CompileError,
    LinkerError,
    CacheError,
    ImportModuleError,
    DependencyError,
    PlatformError,
    SandboxError as CoreSandboxError,
    ConfigError,
    ErrorCategory,
    ErrorSeverity,
)

from .core.cache import (
    CacheKey,
    CacheKeyBuilder,
    CacheMetadata,
    CacheManager,
    FilesystemCacheBackend,
)

from .core.config import (
    CompilerConfig as CoreCompilerConfig,
    OptimizationConfig as CoreOptimizationConfig,
    DebugConfig as CoreDebugConfig,
    BuildConfig as CoreBuildConfig,
    CacheConfig as CoreCacheConfig,
    SandboxConfig as CoreSandboxConfig,
    PythonConfig as CorePythonConfig,
    CImporterConfig as CoreCImporterConfig,
)


# ============================================================================
# Compiler Imports
# ============================================================================

from .compilers import (
    # Base classes
    CompilerBackend,
    CompilerInfo,
    CompilerFeature,
    CompileResult,
    PreprocessResult,
    
    # Implementations
    GCCBackend,
    ClangBackend,
    MSVCBackend,
    ICCBackend,
    
    # Detection
    CompilerDetector,
    CompilerRegistry,
    CompilerCandidate,
    CompilerPriority,
    detect_compiler,
    list_compilers,
    get_compiler_registry,
    get_compiler_backend,
    get_best_compiler,
    has_compiler,
    
    # Flag normalization
    FlagNormalizer,
    FlagMapper,
    FlagMapping,
    OptimizationPreset,
    SIMDPreset,
    WarningPreset,
    LanguageStandardPreset,
    SanitizerPreset,
    LinkerPreset,
    normalize_flags,
    get_optimization_flags,
)



# ============================================================================
# Loader Imports
# ============================================================================

from .loaders import (
    # Base classes
    BaseLoader,
    LoaderConfig,
    LoaderState,
    LoaderEvent,
    LoaderEventType,
    ModuleMetadata,
    ModuleOrigin,
    ModuleProxy,
    BatchLoader,
    
    # C/C++ loader
    CLoader,
    CompilationConfig,
    
    # Cython loader
    CythonLoader,
    CythonConfig,
    CythonDirective,
    CythonBackend,
)

# ============================================================================
# Sandbox Imports
# ============================================================================

from .sandbox import (
    # Main classes
    SandboxManager,
    ProcessIsolator,
    ResourceLimits,
    SandboxPolicy as SandboxPolicyEnum,
    SandboxResult,
    
    # Exceptions
    SandboxError,
    SandboxViolation,
    SandboxTimeoutError,
    SandboxMemoryError,
    
    # Limiters
    CPULimiter,
    MemoryLimiter,
    DiskLimiter,
    ProcessLimiter,
    NetworkBlocker,
    
    # Filesystem isolation
    FilesystemJail,
    TempWorkspace,
    PathRestriction,
)

# Windows-specific (conditional)
try:
    from .sandbox import (
        WindowsJobObject,
        WindowsProcessGroup,
        WindowsTokenPrivileges,
        WindowsRestrictedToken,
        WindowsProcessMitigations,
    )
    _WINDOWS_SANDBOX_AVAILABLE = True
except ImportError:
    _WINDOWS_SANDBOX_AVAILABLE = False
    WindowsJobObject = None
    WindowsProcessGroup = None
    WindowsTokenPrivileges = None
    WindowsRestrictedToken = None
    WindowsProcessMitigations = None

# ============================================================================
# Utils Imports
# ============================================================================

from .utils import (
    # Platform utilities
    get_platform,
    get_platform_info,
    get_architecture,
    get_system,
    get_machine,
    get_processor,
    get_python_version,
    get_python_implementation,
    get_shared_library_extension,
    get_executable_extension,
    get_python_include_paths,
    get_python_library_paths,
    get_python_library_name,
    get_python_library_full_path,
    get_python_config_var,
    get_python_extension_suffix,
    get_object_extension,
    get_static_library_extension,
    is_windows,
    is_linux,
    is_macos,
    is_bsd,
    is_unix,
    is_64bit,
    is_32bit,
    is_arm,
    is_x86,
    PlatformInfo,
    PlatformType,
    ArchitectureType,
    
    # Checksum utilities
    compute_checksum,
    compute_file_hash,
    compute_string_hash,
    compute_bytes_hash,
    verify_checksum,
    compare_files,
    hash_string,
    hash_file,
    get_file_checksum,
    HashAlgorithm,
    ChecksumResult,
    StreamingHashReader,
    IncrementalHasher,

    # System utilities
    CommandResult,
    CommandError,
    TimeoutError,
    run_command,
    run_command_sync,
    run_command_async,
    run_commands_parallel,
    get_environment,
    set_environment,
    get_env,
    set_env,
    unset_env,
    prepend_path,
    append_path,
    get_cpu_count,
    get_memory_info,
    get_disk_usage,
    get_process_id,
    get_process_parent_id,
    is_process_running,
    kill_process,
    kill_process_tree,
    get_child_processes,
    get_process_info,
    SignalHandler,
    send_signal,
    send_signal_to_group,
    create_process_group,
    get_process_group,
    TempFile,
    TempDirectory,
    create_temp_file,
    create_temp_directory,
)

# ============================================================================
# Global Instances and Convenience Functions
# ============================================================================

# Global loader instances (lazy initialized)
_global_c_loader: Optional[CLoader] = None
_global_cython_loader: Optional[CythonLoader] = None
_global_loader_config: Optional[LoaderConfig] = None
_global_compile_config: Optional[CompilationConfig] = None


def get_c_loader(
    config: Optional[LoaderConfig] = None,
    compile_config: Optional[CompilationConfig] = None,
    cache_dir: Optional[Path] = None,
    compiler: Optional[str] = None,
) -> CLoader:
    """
    Get or create a global C/C++ loader instance.
    
    Parameters
    ----------
    config : Optional[LoaderConfig]
        Loader configuration.
    compile_config : Optional[CompilationConfig]
        Compilation configuration.
    cache_dir : Optional[Path]
        Cache directory path.
    compiler : Optional[str]
        Preferred compiler name.
        
    Returns
    -------
    CLoader
        C/C++ loader instance.
        
    Examples
    --------
    >>> loader = cimporter.get_c_loader(
    ...     compiler="clang",
    ...     cache_dir=Path(".cache")
    ... )
    >>> module = loader.load("extension.c")
    """
    global _global_c_loader, _global_loader_config, _global_compile_config
    
    if _global_c_loader is None or config or compile_config:
        if config:
            _global_loader_config = config
        else:
            _global_loader_config = LoaderConfig(
                cache_enabled=cache_dir is not None,
                cache_strategy=CacheStrategy.NORMAL,
                parallel_strategy=ParallelStrategy.AUTO,
                track_dependencies=True,
                enable_hot_reload=False,
            )
        
        if compile_config:
            _global_compile_config = compile_config
        else:
            _global_compile_config = CompilationConfig(
                optimization_preset=OptimizationPreset.BALANCED,
                simd_preset=SIMDPreset.AUTO,
                warning_level=WarningPreset.NORMAL,
                link_type=LinkType.MODULE,
            )
        
        cache_manager = None
        if cache_dir:
            cache_manager = CacheManager(cache_dir=cache_dir)
        
        _global_c_loader = CLoader(
            config=_global_loader_config,
            compile_config=_global_compile_config,
            cache_manager=cache_manager,
            compiler_backend=detect_compiler(compiler) if compiler else None,
        )
    
    return _global_c_loader


def get_cython_loader(
    config: Optional[LoaderConfig] = None,
    cython_config: Optional[CythonConfig] = None,
    cache_dir: Optional[Path] = None,
) -> CythonLoader:
    """
    Get or create a global Cython loader instance.
    
    Parameters
    ----------
    config : Optional[LoaderConfig]
        Loader configuration.
    cython_config : Optional[CythonConfig]
        Cython configuration.
    cache_dir : Optional[Path]
        Cache directory path.
        
    Returns
    -------
    CythonLoader
        Cython loader instance.
        
    Examples
    --------
    >>> loader = cimporter.get_cython_loader()
    >>> module = loader.load("module.pyx")
    """
    global _global_cython_loader, _global_loader_config
    
    if _global_cython_loader is None or config:
        if config:
            _global_loader_config = config
        else:
            _global_loader_config = LoaderConfig(
                cache_enabled=cache_dir is not None,
                cache_strategy=CacheStrategy.NORMAL,
                parallel_strategy=ParallelStrategy.AUTO,
                track_dependencies=True,
            )
        
        if cython_config is None:
            cython_config = CythonConfig(
                language_level=3,
                backend=CythonBackend.CYTHON,
            )
        
        cache_manager = None
        if cache_dir:
            cache_manager = CacheManager(cache_dir=cache_dir)
        
        _global_cython_loader = CythonLoader(
            config=_global_loader_config,
            cython_config=cython_config,
            cache_manager=cache_manager,
        )
    
    return _global_cython_loader


def load(
    source: Union[str, Path, List[Union[str, Path]]],
    **kwargs,
) -> Any:
    """
    Convenience function to load a C/C++ module.
    
    This is the primary entry point for loading C/C++ extensions.
    
    Parameters
    ----------
    source : Union[str, Path, List[Union[str, Path]]]
        Path to source file(s) or pre-compiled library.
    **kwargs : Any
        Additional options:
        - recompile : bool - Force recompilation.
        - module_name : str - Override module name.
        - optimization : str - Optimization level.
        - simd : str - SIMD instruction set.
        - openmp : bool - Enable OpenMP.
        - lto : bool - Enable LTO.
        - debug : bool - Include debug symbols.
        - compiler : str - Preferred compiler.
        - cache_dir : Path - Cache directory.
        
    Returns
    -------
    Any
        Loaded Python module.
        
    Examples
    --------
    >>> import pyputil.cutil.cimporter
    >>> 
    >>> # Basic usage
    >>> module = cimporter.load("my_extension.c")
    >>> result = module.my_function(42)
    >>> 
    >>> # With optimizations
    >>> module = cimporter.load(
    ...     "neural_net.cpp",
    ...     optimization="speed",
    ...     simd="avx2",
    ...     openmp=True,
    ...     compiler="clang",
    ... )
    >>> 
    >>> # Multiple source files
    >>> module = cimporter.load(["main.c", "utils.c", "math.c"])
    """
    # Parse kwargs
    compile_config_kwargs = {}
    loader_kwargs = {}
    
    opt_map = {
        "none": OptimizationPreset.NONE,
        "size": OptimizationPreset.SIZE,
        "balanced": OptimizationPreset.BALANCED,
        "speed": OptimizationPreset.SPEED,
        "aggressive": OptimizationPreset.AGGRESSIVE,
        "debug": OptimizationPreset.DEBUG,
    }
    
    if "optimization" in kwargs:
        opt = kwargs.pop("optimization")
        if isinstance(opt, str):
            compile_config_kwargs["optimization_preset"] = opt_map.get(opt.lower(), OptimizationPreset.BALANCED)
        else:
            compile_config_kwargs["optimization_preset"] = opt
    
    simd_map = {
        "none": SIMDPreset.NONE,
        "auto": SIMDPreset.AUTO,
        "sse2": SIMDPreset.SSE2,
        "sse4": SIMDPreset.SSE4_2,
        "avx": SIMDPreset.AVX,
        "avx2": SIMDPreset.AVX2,
        "avx512": SIMDPreset.AVX512,
        "neon": SIMDPreset.NEON,
    }
    
    if "simd" in kwargs:
        simd = kwargs.pop("simd")
        if isinstance(simd, str):
            compile_config_kwargs["simd_preset"] = simd_map.get(simd.lower(), SIMDPreset.AUTO)
        else:
            compile_config_kwargs["simd_preset"] = simd
    
    bool_options = ["openmp", "lto", "fast_math", "debug_symbols", "verbose"]
    for opt in bool_options:
        if opt in kwargs:
            compile_config_kwargs[opt] = kwargs.pop(opt)
    
    if "defines" in kwargs:
        compile_config_kwargs["defines"] = kwargs.pop("defines")
    
    if "include_paths" in kwargs:
        compile_config_kwargs["include_paths"] = kwargs.pop("include_paths")
    
    if "libraries" in kwargs:
        compile_config_kwargs["libraries"] = kwargs.pop("libraries")
    
    # Loader options
    compiler = kwargs.pop("compiler", None)
    cache_dir = kwargs.pop("cache_dir", None)
    
    # Create compile config if needed
    compile_config = None
    if compile_config_kwargs:
        compile_config = CompilationConfig(**compile_config_kwargs)
    
    # Get loader and load
    loader = get_c_loader(
        compiler=compiler,
        cache_dir=cache_dir,
        compile_config=compile_config,
    )
    
    return loader.load(source, **kwargs)


def load_cython(
    source: Union[str, Path],
    **kwargs,
) -> Any:
    """
    Convenience function to load a Cython module.
    
    Parameters
    ----------
    source : Union[str, Path]
        Path to .pyx source file.
    **kwargs : Any
        Additional options:
        - recompile : bool - Force recompilation.
        - module_name : str - Override module name.
        - language_level : int - Python language level.
        - annotate : bool - Generate HTML annotation.
        - cache_dir : Path - Cache directory.
        
    Returns
    -------
    Any
        Loaded Python module.
        
    Examples
    --------
    >>> import pyputil.cutil.cimporter
    >>> 
    >>> module = cimporter.load_cython("fast_module.pyx")
    >>> result = module.fast_function()
    >>> 
    >>> # With annotation
    >>> module = cimporter.load_cython(
    ...     "module.pyx",
    ...     annotate=True,
    ...     language_level=3,
    ... )
    """
    # Parse kwargs
    cython_config_kwargs = {}
    
    if "language_level" in kwargs:
        cython_config_kwargs["language_level"] = kwargs.pop("language_level")
    
    if "annotate" in kwargs:
        cython_config_kwargs["annotate"] = kwargs.pop("annotate")
    
    if "directives" in kwargs:
        cython_config_kwargs["directives"] = kwargs.pop("directives")
    
    cache_dir = kwargs.pop("cache_dir", None)
    
    # Create cython config if needed
    cython_config = None
    if cython_config_kwargs:
        cython_config = CythonConfig(**cython_config_kwargs)
    
    # Get loader and load
    loader = get_cython_loader(
        cache_dir=cache_dir,
        cython_config=cython_config,
    )
    
    return loader.load(source, **kwargs)


def load_batch(
    sources: List[Union[str, Path]],
    parallel: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """
    Load multiple C/C++ modules in batch.
    
    Parameters
    ----------
    sources : List[Union[str, Path]]
        List of source files.
    parallel : bool
        Use parallel compilation.
    **kwargs : Any
        Additional options passed to load().
        
    Returns
    -------
    Dict[str, Any]
        Dictionary mapping module names to loaded modules.
        
    Examples
    --------
    >>> modules = cimporter.load_batch([
    ...     "kernel.c",
    ...     "utils.c",
    ...     "math.c",
    ... ])
    >>> for name, module in modules.items():
    ...     print(f"Loaded {name}")
    """
    loader = get_c_loader(
        compiler=kwargs.pop("compiler", None),
        cache_dir=kwargs.pop("cache_dir", None),
    )
    
    return loader.load_batch(sources, parallel=parallel, **kwargs)


def unload(module_name: str) -> bool:
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
        
    Examples
    --------
    >>> cimporter.unload("my_extension")
    True
    """
    if _global_c_loader and _global_c_loader.is_loaded(module_name):
        return _global_c_loader.unload(module_name)
    
    if _global_cython_loader and _global_cython_loader.is_loaded(module_name):
        return _global_cython_loader.unload(module_name)
    
    return False


def reload(module_name: str) -> Any:
    """
    Reload a previously loaded module.
    
    Parameters
    ----------
    module_name : str
        Name of module to reload.
        
    Returns
    -------
    Any
        Reloaded module.
        
    Examples
    --------
    >>> module = cimporter.reload("my_extension")
    """
    if _global_c_loader and _global_c_loader.is_loaded(module_name):
        return _global_c_loader.reload(module_name)
    
    if _global_cython_loader and _global_cython_loader.is_loaded(module_name):
        return _global_cython_loader.reload(module_name)
    
    raise ImportModuleError(
        module_name=module_name,
        library_path=Path("unknown"),
        message="Module not loaded",
    )


def is_loaded(module_name: str) -> bool:
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
        
    Examples
    --------
    >>> if cimporter.is_loaded("my_extension"):
    ...     print("Module is loaded")
    """
    if _global_c_loader:
        return _global_c_loader.is_loaded(module_name)
    
    if _global_cython_loader:
        return _global_cython_loader.is_loaded(module_name)
    
    return False


def list_loaded() -> List[str]:
    """
    List all currently loaded module names.
    
    Returns
    -------
    List[str]
        List of loaded module names.
        
    Examples
    --------
    >>> loaded = cimporter.list_loaded()
    >>> print(f"Loaded modules: {loaded}")
    """
    modules = []
    
    if _global_c_loader:
        modules.extend(_global_c_loader.list_loaded_modules())
    
    if _global_cython_loader:
        modules.extend(_global_cython_loader.list_loaded_modules())
    
    return modules


def clear_cache() -> int:
    """
    Clear all compilation caches.
    
    Returns
    -------
    int
        Number of items removed.
        
    Examples
    --------
    >>> removed = cimporter.clear_cache()
    >>> print(f"Removed {removed} cached items")
    """
    count = 0
    
    if _global_c_loader:
        count += _global_c_loader.clear_cache()
    
    if _global_cython_loader:
        count += _global_cython_loader.clear_cache()
    
    return count


def get_stats() -> Dict[str, Any]:
    """
    Get loader statistics.
    
    Returns
    -------
    Dict[str, Any]
        Dictionary of statistics.
        
    Examples
    --------
    >>> stats = cimporter.get_stats()
    >>> print(f"Total loads: {stats.get('total_loads', 0)}")
    >>> print(f"Cache hits: {stats.get('cache_hits', 0)}")
    """
    stats = {
        "version": __version__,
        "platform": get_platform_info().to_dict(),
        "c_loader": None,
        "cython_loader": None,
        "compilers": list_compilers(),
    }
    
    if _global_c_loader:
        stats["c_loader"] = _global_c_loader.get_stats()
    
    if _global_cython_loader:
        stats["cython_loader"] = _global_cython_loader.get_stats()
    
    return stats


def create_sandbox(
    policy: SandboxPolicyEnum = SandboxPolicyEnum.BASIC,
    timeout_seconds: Optional[float] = 60,
    memory_limit_mb: Optional[int] = 1024,
    cpu_time_seconds: Optional[float] = None,
    max_processes: Optional[int] = None,
    allow_network: bool = False,
    allowed_paths: Optional[List[Path]] = None,
    read_only_paths: Optional[List[Path]] = None,
    workspace: Optional[Path] = None,
) -> SandboxManager:
    """
    Create a sandbox for secure compilation.
    
    Parameters
    ----------
    policy : SandboxPolicy
        Sandbox security policy.
    timeout_seconds : Optional[float]
        Wall-clock timeout in seconds.
    memory_limit_mb : Optional[int]
        Memory limit in megabytes.
    cpu_time_seconds : Optional[float]
        CPU time limit in seconds.
    max_processes : Optional[int]
        Maximum number of child processes.
    allow_network : bool
        Whether to allow network access.
    allowed_paths : Optional[List[Path]]
        Paths allowed for filesystem access.
    read_only_paths : Optional[List[Path]]
        Read-only allowed paths.
    workspace : Optional[Path]
        Custom workspace directory.
        
    Returns
    -------
    SandboxManager
        Configured sandbox manager.
        
    Examples
    --------
    >>> sandbox = cimporter.create_sandbox(
    ...     policy=SandboxPolicy.STRICT,
    ...     timeout_seconds=30,
    ...     memory_limit_mb=512,
    ... )
    >>> result = sandbox.run(["gcc", "source.c"])
    """
    limits = ResourceLimits(
        timeout_seconds=timeout_seconds,
        memory_limit_mb=memory_limit_mb,
        cpu_time_seconds=cpu_time_seconds,
        max_processes=max_processes,
    )
    
    return SandboxManager(
        policy=policy,
        limits=limits,
        workspace=workspace,
        allow_network=allow_network,
        allowed_paths=allowed_paths,
        read_only_paths=read_only_paths,
    )


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [    
    # Setup
    "setup_logging",
    
    # Core enums
    "OptimizationLevel",
    "SIMDLevel",
    "CompilerFamily",
    "BuildMode",
    "CacheStrategy",
    "ParallelStrategy",
    "LanguageStandard",
    "LinkType",
    "SandboxPolicy",
    "LogLevel",
    "DependencyType",
    
    # Core exceptions
    "CImporterBaseException",
    "CompileError",
    "LinkerError",
    "CacheError",
    "ImportModuleError",
    "DependencyError",
    "PlatformError",
    "CoreSandboxError",
    "ConfigError",
    "ErrorCategory",
    "ErrorSeverity",
    
    # Core cache
    "CacheKey",
    "CacheKeyBuilder",
    "CacheMetadata",
    "CacheManager",
    
    # Compilers
    "CompilerBackend",
    "CompilerInfo",
    "CompilerFeature",
    "CompileResult",
    "GCCBackend",
    "ClangBackend",
    "MSVCBackend",
    "ICCBackend",
    "CompilerDetector",
    "CompilerRegistry",
    "CompilerCandidate",
    "CompilerPriority",
    "detect_compiler",
    "list_compilers",
    "get_compiler_backend",
    "get_best_compiler",
    "has_compiler",
    
    # Config classes
    'CoreCompilerConfig',
    'CoreOptimizationConfig', 
    'CoreDebugConfig', 
    'CoreBuildConfig', 
    'CoreCacheConfig', 
    'CoreSandboxConfig', 
    'CorePythonConfig', 
    'CoreCImporterConfig',
    
    # Flag normalization
    "FlagNormalizer",
    "FlagMapper",
    "OptimizationPreset",
    "SIMDPreset",
    "WarningPreset",
    "LanguageStandardPreset",
    "SanitizerPreset",
    "LinkerPreset",
    "normalize_flags",
    "get_optimization_flags",
    
    # Loaders
    "BaseLoader",
    "LoaderConfig",
    "LoaderState",
    "LoaderEvent",
    "LoaderEventType",
    "ModuleMetadata",
    "ModuleOrigin",
    "ModuleProxy",
    "BatchLoader",
    "CLoader",
    "CompilationConfig",
    "CythonLoader",
    "CythonConfig",
    "CythonDirective",
    "CythonBackend",
    
    # Sandbox
    "SandboxManager",
    "ProcessIsolator",
    "ResourceLimits",
    "SandboxResult",
    "SandboxError",
    "SandboxViolation",
    "SandboxTimeoutError",
    "SandboxMemoryError",
    "CPULimiter",
    "MemoryLimiter",
    "DiskLimiter",
    "ProcessLimiter",
    "NetworkBlocker",
    "FilesystemJail",
    "TempWorkspace",
    "PathRestriction",
    
    # Platform utilities
    "get_platform",
    "get_platform_info",
    "get_architecture",
    "get_system",
    "get_machine",
    "get_shared_library_extension",
    "get_executable_extension",
    "get_python_include_paths",
    "get_python_library_paths",
    "get_python_library_name",
    "get_python_library_full_path",
    "get_python_config_var",
    "get_python_extension_suffix",
    "is_windows",
    "is_linux",
    "is_macos",
    "is_unix",
    "is_64bit",
    "is_arm",
    "is_x86",
    "PlatformInfo",
    "PlatformType",
    "ArchitectureType",
    
    # Checksum utilities
    "compute_checksum",
    "compute_file_hash",
    "compute_string_hash",
    "verify_checksum",
    "compare_files",
    "hash_string",
    "hash_file",
    "get_file_checksum",
    "HashAlgorithm",
    "ChecksumResult",
    
    # System utilities
    "CommandResult",
    "CommandError",
    "TimeoutError",
    "run_command",
    "run_command_sync",
    "run_command_async",
    "run_commands_parallel",
    "get_environment",
    "set_environment",
    "get_env",
    "set_env",
    "unset_env",
    "prepend_path",
    "append_path",
    "get_cpu_count",
    "get_memory_info",
    "get_disk_usage",
    "get_process_id",
    "get_process_parent_id",
    "is_process_running",
    "kill_process",
    "kill_process_tree",
    "get_child_processes",
    "get_process_info",
    "SignalHandler",
    "send_signal",
    "send_signal_to_group",
    "create_process_group",
    "get_process_group",
    "TempFile",
    "TempDirectory",
    "create_temp_file",
    "create_temp_directory",
    
    # Global loader functions
    "get_c_loader",
    "get_cython_loader",
    "load",
    "load_cython",
    "load_batch",
    "unload",
    "reload",
    "is_loaded",
    "list_loaded",
    "clear_cache",
    "get_stats",
    "print_info",
    
    # Sandbox creation
    "create_sandbox",
]


# ============================================================================
# Namespace Cleanup
# ============================================================================
from ...api import clean
clean(expose=__all__)


# ============================================================================
# Module Cleanup
# ============================================================================

def _cleanup() -> None:
    """
    Clean up global resources on module exit.
    """
    global _global_c_loader, _global_cython_loader
    
    if _global_c_loader:
        try:
            _global_c_loader.close()
        except Exception:
            pass
        _global_c_loader = None
    
    if _global_cython_loader:
        try:
            _global_cython_loader.close()
        except Exception:
            pass
        _global_cython_loader = None


import atexit
atexit.register(_cleanup)


# ============================================================================
# Module Information
# ============================================================================

def print_info() -> None:
    """
    Print information about the cimporter installation.
    
    Examples
    --------
    >>> import pyputil.cutil.cimporter
    >>> cimporter.print_info()
    """    
    info = get_platform_info()
    print("Platform Information:")
    print(f"  System: {info.platform_type.value}")
    print(f"  Architecture: {info.architecture.value}")
    print(f"  Python: {info.python_version} ({info.python_implementation.value})")
    print(f"  ABI: {info.python_abi}")
    print(f"  64-bit: {info.is_64bit}")
    print()
    
    print("Available Compilers:")
    for compiler in list_compilers():
        backend = get_compiler_backend(compiler)
        if backend:
            print(f"  - {compiler}: {backend.info.version}")
        else:
            print(f"  - {compiler}: not available")
    print()
    
    features = {
        "Filesystem Jail": FilesystemJail is not None,
        "Windows Job Objects": WindowsJobObject is not None and _WINDOWS_SANDBOX_AVAILABLE,
        "xxHash": HashAlgorithm.XXH64.is_available(),
        "BLAKE2": HashAlgorithm.BLAKE2B.is_available(),
    }
    
    print("Available Features:")
    for feature, available in features.items():
        status = "✓" if available else "✗"
        print(f"  {status} {feature}")


if __name__ == "__main__":
    print_info()