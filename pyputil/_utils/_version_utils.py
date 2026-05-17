#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Version Utilities - Comprehensive Version Representation and Comparison Module
==========================================================================

A robust, feature-rich version representation module that implements
semantic versioning with full comparison support following PEP 440 semantics.
This module provides version parsing, comparison, range checking, and
manipulation capabilities with thread-safe caching and comprehensive
error handling.

Examples
--------
>>> from pyputil.version import Version, parse_version
>>> v1 = Version(1, 2, 3)
>>> v2 = Version(1, 2, 0)
>>> v1 > v2
True

>>> beta = Version(1, 0, 0, prerelease="beta")
>>> release = Version(1, 0, 0)
>>> beta < release
True

>>> parsed = parse_version("1.2.3-beta+20240101")
>>> parsed.major
1
>>> parsed.prerelease
'beta'
>>> parsed.build
'20240101'

>>> v = Version(1, 2, 3)
>>> v.bump("minor")
Version(1, 3, 0)

>>> from pyputil.version import VersionRange, check_compatibility
>>> range_spec = VersionRange(">=1.2.3,<2.0.0")
>>> range_spec.contains("1.5.0")
True

References
----------
- PEP 440: https://www.python.org/dev/peps/pep-0440/
- Semantic Versioning: https://semver.org/
"""

import re
from functools import total_ordering, lru_cache
from typing import (
    Any, Dict, List, Tuple, Union, Optional, 
    ClassVar, Pattern, Iterator, overload
)
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
import warnings


# ============================================================================
# Enums for Type-Safe Configuration
# ============================================================================

class ReleaseType(Enum):
    """
    Enumeration of release types with precedence ordering.
    
    Attributes
    ----------
    DEV : int
        Development release (lowest precedence).
    PRE : int
        Pre-release (generic).
    ALPHA : int
        Alpha release.
    BETA : int
        Beta release.
    RC : int
        Release candidate.
    STABLE : int
        Stable/final release (highest precedence).
    POST : int
        Post-release (higher than stable but treated specially).
    UNKNOWN : int
        Unknown release type.
    """
    DEV = 1
    PRE = 1
    PREVIEW = 1
    ALPHA = 2
    BETA = 3
    RC = 4
    CANDIDATE = 4
    STABLE = 5
    FINAL = 5
    RELEASE = 5
    POST = 6
    UNKNOWN = 0
    
    @classmethod
    def from_string(cls, value: str) -> 'ReleaseType':
        """
        Determine release type from string identifier.
        
        Parameters
        ----------
        value : str
            Release type string (e.g., 'alpha', 'beta', 'rc').
        
        Returns
        -------
        ReleaseType
            Corresponding release type enum.
        """
        if not value:
            return cls.STABLE
        
        value_lower = value.lower()
        
        # Development releases
        if value_lower.startswith(('dev', 'pre', 'preview')):
            return cls.DEV
        
        # Alpha releases
        if value_lower.startswith(('alpha', 'a')):
            return cls.ALPHA
        
        # Beta releases
        if value_lower.startswith(('beta', 'b')):
            return cls.BETA
        
        # Release candidates
        if value_lower.startswith(('rc', 'c', 'candidate')):
            return cls.RC
        
        # Post releases
        if value_lower.startswith('post'):
            return cls.POST
        
        # Stable releases
        if value_lower in ('stable', 'final', 'release'):
            return cls.STABLE
        
        return cls.UNKNOWN
    
    @property
    def precedence(self) -> int:
        """
        Get numeric precedence for comparison.
        
        Returns
        -------
        int
            Precedence value (higher = newer).
        """
        return self.value
    
    def __str__(self) -> str:
        return self.name.lower()


class VersionFormat(Enum):
    """
    Output formats for version parsing.
    
    Attributes
    ----------
    OBJECT : str
        Return Version object.
    TUPLE : str
        Return tuple (major, minor, patch, prerelease, build).
    LIST : str
        Return list of components.
    DICT : str
        Return dictionary with component keys.
    STRING : str
        Return normalized string representation.
    """
    OBJECT = "object"
    TUPLE = "tuple"
    LIST = "list"
    DICT = "dict"
    STRING = "string"
    
    def __str__(self) -> str:
        return self.value


class BumpType(Enum):
    """
    Version bump types.
    
    Attributes
    ----------
    MAJOR : str
        Increment major version.
    MINOR : str
        Increment minor version.
    PATCH : str
        Increment patch version.
    PRERELEASE : str
        Increment pre-release number.
    BUILD : str
        Update build metadata.
    """
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    PRERELEASE = "prerelease"
    BUILD = "build"
    
    def __str__(self) -> str:
        return self.value


class RangeOperator(Enum):
    """
    Version range operators.
    
    Attributes
    ----------
    EQ : str
        Equal to (==).
    NE : str
        Not equal to (!=).
    GT : str
        Greater than (>).
    GE : str
        Greater than or equal (>=).
    LT : str
        Less than (<).
    LE : str
        Less than or equal (<=).
    COMPATIBLE : str
        Compatible release (~=).
    ARBITRARY : str
        Arbitrary equality (===).
    """
    EQ = "=="
    NE = "!="
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="
    COMPATIBLE = "~="
    ARBITRARY = "==="
    
    @classmethod
    def from_string(cls, value: str) -> Optional['RangeOperator']:
        """
        Convert string to RangeOperator enum.
        
        Parameters
        ----------
        value : str
            Operator string.
        
        Returns
        -------
        Optional[RangeOperator]
            Corresponding enum value.
        """
        for op in cls:
            if op.value == value:
                return op
        return None
    
    def __str__(self) -> str:
        return self.value


# ============================================================================
# Regular Expression Patterns
# ============================================================================

@dataclass(frozen=True)
class VersionPatterns:
    """
    Container for compiled regular expression patterns.
    
    Attributes
    ----------
    FULL : Pattern
        Complete version pattern with all components.
    SIMPLE : Pattern
        Simple numeric version pattern.
    PRERELEASE_PARTS : Pattern
        Pattern for parsing pre-release components.
    BUILD : Pattern
        Pattern for build metadata.
    V_PREFIX : Pattern
        Pattern for detecting v-prefix.
    RANGE_SPLIT : Pattern
        Pattern for splitting version ranges.
    """
    
    # Complete version pattern
    FULL: ClassVar[Pattern] = re.compile(
        r"""
        ^
        [vV]?
        (?P<major>0|[1-9]\d*)
        (?:\.(?P<minor>0|[1-9]\d*))?
        (?:\.(?P<patch>0|[1-9]\d*))?
        (?:[-_.]?
            (?P<prerelease>
                (?:alpha|a|beta|b|rc|candidate|dev|pre|preview|post)
                (?:[-_.]?\d+)?
                (?:[-_.]\d+)*
            )
        )?
        (?:\+(?P<build>[0-9a-zA-Z][0-9a-zA-Z.-]*))?
        $
        """,
        re.VERBOSE | re.IGNORECASE
    )
    
    # Simple numeric pattern
    SIMPLE: ClassVar[Pattern] = re.compile(
        r'^(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?$'
    )
    
    # Pre-release component parser
    PRERELEASE_PARTS: ClassVar[Pattern] = re.compile(
        r'([a-zA-Z]+)(?:[-_.]?(\d*))?(?:[-_.](.*))?'
    )
    
    # Build metadata pattern
    BUILD: ClassVar[Pattern] = re.compile(
        r'^[0-9a-zA-Z][0-9a-zA-Z.-]*$'
    )
    
    # V-prefix detection
    V_PREFIX: ClassVar[Pattern] = re.compile(r'^[vV](.+)$')
    
    # Range constraint splitter
    RANGE_SPLIT: ClassVar[Pattern] = re.compile(r'\s*,\s*')
    
    # Operator and version extractor
    OPERATOR_VERSION: ClassVar[Pattern] = re.compile(
        r'([<>]=?|==|!=|~=|===)\s*(.+)'
    )


# Singleton instance for pattern access
PATTERNS = VersionPatterns()


# ============================================================================
# Precedence Mapping
# ============================================================================

# Precedence values for release types (higher = newer)
_PRECEDENCE_MAP: Dict[Optional[str], int] = {
    None: 5,
    "final": 5,
    "stable": 5,
    "release": 5,
    "post": 6,
    "rc": 4,
    "candidate": 4,
    "beta": 3,
    "b": 3,
    "alpha": 2,
    "a": 2,
    "dev": 1,
    "pre": 1,
    "preview": 1,
}

# Normalized release type mapping
_RELEASE_TYPE_MAP: Dict[str, str] = {
    "a": "alpha",
    "b": "beta",
    "c": "rc",
    "pre": "dev",
    "preview": "dev",
    "candidate": "rc",
    "final": "stable",
    "release": "stable",
}


# ============================================================================
# Pre-release Normalization
# ============================================================================

@dataclass(frozen=True)
class PrereleaseInfo:
    """
    Normalized pre-release information for comparison.
    
    Attributes
    ----------
    release_type : ReleaseType
        Type of release.
    number : int
        Numeric identifier (e.g., 1 in 'beta1').
    sub_number : int
        Sub-number for complex identifiers (e.g., 2 in 'beta.1.2').
    original : Optional[str]
        Original pre-release string.
    normalized : Optional[str]
        Normalized pre-release string.
    """
    release_type: ReleaseType = ReleaseType.STABLE
    number: int = 0
    sub_number: int = 0
    original: Optional[str] = None
    normalized: Optional[str] = None
    
    @classmethod
    def from_string(cls, prerelease: Optional[str]) -> 'PrereleaseInfo':
        """
        Parse pre-release string into normalized components.
        
        Parameters
        ----------
        prerelease : Optional[str]
            Pre-release string to parse.
        
        Returns
        -------
        PrereleaseInfo
            Normalized pre-release information.
        """
        if not prerelease:
            return cls(release_type=ReleaseType.STABLE)
        
        # Clean and normalize
        cleaned = prerelease.strip().lower()
        cleaned = cleaned.replace('_', '-')
        
        # Parse components
        match = PATTERNS.PRERELEASE_PARTS.match(cleaned)
        if not match:
            return cls(
                release_type=ReleaseType.UNKNOWN,
                original=prerelease,
                normalized=cleaned
            )
        
        tag, num_str, rest = match.groups()
        
        # Normalize tag
        tag_lower = tag.lower()
        normalized_tag = _RELEASE_TYPE_MAP.get(tag_lower, tag_lower)
        release_type = ReleaseType.from_string(tag_lower)
        
        # Parse number
        number = int(num_str) if num_str and num_str.isdigit() else 0
        
        # Parse sub-number
        sub_number = 0
        if rest:
            rest_match = re.search(r'\d+', rest)
            if rest_match:
                sub_number = int(rest_match.group())
        
        # Build normalized string
        if number > 0:
            normalized = f"{normalized_tag}.{number}"
            if sub_number > 0:
                normalized += f".{sub_number}"
        else:
            normalized = normalized_tag
        
        return cls(
            release_type=release_type,
            number=number,
            sub_number=sub_number,
            original=prerelease,
            normalized=normalized
        )
    
    def to_comparison_tuple(self) -> Tuple[int, int, int]:
        """
        Get tuple for version comparison.
        
        Returns
        -------
        Tuple[int, int, int]
            Tuple of (precedence, number, sub_number).
        """
        return (self.release_type.precedence, self.number, self.sub_number)
    
    def __bool__(self) -> bool:
        """Return True if this is a pre-release."""
        return self.release_type != ReleaseType.STABLE


# ============================================================================
# Version Class
# ============================================================================

@total_ordering
class Version:
    """
    Immutable version object with PEP 440 comparison semantics.
    
    This class represents a semantic version with support for pre-release
    identifiers and build metadata. It provides rich comparison operators,
    bumping methods, and various output formats.
    
    Parameters
    ----------
    major : int
        Major version number.
    minor : int, default=0
        Minor version number.
    patch : int, default=0
        Patch version number.
    prerelease : Optional[str], default=None
        Pre-release identifier (e.g., 'beta', 'rc1', 'alpha.2').
    build : Optional[str], default=None
        Build metadata (e.g., '20240101', 'commit.123').
    epoch : int, default=0
        Epoch number (PEP 440).
    
    Attributes
    ----------
    major : int
        Major version number.
    minor : int
        Minor version number.
    patch : int
        Patch version number.
    prerelease : Optional[str]
        Pre-release identifier.
    build : Optional[str]
        Build metadata.
    epoch : int
        Epoch number.
    prerelease_info : PrereleaseInfo
        Normalized pre-release information.
    release_type : ReleaseType
        Type of release.
    
    Examples
    --------
    >>> v1 = Version(1, 2, 3)
    >>> v2 = Version(1, 2, 0)
    >>> v1 > v2
    True
    
    >>> beta = Version(1, 0, 0, prerelease="beta")
    >>> release = Version(1, 0, 0)
    >>> beta < release
    True
    
    >>> rc1 = Version(1, 0, 0, prerelease="rc1")
    >>> rc2 = Version(1, 0, 0, prerelease="rc2")
    >>> rc1 < rc2
    True
    
    >>> v = Version(1, 2, 3, build="20240101")
    >>> str(v)
    '1.2.3+20240101'
    """
    
    __slots__ = (
        "_major", "_minor", "_patch", "_prerelease", "_build", "_epoch",
        "_prerelease_info", "_release_type", "_hash", "_string"
    )
    
    def __init__(
        self,
        major: int,
        minor: int = 0,
        patch: int = 0,
        prerelease: Optional[str] = None,
        build: Optional[str] = None,
        epoch: int = 0,
    ):
        # Validate inputs
        if major < 0:
            raise ValueError(f"Major version cannot be negative: {major}")
        if minor < 0:
            raise ValueError(f"Minor version cannot be negative: {minor}")
        if patch < 0:
            raise ValueError(f"Patch version cannot be negative: {patch}")
        if epoch < 0:
            raise ValueError(f"Epoch cannot be negative: {epoch}")
        
        self._major = major
        self._minor = minor
        self._patch = patch
        self._prerelease = prerelease
        self._build = build
        self._epoch = epoch
        
        # Parse pre-release info
        self._prerelease_info = PrereleaseInfo.from_string(prerelease)
        self._release_type = self._prerelease_info.release_type
        
        # Cache hash and string representation
        self._hash = hash(self._compute_comparison_tuple())
        self._string = self._compute_string()
    
    @property
    def major(self) -> int:
        """Major version number."""
        return self._major
    
    @property
    def minor(self) -> int:
        """Minor version number."""
        return self._minor
    
    @property
    def patch(self) -> int:
        """Patch version number."""
        return self._patch
    
    @property
    def prerelease(self) -> Optional[str]:
        """Pre-release identifier."""
        return self._prerelease
    
    @property
    def build(self) -> Optional[str]:
        """Build metadata."""
        return self._build
    
    @property
    def epoch(self) -> int:
        """Epoch number."""
        return self._epoch
    
    @property
    def prerelease_info(self) -> PrereleaseInfo:
        """Normalized pre-release information."""
        return self._prerelease_info
    
    @property
    def release_type(self) -> ReleaseType:
        """Type of release."""
        return self._release_type
    
    def _compute_comparison_tuple(self) -> Tuple:
        """
        Compute tuple used for version comparison.
        
        Returns
        -------
        Tuple
            Comparison tuple: (epoch, major, minor, patch, pre_tuple).
        """
        return (
            self._epoch,
            self._major,
            self._minor,
            self._patch,
            self._prerelease_info.to_comparison_tuple(),
        )
    
    def _compute_string(self) -> str:
        """
        Compute string representation.
        
        Returns
        -------
        str
            String representation of the version.
        """
        if self._epoch > 0:
            v = f"{self._epoch}!{self._major}.{self._minor}.{self._patch}"
        else:
            v = f"{self._major}.{self._minor}.{self._patch}"
        
        if self._prerelease:
            v += f"-{self._prerelease}"
        if self._build:
            v += f"+{self._build}"
        
        return v
    
    def __eq__(self, other: Any) -> bool:
        """Check equality with another Version."""
        if not isinstance(other, Version):
            return NotImplemented
        return self._compute_comparison_tuple() == other._compute_comparison_tuple()
    
    def __lt__(self, other: Any) -> bool:
        """Check if this version is less than another."""
        if not isinstance(other, Version):
            return NotImplemented
        return self._compute_comparison_tuple() < other._compute_comparison_tuple()
    
    def __hash__(self) -> int:
        """Return cached hash value."""
        return self._hash
    
    def __str__(self) -> str:
        """Return cached string representation."""
        return self._string
    
    def __repr__(self) -> str:
        """Return detailed string representation."""
        parts = [f"{self._major}, {self._minor}, {self._patch}"]
        if self._prerelease:
            parts.append(f"prerelease={self._prerelease!r}")
        if self._build:
            parts.append(f"build={self._build!r}")
        if self._epoch > 0:
            parts.append(f"epoch={self._epoch}")
        return f"Version({', '.join(parts)})"
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert version to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with version components.
        """
        return {
            "major": self._major,
            "minor": self._minor,
            "patch": self._patch,
            "prerelease": self._prerelease,
            "build": self._build,
            "epoch": self._epoch,
            "release_type": str(self._release_type),
            "is_stable": self.is_stable(),
            "is_prerelease": self.is_prerelease(),
            "string": self._string,
        }
    
    def to_tuple(self) -> Tuple[int, int, int, Optional[str], Optional[str], int]:
        """
        Convert version to tuple.
        
        Returns
        -------
        Tuple
            (major, minor, patch, prerelease, build, epoch)
        """
        return (self._major, self._minor, self._patch, self._prerelease, self._build, self._epoch)
    
    def to_list(self) -> List:
        """
        Convert version to list.
        
        Returns
        -------
        List
            [major, minor, patch, prerelease, build, epoch]
        """
        return list(self.to_tuple())
    
    def bump(self, part: Union[str, BumpType] = "patch") -> "Version":
        """
        Increment version component.
        
        Parameters
        ----------
        part : Union[str, BumpType], default='patch'
            Which part of the version to increment.
            Valid values: 'major', 'minor', 'patch'.
        
        Returns
        -------
        Version
            New Version object with incremented value.
        
        Raises
        ------
        ValueError
            If part is invalid.
        
        Examples
        --------
        >>> v = Version(1, 2, 3)
        >>> v.bump("patch")
        Version(1, 2, 4)
        >>> v.bump("minor")
        Version(1, 3, 0)
        >>> v.bump("major")
        Version(2, 0, 0)
        """
        if isinstance(part, str):
            try:
                part = BumpType(part.lower())
            except ValueError:
                raise ValueError(f"Invalid bump part: '{part}'. Must be 'major', 'minor', or 'patch'")
        
        if part == BumpType.MAJOR:
            return Version(
                self._major + 1, 0, 0,
                epoch=self._epoch
            )
        elif part == BumpType.MINOR:
            return Version(
                self._major, self._minor + 1, 0,
                epoch=self._epoch
            )
        elif part == BumpType.PATCH:
            return Version(
                self._major, self._minor, self._patch + 1,
                epoch=self._epoch
            )
        else:
            raise ValueError(f"Cannot bump '{part.value}'. Use 'major', 'minor', or 'patch'")
    
    def is_prerelease(self) -> bool:
        """
        Check if version is a pre-release.
        
        Returns
        -------
        bool
            True if version has pre-release tag, False otherwise.
        """
        return bool(self._prerelease_info)
    
    def is_stable(self) -> bool:
        """
        Check if version is stable (no pre-release).
        
        Returns
        -------
        bool
            True if version has no pre-release tag, False otherwise.
        """
        return not bool(self._prerelease_info)
    
    def is_postrelease(self) -> bool:
        """
        Check if version is a post-release.
        
        Returns
        -------
        bool
            True if version is a post-release.
        """
        return self._release_type == ReleaseType.POST
    
    def is_development(self) -> bool:
        """
        Check if version is a development release.
        
        Returns
        -------
        bool
            True if version is a development release.
        """
        return self._release_type == ReleaseType.DEV
    
    def compatible_with(self, other: "Version") -> bool:
        """
        Check if versions are compatible (same major version).
        
        Parameters
        ----------
        other : Version
            Other version to compare with.
        
        Returns
        -------
        bool
            True if same major version, False otherwise.
        """
        if not isinstance(other, Version):
            return NotImplemented
        return self._epoch == other._epoch and self._major == other._major
    
    def next_major(self) -> "Version":
        """Get next major version."""
        return self.bump(BumpType.MAJOR)
    
    def next_minor(self) -> "Version":
        """Get next minor version."""
        return self.bump(BumpType.MINOR)
    
    def next_patch(self) -> "Version":
        """Get next patch version."""
        return self.bump(BumpType.PATCH)
    
    def without_build(self) -> "Version":
        """
        Return version without build metadata.
        
        Returns
        -------
        Version
            Version object with build metadata removed.
        """
        return Version(
            self._major, self._minor, self._patch,
            prerelease=self._prerelease,
            epoch=self._epoch
        )
    
    def with_build(self, build: str) -> "Version":
        """
        Return version with updated build metadata.
        
        Parameters
        ----------
        build : str
            New build metadata.
        
        Returns
        -------
        Version
            Version object with new build metadata.
        """
        return Version(
            self._major, self._minor, self._patch,
            prerelease=self._prerelease,
            build=build,
            epoch=self._epoch
        )
    
    @classmethod
    def from_string(cls, version: str, strict: bool = True) -> Optional["Version"]:
        """
        Create Version from string.
        
        Parameters
        ----------
        version : str
            Version string to parse.
        strict : bool, default=True
            If True, raise ValueError on invalid version.
        
        Returns
        -------
        Optional[Version]
            Parsed Version object, or None if invalid and strict=False.
        
        Raises
        ------
        ValueError
            If strict=True and version is invalid.
        """
        result = parse_version(version, strict=strict)
        if result is None and strict:
            raise ValueError(f"Invalid version string: {version!r}")
        return result


