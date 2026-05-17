#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Filesystem utilities for directory tree operations.

This module provides robust filesystem operations for directory traversal,
package discovery, and requirement file parsing with comprehensive error
handling and platform-agnostic implementations. 
"""

from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Iterator, Set, Tuple
from datetime import datetime
import os
import stat
import fnmatch
import sys
import warnings
from functools import lru_cache
import hashlib
import codecs
from collections import defaultdict


class FilesystemError(Exception):
    """
    Exception raised for filesystem operation errors.
    
    Attributes
    ----------
    message : str
        Human-readable description of the error
    path : Optional[str]
        Path that caused the error
    operation : Optional[str]
        The operation that failed (read, write, list, etc.)
    original_error : Optional[Exception]
        Original exception that caused this error
    
    Examples
    --------
    >>> raise FilesystemError("Failed to read directory", 
    ...                       path="/nonexistent", operation="list")
    """
    
    def __init__(self, message: str, path: Optional[Union[str, Path]] = None,
                 operation: Optional[str] = None,
                 original_error: Optional[Exception] = None):
        self.message = message
        self.path = str(path) if path else None
        self.operation = operation
        self.original_error = original_error
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        """Format the error message with context."""
        parts = [self.message]
        if self.path:
            parts.append(f" (path: {self.path})")
        if self.operation:
            parts.append(f" (operation: {self.operation})")
        if self.original_error:
            parts.append(f" (cause: {str(self.original_error)})")
        return "".join(parts)


def to_string_path(path: Union[str, Path]) -> str:
    """
    Convert a path to string representation safely.
    
    Parameters
    ----------
    path : str or Path
        Path to convert
    
    Returns
    -------
    str
        String representation of the path
    
    Examples
    --------
    >>> to_string_path(Path("/home/user"))
    '/home/user'
    >>> to_string_path("C:\\Users")
    'C:\\Users'
    """
    if isinstance(path, Path):
        return str(path)
    return path


def get_parent_directory(path: Union[str, Path], resolve: bool = True) -> str:
    """
    Return the parent directory of a given path as string.
    
    This function safely handles both files and directories, resolving
    symlinks when requested, and provides cross-platform path handling.
    
    Parameters
    ----------
    path : str or Path
        Path to a file or directory
    resolve : bool, default=True
        Whether to resolve symbolic links and normalize the path
    
    Returns
    -------
    str
        Parent directory path as string
    
    Raises
    ------
    FilesystemError
        If path cannot be resolved or parent cannot be determined
    
    Examples
    --------
    >>> get_parent_directory("/home/user/file.txt")
    '/home/user'
    >>> get_parent_directory("/home/user/")
    '/home/user'
    >>> get_parent_directory("relative/path/file.txt", resolve=False)
    'relative/path'
    """
    try:
        path_obj = Path(path)
        
        if resolve:
            try:
                path_obj = path_obj.resolve()
            except (OSError, RuntimeError) as e:
                raise FilesystemError(
                    f"Failed to resolve path", 
                    path=path, 
                    operation="resolve",
                    original_error=e
                )
        
        # Check if path points to a directory
        try:
            if path_obj.is_dir():
                return str(path_obj)
        except (OSError, PermissionError):
            # If we can't check, assume it's a file
            pass
        
        return str(path_obj.parent)
        
    except Exception as e:
        if not isinstance(e, FilesystemError):
            raise FilesystemError(
                "Failed to get parent directory",
                path=path,
                operation="get_parent",
                original_error=e
            )
        raise


def get_absolute_path(path: Union[str, Path]) -> str:
    """
    Get absolute path as string.
    
    Parameters
    ----------
    path : str or Path
        Path to convert to absolute
    
    Returns
    -------
    str
        Absolute path as string
    
    Examples
    --------
    >>> get_absolute_path("relative/path")
    '/current/working/directory/relative/path'
    """
    return str(Path(path).absolute())


def get_normalized_path(path: Union[str, Path]) -> str:
    """
    Get normalized path (resolved, absolute) as string.
    
    Parameters
    ----------
    path : str or Path
        Path to normalize
    
    Returns
    -------
    str
        Normalized path as string
    
    Examples
    --------
    >>> get_normalized_path("./parent/../child/file.txt")
    '/current/working/directory/child/file.txt'
    """
    return str(Path(path).resolve())


def safe_join(base: Union[str, Path], *paths: Union[str, Path]) -> str:
    """
    Safely join paths preventing directory traversal attacks.
    
    Parameters
    ----------
    base : str or Path
        Base directory path
    *paths : str or Path
        Path segments to join
    
    Returns
    -------
    str
        Joined path resolved within base directory as string
    
    Raises
    ------
    FilesystemError
        If the joined path escapes the base directory
    
    Examples
    --------
    >>> safe_join("/home/user", "documents", "file.txt")
    '/home/user/documents/file.txt'
    >>> safe_join("/home/user", "../etc/passwd")  # Raises error
    Traceback (most recent call last):
    ...
    FilesystemError: Path escapes base directory
    """
    base_path = Path(base).resolve()
    target_path = base_path.joinpath(*paths).resolve()
    
    try:
        target_path.relative_to(base_path)
    except ValueError:
        raise FilesystemError(
            f"Path '{target_path}' escapes base directory '{base_path}'",
            path=target_path,
            operation="safe_join"
        )
    
    return str(target_path)


def is_path_accessible(path: Union[str, Path], mode: int = os.R_OK) -> bool:
    """
    Check if a path is accessible with specified permissions.
    
    Parameters
    ----------
    path : str or Path
        Path to check
    mode : int, default=os.R_OK
        Access mode (os.R_OK, os.W_OK, os.X_OK, or combination)
    
    Returns
    -------
    bool
        True if path is accessible, False otherwise
    
    Examples
    --------
    >>> is_path_accessible("/home/user/file.txt")
    True
    >>> is_path_accessible("/root/secret.txt", os.W_OK)
    False
    """
    try:
        return os.access(str(path), mode)
    except Exception:
        return False


def get_file_size(path: Union[str, Path]) -> int:
    """
    Get file size in bytes.
    
    Parameters
    ----------
    path : str or Path
        Path to file
    
    Returns
    -------
    int
        File size in bytes, or 0 if file doesn't exist
    
    Examples
    --------
    >>> get_file_size("large_file.bin")
    1048576
    """
    try:
        return Path(path).stat().st_size
    except (OSError, FileNotFoundError):
        return 0


def get_file_modified_time(path: Union[str, Path]) -> float:
    """
    Get file modification timestamp.
    
    Parameters
    ----------
    path : str or Path
        Path to file
    
    Returns
    -------
    float
        Modification timestamp (Unix epoch), or 0 if error
    
    Examples
    --------
    >>> mtime = get_file_modified_time("file.txt")
    >>> from datetime import datetime
    >>> datetime.fromtimestamp(mtime)
    datetime.datetime(2024, 1, 1, 12, 0, 0)
    """
    try:
        return Path(path).stat().st_mtime
    except (OSError, FileNotFoundError):
        return 0.0


def list_directory(path: Union[str, Path], 
                   pattern: Optional[str] = None,
                   include_hidden: bool = False,
                   recursive: bool = False) -> List[str]:
    """
    List contents of a directory with filtering options.
    
    Parameters
    ----------
    path : str or Path
        Directory path to list
    pattern : str, optional
        Glob pattern to filter files (e.g., "*.py")
    include_hidden : bool, default=False
        Whether to include hidden files (starting with .)
    recursive : bool, default=False
        Whether to list subdirectories recursively
    
    Returns
    -------
    List[str]
        List of file/directory names as strings
    
    Raises
    ------
    FilesystemError
        If directory cannot be read
    
    Examples
    --------
    >>> list_directory("/home/user", pattern="*.txt")
    ['notes.txt', 'readme.txt']
    >>> list_directory("/home/user", recursive=True, include_hidden=True)
    ['.config', '.bashrc', 'docs/file.txt']
    """
    try:
        path_obj = Path(path)
        
        if not path_obj.is_dir():
            raise FilesystemError("Not a directory", path=path, operation="list")
        
        items = []
        
        if recursive:
            for item in path_obj.rglob("*"):
                if pattern and not fnmatch.fnmatch(item.name, pattern):
                    continue
                if not include_hidden and item.name.startswith('.'):
                    continue
                items.append(str(item.relative_to(path_obj)))
        else:
            for item in path_obj.iterdir():
                if pattern and not fnmatch.fnmatch(item.name, pattern):
                    continue
                if not include_hidden and item.name.startswith('.'):
                    continue
                items.append(item.name)
        
        return sorted(items)
        
    except (OSError, PermissionError) as e:
        raise FilesystemError(
            "Failed to list directory",
            path=path,
            operation="list",
            original_error=e
        )


def ensure_directory(path: Union[str, Path], create_parents: bool = True) -> str:
    """
    Ensure a directory exists, creating if necessary.
    
    Parameters
    ----------
    path : str or Path
        Directory path to ensure
    create_parents : bool, default=True
        Whether to create parent directories if they don't exist
    
    Returns
    -------
    str
        Path to the directory as string
    
    Raises
    ------
    FilesystemError
        If directory cannot be created
    
    Examples
    --------
    >>> ensure_directory("new_dir/sub_dir")
    'new_dir/sub_dir'
    """
    try:
        path_obj = Path(path)
        
        if create_parents:
            path_obj.mkdir(parents=True, exist_ok=True)
        else:
            path_obj.mkdir(exist_ok=True)
        
        return str(path_obj)
        
    except (OSError, PermissionError) as e:
        raise FilesystemError(
            "Failed to create directory",
            path=path,
            operation="mkdir",
            original_error=e
        )


def generate_directory_tree(
    path: Union[str, Path],
    indent: str = "",
    max_depth: Optional[int] = None,
    show_files: bool = True,
    show_dirs: bool = True,
    sort_by: str = "name",
    full_path: bool = False,
    ignore: Optional[List[str]] = None,
    current_depth: int = 0,
    use_ascii: bool = False,
    include_size: bool = False,
    include_permissions: bool = False,
) -> str:
    """
    Generate a visual directory tree structure for a project path.
    
    This function creates an ASCII/Unicode tree representation of a directory
    structure with extensive customization options.
    
    Parameters
    ----------
    path : str or Path
        Project path for displaying the internal path tree.
    indent : str, optional
        Current indentation string for recursive formatting.
    max_depth : int or None, optional
        Maximum directory depth to display.
    show_files : bool, default=True
        Include files in the tree output.
    show_dirs : bool, default=True
        Include directories in the tree output.
    sort_by : {"name", "size", "mtime"}, default="name"
        Sorting criteria for directory contents.
    full_path : bool, default=False
        Display full paths instead of relative names.
    ignore : list or None, optional
        List of glob patterns to exclude (e.g. ["*.pyc", "__pycache__"]).
    current_depth : int, optional
        Current recursion depth (internal use).
    use_ascii : bool, default=False
        Use ASCII characters instead of Unicode for tree lines.
    include_size : bool, default=False
        Include file/directory sizes in output.
    include_permissions : bool, default=False
        Include file/directory permissions in output.
    
    Returns
    -------
    str
        Formatted tree structure as a multiline string.
    
    Raises
    ------
    FilesystemError
        If the specified path does not exist.
    
    Examples
    --------
    >>> print(generate_directory_tree("./myproject", max_depth=2))
    myproject/
    ├── src/
    │   ├── __init__.py
    │   └── main.py
    └── tests/
        └── test_main.py
    
    >>> print(generate_directory_tree(".", use_ascii=True, include_size=True))
    project/
    |-- src/ (4096 bytes)
    |   |-- main.py (1024 bytes)
    |   `-- utils.py (512 bytes)
    `-- README.md (2048 bytes)
    """
    # Validate path
    path_obj = Path(path)
    if not path_obj.exists():
        raise FilesystemError("Path does not exist", path=path, operation="generate_tree")
    
    # Check depth limit
    if max_depth is not None and current_depth >= max_depth:
        return ""
    
    # Prepare ignore patterns
    ignore_patterns = ignore or []
    
    # Collect items
    items = []
    try:
        for item in path_obj.iterdir():
            # Check ignore patterns
            ignored = False
            for pattern in ignore_patterns:
                if fnmatch.fnmatch(item.name, pattern):
                    ignored = True
                    break
            if ignored:
                continue
            
            items.append(item)
    except PermissionError:
        return f"{path_obj.name}/ [Permission Denied]\n"
    
    # Sort items
    if sort_by == "name":
        items.sort(key=lambda x: x.name.lower())
    elif sort_by == "size":
        items.sort(key=lambda x: x.stat().st_size if x.is_file() else 0)
    elif sort_by == "mtime":
        items.sort(key=lambda x: x.stat().st_mtime)
    else:
        items.sort(key=lambda x: x.name.lower())
    
    # Choose tree characters
    if use_ascii:
        branch_chars = {
            'mid': '|-- ',
            'last': '`-- ',
            'indent_mid': '|   ',
            'indent_last': '    '
        }
    else:
        branch_chars = {
            'mid': '├── ',
            'last': '└── ',
            'indent_mid': '│   ',
            'indent_last': '    '
        }
    
    # Generate tree
    output_lines = []
    
    # Root directory with trailing slash
    root_name = str(path_obj) if full_path else (path_obj.name + '/')
    output_lines.append(root_name)
    
    for i, item in enumerate(items):
        is_last = (i == len(items) - 1)
        is_dir = item.is_dir()
        
        # Filter by type
        if is_dir and not show_dirs:
            continue
        if not is_dir and not show_files:
            continue
        
        # Prepare display name
        if full_path:
            display_name = str(item)
        else:
            display_name = item.name
            if is_dir:
                display_name += '/'
        
        # Add metadata
        metadata = []
        if include_size:
            try:
                size = item.stat().st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f} KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f} MB"
                metadata.append(f"({size_str})")
            except (OSError, PermissionError):
                metadata.append("(?)")
        
        if include_permissions:
            try:
                mode = item.stat().st_mode
                perms = []
                for who in [stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR,
                           stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP,
                           stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH]:
                    perms.append('r' if mode & who else '-')
                perms_str = ''.join(perms)
                metadata.append(f"[{perms_str}]")
            except (OSError, PermissionError):
                metadata.append("[?]")
        
        if metadata:
            display_name = f"{display_name} {' '.join(metadata)}"
        
        # Add branch line
        branch = branch_chars['last'] if is_last else branch_chars['mid']
        output_lines.append(f"{indent}{branch}{display_name}")
        
        # Process subdirectories
        if is_dir:
            next_indent = indent + (branch_chars['indent_last'] if is_last else branch_chars['indent_mid'])
            
            sub_output = generate_directory_tree(
                item,
                indent=next_indent,
                max_depth=max_depth,
                show_files=show_files,
                show_dirs=show_dirs,
                sort_by=sort_by,
                full_path=full_path,
                ignore=ignore,
                current_depth=current_depth + 1,
                use_ascii=use_ascii,
                include_size=include_size,
                include_permissions=include_permissions,
            )
            
            # Skip empty subdirectory output if no content
            if sub_output and not sub_output.startswith(item.name):
                output_lines.append(sub_output.rstrip('\n'))
    
    return '\n'.join(output_lines) + '\n'


def find_package_files(path: Union[str, Path]) -> List[Dict[str, str]]:
    """
    Find all Python package files in a directory with metadata.
    
    Parameters
    ----------
    path : str or Path
        Directory to search
    
    Returns
    -------
    List[Dict[str, str]]
        List of dictionaries containing file info with keys:
        - path: Full path to file
        - type: File type (setup.py, pyproject.toml, setup.cfg, requirements.txt)
        - directory: Parent directory name
    
    Examples
    --------
    >>> files = find_package_files("./myproject")
    >>> for f in files:
    ...     print(f"{f['type']}: {f['path']}")
    setup.py: ./myproject/setup.py
    requirements.txt: ./myproject/requirements.txt
    """
    path_obj = Path(path)
    package_files = []
    
    patterns = {
        "setup.py": "setup.py",
        "pyproject.toml": "pyproject.toml",
        "setup.cfg": "setup.cfg",
        "requirements.txt": "requirements.txt",
        "requirements-dev.txt": "requirements-dev.txt",
        "Pipfile": "Pipfile",
        "poetry.lock": "poetry.lock",
        "pyproject.toml": "pyproject.toml",
    }
    
    for pattern_name, pattern in patterns.items():
        for file_path in path_obj.rglob(pattern):
            if file_path.is_file():
                package_files.append({
                    'path': str(file_path),
                    'type': pattern_name,
                    'directory': str(file_path.parent),
                    'name': file_path.name,
                    'size': file_path.stat().st_size,
                    'modified': file_path.stat().st_mtime
                })
    
    return package_files


def read_requirements_file(path: Union[str, Path], 
                          strip_comments: bool = True,
                          strip_whitespace: bool = True,
                          skip_empty: bool = True,
                          handle_continuations: bool = True) -> List[str]:
    """
    Read and parse a requirements.txt file with advanced options.
    
    Parameters
    ----------
    path : str or Path
        Path to requirements.txt file
    strip_comments : bool, default=True
        Remove comments (lines starting with #)
    strip_whitespace : bool, default=True
        Strip leading/trailing whitespace from lines
    skip_empty : bool, default=True
        Skip empty lines after processing
    handle_continuations : bool, default=True
        Handle line continuations (lines ending with \)
    
    Returns
    -------
    List[str]
        List of requirement strings
    
    Raises
    ------
    FilesystemError
        If file cannot be read
    
    Examples
    --------
    >>> read_requirements_file("requirements.txt")
    ['requests>=2.28.0', 'django==4.2.0']
    
    >>> # With continuation lines
    >>> read_requirements_file("requirements.txt", handle_continuations=True)
    ['package>=1.0', 'another-package==2.0']
    """
    path_obj = Path(path)
    
    if not path_obj.exists():
        return []
    
    if not path_obj.is_file():
        raise FilesystemError("Not a file", path=path, operation="read_requirements")
    
    requirements = []
    
    try:
        # Try UTF-8 first, then fallback to system encoding
        try:
            content = path_obj.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            content = path_obj.read_text(encoding='latin-1')
        
        lines = content.splitlines()
        
        if handle_continuations:
            # Handle line continuations
            continued_lines = []
            current_line = []
            
            for line in lines:
                if line.rstrip().endswith('\\'):
                    # Continuation line
                    current_line.append(line.rstrip('\\').rstrip())
                else:
                    if current_line:
                        current_line.append(line)
                        continued_lines.append(''.join(current_line))
                        current_line = []
                    else:
                        continued_lines.append(line)
            
            if current_line:
                continued_lines.append(''.join(current_line))
            
            lines = continued_lines
        
        for line in lines:
            original_line = line
            
            if strip_whitespace:
                line = line.strip()
            
            if strip_comments and line.startswith('#'):
                continue
            
            if skip_empty and not line:
                continue
            
            # Handle inline comments
            if strip_comments and '#' in line:
                line = line.split('#')[0].strip()
            
            if line:
                requirements.append(line)
        
        return requirements
        
    except (OSError, PermissionError) as e:
        raise FilesystemError(
            "Failed to read requirements file",
            path=path,
            operation="read",
            original_error=e
        )


def write_requirements_file(path: Union[str, Path], 
                           requirements: List[str],
                           create_backup: bool = True) -> str:
    """
    Write requirements to a file with backup option.
    
    Parameters
    ----------
    path : str or Path
        Path to requirements.txt file
    requirements : List[str]
        List of requirement strings
    create_backup : bool, default=True
        Create a backup of existing file (.bak extension)
    
    Returns
    -------
    str
        Path to written file as string
    
    Raises
    ------
    FilesystemError
        If file cannot be written
    
    Examples
    --------
    >>> write_requirements_file("requirements.txt", ["requests>=2.28", "django==4.2"])
    'requirements.txt'
    """
    path_obj = Path(path)
    
    try:
        # Create backup if requested and file exists
        if create_backup and path_obj.exists():
            backup_path = path_obj.with_suffix('.txt.bak')
            path_obj.rename(backup_path)
        
        # Ensure directory exists
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        # Write requirements
        content = '\n'.join(requirements) + '\n'
        path_obj.write_text(content, encoding='utf-8')
        
        return str(path_obj)
        
    except (OSError, PermissionError) as e:
        raise FilesystemError(
            "Failed to write requirements file",
            path=path,
            operation="write",
            original_error=e
        )


def get_package_directories(path: Union[str, Path]) -> List[str]:
    """
    Find all Python package directories (containing __init__.py).
    
    Parameters
    ----------
    path : str or Path
        Directory to search
    
    Returns
    -------
    List[str]
        List of package directory paths as strings
    
    Examples
    --------
    >>> get_package_directories("./src")
    ['./src/mypackage', './src/mypackage/subpackage']
    """
    path_obj = Path(path)
    packages = []
    
    for init_file in path_obj.rglob("__init__.py"):
        package_dir = init_file.parent
        packages.append(str(package_dir))
    
    return sorted(packages)


def find_import_strings(file_path: Union[str, Path]) -> List[str]:
    """
    Extract import strings from a Python file.
    
    Parameters
    ----------
    file_path : str or Path
        Path to Python file
    
    Returns
    -------
    List[str]
        List of imported package names
    
    Examples
    --------
    >>> find_import_strings("main.py")
    ['os', 'sys', 'requests', 'django']
    """
    path_obj = Path(file_path)
    
    if not path_obj.exists() or not path_obj.suffix == '.py':
        return []
    
    imports = set()
    import_patterns = [
        r'^\s*import\s+(\w+)',
        r'^\s*from\s+(\w+(?:\.\w+)*)\s+import',
    ]
    
    try:
        content = path_obj.read_text(encoding='utf-8')
        
        for pattern in import_patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                module = match.group(1).split('.')[0]
                if module:
                    imports.add(module)
        
        return sorted(imports)
        
    except (OSError, UnicodeDecodeError):
        return []


def calculate_checksum(path: Union[str, Path], algorithm: str = 'sha256') -> str:
    """
    Calculate file checksum/hash.
    
    Parameters
    ----------
    path : str or Path
        Path to file
    algorithm : str, default='sha256'
        Hash algorithm (md5, sha1, sha256, sha512)
    
    Returns
    -------
    str
        Hexadecimal hash string, or empty string on error
    
    Examples
    --------
    >>> calculate_checksum("file.txt")
    'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    """
    try:
        hash_func = hashlib.new(algorithm)
    except ValueError:
        return ""
    
    try:
        path_obj = Path(path)
        with path_obj.open('rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hash_func.update(chunk)
        return hash_func.hexdigest()
    except (OSError, FileNotFoundError):
        return ""


def get_disk_usage(path: Union[str, Path]) -> Dict[str, int]:
    """
    Get disk usage statistics for a path.
    
    Parameters
    ----------
    path : str or Path
        Path to check
    
    Returns
    -------
    Dict[str, int]
        Dictionary with 'total', 'used', 'free' bytes
    
    Examples
    --------
    >>> usage = get_disk_usage("/home")
    >>> print(f"Free: {usage['free'] / (1024**3):.1f} GB")
    """
    path_obj = Path(path)
    
    try:
        if sys.platform == 'win32':
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                str(path_obj), None, ctypes.byref(total_bytes), ctypes.byref(free_bytes)
            )
            used_bytes = total_bytes.value - free_bytes.value
            return {
                'total': total_bytes.value,
                'used': used_bytes,
                'free': free_bytes.value
            }
        else:
            statvfs = os.statvfs(str(path_obj))
            total = statvfs.f_frsize * statvfs.f_blocks
            free = statvfs.f_frsize * statvfs.f_bavail
            used = total - (statvfs.f_frsize * statvfs.f_bfree)
            return {'total': total, 'used': used, 'free': free}
    except Exception:
        return {'total': 0, 'used': 0, 'free': 0}


# Import re for pattern matching
import re


# Module-level warning for platform-specific features
def _check_platform():
    """Log platform information for debugging."""
    warnings.warn(
        f"Filesystem utilities initialized for platform: {sys.platform}",
        UserWarning,
        stacklevel=2
    )


_check_platform()