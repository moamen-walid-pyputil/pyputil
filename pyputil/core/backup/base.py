from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, Any, List

# =============================================================================
# ENUMERATIONS
# =============================================================================

class BackupFormat(Enum):
    """
    Enumeration representing available backup storage formats.
    
    Attributes
    ----------
    ZIP : str
        Store backup as compressed ZIP archive (default, saves disk space)
    DIRECTORY : str
        Store backup as uncompressed directory (faster access, more disk space)
    
    Examples
    --------
    >>> # Create ZIP backup
    >>> backup_mgr.backup(format=BackupFormat.ZIP)
    >>> 
    >>> # Create directory backup
    >>> backup_mgr.backup(format=BackupFormat.DIRECTORY)
    """
    
    ZIP = "zip"
    DIRECTORY = "directory"


class BackupStatus(Enum):
    """
    Enumeration of possible backup operation status codes.
    
    Attributes
    ----------
    SUCCESS : int
        Operation completed successfully
    PARTIAL : int
        Operation completed partially (some files may have issues)
    FAILED : int
        Operation failed completely
    SKIPPED : int
        Operation was skipped (e.g., backup already exists)
    CORRUPTED : int
        Backup exists but is corrupted
    NOT_FOUND : int
        Requested backup or module not found
    
    Examples
    --------
    >>> result = backup_mgr.backup()
    >>> if result.status == BackupStatus.SUCCESS:
    ...     print("Backup created successfully")
    """
    
    SUCCESS = 0
    PARTIAL = 1
    FAILED = 2
    SKIPPED = 3
    CORRUPTED = 4
    NOT_FOUND = 5


class ErrorSeverity(Enum):
    """
    Enumeration of error severity levels for logging and handling.
    
    Attributes
    ----------
    DEBUG : int
        Debugging information
    INFO : int
        Informational message
    WARNING : int
        Warning that doesn't stop execution
    ERROR : int
        Error that affects operation but not system stability
    CRITICAL : int
        Critical error requiring immediate attention
    """
    
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4


# =============================================================================
# DATA CLASSES FOR OUTPUTS
# =============================================================================

