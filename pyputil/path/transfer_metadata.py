#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module and Package Filesystem Operations.

This module provides robust, production-ready utilities for copying, moving,
and synchronizing Python modules and packages in the filesystem. It includes
comprehensive error handling, path validation, and batch operation support.

Features
--------
- Copy and move single or multiple modules/packages
- Synchronize packages between locations (like rsync)
- Comprehensive path validation and safety checks
- Full NumPy-style documentation
- Type hints throughout
- Thread-safe operations with proper locking
- Structured dataclass responses instead of raw dictionaries

Examples
--------
>>> from module_ops import copy, move, sync
>>> # Copy a single module
>>> result = copy("requests", target="/backup/modules")
>>> print(f"Copied: {result.succeeded} files")
>>> # Move multiple packages at once
>>> result = move(["numpy", "pandas"], target="/opt/packages", overwrite=True)
>>> # Synchronize a package
>>> result = sync("my_package", "/deployment/location", delete_orphans=True)
"""

from importlib.util import find_spec
from pathlib import Path
import shutil
import sys
import filecmp
import fnmatch
from typing import Optional, Union, List, Tuple, Set, Dict, Any
from dataclasses import dataclass, field
from enum import Enum, auto
import logging
import tempfile
import hashlib
import json
from datetime import datetime
from threading import Lock
import os
import stat


class ConflictResolution(Enum):
    """Enumeration of conflict resolution strategies for file operations."""
    
    ERROR = auto()
    """Raise an error when conflicts occur."""
    
    OVERWRITE = auto()
    """Overwrite existing files/directories unconditionally."""
    
    SKIP = auto()
    """Skip conflicting files/directories."""
    
    BACKUP = auto()
    """Create backup of existing files before overwriting."""
    
    MERGE = auto()
    """Merge directories (only applicable for directory operations)."""
    
    RENAME = auto()
    """Rename the new file to avoid conflict (adds suffix)."""


@dataclass
class OperationResult:
    """
    Container for operation results and statistics.
    
    Attributes
    ----------
    success : bool
        Whether the operation completed successfully.
    processed : int
        Number of items processed.
    succeeded : int
        Number of items successfully processed.
    failed : int
        Number of items that failed.
    skipped : int
        Number of items skipped due to conflicts or filters.
    paths : List[Path]
        List of resulting paths after operation.
    errors : List[Tuple[str, Exception]]
        List of errors encountered during operation.
    warnings : List[str]
        List of warning messages generated during operation.
    metadata : Dict[str, Any]
        Additional metadata about the operation.
    """
    
    success: bool = True
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    paths: List[Path] = field(default_factory=list)
    errors: List[Tuple[str, Exception]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert OperationResult to dictionary format.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the result.
        """
        return {
            "success": self.success,
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "paths": [str(p) for p in self.paths],
            "errors": [(name, str(err)) for name, err in self.errors],
            "warnings": self.warnings,
            "metadata": self.metadata
        }


@dataclass
class ModuleInfo:
    """
    Container for module or package information.
    
    Attributes
    ----------
    name : str
        Name of the module or package.
    path : Optional[Path]
        Resolved filesystem path to the module/package.
    module_type : str
        Type of module: 'module', 'package', or 'unknown'.
    exists : bool
        Whether the module exists and is accessible.
    size : int
        Total size in bytes.
    file_count : int
        Number of files in the module/package.
    modified : Optional[datetime]
        Last modification timestamp.
    permissions : Optional[str]
        File permissions in octal format.
    is_symlink : bool
        Whether the path is a symbolic link.
    error : Optional[str]
        Error message if module info couldn't be retrieved.
    metadata : Dict[str, Any]
        Additional module metadata.
    """
    
    name: str
    path: Optional[Path] = None
    module_type: str = "unknown"
    exists: bool = False
    size: int = 0
    file_count: int = 0
    modified: Optional[datetime] = None
    permissions: Optional[str] = None
    is_symlink: bool = False
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert ModuleInfo to dictionary format.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the module info.
        """
        return {
            "name": self.name,
            "path": str(self.path) if self.path else None,
            "type": self.module_type,
            "exists": self.exists,
            "size": self.size,
            "file_count": self.file_count,
            "modified": self.modified.isoformat() if self.modified else None,
            "permissions": self.permissions,
            "is_symlink": self.is_symlink,
            "error": self.error,
            "metadata": self.metadata
        }


@dataclass
class VerificationResult:
    """
    Container for module verification results.
    
    Attributes
    ----------
    exists : List[str]
        List of verified modules that exist.
    missing : List[str]
        List of modules that could not be found.
    mismatched : List[str]
        List of modules with mismatched content.
    errors : List[Tuple[str, str]]
        List of modules that couldn't be verified due to errors.
    summary : Dict[str, int]
        Summary statistics of the verification.
    verified_modules : List[ModuleInfo]
        Detailed information about verified modules.
    timestamp : datetime
        When the verification was performed.
    """
    
    exists: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    mismatched: List[str] = field(default_factory=list)
    errors: List[Tuple[str, str]] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    verified_modules: List[ModuleInfo] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        """Initialize summary if empty."""
        if not self.summary:
            self.summary = {
                "total": 0,
                "verified": len(self.exists),
                "missing": len(self.missing),
                "mismatched": len(self.mismatched),
                "failed": len(self.errors)
            }
    
    @property
    def all_verified(self) -> bool:
        """
        Check if all modules were verified successfully.
        
        Returns
        -------
        bool
            True if all modules exist and match (if reference provided).
        """
        return (len(self.missing) == 0 and 
                len(self.mismatched) == 0 and 
                len(self.errors) == 0)
    
    @property
    def total_modules(self) -> int:
        """
        Get total number of modules checked.
        
        Returns
        -------
        int
            Total modules processed.
        """
        return (len(self.exists) + len(self.missing) + 
                len(self.errors))
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert VerificationResult to dictionary format.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the verification result.
        """
        return {
            "exists": self.exists,
            "missing": self.missing,
            "mismatched": self.mismatched,
            "errors": self.errors,
            "summary": self.summary,
            "verified_modules": [m.to_dict() for m in self.verified_modules],
            "timestamp": self.timestamp.isoformat(),
            "all_verified": self.all_verified,
            "total_modules": self.total_modules
        }


