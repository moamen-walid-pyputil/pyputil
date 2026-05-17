from .base import ErrorSeverity
from typing import Optional

# =============================================================================
# EXCEPTIONS
# =============================================================================

class BackupError(Exception):
    """
    Base exception class for backup system errors.
    
    This exception is raised when any backup operation encounters an error.
    It carries additional context about the operation and original exception.
    
    Parameters
    ----------
    message : str
        Error message describing what went wrong
    operation : str
        Name of the operation that failed (e.g., 'backup', 'restore')
    original_exception : Optional[Exception]
        Original exception that caused this error
    severity : ErrorSeverity
        Severity level of the error
    
    Attributes
    ----------
    message : str
        Error description
    operation : str
        Failed operation name
    original_exception : Optional[Exception]
        Original exception if any
    severity : ErrorSeverity
        Error severity level
    
    Examples
    --------
    >>> try:
    ...     backup_mgr.backup()
    ... except BackupError as e:
    ...     print(f"Backup failed during {e.operation}: {e.message}")
    ...     if e.original_exception:
    ...         print(f"Caused by: {e.original_exception}")
    """
    
    def __init__(
        self,
        message: str,
        operation: str = "unknown",
        original_exception: Optional[Exception] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR
    ):
        self.message = message
        self.operation = operation
        self.original_exception = original_exception
        self.severity = severity
        super().__init__(self.message)


class BackupNotFoundError(BackupError):
    """
    Exception raised when a requested backup does not exist.
    
    Examples
    --------
    >>> try:
    ...     backup_mgr.restore(stamp="nonexistent")
    ... except BackupNotFoundError as e:
    ...     print(f"Backup not found: {e}")
    """
    
    def __init__(self, stamp: str, operation: str = "restore"):
        super().__init__(
            message=f"Backup with stamp '{stamp}' not found",
            operation=operation,
            severity=ErrorSeverity.WARNING
        )
        self.stamp = stamp


class BackupCorruptedError(BackupError):
    """
    Exception raised when a backup exists but is corrupted.
    
    Examples
    --------
    >>> try:
    ...     backup_mgr.restore(stamp="corrupted_backup")
    ... except BackupCorruptedError as e:
    ...     print(f"Cannot restore corrupted backup: {e}")
    """
    
    def __init__(self, stamp: str, reason: str = "integrity check failed", operation: str = "restore"):
        super().__init__(
            message=f"Backup '{stamp}' is corrupted: {reason}",
            operation=operation,
            severity=ErrorSeverity.ERROR
        )
        self.stamp = stamp
        self.reason = reason


class ModuleNotFoundError(BackupError):
    """
    Exception raised when the target module cannot be found.
    
    Examples
    --------
    >>> try:
    ...     backup_mgr = ModuleBackup("nonexistent_module")
    ... except ModuleNotFoundError as e:
    ...     print(f"Cannot find module: {e}")
    """
    
    def __init__(self, module_name: str):
        super().__init__(
            message=f"Module '{module_name}' not found in Python path",
            operation="initialization",
            severity=ErrorSeverity.ERROR
        )
        self.module_name = module_name