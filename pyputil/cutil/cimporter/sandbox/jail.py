#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
==================================
    FILESYSTEM JAIL - ADVANCED
==================================

Advanced filesystem isolation and restriction system for sandboxed execution.
Provides comprehensive path-based access control, chroot-style jails,
bind mounts, overlay filesystems, and resource monitoring.

This module implements enterprise-grade filesystem sandboxing with:
- Multi-layered path restriction (whitelist, blacklist, readonly)
- Chroot jail with automatic environment setup
- Bind mount management for selective filesystem exposure
- OverlayFS support for copy-on-write isolation
- tmpfs mounts for secure temporary storage
- Resource quota monitoring and enforcement
- Symlink/hardlink control and validation
- Cross-platform abstraction (Linux, macOS, BSD)
- Seccomp-bpf integration for syscall filtering
- Automatic cleanup and resource reclamation

Architecture:
-------------
FilesystemJail (Main orchestrator)
├── PathRestrictionEngine (Rule evaluation)
├── MountManager (Bind mounts, tmpfs, overlay)
├── ChrootEnvironment (Chroot setup and management)
├── ResourceMonitor (Disk quota and inode limits)
├── SymlinkValidator (Link security checking)
└── CleanupManager (Resource reclamation)

Examples:
---------
>>> # Basic read-only jail
>>> jail = FilesystemJail(
...     root_path=Path("/tmp/sandbox"),
...     allowed_paths=[Path("/usr/bin"), Path("/lib")],
...     read_only_paths=[Path("/usr"), Path("/etc")],
... )
>>> with jail:
...     result = jailed_execute(["gcc", "source.c"])

