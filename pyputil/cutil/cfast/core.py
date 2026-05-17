#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Core public API for cfast - C Foreign Function Interface for Python.

This module provides the main entry points for users to compile and load
C code dynamically from Python. It offers both a class-based interface
for advanced control and simple function-based APIs for common use cases.

Primary Interfaces
------------------
CFastEngine
    Stateful engine class for managing compilations with consistent settings.
load_c
    Compile and load C code as a ctypes library (function API).
load_c_file
    Load and compile C code from a file.
cfunc
    Get a single C function as a Python callable.
compile_c_code
    Low-level compilation function returning path to compiled library.

Features
--------
- Automatic compiler detection (GCC, Clang, MSVC)
- Disk and memory caching for compiled libraries
- Automatic function signature detection (requires pycparser)
- Thread-safe compilation with file locking
- Cross-platform support (Linux, macOS, Windows)
- Configurable compilation flags and linking options

Security
--------
- Cache keys derived from content hash prevent injection
- Path traversal protection for include directories
- Atomic file operations prevent race conditions
- Process-level file locking for concurrent safety

Examples
--------
>>> import cfast
>>> 
>>> # Simple function loading
>>> add = cfast.cfunc('''
...     int add(int a, int b) {
...         return a + b;
...     }
... ''')
>>> add(5, 3)
8

>>> # Load entire library
>>> lib = cfast.load_c('''
...     #include <math.h>
...     
...     double vector_length(double x, double y) {
...         return sqrt(x*x + y*y);
...     }
...     
...     int factorial(int n) {
...         if (n <= 1) return 1;
...         return n * factorial(n - 1);
...     }
... ''', libraries=['m'])
>>> 
>>> lib.vector_length(3.0, 4.0)
5.0
>>> lib.factorial(5)
120

>>> # Advanced usage with engine
>>> engine = cfast.CFastEngine(
...     cflags=['-O3', '-march=native'],
...     auto_signatures=True
... )
>>> 
>>> lib1 = engine.load('int add(int a, int b) { return a + b; }')
>>> lib2 = engine.load('int mul(int a, int b) { return a * b; }')
>>> 
>>> # Load from file
>>> lib = cfast.load_c_file('mylib.c', cflags=['-Wall', '-O2'])

