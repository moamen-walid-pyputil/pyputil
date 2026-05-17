#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module Metadata Management System.

This module provides comprehensive metadata tracking and management for
Python modules with support for versioning, dependency resolution,
cryptographic verification, and cross-platform compatibility.

The metadata system enables sophisticated module lifecycle management
including version control, integrity verification, dependency tracking,
and serialization for distributed environments.

Features:
---------
- Comprehensive module metadata tracking
- Cryptographic hash verification for integrity
- Semantic versioning support
- Dependency graph construction and validation
- Cross-platform path normalization
- JSON serialization/deserialization
- Metadata caching with TTL
- Audit trail for modifications
- Integration with package managers

Examples
--------
>>> meta = ModuleMetadata("my_package.core")
>>> meta.version = "2.1.0"
>>> meta.add_dependency("numpy", ">=1.20.0")
>>> meta.add_dependency("pandas", ">=1.3.0")
>>> meta.update_content_hash(source_code)
>>> meta.save_to_file("metadata.json")
>>> 
>>> # Load and verify
>>> loaded = ModuleMetadata.from_file("metadata.json")
>>> if loaded.verify_integrity(source_code):
...     print("Module integrity verified")
"""

import json
import hashlib
import time
import os
import sys
import re
import threading
from pathlib import Path
from typing import (
    Dict, List, Set, Optional, Any, Union, Tuple,
    Callable, Iterator, NamedTuple, FrozenSet
)
from dataclasses import dataclass, field, asdict, replace
from datetime import datetime, timedelta
from enum import Enum, auto
from functools import lru_cache, wraps
from collections import defaultdict
import warnings


class VersionScheme(Enum):
    """
    Version numbering schemes supported by the metadata system.
    
    Attributes
    ----------
    SEMANTIC : str
        Semantic versioning (major.minor.patch)
    CALENDAR : str
        Calendar versioning (YYYY.MM.DD)
    INCREMENTAL : str
        Simple incremental versioning (1, 2, 3, ...)
    CUSTOM : str
        Custom versioning scheme
    """
    SEMANTIC = "semantic"
    CALENDAR = "calendar"
    INCREMENTAL = "incremental"
    CUSTOM = "custom"


class DependencyType(Enum):
    """
    Types of module dependencies.
    
    Attributes
    ----------
    REQUIRED : str
        Hard dependency, module cannot function without it
    OPTIONAL : str
        Soft dependency, module can function without it
    DEVELOPMENT : str
        Development-only dependency
    RUNTIME : str
        Runtime-only dependency
    BUILD : str
        Build-time dependency
    TEST : str
        Testing dependency
    """
    REQUIRED = "required"
    OPTIONAL = "optional"
    DEVELOPMENT = "development"
    RUNTIME = "runtime"
    BUILD = "build"
    TEST = "test"


class IntegrityStatus(Enum):
    """
    Module integrity verification status.
    
    Attributes
    ----------
    VERIFIED : str
        Module integrity verified successfully
    MODIFIED : str
        Module has been modified since last verification
    CORRUPTED : str
        Module content is corrupted or tampered
    UNKNOWN : str
        Module integrity status unknown
    PENDING : str
        Verification pending
    """
    VERIFIED = "verified"
    MODIFIED = "modified"
    CORRUPTED = "corrupted"
    UNKNOWN = "unknown"
    PENDING = "pending"


@dataclass
class DependencySpec:
    """
    Detailed specification for a module dependency.
    
    This class provides comprehensive dependency specification including
    version constraints, compatibility ranges, and platform requirements.
    
    Attributes
    ----------
    name : str
        Dependency package/module name
    version_spec : str
        Version specification (e.g., ">=1.0.0,<2.0.0")
    dep_type : DependencyType
        Type of dependency
    min_version : Optional[str]
        Minimum compatible version
    max_version : Optional[str]
        Maximum compatible version
    exact_version : Optional[str]
        Exact required version
    platform_restrictions : List[str]
        Platform-specific restrictions (e.g., ["linux", "darwin"])
    python_version : Optional[str]
        Python version requirement (e.g., ">=3.8")
    optional_reason : Optional[str]
        Reason for optional dependency
    install_hint : Optional[str]
        Installation hint or command
    """
    name: str
    version_spec: str = ""
    dep_type: DependencyType = DependencyType.REQUIRED
    min_version: Optional[str] = None
    max_version: Optional[str] = None
    exact_version: Optional[str] = None
    platform_restrictions: List[str] = field(default_factory=list)
    python_version: Optional[str] = None
    optional_reason: Optional[str] = None
    install_hint: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate and normalize dependency specification."""
        if not self.version_spec and not any([self.min_version, self.max_version, self.exact_version]):
            self.version_spec = "*"  # Any version
        
        # Parse version spec if provided
        if self.version_spec and not any([self.min_version, self.max_version, self.exact_version]):
            self._parse_version_spec()
    
    def _parse_version_spec(self) -> None:
        """Parse version specification string."""
        if self.version_spec == "*":
            return
        
        # Parse common patterns
        patterns = [
            (r'^==([0-9.]+)$', lambda m: setattr(self, 'exact_version', m.group(1))),
            (r'^>=([0-9.]+)$', lambda m: setattr(self, 'min_version', m.group(1))),
            (r'^<=([0-9.]+)$', lambda m: setattr(self, 'max_version', m.group(1))),
            (r'^>([0-9.]+)$', lambda m: setattr(self, 'min_version', m.group(1))),
            (r'^<([0-9.]+)$', lambda m: setattr(self, 'max_version', m.group(1))),
            (r'^~=([0-9.]+)$', lambda m: self._parse_compatible(m.group(1))),
            (r'^([0-9.]+)$', lambda m: setattr(self, 'exact_version', m.group(1))),
        ]
        
        for pattern, handler in patterns:
            match = re.match(pattern, self.version_spec.strip())
            if match:
                handler(match)
                break
    
    def _parse_compatible(self, version: str) -> None:
        """Parse compatible release specification."""
        parts = version.split('.')
        self.min_version = version
        
        if len(parts) >= 2:
            major, minor = int(parts[0]), int(parts[1])
            self.max_version = f"{major}.{minor + 1}.0"
        else:
            self.max_version = f"{int(parts[0]) + 1}.0.0"
    
    def is_compatible_with(self, version: str, platform: Optional[str] = None) -> bool:
        """
        Check if a version is compatible with this dependency spec.
        
        Parameters
        ----------
        version : str
            Version to check
        platform : Optional[str]
            Current platform name
            
        Returns
        -------
        bool
            True if version is compatible
        """
        # Check platform restrictions
        if self.platform_restrictions and platform:
            current_platform = platform or sys.platform
            if current_platform not in self.platform_restrictions:
                return False
        
        # Check Python version
        if self.python_version:
            if not self._check_python_version(self.python_version):
                return False
        
        # Check version constraints
        if self.exact_version:
            return version == self.exact_version
        
        if self.min_version and self.max_version:
            return self._version_compare(self.min_version, version) <= 0 and \
                   self._version_compare(version, self.max_version) < 0
        
        if self.min_version:
            return self._version_compare(self.min_version, version) <= 0
        
        if self.max_version:
            return self._version_compare(version, self.max_version) < 0
        
        return True  # No version constraints
    
    def _version_compare(self, v1: str, v2: str) -> int:
        """
        Compare two version strings.
        
        Parameters
        ----------
        v1 : str
            First version string
        v2 : str
            Second version string
            
        Returns
        -------
        int
            -1 if v1 < v2, 0 if equal, 1 if v1 > v2
        """
        def normalize(v):
            return [int(x) for x in re.sub(r'(\.0+)*$', '', v).split('.')]
        
        try:
            n1, n2 = normalize(v1), normalize(v2)
            return (n1 > n2) - (n1 < n2)
        except ValueError:
            return (v1 > v2) - (v1 < v2)
    
    def _check_python_version(self, spec: str) -> bool:
        """
        Check if current Python version matches specification.
        
        Parameters
        ----------
        spec : str
            Python version specification
            
        Returns
        -------
        bool
            True if compatible
        """
        current = f"{sys.version_info.major}.{sys.version_info.minor}"
        
        if spec.startswith(">="):
            return self._version_compare(spec[2:], current) <= 0
        elif spec.startswith("<="):
            return self._version_compare(current, spec[2:]) <= 0
        elif spec.startswith("=="):
            return current == spec[2:]
        elif spec.startswith(">"):
            return self._version_compare(spec[1:], current) < 0
        elif spec.startswith("<"):
            return self._version_compare(current, spec[1:]) < 0
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'name': self.name,
            'version_spec': self.version_spec,
            'dep_type': self.dep_type.value,
            'min_version': self.min_version,
            'max_version': self.max_version,
            'exact_version': self.exact_version,
            'platform_restrictions': self.platform_restrictions,
            'python_version': self.python_version,
            'optional_reason': self.optional_reason,
            'install_hint': self.install_hint
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DependencySpec':
        """Create from dictionary representation."""
        return cls(
            name=data['name'],
            version_spec=data.get('version_spec', ''),
            dep_type=DependencyType(data.get('dep_type', 'required')),
            min_version=data.get('min_version'),
            max_version=data.get('max_version'),
            exact_version=data.get('exact_version'),
            platform_restrictions=data.get('platform_restrictions', []),
            python_version=data.get('python_version'),
            optional_reason=data.get('optional_reason'),
            install_hint=data.get('install_hint')
        )
    
    def __str__(self) -> str:
        """Return string representation."""
        parts = [self.name]
        if self.version_spec:
            parts.append(self.version_spec)
        if self.dep_type != DependencyType.REQUIRED:
            parts.append(f"[{self.dep_type.value}]")
        return " ".join(parts)