# ============================================================================
# Version Range Class
# ============================================================================

@dataclass(frozen=True)
class VersionConstraint:
    """
    A single version constraint (operator + version).
    
    Attributes
    ----------
    operator : RangeOperator
        Constraint operator.
    version : Version
        Target version.
    original : str
        Original constraint string.
    """
    operator: RangeOperator
    version: Version
    original: str = ""
    
    def check(self, version: Version) -> bool:
        """
        Check if a version satisfies this constraint.
        
        Parameters
        ----------
        version : Version
            Version to check.
        
        Returns
        -------
        bool
            True if version satisfies constraint.
        """
        if self.operator == RangeOperator.EQ:
            return version == self.version
        elif self.operator == RangeOperator.NE:
            return version != self.version
        elif self.operator == RangeOperator.GT:
            return version > self.version
        elif self.operator == RangeOperator.GE:
            return version >= self.version
        elif self.operator == RangeOperator.LT:
            return version < self.version
        elif self.operator == RangeOperator.LE:
            return version <= self.version
        elif self.operator == RangeOperator.COMPATIBLE:
            # Compatible release: same major, >= version
            if version.epoch != self.version.epoch:
                return False
            if version.major != self.version.major:
                return False
            return version >= self.version
        elif self.operator == RangeOperator.ARBITRARY:
            # Arbitrary equality: string comparison
            return str(version) == str(self.version)
        return False
    
    def __str__(self) -> str:
        if self.original:
            return self.original
        return f"{self.operator.value}{self.version}"
    
    def __repr__(self) -> str:
        return f"VersionConstraint({self.operator.value}{self.version})"


