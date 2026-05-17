#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    COMPILER DETECTION SYSTEM
==================================

Advanced compiler detection system with automatic discovery,
version parsing, capability probing, and intelligent fallback
mechanisms across all major platforms.
"""

import os
import re
import subprocess
import sys
import json
import shutil
import platform
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum, auto, Enum
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, Type

from .base import CompilerBackend, CompilerFamily, CompilerFeature, CompilerInfo
from .gcc import GCCBackend
from .clang import ClangBackend
from .msvc import MSVCBackend
from .icc import ICCBackend


class CompilerPriority(IntEnum):
    """
    Compiler priority levels for automatic selection.
    
    This enum uses IntEnum to allow integer values and comparisons.
    
    Attributes
    ----------
    SYSTEM_DEFAULT : int
        System default compiler (lowest priority). Value: 0
    VERY_LOW : int
        Very low priority. Value: 15
    LOW : int
        Low priority. Value: 30
    MEDIUM_LOW : int
        Medium-low priority. Value: 45
    MEDIUM : int
        Medium priority. Value: 55
    PREFERRED : int
        User-preferred compiler. Value: 65
    HIGH : int
        High priority. Value: 75
    OPTIMAL : int
        Best compiler for the current platform. Value: 85
    VERY_HIGH : int
        Very high priority. Value: 95
    EXPLICIT : int
        Explicitly specified compiler (highest priority). Value: 100
    """
    
    SYSTEM_DEFAULT = 0
    VERY_LOW = 15
    LOW = 30
    MEDIUM_LOW = 45
    MEDIUM = 55
    PREFERRED = 65
    HIGH = 75
    OPTIMAL = 85
    VERY_HIGH = 95
    EXPLICIT = 100
    
    def __int__(self):
        """Return integer value."""
        return self.value
    
    def __lt__(self, other):
        """Compare priorities."""
        if isinstance(other, CompilerPriority):
            return self.value < other.value
        return self.value < other
    
    def __le__(self, other):
        """Compare priorities."""
        if isinstance(other, CompilerPriority):
            return self.value <= other.value
        return self.value <= other
    
    def __gt__(self, other):
        """Compare priorities."""
        if isinstance(other, CompilerPriority):
            return self.value > other.value
        return self.value > other
    
    def __ge__(self, other):
        """Compare priorities."""
        if isinstance(other, CompilerPriority):
            return self.value >= other.value
        return self.value >= other


class PlatformType(Enum):
    """
    Platform type enumeration for compiler detection strategies.

    Attributes
    ----------
    LINUX : str
        Linux operating system.
    MACOS : str
        macOS operating system.
    WINDOWS : str
        Windows operating system.
    BSD : str
        BSD operating system.
    OTHER : str
        Other/unknown operating system.
    """

    LINUX = "linux"
    MACOS = "darwin"
    WINDOWS = "win32"
    BSD = "bsd"
    OTHER = "other"

    @classmethod
    def current(cls) -> "PlatformType":
        """
        Get current platform type.

        Returns
        -------
        PlatformType
            Current platform type.
        """
        system = sys.platform
        if system.startswith("linux"):
            return cls.LINUX
        elif system == "darwin":
            return cls.MACOS
        elif system == "win32":
            return cls.WINDOWS
        elif "bsd" in system:
            return cls.BSD
        else:
            return cls.OTHER


@dataclass
class CompilerCandidate:
    """
    Represents a detected compiler candidate with metadata.

    Parameters
    ----------
    name : str
        Compiler name (e.g., 'gcc', 'clang', 'cl').
    family : CompilerFamily
        Compiler family.
    executable_path : Path
        Path to compiler executable.
    version : str
        Version string.
    version_tuple : Tuple[int, int, int]
        Parsed version tuple.
    priority : CompilerPriority
        Priority level for selection.
    platform : PlatformType
        Platform this compiler runs on.
    target_arch : str
        Target architecture.
    features : CompilerFeature
        Detected feature flags.
    backend_class : Type[CompilerBackend]
        Backend class for this compiler.
    metadata : Dict[str, Any]
        Additional metadata.

    Attributes
    ----------
    name : str
        Compiler name.
    family : CompilerFamily
        Compiler family.
    executable_path : Path
        Executable path.
    version : str
        Version string.
    version_tuple : Tuple[int, int, int]
        Version tuple.
    priority : CompilerPriority
        Priority level.
    platform : PlatformType
        Platform type.
    target_arch : str
        Target architecture.
    features : CompilerFeature
        Feature flags.
    backend_class : Type[CompilerBackend]
        Backend class.
    metadata : Dict[str, Any]
        Metadata dictionary.

    Examples
    --------
    >>> candidate = CompilerCandidate(
    ...     name="gcc",
    ...     family=CompilerFamily.GNU,
    ...     executable_path=Path("/usr/bin/gcc"),
    ...     version="11.4.0",
    ...     version_tuple=(11, 4, 0),
    ...     priority=CompilerPriority.SYSTEM_DEFAULT,
    ...     platform=PlatformType.LINUX,
    ...     target_arch="x86_64",
    ...     features=CompilerFeature.C11 | CompilerFeature.CPP17,
    ...     backend_class=GCCBackend,
    ... )
    >>> print(f"Found {candidate.name} {candidate.version}")
    """

    name: str
    family: CompilerFamily
    executable_path: Path
    version: str
    version_tuple: Tuple[int, int, int]
    priority: CompilerPriority = CompilerPriority.SYSTEM_DEFAULT
    platform: PlatformType = field(default_factory=PlatformType.current)
    target_arch: str = ""
    features: CompilerFeature = CompilerFeature.NONE
    backend_class: Optional[Type[CompilerBackend]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.target_arch == "":
            self.target_arch = platform.machine()

    def create_backend(self, **kwargs) -> Optional[CompilerBackend]:
        """
        Create a compiler backend instance from this candidate.

        Parameters
        ----------
        **kwargs : Any
            Additional arguments for backend constructor.

        Returns
        -------
        Optional[CompilerBackend]
            Compiler backend instance or None.
        """
        if self.backend_class is None:
            return None

        try:
            return self.backend_class(
                executable_path=self.executable_path,
                **kwargs
            )
        except Exception:
            return None

    def is_better_than(self, other: "CompilerCandidate") -> bool:
        """
        Compare this candidate with another.

        Parameters
        ----------
        other : CompilerCandidate
            Other candidate to compare.

        Returns
        -------
        bool
            True if this candidate is better.
        """
        if self.priority.value != other.priority.value:
            return self.priority.value > other.priority.value

        return self.version_tuple > other.version_tuple

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
            "executable_path": str(self.executable_path),
            "version": self.version,
            "version_tuple": list(self.version_tuple),
            "priority": self.priority.value,
            "platform": self.platform.value,
            "target_arch": self.target_arch,
            "features": [f.name for f in CompilerFeature if self.features & f],
            "metadata": self.metadata,
        }


class CompilerDetector(ABC):
    """
    Abstract base class for compiler-specific detectors.

    Each compiler family has its own detector implementation that
    knows how to find, identify, and probe that compiler's capabilities.

    Attributes
    ----------
    name : str
        Detector name.
    family : CompilerFamily
        Compiler family this detector handles.
    platform : PlatformType
        Platform this detector operates on.
    _detected_cache : List[CompilerCandidate]
        Cached detection results.
    _cache_lock : RLock
        Lock for cache access.
    """

    name: str = "base"
    family: CompilerFamily = CompilerFamily.OTHER
    platform: PlatformType = PlatformType.current()

    def __init__(self):
        self._detected_cache: List[CompilerCandidate] = []
        self._cache_lock = RLock()

    @abstractmethod
    def detect(self) -> List[CompilerCandidate]:
        """
        Detect all instances of this compiler.

        Returns
        -------
        List[CompilerCandidate]
            List of detected compiler candidates.
        """
        pass

    @abstractmethod
    def probe_version(self, executable_path: Path) -> Optional[Tuple[int, int, int]]:
        """
        Probe compiler version.

        Parameters
        ----------
        executable_path : Path
            Path to compiler executable.

        Returns
        -------
        Optional[Tuple[int, int, int]]
            Version tuple (major, minor, patch) or None.
        """
        pass

    @abstractmethod
    def probe_features(self, executable_path: Path) -> CompilerFeature:
        """
        Probe compiler features.

        Parameters
        ----------
        executable_path : Path
            Path to compiler executable.

        Returns
        -------
        CompilerFeature
            Feature flags.
        """
        pass

    def probe_target(self, executable_path: Path) -> str:
        """
        Probe compiler target architecture.

        Parameters
        ----------
        executable_path : Path
            Path to compiler executable.

        Returns
        -------
        str
            Target architecture string.
        """
        try:
            result = subprocess.run(
                [str(executable_path), "-dumpmachine"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()
        except Exception:
            return platform.machine()

    def get_cached_candidates(self) -> List[CompilerCandidate]:
        """
        Get cached detection results.

        Returns
        -------
        List[CompilerCandidate]
            Cached compiler candidates.
        """
        with self._cache_lock:
            if not self._detected_cache:
                self._detected_cache = self.detect()
            return self._detected_cache.copy()

    def clear_cache(self) -> None:
        """
        Clear detection cache.
        """
        with self._cache_lock:
            self._detected_cache.clear()

    def _run_probe_command(
        self,
        cmd: List[str],
        timeout: int = 10,
    ) -> Optional[str]:
        """
        Run a probe command and return output.

        Parameters
        ----------
        cmd : List[str]
            Command to run.
        timeout : int
            Timeout in seconds.

        Returns
        -------
        Optional[str]
            Command output or None.
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.stdout + result.stderr
        except Exception:
            return None