@dataclass
class BackupEntry:
    """
    Data class representing a single backup entry in the index.
    
    This class stores all metadata associated with a backup, including
    timestamps, compression settings, and file locations.
    
    Parameters
    ----------
    stamp : str
        Unique timestamp identifier for the backup (format: YYYYmmddTHHMMSSZ)
    name : str
        Human-readable backup name (format: <module_name>_<stamp>)
    created_at : str
        ISO format timestamp of backup creation with Zulu timezone
    original : str
        Original module path before backup
    compress : bool
        Whether backup is stored as compressed ZIP (True) or directory (False)
    message : str, optional
        User-provided description or note about the backup
    archive : Optional[str], optional
        Path to ZIP archive if compress=True, None otherwise
    size_bytes : int, optional
        Total size of backup in bytes
    checksum : Optional[str], optional
        SHA-256 checksum for integrity verification
    file_count : int, optional
        Number of files in the backup
    version : str, optional
        Module version if detected from __version__
    
    Examples
    --------
    >>> entry = BackupEntry(
    ...     stamp="20231215T143045Z",
    ...     name="my_module_20231215T143045Z",
    ...     created_at="2023-12-15T14:30:45Z",
    ...     original="/path/to/my_module",
    ...     compress=True,
    ...     message="Pre-refactoring backup",
    ...     archive="/path/to/backup.zip",
    ...     size_bytes=1048576,
    ...     file_count=42
    ... )
    >>> print(entry.name)
    my_module_20231215T143045Z
    """
    
    stamp: str
    name: str
    created_at: str
    original: str
    compress: bool
    message: str = ""
    archive: Optional[str] = None
    size_bytes: int = 0
    checksum: Optional[str] = None
    file_count: int = 0
    version: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert BackupEntry to dictionary for JSON serialization.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the backup entry
            
        Examples
        --------
        >>> entry = BackupEntry(stamp="123", name="test", created_at="now", 
        ...                     original="/path", compress=False)
        >>> data = entry.to_dict()
        >>> print(data.keys())
        dict_keys(['stamp', 'name', 'created_at', 'original', 'compress', 
                   'message', 'archive', 'size_bytes', 'checksum', 'file_count', 'version'])
        """
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackupEntry":
        """
        Create BackupEntry instance from dictionary data.
        
        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary containing backup entry data
            
        Returns
        -------
        BackupEntry
            New BackupEntry instance populated from dictionary
            
        Examples
        --------
        >>> data = {
        ...     "stamp": "20231215T143045Z",
        ...     "name": "module_20231215T143045Z",
        ...     "created_at": "2023-12-15T14:30:45Z",
        ...     "original": "/path/to/module",
        ...     "compress": True
        ... }
        >>> entry = BackupEntry.from_dict(data)
        >>> isinstance(entry, BackupEntry)
        True
        """
        return cls(**data)


@dataclass
class BackupResult:
    """
    Data class representing the result of a backup operation.
    
    Attributes
    ----------
    status : BackupStatus
        Status code indicating operation outcome
    backup : Optional[BackupEntry]
        Backup entry if operation was successful
    location : Optional[str]
        Path where backup was stored
    message : str
        Human-readable status message
    details : Dict[str, Any]
        Additional operation-specific details
    duration_ms : float
        Operation duration in milliseconds
    warnings : List[str]
        List of warning messages generated during operation
    
    Examples
    --------
    >>> result = backup_mgr.backup()
    >>> if result.status == BackupStatus.SUCCESS:
    ...     print(f"Backup saved to: {result.location}")
    ...     print(f"Took {result.duration_ms:.2f}ms")
    """
    
    status: BackupStatus
    backup: Optional[BackupEntry] = None
    location: Optional[str] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    warnings: List[str] = field(default_factory=list)
    
    def is_success(self) -> bool:
        """
        Check if operation was successful.
        
        Returns
        -------
        bool
            True if status is SUCCESS, False otherwise
            
        Examples
        --------
        >>> result = backup_mgr.backup()
        >>> if result.is_success():
        ...     print("Backup created!")
        """
        return self.status == BackupStatus.SUCCESS
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert result to dictionary for logging or API responses.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation with status as string value
            
        Examples
        --------
        >>> result = backup_mgr.backup()
        >>> log_data = result.to_dict()
        >>> print(log_data['status'])
        SUCCESS
        """
        return {
            "status": self.status.name,
            "status_code": self.status.value,
            "backup": self.backup.to_dict() if self.backup else None,
            "location": self.location,
            "message": self.message,
            "details": self.details,
            "duration_ms": self.duration_ms,
            "warnings": self.warnings
        }


@dataclass
class RestoreResult:
    """
    Data class representing the result of a restore operation.
    
    Attributes
    ----------
    status : BackupStatus
        Status code indicating operation outcome
    stamp : str
        Stamp of the restored backup
    original_path : str
        Original path where module was restored
    restored_files : int
        Number of files restored
    message : str
        Human-readable status message
    details : Dict[str, Any]
        Additional operation-specific details
    duration_ms : float
        Operation duration in milliseconds
    
    Examples
    --------
    >>> result = backup_mgr.restore(stamp="20231215T143045Z")
    >>> if result.is_success():
    ...     print(f"Restored {result.restored_files} files to {result.original_path}")
    """
    
    status: BackupStatus
    stamp: str = ""
    original_path: str = ""
    restored_files: int = 0
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    
    def is_success(self) -> bool:
        """
        Check if restore operation was successful.
        
        Returns
        -------
        bool
            True if status is SUCCESS, False otherwise
        """
        return self.status == BackupStatus.SUCCESS
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert result to dictionary for logging or API responses.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of restore result
        """
        return {
            "status": self.status.name,
            "status_code": self.status.value,
            "stamp": self.stamp,
            "original_path": self.original_path,
            "restored_files": self.restored_files,
            "message": self.message,
            "details": self.details,
            "duration_ms": self.duration_ms
        }


@dataclass
class VerificationResult:
    """
    Data class representing backup integrity verification results.
    
    Attributes
    ----------
    status : BackupStatus
        Status code indicating verification outcome
    stamp : str
        Stamp of verified backup
    is_valid : bool
        True if backup is intact and valid
    checksum_match : bool
        True if checksum verification passed
    file_count_match : bool
        True if file count matches recorded value
    missing_files : List[str]
        List of files that should exist but don't
    corrupted_files : List[str]
        List of files that are corrupted
    message : str
        Human-readable status message
    details : Dict[str, Any]
        Additional verification details
    
    Examples
    --------
    >>> result = backup_mgr.verify_backup(stamp="20231215T143045Z")
    >>> if result.is_valid:
    ...     print("Backup integrity verified!")
    ... else:
    ...     print(f"Verification failed: {result.message}")
    """
    
    status: BackupStatus
    stamp: str = ""
    is_valid: bool = False
    checksum_match: bool = False
    file_count_match: bool = False
    missing_files: List[str] = field(default_factory=list)
    corrupted_files: List[str] = field(default_factory=list)
    message: str = ""
    details: Dict[str, Any] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert verification result to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of verification result
        """
        return {
            "status": self.status.name,
            "stamp": self.stamp,
            "is_valid": self.is_valid,
            "checksum_match": self.checksum_match,
            "file_count_match": self.file_count_match,
            "missing_files": self.missing_files,
            "corrupted_files": self.corrupted_files,
            "message": self.message,
            "details": self.details
        }


