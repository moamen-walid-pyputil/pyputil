#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Utility functions and constants for cfast.

This module provides comprehensive helper functions for:
- Atomic file operations with platform-specific optimizations
- Compiler version detection and validation
- C type mapping with extended platform support
- Source code analysis and function extraction
- String and path sanitization for security
- Performance monitoring and benchmarking
- Cross-platform file system operations

Security Features
-----------------
- Path traversal prevention
- Atomic file operations to prevent race conditions
- Input validation and sanitization
- Secure temporary file handling
- Platform-specific permission management

Constants
---------
CTYPE_MAP : Dict[Tuple[str, ...], type]
    Mapping from C type name tuples to ctypes types.
EXTENDED_CTYPE_MAP : Dict[Tuple[str, ...], type]
    Extended mapping with platform-specific types.
SIGNEDNESS_MAP : Dict[str, type]
    Mapping between signed and unsigned integer types.
TYPE_SIZE_MAP : Dict[type, int]
    Typical sizes of ctypes types in bytes.
C_KEYWORDS : Set[str]
    Set of C language keywords for validation.
RESERVED_IDENTIFIERS : Set[str]
    Reserved identifiers that should not be used.

Functions
---------
atomic_write
    Write content to a file atomically with platform optimizations.
atomic_read
    Read content from a file atomically.
safe_path_join
    Safely join path components preventing traversal attacks.
sanitize_filename
    Sanitize a string for use as a filename.
sanitize_identifier
    Sanitize a string for use as a C identifier.
get_compiler_version
    Get detailed version information from a compiler.
validate_compiler_executable
    Validate that a compiler executable is usable.
extract_function_names
    Extract function names from C code with enhanced accuracy.
extract_struct_names
    Extract struct/union/enum names from C code.
extract_includes
    Extract #include directives from C code.
detect_c_standard
    Detect C standard version from code features.
calculate_code_hash
    Calculate deterministic hash of C code.
measure_execution_time
    Context manager for measuring execution time.
normalize_path
    Normalize a path for consistent comparison.
is_subpath
    Check if a path is a subpath of another safely.
get_system_temp_dir
    Get system temporary directory with fallback.
create_secure_temp_file
    Create a temporary file with secure permissions.
remove_file_safely
    Safely remove a file with retry logic.
get_file_info
    Get comprehensive file information.
format_size
    Format byte size in human-readable format.