class GCCDetector(CompilerDetector):
    """
    GNU Compiler Collection (GCC) detector.

    Detects GCC installations on Linux, macOS, and Windows (MinGW/Cygwin).
    Supports versioned executables (gcc-11, gcc-12, etc.) and
    cross-compilation toolchains.

    Attributes
    ----------
    name : str
        "gcc"
    family : CompilerFamily
        CompilerFamily.GNU
    _version_pattern : re.Pattern
        Compiled regex for version parsing.
    _common_paths : List[Path]
        Common installation paths.

    Examples
    --------
    >>> detector = GCCDetector()
    >>> candidates = detector.detect()
    >>> for c in candidates:
    ...     print(f"GCC {c.version} at {c.executable_path}")
    """

    name = "gcc"
    family = CompilerFamily.GNU

    def __init__(self):
        super().__init__()
        self._version_pattern = re.compile(
            r"(?:gcc|g\+\+)\s+(?:\([^)]+\)\s+)?(\d+)\.(\d+)\.(\d+)",
            re.IGNORECASE
        )

        # Common GCC installation paths per platform
        self._common_paths: Dict[PlatformType, List[Path]] = {
            PlatformType.LINUX: [
                Path("/usr/bin"),
                Path("/usr/local/bin"),
                Path("/opt/gcc/bin"),
                Path("/opt/rh/gcc-toolset-13/root/usr/bin"),
                Path("/opt/rh/gcc-toolset-12/root/usr/bin"),
                Path("/opt/rh/gcc-toolset-11/root/usr/bin"),
                Path("/opt/rh/devtoolset-11/root/usr/bin"),
                Path("/opt/rh/devtoolset-10/root/usr/bin"),
            ],
            PlatformType.MACOS: [
                Path("/usr/local/bin"),
                Path("/opt/homebrew/bin"),
                Path("/opt/local/bin"),
                Path("/usr/bin"),
            ],
            PlatformType.WINDOWS: [
                Path("C:\\msys64\\mingw64\\bin"),
                Path("C:\\msys64\\mingw32\\bin"),
                Path("C:\\mingw64\\bin"),
                Path("C:\\mingw32\\bin"),
                Path("C:\\cygwin64\\bin"),
                Path("C:\\cygwin\\bin"),
            ],
        }

    def detect(self) -> List[CompilerCandidate]:
        """
        Detect all GCC installations.

        Returns
        -------
        List[CompilerCandidate]
            List of detected GCC candidates.
        """
        candidates: List[CompilerCandidate] = []
        seen_paths: Set[Path] = set()

        # Search in PATH first
        for name in ["gcc", "gcc-13", "gcc-12", "gcc-11", "gcc-10", "gcc-9", "gcc-8"]:
            exe = shutil.which(name)
            if exe:
                path = Path(exe)
                if path not in seen_paths:
                    seen_paths.add(path)
                    candidate = self._create_candidate(path)
                    if candidate:
                        candidates.append(candidate)

        # Search common paths
        for base in self._common_paths.get(self.platform, []):
            if not base.exists():
                continue

            # Look for gcc executables
            patterns = ["gcc", "gcc-*", "*-gcc", "*-linux-gnu-gcc"]
            for pattern in patterns:
                for exe in base.glob(pattern):
                    if exe.is_file() and os.access(exe, os.X_OK):
                        if exe not in seen_paths:
                            seen_paths.add(exe)
                            candidate = self._create_candidate(exe)
                            if candidate:
                                candidates.append(candidate)

        # Check environment variables
        cc_env = os.environ.get("CC", "")
        if cc_env:
            path = Path(cc_env)
            if path not in seen_paths and self._is_gcc(path):
                candidate = self._create_candidate(path)
                if candidate:
                    candidate.priority = CompilerPriority.PREFERRED
                    candidates.append(candidate)

        # Sort by version (newest first)
        candidates.sort(key=lambda c: c.version_tuple, reverse=True)
        return candidates

    def _is_gcc(self, path: Path) -> bool:
        """
        Check if an executable is GCC.

        Parameters
        ----------
        path : Path
            Executable path.

        Returns
        -------
        bool
            True if executable is GCC.
        """
        output = self._run_probe_command([str(path), "--version"])
        if output:
            return "gcc" in output.lower() or "gnu" in output.lower()
        return False

    def _create_candidate(self, path: Path) -> Optional[CompilerCandidate]:
        """
        Create a candidate from an executable path.

        Parameters
        ----------
        path : Path
            Executable path.

        Returns
        -------
        Optional[CompilerCandidate]
            Candidate or None if probing fails.
        """
        version_tuple = self.probe_version(path)
        if not version_tuple:
            return None

        version_str = f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"
        target = self.probe_target(path)
        features = self.probe_features(path)

        # Determine priority
        priority = CompilerPriority.SYSTEM_DEFAULT
        if os.environ.get("CC") == str(path):
            priority = CompilerPriority.PREFERRED

        return CompilerCandidate(
            name="gcc",
            family=self.family,
            executable_path=path,
            version=version_str,
            version_tuple=version_tuple,
            priority=priority,
            platform=self.platform,
            target_arch=target,
            features=features,
            backend_class=GCCBackend,
            metadata={"compiler": "gcc", "path": str(path)},
        )

    def probe_version(self, executable_path: Path) -> Optional[Tuple[int, int, int]]:
        """
        Probe GCC version.

        Parameters
        ----------
        executable_path : Path
            Path to GCC executable.

        Returns
        -------
        Optional[Tuple[int, int, int]]
            Version tuple or None.
        """
        output = self._run_probe_command([str(executable_path), "--version"])
        if not output:
            return None

        match = self._version_pattern.search(output)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

        # Fallback: try -dumpversion
        output = self._run_probe_command([str(executable_path), "-dumpversion"])
        if output:
            parts = output.strip().split(".")
            if len(parts) >= 2:
                try:
                    major = int(parts[0])
                    minor = int(parts[1]) if len(parts) > 1 else 0
                    patch = int(parts[2]) if len(parts) > 2 else 0
                    return (major, minor, patch)
                except ValueError:
                    pass

        return None

    def probe_features(self, executable_path: Path) -> CompilerFeature:
        """
        Probe GCC features.

        Parameters
        ----------
        executable_path : Path
            Path to GCC executable.

        Returns
        -------
        CompilerFeature
            Feature flags.
        """
        features = CompilerFeature.NONE

        # Get version first
        version = self.probe_version(executable_path)
        if not version:
            return features

        major, minor, patch = version

        # Version-based features
        if (major, minor) >= (5, 0):
            features |= CompilerFeature.C11
        if (major, minor) >= (5, 0):
            features |= CompilerFeature.CPP11
        if (major, minor) >= (6, 0):
            features |= CompilerFeature.CPP14
        if (major, minor) >= (8, 0):
            features |= CompilerFeature.C17
        if (major, minor) >= (7, 0):
            features |= CompilerFeature.CPP17
        if (major, minor) >= (10, 0):
            features |= CompilerFeature.CPP20
        if (major, minor) >= (12, 0):
            features |= CompilerFeature.CPP23

        # Test OpenMP
        if self._test_flag(executable_path, "-fopenmp"):
            features |= CompilerFeature.OPENMP

        # Test LTO
        if self._test_flag(executable_path, "-flto"):
            features |= CompilerFeature.LTO

        # Test SIMD
        simd_flags = ["-mavx2", "-mavx", "-msse4.2", "-msse2"]
        for flag in simd_flags:
            if self._test_flag(executable_path, flag):
                if flag == "-mavx2":
                    features |= CompilerFeature.SIMD_AVX2 | CompilerFeature.SIMD_AVX
                elif flag == "-mavx":
                    features |= CompilerFeature.SIMD_AVX
                elif flag == "-msse4.2":
                    features |= CompilerFeature.SIMD_SSE4_2
                elif flag == "-msse2":
                    features |= CompilerFeature.SIMD_SSE2
                break

        return features

    def _test_flag(self, exe: Path, flag: str) -> bool:
        """
        Test if a compiler flag is supported.

        Parameters
        ----------
        exe : Path
            Compiler executable.
        flag : str
            Flag to test.

        Returns
        -------
        bool
            True if flag is supported.
        """
        with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
            f.write("int main() { return 0; }")
            test_file = Path(f.name)

        try:
            with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as f:
                output = Path(f.name)

            cmd = [str(exe), "-c", str(test_file), "-o", str(output), flag]
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            output.unlink(missing_ok=True)
            return result.returncode == 0
        except Exception:
            return False
        finally:
            test_file.unlink(missing_ok=True)