>>> # Cache management
>>> cfast.clear_cache(max_age_days=30)  # Clear old caches
"""

import ctypes
import logging
import warnings
import sys
import os
import tempfile
import shutil
import time
import hashlib
from pathlib import Path
from typing import (
    Optional, List, Dict, Union, Callable, Any, 
    Tuple, Type, overload, Iterator
)
from dataclasses import dataclass, field
from contextlib import contextmanager
from functools import wraps
from types import FunctionType

from .exceptions import (
    CompilationError, 
    SignatureDetectionError, 
    CacheError,
    CompilerNotFoundError
)
from .platform import PlatformInfo
from .compiler import (
    Compiler, 
    GccCompiler, 
    ClangCompiler, 
    MsvcCompiler,
    detect_compiler,
    validate_compiler_installation,
    CompilerCapabilities,
    CompilationResult,
)
from .cache import (
    CacheManager,
    CacheEntry,
    CacheMetadata,
    FileLock,
    compute_cache_key,
    get_cache_path,
    ensure_cache_dir,
    acquire_cache_lock,
    cleanup_stale_locks,
    CacheEntryStatus,
)
from .parser import (
    set_function_signatures, 
    PYPARSER_AVAILABLE, 
    parse_c_code,
    ParseResult,
    ParsedFunction,
    CTypeMapper,
    CachingParser,
    validate_c_code,
)
from .utils import (
    atomic_write, 
    extract_function_names,
    sanitize_identifier,
    safe_path_join,
    get_file_info,
    format_size,
    calculate_code_hash,
    measure_execution_time,
)

# =============================================================================
# Constants and Configuration
# =============================================================================

ENGINE_VERSION = "2.0.0"

# Default compilation flags
DEFAULT_CFLAGS: List[str] = ["-O2", "-fPIC"]

# Default libraries to link
DEFAULT_LIBS: List[str] = []

# Default compiler preference order
DEFAULT_COMPILER_PREFERENCE = "gcc"

# Maximum source code size (10 MB)
MAX_SOURCE_SIZE = 10 * 1024 * 1024

# Setup logging
logger = logging.getLogger(__name__)
_logger_initialized = False


def _setup_logging(level: int = logging.INFO) -> None:
    """Setup logging configuration."""
    global _logger_initialized
    if _logger_initialized:
        return
    
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(handler)
    logger.setLevel(level)
    _logger_initialized = True


# =============================================================================
# Loaded Library Wrapper
# =============================================================================

@dataclass
class LibraryInfo:
    """Information about a loaded library."""
    path: Path
    source_hash: str
    compiler_name: str
    compiler_version: str
    compilation_time: float
    cache_key: str
    functions: List[str] = field(default_factory=list)
    structs: List[str] = field(default_factory=list)
    size_bytes: int = 0


class CFastLibrary:
    """
    Wrapper around ctypes.CDLL with additional metadata and safety features.
    
    This class extends ctypes.CDLL functionality with:
    - Automatic function signature detection
    - Library metadata tracking
    - Safe function access with validation
    - Comprehensive error messages
    
    Parameters
    ----------
    lib : ctypes.CDLL
        The underlying ctypes library.
    info : LibraryInfo
        Library metadata information.
    
    Attributes
    ----------
    _lib : ctypes.CDLL
        Underlying ctypes library.
    info : LibraryInfo
        Library metadata.
    
    Examples
    --------
    >>> lib = CFastLibrary(ctypes.CDLL('./mylib.so'), info)
    >>> result = lib.add(5, 3)
    >>> print(lib.info.functions)
    ['add', 'subtract', 'multiply']
    """
    
    def __init__(self, lib: ctypes.CDLL, info: LibraryInfo):
        self._lib = lib
        self.info = info
        
    def __getattr__(self, name: str) -> Any:
        """Get attribute from underlying library with validation."""
        if name.startswith('_'):
            return super().__getattribute__(name)
        
        try:
            attr = getattr(self._lib, name)
        except AttributeError:
            available = [f for f in dir(self._lib) if not f.startswith('_')]
            raise AttributeError(
                f"Function '{name}' not found in library.\n"
                f"Available functions: {', '.join(available) if available else 'none'}"
            )
        
        return attr
    
    def __dir__(self) -> List[str]:
        """Return list of available attributes."""
        base = super().__dir__()
        lib_attrs = [a for a in dir(self._lib) if not a.startswith('_')]
        return base + lib_attrs
    
    def __repr__(self) -> str:
        return f"CFastLibrary(path='{self.info.path}', functions={len(self.info.functions)})"
    
    def has_function(self, name: str) -> bool:
        """Check if library exports a specific function."""
        return hasattr(self._lib, name)
    
    def get_function(self, name: str) -> Optional[Callable]:
        """Get a function by name, returning None if not found."""
        return getattr(self._lib, name, None)
    
    def list_functions(self) -> List[str]:
        """List all exported functions."""
        return [f for f in dir(self._lib) if not f.startswith('_')]


# =============================================================================
# Compilation Options
# =============================================================================

@dataclass
class CompileOptions:
    """
    Compilation options for fine-grained control.
    
    Attributes
    ----------
    cflags : List[str]
        Compiler flags.
    libraries : List[str]
        Libraries to link.
    includes : List[str]
        Include directories.
    defines : Dict[str, Optional[str]]
        Preprocessor definitions.
    link_args : List[str]
        Additional linker arguments.
    optimization_level : Optional[int]
        Optimization level (0-3).
    debug : bool
        Include debug symbols.
    warnings_as_errors : bool
        Treat warnings as errors.
    standard : Optional[str]
        C standard (e.g., 'c99', 'c11').
    """
    cflags: List[str] = field(default_factory=list)
    libraries: List[str] = field(default_factory=list)
    includes: List[str] = field(default_factory=list)
    defines: Dict[str, Optional[str]] = field(default_factory=dict)
    link_args: List[str] = field(default_factory=list)
    optimization_level: Optional[int] = None
    debug: bool = False
    warnings_as_errors: bool = False
    standard: Optional[str] = None
    
    def to_cflags(self, compiler_type: str = 'gcc') -> List[str]:
        """Convert options to compiler flags."""
        flags = list(self.cflags)
        
        # Optimization
        if self.optimization_level is not None:
            if compiler_type == 'msvc':
                flags.append(f'/O{self.optimization_level}')
            else:
                flags.append(f'-O{self.optimization_level}')
        
        # Debug
        if self.debug:
            if compiler_type == 'msvc':
                flags.extend(['/Zi', '/DEBUG'])
            else:
                flags.append('-g')
        
        # Warnings
        if self.warnings_as_errors:
            if compiler_type == 'msvc':
                flags.append('/WX')
            else:
                flags.append('-Werror')
        
        # C standard
        if self.standard:
            if compiler_type == 'msvc':
                std_map = {'c89': '/std:c89', 'c99': '/std:c99', 'c11': '/std:c11', 'c17': '/std:c17'}
                flags.append(std_map.get(self.standard, f'/std:{self.standard}'))
            else:
                flags.append(f'-std={self.standard}')
        
        return flags


# =============================================================================
# Main Engine Class
# =============================================================================

class CFastEngine:
    """
    Main engine class for compiling and loading C code.
    
    Provides a stateful interface for repeated compilations with consistent
    settings. Maintains disk and memory caches of compiled libraries and
    supports comprehensive compiler configuration.
    
    Parameters
    ----------
    compiler : Optional[Compiler]
        Compiler instance to use. If None, auto-detected.
    cflags : Optional[List[str]]
        Default compiler flags for all compilations.
    libraries : Optional[List[str]]
        Default libraries to link.
    includes : Optional[List[str]]
        Default include directories.
    defines : Optional[Dict[str, Optional[str]]]
        Default macro definitions.
    link_args : Optional[List[str]]
        Default linker arguments.
    auto_signatures : bool
        Whether to automatically set function signatures.
    enable_cache : bool
        Whether to enable disk caching.
    cache_root : Optional[Path]
        Root directory for cache storage.
    max_cache_size : Optional[int]
        Maximum cache size in bytes.
    max_cache_age_days : Optional[int]
        Maximum cache age in days.
    validate_code : bool
        Whether to validate C code before compilation.
    timeout : int
        Compilation timeout in seconds.
    
    Attributes
    ----------
    compiler : Compiler
        The compiler instance being used.
    cache_manager : CacheManager
        Cache manager instance.
    options : CompileOptions
        Default compilation options.
    auto_signatures : bool
        Whether automatic signature detection is enabled.
    stats : Dict[str, Any]
        Engine statistics (compilations, cache hits, etc.).
    
    Examples
    --------
    >>> # Basic usage
    >>> engine = CFastEngine()
    >>> lib = engine.load('int add(int a, int b) { return a + b; }')
    >>> lib.add(3, 5)
    8
    
    >>> # Advanced configuration
    >>> engine = CFastEngine(
    ...     compiler=GccCompiler(),
    ...     cflags=['-O3', '-march=native'],
    ...     libraries=['m', 'pthread'],
    ...     max_cache_size=1024*1024*1024,  # 1 GB
    ...     max_cache_age_days=30,
    ... )
    
    >>> # With compilation options
    >>> options = CompileOptions(
    ...     optimization_level=3,
    ...     debug=True,
    ...     standard='c11'
    ... )
    >>> lib = engine.load(code, options=options)
    
    >>> # Get statistics
    >>> print(engine.get_stats())
    {'compilations': 5, 'cache_hits': 12, 'cache_misses': 5, ...}
    """
    
    def __init__(
        self,
        compiler: Optional[Compiler] = None,
        cflags: Optional[List[str]] = None,
        libraries: Optional[List[str]] = None,
        includes: Optional[List[str]] = None,
        defines: Optional[Dict[str, Optional[str]]] = None,
        link_args: Optional[List[str]] = None,
        auto_signatures: bool = True,
        enable_cache: bool = True,
        cache_root: Optional[Path] = None,
        max_cache_size: Optional[int] = None,
        max_cache_age_days: Optional[int] = None,
        validate_code: bool = True,
        timeout: int = 120,
    ):
        _setup_logging()
        
        # Initialize compiler
        self.compiler = self._init_compiler(compiler, timeout)
        
        # Default options
        self.default_options = CompileOptions(
            cflags=cflags or DEFAULT_CFLAGS.copy(),
            libraries=libraries or DEFAULT_LIBS.copy(),
            includes=includes or [],
            defines=defines or {},
            link_args=link_args or [],
        )
        
        self.auto_signatures = auto_signatures
        self.validate_code = validate_code
        
        # Initialize cache
        from datetime import timedelta
        max_age = timedelta(days=max_cache_age_days) if max_cache_age_days else None
        
        self.cache_manager = CacheManager(
            cache_root=cache_root,
            max_size=max_cache_size,
            max_age=max_age,
            auto_cleanup=True,
        ) if enable_cache else None
        
        # Parser cache for performance
        self._parser = CachingParser() if PYPARSER_AVAILABLE else None
        
        # In-memory library cache
        self._memory_cache: Dict[str, CFastLibrary] = {}
        
        # Statistics
        self._stats = {
            'compilations': 0,
            'compilation_failures': 0,
            'signature_detections': 0,
            'signature_failures': 0,
            'total_compilation_time': 0.0,
        }
        
        logger.info(
            f"CFastEngine initialized with {self.compiler.name} "
            f"{self.compiler.version}"
        )
    
    def _init_compiler(
        self,
        compiler: Optional[Compiler],
        timeout: int
    ) -> Compiler:
        """Initialize and validate compiler."""
        if compiler is not None:
            return compiler
        
        try:
            detected = detect_compiler(timeout=timeout)
            if detected is None:
                raise CompilerNotFoundError("No C compiler found")
            return detected
        except CompilerNotFoundError as e:
            raise CompilerNotFoundError(
                f"{e}\n"
                "Please install a C compiler:\n"
                "  - Linux: sudo apt install gcc (or build-essential)\n"
                "  - macOS: xcode-select --install\n"
                "  - Windows: Install Visual Studio Build Tools or MinGW"
            ) from e
    
    def _get_cache_key(
        self,
        code: str,
        options: Optional[CompileOptions] = None,
    ) -> str:
        """Compute the cache key for given compilation parameters."""
        opts = options or self.default_options
        
        return compute_cache_key(
            code=code,
            cflags=opts.to_cflags(self.compiler.name),
            compiler_name=self.compiler.name,
            compiler_version=self.compiler.version,
            libraries=opts.libraries,
            includes=opts.includes,
            defines=opts.defines,
            engine_version=ENGINE_VERSION,
        )
    
    def _validate_code(self, code: str) -> None:
        """
        Validate C source code before compilation.
        
        Parameters
        ----------
        code : str
            C source code to validate.
        
        Raises
        ------
        ValueError
            If code fails validation.
        """
        if not code:
            raise ValueError("Source code cannot be empty")
        
        if not isinstance(code, FunctionType) and len(code) > MAX_SOURCE_SIZE:
            raise ValueError(
                f"Source code exceeds maximum size of {format_size(MAX_SOURCE_SIZE)}"
            )
        
        # Check for balanced braces (basic validation)
        brace_count = 0
        paren_count = 0
        in_string = False
        in_char = False
        escape = False
        
        for char in str(code):
            if escape:
                escape = False
                continue
            
            if char == '\\':
                escape = True
                continue
            
            if char == '"' and not in_char:
                in_string = not in_string
            elif char == "'" and not in_string:
                in_char = not in_char
            
            if not in_string and not in_char:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                elif char == '(':
                    paren_count += 1
                elif char == ')':
                    paren_count -= 1
        
        if brace_count != 0:
            raise ValueError(f"Unbalanced braces: {brace_count:+d}")
        
        if paren_count != 0:
            raise ValueError(f"Unbalanced parentheses: {paren_count:+d}")
    
    def compile(
        self,
        code: str,
        options: Optional[CompileOptions] = None,
        force_recompile: bool = False,
    ) -> Path:
        """
        Compile C code into a shared library.
        
        Parameters
        ----------
        code : str
            The C source code to compile.
        options : Optional[CompileOptions]
            Compilation options (overrides defaults).
        force_recompile : bool
            If True, ignore cached library and recompile.
        
        Returns
        -------
        Path
            Path to the compiled shared library.
        
        Raises
        ------
        ValueError
            If code validation fails.
        CompilationError
            If compilation fails.
        """
        start_time = time.time()
        
        # Validate code
        if self.validate_code:
            self._validate_code(code)
        
        opts = options or self.default_options
        
        # Generate cache key
        cache_key = self._get_cache_key(code, opts)
        
        # Check cache
        if self.cache_manager and not force_recompile:
            entry = self.cache_manager.get(cache_key)
            if entry and entry.library_path and entry.library_path.exists():
                logger.debug(f"Cache hit: {cache_key}")
                return entry.library_path
        
        # Prepare cache directory
        cache_dir = ensure_cache_dir(cache_key, 
            self.cache_manager.cache_root if self.cache_manager else None
        )
        
        lib_name = sanitize_identifier(f"cfast_{cache_key[:8]}")
        ext = PlatformInfo.shared_lib_extension()
        so_file = cache_dir / f"{lib_name}{ext}"
        
        # Acquire lock for concurrent safety
        with acquire_cache_lock(cache_dir) as lock:
            # Double-check cache after lock
            if self.cache_manager and not force_recompile:
                entry = self.cache_manager.get(cache_key)
                if entry and entry.library_path and entry.library_path.exists():
                    logger.debug(f"Library compiled by another process: {cache_key}")
                    return entry.library_path
            
            logger.info(
                f"Compiling C code ({len(str(code))} bytes) with {self.compiler.name}",
                extra={'cache_key': cache_key}
            )
            
            try:
                # Write source
                source_file = cache_dir / "source.c"
                atomic_write(source_file, code)
                
                # Prepare includes
                all_includes = list(opts.includes)
                if "#include <Python.h>" in code:
                    all_includes.extend(PlatformInfo.python_include_args())
                
                # Build compiler flags
                cflags = opts.to_cflags(self.compiler.name)
                
                # Compile
                result = self.compiler.compile_shared_library(
                    source=source_file,
                    output=so_file,
                    cflags=cflags,
                    includes=all_includes,
                    defines=opts.defines,
                    libraries=opts.libraries,
                    link_args=opts.link_args,
                )
                
                elapsed = time.time() - start_time
                self._stats['compilations'] += 1
                self._stats['total_compilation_time'] += elapsed
                
                logger.info(
                    f"Compilation successful in {elapsed:.2f}s: {so_file}"
                )
                
                # Store in cache
                if self.cache_manager:
                    metadata = CacheMetadata(
                        cache_key=cache_key,
                        compiler_name=self.compiler.name,
                        compiler_version=self.compiler.version,
                        source_hash=calculate_code_hash(code),
                    )
                    self.cache_manager.store(
                        cache_key, code, so_file, metadata
                    )
                
                return so_file
                
            except CompilationError:
                self._stats['compilation_failures'] += 1
                raise
            except Exception as e:
                self._stats['compilation_failures'] += 1
                raise CompilationError(
                    f"Unexpected error during compilation: {e}"
                ) from e
    
    def load(
        self,
        code: str,
        options: Optional[CompileOptions] = None,
        force_recompile: bool = False,
        extra_includes: Optional[List[str]] = None,
    ) -> CFastLibrary:
        """
        Compile and load C code into a ctypes library.
        
        Parameters
        ----------
        code : str
            Complete C source code.
        options : Optional[CompileOptions]
            Compilation options (overrides defaults).
        force_recompile : bool
            If True, ignore cached library and recompile.
        extra_includes : Optional[List[str]]
            Additional include directories for signature detection.
        
        Returns
        -------
        CFastLibrary
            Loaded library wrapper with configured function signatures.
        
        Raises
        ------
        ValueError
            If code validation fails.
        CompilationError
            If compilation fails.
        
        Examples
        --------
        >>> engine = CFastEngine()
        >>> lib = engine.load('''
        ...     int factorial(int n) {
        ...         if (n <= 1) return 1;
        ...         return n * factorial(n - 1);
        ...     }
        ... ''')
        >>> lib.factorial(5)
        120
        """
        cache_key = self._get_cache_key(code, options)
        
        # Check memory cache
        if cache_key in self._memory_cache and not force_recompile:
            logger.debug(f"Memory cache hit: {cache_key}")
            return self._memory_cache[cache_key]
        
        # Compile
        so_path = self.compile(code, options, force_recompile)
        
        # Load library
        logger.debug(f"Loading library: {so_path}")
        ctypes_lib = ctypes.CDLL(str(so_path))
        
        # Detect functions
        functions = []
        structs = []
        
        if self.auto_signatures and PYPARSER_AVAILABLE:
            try:
                # Parse code for signatures
                parse_result = self._parser.parse(
                    code,
                    extra_includes=extra_includes or options.includes if options else None
                )
                
                # Build struct classes
                from .parser import build_struct_classes
                struct_classes = build_struct_classes(
                    parse_result.structs,
                    parse_result.unions
                )
                
                # Apply signatures
                mapper = CTypeMapper(struct_classes=struct_classes)
                set_function_signatures(
                    ctypes_lib, code,
                    extra_includes=extra_includes,
                    mapper=mapper
                )
                
                functions = list(parse_result.functions.keys())
                structs = list(parse_result.structs.keys())
                
                self._stats['signature_detections'] += 1
                logger.debug(f"Detected {len(functions)} functions")
                
            except Exception as e:
                self._stats['signature_failures'] += 1
                logger.warning(f"Signature detection failed: {e}")
                warnings.warn(
                    f"Automatic signature detection failed: {e}\n"
                    "Function signatures not set. Use manual argtypes/restype.",
                    UserWarning,
                    stacklevel=2
                )
        else:
            # Fallback to regex extraction
            functions = extract_function_names(code)
        
        # Create library info
        info = LibraryInfo(
            path=so_path,
            source_hash=calculate_code_hash(code),
            compiler_name=self.compiler.name,
            compiler_version=self.compiler.version,
            compilation_time=time.time(),
            cache_key=cache_key,
            functions=functions,
            structs=structs,
            size_bytes=so_path.stat().st_size if so_path.exists() else 0,
        )
        
        # Wrap and cache
        lib = CFastLibrary(ctypes_lib, info)
        self._memory_cache[cache_key] = lib
        
        return lib
    
    def get_function(
        self,
        code: str,
        func_name: Optional[str] = None,
        options: Optional[CompileOptions] = None,
        **kwargs
    ) -> Callable:
        """
        Compile C code and return a specific function as a Python callable.
        
        Parameters
        ----------
        code : str
            C source code containing the function(s).
        func_name : Optional[str]
            Name of the function to extract. If None and exactly one function
            exists, that function is returned.
        options : Optional[CompileOptions]
            Compilation options.
        **kwargs
            Additional arguments passed to `load()`.
        
        Returns
        -------
        Callable
            The requested C function with automatic type conversion.
        
        Raises
        ------
        ValueError
            If func_name is None and code does not contain exactly one function.
        AttributeError
            If the specified function name does not exist.
        
        Examples
        --------
        >>> engine = CFastEngine()
        >>> add = engine.get_function('''
        ...     int add(int a, int b) { return a + b; }
        ... ''')
        >>> add(3, 5)
        8
        """
        lib = self.load(code, options=options, **kwargs)
        
        if func_name is None:
            # Try to auto-detect function name
            if lib.info.functions:
                if len(lib.info.functions) == 1:
                    func_name = lib.info.functions[0]
                    logger.debug(f"Auto-detected function: {func_name}")
                else:
                    raise ValueError(
                        f"Code contains {len(lib.info.functions)} functions. "
                        f"Please specify func_name.\n"
                        f"Available: {', '.join(lib.info.functions)}"
                    )
            else:
                # Fallback to regex
                func_names = extract_function_names(code)
                if len(func_names) == 1:
                    func_name = func_names[0]
                else:
                    raise ValueError(
                        "Cannot auto-detect function name. Please specify func_name.\n"
                        f"Found: {', '.join(func_names) if func_names else 'none'}"
                    )
        
        return getattr(lib, func_name)
    
    def compile_file(
        self,
        filepath: Union[str, Path],
        options: Optional[CompileOptions] = None,
        force_recompile: bool = False,
        encoding: str = 'utf-8',
    ) -> Path:
        """
        Compile a C source file into a shared library.
        
        Parameters
        ----------
        filepath : Union[str, Path]
            Path to the C source file.
        options : Optional[CompileOptions]
            Compilation options.
        force_recompile : bool
            If True, ignore cached library and recompile.
        encoding : str
            File encoding.
        
        Returns
        -------
        Path
            Path to compiled shared library.
        
        Raises
        ------
        FileNotFoundError
            If file does not exist.
        ValueError
            If file is empty or invalid.
        CompilationError
            If compilation fails.
        """
        path = Path(filepath)
        
        if not path.exists():
            raise FileNotFoundError(f"C source file not found: {path}")
        
        if not path.is_file():
            raise ValueError(f"Expected a file: {path}")
        
        if path.stat().st_size == 0:
            raise ValueError(f"C source file is empty: {path}")
        
        code = path.read_text(encoding=encoding)
        return self.compile(code, options, force_recompile)
    
    def load_file(
        self,
        filepath: Union[str, Path],
        options: Optional[CompileOptions] = None,
        force_recompile: bool = False,
        encoding: str = 'utf-8',
        **kwargs
    ) -> CFastLibrary:
        """
        Load and compile a C source file.
        
        Parameters
        ----------
        filepath : Union[str, Path]
            Path to the C source file.
        options : Optional[CompileOptions]
            Compilation options.
        force_recompile : bool
            If True, ignore cached library and recompile.
        encoding : str
            File encoding.
        **kwargs
            Additional arguments passed to `load()`.
        
        Returns
        -------
        CFastLibrary
            Loaded library wrapper.
        """
        path = Path(filepath)
        
        if not path.exists():
            raise FileNotFoundError(f"C source file not found: {path}")
        
        if path.suffix.lower() not in ('.c', '.h'):
            warnings.warn(
                f"File does not have typical C extension: {path.suffix}",
                UserWarning,
                stacklevel=2
            )
        
        code = path.read_text(encoding=encoding)
        return self.load(code, options, force_recompile, **kwargs)
    
    def clear_cache(self, memory_only: bool = False) -> int:
        """
        Clear caches.
        
        Parameters
        ----------
        memory_only : bool
            If True, only clear memory cache.
        
        Returns
        -------
        int
            Number of entries cleared.
        """
        cleared = len(self._memory_cache)
        self._memory_cache.clear()
        
        if not memory_only and self.cache_manager:
            cleared += self.cache_manager.clear()
        
        logger.info(f"Cleared {cleared} cache entries")
        return cleared
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get engine statistics.
        
        Returns
        -------
        Dict[str, Any]
            Statistics dictionary.
        """
        stats = dict(self._stats)
        
        if self.cache_manager:
            stats['cache'] = self.cache_manager.get_stats()
        
        stats['memory_cached'] = len(self._memory_cache)
        stats['compiler'] = {
            'name': self.compiler.name,
            'version': self.compiler.version,
            'target': self.compiler.target_platform,
        }
        
        if self._stats['compilations'] > 0:
            stats['avg_compilation_time'] = (
                self._stats['total_compilation_time'] / 
                self._stats['compilations']
            )
        
        return stats
    
    def __repr__(self) -> str:
        return (
            f"CFastEngine(compiler='{self.compiler.name}', "
            f"cached={len(self._memory_cache)}, "
            f"compilations={self._stats['compilations']})"
        )