Examples
--------
>>> from cfast.utils import atomic_write, sanitize_identifier, extract_function_names
>>> 
>>> # Write file atomically
>>> atomic_write(Path('config.txt'), 'key=value')
>>> 
>>> # Sanitize identifier
>>> clean_name = sanitize_identifier('my-function!@#123')
>>> print(clean_name)  # 'my_function_123'
>>> 
>>> # Extract function names
>>> code = '''
... int add(int a, int b) { return a + b; }
... static void helper(void) { }
... '''
>>> functions = extract_function_names(code)
>>> print(functions)  # ['add', 'helper']
"""

import ctypes
import subprocess
import tempfile
import os
import sys
import re
import time
import hashlib
import shutil
import stat
import errno
import warnings
import contextlib
from pathlib import Path
from typing import Dict, Tuple, List, Optional, Set, Any, Union, Iterator, Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import lru_cache, wraps


# =============================================================================
# Constants
# =============================================================================

# Basic C type mapping
CTYPE_MAP: Dict[Tuple[str, ...], type] = {
    # Basic integer types
    ('int',): ctypes.c_int,
    ('char',): ctypes.c_char,
    ('signed', 'char'): ctypes.c_byte,
    ('unsigned', 'char'): ctypes.c_ubyte,
    ('short',): ctypes.c_short,
    ('signed', 'short'): ctypes.c_short,
    ('unsigned', 'short'): ctypes.c_ushort,
    ('long',): ctypes.c_long,
    ('signed', 'long'): ctypes.c_long,
    ('unsigned', 'long'): ctypes.c_ulong,
    ('long', 'long'): ctypes.c_longlong,
    ('signed', 'long', 'long'): ctypes.c_longlong,
    ('unsigned', 'long', 'long'): ctypes.c_ulonglong,
    
    # Explicit signed/unsigned int
    ('signed', 'int'): ctypes.c_int,
    ('unsigned', 'int'): ctypes.c_uint,
    ('signed',): ctypes.c_int,
    ('unsigned',): ctypes.c_uint,
    
    # Floating point types
    ('float',): ctypes.c_float,
    ('double',): ctypes.c_double,
    ('long', 'double'): ctypes.c_longdouble,
    ('float', '_Complex'): ctypes.c_void_p,  # Not directly supported
    ('double', '_Complex'): ctypes.c_void_p,
    ('long', 'double', '_Complex'): ctypes.c_void_p,
    
    # Special types
    ('void',): None,
    ('size_t',): ctypes.c_size_t,
    ('ssize_t',): ctypes.c_ssize_t,
    ('ptrdiff_t',): ctypes.c_ssize_t,
    ('intptr_t',): ctypes.c_void_p,
    ('uintptr_t',): ctypes.c_void_p,
    ('wchar_t',): ctypes.c_wchar,
    
    # Fixed-width integer types (stdint.h)
    ('int8_t',): ctypes.c_int8,
    ('uint8_t',): ctypes.c_uint8,
    ('int16_t',): ctypes.c_int16,
    ('uint16_t',): ctypes.c_uint16,
    ('int32_t',): ctypes.c_int32,
    ('uint32_t',): ctypes.c_uint32,
    ('int64_t',): ctypes.c_int64,
    ('uint64_t',): ctypes.c_uint64,
    
    # Fast and least width types
    ('int_fast8_t',): ctypes.c_int8,
    ('uint_fast8_t',): ctypes.c_uint8,
    ('int_fast16_t',): ctypes.c_int16,
    ('uint_fast16_t',): ctypes.c_uint16,
    ('int_fast32_t',): ctypes.c_int32,
    ('uint_fast32_t',): ctypes.c_uint32,
    ('int_fast64_t',): ctypes.c_int64,
    ('uint_fast64_t',): ctypes.c_uint64,
    ('int_least8_t',): ctypes.c_int8,
    ('uint_least8_t',): ctypes.c_uint8,
    ('int_least16_t',): ctypes.c_int16,
    ('uint_least16_t',): ctypes.c_uint16,
    ('int_least32_t',): ctypes.c_int32,
    ('uint_least32_t',): ctypes.c_uint32,
    ('int_least64_t',): ctypes.c_int64,
    ('uint_least64_t',): ctypes.c_uint64,
    
    # Max-width types
    ('intmax_t',): ctypes.c_int64,
    ('uintmax_t',): ctypes.c_uint64,
    
    # Boolean types
    ('bool',): ctypes.c_bool,
    ('_Bool',): ctypes.c_bool,
    
    # Time types
    ('time_t',): ctypes.c_long,
    ('clock_t',): ctypes.c_long,
    ('suseconds_t',): ctypes.c_long,
    ('useconds_t',): ctypes.c_uint,
    
    # File and I/O types
    ('FILE',): ctypes.c_void_p,
    ('fpos_t',): ctypes.c_longlong,
    
    # Platform-specific type aliases
    ('__int8_t',): ctypes.c_int8,
    ('__uint8_t',): ctypes.c_uint8,
    ('__int16_t',): ctypes.c_int16,
    ('__uint16_t',): ctypes.c_uint16,
    ('__int32_t',): ctypes.c_int32,
    ('__uint32_t',): ctypes.c_uint32,
    ('__int64_t',): ctypes.c_int64,
    ('__uint64_t',): ctypes.c_uint64,
}


# Extended type map for backward compatibility
EXTENDED_CTYPE_MAP = CTYPE_MAP


# Mapping between signed and unsigned types
SIGNEDNESS_MAP: Dict[type, type] = {
    ctypes.c_int8: ctypes.c_uint8,
    ctypes.c_int16: ctypes.c_uint16,
    ctypes.c_int32: ctypes.c_uint32,
    ctypes.c_int64: ctypes.c_uint64,
    ctypes.c_byte: ctypes.c_ubyte,
    ctypes.c_short: ctypes.c_ushort,
    ctypes.c_int: ctypes.c_uint,
    ctypes.c_long: ctypes.c_ulong,
    ctypes.c_longlong: ctypes.c_ulonglong,
    
    ctypes.c_uint8: ctypes.c_int8,
    ctypes.c_uint16: ctypes.c_int16,
    ctypes.c_uint32: ctypes.c_int32,
    ctypes.c_uint64: ctypes.c_int64,
    ctypes.c_ubyte: ctypes.c_byte,
    ctypes.c_ushort: ctypes.c_short,
    ctypes.c_uint: ctypes.c_int,
    ctypes.c_ulong: ctypes.c_long,
    ctypes.c_ulonglong: ctypes.c_longlong,
}


# Typical sizes of ctypes types in bytes
TYPE_SIZE_MAP: Dict[type, int] = {
    ctypes.c_int8: 1,
    ctypes.c_uint8: 1,
    ctypes.c_int16: 2,
    ctypes.c_uint16: 2,
    ctypes.c_int32: 4,
    ctypes.c_uint32: 4,
    ctypes.c_int64: 8,
    ctypes.c_uint64: 8,
    ctypes.c_byte: 1,
    ctypes.c_ubyte: 1,
    ctypes.c_char: 1,
    ctypes.c_wchar: 2 if sys.platform.startswith('win') else 4,
    ctypes.c_short: 2,
    ctypes.c_ushort: 2,
    ctypes.c_int: 4,
    ctypes.c_uint: 4,
    ctypes.c_long: 8 if sys.maxsize > 2**32 else 4,
    ctypes.c_ulong: 8 if sys.maxsize > 2**32 else 4,
    ctypes.c_longlong: 8,
    ctypes.c_ulonglong: 8,
    ctypes.c_float: 4,
    ctypes.c_double: 8,
    ctypes.c_longdouble: 16 if sys.platform != 'win32' else 8,
    ctypes.c_size_t: 8 if sys.maxsize > 2**32 else 4,
    ctypes.c_ssize_t: 8 if sys.maxsize > 2**32 else 4,
    ctypes.c_void_p: 8 if sys.maxsize > 2**32 else 4,
    ctypes.c_bool: 1,
}


# C language keywords (C11)
C_KEYWORDS: Set[str] = {
    '_Alignas', '_Alignof', '_Atomic', '_Bool', '_Complex', '_Generic',
    '_Imaginary', '_Noreturn', '_Static_assert', '_Thread_local',
    'auto', 'break', 'case', 'char', 'const', 'continue', 'default',
    'do', 'double', 'else', 'enum', 'extern', 'float', 'for', 'goto',
    'if', 'inline', 'int', 'long', 'register', 'restrict', 'return',
    'short', 'signed', 'sizeof', 'static', 'struct', 'switch', 'typedef',
    'union', 'unsigned', 'void', 'volatile', 'while',
}


# Reserved identifiers (starting with underscore or containing double underscore)
RESERVED_IDENTIFIER_PATTERNS = [
    r'^_.*',           # Starts with underscore
    r'.*__.*',         # Contains double underscore
    r'^[0-9].*',       # Starts with digit
]


# Common C standard library function names
C_STANDARD_FUNCTIONS: Set[str] = {
    # stdio.h
    'printf', 'scanf', 'fprintf', 'fscanf', 'sprintf', 'sscanf',
    'fopen', 'fclose', 'fread', 'fwrite', 'fseek', 'ftell', 'rewind',
    'fgets', 'fputs', 'getc', 'putc', 'getchar', 'putchar', 'puts',
    'remove', 'rename', 'tmpfile', 'tmpnam', 'fflush', 'setbuf', 'setvbuf',
    'perror', 'feof', 'ferror', 'clearerr',
    
    # stdlib.h
    'malloc', 'calloc', 'realloc', 'free', 'exit', 'abort', 'atexit',
    'system', 'getenv', 'setenv', 'unsetenv', 'putenv',
    'atoi', 'atol', 'atoll', 'atof', 'strtod', 'strtof', 'strtold',
    'strtol', 'strtoll', 'strtoul', 'strtoull',
    'rand', 'srand', 'qsort', 'bsearch', 'abs', 'labs', 'llabs',
    'div', 'ldiv', 'lldiv',
    
    # string.h
    'strcpy', 'strncpy', 'strcat', 'strncat', 'strcmp', 'strncmp',
    'strchr', 'strrchr', 'strstr', 'strlen', 'strdup', 'strndup',
    'memcpy', 'memmove', 'memset', 'memcmp', 'memchr',
    'strerror', 'strtok', 'strcoll', 'strxfrm',
    
    # math.h
    'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'atan2',
    'sinh', 'cosh', 'tanh', 'exp', 'log', 'log10', 'pow', 'sqrt',
    'ceil', 'floor', 'fabs', 'fmod', 'round', 'trunc',
    
    # ctype.h
    'isalnum', 'isalpha', 'iscntrl', 'isdigit', 'isgraph', 'islower',
    'isprint', 'ispunct', 'isspace', 'isupper', 'isxdigit',
    'tolower', 'toupper',
    
    # time.h
    'time', 'clock', 'difftime', 'mktime', 'strftime', 'gmtime', 'localtime',
    'asctime', 'ctime',
}


# =============================================================================
# Path and String Sanitization
# =============================================================================

def sanitize_filename(
    filename: str,
    replacement: str = '_',
    max_length: int = 255,
    allow_unicode: bool = True
) -> str:
    """
    Sanitize a string for use as a filename.
    
    Removes or replaces characters that are invalid in filenames across
    different operating systems.
    
    Parameters
    ----------
    filename : str
        Input string to sanitize.
    replacement : str, default '_'
        Character to replace invalid characters with.
    max_length : int, default 255
        Maximum length of the resulting filename.
    allow_unicode : bool, default True
        Whether to allow Unicode characters beyond ASCII.
    
    Returns
    -------
    str
        Sanitized filename safe for use on most file systems.
    
    Examples
    --------
    >>> sanitize_filename('my/file:name?.txt')
    'my_file_name_.txt'
    
    >>> sanitize_filename('日本語ファイル名.txt')
    '日本語ファイル名.txt'
    """
    # Characters invalid in filenames across Windows/Linux/macOS
    invalid_chars = '<>:"/\\|?*'
    
    # Control characters (ASCII 0-31)
    control_chars = ''.join(chr(i) for i in range(32))
    
    # Build translation table
    if allow_unicode:
        # Only replace ASCII invalid/control chars
        trans_table = str.maketrans({
            c: replacement for c in invalid_chars + control_chars
        })
    else:
        # Replace all non-ASCII characters
        def replace_non_ascii(c):
            if ord(c) < 32 or ord(c) > 126 or c in invalid_chars:
                return replacement
            return c
        trans_table = None
        filename = ''.join(replace_non_ascii(c) for c in filename)
    
    if trans_table:
        filename = filename.translate(trans_table)
    
    # Remove leading/trailing spaces and dots (problematic on Windows)
    filename = filename.strip(' .')
    
    # Truncate if too long (preserve extension if possible)
    if len(filename) > max_length:
        if '.' in filename:
            name, ext = filename.rsplit('.', 1)
            max_name_len = max_length - len(ext) - 1
            if max_name_len > 0:
                filename = f"{name[:max_name_len]}.{ext}"
            else:
                filename = filename[:max_length]
        else:
            filename = filename[:max_length]
    
    # Ensure filename is not empty
    if not filename:
        filename = 'unnamed'
    
    return filename


def sanitize_identifier(
    identifier: str,
    replacement: str = '_',
    preserve_case: bool = True,
    check_reserved: bool = True
) -> str:
    """
    Sanitize a string for use as a C identifier.
    
    Converts the input to a valid C identifier by replacing invalid
    characters and ensuring it doesn't start with a digit.
    
    Parameters
    ----------
    identifier : str
        Input string to sanitize.
    replacement : str, default '_'
        Character to replace invalid characters with.
    preserve_case : bool, default True
        Whether to preserve original case.
    check_reserved : bool, default True
        Whether to check against C keywords and add suffix if needed.
    
    Returns
    -------
    str
        Valid C identifier.
    
    Raises
    ------
    ValueError
        If identifier cannot be sanitized to a valid C identifier.
    
    Examples
    --------
    >>> sanitize_identifier('my-function!@#123')
    'my_function_123'
    
    >>> sanitize_identifier('123invalid')
    '_123invalid'
    
    >>> sanitize_identifier('int')
    'int_'  # Avoids C keyword
    """
    if not identifier:
        raise ValueError("Identifier cannot be empty")
    
    # Convert to string and strip
    identifier = str(identifier).strip()
    
    if not preserve_case:
        identifier = identifier.lower()
    
    # Replace invalid characters
    valid_chars = []
    for i, char in enumerate(identifier):
        if i == 0:
            # First character: letter or underscore
            if char.isalpha() or char == '_':
                valid_chars.append(char)
            else:
                valid_chars.append('_')
                if char.isdigit():
                    valid_chars.append(char)
        else:
            # Subsequent characters: alphanumeric or underscore
            if char.isalnum() or char == '_':
                valid_chars.append(char)
            else:
                valid_chars.append(replacement)
    
    result = ''.join(valid_chars)
    
    # Remove consecutive underscores
    while '__' in result:
        result = result.replace('__', '_')
    
    # Remove trailing underscores
    result = result.rstrip('_')
    
    # Ensure it doesn't start with a digit
    if result and result[0].isdigit():
        result = '_' + result
    
    # Check against C keywords
    if check_reserved and result in C_KEYWORDS:
        result = result + '_'
    
    # Check against reserved identifier patterns
    if check_reserved:
        import re
        for pattern in RESERVED_IDENTIFIER_PATTERNS:
            if re.match(pattern, result):
                warnings.warn(
                    f"Identifier '{result}' matches reserved pattern '{pattern}'",
                    UserWarning,
                    stacklevel=2
                )
    
    if not result:
        result = 'unnamed'
    
    return result


def safe_path_join(base: Path, *paths: Union[str, Path]) -> Path:
    """
    Safely join path components preventing directory traversal attacks.
    
    Parameters
    ----------
    base : Path
        Base directory path.
    *paths : Union[str, Path]
        Additional path components to join.
    
    Returns
    -------
    Path
        Resolved path guaranteed to be within base directory.
    
    Raises
    ------
    ValueError
        If the resulting path escapes the base directory.
    
    Examples
    --------
    >>> safe_path_join(Path('/safe'), 'subdir', 'file.txt')
    PosixPath('/safe/subdir/file.txt')
    
    >>> safe_path_join(Path('/safe'), '../escape.txt')
    ValueError: Path escapes base directory
    """
    base = base.resolve()
    
    # Join and resolve the full path
    full_path = base.joinpath(*paths).resolve()
    
    # Check if the resolved path is within the base directory
    try:
        full_path.relative_to(base)
    except ValueError:
        raise ValueError(
            f"Path '{full_path}' escapes base directory '{base}'. "
            "Directory traversal detected."
        )
    
    return full_path


def normalize_path(path: Union[str, Path]) -> Path:
    """
    Normalize a path for consistent comparison.
    
    Resolves the path, converts to absolute, and normalizes case
    on case-insensitive file systems.
    
    Parameters
    ----------
    path : Union[str, Path]
        Path to normalize.
    
    Returns
    -------
    Path
        Normalized path.
    
    Examples
    --------
    >>> normalize_path('/tmp/../tmp/file.txt')
    PosixPath('/tmp/file.txt')
    """
    path = Path(path).expanduser().resolve()
    
    # On Windows, also normalize case
    if sys.platform.startswith('win'):
        try:
            # Get the actual case from the file system
            import win32api
            long_path = win32api.GetLongPathName(str(path))
            return Path(long_path)
        except (ImportError, Exception):
            # Fallback to lowercasing
            return Path(str(path).lower())
    
    return path


def is_subpath(path: Path, parent: Path) -> bool:
    """
    Check if a path is a subpath of another safely.
    
    Parameters
    ----------
    path : Path
        Path to check.
    parent : Path
        Potential parent directory.
    
    Returns
    -------
    bool
        True if path is within parent, False otherwise.
    
    Examples
    --------
    >>> is_subpath(Path('/a/b/c'), Path('/a'))
    True
    
    >>> is_subpath(Path('/a/b/c'), Path('/b'))
    False
    """
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# =============================================================================
# File Operations
# =============================================================================

def atomic_write(
    path: Path,
    content: Union[str, bytes],
    encoding: str = 'utf-8',
    mode: int = 0o644,
    fsync: bool = True
) -> None:
    """
    Write content to a file atomically.
    
    Uses a temporary file in the same directory and rename to ensure
    the write is atomic. If the write fails or is interrupted, the
    original file remains unchanged.
    
    Parameters
    ----------
    path : Path
        Destination file path.
    content : Union[str, bytes]
        Content to write. String will be encoded, bytes written directly.
    encoding : str, default 'utf-8'
        Text encoding for string content.
    mode : int, default 0o644
        File permissions (Unix only, ignored on Windows).
    fsync : bool, default True
        Whether to force write to disk before rename.
    
    Raises
    ------
    OSError
        If file operations fail.
    TypeError
        If content type is not str or bytes.
    
    Examples
    --------
    >>> atomic_write(Path('config.txt'), 'key=value\\n')
    
    >>> atomic_write(Path('data.bin'), b'\\x00\\x01\\x02')
    """
    # Create parent directory if it doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Determine content type
    if isinstance(content, str):
        data = content.encode(encoding)
    elif isinstance(content, bytes):
        data = content
    else:
        raise TypeError(f"Content must be str or bytes, got {type(content).__name__}")
    
    # Create temporary file in the same directory
    fd = None
    tmp_path = None
    
    try:
        # Create temporary file
        fd, tmp_path_str = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix='.tmp'
        )
        tmp_path = Path(tmp_path_str)
        
        # Set permissions (Unix only)
        if sys.platform != 'win32':
            os.fchmod(fd, mode)
        
        # Write content
        os.write(fd, data)
        
        # Force write to disk
        if fsync:
            os.fsync(fd)
        
        os.close(fd)
        fd = None
        
        # Atomic rename (POSIX: atomic, Windows: atomic if destination doesn't exist)
        tmp_path.replace(path)
        
    except Exception:
        # Clean up temp file on failure
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        
        raise


def atomic_read(path: Path, encoding: str = 'utf-8') -> str:
    """
    Read content from a file atomically.
    
    Reads the entire file content. For atomicity, this relies on the
    file system's read operation being atomic for the file size.
    
    Parameters
    ----------
    path : Path
        Source file path.
    encoding : str, default 'utf-8'
        Text encoding for decoding.
    
    Returns
    -------
    str
        File content as string.
    
    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    
    Examples
    --------
    >>> content = atomic_read(Path('config.txt'))
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    return path.read_text(encoding=encoding)