class ClangDetector(CompilerDetector):
    """
    LLVM/Clang compiler detector.

    Detects Clang installations on all platforms, including Apple Clang
    on macOS and clang-cl on Windows.

    Attributes
    ----------
    name : str
        "clang"
    family : CompilerFamily
        CompilerFamily.LLVM
    _version_pattern : re.Pattern
        Compiled regex for version parsing.
    """

    name = "clang"
    family = CompilerFamily.LLVM

    def __init__(self):
        super().__init__()
        self._version_pattern = re.compile(
            r"(?:clang|Apple\s+clang|LLVM)\s+version\s+(\d+)\.(\d+)\.(\d+)",
            re.IGNORECASE
        )

        self._common_paths: Dict[PlatformType, List[Path]] = {
            PlatformType.LINUX: [
                Path("/usr/bin"),
                Path("/usr/local/bin"),
                Path("/opt/llvm/bin"),
            ],
            PlatformType.MACOS: [
                Path("/usr/bin"),
                Path("/usr/local/bin"),
                Path("/opt/homebrew/opt/llvm/bin"),
                Path("/opt/local/bin"),
            ],
            PlatformType.WINDOWS: [
                Path("C:\\Program Files\\LLVM\\bin"),
                Path("C:\\Program Files (x86)\\LLVM\\bin"),
            ],
        }

    def detect(self) -> List[CompilerCandidate]:
        """
        Detect all Clang installations.

        Returns
        -------
        List[CompilerCandidate]
            List of detected Clang candidates.
        """
        candidates: List[CompilerCandidate] = []
        seen_paths: Set[Path] = set()

        # Search in PATH
        for name in ["clang", "clang-18", "clang-17", "clang-16", "clang-15", "clang-14",
                     "clang-13", "clang-12", "clang-11", "clang-10"]:
            exe = shutil.which(name)
            if exe:
                path = Path(exe)
                if path not in seen_paths:
                    seen_paths.add(path)
                    candidate = self._create_candidate(path)
                    if candidate:
                        candidates.append(candidate)

        # Search common paths
        for base in self._common_paths.get(self.platform, []):
            if not base.exists():
                continue

            for exe in base.glob("clang*"):
                if exe.is_file() and os.access(exe, os.X_OK):
                    if exe not in seen_paths and "clang++" not in exe.name:
                        seen_paths.add(exe)
                        candidate = self._create_candidate(exe)
                        if candidate:
                            candidates.append(candidate)

        # Check environment
        for env_var in ["CC", "CLANG"]:
            cc_env = os.environ.get(env_var, "")
            if cc_env:
                path = Path(cc_env)
                if path not in seen_paths and self._is_clang(path):
                    candidate = self._create_candidate(path)
                    if candidate:
                        candidate.priority = CompilerPriority.PREFERRED
                        candidates.append(candidate)

        candidates.sort(key=lambda c: c.version_tuple, reverse=True)
        return candidates

    def _is_clang(self, path: Path) -> bool:
        """
        Check if an executable is Clang.

        Parameters
        ----------
        path : Path
            Executable path.

        Returns
        -------
        bool
            True if executable is Clang.
        """
        output = self._run_probe_command([str(path), "--version"])
        if output:
            return "clang" in output.lower() or "llvm" in output.lower()
        return False

    def _create_candidate(self, path: Path) -> Optional[CompilerCandidate]:
        """
        Create a candidate from an executable path.

        Parameters
        ----------
        path : Path
            Executable path.

        Returns
        -------
        Optional[CompilerCandidate]
            Candidate or None.
        """
        version_tuple = self.probe_version(path)
        if not version_tuple:
            return None

        version_str = f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"
        target = self.probe_target(path)
        features = self.probe_features(path)

        priority = CompilerPriority.SYSTEM_DEFAULT
        if os.environ.get("CC") == str(path):
            priority = CompilerPriority.PREFERRED

        # Check if it's Apple Clang
        is_apple = False
        output = self._run_probe_command([str(path), "--version"])
        if output and "apple" in output.lower():
            is_apple = True

        return CompilerCandidate(
            name="apple-clang" if is_apple else "clang",
            family=self.family,
            executable_path=path,
            version=version_str,
            version_tuple=version_tuple,
            priority=priority,
            platform=self.platform,
            target_arch=target,
            features=features,
            backend_class=ClangBackend,
            metadata={"compiler": "clang", "apple": is_apple},
        )

    def probe_version(self, executable_path: Path) -> Optional[Tuple[int, int, int]]:
        """
        Probe Clang version.

        Parameters
        ----------
        executable_path : Path
            Path to Clang executable.

        Returns
        -------
        Optional[Tuple[int, int, int]]
            Version tuple or None.
        """
        output = self._run_probe_command([str(executable_path), "--version"])
        if not output:
            return None

        match = self._version_pattern.search(output)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

        return None

    def probe_features(self, executable_path: Path) -> CompilerFeature:
        """
        Probe Clang features.

        Parameters
        ----------
        executable_path : Path
            Path to Clang executable.

        Returns
        -------
        CompilerFeature
            Feature flags.
        """
        features = CompilerFeature.NONE

        version = self.probe_version(executable_path)
        if not version:
            return features

        major, minor, _ = version

        # Version-based features
        if (major, minor) >= (3, 4):
            features |= CompilerFeature.C11 | CompilerFeature.CPP11
        if (major, minor) >= (3, 5):
            features |= CompilerFeature.CPP14
        if (major, minor) >= (5, 0):
            features |= CompilerFeature.C17 | CompilerFeature.CPP17
        if (major, minor) >= (10, 0):
            features |= CompilerFeature.CPP20
        if (major, minor) >= (15, 0):
            features |= CompilerFeature.CPP23

        # Test features
        if self._test_flag(executable_path, "-fopenmp"):
            features |= CompilerFeature.OPENMP
        if self._test_flag(executable_path, "-flto"):
            features |= CompilerFeature.LTO
        if self._test_flag(executable_path, "-fsanitize=address"):
            features |= CompilerFeature.SANITIZE_ADDRESS
        if self._test_flag(executable_path, "-fsanitize=thread"):
            features |= CompilerFeature.SANITIZE_THREAD
        if self._test_flag(executable_path, "-fsanitize=undefined"):
            features |= CompilerFeature.SANITIZE_UNDEFINED

        return features

    def _test_flag(self, exe: Path, flag: str) -> bool:
        """
        Test if a compiler flag is supported.

        Parameters
        ----------
        exe : Path
            Compiler executable.
        flag : str
            Flag to test.

        Returns
        -------
        bool
            True if flag is supported.
        """
        with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
            f.write("int main() { return 0; }")
            test_file = Path(f.name)

        try:
            with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as f:
                output = Path(f.name)

            cmd = [str(exe), "-c", str(test_file), "-o", str(output), flag]
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            output.unlink(missing_ok=True)
            return result.returncode == 0
        except Exception:
            return False
        finally:
            test_file.unlink(missing_ok=True)


