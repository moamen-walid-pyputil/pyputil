#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
PypUtil CFast Project: Compile C code at runtime and call it from Python.

CFast provides a seamless bridge between Python and C, allowing you to
compile C source code on-the-fly and call C functions directly from Python
with automatic type conversion, signature detection, and intelligent caching.

Key Features
------------
- **Zero Configuration**: Auto-detects available C compilers (GCC, Clang, MSVC)
- **Automatic Type Conversion**: Maps C types to Python types automatically
- **Signature Detection**: Uses pycparser to detect function signatures
- **Smart Caching**: Caches compiled libraries to avoid recompilation
- **Thread-Safe**: File locking prevents concurrent compilation races
- **Cross-Platform**: Works on Linux, macOS, and Windows
- **Decorator Interface**: Elegant @cfunc decorator for inline C functions

Quick Start
-----------
>>> import cfast

>>> # Simple C function
>>> add = cfast.cfunc('''
...     int add(int a, int b) {
...         return a + b;
...     }
... ''')
>>> add(3, 5)
8

>>> # With math library
>>> distance = cfast.cfunc('''
...     #include <math.h>
...     double distance(double x1, double y1, double x2, double y2) {
...         double dx = x2 - x1;
...         double dy = y2 - y1;
...         return sqrt(dx*dx + dy*dy);
...     }
... ''', libraries=['m'])
>>> distance(0, 0, 3, 4)
5.0

>>> # Load entire C file
>>> lib = cfast.load_c_file('mylib.c')
>>> result = lib.complex_operation([1, 2, 3])

>>> # Decorator style
>>> @cfast.cfunc
... def factorial(n: int) -> int:
...     '''
...     int factorial(int n) {
...         if (n <= 1) return 1;
...         return n * factorial(n - 1);
...     }
...     '''
>>> factorial(10)
3628800

>>> # Define C struct
>>> @cfast.cstruct
... class Point:
...     '''
...     struct Point {
...         double x;
...         double y;
...     };
...     '''
>>> p = Point(x=10.0, y=20.0)
>>> p.x, p.y
(10.0, 20.0)

Modules
-------
- cfast.core: Main engine and public API functions
- cfast.compiler: Compiler abstraction layer
- cfast.cache: Caching system with file locking
- cfast.parser: C code parsing and signature detection
- cfast.decorators: Decorator interface for C functions
- cfast.platform: Platform-specific utilities
- cfast.utils: Helper functions and constants
- cfast.exceptions: Custom exception classes

Configuration
-------------
Environment variables:
    CFAST_CACHE_ROOT: Override default cache directory
    CFAST_CACHE_SIZE: Maximum cache size in bytes
    CFAST_CACHE_AGE: Maximum cache age in days
    CFAST_COMPILER: Preferred compiler ('gcc', 'clang', 'msvc')
    CFAST_CFLAGS: Default compiler flags
    CFAST_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR)

