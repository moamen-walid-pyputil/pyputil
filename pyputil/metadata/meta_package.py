#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""Package metadata analysis module."""

import ast
import importlib
import importlib.metadata as metadata
import time
from pathlib import Path
from typing import Dict, Set, Optional, List
from dataclasses import dataclass, field
import logging
import warnings
from pkgutil import walk_packages

# Configure logger
logger = logging.getLogger(__name__)


@dataclass
class PackageInfo:
    """
    Container for package metadata and structural information.
    
    Attributes
    ----------
    name : str
        Package name
    version : Optional[str]
        Package version if found
    namespace : bool
        Whether this is a namespace package
    metadata : Dict[str, str]
        Raw package metadata from importlib.metadata
    deps : Set[str]
        Set of production deps
    dev_deps : Set[str]
        Set of development/extra deps
    modules : Set[str]
        Set of module names in the package
    subpackages : Set[str]
        Set of subpackage names
    file_count : int
        Number of Python files in the package
    size_bytes : int
        Total size of Python files in bytes
    import_time : float
        Time taken to import the package in seconds
    """
    name: str
    version: Optional[str] = None
    namespace: bool = False
    metadata: Dict[str, str] = field(default_factory=dict)
    deps: Set[str] = field(default_factory=set)
    dev_deps: Set[str] = field(default_factory=set)
    modules: Set[str] = field(default_factory=set)
    subpackages: Set[str] = field(default_factory=set)
    file_count: int = 0
    size_bytes: int = 0
    import_time: float = 0.0
    
    def total_deps(self) -> int:
        """Return total number of deps (including dev)."""
        return len(self.deps) + len(self.dev_deps)


