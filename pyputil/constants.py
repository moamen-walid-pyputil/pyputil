#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Python Import System Constants - Comprehensive Reference
=========================================================

A complete, production-grade collection of all constants related to Python's
import system, module loading, and importlib machinery. This module serves as
the single source of truth for import-related configuration, paths, flags,
and metadata across all Python implementations and platforms.

This module aggregates constants from:
- sys module (interpreter state and configuration)
- sysconfig (build-time configuration)
- importlib.machinery (import system components)
- importlib.util (import utilities)
- site (site-specific configuration)
- platform (system information)
- pkgutil (package utilities)
- zipimport (zip archive imports)

Features
--------
- Complete import path enumeration (site-packages, user-site, stdlib, etc.)
- Bytecode and cache configuration constants
- Module and extension suffixes for all platforms
- Import machinery class references for introspection
- Runtime flags affecting import behavior
- Platform-specific constants for cross-platform compatibility
- Frozen/embedded Python detection
- Namespace package markers
- All standard library paths

Examples
--------
>>> from pyputil.constants.import_system import (
...     SITE_PACKAGES, STDLIB_PATH, EXTENSION_SUFFIXES, MAGIC_NUMBER
... )
>>> 
>>> # Check if a path is in site-packages
>>> def is_site_package(path):
...     return any(path.startswith(sp) for sp in SITE_PACKAGES)
...
>>> # Get current Python's bytecode magic number
>>> print(f"Magic number: {MAGIC_NUMBER.hex()}")
>>> 
>>> # List all C extension suffixes
>>> print(EXTENSION_SUFFIXES)
>>> 
>>> # Check if running in frozen environment
>>> from pyputil.constants.import_system import IS_FROZEN
>>> if IS_FROZEN:
...     print(f"Running frozen: {FROZEN_EXECUTABLE}")

References
----------
- importlib: https://docs.python.org/3/library/importlib.html
- sys: https://docs.python.org/3/library/sys.html
- sysconfig: https://docs.python.org/3/library/sysconfig.html
- PEP 302: New Import Hooks
- PEP 3147: PYC Repository Directories
- PEP 420: Implicit Namespace Packages
- PEP 451: ModuleSpec Type
- PEP 488: Elimination of PYO files
- PEP 552: Deterministic pycs
"""

import sys
import sysconfig
import importlib.machinery
import importlib.util
import importlib.abc
import importlib.metadata
import os
import platform
import zipimport
import pkgutil
import site
import struct
import marshal
import warnings
from pathlib import Path
from typing import Tuple, List, Dict, Optional, Any, Union, FrozenSet, Callable

# ==============================================================================
# Core Path and Environment Constants
# ==============================================================================

# ------------------------------------------------------------------------------
# Site Packages Paths
# ------------------------------------------------------------------------------

def _get_site_packages() -> Tuple[str, ...]:
    """
    Get system-wide third-party package installation directories.
    
    These are directories where pip installs packages.
    Examples: /usr/lib/python3.x/site-packages (Unix), 
              C:\\Python3x\\Lib\\site-packages (Windows)
    
    Returns
    -------
    Tuple[str, ...]
        Tuple of site-package directory paths.
    """
    try:
        return tuple(site.getsitepackages())
    except Exception:
        # Fallback for virtual environments or restricted environments
        return ()


SITE_PACKAGES: Tuple[str, ...] = _get_site_packages()
"""
System-wide third-party package installation directories.

These are directories where pip installs packages.
Examples:
    - Unix: /usr/lib/python3.x/site-packages
    - Windows: C:\\Python3x\\Lib\\site-packages
    - macOS: /Library/Python/3.x/site-packages

Type: Tuple[str, ...]
"""


def _get_user_site() -> str:
    """
    Get user-specific third-party package directory.
    
    Typically located in the user's home directory.
    Example: ~/.local/lib/python3.x/site-packages (Unix)
    
    Returns
    -------
    str
        User site-packages directory path.
    """
    try:
        return site.getusersitepackages()
    except Exception:
        return ""


USER_SITE: str = _get_user_site()
"""
User-specific third-party package directory.

Typically located in the user's home directory.
Examples:
    - Unix: ~/.local/lib/python3.x/site-packages
    - Windows: %APPDATA%\\Python\\Python3x\\site-packages
    - macOS: ~/Library/Python/3.x/lib/python/site-packages

Type: str
"""


def _get_enabled_user_site() -> bool:
    """
    Check if user site-packages directory is enabled.
    
    Returns
    -------
    bool
        True if user site-packages is in sys.path.
    """
    try:
        return site.ENABLE_USER_SITE
    except AttributeError:
        return hasattr(site, 'getusersitepackages') and USER_SITE in sys.path


ENABLE_USER_SITE: bool = _get_enabled_user_site()
"""
Whether user site-packages directory is enabled.

Controlled by PYTHONNOUSERSITE environment variable or -s flag.
When False, user site-packages is not added to sys.path.

Type: bool
"""

# ------------------------------------------------------------------------------
# Python Search Paths
# ------------------------------------------------------------------------------

PYTHON_PATH: Tuple[str, ...] = tuple(sys.path)
"""
Complete Python module search path (sys.path).

Includes all directories where Python looks for modules and packages:
    - Current directory
    - PYTHONPATH environment variable directories
    - Standard library paths
    - Site-packages directories
    - .pth file directories

Note: This is a snapshot at import time. Use sys.path for live access.

Type: Tuple[str, ...]
"""


def _get_stdlib_path() -> str:
    """
    Get standard library directory path.
    
    Returns
    -------
    str
        Standard library path.
    """
    paths = sysconfig.get_paths()
    return paths.get("stdlib", paths.get("purelib", ""))


STDLIB_PATH: str = _get_stdlib_path()
"""
Standard library directory path.

Contains core Python modules (e.g., os, sys, json, collections).
Examples:
    - Unix: /usr/lib/python3.x
    - Windows: C:\\Python3x\\Lib

Type: str
"""


def _get_purelib_path() -> str:
    """
    Get pure Python library directory.
    
    Returns
    -------
    str
        Platform-independent pure Python modules location.
    """
    return sysconfig.get_paths().get("purelib", "")


PURELIB_PATH: str = _get_purelib_path()
"""
Pure Python library directory.

Platform-independent pure Python modules location.
Part of the standard library that doesn't depend on platform.

Type: str
"""


def _get_platlib_path() -> str:
    """
    Get platform-specific library directory.
    
    Returns
    -------
    str
        Platform-dependent Python modules location.
    """
    return sysconfig.get_paths().get("platlib", "")


PLATLIB_PATH: str = _get_platlib_path()
"""
Platform-specific library directory.

Contains platform-dependent Python modules (e.g., binary extensions,
platform-specific pure Python modules).