>>> # Advanced jail with overlay and resource limits
>>> jail = FilesystemJail(
...     root_path=Path("/tmp/sandbox"),
...     use_overlay=True,
...     overlay_lower_dirs=[Path("/usr"), Path("/lib")],
...     disk_quota_mb=500,
...     max_files=1000,
...     allow_network=False,
... )
>>> jail.setup()
>>> # ... execute commands ...
>>> jail.cleanup()
"""

import os
import sys
import stat
import time
import shutil
import tempfile
import subprocess
import threading
import resource
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, IntEnum, IntFlag, auto
from pathlib import Path
from types import TracebackType
from typing import (
    Any, Callable, Dict, Iterator, List, Optional, 
    Set, Tuple, Type, Union, Pattern, Match
)
from contextlib import contextmanager
from collections import defaultdict, OrderedDict
from concurrent.futures import ThreadPoolExecutor
import logging
import hashlib
import re

# Conditional imports for platform-specific features
try:
    import ctypes
    import ctypes.util
    HAVE_CTYPES = True
except ImportError:
    HAVE_CTYPES = False

try:
    import prctl
    HAVE_PRCTL = True
except ImportError:
    HAVE_PRCTL = False

try:
    import seccomp
    HAVE_SECCOMP = True
except ImportError:
    HAVE_SECCOMP = False

logger = logging.getLogger(__name__)


# ============================================================================
# Enumerations and Constants
# ============================================================================

class PathPermission(IntFlag):
    """
    Comprehensive path permission flags for fine-grained access control.

    These flags define the exact operations permitted on a filesystem path.
    They can be combined using bitwise OR to create custom permission sets.

    Attributes
    ----------
    NONE : int
        No access whatsoever (0).
    EXISTS : int
        Permission to check if path exists (stat).
    READ : int
        Permission to read file contents.
    WRITE : int
        Permission to write/modify file contents.
    APPEND : int
        Permission to append to file (no overwrite).
    EXECUTE : int
        Permission to execute file or traverse directory.
    DELETE : int
        Permission to delete/unlink file.
    RENAME : int
        Permission to rename/move file.
    CREATE : int
        Permission to create new files.
    MKDIR : int
        Permission to create directories.
    RMDIR : int
        Permission to remove directories.
    CHMOD : int
        Permission to change file permissions.
    CHOWN : int
        Permission to change file ownership.
    LINK : int
        Permission to create hard links.
    SYMLINK : int
        Permission to create symbolic links.
    READLINK : int
        Permission to read symbolic links.
    TRUNCATE : int
        Permission to truncate files.
    LOCK : int
        Permission to lock files (fcntl/flock).
    MMAP : int
        Permission to memory-map files.
    IOCTL : int
        Permission to perform ioctl operations.
    GETATTR : int
        Permission to get extended attributes.
    SETATTR : int
        Permission to set extended attributes.
    LIST_DIR : int
        Permission to list directory contents.
    READ_DIR : int
        Alias for LIST_DIR.
    SEARCH : int
        Permission to search directory (execute permission).
    BASIC_READ : int
        Convenience: EXISTS | READ | LIST_DIR
    BASIC_WRITE : int
        Convenience: BASIC_READ | WRITE | CREATE | DELETE
    BASIC_EXECUTE : int
        Convenience: READ | EXECUTE | SEARCH
    MODIFY : int
        Convenience: WRITE | APPEND | TRUNCATE | RENAME
    FULL : int
        All permissions combined.

    Examples
    --------
    >>> # Read-only with execute
    >>> perm = PathPermission.READ | PathPermission.EXECUTE
    >>> 
    >>> # Check if write is allowed
    >>> if perm & PathPermission.WRITE:
    ...     print("Write allowed")
    >>> 
    >>> # Full access except chown
    >>> perm = PathPermission.FULL & ~PathPermission.CHOWN
    """

    NONE = 0
    EXISTS = auto()
    READ = auto()
    WRITE = auto()
    APPEND = auto()
    EXECUTE = auto()
    DELETE = auto()
    RENAME = auto()
    CREATE = auto()
    MKDIR = auto()
    RMDIR = auto()
    CHMOD = auto()
    CHOWN = auto()
    LINK = auto()
    SYMLINK = auto()
    READLINK = auto()
    TRUNCATE = auto()
    LOCK = auto()
    MMAP = auto()
    IOCTL = auto()
    GETATTR = auto()
    SETATTR = auto()
    LIST_DIR = auto()
    READ_DIR = LIST_DIR
    SEARCH = EXECUTE

    # Convenience combinations
    BASIC_READ = EXISTS | READ | LIST_DIR
    BASIC_WRITE = BASIC_READ | WRITE | CREATE | DELETE
    BASIC_EXECUTE = READ | EXECUTE | SEARCH
    MODIFY = WRITE | APPEND | TRUNCATE | RENAME
    FULL = (
        EXISTS | READ | WRITE | APPEND | EXECUTE | DELETE | RENAME |
        CREATE | MKDIR | RMDIR | CHMOD | CHOWN | LINK | SYMLINK |
        READLINK | TRUNCATE | LOCK | MMAP | IOCTL | GETATTR | SETATTR
    )

    def to_unix_mode(self) -> int:
        """
        Convert to Unix file mode bits (approximate).

        Returns
        -------
        int
            Unix mode bits (e.g., 0o755).
        """
        mode = 0
        if self & self.READ:
            mode |= stat.S_IRUSR
        if self & self.WRITE:
            mode |= stat.S_IWUSR
        if self & self.EXECUTE:
            mode |= stat.S_IXUSR
        return mode

    def to_access_flags(self) -> int:
        """
        Convert to access(2) flags.

        Returns
        -------
        int
            Access flags (R_OK, W_OK, X_OK).
        """
        flags = 0
        if self & self.READ:
            flags |= os.R_OK
        if self & self.WRITE:
            flags |= os.W_OK
        if self & self.EXECUTE:
            flags |= os.X_OK
        return flags

    def to_open_flags(self) -> int:
        """
        Convert to open(2) flags.

        Returns
        -------
        int
            Open flags (O_RDONLY, O_WRONLY, O_RDWR).
        """
        if (self & self.READ) and (self & self.WRITE):
            return os.O_RDWR
        elif self & self.WRITE:
            return os.O_WRONLY
        else:
            return os.O_RDONLY

    def __str__(self) -> str:
        """Human-readable permission string."""
        if self == self.NONE:
            return "---"
        parts = []
        if self & self.READ:
            parts.append("r")
        if self & self.WRITE:
            parts.append("w")
        if self & self.EXECUTE:
            parts.append("x")
        if self & self.DELETE:
            parts.append("d")
        if self & self.CREATE:
            parts.append("c")
        return "".join(parts) if parts else "---"


class MountType(Enum):
    """
    Filesystem mount types supported by the jail system.

    Attributes
    ----------
    BIND : str
        Bind mount - mirror existing directory.
    TMPFS : str
        Temporary in-memory filesystem.
    PROC : str
        Proc filesystem for process information.
    SYSFS : str
        Sysfs for kernel/subsystem information.
    DEVTMPFS : str
        Device tmpfs for /dev.
    DEVPTS : str
        Pseudo-terminal filesystem.
    OVERLAY : str
        Overlay filesystem (copy-on-write).
    AUFS : str
        Alternative union filesystem.
    UNIONFS : str
        Union filesystem.
    RAMFS : str
        RAM-based filesystem (not swappable).
    CGROUP : str
        Cgroup filesystem.
    SECURITYFS : str
        Security filesystem.
    DEBUGFS : str
        Debug filesystem.
    TRACEFS : str
        Trace filesystem.
    HUGETLBFS : str
        HugeTLB filesystem.
    MQUEUE : str
        POSIX message queue filesystem.
    CONFIGFS : str
        Configfs for kernel configuration.
    FUSE : str
        FUSE (Filesystem in Userspace).
    NFS : str
        Network File System.
    CIFS : str
        Common Internet File System.
    VIRTIOFS : str
        Virtio-fs for VM/hypervisor shared folders.
    """

    BIND = "bind"
    TMPFS = "tmpfs"
    PROC = "proc"
    SYSFS = "sysfs"
    DEVTMPFS = "devtmpfs"
    DEVPTS = "devpts"
    OVERLAY = "overlay"
    AUFS = "aufs"
    UNIONFS = "unionfs"
    RAMFS = "ramfs"
    CGROUP = "cgroup"
    CGROUP2 = "cgroup2"
    SECURITYFS = "securityfs"
    DEBUGFS = "debugfs"
    TRACEFS = "tracefs"
    HUGETLBFS = "hugetlbfs"
    MQUEUE = "mqueue"
    CONFIGFS = "configfs"
    FUSE = "fuse"
    NFS = "nfs"
    CIFS = "cifs"
    VIRTIOFS = "virtiofs"

    def requires_device(self) -> bool:
        """
        Check if mount type requires a device/source.

        Returns
        -------
        bool
            True if device/source is required.
        """
        return self in (self.BIND, self.NFS, self.CIFS, self.VIRTIOFS)

    def is_virtual(self) -> bool:
        """
        Check if mount type is virtual (no backing storage).

        Returns
        -------
        bool
            True if virtual filesystem.
        """
        return self in (
            self.PROC, self.SYSFS, self.DEVPTS, self.CGROUP, self.CGROUP2,
            self.SECURITYFS, self.DEBUGFS, self.TRACEFS, self.CONFIGFS
        )

    def is_temporary(self) -> bool:
        """
        Check if mount type is temporary (in-memory).

        Returns
        -------
        bool
            True if temporary filesystem.
        """
        return self in (self.TMPFS, self.RAMFS, self.DEVTMPFS)


class JailFeature(IntFlag):
    """
    Feature flags for filesystem jail capabilities.

    Attributes
    ----------
    NONE : int
        No special features.
    CHROOT : int
        Chroot support available.
    PIVOT_ROOT : int
        Pivot_root support available.
    MOUNT_NAMESPACE : int
        Mount namespace support available.
    BIND_MOUNTS : int
        Bind mount support available.
    OVERLAYFS : int
        OverlayFS support available.
    TMPFS : int
        Tmpfs support available.
    USER_NAMESPACE : int
        User namespace support available.
    SECCOMP : int
        Seccomp-bpf support available.
    CAPABILITIES : int
        Capabilities support available.
    CGROUPS : int
        Cgroups support available.
    CGROUPS_V2 : int
        Cgroups v2 support available.
    ACLS : int
        POSIX ACLs support available.
    XATTRS : int
        Extended attributes support available.
    SELINUX : int
        SELinux support available.
    APPARMOR : int
        AppArmor support available.
    SYMLINKS : int
        Symlink restrictions available.
    HARD_LINKS : int
        Hard link restrictions available.
    READONLY_BIND : int
        Read-only bind mounts available.
    NOSUID : int
        Nosuid mount option available.
    NOEXEC : int
        Noexec mount option available.
    NODEV : int
        Nodev mount option available.
    QUOTA : int
        Disk quota support available.
    """

    NONE = 0
    CHROOT = auto()
    PIVOT_ROOT = auto()
    MOUNT_NAMESPACE = auto()
    BIND_MOUNTS = auto()
    OVERLAYFS = auto()
    TMPFS = auto()
    USER_NAMESPACE = auto()
    SECCOMP = auto()
    CAPABILITIES = auto()
    CGROUPS = auto()
    CGROUPS_V2 = auto()
    ACLS = auto()
    XATTRS = auto()
    SELINUX = auto()
    APPARMOR = auto()
    SYMLINKS = auto()
    HARD_LINKS = auto()
    READONLY_BIND = auto()
    NOSUID = auto()
    NOEXEC = auto()
    NODEV = auto()
    QUOTA = auto()


class JailViolation(Enum):
    """
    Types of filesystem jail violations.

    Attributes
    ----------
    PATH_NOT_ALLOWED : str
        Attempted access to path outside allowed list.
    WRITE_TO_READONLY : str
        Attempted write to read-only path.
    EXECUTE_DENIED : str
        Attempted execution of non-executable file.
    SYMLINK_TRAVERSAL : str
        Symlink pointing outside jail.
    HARD_LINK_CREATION : str
        Attempted creation of hard link.
    DEVICE_CREATION : str
        Attempted creation of device file.
    MOUNT_ATTEMPT : str
        Attempted mount operation.
    CHOWN_ATTEMPT : str
        Attempted ownership change.
    CHMOD_ATTEMPT : str
        Attempted permission change.
    QUOTA_EXCEEDED : str
        Disk quota exceeded.
    INODE_LIMIT_EXCEEDED : str
        Inode limit exceeded.
    FILE_SIZE_LIMIT : str
        File size limit exceeded.
    DIRECTORY_TRAVERSAL : str
        Directory traversal outside jail.
    FIFO_CREATION : str
        Attempted creation of FIFO/named pipe.
    SOCKET_CREATION : str
        Attempted creation of Unix socket.
    IOCTL_DENIED : str
        Ioctl operation denied.
    MMAP_DENIED : str
        Memory mapping denied.
    LOCK_DENIED : str
        File locking denied.
    """

    PATH_NOT_ALLOWED = "path_not_allowed"
    WRITE_TO_READONLY = "write_to_readonly"
    EXECUTE_DENIED = "execute_denied"
    SYMLINK_TRAVERSAL = "symlink_traversal"
    HARD_LINK_CREATION = "hard_link_creation"
    DEVICE_CREATION = "device_creation"
    MOUNT_ATTEMPT = "mount_attempt"
    CHOWN_ATTEMPT = "chown_attempt"
    CHMOD_ATTEMPT = "chmod_attempt"
    QUOTA_EXCEEDED = "quota_exceeded"
    INODE_LIMIT_EXCEEDED = "inode_limit_exceeded"
    FILE_SIZE_LIMIT = "file_size_limit"
    DIRECTORY_TRAVERSAL = "directory_traversal"
    FIFO_CREATION = "fifo_creation"
    SOCKET_CREATION = "socket_creation"
    IOCTL_DENIED = "ioctl_denied"
    MMAP_DENIED = "mmap_denied"
    LOCK_DENIED = "lock_denied"


class JailError(Exception):
    """
    Base exception for filesystem jail errors.

    Parameters
    ----------
    message : str
        Error message describing what occurred.
    violation : Optional[JailViolation]
        Type of violation that caused the error.
    path : Optional[Path]
        Filesystem path involved in the error.
    operation : Optional[str]
        Operation being performed when error occurred.
    details : Optional[Dict[str, Any]]
        Additional error context.

    Attributes
    ----------
    message : str
        Error message.
    violation : Optional[JailViolation]
        Violation type if applicable.
    path : Optional[Path]
        Involved filesystem path.
    operation : Optional[str]
        Operation attempted.
    details : Dict[str, Any]
        Additional context.
    timestamp : float
        Unix timestamp when error occurred.

    Examples
    --------
    >>> try:
    ...     jail.check_path("/etc/passwd", "write")
    ... except JailError as e:
    ...     print(f"Cannot access {e.path}: {e.violation.value}")
    """

    def __init__(
        self,
        message: str,
        violation: Optional[JailViolation] = None,
        path: Optional[Path] = None,
        operation: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.violation = violation
        self.path = Path(path) if path else None
        self.operation = operation
        self.details = details or {}
        self.timestamp = time.time()
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format comprehensive error message."""
        parts = [self.message]
        if self.violation:
            parts.append(f"[{self.violation.value}]")
        if self.path:
            parts.append(f"path={self.path}")
        if self.operation:
            parts.append(f"op={self.operation}")
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            parts.append(f"({detail_str})")
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert error to serializable dictionary.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation suitable for logging/JSON.
        """
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "violation": self.violation.value if self.violation else None,
            "path": str(self.path) if self.path else None,
            "operation": self.operation,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class PathNotAllowedError(JailError):
    """Raised when accessing a path outside allowed boundaries."""
    pass


class ReadOnlyViolationError(JailError):
    """Raised when attempting to write to a read-only path."""
    pass


class QuotaExceededError(JailError):
    """Raised when disk quota is exceeded."""
    pass


class SymlinkTraversalError(JailError):
    """Raised when symlink points outside jail boundaries."""
    pass


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class PathRestriction:
    """
    Comprehensive restriction rule for a filesystem path.

    This dataclass defines access rules for a specific path within the jail,
    including permission levels, recursion behavior, and special handling
    for symlinks, devices, and quotas.

    Parameters
    ----------
    path : Path
        Absolute or relative path to restrict.
    permission : PathPermission
        Allowed permission flags for this path.
    recursive : bool
        Whether restriction applies to all subpaths recursively.
    follow_symlinks : bool
        Whether to follow and validate symbolic links.
    allow_symlink_creation : bool
        Whether symlinks can be created in this path.
    allow_hardlinks : bool
        Whether hard links can be created.
    allow_devices : bool
        Whether device files can be created/accessed.
    allow_fifos : bool
        Whether named pipes/FIFOs can be created.
    allow_sockets : bool
        Whether Unix domain sockets can be created.
    max_file_size_mb : Optional[int]
        Maximum individual file size in megabytes.
    max_total_size_mb : Optional[int]
        Maximum total size for this path tree.
    max_files : Optional[int]
        Maximum number of files in this path tree.
    priority : int
        Rule priority (higher = evaluated first, default 0).
    description : str
        Human-readable description of this restriction.
    enabled : bool
        Whether this restriction is active.
    metadata : Dict[str, Any]
        Additional arbitrary metadata.

    Attributes
    ----------
    path : Path
        Target path.
    permission : PathPermission
        Permission flags.
    recursive : bool
        Recursive flag.
    follow_symlinks : bool
        Follow symlinks flag.
    allow_symlink_creation : bool
        Symlink creation flag.
    allow_hardlinks : bool
        Hard link flag.
    allow_devices : bool
        Device files flag.
    allow_fifos : bool
        FIFO flag.
    allow_sockets : bool
        Socket flag.
    max_file_size_mb : Optional[int]
        Max file size.
    max_total_size_mb : Optional[int]
        Max total size.
    max_files : Optional[int]
        Max file count.
    priority : int
        Rule priority.
    description : str
        Description.
    enabled : bool
        Enabled flag.
    metadata : Dict[str, Any]
        Additional metadata.
    _normalized_path : Path
        Cached normalized path.
    _path_hash : str
        Cached path hash for fast lookups.

    Examples
    --------
    >>> restriction = PathRestriction(
    ...     path=Path("/usr"),
    ...     permission=PathPermission.READ | PathPermission.EXECUTE,
    ...     recursive=True,
    ...     priority=10,
    ...     description="System binaries - read/execute only"
    ... )
    >>> 
    >>> restriction = PathRestriction(
    ...     path=Path("/tmp/jail/work"),
    ...     permission=PathPermission.FULL,
    ...     recursive=True,
    ...     max_total_size_mb=500,
    ...     max_files=1000,
    ...     description="Workspace with quota"
    ... )
    """

    path: Path
    permission: PathPermission = PathPermission.BASIC_READ
    recursive: bool = True
    follow_symlinks: bool = False
    allow_symlink_creation: bool = False
    allow_hardlinks: bool = False
    allow_devices: bool = False
    allow_fifos: bool = False
    allow_sockets: bool = False
    max_file_size_mb: Optional[int] = None
    max_total_size_mb: Optional[int] = None
    max_files: Optional[int] = None
    priority: int = 0
    description: str = ""
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Cached fields (not included in comparison)
    _normalized_path: Optional[Path] = field(default=None, repr=False, compare=False)
    _path_hash: Optional[str] = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        """Initialize cached fields after dataclass creation."""
        self._normalized_path = self.path.resolve() if self.path.exists() else self.path.absolute()
        self._path_hash = hashlib.md5(str(self._normalized_path).encode()).hexdigest()

    def matches(self, check_path: Path, follow_symlinks: bool = False) -> bool:
        """
        Check if a given path matches this restriction rule.

        This method determines whether the restriction applies to the
        specified path, taking into account recursion settings and
        symlink following preferences.

        Parameters
        ----------
        check_path : Path
            Path to check against this restriction.
        follow_symlinks : bool
            Whether to resolve symlinks before checking.

        Returns
        -------
        bool
            True if this restriction applies to the path.

        Notes
        -----
        - For recursive restrictions, any subpath matches.
        - For non-recursive restrictions, only exact path matches.
        - Symlink resolution can affect matching behavior.

        Examples
        --------
        >>> rule = PathRestriction(Path("/home"), recursive=True)
        >>> rule.matches(Path("/home/user/file.txt"))
        True
        >>> rule.matches(Path("/etc/passwd"))
        False
        """
        if not self.enabled:
            return False

        try:
            # Resolve paths for comparison
            if follow_symlinks:
                check_resolved = check_path.resolve()
            else:
                check_resolved = check_path.absolute()

            rule_resolved = self._normalized_path

            if self.recursive:
                # Check if rule path is a prefix of check path
                try:
                    check_resolved.relative_to(rule_resolved)
                    return True
                except ValueError:
                    return False
            else:
                # Exact match only
                return check_resolved == rule_resolved

        except (OSError, RuntimeError, ValueError):
            # Path resolution failed - do string comparison as fallback
            check_str = str(check_path.absolute())
            rule_str = str(self._normalized_path)

            if self.recursive:
                return check_str.startswith(rule_str)
            else:
                return check_str == rule_str

    def get_effective_permission(self, check_path: Path) -> PathPermission:
        """
        Get effective permission for a specific path under this rule.

        This method returns the applicable permission flags, potentially
        modified based on the specific path (e.g., different permissions
        for subdirectories).

        Parameters
        ----------
        check_path : Path
            Path to get permission for.

        Returns
        -------
        PathPermission
            Effective permission flags.

        Notes
        -----
        - Base implementation returns the rule's permission.
        - Subclasses can override for path-dependent permissions.
        - Write permission may be restricted if quota exceeded.
        """
        return self.permission

    def allows_operation(self, operation: str, check_path: Optional[Path] = None) -> bool:
        """
        Check if a specific operation is allowed.

        Parameters
        ----------
        operation : str
            Operation name ('read', 'write', 'execute', 'delete', etc.).
        check_path : Optional[Path]
            Specific path being operated on.

        Returns
        -------
        bool
            True if operation is allowed.

        Examples
        --------
        >>> rule.allows_operation("write")
        True
        >>> rule.allows_operation("delete")
        False
        """
        operation_map = {
            "read": PathPermission.READ,
            "write": PathPermission.WRITE,
            "execute": PathPermission.EXECUTE,
            "delete": PathPermission.DELETE,
            "create": PathPermission.CREATE,
            "mkdir": PathPermission.MKDIR,
            "rmdir": PathPermission.RMDIR,
            "chmod": PathPermission.CHMOD,
            "chown": PathPermission.CHOWN,
            "rename": PathPermission.RENAME,
            "truncate": PathPermission.TRUNCATE,
            "symlink": PathPermission.SYMLINK,
            "hardlink": PathPermission.LINK,
            "lock": PathPermission.LOCK,
            "mmap": PathPermission.MMAP,
        }

        required = operation_map.get(operation, PathPermission.NONE)
        if required == PathPermission.NONE:
            return False

        effective = self.get_effective_permission(check_path) if check_path else self.permission
        return bool(effective & required)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert restriction to serializable dictionary.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "path": str(self.path),
            "permission": self.permission.value,
            "permission_name": self.permission.name if hasattr(self.permission, 'name') else str(self.permission),
            "recursive": self.recursive,
            "follow_symlinks": self.follow_symlinks,
            "allow_symlink_creation": self.allow_symlink_creation,
            "allow_hardlinks": self.allow_hardlinks,
            "allow_devices": self.allow_devices,
            "allow_fifos": self.allow_fifos,
            "allow_sockets": self.allow_sockets,
            "max_file_size_mb": self.max_file_size_mb,
            "max_total_size_mb": self.max_total_size_mb,
            "max_files": self.max_files,
            "priority": self.priority,
            "description": self.description,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PathRestriction":
        """
        Create restriction from dictionary.

        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary containing restriction data.

        Returns
        -------
        PathRestriction
            Reconstructed PathRestriction instance.
        """
        data_copy = data.copy()
        data_copy["path"] = Path(data_copy["path"])
        if "permission" in data_copy and not isinstance(data_copy["permission"], PathPermission):
            data_copy["permission"] = PathPermission(data_copy["permission"])
        return cls(**data_copy)

    def __lt__(self, other: "PathRestriction") -> bool:
        """Compare by priority (higher priority first)."""
        return self.priority > other.priority

    def __hash__(self) -> int:
        return hash((self._normalized_path, self.recursive, self.priority))

    def __repr__(self) -> str:
        status = "enabled" if self.enabled else "disabled"
        return (f"<PathRestriction path={self.path} "
                f"perm={self.permission} recursive={self.recursive} "
                f"priority={self.priority} [{status}]>")


@dataclass
class MountEntry:
    """
    Represents a single mount point configuration in the jail.

    This dataclass defines how a filesystem should be mounted within
    the jail environment, including mount options, type, and bind settings.

    Parameters
    ----------
    source : Optional[Path]
        Source path or device for the mount.
    target : Path
        Target mount point path (relative to jail root).
    mount_type : MountType
        Type of filesystem to mount.
    options : List[str]
        Mount options (e.g., 'ro', 'noexec', 'nosuid').
    recursive : bool
        For bind mounts, whether to mount recursively.
    readonly : bool
        Force read-only mount.
    noexec : bool
        Disallow execution of binaries.
    nosuid : bool
        Ignore setuid/setgid bits.
    nodev : bool
        Disallow device files.
    noatime : bool
        Disable access time updates.
    relatime : bool
        Use relative access time updates.
    strictatime : bool
        Enforce strict access time updates.
    sync : bool
        Use synchronous writes.
    async_io : bool
        Use asynchronous I/O.
    mandatory_lock : bool
        Enable mandatory locking.
    user : Optional[str]
        Mount owner username.
    group : Optional[str]
        Mount owner group.
    fs_context : Optional[Dict[str, str]]
        Filesystem-specific context options.

    Attributes
    ----------
    source : Optional[Path]
        Mount source.
    target : Path
        Mount target.
    mount_type : MountType
        Mount type.
    options : List[str]
        Mount options.
    recursive : bool
        Recursive flag.
    readonly : bool
        Read-only flag.
    noexec : bool
        No-exec flag.
    nosuid : bool
        No-suid flag.
    nodev : bool
        No-dev flag.
    noatime : bool
        No-atime flag.
    relatime : bool
        Relatime flag.
    strictatime : bool
        Strict atime flag.
    sync : bool
        Sync flag.
    async_io : bool
        Async I/O flag.
    mandatory_lock : bool
        Mandatory lock flag.
    user : Optional[str]
        Mount user.
    group : Optional[str]
        Mount group.
    fs_context : Dict[str, str]
        FS context options.

    Examples
    --------
    >>> mount = MountEntry(
    ...     source=Path("/usr"),
    ...     target=Path("/usr"),
    ...     mount_type=MountType.BIND,
    ...     options=["ro", "noexec"],
    ...     readonly=True,
    ... )
    """

    source: Optional[Path] = None
    target: Path = field(default_factory=lambda: Path("/"))
    mount_type: MountType = MountType.BIND
    options: List[str] = field(default_factory=list)
    recursive: bool = True
    readonly: bool = False
    noexec: bool = False
    nosuid: bool = False
    nodev: bool = False
    noatime: bool = True
    relatime: bool = False
    strictatime: bool = False
    sync: bool = False
    async_io: bool = True
    mandatory_lock: bool = False
    user: Optional[str] = None
    group: Optional[str] = None
    fs_context: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        """Build options list from flags."""
        if self.readonly and "ro" not in self.options:
            self.options.append("ro")
        if self.noexec and "noexec" not in self.options:
            self.options.append("noexec")
        if self.nosuid and "nosuid" not in self.options:
            self.options.append("nosuid")
        if self.nodev and "nodev" not in self.options:
            self.options.append("nodev")
        if self.noatime and "noatime" not in self.options:
            self.options.append("noatime")
        elif self.relatime and "relatime" not in self.options:
            self.options.append("relatime")
        elif self.strictatime and "strictatime" not in self.options:
            self.options.append("strictatime")
        if self.sync and "sync" not in self.options:
            self.options.append("sync")
        elif self.async_io and "async" not in self.options:
            self.options.append("async")
        if self.mandatory_lock and "mand" not in self.options:
            self.options.append("mand")

    def to_mount_command(self, jail_root: Path) -> List[str]:
        """
        Convert to mount command arguments.

        Parameters
        ----------
        jail_root : Path
            Root path of the jail (prepended to target).

        Returns
        -------
        List[str]
            Mount command arguments.
        """
        cmd = ["mount"]

        if self.mount_type == MountType.BIND:
            cmd.extend(["--bind", str(self.source)])
        else:
            cmd.extend(["-t", self.mount_type.value])
            if self.source:
                cmd.append(str(self.source))

        full_target = jail_root / self.target.relative_to("/")
        cmd.append(str(full_target))

        if self.options:
            cmd.extend(["-o", ",".join(self.options)])

        if self.recursive and self.mount_type == MountType.BIND:
            cmd.append("--make-rprivate")

        return cmd

    def to_dict(self) -> Dict[str, Any]:
        """Convert to serializable dictionary."""
        return {
            "source": str(self.source) if self.source else None,
            "target": str(self.target),
            "mount_type": self.mount_type.value,
            "options": self.options,
            "recursive": self.recursive,
            "readonly": self.readonly,
            "noexec": self.noexec,
            "nosuid": self.nosuid,
            "nodev": self.nodev,
        }


@dataclass
class QuotaInfo:
    """
    Disk quota information for a path.

    Parameters
    ----------
    path : Path
        Path being monitored.
    used_bytes : int
        Current disk usage in bytes.
    limit_bytes : Optional[int]
        Quota limit in bytes.
    used_files : int
        Current file count.
    limit_files : Optional[int]
        File count limit.
    last_updated : float
        Timestamp of last update.

    Attributes
    ----------
    path : Path
        Monitored path.
    used_bytes : int
        Used bytes.
    limit_bytes : Optional[int]
        Byte limit.
    used_files : int
        Used file count.
    limit_files : Optional[int]
        File limit.
    last_updated : float
        Last update timestamp.
    usage_percent : float
        Calculated usage percentage.
    """

    path: Path
    used_bytes: int = 0
    limit_bytes: Optional[int] = None
    used_files: int = 0
    limit_files: Optional[int] = None
    last_updated: float = field(default_factory=time.time)

    @property
    def usage_percent(self) -> float:
        """Get usage as percentage of limit."""
        if self.limit_bytes and self.limit_bytes > 0:
            return (self.used_bytes / self.limit_bytes) * 100
        return 0.0

    @property
    def files_percent(self) -> float:
        """Get file count as percentage of limit."""
        if self.limit_files and self.limit_files > 0:
            return (self.used_files / self.limit_files) * 100
        return 0.0

    def is_exceeded(self) -> bool:
        """Check if quota is exceeded."""
        if self.limit_bytes and self.used_bytes > self.limit_bytes:
            return True
        if self.limit_files and self.used_files > self.limit_files:
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "path": str(self.path),
            "used_bytes": self.used_bytes,
            "used_mb": self.used_bytes / (1024 * 1024),
            "limit_bytes": self.limit_bytes,
            "limit_mb": self.limit_bytes / (1024 * 1024) if self.limit_bytes else None,
            "usage_percent": self.usage_percent,
            "used_files": self.used_files,
            "limit_files": self.limit_files,
            "files_percent": self.files_percent,
            "last_updated": self.last_updated,
        }


# ============================================================================
# Path Restriction Engine
# ============================================================================

class PathRestrictionEngine:
    """
    High-performance path restriction evaluation engine.

    This class manages a collection of PathRestriction rules and provides
    fast lookup and evaluation of path permissions. It uses a trie-like
    structure for O(log n) path matching.

    Attributes
    ----------
    _restrictions : List[PathRestriction]
        All registered restrictions sorted by priority.
    _path_cache : Dict[str, Optional[PathRestriction]]
        Cache of path to matching restriction.
    _prefix_trie : Dict[str, Any]
        Trie structure for fast prefix matching.
    _lock : threading.RLock
        Thread lock for concurrent access.
    _stats : Dict[str, Any]
        Performance statistics.

    Examples
    --------
    >>> engine = PathRestrictionEngine()
    >>> engine.add_restriction(PathRestriction(Path("/usr"), PathPermission.READ))
    >>> engine.add_restriction(PathRestriction(Path("/tmp"), PathPermission.FULL))
    >>> 
    >>> # Check path
    >>> perm = engine.check_path(Path("/usr/bin/gcc"), "execute")
    >>> if perm.allowed:
    ...     print("Access granted")
    """

    def __init__(self):
        self._restrictions: List[PathRestriction] = []
        self._path_cache: Dict[str, Optional[PathRestriction]] = {}
        self._prefix_trie: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._stats = {
            "total_checks": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "trie_lookups": 0,
            "violations": 0,
        }
        self._max_cache_size = 10000

    def add_restriction(self, restriction: PathRestriction) -> None:
        """
        Add a path restriction rule.

        Parameters
        ----------
        restriction : PathRestriction
            Restriction rule to add.

        Notes
        -----
        - Rules are evaluated in priority order (higher priority first).
        - Adding a rule invalidates the path cache.
        - Duplicate rules are ignored based on path and recursion.
        """
        with self._lock:
            # Check for duplicates
            for existing in self._restrictions:
                if (existing._normalized_path == restriction._normalized_path and
                    existing.recursive == restriction.recursive):
                    # Update existing instead of adding duplicate
                    existing.permission = restriction.permission
                    existing.priority = restriction.priority
                    existing.enabled = restriction.enabled
                    self._invalidate_cache()
                    return

            self._restrictions.append(restriction)
            self._restrictions.sort()  # Sort by priority
            self._add_to_trie(restriction)
            self._invalidate_cache()

    def remove_restriction(self, path: Path, recursive: bool = True) -> bool:
        """
        Remove a path restriction.

        Parameters
        ----------
        path : Path
            Path of restriction to remove.
        recursive : bool
            Whether to match recursive restrictions.

        Returns
        -------
        bool
            True if a restriction was removed.
        """
        with self._lock:
            normalized = path.resolve() if path.exists() else path.absolute()
            removed = False

            self._restrictions = [
                r for r in self._restrictions
                if not (r._normalized_path == normalized and r.recursive == recursive)
            ]

            if removed:
                self._invalidate_cache()
                self._rebuild_trie()

            return removed

    def get_restriction(self, path: Path) -> Optional[PathRestriction]:
        """
        Get the best-matching restriction for a path.

        This method finds the highest-priority restriction that applies
        to the given path. Deny rules (NONE permission) take precedence
        and stop evaluation.

        Parameters
        ----------
        path : Path
            Path to check.

        Returns
        -------
        Optional[PathRestriction]
            Matching restriction or None if no rule applies.

        Notes
        -----
        - Results are cached for performance.
        - Cache is invalidated when rules are modified.
        - Deny rules (NONE) are returned immediately.
        """
        cache_key = str(path.absolute())

        with self._lock:
            self._stats["total_checks"] += 1

            # Check cache
            if cache_key in self._path_cache:
                self._stats["cache_hits"] += 1
                return self._path_cache[cache_key]

            self._stats["cache_misses"] += 1

            # Find matching restriction
            result = self._find_matching_restriction(path)

            # Update cache
            if len(self._path_cache) < self._max_cache_size:
                self._path_cache[cache_key] = result

            return result

    def _find_matching_restriction(self, path: Path) -> Optional[PathRestriction]:
        """
        Internal method to find matching restriction.

        Parameters
        ----------
        path : Path
            Path to check.

        Returns
        -------
        Optional[PathRestriction]
            Best matching restriction.
        """
        # Try trie-based lookup first
        trie_result = self._lookup_trie(path)
        if trie_result:
            return trie_result

        # Fallback to linear scan (sorted by priority)
        for restriction in self._restrictions:
            if not restriction.enabled:
                continue

            if restriction.matches(path):
                # If this is a deny rule, return immediately
                if restriction.permission == PathPermission.NONE:
                    self._stats["violations"] += 1
                return restriction

        return None

    def check_path(
        self,
        path: Path,
        operation: str,
        follow_symlinks: bool = False,
    ) -> Tuple[bool, Optional[PathRestriction], Optional[JailViolation]]:
        """
        Check if an operation is allowed on a path.

        This is the primary method for access control. It finds the
        applicable restriction and verifies if the requested operation
        is permitted.

        Parameters
        ----------
        path : Path
            Path being accessed.
        operation : str
            Operation being performed ('read', 'write', 'execute', etc.).
        follow_symlinks : bool
            Whether to resolve symlinks before checking.

        Returns
        -------
        Tuple[bool, Optional[PathRestriction], Optional[JailViolation]]
            Tuple of (allowed, matched_restriction, violation_type).

        Examples
        --------
        >>> allowed, rule, violation = engine.check_path(
        ...     Path("/tmp/output.txt"), "write"
        ... )
        >>> if not allowed:
        ...     print(f"Access denied: {violation.value}")
        """
        # Resolve path if needed
        check_path = path.resolve() if follow_symlinks else path.absolute()

        restriction = self.get_restriction(check_path)

        if restriction is None:
            return False, None, JailViolation.PATH_NOT_ALLOWED

        if not restriction.allows_operation(operation, check_path):
            if operation == "write":
                return False, restriction, JailViolation.WRITE_TO_READONLY
            elif operation == "execute":
                return False, restriction, JailViolation.EXECUTE_DENIED
            else:
                return False, restriction, JailViolation.PATH_NOT_ALLOWED

        return True, restriction, None

    def check_symlink(self, link_path: Path, target_path: Path) -> bool:
        """
        Check if creating a symlink is allowed.

        Parameters
        ----------
        link_path : Path
            Path where symlink will be created.
        target_path : Path
            Target path of the symlink.

        Returns
        -------
        bool
            True if symlink creation is allowed.

        Notes
        -----
        - Both link path and target path are checked.
        - Target must be within allowed boundaries.
        - Symlink creation permission required on link path.
        """
        # Check link creation permission
        allowed, rule, _ = self.check_path(link_path, "symlink")
        if not allowed:
            return False

        # Check if target is within allowed boundaries
        target_allowed, _, _ = self.check_path(target_path, "read")
        if not target_allowed:
            raise SymlinkTraversalError(
                message="Symlink target outside jail",
                violation=JailViolation.SYMLINK_TRAVERSAL,
                path=link_path,
                operation="symlink",
                details={"target": str(target_path)},
            )

        # Check rule-specific symlink permission
        if rule and not rule.allow_symlink_creation:
            return False

        return True

    def _add_to_trie(self, restriction: PathRestriction) -> None:
        """
        Add restriction to prefix trie for fast lookups.

        Parameters
        ----------
        restriction : PathRestriction
            Restriction to add.
        """
        parts = str(restriction._normalized_path).split(os.sep)
        current = self._prefix_trie

        for part in parts:
            if part not in current:
                current[part] = {}
            current = current[part]

        current["__restriction__"] = restriction

    def _lookup_trie(self, path: Path) -> Optional[PathRestriction]:
        """
        Look up restriction using prefix trie.

        Parameters
        ----------
        path : Path
            Path to look up.

        Returns
        -------
        Optional[PathRestriction]
            Matching restriction or None.
        """
        self._stats["trie_lookups"] += 1

        parts = str(path.absolute()).split(os.sep)
        current = self._prefix_trie
        best_match: Optional[PathRestriction] = None
        best_priority = -1

        for part in parts:
            if part in current:
                current = current[part]
                if "__restriction__" in current:
                    rule = current["__restriction__"]
                    if rule.recursive and rule.priority > best_priority:
                        best_match = rule
                        best_priority = rule.priority
            else:
                break

        # Check exact match at the end
        if "__restriction__" in current:
            rule = current["__restriction__"]
            if not rule.recursive and rule.priority > best_priority:
                best_match = rule

        return best_match

    def _rebuild_trie(self) -> None:
        """Rebuild the prefix trie from current restrictions."""
        self._prefix_trie = {}
        for restriction in self._restrictions:
            if restriction.enabled:
                self._add_to_trie(restriction)

    def _invalidate_cache(self) -> None:
        """Invalidate the path cache."""
        self._path_cache.clear()

    def get_all_restrictions(self) -> List[PathRestriction]:
        """
        Get all registered restrictions.

        Returns
        -------
        List[PathRestriction]
            Copy of all restrictions.
        """
        with self._lock:
            return self._restrictions.copy()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get engine statistics.

        Returns
        -------
        Dict[str, Any]
            Statistics dictionary.
        """
        with self._lock:
            stats = self._stats.copy()
            stats["cache_size"] = len(self._path_cache)
            stats["total_rules"] = len(self._restrictions)
            stats["enabled_rules"] = sum(1 for r in self._restrictions if r.enabled)
            if stats["total_checks"] > 0:
                stats["cache_hit_rate"] = stats["cache_hits"] / stats["total_checks"]
            else:
                stats["cache_hit_rate"] = 0.0
            return stats

    def clear_cache(self) -> None:
        """Clear the path cache."""
        with self._lock:
            self._path_cache.clear()

    def __len__(self) -> int:
        return len(self._restrictions)


