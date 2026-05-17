#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    GCC COMPILER BACKEND
==================================

GNU Compiler Collection (GCC) backend implementation with comprehensive
feature detection, optimization flag mapping, and platform-specific
configurations.
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


class GCCBackend(CompilerBackend):
    """
    GNU Compiler Collection (GCC) backend implementation.

    This class provides full support for GCC compilers including:
    - Version detection and feature probing
    - Optimization flag mapping and validation
    - SIMD instruction set detection and flag generation
    - OpenMP support detection
    - Sanitizer support (Address, Thread, Undefined)
    - LTO (Link-Time Optimization) support
    - Profile-Guided Optimization (PGO) support
    - Cross-compilation support

    Parameters
    ----------
    executable_path : Optional[Path]
        Path to GCC executable. Auto-detected if None.
    target : Optional[str]
        Target architecture triple for cross-compilation.
    verbose : bool
        Enable verbose output for debugging.
    gxx : bool
        Use g++ instead of gcc for C++ compilation.

    Attributes
    ----------
    executable_path : Optional[Path]
        GCC executable path.
    gxx_path : Optional[Path]
        G++ executable path.
    target : Optional[str]
        Target architecture triple.
    verbose : bool
        Verbose output flag.
    _feature_cache : Dict[str, bool]
        Cache for feature detection results.
    _flag_support_cache : Dict[str, bool]
        Cache for flag support checks.
    _simd_flags : Dict[str, List[str]]
        Mapping of SIMD levels to GCC flags.

    Examples
    --------
    >>> # Basic usage
    >>> gcc = GCCBackend()
    >>> if gcc.is_available():
    ...     result = gcc.compile(
    ...         sources=[Path("main.c")],
    ...         output_path=Path("output.so"),
    ...         optimization_level=3
    ...     )
    ...     print(f"Compiled in {result.compile_time:.2f}s")

    >>> # With specific GCC version
    >>> gcc = GCCBackend(executable_path=Path("/usr/bin/gcc-13"))
    >>> print(f"GCC version: {gcc.info.version}")

    >>> # Cross-compilation
    >>> gcc = GCCBackend(target="aarch64-linux-gnu")
    >>> result = gcc.compile(
    ...     sources=[Path("main.c")],
    ...     output_path=Path("output_arm.so"),
    ...     flags=["-march=armv8-a"]
    ... )

    >>> # Advanced feature detection
    >>> if gcc.info.has_feature(CompilerFeature.OPENMP):
    ...     result = gcc.compile(..., flags=["-fopenmp"])
    >>> if gcc.info.has_feature(CompilerFeature.SIMD_AVX2):
    ...     result = gcc.compile(..., flags=["-mavx2"])
    """

    # GCC version to feature mapping
    VERSION_FEATURES: Dict[Tuple[int, int, int], List[CompilerFeature]] = {
        (4, 8, 0): [CompilerFeature.C11, CompilerFeature.CPP11],
        (4, 9, 0): [CompilerFeature.CPP14, CompilerFeature.SIMD_AVX2],
        (5, 0, 0): [CompilerFeature.C11, CompilerFeature.CPP14, CompilerFeature.OPENMP],
        (6, 0, 0): [CompilerFeature.CPP17],
        (7, 0, 0): [CompilerFeature.C17, CompilerFeature.LTO],
        (8, 0, 0): [CompilerFeature.CPP20, CompilerFeature.SANITIZE_ADDRESS],
        (9, 0, 0): [CompilerFeature.CPP20],
        (10, 0, 0): [CompilerFeature.CPP20, CompilerFeature.CONCEPTS],
        (11, 0, 0): [CompilerFeature.CPP20, CompilerFeature.COROUTINES, CompilerFeature.C23],
        (12, 0, 0): [CompilerFeature.CPP23],
        (13, 0, 0): [CompilerFeature.CPP23, CompilerFeature.MODULES],
    }

    # SIMD flag mapping for GCC
    SIMD_FLAGS: Dict[str, str] = {
        "sse": "-msse",
        "sse2": "-msse2",
        "sse3": "-msse3",
        "ssse3": "-mssse3",
        "sse4.1": "-msse4.1",
        "sse4.2": "-msse4.2",
        "avx": "-mavx",
        "avx2": "-mavx2",
        "avx512f": "-mavx512f",
        "avx512bw": "-mavx512bw",
        "avx512dq": "-mavx512dq",
        "avx512vl": "-mavx512vl",
        "neon": "-mfpu=neon",
    }

    # Architecture-specific optimization flags
    ARCH_FLAGS: Dict[str, str] = {
        "native": "-march=native",
        "x86-64": "-march=x86-64",
        "x86-64-v2": "-march=x86-64-v2",
        "x86-64-v3": "-march=x86-64-v3",
        "x86-64-v4": "-march=x86-64-v4",
        "armv7": "-march=armv7-a",
        "armv8": "-march=armv8-a",
        "armv8.1": "-march=armv8.1-a",
        "armv8.2": "-march=armv8.2-a",
        "armv8.3": "-march=armv8.3-a",
        "armv8.4": "-march=armv8.4-a",
        "armv8.5": "-march=armv8.5-a",
        "armv8.6": "-march=armv8.6-a",
        "armv9": "-march=armv9-a",
    }

    # Tuning flags
    TUNE_FLAGS: Dict[str, str] = {
        "native": "-mtune=native",
        "generic": "-mtune=generic",
        "intel": "-mtune=intel",
        "amd": "-mtune=amdfam10",
        "znver1": "-mtune=znver1",
        "znver2": "-mtune=znver2",
        "znver3": "-mtune=znver3",
        "znver4": "-mtune=znver4",
    }

    # Sanitizer flags
    SANITIZER_FLAGS: Dict[str, str] = {
        "address": "-fsanitize=address",
        "thread": "-fsanitize=thread",
        "undefined": "-fsanitize=undefined",
        "leak": "-fsanitize=leak",
        "memory": "-fsanitize=memory",
    }

    def __init__(
        self,
        executable_path: Optional[Path] = None,
        target: Optional[str] = None,
        verbose: bool = False,
        gxx: bool = False,
    ):
        super().__init__(executable_path, target, verbose)
        self._use_gxx = gxx
        self.gxx_path: Optional[Path] = None
        self._feature_cache: Dict[str, bool] = {}
        self._flag_support_cache: Dict[str, bool] = {}
        self._simd_flags: Dict[str, List[str]] = {}
        self._compiler_type: str = "gcc"
        self._info: Optional[CompilerInfo] = None  # Cache for compiler info

    @property
    def name(self) -> str:
        """Get compiler name."""
        return "g++" if self._use_gxx else "gcc"

    @property
    def family(self) -> CompilerFamily:
        """Get compiler family."""
        return CompilerFamily.GNU

    @property
    def info(self) -> CompilerInfo:
        """
        Get compiler information with lazy loading.

        Returns
        -------
        CompilerInfo
            Complete compiler information.

        Raises
        ------
        RuntimeError
            If GCC cannot be detected or version cannot be determined.
        """
        if self._info is None:
            self._info = self._detect_info()
        return self._info

    def _detect_info(self) -> CompilerInfo:
        """
        Detect comprehensive GCC information and capabilities.

        Returns
        -------
        CompilerInfo
            Complete compiler information.

        Raises
        ------
        RuntimeError
            If GCC cannot be detected or version cannot be determined.
        """
        # Find executable
        exe_path = self._find_executable()
        if not exe_path:
            raise RuntimeError(f"GCC not found in PATH. Tried: {self.name}")

        self.executable_path = exe_path

        # Also find g++ for C++ compilation
        if not self._use_gxx:
            gxx_name = "g++"
            if self.target:
                gxx_name = f"{self.target}-g++"
            import shutil
            gxx_path = shutil.which(gxx_name)
            if gxx_path:
                self.gxx_path = Path(gxx_path)

        # Get version information
        version_output = self._run_command(
            [str(self.executable_path), "--version"],
            capture_output=True,
        ).stdout

        version_info = self._parse_version(version_output)

        # Get target triple
        target_output = self._run_command(
            [str(self.executable_path), "-dumpmachine"],
            capture_output=True,
        ).stdout.strip()

        # Detect features (pass version info to avoid recursion)
        features = self._detect_features(version_info)

        # Get default flags (pass version info to avoid recursion)
        default_flags = self._get_default_flags_internal(version_info)

        # Get include paths
        include_paths = self._detect_include_paths()

        # Get library paths
        library_paths = self._detect_library_paths()

        # Get predefined macros
        predefined_macros = self._detect_predefined_macros()

        # Get supported flags (limited set for performance)
        supported_flags = self._detect_supported_flags()

        return CompilerInfo(
            name=self.name,
            family=self.family,
            version=version_info["version"],
            version_major=version_info["major"],
            version_minor=version_info["minor"],
            version_patch=version_info["patch"],
            executable_path=self.executable_path,
            target_triple=target_output,
            features=features,
            default_flags=default_flags,
            supported_flags=supported_flags,
            include_paths=include_paths,
            library_paths=library_paths,
            predefined_macros=predefined_macros,
        )

    def _parse_version(self, output: str) -> Dict[str, Any]:
        """
        Parse GCC version from output.

        Parameters
        ----------
        output : str
            Output from 'gcc --version'.

        Returns
        -------
        Dict[str, Any]
            Version information dictionary.
        """
        # Pattern for GCC version: "gcc (GCC) 11.4.0" or "gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0"
        pattern = re.compile(r"gcc\s+(?:\([^)]+\)\s+)?(\d+)\.(\d+)\.(\d+)", re.IGNORECASE)

        match = pattern.search(output)
        if match:
            return {
                "version": f"{match.group(1)}.{match.group(2)}.{match.group(3)}",
                "major": int(match.group(1)),
                "minor": int(match.group(2)),
                "patch": int(match.group(3)),
            }

        # Fallback pattern
        pattern2 = re.compile(r"(\d+)\.(\d+)\.(\d+)")
        match = pattern2.search(output)
        if match:
            return {
                "version": f"{match.group(1)}.{match.group(2)}.{match.group(3)}",
                "major": int(match.group(1)),
                "minor": int(match.group(2)),
                "patch": int(match.group(3)),
            }

        raise RuntimeError(f"Could not parse GCC version from: {output[:200]}")

    def _detect_features(self, version_info: Dict[str, Any]) -> CompilerFeature:
        """
        Detect supported GCC features.

        Parameters
        ----------
        version_info : Dict[str, Any]
            Version information dictionary containing major, minor, patch.

        Returns
        -------
        CompilerFeature
            Bitmask of supported features.
        """
        features = CompilerFeature.NONE
        version_tuple = (version_info["major"], version_info["minor"], version_info["patch"])

        # Add version-based features
        for min_version, feature_list in self.VERSION_FEATURES.items():
            if version_tuple >= min_version:
                for feature in feature_list:
                    features |= feature

        # Detect SIMD support
        features |= self._detect_simd_features()

        # Detect OpenMP support
        if self.check_flag_support("-fopenmp"):
            features |= CompilerFeature.OPENMP

        # Detect LTO support
        if self.check_flag_support("-flto"):
            features |= CompilerFeature.LTO

        # Detect sanitizers
        if self.check_flag_support("-fsanitize=address"):
            features |= CompilerFeature.SANITIZE_ADDRESS
        if self.check_flag_support("-fsanitize=thread"):
            features |= CompilerFeature.SANITIZE_THREAD
        if self.check_flag_support("-fsanitize=undefined"):
            features |= CompilerFeature.SANITIZE_UNDEFINED

        # Detect PGO support
        if self.check_flag_support("-fprofile-generate"):
            features |= CompilerFeature.PGO

        # Detect coverage support
        if self.check_flag_support("--coverage"):
            features |= CompilerFeature.COVERAGE

        return features

    def _detect_simd_features(self) -> CompilerFeature:
        """
        Detect supported SIMD instruction sets.

        Returns
        -------
        CompilerFeature
            SIMD feature flags.
        """
        features = CompilerFeature.NONE

        # Test compilation with each SIMD flag
        test_code = "int main() { return 0; }"
        with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
            f.write(test_code)
            test_file = Path(f.name)

        try:
            for simd_name, flag in self.SIMD_FLAGS.items():
                if self._test_compilation(test_file, [flag]):
                    feature_map = {
                        "sse": CompilerFeature.SIMD_SSE,
                        "sse2": CompilerFeature.SIMD_SSE2,
                        "sse3": CompilerFeature.SIMD_SSE3,
                        "ssse3": CompilerFeature.SIMD_SSSE3,
                        "sse4.1": CompilerFeature.SIMD_SSE4_1,
                        "sse4.2": CompilerFeature.SIMD_SSE4_2,
                        "avx": CompilerFeature.SIMD_AVX,
                        "avx2": CompilerFeature.SIMD_AVX2,
                        "avx512f": CompilerFeature.SIMD_AVX512,
                        "neon": CompilerFeature.SIMD_NEON,
                    }
                    if simd_name in feature_map:
                        features |= feature_map[simd_name]
        finally:
            test_file.unlink(missing_ok=True)

        return features

    def _test_compilation(self, source: Path, flags: List[str]) -> bool:
        """
        Test if compilation succeeds with given flags.

        Parameters
        ----------
        source : Path
            Source file to compile.
        flags : List[str]
            Flags to test.

        Returns
        -------
        bool
            True if compilation succeeds.
        """
        try:
            with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as f:
                output = Path(f.name)

            cmd = [str(self.executable_path), "-c", str(source), "-o", str(output)] + flags
            result = self._run_command(cmd, timeout=10)
            output.unlink(missing_ok=True)
            return result.returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    def _get_default_flags_internal(self, version_info: Dict[str, Any]) -> List[str]:
        """
        Get default GCC flags.

        Parameters
        ----------
        version_info : Dict[str, Any]
            Version information dictionary.

        Returns
        -------
        List[str]
            Default flags.
        """
        flags = [
            "-pipe",  # Use pipes instead of temp files
            "-fno-strict-aliasing",  # Python C API requirement
        ]

        # Add architecture-specific defaults
        import platform
        machine = platform.machine()

        if machine in ("x86_64", "i686"):
            flags.extend(["-msse2", "-mfpmath=sse"])
        elif machine.startswith("arm"):
            if version_info["major"] >= 6:
                flags.append("-march=armv7-a" if machine == "armv7l" else "-march=armv8-a")

        return flags

    def _detect_include_paths(self) -> List[Path]:
        """
        Detect default include search paths.

        Returns
        -------
        List[Path]
            Include directories.
        """
        include_paths = []

        # Query GCC for include paths
        try:
            result = self._run_command(
                [str(self.executable_path), "-E", "-Wp,-v", "-xc", "/dev/null"],
                capture_output=True,
            )

            # Parse stderr for include paths
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

        # Add common fallback paths
        common_paths = [
            Path("/usr/include"),
            Path("/usr/local/include"),
            Path("/usr/include/x86_64-linux-gnu"),
        ]

        for path in common_paths:
            if path.exists() and path not in include_paths:
                include_paths.append(path)

        return include_paths

    def _detect_library_paths(self) -> List[Path]:
        """
        Detect default library search paths.

        Returns
        -------
        List[Path]
            Library directories.
        """
        library_paths = []

        # Query GCC for library paths
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

        # Add common paths
        common_paths = [
            Path("/usr/lib"),
            Path("/usr/local/lib"),
            Path("/usr/lib/x86_64-linux-gnu"),
            Path("/lib"),
            Path("/lib64"),
        ]

        for path in common_paths:
            if path.exists() and path not in library_paths:
                library_paths.append(path)

        return library_paths

    def _detect_predefined_macros(self) -> Dict[str, str]:
        """
        Detect predefined preprocessor macros.

        Returns
        -------
        Dict[str, str]
            Macro definitions.
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
        Detect supported GCC flags.

        Returns
        -------
        Set[str]
            Set of supported flags.
        """
        supported = set()

        # Common flags to check
        common_flags = [
            "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-fPIC", "-fPIE", "-fstack-protector",
            "-fopenmp", "-flto", "-fprofile-generate",
            "-fsanitize=address", "-fsanitize=thread", "-fsanitize=undefined",
            "-g", "-g3", "-ggdb", "-p", "-pg",
            "-O0", "-O1", "-O2", "-O3", "-Os", "-Ofast", "-Og",
        ]

        for flag in common_flags:
            if self.check_flag_support(flag):
                supported.add(flag)

        # Check SIMD flags
        for flag in self.SIMD_FLAGS.values():
            if self.check_flag_support(flag):
                supported.add(flag)

        return supported

    def is_available(self) -> bool:
        """
        Check if GCC is available and functional.

        Returns
        -------
        bool
            True if GCC is available.
        """
        try:
            exe = self._find_executable()
            if not exe:
                return False

            # Test basic compilation
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
        optimization_level: int = 2,
        debug: bool = False,
        language: str = "c",
        standard: Optional[str] = None,
        warnings: Union[bool, str] = True,
        extra_objects: Optional[List[Path]] = None,
    ) -> CompileResult:
        """
        Compile source files using GCC.

        Parameters
        ----------
        sources : List[Path]
            Source files to compile.
        output_path : Path
            Output file path.
        flags : Optional[List[str]]
            Additional compiler flags.
        defines : Optional[Dict[str, str]]
            Preprocessor defines.
        include_paths : Optional[List[Path]]
            Additional include directories.
        library_paths : Optional[List[Path]]
            Additional library search paths.
        libraries : Optional[List[str]]
            Libraries to link.
        link_type : str
            Output type ('object', 'shared', 'static', 'executable').
        optimization_level : int
            Optimization level (0-3, 's' for size, 'g' for debug).
        debug : bool
            Include debug symbols.
        language : str
            Source language ('c' or 'c++').
        standard : Optional[str]
            Language standard (e.g., 'c11', 'c++17').
        warnings : Union[bool, str]
            Warning level (True for -Wall, 'extra' for -Wextra, 'error' for -Werror).
        extra_objects : Optional[List[Path]]
            Additional object files to link.

        Returns
        -------
        CompileResult
            Compilation result with metrics.
        """
        import time

        start_time = time.time()

        # Use g++ for C++ sources
        compiler_exe = self.executable_path
        if language == "c++" and self.gxx_path:
            compiler_exe = self.gxx_path

        if not compiler_exe:
            return CompileResult(
                success=False,
                errors=["GCC executable not found"],
                compile_time=time.time() - start_time,
            )

        # Build command
        cmd = [str(compiler_exe)]

        # Add language-specific flags
        if language == "c++":
            cmd.append("-std=c++17" if not standard else f"-std={standard}")
        else:
            cmd.append("-std=c11" if not standard else f"-std={standard}")

        # Link type
        if link_type == "shared":
            cmd.extend(["-shared", "-fPIC"])
        elif link_type == "static":
            cmd.append("-static")
        elif link_type == "object":
            cmd.append("-c")

        # Optimization
        if isinstance(optimization_level, str):
            opt_map = {"s": "-Os", "g": "-Og", "fast": "-Ofast"}
            cmd.append(opt_map.get(optimization_level, "-O2"))
        else:
            cmd.append(f"-O{optimization_level}")

        # Debug
        if debug:
            cmd.append("-g")

        # Warnings
        if warnings:
            if warnings == "extra":
                cmd.extend(["-Wall", "-Wextra"])
            elif warnings == "error":
                cmd.extend(["-Wall", "-Werror"])
            elif warnings == "all":
                cmd.append("-Wall")
            else:
                cmd.append("-Wall")

        # Defines
        if defines:
            for name, value in defines.items():
                if value:
                    cmd.append(f"-D{name}={value}")
                else:
                    cmd.append(f"-D{name}")

        # Include paths
        for inc in (include_paths or []):
            cmd.append(f"-I{inc}")

        # Default include paths
        for inc in self.info.include_paths:
            cmd.append(f"-I{inc}")

        # Extra flags
        if flags:
            cmd.extend(flags)

        # Add default flags
        cmd.extend(self.info.default_flags)

        # Sources
        for src in sources:
            cmd.append(str(src))

        # Extra objects
        if extra_objects:
            cmd.extend(str(obj) for obj in extra_objects)

        # Output
        if link_type == "object":
            cmd.extend(["-o", str(output_path)])
        else:
            cmd.extend(["-o", str(output_path)])

        # Library paths
        if library_paths:
            for lib_path in library_paths:
                cmd.append(f"-L{lib_path}")

        # Libraries
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
                errors=[f"Compilation timeout: {e}"],
            )
        except Exception as e:
            return CompileResult(
                success=False,
                compile_time=time.time() - start_time,
                command=cmd,
                errors=[f"Compilation error: {e}"],
            )

    def preprocess(
        self,
        source: Path,
        output_path: Optional[Path] = None,
        defines: Optional[Dict[str, str]] = None,
        include_paths: Optional[List[Path]] = None,
    ) -> PreprocessResult:
        """
        Preprocess a source file using GCC.

        Parameters
        ----------
        source : Path
            Source file to preprocess.
        output_path : Optional[Path]
            Output file for preprocessed source.
        defines : Optional[Dict[str, str]]
            Preprocessor defines.
        include_paths : Optional[List[Path]]
            Include directories.

        Returns
        -------
        PreprocessResult
            Preprocessing result.
        """
        import time

        start_time = time.time()

        cmd = [str(self.executable_path), "-E", str(source)]

        # Defines
        if defines:
            for name, value in defines.items():
                if value:
                    cmd.append(f"-D{name}={value}")
                else:
                    cmd.append(f"-D{name}")

        # Include paths
        for inc in (include_paths or []):
            cmd.append(f"-I{inc}")

        # Output
        if output_path:
            cmd.extend(["-o", str(output_path)])

        try:
            result = self._run_command(cmd, capture_output=True)

            if result.returncode == 0:
                # Extract macros and includes from preprocessed output
                macros = self._extract_macros_from_preprocessed(result.stdout)
                includes = self._extract_includes_from_preprocessed(result.stdout)

                return PreprocessResult(
                    success=True,
                    output=result.stdout,
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
            Preprocessed output.

        Returns
        -------
        Dict[str, str]
            Macro definitions.
        """
        macros = {}
        # GCC line markers: #define MACRO value
        pattern = re.compile(r'^#define\s+(\w+)(?:\s+(.+))?$', re.MULTILINE)

        for match in pattern.finditer(output):
            name = match.group(1)
            value = match.group(2) if match.group(2) else "1"
            macros[name] = value.strip()

        return macros

    def _extract_includes_from_preprocessed(self, output: str) -> List[Path]:
        """
        Extract included files from preprocessed output.

        Parameters
        ----------
        output : str
            Preprocessed output.

        Returns
        -------
        List[Path]
            List of included files.
        """
        includes = []
        # GCC line markers: # 1 "file.h" 1
        pattern = re.compile(r'^#\s+\d+\s+"([^"]+)"', re.MULTILINE)

        seen = set()
        for match in pattern.finditer(output):
            file_path = match.group(1)
            if file_path not in seen:
                seen.add(file_path)
                includes.append(Path(file_path))

        return includes

    def get_default_flags(self) -> List[str]:
        """
        Get default GCC flags.

        Returns
        -------
        List[str]
            Default flags.
        """
        return self.info.default_flags.copy()

    def check_flag_support(self, flag: str) -> bool:
        """
        Check if a flag is supported by GCC.

        Parameters
        ----------
        flag : str
            Flag to check.

        Returns
        -------
        bool
            True if flag is supported.
        """
        if flag in self._flag_support_cache:
            return self._flag_support_cache[flag]

        # Test with a minimal compilation
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
            Include directories.
        """
        return self.info.include_paths.copy()

    def get_library_paths(self) -> List[Path]:
        """
        Get default library search paths.

        Returns
        -------
        List[Path]
            Library directories.
        """
        return self.info.library_paths.copy()

    def get_predefined_macros(self) -> Dict[str, str]:
        """
        Get predefined preprocessor macros.

        Returns
        -------
        Dict[str, str]
            Macro definitions.
        """
        return self.info.predefined_macros.copy()

    def get_simd_flags(self, level: str) -> List[str]:
        """
        Get SIMD flags for a specific level.

        Parameters
        ----------
        level : str
            SIMD level (e.g., 'avx2', 'sse4.2').

        Returns
        -------
        List[str]
            SIMD compiler flags.
        """
        flags = []

        if level == "auto":
            # Detect best available
            if self.info.has_feature(CompilerFeature.SIMD_AVX512):
                flags.append(self.SIMD_FLAGS["avx512f"])
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
        Get architecture flag.

        Parameters
        ----------
        arch : str
            Architecture name.

        Returns
        -------
        str
            Architecture flag.
        """
        return self.ARCH_FLAGS.get(arch, "")

    def get_tune_flag(self, tune: str) -> str:
        """
        Get tuning flag.

        Parameters
        ----------
        tune : str
            Tuning target.

        Returns
        -------
        str
            Tuning flag.
        """
        return self.TUNE_FLAGS.get(tune, "")

    def get_sanitizer_flag(self, sanitizer: str) -> str:
        """
        Get sanitizer flag.

        Parameters
        ----------
        sanitizer : str
            Sanitizer type.

        Returns
        -------
        str
            Sanitizer flag.
        """
        return self.SANITIZER_FLAGS.get(sanitizer, "")

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
        output_path : Optional[Path]
            Output dependency file (.d).

        Returns
        -------
        List[Path]
            List of dependency files.
        """
        deps = []

        cmd = [str(self.executable_path), "-MM", str(source)]

        try:
            result = self._run_command(cmd, capture_output=True)

            if result.returncode == 0:
                # Parse Makefile-style dependency output
                output = result.stdout.replace("\\\n", " ")
                if ":" in output:
                    deps_part = output.split(":", 1)[1].strip()
                    for dep in deps_part.split():
                        dep = dep.strip()
                        if dep:
                            deps.append(Path(dep))

                # Write to file if requested
                if output_path:
                    with open(output_path, "w") as f:
                        f.write(result.stdout)

        except Exception:
            pass

        return deps

    def __repr__(self) -> str:
        info = self._info if self._info else "not initialized"
        if self._info:
            return f"<GCCBackend {self.info.version} ({self.info.target_triple})>"
        return f"<GCCBackend (not initialized)>"
