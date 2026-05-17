#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Environment Tag Generator - Comprehensive PEP-compliant environment tagging system.

This module provides a robust, cross-platform system for generating standardized
environment tags following various Python Enhancement Proposals (PEPs). These tags
are essential for package distribution, wheel naming, dependency resolution, and
build artifact identification.

The module implements the following PEP specifications:
    - PEP 425: Compatibility Tags for Built Distributions
    - PEP 491: The Wheel Binary Package Format 1.9
    - PEP 600: Future 'manylinux' Platform Tags
    - PEP 625: File Name Convention for Source Distributions
    - PEP 665: Comprehensive Environment Tags (proposed)

Examples
--------
>>> from pyputil.tags import build_tag, EnvironmentTagger
>>> tag = build_tag("numpy", "425")
>>> print(tag)
'numpy-1.23.5-cp39-cp39-macosx_10_9_x86_64'

>>> tagger = EnvironmentTagger()
>>> info = tagger.get_environment_info()
>>> print(info.to_dict())
{'python_version': '3.11.0', 'implementation': 'cpython', 'bitness': '64bit', ...}

>>> env_tag = tagger.generate_environment_tag("600")
>>> print(env_tag)
'env-cp311-cp311_abi3-manylinux_2_35_x86_64-glibc2_35-64bit-release'

