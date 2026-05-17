#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Python Version Management Suite - Comprehensive Version Handling Library
========================================================================

A unified, feature-rich version management library that combines version
validation, parsing, comparison, and extraction capabilities into a single,
cohesive module. This library provides everything needed for working with
Python package versions, environment markers, and version tags.

This module integrates and re-exports ALL functionality from three core components:
- version_validator: Version string validation
- version_type: Rich version objects and comparison
- version_parser: Extract versions from files, packages, and environments

Features
--------
- **Version Validation**: Validate against SemVer, PEP 440, strict, and loose formats
- **Version Comparison**: Full comparison support with PEP 440 semantics
- **Version Parsing**: Extract versions from source files, configs, and installed packages
- **Version Bumping**: Increment major, minor, or patch components
- **Version Ranges**: Parse and check version constraints
- **Environment Tags**: Generate PEP 425/600/656 compatibility tags
- **Cross-Platform**: Full support for Windows, Linux, macOS, and BSD
- **Thread-Safe**: LRU caching for optimal performance

Quick Start
-----------
>>> from version import Version, parse_version, validate_version
>>> 
>>> # Create and compare versions
>>> v1 = Version(1, 2, 3)
>>> v2 = Version(1, 3, 0)
>>> v1 < v2
True
>>> 
>>> # Parse version strings
>>> v = parse_version("1.2.3-beta+20240101")
>>> print(v.major, v.minor, v.patch, v.prerelease)
1 2 3 beta
>>> 
>>> # Validate versions
>>> is_valid, error = validate_version("2.0.0", scheme="semver")
>>> print(f"Valid: {is_valid}")
Valid: True
>>> 
>>> # Extract versions from packages
>>> from version import get_version_info
>>> version = get_version_info("requests")
>>> if version:
...     print(f"requests {version.version}")

Module Structure
----------------
This module re-exports everything from:
- version_validator: Version string validation
- version_type: Rich version objects and comparison
- version_parser: Version extraction from various sources

