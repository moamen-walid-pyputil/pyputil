#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    PLATFORM UTILITIES
==================================

Cross-platform detection and information utilities for system
identification, architecture detection, and platform-specific
configurations.

This module provides comprehensive platform detection capabilities:
- Operating system identification (Windows, Linux, macOS, BSD, etc.)
- CPU architecture detection (x86, x86_64, ARM, ARM64, etc.)
- Python environment information (version, implementation, ABI)
- System resource information (memory, CPU count, disk usage)
- Platform-specific path and extension handling
- WSL, Cygwin, MSYS environment detection
- Android and iOS platform detection

The module caches platform information for performance and provides
both high-level convenience functions and detailed PlatformInfo objects.
"""

import os
import sys
import platform
import struct
import subprocess
import re
import socket
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# ============================================================================
# Platform Type Enumeration
# ============================================================================

class PlatformType(Enum):
    """
    Platform type enumeration for operating system identification.
    
    This enum provides a normalized way to identify the current operating
    system across different Python implementations and platform strings.
    
    Attributes
    ----------
    WINDOWS : str
        Microsoft Windows operating system (value: "windows").
        Includes all Windows versions (7, 8, 10, 11, Server).
    LINUX : str
        Linux operating system (value: "linux").
        Includes all Linux distributions (Ubuntu, Debian, Fedora, etc.).
    MACOS : str
        Apple macOS operating system (value: "darwin").
        Includes all macOS versions (Catalina, Big Sur, Monterey, etc.).
    BSD : str
        BSD operating system family (value: "bsd").
        Includes FreeBSD, OpenBSD, NetBSD, DragonFly BSD.
    SUNOS : str
        Oracle Solaris/SunOS operating system (value: "sunos").
    AIX : str
        IBM AIX operating system (value: "aix").
    ANDROID : str
        Android operating system (value: "android").
        Detected when running Python on Android.
    IOS : str
        Apple iOS operating system (value: "ios").
        Detected when running Python on iOS.
    CYGWIN : str
        Cygwin environment on Windows (value: "cygwin").
        POSIX compatibility layer for Windows.
    MSYS : str
        MSYS/MSYS2 environment on Windows (value: "msys").
        Used by Git Bash, MSYS2, etc.
    WSL : str
        Windows Subsystem for Linux (value: "wsl").
        Linux environment running on Windows.
    EMSCRIPTEN : str
        Emscripten/WebAssembly environment (value: "emscripten").
    UNKNOWN : str
        Unknown or unsupported platform (value: "unknown").
    
    Examples
    --------
    >>> platform_type = PlatformType.LINUX
    >>> print(platform_type.value)
    'linux'
    >>> if platform_type.is_unix():
    ...     print("This is a Unix-like system")
    >>> print(platform_type.get_shared_library_extension())
    '.so'
    """
    
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "darwin"
    BSD = "bsd"
    SUNOS = "sunos"
    AIX = "aix"
    ANDROID = "android"
    IOS = "ios"
    CYGWIN = "cygwin"
    MSYS = "msys"
    WSL = "wsl"
    EMSCRIPTEN = "emscripten"
    UNKNOWN = "unknown"
    
    def is_unix(self) -> bool:
        """
        Check if this platform type is Unix-like.
        
        Unix-like systems include Linux, macOS, BSD, Solaris, AIX,
        Android, and iOS. These systems share common features like
        POSIX compliance, forward-slash paths, and similar system calls.
        
        Returns
        -------
        bool
            True if the platform is Unix-like, False otherwise.
        
        Examples
        --------
        >>> PlatformType.LINUX.is_unix()
        True
        >>> PlatformType.WINDOWS.is_unix()
        False
        """
        return self in (
            self.LINUX,
            self.MACOS,
            self.BSD,
            self.SUNOS,
            self.AIX,
            self.ANDROID,
            self.IOS,
        )
    
    def is_windows_family(self) -> bool:
        """
        Check if this platform is Windows or Windows-compatible.
        
        This includes native Windows, Cygwin, MSYS, and WSL environments.
        WSL is included because it can run Windows executables and
        shares some Windows-specific behaviors.
        
        Returns
        -------
        bool
            True if Windows or Windows-compatible environment.
        
        Examples
        --------
        >>> PlatformType.WINDOWS.is_windows_family()
        True
        >>> PlatformType.CYGWIN.is_windows_family()
        True
        >>> PlatformType.WSL.is_windows_family()
        True
        """
        return self in (self.WINDOWS, self.CYGWIN, self.MSYS, self.WSL)
    
    def is_linux_family(self) -> bool:
        """
        Check if this platform is Linux or Linux-compatible.
        
        This includes native Linux, Android (which uses Linux kernel),
        and WSL (Windows Subsystem for Linux).
        
        Returns
        -------
        bool
            True if Linux or Linux-compatible environment.
        
        Examples
        --------
        >>> PlatformType.LINUX.is_linux_family()
        True
        >>> PlatformType.ANDROID.is_linux_family()
        True
        >>> PlatformType.WSL.is_linux_family()
        True
        """
        return self in (self.LINUX, self.ANDROID, self.WSL)
    
    def is_apple_family(self) -> bool:
        """
        Check if this platform is Apple operating system.
        
        This includes macOS and iOS, which share the Darwin kernel
        and many system frameworks.
        
        Returns
        -------
        bool
            True if macOS or iOS.
        
        Examples
        --------
        >>> PlatformType.MACOS.is_apple_family()
        True
        >>> PlatformType.IOS.is_apple_family()
        True
        """
        return self in (self.MACOS, self.IOS)
    
    def is_mobile(self) -> bool:
        """
        Check if this platform is a mobile operating system.
        
        Returns
        -------
        bool
            True if Android or iOS.
        """
        return self in (self.ANDROID, self.IOS)
    
    def is_embedded(self) -> bool:
        """
        Check if this platform is an embedded/WebAssembly environment.
        
        Returns
        -------
        bool
            True if Emscripten/WebAssembly.
        """
        return self == self.EMSCRIPTEN
    
    def get_executable_extension(self) -> str:
        """
        Get the executable file extension for this platform.
        
        Windows uses '.exe' for executables, while Unix-like systems
        typically have no extension (executable bit instead).
        
        Returns
        -------
        str
            Executable extension including the dot (e.g., '.exe' or '').
        
        Examples
        --------
        >>> PlatformType.WINDOWS.get_executable_extension()
        '.exe'
        >>> PlatformType.LINUX.get_executable_extension()
        ''
        """
        if self.is_windows_family() and self != self.WSL:
            return ".exe"
        return ""
    
    def get_shared_library_extension(self) -> str:
        """
        Get the shared library (dynamic library) extension.
        
        Different platforms use different extensions for shared libraries:
        - Windows: .dll (Dynamic Link Library)
        - macOS/iOS: .dylib (Dynamic Library)
        - Linux/Unix: .so (Shared Object)
        
        Returns
        -------
        str
            Shared library extension including the dot.
        
        Examples
        --------
        >>> PlatformType.WINDOWS.get_shared_library_extension()
        '.dll'
        >>> PlatformType.LINUX.get_shared_library_extension()
        '.so'
        >>> PlatformType.MACOS.get_shared_library_extension()
        '.dylib'
        """
        if self == self.WINDOWS:
            return ".dll"
        elif self.is_apple_family():
            return ".dylib"
        else:
            return ".so"
    
    def get_static_library_extension(self) -> str:
        """
        Get the static library extension.
        
        Windows uses '.lib' for static libraries, while Unix-like systems
        use '.a' (archive) files.
        
        Returns
        -------
        str
            Static library extension including the dot.
        
        Examples
        --------
        >>> PlatformType.WINDOWS.get_static_library_extension()
        '.lib'
        >>> PlatformType.LINUX.get_static_library_extension()
        '.a'
        """
        if self == self.WINDOWS:
            return ".lib"
        return ".a"
    
    def get_object_extension(self) -> str:
        """
        Get the object file extension.
        
        Windows uses '.obj' for object files, while Unix-like systems
        use '.o' (object) files.
        
        Returns
        -------
        str
            Object file extension including the dot.
        
        Examples
        --------
        >>> PlatformType.WINDOWS.get_object_extension()
        '.obj'
        >>> PlatformType.LINUX.get_object_extension()
        '.o'
        """
        if self == self.WINDOWS:
            return ".obj"
        return ".o"
    
    def get_python_extension_module_extension(self) -> str:
        """
        Get the Python C extension module extension.
        
        Python uses platform-specific extensions for compiled modules:
        - Windows: .pyd (Python Dynamic Module)
        - Linux/Unix: .so (same as shared library)
        - macOS: .so (same as shared library)
        
        Returns
        -------
        str
            Python extension module extension including the dot.
        
        Examples
        --------
        >>> PlatformType.WINDOWS.get_python_extension_module_extension()
        '.pyd'
        >>> PlatformType.LINUX.get_python_extension_module_extension()
        '.so'
        """
        if self == self.WINDOWS:
            return ".pyd"
        elif self.is_apple_family():
            return ".so"
        else:
            return ".so"
    
    def get_path_separator(self) -> str:
        """
        Get the path separator for this platform.
        
        Windows uses backslash ('\\'), Unix uses forward slash ('/').
        
        Returns
        -------
        str
            Path separator character.
        
        Examples
        --------
        >>> PlatformType.WINDOWS.get_path_separator()
        '\\\\'
        >>> PlatformType.LINUX.get_path_separator()
        '/'
        """
        if self == self.WINDOWS:
            return "\\"
        return "/"
    
    def get_path_list_separator(self) -> str:
        """
        Get the PATH environment variable separator.
        
        Windows uses semicolon (';'), Unix uses colon (':').
        
        Returns
        -------
        str
            PATH list separator character.
        
        Examples
        --------
        >>> PlatformType.WINDOWS.get_path_list_separator()
        ';'
        >>> PlatformType.LINUX.get_path_list_separator()
        ':'
        """
        if self == self.WINDOWS:
            return ";"
        return ":"
    
    def get_line_ending(self) -> str:
        """
        Get the default line ending for text files.
        
        Windows uses CR+LF ('\\r\\n'), Unix uses LF ('\\n').
        
        Returns
        -------
        str
            Line ending string.
        
        Examples
        --------
        >>> PlatformType.WINDOWS.get_line_ending()
        '\\\\r\\\\n'
        >>> PlatformType.LINUX.get_line_ending()
        '\\\\n'
        """
        if self == self.WINDOWS:
            return "\r\n"
        return "\n"
    
    def get_dev_null(self) -> str:
        """
        Get the path to the null device.
        
        Windows uses 'NUL', Unix uses '/dev/null'.
        
        Returns
        -------
        str
            Path to null device.
        
        Examples
        --------
        >>> PlatformType.WINDOWS.get_dev_null()
        'NUL'
        >>> PlatformType.LINUX.get_dev_null()
        '/dev/null'
        """
        if self == self.WINDOWS:
            return "NUL"
        return "/dev/null"


# ============================================================================
# Architecture Type Enumeration
# ============================================================================

class ArchitectureType(Enum):
    """
    CPU architecture enumeration for processor identification.
    
    This enum provides a normalized way to identify the CPU architecture
    across different platform strings and Python implementations.
    
    Attributes
    ----------
    X86 : str
        32-bit x86 architecture (value: "x86").
        Includes i386, i486, i586, i686, and similar.
    X86_64 : str
        64-bit x86-64 architecture (value: "x86_64").
        Also known as AMD64, Intel 64, or x64.
    ARM : str
        32-bit ARM architecture (value: "arm").
        Includes armv5, armv6, armv7, and similar.
    ARM64 : str
        64-bit ARM architecture (value: "arm64").
        Also known as AArch64.
    PPC : str
        32-bit PowerPC architecture (value: "ppc").
    PPC64 : str
        64-bit PowerPC architecture (value: "ppc64").
        Includes ppc64le (little-endian).
    S390X : str
        IBM System/390 64-bit architecture (value: "s390x").
        Used on IBM mainframes.
    MIPS : str
        32-bit MIPS architecture (value: "mips").
    MIPS64 : str
        64-bit MIPS architecture (value: "mips64").
    RISCV : str
        32-bit RISC-V architecture (value: "riscv").
    RISCV64 : str
        64-bit RISC-V architecture (value: "riscv64").
    SPARC : str
        32-bit SPARC architecture (value: "sparc").
    SPARC64 : str
        64-bit SPARC architecture (value: "sparc64").
    WASM : str
        WebAssembly architecture (value: "wasm").
    UNKNOWN : str
        Unknown or unsupported architecture (value: "unknown").
    
    Examples
    --------
    >>> arch = ArchitectureType.X86_64
    >>> print(arch.value)
    'x86_64'
    >>> if arch.is_64bit():
    ...     print("64-bit architecture")
    >>> if arch.is_x86():
    ...     print("x86-based processor")
    >>> print(arch.get_march_flag())
    'x86-64'
    """
    
    X86 = "x86"
    X86_64 = "x86_64"
    ARM = "arm"
    ARM64 = "arm64"
    PPC = "ppc"
    PPC64 = "ppc64"
    S390X = "s390x"
    MIPS = "mips"
    MIPS64 = "mips64"
    RISCV = "riscv"
    RISCV64 = "riscv64"
    SPARC = "sparc"
    SPARC64 = "sparc64"
    WASM = "wasm"
    UNKNOWN = "unknown"
    
    def is_64bit(self) -> bool:
        """
        Check if this architecture is 64-bit.
        
        Returns
        -------
        bool
            True if 64-bit architecture, False otherwise.
        
        Examples
        --------
        >>> ArchitectureType.X86_64.is_64bit()
        True
        >>> ArchitectureType.X86.is_64bit()
        False
        """
        return self in (
            self.X86_64,
            self.ARM64,
            self.PPC64,
            self.S390X,
            self.MIPS64,
            self.RISCV64,
            self.SPARC64,
        )
    
    def is_32bit(self) -> bool:
        """
        Check if this architecture is 32-bit.
        
        Returns
        -------
        bool
            True if 32-bit architecture, False otherwise.
        """
        return not self.is_64bit() and self != self.UNKNOWN and self != self.WASM
    
    def is_arm(self) -> bool:
        """
        Check if this architecture is ARM-based.
        
        Returns
        -------
        bool
            True if ARM or ARM64 architecture.
        
        Examples
        --------
        >>> ArchitectureType.ARM64.is_arm()
        True
        >>> ArchitectureType.X86_64.is_arm()
        False
        """
        return self in (self.ARM, self.ARM64)
    
    def is_x86(self) -> bool:
        """
        Check if this architecture is x86-based.
        
        Returns
        -------
        bool
            True if x86 or x86_64 architecture.
        
        Examples
        --------
        >>> ArchitectureType.X86_64.is_x86()
        True
        >>> ArchitectureType.ARM64.is_x86()
        False
        """
        return self in (self.X86, self.X86_64)
    
    def is_riscv(self) -> bool:
        """
        Check if this architecture is RISC-V.
        
        Returns
        -------
        bool
            True if RISC-V architecture.
        """
        return self in (self.RISCV, self.RISCV64)
    
    def is_ppc(self) -> bool:
        """
        Check if this architecture is PowerPC.
        
        Returns
        -------
        bool
            True if PowerPC architecture.
        """
        return self in (self.PPC, self.PPC64)
    
    def get_word_size(self) -> int:
        """
        Get the word size in bits for this architecture.
        
        Returns
        -------
        int
            Word size in bits (32 or 64).
        """
        return 64 if self.is_64bit() else 32
    
    def get_endianness(self) -> str:
        """
        Get the default endianness for this architecture.
        
        Returns
        -------
        str
            'little' or 'big' endian.
        
        Notes
        -----
        Most modern architectures are little-endian (x86, ARM).
        Some architectures can be either (PPC, MIPS, ARM can be big-endian).
        """
        if self in (self.X86, self.X86_64):
            return "little"
        elif self in (self.ARM, self.ARM64):
            return "little"  # Usually little, can be big
        elif self in (self.PPC, self.PPC64):
            return "big"  # Can be little for ppc64le
        else:
            return sys.byteorder
    
    def get_march_flag(self) -> str:
        """
        Get the -march flag value for GCC/Clang.
        
        This returns the appropriate architecture flag for compiler
        optimization and targeting.
        
        Returns
        -------
        str
            Architecture flag string for -march.
        
        Examples
        --------
        >>> ArchitectureType.X86_64.get_march_flag()
        'x86-64'
        >>> ArchitectureType.ARM64.get_march_flag()
        'armv8-a'
        """
        flags = {
            self.X86: "i686",
            self.X86_64: "x86-64",
            self.ARM: "armv7-a",
            self.ARM64: "armv8-a",
            self.PPC: "powerpc",
            self.PPC64: "powerpc64",
            self.RISCV: "rv32gc",
            self.RISCV64: "rv64gc",
        }
        return flags.get(self, "")
    
    def get_mtune_flag(self) -> str:
        """
        Get the -mtune flag value for GCC/Clang.
        
        Returns
        -------
        str
            Tuning flag string for -mtune.
        """
        tunes = {
            self.X86: "generic",
            self.X86_64: "generic",
            self.ARM: "generic-armv7-a",
            self.ARM64: "generic-armv8-a",
        }
        return tunes.get(self, "generic")
    
    def get_llvm_target_triple(self) -> str:
        """
        Get the LLVM/Clang target triple for this architecture.
        
        Returns
        -------
        str
            LLVM target triple string.
        
        Examples
        --------
        >>> ArchitectureType.X86_64.get_llvm_target_triple()
        'x86_64-unknown-linux-gnu'
        """
        base = self.value
        system = platform.system().lower()
        
        if system == "windows":
            return f"{base}-pc-windows-msvc"
        elif system == "darwin":
            return f"{base}-apple-darwin"
        else:
            # Detect libc
            libc = "gnu"
            try:
                import ctypes
                libc = "gnu"  # Default
            except Exception:
                pass
            return f"{base}-unknown-{system}-{libc}"



# ============================================================================
# Python Implementation Enumeration
# ============================================================================

class PythonImplementation(Enum):
    """
    Python implementation enumeration.
    
    Attributes
    ----------
    CPYTHON : str
        Standard CPython implementation (value: "cpython").
    PYPY : str
        PyPy JIT-compiled implementation (value: "pypy").
    JYTHON : str
        Jython (Python on JVM) implementation (value: "jython").
    IRONPYTHON : str
        IronPython (.NET) implementation (value: "ironpython").
    MICROPYTHON : str
        MicroPython (embedded) implementation (value: "micropython").
    CIRCUITPYTHON : str
        CircuitPython (Adafruit) implementation (value: "circuitpython").
    GRAALPYTHON : str
        GraalPython (GraalVM) implementation (value: "graalpython").
    RUSTPYTHON : str
        RustPython implementation (value: "rustpython").
    UNKNOWN : str
        Unknown implementation (value: "unknown").
    """
    
    CPYTHON = "cpython"
    PYPY = "pypy"
    JYTHON = "jython"
    IRONPYTHON = "ironpython"
    MICROPYTHON = "micropython"
    CIRCUITPYTHON = "circuitpython"
    GRAALPYTHON = "graalpython"
    RUSTPYTHON = "rustpython"
    UNKNOWN = "unknown"
    
    def get_abi_tag(self) -> str:
        """
        Get the ABI tag prefix for this implementation.
        
        Returns
        -------
        str
            ABI tag prefix (e.g., 'cp' for CPython, 'pp' for PyPy).
        """
        tags = {
            self.CPYTHON: "cp",
            self.PYPY: "pp",
            self.JYTHON: "jy",
            self.IRONPYTHON: "ip",
            self.MICROPYTHON: "mp",
        }
        return tags.get(self, "py")
    
    def supports_c_extensions(self) -> bool:
        """
        Check if this implementation supports C extensions.
        
        Returns
        -------
        bool
            True if C extensions are supported.
        """
        return self in (self.CPYTHON, self.PYPY)


# ============================================================================
# Platform Information Data Class
# ============================================================================

@dataclass
class PlatformInfo:
    """
    Comprehensive platform information container.
    
    This dataclass holds all detected information about the current
    platform, including operating system, architecture, Python environment,
    and various system details. It is the primary return type for
    platform detection functions.
    
    Attributes
    ----------
    system : str
        Raw system identifier from sys.platform (e.g., 'linux', 'win32').
    platform_type : PlatformType
        Normalized platform type enumeration.
    architecture : ArchitectureType
        Normalized CPU architecture enumeration.
    python_implementation : PythonImplementation
        Python implementation type.
    machine : str
        Machine type from platform.machine() (e.g., 'x86_64').
    processor : str
        Processor name from platform.processor().
    release : str
        System release from platform.release().
    version : str
        System version from platform.version().
    python_version : str
        Python version string (e.g., '3.10.12').
    python_version_tuple : Tuple[int, int, int]
        Python version as (major, minor, micro) tuple.
    python_abi : str
        Python ABI tag (e.g., 'cp310' for CPython 3.10).
    bits : int
        Word size in bits (32 or 64).
    is_64bit : bool
        True if 64-bit system.
    is_windows : bool
        True if Windows.
    is_linux : bool
        True if Linux.
    is_macos : bool
        True if macOS.
    is_bsd : bool
        True if BSD.
    is_wsl : bool
        True if running under WSL.
    is_cygwin : bool
        True if running under Cygwin.
    is_msys : bool
        True if running under MSYS/MSYS2.
    is_android : bool
        True if Android.
    is_ios : bool
        True if iOS.
    libc_version : Optional[str]
        GNU libc version if available.
    kernel_version : Optional[str]
        Kernel version string.
    distribution : Optional[str]
        Linux distribution name if available.
    distribution_version : Optional[str]
        Linux distribution version if available.
    distribution_id : Optional[str]
        Linux distribution ID (like os-release ID).
    hostname : str
        System hostname.
    username : str
        Current username.
    home_directory : Path
        User home directory path.
    temp_directory : Path
        System temporary directory path.
    cache_directory : Path
        User cache directory path.
    config_directory : Path
        User config directory path.
    data_directory : Path
        User data directory path.
    cpu_count : int
        Number of logical CPU cores.
    cpu_count_physical : int
        Number of physical CPU cores.
    total_memory_bytes : int
        Total system memory in bytes.
    available_memory_bytes : int
        Available system memory in bytes.
    
    Examples
    --------
    >>> info = get_platform_info()
    >>> print(f"Platform: {info.platform_type.value}")
    >>> print(f"Architecture: {info.architecture.value}")
    >>> print(f"Python: {info.python_version} ({info.python_abi})")
    >>> print(f"CPU cores: {info.cpu_count}")
    >>> print(f"Memory: {info.total_memory_bytes / (1024**3):.1f} GB")
    >>> 
    >>> # Use for cache key generation
    >>> cache_key = f"build_{info.get_cache_key_suffix()}"
    >>> print(cache_key)  # 'build_linux_x86_64_cp310'
    """
    
    # Core platform info
    system: str
    platform_type: PlatformType
    architecture: ArchitectureType
    python_implementation: PythonImplementation
    
    # Hardware info
    machine: str
    processor: str
    
    # OS version info
    release: str
    version: str
    
    # Python version info
    python_version: str
    python_version_tuple: Tuple[int, int, int]
    python_abi: str
    
    # Bitness
    bits: int
    is_64bit: bool
    
    # Boolean flags
    is_windows: bool
    is_linux: bool
    is_macos: bool
    is_bsd: bool
    is_wsl: bool = False
    is_cygwin: bool = False
    is_msys: bool = False
    is_android: bool = False
    is_ios: bool = False
    
    # Library versions
    libc_version: Optional[str] = None
    kernel_version: Optional[str] = None
    
    # Distribution info
    distribution: Optional[str] = None
    distribution_version: Optional[str] = None
    distribution_id: Optional[str] = None
    
    # User/environment info
    hostname: str = ""
    username: str = ""
    home_directory: Path = field(default_factory=Path.cwd)
    temp_directory: Path = field(default_factory=lambda: Path("/tmp"))
    cache_directory: Path = field(default_factory=lambda: Path("/tmp"))
    config_directory: Path = field(default_factory=lambda: Path("/tmp"))
    data_directory: Path = field(default_factory=lambda: Path("/tmp"))
    
    # System resources
    cpu_count: int = 1
    cpu_count_physical: int = 1
    total_memory_bytes: int = 0
    available_memory_bytes: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert platform info to a serializable dictionary.
        
        This method produces a JSON-compatible dictionary containing
        all platform information, suitable for serialization, logging,
        or cache key generation.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of platform information.
        
        Examples
        --------
        >>> info = get_platform_info()
        >>> data = info.to_dict()
        >>> import json
        >>> print(json.dumps(data, indent=2, default=str))
        """
        return {
            # Core
            "system": self.system,
            "platform_type": self.platform_type.value,
            "architecture": self.architecture.value,
            "python_implementation": self.python_implementation.value,
            
            # Hardware
            "machine": self.machine,
            "processor": self.processor,
            
            # OS version
            "release": self.release,
            "version": self.version,
            
            # Python version
            "python_version": self.python_version,
            "python_version_tuple": list(self.python_version_tuple),
            "python_abi": self.python_abi,
            
            # Bitness
            "bits": self.bits,
            "is_64bit": self.is_64bit,
            
            # Flags
            "is_windows": self.is_windows,
            "is_linux": self.is_linux,
            "is_macos": self.is_macos,
            "is_bsd": self.is_bsd,
            "is_wsl": self.is_wsl,
            "is_cygwin": self.is_cygwin,
            "is_msys": self.is_msys,
            "is_android": self.is_android,
            "is_ios": self.is_ios,
            
            # Libraries
            "libc_version": self.libc_version,
            "kernel_version": self.kernel_version,
            
            # Distribution
            "distribution": self.distribution,
            "distribution_version": self.distribution_version,
            "distribution_id": self.distribution_id,
            
            # User/Environment
            "hostname": self.hostname,
            "username": self.username,
            "home_directory": str(self.home_directory),
            "temp_directory": str(self.temp_directory),
            "cache_directory": str(self.cache_directory),
            "config_directory": str(self.config_directory),
            "data_directory": str(self.data_directory),
            
            # Resources
            "cpu_count": self.cpu_count,
            "cpu_count_physical": self.cpu_count_physical,
            "total_memory_bytes": self.total_memory_bytes,
            "total_memory_gb": round(self.total_memory_bytes / (1024**3), 2),
            "available_memory_bytes": self.available_memory_bytes,
            "available_memory_gb": round(self.available_memory_bytes / (1024**3), 2),
        }
    
    def get_cache_key_suffix(self) -> str:
        """
        Generate a cache key suffix based on platform characteristics.
        
        This method creates a unique string that identifies the platform
        and environment, suitable for use as a cache key suffix to
        separate binaries built for different platforms.
        
        Returns
        -------
        str
            Cache key suffix (e.g., 'linux_x86_64_cp310').
        
        Examples
        --------
        >>> info = get_platform_info()
        >>> suffix = info.get_cache_key_suffix()
        >>> print(f"Cache key: build_{suffix}")
        'build_linux_x86_64_cp310'
        """
        parts = [
            self.platform_type.value,
            self.architecture.value,
            self.python_abi,
        ]
        return "_".join(parts)
    
    def get_full_cache_key(self, prefix: str = "") -> str:
        """
        Generate a full cache key with optional prefix.
        
        Parameters
        ----------
        prefix : str
            Optional prefix for the cache key.
            
        Returns
        -------
        str
            Full cache key string.
        
        Examples
        --------
        >>> info = get_platform_info()
        >>> key = info.get_full_cache_key("myapp")
        >>> print(key)
        'myapp_linux_x86_64_cp310'
        """
        suffix = self.get_cache_key_suffix()
        if prefix:
            return f"{prefix}_{suffix}"
        return suffix
    
    def get_compiler_target_triple(self, compiler: str = "gcc") -> str:
        """
        Get the target triple for compiler cross-compilation.
        
        Parameters
        ----------
        compiler : str
            Compiler name ('gcc', 'clang', 'msvc').
            
        Returns
        -------
        str
            Target triple string for the compiler.
        """
        if compiler == "msvc":
            return f"{self.architecture.value}-pc-windows-msvc"
        
        vendor = "pc" if self.is_windows else "unknown"
        system = self.system
        if system == "win32":
            system = "windows"
        elif system == "darwin":
            system = "darwin"
        
        abi = "gnu"
        if self.is_android:
            abi = "android"
        elif self.is_macos:
            abi = ""
        
        parts = [self.architecture.value, vendor, system]
        if abi:
            parts.append(abi)
        
        return "-".join(parts)
    
    def is_compatible_with(self, other: "PlatformInfo") -> bool:
        """
        Check if this platform is binary-compatible with another.
        
        Parameters
        ----------
        other : PlatformInfo
            Another platform info to compare.
            
        Returns
        -------
        bool
            True if binaries should be compatible.
        """
        # Must be same platform type
        if self.platform_type != other.platform_type:
            return False
        
        # Must be same architecture family
        if self.architecture != other.architecture:
            return False
        
        # Must be same Python ABI
        if self.python_abi != other.python_abi:
            return False
        
        # Must be same bitness
        if self.bits != other.bits:
            return False
        
        return True
    
    def get_system_info_string(self) -> str:
        """
        Get a human-readable system information string.
        
        Returns
        -------
        str
            Formatted system information.
        
        Examples
        --------
        >>> info = get_platform_info()
        >>> print(info.get_system_info_string())
        Linux x86_64 (Ubuntu 22.04) - Python 3.10.12 (cp310)
        """
        parts = [f"{self.platform_type.value} {self.architecture.value}"]
        
        if self.distribution:
            distro = f"{self.distribution}"
            if self.distribution_version:
                distro += f" {self.distribution_version}"
            parts.append(f"({distro})")
        
        parts.append(f"- Python {self.python_version} ({self.python_implementation.value})")
        
        return " ".join(parts)
    
    def __str__(self) -> str:
        """String representation of platform info."""
        return self.get_system_info_string()
    
    def __repr__(self) -> str:
        """Detailed representation of platform info."""
        return (f"PlatformInfo(platform={self.platform_type.value}, "
                f"arch={self.architecture.value}, "
                f"python={self.python_version}, "
                f"bits={self.bits})")


