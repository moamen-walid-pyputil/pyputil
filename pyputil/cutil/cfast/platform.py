#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Platform-specific utilities and system information detection.

This module provides comprehensive platform detection, system information
gathering, and platform-specific path resolution for the cfast package.
It handles differences between Windows, macOS, and Linux/Unix systems,
providing a unified interface for:
- Shared library extensions
- System include paths
- Python include paths
- Compiler detection helpers
- System information gathering

The module is designed to work across all major platforms and gracefully
degrade when certain features are unavailable.

Classes
-------
PlatformInfo
    Static helper class for platform-dependent information.
SystemInfo
    Detailed system information container class.
PathResolver
    Platform-aware path resolution utilities.

Functions
---------
get_platform_details
    Return comprehensive platform information as a dictionary.
is_windows, is_macos, is_linux
    Boolean platform checks.
get_system_library_paths
    Get standard system library search paths.
get_python_info
    Get detailed Python installation information.
detect_architecture
    Detect CPU architecture (x86_64, arm64, etc.).
detect_compiler_toolchain
    Attempt to detect installed compiler toolchains.
get_hostname
    Get the system hostname safely across platforms.

Examples
--------
>>> from cfast.platform import PlatformInfo, SystemInfo

>>> # Basic platform checks
>>> print(PlatformInfo.shared_lib_extension())
'.so'

>>> # Get detailed system info
>>> info = SystemInfo.collect()
>>> print(info.architecture)
'x86_64'

