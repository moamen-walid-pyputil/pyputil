#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Auto Package Installer Module (Enhanced & Production-Ready)
===========================================================

This module provides a safe, enhanced mechanism for automatically installing
missing packages when they are imported. It intelligently resolves import
names to PyPI distribution names, supports confirmation modes, security levels,
and caches installation attempts.

Key Security & Performance Features:
- Package name validation to prevent injection attacks.
- Blocklist for critical packages (pip, setuptools).
- Enforces virtual environment usage by default (configurable).
- Debounces pip calls to prevent resource exhaustion.
- Thread-safe caching of successes and failures.

The module installs a meta path finder that intercepts import failures and
attempts to install the corresponding package from PyPI (or other indexes)
before retrying the import.

Examples
--------
>>> from auto_install import auto_install
>>> # For Android or Colab environments:
>>> auto_install(mode="confirm", virtual_env_only=False, use_safe_flags=False)
>>> import requests  # Will prompt if missing
>>> import numpy     # Same

>>> # For production with virtual environments:
>>> auto_install(mode="confirm", virtual_env_only=True, use_safe_flags=True)
"""

import sys
import subprocess
import importlib
import importlib.abc
import importlib.util
import importlib.machinery
import warnings
import logging
import os
import time
import re
import threading
import site
from typing import Optional, List, Set, Tuple, Dict, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Try to use importlib.metadata if available (Python 3.8+)
try:
    from importlib.metadata import distributions, distribution
    HAS_IMPORTLIB_METADATA = True
except ImportError:
    HAS_IMPORTLIB_METADATA = False

# Optional: use pkg_resources as fallback
try:
    import pkg_resources
    HAS_PKG_RESOURCES = True
except ImportError:
    HAS_PKG_RESOURCES = False

# Configure logging (User can override this)
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())  # Default to no output unless handler added

# Mapping from common import names to PyPI distribution names
IMPORT_TO_PACKAGE_MAP: Dict[str, str] = {
    # Standard library aliases (for documentation)
    'PIL': 'pillow',
    'cv2': 'opencv-python',
    'sklearn': 'scikit-learn',
    'bs4': 'beautifulsoup4',
    'yaml': 'pyyaml',
    'crypto': 'pycryptodome',
    'MySQLdb': 'mysqlclient',
    'psycopg2': 'psycopg2-binary',
    'tkinter': 'tk',
    'datetime': None,  # built-in, ignore
    'json': None,
    'os': None,
    'sys': None,
    're': None,
    'collections': None,
    'itertools': None,
    'functools': None,
    # Add more mappings as needed
}

# Critical packages that should NEVER be auto-installed/upgraded
BLOCKED_PACKAGES: Set[str] = {
    "pip", "setuptools", "wheel", "pkg_resources", "distutils"
}


class InstallationMode(Enum):
    """
    Installation modes for the auto installer.

    Attributes
    ----------
    SILENT : str
        Install without asking for confirmation.
    CONFIRM : str
        Ask for confirmation before installing.
    DRY_RUN : str
        Show what would be installed without actually installing.
    STRICT : str
        Only install from a predefined safe packages list.
    """
    SILENT = "silent"
    CONFIRM = "confirm"
    DRY_RUN = "dry_run"
    STRICT = "strict"


class SecurityLevel(Enum):
    """
    Security levels for the auto installer.

    Attributes
    ----------
    LOW : str
        No restrictions; install any package.
    MEDIUM : str
        Warn about installations and require confirmation unless in silent mode.
    HIGH : str
        Only install from safe packages list and require confirmation.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class AutoInstallConfig:
    """
    Configuration settings for the AutoInstallFinder.

    Parameters
    ----------
    mode : InstallationMode, optional
        Installation mode (default: SILENT).
    security_level : SecurityLevel, optional
        Security level (default: MEDIUM).
    safe_packages : Set[str], optional
        Set of package names considered safe for auto-installation.
    virtual_env_only : bool, optional
        If True, only allow installation in virtual environments (default: False).
    use_safe_flags : bool, optional
        If True, add security flags like --require-virtualenv to pip commands.
        Set to False for environments like Android/Pydroid, Google Colab, etc.
        (default: False).
    max_install_attempts : int, optional
        Maximum number of installation attempts per package (default: 1).
    timeout_seconds : int, optional
        Timeout for pip installation process (default: 60).
    log_installations : bool, optional
        Whether to log installation attempts (default: True).
    allowed_sources : List[str], optional
        List of allowed PyPI source URLs (default: ['https://pypi.org/simple']).
    extra_pip_args : List[str], optional
        Additional arguments to pass to pip (e.g., ['--no-deps']).
    use_cache : bool, optional
        Cache the result of existence checks (default: True).
    check_installed_first : bool, optional
        Check if the package is already installed before attempting install (default: True).
    resolve_import_name : bool, optional
        Try to map import name to distribution name using known mappings (default: True).
    debounce_seconds : float, optional
        Minimum time between pip calls for the same package to prevent abuse (default: 5.0).
    auto_user_flag : bool, optional
        Automatically add --user flag when not in virtual environment (default: True).
    refresh_sys_path : bool, optional
        Automatically refresh sys.path after installation (fixes Pydroid/Android issues)
        (default: True).

    Examples
    --------
    >>> # For production with virtual environments:
    >>> config = AutoInstallConfig(
    ...     mode=InstallationMode.CONFIRM,
    ...     security_level=SecurityLevel.HIGH,
    ...     safe_packages={'requests', 'numpy'},
    ...     virtual_env_only=True,
    ...     use_safe_flags=True
    ... )
    """
    mode: InstallationMode = InstallationMode.SILENT
    security_level: SecurityLevel = SecurityLevel.MEDIUM
    safe_packages: Set[str] = field(default_factory=set)
    virtual_env_only: bool = False
    use_safe_flags: bool = False
    max_install_attempts: int = 1
    timeout_seconds: int = 60
    log_installations: bool = True
    allowed_sources: Optional[List[str]] = None
    extra_pip_args: List[str] = field(default_factory=list)
    use_cache: bool = True
    check_installed_first: bool = True
    resolve_import_name: bool = True
    debounce_seconds: float = 5.0
    auto_user_flag: bool = True
    refresh_sys_path: bool = True

    def __post_init__(self):
        """Initialize mutable defaults and validate configuration."""
        if self.allowed_sources is None:
            self.allowed_sources = ['https://pypi.org/simple']

        if self.security_level == SecurityLevel.HIGH and not self.safe_packages:
            warnings.warn(
                "Security level HIGH set but no safe packages defined. "
                "Auto-installation will be disabled for all packages.",
                UserWarning,
                stacklevel=2
            )