# ============================================================================
# Cache Management
# ============================================================================

# Global cache for platform information
_platform_info_cache: Optional[PlatformInfo] = None


def clear_platform_cache() -> None:
    """
    Clear the cached platform information.
    
    This forces the next call to get_platform_info() to re-detect
    all platform information. Useful when the environment changes
    or for testing.
    
    Examples
    --------
    >>> clear_platform_cache()
    >>> info = get_platform_info()  # Fresh detection
    """
    global _platform_info_cache
    _platform_info_cache = None


# ============================================================================
# Platform Detection Functions (Internal)
# ============================================================================

def _detect_platform_type() -> PlatformType:
    """
    Detect the current platform type.
    
    This internal function analyzes sys.platform and other environment
    variables to determine the exact platform type.
    
    Returns
    -------
    PlatformType
        Detected platform type.
    """
    system = sys.platform
    
    # Check environment variables for WSL
    if system == "linux":
        # Check for WSL
        if "WSL_DISTRO_NAME" in os.environ:
            return PlatformType.WSL
        if "WSL_INTEROP" in os.environ:
            return PlatformType.WSL
        # Check /proc/version for Microsoft
        try:
            with open("/proc/version", "r") as f:
                content = f.read().lower()
                if "microsoft" in content or "wsl" in content:
                    return PlatformType.WSL
        except (IOError, OSError):
            pass
    
    # Map sys.platform to PlatformType
    platform_map = {
        "win32": PlatformType.WINDOWS,
        "darwin": PlatformType.MACOS,
        "linux": PlatformType.LINUX,
        "cygwin": PlatformType.CYGWIN,
        "msys": PlatformType.MSYS,
        "emscripten": PlatformType.EMSCRIPTEN,
    }
    
    if system in platform_map:
        platform_type = platform_map[system]
        
        # Additional checks for Linux
        if platform_type == PlatformType.LINUX:
            # Check for Android
            if hasattr(sys, "getandroidapilevel"):
                return PlatformType.ANDROID
            # Check Android paths
            if os.path.exists("/system/build.prop"):
                return PlatformType.ANDROID
        
        # Check for iOS (Pythonista or similar)
        if platform_type == PlatformType.MACOS:
            if os.path.exists("/System/Library/CoreServices/SystemVersion.plist"):
                # Could be macOS, but check for iOS simulator
                pass
        
        return platform_type
    
    # Check for BSD variants
    if system.startswith(("freebsd", "openbsd", "netbsd", "dragonfly")):
        return PlatformType.BSD
    
    # Check for SunOS/Solaris
    if system.startswith("sunos"):
        return PlatformType.SUNOS
    
    # Check for AIX
    if system.startswith("aix"):
        return PlatformType.AIX
    
    return PlatformType.UNKNOWN


