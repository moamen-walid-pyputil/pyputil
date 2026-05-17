#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Caching mechanism for compiled libraries with cross-platform file locking.

This module provides functions for computing cache keys based on compilation
parameters, managing cache directories, and implementing cross-platform
file locking to prevent race conditions during concurrent compilation.

The caching strategy:
    1. A cache key is computed from the source code and all compilation parameters
    2. The compiled library is stored in a directory named after the cache key
    3. File locking ensures only one process compiles a given key at a time
    4. Compiled libraries persist across Python sessions

Examples
--------
>>> from cfast_basic.cache import _compute_cache_key, _ensure_cache_dir
>>> key = _compute_cache_key(
...     code="int add(int a, int b) { return a + b; }",
...     cflags=["-O2"],
...     compiler_name="gcc",
...     libraries=[],
...     includes=[],
...     defines={},
...     engine_version="1"
... )
>>> cache_dir = _ensure_cache_dir(key)
>>> print(f"Cache directory: {cache_dir}")
"""

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Optional, Any, Union

from .exceptions import LockError


# Try to import fcntl for Unix locking
try:
    import fcntl
    _FCNTL_AVAILABLE = True
except ImportError:
    _FCNTL_AVAILABLE = False

# Try to import msvcrt for Windows locking
try:
    import msvcrt
    _MSVCRT_AVAILABLE = True
except ImportError:
    _MSVCRT_AVAILABLE = False


def _compute_cache_key(
    code: str,
    cflags: List[str],
    compiler_name: str,
    libraries: List[str],
    includes: List[str],
    defines: Dict[str, Optional[str]],
    engine_version: str,
) -> str:
    """
    Compute a unique key for caching the compiled library.

    The key is based on the source code, engine version, and all compilation
    parameters that could affect the binary output. The algorithm uses SHA256
    hashing with null-separated components to avoid hash collisions from
    ambiguous concatenation.

    Parameters
    ----------
    code : str
        The complete C source code to be compiled.
    cflags : list of str
        Compiler flags (e.g., ``['-O2', '-Wall']``).
    compiler_name : str
        Name of the compiler executable (e.g., ``'gcc'``, ``'clang'``, ``'cl'``).
    libraries : list of str
        Libraries to link against (e.g., ``['m', 'pthread']``).
    includes : list of str
        Additional include directories.
    defines : dict of {str: str or None}
        Macro definitions. Keys are macro names. If value is None, the macro
        is defined without a value (``-DMACRO``). Otherwise, it is defined
        with the value (``-DMACRO=value``).
    engine_version : str
        Version string of the cfast_basic engine. This should be incremented when
        changes are made to the compilation or parsing logic that would
        invalidate existing cached libraries.

    Returns
    -------
    str
        A 16-character hexadecimal string (first 16 characters of SHA256 hash)
        that uniquely identifies the compilation configuration.

    Notes
    -----
    All list and dictionary inputs are sorted before hashing to ensure
    deterministic keys regardless of input order.

    Examples
    --------
    >>> key = _compute_cache_key(
    ...     code="int foo() { return 42; }",
    ...     cflags=["-O2", "-Wall"],
    ...     compiler_name="gcc",
    ...     libraries=["m"],
    ...     includes=["/usr/local/include"],
    ...     defines={"DEBUG": None, "VERSION": "1.0"},
    ...     engine_version="5"
    ... )
    >>> len(key)
    16
    >>> key.isalnum()
    True
    """
    # Sort all collections to ensure deterministic key
    cflags_sorted = sorted(cflags)
    libs_sorted = sorted(libraries)
    includes_sorted = sorted(includes)
    defines_sorted = sorted(defines.items())

    # Build the components list
    components: List[str] = [
        engine_version,
        code,
        compiler_name,
    ]
    components.extend(cflags_sorted)
    components.extend(libs_sorted)
    components.extend(includes_sorted)
    components.extend(
        f"{k}={v}" if v is not None else k
        for k, v in defines_sorted
    )

    # Join with null separator to prevent ambiguity
    full_input = "\0".join(components)

    # Compute SHA256 and return first 16 characters
    hash_obj = hashlib.sha256(full_input.encode('utf-8'))
    return hash_obj.hexdigest()[:16]


def _get_cache_root() -> Path:
    """
    Get the root directory for all cfast_basic caches.

    The cache root is located in the system temporary directory under
    a 'cfast_basic_cache' subdirectory.

    Returns
    -------
    Path
        Absolute path to the cache root directory.

    Examples
    --------
    >>> root = _get_cache_root()
    >>> print(root)  # e.g., /tmp/cfast_basic_cache on Linux
    """
    return Path(tempfile.gettempdir()) / "cfast_basic_cache"


def _ensure_cache_dir(cache_key: str) -> Path:
    """
    Create and return a cache directory for a given cache key.

    The directory is created under the cache root directory. Parent
    directories are created if they do not exist.

    Parameters
    ----------
    cache_key : str
        The 16-character cache key returned by :func:`_compute_cache_key`.

    Returns
    -------
    Path
        Path to the created cache directory.

    Examples
    --------
    >>> key = "abc123def4567890"
    >>> cache_dir = _ensure_cache_dir(key)
    >>> cache_dir.exists()
    True
    """
    cache_root = _get_cache_root()
    cache_dir = cache_root / cache_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _lock_file_path(cache_dir: Path) -> Path:
    """
    Return the path to the lock file for a cache directory.

    Parameters
    ----------
    cache_dir : Path
        Path to the cache directory.

    Returns
    -------
    Path
        Path to the lock file (named 'compile.lock' inside the cache directory).

    Examples
    --------
    >>> lock_path = _lock_file_path(Path("/tmp/cfast_basic_cache/abc123"))
    >>> lock_path.name
    'compile.lock'
    """
    return cache_dir / "compile.lock"


class FileLock:
    """
    Cross-platform exclusive file lock.

    This class provides a context manager interface for acquiring and
    releasing exclusive file locks. It automatically selects the appropriate
    locking mechanism based on the operating system:

    - Windows: Uses ``msvcrt.locking`` on file descriptors
    - Unix (Linux/macOS): Uses ``fcntl.flock``
    - Unsupported platforms: Falls back to no-op locking

    The lock is implemented as an exclusive (write) lock. Only one process
    can hold the lock on a given file at a time.

    Parameters
    ----------
    lock_path : Path or str
        Path to the lock file. The file will be created if it does not exist.

    Attributes
    ----------
    lock_path : Path
        The resolved absolute path to the lock file.
    is_locked : bool
        True if the lock is currently held by this instance.
    _fd : int or None
        The open file descriptor for the lock file, or None if not locked.

    Examples
    --------
    Basic usage with context manager:

    >>> lock = FileLock("/tmp/my.lock")
    >>> with lock:
    ...     # Critical section - only one process can be here
    ...     perform_exclusive_operation()
    ... # Lock is automatically released

    Manual acquire/release:

    >>> lock = FileLock("/tmp/my.lock")
    >>> if lock.acquire(blocking=False):
    ...     try:
    ...         do_something()
    ...     finally:
    ...         lock.release()
    ... else:
    ...     print("Could not acquire lock - another process holds it")

    Notes
    -----
    - The lock is *not* thread-safe; it only synchronizes between processes.
    - On some network filesystems, file locking may not be supported. In such
      cases, the lock methods will raise :class:`LockError`.
    - The lock file is not automatically deleted when the lock is released.
    """

    def __init__(self, lock_path: Union[str, Path]):
        """
        Initialize a FileLock instance.

        Parameters
        ----------
        lock_path : Path or str
            Path to the lock file. The file will be created on first acquire.
        """
        self.lock_path = Path(lock_path).resolve()
        self._fd: Optional[int] = None
        self._is_locked: bool = False

    @property
    def is_locked(self) -> bool:
        """
        Check if the lock is currently held by this instance.

        Returns
        -------
        bool
            True if this instance holds the lock, False otherwise.
        """
        return self._is_locked

    def _acquire_windows(self, blocking: bool) -> bool:
        """
        Acquire lock on Windows using msvcrt.locking.

        Parameters
        ----------
        blocking : bool
            If True, block until lock is acquired. If False, return immediately.

        Returns
        -------
        bool
            True if lock acquired, False if would block (when blocking=False).

        Raises
        ------
        LockError
            If locking fails for reasons other than the lock being held.
        """
        lock_flag = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK

        try:
            msvcrt.locking(self._fd, lock_flag, 1)  # Lock the entire file
            return True
        except OSError as e:
            if not blocking:
                # Non-blocking lock would block - this is an expected outcome
                return False
            # Blocking lock failed for other reasons
            raise LockError(
                f"Failed to acquire lock on Windows: {e}",
                lock_path=str(self.lock_path)
            ) from e

    def _release_windows(self) -> None:
        """Release lock on Windows."""
        try:
            msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
        except OSError as e:
            # Log but don't raise on unlock errors
            import logging
            logging.getLogger(__name__).debug(
                f"Error releasing lock on Windows: {e}"
            )

    def _acquire_unix(self, blocking: bool) -> bool:
        """
        Acquire lock on Unix using fcntl.flock.

        Parameters
        ----------
        blocking : bool
            If True, block until lock is acquired. If False, return immediately.

        Returns
        -------
        bool
            True if lock acquired, False if would block (when blocking=False).

        Raises
        ------
        LockError
            If locking fails for reasons other than the lock being held.
        """
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB

        try:
            fcntl.flock(self._fd, flags)
            return True
        except (OSError, IOError) as e:
            if not blocking:
                errno = getattr(e, 'errno', 0)
                if errno in (fcntl.EAGAIN, fcntl.EACCES):
                    # Would block - expected for non-blocking lock
                    return False
            # Other error or blocking lock failed
            raise LockError(
                f"Failed to acquire lock on Unix: {e}",
                lock_path=str(self.lock_path)
            ) from e

    def _release_unix(self) -> None:
        """Release lock on Unix."""
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except (OSError, IOError) as e:
            import logging
            logging.getLogger(__name__).debug(
                f"Error releasing lock on Unix: {e}"
            )

    def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire an exclusive lock on the lock file.

        Parameters
        ----------
        blocking : bool, default True
            If True, block indefinitely until the lock can be acquired.
            If False, return immediately with False if the lock is held
            by another process.

        Returns
        -------
        bool
            True if the lock was successfully acquired, False if the lock
            is held by another process and blocking=False.

        Raises
        ------
        LockError
            If locking is not supported on the filesystem, if permission
            is denied, or if another unrecoverable error occurs.

        Notes
        -----
        Calling acquire on an already-locked instance returns True immediately.
        """
        if self._is_locked:
            return True

        # Ensure parent directory exists
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        # Open the lock file (create if doesn't exist)
        try:
            self._fd = os.open(
                self.lock_path,
                os.O_CREAT | os.O_RDWR,
                0o644
            )
        except OSError as e:
            raise LockError(
                f"Cannot open lock file {self.lock_path}: {e}",
                lock_path=str(self.lock_path)
            ) from e

        try:
            if sys.platform.startswith("win"):
                if not _MSVCRT_AVAILABLE:
                    raise LockError(
                        "msvcrt module not available on Windows",
                        lock_path=str(self.lock_path)
                    )
                acquired = self._acquire_windows(blocking)
            else:
                if not _FCNTL_AVAILABLE:
                    raise LockError(
                        "fcntl module not available on Unix",
                        lock_path=str(self.lock_path)
                    )
                acquired = self._acquire_unix(blocking)

            if acquired:
                self._is_locked = True
                return True
            else:
                # Could not acquire non-blocking lock
                os.close(self._fd)
                self._fd = None
                return False

        except Exception:
            # Clean up on any error
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            raise

    def release(self) -> None:
        """
        Release the lock if it is currently held.

        This method is idempotent; calling it multiple times has no effect
        after the first release.

        Notes
        -----
        This method does not delete the lock file; it only releases the
        operating system lock and closes the file descriptor.
        """
        if not self._is_locked or self._fd is None:
            return

        try:
            if sys.platform.startswith("win"):
                self._release_windows()
            else:
                self._release_unix()
        finally:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            self._is_locked = False

    def __enter__(self) -> 'FileLock':
        """
        Enter the context manager, acquiring the lock with blocking=True.

        Returns
        -------
        FileLock
            The FileLock instance itself.

        Raises
        ------
        LockError
            If the lock cannot be acquired.
        """
        self.acquire(blocking=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit the context manager, releasing the lock.

        The lock is released regardless of whether an exception occurred.

        Parameters
        ----------
        exc_type : type or None
            The exception type if an exception occurred, else None.
        exc_val : Exception or None
            The exception instance if an exception occurred, else None.
        exc_tb : traceback or None
            The traceback if an exception occurred, else None.
        """
        self.release()

    def __del__(self) -> None:
        """
        Destructor that attempts to release the lock if still held.

        Notes
        -----
        Relying on __del__ for cleanup is not recommended; always use
        the context manager or explicitly call release().
        """
        try:
            if self._is_locked:
                self.release()
        except Exception:
            # Suppress all exceptions during garbage collection
            pass


def acquire_lock(cache_dir: Path) -> Optional[FileLock]:
    """
    Acquire an exclusive lock on a cache directory.

    This function creates a :class:`FileLock` for the cache directory and
    attempts to acquire it with blocking behavior. The lock prevents
    concurrent compilation of the same cache key.

    Parameters
    ----------
    cache_dir : Path
        Path to the cache directory to lock.

    Returns
    -------
    FileLock or None
        A locked :class:`FileLock` instance if locking is supported and
        the lock was acquired. Returns None if locking is not supported
        on the filesystem. In the None case, the caller should proceed
        without locking (accepting the race condition).

    Examples
    --------
    >>> cache_dir = _ensure_cache_dir("abc123")
    >>> lock = acquire_lock(cache_dir)
    >>> try:
    ...     # Compile while holding lock
    ...     compile_code()
    ... finally:
    ...     release_lock(lock)
    """
    lock_path = _lock_file_path(cache_dir)
    lock = FileLock(lock_path)

    try:
        lock.acquire(blocking=True)
        return lock
    except LockError as e:
        import logging
        logging.getLogger(__name__).warning(
            f"Could not acquire lock on {cache_dir}: {e}. "
            "Proceeding without locking (race condition possible)."
        )
        return None


def release_lock(lock: Optional[FileLock]) -> None:
    """
    Release a previously acquired lock.

    This function safely releases a lock if it is not None.

    Parameters
    ----------
    lock : FileLock or None
        The lock to release, or None.

    Examples
    --------
    >>> lock = acquire_lock(cache_dir)
    >>> try:
    ...     do_work()
    ... finally:
    ...     release_lock(lock)
    """
    if lock is not None:
        lock.release()


def get_cache_info(cache_key: str) -> Dict[str, Any]:
    """
    Get information about a cached library.

    Parameters
    ----------
    cache_key : str
        The 16-character cache key.

    Returns
    -------
    dict
        Dictionary containing cache information with keys:
            - 'exists': bool - Whether the cache directory exists
            - 'library_exists': bool - Whether the compiled library exists
            - 'cache_dir': Path - Path to the cache directory
            - 'library_path': Path - Path to the compiled library (may not exist)
            - 'size_bytes': int - Size of the library in bytes (0 if doesn't exist)
            - 'created': float - Creation timestamp (0 if doesn't exist)
            - 'age_days': float - Age in days (0 if doesn't exist)

    Examples
    --------
    >>> info = get_cache_info("abc123def4567890")
    >>> if info['exists']:
    ...     print(f"Cache age: {info['age_days']:.1f} days")
    """
    cache_dir = _ensure_cache_dir(cache_key)
    lib_path = cache_dir / f"cfast_basic{PlatformInfo.shared_lib_extension()}"

    info: Dict[str, Any] = {
        'exists': cache_dir.exists(),
        'library_exists': lib_path.exists(),
        'cache_dir': cache_dir,
        'library_path': lib_path,
        'size_bytes': 0,
        'created': 0.0,
        'age_days': 0.0,
    }

    if lib_path.exists():
        try:
            stat = lib_path.stat()
            info['size_bytes'] = stat.st_size
            info['created'] = stat.st_ctime
            info['age_days'] = (time.time() - stat.st_ctime) / 86400.0
        except OSError:
            pass

    return info


def clear_cache(max_age_days: Optional[int] = None) -> int:
    """
    Remove cached compiled libraries from the filesystem.

    Parameters
    ----------
    max_age_days : int, optional
        If provided, only remove cache directories older than this many days.
        If None, remove all caches regardless of age.

    Returns
    -------
    int
        The number of cache directories that were removed.

    Examples
    --------
    >>> # Clear all caches
    >>> removed = clear_cache()
    >>> print(f"Removed {removed} cache directories")

    >>> # Clear caches older than 7 days
    >>> removed = clear_cache(max_age_days=7)
    >>> print(f"Removed {removed} old cache directories")
    """
    import shutil
    import re

    cache_root = _get_cache_root()
    if not cache_root.exists():
        return 0

    # Validate cache key format: 16 hexadecimal characters
    cache_key_pattern = re.compile(r'^[0-9a-f]{16}$')
    now = time.time()
    removed = 0

    for item in cache_root.iterdir():
        if not item.is_dir():
            continue

        # Only delete directories that look like cache keys
        if not cache_key_pattern.match(item.name):
            continue

        should_remove = True

        if max_age_days is not None:
            try:
                mtime = item.stat().st_mtime
                age_days = (now - mtime) / 86400.0
                should_remove = age_days > max_age_days
            except OSError:
                # If we can't stat, assume it's old and safe to remove
                should_remove = True

        if should_remove:
            try:
                shutil.rmtree(item, ignore_errors=False)
                removed += 1
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to remove cache directory {item}: {e}"
                )

    return removed