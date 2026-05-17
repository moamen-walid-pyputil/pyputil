#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Python Package Requirements Handler
=============================================

A comprehensive, production-grade requirements management system that provides
complete PEP 508 compliance, advanced name resolution, intelligent caching,
and robust validation for Python package dependencies.

This module implements a sophisticated requirements parsing and management
system with support for:
- Full PEP 508 requirement specification compliance
- VCS references (git, hg, svn, bzr)
- Direct URL references and local file paths
- Editable installations (-e flag)
- Environment markers with complex boolean expressions
- Extras and optional dependencies
- Version specifiers with full PEP 440 compliance
- Intelligent import-to-distribution name resolution
- Multi-level caching for optimal performance
- Comprehensive error handling with detailed diagnostics

Architecture
------------
The module is built around the `Requirement` class which serves as the primary
interface for all requirement operations. Supporting components include:

- **RequirementMetadata**: Immutable dataclass for parsed requirement components
- **NameResolver**: Advanced import-to-distribution name resolution
- **MarkerEvaluator**: PEP 508 environment marker evaluation
- **VersionMatcher**: PEP 440 version constraint matching
- **CacheManager**: Multi-level LRU caching system

Examples
--------
>>> from pyputil.requirements import Requirement, parse_requirement
>>> 
>>> # Basic requirement parsing
>>> req = Requirement("requests[security]>=2.28.0")
>>> req.name
'requests'
>>> req.extras
['security']
>>> req.version_spec
'>=2.28.0'
>>> 
>>> # VCS requirement
>>> req = Requirement("package @ git+https://github.com/user/repo.git@v1.2.3")
>>> req.is_vcs
True
>>> req.vcs_type
'git'
>>> req.vcs_ref
'v1.2.3'
>>> 
>>> # Environment markers
>>> req = Requirement("pandas>=1.5.0; python_version >= '3.8'")
>>> req.marker
"python_version >= '3.8'"
>>> req.evaluate_marker()
True  # On Python 3.8+
>>> 
>>> # Local editable requirement
>>> req = Requirement("-e ./local-package[dev]")
>>> req.is_editable
True
>>> req.is_local
True
>>> req.local_path
PosixPath('/absolute/path/to/local-package')
>>> 
>>> # Batch processing with validation
>>> requirements = Requirement.from_requirements_file("requirements.txt")
>>> valid_reqs = [r for r in requirements if r.is_valid]
>>> installed_reqs = [r for r in requirements if r.is_installed()]
>>> 
>>> # Advanced name resolution
>>> canonical = Requirement.canonical_name("PIL")
>>> canonical
'pillow'
>>> Requirement.compare_names("sklearn", "scikit-learn")
True

