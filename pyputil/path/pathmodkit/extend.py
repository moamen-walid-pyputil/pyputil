#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import sys
from pathlib import Path
from typing import List, Union, Sequence, Optional

def extend_path(path: Union[List[str], object], name: str) -> Union[List[str], object]:
    """
    Extend a package's path by adding subdirectories from sys.path and .pkg files.

    This function is designed to be used in a package's `__init__.py` to combine
    multiple directories containing parts of the same logical package.

    Parameters
    ----------
    path : list of str or object
        The current package path (typically `__path__`). If not a list
        (e.g., in frozen packages), it's returned unchanged.
    name : str
        The package's name (typically `__name__`). Can be a dotted name
        for subpackages.

    Returns
    -------
    list of str or object
        Extended path list (or original object if input wasn't a list).

    Notes
    -----
    This function performs two main tasks to extend the package path:

    1. **Namespace package discovery (PEP 420)**:
       For each directory in the search path (sys.path for top-level packages
       or parent package's __path__ for subpackages), if it contains a
       subdirectory matching the package name, that subdirectory is added
       to the package's __path__.

    2. **.pkg file processing**:
       For each directory in the search path, if it contains a file named
       `{name}.pkg`, each non-empty, non-comment line from that file is
       added to the path (without checking if the paths exist).

    The input path is never modified; a new copy is returned with items
    appended at the end. Duplicate entries are automatically prevented.

    Important behaviors:
    - Unicode paths are fully supported through pathlib
    - Non-existent directories in sys.path are silently ignored
    - .pkg files are trusted at face value (paths aren't validated)
    - Comments in .pkg files start with '#' and are ignored
    - Empty lines in .pkg files are ignored

    Examples
    --------
    >>> # Basic usage in a package's __init__.py:
    >>> from extend_path import extend_path
    >>> __path__ = extend_path(__path__, __name__)
    
    >>> # For a namespace package spanning multiple directories:
    >>> # If sys.path contains '/site1' and '/site2', both having
    >>> # a 'mypackage' subdirectory, both will be included.
    >>> 
    >>> # Example .pkg file content (mypackage.pkg):
    >>> # /usr/local/share/mypackage/extras
    >>> # /opt/mypackage/plugins
    >>> # # This is a comment and will be ignored
    >>> # /network/shared/mypackage

    See Also
    --------
    pkgutil.extend_path : Original function this is based on
    importlib.resources : For accessing resources within packages
    """
    
    # Return unchanged if not a list (e.g., frozen packages or custom objects)
    if not isinstance(path, list):
        return path
    
    # Work on a copy to avoid modifying the original path
    extended_path = path.copy()
    
    # Parse the package name to handle subpackages
    parent_package, _, final_name = name.rpartition('.')
    
    # Determine where to search for package parts
    if parent_package:
        # For subpackages, search in parent package's path
        try:
            parent_module = sys.modules[parent_package]
            search_path = parent_module.__path__
        except (KeyError, AttributeError):
            # Parent package not found or has no __path__ - can't proceed
            return extended_path
    else:
        # For top-level packages, search in sys.path
        search_path = sys.path
    
    # Prepare the .pkg filename
    pkg_filename = f"{name}.pkg"
    
    # Process each directory in the search path
    for search_dir in search_path:
        # Skip non-string entries 
        if not isinstance(search_dir, (str, Path)):
            continue
        
        try:
            search_path_obj = Path(search_dir)
        except (TypeError, ValueError):
            # Invalid path - skip silently
            continue
        
        # Skip directories that don't exist
        if not search_path_obj.is_dir():
            continue
        
        # --- Part 1: Look for subdirectories (namespace packages) ---
        subdir_path = search_path_obj / final_name
        if subdir_path.is_dir():
            subdir_str = str(subdir_path)
            if subdir_str not in extended_path:
                extended_path.append(subdir_str)
        
        # --- Part 2: Look for .pkg files ---
        pkg_file_path = search_path_obj / pkg_filename
        if pkg_file_path.is_file():
            try:
                # Read and process the .pkg file
                content = pkg_file_path.read_text(encoding='utf-8')
                for line in content.splitlines():
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    # Add the path (no existence check by design - feature, not bug)
                    if line not in extended_path:
                        extended_path.append(line)
                        
            except (OSError, IOError, UnicodeDecodeError) as e:
                pass
    
    return extended_path