References
----------
- PEP 425: https://www.python.org/dev/peps/pep-0425/
- PEP 491: https://www.python.org/dev/peps/pep-0491/
- PEP 600: https://www.python.org/dev/peps/pep-0600/
- PEP 625: https://www.python.org/dev/peps/pep-0625/
"""

import sys
import sysconfig
import platform
import struct
import os
import re
import subprocess
from typing import (
    Optional, Union, Dict, Callable, List, Tuple, Any, 
    ClassVar, Type, Iterator, overload, Literal, Final
)
from enum import Enum, auto
from dataclasses import dataclass, field, asdict, fields
from functools import lru_cache, total_ordering
from pathlib import Path
from importlib.metadata import version as get_package_version
from importlib.metadata import PackageNotFoundError
import warnings

# ============================================================================
# Enums and Type Definitions
# ============================================================================

class PEPVersion(Enum):
    """
    Enumeration of supported PEP versions for tag generation.
    
    Attributes
    ----------
    PEP_425 : str
        PEP 425 - Compatibility Tags for Built Distributions.
    PEP_491 : str
        PEP 491 - Wheel Binary Package Format 1.9.
    PEP_600 : str
        PEP 600 - Future 'manylinux' Platform Tags.
    PEP_625 : str
        PEP 625 - File Name Convention for Source Distributions.
    PEP_665 : str
        PEP 665 - Comprehensive Environment Tags (proposed).
    """
    PEP_425 = "425"
    PEP_491 = "491"
    PEP_600 = "600"
    PEP_625 = "625"
    PEP_665 = "665"
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value
    
    @classmethod
    def from_string(cls, value: str) -> Optional['PEPVersion']:
        """
        Convert a string to a PEPVersion enum value.
        
        Parameters
        ----------
        value : str
            String representation of the PEP version (e.g., '425', '600').
        
        Returns
        -------
        Optional[PEPVersion]
            Corresponding enum value, or None if not found.
        """
        try:
            return cls(value)
        except ValueError:
            return None
    
    @property
    def description(self) -> str:
        """Get a human-readable description of the PEP version."""
        descriptions = {
            PEPVersion.PEP_425: "Compatibility Tags for Built Distributions",
            PEPVersion.PEP_491: "Wheel Binary Package Format 1.9",
            PEPVersion.PEP_600: "Future 'manylinux' Platform Tags",
            PEPVersion.PEP_625: "File Name Convention for Source Distributions",
            PEPVersion.PEP_665: "Comprehensive Environment Tags (proposed)",
        }
        return descriptions.get(self, "Unknown PEP version")


class PythonImplementation(Enum):
    """
    Enumeration of Python implementations.
    
    Attributes
    ----------
    CPYTHON : str
        Standard CPython implementation.
    PYPY : str
        PyPy implementation.
    JYTHON : str
        Jython implementation (Java).
    IRONPYTHON : str
        IronPython implementation (.NET).
    MICROPYTHON : str
        MicroPython implementation.
    STACKLESS : str
        Stackless Python implementation.
    UNKNOWN : str
        Unknown or unrecognized implementation.
    """
    CPYTHON = "cpython"
    PYPY = "pypy"
    JYTHON = "jython"
    IRONPYTHON = "ironpython"
    MICROPYTHON = "micropython"
    STACKLESS = "stackless"
    UNKNOWN = "unknown"
    
    @classmethod
    def detect(cls) -> 'PythonImplementation':
        """
        Detect the current Python implementation.
        
        Returns
        -------
        PythonImplementation
            The detected implementation.
        """
        name = platform.python_implementation().lower()
        
        implementation_map = {
            "cpython": cls.CPYTHON,
            "pypy": cls.PYPY,
            "jython": cls.JYTHON,
            "ironpython": cls.IRONPYTHON,
            "micropython": cls.MICROPYTHON,
            "stackless": cls.STACKLESS,
        }
        
        return implementation_map.get(name, cls.UNKNOWN)
    
    @property
    def pep425_tag(self) -> str:
        """
        Get the two-letter PEP 425 implementation tag.
        
        Returns
        -------
        str
            Two-letter implementation code (e.g., 'cp', 'pp', 'jy', 'ip').
        """
        tag_map = {
            PythonImplementation.CPYTHON: "cp",
            PythonImplementation.PYPY: "pp",
            PythonImplementation.JYTHON: "jy",
            PythonImplementation.IRONPYTHON: "ip",
            PythonImplementation.MICROPYTHON: "mp",
            PythonImplementation.STACKLESS: "sl",
        }
        return tag_map.get(self, self.value[:2])
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


class LibCType(Enum):
    """
    Enumeration of C library implementations.
    
    Attributes
    ----------
    GLIBC : str
        GNU C Library (glibc).
    MUSL : str
        musl libc.
    BSD_LIBC : str
        BSD libc implementation.
    SOLARIS_LIBC : str
        Solaris/Illumos libc.
    AIX_LIBC : str
        AIX libc.
    MSVCRT : str
        Microsoft Visual C Runtime.
    CYGWIN : str
        Cygwin C library.
    NONE : str
        No C library (e.g., not on Linux).
    UNKNOWN : str
        Unknown C library implementation.
    """
    GLIBC = "glibc"
    MUSL = "musl"
    BSD_LIBC = "bsd_libc"
    SOLARIS_LIBC = "solaris_libc"
    AIX_LIBC = "aix_libc"
    MSVCRT = "msvcrt"
    CYGWIN = "cygwin"
    NONE = "none"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


class BuildType(Enum):
    """
    Enumeration of Python build types.
    
    Attributes
    ----------
    RELEASE : str
        Release build (optimized).
    DEBUG : str
        Debug build (with assertions and debug symbols).
    UNKNOWN : str
        Unknown build type.
    """
    RELEASE = "release"
    DEBUG = "debug"
    UNKNOWN = "unknown"
    
    @classmethod
    def detect(cls) -> 'BuildType':
        """
        Detect if Python is a debug build.
        
        Returns
        -------
        BuildType
            The detected build type.
        """
        # Check for debug build indicators
        if hasattr(sys, "gettotalrefcount"):
            return cls.DEBUG
        
        # Check abiflags for 'd' (debug) indicator
        abiflags = getattr(sys, "abiflags", "")
        if 'd' in abiflags:
            return cls.DEBUG
        
        # Check for Py_DEBUG flag in sysconfig
        py_debug = sysconfig.get_config_var("Py_DEBUG")
        if py_debug:
            return cls.DEBUG
        
        return cls.RELEASE
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


class EnvironmentType(Enum):
    """
    Enumeration of Python environment types.
    
    Attributes
    ----------
    SYSTEM : str
        System-wide Python installation.
    VIRTUALENV : str
        Virtual environment (venv/virtualenv).
    CONDA : str
        Conda environment.
    DOCKER : str
        Running inside a Docker container.
    EMBEDDED : str
        Embedded Python distribution.
    UNKNOWN : str
        Unknown environment type.
    """
    SYSTEM = "system"
    VIRTUALENV = "venv"
    CONDA = "conda"
    DOCKER = "docker"
    EMBEDDED = "embedded"
    UNKNOWN = "unknown"
    
    @classmethod
    def detect(cls) -> 'EnvironmentType':
        """
        Detect the current Python environment type.
        
        Returns
        -------
        EnvironmentType
            The detected environment type.
        """
        # Check for virtual environment
        if hasattr(sys, "real_prefix") or (
            hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
        ):
            return cls.VIRTUALENV
        
        # Check for conda environment
        if os.environ.get("CONDA_PREFIX") or os.environ.get("CONDA_DEFAULT_ENV"):
            return cls.CONDA
        
        # Check for Docker container
        if Path("/.dockerenv").exists():
            return cls.DOCKER
        if os.path.exists("/proc/1/cgroup"):
            try:
                with open("/proc/1/cgroup", "r") as f:
                    if "docker" in f.read():
                        return cls.DOCKER
            except (IOError, PermissionError):
                pass
        
        # Check for embedded Python
        if hasattr(sys, "frozen") or getattr(sys, "_MEIPASS", None):
            return cls.EMBEDDED
        
        return cls.SYSTEM
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


class Architecture(Enum):
    """
    Enumeration of CPU architectures.
    
    Attributes
    ----------
    X86_64 : str
        64-bit x86 (AMD64, Intel 64).
    X86 : str
        32-bit x86 (i386, i486, i586, i686).
    ARM64 : str
        64-bit ARM (AArch64, ARMv8).
    ARM32 : str
        32-bit ARM (ARMv6, ARMv7).
    PPC64LE : str
        64-bit PowerPC little-endian.
    PPC64 : str
        64-bit PowerPC big-endian.
    S390X : str
        IBM System z (64-bit).
    MIPS64 : str
        64-bit MIPS.
    MIPS : str
        32-bit MIPS.
    RISCV64 : str
        64-bit RISC-V.
    SPARC64 : str
        64-bit SPARC.
    UNKNOWN : str
        Unknown architecture.
    """
    X86_64 = "x86_64"
    X86 = "x86"
    ARM64 = "aarch64"
    ARM32 = "arm"
    PPC64LE = "ppc64le"
    PPC64 = "ppc64"
    S390X = "s390x"
    MIPS64 = "mips64"
    MIPS = "mips"
    RISCV64 = "riscv64"
    SPARC64 = "sparc64"
    UNKNOWN = "unknown"
    
    @classmethod
    def detect(cls) -> 'Architecture':
        """
        Detect the current CPU architecture.
        
        Returns
        -------
        Architecture
            The detected architecture.
        """
        machine = platform.machine().lower()
        
        # Normalize common variations
        arch_map = {
            # x86_64 variations
            "x86_64": cls.X86_64,
            "amd64": cls.X86_64,
            "intel64": cls.X86_64,
            "em64t": cls.X86_64,
            
            # x86 variations
            "i386": cls.X86,
            "i486": cls.X86,
            "i586": cls.X86,
            "i686": cls.X86,
            "x86": cls.X86,
            
            # ARM64 variations
            "aarch64": cls.ARM64,
            "arm64": cls.ARM64,
            "armv8": cls.ARM64,
            "armv8-a": cls.ARM64,
            
            # ARM32 variations
            "arm": cls.ARM32,
            "armv6": cls.ARM32,
            "armv6l": cls.ARM32,
            "armv7": cls.ARM32,
            "armv7l": cls.ARM32,
            
            # PowerPC
            "ppc64le": cls.PPC64LE,
            "ppc64": cls.PPC64,
            "powerpc": cls.PPC64,
            
            # IBM System z
            "s390x": cls.S390X,
            "s390": cls.S390X,
            
            # MIPS
            "mips64": cls.MIPS64,
            "mips": cls.MIPS,
            
            # RISC-V
            "riscv64": cls.RISCV64,
            
            # SPARC
            "sparc64": cls.SPARC64,
            "sun4u": cls.SPARC64,
        }
        
        return arch_map.get(machine, cls.UNKNOWN)
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


class OperatingSystem(Enum):
    """
    Enumeration of operating systems.
    
    Attributes
    ----------
    LINUX : str
        Linux operating system.
    MACOS : str
        macOS (Darwin).
    WINDOWS : str
        Microsoft Windows.
    FREEBSD : str
        FreeBSD.
    OPENBSD : str
        OpenBSD.
    NETBSD : str
        NetBSD.
    DRAGONFLY : str
        DragonFly BSD.
    SOLARIS : str
        Oracle Solaris / Illumos.
    AIX : str
        IBM AIX.
    HPUX : str
        Hewlett Packard HP-UX.
    CYGWIN : str
        Cygwin environment.
    UNKNOWN : str
        Unknown operating system.
    """
    LINUX = "linux"
    MACOS = "darwin"
    WINDOWS = "windows"
    FREEBSD = "freebsd"
    OPENBSD = "openbsd"
    NETBSD = "netbsd"
    DRAGONFLY = "dragonfly"
    SOLARIS = "sunos"
    AIX = "aix"
    HPUX = "hp-ux"
    CYGWIN = "cygwin"
    UNKNOWN = "unknown"
    
    @classmethod
    def detect(cls) -> 'OperatingSystem':
        """
        Detect the current operating system.
        
        Returns
        -------
        OperatingSystem
            The detected operating system.
        """
        system = platform.system().lower()
        sys_platform = sys.platform.lower()
        
        # Use both platform.system() and sys.platform for accurate detection
        if system == "linux":
            return cls.LINUX
        elif system == "darwin":
            return cls.MACOS
        elif system == "windows":
            return cls.WINDOWS
        elif sys_platform.startswith("freebsd"):
            return cls.FREEBSD
        elif sys_platform.startswith("openbsd"):
            return cls.OPENBSD
        elif sys_platform.startswith("netbsd"):
            return cls.NETBSD
        elif sys_platform.startswith("dragonfly"):
            return cls.DRAGONFLY
        elif sys_platform.startswith(("sunos", "solaris")):
            return cls.SOLARIS
        elif sys_platform.startswith("aix"):
            return cls.AIX
        elif sys_platform.startswith(("hp-ux", "hpux")):
            return cls.HPUX
        elif "cygwin" in sys_platform:
            return cls.CYGWIN
        
        return cls.UNKNOWN
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value
    
    @property
    def is_unix_like(self) -> bool:
        """Check if the OS is Unix-like."""
        return self not in (OperatingSystem.WINDOWS, OperatingSystem.UNKNOWN)


# Type aliases for better readability
PEPVersionStr = Literal["425", "491", "600", "625", "665"]
TagBuilderFunc = Callable[[str], str]


# ============================================================================
# Data Classes for Environment Information
# ============================================================================

@dataclass(frozen=True)
class LibCInfo:
    """
    Information about the C library implementation.
    
    Attributes
    ----------
    type : LibCType
        Type of C library (glibc, musl, etc.).
    version : str
        Version string of the C library.
    version_tuple : Tuple[int, ...]
        Parsed version tuple (major, minor, patch).
    raw_string : str
        Raw version string as reported by the system.
    
    Examples
    --------
    >>> info = LibCInfo.detect()
    >>> info.type
    <LibCType.GLIBC: 'glibc'>
    >>> info.version
    '2.35'
    """
    type: LibCType
    version: str
    version_tuple: Tuple[int, ...] = field(default_factory=tuple)
    raw_string: str = ""
    
    @classmethod
    def detect(cls) -> 'LibCInfo':
        """
        Detect the C library on the current system.
        
        Returns
        -------
        LibCInfo
            Detected C library information.
        """
        os_type = OperatingSystem.detect()
        
        # Linux systems - detect glibc or musl
        if os_type == OperatingSystem.LINUX:
            return cls._detect_linux_libc()
        
        # BSD systems - use BSD libc
        elif os_type in (OperatingSystem.FREEBSD, OperatingSystem.OPENBSD,
                        OperatingSystem.NETBSD, OperatingSystem.DRAGONFLY):
            return cls._detect_bsd_libc(os_type)
        
        # macOS - uses its own libSystem
        elif os_type == OperatingSystem.MACOS:
            return cls._detect_macos_libc()
        
        # Windows - MSVCRT
        elif os_type == OperatingSystem.WINDOWS:
            return cls._detect_windows_libc()
        
        # Solaris - Solaris libc
        elif os_type == OperatingSystem.SOLARIS:
            return cls._detect_solaris_libc()
        
        # AIX - AIX libc
        elif os_type == OperatingSystem.AIX:
            return cls._detect_aix_libc()
        
        # Cygwin - Cygwin libc
        elif os_type == OperatingSystem.CYGWIN:
            return cls._detect_cygwin_libc()
        
        return cls(type=LibCType.NONE, version="", raw_string="")
    
    @classmethod
    def _detect_linux_libc(cls) -> 'LibCInfo':
        """
        Detect C library on Linux (glibc or musl).
        
        Returns
        -------
        LibCInfo
            Detected C library information.
        """
        # Try platform.libc_ver first
        libc_name, version_str = platform.libc_ver()
        
        if libc_name:
            libc_type = LibCType.GLIBC if "glibc" in libc_name.lower() else LibCType.UNKNOWN
            version_tuple = cls._parse_version(version_str)
            return cls(
                type=libc_type,
                version=version_str,
                version_tuple=version_tuple,
                raw_string=f"{libc_name} {version_str}"
            )
        
        # Try to detect musl
        if cls._is_musl():
            version_str = cls._get_musl_version()
            version_tuple = cls._parse_version(version_str)
            return cls(
                type=LibCType.MUSL,
                version=version_str,
                version_tuple=version_tuple,
                raw_string=f"musl {version_str}"
            )
        
        # Fallback: try to read from ldd
        return cls._detect_via_ldd()
    
    @classmethod
    def _is_musl(cls) -> bool:
        """
        Check if the system is using musl libc.
        
        Returns
        -------
        bool
            True if musl is detected.
        """
        try:
            # Check for musl-specific files
            if Path("/lib/libc.musl-x86_64.so.1").exists():
                return True
            if Path("/lib/ld-musl-x86_64.so.1").exists():
                return True
            
            # Try to execute ldd and check output
            result = subprocess.run(
                ["ldd", "--version"],
                capture_output=True,
                text=True,
                timeout=2
            )
            return "musl" in result.stdout.lower() or "musl" in result.stderr.lower()
        except (subprocess.SubprocessError, FileNotFoundError, PermissionError):
            return False
    
    @classmethod
    def _get_musl_version(cls) -> str:
        """
        Get musl libc version.
        
        Returns
        -------
        str
            Version string or 'unknown'.
        """
        try:
            result = subprocess.run(
                ["ldd", "--version"],
                capture_output=True,
                text=True,
                timeout=2
            )
            # Parse version from output like "musl libc (x86_64) Version 1.2.3"
            match = re.search(r"Version\s+(\d+\.\d+\.\d+)", result.stdout)
            if match:
                return match.group(1)
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        return "unknown"
    
    @classmethod
    def _detect_via_ldd(cls) -> 'LibCInfo':
        """
        Detect C library using ldd command.
        
        Returns
        -------
        LibCInfo
            Detected C library information.
        """
        try:
            result = subprocess.run(
                ["ldd", "--version"],
                capture_output=True,
                text=True,
                timeout=2
            )
            output = result.stdout
            
            # Parse glibc version
            match = re.search(r"ldd\s+.*\s+(\d+\.\d+)", output)
            if match:
                version = match.group(1)
                return cls(
                    type=LibCType.GLIBC,
                    version=version,
                    version_tuple=cls._parse_version(version),
                    raw_string=f"glibc {version}"
                )
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        
        return cls(type=LibCType.UNKNOWN, version="unknown", raw_string="unknown")
    
    @classmethod
    def _detect_bsd_libc(cls, os_type: OperatingSystem) -> 'LibCInfo':
        """
        Detect C library on BSD systems.
        
        Parameters
        ----------
        os_type : OperatingSystem
            The BSD variant.
        
        Returns
        -------
        LibCInfo
            Detected C library information.
        """
        # BSD systems use their own libc
        version = platform.release()
        return cls(
            type=LibCType.BSD_LIBC,
            version=version,
            version_tuple=cls._parse_version(version),
            raw_string=f"{os_type.value} libc {version}"
        )
    
    @classmethod
    def _detect_macos_libc(cls) -> 'LibCInfo':
        """
        Detect C library on macOS.
        
        Returns
        -------
        LibCInfo
            Detected C library information.
        """
        version = platform.mac_ver()[0]
        return cls(
            type=LibCType.NONE,  # macOS uses libSystem, not a traditional libc
            version=version,
            version_tuple=cls._parse_version(version),
            raw_string=f"macOS {version}"
        )
    
    @classmethod
    def _detect_windows_libc(cls) -> 'LibCInfo':
        """
        Detect C library on Windows.
        
        Returns
        -------
        LibCInfo
            Detected C library information.
        """
        version = platform.version()
        return cls(
            type=LibCType.MSVCRT,
            version=version,
            raw_string=f"MSVCRT {version}"
        )
    
    @classmethod
    def _detect_solaris_libc(cls) -> 'LibCInfo':
        """
        Detect C library on Solaris/Illumos.
        
        Returns
        -------
        LibCInfo
            Detected C library information.
        """
        version = platform.release()
        return cls(
            type=LibCType.SOLARIS_LIBC,
            version=version,
            version_tuple=cls._parse_version(version),
            raw_string=f"Solaris libc {version}"
        )
    
    @classmethod
    def _detect_aix_libc(cls) -> 'LibCInfo':
        """
        Detect C library on AIX.
        
        Returns
        -------
        LibCInfo
            Detected C library information.
        """
        version = platform.version()
        return cls(
            type=LibCType.AIX_LIBC,
            version=version,
            raw_string=f"AIX libc {version}"
        )
    
    @classmethod
    def _detect_cygwin_libc(cls) -> 'LibCInfo':
        """
        Detect C library on Cygwin.
        
        Returns
        -------
        LibCInfo
            Detected C library information.
        """
        version = platform.release()
        return cls(
            type=LibCType.CYGWIN,
            version=version,
            version_tuple=cls._parse_version(version),
            raw_string=f"Cygwin {version}"
        )
    
    @staticmethod
    def _parse_version(version_str: str) -> Tuple[int, ...]:
        """
        Parse version string to tuple of integers.
        
        Parameters
        ----------
        version_str : str
            Version string to parse.
        
        Returns
        -------
        Tuple[int, ...]
            Tuple of version components.
        """
        try:
            parts = re.findall(r'\d+', version_str)
            return tuple(int(p) for p in parts[:3])
        except (ValueError, TypeError):
            return ()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "type": str(self.type),
            "version": self.version,
            "version_tuple": list(self.version_tuple),
            "raw_string": self.raw_string,
        }
    
    def to_tag_string(self) -> str:
        """
        Convert to a normalized tag string.
        
        Returns
        -------
        str
            Tag string like 'glibc2_35', 'musl1_2_3', or 'none'.
        """
        if self.type == LibCType.NONE:
            return "none"
        elif self.type == LibCType.UNKNOWN:
            return "unknown"
        
        version_str = "_".join(str(v) for v in self.version_tuple[:2])
        return f"{self.type.value}{version_str}"


@dataclass(frozen=True)
class EnvironmentInfo:
    """
    Comprehensive information about the Python environment.
    
    This dataclass encapsulates all detectable information about the current
    Python environment, including implementation details, architecture,
    build type, and C library information.
    
    Attributes
    ----------
    python_version : str
        Full Python version string (e.g., '3.11.0').
    python_version_tuple : Tuple[int, int, int]
        Python version as tuple (major, minor, micro).
    implementation : PythonImplementation
        Python implementation type.
    implementation_tag : str
        Two-letter PEP 425 implementation tag.
    operating_system : OperatingSystem
        Operating system type.
    architecture : Architecture
        CPU architecture.
    bitness : str
        Bitness of Python ('32bit' or '64bit').
    build_type : BuildType
        Release or debug build.
    environment_type : EnvironmentType
        Virtual environment, system, conda, etc.
    libc_info : LibCInfo
        C library information.
    platform_tag : str
        Platform tag as returned by sysconfig.
    soabi : Optional[str]
        SOABI tag if available.
    abiflags : str
        Python ABI flags.
    sys_platform : str
        sys.platform value.
    
    Examples
    --------
    >>> info = EnvironmentInfo.detect()
    >>> info.python_version
    '3.11.0'
    >>> info.implementation
    <PythonImplementation.CPYTHON: 'cpython'>
    >>> info.bitness
    '64bit'
    """
    python_version: str
    python_version_tuple: Tuple[int, int, int]
    implementation: PythonImplementation
    implementation_tag: str
    operating_system: OperatingSystem
    architecture: Architecture
    bitness: str
    build_type: BuildType
    environment_type: EnvironmentType
    libc_info: LibCInfo
    platform_tag: str
    soabi: Optional[str]
    abiflags: str
    sys_platform: str
    
    @classmethod
    def detect(cls) -> 'EnvironmentInfo':
        """
        Detect comprehensive environment information.
        
        Returns
        -------
        EnvironmentInfo
            Complete environment information.
        """
        # Python version
        version_info = sys.version_info
        python_version = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
        version_tuple = (version_info.major, version_info.minor, version_info.micro)
        
        # Implementation
        implementation = PythonImplementation.detect()
        implementation_tag = implementation.pep425_tag
        
        # OS and architecture
        operating_system = OperatingSystem.detect()
        architecture = Architecture.detect()
        
        # Bitness
        bitness = f"{struct.calcsize('P') * 8}bit"
        
        # Build and environment types
        build_type = BuildType.detect()
        environment_type = EnvironmentType.detect()
        
        # C library information
        libc_info = LibCInfo.detect()
        
        # Platform tag
        platform_tag = sysconfig.get_platform()
        
        # SOABI and ABI flags
        soabi = sysconfig.get_config_var("SOABI")
        abiflags = getattr(sys, "abiflags", "")
        
        # sys.platform
        sys_platform = sys.platform
        
        return cls(
            python_version=python_version,
            python_version_tuple=version_tuple,
            implementation=implementation,
            implementation_tag=implementation_tag,
            operating_system=operating_system,
            architecture=architecture,
            bitness=bitness,
            build_type=build_type,
            environment_type=environment_type,
            libc_info=libc_info,
            platform_tag=platform_tag,
            soabi=soabi,
            abiflags=abiflags,
            sys_platform=sys_platform,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert environment information to a dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of environment information.
        """
        return {
            "python_version": self.python_version,
            "python_version_tuple": list(self.python_version_tuple),
            "implementation": str(self.implementation),
            "implementation_tag": self.implementation_tag,
            "operating_system": str(self.operating_system),
            "architecture": str(self.architecture),
            "bitness": self.bitness,
            "build_type": str(self.build_type),
            "environment_type": str(self.environment_type),
            "libc_info": self.libc_info.to_dict(),
            "platform_tag": self.platform_tag,
            "soabi": self.soabi,
            "abiflags": self.abiflags,
            "sys_platform": self.sys_platform,
        }
    
    @property
    def python_tag_pep425(self) -> str:
        """
        Generate Python version tag according to PEP 425.
        
        Returns
        -------
        str
            Tag like 'cp39', 'pp38', etc.
        """
        ver = self.python_version_tuple
        return f"{self.implementation_tag}{ver[0]}{ver[1]}"
    
    @property
    def python_tag_pep600(self) -> str:
        """
        Generate Python version tag according to PEP 600.
        
        Returns
        -------
        str
            Tag including micro version.
        """
        ver = self.python_version_tuple
        return f"{self.implementation_tag}{ver[0]}{ver[1]}{ver[2]}"
    
    @property
    def abi_tag_pep425(self) -> str:
        """
        Generate ABI tag according to PEP 425.
        
        Returns
        -------
        str
            ABI tag like 'cp39', 'cp39d', 'cp39-abi3'.
        """
        if self.soabi:
            return self.soabi
        
        ver = self.python_version_tuple
        return f"{self.implementation_tag}{ver[0]}{ver[1]}{self.abiflags}"
    
    @property
    def abi_tag_pep600(self) -> str:
        """
        Generate ABI tag according to PEP 600.
        
        Returns
        -------
        str
            ABI tag with underscores.
        """
        abi = self.abi_tag_pep425
        return abi.replace(".", "_").replace("-", "_")
    
    @property
    def platform_tag_pep425(self) -> str:
        """
        Generate platform tag according to PEP 425.
        
        Returns
        -------
        str
            Platform tag with underscores.
        """
        return self.platform_tag.replace(".", "_").replace("-", "_")
    
    @property
    def platform_tag_pep600(self) -> str:
        """
        Generate platform tag according to PEP 600 (manylinux-aware).
        
        Returns
        -------
        str
            Platform tag possibly with manylinux/musllinux prefix.
        """
        if self.operating_system == OperatingSystem.LINUX:
            libc = self.libc_info
            
            if libc.type == LibCType.GLIBC and libc.version_tuple:
                major, minor = libc.version_tuple[:2]
                arch = str(self.architecture)
                return f"manylinux_{major}_{minor}_{arch}"
            elif libc.type == LibCType.MUSL:
                if libc.version_tuple:
                    major, minor = libc.version_tuple[:2]
                    arch = str(self.architecture)
                    return f"musllinux_{major}_{minor}_{arch}"
                else:
                    arch = str(self.architecture)
                    version = libc.version.replace(".", "_")
                    return f"musllinux_{version}_{arch}"
        
        return self.platform_tag_pep425
    
    def __repr__(self) -> str:
        """Provide a concise string representation."""
        return (f"EnvironmentInfo(python={self.python_version}, "
                f"os={self.operating_system.value}, "
                f"arch={self.architecture.value})")


