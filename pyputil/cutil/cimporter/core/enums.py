#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    CORE ENUMERATION TYPES
==================================

Cross-platform enumeration types for consistent state representation
across different compilers, platforms, and optimization levels.
"""

from enum import Enum, IntEnum, auto
from typing import Dict, Set, Optional


class OptimizationLevel(Enum):
    """
    Optimization level enumeration for cross-platform flag mapping.

    This enum provides a platform-agnostic way to specify optimization
    levels that get translated to compiler-specific flags.

    Attributes
    ----------
    NONE : str
        No optimization (-O0 / /Od). Fastest compilation, best for debugging.
    BASIC : str
        Basic optimization (-O1 / /O1). Good balance of speed and compilation time.
    STANDARD : str
        Standard optimization (-O2 / /O2). Recommended for most use cases.
    MAX : str
        Maximum optimization (-O3 / /Ox). Aggressive optimization.
    SIZE : str
        Optimize for binary size (-Os / /O1). Smaller output, may be slower.

    Examples
    --------
    >>> level = OptimizationLevel.MAX
    >>> flag_map = {
    ...     OptimizationLevel.NONE: "-O0",
    ...     OptimizationLevel.MAX: "-O3"
    ... }
    """

    NONE = "none"
    BASIC = "basic"
    STANDARD = "standard"
    MAX = "max"
    SIZE = "size"

    def get_compile_time_impact(self) -> str:
        """
        Get description of compilation time impact.

        Returns
        -------
        str
            Human-readable description of compilation time impact.
        """
        impacts = {
            self.NONE: "Minimal compilation time",
            self.BASIC: "Slightly increased compilation time",
            self.STANDARD: "Moderate compilation time increase",
            self.MAX: "Significant compilation time increase",
            self.SIZE: "Moderate compilation time increase",
        }
        return impacts.get(self, "Unknown impact")

    def get_runtime_impact(self) -> str:
        """
        Get description of runtime performance impact.

        Returns
        -------
        str
            Human-readable description of runtime performance impact.
        """
        impacts = {
            self.NONE: "No optimization, suitable for debugging",
            self.BASIC: "Basic speed improvements",
            self.STANDARD: "Good performance for most applications",
            self.MAX: "Maximum performance, may increase binary size",
            self.SIZE: "Optimized for smaller binary size",
        }
        return impacts.get(self, "Unknown impact")


class SIMDLevel(Enum):
    """
    SIMD instruction set levels for cross-platform mapping.

    This enum provides a platform-agnostic way to specify SIMD/vectorization
    instruction sets that get translated to compiler-specific flags.

    Attributes
    ----------
    NONE : str
        No SIMD instructions. Portable but slower.
    SSE2 : str
        SSE2 instructions (x86_64 baseline).
    SSE3 : str
        SSE3 instructions (supplemental SSE3).
    SSSE3 : str
        SSSE3 instructions.
    SSE4_1 : str
        SSE4.1 instructions.
    SSE4_2 : str
        SSE4.2 instructions.
    AVX : str
        AVX (Advanced Vector Extensions) 128-bit vectors.
    AVX2 : str
        AVX2 256-bit vectors with FMA support.
    AVX512 : str
        AVX-512 512-bit vectors.
    NEON : str
        ARM NEON SIMD instructions.
    SVE : str
        ARM SVE (Scalable Vector Extension).
    ALTIVEC : str
        PowerPC AltiVec/VMX instructions.
    VSX : str
        PowerPC VSX (Vector-Scalar Extension).

    Examples
    --------
    >>> simd = SIMDLevel.AVX2
    >>> if simd.is_supported_on_current_platform():
    ...     flags = simd.get_compiler_flags("gcc")
    """

    NONE = "none"
    SSE2 = "sse2"
    SSE3 = "sse3"
    SSSE3 = "ssse3"
    SSE4_1 = "sse4.1"
    SSE4_2 = "sse4.2"
    AVX = "avx"
    AVX2 = "avx2"
    AVX512 = "avx512"
    NEON = "neon"
    SVE = "sve"
    ALTIVEC = "altivec"
    VSX = "vsx"

    def is_x86(self) -> bool:
        """
        Check if this SIMD level is for x86/x86_64 architecture.

        Returns
        -------
        bool
            True if this is an x86 SIMD level.
        """
        return self in {
            self.SSE2,
            self.SSE3,
            self.SSSE3,
            self.SSE4_1,
            self.SSE4_2,
            self.AVX,
            self.AVX2,
            self.AVX512,
        }

    def is_arm(self) -> bool:
        """
        Check if this SIMD level is for ARM architecture.

        Returns
        -------
        bool
            True if this is an ARM SIMD level.
        """
        return self in {self.NEON, self.SVE}

    def is_powerpc(self) -> bool:
        """
        Check if this SIMD level is for PowerPC architecture.

        Returns
        -------
        bool
            True if this is a PowerPC SIMD level.
        """
        return self in {self.ALTIVEC, self.VSX}

    def get_minimum_cpu_features(self) -> Set[str]:
        """
        Get required CPU feature flags for this SIMD level.

        Returns
        -------
        Set[str]
            Set of CPU feature names required.
        """
        features: Dict["SIMDLevel", Set[str]] = {
            self.NONE: set(),
            self.SSE2: {"sse2"},
            self.SSE3: {"sse2", "sse3"},
            self.SSSE3: {"sse2", "ssse3"},
            self.SSE4_1: {"sse2", "sse4.1"},
            self.SSE4_2: {"sse2", "sse4.2"},
            self.AVX: {"avx"},
            self.AVX2: {"avx2"},
            self.AVX512: {"avx512f"},
            self.NEON: {"neon"},
            self.SVE: {"sve"},
            self.ALTIVEC: {"altivec"},
            self.VSX: {"vsx"},
        }
        return features.get(self, set())

    def get_vector_width(self) -> int:
        """
        Get the vector register width in bits.

        Returns
        -------
        int
            Vector width in bits.
        """
        widths = {
            self.NONE: 0,
            self.SSE2: 128,
            self.SSE3: 128,
            self.SSSE3: 128,
            self.SSE4_1: 128,
            self.SSE4_2: 128,
            self.AVX: 256,
            self.AVX2: 256,
            self.AVX512: 512,
            self.NEON: 128,
            self.SVE: 0,  # Variable
            self.ALTIVEC: 128,
            self.VSX: 128,
        }
        return widths.get(self, 0)


class CompilerFamily(Enum):
    """
    Compiler family enumeration for high-level categorization.

    Attributes
    ----------
    GNU : str
        GCC and GNU-compatible compilers.
    LLVM : str
        Clang and LLVM-based compilers.
    MICROSOFT : str
        MSVC (Microsoft Visual C++).
    INTEL : str
        Intel C++ Compiler (ICC, ICX).
    OTHER : str
        Other/unknown compiler families.
    """

    GNU = "gnu"
    LLVM = "llvm"
    MICROSOFT = "microsoft"
    INTEL = "intel"
    OTHER = "other"

    def get_default_extensions(self) -> Dict[str, str]:
        """
        Get default file extensions for this compiler family.

        Returns
        -------
        Dict[str, str]
            Mapping of file types to extensions.
        """
        if self == self.MICROSOFT:
            return {
                "object": ".obj",
                "shared_library": ".dll",
                "static_library": ".lib",
                "executable": ".exe",
            }
        else:
            return {
                "object": ".o",
                "shared_library": ".so",
                "static_library": ".a",
                "executable": "",
            }

    def get_warning_flag_prefix(self) -> str:
        """
        Get the warning flag prefix for this compiler family.

        Returns
        -------
        str
            Warning flag prefix (e.g., '-W' for GNU, '/w' for MSVC).
        """
        if self == self.MICROSOFT:
            return "/w"
        else:
            return "-W"

    def get_define_flag(self) -> str:
        """
        Get the preprocessor define flag.

        Returns
        -------
        str
            Define flag (e.g., '-D' for GNU, '/D' for MSVC).
        """
        if self == self.MICROSOFT:
            return "/D"
        else:
            return "-D"

    def get_include_flag(self) -> str:
        """
        Get the include path flag.

        Returns
        -------
        str
            Include flag (e.g., '-I' for GNU, '/I' for MSVC).
        """
        if self == self.MICROSOFT:
            return "/I"
        else:
            return "-I"

    def get_library_flag(self) -> str:
        """
        Get the library linking flag.

        Returns
        -------
        str
            Library flag (e.g., '-l' for GNU, '.lib' for MSVC).
        """
        if self == self.MICROSOFT:
            return ""
        else:
            return "-l"

    def get_library_path_flag(self) -> str:
        """
        Get the library search path flag.

        Returns
        -------
        str
            Library path flag (e.g., '-L' for GNU, '/LIBPATH:' for MSVC).
        """
        if self == self.MICROSOFT:
            return "/LIBPATH:"
        else:
            return "-L"

    def get_output_flag(self) -> str:
        """
        Get the output file flag.

        Returns
        -------
        str
            Output flag (e.g., '-o' for GNU, '/Fe' for MSVC).
        """
        if self == self.MICROSOFT:
            return "/Fe"
        else:
            return "-o"

    def get_shared_flag(self) -> str:
        """
        Get the shared library flag.

        Returns
        -------
        str
            Shared library flag (e.g., '-shared' for GNU, '/LD' for MSVC).
        """
        if self == self.MICROSOFT:
            return "/LD"
        else:
            return "-shared"

    def get_pic_flag(self) -> str:
        """
        Get the position-independent code flag.

        Returns
        -------
        str
            PIC flag (e.g., '-fPIC' for GNU, '' for MSVC).
        """
        if self == self.MICROSOFT:
            return ""  # MSVC doesn't need PIC
        else:
            return "-fPIC"

    def get_optimization_flag(self, level: "OptimizationLevel") -> str:
        """
        Get optimization flag for a given level.

        Parameters
        ----------
        level : OptimizationLevel
            Optimization level.

        Returns
        -------
        str
            Compiler flag for the optimization level.
        """
        if self == self.MICROSOFT:
            flags = {
                OptimizationLevel.NONE: "/Od",
                OptimizationLevel.BASIC: "/O1",
                OptimizationLevel.STANDARD: "/O2",
                OptimizationLevel.MAX: "/Ox",
                OptimizationLevel.SIZE: "/O1",
            }
        else:
            flags = {
                OptimizationLevel.NONE: "-O0",
                OptimizationLevel.BASIC: "-O1",
                OptimizationLevel.STANDARD: "-O2",
                OptimizationLevel.MAX: "-O3",
                OptimizationLevel.SIZE: "-Os",
            }
        return flags.get(level, "-O2")


class BuildMode(Enum):
    """
    Build mode enumeration for different compilation strategies.

    Attributes
    ----------
    DEBUG : str
        Debug build with symbols and no optimization.
    RELEASE : str
        Release build with full optimization.
    RELWITHDEBINFO : str
        Release build with debug symbols.
    MINSIZEREL : str
        Release build optimized for minimal size.
    PROFILE : str
        Build with profiling instrumentation.
    COVERAGE : str
        Build with code coverage instrumentation.
    SANITIZE : str
        Build with sanitizers (ASAN, UBSAN, TSAN).
    """

    DEBUG = "debug"
    RELEASE = "release"
    RELWITHDEBINFO = "relwithdebinfo"
    MINSIZEREL = "minsizerel"
    PROFILE = "profile"
    COVERAGE = "coverage"
    SANITIZE = "sanitize"

    def get_optimization_level(self) -> "OptimizationLevel":
        """
        Get the optimization level for this build mode.

        Returns
        -------
        OptimizationLevel
            Corresponding optimization level.
        """
        levels = {
            self.DEBUG: OptimizationLevel.NONE,
            self.RELEASE: OptimizationLevel.MAX,
            self.RELWITHDEBINFO: OptimizationLevel.STANDARD,
            self.MINSIZEREL: OptimizationLevel.SIZE,
            self.PROFILE: OptimizationLevel.STANDARD,
            self.COVERAGE: OptimizationLevel.NONE,
            self.SANITIZE: OptimizationLevel.BASIC,
        }
        return levels.get(self, OptimizationLevel.STANDARD)

    def get_debug_symbols(self) -> bool:
        """
        Check if debug symbols should be included.

        Returns
        -------
        bool
            True if debug symbols should be generated.
        """
        return self in {self.DEBUG, self.RELWITHDEBINFO, self.PROFILE}

    def get_assertions_enabled(self) -> bool:
        """
        Check if assertions should be enabled.

        Returns
        -------
        bool
            True if assertions should be enabled.
        """
        return self in {self.DEBUG, self.SANITIZE}


class CacheStrategy(Enum):
    """
    Cache strategy enumeration for different caching behaviors.

    Attributes
    ----------
    AGGRESSIVE : str
        Cache everything, minimal cache invalidation.
    NORMAL : str
        Standard caching with content-based invalidation.
    CONSERVATIVE : str
        Frequent validation, minimal caching.
    NONE : str
        No caching, always recompile.
    INCREMENTAL : str
        Incremental compilation with dependency tracking.
    DISTRIBUTED : str
        Distributed cache shared across machines.
    """

    AGGRESSIVE = "aggressive"
    NORMAL = "normal"
    CONSERVATIVE = "conservative"
    NONE = "none"
    INCREMENTAL = "incremental"
    DISTRIBUTED = "distributed"

    def should_validate_cache(self) -> bool:
        """
        Check if cache should be validated before use.

        Returns
        -------
        bool
            True if cache validation is required.
        """
        return self in {self.CONSERVATIVE, self.NORMAL}

    def should_store_intermediates(self) -> bool:
        """
        Check if intermediate files should be cached.

        Returns
        -------
        bool
            True if intermediate files should be stored.
        """
        return self in {self.AGGRESSIVE, self.INCREMENTAL, self.DISTRIBUTED}

    def get_max_cache_age_days(self) -> Optional[int]:
        """
        Get maximum cache age in days before invalidation.

        Returns
        -------
        Optional[int]
            Maximum age in days, or None for unlimited.
        """
        ages = {
            self.AGGRESSIVE: None,
            self.NORMAL: 30,
            self.CONSERVATIVE: 7,
            self.NONE: 0,
            self.INCREMENTAL: None,
            self.DISTRIBUTED: None,
        }
        return ages.get(self, 30)


class ParallelStrategy(Enum):
    """
    Parallel compilation strategy enumeration.

    Attributes
    ----------
    NONE : str
        No parallelism, sequential compilation.
    THREADS : str
        Use thread-based parallelism (ThreadPoolExecutor).
    PROCESSES : str
        Use process-based parallelism (ProcessPoolExecutor).
    AUTO : str
        Automatically choose best strategy based on platform.
    DISTRIBUTED : str
        Distributed compilation across network.
    """

    NONE = "none"
    THREADS = "threads"
    PROCESSES = "processes"
    AUTO = "auto"
    DISTRIBUTED = "distributed"

    def get_executor_class(self):
        """
        Get the appropriate executor class for this strategy.

        Returns
        -------
        Type
            Executor class (ThreadPoolExecutor or ProcessPoolExecutor).
        """
        from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

        if self == self.THREADS:
            return ThreadPoolExecutor
        elif self == self.PROCESSES:
            return ProcessPoolExecutor
        elif self == self.AUTO:
            # Use processes on Windows (better isolation), threads elsewhere
            import sys
            return ProcessPoolExecutor if sys.platform == "win32" else ThreadPoolExecutor
        else:
            return ThreadPoolExecutor

    def get_worker_count(self) -> int:
        """
        Get recommended number of parallel workers.

        Returns
        -------
        int
            Number of worker threads/processes.
        """
        import os

        cpu_count = os.cpu_count() or 4

        if self == self.NONE:
            return 1
        elif self == self.PROCESSES:
            return max(1, cpu_count - 1)  # Leave one core free
        elif self == self.THREADS:
            return cpu_count
        elif self == self.AUTO:
            return max(1, cpu_count - 1)
        else:
            return cpu_count


class LanguageStandard(Enum):
    """
    Programming language standard enumeration.

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
        ISO C23 (upcoming).
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
        ISO C++23.
    GNU89 : str
        GNU C89 with extensions.
    GNU99 : str
        GNU C99 with extensions.
    GNU11 : str
        GNU C11 with extensions.
    GNU17 : str
        GNU C17 with extensions.
    GNUPP98 : str
        GNU C++98 with extensions.
    GNUPP11 : str
        GNU C++11 with extensions.
    GNUPP14 : str
        GNU C++14 with extensions.
    GNUPP17 : str
        GNU C++17 with extensions.
    GNUPP20 : str
        GNU C++20 with extensions.
    """

    # C standards
    C89 = "c89"
    C99 = "c99"
    C11 = "c11"
    C17 = "c17"
    C23 = "c23"

    # C++ standards
    CPP98 = "c++98"
    CPP11 = "c++11"
    CPP14 = "c++14"
    CPP17 = "c++17"
    CPP20 = "c++20"
    CPP23 = "c++23"

    # GNU C extensions
    GNU89 = "gnu89"
    GNU99 = "gnu99"
    GNU11 = "gnu11"
    GNU17 = "gnu17"

    # GNU C++ extensions
    GNUPP98 = "gnu++98"
    GNUPP11 = "gnu++11"
    GNUPP14 = "gnu++14"
    GNUPP17 = "gnu++17"
    GNUPP20 = "gnu++20"

    def is_c_standard(self) -> bool:
        """
        Check if this is a C language standard.

        Returns
        -------
        bool
            True if this is a C standard.
        """
        return self.value.startswith(("c", "gnu")) and "++" not in self.value

    def is_cpp_standard(self) -> bool:
        """
        Check if this is a C++ language standard.

        Returns
        -------
        bool
            True if this is a C++ standard.
        """
        return "++" in self.value

    def get_compiler_flag(self, compiler_family: "CompilerFamily") -> str:
        """
        Get the compiler flag for this language standard.

        Parameters
        ----------
        compiler_family : CompilerFamily
            Compiler family to generate flag for.

        Returns
        -------
        str
            Compiler flag for the language standard.
        """
        if compiler_family == CompilerFamily.MICROSOFT:
            ms_flags = {
                self.C89: "/std:c89",
                self.C99: "/std:c99",
                self.C11: "/std:c11",
                self.C17: "/std:c17",
                self.CPP98: "/std:c++98",
                self.CPP11: "/std:c++11",
                self.CPP14: "/std:c++14",
                self.CPP17: "/std:c++17",
                self.CPP20: "/std:c++20",
                self.CPP23: "/std:c++latest",
            }
            return ms_flags.get(self, "")

        # GCC/Clang/Intel
        return f"-std={self.value}"

    def get_year(self) -> int:
        """
        Get the year this standard was published.

        Returns
        -------
        int
            Publication year.
        """
        years = {
            self.C89: 1989,
            self.C99: 1999,
            self.C11: 2011,
            self.C17: 2017,
            self.C23: 2023,
            self.CPP98: 1998,
            self.CPP11: 2011,
            self.CPP14: 2014,
            self.CPP17: 2017,
            self.CPP20: 2020,
            self.CPP23: 2023,
        }
        return years.get(self, 0)


class LinkType(Enum):
    """
    Link type enumeration for library linking.

    Attributes
    ----------
    SHARED : str
        Dynamic/shared library (.so, .dll, .dylib).
    STATIC : str
        Static library (.a, .lib).
    EXECUTABLE : str
        Standalone executable.
    MODULE : str
        Python extension module.
    """

    SHARED = "shared"
    STATIC = "static"
    EXECUTABLE = "executable"
    MODULE = "module"

    def get_extension(self, platform: str = None) -> str:
        """
        Get the file extension for this link type.

        Parameters
        ----------
        platform : str, optional
            Platform identifier (default: current platform).

        Returns
        -------
        str
            File extension including dot.
        """
        import sys

        platform = platform or sys.platform

        if self == self.SHARED:
            if platform == "win32":
                return ".dll"
            elif platform == "darwin":
                return ".dylib"
            else:
                return ".so"
        elif self == self.STATIC:
            if platform == "win32":
                return ".lib"
            else:
                return ".a"
        elif self == self.EXECUTABLE:
            if platform == "win32":
                return ".exe"
            else:
                return ""
        elif self == self.MODULE:
            if platform == "win32":
                return ".pyd"
            else:
                return ".so"
        return ""


class DependencyType(Enum):
    """
    Dependency relationship type enumeration.

    Attributes
    ----------
    HARD : str
        Required dependency, must be compiled first.
    SOFT : str
        Optional dependency, compiled if available.
    CIRCULAR : str
        Circular dependency detected.
    SYSTEM : str
        System library dependency.
    HEADER_ONLY : str
        Header-only library dependency.
    RUNTIME : str
        Runtime dependency only (no compile-time requirement).
    """

    HARD = "hard"
    SOFT = "soft"
    CIRCULAR = "circular"
    SYSTEM = "system"
    HEADER_ONLY = "header_only"
    RUNTIME = "runtime"

    def requires_compilation(self) -> bool:
        """
        Check if this dependency requires compilation.

        Returns
        -------
        bool
            True if compilation is required.
        """
        return self in {self.HARD, self.CIRCULAR}

    def is_optional(self) -> bool:
        """
        Check if this dependency is optional.

        Returns
        -------
        bool
            True if dependency is optional.
        """
        return self == self.SOFT


class FileChangeType(Enum):
    """
    File system change type enumeration for hot reloading.

    Attributes
    ----------
    CREATED : str
        File was created.
    MODIFIED : str
        File was modified.
    DELETED : str
        File was deleted.
    MOVED : str
        File was moved/renamed.
    """

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"

    def requires_recompile(self) -> bool:
        """
        Check if this change requires recompilation.

        Returns
        -------
        bool
            True if recompilation is needed.
        """
        return self in {self.CREATED, self.MODIFIED}

    def requires_reload(self) -> bool:
        """
        Check if this change requires module reload.

        Returns
        -------
        bool
            True if module reload is needed.
        """
        return self in {self.CREATED, self.MODIFIED}


class SandboxPolicy(Enum):
    """
    Sandbox security policy enumeration.

    Attributes
    ----------
    NONE : str
        No sandboxing.
    BASIC : str
        Basic resource limits only.
    STRICT : str
        Strict isolation with all restrictions.
    CUSTOM : str
        Custom policy defined by user.
    """

    NONE = "none"
    BASIC = "basic"
    STRICT = "strict"
    CUSTOM = "custom"

    def get_default_timeout(self) -> Optional[int]:
        """
        Get default compilation timeout in seconds.

        Returns
        -------
        Optional[int]
            Timeout in seconds, or None for unlimited.
        """
        timeouts = {
            self.NONE: None,
            self.BASIC: 300,  # 5 minutes
            self.STRICT: 60,  # 1 minute
            self.CUSTOM: None,
        }
        return timeouts.get(self, 300)

    def get_default_memory_limit_mb(self) -> Optional[int]:
        """
        Get default memory limit in megabytes.

        Returns
        -------
        Optional[int]
            Memory limit in MB, or None for unlimited.
        """
        limits = {
            self.NONE: None,
            self.BASIC: 4096,  # 4 GB
            self.STRICT: 1024,  # 1 GB
            self.CUSTOM: None,
        }
        return limits.get(self, 4096)

    def restrict_filesystem_access(self) -> bool:
        """
        Check if filesystem access should be restricted.

        Returns
        -------
        bool
            True if filesystem should be restricted.
        """
        return self == self.STRICT

    def restrict_network_access(self) -> bool:
        """
        Check if network access should be restricted.

        Returns
        -------
        bool
            True if network should be restricted.
        """
        return self == self.STRICT


class LogLevel(Enum):
    """
    Logging level enumeration.

    Attributes
    ----------
    QUIET : int
        No output except fatal errors.
    ERROR : int
        Only error messages.
    WARNING : int
        Warnings and errors.
    INFO : int
        Informational messages.
    VERBOSE : int
        Verbose output with progress.
    DEBUG : int
        Debug-level detailed output.
    TRACE : int
        Trace-level extremely detailed output.
    """

    QUIET = 0
    ERROR = 1
    WARNING = 2
    INFO = 3
    VERBOSE = 4
    DEBUG = 5
    TRACE = 6

    def to_logging_level(self) -> int:
        """
        Convert to Python logging module level.

        Returns
        -------
        int
            Logging module level constant.
        """
        import logging

        mapping = {
            self.QUIET: logging.CRITICAL,
            self.ERROR: logging.ERROR,
            self.WARNING: logging.WARNING,
            self.INFO: logging.INFO,
            self.VERBOSE: logging.INFO,
            self.DEBUG: logging.DEBUG,
            self.TRACE: logging.DEBUG,
        }
        return mapping.get(self, logging.INFO)

    def should_show_progress(self) -> bool:
        """
        Check if progress indicators should be shown.

        Returns
        -------
        bool
            True if progress should be shown.
        """
        return self.value >= self.VERBOSE.value

    def should_show_commands(self) -> bool:
        """
        Check if compilation commands should be printed.

        Returns
        -------
        bool
            True if commands should be shown.
        """
        return self.value >= self.DEBUG.value

    def should_show_trace(self) -> bool:
        """
        Check if trace-level details should be shown.

        Returns
        -------
        bool
            True if trace details should be shown.
        """
        return self.value >= self.TRACE.value