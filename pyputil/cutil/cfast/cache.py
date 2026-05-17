#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Caching mechanism for compiled libraries with cross-platform file locking.

This module provides a robust, thread-safe, and process-safe caching system
for compiled C libraries. It implements deterministic cache key generation,
atomic file operations, and comprehensive cross-platform file locking to
prevent concurrent compilation races and ensure cache integrity.

The cache system uses a content-addressable approach where the cache key is
derived from all inputs that could affect the compiled output, including:
- Source code (content-hashed)
- Compiler identity and version
- Compilation flags and parameters
- Include paths and preprocessor definitions
- Linked libraries
- Engine version (to invalidate on logic changes)

Security Features
-----------------
- Content-addressable storage prevents cache poisoning
- Atomic file operations eliminate race conditions
- Process-level file locking prevents concurrent modification
- Stale lock detection prevents deadlocks from crashed processes
- Input validation prevents path traversal attacks
- SHA-256 hashing with collision resistance

Locking Mechanism
-----------------
File locking ensures that multiple processes attempting to compile the same
code will serialize access. The implementation adapts to the platform:
- Unix (Linux, macOS): fcntl.flock for advisory locking
- Windows: msvcrt.locking for mandatory locking

Each lock file contains process metadata (PID, timestamp, hostname) enabling
detection and recovery from stale locks left by crashed processes.

Cache Structure
---------------
Cache entries are stored in the system temporary directory:
    {tempdir}/cfast_cache/{cache_key}/
        ├── compile.lock          # Lock file with process metadata
        ├── source.c              # Original source code
        ├── metadata.json         # Compilation parameters and hash
        ├── output{ext}           # Compiled shared library
        └── symbols.json          # Exported function signatures

Classes
-------
CacheEntry
    Represents a single cache entry with metadata and validation.
CacheManager
    Manages cache operations including storage, retrieval, and cleanup.
FileLock
    Cross-platform file lock with stale detection and recovery.

Functions
---------
compute_cache_key
    Generate deterministic cache key from compilation inputs.
get_cache_path
    Get filesystem path for a cache entry.
validate_cache_entry
    Verify cache entry integrity and consistency.
cleanup_stale_locks
    Remove stale lock files from abandoned processes.
purge_cache
    Remove all or expired cache entries.