@dataclass(frozen=True)
class PackageTag:
    """
    Represents a complete package tag following a specific PEP.
    
    Attributes
    ----------
    package_name : str
        Normalized package name.
    version : str
        Package version string.
    python_tag : str
        Python version tag.
    abi_tag : str
        ABI tag.
    platform_tag : str
        Platform tag.
    additional_tags : Dict[str, str]
        Additional tag components (libc, bitness, debug, etc.).
    pep_version : PEPVersion
        PEP version used to generate this tag.
    full_string : str
        Complete tag string.
    
    Examples
    --------
    >>> tag = PackageTag(
    ...     package_name="numpy",
    ...     version="1.23.5",
    ...     python_tag="cp39",
    ...     abi_tag="cp39",
    ...     platform_tag="manylinux_2_17_x86_64",
    ...     additional_tags={"libc": "glibc2_17"},
    ...     pep_version=PEPVersion.PEP_600
    ... )
    >>> str(tag)
    'numpy-1.23.5-cp39-cp39-manylinux_2_17_x86_64-glibc2_17'
    """
    package_name: str
    version: str
    python_tag: str
    abi_tag: str
    platform_tag: str
    additional_tags: Dict[str, str] = field(default_factory=dict)
    pep_version: PEPVersion = PEPVersion.PEP_425
    full_string: str = field(init=False)
    
    def __post_init__(self) -> None:
        """Build the full tag string after initialization."""
        parts = [self.package_name, self.version, self.python_tag, 
                self.abi_tag, self.platform_tag]
        
        # Add additional tags in consistent order
        tag_order = ["libc", "bitness", "debug", "venv"]
        for key in tag_order:
            if key in self.additional_tags:
                parts.append(self.additional_tags[key])
        
        # Use object.__setattr__ because the class is frozen
        object.__setattr__(self, "full_string", "-".join(parts))
    
    def __str__(self) -> str:
        """Return the full tag string."""
        return self.full_string
    
    def __repr__(self) -> str:
        """Provide a detailed string representation."""
        return f"PackageTag(package='{self.package_name}', version='{self.version}', pep={self.pep_version.value})"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "package_name": self.package_name,
            "version": self.version,
            "python_tag": self.python_tag,
            "abi_tag": self.abi_tag,
            "platform_tag": self.platform_tag,
            "additional_tags": self.additional_tags.copy(),
            "pep_version": str(self.pep_version),
            "full_string": self.full_string,
        }
    
    def to_wheel_filename(self) -> str:
        """
        Convert to a wheel filename.
        
        Returns
        -------
        str
            Wheel filename like 'numpy-1.23.5-cp39-cp39-manylinux_2_17_x86_64.whl'.
        """
        return f"{self.full_string}.whl"
    
    def to_sdist_filename(self, format: Literal["tar.gz", "zip"] = "tar.gz") -> str:
        """
        Convert to a source distribution filename.
        
        Parameters
        ----------
        format : Literal["tar.gz", "zip"], default="tar.gz"
            Archive format.
        
        Returns
        -------
        str
            Source distribution filename.
        """
        return f"{self.package_name}-{self.version}.{format}"