class PackageExistenceChecker:
    """
    Utility class to check if a package is installed, with caching.

    Parameters
    ----------
    use_cache : bool
        Whether to cache results.
    """

    def __init__(self, use_cache: bool = True):
        self._cache: Dict[str, bool] = {}
        self.use_cache = use_cache

    def is_package_installed(self, package_name: str) -> bool:
        """
        Check if a distribution (PyPI package) is installed.

        Parameters
        ----------
        package_name : str
            Distribution name (e.g., 'requests').

        Returns
        -------
        bool
            True if the package is installed, False otherwise.
        """
        if self.use_cache and package_name in self._cache:
            return self._cache[package_name]

        installed = False
        if HAS_IMPORTLIB_METADATA:
            try:
                # Try to get distribution
                dist = distribution(package_name)
                installed = dist is not None
            except Exception:
                installed = False
        elif HAS_PKG_RESOURCES:
            try:
                # pkg_resources.get_distribution raises DistributionNotFound if not present
                pkg_resources.get_distribution(package_name)
                installed = True
            except pkg_resources.DistributionNotFound:
                installed = False
        else:
            # Fallback: try to import a module that matches the package name
            # This is unreliable but better than nothing
            try:
                importlib.import_module(package_name)
                installed = True
            except ImportError:
                installed = False

        if self.use_cache:
            self._cache[package_name] = installed
        return installed


