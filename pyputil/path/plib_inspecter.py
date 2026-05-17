#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Plib - Python Module & Package Toolkit
====================================================

A comprehensive, secure, and cross-platform library for inspecting,
manipulating, and analyzing Python modules and packages. Designed with
the same philosophy as ``pathlib.Path`` but for module objects.

Key Capabilities
----------------
*   **Inspection**: Retrieve metadata, size, structure, and location.
*   **Manipulation**: Move, copy, symlink, delete, and modify modules safely.
*   **Integrity**: Create snapshots, verify checksums, detect tampering.
*   **Analysis**: Scan dependencies, find vulnerabilities, search source code.
*   **Safety**: Atomic operations, permission hardening, path traversal prevention.
*   **Cross-Platform**: Full support for Windows, Linux, and macOS.

Quick Start
-----------
>>> from pyputil.path import Plib
>>> package = Plib('requests')
>>> print(package.information())
ModuleInformation(name='requests', is_package=True, size_mb=2.45, file_count=145)

>>> # Check integrity
>>> snapshot = package.create_snapshot()
>>> difference = package.diff_snapshot(snapshot)
>>> if difference.has_changes:
...     print(difference.report())

>>> # Find all imports
>>> dependencies = package.get_deps()
>>> print(f"Third-party: {dependencies.third_party}")

>>> # Scan for vulnerabilities
>>> vulnerabilities = package.scan_vulnerabilities()
>>> if not vulnerabilities.is_clean:
...     for issue in vulnerabilities.all_issues():
...         print(f"[{issue.severity}] {issue.file_path}:{issue.line_number}")
"""

__all__ = [
    # Main class
    'Plib',
    
    # Data classes
    'ModuleInformation',
    'SnapshotEntry',
    'SnapshotDifference',
    'FileEntry',
    'DependencyInformation',
    'VulnerabilityIssue',
    'VulnerabilityInformation',
    'SearchMatch',
    'SizeInformation',
    'BackupInformation',
    
    # Exceptions
    'PlibError',
    'ModuleNotFoundError',
    'SecurityViolationError',
    'IntegrityVerificationError',
    'VulnerabilityDetectedError',
    
    # Types
    'MoveMode',
    'HashAlgorithm',
    'VulnerabilitySeverity',
]

from dataclasses import dataclass, field
from typing import (
    Optional, List, Dict, Any, Tuple, Set, FrozenSet, 
    Iterator, Generator, Union, Literal, ClassVar
)
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache, wraps
from datetime import datetime, timezone
from collections import defaultdict, OrderedDict
import importlib
import importlib.util
import importlib.machinery
import inspect
import shutil
import os
import sys
import hashlib
import tempfile
import json
import re
import stat
import logging
import platform
import threading
from contextlib import contextmanager, suppress

# Configure structured logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


# ===========================================================
# Type Aliases
# ===========================================================

MoveMode = Literal["move", "copy", "symlink", "hardlink"]
"""
Valid modes for module relocation operations.

*   ``"move"``: Move the module to a new location.
*   ``"copy"``: Create a copy of the module at the destination.
*   ``"symlink"``: Create a symbolic link pointing to the module.
*   ``"hardlink"``: Create a hard link to the module file.
"""

HashAlgorithm = Literal["md5", "sha256", "sha1", "blake2b", "sha512", "sha3_256"]
"""
Supported cryptographic hash algorithms for integrity operations.

*   ``"md5"``: Fast, suitable for non-security integrity checks.
*   ``"sha256"``: Good balance of security and performance.
*   ``"sha1"``: Legacy, use only for compatibility.
*   ``"blake2b"``: Modern, high-performance algorithm.
*   ``"sha512"``: Maximum security, slower performance.
*   ``"sha3_256"``: Latest NIST standard.
"""

VulnerabilitySeverity = Literal["critical", "high", "medium", "low", "info"]
"""
Severity levels for detected vulnerabilities.

*   ``"critical"``: Immediate security risk, can lead to full system compromise.
*   ``"high"``: Significant risk, requires prompt attention.
*   ``"medium"``: Moderate risk, should be addressed.
*   ``"low"``: Minor issue, low risk of exploitation.
*   ``"info"``: Informational finding, no direct risk.
"""

# ===========================================================
# Security Constants
# ===========================================================

# Maximum file size for hashing (100 MB)
MAXIMUM_FILE_SIZE_BYTES: int = 100 * 1024 * 1024

# Maximum total module size (1 GB)
MAXIMUM_TOTAL_SIZE_BYTES: int = 1024 * 1024 * 1024

# Secure file permissions: rw-r--r-- (644)
SECURE_FILE_PERMISSIONS: int = (
    stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
)

# Secure directory permissions: rwxr-xr-x (755)
SECURE_DIRECTORY_PERMISSIONS: int = (
    stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
)

# Blocked system paths (Unix)
BLOCKED_SYSTEM_PATHS: FrozenSet[str] = frozenset({
    '/proc', '/sys', '/dev', '/etc', '/boot', '/root', '/run', '/var/run'
})

# Blocked Windows paths
BLOCKED_WINDOWS_PATHS: FrozenSet[str] = frozenset({
    'system32', 'syswow64', 'windows', 'winnt'
})

# Supported file extensions for analysis
PYTHON_FILE_EXTENSIONS: FrozenSet[str] = frozenset({
    '.py', '.pyw', '.pyx', '.pxd', '.pyi', '.pyd', '.so', '.dll', '.dylib'
})

# Vulnerability detection patterns
VULNERABILITY_PATTERNS: Dict[str, Tuple[re.Pattern, VulnerabilitySeverity, str]] = {
    'dangerous_eval': (
        re.compile(r'\beval\s*\(', re.IGNORECASE),
        'critical',
        'Use of eval() can lead to arbitrary code execution'
    ),
    'dangerous_exec': (
        re.compile(r'\bexec\s*\(', re.IGNORECASE),
        'critical',
        'Use of exec() can execute arbitrary Python code'
    ),
    'insecure_pickle': (
        re.compile(r'\bpickle\.(loads?|dump)\s*\(', re.IGNORECASE),
        'high',
        'Pickle deserialization can execute arbitrary code'
    ),
    'shell_command_injection': (
        re.compile(r'\bos\.(system|popen|spawn)\s*\(', re.IGNORECASE),
        'high',
        'Shell command execution may allow injection attacks'
    ),
    'hardcoded_credentials': (
        re.compile(
            r'(password|passwd|secret|api_key|token|auth)\s*=\s*[\'\"][^\'\"]{8,}[\'\"]',
            re.IGNORECASE
        ),
        'medium',
        'Hardcoded credentials found in source code'
    ),
    'insecure_yaml_loading': (
        re.compile(r'\byaml\.load\s*\(', re.IGNORECASE),
        'high',
        'Unsafe YAML loading can execute arbitrary code'
    ),
    'debug_mode_enabled': (
        re.compile(r'\bDEBUG\s*=\s*True\b'),
        'low',
        'Debug mode enabled, may leak sensitive information'
    ),
    'insecure_temporary_file': (
        re.compile(r'\btempfile\.mktemp\s*\(', re.IGNORECASE),
        'medium',
        'mktemp() is deprecated and insecure, use mkstemp() instead'
    ),
    'assert_usage_in_production': (
        re.compile(r'\bassert\s+', re.IGNORECASE),
        'info',
        'Assert statements may be disabled with -O flag'
    ),
    'http_without_ssl': (
        re.compile(r'https?://(?!localhost|127\.0\.0\.1)', re.IGNORECASE),
        'low',
        'HTTP URL found, consider using HTTPS'
    ),
}

# Standard library module names
STDLIB_MODULE_NAMES: FrozenSet[str] = frozenset()

# Helper function for lazy load `modules`
def init_stdlibs() -> List[str]:
	global STDLIB_MODULE_NAMES

	from ..modules import LIST_OF_STDLIBS
	STDLIB_MODULE_NAMES = LIST_OF_STDLIBS


# ===========================================================
# Data Classes 
# ===========================================================

@dataclass(frozen=True)
class ModuleInformation:
    """
    Comprehensive information about a Python module or package.
    
    This immutable data class contains all essential metadata about
    a module, including its location, type, size, and file count.
    
    Attributes
    ----------
    module_name : str
        The fully qualified module name (e.g., ``'requests'``, ``'numpy.linalg'``).
    absolute_path : Optional[Path]
        Resolved filesystem path to the module or package root.
        ``None`` if the module is built-in or not found.
    is_package : bool
        ``True`` if this is a package (directory with ``__init__.py``),
        ``False`` if it is a single-file module.
    is_builtin : bool
        ``True`` if the module is compiled into the Python interpreter.
    size_bytes : int
        Total size of all module files in bytes.
    size_mb : float
        Total size in megabytes (rounded to 2 decimal places).
    file_count : int
        Number of Python files in the module.
    python_version : str
        Python version used to inspect the module.
    platform : str
        Operating system name (e.g., ``'Linux'``, ``'Windows'``, ``'Darwin'``).
    inspection_timestamp : datetime
        UTC timestamp when this information was generated.
    
    Examples
    --------
    >>> package = Plib('requests')
    >>> info = package.information()
    >>> print(info)
    ModuleInformation(name='requests', is_package=True, size_mb=2.45)
    >>> print(f"Files: {info.file_count}, Size: {info.size_mb} MB")
    Files: 145, Size: 2.45 MB
    
    >>> # For a single-file module
    >>> module = Plib('mymodule')
    >>> info = module.information()
    >>> print(info.is_package)
    False
    """
    module_name: str
    absolute_path: Optional[Path]
    is_package: bool
    is_builtin: bool
    size_bytes: int
    size_mb: float
    file_count: int
    python_version: str = field(default_factory=lambda: sys.version.split()[0])
    platform: str = field(default_factory=platform.system)
    inspection_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        """Return a concise representation of the module information."""
        if self.is_builtin:
            return f"ModuleInformation(name={self.module_name!r}, is_builtin=True)"
        return (
            f"ModuleInformation(name={self.module_name!r}, "
            f"is_package={self.is_package}, size_mb={self.size_mb:.2f})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the module information to a JSON-serializable dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with all attributes, Path converted to string.
        
        Examples
        --------
        >>> info = package.information()
        >>> data = info.to_dict()
        >>> print(json.dumps(data, indent=2))
        {
          "module_name": "requests",
          "absolute_path": "/usr/lib/python3/site-packages/requests",
          ...
        }
        """
        return {
            'module_name': self.module_name,
            'absolute_path': str(self.absolute_path) if self.absolute_path else None,
            'is_package': self.is_package,
            'is_builtin': self.is_builtin,
            'size_bytes': self.size_bytes,
            'size_mb': self.size_mb,
            'file_count': self.file_count,
            'python_version': self.python_version,
            'platform': self.platform,
            'inspection_timestamp': self.inspection_timestamp.isoformat(),
        }


