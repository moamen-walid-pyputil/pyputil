#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    CROSS-PLATFORM CACHE SYSTEM
==================================

Intelligent caching system with platform-aware cache keys,
content-based validation, and distributed cache support.
"""

import hashlib
import json
import os
import pickle
import platform
import shutil
import sqlite3
import struct
import sys
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .enums import CacheStrategy
from .exceptions import CacheError, ErrorCategory, ErrorSeverity


@dataclass
class CacheKey:
    """
    Comprehensive cache key for cross-platform binary compatibility.

    This dataclass encapsulates all factors that affect binary compatibility
    across different platforms, compilers, and build configurations.

    Parameters
    ----------
    source_hash : str
        SHA-256 hash of the source file content.
    compiler_name : str
        Name of the compiler (e.g., 'gcc', 'clang', 'msvc').
    compiler_version : str
        Compiler version string.
    platform_name : str
        Operating system name (e.g., 'linux', 'win32', 'darwin').
    architecture : str
        CPU architecture (e.g., 'x86_64', 'aarch64').
    python_version : str
        Python version (e.g., '3.10.12').
    python_abi : str
        Python ABI tag (e.g., 'cp310').
    optimization_flags : Tuple[str, ...]
        Normalized optimization flags used.
    simd_level : str
        SIMD instruction set level used.
    link_type : str
        Type of linking (shared, static, module).
    dependencies_hash : str
        Combined hash of all dependency files.
    environment_hash : str
        Hash of relevant environment variables.

    Attributes
    ----------
    key_string : str
        Precomputed cache key string.
    platform_specific : bool
        Whether this key is platform-specific.

    Examples
    --------
    >>> key = CacheKey(
    ...     source_hash="abc123",
    ...     compiler_name="gcc",
    ...     compiler_version="11.4.0",
    ...     platform_name="linux",
    ...     architecture="x86_64",
    ...     python_version="3.10.12",
    ...     python_abi="cp310",
    ...     optimization_flags=("-O3", "-march=native"),
    ...     simd_level="avx2",
    ...     link_type="module",
    ...     dependencies_hash="def456",
    ...     environment_hash="ghi789"
    ... )
    >>> cache_id = key.generate()
    """

    source_hash: str
    compiler_name: str
    compiler_version: str
    platform_name: str
    architecture: str
    python_version: str
    python_abi: str
    optimization_flags: Tuple[str, ...]
    simd_level: str
    link_type: str
    dependencies_hash: str
    environment_hash: str

    # Optional metadata
    created_at: float = field(default_factory=time.time)
    tags: Set[str] = field(default_factory=set)

    def generate(self) -> str:
        """
        Generate a deterministic cache key string.

        Returns
        -------
        str
            SHA-256 hash of the serialized cache key components.
        """
        # Create a deterministic string representation
        components = [
            self.source_hash,
            self.compiler_name,
            self.compiler_version,
            self.platform_name,
            self.architecture,
            self.python_version,
            self.python_abi,
            ",".join(sorted(self.optimization_flags)),
            self.simd_level,
            self.link_type,
            self.dependencies_hash,
            self.environment_hash,
        ]

        key_string = "|".join(components)
        return hashlib.sha256(key_string.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        data = asdict(self)
        data["optimization_flags"] = list(self.optimization_flags)
        data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheKey":
        """
        Create CacheKey from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary representation.

        Returns
        -------
        CacheKey
            Reconstructed CacheKey instance.
        """
        data["optimization_flags"] = tuple(data["optimization_flags"])
        data["tags"] = set(data["tags"])
        return cls(**data)

    def is_compatible_with(self, other: "CacheKey") -> bool:
        """
        Check if this cache key is binary-compatible with another.

        Parameters
        ----------
        other : CacheKey
            Another cache key to compare.

        Returns
        -------
        bool
            True if the keys represent compatible binaries.
        """
        # Critical compatibility factors
        critical_fields = [
            "platform_name",
            "architecture",
            "python_version",
            "python_abi",
            "compiler_name",
            "link_type",
        ]

        for field in critical_fields:
            if getattr(self, field) != getattr(other, field):
                return False

        return True

    def get_cache_subdir(self) -> Path:
        """
        Get the cache subdirectory path based on key components.

        Returns
        -------
        Path
            Relative path for cache organization.
        """
        # Organize cache by platform, architecture, and compiler
        parts = [
            self.platform_name,
            self.architecture,
            self.compiler_name,
            self.python_version,
        ]
        return Path(*parts)

    def get_filename(self) -> str:
        """
        Get the cache filename.

        Returns
        -------
        str
            Cache filename including extension.
        """
        # Determine extension based on link type
        if self.link_type == "module":
            if self.platform_name == "win32":
                ext = ".pyd"
            else:
                ext = ".so"
        elif self.link_type == "shared":
            if self.platform_name == "win32":
                ext = ".dll"
            elif self.platform_name == "darwin":
                ext = ".dylib"
            else:
                ext = ".so"
        elif self.link_type == "static":
            if self.platform_name == "win32":
                ext = ".lib"
            else:
                ext = ".a"
        else:
            ext = ""

        return f"{self.generate()[:16]}{ext}"


class CacheMetadata:
    """
    Metadata for cached compilation artifacts.

    This class stores additional information about cached items
    for cache management, cleanup, and statistics.

    Parameters
    ----------
    cache_key : CacheKey
        The cache key for this artifact.
    file_size : int
        Size of the cached file in bytes.
    compile_time : float
        Compilation time in seconds.
    access_count : int
        Number of times this cache entry has been accessed.
    last_accessed : float
        Timestamp of last access.
    expires_at : Optional[float]
        Expiration timestamp, if any.

    Attributes
    ----------
    cache_key : CacheKey
        Cache key reference.
    file_size : int
        File size in bytes.
    compile_time : float
        Compilation time.
    access_count : int
        Access counter.
    last_accessed : float
        Last access timestamp.
    expires_at : Optional[float]
        Expiration timestamp.
    """

    def __init__(
        self,
        cache_key: CacheKey,
        file_size: int = 0,
        compile_time: float = 0.0,
        access_count: int = 0,
        last_accessed: Optional[float] = None,
        expires_at: Optional[float] = None,
    ):
        self.cache_key = cache_key
        self.file_size = file_size
        self.compile_time = compile_time
        self.access_count = access_count
        self.last_accessed = last_accessed or time.time()
        self.expires_at = expires_at

    def record_access(self) -> None:
        """
        Record a cache access, incrementing counters.
        """
        self.access_count += 1
        self.last_accessed = time.time()

    def is_expired(self) -> bool:
        """
        Check if this cache entry has expired.

        Returns
        -------
        bool
            True if expired.
        """
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "cache_key": self.cache_key.to_dict(),
            "file_size": self.file_size,
            "compile_time": self.compile_time,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheMetadata":
        """
        Create CacheMetadata from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary representation.

        Returns
        -------
        CacheMetadata
            Reconstructed instance.
        """
        return cls(
            cache_key=CacheKey.from_dict(data["cache_key"]),
            file_size=data["file_size"],
            compile_time=data["compile_time"],
            access_count=data["access_count"],
            last_accessed=data["last_accessed"],
            expires_at=data["expires_at"],
        )


class CacheBackend(ABC):
    """
    Abstract base class for cache storage backends.

    This class defines the interface for different cache storage
    implementations (filesystem, SQLite, Redis, etc.).
    """

    @abstractmethod
    def get(self, key: CacheKey) -> Optional[Path]:
        """
        Retrieve a cached item.

        Parameters
        ----------
        key : CacheKey
            Cache key to retrieve.

        Returns
        -------
        Optional[Path]
            Path to cached file, or None if not found.
        """
        pass

    @abstractmethod
    def put(self, key: CacheKey, source_path: Path) -> bool:
        """
        Store a file in the cache.

        Parameters
        ----------
        key : CacheKey
            Cache key for the item.
        source_path : Path
            Path to the file to cache.

        Returns
        -------
        bool
            True if stored successfully.
        """
        pass

    @abstractmethod
    def contains(self, key: CacheKey) -> bool:
        """
        Check if a key exists in the cache.

        Parameters
        ----------
        key : CacheKey
            Cache key to check.

        Returns
        -------
        bool
            True if the key exists.
        """
        pass

    @abstractmethod
    def remove(self, key: CacheKey) -> bool:
        """
        Remove an item from the cache.

        Parameters
        ----------
        key : CacheKey
            Cache key to remove.

        Returns
        -------
        bool
            True if removed successfully.
        """
        pass

    @abstractmethod
    def clear(self) -> int:
        """
        Clear all items from the cache.

        Returns
        -------
        int
            Number of items removed.
        """
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns
        -------
        Dict[str, Any]
            Dictionary of cache statistics.
        """
        pass

    @abstractmethod
    def cleanup_expired(self) -> int:
        """
        Remove expired items from the cache.

        Returns
        -------
        int
            Number of items removed.
        """
        pass

    @abstractmethod
    def get_metadata(self, key: CacheKey) -> Optional[CacheMetadata]:
        """
        Get metadata for a cached item.

        Parameters
        ----------
        key : CacheKey
            Cache key.

        Returns
        -------
        Optional[CacheMetadata]
            Metadata or None if not found.
        """
        pass

    @abstractmethod
    def update_metadata(self, key: CacheKey, metadata: CacheMetadata) -> bool:
        """
        Update metadata for a cached item.

        Parameters
        ----------
        key : CacheKey
            Cache key.
        metadata : CacheMetadata
            Updated metadata.

        Returns
        -------
        bool
            True if updated successfully.
        """
        pass