def get_system_temp_dir() -> Path:
    """
    Get system temporary directory with fallback.
    
    Returns
    -------
    Path
        Path to temporary directory.
    
    Examples
    --------
    >>> temp_dir = get_system_temp_dir()
    >>> print(temp_dir)
    /tmp
    """
    # Try environment variables first
    for var in ['TMPDIR', 'TEMP', 'TMP']:
        if var in os.environ:
            temp_path = Path(os.environ[var])
            if temp_path.exists() and temp_path.is_dir():
                return temp_path
    
    # Use Python's tempfile
    return Path(tempfile.gettempdir())


@contextlib.contextmanager
def create_secure_temp_file(
    suffix: str = '',
    prefix: str = 'tmp_',
    directory: Optional[Path] = None,
    mode: int = 0o600,
    delete: bool = True
) -> Iterator[Path]:
    """
    Create a temporary file with secure permissions.
    
    Parameters
    ----------
    suffix : str
        File suffix/extension.
    prefix : str
        File prefix.
    directory : Optional[Path]
        Directory to create file in. Uses system temp if None.
    mode : int
        File permissions (Unix only).
    delete : bool
        Whether to delete the file on context exit.
    
    Yields
    ------
    Path
        Path to the temporary file.
    
    Examples
    --------
    >>> with create_secure_temp_file(suffix='.c') as tmp_path:
    ...     tmp_path.write_text('int main() { return 0; }')
    ...     # File is automatically deleted after context
    """
    dir_path = str(directory) if directory else None
    fd, path_str = tempfile.mkstemp(
        suffix=suffix,
        prefix=prefix,
        dir=dir_path
    )
    
    # Set secure permissions
    if sys.platform != 'win32':
        os.fchmod(fd, mode)
    
    os.close(fd)
    tmp_path = Path(path_str)
    
    try:
        yield tmp_path
    finally:
        if delete:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def remove_file_safely(path: Path, retries: int = 3, delay: float = 0.1) -> bool:
    """
    Safely remove a file with retry logic.
    
    Parameters
    ----------
    path : Path
        Path to file to remove.
    retries : int, default 3
        Number of retry attempts.
    delay : float, default 0.1
        Delay between retries in seconds.
    
    Returns
    -------
    bool
        True if file was removed or didn't exist, False on failure.
    
    Examples
    --------
    >>> remove_file_safely(Path('temp.txt'))
    True
    """
    if not path.exists():
        return True
    
    for attempt in range(retries):
        try:
            path.unlink()
            return True
        except PermissionError:
            # File might be locked by another process
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                return False
        except OSError:
            return False
    
    return False


