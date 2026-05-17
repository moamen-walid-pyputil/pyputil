#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    COMPILER BASE ABSTRACTIONS
==================================

Abstract base classes and data structures for compiler abstraction layer.
Provides unified interface for all compiler implementations.
"""

import os
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, Flag, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union


class CompilerFamily(Enum):
    """
    Compiler family enumeration for high-level categorization.

    Attributes
    ----------
    GNU : str
        GNU Compiler Collection (GCC) and compatible compilers.
    LLVM : str
        LLVM/Clang compiler family.
    MICROSOFT : str
        Microsoft Visual C++ (MSVC) compiler family.
    INTEL : str
        Intel C++ Compiler (ICC, ICX) family.
    OTHER : str
        Unknown or other compiler families.
    """

    GNU = "gnu"
    LLVM = "llvm"
    MICROSOFT = "microsoft"
    INTEL = "intel"
    OTHER = "other"

    def get_flag_style(self) -> str:
        """
        Get the flag style for this compiler family.

        Returns
        -------
        str
            Flag style: 'gnu' (dash-prefixed) or 'msvc' (slash-prefixed).
        """
        if self == self.MICROSOFT:
            return "msvc"
        return "gnu"

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
                "module": ".pyd",
                "preprocessed": ".i",
                "assembly": ".asm",
            }
        elif self == self.INTEL:
            return {
                "object": ".o",
                "shared_library": ".so",
                "static_library": ".a",
                "executable": "",
                "module": ".so",
                "preprocessed": ".i",
                "assembly": ".s",
            }
        else:
            return {
                "object": ".o",
                "shared_library": ".so",
                "static_library": ".a",
                "executable": "",
                "module": ".so",
                "preprocessed": ".i",
                "assembly": ".s",
            }

    def get_define_flag(self) -> str:
        """
        Get preprocessor define flag.

        Returns
        -------
        str
            Define flag (e.g., '-D' for GNU, '/D' for MSVC).
        """
        return "/D" if self == self.MICROSOFT else "-D"

    def get_include_flag(self) -> str:
        """
        Get include path flag.

        Returns
        -------
        str
            Include flag (e.g., '-I' for GNU, '/I' for MSVC).
        """
        return "/I" if self == self.MICROSOFT else "-I"

    def get_library_flag(self) -> str:
        """
        Get library linking flag.

        Returns
        -------
        str
            Library flag (e.g., '-l' for GNU, '' for MSVC).
        """
        return "" if self == self.MICROSOFT else "-l"

    def get_library_path_flag(self) -> str:
        """
        Get library search path flag.

        Returns
        -------
        str
            Library path flag (e.g., '-L' for GNU, '/LIBPATH:' for MSVC).
        """
        return "/LIBPATH:" if self == self.MICROSOFT else "-L"

    def get_output_flag(self) -> str:
        """
        Get output file flag.

        Returns
        -------
        str
            Output flag (e.g., '-o' for GNU, '/Fe' for MSVC executable,
            '/Fo' for MSVC object).
        """
        return "/Fe" if self == self.MICROSOFT else "-o"

    def get_object_output_flag(self) -> str:
        """
        Get object file output flag.

        Returns
        -------
        str
            Object output flag (e.g., '-c -o' for GNU, '/Fo' for MSVC).
        """
        return "/Fo" if self == self.MICROSOFT else "-o"

    def get_shared_flag(self) -> str:
        """
        Get shared library flag.

        Returns
        -------
        str
            Shared flag (e.g., '-shared' for GNU, '/LD' for MSVC).
        """
        return "/LD" if self == self.MICROSOFT else "-shared"

    def get_pic_flag(self) -> str:
        """
        Get position-independent code flag.

        Returns
        -------
        str
            PIC flag (e.g., '-fPIC' for GNU, '' for MSVC).
        """
        return "" if self == self.MICROSOFT else "-fPIC"

    def get_optimization_flag(self, level: int) -> str:
        """
        Get optimization flag for a given level.

        Parameters
        ----------
        level : int
            Optimization level (0-3).

        Returns
        -------
        str
            Optimization flag.
        """
        if self == self.MICROSOFT:
            flags = {0: "/Od", 1: "/O1", 2: "/O2", 3: "/Ox"}
        else:
            flags = {0: "-O0", 1: "-O1", 2: "-O2", 3: "-O3"}
        return flags.get(level, "-O2" if self != self.MICROSOFT else "/O2")

    def get_debug_flag(self) -> str:
        """
        Get debug symbols flag.

        Returns
        -------
        str
            Debug flag (e.g., '-g' for GNU, '/Zi' for MSVC).
        """
        return "/Zi" if self == self.MICROSOFT else "-g"

    def get_warning_flag(self, level: str = "all") -> str:
        """
        Get warning flag for a given level.

        Parameters
        ----------
        level : str
            Warning level ('all', 'extra', 'error').

        Returns
        -------
        str
            Warning flag.
        """
        if self == self.MICROSOFT:
            flags = {"all": "/W4", "extra": "/Wall", "error": "/WX"}
        else:
            flags = {"all": "-Wall", "extra": "-Wextra", "error": "-Werror"}
        return flags.get(level, "-Wall" if self != self.MICROSOFT else "/W3")

    def get_standard_flag(self, standard: str) -> str:
        """
        Get language standard flag.

        Parameters
        ----------
        standard : str
            Language standard (e.g., 'c11', 'c++17').

        Returns
        -------
        str
            Standard flag.
        """
        if self == self.MICROSOFT:
            mapping = {
                "c89": "/std:c89",
                "c99": "/std:c99",
                "c11": "/std:c11",
                "c17": "/std:c17",
                "c++98": "/std:c++98",
                "c++11": "/std:c++11",
                "c++14": "/std:c++14",
                "c++17": "/std:c++17",
                "c++20": "/std:c++20",
                "c++23": "/std:c++latest",
            }
        else:
            mapping = {
                "c89": "-std=c89",
                "c99": "-std=c99",
                "c11": "-std=c11",
                "c17": "-std=c17",
                "c++98": "-std=c++98",
                "c++11": "-std=c++11",
                "c++14": "-std=c++14",
                "c++17": "-std=c++17",
                "c++20": "-std=c++20",
                "c++23": "-std=c++23",
            }
        return mapping.get(standard, "")


class CompilerFeature(Flag):
    """
    Compiler feature flags enumeration.

    These flags indicate which features are supported by a compiler.

    Attributes
    ----------
    NONE : int
        No special features.
    C89 : int
        C89/C90 language support.
    C99 : int
        C99 language support.
    C11 : int
        C11 language support.
    C17 : int
        C17 language support.
    C23 : int
        C23 language support.
    CPP98 : int
        C++98 language support.
    CPP11 : int
        C++11 language support.
    CPP14 : int
        C++14 language support.
    CPP17 : int
        C++17 language support.
    CPP20 : int
        C++20 language support.
    CPP23 : int
        C++23 language support.
    OPENMP : int
        OpenMP parallel programming support.
    SIMD_SSE : int
        SSE SIMD instructions.
    SIMD_SSE2 : int
        SSE2 SIMD instructions.
    SIMD_SSE3 : int
        SSE3 SIMD instructions.
    SIMD_SSSE3 : int
        SSSE3 SIMD instructions.
    SIMD_SSE4_1 : int
        SSE4.1 SIMD instructions.
    SIMD_SSE4_2 : int
        SSE4.2 SIMD instructions.
    SIMD_AVX : int
        AVX SIMD instructions.
    SIMD_AVX2 : int
        AVX2 SIMD instructions.
    SIMD_AVX512 : int
        AVX-512 SIMD instructions.
    SIMD_NEON : int
        ARM NEON SIMD instructions.
    LTO : int
        Link-Time Optimization support.
    PGO : int
        Profile-Guided Optimization support.
    SANITIZE_ADDRESS : int
        AddressSanitizer support.
    SANITIZE_THREAD : int
        ThreadSanitizer support.
    SANITIZE_UNDEFINED : int
        UndefinedBehaviorSanitizer support.
    COVERAGE : int
        Code coverage instrumentation.
    COROUTINES : int
        C++20 coroutines support.
    MODULES : int
        C++20 modules support.
    CONCEPTS : int
        C++20 concepts support.
    """

    NONE = 0

    # C standards
    C89 = auto()
    C99 = auto()
    C11 = auto()
    C17 = auto()
    C23 = auto()

    # C++ standards
    CPP98 = auto()
    CPP11 = auto()
    CPP14 = auto()
    CPP17 = auto()
    CPP20 = auto()
    CPP23 = auto()

    # Parallelism
    OPENMP = auto()

    # SIMD (x86)
    SIMD_SSE = auto()
    SIMD_SSE2 = auto()
    SIMD_SSE3 = auto()
    SIMD_SSSE3 = auto()
    SIMD_SSE4_1 = auto()
    SIMD_SSE4_2 = auto()
    SIMD_AVX = auto()
    SIMD_AVX2 = auto()
    SIMD_AVX512 = auto()

    # SIMD (ARM)
    SIMD_NEON = auto()

    # Optimizations
    LTO = auto()
    PGO = auto()

    # Sanitizers
    SANITIZE_ADDRESS = auto()
    SANITIZE_THREAD = auto()
    SANITIZE_UNDEFINED = auto()

    # Instrumentation
    COVERAGE = auto()

    # C++20 features
    COROUTINES = auto()
    MODULES = auto()
    CONCEPTS = auto()


@dataclass
class CompilerInfo:
    """
    Comprehensive compiler information and capabilities.

    Parameters
    ----------
    name : str
        Compiler name (e.g., 'gcc', 'clang', 'cl', 'icc').
    family : CompilerFamily
        Compiler family.
    version : str
        Full version string.
    version_major : int
        Major version number.
    version_minor : int
        Minor version number.
    version_patch : int
        Patch version number.
    executable_path : Optional[Path]
        Path to compiler executable.
    target_triple : str
        Target architecture triple.
    features : CompilerFeature
        Supported features bitmask.
    default_flags : List[str]
        Default compiler flags.
    supported_flags : Set[str]
        Set of all supported flags.
    include_paths : List[Path]
        Default include search paths.
    library_paths : List[Path]
        Default library search paths.
    predefined_macros : Dict[str, str]
        Predefined preprocessor macros.

    Attributes
    ----------
    name : str
        Compiler name.
    family : CompilerFamily
        Compiler family.
    version : str
        Version string.
    version_major : int
        Major version.
    version_minor : int
        Minor version.
    version_patch : int
        Patch version.
    executable_path : Optional[Path]
        Executable path.
    target_triple : str
        Target triple.
    features : CompilerFeature
        Feature flags.
    default_flags : List[str]
        Default flags.
    supported_flags : Set[str]
        Supported flags.
    include_paths : List[Path]
        Include paths.
    library_paths : List[Path]
        Library paths.
    predefined_macros : Dict[str, str]
        Predefined macros.

    Examples
    --------
    >>> info = CompilerInfo(
    ...     name="gcc",
    ...     family=CompilerFamily.GNU,
    ...     version="11.4.0",
    ...     version_major=11,
    ...     version_minor=4,
    ...     version_patch=0,
    ...     executable_path=Path("/usr/bin/gcc"),
    ...     target_triple="x86_64-linux-gnu",
    ...     features=CompilerFeature.C11 | CompilerFeature.CPP17 | CompilerFeature.OPENMP
    ... )
    >>> print(f"Compiler: {info.name} {info.version}")
    >>> print(f"Supports C++17: {bool(info.features & CompilerFeature.CPP17)}")
    """

    name: str
    family: CompilerFamily
    version: str
    version_major: int = 0
    version_minor: int = 0
    version_patch: int = 0
    executable_path: Optional[Path] = None
    target_triple: str = ""
    features: CompilerFeature = CompilerFeature.NONE
    default_flags: List[str] = field(default_factory=list)
    supported_flags: Set[str] = field(default_factory=set)
    include_paths: List[Path] = field(default_factory=list)
    library_paths: List[Path] = field(default_factory=list)
    predefined_macros: Dict[str, str] = field(default_factory=dict)

    def has_feature(self, feature: CompilerFeature) -> bool:
        """
        Check if compiler supports a specific feature.

        Parameters
        ----------
        feature : CompilerFeature
            Feature to check.

        Returns
        -------
        bool
            True if feature is supported.
        """
        return bool(self.features & feature)

    def supports_flag(self, flag: str) -> bool:
        """
        Check if compiler supports a specific flag.

        Parameters
        ----------
        flag : str
            Flag to check.

        Returns
        -------
        bool
            True if flag is supported.
        """
        return flag in self.supported_flags

    def get_version_tuple(self) -> Tuple[int, int, int]:
        """
        Get version as tuple.

        Returns
        -------
        Tuple[int, int, int]
            (major, minor, patch) version tuple.
        """
        return (self.version_major, self.version_minor, self.version_patch)

    def compare_version(self, other: str) -> int:
        """
        Compare version with another version string.

        Parameters
        ----------
        other : str
            Version string to compare (e.g., "10.0.0").

        Returns
        -------
        int
            -1 if older, 0 if equal, 1 if newer.
        """
        try:
            parts = other.split(".")
            other_tuple = (
                int(parts[0]),
                int(parts[1]) if len(parts) > 1 else 0,
                int(parts[2]) if len(parts) > 2 else 0,
            )
        except (ValueError, IndexError):
            return 0

        my_tuple = self.get_version_tuple()

        if my_tuple < other_tuple:
            return -1
        elif my_tuple > other_tuple:
            return 1
        return 0

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "name": self.name,
            "family": self.family.value,
            "version": self.version,
            "version_major": self.version_major,
            "version_minor": self.version_minor,
            "version_patch": self.version_patch,
            "executable_path": str(self.executable_path) if self.executable_path else None,
            "target_triple": self.target_triple,
            "features": [f.name for f in CompilerFeature if self.features & f],
            "default_flags": self.default_flags,
            "include_paths": [str(p) for p in self.include_paths],
            "library_paths": [str(p) for p in self.library_paths],
        }

    def __repr__(self) -> str:
        return f"<CompilerInfo {self.name} {self.version} ({self.target_triple})>"


@dataclass
class CompileResult:
    """
    Result of a compilation operation.

    Parameters
    ----------
    success : bool
        Whether compilation succeeded.
    output_path : Optional[Path]
        Path to output file.
    compile_time : float
        Compilation time in seconds.
    command : List[str]
        Compilation command executed.
    return_code : int
        Process return code.
    stdout : str
        Standard output.
    stderr : str
        Standard error.
    warnings : List[str]
        Parsed warning messages.
    errors : List[str]
        Parsed error messages.
    object_size : int
        Size of output file in bytes.
    cache_hit : bool
        Whether result came from cache.

    Attributes
    ----------
    success : bool
        Success flag.
    output_path : Optional[Path]
        Output path.
    compile_time : float
        Compilation time.
    command : List[str]
        Command executed.
    return_code : int
        Return code.
    stdout : str
        Stdout output.
    stderr : str
        Stderr output.
    warnings : List[str]
        Warning messages.
    errors : List[str]
        Error messages.
    object_size : int
        Output size.
    cache_hit : bool
        Cache hit flag.
    """

    success: bool
    output_path: Optional[Path] = None
    compile_time: float = 0.0
    command: List[str] = field(default_factory=list)
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    object_size: int = 0
    cache_hit: bool = False

    def has_warnings(self) -> bool:
        """
        Check if compilation produced warnings.

        Returns
        -------
        bool
            True if there are warnings.
        """
        return len(self.warnings) > 0

    def has_errors(self) -> bool:
        """
        Check if compilation produced errors.

        Returns
        -------
        bool
            True if there are errors.
        """
        return len(self.errors) > 0

    def get_summary(self) -> str:
        """
        Get a human-readable summary.

        Returns
        -------
        str
            Summary string.
        """
        if self.success:
            status = "SUCCESS"
            if self.cache_hit:
                status += " (cached)"
        else:
            status = f"FAILED (code {self.return_code})"

        summary = [f"Compilation {status} in {self.compile_time:.2f}s"]

        if self.output_path:
            size_mb = self.object_size / (1024 * 1024)
            summary.append(f"Output: {self.output_path} ({size_mb:.2f} MB)")

        if self.warnings:
            summary.append(f"Warnings: {len(self.warnings)}")
            for w in self.warnings[:3]:
                summary.append(f"  - {w}")

        if self.errors:
            summary.append(f"Errors: {len(self.errors)}")
            for e in self.errors[:3]:
                summary.append(f"  - {e}")

        return "\n".join(summary)

    def __bool__(self) -> bool:
        return self.success


@dataclass
class PreprocessResult:
    """
    Result of a preprocessing operation.

    Parameters
    ----------
    success : bool
        Whether preprocessing succeeded.
    output : str
        Preprocessed source code.
    output_path : Optional[Path]
        Path to preprocessed file.
    macros : Dict[str, str]
        Detected macro definitions.
    includes : List[Path]
        Included header files.
    compile_time : float
        Processing time in seconds.

    Attributes
    ----------
    success : bool
        Success flag.
    output : str
        Preprocessed output.
    output_path : Optional[Path]
        Output file path.
    macros : Dict[str, str]
        Macro definitions.
    includes : List[Path]
        Included headers.
    compile_time : float
        Processing time.
    """

    success: bool
    output: str = ""
    output_path: Optional[Path] = None
    macros: Dict[str, str] = field(default_factory=dict)
    includes: List[Path] = field(default_factory=list)
    compile_time: float = 0.0


class CompilerBackend(ABC):
    """
    Abstract base class for all compiler backends.

    This class defines the interface that all compiler implementations
    must provide, ensuring consistent behavior across different compilers
    and platforms.

    Parameters
    ----------
    executable_path : Optional[Path]
        Path to compiler executable. Auto-detected if None.
    target : Optional[str]
        Target architecture triple.
    verbose : bool
        Enable verbose output.

    Attributes
    ----------
    executable_path : Optional[Path]
        Compiler executable path.
    target : Optional[str]
        Target architecture.
    verbose : bool
        Verbose flag.
    info : CompilerInfo
        Compiler information and capabilities.
    _temp_dir : Optional[Path]
        Temporary directory for compilation.

    Examples
    --------
    >>> # Subclass implementation
    >>> class GCCBackend(CompilerBackend):
    ...     @property
    ...     def name(self) -> str:
    ...         return "gcc"
    ...     
    ...     @property
    ...     def family(self) -> CompilerFamily:
    ...         return CompilerFamily.GNU
    ...     
    ...     def _detect_info(self) -> CompilerInfo:
    ...         # Detection logic
    ...         pass
    """

    def __init__(
        self,
        executable_path: Optional[Path] = None,
        target: Optional[str] = None,
        verbose: bool = False,
    ):
        self.executable_path = executable_path
        self.target = target
        self.verbose = verbose
        self._temp_dir: Optional[Path] = None

        # Lazy initialization
        self._info: Optional[CompilerInfo] = None

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Get compiler name.

        Returns
        -------
        str
            Compiler name (e.g., 'gcc', 'clang').
        """
        pass

    @property
    @abstractmethod
    def family(self) -> CompilerFamily:
        """
        Get compiler family.

        Returns
        -------
        CompilerFamily
            Compiler family.
        """
        pass

    @property
    def info(self) -> CompilerInfo:
        """
        Get compiler information (lazy-loaded).

        Returns
        -------
        CompilerInfo
            Compiler information.
        """
        if self._info is None:
            self._info = self._detect_info()
        return self._info

    @abstractmethod
    def _detect_info(self) -> CompilerInfo:
        """
        Detect compiler information and capabilities.

        Returns
        -------
        CompilerInfo
            Detected compiler information.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if compiler is available and functional.

        Returns
        -------
        bool
            True if compiler is available.
        """
        pass

    @abstractmethod
    def compile(
        self,
        sources: List[Path],
        output_path: Path,
        flags: Optional[List[str]] = None,
        defines: Optional[Dict[str, str]] = None,
        include_paths: Optional[List[Path]] = None,
        library_paths: Optional[List[Path]] = None,
        libraries: Optional[List[str]] = None,
        link_type: str = "shared",
        optimization_level: int = 2,
        debug: bool = False,
    ) -> CompileResult:
        """
        Compile source files to object code or library.

        Parameters
        ----------
        sources : List[Path]
            List of source files to compile.
        output_path : Path
            Path for output file.
        flags : Optional[List[str]]
            Additional compiler flags.
        defines : Optional[Dict[str, str]]
            Preprocessor defines.
        include_paths : Optional[List[Path]]
            Additional include directories.
        library_paths : Optional[List[Path]]
            Additional library search paths.
        libraries : Optional[List[str]]
            Libraries to link against.
        link_type : str
            Type of output ('object', 'shared', 'static', 'executable').
        optimization_level : int
            Optimization level (0-3).
        debug : bool
            Include debug symbols.

        Returns
        -------
        CompileResult
            Compilation result.
        """
        pass

    @abstractmethod
    def preprocess(
        self,
        source: Path,
        output_path: Optional[Path] = None,
        defines: Optional[Dict[str, str]] = None,
        include_paths: Optional[List[Path]] = None,
    ) -> PreprocessResult:
        """
        Preprocess a source file.

        Parameters
        ----------
        source : Path
            Source file to preprocess.
        output_path : Optional[Path]
            Output file path for preprocessed source.
        defines : Optional[Dict[str, str]]
            Preprocessor defines.
        include_paths : Optional[List[Path]]
            Include directories.

        Returns
        -------
        PreprocessResult
            Preprocessing result.
        """
        pass

    @abstractmethod
    def get_default_flags(self) -> List[str]:
        """
        Get default compiler flags.

        Returns
        -------
        List[str]
            Default flags.
        """
        pass

    @abstractmethod
    def check_flag_support(self, flag: str) -> bool:
        """
        Check if a compiler flag is supported.

        Parameters
        ----------
        flag : str
            Flag to check.

        Returns
        -------
        bool
            True if flag is supported.
        """
        pass

    @abstractmethod
    def get_include_paths(self) -> List[Path]:
        """
        Get default include search paths.

        Returns
        -------
        List[Path]
            List of include directories.
        """
        pass

    @abstractmethod
    def get_library_paths(self) -> List[Path]:
        """
        Get default library search paths.

        Returns
        -------
        List[Path]
            List of library directories.
        """
        pass

    @abstractmethod
    def get_predefined_macros(self) -> Dict[str, str]:
        """
        Get predefined preprocessor macros.

        Returns
        -------
        Dict[str, str]
            Dictionary of macro names to values.
        """
        pass

    def _find_executable(self) -> Optional[Path]:
        """
        Find compiler executable in PATH.

        Returns
        -------
        Optional[Path]
            Path to executable or None.
        """
        import shutil

        # Check provided path
        if self.executable_path:
            if self.executable_path.exists():
                return self.executable_path

        # Search in PATH
        path = shutil.which(self.name)
        if path:
            return Path(path)

        # Search common locations
        common_paths = [
            Path("/usr/bin") / self.name,
            Path("/usr/local/bin") / self.name,
            Path("/opt/local/bin") / self.name,
            Path.home() / ".local" / "bin" / self.name,
        ]

        for p in common_paths:
            if p.exists():
                return p

        return None

    def _run_command(
        self,
        cmd: List[str],
        timeout: Optional[float] = 300,
        capture_output: bool = True,
        cwd: Optional[Path] = None,
    ) -> subprocess.CompletedProcess:
        """
        Run a compiler command.

        Parameters
        ----------
        cmd : List[str]
            Command to run.
        timeout : Optional[float]
            Timeout in seconds.
        capture_output : bool
            Whether to capture output.
        cwd : Optional[Path]
            Working directory.

        Returns
        -------
        subprocess.CompletedProcess
            Process result.
        """
        if self.verbose:
            import logging
            logging.getLogger(__name__).debug(f"Running: {' '.join(cmd)}")

        return subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
        )

    def _get_temp_dir(self) -> Path:
        """
        Get or create temporary directory.

        Returns
        -------
        Path
            Temporary directory path.
        """
        if self._temp_dir is None:
            import tempfile
            self._temp_dir = Path(tempfile.mkdtemp(prefix=f"{self.name}_"))
        return self._temp_dir

    def cleanup(self) -> None:
        """
        Clean up temporary files.
        """
        if self._temp_dir and self._temp_dir.exists():
            import shutil
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    def _build_basic_flags(
        self,
        optimization_level: int = 2,
        debug: bool = False,
        link_type: str = "shared",
    ) -> List[str]:
        """
        Build basic compiler flags.

        Parameters
        ----------
        optimization_level : int
            Optimization level (0-3).
        debug : bool
            Include debug symbols.
        link_type : str
            Type of output.

        Returns
        -------
        List[str]
            Basic flags.
        """
        flags = []

        # Optimization
        opt_flag = self.family.get_optimization_flag(optimization_level)
        if opt_flag:
            flags.append(opt_flag)

        # Debug
        if debug:
            debug_flag = self.family.get_debug_flag()
            if debug_flag:
                flags.append(debug_flag)

        # Link type
        if link_type == "shared":
            shared_flag = self.family.get_shared_flag()
            if shared_flag:
                flags.append(shared_flag)
            pic_flag = self.family.get_pic_flag()
            if pic_flag:
                flags.append(pic_flag)

        return flags

    def _parse_warnings_errors(self, output: str) -> Tuple[List[str], List[str]]:
        """
        Parse warnings and errors from compiler output.

        Parameters
        ----------
        output : str
            Compiler output.

        Returns
        -------
        Tuple[List[str], List[str]]
            Tuple of (warnings, errors).
        """
        import re

        warnings = []
        errors = []

        lines = output.split("\n")

        # GCC/Clang patterns
        gcc_warning = re.compile(r"warning:", re.IGNORECASE)
        gcc_error = re.compile(r"error:", re.IGNORECASE)

        # MSVC patterns
        msvc_warning = re.compile(r"warning C\d+:", re.IGNORECASE)
        msvc_error = re.compile(r"error C\d+:", re.IGNORECASE)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if self.family == CompilerFamily.MICROSOFT:
                if msvc_error.search(line):
                    errors.append(line)
                elif msvc_warning.search(line):
                    warnings.append(line)
            else:
                if gcc_error.search(line):
                    errors.append(line)
                elif gcc_warning.search(line):
                    warnings.append(line)

        return warnings, errors

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.name} {self.info.version if self._info else 'unknown'}>"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()