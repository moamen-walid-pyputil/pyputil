#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    COMPILER ABSTRACTION LAYER
    PypUtil Extension CImporter Compilers Project
==================================

Cross-platform compiler abstraction system providing unified interface
for GCC, Clang, MSVC, and ICC compilers with automatic detection,
flag normalization, and platform-specific optimizations.

This module provides a complete compiler abstraction layer with:
- Unified interface for all major C/C++ compilers
- Automatic compiler detection and capability probing
- Cross-platform flag normalization and translation
- Platform-specific optimization presets
- Comprehensive feature detection (SIMD, OpenMP, LTO, etc.)
- Sanitizer integration (Address, Thread, Undefined, Memory, Leak)
- Profile-Guided Optimization (PGO) support
- Link-Time Optimization (LTO/IPO) support
- C++20/23 module support detection

Exported Components
-------------------
Base Classes:
    - CompilerBackend: Abstract base class for all compilers
    - CompilerInfo: Compiler information and capabilities
    - CompilerFamily: Compiler family enumeration
    - CompilerFeature: Feature flags enumeration
    - CompileResult: Compilation result with metrics
    - PreprocessResult: Preprocessing result

Compiler Implementations:
    - GCCBackend: GNU Compiler Collection (GCC)
    - ClangBackend: LLVM/Clang compiler
    - MSVCBackend: Microsoft Visual C++ (MSVC)
    - ICCBackend: Intel C++ Compiler (ICC/ICX)

Detection System:
    - CompilerDetector: Base detector class
    - GCCDetector: GCC detection
    - ClangDetector: Clang detection
    - MSVCDetector: MSVC detection
    - ICCDetector: Intel compiler detection
    - CompilerRegistry: Central registry and selection
    - CompilerCandidate: Detected compiler candidate
    - CompilerPriority: Priority levels for selection

Flag Normalization:
    - FlagNormalizer: High-level flag normalization
    - FlagMapper: Flag mapping registry
    - FlagMapping: Single flag mapping across compilers
    - OptimizationPreset: Optimization level presets
    - SIMDPreset: SIMD instruction set presets
    - WarningPreset: Warning level presets
    - LanguageStandardPreset: Language standard presets
    - SanitizerPreset: Sanitizer type presets
    - LinkerPreset: Linker selection presets

Utility Functions:
    - detect_compiler: Auto-detect and create compiler backend
    - list_compilers: List all available compilers
    - normalize_flags: Normalize flags for a compiler family
    - get_optimization_flags: Get optimization flags by level
    - get_flag_normalizer: Get global flag normalizer instance
    - get_compiler_registry: Get global compiler registry instance