Type: str
"""


def _get_platstdlib_path() -> str:
    """
    Get platform-specific standard library directory.
    
    Returns
    -------
    str
        Platform-specific standard library path.
    """
    return sysconfig.get_paths().get("platstdlib", PLATLIB_PATH)


PLATSTDLIB_PATH: str = _get_platstdlib_path()
"""
Platform-specific standard library directory.

Contains platform-specific standard library modules.

Type: str
"""

# ------------------------------------------------------------------------------
# Header and Include Paths
# ------------------------------------------------------------------------------

def _get_include_path() -> str:
    """
    Get Python header files directory.
    
    Returns
    -------
    str
        Include directory path.
    """
    return sysconfig.get_paths().get("include", "")


INCLUDE_PATH: str = _get_include_path()
"""
Python header files directory.

Contains Python C API headers (Python.h, etc.) for extension development.
Examples:
    - Unix: /usr/include/python3.x
    - Windows: C:\\Python3x\\include

Type: str
"""


def _get_platinclude_path() -> str:
    """
    Get platform-specific header files directory.
    
    Returns
    -------
    str
        Platform-specific include directory.
    """
    return sysconfig.get_paths().get("platinclude", INCLUDE_PATH)


PLATINCLUDE_PATH: str = _get_platinclude_path()
"""
Platform-specific header files directory.

Contains platform-specific Python headers (e.g., pyconfig.h).

Type: str
"""

# ------------------------------------------------------------------------------
# Scripts and Data Paths
# ------------------------------------------------------------------------------

def _get_scripts_path() -> str:
    """
    Get executable scripts directory.
    
    Returns
    -------
    str
        Scripts directory path.
    """
    return sysconfig.get_paths().get("scripts", "")


SCRIPTS_PATH: str = _get_scripts_path()
"""
Executable scripts directory.

Where Python scripts and entry points are installed (e.g., pip, pytest).
Examples:
    - Unix: /usr/bin
    - Windows: C:\\Python3x\\Scripts

Type: str
"""


def _get_data_path() -> str:
    """
    Get data files directory.
    
    Returns
    -------
    str
        Data directory path.
    """
    return sysconfig.get_paths().get("data", "")


DATA_PATH: str = _get_data_path()
"""
Data files directory.

Contains Python package data files (resources, documentation, etc.).
Examples:
    - Unix: /usr/share
    - Windows: C:\\Python3x

Type: str
"""

# ------------------------------------------------------------------------------
# Executable and Prefix Paths
# ------------------------------------------------------------------------------

EXECUTABLE: str = sys.executable
"""
Path to the Python interpreter executable.

The actual binary being used to run this code.
Examples:
    - Unix: /usr/bin/python3
    - Windows: C:\\Python3x\\python.exe
    - Virtual env: /path/to/venv/bin/python

Type: str
"""


EXECUTABLE_DIR: str = os.path.dirname(sys.executable)
"""
Directory containing the Python interpreter executable.

Parent directory of the Python executable.

Type: str
"""


PREFIX: str = sys.prefix
"""
Installation prefix for Python.

The root directory of the Python installation.
Examples:
    - Unix: /usr or /usr/local
    - Windows: C:\\Python3x
    - Virtual env: /path/to/venv

Type: str
"""


BASE_PREFIX: str = sys.base_prefix
"""
Base installation prefix.

The prefix of the base Python installation (not a virtual environment).
In a virtual environment, this points to the system Python.

Type: str
"""


EXEC_PREFIX: str = sys.exec_prefix
"""
Executable prefix for Python.

Directory where platform-dependent Python files are installed.
Often same as PREFIX.

Type: str
"""


BASE_EXEC_PREFIX: str = sys.base_exec_prefix
"""
Base executable prefix.

The exec_prefix of the base Python installation.

Type: str
"""


PYTHON_HOME: str = os.path.dirname(sys.executable)
"""
Python executable home directory.

Directory where the Python executable is located.

Type: str
"""


def _is_virtual_env() -> bool:
    """
    Check if running in a virtual environment.
    
    Returns
    -------
    bool
        True if in virtual environment.
    """
    return (
        hasattr(sys, 'real_prefix') or
        sys.base_prefix != sys.prefix or
        (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    )


IS_VIRTUAL_ENV: bool = _is_virtual_env()
"""
Whether running in a virtual environment.

True if in venv, virtualenv, or conda environment.

Type: bool
"""


def _get_virtual_env_path() -> Optional[str]:
    """
    Get virtual environment path if applicable.
    
    Returns
    -------
    Optional[str]
        Virtual environment path or None.
    """
    if IS_VIRTUAL_ENV:
        return sys.prefix
    return os.environ.get('VIRTUAL_ENV')


VIRTUAL_ENV_PATH: Optional[str] = _get_virtual_env_path()
"""
Virtual environment path if running in one.

Set to sys.prefix for virtual environments, or VIRTUAL_ENV from environment.

Type: Optional[str]
"""

# ------------------------------------------------------------------------------
# Library Directory Constants
# ------------------------------------------------------------------------------

def _get_libdir() -> Optional[str]:
    """
    Get platform-specific library directory.
    
    Returns
    -------
    Optional[str]
        Library directory path or None.
    """
    return sysconfig.get_config_var("LIBDIR")


PLATFORM_LIBDIR: Optional[str] = _get_libdir()
"""
Platform-specific library directory.

Usually /usr/lib or /usr/lib64 on Unix systems.
None if not configured.

Type: Optional[str]
"""


def _get_libdest() -> Optional[str]:
    """
    Get library destination directory.
    
    Returns
    -------
    Optional[str]
        Library destination path.
    """
    return sysconfig.get_config_var("LIBDEST")


LIBDEST: Optional[str] = _get_libdest()
"""
Library destination directory.

Main Python library directory.

Type: Optional[str]
"""


def _get_multiarch() -> Optional[str]:
    """
    Get multiarch triplet for current platform.
    
    Returns
    -------
    Optional[str]
        Multiarch triplet or None.
    """
    return sysconfig.get_config_var("MULTIARCH")


MULTIARCH: Optional[str] = _get_multiarch()
"""
Multiarch triplet for current platform.

Examples:
    - Debian/Ubuntu: 'x86_64-linux-gnu', 'aarch64-linux-gnu'
    - None if not supported (Windows, macOS)

Type: Optional[str]
"""


def _get_ldshared() -> Optional[str]:
    """
    Get shared library linker command.
    
    Returns
    -------
    Optional[str]
        Linker command for shared libraries.
    """
    return sysconfig.get_config_var("LDSHARED")


LDSHARED: Optional[str] = _get_ldshared()
"""
Shared library linker command.

Command used to link C extension modules.