# =============================================================================
# Global Engine Instance
# =============================================================================

_global_engine: Optional[CFastEngine] = None
_global_engine_lock = __import__('threading').Lock()


def _get_global_engine() -> CFastEngine:
    """Get or create the global engine instance (thread-safe)."""
    global _global_engine
    with _global_engine_lock:
        if _global_engine is None:
            _global_engine = CFastEngine()
        return _global_engine


def reset_global_engine() -> None:
    """Reset the global engine instance."""
    global _global_engine
    with _global_engine_lock:
        if _global_engine is not None:
            _global_engine.clear_cache()
        _global_engine = None


# =============================================================================
# Public API Functions
# =============================================================================

def load_c(
    code: str,
    compiler: Optional[Compiler] = None,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    link_args: Optional[List[str]] = None,
    force_recompile: bool = False,
    auto_signatures: bool = True,
    extra_includes: Optional[List[str]] = None,
    **kwargs
) -> CFastLibrary:
    """
    Compile C code into a shared library and load it with ctypes.
    
    This is the primary function for loading C code dynamically. The library
    is cached based on a hash of the source code, compiler version, and all
    compilation parameters. If pycparser is installed, function signatures
    are automatically detected and applied.
    
    Parameters
    ----------
    code : str
        Complete C source code.
    compiler : Optional[Compiler]
        Compiler instance to use. If None, auto-detected.
    cflags : Optional[List[str]]
        Compiler flags (defaults to ['-O2', '-fPIC']).
    libraries : Optional[List[str]]
        Libraries to link against.
    includes : Optional[List[str]]
        Additional include directories for compilation.
    defines : Optional[Dict[str, Optional[str]]]
        Preprocessor macro definitions.
    link_args : Optional[List[str]]
        Additional linker arguments.
    force_recompile : bool
        If True, ignore cached library and recompile.
    auto_signatures : bool
        If True, attempt to set function signatures automatically.
    extra_includes : Optional[List[str]]
        Additional include directories for signature detection.
    **kwargs
        Additional arguments passed to CFastEngine.
    
    Returns
    -------
    CFastLibrary
        Loaded library wrapper with configured function signatures.
    
    Raises
    ------
    CompilationError
        If compilation fails.
    CompilerNotFoundError
        If no C compiler is found.
    ValueError
        If code validation fails.
    
    Examples
    --------
    >>> import cfast
    >>> 
    >>> # Simple addition
    >>> lib = cfast.load_c('''
    ...     int add(int a, int b) {
    ...         return a + b;
    ...     }
    ... ''')
    >>> lib.add(3, 5)
    8
    
    >>> # With math library
    >>> lib = cfast.load_c('''
    ...     #include <math.h>
    ...     
    ...     double vector_length(double x, double y) {
    ...         return sqrt(x*x + y*y);
    ...     }
    ... ''', libraries=['m'])
    >>> lib.vector_length(3.0, 4.0)
    5.0
    
    >>> # With custom compiler and flags
    >>> from cfast import GccCompiler
    >>> lib = cfast.load_c(
    ...     code='int mul(int a, int b) { return a * b; }',
    ...     compiler=GccCompiler(),
    ...     cflags=['-O3', '-march=native'],
    ...     defines={'DEBUG': None, 'VERSION': '1.0'}
    ... )
    """
    options = CompileOptions(
        cflags=cflags or DEFAULT_CFLAGS.copy(),
        libraries=libraries or [],
        includes=includes or [],
        defines=defines or {},
        link_args=link_args or [],
    )
    
    engine = CFastEngine(
        compiler=compiler,
        auto_signatures=auto_signatures,
        **kwargs
    )
    
    return engine.load(
        code=code,
        options=options,
        force_recompile=force_recompile,
        extra_includes=extra_includes,
    )


