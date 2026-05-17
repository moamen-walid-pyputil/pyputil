#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    COMPILER FLAG NORMALIZER
==================================

Cross-platform compiler flag normalization and mapping system.
Provides unified flag interface across GCC, Clang, MSVC, and ICC.
"""

import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import sys

from .base import CompilerFamily


class OptimizationPreset(Enum):
    """
    Optimization preset enumeration for cross-platform optimization levels.

    These presets provide a unified way to specify optimization levels
    that get translated to appropriate compiler-specific flags.

    Attributes
    ----------
    NONE : str
        No optimization. Fast compilation, easy debugging.
        Maps to: -O0 (GCC/Clang/ICC), /Od (MSVC)

    SIZE : str
        Optimize for minimal binary size.
        Maps to: -Os (GCC/Clang/ICC), /Os (MSVC)

    BALANCED : str
        Balanced optimization. Good performance without extreme compilation time.
        Maps to: -O2 (GCC/Clang/ICC), /O2 (MSVC)

    SPEED : str
        Maximum speed optimization. Aggressive optimizations enabled.
        Maps to: -O3 (GCC/Clang/ICC), /O2 /Ot (MSVC)

    AGGRESSIVE : str
        Aggressive optimizations including fast math and link-time optimization.
        Maps to: -O3 -ffast-math -flto (GCC/Clang), /O2 /GL /fp:fast (MSVC)

    DEBUG : str
        Debug-friendly optimization. Preserves debugging experience.
        Maps to: -Og (GCC/Clang), /Od /Zi (MSVC)
    """

    NONE = "none"
    SIZE = "size"
    BALANCED = "balanced"
    SPEED = "speed"
    AGGRESSIVE = "aggressive"
    DEBUG = "debug"


class SIMDPreset(Enum):
    """
    SIMD instruction set preset enumeration for cross-platform vectorization.

    These presets provide a unified way to specify SIMD/vectorization levels
    that get translated to appropriate compiler-specific flags.

    Attributes
    ----------
    NONE : str
        No SIMD instructions. Most portable.
        Maps to: no SIMD flags (GCC/Clang/ICC), /arch:IA32 (MSVC)

    AUTO : str
        Auto-detect best SIMD for current CPU.
        Maps to: -march=native (GCC/Clang), -xHost (ICC), /arch:AVX2 (MSVC)

    SSE2 : str
        SSE2 instructions. Baseline for x86_64.
        Maps to: -msse2 (GCC/Clang/ICC), /arch:SSE2 (MSVC)

    SSE4_2 : str
        SSE4.2 instructions. Good for string/text processing.
        Maps to: -msse4.2 (GCC/Clang/ICC), /arch:SSE2 (MSVC - no SSE4 flag)

    AVX : str
        AVX instructions. 256-bit vectors, good for floating-point.
        Maps to: -mavx (GCC/Clang), -xAVX (ICC), /arch:AVX (MSVC)

    AVX2 : str
        AVX2 instructions. Integer SIMD and FMA support.
        Maps to: -mavx2 (GCC/Clang), -xCORE-AVX2 (ICC), /arch:AVX2 (MSVC)

    AVX512 : str
        AVX-512 instructions. 512-bit vectors, highest performance.
        Maps to: -mavx512f (GCC/Clang), -xCOMMON-AVX512 (ICC), /arch:AVX512 (MSVC)

    NEON : str
        ARM NEON SIMD instructions.
        Maps to: -mfpu=neon (GCC/Clang)
    """

    NONE = "none"
    AUTO = "auto"
    SSE2 = "sse2"
    SSE4_2 = "sse4.2"
    AVX = "avx"
    AVX2 = "avx2"
    AVX512 = "avx512"
    NEON = "neon"


class WarningPreset(Enum):
    """
    Warning level preset enumeration for cross-platform diagnostics.

    Attributes
    ----------
    NONE : str
        No warnings.
        Maps to: -w (GCC/Clang/ICC), /W0 (MSVC)

    NORMAL : str
        Normal warning level. Good balance.
        Maps to: -Wall (GCC/Clang/ICC), /W3 (MSVC)

    EXTRA : str
        Extra warnings. More thorough checking.
        Maps to: -Wall -Wextra (GCC/Clang/ICC), /W4 (MSVC)

    PEDANTIC : str
        Pedantic warnings. Strict standards compliance.
        Maps to: -Wall -Wextra -pedantic (GCC/Clang/ICC), /Wall (MSVC)

    ERROR : str
        Treat warnings as errors.
        Maps to: -Werror (GCC/Clang/ICC), /WX (MSVC)

    EVERYTHING : str
        All possible warnings.
        Maps to: -Weverything (Clang), /Wall (MSVC)
    """

    NONE = "none"
    NORMAL = "normal"
    EXTRA = "extra"
    PEDANTIC = "pedantic"
    ERROR = "error"
    EVERYTHING = "everything"


class LanguageStandardPreset(Enum):
    """
    Language standard preset enumeration for cross-platform C/C++ standards.

    Attributes
    ----------
    C89 : str
        ANSI C (C89/C90).
    C99 : str
        ISO C99.
    C11 : str
        ISO C11.
    C17 : str
        ISO C17.
    C23 : str
        ISO C23 (latest).
    CPP98 : str
        ISO C++98.
    CPP11 : str
        ISO C++11.
    CPP14 : str
        ISO C++14.
    CPP17 : str
        ISO C++17.
    CPP20 : str
        ISO C++20.
    CPP23 : str
        ISO C++23 (latest).
    GNU_C11 : str
        GNU C11 with extensions.
    GNU_CPP17 : str
        GNU C++17 with extensions.
    LATEST : str
        Latest supported standard.
    """

    C89 = "c89"
    C99 = "c99"
    C11 = "c11"
    C17 = "c17"
    C23 = "c23"
    CPP98 = "c++98"
    CPP11 = "c++11"
    CPP14 = "c++14"
    CPP17 = "c++17"
    CPP20 = "c++20"
    CPP23 = "c++23"
    GNU_C11 = "gnu11"
    GNU_CPP17 = "gnu++17"
    LATEST = "latest"


class SanitizerPreset(Enum):
    """
    Sanitizer preset enumeration for cross-platform runtime instrumentation.

    Attributes
    ----------
    NONE : str
        No sanitizer.

    ADDRESS : str
        AddressSanitizer. Detects memory errors.
        Maps to: -fsanitize=address (GCC/Clang), /fsanitize=address (MSVC)

    THREAD : str
        ThreadSanitizer. Detects data races.
        Maps to: -fsanitize=thread (GCC/Clang)

    UNDEFINED : str
        UndefinedBehaviorSanitizer. Detects undefined behavior.
        Maps to: -fsanitize=undefined (GCC/Clang)

    LEAK : str
        LeakSanitizer. Detects memory leaks.
        Maps to: -fsanitize=leak (GCC/Clang)

    MEMORY : str
        MemorySanitizer. Detects uninitialized reads.
        Maps to: -fsanitize=memory (Clang)
    """

    NONE = "none"
    ADDRESS = "address"
    THREAD = "thread"
    UNDEFINED = "undefined"
    LEAK = "leak"
    MEMORY = "memory"


class LinkerPreset(Enum):
    """
    Linker preset enumeration for cross-platform linking options.

    Attributes
    ----------
    DEFAULT : str
        System default linker.

    GOLD : str
        GNU Gold linker (faster linking).
        Maps to: -fuse-ld=gold (GCC/Clang)

    LLD : str
        LLVM LLD linker (fast, cross-platform).
        Maps to: -fuse-ld=lld (GCC/Clang)

    MOLD : str
        Mold linker (fastest linking).
        Maps to: -fuse-ld=mold (GCC/Clang)

    BFD : str
        GNU BFD linker (traditional).
        Maps to: -fuse-ld=bfd (GCC/Clang)

    LINK_EXE : str
        MSVC link.exe.
        Maps to: (implicit for MSVC)
    """

    DEFAULT = "default"
    GOLD = "gold"
    LLD = "lld"
    MOLD = "mold"
    BFD = "bfd"
    LINK_EXE = "link"


@dataclass
class FlagMapping:
    """
    Represents a single flag mapping across compilers.

    Parameters
    ----------
    name : str
        Logical flag name (e.g., 'optimize_speed').
    gcc_flags : List[str]
        Flags for GCC compiler.
    clang_flags : List[str]
        Flags for Clang compiler.
    msvc_flags : List[str]
        Flags for MSVC compiler.
    icc_flags : List[str]
        Flags for Intel compiler.
    description : str
        Human-readable description of the flag.
    category : str
        Flag category (optimization, warning, debug, etc.).
    requires_version : Optional[Tuple[int, int, int]]
        Minimum compiler version required for this flag.
    mutually_exclusive : List[str]
        List of logical flag names that conflict with this one.
    platform_specific : Optional[Dict[str, List[str]]]
        Platform-specific overrides (e.g., {'linux': [...], 'windows': [...]}).

    Attributes
    ----------
    name : str
        Logical flag name.
    gcc_flags : List[str]
        GCC flags.
    clang_flags : List[str]
        Clang flags.
    msvc_flags : List[str]
        MSVC flags.
    icc_flags : List[str]
        ICC flags.
    description : str
        Description.
    category : str
        Category.
    requires_version : Optional[Tuple[int, int, int]]
        Minimum version requirement.
    mutually_exclusive : List[str]
        Conflicting flags.
    platform_specific : Dict[str, List[str]]
        Platform overrides.

    Examples
    --------
    >>> mapping = FlagMapping(
    ...     name="openmp",
    ...     gcc_flags=["-fopenmp"],
    ...     clang_flags=["-fopenmp"],
    ...     msvc_flags=["/openmp"],
    ...     icc_flags=["-qopenmp"],
    ...     description="Enable OpenMP parallelization",
    ...     category="parallel",
    ... )
    """

    name: str
    gcc_flags: List[str] = field(default_factory=list)
    clang_flags: List[str] = field(default_factory=list)
    msvc_flags: List[str] = field(default_factory=list)
    icc_flags: List[str] = field(default_factory=list)
    description: str = ""
    category: str = "general"
    requires_version: Optional[Tuple[int, int, int]] = None
    mutually_exclusive: List[str] = field(default_factory=list)
    platform_specific: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)

    def get_flags(self, family: CompilerFamily) -> List[str]:
        """
        Get flags for a specific compiler family.

        Parameters
        ----------
        family : CompilerFamily
            Compiler family.

        Returns
        -------
        List[str]
            List of compiler flags.
        """
        flags_map = {
            CompilerFamily.GNU: self.gcc_flags,
            CompilerFamily.LLVM: self.clang_flags,
            CompilerFamily.MICROSOFT: self.msvc_flags,
            CompilerFamily.INTEL: self.icc_flags,
        }

        flags = flags_map.get(family, [])
        return flags.copy()

    def get_flags_for_platform(self, family: CompilerFamily, platform_name: str) -> List[str]:
        """
        Get flags for a specific compiler family and platform.

        Parameters
        ----------
        family : CompilerFamily
            Compiler family.
        platform_name : str
            Platform name (e.g., 'linux', 'win32', 'darwin').

        Returns
        -------
        List[str]
            List of compiler flags.
        """
        base_flags = self.get_flags(family)

        if family.value in self.platform_specific:
            family_overrides = self.platform_specific[family.value]
            if platform_name in family_overrides:
                return family_overrides[platform_name]

        return base_flags


class FlagMapper:
    """
    Central flag mapping registry and translator.

    This class maintains a comprehensive mapping of logical flags
    to compiler-specific flags and provides translation services.

    Attributes
    ----------
    _mappings : Dict[str, FlagMapping]
        Registered flag mappings by logical name.
    _preset_mappings : Dict[Enum, List[str]]
        Preset to logical flag list mappings.
    _flag_aliases : Dict[str, str]
        Aliases for logical flag names.
    _compiler_info : Optional[CompilerInfo]
        Target compiler information for version checking.

    Examples
    --------
    >>> mapper = FlagMapper()
    >>> mapper.register(FlagMapping(
    ...     name="openmp",
    ...     gcc_flags=["-fopenmp"],
    ...     msvc_flags=["/openmp"],
    ... ))
    >>> 
    >>> # Translate logical flags to GCC flags
    >>> flags = mapper.translate(["openmp", "optimize_speed"], CompilerFamily.GNU)
    >>> print(flags)  # ['-fopenmp', '-O3']
    >>> 
    >>> # Use presets
    >>> mapper.register_preset(OptimizationPreset.SPEED, ["optimize_speed"])
    >>> flags = mapper.translate_preset(OptimizationPreset.SPEED, CompilerFamily.MICROSOFT)
    """

    def __init__(self):
        self._mappings: Dict[str, FlagMapping] = {}
        self._preset_mappings: Dict[Enum, List[str]] = {}
        self._flag_aliases: Dict[str, str] = {}
        self._compiler_info: Optional[Any] = None

        # Register built-in mappings
        self._register_builtin_mappings()
        self._register_builtin_presets()
        self._register_aliases()

    def _register_builtin_mappings(self) -> None:
        """
        Register built-in flag mappings for all compilers.

        This method initializes comprehensive flag mappings covering:
        - Optimization levels
        - SIMD instruction sets
        - Warning levels
        - Language standards
        - Debug information
        - Parallel programming (OpenMP)
        - Link-time optimization
        - Position-independent code
        - Sanitizers
        - Security features
        - Profiling and coverage
        """
        builtins = [
            # Optimization levels
            FlagMapping(
                name="optimize_none",
                gcc_flags=["-O0"],
                clang_flags=["-O0"],
                msvc_flags=["/Od"],
                icc_flags=["-O0"],
                description="No optimization",
                category="optimization",
            ),
            FlagMapping(
                name="optimize_size",
                gcc_flags=["-Os"],
                clang_flags=["-Os"],
                msvc_flags=["/Os"],
                icc_flags=["-Os"],
                description="Optimize for size",
                category="optimization",
            ),
            FlagMapping(
                name="optimize_speed",
                gcc_flags=["-O2"],
                clang_flags=["-O2"],
                msvc_flags=["/O2"],
                icc_flags=["-O2"],
                description="Optimize for speed",
                category="optimization",
            ),
            FlagMapping(
                name="optimize_max",
                gcc_flags=["-O3"],
                clang_flags=["-O3"],
                msvc_flags=["/Ox"],
                icc_flags=["-O3"],
                description="Maximum optimization",
                category="optimization",
            ),
            FlagMapping(
                name="optimize_debug",
                gcc_flags=["-Og"],
                clang_flags=["-Og"],
                msvc_flags=["/Od", "/Zi"],
                icc_flags=["-Og"],
                description="Debug-friendly optimization",
                category="optimization",
            ),
            FlagMapping(
                name="fast_math",
                gcc_flags=["-ffast-math"],
                clang_flags=["-ffast-math"],
                msvc_flags=["/fp:fast"],
                icc_flags=["-fp-model fast=2"],
                description="Fast math optimizations (may affect precision)",
                category="optimization",
            ),

            # SIMD flags
            FlagMapping(
                name="simd_auto",
                gcc_flags=["-march=native"],
                clang_flags=["-march=native"],
                msvc_flags=["/arch:AVX2"],
                icc_flags=["-xHost"],
                description="Auto-detect best SIMD for current CPU",
                category="simd",
            ),
            FlagMapping(
                name="simd_sse2",
                gcc_flags=["-msse2"],
                clang_flags=["-msse2"],
                msvc_flags=["/arch:SSE2"],
                icc_flags=["-msse2"],
                description="Enable SSE2 instructions",
                category="simd",
            ),
            FlagMapping(
                name="simd_sse4_2",
                gcc_flags=["-msse4.2"],
                clang_flags=["-msse4.2"],
                msvc_flags=["/arch:SSE2"],
                icc_flags=["-msse4.2"],
                description="Enable SSE4.2 instructions",
                category="simd",
            ),
            FlagMapping(
                name="simd_avx",
                gcc_flags=["-mavx"],
                clang_flags=["-mavx"],
                msvc_flags=["/arch:AVX"],
                icc_flags=["-xAVX"],
                description="Enable AVX instructions",
                category="simd",
            ),
            FlagMapping(
                name="simd_avx2",
                gcc_flags=["-mavx2", "-mfma"],
                clang_flags=["-mavx2", "-mfma"],
                msvc_flags=["/arch:AVX2"],
                icc_flags=["-xCORE-AVX2"],
                description="Enable AVX2 instructions",
                category="simd",
            ),
            FlagMapping(
                name="simd_avx512",
                gcc_flags=["-mavx512f", "-mavx512bw", "-mavx512dq", "-mavx512vl"],
                clang_flags=["-mavx512f", "-mavx512bw", "-mavx512dq", "-mavx512vl"],
                msvc_flags=["/arch:AVX512"],
                icc_flags=["-xCOMMON-AVX512"],
                description="Enable AVX-512 instructions",
                category="simd",
            ),
            FlagMapping(
                name="simd_neon",
                gcc_flags=["-mfpu=neon"],
                clang_flags=["-mfpu=neon"],
                msvc_flags=[],
                icc_flags=[],
                description="Enable ARM NEON SIMD",
                category="simd",
            ),

            # Warning levels
            FlagMapping(
                name="warnings_none",
                gcc_flags=["-w"],
                clang_flags=["-w"],
                msvc_flags=["/W0"],
                icc_flags=["-w"],
                description="Disable all warnings",
                category="warnings",
            ),
            FlagMapping(
                name="warnings_normal",
                gcc_flags=["-Wall"],
                clang_flags=["-Wall"],
                msvc_flags=["/W3"],
                icc_flags=["-Wall"],
                description="Normal warning level",
                category="warnings",
            ),
            FlagMapping(
                name="warnings_extra",
                gcc_flags=["-Wall", "-Wextra"],
                clang_flags=["-Wall", "-Wextra"],
                msvc_flags=["/W4"],
                icc_flags=["-Wall", "-Wextra"],
                description="Extra warnings",
                category="warnings",
            ),
            FlagMapping(
                name="warnings_pedantic",
                gcc_flags=["-Wall", "-Wextra", "-pedantic"],
                clang_flags=["-Wall", "-Wextra", "-pedantic"],
                msvc_flags=["/Wall"],
                icc_flags=["-Wall", "-Wextra", "-pedantic"],
                description="Pedantic warnings",
                category="warnings",
            ),
            FlagMapping(
                name="warnings_error",
                gcc_flags=["-Werror"],
                clang_flags=["-Werror"],
                msvc_flags=["/WX"],
                icc_flags=["-Werror"],
                description="Treat warnings as errors",
                category="warnings",
                mutually_exclusive=["warnings_none"],
            ),
            FlagMapping(
                name="warnings_everything",
                gcc_flags=["-Wall", "-Wextra"],
                clang_flags=["-Weverything"],
                msvc_flags=["/Wall"],
                icc_flags=["-Wall", "-Wextra"],
                description="All possible warnings",
                category="warnings",
            ),

            # Debug information
            FlagMapping(
                name="debug_symbols",
                gcc_flags=["-g"],
                clang_flags=["-g"],
                msvc_flags=["/Zi"],
                icc_flags=["-g"],
                description="Generate debug symbols",
                category="debug",
            ),
            FlagMapping(
                name="debug_full",
                gcc_flags=["-g3"],
                clang_flags=["-g3"],
                msvc_flags=["/Zi", "/DEBUG:FULL"],
                icc_flags=["-g3"],
                description="Generate full debug information",
                category="debug",
            ),
            FlagMapping(
                name="debug_line_tables",
                gcc_flags=["-g1"],
                clang_flags=["-gline-tables-only"],
                msvc_flags=["/Zi", "/DEBUG:FASTLINK"],
                icc_flags=["-g1"],
                description="Generate line tables only",
                category="debug",
            ),

            # Parallel programming
            FlagMapping(
                name="openmp",
                gcc_flags=["-fopenmp"],
                clang_flags=["-fopenmp"],
                msvc_flags=["/openmp"],
                icc_flags=["-qopenmp"],
                description="Enable OpenMP parallelization",
                category="parallel",
            ),
            FlagMapping(
                name="openmp_simd",
                gcc_flags=["-fopenmp-simd"],
                clang_flags=["-fopenmp-simd"],
                msvc_flags=["/openmp:experimental"],
                icc_flags=["-qopenmp-simd"],
                description="Enable OpenMP SIMD only",
                category="parallel",
            ),

            # Link-time optimization
            FlagMapping(
                name="lto",
                gcc_flags=["-flto"],
                clang_flags=["-flto"],
                msvc_flags=["/GL", "/LTCG"],
                icc_flags=["-ipo"],
                description="Enable link-time optimization",
                category="optimization",
            ),
            FlagMapping(
                name="lto_thin",
                gcc_flags=[],
                clang_flags=["-flto=thin"],
                msvc_flags=[],
                icc_flags=[],
                description="Enable ThinLTO (Clang only)",
                category="optimization",
            ),

            # Position-independent code
            FlagMapping(
                name="pic",
                gcc_flags=["-fPIC"],
                clang_flags=["-fPIC"],
                msvc_flags=[],
                icc_flags=["-fPIC"],
                description="Generate position-independent code",
                category="linking",
            ),
            FlagMapping(
                name="pie",
                gcc_flags=["-fPIE"],
                clang_flags=["-fPIE"],
                msvc_flags=["/DYNAMICBASE"],
                icc_flags=["-fPIE"],
                description="Generate position-independent executable",
                category="linking",
            ),

            # Sanitizers
            FlagMapping(
                name="sanitize_address",
                gcc_flags=["-fsanitize=address", "-fno-omit-frame-pointer"],
                clang_flags=["-fsanitize=address", "-fno-omit-frame-pointer"],
                msvc_flags=["/fsanitize=address"],
                icc_flags=[],
                description="Enable AddressSanitizer",
                category="sanitizer",
            ),
            FlagMapping(
                name="sanitize_thread",
                gcc_flags=["-fsanitize=thread"],
                clang_flags=["-fsanitize=thread"],
                msvc_flags=[],
                icc_flags=[],
                description="Enable ThreadSanitizer",
                category="sanitizer",
            ),
            FlagMapping(
                name="sanitize_undefined",
                gcc_flags=["-fsanitize=undefined"],
                clang_flags=["-fsanitize=undefined"],
                msvc_flags=[],
                icc_flags=[],
                description="Enable UndefinedBehaviorSanitizer",
                category="sanitizer",
            ),
            FlagMapping(
                name="sanitize_leak",
                gcc_flags=["-fsanitize=leak"],
                clang_flags=["-fsanitize=leak"],
                msvc_flags=[],
                icc_flags=[],
                description="Enable LeakSanitizer",
                category="sanitizer",
            ),
            FlagMapping(
                name="sanitize_memory",
                gcc_flags=[],
                clang_flags=["-fsanitize=memory"],
                msvc_flags=[],
                icc_flags=[],
                description="Enable MemorySanitizer (Clang only)",
                category="sanitizer",
            ),

            # Security features
            FlagMapping(
                name="security_stack_protector",
                gcc_flags=["-fstack-protector-strong"],
                clang_flags=["-fstack-protector-strong"],
                msvc_flags=["/GS"],
                icc_flags=["-fstack-protector-strong"],
                description="Enable stack protector",
                category="security",
            ),
            FlagMapping(
                name="security_control_flow_guard",
                gcc_flags=["-fcf-protection=full"],
                clang_flags=["-fcf-protection=full"],
                msvc_flags=["/guard:cf"],
                icc_flags=["-fcf-protection=full"],
                description="Enable Control Flow Guard",
                category="security",
            ),
            FlagMapping(
                name="security_spectre",
                gcc_flags=["-mindirect-branch=thunk"],
                clang_flags=["-mretpoline"],
                msvc_flags=["/Qspectre"],
                icc_flags=[],
                description="Enable Spectre mitigation",
                category="security",
            ),

            # Profiling
            FlagMapping(
                name="profile_generate",
                gcc_flags=["-fprofile-generate"],
                clang_flags=["-fprofile-instr-generate"],
                msvc_flags=["/GL", "/LTCG", "/GENPROFILE"],
                icc_flags=["-prof-gen"],
                description="Generate profile for PGO",
                category="profiling",
            ),
            FlagMapping(
                name="profile_use",
                gcc_flags=["-fprofile-use"],
                clang_flags=["-fprofile-instr-use"],
                msvc_flags=["/GL", "/LTCG", "/USEPROFILE"],
                icc_flags=["-prof-use"],
                description="Use profile for PGO",
                category="profiling",
            ),
            FlagMapping(
                name="coverage",
                gcc_flags=["--coverage"],
                clang_flags=["--coverage"],
                msvc_flags=["/PROFILE"],
                icc_flags=["--coverage"],
                description="Generate code coverage information",
                category="profiling",
            ),

            # Architecture-specific
            FlagMapping(
                name="arch_native",
                gcc_flags=["-march=native"],
                clang_flags=["-march=native"],
                msvc_flags=[],
                icc_flags=["-xHost"],
                description="Optimize for current CPU",
                category="architecture",
            ),
            FlagMapping(
                name="tune_native",
                gcc_flags=["-mtune=native"],
                clang_flags=["-mtune=native"],
                msvc_flags=[],
                icc_flags=[],
                description="Tune for current CPU",
                category="architecture",
            ),

            # Linker
            FlagMapping(
                name="linker_lld",
                gcc_flags=["-fuse-ld=lld"],
                clang_flags=["-fuse-ld=lld"],
                msvc_flags=[],
                icc_flags=["-fuse-ld=lld"],
                description="Use LLD linker",
                category="linking",
            ),
            FlagMapping(
                name="linker_gold",
                gcc_flags=["-fuse-ld=gold"],
                clang_flags=["-fuse-ld=gold"],
                msvc_flags=[],
                icc_flags=[],
                description="Use Gold linker",
                category="linking",
            ),
            FlagMapping(
                name="linker_mold",
                gcc_flags=["-fuse-ld=mold"],
                clang_flags=["-fuse-ld=mold"],
                msvc_flags=[],
                icc_flags=[],
                description="Use Mold linker",
                category="linking",
            ),

            # Standard library (C++)
            FlagMapping(
                name="stdlib_libcxx",
                gcc_flags=[],
                clang_flags=["-stdlib=libc++"],
                msvc_flags=[],
                icc_flags=["-stdlib=libc++"],
                description="Use libc++ standard library",
                category="stdlib",
            ),
            FlagMapping(
                name="stdlib_libstdcxx",
                gcc_flags=[],
                clang_flags=["-stdlib=libstdc++"],
                msvc_flags=[],
                icc_flags=[],
                description="Use libstdc++ standard library",
                category="stdlib",
            ),

            # Verbose output
            FlagMapping(
                name="verbose",
                gcc_flags=["-v"],
                clang_flags=["-v"],
                msvc_flags=["/VERBOSE"],
                icc_flags=["-v"],
                description="Verbose compilation output",
                category="diagnostic",
            ),
        ]

        for mapping in builtins:
            self.register(mapping)

        # Register language standard mappings
        self._register_language_standards()

    def _register_language_standards(self) -> None:
        """
        Register language standard flag mappings.
        """
        c_standards = {
            "std_c89": ("c89", ["-std=c89"], ["-std=c89"], ["/std:c89"], ["-std=c89"]),
            "std_c99": ("c99", ["-std=c99"], ["-std=c99"], ["/std:c99"], ["-std=c99"]),
            "std_c11": ("c11", ["-std=c11"], ["-std=c11"], ["/std:c11"], ["-std=c11"]),
            "std_c17": ("c17", ["-std=c17"], ["-std=c17"], ["/std:c17"], ["-std=c17"]),
            "std_c23": ("c23", ["-std=c2x"], ["-std=c2x"], ["/std:c17"], ["-std=c2x"]),
            "std_gnu11": ("gnu11", ["-std=gnu11"], ["-std=gnu11"], [], ["-std=gnu11"]),
            "std_gnu17": ("gnu17", ["-std=gnu17"], ["-std=gnu17"], [], ["-std=gnu17"]),
        }

        cpp_standards = {
            "std_cpp98": ("c++98", ["-std=c++98"], ["-std=c++98"], ["/std:c++98"], ["-std=c++98"]),
            "std_cpp11": ("c++11", ["-std=c++11"], ["-std=c++11"], ["/std:c++11"], ["-std=c++11"]),
            "std_cpp14": ("c++14", ["-std=c++14"], ["-std=c++14"], ["/std:c++14"], ["-std=c++14"]),
            "std_cpp17": ("c++17", ["-std=c++17"], ["-std=c++17"], ["/std:c++17"], ["-std=c++17"]),
            "std_cpp20": ("c++20", ["-std=c++20"], ["-std=c++20"], ["/std:c++20"], ["-std=c++20"]),
            "std_cpp23": ("c++23", ["-std=c++23"], ["-std=c++23"], ["/std:c++latest"], ["-std=c++23"]),
            "std_gnupp17": ("gnu++17", ["-std=gnu++17"], ["-std=gnu++17"], [], ["-std=gnu++17"]),
        }

        for name, (_, gcc, clang, msvc, icc) in {**c_standards, **cpp_standards}.items():
            self.register(FlagMapping(
                name=name,
                gcc_flags=gcc,
                clang_flags=clang,
                msvc_flags=msvc,
                icc_flags=icc,
                description=f"Use {name} language standard",
                category="standard",
            ))

    def _register_builtin_presets(self) -> None:
        """
        Register built-in preset mappings.
        """
        # Optimization presets
        self.register_preset(OptimizationPreset.NONE, ["optimize_none"])
        self.register_preset(OptimizationPreset.SIZE, ["optimize_size"])
        self.register_preset(OptimizationPreset.BALANCED, ["optimize_speed"])
        self.register_preset(OptimizationPreset.SPEED, ["optimize_max"])
        self.register_preset(OptimizationPreset.AGGRESSIVE, ["optimize_max", "fast_math", "lto"])
        self.register_preset(OptimizationPreset.DEBUG, ["optimize_debug", "debug_symbols"])

        # SIMD presets
        self.register_preset(SIMDPreset.NONE, [])
        self.register_preset(SIMDPreset.AUTO, ["simd_auto"])
        self.register_preset(SIMDPreset.SSE2, ["simd_sse2"])
        self.register_preset(SIMDPreset.SSE4_2, ["simd_sse4_2"])
        self.register_preset(SIMDPreset.AVX, ["simd_avx"])
        self.register_preset(SIMDPreset.AVX2, ["simd_avx2"])
        self.register_preset(SIMDPreset.AVX512, ["simd_avx512"])
        self.register_preset(SIMDPreset.NEON, ["simd_neon"])

        # Warning presets
        self.register_preset(WarningPreset.NONE, ["warnings_none"])
        self.register_preset(WarningPreset.NORMAL, ["warnings_normal"])
        self.register_preset(WarningPreset.EXTRA, ["warnings_extra"])
        self.register_preset(WarningPreset.PEDANTIC, ["warnings_pedantic"])
        self.register_preset(WarningPreset.ERROR, ["warnings_normal", "warnings_error"])
        self.register_preset(WarningPreset.EVERYTHING, ["warnings_everything"])

        # Language standard presets
        self.register_preset(LanguageStandardPreset.C89, ["std_c89"])
        self.register_preset(LanguageStandardPreset.C99, ["std_c99"])
        self.register_preset(LanguageStandardPreset.C11, ["std_c11"])
        self.register_preset(LanguageStandardPreset.C17, ["std_c17"])
        self.register_preset(LanguageStandardPreset.C23, ["std_c23"])
        self.register_preset(LanguageStandardPreset.CPP98, ["std_cpp98"])
        self.register_preset(LanguageStandardPreset.CPP11, ["std_cpp11"])
        self.register_preset(LanguageStandardPreset.CPP14, ["std_cpp14"])
        self.register_preset(LanguageStandardPreset.CPP17, ["std_cpp17"])
        self.register_preset(LanguageStandardPreset.CPP20, ["std_cpp20"])
        self.register_preset(LanguageStandardPreset.CPP23, ["std_cpp23"])
        self.register_preset(LanguageStandardPreset.GNU_C11, ["std_gnu11"])
        self.register_preset(LanguageStandardPreset.GNU_CPP17, ["std_gnupp17"])
        self.register_preset(LanguageStandardPreset.LATEST, ["std_c23"])

        # Sanitizer presets
        self.register_preset(SanitizerPreset.NONE, [])
        self.register_preset(SanitizerPreset.ADDRESS, ["sanitize_address"])
        self.register_preset(SanitizerPreset.THREAD, ["sanitize_thread"])
        self.register_preset(SanitizerPreset.UNDEFINED, ["sanitize_undefined"])
        self.register_preset(SanitizerPreset.LEAK, ["sanitize_leak"])
        self.register_preset(SanitizerPreset.MEMORY, ["sanitize_memory"])

        # Linker presets
        self.register_preset(LinkerPreset.DEFAULT, [])
        self.register_preset(LinkerPreset.GOLD, ["linker_gold"])
        self.register_preset(LinkerPreset.LLD, ["linker_lld"])
        self.register_preset(LinkerPreset.MOLD, ["linker_mold"])

    def _register_aliases(self) -> None:
        """
        Register flag name aliases for convenience.
        """
        aliases = {
            "O0": "optimize_none",
            "Os": "optimize_size",
            "O2": "optimize_speed",
            "O3": "optimize_max",
            "Og": "optimize_debug",
            "Ofast": "fast_math",
            "g": "debug_symbols",
            "ggdb": "debug_full",
            "fopenmp": "openmp",
            "flto": "lto",
            "fPIC": "pic",
            "fsanitize": "sanitize_address",
            "Werror": "warnings_error",
            "Wall": "warnings_normal",
            "Wextra": "warnings_extra",
            "pedantic": "warnings_pedantic",
            "march": "arch_native",
        }

        for alias, target in aliases.items():
            self._flag_aliases[alias] = target

    def register(self, mapping: FlagMapping) -> None:
        """
        Register a flag mapping.

        Parameters
        ----------
        mapping : FlagMapping
            Flag mapping to register.
        """
        self._mappings[mapping.name] = mapping

    def register_preset(self, preset: Enum, flag_names: List[str]) -> None:
        """
        Register a preset mapping.

        Parameters
        ----------
        preset : Enum
            Preset enum value.
        flag_names : List[str]
            List of logical flag names.
        """
        self._preset_mappings[preset] = flag_names

    def set_compiler_info(self, info: Any) -> None:
        """
        Set target compiler information for version checking.

        Parameters
        ----------
        info : CompilerInfo
            Compiler information.
        """
        self._compiler_info = info

    def get_mapping(self, name: str) -> Optional[FlagMapping]:
        """
        Get a flag mapping by name.

        Parameters
        ----------
        name : str
            Logical flag name.

        Returns
        -------
        Optional[FlagMapping]
            Flag mapping or None.
        """
        # Check aliases
        if name in self._flag_aliases:
            name = self._flag_aliases[name]

        return self._mappings.get(name)

    def translate(
        self,
        flag_names: List[str],
        family: CompilerFamily,
        platform_name: Optional[str] = None,
        filter_unsupported: bool = True,
    ) -> List[str]:
        """
        Translate logical flag names to compiler-specific flags.

        Parameters
        ----------
        flag_names : List[str]
            List of logical flag names.
        family : CompilerFamily
            Target compiler family.
        platform_name : Optional[str]
            Platform name for platform-specific flags.
        filter_unsupported : bool
            Whether to filter out unsupported flags.

        Returns
        -------
        List[str]
            List of compiler-specific flags.
        """
        if platform_name is None:
            platform_name = sys.platform

        translated: List[str] = []
        seen_flags: Set[str] = set()

        # Track mutually exclusive flags
        excluded: Set[str] = set()

        for name in flag_names:
            if name in excluded:
                continue

            mapping = self.get_mapping(name)
            if not mapping:
                # Pass through unknown flags
                translated.append(name)
                continue

            # Check version requirement
            if filter_unsupported and mapping.requires_version:
                if self._compiler_info:
                    if self._compiler_info.version_tuple < mapping.requires_version:
                        continue

            # Add mutually exclusive flags to excluded set
            excluded.update(mapping.mutually_exclusive)

            # Get flags for this compiler family and platform
            flags = mapping.get_flags_for_platform(family, platform_name)

            for flag in flags:
                if flag not in seen_flags:
                    seen_flags.add(flag)
                    translated.append(flag)

        return translated

    def translate_preset(
        self,
        preset: Enum,
        family: CompilerFamily,
        platform_name: Optional[str] = None,
        extra_flags: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Translate a preset to compiler-specific flags.

        Parameters
        ----------
        preset : Enum
            Preset enum value.
        family : CompilerFamily
            Target compiler family.
        platform_name : Optional[str]
            Platform name.
        extra_flags : Optional[List[str]]
            Additional logical flags to include.

        Returns
        -------
        List[str]
            List of compiler-specific flags.
        """
        flag_names = self._preset_mappings.get(preset, []).copy()

        if extra_flags:
            flag_names.extend(extra_flags)

        return self.translate(flag_names, family, platform_name)

    def get_all_mappings(self) -> Dict[str, FlagMapping]:
        """
        Get all registered mappings.

        Returns
        -------
        Dict[str, FlagMapping]
            All registered mappings.
        """
        return self._mappings.copy()

    def get_mappings_by_category(self, category: str) -> List[FlagMapping]:
        """
        Get all mappings in a specific category.

        Parameters
        ----------
        category : str
            Category name.

        Returns
        -------
        List[FlagMapping]
            List of mappings in the category.
        """
        return [m for m in self._mappings.values() if m.category == category]

    def list_categories(self) -> List[str]:
        """
        List all flag categories.

        Returns
        -------
        List[str]
            List of category names.
        """
        categories: Set[str] = set()
        for mapping in self._mappings.values():
            categories.add(mapping.category)
        return sorted(list(categories))

    def list_available_flags(self) -> List[str]:
        """
        List all available logical flag names.

        Returns
        -------
        List[str]
            List of flag names.
        """
        return sorted(list(self._mappings.keys()))

    def get_flag_description(self, name: str) -> Optional[str]:
        """
        Get description for a logical flag.

        Parameters
        ----------
        name : str
            Logical flag name.

        Returns
        -------
        Optional[str]
            Flag description or None.
        """
        mapping = self.get_mapping(name)
        if mapping:
            return mapping.description
        return None