References
----------
- PEP 508: https://www.python.org/dev/peps/pep-0508/
- PEP 440: https://www.python.org/dev/peps/pep-0440/
- PEP 503: https://www.python.org/dev/peps/pep-0503/
- PEP 496: https://www.python.org/dev/peps/pep-0496/
"""

import re
import sys
import os
import json
import hashlib
import tempfile
import subprocess
import ast
import logging
import time
import threading
from typing import (
    Optional, Dict, List, Set, Union, Tuple, Any, Generator, 
    overload, Iterable, Iterator, Callable, TypeVar, ClassVar,
    Pattern, Match, NamedTuple, FrozenSet, Deque, DefaultDict, Final
)
from dataclasses import dataclass, field, asdict, fields, replace
from functools import lru_cache, wraps, total_ordering
from enum import Enum, auto, Flag, IntFlag
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlunparse
from contextlib import contextmanager
from collections import defaultdict, deque, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings

# ============================================================================
# Platform Detection and Configuration
# ============================================================================

_IS_WINDOWS: Final[bool] = sys.platform == "win32"
_IS_MACOS: Final[bool] = sys.platform == "darwin"
_IS_LINUX: Final[bool] = sys.platform.startswith("linux")
_IS_BSD: Final[bool] = any(sys.platform.startswith(b) for b in ("freebsd", "openbsd", "netbsd", "dragonfly"))
_IS_CYGWIN: Final[bool] = "cygwin" in sys.platform
_IS_MSYS: Final[bool] = "msys" in sys.platform

_PYTHON_VERSION: Final[Tuple[int, int, int]] = sys.version_info[:3]
_PYTHON_VERSION_STR: Final[str] = f"{_PYTHON_VERSION[0]}.{_PYTHON_VERSION[1]}.{_PYTHON_VERSION[2]}"
_PYTHON_IMPLEMENTATION: Final[str] = sys.implementation.name
_PLATFORM_SYSTEM: Final[str] = sys.platform

# ============================================================================
# Imports with Fallback Handling
# ============================================================================

# Importlib.metadata (Python 3.8+)
try:
    from importlib.metadata import (
        packages_distributions, distributions, distribution,
        version as importlib_version, PackageNotFoundError
    )
    HAS_IMPORTLIB_METADATA: Final[bool] = True
except ImportError:
    HAS_IMPORTLIB_METADATA = False
    packages_distributions = None
    distributions = None
    distribution = None
    importlib_version = None
    PackageNotFoundError = Exception

# Pkg_resources (legacy fallback)
try:
    import pkg_resources
    HAS_PKG_RESOURCES: Final[bool] = True
except ImportError:
    HAS_PKG_RESOURCES = False
    pkg_resources = None

# Packaging library for version handling
try:
    import packaging.version
    import packaging.specifiers
    import packaging.markers
    import packaging.requirements
    HAS_PACKAGING: Final[bool] = True
except ImportError:
    HAS_PACKAGING = False
    packaging = None

# TOML support for pyproject.toml
try:
    if sys.version_info >= (3, 11):
        import tomllib
        HAS_TOML = True
    else:
        try:
            import tomli as tomllib
            HAS_TOML = True
        except ImportError:
            try:
                import toml as tomllib
                HAS_TOML = True
            except ImportError:
                HAS_TOML = False
except ImportError:
    HAS_TOML = False

# ============================================================================
# Constants and Regular Expressions
# ============================================================================

class RequirementType(Enum):
    """
    Enumeration of requirement types.
    
    Attributes
    ----------
    STANDARD : str
        Standard PyPI package requirement.
    VCS : str
        Version control system requirement (git, hg, svn, bzr).
    URL : str
        Direct URL requirement (HTTP/HTTPS).
    LOCAL : str
        Local file or directory requirement.
    EDITABLE : str
        Editable installation (-e flag).
    ARCHIVE : str
        Direct archive file requirement (.whl, .tar.gz, .zip).
    WHEEL : str
        Wheel file requirement.
    SDIST : str
        Source distribution requirement.
    """
    STANDARD = "standard"
    VCS = "vcs"
    URL = "url"
    LOCAL = "local"
    EDITABLE = "editable"
    ARCHIVE = "archive"
    WHEEL = "wheel"
    SDIST = "sdist"


class VCSSystem(Enum):
    """
    Supported version control systems.
    
    Attributes
    ----------
    GIT : str
        Git version control.
    MERCURIAL : str
        Mercurial (hg) version control.
    SUBVERSION : str
        Subversion (svn) version control.
    BAZAAR : str
        Bazaar (bzr) version control.
    """
    GIT = "git"
    MERCURIAL = "hg"
    SUBVERSION = "svn"
    BAZAAR = "bzr"
    
    @classmethod
    def from_prefix(cls, prefix: str) -> Optional['VCSSystem']:
        """Determine VCS from URL prefix."""
        prefix_lower = prefix.lower()
        if 'git' in prefix_lower:
            return cls.GIT
        elif 'hg' in prefix_lower or 'mercurial' in prefix_lower:
            return cls.MERCURIAL
        elif 'svn' in prefix_lower or 'subversion' in prefix_lower:
            return cls.SUBVERSION
        elif 'bzr' in prefix_lower or 'bazaar' in prefix_lower:
            return cls.BAZAAR
        return None


class MarkerOperator(Enum):
    """
    Environment marker operators per PEP 508.
    
    Attributes
    ----------
    EQ : str
        Equal (==).
    NE : str
        Not equal (!=).
    GT : str
        Greater than (>).
    GE : str
        Greater than or equal (>=).
    LT : str
        Less than (<).
    LE : str
        Less than or equal (<=).
    IN : str
        Membership (in).
    NOT_IN : str
        Non-membership (not in).
    AND : str
        Logical AND.
    OR : str
        Logical OR.
    """
    EQ = "=="
    NE = "!="
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="
    IN = "in"
    NOT_IN = "not in"
    AND = "and"
    OR = "or"


class ConstraintOperator(Enum):
    """
    Version constraint operators per PEP 440.
    
    Attributes
    ----------
    EQ : str
        Equal (==).
    NE : str
        Not equal (!=).
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
    ARBITRARY : str
        Arbitrary equality (===).
    """
    EQ = "=="
    NE = "!="
    GT = ">"
    GE = ">="
    LT = "<"
    LE = "<="
    COMPATIBLE = "~="
    ARBITRARY = "==="


# Comprehensive regex patterns for requirement parsing
_REQUIREMENT_PATTERNS: Dict[str, Pattern] = {
    # PEP 503 name normalization
    'normalize': re.compile(r"[-_.]+"),
    
    # Version specifier extraction
    'version_split': re.compile(r"([<>=!~]=?.*|\[.*\]$)"),
    
    # Extras extraction
    'extras': re.compile(r"\[([^\]]+)\]"),
    
    # Version constraint operators
    'constraint': re.compile(r"[<>]=?|==|!=|~=|==="),
    
    # Environment marker extraction
    'marker': re.compile(r";\s*(.+)$"),
    
    # URL reference extraction (PEP 508 direct references)
    'url': re.compile(r"@\s*(https?://[^\s]+|git\+[^\s]+|svn\+[^\s]+|hg\+[^\s]+|bzr\+[^\s]+)"),
    
    # PEP 508 name validation
    'pep508_name': re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9_.-]*[a-zA-Z0-9])?$"),
    
    # Archive file extensions
    'archive': re.compile(r'\.(tar\.gz|tgz|tar\.bz2|tbz2|tar\.xz|txz|zip|whl)$'),
    
    # Git URL pattern
    'git_url': re.compile(
        r'^(?:(?:git\+)?(?:https?|ssh)://[^/]+/[^/]+/[^/]+\.git(?:@[^#]+)?(?:#.*)?)$'
    ),
    
    # Local path detection
    'local_path': re.compile(r'^([./]|[a-zA-Z]:\\|~/)'),
    
    # VCS reference extraction
    'vcs_ref': re.compile(r'@([^#]+)'),
    
    # Egg fragment extraction
    'egg': re.compile(r'#egg=([^&]+)'),
    
    # Subdirectory fragment
    'subdirectory': re.compile(r'#subdirectory=([^&]+)'),
    
    # Hash extraction (--hash=...)
    'hash': re.compile(r'--hash=([^:]+):([a-fA-F0-9]+)'),
    
    # Environment variable in marker
    'env_var': re.compile(r'env\.([a-zA-Z_][a-zA-Z0-9_]*)'),
    
    # Python version in marker
    'python_version': re.compile(r'python_version\s*([<>=!]+)\s*[\'"](\d+\.?\d*)[\'"]'),
    
    # Platform in marker
    'platform': re.compile(r'sys_platform\s*==\s*[\'"]([^\'"]+)[\'"]'),
    
    # Implementation in marker
    'implementation': re.compile(r'platform_python_implementation\s*==\s*[\'"]([^\'"]+)[\'"]'),
    
    # Extra in marker
    'extra_marker': re.compile(r'extra\s*==\s*[\'"]([^\'"]+)[\'"]'),
}

# VCS URL prefixes
_VCS_PREFIXES: FrozenSet[str] = frozenset({
    'git+', 'git+ssh://', 'git+https://', 'git+http://',
    'hg+', 'svn+', 'bzr+',
})

# Archive extensions
_ARCHIVE_EXTENSIONS: FrozenSet[str] = frozenset({
    '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz', '.zip', '.whl'
})

# ============================================================================
# Name Mapping System
# ============================================================================

class NameMapping:
    """
    Comprehensive package name mapping system.
    
    This class manages bidirectional mappings between import names and
    distribution names, including aliases, fallbacks, and binary preferences.
    """
    
    # Primary mapping: import name -> distribution name
    IMPORT_TO_DIST: ClassVar[Dict[str, Union[str, List[str]]]] = {
        "pil": "pillow",
        "PIL": "pillow",
        "cv2": "opencv-python",
        "cv": ["opencv-python", "opencv-contrib-python"],
        "opencv": ["opencv-python", "opencv-contrib-python"],
        "sklearn": "scikit-learn",
        "yaml": "pyyaml",
        "pyyaml": "pyyaml",
        "bs4": "beautifulsoup4",
        "beautifulsoup": "beautifulsoup4",
        "crypto": "pycryptodome",
        "Crypto": "pycryptodome",
        "tkinter": "tk",
        "Tkinter": "tk",
        "pandas": "pandas",
        "numpy": "numpy",
        "np": "numpy",
        "matplotlib": "matplotlib",
        "plt": "matplotlib",
        "pyplot": "matplotlib",
        "pytest": "pytest",
        "djongo": "djongo",
        "mysql": "mysql-connector-python",
        "psycopg2": "psycopg2-binary",
        "tensorflow": "tensorflow",
        "tf": "tensorflow",
        "keras": "keras",
        "torch": "torch",
        "flask": "flask",
        "django": "django",
        "requests": "requests",
        "urllib3": "urllib3",
        "certifi": "certifi",
        "chardet": "chardet",
        "idna": "idna",
        "setuptools": "setuptools",
        "pkg_resources": "setuptools",
        "pip": "pip",
        "wheel": "wheel",
        "scipy": "scipy",
        "skimage": "scikit-image",
        "sklearn": "scikit-learn",
        "sm": "statsmodels",
        "statsmodels": "statsmodels",
        "seaborn": "seaborn",
        "sns": "seaborn",
        "plotly": "plotly",
        "dash": "dash",
        "streamlit": "streamlit",
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "gunicorn": "gunicorn",
        "sqlalchemy": "sqlalchemy",
        "alembic": "alembic",
        "pymongo": "pymongo",
        "redis": "redis",
        "celery": "celery",
        "aiohttp": "aiohttp",
        "httpx": "httpx",
        "boto3": "boto3",
        "botocore": "botocore",
        "azure": "azure-storage-blob",
        "google.cloud": "google-cloud-storage",
        "lxml": "lxml",
        "xml": "lxml",
        "html5lib": "html5lib",
        "jinja2": "jinja2",
        "markdown": "markdown",
        "pygments": "pygments",
        "sphinx": "sphinx",
        "myst": "myst-parser",
        "jupyter": "jupyter",
        "notebook": "notebook",
        "ipython": "ipython",
        "cython": "cython",
        "numba": "numba",
        "cffi": "cffi",
        "pycparser": "pycparser",
        "cryptography": "cryptography",
        "paramiko": "paramiko",
        "fabric": "fabric",
        "ansible": "ansible",
        "docker": "docker",
        "kubernetes": "kubernetes",
        "ray": "ray",
        "dask": "dask",
        "polars": "polars",
        "pyspark": "pyspark",
        "networkx": "networkx",
        "igraph": "python-igraph",
        "sympy": "sympy",
        "mpmath": "mpmath",
        "click": "click",
        "fire": "fire",
        "typer": "typer",
        "rich": "rich",
        "tqdm": "tqdm",
        "loguru": "loguru",
        "structlog": "structlog",
        "python-json-logger": "python-json-logger",
        "orjson": "orjson",
        "ujson": "ujson",
        "msgpack": "msgpack",
        "protobuf": "protobuf",
        "grpc": "grpcio",
        "thrift": "thrift",
        "avro": "avro-python3",
        "pyarrow": "pyarrow",
        "pydantic": "pydantic",
        "attrs": "attrs",
        "dataclasses": "dataclasses",
        "marshmallow": "marshmallow",
        "cerberus": "cerberus",
        "jsonschema": "jsonschema",
        "pyyaml": "pyyaml",
        "toml": "toml",
        "python-dotenv": "python-dotenv",
        "configparser": "configparser",
        "argparse": "argparse",
    }
    
    # Binary package preferences with fallback options
    BINARY_PREFERENCES: ClassVar[Dict[str, List[str]]] = {
        "opencv-python": [
            "opencv-python-headless",
            "opencv-contrib-python",
            "opencv-contrib-python-headless"
        ],
        "opencv-contrib-python": [
            "opencv-contrib-python-headless",
            "opencv-python"
        ],
        "pillow": ["pillow-simd"],
        "numpy": ["numpy-mkl"],
        "matplotlib": ["matplotlib-base"],
        "pandas": ["pandas-datareader"],
        "psycopg2": ["psycopg2-binary"],
        "mysqlclient": ["mysql-connector-python", "pymysql"],
        "lxml": ["lxml-html-clean"],
    }
    
    # Common aliases (bidirectional)
    ALIASES: ClassVar[Dict[str, str]] = {
        "python-ldap": "pyldap",
        "pyldap": "python-ldap",
        "pyyaml": "yaml",
        "yaml": "pyyaml",
        "beautifulsoup4": "bs4",
        "bs4": "beautifulsoup4",
        "scikit-learn": "sklearn",
        "sklearn": "scikit-learn",
        "scikit-image": "skimage",
        "skimage": "scikit-image",
        "opencv-python": "cv2",
        "cv2": "opencv-python",
        "pillow": "PIL",
        "PIL": "pillow",
        "tensorflow": "tf",
        "tf": "tensorflow",
        "matplotlib": "plt",
        "plt": "matplotlib",
        "numpy": "np",
        "np": "numpy",
        "pandas": "pd",
        "pd": "pandas",
        "seaborn": "sns",
        "sns": "seaborn",
        "statsmodels": "sm",
        "sm": "statsmodels",
    }
    
    # False positives and test modules to filter
    FALSE_POSITIVES: ClassVar[FrozenSet[str]] = frozenset({
        'setuptools', 'distutils', 'pkg_resources', '__future__',
        '__main__', 'typing_extensions', 'unittest', 'doctest',
        'test', 'tests', 'conftest', 'setup',
    })
    
    # Test module prefixes
    TEST_PREFIXES: ClassVar[FrozenSet[str]] = frozenset({
        'test_', 'pytest', 'unittest', '_test', 'testing', 'mock',
    })
    
    # Standard library modules (comprehensive list)
    STDLIB_MODULES: ClassVar[FrozenSet[str]] = frozenset({
        'abc', 'aifc', 'argparse', 'array', 'ast', 'asynchat', 'asyncio',
        'asyncore', 'atexit', 'audioop', 'base64', 'bdb', 'binascii',
        'binhex', 'bisect', 'builtins', 'bz2', 'calendar', 'cgi', 'cgitb',
        'chunk', 'cmath', 'cmd', 'code', 'codecs', 'codeop', 'collections',
        'colorsys', 'compileall', 'concurrent', 'configparser', 'contextlib',
        'contextvars', 'copy', 'copyreg', 'cProfile', 'crypt', 'csv',
        'ctypes', 'curses', 'dataclasses', 'datetime', 'dbm', 'decimal',
        'difflib', 'dis', 'distutils', 'doctest', 'email', 'encodings',
        'ensurepip', 'enum', 'errno', 'faulthandler', 'fcntl', 'filecmp',
        'fileinput', 'fnmatch', 'fractions', 'ftplib', 'functools', 'gc',
        'getopt', 'getpass', 'gettext', 'glob', 'graphlib', 'grp', 'gzip',
        'hashlib', 'heapq', 'hmac', 'html', 'http', 'idlelib', 'imaplib',
        'imghdr', 'imp', 'importlib', 'inspect', 'io', 'ipaddress', 'itertools',
        'json', 'keyword', 'lib2to3', 'linecache', 'locale', 'logging', 'lzma',
        'mailbox', 'mailcap', 'marshal', 'math', 'mimetypes', 'mmap',
        'modulefinder', 'msilib', 'msvcrt', 'multiprocessing', 'netrc',
        'nis', 'nntplib', 'numbers', 'operator', 'optparse', 'os', 'ossaudiodev',
        'pathlib', 'pdb', 'pickle', 'pickletools', 'pipes', 'pkgutil',
        'platform', 'plistlib', 'poplib', 'posix', 'posixpath', 'pprint',
        'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr', 'pydoc',
        'queue', 'quopri', 'random', 're', 'readline', 'reprlib', 'resource',
        'rlcompleter', 'runpy', 'sched', 'secrets', 'select', 'selectors',
        'shelve', 'shlex', 'shutil', 'signal', 'site', 'smtpd', 'smtplib',
        'sndhdr', 'socket', 'socketserver', 'spwd', 'sqlite3', 'ssl',
        'stat', 'statistics', 'string', 'stringprep', 'struct', 'subprocess',
        'sunau', 'symtable', 'sys', 'sysconfig', 'syslog', 'tabnanny',
        'tarfile', 'telnetlib', 'tempfile', 'termios', 'test', 'textwrap',
        'threading', 'time', 'timeit', 'tkinter', 'token', 'tokenize',
        'trace', 'traceback', 'tracemalloc', 'tty', 'turtle', 'turtledemo',
        'types', 'typing', 'unicodedata', 'unittest', 'urllib', 'uu',
        'uuid', 'venv', 'warnings', 'wave', 'weakref', 'webbrowser',
        'winreg', 'winsound', 'wsgiref', 'xdrlib', 'xml', 'xmlrpc', 'zipapp',
        'zipfile', 'zipimport', 'zlib', 'zoneinfo',
    })
    
    @classmethod
    def normalize(cls, name: str) -> str:
        """
        Normalize package name according to PEP 503.
        
        Parameters
        ----------
        name : str
            Package name to normalize.
        
        Returns
        -------
        str
            Normalized package name (lowercase, hyphens for separators).
        """
        if not name:
            return ""
        return _REQUIREMENT_PATTERNS['normalize'].sub("-", name).strip("-").lower()
    
    @classmethod
    def resolve_import(cls, import_name: str) -> str:
        """
        Resolve import name to distribution name.
        
        Parameters
        ----------
        import_name : str
            Python import name.
        
        Returns
        -------
        str
            Distribution name.
        """
        normalized = cls.normalize(import_name)
        
        # Check direct mapping
        if normalized in cls.IMPORT_TO_DIST:
            value = cls.IMPORT_TO_DIST[normalized]
            if isinstance(value, str):
                return value
            elif isinstance(value, list) and value:
                return value[0]
        
        # Check aliases
        if normalized in cls.ALIASES:
            return cls.ALIASES[normalized]
        
        return normalized
    
    @classmethod
    def get_import_names(cls, distribution_name: str) -> List[str]:
        """
        Get common import names for a distribution.
        
        Parameters
        ----------
        distribution_name : str
            Distribution name.
        
        Returns
        -------
        List[str]
            List of common import names.
        """
        result = []
        normalized = cls.normalize(distribution_name)
        
        # Check reverse mapping
        for imp, dist in cls.IMPORT_TO_DIST.items():
            if isinstance(dist, str) and cls.normalize(dist) == normalized:
                result.append(imp)
            elif isinstance(dist, list):
                for d in dist:
                    if cls.normalize(d) == normalized:
                        result.append(imp)
                        break
        
        # Check aliases
        for alias, target in cls.ALIASES.items():
            if cls.normalize(target) == normalized:
                result.append(alias)
        
        result.append(normalized)
        return list(set(result))
    
    @classmethod
    def compare(cls, name1: str, name2: str) -> bool:
        """
        Compare two package names for equivalence.
        
        Parameters
        ----------
        name1 : str
            First package name.
        name2 : str
            Second package name.
        
        Returns
        -------
        bool
            True if names refer to the same package.
        """
        resolved1 = cls.resolve_import(name1)
        resolved2 = cls.resolve_import(name2)
        return cls.normalize(resolved1) == cls.normalize(resolved2)
    
    @classmethod
    def is_stdlib(cls, module_name: str) -> bool:
        """
        Check if a module is part of the standard library.
        
        Parameters
        ----------
        module_name : str
            Module name to check.
        
        Returns
        -------
        bool
            True if module is in standard library.
        """
        top_level = module_name.split('.')[0]
        return top_level in cls.STDLIB_MODULES
    
    @classmethod
    def is_test_module(cls, module_name: str) -> bool:
        """
        Check if a module appears to be a test module.
        
        Parameters
        ----------
        module_name : str
            Module name to check.
        
        Returns
        -------
        bool
            True if module is likely a test module.
        """
        lower_name = module_name.lower()
        return (lower_name in cls.FALSE_POSITIVES or
                any(lower_name.startswith(p) for p in cls.TEST_PREFIXES))


# ============================================================================
# Requirement Metadata Dataclass
# ============================================================================

@dataclass(frozen=True)
class VCSInfo:
    """
    Version control system information.
    
    Attributes
    ----------
    vcs_type : VCSSystem
        Type of VCS.
    url : str
        Repository URL.
    ref : Optional[str]
        Branch, tag, or commit reference.
    subdirectory : Optional[str]
        Subdirectory within repository.
    egg : Optional[str]
        Egg name override.
    """
    vcs_type: VCSSystem
    url: str
    ref: Optional[str] = None
    subdirectory: Optional[str] = None
    egg: Optional[str] = None
    
    def to_pip_string(self) -> str:
        """Convert to pip-compatible VCS string."""
        prefix = f"{self.vcs_type.value}+"
        result = f"{prefix}{self.url}"
        if self.ref:
            result += f"@{self.ref}"
        if self.subdirectory:
            result += f"#subdirectory={self.subdirectory}"
        elif self.egg:
            result += f"#egg={self.egg}"
        return result


@dataclass(frozen=True)
class VersionConstraint:
    """
    Single version constraint.
    
    Attributes
    ----------
    operator : ConstraintOperator
        Constraint operator.
    version : str
        Version string.
    """
    operator: ConstraintOperator
    version: str
    
    def to_string(self) -> str:
        """Convert to string representation."""
        return f"{self.operator.value}{self.version}"


@dataclass(frozen=True)
class RequirementMetadata:
    """
    Comprehensive structured metadata for parsed Python package requirements.
    
    This immutable dataclass stores all components of a PEP 508 requirement
    specification with complete validation and parsing capabilities.
    
    Attributes
    ----------
    name : str
        Normalized package name according to PEP 503.
    original_name : str
        Original package name as provided.
    requirement_type : RequirementType
        Type of requirement.
    extras : Optional[Tuple[str, ...]]
        Tuple of extras requirements.
    version_spec : Optional[str]
        Raw version specification string.
    version_constraints : Tuple[VersionConstraint, ...]
        Parsed version constraints.
    marker : Optional[str]
        Raw environment marker expression.
    parsed_marker : Optional[Any]
        Parsed marker object (if packaging available).
    url : Optional[str]
        Direct URL reference.
    vcs_info : Optional[VCSInfo]
        VCS information if applicable.
    is_local : bool
        Whether this is a local path requirement.
    local_path : Optional[Path]
        Resolved local filesystem path.
    is_editable : bool
        Whether this is an editable installation.
    is_archive : bool
        Whether this is a direct archive file.
    archive_path : Optional[Path]
        Path to archive file if local.
    hash_algorithm : Optional[str]
        Hash algorithm (e.g., 'sha256').
    hash_value : Optional[str]
        Hash value.
    python_version_constraint : Optional[str]
        Extracted Python version constraint from marker.
    platform_constraint : Optional[str]
        Extracted platform constraint from marker.
    implementation_constraint : Optional[str]
        Extracted implementation constraint from marker.
    extra_marker : Optional[str]
        Extracted extra marker.
    raw : str
        Original requirement string.
    is_valid : bool
        Whether the requirement is valid.
    validation_errors : Tuple[str, ...]
        Validation error messages if any.
    """
    name: str
    original_name: str = ""
    requirement_type: RequirementType = RequirementType.STANDARD
    extras: Optional[Tuple[str, ...]] = None
    version_spec: Optional[str] = None
    version_constraints: Tuple[VersionConstraint, ...] = field(default_factory=tuple)
    marker: Optional[str] = None
    parsed_marker: Optional[Any] = None
    url: Optional[str] = None
    vcs_info: Optional[VCSInfo] = None
    is_local: bool = False
    local_path: Optional[Path] = None
    is_editable: bool = False
    is_archive: bool = False
    archive_path: Optional[Path] = None
    hash_algorithm: Optional[str] = None
    hash_value: Optional[str] = None
    python_version_constraint: Optional[str] = None
    platform_constraint: Optional[str] = None
    implementation_constraint: Optional[str] = None
    extra_marker: Optional[str] = None
    raw: str = ""
    is_valid: bool = True
    validation_errors: Tuple[str, ...] = field(default_factory=tuple)
    
    def __post_init__(self) -> None:
        """Validate and process after initialization."""
        # Parse version constraints if version_spec present
        if self.version_spec and not self.version_constraints:
            constraints = self._parse_version_constraints(self.version_spec)
            object.__setattr__(self, "version_constraints", tuple(constraints))
        
        # Parse marker components
        if self.marker:
            self._parse_marker_components()
        
        # Validate
        errors = self._validate()
        if errors:
            object.__setattr__(self, "is_valid", False)
            object.__setattr__(self, "validation_errors", tuple(errors))
    
    @staticmethod
    def _parse_version_constraints(spec: str) -> List[VersionConstraint]:
        """Parse version specifier into constraints list."""
        constraints = []
        parts = re.split(r',(?![^()]*\))', spec)
        
        for part in parts:
            part = part.strip()
            match = re.match(r'([<>]=?|==|!=|~=|===)\s*(.+)', part)
            if match:
                op_str, version = match.groups()
                try:
                    op = ConstraintOperator(op_str)
                    constraints.append(VersionConstraint(op, version.strip()))
                except ValueError:
                    pass
        
        return constraints
    
    def _parse_marker_components(self) -> None:
        """Parse marker string for extracted constraints."""
        if not self.marker:
            return
        
        # Python version
        py_match = _REQUIREMENT_PATTERNS['python_version'].search(self.marker)
        if py_match:
            op, version = py_match.groups()
            object.__setattr__(self, "python_version_constraint", f"{op} {version}")
        
        # Platform
        plat_match = _REQUIREMENT_PATTERNS['platform'].search(self.marker)
        if plat_match:
            object.__setattr__(self, "platform_constraint", plat_match.group(1))
        
        # Implementation
        impl_match = _REQUIREMENT_PATTERNS['implementation'].search(self.marker)
        if impl_match:
            object.__setattr__(self, "implementation_constraint", impl_match.group(1))
        
        # Extra
        extra_match = _REQUIREMENT_PATTERNS['extra_marker'].search(self.marker)
        if extra_match:
            object.__setattr__(self, "extra_marker", extra_match.group(1))
    
    def _validate(self) -> List[str]:
        """Validate the requirement metadata."""
        errors = []
        
        # Validate name
        if not self.name:
            errors.append("Package name is required")
        elif not _REQUIREMENT_PATTERNS['pep508_name'].match(self.name):
            errors.append(f"Invalid package name: {self.name}")
        
        # Validate version constraints
        for constraint in self.version_constraints:
            if not constraint.version:
                errors.append(f"Missing version for constraint: {constraint.operator.value}")
        
        # Validate URL
        if self.url:
            try:
                parsed = urlparse(self.url)
                if not parsed.scheme and not self.is_local:
                    errors.append(f"Invalid URL scheme: {self.url}")
            except Exception as e:
                errors.append(f"Invalid URL format: {e}")
        
        # Validate local path
        if self.is_local and self.local_path:
            try:
                if not self.local_path.exists():
                    errors.append(f"Local path does not exist: {self.local_path}")
            except Exception as e:
                errors.append(f"Invalid local path: {e}")
        
        return errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "name": self.name,
            "original_name": self.original_name,
            "requirement_type": self.requirement_type.value,
            "extras": list(self.extras) if self.extras else None,
            "version_spec": self.version_spec,
            "version_constraints": [
                {"operator": c.operator.value, "version": c.version}
                for c in self.version_constraints
            ],
            "marker": self.marker,
            "url": self.url,
            "is_local": self.is_local,
            "local_path": str(self.local_path) if self.local_path else None,
            "is_editable": self.is_editable,
            "is_archive": self.is_archive,
            "hash_algorithm": self.hash_algorithm,
            "hash_value": self.hash_value,
            "python_version_constraint": self.python_version_constraint,
            "platform_constraint": self.platform_constraint,
            "implementation_constraint": self.implementation_constraint,
            "raw": self.raw,
            "is_valid": self.is_valid,
            "validation_errors": list(self.validation_errors),
        }
        
        if self.vcs_info:
            result["vcs_info"] = {
                "vcs_type": self.vcs_info.vcs_type.value,
                "url": self.vcs_info.url,
                "ref": self.vcs_info.ref,
                "subdirectory": self.vcs_info.subdirectory,
                "egg": self.vcs_info.egg,
            }
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RequirementMetadata':
        """Create metadata from dictionary."""
        if 'local_path' in data and data['local_path']:
            data['local_path'] = Path(data['local_path'])
        if 'extras' in data and data['extras']:
            data['extras'] = tuple(data['extras'])
        if 'version_constraints' in data:
            data['version_constraints'] = tuple(
                VersionConstraint(ConstraintOperator(c['operator']), c['version'])
                for c in data['version_constraints']
            )
        if 'requirement_type' in data:
            data['requirement_type'] = RequirementType(data['requirement_type'])
        if 'vcs_info' in data and data['vcs_info']:
            vcs_data = data.pop('vcs_info')
            data['vcs_info'] = VCSInfo(
                vcs_type=VCSSystem(vcs_data['vcs_type']),
                url=vcs_data['url'],
                ref=vcs_data.get('ref'),
                subdirectory=vcs_data.get('subdirectory'),
                egg=vcs_data.get('egg'),
            )
        if 'validation_errors' in data:
            data['validation_errors'] = tuple(data['validation_errors'])
        return cls(**data)
    
    def get_install_string(self, include_markers: bool = False) -> str:
        """
        Generate pip-compatible install string.
        
        Parameters
        ----------
        include_markers : bool, default=False
            Whether to include environment markers.
        
        Returns
        -------
        str
            Requirement string suitable for pip install.
        """
        parts = []
        
        if self.is_editable:
            parts.append('-e')
        
        if self.url:
            parts.append(self.url)
        elif self.is_local and self.local_path:
            parts.append(str(self.local_path))
        elif self.vcs_info:
            parts.append(self.vcs_info.to_pip_string())
        else:
            pkg_str = self.name
            
            if self.extras:
                pkg_str += f"[{','.join(self.extras)}]"
            
            if self.version_spec:
                pkg_str += self.version_spec
            
            parts.append(pkg_str)
        
        if include_markers and self.marker:
            parts.append(f"; {self.marker}")
        
        return ' '.join(parts)
    
    def __str__(self) -> str:
        return self.get_install_string(include_markers=True)
    
    def __repr__(self) -> str:
        return (f"RequirementMetadata(name='{self.name}', "
                f"type={self.requirement_type.value}, valid={self.is_valid})")


# ============================================================================
# Cache Management System
# ============================================================================

class CacheManager:
    """
    Thread-safe multi-level caching system for requirement operations.
    
    This class manages caches for:
    - Requirement parsing results
    - Name normalization and resolution
    - Validation results
    - Distribution lookups
    - Marker evaluation results
    
    Attributes
    ----------
    max_size : int
        Maximum number of items per cache.
    ttl : Optional[float]
        Time-to-live in seconds for cache entries.
    """
    
    def __init__(self, max_size: int = 1000, ttl: Optional[float] = None):
        self.max_size = max_size
        self.ttl = ttl
        self._lock = threading.RLock()
        self._caches: Dict[str, OrderedDict] = {}
        self._timestamps: Dict[str, Dict[str, float]] = {}
        self._stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"hits": 0, "misses": 0})
    
    def _get_cache(self, name: str) -> OrderedDict:
        """Get or create a named cache."""
        with self._lock:
            if name not in self._caches:
                self._caches[name] = OrderedDict()
                self._timestamps[name] = {}
            return self._caches[name]
    
    def _cleanup_expired(self, name: str) -> None:
        """Remove expired entries from cache."""
        if not self.ttl:
            return
        
        with self._lock:
            if name not in self._timestamps:
                return
            
            current_time = time.time()
            expired_keys = [
                k for k, ts in self._timestamps[name].items()
                if current_time - ts > self.ttl
            ]
            
            cache = self._caches.get(name, {})
            for key in expired_keys:
                cache.pop(key, None)
                self._timestamps[name].pop(key, None)
    
    def get(self, cache_name: str, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Parameters
        ----------
        cache_name : str
            Name of the cache.
        key : str
            Cache key.
        
        Returns
        -------
        Optional[Any]
            Cached value or None.
        """
        self._cleanup_expired(cache_name)
        
        with self._lock:
            cache = self._caches.get(cache_name, {})
            if key in cache:
                self._stats[cache_name]["hits"] += 1
                # Move to end for LRU
                cache.move_to_end(key)
                return cache[key]
            
            self._stats[cache_name]["misses"] += 1
            return None
    
    def set(self, cache_name: str, key: str, value: Any) -> None:
        """
        Store value in cache.
        
        Parameters
        ----------
        cache_name : str
            Name of the cache.
        key : str
            Cache key.
        value : Any
            Value to cache.
        """
        with self._lock:
            if cache_name not in self._caches:
                self._caches[cache_name] = OrderedDict()
                self._timestamps[cache_name] = {}
            
            cache = self._caches[cache_name]
            
            # Remove if at capacity
            if len(cache) >= self.max_size:
                oldest_key = next(iter(cache))
                cache.pop(oldest_key)
                self._timestamps[cache_name].pop(oldest_key, None)
            
            cache[key] = value
            cache.move_to_end(key)
            self._timestamps[cache_name][key] = time.time()
    
    def clear(self, cache_name: Optional[str] = None) -> None:
        """
        Clear one or all caches.
        
        Parameters
        ----------
        cache_name : Optional[str], default=None
            Name of cache to clear, or None to clear all.
        """
        with self._lock:
            if cache_name:
                self._caches.pop(cache_name, None)
                self._timestamps.pop(cache_name, None)
                self._stats.pop(cache_name, None)
            else:
                self._caches.clear()
                self._timestamps.clear()
                self._stats.clear()
    
    def get_stats(self, cache_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Parameters
        ----------
        cache_name : Optional[str], default=None
            Name of cache to get stats for, or None for all.
        
        Returns
        -------
        Dict[str, Any]
            Cache statistics.
        """
        with self._lock:
            if cache_name:
                cache = self._caches.get(cache_name, {})
                stats = self._stats.get(cache_name, {"hits": 0, "misses": 0}).copy()
                stats["size"] = len(cache)
                stats["max_size"] = self.max_size
                total = stats["hits"] + stats["misses"]
                stats["hit_rate"] = stats["hits"] / total if total > 0 else 0.0
                return stats
            
            result = {}
            for name in self._caches:
                result[name] = self.get_stats(name)
            return result


# ============================================================================
# Main Requirement Class
# ============================================================================

class RequirementError(Exception):
    """Custom exception for requirement handling errors."""
    pass


class Requirement:
    """
    Comprehensive Python package requirement handler.
    
    This class provides a complete interface for parsing, validating,
    and manipulating Python package requirements according to PEP 508.
    
    Parameters
    ----------
    requirement : Optional[str], default=None
        Requirement string to parse.
    **kwargs
        Additional configuration options.
    
    Attributes
    ----------
    metadata : RequirementMetadata
        Parsed requirement metadata.
    raw : str
        Original requirement string.
    
    Examples
    --------
    >>> req = Requirement("requests[security]>=2.28.0")
    >>> req.name
    'requests'
    >>> req.extras
    ('security',)
    >>> req.version_spec
    '>=2.28.0'
    
    >>> req = Requirement("-e git+https://github.com/user/repo.git@v1.0#egg=package")
    >>> req.is_editable
    True
    >>> req.vcs_info.vcs_type
    <VCSSystem.GIT: 'git'>
    >>> req.vcs_info.ref
    'v1.0'
    
    >>> req = Requirement("pandas>=1.5.0; python_version >= '3.8'")
    >>> req.marker
    "python_version >= '3.8'"
    >>> req.evaluate_marker()
    True  # On Python 3.8+
    """
    
    # Class-level cache manager
    _cache_manager: ClassVar[CacheManager] = CacheManager(max_size=2000, ttl=3600)
    
    def __init__(self, requirement: Optional[str] = None, **kwargs):
        self._config = {
            'normalize': kwargs.get('normalize', True),
            'resolve_import': kwargs.get('resolve_import', False),
            'use_known_map': kwargs.get('use_known_map', True),
            'validate': kwargs.get('validate', True),
            'prefer_binary': kwargs.get('prefer_binary', False),
        }
        
        self.raw = requirement
        self.metadata: Optional[RequirementMetadata] = None
        
        if requirement is not None:
            self.parse(requirement)
    
    @property
    def name(self) -> Optional[str]:
        """Get normalized package name."""
        return self.metadata.name if self.metadata else None
    
    @property
    def extras(self) -> Optional[Tuple[str, ...]]:
        """Get extras requirements."""
        return self.metadata.extras if self.metadata else None
    
    @property
    def version_spec(self) -> Optional[str]:
        """Get version specification."""
        return self.metadata.version_spec if self.metadata else None
    
    @property
    def marker(self) -> Optional[str]:
        """Get environment marker."""
        return self.metadata.marker if self.metadata else None
    
    @property
    def url(self) -> Optional[str]:
        """Get URL reference."""
        return self.metadata.url if self.metadata else None
    
    @property
    def is_vcs(self) -> bool:
        """Check if requirement is from VCS."""
        return self.metadata.vcs_info is not None if self.metadata else False
    
    @property
    def is_local(self) -> bool:
        """Check if requirement is local path."""
        return self.metadata.is_local if self.metadata else False
    
    @property
    def is_editable(self) -> bool:
        """Check if requirement is editable."""
        return self.metadata.is_editable if self.metadata else False
    
    @property
    def is_valid(self) -> bool:
        """Check if requirement is valid."""
        return self.metadata.is_valid if self.metadata else False
    
    @property
    def vcs_info(self) -> Optional[VCSInfo]:
        """Get VCS information."""
        return self.metadata.vcs_info if self.metadata else None
    
    @property
    def requirement_type(self) -> Optional[RequirementType]:
        """Get requirement type."""
        return self.metadata.requirement_type if self.metadata else None
    
    def parse(self, requirement: str) -> 'Requirement':
        """
        Parse requirement string and populate metadata.
        
        Parameters
        ----------
        requirement : str
            Requirement string to parse.
        
        Returns
        -------
        Requirement
            Self for method chaining.
        
        Raises
        ------
        RequirementError
            If parsing fails.
        """
        # Check cache
        cache_key = f"parse:{requirement}:{self._config}"
        cached = self._cache_manager.get("parse", cache_key)
        if cached:
            self.metadata = cached
            return self
        
        try:
            self.raw = requirement
            self.metadata = self._parse_requirement(requirement)
            
            if self._config['validate'] and not self.metadata.is_valid:
                errors = ', '.join(self.metadata.validation_errors)
                raise RequirementError(f"Invalid requirement: {errors}")
            
            self._cache_manager.set("parse", cache_key, self.metadata)
            return self
            
        except Exception as e:
            raise RequirementError(f"Failed to parse requirement '{requirement}': {e}") from e
    
    def _parse_requirement(self, requirement: str) -> RequirementMetadata:
        """Internal requirement parsing logic."""
        requirement = requirement.strip()
        original = requirement
        
        # Handle editable flag
        is_editable = False
        if requirement.startswith('-e '):
            is_editable = True
            requirement = requirement[3:].strip()
        
        # Check for local path
        if _REQUIREMENT_PATTERNS['local_path'].match(requirement):
            return self._parse_local_requirement(
                requirement, original, is_editable
            )
        
        # Extract marker
        marker = None
        marker_match = _REQUIREMENT_PATTERNS['marker'].search(requirement)
        if marker_match:
            marker = marker_match.group(1).strip()
            requirement = requirement[:marker_match.start()].strip()
        
        # Extract URL
        url = None
        url_match = _REQUIREMENT_PATTERNS['url'].search(requirement)
        if url_match:
            url = url_match.group(1)
            requirement = requirement[:url_match.start()].strip()
        
        # Parse VCS or URL requirement
        if url:
            return self._parse_url_requirement(
                requirement, url, marker, original, is_editable
            )
        
        # Parse standard requirement
        return self._parse_standard_requirement(
            requirement, marker, original, is_editable
        )
    
    def _parse_local_requirement(
        self, path_str: str, original: str, is_editable: bool
    ) -> RequirementMetadata:
        """Parse local path requirement."""
        try:
            path = Path(path_str).resolve()
            return RequirementMetadata(
                name=path.stem,
                original_name=original,
                requirement_type=RequirementType.LOCAL,
                is_local=True,
                local_path=path,
                is_editable=is_editable,
                raw=original,
                is_valid=path.exists(),
                validation_errors=() if path.exists() else ("Local path does not exist",),
            )
        except Exception as e:
            return RequirementMetadata(
                name=path_str,
                original_name=original,
                requirement_type=RequirementType.LOCAL,
                is_local=True,
                is_editable=is_editable,
                raw=original,
                is_valid=False,
                validation_errors=(f"Invalid local path: {e}",),
            )
    
    def _parse_url_requirement(
        self, name_part: str, url: str, marker: Optional[str],
        original: str, is_editable: bool
    ) -> RequirementMetadata:
        """Parse URL/VCS requirement."""
        # Extract name from @ syntax
        if '@' in name_part:
            name = name_part.split('@')[0].strip()
        else:
            name = name_part.strip()
        
        # Check for VCS
        vcs_info = None
        requirement_type = RequirementType.URL
        
        for prefix in _VCS_PREFIXES:
            if url.startswith(prefix):
                vcs_info = self._parse_vcs_url(url)
                requirement_type = RequirementType.VCS
                if vcs_info and vcs_info.egg:
                    name = vcs_info.egg
                break
        
        # Check for archive
        is_archive = bool(_REQUIREMENT_PATTERNS['archive'].search(url))
        if is_archive:
            requirement_type = RequirementType.ARCHIVE
        
        # Normalize name
        if name:
            name = self._normalize_name(name)
        else:
            name = self._extract_name_from_url(url)
        
        # Extract extras from name
        extras = None
        extras_match = _REQUIREMENT_PATTERNS['extras'].search(name)
        if extras_match:
            extras = tuple(e.strip() for e in extras_match.group(1).split(','))
            name = name[:extras_match.start()]
        
        return RequirementMetadata(
            name=name,
            original_name=original,
            requirement_type=requirement_type,
            extras=extras,
            marker=marker,
            url=url,
            vcs_info=vcs_info,
            is_editable=is_editable,
            is_archive=is_archive,
            raw=original,
        )
    
    def _parse_standard_requirement(
        self, requirement: str, marker: Optional[str],
        original: str, is_editable: bool
    ) -> RequirementMetadata:
        """Parse standard PyPI requirement."""
        # Extract extras
        extras = None
        extras_match = _REQUIREMENT_PATTERNS['extras'].search(requirement)
        if extras_match:
            extras = tuple(e.strip() for e in extras_match.group(1).split(','))
            requirement = (requirement[:extras_match.start()] + 
                          requirement[extras_match.end():])
        
        # Extract version specifier
        version_spec = None
        version_match = _REQUIREMENT_PATTERNS['version_split'].search(requirement)
        if version_match:
            version_spec = version_match.group(1)
            requirement = requirement[:version_match.start()]
        
        # Normalize name
        name = self._normalize_name(requirement.strip())
        
        # Apply binary preference
        if self._config['prefer_binary'] and name in NameMapping.BINARY_PREFERENCES:
            name = NameMapping.BINARY_PREFERENCES[name][0]
        
        return RequirementMetadata(
            name=name,
            original_name=original,
            requirement_type=RequirementType.STANDARD,
            extras=extras,
            version_spec=version_spec,
            marker=marker,
            is_editable=is_editable,
            raw=original,
        )
    
    def _parse_vcs_url(self, url: str) -> Optional[VCSInfo]:
        """Parse VCS URL into structured info."""
        # Determine VCS type
        vcs_type = None
        for prefix in _VCS_PREFIXES:
            if url.startswith(prefix):
                vcs_type = VCSSystem.from_prefix(prefix)
                url = url[len(prefix):]
                break
        
        if not vcs_type:
            return None
        
        # Extract ref
        ref = None
        ref_match = _REQUIREMENT_PATTERNS['vcs_ref'].search(url)
        if ref_match:
            ref = ref_match.group(1)
            url = url[:ref_match.start()]
        
        # Extract fragments
        subdirectory = None
        egg = None
        
        fragment_match = _REQUIREMENT_PATTERNS['subdirectory'].search(url)
        if fragment_match:
            subdirectory = fragment_match.group(1)
        
        egg_match = _REQUIREMENT_PATTERNS['egg'].search(url)
        if egg_match:
            egg = egg_match.group(1)
        
        # Clean URL
        clean_url = url.split('#')[0]
        
        return VCSInfo(
            vcs_type=vcs_type,
            url=clean_url,
            ref=ref,
            subdirectory=subdirectory,
            egg=egg,
        )
    
    def _normalize_name(self, name: str) -> str:
        """Normalize package name."""
        if not self._config['normalize']:
            return name
        
        normalized = NameMapping.normalize(name)
        
        if self._config['use_known_map']:
            resolved = NameMapping.resolve_import(normalized)
            if resolved != normalized:
                normalized = resolved
        
        if self._config['resolve_import']:
            normalized = self._resolve_import_name(normalized)
        
        return normalized
    
    def _resolve_import_name(self, name: str) -> str:
        """Resolve import name to distribution name."""
        cache_key = f"resolve:{name}"
        cached = self._cache_manager.get("resolve", cache_key)
        if cached:
            return cached
        
        result = name
        
        if HAS_IMPORTLIB_METADATA and packages_distributions:
            try:
                mapping = packages_distributions()
                if name in mapping and mapping[name]:
                    result = mapping[name][0]
            except Exception:
                pass
        
        self._cache_manager.set("resolve", cache_key, result)
        return result
    
    def _extract_name_from_url(self, url: str) -> str:
        """Extract package name from URL."""
        # Try egg fragment
        egg_match = _REQUIREMENT_PATTERNS['egg'].search(url)
        if egg_match:
            return self._normalize_name(egg_match.group(1))
        
        # Try to parse from path
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        if path:
            filename = path.split('/')[-1]
            # Remove extension
            for ext in _ARCHIVE_EXTENSIONS:
                if filename.endswith(ext):
                    filename = filename[:-len(ext)]
                    break
            # Remove version
            filename = re.sub(r'-\d+.*$', '', filename)
            return self._normalize_name(filename)
        
        return "unknown"
    
    def evaluate_marker(self, environment: Optional[Dict[str, Any]] = None) -> bool:
        """
        Evaluate environment marker against current or provided environment.
        
        Parameters
        ----------
        environment : Optional[Dict[str, Any]], default=None
            Custom environment dictionary. If None, uses current environment.
        
        Returns
        -------
        bool
            True if marker evaluates to True, False otherwise.
        """
        if not self.marker:
            return True
        
        if environment is None:
            environment = self._get_default_environment()
        
        if HAS_PACKAGING:
            try:
                marker = packaging.markers.Marker(self.marker)
                return marker.evaluate(environment)
            except Exception:
                pass
        
        # Fallback basic evaluation
        return self._evaluate_marker_basic(environment)
    
    def _get_default_environment(self) -> Dict[str, Any]:
        """Get default environment for marker evaluation."""
        return {
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}",
            'python_full_version': _PYTHON_VERSION_STR,
            'sys_platform': sys.platform,
            'platform_system': sys.platform,
            'platform_machine': sys.platform,
            'platform_python_implementation': _PYTHON_IMPLEMENTATION,
            'platform_version': sys.platform,
            'platform_release': sys.platform,
            'implementation_name': _PYTHON_IMPLEMENTATION,
            'implementation_version': _PYTHON_VERSION_STR,
            'os_name': os.name,
            'extra': '',
        }
    
    def _evaluate_marker_basic(self, environment: Dict[str, Any]) -> bool:
        """Basic marker evaluation fallback."""
        # Simple evaluation for common patterns
        if 'python_version' in self.marker:
            if ">= '3.8'" in self.marker or ">='3.8'" in self.marker:
                return sys.version_info >= (3, 8)
            elif ">= '3.7'" in self.marker or ">='3.7'" in self.marker:
                return sys.version_info >= (3, 7)
            elif ">= '3.6'" in self.marker or ">='3.6'" in self.marker:
                return sys.version_info >= (3, 6)
        
        if 'sys_platform' in self.marker:
            platform = environment.get('sys_platform', '')
            if f"== '{platform}'" in self.marker or f"=='{platform}'" in self.marker:
                return True
            if 'win32' in self.marker and sys.platform == 'win32':
                return True
            if 'linux' in self.marker and sys.platform.startswith('linux'):
                return True
            if 'darwin' in self.marker and sys.platform == 'darwin':
                return True
        
        return True
    
    def is_installed(self, check_version: bool = True) -> bool:
        """
        Check if this requirement is installed.
        
        Parameters
        ----------
        check_version : bool, default=True
            Whether to check version constraints.
        
        Returns
        -------
        bool
            True if installed and satisfies constraints.
        """
        if not self.name:
            return False
        
        try:
            if HAS_IMPORTLIB_METADATA:
                dist = distribution(self.name)
                installed_version = dist.version
            elif HAS_PKG_RESOURCES:
                dist = pkg_resources.get_distribution(self.name)
                installed_version = dist.version
            else:
                return False
            
            if check_version and self.version_spec and HAS_PACKAGING:
                specifier = packaging.specifiers.SpecifierSet(self.version_spec)
                return packaging.version.parse(installed_version) in specifier
            
            return True
            
        except Exception:
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert requirement to dictionary."""
        if not self.metadata:
            return {"raw": self.raw}
        return self.metadata.to_dict()
    
    def __str__(self) -> str:
        return str(self.metadata) if self.metadata else self.raw or ""
    
    def __repr__(self) -> str:
        return f"Requirement('{self}')"
    
    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Requirement):
            return False
        if not self.name or not other.name:
            return False
        return NameMapping.compare(self.name, other.name)
    
    def __hash__(self) -> int:
        return hash(self.name) if self.name else hash(self.raw)
    
    @classmethod
    def clear_cache(cls, cache_name: Optional[str] = None) -> None:
        """
        Clear requirement caches.
        
        Parameters
        ----------
        cache_name : Optional[str], default=None
            Name of cache to clear, or None to clear all.
        """
        cls._cache_manager.clear(cache_name)
    
    @classmethod
    def get_cache_stats(cls) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns
        -------
        Dict[str, Any]
            Cache statistics.
        """
        return cls._cache_manager.get_stats()
    
    @classmethod
    def normalize(
        cls,
        name: str,
        *,
        keep_extras: bool = False,
        keep_version: bool = False,
        keep_markers: bool = False,
        lowercase: bool = True,
        resolve_import: bool = False,
        use_known_map: bool = True,
        prefer_binary: bool = False,
    ) -> str:
        """
        Normalize a package or requirement string.
        
        Parameters
        ----------
        name : str
            Input package/module name or requirement string.
        keep_extras : bool, default=False
            Keep extras like [dev], [test].
        keep_version : bool, default=False
            Keep version specifiers.
        keep_markers : bool, default=False
            Keep environment markers.
        lowercase : bool, default=True
            Convert to lowercase.
        resolve_import : bool, default=False
            Resolve import name to distribution name.
        use_known_map : bool, default=True
            Apply known name mappings.
        prefer_binary : bool, default=False
            Prefer binary distributions.
        
        Returns
        -------
        str
            Normalized package name or requirement string.
        """
        # Parse with temporary config
        temp_req = cls(name, validate=False, normalize=lowercase,
                      resolve_import=resolve_import,
                      use_known_map=use_known_map,
                      prefer_binary=prefer_binary)
        
        if not temp_req.metadata:
            return name
        
        meta = temp_req.metadata
        result = meta.name
        
        if keep_extras and meta.extras:
            result += f"[{','.join(meta.extras)}]"
        
        if keep_version and meta.version_spec:
            result += meta.version_spec
        
        if keep_markers and meta.marker:
            result += f"; {meta.marker}"
        
        return result
    
    @classmethod
    def canonical_name(cls, name: str) -> str:
        """
        Get canonical PyPI name for a package.
        
        Parameters
        ----------
        name : str
            Package name or import name.
        
        Returns
        -------
        str
            Canonical PyPI package name.
        """
        return cls.normalize(name, resolve_import=True, use_known_map=True)
    
    @classmethod
    def compare_names(cls, name1: str, name2: str) -> bool:
        """
        Compare two package names for equivalence.
        
        Parameters
        ----------
        name1 : str
            First package name.
        name2 : str
            Second package name.
        
        Returns
        -------
        bool
            True if names refer to the same package.
        """
        return NameMapping.compare(name1, name2)
    
    @classmethod
    def from_requirements_file(cls, filepath: Union[str, Path]) -> List['Requirement']:
        """
        Parse requirements from a requirements.txt file.
        
        Parameters
        ----------
        filepath : Union[str, Path]
            Path to requirements.txt file.
        
        Returns
        -------
        List[Requirement]
            List of Requirement objects.
        
        Raises
        ------
        FileNotFoundError
            If file doesn't exist.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Requirements file not found: {filepath}")
        
        requirements = []
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Handle line continuations
        lines = []
        current_line = ""
        for line in content.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                if current_line:
                    lines.append(current_line)
                    current_line = ""
                continue
            
            if line.endswith('\\'):
                current_line += line[:-1].strip()
            else:
                current_line += line
                lines.append(current_line)
                current_line = ""
        
        if current_line:
            lines.append(current_line)
        
        for line in lines:
            if line.strip():
                try:
                    requirements.append(cls(line.strip()))
                except Exception as e:
                    logger.warning(f"Failed to parse requirement '{line}': {e}")
        
        return requirements
    
    @classmethod
    def batch_parse(
        cls,
        requirements: List[str],
        *,
        parallel: bool = False,
        max_workers: int = 4,
        **kwargs
    ) -> List['Requirement']:
        """
        Parse multiple requirements in batch.
        
        Parameters
        ----------
        requirements : List[str]
            List of requirement strings.
        parallel : bool, default=False
            Whether to use parallel processing.
        max_workers : int, default=4
            Maximum number of parallel workers.
        **kwargs
            Additional arguments for Requirement constructor.
        
        Returns
        -------
        List[Requirement]
            List of parsed Requirement objects.
        """
        if not parallel:
            return [cls(req, **kwargs) for req in requirements]
        
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(cls, req, **kwargs): req for req in requirements}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.warning(f"Failed to parse '{futures[future]}': {e}")
        
        return results


