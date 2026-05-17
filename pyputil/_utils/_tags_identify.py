#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Extended PEP Identification and Classification System
======================================================================

This module provides comprehensive identification, validation, and classification
of Python package filenames and tags according to various Python Enhancement
Proposals (PEPs). It supports both complete filenames (wheels, source distributions)
and individual tag components (Python tags, ABI tags, platform tags).

Supported PEPs
--------------
- **PEP 425**: Compatibility Tags for Built Distributions
  Defines the three-part tag system: python tag, ABI tag, platform tag.
  
- **PEP 440**: Version Identification and Dependency Specification
  Defines version string format and normalization rules.
  
- **PEP 491**: The Wheel Binary Package Format 1.9
  Defines the complete wheel filename structure including optional build tags.
  
- **PEP 600**: Future 'manylinux' Platform Tags
  Defines the manylinux platform tag format for Linux binary compatibility.
  
- **PEP 625**: File Name Convention for Source Distributions
  Defines filename patterns for source distribution archives.
  
- **PEP 656**: Platform Tag for Linux Distributions Using musl libc
  Defines the musllinux platform tag format for musl-based Linux distributions.
  
- **PEP 665**: Simple Repository API (metadata format, not filename tags)
  Referenced for completeness but does not define filename patterns.

Examples
--------
>>> from pyputil.tags import identify_pep_from_filename, parse_wheel_filename
>>> peps = identify_pep_from_filename("numpy-1.24.3-cp311-cp311-win_amd64.whl")
>>> print(peps)
[<PEP.PEP_425: 425>, <PEP.PEP_440: 440>, <PEP.PEP_491: 491>]

>>> parsed = parse_wheel_filename("cryptography-39.0.0-cp36-abi3-manylinux_2_28_x86_64.whl")
>>> print(parsed.distribution)
'cryptography'
>>> print(parsed.python_tag)
'cp36'
>>> print(parsed.classification.get_matched_peps())
[<PEP.PEP_425: 425>, <PEP.PEP_440: 440>, <PEP.PEP_491: 491>, <PEP.PEP_600: 600>]

>>> from pep_identifier import is_pep600_platform, TagType
>>> is_pep600_platform("manylinux_2_28_x86_64")
True
>>> is_pep600_platform("musllinux_1_1_x86_64")
False

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
from typing import List, Optional, Set, Dict, Union, Tuple, Any, ClassVar, Iterator
from pathlib import Path
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from functools import lru_cache
import warnings


# ============================================================================
# Enums for Type-Safe PEP References
# ============================================================================

class PEP(Enum):
    """
    Enumeration of PEP numbers supported by this module.
    
    Attributes
    ----------
    PEP_425 : int
        PEP 425 - Compatibility Tags for Built Distributions.
    PEP_440 : int
        PEP 440 - Version Identification and Dependency Specification.
    PEP_491 : int
        PEP 491 - The Wheel Binary Package Format 1.9.
    PEP_600 : int
        PEP 600 - Future 'manylinux' Platform Tags.
    PEP_625 : int
        PEP 625 - File Name Convention for Source Distributions.
    PEP_656 : int
        PEP 656 - Platform Tag for musl-based Linux Distributions.
    PEP_665 : int
        PEP 665 - Simple Repository API.
    """
    PEP_425 = 425
    PEP_440 = 440
    PEP_491 = 491
    PEP_600 = 600
    PEP_625 = 625
    PEP_656 = 656
    PEP_665 = 665
    
    def __int__(self) -> int:
        """Return the integer value of the PEP."""
        return self.value
    
    def __str__(self) -> str:
        """Return the string representation of the PEP."""
        return str(self.value)
    
    @classmethod
    def from_int(cls, value: int) -> Optional['PEP']:
        """
        Convert an integer to a PEP enum value.
        
        Parameters
        ----------
        value : int
            PEP number (e.g., 425, 600).
        
        Returns
        -------
        Optional[PEP]
            Corresponding enum value, or None if not found.
        """
        try:
            return cls(value)
        except ValueError:
            return None
    
    @property
    def title(self) -> str:
        """Get the full title of the PEP."""
        titles = {
            PEP.PEP_425: "Compatibility Tags for Built Distributions",
            PEP.PEP_440: "Version Identification and Dependency Specification",
            PEP.PEP_491: "The Wheel Binary Package Format 1.9",
            PEP.PEP_600: "Future 'manylinux' Platform Tags",
            PEP.PEP_625: "File Name Convention for Source Distributions",
            PEP.PEP_656: "Platform Tag for Linux Distributions Using musl",
            PEP.PEP_665: "Simple Repository API",
        }
        return titles.get(self, f"PEP {self.value}")
    
    @property
    def url(self) -> str:
        """Get the official URL for this PEP."""
        return f"https://www.python.org/dev/peps/pep-{self.value:04d}/"
    
    @property
    def defines_filename_pattern(self) -> bool:
        """Check if this PEP defines a filename pattern."""
        return self in (PEP.PEP_491, PEP.PEP_625)
    
    @property
    def defines_platform_tag(self) -> bool:
        """Check if this PEP defines a platform tag format."""
        return self in (PEP.PEP_425, PEP.PEP_600, PEP.PEP_656)


class TagType(Enum):
    """
    Enumeration of tag types defined in PEP 425.
    
    Attributes
    ----------
    PYTHON : str
        Python version tag (e.g., 'cp311', 'py3').
    ABI : str
        ABI compatibility tag (e.g., 'cp311', 'abi3', 'none').
    PLATFORM : str
        Platform tag (e.g., 'win_amd64', 'manylinux_2_28_x86_64').
    UNKNOWN : str
        Unknown tag type.
    """
    PYTHON = "python"
    ABI = "abi"
    PLATFORM = "platform"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value


