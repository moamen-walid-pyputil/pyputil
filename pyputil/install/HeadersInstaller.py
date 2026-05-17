#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import sys
import sysconfig
import urllib.request
import zipfile
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional, Union, List, Tuple
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_python_version() -> str:
    """
    Get the current Python version as a string.
    
    Returns
    -------
    str
        Current Python version in format 'major.minor.micro' (e.g., '3.9.5')
    
    Examples
    --------
    >>> get_python_version()
    '3.9.5'
    """
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


def get_target_include_dir() -> Path:
    """
    Get the target include directory for Python headers.
    
    Returns
    -------
    Path
        Path to the Python include directory
    
    Examples
    --------
    >>> get_target_include_dir()
    PosixPath('/usr/include/python3.9')
    """
    return Path(sysconfig.get_paths()["include"])


def build_download_url(
    version: str,
    source: str = "github",
    custom_url: Optional[str] = None
) -> str:
    """
    Build the download URL for Python source code.
    
    Parameters
    ----------
    version : str
        Python version string (e.g., '3.9.5')
    source : str, optional
        Source repository ('github' by default)
    custom_url : str, optional
        Custom URL template with {version} placeholder
    
    Returns
    -------
    str
        Complete download URL
    
    Raises
    ------
    ValueError
        If source is not supported and no custom URL provided
    
    Examples
    --------
    >>> build_download_url('3.9.5')
    'https://github.com/python/cpython/archive/refs/tags/v3.9.5.zip'
    """
    if custom_url:
        return custom_url.format(version=version)
    
    if source == "github":
        return f"https://github.com/python/cpython/archive/refs/tags/v{version}.zip"
    elif source == "python.org":
        return f"https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz"
    else:
        raise ValueError(f"Unsupported source: {source}. Use 'github', 'python.org', or provide custom_url.")


def download_file(
    url: str,
    destination: Path,
    retries: int = 3,
    retry_delay: float = 2.0,
    verbose: bool = False
) -> bool:
    """
    Download a file from URL with retry mechanism.
    
    Parameters
    ----------
    url : str
        URL to download from
    destination : Path
        Path to save the downloaded file
    retries : int, optional
        Number of retry attempts (default: 3)
    retry_delay : float, optional
        Delay between retries in seconds (default: 2.0)
    verbose : bool, optional
        Enable verbose logging (default: False)
    
    Returns
    -------
    bool
        True if download successful, False otherwise
    """
    for attempt in range(retries):
        try:
            if verbose:
                logger.info(f"Download attempt {attempt + 1}/{retries}: {url}")
            
            urllib.request.urlretrieve(url, destination)
            
            if verbose:
                logger.info(f"Download successful: {destination}")
            
            return True
            
        except Exception as e:
            if verbose:
                logger.warning(f"Download failed: {e}")
            
            if attempt + 1 < retries:
                if verbose:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
    
    logger.error(f"Failed to download after {retries} attempts")
    return False


def extract_zip(zip_path: Path, extract_dir: Path, verbose: bool = False) -> bool:
    """
    Extract a ZIP archive.
    
    Parameters
    ----------
    zip_path : Path
        Path to the ZIP file
    extract_dir : Path
        Directory to extract contents to
    verbose : bool, optional
        Enable verbose logging (default: False)
    
    Returns
    -------
    bool
        True if extraction successful, False otherwise
    """
    try:
        if verbose:
            logger.info(f"Extracting {zip_path} to {extract_dir}")
        
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)
        
        if verbose:
            logger.info("Extraction successful")
        
        return True
        
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return False


def find_include_directory(extract_dir: Path, verbose: bool = False) -> Optional[Path]:
    """
    Find the Include directory containing Python.h in extracted source.
    
    Parameters
    ----------
    extract_dir : Path
        Directory containing extracted Python source
    verbose : bool, optional
        Enable verbose logging (default: False)
    
    Returns
    -------
    Optional[Path]
        Path to Include directory if found, None otherwise
    """
    if verbose:
        logger.info(f"Searching for Include directory in {extract_dir}")
    
    for p in extract_dir.rglob("Include"):
        if (p / "Python.h").exists():
            if verbose:
                logger.info(f"Found Include directory: {p}")
            return p
    
    logger.error("Could not find Include directory with Python.h")
    return None


def backup_existing_directory(
    target_dir: Path,
    verbose: bool = False
) -> Optional[Path]:
    """
    Create a backup of an existing directory.
    
    Parameters
    ----------
    target_dir : Path
        Directory to backup
    verbose : bool, optional
        Enable verbose logging (default: False)
    
    Returns
    -------
    Optional[Path]
        Path to backup directory if created, None if no backup needed
    """
    if not target_dir.exists():
        return None
    
    backup_dir = target_dir.parent / f"{target_dir.name}.backup"
    
    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        
        shutil.copytree(target_dir, backup_dir)
        
        if verbose:
            logger.info(f"Backup created: {backup_dir}")
        
        return backup_dir
        
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return None


def clean_target_directory(target_dir: Path, verbose: bool = False) -> bool:
    """
    Clean (remove) the target directory.
    
    Parameters
    ----------
    target_dir : Path
        Directory to clean
    verbose : bool, optional
        Enable verbose logging (default: False)
    
    Returns
    -------
    bool
        True if cleaning successful or directory doesn't exist
    """
    if not target_dir.exists():
        return True
    
    try:
        shutil.rmtree(target_dir)
        
        if verbose:
            logger.info(f"Cleaned target directory: {target_dir}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to clean target directory: {e}")
        return False