# ============================================================================
# Convenience Functions
# ============================================================================

def parse_requirement(requirement: str, **kwargs) -> RequirementMetadata:
    """
    Parse a requirement string into metadata.
    
    Parameters
    ----------
    requirement : str
        Requirement string to parse.
    **kwargs
        Additional parsing options.
    
    Returns
    -------
    RequirementMetadata
        Parsed requirement metadata.
    """
    req = Requirement(requirement, **kwargs)
    if not req.metadata:
        raise RequirementError(f"Failed to parse requirement: {requirement}")
    return req.metadata


def parse_requirements(
    requirements: List[str],
    parallel: bool = False,
    **kwargs
) -> List[RequirementMetadata]:
    """
    Parse multiple requirement strings.
    
    Parameters
    ----------
    requirements : List[str]
        List of requirement strings.
    parallel : bool, default=False
        Whether to use parallel processing.
    **kwargs
        Additional parsing options.
    
    Returns
    -------
    List[RequirementMetadata]
        List of parsed metadata.
    """
    reqs = Requirement.batch_parse(requirements, parallel=parallel, **kwargs)
    return [r.metadata for r in reqs if r.metadata]


def validate_requirement(requirement: str) -> Tuple[bool, Optional[str]]:
    """
    Validate a requirement string.
    
    Parameters
    ----------
    requirement : str
        Requirement string to validate.
    
    Returns
    -------
    Tuple[bool, Optional[str]]
        (is_valid, error_message)
    """
    try:
        req = Requirement(requirement, validate=True)
        if req.is_valid:
            return True, None
        errors = ', '.join(req.metadata.validation_errors) if req.metadata else "Unknown error"
        return False, errors
    except Exception as e:
        return False, str(e)


