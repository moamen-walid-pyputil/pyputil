#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    CHECKSUM UTILITIES
==================================

Comprehensive checksum and hashing utilities for file integrity
verification, content-based caching, and secure hash generation.

This module provides:
- Multiple hash algorithms (MD5, SHA1, SHA256, SHA512, BLAKE2)
- Streaming hash computation for large files
- Parallel hashing for multiple files
- Checksum verification and comparison
- Content-based cache key generation
- String and bytes hashing utilities

Supported Algorithms:
- MD5: Fast, 128-bit (legacy, not for security)
- SHA1: 160-bit (legacy, not for security)
- SHA224: 224-bit SHA2
- SHA256: 256-bit SHA2 (recommended)
- SHA384: 384-bit SHA2
- SHA512: 512-bit SHA2
- SHA3_256: 256-bit SHA3
- SHA3_512: 512-bit SHA3
- BLAKE2b: 512-bit BLAKE2 (fast, secure)
- BLAKE2s: 256-bit BLAKE2 (fast, secure)
- XXH64: 64-bit xxHash (extremely fast, non-cryptographic)
- XXH128: 128-bit xxHash (extremely fast, non-cryptographic)
"""

import os
import sys
import hashlib
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union, BinaryIO
import functools
import io

# Try to import optional hash libraries
try:
    import xxhash
    XXHASH_AVAILABLE = True
except ImportError:
    XXHASH_AVAILABLE = False

try:
    import blake2
    BLAKE2_AVAILABLE = True
except ImportError:
    BLAKE2_AVAILABLE = hasattr(hashlib, 'blake2b')


# ============================================================================
# Hash Algorithm Enumeration
# ============================================================================

class HashAlgorithm(Enum):
    """
    Hash algorithm enumeration for checksum generation.
    
    This enum provides a unified interface for selecting hash algorithms
    across different Python versions and optional dependencies.
    
    Attributes
    ----------
    MD5 : str
        MD5 algorithm - 128-bit, fast, not cryptographically secure.
        Available on all platforms. Value: "md5"
    SHA1 : str
        SHA-1 algorithm - 160-bit, not cryptographically secure.
        Available on all platforms. Value: "sha1"
    SHA224 : str
        SHA-224 algorithm - 224-bit SHA2 family.
        Available on all platforms. Value: "sha224"
    SHA256 : str
        SHA-256 algorithm - 256-bit SHA2 family.
        Recommended for general use. Value: "sha256"
    SHA384 : str
        SHA-384 algorithm - 384-bit SHA2 family. Value: "sha384"
    SHA512 : str
        SHA-512 algorithm - 512-bit SHA2 family. Value: "sha512"
    SHA3_256 : str
        SHA3-256 algorithm - 256-bit SHA3 family.
        Available Python 3.6+. Value: "sha3_256"
    SHA3_512 : str
        SHA3-512 algorithm - 512-bit SHA3 family.
        Available Python 3.6+. Value: "sha3_512"
    BLAKE2B : str
        BLAKE2b algorithm - 512-bit, faster than SHA3.
        Available Python 3.6+ or blake2 package. Value: "blake2b"
    BLAKE2S : str
        BLAKE2s algorithm - 256-bit, optimized for 32-bit.
        Available Python 3.6+ or blake2 package. Value: "blake2s"
    XXH64 : str
        xxHash 64-bit - extremely fast non-cryptographic hash.
        Requires xxhash package. Value: "xxh64"
    XXH128 : str
        xxHash 128-bit - extremely fast non-cryptographic hash.
        Requires xxhash package. Value: "xxh128"
    
    Examples
    --------
    >>> from cimporter.utils.checksum import HashAlgorithm
    >>> 
    >>> # Check available algorithms
    >>> available = HashAlgorithm.get_available_algorithms()
    >>> print(f"Available: {[a.value for a in available]}")
    >>> 
    >>> # Get algorithm info
    >>> algo = HashAlgorithm.SHA256
    >>> print(f"{algo.value}: {algo.get_digest_size()} bytes, {algo.is_cryptographic()}")
    >>> 
    >>> # Create hasher
    >>> hasher = algo.create_hasher()
    >>> hasher.update(b"data")
    >>> print(hasher.hexdigest())
    """
    
    MD5 = "md5"
    SHA1 = "sha1"
    SHA224 = "sha224"
    SHA256 = "sha256"
    SHA384 = "sha384"
    SHA512 = "sha512"
    SHA3_256 = "sha3_256"
    SHA3_512 = "sha3_512"
    BLAKE2B = "blake2b"
    BLAKE2S = "blake2s"
    XXH64 = "xxh64"
    XXH128 = "xxh128"
    
    def is_available(self) -> bool:
        """
        Check if this algorithm is available on the current system.
        
        Some algorithms require specific Python versions or optional
        packages (xxhash, blake2).
        
        Returns
        -------
        bool
            True if the algorithm can be used.
        
        Examples
        --------
        >>> if HashAlgorithm.XXH64.is_available():
        ...     print("xxHash is available for fast hashing")
        """
        if self in (self.XXH64, self.XXH128):
            return XXHASH_AVAILABLE
        
        if self in (self.BLAKE2B, self.BLAKE2S):
            return BLAKE2_AVAILABLE
        
        if self in (self.SHA3_256, self.SHA3_512):
            return hasattr(hashlib, 'sha3_256')
        
        # Basic algorithms always available
        return True
    
    def create_hasher(self, **kwargs) -> Any:
        """
        Create a new hash object for this algorithm.
        
        Parameters
        ----------
        **kwargs : Any
            Additional arguments for the hash constructor.
            For BLAKE2: key, salt, person, digest_size, etc.
            For xxHash: seed.
            
        Returns
        -------
        Any
            Hash object with update() and digest() methods.
            
        Raises
        ------
        ValueError
            If the algorithm is not available.
        
        Examples
        --------
        >>> hasher = HashAlgorithm.SHA256.create_hasher()
        >>> hasher.update(b"Hello, World!")
        >>> print(hasher.hexdigest())
        >>> 
        >>> # BLAKE2 with custom parameters
        >>> hasher = HashAlgorithm.BLAKE2B.create_hasher(
        ...     key=b"secret-key",
        ...     digest_size=32
        ... )
        """
        if not self.is_available():
            raise ValueError(f"Hash algorithm '{self.value}' is not available")
        
        if self == self.MD5:
            return hashlib.md5(**kwargs)
        elif self == self.SHA1:
            return hashlib.sha1(**kwargs)
        elif self == self.SHA224:
            return hashlib.sha224(**kwargs)
        elif self == self.SHA256:
            return hashlib.sha256(**kwargs)
        elif self == self.SHA384:
            return hashlib.sha384(**kwargs)
        elif self == self.SHA512:
            return hashlib.sha512(**kwargs)
        elif self == self.SHA3_256:
            return hashlib.sha3_256(**kwargs)
        elif self == self.SHA3_512:
            return hashlib.sha3_512(**kwargs)
        elif self == self.BLAKE2B:
            if hasattr(hashlib, 'blake2b'):
                return hashlib.blake2b(**kwargs)
            else:
                return blake2.BLAKE2b(**kwargs)
        elif self == self.BLAKE2S:
            if hasattr(hashlib, 'blake2s'):
                return hashlib.blake2s(**kwargs)
            else:
                return blake2.BLAKE2s(**kwargs)
        elif self == self.XXH64:
            seed = kwargs.get('seed', 0)
            return xxhash.xxh64(seed=seed)
        elif self == self.XXH128:
            seed = kwargs.get('seed', 0)
            return xxhash.xxh128(seed=seed)
        
        raise ValueError(f"Unknown algorithm: {self}")
    
    def get_digest_size(self) -> int:
        """
        Get the digest size in bytes for this algorithm.
        
        Returns
        -------
        int
            Size of the hash digest in bytes.
        
        Examples
        --------
        >>> algo = HashAlgorithm.SHA256
        >>> print(f"Digest size: {algo.get_digest_size()} bytes ({algo.get_digest_size() * 8} bits)")
        32 bytes (256 bits)
        """
        sizes = {
            self.MD5: 16,
            self.SHA1: 20,
            self.SHA224: 28,
            self.SHA256: 32,
            self.SHA384: 48,
            self.SHA512: 64,
            self.SHA3_256: 32,
            self.SHA3_512: 64,
            self.BLAKE2B: 64,
            self.BLAKE2S: 32,
            self.XXH64: 8,
            self.XXH128: 16,
        }
        return sizes.get(self, 0)
    
    def get_block_size(self) -> int:
        """
        Get the internal block size in bytes for this algorithm.
        
        Returns
        -------
        int
            Block size in bytes.
        """
        sizes = {
            self.MD5: 64,
            self.SHA1: 64,
            self.SHA224: 64,
            self.SHA256: 64,
            self.SHA384: 128,
            self.SHA512: 128,
            self.SHA3_256: 136,
            self.SHA3_512: 72,
            self.BLAKE2B: 128,
            self.BLAKE2S: 64,
            self.XXH64: 32,
            self.XXH128: 32,
        }
        return sizes.get(self, 0)
    
    def is_cryptographic(self) -> bool:
        """
        Check if this algorithm is cryptographically secure.
        
        Cryptographic hashes are collision-resistant and suitable
        for security-sensitive applications. Non-cryptographic hashes
        (like xxHash) are faster but should not be used for security.
        
        Returns
        -------
        bool
            True if the algorithm is cryptographically secure.
        
        Examples
        --------
        >>> if HashAlgorithm.SHA256.is_cryptographic():
        ...     print("SHA256 is secure for cryptographic use")
        >>> if not HashAlgorithm.XXH64.is_cryptographic():
        ...     print("xxHash is fast but not for security")
        """
        return self not in (self.XXH64, self.XXH128)
    
    def is_recommended(self) -> bool:
        """
        Check if this algorithm is recommended for general use.
        
        Returns
        -------
        bool
            True if recommended (BLAKE2 or SHA256).
        """
        return self in (self.SHA256, self.BLAKE2B, self.BLAKE2S)
    
    def get_name(self) -> str:
        """
        Get the human-readable name of the algorithm.
        
        Returns
        -------
        str
            Algorithm name.
        """
        names = {
            self.MD5: "MD5",
            self.SHA1: "SHA-1",
            self.SHA224: "SHA-224",
            self.SHA256: "SHA-256",
            self.SHA384: "SHA-384",
            self.SHA512: "SHA-512",
            self.SHA3_256: "SHA3-256",
            self.SHA3_512: "SHA3-512",
            self.BLAKE2B: "BLAKE2b",
            self.BLAKE2S: "BLAKE2s",
            self.XXH64: "xxHash64",
            self.XXH128: "xxHash128",
        }
        return names.get(self, self.value)
    
    @classmethod
    def get_available_algorithms(cls) -> List["HashAlgorithm"]:
        """
        Get list of all available algorithms on the current system.
        
        Returns
        -------
        List[HashAlgorithm]
            List of available algorithms.
        
        Examples
        --------
        >>> available = HashAlgorithm.get_available_algorithms()
        >>> for algo in available:
        ...     print(f"- {algo.get_name()} ({algo.value})")
        """
        return [algo for algo in cls if algo.is_available()]
    
    @classmethod
    def get_recommended(cls) -> "HashAlgorithm":
        """
        Get the recommended algorithm for the current system.
        
        Prefers BLAKE2b if available, falls back to SHA256.
        
        Returns
        -------
        HashAlgorithm
            Recommended algorithm.
        """
        if cls.BLAKE2B.is_available():
            return cls.BLAKE2B
        return cls.SHA256
    
    @classmethod
    def get_fast(cls) -> "HashAlgorithm":
        """
        Get the fastest available algorithm (non-cryptographic).
        
        Prefers xxHash64 if available, falls back to MD5.
        
        Returns
        -------
        HashAlgorithm
            Fastest algorithm.
        """
        if cls.XXH64.is_available():
            return cls.XXH64
        return cls.MD5
    
    def __str__(self) -> str:
        """String representation."""
        return self.get_name()


 #============================================================================
# Checksum Error
# ============================================================================

class ChecksumError(Exception):
    """
    Exception raised for checksum-related errors.
    
    This exception is raised when checksum verification fails,
    when a file cannot be read, or when a hash algorithm is unavailable.
    
    Attributes
    ----------
    message : str
        Error message describing what went wrong.
    path : Optional[Path]
        File path that caused the error, if applicable.
    expected : Optional[str]
        Expected checksum value, if applicable.
    actual : Optional[str]
        Actual checksum value, if applicable.
    algorithm : Optional[HashAlgorithm]
        Hash algorithm being used.
    
    Examples
    --------
    >>> try:
    ...     verify_checksum("file.txt", "abc123", algorithm=HashAlgorithm.SHA256)
    ... except ChecksumError as e:
    ...     print(f"Checksum mismatch: expected {e.expected}, got {e.actual}")
    """
    
    def __init__(
        self,
        message: str,
        path: Optional[Path] = None,
        expected: Optional[str] = None,
        actual: Optional[str] = None,
        algorithm: Optional[HashAlgorithm] = None,
    ):
        self.message = message
        self.path = path
        self.expected = expected
        self.actual = actual
        self.algorithm = algorithm
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        """Format the error message with context."""
        parts = [self.message]
        if self.path:
            parts.append(f"path={self.path}")
        if self.algorithm:
            parts.append(f"algorithm={self.algorithm.value}")
        if self.expected:
            parts.append(f"expected={self.expected}")
        if self.actual:
            parts.append(f"actual={self.actual}")
        return " ".join(parts)



# ============================================================================
# Checksum Result
# ============================================================================

@dataclass
class ChecksumResult:
    """
    Result of a checksum computation.
    
    This dataclass contains the computed hash along with metadata
    about the computation such as file size and processing time.
    
    Attributes
    ----------
    path : Path
        Path to the file that was hashed.
    algorithm : HashAlgorithm
        Hash algorithm used.
    checksum : str
        Hexadecimal digest string.
    digest : bytes
        Raw digest bytes.
    file_size : int
        Size of the file in bytes.
    compute_time : float
        Time taken to compute the hash in seconds.
    throughput_mbps : float
        Throughput in megabytes per second.
    chunk_count : int
        Number of chunks processed.
    verified : bool
        Whether the checksum was verified (if applicable).
    
    Examples
    --------
    >>> result = compute_checksum(Path("large_file.dat"), algorithm=HashAlgorithm.SHA256)
    >>> print(f"SHA256: {result.checksum}")
    >>> print(f"Size: {result.file_size / (1024**2):.1f} MB")
    >>> print(f"Time: {result.compute_time:.3f}s")
    >>> print(f"Speed: {result.throughput_mbps:.1f} MB/s")
    """
    
    path: Path
    algorithm: HashAlgorithm
    checksum: str
    digest: bytes
    file_size: int
    compute_time: float
    throughput_mbps: float = 0.0
    chunk_count: int = 0
    verified: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "path": str(self.path),
            "algorithm": self.algorithm.value,
            "checksum": self.checksum,
            "file_size": self.file_size,
            "file_size_mb": self.file_size / (1024 * 1024),
            "compute_time": self.compute_time,
            "throughput_mbps": self.throughput_mbps,
            "chunk_count": self.chunk_count,
            "verified": self.verified,
        }
    
    def __str__(self) -> str:
        """String representation."""
        return f"{self.checksum} ({self.algorithm.value})"
    
    def __eq__(self, other: Any) -> bool:
        """Compare checksums for equality."""
        if isinstance(other, ChecksumResult):
            return self.checksum == other.checksum and self.algorithm == other.algorithm
        elif isinstance(other, str):
            return self.checksum == other
        return False


# ============================================================================
# Streaming Hash Reader
# ============================================================================

class StreamingHashReader:
    """
    Streaming file reader that computes hash while reading.
    
    This class provides a file-like object that computes a hash of
    the data as it is read, allowing efficient single-pass processing.
    
    Parameters
    ----------
    file_path : Path
        Path to the file to read.
    algorithm : HashAlgorithm
        Hash algorithm to use.
    buffer_size : int
        Buffer size for reading (default: 8192).
    progress_callback : Optional[Callable[[int, int], None]]
        Optional callback for progress reporting.
        Called with (bytes_read, total_bytes).
    
    Attributes
    ----------
    file_path : Path
        File path.
    algorithm : HashAlgorithm
        Hash algorithm.
    file_size : int
        Total file size in bytes.
    bytes_read : int
        Number of bytes read so far.
    hasher : Any
        Hash object.
    _file : BinaryIO
        Open file handle.
    
    Examples
    --------
    >>> reader = StreamingHashReader(Path("data.bin"), HashAlgorithm.SHA256)
    >>> 
    >>> # Read and hash simultaneously
    >>> data = reader.read(1024)
    >>> while data:
    ...     process(data)
    ...     data = reader.read(1024)
    >>> 
    >>> # Get the final hash
    >>> result = reader.get_result()
    >>> print(f"Checksum: {result.checksum}")
    >>> reader.close()
    >>> 
    >>> # Use as context manager
    >>> with StreamingHashReader(Path("data.bin"), HashAlgorithm.SHA256) as reader:
    ...     content = reader.read()
    ...     checksum = reader.get_checksum()
    """
    
    def __init__(
        self,
        file_path: Path,
        algorithm: HashAlgorithm = HashAlgorithm.SHA256,
        buffer_size: int = 8192,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ):
        self.file_path = Path(file_path)
        self.algorithm = algorithm
        self.buffer_size = buffer_size
        self.progress_callback = progress_callback
        
        if not self.file_path.exists():
            raise FileNotFoundError(f"File not found: {self.file_path}")
        
        self.file_size = self.file_path.stat().st_size
        self.bytes_read = 0
        self.start_time = time.time()
        
        self.hasher = algorithm.create_hasher()
        self._file: Optional[BinaryIO] = None
        self._closed = False
    
    def open(self) -> "StreamingHashReader":
        """
        Open the file for reading.
        
        Returns
        -------
        StreamingHashReader
            Self for method chaining.
        """
        if self._closed:
            raise ValueError("Reader is closed")
        if self._file is None:
            self._file = open(self.file_path, "rb")
        return self
    
    def read(self, size: Optional[int] = None) -> bytes:
        """
        Read data from the file and update the hash.
        
        Parameters
        ----------
        size : Optional[int]
            Number of bytes to read. If None, read until EOF.
            
        Returns
        -------
        bytes
            Data read from the file.
        """
        if self._file is None:
            self.open()
        
        if size is None or size < 0:
            data = self._file.read()
        else:
            data = self._file.read(size)
        
        if data:
            self.hasher.update(data)
            self.bytes_read += len(data)
            
            if self.progress_callback:
                self.progress_callback(self.bytes_read, self.file_size)
        
        return data
    
    def readinto(self, buffer: bytearray) -> int:
        """
        Read data into a pre-allocated buffer.
        
        Parameters
        ----------
        buffer : bytearray
            Buffer to read into.
            
        Returns
        -------
        int
            Number of bytes read.
        """
        if self._file is None:
            self.open()
        
        data = self._file.readinto(buffer)
        
        if data:
            self.hasher.update(buffer[:data])
            self.bytes_read += data
            
            if self.progress_callback:
                self.progress_callback(self.bytes_read, self.file_size)
        
        return data
    
    def readline(self, limit: int = -1) -> bytes:
        """
        Read a single line from the file.
        
        Parameters
        ----------
        limit : int
            Maximum number of bytes to read.
            
        Returns
        -------
        bytes
            Line data including newline.
        """
        if self._file is None:
            self.open()
        
        data = self._file.readline(limit)
        
        if data:
            self.hasher.update(data)
            self.bytes_read += len(data)
            
            if self.progress_callback:
                self.progress_callback(self.bytes_read, self.file_size)
        
        return data
    
    def readlines(self, hint: int = -1) -> List[bytes]:
        """
        Read all lines from the file.
        
        Parameters
        ----------
        hint : int
            Approximate number of bytes to read.
            
        Returns
        -------
        List[bytes]
            List of lines.
        """
        lines = []
        total = 0
        
        while True:
            line = self.readline()
            if not line:
                break
            lines.append(line)
            total += len(line)
            if hint > 0 and total >= hint:
                break
        
        return lines
    
    def seek(self, offset: int, whence: int = 0) -> int:
        """
        Seek to a position in the file.
        
        Note: This does not reset the hash. Use with caution.
        
        Parameters
        ----------
        offset : int
            Offset in bytes.
        whence : int
            Reference point (0=start, 1=current, 2=end).
            
        Returns
        -------
        int
            New absolute position.
        """
        if self._file is None:
            self.open()
        return self._file.seek(offset, whence)
    
    def tell(self) -> int:
        """
        Get current position in the file.
        
        Returns
        -------
        int
            Current position.
        """
        if self._file is None:
            return 0
        return self._file.tell()
    
    def get_digest(self) -> bytes:
        """
        Get the raw digest of the data read so far.
        
        Returns
        -------
        bytes
            Raw digest bytes.
        """
        return self.hasher.digest()
    
    def get_hexdigest(self) -> str:
        """
        Get the hexadecimal digest of the data read so far.
        
        Returns
        -------
        str
            Hexadecimal digest string.
        """
        return self.hasher.hexdigest()
    
    def get_checksum(self) -> str:
        """
        Get the checksum (hexadecimal digest).
        
        Returns
        -------
        str
            Checksum string.
        """
        return self.get_hexdigest()
    
    def get_result(self) -> ChecksumResult:
        """
        Get the complete checksum result.
        
        Returns
        -------
        ChecksumResult
            Result with metadata.
        """
        compute_time = time.time() - self.start_time
        throughput = (self.bytes_read / (1024 * 1024)) / compute_time if compute_time > 0 else 0
        
        return ChecksumResult(
            path=self.file_path,
            algorithm=self.algorithm,
            checksum=self.get_hexdigest(),
            digest=self.get_digest(),
            file_size=self.file_size,
            compute_time=compute_time,
            throughput_mbps=throughput,
            chunk_count=(self.bytes_read // self.buffer_size) + 1,
        )
    
    def close(self) -> None:
        """
        Close the file handle.
        """
        if self._file:
            self._file.close()
            self._file = None
        self._closed = True
    
    @property
    def closed(self) -> bool:
        """Check if the reader is closed."""
        return self._closed
    
    def __enter__(self) -> "StreamingHashReader":
        """Context manager entry."""
        return self.open()
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
    
    def __iter__(self) -> Iterator[bytes]:
        """Iterate over chunks of the file."""
        return self
    
    def __next__(self) -> bytes:
        """Get next chunk of data."""
        data = self.read(self.buffer_size)
        if not data:
            raise StopIteration
        return data


# ============================================================================
# Core Hash Functions
# ============================================================================

def compute_file_hash(
    file_path: Union[str, Path],
    algorithm: HashAlgorithm = HashAlgorithm.SHA256,
    buffer_size: int = 8192,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> ChecksumResult:
    """
    Compute the hash of a file.
    
    This function computes the cryptographic or non-cryptographic hash
    of a file using the specified algorithm. It processes the file in
    chunks to handle large files efficiently.
    
    Parameters
    ----------
    file_path : Union[str, Path]
        Path to the file to hash.
    algorithm : HashAlgorithm
        Hash algorithm to use (default: SHA256).
    buffer_size : int
        Buffer size for reading in bytes (default: 8192).
    progress_callback : Optional[Callable[[int, int], None]]
        Optional callback for progress reporting.
        Called with (bytes_read, total_bytes).
        
    Returns
    -------
    ChecksumResult
        Result containing the hash and metadata.
        
    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ChecksumError
        If the hash algorithm is unavailable or an error occurs.
        
    Examples
    --------
    >>> result = compute_file_hash("large_file.dat", HashAlgorithm.SHA256)
    >>> print(f"SHA256: {result.checksum}")
    >>> print(f"Time: {result.compute_time:.3f}s")
    >>> 
    >>> # With progress callback
    >>> def progress(read, total):
    ...     print(f"Progress: {read}/{total} bytes ({100*read/total:.1f}%)")
    >>> 
    >>> result = compute_file_hash("file.dat", progress_callback=progress)
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    if not algorithm.is_available():
        raise ChecksumError(
            f"Hash algorithm '{algorithm.value}' is not available",
            path=path,
            algorithm=algorithm,
        )
    
    with StreamingHashReader(
        path,
        algorithm=algorithm,
        buffer_size=buffer_size,
        progress_callback=progress_callback,
    ) as reader:
        # Read entire file
        while reader.read(buffer_size):
            pass
        
        return reader.get_result()