@dataclass
class SyncStats:
    """
    Detailed statistics for synchronization operations.
    
    Attributes
    ----------
    files_to_sync : int
        Number of files that need to be synchronized.
    files_to_delete : int
        Number of orphaned files to be deleted.
    bytes_to_transfer : int
        Total bytes to be transferred.
    files_copied : int
        Number of files actually copied.
    files_deleted : int
        Number of files actually deleted.
    bytes_transferred : int
        Total bytes actually transferred.
    errors_count : int
        Number of errors during sync.
    warnings_count : int
        Number of warnings during sync.
    """
    
    files_to_sync: int = 0
    files_to_delete: int = 0
    bytes_to_transfer: int = 0
    files_copied: int = 0
    files_deleted: int = 0
    bytes_transferred: int = 0
    errors_count: int = 0
    warnings_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert SyncStats to dictionary format.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of sync statistics.
        """
        return {
            "files_to_sync": self.files_to_sync,
            "files_to_delete": self.files_to_delete,
            "bytes_to_transfer": self.bytes_to_transfer,
            "files_copied": self.files_copied,
            "files_deleted": self.files_deleted,
            "bytes_transferred": self.bytes_transferred,
            "errors_count": self.errors_count,
            "warnings_count": self.warnings_count
        }


@dataclass
class BatchOperationResult:
    """
    Container for batch operation results across multiple modules.
    
    Attributes
    ----------
    total_operations : int
        Total number of operations attempted.
    successful : int
        Number of successful operations.
    failed : int
        Number of failed operations.
    results : Dict[str, OperationResult]
        Individual results keyed by module name.
    errors : List[Tuple[str, str]]
        Aggregated errors from all operations.
    start_time : datetime
        When the batch operation started.
    end_time : Optional[datetime]
        When the batch operation completed.
    """
    
    total_operations: int = 0
    successful: int = 0
    failed: int = 0
    results: Dict[str, OperationResult] = field(default_factory=dict)
    errors: List[Tuple[str, str]] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    
    @property
    def duration_seconds(self) -> float:
        """
        Calculate operation duration in seconds.
        
        Returns
        -------
        float
            Duration in seconds, or 0 if not completed.
        """
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0
    
    @property
    def success_rate(self) -> float:
        """
        Calculate success rate as percentage.
        
        Returns
        -------
        float
            Success rate (0.0 to 100.0).
        """
        if self.total_operations == 0:
            return 0.0
        return (self.successful / self.total_operations) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert BatchOperationResult to dictionary format.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the batch result.
        """
        return {
            "total_operations": self.total_operations,
            "successful": self.successful,
            "failed": self.failed,
            "results": {name: result.to_dict() for name, result in self.results.items()},
            "errors": self.errors,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "success_rate": self.success_rate
        }


class ModuleOperationError(Exception):
    """
    Base exception for module operation errors.
    
    This exception wraps lower-level errors with additional context
    about the module operation being performed.
    
    Parameters
    ----------
    message : str
        Error message describing the failure.
    module_name : str, optional
        Name of the module involved in the operation.
    original_error : Exception, optional
        The original exception that caused this error.
    operation : str, optional
        Type of operation being performed ('copy', 'move', 'sync').
    """
    
    def __init__(
        self,
        message: str,
        module_name: Optional[str] = None,
        original_error: Optional[Exception] = None,
        operation: Optional[str] = None
    ):
        self.module_name = module_name
        self.original_error = original_error
        self.operation = operation
        
        full_message = message
        if module_name:
            full_message = f"[{module_name}] {full_message}"
        if operation:
            full_message = f"{operation.upper()}: {full_message}"
            
        super().__init__(full_message)


class PathSecurityError(ModuleOperationError):
    """Raised when a path operation violates security constraints."""
    pass


class ModuleNotFoundInSysPath(ModuleOperationError):
    """Raised when a module cannot be found in sys.path."""
    pass


class _FileLockManager:
    """
    Thread-safe file operation lock manager.
    
    This class manages locks for file operations to prevent race conditions
    when multiple threads attempt to operate on the same paths.
    
    Attributes
    ----------
    _locks : Dict[str, Lock]
        Dictionary mapping canonical paths to Lock objects.
    _global_lock : Lock
        Global lock for the lock dictionary operations.
    """
    
    def __init__(self):
        """Initialize the lock manager."""
        self._locks: Dict[str, Lock] = {}
        self._global_lock = Lock()
    
    def acquire(self, path: Path) -> None:
        """
        Acquire a lock for a specific path.
        
        Parameters
        ----------
        path : Path
            The filesystem path to lock.
        """
        canonical = str(path.resolve())
        
        with self._global_lock:
            if canonical not in self._locks:
                self._locks[canonical] = Lock()
            lock = self._locks[canonical]
        
        lock.acquire()
    
    def release(self, path: Path) -> None:
        """
        Release a lock for a specific path.
        
        Parameters
        ----------
        path : Path
            The filesystem path to unlock.
        """
        canonical = str(path.resolve())
        
        with self._global_lock:
            lock = self._locks.get(canonical)
        
        if lock:
            lock.release()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, *args):
        """Context manager exit - no cleanup needed."""
        pass


# Global lock manager instance
_lock_manager = _FileLockManager()

# Configure module logger
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def _resolve_module_path(name: str) -> Path:
    """
    Resolve the filesystem path of a module or package.
    
    This function uses importlib.util.find_spec to locate the module's
    origin and converts it to a resolved Path object. It handles both
    regular modules (.py files) and packages (directories with __init__.py).
    
    Parameters
    ----------
    name : str
        Module or package name. Can use dot notation for submodules
        (e.g., 'package.submodule').
    
    Returns
    -------
    Path
        Resolved absolute path to module file or package directory.
    
    Raises
    ------
    ModuleNotFoundInSysPath
        If the module cannot be found in sys.path.
    ValueError
        If the module spec has no origin (e.g., built-in modules).
    ModuleOperationError
        If the resolved path is invalid or inaccessible.
    
    Examples
    --------
    >>> _resolve_module_path("os")
    Path("/usr/lib/python3.9/os.py")
    
    >>> _resolve_module_path("email")
    Path("/usr/lib/python3.9/email/")
    """
    try:
        spec = find_spec(name)
    except (ImportError, ModuleNotFoundError) as e:
        raise ModuleNotFoundInSysPath(
            f"Module '{name}' could not be found",
            module_name=name,
            original_error=e
        )
    
    if spec is None:
        raise ModuleNotFoundInSysPath(
            f"Module '{name}' not found in sys.path",
            module_name=name
        )
    
    if spec.origin is None:
        raise ModuleOperationError(
            f"Module '{name}' has no filesystem origin (may be built-in or namespace)",
            module_name=name
        )
    
    try:
        path = Path(spec.origin).resolve(strict=False)
        
        # Verify path is accessible
        if not path.exists():
            raise ModuleOperationError(
                f"Module origin '{path}' does not exist on filesystem",
                module_name=name
            )
        
        # For packages, return the directory containing __init__.py
        if path.name == "__init__.py":
            return path.parent
        
        return path
        
    except (OSError, RuntimeError) as e:
        raise ModuleOperationError(
            f"Failed to resolve path for module '{name}'",
            module_name=name,
            original_error=e
        )