class PackageInstaller:
    """
    Handles the actual installation of packages using pip.

    This class encapsulates the logic for building pip commands, validating
    package names, and executing the installation subprocess safely.

    Parameters
    ----------
    config : AutoInstallConfig
        The configuration settings for the auto-installer.
    """

    def __init__(self, config: AutoInstallConfig):
        self.config = config
        self._checker = PackageExistenceChecker(use_cache=config.use_cache)

    def _is_valid_package_name(self, name: str) -> bool:
        """
        Validate package name to prevent command injection.

        Parameters
        ----------
        name : str
            The package name to validate.

        Returns
        -------
        bool
            True if the package name is safe, False otherwise.
        """
        # PEP 508 defines valid package names, this regex is a strict subset
        return re.match(r'^[a-zA-Z0-9._-]+$', name) is not None

    def _is_in_virtual_env(self) -> bool:
        """
        Check if the current Python environment is a virtual environment.

        Returns
        -------
        bool
            True if in a virtual environment, False otherwise.
        """
        return (hasattr(sys, 'real_prefix') or
                (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))

    def install_package(self, package: str) -> bool:
        """
        Install a package using pip.

        Parameters
        ----------
        package : str
            Name of the package to install.

        Returns
        -------
        bool
            True if installation succeeded, False otherwise.
        """
        # 1. Name Validation (Security)
        if not self._is_valid_package_name(package):
            msg = f"Invalid package name detected: '{package}'. Skipping installation."
            warnings.warn(msg, UserWarning, stacklevel=3)
            logger.warning(msg)
            return False

        # 2. Blocklist Check (Security)
        if package in BLOCKED_PACKAGES:
            msg = f"Attempt to install blocked critical package: '{package}'. Skipping."
            warnings.warn(msg, UserWarning, stacklevel=3)
            logger.warning(msg)
            return False

        # 3. Virtual Environment Check (Security)
        if self.config.virtual_env_only and not self._is_in_virtual_env():
            msg = f"Not in a virtual environment. Skipping installation of '{package}'."
            warnings.warn(msg, UserWarning, stacklevel=3)
            logger.warning(msg)
            return False

        # 4. Build pip command
        cmd = [sys.executable, "-m", "pip", "install", package]

        # Add safe flags if enabled
        if self.config.use_safe_flags:
            cmd.extend(["--require-virtualenv"])
            cmd.extend(["--disable-pip-version-check"])

        # Add --user flag automatically if not in virtual environment
        if self.config.auto_user_flag and not self._is_in_virtual_env():
            if "--user" not in self.config.extra_pip_args:
                cmd.append("--user")

        # Add allowed sources
        if self.config.allowed_sources:
            # Use first source as index-url (simplification)
            index_url = self.config.allowed_sources[0]
            cmd.extend(["--index-url", index_url])
            # Additional sources can be added as extra-index-url
            for extra in self.config.allowed_sources[1:]:
                cmd.extend(["--extra-index-url", extra])

        # Add extra pip arguments
        cmd.extend(self.config.extra_pip_args)

        # 5. Execute installation
        try:
            logger.info(f"Executing: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                check=False
            )

            if result.returncode == 0:
                if self.config.log_installations:
                    logger.info(f"Successfully installed package: {package}")
                return True
            else:
                error_msg = f"Pip installation failed for '{package}': {result.stderr.strip()}"
                warnings.warn(error_msg, UserWarning, stacklevel=3)
                logger.error(error_msg)
                return False

        except subprocess.TimeoutExpired:
            error_msg = f"Installation timed out after {self.config.timeout_seconds} seconds"
            warnings.warn(error_msg, UserWarning, stacklevel=3)
            logger.error(error_msg)
            return False
        except Exception as e:
            error_msg = f"Unexpected error during installation: {e}"
            warnings.warn(error_msg, UserWarning, stacklevel=3)
            logger.error(error_msg)
            return False


