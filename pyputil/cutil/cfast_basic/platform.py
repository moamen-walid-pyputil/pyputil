#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Platform-specific utilities for the cfast_basic library.

This module provides platform detection, system include path discovery,
shared library extension determination, and helper functions for obtaining
Python-specific compiler flags. It abstracts away operating system differences
to provide a uniform interface for the rest of the library.

The main class :class:`PlatformInfo` contains static methods for retrieving
platform-dependent information such as:
    - Shared library file extensions (.dll, .so, .dylib)
    - System C header include paths
    - Python development header include flags
    - Platform identification

Examples
--------
>>> from cfast_basic.platform import PlatformInfo
>>> ext = PlatformInfo.shared_lib_extension()
>>> print(f"Shared libraries on this platform use extension: {ext}")
>>> includes = PlatformInfo.python_include_args()
>>> print(f"Python include flags: {includes}")
"""

import sys
import sysconfig
import subprocess
import glob
from pathlib import Path
from typing import List, Optional, Tuple


class PlatformInfo:
    """
    Helper class for obtaining platform-dependent information.

    This class provides static methods that return information about the
    current operating system, such as the correct shared library extension,
    system include paths for C headers, and compiler flags for Python
    development headers. All methods are stateless and can be called
    without instantiating the class.

    Attributes
    ----------
    This class has no instance attributes; all methods are static.

    Notes
    -----
    The methods in this class are designed to work on Windows, macOS, and
    Linux. They fall back gracefully when certain information cannot be
    determined (e.g., when Visual Studio is not installed on Windows).
    """

    @staticmethod
    def is_windows() -> bool:
        """
        Determine if the current platform is Windows.

        Returns
        -------
        bool
            True if running on Windows, False otherwise.

        Examples
        --------
        >>> if PlatformInfo.is_windows():
        ...     print("Running on Windows")
        ... else:
        ...     print("Running on Unix-like system")
        """
        return sys.platform.startswith("win")

    @staticmethod
    def is_macos() -> bool:
        """
        Determine if the current platform is macOS.

        Returns
        -------
        bool
            True if running on macOS (Darwin), False otherwise.

        Examples
        --------
        >>> if PlatformInfo.is_macos():
        ...     print("Running on macOS")
        """
        return sys.platform.startswith("darwin")

    @staticmethod
    def is_linux() -> bool:
        """
        Determine if the current platform is Linux.

        Returns
        -------
        bool
            True if running on Linux, False otherwise.

        Examples
        --------
        >>> if PlatformInfo.is_linux():
        ...     print("Running on Linux")
        """
        return sys.platform.startswith("linux")

    @staticmethod
    def shared_lib_extension() -> str:
        """
        Return the file extension for shared libraries on the current platform.

        The extension includes the leading dot.

        Returns
        -------
        str
            Shared library extension:
                - ``'.dll'`` on Windows
                - ``'.dylib'`` on macOS
                - ``'.so'`` on Linux and other Unix-like systems

        Examples
        --------
        >>> ext = PlatformInfo.shared_lib_extension()
        >>> lib_path = Path(f"mylib{ext}")
        >>> print(lib_path)  # mylib.so on Linux, mylib.dll on Windows
        """
        if PlatformInfo.is_windows():
            return ".dll"
        if PlatformInfo.is_macos():
            return ".dylib"
        return ".so"

    @staticmethod
    def get_system_include_paths() -> List[str]:
        """
        Get standard system include paths for C headers.

        This method returns a list of directories where system C headers
        are typically located. The returned paths are absolute and may
        include glob patterns that have been expanded.

        Returns
        -------
        list of str
            Absolute paths to system C header directories. The list may
            be empty if no standard paths are found.

        Notes
        -----
        On Unix-like systems, this includes:
            - ``/usr/include``
            - ``/usr/local/include``
            - GCC-specific include directories (via glob expansion)

        On Windows, this attempts to locate:
            - Visual Studio C runtime includes
            - Windows SDK includes

        Examples
        --------
        >>> paths = PlatformInfo.get_system_include_paths()
        >>> for path in paths:
        ...     print(f"System include: {path}")
        """
        paths: List[str] = []

        if not PlatformInfo.is_windows():
            # Unix-like system include paths
            common_paths = [
                "/usr/include",
                "/usr/local/include",
            ]
            paths.extend(common_paths)

            # GCC-specific includes with recursive glob
            gcc_pattern = "/usr/lib/gcc/**/include"
            try:
                expanded = glob.glob(gcc_pattern, recursive=True)
                paths.extend(expanded)
            except (OSError, glob.error):
                # Ignore glob errors on restricted filesystems
                pass

        else:
            # Windows: attempt to locate Visual Studio and SDK includes
            program_files = Path("C:/Program Files")
            program_files_x86 = Path("C:/Program Files (x86)")

            msvc_patterns = [
                program_files / "Microsoft Visual Studio" / "**" / "VC" / "Tools" / "**" / "include",
                program_files_x86 / "Microsoft Visual Studio" / "**" / "VC" / "Tools" / "**" / "include",
                program_files / "Windows Kits" / "**" / "Include" / "**",
            ]

            for pattern in msvc_patterns:
                try:
                    expanded = glob.glob(str(pattern), recursive=True)
                    paths.extend(expanded)
                except (OSError, glob.error):
                    pass

        return paths

    @staticmethod
    def python_include_args() -> List[str]:
        """
        Return compiler arguments to include Python and system headers.

        This method attempts multiple strategies to obtain the correct
        include flags for compiling C extensions that use the Python C API.

        Strategies (in order of preference):
            1. Call ``python3-config --includes`` (Unix-like systems)
            2. Use ``sysconfig`` paths for include and platinclude
            3. Add system include paths from :meth:`get_system_include_paths`
            4. Add current directory (``-I.``)

        Returns
        -------
        list of str
            Include flags formatted as compiler arguments, e.g.,
            ``['-I/usr/include/python3.9', '-I/usr/include']``.
            Duplicate flags are removed while preserving order.

        Examples
        --------
        >>> flags = PlatformInfo.python_include_args()
        >>> print(" ".join(flags))
        -I/usr/include/python3.11 -I/usr/include -I.

        Notes
        -----
        On Windows, ``python3-config`` is typically not available, so the
        method falls back to ``sysconfig`` paths and Visual Studio detection.
        """
        include_args: List[str] = []

        # Strategy 1: python3-config (Unix-like systems)
        if not PlatformInfo.is_windows():
            try:
                output = subprocess.check_output(
                    ["python3-config", "--includes"],
                    text=True,
                    stderr=subprocess.DEVNULL
                ).strip()
                if output:
                    include_args.extend(output.split())
            except (subprocess.CalledProcessError, FileNotFoundError, OSError):
                pass

        # Strategy 2: sysconfig paths
        python_include = sysconfig.get_path('include')
        if python_include:
            include_args.append(f"-I{python_include}")

        python_platinclude = sysconfig.get_path('platinclude')
        if python_platinclude and python_platinclude != python_include:
            include_args.append(f"-I{python_platinclude}")

        # Strategy 3: System include paths (for standard C headers)
        for sys_path in PlatformInfo.get_system_include_paths():
            include_args.append(f"-I{sys_path}")

        # Strategy 4: Current directory
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
    def get_platform_tuple() -> Tuple[str, str]:
        """
        Get a tuple identifying the current platform.

        Returns
        -------
        tuple of (str, str)
            A tuple containing:
                - system: The operating system name ('windows', 'linux', 'darwin')
                - machine: The machine architecture ('x86_64', 'arm64', etc.)

        Examples
        --------
        >>> system, arch = PlatformInfo.get_platform_tuple()
        >>> print(f"Running on {system} ({arch})")
        """
        system = sys.platform
        if system.startswith("win"):
            system = "windows"
        elif system.startswith("linux"):
            system = "linux"
        elif system.startswith("darwin"):
            system = "darwin"

        import platform
        machine = platform.machine().lower()

        return system, machine

    @staticmethod
    def get_default_compiler() -> Optional[str]:
        """
        Get a reasonable default compiler name for the current platform.

        Returns
        -------
        str or None
            The recommended compiler executable name for the current platform,
            or None if no reasonable default can be determined.
            - Windows: 'cl' (MSVC)
            - macOS: 'clang'
            - Linux: 'gcc'

        Examples
        --------
        >>> default = PlatformInfo.get_default_compiler()
        >>> print(f"Recommended compiler: {default}")
        """
        if PlatformInfo.is_windows():
            return "cl"
        if PlatformInfo.is_macos():
            return "clang"
        return "gcc"