#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Binary Module Inspector - A Python module type detection library.

This module provides utilities to inspect and classify Python modules,
distinguishing between pure Python, compiled extensions, built-in modules,
frozen modules, namespace packages, and other module types using both
loader-based inspection and signature-based file analysis.

The library is designed to be cross-platform compatible, supporting:
    - Linux (all major distributions)
    - macOS (Darwin) including universal/fat binaries
    - Windows (all versions supporting Python)
    - BSD variants (FreeBSD, OpenBSD, NetBSD, DragonFly)
    - Solaris/SunOS
    - AIX
    - HP-UX
    - Cygwin and MSYS2 environments
    - Other POSIX-compliant systems

Key Features
------------
- Module type classification with high accuracy
- Binary file signature detection for multiple executable formats
- Platform-specific magic number identification
- Thread-safe operation with internal caching
- Minimal dependencies (only standard library)

Examples
--------
>>> from pyputil.cutil import get_module_type, is_extension_module
>>> get_module_type("sys")
'built-in'
>>> get_module_type("numpy")
'extension'
>>> is_extension_module("math")
True
>>> is_extension_module("os")
False

Notes
-----
The module uses importlib's machinery for primary detection and falls back
to binary signature analysis for edge cases where loader information may
be incomplete or inaccurate.
"""

import sys
import os
import importlib.util
import importlib.machinery
import importlib.abc
import stat
import struct
from pathlib import Path
from typing import (
    List, 
    Tuple, 
    Dict, 
    Optional, 
    Union, 
    Any, 
    FrozenSet,
    Iterator,
    ClassVar,
    overload
)
from functools import lru_cache
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict, fields, is_dataclass
from enum import Enum, auto
import warnings

# ============================================================================
# Enums and Data Classes
# ============================================================================

class ModuleType(str, Enum):
    """
    Enumeration of possible Python module types.
    
    This enum provides type-safe constants for module classifications
    returned by module inspection functions.
    
    Attributes
    ----------
    BUILTIN : str
        Modules built into the Python interpreter (e.g., sys, builtins).
    FROZEN : str
        Frozen modules embedded in the interpreter executable.
    EXTENSION : str
        Compiled C/C++/Fortran/Rust extension modules.
    PURE_PYTHON : str
        Pure Python source or bytecode modules.
    NAMESPACE : str
        Namespace packages as defined in PEP 420.
    COMPILED_BINARY : str
        Binary files detected by signature analysis.
    UNKNOWN : str
        Modules that exist but whose type cannot be determined.
    """
    BUILTIN = "built-in"
    FROZEN = "frozen"
    EXTENSION = "extension"
    PURE_PYTHON = "pure-python"
    NAMESPACE = "namespace"
    COMPILED_BINARY = "compiled-binary"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value
    
    @classmethod
    def from_string(cls, value: str) -> Optional['ModuleType']:
        """
        Convert a string to a ModuleType enum value.
        
        Parameters
        ----------
        value : str
            String representation of the module type.
        
        Returns
        -------
        Optional[ModuleType]
            Corresponding enum value, or None if not found.
        """
        try:
            return cls(value)
        except ValueError:
            return None


class BinaryFormat(Enum):
    """
    Enumeration of binary executable formats.
    
    Attributes
    ----------
    ELF : str
        Executable and Linkable Format (Linux/BSD/Solaris).
    PE : str
        Portable Executable format (Windows).
    MACH_O : str
        Mach Object format (macOS/Darwin).
    XCOFF : str
        Extended Common Object File Format (AIX).
    SOM : str
        System Object Module (HP-UX PA-RISC).
    WASM : str
        WebAssembly format.
    ARCHIVE : str
        Static library archive format.
    UNKNOWN : str
        Unknown or unrecognized binary format.
    """
    ELF = "ELF"
    PE = "PE/COFF"
    MACH_O = "Mach-O"
    XCOFF = "XCOFF"
    SOM = "SOM"
    WASM = "WebAssembly"
    ARCHIVE = "AR Archive"
    UNKNOWN = "Unknown"
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


@dataclass(frozen=True)
class MagicNumber:
    """
    Represents a binary format magic number signature.
    
    This immutable dataclass encapsulates a magic number byte sequence
    along with its description and associated binary format.
    
    Attributes
    ----------
    magic : bytes
        The magic number byte sequence.
    description : str
        Human-readable description of the binary format.
    format : BinaryFormat
        The binary format this magic number identifies.
    platform : Optional[str]
        Platform this magic number is associated with.
    endianness : Optional[str]
        Endianness of the format ('little', 'big', or None).
    architecture : Optional[str]
        Target architecture (e.g., '32-bit', '64-bit', 'universal').
    
    Examples
    --------
    >>> elf_magic = MagicNumber(
    ...     magic=b"\\x7fELF",
    ...     description="ELF 64-bit",
    ...     format=BinaryFormat.ELF,
    ...     architecture="64-bit"
    ... )
    >>> elf_magic.magic.hex(' ')
    '7f 45 4c 46'
    """
    magic: bytes
    description: str
    format: BinaryFormat
    platform: Optional[str] = None
    endianness: Optional[str] = None
    architecture: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate the magic number data after initialization."""
        if not self.magic:
            raise ValueError("Magic number cannot be empty")
        if len(self.magic) > 16:  # Reasonable upper limit
            warnings.warn(
                f"Magic number length ({len(self.magic)} bytes) exceeds typical size",
                UserWarning,
                stacklevel=3
            )
    
    def matches(self, data: bytes) -> bool:
        """
        Check if this magic number matches the beginning of given data.
        
        Parameters
        ----------
        data : bytes
            Data to check against this magic number.
        
        Returns
        -------
        bool
            True if data starts with this magic number.
        """
        return data.startswith(self.magic)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the magic number to a dictionary representation.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with all magic number attributes.
        """
        return {
            "magic": self.magic.hex(' '),
            "description": self.description,
            "format": str(self.format),
            "platform": self.platform,
            "endianness": self.endianness,
            "architecture": self.architecture,
        }
    
    def __repr__(self) -> str:
        """Provide a detailed string representation."""
        return (f"MagicNumber(magic={self.magic.hex(' ')}, "
                f"format={self.format.value}, "
                f"description='{self.description}')")


@dataclass
class ModuleInfo:
    """
    Comprehensive information about a Python module.
    
    This dataclass encapsulates all metadata about a Python module,
    including its type, location, loader information, and file properties.
    
    Attributes
    ----------
    name : str
        Fully qualified module name.
    type : Optional[ModuleType]
        Classification of the module type.
    exists : bool
        Whether the module can be found in the import system.
    imported : bool
        Whether the module is currently loaded in sys.modules.
    origin : Optional[str]
        Filesystem path to the module file (if applicable).
    loader : Optional[str]
        Name of the loader class used to load this module.
    is_package : bool
        Whether the module is a package.
    file_size : Optional[int]
        Size of the module file in bytes (if applicable).
    is_binary : bool
        Whether the module file is a compiled binary.
    binary_format : Optional[BinaryFormat]
        Detected binary format if the file is a binary.
    filename_parts : Optional[List[str]]
        Components of the filename split by dots.
    magic_numbers : Optional[List[MagicNumber]]
        Magic numbers detected in the file (if binary).
    submodule_search_locations : Optional[List[str]]
        Package submodule search paths (for packages).
    has_submodules : bool
        Whether the module has discoverable submodules.
    import_time : Optional[float]
        Time when the module was imported (if available).
    
    Examples
    --------
    >>> info = get_module_info("math")
    >>> info.type
    <ModuleType.EXTENSION: 'extension'>
    >>> info.is_binary
    True
    >>> info.to_dict()['name']
    'math'
    """
    name: str
    type: Optional[ModuleType] = None
    exists: bool = False
    imported: bool = False
    origin: Optional[str] = None
    loader: Optional[str] = None
    is_package: bool = False
    file_size: Optional[int] = None
    is_binary: bool = False
    binary_format: Optional[BinaryFormat] = None
    filename_parts: Optional[List[str]] = field(default_factory=list)
    magic_numbers: Optional[List[MagicNumber]] = field(default_factory=list)
    submodule_search_locations: Optional[List[str]] = field(default_factory=list)
    has_submodules: bool = False
    import_time: Optional[float] = None
    
    def __post_init__(self) -> None:
        """Initialize default values and validate after creation."""
        if self.filename_parts is None:
            self.filename_parts = []
        if self.magic_numbers is None:
            self.magic_numbers = []
        if self.submodule_search_locations is None:
            self.submodule_search_locations = []
    
    def to_dict(self, include_magic_details: bool = False) -> Dict[str, Any]:
        """
        Convert the module information to a dictionary.
        
        Parameters
        ----------
        include_magic_details : bool, default=False
            If True, include detailed magic number information as dictionaries.
            Otherwise, include only the count of magic numbers.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the module information.
        """
        result = {
            "name": self.name,
            "type": str(self.type) if self.type else None,
            "exists": self.exists,
            "imported": self.imported,
            "origin": self.origin,
            "loader": self.loader,
            "is_package": self.is_package,
            "file_size": self.file_size,
            "is_binary": self.is_binary,
            "binary_format": str(self.binary_format) if self.binary_format else None,
            "filename_parts": self.filename_parts,
            "submodule_search_locations": self.submodule_search_locations,
            "has_submodules": self.has_submodules,
            "import_time": self.import_time,
        }
        
        if include_magic_details and self.magic_numbers:
            result["magic_numbers"] = [m.to_dict() for m in self.magic_numbers]
        else:
            result["magic_numbers_count"] = len(self.magic_numbers) if self.magic_numbers else 0
        
        return result


@dataclass
class CacheInfo:
    """
    Information about the module specification cache state.
    
    Attributes
    ----------
    size : int
        Number of cached module specifications.
    max_size : Optional[int]
        Maximum cache size (None if unlimited).
    hit_rate : float
        Cache hit rate (0.0 to 1.0).
    misses : int
        Number of cache misses.
    hits : int
        Number of cache hits.
    evictions : int
        Number of cache evictions (if applicable).
    """
    size: int
    max_size: Optional[int] = None
    hit_rate: float = 0.0
    misses: int = 0
    hits: int = 0
    evictions: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)
    
    def __repr__(self) -> str:
        """Provide a detailed string representation."""
        return (f"CacheInfo(size={self.size}, max_size={self.max_size}, "
                f"hit_rate={self.hit_rate:.2%}, hits={self.hits}, "
                f"misses={self.misses})")


@dataclass
class PlatformBinaryInfo:
    """
    Information about binary formats supported on a platform.
    
    Attributes
    ----------
    platform : str
        Platform identifier (e.g., 'linux', 'win32', 'darwin').
    normalized_platform : str
        Normalized platform identifier.
    magic_numbers : List[MagicNumber]
        List of magic numbers for this platform.
    primary_format : Optional[BinaryFormat]
        Primary binary format for this platform.
    extension_suffixes : List[str]
        Valid extension module suffixes for this platform.
    """
    platform: str
    normalized_platform: str
    magic_numbers: List[MagicNumber] = field(default_factory=list)
    primary_format: Optional[BinaryFormat] = None
    extension_suffixes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "platform": self.platform,
            "normalized_platform": self.normalized_platform,
            "primary_format": str(self.primary_format) if self.primary_format else None,
            "extension_suffixes": self.extension_suffixes,
            "magic_numbers": [m.to_dict() for m in self.magic_numbers],
        }
    
    def __repr__(self) -> str:
        """Provide a concise string representation."""
        return (f"PlatformBinaryInfo(platform='{self.platform}', "
                f"primary_format={self.primary_format}, "
                f"magic_numbers={len(self.magic_numbers)})")


# ============================================================================
# Constants & Configuration
# ============================================================================

# Pre-computed mapping for platform-specific binary format signatures
_PLATFORM_MAGIC_MAP: Dict[str, List[MagicNumber]] = {
    # Linux systems - ELF format
    "linux": [
        MagicNumber(
            magic=b"\x7fELF",
            description="ELF (Executable and Linkable Format)",
            format=BinaryFormat.ELF,
            platform="linux"
        )
    ],
    "linux2": [
        MagicNumber(
            magic=b"\x7fELF",
            description="ELF (Executable and Linkable Format)",
            format=BinaryFormat.ELF,
            platform="linux2"
        )
    ],
    "linux-armv7l": [
        MagicNumber(
            magic=b"\x7fELF",
            description="ELF (ARM 32-bit)",
            format=BinaryFormat.ELF,
            platform="linux-armv7l",
            architecture="32-bit"
        )
    ],
    "linux-aarch64": [
        MagicNumber(
            magic=b"\x7fELF",
            description="ELF (AArch64)",
            format=BinaryFormat.ELF,
            platform="linux-aarch64",
            architecture="64-bit"
        )
    ],
    
    # Windows systems - PE/COFF format
    "win32": [
        MagicNumber(
            magic=b"MZ",
            description="PE/COFF (Windows Executable - EXE/DLL/PYD)",
            format=BinaryFormat.PE,
            platform="win32"
        )
    ],
    "win64": [
        MagicNumber(
            magic=b"MZ",
            description="PE32+ (Windows 64-bit Executable - EXE/DLL/PYD)",
            format=BinaryFormat.PE,
            platform="win64",
            architecture="64-bit"
        )
    ],
    "cygwin": [
        MagicNumber(
            magic=b"MZ",
            description="PE/COFF (Cygwin Executable)",
            format=BinaryFormat.PE,
            platform="cygwin"
        )
    ],
    
    # macOS/Darwin systems - Mach-O format
    "darwin": [
        MagicNumber(
            magic=b"\xfe\xed\xfa\xce",
            description="Mach-O 32-bit (big endian)",
            format=BinaryFormat.MACH_O,
            platform="darwin",
            architecture="32-bit",
            endianness="big"
        ),
        MagicNumber(
            magic=b"\xce\xfa\xed\xfe",
            description="Mach-O 32-bit (little endian)",
            format=BinaryFormat.MACH_O,
            platform="darwin",
            architecture="32-bit",
            endianness="little"
        ),
        MagicNumber(
            magic=b"\xfe\xed\xfa\xcf",
            description="Mach-O 64-bit (big endian)",
            format=BinaryFormat.MACH_O,
            platform="darwin",
            architecture="64-bit",
            endianness="big"
        ),
        MagicNumber(
            magic=b"\xcf\xfa\xed\xfe",
            description="Mach-O 64-bit (little endian)",
            format=BinaryFormat.MACH_O,
            platform="darwin",
            architecture="64-bit",
            endianness="little"
        ),
        MagicNumber(
            magic=b"\xca\xfe\xba\xbe",
            description="Mach-O Fat binary (universal 32-bit)",
            format=BinaryFormat.MACH_O,
            platform="darwin",
            architecture="universal"
        ),
        MagicNumber(
            magic=b"\xca\xfe\xba\xbf",
            description="Mach-O Fat binary (universal 64-bit)",
            format=BinaryFormat.MACH_O,
            platform="darwin",
            architecture="universal"
        ),
    ],
    
    # IBM AIX - XCOFF format
    "aix": [
        MagicNumber(
            magic=b"\x01\xdf",
            description="XCOFF32 (AIX 32-bit Object File)",
            format=BinaryFormat.XCOFF,
            platform="aix",
            architecture="32-bit"
        ),
        MagicNumber(
            magic=b"\x01\xf7",
            description="XCOFF64 (AIX 64-bit Object File)",
            format=BinaryFormat.XCOFF,
            platform="aix",
            architecture="64-bit"
        ),
    ],
    
    # HP-UX - SOM/ELF format
    "hp-ux": [
        MagicNumber(
            magic=b"\x02\x10",
            description="SOM (HP-UX PA-RISC Object Module)",
            format=BinaryFormat.SOM,
            platform="hp-ux"
        ),
        MagicNumber(
            magic=b"\x02\x14",
            description="SOM (HP-UX PA-RISC 2.0)",
            format=BinaryFormat.SOM,
            platform="hp-ux"
        ),
        MagicNumber(
            magic=b"\x7fELF",
            description="ELF (HP-UX Itanium)",
            format=BinaryFormat.ELF,
            platform="hp-ux",
            architecture="64-bit"
        ),
    ],
    
    # WebAssembly
    "emscripten": [
        MagicNumber(
            magic=b"\x00asm",
            description="WebAssembly (WASM)",
            format=BinaryFormat.WASM,
            platform="emscripten"
        ),
    ],
}

# Set of platform identifiers that use ELF format
_ELF_PLATFORMS: FrozenSet[str] = frozenset({
    "linux", "linux2", "linux-armv7l", "linux-aarch64",
    "linux-ppc64le", "linux-s390x",
    "freebsd", "openbsd", "netbsd", "dragonfly",
    "sunos", "solaris",
})

# Cache for module specifications
_spec_cache: Dict[str, Optional[importlib.machinery.ModuleSpec]] = {}
_spec_cache_lock: Any = None

# Cache statistics
_cache_hits: int = 0
_cache_misses: int = 0
_cache_evictions: int = 0

# Attempt to import threading for lock support
try:
    import threading
    _spec_cache_lock = threading.RLock()
except ImportError:
    _spec_cache_lock = None


# ============================================================================
# Internal Helper Functions
# ============================================================================

@contextmanager
def _acquire_cache_lock() -> Iterator[None]:
    """
    Context manager for safely acquiring and releasing the cache lock.
    
    Yields
    ------
    None
        Control is yielded back to the caller within the locked context.
    """
    if _spec_cache_lock is not None:
        with _spec_cache_lock:
            yield
    else:
        yield


def _normalize_platform(platform: Optional[str] = None) -> str:
    """
    Normalize platform identifiers to handle variations and aliases.
    
    Parameters
    ----------
    platform : Optional[str], default=None
        Platform identifier to normalize.
    
    Returns
    -------
    str
        Normalized platform identifier.
    """
    if platform is None:
        platform = sys.platform
    
    if not platform:
        return "unknown"
    
    platform_lower = platform.lower()
    
    # BSD variants - strip version numbers
    for bsd_base in ("freebsd", "openbsd", "netbsd", "dragonfly"):
        if platform_lower.startswith(bsd_base):
            if any(c.isdigit() for c in platform_lower):
                return bsd_base
            return platform_lower
    
    # SunOS/Solaris variants
    if platform_lower.startswith(("sunos", "solaris")):
        return "sunos"
    
    # AIX variants
    if platform_lower.startswith("aix"):
        return "aix"
    
    # HP-UX variants
    if platform_lower.startswith(("hp-ux", "hpux")):
        return "hp-ux"
    
    # Windows variants
    if platform_lower.startswith("win"):
        return "win64" if sys.maxsize > 2**32 else "win32"
    
    # Cygwin/MSYS variants
    if "cygwin" in platform_lower:
        return "cygwin"
    if "msys" in platform_lower or "mingw" in platform_lower:
        return "msys"
    
    # Emscripten/WASI
    if "emscripten" in platform_lower:
        return "emscripten"
    if "wasi" in platform_lower:
        return "wasi"
    
    return platform_lower


def _get_module_spec(name: str) -> Optional[importlib.machinery.ModuleSpec]:
    """
    Retrieve module specification with thread-safe caching.
    
    Parameters
    ----------
    name : str
        The fully qualified module name to look up.
    
    Returns
    -------
    Optional[importlib.machinery.ModuleSpec]
        Module specification if found and accessible, None otherwise.
    """
    global _cache_hits, _cache_misses
    
    # Fast path: check cache first
    with _acquire_cache_lock():
        if name in _spec_cache:
            _cache_hits += 1
            return _spec_cache[name]
    
    _cache_misses += 1
    spec = None
    
    try:
        spec = importlib.util.find_spec(name)
        
        # Validate namespace packages
        if spec is not None and spec.origin is None:
            if not hasattr(spec, "submodule_search_locations") or \
               spec.submodule_search_locations is None:
                spec = None
                
    except (ImportError, AttributeError, ValueError, TypeError) as e:
        spec = None
        if os.environ.get("PYTHONDEBUG", ""):
            warnings.warn(
                f"Failed to find spec for module '{name}': {e}",
                RuntimeWarning,
                stacklevel=2
            )
    except Exception as e:
        spec = None
        if os.environ.get("PYTHONDEBUG", ""):
            warnings.warn(
                f"Unexpected error finding spec for '{name}': {type(e).__name__}: {e}",
                RuntimeWarning,
                stacklevel=2
            )
    
    # Cache the result
    with _acquire_cache_lock():
        _spec_cache[name] = spec
    
    return spec


def _read_file_header(path: Path, max_bytes: int = 512) -> Optional[bytes]:
    """
    Safely read the initial bytes of a file for signature detection.
    
    Parameters
    ----------
    path : Path
        Path to the file to read.
    max_bytes : int, default=512
        Maximum number of bytes to read.
    
    Returns
    -------
    Optional[bytes]
        The first `max_bytes` bytes of the file, or None if unreadable.
    """
    try:
        resolved_path = path.resolve(strict=False)
        
        if not resolved_path.exists():
            return None
        
        if not resolved_path.is_file():
            if resolved_path.is_symlink():
                try:
                    target = resolved_path.resolve(strict=True)
                    if not target.is_file():
                        return None
                except (OSError, RuntimeError):
                    return None
            else:
                return None
        
        if not os.access(str(resolved_path), os.R_OK):
            return None
        
        file_stat = resolved_path.stat()
        if file_stat.st_size == 0:
            return None
        
        if stat.S_ISCHR(file_stat.st_mode) or stat.S_ISBLK(file_stat.st_mode):
            return None
        
        with open(resolved_path, "rb") as file_handle:
            return file_handle.read(max_bytes)
        
    except (IOError, OSError, PermissionError, FileNotFoundError):
        return None
    except Exception as e:
        if os.environ.get("PYTHONDEBUG", ""):
            warnings.warn(
                f"Unexpected error reading file '{path}': {e}",
                RuntimeWarning,
                stacklevel=2
            )
        return None


def _detect_binary_format(header: bytes) -> Tuple[Optional[BinaryFormat], List[MagicNumber]]:
    """
    Detect binary format and matching magic numbers from file header.
    
    Parameters
    ----------
    header : bytes
        File header bytes to analyze.
    
    Returns
    -------
    Tuple[Optional[BinaryFormat], List[MagicNumber]]
        Detected binary format and list of matching magic numbers.
    """
    detected_format = None
    matching_magic = []
    
    # Get all magic numbers from all platforms
    all_magic: List[MagicNumber] = []
    for magic_list in _PLATFORM_MAGIC_MAP.values():
        all_magic.extend(magic_list)
    
    for magic_obj in all_magic:
        if magic_obj.matches(header):
            matching_magic.append(magic_obj)
            if detected_format is None:
                detected_format = magic_obj.format
    
    # Additional validation for PE format
    if header.startswith(b"MZ") and len(header) > 0x40:
        try:
            pe_offset = struct.unpack("<I", header[0x3C:0x40])[0]
            if pe_offset < len(header) - 4:
                pe_sig = header[pe_offset:pe_offset + 4]
                if pe_sig not in (b"PE\x00\x00", b"PE\x00\x01"):
                    detected_format = None
        except (struct.error, IndexError):
            detected_format = None
    
    return detected_format, matching_magic


def _check_binary_signatures(path: Path) -> Tuple[bool, Optional[BinaryFormat], List[MagicNumber]]:
    """
    Inspect a file header to determine if it matches known binary signatures.
    
    Parameters
    ----------
    path : Path
        Path to the file to inspect.
    
    Returns
    -------
    Tuple[bool, Optional[BinaryFormat], List[MagicNumber]]
        - Boolean indicating if file is a compiled binary
        - Detected binary format (if any)
        - List of matching magic numbers
    """
    header = _read_file_header(path, max_bytes=512)
    if header is None:
        return False, None, []
    
    detected_format, matching_magic = _detect_binary_format(header)
    
    is_binary = detected_format is not None
    return is_binary, detected_format, matching_magic


def _get_file_extension_suffixes() -> FrozenSet[str]:
    """Get the set of valid Python extension module suffixes."""
    try:
        suffixes = set()
        for suffix in importlib.machinery.EXTENSION_SUFFIXES:
            suffixes.add(suffix)
            suffixes.add(suffix.lower())
        return frozenset(suffixes)
    except AttributeError:
        return frozenset({'.so', '.pyd', '.dylib', '.dll', '.sl'})


_EXTENSION_SUFFIXES: FrozenSet[str] = _get_file_extension_suffixes()
_MIN_BINARY_SIZE: int = 100


def _is_extension_file(path: Path) -> bool:
    """Check if a file has an extension module suffix."""
    suffix = path.suffix.lower()
    return suffix in _EXTENSION_SUFFIXES or any(
        path.name.endswith(ext) for ext in _EXTENSION_SUFFIXES
    )


# ============================================================================
# Public API - Module Type Detection
# ============================================================================

def is_extension_module(name: str) -> bool:
    """
    Determine if a module is a compiled C/C++ extension using loader inspection.
    
    Parameters
    ----------
    name : str
        The fully qualified name of the Python module to check.
    
    Returns
    -------
    bool
        True if the module is an extension module, False otherwise.
    
    Examples
    --------
    >>> is_extension_module("math")
    True
    >>> is_extension_module("os")
    False
    """
    spec = _get_module_spec(name)
    if spec is None:
        return False
    
    if isinstance(spec.loader, importlib.machinery.ExtensionFileLoader):
        return True
    
    if spec.origin and _is_extension_file(Path(spec.origin)):
        return True
    
    return False


def is_compiled_binary(name: str) -> bool:
    """
    Detect if a module is a compiled binary using file signature analysis.
    
    Parameters
    ----------
    name : str
        The fully qualified name of the Python module to check.
    
    Returns
    -------
    bool
        True if the module file is a compiled binary, False otherwise.
    
    Examples
    --------
    >>> is_compiled_binary("math")
    True
    >>> is_compiled_binary("sys")
    False
    """
    spec = _get_module_spec(name)
    if spec is None or spec.origin is None:
        return False
    
    if spec.origin in ("built-in", "frozen"):
        return False
    
    try:
        path = Path(spec.origin)
    except (TypeError, ValueError):
        return False
    
    if not path.exists() or not path.is_file():
        return False
    
    suffix_lower = path.suffix.lower()
    if suffix_lower in (".py", ".pyc", ".pyo"):
        return False
    
    try:
        file_size = path.stat().st_size
    except (OSError, PermissionError):
        return False
    
    if file_size < _MIN_BINARY_SIZE:
        return False
    
    is_binary, _, _ = _check_binary_signatures(path)
    return is_binary


def get_module_type(name: str) -> Optional[ModuleType]:
    """
    Classify a Python module.
    
    Parameters
    ----------
    name : str
        The fully qualified name of the Python module to classify.
    
    Returns
    -------
    Optional[ModuleType]
        The module type as an enum value, or None if not found.
    
    Examples
    --------
    >>> get_module_type("math")
    <ModuleType.EXTENSION: 'extension'>
    >>> get_module_type("os")
    <ModuleType.PURE_PYTHON: 'pure-python'>
    """
    spec = _get_module_spec(name)
    if spec is None:
        return None
    
    if spec.origin == "built-in":
        return ModuleType.BUILTIN
    
    if spec.origin == "frozen":
        return ModuleType.FROZEN
    
    if spec.origin is None and hasattr(spec, "submodule_search_locations"):
        if spec.submodule_search_locations is not None:
            return ModuleType.NAMESPACE
    
    if isinstance(spec.loader, importlib.machinery.ExtensionFileLoader):
        return ModuleType.EXTENSION
    
    if spec.origin:
        try:
            path = Path(spec.origin)
            suffix = path.suffix.lower()
            
            if suffix in (".py", ".pyc", ".pyo"):
                return ModuleType.PURE_PYTHON
            
            if _is_extension_file(path):
                return ModuleType.EXTENSION
            
            is_binary, _, _ = _check_binary_signatures(path)
            if is_binary:
                return ModuleType.COMPILED_BINARY
                
        except (TypeError, ValueError, OSError):
            pass
    
    if name in sys.modules:
        module = sys.modules[name]
        if hasattr(module, "__path__") and not hasattr(module, "__file__"):
            return ModuleType.NAMESPACE
    
    return ModuleType.UNKNOWN


# ============================================================================
# Public API - Module Information
# ============================================================================

def get_module_info(name: str) -> ModuleInfo:
    """
    Get comprehensive information about a Python module as a dataclass.
    
    Parameters
    ----------
    name : str
        The fully qualified name of the Python module to inspect.
    
    Returns
    -------
    ModuleInfo
        Dataclass containing detailed module information.
    
    Examples
    --------
    >>> info = get_module_info("math")
    >>> info.type
    <ModuleType.EXTENSION: 'extension'>
    >>> info.is_binary
    True
    >>> info.to_dict()['name']
    'math'
    >>> print(info.get_summary())
    Module: math
      Type: extension
      Exists: True
      Imported: False
      Binary: Yes
      Format: ELF
    """
    spec = _get_module_spec(name)
    module_type = get_module_type(name) if spec else None
    
    info = ModuleInfo(
        name=name,
        type=module_type,
        exists=spec is not None,
        imported=name in sys.modules,
        origin=spec.origin if spec else None,
        loader=type(spec.loader).__name__ if spec and spec.loader else None,
    )
    
    # Package detection
    if spec:
        info.is_package = hasattr(spec, "submodule_search_locations") and \
                        spec.submodule_search_locations is not None
        if info.is_package and spec.submodule_search_locations:
            info.submodule_search_locations = list(spec.submodule_search_locations)
            info.has_submodules = len(spec.submodule_search_locations) > 0
    
    # File information
    if spec and spec.origin and spec.origin not in ("built-in", "frozen"):
        try:
            path = Path(spec.origin)
            info.filename_parts = path.name.split(".")
            
            if path.is_file():
                try:
                    info.file_size = path.stat().st_size
                except OSError:
                    pass
                
                if info.file_size and info.file_size >= _MIN_BINARY_SIZE:
                    is_binary, binary_format, magic_numbers = _check_binary_signatures(path)
                    info.is_binary = is_binary
                    info.binary_format = binary_format
                    info.magic_numbers = magic_numbers
        except (TypeError, ValueError, OSError):
            pass
    
    # Additional info from imported module
    if name in sys.modules:
        module = sys.modules[name]
        if hasattr(module, "__file__") and not info.origin:
            info.origin = getattr(module, "__file__", None)
        if hasattr(module, "__loader__") and not info.loader:
            info.loader = type(getattr(module, "__loader__")).__name__
    
    return info


def get_module_path(name: str) -> Optional[Path]:
    """
    Get the filesystem path to a module's origin file.
    
    Parameters
    ----------
    name : str
        The fully qualified name of the Python module to locate.
    
    Returns
    -------
    Optional[Path]
        Path object pointing to the module's file, or None if not found.
    
    Examples
    --------
    >>> path = get_module_path("os")
    >>> path.name in ("os.py", "os.pyc")
    True
    """
    info = get_module_info(name)
    if info.origin:
        try:
            return Path(info.origin)
        except (TypeError, ValueError):
            pass
    return None


def get_module_filename_parts(name: str) -> Optional[List[str]]:
    """
    Extract the filename components of a module's origin file.
    
    Parameters
    ----------
    name : str
        The fully qualified name of the Python module to inspect.
    
    Returns
    -------
    Optional[List[str]]
        List of filename parts split by dots, or None if not available.
    """
    info = get_module_info(name)
    return info.filename_parts if info.filename_parts else None


# ============================================================================
# Public API - Cache Management
# ============================================================================

def clear_spec_cache() -> None:
    """
    Clear the internal module specification cache.
    
    Examples
    --------
    >>> get_module_type("math")  # Caches the result
    'extension'
    >>> clear_spec_cache()
    """
    global _cache_evictions
    with _acquire_cache_lock():
        _cache_evictions += len(_spec_cache)
        _spec_cache.clear()


def get_cache_info() -> CacheInfo:
    """
    Get information about the current state of the specification cache.
    
    Returns
    -------
    CacheInfo
        Dataclass containing cache statistics.
    
    Examples
    --------
    >>> info = get_cache_info()
    >>> info.size >= 0
    True
    >>> info.hit_rate >= 0
    True
    """
    global _cache_hits, _cache_misses, _cache_evictions
    
    with _acquire_cache_lock():
        size = len(_spec_cache)
    
    total_requests = _cache_hits + _cache_misses
    hit_rate = _cache_hits / total_requests if total_requests > 0 else 0.0
    
    return CacheInfo(
        size=size,
        max_size=None,
        hit_rate=hit_rate,
        hits=_cache_hits,
        misses=_cache_misses,
        evictions=_cache_evictions,
    )


# ============================================================================
# Public API - Platform Magic Numbers
# ============================================================================

@lru_cache(maxsize=1)
def get_magic_numbers(platform: Optional[str] = None) -> List[MagicNumber]:
    """
    Retrieve magic number signatures for compiled binary formats.
    
    Parameters
    ----------
    platform : Optional[str], default=None
        Platform identifier to query. If None, uses current platform.
    
    Returns
    -------
    List[MagicNumber]
        List of MagicNumber objects for the specified platform.
    
    Raises
    ------
    NotImplementedError
        If the specified platform is not recognized.
    
    Examples
    --------
    >>> magic_numbers = get_magic_numbers()
    >>> len(magic_numbers) > 0
    True
    >>> isinstance(magic_numbers[0], MagicNumber)
    True
    """
    normalized_platform = _normalize_platform(platform)
    
    if normalized_platform in _PLATFORM_MAGIC_MAP:
        return _PLATFORM_MAGIC_MAP[normalized_platform]
    
    if normalized_platform in _ELF_PLATFORMS:
        return _PLATFORM_MAGIC_MAP["linux"]
    
    supported = sorted(set(_PLATFORM_MAGIC_MAP.keys()))
    raise NotImplementedError(
        f"Unsupported platform: '{normalized_platform}'. "
        f"Supported: {', '.join(supported)}"
    )


def get_current_magic_numbers() -> List[MagicNumber]:
    """
    Get magic numbers for the current platform.
    
    Returns
    -------
    List[MagicNumber]
        List of MagicNumber objects for the current platform.
        Returns empty list if platform is unsupported.
    
    Examples
    --------
    >>> magic = get_current_magic_numbers()
    >>> isinstance(magic, list)
    True
    """
    try:
        return get_magic_numbers()
    except NotImplementedError:
        if os.name == "posix":
            if sys.platform.startswith("aix"):
                return _PLATFORM_MAGIC_MAP.get("aix", [])
            elif sys.platform.startswith(("hp", "hpux")):
                return _PLATFORM_MAGIC_MAP.get("hp-ux", [])
            else:
                return _PLATFORM_MAGIC_MAP.get("linux", [])
        elif os.name == "nt":
            return _PLATFORM_MAGIC_MAP.get("win32", [])
        return []


def get_platform_binary_info(platform: Optional[str] = None) -> PlatformBinaryInfo:
    """
    Get comprehensive binary format information for a platform.
    
    Parameters
    ----------
    platform : Optional[str], default=None
        Platform identifier to query.
    
    Returns
    -------
    PlatformBinaryInfo
        Dataclass containing platform binary information.
    
    Examples
    --------
    >>> info = get_platform_binary_info()
    >>> info.platform == sys.platform
    True
    >>> info.primary_format is not None
    True
    """
    platform_str = platform or sys.platform
    normalized = _normalize_platform(platform_str)
    
    magic_numbers = get_current_magic_numbers() if platform is None else []
    if platform is not None:
        try:
            magic_numbers = get_magic_numbers(platform)
        except NotImplementedError:
            pass
    
    primary_format = magic_numbers[0].format if magic_numbers else None
    
    extension_suffixes = list(_EXTENSION_SUFFIXES) if _EXTENSION_SUFFIXES else []
    
    return PlatformBinaryInfo(
        platform=platform_str,
        normalized_platform=normalized,
        magic_numbers=magic_numbers,
        primary_format=primary_format,
        extension_suffixes=extension_suffixes,
    )


# Module-level constant for the current platform's magic numbers
try:
    MAGIC_NUMBERS: Optional[List[MagicNumber]] = get_current_magic_numbers()
except Exception:
    MAGIC_NUMBERS = None


# ============================================================================
# Public API - Module Iteration
# ============================================================================

def iter_modules_by_type(module_type: Union[str, ModuleType]) -> Iterator[str]:
    """
    Iterate over all imported modules of a specific type.
    
    Parameters
    ----------
    module_type : Union[str, ModuleType]
        The module type to filter by. Can be string or ModuleType enum.
    
    Yields
    ------
    str
        Module names that match the specified type.
    
    Examples
    --------
    >>> list(iter_modules_by_type("built-in"))  # doctest: +ELLIPSIS
    ['sys', 'builtins', ...]
    
    >>> from pyputil.cutil import ModuleType
    >>> list(iter_modules_by_type(ModuleType.EXTENSION))  # doctest: +ELLIPSIS
    ['math', ...]
    """
    if isinstance(module_type, str):
        module_type_enum = ModuleType.from_string(module_type)
    else:
        module_type_enum = module_type
    
    if module_type_enum is None:
        valid_types = [t.value for t in ModuleType]
        raise ValueError(
            f"Invalid module_type '{module_type}'. "
            f"Must be one of: {', '.join(valid_types)}"
        )
    
    for module_name in sys.modules:
        try:
            if get_module_type(module_name) == module_type_enum:
                yield module_name
        except Exception:
            continue


def iter_all_modules() -> Iterator[ModuleInfo]:
    """
    Iterate over all currently imported modules with full information.
    
    Yields
    ------
    ModuleInfo
        ModuleInfo dataclass for each imported module.
    
    Examples
    --------
    >>> for info in iter_all_modules():
    ...     if info.type == ModuleType.BUILTIN:
    ...         print(info.name)
    ...         break
    sys
    """
    for module_name in sys.modules:
        try:
            yield get_module_info(module_name)
        except Exception:
            continue


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "ModuleType",
    "BinaryFormat",
    
    # Dataclasses
    "MagicNumber",
    "ModuleInfo",
    "CacheInfo",
    "PlatformBinaryInfo",
    
    # Module type detection
    "is_extension_module",
    "is_compiled_binary",
    "get_module_type",
    
    # Module information
    "get_module_info",
    "get_module_filename_parts",
    "get_module_path",
    
    # Cache management
    "clear_spec_cache",
    "get_cache_info",
    
    # Platform magic numbers
    "get_magic_numbers",
    "get_current_magic_numbers",
    "get_platform_binary_info",
    "MAGIC_NUMBERS",
    
    # Module iteration
    "iter_modules_by_type",
    "iter_all_modules",
]