# ============================================================================
# Mount Manager
# ============================================================================

class MountManager:
    """
    Advanced mount point manager for filesystem jail.

    This class handles all mount operations within the jail, including
    bind mounts, tmpfs, overlay filesystems, and automatic cleanup.

    Attributes
    ----------
    jail_root : Path
        Root path of the jail.
    _mounts : List[MountEntry]
        Configured mount entries.
    _active_mounts : List[Path]
        Currently active mount points.
    _lock : threading.RLock
        Thread lock for mount operations.
    _available_features : JailFeature
        Features available on this system.

    Examples
    --------
    >>> manager = MountManager(Path("/tmp/jail"))
    >>> manager.add_bind_mount(Path("/usr"), Path("/usr"), readonly=True)
    >>> manager.add_tmpfs(Path("/tmp"), size_mb=100)
    >>> manager.mount_all()
    >>> # ... use jail ...
    >>> manager.umount_all()
    """

    def __init__(self, jail_root: Path):
        self.jail_root = Path(jail_root).resolve()
        self._mounts: List[MountEntry] = []
        self._active_mounts: List[Path] = []
        self._lock = threading.RLock()
        self._available_features = self._detect_features()
        self._mount_namespace_active = False

    def _detect_features(self) -> JailFeature:
        """
        Detect available mount features on this system.

        Returns
        -------
        JailFeature
            Bitmask of available features.
        """
        features = JailFeature.NONE

        # Check bind mounts
        if self._check_kernel_feature("bind"):
            features |= JailFeature.BIND_MOUNTS

        # Check overlayfs
        if Path("/sys/module/overlay").exists():
            features |= JailFeature.OVERLAYFS

        # Check tmpfs
        if self._check_kernel_feature("tmpfs"):
            features |= JailFeature.TMPFS

        # Check mount namespace
        if Path("/proc/self/ns/mnt").exists():
            features |= JailFeature.MOUNT_NAMESPACE

        # Check user namespace
        if Path("/proc/self/ns/user").exists():
            features |= JailFeature.USER_NAMESPACE

        return features

    def _check_kernel_feature(self, feature: str) -> bool:
        """
        Check if kernel feature is available.

        Parameters
        ----------
        feature : str
            Feature name.

        Returns
        -------
        bool
            True if available.
        """
        try:
            with open("/proc/filesystems", "r") as f:
                return any(feature in line for line in f)
        except (IOError, OSError):
            return False

    def add_bind_mount(
        self,
        source: Path,
        target: Path,
        readonly: bool = False,
        recursive: bool = True,
        **kwargs,
    ) -> MountEntry:
        """
        Add a bind mount configuration.

        Parameters
        ----------
        source : Path
            Source directory to bind.
        target : Path
            Target mount point (relative to jail root).
        readonly : bool
            Mount as read-only.
        recursive : bool
            Use recursive bind mount.
        **kwargs : Any
            Additional mount options.

        Returns
        -------
        MountEntry
            Created mount entry.

        Raises
        ------
        JailError
            If bind mounts are not supported.
        """
        if not (self._available_features & JailFeature.BIND_MOUNTS):
            raise JailError(
                message="Bind mounts not supported on this system",
                violation=JailViolation.MOUNT_ATTEMPT,
            )

        entry = MountEntry(
            source=Path(source).resolve(),
            target=Path(target),
            mount_type=MountType.BIND,
            readonly=readonly,
            recursive=recursive,
            **kwargs,
        )

        with self._lock:
            self._mounts.append(entry)

        return entry

    def add_tmpfs(
        self,
        target: Path,
        size_mb: Optional[int] = None,
        mode: str = "1777",
        **kwargs,
    ) -> MountEntry:
        """
        Add a tmpfs mount configuration.

        Parameters
        ----------
        target : Path
            Target mount point.
        size_mb : Optional[int]
            Maximum size in megabytes.
        mode : str
            Mount point permissions.
        **kwargs : Any
            Additional options.

        Returns
        -------
        MountEntry
            Created mount entry.
        """
        entry = MountEntry(
            target=Path(target),
            mount_type=MountType.TMPFS,
            **kwargs,
        )

        if size_mb:
            entry.options.append(f"size={size_mb}m")
        if mode:
            entry.options.append(f"mode={mode}")

        with self._lock:
            self._mounts.append(entry)

        return entry

    def add_overlay(
        self,
        target: Path,
        lower_dirs: List[Path],
        upper_dir: Path,
        work_dir: Path,
        **kwargs,
    ) -> MountEntry:
        """
        Add an overlay filesystem mount.

        Parameters
        ----------
        target : Path
            Target mount point.
        lower_dirs : List[Path]
            Lower (read-only) directories.
        upper_dir : Path
            Upper (writable) directory.
        work_dir : Path
            Work directory for overlay.
        **kwargs : Any
            Additional options.

        Returns
        -------
        MountEntry
            Created mount entry.

        Raises
        ------
        JailError
            If overlayfs is not supported.
        """
        if not (self._available_features & JailFeature.OVERLAYFS):
            raise JailError(
                message="OverlayFS not supported on this system",
                violation=JailViolation.MOUNT_ATTEMPT,
            )

        lower_str = ":".join(str(p) for p in lower_dirs)
        entry = MountEntry(
            target=Path(target),
            mount_type=MountType.OVERLAY,
            **kwargs,
        )
        entry.options.append(f"lowerdir={lower_str}")
        entry.options.append(f"upperdir={upper_dir}")
        entry.options.append(f"workdir={work_dir}")

        with self._lock:
            self._mounts.append(entry)

        return entry

    def add_proc(self, target: Path = Path("/proc")) -> MountEntry:
        """
        Add proc filesystem mount.

        Parameters
        ----------
        target : Path
            Target mount point.

        Returns
        -------
        MountEntry
            Created mount entry.
        """
        entry = MountEntry(
            source=None,
            target=target,
            mount_type=MountType.PROC,
            options=["nosuid", "noexec", "nodev"],
        )

        with self._lock:
            self._mounts.append(entry)

        return entry

    def add_sysfs(self, target: Path = Path("/sys")) -> MountEntry:
        """
        Add sysfs mount.

        Parameters
        ----------
        target : Path
            Target mount point.

        Returns
        -------
        MountEntry
            Created mount entry.
        """
        entry = MountEntry(
            source=None,
            target=target,
            mount_type=MountType.SYSFS,
            options=["nosuid", "noexec", "nodev"],
        )

        with self._lock:
            self._mounts.append(entry)

        return entry

    def add_devtmpfs(self, target: Path = Path("/dev")) -> MountEntry:
        """
        Add devtmpfs mount.

        Parameters
        ----------
        target : Path
            Target mount point.

        Returns
        -------
        MountEntry
            Created mount entry.
        """
        entry = MountEntry(
            source=None,
            target=target,
            mount_type=MountType.DEVTMPFS,
            options=["nosuid", "noexec", "mode=0755"],
        )

        with self._lock:
            self._mounts.append(entry)

        return entry

    def add_devpts(self, target: Path = Path("/dev/pts")) -> MountEntry:
        """
        Add devpts mount for pseudo-terminals.

        Parameters
        ----------
        target : Path
            Target mount point.

        Returns
        -------
        MountEntry
            Created mount entry.
        """
        entry = MountEntry(
            source=None,
            target=target,
            mount_type=MountType.DEVPTS,
            options=["nosuid", "noexec", "mode=0620", "ptmxmode=0666"],
        )

        with self._lock:
            self._mounts.append(entry)

        return entry

    def mount_all(self) -> List[Path]:
        """
        Mount all configured mount points.

        Returns
        -------
        List[Path]
            List of successfully mounted paths.

        Raises
        ------
        JailError
            If mount operation fails.
        """
        mounted = []

        with self._lock:
            # Sort mounts to ensure proper order (e.g., /dev before /dev/pts)
            sorted_mounts = sorted(
                self._mounts,
                key=lambda m: (len(m.target.parts), str(m.target))
            )

            for entry in sorted_mounts:
                try:
                    full_target = self.jail_root / entry.target.relative_to("/")
                    full_target.mkdir(parents=True, exist_ok=True)

                    if not self._is_mounted(full_target):
                        cmd = entry.to_mount_command(self.jail_root)
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            check=False,
                        )

                        if result.returncode == 0:
                            self._active_mounts.append(full_target)
                            mounted.append(full_target)
                            logger.debug(f"Mounted {entry.target} ({entry.mount_type.value})")
                        else:
                            logger.error(f"Failed to mount {entry.target}: {result.stderr}")

                except Exception as e:
                    logger.error(f"Mount error for {entry.target}: {e}")

        return mounted

    def umount_all(self, force: bool = False) -> List[Path]:
        """
        Unmount all active mount points.

        Parameters
        ----------
        force : bool
            Force lazy unmount if busy.

        Returns
        -------
        List[Path]
            List of successfully unmounted paths.
        """
        unmounted = []

        # Unmount in reverse order
        for mount_point in reversed(self._active_mounts):
            try:
                if self._is_mounted(mount_point):
                    cmd = ["umount"]
                    if force:
                        cmd.append("-l")  # Lazy unmount
                    cmd.append(str(mount_point))

                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    if result.returncode == 0:
                        unmounted.append(mount_point)
                        logger.debug(f"Unmounted {mount_point}")

            except Exception as e:
                logger.error(f"Unmount error for {mount_point}: {e}")

        with self._lock:
            for path in unmounted:
                if path in self._active_mounts:
                    self._active_mounts.remove(path)

        return unmounted

    def _is_mounted(self, path: Path) -> bool:
        """
        Check if a path is a mount point.

        Parameters
        ----------
        path : Path
            Path to check.

        Returns
        -------
        bool
            True if path is mounted.
        """
        try:
            # Check /proc/mounts
            with open("/proc/mounts", "r") as f:
                for line in f:
                    if str(path) in line.split():
                        return True

            # Check parent device differs
            path_stat = path.stat()
            parent_stat = path.parent.stat()
            return path_stat.st_dev != parent_stat.st_dev

        except (IOError, OSError):
            return False

    def get_active_mounts(self) -> List[Path]:
        """
        Get list of currently active mounts.

        Returns
        -------
        List[Path]
            Active mount points.
        """
        with self._lock:
            return self._active_mounts.copy()

    def get_mount_info(self) -> List[Dict[str, Any]]:
        """
        Get information about all mounts.

        Returns
        -------
        List[Dict[str, Any]]
            List of mount information dictionaries.
        """
        info = []
        for mount in self._active_mounts:
            try:
                stat_info = mount.stat()
                info.append({
                    "path": str(mount),
                    "device": stat_info.st_dev,
                    "inode": stat_info.st_ino,
                    "is_mounted": self._is_mounted(mount),
                })
            except OSError:
                info.append({
                    "path": str(mount),
                    "is_mounted": False,
                    "error": "stat failed",
                })
        return info

    def clear(self) -> None:
        """Clear all mount configurations."""
        with self._lock:
            self._mounts.clear()


