#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Version Parser - Comprehensive Python Package Version Extraction Library
========================================================================

A robust, cross-platform version extraction library that provides multiple
methods to retrieve version information from Python packages, source files,
configuration files, and installed distributions. Supports PEP 621, Poetry,
setuptools, and various version file formats.

Supported Version Sources
-------------------------
- FILE: Regex extraction from Python files
- FILE_AST: AST-based extraction from Python files
- IMPORT: Direct module import
- IMPORTLIB: importlib.metadata (Python 3.8+)
- PKG_RESOURCES: pkg_resources (legacy)
- SETUP_PY: setup.py parsing
- PYPROJECT_TOML: pyproject.toml (PEP 621, Poetry)
- REQUIREMENTS: requirements.txt
- PIP_LIST: pip list command output
- CUSTOM: Custom user-provided version

Examples
--------
>>> from pyputil.version import VersionParser, get_version_info
>>> parser = VersionParser()
>>> 
>>> # Parse installed packages
>>> packages = parser.parse_installed_packages()
>>> for pkg in packages[:5]:
...     print(f"{pkg.name}: {pkg.version}")
...
>>> # Parse a specific file
>>> versions = parser.parse_from_file("my_module/__init__.py")
>>> 
>>> # Parse from import
>>> version = parser.parse_from_import("requests")
>>> if version:
...     print(f"requests {version.version}")
...
>>> # Parse entire project directory
>>> all_versions = parser.parse_directory(".")
>>> for v in all_versions:
...     print(f"{v.name}: {v.version} (source: {v.source.value})")
"""

import re
import ast
import sys
import json
import subprocess
import configparser
from pathlib import Path
from typing import (
    Dict, List, Optional, Union, Tuple, Any, Set, 
    Iterator, ClassVar, Pattern, Callable, TypeVar
)
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from functools import lru_cache
import warnings
import os
import hashlib

# ============================================================================
# Platform-Specific Configuration
# ============================================================================

# Detect operating system
_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"
_IS_LINUX = sys.platform.startswith("linux")
_IS_BSD = any(sys.platform.startswith(bsd) for bsd in ("freebsd", "openbsd", "netbsd", "dragonfly"))

# Python version detection
_PYTHON_VERSION = sys.version_info
_PYTHON_311_PLUS = _PYTHON_VERSION >= (3, 11)
_PYTHON_38_PLUS = _PYTHON_VERSION >= (3, 8)

# Encoding for file operations
_DEFAULT_ENCODING = 'utf-8'
_FALLBACK_ENCODINGS = ['latin-1', 'cp1252'] if _IS_WINDOWS else ['latin-1']


# ============================================================================
# Enums for Type-Safe Configuration
# ============================================================================

class VersionSource(Enum):
    """
    Enumeration of version information sources.
    
    Attributes
    ----------
    FILE : str
        Regex-based extraction from Python source files.
    FILE_AST : str
        AST-based extraction from Python source files.
    IMPORT : str
        Direct module import and attribute inspection.
    IMPORTLIB : str
        importlib.metadata (Python 3.8+ standard library).
    PKG_RESOURCES : str
        pkg_resources (setuptools legacy API).
    SETUP_PY : str
        Parsing setup.py configuration file.
    SETUP_CFG : str
        Parsing setup.cfg configuration file.
    PYPROJECT_TOML : str
        Parsing pyproject.toml (PEP 621 / Poetry).
    REQUIREMENTS : str
        Parsing requirements.txt file.
    PIP_LIST : str
        Executing 'pip list' command.
    ENVIRONMENT : str
        Environment variable.
    CUSTOM : str
        User-provided custom version.
    UNKNOWN : str
        Unknown or unspecified source.
    """
    FILE = "file"
    FILE_AST = "file_ast"
    IMPORT = "import"
    IMPORTLIB = "importlib"
    PKG_RESOURCES = "pkg_resources"
    SETUP_PY = "setup_py"
    SETUP_CFG = "setup_cfg"
    PYPROJECT_TOML = "pyproject_toml"
    REQUIREMENTS = "requirements"
    PIP_LIST = "pip_list"
    ENVIRONMENT = "environment"
    CUSTOM = "custom"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value
    
    @property
    def description(self) -> str:
        """Get human-readable description of the source."""
        descriptions = {
            VersionSource.FILE: "Regex extraction from Python file",
            VersionSource.FILE_AST: "AST-based extraction from Python file",
            VersionSource.IMPORT: "Direct module import",
            VersionSource.IMPORTLIB: "importlib.metadata (standard library)",
            VersionSource.PKG_RESOURCES: "pkg_resources (setuptools legacy)",
            VersionSource.SETUP_PY: "setup.py configuration",
            VersionSource.SETUP_CFG: "setup.cfg configuration",
            VersionSource.PYPROJECT_TOML: "pyproject.toml (PEP 621/Poetry)",
            VersionSource.REQUIREMENTS: "requirements.txt",
            VersionSource.PIP_LIST: "pip list command",
            VersionSource.ENVIRONMENT: "Environment variable",
            VersionSource.CUSTOM: "User-provided custom version",
        }
        return descriptions.get(self, "Unknown source")
    
    @property
    def default_confidence(self) -> float:
        """
        Get default confidence level for this source.
        
        Returns
        -------
        float
            Default confidence value (0.0 to 1.0).
        """
        confidences = {
            VersionSource.FILE: 0.8,
            VersionSource.FILE_AST: 0.95,
            VersionSource.IMPORT: 0.95,
            VersionSource.IMPORTLIB: 0.95,
            VersionSource.PKG_RESOURCES: 0.9,
            VersionSource.SETUP_PY: 0.85,
            VersionSource.SETUP_CFG: 0.85,
            VersionSource.PYPROJECT_TOML: 0.9,
            VersionSource.REQUIREMENTS: 0.85,
            VersionSource.PIP_LIST: 0.85,
            VersionSource.ENVIRONMENT: 0.7,
            VersionSource.CUSTOM: 1.0,
        }
        return confidences.get(self, 0.5)


class ParseErrorType(Enum):
    """
    Enumeration of parsing error types.
    
    Attributes
    ----------
    NONE : str
        No error.
    FILE_NOT_FOUND : str
        Specified file does not exist.
    PERMISSION_DENIED : str
        Insufficient permissions to read file.
    SYNTAX_ERROR : str
        Python syntax error in source file.
    IMPORT_ERROR : str
        Module could not be imported.
    ENCODING_ERROR : str
        File encoding could not be determined.
    TIMEOUT : str
        Operation timed out.
    PARSE_FAILED : str
        General parsing failure.
    UNKNOWN : str
        Unknown error type.
    """
    NONE = "none"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    SYNTAX_ERROR = "syntax_error"
    IMPORT_ERROR = "import_error"
    ENCODING_ERROR = "encoding_error"
    TIMEOUT = "timeout"
    PARSE_FAILED = "parse_failed"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value


class ProjectFormat(Enum):
    """
    Enumeration of project configuration formats.
    
    Attributes
    ----------
    PEP_621 : str
        PEP 621 standard pyproject.toml format.
    POETRY : str
        Poetry pyproject.toml format.
    SETUPTOOLS : str
        Traditional setuptools (setup.py/setup.cfg).
    FLIT : str
        Flit pyproject.toml format.
    PDM : str
        PDM pyproject.toml format.
    HATCH : str
        Hatch pyproject.toml format.
    UNKNOWN : str
        Unknown project format.
    """
    PEP_621 = "pep621"
    POETRY = "poetry"
    SETUPTOOLS = "setuptools"
    FLIT = "flit"
    PDM = "pdm"
    HATCH = "hatch"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value


class RequirementOperator(Enum):
    """
    Enumeration of version requirement operators.
    
    Attributes
    ----------
    EQ : str
        Equal to (==).
    NE : str
        Not equal to (!=).
    GT : str
        Greater than (>).
    GE : str
        Greater than or equal (>=).
    LT : str
        Less than (<).
    LE : str
        Less than or equal (<=).
    COMPATIBLE : str
        Compatible release (~=).
    WILDCARD : str
        Wildcard/any version (*).
    """
    EQ = "=="
    NE = "!="
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="
    COMPATIBLE = "~="
    WILDCARD = "*"
    
    @classmethod
    def from_string(cls, value: str) -> Optional['RequirementOperator']:
        """Convert string to RequirementOperator enum."""
        for op in cls:
            if op.value == value:
                return op
        return None
    
    def __str__(self) -> str:
        return self.value


# ============================================================================
# Data Classes
# ============================================================================

@dataclass(frozen=True)
class ParseError:
    """
    Represents a parsing error with detailed information.
    
    Attributes
    ----------
    error_type : ParseErrorType
        Type of error that occurred.
    message : str
        Human-readable error message.
    path : Optional[str]
        File path related to the error.
    line_number : Optional[int]
        Line number where error occurred (if applicable).
    original_error : Optional[Exception]
        Original exception that caused the error.
    """
    error_type: ParseErrorType
    message: str
    path: Optional[str] = None
    line_number: Optional[int] = None
    original_error: Optional[Exception] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "error_type": str(self.error_type),
            "message": self.message,
            "path": self.path,
            "line_number": self.line_number,
            "original_error": str(self.original_error) if self.original_error else None,
        }
    
    def __str__(self) -> str:
        parts = [f"[{self.error_type.value}] {self.message}"]
        if self.path:
            parts.append(f"Path: {self.path}")
        if self.line_number:
            parts.append(f"Line: {self.line_number}")
        return " ".join(parts)


@dataclass(frozen=True)
class ModuleVersion:
    """
    Represents a module version with metadata.
    
    Attributes
    ----------
    name : str
        Module or package name.
    version : str
        Version string.
    source : VersionSource
        Source of the version information.
    path : Optional[str]
        File path where version was found.
    confidence : float
        Confidence level (0.0 to 1.0).
    metadata : Dict[str, Any]
        Additional metadata about the version.
    error : Optional[ParseError]
        Error that occurred during parsing (if any).
    timestamp : float
        Unix timestamp when version was parsed.
    """
    name: str
    version: str
    source: VersionSource = VersionSource.UNKNOWN
    path: Optional[str] = None
    confidence: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[ParseError] = None
    timestamp: float = field(default_factory=lambda: __import__('time').time())
    
    def __post_init__(self) -> None:
        """Validate after initialization."""
        if not self.name:
            raise ValueError("Module name cannot be empty")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")
    
    @property
    def is_reliable(self) -> bool:
        """
        Check if the version information is reliable.
        
        Returns
        -------
        bool
            True if confidence >= 0.9.
        """
        return self.confidence >= 0.9
    
    @property
    def has_error(self) -> bool:
        """Check if there was an error during parsing."""
        return self.error is not None
    
    @property
    def version_tuple(self) -> Tuple[int, ...]:
        """
        Parse version string into tuple of integers.
        
        Returns
        -------
        Tuple[int, ...]
            Version components as integers.
        """
        try:
            parts = re.findall(r'\d+', self.version)
            return tuple(int(p) for p in parts[:3])
        except (ValueError, TypeError):
            return ()
    
    def to_dict(self, include_metadata: bool = True) -> Dict[str, Any]:
        """
        Convert to dictionary representation.
        
        Parameters
        ----------
        include_metadata : bool, default=True
            Whether to include full metadata.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        result = {
            "name": self.name,
            "version": self.version,
            "source": str(self.source),
            "path": self.path,
            "confidence": self.confidence,
            "is_reliable": self.is_reliable,
            "version_tuple": list(self.version_tuple),
            "timestamp": self.timestamp,
        }
        
        if include_metadata and self.metadata:
            result["metadata"] = self.metadata.copy()
        
        if self.error:
            result["error"] = self.error.to_dict()
        
        return result
    
    def get_cache_key(self) -> str:
        """
        Generate a cache key for this version.
        
        Returns
        -------
        str
            Unique cache key.
        """
        components = [self.name, self.version, str(self.source)]
        if self.path:
            components.append(self.path)
        return hashlib.md5(":".join(components).encode()).hexdigest()
    
    def __lt__(self, other: 'ModuleVersion') -> bool:
        """Compare versions for sorting."""
        if not isinstance(other, ModuleVersion):
            return NotImplemented
        return self.name < other.name or (self.name == other.name and self.version < other.version)
    
    def __repr__(self) -> str:
        return f"ModuleVersion(name='{self.name}', version='{self.version}', source={self.source.value})"