@dataclass
class FileInfo:
    """Comprehensive file information."""
    path: Path
    exists: bool
    size: int
    is_file: bool
    is_dir: bool
    is_symlink: bool
    created: Optional[float]
    modified: Optional[float]
    accessed: Optional[float]
    permissions: str
    owner: Optional[str]
    group: Optional[str]
    hash_sha256: Optional[str]


def get_file_info(path: Path, calculate_hash: bool = False) -> FileInfo:
    """
    Get comprehensive file information.
    
    Parameters
    ----------
    path : Path
        Path to file.
    calculate_hash : bool, default False
        Whether to calculate SHA-256 hash.
    
    Returns
    -------
    FileInfo
        File information dataclass.
    
    Examples
    --------
    >>> info = get_file_info(Path('data.txt'))
    >>> print(f"Size: {format_size(info.size)}")
    """
    stat_info = None
    try:
        stat_info = path.stat()
        exists = True
    except OSError:
        exists = False
    
    if not exists:
        return FileInfo(
            path=path,
            exists=False,
            size=0,
            is_file=False,
            is_dir=False,
            is_symlink=False,
            created=None,
            modified=None,
            accessed=None,
            permissions='',
            owner=None,
            group=None,
            hash_sha256=None,
        )
    
    # Parse permissions
    if sys.platform != 'win32':
        mode = stat_info.st_mode
        perms = stat.filemode(mode)
    else:
        perms = 'rwx' if path.is_file() else '---'
    
    # Get owner/group (Unix only)
    owner = None
    group = None
    if sys.platform != 'win32':
        import pwd
        import grp
        try:
            owner = pwd.getpwuid(stat_info.st_uid).pw_name
        except (KeyError, ImportError):
            pass
        try:
            group = grp.getgrgid(stat_info.st_gid).gr_name
        except (KeyError, ImportError):
            pass
    
    # Calculate hash if requested
    file_hash = None
    if calculate_hash and path.is_file():
        file_hash = calculate_code_hash(path.read_bytes())
    
    return FileInfo(
        path=path,
        exists=True,
        size=stat_info.st_size,
        is_file=path.is_file(),
        is_dir=path.is_dir(),
        is_symlink=path.is_symlink(),
        created=stat_info.st_ctime,
        modified=stat_info.st_mtime,
        accessed=stat_info.st_atime,
        permissions=perms,
        owner=owner,
        group=group,
        hash_sha256=file_hash,
    )


