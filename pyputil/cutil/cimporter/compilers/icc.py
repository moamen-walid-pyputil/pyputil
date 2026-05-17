#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    INTEL C++ COMPILER BACKEND
==================================

Intel C++ Compiler (ICC/ICX) backend implementation with comprehensive
feature detection, Intel-specific optimizations, and cross-platform support.

This module provides a complete interface to Intel compilers including:
- Intel C++ Compiler Classic (ICC/ICPC)
- Intel oneAPI DPC++/C++ Compiler (ICX/ICPX)

Key Features:
- Automatic compiler detection and version parsing
- Support for Intel-specific optimization flags
- CPU dispatch for multiple architectures
- Integration with Intel MKL, IPP, and TBB
- Profile-Guided Optimization (PGO)
- Interprocedural Optimization (IPO)
- OpenMP parallelization support
- Vectorization reports and optimization diagnostics
"""

import os
import re
import subprocess
import tempfile
import platform as pf
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .base import (
    CompilerBackend,
    CompilerFamily,
    CompilerFeature,
    CompilerInfo,
    CompileResult,
    PreprocessResult,
)


class ICCBackend(CompilerBackend):
    """
    Intel C++ Compiler (ICC/ICX) backend implementation.

    This class provides comprehensive support for Intel compilers with
    automatic detection of both classic ICC and LLVM-based ICX compilers.
    It includes Intel-specific optimizations, CPU dispatch capabilities,
    and integration with Intel performance libraries.

    Parameters
    ----------
    executable_path : Optional[Path], default=None
        Path to ICC/ICX executable. If None, auto-detection is performed
        by searching common installation paths and PATH environment.
    
    target : Optional[str], default=None
        Target architecture triple for cross-compilation. If None, the
        host architecture is automatically detected.
    
    verbose : bool, default=False
        Enable verbose output for debugging. When True, all compiler
        commands and their output are printed to stderr.
    
    use_icx : bool, default=False
        Use ICX (LLVM-based oneAPI compiler) instead of classic ICC.
        ICX provides better C++20/23 support and LLVM optimizations.
    
    use_icpc : bool, default=False
        Use ICPC (C++ compiler) instead of ICC. When True, the compiler
        is invoked in C++ mode with appropriate defaults for C++ code.

    Attributes
    ----------
    executable_path : Optional[Path]
        Path to the detected Intel compiler executable.
    
    icpc_path : Optional[Path]
        Path to the C++ compiler (ICPC or ICPX) if available.
    
    target : Optional[str]
        Target architecture specification.
    
    verbose : bool
        Verbose output flag for debugging.
    
    use_icx : bool
        Flag indicating use of LLVM-based ICX compiler.
    
    use_icpc : bool
        Flag indicating use of C++ compiler mode.
    
    _feature_cache : Dict[str, bool]
        Cache for feature detection results to avoid redundant checks.
    
    _flag_support_cache : Dict[str, bool]
        Cache for compiler flag support verification results.
    
    _is_classic : Optional[bool]
        Flag indicating if using classic ICC (True) or ICX (False).
    
    _intel_env_script : Optional[Path]
        Path to Intel environment setup script (setvars.sh/compilervars.sh).
    
    _info : Optional[CompilerInfo]
        Cached compiler information to prevent infinite recursion.

    Examples
    --------
    >>> # Basic usage with auto-detection
    >>> icc = ICCBackend()
    >>> if icc.is_available():
    ...     result = icc.compile(
    ...         sources=[Path("main.c")],
    ...         output_path=Path("output.so"),
    ...         optimization_level=3
    ...     )
    ...     print(f"Compiled in {result.compile_time:.2f}s")

    >>> # Using ICX (LLVM-based) compiler
    >>> icx = ICCBackend(use_icx=True, use_icpc=True)
    >>> result = icx.compile(
    ...     sources=[Path("main.cpp")],
    ...     output_path=Path("output"),
    ...     flags=["-xHost", "-ipo"],
    ...     optimization_level="fast",
    ...     openmp=True
    ... )

    >>> # CPU dispatch for multiple architectures
    >>> icc = ICCBackend()
    >>> result = icc.compile(
    ...     sources=[Path("kernel.c")],
    ...     output_path=Path("kernel.so"),
    ...     cpu_dispatch="CORE-AVX512,CORE-AVX2,AVX,SSE4.2",
    ...     link_type="shared"
    ... )

    >>> # Integration with Intel MKL
    >>> result = icc.compile(
    ...     sources=[Path("matrix.c")],
    ...     output_path=Path("matrix"),
    ...     mkl="parallel",  # Use threaded MKL
    ...     libraries=["mkl_intel_lp64", "mkl_intel_thread", "mkl_core"],
    ...     link_type="executable"
    ... )

    >>> # Profile-Guided Optimization (PGO)
    >>> # Step 1: Generate profile
    >>> icc.compile(
    ...     sources=[Path("app.c")],
    ...     output_path=Path("app"),
    ...     flags=["-prof-gen"],
    ...     link_type="executable"
    ... )
    >>> # Run app to generate .dyn file
    >>> # Step 2: Use profile
    >>> result = icc.compile(
    ...     sources=[Path("app.c")],
    ...     output_path=Path("app_optimized"),
    ...     flags=["-prof-use"],
    ...     optimization_level=3,
    ...     link_type="executable"
    ... )

    Notes
    -----
    Intel Compiler Versions:
    - ICC classic: versions 12.0 through 19.x
    - ICX (oneAPI): versions 2021.1 and later (based on LLVM)
    
    Key Intel-Specific Flags:
    - `-fast`: Aggressive optimization (equivalent to -O3 -ipo -static)
    - `-xHost`: Optimize for host CPU architecture
    - `-ipo`: Interprocedural Optimization
    - `-qopenmp`: OpenMP parallelization (classic)
    - `-fiopenmp`: OpenMP parallelization (ICX)
    - `-ax`: Generate multiple code paths for CPU dispatch
    - `-prof-gen`/`-prof-use`: Profile-Guided Optimization
    - `-mkl`: Link with Intel Math Kernel Library
    
    CPU Dispatch Syntax:
    - `-axCORE-AVX512,CORE-AVX2,AVX,SSE4.2`
    - Generates optimized code for each specified architecture
    - Runtime selection based on CPU capabilities
    
    See Also
    --------
    GCCBackend : GNU Compiler Collection backend
    ClangBackend : LLVM/Clang compiler backend
    """

    # ========================================================================
    # VERSION FEATURE MAPPINGS
    # ========================================================================
    
    # Version to feature mapping for classic ICC compiler
    # Format: (major, minor) -> List[CompilerFeature]
    ICC_VERSION_FEATURES: Dict[Tuple[int, int], List[CompilerFeature]] = {
        (12, 0): [CompilerFeature.CPP11],
        (13, 0): [CompilerFeature.CPP11],
        (14, 0): [CompilerFeature.CPP11],
        (15, 0): [CompilerFeature.CPP11, CompilerFeature.CPP14, CompilerFeature.OPENMP],
        (16, 0): [
            CompilerFeature.C11, CompilerFeature.CPP11, 
            CompilerFeature.CPP14, CompilerFeature.OPENMP
        ],
        (17, 0): [
            CompilerFeature.C11, CompilerFeature.CPP11, 
            CompilerFeature.CPP14, CompilerFeature.CPP17, 
            CompilerFeature.OPENMP
        ],
        (18, 0): [
            CompilerFeature.C11, CompilerFeature.CPP11, 
            CompilerFeature.CPP14, CompilerFeature.CPP17, 
            CompilerFeature.OPENMP
        ],
        (19, 0): [
            CompilerFeature.C11, CompilerFeature.C17, 
            CompilerFeature.CPP11, CompilerFeature.CPP14, 
            CompilerFeature.CPP17, CompilerFeature.OPENMP
        ],
    }

    # Version to feature mapping for ICX (LLVM-based) compiler
    # ICX versions follow year-based numbering (2021.1, 2022.0, etc.)
    ICX_VERSION_FEATURES: Dict[Tuple[int, int], List[CompilerFeature]] = {
        (2021, 1): [
            CompilerFeature.C11, CompilerFeature.C17, 
            CompilerFeature.CPP11, CompilerFeature.CPP14, 
            CompilerFeature.CPP17, CompilerFeature.CPP20, 
            CompilerFeature.OPENMP
        ],
        (2022, 0): [
            CompilerFeature.C11, CompilerFeature.C17, 
            CompilerFeature.CPP11, CompilerFeature.CPP14, 
            CompilerFeature.CPP17, CompilerFeature.CPP20, 
            CompilerFeature.OPENMP
        ],
        (2023, 0): [
            CompilerFeature.C11, CompilerFeature.C17, CompilerFeature.C23,
            CompilerFeature.CPP11, CompilerFeature.CPP14, 
            CompilerFeature.CPP17, CompilerFeature.CPP20, 
            CompilerFeature.CPP23, CompilerFeature.OPENMP
        ],
        (2024, 0): [
            CompilerFeature.C11, CompilerFeature.C17, CompilerFeature.C23,
            CompilerFeature.CPP11, CompilerFeature.CPP14, 
            CompilerFeature.CPP17, CompilerFeature.CPP20, 
            CompilerFeature.CPP23, CompilerFeature.OPENMP
        ],
    }

    # ========================================================================
    # FLAG MAPPINGS
    # ========================================================================
    
    # SIMD instruction set flags mapping
    SIMD_FLAGS: Dict[str, str] = {
        "sse2": "-msse2",
        "sse3": "-msse3",
        "ssse3": "-mssse3",
        "sse4.1": "-msse4.1",
        "sse4.2": "-msse4.2",
        "avx": "-mavx",
        "avx2": "-xCORE-AVX2",      # Intel-specific flag
        "avx512": "-xCORE-AVX512",   # Intel-specific flag
        "avx512f": "-xCOMMON-AVX512",
        "avx512bw": "-xCORE-AVX512",
        "avx512dq": "-xCORE-AVX512",
        "avx512vl": "-xCORE-AVX512",
    }

    # Optimization level flags for Intel compilers
    OPTIMIZATION_FLAGS: Dict[str, str] = {
        "0": "-O0",      # No optimization
        "1": "-O1",      # Basic optimization
        "2": "-O2",      # Standard optimization (default)
        "3": "-O3",      # Aggressive optimization
        "fast": "-fast", # Intel-specific: -O3 -ipo -static
        "size": "-Os",   # Optimize for size
    }

    # Architecture-specific optimization flags
    ARCH_FLAGS: Dict[str, str] = {
        "native": "-xHost",           # Optimize for host CPU
        "sse2": "-xSSE2",
        "sse3": "-xSSE3",
        "ssse3": "-xSSSE3",
        "sse4.1": "-xSSE4.1",
        "sse4.2": "-xSSE4.2",
        "avx": "-xAVX",
        "avx2": "-xCORE-AVX2",
        "avx512": "-xCOMMON-AVX512",
        "mic": "-xMIC-AVX512",        # Intel MIC architecture
    }

    # CPU dispatch flags for generating multiple code paths
    DISPATCH_FLAGS: Dict[str, str] = {
        "ax": "-ax",                   # Generate multiple code paths
        "ax_auto": "-axCORE-AVX512,CORE-AVX2,AVX,SSE4.2",
    }

    # Interprocedural Optimization (IPO) flags
    IPO_FLAGS: Dict[str, str] = {
        "single": "-ipo",                    # Single file IPO
        "multi": "-ipo -ipo-jobs=auto",      # Multi-file IPO with auto parallel
        "inline": "-inline",                 # Aggressive inlining
        "ipo_inline": "-ipo -inline",        # Combined IPO and inlining
    }

    # OpenMP parallelization flags
    OPENMP_FLAGS: Dict[str, str] = {
        "classic": "-qopenmp",        # Classic ICC OpenMP
        "llvm": "-fiopenmp",          # ICX/LLVM OpenMP
        "simd": "-qopenmp-simd",      # OpenMP SIMD directives only
        "libomp": "-fiopenmp -fopenmp-targets=spir64",  # OpenMP offload
    }

    # Intel Math Kernel Library (MKL) integration flags
    MKL_FLAGS: Dict[str, str] = {
        "sequential": "-mkl=sequential",  # Sequential MKL
        "parallel": "-mkl=parallel",      # Threaded MKL
        "cluster": "-mkl=cluster",        # Cluster MKL
    }

    # Intel Threading Building Blocks (TBB) flags
    TBB_FLAGS: Dict[str, str] = {
        "static": "-tbb",              # Static TBB linking
        "dynamic": "-tbb -tbb-dynamic", # Dynamic TBB linking
    }

    # Profile-Guided Optimization (PGO) flags
    PGO_FLAGS: Dict[str, str] = {
        "generate": "-prof-gen",       # Generate profile data
        "use": "-prof-use",            # Use profile data
        "merge": "-prof-merge",        # Merge profile data
        "gen_parallel": "-prof-gen -parallel",  # Parallel profile generation
    }

    # Optimization diagnostic and report flags
    DIAGNOSTIC_FLAGS: Dict[str, str] = {
        "vector": "-qopt-report -qopt-report-phase=vec",
        "openmp": "-qopt-report -qopt-report-phase=openmp",
        "ipo": "-qopt-report -qopt-report-phase=ipo",
        "loop": "-qopt-report -qopt-report-phase=loop",
        "all": "-qopt-report=5",       # Maximum detail level
        "remarks": "-qopt-report -qopt-report-embed",  # Embed remarks in object
    }

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    def __init__(
        self,
        executable_path: Optional[Path] = None,
        target: Optional[str] = None,
        verbose: bool = False,
        use_icx: bool = False,
        use_icpc: bool = False,
    ):
        """
        Initialize Intel compiler backend.

        Parameters
        ----------
        executable_path : Optional[Path], default=None
            Explicit path to compiler executable. If None, auto-detection
            searches common installation paths and PATH environment.
        
        target : Optional[str], default=None
            Target architecture triple (e.g., 'x86_64-linux-gnu').
            If None, host architecture is used.
        
        verbose : bool, default=False
            Enable verbose output. When True, all compiler commands
            and their output are displayed for debugging.
        
        use_icx : bool, default=False
            Use ICX (LLVM-based oneAPI compiler) instead of classic ICC.
            ICX is recommended for newer C++ standards (C++20/23).
        
        use_icpc : bool, default=False
            Use ICPC/ICPX (C++ compiler) instead of C compiler.
            This automatically sets appropriate C++ defaults.
        """
        super().__init__(executable_path, target, verbose)
        self.use_icx = use_icx
        self.use_icpc = use_icpc
        self.icpc_path: Optional[Path] = None
        self._feature_cache: Dict[str, bool] = {}
        self._flag_support_cache: Dict[str, bool] = {}
        self._is_classic: Optional[bool] = None
        self._intel_env_script: Optional[Path] = None
        self._info: Optional[CompilerInfo] = None  # Cache for compiler info

        # Attempt to setup Intel compiler environment
        self._setup_intel_environment()

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def name(self) -> str:
        """
        Get compiler executable name.

        Returns
        -------
        str
            Compiler name based on configuration:
            - 'icx' for ICX C compiler
            - 'icpx' for ICX C++ compiler
            - 'icc' for classic ICC C compiler
            - 'icpc' for classic ICC C++ compiler
        """
        if self.use_icx:
            return "icpx" if self.use_icpc else "icx"
        return "icpc" if self.use_icpc else "icc"

    @property
    def family(self) -> CompilerFamily:
        """
        Get compiler family identifier.

        Returns
        -------
        CompilerFamily
            Always returns CompilerFamily.INTEL for Intel compilers.
        """
        return CompilerFamily.INTEL

    @property
    def info(self) -> CompilerInfo:
        """
        Get compiler information with lazy loading.

        This property implements lazy initialization to avoid infinite
        recursion during feature detection. The compiler information is
        detected once and cached for subsequent accesses.

        Returns
        -------
        CompilerInfo
            Complete compiler information including version, features,
            paths, and capabilities.

        Raises
        ------
        RuntimeError
            If compiler cannot be detected or version cannot be parsed.
        """
        if self._info is None:
            self._info = self._detect_info()
        return self._info

    # ========================================================================
    # COMPILER DETECTION AND ENVIRONMENT SETUP
    # ========================================================================

    def _find_intel_compiler(self) -> Optional[Path]:
        """
        Find Intel compiler executable in common locations.

        This method searches for Intel compilers in the following order:
        1. System PATH environment
        2. Versioned executables (icx-2023, icc-19, etc.)
        3. Intel oneAPI installation directories
        4. Classic Intel compiler installation paths
        5. Windows-specific installation paths

        Returns
        -------
        Optional[Path]
            Path to compiler executable if found, None otherwise.

        Notes
        -----
        Common installation paths checked:
        - Linux: /opt/intel/oneapi/compiler/latest/bin/
        - Linux: /opt/intel/bin/
        - Windows: C:\\Program Files (x86)\\Intel\\oneAPI\\compiler\\latest\\bin\\
        - Windows: C:\\Program Files\\Intel\\Compiler\\bin\\
        """
        import shutil

        # Build list of compiler names to try
        compiler_names = []
        if self.use_icx:
            # ICX compiler names
            compiler_names.extend(["icx", "icpx"] if self.use_icpc else ["icx"])
        else:
            # Classic ICC compiler names
            compiler_names.extend(["icc", "icpc"] if self.use_icpc else ["icc"])

        # Try system PATH first
        for name in compiler_names:
            path = shutil.which(name)
            if path:
                return Path(path)

        # Try versioned executables (common for multiple versions)
        for version in range(2025, 2020, -1):  # Try newer versions first
            for name in compiler_names:
                versioned = shutil.which(f"{name}-{version}")
                if versioned:
                    return Path(versioned)

        # Check common Intel installation paths
        intel_paths = []

        # Linux/Unix paths
        intel_paths.extend([
            Path("/opt/intel/oneapi/compiler/latest/bin"),
            Path("/opt/intel/oneapi/compiler/2024.0/bin"),
            Path("/opt/intel/oneapi/compiler/2023.0/bin"),
            Path("/opt/intel/bin"),
            Path(os.environ.get("INTEL_HOME", "")) / "bin" if "INTEL_HOME" in os.environ else None,
        ])

        # Windows paths
        intel_paths.extend([
            Path("C:\\Program Files (x86)\\Intel\\oneAPI\\compiler\\latest\\bin"),
            Path("C:\\Program Files\\Intel\\Compiler\\latest\\bin"),
            Path("C:\\Program Files (x86)\\Intel\\Compiler\\latest\\bin"),
        ])

        # Search each path
        for base in intel_paths:
            if base and base.exists():
                for name in compiler_names:
                    exe = base / name
                    if exe.exists():
                        return exe
                    # Windows executable extension
                    exe_win = base / f"{name}.exe"
                    if exe_win.exists():
                        return exe_win

        return None

    def _setup_intel_environment(self) -> bool:
        """
        Setup Intel compiler environment variables.

        This method attempts to locate and source Intel environment
        setup scripts (setvars.sh on Linux, setvars.bat on Windows)
        which configure PATH, LD_LIBRARY_PATH, and other necessary
        environment variables for Intel compilers.

        Returns
        -------
        bool
            True if environment script was found and successfully set up,
            False otherwise.

        Notes
        -----
        The environment setup is attempted but not required for basic
        compiler functionality if the compiler is already in PATH.
        """
        # Common locations for Intel environment setup scripts
        setvars_locations = [
            Path("/opt/intel/oneapi/setvars.sh"),
            Path("/opt/intel/bin/compilervars.sh"),
            Path("/opt/intel/oneapi/compiler/latest/env/vars.sh"),
            Path("C:\\Program Files (x86)\\Intel\\oneAPI\\setvars.bat"),
            Path("C:\\Program Files\\Intel\\oneAPI\\setvars.bat"),
        ]

        for script in setvars_locations:
            if script.exists():
                self._intel_env_script = script
                # Note: Actual sourcing would require shell integration
                # We just record the script location for reference
                if self.verbose:
                    print(f"Found Intel environment script: {script}")
                return True

        return False

    # ========================================================================
    # COMPILER INFORMATION DETECTION
    # ========================================================================

    def _detect_info(self) -> CompilerInfo:
        """
        Detect comprehensive Intel compiler information.

        This method performs complete compiler detection including:
        - Executable location and version parsing
        - Compiler type detection (classic ICC vs ICX)
        - Feature detection based on version
        - Default include and library paths
        - Predefined macros and supported flags

        Returns
        -------
        CompilerInfo
            Complete compiler information structure.

        Raises
        ------
        RuntimeError
            If compiler executable cannot be found.

        Notes
        -----
        This method is called only once due to lazy loading via the
        `info` property, preventing infinite recursion.
        """
        # Find compiler executable
        exe_path = self.executable_path or self._find_intel_compiler()
        if not exe_path:
            raise RuntimeError(
                f"Intel compiler not found. Tried: {self.name}\n"
                "Please ensure Intel oneAPI or classic compiler is installed\n"
                "and properly configured in PATH."
            )

        self.executable_path = exe_path

        # Find C++ compiler if not already using it
        if not self.use_icpc:
            import shutil
            cpp_name = "icpx" if self.use_icx else "icpc"
            cpp_path = shutil.which(cpp_name)
            if cpp_path:
                self.icpc_path = Path(cpp_path)

        # Get version information
        version_info = self._get_version_info()
        self._is_classic = not self.use_icx and version_info["major"] < 2021

        # Detect features (pass version info to avoid recursion)
        features = self._detect_features(version_info)

        # Get default flags (pass version info to avoid recursion)
        default_flags = self._get_default_flags_internal(version_info)

        # Get include and library paths
        include_paths = self._detect_include_paths()
        library_paths = self._detect_library_paths()

        # Get predefined macros and supported flags
        predefined_macros = self._detect_predefined_macros()
        supported_flags = self._detect_supported_flags()

        # Get target triple
        target_triple = self._get_target_info()

        return CompilerInfo(
            name=self.name,
            family=self.family,
            version=version_info["version"],
            version_major=version_info["major"],
            version_minor=version_info["minor"],
            version_patch=version_info["patch"],
            executable_path=self.executable_path,
            target_triple=target_triple,
            features=features,
            default_flags=default_flags,
            supported_flags=supported_flags,
            include_paths=include_paths,
            library_paths=library_paths,
            predefined_macros=predefined_macros,
        )

    def _get_version_info(self) -> Dict[str, Any]:
        """
        Parse Intel compiler version from --version output.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'version': string version (e.g., '2023.0.0')
            - 'major': major version number (int)
            - 'minor': minor version number (int)
            - 'patch': patch version number (int)

        Notes
        -----
        Supports multiple version output formats:
        - Classic ICC: "icc (ICC) 19.0.0 20181019"
        - ICX: "Intel(R) oneAPI DPC++/C++ Compiler 2023.0.0"
        - Generic: "Intel(R) Compiler 2021.1.2"
        """
        try:
            result = self._run_command(
                [str(self.executable_path), "--version"],
                capture_output=True,
                timeout=10,
            )

            output = result.stdout + result.stderr

            # Pattern for classic ICC: "icc (ICC) 19.0.0 20181019"
            pattern_icc = re.compile(
                r"(?:icc|icpc|icx|icpx)\s+\([^)]+\)\s+(\d+)\.(\d+)\.(\d+)",
                re.IGNORECASE
            )

            match = pattern_icc.search(output)
            if match:
                return {
                    "version": f"{match.group(1)}.{match.group(2)}.{match.group(3)}",
                    "major": int(match.group(1)),
                    "minor": int(match.group(2)),
                    "patch": int(match.group(3)),
                }

            # Pattern for ICX: "Intel(R) oneAPI DPC++/C++ Compiler 2023.0.0"
            pattern_icx = re.compile(
                r"(?:Intel.*Compiler|oneAPI)\s+(\d+)\.(\d+)\.(\d+)",
                re.IGNORECASE
            )

            match = pattern_icx.search(output)
            if match:
                return {
                    "version": f"{match.group(1)}.{match.group(2)}.{match.group(3)}",
                    "major": int(match.group(1)),
                    "minor": int(match.group(2)),
                    "patch": int(match.group(3)),
                }

            # Pattern for version-only output
            pattern_version = re.compile(r"(\d+)\.(\d+)\.(\d+)")
            match = pattern_version.search(output)
            if match:
                return {
                    "version": f"{match.group(1)}.{match.group(2)}.{match.group(3)}",
                    "major": int(match.group(1)),
                    "minor": int(match.group(2)),
                    "patch": int(match.group(3)),
                }

        except subprocess.TimeoutExpired:
            if self.verbose:
                print("Warning: Timeout while detecting compiler version")
        except Exception as e:
            if self.verbose:
                print(f"Warning: Error detecting compiler version: {e}")

        # Return unknown version as fallback
        return {"version": "unknown", "major": 0, "minor": 0, "patch": 0}

    def _get_target_info(self) -> str:
        """
        Get target architecture information.

        Returns
        -------
        str
            Target architecture triple in format: {arch}-{system}-intel
            Examples: 'x86_64-linux-intel', 'x86_64-windows-intel'

        Notes
        -----
        If target is explicitly set in constructor, it is returned.
        Otherwise, host architecture is detected using platform module.
        """
        if self.target:
            return self.target

        machine = pf.machine().lower()
        system = pf.system().lower()

        # Map platform machine names to standard triples
        arch_map = {
            "x86_64": "x86_64",
            "amd64": "x86_64",
            "i386": "i686",
            "i686": "i686",
            "arm64": "aarch64",
            "aarch64": "aarch64",
        }

        arch = arch_map.get(machine, machine)
        return f"{arch}-{system}-intel"

    # ========================================================================
    # FEATURE DETECTION
    # ========================================================================

    def _detect_features(self, version_info: Dict[str, Any]) -> CompilerFeature:
        """
        Detect supported Intel compiler features.

        Parameters
        ----------
        version_info : Dict[str, Any]
            Version information from _get_version_info().
            Contains 'major', 'minor', 'patch' keys.

        Returns
        -------
        CompilerFeature
            Bitmask of supported compiler features.

        Notes
        -----
        Features are detected based on:
        1. Version-based feature mapping (using pre-defined tables)
        2. Runtime compilation tests for SIMD support
        3. Flag support checks for IPO, PGO, and OpenMP

        This method does NOT use self.info to avoid infinite recursion.
        """
        features = CompilerFeature.NONE
        version_tuple = (version_info["major"], version_info["minor"])

        # Choose appropriate feature map based on compiler type
        if self.use_icx or version_info["major"] >= 2021:
            feature_map = self.ICX_VERSION_FEATURES
        else:
            feature_map = self.ICC_VERSION_FEATURES

        # Add version-based features (sorted to ensure correct ordering)
        for min_version, feature_list in sorted(feature_map.items()):
            if version_tuple >= min_version:
                for feature in feature_list:
                    features |= feature

        # Detect SIMD support via runtime compilation tests
        features |= self._detect_simd_features()

        # Detect IPO (Interprocedural Optimization) support
        if self.check_flag_support("-ipo"):
            features |= CompilerFeature.LTO

        # Detect PGO (Profile-Guided Optimization) support
        if self.check_flag_support("-prof-gen"):
            features |= CompilerFeature.PGO

        # Detect OpenMP support (both classic and LLVM variants)
        if self.check_flag_support("-qopenmp") or self.check_flag_support("-fiopenmp"):
            features |= CompilerFeature.OPENMP

        return features

    def _detect_simd_features(self) -> CompilerFeature:
        """
        Detect supported SIMD instruction sets via runtime testing.

        Returns
        -------
        CompilerFeature
            Bitmask of supported SIMD features.

        Notes
        -----
        Each SIMD feature is tested by attempting to compile a minimal
        source file with the corresponding compiler flag. Successful
        compilation indicates support.
        """
        features = CompilerFeature.NONE

        # Create minimal test source
        test_code = "int main() { return 0; }"
        with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
            f.write(test_code)
            test_file = Path(f.name)

        try:
            # Test each SIMD flag and map to CompilerFeature
            simd_tests = [
                ("-xSSE2", CompilerFeature.SIMD_SSE2),
                ("-xSSE3", CompilerFeature.SIMD_SSE3),
                ("-xSSSE3", CompilerFeature.SIMD_SSSE3),
                ("-xSSE4.1", CompilerFeature.SIMD_SSE4_1),
                ("-xSSE4.2", CompilerFeature.SIMD_SSE4_2),
                ("-xAVX", CompilerFeature.SIMD_AVX),
                ("-xCORE-AVX2", CompilerFeature.SIMD_AVX2),
                ("-xCOMMON-AVX512", CompilerFeature.SIMD_AVX512),
            ]

            for flag, feature in simd_tests:
                if self._test_compilation(test_file, [flag]):
                    features |= feature

        finally:
            # Clean up temporary file
            test_file.unlink(missing_ok=True)

        return features

    def _test_compilation(self, source: Path, flags: List[str]) -> bool:
        """
        Test if compilation succeeds with given flags.

        Parameters
        ----------
        source : Path
            Path to source file to compile.
        flags : List[str]
            List of compiler flags to test.

        Returns
        -------
        bool
            True if compilation succeeded (return code 0), False otherwise.

        Notes
        -----
        This method compiles to an object file without linking to
        speed up testing. Temporary output files are cleaned up
        regardless of success or failure.
        """
        try:
            # Create temporary output file
            with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as f:
                output = Path(f.name)

            # Build and execute compilation command
            cmd = [str(self.executable_path), "-c", str(source), "-o", str(output)] + flags
            result = self._run_command(cmd, timeout=10)

            # Clean up and return result
            output.unlink(missing_ok=True)
            return result.returncode == 0

        except (subprocess.SubprocessError, OSError):
            return False

    # ========================================================================
    # FLAG AND PATH DETECTION
    # ========================================================================

    def _get_default_flags_internal(self, version_info: Dict[str, Any]) -> List[str]:
        """
        Get default compiler flags.

        Parameters
        ----------
        version_info : Dict[str, Any]
            Version information (reserved for future version-specific flags).

        Returns
        -------
        List[str]
            List of default compiler flags.

        Notes
        -----
        Default flags include:
        - -fPIC: Position-independent code (required for shared libraries)
        - -fno-strict-aliasing: Compatible with Python C API
        """
        flags = [
            "-fPIC",  # Position-independent code
            "-fno-strict-aliasing",  # Required for Python C API compatibility
        ]

        # Add ICX-specific flags
        if not self._is_classic and self._is_classic is not None:
            flags.append("-fno-limit-debug-info")

        return flags

    def _detect_include_paths(self) -> List[Path]:
        """
        Detect default include search paths.

        Returns
        -------
        List[Path]
            List of include directories searched by the compiler.

        Notes
        -----
        Uses -E -Wp,-v flags to query the compiler's include search paths.
        Also adds Intel-specific include directories if found.
        """
        include_paths = []

        # Query compiler for include paths
        try:
            result = self._run_command(
                [str(self.executable_path), "-E", "-Wp,-v", "-xc", "/dev/null"],
                capture_output=True,
            )

            # Parse stderr output for include paths
            in_include_section = False
            for line in result.stderr.split("\n"):
                if "search starts here" in line:
                    in_include_section = True
                    continue
                if "End of search list" in line:
                    break
                if in_include_section:
                    path = line.strip()
                    if path and Path(path).exists():
                        include_paths.append(Path(path))

        except Exception:
            pass

        # Add Intel-specific include paths
        if self.executable_path:
            # Try to find Intel include directory relative to executable
            intel_root = self.executable_path.parent.parent
            intel_include = intel_root / "include"
            if intel_include.exists():
                include_paths.append(intel_include)

        return include_paths

    def _detect_library_paths(self) -> List[Path]:
        """
        Detect default library search paths.

        Returns
        -------
        List[Path]
            List of library directories searched by the linker.

        Notes
        -----
        Uses -print-search-dirs flag to query compiler's library paths.
        Also adds Intel-specific library directories for MKL and TBB.
        """
        library_paths = []

        # Query compiler for library paths
        try:
            result = self._run_command(
                [str(self.executable_path), "-print-search-dirs"],
                capture_output=True,
            )

            for line in result.stdout.split("\n"):
                if line.startswith("libraries:"):
                    paths = line.split(":", 1)[1].strip()
                    for path in paths.split(":"):
                        if path and Path(path).exists():
                            library_paths.append(Path(path))
                    break

        except Exception:
            pass

        # Add Intel-specific library paths
        if self.executable_path:
            intel_root = self.executable_path.parent.parent
            intel_lib = intel_root / "lib"
            if intel_lib.exists():
                library_paths.append(intel_lib)

            # Architecture-specific library directory
            arch_lib = intel_root / "lib" / "intel64"
            if arch_lib.exists():
                library_paths.append(arch_lib)

        return library_paths

    def _detect_predefined_macros(self) -> Dict[str, str]:
        """
        Detect predefined preprocessor macros.

        Returns
        -------
        Dict[str, str]
            Dictionary mapping macro names to their values.

        Notes
        -----
        Uses -E -dM flags to dump all predefined macros.
        """
        macros = {}

        try:
            result = self._run_command(
                [str(self.executable_path), "-E", "-dM", "-xc", "/dev/null"],
                capture_output=True,
            )

            for line in result.stdout.split("\n"):
                if line.startswith("#define "):
                    parts = line[8:].split(" ", 1)
                    if len(parts) == 2:
                        macros[parts[0]] = parts[1]
                    else:
                        macros[parts[0]] = "1"

        except Exception:
            pass

        return macros

    def _detect_supported_flags(self) -> Set[str]:
        """
        Detect supported compiler flags.

        Returns
        -------
        Set[str]
            Set of compiler flags that are supported by this version.

        Notes
        -----
        Tests a comprehensive list of common Intel compiler flags
        and returns only those that are accepted.
        """
        supported = set()

        # List of common Intel compiler flags to test
        common_flags = [
            # Optimization flags
            "-O0", "-O1", "-O2", "-O3", "-fast", "-Os",
            # Debug flags
            "-g", "-g3",
            # Warning flags
            "-Wall", "-w", "-Werror",
            # Code generation flags
            "-fPIC", "-fPIE",
            # IPO flags
            "-ipo", "-ipo-jobs=auto",
            # OpenMP flags
            "-qopenmp", "-fiopenmp", "-qopenmp-simd",
            # Architecture flags
            "-xHost", "-xSSE2", "-xSSE3", "-xSSSE3",
            "-xSSE4.1", "-xSSE4.2", "-xAVX", "-xCORE-AVX2", "-xCOMMON-AVX512",
            # CPU dispatch flags
            "-ax", "-axCORE-AVX512,CORE-AVX2,AVX,SSE4.2",
            # MKL flags
            "-mkl=sequential", "-mkl=parallel", "-mkl=cluster",
            # TBB flags
            "-tbb", "-tbb-dynamic",
            # PGO flags
            "-prof-gen", "-prof-use",
            # Report flags
            "-qopt-report", "-qopt-report=5",
            # Vectorization flags
            "-vec", "-no-vec", "-simd", "-no-simd",
        ]

        # Test each flag for support
        for flag in common_flags:
            if self.check_flag_support(flag):
                supported.add(flag)

        return supported

    # ========================================================================
    # PUBLIC API METHODS
    # ========================================================================

    def is_available(self) -> bool:
        """
        Check if Intel compiler is available and functional.

        Returns
        -------
        bool
            True if compiler executable exists and returns version info,
            False otherwise.

        Notes
        -----
        This method does not rely on lazy-loaded info property to
        avoid recursion during initial detection.
        """
        try:
            # Find executable without using cached info
            exe = self.executable_path or self._find_intel_compiler()
            if not exe:
                return False

            # Test basic functionality
            result = self._run_command(
                [str(exe), "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0

        except Exception:
            return False

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
        optimization_level: Union[int, str] = 2,
        debug: bool = False,
        language: str = "c",
        standard: Optional[str] = None,
        warnings: Union[bool, str] = True,
        extra_objects: Optional[List[Path]] = None,
        ipo: bool = False,
        openmp: bool = False,
        cpu_dispatch: Optional[str] = None,
        mkl: Optional[str] = None,
        tbb: bool = False,
        vector_report: bool = False,
        use_fast: bool = False,
    ) -> CompileResult:
        """
        Compile source files using Intel compiler.

        Parameters
        ----------
        sources : List[Path]
            List of source files to compile.
        
        output_path : Path
            Path where output file will be written.
        
        flags : Optional[List[str]], default=None
            Additional compiler flags to pass directly.
        
        defines : Optional[Dict[str, str]], default=None
            Preprocessor definitions (e.g., {'DEBUG': '1'} -> -DDEBUG=1).
        
        include_paths : Optional[List[Path]], default=None
            Additional include directories (-I flag).
        
        library_paths : Optional[List[Path]], default=None
            Additional library search paths (-L flag).
        
        libraries : Optional[List[str]], default=None
            Libraries to link (-l flag).
        
        link_type : str, default='shared'
            Output type: 'object', 'shared', 'static', 'executable'.
        
        optimization_level : Union[int, str], default=2
            Optimization level: 0, 1, 2, 3, 'fast', 'size'.
        
        debug : bool, default=False
            Include debug symbols (-g flag).
        
        language : str, default='c'
            Source language: 'c' or 'c++'.
        
        standard : Optional[str], default=None
            Language standard (e.g., 'c11', 'c++17', 'c++20').
        
        warnings : Union[bool, str], default=True
            Warning level: True/False, 'error', 'all', 'extra'.
        
        extra_objects : Optional[List[Path]], default=None
            Additional object files to link.
        
        ipo : bool, default=False
            Enable Interprocedural Optimization (-ipo).
        
        openmp : bool, default=False
            Enable OpenMP parallelization.
        
        cpu_dispatch : Optional[str], default=None
            CPU dispatch targets for -ax flag.
            Example: 'CORE-AVX512,CORE-AVX2,AVX,SSE4.2'
        
        mkl : Optional[str], default=None
            Intel MKL linkage: 'sequential', 'parallel', 'cluster'.
        
        tbb : bool, default=False
            Enable Intel Threading Building Blocks.
        
        vector_report : bool, default=False
            Generate detailed vectorization report.
        
        use_fast : bool, default=False
            Use -fast flag (aggressive optimization).

        Returns
        -------
        CompileResult
            Compilation result with success status, output path,
            compile time, warnings, errors, and other metadata.

        Raises
        ------
        None - Errors are captured in CompileResult.

        Examples
        --------
        >>> icc = ICCBackend()
        >>> result = icc.compile(
        ...     sources=[Path("matrix.c")],
        ...     output_path=Path("matrix.so"),
        ...     optimization_level=3,
        ...     ipo=True,
        ...     openmp=True,
        ...     mkl="parallel"
        ... )
        >>> if result.success:
        ...     print(f"Compiled successfully: {result.object_size} bytes")
        """
        import time

        start_time = time.time()

        # Select appropriate compiler (C or C++)
        compiler_exe = self.executable_path
        if language == "c++" and self.icpc_path:
            compiler_exe = self.icpc_path

        if not compiler_exe:
            return CompileResult(
                success=False,
                errors=["Intel compiler executable not found"],
                compile_time=time.time() - start_time,
            )

        # Build command
        cmd = [str(compiler_exe)]

        # Language standard
        if standard:
            cmd.append(f"-std={standard}")

        # Link type and code generation
        if link_type == "shared":
            cmd.extend(["-shared", "-fPIC"])
        elif link_type == "static":
            cmd.append("-static")
        elif link_type == "object":
            cmd.append("-c")

        # Optimization level
        if use_fast:
            cmd.append("-fast")
        elif isinstance(optimization_level, str):
            if optimization_level in self.OPTIMIZATION_FLAGS:
                cmd.append(self.OPTIMIZATION_FLAGS[optimization_level])
        else:
            cmd.append(f"-O{optimization_level}")

        # Interprocedural Optimization (IPO)
        if ipo:
            if self.check_flag_support("-ipo"):
                cmd.append("-ipo")

        # Debug symbols
        if debug:
            cmd.append("-g")

        # OpenMP parallelization
        if openmp:
            if self._is_classic:
                cmd.append("-qopenmp")
            else:
                cmd.append("-fiopenmp")

        # CPU dispatch for multiple architectures
        if cpu_dispatch:
            cmd.append(f"-ax{cpu_dispatch}")

        # Intel Math Kernel Library (MKL)
        if mkl and mkl in self.MKL_FLAGS:
            if self.check_flag_support(self.MKL_FLAGS[mkl]):
                cmd.append(self.MKL_FLAGS[mkl])

        # Intel Threading Building Blocks (TBB)
        if tbb:
            if self.check_flag_support("-tbb"):
                cmd.append("-tbb")

        # Vectorization report
        if vector_report:
            cmd.append("-qopt-report=5")
            cmd.append("-qopt-report-phase=vec")

        # Warning flags
        if warnings:
            if warnings == "error":
                cmd.append("-Werror")
            elif warnings == "all":
                cmd.append("-Wall")
            else:
                cmd.append("-Wall")  # Default warnings

        # Preprocessor definitions
        if defines:
            for name, value in defines.items():
                if value:
                    cmd.append(f"-D{name}={value}")
                else:
                    cmd.append(f"-D{name}")

        # Include directories
        for inc in (include_paths or []):
            cmd.append(f"-I{inc}")

        # Default include paths from compiler info
        for inc in self.info.include_paths:
            cmd.append(f"-I{inc}")

        # Additional flags
        if flags:
            cmd.extend(flags)

        # Default flags
        cmd.extend(self.info.default_flags)

        # Source files
        for src in sources:
            cmd.append(str(src))

        # Extra object files
        if extra_objects:
            cmd.extend(str(obj) for obj in extra_objects)

        # Output file
        cmd.extend(["-o", str(output_path)])

        # Library search paths
        if library_paths:
            for lib_path in library_paths:
                cmd.append(f"-L{lib_path}")

        # Libraries to link
        if libraries:
            for lib in libraries:
                cmd.append(f"-l{lib}")

        # Execute compilation
        try:
            result = self._run_command(cmd, capture_output=not self.verbose)

            compile_time = time.time() - start_time
            warnings_list, errors_list = self._parse_warnings_errors(result.stderr)

            if result.returncode == 0 and output_path.exists():
                object_size = output_path.stat().st_size
                return CompileResult(
                    success=True,
                    output_path=output_path,
                    compile_time=compile_time,
                    command=cmd,
                    return_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    warnings=warnings_list,
                    errors=errors_list,
                    object_size=object_size,
                )
            else:
                return CompileResult(
                    success=False,
                    compile_time=compile_time,
                    command=cmd,
                    return_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    warnings=warnings_list,
                    errors=errors_list,
                )

        except subprocess.TimeoutExpired as e:
            return CompileResult(
                success=False,
                compile_time=time.time() - start_time,
                command=cmd,
                errors=[f"Compilation timeout ({e.timeout}s): {str(e)}"],
            )
        except Exception as e:
            return CompileResult(
                success=False,
                compile_time=time.time() - start_time,
                command=cmd,
                errors=[f"Compilation error: {str(e)}"],
            )

    def preprocess(
        self,
        source: Path,
        output_path: Optional[Path] = None,
        defines: Optional[Dict[str, str]] = None,
        include_paths: Optional[List[Path]] = None,
    ) -> PreprocessResult:
        """
        Preprocess a source file using Intel compiler.

        Parameters
        ----------
        source : Path
            Source file to preprocess.
        
        output_path : Optional[Path], default=None
            Output file for preprocessed source. If None, output is captured.
        
        defines : Optional[Dict[str, str]], default=None
            Preprocessor definitions.
        
        include_paths : Optional[List[Path]], default=None
            Include directories.

        Returns
        -------
        PreprocessResult
            Preprocessing result with output content, macros, and includes.

        Examples
        --------
        >>> icc = ICCBackend()
        >>> result = icc.preprocess(
        ...     source=Path("main.c"),
        ...     defines={"VERSION": "1.0"}
        ... )
        >>> if result.success:
        ...     print(f"Macros found: {len(result.macros)}")
        """
        import time

        start_time = time.time()

        cmd = [str(self.executable_path), "-E", str(source)]

        # Preprocessor definitions
        if defines:
            for name, value in defines.items():
                if value:
                    cmd.append(f"-D{name}={value}")
                else:
                    cmd.append(f"-D{name}")

        # Include directories
        for inc in (include_paths or []):
            cmd.append(f"-I{inc}")

        # Output file
        if output_path:
            cmd.extend(["-o", str(output_path)])

        try:
            result = self._run_command(cmd, capture_output=not output_path)

            if result.returncode == 0:
                # Get output content
                output = result.stdout
                if output_path and output_path.exists():
                    with open(output_path, "r") as f:
                        output = f.read()

                # Extract macros and includes
                macros = self._extract_macros_from_preprocessed(output)
                includes = self._extract_includes_from_preprocessed(output)

                return PreprocessResult(
                    success=True,
                    output=output,
                    output_path=output_path,
                    macros=macros,
                    includes=includes,
                    compile_time=time.time() - start_time,
                )
            else:
                return PreprocessResult(
                    success=False,
                    output=result.stderr,
                    compile_time=time.time() - start_time,
                )

        except Exception as e:
            return PreprocessResult(
                success=False,
                output=str(e),
                compile_time=time.time() - start_time,
            )

    def _extract_macros_from_preprocessed(self, output: str) -> Dict[str, str]:
        """
        Extract macro definitions from preprocessed output.

        Parameters
        ----------
        output : str
            Preprocessed source code.

        Returns
        -------
        Dict[str, str]
            Dictionary of macro names to their values.
        """
        macros = {}
        pattern = re.compile(r'^#define\s+(\w+)(?:\s+(.+))?$', re.MULTILINE)

        for match in pattern.finditer(output):
            name = match.group(1)
            value = match.group(2) if match.group(2) else "1"
            macros[name] = value.strip()

        return macros

    def _extract_includes_from_preprocessed(self, output: str) -> List[Path]:
        """
        Extract included file paths from preprocessed output.

        Parameters
        ----------
        output : str
            Preprocessed source code.

        Returns
        -------
        List[Path]
            List of included file paths.
        """
        includes = []
        pattern = re.compile(r'^#\s+\d+\s+"([^"]+)"', re.MULTILINE)

        seen = set()
        for match in pattern.finditer(output):
            file_path = match.group(1)
            if file_path not in seen:
                seen.add(file_path)
                includes.append(Path(file_path))

        return includes

    # ========================================================================
    # UTILITY METHODS
    # ========================================================================

    def get_default_flags(self) -> List[str]:
        """
        Get default compiler flags.

        Returns
        -------
        List[str]
            Copy of the default flags list.
        """
        return self.info.default_flags.copy()

    def check_flag_support(self, flag: str) -> bool:
        """
        Check if a compiler flag is supported.

        Parameters
        ----------
        flag : str
            Compiler flag to check (e.g., '-ipo', '-qopenmp').

        Returns
        -------
        bool
            True if flag is accepted by the compiler.

        Notes
        -----
        Results are cached in _flag_support_cache to avoid redundant checks.
        """
        if flag in self._flag_support_cache:
            return self._flag_support_cache[flag]

        # Test flag with minimal compilation
        with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
            f.write("int main() { return 0; }")
            test_file = Path(f.name)

        try:
            cmd = [str(self.executable_path), "-c", str(test_file), flag]
            result = self._run_command(cmd, capture_output=True, timeout=10)
            supported = result.returncode == 0
        except Exception:
            supported = False
        finally:
            test_file.unlink(missing_ok=True)

        self._flag_support_cache[flag] = supported
        return supported

    def get_include_paths(self) -> List[Path]:
        """
        Get default include search paths.

        Returns
        -------
        List[Path]
            Copy of the include paths list.
        """
        return self.info.include_paths.copy()

    def get_library_paths(self) -> List[Path]:
        """
        Get default library search paths.

        Returns
        -------
        List[Path]
            Copy of the library paths list.
        """
        return self.info.library_paths.copy()

    def get_predefined_macros(self) -> Dict[str, str]:
        """
        Get predefined preprocessor macros.

        Returns
        -------
        Dict[str, str]
            Copy of the predefined macros dictionary.
        """
        return self.info.predefined_macros.copy()

    def get_simd_flags(self, level: str) -> List[str]:
        """
        Get SIMD flags for a specific instruction set level.

        Parameters
        ----------
        level : str
            SIMD level: 'auto', 'sse2', 'sse3', 'ssse3', 'sse4.1', 
            'sse4.2', 'avx', 'avx2', 'avx512'

        Returns
        -------
        List[str]
            List of compiler flags for the specified SIMD level.

        Examples
        --------
        >>> icc = ICCBackend()
        >>> flags = icc.get_simd_flags('avx2')
        >>> print(flags)  # ['-xCORE-AVX2']
        
        >>> flags = icc.get_simd_flags('auto')
        >>> # Returns best available based on detected features
        """
        flags = []

        if level == "auto":
            # Auto-detect best available SIMD level
            if self.info.has_feature(CompilerFeature.SIMD_AVX512):
                flags.append(self.SIMD_FLAGS["avx512"])
            elif self.info.has_feature(CompilerFeature.SIMD_AVX2):
                flags.append(self.SIMD_FLAGS["avx2"])
            elif self.info.has_feature(CompilerFeature.SIMD_AVX):
                flags.append(self.SIMD_FLAGS["avx"])
            elif self.info.has_feature(CompilerFeature.SIMD_SSE4_2):
                flags.append(self.SIMD_FLAGS["sse4.2"])
            elif self.info.has_feature(CompilerFeature.SIMD_SSE2):
                flags.append(self.SIMD_FLAGS["sse2"])
        elif level in self.SIMD_FLAGS:
            flags.append(self.SIMD_FLAGS[level])

        return flags

    def get_arch_flag(self, arch: str) -> str:
        """
        Get architecture-specific optimization flag.

        Parameters
        ----------
        arch : str
            Architecture name: 'native', 'sse2', 'sse3', 'ssse3', 
            'sse4.1', 'sse4.2', 'avx', 'avx2', 'avx512', 'mic'

        Returns
        -------
        str
            Compiler flag for the specified architecture.

        Examples
        --------
        >>> icc = ICCBackend()
        >>> flag = icc.get_arch_flag('native')  # Returns '-xHost'
        >>> flag = icc.get_arch_flag('avx2')    # Returns '-xCORE-AVX2'
        """
        return self.ARCH_FLAGS.get(arch, "")

    def is_classic(self) -> bool:
        """
        Check if using classic ICC compiler (not ICX).

        Returns
        -------
        bool
            True if using classic ICC, False for ICX or unknown.

        Notes
        -----
        Classic ICC versions are < 2021. ICX versions are 2021.1 and later.
        """
        return self._is_classic or False

    def get_intel_env_script(self) -> Optional[Path]:
        """
        Get path to Intel environment setup script.

        Returns
        -------
        Optional[Path]
            Path to setvars.sh/compilervars.sh if found, None otherwise.
        """
        return self._intel_env_script

    # ========================================================================
    # REPRESENTATION
    # ========================================================================

    def __repr__(self) -> str:
        """
        Get string representation of the backend.

        Returns
        -------
        str
            Human-readable representation including compiler type and version.
        """
        if self._info:
            compiler_type = "ICC" if self.is_classic() else "ICX"
            return f"<ICCBackend {compiler_type} {self.info.version}>"
        return "<ICCBackend (not initialized)>"