Type: Optional[str]
"""


def _get_cc() -> Optional[str]:
    """
    Get C compiler command.
    
    Returns
    -------
    Optional[str]
        C compiler command.
    """
    return sysconfig.get_config_var("CC")


CC: Optional[str] = _get_cc()
"""
C compiler command used to build Python.

Type: Optional[str]
"""


def _get_cxx() -> Optional[str]:
    """
    Get C++ compiler command.
    
    Returns
    -------
    Optional[str]
        C++ compiler command.
    """
    return sysconfig.get_config_var("CXX")


CXX: Optional[str] = _get_cxx()
"""
C++ compiler command used to build Python.

Type: Optional[str]
"""

# ==============================================================================
# Bytecode and Cache Constants
# ==============================================================================

CACHE_TAG: str = sys.implementation.cache_tag
"""
Bytecode cache tag based on Python implementation and version.

Used in __pycache__ directory naming.
Examples:
    - CPython: 'cpython-311'
    - PyPy: 'pypy-39'

Type: str
"""


PYCACHE_DIR_NAME: str = "__pycache__"
"""
Name of the bytecode cache directory.

Always "__pycache__" - where .pyc files are stored (PEP 3147).

Type: str
"""


MAGIC_NUMBER: bytes = importlib.util.MAGIC_NUMBER
"""
Magic number for Python bytecode.

4-byte identifier that changes when bytecode format changes.
Used to validate .pyc file compatibility.

Type: bytes
"""


MAGIC_NUMBER_INT: int = struct.unpack('<I', importlib.util.MAGIC_NUMBER)[0]
"""
Magic number as integer.

Integer representation of the 4-byte magic number.

Type: int
"""


MAGIC_NUMBER_HEX: str = importlib.util.MAGIC_NUMBER.hex()
"""
Magic number as hexadecimal string.

Type: str
"""


BYTECODE_SUFFIXES: Tuple[str, ...] = tuple(importlib.machinery.BYTECODE_SUFFIXES)
"""
Valid bytecode file extensions.

List of suffixes for compiled Python files.
Examples: ['.pyc', '.pyo']

Type: Tuple[str, ...]
"""


OPTIMIZE_LEVEL: int = sys.flags.optimize
"""
Current optimization level.

- 0: No optimization (default)
- 1: -O flag (removes assert statements)
- 2: -OO flag (removes docstrings)

Type: int
"""


def _get_pyc_mtime() -> bool:
    """
    Check if pyc files include source modification time.
    
    Returns
    -------
    bool
        True if mtime is included in pyc files.
    """
    # PEP 552: Check if using hash-based pycs
    return sys.flags.hash_randomization == 0


PYC_INCLUDES_MTIME: bool = _get_pyc_mtime()
"""
Whether pyc files include source modification time.

False when using hash-based pycs (deterministic builds).

Type: bool
"""


def _get_pyc_invalidation_mode() -> str:
    """
    Get pyc invalidation mode.
    
    Returns
    -------
    str
        'timestamp', 'hash', or 'unchecked-hash'
    """
    try:
        import importlib._bootstrap_external
        return getattr(
            importlib._bootstrap_external, 
            '_get_source_hash', 
            lambda x: 'timestamp'
        )().__class__.__name__
    except Exception:
        return 'timestamp'


PYC_INVALIDATION_MODE: str = _get_pyc_invalidation_mode()
"""
PYC invalidation mode (PEP 552).

- 'timestamp': Based on file modification time
- 'hash': Based on source file hash
- 'unchecked-hash': Hash-based but not checked

Type: str
"""


def _get_pycache_prefix() -> Optional[str]:
    """
    Get pycache prefix if configured.
    
    Returns
    -------
    Optional[str]
        PYCACHE_PREFIX environment variable or None.
    """
    return os.environ.get('PYTHONPYCACHEPREFIX')


PYCACHE_PREFIX: Optional[str] = _get_pycache_prefix()
"""
PYCACHE_PREFIX environment variable value.

When set, .pyc files are written to this directory tree.

Type: Optional[str]
"""

# ==============================================================================
# Module and Import System Constants
# ==============================================================================

BUILTIN_MODULE_NAMES: Tuple[str, ...] = tuple(sys.builtin_module_names)
"""
Names of built-in modules.

Modules compiled into the interpreter (e.g., sys, marshal, time, _io, _codecs).

Type: Tuple[str, ...]
"""


def _get_frozen_module_names() -> Tuple[str, ...]:
    """
    Get names of frozen modules.
    
    Returns
    -------
    Tuple[str, ...]
        Tuple of frozen module names.
    """
    try:
        return tuple(sys.stdlib_module_names) if hasattr(sys, 'stdlib_module_names') else ()
    except Exception:
        return ()


FROZEN_MODULE_NAMES: Tuple[str, ...] = _get_frozen_module_names()
"""
Names of frozen modules.

Modules frozen into the interpreter (e.g., importlib._bootstrap).

Type: Tuple[str, ...]
"""


def _get_stdlib_module_names() -> Tuple[str, ...]:
    """
    Get names of standard library modules.
    
    Returns
    -------
    Tuple[str, ...]
        Tuple of standard library module names.
    """
    if hasattr(sys, 'stdlib_module_names'):
        return tuple(sys.stdlib_module_names)
    return ()


STDLIB_MODULE_NAMES: Tuple[str, ...] = _get_stdlib_module_names()
"""
Names of all standard library modules (Python 3.10+).

Complete list of modules that are part of the standard library.

Type: Tuple[str, ...]
"""


EXTENSION_SUFFIXES: Tuple[str, ...] = tuple(importlib.machinery.EXTENSION_SUFFIXES)
"""
Valid C extension module suffixes.

Platform-dependent shared library extensions.
Examples:
    - Linux: .cpython-311-x86_64-linux-gnu.so, .abi3.so, .so
    - Windows: .cp311-win_amd64.pyd, .pyd
    - macOS: .cpython-311-darwin.so, .so

Type: Tuple[str, ...]
"""


SOURCE_SUFFIXES: Tuple[str, ...] = tuple(importlib.machinery.SOURCE_SUFFIXES)
"""
Valid Python source file extensions.

Typically just ['.py'] - can include other extensions if configured.

Type: Tuple[str, ...]
"""


ALL_IMPORTABLE_SUFFIXES: Tuple[str, ...] = (
    SOURCE_SUFFIXES +
    BYTECODE_SUFFIXES +
    EXTENSION_SUFFIXES
)
"""
Complete list of importable file extensions.

Union of source, bytecode, and extension module suffixes.

Type: Tuple[str, ...]
"""


def _get_ext_suffix() -> Optional[str]:
    """
    Get primary extension module suffix.
    
    Returns
    -------
    Optional[str]
        EXT_SUFFIX from sysconfig or None.
    """
    return sysconfig.get_config_var("EXT_SUFFIX")


EXT_SUFFIX: Optional[str] = _get_ext_suffix()
"""
Primary extension module suffix for current platform.