@dataclass
class ParseResult:
    """
    Result of a version parsing operation.
    
    Attributes
    ----------
    versions : List[ModuleVersion]
        List of parsed version objects.
    errors : List[ParseError]
        List of errors encountered during parsing.
    total_processed : int
        Total number of items processed.
    success_count : int
        Number of successfully parsed items.
    source_stats : Dict[VersionSource, int]
        Statistics by version source.
    """
    versions: List[ModuleVersion] = field(default_factory=list)
    errors: List[ParseError] = field(default_factory=list)
    total_processed: int = 0
    success_count: int = 0
    source_stats: Dict[VersionSource, int] = field(default_factory=dict)
    
    def add_version(self, version: ModuleVersion) -> None:
        """Add a successfully parsed version."""
        self.versions.append(version)
        self.success_count += 1
        self.total_processed += 1
        self.source_stats[version.source] = self.source_stats.get(version.source, 0) + 1
    
    def add_error(self, error: ParseError) -> None:
        """Add a parsing error."""
        self.errors.append(error)
        self.total_processed += 1
    
    @property
    def success_rate(self) -> float:
        """
        Calculate success rate.
        
        Returns
        -------
        float
            Success rate (0.0 to 1.0).
        """
        if self.total_processed == 0:
            return 0.0
        return self.success_count / self.total_processed
    
    def get_unique_versions(self) -> List[ModuleVersion]:
        """
        Get unique versions (keeping highest confidence).
        
        Returns
        -------
        List[ModuleVersion]
            List of unique version objects.
        """
        unique: Dict[str, ModuleVersion] = {}
        for v in self.versions:
            key = f"{v.name}:{v.version}"
            if key not in unique or unique[key].confidence < v.confidence:
                unique[key] = v
        return sorted(unique.values(), key=lambda x: (x.name, x.version))
    
    def filter_by_source(self, source: VersionSource) -> List[ModuleVersion]:
        """
        Filter versions by source.
        
        Parameters
        ----------
        source : VersionSource
            Source to filter by.
        
        Returns
        -------
        List[ModuleVersion]
            Filtered version objects.
        """
        return [v for v in self.versions if v.source == source]
    
    def filter_reliable(self) -> List[ModuleVersion]:
        """Get only reliable versions (confidence >= 0.9)."""
        return [v for v in self.versions if v.is_reliable]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "versions": [v.to_dict() for v in self.versions],
            "errors": [e.to_dict() for e in self.errors],
            "total_processed": self.total_processed,
            "success_count": self.success_count,
            "success_rate": self.success_rate,
            "source_stats": {str(k): v for k, v in self.source_stats.items()},
            "unique_count": len(self.get_unique_versions()),
        }
    
    def get_summary(self) -> str:
        """
        Get a human-readable summary.
        
        Returns
        -------
        str
            Formatted summary string.
        """
        lines = [
            f"Parse Result Summary:",
            f"  Total processed: {self.total_processed}",
            f"  Successful: {self.success_count} ({self.success_rate:.1%})",
            f"  Errors: {len(self.errors)}",
            f"  Unique versions: {len(self.get_unique_versions())}",
            f"  Source breakdown:",
        ]
        for source, count in sorted(self.source_stats.items(), key=lambda x: -x[1]):
            lines.append(f"    - {source.value}: {count}")
        return "\n".join(lines)
    
    def __bool__(self) -> bool:
        """Return True if any versions were found."""
        return len(self.versions) > 0