def _resolve_module_paths(
    names: Union[str, List[str]]
) -> Dict[str, Path]:
    """
    Resolve multiple module paths in batch.
    
    Parameters
    ----------
    names : Union[str, List[str]]
        Single module name or list of module names to resolve.
    
    Returns
    -------
    Dict[str, Path]
        Dictionary mapping module names to their resolved paths.
    
    Raises
    ------
    ModuleOperationError
        If any module cannot be resolved.
    """
    if isinstance(names, str):
        names = [names]
    
    resolved = {}
    errors = []
    
    for name in names:
        try:
            resolved[name] = _resolve_module_path(name)
        except Exception as e:
            errors.append((name, e))
    
    if errors:
        error_messages = [f"{name}: {err}" for name, err in errors]
        raise ModuleOperationError(
            f"Failed to resolve modules: {'; '.join(error_messages)}",
            operation="resolve"
        )
    
    return resolved


def _validate_paths(
    src: Path,
    dst: Path,
    allow_same: bool = False,
    require_src_exists: bool = True
) -> None:
    """
    Validate source and destination paths for file operations.
    
    Performs comprehensive validation including existence checks,
    permission verification, and safety constraints.
    
    Parameters
    ----------
    src : Path
        Source path to validate.
    dst : Path
        Destination path to validate.
    allow_same : bool, default=False
        Whether to allow source and destination to be the same path.
    require_src_exists : bool, default=True
        Whether to require that the source path exists.
    
    Raises
    ------
    FileNotFoundError
        If source does not exist and require_src_exists is True.
    PathSecurityError
        If source and destination are the same and not allowed.
    PermissionError
        If destination parent directory is not writable.
    ModuleOperationError
        For other validation failures.
    
    Warns
    -----
    UserWarning
        If destination exists and may be overwritten.
    """
    # Check source existence
    if require_src_exists and not src.exists():
        raise FileNotFoundError(f"Source '{src}' does not exist")
    
    # Security: Prevent self-operation unless explicitly allowed
    try:
        if src.resolve() == dst.resolve():
            if not allow_same:
                raise PathSecurityError(
                    f"Source and destination are the same: '{src}'",
                    operation="validate"
                )
            logger.warning(f"Source and destination are identical: '{src}'")
    except (OSError, RuntimeError) as e:
        raise ModuleOperationError(
            f"Failed to resolve paths for comparison: {e}",
            original_error=e
        )
    
    # Check if destination parent is writable
    parent = dst.parent
    if parent.exists():
        if not os.access(str(parent), os.W_OK):
            raise PermissionError(
                f"Destination parent directory '{parent}' is not writable"
            )
    else:
        # Check if we can create the parent
        current = parent
        while current != current.parent:
            if current.exists():
                if not os.access(str(current), os.W_OK):
                    raise PermissionError(
                        f"Cannot create destination path: '{current}' is not writable"
                    )
                break
            current = current.parent
    
    # Warn if destination exists
    if dst.exists():
        logger.warning(f"Destination '{dst}' already exists and may be affected")


def _compute_file_hash(path: Path, algorithm: str = "sha256") -> str:
    """
    Compute cryptographic hash of a file's contents.
    
    Parameters
    ----------
    path : Path
        Path to the file.
    algorithm : str, default="sha256"
        Hash algorithm to use (md5, sha1, sha256, etc.).
    
    Returns
    -------
    str
        Hexadecimal digest of the file's hash.
    
    Raises
    ------
    ModuleOperationError
        If file cannot be read or hash computation fails.
    """
    try:
        hasher = hashlib.new(algorithm)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, ValueError) as e:
        raise ModuleOperationError(
            f"Failed to compute {algorithm} hash for '{path}'",
            original_error=e
        )