Examples
--------
>>> from pyputil.cutil.cimporter.compilers import *
>>> 
>>> # Auto-detect best compiler
>>> backend = detect_compiler()
>>> if backend:
...     result = backend.compile(
...         sources=[Path("main.c")],
...         output_path=Path("output.so"),
...         optimization_level=3
...     )
...     print(f"Compiled in {result.compile_time:.2f}s")
>>> 
>>> # Get specific compiler
>>> registry = get_compiler_registry()
>>> clang = registry.get_compiler("clang", min_version=(15, 0, 0))
>>> if clang:
...     backend = clang.create_backend()
...     result = backend.compile(...)
>>> 
>>> # Normalize flags across compilers
>>> flags = normalize_flags(["O3", "openmp", "avx2"], "gcc")
>>> print(flags)  # ['-O3', '-fopenmp', '-mavx2', '-mfma']
>>> 
>>> # Get optimization flags for MSVC
>>> msvc_flags = get_optimization_flags("msvc", "speed")
>>> print(msvc_flags)  # ['/O2']
>>> 
>>> # List all available compilers
>>> available = list_compilers()
>>> print(available)  # ['gcc', 'clang', 'msvc', ...]
"""

import sys as _sys
from typing import List, Optional, Union

# ============================================================================
# Base Classes and Data Structures
# ============================================================================

from .base import (
    # Abstract base
    CompilerBackend,
    
    # Enumerations
    CompilerFamily,
    CompilerFeature,
    
    # Data classes
    CompilerInfo,
    CompileResult,
    PreprocessResult,
)

# ============================================================================
# Compiler Backend Implementations
# ============================================================================

from .gcc import GCCBackend
from .clang import ClangBackend
from .msvc import MSVCBackend
from .icc import ICCBackend

# ============================================================================
# Compiler Detection System
# ============================================================================

from .detector import (
    # Base detector
    CompilerDetector,
    
    # Concrete detectors
    GCCDetector,
    ClangDetector,
    MSVCDetector,
    ICCDetector,
    
    # Registry and utilities
    CompilerRegistry,
    CompilerCandidate,
    CompilerPriority,
    PlatformType,
    
    # Convenience functions
    get_compiler_registry,
    detect_compiler,
    list_compilers,
)

# ============================================================================
# Flag Normalization System
# ============================================================================

from .flag_normalizer import (
    # Main classes
    FlagNormalizer,
    FlagMapper,
    FlagMapping,
    
    # Preset enumerations
    OptimizationPreset,
    SIMDPreset,
    WarningPreset,
    LanguageStandardPreset,
    SanitizerPreset,
    LinkerPreset,
    
    # Convenience functions
    get_flag_normalizer,
    normalize_flags,
    get_optimization_flags,
)

# ============================================================================
# Additional Exports from Detection System
# ============================================================================

# Re-export useful types from detector
CompilersDict = dict  # Type alias for compiler dictionary

# ============================================================================
# Backward Compatibility Aliases
# ============================================================================

# Aliases for backward compatibility with older versions
Compiler = CompilerBackend
CompilationResult = CompileResult
CompilerFamily_GNU = CompilerFamily.GNU
CompilerFamily_LLVM = CompilerFamily.LLVM
CompilerFamily_MSVC = CompilerFamily.MICROSOFT
CompilerFamily_Intel = CompilerFamily.INTEL

# Aliases for flag presets (shorter names)
OptLevel = OptimizationPreset
SimdLevel = SIMDPreset
WarnLevel = WarningPreset
StdLevel = LanguageStandardPreset

# ============================================================================
# Module-Level Helper Functions
# ============================================================================

def get_compiler_backend(
    name: Optional[str] = None,
    version: Optional[str] = None,
    **kwargs
) -> Optional[CompilerBackend]:
    """
    Get a compiler backend instance by name.

    This is a convenience wrapper around the compiler registry.

    Parameters
    ----------
    name : Optional[str]
        Compiler name ('gcc', 'clang', 'msvc', 'icc').
        Auto-detects best available if None.
    version : Optional[str]
        Minimum version required (e.g., '11.0.0').
    **kwargs : Any
        Additional arguments passed to backend constructor.

    Returns
    -------
    Optional[CompilerBackend]
        Compiler backend instance or None if not found.

    Examples
    --------
    >>> backend = get_compiler_backend("clang", version="15.0.0")
    >>> if backend:
    ...     print(f"Found {backend.name} {backend.info.version}")
    """
    registry = get_compiler_registry()
    
    min_version = None
    if version:
        parts = version.split(".")
        try:
            min_version = (
                int(parts[0]),
                int(parts[1]) if len(parts) > 1 else 0,
                int(parts[2]) if len(parts) > 2 else 0,
            )
        except ValueError:
            pass
    
    candidate = registry.get_compiler(name=name, min_version=min_version)
    if candidate:
        return candidate.create_backend(**kwargs)
    return None


def get_all_compilers() -> dict:
    """
    Get all detected compilers grouped by name.

    Returns
    -------
    dict
        Dictionary mapping compiler names to lists of CompilerCandidate.

    Examples
    --------
    >>> all_comps = get_all_compilers()
    >>> for name, candidates in all_comps.items():
    ...     print(f"{name}: {len(candidates)} version(s)")
    ...     for c in candidates:
    ...         print(f"  - {c.version} at {c.executable_path}")
    """
    registry = get_compiler_registry()
    return registry.get_all_compilers()


def get_best_compiler(
    min_version: Optional[str] = None,
    required_features: Optional[List[str]] = None,
) -> Optional[CompilerBackend]:
    """
    Get the best available compiler meeting requirements.

    Parameters
    ----------
    min_version : Optional[str]
        Minimum version required (e.g., '11.0.0').
    required_features : Optional[List[str]]
        List of required feature names.

    Returns
    -------
    Optional[CompilerBackend]
        Best matching compiler backend or None.

    Examples
    --------
    >>> backend = get_best_compiler(
    ...     min_version="10.0.0",
    ...     required_features=["openmp", "lto"]
    ... )
    """
    registry = get_compiler_registry()
    
    # Parse version
    min_ver_tuple = None
    if min_version:
        parts = min_version.split(".")
        try:
            min_ver_tuple = (
                int(parts[0]),
                int(parts[1]) if len(parts) > 1 else 0,
                int(parts[2]) if len(parts) > 2 else 0,
            )
        except ValueError:
            pass
    
    # Parse features
    features_flag = CompilerFeature.NONE
    feature_map = {
        "openmp": CompilerFeature.OPENMP,
        "lto": CompilerFeature.LTO,
        "pgo": CompilerFeature.PGO,
        "c11": CompilerFeature.C11,
        "c17": CompilerFeature.C17,
        "c23": CompilerFeature.C23,
        "cpp11": CompilerFeature.CPP11,
        "cpp14": CompilerFeature.CPP14,
        "cpp17": CompilerFeature.CPP17,
        "cpp20": CompilerFeature.CPP20,
        "cpp23": CompilerFeature.CPP23,
        "sse2": CompilerFeature.SIMD_SSE2,
        "sse4_2": CompilerFeature.SIMD_SSE4_2,
        "avx": CompilerFeature.SIMD_AVX,
        "avx2": CompilerFeature.SIMD_AVX2,
        "avx512": CompilerFeature.SIMD_AVX512,
        "neon": CompilerFeature.SIMD_NEON,
        "address_sanitizer": CompilerFeature.SANITIZE_ADDRESS,
        "thread_sanitizer": CompilerFeature.SANITIZE_THREAD,
        "undefined_sanitizer": CompilerFeature.SANITIZE_UNDEFINED,
        "coverage": CompilerFeature.COVERAGE,
        "coroutines": CompilerFeature.COROUTINES,
        "modules": CompilerFeature.MODULES,
        "concepts": CompilerFeature.CONCEPTS,
    }
    
    if required_features:
        for feat in required_features:
            if feat.lower() in feature_map:
                features_flag |= feature_map[feat.lower()]
    
    candidate = registry.get_best_compiler(
        min_version=min_ver_tuple,
        required_features=features_flag if features_flag else None,
    )
    
    if candidate:
        return candidate.create_backend()
    return None


def get_compiler_info(name: Optional[str] = None) -> Optional[CompilerInfo]:
    """
    Get information about a compiler without creating a full backend.

    Parameters
    ----------
    name : Optional[str]
        Compiler name. Gets best available if None.

    Returns
    -------
    Optional[CompilerInfo]
        Compiler information or None.

    Examples
    --------
    >>> info = get_compiler_info("gcc")
    >>> if info:
    ...     print(f"GCC {info.version} on {info.target_triple}")
    ...     print(f"Features: {info.features}")
    """
    backend = get_compiler_backend(name)
    if backend:
        return backend.info
    return None


def has_compiler(name: str, min_version: Optional[str] = None) -> bool:
    """
    Check if a specific compiler is available.

    Parameters
    ----------
    name : str
        Compiler name.
    min_version : Optional[str]
        Minimum version required.

    Returns
    -------
    bool
        True if compiler is available.

    Examples
    --------
    >>> if has_compiler("clang", "15.0.0"):
    ...     print("Clang 15+ is available")
    """
    return get_compiler_backend(name, version=min_version) is not None


def get_compiler_version(name: Optional[str] = None) -> Optional[str]:
    """
    Get version string of a compiler.

    Parameters
    ----------
    name : Optional[str]
        Compiler name.

    Returns
    -------
    Optional[str]
        Version string or None.

    Examples
    --------
    >>> ver = get_compiler_version("msvc")
    >>> print(f"MSVC version: {ver}")
    """
    info = get_compiler_info(name)
    if info:
        return info.version
    return None


def get_platform_default_compiler() -> str:
    """
    Get the recommended default compiler for current platform.

    Returns
    -------
    str
        Recommended compiler name.

    Examples
    --------
    >>> default = get_platform_default_compiler()
    >>> print(f"Recommended compiler for this platform: {default}")
    """
    registry = get_compiler_registry()
    prefs = registry.PLATFORM_PREFERENCES.get(registry._platform, ["clang", "gcc"])
    
    # Return first available from preferences
    for name in prefs:
        if has_compiler(name):
            return name
    
    return "unknown"


def print_compiler_report() -> None:
    """
    Print a comprehensive report of all detected compilers.

    This function outputs a detailed report of all compilers found
    on the system, including versions, paths, and features.

    Examples
    --------
    >>> print_compiler_report()
    ==================================
    COMPILER DETECTION REPORT
    ==================================
    Platform: linux (x86_64)
    
    GCC:
      [✓] 13.2.0 at /usr/bin/gcc
          Features: C11, C17, C++11, C++14, C++17, C++20, OpenMP, LTO, AVX2
      [✓] 12.3.0 at /usr/bin/gcc-12
          Features: C11, C17, C++11, C++14, C++17, C++20, OpenMP, LTO, AVX2
    
    Clang:
      [✓] 17.0.6 at /usr/bin/clang
          Features: C11, C17, C++11, C++14, C++17, C++20, OpenMP, LTO, AVX2
    ...
    """
    registry = get_compiler_registry()
    stats = registry.get_statistics()
    
    print("=" * 50)
    print("COMPILER DETECTION REPORT")
    print("=" * 50)
    print(f"Platform: {_sys.platform} ({stats.get('platform', 'unknown')})")
    print(f"Preferred: {stats.get('preferred', 'auto')}")
    print()
    
    all_comps = registry.get_all_compilers()
    
    if not all_comps:
        print("No compilers detected.")
        return
    
    for name in sorted(all_comps.keys()):
        print(f"{name.upper()}:")
        for candidate in all_comps[name]:
            status = "✓" if candidate.create_backend() else "✗"
            features = []
            
            # Extract feature names
            for feat in CompilerFeature:
                if candidate.features & feat and feat != CompilerFeature.NONE:
                    features.append(feat.name)
            
            feat_str = ", ".join(features[:8])
            if len(features) > 8:
                feat_str += f", ... ({len(features)} total)"
            
            print(f"  [{status}] {candidate.version} at {candidate.executable_path}")
            if features:
                print(f"      Features: {feat_str}")
        print()


def normalize_compiler_flags(
    flags: List[str],
    family: Optional[Union[str, CompilerFamily]] = None,
) -> List[str]:
    """
    Normalize flags for a compiler family or auto-detected compiler.

    Parameters
    ----------
    flags : List[str]
        List of logical or raw flags.
    family : Optional[Union[str, CompilerFamily]]
        Target compiler family. Auto-detects if None.

    Returns
    -------
    List[str]
        Normalized compiler flags.

    Examples
    --------
    >>> flags = normalize_compiler_flags(["O3", "openmp", "debug"])
    >>> print(flags)
    """
    if family is None:
        backend = detect_compiler()
        if backend:
            family = backend.family
        else:
            family = CompilerFamily.GNU  # Default
    
    return normalize_flags(flags, family)


# ============================================================================
# __all__ Definition
# ============================================================================

__all__ = [    
    # Base classes
    "CompilerBackend",
    "CompilerInfo",
    "CompilerFamily",
    "CompilerFeature",
    "CompileResult",
    "PreprocessResult",
    
    # Compiler implementations
    "GCCBackend",
    "ClangBackend",
    "MSVCBackend",
    "ICCBackend",
    
    # Detection system
    "CompilerDetector",
    "GCCDetector",
    "ClangDetector",
    "MSVCDetector",
    "ICCDetector",
    "CompilerRegistry",
    "CompilerCandidate",
    "CompilerPriority",
    "PlatformType",
    
    # Detection functions
    "get_compiler_registry",
    "detect_compiler",
    "list_compilers",
    "get_compiler_backend",
    "get_all_compilers",
    "get_best_compiler",
    "get_compiler_info",
    "has_compiler",
    "get_compiler_version",
    "get_platform_default_compiler",
    
    # Flag normalization
    "FlagNormalizer",
    "FlagMapper",
    "FlagMapping",
    
    # Flag presets
    "OptimizationPreset",
    "SIMDPreset",
    "WarningPreset",
    "LanguageStandardPreset",
    "SanitizerPreset",
    "LinkerPreset",
    
    # Flag functions
    "get_flag_normalizer",
    "normalize_flags",
    "get_optimization_flags",
    "normalize_compiler_flags",
    
    # Type aliases
    "OptLevel",
    "SimdLevel",
    "WarnLevel",
    "StdLevel",
    
    # Backward compatibility
    "Compiler",
    "CompilationResult",
    "CompilerFamily_GNU",
    "CompilerFamily_LLVM",
    "CompilerFamily_MSVC",
    "CompilerFamily_Intel",
]


# ============================================================================
# Module Initialization Message (if run directly)
# ============================================================================

if __name__ == "__main__":
    print(f"CImporter Compiler Abstraction Layer")
    print(f"Platform: {_sys.platform}")
    print()
    print_compiler_report()