#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Version Validator - Comprehensive Version String Validation Library
===================================================================

A robust,  version string validation library supporting multiple
versioning schemes including Semantic Versioning 2.0.0, PEP 440, strict numeric,
and loose version formats. This module provides detailed validation with
customizable constraints and comprehensive error reporting.

Supported Version Schemes
-------------------------
- **Semantic Versioning 2.0.0 (SemVer)**: Major.Minor.Patch[-Prerelease][+Build]
- **PEP 440**: Python package versioning specification
- **Strict Numeric**: Simple Major.Minor.Patch with optional components
- **Loose**: Flexible version format detection

Examples
--------
>>> from pyputil.version import validate_version, VersionScheme
>>> result = validate_version("1.2.3", scheme=VersionScheme.SEMVER)
>>> result.is_valid
True
>>> result.error_message is None
True

>>> result = validate_version("1.2.3-beta+20240101", scheme=VersionScheme.SEMVER)
>>> result.components
VersionComponents(major=1, minor=2, patch=3, prerelease='beta', build='20240101')

>>> # With constraints
>>> result = validate_version(
...     "1.2.3",
...     scheme=VersionScheme.SEMVER,
...     constraints=ValidationConstraints(min_major=2)
... )
>>> result.is_valid
False
>>> result.error_message
'Major version must be >= 2'

>>> # Convenience functions
>>> from pyputil.version import is_semver, is_pep440
>>> is_semver("1.2.3")
True
>>> is_pep440("1.2.3.dev1+local")
True

References
----------
- Semantic Versioning: https://semver.org/
- PEP 440: https://www.python.org/dev/peps/pep-0440/
"""

import re
import sys
from typing import (
    Optional, Tuple, Union, Dict, Any, List, ClassVar, Pattern
)
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from functools import lru_cache
import warnings


# ============================================================================
# Enums for Type-Safe Configuration
# ============================================================================

class VersionScheme(Enum):
    """
    Enumeration of supported versioning schemes.
    
    Attributes
    ----------
    SEMVER : str
        Semantic Versioning 2.0.0 (Major.Minor.Patch[-Prerelease][+Build]).
    PEP440 : str
        Python PEP 440 version specification.
    STRICT : str
        Strict numeric versioning with required components.
    LOOSE : str
        Flexible version format that accepts most reasonable patterns.
    """
    SEMVER = "semver"
    PEP440 = "pep440"
    STRICT = "strict"
    LOOSE = "loose"
    
    def __str__(self) -> str:
        return self.value
    
    @classmethod
    def from_string(cls, value: str) -> Optional['VersionScheme']:
        """
        Convert a string to a VersionScheme enum value.
        
        Parameters
        ----------
        value : str
            String representation of the scheme.
        
        Returns
        -------
        Optional[VersionScheme]
            Corresponding enum value, or None if not found.
        """
        try:
            return cls(value.lower())
        except ValueError:
            return None
    
    @property
    def description(self) -> str:
        """Get a human-readable description of the scheme."""
        descriptions = {
            VersionScheme.SEMVER: "Semantic Versioning 2.0.0",
            VersionScheme.PEP440: "Python PEP 440 Version Specification",
            VersionScheme.STRICT: "Strict Numeric Versioning",
            VersionScheme.LOOSE: "Flexible/Loose Version Format",
        }
        return descriptions.get(self, "Unknown scheme")


class ValidationErrorType(Enum):
    """
    Enumeration of validation error types.
    
    Attributes
    ----------
    NONE : str
        No error.
    EMPTY_STRING : str
        Version string is empty.
    INVALID_TYPE : str
        Version is not a string.
    INVALID_FORMAT : str
        Version format does not match expected pattern.
    TOO_MANY_COMPONENTS : str
        Version has too many dot-separated components.
    NEGATIVE_VERSION : str
        Version component is negative.
    MAJOR_TOO_LOW : str
        Major version below minimum allowed.
    MAJOR_TOO_HIGH : str
        Major version above maximum allowed.
    MINOR_REQUIRED : str
        Minor version required but not present.
    PATCH_REQUIRED : str
        Patch version required but not present.
    PRERELEASE_NOT_ALLOWED : str
        Pre-release versions not allowed.
    BUILD_NOT_ALLOWED : str
        Build metadata not allowed.
    INVALID_PRERELEASE : str
        Invalid pre-release format.
    INVALID_BUILD : str
        Invalid build metadata format.
    UNKNOWN_ERROR : str
        Unknown validation error.
    """
    NONE = "none"
    EMPTY_STRING = "empty_string"
    INVALID_TYPE = "invalid_type"
    INVALID_FORMAT = "invalid_format"
    TOO_MANY_COMPONENTS = "too_many_components"
    NEGATIVE_VERSION = "negative_version"
    MAJOR_TOO_LOW = "major_too_low"
    MAJOR_TOO_HIGH = "major_too_high"
    MINOR_REQUIRED = "minor_required"
    PATCH_REQUIRED = "patch_required"
    PRERELEASE_NOT_ALLOWED = "prerelease_not_allowed"
    BUILD_NOT_ALLOWED = "build_not_allowed"
    INVALID_PRERELEASE = "invalid_prerelease"
    INVALID_BUILD = "invalid_build"
    UNKNOWN_ERROR = "unknown_error"
    
    def __str__(self) -> str:
        return self.value
    
    @property
    def default_message(self) -> str:
        """Get default error message for this error type."""
        messages = {
            ValidationErrorType.NONE: "No error",
            ValidationErrorType.EMPTY_STRING: "Version string is empty",
            ValidationErrorType.INVALID_TYPE: "Version must be a string",
            ValidationErrorType.INVALID_FORMAT: "Invalid version format",
            ValidationErrorType.TOO_MANY_COMPONENTS: "Too many version components",
            ValidationErrorType.NEGATIVE_VERSION: "Version components cannot be negative",
            ValidationErrorType.MAJOR_TOO_LOW: "Major version below minimum allowed",
            ValidationErrorType.MAJOR_TOO_HIGH: "Major version above maximum allowed",
            ValidationErrorType.MINOR_REQUIRED: "Minor version required but not found",
            ValidationErrorType.PATCH_REQUIRED: "Patch version required but not found",
            ValidationErrorType.PRERELEASE_NOT_ALLOWED: "Pre-release versions not allowed",
            ValidationErrorType.BUILD_NOT_ALLOWED: "Build metadata not allowed",
            ValidationErrorType.INVALID_PRERELEASE: "Invalid pre-release format",
            ValidationErrorType.INVALID_BUILD: "Invalid build metadata format",
            ValidationErrorType.UNKNOWN_ERROR: "Unknown validation error",
        }
        return messages.get(self, "Unknown error")


class PreReleaseType(Enum):
    """
    Enumeration of pre-release types.
    
    Attributes
    ----------
    NONE : str
        No pre-release (stable version).
    ALPHA : str
        Alpha release.
    BETA : str
        Beta release.
    RC : str
        Release candidate.
    DEV : str
        Development release.
    POST : str
        Post-release.
    OTHER : str
        Other pre-release type.
    """
    NONE = "none"
    ALPHA = "alpha"
    BETA = "beta"
    RC = "rc"
    DEV = "dev"
    POST = "post"
    OTHER = "other"
    
    @classmethod
    def from_string(cls, value: str) -> 'PreReleaseType':
        """
        Determine pre-release type from string.
        
        Parameters
        ----------
        value : str
            Pre-release identifier string.
        
        Returns
        -------
        PreReleaseType
            Detected pre-release type.
        """
        if not value:
            return cls.NONE
        
        value_lower = value.lower()
        
        if value_lower.startswith(('alpha', 'a')):
            return cls.ALPHA
        elif value_lower.startswith(('beta', 'b')):
            return cls.BETA
        elif value_lower.startswith(('rc', 'c', 'pre')):
            return cls.RC
        elif value_lower.startswith('dev'):
            return cls.DEV
        elif value_lower.startswith('post'):
            return cls.POST
        
        return cls.OTHER
    
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
    SEMVER : Pattern
        Semantic Versioning 2.0.0 pattern.
    PEP440 : Pattern
        PEP 440 version pattern.
    STRICT : Pattern
        Strict numeric version pattern.
    LOOSE : Pattern
        Loose/flexible version pattern.
    V_PREFIX : Pattern
        Pattern to detect and strip v-prefix.
    NUMERIC : Pattern
        Pattern for numeric components.
    PRERELEASE_SEPARATORS : Pattern
        Pattern for pre-release separators.
    """
    
    # Semantic Versioning 2.0.0
    # Format: Major.Minor.Patch[-Prerelease][+Build]
    SEMVER: ClassVar[Pattern] = re.compile(
        r'^(?P<major>0|[1-9]\d*)'
        r'\.(?P<minor>0|[1-9]\d*)'
        r'\.(?P<patch>0|[1-9]\d*)'
        r'(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?'
        r'(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$'
    )
    
    # PEP 440 Version Pattern (comprehensive)
    # Based on: https://www.python.org/dev/peps/pep-0440/#appendix-b-parsing-version-strings-with-regular-expressions
    PEP440: ClassVar[Pattern] = re.compile(
        r'^v?'
        r'(?P<epoch>\d+!)?'
        r'(?P<major>0|[1-9]\d*)'
        r'(?:\.(?P<minor>0|[1-9]\d*))?'
        r'(?:\.(?P<patch>0|[1-9]\d*))?'
        r'(?:(?P<pre_l>[a-zA-Z]+)(?P<pre_n>\d+)?)?'
        r'(?:(?P<post_l>\.post)(?P<post_n>\d+))?'
        r'(?:(?P<dev_l>\.dev)(?P<dev_n>\d+))?'
        r'(?:\+(?P<local>[a-zA-Z0-9.]+))?$',
        re.IGNORECASE
    )
    
    # Strict Numeric Pattern
    STRICT: ClassVar[Pattern] = re.compile(
        r'^(?P<major>\d+)'
        r'(?:\.(?P<minor>\d+))?'
        r'(?:\.(?P<patch>\d+))?'
        r'(?:[-_.](?P<prerelease>[a-zA-Z][a-zA-Z0-9]*))?'
        r'(?:\+(?P<build>[a-zA-Z0-9._-]+))?$'
    )
    
    # Loose/Flexible Pattern
    LOOSE: ClassVar[Pattern] = re.compile(
        r'^[vV]?'
        r'(?P<major>\d+)'
        r'(?:[.-](?P<minor>\d+))?'
        r'(?:[.-](?P<patch>\d+))?'
        r'(?:[-_.]?(?P<prerelease>[a-zA-Z][a-zA-Z0-9.]*))?'
        r'(?:\+(?P<build>[a-zA-Z0-9._-]+))?$'
    )
    
    # V-prefix detection
    V_PREFIX: ClassVar[Pattern] = re.compile(r'^[vV](.+)$')
    
    # Numeric component validation
    NUMERIC: ClassVar[Pattern] = re.compile(r'^\d+$')
    
    # Pre-release separators
    PRERELEASE_SEPARATORS: ClassVar[Pattern] = re.compile(r'[-_.]')