def compute_checksum(
    file_path: Union[str, Path],
    algorithm: HashAlgorithm = HashAlgorithm.SHA256,
    buffer_size: int = 8192,
) -> str:
    """
    Compute the checksum (hexadecimal hash) of a file.
    
    This is a convenience wrapper around compute_file_hash that returns
    just the checksum string.
    
    Parameters
    ----------
    file_path : Union[str, Path]
        Path to the file.
    algorithm : HashAlgorithm
        Hash algorithm to use (default: SHA256).
    buffer_size : int
        Buffer size for reading (default: 8192).
        
    Returns
    -------
    str
        Hexadecimal checksum string.
        
    Examples
    --------
    >>> checksum = compute_checksum("source.c")
    >>> print(f"Checksum: {checksum}")
    """
    result = compute_file_hash(file_path, algorithm, buffer_size)
    return result.checksum


def compute_string_hash(
    data: str,
    algorithm: HashAlgorithm = HashAlgorithm.SHA256,
    encoding: str = "utf-8",
) -> str:
    """
    Compute the hash of a string.
    
    Parameters
    ----------
    data : str
        String to hash.
    algorithm : HashAlgorithm
        Hash algorithm to use.
    encoding : str
        Character encoding (default: utf-8).
        
    Returns
    -------
    str
        Hexadecimal hash string.
        
    Examples
    --------
    >>> hash_value = compute_string_hash("Hello, World!", HashAlgorithm.SHA256)
    >>> print(hash_value)
    """
    if not algorithm.is_available():
        raise ChecksumError(f"Algorithm '{algorithm.value}' not available", algorithm=algorithm)
    
    hasher = algorithm.create_hasher()
    hasher.update(data.encode(encoding))
    return hasher.hexdigest()