Most commonly used suffix for C extensions.
Examples:
    - Linux: .cpython-311-x86_64-linux-gnu.so
    - Windows: .cp311-win_amd64.pyd
    - macOS: .cpython-311-darwin.so

Type: Optional[str]
"""


def _get_soabi() -> Optional[str]:
    """
    Get SOABI (SO ABI) identifier.
    
    Returns
    -------
    Optional[str]
        SOABI string or None.
    """
    return sysconfig.get_config_var("SOABI")


SOABI: Optional[str] = _get_soabi()
"""
SOABI (SO ABI) identifier.

Platform and Python version ABI tag for extension modules.
Examples:
    - 'cpython-311-x86_64-linux-gnu'
    - 'cp311-win_amd64'

Type: Optional[str]
"""


def _get_primary_extension_suffix() -> Optional[str]:
    """
    Return the primary file suffix for extension modules.
    
    Returns
    -------
    Optional[str]
        Primary extension suffix (e.g., '.so', '.pyd').
    """
    suffixes = importlib.machinery.EXTENSION_SUFFIXES
    if not suffixes:
        return None
    # Get the base suffix (without ABI tag)
    return os.path.splitext(suffixes[0])[-1]


PRIMARY_EXTENSION_SUFFIX: Optional[str] = _get_primary_extension_suffix()
"""
Primary extension module file suffix.

The basic suffix without ABI tags.
Examples:
    - Linux/macOS: '.so'
    - Windows: '.pyd'

Type: Optional[str]
"""


def _get_debug_suffix() -> Optional[str]:
    """
    Get debug build extension suffix.
    
    Returns
    -------
    Optional[str]
        Debug extension suffix or None.
    """
    return sysconfig.get_config_var("DEBUG_EXT")


DEBUG_EXT_SUFFIX: Optional[str] = _get_debug_suffix()
"""
Debug build extension module suffix.

Used for debug builds of Python (e.g., '_d.pyd' on Windows).

Type: Optional[str]
"""

# ==============================================================================
# Import Machinery Class References
# ==============================================================================

BUILTIN_IMPORTER_CLASS = importlib.machinery.BuiltinImporter
"""
Built-in module importer class reference.

Handles importing built-in modules (compiled into interpreter).

Type: type
"""


FROZEN_IMPORTER_CLASS = importlib.machinery.FrozenImporter
"""
Frozen module importer class reference.

Handles importing frozen modules (embedded in the interpreter).

Type: type
"""


PATH_FINDER_CLASS = importlib.machinery.PathFinder
"""
Path-based finder class reference.

Main finder for filesystem-based imports.

Type: type
"""


FILE_FINDER_CLASS = importlib.machinery.FileFinder
"""
File system finder class reference.

Finds modules in the filesystem using path hooks.

Type: type
"""


SOURCE_FILE_LOADER_CLASS = importlib.machinery.SourceFileLoader
"""
Source file loader class reference.

Loads Python source files (.py).

Type: type
"""


SOURCELESS_FILE_LOADER_CLASS = importlib.machinery.SourcelessFileLoader
"""
Bytecode file loader class reference.

Loads pre-compiled bytecode files (.pyc).

Type: type
"""


EXTENSION_FILE_LOADER_CLASS = importlib.machinery.ExtensionFileLoader
"""
Extension module loader class reference.

Loads C extension modules (.so, .pyd, .dll).

Type: type
"""


MODULE_SPEC_CLASS = importlib.machinery.ModuleSpec
"""
Module specification class reference.

Contains all import-related information about a module (PEP 451).

Type: type
"""


def _get_namespace_loader_class():
    """
    Get namespace package loader class if available.
    
    Returns
    -------
    Optional[type]
        NamespaceLoader class or None.
    """
    try:
        from importlib.machinery import NamespaceLoader
        return NamespaceLoader
    except ImportError:
        return None


NAMESPACE_LOADER_CLASS = _get_namespace_loader_class()
"""
Namespace package loader class reference.

Loader for PEP 420 namespace packages.

Type: Optional[type]
"""

# ==============================================================================
# Meta Path and Finder Constants
# ==============================================================================

META_PATH_FINDER_NAMES: Tuple[str, ...] = (
    'BuiltinImporter',
    'FrozenImporter',
    'PathFinder',
)
"""
Names of standard meta path finders.

Useful for introspection and debugging sys.meta_path.

Type: Tuple[str, ...]
"""


PATH_HOOK_NAMES: Tuple[str, ...] = (
    'ZipImporter',
    'FileFinder',
)
"""
Names of standard path hooks.

Used for handling special import paths like zip files.

Type: Tuple[str, ...]
"""


# References to mutable import system components
META_PATH: List[Any] = sys.meta_path
"""
Reference to sys.meta_path (mutable).

The list of meta path finders (can be modified at runtime).
Note: This is a reference, not a constant copy.

Type: List[Any]
"""


PATH_HOOKS: List[Any] = sys.path_hooks
"""
Reference to sys.path_hooks (mutable).

The list of path hooks for processing entries in sys.path.
Note: This is a reference, not a constant copy.

Type: List[Any]
"""


PATH_IMPORTER_CACHE: Dict[str, Any] = sys.path_importer_cache
"""
Reference to sys.path_importer_cache (mutable).

Cache mapping path entries to their finder objects.
Note: This is a reference, not a constant copy.

Type: Dict[str, Any]
"""


MODULES: Dict[str, Any] = sys.modules
"""
Reference to sys.modules (mutable).

Dictionary of all imported modules.
Note: This is a reference, not a constant copy.

Type: Dict[str, Any]
"""

# ==============================================================================
# Zip Import Constants
# ==============================================================================

ZIP_IMPORT_SUPPORTED: bool = hasattr(zipimport, 'zipimporter')
"""
Whether zipimport is available.

True if Python was compiled with zipimport support.

Type: bool
"""


ZIP_IMPORTER_CLASS = zipimport.zipimporter if ZIP_IMPORT_SUPPORTED else None
"""
ZipImporter class reference if available.

Handles importing modules from zip archives.

Type: Optional[type]
"""


ZIP_ARCHIVE_SUFFIXES: Tuple[str, ...] = ('.zip', '.egg', '.whl')
"""
Common zip archive extensions.

File extensions that can be treated as zip archives for import.

Type: Tuple[str, ...]
"""


def _get_zip_safe_flag() -> Optional[bool]:
    """
    Check if Python can run from a zip file.
    
    Returns
    -------
    Optional[bool]
        True if zip-safe, False otherwise.
    """
    try:
        return not hasattr(sys, 'frozen') and ZIP_IMPORT_SUPPORTED
    except Exception:
        return None


ZIP_SAFE: Optional[bool] = _get_zip_safe_flag()
"""
Whether Python can run from zip files.