References
----------
- PEP 440: https://www.python.org/dev/peps/pep-0440/
- Semantic Versioning: https://semver.org/
- PEP 425: https://www.python.org/dev/peps/pep-0425/
- PEP 600: https://www.python.org/dev/peps/pep-0600/
"""

import sys
from pathlib import Path
from typing import (
    Dict, List, Optional, Union, Tuple, Any, Set,
    Iterator, Callable, TypeVar, overload
)

# ============================================================================
# Import ALL from Version Validator
# ============================================================================

from ._utils._version_validator import (
    # === Enums ===
    VersionScheme,
    ValidationErrorType,
    PreReleaseType,
    
    # === Data Classes ===
    VersionComponents,
    ValidationConstraints,
    ValidationResult,
    VersionPatterns as ValidatorPatterns,
    
    # === Main Functions ===
    validate_version,
    validate_version_simple,
    
    # === Convenience Functions ===
    is_semver,
    is_pep440,
    is_valid_version_string,
    parse_version as parse_version_validator,
    compare_versions as compare_versions_validator,
    normalize_version,
    
    # === Cache Management ===
    clear_validation_cache,
    get_cache_info as get_validator_cache_info,
)

# Also import internal validation functions 
from ._utils._version_validator import (
    _validate_semver,
    _validate_pep440,
    _validate_strict,
    _validate_loose,
    _strip_v_prefix,
)

# ============================================================================
# Import ALL from Version Type
# ============================================================================

from ._utils._version_utils import (
    # === Enums ===
    ReleaseType,
    VersionFormat,
    BumpType,
    RangeOperator,
    
    # === Data Classes ===
    PrereleaseInfo,
    VersionConstraint,
    VersionRange,
    VersionPatterns as TypePatterns,
    
    # === Main Classes ===
    Version,
    VersionType,  # Alias for backward compatibility
    
    # === Parsing Functions ===
    parse_version,
    parse_version_with_format,
    version_parse,  # Legacy
    
    # === Comparison Functions ===
    compare_versions,
    version_compare,  # Legacy
    check_compatibility,
    is_compatible,  # Legacy
    
    # === Range Functions ===
    parse_version_range,
    
    # === Utility Functions ===
    get_highest_version,
    get_lowest_version,
    sort_versions,
    filter_stable,
    filter_prerelease,
    
    # === Cache Management ===
    clear_parse_cache,
    get_parse_cache_info,
)

# Also import internal type functions 
from ._utils._version_utils import (
    _PRECEDENCE_MAP,
    _RELEASE_TYPE_MAP,
)

# ============================================================================
# Import ALL from Version Parser
# ============================================================================

from ._utils._version_parser import (
    # === Enums ===
    VersionSource,
    ParseErrorType,
    ProjectFormat,
    RequirementOperator,
    
    # === Data Classes ===
    ParseError,
    ModuleVersion,
    ParseResult,
    VersionPatterns as ParserPatterns,
    
    # === Main Class ===
    VersionParser,
    
    # === Exception ===
    VersionParserError,
    
    # === Convenience Functions ===
    get_version_info,
    get_all_versions,
    get_installed_versions,
    clear_global_cache,
)

# Also import internal parser components 
from ._utils._version_parser import (
    VersionVisitor,
    _DEFAULT_ENCODING,
    _FALLBACK_ENCODINGS,
    _IS_WINDOWS,
    _IS_MACOS,
    _IS_LINUX,
    _IS_BSD,
    _PYTHON_VERSION,
    _PYTHON_311_PLUS,
    _PYTHON_38_PLUS,
)

# ============================================================================
# Additional Utility Functions
# ============================================================================

def get_version(value: Union[str, Version, ModuleVersion]) -> Optional[Version]:
    """
    Convert various version representations to a Version object.
    
    This utility function accepts strings, Version objects, or ModuleVersion
    objects and returns a normalized Version object.
    
    Parameters
    ----------
    value : Union[str, Version, ModuleVersion]
        The version value to convert.
    
    Returns
    -------
    Optional[Version]
        Version object if conversion succeeds, None otherwise.
    
    Examples
    --------
    >>> get_version("1.2.3")
    Version(1, 2, 3)
    
    >>> v = Version(2, 0, 0)
    >>> get_version(v) is v
    True
    
    >>> from version import ModuleVersion, VersionSource
    >>> mv = ModuleVersion("pkg", "1.0.0", VersionSource.CUSTOM)
    >>> get_version(mv)
    Version(1, 0, 0)
    """
    if isinstance(value, Version):
        return value
    elif isinstance(value, ModuleVersion):
        return parse_version(value.version)
    elif isinstance(value, str):
        return parse_version(value)
    return None


def version_to_string(value: Union[str, Version, ModuleVersion]) -> str:
    """
    Convert various version representations to a normalized string.
    
    Parameters
    ----------
    value : Union[str, Version, ModuleVersion]
        The version value to convert.
    
    Returns
    -------
    str
        Normalized version string.
    
    Examples
    --------
    >>> version_to_string(Version(1, 2, 3, prerelease="beta"))
    '1.2.3-beta'
    
    >>> version_to_string("v1.2.3")
    '1.2.3'
    
    >>> from version import ModuleVersion, VersionSource
    >>> mv = ModuleVersion("pkg", "1.0.0", VersionSource.CUSTOM)
    >>> version_to_string(mv)
    '1.0.0'
    """
    if isinstance(value, Version):
        return str(value)
    elif isinstance(value, ModuleVersion):
        v = parse_version(value.version)
        return str(v) if v else value.version
    elif isinstance(value, str):
        v = parse_version(value)
        return str(v) if v else value
    return str(value)


def version_to_tuple(value: Union[str, Version, ModuleVersion]) -> Tuple[int, ...]:
    """
    Convert version to tuple of integers.
    
    Parameters
    ----------
    value : Union[str, Version, ModuleVersion]
        The version value to convert.
    
    Returns
    -------
    Tuple[int, ...]
        Version components as integers (major, minor, patch).
    
    Examples
    --------
    >>> version_to_tuple("1.2.3")
    (1, 2, 3)
    
    >>> version_to_tuple(Version(2, 0, 0))
    (2, 0, 0)
    """
    v = get_version(value)
    if v:
        return v.version_tuple
    return ()


def satisfies_requirement(
    version: Union[str, Version, ModuleVersion],
    requirement: str
) -> bool:
    """
    Check if a version satisfies a requirement string.
    
    This is a convenience wrapper that handles all version types.
    
    Parameters
    ----------
    version : Union[str, Version, ModuleVersion]
        Version to check.
    requirement : str
        Requirement string (e.g., ">=1.0.0", "~=2.0", "==1.2.3").
    
    Returns
    -------
    bool
        True if version satisfies requirement.
    
    Examples
    --------
    >>> satisfies_requirement("1.2.3", ">=1.0.0")
    True
    
    >>> satisfies_requirement("2.0.0", "~=1.5")
    False
    
    >>> satisfies_requirement("1.5.0", ">=1.5.0,<2.0.0")
    True
    """
    version_str = version_to_string(version)
    return check_compatibility(version_str, requirement)


def get_latest_version(versions: List[Union[str, Version, ModuleVersion]]) -> Optional[Version]:
    """
    Get the latest (highest) version from a list.
    
    Parameters
    ----------
    versions : List[Union[str, Version, ModuleVersion]]
        List of versions.
    
    Returns
    -------
    Optional[Version]
        Latest version, or None if list is empty.
    
    Examples
    --------
    >>> get_latest_version(["1.0.0", "2.0.0", "1.5.0"])
    Version(2, 0, 0)
    
    >>> get_latest_version(["1.0.0-beta", "1.0.0", "1.0.0-alpha"])
    Version(1, 0, 0)
    """
    parsed = []
    for v in versions:
        p = get_version(v)
        if p:
            parsed.append(p)
    return max(parsed) if parsed else None


def get_earliest_version(versions: List[Union[str, Version, ModuleVersion]]) -> Optional[Version]:
    """
    Get the earliest (lowest) version from a list.
    
    Parameters
    ----------
    versions : List[Union[str, Version, ModuleVersion]]
        List of versions.
    
    Returns
    -------
    Optional[Version]
        Earliest version, or None if list is empty.
    
    Examples
    --------
    >>> get_earliest_version(["1.0.0", "2.0.0", "1.5.0"])
    Version(1, 0, 0)
    """
    parsed = []
    for v in versions:
        p = get_version(v)
        if p:
            parsed.append(p)
    return min(parsed) if parsed else None


def detect_project_version(project_path: Union[str, Path] = ".") -> Optional[ModuleVersion]:
    """
    Detect the main version of a project from its configuration files.
    
    This function scans common project files to find the primary version.
    
    Parameters
    ----------
    project_path : Union[str, Path], default="."
        Path to the project directory.
    
    Returns
    -------
    Optional[ModuleVersion]
        Detected version with metadata, or None if not found.
    
    Examples
    --------
    >>> version = detect_project_version(".")
    >>> if version:
    ...     print(f"Project version: {version.version}")
    ...     print(f"Source: {version.source.value}")
    """
    parser = VersionParser()
    result = parser.parse_directory(project_path, recursive=False)
    
    # Get unique versions sorted by confidence
    unique = result.get_unique_versions()
    if unique:
        # Return highest confidence version
        return max(unique, key=lambda v: v.confidence)
    return None


def detect_package_versions(project_path: Union[str, Path] = ".") -> Dict[str, str]:
    """
    Detect all package versions referenced in a project.
    
    This includes the project's own version and all dependencies.
    
    Parameters
    ----------
    project_path : Union[str, Path], default="."
        Path to the project directory.
    
    Returns
    -------
    Dict[str, str]
        Dictionary mapping package names to versions.
    
    Examples
    --------
    >>> versions = detect_package_versions(".")
    >>> for name, version in versions.items():
    ...     print(f"{name}: {version}")
    """
    parser = VersionParser()
    result = parser.parse_directory(project_path)
    unique = result.get_unique_versions()
    return {v.name: v.version for v in unique}


class VersionInfo:
    """
    Comprehensive version information container.
    
    This class provides a unified interface for working with version
    information from various sources.
    
    Parameters
    ----------
    value : Union[str, Version, ModuleVersion]
        The version value.
    
    Attributes
    ----------
    raw : Union[str, Version, ModuleVersion]
        Original raw value.
    version : Optional[Version]
        Parsed Version object.
    string : str
        Normalized string representation.
    tuple : Tuple[int, ...]
        Version tuple (major, minor, patch).
    is_valid : bool
        Whether the version is valid.
    is_stable : bool
        Whether it's a stable release.
    is_prerelease : bool
        Whether it's a pre-release.
    
    Examples
    --------
    >>> info = VersionInfo("1.2.3-beta+20240101")
    >>> info.major
    1
    >>> info.is_prerelease
    True
    >>> info.string
    '1.2.3-beta'
    
    >>> info = VersionInfo(Version(2, 0, 0))
    >>> info.is_stable
    True
    """
    
    __slots__ = ("raw", "version", "_string", "_tuple")
    
    def __init__(self, value: Union[str, Version, ModuleVersion]):
        self.raw = value
        self.version = get_version(value)
        self._string: Optional[str] = None
        self._tuple: Optional[Tuple[int, ...]] = None
    
    @property
    def string(self) -> str:
        """Normalized string representation."""
        if self._string is None:
            self._string = version_to_string(self.raw)
        return self._string
    
    @property
    def tuple(self) -> Tuple[int, ...]:
        """Version tuple (major, minor, patch)."""
        if self._tuple is None:
            self._tuple = version_to_tuple(self.raw)
        return self._tuple
    
    @property
    def major(self) -> int:
        """Major version number."""
        return self.version.major if self.version else 0
    
    @property
    def minor(self) -> int:
        """Minor version number."""
        return self.version.minor if self.version else 0
    
    @property
    def patch(self) -> int:
        """Patch version number."""
        return self.version.patch if self.version else 0
    
    @property
    def prerelease(self) -> Optional[str]:
        """Pre-release identifier."""
        return self.version.prerelease if self.version else None
    
    @property
    def build(self) -> Optional[str]:
        """Build metadata."""
        return self.version.build if self.version else None
    
    @property
    def epoch(self) -> int:
        """Epoch number."""
        return self.version.epoch if self.version else 0
    
    @property
    def is_valid(self) -> bool:
        """Whether the version is valid."""
        return self.version is not None
    
    @property
    def is_stable(self) -> bool:
        """Whether it's a stable release."""
        return self.version.is_stable() if self.version else False
    
    @property
    def is_prerelease(self) -> bool:
        """Whether it's a pre-release."""
        return self.version.is_prerelease() if self.version else False
    
    @property
    def is_postrelease(self) -> bool:
        """Whether it's a post-release."""
        return self.version.is_postrelease() if self.version else False
    
    @property
    def is_development(self) -> bool:
        """Whether it's a development release."""
        return self.version.is_development() if self.version else False
    
    @property
    def release_type(self) -> Optional[ReleaseType]:
        """Release type."""
        return self.version.release_type if self.version else None
    
    def satisfies(self, requirement: str) -> bool:
        """
        Check if version satisfies a requirement.
        
        Parameters
        ----------
        requirement : str
            Requirement string.
        
        Returns
        -------
        bool
            True if satisfied.
        """
        return satisfies_requirement(self.raw, requirement)
    
    def bump(self, part: str = "patch") -> Optional['VersionInfo']:
        """
        Create a new VersionInfo with incremented version.
        
        Parameters
        ----------
        part : {'major', 'minor', 'patch'}, default='patch'
            Which part to increment.
        
        Returns
        -------
        Optional[VersionInfo]
            New VersionInfo with bumped version.
        """
        if self.version:
            return VersionInfo(self.version.bump(part))
        return None
    
    def next_major(self) -> Optional['VersionInfo']:
        """Get next major version."""
        if self.version:
            return VersionInfo(self.version.next_major())
        return None
    
    def next_minor(self) -> Optional['VersionInfo']:
        """Get next minor version."""
        if self.version:
            return VersionInfo(self.version.next_minor())
        return None
    
    def next_patch(self) -> Optional['VersionInfo']:
        """Get next patch version."""
        if self.version:
            return VersionInfo(self.version.next_patch())
        return None
    
    def compatible_with(self, other: Union[str, 'VersionInfo', Version]) -> bool:
        """
        Check if versions are compatible (same major version).
        
        Parameters
        ----------
        other : Union[str, VersionInfo, Version]
            Other version to compare with.
        
        Returns
        -------
        bool
            True if compatible.
        """
        if not self.version:
            return False
        
        if isinstance(other, VersionInfo):
            other_v = other.version
        elif isinstance(other, Version):
            other_v = other
        else:
            other_v = get_version(other)
        
        return self.version.compatible_with(other_v) if other_v else False
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary representation.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with version information.
        """
        return {
            "string": self.string,
            "tuple": list(self.tuple),
            "major": self.major,
            "minor": self.minor,
            "patch": self.patch,
            "prerelease": self.prerelease,
            "build": self.build,
            "epoch": self.epoch,
            "is_valid": self.is_valid,
            "is_stable": self.is_stable,
            "is_prerelease": self.is_prerelease,
            "is_postrelease": self.is_postrelease,
            "is_development": self.is_development,
            "release_type": str(self.release_type) if self.release_type else None,
        }
    
    def __str__(self) -> str:
        return self.string
    
    def __repr__(self) -> str:
        return f"VersionInfo({self.string!r})"
    
    def __eq__(self, other: Any) -> bool:
        if isinstance(other, VersionInfo):
            return self.version == other.version
        return self.version == get_version(other)
    
    def __lt__(self, other: Any) -> bool:
        if isinstance(other, VersionInfo):
            return self.version < other.version if self.version else False
        v = get_version(other)
        return self.version < v if self.version and v else False
    
    def __le__(self, other: Any) -> bool:
        if isinstance(other, VersionInfo):
            return self.version <= other.version if self.version else False
        v = get_version(other)
        return self.version <= v if self.version and v else False
    
    def __gt__(self, other: Any) -> bool:
        if isinstance(other, VersionInfo):
            return self.version > other.version if self.version else False
        v = get_version(other)
        return self.version > v if self.version and v else False
    
    def __ge__(self, other: Any) -> bool:
        if isinstance(other, VersionInfo):
            return self.version >= other.version if self.version else False
        v = get_version(other)
        return self.version >= v if self.version and v else False
    
    def __hash__(self) -> int:
        return hash(self.version) if self.version else hash(self.string)


# ============================================================================
# Cache Management
# ============================================================================

def clear_all_caches() -> None:
    """
    Clear all caches across all version modules.
    
    This function clears:
    - Validation cache (version_validator)
    - Parse cache (version_type)
    - Parser cache (version_parser)
    
    Examples
    --------
    >>> clear_all_caches()
    """
    clear_validation_cache()
    clear_parse_cache()
    clear_global_cache()


def get_all_cache_info() -> Dict[str, Any]:
    """
    Get cache information from all modules.
    
    Returns
    -------
    Dict[str, Any]
        Combined cache statistics.
    
    Examples
    --------
    >>> info = get_all_cache_info()
    >>> print(f"Validation cache: {info['validation']['size']}")
    >>> print(f"Parse cache: {info['parse']['size']}")
    """
    result = {
        "validation": get_validator_cache_info(),
        "parse": get_parse_cache_info(),
    }
    
    # Try to get parser stats if global parser exists
    try:
        from ._utils._version_parser import _global_parser
        if _global_parser:
            result["parser"] = _global_parser.get_stats()
    except (ImportError, AttributeError):
        result["parser"] = {}
    
    return result


def get_available_functions() -> Dict[str, List[str]]:
    """
    Get lists of all available functions grouped by category.
    
    Returns
    -------
    Dict[str, List[str]]
        Categorized function names.
    """
    return {
        "validation": [
            "validate_version", "validate_version_simple",
            "is_semver", "is_pep440", "is_valid_version_string",
            "normalize_version"
        ],
        "parsing": [
            "parse_version", "parse_version_with_format", "version_parse",
            "parse_version_range"
        ],
        "comparison": [
            "compare_versions", "version_compare", "check_compatibility",
            "is_compatible", "satisfies_requirement"
        ],
        "extraction": [
            "get_version_info", "get_all_versions", "get_installed_versions",
            "detect_project_version", "detect_package_versions"
        ],
        "utility": [
            "get_version", "version_to_string", "version_to_tuple",
            "get_latest_version", "get_earliest_version",
            "get_highest_version", "get_lowest_version",
            "sort_versions", "filter_stable", "filter_prerelease"
        ],
        "cache": [
            "clear_all_caches", "get_all_cache_info",
            "clear_validation_cache", "clear_parse_cache", "clear_global_cache"
        ],
        "classes": [
            "Version", "VersionType", "VersionRange", "VersionInfo",
            "VersionParser", "ModuleVersion", "ParseResult"
        ],
        "enums": [
            "VersionScheme", "ReleaseType", "VersionSource", "VersionFormat",
            "BumpType", "RangeOperator", "ProjectFormat", "RequirementOperator"
        ],
    }


# ============================================================================
# Module Exports - EVERYTHING
# ============================================================================

__all__ = [
    # ===== Version Validator - Enums =====
    "VersionScheme",
    "ValidationErrorType",
    "PreReleaseType",
    
    # ===== Version Validator - Data Classes =====
    "VersionComponents",
    "ValidationConstraints",
    "ValidationResult",
    "ValidatorPatterns",
    
    # ===== Version Validator - Functions =====
    "validate_version",
    "validate_version_simple",
    "is_semver",
    "is_pep440",
    "is_valid_version_string",
    "parse_version_validator",
    "compare_versions_validator",
    "normalize_version",
    "clear_validation_cache",
    "get_validator_cache_info",
    
    # ===== Version Validator - Internal =====
    "_validate_semver",
    "_validate_pep440",
    "_validate_strict",
    "_validate_loose",
    "_strip_v_prefix",
    
    # ===== Version Type - Enums =====
    "ReleaseType",
    "VersionFormat",
    "BumpType",
    "RangeOperator",
    
    # ===== Version Type - Data Classes =====
    "PrereleaseInfo",
    "VersionConstraint",
    "VersionRange",
    "TypePatterns",
    
    # ===== Version Type - Classes =====
    "Version",
    "VersionType",  # Alias for backward compatibility
    
    # ===== Version Type - Functions =====
    "parse_version",
    "parse_version_with_format",
    "version_parse",
    "compare_versions",
    "version_compare",
    "check_compatibility",
    "is_compatible",
    "parse_version_range",
    "get_highest_version",
    "get_lowest_version",
    "sort_versions",
    "filter_stable",
    "filter_prerelease",
    "clear_parse_cache",
    "get_parse_cache_info",
    
    # ===== Version Type - Internal =====
    "_PRECEDENCE_MAP",
    "_RELEASE_TYPE_MAP",
    
    # ===== Version Parser - Enums =====
    "VersionSource",
    "ParseErrorType",
    "ProjectFormat",
    "RequirementOperator",
    
    # ===== Version Parser - Data Classes =====
    "ParseError",
    "ModuleVersion",
    "ParseResult",
    "ParserPatterns",
    
    # ===== Version Parser - Classes =====
    "VersionParser",
    "VersionVisitor",
    
    # ===== Version Parser - Exception =====
    "VersionParserError",
    
    # ===== Version Parser - Functions =====
    "get_version_info",
    "get_all_versions",
    "get_installed_versions",
    "clear_global_cache",
    
    # ===== Version Parser - Constants =====
    "_DEFAULT_ENCODING",
    "_FALLBACK_ENCODINGS",
    "_IS_WINDOWS",
    "_IS_MACOS",
    "_IS_LINUX",
    "_IS_BSD",
    "_PYTHON_VERSION",
    "_PYTHON_311_PLUS",
    "_PYTHON_38_PLUS",
    
    # ===== Utility Functions =====
    "get_version",
    "version_to_string",
    "version_to_tuple",
    "satisfies_requirement",
    "get_latest_version",
    "get_earliest_version",
    "detect_project_version",
    "detect_package_versions",
    
    # ===== VersionInfo Class =====
    "VersionInfo",
    
    # ===== Cache Management =====
    "clear_all_caches",
    "get_all_cache_info",
    
    # ===== Module Info =====
    "get_available_functions",
]


# ============================================================================
# Backward Compatibility Aliases
# ============================================================================

# Aliases for backward compatibility with older code
parse = parse_version
validate = validate_version
compare = compare_versions
is_compatible_version = check_compatibility

# Version class aliases
PEP440Version = Version
SemVer = Version
VersionObject = Version

# Parser aliases
Parser = VersionParser
ModuleInfo = ModuleVersion
ParserResult = ParseResult


# ============================================================================
# Interactive Help
# ============================================================================

def help():
    """
    Display interactive help for the version module.
    
    Examples
    --------
    >>> help()
    """
    print(__doc__)
    print("\n" + "=" * 80)
    print("QUICK REFERENCE")
    print("=" * 80)
    print("""