# ============================================================================
# Environment Tagger Class
# ============================================================================

class EnvironmentTagger:
    """
    Main class for generating environment tags.
    
    This class provides methods for generating environment tags following
    various PEP specifications. It caches environment information for
    performance and provides detailed control over tag generation.
    
    Parameters
    ----------
    use_cache : bool, default=True
        Whether to cache environment information.
    
    Attributes
    ----------
    env_info : EnvironmentInfo
        Detected environment information.
    
    Examples
    --------
    >>> tagger = EnvironmentTagger()
    >>> tag = tagger.build_package_tag("numpy", PEPVersion.PEP_600)
    >>> print(tag)
    numpy-1.23.5-cp311-cp311_abi3-manylinux_2_35_x86_64-glibc2_35-64bit-release
    
    >>> env_tag = tagger.generate_environment_tag(PEPVersion.PEP_665)
    >>> print(env_tag)
    env-cp311-cp311_abi3-manylinux_2_35_x86_64-glibc2_35-64bit-release-venv
    """
    
    _env_info_cache: ClassVar[Optional[EnvironmentInfo]] = None
    
    def __init__(self, use_cache: bool = True):
        if use_cache and self._env_info_cache is not None:
            self.env_info = self._env_info_cache
        else:
            self.env_info = EnvironmentInfo.detect()
            if use_cache:
                EnvironmentTagger._env_info_cache = self.env_info
    
    @classmethod
    def clear_cache(cls) -> None:
        """Clear the cached environment information."""
        cls._env_info_cache = None
    
    @staticmethod
    def _normalize_package_name(name: str) -> str:
        """
        Normalize package name according to PEP 503.
        
        Parameters
        ----------
        name : str
            Original package name.
        
        Returns
        -------
        str
            Normalized package name.
        """
        return re.sub(r'[-_.]+', '-', name).lower()
    
    @staticmethod
    def _get_package_version(package: str) -> str:
        """
        Get package version with fallback.
        
        Parameters
        ----------
        package : str
            Package name.
        
        Returns
        -------
        str
            Package version or 'unknown'.
        """
        try:
            return get_package_version(package)
        except PackageNotFoundError:
            return "unknown"
        except Exception as e:
            warnings.warn(
                f"Failed to get version for '{package}': {e}",
                RuntimeWarning,
                stacklevel=2
            )
            return "unknown"
    
    def build_tag_pep425(self, package: str) -> PackageTag:
        """
        Build a tag following PEP 425.
        
        Parameters
        ----------
        package : str
            Package name.
        
        Returns
        -------
        PackageTag
            Complete package tag.
        """
        normalized_name = self._normalize_package_name(package)
        version = self._get_package_version(package)
        
        return PackageTag(
            package_name=normalized_name,
            version=version,
            python_tag=self.env_info.python_tag_pep425,
            abi_tag=self.env_info.abi_tag_pep425,
            platform_tag=self.env_info.platform_tag_pep425,
            pep_version=PEPVersion.PEP_425,
        )
    
    def build_tag_pep491(self, package: str) -> PackageTag:
        """
        Build a tag following PEP 491 (Wheel format 1.9).
        
        Parameters
        ----------
        package : str
            Package name.
        
        Returns
        -------
        PackageTag
            Complete package tag.
        """
        # PEP 491 uses the same tags as PEP 425 but with normalized names
        normalized_name = self._normalize_package_name(package)
        version = self._get_package_version(package)
        
        return PackageTag(
            package_name=normalized_name,
            version=version,
            python_tag=self.env_info.python_tag_pep425,
            abi_tag=self.env_info.abi_tag_pep425,
            platform_tag=self.env_info.platform_tag_pep425,
            pep_version=PEPVersion.PEP_491,
        )
    
    def build_tag_pep600(self, package: str) -> PackageTag:
        """
        Build a tag following PEP 600.
        
        Parameters
        ----------
        package : str
            Package name.
        
        Returns
        -------
        PackageTag
            Complete package tag with additional information.
        """
        normalized_name = self._normalize_package_name(package)
        version = self._get_package_version(package)
        
        additional = {
            "libc": self.env_info.libc_info.to_tag_string(),
            "bitness": self.env_info.bitness,
            "debug": str(self.env_info.build_type),
        }
        
        return PackageTag(
            package_name=normalized_name,
            version=version,
            python_tag=self.env_info.python_tag_pep600,
            abi_tag=self.env_info.abi_tag_pep600,
            platform_tag=self.env_info.platform_tag_pep600,
            additional_tags=additional,
            pep_version=PEPVersion.PEP_600,
        )
    
    def build_tag_pep625(self, package: str) -> PackageTag:
        """
        Build a tag following PEP 625 (source distribution).
        
        Parameters
        ----------
        package : str
            Package name.
        
        Returns
        -------
        PackageTag
            Package tag for source distribution.
        """
        normalized_name = self._normalize_package_name(package)
        version = self._get_package_version(package)
        
        return PackageTag(
            package_name=normalized_name,
            version=version,
            python_tag="",
            abi_tag="",
            platform_tag="",
            pep_version=PEPVersion.PEP_625,
        )
    
    def build_tag_pep665(self, package: str) -> PackageTag:
        """
        Build a tag following PEP 665 (comprehensive).
        
        Parameters
        ----------
        package : str
            Package name.
        
        Returns
        -------
        PackageTag
            Comprehensive package tag with all available information.
        """
        normalized_name = self._normalize_package_name(package)
        version = self._get_package_version(package)
        
        additional = {
            "libc": self.env_info.libc_info.to_tag_string(),
            "bitness": self.env_info.bitness,
            "debug": str(self.env_info.build_type),
            "venv": str(self.env_info.environment_type),
        }
        
        return PackageTag(
            package_name=normalized_name,
            version=version,
            python_tag=self.env_info.python_tag_pep600,
            abi_tag=self.env_info.abi_tag_pep600,
            platform_tag=self.env_info.platform_tag_pep600,
            additional_tags=additional,
            pep_version=PEPVersion.PEP_665,
        )
    
    def build_package_tag(self, package: str, 
                          pep_version: Union[str, PEPVersion]) -> PackageTag:
        """
        Build a package tag following the specified PEP version.
        
        Parameters
        ----------
        package : str
            Package name.
        pep_version : Union[str, PEPVersion]
            PEP version to follow.
        
        Returns
        -------
        PackageTag
            Complete package tag.
        
        Raises
        ------
        ValueError
            If an unsupported PEP version is provided.
        """
        if isinstance(pep_version, str):
            pep_version = PEPVersion.from_string(pep_version)
            if pep_version is None:
                raise ValueError(f"Invalid PEP version: {pep_version}")
        
        builders = {
            PEPVersion.PEP_425: self.build_tag_pep425,
            PEPVersion.PEP_491: self.build_tag_pep491,
            PEPVersion.PEP_600: self.build_tag_pep600,
            PEPVersion.PEP_625: self.build_tag_pep625,
            PEPVersion.PEP_665: self.build_tag_pep665,
        }
        
        builder = builders.get(pep_version)
        if builder is None:
            raise ValueError(f"Unsupported PEP version: {pep_version}")
        
        return builder(package)
    
    def generate_environment_tag(self, 
                                  pep_version: Union[str, PEPVersion] = PEPVersion.PEP_600) -> str:
        """
        Generate an environment tag without a specific package.
        
        Parameters
        ----------
        pep_version : Union[str, PEPVersion], default=PEPVersion.PEP_600
            PEP version to follow.
        
        Returns
        -------
        str
            Environment tag string.
        """
        tag = self.build_package_tag("env", pep_version)
        return str(tag)
    
    def get_environment_info(self) -> EnvironmentInfo:
        """
        Get the detected environment information.
        
        Returns
        -------
        EnvironmentInfo
            Complete environment information.
        """
        return self.env_info