True if Python supports running from zip archives.

Type: Optional[bool]
"""

# ==============================================================================
# Runtime and Environment Flags
# ==============================================================================

DEBUG_FLAG: bool = sys.flags.debug
"""
Whether Python is running in debug mode (-d flag).

Enables parser debugging output.

Type: bool
"""


VERBOSE_FLAG: bool = sys.flags.verbose
"""
Whether verbose import is enabled (-v flag).

Prints detailed information about module imports.

Type: bool
"""


QUIET_FLAG: bool = getattr(sys.flags, 'quiet', False)
"""
Whether quiet mode is enabled (-q flag).

Suppresses version and copyright messages.

Type: bool
"""


INSPECT_FLAG: bool = sys.flags.inspect
"""
Whether inspect mode is enabled (-i flag).

Enters interactive mode after script execution.

Type: bool
"""


INTERACTIVE_FLAG: bool = sys.flags.interactive
"""
Whether interactive mode is enabled.

True when running interactively.

Type: bool
"""


ISOLATED_FLAG: bool = getattr(sys.flags, 'isolated', False)
"""
Whether isolated mode is enabled (-I flag).

Prevents importing site.py and setting PYTHON* environment variables.

Type: bool
"""


NO_SITE_FLAG: bool = getattr(sys.flags, 'no_site', False)
"""
Whether site module import is disabled (-S flag).

Prevents automatic import of site.py.

Type: bool
"""


IGNORE_ENVIRONMENT_FLAG: bool = getattr(sys.flags, 'ignore_environment', False)
"""
Whether environment variables are ignored (-E flag).

Ignores all PYTHON* environment variables.

Type: bool
"""


DONT_WRITE_BYTECODE_FLAG: bool = sys.dont_write_bytecode
"""
Whether bytecode writing is disabled (-B flag).

Prevents writing .pyc files.

Type: bool
"""


NO_USER_SITE_FLAG: bool = getattr(sys.flags, 'no_user_site', False)
"""
Whether user site-packages is disabled (-s flag).

Prevents adding user site-packages to sys.path.

Type: bool
"""


HASH_RANDOMIZATION_FLAG: bool = sys.flags.hash_randomization
"""
Whether hash randomization is enabled (-R flag).

Enables randomized hashing for strings, bytes, and datetime objects.

Type: bool
"""


DEV_MODE_FLAG: bool = getattr(sys.flags, 'dev_mode', False)
"""
Whether development mode is enabled (-X dev).

Enables development mode features (warnings, assertions, etc.).

Type: bool
"""


UTF8_MODE_FLAG: bool = getattr(sys.flags, 'utf8_mode', False)
"""
Whether UTF-8 mode is enabled (-X utf8).

Forces UTF-8 encoding for text encoding.

Type: bool
"""


WARN_DEFAULT_ENCODING_FLAG: bool = getattr(sys.flags, 'warn_default_encoding', False)
"""
Whether default encoding warnings are enabled (-X warn_default_encoding).

Emits EncodingWarning when default encoding is used.

Type: bool
"""

# ==============================================================================
# Frozen and Embedded Python Constants
# ==============================================================================

IS_FROZEN: bool = hasattr(sys, 'frozen')
"""
Whether the interpreter is frozen.

True if running in a frozen application (PyInstaller, cx_Freeze, etc.).

Type: bool
"""


FROZEN_EXECUTABLE: Optional[str] = getattr(sys, 'executable', None) if hasattr(sys, 'frozen') else None
"""
Path to frozen executable if available.

None if not running in frozen environment.

Type: Optional[str]
"""


MEIPASS: Optional[str] = getattr(sys, '_MEIPASS', None)
"""
PyInstaller temp directory for bundled files.

Only set when running PyInstaller onefile mode.

Type: Optional[str]
"""


def _is_pyinstaller() -> bool:
    """
    Check if running under PyInstaller.
    
    Returns
    -------
    bool
        True if PyInstaller bundled.
    """
    return hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False)


IS_PYINSTALLER: bool = _is_pyinstaller()
"""
Whether running under PyInstaller.

True if bundled with PyInstaller.

Type: bool
"""


def _is_cx_freeze() -> bool:
    """
    Check if running under cx_Freeze.
    
    Returns
    -------
    bool
        True if cx_Freeze bundled.
    """
    return hasattr(sys, 'frozen') and not hasattr(sys, '_MEIPASS')


IS_CX_FREEZE: bool = _is_cx_freeze()
"""
Whether running under cx_Freeze.

True if bundled with cx_Freeze.

Type: bool
"""


def _is_py2exe() -> bool:
    """
    Check if running under py2exe.
    
    Returns
    -------
    bool
        True if py2exe bundled.
    """
    return hasattr(sys, 'frozen') and sys.frozen == 'console_exe'


IS_PY2EXE: bool = _is_py2exe()
"""
Whether running under py2exe.

True if bundled with py2exe.

Type: bool
"""

# ==============================================================================
# Standard Library Paths
# ==============================================================================

STDLIB_PATHS: Tuple[str, ...] = tuple(filter(None, (STDLIB_PATH, PURELIB_PATH, PLATLIB_PATH, PLATSTDLIB_PATH)))
"""
All paths considered part of the standard library.

Tuple of standard library directories.

Type: Tuple[str, ...]
"""


def is_stdlib_path(path: Union[str, Path]) -> bool:
    """
    Check if given path is within the standard library directories.
    
    Parameters
    ----------
    path : Union[str, Path]
        Path to check.
    
    Returns
    -------
    bool
        True if path is in standard library.
    """
    path_str = str(path)
    return any(
        path_str.startswith(stdlib_path) 
        for stdlib_path in STDLIB_PATHS 
        if stdlib_path
    )


IS_STDLIB_PATH: Callable[[Union[str, Path]], bool] = is_stdlib_path
"""
Function to check if a path is in the standard library.

Useful for determining if a module is built-in or third-party.

Type: Callable[[Union[str, Path]], bool]
"""

# ==============================================================================
# Python Package Structure Constants
# ==============================================================================

INIT_PY: str = '__init__.py'
"""
Name of package initialization file.

Standard __init__.py file name.

Type: str
"""


INIT_PYC: str = f'__init__{CACHE_TAG}.pyc' if CACHE_TAG else '__init__.pyc'
"""
Name of package bytecode cache file.

Standard __init__.pyc file name with cache tag.

Type: str
"""


NAMESPACE_PACKAGE_MARKERS: Tuple[str, ...] = ('.pyp', '.pyd', '.so', '.dll', '.dylib')
"""
Files that indicate a namespace package.

Markers for PEP 420 namespace packages (no __init__.py).

Type: Tuple[str, ...]
"""


MAIN_SCRIPT_NAME: str = '__main__'
"""
Name of the main module.