Version Creation:
    v = Version(1, 2, 3)                    # Major, minor, patch
    v = Version(1, 0, 0, prerelease="beta") # With pre-release
    v = parse_version("1.2.3-beta+20240101")# From string

Version Validation:
    is_valid, error = validate_version("1.2.3", scheme="semver")
    is_semver("1.2.3")                      # True
    is_pep440("1.2.3.dev1")                 # True

Version Comparison:
    v1 < v2                                 # Rich comparison
    compare_versions("1.2.3", "1.2.0")      # Returns 1 (greater)
    
Version Ranges:
    req = VersionRange(">=1.2.3,<2.0.0")
    req.contains("1.5.0")                   # True
    check_compatibility("1.5.0", ">=1.2.3") # True

Version Extraction:
    info = get_version_info("requests")     # From installed package
    versions = get_all_versions(".")        # From project directory
    parser = VersionParser()
    result = parser.parse_directory(".")    # Full parsing result

Version Bumping:
    v = Version(1, 2, 3)
    v2 = v.bump("minor")                    # Version(1, 3, 0)
    v3 = v.next_major()                     # Version(2, 0, 0)

Utility Functions:
    latest = get_latest_version(["1.0.0", "2.0.0", "1.5.0"])
    info = VersionInfo("1.2.3-beta")
    print(info.major, info.is_prerelease)   # 1, True
    
Cache Management:
    clear_all_caches()                      # Clear all caches
    info = get_all_cache_info()             # Get cache statistics
    """)


if __name__ == "__main__":
    help()