@dataclass(frozen=True)
class VersionRange:
    """
    A version range composed of multiple constraints.
    
    Attributes
    ----------
    constraints : Tuple[VersionConstraint, ...]
        Tuple of version constraints (all must be satisfied).
    original : str
        Original range string.
    is_exact : bool
        Whether this is an exact version requirement.
    is_simple : bool
        Whether this is a simple single-constraint range.
    
    Examples
    --------
    >>> range_spec = VersionRange(">=1.2.3,<2.0.0")
    >>> range_spec.contains("1.5.0")
    True
    >>> range_spec.contains("2.0.0")
    False
    
    >>> exact = VersionRange("1.2.3")
    >>> exact.is_exact
    True
    """
    constraints: Tuple[VersionConstraint, ...] = field(default_factory=tuple)
    original: str = ""
    is_exact: bool = False
    is_simple: bool = False
    
    def __post_init__(self) -> None:
        """Validate after initialization."""
        if not self.constraints and self.original:
            # This shouldn't happen with proper parsing
            pass
    
    @classmethod
    def parse(cls, range_str: str) -> "VersionRange":
        """
        Parse a version range string.
        
        Parameters
        ----------
        range_str : str
            Version range string (e.g., ">=1.2.3,<2.0.0", "~=1.2.3", "1.2.3").
        
        Returns
        -------
        VersionRange
            Parsed version range.
        
        Raises
        ------
        ValueError
            If range string is invalid.
        """
        original = range_str.strip()
        
        if not original:
            raise ValueError("Empty version range")
        
        # Check for compatible release operator
        if original.startswith("~="):
            version_str = original[2:].strip()
            version = Version.from_string(version_str)
            if version is None:
                raise ValueError(f"Invalid version in compatible release: {version_str!r}")
            
            constraint = VersionConstraint(
                operator=RangeOperator.COMPATIBLE,
                version=version,
                original=original
            )
            return cls(
                constraints=(constraint,),
                original=original,
                is_exact=False,
                is_simple=True
            )
        
        # Split by commas
        parts = PATTERNS.RANGE_SPLIT.split(original)
        constraints: List[VersionConstraint] = []
        
        for part in parts:
            if not part:
                continue
            
            # Try to match operator + version
            match = PATTERNS.OPERATOR_VERSION.match(part)
            if match:
                op_str, ver_str = match.groups()
                operator = RangeOperator.from_string(op_str)
                if operator is None:
                    raise ValueError(f"Invalid operator: {op_str!r}")
            else:
                # Assume exact version
                operator = RangeOperator.EQ
                ver_str = part
            
            version = Version.from_string(ver_str.strip())
            if version is None:
                raise ValueError(f"Invalid version in range: {ver_str!r}")
            
            constraints.append(VersionConstraint(
                operator=operator,
                version=version,
                original=part
            ))
        
        if not constraints:
            raise ValueError(f"No valid constraints found in: {range_str!r}")
        
        is_exact = len(constraints) == 1 and constraints[0].operator == RangeOperator.EQ
        is_simple = len(constraints) == 1
        
        return cls(
            constraints=tuple(constraints),
            original=original,
            is_exact=is_exact,
            is_simple=is_simple
        )
    
    def contains(self, version: Union[str, Version]) -> bool:
        """
        Check if a version satisfies this range.
        
        Parameters
        ----------
        version : Union[str, Version]
            Version to check.
        
        Returns
        -------
        bool
            True if version satisfies all constraints.
        
        Examples
        --------
        >>> range_spec = VersionRange(">=1.2.3,<2.0.0")
        >>> range_spec.contains("1.5.0")
        True
        >>> range_spec.contains("2.0.0")
        False
        """
        if isinstance(version, str):
            ver = Version.from_string(version)
            if ver is None:
                return False
        else:
            ver = version
        
        for constraint in self.constraints:
            if not constraint.check(ver):
                return False
        
        return True
    
    def __contains__(self, version: Union[str, Version]) -> bool:
        """Support 'in' operator."""
        return self.contains(version)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary representation.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "original": self.original,
            "is_exact": self.is_exact,
            "is_simple": self.is_simple,
            "constraints": [
                {
                    "operator": str(c.operator),
                    "version": str(c.version),
                    "original": c.original,
                }
                for c in self.constraints
            ],
        }
    
    def __str__(self) -> str:
        return self.original or ", ".join(str(c) for c in self.constraints)
    
    def __repr__(self) -> str:
        return f"VersionRange({self.original!r})"