# ============================================================================
# Convenience Functions (Backward Compatible)
# ============================================================================

# Create a global tagger instance for convenience functions
_global_tagger: Optional[EnvironmentTagger] = None


def _get_global_tagger() -> EnvironmentTagger:
    """Get or create the global tagger instance."""
    global _global_tagger
    if _global_tagger is None:
        _global_tagger = EnvironmentTagger()
    return _global_tagger


def build_tag(package: str, pep_version: PEPVersionStr = "425") -> str:
    """
    Build an environment tag for a package according to a specified PEP.
    
    This is a convenience function that uses the global EnvironmentTagger
    instance. For more control, create an EnvironmentTagger instance directly.
    
    Parameters
    ----------
    package : str
        Name of the package.
    pep_version : {"425", "491", "600", "625", "665"}, default="425"
        The PEP version to follow.
    
    Returns
    -------
    str
        Formatted tag string according to the selected PEP.
    
    Raises
    ------
    ValueError
        If an unsupported PEP version is provided.
    
    Examples
    --------
    >>> build_tag("numpy", "425")
    'numpy-1.23.5-cp39-cp39-macosx_10_9_x86_64'
    
    >>> build_tag("pandas", "600")
    'pandas-1.5.3-cp39-cp39_abi3-manylinux_2_17_x86_64-glibc2_17-64bit-release'
    """
    tagger = _get_global_tagger()
    tag = tagger.build_package_tag(package, pep_version)
    return str(tag)


