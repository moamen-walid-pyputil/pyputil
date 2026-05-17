#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Python Package Filename Tag Parser
==================================

Comprehensive parser for Python package filenames that extracts and processes
distribution tags according to PEP 425, PEP 440, PEP 491, PEP 600, PEP 625,
PEP 656, and related standards.

This module provides functionality to parse Python package filenames and extract
metadata including distribution name, version, Python version requirements,
ABI tags, platform compatibility, build tags, and architecture details.

Supported PEPs
--------------
- **PEP 425**: Compatibility Tags for Built Distributions
- **PEP 440**: Version Identification and Dependency Specification
- **PEP 491**: The Wheel Binary Package Format 1.9
- **PEP 600**: Future 'manylinux' Platform Tags
- **PEP 625**: File Name Convention for Source Distributions
- **PEP 656**: Platform Tag for Linux Distributions Using musl
- **PEP 665**: Simple Repository API (metadata format)

Examples
--------
>>> parser = PackageTagParser()
>>> result = parser.parse("numpy-1.24.3-cp311-cp311-win_amd64.whl")
>>> print(result.distribution_name, result.version)
numpy 1.24.3
>>> print(result.python_tag, result.abi_tag, result.platform_tag)
cp311 cp311 win_amd64

>>> # Parsing a manylinux wheel
>>> result = parser.parse("cryptography-39.0.0-cp36-abi3-manylinux_2_28_x86_64.whl")
>>> print(result.platform_tag, result.architecture)
manylinux_2_28_x86_64 x86_64
>>> print(result.compatibility.is_universal)
False

>>> # Filtering packages
>>> packages = parser.parse_multiple([...])
>>> filter_obj = PackageFilter(packages)
>>> linux_pkgs = filter_obj.by_platform_type(PlatformType.LINUX)