class FilesystemCacheBackend(CacheBackend):
    """
    Filesystem-based cache backend implementation.

    This backend stores cached files directly on the filesystem
    with an optional SQLite database for metadata.

    Parameters
    ----------
    cache_dir : Path
        Root directory for cache storage.
    use_db : bool, optional
        Whether to use SQLite for metadata (default: True).
    compression : bool, optional
        Whether to compress cached files (default: False).

    Attributes
    ----------
    cache_dir : Path
        Cache root directory.
    db_path : Optional[Path]
        Path to SQLite database file.
    _db_connection : Optional[sqlite3.Connection]
        SQLite connection.
    _lock : RLock
        Thread lock for concurrent access.

    Examples
    --------
    >>> backend = FilesystemCacheBackend(Path(".hypercache"))
    >>> key = CacheKey(...)
    >>> backend.put(key, Path("output.so"))
    >>> cached = backend.get(key)
    """

    def __init__(
        self, cache_dir: Path, use_db: bool = True, compression: bool = False
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.use_db = use_db
        self.compression = compression
        self._lock = RLock()

        if self.use_db:
            self.db_path = self.cache_dir / "cache.db"
            self._init_database()
        else:
            self.db_path = None
            self._db_connection = None

    def _init_database(self) -> None:
        """
        Initialize the SQLite database for metadata storage.
        """
        self._db_connection = sqlite3.connect(
            str(self.db_path), check_same_thread=False
        )
        self._db_connection.execute("""
            CREATE TABLE IF NOT EXISTS cache_metadata (
                cache_key TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                file_size INTEGER,
                compile_time REAL,
                access_count INTEGER DEFAULT 0,
                last_accessed REAL,
                expires_at REAL,
                created_at REAL DEFAULT (strftime('%s', 'now')),
                metadata_json TEXT
            )
        """)
        self._db_connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_accessed 
            ON cache_metadata(last_accessed)
        """)
        self._db_connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_expires_at 
            ON cache_metadata(expires_at) WHERE expires_at IS NOT NULL
        """)
        self._db_connection.commit()

    def _get_cache_path(self, key: CacheKey) -> Path:
        """
        Get the filesystem path for a cache key.

        Parameters
        ----------
        key : CacheKey
            Cache key.

        Returns
        -------
        Path
            Full path to the cached file.
        """
        subdir = self.cache_dir / key.get_cache_subdir()
        subdir.mkdir(parents=True, exist_ok=True)
        return subdir / key.get_filename()

    def get(self, key: CacheKey) -> Optional[Path]:
        """
        Retrieve a cached item from the filesystem.

        Parameters
        ----------
        key : CacheKey
            Cache key to retrieve.

        Returns
        -------
        Optional[Path]
            Path to cached file, or None if not found.
        """
        with self._lock:
            cache_path = self._get_cache_path(key)

            if not cache_path.exists():
                return None

            # Check if file is valid (not corrupted)
            try:
                if not self._validate_file(cache_path):
                    self.remove(key)
                    return None
            except (OSError, IOError):
                return None

            # Update access metadata
            if self.use_db:
                self._update_access_metadata(key, cache_path)

            return cache_path

    def _validate_file(self, path: Path) -> bool:
        """
        Validate that a cached file is not corrupted.

        Parameters
        ----------
        path : Path
            Path to the file.

        Returns
        -------
        bool
            True if file appears valid.
        """
        try:
            # Basic validation: check file exists and has content
            if not path.exists():
                return False

            stat = path.stat()
            if stat.st_size == 0:
                return False

            # For shared libraries, check magic number
            if path.suffix in (".so", ".dylib"):
                with open(path, "rb") as f:
                    magic = f.read(4)
                    # ELF magic: 0x7F 'E' 'L' 'F'
                    if magic == b"\x7fELF":
                        return True
                    # Mach-O magic: various
                    if magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
                        return True
            elif path.suffix == ".dll" or path.suffix == ".pyd":
                with open(path, "rb") as f:
                    magic = f.read(2)
                    # PE magic: 'MZ'
                    if magic == b"MZ":
                        return True

            return True
        except (OSError, IOError):
            return False

    def _update_access_metadata(self, key: CacheKey, path: Path) -> None:
        """
        Update access metadata in the database.

        Parameters
        ----------
        key : CacheKey
            Cache key.
        path : Path
            Cached file path.
        """
        if not self._db_connection:
            return

        try:
            cache_id = key.generate()
            self._db_connection.execute("""
                UPDATE cache_metadata 
                SET access_count = access_count + 1,
                    last_accessed = ?
                WHERE cache_key = ?
            """, (time.time(), cache_id))
            self._db_connection.commit()
        except sqlite3.Error:
            pass

    def put(self, key: CacheKey, source_path: Path) -> bool:
        """
        Store a file in the filesystem cache.

        Parameters
        ----------
        key : CacheKey
            Cache key for the item.
        source_path : Path
            Path to the file to cache.

        Returns
        -------
        bool
            True if stored successfully.
        """
        if not source_path.exists():
            return False

        with self._lock:
            cache_path = self._get_cache_path(key)

            try:
                # Copy file to cache
                if self.compression:
                    self._copy_compressed(source_path, cache_path)
                else:
                    shutil.copy2(source_path, cache_path)

                # Store metadata
                stat = cache_path.stat()
                metadata = CacheMetadata(
                    cache_key=key,
                    file_size=stat.st_size,
                    compile_time=0.0,  # Will be set by caller
                    access_count=0,
                    last_accessed=time.time(),
                )

                if self.use_db:
                    self._store_metadata(key, cache_path, metadata)

                return True
            except (OSError, IOError, shutil.Error) as e:
                raise CacheError(
                    message=f"Failed to store cache file: {e}",
                    cache_path=cache_path,
                    operation="write",
                    severity=ErrorSeverity.WARNING,
                )

    def _copy_compressed(self, source: Path, dest: Path) -> None:
        """
        Copy and compress a file.

        Parameters
        ----------
        source : Path
            Source file path.
        dest : Path
            Destination file path (with .gz extension added).
        """
        import gzip

        dest_gz = dest.with_suffix(dest.suffix + ".gz")
        with open(source, "rb") as f_in:
            with gzip.open(dest_gz, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

    def _store_metadata(
        self, key: CacheKey, path: Path, metadata: CacheMetadata
    ) -> None:
        """
        Store metadata in the database.

        Parameters
        ----------
        key : CacheKey
            Cache key.
        path : Path
            Cached file path.
        metadata : CacheMetadata
            Metadata to store.
        """
        if not self._db_connection:
            return

        try:
            cache_id = key.generate()
            self._db_connection.execute("""
                INSERT OR REPLACE INTO cache_metadata 
                (cache_key, file_path, file_size, compile_time, 
                 access_count, last_accessed, expires_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cache_id,
                str(path),
                metadata.file_size,
                metadata.compile_time,
                metadata.access_count,
                metadata.last_accessed,
                metadata.expires_at,
                json.dumps(metadata.to_dict()),
            ))
            self._db_connection.commit()
        except sqlite3.Error as e:
            raise CacheError(
                message=f"Failed to store metadata: {e}",
                cache_path=self.db_path,
                cache_key=cache_id,
                operation="write",
            )

    def contains(self, key: CacheKey) -> bool:
        """
        Check if a key exists in the cache.

        Parameters
        ----------
        key : CacheKey
            Cache key to check.

        Returns
        -------
        bool
            True if the key exists.
        """
        return self.get(key) is not None

    def remove(self, key: CacheKey) -> bool:
        """
        Remove an item from the cache.

        Parameters
        ----------
        key : CacheKey
            Cache key to remove.

        Returns
        -------
        bool
            True if removed successfully.
        """
        with self._lock:
            cache_path = self._get_cache_path(key)
            cache_id = key.generate()

            removed = False

            # Remove file
            if cache_path.exists():
                try:
                    cache_path.unlink()
                    removed = True
                except OSError:
                    pass

            # Remove compressed version if exists
            compressed_path = cache_path.with_suffix(cache_path.suffix + ".gz")
            if compressed_path.exists():
                try:
                    compressed_path.unlink()
                except OSError:
                    pass

            # Remove metadata
            if self._db_connection:
                try:
                    self._db_connection.execute(
                        "DELETE FROM cache_metadata WHERE cache_key = ?",
                        (cache_id,)
                    )
                    self._db_connection.commit()
                except sqlite3.Error:
                    pass

            return removed

    def clear(self) -> int:
        """
        Clear all items from the cache.

        Returns
        -------
        int
            Number of items removed.
        """
        with self._lock:
            count = 0

            # Remove all files
            for item in self.cache_dir.rglob("*"):
                if item.is_file():
                    try:
                        item.unlink()
                        count += 1
                    except OSError:
                        pass

            # Clear database
            if self._db_connection:
                try:
                    cursor = self._db_connection.execute(
                        "SELECT COUNT(*) FROM cache_metadata"
                    )
                    count = cursor.fetchone()[0]
                    self._db_connection.execute("DELETE FROM cache_metadata")
                    self._db_connection.commit()
                except sqlite3.Error:
                    pass

            return count

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns
        -------
        Dict[str, Any]
            Dictionary of cache statistics.
        """
        stats: Dict[str, Any] = {
            "backend": "filesystem",
            "cache_dir": str(self.cache_dir),
            "total_items": 0,
            "total_size_bytes": 0,
            "total_size_mb": 0.0,
            "avg_compile_time": 0.0,
            "hit_rate": 0.0,
        }

        if self._db_connection:
            try:
                cursor = self._db_connection.execute("""
                    SELECT 
                        COUNT(*) as count,
                        SUM(file_size) as total_size,
                        AVG(compile_time) as avg_compile,
                        SUM(access_count) as total_accesses
                    FROM cache_metadata
                """)
                row = cursor.fetchone()
                if row:
                    stats["total_items"] = row[0] or 0
                    stats["total_size_bytes"] = row[1] or 0
                    stats["total_size_mb"] = stats["total_size_bytes"] / (1024 * 1024)
                    stats["avg_compile_time"] = row[2] or 0.0

                    total_accesses = row[3] or 0
                    if stats["total_items"] > 0:
                        stats["hit_rate"] = total_accesses / (
                            total_accesses + stats["total_items"]
                        )
            except sqlite3.Error:
                pass

        return stats

    def cleanup_expired(self) -> int:
        """
        Remove expired items from the cache.

        Returns
        -------
        int
            Number of items removed.
        """
        with self._lock:
            count = 0

            if not self._db_connection:
                return count

            try:
                current_time = time.time()
                cursor = self._db_connection.execute("""
                    SELECT cache_key, file_path 
                    FROM cache_metadata 
                    WHERE expires_at IS NOT NULL AND expires_at < ?
                """, (current_time,))

                for cache_id, file_path in cursor.fetchall():
                    # Remove file
                    try:
                        Path(file_path).unlink(missing_ok=True)
                    except OSError:
                        pass

                    # Remove metadata
                    self._db_connection.execute(
                        "DELETE FROM cache_metadata WHERE cache_key = ?",
                        (cache_id,)
                    )
                    count += 1

                self._db_connection.commit()
            except sqlite3.Error:
                pass

            return count

    def get_metadata(self, key: CacheKey) -> Optional[CacheMetadata]:
        """
        Get metadata for a cached item.

        Parameters
        ----------
        key : CacheKey
            Cache key.

        Returns
        -------
        Optional[CacheMetadata]
            Metadata or None if not found.
        """
        if not self._db_connection:
            return None

        try:
            cursor = self._db_connection.execute("""
                SELECT metadata_json FROM cache_metadata WHERE cache_key = ?
            """, (key.generate(),))
            row = cursor.fetchone()

            if row and row[0]:
                data = json.loads(row[0])
                return CacheMetadata.from_dict(data)
        except (sqlite3.Error, json.JSONDecodeError):
            pass

        return None

    def update_metadata(self, key: CacheKey, metadata: CacheMetadata) -> bool:
        """
        Update metadata for a cached item.

        Parameters
        ----------
        key : CacheKey
            Cache key.
        metadata : CacheMetadata
            Updated metadata.

        Returns
        -------
        bool
            True if updated successfully.
        """
        if not self._db_connection:
            return False

        cache_path = self._get_cache_path(key)
        return self._store_metadata(key, cache_path, metadata)


class CacheManager:
    """
    High-level cache management system.

    This class provides a unified interface for cache operations
    with support for multiple backends, strategies, and policies.

    Parameters
    ----------
    cache_dir : Path
        Root directory for cache storage.
    strategy : CacheStrategy, optional
        Caching strategy (default: CacheStrategy.NORMAL).
    max_size_gb : Optional[float], optional
        Maximum cache size in gigabytes (default: 10.0).
    max_age_days : Optional[int], optional
        Maximum age for cached items in days (default: 30).
    backend : Optional[CacheBackend], optional
        Custom cache backend (default: FilesystemCacheBackend).

    Attributes
    ----------
    cache_dir : Path
        Cache directory.
    strategy : CacheStrategy
        Caching strategy.
    backend : CacheBackend
        Cache backend instance.
    _lock : RLock
        Thread lock.

    Examples
    --------
    >>> manager = CacheManager(
    ...     Path.home() / ".cache" / "cimporter",
    ...     strategy=CacheStrategy.NORMAL,
    ...     max_size_gb=5.0
    ... )
    >>> key = CacheKey(...)
    >>> cached = manager.get(key)
    >>> if cached is None:
    ...     compile()
    ...     manager.put(key, output_path)
    """

    # Global cache directory based on platform conventions
    @classmethod
    def get_default_cache_dir(cls) -> Path:
        """
        Get the default cache directory based on platform.

        Returns
        -------
        Path
            Default cache directory path.
        """
        import sys

        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Caches"
        else:
            base = Path.home() / ".cache"

        return base / "cimporter"

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        strategy: CacheStrategy = CacheStrategy.NORMAL,
        max_size_gb: Optional[float] = 10.0,
        max_age_days: Optional[int] = 30,
        backend: Optional[CacheBackend] = None,
    ):
        self.cache_dir = cache_dir or self.get_default_cache_dir()
        self.strategy = strategy
        self.max_size_gb = max_size_gb
        self.max_age_days = max_age_days
        self._lock = RLock()

        if backend:
            self.backend = backend
        else:
            self.backend = FilesystemCacheBackend(
                self.cache_dir,
                use_db=(strategy != CacheStrategy.NONE),
                compression=False,
            )

        # Run maintenance on initialization
        if self.strategy != CacheStrategy.NONE:
            self._maintenance()

    def get(self, key: CacheKey) -> Optional[Path]:
        """
        Retrieve a cached item.

        Parameters
        ----------
        key : CacheKey
            Cache key to retrieve.

        Returns
        -------
        Optional[Path]
            Path to cached file, or None if not found.
        """
        if self.strategy == CacheStrategy.NONE:
            return None

        with self._lock:
            cached = self.backend.get(key)

            if cached:
                # Check if expired based on strategy
                if self.strategy.should_validate_cache():
                    metadata = self.backend.get_metadata(key)
                    if metadata and metadata.is_expired():
                        self.backend.remove(key)
                        return None

                    # Check age limit
                    if self.max_age_days and metadata:
                        age = time.time() - metadata.last_accessed
                        if age > self.max_age_days * 86400:
                            self.backend.remove(key)
                            return None

            return cached

    def put(
        self, key: CacheKey, source_path: Path, compile_time: float = 0.0
    ) -> bool:
        """
        Store a file in the cache.

        Parameters
        ----------
        key : CacheKey
            Cache key for the item.
        source_path : Path
            Path to the file to cache.
        compile_time : float, optional
            Compilation time in seconds.

        Returns
        -------
        bool
            True if stored successfully.
        """
        if self.strategy == CacheStrategy.NONE:
            return False

        with self._lock:
            success = self.backend.put(key, source_path)

            if success:
                # Update metadata with compile time
                metadata = self.backend.get_metadata(key)
                if metadata:
                    metadata.compile_time = compile_time
                    if self.max_age_days:
                        metadata.expires_at = time.time() + (
                            self.max_age_days * 86400
                        )
                    self.backend.update_metadata(key, metadata)

                # Check size limit
                if self.max_size_gb:
                    self._enforce_size_limit()

            return success

    def _enforce_size_limit(self) -> None:
        """
        Enforce maximum cache size by removing oldest items.
        """
        if not self.max_size_gb:
            return

        stats = self.backend.get_stats()
        current_size_gb = stats.get("total_size_mb", 0) / 1024

        if current_size_gb <= self.max_size_gb:
            return

        # Remove oldest items until under limit
        if isinstance(self.backend, FilesystemCacheBackend):
            self._remove_oldest_items(current_size_gb - self.max_size_gb)

    def _remove_oldest_items(self, excess_gb: float) -> None:
        """
        Remove oldest cache items to free space.

        Parameters
        ----------
        excess_gb : float
            Amount of space to free in gigabytes.
        """
        if not isinstance(self.backend, FilesystemCacheBackend):
            return

        if not self.backend._db_connection:
            return

        try:
            excess_bytes = excess_gb * 1024 * 1024 * 1024
            freed_bytes = 0

            cursor = self.backend._db_connection.execute("""
                SELECT cache_key, file_path, file_size
                FROM cache_metadata
                ORDER BY last_accessed ASC
            """)

            for cache_id, file_path, file_size in cursor.fetchall():
                if freed_bytes >= excess_bytes:
                    break

                # Remove file
                try:
                    Path(file_path).unlink(missing_ok=True)
                except OSError:
                    pass

                # Remove metadata
                self.backend._db_connection.execute(
                    "DELETE FROM cache_metadata WHERE cache_key = ?",
                    (cache_id,)
                )

                freed_bytes += file_size or 0

            self.backend._db_connection.commit()
        except sqlite3.Error:
            pass

    def _maintenance(self) -> None:
        """
        Perform periodic cache maintenance.
        """
        with self._lock:
            # Clean up expired items
            self.backend.cleanup_expired()

            # Enforce size limit
            if self.max_size_gb:
                self._enforce_size_limit()

    def clear(self) -> int:
        """
        Clear all items from the cache.

        Returns
        -------
        int
            Number of items removed.
        """
        with self._lock:
            return self.backend.clear()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns
        -------
        Dict[str, Any]
            Dictionary of cache statistics.
        """
        return self.backend.get_stats()

    def remove(self, key: CacheKey) -> bool:
        """
        Remove a specific item from the cache.

        Parameters
        ----------
        key : CacheKey
            Cache key to remove.

        Returns
        -------
        bool
            True if removed.
        """
        with self._lock:
            return self.backend.remove(key)

    def contains(self, key: CacheKey) -> bool:
        """
        Check if an item exists in the cache.

        Parameters
        ----------
        key : CacheKey
            Cache key to check.

        Returns
        -------
        bool
            True if cached.
        """
        if self.strategy == CacheStrategy.NONE:
            return False
        return self.backend.contains(key)


class CacheKeyBuilder:
    """
    Builder for creating comprehensive cache keys.

    This class collects all relevant information from the build
    environment to generate deterministic cache keys.

    Parameters
    ----------
    source_path : Path
        Path to the source file.

    Attributes
    ----------
    source_path : Path
        Source file path.
    _source_hash : Optional[str]
        Cached source hash.
    _dependencies : List[Path]
        List of dependency files.
    """

    def __init__(self, source_path: Path):
        self.source_path = Path(source_path)
        self._source_hash: Optional[str] = None
        self._dependencies: List[Path] = []

    def compute_source_hash(self) -> str:
        """
        Compute SHA-256 hash of the source file.

        Returns
        -------
        str
            Hexadecimal hash string.
        """
        if self._source_hash:
            return self._source_hash

        hasher = hashlib.sha256()
        with open(self.source_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        self._source_hash = hasher.hexdigest()
        return self._source_hash

    def add_dependency(self, path: Path) -> "CacheKeyBuilder":
        """
        Add a dependency file to include in the cache key.

        Parameters
        ----------
        path : Path
            Path to dependency file.

        Returns
        -------
        CacheKeyBuilder
            Self for method chaining.
        """
        self._dependencies.append(Path(path))
        return self

    def compute_dependencies_hash(self) -> str:
        """
        Compute combined hash of all dependencies.

        Returns
        -------
        str
            Hexadecimal hash string.
        """
        if not self._dependencies:
            return hashlib.sha256(b"").hexdigest()

        hasher = hashlib.sha256()
        for dep_path in sorted(self._dependencies):
            if dep_path.exists():
                with open(dep_path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        hasher.update(chunk)
                hasher.update(str(dep_path).encode())
        return hasher.hexdigest()

    @staticmethod
    def get_compiler_version(compiler_name: str) -> str:
        """
        Get compiler version string.

        Parameters
        ----------
        compiler_name : str
            Compiler name (e.g., 'gcc', 'clang', 'cl').

        Returns
        -------
        str
            Version string.
        """
        try:
            if compiler_name == "cl":
                result = subprocess.run(
                    [compiler_name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    shell=True,
                )
                # Parse MSVC version from output
                for line in result.stdout.split("\n"):
                    if "Version" in line:
                        return line.strip()
            else:
                result = subprocess.run(
                    [compiler_name, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return result.stdout.split("\n")[0].strip()
        except (subprocess.SubprocessError, FileNotFoundError):
            return "unknown"

        return "unknown"

    @staticmethod
    def get_python_abi() -> str:
        """
        Get Python ABI tag.

        Returns
        -------
        str
            ABI tag (e.g., 'cp310').
        """
        return f"cp{sys.version_info.major}{sys.version_info.minor}"

    @staticmethod
    def get_environment_hash() -> str:
        """
        Compute hash of relevant environment variables.

        Returns
        -------
        str
            Hexadecimal hash string.
        """
        relevant_vars = [
            "CFLAGS",
            "CXXFLAGS",
            "LDFLAGS",
            "CC",
            "CXX",
            "PATH",
            "PYTHONPATH",
            "LD_LIBRARY_PATH",
            "DYLD_LIBRARY_PATH",
        ]

        hasher = hashlib.sha256()
        for var in sorted(relevant_vars):
            value = os.environ.get(var, "")
            hasher.update(f"{var}={value}".encode())

        return hasher.hexdigest()

    def build(
        self,
        compiler_name: str,
        optimization_flags: Tuple[str, ...],
        simd_level: str,
        link_type: str,
    ) -> CacheKey:
        """
        Build the final cache key.

        Parameters
        ----------
        compiler_name : str
            Compiler name.
        optimization_flags : Tuple[str, ...]
            Optimization flags tuple.
        simd_level : str
            SIMD level string.
        link_type : str
            Link type string.

        Returns
        -------
        CacheKey
            Complete cache key.
        """
        return CacheKey(
            source_hash=self.compute_source_hash(),
            compiler_name=compiler_name,
            compiler_version=self.get_compiler_version(compiler_name),
            platform_name=sys.platform,
            architecture=platform.machine(),
            python_version=sys.version.split()[0],
            python_abi=self.get_python_abi(),
            optimization_flags=optimization_flags,
            simd_level=simd_level,
            link_type=link_type,
            dependencies_hash=self.compute_dependencies_hash(),
            environment_hash=self.get_environment_hash(),
        )