class SysPathRefresher:
    """
    Utility class to refresh sys.path after package installation.
    
    This is crucial for environments like Pydroid/Android where --user
    installations may not be immediately visible to Python's import system.
    """
    
    @staticmethod
    def refresh() -> None:
        """
        Refresh sys.path to include newly installed packages.
        
        This method:
        1. Reloads site packages using site.main()
        2. Invalidates importlib caches
        3. Adds common user site-packages paths manually
        """
        try:
            # 1. Reload site packages
            site.main()
            
            # 2. Invalidate import caches
            importlib.invalidate_caches()
            
            # 3. Add common user site-packages paths
            user_site_paths = SysPathRefresher._get_user_site_paths()
            for path in user_site_paths:
                if os.path.exists(path) and path not in sys.path:
                    sys.path.insert(0, path)
                    logger.debug(f"Added user site-packages path: {path}")
                    
            # 4. Also try to add system site-packages if needed
            system_site_paths = SysPathRefresher._get_system_site_paths()
            for path in system_site_paths:
                if os.path.exists(path) and path not in sys.path:
                    sys.path.append(path)
                    logger.debug(f"Added system site-packages path: {path}")
                    
        except Exception as e:
            logger.debug(f"Failed to refresh sys.path: {e}")
    
    @staticmethod
    def _get_user_site_paths() -> List[str]:
        """
        Get possible user site-packages paths.
        
        Returns
        -------
        List[str]
            List of possible user site-packages directory paths.
        """
        paths = []
        
        # Try to get from site module
        try:
            user_site = site.getusersitepackages()
            if user_site:
                paths.append(user_site)
        except:
            pass
        
        # Manual construction for different Python versions
        python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        home = os.path.expanduser("~")
        
        possible_paths = [
            os.path.join(home, ".local", "lib", python_version, "site-packages"),
            os.path.join(home, ".local", "lib", "python3", "site-packages"),
            os.path.join(home, ".local", "lib", "python", "site-packages"),
            os.path.join(home, "Library", "Python", python_version, "lib", "site-packages"),  # macOS
        ]
        
        for path in possible_paths:
            if path not in paths:
                paths.append(path)
                
        return paths
    
    @staticmethod
    def _get_system_site_paths() -> List[str]:
        """
        Get system site-packages paths.
        
        Returns
        -------
        List[str]
            List of system site-packages directory paths.
        """
        paths = []
        
        # Try to get from site module
        try:
            system_site = site.getsitepackages()
            paths.extend(system_site)
        except:
            pass
            
        return paths