def load_c_file(
    filepath: Union[str, Path],
    encoding: str = "utf-8",
    **kwargs
) -> CFastLibrary:
    """
    Load, compile, and link a C source file.
    
    Parameters
    ----------
    filepath : Union[str, Path]
        Path to the C source file.
    encoding : str
        Encoding used to read the file.
    **kwargs
        Additional arguments passed to `load_c`.
    
    Returns
    -------
    CFastLibrary
        The compiled and loaded shared library.
    
    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the path is not a file or is empty.
    CompilationError
        If compilation fails.
    
    Examples
    --------
    >>> lib = cfast.load_c_file("mylib.c")
    >>> result = lib.add(2, 3)
    
    >>> lib = cfast.load_c_file(
    ...     "math_utils.c",
    ...     cflags=["-O2", "-Wall"],
    ...     libraries=["m"]
    ... )
    """
    path = Path(filepath).resolve()
    
    if not path.exists():
        raise FileNotFoundError(f"C source file not found: {path}")
    
    if not path.is_file():
        raise ValueError(f"Expected a file, got: {path}")
    
    if path.stat().st_size == 0:
        raise ValueError(f"C source file is empty: {path}")
    
    try:
        code = path.read_text(encoding=encoding)
    except UnicodeDecodeError as e:
        raise ValueError(f"Failed to decode file with encoding '{encoding}': {e}") from e
    except Exception as e:
        raise OSError(f"Failed to read C source file '{path}': {e}") from e
    
    return load_c(code, **kwargs)