def _detect_architecture() -> ArchitectureType:
    """
    Detect the CPU architecture.
    
    This internal function analyzes platform.machine() and system
    information to determine the exact CPU architecture.
    
    Returns
    -------
    ArchitectureType
        Detected architecture type.
    """
    machine = platform.machine().lower()
    
    # Normalize machine names
    machine_map = {
        # x86
        "x86_64": ArchitectureType.X86_64,
        "amd64": ArchitectureType.X86_64,
        "x64": ArchitectureType.X86_64,
        "i386": ArchitectureType.X86,
        "i486": ArchitectureType.X86,
        "i586": ArchitectureType.X86,
        "i686": ArchitectureType.X86,
        "x86": ArchitectureType.X86,
        
        # ARM
        "arm64": ArchitectureType.ARM64,
        "aarch64": ArchitectureType.ARM64,
        "armv7l": ArchitectureType.ARM,
        "armv6l": ArchitectureType.ARM,
        "armv5tel": ArchitectureType.ARM,
        "arm": ArchitectureType.ARM,
        
        # PowerPC
        "ppc64le": ArchitectureType.PPC64,
        "ppc64": ArchitectureType.PPC64,
        "ppc": ArchitectureType.PPC,
        
        # S390X
        "s390x": ArchitectureType.S390X,
        
        # MIPS
        "mips64": ArchitectureType.MIPS64,
        "mips": ArchitectureType.MIPS,
        
        # RISC-V
        "riscv64": ArchitectureType.RISCV64,
        "riscv": ArchitectureType.RISCV,
        
        # SPARC
        "sparc64": ArchitectureType.SPARC64,
        "sparc": ArchitectureType.SPARC,
        
        # WebAssembly
        "wasm32": ArchitectureType.WASM,
        "wasm64": ArchitectureType.WASM,
    }
    
    if machine in machine_map:
        return machine_map[machine]
    
    # Check for ARM variants
    if machine.startswith("armv"):
        if "64" in machine:
            return ArchitectureType.ARM64
        return ArchitectureType.ARM
    
    if machine.startswith("aarch64"):
        return ArchitectureType.ARM64
    
    return ArchitectureType.UNKNOWN