@dataclass(frozen=True)
class SnapshotEntry:
    """
    A single file entry within a module snapshot.
    
    Represents one file's integrity data at a specific point in time.
    Snapshots are used for change detection and integrity verification.
    
    Attributes
    ----------
    relative_path : str
        File path relative to the module root directory.
        Uses forward slashes on all platforms for consistency.
    hash_digest : str
        Hexadecimal hash digest of the file contents.
        Empty string if the file could not be hashed (too large, permissions).
    file_size_bytes : int
        File size in bytes at the time of snapshot.
    modification_timestamp : float
        File modification time as Unix timestamp (seconds since epoch).
    
    Examples
    --------
    >>> entry = SnapshotEntry(
    ...     relative_path='api.py',
    ...     hash_digest='abc123def456',
    ...     file_size_bytes=12345,
    ...     modification_timestamp=1700000000.0
    ... )
    >>> print(entry)
    SnapshotEntry(path='api.py', hash='abc123de...', size=12345)
    """
    relative_path: str
    hash_digest: str
    file_size_bytes: int
    modification_timestamp: float

    def __repr__(self) -> str:
        """Return a concise representation of the snapshot entry."""
        short_hash = self.hash_digest[:8] + '...' if len(self.hash_digest) > 8 else self.hash_digest
        return (
            f"SnapshotEntry(path={self.relative_path!r}, "
            f"hash={short_hash!r}, size={self.file_size_bytes})"
        )