# ============================================================================
# Main FilesystemJail Class
# ============================================================================

class FilesystemJail:
    """
    Comprehensive filesystem jail for secure process execution.

    This class provides a complete filesystem isolation solution with
    path-based access control, chroot support, mount management, and
    resource monitoring.

    Parameters
    ----------
    root_path : Path
        Root directory for the jail.
    allowed_paths : Optional[List[Path]]
        Paths explicitly allowed for access.
    denied_paths : Optional[List[Path]]
        Paths explicitly denied.
    read_only_paths : Optional[List[Path]]
        Paths allowed with read-only access.
    executable_paths : Optional[List[Path]]
        Paths where execution is permitted.
    writable_paths : Optional[List[Path]]
        Paths where writing is permitted.
    use_chroot : bool
        Use actual chroot system call (requires root).
    use_overlay : bool
        Use overlayfs for copy-on-write isolation.
    overlay_lower_dirs : Optional[List[Path]]
        Lower directories for overlayfs.
    allow_network : bool
        Allow network-related files (e.g., /etc/resolv.conf).
    allow_devices : bool
        Allow device file access.
    disk_quota_mb : Optional[int]
        Maximum total disk usage in jail.
    max_files : Optional[int]
        Maximum number of files in jail.
    max_file_size_mb : Optional[int]
        Maximum individual file size.
    temp_workspace : bool
        Create temporary workspace that auto-cleans.
    cleanup_on_exit : bool
        Automatically cleanup on context manager exit.
    readonly_root : bool
        Make root filesystem read-only.
    hide_system_paths : bool
        Hide sensitive system paths (/proc, /sys, etc.).
    preserve_env : bool
        Preserve original environment variables.

    Attributes
    ----------
    root_path : Path
        Jail root directory.
    restriction_engine : PathRestrictionEngine
        Path restriction evaluation engine.
    mount_manager : MountManager
        Mount point manager.
    use_chroot : bool
        Chroot enabled flag.
    use_overlay : bool
        Overlayfs enabled flag.
    allow_network : bool
        Network allowed flag.
    cleanup_on_exit : bool
        Auto-cleanup flag.
    _quota_info : Dict[Path, QuotaInfo]
        Quota monitoring information.
    _setup_complete : bool
        Whether jail has been set up.
    _temp_workspace : Optional[TempWorkspace]
        Temporary workspace manager.

    Examples
    --------
    >>> # Basic read-only jail
    >>> jail = FilesystemJail(
    ...     root_path=Path("/tmp/sandbox"),
    ...     allowed_paths=[Path("/usr/bin"), Path("/lib")],
    ...     read_only_paths=[Path("/usr"), Path("/etc")],
    ... )
    >>> jail.setup()
    >>> result = jail.execute(["gcc", "source.c"])
    >>> jail.cleanup()

    >>> # Advanced jail with overlay and quotas
    >>> jail = FilesystemJail(
    ...     root_path=Path("/tmp/sandbox"),
    ...     use_overlay=True,
    ...     overlay_lower_dirs=[Path("/usr"), Path("/lib")],
    ...     writable_paths=[Path("/tmp"), Path("/home/user/work")],
    ...     disk_quota_mb=500,
    ...     max_files=1000,
    ...     allow_network=False,
    ... )
    >>> with jail:
    ...     result = jailed_execute(["make", "-j4"])
    """

    # System paths that may need to be available
    SYSTEM_PATHS = [
        "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/lib",
        "/lib", "/lib64", "/usr/lib64", "/usr/libexec",
        "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d",
        "/etc/alternatives", "/etc/passwd", "/etc/group",
        "/etc/nsswitch.conf", "/etc/hosts", "/etc/hostname",
    ]

    # Device files needed for basic operation
    DEVICE_FILES = [
        "/dev/null", "/dev/zero", "/dev/random", "/dev/urandom",
        "/dev/stdin", "/dev/stdout", "/dev/stderr", "/dev/fd",
        "/dev/full", "/dev/tty",
    ]

    # Network-related files
    NETWORK_FILES = [
        "/etc/resolv.conf", "/etc/hosts", "/etc/hostname",
        "/etc/nsswitch.conf", "/etc/services", "/etc/protocols",
    ]

    # Sensitive paths to hide
    SENSITIVE_PATHS = [
        "/proc", "/sys", "/dev", "/run", "/var/run",
        "/boot", "/root", "/home/*/.ssh", "/home/*/.gnupg",
        "/etc/shadow", "/etc/sudoers", "/etc/ssh",
    ]

    def __init__(
        self,
        root_path: Path,
        allowed_paths: Optional[List[Path]] = None,
        denied_paths: Optional[List[Path]] = None,
        read_only_paths: Optional[List[Path]] = None,
        executable_paths: Optional[List[Path]] = None,
        writable_paths: Optional[List[Path]] = None,
        use_chroot: bool = False,
        use_overlay: bool = False,
        overlay_lower_dirs: Optional[List[Path]] = None,
        allow_network: bool = False,
        allow_devices: bool = False,
        disk_quota_mb: Optional[int] = None,
        max_files: Optional[int] = None,
        max_file_size_mb: Optional[int] = None,
        temp_workspace: bool = False,
        cleanup_on_exit: bool = True,
        readonly_root: bool = True,
        hide_system_paths: bool = True,
        preserve_env: bool = True,
    ):
        self.root_path = Path(root_path).resolve()
        self.use_chroot = use_chroot and os.geteuid() == 0
        self.use_overlay = use_overlay
        self.overlay_lower_dirs = overlay_lower_dirs or []
        self.allow_network = allow_network
        self.allow_devices = allow_devices
        self.disk_quota_mb = disk_quota_mb
        self.max_files = max_files
        self.max_file_size_mb = max_file_size_mb
        self.cleanup_on_exit = cleanup_on_exit
        self.readonly_root = readonly_root
        self.hide_system_paths = hide_system_paths
        self.preserve_env = preserve_env

        # Initialize components
        self.restriction_engine = PathRestrictionEngine()
        self.mount_manager = MountManager(self.root_path)

        # State tracking
        self._setup_complete = False
        self._temp_workspace: Optional[TempWorkspace] = None
        self._quota_info: Dict[Path, QuotaInfo] = {}
        self._original_cwd = Path.cwd()
        self._chroot_active = False

        # Setup workspace
        if temp_workspace:
            self._temp_workspace = TempWorkspace(prefix="jail_")
            self.root_path = self._temp_workspace.path

        # Build restrictions from parameters
        self._build_restrictions(
            allowed_paths, denied_paths, read_only_paths,
            executable_paths, writable_paths,
        )

        # Add system paths
        self._add_system_paths()

        # Add network files if allowed
        if allow_network:
            self._add_network_files()

        # Add devices if allowed
        if allow_devices:
            self._add_device_files()

        # Hide sensitive paths
        if hide_system_paths:
            self._hide_sensitive_paths()

    def _build_restrictions(
        self,
        allowed_paths: Optional[List[Path]],
        denied_paths: Optional[List[Path]],
        read_only_paths: Optional[List[Path]],
        executable_paths: Optional[List[Path]],
        writable_paths: Optional[List[Path]],
    ) -> None:
        """
        Build path restrictions from parameters.

        Parameters
        ----------
        allowed_paths : Optional[List[Path]]
            Allowed paths.
        denied_paths : Optional[List[Path]]
            Denied paths.
        read_only_paths : Optional[List[Path]]
            Read-only paths.
        executable_paths : Optional[List[Path]]
            Executable paths.
        writable_paths : Optional[List[Path]]
            Writable paths.
        """
        # Deny sensitive paths first (highest priority)
        for path in (denied_paths or []):
            self.restriction_engine.add_restriction(PathRestriction(
                path=Path(path),
                permission=PathPermission.NONE,
                recursive=True,
                priority=100,
                description="Explicitly denied",
            ))

        # Writable paths (high priority)
        for path in (writable_paths or []):
            self.restriction_engine.add_restriction(PathRestriction(
                path=Path(path),
                permission=PathPermission.FULL,
                recursive=True,
                priority=80,
                description="Writable path",
                max_file_size_mb=self.max_file_size_mb,
                max_total_size_mb=self.disk_quota_mb,
                max_files=self.max_files,
            ))

        # Executable paths
        for path in (executable_paths or []):
            self.restriction_engine.add_restriction(PathRestriction(
                path=Path(path),
                permission=PathPermission.READ | PathPermission.EXECUTE,
                recursive=True,
                priority=70,
                description="Executable path",
            ))

        # Read-only paths
        for path in (read_only_paths or []):
            self.restriction_engine.add_restriction(PathRestriction(
                path=Path(path),
                permission=PathPermission.READ,
                recursive=True,
                priority=60,
                description="Read-only path",
            ))

        # General allowed paths
        for path in (allowed_paths or []):
            self.restriction_engine.add_restriction(PathRestriction(
                path=Path(path),
                permission=PathPermission.BASIC_READ,
                recursive=True,
                priority=50,
                description="Allowed path",
            ))

        # Root path always allowed
        root_perm = PathPermission.BASIC_READ if self.readonly_root else PathPermission.FULL
        self.restriction_engine.add_restriction(PathRestriction(
            path=self.root_path,
            permission=root_perm,
            recursive=True,
            priority=90,
            description="Jail root",
            max_file_size_mb=self.max_file_size_mb,
            max_total_size_mb=self.disk_quota_mb,
            max_files=self.max_files,
        ))

    def _add_system_paths(self) -> None:
        """Add essential system paths to allowed list."""
        for sys_path in self.SYSTEM_PATHS:
            path = Path(sys_path)
            if path.exists():
                self.restriction_engine.add_restriction(PathRestriction(
                    path=path,
                    permission=PathPermission.READ | PathPermission.EXECUTE,
                    recursive=True,
                    priority=40,
                    description="System path",
                ))

    def _add_network_files(self) -> None:
        """Add network configuration files."""
        for net_file in self.NETWORK_FILES:
            path = Path(net_file)
            if path.exists():
                self.restriction_engine.add_restriction(PathRestriction(
                    path=path,
                    permission=PathPermission.READ,
                    recursive=False,
                    priority=40,
                    description="Network configuration",
                ))

    def _add_device_files(self) -> None:
        """Add basic device files."""
        for dev_file in self.DEVICE_FILES:
            path = Path(dev_file)
            self.restriction_engine.add_restriction(PathRestriction(
                path=path,
                permission=PathPermission.READ | PathPermission.WRITE,
                recursive=False,
                priority=40,
                description="Device file",
                allow_devices=True,
            ))

    def _hide_sensitive_paths(self) -> None:
        """Hide sensitive system paths."""
        for sensitive in self.SENSITIVE_PATHS:
            if "*" in sensitive:
                # Handle wildcard patterns
                import glob
                for path_str in glob.glob(sensitive):
                    self.restriction_engine.add_restriction(PathRestriction(
                        path=Path(path_str),
                        permission=PathPermission.NONE,
                        recursive=True,
                        priority=100,
                        description="Hidden sensitive path",
                    ))
            else:
                path = Path(sensitive)
                if path.exists() or path.parent.exists():
                    self.restriction_engine.add_restriction(PathRestriction(
                        path=path,
                        permission=PathPermission.NONE,
                        recursive=True,
                        priority=100,
                        description="Hidden sensitive path",
                    ))

    def setup(self) -> bool:
        """
        Setup the filesystem jail.

        This method prepares the jail environment:
        1. Creates root directory structure
        2. Sets up mounts (bind, tmpfs, overlay)
        3. Copies essential files
        4. Configures chroot if enabled
        5. Sets up resource monitoring

        Returns
        -------
        bool
            True if setup completed successfully.

        Raises
        ------
        JailError
            If setup fails.
        """
        if self._setup_complete:
            logger.warning("Jail already set up")
            return True

        logger.info(f"Setting up filesystem jail at {self.root_path}")

        try:
            # Create root directory
            self.root_path.mkdir(parents=True, exist_ok=True)

            # Setup basic directory structure
            self._create_directory_structure()

            # Setup mounts
            self._setup_mounts()

            # Setup chroot if enabled
            if self.use_chroot:
                self._setup_chroot_environment()

            # Copy essential files
            self._copy_essential_files()

            # Setup resource monitoring
            if self.disk_quota_mb or self.max_files:
                self._setup_quota_monitoring()

            self._setup_complete = True
            logger.info("Filesystem jail setup complete")

            return True

        except Exception as e:
            logger.error(f"Jail setup failed: {e}")
            self.cleanup()
            raise JailError(
                message=f"Failed to setup jail: {e}",
                violation=JailViolation.MOUNT_ATTEMPT,
                details={"root": str(self.root_path)},
            ) from e

    def _create_directory_structure(self) -> None:
        """Create basic directory structure in jail."""
        directories = [
            "/tmp", "/var/tmp", "/run", "/var/run",
            "/dev", "/proc", "/sys", "/etc",
            "/usr", "/usr/bin", "/usr/lib", "/usr/local",
            "/bin", "/sbin", "/lib", "/lib64",
            "/home", "/root",
        ]

        for dir_path in directories:
            full_path = self.root_path / dir_path.lstrip("/")
            full_path.mkdir(parents=True, exist_ok=True)

    def _setup_mounts(self) -> None:
        """Setup all configured mounts."""
        # Setup overlay if requested
        if self.use_overlay and self.overlay_lower_dirs:
            self._setup_overlay()

        # Add basic virtual filesystems
        if not self.hide_system_paths:
            self.mount_manager.add_proc()
            self.mount_manager.add_sysfs()
            self.mount_manager.add_devtmpfs()
            self.mount_manager.add_devpts()

        # Add tmpfs for temporary directories
        self.mount_manager.add_tmpfs(Path("/tmp"), size_mb=100)
        self.mount_manager.add_tmpfs(Path("/run"), size_mb=10)

        # Mount all
        self.mount_manager.mount_all()

    def _setup_overlay(self) -> None:
        """Setup overlay filesystem."""
        lower_dirs = [Path(d).resolve() for d in self.overlay_lower_dirs]
        upper_dir = self.root_path / ".overlay_upper"
        work_dir = self.root_path / ".overlay_work"

        upper_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)

        self.mount_manager.add_overlay(
            target=Path("/"),
            lower_dirs=lower_dirs,
            upper_dir=upper_dir,
            work_dir=work_dir,
        )

    def _setup_chroot_environment(self) -> None:
        """
        Setup minimal chroot environment.

        This requires root privileges and copies essential libraries
        and binaries to the jail.
        """
        if os.geteuid() != 0:
            logger.warning("Chroot requires root privileges")
            self.use_chroot = False
            return

        # Copy essential libraries
        self._copy_essential_libraries()

        # Create basic device nodes if not mounted
        dev_path = self.root_path / "dev"
        if not self.mount_manager._is_mounted(dev_path):
            self._create_basic_devices(dev_path)

    def _copy_essential_libraries(self) -> None:
        """
        Copy essential shared libraries to jail.

        This method uses ldd to discover required libraries and
        copies them to the appropriate locations in the jail.
        """
        essential_binaries = ["/bin/sh", "/bin/bash", "/usr/bin/env"]

        lib_paths = [
            "/lib/x86_64-linux-gnu",
            "/lib64",
            "/usr/lib/x86_64-linux-gnu",
            "/usr/lib64",
            "/lib/aarch64-linux-gnu",
            "/usr/lib/aarch64-linux-gnu",
        ]

        for lib_path in lib_paths:
            src = Path(lib_path)
            if src.exists():
                dest = self.root_path / lib_path.lstrip("/")
                dest.parent.mkdir(parents=True, exist_ok=True)

                if not dest.exists():
                    try:
                        # Copy symlinks and libraries
                        for item in src.iterdir():
                            if item.is_symlink() or item.suffix in (".so", ".so.*"):
                                target = dest / item.name
                                if item.is_symlink():
                                    link_target = item.readlink()
                                    target.symlink_to(link_target)
                                else:
                                    shutil.copy2(item, target, follow_symlinks=False)
                    except (OSError, shutil.Error) as e:
                        logger.debug(f"Library copy warning: {e}")

    def _create_basic_devices(self, dev_path: Path) -> None:
        """
        Create basic device files in /dev.

        Parameters
        ----------
        dev_path : Path
            Device directory path.
        """
        devices = [
            ("null", 1, 3, 0o666),
            ("zero", 1, 5, 0o666),
            ("random", 1, 8, 0o444),
            ("urandom", 1, 9, 0o444),
            ("tty", 5, 0, 0o666),
            ("full", 1, 7, 0o666),
        ]

        for name, major, minor, mode in devices:
            device_file = dev_path / name
            if not device_file.exists():
                try:
                    os.mknod(str(device_file), stat.S_IFCHR | mode, os.makedev(major, minor))
                except (OSError, PermissionError) as e:
                    logger.debug(f"Cannot create {name}: {e}")

        # Create symlinks
        symlinks = [
            ("/proc/self/fd", "/dev/fd"),
            ("/proc/self/fd/0", "/dev/stdin"),
            ("/proc/self/fd/1", "/dev/stdout"),
            ("/proc/self/fd/2", "/dev/stderr"),
        ]

        for target, link in symlinks:
            link_path = self.root_path / link.lstrip("/")
            if not link_path.exists():
                try:
                    link_path.symlink_to(target)
                except OSError:
                    pass

    def _copy_essential_files(self) -> None:
        """Copy essential configuration files to jail."""
        essential_files = [
            "/etc/passwd", "/etc/group", "/etc/nsswitch.conf",
            "/etc/ld.so.cache", "/etc/ld.so.conf",
        ]

        if self.allow_network:
            essential_files.extend(self.NETWORK_FILES)

        for file_path in essential_files:
            src = Path(file_path)
            if src.exists():
                dest = self.root_path / file_path.lstrip("/")
                dest.parent.mkdir(parents=True, exist_ok=True)

                if not dest.exists():
                    try:
                        shutil.copy2(src, dest)
                    except OSError:
                        pass

    def _setup_quota_monitoring(self) -> None:
        """Setup disk quota monitoring."""
        for restriction in self.restriction_engine.get_all_restrictions():
            if restriction.max_total_size_mb or restriction.max_files:
                self._quota_info[restriction._normalized_path] = QuotaInfo(
                    path=restriction._normalized_path,
                    limit_bytes=restriction.max_total_size_mb * 1024 * 1024 if restriction.max_total_size_mb else None,
                    limit_files=restriction.max_files,
                )

    def check_path(
        self,
        path: Path,
        operation: str,
        follow_symlinks: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if an operation is allowed on a path.

        Parameters
        ----------
        path : Path
            Path to check.
        operation : str
            Operation type ('read', 'write', 'execute', 'delete', etc.).
        follow_symlinks : bool
            Whether to resolve symlinks.

        Returns
        -------
        Tuple[bool, Optional[str]]
            Tuple of (allowed, error_message).
        """
        # Adjust path for chroot
        if self._chroot_active:
            try:
                path = path.relative_to(self.root_path)
            except ValueError:
                path = Path("/") / path

        allowed, rule, violation = self.restriction_engine.check_path(
            path, operation, follow_symlinks
        )

        if not allowed:
            error_msg = f"Access denied: {violation.value if violation else 'not allowed'}"
            return False, error_msg

        # Check quota for write operations
        if operation == "write" and rule and rule.max_total_size_mb:
            quota = self._quota_info.get(rule._normalized_path)
            if quota and quota.is_exceeded():
                return False, f"Quota exceeded: {quota.usage_percent:.1f}% used"

        return True, None

    def resolve_path(self, path: Path) -> Path:
        """
        Resolve a path within the jail.

        Parameters
        ----------
        path : Path
            Path to resolve.

        Returns
        -------
        Path
            Resolved absolute path within jail.
        """
        if self._chroot_active:
            return Path("/") / path.absolute().relative_to(self.root_path)
        return self.root_path / path

    def execute(
        self,
        cmd: List[str],
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None,
        input_data: Optional[str] = None,
        capture_output: bool = True,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """
        Execute a command within the jail.

        Parameters
        ----------
        cmd : List[str]
            Command to execute.
        env : Optional[Dict[str, str]]
            Environment variables.
        cwd : Optional[Path]
            Working directory (relative to jail root).
        input_data : Optional[str]
            Data to send to stdin.
        capture_output : bool
            Capture stdout/stderr.
        timeout : Optional[float]
            Execution timeout in seconds.
        **kwargs : Any
            Additional subprocess arguments.

        Returns
        -------
        subprocess.CompletedProcess
            Process result.

        Raises
        ------
        JailError
            If command execution fails due to jail restrictions.
        """
        if not self._setup_complete:
            self.setup()

        # Resolve working directory
        work_dir = self.root_path
        if cwd:
            work_dir = work_dir / cwd
            work_dir.mkdir(parents=True, exist_ok=True)

        # Check executable access
        exe_path = Path(cmd[0])
        if not exe_path.is_absolute():
            # Search in PATH
            exe_path = self._find_executable(cmd[0])

        allowed, error = self.check_path(exe_path, "execute")
        if not allowed:
            raise JailError(
                message=f"Cannot execute {cmd[0]}: {error}",
                violation=JailViolation.EXECUTE_DENIED,
                path=exe_path,
            )

        # Prepare environment
        process_env = {}
        if self.preserve_env:
            process_env.update(os.environ)
        if env:
            process_env.update(env)

        # Add jail environment
        process_env.update(self.get_environment())

        # Execute command
        try:
            if self.use_chroot:
                return self._execute_chroot(cmd, process_env, work_dir, timeout)
            else:
                return subprocess.run(
                    cmd,
                    env=process_env,
                    cwd=str(work_dir),
                    input=input_data,
                    capture_output=capture_output,
                    text=True,
                    timeout=timeout,
                    **kwargs,
                )

        except subprocess.TimeoutExpired as e:
            raise JailError(
                message=f"Command timed out after {timeout}s",
                details={"cmd": cmd},
            ) from e
        except Exception as e:
            raise JailError(
                message=f"Command execution failed: {e}",
                details={"cmd": cmd},
            ) from e

    def _find_executable(self, name: str) -> Path:
        """
        Find executable in PATH within jail.

        Parameters
        ----------
        name : str
            Executable name.

        Returns
        -------
        Path
            Full path to executable.

        Raises
        ------
        JailError
            If executable not found.
        """
        path_dirs = ["/usr/bin", "/usr/sbin", "/bin", "/sbin", "/usr/local/bin"]

        for dir_path in path_dirs:
            exe_path = self.root_path / dir_path.lstrip("/") / name
            if exe_path.exists() and os.access(exe_path, os.X_OK):
                return exe_path

        # Check if absolute path was given
        if Path(name).is_absolute():
            exe_path = self.root_path / name.lstrip("/")
            if exe_path.exists():
                return exe_path

        raise JailError(
            message=f"Executable not found: {name}",
            violation=JailViolation.PATH_NOT_ALLOWED,
        )

    def _execute_chroot(
        self,
        cmd: List[str],
        env: Dict[str, str],
        cwd: Path,
        timeout: Optional[float],
    ) -> subprocess.CompletedProcess:
        """
        Execute command in chroot environment.

        This requires root privileges and uses os.chroot().

        Parameters
        ----------
        cmd : List[str]
            Command to execute.
        env : Dict[str, str]
            Environment variables.
        cwd : Path
            Working directory.
        timeout : Optional[float]
            Timeout in seconds.

        Returns
        -------
        subprocess.CompletedProcess
            Process result.
        """
        # This would use os.fork() and os.chroot()
        # For simplicity, we use subprocess with chroot wrapper
        chroot_cmd = ["chroot", str(self.root_path)] + cmd

        return subprocess.run(
            chroot_cmd,
            env=env,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def get_environment(self) -> Dict[str, str]:
        """
        Get environment variables for jailed execution.

        Returns
        -------
        Dict[str, str]
            Environment variables.
        """
        env = {}

        # Set paths relative to jail
        env["PATH"] = "/usr/bin:/usr/sbin:/bin:/sbin:/usr/local/bin"
        env["HOME"] = "/"
        env["USER"] = os.environ.get("USER", "nobody")
        env["LOGNAME"] = env["USER"]
        env["SHELL"] = "/bin/sh"
        env["LANG"] = os.environ.get("LANG", "C.UTF-8")
        env["LC_ALL"] = os.environ.get("LC_ALL", "C.UTF-8")

        # Set temporary directories
        env["TMPDIR"] = "/tmp"
        env["TEMP"] = "/tmp"
        env["TMP"] = "/tmp"
        env["TEMPDIR"] = "/tmp"

        # Clear potentially dangerous variables
        dangerous_vars = [
            "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
            "PYTHONPATH", "PERL5LIB", "RUBYLIB",
        ]
        for var in dangerous_vars:
            env.pop(var, None)

        return env

    def update_quota(self, path: Path, size_bytes: int) -> None:
        """
        Update quota usage for a path.

        Parameters
        ----------
        path : Path
            Path that was modified.
        size_bytes : int
            Size change in bytes (positive for addition, negative for removal).
        """
        for restriction in self.restriction_engine.get_all_restrictions():
            if restriction.matches(path) and restriction.max_total_size_mb:
                quota = self._quota_info.get(restriction._normalized_path)
                if quota:
                    quota.used_bytes += size_bytes
                    quota.last_updated = time.time()

                    if quota.is_exceeded():
                        raise QuotaExceededError(
                            message="Disk quota exceeded",
                            violation=JailViolation.QUOTA_EXCEEDED,
                            path=path,
                            details={
                                "used_mb": quota.used_bytes / (1024 * 1024),
                                "limit_mb": quota.limit_bytes / (1024 * 1024) if quota.limit_bytes else None,
                                "usage_percent": quota.usage_percent,
                            },
                        )

    def get_stats(self) -> Dict[str, Any]:
        """
        Get jail statistics and status.

        Returns
        -------
        Dict[str, Any]
            Statistics dictionary.
        """
        stats = {
            "root_path": str(self.root_path),
            "setup_complete": self._setup_complete,
            "use_chroot": self.use_chroot,
            "chroot_active": self._chroot_active,
            "use_overlay": self.use_overlay,
            "allow_network": self.allow_network,
            "allow_devices": self.allow_devices,
            "disk_quota_mb": self.disk_quota_mb,
            "max_files": self.max_files,
            "restriction_engine": self.restriction_engine.get_stats(),
            "active_mounts": self.mount_manager.get_mount_info(),
            "quotas": [q.to_dict() for q in self._quota_info.values()],
        }

        # Add disk usage
        try:
            usage = shutil.disk_usage(self.root_path)
            stats["disk_usage"] = {
                "total_mb": usage.total / (1024 * 1024),
                "used_mb": usage.used / (1024 * 1024),
                "free_mb": usage.free / (1024 * 1024),
            }
        except OSError:
            stats["disk_usage"] = None

        return stats

    def cleanup(self) -> None:
        """
        Cleanup filesystem jail resources.

        This method:
        1. Unmounts all filesystems
        2. Removes temporary files
        3. Clears caches
        4. Deletes workspace if temporary
        """
        logger.info(f"Cleaning up filesystem jail at {self.root_path}")

        try:
            # Unmount all mounts
            self.mount_manager.umount_all(force=True)

            # Clear caches
            self.restriction_engine.clear_cache()

            # Cleanup temporary workspace
            if self._temp_workspace:
                self._temp_workspace.cleanup()
                self._temp_workspace = None
            elif not self._temp_workspace and self.root_path.exists():
                # Only remove if we created it and cleanup is enabled
                if self.cleanup_on_exit and self._setup_complete:
                    try:
                        shutil.rmtree(self.root_path, ignore_errors=True)
                    except OSError as e:
                        logger.warning(f"Failed to remove jail directory: {e}")

            self._setup_complete = False
            self._chroot_active = False
            self._quota_info.clear()

            logger.info("Filesystem jail cleanup complete")

        except Exception as e:
            logger.error(f"Jail cleanup error: {e}")

    def __enter__(self) -> "FilesystemJail":
        """Context manager entry."""
        self.setup()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Context manager exit."""
        self.cleanup()

    def __repr__(self) -> str:
        status = "ready" if self._setup_complete else "not set up"
        return (f"<FilesystemJail root={self.root_path} "
                f"rules={len(self.restriction_engine)} "
                f"chroot={self.use_chroot} [{status}]>")


class TempWorkspace:
    """
    Temporary workspace manager for sandboxed execution.

    Creates and manages a temporary directory that is automatically
    cleaned up when the workspace is destroyed.

    Parameters
    ----------
    prefix : str
        Prefix for temporary directory name.
    base_dir : Optional[Path]
        Base directory for temp workspace.
    cleanup_on_exit : bool
        Automatically cleanup on context manager exit.
    mode : int
        Directory permissions mode.

    Attributes
    ----------
    path : Path
        Workspace directory path.
    cleanup_on_exit : bool
        Cleanup flag.
    _created : bool
        Whether directory was created.

    Examples
    --------
    >>> with TempWorkspace(prefix="compile_") as ws:
    ...     print(f"Workspace: {ws.path}")
    ...     # Files created here will be cleaned up automatically
    """

    def __init__(
        self,
        prefix: str = "sandbox_",
        base_dir: Optional[Path] = None,
        cleanup_on_exit: bool = True,
        mode: int = 0o700,
    ):
        self.prefix = prefix
        self.base_dir = base_dir
        self.cleanup_on_exit = cleanup_on_exit
        self.mode = mode
        self.path: Path = self._create()
        self._created = True

    def _create(self) -> Path:
        """
        Create temporary workspace directory.

        Returns
        -------
        Path
            Created directory path.
        """
        if self.base_dir:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            path = Path(tempfile.mkdtemp(prefix=self.prefix, dir=str(self.base_dir)))
        else:
            path = Path(tempfile.mkdtemp(prefix=self.prefix))

        path.chmod(self.mode)
        return path

    def cleanup(self) -> None:
        """
        Clean up workspace directory and all contents.
        """
        if self._created and self.path.exists():
            try:
                shutil.rmtree(self.path, ignore_errors=True)
                self._created = False
                logger.debug(f"Cleaned up workspace: {self.path}")
            except (OSError, PermissionError) as e:
                logger.warning(f"Failed to cleanup workspace {self.path}: {e}")

    def get_disk_usage(self) -> Dict[str, int]:
        """
        Get disk usage of workspace.

        Returns
        -------
        Dict[str, int]
            Dictionary with size_bytes and file_count.
        """
        total_size = 0
        file_count = 0

        if self.path.exists():
            for item in self.path.rglob("*"):
                if item.is_file():
                    try:
                        total_size += item.stat().st_size
                        file_count += 1
                    except OSError:
                        pass

        return {
            "size_bytes": total_size,
            "size_mb": total_size // (1024 * 1024),
            "file_count": file_count,
        }

    def __enter__(self) -> "TempWorkspace":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self.cleanup_on_exit:
            self.cleanup()

    def __repr__(self) -> str:
        return f"<TempWorkspace path={self.path}>"


# ============================================================================
# Utility Functions
# ============================================================================

def is_path_in_jail(path: Path, jail_root: Path) -> bool:
    """
    Check if a path is within a jail root.

    Parameters
    ----------
    path : Path
        Path to check.
    jail_root : Path
        Jail root directory.

    Returns
    -------
    bool
        True if path is within jail.
    """
    try:
        path.resolve().relative_to(jail_root.resolve())
        return True
    except ValueError:
        return False


def escape_jail_path(path: Path, jail_root: Path) -> Path:
    """
    Convert absolute path to jail-relative path.

    Parameters
    ----------
    path : Path
        Absolute path.
    jail_root : Path
        Jail root directory.

    Returns
    -------
    Path
        Path relative to jail root.

    Raises
    ------
    ValueError
        If path is outside jail.
    """
    try:
        return Path("/") / path.resolve().relative_to(jail_root.resolve())
    except ValueError:
        raise ValueError(f"Path {path} is outside jail root {jail_root}")


def create_minimal_jail(
    workspace: Path,
    allowed_commands: List[str],
) -> FilesystemJail:
    """
    Create a minimal jail for executing specific commands.

    Parameters
    ----------
    workspace : Path
        Workspace directory.
    allowed_commands : List[str]
        List of allowed command paths.

    Returns
    -------
    FilesystemJail
        Configured minimal jail.
    """
    jail = FilesystemJail(
        root_path=workspace,
        allowed_paths=[Path("/usr/bin"), Path("/bin"), Path("/lib"), Path("/lib64")],
        executable_paths=[Path(cmd) for cmd in allowed_commands],
        readonly_root=True,
        hide_system_paths=True,
        allow_network=False,
    )

    return jail


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums and constants
    "PathPermission",
    "MountType",
    "JailFeature",
    "JailViolation",
    
    # Exceptions
    "JailError",
    "PathNotAllowedError",
    "ReadOnlyViolationError",
    "QuotaExceededError",
    "SymlinkTraversalError",
    
    # Data structures
    "PathRestriction",
    "MountEntry",
    "QuotaInfo",
    
    # Engines
    "PathRestrictionEngine",
    "MountManager",
    
    # Main class
    "FilesystemJail",
    "TempWorkspace",
    
    # Utilities
    "is_path_in_jail",
    "escape_jail_path",
    "create_minimal_jail",
]