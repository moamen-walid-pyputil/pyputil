#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
===============================================================================
                    C/C++ MODULE LOADER - COMPREHENSIVE FIXED VERSION
===============================================================================

Advanced C/C++ extension module loader with cross-platform compilation,
intelligent caching, dependency resolution, and hot reloading.

This module provides a complete solution for compiling and loading C/C++ 
source files as Python extension modules with automatic dependency management,
cross-platform support, and intelligent caching mechanisms.

Author: CImporter Team
Version: 2.0.0
License: MIT
===============================================================================
"""

# =============================================================================
# STANDARD LIBRARY IMPORTS
# =============================================================================
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import logging

# =============================================================================
# INTERNAL MODULE IMPORTS
# =============================================================================

# Base components
from .base import (
    BaseLoader,
    LoaderConfig,
    LoaderState,
    LoaderEventType,
    ModuleMetadata,
    ModuleOrigin,
    ModuleProxy,
    BatchLoader,
)

# Core exceptions
from ..core.exceptions import (
    CompileError,
    LinkerError,
    ImportModuleError,
    CacheError,
    PlatformError,
    DependencyError,
    ConfigError,
    ErrorCategory,
    ErrorSeverity,
)

# Core enums
from ..core.enums import (
    OptimizationLevel,
    SIMDLevel,
    BuildMode,
    CacheStrategy,
    ParallelStrategy,
    LogLevel,
    LanguageStandard,
    LinkType,
    SandboxPolicy,
    DependencyType,
)

# Cache system
from ..core.cache import CacheKey, CacheKeyBuilder, CacheManager

# Compiler system
from ..compilers import (
    CompilerBackend,
    CompilerFamily,
    CompilerFeature,
    CompilerInfo,
    CompileResult,
    GCCBackend,
    ClangBackend,
    MSVCBackend,
    ICCBackend,
    CompilerDetector,
    CompilerRegistry,
    FlagNormalizer,
    OptimizationPreset,
    SIMDPreset,
    WarningPreset,
    detect_compiler,
    get_compiler_registry,
    normalize_flags,
)

# Sandbox
from ..sandbox import SandboxManager, ResourceLimits

# Platform utilities
from ..utils.platform_ import (
    get_platform,
    get_architecture,
    get_shared_library_extension,
    get_executable_extension,
    get_python_include_paths,
    get_python_library_paths,
    get_python_version,
    is_windows,
    is_linux,
    is_macos,
)

# Setup logger
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# =============================================================================
# ENUMERATIONS
# =============================================================================

class CSourceType(Enum):
    """
    C/C++ source file type enumeration.

    This enumeration defines all possible C/C++ file types that the loader
    can handle, including source files, headers, object files, libraries,
    and Python extension modules.

    Attributes
    ----------
    C_SOURCE : str
        C source file with .c extension.
    C_HEADER : str
        C header file with .h extension.
    CPP_SOURCE : str
        C++ source file with .cpp, .cc, .cxx, .c++, or .C extension.
    CPP_HEADER : str
        C++ header file with .hpp, .hh, .hxx, .h++, or .H extension.
    OBJECT : str
        Compiled object file with .o (Unix) or .obj (Windows) extension.
    STATIC_LIBRARY : str
        Static library with .a (Unix) or .lib (Windows) extension.
    SHARED_LIBRARY : str
        Shared/dynamic library with .so (Unix), .dll (Windows), or .dylib (macOS) extension.
    PYTHON_MODULE : str
        Python extension module with .pyd (Windows) or .so (Unix) extension.
    PREPROCESSED : str
        Preprocessed source with .i (C) or .ii (C++) extension.
    ASSEMBLY : str
        Assembly source with .s, .S, or .asm extension.
    UNKNOWN : str
        Unknown or unrecognized file type.

    Examples
    --------
    >>> source_type = CSourceType.from_extension(Path("main.cpp"))
    >>> print(source_type)
    CSourceType.CPP_SOURCE
    >>> print(source_type.is_source())
    True
    >>> print(source_type.get_language())
    'c++'
    """

    C_SOURCE = "c_source"
    C_HEADER = "c_header"
    CPP_SOURCE = "cpp_source"
    CPP_HEADER = "cpp_header"
    OBJECT = "object"
    STATIC_LIBRARY = "static_library"
    SHARED_LIBRARY = "shared_library"
    PYTHON_MODULE = "python_module"
    PREPROCESSED = "preprocessed"
    ASSEMBLY = "assembly"
    UNKNOWN = "unknown"

    @classmethod
    def from_extension(cls, path: Path) -> "CSourceType":
        """
        Determine source type from file extension.

        This method examines the file extension of the given path and returns
        the appropriate CSourceType enumeration value. The detection is
        case-insensitive and supports all common C/C++ file extensions across
        different platforms.

        Parameters
        ----------
        path : Path
            File path to examine.

        Returns
        -------
        CSourceType
            The detected source type. Returns CSourceType.UNKNOWN if the
            extension is not recognized.

        Notes
        -----
        The method handles platform-specific variations:
        - Windows: .obj, .lib, .dll, .pyd
        - Unix/Linux: .o, .a, .so
        - macOS: .dylib

        Examples
        --------
        >>> CSourceType.from_extension(Path("program.c"))
        CSourceType.C_SOURCE
        
        >>> CSourceType.from_extension(Path("library.hpp"))
        CSourceType.CPP_HEADER
        
        >>> CSourceType.from_extension(Path("module.pyd"))
        CSourceType.PYTHON_MODULE
        """
        suffix = path.suffix.lower()

        # C sources
        if suffix == ".c":
            return cls.C_SOURCE
        if suffix == ".h":
            return cls.C_HEADER

        # C++ sources
        if suffix in (".cpp", ".cc", ".cxx", ".c++", ".C"):
            return cls.CPP_SOURCE
        if suffix in (".hpp", ".hh", ".hxx", ".h++", ".H"):
            return cls.CPP_HEADER

        # Object files
        if suffix in (".o", ".obj"):
            return cls.OBJECT

        # Libraries
        if suffix in (".a", ".lib"):
            return cls.STATIC_LIBRARY
        if suffix in (".so", ".dll", ".dylib"):
            return cls.SHARED_LIBRARY

        # Python modules
        if suffix == ".pyd" or (suffix == ".so" and ".cpython" in path.name):
            return cls.PYTHON_MODULE

        # Preprocessed
        if suffix in (".i", ".ii"):
            return cls.PREPROCESSED

        # Assembly
        if suffix in (".s", ".S", ".asm"):
            return cls.ASSEMBLY

        return cls.UNKNOWN

    def is_source(self) -> bool:
        """
        Check if this type is a compilable source file.

        Compilable source files include C sources, C++ sources, and assembly
        files. These files can be passed directly to the compiler for
        compilation into object files.

        Returns
        -------
        bool
            True if the file type is compilable source, False otherwise.

        Examples
        --------
        >>> CSourceType.C_SOURCE.is_source()
        True
        >>> CSourceType.CPP_SOURCE.is_source()
        True
        >>> CSourceType.C_HEADER.is_source()
        False
        """
        return self in (self.C_SOURCE, self.CPP_SOURCE, self.ASSEMBLY)

    def is_header(self) -> bool:
        """
        Check if this type is a header file.

        Header files are included by source files and are not compiled directly.
        They are used for dependency tracking and precompiled header generation.

        Returns
        -------
        bool
            True if the file type is a header file, False otherwise.

        Examples
        --------
        >>> CSourceType.C_HEADER.is_header()
        True
        >>> CSourceType.CPP_HEADER.is_header()
        True
        >>> CSourceType.C_SOURCE.is_header()
        False
        """
        return self in (self.C_HEADER, self.CPP_HEADER)

    def is_cpp(self) -> bool:
        """
        Check if this type is C++ (source or header).

        This method identifies C++ files as opposed to C files. This is
        important for selecting the appropriate compiler flags and language
        standard.

        Returns
        -------
        bool
            True if the file type is C++ source or header, False otherwise.

        Examples
        --------
        >>> CSourceType.CPP_SOURCE.is_cpp()
        True
        >>> CSourceType.CPP_HEADER.is_cpp()
        True
        >>> CSourceType.C_SOURCE.is_cpp()
        False
        """
        return self in (self.CPP_SOURCE, self.CPP_HEADER)

    def get_language(self) -> str:
        """
        Get language identifier for compiler.

        Returns the appropriate language identifier string that can be passed
        to the compiler's language selection flags (e.g., -x c or -x c++).

        Returns
        -------
        str
            Language identifier: 'c' for C files, 'c++' for C++ files.

        Examples
        --------
        >>> CSourceType.C_SOURCE.get_language()
        'c'
        >>> CSourceType.CPP_SOURCE.get_language()
        'c++'
        >>> CSourceType.CPP_HEADER.get_language()
        'c++'
        """
        if self.is_cpp():
            return "c++"
        return "c"


# =============================================================================
# CONFIGURATION DATACLASSES
# =============================================================================

@dataclass
class CompilationConfig:
    """
    Comprehensive configuration for C/C++ compilation.

    This dataclass encapsulates all compilation settings including
    optimization levels, SIMD instruction sets, language standards,
    and platform-specific flags. It provides a unified interface for
    configuring the compilation process across different compilers
    and platforms.

    Parameters
    ----------
    optimization_level : OptimizationLevel, optional
        Basic optimization level preset. Default is OptimizationLevel.STANDARD.
    optimization_preset : OptimizationPreset, optional
        Advanced optimization preset that overrides optimization_level.
        Takes precedence if provided. Default is None.
    simd_level : SIMDLevel, optional
        SIMD instruction set level. Default is SIMDLevel.NONE.
    simd_preset : SIMDPreset, optional
        Advanced SIMD preset that overrides simd_level.
        Takes precedence if provided. Default is None.
    language_standard : LanguageStandard, optional
        C/C++ language standard to enforce. Default is None (compiler default).
    warning_level : WarningPreset, optional
        Warning level preset. Default is WarningPreset.NORMAL.
    build_mode : BuildMode, optional
        Build mode (debug, release, etc.). Default is BuildMode.RELEASE.
    extra_flags : List[str], optional
        Additional raw compiler flags passed directly to compiler.
        Default is empty list.
    extra_logical_flags : List[str], optional
        Additional logical flags that are normalized per compiler.
        Default is empty list.
    defines : Dict[str, str], optional
        Preprocessor macro definitions. Keys are macro names, values are
        their definitions (empty string for definition without value).
        Default is empty dict.
    undefines : List[str], optional
        Macros to explicitly undefine. Default is empty list.
    include_paths : List[Path], optional
        Additional include search directories. Default is empty list.
    library_paths : List[Path], optional
        Additional library search directories. Default is empty list.
    libraries : List[str], optional
        Libraries to link against. Default is empty list.
    link_type : LinkType, optional
        Type of output linking. Default is LinkType.MODULE.
    position_independent : bool, optional
        Generate position-independent code (required for shared libraries).
        Default is True.
    debug_symbols : bool, optional
        Include debug symbols in output. Default is False.
    openmp : bool, optional
        Enable OpenMP parallelization support. Default is False.
    lto : bool, optional
        Enable Link-Time Optimization. Default is False.
    fast_math : bool, optional
        Enable fast math optimizations (may violate IEEE standards).
        Default is False.
    exceptions : bool, optional
        Enable C++ exception handling. Default is True.
    rtti : bool, optional
        Enable C++ Run-Time Type Information. Default is True.
    threads : bool, optional
        Enable threading support. Default is True.
    sanitizers : List[str], optional
        List of sanitizers to enable (e.g., 'address', 'thread', 'undefined').
        Default is empty list.
    security_hardening : bool, optional
        Enable security hardening flags (stack protector, etc.).
        Default is False.
    verbose : bool, optional
        Show verbose compilation output. Default is False.
    keep_intermediates : bool, optional
        Keep intermediate files (.o, .i) after compilation. Default is False.
    compile_timeout : float, optional
        Timeout for compilation in seconds. Default is 300.0 (5 minutes).
    max_parallel_jobs : int, optional
        Maximum parallel compilation jobs. None means auto-detect.
        Default is None.
    custom_compiler : str, optional
        Custom compiler executable path or name. Default is None.
    custom_linker : str, optional
        Custom linker executable path. Default is None.

    Attributes
    ----------
    optimization_level : OptimizationLevel
        Basic optimization level.
    optimization_preset : Optional[OptimizationPreset]
        Advanced optimization preset.
    simd_level : SIMDLevel
        SIMD instruction set level.
    simd_preset : Optional[SIMDPreset]
        Advanced SIMD preset.
    language_standard : Optional[LanguageStandard]
        Language standard.
    warning_level : WarningPreset
        Warning level.
    build_mode : BuildMode
        Build mode.
    extra_flags : List[str]
        Raw extra compiler flags.
    extra_logical_flags : List[str]
        Logical extra flags.
    defines : Dict[str, str]
        Preprocessor definitions.
    undefines : List[str]
        Macros to undefine.
    include_paths : List[Path]
        Include search paths.
    library_paths : List[Path]
        Library search paths.
    libraries : List[str]
        Libraries to link.
    link_type : LinkType
        Output link type.
    position_independent : bool
        Position-independent code flag.
    debug_symbols : bool
        Debug symbols flag.
    openmp : bool
        OpenMP support flag.
    lto : bool
        Link-time optimization flag.
    fast_math : bool
        Fast math flag.
    exceptions : bool
        Exception handling flag.
    rtti : bool
        RTTI flag.
    threads : bool
        Threading support flag.
    sanitizers : List[str]
        Enabled sanitizers.
    security_hardening : bool
        Security hardening flag.
    verbose : bool
        Verbose output flag.
    keep_intermediates : bool
        Keep intermediate files flag.
    compile_timeout : Optional[float]
        Compilation timeout.
    max_parallel_jobs : Optional[int]
        Maximum parallel jobs.
    custom_compiler : Optional[str]
        Custom compiler path.
    custom_linker : Optional[str]
        Custom linker path.

    Examples
    --------
    >>> # Basic configuration
    >>> config = CompilationConfig(
    ...     optimization_preset=OptimizationPreset.SPEED,
    ...     language_standard=LanguageStandard.CPP17,
    ... )
    
    >>> # Advanced configuration with all features
    >>> config = CompilationConfig(
    ...     optimization_preset=OptimizationPreset.AGGRESSIVE,
    ...     simd_preset=SIMDPreset.AVX2,
    ...     language_standard=LanguageStandard.CPP20,
    ...     warning_level=WarningPreset.PEDANTIC,
    ...     build_mode=BuildMode.RELEASE,
    ...     defines={"NDEBUG": "", "VERSION": "1.0.0"},
    ...     include_paths=[Path("/usr/local/include")],
    ...     libraries=["m", "pthread"],
    ...     openmp=True,
    ...     lto=True,
    ...     fast_math=True,
    ...     security_hardening=True,
    ... )
    >>> warnings = config.validate()
    >>> if warnings:
    ...     for warning in warnings:
    ...         print(f"Warning: {warning}")
    """

    # Optimization settings
    optimization_level: OptimizationLevel = OptimizationLevel.STANDARD
    optimization_preset: Optional[OptimizationPreset] = None

    # SIMD settings
    simd_level: SIMDLevel = SIMDLevel.NONE
    simd_preset: Optional[SIMDPreset] = None

    # Language settings
    language_standard: Optional[LanguageStandard] = None
    warning_level: WarningPreset = WarningPreset.NORMAL

    # Build mode
    build_mode: BuildMode = BuildMode.RELEASE

    # Extra flags
    extra_flags: List[str] = field(default_factory=list)
    extra_logical_flags: List[str] = field(default_factory=list)

    # Preprocessor settings
    defines: Dict[str, str] = field(default_factory=dict)
    undefines: List[str] = field(default_factory=list)

    # Path settings
    include_paths: List[Path] = field(default_factory=list)
    library_paths: List[Path] = field(default_factory=list)
    libraries: List[str] = field(default_factory=list)

    # Linking settings
    link_type: LinkType = LinkType.MODULE
    position_independent: bool = True

    # Debug settings
    debug_symbols: bool = False

    # Feature toggles
    openmp: bool = False
    lto: bool = False
    fast_math: bool = False
    exceptions: bool = True
    rtti: bool = True
    threads: bool = True

    # Sanitizers
    sanitizers: List[str] = field(default_factory=list)

    # Security
    security_hardening: bool = False

    # Compilation control
    verbose: bool = False
    keep_intermediates: bool = False
    compile_timeout: Optional[float] = 300.0
    max_parallel_jobs: Optional[int] = None

    # Custom tools
    custom_compiler: Optional[str] = None
    custom_linker: Optional[str] = None

    def get_optimization_preset(self) -> OptimizationPreset:
        """
        Get the effective optimization preset.

        This method determines the actual optimization preset to use based on:
        1. Explicitly set optimization_preset
        2. Build mode mapping (if optimization_preset is None)
        3. Default to BALANCED

        Returns
        -------
        OptimizationPreset
            The effective optimization preset to apply.

        Notes
        -----
        Build mode mappings:
        - DEBUG → OptimizationPreset.DEBUG
        - RELEASE → OptimizationPreset.BALANCED
        - RELWITHDEBINFO → OptimizationPreset.BALANCED
        - MINSIZEREL → OptimizationPreset.SIZE
        - PROFILE → OptimizationPreset.SPEED
        - COVERAGE → OptimizationPreset.DEBUG
        - SANITIZE → OptimizationPreset.DEBUG

        Examples
        --------
        >>> config = CompilationConfig(build_mode=BuildMode.DEBUG)
        >>> config.get_optimization_preset()
        OptimizationPreset.DEBUG
        
        >>> config = CompilationConfig(optimization_preset=OptimizationPreset.SPEED)
        >>> config.get_optimization_preset()
        OptimizationPreset.SPEED
        """
        if self.optimization_preset is not None:
            return self.optimization_preset

        # Map from build mode
        mode_map = {
            BuildMode.DEBUG: OptimizationPreset.DEBUG,
            BuildMode.RELEASE: OptimizationPreset.BALANCED,
            BuildMode.RELWITHDEBINFO: OptimizationPreset.BALANCED,
            BuildMode.MINSIZEREL: OptimizationPreset.SIZE,
            BuildMode.PROFILE: OptimizationPreset.SPEED,
            BuildMode.COVERAGE: OptimizationPreset.DEBUG,
            BuildMode.SANITIZE: OptimizationPreset.DEBUG,
        }
        return mode_map.get(self.build_mode, OptimizationPreset.BALANCED)

    def get_simd_preset(self) -> SIMDPreset:
        """
        Get the effective SIMD preset.

        This method determines the actual SIMD preset to use based on:
        1. Explicitly set simd_preset
        2. SIMD level mapping (if simd_preset is None)
        3. Default to AUTO

        Returns
        -------
        SIMDPreset
            The effective SIMD preset to apply.

        Notes
        -----
        SIMD level mappings:
        - NONE → SIMDPreset.NONE
        - SSE2 → SIMDPreset.SSE2
        - SSE3 → SIMDPreset.SSE2
        - SSSE3 → SIMDPreset.SSE2
        - SSE4_1 → SIMDPreset.SSE4_2
        - SSE4_2 → SIMDPreset.SSE4_2
        - AVX → SIMDPreset.AVX
        - AVX2 → SIMDPreset.AVX2
        - AVX512 → SIMDPreset.AVX512
        - NEON → SIMDPreset.NEON

        Examples
        --------
        >>> config = CompilationConfig(simd_level=SIMDLevel.AVX2)
        >>> config.get_simd_preset()
        SIMDPreset.AVX2
        """
        if self.simd_preset is not None:
            return self.simd_preset

        # Map from SIMDLevel
        level_map = {
            SIMDLevel.NONE: SIMDPreset.NONE,
            SIMDLevel.SSE2: SIMDPreset.SSE2,
            SIMDLevel.SSE3: SIMDPreset.SSE2,
            SIMDLevel.SSSE3: SIMDPreset.SSE2,
            SIMDLevel.SSE4_1: SIMDPreset.SSE4_2,
            SIMDLevel.SSE4_2: SIMDPreset.SSE4_2,
            SIMDLevel.AVX: SIMDPreset.AVX,
            SIMDLevel.AVX2: SIMDPreset.AVX2,
            SIMDLevel.AVX512: SIMDPreset.AVX512,
            SIMDLevel.NEON: SIMDPreset.NEON,
        }
        return level_map.get(self.simd_level, SIMDPreset.AUTO)

    def get_warning_preset(self) -> WarningPreset:
        """
        Get the effective warning preset.

        For debug builds, returns WarningPreset.EXTRA to catch more issues.
        Otherwise returns the configured warning_level.

        Returns
        -------
        WarningPreset
            The effective warning preset to apply.

        Examples
        --------
        >>> config = CompilationConfig(build_mode=BuildMode.DEBUG)
        >>> config.get_warning_preset()
        WarningPreset.EXTRA
        
        >>> config = CompilationConfig(
        ...     build_mode=BuildMode.RELEASE,
        ...     warning_level=WarningPreset.PEDANTIC
        ... )
        >>> config.get_warning_preset()
        WarningPreset.PEDANTIC
        """
        if self.build_mode == BuildMode.DEBUG:
            return WarningPreset.EXTRA
        return self.warning_level

    def get_language(self, source_type: CSourceType) -> str:
        """
        Get language string for a source type.

        Parameters
        ----------
        source_type : CSourceType
            Source file type.

        Returns
        -------
        str
            Language identifier ('c' or 'c++').

        Examples
        --------
        >>> config = CompilationConfig()
        >>> config.get_language(CSourceType.CPP_SOURCE)
        'c++'
        """
        return source_type.get_language()

    def validate(self) -> List[str]:
        """
        Validate configuration and return warnings.

        This method checks for potential issues in the configuration that
        might cause problems during compilation, such as incompatible
        combinations of flags or settings that may significantly slow down
        the build process.

        Returns
        -------
        List[str]
            List of validation warning messages. Empty list if no warnings.

        Notes
        -----
        Current validation checks:
        - LTO with debug builds (slow compilation)
        - OpenMP without threading support
        - Sanitizers with aggressive optimizations (potential conflicts)

        Examples
        --------
        >>> config = CompilationConfig(lto=True, build_mode=BuildMode.DEBUG)
        >>> warnings = config.validate()
        >>> warnings
        ['LTO with debug build may slow compilation significantly']
        """
        warnings = []

        # Check for LTO with debug builds
        if self.lto and self.build_mode == BuildMode.DEBUG:
            warnings.append("LTO with debug build may slow compilation significantly")

        # Check OpenMP requires threading
        if self.openmp and not self.threads:
            warnings.append("OpenMP requires threading support")

        # Check sanitizers with aggressive optimizations
        if self.sanitizers and self.optimization_preset == OptimizationPreset.AGGRESSIVE:
            warnings.append("Sanitizers may conflict with aggressive optimizations")

        return warnings


@dataclass
class CompilationUnit:
    """
    Represents a single compilation unit (source file).

    This dataclass tracks all information related to a single source file
    being compiled, including its dependencies, compilation status, and
    compilation timing information. It supports incremental compilation
    by tracking when files were last compiled and checking for changes.

    Parameters
    ----------
    source_path : Path
        Absolute path to the source file.
    source_type : CSourceType
        Type of the source file (C, C++, assembly, etc.).
    object_path : Optional[Path], optional
        Path where the compiled object file will be written.
        Generated automatically if not provided. Default is None.
    dependencies : List[Path], optional
        List of header files this source depends on.
        Populated by dependency parser. Default is empty list.
    defines : Dict[str, str], optional
        Unit-specific preprocessor definitions. Default is empty dict.
    include_paths : List[Path], optional
        Unit-specific include search paths. Default is empty list.
    extra_flags : List[str], optional
        Unit-specific compiler flags. Default is empty list.
    compiled_at : Optional[float], optional
        Timestamp (time.time()) when last compiled. Default is None.
    compile_time : float, optional
        Time in seconds taken to compile this unit. Default is 0.0.

    Attributes
    ----------
    source_path : Path
        Source file path.
    source_type : CSourceType
        Source file type.
    object_path : Optional[Path]
        Object file output path.
    dependencies : List[Path]
        Header dependencies.
    defines : Dict[str, str]
        Unit-specific defines.
    include_paths : List[Path]
        Unit-specific include paths.
    extra_flags : List[str]
        Unit-specific compiler flags.
    compiled_at : Optional[float]
        Compilation timestamp.
    compile_time : float
        Compilation duration in seconds.

    Examples
    --------
    >>> unit = CompilationUnit(
    ...     source_path=Path("main.cpp"),
    ...     source_type=CSourceType.CPP_SOURCE,
    ... )
    >>> if unit.needs_recompile():
    ...     print("Needs recompilation")
    >>> hash_value = unit.get_dependency_hash()
    """

    source_path: Path
    source_type: CSourceType
    object_path: Optional[Path] = None
    dependencies: List[Path] = field(default_factory=list)
    defines: Dict[str, str] = field(default_factory=dict)
    include_paths: List[Path] = field(default_factory=list)
    extra_flags: List[str] = field(default_factory=list)
    compiled_at: Optional[float] = None
    compile_time: float = 0.0

    def needs_recompile(self) -> bool:
        """
        Check if this unit needs recompilation.

        A unit needs recompilation if:
        1. It has never been compiled (compiled_at is None)
        2. The object file doesn't exist
        3. The source file has been modified since last compilation
        4. Any dependency header has been modified since last compilation

        Returns
        -------
        bool
            True if recompilation is needed, False otherwise.

        Examples
        --------
        >>> unit = CompilationUnit(Path("main.c"), CSourceType.C_SOURCE)
        >>> unit.needs_recompile()
        True
        >>> # After compilation
        >>> unit.compiled_at = time.time()
        >>> unit.object_path = Path("main.o")
        >>> unit.needs_recompile()
        False
        """
        # Never compiled
        if self.compiled_at is None:
            return True

        # Object file missing
        if not self.object_path or not self.object_path.exists():
            return True

        # Source file modified
        if self.source_path.stat().st_mtime > self.compiled_at:
            return True

        # Check header dependencies
        for header in self.dependencies:
            if header.exists() and header.stat().st_mtime > self.compiled_at:
                return True

        return False

    def get_dependency_hash(self) -> str:
        """
        Compute SHA-256 hash of the source and all dependencies.

        This method computes a cryptographic hash of the source file content
        and all header dependencies. The hash can be used for cache key
        generation to uniquely identify this compilation unit's state.

        Returns
        -------
        str
            Hexadecimal SHA-256 hash string representing the unit's content.

        Notes
        -----
        The hash includes:
        - Full content of the source file
        - Full content of each header dependency (in sorted order)
        - The path of each header (to detect moved files)

        Examples
        --------
        >>> unit = CompilationUnit(Path("main.c"), CSourceType.C_SOURCE)
        >>> hash_value = unit.get_dependency_hash()
        >>> print(len(hash_value))
        64
        """
        hasher = hashlib.sha256()

        # Hash source file content
        with open(self.source_path, "rb") as f:
            hasher.update(f.read())

        # Hash all headers in sorted order (for consistency)
        for header in sorted(self.dependencies):
            if header.exists():
                with open(header, "rb") as f:
                    hasher.update(f.read())
                # Include path to detect moved/renamed files
                hasher.update(str(header).encode())

        return hasher.hexdigest()


@dataclass
class LinkUnit:
    """
    Represents a linking operation.

    This dataclass tracks all information related to linking multiple
    object files into a final executable or shared library. It supports
    incremental linking by tracking modification times of object files.

    Parameters
    ----------
    objects : List[Path]
        List of object files to link together.
    output_path : Path
        Path where the linked output will be written.
    libraries : List[str], optional
        Additional libraries to link against. Default is empty list.
    library_paths : List[Path], optional
        Additional library search paths. Default is empty list.
    link_type : LinkType, optional
        Type of linking operation (shared library, executable, etc.).
        Default is LinkType.MODULE.
    extra_flags : List[str], optional
        Additional linker flags. Default is empty list.
    linked_at : Optional[float], optional
        Timestamp (time.time()) when last linked. Default is None.
    link_time : float, optional
        Time in seconds taken to link. Default is 0.0.

    Attributes
    ----------
    objects : List[Path]
        Object files to link.
    output_path : Path
        Output file path.
    libraries : List[str]
        Libraries to link.
    library_paths : List[Path]
        Library search paths.
    link_type : LinkType
        Type of linking.
    extra_flags : List[str]
        Extra linker flags.
    linked_at : Optional[float]
        Linking timestamp.
    link_time : float
        Linking duration in seconds.

    Examples
    --------
    >>> link_unit = LinkUnit(
    ...     objects=[Path("main.o"), Path("utils.o")],
    ...     output_path=Path("mymodule.so"),
    ...     libraries=["m", "pthread"],
    ... )
    >>> if link_unit.needs_relink():
    ...     print("Needs relinking")
    """

    objects: List[Path]
    output_path: Path
    libraries: List[str] = field(default_factory=list)
    library_paths: List[Path] = field(default_factory=list)
    link_type: LinkType = LinkType.MODULE
    extra_flags: List[str] = field(default_factory=list)
    linked_at: Optional[float] = None
    link_time: float = 0.0

    def needs_relink(self) -> bool:
        """
        Check if relinking is needed.

        Relinking is needed if:
        1. Never linked before (linked_at is None)
        2. Output file doesn't exist
        3. Any object file has been modified since last linking

        Returns
        -------
        bool
            True if relinking is needed, False otherwise.

        Examples
        --------
        >>> link_unit = LinkUnit([Path("main.o")], Path("output.so"))
        >>> link_unit.needs_relink()
        True
        >>> # After linking
        >>> link_unit.linked_at = time.time()
        >>> link_unit.needs_relink()
        False
        """
        # Never linked
        if self.linked_at is None:
            return True

        # Output file missing
        if not self.output_path.exists():
            return True

        # Check if any object file is newer
        for obj in self.objects:
            if obj.exists() and obj.stat().st_mtime > self.linked_at:
                return True

        return False


# =============================================================================
# DEPENDENCY PARSER
# =============================================================================

class DependencyParser:
    """
    C/C++ dependency parser using compiler's built-in dependency generation.

    This class extracts header dependencies from C/C++ source files using
    the compiler's -MM (GCC/Clang) or /showIncludes (MSVC) options. It
    maintains a cache of parsed dependencies to avoid redundant parsing.

    Parameters
    ----------
    compiler_backend : CompilerBackend
        Compiler backend instance used for dependency parsing.
    include_paths : Optional[List[Path]], optional
        Additional include search paths for the compiler. Default is None.
    defines : Optional[Dict[str, str]], optional
        Preprocessor definitions for the compiler. Default is None.

    Attributes
    ----------
    compiler_backend : CompilerBackend
        The compiler backend used for parsing.
    include_paths : List[Path]
        Additional include search paths.
    defines : Dict[str, str]
        Preprocessor macro definitions.
    _cache : Dict[Path, List[Path]]
        Cache of parsed dependencies (source path -> dependency paths).
    _cache_lock : threading.RLock
        Lock for thread-safe cache access.
    _visited : Set[Path]
        Set of currently visited files to detect circular includes.

    Examples
    --------
    >>> backend = detect_compiler()
    >>> parser = DependencyParser(backend)
    >>> deps = parser.parse(Path("main.cpp"))
    >>> for dep in deps:
    ...     print(f"Depends on: {dep}")
    >>> parser.clear_cache()
    """

    def __init__(
        self,
        compiler_backend: CompilerBackend,
        include_paths: Optional[List[Path]] = None,
        defines: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Initialize the dependency parser.

        Parameters
        ----------
        compiler_backend : CompilerBackend
            Compiler backend to use for parsing dependencies.
        include_paths : Optional[List[Path]], optional
            Additional include search paths. Default is None.
        defines : Optional[Dict[str, str]], optional
            Preprocessor macro definitions. Default is None.
        """
        self.compiler_backend = compiler_backend
        self.include_paths = include_paths or []
        self.defines = defines or {}
        
        # Cache for parsed dependencies
        self._cache: Dict[Path, List[Path]] = {}
        self._cache_lock = threading.RLock()
        
        # Track visited files to prevent circular dependency infinite recursion
        self._visited: Set[Path] = set()

    def parse(self, source_path: Path, force_refresh: bool = False) -> List[Path]:
        """
        Parse dependencies for a source file.

        This method extracts all header files that the given source file
        depends on using the compiler's dependency generation features.
        Results are cached to avoid redundant parsing.

        Parameters
        ----------
        source_path : Path
            Absolute path to the source file to analyze.
        force_refresh : bool, optional
            If True, bypass cache and re-parse dependencies.
            Default is False.

        Returns
        -------
        List[Path]
            List of absolute paths to all header files that the source
            file depends on (including transitive dependencies).

        Notes
        -----
        The method handles circular includes by tracking visited files
        during recursive parsing.

        Examples
        --------
        >>> parser = DependencyParser(compiler_backend)
        >>> deps = parser.parse(Path("main.cpp"))
        >>> len(deps)
        15
        >>> # Force refresh
        >>> deps = parser.parse(Path("main.cpp"), force_refresh=True)
        """
        # Check for circular includes
        if source_path in self._visited:
            return []
        
        self._visited.add(source_path)
        
        try:
            with self._cache_lock:
                if not force_refresh and source_path in self._cache:
                    return self._cache[source_path].copy()

                deps = self._parse_with_compiler(source_path)
                self._cache[source_path] = deps
                return deps.copy()
        finally:
            self._visited.discard(source_path)

    def _parse_with_compiler(self, source_path: Path) -> List[Path]:
        """
        Parse dependencies using the appropriate compiler method.

        Parameters
        ----------
        source_path : Path
            Source file path to parse.

        Returns
        -------
        List[Path]
            List of dependency header files.
        """
        if self.compiler_backend.family == CompilerFamily.MICROSOFT:
            return self._parse_msvc(source_path)
        else:
            return self._parse_gnu(source_path)

    def _parse_gnu(self, source_path: Path) -> List[Path]:
        """
        Parse dependencies using GCC/Clang -MM option.

        This method uses the -MM flag which outputs Makefile-style
        dependency information, excluding system headers.

        Parameters
        ----------
        source_path : Path
            Source file path to parse.

        Returns
        -------
        List[Path]
            List of dependency header files.
        """
        deps: List[Path] = []

        # Build command
        cmd = [str(self.compiler_backend.executable_path), "-MM", str(source_path)]

        # Add include paths
        for inc in self.include_paths:
            cmd.extend(["-I", str(inc)])

        # Add defines
        for name, value in self.defines.items():
            if value:
                cmd.append(f"-D{name}={value}")
            else:
                cmd.append(f"-D{name}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                # Parse Makefile-style output: "target: dep1 dep2 \\\n dep3"
                output = result.stdout.replace("\\\n", " ")
                if ":" in output:
                    deps_part = output.split(":", 1)[1].strip()
                    for dep in deps_part.split():
                        dep_path = Path(dep)
                        if dep_path.exists():
                            deps.append(dep_path)

                            # Recursively parse headers (transitive dependencies)
                            sub_deps = self.parse(dep_path)
                            for sub_dep in sub_deps:
                                if sub_dep not in deps:
                                    deps.append(sub_dep)

        except (subprocess.SubprocessError, OSError) as e:
            logger.debug(f"Dependency parsing failed for {source_path}: {e}")

        return deps

    def _parse_msvc(self, source_path: Path) -> List[Path]:
        """
        Parse dependencies using MSVC /showIncludes option.

        This method uses the /showIncludes flag which outputs a note
        for each included file during compilation.

        Parameters
        ----------
        source_path : Path
            Source file path to parse.

        Returns
        -------
        List[Path]
            List of dependency header files.
        """
        deps: List[Path] = []

        # Build command
        cmd = [
            str(self.compiler_backend.executable_path),
            "/c",
            "/showIncludes",
            str(source_path)
        ]

        # Add include paths
        for inc in self.include_paths:
            cmd.extend(["/I", str(inc)])

        # Add defines
        for name, value in self.defines.items():
            if value:
                cmd.append(f"/D{name}={value}")
            else:
                cmd.append(f"/D{name}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            # MSVC outputs include notes to stderr
            # Pattern: "Note: including file: path" (English)
            # Also handle localized versions
            pattern = re.compile(
                r"(?:Note|Remarque|Hinweis|Nota|メモ|참고): including file:\s*(.+)",
                re.IGNORECASE
            )

            for line in result.stderr.split("\n"):
                match = pattern.search(line)
                if match:
                    include_path = match.group(1).strip()
                    dep_path = Path(include_path)
                    if dep_path.exists():
                        deps.append(dep_path)

        except (subprocess.SubprocessError, OSError) as e:
            logger.debug(f"MSVC dependency parsing failed for {source_path}: {e}")

        return deps

    def clear_cache(self) -> None:
        """
        Clear the dependency cache.

        This method removes all cached dependency information, forcing
        re-parsing on subsequent calls to parse().
        """
        with self._cache_lock:
            self._cache.clear()


# =============================================================================
# MAIN LOADER CLASS
# =============================================================================

class CLoader(BaseLoader):
    """
    Advanced C/C++ extension module loader.

    This class provides comprehensive support for compiling and loading
    C/C++ source files as Python extension modules with features including:
    
    - Cross-platform compilation (GCC, Clang, MSVC, ICC)
    - Intelligent caching with platform-aware cache keys
    - Automatic header dependency resolution
    - Incremental compilation (only recompile changed files)
    - Parallel compilation of multiple source files
    - Hot reloading with file watching
    - Sandboxed compilation for security
    - Python C API integration
    - Support for multiple source files per module
    - Precompiled header support
    - Unity/jumbo builds support
    - Compilation database generation for tools

    Parameters
    ----------
    config : Optional[LoaderConfig], optional
        Loader configuration for caching, reloading, etc. Default is None.
    compile_config : Optional[CompilationConfig], optional
        Compilation configuration for optimization, SIMD, etc. Default is None.
    cache_manager : Optional[CacheManager], optional
        Cache manager instance. Created automatically if None. Default is None.
    compiler_backend : Optional[CompilerBackend], optional
        Compiler backend. Auto-detected if None. Default is None.
    flag_normalizer : Optional[FlagNormalizer], optional
        Flag normalizer instance. Created automatically if None. Default is None.

    Attributes
    ----------
    compile_config : CompilationConfig
        The compilation configuration.
    compiler_backend : CompilerBackend
        The selected compiler backend.
    flag_normalizer : FlagNormalizer
        Flag normalizer for cross-compiler flag translation.
    dependency_parser : DependencyParser
        Dependency parser for header analysis.
    _compilation_units : Dict[str, CompilationUnit]
        Map of source path to compilation unit.
    _link_unit_map : Dict[str, LinkUnit]
        Map of output path to link unit (renamed from _link_units to avoid
        conflict with _link_units method).
    _python_includes : List[Path]
        Detected Python include directories.
    _python_libs : List[Path]
        Detected Python library directories.
    _python_version : str
        Detected Python version string.
    _sandbox : Optional[SandboxManager]
        Sandbox manager for secure compilation.
    _watcher : Optional[Any]
        File watcher for hot reloading.
    _compile_lock : threading.RLock
        Lock for thread-safe compilation operations.
    _flag_cache : Dict[str, List[str]]
        Cache for normalized compiler flags.

    Examples
    --------
    >>> # Basic usage - single source file
    >>> loader = CLoader()
    >>> module = loader.load("my_extension.c")
    >>> result = module.my_function(42)
    >>> loader.unload("my_extension")

    >>> # Multiple source files
    >>> loader = CLoader()
    >>> module = loader.load(["main.c", "utils.c", "math.c"])
    
    >>> # Advanced configuration
    >>> config = LoaderConfig(
    ...     cache_enabled=True,
    ...     auto_reload=True,
    ...     enable_hot_reload=True
    ... )
    >>> compile_config = CompilationConfig(
    ...     optimization_preset=OptimizationPreset.SPEED,
    ...     simd_preset=SIMDPreset.AVX2,
    ...     language_standard=LanguageStandard.CPP17,
    ...     openmp=True,
    ...     lto=True
    ... )
    >>> loader = CLoader(
    ...     config=config,
    ...     compile_config=compile_config,
    ... )
    >>> module = loader.load("neural_net.cpp")
    
    >>> # Hot reloading
    >>> loader.watch("my_extension.c")
    >>> # Module automatically reloads when source changes
    
    >>> # Generate compilation database for clangd/clang-tidy
    >>> db_path = loader.generate_compilation_database(Path("build/"))
    
    >>> # Clean up
    >>> loader.close()
    """

    def __init__(
        self,
        config: Optional[LoaderConfig] = None,
        compile_config: Optional[CompilationConfig] = None,
        cache_manager: Optional[CacheManager] = None,
        compiler_backend: Optional[CompilerBackend] = None,
        flag_normalizer: Optional[FlagNormalizer] = None,
    ) -> None:
        """
        Initialize the C/C++ module loader.

        Parameters
        ----------
        config : Optional[LoaderConfig], optional
            Loader configuration. Default is None.
        compile_config : Optional[CompilationConfig], optional
            Compilation configuration. Default is None.
        cache_manager : Optional[CacheManager], optional
            Cache manager instance. Default is None.
        compiler_backend : Optional[CompilerBackend], optional
            Compiler backend. Default is None (auto-detected).
        flag_normalizer : Optional[FlagNormalizer], optional
            Flag normalizer. Default is None.

        Raises
        ------
        CompileError
            If no suitable C/C++ compiler is found on the system.
        """
        super().__init__(config=config, cache_manager=cache_manager)

        self.compile_config = compile_config or CompilationConfig()
        self.flag_normalizer = flag_normalizer or FlagNormalizer()

        # Initialize compiler
        if compiler_backend:
            self.compiler_backend = compiler_backend
        else:
            if self.compile_config.custom_compiler:
                self.compiler_backend = detect_compiler(self.compile_config.custom_compiler)
            else:
                self.compiler_backend = detect_compiler()

        if not self.compiler_backend:
            raise CompileError(
                compiler="unknown",
                message="No suitable C/C++ compiler found on the system",
                category=ErrorCategory.COMPILER_NOT_FOUND,
                severity=ErrorSeverity.FATAL,
            )

        # Set compiler info for flag normalizer
        self.flag_normalizer.mapper.set_compiler_info(self.compiler_backend.info)

        # Initialize dependency parser
        self.dependency_parser = DependencyParser(
            self.compiler_backend,
            self.compile_config.include_paths,
            self.compile_config.defines,
        )

        # Track compilation and link units
        # FIXED: Renamed from _link_units to _link_unit_map to avoid conflict
        # with the _link_units() method (dict vs function name collision)
        self._compilation_units: Dict[str, CompilationUnit] = {}
        self._link_unit_map: Dict[str, LinkUnit] = {}

        # Python environment
        self._python_includes = self._detect_python_includes()
        self._python_libs = self._detect_python_libs()
        self._python_version = get_python_version()

        # Thread safety
        self._compile_lock = threading.RLock()
        self._flag_cache: Dict[str, List[str]] = {}

        # Sandbox
        self._sandbox: Optional[SandboxManager] = None
        if self.config.sandbox_policy != SandboxPolicy.NONE:
            self._setup_sandbox()

        # Hot reload watcher
        self._watcher = None
        if self.config.enable_hot_reload:
            self._setup_watcher()

        # Log initialization
        self._trigger_event(
            LoaderEventType.STATE_CHANGED,
            "",
            data={
                "compiler": self.compiler_backend.name,
                "compiler_version": self.compiler_backend.info.version,
                "compiler_family": self.compiler_backend.family.value,
                "python_version": self._python_version,
                "platform": get_platform(),
                "architecture": get_architecture(),
            },
        )

    def _detect_python_includes(self) -> List[Path]:
        """
        Detect Python include directories for the current Python installation.

        Returns
        -------
        List[Path]
            List of absolute paths to Python include directories.

        Notes
        -----
        This method uses platform-specific utilities to locate the correct
        Python header files required for compiling extension modules.
        """
        return get_python_include_paths()

    def _detect_python_libs(self) -> List[Path]:
        """
        Detect Python library directories for the current Python installation.

        Returns
        -------
        List[Path]
            List of absolute paths to Python library directories.

        Notes
        -----
        This method uses platform-specific utilities to locate the correct
        Python library files required for linking extension modules.
        """
        return get_python_library_paths()

    def _setup_sandbox(self) -> None:
        """
        Setup compilation sandbox for secure execution.

        This method initializes the sandbox manager based on the configured
        sandbox policy and resource limits. The sandbox provides:
        - Process isolation
        - Memory and CPU time limits
        - Filesystem restrictions (based on policy)
        - Network blocking (based on policy)

        Notes
        -----
        The sandbox is only created if the policy is not SandboxPolicy.NONE.
        Resource limits are derived from loader configuration and compilation
        settings.

        FIXED: Added proper SandboxPolicy handling to avoid attribute errors
        when the policy enum doesn't have expected methods.
        """
        from ..core.enums import SandboxPolicy
        
        # Skip if sandbox is disabled
        if self.config.sandbox_policy == SandboxPolicy.NONE:
            self._sandbox = None
            return

        try:
            # FIXED: Extract the actual policy value if needed
            # Some sandbox implementations expect a string or specific enum
            policy = self.config.sandbox_policy
            
            # Create sandbox with configured policy
            self._sandbox = SandboxManager(
                policy=policy,
                allow_network=False,  # Compilation shouldn't need network
            )
            
            # Override default limits with configured values
            if self.config.timeout_load:
                self._sandbox.limits.timeout_seconds = self.config.timeout_load
            elif self.compile_config.compile_timeout:
                self._sandbox.limits.timeout_seconds = self.compile_config.compile_timeout
            
            # Set memory limit if specified in compile config
            if hasattr(self.compile_config, 'memory_limit_mb') and self.compile_config.memory_limit_mb:
                self._sandbox.limits.memory_limit_mb = self.compile_config.memory_limit_mb
            
            logger.debug(f"Sandbox initialized with policy: {policy}")
            
        except ImportError as e:
            logger.warning(f"Sandbox not available: {e}")
            self._sandbox = None
        except Exception as e:
            logger.error(f"Failed to setup sandbox: {e}")
            self._sandbox = None

    def _setup_watcher(self) -> None:
        """
        Setup file watcher for hot reloading.

        This method initializes the file watcher system that monitors
        source files for changes and triggers automatic reloading.
        """
        try:
            from ..monitors import FileWatcher
            self._watcher = FileWatcher()
            self._watcher.start()
        except ImportError:
            logger.warning("FileWatcher not available, hot reload disabled")
            self.config.enable_hot_reload = False

    def _get_normalized_flags(self, language: str = "c") -> List[str]:
        """
        Get normalized compilation flags for the current configuration.

        This method generates a complete set of compiler flags based on
        the compilation configuration, normalized for the specific compiler
        backend being used.

        Parameters
        ----------
        language : str, optional
            Language identifier ('c' or 'c++'). Default is 'c'.

        Returns
        -------
        List[str]
            List of normalized compiler flags ready to pass to the compiler.

        Notes
        -----
        The flags include:
        - Base optimization flags
        - SIMD instruction set flags
        - Warning flags
        - Language standard flags
        - Debug symbol flags
        - OpenMP flags (if enabled)
        - LTO flags (if enabled)
        - Position-independent code flags
        - Security hardening flags
        - Sanitizer flags
        - Python include paths
        - User-defined include paths and macros

        Results are cached per language and compiler family for performance.
        """
        cache_key = f"{language}_{self.compiler_backend.family.value}"

        if cache_key in self._flag_cache:
            return self._flag_cache[cache_key].copy()

        flags: List[str] = []

        # Get base build flags from normalizer
        base_flags = self.flag_normalizer.get_build_flags(
            family=self.compiler_backend.family,
            optimization=self.compile_config.get_optimization_preset(),
            simd=self.compile_config.get_simd_preset(),
            warnings=self.compile_config.get_warning_preset(),
            debug=self.compile_config.debug_symbols,
            openmp=self.compile_config.openmp,
            lto=self.compile_config.lto,
            pic=self.compile_config.position_independent,
            standard=self.compile_config.language_standard.value if self.compile_config.language_standard else None,
            language=language,
        )
        flags.extend(base_flags)

        # Add fast math if enabled
        if self.compile_config.fast_math:
            fast_math_flags = self.flag_normalizer.mapper.translate(
                ["fast_math"], self.compiler_backend.family
            )
            flags.extend(fast_math_flags)

        # Add security hardening
        if self.compile_config.security_hardening:
            sec_flags = self.flag_normalizer.get_security_flags(
                self.compiler_backend.family,
                stack_protector=True,
                control_flow_guard=is_windows(),
            )
            flags.extend(sec_flags)

        # Add sanitizers
        if self.compile_config.sanitizers:
            from ..compilers.flag_normalizer import SanitizerPreset
            for sanitizer in self.compile_config.sanitizers:
                try:
                    preset = SanitizerPreset(sanitizer)
                    sanitizer_flags = self.flag_normalizer.get_sanitizer_flags(
                        self.compiler_backend.family,
                        preset,
                    )
                    flags.extend(sanitizer_flags)
                except ValueError:
                    logger.warning(f"Unknown sanitizer: {sanitizer}")

        # Add C++ specific flags
        if language == "c++":
            if not self.compile_config.exceptions:
                if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                    flags.append("/EHsc-")
                else:
                    flags.append("-fno-exceptions")

            if not self.compile_config.rtti:
                if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                    flags.append("/GR-")
                else:
                    flags.append("-fno-rtti")

        # Add Python includes
        for inc in self._python_includes:
            if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                flags.append(f"/I{inc}")
            else:
                flags.append(f"-I{inc}")

        # Add user include paths
        for inc in self.compile_config.include_paths:
            if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                flags.append(f"/I{inc}")
            else:
                flags.append(f"-I{inc}")

        # Add user defines
        for name, value in self.compile_config.defines.items():
            if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                if value:
                    flags.append(f"/D{name}={value}")
                else:
                    flags.append(f"/D{name}")
            else:
                if value:
                    flags.append(f"-D{name}={value}")
                else:
                    flags.append(f"-D{name}")

        # Add extra logical flags
        if self.compile_config.extra_logical_flags:
            normalized_extra = self.flag_normalizer.normalize_flags(
                self.compile_config.extra_logical_flags,
                self.compiler_backend.family,
            )
            flags.extend(normalized_extra)

        # Add raw extra flags
        flags.extend(self.compile_config.extra_flags)

        # Deduplicate flags while preserving order
        seen = set()
        unique_flags = []
        for flag in flags:
            if flag not in seen:
                seen.add(flag)
                unique_flags.append(flag)

        self._flag_cache[cache_key] = unique_flags
        return unique_flags.copy()

    def _create_compilation_unit(self, source_path: Path) -> CompilationUnit:
        """
        Create a compilation unit for a source file.

        This method analyzes a source file, determines its type, and parses
        its header dependencies to create a complete CompilationUnit.

        Parameters
        ----------
        source_path : Path
            Absolute path to the source file.

        Returns
        -------
        CompilationUnit
            A fully populated compilation unit for the source file.

        Examples
        --------
        >>> unit = loader._create_compilation_unit(Path("main.cpp"))
        >>> print(unit.source_type)
        CSourceType.CPP_SOURCE
        >>> print(len(unit.dependencies))
        12
        """
        source_type = CSourceType.from_extension(source_path)

        # Parse dependencies
        deps = self.dependency_parser.parse(source_path)

        return CompilationUnit(
            source_path=source_path,
            source_type=source_type,
            dependencies=deps,
        )

    def _compile_unit(self, unit: CompilationUnit) -> CompileResult:
        """
        Compile a single compilation unit to an object file.

        Parameters
        ----------
        unit : CompilationUnit
            The compilation unit to compile.

        Returns
        -------
        CompileResult
            Result of the compilation operation.

        Raises
        ------
        CompileError
            If compilation fails (success=False in result).

        Notes
        -----
        FIXED: Added proper error handling - no longer silently ignores
        compilation failures with `pass`. Now raises CompileError.
        """
        if not unit.object_path:
            # Generate unique object path to avoid collisions
            build_dir = self._get_build_dir()
            obj_ext = ".obj" if self.compiler_backend.family == CompilerFamily.MICROSOFT else ".o"
            # FIXED: Added id(unit) to ensure unique object file names
            unit.object_path = build_dir / f"{unit.source_path.stem}_{id(unit)}{obj_ext}"

        # Ensure output directory exists
        unit.object_path.parent.mkdir(parents=True, exist_ok=True)

        # Get language
        language = unit.source_type.get_language()

        # Get normalized flags
        flags = self._get_normalized_flags(language)

        # Add unit-specific flags
        flags.extend(unit.extra_flags)

        # Add unit-specific includes
        for inc in unit.include_paths:
            if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                flags.append(f"/I{inc}")
            else:
                flags.append(f"-I{inc}")

        # Add unit-specific defines
        for name, value in unit.defines.items():
            if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                if value:
                    flags.append(f"/D{name}={value}")
                else:
                    flags.append(f"/D{name}")
            else:
                if value:
                    flags.append(f"-D{name}={value}")
                else:
                    flags.append(f"-D{name}")

        # Compile
        start_time = time.time()

        result = self.compiler_backend.compile(
            sources=[unit.source_path],
            output_path=unit.object_path,
            flags=flags,
            link_type="object",
            language=language,
        )

        unit.compile_time = time.time() - start_time
        unit.compiled_at = time.time()

        # FIXED: Proper error handling - raise exception on failure
        if not result.success:
            raise CompileError(
                compiler=self.compiler_backend.name,
                message=f"Compilation failed for {unit.source_path}",
                source_file=unit.source_path,
                stderr=result.stderr,
                return_code=result.return_code,
                category=ErrorCategory.COMPILATION_FAILED,
                severity=ErrorSeverity.ERROR,
            )

        return result

    def _link_units(
        self,
        units: List[CompilationUnit],
        output_path: Path,
        link_unit: Optional[LinkUnit] = None,
    ) -> CompileResult:
        """
        Link compiled units into a final module.

        Parameters
        ----------
        units : List[CompilationUnit]
            Compiled compilation units to link together.
        output_path : Path
            Path where the linked output should be written.
        link_unit : Optional[LinkUnit], optional
            Pre-configured link unit. Created automatically if None.

        Returns
        -------
        CompileResult
            Result of the linking operation.

        Raises
        ------
        LinkerError
            If linking fails (success=False in result).
        """
        if not units:
            return CompileResult(
                success=False,
                errors=["No compilation units to link"],
            )

        # Collect object files
        object_files = [
            u.object_path for u in units 
            if u.object_path and u.object_path.exists()
        ]

        if not object_files:
            return CompileResult(
                success=False,
                errors=["No object files found for linking"],
            )

        # Create or use link unit
        if link_unit is None:
            link_unit = LinkUnit(
                objects=object_files,
                output_path=output_path,
                libraries=self.compile_config.libraries.copy(),
                library_paths=self.compile_config.library_paths.copy(),
                link_type=self.compile_config.link_type,
            )

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Get language (use first unit's language)
        language = units[0].source_type.get_language()

        # Get flags
        flags = self._get_normalized_flags(language)

        # Add Python libraries for module linking
        if self.compile_config.link_type == LinkType.MODULE:
            # FIXED: Proper platform-specific library handling
            if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                for lib_path in self._python_libs:
                    flags.append(f"/LIBPATH:{lib_path}")
                # Python library name depends on version
                py_lib = f"python{self._python_version.replace('.', '')}.lib"
                flags.append(py_lib)
            else:
                for lib_path in self._python_libs:
                    flags.append(f"-L{lib_path}")
                flags.append(f"-lpython{self._python_version}")

        # Add user library paths
        for lib_path in link_unit.library_paths:
            if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                flags.append(f"/LIBPATH:{lib_path}")
            else:
                flags.append(f"-L{lib_path}")

        # Add user libraries
        for lib in link_unit.libraries:
            if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                flags.append(f"{lib}.lib")
            else:
                flags.append(f"-l{lib}")

        # Add extra linker flags
        flags.extend(link_unit.extra_flags)

        # Link
        start_time = time.time()

        result = self.compiler_backend.compile(
            sources=[],
            output_path=output_path,
            flags=flags,
            link_type=link_unit.link_type.value,
            extra_objects=link_unit.objects,
            language=language,
        )

        link_unit.link_time = time.time() - start_time
        link_unit.linked_at = time.time()

        if result.success:
            # FIXED: Use _link_unit_map instead of _link_units
            self._link_unit_map[str(output_path)] = link_unit
        else:
            raise LinkerError(
                compiler=self.compiler_backend.name,
                message="Linking failed",
                stderr=result.stderr,
                category=ErrorCategory.LINK_FAILED,
                severity=ErrorSeverity.ERROR,
            )

        return result

    def _get_build_dir(self) -> Path:
        """
        Get the build directory for intermediate files.

        Returns
        -------
        Path
            Absolute path to the build directory.

        Notes
        -----
        If a cache manager is available, uses its cache directory.
        Otherwise, uses a temporary directory.
        """
        if self.cache_manager:
            return self.cache_manager.cache_dir / "build"
        return Path(tempfile.gettempdir()) / "cimporter" / "build"

    def _get_output_path(
        self, 
        module_name: str, 
        cache_key: Optional[CacheKey] = None
    ) -> Path:
        """
        Get the output path for a compiled module.

        Parameters
        ----------
        module_name : str
            Name of the module.
        cache_key : Optional[CacheKey], optional
            Cache key for cached output. Used to locate cached files.

        Returns
        -------
        Path
            Absolute path where the compiled module should be written.
        """
        if cache_key and self.cache_manager:
            return self.cache_manager.backend._get_cache_path(cache_key)

        build_dir = self._get_build_dir()
        ext = get_shared_library_extension()
        if self.compile_config.link_type == LinkType.MODULE and is_windows():
            ext = ".pyd"
        return build_dir / f"{module_name}{ext}"

    def load(
        self,
        source: Union[str, Path, List[Union[str, Path]]],
        **kwargs,
    ) -> ModuleType:
        """
        Load a C/C++ module from source.

        This is the main entry point for loading C/C++ extension modules.
        It handles compilation, caching, and loading of the module.

        Parameters
        ----------
        source : Union[str, Path, List[Union[str, Path]]]
            Path to source file(s) or pre-compiled library.
            Can be a single path or a list of paths.
        **kwargs : Any
            Additional options:
            - recompile : bool - Force recompilation (default: False)
            - module_name : str - Override module name (default: source stem)
            - incremental : bool - Use incremental compilation (default: True)
            - unity_build : bool - Use unity/jumbo build (default: False)

        Returns
        -------
        ModuleType
            The loaded Python module.

        Raises
        ------
        CompileError
            If compilation fails.
        LinkerError
            If linking fails.
        ImportModuleError
            If loading the compiled module fails.

        Examples
        --------
        >>> loader = CLoader()
        >>> module = loader.load("my_extension.c")
        >>> module = loader.load(["main.cpp", "utils.cpp"])
        >>> module = loader.load("module.c", recompile=True)
        """
        self._check_state(
            LoaderState.INITIALIZED,
            LoaderState.LOADED,
            LoaderState.RELOADING,
        )

        # Normalize sources to list of absolute paths
        if isinstance(source, (str, Path)):
            sources = [Path(source).resolve()]
        else:
            sources = [Path(s).resolve() for s in source]

        recompile = kwargs.get("recompile", False)
        incremental = kwargs.get("incremental", True)
        module_name = kwargs.get("module_name")

        if not module_name:
            module_name = sources[0].stem

        # Check if already loaded
        if not recompile and self.is_loaded(module_name):
            self._trigger_event(LoaderEventType.CACHE_HIT, module_name)
            return self.get_module(module_name)

        self._set_state(LoaderState.LOADING)
        self._trigger_event(
            LoaderEventType.PRE_LOAD, 
            module_name, 
            data={"sources": [str(s) for s in sources]}
        )

        try:
            with self._compile_lock:
                # Check if it's a pre-compiled library
                if len(sources) == 1 and CSourceType.from_extension(sources[0]) == CSourceType.PYTHON_MODULE:
                    library_path = sources[0]
                    origin = ModuleOrigin.PREBUILT
                    compile_time = 0.0
                    cache_key = None

                else:
                    # Build cache key with comprehensive information
                    # FIXED: Include all relevant configuration in cache key
                    builder = CacheKeyBuilder(sources[0])
                    for src in sources[1:]:
                        builder.add_dependency(src)

                    cache_key = builder.build(
                        compiler_name=self.compiler_backend.name,
                        optimization_flags=tuple(self._get_normalized_flags()),
                        simd_level=self.compile_config.simd_level.value,
                        link_type=self.compile_config.link_type.value,
                    )

                    # Check cache
                    if not recompile and self.cache_manager:
                        cached = self.cache_manager.get(cache_key)
                        if cached and cached.exists():
                            library_path = cached
                            origin = ModuleOrigin.CACHE
                            compile_time = 0.0
                            self._trigger_event(LoaderEventType.CACHE_HIT, module_name)

                            # Load from cache
                            module = self._load_library(library_path, module_name)
                            self._register_module(
                                module_name,
                                module,
                                ModuleMetadata(
                                    name=module_name,
                                    source_path=sources[0],
                                    library_path=library_path,
                                    origin=origin,
                                    compile_time=compile_time,
                                    cache_key=cache_key,
                                    checksum=builder.compute_source_hash(),
                                ),
                            )
                            self._set_state(LoaderState.LOADED)
                            return module

                    self._trigger_event(LoaderEventType.CACHE_MISS, module_name)

                    # Create compilation units
                    units: List[CompilationUnit] = []
                    for src in sources:
                        unit = self._create_compilation_unit(src)
                        units.append(unit)
                        self._compilation_units[str(src)] = unit

                    # Compile units
                    total_compile_time = 0.0
                    for unit in units:
                        if incremental and not unit.needs_recompile():
                            logger.debug(f"Skipping {unit.source_path} (up to date)")
                            continue

                        logger.debug(f"Compiling {unit.source_path}")
                        result = self._compile_unit(unit)
                        total_compile_time += unit.compile_time

                    # Link
                    output_path = self._get_output_path(module_name, cache_key)
                    link_result = self._link_units(units, output_path)

                    library_path = output_path
                    origin = ModuleOrigin.SOURCE
                    
                    # Get link time from link unit map
                    link_unit = self._link_unit_map.get(str(output_path))
                    link_time = link_unit.link_time if link_unit else 0.0
                    compile_time = total_compile_time + link_time

                    # Store in cache
                    if self.cache_manager and cache_key:
                        self.cache_manager.put(cache_key, library_path, compile_time)

                # Load the library
                load_start = time.time()
                module = self._load_library(library_path, module_name)
                load_time = time.time() - load_start

                # Register module
                metadata = ModuleMetadata(
                    name=module_name,
                    source_path=sources[0],
                    library_path=library_path,
                    origin=origin,
                    load_time=load_time,
                    compile_time=compile_time if 'compile_time' in locals() else 0.0,
                    cache_key=cache_key if origin != ModuleOrigin.PREBUILT else None,
                    checksum=CacheKeyBuilder(sources[0]).compute_source_hash() if origin != ModuleOrigin.PREBUILT else "",
                )

                self._register_module(module_name, module, metadata)

                self._set_state(LoaderState.LOADED)
                self._trigger_event(
                    LoaderEventType.POST_LOAD, 
                    module_name, 
                    data={"load_time": load_time, "compile_time": metadata.compile_time}
                )

                return module

        except Exception as e:
            self._set_state(LoaderState.FAILED)
            self._stats["error_count"] += 1
            self._trigger_event(LoaderEventType.LOAD_ERROR, module_name, error=e)
            raise

    def _load_library(self, library_path: Path, module_name: str) -> ModuleType:
        """
        Load a compiled library as a Python module.

        Parameters
        ----------
        library_path : Path
            Path to the compiled shared library.
        module_name : str
            Name to assign to the loaded module.

        Returns
        -------
        ModuleType
            The loaded Python module.

        Raises
        ------
        ImportModuleError
            If loading the module fails.
        """
        try:
            spec = importlib.util.spec_from_file_location(module_name, str(library_path))

            if spec is None or spec.loader is None:
                raise ImportModuleError(
                    module_name=module_name,
                    library_path=library_path,
                    message="Could not create module spec",
                    category=ErrorCategory.IMPORT_FAILED,
                    severity=ErrorSeverity.ERROR,
                )

            module = importlib.util.module_from_spec(spec)

            # Add to sys.modules temporarily during loading
            sys.modules[module_name] = module

            try:
                spec.loader.exec_module(module)
            except Exception as e:
                sys.modules.pop(module_name, None)
                raise

            return module

        except Exception as e:
            raise ImportModuleError(
                module_name=module_name,
                library_path=library_path,
                message=f"Failed to load module: {e}",
                python_error=e,
                category=ErrorCategory.IMPORT_FAILED,
                severity=ErrorSeverity.ERROR,
            )

    def unload(self, module_name: str) -> bool:
        """
        Unload a previously loaded module.

        Parameters
        ----------
        module_name : str
            Name of the module to unload.

        Returns
        -------
        bool
            True if the module was unloaded successfully, False otherwise.

        Notes
        -----
        A module cannot be unloaded if other loaded modules depend on it.
        """
        with self._module_lock:
            if module_name not in self._loaded_modules:
                return False

            # Check for dependents
            dependents = self.get_dependents(module_name)
            if dependents:
                logger.warning(f"Cannot unload {module_name}: depended on by {dependents}")
                return False

            # Remove from sys.modules
            if module_name in sys.modules:
                del sys.modules[module_name]

            # Clean up compilation units
            metadata = self._module_metadata.get(module_name)
            if metadata:
                cache_key = str(metadata.source_path)
                self._compilation_units.pop(cache_key, None)

            # Unregister
            self._unregister_module(module_name)

            self._trigger_event(
                LoaderEventType.STATE_CHANGED,
                module_name,
                data={"action": "unload"},
            )

            return True

    def reload(self, module_name: str) -> ModuleType:
        """
        Reload a previously loaded module.

        Parameters
        ----------
        module_name : str
            Name of the module to reload.

        Returns
        -------
        ModuleType
            The reloaded module.

        Raises
        ------
        ImportModuleError
            If the module is not currently loaded.
        """
        metadata = self._module_metadata.get(module_name)
        if not metadata:
            raise ImportModuleError(
                module_name=module_name,
                library_path=Path("unknown"),
                message="Module not loaded",
                category=ErrorCategory.NOT_FOUND,
                severity=ErrorSeverity.ERROR,
            )

        self._set_state(LoaderState.RELOADING)
        self._trigger_event(LoaderEventType.PRE_RELOAD, module_name)
        self._stats["reload_count"] += 1

        # Invalidate dependents
        if self.config.track_dependencies:
            self.invalidate_dependents(module_name)

        # Unload current version
        self.unload(module_name)

        # Reload from source
        module = self.load(metadata.source_path, recompile=True)

        self._trigger_event(LoaderEventType.POST_RELOAD, module_name)
        self._set_state(LoaderState.LOADED)

        return module

    def is_loaded(self, module_name: str) -> bool:
        """
        Check if a module is currently loaded.

        Parameters
        ----------
        module_name : str
            Name of the module to check.

        Returns
        -------
        bool
            True if the module is loaded, False otherwise.
        """
        return module_name in self._loaded_modules

    def get_metadata(self, module_name: str) -> Optional[ModuleMetadata]:
        """
        Get metadata for a loaded module.

        Parameters
        ----------
        module_name : str
            Name of the module.

        Returns
        -------
        Optional[ModuleMetadata]
            Module metadata if the module is loaded, None otherwise.
        """
        return self._module_metadata.get(module_name)

    def watch(self, source: Union[str, Path]) -> bool:
        """
        Watch a source file for changes and auto-reload.

        Parameters
        ----------
        source : Union[str, Path]
            Source file to watch.

        Returns
        -------
        bool
            True if watching started successfully, False otherwise.

        Notes
        -----
        When the watched file changes, the module will be automatically
        reloaded if auto_reload is enabled in the configuration.
        """
        if not self._watcher:
            return False

        source_path = Path(source).resolve()
        module_name = source_path.stem

        def on_change(path: Path) -> None:
            """Callback for file changes."""
            if path == source_path:
                self._trigger_event(
                    LoaderEventType.STATE_CHANGED,
                    module_name,
                    data={"action": "file_changed", "path": str(path)},
                )
                if self.config.auto_reload:
                    logger.info(f"Auto-reloading {module_name} due to file change")
                    self.reload(module_name)

        self._watcher.add_watch(source_path, on_change)

        # Also watch header dependencies
        cache_key = str(source_path)
        if cache_key in self._compilation_units:
            for dep in self._compilation_units[cache_key].dependencies:
                self._watcher.add_watch(dep, on_change)

        return True

    def unwatch(self, source: Union[str, Path]) -> bool:
        """
        Stop watching a source file.

        Parameters
        ----------
        source : Union[str, Path]
            Source file to stop watching.

        Returns
        -------
        bool
            True if stopped successfully, False otherwise.
        """
        if not self._watcher:
            return False

        source_path = Path(source).resolve()
        self._watcher.remove_watch(source_path)
        return True

    def generate_compilation_database(
        self,
        output_dir: Path,
        sources: Optional[List[Path]] = None,
    ) -> Path:
        """
        Generate a JSON compilation database for tools (clangd, clang-tidy, etc.).

        Parameters
        ----------
        output_dir : Path
            Output directory for compile_commands.json.
        sources : Optional[List[Path]], optional
            Source files to include. If None, includes all loaded sources.

        Returns
        -------
        Path
            Path to the generated compile_commands.json file.

        Examples
        --------
        >>> loader = CLoader()
        >>> loader.load("main.cpp")
        >>> db_path = loader.generate_compilation_database(Path("build/"))
        >>> print(db_path)
        build/compile_commands.json
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        if sources is None:
            sources = [Path(k) for k in self._compilation_units.keys()]

        commands = []

        for source_path in sources:
            if str(source_path) in self._compilation_units:
                unit = self._compilation_units[str(source_path)]
            else:
                unit = self._create_compilation_unit(source_path)

            language = unit.source_type.get_language()
            flags = self._get_normalized_flags(language)

            # Build full command line
            cmd_parts = [str(self.compiler_backend.executable_path)]
            cmd_parts.extend(flags)
            cmd_parts.append(str(source_path))
            command = " ".join(cmd_parts)

            commands.append({
                "directory": str(source_path.parent.absolute()),
                "command": command,
                "file": str(source_path),
                "arguments": cmd_parts,
            })

        db_path = output_dir / "compile_commands.json"
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(commands, f, indent=2)

        logger.info(f"Generated compilation database at {db_path}")
        return db_path

    def precompile_header(
        self,
        header_path: Path,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Precompile a header file for faster compilation.

        Parameters
        ----------
        header_path : Path
            Header file to precompile.
        output_path : Optional[Path], optional
            Output path for precompiled header. Auto-generated if None.

        Returns
        -------
        Path
            Path to the generated precompiled header.

        Raises
        ------
        CompileError
            If precompilation fails.
        """
        if not output_path:
            build_dir = self._get_build_dir()
            if self.compiler_backend.family == CompilerFamily.MICROSOFT:
                output_path = build_dir / f"{header_path.stem}.pch"
            else:
                output_path = build_dir / f"{header_path.stem}.gch"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        flags = self._get_normalized_flags()

        if self.compiler_backend.family == CompilerFamily.MICROSOFT:
            flags.extend(["/Yc", f"/Fp{output_path}"])
        else:
            flags.append("-x")
            if header_path.suffix in (".hpp", ".hh", ".hxx"):
                flags.append("c++-header")
            else:
                flags.append("c-header")

        result = self.compiler_backend.compile(
            sources=[header_path],
            output_path=output_path,
            flags=flags,
            link_type="object",
        )

        if not result.success:
            raise CompileError(
                compiler=self.compiler_backend.name,
                message=f"Failed to precompile header: {header_path}",
                stderr=result.stderr,
                category=ErrorCategory.COMPILATION_FAILED,
                severity=ErrorSeverity.ERROR,
            )

        logger.info(f"Precompiled header generated at {output_path}")
        return output_path

    def close(self) -> None:
        """
        Close the loader and release all resources.

        This method stops the file watcher, cleans up the sandbox,
        clears caches, and releases all system resources.
        """
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        if self._sandbox:
            self._sandbox.cleanup()
            self._sandbox = None

        self.dependency_parser.clear_cache()
        self._compilation_units.clear()
        self._link_unit_map.clear()
        self._flag_cache.clear()

        super().close()
        logger.debug("CLoader closed")

    def __repr__(self) -> str:
        """
        Get a string representation of the loader.

        Returns
        -------
        str
            String representation including compiler info and state.
        """
        return (
            f"<CLoader "
            f"compiler={self.compiler_backend.name} "
            f"modules={len(self._loaded_modules)} "
            f"cache={'enabled' if self.config.cache_enabled else 'disabled'} "
            f"state={self.state.value}>"
        )