@dataclass(frozen=True)
class SnapshotDifference:
    """
    Result of comparing two module snapshots.
    
    Contains detailed information about what changed between
    two points in time for a module's files.
    
    Attributes
    ----------
    has_changes : bool
        ``True`` if any differences were detected (additions, removals, or modifications).
    added_files : List[str]
        Relative paths of files present in the new snapshot but absent in the old.
    removed_files : List[str]
        Relative paths of files present in the old snapshot but absent in the new.
    modified_files : Dict[str, Tuple[str, str]]
        Mapping of relative paths to tuples of ``(old_hash, new_hash)``.
        Only includes files whose content hash changed.
    unchanged_count : int
        Number of files with identical hashes in both snapshots.
    total_file_count : int
        Total number of files in the current (new) snapshot.
    hash_algorithm : HashAlgorithm
        The hash algorithm used for the comparison.
    comparison_timestamp : datetime
        UTC timestamp when the comparison was performed.
    
    Examples
    --------
    >>> old_snapshot = package.create_snapshot()
    >>> # ... time passes, files change ...
    >>> difference = package.diff_snapshot(old_snapshot)
    >>> if difference.has_changes:
    ...     print(f"Changed files: {list(difference.modified_files.keys())}")
    ...     print(difference.generate_report())
    Diff Report: +2 added, -1 removed, ~3 modified, 100 unchanged
    """
    has_changes: bool
    added_files: List[str]
    removed_files: List[str]
    modified_files: Dict[str, Tuple[str, str]]
    unchanged_count: int
    total_file_count: int
    hash_algorithm: HashAlgorithm
    comparison_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def generate_report(self) -> str:
        """
        Generate a human-readable summary of the snapshot differences.
        
        Returns
        -------
        str
            Multi-line string summarizing all changes detected.
        
        Examples
        --------
        >>> difference = package.diff_snapshot(old_snap)
        >>> print(difference.generate_report())
        Snapshot Difference Report (sha256)
        ===================================
        Added Files (2):
          + config.json
          + utils/helpers.py
        
        Removed Files (1):
          - deprecated.py
        
        Modified Files (3):
          ~ api.py (abc12345 -> def67890)
          ~ core.py (111aaaaa -> 222bbbbb)
          ~ __init__.py (xyz99999 -> aaa00000)
        
        Unchanged: 145 files
        Total: 148 files
        """
        lines = [
            f"Snapshot Difference Report ({self.hash_algorithm})",
            "=" * 40,
        ]
        
        if self.added_files:
            lines.append(f"\nAdded Files ({len(self.added_files)}):")
            for file_path in self.added_files:
                lines.append(f"  + {file_path}")
        
        if self.removed_files:
            lines.append(f"\nRemoved Files ({len(self.removed_files)}):")
            for file_path in self.removed_files:
                lines.append(f"  - {file_path}")
        
        if self.modified_files:
            lines.append(f"\nModified Files ({len(self.modified_files)}):")
            for file_path, (old_hash, new_hash) in self.modified_files.items():
                lines.append(f"  ~ {file_path} ({old_hash[:8]} -> {new_hash[:8]})")
        
        lines.append(f"\nUnchanged: {self.unchanged_count} files")
        lines.append(f"Total: {self.total_file_count} files")
        
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the difference result to a JSON-serializable dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the difference result.
        
        Examples
        --------
        >>> difference = package.diff_snapshot(snap)
        >>> with open('changes.json', 'w') as output_file:
        ...     json.dump(difference.to_dict(), output_file, indent=2)
        """
        return {
            'has_changes': self.has_changes,
            'added_files': self.added_files,
            'removed_files': self.removed_files,
            'modified_files': {
                path: {'old_hash': old, 'new_hash': new}
                for path, (old, new) in self.modified_files.items()
            },
            'unchanged_count': self.unchanged_count,
            'total_file_count': self.total_file_count,
            'hash_algorithm': self.hash_algorithm,
            'comparison_timestamp': self.comparison_timestamp.isoformat(),
        }


@dataclass(frozen=True)
class FileEntry:
    """
    Detailed information about a single file within a module.
    
    Attributes
    ----------
    abs_path : str
        Resolved absolute path to the file.
    relative_path : str
        Path relative to the module root directory.
    size : int
        Size of the file in bytes.
    line_count : int
        Number of lines in the file (for text files only).
    is_executable : bool
        ``True`` if the file has execute permissions.
    is_binary : bool
        ``True`` if the file was detected as binary content.
    suffix : str
        File extension including the dot (e.g., ``'.py'``).
    last_modified : datetime
        UTC timestamp of the file's last modification time.
    
    Examples
    --------
    >>> files = package.list_files()
    >>> for file_entry in files:
    ...     print(f"{file_entry.relative_path}: {file_entry.line_count} lines")
    utils.py: 245 lines
    api.py: 1023 lines
    """
    abs_path: str
    relative_path: str
    size: int
    line_count: int
    is_executable: bool
    is_binary: bool
    suffix: str
    last_modified: datetime


@dataclass(frozen=True)
class DependencyInformation:
    """
    Complete analysis of a module's import dependencies.
    
    Categorizes all imports found in the module's source code
    into standard library, third-party, and local imports.
    
    Attributes
    ----------
    module_name : str
        The name of the analyzed module.
    all_imports : List[str]
        All import names discovered in the source code.
    standard_library : List[str]
        Imports from Python's standard library.
    third_party : List[str]
        Imports from installed third-party packages.
    local_imports : List[str]
        Relative or local project imports.
    unresolved : List[str]
        Imports that could not be resolved to any known location.
    import_count : int
        Total number of unique imports found.
    
    Examples
    --------
    >>> dependencies = package.get_deps()
    >>> print(f"Third-party: {dependencies.third_party}")
    ['urllib3', 'certifi', 'charset_normalizer', 'idna']
    >>> print(f"Unresolved: {dependencies.unresolved}")
    []
    """
    module_name: str
    all_imports: List[str]
    standard_library: List[str]
    third_party: List[str]
    local_imports: List[str]
    unresolved: List[str]
    import_count: int

    @property
    def external_dependencies(self) -> List[str]:
        """
        Get all non-standard-library, non-local dependencies.
        
        Returns
        -------
        List[str]
            Combined list of third-party and unresolved imports.
        """
        return sorted(set(self.third_party + self.unresolved))


@dataclass(frozen=True)
class VulnerabilityIssue:
    """
    A single security vulnerability finding.
    
    Attributes
    ----------
    file_path : str
        Relative path to the file containing the issue.
    line_number : int
        Line number where the issue was detected (1-based).
    pattern_name : str
        Name of the vulnerability pattern that matched.
    severity : VulnerabilitySeverity
        Severity level of the finding.
    description : str
        Human-readable description of the vulnerability.
    code_snippet : str
        The matching line of code (truncated to 120 characters).
    
    Examples
    --------
    >>> issue = VulnerabilityIssue(
    ...     file_path='utils.py',
    ...     line_number=42,
    ...     pattern_name='dangerous_eval',
    ...     severity='critical',
    ...     description='Use of eval() can lead to arbitrary code execution',
    ...     code_snippet='result = eval(user_input)'
    ... )
    >>> print(f"[{issue.severity}] {issue.file_path}:{issue.line_number}")
    [critical] utils.py:42
    """
    file_path: str
    line_number: int
    pattern_name: str
    severity: VulnerabilitySeverity
    description: str
    code_snippet: str


@dataclass(frozen=True)
class VulnerabilityInformation:
    """
    Complete results of a vulnerability scan on a module.
    
    Attributes
    ----------
    critical_issues : List[VulnerabilityIssue]
        Issues with critical severity.
    high_issues : List[VulnerabilityIssue]
        Issues with high severity.
    medium_issues : List[VulnerabilityIssue]
        Issues with medium severity.
    low_issues : List[VulnerabilityIssue]
        Issues with low severity.
    informational_issues : List[VulnerabilityIssue]
        Informational findings.
    total_issues : int
        Total number of issues found across all severities.
    is_clean : bool
        ``True`` if no issues were found.
    scan_timestamp : datetime
        UTC timestamp when the scan was performed.
    files_scanned : int
        Number of files that were analyzed.
    
    Methods
    -------
    all_issues() -> List[VulnerabilityIssue]
        Return a flat list of all issues found.
    
    generate_report() -> str
        Generate a human-readable summary report.
    
    Examples
    --------
    >>> vulnerabilities = package.scan_vulnerabilities()
    >>> if not vulnerabilities.is_clean:
    ...     print(vulnerabilities.generate_report())
    ...     for issue in vulnerabilities.critical_issues:
    ...         print(f"CRITICAL: {issue.file_path}:{issue.line_number}")
    """
    critical_issues: List[VulnerabilityIssue]
    high_issues: List[VulnerabilityIssue]
    medium_issues: List[VulnerabilityIssue]
    low_issues: List[VulnerabilityIssue]
    informational_issues: List[VulnerabilityIssue]
    total_issues: int
    is_clean: bool
    scan_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    files_scanned: int = 0

    def all_issues(self) -> List[VulnerabilityIssue]:
        """
        Return all detected issues as a single flat list.
        
        Returns
        -------
        List[VulnerabilityIssue]
            Combined list of all issues across all severity levels.
        
        Examples
        --------
        >>> all_issues = vulnerabilities.all_issues()
        >>> for issue in all_issues:
        ...     print(f"{issue.severity}: {issue.file_path}")
        """
        return (
            self.critical_issues + 
            self.high_issues + 
            self.medium_issues + 
            self.low_issues +
            self.informational_issues
        )

    def generate_report(self) -> str:
        """
        Generate a human-readable vulnerability scan report.
        
        Returns
        -------
        str
            Formatted multi-line report of all findings.
        
        Examples
        --------
        >>> print(vulnerabilities.generate_report())
        Vulnerability Scan Report
        ========================
        CRITICAL: 2 issues
        HIGH: 1 issue
        MEDIUM: 0 issues
        LOW: 3 issues
        INFO: 1 issue
        Total: 7 issues in 145 files
        Clean: No
        """
        lines = [
            "Vulnerability Scan Report",
            "=" * 24,
            f"CRITICAL: {len(self.critical_issues)} issues",
            f"HIGH: {len(self.high_issues)} issues",
            f"MEDIUM: {len(self.medium_issues)} issues",
            f"LOW: {len(self.low_issues)} issues",
            f"INFO: {len(self.informational_issues)} issues",
            f"Total: {self.total_issues} issues in {self.files_scanned} files",
            f"Clean: {'Yes' if self.is_clean else 'No'}",
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class SearchMatch:
    """
    A single search result match.
    
    Attributes
    ----------
    file_path : str
        Relative path to the file containing the match.
    line_number : int
        Line number where the match was found (1-based).
    line_content : str
        The full content of the matching line.
    column_position : int
        Starting column of the match (0-based).
    match_text : str
        The exact text that matched the search query.
    
    Examples
    --------
    >>> matches = package.search_code('def handle_request')
    >>> for match in matches:
    ...     print(f"{match.file_path}:{match.line_number}: {match.line_content.strip()}")
    api.py:42: def handle_request(url, params=None):
    core.py:128: def handle_request_error(error):
    """
    file_path: str
    line_number: int
    line_content: str
    column_position: int
    match_text: str


@dataclass(frozen=True)
class SizeInformation:
    """
    Detailed size breakdown of a module.
    
    Attributes
    ----------
    total_bytes : int
        Total size of all files in bytes.
    total_megabytes : float
        Total size in megabytes.
    total_kilobytes : float
        Total size in kilobytes.
    file_count : int
        Number of files counted.
    largest_file : Tuple[str, int]
        Tuple of (relative_path, size_in_bytes) of the largest file.
    by_extension : Dict[str, int]
        Size breakdown by file extension in bytes.
    
    Examples
    --------
    >>> size_info = package.calculate_size()
    >>> print(f"Total: {size_info.total_megabytes:.2f} MB")
    >>> print(f"Largest: {size_info.largest_file[0]} ({size_info.largest_file[1]} bytes)")
    """
    total_bytes: int
    total_megabytes: float
    total_kilobytes: float
    file_count: int
    largest_file: Tuple[str, int]
    by_extension: Dict[str, int]


@dataclass(frozen=True)
class BackupInformation:
    """
    Information about a created backup.
    
    Attributes
    ----------
    original_path : Path
        The original file path that was backed up.
    backup_path : Path
        The path where the backup was created.
    backup_size_bytes : int
        Size of the backup file in bytes.
    creation_timestamp : datetime
        When the backup was created (UTC).
    
    Examples
    --------
    >>> backup = package.create_backup('config.py')
    >>> print(f"Backup created at: {backup.backup_path}")
    """
    original_path: Path
    backup_path: Path
    backup_size_bytes: int
    creation_timestamp: datetime


# ===========================================================
# Exceptions
# ===========================================================

class PlibError(Exception):
    """
    Base exception for all Plib-related errors.
    
    All custom exceptions in this module inherit from this class,
    allowing easy catching of any Plib-specific error.
    
    Examples
    --------
    >>> try:
    ...     package.move_to('/restricted/path')
    ... except PlibError as error:
    ...     print(f"Operation failed: {error}")
    """
    pass


class ModuleNotFoundError(PlibError):
    """
    Raised when a module cannot be found in the Python environment.
    
    This is distinct from the built-in ``ModuleNotFoundError`` to
    allow specific handling of Plib-related module resolution failures.
    
    Examples
    --------
    >>> try:
    ...     module = Plib('nonexistent_module_xyz')
    ... except ModuleNotFoundError as error:
    ...     print(f"Cannot find: {error.module_name}")
    """
    def __init__(self, module_name: str):
        self.module_name = module_name
        super().__init__(f"No module named '{module_name}' found in Python path")


class SecurityViolationError(PlibError):
    """
    Raised when a security violation is detected.
    
    This includes path traversal attempts, access to blocked system
    directories, and other suspicious activities.
    
    Examples
    --------
    >>> try:
    ...     package.add_file('../../../etc/passwd', 'content')
    ... except SecurityViolationError as error:
    ...     print(f"Blocked: {error}")
    """
    pass


class IntegrityVerificationError(PlibError):
    """
    Raised when module integrity verification fails.
    
    Indicates that files have been modified, corrupted, or tampered
    with since the last snapshot was taken.
    
    Examples
    --------
    >>> try:
    ...     package.verify_integrity(expected_snapshot)
    ... except IntegrityVerificationError as error:
    ...     print(f"Integrity failure: {error.modified_files}")
    """
    def __init__(self, message: str, modified_files: Optional[List[str]] = None):
        self.modified_files = modified_files or []
        super().__init__(message)


class VulnerabilityDetectedError(PlibError):
    """
    Raised when critical vulnerabilities are found during scanning.
    
    Can be used to halt CI/CD pipelines or trigger alerts when
    security issues are detected.
    
    Examples
    --------
    >>> try:
    ...     vulnerabilities = package.scan_vulnerabilities()
    ...     if vulnerabilities.critical_issues:
    ...         raise VulnerabilityDetectedError(
    ...             f"Critical issues: {len(vulnerabilities.critical_issues)}"
    ...         )
    ... except VulnerabilityDetectedError:
    ...     print("Deployment blocked due to security issues")
    """
    pass


# ===========================================================
# Internal Utilities
# ===========================================================

def _validate_path_security(path: Path, root_path: Optional[Path] = None) -> None:
    """
    Validate that a path is safe to operate on.
    
    Checks for path traversal attempts, blocked system directories,
    and ensures the path is within allowed boundaries.
    
    Parameters
    ----------
    path : Path
        The path to validate.
    root_path : Optional[Path]
        If provided, ensure the path is within this root directory.
    
    Raises
    ------
    SecurityViolationError
        If the path is deemed unsafe.
    """
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise SecurityViolationError(f"Cannot resolve path '{path}': {error}")
    
    # Check against blocked system paths
    path_string = str(resolved).lower()
    
    if platform.system() == "Windows":
        for blocked in BLOCKED_WINDOWS_PATHS:
            if f"\\{blocked}\\" in f"\\{path_string}\\" or path_string.startswith(f"{blocked}\\"):
                raise SecurityViolationError(
                    f"Access to Windows system directory blocked: {path}"
                )
    else:
        for blocked in BLOCKED_SYSTEM_PATHS:
            if path_string.startswith(blocked):
                raise SecurityViolationError(
                    f"Access to system directory blocked: {path}"
                )
    
    # Check containment within root
    if root_path is not None:
        try:
            resolved.relative_to(root_path.resolve())
        except ValueError:
            raise SecurityViolationError(
                f"Path '{path}' escapes the module root '{root_path}'"
            )


def _compute_file_hash(file_path: Path, algorithm: HashAlgorithm) -> str:
    """
    Compute the cryptographic hash of a single file.
    
    Parameters
    ----------
    file_path : Path
        Path to the file to hash.
    algorithm : HashAlgorithm
        Hash algorithm to use.
    
    Returns
    -------
    str
        Hexadecimal hash digest, or empty string if hashing fails.
    """
    try:
        file_size = file_path.stat().st_size
    except OSError:
        return ""
    
    # Skip files that are too large
    if file_size > MAXIMUM_FILE_SIZE_BYTES:
        logger.warning(f"File exceeds maximum size for hashing: {file_path}")
        return ""
    
    # Handle empty files
    if file_size == 0:
        return hashlib.new(algorithm, b"").hexdigest()
    
    hash_object = hashlib.new(algorithm)
    try:
        with open(file_path, "rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(65536), b""):
                hash_object.update(chunk)
        return hash_object.hexdigest()
    except (OSError, PermissionError) as error:
        logger.warning(f"Cannot read file for hashing '{file_path}': {error}")
        return ""
    

def _compute_hashes_parallel(
    file_paths: List[Path], 
    algorithm: HashAlgorithm,
    worker_threads: int = 8
) -> Dict[Path, str]:
    """
    Compute hashes for multiple files in parallel using threading.
    
    Parameters
    ----------
    file_paths : List[Path]
        List of file paths to hash.
    algorithm : HashAlgorithm
        Hash algorithm to use.
    worker_threads : int
        Maximum number of worker threads. Default is 8.
    
    Returns
    -------
    Dict[Path, str]
        Mapping of file paths to their hash digests.
    """
    worker_threads = min(worker_threads, max(1, (os.cpu_count() or 4)))
    results: Dict[Path, str] = {}
    
    with ThreadPoolExecutor(max_workers=worker_threads) as executor:
        future_to_path = {
            executor.submit(_compute_file_hash, path, algorithm): path 
            for path in file_paths
        }
        
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                results[path] = future.result()
            except Exception as error:
                logger.warning(f"Hash computation failed for '{path}': {error}")
                results[path] = ""
    
    return results


def _find_module_path(module_name: str) -> Optional[Path]:
    """
    Locate the filesystem path of a Python module.
    
    Parameters
    ----------
    module_name : str
        Fully qualified module name.
    
    Returns
    -------
    Optional[Path]
        Path to the module or None if not found.
    """
    try:
        # Try to find the module specification
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            return None
        
        # Built-in modules have no origin
        if spec.origin is None:
            return None
        
        origin_path = Path(spec.origin).resolve()
        
        # Check if it's a package (has __init__.py)
        if origin_path.name == '__init__.py':
            return origin_path.parent
        
        return origin_path
    
    except (ImportError, ValueError, AttributeError):
        return None


def _is_python_file(file_path: Path) -> bool:
    """Check if a file has a Python-related extension."""
    return file_path.suffix.lower() in PYTHON_FILE_EXTENSIONS


def _is_text_file(file_path: Path) -> bool:
    """
    Detect if a file is a text file by reading a sample.
    
    Parameters
    ----------
    file_path : Path
        Path to the file.
    
    Returns
    -------
    bool
        True if the file appears to be text, False if binary.
    """
    try:
        with open(file_path, 'rb') as file_handle:
            sample = file_handle.read(1024)
        # Check for null bytes (binary indicator)
        return b'\x00' not in sample
    except (OSError, PermissionError):
        return False


def _count_file_lines(file_path: Path) -> int:
    """
    Count the number of lines in a text file.
    
    Parameters
    ----------
    file_path : Path
        Path to the text file.
    
    Returns
    -------
    int
        Number of lines, or 0 if the file cannot be read.
    """
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file_handle:
            return sum(1 for _ in file_handle)
    except (OSError, PermissionError):
        return 0


# ===========================================================
# Main Plib Class
# ===========================================================

class Plib:
    """
    A safe interface for processing and manipulating Python modules and packages.
    
    This class provides the equivalent of ``pathlib.Path`` but for Python
    modules. It allows inspection, modification, integrity verification,
    and security analysis of installed modules and packages.
    
    Parameters
    ----------
    module_name : str
        Name of the module or package (e.g., ``'requests'``, ``'numpy'``).
    allow_missing : bool, optional
        If ``True``, do not raise ``ModuleNotFoundError`` when the module
        is not found. The object will have ``exists = False``. Default is ``False``.
    search_paths : Optional[List[Union[str, Path]]], optional
        Additional paths to search for the module. Default is ``None``.
    
    Attributes
    ----------
    name : str
        The module name.
    path : Optional[Path]
        Resolved filesystem path to the module, or ``None`` if not found.
    exists : bool
        ``True`` if the module was found on the filesystem.
    
    Raises
    ------
    ModuleNotFoundError
        If the module cannot be found and ``allow_missing`` is ``False``.
    ValueError
        If ``module_name`` is empty or not a string.
    
    Examples
    --------
    >>> # Basic usage with an installed package
    >>> requests_package = Plib('requests')
    >>> print(requests_package.exists)
    True
    >>> print(requests_package.path)
    /usr/lib/python3.12/site-packages/requests
    
    >>> # Information about the module
    >>> info = requests_package.information()
    >>> print(f"{info.module_name} is {'a package' if info.is_package else 'a module'}")
    requests is a package
    
    >>> # Handle missing modules gracefully
    >>> missing_module = Plib('nonexistent_module', allow_missing=True)
    >>> print(missing_module.exists)
    False
    
    >>> # With custom search path
    >>> custom_module = Plib('my_local_module', search_paths=['./src', './lib'])
    
    See Also
    --------
    pathlib.Path : Standard library path manipulation.
    importlib : Python's import machinery.
    """
    
    def __init__(
        self,
        module_name: str,
        allow_missing: bool = False,
        search_paths: Optional[List[Union[str, Path]]] = None,
    ) -> None:
        """
        Initialize a Plib object for a module or package.
        
        Parameters
        ----------
        module_name : str
            Name of the module or package.
        allow_missing : bool, optional
            If True, don't raise error when module is not found.
        search_paths : Optional[List[Union[str, Path]]], optional
            Additional paths to search.
        
        Raises
        ------
        ValueError
            If module_name is empty or invalid.
        ModuleNotFoundError
            If module is not found and allow_missing is False.
        """
        if not module_name or not isinstance(module_name, str):
            raise ValueError(
                f"Module name must be a non-empty string, got: {module_name!r}"
            )
        
        # Clean module name (strip whitespace, normalize dots)
        self.name: str = module_name.strip().replace('/', '.').replace('\\', '.')
        self._path: Optional[Path] = None
        self._cache: Dict[str, Any] = {}
        
        # Add custom search paths to sys.path temporarily
        if search_paths:
            for search_path in search_paths:
                path_obj = Path(search_path).resolve()
                if path_obj.exists() and str(path_obj) not in sys.path:
                    sys.path.insert(0, str(path_obj))
        
        # Find the module
        self._path = _find_module_path(self.name)
        
        # Validate the path
        if self._path is not None:
            _validate_path_security(self._path)
        
        if self._path is None and not allow_missing:
            raise ModuleNotFoundError(self.name)
    
    # ── Properties ──────────────────────────────────────
    
    @property
    def path(self) -> Optional[Path]:
        """
        Get the resolved filesystem path to the module.
        
        Returns
        -------
        Optional[Path]
            The module's path, or None if not found.
        """
        return self._path
    
    @property
    def exists(self) -> bool:
        """
        Check if the module exists on the filesystem.
        
        Returns
        -------
        bool
            True if the module was found, False otherwise.
        """
        return self._path is not None and self._path.exists()
    
    # ── Magic Methods ───────────────────────────────────
    
    def __repr__(self) -> str:
        """Return a developer-friendly representation."""
        if self.exists:
            return f"Plib({self.name!r}, path={str(self._path)!r})"
        return f"Plib({self.name!r}, exists=False)"
    
    def __str__(self) -> str:
        """Return the module path as a string, or the name if not found."""
        return str(self._path) if self._path else self.name
    
    def __eq__(self, other: object) -> bool:
        """Compare two Plib objects by their resolved paths."""
        if not isinstance(other, Plib):
            return NotImplemented
        if self._path is None or other._path is None:
            return self.name == other.name
        return self._path.resolve() == other._path.resolve()
    
    def __hash__(self) -> int:
        """Hash based on the resolved path."""
        if self._path is None:
            return hash(self.name)
        return hash(self._path.resolve())
    
    # ── Information Methods ─────────────────────────────
    
    def information(self) -> ModuleInformation:
        """
        Retrieve comprehensive information about the module.
        
        Returns
        -------
        ModuleInformation
            Dataclass containing all module metadata.
        
        Examples
        --------
        >>> package = Plib('json')
        >>> info = package.information()
        >>> print(f"Package: {info.is_package}, Size: {info.size_mb}MB")
        >>> print(info.to_dict())
        """
        if not self.exists or self._path is None:
            return ModuleInformation(
                module_name=self.name,
                absolute_path=None,
                is_package=False,
                is_builtin=False,
                size_bytes=0,
                size_mb=0.0,
                file_count=0,
            )
        
        # Determine if package
        is_package = self._path.is_dir() and (self._path / '__init__.py').exists()
        
        # Calculate size
        size_data = self.calculate_size()
        
        # Count files
        python_files = [
            f for f in self._path.rglob('*') 
            if f.is_file() and _is_python_file(f)
        ]
        
        # Check if built-in
        is_builtin = False
        try:
            spec = importlib.util.find_spec(self.name)
            if spec is not None:
                is_builtin = spec.origin is None and spec.loader is not None
        except (ImportError, ValueError):
            pass
        
        return ModuleInformation(
            module_name=self.name,
            absolute_path=self._path,
            is_package=is_package,
            is_builtin=is_builtin,
            size_bytes=size_data.total_bytes,
            size_mb=round(size_data.total_bytes / (1024 * 1024), 2),
            file_count=len(python_files),
        )
    
    def is_package(self) -> bool:
        """
        Check if the module is a package (has __init__.py).
        
        Returns
        -------
        bool
            True if the module is a package.
        
        Examples
        --------
        >>> Plib('requests').is_package()
        True
        >>> Plib('os').is_package()
        False
        """
        if not self.exists or self._path is None:
            return False
        return self._path.is_dir() and (self._path / '__init__.py').exists()
    
    def is_single_file(self) -> bool:
        """
        Check if the module is a single-file module (not a package).
        
        Returns
        -------
        bool
            True if it is a single .py file.
        
        Examples
        --------
        >>> Plib('os').is_single_file()
        True
        """
        if not self.exists or self._path is None:
            return False
        return self._path.is_file()
    
    # ── File Listing Methods ────────────────────────────
    
    def list_files(
        self,
        pattern: str = "*.py",
        recursive: bool = True,
        maximum_depth: Optional[int] = None,
        exclude_patterns: Optional[List[str]] = None,
    ) -> List[FileEntry]:
        """
        List all files in the module matching criteria.
        
        Parameters
        ----------
        pattern : str, optional
            Glob pattern to match files. Default is ``"*.py"``.
        recursive : bool, optional
            Search directories recursively. Default is ``True``.
        maximum_depth : Optional[int], optional
            Maximum directory depth for search. ``None`` means unlimited.
        exclude_patterns : Optional[List[str]], optional
            Glob patterns to exclude from results.
        
        Returns
        -------
        List[FileEntry]
            List of file entries with metadata.
        
        Examples
        --------
        >>> package = Plib('requests')
        >>> all_python_files = package.list_files()
        >>> print(f"Found {len(all_python_files)} Python files")
        
        >>> test_files = package.list_files('test_*.py', maximum_depth=2)
        >>> for file_entry in test_files:
        ...     print(file_entry.relative_path)
        tests/test_requests.py
        tests/test_utils.py
        """
        if not self.exists or self._path is None:
            return []
        
        files: List[Path] = []
        exclude_patterns = exclude_patterns or []
        
        if recursive:
            for file_path in self._path.rglob(pattern):
                # Check depth limit
                if maximum_depth is not None:
                    depth = len(file_path.relative_to(self._path).parents)
                    if depth > maximum_depth:
                        continue
                
                # Check exclusions
                if any(file_path.match(excl) for excl in exclude_patterns):
                    continue
                
                if file_path.is_file():
                    files.append(file_path)
        else:
            for file_path in self._path.glob(pattern):
                if file_path.is_file():
                    if not any(file_path.match(excl) for excl in exclude_patterns):
                        files.append(file_path)
        
        # Build FileEntry objects
        entries: List[FileEntry] = []
        for file_path in sorted(files):
            try:
                stat_info = file_path.stat()
                is_binary = not _is_text_file(file_path)
                line_count = 0 if is_binary else _count_file_lines(file_path)
                is_executable = bool(stat_info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
                
                entries.append(FileEntry(
                    abs_path=str(file_path),
                    relative_path=str(file_path.relative_to(self._path)),
                    size=stat_info.st_size,
                    line_count=line_count,
                    is_executable=is_executable,
                    is_binary=is_binary,
                    suffix=file_path.suffix,
                    last_modified=datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc).isoformat(),
                ))
            except OSError as error:
                logger.warning(f"Cannot stat file '{file_path}': {error}")
        
        return entries
    
    # ── Size Calculation ────────────────────────────────
    
    def calculate_size(
        self,
        exclude_patterns: Optional[List[str]] = None,
    ) -> SizeInformation:
        """
        Calculate the total size of the module with detailed breakdown.
        
        Parameters
        ----------
        exclude_patterns : Optional[List[str]], optional
            Glob patterns to exclude from size calculation.
        
        Returns
        -------
        SizeInformation
            Detailed size breakdown.
        
        Examples
        --------
        >>> package = Plib('numpy')
        >>> size_info = package.calculate_size()
        >>> print(f"Total: {size_info.total_megabytes:.2f} MB")
        >>> print(f"Largest: {size_info.largest_file}")
        >>> print(f"By extension: {size_info.by_extension}")
        """
        if not self.exists or self._path is None:
            return SizeInformation(
                total_bytes=0, total_megabytes=0.0, total_kilobytes=0.0,
                file_count=0, largest_file=("", 0), by_extension={},
            )
        
        exclude_patterns = exclude_patterns or ['__pycache__/**', '*.pyc', '*.pyo']
        total_bytes = 0
        largest: Tuple[str, int] = ("", 0)
        by_extension: Dict[str, int] = defaultdict(int)
        file_count = 0
        
        for file_path in self._path.rglob('*'):
            if not file_path.is_file():
                continue
            
            # Check exclusion
            if any(file_path.match(pattern) for pattern in exclude_patterns):
                continue
            
            try:
                file_size = file_path.stat().st_size
                total_bytes += file_size
                file_count += 1
                
                # Track largest
                if file_size > largest[1]:
                    largest = (str(file_path.relative_to(self._path)), file_size)
                
                # Track by extension
                by_extension[file_path.suffix or '(no extension)'] += file_size
                
            except OSError:
                continue
        
        return SizeInformation(
            total_bytes=total_bytes,
            total_megabytes=round(total_bytes / (1024 * 1024), 2),
            total_kilobytes=round(total_bytes / 1024, 2),
            file_count=file_count,
            largest_file=largest,
            by_extension=dict(by_extension),
        )
    
    # ── Snapshot & Integrity Methods ────────────────────
    
    def create_snapshot(
        self,
        algorithm: HashAlgorithm = "sha256",
        maximum_files: Optional[int] = None,
        exclude_patterns: Optional[List[str]] = None,
    ) -> Dict[str, SnapshotEntry]:
        """
        Create an integrity snapshot of the module's files.
        
        Parameters
        ----------
        algorithm : HashAlgorithm, optional
            Hash algorithm to use. Default is ``"sha256"``.
        maximum_files : Optional[int], optional
            Limit the number of files to hash.
        exclude_patterns : Optional[List[str]], optional
            Glob patterns to exclude.
        
        Returns
        -------
        Dict[str, SnapshotEntry]
            Mapping of relative paths to snapshot entries.
        
        Examples
        --------
        >>> package = Plib('requests')
        >>> snapshot = package.create_snapshot()
        >>> print(f"Hashed {len(snapshot)} files")
        >>> with open('integrity.json', 'w') as f:
        ...     json.dump({
        ...         k: {'hash': v.hash_digest, 'size': v.file_size_bytes}
        ...         for k, v in snapshot.items()
        ...     }, f, indent=2)
        """
        if not self.exists or self._path is None:
            return {}
        
        exclude_patterns = exclude_patterns or []
        files_to_hash: List[Path] = []
        
        for file_path in self._path.rglob('*'):
            if not file_path.is_file():
                continue
            if not _is_python_file(file_path):
                continue
            if any(file_path.match(p) for p in exclude_patterns):
                continue
            files_to_hash.append(file_path)
        
        if maximum_files:
            files_to_hash = files_to_hash[:maximum_files]
        
        if not files_to_hash:
            return {}
        
        # Compute hashes in parallel
        hash_results = _compute_hashes_parallel(files_to_hash, algorithm)
        
        # Build snapshot entries
        snapshot: Dict[str, SnapshotEntry] = {}
        for file_path, hash_digest in hash_results.items():
            try:
                stat_info = file_path.stat()
                rel_path = str(file_path.relative_to(self._path))
                snapshot[rel_path] = SnapshotEntry(
                    relative_path=rel_path,
                    hash_digest=hash_digest,
                    file_size_bytes=stat_info.st_size,
                    modification_timestamp=stat_info.st_mtime,
                )
            except OSError:
                continue
        
        return snapshot
    
    def diff_snapshot(
        self,
        old_snapshot: Dict[str, SnapshotEntry],
        algorithm: HashAlgorithm = "sha256",
    ) -> SnapshotDifference:
        """
        Compare the current module state against an old snapshot.
        
        Parameters
        ----------
        old_snapshot : Dict[str, SnapshotEntry]
            Previous snapshot to compare against.
        algorithm : HashAlgorithm, optional
            Hash algorithm for current snapshot. Default is ``"sha256"``.
        
        Returns
        -------
        SnapshotDifference
            Detailed comparison results.
        
        Examples
        --------
        >>> snapshot = package.create_snapshot()
        >>> # ... make changes ...
        >>> diff = package.diff_snapshot(snapshot)
        >>> if diff.has_changes:
        ...     print(diff.generate_report())
        >>>     for path, (old, new) in diff.modified_files.items():
        ...         print(f"Modified: {path}")
        """
        current_snapshot = self.create_snapshot(algorithm)
        
        old_paths = set(old_snapshot.keys())
        new_paths = set(current_snapshot.keys())
        
        added = sorted(list(new_paths - old_paths))
        removed = sorted(list(old_paths - new_paths))
        modified: Dict[str, Tuple[str, str]] = {}
        unchanged = 0
        
        for path in old_paths & new_paths:
            old_hash = old_snapshot[path].hash_digest
            new_hash = current_snapshot[path].hash_digest
            if old_hash != new_hash:
                modified[path] = (old_hash, new_hash)
            else:
                unchanged += 1
        
        has_changes = bool(added or removed or modified)
        
        return SnapshotDifference(
            has_changes=has_changes,
            added_files=added,
            removed_files=removed,
            modified_files=modified,
            unchanged_count=unchanged,
            total_file_count=len(current_snapshot),
            hash_algorithm=algorithm,
        )
    
    def verify_integrity(
        self,
        expected_snapshot: Dict[str, SnapshotEntry],
        algorithm: HashAlgorithm = "sha256",
        raise_on_failure: bool = False,
    ) -> SnapshotDifference:
        """
        Verify module integrity against an expected snapshot.
        
        Parameters
        ----------
        expected_snapshot : Dict[str, SnapshotEntry]
            The expected snapshot for comparison.
        algorithm : HashAlgorithm, optional
            Hash algorithm. Default is ``"sha256"``.
        raise_on_failure : bool, optional
            If True, raise IntegrityVerificationError on differences.
        
        Returns
        -------
        SnapshotDifference
            Detailed difference results.
        
        Raises
        ------
        IntegrityVerificationError
            If raise_on_failure is True and changes are detected.
        
        Examples
        --------
        >>> snapshot = package.create_snapshot()
        >>> # ... later ...
        >>> try:
        ...     diff = package.verify_integrity(snapshot, raise_on_failure=True)
        ...     print("Integrity verified successfully")
        ... except IntegrityVerificationError as e:
        ...     print(f"INTEGRITY FAILURE: {e.modified_files}")
        """
        difference = self.diff_snapshot(expected_snapshot, algorithm)
        
        if raise_on_failure and difference.has_changes:
            modified_list = list(difference.modified_files.keys())
            raise IntegrityVerificationError(
                f"Module '{self.name}' integrity verification failed. "
                f"Added: {len(difference.added_files)}, "
                f"Removed: {len(difference.removed_files)}, "
                f"Modified: {len(difference.modified_files)}",
                modified_files=modified_list,
            )
        
        return difference
    
    # ── File Modification Methods ───────────────────────
    
    def add_file(
        self,
        relative_filename: str,
        content: str,
        allow_overwrite: bool = False,
        create_backup: bool = True,
    ) -> Optional[BackupInformation]:
        """
        Add a new file with content to the module root.
        
        Parameters
        ----------
        relative_filename : str
            File path relative to the module root.
        content : str
            Content to write to the file.
        allow_overwrite : bool, optional
            If True, overwrite existing files. Default is False.
        create_backup : bool, optional
            If True, create a backup before overwriting. Default is True.
        
        Returns
        -------
        Optional[BackupInformation]
            Backup information if backup was created, None otherwise.
        
        Raises
        ------
        PlibError
            If module doesn't exist.
        FileExistsError
            If file exists and allow_overwrite is False.
        SecurityViolationError
            If path escapes module root.
        
        Examples
        --------
        >>> package = Plib('requests')
        >>> package.add_file('custom_config.py', '# Custom config\\nDEBUG = True')
        >>> backup = package.add_file('existing.py', 'new content', 
        ...                           allow_overwrite=True, create_backup=True)
        >>> print(f"Backup: {backup.backup_path}")
        """
        if not self.exists or self._path is None:
            raise PlibError(f"Module '{self.name}' does not exist")
        
        target_path = (self._path / relative_filename).resolve()
        
        # Security check
        _validate_path_security(target_path, root_path=self._path)
        
        # Check existence
        if target_path.exists() and not allow_overwrite:
            raise FileExistsError(
                f"File '{relative_filename}' already exists. "
                f"Use allow_overwrite=True to overwrite."
            )
        
        backup_info = None
        
        # Create backup if requested
        if create_backup and target_path.exists():
            backup_info = self.create_backup(relative_filename)
        
        # Write file atomically
        self._write_file_atomically(target_path, content)
        
        logger.info(f"Added file: {relative_filename}")
        return backup_info
    
    def add_directory(
        self,
        relative_dirname: str,
        allow_existing: bool = True,
    ) -> Path:
        """
        Create a new directory within the module.
        
        Parameters
        ----------
        relative_dirname : str
            Directory path relative to module root.
        allow_existing : bool, optional
            If True, don't raise error if directory exists. Default is True.
        
        Returns
        -------
        Path
            The created directory path.
        
        Raises
        ------
        PlibError
            If module doesn't exist.
        FileExistsError
            If directory exists and allow_existing is False.
        SecurityViolationError
            If path escapes module root.
        
        Examples
        --------
        >>> package = Plib('requests')
        >>> new_dir = package.add_directory('utils/custom')
        >>> print(new_dir)
        /usr/lib/python3/site-packages/requests/utils/custom
        """
        if not self.exists or self._path is None:
            raise PlibError(f"Module '{self.name}' does not exist")
        
        target_path = (self._path / relative_dirname).resolve()
        _validate_path_security(target_path, root_path=self._path)
        
        if target_path.exists() and not allow_existing:
            raise FileExistsError(
                f"Directory '{relative_dirname}' already exists"
            )
        
        target_path.mkdir(parents=True, exist_ok=allow_existing)
        os.chmod(target_path, SECURE_DIRECTORY_PERMISSIONS)
        
        logger.info(f"Created directory: {relative_dirname}")
        return target_path
    
    def remove_path(
        self,
        relative_path: str,
        safe_delete: bool = True,
    ) -> None:
        """
        Remove a file or directory from the module.
        
        Parameters
        ----------
        relative_path : str
            Relative path to remove.
        safe_delete : bool, optional
            If True, move to system trash instead of permanent deletion.
            Default is True.
        
        Raises
        ------
        PlibError
            If module doesn't exist.
        FileNotFoundError
            If path doesn't exist.
        SecurityViolationError
            If path escapes module root.
        
        Examples
        --------
        >>> package = Plib('requests')
        >>> package.remove_path('deprecated_module.py', safe_delete=True)
        >>> package.remove_path('old_tests/', safe_delete=True)
        """
        if not self.exists or self._path is None:
            raise PlibError(f"Module '{self.name}' does not exist")
        
        target_path = (self._path / relative_path).resolve()
        _validate_path_security(target_path, root_path=self._path)
        
        if not target_path.exists():
            raise FileNotFoundError(f"Path not found: {relative_path}")
        
        if safe_delete:
            try:
                import send2trash
                send2trash.send2trash(str(target_path))
                logger.info(f"Moved to trash: {relative_path}")
            except ImportError:
                raise PlibError(
                    "send2trash package is required for safe deletion. "
                    "Install it with: pip install send2trash"
                )
        else:
            if target_path.is_file():
                target_path.unlink()
            else:
                shutil.rmtree(str(target_path))
            logger.warning(f"Permanently deleted: {relative_path}")
    
    def remove_module(
        self,
        force: bool = False,
    ) -> None:
        """
        Remove the entire module from the filesystem.
        
        Parameters
        ----------
        force : bool, optional
            If True, force removal even for standard library modules.
            Default is False.
        
        Raises
        ------
        RuntimeError
            If trying to remove a standard library module without force=True.
        PlibError
            If module doesn't exist.
        
        Examples
        --------
        >>> package = Plib('some_installed_package')
        >>> package.remove_module()
        >>> # Force remove even stdlib (dangerous!)
        >>> # package.remove_module(force=True)
        """
        if not self.exists or self._path is None:
            raise PlibError(f"Module '{self.name}' does not exist")
        
        # Check if standard library
        if self.name in STDLIB_MODULE_NAMES and not force:
            raise RuntimeError(
                f"Cannot remove standard library module '{self.name}'. "
                f"Use force=True to override (DANGEROUS)."
            )
        
        target_path = self._path.resolve()
        _validate_path_security(target_path)
        
        if target_path.is_dir():
            shutil.rmtree(str(target_path), ignore_errors=True)
        else:
            target_path.unlink(missing_ok=True)
        
        # Try to remove cached metadata
        with suppress(Exception):
            meta_path = target_path.parent / '__pycache__'
            if meta_path.exists():
                meta_files = list(meta_path.glob(f"{target_path.stem}.*"))
                for mf in meta_files:
                    mf.unlink(missing_ok=True)
        
        self._path = None
        logger.info(f"Removed module: {self.name}")
    
    # ── Relocation Methods ──────────────────────────────
    
    def move_to(
        self,
        destination: Union[str, Path],
        mode: MoveMode = "move",
    ) -> Optional[Path]:
        """
        Move, copy, symlink, or hardlink the module to a new location.
        
        Parameters
        ----------
        destination : Union[str, Path]
            Destination directory path.
        mode : MoveMode, optional
            Operation mode: 'move', 'copy', 'symlink', or 'hardlink'.
            Default is 'move'.
        
        Returns
        -------
        Optional[Path]
            New path of the module, or None if operation failed.
        
        Raises
        ------
        PlibError
            If module doesn't exist.
        SecurityViolationError
            If destination is unsafe.
        ValueError
            If mode is invalid.
        
        Examples
        --------
        >>> package = Plib('requests')
        >>> new_path = package.move_to('/home/user/custom_packages/', mode='copy')
        >>> print(f"Copied to: {new_path}")
        
        >>> symlinked = package.move_to('/usr/local/lib/python/', mode='symlink')
        """
        if not self.exists or self._path is None:
            raise PlibError(f"Module '{self.name}' does not exist")
        
        destination_path = Path(destination).resolve()
        _validate_path_security(destination_path)
        
        # Create destination directory
        destination_path.mkdir(parents=True, exist_ok=True)
        
        source_path = self._path.resolve()
        target_path = destination_path / source_path.name
        
        try:
            if mode == "move":
                shutil.move(str(source_path), str(target_path))
                self._path = target_path
                logger.info(f"Moved '{self.name}' to: {target_path}")
                
            elif mode == "copy":
                if source_path.is_file():
                    shutil.copy2(str(source_path), str(target_path))
                else:
                    shutil.copytree(
                        str(source_path), str(target_path),
                        dirs_exist_ok=True
                    )
                logger.info(f"Copied '{self.name}' to: {target_path}")
                
            elif mode == "symlink":
                if target_path.exists():
                    target_path.unlink()
                os.symlink(str(source_path), str(target_path))
                logger.info(f"Symlinked '{self.name}' to: {target_path}")
                
            elif mode == "hardlink":
                if target_path.exists():
                    target_path.unlink()
                os.link(str(source_path), str(target_path))
                logger.info(f"Hardlinked '{self.name}' to: {target_path}")
                
            else:
                raise ValueError(
                    f"Invalid mode '{mode}'. Choose from: move, copy, symlink, hardlink"
                )
            
            return target_path
            
        except (OSError, shutil.Error) as error:
            logger.error(f"Failed to {mode} '{self.name}' to '{destination}': {error}")
            raise PlibError(f"Relocation failed: {error}")
    
    # ── Backup Methods ──────────────────────────────────
    
    def create_backup(self, relative_path: str) -> BackupInformation:
        """
        Create a timestamped backup of a specific file in the module.
        
        Parameters
        ----------
        relative_path : str
            Relative path to the file to backup.
        
        Returns
        -------
        BackupInformation
            Details about the created backup.
        
        Raises
        ------
        PlibError
            If module doesn't exist.
        FileNotFoundError
            If the source file doesn't exist.
        
        Examples
        --------
        >>> package = Plib('requests')
        >>> backup = package.create_backup('api.py')
        >>> print(f"Backup: {backup.backup_path}")
        """
        if not self.exists or self._path is None:
            raise PlibError(f"Module '{self.name}' does not exist")
        
        source_path = (self._path / relative_path).resolve()
        _validate_path_security(source_path, root_path=self._path)
        
        if not source_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        
        # Create timestamped backup name
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = source_path.with_suffix(f"{source_path.suffix}.{timestamp}.backup")
        
        shutil.copy2(str(source_path), str(backup_path))
        backup_size = backup_path.stat().st_size
        
        logger.info(f"Created backup: {backup_path}")
        
        return BackupInformation(
            original_path=source_path,
            backup_path=backup_path,
            backup_size_bytes=backup_size,
            creation_timestamp=datetime.now(timezone.utc).isoformat(),
        )
    
    def list_backups(self) -> List[BackupInformation]:
        """
        List all backup files for this module.
        
        Returns
        -------
        List[BackupInformation]
            List of all backup information.
        
        Examples
        --------
        >>> package = Plib('requests')
        >>> backups = package.list_backups()
        >>> for backup in backups:
        ...     print(f"{backup.original_path.name}: {backup.creation_timestamp}")
        """
        if not self.exists or self._path is None:
            return []
        
        backups: List[BackupInformation] = []
        backup_pattern = "*.backup"
        
        for backup_path in self._path.rglob(backup_pattern):
            # Parse original path
            stem = backup_path.stem  # e.g., "api.py.20240101_120000"
            original_name = stem.rsplit('.', 2)[0] + backup_path.suffix.replace('.backup', '')
            # This is simplified; real parsing would need the full pattern
            
            backups.append(BackupInformation(
                original_path=self._path / original_name,
                backup_path=backup_path,
                backup_size_bytes=backup_path.stat().st_size,
                creation_timestamp=datetime.fromtimestamp(
                    backup_path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            ))
        
        return backups
    
    # ── Search Methods ──────────────────────────────────
    
    def search_code(
        self,
        query: str,
        case_sensitive: bool = True,
        maximum_results: Optional[int] = None,
        file_pattern: str = "*.py",
    ) -> List[SearchMatch]:
        """
        Search for text within the module's source code.
        
        Parameters
        ----------
        query : str
            Text to search for (plain text, not regex).
        case_sensitive : bool, optional
            Perform case-sensitive search. Default is True.
        maximum_results : Optional[int], optional
            Maximum number of results to return.
        file_pattern : str, optional
            Glob pattern for files to search. Default is "*.py".
        
        Returns
        -------
        List[SearchMatch]
            List of matches found.
        
        Examples
        --------
        >>> package = Plib('requests')
        >>> matches = package.search_code('def get')
        >>> for match in matches[:5]:
        ...     print(f"{match.file_path}:{match.line_number}: {match.line_content.strip()}")
        
        >>> # Case-insensitive search
        >>> matches = package.search_code('timeout', case_sensitive=False)
        """
        if not self.exists or self._path is None:
            return []
        
        search_query = query if case_sensitive else query.lower()
        matches: List[SearchMatch] = []
        
        for file_path in self._path.rglob(file_pattern):
            if not file_path.is_file():
                continue
            if not _is_text_file(file_path):
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line_number, line in enumerate(f, start=1):
                        search_line = line if case_sensitive else line.lower()
                        position = search_line.find(search_query)
                        
                        if position != -1:
                            matches.append(SearchMatch(
                                file_path=str(file_path.relative_to(self._path)),
                                line_number=line_number,
                                line_content=line.rstrip('\n'),
                                column_position=position,
                                match_text=line[position:position + len(query)],
                            ))
                            
                            if maximum_results and len(matches) >= maximum_results:
                                return matches
            except (OSError, UnicodeDecodeError):
                continue
        
        return matches
    
    # ── Dependency Analysis ─────────────────────────────
    
    def get_deps(self) -> DependencyInformation:
        """
        Analyze and categorize the module's import dependencies.
        
        Returns
        -------
        DependencyInformation
            Categorized dependency information.
        
        Examples
        --------
        >>> package = Plib('requests')
        >>> deps = package.get_deps()
        >>> print(f"Standard library: {deps.standard_library}")
        >>> print(f"Third-party: {deps.third_party}")
        >>> print(f"External: {deps.external_dependencies}")
        """
        if not self.exists or self._path is None:
            return DependencyInformation(
                module_name=self.name,
                all_imports=[], standard_library=[], third_party=[],
                local_imports=[], unresolved=[], import_count=0,
            )
        
        # Regex to find imports
        import_pattern = re.compile(
            r'^\s*(?:from\s+(\S+)\s+import|import\s+(\S+))',
            re.MULTILINE
        )
        
        all_imports: Set[str] = set()
        
        for file_path in self._path.rglob('*.py'):
            if not file_path.is_file():
                continue
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                for match in import_pattern.finditer(content):
                    module_name = match.group(1) or match.group(2)
                    # Get top-level package name
                    top_level = module_name.split('.')[0]
                    all_imports.add(top_level)
            except (OSError, UnicodeDecodeError):
                continue
        
        # Categorize imports
        stdlib: List[str] = []
        third_party: List[str] = []
        local_imports: List[str] = []
        unresolved: List[str] = []
        
        for imp in sorted(all_imports):
            if imp in STDLIB_MODULE_NAMES:
                stdlib.append(imp)
            elif imp.startswith('.'):
                local_imports.append(imp)
            else:
                # Check if it can be found
                try:
                    spec = importlib.util.find_spec(imp)
                    if spec is None or spec.origin is None:
                        unresolved.append(imp)
                    else:
                        origin = Path(spec.origin)
                        if str(self._path) in str(origin):
                            local_imports.append(imp)
                        else:
                            third_party.append(imp)
                except (ImportError, ValueError):
                    unresolved.append(imp)
        
        return DependencyInformation(
            module_name=self.name,
            all_imports=sorted(all_imports),
            standard_library=sorted(stdlib),
            third_party=sorted(third_party),
            local_imports=sorted(local_imports),
            unresolved=sorted(unresolved),
            import_count=len(all_imports),
        )
    
    # ── Vulnerability Scanning ──────────────────────────
    
    def scan_vulnerabilities(
        self,
        severity_filter: Optional[List[VulnerabilitySeverity]] = None,
        maximum_issues_per_file: int = 20,
    ) -> VulnerabilityInformation:
        """
        Scan the module's source code for security vulnerabilities.
        
        Parameters
        ----------
        severity_filter : Optional[List[VulnerabilitySeverity]], optional
            Only report issues of these severities. None means all.
        maximum_issues_per_file : int, optional
            Maximum issues to report per file. Default is 20.
        
        Returns
        -------
        VulnerabilityInformation
            Complete vulnerability scan results.
        
        Examples
        --------
        >>> package = Plib('some_package')
        >>> vulns = package.scan_vulnerabilities()
        >>> if vulns.critical_issues:
        ...     print(f"CRITICAL: {len(vulns.critical_issues)} issues found!")
        >>> print(vulns.generate_report())
        
        >>> # Only check for critical and high issues
        >>> vulns = package.scan_vulnerabilities(
        ...     severity_filter=['critical', 'high']
        ... )
        """
        if not self.exists or self._path is None:
            return VulnerabilityInformation(
                critical_issues=[], high_issues=[], medium_issues=[],
                low_issues=[], informational_issues=[],
                total_issues=0, is_clean=True, files_scanned=0,
            )
        
        severity_filter_set = set(severity_filter) if severity_filter else None
        
        critical: List[VulnerabilityIssue] = []
        high: List[VulnerabilityIssue] = []
        medium: List[VulnerabilityIssue] = []
        low: List[VulnerabilityIssue] = []
        info: List[VulnerabilityIssue] = []
        files_scanned = 0
        
        for file_path in self._path.rglob('*.py'):
            if not file_path.is_file():
                continue
            files_scanned += 1
            file_issues = 0
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                
                for line_number, line in enumerate(lines, start=1):
                    if file_issues >= maximum_issues_per_file:
                        break
                    
                    for pattern_name, (pattern, severity, description) in VULNERABILITY_PATTERNS.items():
                        # Apply severity filter
                        if severity_filter_set and severity not in severity_filter_set:
                            continue
                        
                        match = pattern.search(line)
                        if match:
                            issue = VulnerabilityIssue(
                                file_path=str(file_path.relative_to(self._path)),
                                line_number=line_number,
                                pattern_name=pattern_name,
                                severity=severity,
                                description=description,
                                code_snippet=line.strip()[:120],
                            )
                            
                            if severity == 'critical':
                                critical.append(issue)
                            elif severity == 'high':
                                high.append(issue)
                            elif severity == 'medium':
                                medium.append(issue)
                            elif severity == 'low':
                                low.append(issue)
                            else:
                                info.append(issue)
                            
                            file_issues += 1
                            break  # One issue per line
                            
            except (OSError, UnicodeDecodeError):
                continue
        
        total = len(critical) + len(high) + len(medium) + len(low) + len(info)
        
        return VulnerabilityInformation(
            critical_issues=critical,
            high_issues=high,
            medium_issues=medium,
            low_issues=low,
            informational_issues=info,
            total_issues=total,
            is_clean=(total == 0),
            files_scanned=files_scanned,
        )
    
    # ── Internal Utilities ──────────────────────────────
    
    def _write_file_atomically(self, target_path: Path, content: str) -> None:
        """
        Write content to a file atomically using a temporary file.
        
        Parameters
        ----------
        target_path : Path
            The final file path.
        content : str
            Content to write.
        
        Raises
        ------
        OSError
            If the write operation fails.
        """
        # Create parent directories if needed
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write to temporary file first
        temp_file = None
        try:
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                dir=str(target_path.parent),
                prefix='.tmp_',
                suffix='.plib',
                delete=False,
                encoding='utf-8',
            )
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_file.close()
            
            # Set secure permissions
            os.chmod(temp_file.name, SECURE_FILE_PERMISSIONS)
            
            # Atomic rename
            shutil.move(temp_file.name, str(target_path))
            
        except Exception:
            # Clean up temp file
            if temp_file is not None:
                with suppress(OSError):
                    Path(temp_file.name).unlink()
            raise
        
        finally:
            if temp_file is not None:
                with suppress(OSError):
                    Path(temp_file.name).unlink(missing_ok=True)
    
    def _copy_file_safely(
        self,
        source: Path,
        destination: Path,
        preserve_metadata: bool = True,
    ) -> None:
        """
        Copy a file or directory safely with validation.
        
        Parameters
        ----------
        source : Path
            Source file or directory.
        destination : Path
            Destination directory.
        preserve_metadata : bool, optional
            Preserve file metadata. Default is True.
        
        Raises
        ------
        SecurityViolationError
            If paths are unsafe.
        FileNotFoundError
            If source doesn't exist.
        """
        _validate_path_security(source)
        _validate_path_security(destination)
        
        if not source.exists():
            raise FileNotFoundError(f"Source not found: {source}")
        
        destination.mkdir(parents=True, exist_ok=True)
        
        copy_function = shutil.copy2 if preserve_metadata else shutil.copy
        
        try:
            if source.is_file():
                copy_function(str(source), str(destination / source.name))
            else:
                shutil.copytree(
                    str(source),
                    str(destination / source.name),
                    copy_function=copy_function,
                    dirs_exist_ok=True,
                )
        except (shutil.Error, OSError) as error:
            logger.error(f"Copy failed: {source} -> {destination}: {error}")
            raise


# ===========================================================
# Module-Level Utility Functions
# ===========================================================

def find_all_modules(root_package: str) -> List[str]:
    """
    Find all submodules within a package.
    
    Parameters
    ----------
    root_package : str
        Name of the root package.
    
    Returns
    -------
    List[str]
        List of fully qualified module names.
    
    Examples
    --------
    >>> submodules = find_all_modules('requests')
    >>> print(f"Found {len(submodules)} submodules in requests")
    """
    try:
        package = Plib(root_package)
        if not package.exists:
            return []
        
        modules: List[str] = [root_package]
        for file_entry in package.list_files('*.py'):
            rel = file_entry.relative_path
            if rel == '__init__.py':
                continue
            mod_path = rel.replace('/', '.').replace('.py', '') 
            modules.append(f"{root_package}.{mod_path}")
        
        return sorted(set(modules))
    except Exception:
        return []


def compare_modules(
    module_a: Union[str, Plib],
    module_b: Union[str, Plib],
) -> SnapshotDifference:
    """
    Compare two modules for differences.
    
    Parameters
    ----------
    module_a : Union[str, Plib]
        First module name or Plib object.
    module_b : Union[str, Plib]
        Second module name or Plib object.
    
    Returns
    -------
    SnapshotDifference
        Differences between the two modules.
    
    Examples
    --------
    >>> diff = compare_modules('requests', 'urllib3')
    >>> print(diff.generate_report())
    """
    if isinstance(module_a, str):
        module_a = Plib(module_a)
    if isinstance(module_b, str):
        module_b = Plib(module_b)
    
    snapshot_a = module_a.create_snapshot()
    snapshot_b = module_b.create_snapshot()
    
    # Compare paths (different modules will have all different paths)
    all_paths = set(snapshot_a.keys()) | set(snapshot_b.keys())
    modified: Dict[str, Tuple[str, str]] = {}
    
    for path in all_paths:
        hash_a = snapshot_a[path].hash_digest if path in snapshot_a else "N/A"
        hash_b = snapshot_b[path].hash_digest if path in snapshot_b else "N/A"
        if hash_a != hash_b:
            modified[path] = (hash_a, hash_b)
    
    added = sorted(set(snapshot_b.keys()) - set(snapshot_a.keys()))
    removed = sorted(set(snapshot_a.keys()) - set(snapshot_b.keys()))
    
    return SnapshotDifference(
        has_changes=bool(added or removed or modified),
        added_files=added,
        removed_files=removed,
        modified_files=modified,
        unchanged_count=sum(1 for p in set(snapshot_a) & set(snapshot_b) if p not in modified),
        total_file_count=len(snapshot_b),
        hash_algorithm="sha256",
    )