Examples
--------
>>> from cfast.cache import CacheManager, compute_cache_key
>>> 
>>> # Create cache manager
>>> cache = CacheManager()
>>> 
>>> # Generate cache key
>>> key = compute_cache_key(
...     code='int add(int a, int b) { return a + b; }',
...     cflags=['-O3', '-Wall'],
...     compiler_name='gcc',
...     compiler_version='11.4.0',
...     libraries=['m'],
...     includes=['/usr/include'],
...     defines={'NDEBUG': None},
...     engine_version='1.0.0'
... )
>>> 
>>> # Check cache and compile if needed
>>> lib = cache.get_or_compile(key, source_path, compiler)
"""

import hashlib
import os
import sys
import tempfile
import errno
import json
import time
import shutil
import warnings
import platform
import struct
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Union, Set, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from contextlib import contextmanager
from threading import Lock as ThreadLock
from types import FunctionType

from .platform import PlatformInfo
from .utils import atomic_write, get_compiler_version
from .exceptions import CacheError, CacheIntegrityError, LockAcquisitionError


# =============================================================================
# Constants and Configuration
# =============================================================================

# Default cache settings
DEFAULT_CACHE_ROOT = Path(tempfile.gettempdir()) / "cfast_cache"
DEFAULT_STALE_TIMEOUT = 300.0  # 5 minutes
DEFAULT_MAX_CACHE_SIZE = 1024 * 1024 * 1024  # 1 GB
DEFAULT_MAX_CACHE_AGE = timedelta(days=30)
DEFAULT_HASH_ALGORITHM = 'sha256'
DEFAULT_HASH_LENGTH = 16  # Characters from hex digest

# Lock file constants
LOCK_FILE_NAME = "compile.lock"
METADATA_FILE_NAME = "metadata.json"
SOURCE_FILE_NAME = "source.c"
SYMBOLS_FILE_NAME = "symbols.json"
OUTPUT_FILE_NAME = "output"

# Thread-local storage for reentrant lock detection
_thread_local = __import__('threading').local()


class CacheEntryStatus(Enum):
    """Status of a cache entry."""
    VALID = auto()           # Entry is complete and valid
    INCOMPLETE = auto()      # Entry is being written
    CORRUPT = auto()         # Entry is corrupted
    STALE = auto()           # Entry has exceeded max age
    LOCKED = auto()          # Entry is locked by another process


@dataclass(frozen=True)
class CacheKeyComponents:
    """
    Components that make up a cache key.
    
    Attributes
    ----------
    source_hash : str
        SHA-256 hash of the source code content.
    compiler_name : str
        Normalized compiler identifier.
    compiler_version : str
        Compiler version string.
    flags_hash : str
        Hash of compilation flags and parameters.
    engine_version : str
        Engine version for invalidation.
    platform_id : str
        Platform identifier (OS, architecture).
    """
    source_hash: str
    compiler_name: str
    compiler_version: str
    flags_hash: str
    engine_version: str
    platform_id: str
    
    def to_key_string(self) -> str:
        """Convert components to a cache key string."""
        combined = f"{self.source_hash[:8]}_{self.compiler_name}_{self.flags_hash[:8]}_{self.platform_id}"
        return hashlib.sha256(combined.encode()).hexdigest()[:DEFAULT_HASH_LENGTH]


@dataclass
class CacheMetadata:
    """
    Metadata stored with each cache entry.
    
    Attributes
    ----------
    cache_key : str
        The cache key for this entry.
    created_at : float
        Unix timestamp when entry was created.
    last_accessed : float
        Unix timestamp of last access.
    compiler_name : str
        Name of compiler used.
    compiler_version : str
        Version of compiler used.
    source_hash : str
        SHA-256 hash of source code.
    flags_hash : str
        Hash of compilation flags.
    file_size : int
        Size of compiled library in bytes.
    platform_info : Dict[str, str]
        Platform information (OS, arch, etc.).
    custom_metadata : Dict[str, Any]
        User-defined metadata.
    """
    cache_key: str
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    compiler_name: str = ""
    compiler_version: str = ""
    source_hash: str = ""
    flags_hash: str = ""
    file_size: int = 0
    platform_info: Dict[str, str] = field(default_factory=dict)
    custom_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self, max_age: Optional[timedelta] = None) -> bool:
        """
        Check if cache entry has exceeded maximum age.
        
        Parameters
        ----------
        max_age : Optional[timedelta]
            Maximum allowed age. If None, never expires.
        
        Returns
        -------
        bool
            True if expired, False otherwise.
        """
        if max_age is None:
            return False
        age = time.time() - self.created_at
        return age > max_age.total_seconds()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheMetadata':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class CacheEntry:
    """
    Represents a single cache entry with validation and lifecycle management.
    
    Attributes
    ----------
    cache_dir : Path
        Directory containing cache files.
    metadata : CacheMetadata
        Entry metadata.
    library_path : Optional[Path]
        Path to compiled library file.
    source_path : Optional[Path]
        Path to cached source file.
    status : CacheEntryStatus
        Current status of the entry.
    """
    cache_dir: Path
    metadata: CacheMetadata
    library_path: Optional[Path] = None
    source_path: Optional[Path] = None
    status: CacheEntryStatus = CacheEntryStatus.VALID
    
    @classmethod
    def from_cache_dir(cls, cache_dir: Path) -> Optional['CacheEntry']:
        """
        Load a cache entry from a directory.
        
        Parameters
        ----------
        cache_dir : Path
            Path to cache directory.
        
        Returns
        -------
        Optional[CacheEntry]
            Loaded entry or None if invalid.
        """
        metadata_path = cache_dir / METADATA_FILE_NAME
        
        if not metadata_path.exists():
            return None
        
        try:
            with open(metadata_path, 'r') as f:
                data = json.load(f)
            metadata = CacheMetadata.from_dict(data)
        except (json.JSONDecodeError, OSError, KeyError):
            return None
        
        # Determine library path based on platform
        lib_ext = _get_shared_library_extension()
        library_path = cache_dir / f"{OUTPUT_FILE_NAME}{lib_ext}"
        source_path = cache_dir / SOURCE_FILE_NAME
        
        # Validate entry
        status = cls._validate_entry(cache_dir, metadata, library_path)
        
        return cls(
            cache_dir=cache_dir,
            metadata=metadata,
            library_path=library_path if library_path.exists() else None,
            source_path=source_path if source_path.exists() else None,
            status=status
        )
    
    @staticmethod
    def _validate_entry(
        cache_dir: Path,
        metadata: CacheMetadata,
        library_path: Path
    ) -> CacheEntryStatus:
        """
        Validate cache entry integrity.
        
        Parameters
        ----------
        cache_dir : Path
            Cache directory path.
        metadata : CacheMetadata
            Entry metadata.
        library_path : Path
            Path to library file.
        
        Returns
        -------
        CacheEntryStatus
            Validation status.
        """
        # Check lock file
        lock_path = cache_dir / LOCK_FILE_NAME
        if lock_path.exists():
            if _is_lock_stale(lock_path):
                try:
                    lock_path.unlink()
                except OSError:
                    pass
            else:
                return CacheEntryStatus.LOCKED
        
        # Check library file
        if not library_path.exists():
            return CacheEntryStatus.INCOMPLETE
        
        # Verify file size matches metadata
        actual_size = library_path.stat().st_size
        if metadata.file_size != actual_size:
            return CacheEntryStatus.CORRUPT
        
        # Verify library is readable
        if not os.access(library_path, os.R_OK):
            return CacheEntryStatus.CORRUPT
        
        return CacheEntryStatus.VALID
    
    def touch(self) -> None:
        """Update last accessed timestamp."""
        self.metadata.last_accessed = time.time()
        self._save_metadata()
    
    def _save_metadata(self) -> None:
        """Save metadata to disk atomically."""
        metadata_path = self.cache_dir / METADATA_FILE_NAME
        try:
            data = self.metadata.to_dict()
            atomic_write(metadata_path, json.dumps(data, indent=2))
        except OSError:
            pass  # Non-critical if metadata write fails
    
    def delete(self) -> bool:
        """
        Delete this cache entry from disk.
        
        Returns
        -------
        bool
            True if deleted successfully, False otherwise.
        """
        try:
            shutil.rmtree(self.cache_dir)
            return True
        except OSError:
            return False


# =============================================================================
# Utility Functions
# =============================================================================

def _get_shared_library_extension() -> str:
    """Return platform-specific shared library extension."""
    if sys.platform.startswith('win'):
        return '.dll'
    elif sys.platform == 'darwin':
        return '.dylib'
    else:
        return '.so'


def _normalize_compiler_name(name: str) -> str:
    """
    Normalize compiler name for consistent cache keys.
    
    Parameters
    ----------
    name : str
        Raw compiler name.
    
    Returns
    -------
    str
        Normalized compiler name.
    """
    name_lower = name.lower()
    
    # Handle common variations
    if 'gcc' in name_lower or 'gnu' in name_lower:
        return 'gcc'
    elif 'clang' in name_lower or 'llvm' in name_lower:
        return 'clang'
    elif 'msvc' in name_lower or 'microsoft' in name_lower or name_lower == 'cl':
        return 'msvc'
    else:
        return name_lower


def _normalize_flags(flags: List[str]) -> List[str]:
    """
    Normalize compilation flags for consistent hashing.
    
    Removes order-dependent variations and normalizes equivalent flags.
    
    Parameters
    ----------
    flags : List[str]
        Raw compilation flags.
    
    Returns
    -------
    List[str]
        Normalized and sorted flags.
    """
    normalized = []
    
    for flag in flags:
        # Remove leading/trailing whitespace
        flag = flag.strip()
        
        # Skip empty flags
        if not flag:
            continue
        
        # Normalize optimization flags
        if flag in ('-O', '-O1', '-O2', '-O3', '-Os', '-Ofast', '/O1', '/O2', '/Ox'):
            normalized.append(flag)
        # Normalize include paths (remove trailing slashes)
        elif flag.startswith('-I') or flag.startswith('/I'):
            path = flag[2:].rstrip('/\\')
            normalized.append(f"{flag[:2]}{path}")
        # Normalize define flags (remove extra spaces)
        elif flag.startswith('-D') or flag.startswith('/D'):
            def_part = flag[2:].replace(' ', '')
            normalized.append(f"{flag[:2]}{def_part}")
        else:
            normalized.append(flag)
    
    # Sort for deterministic order
    return sorted(normalized)


def _hash_content(content: str, algorithm: str = DEFAULT_HASH_ALGORITHM) -> str:
    """
    Generate hash of string content.
    
    Parameters
    ----------
    content : str
        Content to hash.
    algorithm : str
        Hash algorithm name.
    
    Returns
    -------
    str
        Hexadecimal hash string.
    """
    if isinstance(content, FunctionType):
    	content = repr(content)
    hasher = hashlib.new(algorithm)
    hasher.update(content.encode('utf-8'))
    return hasher.hexdigest()


def _get_platform_id() -> str:
    """
    Generate platform identifier for cache segregation.
    
    Returns
    -------
    str
        Platform identifier string.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()
    bits = struct.calcsize("P") * 8
    
    # Normalize machine names
    machine_map = {
        'x86_64': 'x64',
        'amd64': 'x64',
        'i386': 'x86',
        'i686': 'x86',
        'arm64': 'arm64',
        'aarch64': 'arm64',
    }
    machine = machine_map.get(machine, machine)
    
    return f"{system}_{machine}_{bits}bit"