def cfunc(
    code: str,
    func_name: Optional[str] = None,
    **kwargs
) -> Callable:
    """
    Compile C code and return a callable Python function.
    
    This is a convenience wrapper around `load_c` that returns a single
    function directly instead of the entire library object.
    
    Parameters
    ----------
    code : str
        C source code containing the function(s).
    func_name : Optional[str]
        Name of the function to extract. If None and exactly one function
        exists, that function is returned.
    **kwargs
        Additional arguments passed to `load_c`.
    
    Returns
    -------
    Callable
        The requested C function, wrapped as a Python callable.
    
    Raises
    ------
    ValueError
        If func_name is None and code does not contain exactly one function.
    AttributeError
        If the specified function name does not exist.
    CompilationError
        If compilation fails.
    
    Examples
    --------
    >>> import cfast
    >>> 
    >>> # Single function auto-detection
    >>> add = cfast.cfunc('''
    ...     int add(int a, int b) {
    ...         return a + b;
    ...     }
    ... ''')
    >>> add(3, 5)
    8
    
    >>> # Multiple functions with explicit name
    >>> square = cfast.cfunc('''
    ...     double square(double x) { return x * x; }
    ...     double cube(double x) { return x * x * x; }
    ... ''', func_name='square')
    >>> square(4.0)
    16.0
    
    >>> # With custom compiler flags
    >>> fast_add = cfast.cfunc(
    ...     code='int add(int a, int b) { return a + b; }',
    ...     cflags=['-O3', '-march=native']
    ... )
    """
    engine = _get_global_engine()
    
    # Update engine if kwargs provided
    if kwargs:
        engine = CFastEngine(**kwargs)
    
    return engine.get_function(code, func_name, **kwargs)