def compute_bytes_hash(
    data: bytes,
    algorithm: HashAlgorithm = HashAlgorithm.SHA256,
) -> str:
    """
    Compute the hash of bytes data.
    
    Parameters
    ----------
    data : bytes
        Bytes to hash.
    algorithm : HashAlgorithm
        Hash algorithm to use.
        
    Returns
    -------
    str
        Hexadecimal hash string.
        
    Examples
    --------
    >>> hash_value = compute_bytes_hash(b"\\x00\\x01\\x02", HashAlgorithm.SHA256)
    >>> print(hash_value)
    """
    if not algorithm.is_available():
        raise ChecksumError(f"Algorithm '{algorithm.value}' not available", algorithm=algorithm)
    
    hasher = algorithm.create_hasher()
    hasher.update(data)
    return hasher.hexdigest()


def compute_stream_hash(
    stream: BinaryIO,
    algorithm: HashAlgorithm = HashAlgorithm.SHA256,
    buffer_size: int = 8192,
) -> ChecksumResult:
    """
    Compute the hash of a file-like stream.
    
    Parameters
    ----------
    stream : BinaryIO
        Binary stream to read from.
    algorithm : HashAlgorithm
        Hash algorithm to use.
    buffer_size : int
        Buffer size for reading.
        
    Returns
    -------
    ChecksumResult
        Result with hash and metadata.
        
    Examples
    --------
    >>> import io
    >>> data = io.BytesIO(b"Hello, World!")
    >>> result = compute_stream_hash(data)
    >>> print(result.checksum)
    """
    if not algorithm.is_available():
        raise ChecksumError(f"Algorithm '{algorithm.value}' not available", algorithm=algorithm)
    
    start_time = time.time()
    hasher = algorithm.create_hasher()
    bytes_read = 0
    chunk_count = 0
    
    while True:
        chunk = stream.read(buffer_size)
        if not chunk:
            break
        hasher.update(chunk)
        bytes_read += len(chunk)
        chunk_count += 1
    
    compute_time = time.time() - start_time
    throughput = (bytes_read / (1024 * 1024)) / compute_time if compute_time > 0 else 0
    
    return ChecksumResult(
        path=Path("<stream>"),
        algorithm=algorithm,
        checksum=hasher.hexdigest(),
        digest=hasher.digest(),
        file_size=bytes_read,
        compute_time=compute_time,
        throughput_mbps=throughput,
        chunk_count=chunk_count,
    )