# ============================================================================
# Version Parsing Functions
# ============================================================================

@lru_cache(maxsize=1024)
def parse_version(
    version: str,
    *,
    strict: bool = False,
    allow_v_prefix: bool = True,
    fill_missing: bool = True,
) -> Optional[Version]:
    """
    Parse a version string into a Version object.
    
    Supports various version formats including:
    - Semantic versions: "1.2.3", "1.2", "1"
    - Pre-release versions: "1.0.0-alpha", "2.0b1", "1.0-rc.1"
    - Build metadata: "1.0.0+20240101", "2.0-rc1+commit.123"
    - With 'v' prefix: "v1.2.3", "v2.0"
    - PEP 440 style: "1.0.0.dev1", "2.0.0.post1"
    - Epoch versions: "1!1.2.3"
    
    Parameters
    ----------
    version : str
        Version string to parse.
    strict : bool, default=False
        If True, raise ValueError on invalid version.
    allow_v_prefix : bool, default=True
        Allow version strings to start with 'v' or 'V'.
    fill_missing : bool, default=True
        Fill missing minor and patch components with 0.
    
    Returns
    -------
    Optional[Version]
        Parsed Version object, or None if invalid and strict=False.
    
    Raises
    ------
    TypeError
        If version is not a string.
    ValueError
        If strict=True and version format is invalid.
    
    Examples
    --------
    >>> parse_version("1.2.3")
    Version(1, 2, 3)
    
    >>> parse_version("v2.0")
    Version(2, 0, 0)
    
    >>> parse_version("1.0.0-beta+20240101")
    Version(1, 0, 0, prerelease='beta', build='20240101')
    
    >>> parse_version("invalid")
    >>> parse_version("invalid", strict=True)
    Traceback (most recent call last):
        ...
    ValueError: Invalid version string: 'invalid'
    """
    if not isinstance(version, str):
        raise TypeError(f"version must be a string, got {type(version).__name__}")
    
    original = version
    version = version.strip()
    
    if not version:
        if strict:
            raise ValueError("Empty version string")
        return None
    
    # Handle v-prefix
    if allow_v_prefix:
        match = PATTERNS.V_PREFIX.match(version)
        if match:
            version = match.group(1)
    
    # Parse epoch
    epoch = 0
    if '!' in version:
        epoch_part, version = version.split('!', 1)
        try:
            epoch = int(epoch_part)
        except ValueError:
            if strict:
                raise ValueError(f"Invalid epoch: {epoch_part!r}")
            return None
    
    # Parse using full pattern
    match = PATTERNS.FULL.match(version)
    if not match:
        if strict:
            raise ValueError(f"Invalid version string: {original!r}")
        return None
    
    groups = match.groupdict()
    
    # Extract components
    try:
        major = int(groups['major'])
        minor_str = groups.get('minor')
        patch_str = groups.get('patch')
        
        minor = int(minor_str) if minor_str else (0 if fill_missing else 0)
        patch = int(patch_str) if patch_str else (0 if fill_missing else 0)
        
        prerelease = groups.get('prerelease')
        build = groups.get('build')
        
        # Clean prerelease
        if prerelease:
            prerelease = prerelease.strip().lower().replace('_', '-')
        
        # Validate build metadata
        if build and not PATTERNS.BUILD.match(build):
            warnings.warn(f"Invalid build metadata format: {build!r}", UserWarning)
        
        return Version(
            major=major,
            minor=minor,
            patch=patch,
            prerelease=prerelease,
            build=build,
            epoch=epoch
        )
        
    except (ValueError, TypeError) as e:
        if strict:
            raise ValueError(f"Invalid version components in {original!r}: {e}") from e
        return None