def compile_c_code(
    code: str,
    output_path: Optional[Union[str, Path]] = None,
    compiler: Optional[Compiler] = None,
    cflags: Optional[List[str]] = None,
    libraries: Optional[List[str]] = None,
    includes: Optional[List[str]] = None,
    defines: Optional[Dict[str, Optional[str]]] = None,
    force_recompile: bool = False,
    **kwargs
) -> Path:
    """
    Compile C code into a shared library (low-level API).
    
    This function provides direct access to the compilation step without
    loading the resulting library. Useful when you only need the compiled
    binary file.
    
    Parameters
    ----------
    code : str
        The C source code.
    output_path : Optional[Union[str, Path]]
        Custom output path. If None, uses cache directory.
    compiler : Optional[Compiler]
        Compiler instance to use.
    cflags : Optional[List[str]]
        Compiler flags.
    libraries : Optional[List[str]]
        Libraries to link.
    includes : Optional[List[str]]
        Additional include directories.
    defines : Optional[Dict[str, Optional[str]]]
        Macro definitions.
    force_recompile : bool
        If True, ignore cache and recompile.
    **kwargs
        Additional arguments passed to CFastEngine.
    
    Returns
    -------
    Path
        Path to the compiled shared library.
    
    Raises
    ------
    CompilationError
        If compilation fails.
    
    Examples
    --------
    >>> # Compile to default cache location
    >>> lib_path = cfast.compile_c_code('''
    ...     int add(int a, int b) { return a + b; }
    ... ''')
    >>> print(lib_path)
    /tmp/cfast_cache/abc123/cfast_abc123.so
    
    >>> # Compile to custom location
    >>> lib_path = cfast.compile_c_code(
    ...     code='int mul(int a, int b) { return a * b; }',
    ...     output_path='./mylib.so',
    ...     cflags=['-O3']
    ... )
    """
    if output_path:
        # Custom output path - bypass cache
        engine = CFastEngine(compiler=compiler, enable_cache=False, **kwargs)
        options = CompileOptions(
            cflags=cflags or DEFAULT_CFLAGS.copy(),
            libraries=libraries or [],
            includes=includes or [],
            defines=defines or {},
        )
        
        # Compile directly to output path
        cache_dir = Path(output_path).parent
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        source_file = cache_dir / "temp_source.c"
        atomic_write(source_file, code)
        
        try:
            engine.compiler.compile_shared_library(
                source=source_file,
                output=Path(output_path),
                cflags=options.to_cflags(engine.compiler.name),
                includes=options.includes,
                defines=options.defines,
                libraries=options.libraries,
            )
            return Path(output_path)
        finally:
            source_file.unlink(missing_ok=True)
    else:
        # Use cache
        engine = CFastEngine(compiler=compiler, **kwargs)
        options = CompileOptions(
            cflags=cflags or DEFAULT_CFLAGS.copy(),
            libraries=libraries or [],
            includes=includes or [],
            defines=defines or {},
        )
        return engine.compile(code, options, force_recompile)


