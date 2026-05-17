#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module for detecting installed packages in the current Python environment.
"""

import site
import pkgutil
from pathlib import Path
from typing import List, Optional, Set, Generator
from functools import lru_cache
from .stdlib import is_stdlib, LIST_OF_STDLIBS


def _iter_package_paths(
    site_dirs: List[Path], include_editable: bool
) -> Generator[Path, None, None]:
    """
    Generate package paths from site directories.

    Parameters
    ----------
    site_dirs : List[Path]
        List of site directory paths.
    include_editable : bool
        Whether to include editable installations.

    Yields
    ------
    Path
        Path to a package or distribution info directory.
    """
    for site_dir in site_dirs:
        if not site_dir or not site_dir.exists():
            continue
        try:
            for entry in site_dir.iterdir():
                if entry.name.startswith("_") or entry.name.startswith("."):
                    continue
                yield entry
        except (PermissionError, OSError):
            continue


def _extract_package_name(path: Path, dist_info: bool) -> Optional[str]:
    """
    Extract package name from path.

    Parameters
    ----------
    path : Path
        Path to package directory or distribution info.
    dist_info : bool
        Whether to handle distribution info files.

    Returns
    -------
    Optional[str]
        Extracted package name, or None if invalid.
    """
    stem = path.stem
    if dist_info and path.suffix in {".dist-info", ".egg-info"}:
        if "-" in stem:
            stem = stem.split("-")[0]
    if not stem or len(stem) < 2:
        return None
    return stem


@lru_cache(maxsize=128)
def list_packages(
    dist_info: bool = False,
    include_editable: bool = True,
    ignore: Optional[List[str]] = None,
    include_stdlib: bool = False,
) -> List[str]:
    """
    Retrieve packages installed in the current Python environment.

    Parameters
    ----------
    dist_info : bool, optional
        If True, includes packages from dist-info/egg-info directories.
        Default is False.
    include_editable : bool, optional
        If True, includes user-editable installations (from user site).
        Default is True.
    ignore : Optional[List[str]], optional
        List of string patterns to ignore in package names.
        Default is None.
    include_stdlib : bool, optional
        If True, includes standard library packages.
        Default is False.

    Returns
    -------
    List[str]
        Sorted list of unique package names.

    Examples
    --------
    >>> packages_env()
    ['numpy', 'pandas', 'requests']

    >>> packages_env(dist_info=True, ignore=['test', 'example'])
    ['main-package', 'numpy', 'pandas']
    """
    ignore_set: Set[str] = set()

    if ignore:
        ignore_set = {pattern.lower() for pattern in ignore}
    site_dirs: List[Path] = [Path(s) for s in site.getsitepackages() if s]

    if include_editable:
        user_site = site.getusersitepackages()
        if user_site:
            site_dirs.append(Path(user_site))

    packages: Set[str] = set()
    stdlib_cache: Set[str] = set()

    for entry in _iter_package_paths(site_dirs, include_editable):
        pkg_name = _extract_package_name(entry, dist_info)

        if not pkg_name:
            continue

        if not include_stdlib:
            if pkg_name in stdlib_cache or is_stdlib(pkg_name):
                stdlib_cache.add(pkg_name)
                continue

        pkg_lower = pkg_name.lower()
        if ignore_set and any((pattern in pkg_lower for pattern in ignore_set)):
            continue
        packages.add(pkg_name)

    return sorted(packages)


@lru_cache(maxsize=128)
def all_packages(
    ignore: Optional[List[str]] = None,
) -> List[str]:
    """
    Return all available modules in the current Python environment.

    Parameters
    ----------
    ignore : list of str, optional
        List of case-insensitive name patterns. Any module containing
        one of these patterns will be excluded from the result.

    Returns
    -------
    list of str
        Sorted list of unique module names.
    """

    ignore_set: Set[str] = {i.lower() for i in ignore} if ignore else set()
    all_mods: Set[str] = set()

    # Add installed packages 
    all_mods.update(
        list_packages(
            dist_info=True,
            include_editable=True,
            include_stdlib=True,
        )
    )

    # Add standard library modules 
    all_mods.update(LIST_OF_STDLIBS)

    # Discover modules available via sys.path 
    for mod in pkgutil.iter_modules():
        name = mod.name
        if name:
            all_mods.add(name)

    # Apply ignore filtering
    if ignore_set:
        all_mods = {
            m for m in all_mods
            if not any(pattern in m.lower() for pattern in ignore_set)
        }

    return sorted(all_mods)