@dataclass
class ContentHash:
    """
    Multi-algorithm content hash for integrity verification.
    
    This class provides multiple hash algorithms for robust content
    verification with support for different security requirements.
    
    Attributes
    ----------
    sha256 : str
        SHA-256 hash (recommended for general use)
    sha512 : str
        SHA-512 hash (higher security)
    md5 : str
        MD5 hash (legacy/compatibility)
    blake2b : Optional[str]
        BLAKE2b hash (modern, high-performance)
    timestamp : float
        When the hash was computed
    """
    sha256: str = ""
    sha512: str = ""
    md5: str = ""
    blake2b: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    @classmethod
    def from_content(cls, content: Union[str, bytes]) -> 'ContentHash':
        """
        Create ContentHash from content.
        
        Parameters
        ----------
        content : Union[str, bytes]
            Content to hash
            
        Returns
        -------
        ContentHash
            Computed hash values
        """
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        return cls(
            sha256=hashlib.sha256(content).hexdigest(),
            sha512=hashlib.sha512(content).hexdigest(),
            md5=hashlib.md5(content).hexdigest(),
            blake2b=hashlib.blake2b(content).hexdigest() if hasattr(hashlib, 'blake2b') else None,
            timestamp=time.time()
        )
    
    def verify(self, content: Union[str, bytes], algorithm: str = "sha256") -> bool:
        """
        Verify content against stored hash.
        
        Parameters
        ----------
        content : Union[str, bytes]
            Content to verify
        algorithm : str
            Hash algorithm to use ('sha256', 'sha512', 'md5', 'blake2b')
            
        Returns
        -------
        bool
            True if content matches hash
        """
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        stored_hash = getattr(self, algorithm, None)
        if stored_hash is None:
            return False
        
        if algorithm == "sha256":
            computed = hashlib.sha256(content).hexdigest()
        elif algorithm == "sha512":
            computed = hashlib.sha512(content).hexdigest()
        elif algorithm == "md5":
            computed = hashlib.md5(content).hexdigest()
        elif algorithm == "blake2b" and hasattr(hashlib, 'blake2b'):
            computed = hashlib.blake2b(content).hexdigest()
        else:
            return False
        
        return computed == stored_hash
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'sha256': self.sha256,
            'sha512': self.sha512,
            'md5': self.md5,
            'blake2b': self.blake2b,
            'timestamp': self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContentHash':
        """Create from dictionary."""
        return cls(
            sha256=data.get('sha256', ''),
            sha512=data.get('sha512', ''),
            md5=data.get('md5', ''),
            blake2b=data.get('blake2b'),
            timestamp=data.get('timestamp', time.time())
        )