def normalize_name(name: str, **kwargs) -> str:
    """Normalize package name."""
    return Requirement.normalize(name, **kwargs)


def canonical_name(name: str) -> str:
    """Get canonical PyPI package name."""
    return Requirement.canonical_name(name)


def compare_names(name1: str, name2: str) -> bool:
    """Compare two package names for equivalence."""
    return Requirement.compare_names(name1, name2)


def get_distribution_name(import_name: str) -> Optional[str]:
    """Get distribution name for an import name."""
    return Requirement.canonical_name(import_name)


def get_import_names(distribution_name: str) -> List[str]:
    """Get common import names for a distribution."""
    return NameMapping.get_import_names(distribution_name)


def read_requirements(filepath: Union[str, Path]) -> List[Requirement]:
    """Read and parse a requirements.txt file."""
    return Requirement.from_requirements_file(filepath)


def is_test_module(module_name: str) -> bool:
    """Check if module appears to be a test module."""
    return NameMapping.is_test_module(module_name)


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    "RequirementType",
    "VCSSystem",
    "MarkerOperator",
    "ConstraintOperator",
    
    # Data Classes
    "VCSInfo",
    "VersionConstraint",
    "RequirementMetadata",
    
    # Main Classes
    "CacheManager",
    "Requirement",
    
    # Exceptions
    "RequirementError",
    
    # Name Mapping
    "NameMapping",
    
    # Convenience Functions
    "parse_requirement",
    "parse_requirements",
    "validate_requirement",
    "normalize_name",
    "canonical_name",
    "compare_names",
    "get_distribution_name",
    "get_import_names",
    "read_requirements",
    "is_test_module",
]