Examples
--------
>>> import cfast
>>> 
>>> # Configure logging
>>> cfast.set_log_level('DEBUG')
>>> 
>>> # Check cache info
>>> info = cfast.get_cache_info()
>>> print(f"Cache size: {info['formatted_size']}")
>>> 
>>> # Use custom engine
>>> engine = cfast.CFastEngine(
...     compiler=cfast.GccCompiler(),
...     cflags=['-O3', '-march=native'],
...     auto_signatures=True
... )
>>> lib = engine.load('int add(int a, int b) { return a + b; }')
>>> 
>>> # Compile only (don't load)
>>> lib_path = cfast.compile_c_code('int mul(int a, int b) { return a * b; }')
>>> print(f"Compiled to: {lib_path}")
"""

import os
import sys
import logging
import warnings
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Callable


# =============================================================================
# Environment Configuration
# =============================================================================

def _get_env_bool(name: str, default: bool = False) -> bool:
    """Get boolean environment variable."""
    value = os.environ.get(name, str(default)).lower()
    return value in ('1', 'true', 'yes', 'on')


def _get_env_int(name: str, default: int) -> int:
    """Get integer environment variable."""
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _get_env_path(name: str, default: Optional[Path] = None) -> Optional[Path]:
    """Get path environment variable."""
    value = os.environ.get(name)
    if value:
        return Path(value).expanduser().resolve()
    return default


# Environment-based configuration
CONFIG = {
    'cache_root': _get_env_path('CFAST_CACHE_ROOT'),
    'cache_max_size': _get_env_int('CFAST_CACHE_SIZE', 1024 * 1024 * 1024),  # 1 GB
    'cache_max_age_days': _get_env_int('CFAST_CACHE_AGE', 30),
    'preferred_compiler': os.environ.get('CFAST_COMPILER', 'gcc'),
    'default_cflags': os.environ.get('CFAST_CFLAGS', '').split() or None,
    'auto_signatures': _get_env_bool('CFAST_AUTO_SIGNATURES', True),
    'validate_code': _get_env_bool('CFAST_VALIDATE_CODE', True),
    'log_level': os.environ.get('CFAST_LOG_LEVEL', 'WARNING').upper(),
    'timeout': _get_env_int('CFAST_TIMEOUT', 120),
    'enable_cache': _get_env_bool('CFAST_ENABLE_CACHE', True),
}


# =============================================================================
# Imports and Exports
# =============================================================================

# Exceptions - available at top level
from .exceptions import (
    CFastError,
    ErrorSeverity,
    SourceContext,
    CompilationError,
    CompilerNotFoundError,
    CompilationTimeoutError,
    LinkerError,
    PreprocessorError,
    AssemblyError,
    SignatureDetectionError,
    PycparserNotAvailableError,
    ParseSyntaxError,
    StructDefinitionError,
    TypeConversionError,
    IncludeResolutionError,
    CacheError,
    CacheIntegrityError,
    CacheCorruptionError,
    CacheLockError,
    StaleLockError,
    CacheCapacityError,
    CacheIOError,
    PlatformError,
    UnsupportedPlatformError,
    LibraryLoadError,
    ArchitectureMismatchError,
    PermissionError,
    ConfigurationError,
    InvalidSourceCodeError,
    FunctionNotFoundError,
    MultipleFunctionsError,
    InvalidCompilerFlagError,
    IncludePathError,
    RuntimeError,
    FunctionCallError,
    MemoryAccessError,
    TypeMismatchError,
    NullPointerError,
    LockAcquisitionError,
    ParseError,
    extract_source_context,
    deserialize_exception,
)

# Core API
from .core import (
    CFastEngine,
    CFastLibrary,
    LibraryInfo,
    CompileOptions,
    load_c,
    load_c_file,
    cfunc,
    compile_c_code,
    validate_c_code,
    clear_cache,
    get_cache_info,
    list_cached_libraries,
    set_log_level,
    reset_global_engine,
    # Aliases
    load as load_c_alias,
    load_file as load_c_file_alias,
    compile_code as compile_c_code_alias,
)

# Compiler abstraction
from .compiler import (
    Compiler,
    GccCompiler,
    ClangCompiler,
    MsvcCompiler,
    detect_compiler,
    validate_compiler_installation,
    get_supported_compilers,
    CompilerType,
    CompilerCapabilities,
    CompilationResult,
)

# Cache system
from .cache import (
    CacheManager,
    CacheEntry,
    CacheMetadata,
    FileLock,
    CacheEntryStatus,
    compute_cache_key,
    acquire_cache_lock,
    cleanup_stale_locks,
)

# Parser and signature detection
from .parser import (
    parse_c_code,
    parse_function_signatures,
    parse_struct_definitions,
    build_struct_classes,
    set_function_signatures,
    CachingParser,
    ParseResult,
    ParsedFunction,
    ParsedStruct,
    ParsedEnum,
    ParsedType,
    CTypeMapper,
    CTypeCategory,
    PYPARSER_AVAILABLE,
    PYPARSER_VERSION,
)

# Decorators
from .decorators import (
    cfunc as cfunc_decorator,
    cfunc_inline,
    cfunc_from_file,
    cstruct,
    cenum,
    cmodule,
    is_cfunc,
    get_c_code,
    get_c_name,
)

# Platform utilities
from .platform import (
    PlatformInfo,
    get_platform_details,
    SystemInfo,
)

# Utility functions
from .utils import (
    atomic_write,
    atomic_read,
    get_compiler_version,
    extract_function_names,
    extract_struct_names,
    extract_includes,
    calculate_code_hash,
    sanitize_identifier,
    sanitize_filename,
    safe_path_join,
    format_size,
    measure_execution_time,
    time_function,
    CTYPE_MAP,
    C_KEYWORDS,
)


# =============================================================================
# Logging Setup
# =============================================================================

_logger = logging.getLogger(__name__)
_logger_initialized = False


def _setup_logging():
    """Initialize logging for the package."""
    global _logger_initialized
    if _logger_initialized:
        return
    
    # Set level from environment
    level = getattr(logging, CONFIG['log_level'], logging.WARNING)
    _logger.setLevel(level)
    
    # Add handler if none exists
    if not _logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        _logger.addHandler(handler)
    
    _logger_initialized = True
    _logger.debug(f"CFast initialized")


_setup_logging()


# =============================================================================
# Convenience Functions
# =============================================================================

def info() -> Dict[str, Any]:
    """
    Get comprehensive information about the CFast installation.
    
    Returns
    -------
    Dict[str, Any]
        Dictionary containing version, compiler, cache, and platform info.
    
    Examples
    --------
    >>> import cfast
    >>> info = cfast.info()
    >>> print(f"Version: {info['version']}")
    >>> print(f"Compiler: {info['compiler']['name']}")
    >>> print(f"pycparser: {info['pycparser_available']}")
    """
    info_dict = {
        'version': __version__,
        'version_info': version_info,
        'pycparser_available': PYPARSER_AVAILABLE,
        'pycparser_version': PYPARSER_VERSION,
        'platform': {
            'system': sys.platform,
            'python_version': sys.version,
            'python_implementation': sys.implementation.name,
            'architecture': PlatformInfo.get_architecture(),
        },
        'config': {
            'cache_root': str(CONFIG['cache_root']) if CONFIG['cache_root'] else 'default',
            'cache_max_size': format_size(CONFIG['cache_max_size']),
            'cache_max_age_days': CONFIG['cache_max_age_days'],
            'auto_signatures': CONFIG['auto_signatures'],
            'validate_code': CONFIG['validate_code'],
            'log_level': CONFIG['log_level'],
        },
    }
    
    # Try to detect compiler
    try:
        compiler = detect_compiler()
        if compiler:
            info_dict['compiler'] = {
                'name': compiler.name,
                'version': compiler.version,
                'executable': str(compiler.executable),
                'target': compiler.target_platform,
            }
        else:
            info_dict['compiler'] = None
    except Exception as e:
        info_dict['compiler'] = {'error': str(e)}
    
    # Get cache info
    try:
        cache_info = get_cache_info()
        info_dict['cache'] = cache_info
    except Exception as e:
        info_dict['cache'] = {'error': str(e)}
    
    return info_dict


def check() -> bool:
    """
    Check if CFast is properly configured and ready to use.
    
    Returns
    -------
    bool
        True if everything is working, False otherwise.
    
    Examples
    --------
    >>> if cfast.check():
    ...     print("CFast is ready!")
    ... else:
    ...     print("CFast needs configuration")
    """
    issues = []
    
    # Check compiler
    try:
        compiler = detect_compiler()
        if compiler is None:
            issues.append("No C compiler found")
    except Exception as e:
        issues.append(f"Compiler detection failed: {e}")
    
    # Check pycparser (optional)
    if not PYPARSER_AVAILABLE:
        issues.append("pycparser not installed (optional, for signature detection)")
    
    # Check cache directory
    try:
        from .cache import DEFAULT_CACHE_ROOT
        cache_root = CONFIG['cache_root'] or DEFAULT_CACHE_ROOT
        cache_root.mkdir(parents=True, exist_ok=True)
        if not os.access(cache_root, os.W_OK):
            issues.append(f"Cache directory not writable: {cache_root}")
    except Exception as e:
        issues.append(f"Cache directory issue: {e}")
    
    if issues:
        _logger.warning("CFast check found issues:\n  - " + "\n  - ".join(issues))
        return False
    
    _logger.info("CFast check passed")
    return True


def test(verbose: bool = False) -> bool:
    """
    Run a simple test to verify CFast is working.
    
    Parameters
    ----------
    verbose : bool, default False
        If True, print detailed test output.
    
    Returns
    -------
    bool
        True if test passes, False otherwise.
    
    Examples
    --------
    >>> cfast.test()
    True
    """
    test_code = "int test_add(int a, int b) { return a + b; }"
    
    try:
        if verbose:
            print("Testing CFast...")
            print(f"  Code: {test_code}")
        
        # Test compilation
        result = cfunc(test_code, func_name="test_add")
        
        # Test execution
        output = result(2, 3)
        
        if output == 5:
            if verbose:
                print("  Result: test_add(2, 3) = 5 ✓")
                print("CFast is working correctly!")
            return True
        else:
            if verbose:
                print(f"  Error: Expected 5, got {output}")
            return False
            
    except Exception as e:
        if verbose:
            print(f"  Error: {e}")
        return False


def set_cache_root(path: Union[str, Path]) -> None:
    """
    Set the cache root directory.
    
    Parameters
    ----------
    path : Union[str, Path]
        Path to the cache directory.
    
    Examples
    --------
    >>> cfast.set_cache_root('/tmp/my_cfast_cache')
    """
    global CONFIG
    CONFIG['cache_root'] = Path(path).expanduser().resolve()
    _logger.info(f"Cache root set to: {CONFIG['cache_root']}")


def get_version() -> str:
    """Return the current version string."""
    return __version__


def get_engine() -> CFastEngine:
    """
    Get the global CFastEngine instance.
    
    Returns
    -------
    CFastEngine
        The global engine instance.
    
    Examples
    --------
    >>> engine = cfast.get_engine()
    >>> print(engine.get_stats())
    """
    from .core import _get_engine
    return _get_engine()


# =============================================================================
# Module-Level Aliases for Backward Compatibility
# =============================================================================

# Core aliases
load = load_c
load_file = load_c_file
compile_code = compile_c_code

# Compiler aliases
get_compiler = detect_compiler

# Cache aliases
purge_cache = clear_cache

# Parser aliases
parse = parse_c_code
build_structs = build_struct_classes
set_signatures = set_function_signatures


# =============================================================================
# Deprecated Functions
# =============================================================================

def deprecated(func_or_message=None, version=None):
    """Decorator to mark functions as deprecated."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            msg = func_or_message or f"{func.__name__} is deprecated"
            if version:
                msg += f" since version {version}"
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)
        return wrapper
    
    if callable(func_or_message):
        return decorator(func_or_message)
    return decorator