# ============================================================================
# Verification Functions
# ============================================================================

def verify_checksum(
    file_path: Union[str, Path],
    expected_checksum: str,
    algorithm: HashAlgorithm = HashAlgorithm.SHA256,
    buffer_size: int = 8192,
) -> bool:
    """
    Verify that a file matches an expected checksum.
    
    Parameters
    ----------
    file_path : Union[str, Path]
        Path to the file to verify.
    expected_checksum : str
        Expected hexadecimal checksum.
    algorithm : HashAlgorithm
        Hash algorithm to use.
    buffer_size : int
        Buffer size for reading.
        
    Returns
    -------
    bool
        True if the checksum matches.
        
    Raises
    ------
    ChecksumError
        If the checksum does not match.
        
    Examples
    --------
    >>> try:
    ...     verify_checksum("downloaded.zip", "abc123...", HashAlgorithm.SHA256)
    ...     print("Checksum verified!")
    ... except ChecksumError as e:
    ...     print(f"Verification failed: {e}")
    """
    path = Path(file_path)
    actual_result = compute_file_hash(path, algorithm, buffer_size)
    actual = actual_result.checksum
    
    # Normalize expected (lowercase, no spaces)
    expected = expected_checksum.strip().lower()
    
    if actual != expected:
        raise ChecksumError(
            "Checksum verification failed",
            path=path,
            expected=expected,
            actual=actual,
            algorithm=algorithm,
        )
    
    return True