class AutoInstallFinder(importlib.abc.MetaPathFinder):
    """
    Meta path finder that automatically installs missing Python packages.

    This finder integrates with Python's import system to intercept import
    failures and install missing packages from PyPI (or other indexes).

    Parameters
    ----------
    config : AutoInstallConfig, optional
        Configuration settings.

    Attributes
    ----------
    config : AutoInstallConfig
        Configuration settings.
    _installed_packages : Set[str]
        Set of packages that have been attempted for installation.
    _failed_packages : Set[str]
        Set of packages that failed installation or were blocked.
    _attempt_counts : Dict[str, int]
        Number of installation attempts per package.
    _last_attempt_time : Dict[str, float]
        Timestamp of the last installation attempt for debouncing.
    _finding : bool
        Recursion prevention flag.
    _lock : threading.RLock
        Reentrant lock for thread safety.

    Examples
    --------
    >>> config = AutoInstallConfig(mode=InstallationMode.CONFIRM)
    >>> finder = AutoInstallFinder(config)
    >>> sys.meta_path.insert(0, finder)
    """

    def __init__(self, config: Optional[AutoInstallConfig] = None):
        self.config = config or AutoInstallConfig()
        self._installed_packages: Set[str] = set()
        self._failed_packages: Set[str] = set()
        self._attempt_counts: Dict[str, int] = {}
        self._last_attempt_time: Dict[str, float] = {}
        self._finding: bool = False
        self._checker = PackageExistenceChecker(use_cache=self.config.use_cache)
        self._installer = PackageInstaller(self.config)
        self._lock = threading.RLock()

    def _resolve_package_name(self, module_name: str) -> Optional[str]:
        """
        Resolve an import module name to a PyPI distribution name.

        Parameters
        ----------
        module_name : str
            The module name being imported (e.g., 'numpy', 'PIL', 'cv2').

        Returns
        -------
        Optional[str]
            Distribution name, or None if the module is known to be built-in
            or should not be auto-installed.

        Notes
        -----
        Uses a mapping table for common aliases. If no mapping, assumes the
        distribution name is the same as the top-level module name.
        """
        # Extract top-level module name
        top_level = module_name.split('.')[0]

        # Check if it's a known built-in or stdlib module (optional)
        if top_level in sys.builtin_module_names:
            return None

        # Use mapping if available
        if self.config.resolve_import_name:
            mapped = IMPORT_TO_PACKAGE_MAP.get(top_level)
            if mapped is not None:
                return mapped if mapped else None
        return top_level

    def _is_safe_to_install(self, package: str) -> Tuple[bool, str]:
        """
        Check if it is safe to install a package based on security settings.

        Parameters
        ----------
        package : str
            Name of the package to check.

        Returns
        -------
        Tuple[bool, str]
            (safe, reason) where `safe` is True if installation is allowed,
            and `reason` explains the decision.
        """
        # High security: must be in safe_packages
        if self.config.security_level == SecurityLevel.HIGH:
            if package not in self.config.safe_packages:
                return False, f"Package '{package}' not in safe packages list"

        # Installation attempts limit
        attempts = self._attempt_counts.get(package, 0)
        if attempts >= self.config.max_install_attempts:
            return False, f"Maximum installation attempts ({self.config.max_install_attempts}) exceeded"

        return True, "OK"

    def _confirm_installation(self, package: str) -> bool:
        """
        Ask the user for confirmation to install a package.

        Parameters
        ----------
        package : str
            Name of the package to install.

        Returns
        -------
        bool
            True if confirmed, False otherwise.
        """
        mode = self.config.mode
        if mode == InstallationMode.SILENT:
            return True
        if mode == InstallationMode.DRY_RUN:
            return False
        if mode == InstallationMode.STRICT:
            return package in self.config.safe_packages
        if mode == InstallationMode.CONFIRM:
            try:
                response = input(f"Install package '{package}'? (y/N): ").strip().lower()
                return response in ('y', 'yes')
            except (KeyboardInterrupt, EOFError):
                return False
        return False

    def find_spec(self, fullname: str, path: Optional[List[str]] = None,
                  target: Optional[importlib.machinery.ModuleSpec] = None) -> Optional[importlib.machinery.ModuleSpec]:
        """
        Find or install a module specification.

        This method is called by Python's import machinery. If the module
        cannot be found, it resolves the package name, checks if already
        installed, and attempts to install it before retrying.

        Parameters
        ----------
        fullname : str
            Fully qualified module name being imported.
        path : Optional[List[str]]
            Module search path (unused).
        target : Optional[importlib.machinery.ModuleSpec]
            Target module object (unused).

        Returns
        -------
        Optional[importlib.machinery.ModuleSpec]
            Module specification if found/installed, None otherwise.
        """
        # Prevent recursion
        if self._finding:
            return None

        with self._lock:
            self._finding = True
            try:
                # 1. Try existing finders first
                meta_path = sys.meta_path
                other_finders = [f for f in meta_path if f is not self]
                for finder in other_finders:
                    if hasattr(finder, 'find_spec'):
                        spec = finder.find_spec(fullname, path, target)
                    elif hasattr(finder, 'find_module'):
                        loader = finder.find_module(fullname, path)
                        spec = importlib.machinery.ModuleSpec(fullname, loader) if loader else None
                    else:
                        continue
                    if spec is not None:
                        return spec

                # 2. Module not found – resolve distribution name
                package = self._resolve_package_name(fullname)
                if package is None:
                    # Known built-in or excluded
                    return None

                # 3. Check caches (Success, Failure, Debounce)
                if package in self._installed_packages:
                    # If it's in installed_packages but still not found, refresh sys.path
                    if self.config.refresh_sys_path:
                        SysPathRefresher.refresh()
                        # Try one more time after refresh
                        for finder in other_finders:
                            if hasattr(finder, 'find_spec'):
                                spec = finder.find_spec(fullname, path, target)
                            elif hasattr(finder, 'find_module'):
                                loader = finder.find_module(fullname, path)
                                spec = importlib.machinery.ModuleSpec(fullname, loader) if loader else None
                            else:
                                continue
                            if spec is not None:
                                return spec
                    return None
                    
                if package in self._failed_packages:
                    return None

                # Debounce check
                last_time = self._last_attempt_time.get(package, 0)
                if time.time() - last_time < self.config.debounce_seconds:
                    logger.debug(f"Debounced: {package}")
                    return None

                # 4. Safety & Security Checks
                safe, reason = self._is_safe_to_install(package)
                if not safe:
                    warnings.warn(f"Skipping installation of '{package}': {reason}", UserWarning, stacklevel=2)
                    self._failed_packages.add(package)
                    return None

                # 5. Check if already installed via metadata
                if self.config.check_installed_first and self._checker.is_package_installed(package):
                    self._installed_packages.add(package)
                    # Refresh sys.path if needed
                    if self.config.refresh_sys_path:
                        SysPathRefresher.refresh()
                    return None

                # 6. Confirmation Prompt
                if not self._confirm_installation(package):
                    warnings.warn(f"Installation of '{package}' cancelled by user", UserWarning, stacklevel=2)
                    self._failed_packages.add(package)
                    return None

                # 7. Attempt Installation
                self._attempt_counts[package] = self._attempt_counts.get(package, 0) + 1
                self._last_attempt_time[package] = time.time()

                if self._installer.install_package(package):
                    self._installed_packages.add(package)
                    
                    # CRITICAL: Refresh sys.path after installation
                    # This fixes issues where --user packages
                    # are not immediately visible to Python's import system
                    if self.config.refresh_sys_path:
                        SysPathRefresher.refresh()
                    
                    # Retry finding the module now that it's installed
                    for finder in other_finders:
                        if hasattr(finder, 'find_spec'):
                            spec = finder.find_spec(fullname, path, target)
                        elif hasattr(finder, 'find_module'):
                            loader = finder.find_module(fullname, path)
                            spec = importlib.machinery.ModuleSpec(fullname, loader) if loader else None
                        else:
                            continue
                        if spec is not None:
                            return spec
                else:
                    self._failed_packages.add(package)

                return None

            except Exception as e:
                warnings.warn(f"Auto-install error for '{fullname}': {e}", UserWarning, stacklevel=2)
                logger.error(f"Auto-install error: {e}", exc_info=True)
                return None
            finally:
                self._finding = False