class DistributionType(Enum):
    """
    Enumeration of distribution types.
    
    Attributes
    ----------
    WHEEL : str
        Wheel distribution (.whl).
    SDIST : str
        Source distribution (.tar.gz, .zip, etc.).
    UNKNOWN : str
        Unknown distribution type.
    """
    WHEEL = "wheel"
    SDIST = "sdist"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value


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
    def from_tag(cls, tag: str) -> Optional['PythonImplementation']:
        """
        Extract implementation from a Python tag.
        
        Parameters
        ----------
        tag : str
            Python tag string (e.g., 'cp311', 'py3').
        
        Returns
        -------
        Optional[PythonImplementation]
            Detected implementation, or None.
        """
        for impl in cls:
            if impl != cls.UNKNOWN and tag.startswith(impl.value):
                return impl
        return None
    
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
        elif tag.startswith("linux"):
            return cls.LINUX
        elif tag.startswith("macosx"):
            return cls.MACOS
        elif tag.startswith("manylinux"):
            return cls.MANYLINUX
        elif tag.startswith("musllinux"):
            return cls.MUSLLINUX
        return cls.UNKNOWN
    
    def __str__(self) -> str:
        return self.value


# ============================================================================
# Regular Expression 
#  ============================================================================

@dataclass(frozen=True)
class RegexPatterns:
    """
    Container for all compiled regular expression patterns.
    
    This dataclass provides a single source of truth for all regex patterns
    used in PEP identification, with proper documentation for each pattern.
    
    Attributes
    ----------
    PEP440_VERSION : re.Pattern
        Pattern for PEP 440 version strings.
    PEP425_PYTHON : re.Pattern
        Pattern for PEP 425 Python tags.
    PEP425_ABI : re.Pattern
        Pattern for PEP 425 ABI tags.
    PEP425_PLATFORM_BASIC : re.Pattern
        Pattern for basic PEP 425 platform tags.
    PEP491_WHEEL : re.Pattern
        Pattern for PEP 491 wheel filenames.
    PEP600_MANYLINUX : re.Pattern
        Pattern for PEP 600 manylinux platform tags.
    PEP625_SDIST : re.Pattern
        Pattern for PEP 625 source distribution filenames.
    PEP656_MUSLLINUX : re.Pattern
        Pattern for PEP 656 musllinux platform tags.
    """
    
    # PEP 440: Version pattern (simplified but covers most cases)
    # Based on: https://peps.python.org/pep-0440/#appendix-b-parsing-version-strings-with-regular-expressions
    PEP440_VERSION: ClassVar[re.Pattern] = re.compile(
        r'^v?'  # Optional 'v' prefix
        r'(\d+!)?'  # Optional epoch
        r'(\d+)'  # Major version (required)
        r'(\.\d+)*'  # Minor/micro versions
        r'((a|b|rc|alpha|beta|pre|preview)(\d+))?'  # Pre-release
        r'(\.post(\d+))?'  # Post-release
        r'(\.dev(\d+))?'  # Development release
        r'(\+[a-zA-Z0-9.]+)?'  # Local version
        r'$',
        re.IGNORECASE
    )
    
    # PEP 425: Python tag (implementation + version)
    PEP425_PYTHON: ClassVar[re.Pattern] = re.compile(
        r'^(?P<implementation>cp|py|pp|ip|jp|mp|sl)'
        r'(?P<version>\d+)(?:\.(?P<micro>\d+))?$',
        re.IGNORECASE
    )
    
    # PEP 425: ABI tag (implementation-specific, abi3, or none)
    PEP425_ABI: ClassVar[re.Pattern] = re.compile(
        r'^(?P<abi>cp|pp|none|abi3)(?P<version>\d*)$',
        re.IGNORECASE
    )
    
    # PEP 425: Basic platform tags (non-manylinux)
    PEP425_PLATFORM_BASIC: ClassVar[re.Pattern] = re.compile(
        r'^(?P<platform>win|linux|macosx)'
        r'(?P<suffix>[a-zA-Z0-9_.-]*)$',
        re.IGNORECASE
    )
    
    # PEP 491: Wheel filename pattern (including optional build tag)
    # Format: {distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl
    PEP491_WHEEL: ClassVar[re.Pattern] = re.compile(
        r'^(?P<distribution>[a-zA-Z0-9]([a-zA-Z0-9_.-]*[a-zA-Z0-9])?)'
        r'-(?P<version>[a-zA-Z0-9_.!+*-]+?)'
        r'(?:-(?P<build>\d+[a-zA-Z0-9_.-]*))?'
        r'-(?P<python_tag>[a-zA-Z0-9_.-]+?)'
        r'-(?P<abi_tag>[a-zA-Z0-9_.-]+?)'
        r'-(?P<platform_tag>[a-zA-Z0-9_.-]+?)'
        r'\.whl$',
        re.IGNORECASE
    )
    
    # PEP 600: Manylinux platform tags
    # Modern format: manylinux_<major>_<minor>_<arch>
    # Legacy format: manylinux<year>_<arch> (e.g., manylinux2014_x86_64)
    PEP600_MANYLINUX: ClassVar[re.Pattern] = re.compile(
        r'^manylinux'
        r'(?:(?P<year>\d{4})|_(?P<major>\d+)_(?P<minor>\d+))?'
        r'_(?P<arch>[a-zA-Z0-9_.-]+)$',
        re.IGNORECASE
    )
    
    # PEP 625: Source distribution filename pattern
    # Supported extensions: .tar.gz, .zip, .tgz, .tar.bz2, .tar.xz
    PEP625_SDIST: ClassVar[re.Pattern] = re.compile(
        r'^(?P<distribution>[a-zA-Z0-9]([a-zA-Z0-9_.-]*[a-zA-Z0-9])?)'
        r'-(?P<version>[a-zA-Z0-9_.!+*-]+?)'
        r'\.(?P<extension>tar\.gz|zip|tgz|tar\.bz2|tar\.xz|tar\.Z|tar)$',
        re.IGNORECASE
    )
    
    # PEP 656: musllinux platform tags
    # Format: musllinux_<major>_<minor>_<arch>
    PEP656_MUSLLINUX: ClassVar[re.Pattern] = re.compile(
        r'^musllinux_'
        r'(?P<major>\d+)_(?P<minor>\d+)_'
        r'(?P<arch>[a-zA-Z0-9_.-]+)$',
        re.IGNORECASE
    )
    
    # Additional pattern: Platform-independent wheel
    ANY_PLATFORM: ClassVar[re.Pattern] = re.compile(
        r'^any$',
        re.IGNORECASE
    )


