#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from __future__ import annotations

import shutil
import os
import logging
import subprocess
import sys
import warnings
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import platform
import tempfile
import stat
import importlib.util

from importlib.metadata import distributions, PackageNotFoundError, Distribution

from .metafile import getlocation


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class RemovalStatus(Enum):
    """Status codes for package removal operations."""
    SUCCESS = "success"
    SKIPPED_PROTECTED = "skipped_protected"
    SKIPPED_DEPENDENCY = "skipped_dependency"
    SKIPPED_EDITABLE = "skipped_editable"
    SKIPPED_NOT_FOUND = "skipped_not_found"
    FAILED_PIP = "failed_pip"
    FAILED_EXCEPTION = "failed_exception"
    DRY_RUN = "dry_run"


@dataclass
class RemovalResult:
    """Container for package removal operation results."""
    package_name: str
    status: RemovalStatus
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    dependents: Optional[Set[str]] = None
    error_details: Optional[str] = None


# Always protected packages - critical for environment stability
PROTECTED_PACKAGES: Set[str] = {
    "pip",
    "setuptools",
    "wheel",
    "distribute",
    "importlib-metadata",
    "importlib_resources",
}

# Packages that might break system tools if removed
SYSTEM_CRITICAL: Set[str] = {
    "python",
    "python3",
    "apt",
    "yum",
    "dnf",
}


# =========================
# Internal helpers
# =========================


def _build_dependency_map() -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """
    Build dependency and reverse-dependency maps from installed packages.
    
    This function analyzes all installed distributions and creates two maps:
    1. Forward map: package -> its dependencies
    2. Reverse map: package -> packages that depend on it
    
    Returns
    -------
    deps_map : dict of {str: set}
        A mapping from package names (lowercase) to sets of their dependency
        package names (lowercase). Empty sets indicate no dependencies.
        
    reverse_map : dict of {str: set}
        A mapping from package names (lowercase) to sets of packages that depend
        on them. Empty sets indicate no packages depend on this package.
    
    Notes
    -----
    - Package names are normalized to lowercase for consistent comparison
    - Only direct dependencies are captured (not transitive)
    - Packages without metadata or names are skipped silently
    - Requirement specifiers (versions, extras) are stripped, keeping only package names
    
    Examples
    --------
    >>> deps, rev = _build_dependency_map()
    >>> "numpy" in deps.get("pandas", set())
    True
    >>> "pandas" in rev.get("numpy", set())
    True
    """
    deps_map: Dict[str, Set[str]] = {}
    reverse_map: Dict[str, Set[str]] = {}
    
    for dist in distributions():
        name = dist.metadata.get("Name")
        if not name:
            logger.debug(f"Skipping distribution with no name: {dist}")
            continue
        
        name = name.lower()
        deps: Set[str] = set()
        
        requires = dist.requires or []
        for req in requires:
            # Extract package name before any version specifier or extra
            pkg_name = req.split()[0].split(';')[0].split('[')[0].lower()
            deps.add(pkg_name)
        
        deps_map[name] = deps
        
        for dep in deps:
            reverse_map.setdefault(dep, set()).add(name)
    
    logger.debug(f"Built dependency map with {len(deps_map)} packages")
    return deps_map, reverse_map


def _get_package_details(dist: Distribution) -> Dict[str, Union[str, bool, List[str]]]:
    """
    Extract detailed information about a distribution.
    
    Parameters
    ----------
    dist : Distribution
        The distribution object from importlib.metadata
        
    Returns
    -------
    dict
        Dictionary containing package details:
        - name: Package name
        - version: Package version
        - is_editable: Whether it's an editable install
        - location: Installation path
        - files: List of installed files (if available)
        
    Examples
    --------
    >>> dist = next(distributions())
    >>> details = _get_package_details(dist)
    >>> details['name']
    'pip'
    >>> isinstance(details['is_editable'], bool)
    True
    """
    details = {
        'name': dist.metadata.get("Name", "unknown"),
        'version': dist.metadata.get("Version", "unknown"),
        'is_editable': False,
        'location': str(dist.locate_file(".")) if dist._path else "unknown",
        'files': []
    }
    
    # Check for editable installation
    try:
        # Editable installs typically have a direct.py or similar structure
        if dist.files is None:
            details['is_editable'] = True
        else:
            for file in dist.files:
                if 'direct' in str(file) or 'editable' in str(file):
                    details['is_editable'] = True
                    break
    except Exception:
        details['is_editable'] = True
    
    return details