def validate_c_code(
    code: str,
    extra_includes: Optional[List[str]] = None
) -> Tuple[bool, List[str]]:
    """
    Validate C code syntax without compiling.
    
    Parameters
    ----------
    code : str
        C source code to validate.
    extra_includes : Optional[List[str]]
        Additional include directories.
    
    Returns
    -------
    Tuple[bool, List[str]]
        - bool: True if valid, False otherwise
        - List[str]: List of validation errors/warnings
    
    Examples
    --------
    >>> is_valid, errors = cfast.validate_c_code('''
    ...     int add(int a, int b) {
    ...         return a + b
    ...     }
    ... ''')
    >>> if not is_valid:
    ...     for error in errors:
    ...         print(error)
    """
    if PYPARSER_AVAILABLE:
        return validate_c_code(code, extra_includes)
    else:
        # Basic validation only
        errors = []
        try:
            engine = CFastEngine(validate_code=True, enable_cache=False)
            engine._validate_code(code)
            return True, []
        except ValueError as e:
            return False, [str(e)]


def clear_cache(
    max_age_days: Optional[int] = None,
    memory_only: bool = False
) -> int:
    """
    Remove cached compiled libraries.
    
    Parameters
    ----------
    max_age_days : Optional[int]
        If given, only remove cache entries older than this many days.
    memory_only : bool
        If True, only clear memory cache.
    
    Returns
    -------
    int
        Number of cache entries removed.
    
    Examples
    --------
    >>> # Clear all caches
    >>> cfast.clear_cache()
    
    >>> # Clear caches older than 7 days
    >>> cfast.clear_cache(max_age_days=7)
    
    >>> # Clear only memory cache
    >>> cfast.clear_cache(memory_only=True)
    """
    global _global_engine

    from datetime import timedelta
    
    max_age = timedelta(days=max_age_days) if max_age_days else None
    
    if memory_only:
        if _global_engine is not None:
            return _global_engine.clear_cache(memory_only=True)
        return 0
    
    manager = CacheManager(max_age=max_age)
    cleared = manager.cleanup()
    
    # Also clear global engine's memory cache
    if _global_engine is not None:
        cleared += _global_engine.clear_cache(memory_only=True)
    
    logger.info(f"Cleared {cleared} cache entries")
    return cleared