def copy_headers(
    source_dir: Path,
    target_dir: Path,
    include_subdirs: bool = True,
    verbose: bool = False
) -> Tuple[int, int]:
    """
    Copy header files from source to target directory.
    
    Parameters
    ----------
    source_dir : Path
        Source Include directory
    target_dir : Path
        Target include directory
    include_subdirs : bool, optional
        Include subdirectories in copy (default: True)
    verbose : bool, optional
        Enable verbose logging (default: False)
    
    Returns
    -------
    Tuple[int, int]
        Tuple of (successful_copies, failed_copies)
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    
    successful = 0
    failed = 0
    
    for item in source_dir.iterdir():
        dest = target_dir / item.name
        
        try:
            if item.is_dir() and include_subdirs:
                if verbose:
                    logger.info(f"Copying directory: {item.name}")
                
                shutil.copytree(item, dest, dirs_exist_ok=True)
                successful += 1
                
            elif item.is_file():
                if verbose:
                    logger.info(f"Copying file: {item.name}")
                
                shutil.copy2(item, dest)
                successful += 1
                
        except Exception as e:
            if verbose:
                logger.warning(f"Failed to copy {item.name}: {e}")
            failed += 1
    
    if verbose:
        logger.info(f"Copy complete: {successful} successful, {failed} failed")
    
    return (successful, failed)


def cleanup_temp_directory(temp_dir: Path, verbose: bool = False) -> bool:
    """
    Remove temporary directory.
    
    Parameters
    ----------
    temp_dir : Path
        Temporary directory to remove
    verbose : bool, optional
        Enable verbose logging (default: False)
    
    Returns
    -------
    bool
        True if cleanup successful or directory doesn't exist
    """
    if not temp_dir.exists():
        return True
    
    try:
        shutil.rmtree(temp_dir)
        
        if verbose:
            logger.info(f"Cleaned up temporary directory: {temp_dir}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to clean up temporary directory: {e}")
        return False


def install_python_headers(
    version: Optional[str] = None,
    target_dir: Optional[Union[str, Path]] = None,
    retries: int = 3,
    retry_delay: float = 2.0,
    clean_existing: bool = False,
    backup_existing: bool = True,
    verbose: bool = False,
    include_subdirs: bool = True,
    source: str = "github",
    custom_url: Optional[str] = None
) -> Optional[str]:
    """
    Install Python headers from source.
    
    This function downloads Python source code, extracts it, and copies the header files
    (including Python.h) to the target include directory.
    
    Parameters
    ----------
    version : str, optional
        Python version string (e.g., '3.9.5'). If None, uses current version.
    target_dir : Union[str, Path], optional
        Target directory for headers. If None, uses system include directory.
    retries : int, optional
        Number of download retry attempts (default: 3)
    retry_delay : float, optional
        Delay between retries in seconds (default: 2.0)
    clean_existing : bool, optional
        Remove existing headers before installation (default: False)
    backup_existing : bool, optional
        Create backup of existing headers (default: True)
    verbose : bool, optional
        Enable verbose logging (default: False)
    include_subdirs : bool, optional
        Include subdirectories when copying headers (default: True)
    source : str, optional
        Source repository ('github' or 'python.org') (default: 'github')
    custom_url : str, optional
        Custom URL template with {version} placeholder
    
    Returns
    -------
    Optional[str]
        String path to installed headers directory if successful, None otherwise
    
    Examples
    --------
    >>> # Install headers for current Python version
    >>> install_python_headers()
    '/usr/include/python3.9'
    
    >>> # Install headers for specific version with backup
    >>> install_python_headers(version='3.8.10', backup_existing=True, verbose=True)
    '/usr/include/python3.8'
    
    >>> # Install to custom directory
    >>> install_python_headers(target_dir='./my_headers', clean_existing=True)
    './my_headers'
    
    Notes
    -----
    This function is particularly useful in environments where Python headers
    are not pre-installed (e.g., minimal containers, certain CI/CD setups)
    or when building C extensions that require specific header versions.
    """
    # Step 1: Determine version
    if version is None:
        version = get_python_version()
    
    if verbose:
        logger.info(f"Installing Python {version} headers")
    
    # Step 2: Determine target directory
    if target_dir is None:
        target_dir = get_target_include_dir()
    else:
        target_dir = Path(target_dir)
    
    if verbose:
        logger.info(f"Target directory: {target_dir}")
    
    # Step 3: Backup existing headers if requested
    if backup_existing and target_dir.exists():
        backup_existing_directory(target_dir, verbose)
    
    # Step 4: Clean existing headers if requested
    if clean_existing:
        if not clean_target_directory(target_dir, verbose):
            return None
    
    # Step 5: Build download URL
    try:
        url = build_download_url(version, source, custom_url)
        if verbose:
            logger.info(f"Download URL: {url}")
    except ValueError as e:
        logger.error(e)
        return None
    
    # Step 6: Create temporary directory
    temp_dir = Path(tempfile.mkdtemp())
    if verbose:
        logger.info(f"Created temporary directory: {temp_dir}")
    
    try:
        # Step 7: Download source
        zip_path = temp_dir / "python_source.zip"
        if not download_file(url, zip_path, retries, retry_delay, verbose):
            return None
        
        # Step 8: Extract archive
        extract_dir = temp_dir / "extracted"
        extract_dir.mkdir()
        
        if not extract_zip(zip_path, extract_dir, verbose):
            return None
        
        # Step 9: Find Include directory
        include_source = find_include_directory(extract_dir, verbose)
        if not include_source:
            return None
        
        # Step 10: Copy headers
        successful, failed = copy_headers(
            include_source,
            target_dir,
            include_subdirs,
            verbose
        )
        
        if successful == 0:
            logger.error("No headers were copied")
            return None
        
        if verbose:
            logger.info(f"Headers installed successfully to {target_dir}")
        
        return str(target_dir)
        
    finally:
        # Step 11: Always clean up temporary directory
        cleanup_temp_directory(temp_dir, verbose)