References
----------
- PEP 425: https://www.python.org/dev/peps/pep-0425/
- PEP 440: https://www.python.org/dev/peps/pep-0440/
- PEP 491: https://www.python.org/dev/peps/pep-0491/
- PEP 600: https://www.python.org/dev/peps/pep-0600/
- PEP 625: https://www.python.org/dev/peps/pep-0625/
- PEP 656: https://www.python.org/dev/peps/pep-0656/
"""

import re
import logging
from typing import (
    Dict, List, Optional, Tuple, Union, Any, Set, 
    Iterator, ClassVar, Pattern, Callable, TypeVar
)
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from pathlib import Path
from functools import lru_cache
import warnings

# Configure module logger
logger = logging.getLogger(__name__)


from ._utils._tags import (
    PEPVersion,
    PythonImplementation,
    LibCType,
    BuildType,
    EnvironmentType,
    Architecture,
    OperatingSystem,
    LibCInfo,
    EnvironmentInfo,
    PackageTag,
    EnvironmentTagger,
    build_tag,
    env_tag,
    get_environment_summary,
    clear_cache as _clear_cache
)
from ._utils._tags_identify import (
    PEP,
    TagType,
    DistributionType,
    PythonImplementation,
    ABIType,
    PlatformType,
    PEPClassification,
    ParsedTag,
    ParsedWheelFilename,
    ParsedSdistFilename,
    RegexPatterns,
    parse_python_tag,
    parse_abi_tag,
    parse_platform_tag,
    is_pep425_tag,
    is_pep440_version,
    is_pep491_filename,
    is_pep600_platform,
    is_pep625_filename,
    is_pep656_platform,
    parse_wheel_filename,
    parse_sdist_filename,
    parse_filename,
    identify_pep_from_filename,
    classify_filename,
    extract_distribution_name,
    extract_version,
    get_distribution_type
)


# ============================================================================
# Enums for Type-Safe Tag Classification
# ============================================================================

class DistributionType(Enum):
    """
    Enumeration of Python package distribution types.
    
    Attributes
    ----------
    WHEEL : str
        Wheel distribution (.whl) - PEP 491.
    SDIST : str
        Source distribution (.tar.gz, .zip) - PEP 625.
    EGG : str
        Legacy egg format (.egg).
    UNKNOWN : str
        Unknown distribution type.
    """
    WHEEL = "wheel"
    SDIST = "sdist"
    EGG = "egg"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value
    
    @classmethod
    def from_filename(cls, filename: str) -> 'DistributionType':
        """
        Detect distribution type from filename.
        
        Parameters
        ----------
        filename : str
            The filename to analyze.
        
        Returns
        -------
        DistributionType
            Detected distribution type.
        """
        filename_lower = filename.lower()
        if filename_lower.endswith('.whl'):
            return cls.WHEEL
        elif filename_lower.endswith(('.tar.gz', '.zip', '.tgz', '.tar.bz2', '.tar.xz')):
            return cls.SDIST
        elif filename_lower.endswith('.egg'):
            return cls.EGG
        return cls.UNKNOWN


class PythonImplementation(Enum):
    """
    Python implementations recognized in tags.
    
    Attributes
    ----------
    CPYTHON : str
        CPython implementation ('cp').
    PYPY : str
        PyPy implementation ('pp').
    JYTHON : str
        Jython implementation ('jp').
    IRONPYTHON : str
        IronPython implementation ('ip').
    GENERIC : str
        Generic Python ('py').
    UNKNOWN : str
        Unknown implementation.
    """
    CPYTHON = "cp"
    PYPY = "pp"
    JYTHON = "jp"
    IRONPYTHON = "ip"
    GENERIC = "py"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_tag(cls, tag: str) -> 'PythonImplementation':
        """
        Extract implementation from a Python tag.
        
        Parameters
        ----------
        tag : str
            Python tag string (e.g., 'cp311', 'py3').
        
        Returns
        -------
        PythonImplementation
            Detected implementation.
        """
        for impl in cls:
            if impl != cls.UNKNOWN and tag.startswith(impl.value):
                return impl
        return cls.UNKNOWN
    
    @property
    def display_name(self) -> str:
        """Get human-readable implementation name."""
        names = {
            PythonImplementation.CPYTHON: "CPython",
            PythonImplementation.PYPY: "PyPy",
            PythonImplementation.JYTHON: "Jython",
            PythonImplementation.IRONPYTHON: "IronPython",
            PythonImplementation.GENERIC: "Python",
        }
        return names.get(self, self.value)
    
    def __str__(self) -> str:
        return self.value


class ABIType(Enum):
    """
    ABI types recognized in tags.
    
    Attributes
    ----------
    SPECIFIC : str
        Implementation-specific ABI (e.g., 'cp311').
    ABI3 : str
        Stable ABI version 3 ('abi3').
    NONE : str
        No ABI requirements ('none').
    UNKNOWN : str
        Unknown ABI type.
    """
    SPECIFIC = "specific"
    ABI3 = "abi3"
    NONE = "none"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_tag(cls, tag: str) -> 'ABIType':
        """
        Determine ABI type from a tag.
        
        Parameters
        ----------
        tag : str
            ABI tag string.
        
        Returns
        -------
        ABIType
            Detected ABI type.
        """
        if tag == "none":
            return cls.NONE
        elif tag.startswith("abi3"):
            return cls.ABI3
        elif tag.startswith(("cp", "pp", "jp", "ip")):
            return cls.SPECIFIC
        return cls.UNKNOWN
    
    def __str__(self) -> str:
        return self.value


class PlatformType(Enum):
    """
    Platform tag types.
    
    Attributes
    ----------
    WINDOWS : str
        Windows platform ('win').
    LINUX : str
        Generic Linux platform ('linux').
    MACOS : str
        macOS platform ('macosx').
    MANYLINUX : str
        manylinux platform (PEP 600).
    MUSLLINUX : str
        musllinux platform (PEP 656).
    ANY : str
        Platform-independent ('any').
    UNKNOWN : str
        Unknown platform type.
    """
    WINDOWS = "win"
    LINUX = "linux"
    MACOS = "macosx"
    MANYLINUX = "manylinux"
    MUSLLINUX = "musllinux"
    ANY = "any"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_tag(cls, tag: str) -> 'PlatformType':
        """
        Determine platform type from a tag.
        
        Parameters
        ----------
        tag : str
            Platform tag string.
        
        Returns
        -------
        PlatformType
            Detected platform type.
        """
        if tag == "any":
            return cls.ANY
        elif tag.startswith("win"):
            return cls.WINDOWS
        elif tag.startswith("linux") and not tag.startswith(("manylinux", "musllinux")):
            return cls.LINUX
        elif tag.startswith("macosx"):
            return cls.MACOS
        elif tag.startswith("manylinux"):
            return cls.MANYLINUX
        elif tag.startswith("musllinux"):
            return cls.MUSLLINUX
        return cls.UNKNOWN
    
    @property
    def display_name(self) -> str:
        """Get human-readable platform name."""
        names = {
            PlatformType.WINDOWS: "Windows",
            PlatformType.LINUX: "Linux",
            PlatformType.MACOS: "macOS",
            PlatformType.MANYLINUX: "Manylinux",
            PlatformType.MUSLLINUX: "musllinux",
            PlatformType.ANY: "Platform-independent",
        }
        return names.get(self, self.value)
    
    def __str__(self) -> str:
        return self.value


class Architecture(Enum):
    """
    CPU architectures recognized in platform tags.
    
    Attributes
    ----------
    X86_64 : str
        64-bit x86 (AMD64, Intel 64).
    X86 : str
        32-bit x86 (i386, i686).
    ARM64 : str
        64-bit ARM (AArch64).
    ARMV7 : str
        32-bit ARMv7.
    PPC64LE : str
        64-bit PowerPC little-endian.
    PPC64 : str
        64-bit PowerPC big-endian.
    S390X : str
        IBM System z (64-bit).
    IA64 : str
        Intel Itanium.
    UNIVERSAL2 : str
        macOS universal binary (x86_64 + arm64).
    UNKNOWN : str
        Unknown architecture.
    """
    X86_64 = "x86_64"
    X86 = "x86"
    ARM64 = "arm64"
    ARMV7 = "armv7"
    PPC64LE = "ppc64le"
    PPC64 = "ppc64"
    S390X = "s390x"
    IA64 = "ia64"
    UNIVERSAL2 = "universal2"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_string(cls, arch_str: str) -> 'Architecture':
        """
        Normalize architecture string to enum value.
        
        Parameters
        ----------
        arch_str : str
            Architecture string to normalize.
        
        Returns
        -------
        Architecture
            Normalized architecture enum.
        """
        arch_lower = arch_str.lower()
        
        # x86_64 variations
        if arch_lower in ('x86_64', 'amd64', 'intel64', 'em64t'):
            return cls.X86_64
        
        # x86 variations
        if arch_lower in ('i386', 'i486', 'i586', 'i686', 'x86', 'win32'):
            return cls.X86
        
        # ARM64 variations
        if arch_lower in ('aarch64', 'arm64', 'armv8'):
            return cls.ARM64
        
        # ARMv7 variations
        if arch_lower in ('armv7', 'armv7l'):
            return cls.ARMV7
        
        # PowerPC
        if arch_lower == 'ppc64le':
            return cls.PPC64LE
        if arch_lower == 'ppc64':
            return cls.PPC64
        
        # IBM System z
        if arch_lower == 's390x':
            return cls.S390X
        
        # Itanium
        if arch_lower in ('ia64', 'itanium'):
            return cls.IA64
        
        # Universal
        if arch_lower == 'universal2':
            return cls.UNIVERSAL2
        
        return cls.UNKNOWN
    
    def __str__(self) -> str:
        return self.value


class TagType(Enum):
    """
    Enumeration of possible Python package tag types.
    
    Attributes
    ----------
    VERSION : str
        Package version tag.
    PYTHON : str
        Python interpreter version tag.
    ABI : str
        Application Binary Interface tag.
    PLATFORM : str
        Target platform tag.
    BUILD : str
        Build number or tag.
    ARCHITECTURE : str
        System architecture.
    IMPLEMENTATION : str
        Python implementation.
    DISTRIBUTION : str
        Distribution format.
    """
    VERSION = auto()
    PYTHON = auto()
    ABI = auto()
    PLATFORM = auto()
    BUILD = auto()
    ARCHITECTURE = auto()
    IMPLEMENTATION = auto()
    DISTRIBUTION = auto()
    
    def __str__(self) -> str:
        return self.name.lower()


# ============================================================================
# Regular Expression Patterns (Compiled for Performance)
# ============================================================================

@dataclass(frozen=True)
class FilenamePatterns:
    """
    Container for all compiled regular expression patterns.
    
    Attributes
    ----------
    WHEEL : Pattern
        Complete wheel filename pattern (PEP 491).
    SDIST : Pattern
        Source distribution pattern (PEP 625).
    EGG : Pattern
        Legacy egg format pattern.
    PYTHON_TAG : Pattern
        Python tag extraction pattern.
    ABI_TAG : Pattern
        ABI tag extraction pattern.
    PLATFORM_TAG : Pattern
        Platform tag extraction pattern.
    BUILD_TAG : Pattern
        Build tag extraction pattern.
    VERSION : Pattern
        Version string extraction pattern.
    ARCH_EXTRACT : Pattern
        Architecture extraction from platform tag.
    MANYLINUX_VERSION : Pattern
        manylinux version extraction.
    MUSLLINUX_VERSION : Pattern
        musllinux version extraction.
    """
    
    # Complete wheel pattern (PEP 491)
    # Format: {distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl
    WHEEL: ClassVar[Pattern] = re.compile(
        r'^(?P<distribution>[a-zA-Z0-9](?:[a-zA-Z0-9_.-]*[a-zA-Z0-9])?)'
        r'-(?P<version>[a-zA-Z0-9_.!+*-]+?)'
        r'(?:-(?P<build>\d+[a-zA-Z0-9_.-]*))?'
        r'-(?P<python>[a-zA-Z0-9_.-]+?)'
        r'-(?P<abi>[a-zA-Z0-9_.-]+?)'
        r'-(?P<platform>[a-zA-Z0-9_.-]+?)'
        r'\.whl$',
        re.IGNORECASE
    )
    
    # Source distribution pattern (PEP 625)
    SDIST: ClassVar[Pattern] = re.compile(
        r'^(?P<distribution>[a-zA-Z0-9](?:[a-zA-Z0-9_.-]*[a-zA-Z0-9])?)'
        r'-(?P<version>[a-zA-Z0-9_.!+*-]+?)'
        r'\.(?P<extension>tar\.gz|zip|tgz|tar\.bz2|tar\.xz|tar\.Z|tar)$',
        re.IGNORECASE
    )
    
    # Egg pattern (legacy)
    EGG: ClassVar[Pattern] = re.compile(
        r'^(?P<distribution>[a-zA-Z0-9_.-]+?)'
        r'-(?P<version>[a-zA-Z0-9_.-]+?)'
        r'(?:-py(?P<python>\d+\.\d+))?'
        r'(?:-(?P<platform>[a-zA-Z0-9_.-]+))?'
        r'\.egg$',
        re.IGNORECASE
    )
    
    # Individual tag extractors
    PYTHON_TAG: ClassVar[Pattern] = re.compile(
        r'(?<=-)((?:cp|py|pp|ip|jp|mp|sl)\d+(?:\.\d+)?(?:[_-]\w+)?)',
        re.IGNORECASE
    )
    
    ABI_TAG: ClassVar[Pattern] = re.compile(
        r'(?<=-)((?:cp|pp|none|abi3)\d*(?:[_-]\w+)?)(?=-)',
        re.IGNORECASE
    )
    
    PLATFORM_TAG: ClassVar[Pattern] = re.compile(
        r'(?<=-)((?:win|linux|macosx|manylinux|musllinux|any)[a-zA-Z0-9_.-]*)',
        re.IGNORECASE
    )
    
    BUILD_TAG: ClassVar[Pattern] = re.compile(
        r'(?<=-)(\d+(?:\.\d+)*(?:[a-zA-Z0-9_.-]+))?(?=-[cp]|\.)'
    )
    
    VERSION: ClassVar[Pattern] = re.compile(
        r'-(\d+(?:\.\d+)*(?:[a-zA-Z0-9_.-]*?))'
    )
    
    # Architecture extractor
    ARCH_EXTRACT: ClassVar[Pattern] = re.compile(
        r'(x86_64|amd64|i[3-6]86|aarch64|arm64|armv7l?|ppc64le?|s390x|ia64|universal2|win32)',
        re.IGNORECASE
    )
    
    # Version extractors for special platform tags
    MANYLINUX_VERSION: ClassVar[Pattern] = re.compile(
        r'manylinux(?:_(\d+)_(\d+)|(\d{4}))',
        re.IGNORECASE
    )
    
    MUSLLINUX_VERSION: ClassVar[Pattern] = re.compile(
        r'musllinux_(\d+)_(\d+)',
        re.IGNORECASE
    )
    
    # Implementation extractor
    IMPLEMENTATION: ClassVar[Pattern] = re.compile(
        r'^(cp|pp|ip|jp|py)',
        re.IGNORECASE
    )


# Singleton instance for pattern access
PATTERNS = FilenamePatterns()


# ============================================================================
# Data Classes for Parsed Information
# ============================================================================

@dataclass(frozen=True)
class CompatibilityInfo:
    """
    Compatibility information extracted from package tags.
    
    Attributes
    ----------
    python_versions : Tuple[str, ...]
        Formatted Python versions (e.g., ('3.11', '3.10')).
    platforms : Tuple[str, ...]
        Human-readable platform descriptions.
    implementations : Tuple[str, ...]
        Python implementation names.
    is_universal : bool
        Whether package is platform-independent.
    requires_specific_abi : bool
        Whether a specific ABI is required.
    abi_type : ABIType
        Type of ABI required.
    platform_type : PlatformType
        Type of platform.
    architecture : Optional[Architecture]
        Architecture if applicable.
    """
    python_versions: Tuple[str, ...] = field(default_factory=tuple)
    platforms: Tuple[str, ...] = field(default_factory=tuple)
    implementations: Tuple[str, ...] = field(default_factory=tuple)
    is_universal: bool = False
    requires_specific_abi: bool = False
    abi_type: ABIType = ABIType.UNKNOWN
    platform_type: PlatformType = PlatformType.UNKNOWN
    architecture: Optional[Architecture] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "python_versions": list(self.python_versions),
            "platforms": list(self.platforms),
            "implementations": list(self.implementations),
            "is_universal": self.is_universal,
            "requires_specific_abi": self.requires_specific_abi,
            "abi_type": str(self.abi_type),
            "platform_type": str(self.platform_type),
            "architecture": str(self.architecture) if self.architecture else None,
        }
    
    def supports_python_version(self, version: str) -> bool:
        """
        Check if a specific Python version is supported.
        
        Parameters
        ----------
        version : str
            Python version to check (e.g., '3.11').
        
        Returns
        -------
        bool
            True if supported.
        """
        return version in self.python_versions
    
    def supports_platform(self, platform: str) -> bool:
        """
        Check if a platform type is supported.
        
        Parameters
        ----------
        platform : str
            Platform to check (case-insensitive substring match).
        
        Returns
        -------
        bool
            True if supported.
        """
        platform_lower = platform.lower()
        return any(platform_lower in p.lower() for p in self.platforms)


@dataclass(frozen=True)
class ParsedPackageInfo:
    """
    Immutable data class containing complete parsed package information.
    
    This class stores all metadata extracted from a Python package filename,
    organized with both structured fields and raw tags. It provides methods
    for compatibility analysis and filename reconstruction.
    
    Attributes
    ----------
    distribution_name : str
        Normalized distribution name.
    version : str
        Package version string.
    python_tag : str
        Raw Python version tag.
    abi_tag : str
        Raw ABI tag.
    platform_tag : str
        Raw platform tag.
    build_tag : str
        Build tag (optional).
    extension : str
        File extension including dot.
    original_filename : str
        Original complete filename.
    distribution_type : DistributionType
        Type of distribution.
    implementation : PythonImplementation
        Detected Python implementation.
    architecture : Architecture
        Detected architecture.
    compatibility : CompatibilityInfo
        Comprehensive compatibility information.
    raw_tags : Dict[str, str]
        Dictionary of all raw extracted tags.
    manylinux_version : Optional[Tuple[int, int]]
        manylinux version tuple if applicable.
    musllinux_version : Optional[Tuple[int, int]]
        musllinux version tuple if applicable.
    is_valid : bool
        Whether the filename conforms to expected format.
    
    Examples
    --------
    >>> info = ParsedPackageInfo(
    ...     distribution_name="numpy",
    ...     version="1.24.3",
    ...     python_tag="cp311",
    ...     abi_tag="cp311",
    ...     platform_tag="win_amd64",
    ...     extension=".whl",
    ...     distribution_type=DistributionType.WHEEL
    ... )
    >>> info.compatibility.is_universal
    False
    >>> info.architecture
    <Architecture.X86_64: 'x86_64'>
    """
    distribution_name: str
    version: str = ""
    python_tag: str = ""
    abi_tag: str = ""
    platform_tag: str = ""
    build_tag: str = ""
    extension: str = ""
    original_filename: str = ""
    distribution_type: DistributionType = DistributionType.UNKNOWN
    implementation: PythonImplementation = PythonImplementation.UNKNOWN
    architecture: Architecture = Architecture.UNKNOWN
    compatibility: CompatibilityInfo = field(default_factory=CompatibilityInfo)
    raw_tags: Dict[str, str] = field(default_factory=dict)
    manylinux_version: Optional[Tuple[int, int]] = None
    musllinux_version: Optional[Tuple[int, int]] = None
    is_valid: bool = False
    
    @property
    def normalized_name(self) -> str:
        """
        Get PEP 503 normalized distribution name.
        
        Returns
        -------
        str
            Normalized name with hyphens.
        """
        return re.sub(r'[-_.]+', '-', self.distribution_name).lower()
    
    @property
    def python_versions(self) -> Tuple[str, ...]:
        """Get list of compatible Python versions."""
        return self.compatibility.python_versions
    
    @property
    def is_universal(self) -> bool:
        """Check if package is platform-independent."""
        return self.compatibility.is_universal
    
    def reconstruct_filename(self, include_build: bool = True) -> str:
        """
        Reconstruct the filename from parsed components.
        
        Parameters
        ----------
        include_build : bool, default=True
            Whether to include build tag if present.
        
        Returns
        -------
        str
            Reconstructed filename.
        """
        parts = [self.distribution_name, self.version]
        
        if include_build and self.build_tag:
            parts.append(self.build_tag)
        
        if self.distribution_type == DistributionType.WHEEL:
            if self.python_tag:
                parts.append(self.python_tag)
            if self.abi_tag:
                parts.append(self.abi_tag)
            if self.platform_tag:
                parts.append(self.platform_tag)
        
        filename = "-".join(parts)
        if self.extension:
            filename += self.extension
        
        return filename
    
    def to_dict(self, include_compatibility: bool = True) -> Dict[str, Any]:
        """
        Convert to dictionary representation.
        
        Parameters
        ----------
        include_compatibility : bool, default=True
            Whether to include full compatibility info.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        result = {
            "distribution_name": self.distribution_name,
            "normalized_name": self.normalized_name,
            "version": self.version,
            "python_tag": self.python_tag,
            "abi_tag": self.abi_tag,
            "platform_tag": self.platform_tag,
            "build_tag": self.build_tag,
            "extension": self.extension,
            "original_filename": self.original_filename,
            "distribution_type": str(self.distribution_type),
            "implementation": str(self.implementation),
            "architecture": str(self.architecture),
            "is_valid": self.is_valid,
            "raw_tags": self.raw_tags.copy(),
        }
        
        if self.manylinux_version:
            result["manylinux_version"] = list(self.manylinux_version)
        if self.musllinux_version:
            result["musllinux_version"] = list(self.musllinux_version)
        
        if include_compatibility:
            result["compatibility"] = self.compatibility.to_dict()
        
        return result
    
    def get_summary(self) -> str:
        """
        Get a human-readable summary of the package.
        
        Returns
        -------
        str
            Formatted summary string.
        """
        lines = [
            f"Package: {self.distribution_name} {self.version}",
            f"  Type: {self.distribution_type.value}",
            f"  Valid: {self.is_valid}",
        ]
        
        if self.python_tag:
            lines.append(f"  Python Tag: {self.python_tag}")
            if self.compatibility.python_versions:
                lines.append(f"    Versions: {', '.join(self.compatibility.python_versions)}")
        
        if self.abi_tag:
            lines.append(f"  ABI Tag: {self.abi_tag} ({self.compatibility.abi_type.value})")
        
        if self.platform_tag:
            lines.append(f"  Platform Tag: {self.platform_tag}")
            if self.architecture != Architecture.UNKNOWN:
                lines.append(f"    Architecture: {self.architecture.value}")
        
        if self.compatibility.is_universal:
            lines.append("  ✓ Universal package")
        
        if self.compatibility.requires_specific_abi:
            lines.append("  ⚠ Requires specific ABI")
        
        return "\n".join(lines)
    
    def __repr__(self) -> str:
        return (f"ParsedPackageInfo(name='{self.distribution_name}', "
                f"version='{self.version}', type={self.distribution_type.value})")


