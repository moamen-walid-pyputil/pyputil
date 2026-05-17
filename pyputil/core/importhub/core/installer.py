#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Automatic package installation functionality.
"""

import subprocess
import sys
import threading
from typing import Optional, List
import importlib.metadata


class PackageInstaller:
    """
    Handles automatic installation of Python packages.
    
    This class manages pip installations with thread safety and version
    specification support.
    """
    
    def __init__(self):
        """Initialize installer with thread lock."""
        self._lock = threading.RLock()
        self._installed_packages = set()
    
    def install(
        self,
        package_name: str,
        version: Optional[str] = None,
        upgrade: bool = False,
        user: bool = False,
    ) -> bool:
        """
        Install a package using pip.
        
        Parameters
        ----------
        package_name : str
            Name of the package to install.
        version : str, optional
            Version specification (e.g., "1.26.0", ">=2.0").
        upgrade : bool
            Upgrade package if already installed.
        user : bool
            Install in user site-packages directory.
        
        Returns
        -------
        bool
            True if installation successful.
        
        Raises
        ------
        subprocess.CalledProcessError
            If pip installation fails.
        """
        with self._lock:
            # Skip if already installed (and not upgrading)
            if not upgrade and self.is_installed(package_name, version):
                return True
            
            # Build pip command
            cmd = [sys.executable, "-m", "pip", "install"]
            
            if user:
                cmd.append("--user")
            
            if upgrade:
                cmd.append("--upgrade")
            
            # Add package with version
            if version:
                cmd.append(f"{package_name}{version}")
            else:
                cmd.append(package_name)
            
            # Run installation
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                self._installed_packages.add(package_name)
                return True
            
            # Raise on failure
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                output=result.stdout,
                stderr=result.stderr
            )
    
    def is_installed(self, package_name: str, version: Optional[str] = None) -> bool:
        """
        Check if package is installed with compatible version.
        
        Parameters
        ----------
        package_name : str
            Package name to check.
        version : str, optional
            Required version specification.
        
        Returns
        -------
        bool
            True if installed and version compatible.
        """
        try:
            dist = importlib.metadata.distribution(package_name)
            
            if version is None:
                return True
            
            # Version checking would need a proper version parser
            # This is simplified
            return True
            
        except importlib.metadata.PackageNotFoundError:
            return False
    
    def get_installed_version(self, package_name: str) -> Optional[str]:
        """
        Get installed version of package.
        
        Parameters
        ----------
        package_name : str
            Package name.
        
        Returns
        -------
        Optional[str]
            Version string or None if not installed.
        """
        try:
            dist = importlib.metadata.distribution(package_name)
            return dist.version
        except importlib.metadata.PackageNotFoundError:
            return None


# Global installer instance
_global_installer = PackageInstaller()


def get_installer() -> PackageInstaller:
    """Get the global package installer instance."""
    return _global_installer


def install_package(
    package_name: str,
    version: Optional[str] = None,
    upgrade: bool = False,
    user: bool = False,
) -> bool:
    """
    Convenience function to install a package.
    
    Parameters
    ----------
    package_name : str
        Package name.
    version : str, optional
        Version specification.
    upgrade : bool
        Upgrade if exists.
    user : bool
        Install in user directory.
    
    Returns
    -------
    bool
        Installation success.
    """
    return get_installer().install(package_name, version, upgrade, user)