#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Module Backup System
=============================

A robust, production-ready backup solution for Python modules with integrity checking,
compression, retention policies, cross-platform compatibility, and comprehensive error handling.

This module provides a complete backup management system that can:
- Create compressed or uncompressed backups of any Python module or package
- Restore backups with integrity verification
- Manage backup retention policies
- Track backup metadata in JSON indexes

Example
-------
>>> from pyputil.core import ModuleBackup
>>> 
>>> # Initialize backup manager for a module
>>> backup_mgr = ModuleBackup("requests")
>>> 
>>> # Create a backup
>>> result = backup_mgr.backup(compress=True, message="Pre-upgrade backup")
>>> print(result.status)  # BackupStatus.SUCCESS
>>> 
>>> # List all backups
>>> backups = backup_mgr.list_backups()
>>> for backup in backups:
...     print(f"{backup.name}: {backup.created_at}")
>>> 
>>> # Restore a specific backup
>>> restore_result = backup_mgr.restore(stamp="20231215T143045Z")
>>> print(restore_result.message)
"""

import shutil
import zipfile
import json
import hashlib
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from contextlib import contextmanager
import importlib.util
import logging

from .base import (
	BackupFormat,
	BackupStatus,
	ErrorSeverity,
	BackupEntry,
	BackupResult,
	RestoreResult,
	VerificationResult,
	CleanupResult,
	BackupInfo
)
from .exceptions import (
	ModuleNotFoundError,
	BackupCorruptedError,
	BackupNotFoundError,
	BackupError
)



# =============================================================================
# MAIN MODULEBACKUP CLASS
# =============================================================================

class ModuleBackup:
    """
    Advanced backup manager for Python modules and packages.
    
    This class provides comprehensive backup functionality including:
    - Creating compressed (ZIP) or uncompressed (directory) backups
    - Restoring backups with integrity verification
    - Automatic retention policy management
    - Checksum verification for data integrity
    - Cross-platform compatibility (Windows, Linux, macOS)
    - Thread-safe operations
    - Comprehensive logging and error handling
    
    Parameters
    ----------
    module_name : str
        Name of the Python module or package to backup
    backup_root : Optional[str], optional
        Root directory for storing backups. If None, uses default
        location in module's parent directory (./.backup_<module_name>)
    enable_checksum : bool, optional
        Whether to calculate and verify SHA-256 checksums. Default is True
    enable_logging : bool, optional
        Whether to enable internal logging. Default is True
    log_level : int, optional
        Logging level (DEBUG, INFO, WARNING, ERROR). Default is logging.INFO
    max_retries : int, optional
        Maximum retry attempts for failed operations. Default is 3
    
    Attributes
    ----------
    module_name : str
        Name of the module being backed up
    module_path : Path
        Absolute filesystem path to the module
    backups_root : Path
        Root directory where backups are stored
    index_file : Path
        Path to the JSON index file containing backup metadata
    
    Examples
    --------
    Basic usage:
    
    >>> from pyputil.core import ModuleBackup
    >>> 
    >>> # Initialize backup manager for a module
    >>> backup = ModuleBackup("my_package")
    >>> 
    >>> # Create a compressed backup with a message
    >>> result = backup.backup(
    ...     compress=True,
    ...     message="Pre-deployment backup",
    ...     max_backups=10
    ... )
    >>> if result.is_success():
    ...     print(f"Backup created: {result.location}")
    ...     print(f"Size: {result.backup.size_bytes} bytes")
    ... 
    >>> # List all backups
    >>> backups = backup.list_backups()
    >>> for bkp in backups:
    ...     print(f"{bkp.name} - {bkp.created_at} - {bkp.message}")
    ... 
    >>> # Restore the latest backup
    >>> restore_result = backup.restore(overwrite=True)
    >>> if restore_result.is_success():
    ...     print(f"Restored {restore_result.restored_files} files")
    ... 
    >>> # Clean up old backups keeping only the 5 most recent
    >>> cleanup_result = backup.cleanup(keep_latest=5)
    >>> print(f"Removed {cleanup_result.removed_count} old backups")
    
    Advanced usage with custom settings:
    
    >>> # Create backup manager with custom backup root and checksums disabled
    >>> backup = ModuleBackup(
    ...     module_name="my_module",
    ...     backup_root="/custom/backup/path",
    ...     enable_checksum=False,
    ...     max_retries=5
    ... )
    >>> 
    >>> # Create directory backup (not compressed) with custom message
    >>> result = backup.backup(
    ...     compress=False,
    ...     message="Development snapshot",
    ...     max_backups=20
    ... )
    >>> 
    >>> # Verify backup integrity
    >>> verify_result = backup.verify_backup(stamp=result.backup.stamp)
    >>> if verify_result.is_valid:
    ...     print("Backup integrity verified")
    """
    
    def __init__(
        self,
        module_name: str,
        backup_root: Optional[str] = None,
        enable_checksum: bool = True,
        enable_logging: bool = True,
        log_level: int = logging.INFO,
        max_retries: int = 3
    ) -> None:
        """
        Initialize the ModuleBackup instance with the specified configuration.
        
        This constructor sets up the backup environment, locates the target module,
        creates necessary directories, and initializes the backup index.
        
        Parameters
        ----------
        module_name : str
            Name of the Python module or package to backup
        backup_root : Optional[str], optional
            Custom root directory for backups. If None, uses 
            ./backups_<module_name> in current working directory
        enable_checksum : bool, optional
            Enable SHA-256 checksum calculation for integrity verification
        enable_logging : bool, optional
            Enable internal logging
        log_level : int, optional
            Logging level (use logging.DEBUG, INFO, etc.)
        max_retries : int, optional
            Maximum retry attempts for I/O operations
        
        Raises
        ------
        ModuleNotFoundError
            If the Python module cannot be found in the import path
        BackupError
            If backup directory cannot be created or other initialization fails
        
        Examples
        --------
        >>> # Standard initialization with default settings
        >>> backup = ModuleBackup("requests")
        >>> 
        >>> # Custom backup location and verbose logging
        >>> backup = ModuleBackup(
        ...     module_name="my_package",
        ...     backup_root="/var/backups/my_package",
        ...     enable_logging=True,
        ...     log_level=logging.DEBUG
        ... )
        >>> 
        >>> # Disable checksums for faster backups (less integrity checking)
        >>> backup = ModuleBackup("my_module", enable_checksum=False)
        """
        self.module_name = module_name
        self.enable_checksum = enable_checksum
        self.max_retries = max_retries
        
        # Setup logging
        self.logger = None
        if enable_logging:
            self._setup_logging(log_level)
        
        # Locate the module
        self.logger and self.logger.debug(f"Locating module: {module_name}")
        self.module_path = self._find_module_path(module_name)
        self.logger and self.logger.info(f"Module found at: {self.module_path}")
        
        # Determine backup root directory
        if backup_root:
            self.backups_root = Path(backup_root).resolve()
        else:
            self.backups_root = Path.cwd() / f"backups_{self.module_name}"
        
        # Create backup directory structure
        self._initialize_backup_directory()
        
        # Initialize backup index
        self.index_file = self.backups_root / "backups_index.json"
        self._lock = threading.RLock()  # For thread-safe operations
        self._initialize_index()
        
        self.logger and self.logger.info(f"ModuleBackup initialized for '{module_name}'")
    
    # -------------------------------------------------------------------------
    # PRIVATE INITIALIZATION METHODS
    # -------------------------------------------------------------------------
    
    def _setup_logging(self, log_level: int) -> None:
        """
        Configure internal logging system.
        
        Sets up a logger with console handler and formatted output.
        
        Parameters
        ----------
        log_level : int
            Logging level (logging.DEBUG, INFO, WARNING, ERROR)
        
        Examples
        --------
        >>> backup = ModuleBackup("module", enable_logging=True, log_level=logging.DEBUG)
        >>> # Now sees debug messages during operations
        """
        self.logger = logging.getLogger(f"ModuleBackup.{self.module_name}")
        self.logger.setLevel(log_level)
        
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def _find_module_path(self, module_name: str) -> Path:
        """
        Locate the filesystem path of a Python module or package.
        
        Uses importlib to find the module specification and resolves
        the absolute path. Handles both single-file modules and packages.
        
        Parameters
        ----------
        module_name : str
            Name of the module to locate
        
        Returns
        -------
        Path
            Absolute filesystem path to the module
        
        Raises
        ------
        ModuleNotFoundError
            If module cannot be found in Python's import path
        BackupError
            If module path doesn't exist on disk
        
        Examples
        --------
        >>> backup = ModuleBackup("os")
        >>> print(backup.module_path)
        /usr/lib/python3.9/os.py
        
        >>> backup = ModuleBackup("json")
        >>> print(backup.module_path)
        /usr/lib/python3.9/json/__init__.py
        """
        try:
            spec = importlib.util.find_spec(module_name)
            if spec is None or spec.origin is None:
                raise ModuleNotFoundError(module_name)
            
            module_path = Path(spec.origin).resolve()
            
            if not module_path.exists():
                raise BackupError(
                    f"Module path does not exist: {module_path}",
                    operation="find_module"
                )
            
            # For packages, the __init__.py indicates the package root
            if module_path.name == "__init__.py":
                module_path = module_path.parent
            
            return module_path
            
        except ModuleNotFoundError:
            self.logger and self.logger.error(f"Module '{module_name}' not found")
            raise ModuleNotFoundError(module_name)
        except Exception as e:
            self.logger and self.logger.error(f"Error locating module: {e}")
            raise BackupError(
                f"Failed to locate module '{module_name}': {e}",
                operation="find_module",
                original_exception=e
            )
    
    def _initialize_backup_directory(self) -> None:
        """
        Create and prepare the backup root directory.
        
        Creates the backups root directory if it doesn't exist and ensures
        proper permissions for read/write operations.
        
        Raises
        ------
        BackupError
            If directory cannot be created due to permissions or other issues
        
        Examples
        --------
        >>> backup = ModuleBackup("module")
        >>> # Backup directory automatically created at initialization
        """
        try:
            self.backups_root.mkdir(parents=True, exist_ok=True)
            self.logger and self.logger.debug(f"Backup directory: {self.backups_root}")
            
            # Test write permissions
            test_file = self.backups_root / ".write_test"
            test_file.touch()
            if test_file.exists():
                test_file.unlink()
            
        except PermissionError as e:
            raise BackupError(
                f"Permission denied creating backup directory: {self.backups_root}",
                operation="initialize",
                original_exception=e,
                severity=ErrorSeverity.CRITICAL
            )
        except Exception as e:
            raise BackupError(
                f"Failed to create backup directory: {e}",
                operation="initialize",
                original_exception=e
            )
    
    def _initialize_index(self) -> None:
        """
        Initialize or load the backup index file.
        
        Creates an empty index if it doesn't exist, otherwise loads
        existing backup metadata.
        
        Raises
        ------
        BackupError
            If index file is corrupted or cannot be read/written
        
        Examples
        --------
        >>> backup = ModuleBackup("module")
        >>> # Index automatically initialized if needed
        """
        if not self.index_file.exists():
            self._write_index([])
            self.logger and self.logger.debug("Created new backup index")
        else:
            # Validate existing index
            try:
                entries = self._read_index()
                self.logger and self.logger.info(f"Loaded index with {len(entries)} backups")
                
                # Validate backup files still exist
                for entry in entries[:]:
                    if not self._backup_exists(entry):
                        self.logger and self.logger.warning(f"Backup missing: {entry.stamp}")
                        entries.remove(entry)
                
                if len(entries) != len(self._read_index()):
                    self._write_index(entries)
                    
            except Exception as e:
                self.logger and self.logger.error(f"Failed to load index: {e}")
                # Backup corrupted index and start fresh
                backup_file = self.index_file.with_suffix(".json.corrupted")
                shutil.copy2(self.index_file, backup_file)
                self.logger and self.logger.warning(f"Backed up corrupted index to {backup_file}")
                self._write_index([])
    
    # -------------------------------------------------------------------------
    # PRIVATE INDEX MANAGEMENT METHODS
    # -------------------------------------------------------------------------
    
    def _read_index(self) -> List[BackupEntry]:
        """
        Read and parse the backup index JSON file.
        
        Returns
        -------
        List[BackupEntry]
            List of backup entries sorted by creation date (newest first)
        
        Examples
        --------
        >>> entries = backup._read_index()
        >>> for entry in entries:
        ...     print(f"Backup: {entry.name}, Created: {entry.created_at}")
        """
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                entries = [BackupEntry.from_dict(item) for item in data]
                # Sort by created_at descending (newest first)
                entries.sort(key=lambda x: x.created_at, reverse=True)
                return entries
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as e:
            self.logger and self.logger.error(f"Corrupted index file: {e}")
            return []
    
    def _write_index(self, entries: List[BackupEntry]) -> None:
        """
        Write backup index data to the JSON file.
        
        Parameters
        ----------
        entries : List[BackupEntry]
            List of backup entries to write to disk
        
        Raises
        ------
        BackupError
            If unable to write to index file
        
        Examples
        --------
        >>> entries = backup._read_index()
        >>> entries.append(new_backup)
        >>> backup._write_index(entries)
        """
        try:
            # Write to temporary file first, then rename for atomic operation
            temp_file = self.index_file.with_suffix(".json.tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(
                    [entry.to_dict() for entry in entries],
                    f,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True
                )
            temp_file.replace(self.index_file)
            
        except Exception as e:
            raise BackupError(
                f"Failed to write index: {e}",
                operation="write_index",
                original_exception=e
            )
    
    def _backup_exists(self, entry: BackupEntry) -> bool:
        """
        Check if backup files actually exist on disk.
        
        Parameters
        ----------
        entry : BackupEntry
            Backup entry to verify existence
        
        Returns
        -------
        bool
            True if backup files exist, False otherwise
        
        Examples
        --------
        >>> entry = backup._read_index()[0]
        >>> if backup._backup_exists(entry):
        ...     print("Backup files are present")
        """
        if entry.archive:
            return Path(entry.archive).exists()
        else:
            return (self.backups_root / entry.name).exists()
    
    # -------------------------------------------------------------------------
    # PRIVATE BACKUP OPERATION METHODS
    # -------------------------------------------------------------------------
    
    def _make_stamp(self) -> str:
        """
        Generate a unique timestamp identifier for backups.
        
        Creates UTC timestamp in ISO-like format without separators,
        suitable for use in filenames and as unique identifiers.
        
        Returns
        -------
        str
            Timestamp in format 'YYYYmmddTHHMMSSZ'
        
        Examples
        --------
        >>> stamp = backup._make_stamp()
        >>> print(stamp)
        '20231215T143045Z'
        >>> len(stamp)
        16
        """
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    
    def _calculate_checksum(self, path: Path) -> str:
        """
        Calculate SHA-256 checksum of a file or directory.
        
        For directories, computes combined checksum of all files in
        deterministic order.
        
        Parameters
        ----------
        path : Path
            File or directory path to calculate checksum for
        
        Returns
        -------
        str
            Hexadecimal SHA-256 checksum string
        
        Examples
        --------
        >>> checksum = backup._calculate_checksum(Path("my_module.py"))
        >>> print(checksum[:16])
        'e3b0c44298fc1c14'
        """
        sha256 = hashlib.sha256()
        
        if path.is_file():
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
        else:
            # For directories, checksum all files in sorted order
            for file_path in sorted(path.rglob("*")):
                if file_path.is_file():
                    rel_path = str(file_path.relative_to(path))
                    sha256.update(rel_path.encode())
                    with open(file_path, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def _count_files(self, path: Path) -> int:
        """
        Count the number of files in a directory or file.
        
        Parameters
        ----------
        path : Path
            File or directory path to count files in
        
        Returns
        -------
        int
            Number of files (1 for a single file, recursively for directories)
        
        Examples
        --------
        >>> count = backup._count_files(Path("my_package"))
        >>> print(f"Package contains {count} files")
        """
        if path.is_file():
            return 1
        return sum(1 for _ in path.rglob("*") if _.is_file())
    
    def _get_directory_size(self, path: Path) -> int:
        """
        Calculate total size of a directory or file in bytes.
        
        Parameters
        ----------
        path : Path
            File or directory path to calculate size for
        
        Returns
        -------
        int
            Total size in bytes
        
        Examples
        --------
        >>> size = backup._get_directory_size(Path("my_module.py"))
        >>> print(f"Size: {size / 1024:.2f} KB")
        """
        if path.is_file():
            return path.stat().st_size
        
        total = 0
        for file_path in path.rglob("*"):
            if file_path.is_file():
                total += file_path.stat().st_size
        return total
    
    @contextmanager
    def _retry_on_error(self, operation: str, max_retries: Optional[int] = None):
        """
        Context manager for retrying operations on transient errors.
        
        Parameters
        ----------
        operation : str
            Name of the operation for logging
        max_retries : Optional[int], optional
            Maximum retry attempts, defaults to instance max_retries
        
        Yields
        ------
        None
        
        Raises
        ------
        BackupError
            After exhausting all retry attempts
        
        Examples
        --------
        >>> with backup._retry_on_error("backup_copy"):
        ...     shutil.copytree(source, dest)
        """
        retries = max_retries if max_retries is not None else self.max_retries
        last_exception = None
        
        for attempt in range(retries + 1):
            try:
                yield
                return
            except (OSError, IOError, PermissionError) as e:
                last_exception = e
                if attempt < retries:
                    wait_time = 0.5 * (2 ** attempt)  # Exponential backoff
                    self.logger and self.logger.warning(
                        f"Retry {attempt + 1}/{retries} for {operation} after {wait_time}s: {e}"
                    )
                    time.sleep(wait_time)
                else:
                    self.logger and self.logger.error(f"Failed {operation} after {retries} retries")
                    raise BackupError(
                        f"Failed {operation} after {retries} retries: {e}",
                        operation=operation,
                        original_exception=e
                    )
    
    def _copy_module_content(self, source: Path, target: Path, use_retry: bool = True) -> int:
        """
        Copy module content from source to target with retry support.
        
        Parameters
        ----------
        source : Path
            Source module path
        target : Path
            Target backup path
        use_retry : bool, optional
            Whether to use retry mechanism, default True
        
        Returns
        -------
        int
            Number of files copied
        
        Raises
        ------
        BackupError
            If copying fails after retries
        
        Examples
        --------
        >>> count = backup._copy_module_content(source_path, target_path)
        >>> print(f"Copied {count} files")
        """
        def copy_operation():
            if source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                return 1
            else:
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target, symlinks=False, ignore_dangling_symlinks=True)
                return self._count_files(target)
        
        if use_retry:
            with self._retry_on_error("copy_module_content"):
                return copy_operation()
        else:
            return copy_operation()
    
    def _create_zip_archive(
        self,
        source_dir: Path,
        archive_path: Path,
        base_name: str,
        compression_level: int = 6
    ) -> Tuple[int, int]:
        """
        Create a ZIP archive from a directory with compression.
        
        Parameters
        ----------
        source_dir : Path
            Directory to compress
        archive_path : Path
            Path for the resulting ZIP file
        base_name : str
            Base name for archive entries (top-level folder name)
        compression_level : int, optional
            ZIP compression level (1-9), default 6
        
        Returns
        -------
        Tuple[int, int]
            (file_count, total_size) - Number of files added and archive size
        
        Raises
        ------
        BackupError
            If ZIP creation fails
        
        Examples
        --------
        >>> file_count, size = backup._create_zip_archive(
        ...     source_dir=Path("temp_backup"),
        ...     archive_path=Path("backup.zip"),
        ...     base_name="my_module_20231215"
        ... )
        >>> print(f"Added {file_count} files, archive size: {size} bytes")
        """
        file_count = 0
        total_size = 0
        
        try:
            with zipfile.ZipFile(
                archive_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=compression_level
            ) as zf:
                for file_path in source_dir.rglob("*"):
                    if file_path.is_file():
                        arcname = str(Path(base_name) / file_path.relative_to(source_dir))
                        zf.write(file_path, arcname=arcname)
                        file_count += 1
                        total_size += file_path.stat().st_size
            
            self.logger and self.logger.debug(
                f"Created ZIP archive: {file_count} files, {total_size} bytes, "
                f"compressed to {archive_path.stat().st_size} bytes"
            )
            
            return file_count, total_size
            
        except Exception as e:
            raise BackupError(
                f"Failed to create ZIP archive: {e}",
                operation="create_zip",
                original_exception=e
            )
    
    def _apply_retention_policy(self, entries: List[BackupEntry], max_backups: int) -> CleanupResult:
        """
        Apply retention policy by removing oldest backups beyond limit.
        
        Parameters
        ----------
        entries : List[BackupEntry]
            List of backup entries (already sorted newest first)
        max_backups : int
            Maximum number of backups to keep
        
        Returns
        -------
        CleanupResult
            Result of retention policy application
        
        Examples
        --------
        >>> entries = backup._read_index()
        >>> result = backup._apply_retention_policy(entries, 10)
        >>> print(f"Removed {result.removed_count} old backups")
        """
        if len(entries) <= max_backups:
            return CleanupResult(
                status=BackupStatus.SUCCESS,
                kept_count=len(entries),
                removed_count=0,
                message="No backups needed removal"
            )
        
        removed_stamps = []
        freed_bytes = 0
        
        # Remove oldest backups (those beyond max_backups)
        for entry in entries[max_backups:]:
            try:
                # Remove backup files
                if entry.archive and Path(entry.archive).exists():
                    size = Path(entry.archive).stat().st_size
                    Path(entry.archive).unlink()
                    freed_bytes += size
                
                backup_dir = self.backups_root / entry.name
                if backup_dir.exists():
                    size = self._get_directory_size(backup_dir)
                    shutil.rmtree(backup_dir)
                    freed_bytes += size
                
                removed_stamps.append(entry.stamp)
                self.logger and self.logger.info(f"Removed old backup: {entry.stamp}")
                
            except Exception as e:
                self.logger and self.logger.error(f"Failed to remove backup {entry.stamp}: {e}")
        
        # Keep only the most recent backups
        del entries[max_backups:]
        
        return CleanupResult(
            status=BackupStatus.SUCCESS,
            kept_count=len(entries),
            removed_count=len(removed_stamps),
            freed_bytes=freed_bytes,
            removed_stamps=removed_stamps,
            message=f"Removed {len(removed_stamps)} old backups"
        )
    
    # -------------------------------------------------------------------------
    # PRIVATE RESTORE METHODS
    # -------------------------------------------------------------------------
    
    def _extract_archive(self, archive_path: Path, stamp: str) -> Path:
        """
        Extract ZIP archive to a temporary directory.
        
        Parameters
        ----------
        archive_path : Path
            Path to ZIP archive
        stamp : str
            Backup stamp for naming temporary directory
        
        Returns
        -------
        Path
            Path to extracted directory root
        
        Raises
        ------
        BackupError
            If extraction fails
        
        Examples
        --------
        >>> extracted = backup._extract_archive(Path("backup.zip"), "20231215T143045Z")
        >>> print(f"Extracted to: {extracted}")
        """
        temp_dir = self.backups_root / f"__extract__{stamp}"
        
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            with zipfile.ZipFile(archive_path, "r") as zf:
                # Verify archive integrity first
                bad_file = zf.testzip()
                if bad_file:
                    raise BackupCorruptedError(stamp, f"Corrupted file in archive: {bad_file}")
                zf.extractall(temp_dir)
            
            # Find the extracted root directory (may have one top-level folder)
            extracted_items = list(temp_dir.iterdir())
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                return extracted_items[0]
            return temp_dir
            
        except zipfile.BadZipFile as e:
            raise BackupCorruptedError(stamp, "Invalid ZIP archive format", original_exception=e)
        except Exception as e:
            raise BackupError(
                f"Failed to extract archive: {e}",
                operation="extract_archive",
                original_exception=e
            )
    
    def _restore_files(self, source: Path, destination: Path, overwrite: bool) -> int:
        """
        Restore files from source to destination with safety checks.
        
        Parameters
        ----------
        source : Path
            Source directory or file to restore from
        destination : Path
            Destination path to restore to
        overwrite : bool
            Whether to overwrite existing files/directories
        
        Returns
        -------
        int
            Number of files restored
        
        Raises
        ------
        BackupError
            If restore fails
        
        Examples
        --------
        >>> count = backup._restore_files(
        ...     source=Path("backup/my_module"),
        ...     destination=Path("/path/to/module"),
        ...     overwrite=True
        ... )
        >>> print(f"Restored {count} files")
        """
        try:
            # Handle existing destination
            if destination.exists():
                if overwrite:
                    if destination.is_file():
                        destination.unlink()
                    else:
                        shutil.rmtree(destination)
                else:
                    raise BackupError(
                        f"Destination exists and overwrite=False: {destination}",
                        operation="restore_files"
                    )
            
            # Perform restore
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=False)
                file_count = self._count_files(destination)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                file_count = 1
            
            self.logger and self.logger.info(f"Restored {file_count} files to {destination}")
            return file_count
            
        except Exception as e:
            raise BackupError(
                f"Failed to restore files: {e}",
                operation="restore_files",
                original_exception=e
            )
    
    # -------------------------------------------------------------------------
    # PUBLIC BACKUP OPERATIONS
    # -------------------------------------------------------------------------
    
    def backup(
        self,
        compress: bool = True,
        message: Optional[str] = None,
        max_backups: Optional[int] = None,
        compression_level: int = 6,
        verify_after: bool = True
    ) -> BackupResult:
        """
        Create a new backup of the module.
        
        This method creates a timestamped backup of the module, either as
        a compressed ZIP archive or as a directory copy. It optionally applies
        retention policies and verifies the backup after creation.
        
        Parameters
        ----------
        compress : bool, optional
            If True, create compressed ZIP archive. If False, create directory copy.
            Default is True.
        message : Optional[str], optional
            User description or note for the backup. Default is None.
        max_backups : Optional[int], optional
            Maximum number of backups to keep. Oldest backups will be removed.
            If None, keeps all backups. Default is None.
        compression_level : int, optional
            ZIP compression level (1-9, where 9 is maximum compression).
            Only used if compress=True. Default is 6.
        verify_after : bool, optional
            Whether to verify backup integrity after creation. Default is True.
        
        Returns
        -------
        BackupResult
            Object containing operation status, backup metadata, and details
        
        Raises
        ------
        BackupError
            If backup creation fails (wrapped in BackupResult with error status)
        
        Examples
        --------
        >>> # Create a basic compressed backup
        >>> result = backup.backup()
        >>> if result.is_success():
        ...     print(f"Backup created: {result.location}")
        ...     print(f"Backup size: {result.backup.size_bytes} bytes")
        
        >>> # Create an uncompressed backup with message
        >>> result = backup.backup(
        ...     compress=False,
        ...     message="Development snapshot before refactoring",
        ...     max_backups=10
        ... )
        
        >>> # Create a highly compressed backup (slower but smaller)
        >>> result = backup.backup(
        ...     compress=True,
        ...     compression_level=9,
        ...     verify_after=True
        ... )
        
        >>> # Create backup with retention policy (keep only 5 latest)
        >>> result = backup.backup(max_backups=5)
        >>> if not result.is_success():
        ...     print(f"Warning: {result.message}")
        ...     for warning in result.warnings:
        ...         print(f"  - {warning}")
        """
        start_time = time.time()
        stamp = self._make_stamp()
        base_name = f"{self.module_name}_{stamp}"
        warnings = []
        
        self.logger and self.logger.info(f"Starting backup of '{self.module_name}' (stamp: {stamp})")
        
        with self._lock:
            try:
                # Create temporary directory for backup assembly
                temp_backup_dir = self.backups_root / f"__temp_{stamp}"
                if temp_backup_dir.exists():
                    shutil.rmtree(temp_backup_dir)
                temp_backup_dir.mkdir(parents=True, exist_ok=False)
                
                # Copy module content to temporary directory
                self.logger and self.logger.debug("Copying module content...")
                file_count = self._copy_module_content(self.module_path, temp_backup_dir / self.module_path.name)
                
                # Prepare backup entry
                backup_entry = BackupEntry(
                    stamp=stamp,
                    name=base_name,
                    created_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    original=str(self.module_path),
                    compress=compress,
                    message=message or "",
                    file_count=file_count
                )
                
                # Detect module version if available
                try:
                    if self.module_path.is_dir():
                        init_file = self.module_path / "__init__.py"
                        if init_file.exists():
                            with open(init_file, 'r') as f:
                                content = f.read()
                                import re
                                version_match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", content)
                                if version_match:
                                    backup_entry.version = version_match.group(1)
                except Exception:
                    pass  # Version detection is optional
                
                # Handle storage format (ZIP or directory)
                location = None
                if compress:
                    self.logger and self.logger.debug("Creating ZIP archive...")
                    archive_path = self.backups_root / f"{base_name}.zip"
                    file_count, total_size = self._create_zip_archive(
                        temp_backup_dir, archive_path, base_name, compression_level
                    )
                    shutil.rmtree(temp_backup_dir)
                    backup_entry.archive = str(archive_path)
                    backup_entry.size_bytes = total_size
                    backup_entry.file_count = file_count
                    location = str(archive_path)
                    self.logger and self.logger.info(f"Created ZIP backup: {archive_path} ({total_size} bytes)")
                else:
                    target_folder = self.backups_root / base_name
                    if target_folder.exists():
                        shutil.rmtree(target_folder)
                    temp_backup_dir.rename(target_folder)
                    backup_entry.size_bytes = self._get_directory_size(target_folder)
                    location = str(target_folder)
                    self.logger and self.logger.info(f"Created directory backup: {target_folder} ({backup_entry.size_bytes} bytes)")
                
                # Calculate checksum if enabled
                if self.enable_checksum:
                    self.logger and self.logger.debug("Calculating checksum...")
                    backup_path = Path(location) if not compress else Path(backup_entry.archive)
                    backup_entry.checksum = self._calculate_checksum(backup_path)
                
                # Update index
                entries = self._read_index()
                entries.insert(0, backup_entry)  # Newest first
                
                # Apply retention policy if specified
                cleanup_result = None
                if max_backups is not None and max_backups > 0:
                    cleanup_result = self._apply_retention_policy(entries, max_backups)
                    if cleanup_result.removed_count > 0:
                        warnings.append(f"Retention policy removed {cleanup_result.removed_count} old backups")
                
                self._write_index(entries)
                
                # Verify backup integrity if requested
                if verify_after:
                    self.logger and self.logger.debug("Verifying backup...")
                    verify_result = self.verify_backup(stamp)
                    if not verify_result.is_valid:
                        warnings.append(f"Backup verification failed: {verify_result.message}")
                
                duration_ms = (time.time() - start_time) * 1000
                
                self.logger and self.logger.info(f"Backup completed in {duration_ms:.2f}ms")
                
                return BackupResult(
                    status=BackupStatus.SUCCESS,
                    backup=backup_entry,
                    location=location,
                    message=f"Backup created successfully",
                    details={
                        "stamp": stamp,
                        "compress": compress,
                        "file_count": file_count,
                        "compression_level": compression_level if compress else None
                    },
                    duration_ms=duration_ms,
                    warnings=warnings
                )
                
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                self.logger and self.logger.error(f"Backup failed: {e}")
                
                # Cleanup on error
                try:
                    temp_dir = self.backups_root / f"__temp_{stamp}"
                    if temp_dir.exists():
                        shutil.rmtree(temp_dir)
                    zip_file = self.backups_root / f"{base_name}.zip"
                    if zip_file.exists():
                        zip_file.unlink()
                    dir_backup = self.backups_root / base_name
                    if dir_backup.exists():
                        shutil.rmtree(dir_backup)
                except Exception as cleanup_error:
                    self.logger and self.logger.warning(f"Cleanup error: {cleanup_error}")
                
                return BackupResult(
                    status=BackupStatus.FAILED,
                    message=f"Backup failed: {str(e)}",
                    details={"stamp": stamp, "error_type": type(e).__name__},
                    duration_ms=duration_ms,
                    warnings=warnings
                )
    
    def list_backups(self, reverse: bool = False) -> List[BackupEntry]:
        """
        Return a list of all available backups.
        
        Parameters
        ----------
        reverse : bool, optional
            If True, returns backups in chronological order (oldest first).
            If False, returns newest first. Default is False.
        
        Returns
        -------
        List[BackupEntry]
            List of backup entries (newest first by default)
        
        Examples
        --------
        >>> # Get all backups (newest first)
        >>> backups = backup.list_backups()
        >>> for bkp in backups:
        ...     print(f"{bkp.name} - {bkp.created_at} - {bkp.message}")
        
        >>> # Get backups oldest first
        >>> old_backups = backup.list_backups(reverse=True)
        >>> oldest = old_backups[0]
        >>> print(f"Oldest backup: {oldest.name}")
        
        >>> # Filter backups with messages
        >>> backups = backup.list_backups()
        >>> annotated = [b for b in backups if b.message]
        >>> print(f"Found {len(annotated)} backups with notes")
        """
        entries = self._read_index()
        if reverse:
            return list(reversed(entries))
        return entries
    
    def restore(
        self,
        stamp: Optional[str] = None,
        overwrite: bool = True,
        backup_format: BackupFormat = BackupFormat.ZIP,
        verify_before: bool = True
    ) -> RestoreResult:
        """
        Restore a backup to the original module location.
        
        Parameters
        ----------
        stamp : Optional[str], optional
            Stamp of the backup to restore. If None, restores the newest backup.
        overwrite : bool, optional
            If True, replaces existing module files. If False, raises error if exists.
            Default is True.
        backup_format : BackupFormat, optional
            Format to restore from (ZIP or DIRECTORY). Default is BackupFormat.ZIP.
        verify_before : bool, optional
            Whether to verify backup integrity before restoring. Default is True.
        
        Returns
        -------
        RestoreResult
            Object containing restore operation results
        
        Raises
        ------
        BackupNotFoundError
            If no backups available or specific backup not found
        BackupCorruptedError
            If backup exists but is corrupted
        BackupError
            If restore operation fails
        
        Examples
        --------
        >>> # Restore the latest backup
        >>> result = backup.restore()
        >>> if result.is_success():
        ...     print(f"Restored {result.restored_files} files")
        
        >>> # Restore a specific backup by stamp
        >>> result = backup.restore(stamp="20231215T143045Z")
        >>> print(f"Restored backup from {result.stamp} to {result.original_path}")
        
        >>> # Restore without overwriting (fails if module exists)
        >>> try:
        ...     result = backup.restore(overwrite=False)
        ... except BackupError as e:
        ...     print(f"Cannot restore: {e}")
        
        >>> # Restore from directory format specifically
        >>> result = backup.restore(
        ...     stamp="20231215T143045Z",
        ...     backup_format=BackupFormat.DIRECTORY
        ... )
        """
        start_time = time.time()
        
        self.logger and self.logger.info(f"Starting restore operation (stamp: {stamp or 'latest'})")
        
        with self._lock:
            try:
                entries = self._read_index()
                if not entries:
                    raise BackupNotFoundError("none", operation="restore")
                
                # Find the backup entry
                entry = None
                if stamp:
                    entry = next((e for e in entries if e.stamp == stamp), None)
                    if entry is None:
                        raise BackupNotFoundError(stamp, operation="restore")
                else:
                    entry = entries[0]
                    stamp = entry.stamp
                
                self.logger and self.logger.info(f"Restoring backup: {entry.name}")
                
                # Verify backup before restore if requested
                if verify_before:
                    verify_result = self.verify_backup(stamp)
                    if not verify_result.is_valid:
                        raise BackupCorruptedError(stamp, verify_result.message)
                
                # Determine source path based on format
                source_root = None
                if backup_format == BackupFormat.ZIP and entry.archive:
                    archive_path = Path(entry.archive)
                    if not archive_path.exists():
                        raise BackupNotFoundError(stamp, "Archive file missing")
                    source_root = self._extract_archive(archive_path, stamp)
                elif backup_format == BackupFormat.DIRECTORY:
                    source_root = self.backups_root / entry.name
                    if not source_root.exists():
                        raise BackupNotFoundError(stamp, "Backup directory missing")
                else:
                    raise ValueError(f"Unsupported backup format: {backup_format}")
                
                # Perform restore
                restored_files = self._restore_files(source_root, self.module_path, overwrite)
                
                # Cleanup temporary extraction directory
                if backup_format == BackupFormat.ZIP and entry.archive:
                    temp_dir = self.backups_root / f"__extract__{stamp}"
                    if temp_dir.exists():
                        shutil.rmtree(temp_dir)
                
                duration_ms = (time.time() - start_time) * 1000
                
                self.logger and self.logger.info(f"Restore completed: {restored_files} files in {duration_ms:.2f}ms")
                
                return RestoreResult(
                    status=BackupStatus.SUCCESS,
                    stamp=stamp,
                    original_path=str(self.module_path),
                    restored_files=restored_files,
                    message=f"Successfully restored {restored_files} files",
                    duration_ms=duration_ms
                )
                
            except (BackupNotFoundError, BackupCorruptedError):
                raise
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                self.logger and self.logger.error(f"Restore failed: {e}")
                
                # Cleanup on error
                try:
                    temp_dir = self.backups_root / f"__extract__{stamp}"
                    if stamp and temp_dir.exists():
                        shutil.rmtree(temp_dir)
                except Exception:
                    pass
                
                return RestoreResult(
                    status=BackupStatus.FAILED,
                    stamp=stamp or "unknown",
                    message=f"Restore failed: {str(e)}",
                    details={"error_type": type(e).__name__},
                    duration_ms=duration_ms
                )
    
    def delete_backup(self, stamp: str) -> CleanupResult:
        """
        Delete a specific backup permanently.
        
        Parameters
        ----------
        stamp : str
            Stamp of the backup to delete
        
        Returns
        -------
        CleanupResult
            Object containing deletion results
        
        Raises
        ------
        BackupNotFoundError
            If backup with given stamp doesn't exist
        
        Examples
        --------
        >>> # Delete a specific backup
        >>> result = backup.delete_backup("20231215T143045Z")
        >>> if result.status == BackupStatus.SUCCESS:
        ...     print(f"Deleted backup, freed {result.freed_bytes} bytes")
        
        >>> # List backups, then delete the oldest
        >>> backups = backup.list_backups(reverse=True)
        >>> oldest = backups[0]
        >>> result = backup.delete_backup(oldest.stamp)
        >>> print(f"Removed {oldest.stamp}")
        """
        self.logger and self.logger.info(f"Deleting backup: {stamp}")
        
        with self._lock:
            entries = self._read_index()
            entry = next((e for e in entries if e.stamp == stamp), None)
            
            if entry is None:
                raise BackupNotFoundError(stamp, operation="delete_backup")
            
            freed_bytes = 0
            
            # Remove backup files
            if entry.archive and Path(entry.archive).exists():
                size = Path(entry.archive).stat().st_size
                Path(entry.archive).unlink()
                freed_bytes += size
                self.logger and self.logger.debug(f"Deleted archive: {entry.archive} ({size} bytes)")
            
            backup_dir = self.backups_root / entry.name
            if backup_dir.exists():
                size = self._get_directory_size(backup_dir)
                shutil.rmtree(backup_dir)
                freed_bytes += size
                self.logger and self.logger.debug(f"Deleted directory: {backup_dir} ({size} bytes)")
            
            # Update index
            entries = [e for e in entries if e.stamp != stamp]
            self._write_index(entries)
            
            self.logger and self.logger.info(f"Deleted backup {stamp}, freed {freed_bytes} bytes")
            
            return CleanupResult(
                status=BackupStatus.SUCCESS,
                kept_count=len(entries),
                removed_count=1,
                freed_bytes=freed_bytes,
                removed_stamps=[stamp],
                message=f"Backup {stamp} deleted successfully"
            )
    
    def get_backup_info(self, stamp: str) -> Optional[BackupInfo]:
        """
        Get detailed information about a specific backup.
        
        Parameters
        ----------
        stamp : str
            Stamp of the backup to inspect
        
        Returns
        -------
        Optional[BackupInfo]
            Detailed backup information, or None if backup not found
        
        Examples
        --------
        >>> info = backup.get_backup_info("20231215T143045Z")
        >>> if info:
        ...     print(f"Backup: {info.entry.name}")
        ...     print(f"Size: {info.total_size / 1024 / 1024:.2f} MB")
        ...     print(f"Files: {info.file_count}")
        ...     print(f"Corrupted: {info.is_corrupted}")
        
        >>> # Check backup health
        >>> info = backup.get_backup_info(backup.list_backups()[0].stamp)
        >>> if info and not info.is_corrupted:
        ...     print("Backup is healthy")
        ... else:
        ...     print("Backup may be corrupted")
        """
        entries = self._read_index()
        entry = next((e for e in entries if e.stamp == stamp), None)
        
        if entry is None:
            return None
        
        info = BackupInfo(entry=entry)
        
        # Check existence and gather size information
        if entry.archive and Path(entry.archive).exists():
            info.exists = True
            info.archive_size = Path(entry.archive).stat().st_size
            info.total_size = info.archive_size
            info.file_count = self._count_files(Path(entry.archive))
        elif not entry.archive:
            backup_dir = self.backups_root / entry.name
            if backup_dir.exists():
                info.exists = True
                info.directory_size = self._get_directory_size(backup_dir)
                info.total_size = info.directory_size
                info.file_count = self._count_files(backup_dir)
        
        return info
    
    def verify_backup(self, stamp: str, deep: bool = False) -> VerificationResult:
        """
        Verify the integrity of a backup.
        
        Parameters
        ----------
        stamp : str
            Stamp of the backup to verify
        deep : bool, optional
            If True, performs deep verification (checks all files).
            If False, basic verification (exists and structure valid).
            Default is False.
        
        Returns
        -------
        VerificationResult
            Object containing verification results
        
        Examples
        --------
        >>> # Basic verification
        >>> result = backup.verify_backup("20231215T143045Z")
        >>> if result.is_valid:
        ...     print("Backup is valid")
        ... else:
        ...     print(f"Verification failed: {result.message}")
        
        >>> # Deep verification (checks all file contents)
        >>> result = backup.verify_backup("20231215T143045Z", deep=True)
        >>> if result.is_valid:
        ...     print("Backup fully verified")
        ... elif result.corrupted_files:
        ...     print(f"Corrupted files: {', '.join(result.corrupted_files)}")
        
        >>> # Verify all backups
        >>> backups = backup.list_backups()
        >>> for bkp in backups:
        ...     result = backup.verify_backup(bkp.stamp)
        ...     if not result.is_valid:
        ...         print(f"Backup {bkp.stamp} is corrupted: {result.message}")
        """
        self.logger and self.logger.info(f"Verifying backup: {stamp} (deep={deep})")
        
        entries = self._read_index()
        entry = next((e for e in entries if e.stamp == stamp), None)
        
        if entry is None:
            return VerificationResult(
                status=BackupStatus.NOT_FOUND,
                stamp=stamp,
                message=f"Backup with stamp '{stamp}' not found"
            )
        
        missing_files = []
        corrupted_files = []
        
        try:
            # Check if backup files exist
            if entry.archive:
                archive_path = Path(entry.archive)
                if not archive_path.exists():
                    return VerificationResult(
                        status=BackupStatus.CORRUPTED,
                        stamp=stamp,
                        is_valid=False,
                        message=f"Archive file missing: {archive_path}"
                    )
                
                # Verify ZIP integrity
                try:
                    with zipfile.ZipFile(archive_path, "r") as zf:
                        bad_file = zf.testzip()
                        if bad_file:
                            corrupted_files.append(bad_file)
                            return VerificationResult(
                                status=BackupStatus.CORRUPTED,
                                stamp=stamp,
                                is_valid=False,
                                corrupted_files=corrupted_files,
                                message=f"ZIP archive corrupted at file: {bad_file}"
                            )
                except zipfile.BadZipFile as e:
                    return VerificationResult(
                        status=BackupStatus.CORRUPTED,
                        stamp=stamp,
                        is_valid=False,
                        message=f"Invalid ZIP archive: {e}"
                    )
                
                # Deep verification for archives
                if deep:
                    with zipfile.ZipFile(archive_path, "r") as zf:
                        for file_info in zf.infolist():
                            if not file_info.file_size:  # Skip empty files
                                continue
                            try:
                                zf.read(file_info)
                            except Exception:
                                corrupted_files.append(file_info.filename)
            
            else:
                backup_dir = self.backups_root / entry.name
                if not backup_dir.exists():
                    return VerificationResult(
                        status=BackupStatus.CORRUPTED,
                        stamp=stamp,
                        is_valid=False,
                        message=f"Backup directory missing: {backup_dir}"
                    )
                
                # Deep verification for directories
                if deep:
                    for file_path in backup_dir.rglob("*"):
                        if file_path.is_file():
                            try:
                                with open(file_path, 'rb') as f:
                                    f.read()
                            except Exception:
                                corrupted_files.append(str(file_path.relative_to(backup_dir)))
            
            # Verify checksum if available
            checksum_match = True
            if self.enable_checksum and entry.checksum:
                backup_path = Path(entry.archive) if entry.archive else self.backups_root / entry.name
                current_checksum = self._calculate_checksum(backup_path)
                checksum_match = (current_checksum == entry.checksum)
                if not checksum_match:
                    corrupted_files.append("checksum_mismatch")
            
            is_valid = (len(missing_files) == 0 and len(corrupted_files) == 0 and checksum_match)
            
            if is_valid:
                self.logger and self.logger.info(f"Backup {stamp} verified successfully")
                return VerificationResult(
                    status=BackupStatus.SUCCESS,
                    stamp=stamp,
                    is_valid=True,
                    checksum_match=checksum_match,
                    file_count_match=True,
                    message="Backup is valid and complete"
                )
            else:
                self.logger and self.logger.warning(f"Backup {stamp} verification failed")
                return VerificationResult(
                    status=BackupStatus.CORRUPTED,
                    stamp=stamp,
                    is_valid=False,
                    checksum_match=checksum_match,
                    missing_files=missing_files,
                    corrupted_files=corrupted_files,
                    message=f"Backup corrupted: {len(corrupted_files)} issues found"
                )
                
        except Exception as e:
            self.logger and self.logger.error(f"Verification error: {e}")
            return VerificationResult(
                status=BackupStatus.FAILED,
                stamp=stamp,
                is_valid=False,
                message=f"Verification failed: {str(e)}"
            )
    
    def cleanup(self, keep_latest: int = 5, dry_run: bool = False) -> CleanupResult:
        """
        Clean up old backups, keeping only the specified number of latest ones.
        
        Parameters
        ----------
        keep_latest : int, optional
            Number of latest backups to keep. Default is 5.
        dry_run : bool, optional
            If True, only report what would be deleted without actually deleting.
            Default is False.
        
        Returns
        -------
        CleanupResult
            Object containing cleanup results and statistics
        
        Examples
        --------
        >>> # Keep only the 5 most recent backups
        >>> result = backup.cleanup(keep_latest=5)
        >>> print(f"Removed {result.removed_count} backups, freed {result.freed_bytes} bytes")
        
        >>> # Preview cleanup without actually deleting
        >>> result = backup.cleanup(keep_latest=3, dry_run=True)
        >>> print(f"Would remove {result.removed_count} backups")
        >>> for stamp in result.removed_stamps:
        ...     print(f"  - {stamp}")
        
        >>> # Aggressive cleanup - keep only 1 backup
        >>> result = backup.cleanup(keep_latest=1)
        >>> if result.removed_count > 0:
        ...     print(f"Kept only latest backup, removed {result.removed_count} others")
        """
        self.logger and self.logger.info(f"Starting cleanup (keep_latest={keep_latest}, dry_run={dry_run})")
        
        with self._lock:
            entries = self._read_index()
            initial_count = len(entries)
            
            if initial_count <= keep_latest:
                self.logger and self.logger.info("No cleanup needed")
                return CleanupResult(
                    status=BackupStatus.SUCCESS,
                    kept_count=initial_count,
                    removed_count=0,
                    message=f"Only {initial_count} backups exist, keeping all"
                )
            
            if dry_run:
                # Just report what would be removed
                to_remove = entries[keep_latest:]
                removed_stamps = [e.stamp for e in to_remove]
                
                # Calculate potential freed space
                freed_bytes = 0
                for entry in to_remove:
                    if entry.archive and Path(entry.archive).exists():
                        freed_bytes += Path(entry.archive).stat().st_size
                    else:
                        backup_dir = self.backups_root / entry.name
                        if backup_dir.exists():
                            freed_bytes += self._get_directory_size(backup_dir)
                
                return CleanupResult(
                    status=BackupStatus.SUCCESS,
                    kept_count=keep_latest,
                    removed_count=len(to_remove),
                    freed_bytes=freed_bytes,
                    removed_stamps=removed_stamps,
                    message=f"Dry run: would remove {len(to_remove)} backups"
                )
            
            # Actually perform cleanup
            result = self._apply_retention_policy(entries, keep_latest)
            self._write_index(entries)
            
            self.logger and self.logger.info(f"Cleanup completed: removed {result.removed_count} backups")
            return result
    
    def export_index(self, format: str = "json") -> str:
        """
        Export backup index in various formats for reporting.
        
        Parameters
        ----------
        format : str, optional
            Output format: 'json', 'csv', or 'summary'. Default is 'json'.
        
        Returns
        -------
        str
            Formatted index data as string
        
        Examples
        --------
        >>> # Export as JSON
        >>> json_data = backup.export_index(format="json")
        >>> print(json_data)
        
        >>> # Export as CSV for spreadsheet analysis
        >>> csv_data = backup.export_index(format="csv")
        >>> with open("backups.csv", "w") as f:
        ...     f.write(csv_data)
        
        >>> # Get summary statistics
        >>> summary = backup.export_index(format="summary")
        >>> print(summary)
        """
        entries = self._read_index()
        
        if format == "json":
            return json.dumps([e.to_dict() for e in entries], indent=2, ensure_ascii=False)
        
        elif format == "csv":
            import io
            output = io.StringIO()
            output.write("stamp,name,created_at,compress,message,file_count,size_bytes,version\n")
            for e in entries:
                output.write(f"{e.stamp},{e.name},{e.created_at},{e.compress},\"{e.message}\",{e.file_count},{e.size_bytes},{e.version or ''}\n")
            return output.getvalue()
        
        elif format == "summary":
            total_size = sum(e.size_bytes for e in entries)
            total_files = sum(e.file_count for e in entries)
            compressed = sum(1 for e in entries if e.compress)
            
            return f"""
Backup Summary for '{self.module_name}'
========================================
Total backups: {len(entries)}
Compressed backups: {compressed}
Directory backups: {len(entries) - compressed}
Total size: {total_size / 1024 / 1024:.2f} MB
Total files: {total_files}
Latest backup: {entries[0].stamp if entries else 'N/A'}
Oldest backup: {entries[-1].stamp if entries else 'N/A'}
"""
        else:
            raise ValueError(f"Unsupported export format: {format}")