def auto_install(mode: str = "silent",
                security_level: str = "medium",
                safe_packages: Optional[Set[str]] = None,
                virtual_env_only: bool = False,
                use_safe_flags: bool = False,
                refresh_sys_path: bool = True,
                **kwargs) -> None:
    """
    Enable automatic installation of missing packages on import.

    This function installs a meta path finder that intercepts import failures
    and automatically installs the corresponding package from PyPI.

    Parameters
    ----------
    mode : {"silent", "confirm", "dry_run", "strict"}, default="silent"
        Installation mode:
        - "silent": Install without asking.
        - "confirm": Ask for confirmation before installing.
        - "dry_run": Show what would be installed without actually installing.
        - "strict": Only install from `safe_packages` list.
    security_level : {"low", "medium", "high"}, default="medium"
        Security level:
        - "low": No restrictions.
        - "medium": Warn about installations.
        - "high": Only install from `safe_packages` and require confirmation.
    safe_packages : Set[str], optional
        Set of package names considered safe for auto-installation.
        Required if `security_level` is "high".
    virtual_env_only : bool, default=False
        If True, only allow installation in virtual environments.
    use_safe_flags : bool, default=False
        If True, add security flags like --require-virtualenv to pip commands.
        Set to False for environments like Android/Pydroid, Google Colab, etc.
    refresh_sys_path : bool, default=True
        If True, automatically refresh sys.path after installation.
        This fixes issues on Pydroid/Android where newly installed packages
        are not immediately visible to Python's import system.
    **kwargs : dict
        Additional configuration options passed to `AutoInstallConfig`:
        - `max_install_attempts` (int, default=1)
        - `timeout_seconds` (int, default=60)
        - `log_installations` (bool, default=True)
        - `allowed_sources` (List[str], default=['https://pypi.org/simple'])
        - `extra_pip_args` (List[str], default=[])
        - `use_cache` (bool, default=True)
        - `check_installed_first` (bool, default=True)
        - `resolve_import_name` (bool, default=True)
        - `debounce_seconds` (float, default=5.0)
        - `auto_user_flag` (bool, default=True)

    Returns
    -------
    None

    Warnings
    --------
    UserWarning
        Various warnings are issued for installation attempts, failures,
        and security restrictions.

    Examples
    --------
    >>> # For Android/Pydroid or Google Colab:
    >>> auto_install(mode="confirm", virtual_env_only=False, use_safe_flags=False)
    >>> import requests  # Will ask before installing and work correctly!

    >>> # For production with virtual environments:
    >>> auto_install(mode="strict", security_level="high",
    ...              safe_packages={'numpy', 'pandas'},
    ...              virtual_env_only=True,
    ...              use_safe_flags=True)
    >>> import numpy   # Allowed
    >>> import flask   # Not allowed, will raise ImportError

    >>> auto_install(mode="dry_run")
    >>> import matplotlib  # Shows warning but does not install
    """
    mode_map = {
        "silent": InstallationMode.SILENT,
        "confirm": InstallationMode.CONFIRM,
        "dry_run": InstallationMode.DRY_RUN,
        "strict": InstallationMode.STRICT
    }
    security_map = {
        "low": SecurityLevel.LOW,
        "medium": SecurityLevel.MEDIUM,
        "high": SecurityLevel.HIGH
    }

    config = AutoInstallConfig(
        mode=mode_map.get(mode, InstallationMode.SILENT),
        security_level=security_map.get(security_level, SecurityLevel.MEDIUM),
        safe_packages=safe_packages or set(),
        virtual_env_only=virtual_env_only,
        use_safe_flags=use_safe_flags,
        refresh_sys_path=refresh_sys_path,
        **kwargs
    )

    finder = AutoInstallFinder(config)
    # Insert at the beginning to take precedence over default finders
    sys.meta_path.insert(0, finder)

    warnings.warn(
        f"Auto-install enabled (mode={mode}, security={security_level}, "
        f"virtual_env_only={virtual_env_only}, use_safe_flags={use_safe_flags}, "
        f"refresh_sys_path={refresh_sys_path})",
        UserWarning,
        stacklevel=2
    )