>>> # Get include paths for compilation
>>> includes = PlatformInfo.python_include_args()
>>> print(includes[0])
'-I/usr/include/python3.11'
"""

import os
import sys
import sysconfig
import platform
import subprocess
import glob
import socket
import ctypes
import warnings
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple, Set
from dataclasses import dataclass, field


# =============================================================================
# Platform Detection Utilities
# =============================================================================

def is_windows() -> bool:
    """
    Check if the current platform is Windows.

    Returns
    -------
    bool
        True if running on Windows, False otherwise.

    Examples
    --------
    >>> if is_windows():
    ...     compiler = "cl.exe"
    ... else:
    ...     compiler = "gcc"
    """
    return sys.platform.startswith("win")


def is_macos() -> bool:
    """
    Check if the current platform is macOS.

    Returns
    -------
    bool
        True if running on macOS (Darwin), False otherwise.

    Examples
    --------
    >>> if is_macos():
    ...     # Use macOS-specific framework paths
    ...     frameworks = ["-framework", "Foundation"]
    """
    return sys.platform.startswith("darwin")


def is_linux() -> bool:
    """
    Check if the current platform is Linux.

    Returns
    -------
    bool
        True if running on Linux, False otherwise.

    Examples
    --------
    >>> if is_linux():
    ...     # Use Linux-specific library paths
    ...     lib_paths = ["/usr/lib", "/usr/local/lib"]
    """
    return sys.platform.startswith("linux")


def is_bsd() -> bool:
    """
    Check if the current platform is a BSD variant.

    Returns
    -------
    bool
        True if running on FreeBSD, OpenBSD, NetBSD, or DragonFly BSD.

    Notes
    -----
    This includes all BSD-derived systems including macOS (Darwin) if
    strict checking is not used. For macOS specifically, use `is_macos()`.
    """
    return (sys.platform.startswith("freebsd") or
            sys.platform.startswith("openbsd") or
            sys.platform.startswith("netbsd") or
            sys.platform.startswith("dragonfly"))


def is_unix_like() -> bool:
    """
    Check if the current platform is Unix-like.

    Returns
    -------
    bool
        True if running on Linux, macOS, or BSD, False otherwise.

    Examples
    --------
    >>> if is_unix_like():
    ...     # Use POSIX APIs
    ...     import fcntl
    """
    return is_linux() or is_macos() or is_bsd()


def is_64bit() -> bool:
    """
    Check if the Python interpreter is 64-bit.

    Returns
    -------
    bool
        True if running 64-bit Python, False for 32-bit.

    Notes
    -----
    This checks the Python interpreter's bitness, not the OS bitness,
    though they typically match.

    Examples
    --------
    >>> if is_64bit():
    ...     # Use 64-bit specific optimizations
    ...     cflags = ["-m64"]
    """
    return sys.maxsize > 2**32


def detect_architecture() -> str:
    """
    Detect the CPU architecture of the current system.

    Returns
    -------
    str
        Architecture identifier. Common values:
        - 'x86_64' : 64-bit Intel/AMD
        - 'x86' : 32-bit Intel/AMD
        - 'arm64' : 64-bit ARM (Apple Silicon, ARMv8)
        - 'arm' : 32-bit ARM
        - 'ppc64le' : PowerPC 64-bit little-endian
        - 's390x' : IBM System z
        - 'unknown' : Could not detect

    Examples
    --------
    >>> arch = detect_architecture()
    >>> if arch == 'arm64':
    ...     cflags.append("-march=armv8-a")
    """
    machine = platform.machine().lower()
    
    # x86 architectures
    if machine in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if machine in ("i386", "i486", "i586", "i686", "x86"):
        return "x86"
    
    # ARM architectures
    if machine in ("arm64", "aarch64", "armv8", "armv8-a"):
        return "arm64"
    if machine.startswith("arm"):
        return "arm"
    
    # PowerPC
    if machine in ("ppc64le", "ppc64el"):
        return "ppc64le"
    if machine.startswith("ppc"):
        return "ppc"
    
    # IBM System z
    if machine.startswith("s390"):
        return "s390x"
    
    # MIPS
    if machine.startswith("mips"):
        return "mips"
    
    # RISC-V
    if machine.startswith("riscv"):
        return "riscv"
    
    return "unknown"


def get_hostname() -> str:
    """
    Get the system hostname safely across all platforms.

    Returns
    -------
    str
        System hostname, or "unknown" if it cannot be determined.

    Notes
    -----
    This function handles platform differences and network unavailability
    gracefully, falling back to "unknown" rather than raising exceptions.

    Examples
    --------
    >>> hostname = get_hostname()
    >>> print(f"Running on {hostname}")
    """
    try:
        return socket.gethostname()
    except (socket.error, OSError):
        # Fallback: try environment variables
        for env_var in ("HOSTNAME", "COMPUTERNAME"):
            if env_var in os.environ:
                return os.environ[env_var]
        return "unknown"


def get_os_version() -> str:
    """
    Get detailed operating system version information.

    Returns
    -------
    str
        OS version string (e.g., 'Windows 10', 'macOS 14.0', 'Ubuntu 22.04').

    Examples
    --------
    >>> version = get_os_version()
    >>> print(f"Running on {version}")
    """
    if is_windows():
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
            ) as key:
                product_name = winreg.QueryValueEx(key, "ProductName")[0]
                return product_name
        except Exception:
            return platform.system() + " " + platform.release()
    
    elif is_macos():
        try:
            result = subprocess.run(
                ["sw_vers", "-productVersion"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return f"macOS {result.stdout.strip()}"
        except Exception:
            pass
        return f"macOS {platform.mac_ver()[0]}"
    
    elif is_linux():
        # Try to read from os-release
        try:
            with open("/etc/os-release", "r") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
        
        # Fallback to platform info
        return f"{platform.system()} {platform.release()}"
    
    else:
        return f"{platform.system()} {platform.release()}"


# =============================================================================
# Path Detection and Resolution
# =============================================================================

class PathResolver:
    """
    Platform-aware path resolution utilities.

    This class provides methods to locate system directories, include paths,
    and library paths across different platforms. It handles platform-specific
    conventions and environment variable expansion.

    Methods
    -------
    expand_path
        Expand environment variables and user home directory in a path.
    find_executable
        Locate an executable in the system PATH.
    find_library
        Locate a shared library file.
    find_include
        Locate a header file in standard include paths.
    get_system_directories
        Get standard system directory paths.

    Examples
    --------
    >>> resolver = PathResolver()
    >>> gcc_path = resolver.find_executable("gcc")
    >>> if gcc_path:
    ...     print(f"GCC found at: {gcc_path}")

    >>> lib_path = resolver.find_library("m")
    >>> print(lib_path)
    '/usr/lib/x86_64-linux-gnu/libm.so'
    """

    @staticmethod
    def expand_path(path: str) -> Path:
        """
        Expand environment variables and user home directory.

        Parameters
        ----------
        path : str
            Path that may contain environment variables ($VAR or %VAR%)
            or tilde (~) for home directory.

        Returns
        -------
        Path
            Expanded absolute path.

        Examples
        --------
        >>> PathResolver.expand_path("~/projects/code.c")
        PosixPath('/home/user/projects/code.c')

        >>> PathResolver.expand_path("$HOME/.local/include")
        PosixPath('/home/user/.local/include')
        """
        # Expand environment variables
        expanded = os.path.expandvars(path)
        # Expand user home (~)
        expanded = os.path.expanduser(expanded)
        return Path(expanded).resolve()

    @staticmethod
    def find_executable(name: str) -> Optional[Path]:
        """
        Find an executable in the system PATH.

        Parameters
        ----------
        name : str
            Name of the executable (e.g., 'gcc', 'clang', 'cl').

        Returns
        -------
        Path or None
            Full path to the executable if found, None otherwise.

        Notes
        -----
        On Windows, this automatically appends '.exe' if not present.
        On Unix, file execute permission is checked.

        Examples
        --------
        >>> gcc = PathResolver.find_executable("gcc")
        >>> if gcc:
        ...     print(f"GCC: {gcc}")
        """
        import shutil
        
        # On Windows, ensure .exe extension
        search_name = name
        if is_windows() and not name.lower().endswith(".exe"):
            search_name = name + ".exe"
        
        # Use shutil.which for cross-platform PATH search
        found = shutil.which(search_name)
        if found:
            path = Path(found)
            # On Unix, check if file is executable
            if is_unix_like():
                if os.access(path, os.X_OK):
                    return path
                return None
            return path
        
        return None

    @staticmethod
    def find_library(
        name: str,
        extra_paths: Optional[List[str]] = None
    ) -> Optional[Path]:
        """
        Locate a shared library file.

        Searches standard library paths for a library matching the given name.
        Handles platform-specific naming conventions (lib*.so, *.dylib, *.dll).

        Parameters
        ----------
        name : str
            Library name without 'lib' prefix or extension.
            For example, 'm' for libm.so, 'python3' for libpython3.so.
        extra_paths : list of str, optional
            Additional directories to search.

        Returns
        -------
        Path or None
            Full path to the library if found, None otherwise.

        Examples
        --------
        >>> libm = PathResolver.find_library("m")
        >>> print(libm)
        '/usr/lib/x86_64-linux-gnu/libm.so'

        >>> libpython = PathResolver.find_library("python3.11")
        >>> print(libpython)
        '/usr/lib/libpython3.11.so'
        """
        # Build search paths
        search_paths = get_system_library_paths()
        if extra_paths:
            search_paths.extend(extra_paths)
        
        # Platform-specific library name patterns
        if is_windows():
            patterns = [
                f"{name}.dll",
                f"lib{name}.dll",
                f"{name}.lib",
            ]
        elif is_macos():
            patterns = [
                f"lib{name}.dylib",
                f"lib{name}.so",  # Some Unix libraries on macOS
                f"{name}.dylib",
            ]
        else:  # Linux/Unix
            patterns = [
                f"lib{name}.so",
                f"lib{name}.so.*",  # Versioned library
                f"{name}.so",
            ]
        
        # Also check with architecture-specific paths
        arch = detect_architecture()
        if arch == "x86_64" and is_linux():
            search_paths.append(f"/usr/lib/x86_64-linux-gnu")
        
        for pattern in patterns:
            for search_path in search_paths:
                if "*" in pattern:
                    # Handle glob patterns
                    glob_pattern = os.path.join(search_path, pattern)
                    matches = glob.glob(glob_pattern)
                    if matches:
                        # Return the first match (prefer unversioned)
                        for match in matches:
                            if "." not in os.path.basename(match).split(".so")[-1]:
                                return Path(match)
                        return Path(matches[0])
                else:
                    full_path = Path(search_path) / pattern
                    if full_path.exists():
                        return full_path
        
        return None

    @staticmethod
    def find_include(
        header: str,
        extra_paths: Optional[List[str]] = None
    ) -> Optional[Path]:
        """
        Locate a header file in standard include paths.

        Parameters
        ----------
        header : str
            Header file name (e.g., 'stdio.h', 'Python.h').
        extra_paths : list of str, optional
            Additional directories to search.

        Returns
        -------
        Path or None
            Full path to the header if found, None otherwise.

        Examples
        --------
        >>> python_h = PathResolver.find_include("Python.h")
        >>> if python_h:
        ...     print(f"Python.h at: {python_h}")
        """
        search_paths = get_system_include_paths()
        if extra_paths:
            search_paths.extend(extra_paths)
        
        for search_path in search_paths:
            # Handle glob patterns in search path
            if "*" in search_path:
                for expanded in glob.glob(search_path, recursive=True):
                    full_path = Path(expanded) / header
                    if full_path.exists():
                        return full_path
            else:
                full_path = Path(search_path) / header
                if full_path.exists():
                    return full_path
        
        return None

    @staticmethod
    def get_system_directories() -> Dict[str, Path]:
        """
        Get standard system directory paths.

        Returns
        -------
        dict
            Dictionary mapping directory types to their paths:
            - 'temp' : Temporary directory
            - 'home' : User home directory
            - 'cache' : User cache directory
            - 'config' : User config directory
            - 'data' : User data directory
            - 'program_files' : Program Files (Windows only)

        Examples
        --------
        >>> dirs = PathResolver.get_system_directories()
        >>> print(dirs['temp'])
        '/tmp'
        """
        import tempfile
        
        dirs = {
            'temp': Path(tempfile.gettempdir()),
            'home': Path.home(),
        }
        
        # XDG directories on Unix
        if is_unix_like():
            dirs['cache'] = Path(
                os.environ.get('XDG_CACHE_HOME',
                              str(Path.home() / '.cache'))
            )
            dirs['config'] = Path(
                os.environ.get('XDG_CONFIG_HOME',
                              str(Path.home() / '.config'))
            )
            dirs['data'] = Path(
                os.environ.get('XDG_DATA_HOME',
                              str(Path.home() / '.local' / 'share'))
            )
        elif is_windows():
            # Windows known folders
            dirs['cache'] = Path(
                os.environ.get('LOCALAPPDATA',
                              str(Path.home() / 'AppData' / 'Local'))
            )
            dirs['config'] = Path(
                os.environ.get('APPDATA',
                              str(Path.home() / 'AppData' / 'Roaming'))
            )
            dirs['data'] = dirs['config']
            
            # Program Files
            program_files = os.environ.get('ProgramFiles', 'C:\\Program Files')
            program_files_x86 = os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')
            dirs['program_files'] = Path(program_files)
            dirs['program_files_x86'] = Path(program_files_x86)
        
        return dirs


# =============================================================================
# System Include Paths
# =============================================================================

def get_system_include_paths() -> List[str]:
    """
    Get standard system include paths for C headers.

    Returns
    -------
    list of str
        System include directories appropriate for the current platform.

    Notes
    -----
    On Unix-like systems, includes /usr/include, /usr/local/include,
    and GCC-specific include paths.
    On Windows, attempts to locate Visual Studio and Windows SDK include paths.

    Examples
    --------
    >>> includes = get_system_include_paths()
    >>> for inc in includes:
    ...     print(inc)
    '/usr/include'
    '/usr/local/include'
    '/usr/lib/gcc/x86_64-linux-gnu/11/include'
    """
    paths = []
    
    if is_unix_like():
        # Common Unix include paths
        common_paths = [
            "/usr/include",
            "/usr/local/include",
            "/opt/local/include",  # MacPorts
            "/opt/homebrew/include",  # Homebrew on Apple Silicon
            "/usr/local/opt",  # Homebrew symlinks
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                paths.append(path)
        
        # GCC-specific includes
        gcc_patterns = [
            "/usr/lib/gcc/*/*/include",
            "/usr/local/lib/gcc/*/*/include",
        ]
        for pattern in gcc_patterns:
            expanded = glob.glob(pattern)
            paths.extend(expanded)
        
        # LLVM/Clang includes
        clang_patterns = [
            "/usr/lib/llvm-*/lib/clang/*/include",
            "/usr/local/llvm*/lib/clang/*/include",
        ]
        for pattern in clang_patterns:
            expanded = glob.glob(pattern)
            paths.extend(expanded)
    
    elif is_windows():
        # Try to find Visual Studio includes
        vc_paths = _find_visual_studio_includes()
        paths.extend(vc_paths)
        
        # Windows SDK includes
        sdk_paths = _find_windows_sdk_includes()
        paths.extend(sdk_paths)
        
        # MinGW includes if present
        mingw_paths = [
            "C:\\MinGW\\include",
            "C:\\msys64\\mingw64\\include",
            "C:\\msys64\\mingw32\\include",
        ]
        for path in mingw_paths:
            if os.path.exists(path):
                paths.append(path)
    
    return paths


def _find_visual_studio_includes() -> List[str]:
    """Find Visual Studio include paths on Windows."""
    paths = []
    
    program_files = Path(os.environ.get('ProgramFiles', 'C:\\Program Files'))
    program_files_x86 = Path(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)'))
    
    # VS 2022, 2019, 2017 paths
    vs_patterns = [
        program_files / "Microsoft Visual Studio" / "2022" / "*" / "VC" / "Tools" / "MSVC" / "*" / "include",
        program_files_x86 / "Microsoft Visual Studio" / "2022" / "*" / "VC" / "Tools" / "MSVC" / "*" / "include",
        program_files / "Microsoft Visual Studio" / "2019" / "*" / "VC" / "Tools" / "MSVC" / "*" / "include",
        program_files_x86 / "Microsoft Visual Studio" / "2019" / "*" / "VC" / "Tools" / "MSVC" / "*" / "include",
        program_files / "Microsoft Visual Studio" / "2017" / "*" / "VC" / "Tools" / "MSVC" / "*" / "include",
        program_files_x86 / "Microsoft Visual Studio" / "2017" / "*" / "VC" / "Tools" / "MSVC" / "*" / "include",
    ]
    
    for pattern in vs_patterns:
        expanded = glob.glob(str(pattern))
        paths.extend(expanded)
    
    # Build Tools
    build_tools_patterns = [
        program_files / "Microsoft Visual Studio" / "BuildTools" / "VC" / "Tools" / "MSVC" / "*" / "include",
        program_files_x86 / "Microsoft Visual Studio" / "BuildTools" / "VC" / "Tools" / "MSVC" / "*" / "include",
    ]
    for pattern in build_tools_patterns:
        expanded = glob.glob(str(pattern))
        paths.extend(expanded)
    
    return paths


def _find_windows_sdk_includes() -> List[str]:
    """Find Windows SDK include paths."""
    paths = []
    
    program_files = Path(os.environ.get('ProgramFiles', 'C:\\Program Files'))
    program_files_x86 = Path(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)'))
    
    # Windows Kits
    kit_patterns = [
        program_files / "Windows Kits" / "10" / "Include" / "*",
        program_files_x86 / "Windows Kits" / "10" / "Include" / "*",
        program_files / "Windows Kits" / "8.1" / "Include" / "*",
        program_files_x86 / "Windows Kits" / "8.1" / "Include" / "*",
        program_files / "Windows Kits" / "8.0" / "Include" / "*",
        program_files_x86 / "Windows Kits" / "8.0" / "Include" / "*",
    ]
    
    for pattern in kit_patterns:
        expanded = glob.glob(str(pattern))
        for kit_path in expanded:
            # Add shared, ucrt, um subdirectories
            for sub in ["shared", "ucrt", "um"]:
                sub_path = Path(kit_path) / sub
                if sub_path.exists():
                    paths.append(str(sub_path))
    
    return paths


def get_system_library_paths() -> List[str]:
    """
    Get standard system library search paths.

    Returns
    -------
    list of str
        System library directories appropriate for the current platform.

    Examples
    --------
    >>> lib_paths = get_system_library_paths()
    >>> for path in lib_paths:
    ...     print(path)
    '/usr/lib'
    '/usr/local/lib'
    '/usr/lib/x86_64-linux-gnu'
    """
    paths = []
    
    if is_unix_like():
        # Standard Unix library paths
        standard_paths = [
            "/usr/lib",
            "/usr/local/lib",
            "/opt/local/lib",
            "/opt/homebrew/lib",
            "/lib",
        ]
        paths.extend([p for p in standard_paths if os.path.exists(p)])
        
        # Architecture-specific paths on Linux
        if is_linux():
            arch = detect_architecture()
            if arch == "x86_64":
                paths.append("/usr/lib/x86_64-linux-gnu")
                paths.append("/lib/x86_64-linux-gnu")
            elif arch == "arm64":
                paths.append("/usr/lib/aarch64-linux-gnu")
                paths.append("/lib/aarch64-linux-gnu")
            elif arch == "arm":
                paths.append("/usr/lib/arm-linux-gnueabihf")
        
        # LD_LIBRARY_PATH
        ld_path = os.environ.get("LD_LIBRARY_PATH", "")
        if ld_path:
            paths.extend(ld_path.split(":"))
    
    elif is_windows():
        # Windows library paths
        paths.extend([
            os.environ.get("SystemRoot", "C:\\Windows") + "\\System32",
            os.environ.get("SystemRoot", "C:\\Windows") + "\\SysWOW64",
        ])
        
        # PATH environment variable
        path_env = os.environ.get("PATH", "")
        if path_env:
            paths.extend(path_env.split(";"))
    
    return [p for p in paths if p and os.path.exists(p)]


# =============================================================================
# Python-specific Information
# =============================================================================

def get_python_info() -> Dict[str, Any]:
    """
    Get detailed Python installation information.

    Returns
    -------
    dict
        Dictionary containing Python version, paths, and configuration.

    Examples
    --------
    >>> info = get_python_info()
    >>> print(f"Python {info['version']} at {info['executable']}")
    >>> print(f"Include path: {info['include']}")
    """
    return {
        'version': sys.version,
        'version_info': tuple(sys.version_info),
        'executable': Path(sys.executable),
        'prefix': Path(sys.prefix),
        'base_prefix': Path(sys.base_prefix),
        'include': Path(sysconfig.get_path('include')),
        'platinclude': Path(sysconfig.get_path('platinclude')),
        'stdlib': Path(sysconfig.get_path('stdlib')),
        'platlib': Path(sysconfig.get_path('platlib')),
        'purelib': Path(sysconfig.get_path('purelib')),
        'bitness': 64 if is_64bit() else 32,
        'implementation': platform.python_implementation(),
        'compiler': platform.python_compiler(),
    }


def get_python_include_paths() -> List[str]:
    """
    Get Python header include paths.

    Returns
    -------
    list of str
        Paths containing Python.h and other Python C API headers.

    Examples
    --------
    >>> includes = get_python_include_paths()
    >>> for inc in includes:
    ...     print(inc)
    '/usr/include/python3.11'
    '/usr/include/x86_64-linux-gnu/python3.11'
    """
    paths = []
    
    # Standard sysconfig paths
    include = sysconfig.get_path('include')
    if include and os.path.exists(include):
        paths.append(include)
    
    platinclude = sysconfig.get_path('platinclude')
    if platinclude and os.path.exists(platinclude) and platinclude != include:
        paths.append(platinclude)
    
    # Additional common locations
    if is_unix_like():
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        extra_paths = [
            f"/usr/include/python{version}",
            f"/usr/local/include/python{version}",
            f"/opt/homebrew/include/python{version}",
            f"/opt/local/include/python{version}",
        ]
        for path in extra_paths:
            if os.path.exists(path):
                paths.append(path)
    
    # Virtual environment
    if hasattr(sys, 'real_prefix') or (
        hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
    ):
        venv_include = Path(sys.prefix) / "include"
        if venv_include.exists():
            paths.append(str(venv_include))
    
    return paths


# =============================================================================
# Compiler Toolchain Detection
# =============================================================================

def detect_compiler_toolchain() -> Dict[str, Any]:
    """
    Detect installed compiler toolchains on the system.

    Returns
    -------
    dict
        Dictionary with detected compilers and their versions.

    Examples
    --------
    >>> toolchains = detect_compiler_toolchain()
    >>> print(toolchains['gcc'])
    {'path': '/usr/bin/gcc', 'version': '11.4.0'}
    >>> print(toolchains['clang'])
    {'path': '/usr/bin/clang', 'version': '14.0.0'}
    """
    import shutil
    
    toolchains = {}
    
    # Check GCC
    gcc_path = shutil.which("gcc")
    if gcc_path:
        toolchains['gcc'] = {
            'path': gcc_path,
            'version': _get_compiler_version("gcc")
        }
    
    # Check Clang
    clang_path = shutil.which("clang")
    if clang_path:
        toolchains['clang'] = {
            'path': clang_path,
            'version': _get_compiler_version("clang")
        }
    
    # Check MSVC on Windows
    if is_windows():
        cl_path = shutil.which("cl")
        if cl_path:
            toolchains['msvc'] = {
                'path': cl_path,
                'version': _get_compiler_version("cl")
            }
    
    return toolchains


def _get_compiler_version(exe: str) -> str:
    """Get compiler version string."""
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.splitlines()[0].strip()
    except Exception:
        pass
    return "unknown"


# =============================================================================
# PlatformInfo Class
# =============================================================================

class PlatformInfo:
    """
    Static helper class for platform-dependent information.

    This class provides a unified interface for accessing platform-specific
    values like shared library extensions, include paths, and compiler arguments.
    All methods are static for easy access without instantiation.

    Methods
    -------
    shared_lib_extension
        Return the file extension for shared libraries.
    executable_extension
        Return the file extension for executables.
    object_file_extension
        Return the file extension for object files.
    static_lib_extension
        Return the file extension for static libraries.
    python_include_args
        Return compiler arguments to include Python headers.
    get_system_include_args
        Return compiler arguments for system includes.
    get_default_cflags
        Get recommended default compiler flags for the platform.
    get_hostname
        Get the system hostname.

    Examples
    --------
    >>> ext = PlatformInfo.shared_lib_extension()
    >>> print(ext)
    '.so'

    >>> includes = PlatformInfo.python_include_args()
    >>> print(includes[0])
    '-I/usr/include/python3.11'
    """

    @staticmethod
    def shared_lib_extension() -> str:
        """
        Return the file extension for shared libraries on the current platform.

        Returns
        -------
        str
            '.dll' on Windows, '.dylib' on macOS, '.so' elsewhere.

        Examples
        --------
        >>> ext = PlatformInfo.shared_lib_extension()
        >>> lib_name = f"mylib{ext}"
        """
        if is_windows():
            return ".dll"
        if is_macos():
            return ".dylib"
        return ".so"

    @staticmethod
    def executable_extension() -> str:
        """
        Return the file extension for executables on the current platform.

        Returns
        -------
        str
            '.exe' on Windows, empty string elsewhere.

        Examples
        --------
        >>> ext = PlatformInfo.executable_extension()
        >>> prog = f"myprogram{ext}"
        """
        return ".exe" if is_windows() else ""

    @staticmethod
    def object_file_extension() -> str:
        """
        Return the file extension for object files on the current platform.

        Returns
        -------
        str
            '.obj' on Windows, '.o' elsewhere.

        Examples
        --------
        >>> ext = PlatformInfo.object_file_extension()
        >>> obj = f"source{ext}"
        """
        return ".obj" if is_windows() else ".o"

    @staticmethod
    def static_lib_extension() -> str:
        """
        Return the file extension for static libraries on the current platform.

        Returns
        -------
        str
            '.lib' on Windows, '.a' elsewhere.

        Examples
        --------
        >>> ext = PlatformInfo.static_lib_extension()
        >>> lib = f"libmylib{ext}"
        """
        return ".lib" if is_windows() else ".a"

    @staticmethod
    def python_include_args() -> List[str]:
        """
        Return compiler arguments to include Python and system headers.

        Tries multiple methods:
        1. `python3-config --includes`
        2. sysconfig paths
        3. Common system include paths

        Returns
        -------
        list of str
            Include flags (e.g., ['-I/usr/include/python3.11', '-I/usr/include']).

        Notes
        -----
        This is crucial for compiling code that includes Python.h or
        standard C headers.

        Examples
        --------
        >>> args = PlatformInfo.python_include_args()
        >>> compiler.compile(cflags=args + ["-O3"])
        """
        include_args = []
        
        # Method 1: python3-config
        try:
            output = subprocess.check_output(
                ["python3-config", "--includes"],
                text=True,
                stderr=subprocess.DEVNULL
            ).strip()
            include_args.extend(output.split())
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Method 2: sysconfig paths
            python_include = sysconfig.get_path('include')
            if python_include:
                include_args.append(f"-I{python_include}")
            
            python_platinclude = sysconfig.get_path('platinclude')
            if python_platinclude and python_platinclude != python_include:
                include_args.append(f"-I{python_platinclude}")
        
        # Method 3: Add system include paths for standard headers
        for sys_path in get_system_include_paths():
            include_args.append(f"-I{sys_path}")
        
        # Method 4: Add current directory
        include_args.append("-I.")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_args = []
        for arg in include_args:
            if arg not in seen:
                seen.add(arg)
                unique_args.append(arg)
        
        return unique_args

    @staticmethod
    def get_system_include_args() -> List[str]:
        """
        Return compiler arguments for system include directories.

        Returns
        -------
        list of str
            Include flags for system headers only.

        Examples
        --------
        >>> args = PlatformInfo.get_system_include_args()
        >>> print(args)
        ['-I/usr/include', '-I/usr/local/include']
        """
        args = []
        for sys_path in get_system_include_paths():
            args.append(f"-I{sys_path}")
        return args

    @staticmethod
    def get_default_cflags() -> List[str]:
        """
        Get recommended default compiler flags for the current platform.

        Returns
        -------
        list of str
            Platform-appropriate default optimization and warning flags.

        Examples
        --------
        >>> cflags = PlatformInfo.get_default_cflags()
        >>> print(cflags)
        ['-O3', '-Wall', '-fPIC']
        """
        if is_windows():
            return ["/O2", "/W3"]
        else:
            return ["-O3", "-Wall", "-fPIC"]

    @staticmethod
    def get_hostname() -> str:
        """
        Get the system hostname.

        Returns
        -------
        str
            System hostname, or "unknown" if unavailable.
        """
        return get_hostname()

    @staticmethod
    def get_platform_tag() -> str:
        """
        Get a platform identification tag for binary compatibility.

        Returns
        -------
        str
            Platform tag in the format 'os-architecture'
            (e.g., 'linux-x86_64', 'win32-x86', 'macos-arm64').

        Examples
        --------
        >>> tag = PlatformInfo.get_platform_tag()
        >>> print(tag)
        'linux-x86_64'
        """
        if is_windows():
            os_name = "win32" if not is_64bit() else "win64"
        elif is_macos():
            os_name = "macos"
        elif is_linux():
            os_name = "linux"
        else:
            os_name = sys.platform
        
        arch = detect_architecture()
        return f"{os_name}-{arch}"


# =============================================================================
# SystemInfo Class
# =============================================================================

@dataclass
class SystemInfo:
    """
    Detailed system information container class.

    This dataclass holds comprehensive information about the current system,
    including OS details, Python installation, available compilers, and
    relevant paths. It can be used for debugging, logging, or conditional
    behavior based on system capabilities.

    Attributes
    ----------
    os_name : str
        Operating system name (e.g., 'Windows', 'Linux', 'Darwin').
    os_version : str
        Detailed OS version string.
    architecture : str
        CPU architecture (e.g., 'x86_64', 'arm64').
    hostname : str
        System hostname.
    python_version : str
        Python version string.
    python_executable : Path
        Path to Python executable.
    python_include : Path
        Path to Python include directory.
    python_bitness : int
        32 or 64 bit.
    is_64bit : bool
        Whether Python is 64-bit.
    shared_lib_ext : str
        Shared library extension.
    system_include_paths : List[str]
        Standard C include paths.
    system_library_paths : List[str]
        Standard library search paths.
    available_compilers : Dict[str, Any]
        Detected compilers and their versions.
    environment_variables : Dict[str, str]
        Relevant environment variables.

    Methods
    -------
    collect
        Class method to gather all system information.
    to_dict
        Convert system info to a dictionary.
    summary
        Return a human-readable summary string.

    Examples
    --------
    >>> info = SystemInfo.collect()
    >>> print(info.summary())
    System: Linux 6.5.0 (x86_64)
    Python: 3.11.4 at /usr/bin/python3
    Compilers: gcc 11.4.0

    >>> data = info.to_dict()
    >>> print(data['architecture'])
    'x86_64'
    """
    
    os_name: str
    os_version: str
    architecture: str
    hostname: str
    python_version: str
    python_executable: Path
    python_include: Path
    python_bitness: int
    is_64bit: bool
    shared_lib_ext: str
    system_include_paths: List[str] = field(default_factory=list)
    system_library_paths: List[str] = field(default_factory=list)
    available_compilers: Dict[str, Any] = field(default_factory=dict)
    environment_variables: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def collect(cls) -> 'SystemInfo':
        """
        Collect comprehensive system information.

        Returns
        -------
        SystemInfo
            Populated SystemInfo instance with current system data.

        Examples
        --------
        >>> info = SystemInfo.collect()
        >>> print(info.architecture)
        'x86_64'
        """
        python_info = get_python_info()
        
        # Collect relevant environment variables
        env_vars = {}
        relevant_vars = [
            'PATH', 'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH',
            'CFLAGS', 'LDFLAGS', 'CC', 'CXX',
            'CFAST_CFLAGS', 'CFAST_COMPILER', 'CFAST_LIBS',
        ]
        for var in relevant_vars:
            if var in os.environ:
                env_vars[var] = os.environ[var]
        
        return cls(
            os_name=platform.system(),
            os_version=get_os_version(),
            architecture=detect_architecture(),
            hostname=get_hostname(),
            python_version=python_info['version'],
            python_executable=python_info['executable'],
            python_include=python_info['include'],
            python_bitness=python_info['bitness'],
            is_64bit=is_64bit(),
            shared_lib_ext=PlatformInfo.shared_lib_extension(),
            system_include_paths=get_system_include_paths(),
            system_library_paths=get_system_library_paths(),
            available_compilers=detect_compiler_toolchain(),
            environment_variables=env_vars,
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert system info to a dictionary.

        Returns
        -------
        dict
            Dictionary representation with Path objects converted to strings.

        Examples
        --------
        >>> info = SystemInfo.collect()
        >>> data = info.to_dict()
        >>> import json
        >>> print(json.dumps(data, indent=2, default=str))
        """
        data = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Path):
                data[key] = str(value)
            elif isinstance(value, (list, dict)):
                data[key] = value
            else:
                data[key] = value
        return data

    def summary(self) -> str:
        """
        Return a human-readable summary of system information.

        Returns
        -------
        str
            Formatted summary string.

        Examples
        --------
        >>> info = SystemInfo.collect()
        >>> print(info.summary())
        System: Linux 6.5.0 (x86_64)
        Python: 3.11.4 (64-bit) at /usr/bin/python3
        Compilers: gcc 11.4.0, clang 14.0.0
        """
        lines = [
            f"System: {self.os_name} {self.os_version} ({self.architecture})",
            f"Python: {self.python_version.split()[0]} ({self.python_bitness}-bit) at {self.python_executable}",
        ]
        
        if self.available_compilers:
            compilers = []
            for name, info in self.available_compilers.items():
                version = info.get('version', 'unknown')
                compilers.append(f"{name} {version}")
            lines.append(f"Compilers: {', '.join(compilers)}")
        else:
            lines.append("Compilers: None detected")
        
        lines.append(f"Shared lib ext: {self.shared_lib_ext}")
        lines.append(f"Hostname: {self.hostname}")
        
        return "\n".join(lines)


# =============================================================================
# Convenience Functions
# =============================================================================

def get_platform_details() -> Dict[str, Any]:
    """
    Return comprehensive platform information as a dictionary.

    This is a convenience wrapper around SystemInfo.collect().to_dict().

    Returns
    -------
    dict
        Dictionary with complete platform information.

    Examples
    --------
    >>> details = get_platform_details()
    >>> print(details['os_name'])
    'Linux'
    >>> print(details['available_compilers'].keys())
    dict_keys(['gcc', 'clang'])
    """
    return SystemInfo.collect().to_dict()


def is_compatible_platform() -> bool:
    """
    Check if the current platform is fully compatible with cfast.

    Returns
    -------
    bool
        True if platform is supported, False otherwise.

    Notes
    -----
    Issues a warning if the platform is partially supported or untested.

    Examples
    --------
    >>> if is_compatible_platform():
    ...     print("Platform is fully supported")
    ... else:
    ...     print("Platform may have limitations")
    """
    if is_linux() or is_macos() or is_windows():
        return True
    
    warnings.warn(
        f"Platform '{sys.platform}' is not officially tested with cfast. "
        "Some features may not work correctly.",
        UserWarning,
        stacklevel=2
    )
    return False