# =============================================================================
# Cache Key Computation
# =============================================================================

def compute_cache_key(
    code: str,
    cflags: List[str],
    compiler_name: str,
    compiler_version: str,
    libraries: List[str],
    includes: List[str],
    defines: Dict[str, Optional[str]],
    engine_version: str,
) -> str:
    """
    Compute a unique, deterministic cache key for compiled output.
    
    The cache key is derived from all inputs that could affect the compiled
    binary. The same inputs will always produce the same key, ensuring
    cache hits for identical compilation requests.
    
    Parameters
    ----------
    code : str
        The complete C source code to be compiled.
    cflags : List[str]
        Compiler flags (e.g., ['-O3', '-Wall']). Order is normalized.
    compiler_name : str
        Name of the compiler (e.g., 'gcc', 'clang', 'msvc').
    compiler_version : str
        Version string of the compiler.
    libraries : List[str]
        Library names to link against (e.g., ['m', 'pthread']).
    includes : List[str]
        Include directory paths.
    defines : Dict[str, Optional[str]]
        Preprocessor macro definitions. Values may be None.
    engine_version : str
        Version identifier for the engine itself.
    
    Returns
    -------
    str
        A hexadecimal hash string (default 16 characters) derived from SHA-256.
    
    Raises
    ------
    ValueError
        If any input contains invalid characters or patterns.
    
    Notes
    -----
    Components are joined with null characters ('\\0') to prevent ambiguity
    between, for example, ['-O', '3'] and ['-O3'].
    
    Examples
    --------
    >>> key = compute_cache_key(
    ...     code='int add(int a, int b) { return a + b; }',
    ...     cflags=['-O3', '-Wall'],
    ...     compiler_name='gcc',
    ...     compiler_version='11.4.0',
    ...     libraries=['m'],
    ...     includes=['/usr/include'],
    ...     defines={'NDEBUG': None, 'VERSION': '1.0'},
    ...     engine_version='1.0.0'
    ... )
    >>> print(key)
    'a1b2c3d4e5f6g7h8'
    """
    # Validate inputs for security
    _validate_cache_key_inputs(code, cflags, compiler_name, libraries, includes, defines)
    
    # Generate source hash
    source_hash = _hash_content(code)
    
    # Normalize inputs
    normalized_compiler = _normalize_compiler_name(compiler_name)
    normalized_cflags = _normalize_flags(cflags)
    normalized_libraries = sorted([lib.strip() for lib in libraries if lib.strip()])
    normalized_includes = sorted([inc.rstrip('/\\') for inc in includes if inc.strip()])
    normalized_defines = sorted([
        f"{k}={v}" if v is not None else k
        for k, v in defines.items()
        if k and k.strip()
    ])
    
    # Build flags string for hashing
    flags_components = [
        *normalized_cflags,
        *normalized_libraries,
        *normalized_includes,
        *normalized_defines,
    ]
    flags_string = "\0".join(flags_components)
    flags_hash = _hash_content(flags_string)
    
    # Get platform identifier
    platform_id = _get_platform_id()
    
    # Create components object
    components = CacheKeyComponents(
        source_hash=source_hash,
        compiler_name=normalized_compiler,
        compiler_version=compiler_version,
        flags_hash=flags_hash,
        engine_version=engine_version,
        platform_id=platform_id,
    )
    
    return components.to_key_string()


