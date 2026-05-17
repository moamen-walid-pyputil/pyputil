#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from pathlib import Path
import sys
import re
import os
import importlib.util
import sysconfig
from typing import List, Optional, Set, Union, Any
import concurrent.futures
import logging
import site
from functools import lru_cache
from ..utils import ispackage


logger = logging.getLogger(__name__)
USER_SITE = site.getusersitepackages()


def getlocation(name: str, default: Any = 0) -> Union[List[str], Any]:
    """
    Locate a Python module or package on the current system.

    This function searches for Python modules, packages, and compiled
    extension modules using Python's import system rather than only
    scanning ``sys.path`` manually.

    Parameters
    ----------
    name : str
        Module or package name.
        The ``.py`` suffix is optional.
    default : Any, optional
        Value returned if the module cannot be found.
        If not provided, a ``ModuleNotFoundError`` is raised.

    Returns
    -------
    list of str or Any
        A list of absolute paths where the module/package exists.
        If nothing is found and ``default`` is provided, ``default``
        is returned instead.

    Raises
    ------
    ModuleNotFoundError
        If the module/package cannot be located and no default is given.

    Examples
    --------
    >>> getlocation("json")
    ['/usr/lib/python3.11/json/__init__.py']

    >>> getlocation("os")
    ['/usr/lib/python3.11/os.py']
    """
    locations: List[str] = []

    module_name = name.removesuffix(".py")

    # Try import system first (handles compiled modules + packages)
    spec = importlib.util.find_spec(module_name)

    if spec is not None:
        if spec.origin and spec.origin != "built-in":
            locations.append(str(Path(spec.origin).resolve()))

        if spec.submodule_search_locations:
            for loc in spec.submodule_search_locations:
                locations.append(str(Path(loc).resolve()))

    # Fallback manual scan (extra safety)
    for base in sys.path:
        base_path = Path(base)
        if not base_path.exists():
            continue

        pkg_path = base_path / module_name
        if pkg_path.is_dir():
            locations.append(str(pkg_path.resolve()))

        for suffix in (".py", ".pyc", ".so", ".pyd", ".dll"):
            mod_path = base_path / f"{module_name}{suffix}"
            if mod_path.is_file():
                locations.append(str(mod_path.resolve()))

    locations = list(dict.fromkeys(locations))  # remove duplicates

    if locations:
        return locations
    elif default != 0:
        return default
    else:
        raise ModuleNotFoundError(f"No module or package named '{name}'")


def getsitepath() -> List[str]:
    """
    Retrieve all Python 'site-packages' directories currently.

    Returns:
        List[str]: A list of strings, each representing a full path to a discovered
                  'site-packages' directory. Returns an empty list if none are found.
    """
    return site.getsitepackages()


@lru_cache(maxsize=128)
def getmetafilepkg(
    name: str,
    site: Optional[Union[str, Path]] = None,
    strict: bool = True
) -> Optional[str]:
    """
    Locate the 'METADATA' file of a specific installed Python package.

    This function searches for a package's METADATA file within .dist-info
    directories across site-packages locations. It handles package name
    normalization and version-aware matching.

    Parameters
    ----------
    name : str
        The name of the package whose metadata file should be located.
        Package names are case-insensitive and handle separators (-, _, .).
    site : Optional[Union[str, Path]], optional
        The specific site-packages directory to search. If omitted,
        searches all directories from site.getsitepath() and user site.
        Default is None.
    strict : bool, optional
        If True, requires exact version matching when package version
        can be determined. If False, matches any version of the package.
        Default is True.

    Returns
    -------
    Optional[str]
        The full filesystem path to the package's 'METADATA' file if found,
        or None if no matching metadata directory exists.

    Examples
    --------
    >>> getmetafilepkg('requests')
    '/usr/lib/python3.9/site-packages/requests-2.26.0.dist-info/METADATA'
    
    >>> getmetafilepkg('requests', site='/custom/site-packages')
    '/custom/site-packages/requests-2.26.0.dist-info/METADATA'
    
    >>> getmetafilepkg('nonexistent-package')
    None
    """
    from ...version import get_version_info
    
    # Normalize package name for consistent matching
    normalized_name = _normalize_package_name(name)
    
    # Try to get package version if needed
    package_version = None
    if strict:
        try:
            package_version = get_version_info(name).version
        except Exception as e:
            logger.debug(f"Could not determine version for {name}: {e}")
    
    # Get site directories to search
    site_dirs = _get_site_directories(site)
    
    # Search for METADATA file
    metadata_path = _search_metadata(
        site_dirs, normalized_name, package_version
    )
    
    return str(metadata_path) if metadata_path else None