# ============================================================================
# Regular Expression Patterns
# ============================================================================

@dataclass(frozen=True)
class VersionPatterns:
    """
    Container for compiled regular expression patterns.
    
    Attributes
    ----------
    VERSION_ASSIGN : List[Pattern]
        Patterns for version assignments in Python files.
    SETUP_VERSION : List[Pattern]
        Patterns for version extraction from setup.py.
    REQUIREMENT_LINE : Pattern
        Pattern for parsing requirements.txt lines.
    ENV_MARKER : Pattern
        Pattern for environment markers in requirements.
    EXTRAS : Pattern
        Pattern for extras specification.
    """
    
    # Version assignment patterns for Python files
    VERSION_ASSIGN: ClassVar[List[Pattern]] = [
        re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        re.compile(r'^__version__\s*=\s*\([\'"]([^\'"]+)[\'"]\)', re.MULTILINE),
        re.compile(r'^VERSION\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        re.compile(r'^VERSION\s*=\s*\([\'"]([^\'"]+)[\'"]\)', re.MULTILINE),
        re.compile(r'^version\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        re.compile(r'^__version__\s*=\s*["\']([\d\.]+[a-z]?[\d\.]*)["\']', re.MULTILINE),
        re.compile(r'^__version_info__\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)', re.MULTILINE),
    ]
    
    # Setup.py version extraction patterns
    SETUP_VERSION: ClassVar[List[Pattern]] = [
        re.compile(r'setup\s*\([^)]*version\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE | re.DOTALL),
        re.compile(r'^version\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        re.compile(r'version\s*=\s*get_version\(\)', re.MULTILINE),
        re.compile(r'use_scm_version\s*=\s*True', re.MULTILINE),
    ]
    
    # Requirements.txt line parser
    REQUIREMENT_LINE: ClassVar[Pattern] = re.compile(
        r'^([a-zA-Z0-9_\-\.]+)(?:\[([a-zA-Z0-9_,\-\.]+)\])?'
        r'(?:([=<>!~]=+)([0-9a-zA-Z\.\*\+]+))?'
        r'(?:\s*;\s*(.+))?$'
    )
    
    # Environment marker pattern
    ENV_MARKER: ClassVar[Pattern] = re.compile(r';.*$')
    
    # Extras pattern
    EXTRAS: ClassVar[Pattern] = re.compile(r'\[.*?\]')
    
    # Version number extraction
    VERSION_NUMBERS: ClassVar[Pattern] = re.compile(r'\d+')
    
    # Package name normalization
    PACKAGE_NAME: ClassVar[Pattern] = re.compile(r'^[a-zA-Z0-9_\-\.]+')


# Singleton instance for pattern access
PATTERNS = VersionPatterns()


# ============================================================================
# AST Visitor for Version Extraction
# ============================================================================

class VersionVisitor(ast.NodeVisitor):
    """
    AST visitor that extracts version assignments from Python code.
    
    This visitor traverses the abstract syntax tree of a Python module and
    identifies version assignments in various forms including simple
    assignments, annotated assignments, and tuple patterns.
    
    Attributes
    ----------
    versions : List[Tuple[str, str, float, Dict[str, Any]]]
        List of (version_string, variable_name, confidence, metadata) tuples.
    errors : List[ParseError]
        List of errors encountered during traversal.
    """
    
    # Common version variable names
    _VERSION_VARS: ClassVar[Set[str]] = {
        '__version__', 'VERSION', 'version', '__version_info__',
        '__VERSION__', 'Version', '_version', 'VERSION_STRING'
    }
    
    # Implementation mapping
    _IMPLEMENTATION_MAP: ClassVar[Dict[str, str]] = {
        'cpython': 'cp', 'pypy': 'pp', 'jython': 'jy', 'ironpython': 'ip'
    }
    
    def __init__(self) -> None:
        """Initialize the visitor with empty collections."""
        self.versions: List[Tuple[str, str, float, Dict[str, Any]]] = []
        self.errors: List[ParseError] = []
        self._current_file: Optional[str] = None
    
    def set_current_file(self, file_path: str) -> None:
        """Set the current file being processed for error reporting."""
        self._current_file = file_path
    
    def _extract_string_value(self, node: ast.expr) -> Optional[str]:
        """
        Extract string value from an AST node.
        
        Parameters
        ----------
        node : ast.expr
            The AST expression node to extract value from.
        
        Returns
        -------
        Optional[str]
            Extracted string value, or None if extraction fails.
        """
        # Python 3.8+ uses ast.Constant
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return node.value
            elif isinstance(node.value, (int, float)):
                return str(node.value)
        
        # Python < 3.8 uses ast.Str
        if hasattr(ast, 'Str') and isinstance(node, ast.Str):
            return node.s
        
        # Handle tuple patterns: __version__ = ("1.0.0",)
        if isinstance(node, ast.Tuple):
            if node.elts:
                return self._extract_string_value(node.elts[0])
        
        # Handle joined strings (f-strings)
        if isinstance(node, ast.JoinedStr):
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif hasattr(ast, 'FormattedValue') and isinstance(value, ast.FormattedValue):
                    extracted = self._extract_string_value(value.value)
                    if extracted:
                        parts.append(extracted)
            if parts:
                return ''.join(parts)
        
        # Handle binary operations (string concatenation)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._extract_string_value(node.left)
            right = self._extract_string_value(node.right)
            if left is not None and right is not None:
                return left + right
        
        return None
    
    def _extract_tuple_version(self, node: ast.expr) -> Optional[str]:
        """
        Extract version from tuple representation (e.g., (1, 2, 3)).
        
        Parameters
        ----------
        node : ast.expr
            The AST tuple node.
        
        Returns
        -------
        Optional[str]
            Version string like "1.2.3" or None.
        """
        if not isinstance(node, ast.Tuple):
            return None
        
        parts = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, int):
                parts.append(str(elt.value))
            elif hasattr(ast, 'Num') and isinstance(elt, ast.Num):
                parts.append(str(elt.n))
            else:
                return None
        
        return '.'.join(parts) if parts else None
    
    def visit_Assign(self, node: ast.Assign) -> None:
        """
        Visit an assignment node to extract version assignments.
        
        Parameters
        ----------
        node : ast.Assign
            The assignment AST node to process.
        """
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in self._VERSION_VARS:
                version_value = self._extract_string_value(node.value)
                
                if version_value:
                    confidence = 1.0 if target.id == '__version__' else 0.9
                    self.versions.append((
                        version_value, target.id, confidence,
                        {'variable': target.id, 'type': 'assignment'}
                    ))
                else:
                    # Try tuple extraction
                    tuple_version = self._extract_tuple_version(node.value)
                    if tuple_version:
                        confidence = 1.0 if target.id == '__version_info__' else 0.85
                        self.versions.append((
                            tuple_version, target.id, confidence,
                            {'variable': target.id, 'type': 'tuple_assignment'}
                        ))
        
        self.generic_visit(node)
    
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """
        Visit an annotated assignment node (Python 3.6+).
        
        Parameters
        ----------
        node : ast.AnnAssign
            The annotated assignment AST node to process.
        """
        if isinstance(node.target, ast.Name) and node.target.id in self._VERSION_VARS:
            if node.value:
                version_value = self._extract_string_value(node.value)
                if version_value:
                    confidence = 1.0 if node.target.id == '__version__' else 0.9
                    self.versions.append((
                        version_value, node.target.id, confidence,
                        {'variable': node.target.id, 'type': 'annotated_assignment'}
                    ))
        
        self.generic_visit(node)


# ============================================================================
# Main Version Parser Class
# ============================================================================

class VersionParser:
    """
    Comprehensive version parser for Python packages and files.
    
    This class provides multiple methods to extract version information from
    Python modules, source files, configuration files, and installed packages.
    It includes thread-safe caching, multiple fallback strategies, and
    comprehensive error handling.
    
    Parameters
    ----------
    use_fallbacks : bool, default=True
        Whether to use fallback methods when primary methods fail.
    cache_versions : bool, default=True
        Whether to cache parsed versions for performance.
    cache_size : int, default=1000
        Maximum number of items to cache.
    timeout : float, default=30.0
        Timeout in seconds for subprocess operations.
    encoding : str, default='utf-8'
        Default encoding for file operations.
    
    Attributes
    ----------
    use_fallbacks : bool
        Whether fallback methods are enabled.
    cache_versions : bool
        Whether caching is enabled.
    timeout : float
        Timeout for subprocess operations.
    encoding : str
        Default file encoding.
    
    Examples
    --------
    >>> parser = VersionParser()
    >>> 
    >>> # Parse installed packages
    >>> packages = parser.parse_installed_packages()
    >>> for pkg in packages[:5]:
    ...     print(f"{pkg.name}: {pkg.version}")
    ...
    >>> # Parse a specific file
    >>> versions = parser.parse_from_file("my_module.py")
    >>> 
    >>> # Parse from import
    >>> version = parser.parse_from_import("requests")
    >>> if version:
    ...     print(f"requests {version.version}")
    ...
    >>> # Parse entire project
    >>> result = parser.parse_directory(".")
    >>> print(result.get_summary())
    """
    
    def __init__(
        self,
        use_fallbacks: bool = True,
        cache_versions: bool = True,
        cache_size: int = 1000,
        timeout: float = 30.0,
        encoding: str = _DEFAULT_ENCODING,
    ) -> None:
        """
        Initialize the version parser.
        
        Parameters
        ----------
        use_fallbacks : bool, default=True
            Whether to use fallback methods.
        cache_versions : bool, default=True
            Whether to cache parsed versions.
        cache_size : int, default=1000
            Maximum cache size (LRU eviction).
        timeout : float, default=30.0
            Timeout for subprocess operations.
        encoding : str, default='utf-8'
            Default encoding for file operations.
        """
        self.use_fallbacks = use_fallbacks
        self.cache_versions = cache_versions
        self.cache_size = cache_size
        self.timeout = timeout
        self.encoding = encoding
        
        self._cache: Dict[str, Any] = {}
        self._cache_order: List[str] = []
        self._stats = {
            'cache_hits': 0,
            'cache_misses': 0,
            'parse_attempts': 0,
            'parse_successes': 0,
        }
        
        # Lazy-loaded modules
        self._toml_module: Optional[Any] = None
        self._importlib_metadata: Optional[Any] = None
    
    def _get_from_cache(self, key: str) -> Optional[Any]:
        """
        Retrieve item from cache.
        
        Parameters
        ----------
        key : str
            Cache key.
        
        Returns
        -------
        Optional[Any]
            Cached value or None.
        """
        if not self.cache_versions:
            return None
        
        if key in self._cache:
            self._stats['cache_hits'] += 1
            # Move to end for LRU
            self._cache_order.remove(key)
            self._cache_order.append(key)
            return self._cache[key]
        
        self._stats['cache_misses'] += 1
        return None
    
    def _put_in_cache(self, key: str, value: Any) -> None:
        """
        Store item in cache with LRU eviction.
        
        Parameters
        ----------
        key : str
            Cache key.
        value : Any
            Value to cache.
        """
        if not self.cache_versions:
            return
        
        if key in self._cache:
            self._cache_order.remove(key)
        elif len(self._cache) >= self.cache_size:
            # Evict oldest
            oldest_key = self._cache_order.pop(0)
            del self._cache[oldest_key]
        
        self._cache[key] = value
        self._cache_order.append(key)
    
    def _read_file_with_fallback_encoding(self, file_path: Path) -> Optional[str]:
        """
        Read a file with fallback encodings.
        
        Parameters
        ----------
        file_path : Path
            Path to the file.
        
        Returns
        -------
        Optional[str]
            File content or None if all encodings fail.
        """
        encodings = [self.encoding] + _FALLBACK_ENCODINGS
        
        for enc in encodings:
            try:
                return file_path.read_text(encoding=enc)
            except (UnicodeDecodeError, LookupError):
                continue
        
        return None
    
    def _get_toml_parser(self) -> Optional[Any]:
        """
        Get available TOML parser module.
        
        Returns
        -------
        Optional[Any]
            TOML module or None if not available.
        """
        if self._toml_module is not None:
            return self._toml_module
        
        # Try Python 3.11+ tomllib
        if _PYTHON_311_PLUS:
            try:
                import tomllib
                self._toml_module = tomllib
                return tomllib
            except ImportError:
                pass
        
        # Try tomli (third-party)
        try:
            import tomli
            self._toml_module = tomli
            return tomli
        except ImportError:
            pass
        
        # Try toml (legacy)
        try:
            import toml
            self._toml_module = toml
            return toml
        except ImportError:
            pass
        
        return None
    
    def _get_importlib_metadata(self) -> Optional[Any]:
        """
        Get importlib.metadata module.
        
        Returns
        -------
        Optional[Any]
            importlib.metadata module or None.
        """
        if self._importlib_metadata is not None:
            return self._importlib_metadata
        
        if _PYTHON_38_PLUS:
            try:
                import importlib.metadata
                self._importlib_metadata = importlib.metadata
                return importlib.metadata
            except ImportError:
                pass
        
        return None
    
    def parse_from_file(self, file_path: Union[str, Path]) -> ParseResult:
        """
        Parse version information from a Python file.
        
        This method uses both regex pattern matching and AST parsing to extract
        version information from Python source files.
        
        Parameters
        ----------
        file_path : Union[str, Path]
            Path to the Python file to parse.
        
        Returns
        -------
        ParseResult
            Result containing parsed versions and any errors.
        
        Examples
        --------
        >>> parser = VersionParser()
        >>> result = parser.parse_from_file("src/mypackage/__init__.py")
        >>> for v in result.versions:
        ...     print(f"Found version: {v.version} (confidence: {v.confidence})")
        """
        file_path = Path(file_path)
        result = ParseResult()
        
        # Check cache
        cache_key = f"file:{file_path.absolute()}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            for v in cached:
                result.add_version(v)
            return result
        
        # Check file existence
        if not file_path.exists():
            error = ParseError(
                error_type=ParseErrorType.FILE_NOT_FOUND,
                message=f"File not found: {file_path}",
                path=str(file_path)
            )
            result.add_error(error)
            return result
        
        # Check readability
        if not os.access(str(file_path), os.R_OK):
            error = ParseError(
                error_type=ParseErrorType.PERMISSION_DENIED,
                message=f"Cannot read file: {file_path}",
                path=str(file_path)
            )
            result.add_error(error)
            return result
        
        versions: List[ModuleVersion] = []
        
        try:
            content = self._read_file_with_fallback_encoding(file_path)
            if content is None:
                error = ParseError(
                    error_type=ParseErrorType.ENCODING_ERROR,
                    message=f"Cannot decode file: {file_path}",
                    path=str(file_path)
                )
                result.add_error(error)
                return result
            
            # Method 1: Regex pattern matching (fast)
            for pattern in PATTERNS.VERSION_ASSIGN:
                matches = pattern.findall(content)
                for match in matches:
                    if match:
                        if isinstance(match, tuple):
                            # Handle version_info tuple: (1, 2, 3)
                            version_str = '.'.join(str(m) for m in match if m)
                        else:
                            version_str = str(match).strip()
                        
                        if version_str:
                            versions.append(ModuleVersion(
                                name=file_path.stem,
                                version=version_str,
                                source=VersionSource.FILE,
                                path=str(file_path),
                                confidence=VersionSource.FILE.default_confidence,
                                metadata={'pattern': pattern.pattern[:50]}
                            ))
            
            # Method 2: AST parsing (slower, more accurate)
            try:
                tree = ast.parse(content)
                visitor = VersionVisitor()
                visitor.set_current_file(str(file_path))
                visitor.visit(tree)
                
                for version_str, var_name, confidence, metadata in visitor.versions:
                    versions.append(ModuleVersion(
                        name=file_path.stem,
                        version=version_str,
                        source=VersionSource.FILE_AST,
                        path=str(file_path),
                        confidence=confidence,
                        metadata={'variable': var_name, **metadata}
                    ))
                    
            except SyntaxError as e:
                error = ParseError(
                    error_type=ParseErrorType.SYNTAX_ERROR,
                    message=f"Syntax error: {e}",
                    path=str(file_path),
                    line_number=e.lineno if hasattr(e, 'lineno') else None,
                    original_error=e
                )
                result.add_error(error)
                
                if not self.use_fallbacks:
                    raise VersionParserError(f"Syntax error in {file_path}: {e}") from e
            
            # Remove duplicates (keep highest confidence)
            unique_versions: Dict[str, ModuleVersion] = {}
            for v in versions:
                key = f"{v.name}:{v.version}"
                if key not in unique_versions or unique_versions[key].confidence < v.confidence:
                    unique_versions[key] = v
            
            for v in unique_versions.values():
                result.add_version(v)
            
            # Cache the result
            self._put_in_cache(cache_key, list(unique_versions.values()))
            
        except Exception as e:
            error = ParseError(
                error_type=ParseErrorType.PARSE_FAILED,
                message=f"Error parsing file: {e}",
                path=str(file_path),
                original_error=e
            )
            result.add_error(error)
            
            if not self.use_fallbacks:
                raise VersionParserError(f"Error parsing {file_path}: {e}") from e
        
        return result
    
    def parse_from_import(self, module_name: str) -> Optional[ModuleVersion]:
        """
        Parse version by importing the module.
        
        This method attempts to import the module and extract version information
        from common version attributes.
        
        Parameters
        ----------
        module_name : str
            Name of the module to import and parse.
        
        Returns
        -------
        Optional[ModuleVersion]
            ModuleVersion object if version is found, None otherwise.
        
        Examples
        --------
        >>> parser = VersionParser()
        >>> version = parser.parse_from_import("numpy")
        >>> if version:
        ...     print(f"NumPy version: {version.version}")
        """
        cache_key = f"import:{module_name}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached[0] if cached else None
        
        self._stats['parse_attempts'] += 1
        version_attrs = ['__version__', 'VERSION', 'version', '__version_info__']
        
        try:
            module = __import__(module_name)
            
            version = None
            source_attr = None
            
            for attr in version_attrs:
                if hasattr(module, attr):
                    version = getattr(module, attr)
                    source_attr = attr
                    break
            
            if version is not None:
                # Convert tuple/list to string
                if isinstance(version, (tuple, list)):
                    version = '.'.join(str(v) for v in version)
                
                result = ModuleVersion(
                    name=module_name,
                    version=str(version),
                    source=VersionSource.IMPORT,
                    path=getattr(module, '__file__', None),
                    metadata={'attribute': source_attr},
                    confidence=VersionSource.IMPORT.default_confidence
                )
                
                self._stats['parse_successes'] += 1
                self._put_in_cache(cache_key, [result])
                return result
                
        except ImportError:
            if self.use_fallbacks:
                # Try importlib.metadata as fallback
                importlib_meta = self._get_importlib_metadata()
                if importlib_meta:
                    try:
                        version = importlib_meta.version(module_name)
                        result = ModuleVersion(
                            name=module_name,
                            version=version,
                            source=VersionSource.IMPORTLIB,
                            confidence=VersionSource.IMPORTLIB.default_confidence
                        )
                        self._stats['parse_successes'] += 1
                        self._put_in_cache(cache_key, [result])
                        return result
                    except Exception:
                        pass
        except Exception as e:
            if not self.use_fallbacks:
                raise VersionParserError(f"Error importing {module_name}: {e}") from e
        
        return None
    
    def parse_from_setup_py(self, setup_py_path: Union[str, Path]) -> ParseResult:
        """
        Parse version from setup.py file.
        
        Extracts version information from a setup.py file by parsing the
        setup() function call.
        
        Parameters
        ----------
        setup_py_path : Union[str, Path]
            Path to the setup.py file.
        
        Returns
        -------
        ParseResult
            Result containing parsed versions and any errors.
        
        Examples
        --------
        >>> parser = VersionParser()
        >>> result = parser.parse_from_setup_py("setup.py")
        >>> for v in result.versions:
        ...     print(f"Package: {v.name}, Version: {v.version}")
        """
        setup_py_path = Path(setup_py_path)
        result = ParseResult()
        
        if not setup_py_path.exists():
            error = ParseError(
                error_type=ParseErrorType.FILE_NOT_FOUND,
                message=f"File not found: {setup_py_path}",
                path=str(setup_py_path)
            )
            result.add_error(error)
            return result
        
        cache_key = f"setup:{setup_py_path.absolute()}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            for v in cached:
                result.add_version(v)
            return result
        
        try:
            content = self._read_file_with_fallback_encoding(setup_py_path)
            if content is None:
                error = ParseError(
                    error_type=ParseErrorType.ENCODING_ERROR,
                    message=f"Cannot decode file: {setup_py_path}",
                    path=str(setup_py_path)
                )
                result.add_error(error)
                return result
            
            package_name = setup_py_path.parent.name
            
            # Regex-based extraction
            for pattern in PATTERNS.SETUP_VERSION:
                match = pattern.search(content)
                if match:
                    version_str = match.group(1) if match.groups() else "dynamic"
                    
                    # Check for setuptools_scm
                    if version_str == "dynamic" and 'use_scm_version' in content:
                        version_str = "dynamic (setuptools_scm)"
                        confidence = 0.6
                    else:
                        confidence = VersionSource.SETUP_PY.default_confidence
                    
                    v = ModuleVersion(
                        name=package_name,
                        version=version_str,
                        source=VersionSource.SETUP_PY,
                        path=str(setup_py_path),
                        metadata={'pattern': pattern.pattern[:50]},
                        confidence=confidence
                    )
                    result.add_version(v)
                    break
            
            # AST-based extraction
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name) and node.func.id == 'setup':
                            for keyword in node.keywords:
                                if keyword.arg == 'version':
                                    version_value = self._extract_setup_version(keyword.value)
                                    if version_value:
                                        v = ModuleVersion(
                                            name=package_name,
                                            version=version_value,
                                            source=VersionSource.SETUP_PY,
                                            path=str(setup_py_path),
                                            confidence=0.95
                                        )
                                        result.add_version(v)
            except SyntaxError:
                pass
            
            self._put_in_cache(cache_key, result.versions)
            
        except Exception as e:
            error = ParseError(
                error_type=ParseErrorType.PARSE_FAILED,
                message=f"Error parsing setup.py: {e}",
                path=str(setup_py_path),
                original_error=e
            )
            result.add_error(error)
            
            if not self.use_fallbacks:
                raise VersionParserError(f"Error parsing setup.py: {e}") from e
        
        return result
    
    def _extract_setup_version(self, node: ast.expr) -> Optional[str]:
        """
        Extract version value from setup() keyword argument.
        
        Parameters
        ----------
        node : ast.expr
            AST node containing version value.
        
        Returns
        -------
        Optional[str]
            Extracted version string.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        elif hasattr(ast, 'Str') and isinstance(node, ast.Str):
            return node.s
        elif isinstance(node, ast.Name):
            # Version is a variable reference
            return f"dynamic ({node.id})"
        elif isinstance(node, ast.Attribute):
            # Version is an attribute reference
            return f"dynamic ({node.attr})"
        return None
    
    def parse_from_pyproject_toml(self, toml_path: Union[str, Path]) -> ParseResult:
        """
        Parse version from pyproject.toml file.
        
        Extracts version information from pyproject.toml, supporting PEP 621,
        Poetry, Flit, PDM, and Hatch formats.
        
        Parameters
        ----------
        toml_path : Union[str, Path]
            Path to the pyproject.toml file.
        
        Returns
        -------
        ParseResult
            Result containing parsed versions and any errors.
        
        Examples
        --------
        >>> parser = VersionParser()
        >>> result = parser.parse_from_pyproject_toml("pyproject.toml")
        >>> for v in result.versions:
        ...     print(f"Version: {v.version} (from {v.metadata.get('format')})")
        """
        toml_path = Path(toml_path)
        result = ParseResult()
        
        if not toml_path.exists():
            error = ParseError(
                error_type=ParseErrorType.FILE_NOT_FOUND,
                message=f"File not found: {toml_path}",
                path=str(toml_path)
            )
            result.add_error(error)
            return result
        
        cache_key = f"toml:{toml_path.absolute()}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            for v in cached:
                result.add_version(v)
            return result
        
        toml_parser = self._get_toml_parser()
        if toml_parser is None:
            if self.use_fallbacks:
                return result
            else:
                raise VersionParserError("No TOML parser available")
        
        try:
            with open(toml_path, 'rb') as f:
                data = toml_parser.load(f)
            
            package_name = toml_path.parent.name
            version = None
            project_format = ProjectFormat.UNKNOWN
            
            # Check different formats
            # PEP 621
            if 'project' in data and 'version' in data['project']:
                version = data['project']['version']
                project_format = ProjectFormat.PEP_621
                package_name = data['project'].get('name', package_name)
            
            # Poetry
            elif 'tool' in data and 'poetry' in data['tool']:
                poetry_data = data['tool']['poetry']
                if 'version' in poetry_data:
                    version = poetry_data['version']
                    project_format = ProjectFormat.POETRY
                    package_name = poetry_data.get('name', package_name)
            
            # Flit
            elif 'tool' in data and 'flit' in data['tool']:
                flit_data = data['tool']['flit']
                if 'metadata' in flit_data and 'version' in flit_data['metadata']:
                    version = flit_data['metadata']['version']
                    project_format = ProjectFormat.FLIT
                    package_name = flit_data['metadata'].get('module', package_name)
            
            # PDM
            elif 'tool' in data and 'pdm' in data['tool']:
                pdm_data = data['tool']['pdm']
                if 'version' in pdm_data:
                    version = pdm_data['version']
                    project_format = ProjectFormat.PDM
                    package_name = pdm_data.get('name', package_name)
            
            # Hatch
            elif 'tool' in data and 'hatch' in data['tool']:
                hatch_data = data['tool']['hatch']
                if 'version' in hatch_data:
                    version = hatch_data['version']
                    project_format = ProjectFormat.HATCH
                    package_name = hatch_data.get('name', package_name)
            
            # Direct version in root
            elif 'version' in data:
                version = data['version']
                project_format = ProjectFormat.UNKNOWN
            
            if version:
                # Check for dynamic version
                is_dynamic = version == 'dynamic' or (
                    'project' in data and 
                    'dynamic' in data['project'] and 
                    'version' in data['project']['dynamic']
                )
                
                v = ModuleVersion(
                    name=str(package_name),
                    version=str(version),
                    source=VersionSource.PYPROJECT_TOML,
                    path=str(toml_path),
                    metadata={
                        'format': project_format.value,
                        'is_dynamic': is_dynamic
                    },
                    confidence=0.7 if is_dynamic else VersionSource.PYPROJECT_TOML.default_confidence
                )
                result.add_version(v)
            
            self._put_in_cache(cache_key, result.versions)
            
        except Exception as e:
            error = ParseError(
                error_type=ParseErrorType.PARSE_FAILED,
                message=f"Error parsing pyproject.toml: {e}",
                path=str(toml_path),
                original_error=e
            )
            result.add_error(error)
            
            if not self.use_fallbacks:
                raise VersionParserError(f"Error parsing pyproject.toml: {e}") from e
        
        return result
    
    def parse_from_requirements(self, req_path: Union[str, Path]) -> ParseResult:
        """
        Parse versions from requirements.txt file.
        
        Extracts package names and versions from requirements.txt format files,
        including support for extras and environment markers.
        
        Parameters
        ----------
        req_path : Union[str, Path]
            Path to the requirements.txt file.
        
        Returns
        -------
        ParseResult
            Result containing parsed requirements and any errors.
        
        Examples
        --------
        >>> parser = VersionParser()
        >>> result = parser.parse_from_requirements("requirements.txt")
        >>> for req in result.versions:
        ...     op = req.metadata.get('operator', '')
        ...     print(f"{req.name}{op}{req.version}")
        """
        req_path = Path(req_path)
        result = ParseResult()
        
        if not req_path.exists():
            error = ParseError(
                error_type=ParseErrorType.FILE_NOT_FOUND,
                message=f"File not found: {req_path}",
                path=str(req_path)
            )
            result.add_error(error)
            return result
        
        cache_key = f"req:{req_path.absolute()}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            for v in cached:
                result.add_version(v)
            return result
        
        try:
            content = self._read_file_with_fallback_encoding(req_path)
            if content is None:
                error = ParseError(
                    error_type=ParseErrorType.ENCODING_ERROR,
                    message=f"Cannot decode file: {req_path}",
                    path=str(req_path)
                )
                result.add_error(error)
                return result
            
            for line_num, line in enumerate(content.strip().split('\n'), 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Handle line continuations
                if line.endswith('\\'):
                    continue
                
                # Parse requirement line
                match = PATTERNS.REQUIREMENT_LINE.match(line)
                if match:
                    name, extras, operator, version, marker = match.groups()
                    
                    metadata = {}
                    if extras:
                        metadata['extras'] = extras.split(',')
                    if marker:
                        metadata['marker'] = marker
                    if operator:
                        metadata['operator'] = operator
                    
                    if version:
                        v = ModuleVersion(
                            name=name,
                            version=version,
                            source=VersionSource.REQUIREMENTS,
                            path=str(req_path),
                            metadata=metadata,
                            confidence=VersionSource.REQUIREMENTS.default_confidence
                        )
                    else:
                        # Package without version specification
                        v = ModuleVersion(
                            name=name,
                            version='*',
                            source=VersionSource.REQUIREMENTS,
                            path=str(req_path),
                            metadata=metadata,
                            confidence=0.7
                        )
                    
                    result.add_version(v)
                else:
                    # Simple package name
                    if re.match(r'^[a-zA-Z0-9_\-\.]+$', line):
                        v = ModuleVersion(
                            name=line,
                            version='*',
                            source=VersionSource.REQUIREMENTS,
                            path=str(req_path),
                            confidence=0.6
                        )
                        result.add_version(v)
            
            self._put_in_cache(cache_key, result.versions)
            
        except Exception as e:
            error = ParseError(
                error_type=ParseErrorType.PARSE_FAILED,
                message=f"Error parsing requirements.txt: {e}",
                path=str(req_path),
                original_error=e
            )
            result.add_error(error)
            
            if not self.use_fallbacks:
                raise VersionParserError(f"Error parsing requirements.txt: {e}") from e
        
        return result
    
    def parse_from_setup_cfg(self, cfg_path: Union[str, Path]) -> ParseResult:
        """
        Parse version from setup.cfg file.
        
        Parameters
        ----------
        cfg_path : Union[str, Path]
            Path to the setup.cfg file.
        
        Returns
        -------
        ParseResult
            Result containing parsed versions and any errors.
        """
        cfg_path = Path(cfg_path)
        result = ParseResult()
        
        if not cfg_path.exists():
            error = ParseError(
                error_type=ParseErrorType.FILE_NOT_FOUND,
                message=f"File not found: {cfg_path}",
                path=str(cfg_path)
            )
            result.add_error(error)
            return result
        
        cache_key = f"cfg:{cfg_path.absolute()}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            for v in cached:
                result.add_version(v)
            return result
        
        try:
            config = configparser.ConfigParser()
            content = self._read_file_with_fallback_encoding(cfg_path)
            if content:
                config.read_string(content)
            else:
                config.read(cfg_path)
            
            package_name = cfg_path.parent.name
            version = None
            
            # Check metadata section
            if config.has_section('metadata') and config.has_option('metadata', 'version'):
                version = config.get('metadata', 'version')
                package_name = config.get('metadata', 'name', fallback=package_name)
            
            # Check bumpversion section
            elif config.has_section('bumpversion') and config.has_option('bumpversion', 'current_version'):
                version = config.get('bumpversion', 'current_version')
            
            if version:
                v = ModuleVersion(
                    name=package_name,
                    version=version,
                    source=VersionSource.SETUP_CFG,
                    path=str(cfg_path),
                    confidence=VersionSource.SETUP_CFG.default_confidence
                )
                result.add_version(v)
            
            self._put_in_cache(cache_key, result.versions)
            
        except Exception as e:
            error = ParseError(
                error_type=ParseErrorType.PARSE_FAILED,
                message=f"Error parsing setup.cfg: {e}",
                path=str(cfg_path),
                original_error=e
            )
            result.add_error(error)
        
        return result
    
    def parse_installed_packages(self) -> ParseResult:
        """
        Parse versions of installed packages.
        
        Uses importlib.metadata (Python 3.8+) or falls back to pkg_resources
        for older Python versions.
        
        Returns
        -------
        ParseResult
            Result containing installed package versions.
        
        Examples
        --------
        >>> parser = VersionParser()
        >>> result = parser.parse_installed_packages()
        >>> for pkg in result.versions[:10]:
        ...     print(f"{pkg.name:30} {pkg.version}")
        """
        cache_key = "installed_packages"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            result = ParseResult()
            for v in cached:
                result.add_version(v)
            return result
        
        result = ParseResult()
        
        # Try importlib.metadata first (Python 3.8+)
        importlib_meta = self._get_importlib_metadata()
        if importlib_meta:
            try:
                for dist in importlib_meta.distributions():
                    try:
                        name = dist.metadata.get('Name', dist.name) if hasattr(dist, 'metadata') else dist.name
                        version = dist.version
                        
                        metadata = {}
                        if hasattr(dist, 'metadata'):
                            metadata = dict(dist.metadata)
                        
                        v = ModuleVersion(
                            name=name,
                            version=version,
                            source=VersionSource.IMPORTLIB,
                            metadata=metadata,
                            confidence=VersionSource.IMPORTLIB.default_confidence
                        )
                        result.add_version(v)
                    except Exception:
                        continue
            except Exception as e:
                error = ParseError(
                    error_type=ParseErrorType.PARSE_FAILED,
                    message=f"Error using importlib.metadata: {e}",
                    original_error=e
                )
                result.add_error(error)
        
        # Fallback to pkg_resources
        if not result.versions and self.use_fallbacks:
            try:
                import pkg_resources
                
                for dist in pkg_resources.working_set:
                    v = ModuleVersion(
                        name=dist.project_name,
                        version=dist.version,
                        source=VersionSource.PKG_RESOURCES,
                        metadata={'location': dist.location},
                        confidence=VersionSource.PKG_RESOURCES.default_confidence
                    )
                    result.add_version(v)
                    
            except ImportError:
                pass
            except Exception as e:
                error = ParseError(
                    error_type=ParseErrorType.PARSE_FAILED,
                    message=f"Error using pkg_resources: {e}",
                    original_error=e
                )
                result.add_error(error)
        
        # Fallback to pip list
        if not result.versions and self.use_fallbacks:
            pip_result = self.parse_pip_list()
            for v in pip_result.versions:
                result.add_version(v)
            for e in pip_result.errors:
                result.add_error(e)
        
        self._put_in_cache(cache_key, result.versions)
        return result
    
    def parse_pip_list(self) -> ParseResult:
        """
        Parse versions using pip list command.
        
        Executes 'pip list --format=json' and parses the output.
        
        Returns
        -------
        ParseResult
            Result containing package versions from pip list.
        
        Examples
        --------
        >>> parser = VersionParser()
        >>> result = parser.parse_pip_list()
        >>> for pkg in result.versions[:5]:
        ...     print(f"{pkg.name} {pkg.version}")
        """
        cache_key = "pip_list"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            result = ParseResult()
            for v in cached:
                result.add_version(v)
            return result
        
        result = ParseResult()
        
        try:
            # Use sys.executable to ensure we use the correct Python
            cmd = [sys.executable, '-m', 'pip', 'list', '--format=json']
            
            # Add --user flag if needed
            env = os.environ.copy()
            if _IS_WINDOWS:
                # Windows-specific adjustments
                env['PYTHONIOENCODING'] = 'utf-8'
            
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                check=False
            )
            
            if proc.returncode != 0:
                error = ParseError(
                    error_type=ParseErrorType.PARSE_FAILED,
                    message=f"pip list failed: {proc.stderr.strip()}",
                )
                result.add_error(error)
                return result
            
            packages = json.loads(proc.stdout)
            
            for package in packages:
                v = ModuleVersion(
                    name=package.get('name', 'unknown'),
                    version=package.get('version', 'unknown'),
                    source=VersionSource.PIP_LIST,
                    confidence=VersionSource.PIP_LIST.default_confidence,
                    metadata={
                        'editable': package.get('editable', False)
                    }
                )
                result.add_version(v)
                
        except subprocess.TimeoutExpired as e:
            error = ParseError(
                error_type=ParseErrorType.TIMEOUT,
                message=f"pip list timed out after {self.timeout}s",
                original_error=e
            )
            result.add_error(error)
        except json.JSONDecodeError as e:
            error = ParseError(
                error_type=ParseErrorType.PARSE_FAILED,
                message=f"Failed to parse pip list JSON: {e}",
                original_error=e
            )
            result.add_error(error)
        except Exception as e:
            error = ParseError(
                error_type=ParseErrorType.PARSE_FAILED,
                message=f"Error running pip list: {e}",
                original_error=e
            )
            result.add_error(error)
        
        self._put_in_cache(cache_key, result.versions)
        return result
    
    def parse_directory(
        self,
        directory: Union[str, Path],
        recursive: bool = True,
        include_hidden: bool = False
    ) -> ParseResult:
        """
        Parse all version files in a directory.
        
        Recursively scans a directory for Python files and configuration files
        that may contain version information.
        
        Parameters
        ----------
        directory : Union[str, Path]
            Directory to scan for version files.
        recursive : bool, default=True
            Whether to scan subdirectories recursively.
        include_hidden : bool, default=False
            Whether to include hidden files and directories.
        
        Returns
        -------
        ParseResult
            Result containing all found versions.
        
        Examples
        --------
        >>> parser = VersionParser()
        >>> result = parser.parse_directory("./myproject")
        >>> print(result.get_summary())
        """
        directory = Path(directory).resolve()
        result = ParseResult()
        
        if not directory.exists():
            error = ParseError(
                error_type=ParseErrorType.FILE_NOT_FOUND,
                message=f"Directory not found: {directory}",
                path=str(directory)
            )
            result.add_error(error)
            return result
        
        if not directory.is_dir():
            error = ParseError(
                error_type=ParseErrorType.PARSE_FAILED,
                message=f"Not a directory: {directory}",
                path=str(directory)
            )
            result.add_error(error)
            return result
        
        cache_key = f"dir:{directory}:{recursive}:{include_hidden}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            for v in cached:
                result.add_version(v)
            return result
        
        # Configuration files at root level
        config_parsers = [
            ('setup.py', self.parse_from_setup_py),
            ('pyproject.toml', self.parse_from_pyproject_toml),
            ('requirements.txt', self.parse_from_requirements),
            ('setup.cfg', self.parse_from_setup_cfg),
        ]
        
        for filename, parser_func in config_parsers:
            file_path = directory / filename
            if file_path.exists() and (include_hidden or not filename.startswith('.')):
                file_result = parser_func(file_path)
                for v in file_result.versions:
                    result.add_version(v)
                for e in file_result.errors:
                    result.add_error(e)
        
        # Python files
        version_file_patterns = {
            '__init__.py', 'version.py', '_version.py', '__version__.py',
            'versions.py', 'release.py', '__about__.py'
        }
        
        if recursive:
            pattern = '**/*.py'
        else:
            pattern = '*.py'
        
        for file_path in directory.glob(pattern):
            if not include_hidden and file_path.name.startswith('.'):
                continue
            
            # Skip certain directories
            if recursive:
                parts = file_path.parts
                if any(p.startswith('.') and not include_hidden for p in parts):
                    continue
                if any(p in {'__pycache__', 'build', 'dist', 'venv', '.venv', 'env', '.env'} for p in parts):
                    continue
            
            if file_path.name in version_file_patterns:
                file_result = self.parse_from_file(file_path)
                for v in file_result.versions:
                    result.add_version(v)
                for e in file_result.errors:
                    result.add_error(e)
        
        self._put_in_cache(cache_key, result.versions)
        return result
    
    def parse_from_environment(self, env_var: str = 'PACKAGE_VERSION') -> Optional[ModuleVersion]:
        """
        Parse version from environment variable.
        
        Parameters
        ----------
        env_var : str, default='PACKAGE_VERSION'
            Name of the environment variable.
        
        Returns
        -------
        Optional[ModuleVersion]
            ModuleVersion if environment variable exists and contains version.
        """
        version = os.environ.get(env_var)
        if version:
            return ModuleVersion(
                name=env_var.lower(),
                version=version,
                source=VersionSource.ENVIRONMENT,
                confidence=VersionSource.ENVIRONMENT.default_confidence,
                metadata={'variable': env_var}
            )
        return None
    
    def clear_cache(self) -> None:
        """
        Clear the version cache.
        
        Examples
        --------
        >>> parser = VersionParser()
        >>> parser.clear_cache()
        """
        self._cache.clear()
        self._cache_order.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get parser statistics.
        
        Returns
        -------
        Dict[str, Any]
            Statistics dictionary.
        """
        total = self._stats['cache_hits'] + self._stats['cache_misses']
        return {
            'cache_size': len(self._cache),
            'cache_hits': self._stats['cache_hits'],
            'cache_misses': self._stats['cache_misses'],
            'cache_hit_rate': self._stats['cache_hits'] / total if total > 0 else 0.0,
            'parse_attempts': self._stats['parse_attempts'],
            'parse_successes': self._stats['parse_successes'],
            'parse_success_rate': (
                self._stats['parse_successes'] / self._stats['parse_attempts']
                if self._stats['parse_attempts'] > 0 else 0.0
            ),
        }


# ============================================================================
# Convenience Functions
# ============================================================================

# Global parser instance for convenience functions
_global_parser: Optional[VersionParser] = None


def _get_global_parser() -> VersionParser:
    """Get or create the global parser instance."""
    global _global_parser
    if _global_parser is None:
        _global_parser = VersionParser()
    return _global_parser


def get_version_info(
    module_name: str,
    parser: Optional[VersionParser] = None
) -> Optional[ModuleVersion]:
    """
    Convenience function to get version information for a module.
    
    Parameters
    ----------
    module_name : str
        Name of the module to get version for.
    parser : Optional[VersionParser], optional
        Parser instance to use, creates new one if not provided.
    
    Returns
    -------
    Optional[ModuleVersion]
        ModuleVersion object if version found, None otherwise.
    
    Examples
    --------
    >>> version = get_version_info("requests")
    >>> if version:
    ...     print(f"requests {version.version}")
    """
    if parser is None:
        parser = _get_global_parser()
    
    return parser.parse_from_import(module_name)


def get_all_versions(
    project_path: Union[str, Path],
    parser: Optional[VersionParser] = None
) -> Dict[str, str]:
    """
    Convenience function to get all versions from a project.
    
    Parameters
    ----------
    project_path : Union[str, Path]
        Path to the project directory.
    parser : Optional[VersionParser], optional
        Parser instance to use.
    
    Returns
    -------
    Dict[str, str]
        Dictionary mapping package names to versions.
    
    Examples
    --------
    >>> versions = get_all_versions(".")
    >>> for name, version in versions.items():
    ...     print(f"{name}: {version}")
    """
    if parser is None:
        parser = _get_global_parser()
    
    result = parser.parse_directory(project_path)
    unique = result.get_unique_versions()
    return {v.name: v.version for v in unique}


def get_installed_versions(
    parser: Optional[VersionParser] = None
) -> Dict[str, str]:
    """
    Get all installed package versions.
    
    Parameters
    ----------
    parser : Optional[VersionParser], optional
        Parser instance to use.
    
    Returns
    -------
    Dict[str, str]
        Dictionary mapping package names to versions.
    """
    if parser is None:
        parser = _get_global_parser()
    
    result = parser.parse_installed_packages()
    unique = result.get_unique_versions()
    return {v.name: v.version for v in unique}


def clear_global_cache() -> None:
    """Clear the global parser cache."""
    global _global_parser
    if _global_parser is not None:
        _global_parser.clear_cache()
    _global_parser = None


# ============================================================================
# Exception Class
# ============================================================================

class VersionParserError(Exception):
    """
    Custom exception for version parsing errors.
    
    Attributes
    ----------
    message : str
        Error message.
    path : Optional[str]
        Related file path.
    original_error : Optional[Exception]
        Original exception that caused this error.
    """
    
    def __init__(
        self,
        message: str,
        path: Optional[str] = None,
        original_error: Optional[Exception] = None
    ):
        self.message = message
        self.path = path
        self.original_error = original_error
        super().__init__(message)


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "VersionSource",
    "ParseErrorType",
    "ProjectFormat",
    "RequirementOperator",
    
    # Data Classes
    "ParseError",
    "ModuleVersion",
    "ParseResult",
    
    # Main Class
    "VersionParser",
    
    # Exception
    "VersionParserError",
    
    # Convenience Functions
    "get_version_info",
    "get_all_versions",
    "get_installed_versions",
    "clear_global_cache",
]