def compare_files(
    file1: Union[str, Path],
    file2: Union[str, Path],
    algorithm: HashAlgorithm = HashAlgorithm.SHA256,
) -> bool:
    """
    Compare two files by their checksums.
    
    This is more efficient than byte-by-byte comparison for large files.
    
    Parameters
    ----------
    file1 : Union[str, Path]
        Path to first file.
    file2 : Union[str, Path]
        Path to second file.
    algorithm : HashAlgorithm
        Hash algorithm to use.
        
    Returns
    -------
    bool
        True if files have identical content.
        
    Examples
    --------
    >>> if compare_files("file1.txt", "file2.txt"):
    ...     print("Files are identical")
    """
    path1 = Path(file1)
    path2 = Path(file2)
    
    # Quick size check
    if path1.stat().st_size != path2.stat().st_size:
        return False
    
    checksum1 = compute_checksum(path1, algorithm)
    checksum2 = compute_checksum(path2, algorithm)
    
    return checksum1 == checksum2


# ============================================================================
# Parallel Hashing
# ============================================================================

@dataclass
class BatchChecksumResult:
    """
    Result of batch checksum computation.
    
    Attributes
    ----------
    results : Dict[Path, ChecksumResult]
        Mapping of file paths to their checksum results.
    total_files : int
        Total number of files processed.
    total_bytes : int
        Total bytes processed.
    total_time : float
        Total wall-clock time.
    failed : Dict[Path, Exception]
        Files that failed to process with their errors.
    """
    
    results: Dict[Path, ChecksumResult] = field(default_factory=dict)
    total_files: int = 0
    total_bytes: int = 0
    total_time: float = 0.0
    failed: Dict[Path, Exception] = field(default_factory=dict)
    
    @property
    def success_count(self) -> int:
        """Number of successfully processed files."""
        return len(self.results)
    
    @property
    def failure_count(self) -> int:
        """Number of failed files."""
        return len(self.failed)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_files": self.total_files,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_bytes": self.total_bytes,
            "total_mb": self.total_bytes / (1024 * 1024),
            "total_time": self.total_time,
            "throughput_mbps": (self.total_bytes / (1024 * 1024)) / self.total_time if self.total_time > 0 else 0,
            "results": {str(k): v.to_dict() for k, v in self.results.items()},
            "failed": {str(k): str(v) for k, v in self.failed.items()},
        }