@lru_cache(maxsize=128)
def getmetapath(
    name: str,
    site: Optional[Union[str, Path]] = None,
    use_parallel: bool = True,
    fallback_variations: bool = True
) -> str:
    """
    Resolve the absolute directory path of a package's metadata (.dist-info) folder.

    This function returns the path to the .dist-info directory containing
    the package's metadata. It uses parallel search by default for better
    performance when scanning multiple site-packages directories.

    Parameters
    ----------
    name : str
        The name of the package to locate. Package names are case-insensitive
        and handle various naming conventions.
    site : Optional[Union[str, Path]], optional
        The specific site-packages directory to search. If provided, searches
        only this location without parallel execution.
        Default is None (search all site-packages directories).
    use_parallel : bool, optional
        Whether to use parallel search when scanning multiple directories.
        Only relevant when site is not specified. Default is True.
    fallback_variations : bool, optional
        Whether to try common name variations (hyphens vs underscores) if
        the exact package name is not found. Default is True.

    Returns
    -------
    str
        The absolute path to the .dist-info directory for the given package.

    Raises
    ------
    FileNotFoundError
        If the package's .dist-info directory cannot be found in any
        site-packages location.

    Examples
    --------
    >>> getmetapath('requests')
    '/usr/lib/python3.9/site-packages/requests-2.26.0.dist-info'
    
    >>> getmetapath('Pillow')
    '/usr/lib/python3.9/site-packages/Pillow-8.3.2.dist-info'
    
    >>> getmetapath('nonexistent-package')
    Traceback (most recent call last):
        ...
    FileNotFoundError: MetaPath not found for 'nonexistent-package'
    """
    # Convert site to Path if string
    site_path = Path(site) if site else None
    
    # Search for metadata file
    if site_path:
        # Single directory search
        metadata_file = getmetafilepkg(name, site_path, strict=True)
        if not metadata_file:
            # Provide detailed error information
            available_sites = _get_site_directories()
            raise FileNotFoundError(
                f"MetaPath not found for '{name}' in '{site_path}'. "
                f"Searched site-packages: {[str(s) for s in available_sites]}"
            )
        return str(Path(metadata_file).parent.resolve())
    
    # Multi-directory search
    site_dirs = _get_site_directories()
    if not site_dirs:
        raise FileNotFoundError(
            "No site-packages directories found. Check your Python installation."
        )
    
    # Search in parallel or sequentially
    if use_parallel and len(site_dirs) > 1:
        result = _parallel_search_metadata(site_dirs, name)
    else:
        result = _sequential_search_metadata(site_dirs, name)
    
    if result:
        return str(Path(result).parent.resolve())
    
    # Try fallback name variations if enabled
    if fallback_variations:
        variations = _generate_name_variations(name)
        for variation in variations:
            if variation == name:
                continue
            logger.debug(f"Trying name variation: {variation}")
            
            if use_parallel and len(site_dirs) > 1:
                result = _parallel_search_metadata(site_dirs, variation)
            else:
                result = _sequential_search_metadata(site_dirs, variation)
            
            if result:
                logger.info(f"Found package '{name}' using variation '{variation}'")
                return str(Path(result).parent.resolve())
    
    # All attempts failed
    raise FileNotFoundError(
        f"MetaPath not found for '{name}'. "
        f"Tried variations: {variations if fallback_variations else [name]}. "
        f"Searched in: {[str(s) for s in site_dirs]}"
    )


