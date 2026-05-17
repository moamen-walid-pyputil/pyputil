#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Core public API for the cfast_basic library.

This module provides the main user-facing functions for compiling and loading
C code at runtime. It orchestrates the compilation, caching, and signature
detection components to provide a seamless experience.

The main public functions are:
    - :func:`load_c`: Compile C code from a string and load it
    - :func:`load_c_file`: Compile C code from a file and load it
    - :func:`cfunc`: Compile C code and return a specific function
    - :func:`compile_c_code`: Low-level compilation without loading
    - :func:`clear_cache`: Remove cached compiled libraries

Examples
--------
>>> import cfast_basic
>>> # Simple function from string
>>> add = cfast_basic.cfunc('int add(int a, int b) { return a + b; }')
>>> add(3, 5)
8

>>> # Load entire library
>>> lib = cfast_basic.load_c('''
...     #include <math.h>
...     double square(double x) { return x * x; }
...     double cube(double x) { return x * x * x; }
... ''')
>>> lib.square(4.0)
16.0

>>> # Load from file
>>> lib = cfast_basic.load_c_file("mylib.c", cflags=["-O3"])
"""

import ctypes
import os
import sys
import logging
import warnings
import re
from pathlib import Path
from typing import List, Optional, Dict, Union, Callable, Any

from .exceptions import CompilationError, SignatureDetectionError, CompilerNotFoundError
from .platform import PlatformInfo
from .compiler import (
    Compiler,
    GccCompiler,
    ClangCompiler,
    MsvcCompiler,
    detect_compiler,
)
from .cache import (
    _compute_cache_key,
    _ensure_cache_dir,
    acquire_lock,
    release_lock,
    clear_cache as _clear_cache,
)
from .parser import set_function_signatures, PYPARSER_AVAILABLE, parse_c_code

# Engine version – increment when compilation or parsing logic changes
# This invalidates all existing caches
ENGINE_VERSION = "5"

# Default compiler flags, can be overridden via environment variable
DEFAULT_CFLAGS = os.environ.get("CFAST_CFLAGS", "-O3").split()
DEFAULT_COMPILER = os.environ.get("CFAST_COMPILER")  # None = auto-detect
DEFAULT_LIBS = os.environ.get("CFAST_LIBS", "").split()

# Setup logging
logger = logging.getLogger(__name__)


def compile_c_code(
    code: str,
    compiler: Optional[Compiler] = None,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    force_recompile: bool = False,
    quiet: bool = False,
) -> Path:
    """
    Compile C code into a shared library, using a cache if possible.

    This function handles the compilation process, including:
        - Computing a cache key based on all compilation parameters
        - Checking for an existing cached library
        - Acquiring a file lock to prevent concurrent compilation
        - Invoking the appropriate compiler
        - Storing the compiled library in the cache

    Parameters
    ----------
    code : str
        The complete C source code to compile.
    compiler : Compiler, optional
        Compiler instance to use. If None, automatically detected via
        :func:`~cfast_basic.compiler.detect_compiler`.
    cflags : list of str, optional
        Additional compiler flags. Defaults to :data:`DEFAULT_CFLAGS`.
    libraries : list of str, optional
        Libraries to link against. Defaults to :data:`DEFAULT_LIBS`.
    includes : list of str, optional
        Additional include directories for header files.
    defines : dict of {str: str or None}, optional
        Macro definitions. Keys are macro names. If value is None, defined as
        ``-DNAME``. Otherwise defined as ``-DNAME=value``.
    force_recompile : bool, default False
        If True, ignore any cached library and recompile from source.
    quiet : bool, default False
        If True, suppress informational log messages.

    Returns
    -------
    Path
        Absolute path to the compiled shared library.

    Raises
    ------
    CompilerNotFoundError
        If no suitable C compiler is found on the system.
    CompilationError
        If the compilation process fails.

    Examples
    --------
    >>> code = "int add(int a, int b) { return a + b; }"
    >>> lib_path = compile_c_code(code)
    >>> lib_path.suffix  # Platform-specific extension
    '.so'

    >>> # With custom flags
    >>> lib_path = compile_c_code(
    ...     code,
    ...     cflags=["-O2", "-Wall"],
    ...     libraries=["m"],
    ...     defines={"DEBUG": None, "VERSION": "1.0"}
    ... )
    """
    # Detect compiler if not provided
    if compiler is None:
        try:
            compiler = detect_compiler(DEFAULT_COMPILER)
        except CompilerNotFoundError:
            raise

    # Set defaults
    cflags = cflags if cflags is not None else DEFAULT_CFLAGS.copy()
    libraries = libraries if libraries is not None else DEFAULT_LIBS.copy()
    includes = includes if includes is not None else []
    defines = defines if defines is not None else {}

    # Compute cache key
    key = _compute_cache_key(
        code=code,
        cflags=cflags,
        compiler_name=compiler.name,
        libraries=libraries,
        includes=includes,
        defines=defines,
        engine_version=ENGINE_VERSION,
    )
    cache_dir = _ensure_cache_dir(key)

    # Determine output library path
    lib_name = "cfast_basic"
    so_file = cache_dir / f"{lib_name}{PlatformInfo.shared_lib_extension()}"

    # Check cache if not forced to recompile
    if not force_recompile and so_file.exists():
        if not quiet:
            logger.debug(f"Using cached library: {so_file}")
        return so_file

    # Acquire lock to prevent concurrent compilation of the same key
    lock = acquire_lock(cache_dir)
    try:
        # Double-check after acquiring lock (another process might have compiled it)
        if not force_recompile and so_file.exists():
            if not quiet:
                logger.debug(f"Library was compiled by another process: {so_file}")
            return so_file

        if not quiet:
            logger.info(f"Compiling C code to {so_file}")

        # Write source to file inside cache directory
        source_file = cache_dir / "source.c"
        source_file.write_text(code, encoding='utf-8')

        # Add Python includes if the code uses Python C API
        if "#include <Python.h>" in code or "#include <python" in code.lower():
            python_includes = PlatformInfo.python_include_args()
            # Extract just the paths from -I flags
            for inc_flag in python_includes:
                if inc_flag.startswith("-I"):
                    includes.append(inc_flag[2:])
            if not quiet:
                logger.debug(f"Added Python includes: {python_includes}")

        # Compile
        compiler.compile_shared_library(
            source=source_file,
            output=so_file,
            cflags=cflags,
            includes=includes,
            defines=defines,
            libraries=libraries,
            link_args=[],
        )

        if not quiet:
            logger.info(f"Successfully compiled: {so_file}")

    except CompilationError:
        # Re-raise compilation errors
        raise
    except Exception as e:
        raise CompilationError(
            f"Unexpected error during compilation: {e}"
        ) from e
    finally:
        release_lock(lock)

    return so_file


def load_c(
    code: str,
    compiler: Optional[Compiler] = None,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    force_recompile: bool = False,
    auto_signatures: bool = True,
    extra_includes: Optional[List[str]] = None,
    quiet: bool = False,
) -> ctypes.CDLL:
    """
    Compile C code into a shared library and load it with ctypes.

    This is the primary entry point for using cfast_basic. It compiles the provided
    C source code, caches the resulting shared library, loads it using ctypes,
    and optionally configures automatic function signature detection.

    Parameters
    ----------
    code : str
        The complete C source code to compile and load.
    compiler : Compiler, optional
        Compiler instance to use. If None, automatically detected.
    cflags : list of str, optional
        Additional compiler flags. Defaults to :data:`DEFAULT_CFLAGS`.
    libraries : list of str, optional
        Libraries to link against. Defaults to :data:`DEFAULT_LIBS`.
    includes : list of str, optional
        Additional include directories for compilation.
    defines : dict of {str: str or None}, optional
        Macro definitions for compilation.
    force_recompile : bool, default False
        If True, ignore cached library and recompile.
    auto_signatures : bool, default True
        If True, attempt to automatically set function signatures using pycparser.
        Requires pycparser to be installed. Falls back gracefully if not available.
    extra_includes : list of str, optional
        Additional include directories for signature detection (pycparser).
        Useful when the code includes custom headers.
    quiet : bool, default False
        If True, suppress informational log messages.

    Returns
    -------
    ctypes.CDLL
        The loaded shared library. If ``auto_signatures`` is True and pycparser
        is available, the functions will have proper ``argtypes`` and ``restype``
        configured for automatic type conversion.

    Raises
    ------
    CompilerNotFoundError
        If no suitable C compiler is found.
    CompilationError
        If compilation fails.

    Examples
    --------
    Basic usage:

    >>> lib = load_c('''
    ...     int add(int a, int b) {
    ...         return a + b;
    ...     }
    ... ''')
    >>> lib.add(3, 5)
    8

    With multiple functions and includes:

    >>> lib = load_c('''
    ...     #include <math.h>
    ...     double square(double x) { return x * x; }
    ...     double pythagoras(double a, double b) {
    ...         return sqrt(a*a + b*b);
    ...     }
    ... ''', libraries=["m"])
    >>> lib.pythagoras(3.0, 4.0)
    5.0

    Disabling automatic signatures (manual configuration required):

    >>> import ctypes
    >>> lib = load_c('int add(int a, int b) { return a + b; }',
    ...              auto_signatures=False)
    >>> lib.add.argtypes = [ctypes.c_int, ctypes.c_int]
    >>> lib.add.restype = ctypes.c_int
    >>> lib.add(3, 5)
    8
    """
    # Merge includes for compilation
    all_includes = list(includes) if includes else []
    if extra_includes:
        all_includes.extend(extra_includes)

    # Compile the code
    so_path = compile_c_code(
        code=code,
        compiler=compiler,
        cflags=cflags,
        libraries=libraries,
        includes=all_includes if all_includes else None,
        defines=defines,
        force_recompile=force_recompile,
        quiet=quiet,
    )

    if not quiet:
        logger.debug(f"Loading library from {so_path}")

    # Load the library
    try:
        lib = ctypes.CDLL(str(so_path))
    except OSError as e:
        raise CompilationError(
            f"Failed to load compiled library {so_path}: {e}"
        ) from e

    # Configure automatic signatures if requested
    if auto_signatures:
        if PYPARSER_AVAILABLE:
            try:
                if not quiet:
                    logger.debug("Attempting automatic signature detection")
                set_function_signatures(lib, code, extra_includes)
                if not quiet:
                    logger.debug("Successfully set function signatures")
            except SignatureDetectionError as e:
                if not quiet:
                    logger.warning(f"Automatic signature detection failed: {e}")
                warnings.warn(
                    f"Automatic signature detection failed: {e}\n"
                    "Falling back to manual type setting. Functions will require "
                    "explicit argtypes/restype configuration.",
                    UserWarning,
                    stacklevel=2
                )
        else:
            if not quiet:
                logger.debug("pycparser not available; skipping automatic signatures")

    return lib


def load_c_file(
    filepath: Union[str, Path],
    encoding: str = "utf-8",
    errors: str = "strict",
    **kwargs: Any
) -> ctypes.CDLL:
    """
    Load, compile, and link a C source file using :func:`load_c`.

    This is a convenience function that reads C source code from a file and
    passes it to :func:`load_c`. All additional keyword arguments are forwarded
    to :func:`load_c`.

    Parameters
    ----------
    filepath : str or Path
        Path to the C source file.
    encoding : str, default "utf-8"
        Text encoding used to read the file.
    errors : str, default "strict"
        Error handling strategy for decoding. Passed to ``Path.read_text()``.
        Common values: ``"strict"``, ``"ignore"``, ``"replace"``.
    **kwargs : dict
        Additional arguments passed directly to :func:`load_c`, such as
        ``compiler``, ``cflags``, ``libraries``, ``includes``, etc.

    Returns
    -------
    ctypes.CDLL
        The compiled and loaded shared library.

    Raises
    ------
    FileNotFoundError
        If the specified file does not exist.
    ValueError
        If the path is not a file or the file is empty.
    OSError
        If the file cannot be read.
    CompilerNotFoundError
        If no suitable C compiler is found.
    CompilationError
        If compilation fails.

    Examples
    --------
    >>> lib = load_c_file("example.c")
    >>> result = lib.add(2, 3)

    >>> lib = load_c_file(
    ...     "math_utils.c",
    ...     cflags=["-O2", "-Wall"],
    ...     libraries=["m"]
    ... )
    """
    path = Path(filepath)

    # Validate path
    if not path.exists():
        raise FileNotFoundError(f"C source file not found: {path}")

    if not path.is_file():
        raise ValueError(f"Expected a file, got: {path}")

    # Optional: basic extension check (non-strict)
    if path.suffix.lower() not in {".c", ".h"}:
        warnings.warn(
            f"File does not have a typical C extension: {path.suffix}",
            UserWarning,
            stacklevel=2
        )

    # Safe read
    try:
        code = path.read_text(encoding=encoding, errors=errors)
    except Exception as e:
        raise OSError(f"Failed to read C source file '{path}': {e}") from e

    # Reject empty / whitespace-only files
    if not code.strip():
        raise ValueError(f"C source file is empty: {path}")

    return load_c(code, **kwargs)


def cfunc(
    code: str,
    func_name: Optional[str] = None,
    extra_includes: Optional[List[str]] = None,
    **kwargs: Any
) -> Callable:
    """
    Compile C code and return a specific callable Python function.

    This is a convenience wrapper around :func:`load_c` that extracts a single
    function from the compiled library and returns it as a Python callable.
    If ``func_name`` is not provided and the code contains exactly one function,
    that function is automatically selected.

    Parameters
    ----------
    code : str
        The complete C source code.
    func_name : str, optional
        Name of the function to extract. If None and exactly one function exists
        in the code, that function is returned automatically.
    extra_includes : list of str, optional
        Additional include directories for signature detection (pycparser).
    **kwargs : dict
        Additional arguments passed to :func:`load_c` (e.g., compiler, cflags,
        libraries, includes, defines).

    Returns
    -------
    callable
        The requested C function, wrapped as a Python callable. If automatic
        signature detection is enabled, arguments and return values are
        automatically converted.

    Raises
    ------
    ValueError
        If ``func_name`` is None and the code does not contain exactly one
        function, or if no functions are found.
    AttributeError
        If the specified function name does not exist in the compiled library.

    Examples
    --------
    Simple single function (auto-detected):

    >>> add = cfunc('''
    ...     int add(int a, int b) {
    ...         return a + b;
    ...     }
    ... ''')
    >>> add(3, 5)
    8

    Multiple functions (must specify name):

    >>> square = cfunc('''
    ...     double square(double x) { return x * x; }
    ...     double cube(double x) { return x * x * x; }
    ... ''', func_name='square')
    >>> square(4.0)
    16.0

    With custom compilation flags:

    >>> fast_sum = cfunc('''
    ...     int sum_array(int* arr, int n) {
    ...         int s = 0;
    ...         for (int i = 0; i < n; i++) s += arr[i];
    ...         return s;
    ...     }
    ... ''', cflags=["-O3", "-march=native"])
    """
    lib = load_c(code, extra_includes=extra_includes, **kwargs)

    # Auto-detect function name if not provided
    if func_name is None:
        if PYPARSER_AVAILABLE:
            try:
                functions, _ = parse_c_code(code, extra_includes)
                func_names = list(functions.keys())

                if len(func_names) == 0:
                    raise ValueError(
                        "No functions found in the provided C code."
                    )
                elif len(func_names) == 1:
                    func_name = func_names[0]
                    logger.debug(f"Auto-detected function: {func_name}")
                else:
                    raise ValueError(
                        f"Code contains {len(func_names)} functions; "
                        f"please specify func_name.\n"
                        f"Available functions: {', '.join(func_names)}"
                    )
            except SignatureDetectionError:
                # Fall through to fallback methods
                pass
            else:
                # Successfully detected via pycparser
                try:
                    return getattr(lib, func_name)
                except AttributeError:
                    raise AttributeError(
                        f"Function '{func_name}' found in source but not exported "
                        f"by compiled library. It may be static."
                    )

        # Fallback methods when pycparser is not available
        # Method 1: Try to extract symbols using nm (Unix only)
        if sys.platform.startswith("linux") or sys.platform.startswith("darwin"):
            try:
                import subprocess

                # Use correct nm flags for each platform
                if sys.platform.startswith("linux"):
                    cmd = ['nm', '-D', '--defined-only', lib._name]
                else:  # macOS
                    cmd = ['nm', '-gU', lib._name]  # -gU shows external defined symbols

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                symbols = []
                for line in result.stdout.splitlines():
                    # Look for code symbols
                    # Linux: 'T' for text (code) section
                    # macOS: 'T' or 't' for text section
                    parts = line.split()
                    if len(parts) >= 3:
                        symbol_type = parts[1] if sys.platform.startswith("linux") else parts[0]
                        if symbol_type in ('T', 't'):
                            sym = parts[-1]
                            # Filter out compiler-generated symbols
                            if not sym.startswith('_') or sym in ['_init', '_fini']:
                                symbols.append(sym.lstrip('_'))

                if len(symbols) == 1:
                    func_name = symbols[0]
                    logger.debug(f"Detected function via nm: {func_name}")
                elif len(symbols) > 1:
                    logger.debug(f"Multiple symbols found via nm: {symbols}")

            except (subprocess.SubprocessError, FileNotFoundError, OSError):
                pass

        # Method 2: Simple regex fallback
        if func_name is None:
            # Remove comments and preprocessor directives
            lines = []
            in_comment = False
            for line in code.split('\n'):
                # Remove single-line comments
                line = re.sub(r'//.*$', '', line)

                # Handle multi-line comments
                if '/*' in line:
                    in_comment = True
                    line = line[:line.index('/*')]
                if '*/' in line and in_comment:
                    in_comment = False
                    line = line[line.index('*/') + 2:]

                if not in_comment and not line.startswith('#') and line.strip():
                    lines.append(line)

            clean_code = '\n'.join(lines)

            # Look for function definitions
            # Pattern: return_type function_name(params) {
            func_matches = re.findall(
                r'[a-zA-Z_][a-zA-Z0-9_*\s]+\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)\s*\{',
                clean_code
            )

            if len(func_matches) == 1:
                func_name = func_matches[0]
                logger.debug(f"Detected function via regex: {func_name}")
            elif len(func_matches) == 0:
                raise ValueError(
                    "No functions found in the provided C code."
                )
            else:
                raise ValueError(
                    "func_name must be specified when pycparser is not installed "
                    "and code contains multiple functions.\n"
                    f"Found functions: {', '.join(func_matches)}"
                )

    # Get the function from the library
    try:
        return getattr(lib, func_name)
    except AttributeError:
        # Provide helpful error message
        available = [f for f in dir(lib) if not f.startswith('_')]
        raise AttributeError(
            f"Function '{func_name}' not found in compiled library.\n"
            f"Available exported symbols: {available if available else 'none'}"
        )


def clear_cache(max_age_days: Optional[int] = None) -> int:
    """
    Remove cached compiled libraries from the filesystem.

    This function cleans up the cfast_basic cache directory, removing old or all
    compiled libraries. It's useful for freeing disk space or forcing fresh
    compilations.

    Parameters
    ----------
    max_age_days : int, optional
        If provided, only remove cache directories older than this many days.
        If None, remove all caches regardless of age.

    Returns
    -------
    int
        The number of cache directories that were removed.

    Examples
    --------
    >>> # Clear all caches
    >>> removed = clear_cache()
    >>> print(f"Removed {removed} cache directories")

    >>> # Clear caches older than 7 days
    >>> removed = clear_cache(max_age_days=7)
    >>> print(f"Removed {removed} old cache directories")
    """
    return _clear_cache(max_age_days)


def get_cache_info(cache_key: str) -> Dict[str, Any]:
    """
    Get information about a specific cached library.

    Parameters
    ----------
    cache_key : str
        The 16-character cache key.

    Returns
    -------
    dict
        Dictionary containing cache information. See :func:`cfast_basic.cache.get_cache_info`
        for the structure.

    Examples
    --------
    >>> from cfast_basic.cache import _compute_cache_key
    >>> key = _compute_cache_key(
    ...     code="int f() { return 0; }",
    ...     cflags=[],
    ...     compiler_name="gcc",
    ...     libraries=[],
    ...     includes=[],
    ...     defines={},
    ...     engine_version=ENGINE_VERSION
    ... )
    >>> info = get_cache_info(key)
    >>> if info['library_exists']:
    ...     print(f"Library size: {info['size_bytes']} bytes")
    """
    from .cache import get_cache_info as _get_cache_info
    return _get_cache_info(cache_key)


# Public API exports
__all__ = [
    # Main functions
    'load_c',
    'load_c_file',
    'cfunc',
    'compile_c_code',
    'clear_cache',
    'get_cache_info',

    # Compiler classes
    'Compiler',
    'GccCompiler',
    'ClangCompiler',
    'MsvcCompiler',
    'detect_compiler',

    # Platform info
    'PlatformInfo',

    # Exceptions
    'CompilationError',
    'SignatureDetectionError',
    'CompilerNotFoundError',
    'LockError',

    # Constants
    'ENGINE_VERSION',
    'DEFAULT_CFLAGS',
    'DEFAULT_LIBS',
    'PYPARSER_AVAILABLE',
]