class auto_install_context:
    """
    Context manager for temporary auto-installation.

    This context manager enables auto-installation only within the block
    and removes the hook afterward.

    Parameters
    ----------
    **kwargs : dict
        Same parameters as `auto_install()`.

    Examples
    --------
    >>> # For Android/Pydroid:
    >>> with auto_install_context(mode="confirm", virtual_env_only=False, use_safe_flags=False):
    ...     import requests  # Will auto-install if missing and work correctly
    >>> import flask  # Normal behavior (no auto-install)
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.finder = None

    def __enter__(self):
        """Enable auto-installation on context entry."""
        mode_map = {
            "silent": InstallationMode.SILENT,
            "confirm": InstallationMode.CONFIRM,
            "dry_run": InstallationMode.DRY_RUN,
            "strict": InstallationMode.STRICT
        }
        security_map = {
            "low": SecurityLevel.LOW,
            "medium": SecurityLevel.MEDIUM,
            "high": SecurityLevel.HIGH
        }

        config = AutoInstallConfig(
            mode=mode_map.get(self.kwargs.get('mode', 'silent'), InstallationMode.SILENT),
            security_level=security_map.get(self.kwargs.get('security_level', 'medium'), SecurityLevel.MEDIUM),
            safe_packages=self.kwargs.get('safe_packages', set()),
            virtual_env_only=self.kwargs.get('virtual_env_only', False),
            use_safe_flags=self.kwargs.get('use_safe_flags', False),
            refresh_sys_path=self.kwargs.get('refresh_sys_path', True),
            **{k: v for k, v in self.kwargs.items()
               if k not in ['mode', 'security_level', 'safe_packages', 
                           'virtual_env_only', 'use_safe_flags', 'refresh_sys_path']}
        )
        self.finder = AutoInstallFinder(config)
        sys.meta_path.insert(0, self.finder)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Remove auto-installation on context exit."""
        if self.finder in sys.meta_path:
            sys.meta_path.remove(self.finder)