def extend_path2(
    path: Union[List[str], object],
    name: str,
    *,
    validate_pkg_paths: bool = False,
    follow_symlinks: bool = True,
    encoding: str = 'utf-8'
) -> Union[List[str], object]:
    """
    Version2 of extend_path with additional configuration options.

    Parameters
    ----------
    path : list of str or object
        The current package path (typically `__path__`).
    name : str
        The package's name (typically `__name__`).
    validate_pkg_paths : bool, default=False
        If True, check that paths from .pkg files actually exist before adding them.
        Note: This changes the original behavior which trusts .pkg files unconditionally.
    follow_symlinks : bool, default=True
        If True, follow symbolic links when checking directories.
    encoding : str, default='utf-8'
        Encoding to use when reading .pkg files.

    Returns
    -------
    list of str or object
        Extended path list (or original object if input wasn't a list).

    Examples
    --------
    >>> # Only add .pkg paths that actually exist
    >>> __path__ = extend_path2(__path__, __name__, validate_pkg_paths=True)
    
    >>> # Use different encoding for .pkg files
    >>> __path__ = extend_path2(__path__, __name__, encoding='latin-1')
    """
    
    if not isinstance(path, list):
        return path
    
    extended_path = path.copy()
    parent_package, _, final_name = name.rpartition('.')
    
    if parent_package:
        try:
            parent_module = sys.modules[parent_package]
            search_path = parent_module.__path__
        except (KeyError, AttributeError):
            return extended_path
    else:
        search_path = sys.path
    
    pkg_filename = f"{name}.pkg"
    
    for search_dir in search_path:
        if not isinstance(search_dir, (str, Path)):
            continue
        
        try:
            search_path_obj = Path(search_dir)
        except (TypeError, ValueError):
            continue
        
        if not search_path_obj.is_dir():
            continue
        
        # Handle namespace subdirectories
        subdir_path = search_path_obj / final_name
        if subdir_path.is_dir():
            subdir_str = str(subdir_path)
            if subdir_str not in extended_path:
                extended_path.append(subdir_str)
        
        # Handle .pkg files
        pkg_file_path = search_path_obj / pkg_filename
        if pkg_file_path.is_file():
            try:
                content = pkg_file_path.read_text(encoding=encoding)
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    # Optionally validate path existence
                    if validate_pkg_paths:
                        path_obj = Path(line)
                        exists = path_obj.exists() if follow_symlinks else path_obj.is_dir()
                        if not exists:
                            continue
                    
                    if line not in extended_path:
                        extended_path.append(line)
                        
            except (OSError, IOError, UnicodeDecodeError) as e:
                pass
    
    return extended_path


# Convenience function for common use cases
def extend_namespace_path(
    path: Union[List[str], object],
    name: str,
    *,
    include_pkg_files: bool = True,
    include_subdirs: bool = True
) -> Union[List[str], object]:
    """
    Simplified version focusing on namespace package behavior.

    Parameters
    ----------
    path : list of str or object
        The current package path.
    name : str
        The package's name.
    include_pkg_files : bool, default=True
        Whether to process .pkg files.
    include_subdirs : bool, default=True
        Whether to look for namespace subdirectories.

    Returns
    -------
    list of str or object
        Extended path list.

    Examples
    --------
    >>> # Only use namespace subdirectories, ignore .pkg files
    >>> __path__ = extend_namespace_path(__path__, __name__, include_pkg_files=False)
    """
    
    if not isinstance(path, list):
        return path
    
    extended_path = path.copy()
    parent_package, _, final_name = name.rpartition('.')
    
    if parent_package:
        try:
            parent_module = sys.modules[parent_package]
            search_path = parent_module.__path__
        except (KeyError, AttributeError):
            return extended_path
    else:
        search_path = sys.path
    
    pkg_filename = f"{name}.pkg" if include_pkg_files else None
    
    for search_dir in search_path:
        if not isinstance(search_dir, (str, Path)):
            continue
        
        try:
            search_path_obj = Path(search_dir)
        except (TypeError, ValueError):
            continue
        
        if not search_path_obj.is_dir():
            continue
        
        # Add namespace subdirectories
        if include_subdirs:
            subdir_path = search_path_obj / final_name
            if subdir_path.is_dir():
                subdir_str = str(subdir_path)
                if subdir_str not in extended_path:
                    extended_path.append(subdir_str)
        
        # Process .pkg files
        if include_pkg_files and pkg_filename:
            pkg_file_path = search_path_obj / pkg_filename
            if pkg_file_path.is_file():
                try:
                    content = pkg_file_path.read_text(encoding='utf-8')
                    for line in content.splitlines():
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if line not in extended_path:
                                extended_path.append(line)
                except (OSError, IOError):
                    pass  # Silently ignore .pkg file errors in this simplified version
    
    return extended_path