# Singleton instance for pattern access
PATTERNS = RegexPatterns()


# ============================================================================
# Data Classes for Parsed Results
# ============================================================================

@dataclass(frozen=True)
class PEPClassification:
    """
    Classification result indicating which PEPs apply to a filename or tag.
    
    Attributes
    ----------
    matches : Dict[PEP, bool]
        Dictionary mapping each PEP to a boolean indicating match status.
    
    Examples
    --------
    >>> classification = PEPClassification({
    ...     PEP.PEP_425: True,
    ...     PEP.PEP_440: True,
    ...     PEP.PEP_491: True,
    ... })
    >>> classification.matches_pep(PEP.PEP_491)
    True
    >>> classification.get_matched_peps()
    [<PEP.PEP_425: 425>, <PEP.PEP_440: 440>, <PEP.PEP_491: 491>]
    """
    matches: Dict[PEP, bool] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Ensure all PEPs have a value in the matches dictionary."""
        all_peps = {
            PEP.PEP_425: False,
            PEP.PEP_440: False,
            PEP.PEP_491: False,
            PEP.PEP_600: False,
            PEP.PEP_625: False,
            PEP.PEP_656: False,
            PEP.PEP_665: False,
        }
        all_peps.update(self.matches)
        object.__setattr__(self, "matches", all_peps)
    
    def matches_pep(self, pep: Union[PEP, int]) -> bool:
        """
        Check if a specific PEP is matched.
        
        Parameters
        ----------
        pep : Union[PEP, int]
            PEP to check.
        
        Returns
        -------
        bool
            True if the PEP is matched.
        """
        if isinstance(pep, int):
            pep_enum = PEP.from_int(pep)
            if pep_enum is None:
                return False
            pep = pep_enum
        return self.matches.get(pep, False)
    
    def get_matched_peps(self) -> List[PEP]:
        """
        Get list of all matched PEPs.
        
        Returns
        -------
        List[PEP]
            Sorted list of matched PEP enums.
        """
        return sorted([pep for pep, matched in self.matches.items() if matched], 
                     key=lambda p: p.value)
    
    def get_matched_numbers(self) -> List[int]:
        """
        Get list of matched PEP numbers.
        
        Returns
        -------
        List[int]
            Sorted list of matched PEP numbers.
        """
        return sorted([pep.value for pep, matched in self.matches.items() if matched])
    
    def to_dict(self) -> Dict[str, bool]:
        """
        Convert to dictionary with string keys.
        
        Returns
        -------
        Dict[str, bool]
            Dictionary with PEP names as keys.
        """
        return {f"PEP_{pep.value}": matched for pep, matched in self.matches.items()}
    
    @property
    def is_wheel(self) -> bool:
        """Check if this is a wheel filename."""
        return self.matches_pep(PEP.PEP_491)
    
    @property
    def is_sdist(self) -> bool:
        """Check if this is a source distribution filename."""
        return self.matches_pep(PEP.PEP_625)
    
    @property
    def uses_manylinux(self) -> bool:
        """Check if this uses manylinux platform tag."""
        return self.matches_pep(PEP.PEP_600)
    
    @property
    def uses_musllinux(self) -> bool:
        """Check if this uses musllinux platform tag."""
        return self.matches_pep(PEP.PEP_656)
    
    def __bool__(self) -> bool:
        """Return True if any PEP is matched."""
        return any(self.matches.values())
    
    def __repr__(self) -> str:
        matched = self.get_matched_numbers()
        return f"PEPClassification(matched={matched})"


@dataclass(frozen=True)
class ParsedTag:
    """
    Parsed representation of a PEP 425 tag component.
    
    Attributes
    ----------
    tag : str
        Original tag string.
    tag_type : TagType
        Type of tag (python, abi, or platform).
    is_valid : bool
        Whether the tag conforms to its expected format.
    implementation : Optional[PythonImplementation]
        Detected implementation (for python/abi tags).
    version : Optional[Tuple[int, ...]]
        Parsed version tuple (for versioned tags).
    platform_type : Optional[PlatformType]
        Detected platform type (for platform tags).
    abi_type : Optional[ABIType]
        Detected ABI type (for ABI tags).
    architecture : Optional[str]
        Detected architecture (for platform tags).
    
    Examples
    --------
    >>> tag = parse_python_tag("cp311")
    >>> tag.tag_type
    <TagType.PYTHON: 'python'>
    >>> tag.implementation
    <PythonImplementation.CPYTHON: 'cp'>
    >>> tag.version
    (3, 11)
    """
    tag: str
    tag_type: TagType
    is_valid: bool
    implementation: Optional[PythonImplementation] = None
    version: Optional[Tuple[int, ...]] = None
    platform_type: Optional[PlatformType] = None
    abi_type: Optional[ABIType] = None
    architecture: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "tag": self.tag,
            "tag_type": str(self.tag_type),
            "is_valid": self.is_valid,
            "implementation": str(self.implementation) if self.implementation else None,
            "version": list(self.version) if self.version else None,
            "platform_type": str(self.platform_type) if self.platform_type else None,
            "abi_type": str(self.abi_type) if self.abi_type else None,
            "architecture": self.architecture,
        }
    
    def __repr__(self) -> str:
        return f"ParsedTag(tag='{self.tag}', type={self.tag_type.value}, valid={self.is_valid})"


@dataclass(frozen=True)
class ParsedWheelFilename:
    """
    Parsed representation of a PEP 491 wheel filename.
    
    Attributes
    ----------
    filename : str
        Original filename.
    distribution : str
        Distribution name.
    version : str
        Version string.
    build_tag : Optional[str]
        Optional build tag.
    python_tag : str
        Python tag.
    abi_tag : str
        ABI tag.
    platform_tag : str
        Platform tag.
    is_valid : bool
        Whether the filename conforms to PEP 491.
    parsed_python : ParsedTag
        Parsed Python tag details.
    parsed_abi : ParsedTag
        Parsed ABI tag details.
    parsed_platform : ParsedTag
        Parsed platform tag details.
    classification : PEPClassification
        PEP classification for this filename.
    
    Examples
    --------
    >>> parsed = parse_wheel_filename("numpy-1.24.3-cp311-cp311-win_amd64.whl")
    >>> parsed.distribution
    'numpy'
    >>> parsed.python_tag
    'cp311'
    >>> parsed.classification.is_wheel
    True
    """
    filename: str
    distribution: str
    version: str
    build_tag: Optional[str]
    python_tag: str
    abi_tag: str
    platform_tag: str
    is_valid: bool
    parsed_python: ParsedTag
    parsed_abi: ParsedTag
    parsed_platform: ParsedTag
    classification: PEPClassification
    
    @property
    def distribution_type(self) -> DistributionType:
        """Get the distribution type."""
        return DistributionType.WHEEL
    
    @property
    def normalized_name(self) -> str:
        """
        Get normalized distribution name according to PEP 503.
        
        Returns
        -------
        str
            Normalized name with runs of punctuation replaced by single hyphen.
        """
        return re.sub(r'[-_.]+', '-', self.distribution).lower()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "filename": self.filename,
            "distribution": self.distribution,
            "normalized_name": self.normalized_name,
            "version": self.version,
            "build_tag": self.build_tag,
            "python_tag": self.python_tag,
            "abi_tag": self.abi_tag,
            "platform_tag": self.platform_tag,
            "is_valid": self.is_valid,
            "distribution_type": str(self.distribution_type),
            "parsed_python": self.parsed_python.to_dict(),
            "parsed_abi": self.parsed_abi.to_dict(),
            "parsed_platform": self.parsed_platform.to_dict(),
            "classification": self.classification.to_dict(),
        }
    
    def get_supported_platforms(self) -> List[str]:
        """
        Get list of platforms this wheel supports.
        
        Returns
        -------
        List[str]
            List of platform identifiers (may include aliases for manylinux).
        """
        platforms = [self.platform_tag]
        
        # For manylinux tags, add compatibility aliases
        if self.parsed_platform.platform_type == PlatformType.MANYLINUX:
            match = PATTERNS.PEP600_MANYLINUX.match(self.platform_tag)
            if match:
                groups = match.groupdict()
                if groups.get("year"):
                    platforms.append(f"manylinux{groups['year']}")
                elif groups.get("major") and groups.get("minor"):
                    platforms.append(f"manylinux_{groups['major']}_{groups['minor']}")
        
        return platforms
    
    def __repr__(self) -> str:
        return f"ParsedWheelFilename(distribution='{self.distribution}', version='{self.version}')"


@dataclass(frozen=True)
class ParsedSdistFilename:
    """
    Parsed representation of a PEP 625 source distribution filename.
    
    Attributes
    ----------
    filename : str
        Original filename.
    distribution : str
        Distribution name.
    version : str
        Version string.
    extension : str
        Archive extension.
    is_valid : bool
        Whether the filename conforms to PEP 625.
    classification : PEPClassification
        PEP classification for this filename.
    
    Examples
    --------
    >>> parsed = parse_sdist_filename("numpy-1.24.3.tar.gz")
    >>> parsed.distribution
    'numpy'
    >>> parsed.extension
    'tar.gz'
    >>> parsed.classification.is_sdist
    True
    """
    filename: str
    distribution: str
    version: str
    extension: str
    is_valid: bool
    classification: PEPClassification
    
    @property
    def distribution_type(self) -> DistributionType:
        """Get the distribution type."""
        return DistributionType.SDIST
    
    @property
    def normalized_name(self) -> str:
        """
        Get normalized distribution name according to PEP 503.
        
        Returns
        -------
        str
            Normalized name with runs of punctuation replaced by single hyphen.
        """
        return re.sub(r'[-_.]+', '-', self.distribution).lower()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "filename": self.filename,
            "distribution": self.distribution,
            "normalized_name": self.normalized_name,
            "version": self.version,
            "extension": self.extension,
            "is_valid": self.is_valid,
            "distribution_type": str(self.distribution_type),
            "classification": self.classification.to_dict(),
        }
    
    @property
    def is_tar_gz(self) -> bool:
        """Check if this is a .tar.gz archive."""
        return self.extension == "tar.gz"
    
    @property
    def is_zip(self) -> bool:
        """Check if this is a .zip archive."""
        return self.extension == "zip"
    
    def __repr__(self) -> str:
        return f"ParsedSdistFilename(distribution='{self.distribution}', version='{self.version}')"


# Type alias for parsed filename results
ParsedFilename = Union[ParsedWheelFilename, ParsedSdistFilename]


# ============================================================================
# Tag Parsing Functions
# ============================================================================

@lru_cache(maxsize=128)
def parse_python_tag(tag: str) -> ParsedTag:
    """
    Parse a Python tag according to PEP 425.
    
    Parameters
    ----------
    tag : str
        Python tag string (e.g., 'cp311', 'py3', 'pp39').
    
    Returns
    -------
    ParsedTag
        Parsed tag information.
    
    Examples
    --------
    >>> parsed = parse_python_tag("cp311")
    >>> parsed.is_valid
    True
    >>> parsed.implementation
    <PythonImplementation.CPYTHON: 'cp'>
    >>> parsed.version
    (3, 11)
    
    >>> parsed = parse_python_tag("py3")
    >>> parsed.implementation
    <PythonImplementation.GENERIC: 'py'>
    >>> parsed.version
    (3,)
    """
    match = PATTERNS.PEP425_PYTHON.match(tag)
    
    if not match:
        return ParsedTag(
            tag=tag,
            tag_type=TagType.PYTHON,
            is_valid=False
        )
    
    groups = match.groupdict()
    implementation = PythonImplementation.from_tag(groups["implementation"])
    
    # Parse version
    version_parts = [int(groups["version"])]
    if groups.get("micro"):
        version_parts.append(int(groups["micro"]))
    
    return ParsedTag(
        tag=tag,
        tag_type=TagType.PYTHON,
        is_valid=True,
        implementation=implementation,
        version=tuple(version_parts)
    )


@lru_cache(maxsize=128)
def parse_abi_tag(tag: str) -> ParsedTag:
    """
    Parse an ABI tag according to PEP 425.
    
    Parameters
    ----------
    tag : str
        ABI tag string (e.g., 'cp311', 'abi3', 'none').
    
    Returns
    -------
    ParsedTag
        Parsed tag information.
    
    Examples
    --------
    >>> parsed = parse_abi_tag("cp311")
    >>> parsed.is_valid
    True
    >>> parsed.abi_type
    <ABIType.SPECIFIC: 'specific'>
    
    >>> parsed = parse_abi_tag("abi3")
    >>> parsed.abi_type
    <ABIType.ABI3: 'abi3'>
    
    >>> parsed = parse_abi_tag("none")
    >>> parsed.abi_type
    <ABIType.NONE: 'none'>
    """
    match = PATTERNS.PEP425_ABI.match(tag)
    
    if not match:
        return ParsedTag(
            tag=tag,
            tag_type=TagType.ABI,
            is_valid=False
        )
    
    groups = match.groupdict()
    abi_type = ABIType.from_tag(tag)
    implementation = None
    
    if groups["abi"] not in ("none", "abi3"):
        implementation = PythonImplementation.from_tag(groups["abi"])
    
    version = None
    if groups.get("version"):
        try:
            version = (int(groups["version"]),)
        except ValueError:
            pass
    
    return ParsedTag(
        tag=tag,
        tag_type=TagType.ABI,
        is_valid=True,
        implementation=implementation,
        abi_type=abi_type,
        version=version
    )


@lru_cache(maxsize=128)
def parse_platform_tag(tag: str) -> ParsedTag:
    """
    Parse a platform tag according to PEP 425, PEP 600, or PEP 656.
    
    Parameters
    ----------
    tag : str
        Platform tag string (e.g., 'win_amd64', 'manylinux_2_28_x86_64').
    
    Returns
    -------
    ParsedTag
        Parsed tag information.
    
    Examples
    --------
    >>> parsed = parse_platform_tag("win_amd64")
    >>> parsed.is_valid
    True
    >>> parsed.platform_type
    <PlatformType.WINDOWS: 'win'>
    >>> parsed.architecture
    'amd64'
    
    >>> parsed = parse_platform_tag("manylinux_2_28_x86_64")
    >>> parsed.platform_type
    <PlatformType.MANYLINUX: 'manylinux'>
    >>> parsed.version
    (2, 28)
    """
    # Check for 'any' platform
    if PATTERNS.ANY_PLATFORM.match(tag):
        return ParsedTag(
            tag=tag,
            tag_type=TagType.PLATFORM,
            is_valid=True,
            platform_type=PlatformType.ANY
        )
    
    # Check for manylinux (PEP 600)
    match = PATTERNS.PEP600_MANYLINUX.match(tag)
    if match:
        groups = match.groupdict()
        version = None
        if groups.get("year"):
            version = (int(groups["year"]),)
        elif groups.get("major") and groups.get("minor"):
            version = (int(groups["major"]), int(groups["minor"]))
        
        return ParsedTag(
            tag=tag,
            tag_type=TagType.PLATFORM,
            is_valid=True,
            platform_type=PlatformType.MANYLINUX,
            version=version,
            architecture=groups.get("arch")
        )
    
    # Check for musllinux (PEP 656)
    match = PATTERNS.PEP656_MUSLLINUX.match(tag)
    if match:
        groups = match.groupdict()
        version = (int(groups["major"]), int(groups["minor"]))
        
        return ParsedTag(
            tag=tag,
            tag_type=TagType.PLATFORM,
            is_valid=True,
            platform_type=PlatformType.MUSLLINUX,
            version=version,
            architecture=groups.get("arch")
        )
    
    # Check for basic platform (PEP 425)
    match = PATTERNS.PEP425_PLATFORM_BASIC.match(tag)
    if match:
        groups = match.groupdict()
        platform_type = PlatformType.from_tag(tag)
        suffix = groups.get("suffix", "")
        
        # Extract architecture from suffix
        arch = suffix.lstrip("_") if suffix else None
        
        return ParsedTag(
            tag=tag,
            tag_type=TagType.PLATFORM,
            is_valid=True,
            platform_type=platform_type,
            architecture=arch
        )
    
    return ParsedTag(
        tag=tag,
        tag_type=TagType.PLATFORM,
        is_valid=False
    )


# ============================================================================
# PEP Identification Functions
# ============================================================================

def is_pep425_tag(tag: str) -> bool:
    """
    Strictly check if a tag conforms to PEP 425.
    
    This function validates whether a given tag (Python, ABI, or basic platform)
    strictly conforms to the PEP 425 specification. It does NOT consider
    manylinux (PEP 600) or musllinux (PEP 656) tags as PEP 425.
    
    Parameters
    ----------
    tag : str
        Tag string to check (e.g., 'cp311', 'abi3', 'win_amd64').
    
    Returns
    -------
    bool
        True if tag matches any of the PEP 425 patterns exactly.
    
    Notes
    -----
    - Python tags: Must start with implementation code (cp, py, pp, ip, jp)
      followed by version digits.
    - ABI tags: Must be 'none', 'abi3', or implementation-specific.
    - Platform tags: Must start with 'win', 'linux', or 'macosx'.
    
    Examples
    --------
    >>> is_pep425_tag('cp311')
    True
    >>> is_pep425_tag('abi3')
    True
    >>> is_pep425_tag('win_amd64')
    True
    >>> is_pep425_tag('manylinux_2_28_x86_64')
    False
    >>> is_pep425_tag('musllinux_1_1_x86_64')
    False
    """
    # Check Python tag
    if PATTERNS.PEP425_PYTHON.match(tag):
        return True
    
    # Check ABI tag
    if PATTERNS.PEP425_ABI.match(tag):
        return True
    
    # Check basic platform tag (but exclude manylinux/musllinux)
    if PATTERNS.PEP425_PLATFORM_BASIC.match(tag):
        # Ensure it's not a manylinux/musllinux tag
        if tag.startswith(('manylinux', 'musllinux')):
            return False
        return True
    
    # Check 'any' platform
    if PATTERNS.ANY_PLATFORM.match(tag):
        return True
    
    return False


def is_pep440_version(version: str) -> bool:
    """
    Check if a string conforms to PEP 440 version format.
    
    Parameters
    ----------
    version : str
        Version string to check.
    
    Returns
    -------
    bool
        True if the version string matches PEP 440 format.
    
    Examples
    --------
    >>> is_pep440_version("1.24.3")
    True
    >>> is_pep440_version("2.0.0a1")
    True
    >>> is_pep440_version("1.0.0.post1")
    True
    >>> is_pep440_version("invalid")
    False
    """
    return bool(PATTERNS.PEP440_VERSION.match(version))


def is_pep491_filename(filename: Union[str, Path]) -> bool:
    """
    Strictly check if a filename conforms to PEP 491 wheel format.
    
    Parameters
    ----------
    filename : Union[str, Path]
        Filename to check.
    
    Returns
    -------
    bool
        True if the filename matches the wheel pattern exactly.
    
    Examples
    --------
    >>> is_pep491_filename('numpy-1.24.3-cp311-cp311-win_amd64.whl')
    True
    >>> is_pep491_filename('requests-2.28.1-py3-none-any.whl')
    True
    >>> is_pep491_filename('scipy-1.10.0.tar.gz')
    False
    """
    return bool(PATTERNS.PEP491_WHEEL.match(str(Path(filename).name)))


def is_pep600_platform(tag: str) -> bool:
    """
    Strictly check if a platform tag conforms to PEP 600 (manylinux).
    
    Parameters
    ----------
    tag : str
        Platform tag to check (e.g., 'manylinux_2_28_x86_64').
    
    Returns
    -------
    bool
        True if the tag matches the manylinux pattern.
    
    Examples
    --------
    >>> is_pep600_platform('manylinux_2_28_x86_64')
    True
    >>> is_pep600_platform('manylinux2014_x86_64')
    True
    >>> is_pep600_platform('linux_x86_64')
    False
    >>> is_pep600_platform('musllinux_1_1_x86_64')
    False
    """
    return bool(PATTERNS.PEP600_MANYLINUX.match(tag))


def is_pep625_filename(filename: Union[str, Path]) -> bool:
    """
    Strictly check if a filename conforms to PEP 625 source distribution format.
    
    Parameters
    ----------
    filename : Union[str, Path]
        Filename to check.
    
    Returns
    -------
    bool
        True if the filename matches the sdist pattern.
    
    Examples
    --------
    >>> is_pep625_filename('numpy-1.24.3.tar.gz')
    True
    >>> is_pep625_filename('pandas-2.0.0.zip')
    True
    >>> is_pep625_filename('Django-4.2.0-py3-none-any.whl')
    False
    """
    return bool(PATTERNS.PEP625_SDIST.match(str(Path(filename).name)))


def is_pep656_platform(tag: str) -> bool:
    """
    Check if a platform tag conforms to PEP 656 (musllinux).
    
    Parameters
    ----------
    tag : str
        Platform tag to check (e.g., 'musllinux_1_1_x86_64').
    
    Returns
    -------
    bool
        True if the tag matches the musllinux pattern.
    
    Examples
    --------
    >>> is_pep656_platform('musllinux_1_1_x86_64')
    True
    >>> is_pep656_platform('musllinux_1_2_aarch64')
    True
    >>> is_pep656_platform('manylinux_2_28_x86_64')
    False
    """
    return bool(PATTERNS.PEP656_MUSLLINUX.match(tag))


# ============================================================================
# Filename Parsing Functions
# ============================================================================

@lru_cache(maxsize=256)
def parse_wheel_filename(filename: Union[str, Path]) -> Optional[ParsedWheelFilename]:
    """
    Parse a wheel filename into structured components.
    
    This function extracts all components from a PEP 491 wheel filename,
    validates each tag according to its respective PEP, and provides
    a comprehensive classification.
    
    Parameters
    ----------
    filename : Union[str, Path]
        Wheel filename to parse.
    
    Returns
    -------
    Optional[ParsedWheelFilename]
        Parsed filename information, or None if not a valid wheel.
    
    Examples
    --------
    >>> parsed = parse_wheel_filename("numpy-1.24.3-cp311-cp311-win_amd64.whl")
    >>> parsed.distribution
    'numpy'
    >>> parsed.python_tag
    'cp311'
    >>> parsed.classification.get_matched_numbers()
    [425, 440, 491]
    
    >>> parsed = parse_wheel_filename("cryptography-39.0.0-cp36-abi3-manylinux_2_28_x86_64.whl")
    >>> parsed.classification.get_matched_numbers()
    [425, 440, 491, 600]
    """
    filename_str = str(Path(filename).name)
    match = PATTERNS.PEP491_WHEEL.match(filename_str)
    
    if not match:
        return None
    
    groups = match.groupdict()
    
    # Extract components
    distribution = groups["distribution"]
    version = groups["version"]
    build_tag = groups.get("build")
    python_tag = groups["python_tag"]
    abi_tag = groups["abi_tag"]
    platform_tag = groups["platform_tag"]
    
    # Parse individual tags
    parsed_python = parse_python_tag(python_tag)
    parsed_abi = parse_abi_tag(abi_tag)
    parsed_platform = parse_platform_tag(platform_tag)
    
    # Build classification
    classification = PEPClassification({
        PEP.PEP_491: True,
        PEP.PEP_440: is_pep440_version(version),
        PEP.PEP_425: all([parsed_python.is_valid, parsed_abi.is_valid,
                         not parsed_platform.platform_type in (PlatformType.MANYLINUX, PlatformType.MUSLLINUX)
                         and parsed_platform.is_valid]),
        PEP.PEP_600: parsed_platform.platform_type == PlatformType.MANYLINUX,
        PEP.PEP_656: parsed_platform.platform_type == PlatformType.MUSLLINUX,
    })
    
    return ParsedWheelFilename(
        filename=filename_str,
        distribution=distribution,
        version=version,
        build_tag=build_tag,
        python_tag=python_tag,
        abi_tag=abi_tag,
        platform_tag=platform_tag,
        is_valid=True,
        parsed_python=parsed_python,
        parsed_abi=parsed_abi,
        parsed_platform=parsed_platform,
        classification=classification
    )


@lru_cache(maxsize=256)
def parse_sdist_filename(filename: Union[str, Path]) -> Optional[ParsedSdistFilename]:
    """
    Parse a source distribution filename into structured components.
    
    This function extracts components from a PEP 625 source distribution
    filename and provides PEP classification.
    
    Parameters
    ----------
    filename : Union[str, Path]
        Source distribution filename to parse.
    
    Returns
    -------
    Optional[ParsedSdistFilename]
        Parsed filename information, or None if not a valid sdist.
    
    Examples
    --------
    >>> parsed = parse_sdist_filename("numpy-1.24.3.tar.gz")
    >>> parsed.distribution
    'numpy'
    >>> parsed.version
    '1.24.3'
    >>> parsed.classification.get_matched_numbers()
    [440, 625]
    """
    filename_str = str(Path(filename).name)
    match = PATTERNS.PEP625_SDIST.match(filename_str)
    
    if not match:
        return None
    
    groups = match.groupdict()
    
    distribution = groups["distribution"]
    version = groups["version"]
    extension = groups["extension"]
    
    classification = PEPClassification({
        PEP.PEP_625: True,
        PEP.PEP_440: is_pep440_version(version),
    })
    
    return ParsedSdistFilename(
        filename=filename_str,
        distribution=distribution,
        version=version,
        extension=extension,
        is_valid=True,
        classification=classification
    )


def parse_filename(filename: Union[str, Path]) -> Optional[ParsedFilename]:
    """
    Parse any package filename (wheel or sdist) into structured components.
    
    This function automatically detects the file type and returns the
    appropriate parsed representation.
    
    Parameters
    ----------
    filename : Union[str, Path]
        Filename to parse.
    
    Returns
    -------
    Optional[ParsedFilename]
        Parsed filename information (ParsedWheelFilename or ParsedSdistFilename),
        or None if not recognized.
    
    Examples
    --------
    >>> parsed = parse_filename("numpy-1.24.3-cp311-cp311-win_amd64.whl")
    >>> isinstance(parsed, ParsedWheelFilename)
    True
    
    >>> parsed = parse_filename("scipy-1.10.0.tar.gz")
    >>> isinstance(parsed, ParsedSdistFilename)
    True
    """
    filename_str = str(filename)
    
    # Try wheel first
    wheel = parse_wheel_filename(filename_str)
    if wheel:
        return wheel
    
    # Try sdist
    sdist = parse_sdist_filename(filename_str)
    if sdist:
        return sdist
    
    return None


# ============================================================================
# Main Identification Function
# ============================================================================

def identify_pep_from_filename(filename: Union[str, Path]) -> List[int]:
    """
    Identify all PEP standards that define the format of the given filename.
    
    This function analyzes a filename and returns all PEP numbers that apply
    to its format. It supports both wheel and source distribution filenames,
    as well as individual tag strings.
    
    Parameters
    ----------
    filename : Union[str, Path]
        Full filename (e.g., 'numpy-1.24.3-cp311-cp311-win_amd64.whl')
        or individual tag string (e.g., 'cp311', 'manylinux_2_28_x86_64').
    
    Returns
    -------
    List[int]
        Sorted list of PEP numbers that apply. Returns empty list if no match.
    
    Examples
    --------
    >>> identify_pep_from_filename('numpy-1.24.3-cp311-cp311-win_amd64.whl')
    [425, 440, 491]
    
    >>> identify_pep_from_filename('cryptography-39.0.0-cp36-abi3-manylinux_2_28_x86_64.whl')
    [425, 440, 491, 600]
    
    >>> identify_pep_from_filename('scipy-1.10.0.tar.gz')
    [440, 625]
    
    >>> identify_pep_from_filename('manylinux_2_28_x86_64')
    [600]
    
    >>> identify_pep_from_filename('unknown-file.txt')
    []
    """
    filename_str = str(Path(filename).name)
    
    # Try parsing as a complete filename
    parsed = parse_filename(filename_str)
    if parsed:
        return parsed.classification.get_matched_numbers()
    
    # If not a recognized filename, check individual tag types
    classification = PEPClassification({})
    
    if is_pep425_tag(filename_str):
        classification.matches[PEP.PEP_425] = True
    
    if is_pep440_version(filename_str):
        classification.matches[PEP.PEP_440] = True
    
    if is_pep600_platform(filename_str):
        classification.matches[PEP.PEP_600] = True
    
    if is_pep656_platform(filename_str):
        classification.matches[PEP.PEP_656] = True
    
    return classification.get_matched_numbers()


def classify_filename(filename: Union[str, Path]) -> Dict[str, bool]:
    """
    Return a detailed classification of which PEP standards the filename satisfies.
    
    Parameters
    ----------
    filename : Union[str, Path]
        Filename to classify.
    
    Returns
    -------
    Dict[str, bool]
        Dictionary with keys 'PEP425', 'PEP440', 'PEP491', 'PEP600',
        'PEP625', 'PEP656' and boolean values.
    
    Examples
    --------
    >>> result = classify_filename('cryptography-39.0.0-cp36-abi3-manylinux_2_28_x86_64.whl')
    >>> result['PEP491']
    True
    >>> result['PEP600']
    True
    >>> result['PEP625']
    False
    """
    peps = identify_pep_from_filename(filename)
    return {
        'PEP425': 425 in peps,
        'PEP440': 440 in peps,
        'PEP491': 491 in peps,
        'PEP600': 600 in peps,
        'PEP625': 625 in peps,
        'PEP656': 656 in peps,
    }


# ============================================================================
# Utility Functions
# ============================================================================

def extract_distribution_name(filename: Union[str, Path]) -> Optional[str]:
    """
    Extract the distribution name from a package filename.
    
    Parameters
    ----------
    filename : Union[str, Path]
        Package filename.
    
    Returns
    -------
    Optional[str]
        Distribution name, or None if not parseable.
    
    Examples
    --------
    >>> extract_distribution_name("numpy-1.24.3-cp311-cp311-win_amd64.whl")
    'numpy'
    >>> extract_distribution_name("scipy-1.10.0.tar.gz")
    'scipy'
    """
    parsed = parse_filename(filename)
    if parsed:
        return parsed.distribution
    return None


def extract_version(filename: Union[str, Path]) -> Optional[str]:
    """
    Extract the version string from a package filename.
    
    Parameters
    ----------
    filename : Union[str, Path]
        Package filename.
    
    Returns
    -------
    Optional[str]
        Version string, or None if not parseable.
    
    Examples
    --------
    >>> extract_version("numpy-1.24.3-cp311-cp311-win_amd64.whl")
    '1.24.3'
    >>> extract_version("scipy-1.10.0.tar.gz")
    '1.10.0'
    """
    parsed = parse_filename(filename)
    if parsed:
        return parsed.version
    return None


def get_distribution_type(filename: Union[str, Path]) -> DistributionType:
    """
    Determine the distribution type from a filename.
    
    Parameters
    ----------
    filename : Union[str, Path]
        Package filename.
    
    Returns
    -------
    DistributionType
        The detected distribution type.
    
    Examples
    --------
    >>> get_distribution_type("numpy-1.24.3-cp311-cp311-win_amd64.whl")
    <DistributionType.WHEEL: 'wheel'>
    >>> get_distribution_type("scipy-1.10.0.tar.gz")
    <DistributionType.SDIST: 'sdist'>
    """
    parsed = parse_filename(filename)
    if parsed:
        return parsed.distribution_type
    return DistributionType.UNKNOWN


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "PEP",
    "TagType",
    "DistributionType",
    "PythonImplementation",
    "ABIType",
    "PlatformType",
    
    # Data Classes
    "PEPClassification",
    "ParsedTag",
    "ParsedWheelFilename",
    "ParsedSdistFilename",
    "RegexPatterns",
    
    # Tag Parsing
    "parse_python_tag",
    "parse_abi_tag",
    "parse_platform_tag",
    
    # PEP Identification
    "is_pep425_tag",
    "is_pep440_version",
    "is_pep491_filename",
    "is_pep600_platform",
    "is_pep625_filename",
    "is_pep656_platform",
    
    # Filename Parsing
    "parse_wheel_filename",
    "parse_sdist_filename",
    "parse_filename",
    
    # Main Functions
    "identify_pep_from_filename",
    "classify_filename",
    
    # Utilities
    "extract_distribution_name",
    "extract_version",
    "get_distribution_type",
]