# ============================================================================
# Main Parser Class
# ============================================================================

class PackageTagParser:
    """
    Main parser class for Python package filenames.
    
    This class implements comprehensive parsing logic for Python package
    filenames, supporting wheels (PEP 491), source distributions (PEP 625),
    and legacy egg formats. It extracts all metadata and provides detailed
    compatibility analysis.
    
    Parameters
    ----------
    strict_mode : bool, default=False
        If True, raises exceptions for malformed filenames.
        If False, attempts best-effort parsing and logs warnings.
    custom_patterns : Optional[Dict[str, str]], default=None
        Additional regex patterns for custom tag formats.
    normalize_names : bool, default=True
        Whether to normalize distribution names per PEP 503.
    
    Attributes
    ----------
    strict_mode : bool
        Current strict mode setting.
    normalize_names : bool
        Whether names are normalized.
    patterns : FilenamePatterns
        Compiled regex patterns.
    
    Examples
    --------
    >>> parser = PackageTagParser(strict_mode=True)
    >>> info = parser.parse("requests-2.28.1-py3-none-any.whl")
    >>> info.distribution_name
    'requests'
    >>> info.compatibility.is_universal
    True
    
    >>> # Parse a manylinux wheel
    >>> info = parser.parse("cryptography-39.0.0-cp36-abi3-manylinux_2_28_x86_64.whl")
    >>> info.platform_tag
    'manylinux_2_28_x86_64'
    >>> info.manylinux_version
    (2, 28)
    """
    
    def __init__(
        self,
        strict_mode: bool = False,
        custom_patterns: Optional[Dict[str, str]] = None,
        normalize_names: bool = True
    ):
        """
        Initialize the PackageTagParser.
        
        Parameters
        ----------
        strict_mode : bool, default=False
            Enable strict parsing mode.
        custom_patterns : Optional[Dict[str, str]], default=None
            Additional custom regex patterns.
        normalize_names : bool, default=True
            Whether to normalize distribution names.
        """
        self.strict_mode = strict_mode
        self.normalize_names = normalize_names
        self.patterns = PATTERNS
        
        # Store custom patterns if provided
        self._custom_patterns: Dict[str, Pattern] = {}
        if custom_patterns:
            for name, pattern in custom_patterns.items():
                self._custom_patterns[name] = re.compile(pattern)
    
    @lru_cache(maxsize=512)
    def parse(self, filename: Union[str, Path]) -> ParsedPackageInfo:
        """
        Parse a single Python package filename.
        
        Parameters
        ----------
        filename : Union[str, Path]
            The filename to parse.
        
        Returns
        -------
        ParsedPackageInfo
            Complete parsed package information.
        
        Raises
        ------
        ValueError
            If filename is malformed and strict_mode is True.
        TypeError
            If filename is not a string or Path.
        
        Examples
        --------
        >>> parser = PackageTagParser()
        >>> info = parser.parse("pandas-2.0.0-cp39-cp39-macosx_11_0_arm64.whl")
        >>> info.distribution_name
        'pandas'
        """
        if not isinstance(filename, (str, Path)):
            raise TypeError(f"Expected string or Path, got {type(filename).__name__}")
        
        filename_str = str(filename)
        basename = Path(filename_str).name
        extension = self._get_extension(basename)
        dist_type = DistributionType.from_filename(basename)
        
        # Initialize base info
        raw_tags: Dict[str, str] = {
            'original_filename': basename,
            'extension': extension,
            'distribution_type': dist_type.value,
        }
        
        try:
            # Parse based on distribution type
            if dist_type == DistributionType.WHEEL:
                parsed = self._parse_wheel(basename)
            elif dist_type == DistributionType.SDIST:
                parsed = self._parse_sdist(basename)
            elif dist_type == DistributionType.EGG:
                parsed = self._parse_egg(basename)
            else:
                parsed = self._parse_generic(basename)
            
            # Merge parsed data
            distribution_name = parsed.get('distribution_name', '')
            if self.normalize_names and distribution_name:
                distribution_name = self._normalize_name(distribution_name)
            
            # Extract additional information
            python_tag = parsed.get('python_tag', '')
            abi_tag = parsed.get('abi_tag', '')
            platform_tag = parsed.get('platform_tag', '')
            
            # Detect implementation
            implementation = self._detect_implementation(python_tag, abi_tag)
            
            # Detect architecture
            architecture = self._detect_architecture(platform_tag)
            
            # Extract version info for special platforms
            manylinux_version = self._extract_manylinux_version(platform_tag)
            musllinux_version = self._extract_musllinux_version(platform_tag)
            
            # Build compatibility info
            compatibility = self._build_compatibility(
                python_tag=python_tag,
                abi_tag=abi_tag,
                platform_tag=platform_tag,
                dist_type=dist_type,
                implementation=implementation,
                architecture=architecture
            )
            
            # Update raw tags
            raw_tags.update({
                'distribution_name': distribution_name,
                'version': parsed.get('version', ''),
                'python_tag': python_tag,
                'abi_tag': abi_tag,
                'platform_tag': platform_tag,
                'build_tag': parsed.get('build_tag', ''),
            })
            
            return ParsedPackageInfo(
                distribution_name=distribution_name,
                version=parsed.get('version', ''),
                python_tag=python_tag,
                abi_tag=abi_tag,
                platform_tag=platform_tag,
                build_tag=parsed.get('build_tag', ''),
                extension=extension,
                original_filename=basename,
                distribution_type=dist_type,
                implementation=implementation,
                architecture=architecture,
                compatibility=compatibility,
                raw_tags=raw_tags,
                manylinux_version=manylinux_version,
                musllinux_version=musllinux_version,
                is_valid=True
            )
            
        except Exception as e:
            if self.strict_mode:
                raise ValueError(f"Failed to parse '{basename}': {e}") from e
            else:
                logger.warning(f"Partial parsing for '{basename}': {e}")
                return ParsedPackageInfo(
                    distribution_name="",
                    original_filename=basename,
                    extension=extension,
                    distribution_type=dist_type,
                    raw_tags=raw_tags,
                    is_valid=False
                )
    
    def parse_multiple(self, filenames: List[Union[str, Path]]) -> List[ParsedPackageInfo]:
        """
        Parse multiple Python package filenames.
        
        Parameters
        ----------
        filenames : List[Union[str, Path]]
            List of filenames to parse.
        
        Returns
        -------
        List[ParsedPackageInfo]
            List of parsed package information objects.
        
        Examples
        --------
        >>> files = ["numpy-1.24.3.whl", "scipy-1.10.0.tar.gz"]
        >>> results = parser.parse_multiple(files)
        >>> len(results)
        2
        """
        return [self.parse(f) for f in filenames]
    
    def _parse_wheel(self, filename: str) -> Dict[str, str]:
        """
        Parse wheel format filename.
        
        Parameters
        ----------
        filename : str
            The wheel filename.
        
        Returns
        -------
        Dict[str, str]
            Parsed components.
        
        Raises
        ------
        ValueError
            If format is invalid.
        """
        match = self.patterns.WHEEL.match(filename)
        if not match:
            raise ValueError(f"Invalid wheel filename format: {filename}")
        
        groups = match.groupdict()
        return {
            'distribution_name': groups.get('distribution', ''),
            'version': groups.get('version', ''),
            'build_tag': groups.get('build', ''),
            'python_tag': groups.get('python', ''),
            'abi_tag': groups.get('abi', ''),
            'platform_tag': groups.get('platform', ''),
        }
    
    def _parse_sdist(self, filename: str) -> Dict[str, str]:
        """
        Parse source distribution filename.
        
        Parameters
        ----------
        filename : str
            The sdist filename.
        
        Returns
        -------
        Dict[str, str]
            Parsed components.
        
        Raises
        ------
        ValueError
            If format is invalid.
        """
        match = self.patterns.SDIST.match(filename)
        if not match:
            raise ValueError(f"Invalid sdist filename format: {filename}")
        
        groups = match.groupdict()
        return {
            'distribution_name': groups.get('distribution', ''),
            'version': groups.get('version', ''),
            'python_tag': '',
            'abi_tag': '',
            'platform_tag': 'any',
            'build_tag': '',
        }
    
    def _parse_egg(self, filename: str) -> Dict[str, str]:
        """
        Parse egg format filename.
        
        Parameters
        ----------
        filename : str
            The egg filename.
        
        Returns
        -------
        Dict[str, str]
            Parsed components.
        
        Raises
        ------
        ValueError
            If format is invalid.
        """
        match = self.patterns.EGG.match(filename)
        if not match:
            raise ValueError(f"Invalid egg filename format: {filename}")
        
        groups = match.groupdict()
        python_ver = groups.get('python', '')
        return {
            'distribution_name': groups.get('distribution', ''),
            'version': groups.get('version', ''),
            'python_tag': f"py{python_ver}" if python_ver else '',
            'abi_tag': '',
            'platform_tag': groups.get('platform', ''),
            'build_tag': '',
        }
    
    def _parse_generic(self, filename: str) -> Dict[str, str]:
        """
        Parse generic package filename (fallback).
        
        Parameters
        ----------
        filename : str
            The filename to parse.
        
        Returns
        -------
        Dict[str, str]
            Best-effort parsed components.
        """
        # Remove extension
        name_part = filename
        for ext in ['.whl', '.tar.gz', '.zip', '.tgz', '.tar.bz2', '.tar.xz', '.egg']:
            if name_part.endswith(ext):
                name_part = name_part[:-len(ext)]
                break
        
        parts = name_part.split('-')
        result: Dict[str, str] = {
            'distribution_name': parts[0] if parts else '',
            'version': parts[1] if len(parts) > 1 else '',
            'python_tag': '',
            'abi_tag': '',
            'platform_tag': '',
            'build_tag': '',
        }
        
        # Try to extract tags using patterns
        for i, part in enumerate(parts[2:], 2):
            if self.patterns.PYTHON_TAG.match(part):
                result['python_tag'] = part
            elif self.patterns.ABI_TAG.match(part):
                result['abi_tag'] = part
            elif self.patterns.PLATFORM_TAG.match(part):
                result['platform_tag'] = part
        
        return result
    
    def _get_extension(self, filename: str) -> str:
        """
        Extract file extension including multi-part extensions.
        
        Parameters
        ----------
        filename : str
            The filename.
        
        Returns
        -------
        str
            File extension including dot.
        """
        multi_extensions = ['.tar.gz', '.tar.bz2', '.tar.xz', '.tar.lz', '.tar.Z']
        for ext in multi_extensions:
            if filename.endswith(ext):
                return ext
        return Path(filename).suffix
    
    @staticmethod
    def _normalize_name(name: str) -> str:
        """
        Normalize distribution name per PEP 503.
        
        Parameters
        ----------
        name : str
            Original distribution name.
        
        Returns
        -------
        str
            Normalized name.
        """
        return re.sub(r'[-_.]+', '-', name).lower()
    
    @staticmethod
    def _detect_implementation(python_tag: str, abi_tag: str) -> PythonImplementation:
        """
        Detect Python implementation from tags.
        
        Parameters
        ----------
        python_tag : str
            Python tag.
        abi_tag : str
            ABI tag.
        
        Returns
        -------
        PythonImplementation
            Detected implementation.
        """
        # Check python tag first
        if python_tag:
            impl = PythonImplementation.from_tag(python_tag)
            if impl != PythonImplementation.UNKNOWN:
                return impl
        
        # Check ABI tag
        if abi_tag:
            impl = PythonImplementation.from_tag(abi_tag)
            if impl != PythonImplementation.UNKNOWN:
                return impl
        
        return PythonImplementation.UNKNOWN
    
    @staticmethod
    def _detect_architecture(platform_tag: str) -> Architecture:
        """
        Detect architecture from platform tag.
        
        Parameters
        ----------
        platform_tag : str
            Platform tag.
        
        Returns
        -------
        Architecture
            Detected architecture.
        """
        if not platform_tag:
            return Architecture.UNKNOWN
        
        match = PATTERNS.ARCH_EXTRACT.search(platform_tag)
        if match:
            return Architecture.from_string(match.group(1))
        
        return Architecture.UNKNOWN
    
    @staticmethod
    def _extract_manylinux_version(platform_tag: str) -> Optional[Tuple[int, int]]:
        """
        Extract manylinux version from platform tag.
        
        Parameters
        ----------
        platform_tag : str
            Platform tag.
        
        Returns
        -------
        Optional[Tuple[int, int]]
            Version tuple (major, minor) or None.
        """
        match = PATTERNS.MANYLINUX_VERSION.search(platform_tag)
        if match:
            groups = match.groups()
            if groups[0] and groups[1]:  # _major_minor format
                return (int(groups[0]), int(groups[1]))
            elif groups[2]:  # year format (e.g., 2014)
                year = int(groups[2])
                # Map year to version (approximate)
                year_map = {2010: (1, 0), 2014: (1, 1), 2020: (2, 0)}
                return year_map.get(year)
        return None
    
    @staticmethod
    def _extract_musllinux_version(platform_tag: str) -> Optional[Tuple[int, int]]:
        """
        Extract musllinux version from platform tag.
        
        Parameters
        ----------
        platform_tag : str
            Platform tag.
        
        Returns
        -------
        Optional[Tuple[int, int]]
            Version tuple (major, minor) or None.
        """
        match = PATTERNS.MUSLLINUX_VERSION.search(platform_tag)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return None
    
    def _build_compatibility(
        self,
        python_tag: str,
        abi_tag: str,
        platform_tag: str,
        dist_type: DistributionType,
        implementation: PythonImplementation,
        architecture: Architecture
    ) -> CompatibilityInfo:
        """
        Build comprehensive compatibility information.
        
        Parameters
        ----------
        python_tag : str
            Python tag.
        abi_tag : str
            ABI tag.
        platform_tag : str
            Platform tag.
        dist_type : DistributionType
            Distribution type.
        implementation : PythonImplementation
            Detected implementation.
        architecture : Architecture
            Detected architecture.
        
        Returns
        -------
        CompatibilityInfo
            Complete compatibility information.
        """
        # Parse Python versions
        python_versions = self._parse_python_versions(python_tag)
        
        # Parse platforms
        platforms = self._parse_platforms(platform_tag, dist_type)
        
        # Parse implementations
        implementations = self._parse_implementations(implementation)
        
        # Determine ABI type
        abi_type = ABIType.from_tag(abi_tag) if abi_tag else ABIType.UNKNOWN
        
        # Determine platform type
        platform_type = PlatformType.from_tag(platform_tag) if platform_tag else PlatformType.UNKNOWN
        
        # Check if universal
        is_universal = self._is_universal(dist_type, platform_tag, abi_tag)
        
        return CompatibilityInfo(
            python_versions=tuple(python_versions),
            platforms=tuple(platforms),
            implementations=tuple(implementations),
            is_universal=is_universal,
            requires_specific_abi=abi_type == ABIType.SPECIFIC,
            abi_type=abi_type,
            platform_type=platform_type,
            architecture=architecture if architecture != Architecture.UNKNOWN else None
        )
    
    @staticmethod
    def _parse_python_versions(python_tag: str) -> List[str]:
        """
        Parse Python versions from python tag.
        
        Parameters
        ----------
        python_tag : str
            Python tag.
        
        Returns
        -------
        List[str]
            List of formatted Python versions.
        """
        if not python_tag:
            return []
        
        versions = []
        
        # Handle compound tags like 'py2.py3'
        if '.' in python_tag and 'py' in python_tag:
            parts = python_tag.split('.')
            for part in parts:
                match = re.search(r'(\d+)', part)
                if match:
                    num = match.group(1)
                    versions.append(PackageTagParser._format_python_version(num))
        else:
            match = re.search(r'(?:cp|py|pp|ip|jp)?(\d+)', python_tag)
            if match:
                num = match.group(1)
                versions.append(PackageTagParser._format_python_version(num))
        
        return versions
    
    @staticmethod
    def _format_python_version(num_str: str) -> str:
        """
        Format Python version number.
        
        Parameters
        ----------
        num_str : str
            Raw version number (e.g., '311', '39').
        
        Returns
        -------
        str
            Formatted version (e.g., '3.11', '3.9').
        """
        if len(num_str) == 1:
            return f"3.{num_str}" if num_str.isdigit() else num_str
        elif len(num_str) == 2:
            return f"{num_str[0]}.{num_str[1]}"
        elif len(num_str) == 3:
            return f"{num_str[0]}.{num_str[1:]}"
        return num_str
    
    @staticmethod
    def _parse_platforms(platform_tag: str, dist_type: DistributionType) -> List[str]:
        """
        Parse platform information into readable format.
        
        Parameters
        ----------
        platform_tag : str
            Platform tag.
        dist_type : DistributionType
            Distribution type.
        
        Returns
        -------
        List[str]
            List of human-readable platform descriptions.
        """
        if dist_type == DistributionType.SDIST:
            return ['Source distribution (platform-independent)']
        
        if not platform_tag:
            return ['any']
        
        if platform_tag == 'any':
            return ['Platform-independent']
        
        platform_type = PlatformType.from_tag(platform_tag)
        
        platform_descriptions = {
            PlatformType.WINDOWS: "Windows",
            PlatformType.LINUX: "Linux",
            PlatformType.MACOS: "macOS",
            PlatformType.MANYLINUX: "Manylinux (Linux)",
            PlatformType.MUSLLINUX: "musllinux (Linux/musl)",
            PlatformType.ANY: "Platform-independent",
        }
        
        base_desc = platform_descriptions.get(platform_type, platform_tag)
        
        # Add architecture if available
        arch_match = PATTERNS.ARCH_EXTRACT.search(platform_tag)
        if arch_match:
            arch = arch_match.group(1)
            return [f"{base_desc} ({arch})"]
        
        return [base_desc]
    
    @staticmethod
    def _parse_implementations(implementation: PythonImplementation) -> List[str]:
        """
        Parse implementation information.
        
        Parameters
        ----------
        implementation : PythonImplementation
            Detected implementation.
        
        Returns
        -------
        List[str]
            List of implementation names.
        """
        if implementation != PythonImplementation.UNKNOWN:
            return [implementation.display_name]
        return []
    
    @staticmethod
    def _is_universal(dist_type: DistributionType, platform_tag: str, abi_tag: str) -> bool:
        """
        Check if package is universal (platform-independent).
        
        Parameters
        ----------
        dist_type : DistributionType
            Distribution type.
        platform_tag : str
            Platform tag.
        abi_tag : str
            ABI tag.
        
        Returns
        -------
        bool
            True if universal.
        """
        # Source distributions are universal
        if dist_type == DistributionType.SDIST:
            return True
        
        # Wheel with platform 'any'
        if platform_tag == 'any':
            return True
        
        # Python-only wheels
        if dist_type == DistributionType.WHEEL:
            if abi_tag == 'none' and platform_tag == 'any':
                return True
        
        return False