def _create_backup(path: Path) -> Path:
    """
    Create a timestamped backup of a file or directory.
    
    Parameters
    ----------
    path : Path
        Path to the file or directory to backup.
    
    Returns
    -------
    Path
        Path to the created backup.
    
    Raises
    ------
    ModuleOperationError
        If backup creation fails.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = path.with_name(f"{path.name}.backup_{timestamp}")
    
    try:
        if path.is_file():
            shutil.copy2(path, backup_path)
        else:
            shutil.copytree(path, backup_path, symlinks=True)
        
        logger.info(f"Created backup: {backup_path}")
        return backup_path
    except (OSError, shutil.Error) as e:
        raise ModuleOperationError(
            f"Failed to create backup of '{path}'",
            original_error=e
        )


def _handle_conflict(
    dst: Path,
    resolution: ConflictResolution,
    backup_dir: Optional[Path] = None
) -> bool:
    """
    Handle conflicts when destination already exists.
    
    Parameters
    ----------
    dst : Path
        Destination path that already exists.
    resolution : ConflictResolution
        Strategy for handling the conflict.
    backup_dir : Path, optional
        Directory for backups (if resolution is BACKUP).
    
    Returns
    -------
    bool
        True if operation should proceed (overwrite/skip), False to abort.
    
    Raises
    ------
    FileExistsError
        If resolution is ERROR.
    ModuleOperationError
        If conflict resolution fails.
    """
    if resolution == ConflictResolution.ERROR:
        raise FileExistsError(f"Destination '{dst}' already exists")
    
    elif resolution == ConflictResolution.SKIP:
        logger.info(f"Skipping existing destination: '{dst}'")
        return False
    
    elif resolution == ConflictResolution.OVERWRITE:
        logger.info(f"Overwriting existing destination: '{dst}'")
        return True
    
    elif resolution == ConflictResolution.BACKUP:
        backup_path = _create_backup(dst)
        if backup_dir:
            shutil.move(str(backup_path), str(backup_dir / backup_path.name))
        return True
    
    elif resolution == ConflictResolution.RENAME:
        counter = 1
        while True:
            new_name = f"{dst.stem}_{counter}{dst.suffix}"
            new_dst = dst.with_name(new_name)
            if not new_dst.exists():
                logger.info(f"Renaming to avoid conflict: {new_dst}")
                return True
            counter += 1
            if counter > 1000:
                raise ModuleOperationError(
                    f"Could not find unique name for '{dst}' after 1000 attempts"
                )
    
    elif resolution == ConflictResolution.MERGE:
        # Only applicable for directories
        if dst.is_dir():
            return True
        else:
            raise ModuleOperationError(
                f"Cannot MERGE: destination '{dst}' is not a directory"
            )
    
    return True


def _remove_path(path: Path) -> None:
    """
    Safely remove a file or directory.
    
    Parameters
    ----------
    path : Path
        Path to remove.
    
    Raises
    ------
    ModuleOperationError
        If removal fails.
    """
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
        else:
            shutil.rmtree(path, ignore_errors=False)
    except (OSError, shutil.Error) as e:
        raise ModuleOperationError(
            f"Failed to remove '{path}'",
            original_error=e
        )


def copy(
    module_or_package: Union[str, List[str]],
    target: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
    conflict_resolution: ConflictResolution = ConflictResolution.ERROR,
    preserve_metadata: bool = True,
    follow_symlinks: bool = True,
    ignore_patterns: Optional[List[str]] = None,
    backup_dir: Optional[Union[str, Path]] = None,
    dry_run: bool = False
) -> OperationResult:
    """
    Copy one or more Python modules or packages to a target directory.
    
    This function provides robust copying of modules and packages with
    comprehensive error handling, conflict resolution strategies, and
    progress tracking.
    
    Parameters
    ----------
    module_or_package : Union[str, List[str]]
        Name(s) of the module(s) or package(s) to copy.
        Can be a single string or a list of strings.
    target : Union[str, Path], optional
        Destination directory. If None, uses current working directory.
    overwrite : bool, default=False
        Legacy parameter for backward compatibility.
        Use conflict_resolution=ConflictResolution.OVERWRITE instead.
    conflict_resolution : ConflictResolution, default=ConflictResolution.ERROR
        Strategy for handling existing destination files/directories.
    preserve_metadata : bool, default=True
        If True, preserve file metadata (timestamps, permissions, etc.)
        using shutil.copy2 semantics.
    follow_symlinks : bool, default=True
        If True, follow symbolic links. If False, copy links as links.
    ignore_patterns : List[str], optional
        List of glob patterns to ignore during directory copy.
    backup_dir : Union[str, Path], optional
        Directory for storing backups when conflict_resolution is BACKUP.
    dry_run : bool, default=False
        If True, simulate the operation without actually copying files.
    
    Returns
    -------
    OperationResult
        Detailed result of the operation including statistics and errors.
    
    Raises
    ------
    ModuleOperationError
        If critical errors occur during the operation.
    
    Examples
    --------
    >>> # Copy a single module
    >>> result = copy("requests", target="/backup")
    >>> print(f"Copied {result.succeeded} modules")
    
    >>> # Copy multiple packages with backup on conflict
    >>> result = copy(
    ...     ["numpy", "pandas", "scipy"],
    ...     target="/opt/packages",
    ...     conflict_resolution=ConflictResolution.BACKUP,
    ...     backup_dir="/opt/backups"
    ... )
    
    >>> # Copy with ignore patterns
    >>> result = copy(
    ...     "my_package",
    ...     target="/deploy",
    ...     ignore_patterns=["*.pyc", "__pycache__", ".git"]
    ... )
    """
    result = OperationResult()
    result.metadata["operation"] = "copy"
    result.metadata["start_time"] = datetime.now().isoformat()
    
    # Handle legacy overwrite parameter
    if overwrite:
        conflict_resolution = ConflictResolution.OVERWRITE
        logger.warning(
            "Parameter 'overwrite' is deprecated. "
            "Use conflict_resolution=ConflictResolution.OVERWRITE instead."
        )
    
    # Validate and prepare paths
    try:
        resolved_modules = _resolve_module_paths(module_or_package)
    except ModuleOperationError as e:
        result.success = False
        result.errors.append(("resolution", e))
        return result
    
    target_path = Path(target) if target else Path.cwd()
    target_path = target_path.resolve()
    
    backup_path = Path(backup_dir) if backup_dir else target_path / ".backups"
    if conflict_resolution == ConflictResolution.BACKUP and not dry_run:
        backup_path.mkdir(parents=True, exist_ok=True)
    
    # Prepare ignore function
    ignore_func = None
    if ignore_patterns:
        def ignore_func(directory, contents):
            ignored = set()
            for pattern in ignore_patterns:
                ignored.update(fnmatch.filter(contents, pattern))
            return list(ignored)
    
    # Process each module
    for module_name, src_path in resolved_modules.items():
        result.processed += 1
        dst_path = target_path / src_path.name
        
        try:
            # Validate paths
            _validate_paths(src_path, dst_path)
            
            # Handle existing destination
            if dst_path.exists():
                should_proceed = _handle_conflict(
                    dst_path, conflict_resolution, backup_path
                )
                if not should_proceed:
                    result.skipped += 1
                    continue
                
                if not dry_run:
                    _remove_path(dst_path)
            
            # Perform the copy
            if not dry_run:
                _lock_manager.acquire(dst_path)
                try:
                    if src_path.is_file():
                        if preserve_metadata:
                            shutil.copy2(src_path, dst_path, follow_symlinks=follow_symlinks)
                        else:
                            shutil.copy(src_path, dst_path, follow_symlinks=follow_symlinks)
                    else:
                        shutil.copytree(
                            src_path, dst_path,
                            symlinks=not follow_symlinks,
                            ignore=ignore_func,
                            copy_function=shutil.copy2 if preserve_metadata else shutil.copy
                        )
                finally:
                    _lock_manager.release(dst_path)
            
            result.succeeded += 1
            result.paths.append(dst_path)
            logger.info(f"Copied '{src_path}' -> '{dst_path}'")
            
        except Exception as e:
            result.failed += 1
            error = ModuleOperationError(
                f"Failed to copy '{module_name}'",
                module_name=module_name,
                original_error=e,
                operation="copy"
            )
            result.errors.append((module_name, error))
            logger.error(f"Copy failed for '{module_name}': {e}")
    
    result.metadata["end_time"] = datetime.now().isoformat()
    result.success = (result.failed == 0)
    
    return result


def move(
    module_or_package: Union[str, List[str]],
    target: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
    conflict_resolution: ConflictResolution = ConflictResolution.ERROR,
    backup_dir: Optional[Union[str, Path]] = None,
    dry_run: bool = False
) -> OperationResult:
    """
    Move one or more Python modules or packages to a target directory.
    
    This function moves modules and packages using efficient rename
    operations when possible, falling back to copy-then-delete when
    moving across filesystem boundaries.
    
    Parameters
    ----------
    module_or_package : Union[str, List[str]]
        Name(s) of the module(s) or package(s) to move.
        Can be a single string or a list of strings.
    target : Union[str, Path], optional
        Destination directory. If None, uses current working directory.
    overwrite : bool, default=False
        Legacy parameter for backward compatibility.
        Use conflict_resolution=ConflictResolution.OVERWRITE instead.
    conflict_resolution : ConflictResolution, default=ConflictResolution.ERROR
        Strategy for handling existing destination files/directories.
    backup_dir : Union[str, Path], optional
        Directory for storing backups when conflict_resolution is BACKUP.
    dry_run : bool, default=False
        If True, simulate the operation without actually moving files.
    
    Returns
    -------
    OperationResult
        Detailed result of the operation including statistics and errors.
    
    Raises
    ------
    ModuleOperationError
        If critical errors occur during the operation.
    
    Warnings
    --------
    Moving modules may break imports if they are currently in use or
    referenced by other modules. Consider using copy() instead if you
    need to preserve the original location.
    
    Examples
    --------
    >>> # Move a single module
    >>> result = move("old_module", target="/archive")
    
    >>> # Move multiple packages with backup
    >>> result = move(
    ...     ["package1", "package2"],
    ...     target="/new_location",
    ...     conflict_resolution=ConflictResolution.BACKUP
    ... )
    """
    result = OperationResult()
    result.metadata["operation"] = "move"
    result.metadata["start_time"] = datetime.now().isoformat()
    
    # Handle legacy overwrite parameter
    if overwrite:
        conflict_resolution = ConflictResolution.OVERWRITE
        logger.warning(
            "Parameter 'overwrite' is deprecated. "
            "Use conflict_resolution=ConflictResolution.OVERWRITE instead."
        )
    
    # Validate and prepare paths
    try:
        resolved_modules = _resolve_module_paths(module_or_package)
    except ModuleOperationError as e:
        result.success = False
        result.errors.append(("resolution", e))
        return result
    
    target_path = Path(target) if target else Path.cwd()
    target_path = target_path.resolve()
    
    backup_path = Path(backup_dir) if backup_dir else target_path / ".backups"
    if conflict_resolution == ConflictResolution.BACKUP and not dry_run:
        backup_path.mkdir(parents=True, exist_ok=True)
    
    # Process each module
    for module_name, src_path in resolved_modules.items():
        result.processed += 1
        dst_path = target_path / src_path.name
        
        try:
            # Validate paths
            _validate_paths(src_path, dst_path)
            
            # Handle existing destination
            if dst_path.exists():
                should_proceed = _handle_conflict(
                    dst_path, conflict_resolution, backup_path
                )
                if not should_proceed:
                    result.skipped += 1
                    continue
                
                if not dry_run:
                    _remove_path(dst_path)
            
            # Perform the move
            if not dry_run:
                _lock_manager.acquire(src_path)
                _lock_manager.acquire(dst_path)
                try:
                    shutil.move(str(src_path), str(dst_path))
                finally:
                    _lock_manager.release(dst_path)
                    _lock_manager.release(src_path)
            
            result.succeeded += 1
            result.paths.append(dst_path)
            logger.info(f"Moved '{src_path}' -> '{dst_path}'")
            
        except Exception as e:
            result.failed += 1
            error = ModuleOperationError(
                f"Failed to move '{module_name}'",
                module_name=module_name,
                original_error=e,
                operation="move"
            )
            result.errors.append((module_name, error))
            logger.error(f"Move failed for '{module_name}': {e}")
    
    result.metadata["end_time"] = datetime.now().isoformat()
    result.success = (result.failed == 0)
    
    return result


def patch_copy(
    modules: List[str],
    target: Optional[Union[str, Path]] = None,
    conflict_resolution: ConflictResolution = ConflictResolution.ERROR,
    **kwargs
) -> OperationResult:
    """
    Copy multiple modules or packages in a single operation.
    
    This is an alias for copy() with explicit list parameter for
    backward compatibility and clarity when copying multiple items.
    
    Parameters
    ----------
    modules : List[str]
        List of module or package names to copy.
    target : Union[str, Path], optional
        Destination directory. If None, uses current working directory.
    conflict_resolution : ConflictResolution, default=ConflictResolution.ERROR
        Strategy for handling existing destination files/directories.
    **kwargs
        Additional keyword arguments passed to copy().
    
    Returns
    -------
    OperationResult
        Detailed result of the operation including statistics and errors.
    
    Examples
    --------
    >>> result = patch_copy(
    ...     ["module1", "module2", "package1"],
    ...     target="/destination",
    ...     conflict_resolution=ConflictResolution.BACKUP
    ... )
    """
    return copy(
        module_or_package=modules,
        target=target,
        conflict_resolution=conflict_resolution,
        **kwargs
    )


def patch_move(
    modules: List[str],
    target: Optional[Union[str, Path]] = None,
    conflict_resolution: ConflictResolution = ConflictResolution.ERROR,
    **kwargs
) -> OperationResult:
    """
    Move multiple modules or packages in a single operation.
    
    This is an alias for move() with explicit list parameter for
    backward compatibility and clarity when moving multiple items.
    
    Parameters
    ----------
    modules : List[str]
        List of module or package names to move.
    target : Union[str, Path], optional
        Destination directory. If None, uses current working directory.
    conflict_resolution : ConflictResolution, default=ConflictResolution.ERROR
        Strategy for handling existing destination files/directories.
    **kwargs
        Additional keyword arguments passed to move().
    
    Returns
    -------
    OperationResult
        Detailed result of the operation including statistics and errors.
    
    Examples
    --------
    >>> result = patch_move(
    ...     ["old_module1", "old_package"],
    ...     target="/archive",
    ...     conflict_resolution=ConflictResolution.OVERWRITE
    ... )
    """
    return move(
        module_or_package=modules,
        target=target,
        conflict_resolution=conflict_resolution,
        **kwargs
    )


def sync(
    package: str,
    target: Union[str, Path],
    direction: str = "source_to_target",
    delete_orphans: bool = False,
    conflict_resolution: ConflictResolution = ConflictResolution.OVERWRITE,
    ignore_patterns: Optional[List[str]] = None,
    checksum: bool = True,
    preserve_metadata: bool = True,
    backup_dir: Optional[Union[str, Path]] = None,
    dry_run: bool = False
) -> OperationResult:
    """
    Synchronize a package between its source location and a target directory.
    
    This function performs bidirectional or unidirectional synchronization
    between a Python package and a target directory, similar to rsync.
    It compares files by modification time and optionally checksum to
    determine which files need to be synchronized.
    
    Parameters
    ----------
    package : str
        Name of the package to synchronize.
    target : Union[str, Path]
        Target directory to synchronize with.
    direction : str, default="source_to_target"
        Synchronization direction:
        - "source_to_target": Copy newer files from package to target
        - "target_to_source": Copy newer files from target to package
        - "bidirectional": Synchronize both directions (latest wins)
    delete_orphans : bool, default=False
        If True, delete files in destination that don't exist in source.
        Only applies when direction is "source_to_target".
    conflict_resolution : ConflictResolution, default=ConflictResolution.OVERWRITE
        Strategy for handling conflicts during synchronization.
    ignore_patterns : List[str], optional
        List of glob patterns to ignore during synchronization.
    checksum : bool, default=True
        If True, use checksums to verify file differences when timestamps
        are identical. This prevents unnecessary copies but is slower.
    preserve_metadata : bool, default=True
        If True, preserve file metadata during synchronization.
    backup_dir : Union[str, Path], optional
        Directory for storing backups when conflict_resolution is BACKUP.
    dry_run : bool, default=False
        If True, simulate the operation without actually modifying files.
    
    Returns
    -------
    OperationResult
        Detailed result of the synchronization operation.
    
    Raises
    ------
    ModuleOperationError
        If critical errors occur during synchronization.
    ValueError
        If direction parameter is invalid.
    
    Examples
    --------
    >>> # Synchronize package to deployment directory
    >>> result = sync(
    ...     "my_package",
    ...     "/var/www/my_package",
    ...     direction="source_to_target",
    ...     delete_orphans=True
    ... )
    
    >>> # Bidirectional sync with ignore patterns
    >>> result = sync(
    ...     "dev_package",
    ...     "/backup/dev_package",
    ...     direction="bidirectional",
    ...     ignore_patterns=["*.pyc", "__pycache__", "*.log"]
    ... )
    
    >>> # Dry run to see what would be synchronized
    >>> result = sync(
    ...     "my_package",
    ...     "/target",
    ...     dry_run=True
    ... )
    >>> print(f"Would sync {result.metadata['files_to_sync']} files")
    """
    result = OperationResult()
    result.metadata["operation"] = "sync"
    result.metadata["start_time"] = datetime.now().isoformat()
    result.metadata["direction"] = direction
    
    # Initialize sync stats
    sync_stats = SyncStats()
    
    # Validate direction
    valid_directions = ["source_to_target", "target_to_source", "bidirectional"]
    if direction not in valid_directions:
        raise ValueError(
            f"Invalid direction '{direction}'. Must be one of {valid_directions}"
        )
    
    # Resolve package path
    try:
        src_path = _resolve_module_path(package)
    except ModuleOperationError as e:
        result.success = False
        result.errors.append((package, e))
        return result
    
    target_path = Path(target).resolve()
    
    # Validate paths
    try:
        _validate_paths(src_path, target_path, allow_same=False)
    except Exception as e:
        result.success = False
        result.errors.append(("validation", e))
        return result
    
    # Create target directory if it doesn't exist
    if not target_path.exists() and not dry_run:
        target_path.mkdir(parents=True, exist_ok=True)
    
    # Prepare ignore patterns
    ignore_patterns = ignore_patterns or []
    ignore_patterns.extend(["*.pyc", "__pycache__", "*.pyo", ".git", ".svn"])
    
    def should_ignore(path: Path) -> bool:
        """Check if a path should be ignored."""
        name = path.name
        for pattern in ignore_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False
    
    # Collect files for synchronization
    files_to_sync = []
    files_to_delete = []
    
    # Walk source directory
    src_files = {}
    if src_path.is_dir():
        for root, dirs, files in os.walk(src_path):
            # Filter directories
            dirs[:] = [d for d in dirs if not should_ignore(Path(root) / d)]
            
            for file in files:
                file_path = Path(root) / file
                if should_ignore(file_path):
                    continue
                    
                rel_path = file_path.relative_to(src_path)
                src_files[str(rel_path)] = {
                    "path": file_path,
                    "mtime": file_path.stat().st_mtime,
                    "size": file_path.stat().st_size
                }
                if checksum and file_path.is_file():
                    src_files[str(rel_path)]["hash"] = _compute_file_hash(file_path)
    else:
        # Single file package
        rel_path = src_path.name
        src_files[rel_path] = {
            "path": src_path,
            "mtime": src_path.stat().st_mtime,
            "size": src_path.stat().st_size
        }
        if checksum:
            src_files[rel_path]["hash"] = _compute_file_hash(src_path)
    
    # Walk target directory if it exists
    target_files = {}
    if target_path.exists():
        for root, dirs, files in os.walk(target_path):
            # Filter directories
            dirs[:] = [d for d in dirs if not should_ignore(Path(root) / d)]
            
            for file in files:
                file_path = Path(root) / file
                if should_ignore(file_path):
                    continue
                    
                rel_path = file_path.relative_to(target_path)
                target_files[str(rel_path)] = {
                    "path": file_path,
                    "mtime": file_path.stat().st_mtime,
                    "size": file_path.stat().st_size
                }
                if checksum and file_path.is_file():
                    target_files[str(rel_path)]["hash"] = _compute_file_hash(file_path)
    
    # Determine files to synchronize
    for rel_path, src_info in src_files.items():
        target_info = target_files.get(rel_path)
        
        if target_info is None:
            # File exists only in source
            if direction in ["source_to_target", "bidirectional"]:
                files_to_sync.append(("copy", src_info["path"],
                                    target_path / rel_path))
                sync_stats.bytes_to_transfer += src_info["size"]
        else:
            # File exists in both - check if different
            need_sync = False
            
            if src_info["mtime"] != target_info["mtime"]:
                need_sync = True
            elif src_info["size"] != target_info["size"]:
                need_sync = True
            elif checksum and src_info.get("hash") != target_info.get("hash"):
                need_sync = True
            
            if need_sync:
                if direction == "source_to_target":
                    files_to_sync.append(("update", src_info["path"],
                                        target_path / rel_path))
                    sync_stats.bytes_to_transfer += src_info["size"]
                elif direction == "target_to_source":
                    files_to_sync.append(("update", target_info["path"],
                                        src_path / rel_path))
                    sync_stats.bytes_to_transfer += target_info["size"]
                elif direction == "bidirectional":
                    # Sync the newer file
                    if src_info["mtime"] > target_info["mtime"]:
                        files_to_sync.append(("update", src_info["path"],
                                            target_path / rel_path))
                        sync_stats.bytes_to_transfer += src_info["size"]
                    else:
                        files_to_sync.append(("update", target_info["path"],
                                            src_path / rel_path))
                        sync_stats.bytes_to_transfer += target_info["size"]
    
    # Find orphaned files in target
    if delete_orphans and direction == "source_to_target":
        for rel_path, target_info in target_files.items():
            if rel_path not in src_files:
                files_to_delete.append(target_info["path"])
    
    # Update statistics
    sync_stats.files_to_sync = len(files_to_sync)
    sync_stats.files_to_delete = len(files_to_delete)
    
    result.metadata["sync_stats"] = sync_stats.to_dict()
    
    if dry_run:
        logger.info(f"Dry run: Would sync {len(files_to_sync)} files, "
                   f"delete {len(files_to_delete)} files")
        result.succeeded = len(files_to_sync)
        result.metadata["dry_run"] = True
        return result
    
    # Backup directory
    backup_path = None
    if conflict_resolution == ConflictResolution.BACKUP:
        backup_path = Path(backup_dir) if backup_dir else target_path / ".sync_backups"
        backup_path.mkdir(parents=True, exist_ok=True)
    
    # Process file copies
    for action, src_file, dst_file in files_to_sync:
        result.processed += 1
        
        try:
            # Create parent directory
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Handle existing destination
            if dst_file.exists():
                should_proceed = _handle_conflict(
                    dst_file, conflict_resolution, backup_path
                )
                if not should_proceed:
                    result.skipped += 1
                    continue
                
                _remove_path(dst_file)
            
            # Perform the copy
            _lock_manager.acquire(dst_file)
            try:
                if preserve_metadata:
                    shutil.copy2(src_file, dst_file)
                else:
                    shutil.copy(src_file, dst_file)
                    
                # Update stats
                sync_stats.files_copied += 1
                sync_stats.bytes_transferred += src_file.stat().st_size
            finally:
                _lock_manager.release(dst_file)
            
            result.succeeded += 1
            result.paths.append(dst_file)
            logger.debug(f"Synchronized: {src_file} -> {dst_file}")
            
        except Exception as e:
            result.failed += 1
            sync_stats.errors_count += 1
            error = ModuleOperationError(
                f"Failed to sync '{src_file}'",
                original_error=e,
                operation="sync"
            )
            result.errors.append((str(src_file), error))
            logger.error(f"Sync failed for '{src_file}': {e}")
    
    # Delete orphaned files
    for orphan in files_to_delete:
        try:
            if conflict_resolution == ConflictResolution.BACKUP:
                _create_backup(orphan)
            
            _lock_manager.acquire(orphan)
            try:
                _remove_path(orphan)
                sync_stats.files_deleted += 1
            finally:
                _lock_manager.release(orphan)
            
            logger.info(f"Deleted orphan: {orphan}")
        except Exception as e:
            sync_stats.warnings_count += 1
            result.warnings.append(f"Failed to delete orphan '{orphan}': {e}")
            logger.warning(f"Failed to delete orphan '{orphan}': {e}")
    
    # Clean up empty directories in target (if delete_orphans)
    if delete_orphans and direction == "source_to_target":
        for root, dirs, files in os.walk(target_path, topdown=False):
            if root != str(target_path):
                try:
                    if not os.listdir(root):
                        os.rmdir(root)
                        logger.debug(f"Removed empty directory: {root}")
                except OSError:
                    pass  # Directory not empty or permission denied
    
    result.metadata["end_time"] = datetime.now().isoformat()
    result.metadata["sync_stats"] = sync_stats.to_dict()
    result.success = (result.failed == 0)
    
    return result


def verify(
    module_or_package: Union[str, List[str]],
    reference: Optional[Union[str, Path]] = None,
    checksum: bool = True
) -> VerificationResult:
    """
    Verify the integrity of modules or packages.
    
    This function checks that modules exist and optionally verifies
    their contents against a reference location using checksums.
    
    Parameters
    ----------
    module_or_package : Union[str, List[str]]
        Module(s) or package(s) to verify.
    reference : Union[str, Path], optional
        Reference directory to compare against. If None, only verifies
        that modules exist and are accessible.
    checksum : bool, default=True
        If True and reference is provided, verify file contents using
        cryptographic checksums.
    
    Returns
    -------
    VerificationResult
        Structured verification results with detailed module information.
    
    Examples
    --------
    >>> # Verify modules exist
    >>> result = verify(["numpy", "pandas", "requests"])
    >>> print(f"Found: {result.exists}")
    >>> print(f"Missing: {result.missing}")
    >>> print(f"All verified: {result.all_verified}")
    
    >>> # Verify against reference copy
    >>> result = verify(
    ...     "my_package",
    ...     reference="/backup/my_package",
    ...     checksum=True
    ... )
    >>> if result.mismatched:
    ...     print("Package differs from backup!")
    """
    if isinstance(module_or_package, str):
        modules_to_check = [module_or_package]
    else:
        modules_to_check = module_or_package
    
    result = VerificationResult()
    result.summary["total"] = len(modules_to_check)
    
    reference_path = Path(reference) if reference else None
    
    for module_name in modules_to_check:
        try:
            # Check if module exists
            module_path = _resolve_module_path(module_name)
            
            # Create ModuleInfo object
            module_info = ModuleInfo(name=module_name)
            module_info.path = module_path
            module_info.exists = True
            module_info.module_type = "package" if module_path.is_dir() else "module"
            
            # Get file stats
            stat_info = module_path.stat()
            module_info.modified = datetime.fromtimestamp(stat_info.st_mtime)
            module_info.permissions = oct(stat_info.st_mode)[-3:]
            module_info.is_symlink = module_path.is_symlink()
            
            # Calculate size and file count
            if module_path.is_file():
                module_info.size = stat_info.st_size
                module_info.file_count = 1
            else:
                total_size = 0
                file_count = 0
                for root, dirs, files in os.walk(module_path):
                    file_count += len(files)
                    for file in files:
                        file_path = Path(root) / file
                        try:
                            total_size += file_path.stat().st_size
                        except OSError:
                            pass
                module_info.size = total_size
                module_info.file_count = file_count
            
            result.exists.append(module_name)
            result.verified_modules.append(module_info)
            
            # Compare with reference if provided
            if reference_path:
                ref_module_path = reference_path / module_path.name
                
                if not ref_module_path.exists():
                    result.mismatched.append(module_name)
                    continue
                
                # Compare contents
                mismatched = False
                if checksum:
                    if module_path.is_file() and ref_module_path.is_file():
                        src_hash = _compute_file_hash(module_path)
                        ref_hash = _compute_file_hash(ref_module_path)
                        
                        if src_hash != ref_hash:
                            mismatched = True
                    else:
                        # Directory comparison
                        comparison = filecmp.dircmp(
                            module_path, ref_module_path
                        )
                        if (comparison.left_only or comparison.right_only or
                            comparison.diff_files):
                            mismatched = True
                
                if mismatched:
                    result.mismatched.append(module_name)
                
        except ModuleNotFoundInSysPath:
            result.missing.append(module_name)
            # Add minimal ModuleInfo for missing module
            missing_info = ModuleInfo(
                name=module_name,
                exists=False,
                error="Module not found in sys.path"
            )
            result.verified_modules.append(missing_info)
            
        except Exception as e:
            result.errors.append((module_name, str(e)))
            # Add ModuleInfo with error
            error_info = ModuleInfo(
                name=module_name,
                exists=False,
                error=str(e)
            )
            result.verified_modules.append(error_info)
            logger.error(f"Verification failed for '{module_name}': {e}")
    
    # Update summary
    result.summary.update({
        "verified": len(result.exists),
        "missing": len(result.missing),
        "mismatched": len(result.mismatched),
        "failed": len(result.errors)
    })
    
    result.timestamp = datetime.now().isoformat()
    
    return result


def info(module_or_package: Union[str, List[str]]) -> Dict[str, ModuleInfo]:
    """
    Get detailed information about modules or packages.
    
    This function retrieves metadata and filesystem information about
    the specified modules or packages.
    
    Parameters
    ----------
    module_or_package : Union[str, List[str]]
        Module(s) or package(s) to get information for.
    
    Returns
    -------
    Dict[str, ModuleInfo]
        Dictionary mapping module names to their detailed information.
    
    Examples
    --------
    >>> # Get info about a single module
    >>> info_dict = info("requests")
    >>> req_info = info_dict["requests"]
    >>> print(f"Requests is at: {req_info.path}")
    >>> print(f"Size: {req_info.size} bytes")
    >>> print(f"Type: {req_info.module_type}")
    
    >>> # Get info about multiple packages
    >>> info_dict = info(["numpy", "pandas", "scipy"])
    >>> for name, module_info in info_dict.items():
    ...     print(f"{name}: {module_info.module_type} at {module_info.path}")
    ...     print(f"  Files: {module_info.file_count}, Size: {module_info.size}")
    """
    if isinstance(module_or_package, str):
        modules = [module_or_package]
    else:
        modules = module_or_package
    
    result = {}
    
    for module_name in modules:
        try:
            path = _resolve_module_path(module_name)
            
            # Create ModuleInfo object
            module_info = ModuleInfo(
                name=module_name,
                path=str(path),
                exists=True,
                module_type="package" if path.is_dir() else "module"
            )
            
            stat_info = path.stat()
            module_info.modified = datetime.fromtimestamp(stat_info.st_mtime).isoformat()
            module_info.permissions = oct(stat_info.st_mode)[-3:]
            module_info.is_symlink = path.is_symlink()
            
            # Calculate size and file count
            if path.is_file():
                module_info.size = stat_info.st_size
                module_info.file_count = 1
            else:
                total_size = 0
                file_count = 0
                python_files = 0
                
                for root, dirs, files in os.walk(path):
                    file_count += len(files)
                    for file in files:
                        file_path = Path(root) / file
                        try:
                            file_size = file_path.stat().st_size
                            total_size += file_size
                            
                            if file.endswith('.py'):
                                python_files += 1
                        except OSError:
                            pass
                
                module_info.size = total_size
                module_info.file_count = file_count
                module_info.metadata["python_files"] = python_files
            
            # Add Python-specific metadata
            if path.is_dir():
                init_file = path / "__init__.py"
                module_info.metadata["has_init"] = init_file.exists()
            
            result[module_name] = module_info
            
        except Exception as e:
            error_info = ModuleInfo(
                name=module_name,
                exists=False,
                error=str(e)
            )
            result[module_name] = error_info
    
    return result


def setup_logging(level: int = logging.INFO, handler: Optional[logging.Handler] = None) -> None:
    """
    Configure logging for the module operations.
    
    Parameters
    ----------
    level : int, default=logging.INFO
        Logging level (e.g., logging.DEBUG, logging.INFO).
    handler : logging.Handler, optional
        Custom log handler. If None, a StreamHandler is created.
    
    Examples
    --------
    >>> import logging
    >>> setup_logging(level=logging.DEBUG)
    >>> # Or with custom handler
    >>> file_handler = logging.FileHandler("module_ops.log")
    >>> setup_logging(handler=file_handler)
    """
    if handler is None:
        handler = logging.StreamHandler()
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    logger.setLevel(level)


# Clean up handler on module removal
def _cleanup_logging():
    """Clean up logging handlers (called on module cleanup)."""
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)


import atexit
atexit.register(_cleanup_logging)