def get_cache_info() -> Dict[str, Any]:
    """
    Get information about the cache.
    
    Returns
    -------
    Dict[str, Any]
        Cache information including size, entry count, location.
    
    Examples
    --------
    >>> info = cfast.get_cache_info()
    >>> print(f"Cache size: {info['formatted_size']}")
    >>> print(f"Entries: {info['entry_count']}")
    """
    manager = CacheManager()
    stats = manager.get_stats()
    
    stats['cache_root'] = str(manager.cache_root)
    stats['formatted_size'] = format_size(stats.get('cache_size', 0))
    
    return stats


def list_cached_libraries() -> List[Dict[str, Any]]:
    """
    List all cached libraries with their metadata.
    
    Returns
    -------
    List[Dict[str, Any]]
        List of cache entry information.
    
    Examples
    --------
    >>> entries = cfast.list_cached_libraries()
    >>> for entry in entries:
    ...     print(f"{entry['cache_key'][:8]}: {entry['compiler_name']}")
    """
    manager = CacheManager()
    entries = []
    
    if manager.cache_root.exists():
        for cache_dir in manager.cache_root.iterdir():
            if cache_dir.is_dir():
                entry = CacheEntry.from_cache_dir(cache_dir)
                if entry:
                    entries.append({
                        'cache_key': entry.metadata.cache_key,
                        'compiler_name': entry.metadata.compiler_name,
                        'compiler_version': entry.metadata.compiler_version,
                        'created': entry.metadata.created_at,
                        'size': entry.metadata.file_size,
                        'status': entry.status.name,
                    })
    
    return sorted(entries, key=lambda e: e['created'], reverse=True)


def set_log_level(level: Union[int, str]) -> None:
    """
    Set the logging level for cfast.
    
    Parameters
    ----------
    level : Union[int, str]
        Logging level (e.g., logging.DEBUG, 'DEBUG', 'INFO').
    
    Examples
    --------
    >>> import logging
    >>> cfast.set_log_level(logging.DEBUG)
    >>> cfast.set_log_level('INFO')
    """
    _setup_logging()
    
    if isinstance(level, str):
        level = getattr(logging, level.upper())
    
    logger.setLevel(level)


# =============================================================================
# Convenience Aliases
# =============================================================================

# Aliases for backward compatibility
load = load_c
load_file = load_c_file
compile_code = compile_c_code


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Main classes
    'CFastEngine',
    'CFastLibrary',
    'LibraryInfo',
    'CompileOptions',
    
    # Main functions
    'load_c',
    'load_c_file',
    'cfunc',
    'compile_c_code',
    'validate_c_code',
    
    # Cache management
    'clear_cache',
    'get_cache_info',
    'list_cached_libraries',
    
    # Utilities
    'set_log_level',
    'reset_global_engine',
    
    # Aliases
    'load',
    'load_file',
    'compile_code',
    
    # Constants
    'ENGINE_VERSION',
    'DEFAULT_CFLAGS',
    'DEFAULT_LIBS',
]