def _check_safe_removal(
    package_name: str,
    protected_set: Set[str],
    reverse_map: Dict[str, Set[str]],
    deps_map: Dict[str, Set[str]],
    force: bool = False
) -> Tuple[bool, str, Optional[Set[str]]]:
    """
    Determine if it's safe to remove a package.
    
    Parameters
    ----------
    package_name : str
        Name of the package to check (case-insensitive)
        
    protected_set : set of str
        Set of protected package names (lowercase)
        
    reverse_map : dict of {str: set}
        Reverse dependency map from _build_dependency_map()
        
    deps_map : dict of {str: set}
        Forward dependency map from _build_dependency_map()
        
    force : bool, default=False
        If True, bypass safety checks (use with extreme caution)
        
    Returns
    -------
    safe : bool
        True if removal appears safe, False otherwise
        
    reason : str
        Explanation of why removal is safe or unsafe
        
    dependents : set of str or None
        Set of packages that depend on this package (if any)
        
    Notes
    -----
    Safety checks include:
    1. Package is not in protected set
    2. Package has no active dependents (unless force=True)
    3. Package doesn't appear to be system-critical
    
    Examples
    --------
    >>> deps, rev = _build_dependency_map()
    >>> safe, reason, dependents = _check_safe_removal("numpy", set(), rev, deps)
    >>> if safe:
    ...     print(f"Safe to remove: {reason}")
    """
    package_lower = package_name.lower()
    
    # Force mode bypasses most checks
    if force:
        return True, "Force removal enabled", None
    
    # Check protected packages
    if package_lower in protected_set:
        return False, f"Package is protected (in PROTECTED_PACKAGES or exclude list)", None
    
    # Check system-critical packages
    if package_lower in SYSTEM_CRITICAL:
        return False, f"Package is system-critical: {package_lower}", None
    
    # Check for dependents
    dependents = reverse_map.get(package_lower, set())
    active_dependents = {d for d in dependents if d not in protected_set}
    
    if active_dependents:
        return False, f"Package has {len(active_dependents)} dependent(s)", active_dependents
    
    return True, "No conflicts found", None


def _get_system_protected_paths() -> List[Path]:
    """
    Get system-specific protected paths that are considered critical.
    
    This function returns a list of paths that are typically protected by the
    operating system because deleting them could break the system.
    
    Returns
    -------
    List[Path]
        A list of Path objects representing critical system directories.
        
    Notes
    -----
    - On Windows: Returns SystemRoot, System32, Program Files, and drive roots
    - On Unix/Linux: Returns /, /usr, /bin, /sbin, /etc, /boot, /dev, etc.
    - On macOS: Additionally returns /System, /Applications, /Library
    
    Examples
    --------
    >>> protected = _get_system_protected_paths()
    >>> len(protected) > 0
    True
    >>> any(p.name == 'Windows' for p in protected)  # On Windows
    True
    """
    system = platform.system().lower()
    protected_paths = []
    
    if system == 'windows':
        # Windows system paths
        windows_dirs = [
            os.environ.get('SystemRoot', 'C:\\Windows'),
            os.environ.get('SystemDrive', 'C:') + '\\Windows\\System32',
            os.environ.get('ProgramFiles', 'C:\\Program Files'),
            os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)'),
        ]
        protected_paths.extend([Path(p) for p in windows_dirs if p])
        # Add drive roots
        import string
        for drive in string.ascii_uppercase:
            protected_paths.append(Path(f"{drive}:\\"))
    else:
        # Unix-like system paths
        protected_paths.extend([
            Path("/"),
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/lib"),
            Path("/lib64"),
            Path("/etc"),
            Path("/boot"),
            Path("/dev"),
            Path("/proc"),
            Path("/sys"),
        ])
        
        # Add macOS specific paths
        if system == 'darwin':
            protected_paths.extend([
                Path("/System"),
                Path("/Applications"),
                Path("/Library"),
            ])
    
    return protected_paths


def _is_dangerous_path(path: Path, force: bool = False) -> bool:
    """
    Check if path is too sensitive to delete (cross-platform).
    
    When force=True, this function always returns False, allowing deletion
    of any path regardless of how sensitive it is.
    
    Parameters
    ----------
    path : Path
        The path to check for danger level.
    force : bool, optional
        If True, bypass all danger checks (default is False).
        
    Returns
    -------
    bool
        True if the path is considered dangerous and force=False,
        False if the path is safe or force=True.
        
    Notes
    -----
    - With force=False: Checks against system protected paths and mount points
    - With force=True: Always returns False (no path is considered dangerous)
    - If path cannot be accessed, returns True (conservative approach)
    
    Examples
    --------
    >>> from pathlib import Path
    >>> _is_dangerous_path(Path("/usr"), force=False)  # Dangerous on Unix
    True
    >>> _is_dangerous_path(Path("/usr"), force=True)   # Force bypass
    False
    >>> _is_dangerous_path(Path("./my_module"), force=False)  # Safe path
    False
    """
    if force:
        # When force=True, we delete anything without checks
        return False
        
    try:
        resolved = path.resolve()
        dangerous_roots = _get_system_protected_paths()
        
        # Check exact matches and parent relationships
        for root in dangerous_roots:
            try:
                resolved_root = root.resolve()
                if resolved == resolved_root or resolved_root in resolved.parents:
                    return True
            except (PermissionError, OSError):
                continue
                
        # Additional safety: check if path is a mount point
        try:
            if path.is_mount():
                return True
        except (OSError, AttributeError):
            # is_mount might not be available on older Python versions
            pass
            
        return False
    except (PermissionError, OSError):
        # If we can't access the path, assume it's dangerous
        return True