def _detect_python_implementation() -> PythonImplementation:
    """
    Detect the Python implementation.
    
    Returns
    -------
    PythonImplementation
        Detected Python implementation.
    """
    impl = platform.python_implementation().lower()
    
    impl_map = {
        "cpython": PythonImplementation.CPYTHON,
        "pypy": PythonImplementation.PYPY,
        "jython": PythonImplementation.JYTHON,
        "ironpython": PythonImplementation.IRONPYTHON,
        "micropython": PythonImplementation.MICROPYTHON,
        "circuitpython": PythonImplementation.CIRCUITPYTHON,
        "graalpython": PythonImplementation.GRAALPYTHON,
        "rustpython": PythonImplementation.RUSTPYTHON,
    }
    
    return impl_map.get(impl, PythonImplementation.UNKNOWN)


def _get_python_abi(impl: PythonImplementation) -> str:
    """
    Generate Python ABI tag.
    
    Parameters
    ----------
    impl : PythonImplementation
        Python implementation.
        
    Returns
    -------
    str
        ABI tag (e.g., 'cp310').
    """
    prefix = impl.get_abi_tag()
    return f"{prefix}{sys.version_info.major}{sys.version_info.minor}"


def _detect_libc_version() -> Optional[str]:
    """
    Detect GNU libc version on Linux.
    
    Returns
    -------
    Optional[str]
        libc version string or None if not available.
    """
    if not sys.platform.startswith("linux"):
        return None
    
    # Try using ctypes to call gnu_get_libc_version
    try:
        import ctypes
        import ctypes.util
        
        libc_path = ctypes.util.find_library("c")
        if libc_path:
            libc = ctypes.CDLL(libc_path)
            if hasattr(libc, "gnu_get_libc_version"):
                libc.gnu_get_libc_version.restype = ctypes.c_char_p
                version = libc.gnu_get_libc_version()
                if version:
                    return version.decode("utf-8")
    except Exception:
        pass
    
    # Try parsing from libc.so.6
    try:
        result = subprocess.run(
            ["/lib/libc.so.6"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout + result.stderr
        
        # Parse version from output
        match = re.search(r"GNU C Library.*?(\d+\.\d+)", output)
        if match:
            return match.group(1)
    except Exception:
        pass
    
    return None


def _detect_distribution() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Detect Linux distribution information.
    
    Returns
    -------
    Tuple[Optional[str], Optional[str], Optional[str]]
        Tuple of (distribution_name, distribution_version, distribution_id).
    """
    if not sys.platform.startswith("linux"):
        return None, None, None
    
    # Try /etc/os-release first (modern standard)
    try:
        with open("/etc/os-release", "r") as f:
            content = f.read()
        
        distro = None
        version = None
        distro_id = None
        
        for line in content.split("\n"):
            if line.startswith("NAME="):
                distro = line.split("=", 1)[1].strip('"')
            elif line.startswith("VERSION_ID="):
                version = line.split("=", 1)[1].strip('"')
            elif line.startswith("ID="):
                distro_id = line.split("=", 1)[1].strip('"')
        
        if distro or version or distro_id:
            return distro, version, distro_id
    except (IOError, OSError):
        pass
    
    # Try lsb_release
    try:
        result = subprocess.run(
            ["lsb_release", "-si"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            distro = result.stdout.strip()
            
            result = subprocess.run(
                ["lsb_release", "-sr"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = result.stdout.strip() if result.returncode == 0 else None
            
            return distro, version, distro.lower() if distro else None
    except Exception:
        pass
    
    # Try distribution-specific files
    release_files = [
        "/etc/redhat-release",
        "/etc/SuSE-release",
        "/etc/debian_version",
        "/etc/gentoo-release",
        "/etc/arch-release",
        "/etc/alpine-release",
    ]
    
    for rel_file in release_files:
        try:
            with open(rel_file, "r") as f:
                content = f.read().strip()
                if "release" in rel_file:
                    # Parse RedHat-style
                    match = re.match(r"(.+?)\s+release\s+(\d+(?:\.\d+)*)", content)
                    if match:
                        return match.group(1), match.group(2), match.group(1).lower()
                elif "debian_version" in rel_file:
                    return "Debian", content, "debian"
                elif "arch-release" in rel_file:
                    return "Arch Linux", None, "arch"
                elif "alpine-release" in rel_file:
                    return "Alpine Linux", content, "alpine"
        except (IOError, OSError):
            continue
    
    return None, None, None


def _get_cpu_count() -> Tuple[int, int]:
    """
    Get logical and physical CPU core counts.
    
    Returns
    -------
    Tuple[int, int]
        Tuple of (logical_cores, physical_cores).
    """
    logical = 1
    physical = 1
    
    try:
        logical = os.cpu_count() or 1
    except Exception:
        pass
    
    # Try to get physical cores
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/cpuinfo", "r") as f:
                content = f.read()
            
            # Count unique physical IDs
            physical_ids = set()
            for line in content.split("\n"):
                if line.startswith("physical id"):
                    physical_ids.add(line.split(":")[1].strip())
            
            if physical_ids:
                # Count cores per physical ID
                core_ids = set()
                for line in content.split("\n"):
                    if line.startswith("core id"):
                        core_ids.add(line.split(":")[1].strip())
                
                physical = len(physical_ids) * len(core_ids) if core_ids else len(physical_ids)
        except Exception:
            physical = logical
    elif sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"],
                capture_output=True,
                text=True,
            )
            physical = int(result.stdout.strip())
        except Exception:
            physical = logical
    elif sys.platform == "win32":
        try:
            import ctypes
            # This would require more complex WMI calls
            physical = logical
        except Exception:
            physical = logical
    
    return max(1, logical), max(1, physical)


def _get_memory_info() -> Tuple[int, int]:
    """
    Get total and available system memory.
    
    Returns
    -------
    Tuple[int, int]
        Tuple of (total_bytes, available_bytes).
    """
    total = 0
    available = 0
    
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo", "r") as f:
                content = f.read()
            
            for line in content.split("\n"):
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024  # kB to bytes
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1]) * 1024
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
            )
            total = int(result.stdout.strip())
            available = total  # Approximate
        except Exception:
            pass
    elif sys.platform == "win32":
        try:
            import ctypes
            
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            
            mem_status = MEMORYSTATUSEX()
            mem_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status))
            
            total = mem_status.ullTotalPhys
            available = mem_status.ullAvailPhys
        except Exception:
            pass
    
    return total, available


def _get_user_directories() -> Tuple[Path, Path, Path, Path, Path]:
    """
    Get user directories (home, temp, cache, config, data).
    
    Returns
    -------
    Tuple[Path, Path, Path, Path, Path]
        Tuple of (home, temp, cache, config, data) directories.
    """
    home = Path.home()
    
    # Temp directory
    if sys.platform == "win32":
        temp = Path(os.environ.get("TEMP", os.environ.get("TMP", "C:\\Temp")))
    else:
        temp = Path("/tmp")
    
    # Cache directory
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        cache = Path(local_appdata) / "cimporter" / "cache"
    elif sys.platform == "darwin":
        cache = home / "Library" / "Caches" / "cimporter"
    else:
        xdg_cache = os.environ.get("XDG_CACHE_HOME", str(home / ".cache"))
        cache = Path(xdg_cache) / "cimporter"
    
    # Config directory
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
        config = Path(appdata) / "cimporter"
    elif sys.platform == "darwin":
        config = home / "Library" / "Application Support" / "cimporter"
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
        config = Path(xdg_config) / "cimporter"
    
    # Data directory
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        data = Path(local_appdata) / "cimporter" / "data"
    elif sys.platform == "darwin":
        data = home / "Library" / "Application Support" / "cimporter" / "data"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share"))
        data = Path(xdg_data) / "cimporter"
    
    return home, temp, cache, config, data


def _get_hostname() -> str:
    """Get system hostname."""
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _get_username() -> str:
    """Get current username."""
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))


# ============================================================================
# Public API Functions
# ============================================================================

def get_platform_info(refresh: bool = False) -> PlatformInfo:
    """
    Get comprehensive platform information.
    
    This function detects and returns detailed information about the
    current platform, including OS type, architecture, Python version,
    system resources, and environment details. Results are cached
    for performance unless refresh=True.
    
    Parameters
    ----------
    refresh : bool
        If True, refresh cached information and re-detect all platform
        details. Use this if the environment has changed or for testing.
        
    Returns
    -------
    PlatformInfo
        Comprehensive platform information object containing all detected
        system and environment details.
        
    Examples
    --------
    >>> info = get_platform_info()
    >>> print(f"Platform: {info.platform_type.value}")
    >>> print(f"Architecture: {info.architecture.value}")
    >>> print(f"Python: {info.python_version} ({info.python_implementation.value})")
    >>> print(f"CPU cores: {info.cpu_count} logical, {info.cpu_count_physical} physical")
    >>> print(f"Memory: {info.total_memory_bytes / (1024**3):.1f} GB total")
    >>> 
    >>> # Check specific flags
    >>> if info.is_wsl:
    ...     print("Running under WSL")
    >>> if info.architecture.is_arm():
    ...     print("ARM-based system detected")
    >>> 
    >>> # Generate cache key
    >>> cache_key = info.get_cache_key_suffix()
    >>> print(f"Cache key suffix: {cache_key}")
    """
    global _platform_info_cache
    
    if _platform_info_cache is not None and not refresh:
        return _platform_info_cache
    
    # Detect platform type
    platform_type = _detect_platform_type()
    
    # Detect architecture
    architecture = _detect_architecture()
    
    # Detect Python implementation
    python_impl = _detect_python_implementation()
    
    # Detect libc version (Linux only)
    libc_version = _detect_libc_version() if platform_type.is_linux_family() else None
    
    # Detect distribution (Linux only)
    distro, distro_version, distro_id = _detect_distribution() if platform_type == PlatformType.LINUX else (None, None, None)
    
    # Get CPU info
    cpu_count, cpu_physical = _get_cpu_count()
    
    # Get memory info
    total_memory, available_memory = _get_memory_info()
    
    # Get user directories
    home, temp, cache, config, data = _get_user_directories()
    
    # Determine bits
    bits = 64 if sys.maxsize > 2**32 else 32
    
    # Get version info
    py_version = platform.python_version()
    py_version_tuple = sys.version_info[:3]
    python_abi = _get_python_abi(python_impl)
    
    info = PlatformInfo(
        # Core
        system=sys.platform,
        platform_type=platform_type,
        architecture=architecture,
        python_implementation=python_impl,
        
        # Hardware
        machine=platform.machine(),
        processor=platform.processor() or "unknown",
        
        # OS version
        release=platform.release() or "unknown",
        version=platform.version() or "unknown",
        
        # Python version
        python_version=py_version,
        python_version_tuple=py_version_tuple,
        python_abi=python_abi,
        
        # Bitness
        bits=bits,
        is_64bit=(bits == 64),
        
        # Boolean flags
        is_windows=(platform_type == PlatformType.WINDOWS),
        is_linux=(platform_type == PlatformType.LINUX),
        is_macos=(platform_type == PlatformType.MACOS),
        is_bsd=(platform_type == PlatformType.BSD),
        is_wsl=(platform_type == PlatformType.WSL),
        is_cygwin=(platform_type == PlatformType.CYGWIN),
        is_msys=(platform_type == PlatformType.MSYS),
        is_android=(platform_type == PlatformType.ANDROID),
        is_ios=(platform_type == PlatformType.IOS),
        
        # Libraries
        libc_version=libc_version,
        kernel_version=platform.release(),
        
        # Distribution
        distribution=distro,
        distribution_version=distro_version,
        distribution_id=distro_id,
        
        # User/Environment
        hostname=_get_hostname(),
        username=_get_username(),
        home_directory=home,
        temp_directory=temp,
        cache_directory=cache,
        config_directory=config,
        data_directory=data,
        
        # Resources
        cpu_count=cpu_count,
        cpu_count_physical=cpu_physical,
        total_memory_bytes=total_memory,
        available_memory_bytes=available_memory,
    )
    
    _platform_info_cache = info
    return info


def get_platform() -> PlatformType:
    """
    Get the current platform type.
    
    This is a convenience function that returns just the platform type
    without all the detailed information.
    
    Returns
    -------
    PlatformType
        Platform type enumeration value.
        
    Examples
    --------
    >>> platform_type = get_platform()
    >>> if platform_type == PlatformType.WINDOWS:
    ...     print("Running on Windows")
    >>> elif platform_type.is_unix():
    ...     print("Running on Unix-like system")
    >>> 
    >>> # Use platform-specific extensions
    >>> ext = platform_type.get_shared_library_extension()
    >>> print(f"Shared libraries use '{ext}'")
    """
    return get_platform_info().platform_type


def get_architecture() -> ArchitectureType:
    """
    Get the current CPU architecture.
    
    Returns
    -------
    ArchitectureType
        Architecture type enumeration value.
        
    Examples
    --------
    >>> arch = get_architecture()
    >>> if arch.is_64bit():
    ...     print("64-bit architecture")
    >>> if arch.is_arm():
    ...     print("ARM-based processor")
    >>> print(f"Compiler -march flag: {arch.get_march_flag()}")
    """
    return get_platform_info().architecture


def get_system() -> str:
    """
    Get the raw system identifier string.
    
    This returns the value of sys.platform, which is the most direct
    platform identifier from Python.
    
    Returns
    -------
    str
        System identifier (e.g., 'linux', 'win32', 'darwin').
        
    Examples
    --------
    >>> system = get_system()
    >>> print(f"sys.platform = {system}")
    """
    return sys.platform


def get_machine() -> str:
    """
    Get the machine type string.
    
    This returns the value of platform.machine(), which identifies
    the CPU architecture in platform-specific format.
    
    Returns
    -------
    str
        Machine type (e.g., 'x86_64', 'arm64', 'AMD64').
        
    Examples
    --------
    >>> machine = get_machine()
    >>> print(f"Machine: {machine}")
    """
    return platform.machine()


def get_processor() -> str:
    """
    Get the processor name string.
    
    This returns the value of platform.processor(), which may contain
    the CPU model name on some platforms.
    
    Returns
    -------
    str
        Processor name or 'unknown' if not available.
        
    Examples
    --------
    >>> processor = get_processor()
    >>> print(f"Processor: {processor}")
    """
    return platform.processor() or "unknown"


def get_python_version() -> str:
    """
    Get the Python version string.
    
    Returns
    -------
    str
        Python version (e.g., '3.10.12').
        
    Examples
    --------
    >>> version = get_python_version()
    >>> print(f"Python {version}")
    """
    return platform.python_version()


def get_python_version_tuple() -> Tuple[int, int, int]:
    """
    Get the Python version as a tuple.
    
    Returns
    -------
    Tuple[int, int, int]
        Python version as (major, minor, micro) tuple.
        
    Examples
    --------
    >>> major, minor, micro = get_python_version_tuple()
    >>> print(f"Python {major}.{minor}.{micro}")
    """
    return sys.version_info[:3]


def get_python_implementation() -> str:
    """
    Get the Python implementation name.
    
    Returns
    -------
    str
        Implementation name (e.g., 'CPython', 'PyPy').
        
    Examples
    --------
    >>> impl = get_python_implementation()
    >>> print(f"Implementation: {impl}")
    """
    return platform.python_implementation()


def get_python_abi() -> str:
    """
    Get the Python ABI tag.
    
    The ABI tag identifies the Python implementation and version
    for binary compatibility. For example, 'cp310' for CPython 3.10.
    
    Returns
    -------
    str
        Python ABI tag.
        
    Examples
    --------
    >>> abi = get_python_abi()
    >>> print(f"Python ABI: {abi}")
    """
    return get_platform_info().python_abi


def get_shared_library_extension() -> str:
    """
    Get the shared library file extension for the current platform.
    
    Returns
    -------
    str
        Extension including the dot (e.g., '.so', '.dll', '.dylib').
        
    Examples
    --------
    >>> ext = get_shared_library_extension()
    >>> lib_path = f"libmylib{ext}"
    >>> print(lib_path)
    """
    return get_platform().get_shared_library_extension()


def get_executable_extension() -> str:
    """
    Get the executable file extension for the current platform.
    
    Returns
    -------
    str
        Extension including the dot (e.g., '.exe' for Windows, '' for Unix).
        
    Examples
    --------
    >>> ext = get_executable_extension()
    >>> exe_path = f"myprogram{ext}"
    >>> print(exe_path)
    """
    return get_platform().get_executable_extension()


def get_object_extension() -> str:
    """
    Get the object file extension for the current platform.
    
    Returns
    -------
    str
        Extension including the dot (e.g., '.o', '.obj').
        
    Examples
    --------
    >>> ext = get_object_extension()
    >>> obj_path = f"source{ext}"
    >>> print(obj_path)
    """
    return get_platform().get_object_extension()


def get_static_library_extension() -> str:
    """
    Get the static library extension for the current platform.
    
    Returns
    -------
    str
        Extension including the dot (e.g., '.a', '.lib').
        
    Examples
    --------
    >>> ext = get_static_library_extension()
    >>> lib_path = f"libmylib{ext}"
    >>> print(lib_path)
    """
    return get_platform().get_static_library_extension()


def get_python_extension_module_extension() -> str:
    """
    Get the Python C extension module extension for the current platform.
    
    Returns
    -------
    str
        Extension including the dot (e.g., '.pyd' for Windows, '.so' for Unix).
        
    Examples
    --------
    >>> ext = get_python_extension_module_extension()
    >>> module_path = f"mymodule{ext}"
    >>> print(module_path)
    """
    return get_platform().get_python_extension_module_extension()


def is_windows() -> bool:
    """
    Check if running on Windows.
    
    Returns
    -------
    bool
        True if running on Windows (including native Windows).
        
    Examples
    --------
    >>> if is_windows():
    ...     print("Using Windows-specific code")
    ...     separator = '\\\\'
    ... else:
    ...     separator = '/'
    """
    return get_platform_info().is_windows


def is_linux() -> bool:
    """
    Check if running on Linux.
    
    Returns
    -------
    bool
        True if running on native Linux.
        
    Examples
    --------
    >>> if is_linux():
    ...     print("Using Linux-specific code")
    """
    return get_platform_info().is_linux


def is_macos() -> bool:
    """
    Check if running on macOS.
    
    Returns
    -------
    bool
        True if running on macOS.
        
    Examples
    --------
    >>> if is_macos():
    ...     print("Using macOS-specific code")
    """
    return get_platform_info().is_macos


def is_bsd() -> bool:
    """
    Check if running on BSD.
    
    Returns
    -------
    bool
        True if running on FreeBSD, OpenBSD, NetBSD, etc.
    """
    return get_platform_info().is_bsd


def is_wsl() -> bool:
    """
    Check if running under Windows Subsystem for Linux.
    
    Returns
    -------
    bool
        True if running under WSL.
        
    Examples
    --------
    >>> if is_wsl():
    ...     print("Running under WSL - hybrid environment")
    """
    return get_platform_info().is_wsl


def is_cygwin() -> bool:
    """
    Check if running under Cygwin.
    
    Returns
    -------
    bool
        True if running under Cygwin environment.
    """
    return get_platform_info().is_cygwin


def is_msys() -> bool:
    """
    Check if running under MSYS/MSYS2.
    
    Returns
    -------
    bool
        True if running under MSYS environment (e.g., Git Bash).
    """
    return get_platform_info().is_msys


def is_android() -> bool:
    """
    Check if running on Android.
    
    Returns
    -------
    bool
        True if running on Android.
    """
    return get_platform_info().is_android


def is_ios() -> bool:
    """
    Check if running on iOS.
    
    Returns
    -------
    bool
        True if running on iOS.
    """
    return get_platform_info().is_ios


def is_unix() -> bool:
    """
    Check if running on a Unix-like system.
    
    This includes Linux, macOS, BSD, Solaris, AIX, Android, and iOS.
    
    Returns
    -------
    bool
        True if running on Unix-like system.
        
    Examples
    --------
    >>> if is_unix():
    ...     print("Using POSIX-compatible code")
    """
    return get_platform().is_unix()


def is_windows_family() -> bool:
    """
    Check if running on Windows or Windows-compatible environment.
    
    This includes native Windows, Cygwin, MSYS, and WSL.
    
    Returns
    -------
    bool
        True if Windows or Windows-compatible.
    """
    return get_platform().is_windows_family()


def is_64bit() -> bool:
    """
    Check if running on a 64-bit system.
    
    Returns
    -------
    bool
        True if 64-bit system.
        
    Examples
    --------
    >>> if is_64bit():
    ...     print("64-bit system - can use >4GB memory")
    """
    return get_platform_info().is_64bit


def is_32bit() -> bool:
    """
    Check if running on a 32-bit system.
    
    Returns
    -------
    bool
        True if 32-bit system.
    """
    return not is_64bit()


def is_arm() -> bool:
    """
    Check if running on ARM architecture.
    
    Returns
    -------
    bool
        True if ARM or ARM64 processor.
        
    Examples
    --------
    >>> if is_arm():
    ...     print("ARM-based system - use NEON SIMD")
    """
    return get_architecture().is_arm()


def is_x86() -> bool:
    """
    Check if running on x86 architecture.
    
    Returns
    -------
    bool
        True if x86 or x86_64 processor.
        
    Examples
    --------
    >>> if is_x86():
    ...     print("x86-based system - use SSE/AVX SIMD")
    """
    return get_architecture().is_x86()


def get_cpu_count() -> int:
    """
    Get the number of logical CPU cores.
    
    Returns
    -------
    int
        Number of logical CPU cores.
        
    Examples
    --------
    >>> cores = get_cpu_count()
    >>> print(f"Using {cores} parallel jobs")
    """
    return get_platform_info().cpu_count


def get_cpu_count_physical() -> int:
    """
    Get the number of physical CPU cores.
    
    Returns
    -------
    int
        Number of physical CPU cores.
        
    Examples
    --------
    >>> physical = get_cpu_count_physical()
    >>> print(f"{physical} physical cores available")
    """
    return get_platform_info().cpu_count_physical


def get_total_memory() -> int:
    """
    Get total system memory in bytes.
    
    Returns
    -------
    int
        Total memory in bytes.
        
    Examples
    --------
    >>> mem_bytes = get_total_memory()
    >>> mem_gb = mem_bytes / (1024**3)
    >>> print(f"Total memory: {mem_gb:.1f} GB")
    """
    return get_platform_info().total_memory_bytes


def get_available_memory() -> int:
    """
    Get available system memory in bytes.
    
    Returns
    -------
    int
        Available memory in bytes.
        
    Examples
    --------
    >>> avail_bytes = get_available_memory()
    >>> avail_gb = avail_bytes / (1024**3)
    >>> print(f"Available memory: {avail_gb:.1f} GB")
    """
    return get_platform_info().available_memory_bytes


def get_user_cache_dir() -> Path:
    """
    Get the user cache directory path.
    
    This follows platform conventions:
    - Windows: %LOCALAPPDATA%\\cimporter\\cache
    - macOS: ~/Library/Caches/cimporter
    - Linux: $XDG_CACHE_HOME/cimporter or ~/.cache/cimporter
    
    Returns
    -------
    Path
        User cache directory path.
        
    Examples
    --------
    >>> cache_dir = get_user_cache_dir()
    >>> cache_dir.mkdir(parents=True, exist_ok=True)
    >>> cache_file = cache_dir / "mycache.dat"
    """
    return get_platform_info().cache_directory


def get_user_config_dir() -> Path:
    """
    Get the user configuration directory path.
    
    This follows platform conventions:
    - Windows: %APPDATA%\\cimporter
    - macOS: ~/Library/Application Support/cimporter
    - Linux: $XDG_CONFIG_HOME/cimporter or ~/.config/cimporter
    
    Returns
    -------
    Path
        User config directory path.
        
    Examples
    --------
    >>> config_dir = get_user_config_dir()
    >>> config_file = config_dir / "settings.json"
    """
    return get_platform_info().config_directory


def get_user_data_dir() -> Path:
    """
    Get the user data directory path.
    
    This follows platform conventions:
    - Windows: %LOCALAPPDATA%\\cimporter\\data
    - macOS: ~/Library/Application Support/cimporter/data
    - Linux: $XDG_DATA_HOME/cimporter or ~/.local/share/cimporter
    
    Returns
    -------
    Path
        User data directory path.
        
    Examples
    --------
    >>> data_dir = get_user_data_dir()
    >>> data_dir.mkdir(parents=True, exist_ok=True)
    """
    return get_platform_info().data_directory


def get_temp_directory() -> Path:
    """
    Get the system temporary directory path.
    
    Returns
    -------
    Path
        Temporary directory path.
        
    Examples
    --------
    >>> temp_dir = get_temp_directory()
    >>> import tempfile
    >>> temp_file = temp_dir / f"myapp_{os.getpid()}.tmp"
    """
    return get_platform_info().temp_directory


# ============================================================================
# Python Include and Library Paths Detection
# ============================================================================

def get_python_include_paths() -> List[Path]:
    """
    Get Python C API include directories for compiling extensions.
    
    This function detects all include directories needed to compile
    Python C extensions. It searches multiple sources in order of
    reliability:
    
    1. sysconfig.get_path('include') - Most reliable
    2. sysconfig.get_path('platinclude') - Platform-specific includes
    3. distutils.sysconfig (if available)
    4. Common system locations as fallback
    
    Returns
    -------
    List[Path]
        List of include directory paths. Empty list if none found.
        
    Examples
    --------
    >>> includes = get_python_include_paths()
    >>> for inc in includes:
    ...     print(f"Python include: {inc}")
    >>> 
    >>> # Use with compiler
    >>> flags = [f"-I{inc}" for inc in includes]
    
    Notes
    -----
    The returned paths are guaranteed to exist. Non-existent paths
    are filtered out.
    """
    includes: List[Path] = []
    seen: Set[Path] = set()
    
    def add_path(path: Optional[Union[str, Path]]) -> None:
        """Add a path if it exists and hasn't been added."""
        if path:
            p = Path(path)
            if p.exists() and p not in seen:
                includes.append(p)
                seen.add(p)
    
    # Method 1: Use sysconfig (most reliable, Python 3.2+)
    try:
        import sysconfig
        
        # Standard include directory
        include_dir = sysconfig.get_path('include')
        add_path(include_dir)
        
        # Platform-specific include directory
        plat_include = sysconfig.get_path('platinclude')
        if plat_include != include_dir:
            add_path(plat_include)
        
        # Get INCLUDEPY from config vars
        include_py = sysconfig.get_config_var('INCLUDEPY')
        add_path(include_py)
        
        # Get CONFINCLUDEPY for pyconfig.h location
        conf_include = sysconfig.get_config_var('CONFINCLUDEPY')
        add_path(conf_include)
        
    except ImportError:
        pass
    except Exception:
        pass
    
    # Method 2: Try distutils (older Python versions)
    if not includes:
        try:
            from distutils import sysconfig as distutils_sysconfig
            
            include_dir = distutils_sysconfig.get_python_inc()
            add_path(include_dir)
            
            plat_include = distutils_sysconfig.get_python_inc(plat_specific=True)
            if plat_include != include_dir:
                add_path(plat_include)
                
        except ImportError:
            pass
        except Exception:
            pass
    
    # Method 3: Use sys.prefix and sys.exec_prefix
    if not includes:
        python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        version_abi = f"python{sys.version_info.major}{sys.version_info.minor}"
        
        # Common include paths
        common_paths = [
            Path(sys.prefix) / "include" / python_version,
            Path(sys.prefix) / "include" / version_abi,
            Path(sys.exec_prefix) / "include" / python_version,
            Path(sys.exec_prefix) / "include" / version_abi,
            Path(sys.prefix) / "include",
            Path(sys.exec_prefix) / "include",
        ]
        
        for path in common_paths:
            add_path(path)
    
    # Method 4: System locations (Linux/macOS)
    if not includes:
        python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        version_abi = f"python{sys.version_info.major}{sys.version_info.minor}"
        
        system_paths = [
            Path("/usr/include") / python_version,
            Path("/usr/local/include") / python_version,
            Path("/opt/homebrew/include") / python_version,
            Path("/usr/include") / version_abi,
            Path("/usr/local/include") / version_abi,
            Path("/opt/homebrew/include") / version_abi,
        ]
        
        for path in system_paths:
            add_path(path)
    
    # Method 5: Virtual environment detection
    if sys.prefix != sys.base_prefix:
        venv_include = Path(sys.prefix) / "include"
        add_path(venv_include)
        
        python_version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        venv_version_include = Path(sys.prefix) / "include" / python_version
        add_path(venv_version_include)
    
    # Method 6: Windows-specific registry lookup
    if is_windows() and not includes:
        windows_paths = _get_windows_python_include_paths()
        for path in windows_paths:
            add_path(path)
    
    # Method 7: Check environment variable
    env_include = os.environ.get('PYTHON_INCLUDE')
    if env_include:
        for path in env_include.split(os.pathsep):
            add_path(path.strip())
    
    return includes


def _get_windows_python_include_paths() -> List[Path]:
    """
    Get Python include paths from Windows registry.
    
    Returns
    -------
    List[Path]
        List of include paths found in registry.
    """
    paths: List[Path] = []
    
    try:
        import winreg
        
        # Try current user
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for key_path in (
                r"SOFTWARE\Python\PythonCore",
                r"SOFTWARE\Wow6432Node\Python\PythonCore",
            ):
                try:
                    with winreg.OpenKey(root, key_path) as key:
                        # Enumerate installed Python versions
                        index = 0
                        while True:
                            try:
                                version = winreg.EnumKey(key, index)
                                version_key_path = f"{key_path}\\{version}\\InstallPath"
                                
                                try:
                                    with winreg.OpenKey(root, version_key_path) as ver_key:
                                        install_path, _ = winreg.QueryValueEx(ver_key, "")
                                        if install_path:
                                            include_path = Path(install_path) / "include"
                                            if include_path.exists():
                                                paths.append(include_path)
                                except FileNotFoundError:
                                    pass
                                    
                                index += 1
                            except OSError:
                                break
                except FileNotFoundError:
                    continue
                    
    except ImportError:
        pass
    except Exception:
        pass
    
    # Also check common Windows installation paths
    common_windows_paths = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
        Path("C:\\Python"),
        Path("C:\\Program Files\\Python"),
        Path("C:\\Program Files (x86)\\Python"),
    ]
    
    python_version = f"Python{sys.version_info.major}{sys.version_info.minor}"
    
    for base in common_windows_paths:
        if base.exists():
            # Check version-specific directory
            version_path = base / python_version / "include"
            if version_path.exists():
                paths.append(version_path)
            
            # Check for any Python directory
            for py_dir in base.iterdir():
                if py_dir.is_dir() and py_dir.name.startswith("Python"):
                    include_dir = py_dir / "include"
                    if include_dir.exists():
                        paths.append(include_dir)
    
    return paths


def get_python_library_paths() -> List[Path]:
    """
    Get Python library directories for linking extensions.
    
    This function detects all library directories needed to link
    Python C extensions. It searches multiple sources including
    sysconfig, distutils, and common system locations.
    
    Returns
    -------
    List[Path]
        List of library directory paths. Empty list if none found.
        
    Examples
    --------
    >>> libs = get_python_library_paths()
    >>> for lib in libs:
    ...     print(f"Python library: {lib}")
    >>> 
    >>> # Use with compiler
    >>> flags = [f"-L{lib}" for lib in libs]
    
    Notes
    -----
    The returned paths are guaranteed to exist. Non-existent paths
    are filtered out.
    """
    libs: List[Path] = []
    seen: Set[Path] = set()
    
    def add_path(path: Optional[Union[str, Path]]) -> None:
        """Add a path if it exists and hasn't been added."""
        if path:
            p = Path(path)
            if p.exists() and p not in seen:
                libs.append(p)
                seen.add(p)
    
    # Method 1: Use sysconfig (most reliable)
    try:
        import sysconfig
        
        # Standard library directory
        stdlib_dir = sysconfig.get_path('stdlib')
        add_path(stdlib_dir)
        
        # Purelib directory
        purelib_dir = sysconfig.get_path('purelib')
        add_path(purelib_dir)
        
        # Get LIBDIR from config vars
        lib_dir = sysconfig.get_config_var('LIBDIR')
        add_path(lib_dir)
        
        # Get LIBPL from config vars (Python library directory)
        libpl = sysconfig.get_config_var('LIBPL')
        add_path(libpl)
        
        # Get LDLIBRARY directory
        ld_library = sysconfig.get_config_var('LDLIBRARY')
        if ld_library:
            ld_dir = sysconfig.get_config_var('LIBDIR') or sysconfig.get_config_var('LIBPL')
            if ld_dir:
                add_path(ld_dir)
                
    except ImportError:
        pass
    except Exception:
        pass
    
    # Method 2: Try distutils
    if not libs:
        try:
            from distutils import sysconfig as distutils_sysconfig
            
            lib_dir = distutils_sysconfig.get_config_var('LIBDIR')
            add_path(lib_dir)
            
            libpl = distutils_sysconfig.get_config_var('LIBPL')
            add_path(libpl)
            
        except ImportError:
            pass
        except Exception:
            pass
    
    # Method 3: Use sys.prefix and sys.exec_prefix
    if not libs:
        common_paths = [
            Path(sys.prefix) / "lib",
            Path(sys.exec_prefix) / "lib",
            Path(sys.prefix) / "libs",  # Windows
            Path(sys.exec_prefix) / "libs",  # Windows
            Path(sys.prefix) / "Library" / "lib",  # Conda
            Path(sys.exec_prefix) / "Library" / "lib",  # Conda
        ]
        
        for path in common_paths:
            add_path(path)
    
    # Method 4: System locations
    if not libs:
        system_paths = [
            Path("/usr/lib"),
            Path("/usr/local/lib"),
            Path("/opt/homebrew/lib"),
            Path("/usr/lib64"),
            Path("/usr/local/lib64"),
        ]
        
        for path in system_paths:
            # Check for Python library in this directory
            python_lib_patterns = [
                f"libpython{sys.version_info.major}.{sys.version_info.minor}.*",
                f"libpython{sys.version_info.major}{sys.version_info.minor}.*",
            ]
            
            for pattern in python_lib_patterns:
                if list(path.glob(pattern)):
                    add_path(path)
                    break
    
    # Method 5: Virtual environment detection
    if sys.prefix != sys.base_prefix:
        venv_lib = Path(sys.prefix) / "lib"
        add_path(venv_lib)
        
        venv_libs = Path(sys.prefix) / "libs"  # Windows
        add_path(venv_libs)
    
    # Method 6: Windows-specific registry lookup
    if is_windows() and not libs:
        windows_paths = _get_windows_python_library_paths()
        for path in windows_paths:
            add_path(path)
    
    # Method 7: Check environment variable
    env_lib = os.environ.get('PYTHON_LIBRARY')
    if env_lib:
        for path in env_lib.split(os.pathsep):
            add_path(path.strip())
    
    return libs


def _get_windows_python_library_paths() -> List[Path]:
    """
    Get Python library paths from Windows registry.
    
    Returns
    -------
    List[Path]
        List of library paths found in registry.
    """
    paths: List[Path] = []
    
    try:
        import winreg
        
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for key_path in (
                r"SOFTWARE\Python\PythonCore",
                r"SOFTWARE\Wow6432Node\Python\PythonCore",
            ):
                try:
                    with winreg.OpenKey(root, key_path) as key:
                        index = 0
                        while True:
                            try:
                                version = winreg.EnumKey(key, index)
                                version_key_path = f"{key_path}\\{version}\\InstallPath"
                                
                                try:
                                    with winreg.OpenKey(root, version_key_path) as ver_key:
                                        install_path, _ = winreg.QueryValueEx(ver_key, "")
                                        if install_path:
                                            libs_path = Path(install_path) / "libs"
                                            if libs_path.exists():
                                                paths.append(libs_path)
                                except FileNotFoundError:
                                    pass
                                    
                                index += 1
                            except OSError:
                                break
                except FileNotFoundError:
                    continue
                    
    except ImportError:
        pass
    except Exception:
        pass
    
    return paths


def get_python_library_name() -> str:
    """
    Get the name of the Python library for linking.
    
    This function returns the appropriate library name for the current
    Python installation, which varies by platform and Python version.
    
    Returns
    -------
    str
        Python library name (without 'lib' prefix or extension).
        
    Examples
    --------
    >>> lib_name = get_python_library_name()
    >>> print(f"Python library: {lib_name}")
    >>> 
    >>> # Use with compiler
    >>> # Linux: -lpython3.10
    >>> # Windows: python310.lib
    >>> # macOS: -lpython3.10
    
    Notes
    -----
    - On Windows, returns the full name with .lib extension
    - On Unix, returns the name without 'lib' prefix for -l flag
    """
    # Try to get from sysconfig first
    try:
        import sysconfig
        
        # Get LDLIBRARY or LIBRARY
        ld_library = sysconfig.get_config_var('LDLIBRARY')
        if ld_library:
            name = Path(ld_library).stem
            if name.startswith('lib'):
                name = name[3:]
            return name
        
        library = sysconfig.get_config_var('LIBRARY')
        if library:
            name = Path(library).stem
            if name.startswith('lib'):
                name = name[3:]
            return name
            
    except ImportError:
        pass
    except Exception:
        pass
    
    # Try distutils
    try:
        from distutils import sysconfig as distutils_sysconfig
        
        ld_library = distutils_sysconfig.get_config_var('LDLIBRARY')
        if ld_library:
            name = Path(ld_library).stem
            if name.startswith('lib'):
                name = name[3:]
            return name
            
    except ImportError:
        pass
    except Exception:
        pass
    
    # Build from version info
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    version_short = f"{sys.version_info.major}{sys.version_info.minor}"
    
    if is_windows():
        return f"python{version_short}.lib"
    else:
        return f"python{version}"


def get_python_library_full_path() -> Optional[Path]:
    """
    Get the full path to the Python library file.
    
    This function locates the actual Python library file (e.g., 
    libpython3.10.so, python310.lib, libpython3.10.dylib) on the system.
    
    Returns
    -------
    Optional[Path]
        Path to Python library file, or None if not found.
        
    Examples
    --------
    >>> lib_path = get_python_library_full_path()
    >>> if lib_path:
    ...     print(f"Python library at: {lib_path}")
    ...     # Use directly with compiler
    ...     # gcc ... /path/to/libpython3.10.so
    """
    lib_name = get_python_library_name()
    lib_paths = get_python_library_paths()
    
    # Possible extensions by platform
    if is_windows():
        extensions = ['.lib']
    elif is_macos():
        extensions = ['.dylib', '.so']
    else:
        extensions = ['.so', '.so.1.0', '.a']
    
    # Search in library paths
    for lib_dir in lib_paths:
        for ext in extensions:
            # Try exact name
            candidate = lib_dir / f"{lib_name}{ext}"
            if candidate.exists():
                return candidate
            
            # Try with 'lib' prefix (Unix)
            if not is_windows():
                candidate = lib_dir / f"lib{lib_name}{ext}"
                if candidate.exists():
                    return candidate
            
            # Try with version suffix
            version = f"{sys.version_info.major}.{sys.version_info.minor}"
            candidate = lib_dir / f"libpython{version}{ext}"
            if candidate.exists():
                return candidate
    
    # Try sysconfig directly
    try:
        import sysconfig
        
        lib_dir = sysconfig.get_config_var('LIBDIR')
        ld_library = sysconfig.get_config_var('LDLIBRARY')
        
        if lib_dir and ld_library:
            candidate = Path(lib_dir) / ld_library
            if candidate.exists():
                return candidate
                
    except ImportError:
        pass
    except Exception:
        pass
    
    return None


def get_python_config_var(name: str) -> Optional[str]:
    """
    Get a Python configuration variable.
    
    This function retrieves configuration variables from sysconfig
    or distutils that are useful for compilation.
    
    Parameters
    ----------
    name : str
        Name of the configuration variable.
        
    Returns
    -------
    Optional[str]
        Value of the variable, or None if not found.
        
    Examples
    --------
    >>> # Get compiler flags used to build Python
    >>> cflags = get_python_config_var('CFLAGS')
    >>> print(f"Python CFLAGS: {cflags}")
    >>> 
    >>> # Get linker flags
    >>> ldflags = get_python_config_var('LDFLAGS')
    >>> print(f"Python LDFLAGS: {ldflags}")
    
    Notes
    -----
    Common variable names:
    - CFLAGS, CPPFLAGS, LDFLAGS, LIBS
    - CC, CXX, AR, RANLIB
    - EXT_SUFFIX, SO, SHLIB_SUFFIX
    - prefix, exec_prefix, base, platbase
    """
    # Try sysconfig first
    try:
        import sysconfig
        value = sysconfig.get_config_var(name)
        if value is not None:
            return str(value)
    except ImportError:
        pass
    except Exception:
        pass
    
    # Try distutils
    try:
        from distutils import sysconfig as distutils_sysconfig
        value = distutils_sysconfig.get_config_var(name)
        if value is not None:
            return str(value)
    except ImportError:
        pass
    except Exception:
        pass
    
    return None


def get_python_extension_suffix() -> str:
    """
    Get the file extension for Python C extension modules.
    
    This function returns the platform-specific suffix for compiled
    Python extension modules (e.g., .cpython-310-x86_64-linux-gnu.so).
    
    Returns
    -------
    str
        Extension module suffix (including the dot).
        
    Examples
    --------
    >>> suffix = get_python_extension_suffix()
    >>> print(f"Extension suffix: {suffix}")
    >>> 
    >>> # Build output filename
    >>> output = f"mymodule{suffix}"
    >>> print(output)
    """
    # Try sysconfig
    try:
        import sysconfig
        suffix = sysconfig.get_config_var('EXT_SUFFIX')
        if suffix:
            return suffix
    except ImportError:
        pass
    except Exception:
        pass
    
    # Try distutils
    try:
        from distutils import sysconfig as distutils_sysconfig
        suffix = distutils_sysconfig.get_config_var('EXT_SUFFIX')
        if suffix:
            return suffix
    except ImportError:
        pass
    except Exception:
        pass
    
    # Fallback based on platform
    if is_windows():
        return f".cp{sys.version_info.major}{sys.version_info.minor}-{get_architecture().value}.pyd"
    else:
        return f".cpython-{sys.version_info.major}{sys.version_info.minor}-{get_architecture().value}-{get_system()}.so"


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "PlatformType",
    "ArchitectureType",
    "PythonImplementation",
    
    # Data classes
    "PlatformInfo",
    
    # Cache management
    "clear_platform_cache",
    
    # Platform detection
    "get_platform",
    "get_platform_info",
    "get_architecture",
    "get_system",
    "get_machine",
    "get_processor",
    
    # Python info
    "get_python_version",
    "get_python_version_tuple",
    "get_python_implementation",
    "get_python_abi",
    
    # Extensions
    "get_shared_library_extension",
    "get_executable_extension",
    "get_object_extension",
    "get_static_library_extension",
    "get_python_extension_module_extension",
    
    # Boolean checks
    "is_windows",
    "is_linux",
    "is_macos",
    "is_bsd",
    "is_wsl",
    "is_cygwin",
    "is_msys",
    "is_android",
    "is_ios",
    "is_unix",
    "is_windows_family",
    "is_64bit",
    "is_32bit",
    "is_arm",
    "is_x86",
    
    # System resources
    "get_cpu_count",
    "get_cpu_count_physical",
    "get_total_memory",
    "get_available_memory",
    
    # Directories
    "get_user_cache_dir",
    "get_user_config_dir",
    "get_user_data_dir",
    "get_temp_directory",

    # Python environment
    "get_python_include_paths",
    "get_python_library_paths",
    "get_python_library_name",
    "get_python_library_full_path",
    "get_python_config_var",
    "get_python_extension_suffix",
]