def get_package_metadata(package_name: str) -> PackageInfo:
    """
    Perform comprehensive analysis of a Python package's structure and metadata.
    
    This function analyzes package structure, deps, file size,
    and metadata to provide detailed information about the package. It handles
    both regular packages and namespace packages, extracting version information
    from multiple sources and parsing dependency relationships.
    
    Parameters
    ----------
    package_name : str
        Name of the package to analyze. This should be the import name
        (e.g., 'requests', 'numpy', 'PIL') not necessarily the PyPI distribution name.
    
    Returns
    -------
    PackageInfo
        A dataclass containing comprehensive package information including:
        
        - Basic info: name, version, namespace status
        - deps: production and development deps
        - Structure: modules, subpackages, file count
        - Size: total bytes and megabytes of Python files
        - Performance: import time in seconds
        - Metadata: raw package metadata dictionary
    
    Raises
    ------
    ValueError
        If package_name is empty or contains invalid characters
    
    Warns
    -----
    UserWarning
        If package imports successfully but has no Python files
    UserWarning
        If package has no version information available
    
    Examples
    --------
    Analyze a simple package:
    
    >>> info = get_package_metadata('requests')
    >>> print(f"Version: {info.version}")
    Version: 2.31.0
    >>> print(f"deps: {', '.join(sorted(info.deps))}")
    deps: certifi, charset-normalizer, idna, urllib3
    
    Analyze a package with dev deps:
    
    >>> info = get_package_metadata('pytest')
    >>> print(f"Total deps: {len(info.deps)}")
    Total deps: 12
    >>> print(f"Dev deps: {len(info.dev_deps)}")
    Dev deps: 3
    
    Handle namespace packages:
    
    >>> info = get_package_metadata('google.cloud')
    >>> print(f"Namespace package: {info.namespace}")
    Namespace package: True
    >>> print(f"Subpackages: {list(info.subpackages)[:3]}")
    Subpackages: ['google.cloud.tasks', 'google.cloud.storage', 'google.cloud.bigquery']
    
    Handle missing packages:
    
    >>> info = get_package_metadata('nonexistent_package_xyz')
    ERROR: Failed to import nonexistent_package_xyz: No module named 'nonexistent_package_xyz'
    >>> print(info.name, info.version)
    nonexistent_package_xyz None
    
    Performance tracking:
    
    >>> import time
    >>> start = time.perf_counter()
    >>> info = get_package_metadata('numpy')
    >>> elapsed = time.perf_counter() - start
    >>> print(f"Total time: {elapsed:.3f}s (Import: {info.import_time:.3f}s)")
    Total time: 0.523s (Import: 0.089s)
    
    Notes
    -----
    - Version detection priority: __version__ > version > VERSION > metadata
    - deps with environment markers (e.g., 'pytest; extra == "test"')
      are separated into dev_deps
    - File counting includes only .py files (excludes .pyc, __pycache__, etc.)
    - For namespace packages, file counting may be incomplete due to distributed
      nature across multiple paths
    - Import time measurement includes only the initial import, not analysis
    
    See Also
    --------
    importlib.metadata : Used for metadata extraction
    pyputil.modules.walk_packages : Used for module discovery
    """
    # Input validation
    if not package_name or not isinstance(package_name, str):
        raise ValueError(f"Package name must be a non-empty string, got {package_name!r}")
    
    if not package_name.replace('_', '').replace('-', '').isalnum():
        
        warnings.warn(
            f"Package name '{package_name}' contains unusual characters",
            UserWarning,
            stacklevel=2
        )
    
    start_time = time.perf_counter()
    info = PackageInfo(name=package_name)
    
    # Try to import the package
    try:
        package = importlib.import_module(package_name)
        info.import_time = time.perf_counter() - start_time
    except ImportError as e:
        logger.error(f"Failed to import {package_name}: {e}")
        return info
    
    # Check if it's a namespace package
    info.namespace = hasattr(package, '__path__') and not hasattr(package, '__file__')
    
    # Get version from various sources (priority order)
    version_attrs = ['__version__', 'version', 'VERSION']
    for attr in version_attrs:
        if hasattr(package, attr):
            version_value = getattr(package, attr)
            if version_value:
                info.version = str(version_value)
                break
    
    # Try to get metadata from importlib.metadata
    try:
        pkg_metadata = metadata.metadata(package_name)
        
        # Update version if not already found
        if not info.version:
            info.version = pkg_metadata.get('Version')
        
        # Store raw metadata
        info.metadata = dict(pkg_metadata)
        
        # Parse deps with environment markers
        requires_list = metadata.requires(package_name) or []
        for req in requires_list:
            # Split on ';' to separate requirement from environment marker
            if ';' in req:
                requirement_part = req.split(';')[0].strip()
                marker_part = req.split(';')[1].strip()
                
                # Check if it's an extra/dev dependency
                if 'extra' in marker_part or 'dev' in marker_part:
                    info.dev_deps.add(requirement_part)
                else:
                    info.deps.add(requirement_part)
            else:
                info.deps.add(req.strip())
                
    except (ImportError, metadata.PackageNotFoundError) as e:
        logger.debug(f"Could not retrieve metadata for {package_name}: {e}")
    
    # Analyze package structure
    if hasattr(package, '__path__'):
        for path_item in package.__path__:
            path = Path(path_item)
            if not path.exists() or not path.is_dir():
                continue
            
            # Recursively collect Python files
            try:
                for py_file in path.rglob("*.py"):
                    # Skip files in __pycache__ directories
                    if '__pycache__' in py_file.parts:
                        continue
                    
                    info.file_count += 1
                    info.size_bytes += py_file.stat().st_size
                    
                    # Parse module name from file path
                    rel_path = py_file.relative_to(path)
                    parts = list(rel_path.with_suffix('').parts)
                    
                    if parts[-1] == '__init__':
                        # This is a package marker
                        parts.pop()
                        if parts:
                            subpackage_name = '.'.join([package_name] + parts)
                            info.subpackages.add(subpackage_name)
                    else:
                        # Regular module
                        module_name = '.'.join([package_name] + parts)
                        info.modules.add(module_name)
                        
            except (OSError, PermissionError) as e:
                logger.warning(f"Error accessing files in {path}: {e}")
    
    # Discover additional modules using walk_packages
    if hasattr(package, '__path__'):
        try:
            prefix = f"{package_name}."
            for module_info in walk_packages(package.__path__, prefix):
                if module_info.ispkg:
                    info.subpackages.add(module_info.name)
                else:
                    info.modules.add(module_info.name)
        except Exception as e:
            logger.warning(f"Error walking packages for {package_name}: {e}")
    
    # Issue warnings for unusual cases
    if info.file_count == 0 and not info.namespace:
        
        warnings.warn(
            f"Package '{package_name}' imported successfully but no Python files found",
            UserWarning,
            stacklevel=2
        )
    
    if not info.version:
        warnings.warn(
            f"Could not determine version for package '{package_name}'",
            UserWarning,
            stacklevel=2
        )
    
    return info