def compute_checksums_parallel(
    file_paths: List[Union[str, Path]],
    algorithm: HashAlgorithm = HashAlgorithm.SHA256,
    max_workers: Optional[int] = None,
    use_processes: bool = False,
    progress_callback: Optional[Callable[[int, int, Path], None]] = None,
) -> BatchChecksumResult:
    """
    Compute checksums for multiple files in parallel.
    
    Parameters
    ----------
    file_paths : List[Union[str, Path]]
        List of file paths to process.
    algorithm : HashAlgorithm
        Hash algorithm to use.
    max_workers : Optional[int]
        Maximum number of worker threads/processes.
    use_processes : bool
        Use ProcessPoolExecutor instead of ThreadPoolExecutor.
        Better for CPU-bound hashing (cryptographic algorithms).
    progress_callback : Optional[Callable[[int, int, Path], None]]
        Progress callback receiving (completed, total, current_file).
        
    Returns
    -------
    BatchChecksumResult
        Batch result with all checksums.
        
    Examples
    --------
    >>> files = list(Path("src").glob("*.c"))
    >>> result = compute_checksums_parallel(files, algorithm=HashAlgorithm.SHA256)
    >>> print(f"Processed {result.success_count} files in {result.total_time:.2f}s")
    >>> for path, checksum_result in result.results.items():
    ...     print(f"{path.name}: {checksum_result.checksum}")
    """
    paths = [Path(p) for p in file_paths]
    paths = [p for p in paths if p.exists() and p.is_file()]
    
    if not paths:
        return BatchChecksumResult()
    
    result = BatchChecksumResult(total_files=len(paths))
    start_time = time.time()
    
    executor_class = ProcessPoolExecutor if use_processes else ThreadPoolExecutor
    max_workers = max_workers or min(8, len(paths))
    
    def hash_file(path: Path) -> Tuple[Path, Optional[ChecksumResult], Optional[Exception]]:
        """Hash a single file."""
        try:
            res = compute_file_hash(path, algorithm)
            return path, res, None
        except Exception as e:
            return path, None, e
    
    with executor_class(max_workers=max_workers) as executor:
        futures = {executor.submit(hash_file, p): p for p in paths}
        completed = 0
        
        for future in as_completed(futures):
            path, res, error = future.result()
            completed += 1
            
            if error:
                result.failed[path] = error
            else:
                result.results[path] = res
                result.total_bytes += res.file_size
            
            if progress_callback:
                progress_callback(completed, len(paths), path)
    
    result.total_time = time.time() - start_time
    return result