def format_size(size_bytes: int, binary: bool = True) -> str:
    """
    Format byte size in human-readable format.
    
    Parameters
    ----------
    size_bytes : int
        Size in bytes.
    binary : bool, default True
        If True, use binary prefixes (KiB, MiB).
        If False, use SI prefixes (KB, MB).
    
    Returns
    -------
    str
        Formatted size string.
    
    Examples
    --------
    >>> format_size(1024)
    '1.00 KiB'
    
    >>> format_size(1000, binary=False)
    '1.00 KB'
    """
    if binary:
        units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
        divisor = 1024.0
    else:
        units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        divisor = 1000.0
    
    size = float(size_bytes)
    unit_index = 0
    
    while size >= divisor and unit_index < len(units) - 1:
        size /= divisor
        unit_index += 1
    
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    else:
        return f"{size:.2f} {units[unit_index]}"


# =============================================================================
# Compiler Utilities
# =============================================================================

@dataclass
class CompilerInfo:
    """Detailed compiler information."""
    executable: str
    name: str
    version: str
    full_version: str
    target: str
    thread_model: str
    configured_with: str
    is_available: bool
    error_message: Optional[str] = None


def get_compiler_version(executable: str) -> str:
    """
    Get the version string of a compiler.
    
    Parameters
    ----------
    executable : str
        Path or name of the compiler executable.
    
    Returns
    -------
    str
        Version string from the compiler's --version output, or "unknown"
        if version cannot be determined.
    
    Examples
    --------
    >>> get_compiler_version('gcc')
    'gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0'
    """
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode == 0:
            return result.stdout.splitlines()[0].strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    
    return "unknown"


