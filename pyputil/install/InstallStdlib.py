#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import sys
import sysconfig
import importlib
import shutil
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple, Dict
import logging
import os

from ..modules import is_stdlib

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def validate_module_name(module_name: str) -> str:
    """
    Validate the module name for installation.
    
    Parameters
    ----------
    module_name : str
        Name of the module to validate
        
    Returns
    -------
    str
        Validated and stripped module name
        
    Raises
    ------
    ValueError
        If module name is empty or invalid
        
    Examples
    --------
    >>> validate_module_name('json')
    'json'
    >>> validate_module_name('  os  ')
    'os'
    """
    if not module_name or not isinstance(module_name, str):
        raise ValueError("Module name must be a non-empty string")
    
    module_name = module_name.strip()
    
    if not module_name:
        raise ValueError("Module name cannot be empty or whitespace only")
    
    if not module_name.isidentifier():
        raise ValueError(f"Invalid module name: '{module_name}' is not a valid Python identifier")
    
    return module_name


def get_site_packages_path() -> Path:
    """
    Get and prepare the site-packages directory path.
    
    Returns
    -------
    Path
        Path object pointing to the site-packages directory
        
    Raises
    ------
    RuntimeError
        If site-packages path cannot be determined or created
        
    Examples
    --------
    >>> path = get_site_packages_path()
    >>> print(path)
    /usr/local/lib/python3.9/site-packages
    """
    try:
        site_packages = Path(sysconfig.get_paths()["purelib"])
        logger.debug(f"Site-packages directory: {site_packages}")
    except KeyError as e:
        raise RuntimeError(f"Could not determine site-packages location: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error getting site-packages path: {e}")
    
    # Ensure site-packages exists
    try:
        site_packages.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured site-packages directory exists: {site_packages}")
    except PermissionError as e:
        raise RuntimeError(f"No permission to create site-packages directory: {e}")
    except OSError as e:
        raise RuntimeError(f"Failed to create site-packages directory: {e}")
    
    return site_packages


def find_local_module(module_name: str) -> Tuple[Optional[Path], Optional[str]]:
    """
    Attempt to find and import a module locally.
    
    Parameters
    ----------
    module_name : str
        Name of the module to find
        
    Returns
    -------
    Tuple[Optional[Path], Optional[str]]
        - Path to module file if found, None otherwise
        - Error message if any, None otherwise
        
    Examples
    --------
    >>> path, error = find_local_module('json')
    >>> if path:
    ...     print(f"Found module at: {path}")
    """
    try:
        logger.info(f"Attempting to import module: {module_name}")
        module = importlib.import_module(module_name)
        
        # Check if module has a file path
        module_file = getattr(module, "__file__", None)
        
        if module_file is None:
            return None, f"Module '{module_name}' is a built-in module and cannot be copied"
        
        module_path = Path(module_file)
        
        if not module_path.exists():
            return None, f"Module file not found: {module_path}"
        
        logger.debug(f"Found local module at: {module_path}")
        return module_path, None
        
    except ImportError as e:
        logger.debug(f"Module not found locally: {e}")
        return None, None  # Module not found, try downloading
    except Exception as e:
        return None, f"Unexpected error finding module: {e}"


def determine_target_path(module_path: Path, site_packages: Path) -> Path:
    """
    Determine the target installation path based on module type.
    
    Parameters
    ----------
    module_path : Path
        Source path of the module
    site_packages : Path
        Target site-packages directory
        
    Returns
    -------
    Path
        Target path for installation
        
    Examples
    --------
    >>> target = determine_target_path(Path('/usr/lib/python3.9/json.py'), 
    ...                                Path('/site-packages'))
    >>> print(target)
    /site-packages/json.py
    """
    # Handle C extensions
    if module_path.suffix in (".so", ".pyd", ".dll"):
        logger.debug(f"Detected C extension module: {module_path.suffix}")
        return site_packages / module_path.name
    
    # Handle Python modules
    logger.debug(f"Detected Python module: {module_path.suffix}")
    return site_packages / module_path.name


def copy_module_file(source: Path, target: Path) -> Path:
    """
    Copy a module file from source to target location.
    
    Parameters
    ----------
    source : Path
        Source file path
    target : Path
        Target file path
        
    Returns
    -------
    Path
        Path to the copied file
        
    Raises
    ------
    RuntimeError
        If copy operation fails
        
    Examples
    --------
    >>> copied = copy_module_file(Path('json.py'), Path('/site-packages/json.py'))
    """
    if not is_stdlib(source.stem):
        raise RuntimeError("Source is expected to be stdlib module")
    
    logger.info(f"Copying from {source} to {target}")
    
    try:
        # Check if source exists and is readable
        if not source.exists():
            raise RuntimeError(f"Source file does not exist: {source}")
        
        if not os.access(source, os.R_OK):
            raise RuntimeError(f"Source file is not readable: {source}")
        
        # Perform copy
        shutil.copy2(source, target)
        logger.info(f"Successfully copied to: {target}")
        
        # Verify copy was successful
        if not target.exists():
            raise RuntimeError(f"Copy failed: target file not created: {target}")
        
        return target
        
    except (shutil.Error, OSError) as e:
        raise RuntimeError(f"Failed to copy module file: {e}") 
    except Exception as e:
        raise RuntimeError(f"Unexpected error during copy: {e}")