Used for the entry point script.

Type: str
"""

# ==============================================================================
# Import Hooks and Utilities
# ==============================================================================

PKGUTIL_ITER_MODULES = pkgutil.iter_modules
"""
Reference to pkgutil.iter_modules function.

Useful for iterating over all importable modules.

Type: Callable
"""


PKGUTIL_WALK_PACKAGES = pkgutil.walk_packages
"""
Reference to pkgutil.walk_packages function.

Recursively walks over all packages.

Type: Callable
"""


PKGUTIL_GET_LOADER = pkgutil.get_loader
"""
Reference to pkgutil.get_loader function.

Gets loader for a module.

Type: Callable
"""


PKGUTIL_GET_IMPORTER = pkgutil.get_importer
"""
Reference to pkgutil.get_importer function.

Gets importer for a path.

Type: Callable
"""


IMPORTLIB_FIND_SPEC = importlib.util.find_spec
"""
Reference to importlib.util.find_spec.

Finds module specification.

Type: Callable
"""


IMPORTLIB_MODULE_FROM_SPEC = importlib.util.module_from_spec
"""
Reference to importlib.util.module_from_spec.

Creates module from spec.

Type: Callable
"""


IMPORTLIB_SPEC_FROM_LOADER = importlib.util.spec_from_loader
"""
Reference to importlib.util.spec_from_loader.

Creates spec from loader.

Type: Callable
"""


IMPORTLIB_SPEC_FROM_FILE_LOCATION = importlib.util.spec_from_file_location
"""
Reference to importlib.util.spec_from_file_location.

Creates spec from file location.

Type: Callable
"""


IMPORTLIB_DECODE_SOURCE = importlib.util.decode_source
"""
Reference to importlib.util.decode_source.

Decodes source code bytes to string.

Type: Callable
"""


IMPORTLIB_RESOLVE_NAME = importlib.util.resolve_name
"""
Reference to importlib.util.resolve_name.

Resolves relative import name.

Type: Callable
"""

try:
	IMPORTLIB_SET_LOADER = importlib.util.set_loader
except AttributeError:
	IMPORTLIB_SET_LOADER = None
"""
Reference to importlib.util.set_loader (deprecated).

Sets loader for a module.

Type: Callable
"""


try:
	IMPORTLIB_SET_PACKAGE = importlib.util.set_package
except AttributeError:
	IMPORTLIB_SET_PACKAGE = None
"""
Reference to importlib.util.set_package (deprecated).

Sets package for a module.

Type: Callable
"""


IMPORTLIB_LAZY_LOADER_CLASS = importlib.util.LazyLoader
"""
Reference to importlib.util.LazyLoader.

Lazy loader for modules.

Type: type
"""

# ==============================================================================
# System and Platform Information
# ==============================================================================

PLATFORM: str = sys.platform
"""
Current platform identifier.

Examples:
    - Linux: 'linux'
    - Windows: 'win32'
    - macOS: 'darwin'
    - Cygwin: 'cygwin'
    - FreeBSD: 'freebsd'

Type: str
"""


OS_NAME: str = os.name
"""
Operating system name.

- 'posix': Linux, macOS, BSD
- 'nt': Windows
- 'java': Jython

Type: str
"""


MACHINE: str = platform.machine()
"""
Machine type.

Examples:
    - 'x86_64', 'AMD64'
    - 'arm64', 'aarch64'
    - 'i386', 'i686'
    - 'ppc64le', 's390x'

Type: str
"""


PROCESSOR: str = platform.processor() or MACHINE
"""
Processor name.

May return empty string on some platforms, falls back to MACHINE.

Type: str
"""


PYTHON_VERSION: str = platform.python_version()
"""
Python version as string.

Full version string (e.g., '3.11.0').

Type: str
"""


PYTHON_VERSION_TUPLE: Tuple[int, int, int] = sys.version_info[:3]
"""
Python version as tuple.

Examples:
    - Python 3.11.0: (3, 11, 0)
    - Python 3.12.1: (3, 12, 1)

Type: Tuple[int, int, int]
"""


PYTHON_VERSION_INFO: Tuple[int, int, int, str, int] = sys.version_info
"""
Complete Python version info.

(major, minor, micro, releaselevel, serial)

Type: Tuple[int, int, int, str, int]
"""


PYTHON_IMPLEMENTATION: str = platform.python_implementation()
"""
Python implementation name.

Examples:
    - 'CPython'
    - 'PyPy'
    - 'Jython'
    - 'IronPython'

Type: str
"""


PYTHON_IMPLEMENTATION_LOWER: str = PYTHON_IMPLEMENTATION.lower()
"""
Python implementation name in lowercase.

Type: str
"""


PYTHON_COMPILER: str = platform.python_compiler()
"""
Compiler used to build Python.

Examples:
    - 'GCC 11.2.0'
    - 'MSVC v143'

Type: str
"""


PYTHON_BUILD_INFO: Tuple[str, str] = platform.python_build()
"""
Python build number and date.

(buildno, builddate)

Type: Tuple[str, str]
"""


PYTHON_BRANCH: str = platform.python_branch()
"""
Python source code branch.

Examples:
    - 'main'
    - '3.11'

Type: str
"""


PYTHON_REVISION: str = platform.python_revision()
"""
Python source code revision.

Git commit hash for the build.

Type: str
"""

# ==============================================================================
# Architecture and Bitness Constants
# ==============================================================================

def _get_pointer_size() -> int:
    """
    Get pointer size in bytes.
    
    Returns
    -------
    int
        Pointer size (4 for 32-bit, 8 for 64-bit).
    """
    return struct.calcsize('P')


POINTER_SIZE: int = _get_pointer_size()
"""
Pointer size in bytes.

- 4: 32-bit Python
- 8: 64-bit Python

Type: int
"""


BITNESS: int = POINTER_SIZE * 8
"""
Python interpreter bitness.

- 32: 32-bit
- 64: 64-bit

Type: int
"""


IS_64BIT: bool = POINTER_SIZE == 8
"""
Whether running 64-bit Python.

Type: bool
"""


IS_32BIT: bool = POINTER_SIZE == 4
"""
Whether running 32-bit Python.

Type: bool
"""


def _get_endianness() -> str:
    """
    Get system endianness.
    
    Returns
    -------
    str
        'little' or 'big'.
    """
    return sys.byteorder


ENDIANNESS: str = _get_endianness()
"""
System byte order.

- 'little': Little-endian (x86, ARM)
- 'big': Big-endian (PowerPC, SPARC)

Type: str
"""


IS_LITTLE_ENDIAN: bool = sys.byteorder == 'little'
"""
Whether system is little-endian.

Type: bool
"""


IS_BIG_ENDIAN: bool = sys.byteorder == 'big'
"""
Whether system is big-endian.