def parse_version_with_format(
    version: str,
    output: Union[str, VersionFormat] = VersionFormat.OBJECT,
    **kwargs
) -> Union[Version, Tuple, List, Dict, str, None]:
    """
    Parse version and return in specified format.
    
    Parameters
    ----------
    version : str
        Version string to parse.
    output : Union[str, VersionFormat], default=VersionFormat.OBJECT
        Output format:
        - 'object': Version object
        - 'tuple': (major, minor, patch, prerelease, build, epoch)
        - 'list': [major, minor, patch, prerelease, build, epoch]
        - 'dict': Dictionary with component keys
        - 'string': Normalized string representation
    **kwargs
        Additional arguments passed to parse_version.
    
    Returns
    -------
    Union[Version, Tuple, List, Dict, str, None]
        Parsed version in requested format.
    
    Raises
    ------
    ValueError
        If output type is invalid.
    """
    if isinstance(output, str):
        try:
            output = VersionFormat(output.lower())
        except ValueError:
            raise ValueError(f"Invalid output format: {output!r}. "
                           f"Must be one of: {[f.value for f in VersionFormat]}")
    
    ver = parse_version(version, **kwargs)
    if ver is None:
        return None
    
    if output == VersionFormat.OBJECT:
        return ver
    elif output == VersionFormat.TUPLE:
        return ver.to_tuple()
    elif output == VersionFormat.LIST:
        return ver.to_list()
    elif output == VersionFormat.DICT:
        return ver.to_dict()
    elif output == VersionFormat.STRING:
        return str(ver)
    else:
        raise ValueError(f"Unhandled output format: {output}")