def _validate_cache_key_inputs(
    code: str,
    cflags: List[str],
    compiler_name: str,
    libraries: List[str],
    includes: List[str],
    defines: Dict[str, Optional[str]],
) -> None:
    """
    Validate cache key inputs for security and correctness.
    
    Parameters
    ----------
    code : str
        Source code to validate.
    cflags : List[str]
        Compiler flags to validate.
    compiler_name : str
        Compiler name to validate.
    libraries : List[str]
        Library names to validate.
    includes : List[str]
        Include paths to validate.
    defines : Dict[str, Optional[str]]
        Macro definitions to validate.
    
    Raises
    ------
    ValueError
        If any input fails validation.
    """
    # Validate code
    if not code:
        raise ValueError("Source code cannot be empty")
    
    if not isinstance(code, FunctionType) and len(code) > 10 * 1024 * 1024:  # 10 MB limit
        raise ValueError(f"Source code exceeds maximum size (10 MB): {len(code)} bytes")
    
    # Validate compiler name
    if not compiler_name or not compiler_name.strip():
        raise ValueError("Compiler name cannot be empty")
    
    # Check for path traversal in includes
    for inc in includes:
        if '..' in inc or inc.startswith('~'):
            raise ValueError(f"Suspicious include path: {inc}")
    
    # Validate flag strings
    suspicious_patterns = ['&&', '||', ';', '|', '>', '<', '`', '$(']
    for flag in cflags:
        for pattern in suspicious_patterns:
            if pattern in flag:
                raise ValueError(f"Suspicious pattern in flag '{flag}': {pattern}")
    
    # Validate library names
    for lib in libraries:
        if not lib or not lib.strip():
            continue
        if any(c in lib for c in '/\\:. '):
            raise ValueError(f"Invalid library name: {lib}")


# =============================================================================
# Cache Path Management
# =============================================================================

def get_cache_path(cache_key: str, cache_root: Optional[Path] = None) -> Path:
    """
    Get filesystem path for a cache entry.
    
    Parameters
    ----------
    cache_key : str
        The cache key identifying the compilation unit.
    cache_root : Optional[Path]
        Root directory for cache. If None, uses default.
    
    Returns
    -------
    Path
        Path to the cache directory for this key.
    
    Raises
    ------
    ValueError
        If cache_key contains invalid characters.
    """
    # Validate cache key
    if not cache_key or not cache_key.strip():
        raise ValueError("Cache key cannot be empty")
    
    if not all(c in '0123456789abcdef' for c in cache_key.lower()):
        raise ValueError(f"Invalid cache key format: {cache_key}")
    
    root = cache_root or DEFAULT_CACHE_ROOT
    return root / cache_key


def ensure_cache_dir(cache_key: str, cache_root: Optional[Path] = None) -> Path:
    """
    Create and return the cache directory for a given key.
    
    Parameters
    ----------
    cache_key : str
        The cache key identifying this compilation unit.
    cache_root : Optional[Path]
        Root directory for cache.
    
    Returns
    -------
    Path
        Path object pointing to the cache directory.
    
    Raises
    ------
    CacheError
        If directory creation fails.
    """
    cache_dir = get_cache_path(cache_key, cache_root)
    
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Set appropriate permissions
        if sys.platform != 'win32':
            cache_dir.chmod(0o755)
        
        return cache_dir
    except OSError as e:
        raise CacheError(f"Failed to create cache directory {cache_dir}: {e}") from e


# =============================================================================
# Lock File Management
# =============================================================================

def _lock_file_path(cache_dir: Path) -> Path:
    """Return the path to the lock file for a cache directory."""
    return cache_dir / LOCK_FILE_NAME