Type: bool
"""

# ==============================================================================
# Platform Detection Booleans
# ==============================================================================

IS_WINDOWS: bool = sys.platform == 'win32'
"""
Whether running on Windows.

Type: bool
"""


IS_MACOS: bool = sys.platform == 'darwin'
"""
Whether running on macOS.

Type: bool
"""


IS_LINUX: bool = sys.platform.startswith('linux')
"""
Whether running on Linux.

Type: bool
"""


IS_FREEBSD: bool = sys.platform.startswith('freebsd')
"""
Whether running on FreeBSD.

Type: bool
"""


IS_OPENBSD: bool = sys.platform.startswith('openbsd')
"""
Whether running on OpenBSD.

Type: bool
"""


IS_NETBSD: bool = sys.platform.startswith('netbsd')
"""
Whether running on NetBSD.

Type: bool
"""


IS_DRAGONFLY: bool = sys.platform.startswith('dragonfly')
"""
Whether running on DragonFly BSD.

Type: bool
"""


IS_SOLARIS: bool = sys.platform.startswith('sunos')
"""
Whether running on Solaris/Illumos.

Type: bool
"""


IS_AIX: bool = sys.platform.startswith('aix')
"""
Whether running on AIX.

Type: bool
"""


IS_HPUX: bool = sys.platform.startswith('hp-ux')
"""
Whether running on HP-UX.

Type: bool
"""


IS_CYGWIN: bool = sys.platform.startswith('cygwin')
"""
Whether running on Cygwin.

Type: bool
"""


IS_MSYS: bool = sys.platform.startswith('msys')
"""
Whether running on MSYS2/MinGW.

Type: bool
"""


IS_BSD: bool = any(sys.platform.startswith(p) for p in ('freebsd', 'openbsd', 'netbsd', 'dragonfly'))
"""
Whether running on any BSD system.

Type: bool
"""


IS_POSIX: bool = os.name == 'posix'
"""
Whether running on POSIX-compliant system.

Includes Linux, macOS, BSD, Solaris, etc.

Type: bool
"""


IS_UNIX: bool = IS_POSIX and not IS_CYGWIN
"""
Whether running on Unix-like system.

POSIX but not Cygwin.

Type: bool
"""

# ==============================================================================
# PyPy Specific Constants
# ==============================================================================

IS_PYPY: bool = hasattr(sys, 'pypy_version_info')
"""
Whether running on PyPy.

Type: bool
"""


PYPY_VERSION_INFO: Optional[Tuple[int, ...]] = getattr(sys, 'pypy_version_info', None)
"""
PyPy version info if running on PyPy.

Type: Optional[Tuple[int, ...]]
"""


PYPY_VERSION: Optional[str] = '.'.join(map(str, PYPY_VERSION_INFO)) if PYPY_VERSION_INFO else None
"""
PyPy version string if running on PyPy.

Type: Optional[str]
"""

# ==============================================================================
# Jython Specific Constants
# ==============================================================================

IS_JYTHON: bool = sys.platform.startswith('java')
"""
Whether running on Jython.

Type: bool
"""


JAVA_VERSION: Optional[str] = getattr(sys, 'java_version', None)
"""
Java version if running on Jython.

Type: Optional[str]
"""

# ==============================================================================
# IronPython Specific Constants
# ==============================================================================

IS_IRONPYTHON: bool = sys.platform == 'cli'
"""
Whether running on IronPython.

Type: bool
"""


CLR_VERSION: Optional[str] = getattr(sys, 'clr_version', None)
"""
CLR version if running on IronPython.

Type: Optional[str]
"""

# ==============================================================================
# Environment Variables Affecting Imports
# ==============================================================================

def _get_python_path_env() -> Optional[str]:
    """
    Get PYTHONPATH environment variable.
    
    Returns
    -------
    Optional[str]
        PYTHONPATH value or None.
    """
    return os.environ.get('PYTHONPATH')


PYTHONPATH_ENV: Optional[str] = _get_python_path_env()
"""
PYTHONPATH environment variable.

Additional directories to search for modules.

Type: Optional[str]
"""


def _get_python_home_env() -> Optional[str]:
    """
    Get PYTHONHOME environment variable.
    
    Returns
    -------
    Optional[str]
        PYTHONHOME value or None.
    """
    return os.environ.get('PYTHONHOME')


PYTHONHOME_ENV: Optional[str] = _get_python_home_env()
"""
PYTHONHOME environment variable.

Override for Python installation location.

Type: Optional[str]
"""


def _get_python_case_ok_env() -> bool:
    """
    Check PYTHONCASEOK environment variable.
    
    Returns
    -------
    bool
        True if case-insensitive imports enabled.
    """
    return os.environ.get('PYTHONCASEOK', '') == '1'


PYTHONCASEOK_ENV: bool = _get_python_case_ok_env()
"""
PYTHONCASEOK environment variable.

Enables case-insensitive imports on Windows.

Type: bool
"""


def _get_python_verbose_env() -> bool:
    """
    Check PYTHONVERBOSE environment variable.
    
    Returns
    -------
    bool
        True if verbose imports enabled.
    """
    return os.environ.get('PYTHONVERBOSE', '') == '1'


PYTHONVERBOSE_ENV: bool = _get_python_verbose_env()
"""
PYTHONVERBOSE environment variable.

Prints import messages.

Type: bool
"""


def _get_python_dont_write_bytecode_env() -> bool:
    """
    Check PYTHONDONTWRITEBYTECODE environment variable.
    
    Returns
    -------
    bool
        True if bytecode writing disabled.
    """
    return os.environ.get('PYTHONDONTWRITEBYTECODE', '') == '1'


PYTHONDONTWRITEBYTECODE_ENV: bool = _get_python_dont_write_bytecode_env()
"""
PYTHONDONTWRITEBYTECODE environment variable.

Prevents writing .pyc files.

Type: bool
"""


def _get_python_no_user_site_env() -> bool:
    """
    Check PYTHONNOUSERSITE environment variable.
    
    Returns
    -------
    bool
        True if user site-packages disabled.
    """
    return os.environ.get('PYTHONNOUSERSITE', '') == '1'


PYTHONNOUSERSITE_ENV: bool = _get_python_no_user_site_env()
"""
PYTHONNOUSERSITE environment variable.

Disables user site-packages.

Type: bool
"""


def _get_python_isolated_env() -> bool:
    """
    Check PYTHONISOLATED environment variable.
    
    Returns
    -------
    bool
        True if isolated mode enabled.
    """
    return os.environ.get('PYTHONISOLATED', '') == '1'


PYTHONISOLATED_ENV: bool = _get_python_isolated_env()
"""
PYTHONISOLATED environment variable.

Enables isolated mode.