def download_from_cpython(module_name: str, target: Path) -> str:
    """
    Download a standard library module from CPython GitHub repository.
    
    Parameters
    ----------
    module_name : str
        Name of the module to download
    target : Path
        Target path to save the downloaded file
        
    Returns
    -------
    str
        string path to the downloaded file
        
    Raises
    ------
    RuntimeError
        If download fails for any reason
        
    Examples
    --------
    >>> target = download_from_cpython('json', Path('/site-packages/json.py'))
    """
    # Construct download URL
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    url = f"https://raw.githubusercontent.com/python/cpython/{py_version}/Lib/{module_name}.py"
    
    logger.info(f"Downloading from: {url}")
    
    try:
        # Create request with user agent to avoid blocking
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; Python stdlib installer)'}
        )
        
        with urllib.request.urlopen(req, timeout=30) as response:
            # Check if download was successful
            if response.getcode() != 200:
                raise RuntimeError(f"HTTP {response.getcode()}: Failed to download module")
            
            # Read content
            content = response.read()
            
            # Verify it's a Python file (not HTML error page)
            if content.startswith(b'<!DOCTYPE html>') or content.startswith(b'<html>'):
                raise RuntimeError("Downloaded content is HTML, not a Python module")
            
            # Write to target file
            target.write_bytes(content)
            
        logger.info(f"Successfully downloaded module to: {target}")
        return str(target)
        
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(f"Module '{module_name}' not found in CPython repository for Python {py_version}")
        else:
            raise RuntimeError(f"HTTP error {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")
    except TimeoutError:
        raise RuntimeError("Download timed out after 30 seconds")
    except PermissionError as e:
        raise RuntimeError(f"No permission to write to {target}: {e}")
    except OSError as e:
        raise RuntimeError(f"Failed to write module file: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during download: {e}")


def install_stdlib(module_name: str) -> str:
    """
    Install a Python standard library module to site-packages.
    
    Parameters
    ----------
    module_name : str
        Name of the standard library module to install.
        Examples: 'json', 'collections', 'datetime', 'os'
    
    Returns
    -------
    str
        string path pointing to the installed module file location.
        The file will be placed in the current environment's site-packages directory.
    
    Raises
    ------
    ValueError
        If the module name is empty or invalid
    RuntimeError
        If the installation process fails due to file system or network issues
    ImportError
        If the module is a built-in module that cannot be physically copied
    
    Examples
    --------
    >>> # Install a pure Python module
    >>> path = install_stdlib('json')
    >>> print(path)
    /usr/local/lib/python3.9/site-packages/json.py
    
    >>> # Install a C extension module
    >>> path = install_stdlib('sqlite3')
    >>> print(path)
    /usr/local/lib/python3.9/site-packages/sqlite3.so
    
    >>> # Handle built-in modules
    >>> try:
    ...     install_stdlib('sys')
    ... except ImportError as e:
    ...     print(f"Cannot install built-in module: {e}")
    
    See Also
    --------
    validate_module_name : Validates module name
    get_site_packages_path : Gets site-packages directory
    find_local_module : Attempts to find local module
    copy_module_file : Copies module file
    download_from_cpython : Downloads module from CPython
    """
    
    # Step 1: Validate module name
    module_name = validate_module_name(module_name)
    
    # Step 2: Get site-packages path
    site_packages = get_site_packages_path()
    
    # Step 3: Try to find local module
    module_path, error = find_local_module(module_name)
    
    if error:
        # Built-in module or other error
        raise ImportError(error)
    
    if module_path:
        # Step 4: Local module found - determine target and copy
        target = determine_target_path(module_path, site_packages)
        return str(copy_module_file(module_path, target))
    
    # Step 5: Module not found locally - download from CPython
    target = site_packages / f"{module_name}.py"
    return download_from_cpython(module_name, target)


# Optional: Create a convenience function for bulk installation
def install_stdlib_bulk(module_names: list) -> Dict:
    """
    Install multiple standard library modules.
    
    Parameters
    ----------
    module_names : list
        List of module names to install
        
    Returns
    -------
    dict
        Dictionary mapping module names to installation results
        (str objects for success, Exception objects for failure)
        
    Examples
    --------
    >>> results = install_stdlib_bulk(['json', 'csv', 'invalid!'])
    >>> for module, result in results.items():
    ...     if isinstance(result, str):
    ...         print(f"Installed: {module}: {result}")
    ...     else:
    ...         print(f"Uninstalled: {module}: {result}")
    """
    results = {}
    
    for module_name in module_names:
        try:
            results[module_name] = install_stdlib(module_name)
        except Exception as e:
            results[module_name] = e
    
    return results