class FlagNormalizer:
    """
    High-level flag normalization and optimization interface.

    This class provides a simplified interface for normalizing compiler
    flags across different compilers, with support for presets and
    automatic optimization selection.

    Parameters
    ----------
    mapper : Optional[FlagMapper]
        Flag mapper instance. Creates default if None.

    Attributes
    ----------
    mapper : FlagMapper
        Flag mapper instance.
    _optimization_cache : Dict[Tuple, List[str]]
        Cache for optimization combinations.

    Examples
    --------
    >>> normalizer = FlagNormalizer()
    >>> 
    >>> # Get optimization flags for GCC
    >>> flags = normalizer.get_optimization_flags(
    ...     CompilerFamily.GNU,
    ...     OptimizationPreset.SPEED,
    ...     SIMDPreset.AVX2,
    ... )
    >>> print(flags)  # ['-O3', '-mavx2', '-mfma']
    >>> 
    >>> # Get all flags for a typical release build
    >>> release_flags = normalizer.get_build_flags(
    ...     family=CompilerFamily.LLVM,
    ...     optimization=OptimizationPreset.AGGRESSIVE,
    ...     simd=SIMDPreset.AUTO,
    ...     warnings=WarningPreset.NORMAL,
    ...     debug=False,
    ...     openmp=True,
    ... )
    """

    def __init__(self, mapper: Optional[FlagMapper] = None):
        self.mapper = mapper or FlagMapper()
        self._optimization_cache: Dict[Tuple, List[str]] = {}

    def get_optimization_flags(
        self,
        family: CompilerFamily,
        optimization: OptimizationPreset = OptimizationPreset.BALANCED,
        simd: SIMDPreset = SIMDPreset.AUTO,
        lto: bool = False,
        fast_math: bool = False,
    ) -> List[str]:
        """
        Get optimization-related flags for a compiler.

        Parameters
        ----------
        family : CompilerFamily
            Target compiler family.
        optimization : OptimizationPreset
            Optimization level preset.
        simd : SIMDPreset
            SIMD instruction set preset.
        lto : bool
            Enable link-time optimization.
        fast_math : bool
            Enable fast math optimizations.

        Returns
        -------
        List[str]
            List of optimization flags.
        """
        cache_key = (family, optimization, simd, lto, fast_math)

        if cache_key in self._optimization_cache:
            return self._optimization_cache[cache_key].copy()

        flag_names = []

        # Add optimization preset
        flag_names.extend(self.mapper._preset_mappings.get(optimization, []))

        # Add SIMD preset (if not already covered by optimization)
        if simd != SIMDPreset.NONE:
            simd_flags = self.mapper._preset_mappings.get(simd, [])
            flag_names.extend(simd_flags)

        # Add LTO if requested
        if lto:
            flag_names.append("lto")

        # Add fast math if requested
        if fast_math:
            flag_names.append("fast_math")

        # Translate to compiler flags
        flags = self.mapper.translate(flag_names, family)

        # Cache result
        self._optimization_cache[cache_key] = flags.copy()

        return flags

    def get_warning_flags(
        self,
        family: CompilerFamily,
        level: WarningPreset = WarningPreset.NORMAL,
        as_error: bool = False,
    ) -> List[str]:
        """
        Get warning-related flags for a compiler.

        Parameters
        ----------
        family : CompilerFamily
            Target compiler family.
        level : WarningPreset
            Warning level preset.
        as_error : bool
            Treat warnings as errors.

        Returns
        -------
        List[str]
            List of warning flags.
        """
        flag_names = list(self.mapper._preset_mappings.get(level, []))

        if as_error and level != WarningPreset.ERROR:
            flag_names.append("warnings_error")

        return self.mapper.translate(flag_names, family)

    def get_debug_flags(
        self,
        family: CompilerFamily,
        level: str = "normal",
    ) -> List[str]:
        """
        Get debug information flags for a compiler.

        Parameters
        ----------
        family : CompilerFamily
            Target compiler family.
        level : str
            Debug level ('none', 'line_tables', 'normal', 'full').

        Returns
        -------
        List[str]
            List of debug flags.
        """
        level_map = {
            "none": [],
            "line_tables": ["debug_line_tables"],
            "normal": ["debug_symbols"],
            "full": ["debug_full"],
        }

        flag_names = level_map.get(level, ["debug_symbols"])
        return self.mapper.translate(flag_names, family)

    def get_language_standard_flags(
        self,
        family: CompilerFamily,
        standard: Union[str, LanguageStandardPreset],
        language: str = "c",
    ) -> List[str]:
        """
        Get language standard flags for a compiler.

        Parameters
        ----------
        family : CompilerFamily
            Target compiler family.
        standard : Union[str, LanguageStandardPreset]
            Language standard.
        language : str
            Language type ('c' or 'c++').

        Returns
        -------
        List[str]
            List of language standard flags.
        """
        if isinstance(standard, str):
            # Try to parse string to preset
            try:
                preset = LanguageStandardPreset(standard)
            except ValueError:
                # Try common patterns
                std_lower = standard.lower()
                if std_lower in ("c11", "c17", "c99"):
                    preset = LanguageStandardPreset(std_lower)
                elif std_lower in ("c++11", "c++14", "c++17", "c++20", "c++23"):
                    preset = LanguageStandardPreset(std_lower)
                else:
                    return [standard]  # Pass through
        else:
            preset = standard

        flag_names = self.mapper._preset_mappings.get(preset, [])
        return self.mapper.translate(flag_names, family)

    def get_sanitizer_flags(
        self,
        family: CompilerFamily,
        sanitizers: Union[SanitizerPreset, List[SanitizerPreset]],
    ) -> List[str]:
        """
        Get sanitizer flags for a compiler.

        Parameters
        ----------
        family : CompilerFamily
            Target compiler family.
        sanitizers : Union[SanitizerPreset, List[SanitizerPreset]]
            Sanitizer preset(s) to enable.

        Returns
        -------
        List[str]
            List of sanitizer flags.
        """
        if not isinstance(sanitizers, list):
            sanitizers = [sanitizers]

        flag_names: List[str] = []
        for sanitizer in sanitizers:
            if sanitizer != SanitizerPreset.NONE:
                flag_names.extend(self.mapper._preset_mappings.get(sanitizer, []))

        return self.mapper.translate(flag_names, family)

    def get_security_flags(
        self,
        family: CompilerFamily,
        stack_protector: bool = True,
        control_flow_guard: bool = False,
        spectre: bool = False,
    ) -> List[str]:
        """
        Get security-related flags for a compiler.

        Parameters
        ----------
        family : CompilerFamily
            Target compiler family.
        stack_protector : bool
            Enable stack protector.
        control_flow_guard : bool
            Enable Control Flow Guard.
        spectre : bool
            Enable Spectre mitigation.

        Returns
        -------
        List[str]
            List of security flags.
        """
        flag_names: List[str] = []

        if stack_protector:
            flag_names.append("security_stack_protector")
        if control_flow_guard:
            flag_names.append("security_control_flow_guard")
        if spectre:
            flag_names.append("security_spectre")

        return self.mapper.translate(flag_names, family)

    def get_build_flags(
        self,
        family: CompilerFamily,
        optimization: OptimizationPreset = OptimizationPreset.BALANCED,
        simd: SIMDPreset = SIMDPreset.AUTO,
        warnings: WarningPreset = WarningPreset.NORMAL,
        debug: bool = False,
        openmp: bool = False,
        lto: bool = False,
        pic: bool = True,
        standard: Optional[Union[str, LanguageStandardPreset]] = None,
        language: str = "c",
    ) -> List[str]:
        """
        Get comprehensive build flags for a compiler.

        Parameters
        ----------
        family : CompilerFamily
            Target compiler family.
        optimization : OptimizationPreset
            Optimization level.
        simd : SIMDPreset
            SIMD instruction set.
        warnings : WarningPreset
            Warning level.
        debug : bool
            Include debug symbols.
        openmp : bool
            Enable OpenMP.
        lto : bool
            Enable link-time optimization.
        pic : bool
            Generate position-independent code.
        standard : Optional[Union[str, LanguageStandardPreset]]
            Language standard.
        language : str
            Language type ('c' or 'c++').

        Returns
        -------
        List[str]
            List of all build flags.
        """
        all_flags: List[str] = []

        # Optimization flags
        all_flags.extend(self.get_optimization_flags(
            family, optimization, simd, lto
        ))

        # Warning flags
        all_flags.extend(self.get_warning_flags(family, warnings))

        # Debug flags
        if debug:
            all_flags.extend(self.get_debug_flags(family, "normal"))

        # OpenMP
        if openmp:
            openmp_flags = self.mapper.translate(["openmp"], family)
            all_flags.extend(openmp_flags)

        # Position-independent code
        if pic:
            pic_flags = self.mapper.translate(["pic"], family)
            all_flags.extend(pic_flags)

        # Language standard
        if standard:
            all_flags.extend(self.get_language_standard_flags(family, standard, language))

        return all_flags

    def normalize_flags(
        self,
        flags: List[str],
        family: CompilerFamily,
    ) -> List[str]:
        """
        Normalize a list of mixed logical and compiler flags.

        Parameters
        ----------
        flags : List[str]
            List of flags (can be logical names or raw compiler flags).
        family : CompilerFamily
            Target compiler family.

        Returns
        -------
        List[str]
            Normalized compiler-specific flags.
        """
        normalized: List[str] = []
        logical_names: List[str] = []

        for flag in flags:
            # Check if it's a logical flag
            if self.mapper.get_mapping(flag) or flag in self.mapper._flag_aliases:
                logical_names.append(flag)
            else:
                # Pass through raw flags
                normalized.append(flag)

        # Translate logical flags
        translated = self.mapper.translate(logical_names, family)
        normalized.extend(translated)

        return normalized

    def get_flag_info(self, flag_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a logical flag.

        Parameters
        ----------
        flag_name : str
            Logical flag name.

        Returns
        -------
        Optional[Dict[str, Any]]
            Flag information dictionary or None.
        """
        mapping = self.mapper.get_mapping(flag_name)
        if not mapping:
            return None

        return {
            "name": mapping.name,
            "description": mapping.description,
            "category": mapping.category,
            "gcc_flags": mapping.gcc_flags,
            "clang_flags": mapping.clang_flags,
            "msvc_flags": mapping.msvc_flags,
            "icc_flags": mapping.icc_flags,
            "mutually_exclusive": mapping.mutually_exclusive,
            "requires_version": mapping.requires_version,
        }

    def list_available_optimizations(self) -> List[str]:
        """
        List all available optimization presets.

        Returns
        -------
        List[str]
            List of optimization preset names.
        """
        return [p.value for p in OptimizationPreset]

    def list_available_simd_levels(self) -> List[str]:
        """
        List all available SIMD presets.

        Returns
        -------
        List[str]
            List of SIMD preset names.
        """
        return [p.value for p in SIMDPreset]

    def list_available_warning_levels(self) -> List[str]:
        """
        List all available warning presets.

        Returns
        -------
        List[str]
            List of warning preset names.
        """
        return [p.value for p in WarningPreset]

    def list_available_standards(self) -> List[str]:
        """
        List all available language standard presets.

        Returns
        -------
        List[str]
            List of language standard preset names.
        """
        return [p.value for p in LanguageStandardPreset]

    def clear_cache(self) -> None:
        """
        Clear internal caches.
        """
        self._optimization_cache.clear()


# Global flag normalizer instance
_global_normalizer: Optional[FlagNormalizer] = None


def get_flag_normalizer() -> FlagNormalizer:
    """
    Get the global flag normalizer instance.

    Returns
    -------
    FlagNormalizer
        Global normalizer instance.
    """
    global _global_normalizer
    if _global_normalizer is None:
        _global_normalizer = FlagNormalizer()
    return _global_normalizer


def normalize_flags(
    flags: List[str],
    family: Union[str, CompilerFamily],
) -> List[str]:
    """
    Convenience function to normalize compiler flags.

    Parameters
    ----------
    flags : List[str]
        List of logical or raw flags.
    family : Union[str, CompilerFamily]
        Target compiler family.

    Returns
    -------
    List[str]
        Normalized compiler flags.
    """
    if isinstance(family, str):
        family_map = {
            "gcc": CompilerFamily.GNU,
            "gnu": CompilerFamily.GNU,
            "clang": CompilerFamily.LLVM,
            "llvm": CompilerFamily.LLVM,
            "msvc": CompilerFamily.MICROSOFT,
            "microsoft": CompilerFamily.MICROSOFT,
            "cl": CompilerFamily.MICROSOFT,
            "icc": CompilerFamily.INTEL,
            "intel": CompilerFamily.INTEL,
        }
        family = family_map.get(family.lower(), CompilerFamily.OTHER)

    return get_flag_normalizer().normalize_flags(flags, family)


def get_optimization_flags(
    family: Union[str, CompilerFamily],
    level: str = "balanced",
) -> List[str]:
    """
    Convenience function to get optimization flags.

    Parameters
    ----------
    family : Union[str, CompilerFamily]
        Target compiler family.
    level : str
        Optimization level ('none', 'size', 'balanced', 'speed', 'aggressive').

    Returns
    -------
    List[str]
        Optimization flags.
    """
    if isinstance(family, str):
        family_map = {
            "gcc": CompilerFamily.GNU,
            "clang": CompilerFamily.LLVM,
            "msvc": CompilerFamily.MICROSOFT,
            "icc": CompilerFamily.INTEL,
        }
        family = family_map.get(family.lower(), CompilerFamily.OTHER)

    level_map = {
        "none": OptimizationPreset.NONE,
        "size": OptimizationPreset.SIZE,
        "balanced": OptimizationPreset.BALANCED,
        "speed": OptimizationPreset.SPEED,
        "aggressive": OptimizationPreset.AGGRESSIVE,
        "debug": OptimizationPreset.DEBUG,
    }

    preset = level_map.get(level.lower(), OptimizationPreset.BALANCED)

    return get_flag_normalizer().get_optimization_flags(family, preset)