@lru_cache(maxsize=128)
def get_all_meta_paths(
    include_user_site: bool = True,
    include_venv: bool = True,
    pattern: Optional[str] = None
) -> List[str]:
    """
    Return all .dist-info directories from Python installation paths.

    This function collects all .dist-info directories from standard Python
    site-packages locations, with options to include user site and virtual
    environments.

    Parameters
    ----------
    include_user_site : bool, optional
        Whether to include user site-packages directory (site.USER_SITE).
        Default is True.
    include_venv : bool, optional
        Whether to include virtual environment site-packages if active.
        Default is True.
    pattern : Optional[str], optional
        Optional regex pattern to filter .dist-info directory names.
        If provided, only directories matching the pattern are returned.
        Default is None.

    Returns
    -------
    List[str]
        List of absolute paths to .dist-info directories.

    Examples
    --------
    >>> get_all_meta_paths()
    ['/usr/lib/python3.9/site-packages/requests-2.26.0.dist-info',
     '/usr/lib/python3.9/site-packages/pip-21.2.4.dist-info']
    
    >>> get_all_meta_paths(pattern='requests.*')
    ['/usr/lib/python3.9/site-packages/requests-2.26.0.dist-info']
    
    >>> get_all_meta_paths(include_user_site=False)
    ['/usr/lib/python3.9/site-packages/requests-2.26.0.dist-info']
    """
    meta_paths: Set[Path] = set()
    
    # Collect site-packages directories
    site_dirs = _get_site_directories(
        include_user_site=include_user_site,
        include_venv=include_venv
    )
    
    # Compile pattern if provided
    pattern_re = re.compile(pattern) if pattern else None
    
    # Search each site-packages directory
    for site_dir in site_dirs:
        if not site_dir.exists():
            logger.debug(f"Site directory does not exist: {site_dir}")
            continue
        
        try:
            for dist_info_dir in site_dir.glob("*.dist-info"):
                if dist_info_dir.is_dir():
                    if pattern_re and not pattern_re.search(dist_info_dir.name):
                        continue
                    meta_paths.add(dist_info_dir.resolve())
        except (OSError, PermissionError) as e:
            logger.warning(f"Cannot access {site_dir}: {e}")
            continue
    
    return [str(p) for p in sorted(meta_paths)]


# ============================================================================
# Helper Functions
# ============================================================================

def _normalize_package_name(name: str) -> str:
    """Normalize package name for consistent matching."""
    # Convert to lowercase and replace separators with hyphens
    return re.sub(r"[-_.]+", "-", name.lower())


def _get_site_directories(
    site: Optional[Union[str, Path]] = None,
    include_user_site: bool = True,
    include_venv: bool = True
) -> List[Path]:
    """Get list of site-packages directories to search."""
    if site:
        return [Path(site).resolve()]
    
    site_dirs = set()
    
    # Get system site-packages
    for path_key in ['purelib', 'platlib']:
        try:
            path = sysconfig.get_path(path_key)
            if path:
                site_dirs.add(Path(path))
        except Exception:
            continue
    
    # Add from site module if available
    try:
        for s in getsitepath():
            site_dirs.add(Path(s))
        
        if include_user_site and USER_SITE:
            site_dirs.add(Path(USER_SITE))
    except ImportError:
        pass
    
    # Add virtual environment if requested
    if include_venv and hasattr(sys, 'prefix'):
        venv_site = Path(sys.prefix) / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
        if venv_site.exists():
            site_dirs.add(venv_site)
    
    # Filter out non-existent directories and return sorted
    return sorted([p for p in site_dirs if p.exists()])


def _search_metadata(
    site_dirs: List[Path],
    normalized_name: str,
    package_version: Optional[str]
) -> Optional[Path]:
    """Search for METADATA file in given site directories."""
    
    # Compile regex pattern for matching dist-info directories
    pattern = _build_distinfo_pattern(normalized_name, package_version)
    
    # Search sequentially through directories
    for site_dir in site_dirs:
        if not site_dir.exists():
            continue
        
        try:
            # Use scandir for efficient directory iteration
            with os.scandir(site_dir) as entries:
                for entry in entries:
                    if not entry.is_dir():
                        continue
                    
                    if not (entry.name.endswith('.dist-info') or entry.name.endswith('.egg-info')):
                        continue
                    
                    if pattern.match(entry.name):
                        metadata_path = Path(entry.path) / 'METADATA'
                        if metadata_path.exists():
                            return metadata_path
        except (OSError, PermissionError) as e:
            logger.debug(f"Cannot scan {site_dir}: {e}")
            continue
    
    return None