# ============================================================================
# Package Filter Class
# ============================================================================

T = TypeVar('T', bound=ParsedPackageInfo)


class PackageFilter:
    """
    Filter and query package information based on criteria.
    
    This class provides fluent methods to filter lists of parsed packages
    based on various criteria like Python version, platform, architecture,
    and ABI compatibility.
    
    Parameters
    ----------
    packages : List[ParsedPackageInfo]
        List of parsed package information objects.
    
    Examples
    --------
    >>> parser = PackageTagParser()
    >>> packages = parser.parse_multiple(file_list)
    >>> filter_obj = PackageFilter(packages)
    >>> 
    >>> # Get all Windows packages
    >>> win_pkgs = filter_obj.by_platform_type(PlatformType.WINDOWS)
    >>> 
    >>> # Get CPython 3.11 packages
    >>> cp311_pkgs = filter_obj.by_python_version('3.11')
    >>> 
    >>> # Chain filters
    >>> linux_x64 = filter_obj.by_platform_type(PlatformType.LINUX).by_architecture(Architecture.X86_64)
    """
    
    def __init__(self, packages: List[ParsedPackageInfo]):
        """
        Initialize the PackageFilter.
        
        Parameters
        ----------
        packages : List[ParsedPackageInfo]
            List of parsed package information objects.
        """
        self.packages = packages
    
    def __iter__(self) -> Iterator[ParsedPackageInfo]:
        """Iterate over filtered packages."""
        return iter(self.packages)
    
    def __len__(self) -> int:
        """Return number of filtered packages."""
        return len(self.packages)
    
    def by_platform_type(self, platform_type: Union[PlatformType, str]) -> 'PackageFilter':
        """
        Filter packages by platform type.
        
        Parameters
        ----------
        platform_type : Union[PlatformType, str]
            Platform type to filter by.
        
        Returns
        -------
        PackageFilter
            New filter with filtered packages.
        """
        if isinstance(platform_type, str):
            platform_type = PlatformType(platform_type)
        
        filtered = [
            pkg for pkg in self.packages
            if pkg.compatibility.platform_type == platform_type
        ]
        return PackageFilter(filtered)
    
    def by_platform_pattern(self, pattern: str) -> 'PackageFilter':
        """
        Filter packages by platform tag pattern.
        
        Parameters
        ----------
        pattern : str
            Pattern to match in platform tag (case-insensitive).
        
        Returns
        -------
        PackageFilter
            New filter with filtered packages.
        """
        pattern_lower = pattern.lower()
        filtered = [
            pkg for pkg in self.packages
            if pkg.platform_tag and pattern_lower in pkg.platform_tag.lower()
        ]
        return PackageFilter(filtered)
    
    def by_python_version(self, version: str) -> 'PackageFilter':
        """
        Filter packages by Python version.
        
        Parameters
        ----------
        version : str
            Python version (e.g., '3.11', '3.9').
        
        Returns
        -------
        PackageFilter
            New filter with filtered packages.
        """
        filtered = [
            pkg for pkg in self.packages
            if pkg.compatibility.supports_python_version(version)
        ]
        return PackageFilter(filtered)
    
    def by_python_tag_pattern(self, pattern: str) -> 'PackageFilter':
        """
        Filter packages by Python tag pattern.
        
        Parameters
        ----------
        pattern : str
            Pattern to match in Python tag.
        
        Returns
        -------
        PackageFilter
            New filter with filtered packages.
        """
        filtered = [
            pkg for pkg in self.packages
            if pkg.python_tag and pattern in pkg.python_tag
        ]
        return PackageFilter(filtered)
    
    def by_architecture(self, architecture: Union[Architecture, str]) -> 'PackageFilter':
        """
        Filter packages by architecture.
        
        Parameters
        ----------
        architecture : Union[Architecture, str]
            Architecture to filter by.
        
        Returns
        -------
        PackageFilter
            New filter with filtered packages.
        """
        if isinstance(architecture, str):
            architecture = Architecture.from_string(architecture)
        
        filtered = [
            pkg for pkg in self.packages
            if pkg.architecture == architecture
        ]
        return PackageFilter(filtered)
    
    def by_distribution_type(self, dist_type: Union[DistributionType, str]) -> 'PackageFilter':
        """
        Filter packages by distribution type.
        
        Parameters
        ----------
        dist_type : Union[DistributionType, str]
            Distribution type.
        
        Returns
        -------
        PackageFilter
            New filter with filtered packages.
        """
        if isinstance(dist_type, str):
            dist_type = DistributionType(dist_type)
        
        filtered = [
            pkg for pkg in self.packages
            if pkg.distribution_type == dist_type
        ]
        return PackageFilter(filtered)
    
    def by_abi_type(self, abi_type: Union[ABIType, str]) -> 'PackageFilter':
        """
        Filter packages by ABI type.
        
        Parameters
        ----------
        abi_type : Union[ABIType, str]
            ABI type to filter by.
        
        Returns
        -------
        PackageFilter
            New filter with filtered packages.
        """
        if isinstance(abi_type, str):
            abi_type = ABIType(abi_type)
        
        filtered = [
            pkg for pkg in self.packages
            if pkg.compatibility.abi_type == abi_type
        ]
        return PackageFilter(filtered)
    
    def by_abi_pattern(self, pattern: str) -> 'PackageFilter':
        """
        Filter packages by ABI tag pattern.
        
        Parameters
        ----------
        pattern : str
            Pattern to match in ABI tag.
        
        Returns
        -------
        PackageFilter
            New filter with filtered packages.
        """
        filtered = [
            pkg for pkg in self.packages
            if pkg.abi_tag and pattern in pkg.abi_tag
        ]
        return PackageFilter(filtered)
    
    def by_implementation(self, implementation: Union[PythonImplementation, str]) -> 'PackageFilter':
        """
        Filter packages by Python implementation.
        
        Parameters
        ----------
        implementation : Union[PythonImplementation, str]
            Implementation to filter by.
        
        Returns
        -------
        PackageFilter
            New filter with filtered packages.
        """
        if isinstance(implementation, str):
            implementation = PythonImplementation(implementation)
        
        filtered = [
            pkg for pkg in self.packages
            if pkg.implementation == implementation
        ]
        return PackageFilter(filtered)
    
    def universal_only(self) -> 'PackageFilter':
        """
        Get only platform-independent (universal) packages.
        
        Returns
        -------
        PackageFilter
            New filter with universal packages.
        """
        filtered = [pkg for pkg in self.packages if pkg.is_universal]
        return PackageFilter(filtered)
    
    def platform_specific_only(self) -> 'PackageFilter':
        """
        Get only platform-specific packages.
        
        Returns
        -------
        PackageFilter
            New filter with platform-specific packages.
        """
        filtered = [pkg for pkg in self.packages if not pkg.is_universal]
        return PackageFilter(filtered)
    
    def valid_only(self) -> 'PackageFilter':
        """
        Get only valid packages.
        
        Returns
        -------
        PackageFilter
            New filter with valid packages.
        """
        filtered = [pkg for pkg in self.packages if pkg.is_valid]
        return PackageFilter(filtered)
    
    def by_name(self, name: str, exact: bool = False) -> 'PackageFilter':
        """
        Filter packages by distribution name.
        
        Parameters
        ----------
        name : str
            Distribution name to filter by.
        exact : bool, default=False
            If True, requires exact match; otherwise substring match.
        
        Returns
        -------
        PackageFilter
            New filter with matching packages.
        """
        name_lower = name.lower()
        if exact:
            filtered = [
                pkg for pkg in self.packages
                if pkg.normalized_name == name_lower
            ]
        else:
            filtered = [
                pkg for pkg in self.packages
                if name_lower in pkg.normalized_name
            ]
        return PackageFilter(filtered)
    
    def group_by_name(self) -> Dict[str, List[ParsedPackageInfo]]:
        """
        Group packages by distribution name.
        
        Returns
        -------
        Dict[str, List[ParsedPackageInfo]]
            Dictionary mapping package names to lists of packages.
        """
        groups: Dict[str, List[ParsedPackageInfo]] = {}
        for pkg in self.packages:
            groups.setdefault(pkg.normalized_name, []).append(pkg)
        return groups
    
    def group_by_distribution_type(self) -> Dict[DistributionType, List[ParsedPackageInfo]]:
        """
        Group packages by distribution type.
        
        Returns
        -------
        Dict[DistributionType, List[ParsedPackageInfo]]
            Dictionary mapping distribution types to lists of packages.
        """
        groups: Dict[DistributionType, List[ParsedPackageInfo]] = {}
        for pkg in self.packages:
            groups.setdefault(pkg.distribution_type, []).append(pkg)
        return groups
    
    def group_by_platform_type(self) -> Dict[PlatformType, List[ParsedPackageInfo]]:
        """
        Group packages by platform type.
        
        Returns
        -------
        Dict[PlatformType, List[ParsedPackageInfo]]
            Dictionary mapping platform types to lists of packages.
        """
        groups: Dict[PlatformType, List[ParsedPackageInfo]] = {}
        for pkg in self.packages:
            groups.setdefault(pkg.compatibility.platform_type, []).append(pkg)
        return groups
    
    def get_latest_versions(self) -> 'PackageFilter':
        """
        Get latest version of each package (simple string comparison).
        
        Returns
        -------
        PackageFilter
            New filter with latest versions.
        
        Notes
        -----
        This uses simple string comparison. For proper version comparison,
        use packaging.version.
        """
        grouped = self.group_by_name()
        latest = []
        
        for name, pkgs in grouped.items():
            # Sort by version string (simple comparison)
            sorted_pkgs = sorted(pkgs, key=lambda p: p.version, reverse=True)
            if sorted_pkgs:
                latest.append(sorted_pkgs[0])
        
        return PackageFilter(latest)
    
    def to_list(self) -> List[ParsedPackageInfo]:
        """Get the filtered list of packages."""
        return self.packages.copy()
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the filtered packages.
        
        Returns
        -------
        Dict[str, Any]
            Statistics dictionary.
        """
        total = len(self.packages)
        if total == 0:
            return {'total': 0}
        
        return {
            'total': total,
            'universal': len([p for p in self.packages if p.is_universal]),
            'platform_specific': len([p for p in self.packages if not p.is_universal]),
            'valid': len([p for p in self.packages if p.is_valid]),
            'by_distribution_type': {
                str(dt): len(pkgs)
                for dt, pkgs in self.group_by_distribution_type().items()
            },
            'by_platform_type': {
                str(pt): len(pkgs)
                for pt, pkgs in self.group_by_platform_type().items()
            },
            'unique_names': len(self.group_by_name()),
        }


# ============================================================================
# Convenience Functions
# ============================================================================

# Global parser instance for convenience functions
_global_parser: Optional[PackageTagParser] = None


def _get_global_parser() -> PackageTagParser:
    """Get or create the global parser instance."""
    global _global_parser
    if _global_parser is None:
        _global_parser = PackageTagParser()
    return _global_parser


def parse_package(filename: Union[str, Path]) -> ParsedPackageInfo:
    """
    Convenience function to parse a single package filename.
    
    Parameters
    ----------
    filename : Union[str, Path]
        The filename to parse.
    
    Returns
    -------
    ParsedPackageInfo
        Parsed package information.
    
    Examples
    --------
    >>> info = parse_package("numpy-1.24.3-cp311-cp311-win_amd64.whl")
    >>> print(f"{info.distribution_name} {info.version}")
    numpy 1.24.3
    """
    return _get_global_parser().parse(filename)


def parse_multiple(filenames: List[Union[str, Path]]) -> List[ParsedPackageInfo]:
    """
    Convenience function to parse multiple package filenames.
    
    Parameters
    ----------
    filenames : List[Union[str, Path]]
        List of filenames to parse.
    
    Returns
    -------
    List[ParsedPackageInfo]
        List of parsed package information.
    
    Examples
    --------
    >>> files = ["pandas-2.0.0.whl", "scipy-1.10.0.tar.gz"]
    >>> results = parse_multiple(files)
    """
    return _get_global_parser().parse_multiple(filenames)


def clear_parser_cache() -> None:
    """Clear the global parser's LRU cache."""
    global _global_parser
    if _global_parser is not None:
        _global_parser.parse.cache_clear()
    _global_parser = None


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "DistributionType",
    "PythonImplementation",
    "ABIType",
    "PlatformType",
    "Architecture",
    "TagType",
    
    # Data Classes
    "CompatibilityInfo",
    "ParsedPackageInfo",
    "FilenamePatterns",
    
    # Main Classes
    "PackageTagParser",
    "PackageFilter",
    
    # Convenience Functions
    "parse_package",
    "parse_multiple",
    "clear_parser_cache",
]

