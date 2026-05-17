#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Package Installer Module

This module provides a robust interface to Python's package installer (pip).
It wraps common pip commands with error handling, version checking, and
detailed logging. The main class `PackageInstaller` allows installing,
uninstalling, upgrading, and querying packages safely.

Examples
--------
>>> installer = PackageInstaller("requests")
>>> if not installer.is_installed():
...     installer.install()
>>> if installer.check_upgrade():
...     installer.upgrade()
"""

import subprocess
import sys
import logging
from typing import Optional, Union, List, Dict, Any
from importlib.metadata import version as get_version, PackageNotFoundError
from packaging.version import Version, InvalidVersion
from pathlib import Path
from .exceptions import (
    PackageInstallerExecutionError,
    PackageInstallerTimeout,
    PackageInstallerNotFound,
    PackageInstallerError,
)

# Configure logging for the module
logger = logging.getLogger(__name__)


class PackageInstaller:
    """
    A class to manage Python packages using pip with error handling.

    Parameters
    ----------
    package_name : str
        The name of the package to manage (as recognized by PyPI/pip).
    pip_path : str or Path, optional
        Path to the pip executable. If not provided, it defaults to
        `sys.executable -m pip`, which ensures using the current interpreter's pip.
    timeout : int, optional
        Timeout in seconds for pip subprocess calls. Default is 60.

    Attributes
    ----------
    package_name : str
        The name of the package.
    pip_command : List[str]
        The base pip command (e.g., ['python', '-m', 'pip']).
    timeout : int
        Timeout for subprocess calls.

    Examples
    --------
    >>> installer = PackageInstaller("numpy")
    >>> if not installer.is_installed():
    ...     installer.install(version="1.21.0")
    >>> print(installer.get_version())
    '1.21.0'
    """

    def __init__(
        self,
        package_name: str,
        pip_path: Optional[Union[str, Path]] = None,
        timeout: int = 60,
    ):
        self.package_name = package_name.strip().lower()
        self.timeout = timeout

        if pip_path is None:
            # Use the pip associated with the current Python interpreter
            self.pip_command = [sys.executable, "-m", "pip"]
        else:
            self.pip_command = [str(pip_path)]

        logger.debug(f"Initialized PackageInstaller for {self.package_name}")

    def _run_pip(
        self, args: List[str], capture_output: bool = True, check: bool = False
    ) -> subprocess.CompletedProcess:
        """
        Internal method to run a pip command with error handling.

        Parameters
        ----------
        args : List[str]
            Arguments to pass to pip (excluding the base command).
        capture_output : bool, optional
            If True, capture stdout and stderr. Default True.
        check : bool, optional
            If True, raise CalledProcessError on non-zero exit. Default False.

        Returns
        -------
        subprocess.CompletedProcess
            The result of the subprocess run.

        Raises
        ------
        PackageInstallerError
            If subprocess fails due to timeout, not found, or other errors.
        """
        cmd = self.pip_command + args
        logger.debug(f"Running pip command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                timeout=self.timeout,
                check=check,
            )
            return result
        except subprocess.TimeoutExpired as e:
            raise PackageInstallerTimeout(
                f"Pip command timed out after {self.timeout} seconds: {' '.join(cmd)}"
            ) from e
        except subprocess.CalledProcessError as e:
            # This will only happen if check=True, but we keep it for completeness
            raise PackageInstallerExecutionError(
                f"Pip command failed with exit code {e.returncode}: {e.stderr}"
            ) from e
        except FileNotFoundError as e:
            raise PackageInstallerNotFound(
                f"Pip executable not found: {self.pip_command[0]}"
            ) from e
        except Exception as e:
            raise PackageInstallerError(f"Unexpected error running pip: {e}") from e

    def is_installed(self) -> bool:
        """
        Check if the package is currently installed in the environment.

        Returns
        -------
        bool
            True if the package is installed, False otherwise.

        Notes
        -----
        This uses importlib.metadata to check installation, which is more
        reliable than parsing pip list output.
        """
        try:
            get_version(self.package_name)
            return True
        except PackageNotFoundError:
            return False

    def get_version(self) -> Optional[str]:
        """
        Retrieve the installed version of the package.

        Returns
        -------
        str or None
            The version string if installed, otherwise None.

        Raises
        ------
        InvalidVersionError
            If the installed version string is malformed (optional, but
            the method currently returns None and logs a warning).
        """
        try:
            return get_version(self.package_name)
        except PackageNotFoundError:
            return None
        except InvalidVersion as e:
            logger.warning(f"Installed version for {self.package_name} is invalid: {e}")
            return None

    def get_latest_version(self, pre: bool = False) -> Optional[str]:
        """
        Fetch the latest available version of the package from PyPI.

        Parameters
        ----------
        pre : bool, optional
            If True, include pre-release and development versions.
            Default False (only stable versions).

        Returns
        -------
        str or None
            The latest version string, or None if unable to retrieve.

        Raises
        ------
        PackageInstallerError
            If network issues or invalid metadata prevent retrieval.
        """
        # Use pip's index command to get the latest version
        args = ["index", "versions", self.package_name]
        if pre:
            args.append("--pre")

        result = self._run_pip(args)

        if result.returncode != 0:
            logger.error(f"Failed to fetch latest version: {result.stderr}")
            raise PackageInstallerError(
                f"Could not retrieve latest version for {self.package_name}"
            )

        # Parse output: pip index versions returns lines like "Available versions: 1.2.3, 1.2.4"
        for line in result.stdout.splitlines():
            if "Available versions:" in line:
                versions_str = line.split(":", 1)[1].strip()
                # Split by commas and strip whitespace
                versions = [v.strip() for v in versions_str.split(",")]
                # Return the first one? Actually they are listed in descending order?
                # According to pip documentation, they are listed in reverse chronological order (newest first).
                if versions:
                    return versions[0]
        # If format unknown, fallback to parsing JSON (alternative approach)
        # For simplicity, we'll raise an error
        raise PackageInstallerError(
            f"Could not parse latest version from pip output: {result.stdout}"
        )

    def check_upgrade(self, pre: bool = False) -> bool:
        """
        Determine if a newer version of the package is available.

        Parameters
        ----------
        pre : bool, optional
            If True, consider pre-release versions as candidates for upgrade.

        Returns
        -------
        bool
            True if a newer version exists, False otherwise.

        Raises
        ------
        PackageInstallerError
            If unable to retrieve installed or latest version.
        """
        current = self.get_version()
        if current is None:
            logger.info(f"{self.package_name} is not installed; no upgrade check.")
            return False

        latest = self.get_latest_version(pre=pre)
        if latest is None:
            raise PackageInstallerError(
                f"Could not determine latest version for {self.package_name}"
            )

        try:
            return Version(latest) > Version(current)
        except InvalidVersion as e:
            raise PackageInstallerError(
                f"Version comparison failed: current={current}, latest={latest}"
            ) from e

    def install(
        self,
        version: Optional[str] = None,
        upgrade: bool = False,
        pre: bool = False,
        user: bool = False,
        requirements: Optional[Union[str, Path]] = None,
        extra_args: Optional[List[str]] = None,
    ) -> bool:
        """
        Install the package using pip.

        Parameters
        ----------
        version : str, optional
            Specific version to install (e.g., "1.2.3"). If not given,
            the latest version (matching pre setting) is installed.
        upgrade : bool, optional
            If True, upgrade the package if already installed (equivalent to
            `pip install --upgrade`). Default False.
        pre : bool, optional
            If True, include pre-release and development versions. Default False.
        user : bool, optional
            If True, install to the user site directory (`pip install --user`).
            Default False.
        requirements : str or Path, optional
            Path to a requirements file to install from. If provided, the
            package_name is ignored and the file is used.
        extra_args : list of str, optional
            Additional arguments to pass directly to pip.

        Returns
        -------
        bool
            True if installation succeeded.

        Raises
        ------
        PackageInstallerError
            If installation fails for any reason (e.g., network, conflict,
            permission).
        """
        args = ["install"]

        if requirements:
            args.extend(["-r", str(requirements)])
        else:
            pkg_spec = self.package_name
            if version:
                pkg_spec += f"=={version}"
            args.append(pkg_spec)

        if upgrade:
            args.append("--upgrade")
        if pre:
            args.append("--pre")
        if user:
            args.append("--user")
        if extra_args:
            args.extend(extra_args)

        # Add --quiet to reduce output noise? We'll capture and log if needed.
        result = self._run_pip(args, capture_output=True, check=False)

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            logger.error(f"Installation failed: {error_msg}")
            raise PackageInstallerError(
                f"Failed to install {self.package_name}: {error_msg}"
            )

        logger.info(f"Successfully installed {self.package_name}")
        return True

    def uninstall(
        self, confirm: bool = True, extra_args: Optional[List[str]] = None
    ) -> bool:
        """
        Uninstall the package using pip.

        Parameters
        ----------
        confirm : bool, optional
            If True, pip will ask for confirmation (interactive). To bypass,
            set to False (adds `-y` flag). Default True.
        extra_args : list of str, optional
            Additional arguments to pass directly to pip.

        Returns
        -------
        bool
            True if uninstallation succeeded.

        Raises
        ------
        PackageInstallerError
            If uninstallation fails (e.g., package not installed, permission).
        """
        if not self.is_installed():
            logger.warning(f"{self.package_name} is not installed; nothing to uninstall.")
            return False

        args = ["uninstall", self.package_name]
        if not confirm:
            args.append("-y")
        if extra_args:
            args.extend(extra_args)

        result = self._run_pip(args, capture_output=True, check=False)

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            logger.error(f"Uninstallation failed: {error_msg}")
            raise PackageInstallerError(
                f"Failed to uninstall {self.package_name}: {error_msg}"
            )

        logger.info(f"Successfully uninstalled {self.package_name}")
        return True

    def upgrade(
        self,
        pre: bool = False,
        user: bool = False,
        extra_args: Optional[List[str]] = None,
    ) -> bool:
        """
        Upgrade the package to the latest available version.

        This is a convenience method equivalent to calling
        `install(upgrade=True, pre=pre, user=user, extra_args=extra_args)`.

        Parameters
        ----------
        pre : bool, optional
            If True, include pre-release versions in the upgrade.
        user : bool, optional
            If True, install to the user site directory.
        extra_args : list of str, optional
            Additional arguments to pass directly to pip.

        Returns
        -------
        bool
            True if upgrade succeeded.

        Raises
        ------
        PackageInstallerError
            If upgrade fails.
        """
        return self.install(upgrade=True, pre=pre, user=user, extra_args=extra_args)