# ============================================================================
# Incremental Hash Builder
# ============================================================================

class IncrementalHasher:
    """
    Incremental hash builder for streaming or multi-part data.
    
    This class allows building a hash incrementally from multiple
    sources or chunks of data.
    
    Parameters
    ----------
    algorithm : HashAlgorithm
        Hash algorithm to use.
        
    Attributes
    ----------
    algorithm : HashAlgorithm
        Hash algorithm.
    hasher : Any
        Underlying hash object.
    total_bytes : int
        Total bytes hashed so far.
    
    Examples
    --------
    >>> hasher = IncrementalHasher(HashAlgorithm.SHA256)
    >>> hasher.update(b"First part")
    >>> hasher.update(b"Second part")
    >>> hasher.update_file(Path("data.bin"))
    >>> checksum = hasher.hexdigest()
    >>> print(f"Total: {hasher.total_bytes} bytes, SHA256: {checksum}")
    """
    
    def __init__(self, algorithm: HashAlgorithm = HashAlgorithm.SHA256):
        if not algorithm.is_available():
            raise ChecksumError(f"Algorithm '{algorithm.value}' not available", algorithm=algorithm)
        
        self.algorithm = algorithm
        self.hasher = algorithm.create_hasher()
        self.total_bytes = 0
    
    def update(self, data: Union[bytes, str, bytearray, memoryview]) -> "IncrementalHasher":
        """
        Update the hash with data.
        
        Parameters
        ----------
        data : Union[bytes, str, bytearray, memoryview]
            Data to add to the hash.
            
        Returns
        -------
        IncrementalHasher
            Self for method chaining.
        """
        if isinstance(data, str):
            data = data.encode("utf-8")
        
        self.hasher.update(data)
        self.total_bytes += len(data)
        return self
    
    def update_file(
        self,
        file_path: Union[str, Path],
        buffer_size: int = 8192,
    ) -> "IncrementalHasher":
        """
        Update the hash with the contents of a file.
        
        Parameters
        ----------
        file_path : Union[str, Path]
            Path to the file.
        buffer_size : int
            Buffer size for reading.
            
        Returns
        -------
        IncrementalHasher
            Self for method chaining.
        """
        path = Path(file_path)
        
        with open(path, "rb") as f:
            while True:
                chunk = f.read(buffer_size)
                if not chunk:
                    break
                self.hasher.update(chunk)
                self.total_bytes += len(chunk)
        
        return self
    
    def update_stream(
        self,
        stream: BinaryIO,
        buffer_size: int = 8192,
    ) -> "IncrementalHasher":
        """
        Update the hash from a file-like stream.
        
        Parameters
        ----------
        stream : BinaryIO
            Binary stream to read from.
        buffer_size : int
            Buffer size for reading.
            
        Returns
        -------
        IncrementalHasher
            Self for method chaining.
        """
        while True:
            chunk = stream.read(buffer_size)
            if not chunk:
                break
            self.hasher.update(chunk)
            self.total_bytes += len(chunk)
        
        return self
    
    def update_files(
        self,
        file_paths: List[Union[str, Path]],
        buffer_size: int = 8192,
    ) -> "IncrementalHasher":
        """
        Update the hash with multiple files.
        
        Parameters
        ----------
        file_paths : List[Union[str, Path]]
            List of file paths.
        buffer_size : int
            Buffer size for reading.
            
        Returns
        -------
        IncrementalHasher
            Self for method chaining.
        """
        for path in file_paths:
            self.update_file(path, buffer_size)
        return self
    
    def digest(self) -> bytes:
        """
        Get the raw digest.
        
        Returns
        -------
        bytes
            Raw digest bytes.
        """
        return self.hasher.digest()
    
    def hexdigest(self) -> str:
        """
        Get the hexadecimal digest.
        
        Returns
        -------
        str
            Hexadecimal digest string.
        """
        return self.hasher.hexdigest()
    
    def copy(self) -> "IncrementalHasher":
        """
        Create a copy of this hasher.
        
        Returns
        -------
        IncrementalHasher
            New hasher with same state.
        """
        new_hasher = IncrementalHasher(self.algorithm)
        new_hasher.hasher = self.hasher.copy()
        new_hasher.total_bytes = self.total_bytes
        return new_hasher
    
    def reset(self) -> "IncrementalHasher":
        """
        Reset the hasher to initial state.
        
        Returns
        -------
        IncrementalHasher
            Self for method chaining.
        """
        self.hasher = self.algorithm.create_hasher()
        self.total_bytes = 0
        return self
    
    def __str__(self) -> str:
        """String representation."""
        return f"IncrementalHasher({self.algorithm.value}, {self.total_bytes} bytes)"