# =============================================================================
# Package Exports
# =============================================================================

__all__ = [
    # Main API functions
    'load_c',
    'load_c_file',
    'cfunc',
    'compile_c_code',
    'validate_c_code',
    'clear_cache',
    'get_cache_info',
    'list_cached_libraries',
    'set_log_level',
    'reset_global_engine',
    
    # Core classes
    'CFastEngine',
    'CFastLibrary',
    'LibraryInfo',
    'CompileOptions',
    
    # Compiler classes
    'Compiler',
    'GccCompiler',
    'ClangCompiler',
    'MsvcCompiler',
    'detect_compiler',
    'validate_compiler_installation',
    'get_supported_compilers',
    'CompilerType',
    'CompilerCapabilities',
    'CompilationResult',
    
    # Cache classes
    'CacheManager',
    'CacheEntry',
    'CacheMetadata',
    'FileLock',
    'CacheEntryStatus',
    'compute_cache_key',
    'acquire_cache_lock',
    'cleanup_stale_locks',
    
    # Parser classes and functions
    'parse_c_code',
    'parse_function_signatures',
    'parse_struct_definitions',
    'build_struct_classes',
    'set_function_signatures',
    'CachingParser',
    'ParseResult',
    'ParsedFunction',
    'ParsedStruct',
    'ParsedEnum',
    'ParsedType',
    'CTypeMapper',
    'CTypeCategory',
    'PYPARSER_AVAILABLE',
    'PYPARSER_VERSION',
    
    # Decorators
    'cfunc_decorator',
    'cfunc_inline',
    'cfunc_from_file',
    'cstruct',
    'cenum',
    'cmodule',
    'is_cfunc',
    'get_c_code',
    'get_c_name',
    
    # Platform utilities
    'PlatformInfo',
    'get_platform_details',
    'SystemInfo',
    
    # Utility functions
    'atomic_write',
    'atomic_read',
    'get_compiler_version',
    'extract_function_names',
    'extract_struct_names',
    'extract_includes',
    'calculate_code_hash',
    'sanitize_identifier',
    'sanitize_filename',
    'safe_path_join',
    'format_size',
    'measure_execution_time',
    'time_function',
    'CTYPE_MAP',
    'C_KEYWORDS',
    
    # Information functions
    'info',
    'check',
    'test',
    'set_cache_root',
    'get_version',
    'get_engine',
    
    # Exceptions
    'CFastError',
    'CompilationError',
    'SignatureDetectionError',
    'CacheError',
    'CacheIntegrityError',
    'CompilerNotFoundError',
    'LockAcquisitionError',
    'ParseError',
    'PlatformError',
    # To get all exceptions import the 'exceptions' module by 'cfast.exceptions' 
    
    # Aliases (backward compatibility)
    'load',
    'load_file',
    'compile_code',
    'get_compiler',
    'purge_cache',
    'parse',
    'build_structs',
    'set_signatures',
]


# =============================================================================
# Package Initialization
# =============================================================================

def __dir__() -> List[str]:
    """Return list of public attributes for tab completion."""
    return __all__


def __getattr__(name: str) -> Any:
    """
    Lazy import for submodules to improve import time.
    
    This allows accessing submodules without importing them all at once.
    """
    if name in ('core', 'compiler', 'cache', 'parser', 'decorators', 
                'platform', 'utils', 'exceptions'):
        import importlib
        return importlib.import_module(f'.{name}', __package__)
    
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# =============================================================================
# Welcome Message (only in interactive mode)
# =============================================================================

def _show_welcome():
    """Show welcome message in interactive mode."""
    import sys
    
    # Only show in interactive Python
    if hasattr(sys, 'ps1') and sys.flags.interactive:
        compiler_info = ""
        try:
            compiler = detect_compiler()
            if compiler:
                compiler_info = f"using {compiler.name} {compiler.version}"
        except Exception:
            pass
        
        print(f"CFast loaded {compiler_info}")
        print("Try: cfast.cfunc('int add(int a, int b) { return a + b; }')(3, 5)")


# Show welcome message (can be disabled with CFAST_QUIET=1)
if not _get_env_bool('CFAST_QUIET', False):
    _show_welcome()