def _build_distinfo_pattern(
    normalized_name: str,
    package_version: Optional[str]
) -> re.Pattern:
    """Build regex pattern for matching .dist-info directories."""
    
    escaped_name = re.escape(normalized_name)
    
    if package_version:
        # Exact version matching
        escaped_version = re.escape(package_version)
        pattern = rf"^{escaped_name}-{escaped_version}\.dist-info$"
    else:
        # Any version matching
        pattern = rf"^{escaped_name}-[^\.]+\.dist-info$"
    
    return re.compile(pattern, re.IGNORECASE)


def _parallel_search_metadata(
    site_dirs: List[Path],
    package_name: str
) -> Optional[str]:
    """Search for package metadata in parallel across site directories."""
    
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(4, len(site_dirs))
    ) as executor:
        future_to_dir = {
            executor.submit(getmetafilepkg, package_name, site_dir): site_dir
            for site_dir in site_dirs
        }
        
        for future in concurrent.futures.as_completed(future_to_dir):
            try:
                result = future.result()
                if result:
                    return result
            except Exception as e:
                logger.debug(f"Search failed: {e}")
                continue
    
    return None


def _sequential_search_metadata(
    site_dirs: List[Path],
    package_name: str
) -> Optional[str]:
    """Search for package metadata sequentially."""
    
    for site_dir in site_dirs:
        result = getmetafilepkg(package_name, site_dir)
        if result:
            return result
    
    return None


def _generate_name_variations(name: str) -> List[str]:
    """Generate common name variations for fallback search."""
    variations = set()
    variations.add(name)
    variations.add(name.replace('-', '_'))
    variations.add(name.replace('_', '-'))
    variations.add(name.lower())
    variations.add(name.upper())
    variations.add(name.title())
    variations.add(name.replace('-', '_').lower())
    variations.add(name.replace('_', '-').lower())
    
    # Return in order of likely success
    return [name, name.replace('-', '_'), name.replace('_', '-'), 
            name.lower(), name.replace('-', '_').lower(), 
            name.replace('_', '-').lower()]


def search_metapath(
    pattern: str,
    use_regex: bool = False,
    case_sensitive: bool = False
) -> List[str]:
    """
    Search for installed package metadata (.dist-info) directories.

    This function retrieves all available ``.dist-info`` directories from
    the current Python environment and filters them based on either a
    substring match or a regular expression.

    Parameters
    ----------
    pattern : str
        Pattern used to match metadata directory paths.
        - If ``use_regex=False``: treated as a substring.
        - If ``use_regex=True``: treated as a regular expression.
    use_regex : bool, optional
        If True, interpret ``pattern`` as a regular expression.
        If False, perform a simple substring match.
        Default is False.
    case_sensitive : bool, optional
        Whether the match should be case-sensitive.
        Default is False.

    Returns
    -------
    List[str]
        A list of absolute paths to matching ``.dist-info`` directories.
        Returns an empty list if no matches are found.

    Raises
    ------
    re.error
        If ``use_regex=True`` and the pattern is invalid.

    Examples
    --------
    Basic substring search:

    >>> search_metapath("requests")
    ['/usr/lib/python3.11/site-packages/requests-2.31.0.dist-info']

    Case-insensitive search:

    >>> search_metapath("Requests")
    ['/usr/lib/python3.11/site-packages/requests-2.31.0.dist-info']

    Regex search:

    >>> search_metapath(r"requests-\\d+\\.\\d+", use_regex=True)
    ['/usr/lib/python3.11/site-packages/requests-2.31.0.dist-info']

    No matches:

    >>> search_metapath("nonexistent")
    []
    """
    paths = get_all_meta_paths()

    if not case_sensitive:
        pattern_cmp = pattern.lower()
    else:
        pattern_cmp = pattern

    results = []

    if use_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)

        for p in paths:
            if regex.search(p):
                results.append(p)
    else:
        for p in paths:
            target = p if case_sensitive else p.lower()
            if pattern_cmp in target:
                results.append(p)

    return results