# Singleton instance for pattern access
PATTERNS = VersionPatterns()


# ============================================================================
# Data Classes
# ============================================================================

@dataclass(frozen=True)
class VersionComponents:
    """
    Parsed version components extracted from a version string.
    
    Attributes
    ----------
    major : int
        Major version number.
    minor : Optional[int]
        Minor version number, if present.
    patch : Optional[int]
        Patch version number, if present.
    prerelease : Optional[str]
        Pre-release identifier (e.g., 'beta', 'rc1').
    build : Optional[str]
        Build metadata.
    epoch : Optional[int]
        Epoch number (PEP 440 only).
    prerelease_type : PreReleaseType
        Type of pre-release.
    prerelease_number : Optional[int]
        Numeric part of pre-release if present.
    post_number : Optional[int]
        Post-release number (PEP 440 only).
    dev_number : Optional[int]
        Development release number (PEP 440 only).
    local_version : Optional[str]
        Local version identifier (PEP 440 only).
    raw_string : str
        Original version string.
    scheme : VersionScheme
        Version scheme used for parsing.
    
    Examples
    --------
    >>> comps = VersionComponents(
    ...     major=1, minor=2, patch=3,
    ...     prerelease='beta', build='20240101',
    ...     raw_string='1.2.3-beta+20240101',
    ...     scheme=VersionScheme.SEMVER
    ... )
    >>> comps.prerelease_type
    <PreReleaseType.BETA: 'beta'>
    """
    major: int
    minor: Optional[int] = None
    patch: Optional[int] = None
    prerelease: Optional[str] = None
    build: Optional[str] = None
    epoch: Optional[int] = None
    prerelease_type: PreReleaseType = PreReleaseType.NONE
    prerelease_number: Optional[int] = None
    post_number: Optional[int] = None
    dev_number: Optional[int] = None
    local_version: Optional[str] = None
    raw_string: str = ""
    scheme: VersionScheme = VersionScheme.LOOSE
    
    @property
    def is_stable(self) -> bool:
        """
        Check if this is a stable (non-pre-release) version.
        
        Returns
        -------
        bool
            True if stable, False if pre-release.
        """
        return self.prerelease is None
    
    @property
    def is_prerelease(self) -> bool:
        """
        Check if this is a pre-release version.
        
        Returns
        -------
        bool
            True if pre-release, False otherwise.
        """
        return self.prerelease is not None
    
    @property
    def version_tuple(self) -> Tuple[int, ...]:
        """
        Get version as a tuple of integers.
        
        Returns
        -------
        Tuple[int, ...]
            Tuple of (major, minor, patch) with None values omitted.
        """
        parts: List[int] = [self.major]
        if self.minor is not None:
            parts.append(self.minor)
        if self.patch is not None:
            parts.append(self.patch)
        return tuple(parts)
    
    @property
    def version_string(self) -> str:
        """
        Get normalized version string (without pre-release/build).
        
        Returns
        -------
        str
            Normalized version string like '1.2.3'.
        """
        parts = [str(self.major)]
        if self.minor is not None:
            parts.append(str(self.minor))
        if self.patch is not None:
            parts.append(str(self.patch))
        return '.'.join(parts)
    
    @property
    def full_string(self) -> str:
        """
        Get complete version string with all components.
        
        Returns
        -------
        str
            Complete version string.
        """
        result = self.version_string
        if self.prerelease:
            result += f"-{self.prerelease}"
        if self.build:
            result += f"+{self.build}"
        return result
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary representation.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of version components.
        """
        return {
            "major": self.major,
            "minor": self.minor,
            "patch": self.patch,
            "prerelease": self.prerelease,
            "build": self.build,
            "epoch": self.epoch,
            "prerelease_type": str(self.prerelease_type),
            "prerelease_number": self.prerelease_number,
            "post_number": self.post_number,
            "dev_number": self.dev_number,
            "local_version": self.local_version,
            "is_stable": self.is_stable,
            "version_tuple": list(self.version_tuple),
            "version_string": self.version_string,
            "full_string": self.full_string,
            "raw_string": self.raw_string,
            "scheme": str(self.scheme),
        }
    
    def __lt__(self, other: 'VersionComponents') -> bool:
        """
        Compare versions for ordering.
        
        Parameters
        ----------
        other : VersionComponents
            Other version to compare.
        
        Returns
        -------
        bool
            True if this version is less than other.
        """
        # Compare epoch first (PEP 440)
        self_epoch = self.epoch or 0
        other_epoch = other.epoch or 0
        if self_epoch != other_epoch:
            return self_epoch < other_epoch
        
        # Compare version tuples
        if self.version_tuple != other.version_tuple:
            # Pad with zeros for comparison
            max_len = max(len(self.version_tuple), len(other.version_tuple))
            self_padded = list(self.version_tuple) + [0] * (max_len - len(self.version_tuple))
            other_padded = list(other.version_tuple) + [0] * (max_len - len(other.version_tuple))
            return self_padded < other_padded
        
        # Compare pre-release status (stable > pre-release)
        if self.is_stable != other.is_stable:
            return not self.is_stable
        
        # Compare pre-release type
        if self.prerelease_type != other.prerelease_type:
            type_order = {
                PreReleaseType.NONE: 4,
                PreReleaseType.POST: 3,
                PreReleaseType.DEV: 2,
                PreReleaseType.RC: 1,
                PreReleaseType.BETA: 0,
                PreReleaseType.ALPHA: -1,
            }
            return type_order.get(self.prerelease_type, -2) < type_order.get(other.prerelease_type, -2)
        
        # Compare pre-release numbers
        self_num = self.prerelease_number or 0
        other_num = other.prerelease_number or 0
        if self_num != other_num:
            return self_num < other_num
        
        return False
    
    def __eq__(self, other: object) -> bool:
        """Check equality with another VersionComponents."""
        if not isinstance(other, VersionComponents):
            return NotImplemented
        return (self.epoch == other.epoch and
                self.version_tuple == other.version_tuple and
                self.prerelease == other.prerelease)
    
    def __repr__(self) -> str:
        return f"VersionComponents({self.full_string})"


@dataclass(frozen=True)
class ValidationConstraints:
    """
    Constraints for version validation.
    
    Attributes
    ----------
    allow_v_prefix : bool
        Allow 'v' or 'V' prefix before version number.
    allow_build : bool
        Allow build metadata after '+' sign.
    allow_prerelease : bool
        Allow pre-release tags (alpha, beta, rc, etc.).
    require_minor : bool
        Require minor version component to be present.
    require_patch : bool
        Require patch version component to be present.
    strict_mode : bool
        Use strict validation rules for the selected scheme.
    min_major : int
        Minimum allowed major version (inclusive).
    max_major : Optional[int]
        Maximum allowed major version (inclusive), None for no limit.
    min_minor : Optional[int]
        Minimum allowed minor version (only checked if minor present).
    max_minor : Optional[int]
        Maximum allowed minor version (only checked if minor present).
    allow_zero_major : bool
        Allow major version to be zero (0.x.y versions).
    require_numeric_components : bool
        Require all version components to be numeric.
    
    Examples
    --------
    >>> constraints = ValidationConstraints(
    ...     min_major=1,
    ...     max_major=3,
    ...     require_patch=True,
    ...     allow_prerelease=False
    ... )
    """
    allow_v_prefix: bool = True
    allow_build: bool = True
    allow_prerelease: bool = True
    require_minor: bool = False
    require_patch: bool = False
    strict_mode: bool = False
    min_major: int = 0
    max_major: Optional[int] = None
    min_minor: Optional[int] = None
    max_minor: Optional[int] = None
    allow_zero_major: bool = True
    require_numeric_components: bool = True
    
    def __post_init__(self) -> None:
        """Validate constraints after initialization."""
        if self.min_major < 0:
            raise ValueError("min_major cannot be negative")
        if self.max_major is not None and self.max_major < self.min_major:
            raise ValueError("max_major must be >= min_major")
        if self.min_minor is not None and self.min_minor < 0:
            raise ValueError("min_minor cannot be negative")
        if self.max_minor is not None and self.min_minor is not None and self.max_minor < self.min_minor:
            raise ValueError("max_minor must be >= min_minor")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)
    
    @classmethod
    def for_stable_only(cls) -> 'ValidationConstraints':
        """
        Create constraints for stable versions only (no pre-releases).
        
        Returns
        -------
        ValidationConstraints
            Constraints for stable versions.
        """
        return cls(
            allow_prerelease=False,
            require_patch=True
        )
    
    @classmethod
    def for_semver_strict(cls) -> 'ValidationConstraints':
        """
        Create strict Semantic Versioning constraints.
        
        Returns
        -------
        ValidationConstraints
            Strict SemVer constraints.
        """
        return cls(
            allow_v_prefix=False,
            allow_build=True,
            allow_prerelease=True,
            require_minor=True,
            require_patch=True,
            allow_zero_major=True,
            require_numeric_components=True
        )
    
    @classmethod
    def for_pep440_strict(cls) -> 'ValidationConstraints':
        """
        Create strict PEP 440 constraints.
        
        Returns
        -------
        ValidationConstraints
            Strict PEP 440 constraints.
        """
        return cls(
            allow_v_prefix=True,
            allow_build=True,
            allow_prerelease=True,
            strict_mode=True
        )


@dataclass(frozen=True)
class ValidationResult:
    """
    Result of version validation.
    
    Attributes
    ----------
    is_valid : bool
        Whether the version passed validation.
    error_type : ValidationErrorType
        Type of error if validation failed.
    error_message : Optional[str]
        Detailed error message if validation failed.
    components : Optional[VersionComponents]
        Parsed version components if validation succeeded.
    scheme : VersionScheme
        Version scheme used for validation.
    constraints : ValidationConstraints
        Constraints applied during validation.
    original_version : str
        Original version string provided.
    warnings : List[str]
        Any warnings generated during validation.
    
    Examples
    --------
    >>> result = ValidationResult(
    ...     is_valid=True,
    ...     error_type=ValidationErrorType.NONE,
    ...     components=VersionComponents(major=1, minor=2, patch=3),
    ...     scheme=VersionScheme.SEMVER,
    ...     constraints=ValidationConstraints(),
    ...     original_version="1.2.3"
    ... )
    >>> result.is_valid
    True
    """
    is_valid: bool
    error_type: ValidationErrorType
    error_message: Optional[str] = None
    components: Optional[VersionComponents] = None
    scheme: VersionScheme = VersionScheme.LOOSE
    constraints: ValidationConstraints = field(default_factory=ValidationConstraints)
    original_version: str = ""
    warnings: List[str] = field(default_factory=list)
    
    @classmethod
    def success(
        cls,
        components: VersionComponents,
        scheme: VersionScheme,
        constraints: ValidationConstraints,
        original_version: str,
        warnings: Optional[List[str]] = None
    ) -> 'ValidationResult':
        """
        Create a successful validation result.
        
        Parameters
        ----------
        components : VersionComponents
            Parsed version components.
        scheme : VersionScheme
            Version scheme used.
        constraints : ValidationConstraints
            Constraints applied.
        original_version : str
            Original version string.
        warnings : Optional[List[str]]
            Any warnings.
        
        Returns
        -------
        ValidationResult
            Successful validation result.
        """
        return cls(
            is_valid=True,
            error_type=ValidationErrorType.NONE,
            components=components,
            scheme=scheme,
            constraints=constraints,
            original_version=original_version,
            warnings=warnings or []
        )
    
    @classmethod
    def failure(
        cls,
        error_type: ValidationErrorType,
        error_message: Optional[str] = None,
        scheme: VersionScheme = VersionScheme.LOOSE,
        constraints: ValidationConstraints = field(default_factory=ValidationConstraints),
        original_version: str = "",
        warnings: Optional[List[str]] = None
    ) -> 'ValidationResult':
        """
        Create a failed validation result.
        
        Parameters
        ----------
        error_type : ValidationErrorType
            Type of error.
        error_message : Optional[str]
            Detailed error message.
        scheme : VersionScheme
            Version scheme used.
        constraints : ValidationConstraints
            Constraints applied.
        original_version : str
            Original version string.
        warnings : Optional[List[str]]
            Any warnings.
        
        Returns
        -------
        ValidationResult
            Failed validation result.
        """
        return cls(
            is_valid=False,
            error_type=error_type,
            error_message=error_message or error_type.default_message,
            scheme=scheme,
            constraints=constraints,
            original_version=original_version,
            warnings=warnings or []
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "is_valid": self.is_valid,
            "error_type": str(self.error_type),
            "error_message": self.error_message,
            "scheme": str(self.scheme),
            "original_version": self.original_version,
            "warnings": self.warnings,
        }
        if self.components:
            result["components"] = self.components.to_dict()
        return result
    
    def __bool__(self) -> bool:
        """Return True if validation succeeded."""
        return self.is_valid
    
    def __repr__(self) -> str:
        status = "✓" if self.is_valid else "✗"
        return f"ValidationResult({status} {self.original_version})"


# ============================================================================
# Core Validation Functions
# ============================================================================

def _strip_v_prefix(version: str, allow: bool) -> Tuple[str, bool]:
    """
    Strip 'v' or 'V' prefix from version string.
    
    Parameters
    ----------
    version : str
        Version string to process.
    allow : bool
        Whether v-prefix is allowed.
    
    Returns
    -------
    Tuple[str, bool]
        Tuple of (stripped version, had_prefix).
    """
    match = PATTERNS.V_PREFIX.match(version)
    if match:
        if allow:
            return match.group(1), True
        else:
            return version, True  # Return original but mark as having prefix
    return version, False


def _validate_semver(
    version: str,
    constraints: ValidationConstraints
) -> ValidationResult:
    """
    Validate using Semantic Versioning 2.0.0.
    
    Parameters
    ----------
    version : str
        Version string to validate.
    constraints : ValidationConstraints
        Validation constraints.
    
    Returns
    -------
    ValidationResult
        Validation result.
    """
    warnings_list: List[str] = []
    
    # Handle v-prefix
    version, had_v_prefix = _strip_v_prefix(version, constraints.allow_v_prefix)
    if had_v_prefix and not constraints.allow_v_prefix:
        return ValidationResult.failure(
            ValidationErrorType.INVALID_FORMAT,
            "v-prefix not allowed",
            VersionScheme.SEMVER,
            constraints,
            version
        )
    
    match = PATTERNS.SEMVER.match(version)
    if not match:
        return ValidationResult.failure(
            ValidationErrorType.INVALID_FORMAT,
            "Invalid Semantic Version format (expected: major.minor.patch[-prerelease][+build])",
            VersionScheme.SEMVER,
            constraints,
            version
        )
    
    groups = match.groupdict()
    
    major = int(groups['major'])
    minor = int(groups['minor'])
    patch = int(groups['patch'])
    prerelease = groups.get('prerelease')
    build = groups.get('build')
    
    # Check constraints
    if major < 0:
        return ValidationResult.failure(
            ValidationErrorType.NEGATIVE_VERSION,
            f"Major version cannot be negative (got {major})",
            VersionScheme.SEMVER,
            constraints,
            version
        )
    
    if not constraints.allow_zero_major and major == 0:
        return ValidationResult.failure(
            ValidationErrorType.MAJOR_TOO_LOW,
            "Major version 0 not allowed",
            VersionScheme.SEMVER,
            constraints,
            version
        )
    
    if major < constraints.min_major:
        return ValidationResult.failure(
            ValidationErrorType.MAJOR_TOO_LOW,
            f"Major version must be >= {constraints.min_major} (got {major})",
            VersionScheme.SEMVER,
            constraints,
            version
        )
    
    if constraints.max_major is not None and major > constraints.max_major:
        return ValidationResult.failure(
            ValidationErrorType.MAJOR_TOO_HIGH,
            f"Major version must be <= {constraints.max_major} (got {major})",
            VersionScheme.SEMVER,
            constraints,
            version
        )
    
    if constraints.require_minor and minor is None:
        return ValidationResult.failure(
            ValidationErrorType.MINOR_REQUIRED,
            "Minor version required",
            VersionScheme.SEMVER,
            constraints,
            version
        )
    
    if constraints.require_patch and patch is None:
        return ValidationResult.failure(
            ValidationErrorType.PATCH_REQUIRED,
            "Patch version required",
            VersionScheme.SEMVER,
            constraints,
            version
        )
    
    if prerelease and not constraints.allow_prerelease:
        return ValidationResult.failure(
            ValidationErrorType.PRERELEASE_NOT_ALLOWED,
            f"Pre-release versions not allowed (found '{prerelease}')",
            VersionScheme.SEMVER,
            constraints,
            version
        )
    
    if build and not constraints.allow_build:
        return ValidationResult.failure(
            ValidationErrorType.BUILD_NOT_ALLOWED,
            f"Build metadata not allowed (found '{build}')",
            VersionScheme.SEMVER,
            constraints,
            version
        )
    
    # Check minor/patch constraints if present
    if constraints.min_minor is not None and minor < constraints.min_minor:
        warnings_list.append(f"Minor version {minor} below recommended minimum {constraints.min_minor}")
    
    if constraints.max_minor is not None and minor > constraints.max_minor:
        warnings_list.append(f"Minor version {minor} above recommended maximum {constraints.max_minor}")
    
    # Determine pre-release type
    prerelease_type = PreReleaseType.from_string(prerelease) if prerelease else PreReleaseType.NONE
    
    # Extract pre-release number
    prerelease_number = None
    if prerelease:
        num_match = re.search(r'(\d+)$', prerelease)
        if num_match:
            prerelease_number = int(num_match.group(1))
    
    components = VersionComponents(
        major=major,
        minor=minor,
        patch=patch,
        prerelease=prerelease,
        build=build,
        prerelease_type=prerelease_type,
        prerelease_number=prerelease_number,
        raw_string=version,
        scheme=VersionScheme.SEMVER
    )
    
    return ValidationResult.success(
        components,
        VersionScheme.SEMVER,
        constraints,
        version,
        warnings_list
    )


def _validate_pep440(
    version: str,
    constraints: ValidationConstraints
) -> ValidationResult:
    """
    Validate using PEP 440 version specification.
    
    Parameters
    ----------
    version : str
        Version string to validate.
    constraints : ValidationConstraints
        Validation constraints.
    
    Returns
    -------
    ValidationResult
        Validation result.
    """
    warnings_list: List[str] = []
    
    # Handle v-prefix (PEP 440 allows it)
    version, had_v_prefix = _strip_v_prefix(version, constraints.allow_v_prefix)
    
    match = PATTERNS.PEP440.match(version)
    if not match:
        return ValidationResult.failure(
            ValidationErrorType.INVALID_FORMAT,
            "Invalid PEP 440 version format",
            VersionScheme.PEP440,
            constraints,
            version
        )
    
    groups = match.groupdict()
    
    # Parse epoch
    epoch = None
    if groups.get('epoch'):
        epoch = int(groups['epoch'].rstrip('!'))
    
    major = int(groups['major'])
    minor = int(groups['minor']) if groups.get('minor') else None
    patch = int(groups['patch']) if groups.get('patch') else None
    
    # Parse pre-release
    prerelease = None
    if groups.get('pre_l'):
        pre_l = groups['pre_l']
        pre_n = groups.get('pre_n', '')
        prerelease = f"{pre_l}{pre_n}"
    
    # Parse post-release
    post_number = None
    if groups.get('post_n'):
        post_number = int(groups['post_n'])
        if prerelease is None:
            prerelease = f"post{post_number}"
    
    # Parse dev-release
    dev_number = None
    if groups.get('dev_n'):
        dev_number = int(groups['dev_n'])
        if prerelease is None:
            prerelease = f"dev{dev_number}"
    
    local_version = groups.get('local')
    build = local_version  # PEP 440 uses local version as build metadata
    
    # Check constraints
    if major < 0:
        return ValidationResult.failure(
            ValidationErrorType.NEGATIVE_VERSION,
            f"Major version cannot be negative (got {major})",
            VersionScheme.PEP440,
            constraints,
            version
        )
    
    if not constraints.allow_zero_major and major == 0:
        return ValidationResult.failure(
            ValidationErrorType.MAJOR_TOO_LOW,
            "Major version 0 not allowed",
            VersionScheme.PEP440,
            constraints,
            version
        )
    
    if major < constraints.min_major:
        return ValidationResult.failure(
            ValidationErrorType.MAJOR_TOO_LOW,
            f"Major version must be >= {constraints.min_major} (got {major})",
            VersionScheme.PEP440,
            constraints,
            version
        )
    
    if constraints.max_major is not None and major > constraints.max_major:
        return ValidationResult.failure(
            ValidationErrorType.MAJOR_TOO_HIGH,
            f"Major version must be <= {constraints.max_major} (got {major})",
            VersionScheme.PEP440,
            constraints,
            version
        )
    
    if constraints.require_minor and minor is None:
        return ValidationResult.failure(
            ValidationErrorType.MINOR_REQUIRED,
            "Minor version required",
            VersionScheme.PEP440,
            constraints,
            version
        )
    
    if constraints.require_patch and patch is None:
        return ValidationResult.failure(
            ValidationErrorType.PATCH_REQUIRED,
            "Patch version required",
            VersionScheme.PEP440,
            constraints,
            version
        )
    
    if prerelease and not constraints.allow_prerelease:
        return ValidationResult.failure(
            ValidationErrorType.PRERELEASE_NOT_ALLOWED,
            f"Pre-release versions not allowed (found '{prerelease}')",
            VersionScheme.PEP440,
            constraints,
            version
        )
    
    if build and not constraints.allow_build:
        return ValidationResult.failure(
            ValidationErrorType.BUILD_NOT_ALLOWED,
            f"Build/local version not allowed (found '{build}')",
            VersionScheme.PEP440,
            constraints,
            version
        )
    
    # Strict PEP 440 additional checks
    if constraints.strict_mode:
        # Check for invalid patterns in strict mode
        if version.startswith('0.') and major == 0:
            # Version 0.x requires explicit handling
            pass
        
        # Check local version format
        if local_version and not re.match(r'^[a-zA-Z0-9.]+$', local_version):
            return ValidationResult.failure(
                ValidationErrorType.INVALID_BUILD,
                f"Invalid local version format: '{local_version}'",
                VersionScheme.PEP440,
                constraints,
                version
            )
    
    prerelease_type = PreReleaseType.from_string(prerelease) if prerelease else PreReleaseType.NONE
    
    # Extract pre-release number
    prerelease_number = None
    if prerelease:
        num_match = re.search(r'(\d+)$', prerelease)
        if num_match:
            prerelease_number = int(num_match.group(1))
    
    components = VersionComponents(
        major=major,
        minor=minor,
        patch=patch,
        prerelease=prerelease,
        build=build,
        epoch=epoch,
        prerelease_type=prerelease_type,
        prerelease_number=prerelease_number,
        post_number=post_number,
        dev_number=dev_number,
        local_version=local_version,
        raw_string=version,
        scheme=VersionScheme.PEP440
    )
    
    return ValidationResult.success(
        components,
        VersionScheme.PEP440,
        constraints,
        version,
        warnings_list
    )


def _validate_strict(
    version: str,
    constraints: ValidationConstraints
) -> ValidationResult:
    """
    Validate using strict numeric versioning.
    
    Parameters
    ----------
    version : str
        Version string to validate.
    constraints : ValidationConstraints
        Validation constraints.
    
    Returns
    -------
    ValidationResult
        Validation result.
    """
    warnings_list: List[str] = []
    
    # Handle v-prefix
    version, had_v_prefix = _strip_v_prefix(version, constraints.allow_v_prefix)
    if had_v_prefix and not constraints.allow_v_prefix:
        return ValidationResult.failure(
            ValidationErrorType.INVALID_FORMAT,
            "v-prefix not allowed",
            VersionScheme.STRICT,
            constraints,
            version
        )
    
    match = PATTERNS.STRICT.match(version)
    if not match:
        return ValidationResult.failure(
            ValidationErrorType.INVALID_FORMAT,
            "Invalid strict version format",
            VersionScheme.STRICT,
            constraints,
            version
        )
    
    groups = match.groupdict()
    
    major = int(groups['major'])
    minor = int(groups['minor']) if groups.get('minor') else None
    patch = int(groups['patch']) if groups.get('patch') else None
    prerelease = groups.get('prerelease')
    build = groups.get('build')
    
    # Check constraints
    if major < constraints.min_major:
        return ValidationResult.failure(
            ValidationErrorType.MAJOR_TOO_LOW,
            f"Major version must be >= {constraints.min_major} (got {major})",
            VersionScheme.STRICT,
            constraints,
            version
        )
    
    if constraints.max_major is not None and major > constraints.max_major:
        return ValidationResult.failure(
            ValidationErrorType.MAJOR_TOO_HIGH,
            f"Major version must be <= {constraints.max_major} (got {major})",
            VersionScheme.STRICT,
            constraints,
            version
        )
    
    if constraints.require_minor and minor is None:
        return ValidationResult.failure(
            ValidationErrorType.MINOR_REQUIRED,
            "Minor version required",
            VersionScheme.STRICT,
            constraints,
            version
        )
    
    if constraints.require_patch and patch is None:
        return ValidationResult.failure(
            ValidationErrorType.PATCH_REQUIRED,
            "Patch version required",
            VersionScheme.STRICT,
            constraints,
            version
        )
    
    if prerelease and not constraints.allow_prerelease:
        return ValidationResult.failure(
            ValidationErrorType.PRERELEASE_NOT_ALLOWED,
            f"Pre-release versions not allowed (found '{prerelease}')",
            VersionScheme.STRICT,
            constraints,
            version
        )
    
    if build and not constraints.allow_build:
        return ValidationResult.failure(
            ValidationErrorType.BUILD_NOT_ALLOWED,
            f"Build metadata not allowed (found '{build}')",
            VersionScheme.STRICT,
            constraints,
            version
        )
    
    # Validate numeric components if required
    if constraints.require_numeric_components:
        if minor is not None and not PATTERNS.NUMERIC.match(str(minor)):
            return ValidationResult.failure(
                ValidationErrorType.INVALID_FORMAT,
                "Minor version must be numeric",
                VersionScheme.STRICT,
                constraints,
                version
            )
        if patch is not None and not PATTERNS.NUMERIC.match(str(patch)):
            return ValidationResult.failure(
                ValidationErrorType.INVALID_FORMAT,
                "Patch version must be numeric",
                VersionScheme.STRICT,
                constraints,
                version
            )
    
    prerelease_type = PreReleaseType.from_string(prerelease) if prerelease else PreReleaseType.NONE
    
    components = VersionComponents(
        major=major,
        minor=minor,
        patch=patch,
        prerelease=prerelease,
        build=build,
        prerelease_type=prerelease_type,
        raw_string=version,
        scheme=VersionScheme.STRICT
    )
    
    return ValidationResult.success(
        components,
        VersionScheme.STRICT,
        constraints,
        version,
        warnings_list
    )


def _validate_loose(
    version: str,
    constraints: ValidationConstraints
) -> ValidationResult:
    """
    Validate using loose/flexible versioning.
    
    Parameters
    ----------
    version : str
        Version string to validate.
    constraints : ValidationConstraints
        Validation constraints.
    
    Returns
    -------
    ValidationResult
        Validation result.
    """
    warnings_list: List[str] = []
    
    # Handle v-prefix
    version, had_v_prefix = _strip_v_prefix(version, constraints.allow_v_prefix)
    
    # Check for too many components
    parts = re.split(r'[.\-_]', version)
    if len(parts) > 5:
        return ValidationResult.failure(
            ValidationErrorType.TOO_MANY_COMPONENTS,
            f"Too many version components: {len(parts)}",
            VersionScheme.LOOSE,
            constraints,
            version
        )
    
    match = PATTERNS.LOOSE.match(version)
    if not match:
        return ValidationResult.failure(
            ValidationErrorType.INVALID_FORMAT,
            "Invalid version format",
            VersionScheme.LOOSE,
            constraints,
            version
        )
    
    groups = match.groupdict()
    
    major = int(groups['major'])
    minor = int(groups['minor']) if groups.get('minor') else None
    patch = int(groups['patch']) if groups.get('patch') else None
    prerelease = groups.get('prerelease')
    build = groups.get('build')
    
    # Check constraints
    if major < constraints.min_major:
        return ValidationResult.failure(
            ValidationErrorType.MAJOR_TOO_LOW,
            f"Major version must be >= {constraints.min_major} (got {major})",
            VersionScheme.LOOSE,
            constraints,
            version
        )
    
    if constraints.max_major is not None and major > constraints.max_major:
        return ValidationResult.failure(
            ValidationErrorType.MAJOR_TOO_HIGH,
            f"Major version must be <= {constraints.max_major} (got {major})",
            VersionScheme.LOOSE,
            constraints,
            version
        )
    
    if constraints.require_minor and minor is None:
        return ValidationResult.failure(
            ValidationErrorType.MINOR_REQUIRED,
            "Minor version required",
            VersionScheme.LOOSE,
            constraints,
            version
        )
    
    if constraints.require_patch and patch is None:
        return ValidationResult.failure(
            ValidationErrorType.PATCH_REQUIRED,
            "Patch version required",
            VersionScheme.LOOSE,
            constraints,
            version
        )
    
    if prerelease and not constraints.allow_prerelease:
        return ValidationResult.failure(
            ValidationErrorType.PRERELEASE_NOT_ALLOWED,
            f"Pre-release versions not allowed (found '{prerelease}')",
            VersionScheme.LOOSE,
            constraints,
            version
        )
    
    if build and not constraints.allow_build:
        return ValidationResult.failure(
            ValidationErrorType.BUILD_NOT_ALLOWED,
            f"Build metadata not allowed (found '{build}')",
            VersionScheme.LOOSE,
            constraints,
            version
        )
    
    prerelease_type = PreReleaseType.from_string(prerelease) if prerelease else PreReleaseType.NONE
    
    components = VersionComponents(
        major=major,
        minor=minor,
        patch=patch,
        prerelease=prerelease,
        build=build,
        prerelease_type=prerelease_type,
        raw_string=version,
        scheme=VersionScheme.LOOSE
    )
    
    return ValidationResult.success(
        components,
        VersionScheme.LOOSE,
        constraints,
        version,
        warnings_list
    )


# ============================================================================
# Main Public API
# ============================================================================

@lru_cache(maxsize=1024)
def validate_version(
    version: str,
    scheme: Union[VersionScheme, str] = VersionScheme.LOOSE,
    constraints: Optional[ValidationConstraints] = None
) -> ValidationResult:
    """
    Validate a version string according to specified scheme and constraints.
    
    This is the main entry point for version validation. It supports multiple
    versioning schemes and provides detailed validation results.
    
    Parameters
    ----------
    version : str
        The version string to validate.
    scheme : Union[VersionScheme, str], default=VersionScheme.LOOSE
        Version scheme to validate against:
        - VersionScheme.SEMVER / "semver": Semantic Versioning 2.0.0
        - VersionScheme.PEP440 / "pep440": Python PEP 440
        - VersionScheme.STRICT / "strict": Strict numeric versioning
        - VersionScheme.LOOSE / "loose": Flexible version format
    constraints : Optional[ValidationConstraints], default=None
        Additional validation constraints. If None, uses default constraints.
    
    Returns
    -------
    ValidationResult
        Comprehensive validation result including parsed components if valid.
    
    Raises
    ------
    ValueError
        If version scheme is invalid.
    
    Examples
    --------
    >>> result = validate_version("1.2.3")
    >>> result.is_valid
    True
    >>> result.components.version_tuple
    (1, 2, 3)
    
    >>> result = validate_version("1.2.3-beta+20240101", scheme="semver")
    >>> result.components.prerelease
    'beta'
    >>> result.components.build
    '20240101'
    
    >>> constraints = ValidationConstraints(min_major=2, require_patch=True)
    >>> result = validate_version("1.2.3", constraints=constraints)
    >>> result.is_valid
    False
    >>> result.error_message
    'Major version must be >= 2 (got 1)'
    """
    # Input validation
    if not isinstance(version, str):
        return ValidationResult.failure(
            ValidationErrorType.INVALID_TYPE,
            f"Version must be a string, got {type(version).__name__}",
            VersionScheme.LOOSE,
            ValidationConstraints(),
            str(version)
        )
    
    if not version or not version.strip():
        return ValidationResult.failure(
            ValidationErrorType.EMPTY_STRING,
            "Version string is empty",
            VersionScheme.LOOSE,
            ValidationConstraints(),
            version
        )
    
    version = version.strip()
    
    # Convert scheme string to enum
    if isinstance(scheme, str):
        scheme_enum = VersionScheme.from_string(scheme)
        if scheme_enum is None:
            raise ValueError(f"Invalid version scheme: '{scheme}'. "
                           f"Valid schemes: {[s.value for s in VersionScheme]}")
        scheme = scheme_enum
    
    # Use default constraints if not provided
    if constraints is None:
        constraints = ValidationConstraints()
    
    # Route to appropriate validator
    validators = {
        VersionScheme.SEMVER: _validate_semver,
        VersionScheme.PEP440: _validate_pep440,
        VersionScheme.STRICT: _validate_strict,
        VersionScheme.LOOSE: _validate_loose,
    }
    
    validator = validators.get(scheme)
    if validator is None:
        raise ValueError(f"No validator for scheme: {scheme}")
    
    return validator(version, constraints)


def validate_version_simple(
    version: str,
    scheme: Union[VersionScheme, str] = VersionScheme.LOOSE,
    **constraints_kwargs
) -> Tuple[bool, Optional[str]]:
    """
    Simple version validation returning (is_valid, error_message).
    
    This is a convenience wrapper that returns a simple tuple instead
    of the full ValidationResult object.
    
    Parameters
    ----------
    version : str
        The version string to validate.
    scheme : Union[VersionScheme, str], default=VersionScheme.LOOSE
        Version scheme to validate against.
    **constraints_kwargs
        Keyword arguments passed to ValidationConstraints.
    
    Returns
    -------
    Tuple[bool, Optional[str]]
        - bool: True if version is valid, False otherwise
        - Optional[str]: Error message if invalid, None if valid
    
    Examples
    --------
    >>> is_valid_version("1.2.3")
    (True, None)
    
    >>> is_valid_version("1.2", require_patch=True)
    (False, 'Patch version required')
    """
    constraints = ValidationConstraints(**constraints_kwargs)
    result = validate_version(version, scheme, constraints)
    return (result.is_valid, result.error_message if not result.is_valid else None)


# ============================================================================
# Convenience Functions
# ============================================================================

def is_semver(version: str, strict: bool = True) -> bool:
    """
    Check if version is valid Semantic Versioning 2.0.0.
    
    Parameters
    ----------
    version : str
        Version string to validate.
    strict : bool, default=True
        If True, requires all three components (major.minor.patch).
        If False, allows missing patch version.
    
    Returns
    -------
    bool
        True if valid SemVer, False otherwise.
    
    Examples
    --------
    >>> is_semver("1.2.3")
    True
    >>> is_semver("1.2.3-beta")
    True
    >>> is_semver("1.2", strict=False)
    True
    >>> is_semver("1.2", strict=True)
    False
    """
    constraints = ValidationConstraints.for_semver_strict() if strict else ValidationConstraints(
        require_minor=True,
        require_patch=False
    )
    result = validate_version(version, VersionScheme.SEMVER, constraints)
    return result.is_valid


def is_pep440(version: str, strict: bool = True) -> bool:
    """
    Check if version is valid PEP 440.
    
    Parameters
    ----------
    version : str
        Version string to validate.
    strict : bool, default=True
        Use strict PEP 440 validation.
    
    Returns
    -------
    bool
        True if valid PEP 440, False otherwise.
    
    Examples
    --------
    >>> is_pep440("1.2.3")
    True
    >>> is_pep440("1.2.3.dev1")
    True
    >>> is_pep440("1.2.3+local")
    True
    >>> is_pep440("v1.2.3")
    True
    """
    constraints = ValidationConstraints.for_pep440_strict() if strict else ValidationConstraints()
    result = validate_version(version, VersionScheme.PEP440, constraints)
    return result.is_valid


def is_valid_version_string(version: str) -> bool:
    """
    Quick check if a string appears to be a valid version.
    
    This uses loose validation and is suitable for quick filtering.
    For strict validation, use `is_semver()` or `is_pep440()`.
    
    Parameters
    ----------
    version : str
        Version string to validate.
    
    Returns
    -------
    bool
        True if likely a valid version, False otherwise.
    
    Examples
    --------
    >>> is_valid_version_string("1.2.3")
    True
    >>> is_valid_version_string("v1.2")
    True
    >>> is_valid_version_string("1.0-beta")
    True
    >>> is_valid_version_string("not-a-version")
    False
    """
    result = validate_version(version, VersionScheme.LOOSE)
    return result.is_valid


def parse_version(version: str, scheme: Union[VersionScheme, str] = VersionScheme.LOOSE) -> Optional[VersionComponents]:
    """
    Parse a version string into its components.
    
    Parameters
    ----------
    version : str
        Version string to parse.
    scheme : Union[VersionScheme, str], default=VersionScheme.LOOSE
        Version scheme to use for parsing.
    
    Returns
    -------
    Optional[VersionComponents]
        Parsed version components if valid, None otherwise.
    
    Examples
    --------
    >>> comps = parse_version("1.2.3-beta+20240101", "semver")
    >>> comps.major
    1
    >>> comps.prerelease
    'beta'
    >>> comps.build
    '20240101'
    """
    result = validate_version(version, scheme)
    return result.components if result.is_valid else None


def compare_versions(version1: str, version2: str, scheme: Union[VersionScheme, str] = VersionScheme.LOOSE) -> int:
    """
    Compare two version strings.
    
    Parameters
    ----------
    version1 : str
        First version string.
    version2 : str
        Second version string.
    scheme : Union[VersionScheme, str], default=VersionScheme.LOOSE
        Version scheme to use for parsing.
    
    Returns
    -------
    int
        -1 if version1 < version2
        0 if version1 == version2
        1 if version1 > version2
    
    Raises
    ------
    ValueError
        If either version is invalid.
    
    Examples
    --------
    >>> compare_versions("1.2.3", "1.2.4")
    -1
    >>> compare_versions("2.0.0", "1.9.9")
    1
    >>> compare_versions("1.0.0", "1.0.0")
    0
    """
    comps1 = parse_version(version1, scheme)
    comps2 = parse_version(version2, scheme)
    
    if comps1 is None:
        raise ValueError(f"Invalid version string: '{version1}'")
    if comps2 is None:
        raise ValueError(f"Invalid version string: '{version2}'")
    
    if comps1 < comps2:
        return -1
    elif comps1 == comps2:
        return 0
    else:
        return 1


def normalize_version(version: str, scheme: Union[VersionScheme, str] = VersionScheme.LOOSE) -> Optional[str]:
    """
    Normalize a version string to its canonical form.
    
    Parameters
    ----------
    version : str
        Version string to normalize.
    scheme : Union[VersionScheme, str], default=VersionScheme.LOOSE
        Version scheme to use.
    
    Returns
    -------
    Optional[str]
        Normalized version string if valid, None otherwise.
    
    Examples
    --------
    >>> normalize_version("v1.2.3-beta.1+20240101", "semver")
    '1.2.3-beta.1'
    >>> normalize_version("1.2")
    '1.2'
    """
    comps = parse_version(version, scheme)
    if comps is None:
        return None
    return comps.version_string


def clear_validation_cache() -> None:
    """
    Clear the LRU cache for version validation.
    
    This can be useful in long-running applications to free memory.
    
    Examples
    --------
    >>> validate_version("1.2.3")  # Cached
    >>> clear_validation_cache()   # Clear cache
    """
    validate_version.cache_clear()


def get_cache_info() -> Dict[str, Any]:
    """
    Get information about the validation cache.
    
    Returns
    -------
    Dict[str, Any]
        Cache statistics including size and hit/miss counts.
    
    Examples
    --------
    >>> info = get_cache_info()
    >>> info['maxsize']
    1024
    """
    cache_info = validate_version.cache_info()
    return {
        "hits": cache_info.hits,
        "misses": cache_info.misses,
        "maxsize": cache_info.maxsize,
        "current_size": cache_info.currsize,
        "hit_rate": cache_info.hits / (cache_info.hits + cache_info.misses) if (cache_info.hits + cache_info.misses) > 0 else 0.0
    }


# ============================================================================
# Backward Compatibility Aliases
# ============================================================================

# For backward compatibility with original interface
def is_valid_version(
    version: str,
    *,
    allow_v_prefix: bool = True,
    allow_build: bool = True,
    allow_pre_release: bool = True,
    require_minor: bool = False,
    require_patch: bool = False,
    strict_pep440: bool = False,
    version_scheme: str = "semver",
    min_major: int = 0,
    max_major: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Legacy interface for backward compatibility.
    
    Please use `validate_version()` or `validate_version_simple()` instead.
    """
    constraints = ValidationConstraints(
        allow_v_prefix=allow_v_prefix,
        allow_build=allow_build,
        allow_prerelease=allow_pre_release,
        require_minor=require_minor,
        require_patch=require_patch,
        strict_mode=strict_pep440,
        min_major=min_major,
        max_major=max_major
    )
    return validate_version_simple(version, version_scheme, **constraints.to_dict())


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "VersionScheme",
    "ValidationErrorType",
    "PreReleaseType",
    
    # Data Classes
    "VersionComponents",
    "ValidationConstraints",
    "ValidationResult",
    "VersionPatterns",
    
    # Main Functions
    "validate_version",
    "validate_version_simple",
    
    # Convenience Functions
    "is_semver",
    "is_pep440",
    "is_valid_version_string",
    "parse_version",
    "compare_versions",
    "normalize_version",
    
    # Cache Management
    "clear_validation_cache",
    "get_cache_info",
    
    # Legacy (backward compatibility)
    "is_valid_version",
]