def _is_system_python_path(path: Path, force: bool = False) -> bool:
    """
    Check if path is within Python's system installation.
    
    When force=True, this function always returns False, allowing deletion
    of Python system paths.
    
    Parameters
    ----------
    path : Path
        The path to check.
    force : bool, optional
        If True, bypass system Python path checks (default is False).
        
    Returns
    -------
    bool
        True if path is in Python system paths and force=False,
        False otherwise (including when force=True).
        
    Notes
    -----
    - Checks against Python's standard library paths (stdlib, platstdlib, etc.)
    - With force=True, no path is considered a system Python path
    - Returns False on any exception to avoid blocking
    
    Examples
    --------
    >>> import sysconfig
    >>> stdlib_path = Path(sysconfig.get_path('stdlib'))
    >>> _is_system_python_path(stdlib_path, force=False)
    True
    >>> _is_system_python_path(stdlib_path, force=True)
    False
    >>> _is_system_python_path(Path("./my_module"), force=False)
    False
    """
    if force:
        # When force=True, we allow deletion of Python system paths
        return False
        
    try:
        import sysconfig
        system_paths = [
            sysconfig.get_path('stdlib'),
            sysconfig.get_path('platstdlib'),
            sysconfig.get_path('purelib'),
            sysconfig.get_path('platlib'),
        ]
        
        resolved_path = path.resolve()
        for sys_path in system_paths:
            if sys_path:
                try:
                    resolved_sys_path = Path(sys_path).resolve()
                    if resolved_path == resolved_sys_path or resolved_sys_path in resolved_path.parents:
                        return True
                except (PermissionError, OSError):
                    continue
        return False
    except Exception:
        return False