Type: bool
"""

# ==============================================================================
# Module Exports
# ==============================================================================

__all__ = [
    # Path Constants
    'SITE_PACKAGES',
    'USER_SITE',
    'ENABLE_USER_SITE',
    'PYTHON_PATH',
    'STDLIB_PATH',
    'PURELIB_PATH',
    'PLATLIB_PATH',
    'PLATSTDLIB_PATH',
    'INCLUDE_PATH',
    'PLATINCLUDE_PATH',
    'SCRIPTS_PATH',
    'DATA_PATH',
    'EXECUTABLE',
    'EXECUTABLE_DIR',
    'PREFIX',
    'BASE_PREFIX',
    'EXEC_PREFIX',
    'BASE_EXEC_PREFIX',
    'PYTHON_HOME',
    'IS_VIRTUAL_ENV',
    'VIRTUAL_ENV_PATH',
    'PLATFORM_LIBDIR',
    'LIBDEST',
    'MULTIARCH',
    'LDSHARED',
    'CC',
    'CXX',
    
    # Bytecode Constants
    'CACHE_TAG',
    'PYCACHE_DIR_NAME',
    'MAGIC_NUMBER',
    'MAGIC_NUMBER_INT',
    'MAGIC_NUMBER_HEX',
    'BYTECODE_SUFFIXES',
    'OPTIMIZE_LEVEL',
    'PYC_INCLUDES_MTIME',
    'PYC_INVALIDATION_MODE',
    'PYCACHE_PREFIX',
    
    # Module Constants
    'BUILTIN_MODULE_NAMES',
    'FROZEN_MODULE_NAMES',
    'STDLIB_MODULE_NAMES',
    'EXTENSION_SUFFIXES',
    'SOURCE_SUFFIXES',
    'ALL_IMPORTABLE_SUFFIXES',
    'EXT_SUFFIX',
    'SOABI',
    'PRIMARY_EXTENSION_SUFFIX',
    'DEBUG_EXT_SUFFIX',
    
    # Import Machinery Classes
    'BUILTIN_IMPORTER_CLASS',
    'FROZEN_IMPORTER_CLASS',
    'PATH_FINDER_CLASS',
    'FILE_FINDER_CLASS',
    'SOURCE_FILE_LOADER_CLASS',
    'SOURCELESS_FILE_LOADER_CLASS',
    'EXTENSION_FILE_LOADER_CLASS',
    'MODULE_SPEC_CLASS',
    'NAMESPACE_LOADER_CLASS',
    
    # Meta Path Constants
    'META_PATH_FINDER_NAMES',
    'PATH_HOOK_NAMES',
    'META_PATH',
    'PATH_HOOKS',
    'PATH_IMPORTER_CACHE',
    'MODULES',
    
    # Zip Import Constants
    'ZIP_IMPORT_SUPPORTED',
    'ZIP_IMPORTER_CLASS',
    'ZIP_ARCHIVE_SUFFIXES',
    'ZIP_SAFE',
    
    # Runtime Flags
    'DEBUG_FLAG',
    'VERBOSE_FLAG',
    'QUIET_FLAG',
    'INSPECT_FLAG',
    'INTERACTIVE_FLAG',
    'ISOLATED_FLAG',
    'NO_SITE_FLAG',
    'IGNORE_ENVIRONMENT_FLAG',
    'DONT_WRITE_BYTECODE_FLAG',
    'NO_USER_SITE_FLAG',
    'HASH_RANDOMIZATION_FLAG',
    'DEV_MODE_FLAG',
    'UTF8_MODE_FLAG',
    'WARN_DEFAULT_ENCODING_FLAG',
    
    # Frozen Environment Constants
    'IS_FROZEN',
    'FROZEN_EXECUTABLE',
    'MEIPASS',
    'IS_PYINSTALLER',
    'IS_CX_FREEZE',
    'IS_PY2EXE',
    
    # Standard Library Paths
    'STDLIB_PATHS',
    'IS_STDLIB_PATH',
    
    # Package Structure Constants
    'INIT_PY',
    'INIT_PYC',
    'NAMESPACE_PACKAGE_MARKERS',
    'MAIN_SCRIPT_NAME',
    
    # Import Utilities
    'PKGUTIL_ITER_MODULES',
    'PKGUTIL_WALK_PACKAGES',
    'PKGUTIL_GET_LOADER',
    'PKGUTIL_GET_IMPORTER',
    'IMPORTLIB_FIND_SPEC',
    'IMPORTLIB_MODULE_FROM_SPEC',
    'IMPORTLIB_SPEC_FROM_LOADER',
    'IMPORTLIB_SPEC_FROM_FILE_LOCATION',
    'IMPORTLIB_DECODE_SOURCE',
    'IMPORTLIB_RESOLVE_NAME',
    'IMPORTLIB_SET_LOADER',
    'IMPORTLIB_SET_PACKAGE',
    'IMPORTLIB_LAZY_LOADER_CLASS',
    
    # System Information
    'PLATFORM',
    'OS_NAME',
    'MACHINE',
    'PROCESSOR',
    'PYTHON_VERSION',
    'PYTHON_VERSION_TUPLE',
    'PYTHON_VERSION_INFO',
    'PYTHON_IMPLEMENTATION',
    'PYTHON_IMPLEMENTATION_LOWER',
    'PYTHON_COMPILER',
    'PYTHON_BUILD_INFO',
    'PYTHON_BRANCH',
    'PYTHON_REVISION',
    
    # Architecture Constants
    'POINTER_SIZE',
    'BITNESS',
    'IS_64BIT',
    'IS_32BIT',
    'ENDIANNESS',
    'IS_LITTLE_ENDIAN',
    'IS_BIG_ENDIAN',
    
    # Platform Detection
    'IS_WINDOWS',
    'IS_MACOS',
    'IS_LINUX',
    'IS_FREEBSD',
    'IS_OPENBSD',
    'IS_NETBSD',
    'IS_DRAGONFLY',
    'IS_SOLARIS',
    'IS_AIX',
    'IS_HPUX',
    'IS_CYGWIN',
    'IS_MSYS',
    'IS_BSD',
    'IS_POSIX',
    'IS_UNIX',
    
    # PyPy Constants
    'IS_PYPY',
    'PYPY_VERSION_INFO',
    'PYPY_VERSION',
    
    # Jython Constants
    'IS_JYTHON',
    'JAVA_VERSION',
    
    # IronPython Constants
    'IS_IRONPYTHON',
    'CLR_VERSION',
    
    # Environment Variables
    'PYTHONPATH_ENV',
    'PYTHONHOME_ENV',
    'PYTHONCASEOK_ENV',
    'PYTHONVERBOSE_ENV',
    'PYTHONDONTWRITEBYTECODE_ENV',
    'PYTHONNOUSERSITE_ENV',
    'PYTHONISOLATED_ENV',
]