# ============================================================================
# Comparison and Compatibility Functions
# ============================================================================

def compare_versions(v1: Union[str, Version], v2: Union[str, Version]) -> int:
    """
    Compare two versions.
    
    Parameters
    ----------
    v1 : Union[str, Version]
        First version.
    v2 : Union[str, Version]
        Second version.
    
    Returns
    -------
    int
        -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2.
    
    Raises
    ------
    ValueError
        If either version cannot be parsed.
    
    Examples
    --------
    >>> compare_versions("1.2.3", "1.2.0")
    1
    >>> compare_versions("1.0.0-beta", "1.0.0")
    -1
    >>> compare_versions("2.0.0", "2.0.0")
    0
    """
    # Parse strings if needed
    if isinstance(v1, str):
        v1_parsed = parse_version(v1, strict=True)
        if v1_parsed is None:
            raise ValueError(f"Could not parse version: {v1!r}")
        v1 = v1_parsed
    
    if isinstance(v2, str):
        v2_parsed = parse_version(v2, strict=True)
        if v2_parsed is None:
            raise ValueError(f"Could not parse version: {v2!r}")
        v2 = v2_parsed
    
    if v1 < v2:
        return -1
    elif v1 > v2:
        return 1
    else:
        return 0


def check_compatibility(version: Union[str, Version], requirement: str) -> bool:
    """
    Check if a version satisfies a requirement.
    
    Parameters
    ----------
    version : Union[str, Version]
        Version to check.
    requirement : str
        Requirement string (e.g., ">=1.0.0", "~=2.0", "1.2.x").
    
    Returns
    -------
    bool
        True if version satisfies requirement, False otherwise.
    
    Examples
    --------
    >>> check_compatibility("1.2.3", ">=1.0.0")
    True
    >>> check_compatibility("2.0.0", "~=1.5")
    False
    >>> check_compatibility("1.5.0", ">=1.5.0,<2.0.0")
    True
    """
    # Parse version
    if isinstance(version, str):
        ver = parse_version(version)
        if ver is None:
            return False
    else:
        ver = version
    
    # Parse requirement
    try:
        range_spec = VersionRange.parse(requirement)
    except ValueError:
        return False
    
    return range_spec.contains(ver)