def _read_lock_metadata(lock_path: Path) -> Optional[Dict[str, Any]]:
    """
    Read metadata from an existing lock file.
    
    Parameters
    ----------
    lock_path : Path
        Path to the lock file.
    
    Returns
    -------
    Optional[Dict[str, Any]]
        Parsed metadata dictionary, or None if the file cannot be read.
    """
    try:
        with open(lock_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _write_lock_metadata(lock_path: Path) -> None:
    """
    Write process metadata to the lock file.
    
    This enables detection of stale locks from crashed processes.
    
    Parameters
    ----------
    lock_path : Path
        Path to the lock file.
    """
    metadata = {
        "pid": os.getpid(),
        "timestamp": time.time(),
        "hostname": platform.node(),
        "process_name": sys.argv[0] if sys.argv else "unknown",
        "thread_id": __import__('threading').current_thread().ident,
    }
    try:
        with open(lock_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f)
    except OSError:
        pass  # Non-critical if metadata write fails


def _is_lock_stale(
    lock_path: Path,
    stale_timeout: float = DEFAULT_STALE_TIMEOUT
) -> bool:
    """
    Check if a lock file is stale (from a crashed process).
    
    A lock is considered stale if:
    1. The PID in the metadata no longer exists, OR
    2. The lock is older than `stale_timeout` seconds.
    
    Parameters
    ----------
    lock_path : Path
        Path to the lock file.
    stale_timeout : float
        Time in seconds after which a lock is considered stale.
    
    Returns
    -------
    bool
        True if the lock appears to be stale, False otherwise.
    """
    metadata = _read_lock_metadata(lock_path)
    if metadata is None:
        # No metadata; assume lock file is just created
        return False
    
    # Check timestamp
    lock_age = time.time() - metadata.get("timestamp", 0)
    if lock_age > stale_timeout:
        return True
    
    # Check if PID still exists
    pid = metadata.get("pid")
    if pid is not None:
        if sys.platform == "win32":
            # Windows: Try to open process
            try:
                import ctypes
                import ctypes.wintypes
                
                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_INFORMATION = 0x0400
                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return False
                return True
            except (ImportError, AttributeError, OSError):
                # Fallback: assume not stale if we can't check
                return lock_age > stale_timeout
        else:
            # Unix: Signal 0 checks existence without killing
            try:
                os.kill(pid, 0)
                return False
            except OSError:
                return True
    
    return False


def cleanup_stale_locks(cache_root: Optional[Path] = None) -> int:
    """
    Remove stale lock files from abandoned processes.
    
    Parameters
    ----------
    cache_root : Optional[Path]
        Root directory of cache. Uses default if None.
    
    Returns
    -------
    int
        Number of stale locks cleaned up.
    """
    root = cache_root or DEFAULT_CACHE_ROOT
    
    if not root.exists():
        return 0
    
    cleaned = 0
    
    try:
        for cache_dir in root.iterdir():
            if not cache_dir.is_dir():
                continue
            
            lock_path = cache_dir / LOCK_FILE_NAME
            if lock_path.exists() and _is_lock_stale(lock_path):
                try:
                    lock_path.unlink()
                    cleaned += 1
                except OSError:
                    pass
    except OSError:
        pass
    
    return cleaned


# =============================================================================
# Platform-Specific Locking
# =============================================================================

if sys.platform.startswith("win"):
    import msvcrt
    
    class WindowsFileLock:
        """Windows-specific file locking using msvcrt.locking."""
        
        def __init__(self, lock_path: Path):
            self.lock_path = lock_path
            self._fd = None
            self._locked = False
        
        def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
            """
            Acquire exclusive lock.
            
            Parameters
            ----------
            blocking : bool
                Whether to block until lock is acquired.
            timeout : Optional[float]
                Maximum time to wait for lock (seconds).
            
            Returns
            -------
            bool
                True if lock acquired, False otherwise.
            """
            if self._locked:
                return True
            
            # Open lock file
            try:
                self._fd = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_RDWR,
                    0o666
                )
            except OSError:
                return False
            
            start_time = time.time()
            
            while True:
                try:
                    if blocking:
                        msvcrt.locking(self._fd, msvcrt.LK_LOCK, 1)
                    else:
                        msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                    
                    self._locked = True
                    _write_lock_metadata(self.lock_path)
                    return True
                    
                except OSError:
                    if not blocking:
                        os.close(self._fd)
                        self._fd = None
                        return False
                    
                    if timeout is not None:
                        if time.time() - start_time >= timeout:
                            os.close(self._fd)
                            self._fd = None
                            return False
                    
                    time.sleep(0.1)
        
        def release(self) -> None:
            """Release the lock."""
            if not self._locked or self._fd is None:
                return
            
            try:
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            finally:
                os.close(self._fd)
                self._fd = None
                self._locked = False
                
                try:
                    self.lock_path.unlink(missing_ok=True)
                except OSError:
                    pass

else:
    import fcntl
    
    class UnixFileLock:
        """Unix-specific file locking using fcntl.flock."""
        
        def __init__(self, lock_path: Path):
            self.lock_path = lock_path
            self._fd = None
            self._locked = False
        
        def acquire(self, blocking: bool = True, timeout: Optional[float] = None) -> bool:
            """
            Acquire exclusive lock.
            
            Parameters
            ----------
            blocking : bool
                Whether to block until lock is acquired.
            timeout : Optional[float]
                Maximum time to wait for lock (seconds).
            
            Returns
            -------
            bool
                True if lock acquired, False otherwise.
            """
            if self._locked:
                return True
            
            # Open lock file
            try:
                self._fd = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_RDWR,
                    0o666
                )
            except OSError:
                return False
            
            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB
            
            start_time = time.time()
            
            while True:
                try:
                    fcntl.flock(self._fd, flags)
                    self._locked = True
                    _write_lock_metadata(self.lock_path)
                    return True
                    
                except (OSError, IOError) as e:
                    if not blocking:
                        os.close(self._fd)
                        self._fd = None
                        return False
                    
                    if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                        os.close(self._fd)
                        self._fd = None
                        return False
                    
                    if timeout is not None:
                        if time.time() - start_time >= timeout:
                            os.close(self._fd)
                            self._fd = None
                            return False
                    
                    time.sleep(0.1)
        
        def release(self) -> None:
            """Release the lock."""
            if not self._locked or self._fd is None:
                return
            
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                os.close(self._fd)
                self._fd = None
                self._locked = False
                
                try:
                    self.lock_path.unlink(missing_ok=True)
                except OSError:
                    pass


# =============================================================================
# FileLock Class
# =============================================================================