@dataclass
class CleanupResult:
    """
    Data class representing backup cleanup operation results.
    
    Attributes
    ----------
    status : BackupStatus
        Status code indicating cleanup outcome
    kept_count : int
        Number of backups retained
    removed_count : int
        Number of backups deleted
    freed_bytes : int
        Total disk space freed in bytes
    removed_stamps : List[str]
        List of stamps for removed backups
    message : str
        Human-readable status message
    
    Examples
    --------
    >>> result = backup_mgr.cleanup(keep_latest=5)
    >>> print(f"Removed {result.removed_count} backups, freed {result.freed_bytes} bytes")
    """
    
    status: BackupStatus
    kept_count: int = 0
    removed_count: int = 0
    freed_bytes: int = 0
    removed_stamps: List[str] = field(default_factory=list)
    message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert cleanup result to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of cleanup result
        """
        return {
            "status": self.status.name,
            "kept_count": self.kept_count,
            "removed_count": self.removed_count,
            "freed_bytes": self.freed_bytes,
            "removed_stamps": self.removed_stamps,
            "message": self.message
        }


@dataclass
class BackupInfo:
    """
    Data class with detailed information about a specific backup.
    
    Attributes
    ----------
    entry : BackupEntry
        Basic backup metadata entry
    exists : bool
        Whether backup files actually exist on disk
    archive_size : Optional[int]
        Size of ZIP archive if applicable
    directory_size : Optional[int]
        Size of directory backup if applicable
    total_size : int
        Total size of backup (archive or directory)
    file_count : int
        Number of files in backup
    is_corrupted : bool
        Whether backup is corrupted
    last_verified : Optional[str]
        Timestamp of last verification
    verification_count : int
        Number of times backup has been verified
    
    Examples
    --------
    >>> info = backup_mgr.get_backup_info(stamp="20231215T143045Z")
    >>> if info and info.exists:
    ...     print(f"Backup size: {info.total_size / 1024:.2f} KB")
    ...     print(f"Files: {info.file_count}")
    """
    
    entry: BackupEntry
    exists: bool = False
    archive_size: Optional[int] = None
    directory_size: Optional[int] = None
    total_size: int = 0
    file_count: int = 0
    is_corrupted: bool = False
    last_verified: Optional[str] = None
    verification_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert backup info to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of backup information
        """
        return {
            "entry": self.entry.to_dict(),
            "exists": self.exists,
            "archive_size": self.archive_size,
            "directory_size": self.directory_size,
            "total_size": self.total_size,
            "file_count": self.file_count,
            "is_corrupted": self.is_corrupted,
            "last_verified": self.last_verified,
            "verification_count": self.verification_count
        }