#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    MSVC COMPILER BACKEND
==================================

Microsoft Visual C++ (MSVC) compiler backend implementation with
comprehensive feature detection, Windows-specific optimizations,
and Visual Studio integration.

This module provides a complete interface to Microsoft Visual C++ compiler
with automatic detection of Visual Studio installations, environment setup,
and Windows SDK integration.

Key Features:
- Automatic Visual Studio installation detection (via vswhere)
- vcvarsall.bat environment setup for proper PATH/INCLUDE/LIB
- Windows SDK version detection and integration
- Support for x86, x64, ARM, and ARM64 targets
- MSVC version mapping (_MSC_VER to Visual Studio version)
- SIMD instruction set support (SSE, AVX, AVX2, AVX-512)
- OpenMP parallelization support
- Link-Time Code Generation (LTCG) / Whole Program Optimization
- Profile-Guided Optimization (PGO) support
- Address Sanitizer (ASan) support
- Spectre mitigation flags
- Control Flow Guard (CFG) support
- Runtime library selection (static/dynamic, debug/release)
"""

import os
import re
import subprocess
import tempfile
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


class MSVCBackend(CompilerBackend):
    """
    Microsoft Visual C++ (MSVC) compiler backend implementation.

    This class provides comprehensive support for MSVC compilers with
    automatic detection of Visual Studio installations, environment
    setup, and Windows SDK integration.

    Parameters
    ----------
    executable_path : Optional[Path], default=None
        Path to cl.exe executable. Auto-detected if None.
    
    vcvars_path : Optional[Path], default=None
        Path to vcvarsall.bat or vcvars64.bat. Auto-detected if None.
    
    vs_version : Optional[str], default=None
        Visual Studio version to use (e.g., '2022', '2019', '17.8').
    
    vs_edition : Optional[str], default=None
        Visual Studio edition ('Enterprise', 'Professional', 'Community', 'BuildTools').
    
    sdk_version : Optional[str], default=None
        Windows SDK version to use (e.g., '10.0.22621.0').
    
    platform : Optional[str], default=None
        Target platform ('x86', 'x64', 'arm', 'arm64'). Auto-detected if None.
    
    verbose : bool, default=False
        Enable verbose output for debugging.
    
    use_clang_cl : bool, default=False
        Use clang-cl (Clang with MSVC-compatible interface) instead of cl.exe.

    Attributes
    ----------
    executable_path : Optional[Path]
        Path to cl.exe or clang-cl.exe executable.
    
    vcvars_path : Optional[Path]
        Path to vcvars batch file.
    
    vs_version : Optional[str]
        Visual Studio version.
    
    vs_edition : Optional[str]
        Visual Studio edition.
    
    sdk_version : Optional[str]
        Windows SDK version.
    
    platform : str
        Target platform architecture.
    
    use_clang_cl : bool
        Whether using clang-cl.
    
    _feature_cache : Dict[str, bool]
        Cache for feature detection results.
    
    _flag_support_cache : Dict[str, bool]
        Cache for flag support checks.
    
    _vs_install_path : Optional[Path]
        Detected Visual Studio installation path.
    
    _sdk_path : Optional[Path]
        Detected Windows SDK path.
    
    _env_vars : Dict[str, str]
        Environment variables from vcvars.
    
    _msc_ver : Optional[int]
        Detected _MSC_VER value.
    
    _info : Optional[CompilerInfo]
        Cached compiler information to prevent infinite recursion.

    Examples
    --------
    >>> # Basic usage with auto-detection
    >>> msvc = MSVCBackend()
    >>> if msvc.is_available():
    ...     result = msvc.compile(
    ...         sources=[Path("main.c")],
    ...         output_path=Path("output.dll"),
    ...         optimization_level=2
    ...     )
    ...     print(f"Compiled in {result.compile_time:.2f}s")

    >>> # Specify Visual Studio version and platform
    >>> msvc = MSVCBackend(vs_version="2022", platform="x64")
    >>> result = msvc.compile(
    ...     sources=[Path("main.cpp")],
    ...     output_path=Path("output.dll"),
    ...     link_type="shared",
    ...     language="c++"
    ... )

    >>> # With OpenMP and AVX2 optimizations
    >>> result = msvc.compile(
    ...     sources=[Path("main.c")],
    ...     output_path=Path("output.dll"),
    ...     flags=["/openmp", "/arch:AVX2"],
    ...     optimization_level=2,
    ...     runtime="dynamic"
    ... )

    >>> # Using clang-cl (Clang with MSVC compatibility)
    >>> msvc = MSVCBackend(use_clang_cl=True)
    >>> result = msvc.compile(
    ...     sources=[Path("main.c")],
    ...     output_path=Path("output.dll")
    ... )

    >>> # Profile-Guided Optimization (PGO)
    >>> # Step 1: Instrument
    >>> msvc.compile(sources=[Path("app.c")], output_path=Path("app.exe"),
    ...              flags=["/GL", "/LTCG:PGINSTRUMENT"])
    >>> # Run app to generate .pgc files
    >>> # Step 2: Optimize
    >>> result = msvc.compile(sources=[Path("app.c")], output_path=Path("app_opt.exe"),
    ...                       flags=["/GL", "/LTCG:PGOPTIMIZE"])

    Notes
    -----
    Visual Studio Versions and _MSC_VER:
    - VS 2015 (14.0): _MSC_VER = 1900
    - VS 2017 (15.x): _MSC_VER = 1910-1916
    - VS 2019 (16.x): _MSC_VER = 1920-1929
    - VS 2022 (17.x): _MSC_VER = 1930-1940

    Key MSVC Flags:
    - `/O2`: Maximize speed optimization
    - `/Ox`: Full optimization (legacy)
    - `/GL`: Whole Program Optimization / LTCG
    - `/LTCG`: Link-Time Code Generation
    - `/MD`: Multithreaded DLL runtime
    - `/MT`: Static runtime
    - `/Zi`: PDB debug information
    - `/openmp`: OpenMP parallelization
    - `/arch:AVX2`: AVX2 instruction set
    - `/GS`: Buffer security check
    - `/guard:cf`: Control Flow Guard
    - `/Qspectre`: Spectre v1 mitigation
    """

    # ========================================================================
    # VERSION MAPPINGS
    # ========================================================================

    # MSVC version mapping (_MSC_VER to Visual Studio version and year)
    # Format: _MSC_VER -> (VS_Version, Year)
    MSC_VER_MAP: Dict[int, Tuple[str, int]] = {
        1200: ("6.0", 1998),      # Visual Studio 6.0
        1300: ("7.0", 2002),      # Visual Studio .NET 2002
        1310: ("7.1", 2003),      # Visual Studio .NET 2003
        1400: ("8.0", 2005),      # Visual Studio 2005
        1500: ("9.0", 2008),      # Visual Studio 2008
        1600: ("10.0", 2010),     # Visual Studio 2010
        1700: ("11.0", 2012),     # Visual Studio 2012
        1800: ("12.0", 2013),     # Visual Studio 2013
        1900: ("14.0", 2015),     # Visual Studio 2015
        1910: ("15.0", 2017),     # Visual Studio 2017 (15.0-15.3)
        1911: ("15.3", 2017),     # Visual Studio 2017 (15.3)
        1912: ("15.5", 2017),     # Visual Studio 2017 (15.5)
        1913: ("15.6", 2017),     # Visual Studio 2017 (15.6)
        1914: ("15.7", 2017),     # Visual Studio 2017 (15.7)
        1915: ("15.8", 2017),     # Visual Studio 2017 (15.8)
        1916: ("15.9", 2017),     # Visual Studio 2017 (15.9)
        1920: ("16.0", 2019),     # Visual Studio 2019 (16.0-16.1)
        1921: ("16.1", 2019),     # Visual Studio 2019 (16.1)
        1922: ("16.2", 2019),     # Visual Studio 2019 (16.2)
        1923: ("16.3", 2019),     # Visual Studio 2019 (16.3)
        1924: ("16.4", 2019),     # Visual Studio 2019 (16.4)
        1925: ("16.5", 2019),     # Visual Studio 2019 (16.5)
        1926: ("16.6", 2019),     # Visual Studio 2019 (16.6)
        1927: ("16.7", 2019),     # Visual Studio 2019 (16.7)
        1928: ("16.8", 2019),     # Visual Studio 2019 (16.8)
        1929: ("16.9", 2019),     # Visual Studio 2019 (16.9-16.11)
        1930: ("17.0", 2022),     # Visual Studio 2022 (17.0)
        1931: ("17.1", 2022),     # Visual Studio 2022 (17.1)
        1932: ("17.2", 2022),     # Visual Studio 2022 (17.2)
        1933: ("17.3", 2022),     # Visual Studio 2022 (17.3)
        1934: ("17.4", 2022),     # Visual Studio 2022 (17.4)
        1935: ("17.5", 2022),     # Visual Studio 2022 (17.5)
        1936: ("17.6", 2022),     # Visual Studio 2022 (17.6)
        1937: ("17.7", 2022),     # Visual Studio 2022 (17.7)
        1938: ("17.8", 2022),     # Visual Studio 2022 (17.8)
        1939: ("17.9", 2022),     # Visual Studio 2022 (17.9)
        1940: ("17.10", 2022),    # Visual Studio 2022 (17.10)
    }

    # Feature availability by _MSC_VER
    # Format: minimum _MSC_VER -> List[CompilerFeature]
    MSC_FEATURES: Dict[int, List[CompilerFeature]] = {
        1500: [CompilerFeature.CPP11],                              # VS 2008
        1600: [CompilerFeature.CPP11],                              # VS 2010
        1700: [CompilerFeature.CPP11],                              # VS 2012
        1800: [CompilerFeature.CPP11, CompilerFeature.CPP14],       # VS 2013
        1900: [CompilerFeature.C11, CompilerFeature.CPP11,          # VS 2015
               CompilerFeature.CPP14, CompilerFeature.CPP17],
        1910: [CompilerFeature.C11, CompilerFeature.CPP11,          # VS 2017
               CompilerFeature.CPP14, CompilerFeature.CPP17],
        1920: [CompilerFeature.C11, CompilerFeature.CPP11,          # VS 2019
               CompilerFeature.CPP14, CompilerFeature.CPP17,
               CompilerFeature.CPP20],
        1930: [CompilerFeature.C11, CompilerFeature.C17,            # VS 2022
               CompilerFeature.CPP11, CompilerFeature.CPP14,
               CompilerFeature.CPP17, CompilerFeature.CPP20,
               CompilerFeature.CPP23],
    }

    # ========================================================================
    # FLAG MAPPINGS
    # ========================================================================

    # SIMD instruction set flags for MSVC
    SIMD_FLAGS: Dict[str, str] = {
        "sse": "/arch:SSE",
        "sse2": "/arch:SSE2",
        "avx": "/arch:AVX",
        "avx2": "/arch:AVX2",
        "avx512": "/arch:AVX512",
    }

    # Optimization level flags
    OPTIMIZATION_FLAGS: Dict[str, str] = {
        "0": "/Od",      # Disable optimization (default for debug)
        "1": "/O1",      # Minimize size
        "2": "/O2",      # Maximize speed (default for release)
        "x": "/Ox",      # Full optimization (legacy, similar to /O2)
        "s": "/Os",      # Favor small code
        "t": "/Ot",      # Favor fast code
    }

    # Warning level flags
    WARNING_FLAGS: Dict[str, str] = {
        "0": "/W0",      # No warnings
        "1": "/W1",      # Level 1 (severe warnings)
        "2": "/W2",      # Level 2 (significant warnings)
        "3": "/W3",      # Level 3 (production quality - default)
        "4": "/W4",      # Level 4 (all warnings)
        "all": "/Wall",  # All warnings including disabled
        "error": "/WX",  # Treat warnings as errors
    }

    # Debug information flags
    DEBUG_FLAGS: Dict[str, str] = {
        "none": "",
        "full": "/Zi",           # Full PDB debug information
        "fastlink": "/DEBUG:FASTLINK",  # Fast PDB linking
        "fullbuild": "/DEBUG:FULL",     # Full PDB (slower)
    }

    # Runtime library flags
    RUNTIME_FLAGS: Dict[str, str] = {
        "static": "/MT",              # Static CRT (release)
        "static-debug": "/MTd",       # Static CRT (debug)
        "dynamic": "/MD",             # Dynamic CRT (release)
        "dynamic-debug": "/MDd",      # Dynamic CRT (debug)
    }

    # Language standard flags
    STANDARD_FLAGS: Dict[str, str] = {
        "c11": "/std:c11",
        "c17": "/std:c17",
        "c++14": "/std:c++14",
        "c++17": "/std:c++17",
        "c++20": "/std:c++20",
        "c++latest": "/std:c++latest",
    }

    # Security and mitigation flags
    SECURITY_FLAGS: List[str] = [
        "/GS",           # Buffer security check
        "/sdl",          # Security Development Lifecycle checks
        "/guard:cf",     # Control Flow Guard
    ]

    # Spectre mitigation flags
    SPECTRE_FLAGS: Dict[str, str] = {
        "none": "",
        "v1": "/Qspectre",           # Spectre v1 mitigation
        "v2": "/Qspectre-load",      # Spectre v2 (load) mitigation
        "all": "/Qspectre /Qspectre-load",  # All mitigations
    }

    # Whole Program Optimization / LTCG flags
    LTCG_FLAGS: Dict[str, str] = {
        "none": "",
        "full": "/GL /LTCG",         # Full LTCG
        "incremental": "/GL /LTCG:INCREMENTAL",  # Incremental LTCG
        "pgo_instrument": "/GL /LTCG:PGINSTRUMENT",  # PGO instrument
        "pgo_optimize": "/GL /LTCG:PGOPTIMIZE",      # PGO optimize
        "pgo_update": "/GL /LTCG:PGUPDATE",          # PGO update
    }

    # ========================================================================
    # INITIALIZATION
    # ========================================================================

    def __init__(
        self,
        executable_path: Optional[Path] = None,
        vcvars_path: Optional[Path] = None,
        vs_version: Optional[str] = None,
        vs_edition: Optional[str] = None,
        sdk_version: Optional[str] = None,
        platform: Optional[str] = None,
        verbose: bool = False,
        use_clang_cl: bool = False,
    ):
        """
        Initialize MSVC compiler backend.

        Parameters
        ----------
        executable_path : Optional[Path], default=None
            Explicit path to cl.exe/clang-cl.exe. Auto-detected if None.
        
        vcvars_path : Optional[Path], default=None
            Path to vcvars batch file. Auto-detected from VS installation.
        
        vs_version : Optional[str], default=None
            Visual Studio version to use (e.g., '2022', '2019', '17.8').
        
        vs_edition : Optional[str], default=None
            Visual Studio edition ('Enterprise', 'Professional', 'Community').
        
        sdk_version : Optional[str], default=None
            Windows SDK version to use.
        
        platform : Optional[str], default=None
            Target platform ('x86', 'x64', 'arm', 'arm64').
        
        verbose : bool, default=False
            Enable verbose output for debugging.
        
        use_clang_cl : bool, default=False
            Use clang-cl instead of cl.exe.
        """
        super().__init__(executable_path, None, verbose)
        self.vcvars_path = vcvars_path
        self.vs_version = vs_version
        self.vs_edition = vs_edition
        self.sdk_version = sdk_version
        self.platform = platform or self._detect_host_platform()
        self.use_clang_cl = use_clang_cl

        self._feature_cache: Dict[str, bool] = {}
        self._flag_support_cache: Dict[str, bool] = {}
        self._vs_install_path: Optional[Path] = None
        self._sdk_path: Optional[Path] = None
        self._env_vars: Dict[str, str] = {}
        self._msc_ver: Optional[int] = None
        self._info: Optional[CompilerInfo] = None  # Cache for compiler info

        # Setup environment if compiler is available
        if self.is_available():
            self._setup_environment()

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
            'clang-cl' if using clang-cl, otherwise 'cl'.
        """
        return "clang-cl" if self.use_clang_cl else "cl"

    @property
    def family(self) -> CompilerFamily:
        """
        Get compiler family identifier.

        Returns
        -------
        CompilerFamily
            CompilerFamily.LLVM for clang-cl, CompilerFamily.MICROSOFT for MSVC.
        """
        return CompilerFamily.LLVM if self.use_clang_cl else CompilerFamily.MICROSOFT

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
            If compiler cannot be detected.
        """
        if self._info is None:
            self._info = self._detect_info()
        return self._info

    # ========================================================================
    # PLATFORM DETECTION
    # ========================================================================

    def _detect_host_platform(self) -> str:
        """
        Detect host platform architecture.

        Returns
        -------
        str
            Platform identifier: 'x86', 'x64', 'arm', or 'arm64'.

        Notes
        -----
        Uses Python's platform module and struct to determine
        whether running in 32-bit or 64-bit mode.
        """
        import platform
        import struct

        machine = platform.machine().lower()

        # Map platform machine names to MSVC platform names
        arch_map = {
            "amd64": "x64",
            "x86_64": "x64",
            "x64": "x64",
            "x86": "x86",
            "i386": "x86",
            "i686": "x86",
            "arm64": "arm64",
            "aarch64": "arm64",
            "arm": "arm",
        }

        if machine in arch_map:
            return arch_map[machine]

        # Fallback: check Python bitness
        return "x64" if struct.calcsize("P") == 8 else "x86"

    # ========================================================================
    # VISUAL STUDIO DETECTION
    # ========================================================================

    def _find_vs_installation(self) -> Optional[Path]:
        """
        Find Visual Studio installation using vswhere or common paths.

        Returns
        -------
        Optional[Path]
            Path to Visual Studio installation root, or None if not found.

        Notes
        -----
        Uses Microsoft's vswhere.exe (VS 2017+) for reliable detection.
        Falls back to checking common installation paths for older versions.
        """
        if self._vs_install_path:
            return self._vs_install_path

        # Try vswhere (Visual Studio 2017 and later)
        vswhere_paths = [
            Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) /
            "Microsoft Visual Studio" / "Installer" / "vswhere.exe",
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) /
            "Microsoft Visual Studio" / "Installer" / "vswhere.exe",
        ]

        for vswhere in vswhere_paths:
            if vswhere.exists():
                try:
                    args = [str(vswhere), "-latest", "-property", "installationPath"]
                    if self.vs_version:
                        args = [str(vswhere), "-version", self.vs_version,
                               "-property", "installationPath"]
                    if self.vs_edition:
                        args.extend(["-products", f"Microsoft.VisualStudio.Product.{self.vs_edition}"])

                    result = subprocess.run(
                        args,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

                    if result.returncode == 0 and result.stdout.strip():
                        path = Path(result.stdout.strip())
                        if path.exists():
                            self._vs_install_path = path
                            return path
                except Exception:
                    pass

        # Fallback: Check common installation paths
        common_paths = [
            Path("C:\\Program Files\\Microsoft Visual Studio\\2022"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2022"),
            Path("C:\\Program Files\\Microsoft Visual Studio\\2019"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2019"),
            Path("C:\\Program Files\\Microsoft Visual Studio\\2017"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2017"),
        ]

        for base in common_paths:
            if base.exists():
                # Check editions in order of preference
                for edition in ["Enterprise", "Professional", "Community", "BuildTools"]:
                    path = base / edition
                    if path.exists():
                        self._vs_install_path = path
                        return path

        return None

    def _find_vcvars(self) -> Optional[Path]:
        """
        Find vcvars batch file for environment setup.

        Returns
        -------
        Optional[Path]
            Path to vcvars batch file, or None if not found.

        Notes
        -----
        Searches for vcvarsall.bat or platform-specific vcvars*.bat
        in the detected Visual Studio installation.
        """
        if self.vcvars_path and self.vcvars_path.exists():
            return self.vcvars_path

        vs_path = self._find_vs_installation()
        if not vs_path:
            return None

        # Try platform-specific vcvars first
        vcvars_candidates = [
            vs_path / "VC" / "Auxiliary" / "Build" / f"vcvars{self.platform}.bat",
            vs_path / "VC" / f"vcvars{self.platform}.bat",
            vs_path / "VC" / "bin" / f"vcvars{self.platform}.bat",
        ]

        for candidate in vcvars_candidates:
            if candidate.exists():
                return candidate

        # Try vcvarsall.bat (supports all platforms)
        vcvarsall = vs_path / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
        if vcvarsall.exists():
            return vcvarsall

        return None

    def _find_sdk_path(self) -> Optional[Path]:
        """
        Find Windows SDK installation path.

        Returns
        -------
        Optional[Path]
            Path to Windows SDK root, or None if not found.

        Notes
        -----
        Checks environment variables and common installation paths.
        """
        if self._sdk_path:
            return self._sdk_path

        # Check environment variable
        if "WindowsSdkDir" in self._env_vars:
            self._sdk_path = Path(self._env_vars["WindowsSdkDir"])
            return self._sdk_path

        # Common installation paths
        common_paths = [
            Path("C:\\Program Files (x86)\\Windows Kits\\10"),
            Path("C:\\Program Files\\Windows Kits\\10"),
        ]

        for path in common_paths:
            if path.exists():
                self._sdk_path = path
                return path

        return None

    def _get_sdk_version_str(self) -> str:
        """
        Get Windows SDK version string.

        Returns
        -------
        str
            SDK version string (e.g., '10.0.22621.0').

        Notes
        -----
        Uses user-specified version if provided, otherwise finds
        the latest installed version.
        """
        if self.sdk_version:
            return self.sdk_version

        sdk_path = self._find_sdk_path()
        if sdk_path:
            include_dir = sdk_path / "Include"
            if include_dir.exists():
                versions = sorted(
                    [d.name for d in include_dir.iterdir() if d.is_dir()],
                    reverse=True
                )
                if versions:
                    return versions[0]

        return "10.0.22621.0"  # Windows 11 SDK default

    # ========================================================================
    # ENVIRONMENT SETUP
    # ========================================================================

    def _setup_environment(self) -> bool:
        """
        Setup MSVC compiler environment variables.

        This method runs vcvars batch file and captures the environment
        variables (PATH, INCLUDE, LIB, etc.) for use in compilation.

        Returns
        -------
        bool
            True if environment was set up successfully, False otherwise.

        Notes
        -----
        Creates a temporary batch script that calls vcvars and outputs
        all environment variables, then parses the output.
        """
        if self._env_vars:
            return True

        vcvars = self._find_vcvars()
        if not vcvars:
            return False

        try:
            # Create temporary batch script to capture environment
            with tempfile.NamedTemporaryFile(suffix=".bat", mode="w", delete=False) as f:
                f.write("@echo off\n")
                f.write(f'call "{vcvars}" {self.platform}\n')
                f.write("set\n")  # Output all environment variables
                batch_file = Path(f.name)

            # Run batch file and capture output
            result = subprocess.run(
                [str(batch_file)],
                capture_output=True,
                text=True,
                shell=True,
                timeout=60,
            )

            # Parse environment variables
            for line in result.stdout.split("\n"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    self._env_vars[key.strip()] = value.strip()

            # Clean up
            batch_file.unlink()

            # Update PATH for compiler executable
            if "PATH" in self._env_vars:
                os.environ["PATH"] = self._env_vars["PATH"]

            # Find cl.exe in PATH
            if not self.executable_path:
                import shutil
                exe_name = "clang-cl.exe" if self.use_clang_cl else "cl.exe"
                cl_path = shutil.which(exe_name)
                if cl_path:
                    self.executable_path = Path(cl_path)

            return True

        except Exception as e:
            if self.verbose:
                import logging
                logging.getLogger(__name__).warning(f"Failed to setup MSVC environment: {e}")
            return False

    # ========================================================================
    # COMPILER INFORMATION DETECTION
    # ========================================================================

    def _detect_info(self) -> CompilerInfo:
        """
        Detect comprehensive MSVC compiler information.

        This method performs complete compiler detection including:
        - Executable location and version parsing
        - _MSC_VER value detection
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
            If compiler environment cannot be set up or executable not found.

        Notes
        -----
        This method is called only once due to lazy loading via the
        `info` property, preventing infinite recursion.
        """
        # Setup Visual Studio environment
        if not self._setup_environment():
            raise RuntimeError("Could not setup MSVC environment. "
                             "Please ensure Visual Studio is installed.")

        # Find executable if not already set
        if not self.executable_path:
            exe = self._find_executable()
            if exe:
                self.executable_path = exe

        if not self.executable_path:
            raise RuntimeError("MSVC compiler (cl.exe) not found. "
                             "Please ensure Visual Studio is installed and vcvars is run.")

        # Get version information
        version_info = self._get_version_info()

        # Get target architecture
        target_triple = self._get_target_info()

        # Detect features (pass version info to avoid recursion)
        features = self._detect_features(version_info)

        # Get default flags
        default_flags = self._get_default_flags_internal()

        # Get include and library paths
        include_paths = self._detect_include_paths()
        library_paths = self._detect_library_paths()

        # Get predefined macros and supported flags
        predefined_macros = self._detect_predefined_macros()
        supported_flags = self._detect_supported_flags()

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
        Get MSVC compiler version information.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - 'version': string version (e.g., '19.38.33130')
            - 'major': major version number (int)
            - 'minor': minor version number (int)
            - 'patch': patch version number (int)

        Notes
        -----
        Version information is obtained from environment variables
        (VSCMD_VER) or by running cl.exe and parsing output.
        """
        # Try to get version from environment (vcvars)
        if "VSCMD_VER" in self._env_vars:
            ver = self._env_vars["VSCMD_VER"]
            parts = ver.split(".")
            return {
                "version": ver,
                "major": int(parts[0]) if len(parts) > 0 else 0,
                "minor": int(parts[1]) if len(parts) > 1 else 0,
                "patch": int(parts[2]) if len(parts) > 2 else 0,
            }

        # Try running cl.exe with no arguments
        try:
            result = self._run_command(
                [str(self.executable_path)],
                capture_output=True,
                timeout=10,
            )

            # Pattern for MSVC version in output
            # Example: "Microsoft (R) C/C++ Optimizing Compiler Version 19.38.33130 for x64"
            pattern = re.compile(
                r"(?:Microsoft\s*\(R\)\s*C/C\+\+\s*Optimizing\s*Compiler\s*Version\s*)(\d+)\.(\d+)\.(\d+)",
                re.IGNORECASE
            )

            match = pattern.search(result.stdout + result.stderr)
            if match:
                return {
                    "version": f"{match.group(1)}.{match.group(2)}.{match.group(3)}",
                    "major": int(match.group(1)),
                    "minor": int(match.group(2)),
                    "patch": int(match.group(3)),
                }

        except Exception:
            pass

        # Fallback to unknown
        return {"version": "unknown", "major": 0, "minor": 0, "patch": 0}

    def _get_target_info(self) -> str:
        """
        Get target architecture triple.

        Returns
        -------
        str
            Target triple in format: {arch}-pc-windows-msvc
            Examples: 'x86_64-pc-windows-msvc', 'i686-pc-windows-msvc'
        """
        arch_map = {
            "x86": "i686-pc-windows-msvc",
            "x64": "x86_64-pc-windows-msvc",
            "arm": "arm-pc-windows-msvc",
            "arm64": "aarch64-pc-windows-msvc",
        }
        return arch_map.get(self.platform, "unknown-windows-msvc")

    def _find_executable(self) -> Optional[Path]:
        """
        Find compiler executable in PATH.

        Returns
        -------
        Optional[Path]
            Path to compiler executable, or None if not found.
        """
        import shutil

        exe_name = "clang-cl.exe" if self.use_clang_cl else "cl.exe"
        path = shutil.which(exe_name)
        if path:
            return Path(path)
        return None

    # ========================================================================
    # FEATURE DETECTION
    # ========================================================================

    def _detect_features(self, version_info: Dict[str, Any]) -> CompilerFeature:
        """
        Detect supported MSVC compiler features.

        Parameters
        ----------
        version_info : Dict[str, Any]
            Version information (reserved for future use).

        Returns
        -------
        CompilerFeature
            Bitmask of supported compiler features.

        Notes
        -----
        Features are detected based on:
        1. _MSC_VER value from predefined macros
        2. Runtime compilation tests for SIMD support
        3. Flag support checks for OpenMP, LTCG, PGO, ASan

        This method does NOT use self.info to avoid infinite recursion.
        """
        features = CompilerFeature.NONE

        # Get _MSC_VER from predefined macros
        macros = self._detect_predefined_macros()
        if "_MSC_VER" in macros:
            self._msc_ver = int(macros["_MSC_VER"])

            # Add features based on _MSC_VER (sorted for correct ordering)
            for min_ver, feature_list in sorted(self.MSC_FEATURES.items()):
                if self._msc_ver >= min_ver:
                    for feature in feature_list:
                        features |= feature

        # Detect SIMD support via runtime compilation tests
        features |= self._detect_simd_features()

        # Detect OpenMP support
        if self.check_flag_support("/openmp"):
            features |= CompilerFeature.OPENMP

        # Detect LTCG (Link-Time Code Generation) support
        if self.check_flag_support("/GL") and self.check_flag_support("/LTCG"):
            features |= CompilerFeature.LTO

        # Detect PGO (Profile-Guided Optimization) support
        if (self.check_flag_support("/GL") and 
            self.check_flag_support("/LTCG:PGINSTRUMENT")):
            features |= CompilerFeature.PGO

        # Detect Address Sanitizer (VS 2019 16.9+)
        if self._msc_ver and self._msc_ver >= 1929:
            if self.check_flag_support("/fsanitize=address"):
                features |= CompilerFeature.SANITIZE_ADDRESS

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
                ("/arch:SSE2", CompilerFeature.SIMD_SSE2),
                ("/arch:AVX", CompilerFeature.SIMD_AVX),
                ("/arch:AVX2", CompilerFeature.SIMD_AVX2),
                ("/arch:AVX512", CompilerFeature.SIMD_AVX512),
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
        speed up testing. Environment variables are set from vcvars.
        """
        try:
            # Create temporary output file
            with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
                output = Path(f.name)

            # Build and execute compilation command
            cmd = [str(self.executable_path), "/c", str(source), f"/Fo{output}"] + flags

            env = os.environ.copy()
            env.update(self._env_vars)

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10,
                env=env,
            )

            # Clean up and return result
            output.unlink(missing_ok=True)
            return result.returncode == 0

        except (subprocess.SubprocessError, OSError):
            return False

    # ========================================================================
    # FLAG AND PATH DETECTION
    # ========================================================================

    def _get_default_flags_internal(self) -> List[str]:
        """
        Get default compiler flags.

        Returns
        -------
        List[str]
            List of default compiler flags.

        Notes
        -----
        Default flags include:
        - /nologo: Suppress copyright banner
        - /MD: Multithreaded DLL runtime
        - Windows platform defines
        - CRT security warnings disabled (for Python C API compatibility)
        """
        flags = [
            "/nologo",           # Suppress copyright banner
            "/MD",               # Multithreaded DLL runtime
            "/DWIN32",           # Define WIN32
            "/D_WINDOWS",        # Define _WINDOWS
            "/D_CRT_SECURE_NO_WARNINGS",  # Disable CRT security warnings
        ]

        # Platform-specific defines
        if self.platform == "x64":
            flags.append("/D_WIN64")
            flags.append("/D_WIN32")

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
        Uses INCLUDE environment variable from vcvars and adds
        Visual Studio and Windows SDK include directories.
        """
        include_paths = []

        # Use environment variable from vcvars
        if "INCLUDE" in self._env_vars:
            for path in self._env_vars["INCLUDE"].split(";"):
                p = Path(path)
                if p.exists():
                    include_paths.append(p)

        # Check Visual Studio installation
        vs_path = self._find_vs_installation()
        if vs_path:
            vc_tools = vs_path / "VC" / "Tools" / "MSVC"
            if vc_tools.exists():
                versions = sorted(vc_tools.iterdir(), reverse=True)
                if versions:
                    include = versions[0] / "include"
                    if include.exists():
                        include_paths.append(include)

        # Check Windows SDK
        sdk_path = self._find_sdk_path()
        if sdk_path:
            sdk_include = sdk_path / "Include" / self._get_sdk_version_str()
            if sdk_include.exists():
                include_paths.append(sdk_include)               # root
                include_paths.append(sdk_include / "ucrt")      # UCRT
                include_paths.append(sdk_include / "shared")    # shared headers
                include_paths.append(sdk_include / "um")        # user mode
                include_paths.append(sdk_include / "winrt")     # WinRT

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
        Uses LIB environment variable from vcvars and adds
        Visual Studio and Windows SDK library directories.
        """
        library_paths = []

        # Use environment variable from vcvars
        if "LIB" in self._env_vars:
            for path in self._env_vars["LIB"].split(";"):
                p = Path(path)
                if p.exists():
                    library_paths.append(p)

        # Check Visual Studio installation
        vs_path = self._find_vs_installation()
        if vs_path:
            vc_tools = vs_path / "VC" / "Tools" / "MSVC"
            if vc_tools.exists():
                versions = sorted(vc_tools.iterdir(), reverse=True)
                if versions:
                    lib = versions[0] / "lib" / self.platform
                    if lib.exists():
                        library_paths.append(lib)

        # Check Windows SDK
        sdk_path = self._find_sdk_path()
        if sdk_path:
            sdk_lib = sdk_path / "Lib" / self._get_sdk_version_str()
            if sdk_lib.exists():
                um_lib = sdk_lib / "um" / self.platform
                if um_lib.exists():
                    library_paths.append(um_lib)
                ucrt_lib = sdk_lib / "ucrt" / self.platform
                if ucrt_lib.exists():
                    library_paths.append(ucrt_lib)

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
        Uses /EP /P flags to preprocess to a file, then parses #define lines.
        This is more reliable than parsing compiler output directly.
        """
        macros = {}

        try:
            # Create temporary output file
            with tempfile.NamedTemporaryFile(suffix=".i", mode="w+", delete=False) as f:
                output_file = Path(f.name)

            # Preprocess with /EP (no line markers) and /P (write to file)
            cmd = [str(self.executable_path), "/EP", "/P", f"/Fi{output_file}", "nul"]

            env = os.environ.copy()
            env.update(self._env_vars)

            result = self._run_command(cmd, env=env, timeout=30)

            if output_file.exists():
                with open(output_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                # Parse #define lines
                pattern = re.compile(r'^#define\s+(\w+)(?:\s+(.+))?$', re.MULTILINE)
                for match in pattern.finditer(content):
                    name = match.group(1)
                    value = match.group(2) if match.group(2) else "1"
                    macros[name] = value.strip()

                output_file.unlink()

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
        Tests a comprehensive list of common MSVC compiler flags
        and returns only those that are accepted.
        """
        supported = set()

        # List of common MSVC compiler flags to test
        common_flags = [
            # Optimization flags
            "/O1", "/O2", "/Ox", "/Os", "/Ot", "/Od",
            # Warning flags
            "/W0", "/W1", "/W2", "/W3", "/W4", "/Wall", "/WX",
            # Debug flags
            "/Zi", "/ZI", "/Z7",
            # Runtime flags
            "/MT", "/MTd", "/MD", "/MDd",
            # LTCG flags
            "/GL", "/LTCG", "/LTCG:INCREMENTAL",
            # OpenMP
            "/openmp",
            # Language standards
            "/std:c11", "/std:c17",
            "/std:c++14", "/std:c++17", "/std:c++20", "/std:c++latest",
            # SIMD flags
            "/arch:SSE", "/arch:SSE2", "/arch:AVX", "/arch:AVX2", "/arch:AVX512",
            # Security flags
            "/GS", "/sdl", "/guard:cf",
            # Spectre mitigation
            "/Qspectre", "/Qspectre-load",
            # Sanitizers
            "/fsanitize=address",
            # Build flags
            "/MP",      # Multi-process compilation
            "/bigobj",  # Extended object format
            "/Gy",      # Function-level linking
            "/Gr",      # __fastcall
            "/Gz",      # __stdcall
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
        Check if MSVC compiler is available and functional.

        Returns
        -------
        bool
            True if compiler is available, False otherwise.

        Notes
        -----
        This method does not rely on lazy-loaded info property to
        avoid recursion during initial detection.
        """
        try:
            # Try to setup environment first
            if not self._env_vars:
                if not self._setup_environment():
                    return False

            # Find executable
            exe = self._find_executable()
            if not exe:
                return False

            # Test basic functionality
            result = self._run_command(
                [str(exe)],
                capture_output=True,
                timeout=5,
            )
            # MSVC returns non-zero for no input, but that's expected
            return "Microsoft" in result.stdout + result.stderr

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
        warnings: Union[bool, str] = "3",
        extra_objects: Optional[List[Path]] = None,
        runtime: str = "dynamic",
        pdb_path: Optional[Path] = None,
        manifest: bool = True,
        security: bool = True,
        spectre: Optional[str] = None,
        ltcg: Optional[str] = None,
    ) -> CompileResult:
        """
        Compile source files using MSVC.

        Parameters
        ----------
        sources : List[Path]
            List of source files to compile.
        
        output_path : Path
            Path where output file will be written.
        
        flags : Optional[List[str]], default=None
            Additional compiler flags to pass directly.
        
        defines : Optional[Dict[str, str]], default=None
            Preprocessor definitions (/D flag).
        
        include_paths : Optional[List[Path]], default=None
            Additional include directories (/I flag).
        
        library_paths : Optional[List[Path]], default=None
            Additional library search paths (/LIBPATH flag).
        
        libraries : Optional[List[str]], default=None
            Libraries to link (appends .lib automatically).
        
        link_type : str, default='shared'
            Output type: 'object', 'shared', 'static', 'executable'.
        
        optimization_level : Union[int, str], default=2
            Optimization level: 0, 1, 2, 'x', 's', 't'.
        
        debug : bool, default=False
            Include debug symbols (/Zi flag).
        
        language : str, default='c'
            Source language ('c' or 'c++').
        
        standard : Optional[str], default=None
            Language standard (/std:c++17, /std:c11, etc.).
        
        warnings : Union[bool, str], default='3'
            Warning level: '0', '1', '2', '3', '4', 'all', 'error'.
        
        extra_objects : Optional[List[Path]], default=None
            Additional object files to link.
        
        runtime : str, default='dynamic'
            Runtime library: 'static', 'static-debug', 'dynamic', 'dynamic-debug'.
        
        pdb_path : Optional[Path], default=None
            Path for PDB debug file.
        
        manifest : bool, default=True
            Generate manifest file (/MANIFEST).
        
        security : bool, default=True
            Enable security checks (/GS, /sdl, /guard:cf).
        
        spectre : Optional[str], default=None
            Spectre mitigation: 'v1', 'v2', 'all'.
        
        ltcg : Optional[str], default=None
            LTCG mode: 'full', 'incremental', 'pgo_instrument', etc.

        Returns
        -------
        CompileResult
            Compilation result with success status, output path,
            compile time, warnings, errors, and other metadata.

        Examples
        --------
        >>> msvc = MSVCBackend()
        >>> result = msvc.compile(
        ...     sources=[Path("matrix.c")],
        ...     output_path=Path("matrix.dll"),
        ...     optimization_level=2,
        ...     openmp=True,
        ...     simd="avx2"
        ... )
        >>> if result.success:
        ...     print(f"Compiled: {result.object_size} bytes")
        """
        import time

        start_time = time.time()

        if not self.executable_path:
            return CompileResult(
                success=False,
                errors=["MSVC compiler (cl.exe) not found"],
                compile_time=time.time() - start_time,
            )

        # Build command
        cmd = [str(self.executable_path), "/nologo"]

        # Language standard
        if standard and standard in self.STANDARD_FLAGS:
            cmd.append(self.STANDARD_FLAGS[standard])

        # Link type
        if link_type == "shared":
            cmd.append("/LD")
        elif link_type == "object":
            cmd.append("/c")

        # Optimization level
        opt_str = str(optimization_level)
        if opt_str in self.OPTIMIZATION_FLAGS:
            cmd.append(self.OPTIMIZATION_FLAGS[opt_str])
        else:
            cmd.append("/O2")

        # Runtime library
        if runtime in self.RUNTIME_FLAGS:
            cmd.append(self.RUNTIME_FLAGS[runtime])
        else:
            cmd.append("/MD")

        # Debug symbols
        if debug:
            cmd.append("/Zi")
            if pdb_path:
                cmd.append(f"/Fd{pdb_path}")
            else:
                cmd.append(f"/Fd{output_path.with_suffix('.pdb')}")
        else:
            cmd.append("/DNDEBUG")

        # Warning level
        if warnings:
            warn_str = str(warnings)
            if warn_str in self.WARNING_FLAGS:
                cmd.append(self.WARNING_FLAGS[warn_str])
            elif warnings == "error":
                cmd.append("/WX")
            else:
                cmd.append("/W3")

        # Security checks
        if security:
            for flag in self.SECURITY_FLAGS:
                if self.check_flag_support(flag):
                    cmd.append(flag)

        # Spectre mitigation
        if spectre and spectre in self.SPECTRE_FLAGS:
            flag = self.SPECTRE_FLAGS[spectre]
            if flag and self.check_flag_support(flag.split()[0]):
                cmd.append(flag)

        # LTCG / Whole Program Optimization
        if ltcg and ltcg in self.LTCG_FLAGS:
            flag = self.LTCG_FLAGS[ltcg]
            if flag:
                for f in flag.split():
                    if self.check_flag_support(f):
                        cmd.append(f)

        # Preprocessor definitions
        if defines:
            for name, value in defines.items():
                if value:
                    cmd.append(f"/D{name}={value}")
                else:
                    cmd.append(f"/D{name}")

        # Include directories
        for inc in (include_paths or []):
            cmd.append(f"/I{inc}")

        # Default include paths from compiler info
        for inc in self.info.include_paths:
            cmd.append(f"/I{inc}")

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
        if link_type == "object":
            cmd.append(f"/Fo{output_path}")
        else:
            cmd.append(f"/Fe{output_path}")

        # Library search paths
        if library_paths:
            for lib_path in library_paths:
                cmd.append(f"/LIBPATH:{lib_path}")

        # Libraries to link
        if libraries:
            for lib in libraries:
                if not lib.endswith(".lib"):
                    cmd.append(f"{lib}.lib")
                else:
                    cmd.append(lib)

        # Linker options
        if link_type != "object":
            cmd.append("/link")
            if not debug:
                cmd.append("/OPT:REF")
                cmd.append("/OPT:ICF")
            if manifest:
                cmd.append("/MANIFEST")

        # Execute compilation
        try:
            # Set environment from vcvars
            env = os.environ.copy()
            env.update(self._env_vars)

            if self.verbose:
                import logging
                logging.getLogger(__name__).debug(f"Running: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=not self.verbose,
                text=True,
                timeout=300,
                env=env,
            )

            compile_time = time.time() - start_time
            warnings_list, errors_list = self._parse_msvc_output(result.stdout + result.stderr)

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

    def _parse_msvc_output(self, output: str) -> Tuple[List[str], List[str]]:
        """
        Parse MSVC compiler output for warnings and errors.

        Parameters
        ----------
        output : str
            Compiler stdout/stderr output.

        Returns
        -------
        Tuple[List[str], List[str]]
            Tuple of (warnings_list, errors_list).

        Notes
        -----
        MSVC warnings follow pattern: "warning C####: message"
        MSVC errors follow pattern: "error C####: message" or "fatal error C####: message"
        """
        warnings = []
        errors = []

        # MSVC patterns
        warning_pattern = re.compile(r"warning C\d+:", re.IGNORECASE)
        error_pattern = re.compile(r"error C\d+:", re.IGNORECASE)
        fatal_pattern = re.compile(r"fatal error C\d+:", re.IGNORECASE)

        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue

            if fatal_pattern.search(line):
                errors.append(line)
            elif error_pattern.search(line):
                errors.append(line)
            elif warning_pattern.search(line):
                warnings.append(line)

        return warnings, errors

    def preprocess(
        self,
        source: Path,
        output_path: Optional[Path] = None,
        defines: Optional[Dict[str, str]] = None,
        include_paths: Optional[List[Path]] = None,
    ) -> PreprocessResult:
        """
        Preprocess a source file using MSVC.

        Parameters
        ----------
        source : Path
            Source file to preprocess.
        
        output_path : Optional[Path], default=None
            Output file for preprocessed source. If None, output is captured.
        
        defines : Optional[Dict[str, str]], default=None
            Preprocessor definitions (/D flag).
        
        include_paths : Optional[List[Path]], default=None
            Include directories (/I flag).

        Returns
        -------
        PreprocessResult
            Preprocessing result with output content, macros, and includes.

        Examples
        --------
        >>> msvc = MSVCBackend()
        >>> result = msvc.preprocess(
        ...     source=Path("main.c"),
        ...     defines={"VERSION": "1.0"}
        ... )
        >>> if result.success:
        ...     print(f"Macros found: {len(result.macros)}")
        """
        import time

        start_time = time.time()

        cmd = [str(self.executable_path), "/EP", str(source)]

        if defines:
            for name, value in defines.items():
                if value:
                    cmd.append(f"/D{name}={value}")
                else:
                    cmd.append(f"/D{name}")

        for inc in (include_paths or []):
            cmd.append(f"/I{inc}")

        if output_path:
            cmd.extend(["/P", f"/Fi{output_path}"])

        try:
            env = os.environ.copy()
            env.update(self._env_vars)

            result = subprocess.run(
                cmd,
                capture_output=not output_path,
                text=True,
                timeout=60,
                env=env,
            )

            if result.returncode == 0:
                if output_path and output_path.exists():
                    with open(output_path, "r", encoding="utf-8", errors="ignore") as f:
                        output = f.read()
                else:
                    output = result.stdout

                macros = self._extract_macros_from_preprocessed(output)

                return PreprocessResult(
                    success=True,
                    output=output,
                    output_path=output_path,
                    macros=macros,
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
        # MSVC line markers
        pattern = re.compile(r'^#define\s+(\w+)(?:\s+(.+))?$', re.MULTILINE)

        for match in pattern.finditer(output):
            name = match.group(1)
            value = match.group(2) if match.group(2) else "1"
            macros[name] = value.strip()

        return macros

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
            Compiler flag to check (e.g., '/openmp', '/arch:AVX2').

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
            cmd = [str(self.executable_path), "/c", str(test_file), flag]
            env = os.environ.copy()
            env.update(self._env_vars)

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10,
                env=env,
            )
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
            SIMD level: 'auto', 'sse', 'sse2', 'avx', 'avx2', 'avx512'

        Returns
        -------
        List[str]
            List of compiler flags for the specified SIMD level.

        Examples
        --------
        >>> msvc = MSVCBackend()
        >>> flags = msvc.get_simd_flags('avx2')
        >>> print(flags)  # ['/arch:AVX2']
        
        >>> flags = msvc.get_simd_flags('auto')
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
            elif self.info.has_feature(CompilerFeature.SIMD_SSE2):
                flags.append(self.SIMD_FLAGS["sse2"])
        elif level in self.SIMD_FLAGS:
            flags.append(self.SIMD_FLAGS[level])

        return flags

    def generate_dependencies(
        self,
        source: Path,
        output_path: Optional[Path] = None,
    ) -> List[Path]:
        """
        Generate dependency information for a source file.

        Parameters
        ----------
        source : Path
            Source file.
        output_path : Optional[Path], default=None
            Output dependency file.

        Returns
        -------
        List[Path]
            List of dependency files.

        Notes
        -----
        Uses MSVC's /showIncludes flag to output included file paths.
        """
        deps = []

        # MSVC uses /showIncludes to output dependencies
        cmd = [str(self.executable_path), "/c", "/showIncludes", str(source)]

        try:
            env = os.environ.copy()
            env.update(self._env_vars)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )

            # Parse "Note: including file: path" lines
            pattern = re.compile(r"Note: including file:\s*(.+)", re.IGNORECASE)

            for line in result.stderr.split("\n"):
                match = pattern.search(line)
                if match:
                    include_path = match.group(1).strip()
                    deps.append(Path(include_path))

            # Write to file if requested
            if output_path:
                with open(output_path, "w") as f:
                    for dep in deps:
                        f.write(f"{source}: {dep}\n")

        except Exception:
            pass

        return deps

    def get_vs_version(self) -> Optional[str]:
        """
        Get Visual Studio version string.

        Returns
        -------
        Optional[str]
            Visual Studio version (e.g., '17.0', '16.9'), or None if unknown.
        """
        if self._msc_ver and self._msc_ver in self.MSC_VER_MAP:
            return self.MSC_VER_MAP[self._msc_ver][0]
        return None

    def get_vs_year(self) -> Optional[int]:
        """
        Get Visual Studio release year.

        Returns
        -------
        Optional[int]
            Visual Studio release year (e.g., 2022, 2019), or None if unknown.
        """
        if self._msc_ver and self._msc_ver in self.MSC_VER_MAP:
            return self.MSC_VER_MAP[self._msc_ver][1]
        return None

    def get_msc_ver(self) -> Optional[int]:
        """
        Get _MSC_VER value.

        Returns
        -------
        Optional[int]
            _MSC_VER value (e.g., 1930 for VS 2022), or None if unknown.
        """
        return self._msc_ver

    def get_env_vars(self) -> Dict[str, str]:
        """
        Get environment variables from vcvars setup.

        Returns
        -------
        Dict[str, str]
            Copy of environment variables set by vcvars.
        """
        return self._env_vars.copy()

    def get_vs_install_path(self) -> Optional[Path]:
        """
        Get Visual Studio installation path.

        Returns
        -------
        Optional[Path]
            Path to Visual Studio installation, or None if not found.
        """
        return self._vs_install_path

    def get_sdk_path(self) -> Optional[Path]:
        """
        Get Windows SDK installation path.

        Returns
        -------
        Optional[Path]
            Path to Windows SDK, or None if not found.
        """
        return self._sdk_path

    # ========================================================================
    # REPRESENTATION
    # ========================================================================

    def __repr__(self) -> str:
        """
        Get string representation of the backend.

        Returns
        -------
        str
            Human-readable representation including VS version and platform.
        """
        if self._info:
            vs_ver = self.get_vs_version() or "unknown"
            return f"<MSVCBackend VS {vs_ver} ({self.platform})>"
        return "<MSVCBackend (not initialized)>"