def validate_compiler_executable(executable: Union[str, Path]) -> CompilerInfo:
    """
    Validate that a compiler executable is usable.
    
    Performs comprehensive validation including version detection,
    target platform identification, and basic functionality test.
    
    Parameters
    ----------
    executable : Union[str, Path]
        Path or name of the compiler executable.
    
    Returns
    -------
    CompilerInfo
        Detailed compiler information.
    
    Examples
    --------
    >>> info = validate_compiler_executable('gcc')
    >>> if info.is_available:
    ...     print(f"Using {info.name} {info.version}")
    ...     print(f"Target: {info.target}")
    """
    exe_str = str(executable)
    info = CompilerInfo(
        executable=exe_str,
        name='unknown',
        version='unknown',
        full_version='unknown',
        target='unknown',
        thread_model='unknown',
        configured_with='unknown',
        is_available=False,
    )
    
    # Check if executable exists
    if not shutil.which(exe_str):
        info.error_message = f"Executable not found in PATH: {exe_str}"
        return info
    
    try:
        # Get version
        result = subprocess.run(
            [exe_str, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        
        if result.returncode != 0:
            info.error_message = f"Failed to execute --version: {result.stderr}"
            return info
        
        output = result.stdout
        info.full_version = output.splitlines()[0].strip()
        
        # Detect compiler name
        output_lower = output.lower()
        if 'gcc' in output_lower or 'gnu' in output_lower:
            info.name = 'gcc'
        elif 'clang' in output_lower or 'llvm' in output_lower:
            info.name = 'clang'
        elif 'microsoft' in output_lower or 'msvc' in output_lower:
            info.name = 'msvc'
        
        # Extract version
        version_match = re.search(r'(\d+\.\d+\.\d+)', output)
        if version_match:
            info.version = version_match.group(1)
        
        # Get target platform (GCC/Clang)
        if info.name in ('gcc', 'clang'):
            target_result = subprocess.run(
                [exe_str, "-dumpmachine"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False
            )
            if target_result.returncode == 0:
                info.target = target_result.stdout.strip()
        
        # Test basic compilation
        test_code = "int main(void) { return 0; }"
        with create_secure_temp_file(suffix='.c') as src_path:
            src_path.write_text(test_code)
            
            with create_secure_temp_file() as out_path:
                compile_result = subprocess.run(
                    [exe_str, str(src_path), "-o", str(out_path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False
                )
                
                if compile_result.returncode != 0:
                    info.error_message = f"Compilation test failed: {compile_result.stderr}"
                    return info
        
        info.is_available = True
        
    except subprocess.TimeoutExpired as e:
        info.error_message = f"Timeout: {e}"
    except Exception as e:
        info.error_message = str(e)
    
    return info


# =============================================================================
# C Code Analysis
# =============================================================================

def extract_function_names(code: str, include_static: bool = True) -> List[str]:
    """
    Extract function names from C code using enhanced regex.
    
    This is a fallback method when pycparser is not available.
    Handles various function definition patterns including:
    - Static and inline functions
    - Functions with pointer return types
    - Functions with complex parameter lists
    - Functions split across multiple lines
    
    Parameters
    ----------
    code : str
        C source code.
    include_static : bool, default True
        Whether to include static functions.
    
    Returns
    -------
    List[str]
        List of detected function names in order of appearance.
    
    Examples
    --------
    >>> code = '''
    ... static int helper(void) { return 0; }
    ... inline double* get_values(int n) { return NULL; }
    ... void cleanup(void) { }
    ... '''
    >>> extract_function_names(code)
    ['helper', 'get_values', 'cleanup']
    """
    # Remove comments and strings first
    clean_code = _remove_c_comments_and_strings(code)
    
    # Remove preprocessor directives
    lines = []
    for line in clean_code.split('\n'):
        stripped = line.strip()
        if not stripped.startswith('#'):
            lines.append(line)
    clean_code = '\n'.join(lines)
    
    # Pattern for function definitions
    # Matches: [static] [inline] [const] [volatile] return_type func_name(params) [const] [volatile] {
    pattern = r'''
        # Storage class and specifiers
        (?:(?:static|inline|extern|__inline__?|__static__?)\s+)*
        
        # Return type (complex pattern with pointers, const, etc.)
        (?:
            (?:const\s+)?(?:volatile\s+)?
            (?:unsigned\s+)?(?:signed\s+)?
            (?:long\s+)?(?:short\s+)?
            (?:struct\s+[\w\s\*]+|union\s+[\w\s\*]+|enum\s+[\w\s\*]+|[\w\s]+)
            (?:\s*\*+\s*)*
            (?:\s+const)?(?:\s+volatile)?
        )\s+
        
        # Function name
        ([a-zA-Z_][\w]*)\s*
        
        # Parameter list
        \(
            (?:[^()]*|\([^()]*\))*
        \)
        
        # Qualifiers after parameters
        \s*(?:const)?\s*(?:volatile)?
        
        # Opening brace
        \s*\{
    '''
    
    # Compile with verbose flag for better error messages
    compiled_pattern = re.compile(pattern, re.VERBOSE | re.MULTILINE | re.DOTALL)
    
    matches = compiled_pattern.findall(clean_code)
    
    # Filter based on static inclusion
    if not include_static:
        # Remove static functions by re-checking with static pattern
        static_pattern = r'\bstatic\s+.*?\b' + r'([a-zA-Z_][\w]*)\s*\([^)]*\)\s*\{'
        static_matches = set(re.findall(static_pattern, clean_code, re.DOTALL))
        matches = [m for m in matches if m not in static_matches]
    
    # Remove duplicates while preserving order
    seen = set()
    result = []
    for name in matches:
        if name not in seen and name not in C_KEYWORDS:
            seen.add(name)
            result.append(name)
    
    return result


def _remove_c_comments_and_strings(code: str) -> str:
    """
    Remove C comments and string literals for cleaner regex parsing.
    
    Parameters
    ----------
    code : str
        C source code.
    
    Returns
    -------
    str
        Code with comments and strings replaced by spaces.
    """
    # State machine for parsing
    result = []
    i = 0
    n = len(code)
    
    while i < n:
        # String literal
        if code[i] == '"':
            result.append(' ')
            i += 1
            while i < n and code[i] != '"':
                if code[i] == '\\':
                    i += 2
                else:
                    i += 1
            if i < n:
                i += 1
            continue
        
        # Character literal
        if code[i] == "'":
            result.append(' ')
            i += 1
            while i < n and code[i] != "'":
                if code[i] == '\\':
                    i += 2
                else:
                    i += 1
            if i < n:
                i += 1
            continue
        
        # Line comment
        if i + 1 < n and code[i:i+2] == '//':
            result.append(' ')
            while i < n and code[i] != '\n':
                i += 1
            continue
        
        # Block comment
        if i + 1 < n and code[i:i+2] == '/*':
            result.append(' ')
            i += 2
            while i + 1 < n and code[i:i+2] != '*/':
                i += 1
            if i + 1 < n:
                i += 2
            continue
        
        result.append(code[i])
        i += 1
    
    return ''.join(result)


def extract_struct_names(code: str) -> Dict[str, List[str]]:
    """
    Extract struct, union, and enum names from C code.
    
    Parameters
    ----------
    code : str
        C source code.
    
    Returns
    -------
    Dict[str, List[str]]
        Dictionary with keys 'structs', 'unions', 'enums' containing lists of names.
    
    Examples
    --------
    >>> code = '''
    ... struct Point { int x, y; };
    ... union Data { int i; float f; };
    ... enum Color { RED, GREEN, BLUE };
    ... '''
    >>> extract_struct_names(code)
    {'structs': ['Point'], 'unions': ['Data'], 'enums': ['Color']}
    """
    clean_code = _remove_c_comments_and_strings(code)
    
    struct_pattern = r'\bstruct\s+([a-zA-Z_][\w]*)\s*\{'
    union_pattern = r'\bunion\s+([a-zA-Z_][\w]*)\s*\{'
    enum_pattern = r'\benum\s+([a-zA-Z_][\w]*)\s*\{'
    
    return {
        'structs': list(set(re.findall(struct_pattern, clean_code))),
        'unions': list(set(re.findall(union_pattern, clean_code))),
        'enums': list(set(re.findall(enum_pattern, clean_code))),
    }


def extract_includes(code: str) -> List[Tuple[str, str]]:
    """
    Extract #include directives from C code.
    
    Parameters
    ----------
    code : str
        C source code.
    
    Returns
    -------
    List[Tuple[str, str]]
        List of (include_type, path) tuples.
        include_type is 'system' for <...> or 'local' for "...".
    
    Examples
    --------
    >>> code = '''
    ... #include <stdio.h>
    ... #include "mylib.h"
    ... '''
    >>> extract_includes(code)
    [('system', 'stdio.h'), ('local', 'mylib.h')]
    """
    includes = []
    
    # System includes: #include <...>
    system_pattern = r'#include\s*<([^>]+)>'
    for match in re.findall(system_pattern, code):
        includes.append(('system', match.strip()))
    
    # Local includes: #include "..."
    local_pattern = r'#include\s*"([^"]+)"'
    for match in re.findall(local_pattern, code):
        includes.append(('local', match.strip()))
    
    return includes


def detect_c_standard(code: str) -> str:
    """
    Detect C standard version from code features.
    
    Parameters
    ----------
    code : str
        C source code.
    
    Returns
    -------
    str
        Detected C standard ('c89', 'c99', 'c11', 'c17', 'c23').
    
    Examples
    --------
    >>> code = '''
    ... #include <stdbool.h>
    ... for (int i = 0; i < 10; i++) { }
    ... '''
    >>> detect_c_standard(code)
    'c99'
    """
    features = {
        'c99': [
            r'//',                    # Line comments
            r'\b(bool|true|false)\b', # Boolean type
            r'for\s*\(\s*int\s+\w',   # Loop variable declaration
            r'\b(inline|restrict)\b', # New keywords
            r'\[.*\*.*\]',            # Variable-length arrays
        ],
        'c11': [
            r'\b(_Alignas|_Alignof|_Atomic|_Generic|_Noreturn|_Static_assert|_Thread_local)\b',
            r'<stdatomic\.h>',
            r'<threads\.h>',
        ],
        'c17': [
            # C17 is mostly bug fixes, no major new features
        ],
        'c23': [
            r'\b(nullptr|true|false)\b',  # Without stdbool.h
            r'\b(constexpr|typeof|typeof_unqual)\b',
            r'\[\[.*\]\]',                 # Attributes
        ],
    }
    
    # Start with C89
    standard = 'c89'
    
    for std, patterns in features.items():
        for pattern in patterns:
            if re.search(pattern, code, re.MULTILINE):
                standard = std
                break
    
    return standard


def calculate_code_hash(code: Union[str, bytes], algorithm: str = 'sha256') -> str:
    """
    Calculate deterministic hash of C code.
    
    Normalizes whitespace and removes comments for consistent hashing.
    
    Parameters
    ----------
    code : Union[str, bytes]
        C source code.
    algorithm : str, default 'sha256'
        Hash algorithm to use.
    
    Returns
    -------
    str
        Hexadecimal hash string.
    
    Examples
    --------
    >>> code1 = "int main() { return 0; }"
    >>> code2 = "int main() {\\n    return 0;\\n}"
    >>> calculate_code_hash(code1) == calculate_code_hash(code2)
    True
    """
    if isinstance(code, bytes):
        code_str = code.decode('utf-8', errors='ignore')
    else:
        code_str = code
    
    # Normalize code
    normalized = _normalize_c_code(code_str)
    
    # Calculate hash
    hasher = hashlib.new(algorithm)
    hasher.update(normalized.encode('utf-8'))
    return hasher.hexdigest()


def _normalize_c_code(code: str) -> str:
    """
    Normalize C code for consistent hashing.
    
    Removes comments, normalizes whitespace, and standardizes formatting.
    
    Parameters
    ----------
    code : str
        C source code.
    
    Returns
    -------
    str
        Normalized code.
    """
    # Remove comments
    code = _remove_c_comments_and_strings(code)
    
    # Normalize whitespace
    code = re.sub(r'\s+', ' ', code)
    
    # Remove spaces around operators
    operators = r'([+\-*/%=&|^<>!~,;:\(\)\[\]\{\}])'
    code = re.sub(r'\s*' + operators + r'\s*', r'\1', code)
    
    # Normalize numeric constants
    code = re.sub(r'\b0[xX][0-9a-fA-F]+\b', '0xHEX', code)
    code = re.sub(r'\b\d+\b', 'NUM', code)
    
    # Remove preprocessor directives (they may vary by environment)
    lines = [line for line in code.split('\n') if not line.strip().startswith('#')]
    code = ' '.join(lines)
    
    return code.strip()


# =============================================================================
# Performance Utilities
# =============================================================================

@dataclass
class TimingResult:
    """Result of a timing measurement."""
    elapsed: float
    start_time: float
    end_time: float
    iterations: int = 1
    
    @property
    def average(self) -> float:
        """Average time per iteration."""
        return self.elapsed / self.iterations
    
    @property
    def ops_per_second(self) -> float:
        """Operations per second."""
        if self.elapsed > 0:
            return self.iterations / self.elapsed
        return float('inf')


@contextlib.contextmanager
def measure_execution_time(
    name: Optional[str] = None,
    iterations: int = 1
) -> Iterator[Callable[[], TimingResult]]:
    """
    Context manager for measuring execution time.
    
    Parameters
    ----------
    name : Optional[str]
        Optional name for logging.
    iterations : int, default 1
        Number of iterations to measure.
    
    Yields
    ------
    Callable[[], TimingResult]
        Function that returns timing result when called.
    
    Examples
    --------
    >>> with measure_execution_time('my_func') as get_time:
    ...     result = my_function()
    >>> timing = get_time()
    >>> print(f"Took {timing.elapsed:.3f}s")
    """
    start = time.perf_counter()
    
    timing_result = None
    
    def get_result() -> TimingResult:
        nonlocal timing_result
        if timing_result is None:
            end = time.perf_counter()
            timing_result = TimingResult(
                elapsed=end - start,
                start_time=start,
                end_time=end,
                iterations=iterations,
            )
        return timing_result
    
    try:
        yield get_result
    finally:
        result = get_result()
        if name:
            print(f"[{name}] Completed in {result.elapsed:.4f}s")


def time_function(func: Callable) -> Callable:
    """
    Decorator to measure function execution time.
    
    Parameters
    ----------
    func : Callable
        Function to time.
    
    Returns
    -------
    Callable
        Wrapped function that prints timing information.
    
    Examples
    --------
    >>> @time_function
    ... def slow_function():
    ...     time.sleep(1)
    >>> slow_function()
    [slow_function] Completed in 1.0002s
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        with measure_execution_time(func.__name__) as get_time:
            result = func(*args, **kwargs)
        return result
    return wrapper


# =============================================================================
# Backward Compatibility
# =============================================================================

# Aliases for backward compatibility
atomic_write_file = atomic_write
get_compiler_info = validate_compiler_executable


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Constants
    'CTYPE_MAP',
    'EXTENDED_CTYPE_MAP',
    'SIGNEDNESS_MAP',
    'TYPE_SIZE_MAP',
    'C_KEYWORDS',
    'C_STANDARD_FUNCTIONS',
    
    # Path utilities
    'sanitize_filename',
    'sanitize_identifier',
    'safe_path_join',
    'normalize_path',
    'is_subpath',
    
    # File operations
    'atomic_write',
    'atomic_read',
    'get_system_temp_dir',
    'create_secure_temp_file',
    'remove_file_safely',
    'get_file_info',
    'format_size',
    'FileInfo',
    
    # Compiler utilities
    'get_compiler_version',
    'validate_compiler_executable',
    'CompilerInfo',
    
    # C code analysis
    'extract_function_names',
    'extract_struct_names',
    'extract_includes',
    'detect_c_standard',
    'calculate_code_hash',
    
    # Performance
    'measure_execution_time',
    'time_function',
    'TimingResult',
    
    # Backward compatibility
    'atomic_write_file',
    'get_compiler_info',
]