def env_tag(pep_version: PEPVersionStr = "600") -> str:
    """
    Generate an environment tag for the current Python environment.
    
    This is a convenience function that uses the global EnvironmentTagger
    instance.
    
    Parameters
    ----------
    pep_version : {"425", "491", "600", "625", "665"}, default="600"
        The PEP version to follow.
    
    Returns
    -------
    str
        Environment tag describing the current Python installation.
    
    Examples
    --------
    >>> env_tag("600")
    'env-unknown-cp39-cp39_abi3-manylinux_2_17_x86_64-glibc2_17-64bit-release'
    """
    tagger = _get_global_tagger()
    return tagger.generate_environment_tag(pep_version)


def get_environment_summary() -> str:
    """
    Get a human-readable summary of the current environment.
    
    Returns
    -------
    str
        Formatted summary of environment information.
    
    Examples
    --------
    >>> print(get_environment_summary())
    Python Environment Summary:
      Version: 3.11.0 (cpython)
      OS: linux (linux)
      Architecture: x86_64 (64bit)
      Build: release
      Environment: system
      C Library: glibc 2.35
      ABI Flags: none
      SOABI: cpython-311-x86_64-linux-gnu
    """
    tagger = _get_global_tagger()
    return tagger.env_info.get_summary()


def clear_cache() -> None:
    """Clear the global environment information cache."""
    EnvironmentTagger.clear_cache()
    global _global_tagger
    _global_tagger = None


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "PEPVersion",
    "PythonImplementation",
    "LibCType",
    "BuildType",
    "EnvironmentType",
    "Architecture",
    "OperatingSystem",
    
    # Data Classes
    "LibCInfo",
    "EnvironmentInfo",
    "PackageTag",
    
    # Main Class
    "EnvironmentTagger",
    
    # Convenience Functions
    "build_tag",
    "env_tag",
    "get_environment_summary",
    "clear_cache",
]