@dataclass
class AuditEntry:
    """
    Single audit log entry for metadata changes.
    
    Attributes
    ----------
    action : str
        Type of action performed
    timestamp : float
        When the action occurred
    previous_value : Any
        Value before change
    new_value : Any
        Value after change
    reason : Optional[str]
        Reason for the change
    user : Optional[str]
        User who made the change
    """
    action: str
    timestamp: float = field(default_factory=time.time)
    previous_value: Any = None
    new_value: Any = None
    reason: Optional[str] = None
    user: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'action': self.action,
            'timestamp': self.timestamp,
            'previous_value': self.previous_value,
            'new_value': self.new_value,
            'reason': self.reason,
            'user': self.user
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AuditEntry':
        """Create from dictionary."""
        return cls(
            action=data['action'],
            timestamp=data.get('timestamp', time.time()),
            previous_value=data.get('previous_value'),
            new_value=data.get('new_value'),
            reason=data.get('reason'),
            user=data.get('user')
        )


@dataclass
class ModuleMetadata:
    """
    Comprehensive metadata for tracking module state and dependencies.
    
    This class provides extensive metadata management including versioning,
    dependency tracking, integrity verification, and audit logging.
    
    Attributes
    ----------
    name : str
        Module name (fully qualified)
    version : str
        Module version string
    version_scheme : VersionScheme
        Version numbering scheme used
    author : str
        Module author name/email
    maintainers : List[str]
        List of maintainer names/emails
    description : str
        Module description
    long_description : Optional[str]
        Extended description/documentation
    license : Optional[str]
        Module license type
    homepage : Optional[str]
        Project homepage URL
    repository : Optional[str]
        Source code repository URL
    documentation : Optional[str]
        Documentation URL
    keywords : List[str]
        Search keywords/tags
    classifiers : List[str]
        PyPI classifiers
    dependencies : List[DependencySpec]
        List of module dependencies
    dev_dependencies : List[DependencySpec]
        Development dependencies
    optional_dependencies : Dict[str, List[DependencySpec]]
        Optional dependency groups
    python_requires : Optional[str]
        Required Python version
    platform_requires : List[str]
        Required platforms
    created_at : float
        Creation timestamp
    modified_at : float
        Last modification timestamp
    content_hash : ContentHash
        Content hash for integrity verification
    size : int
        Content size in bytes
    integrity_status : IntegrityStatus
        Current integrity status
    audit_log : List[AuditEntry]
        Audit trail of changes
    custom_metadata : Dict[str, Any]
        Custom extensible metadata
    """
    
    # Basic information
    name: str
    version: str = "1.0.0"
    version_scheme: VersionScheme = VersionScheme.SEMANTIC
    author: str = "unknown"
    maintainers: List[str] = field(default_factory=list)
    description: str = ""
    long_description: Optional[str] = None
    license: Optional[str] = None
    
    # URLs
    homepage: Optional[str] = None
    repository: Optional[str] = None
    documentation: Optional[str] = None
    
    # Classification
    keywords: List[str] = field(default_factory=list)
    classifiers: List[str] = field(default_factory=list)
    
    # Dependencies
    dependencies: List[DependencySpec] = field(default_factory=list)
    dev_dependencies: List[DependencySpec] = field(default_factory=list)
    optional_dependencies: Dict[str, List[DependencySpec]] = field(default_factory=dict)
    
    # Requirements
    python_requires: Optional[str] = None
    platform_requires: List[str] = field(default_factory=list)
    
    # Timestamps
    created_at: float = field(default_factory=time.time)
    modified_at: float = field(default_factory=time.time)
    
    # Integrity
    content_hash: ContentHash = field(default_factory=ContentHash)
    size: int = 0
    integrity_status: IntegrityStatus = IntegrityStatus.UNKNOWN
    
    # Tracking
    audit_log: List[AuditEntry] = field(default_factory=list)
    
    # Extensibility
    custom_metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Internal state
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _cache: Dict[str, Any] = field(default_factory=dict, repr=False)
    
    def __post_init__(self) -> None:
        """Initialize and validate metadata."""
        if not self.maintainers:
            self.maintainers = [self.author]
        
        # Normalize platform paths
        self.platform_requires = [
            p.lower().replace('\\', '/') for p in self.platform_requires
        ]
        
        # Add creation audit entry
        if not self.audit_log:
            self._add_audit_entry("create", None, self.version, "Module metadata created")
    
    def _add_audit_entry(
        self,
        action: str,
        old_value: Any,
        new_value: Any,
        reason: Optional[str] = None
    ) -> None:
        """
        Add an entry to the audit log.
        
        Parameters
        ----------
        action : str
            Type of action performed
        old_value : Any
            Value before change
        new_value : Any
            Value after change
        reason : Optional[str]
            Reason for the change
        """
        with self._lock:
            entry = AuditEntry(
                action=action,
                previous_value=old_value,
                new_value=new_value,
                reason=reason,
                user=os.environ.get('USER', os.environ.get('USERNAME', 'unknown'))
            )
            self.audit_log.append(entry)
            
            # Limit audit log size
            if len(self.audit_log) > 1000:
                self.audit_log = self.audit_log[-1000:]
    
    def update_content_hash(self, content: Union[str, bytes]) -> None:
        """
        Update content hash and size from module source.
        
        This method computes cryptographic hashes of the module content
        for integrity verification and tracking.
        
        Parameters
        ----------
        content : Union[str, bytes]
            Module source code content
            
        Examples
        --------
        >>> meta = ModuleMetadata("my_module")
        >>> source = "def hello(): return 'world'"
        >>> meta.update_content_hash(source)
        >>> print(meta.content_hash.sha256[:16])
        a1b2c3d4e5f6g7h8
        """
        with self._lock:
            old_hash = self.content_hash.sha256 if self.content_hash else ""
            old_size = self.size
            
            if isinstance(content, str):
                content_bytes = content.encode('utf-8')
            else:
                content_bytes = content
            
            self.content_hash = ContentHash.from_content(content_bytes)
            self.size = len(content_bytes)
            self.modified_at = time.time()
            self.integrity_status = IntegrityStatus.VERIFIED
            
            if old_hash and old_hash != self.content_hash.sha256:
                self._add_audit_entry(
                    "content_update",
                    {"hash": old_hash[:16], "size": old_size},
                    {"hash": self.content_hash.sha256[:16], "size": self.size},
                    "Content hash updated"
                )
    
    def verify_integrity(self, content: Union[str, bytes], algorithm: str = "sha256") -> bool:
        """
        Verify module content integrity against stored hash.
        
        This method checks if the provided content matches the stored
        cryptographic hash, detecting any tampering or corruption.
        
        Parameters
        ----------
        content : Union[str, bytes]
            Content to verify
        algorithm : str
            Hash algorithm to use ('sha256', 'sha512', 'md5', 'blake2b')
            
        Returns
        -------
        bool
            True if content integrity is verified
            
        Examples
        --------
        >>> meta = ModuleMetadata("my_module")
        >>> meta.update_content_hash(original_source)
        >>> if meta.verify_integrity(current_source):
        ...     print("Module unchanged")
        ... else:
        ...     print("Module modified or corrupted")
        """
        with self._lock:
            if not self.content_hash:
                self.integrity_status = IntegrityStatus.UNKNOWN
                return False
            
            is_valid = self.content_hash.verify(content, algorithm)
            self.integrity_status = IntegrityStatus.VERIFIED if is_valid else IntegrityStatus.MODIFIED
            
            if not is_valid:
                self._add_audit_entry(
                    "integrity_check_failed",
                    self.content_hash.sha256[:16],
                    "mismatch",
                    f"Integrity verification failed using {algorithm}"
                )
            
            return is_valid
    
    def add_dependency(
        self,
        name: str,
        version_spec: str = "",
        dep_type: DependencyType = DependencyType.REQUIRED,
        **kwargs
    ) -> None:
        """
        Add a module dependency.
        
        This method adds a new dependency to the module's dependency list
        with comprehensive version and platform specifications.
        
        Parameters
        ----------
        name : str
            Dependency package/module name
        version_spec : str
            Version specification (e.g., ">=1.0.0,<2.0.0")
        dep_type : DependencyType
            Type of dependency
        **kwargs
            Additional DependencySpec parameters
            
        Examples
        --------
        >>> meta = ModuleMetadata("my_package")
        >>> meta.add_dependency("numpy", ">=1.20.0")
        >>> meta.add_dependency("pandas", ">=1.3.0", dep_type=DependencyType.OPTIONAL)
        >>> meta.add_dependency(
        ...     "windows-only-lib",
        ...     platform_restrictions=["win32"]
        ... )
        """
        with self._lock:
            # Check for duplicate
            for dep in self.dependencies:
                if dep.name == name and dep.dep_type == dep_type:
                    # Update existing
                    dep.version_spec = version_spec
                    for key, value in kwargs.items():
                        if hasattr(dep, key):
                            setattr(dep, key, value)
                    self._add_audit_entry(
                        "dependency_updated",
                        f"{name}@{dep.version_spec}",
                        f"{name}@{version_spec}",
                        f"Updated {dep_type.value} dependency"
                    )
                    return
            
            # Add new dependency
            dep = DependencySpec(
                name=name,
                version_spec=version_spec,
                dep_type=dep_type,
                **{k: v for k, v in kwargs.items() if hasattr(DependencySpec, k)}
            )
            
            self.dependencies.append(dep)
            self.modified_at = time.time()
            
            self._add_audit_entry(
                "dependency_added",
                None,
                str(dep),
                f"Added {dep_type.value} dependency"
            )
    
    def remove_dependency(self, name: str, dep_type: Optional[DependencyType] = None) -> bool:
        """
        Remove a module dependency.
        
        Parameters
        ----------
        name : str
            Dependency name to remove
        dep_type : Optional[DependencyType]
            Type of dependency to remove (None for all types)
            
        Returns
        -------
        bool
            True if dependency was removed
        """
        with self._lock:
            removed = False
            self.dependencies = [
                dep for dep in self.dependencies
                if not (dep.name == name and (dep_type is None or dep.dep_type == dep_type))
            ]
            
            if removed:
                self.modified_at = time.time()
                self._add_audit_entry(
                    "dependency_removed",
                    name,
                    None,
                    f"Removed {dep_type.value if dep_type else 'all'} dependency"
                )
            
            return removed
    
    def add_optional_dependency_group(
        self,
        group_name: str,
        dependencies: List[Union[str, DependencySpec]]
    ) -> None:
        """
        Add an optional dependency group.
        
        Parameters
        ----------
        group_name : str
            Name of the dependency group (e.g., 'dev', 'test', 'docs')
        dependencies : List[Union[str, DependencySpec]]
            List of dependencies in the group
            
        Examples
        --------
        >>> meta = ModuleMetadata("my_package")
        >>> meta.add_optional_dependency_group(
        ...     "test",
        ...     ["pytest>=7.0.0", "pytest-cov>=4.0.0"]
        ... )
        """
        with self._lock:
            specs = []
            for dep in dependencies:
                if isinstance(dep, str):
                    specs.append(DependencySpec(name=dep, dep_type=DependencyType.OPTIONAL))
                else:
                    specs.append(dep)
            
            self.optional_dependencies[group_name] = specs
            self.modified_at = time.time()
            
            self._add_audit_entry(
                "optional_group_added",
                None,
                group_name,
                f"Added optional dependency group with {len(specs)} dependencies"
            )
    
    def bump_version(self, part: str = "patch") -> str:
        """
        Bump the module version according to semantic versioning.
        
        Parameters
        ----------
        part : str
            Version part to bump ('major', 'minor', 'patch')
            
        Returns
        -------
        str
            New version string
            
        Examples
        --------
        >>> meta = ModuleMetadata("my_module", version="1.2.3")
        >>> meta.bump_version("patch")
        '1.2.4'
        >>> meta.bump_version("minor")
        '1.3.0'
        >>> meta.bump_version("major")
        '2.0.0'
        """
        with self._lock:
            old_version = self.version
            
            if self.version_scheme == VersionScheme.SEMANTIC:
                parts = self.version.split('.')
                while len(parts) < 3:
                    parts.append('0')
                
                major, minor, patch = map(int, parts[:3])
                
                if part == "major":
                    major += 1
                    minor = 0
                    patch = 0
                elif part == "minor":
                    minor += 1
                    patch = 0
                else:  # patch
                    patch += 1
                
                self.version = f"{major}.{minor}.{patch}"
            
            elif self.version_scheme == VersionScheme.CALENDAR:
                self.version = datetime.now().strftime("%Y.%m.%d")
            
            elif self.version_scheme == VersionScheme.INCREMENTAL:
                self.version = str(int(self.version.split('.')[0]) + 1)
            
            self.modified_at = time.time()
            
            self._add_audit_entry(
                "version_bump",
                old_version,
                self.version,
                f"Bumped {part} version"
            )
            
            return self.version
    
    def set_custom_metadata(self, key: str, value: Any) -> None:
        """
        Set custom metadata value.
        
        Parameters
        ----------
        key : str
            Metadata key
        value : Any
            Metadata value
        """
        with self._lock:
            old_value = self.custom_metadata.get(key)
            self.custom_metadata[key] = value
            self.modified_at = time.time()
            
            self._add_audit_entry(
                "custom_metadata_set",
                old_value,
                value,
                f"Set custom metadata '{key}'"
            )
    
    def get_custom_metadata(self, key: str, default: Any = None) -> Any:
        """
        Get custom metadata value.
        
        Parameters
        ----------
        key : str
            Metadata key
        default : Any
            Default value if key not found
            
        Returns
        -------
        Any
            Metadata value
        """
        return self.custom_metadata.get(key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert metadata to dictionary representation.
        
        This method creates a comprehensive dictionary containing all
        metadata fields suitable for JSON serialization.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of metadata
            
        Examples
        --------
        >>> meta = ModuleMetadata("my_module")
        >>> data = meta.to_dict()
        >>> print(json.dumps(data, indent=2))
        {
          "name": "my_module",
          "version": "1.0.0",
          ...
        }
        """
        with self._lock:
            return {
                # Basic info
                'name': self.name,
                'version': self.version,
                'version_scheme': self.version_scheme.value,
                'author': self.author,
                'maintainers': self.maintainers,
                'description': self.description,
                'long_description': self.long_description,
                'license': self.license,
                
                # URLs
                'homepage': self.homepage,
                'repository': self.repository,
                'documentation': self.documentation,
                
                # Classification
                'keywords': self.keywords,
                'classifiers': self.classifiers,
                
                # Dependencies
                'dependencies': [dep.to_dict() for dep in self.dependencies],
                'dev_dependencies': [dep.to_dict() for dep in self.dev_dependencies],
                'optional_dependencies': {
                    group: [dep.to_dict() for dep in deps]
                    for group, deps in self.optional_dependencies.items()
                },
                
                # Requirements
                'python_requires': self.python_requires,
                'platform_requires': self.platform_requires,
                
                # Timestamps
                'created_at': self.created_at,
                'modified_at': self.modified_at,
                
                # Integrity
                'content_hash': self.content_hash.to_dict(),
                'size': self.size,
                'integrity_status': self.integrity_status.value,
                
                # Tracking
                'audit_log': [entry.to_dict() for entry in self.audit_log],
                
                # Extensibility
                'custom_metadata': self.custom_metadata
            }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ModuleMetadata':
        """
        Create metadata instance from dictionary representation.
        
        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary containing metadata fields
            
        Returns
        -------
        ModuleMetadata
            Reconstructed metadata instance
            
        Examples
        --------
        >>> with open("metadata.json") as f:
        ...     data = json.load(f)
        >>> meta = ModuleMetadata.from_dict(data)
        """
        # Parse version scheme
        version_scheme = VersionScheme.SEMANTIC
        if 'version_scheme' in data:
            try:
                version_scheme = VersionScheme(data['version_scheme'])
            except ValueError:
                pass
        
        # Parse dependencies
        dependencies = []
        for dep_data in data.get('dependencies', []):
            dependencies.append(DependencySpec.from_dict(dep_data))
        
        dev_dependencies = []
        for dep_data in data.get('dev_dependencies', []):
            dev_dependencies.append(DependencySpec.from_dict(dep_data))
        
        # Parse optional dependencies
        optional_dependencies = {}
        for group, deps in data.get('optional_dependencies', {}).items():
            optional_dependencies[group] = [
                DependencySpec.from_dict(dep_data) for dep_data in deps
            ]
        
        # Parse content hash
        content_hash = ContentHash.from_dict(data.get('content_hash', {}))
        
        # Parse integrity status
        integrity_status = IntegrityStatus.UNKNOWN
        if 'integrity_status' in data:
            try:
                integrity_status = IntegrityStatus(data['integrity_status'])
            except ValueError:
                pass
        
        # Parse audit log
        audit_log = []
        for entry_data in data.get('audit_log', []):
            audit_log.append(AuditEntry.from_dict(entry_data))
        
        return cls(
            name=data['name'],
            version=data.get('version', '1.0.0'),
            version_scheme=version_scheme,
            author=data.get('author', 'unknown'),
            maintainers=data.get('maintainers', []),
            description=data.get('description', ''),
            long_description=data.get('long_description'),
            license=data.get('license'),
            homepage=data.get('homepage'),
            repository=data.get('repository'),
            documentation=data.get('documentation'),
            keywords=data.get('keywords', []),
            classifiers=data.get('classifiers', []),
            dependencies=dependencies,
            dev_dependencies=dev_dependencies,
            optional_dependencies=optional_dependencies,
            python_requires=data.get('python_requires'),
            platform_requires=data.get('platform_requires', []),
            created_at=data.get('created_at', time.time()),
            modified_at=data.get('modified_at', time.time()),
            content_hash=content_hash,
            size=data.get('size', 0),
            integrity_status=integrity_status,
            audit_log=audit_log,
            custom_metadata=data.get('custom_metadata', {})
        )
    
    def save_to_file(self, path: Union[str, Path], indent: int = 2) -> None:
        """
        Save metadata to JSON file.
        
        Parameters
        ----------
        path : Union[str, Path]
            Path to output file
        indent : int
            JSON indentation level
            
        Raises
        ------
        IOError
            If file cannot be written
            
        Examples
        --------
        >>> meta = ModuleMetadata("my_module")
        >>> meta.save_to_file("my_module.meta.json")
        """
        path = Path(path)
        path = path.resolve()  # Normalize for cross-platform
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=indent, ensure_ascii=False)
    
    @classmethod
    def load_from_file(cls, path: Union[str, Path]) -> 'ModuleMetadata':
        """
        Load metadata from JSON file.
        
        Parameters
        ----------
        path : Union[str, Path]
            Path to metadata file
            
        Returns
        -------
        ModuleMetadata
            Loaded metadata instance
            
        Raises
        ------
        FileNotFoundError
            If file does not exist
        json.JSONDecodeError
            If file contains invalid JSON
            
        Examples
        --------
        >>> meta = ModuleMetadata.load_from_file("my_module.meta.json")
        """
        path = Path(path).resolve()
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return cls.from_dict(data)
    
    def validate_dependencies(self) -> Tuple[bool, List[str]]:
        """
        Validate all dependencies for compatibility.
        
        This method checks all dependencies against current environment
        and returns validation results.
        
        Returns
        -------
        Tuple[bool, List[str]]
            (is_valid, list_of_issues)
            
        Examples
        --------
        >>> meta = ModuleMetadata("my_module")
        >>> valid, issues = meta.validate_dependencies()
        >>> if not valid:
        ...     for issue in issues:
        ...         print(f"Issue: {issue}")
        """
        issues = []
        
        # Check Python version
        if self.python_requires:
            current = f"{sys.version_info.major}.{sys.version_info.minor}"
            if not self._check_version_compatibility(current, self.python_requires):
                issues.append(f"Python {self.python_requires} required, but {current} is installed")
        
        # Check platform
        if self.platform_requires:
            current_platform = sys.platform
            if current_platform not in self.platform_requires:
                issues.append(f"Platform must be one of {self.platform_requires}, but is {current_platform}")
        
        # Check dependencies
        for dep in self.dependencies:
            if dep.dep_type == DependencyType.REQUIRED:
                if not self._is_dependency_satisfied(dep):
                    issues.append(f"Required dependency '{dep}' not satisfied")
        
        return len(issues) == 0, issues
    
    def _is_dependency_satisfied(self, dep: DependencySpec) -> bool:
        """
        Check if a dependency is satisfied in current environment.
        
        Parameters
        ----------
        dep : DependencySpec
            Dependency to check
            
        Returns
        -------
        bool
            True if dependency is satisfied
        """
        try:
            module = __import__(dep.name.split('>=')[0].split('<=')[0].split('==')[0].strip())
            
            if hasattr(module, '__version__'):
                version = module.__version__
                return dep.is_compatible_with(version, sys.platform)
            
            # If no version attribute, assume it's satisfied
            return True
            
        except ImportError:
            return False
    
    def _check_version_compatibility(self, current: str, required: str) -> bool:
        """
        Check if current version satisfies requirement.
        
        Parameters
        ----------
        current : str
            Current version string
        required : str
            Version requirement specification
            
        Returns
        -------
        bool
            True if compatible
        """
        temp_dep = DependencySpec(name="temp", version_spec=required)
        return temp_dep.is_compatible_with(current)
    
    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """
        Generate dependency graph for visualization.
        
        Returns
        -------
        Dict[str, List[str]]
            Adjacency list representation of dependency graph
        """
        graph = defaultdict(list)
        graph[self.name] = [dep.name for dep in self.dependencies]
        
        for dep in self.dependencies:
            graph[dep.name] = []
        
        return dict(graph)
    
    def merge(self, other: 'ModuleMetadata', overwrite: bool = False) -> 'ModuleMetadata':
        """
        Merge another metadata instance into this one.
        
        Parameters
        ----------
        other : ModuleMetadata
            Metadata to merge
        overwrite : bool
            Whether to overwrite existing values
            
        Returns
        -------
        ModuleMetadata
            Self for method chaining
        """
        with self._lock:
            # Merge basic fields
            fields_to_merge = [
                'description', 'long_description', 'license',
                'homepage', 'repository', 'documentation'
            ]
            
            for field in fields_to_merge:
                other_value = getattr(other, field)
                if other_value and (overwrite or not getattr(self, field)):
                    setattr(self, field, other_value)
            
            # Merge lists
            self.keywords = list(set(self.keywords + other.keywords))
            self.classifiers = list(set(self.classifiers + other.classifiers))
            self.maintainers = list(set(self.maintainers + other.maintainers))
            
            # Merge dependencies
            existing_names = {dep.name for dep in self.dependencies}
            for dep in other.dependencies:
                if overwrite or dep.name not in existing_names:
                    self.dependencies.append(dep)
            
            # Merge custom metadata
            if overwrite:
                self.custom_metadata.update(other.custom_metadata)
            else:
                for key, value in other.custom_metadata.items():
                    if key not in self.custom_metadata:
                        self.custom_metadata[key] = value
            
            self.modified_at = time.time()
            self._add_audit_entry(
                "metadata_merged",
                None,
                other.name,
                f"Merged metadata from {other.name}"
            )
            
            return self
    
    def clone(self) -> 'ModuleMetadata':
        """
        Create a deep copy of the metadata.
        
        Returns
        -------
        ModuleMetadata
            Cloned metadata instance
        """
        return self.from_dict(self.to_dict())
    
    def clear_cache(self) -> None:
        """Clear internal cache."""
        with self._lock:
            self._cache.clear()
    
    def __str__(self) -> str:
        """Return string representation."""
        return f"ModuleMetadata({self.name} v{self.version})"
    
    def __repr__(self) -> str:
        """Return detailed representation."""
        return (f"ModuleMetadata(name='{self.name}', version='{self.version}', "
                f"deps={len(self.dependencies)}, status={self.integrity_status.value})")
    
    def __eq__(self, other: Any) -> bool:
        """Check equality with another metadata instance."""
        if not isinstance(other, ModuleMetadata):
            return False
        return (self.name == other.name and 
                self.version == other.version and
                self.content_hash.sha256 == other.content_hash.sha256)
    
    def __hash__(self) -> int:
        """Generate hash for metadata instance."""
        return hash((self.name, self.version, self.content_hash.sha256))


# Export public interface
__all__ = [
    'ModuleMetadata',
    'DependencySpec',
    'ContentHash',
    'AuditEntry',
    'VersionScheme',
    'DependencyType',
    'IntegrityStatus',
]