# ============================================================================
# Convenience Functions
# ============================================================================

def hash_string(data: str, algorithm: str = "sha256") -> str:
    """
    Convenience function to hash a string.
    
    Parameters
    ----------
    data : str
        String to hash.
    algorithm : str
        Algorithm name (e.g., 'sha256', 'md5', 'blake2b').
        
    Returns
    -------
    str
        Hexadecimal hash.
        
    Examples
    --------
    >>> hash_string("Hello", "sha256")
    '185f8db32271fe25f561a6fc938b2e264306ec304eda518007d1764826381969'
    """
    algo = HashAlgorithm(algorithm.lower())
    return compute_string_hash(data, algo)


def hash_file(file_path: Union[str, Path], algorithm: str = "sha256") -> str:
    """
    Convenience function to hash a file.
    
    Parameters
    ----------
    file_path : Union[str, Path]
        Path to file.
    algorithm : str
        Algorithm name.
        
    Returns
    -------
    str
        Hexadecimal hash.
        
    Examples
    --------
    >>> hash_file("document.txt", "md5")
    '5d41402abc4b2a76b9719d911017c592'
    """
    algo = HashAlgorithm(algorithm.lower())
    return compute_checksum(file_path, algo)


def get_file_checksum(file_path: Union[str, Path], algorithm: str = "sha256") -> str:
    """
    Alias for hash_file for backward compatibility.
    
    Parameters
    ----------
    file_path : Union[str, Path]
        Path to file.
    algorithm : str
        Algorithm name.
        
    Returns
    -------
    str
        Hexadecimal checksum.
    """
    return hash_file(file_path, algorithm)


def hash_algorithm(algorithm: str) -> HashAlgorithm:
    """
    Get HashAlgorithm enum from string.
    
    Parameters
    ----------
    algorithm : str
        Algorithm name (case-insensitive).
        
    Returns
    -------
    HashAlgorithm
        Corresponding enum value.
        
    Raises
    ------
    ValueError
        If algorithm name is invalid.
        
    Examples
    --------
    >>> algo = hash_algorithm("sha256")
    >>> print(algo.get_digest_size())
    32
    """
    algo_map = {
        "md5": HashAlgorithm.MD5,
        "sha1": HashAlgorithm.SHA1,
        "sha224": HashAlgorithm.SHA224,
        "sha256": HashAlgorithm.SHA256,
        "sha384": HashAlgorithm.SHA384,
        "sha512": HashAlgorithm.SHA512,
        "sha3_256": HashAlgorithm.SHA3_256,
        "sha3-256": HashAlgorithm.SHA3_256,
        "sha3_512": HashAlgorithm.SHA3_512,
        "sha3-512": HashAlgorithm.SHA3_512,
        "blake2b": HashAlgorithm.BLAKE2B,
        "blake2s": HashAlgorithm.BLAKE2S,
        "xxh64": HashAlgorithm.XXH64,
        "xxhash64": HashAlgorithm.XXH64,
        "xxh128": HashAlgorithm.XXH128,
        "xxhash128": HashAlgorithm.XXH128,
    }
    
    key = algorithm.lower().replace("-", "_")
    if key in algo_map:
        return algo_map[key]
    
    raise ValueError(f"Unknown algorithm: {algorithm}")


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "HashAlgorithm",
    
    # Exceptions
    "ChecksumError",
    
    # Data classes
    "ChecksumResult",
    "BatchChecksumResult",
    
    # Classes
    "StreamingHashReader",
    "IncrementalHasher",
    
    # Core functions
    "compute_file_hash",
    "compute_checksum",
    "compute_string_hash",
    "compute_bytes_hash",
    "compute_stream_hash",
    
    # Verification
    "verify_checksum",
    "compare_files",
    
    # Parallel
    "compute_checksums_parallel",
    
    # Convenience
    "hash_string",
    "hash_file",
    "get_file_checksum",
    "hash_algorithm",
]