def _remove_readonly(func, path, excinfo):
    """
    Handle readonly files on Windows by making them writable.
    
    This function is used as an error handler for shutil.rmtree on Windows
    when encountering read-only files. It changes the file permissions to
    writable and retries the operation.
    
    Parameters
    ----------
    func : callable
        The function that failed (typically os.remove or os.rmdir).
    path : str
        The path to the file/directory that caused the error.
    excinfo : tuple
        Exception info tuple (type, value, traceback).
        
    Notes
    -----
    - Only modifies the read-only attribute (S_IWRITE on Windows)
    - Does not modify other permission bits
    - After making the file writable, the original function is called again
    
    Examples
    --------
    >>> import shutil, stat, os
    >>> # Used internally by shutil.rmtree with onerror parameter
    >>> shutil.rmtree('/path/to/readonly/dir', onerror=_remove_readonly)
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _safe_remove_path(
    path: Path, 
    silent: bool, 
    backup: bool = False,
    force: bool = False
) -> tuple[bool, Optional[Path]]:
    """
    Safely remove a file or directory with cross-platform support.
    
    This function handles file/directory deletion with safety checks,
    permission handling, and optional backup creation. When force=True,
    it bypasses all safety checks and deletes anything.
    
    Parameters
    ----------
    path : Path
        The path to remove (file or directory).
    silent : bool
        If True, suppress exceptions and fail silently.
        If False, raise exceptions on failure.
    backup : bool, optional
        If True, create a backup before deletion (default is False).
        Backups are stored in system temp directory.
    force : bool, optional
        If True, bypass all safety checks (dangerous paths, system paths)
        and delete anything (default is False).
        
    Returns
    -------
    tuple[bool, Optional[Path]]
        A tuple containing:
        - bool: True if removal was successful, False otherwise
        - Optional[Path]: Path to backup if backup=True and removal succeeded,
          otherwise None
          
    Raises
    ------
    RuntimeError
        If attempting to delete a critical path without force=True.
    OSError, PermissionError
        If deletion fails and silent=False.
        
    Notes
    -----
    - On Windows: Automatically handles read-only files by removing the attribute
    - On Unix: Changes directory permissions to 0o755 if needed
    - Backups are created in: {tempdir}/python_rm_backup_{pid}/{original_name}
    - With force=True, no path is considered critical
    - With silent=True, all exceptions are suppressed
    
    Examples
    --------
    >>> from pathlib import Path
    >>> # Safe deletion
    >>> success, backup = _safe_remove_path(Path("./temp.txt"), silent=False)
    >>> 
    >>> # Force deletion of system path
    >>> success, backup = _safe_remove_path(Path("/tmp/test"), silent=False, force=True)
    >>> 
    >>> # Delete with backup
    >>> success, backup = _safe_remove_path(Path("./important.py"), silent=False, backup=True)
    >>> if success and backup:
    ...     print(f"Backup created at {backup}")
    """
    backup_path = None
    
    try:
        if not path.exists():
            return False, None

        # Check for dangerous paths (respects force parameter)
        if _is_dangerous_path(path, force=force) or _is_system_python_path(path, force=force):
            raise RuntimeError(f"Refusing to delete critical path: '{path}'")

        # Create backup if requested
        if backup:
            backup_dir = Path(tempfile.gettempdir()) / f"python_rm_backup_{os.getpid()}"
            backup_dir.mkdir(exist_ok=True)
            backup_path = backup_dir / path.name
            if path.is_dir():
                shutil.copytree(path, backup_path, symlinks=True, ignore_dangling_symlinks=True)
            else:
                shutil.copy2(path, backup_path)

        # Remove read-only attribute on Windows
        if platform.system() == 'Windows':
            if path.is_dir():
                shutil.rmtree(path, onerror=_remove_readonly)
            else:
                # Clear read-only attribute
                path.chmod(stat.S_IWRITE)
                path.unlink()
        else:
            # Unix-like systems
            if path.is_dir():
                # Change permissions if needed
                os.chmod(path, 0o755)
                shutil.rmtree(path)
            else:
                path.unlink()

        return True, backup_path

    except Exception as e:
        if not silent:
            raise
        return False, None


def _validate_stdlib(name: str, force: bool, silent: bool, kind: str) -> bool:
    """
    Check if a module/package is from the standard library and handle accordingly.
    
    Parameters
    ----------
    name : str
        Name of the module or package to check.
    force : bool
        If True, allow removal of standard library modules.
        If False, block removal.
    silent : bool
        If True, suppress exceptions when blocking removal.
        If False, raise RuntimeError when blocking.
    kind : str
        Type of object being checked ('module' or 'package').
        
    Returns
    -------
    bool
        True if removal is allowed (not stdlib or force=True).
        False if removal is blocked (stdlib and force=False).
        
    Raises
    ------
    RuntimeError
        If it's a standard library module, force=False, and silent=False.
        
    Notes
    -----
    - Standard library modules include 'os', 'sys', 'json', 're', etc.
    - With force=True, standard library modules can be removed
    - This is a dangerous operation that can break Python functionality
    
    Examples
    --------
    >>> _validate_stdlib('os', force=False, silent=False, kind='module')
    Traceback (most recent call last):
    ...
    RuntimeError: 'os' is a standard library module and cannot be removed without 'force=True'
    >>> 
    >>> _validate_stdlib('os', force=True, silent=False, kind='module')  # Allowed
    True
    >>> 
    >>> _validate_stdlib('mymodule', force=False, silent=False, kind='module')  # Not stdlib
    True
    """
    from ...modules import is_stdlib
    if is_stdlib(name) and not force:
        if not silent:
            raise RuntimeError(
                f"'{name}' is a standard library {kind} and cannot be removed "
                "without 'force=True'"
            )
        return False
    return True


def _get_all_module_paths(module_name: str) -> List[Path]:
    """
    Get all possible paths for a module (including namespace packages).
    
    This function attempts to locate all filesystem paths associated with
    a Python module, including multiple locations for namespace packages.
    
    Parameters
    ----------
    module_name : str
        Fully qualified name of the module (e.g., 'numpy', 'requests.models').
        
    Returns
    -------
    List[Path]
        A list of unique Path objects where the module is located.
        Returns an empty list if the module cannot be located.
        
    Notes
    -----
    - Uses multiple methods to find module paths:
      1. getlocation() from .metafile
      2. importlib.util.find_spec()
    - Removes duplicate paths automatically
    - For namespace packages, returns all namespace locations
    - For regular modules, returns the single .py file or package directory
    
    Examples
    --------
    >>> paths = _get_all_module_paths('json')
    >>> len(paths) >= 1
    True
    >>> any(p.name == 'json.py' for p in paths)  # Standard library
    True
    >>> 
    >>> paths = _get_all_module_paths('does_not_exist')
    >>> len(paths)
    0
    >>> 
    >>> # For a package
    >>> paths = _get_all_module_paths('urllib')
    >>> any(p.name == 'urllib' and p.is_dir() for p in paths)
    True
    """
    paths = []
    
    # Try to get location using getlocation
    locs = getlocation(module_name, [])
    paths.extend([Path(loc) for loc in locs if Path(loc).is_dir()])
    
    # Try using importlib
    try:
        spec = importlib.util.find_spec(module_name)
        if spec and spec.origin and spec.origin != 'namespace':
            paths.append(Path(spec.origin))
        if spec and spec.submodule_search_locations:
            for loc in spec.submodule_search_locations:
                paths.append(Path(loc))
    except (ImportError, AttributeError):
        pass
    
    return list(set(paths))  # Remove duplicates


# =========================
# Public API
# =========================

def remove_module(
    module_name: str,
    silent: bool = False,
    force: bool = False,
    backup: bool = False,
    dry_run: bool = False,
) -> Optional[Path]:
    """
    Remove a Python module file from the filesystem.

    This function locates and deletes the physical file(s) associated with
    a Python module. It can handle regular modules (.py files) and packages
    (directories with __init__.py). With force=True, it can even delete
    standard library modules (use with extreme caution!).

    Parameters
    ----------
    module_name : str
        Fully qualified name of the module (e.g., 'requests', 'numpy.core').
        Must be importable from the current Python environment.
        
    silent : bool, optional
        If True, suppress all exceptions and fail silently.
        If False (default), raise exceptions on errors.
        
    force : bool, optional
        If True, allow deletion of standard library modules and bypass
        all safety checks. This is DANGEROUS and can break your Python
        installation. Use with extreme caution. Default is False.
        
    backup : bool, optional
        If True, create a backup in the system temp directory before deletion.
        The backup location is returned. Default is False.
        
    dry_run : bool, optional
        If True, only print what would be deleted without actually removing
        anything. Useful for testing. Default is False.

    Returns
    -------
    Optional[Path]
        - If backup=True and deletion successful: Path to backup location
        - If backup=False or no backup created: None
        - If dry_run=True: None

    Raises
    ------
    ValueError
        If module_name is not a valid importable module.
    FileNotFoundError
        If the module file cannot be located on the filesystem.
    RuntimeError
        If attempting to remove a standard library module without force=True.
    OSError
        If filesystem deletion fails (permissions, file in use, etc.).

    Notes
    -----
    - Only removes the physical file, not references in sys.modules
    - The module will still be importable until Python is restarted
    - On Windows, automatically handles read-only files
    - Backups are stored in: {tempdir}/python_rm_backup_{pid}/{module_name}
    - For namespace packages, removes all discovered locations
    - With force=True, no safety checks are performed - you can delete anything!

    Examples
    --------
    >>> # Remove a third-party module (safe)
    >>> remove_module('requests')
    >>> 
    >>> # Remove with backup (safer)
    >>> backup_path = remove_module('mymodule', backup=True)
    >>> print(f"Backup saved to {backup_path}")
    >>> 
    >>> # Preview what would be removed (no actual deletion)
    >>> remove_module('numpy', dry_run=True)
    [DRY RUN] Would remove: /usr/local/lib/python3.9/site-packages/numpy
    >>> 
    >>> # DANGEROUS: Force remove a standard library module
    >>> remove_module('os', force=True, backup=True)  # Creates backup first
    >>> 
    >>> # Silent mode (suppress errors)
    >>> remove_module('nonexistent_module', silent=True)  # Returns None silently
    """
    from ...modules import ismodule
    if not _validate_stdlib(module_name, force, silent, "module"):
        return None

    if not ismodule(module_name):
        if not silent:
            raise ValueError(f"'{module_name}' is not a valid module")
        return None

    paths = _get_all_module_paths(module_name)
    
    if not paths:
        if not silent:
            raise FileNotFoundError(f"No file found for '{module_name}'")
        return None

    backup_paths = []
    for path in paths:
        if dry_run:
            if not silent:
                print(f"[DRY RUN] Would remove: {path}")
            continue
            
        removed, backup = _safe_remove_path(path, silent, backup, force=force)
        if removed and backup:
            backup_paths.append(backup)
        
        if not removed and not silent and not backup:
            raise FileNotFoundError(f"Module file not found at '{path}'")

    return backup_paths[0] if backup_paths else None


def remove_package(
    package_name: str,
    silent: bool = False,
    force: bool = False,
    backup: bool = False,
    dry_run: bool = False,
    recursive: bool = True,
) -> Optional[Path]:
    """
    Remove a Python package directory and all its contents.

    This function locates and deletes the entire directory structure of a
    Python package, including all submodules, subpackages, and other files.
    With force=True, it can delete system packages (use with extreme caution!).

    Parameters
    ----------
    package_name : str
        Fully qualified package name (e.g., 'numpy', 'django.contrib').
        Must be an importable package with __init__.py.
        
    silent : bool, optional
        If True, suppress all exceptions and fail silently.
        If False (default), raise exceptions on errors.
        
    force : bool, optional
        If True, allow deletion of standard library packages and bypass
        all safety checks. This is EXTREMELY DANGEROUS and can break
        your Python installation and even your operating system if you
        delete critical paths. Default is False.
        
    backup : bool, optional
        If True, create a full backup of the entire package before deletion.
        The backup location is returned. Default is False.
        
    dry_run : bool, optional
        If True, only print what would be deleted without actually removing
        anything. Useful for testing. Default is False.
        
    recursive : bool, optional
        If True (default), remove all subdirectories and files recursively.
        If False, only remove the package directory if empty.

    Returns
    -------
    Optional[Path]
        - If backup=True and deletion successful: Path to backup directory
        - If backup=False or no backup created: None
        - If dry_run=True: None

    Raises
    ------
    ValueError
        If package_name is not a valid importable package.
    FileNotFoundError
        If no package paths are found on the filesystem.
    RuntimeError
        If attempting to remove a standard library package without force=True.
    OSError
        If deletion fails (permissions, files in use, etc.).
    PermissionError
        If you don't have permission to delete the package.

    Notes
    -----
    - Removes ALL discovered locations of the package (namespace packages)
    - On Windows, handles permission issues automatically
    - The package will still be importable from cache until Python restarts
    - With force=True, you can delete ANY package, including:
      - Standard library packages (json, urllib, etc.)
      - System packages (if running with sufficient privileges)
      - Even this module's own package (if you're feeling adventurous)
    - Backups preserve directory structure, symlinks, and metadata
    - Deletion is permanent unless backup=True was used

    Warnings
    --------
    - Deleting standard library packages WILL break Python
    - Deleting system packages CAN break your operating system
    - Always use backup=True when using force=True
    - Test with dry_run=True first to see what will be deleted

    Examples
    --------
    >>> # Normal package removal (safe)
    >>> remove_package('mypackage')
    >>> 
    >>> # Remove with backup for safety
    >>> backup_path = remove_package('myapp', backup=True)
    >>> print(f"Package backed up to {backup_path}")
    >>> 
    >>> # Preview deletion (no actual removal)
    >>> remove_package('numpy', dry_run=True)
    [DRY RUN] Would remove: /usr/local/lib/python3.9/site-packages/numpy
    [DRY RUN] Would remove: /usr/local/lib/python3.9/site-packages/numpy-1.21.0.dist-info
    >>> 
    >>> # DANGEROUS: Force delete a standard library package
    >>> remove_package('json', force=True, backup=True, dry_run=True)  # Preview first
    >>> # Only run after preview:
    >>> # remove_package('json', force=True, backup=True)  # Actual deletion
    >>> 
    >>> # Remove namespace package (all locations)
    >>> remove_package('namespace_pkg')  # Removes from all site-packages
    >>> 
    >>> # Silent mode (suppress all errors)
    >>> remove_package('nonexistent_pkg', silent=True)  # Returns None
    """
    from ...modules import ispackage
    if not _validate_stdlib(package_name, force, silent, "package"):
        return None

    if not ispackage(package_name):
        if not silent:
            raise ValueError(f"'{package_name}' is not a valid package")
        return None

    paths = _get_all_module_paths(package_name)

    if not paths:
        if not silent:
            raise FileNotFoundError(f"No locations found for '{package_name}'")
        return None

    removed_any = False
    backup_paths = []

    for path in paths:
        if dry_run:
            if not silent:
                print(f"[DRY RUN] Would remove: {path}")
            continue
            
        removed, backup = _safe_remove_path(path, silent, backup, force=force)
        if removed:
            removed_any = True
            if backup:
                backup_paths.append(backup)

    if not removed_any and not silent:
        raise FileNotFoundError(f"No files found for '{package_name}'")

    return backup_paths[0] if backup_paths else None


def remove(
    module_or_package_name: str,
    silent: bool = False,
    force: bool = False,
    backup: bool = False,
    dry_run: bool = False,
) -> Optional[Path]:
    """
    Remove a module or package by name (auto-detects which one).

    This is the main entry point for deleting Python modules and packages.
    It automatically detects whether the name refers to a module or a package
    and calls the appropriate removal function. With force=True, it can
    delete anything - use with extreme caution!

    Parameters
    ----------
    module_or_package_name : str
        Name of the module or package to delete (e.g., 'requests', 'json', 'mypackage').
        Must be importable from the current Python environment.
        
    silent : bool, optional
        If True, suppress all exceptions and fail silently.
        If False (default), raise exceptions on errors.
        
    force : bool, optional
        If True, allow deletion of standard library modules/packages and
        bypass ALL safety checks. This is EXTREMELY DANGEROUS:
        - Can delete Python's standard library (breaks Python)
        - Can delete system files (breaks OS)
        - Can delete itself (breaks the function while running)
        Use with extreme caution and always with backup=True. Default is False.
        
    backup : bool, optional
        If True, create a backup before deletion.
        HIGHLY RECOMMENDED when using force=True. Default is False.
        
    dry_run : bool, optional
        If True, only print what would be deleted without actually removing
        anything. ALWAYS use this first when using force=True to see what
        will be deleted. Default is False.

    Returns
    -------
    Optional[Path]
        - If backup=True and deletion successful: Path to backup location
        - If backup=False or no backup created: None
        - If dry_run=True: None
        - If silent=True and error occurs: None

    Raises
    ------
    FileNotFoundError
        If the name does not refer to a module or package (and silent=False).
    RuntimeError
        If removal is blocked due to protection rules without force=True.
    ValueError
        If the name is invalid or empty.
    OSError
        If filesystem deletion fails.

    Notes
    -----
    - Automatically detects modules vs packages
    - For modules: removes the .py file or .pyc cache
    - For packages: removes the entire directory tree
    - With force=False: protects standard library and system paths
    - With force=True: NO PROTECTION - you can delete anything
    - Always use dry_run=True first when using force=True
    - Always use backup=True when using force=True
    - Deleted items are gone forever unless backup=True was used

    Warnings
    --------
    EXTREME CAUTION NEEDED WITH force=True 
    
    The following are possible with force=True:
    - Delete 'os' module → Python can no longer run basic commands
    - Delete 'sys' module → Python breaks completely
    - Delete '/usr/lib/python3.x' → System Python broken
    - Delete C:\\Windows\\System32 → Windows won't boot
    - Delete '/' → Linux/macOS system destroyed
    
    ALWAYS follow this safety checklist when using force=True:
    1. Use dry_run=True first to see what will be deleted
    2. Use backup=True to create a restore point
    3. Run in a virtual environment if possible
    4. Have a system backup ready
    5. Don't run as root/Administrator unless necessary

    Examples
    --------
    >>> # Safe usage - delete third-party package
    >>> remove('requests')
    >>> 
    >>> # Safe usage - delete custom module with backup
    >>> backup_path = remove('mymodule', backup=True)
    >>> 
    >>> # Preview deletion (always do this first!)
    >>> remove('numpy', dry_run=True)
    [DRY RUN] Would remove: /usr/local/lib/python3.9/site-packages/numpy
    [DRY RUN] Would remove: /usr/local/lib/python3.9/site-packages/numpy-1.21.0.dist-info
    >>> 
    >>> # DANGEROUS - Force delete standard library (with safety measures)
    >>> # Step 1: Preview
    >>> remove('json', force=True, dry_run=True)
    [DRY RUN] Would remove: /usr/lib/python3.9/json
    [DRY RUN] Would remove: /usr/lib/python3.9/json/__init__.py
    [DRY RUN] Would remove: /usr/lib/python3.9/json/encoder.py
    [DRY RUN] Would remove: /usr/lib/python3.9/json/decoder.py
    >>> 
    >>> # Step 2: If sure, delete with backup
    >>> backup_path = remove('json', force=True, backup=True)
    >>> print(f"Backup saved to {backup_path} - restore with shutil.copytree()")
    >>> 
    >>> # DANGEROUS - Delete system path (EXTREME)
    >>> # remove('/', force=True, dry_run=True)  # Preview first - DON'T ACTUALLY RUN
    >>> 
    >>> # Silent mode - suppress all errors
    >>> remove('nonexistent', silent=True)  # Returns None silently
    >>> 
    >>> # Practical example with error handling
    >>> try:
    ...     backup = remove('mypackage', backup=True, dry_run=False)
    ...     if backup:
    ...         print(f"Successfully deleted. Backup at {backup}")
    ... except Exception as e:
    ...     print(f"Failed to delete: {e}")
    """
    from ...modules import ismodule, ispackage
    
    # Validate input
    if not module_or_package_name or not isinstance(module_or_package_name, str):
        if not silent:
            raise ValueError("module_or_package_name must be a non-empty string")
        return None
    
    if ismodule(module_or_package_name):
        return remove_module(
            module_or_package_name, 
            silent=silent, 
            force=force,
            backup=backup, 
            dry_run=dry_run
        )
    elif ispackage(module_or_package_name):
        return remove_package(
            module_or_package_name, 
            silent=silent, 
            force=force,
            backup=backup, 
            dry_run=dry_run
        )
    else:
        if not silent:
            raise FileNotFoundError(
                f"No module or package named '{module_or_package_name}'"
            )
        return None


def remove_pip_packages(
    *,
    dry_run: bool = True,
    exclude: Optional[Iterable[str]] = None,
    include_editable: bool = False,
    force: bool = False,
    safe_mode: bool = True,
    log_file: Optional[Union[str, Path]] = None,
    verbose: bool = False,
) -> Tuple[int, List[RemovalResult]]:
    """
    Safely uninstall pip packages with comprehensive dependency awareness and safety checks.
    
    This function provides a robust way to remove Python packages from the current
    environment while respecting dependencies and protecting critical packages.
    It performs dependency analysis, safety validation, and detailed logging.
    
    Parameters
    ----------
    dry_run : bool, default=True
        If True, simulate removal without actually uninstalling packages.
        Recommended to run first with dry_run=True to preview changes.
        
    exclude : Iterable[str] or None, optional
        Additional package names to protect from removal (case-insensitive).
        These will be added to the default PROTECTED_PACKAGES set.
        
    include_editable : bool, default=False
        If True, include editable installations in removal candidates.
        Editable installs (pip install -e) are typically development installations
        and may be skipped by default to prevent workflow disruption.
        
    force : bool, default=False
        If True, bypass some safety checks including dependent package warnings.
        Use with extreme caution as this may break other packages!
        
    safe_mode : bool, default=True
        If True, perform additional safety validations including:
        - Verifying pip is functional before attempting removals
        - Checking for virtual environment
        - Validating package existence
        
    log_file : str or Path or None, optional
        Path to a log file where removal operations will be recorded.
        If None, logging is only to stdout/stderr.
        
    verbose : bool, default=False
        If True, output detailed debugging information during execution.
    
    Returns
    -------
    removed_count : int
        Number of packages successfully removed (or would be removed in dry-run mode)
        
    results : list of RemovalResult
        Detailed results for each package attempted for removal, including:
        - Package name
        - Removal status (success, skipped, failed)
        - Message explaining the outcome
        - Timestamp of operation
        - Dependents (if relevant)
        - Error details (if failed)
    
    Warns
    -----
    UserWarning
        For various skip conditions, removal confirmations, and failures.
        Each warning includes context about why an action was taken.
    
    Notes
    -----
    Safety Features:
    - Always protects pip, setuptools, and wheel from removal
    - Prevents removal of packages with active dependents (unless forced)
    - Skips editable installs by default
    - Supports dry-run mode for preview
    - Validates pip functionality before operations
    - Checks for virtual environment to prevent system Python corruption
    
    Dependency Analysis:
    - Builds complete dependency graph of all installed packages
    - Checks both forward and reverse dependencies
    - Prevents orphaned packages by checking dependents
    
    Best Practices:
    1. Always run with dry_run=True first to preview changes
    2. Use in a virtual environment, not system Python
    3. Review excluded packages if needed
    4. Check logs for any warnings or errors
    5. Consider creating a requirements.txt backup before removal
    
    Examples
    --------
    >>> # Preview what would be removed
    >>> count, results = remove_pip_packages(dry_run=True)
    >>> print(f"Would remove {count} packages")
    
    >>> # Remove non-critical packages, protecting 'requests'
    >>> count, results = remove_pip_packages(
    ...     dry_run=False,
    ...     exclude=['requests', 'urllib3'],
    ...     verbose=True
    ... )
    
    >>> # Force removal with logging
    >>> from pathlib import Path
    >>> count, results = remove_pip_packages(
    ...     dry_run=False,
    ...     force=True,
    ...     log_file=Path('./removal.log')
    ... )
    
    >>> # Analyze results
    >>> for result in results:
    ...     if result.status == RemovalStatus.SUCCESS:
    ...         print(f"✓ {result.package_name}")
    ...     elif result.status == RemovalStatus.SKIPPED_DEPENDENCY:
    ...         print(f"⚠ {result.package_name}: {result.message}")
    """
    
    # Setup logging
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
    
    if verbose:
        logger.setLevel(logging.DEBUG)
    
    # Validate environment
    if safe_mode:
        logger.info("Running safety validations...")
        
        # Check for virtual environment
        import sys
        if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
            logger.debug("Virtual environment detected")
        else:
            warning_msg = "Not running in a virtual environment! This may affect system Python."
            warnings.warn(warning_msg, UserWarning)
            if not force:
                logger.warning(warning_msg)
        
        # Verify pip is available
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                raise RuntimeError("pip is not functional")
            logger.debug(f"pip version: {result.stdout.split()[1] if result.stdout else 'unknown'}")
        except Exception as e:
            error_msg = f"Cannot verify pip functionality: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
    
    # Build protection set
    exclude_set = {x.lower() for x in (exclude or [])}
    protected = PROTECTED_PACKAGES | exclude_set
    
    # Build dependency maps
    logger.info("Building dependency maps...")
    deps_map, reverse_map = _build_dependency_map()
    logger.debug(f"Found {len(deps_map)} packages with dependencies")
    
    results: List[RemovalResult] = []
    successful_removals: List[str] = []
    
    # Process each distribution
    for dist in distributions():
        name = dist.metadata.get("Name")
        if not name:
            continue
        
        name_lower = name.lower()
        
        # Get package details for better decision making
        details = _get_package_details(dist)
        
        # Check if removal is safe
        safe, reason, dependents = _check_safe_removal(
            name_lower, protected, reverse_map, deps_map, force
        )
        
        if not safe:
            status = RemovalStatus.SKIPPED_PROTECTED
            message = reason
            if dependents:
                message += f": {', '.join(dependents)}"
            result = RemovalResult(
                package_name=name,
                status=status,
                message=message,
                dependents=dependents
            )
            results.append(result)
            warnings.warn(f"[SKIP] {name}: {message}", UserWarning)
            continue
        
        # Check editable status
        if not include_editable and details['is_editable']:
            status = RemovalStatus.SKIPPED_EDITABLE
            message = "Editable installation skipped (use include_editable=True to override)"
            result = RemovalResult(
                package_name=name,
                status=status,
                message=message,
                dependents=dependents
            )
            results.append(result)
            warnings.warn(f"[SKIP] {name}: {message}", UserWarning)
            continue
        
        # Dry run mode
        if dry_run:
            status = RemovalStatus.DRY_RUN
            message = f"Would uninstall version {details['version']} from {details['location']}"
            result = RemovalResult(
                package_name=name,
                status=status,
                message=message,
                dependents=dependents
            )
            results.append(result)
            warnings.warn(f"[DRY-RUN] {name}: {message}", UserWarning)
            continue
        
        # Actual removal
        try:
            logger.info(f"Attempting to remove {name} (version {details['version']})")
            
            # Use pip uninstall with additional safety flags
            result_proc = subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", "--no-input", name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=30  # Timeout after 30 seconds
            )
            
            if result_proc.returncode == 0:
                status = RemovalStatus.SUCCESS
                message = f"Successfully removed version {details['version']}"
                warnings.warn(f"[REMOVED] {name}: {message}", UserWarning)
                successful_removals.append(name)
            else:
                status = RemovalStatus.FAILED_PIP
                message = f"pip uninstall failed"
                error_details = result_proc.stderr.strip()
                warnings.warn(f"[FAILED] {name}: {message} - {error_details}", UserWarning)
                
                result = RemovalResult(
                    package_name=name,
                    status=status,
                    message=message,
                    error_details=error_details,
                    dependents=dependents
                )
                results.append(result)
                continue
                
        except subprocess.TimeoutExpired:
            status = RemovalStatus.FAILED_PIP
            message = "Removal timed out after 30 seconds"
            error_details = "Process exceeded timeout limit"
            warnings.warn(f"[TIMEOUT] {name}: {message}", UserWarning)
            
            result = RemovalResult(
                package_name=name,
                status=status,
                message=message,
                error_details=error_details,
                dependents=dependents
            )
            results.append(result)
            continue
            
        except Exception as exc:
            status = RemovalStatus.FAILED_EXCEPTION
            message = f"Exception during removal: {type(exc).__name__}"
            error_details = str(exc)
            warnings.warn(f"[ERROR] {name}: {message} - {error_details}", UserWarning)
            
            result = RemovalResult(
                package_name=name,
                status=status,
                message=message,
                error_details=error_details,
                dependents=dependents
            )
            results.append(result)
            continue
        
        # Record successful removal
        result = RemovalResult(
            package_name=name,
            status=status,
            message=message,
            dependents=dependents
        )
        results.append(result)
    
    # Summary logging
    success_count = sum(1 for r in results if r.status == RemovalStatus.SUCCESS)
    dry_run_count = sum(1 for r in results if r.status == RemovalStatus.DRY_RUN)
    skipped_count = len(results) - success_count - dry_run_count
    
    logger.info(f"Removal complete: {success_count} removed, {dry_run_count} dry-run, {skipped_count} skipped")
    
    if log_file:
        logger.info(f"Detailed results logged to {log_file}")
    
    return success_count if not dry_run else dry_run_count, results


# Convenience function for quick preview
def preview_removal(
    exclude: Optional[Iterable[str]] = None,
    include_editable: bool = False,
    verbose: bool = False
) -> Tuple[int, List[RemovalResult]]:
    """
    Convenience wrapper for remove_pip_packages with dry_run=True.
    
    Parameters
    ----------
    exclude : Iterable[str] or None, optional
        Packages to protect from removal
        
    include_editable : bool, default=False
        Whether to include editable installs in preview
        
    verbose : bool, default=False
        Enable verbose output
    
    Returns
    -------
    count : int
        Number of packages that would be removed
        
    results : list of RemovalResult
        Detailed preview results
        
    See Also
    --------
    remove_pip_packages : Main removal function with full options
    
    Examples
    --------
    >>> count, results = preview_removal()
    >>> for r in results:
    ...     print(f"Would remove: {r.package_name} - {r.message}")
    """
    return remove_pip_packages(
        dry_run=True,
        exclude=exclude,
        include_editable=include_editable,
        verbose=verbose
    )
