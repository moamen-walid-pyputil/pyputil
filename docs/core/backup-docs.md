# Module Backup System Documentation

## Overview

The Module Backup System is a production-ready Python library for creating, managing, and restoring backups of Python modules and packages. It provides integrity checking, compression, retention policies, and comprehensive error handling.

## Architecture

The system consists of three core modules:

| Module | Purpose |
|--------|---------|
| `base.py` | Defines data structures and enumerations for backup metadata |
| `exceptions.py` | Custom exception hierarchy for error handling |
| `core.py` | Main `ModuleBackup` class implementing all backup functionality |

## Installation

Place the module in your Python path and import:

```python
from pyputil.core import ModuleBackup
from pyputil.core import BackupStatus, BackupFormat
```

Core Classes

ModuleBackup

The primary class for backup operations.

Constructor parameters:

Parameter Type Default Description
module_name str Required Name of Python module to backup
backup_root Optional[str] None Custom backup directory (default: ./backups_<module_name>)
enable_checksum bool True Enable SHA-256 integrity verification
enable_logging bool True Enable internal logging
log_level int logging.INFO Logging level (DEBUG, INFO, WARNING, ERROR)
max_retries int 3 Retry attempts for failed operations

Data Classes (from base.py)

Class Purpose
BackupEntry Metadata for a single backup (stamp, name, size, checksum, etc.)
BackupResult Result of backup operation
RestoreResult Result of restore operation
VerificationResult Result of integrity verification
CleanupResult Result of retention policy cleanup
BackupInfo Detailed backup information

Enumerations

Enum Values
BackupFormat ZIP, DIRECTORY
BackupStatus SUCCESS, PARTIAL, FAILED, SKIPPED, CORRUPTED, NOT_FOUND
ErrorSeverity DEBUG, INFO, WARNING, ERROR, CRITICAL

Exceptions

Exception When Raised
BackupError Base exception for all backup operations
BackupNotFoundError Requested backup stamp doesn't exist
BackupCorruptedError Backup exists but is corrupted
ModuleNotFoundError Target module cannot be found

Usage Examples

Basic Backup Operations

```python
from pyputil.core import ModuleBackup

# Initialize backup manager
backup = ModuleBackup("requests")

# Create a compressed backup
result = backup.backup(
    compress=True,
    message="Pre-upgrade backup"
)

if result.is_success():
    print(f"Backup created: {result.location}")
    print(f"Backup stamp: {result.backup.stamp}")
    print(f"Size: {result.backup.size_bytes} bytes")
    print(f"Files: {result.backup.file_count}")
```

Listing and Restoring Backups

```python
# List all backups (newest first)
backups = backup.list_backups()
for bkp in backups:
    print(f"{bkp.stamp} - {bkp.created_at} - {bkp.message}")

# Restore latest backup
restore_result = backup.restore(overwrite=True)
print(f"Restored {restore_result.restored_files} files")

# Restore specific backup by stamp
restore_result = backup.restore(
    stamp="20231215T143045Z",
    verify_before=True
)
```

Backup Verification

```python
# Basic verification (checks existence and structure)
verify_result = backup.verify_backup("20231215T143045Z")
if verify_result.is_valid:
    print("Backup is valid")
else:
    print(f"Verification failed: {verify_result.message}")

# Deep verification (checks all file contents)
verify_result = backup.verify_backup("20231215T143045Z", deep=True)
if verify_result.corrupted_files:
    print(f"Corrupted files: {verify_result.corrupted_files}")
```

Retention Management

```python
# Keep only 5 most recent backups
cleanup_result = backup.cleanup(keep_latest=5)
print(f"Removed {cleanup_result.removed_count} backups")
print(f"Freed {cleanup_result.freed_bytes} bytes")

# Preview what would be deleted (dry run)
preview = backup.cleanup(keep_latest=3, dry_run=True)
for stamp in preview.removed_stamps:
    print(f"Would delete: {stamp}")

# Delete specific backup
backup.delete_backup("20231215T143045Z")
```

Getting Backup Information