class MSVCDetector(CompilerDetector):
    """
    Microsoft Visual C++ (MSVC) detector.

    Detects MSVC installations through Visual Studio, Build Tools,
    and Windows SDK. Supports vswhere-based detection for VS 2017+.

    Attributes
    ----------
    name : str
        "msvc"
    family : CompilerFamily
        CompilerFamily.MICROSOFT
    """

    name = "msvc"
    family = CompilerFamily.MICROSOFT
    platform = PlatformType.WINDOWS

    def __init__(self):
        super().__init__()
        self._version_pattern = re.compile(
            r"(?:Microsoft\s*\(R\)\s*C/C\+\+\s*Optimizing\s*Compiler\s*Version\s*)(\d+)\.(\d+)\.(\d+)",
            re.IGNORECASE
        )

    def detect(self) -> List[CompilerCandidate]:
        """
        Detect all MSVC installations.

        Returns
        -------
        List[CompilerCandidate]
            List of detected MSVC candidates.
        """
        candidates: List[CompilerCandidate] = []

        if self.platform != PlatformType.WINDOWS:
            return candidates

        # Use vswhere for VS 2017+
        vswhere_candidates = self._detect_vswhere()
        candidates.extend(vswhere_candidates)

        # Check environment (vcvars may have set up PATH)
        cl_exe = shutil.which("cl.exe")
        if cl_exe:
            path = Path(cl_exe)
            candidate = self._create_candidate(path)
            if candidate and not self._already_detected(candidate, candidates):
                candidates.append(candidate)

        # Check common paths
        common_paths = [
            Path("C:\\Program Files\\Microsoft Visual Studio\\2022\\Enterprise\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files\\Microsoft Visual Studio\\2022\\Professional\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files\\Microsoft Visual Studio\\2022\\Community\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files\\Microsoft Visual Studio\\2022\\BuildTools\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2019\\Enterprise\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2019\\Professional\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2019\\Community\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2019\\BuildTools\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2017\\Enterprise\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2017\\Professional\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2017\\Community\\VC\\Tools\\MSVC"),
            Path("C:\\Program Files (x86)\\Microsoft Visual Studio\\2017\\BuildTools\\VC\\Tools\\MSVC"),
        ]

        for base in common_paths:
            if base.exists():
                for version_dir in sorted(base.iterdir(), reverse=True):
                    for arch in ["x64", "x86", "arm64", "arm"]:
                        cl_path = version_dir / "bin" / f"Host{arch}" / arch / "cl.exe"
                        if cl_path.exists():
                            candidate = self._create_candidate(cl_path)
                            if candidate and not self._already_detected(candidate, candidates):
                                candidates.append(candidate)

        candidates.sort(key=lambda c: c.version_tuple, reverse=True)
        return candidates

    def _detect_vswhere(self) -> List[CompilerCandidate]:
        """
        Detect MSVC using vswhere.exe.

        Returns
        -------
        List[CompilerCandidate]
            List of candidates found via vswhere.
        """
        candidates: List[CompilerCandidate] = []

        vswhere_paths = [
            Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) /
            "Microsoft Visual Studio" / "Installer" / "vswhere.exe",
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) /
            "Microsoft Visual Studio" / "Installer" / "vswhere.exe",
        ]

        for vswhere in vswhere_paths:
            if not vswhere.exists():
                continue

            try:
                result = subprocess.run(
                    [str(vswhere), "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                     "-property", "installationPath", "-format", "json"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode == 0 and result.stdout.strip():
                    installations = json.loads(result.stdout)
                    if not isinstance(installations, list):
                        installations = [installations]

                    for install in installations:
                        vs_path = Path(install["installationPath"])
                        vc_path = vs_path / "VC" / "Tools" / "MSVC"
                        if vc_path.exists():
                            for version_dir in sorted(vc_path.iterdir(), reverse=True):
                                for arch in ["x64", "x86"]:
                                    cl_path = version_dir / "bin" / f"Host{arch}" / arch / "cl.exe"
                                    if cl_path.exists():
                                        candidate = self._create_candidate(cl_path)
                                        if candidate:
                                            candidate.metadata["vs_path"] = str(vs_path)
                                            candidates.append(candidate)

            except Exception:
                continue

        return candidates

    def _already_detected(self, candidate: CompilerCandidate, existing: List[CompilerCandidate]) -> bool:
        """
        Check if a candidate is already in the list.

        Parameters
        ----------
        candidate : CompilerCandidate
            Candidate to check.
        existing : List[CompilerCandidate]
            Existing candidates.

        Returns
        -------
        bool
            True if already detected.
        """
        for c in existing:
            if c.executable_path == candidate.executable_path:
                return True
            if c.version_tuple == candidate.version_tuple and c.target_arch == candidate.target_arch:
                return True
        return False

    def _create_candidate(self, path: Path) -> Optional[CompilerCandidate]:
        """
        Create a candidate from an executable path.

        Parameters
        ----------
        path : Path
            Executable path.

        Returns
        -------
        Optional[CompilerCandidate]
            Candidate or None.
        """
        version_tuple = self.probe_version(path)
        if not version_tuple:
            return None

        version_str = f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"
        target = self.probe_target(path)
        features = self.probe_features(path)

        return CompilerCandidate(
            name="msvc",
            family=self.family,
            executable_path=path,
            version=version_str,
            version_tuple=version_tuple,
            priority=CompilerPriority.SYSTEM_DEFAULT,
            platform=self.platform,
            target_arch=target,
            features=features,
            backend_class=MSVCBackend,
        )

    def probe_version(self, executable_path: Path) -> Optional[Tuple[int, int, int]]:
        """
        Probe MSVC version.

        Parameters
        ----------
        executable_path : Path
            Path to cl.exe.

        Returns
        -------
        Optional[Tuple[int, int, int]]
            Version tuple or None.
        """
        output = self._run_probe_command([str(executable_path)], timeout=10)
        if not output:
            return None

        match = self._version_pattern.search(output)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

        # Try to get version from file properties
        try:
            import win32api
            info = win32api.GetFileVersionInfo(str(executable_path), "\\")
            ms = info['FileVersionMS']
            ls = info['FileVersionLS']
            return (ms >> 16, ms & 0xFFFF, ls >> 16)
        except ImportError:
            pass
        except Exception:
            pass

        return None

    def probe_target(self, executable_path: Path) -> str:
        """
        Probe MSVC target architecture.

        Parameters
        ----------
        executable_path : Path
            Path to cl.exe.

        Returns
        -------
        str
            Target architecture string.
        """
        path_str = str(executable_path).lower()
        if "x64" in path_str or "amd64" in path_str:
            return "x86_64"
        elif "arm64" in path_str:
            return "aarch64"
        elif "arm" in path_str:
            return "arm"
        else:
            return "i686"

    def probe_features(self, executable_path: Path) -> CompilerFeature:
        """
        Probe MSVC features.

        Parameters
        ----------
        executable_path : Path
            Path to cl.exe.

        Returns
        -------
        CompilerFeature
            Feature flags.
        """
        features = CompilerFeature.NONE

        version = self.probe_version(executable_path)
        if not version:
            return features

        major, minor, _ = version

        # Version-based features (approximate)
        msc_ver = major * 100 + minor
        if msc_ver >= 1900:  # VS 2015
            features |= CompilerFeature.C11 | CompilerFeature.CPP11 | CompilerFeature.CPP14
        if msc_ver >= 1910:  # VS 2017
            features |= CompilerFeature.CPP17
        if msc_ver >= 1920:  # VS 2019
            features |= CompilerFeature.CPP20
        if msc_ver >= 1930:  # VS 2022
            features |= CompilerFeature.C17 | CompilerFeature.CPP23

        # Test features
        if self._test_flag(executable_path, "/openmp"):
            features |= CompilerFeature.OPENMP
        if self._test_flag(executable_path, "/GL"):
            features |= CompilerFeature.LTO
        if self._test_flag(executable_path, "/arch:AVX2"):
            features |= CompilerFeature.SIMD_AVX2 | CompilerFeature.SIMD_AVX
        elif self._test_flag(executable_path, "/arch:AVX"):
            features |= CompilerFeature.SIMD_AVX

        return features

    def _test_flag(self, exe: Path, flag: str) -> bool:
        """
        Test if a compiler flag is supported.

        Parameters
        ----------
        exe : Path
            Compiler executable.
        flag : str
            Flag to test.

        Returns
        -------
        bool
            True if flag is supported.
        """
        with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
            f.write("int main() { return 0; }")
            test_file = Path(f.name)

        try:
            with tempfile.NamedTemporaryFile(suffix=".obj", delete=False) as f:
                output = Path(f.name)

            cmd = [str(exe), "/c", str(test_file), f"/Fo{output}", flag, "/nologo"]
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            output.unlink(missing_ok=True)
            return result.returncode == 0
        except Exception:
            return False
        finally:
            test_file.unlink(missing_ok=True)


class ICCDetector(CompilerDetector):
    """
    Intel C++ Compiler (ICC/ICX) detector.

    Detects both classic ICC and LLVM-based ICX installations.
    """

    name = "icc"
    family = CompilerFamily.INTEL

    def __init__(self):
        super().__init__()
        self._version_pattern = re.compile(
            r"(?:icc|icpc|icx|icpx)\s+(?:\([^)]+\)\s+)?(\d+)\.(\d+)\.(\d+)",
            re.IGNORECASE
        )

        self._common_paths: Dict[PlatformType, List[Path]] = {
            PlatformType.LINUX: [
                Path("/opt/intel/oneapi/compiler/latest/bin"),
                Path("/opt/intel/bin"),
                Path("/opt/intel/compilers_and_libraries/linux/bin"),
            ],
            PlatformType.MACOS: [
                Path("/opt/intel/oneapi/compiler/latest/bin"),
                Path("/opt/intel/bin"),
            ],
            PlatformType.WINDOWS: [
                Path("C:\\Program Files (x86)\\Intel\\oneAPI\\compiler\\latest\\bin"),
                Path("C:\\Program Files\\Intel\\Compiler\\bin"),
            ],
        }

    def detect(self) -> List[CompilerCandidate]:
        """
        Detect all Intel compiler installations.

        Returns
        -------
        List[CompilerCandidate]
            List of detected Intel compiler candidates.
        """
        candidates: List[CompilerCandidate] = []
        seen_paths: Set[Path] = set()

        # Search in PATH
        for name in ["icx", "icpx", "icc", "icpc"]:
            exe = shutil.which(name)
            if exe:
                path = Path(exe)
                if path not in seen_paths:
                    seen_paths.add(path)
                    candidate = self._create_candidate(path)
                    if candidate:
                        candidates.append(candidate)

        # Search common paths
        for base in self._common_paths.get(self.platform, []):
            if not base.exists():
                continue

            for name in ["icx", "icpx", "icc", "icpc"]:
                exe = base / name
                if self.platform == PlatformType.WINDOWS:
                    exe = base / f"{name}.exe"

                if exe.exists() and exe not in seen_paths:
                    seen_paths.add(exe)
                    candidate = self._create_candidate(exe)
                    if candidate:
                        candidates.append(candidate)

        candidates.sort(key=lambda c: c.version_tuple, reverse=True)
        return candidates

    def _create_candidate(self, path: Path) -> Optional[CompilerCandidate]:
        """
        Create a candidate from an executable path.

        Parameters
        ----------
        path : Path
            Executable path.

        Returns
        -------
        Optional[CompilerCandidate]
            Candidate or None.
        """
        version_tuple = self.probe_version(path)
        if not version_tuple:
            return None

        version_str = f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"
        target = self.probe_target(path)
        features = self.probe_features(path)

        # Determine if it's ICX or classic ICC
        is_icx = "icx" in path.name.lower()

        return CompilerCandidate(
            name="icx" if is_icx else "icc",
            family=self.family,
            executable_path=path,
            version=version_str,
            version_tuple=version_tuple,
            priority=CompilerPriority.SYSTEM_DEFAULT,
            platform=self.platform,
            target_arch=target,
            features=features,
            backend_class=ICCBackend,
            metadata={"compiler": "intel", "icx": is_icx},
        )

    def probe_version(self, executable_path: Path) -> Optional[Tuple[int, int, int]]:
        """
        Probe Intel compiler version.

        Parameters
        ----------
        executable_path : Path
            Path to compiler executable.

        Returns
        -------
        Optional[Tuple[int, int, int]]
            Version tuple or None.
        """
        output = self._run_probe_command([str(executable_path), "--version"])
        if not output:
            return None

        match = self._version_pattern.search(output)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

        # Try alternative pattern for oneAPI
        pattern2 = re.compile(r"Intel.*oneAPI.*(\d+)\.(\d+)\.(\d+)", re.IGNORECASE)
        match = pattern2.search(output)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

        return None

    def probe_features(self, executable_path: Path) -> CompilerFeature:
        """
        Probe Intel compiler features.

        Parameters
        ----------
        executable_path : Path
            Path to compiler executable.

        Returns
        -------
        CompilerFeature
            Feature flags.
        """
        features = CompilerFeature.NONE

        version = self.probe_version(executable_path)
        if not version:
            return features

        major, minor, _ = version

        # Version-based features
        if major >= 2021:  # ICX
            features |= (CompilerFeature.C11 | CompilerFeature.C17 |
                        CompilerFeature.CPP11 | CompilerFeature.CPP14 |
                        CompilerFeature.CPP17 | CompilerFeature.CPP20)
            if minor >= 2:
                features |= CompilerFeature.CPP23
        else:  # Classic ICC
            if (major, minor) >= (15, 0):
                features |= CompilerFeature.CPP11 | CompilerFeature.CPP14
            if (major, minor) >= (16, 0):
                features |= CompilerFeature.C11
            if (major, minor) >= (17, 0):
                features |= CompilerFeature.CPP17
            if (major, minor) >= (19, 0):
                features |= CompilerFeature.C17

        # Test features
        if self._test_flag(executable_path, "-qopenmp") or self._test_flag(executable_path, "-fiopenmp"):
            features |= CompilerFeature.OPENMP
        if self._test_flag(executable_path, "-ipo"):
            features |= CompilerFeature.LTO

        return features

    def _test_flag(self, exe: Path, flag: str) -> bool:
        """
        Test if a compiler flag is supported.

        Parameters
        ----------
        exe : Path
            Compiler executable.
        flag : str
            Flag to test.

        Returns
        -------
        bool
            True if flag is supported.
        """
        with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
            f.write("int main() { return 0; }")
            test_file = Path(f.name)

        try:
            with tempfile.NamedTemporaryFile(suffix=".o", delete=False) as f:
                output = Path(f.name)

            cmd = [str(exe), "-c", str(test_file), "-o", str(output), flag]
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            output.unlink(missing_ok=True)
            return result.returncode == 0
        except Exception:
            return False
        finally:
            test_file.unlink(missing_ok=True)


class CompilerRegistry:
    """
    Central registry for compiler detection and management.

    This class coordinates all compiler detectors and provides a unified
    interface for discovering, selecting, and instantiating compilers.

    Attributes
    ----------
    _detectors : List[CompilerDetector]
        List of registered detectors.
    _candidates : List[CompilerCandidate]
        Cached list of all detected candidates.
    _lock : RLock
        Thread lock for cache access.
    _preferred_compiler : Optional[str]
        User-preferred compiler name.
    _platform : PlatformType
        Current platform.

    Examples
    --------
    >>> registry = CompilerRegistry()
    >>> registry.register_detector(GCCDetector())
    >>> registry.register_detector(ClangDetector())
    >>> 
    >>> # Get all available compilers
    >>> all_compilers = registry.detect_all()
    >>> for c in all_compilers:
    ...     print(f"{c.name} {c.version}")
    >>> 
    >>> # Get best compiler for current platform
    >>> best = registry.get_best_compiler()
    >>> if best:
    ...     backend = best.create_backend()
    ...     result = backend.compile(...)
    >>> 
    >>> # Get specific compiler
    >>> clang = registry.get_compiler("clang", min_version=(15, 0, 0))
    >>> if clang:
    ...     backend = clang.create_backend()
    """

    # Platform-specific compiler preferences
    PLATFORM_PREFERENCES: Dict[PlatformType, List[str]] = {
        PlatformType.LINUX: ["clang", "gcc", "icc"],
        PlatformType.MACOS: ["apple-clang", "clang", "gcc"],
        PlatformType.WINDOWS: ["msvc", "clang", "gcc", "icc"],
        PlatformType.BSD: ["clang", "gcc"],
        PlatformType.OTHER: ["clang", "gcc"],
    }

    def __init__(self):
        self._detectors: List[CompilerDetector] = []
        self._candidates: List[CompilerCandidate] = []
        self._lock = RLock()
        self._preferred_compiler: Optional[str] = None
        self._platform = PlatformType.current()

        # Register default detectors for current platform
        self._register_default_detectors()

    def _register_default_detectors(self) -> None:
        """
        Register default detectors for current platform.
        """
        # Common detectors for all platforms
        self.register_detector(ClangDetector())

        # Platform-specific detectors
        if self._platform == PlatformType.WINDOWS:
            self.register_detector(MSVCDetector())
            self.register_detector(GCCDetector())  # MinGW
        elif self._platform == PlatformType.LINUX:
            self.register_detector(GCCDetector())
            self.register_detector(ICCDetector())
        elif self._platform == PlatformType.MACOS:
            self.register_detector(GCCDetector())  # Actually Clang on macOS
        else:
            self.register_detector(GCCDetector())

    def register_detector(self, detector: CompilerDetector) -> None:
        """
        Register a compiler detector.

        Parameters
        ----------
        detector : CompilerDetector
            Detector to register.
        """
        with self._lock:
            self._detectors.append(detector)

    def set_preferred_compiler(self, name: str) -> None:
        """
        Set user-preferred compiler.

        Parameters
        ----------
        name : str
            Preferred compiler name (e.g., 'gcc', 'clang', 'msvc').
        """
        with self._lock:
            self._preferred_compiler = name.lower()
            self._candidates.clear()  # Clear cache to reprioritize

    def detect_all(self, force_refresh: bool = False) -> List[CompilerCandidate]:
        """
        Detect all available compilers.

        Parameters
        ----------
        force_refresh : bool
            Force refresh of detection cache.

        Returns
        -------
        List[CompilerCandidate]
            List of all detected compiler candidates.
        """
        with self._lock:
            if not self._candidates or force_refresh:
                self._candidates = self._do_detection()
            return self._candidates.copy()

    def _do_detection(self) -> List[CompilerCandidate]:
        """
        Perform actual compiler detection.

        Returns
        -------
        List[CompilerCandidate]
            Detected candidates with priorities assigned.
        """
        all_candidates: List[CompilerCandidate] = []

        for detector in self._detectors:
            try:
                candidates = detector.detect()
                all_candidates.extend(candidates)
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug(f"Detector {detector.name} failed: {e}")

        # Assign priorities
        self._assign_priorities(all_candidates)

        # Sort by priority then version
        all_candidates.sort(key=lambda c: (c.priority.value, c.version_tuple), reverse=True)

        return all_candidates

    def _assign_priorities(self, candidates: List[CompilerCandidate]) -> None:
        """
        Assign priority levels to candidates.

        Parameters
        ----------
        candidates : List[CompilerCandidate]
            Candidates to prioritize.
        """
        preferences = self.PLATFORM_PREFERENCES.get(self._platform, ["clang", "gcc"])

        for candidate in candidates:
            # Check if it's the preferred compiler
            if self._preferred_compiler and candidate.name == self._preferred_compiler:
                candidate.priority = CompilerPriority.PREFERRED
                continue

            # Check platform preferences
            if candidate.name in preferences:
                index = preferences.index(candidate.name)
                # Map index to valid priority enum values only
                priority_map = {
                    0: CompilerPriority.OPTIMAL,      # First choice - 85
                    1: CompilerPriority.HIGH,          # Second choice - 75
                    2: CompilerPriority.MEDIUM,        # Third choice - 55
                    3: CompilerPriority.MEDIUM_LOW,    # Fourth choice - 45
                    4: CompilerPriority.LOW,           # Fifth choice - 30
                }
                candidate.priority = priority_map.get(index, CompilerPriority.VERY_LOW)
            else:
                candidate.priority = CompilerPriority.SYSTEM_DEFAULT

    def get_compiler(
        self,
        name: Optional[str] = None,
        family: Optional[CompilerFamily] = None,
        min_version: Optional[Tuple[int, int, int]] = None,
        target_arch: Optional[str] = None,
    ) -> Optional[CompilerCandidate]:
        """
        Get a specific compiler by criteria.

        Parameters
        ----------
        name : Optional[str]
            Compiler name (e.g., 'gcc', 'clang').
        family : Optional[CompilerFamily]
            Compiler family.
        min_version : Optional[Tuple[int, int, int]]
            Minimum version required.
        target_arch : Optional[str]
            Target architecture.

        Returns
        -------
        Optional[CompilerCandidate]
            Matching compiler candidate or None.
        """
        candidates = self.detect_all()

        for candidate in candidates:
            if name and candidate.name != name:
                continue
            if family and candidate.family != family:
                continue
            if min_version and candidate.version_tuple < min_version:
                continue
            if target_arch and candidate.target_arch != target_arch:
                continue
            return candidate

        return None

    def get_best_compiler(
        self,
        min_version: Optional[Tuple[int, int, int]] = None,
        required_features: Optional[CompilerFeature] = None,
    ) -> Optional[CompilerCandidate]:
        """
        Get the best available compiler.

        Parameters
        ----------
        min_version : Optional[Tuple[int, int, int]]
            Minimum version required.
        required_features : Optional[CompilerFeature]
            Required feature flags.

        Returns
        -------
        Optional[CompilerCandidate]
            Best matching compiler candidate.
        """
        candidates = self.detect_all()

        for candidate in candidates:
            if min_version and candidate.version_tuple < min_version:
                continue
            if required_features and not (candidate.features & required_features):
                continue
            return candidate

        return None

    def get_all_compilers(self) -> Dict[str, List[CompilerCandidate]]:
        """
        Get all compilers grouped by name.

        Returns
        -------
        Dict[str, List[CompilerCandidate]]
            Dictionary of compiler name to list of candidates.
        """
        grouped: Dict[str, List[CompilerCandidate]] = {}
        for candidate in self.detect_all():
            if candidate.name not in grouped:
                grouped[candidate.name] = []
            grouped[candidate.name].append(candidate)
        return grouped

    def create_backend(
        self,
        name: Optional[str] = None,
        **kwargs,
    ) -> Optional[CompilerBackend]:
        """
        Create a compiler backend instance.

        Parameters
        ----------
        name : Optional[str]
            Compiler name. Uses best available if None.
        **kwargs : Any
            Additional arguments for backend constructor.

        Returns
        -------
        Optional[CompilerBackend]
            Compiler backend instance or None.
        """
        if name:
            candidate = self.get_compiler(name=name)
        else:
            candidate = self.get_best_compiler()

        if candidate:
            return candidate.create_backend(**kwargs)
        return None

    def clear_cache(self) -> None:
        """
        Clear all detection caches.
        """
        with self._lock:
            self._candidates.clear()
            for detector in self._detectors:
                detector.clear_cache()

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get detection statistics.

        Returns
        -------
        Dict[str, Any]
            Statistics dictionary.
        """
        candidates = self.detect_all()
        grouped = self.get_all_compilers()

        return {
            "total_detected": len(candidates),
            "compilers_found": list(grouped.keys()),
            "counts": {name: len(cands) for name, cands in grouped.items()},
            "platform": self._platform.value,
            "preferred": self._preferred_compiler,
        }


# Global registry instance
_global_registry: Optional[CompilerRegistry] = None


def get_compiler_registry() -> CompilerRegistry:
    """
    Get the global compiler registry instance.

    Returns
    -------
    CompilerRegistry
        Global registry instance.
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = CompilerRegistry()
    return _global_registry


def detect_compiler(name: Optional[str] = None) -> Optional[CompilerBackend]:
    """
    Convenience function to detect and create a compiler backend.

    Parameters
    ----------
    name : Optional[str]
        Compiler name. Auto-detects best if None.

    Returns
    -------
    Optional[CompilerBackend]
        Compiler backend instance or None.
    """
    return get_compiler_registry().create_backend(name)


def list_compilers() -> List[str]:
    """
    List all available compiler names.

    Returns
    -------
    List[str]
        List of available compiler names.
    """
    registry = get_compiler_registry()
    grouped = registry.get_all_compilers()
    return list(grouped.keys())


class CompilerDetector(ABC):
    """Abstract base class for compiler-specific detectors."""
    pass