def get_highest_version(versions: List[Union[str, Version]]) -> Optional[Version]:
    """
    Get the highest version from a list.
    
    Parameters
    ----------
    versions : List[Union[str, Version]]
        List of versions.
    
    Returns
    -------
    Optional[Version]
        Highest version, or None if list is empty.
    
    Examples
    --------
    >>> get_highest_version(["1.0.0", "2.0.0", "1.5.0"])
    Version(2, 0, 0)
    """
    parsed: List[Version] = []
    for v in versions:
        if isinstance(v, str):
            p = parse_version(v)
            if p is not None:
                parsed.append(p)
        else:
            parsed.append(v)
    
    if not parsed:
        return None
    
    return max(parsed)


def get_lowest_version(versions: List[Union[str, Version]]) -> Optional[Version]:
    """
    Get the lowest version from a list.
    
    Parameters
    ----------
    versions : List[Union[str, Version]]
        List of versions.
    
    Returns
    -------
    Optional[Version]
        Lowest version, or None if list is empty.
    
    Examples
    --------
    >>> get_lowest_version(["1.0.0", "2.0.0", "1.5.0"])
    Version(1, 0, 0)
    """
    parsed: List[Version] = []
    for v in versions:
        if isinstance(v, str):
            p = parse_version(v)
            if p is not None:
                parsed.append(p)
        else:
            parsed.append(v)
    
    if not parsed:
        return None
    
    return min(parsed)


