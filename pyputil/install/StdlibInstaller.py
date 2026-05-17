#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Standard Library Module Installer
================================
A robust tool for installing Python standard library modules from the CPython repository.
Supports installing entire packages, single modules, and managing installed packages.
"""

import sys
import sysconfig
import shutil
import urllib.request
import urllib.error
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Union, Any
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StdlibInstaller:
    """
    Install and manage Python standard library modules from CPython repository.
    
    This class provides functionality to install, update, and remove standard library
    modules by fetching them directly from the official CPython GitHub repository.
    It handles both single files and entire packages/directories.
    
    Parameters
    ----------
    repo_api : str, optional
        Custom GitHub API URL for CPython contents (default: uses official repo)
    timeout : int, optional
        Timeout in seconds for network requests (default: 30)
        
    Attributes
    ----------
    site_packages : Path
        Path to the site-packages directory
    repo_api : str
        Base URL for GitHub API requests
    py_version : str
        Current Python version (major.minor)
    timeout : int
        Timeout for network requests
        
    Examples
    --------
    >>> installer = StdlibInstaller()
    >>> 
    >>> # Install a package
    >>> installer.install('json')
    >>> 
    >>> # Install a specific version
    >>> installer.install('xml', version='3.9')
    >>> 
    >>> # Update an installed package
    >>> installer.update('json')
    >>> 
    >>> # Remove a package
    >>> installer.remove('json')
    >>> 
    >>> # Install multiple packages
    >>> installer.install_bulk(['csv', 'sqlite3', 'datetime'])
    """
    
    def __init__(self, repo_api: Optional[str] = None, timeout: int = 30):
        """
        Initialize the StdlibInstaller.
        
        Parameters
        ----------
        repo_api : str, optional
            Custom GitHub API URL for CPython contents
        timeout : int, optional
            Timeout in seconds for network requests (default: 30)
            
        Raises
        ------
        RuntimeError
            If site-packages directory cannot be accessed or created
        ValueError
            If timeout is not positive
        """
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
            
        self.timeout = timeout
        
        # Get site-packages path
        try:
            self.site_packages = Path(sysconfig.get_paths()["purelib"])
            logger.debug(f"Site-packages directory: {self.site_packages}")
        except KeyError as e:
            raise RuntimeError(f"Could not determine site-packages location: {e}")
        
        # Ensure site-packages exists
        try:
            self.site_packages.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise RuntimeError(f"No permission to create site-packages directory: {e}")
        except OSError as e:
            raise RuntimeError(f"Failed to create site-packages directory: {e}")
        
        # Set API URL
        self.repo_api = repo_api or "https://api.github.com/repos/python/cpython/contents/Lib"
        self.py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        
        logger.info(f"Initialized StdlibInstaller for Python {self.py_version}")
    
    def _validate_name(self, name: str) -> str:
        """
        Validate package/module name.
        
        Parameters
        ----------
        name : str
            Name to validate
            
        Returns
        -------
        str
            Validated name
            
        Raises
        ------
        ValueError
            If name is empty or invalid
            
        Examples
        --------
        >>> installer._validate_name('json')
        'json'
        """
        if not name or not isinstance(name, str):
            raise ValueError("Name must be a non-empty string")
        
        name = name.strip()
        
        if not name:
            raise ValueError("Name cannot be empty or whitespace only")
        
        # Basic validation - allow dots for subpackages
        parts = name.split('.')
        for part in parts:
            if not part or not part.isidentifier():
                raise ValueError(f"Invalid name part: '{part}' in '{name}'")
        
        return name
    
    def _make_request(self, url: str) -> Any:
        """
        Make an HTTP request with error handling.
        
        Parameters
        ----------
        url : str
            URL to request
            
        Returns
        -------
        Any
            Response object
            
        Raises
        ------
        RuntimeError
            If request fails
        """
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; Python StdlibInstaller)',
                    'Accept': 'application/json'
                }
            )
            
            response = urllib.request.urlopen(req, timeout=self.timeout)
            
            if response.getcode() not in (200, 201):
                raise RuntimeError(f"HTTP {response.getcode()}: Request failed")
            
            return response
            
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(f"Resource not found: {url}")
            elif e.code == 403:
                raise RuntimeError(f"Access forbidden (rate limit may be exceeded): {url}")
            else:
                raise RuntimeError(f"HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}")
        except TimeoutError:
            raise RuntimeError(f"Request timed out after {self.timeout} seconds")
        except Exception as e:
            raise RuntimeError(f"Unexpected request error: {e}")
    
    def _fetch_tree(self, package: str, version: str) -> List[Dict]:
        """
        Fetch directory tree from GitHub API.
        
        Parameters
        ----------
        package : str
            Package path in repository
        version : str
            Python version (branch/tag)
            
        Returns
        -------
        List[Dict]
            List of file/directory entries
            
        Raises
        ------
        RuntimeError
            If fetch fails
            
        Examples
        --------
        >>> tree = installer._fetch_tree('json', '3.9')
        """
        # Handle nested packages
        package_path = package.replace('.', '/')
        url = f"{self.repo_api}/{package_path}?ref={version}"
        
        logger.debug(f"Fetching tree from: {url}")
        
        try:
            with self._make_request(url) as response:
                content = response.read()
                
                # Try to parse as JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"Invalid JSON response: {e}")
                    
        except RuntimeError as e:
            raise RuntimeError(f"Failed to fetch package tree for '{package}': {e}")
    
    def _download_file(self, url: str, target: Path) -> None:
        """
        Download a file from URL to target path.
        
        Parameters
        ----------
        url : str
            File download URL
        target : Path
            Target file path
            
        Raises
        ------
        RuntimeError
            If download fails
            
        Examples
        --------
        >>> installer._download_file(
        ...     'https://raw.githubusercontent.com/.../json.py',
        ...     Path('/site-packages/json.py')
        ... )
        """
        logger.debug(f"Downloading from: {url}")
        
        try:
            with self._make_request(url) as response:
                content = response.read()
                
                # Verify it's Python code (not HTML error)
                if content.startswith(b'<!DOCTYPE html>') or content.startswith(b'<html>'):
                    # Check if it's actually HTML error page
                    if b'404' in content[:1000] or b'Not Found' in content[:1000]:
                        raise RuntimeError("File not found (404)")
                    else:
                        raise RuntimeError("Downloaded content is HTML, not a Python file")
                
                # Ensure target directory exists
                target.parent.mkdir(parents=True, exist_ok=True)
                
                # Write file
                target.write_bytes(content)
                
                logger.debug(f"Successfully downloaded to: {target}")
                
        except RuntimeError as e:
            raise RuntimeError(f"Failed to download {url}: {e}")
        except PermissionError as e:
            raise RuntimeError(f"No permission to write to {target}: {e}")
        except OSError as e:
            raise RuntimeError(f"Failed to write file: {e}")
    
    def _get_installed_path(self, name: str) -> Path:
        """
        Get the installation path for a package.
        
        Parameters
        ----------
        name : str
            Package name
            
        Returns
        -------
        Path
            Installation path
        """
        # Handle nested packages
        return self.site_packages / name.replace('.', '/')
    
    def install(self, name: str, version: Optional[str] = None, force: bool = False) -> str:
        """
        Install a standard library package/module.
        
        Parameters
        ----------
        name : str
            Name of the package/module to install
        version : str, optional
            Python version to install from (default: current version)
        force : bool, optional
            Force reinstallation if already exists (default: False)
            
        Returns
        -------
        str
            String path to installed package.
            
        Raises
        ------
        ValueError
            If name is invalid
        RuntimeError
            If installation fails
        ModuleNotFoundError
            If package not found in repository
            
        Examples
        --------
        >>> # Install a package
        >>> path = installer.install('json')
        >>> print(path)
        /usr/local/lib/python3.9/site-packages/json
        
        >>> # Install specific version
        >>> path = installer.install('xml', version='3.8')
        """
        # Validate name
        name = self._validate_name(name)
        
        # Set version
        version = version or self.py_version
        
        # Get target path
        target = self._get_installed_path(name)
        
        # Check if already installed
        if target.exists() and not force:
            logger.info(f"Package '{name}' already installed at {target}")
            return str(target)
        elif target.exists() and force:
            logger.info(f"Force mode: removing existing installation of '{name}'")
            self.remove(name, ignore_errors=True)
        
        logger.info(f"Installing '{name}' from Python {version}")
        
        try:
            # Fetch directory tree
            tree = self._fetch_tree(name, version)
            
            # Create target directory
            target.mkdir(parents=True, exist_ok=True)
            
            installed_files = []
            
            # Download all files
            for item in tree:
                if item.get("type") == "file":
                    file_name = item.get("name")
                    download_url = item.get("download_url")
                    
                    if not file_name or not download_url:
                        logger.warning(f"Skipping item with missing data: {item}")
                        continue
                    
                    file_path = target / file_name
                    
                    try:
                        self._download_file(download_url, file_path)
                        installed_files.append(file_path)
                        logger.debug(f"Installed: {file_name}")
                    except Exception as e:
                        # Clean up on failure
                        logger.error(f"Failed to install {file_name}: {e}")
                        for f in installed_files:
                            try:
                                if f.exists():
                                    f.unlink()
                            except:
                                pass
                        if target.exists():
                            try:
                                target.rmdir()
                            except:
                                pass
                        raise RuntimeError(f"Installation failed at {file_name}: {e}")
            
            # Create __init__.py if it doesn't exist and this is a package
            init_file = target / "__init__.py"
            if not init_file.exists() and any(f.suffix == '.py' for f in installed_files):
                init_file.touch()
                logger.debug(f"Created {init_file}")
            
            logger.info(f"Successfully installed '{name}' to {target}")
            return str(target)
            
        except RuntimeError as e:
            raise RuntimeError(f"Installation failed for '{name}': {e}")
    
    def install_bulk(self, names: List[str], version: Optional[str] = None) -> Dict[str, Union[str, Exception]]:
        """
        Install multiple packages at once.
        
        Parameters
        ----------
        names : List[str]
            List of package names to install
        version : str, optional
            Python version to install from
            
        Returns
        -------
        Dict[str, Union[stt, Exception]]
            Dictionary mapping package names to installation results
            (str for success, Exception for failure)
            
        Examples
        --------
        >>> results = installer.install_bulk(['json', 'csv', 'xml'])
        >>> for name, result in results.items():
        ...     if isinstance(result, str):
        ...         print(f"Installed: {name}: {result}")
        ...     else:
        ...         print(f"Uninstalled: {name}: {result}")
        """
        results = {}
        
        for name in names:
            try:
                results[name] = self.install(name, version)
            except Exception as e:
                results[name] = e
                logger.error(f"Failed to install '{name}': {e}")
        
        return results
    
    def update(self, name: str, version: Optional[str] = None) -> str:
        """
        Update an installed package to a newer version.
        
        Parameters
        ----------
        name : str
            Name of the package to update
        version : str, optional
            Python version to update to (default: current version)
            
        Returns
        -------
        str
            string path to updated package
            
        Raises
        ------
        ValueError
            If name is invalid
        RuntimeError
            If update fails
        ModuleNotFoundError
            If package not installed
            
        Examples
        --------
        >>> installer.update('json')
        """
        # Validate name
        name = self._validate_name(name)
        
        # Check if installed
        target = self._get_installed_path(name)
        if not target.exists():
            raise ModuleNotFoundError(f"Package '{name}' is not installed")
        
        logger.info(f"Updating '{name}'")
        
        # Remove and reinstall
        self.remove(name)
        return self.install(name, version)
    
    def remove(self, name: str, ignore_errors: bool = False) -> None:
        """
        Remove an installed package.
        
        Parameters
        ----------
        name : str
            Name of the package to remove
        ignore_errors : bool, optional
            Ignore errors during removal (default: False)
            
        Raises
        ------
        ValueError
            If name is invalid
        ModuleNotFoundError
            If package not installed and not ignoring errors
        RuntimeError
            If removal fails
            
        Examples
        --------
        >>> installer.remove('json')
        """
        # Validate name
        name = self._validate_name(name)
        
        # Get target path
        target = self._get_installed_path(name)
        
        if not target.exists():
            if ignore_errors:
                logger.warning(f"Package '{name}' not installed, skipping removal")
                return
            else:
                raise ModuleNotFoundError(f"Package '{name}' is not installed")
        
        logger.info(f"Removing '{name}' from {target}")
        
        try:
            if target.is_dir():
                shutil.rmtree(target)
                logger.debug(f"Removed directory: {target}")
            else:
                target.unlink()
                logger.debug(f"Removed file: {target}")
                
            logger.info(f"Successfully removed '{name}'")
            
        except PermissionError as e:
            if ignore_errors:
                logger.error(f"Permission error removing '{name}': {e}")
            else:
                raise RuntimeError(f"No permission to remove {target}: {e}")
        except OSError as e:
            if ignore_errors:
                logger.error(f"OS error removing '{name}': {e}")
            else:
                raise RuntimeError(f"Failed to remove {target}: {e}")
    
    def list_installed(self, fullpath: bool = False) -> List[str]:
        """
        List all installed standard library packages.
        
        Returns
        -------
        List[str]
            List of paths to installed packages
            
        Examples
        --------
        >>> installed = installer.list_installed(fullpath=True)
        >>> for path in installed:
        ...     print(path)
        """
        if not self.site_packages.exists():
            return []
        
        items = set()
        for item in self.site_packages.iterdir():
            # Skip __pycache__ and other special directories
            if item.name.startswith('__') or item.name.endswith('.pyc'):
                continue
            items.add(str(item) if fullpath else item.stem)
        
        return sorted(items)
    
    def is_installed(self, name: str) -> bool:
        """
        Check if a package is installed.
        
        Parameters
        ----------
        name : str
            Package name to check
            
        Returns
        -------
        bool
            True if installed, False otherwise
            
        Examples
        --------
        >>> if installer.is_installed('json'):
        ...     print("json is installed")
        """
        try:
            name = self._validate_name(name)
        except ValueError:
            return False
        
        return self._get_installed_path(name).exists()
