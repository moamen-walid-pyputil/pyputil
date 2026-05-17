#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Version detection utilities for Python packages.

This module provides robust version detection for Python packages using
multiple resolution strategies and fallback mechanisms.
"""

import importlib
import re
from types import ModuleType
from typing import Optional, Union, List, Tuple, Any
from importlib import metadata as importlib_metadata
from functools import lru_cache
import logging

from ..path.pathmodkit.metafile import getmetafilepkg
from ..path.utils import load

logger = logging.getLogger(__name__)


# Type aliases
VersionTarget = Union[str, ModuleType]
VersionResult = str


class VersionNotFoundError(Exception):
    """Raised when a package version cannot be determined."""
    pass


def version(
    target: VersionTarget,
    *,
    strict: bool = False,
    fallback_to_metadata: bool = True
) -> VersionResult:
    """
    Determine the version string of a Python package or module.

    This function attempts to find version information using multiple strategies
    in the following order:
    
    1. Distribution metadata via importlib.metadata (most reliable)
    2. Module attributes (__version__, VERSION)
    3. Nested version containers (__about__, version, etc.)
    4. Raw metadata file parsing
    5. Heuristics from module __file__ path

    Parameters
    ----------
    target : str or ModuleType
        The name of an installed package/module, or an already imported
        module object.
    strict : bool, optional
        If True, raises VersionNotFoundError when version cannot be
        determined. If False, returns empty string. Default is False.
    fallback_to_metadata : bool, optional
        Whether to attempt parsing the raw METADATA file as a fallback.
        Default is True.

    Returns
    -------
    str
        The resolved version string. Returns empty string if version cannot
        be determined and strict=False.

    Raises
    ------
    TypeError
        If target is neither a string nor a module object.
    VersionNotFoundError
        If strict=True and version cannot be determined.

    Examples
    --------
    >>> version("requests")
    '2.31.0'

    >>> import importlib
    >>> version(importlib)
    ''

    >>> version("nonexistent_package")
    ''

    >>> version("requests", strict=True)
    '2.31.0'

    >>> version("unknown_package", strict=True)
    Traceback (most recent call last):
        ...
    VersionNotFoundError: Could not determine version for 'unknown_package'
    """
    if not isinstance(target, (str, ModuleType)):
        raise TypeError(
            f"Expected str or module, got <{type(target).__name__}>"
        )
    
    # Normalize and process
    module_name, module = _normalize_target(target)
    
    # Try to get version
    version_str = _resolve_version(
        module_name, module, fallback_to_metadata
    )
    
    if version_str:
        return version_str
    
    if strict:
        raise VersionNotFoundError(
            f"Could not determine version for '{module_name}'. "
            f"Tried: distribution metadata, module attributes, "
            f"nested containers, and metadata file."
        )
    
    return ""


def get_package_version(
    package_name: str,
    *,
    use_cached: bool = True
) -> Optional[str]:
    """
    Get package version using importlib.metadata with caching.

    This is a convenience wrapper around importlib.metadata.version with
    caching for performance.

    Parameters
    ----------
    package_name : str
        The name of the installed package.
    use_cached : bool, optional
        Whether to use cached results. Default is True.

    Returns
    -------
    Optional[str]
        Package version if found, None otherwise.

    Examples
    --------
    >>> get_package_version("requests")
    '2.31.0'

    >>> get_package_version("nonexistent")
    None
    """
    if use_cached:
        return _get_cached_package_version(package_name)
    
    try:
        return importlib_metadata.version(package_name)
    except (importlib_metadata.PackageNotFoundError, ValueError):
        return None


def get_module_version(module: ModuleType) -> Optional[str]:
    """
    Extract version from a module's attributes.

    Parameters
    ----------
    module : ModuleType
        The imported module to inspect.

    Returns
    -------
    Optional[str]
        Version string if found in module attributes, None otherwise.

    Examples
    --------
    >>> import requests
    >>> get_module_version(requests)
    '2.31.0'

    >>> import sys
    >>> get_module_version(sys)
    None
    """
    # Try common version attributes
    for attr in ("__version__", "VERSION", "version"):
        value = getattr(module, attr, None)
        if isinstance(value, str) and value:
            return value
    
    # Try nested version objects
    nested_paths = [
        ("__about__", "__version__"),
        ("about", "__version__"),
        ("__info__", "__version__"),
        ("_version",),
        ("version",),
        ("__version_info__",),
    ]
    
    for path in nested_paths:
        try:
            obj = module
            for key in path:
                obj = getattr(obj, key)
            if isinstance(obj, str) and obj:
                return obj
            elif isinstance(obj, (tuple, list)) and obj:
                # Convert version_info tuple to string
                return ".".join(str(part) for part in obj)
        except (AttributeError, TypeError):
            continue
    
    return None


def parse_metadata_version(metadata_content: str) -> Optional[str]:
    """
    Parse version from METADATA file content.

    Parameters
    ----------
    metadata_content : str
        The raw content of a METADATA file.

    Returns
    -------
    Optional[str]
        Version string if found, None otherwise.

    Examples
    --------
    >>> metadata = "Metadata-Version: 2.1\\nName: requests\\nVersion: 2.31.0"
    >>> parse_metadata_version(metadata)
    '2.31.0'
    """
    if not metadata_content:
        return None
    
    # Pattern for version line (handles different formats)
    patterns = [
        r'^Version:\s*(.+)$',
        r'^version:\s*(.+)$',
        r'^VERSION:\s*(.+)$',
    ]
    
    for line in metadata_content.splitlines():
        for pattern in patterns:
            match = re.match(pattern, line.strip())
            if match:
                version_str = match.group(1).strip()
                # Remove any trailing comments or extras
                version_str = re.sub(r'\s*[;#].*$', '', version_str)
                return version_str
    
    return None


def has_metadata(package_name: str) -> bool:
    """
    Check whether a package has METADATA information.

    Parameters
    ----------
    package_name : str
        The name of the package to check.

    Returns
    -------
    bool
        True if metadata exists, False otherwise.

    Examples
    --------
    >>> has_metadata("requests")
    True

    >>> has_metadata("nonexistent")
    False
    """
    try:
        return getmetafilepkg(package_name) is not None
    except Exception:
        return False


def show_metadata(
    package_name: str,
    *,
    as_text: bool = False,
    pretty: bool = True
) -> Optional[str]:
    """
    Display or return the metadata content for a package.

    Parameters
    ----------
    package_name : str
        The name of the package to inspect.
    as_text : bool, optional
        If True, returns content as string. If False, prints to stdout.
        Default is False.
    pretty : bool, optional
        If True, formats output with sections and highlights.
        Only used when as_text=False. Default is True.

    Returns
    -------
    Optional[str]
        Metadata content as string if as_text=True, otherwise None.

    Raises
    ------
    FileNotFoundError
        If metadata file cannot be found.

    Examples
    --------
    >>> show_metadata("requests")  # prints formatted output
    >>> content = show_metadata("requests", as_text=True)
    """
    metadata_path = getmetafilepkg(package_name)
    if not metadata_path:
        raise FileNotFoundError(
            f"No metadata found for package '{package_name}'"
        )
    
    metadata_content = load(metadata_path)
    
    if as_text:
        return metadata_content
    
    if pretty:
        _print_pretty_metadata(metadata_content, package_name)
    else:
        print(metadata_content)
    
    return None


def get_all_package_versions() -> dict:
    """
    Get versions of all installed packages.

    Returns
    -------
    dict
        Dictionary mapping package names to their versions.

    Examples
    --------
    >>> versions = get_all_package_versions()
    >>> versions.get("requests")
    '2.31.0'
    """
    versions = {}
    
    try:
        for dist in importlib_metadata.distributions():
            try:
                versions[dist.metadata["Name"]] = dist.version
            except (KeyError, AttributeError):
                # Fallback to distribution name
                versions[dist.name] = dist.version
    except Exception as e:
        logger.warning(f"Error getting distributions: {e}")
    
    return versions


# ============================================================================
# Private Helper Functions
# ============================================================================

def _normalize_target(target: VersionTarget) -> Tuple[str, Optional[ModuleType]]:
    """Normalize target to module name and module object."""
    if isinstance(target, str):
        name = target
        module = None
        # Try to import if possible
        try:
            module = importlib.import_module(name)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Could not import {name}: {e}")
    else:
        module = target
        name = module.__name__
    
    return name, module


def _resolve_version(
    module_name: str,
    module: Optional[ModuleType],
    fallback_to_metadata: bool
) -> str:
    """Resolve version using multiple strategies."""
    
    # Strategy 1: Distribution metadata
    version_str = get_package_version(module_name, use_cached=True)
    if version_str:
        return version_str
    
    # Strategy 2: Module attributes
    if module:
        version_str = get_module_version(module)
        if version_str:
            return version_str
    
    # Strategy 3: Raw metadata file
    if fallback_to_metadata and has_metadata(module_name):
        try:
            metadata_path = getmetafilepkg(module_name)
            if metadata_path:
                content = load(metadata_path)
                version_str = parse_metadata_version(content)
                if version_str:
                    return version_str
        except Exception as e:
            logger.debug(f"Could not parse metadata for {module_name}: {e}")
    
    # Strategy 4: Try to get from distribution with fallback name
    name_variations = _generate_name_variations(module_name)
    for variation in name_variations:
        if variation != module_name:
            version_str = get_package_version(variation, use_cached=True)
            if version_str:
                logger.debug(f"Found version using name variation: {variation}")
                return version_str
    
    return ""


@lru_cache(maxsize=128)
def _get_cached_package_version(package_name: str) -> Optional[str]:
    """Cached version of importlib.metadata.version."""
    try:
        return importlib_metadata.version(package_name)
    except (importlib_metadata.PackageNotFoundError, ValueError):
        return None


def _generate_name_variations(name: str) -> List[str]:
    """Generate common name variations for fallback lookups."""
    variations = {name}
    
    # Handle hyphens vs underscores
    variations.add(name.replace("-", "_"))
    variations.add(name.replace("_", "-"))
    
    # Handle case variations
    variations.add(name.lower())
    variations.add(name.upper())
    variations.add(name.title())
    
    # Handle PEP 503 normalization
    normalized = re.sub(r"[-_.]+", "-", name).lower()
    variations.add(normalized)
    variations.add(normalized.replace("-", "_"))
    
    return list(variations)


def _print_pretty_metadata(content: str, package_name: str) -> None:
    """Print metadata in a pretty formatted way.""" 
    sections = {}
    current_section = "general"
    sections[current_section] = []
    
    # Parse sections
    for line in content.splitlines():
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].lower()
            sections[current_section] = []
        else:
            sections.setdefault(current_section, []).append(line)
    
    # Print general section first
    if "general" in sections:
        for line in sections["general"]:
            if ":" in line:
                key, value = line.split(":", 1)
                print(f"{key:20}: {value.strip()}")
            elif line.strip():
                print(line)
        print()
    
    # Print other sections
    for section_name, section_lines in sections.items():
        if section_name == "general":
            continue
        
        if section_lines:
            print(f"[{section_name}]")
            for line in section_lines:
                if line.strip():
                    print(f"  {line}")
            print()


def _extract_version(name: str) -> str:
    """
    Extract package version from raw metadata file.
    
    This function is maintained for backward compatibility.
    Prefer parse_metadata_version() for new code.
    
    Parameters
    ----------
    name : str
        Name of the package.
    
    Returns
    -------
    str
        Version string or empty string if not found.
    """
    if not name or not has_metadata(name):
        return ""
    
    try:
        metadata_path = getmetafilepkg(name)
        if not metadata_path:
            return ""
        
        content = load(metadata_path)
        version_str = parse_metadata_version(content)
        return version_str or ""
    except Exception:
        return ""