def sort_versions(versions: List[Union[str, Version]], reverse: bool = False) -> List[Version]:
    """
    Sort a list of versions.
    
    Parameters
    ----------
    versions : List[Union[str, Version]]
        List of versions to sort.
    reverse : bool, default=False
        If True, sort in descending order.
    
    Returns
    -------
    List[Version]
        Sorted list of Version objects.
    
    Examples
    --------
    >>> sort_versions(["1.0.0", "2.0.0", "1.5.0", "1.0.0-beta"])
    [Version(1, 0, 0, prerelease='beta'), Version(1, 0, 0), Version(1, 5, 0), Version(2, 0, 0)]
    """
    parsed: List[Version] = []
    for v in versions:
        if isinstance(v, str):
            p = parse_version(v)
            if p is not None:
                parsed.append(p)
        else:
            parsed.append(v)
    
    return sorted(parsed, reverse=reverse)


def filter_stable(versions: List[Union[str, Version]]) -> List[Version]:
    """
    Filter list to only stable versions.
    
    Parameters
    ----------
    versions : List[Union[str, Version]]
        List of versions.
    
    Returns
    -------
    List[Version]
        List of stable versions.
    """
    parsed: List[Version] = []
    for v in versions:
        if isinstance(v, str):
            p = parse_version(v)
            if p is not None and p.is_stable():
                parsed.append(p)
        elif v.is_stable():
            parsed.append(v)
    
    return parsed


def filter_prerelease(versions: List[Union[str, Version]]) -> List[Version]:
    """
    Filter list to only pre-release versions.
    
    Parameters
    ----------
    versions : List[Union[str, Version]]
        List of versions.
    
    Returns
    -------
    List[Version]
        List of pre-release versions.
    """
    parsed: List[Version] = []
    for v in versions:
        if isinstance(v, str):
            p = parse_version(v)
            if p is not None and p.is_prerelease():
                parsed.append(p)
        elif v.is_prerelease():
            parsed.append(v)
    
    return parsed


def clear_parse_cache() -> None:
    """Clear the version parsing cache."""
    parse_version.cache_clear()


def get_parse_cache_info() -> Dict[str, Any]:
    """
    Get information about the parse cache.
    
    Returns
    -------
    Dict[str, Any]
        Cache statistics.
    """
    info = parse_version.cache_info()
    total = info.hits + info.misses
    return {
        "hits": info.hits,
        "misses": info.misses,
        "maxsize": info.maxsize,
        "current_size": info.currsize,
        "hit_rate": info.hits / total if total > 0 else 0.0,
    }


# ============================================================================
# Backward Compatibility Aliases
# ============================================================================

# For backward compatibility with original interface
VersionType = Version  # Alias for backward compatibility


def version_parse(
    version: str,
    *,
    output: str = "object",
    fill_missing: bool = True,
    strict: bool = False,
    normalize: bool = True,
    allow_v_prefix: bool = True,
) -> Union[Version, Tuple, List, Dict, None]:
    """
    Legacy interface for backward compatibility.
    
    Please use parse_version() or parse_version_with_format() instead.
    """
    return parse_version_with_format(
        version,
        output=output,
        strict=strict,
        allow_v_prefix=allow_v_prefix,
        fill_missing=fill_missing
    )


def parse_version_range(version_range: str) -> Dict[str, Any]:
    """
    Parse version range specifier.
    
    Parameters
    ----------
    version_range : str
        Version range string.
    
    Returns
    -------
    Dict[str, Any]
        Dictionary with parsed range constraints.
    """
    try:
        range_spec = VersionRange.parse(version_range)
        return range_spec.to_dict()
    except ValueError as e:
        return {
            "original": version_range,
            "error": str(e),
            "constraints": [],
        }


def version_compare(v1: Union[str, Version], v2: Union[str, Version]) -> int:
    """Legacy interface for version comparison."""
    return compare_versions(v1, v2)


def is_compatible(version: Union[str, Version], requirement: str) -> bool:
    """Legacy interface for compatibility checking."""
    return check_compatibility(version, requirement)


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "ReleaseType",
    "VersionFormat",
    "BumpType",
    "RangeOperator",
    
    # Data Classes
    "PrereleaseInfo",
    "VersionConstraint",
    "VersionRange",
    
    # Main Classes
    "Version",
    "VersionType",  # Alias for backward compatibility
    
    # Parsing Functions
    "parse_version",
    "parse_version_with_format",
    "version_parse",  # Legacy
    
    # Comparison Functions
    "compare_versions",
    "version_compare",  # Legacy
    "check_compatibility",
    "is_compatible",  # Legacy
    
    # Range Functions
    "parse_version_range",  # Legacy
    
    # Utility Functions
    "get_highest_version",
    "get_lowest_version",
    "sort_versions",
    "filter_stable",
    "filter_prerelease",
    
    # Cache Management
    "clear_parse_cache",
    "get_parse_cache_info",
]