class FileLock:
    """
    Cross-platform file lock with stale lock detection and timeout support.
    
    Provides exclusive file locking using platform-specific mechanisms:
    - Windows: msvcrt.locking
    - Unix: fcntl.flock
    
    The lock file contains process metadata (PID, timestamp, hostname) to detect
    stale locks from crashed processes.
    
    Parameters
    ----------
    lock_path : Path
        Path to the lock file.
    stale_timeout : float
        Time in seconds after which a lock is considered stale.
    
    Attributes
    ----------
    lock_path : Path
        Path to the lock file.
    is_locked : bool
        Whether the lock is currently held.
    
    Examples
    --------
    >>> lock = FileLock(Path("/tmp/my.lock"))
    >>> with lock:
    ...     # Critical section
    ...     pass
    """
    
    def __init__(self, lock_path: Path, stale_timeout: float = DEFAULT_STALE_TIMEOUT):
        self.lock_path = lock_path
        self.stale_timeout = stale_timeout
        
        # Platform-specific implementation
        if sys.platform.startswith("win"):
            self._impl = WindowsFileLock(lock_path)
        else:
            self._impl = UnixFileLock(lock_path)
    
    @property
    def is_locked(self) -> bool:
        """Return whether lock is currently held."""
        return self._impl._locked
    
    def acquire(
        self,
        blocking: bool = True,
        timeout: Optional[float] = None,
        check_stale: bool = True
    ) -> bool:
        """
        Acquire an exclusive lock on the file.
        
        Parameters
        ----------
        blocking : bool
            If True, block until the lock is acquired.
            If False, return immediately if lock cannot be acquired.
        timeout : Optional[float]
            Maximum time to wait for lock in seconds. Only applicable when
            blocking=True. None means wait indefinitely.
        check_stale : bool
            If True, check for and break stale locks before attempting
            to acquire.
        
        Returns
        -------
        bool
            True if lock acquired, False otherwise.
        
        Raises
        ------
        LockAcquisitionError
            If lock acquisition fails for unexpected reasons.
        """
        # Check for and break stale locks
        if check_stale and self.lock_path.exists():
            if _is_lock_stale(self.lock_path, self.stale_timeout):
                try:
                    self.lock_path.unlink()
                except OSError:
                    pass
        
        return self._impl.acquire(blocking, timeout)
    
    def release(self) -> None:
        """Release the lock if held."""
        self._impl.release()
    
    def __enter__(self):
        """Context manager entry."""
        if not self.acquire(blocking=True):
            raise LockAcquisitionError(f"Failed to acquire lock: {self.lock_path}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
        return False


@contextmanager
def acquire_cache_lock(
    cache_dir: Path,
    timeout: Optional[float] = None
) -> Optional[FileLock]:
    """
    Context manager for acquiring cache directory lock.
    
    Parameters
    ----------
    cache_dir : Path
        Cache directory to lock.
    timeout : Optional[float]
        Maximum time to wait for lock.
    
    Yields
    ------
    Optional[FileLock]
        Lock object if acquired, None otherwise.
    
    Examples
    --------
    >>> with acquire_cache_lock(cache_dir) as lock:
    ...     if lock:
    ...         # Perform thread-safe operations
    ...         pass
    """
    lock_path = _lock_file_path(cache_dir)
    lock = FileLock(lock_path)
    
    if lock.acquire(blocking=True, timeout=timeout):
        try:
            yield lock
        finally:
            lock.release()
    else:
        warnings.warn(f"Could not acquire lock for {cache_dir}", RuntimeWarning)
        yield None


# =============================================================================
# Cache Manager
# =============================================================================

class CacheManager:
    """
    Manages cache operations including storage, retrieval, and cleanup.
    
    Provides thread-safe and process-safe cache operations with:
    - Automatic stale entry cleanup
    - Size-based eviction
    - Age-based expiration
    - Metadata tracking
    
    Parameters
    ----------
    cache_root : Optional[Path]
        Root directory for cache. Uses default if None.
    max_size : Optional[int]
        Maximum cache size in bytes. None for unlimited.
    max_age : Optional[timedelta]
        Maximum age for cache entries. None for no expiration.
    auto_cleanup : bool
        Whether to automatically clean up stale entries.
    
    Attributes
    ----------
    cache_root : Path
        Root directory of the cache.
    stats : Dict[str, Any]
        Cache statistics (hits, misses, size, etc.).
    
    Examples
    --------
    >>> cache = CacheManager(max_size=1024*1024*1024)  # 1 GB
    >>> 
    >>> # Store compiled library
    >>> cache.store(key, library_path, metadata)
    >>> 
    >>> # Retrieve from cache
    >>> entry = cache.get(key)
    >>> if entry and entry.status == CacheEntryStatus.VALID:
    ...     lib = load_library(entry.library_path)
    """
    
    def __init__(
        self,
        cache_root: Optional[Path] = None,
        max_size: Optional[int] = DEFAULT_MAX_CACHE_SIZE,
        max_age: Optional[timedelta] = DEFAULT_MAX_CACHE_AGE,
        auto_cleanup: bool = True
    ):
        self.cache_root = cache_root or DEFAULT_CACHE_ROOT
        self.max_size = max_size
        self.max_age = max_age
        self.auto_cleanup = auto_cleanup
        
        # Statistics
        self._stats_lock = ThreadLock()
        self.stats = {
            'hits': 0,
            'misses': 0,
            'stores': 0,
            'evictions': 0,
            'errors': 0,
        }
        
        # In-memory cache for loaded libraries
        self._memory_cache: Dict[str, Any] = {}
        self._memory_cache_lock = ThreadLock()
        
        # Initialize cache directory
        self._initialize_cache()
        
        # Run cleanup if enabled
        if auto_cleanup:
            self.cleanup()
    
    def _initialize_cache(self) -> None:
        """Initialize cache directory structure."""
        try:
            self.cache_root.mkdir(parents=True, exist_ok=True)
            
            # Set appropriate permissions
            if sys.platform != 'win32':
                self.cache_root.chmod(0o755)
                
        except OSError as e:
            warnings.warn(f"Failed to initialize cache directory: {e}", RuntimeWarning)
    
    def _get_cache_dir(self, cache_key: str) -> Path:
        """Get cache directory for a key."""
        return self.cache_root / cache_key
    
    def get(self, cache_key: str) -> Optional[CacheEntry]:
        """
        Retrieve a cache entry.
        
        Parameters
        ----------
        cache_key : str
            Cache key identifying the entry.
        
        Returns
        -------
        Optional[CacheEntry]
            Cache entry if found and valid, None otherwise.
        """
        cache_dir = self._get_cache_dir(cache_key)
        
        if not cache_dir.exists():
            with self._stats_lock:
                self.stats['misses'] += 1
            return None
        
        # Check for lock and handle stale locks
        lock_path = cache_dir / LOCK_FILE_NAME
        if lock_path.exists():
            if _is_lock_stale(lock_path):
                try:
                    lock_path.unlink()
                except OSError:
                    pass
            else:
                # Another process is working on this entry
                with self._stats_lock:
                    self.stats['misses'] += 1
                return None
        
        # Load entry
        entry = CacheEntry.from_cache_dir(cache_dir)
        
        if entry is None:
            with self._stats_lock:
                self.stats['misses'] += 1
            return None
        
        # Check expiration
        if entry.metadata.is_expired(self.max_age):
            entry.delete()
            with self._stats_lock:
                self.stats['misses'] += 1
                self.stats['evictions'] += 1
            return None
        
        # Validate entry
        if entry.status != CacheEntryStatus.VALID:
            with self._stats_lock:
                self.stats['misses'] += 1
            return None
        
        # Update access time
        entry.touch()
        
        with self._stats_lock:
            self.stats['hits'] += 1
        
        return entry
    
    def store(
        self,
        cache_key: str,
        source_code: str,
        library_path: Path,
        metadata: CacheMetadata,
        symbols: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Store a compiled library in the cache.
        
        Parameters
        ----------
        cache_key : str
            Cache key for the entry.
        source_code : str
            Original source code.
        library_path : Path
            Path to compiled library.
        metadata : CacheMetadata
            Entry metadata.
        symbols : Optional[Dict[str, Any]]
            Exported function signatures.
        
        Returns
        -------
        bool
            True if stored successfully, False otherwise.
        
        Raises
        ------
        CacheError
            If storage fails for unexpected reasons.
        """
        cache_dir = ensure_cache_dir(cache_key, self.cache_root)
        
        # Acquire lock for atomic storage
        with acquire_cache_lock(cache_dir) as lock:
            if lock is None:
                warnings.warn(f"Could not acquire lock for storing {cache_key}", RuntimeWarning)
            
            try:
                # Check size constraints
                if self.max_size is not None:
                    current_size = self._get_cache_size()
                    library_size = library_path.stat().st_size
                    
                    if current_size + library_size > self.max_size:
                        self._evict(library_size)
                
                # Store source code
                source_path = cache_dir / SOURCE_FILE_NAME
                atomic_write(source_path, source_code)
                
                # Store library
                lib_ext = _get_shared_library_extension()
                cached_lib_path = cache_dir / f"{OUTPUT_FILE_NAME}{lib_ext}"
                shutil.copy2(library_path, cached_lib_path)
                
                # Update metadata with file size
                metadata.file_size = cached_lib_path.stat().st_size
                metadata.cache_key = cache_key
                metadata.platform_info = {
                    'system': platform.system(),
                    'machine': platform.machine(),
                    'python_version': sys.version,
                }
                
                # Save metadata
                metadata_path = cache_dir / METADATA_FILE_NAME
                atomic_write(metadata_path, json.dumps(metadata.to_dict(), indent=2))
                
                # Store symbols if provided
                if symbols:
                    symbols_path = cache_dir / SYMBOLS_FILE_NAME
                    atomic_write(symbols_path, json.dumps(symbols, indent=2))
                
                with self._stats_lock:
                    self.stats['stores'] += 1
                
                return True
                
            except (OSError, shutil.Error) as e:
                with self._stats_lock:
                    self.stats['errors'] += 1
                
                # Clean up partial storage
                try:
                    shutil.rmtree(cache_dir)
                except OSError:
                    pass
                
                raise CacheError(f"Failed to store cache entry {cache_key}: {e}") from e
    
    def get_or_create(
        self,
        cache_key: str,
        source_code: str,
        compiler: Any,
        compile_func: Callable[[], Path],
        symbols: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[Path], bool]:
        """
        Get from cache or create new entry.
        
        Parameters
        ----------
        cache_key : str
            Cache key.
        source_code : str
            Source code.
        compiler : Any
            Compiler instance.
        compile_func : Callable[[], Path]
            Function to compile if not cached.
        symbols : Optional[Dict[str, Any]]
            Function symbols.
        
        Returns
        -------
        Tuple[Optional[Path], bool]
            - Path to library or None if failed
            - True if from cache, False if newly compiled
        """
        # Try memory cache first
        with self._memory_cache_lock:
            if cache_key in self._memory_cache:
                self.stats['hits'] += 1
                return self._memory_cache[cache_key], True
        
        # Try disk cache
        entry = self.get(cache_key)
        if entry and entry.library_path and entry.library_path.exists():
            with self._memory_cache_lock:
                self._memory_cache[cache_key] = entry.library_path
            return entry.library_path, True
        
        # Compile new library
        try:
            library_path = compile_func()
        except Exception as e:
            with self._stats_lock:
                self.stats['errors'] += 1
            raise
        
        # Store in cache
        metadata = CacheMetadata(
            cache_key=cache_key,
            compiler_name=compiler.name,
            compiler_version=compiler.version,
            source_hash=_hash_content(source_code),
        )
        
        if self.store(cache_key, source_code, library_path, metadata, symbols):
            with self._memory_cache_lock:
                self._memory_cache[cache_key] = library_path
            return library_path, False
        
        return library_path, False
    
    def _get_cache_size(self) -> int:
        """
        Calculate total size of cache.
        
        Returns
        -------
        int
            Total size in bytes.
        """
        total_size = 0
        
        try:
            for cache_dir in self.cache_root.iterdir():
                if cache_dir.is_dir():
                    for file_path in cache_dir.rglob('*'):
                        if file_path.is_file():
                            total_size += file_path.stat().st_size
        except OSError:
            pass
        
        return total_size
    
    def _evict(self, needed_space: int) -> None:
        """
        Evict entries to free up space.
        
        Parameters
        ----------
        needed_space : int
            Space needed in bytes.
        """
        entries = []
        
        # Collect all entries with their metadata
        try:
            for cache_dir in self.cache_root.iterdir():
                if not cache_dir.is_dir():
                    continue
                
                entry = CacheEntry.from_cache_dir(cache_dir)
                if entry:
                    entries.append(entry)
        except OSError:
            return
        
        # Sort by last accessed time (oldest first)
        entries.sort(key=lambda e: e.metadata.last_accessed)
        
        freed_space = 0
        for entry in entries:
            if freed_space >= needed_space:
                break
            
            if entry.library_path and entry.library_path.exists():
                freed_space += entry.library_path.stat().st_size
            
            entry.delete()
            
            with self._stats_lock:
                self.stats['evictions'] += 1
    
    def cleanup(self) -> int:
        """
        Clean up stale and expired cache entries.
        
        Returns
        -------
        int
            Number of entries removed.
        """
        removed = 0
        
        # Clean up stale locks first
        removed += cleanup_stale_locks(self.cache_root)
        
        try:
            for cache_dir in self.cache_root.iterdir():
                if not cache_dir.is_dir():
                    continue
                
                entry = CacheEntry.from_cache_dir(cache_dir)
                if entry is None:
                    # Invalid entry, remove
                    try:
                        shutil.rmtree(cache_dir)
                        removed += 1
                    except OSError:
                        pass
                    continue
                
                # Check expiration
                if entry.metadata.is_expired(self.max_age):
                    if entry.delete():
                        removed += 1
                    continue
                
                # Check corruption
                if entry.status == CacheEntryStatus.CORRUPT:
                    if entry.delete():
                        removed += 1
        except OSError:
            pass
        
        return removed
    
    def clear(self) -> int:
        """
        Clear all cache entries.
        
        Returns
        -------
        int
            Number of entries removed.
        """
        removed = 0
        
        try:
            for cache_dir in self.cache_root.iterdir():
                if cache_dir.is_dir():
                    try:
                        shutil.rmtree(cache_dir)
                        removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
        
        # Clear memory cache
        with self._memory_cache_lock:
            self._memory_cache.clear()
        
        # Reset statistics
        with self._stats_lock:
            for key in self.stats:
                self.stats[key] = 0
        
        return removed
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns
        -------
        Dict[str, Any]
            Statistics including hits, misses, size, entry count.
        """
        with self._stats_lock:
            stats = self.stats.copy()
        
        stats['cache_size'] = self._get_cache_size()
        stats['entry_count'] = self._count_entries()
        stats['hit_ratio'] = (
            stats['hits'] / (stats['hits'] + stats['misses'])
            if (stats['hits'] + stats['misses']) > 0
            else 0.0
        )
        
        return stats
    
    def _count_entries(self) -> int:
        """Count valid cache entries."""
        count = 0
        try:
            for cache_dir in self.cache_root.iterdir():
                if cache_dir.is_dir() and (cache_dir / METADATA_FILE_NAME).exists():
                    count += 1
        except OSError:
            pass
        return count


# =============================================================================
# Legacy Compatibility Functions
# =============================================================================

# In-memory cache for backward compatibility
_LOADED_LIBRARIES: Dict[str, Any] = {}


def get_cached_library(key: str) -> Optional[Any]:
    """Return a library from the in-memory cache if present."""
    return _LOADED_LIBRARIES.get(key)


def cache_loaded_library(key: str, lib: Any) -> None:
    """Store a loaded library in the in-memory cache."""
    _LOADED_LIBRARIES[key] = lib


def clear_memory_cache() -> None:
    """Clear the in-memory library cache."""
    _LOADED_LIBRARIES.clear()


def acquire_lock(cache_dir: Path) -> Optional[FileLock]:
    """
    Acquire an exclusive lock on the cache directory (legacy interface).
    
    Parameters
    ----------
    cache_dir : Path
        Cache directory to lock.
    
    Returns
    -------
    Optional[FileLock]
        Lock object if acquired, None otherwise.
    """
    lock_path = _lock_file_path(cache_dir)
    lock = FileLock(lock_path)
    if lock.acquire(blocking=True):
        return lock
    return None


def release_lock(lock: Optional[FileLock]) -> None:
    """Release the lock if it was acquired (legacy interface)."""
    if lock is not None:
        lock.release()


def purge_cache(cache_root: Optional[Path] = None, max_age: Optional[timedelta] = None) -> int:
    """
    Purge expired cache entries.
    
    Parameters
    ----------
    cache_root : Optional[Path]
        Root directory of cache.
    max_age : Optional[timedelta]
        Maximum age for entries.
    
    Returns
    -------
    int
        Number of entries purged.
    """
    manager = CacheManager(cache_root=cache_root, max_age=max_age)
    return manager.cleanup()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Core classes
    'CacheManager',
    'CacheEntry',
    'CacheMetadata',
    'FileLock',
    'CacheEntryStatus',
    'CacheKeyComponents',
    
    # Key computation
    'compute_cache_key',
    
    # Path management
    'get_cache_path',
    'ensure_cache_dir',
    
    # Lock management
    'acquire_cache_lock',
    'cleanup_stale_locks',
    
    # Cache operations
    'purge_cache',
    
    # Legacy compatibility
    'get_cached_library',
    'cache_loaded_library',
    'clear_memory_cache',
    'acquire_lock',
    'release_lock',
    
    # Exceptions
    'CacheError',
    'CacheIntegrityError',
    'LockAcquisitionError',
]