```python
# Get detailed info about a backup
info = backup.get_backup_info("20231215T143045Z")
if info:
    print(f"Exists: {info.exists}")
    print(f"Total size: {info.total_size / 1024 / 1024:.2f} MB")
    print(f"File count: {info.file_count}")
    print(f"Corrupted: {info.is_corrupted}")

# Export index in different formats
json_data = backup.export_index(format="json")
csv_data = backup.export_index(format="csv")
summary = backup.export_index(format="summary")
print(summary)
```

Uncompressed Backups

```python
# Create directory backup (not compressed)
result = backup.backup(
    compress=False,
    message="Development snapshot"
)

# Restore from directory format
restore_result = backup.restore(
    stamp=result.backup.stamp,
    backup_format=BackupFormat.DIRECTORY
)
```

Backup Storage Structure

Default Directory Layout

```
./backups_<module_name>/
├── backups_index.json          # Metadata index
├── <module_name>_<stamp>.zip   # Compressed backup (if compress=True)
└── <module_name>_<stamp>/      # Directory backup (if compress=False)
    └── <module_name>/          # Copied module content
```

Index File Format (JSON)

```json
[
  {
    "stamp": "20231215T143045Z",
    "name": "requests_20231215T143045Z",
    "created_at": "2023-12-15T14:30:45Z",
    "original": "/usr/lib/python3.9/site-packages/requests",
    "compress": true,
    "message": "Pre-upgrade backup",
    "archive": "/path/to/backups_requests/requests_20231215T143045Z.zip",
    "size_bytes": 1048576,
    "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "file_count": 42,
    "version": "2.28.1"
  }
]
```

Method Reference

ModuleBackup Methods

Method Description
backup(compress, message, max_backups, compression_level, verify_after) Create new backup
restore(stamp, overwrite, backup_format, verify_before) Restore backup to original location
list_backups(reverse) Return list of all backups
verify_backup(stamp, deep) Verify backup integrity
cleanup(keep_latest, dry_run) Remove old backups per retention policy
delete_backup(stamp) Permanently delete specific backup
get_backup_info(stamp) Get detailed backup information
export_index(format) Export backup index (json/csv/summary)

Thread Safety

The ModuleBackup class uses a reentrant lock (threading.RLock) for all operations that modify the backup index or filesystem. This makes the class safe for use in multi-threaded applications:

```python
import threading

backup = ModuleBackup("my_module")

def create_backup():
    backup.backup(message="Thread-safe backup")

threads = [threading.Thread(target=create_backup) for _ in range(3)]
for t in threads:
    t.start()
for t in threads:
    t.join()
```

Error Handling Example

```python
from pyputil.core import ModuleBackup, BackupNotFoundError, BackupCorruptedError
from pyputil.base import BackupStatus

backup = ModuleBackup("my_module")

try:
    result = backup.restore(stamp="nonexistent_stamp")
except BackupNotFoundError as e:
    print(f"Backup not found: {e}")
    print(f"Operation: {e.operation}")
except BackupCorruptedError as e:
    print(f"Backup corrupted: {e.reason}")
except Exception as e:
    print(f"Unexpected error: {e}")

# Alternatively, check result status
result = backup.backup()
if result.status == BackupStatus.FAILED:
    print(f"Failed: {result.message}")
    print(f"Details: {result.details}")
```

Logging Output Example

When enable_logging=True, output resembles:

```
2024-01-15 10:30:45,123 - ModuleBackup.requests - INFO - Module found at: /usr/lib/python3.9/requests
2024-01-15 10:30:45,124 - ModuleBackup.requests - INFO - ModuleBackup initialized for 'requests'
2024-01-15 10:30:45,125 - ModuleBackup.requests - INFO - Starting backup of 'requests' (stamp: 20240115T103045Z)
2024-01-15 10:30:46,234 - ModuleBackup.requests - INFO - Created ZIP backup: /path/to/backup.zip (1048576 bytes)
2024-01-15 10:30:46,456 - ModuleBackup.requests - INFO - Backup completed in 1331.23ms
```

Requirements

· Python 3.7+ (uses importlib.util, pathlib, dataclasses)
· Standard library only (no external dependencies)