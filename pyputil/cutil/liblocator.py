#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""LibLocator.py"""

import inspect
import ctypes
import platform
import sys
import os
import re
import logging
import mmap
import json
import hashlib
import time
import struct
from pathlib import Path
from typing import (Any, Set, Optional, List, Tuple, Dict, Union, Callable, 
                    TypeVar, Iterator, NamedTuple, DefaultDict, FrozenSet)
from functools import lru_cache, wraps
from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError, Future
from enum import Enum, auto
import subprocess
from collections import defaultdict, OrderedDict
from threading import Lock, RLock
import tempfile
import atexit
import weakref
from abc import ABC, abstractmethod

# ============================================================================
# Type Definitions
# ============================================================================

T = TypeVar('T')
ModuleType = type(sys)
CacheKey = Tuple[str, int, str, str, Tuple[str, ...]]

# Type for objects that can be searched
SearchableObject = Union[Callable, type, Any]


# ============================================================================
# Configuration System
# ============================================================================

@dataclass
class Config:
    """
    Runtime configuration for the library locator.
    
    This class holds all configurable parameters that control the behavior
    of the library locator. It can be modified globally using the
    `configure()` function.
    
    Attributes
    ----------
    max_workers : int, default=4
        Number of parallel workers for I/O operations. Automatically
        capped at (CPU_COUNT * 2).
    max_files_to_scan : int, default=200
        Maximum number of files to examine during directory search.
        Higher values increase accuracy but reduce speed.
    scan_timeout : float, default=15.0
        Timeout in seconds for each individual scan operation.
    cache_size : int, default=128
        Size of LRU cache for function results in memory.
    cache_dir : Optional[Path], default=None
        Directory for persistent cache storage. If None, uses
        ~/.cache/liblocator/.
    min_hint_length : int, default=3
        Minimum length of hint strings to consider for searching.
        Shorter strings are ignored to reduce false positives.
    max_search_depth : int, default=3
        Maximum directory recursion depth during filesystem search.
    max_file_size_mb : int, default=500
        Skip files larger than this size (in MB) during scanning.
    global_timeout : float, default=30.0
        Overall timeout in seconds for the entire search operation.
    enable_persistent_cache : bool, default=True
        Whether to use disk-based caching between Python sessions.
    enable_elf_analysis : bool, default=True
        Whether to analyze ELF headers on Linux for symbol extraction.
    enable_pe_analysis : bool, default=True
        Whether to analyze PE headers on Windows for export table analysis.
    debug_mode : bool, default=False
        When True, returns detailed debugging information with results.
    log_level : int, default=logging.WARNING
        Logging level for the module (e.g., logging.DEBUG, logging.INFO).
    confidence_threshold : float, default=0.0
        Minimum confidence score (0.0 to 1.0) required to return a result.
    use_weakref_cache : bool, default=True
        Whether to use weak references for caching to prevent memory leaks.
    site_packages_priority : bool, default=True
        Whether to prioritize site-packages directories in search.
    
    Examples
    --------
    >>> config = Config()
    >>> config.max_workers = 8
    >>> config.debug_mode = True
    
    >>> # Or use the configure function
    >>> configure(max_workers=8, debug_mode=True)
    """
    # Performance settings
    max_workers: int = 4
    max_files_to_scan: int = 200
    scan_timeout: float = 15.0
    cache_size: int = 128
    min_hint_length: int = 3
    max_search_depth: int = 3
    max_file_size_mb: int = 500
    global_timeout: float = 30.0
    
    # Feature toggles
    enable_persistent_cache: bool = True
    enable_elf_analysis: bool = True
    enable_pe_analysis: bool = True
    debug_mode: bool = False
    use_weakref_cache: bool = True
    site_packages_priority: bool = True
    
    # Path settings
    cache_dir: Optional[Path] = None
    
    # Thresholds
    confidence_threshold: float = 0.0
    log_level: int = logging.WARNING
    
    def __post_init__(self) -> None:
        """
        Initialize derived configuration values after dataclass creation.
        
        This method:
            1. Sets up the cache directory
            2. Adjusts worker count based on CPU cores
            3. Validates configuration values
        """
        # Setup cache directory
        if self.cache_dir is None and self.enable_persistent_cache:
            self.cache_dir = Path.home() / '.cache' / 'liblocator'
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Adjust workers based on CPU count
        cpu_count = os.cpu_count() or 1
        self.max_workers = min(self.max_workers, cpu_count * 2)
        self.max_workers = max(1, self.max_workers)  # At least 1 worker
        
        # Validate values
        if self.confidence_threshold < 0 or self.confidence_threshold > 1:
            raise ValueError("confidence_threshold must be between 0.0 and 1.0")
        
        if self.min_hint_length < 1:
            raise ValueError("min_hint_length must be at least 1")
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of configuration.
        """
        result = asdict(self)
        if self.cache_dir:
            result['cache_dir'] = str(self.cache_dir)
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Config':
        """
        Create configuration from dictionary.
        
        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary with configuration values.
        
        Returns
        -------
        Config
            New configuration instance.
        """
        if 'cache_dir' in data and data['cache_dir']:
            data['cache_dir'] = Path(data['cache_dir'])
        return cls(**data)


# Global configuration instance
_config = Config()
_config_lock = RLock()


def configure(**kwargs: Any) -> None:
    """
    Update the global configuration with new values.
    
    This function provides a convenient way to modify the global
    configuration without directly accessing the `_config` object.
    
    Parameters
    ----------
    **kwargs : dict
        Configuration parameters to update. Valid keys are any
        attribute of the `Config` class.
    
    Raises
    ------
    ValueError
        If an unknown configuration parameter is provided.
    
    Examples
    --------
    >>> # Enable debug mode and increase cache size
    >>> configure(debug_mode=True, cache_size=256)
    
    >>> # Set a custom cache directory
    >>> configure(cache_dir=Path('/tmp/my_cache'))
    
    >>> # Adjust performance settings
    >>> configure(max_workers=8, max_files_to_scan=500, global_timeout=60.0)
    """
    global _config
    
    with _config_lock:
        for key, value in kwargs.items():
            if hasattr(_config, key):
                setattr(_config, key, value)
            else:
                valid_keys = [f.name for f in dataclasses.fields(Config)]
                raise ValueError(
                    f"Unknown configuration parameter: '{key}'. "
                    f"Valid parameters are: {', '.join(valid_keys)}"
                )
        
        # Re-initialize cache directory if needed
        if _config.enable_persistent_cache and _config.cache_dir:
            _config.cache_dir.mkdir(parents=True, exist_ok=True)


def get_config() -> Config:
    """
    Get the current global configuration.
    
    Returns
    -------
    Config
        The current global configuration instance.
    
    Examples
    --------
    >>> config = get_config()
    >>> print(f"Max workers: {config.max_workers}")
    >>> print(f"Cache size: {config.cache_size}")
    """
    return _config


def reset_config() -> None:
    """
    Reset the global configuration to default values.
    
    Examples
    --------
    >>> configure(debug_mode=True, max_workers=16)
    >>> reset_config()
    >>> get_config().debug_mode
    False
    """
    global _config
    with _config_lock:
        _config = Config()


# ============================================================================
# Logging System
# ============================================================================

logger = logging.getLogger(__name__)
_logging_initialized = False
_logging_lock = Lock()


def setup_logging(level: Optional[int] = None, 
                  log_file: Optional[Union[str, Path]] = None) -> None:
    """
    Setup logging with appropriate handlers.
    
    This function configures the logger for the module. It can be called
    multiple times without duplicating handlers.
    
    Parameters
    ----------
    level : Optional[int], default=None
        Logging level (e.g., logging.DEBUG, logging.INFO).
        If None, uses the value from configuration.
    log_file : Optional[Union[str, Path]], default=None
        Path to a log file. If provided, logs will be written to this file
        in addition to console output.
    
    Examples
    --------
    >>> # Setup debug logging to console
    >>> setup_logging(level=logging.DEBUG)
    
    >>> # Setup logging to file
    >>> setup_logging(level=logging.INFO, log_file='liblocator.log')
    """
    global _logging_initialized
    
    with _logging_lock:
        if level is None:
            level = _config.log_level
        
        logger.setLevel(level)
        
        # Clear existing handlers if re-initializing
        if _logging_initialized:
            logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # File handler (optional)
        if log_file:
            file_handler = logging.FileHandler(str(log_file), encoding='utf-8')
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        
        _logging_initialized = True


# Initialize logging with default settings
setup_logging()


# ============================================================================
# Enumerations and Constants
# ============================================================================

class ScanMode(Enum):
    """
    Scanning mode balancing speed vs accuracy.
    
    This enumeration defines the trade-off between search speed and
    thoroughness when locating library files.
    
    Attributes
    ----------
    FASTEST : str
        Direct methods only, no file scanning. Fastest but least thorough.
    BALANCED : str
        Limited file scanning with reasonable performance. (Default)
    THOROUGH : str
        Full scanning including deep directory search. Slower but most accurate.
    
    Examples
    --------
    >>> # Use fastest mode for quick checks
    >>> path = guess_file(np, np.array, mode=ScanMode.FASTEST)
    
    >>> # Use thorough mode when accuracy is critical
    >>> path = guess_file(np, np.array, mode=ScanMode.THOROUGH)
    """
    FASTEST = "fastest"
    BALANCED = "balanced"
    THOROUGH = "thorough"
    
    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value


class ConfidenceLevel(Enum):
    """
    Confidence levels for match results.
    
    These values indicate how confident the library is about a match.
    Higher confidence means the result is more likely to be correct.
    
    Attributes
    ----------
    CERTAIN : float (1.0)
        Direct evidence (e.g., __file__ attribute, dladdr).
    HIGH : float (0.8)
        Strong evidence (e.g., multiple symbol matches).
    MEDIUM : float (0.6)
        Good evidence (e.g., filename and content match).
    LOW : float (0.4)
        Weak evidence (e.g., partial filename match only).
    GUESS : float (0.2)
        Best guess from limited information.
    
    Examples
    --------
    >>> result = guess_file_with_details(np, np.array)
    >>> if result['confidence'] >= ConfidenceLevel.HIGH.value:
    ...     print("High confidence result")
    """
    CERTAIN = 1.0
    HIGH = 0.8
    MEDIUM = 0.6
    LOW = 0.4
    GUESS = 0.2


class StrategyType(Enum):
    """
    Types of search strategies used by the locator.
    
    This enumeration categorizes the different methods used to locate
    library files, from fastest to most thorough.
    
    Attributes
    ----------
    DIRECT : str
        Direct object inspection (e.g., __file__ attribute).
    SYSTEM : str
        System API calls (e.g., dladdr, GetModuleHandle).
    MEMORY : str
        Memory analysis (e.g., /proc/pid/maps).
    HEADER : str
        Binary header analysis (e.g., ELF, PE).
    FILESYSTEM : str
        File system search and scanning.
    """
    DIRECT = "direct"
    SYSTEM = "system"
    MEMORY = "memory"
    HEADER = "header"
    FILESYSTEM = "filesystem"


class MatchResult(NamedTuple):
    """
    Structured result from a matching operation.
    
    Attributes
    ----------
    path : Optional[str]
        The found file path, or None if not found.
    score : int
        Raw match score.
    confidence : float
        Normalized confidence value (0.0 to 1.0).
    strategy : str
        Name of the strategy that found the match.
    details : Dict[str, Any]
        Additional details about the match.
    """
    path: Optional[str]
    score: int
    confidence: float
    strategy: str
    details: Dict[str, Any]


# ============================================================================
# Scoring Weights Configuration
# ============================================================================

@dataclass
class ScoreWeights:
    """
    Scoring weights for different types of matches.
    
    These weights determine the relative importance of different match
    indicators when calculating confidence scores.
    
    Attributes
    ----------
    direct_module_file : int, default=1000
        Weight for matches from __file__ attribute.
    dladdr_success : int, default=950
        Weight for successful dladdr API calls.
    windows_module_handle : int, default=950
        Weight for Windows GetModuleHandle API.
    memory_map_match : int, default=900
        Weight for matches in /proc/pid/maps.
    elf_symbol_match : int, default=850
        Weight for ELF symbol table matches.
    pe_export_match : int, default=850
        Weight for PE export table matches.
    exact_filename : int, default=100
        Weight for exact filename matches.
    symbol_table_match : int, default=80
        Weight for symbol table string matches.
    partial_filename : int, default=50
        Weight for partial filename matches.
    export_table_match : int, default=70
        Weight for export table string matches.
    python_version_match : int, default=40
        Weight for Python version in filename.
    content_pattern : int, default=30
        Weight for text patterns in binary content.
    module_path_match : int, default=90
        Weight for path containing module name.
    directory_priority : int, default=20
        Weight for files in priority directories.
    site_packages_match : int, default=60
        Weight for files in site-packages directory.
    
    Examples
    --------
    >>> weights = ScoreWeights()
    >>> weights.exact_filename = 150  # Increase importance
    >>> weights.partial_filename = 30  # Decrease importance
    """
    direct_module_file: int = 1000
    dladdr_success: int = 950
    windows_module_handle: int = 950
    memory_map_match: int = 900
    elf_symbol_match: int = 850
    pe_export_match: int = 850
    exact_filename: int = 100
    symbol_table_match: int = 80
    partial_filename: int = 50
    export_table_match: int = 70
    python_version_match: int = 40
    content_pattern: int = 30
    module_path_match: int = 90
    directory_priority: int = 20
    site_packages_match: int = 60
    
    def to_dict(self) -> Dict[str, int]:
        """Convert weights to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> 'ScoreWeights':
        """Create weights from dictionary."""
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


# Global scoring weights
_SCORE_WEIGHTS = ScoreWeights()


def get_score_weights() -> ScoreWeights:
    """
    Get the current scoring weights configuration.
    
    Returns
    -------
    ScoreWeights
        The current scoring weights.
    
    Examples
    --------
    >>> weights = get_score_weights()
    >>> print(f"Exact filename weight: {weights.exact_filename}")
    """
    return _SCORE_WEIGHTS


def set_score_weights(weights: Union[ScoreWeights, Dict[str, int]]) -> None:
    """
    Update the global scoring weights.
    
    Parameters
    ----------
    weights : Union[ScoreWeights, Dict[str, int]]
        New scoring weights, either as a ScoreWeights instance
        or a dictionary.
    
    Examples
    --------
    >>> # Update using dictionary
    >>> set_score_weights({'exact_filename': 150, 'partial_filename': 30})
    
    >>> # Update using ScoreWeights instance
    >>> new_weights = ScoreWeights(exact_filename=150)
    >>> set_score_weights(new_weights)
    """
    global _SCORE_WEIGHTS
    
    if isinstance(weights, dict):
        _SCORE_WEIGHTS = ScoreWeights.from_dict(weights)
    elif isinstance(weights, ScoreWeights):
        _SCORE_WEIGHTS = weights
    else:
        raise TypeError(f"Expected ScoreWeights or dict, got {type(weights)}")


# ============================================================================
# Platform-Specific Constants
# ============================================================================

# Platform-specific shared library extensions
_PLATFORM_EXTENSIONS: Dict[str, Set[str]] = {
    'windows': {'.pyd', '.dll'},
    'linux': {'.so'},
    'darwin': {'.so', '.dylib', '.bundle'},
    'freebsd': {'.so'},
    'unknown': {'.so', '.pyd', '.dll', '.dylib'}
}

# Priority directories that are checked first during filesystem search
_PRIORITY_DIRS: List[str] = [
    'lib', 
    'build/lib', 
    '.libs', 
    'lib64', 
    'Library/bin', 
    'site-packages',
    'dist-packages'
]

# Patterns for Python version in filenames
_PYTHON_VERSION_PATTERNS: List[re.Pattern] = [
    re.compile(r'cpython[-_](\d+)[-_](\d+)', re.IGNORECASE),
    re.compile(r'python[-_]?(\d+)\.(\d+)', re.IGNORECASE),
    re.compile(r'py(\d)(\d)', re.IGNORECASE),
]

# Patterns to clean from hint strings
_HINT_CLEANUP_PATTERNS: List[re.Pattern] = [
    re.compile(r'[_\-]?(v?\d+\.?\d*)$'),
    re.compile(r'[_\-]?py\d+$', re.IGNORECASE),
    re.compile(r'^_+'),
    re.compile(r'_+$'),
]


# ============================================================================
# Platform Detection
# ============================================================================

class PlatformDetector:
    """
    Detects and caches platform information.
    
    This class provides a singleton interface for detecting and caching
    platform-specific information such as OS type, architecture, and
    Python version. This avoids repeated system calls.
    
    Attributes
    ----------
    _instance : Optional[PlatformDetector]
        Singleton instance.
    _platform : str
        Normalized platform name ('windows', 'linux', 'macos', etc.).
    _architecture : str
        System architecture ('32' or '64').
    _python_version : str
        Python version as string (e.g., '39' for 3.9).
    _libc_version : Optional[str]
        libc version on Linux systems.
    _is_conda : bool
        Whether running in Conda environment.
    _site_packages_paths : List[Path]
        Cached site-packages paths.
    
    Examples
    --------
    >>> detector = PlatformDetector()
    >>> detector.platform
    'linux'
    >>> detector.architecture
    '64'
    >>> detector.python_version
    '310'
    """
    
    _instance: Optional['PlatformDetector'] = None
    _lock: Lock = Lock()
    
    def __new__(cls) -> 'PlatformDetector':
        """
        Create or return the singleton instance.
        
        Returns
        -------
        PlatformDetector
            The singleton instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._detect()
        return cls._instance
    
    def _detect(self) -> None:
        """
        Detect and cache platform details.
        
        This method is called once during instance creation to detect:
            - Operating system type
            - System architecture
            - Python version
            - libc version (Linux only)
            - Conda environment status
            - Site-packages paths
        """
        system = platform.system().lower()
        
        # Detect platform
        if system == 'windows':
            self._platform = 'windows'
        elif system == 'linux':
            self._platform = 'linux'
        elif system == 'darwin':
            self._platform = 'macos'
        elif system == 'freebsd':
            self._platform = 'freebsd'
        else:
            self._platform = 'unknown'
        
        # Detect architecture
        self._architecture = '64' if sys.maxsize > 2**32 else '32'
        
        # Detect Python version
        self._python_version = f"{sys.version_info.major}{sys.version_info.minor}"
        
        # Detect libc version on Linux
        self._libc_version: Optional[str] = None
        if self._platform == 'linux':
            self._libc_version = self._detect_libc_version()
        
        # Check if running in Conda
        self._is_conda = self._detect_conda()
        
        # Cache site-packages paths
        self._site_packages_paths = self._detect_site_packages()
    
    def _detect_libc_version(self) -> Optional[str]:
        """
        Detect glibc version on Linux systems.
        
        Returns
        -------
        Optional[str]
            glibc version string if detected, None otherwise.
        """
        try:
            # Try using ldd --version
            result = subprocess.run(
                ['ldd', '--version'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                match = re.search(r'(\d+\.\d+)', result.stdout)
                if match:
                    return match.group(1)
        except Exception:
            pass
        
        try:
            # Try reading from libc.so.6
            libc_paths = ['/lib/x86_64-linux-gnu/libc.so.6', '/lib/libc.so.6']
            for path in libc_paths:
                if os.path.exists(path):
                    result = subprocess.run(
                        [path],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    match = re.search(r'(\d+\.\d+)', result.stdout)
                    if match:
                        return match.group(1)
        except Exception:
            pass
        
        return None
    
    def _detect_conda(self) -> bool:
        """
        Detect if running in a Conda environment.
        
        Returns
        -------
        bool
            True if in Conda environment, False otherwise.
        """
        return (
            'CONDA_PREFIX' in os.environ or
            'CONDA_DEFAULT_ENV' in os.environ or
            any('conda' in p.lower() for p in sys.path)
        )
    
    def _detect_site_packages(self) -> List[Path]:
        """
        Detect and cache site-packages directory paths.
        
        Returns
        -------
        List[Path]
            List of site-packages directory paths.
        """
        paths = []
        
        # Standard site-packages
        for p in sys.path:
            if 'site-packages' in p or 'dist-packages' in p:
                p_path = Path(p)
                if p_path.exists() and p_path.is_dir():
                    paths.append(p_path)
        
        # Conda-specific paths
        if self._is_conda:
            conda_prefix = os.environ.get('CONDA_PREFIX')
            if conda_prefix:
                conda_path = Path(conda_prefix)
                lib_paths = [
                    conda_path / 'lib',
                    conda_path / 'Library' / 'bin',
                    conda_path / 'lib' / f'python{self._python_version}',
                ]
                for p in lib_paths:
                    if p.exists() and p.is_dir():
                        paths.append(p)
        
        return paths
    
    @property
    def platform(self) -> str:
        """
        Get the current platform name.
        
        Returns
        -------
        str
            Platform name: 'windows', 'linux', 'macos', 'freebsd', or 'unknown'.
        
        Examples
        --------
        >>> PlatformDetector().platform
        'linux'
        """
        return self._platform
    
    @property
    def architecture(self) -> str:
        """
        Get the system architecture.
        
        Returns
        -------
        str
            Architecture string: '32' or '64'.
        
        Examples
        --------
        >>> PlatformDetector().architecture
        '64'
        """
        return self._architecture
    
    @property
    def python_version(self) -> str:
        """
        Get the Python version string.
        
        Returns
        -------
        str
            Python version (e.g., '39' for Python 3.9).
        
        Examples
        --------
        >>> PlatformDetector().python_version
        '310'
        """
        return self._python_version
    
    @property
    def libc_version(self) -> Optional[str]:
        """
        Get the libc version on Linux systems.
        
        Returns
        -------
        Optional[str]
            libc version string if detected, None otherwise or on non-Linux.
        
        Examples
        --------
        >>> detector = PlatformDetector()
        >>> if detector.is_linux():
        ...     print(detector.libc_version)
        '2.31'
        """
        return self._libc_version
    
    @property
    def is_conda(self) -> bool:
        """
        Check if running in a Conda environment.
        
        Returns
        -------
        bool
            True if in Conda environment, False otherwise.
        """
        return self._is_conda
    
    @property
    def site_packages_paths(self) -> List[Path]:
        """
        Get cached site-packages directory paths.
        
        Returns
        -------
        List[Path]
            List of site-packages paths.
        """
        return self._site_packages_paths.copy()
    
    def get_extensions(self) -> Set[str]:
        """
        Get valid shared library extensions for the current platform.
        
        Returns
        -------
        Set[str]
            Set of file extensions (including dot) for shared libraries.
        
        Examples
        --------
        >>> PlatformDetector().get_extensions()
        {'.so'}  # On Linux
        >>> # On Windows: {'.pyd', '.dll'}
        """
        return _PLATFORM_EXTENSIONS.get(self._platform, {'.so', '.dll', '.dylib'})
    
    def is_windows(self) -> bool:
        """
        Check if running on Windows.
        
        Returns
        -------
        bool
            True if on Windows, False otherwise.
        """
        return self._platform == 'windows'
    
    def is_linux(self) -> bool:
        """
        Check if running on Linux.
        
        Returns
        -------
        bool
            True if on Linux, False otherwise.
        """
        return self._platform == 'linux'
    
    def is_macos(self) -> bool:
        """
        Check if running on macOS.
        
        Returns
        -------
        bool
            True if on macOS, False otherwise.
        """
        return self._platform == 'macos'
    
    def is_unix(self) -> bool:
        """
        Check if running on a Unix-like system (Linux, macOS, BSD).
        
        Returns
        -------
        bool
            True if on Unix-like system, False otherwise.
        """
        return self._platform in ('linux', 'macos', 'freebsd')
    
    def get_library_path_pattern(self, libname: str) -> str:
        """
        Get platform-specific library filename pattern.
        
        Parameters
        ----------
        libname : str
            Base library name without extension or 'lib' prefix.
        
        Returns
        -------
        str
            Platform-specific filename pattern.
        
        Examples
        --------
        >>> detector = PlatformDetector()
        >>> detector.get_library_path_pattern('mylib')
        'libmylib.so'  # On Linux
        >>> # On Windows: 'mylib.dll'
        """
        if self._platform == 'windows':
            return f"{libname}.dll"
        elif self._platform == 'macos':
            return f"lib{libname}.dylib"
        else:  # Linux, BSD
            return f"lib{libname}.so"
    
    def reset(self) -> None:
        """
        Reset the platform detector cache.
        
        This forces re-detection of platform information on next access.
        Useful when the environment changes.
        
        Examples
        --------
        >>> PlatformDetector().reset()
        """
        with self._lock:
            self._detect()


# Global platform detector instance
_PLATFORM = PlatformDetector()


def get_platform() -> PlatformDetector:
    """
    Get the global platform detector instance.
    
    Returns
    -------
    PlatformDetector
        The singleton platform detector instance.
    
    Examples
    --------
    >>> platform = get_platform()
    >>> platform.is_linux()
    True
    """
    return _PLATFORM


# ============================================================================
# Persistent Cache System
# ============================================================================

class PersistentCache:
    """
    Disk-based persistent cache for search results.
    
    This cache survives Python process restarts and significantly
    speeds up repeated searches for the same objects. It uses JSON
    serialization for portability and includes TTL-based expiration.
    
    Attributes
    ----------
    cache_dir : Optional[Path]
        Directory where cache files are stored.
    cache_file : Optional[Path]
        Path to the cache JSON file.
    _cache : Dict[str, Dict[str, Any]]
        In-memory cache dictionary.
    _lock : RLock
        Reentrant lock for thread safety.
    _dirty : bool
        Whether there are unsaved changes.
    _ttl_days : int
        Number of days before cache entries expire.
    
    Examples
    --------
    >>> cache = PersistentCache()
    >>> cache.set('my_key', {'path': '/usr/lib/mylib.so', 'score': 100})
    >>> result = cache.get('my_key')
    >>> print(result['path'])
    '/usr/lib/mylib.so'
    """
    
    def __init__(self, 
                 cache_dir: Optional[Path] = None,
                 ttl_days: int = 30) -> None:
        """
        Initialize the persistent cache.
        
        Parameters
        ----------
        cache_dir : Optional[Path], default=None
            Directory for cache storage. If None, uses configuration.
        ttl_days : int, default=30
            Number of days before cache entries expire.
        """
        self.cache_dir = cache_dir or _config.cache_dir
        self.cache_file = self.cache_dir / 'results.json' if self.cache_dir else None
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = RLock()
        self._dirty = False
        self._ttl_days = ttl_days
        
        if self.cache_file:
            self._load()
            atexit.register(self._save)
    
    def _generate_key(self, *args: Any) -> str:
        """
        Generate a cache key from arguments.
        
        Parameters
        ----------
        *args : Any
            Arguments to hash into a key.
        
        Returns
        -------
        str
            SHA-256 hash string.
        """
        data = json.dumps(args, sort_keys=True, default=str)
        return hashlib.sha256(data.encode()).hexdigest()
    
    def _load(self) -> None:
        """
        Load cache from disk.
        
        This method reads the JSON cache file and filters out expired
        entries based on TTL.
        """
        if not self.cache_file or not self.cache_file.exists():
            return
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                now = time.time()
                ttl_seconds = self._ttl_days * 24 * 3600
                
                with self._lock:
                    self._cache = {
                        k: v for k, v in data.items()
                        if now - v.get('timestamp', 0) < ttl_seconds
                    }
                    
                    # Remove expired entries
                    expired_count = len(data) - len(self._cache)
                    if expired_count > 0:
                        self._dirty = True
                        logger.debug(f"Removed {expired_count} expired cache entries")
        except Exception as e:
            logger.debug(f"Failed to load persistent cache: {e}")
            self._cache = {}
    
    def _save(self) -> None:
        """
        Save cache to disk.
        
        This method writes the cache to a JSON file. It uses a temporary
        file and atomic rename to prevent corruption.
        """
        if not self.cache_file or not self._dirty:
            return
        
        try:
            with self._lock:
                # Write to temporary file first
                temp_file = self.cache_file.with_suffix('.tmp')
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(self._cache, f, indent=2, ensure_ascii=False)
                
                # Atomic rename
                temp_file.replace(self.cache_file)
                self._dirty = False
                
                logger.debug(f"Saved {len(self._cache)} entries to persistent cache")
        except Exception as e:
            logger.debug(f"Failed to save persistent cache: {e}")
    
    def get(self, key: Union[str, Tuple[Any, ...]]) -> Optional[Dict[str, Any]]:
        """
        Get cached result by key.
        
        Parameters
        ----------
        key : Union[str, Tuple[Any, ...]]
            Cache key, either a string or tuple to hash.
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached result dictionary, or None if not found or expired.
        
        Examples
        --------
        >>> cache = PersistentCache()
        >>> result = cache.get('my_library_key')
        >>> if result:
        ...     print(f"Found: {result['path']}")
        """
        if isinstance(key, tuple):
            key = self._generate_key(*key)
        
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                # Verify file still exists
                path = entry.get('path')
                if path and os.path.exists(path):
                    return entry.copy()
                else:
                    # Remove stale entry
                    del self._cache[key]
                    self._dirty = True
                    logger.debug(f"Removed stale cache entry for {key}")
        
        return None
    
    def set(self, key: Union[str, Tuple[Any, ...]], result: Dict[str, Any]) -> None:
        """
        Store result in cache.
        
        Parameters
        ----------
        key : Union[str, Tuple[Any, ...]]
            Cache key, either a string or tuple to hash.
        result : Dict[str, Any]
            Result dictionary to cache.
        
        Examples
        --------
        >>> cache = PersistentCache()
        >>> cache.set('my_key', {
        ...     'path': '/usr/lib/mylib.so',
        ...     'score': 950,
        ...     'confidence': 0.95
        ... })
        """
        if isinstance(key, tuple):
            key = self._generate_key(*key)
        
        with self._lock:
            result['timestamp'] = time.time()
            self._cache[key] = result.copy()
            self._dirty = True
            
            # Auto-save if many entries
            if len(self._cache) % 10 == 0:
                self._save()
    
    def clear(self) -> None:
        """
        Clear all cached entries.
        
        Examples
        --------
        >>> cache = PersistentCache()
        >>> cache.clear()
        """
        with self._lock:
            self._cache.clear()
            self._dirty = True
            self._save()
    
    def remove(self, key: Union[str, Tuple[Any, ...]]) -> bool:
        """
        Remove a specific entry from cache.
        
        Parameters
        ----------
        key : Union[str, Tuple[Any, ...]]
            Cache key to remove.
        
        Returns
        -------
        bool
            True if entry was removed, False if not found.
        """
        if isinstance(key, tuple):
            key = self._generate_key(*key)
        
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._dirty = True
                return True
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with cache statistics.
        """
        with self._lock:
            return {
                'entry_count': len(self._cache),
                'dirty': self._dirty,
                'cache_dir': str(self.cache_dir) if self.cache_dir else None,
                'ttl_days': self._ttl_days,
            }


# Global persistent cache instance
_persistent_cache: Optional[PersistentCache] = None
_cache_lock = Lock()


def get_persistent_cache() -> PersistentCache:
    """
    Get the global persistent cache instance.
    
    Returns
    -------
    PersistentCache
        The singleton persistent cache instance.
    
    Examples
    --------
    >>> cache = get_persistent_cache()
    >>> cache.get_stats()
    {'entry_count': 42, 'dirty': False, ...}
    """
    global _persistent_cache
    
    if _persistent_cache is None:
        with _cache_lock:
            if _persistent_cache is None:
                _persistent_cache = PersistentCache()
    
    return _persistent_cache


# ============================================================================
# Memory Cache with LRU and Weak References
# ============================================================================

class MemoryCache:
    """
    In-memory LRU cache with optional weak references.
    
    This cache provides fast in-memory caching with LRU eviction
    policy and optional weak references to prevent memory leaks.
    
    Attributes
    ----------
    maxsize : int
        Maximum number of items in cache.
    _cache : OrderedDict
        Ordered dictionary for LRU behavior.
    _lock : RLock
        Reentrant lock for thread safety.
    _use_weakref : bool
        Whether to use weak references for values.
    _hits : int
        Number of cache hits.
    _misses : int
        Number of cache misses.
    _evictions : int
        Number of evicted entries.
    """
    
    def __init__(self, maxsize: int = 128, use_weakref: bool = True) -> None:
        """
        Initialize the memory cache.
        
        Parameters
        ----------
        maxsize : int, default=128
            Maximum number of items in cache.
        use_weakref : bool, default=True
            Whether to use weak references for cached values.
        """
        self.maxsize = maxsize
        self._cache: OrderedDict = OrderedDict()
        self._lock = RLock()
        self._use_weakref = use_weakref
        self._hits = 0
        self._misses = 0
        self._evictions = 0
    
    def get(self, key: Any) -> Optional[Any]:
        """
        Get value from cache.
        
        Parameters
        ----------
        key : Any
            Cache key (must be hashable).
        
        Returns
        -------
        Optional[Any]
            Cached value, or None if not found.
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            
            # Move to end for LRU
            value = self._cache.pop(key)
            self._cache[key] = value
            
            self._hits += 1
            
            # Handle weak references
            if self._use_weakref and isinstance(value, weakref.ref):
                return value()
            return value
    
    def set(self, key: Any, value: Any) -> None:
        """
        Store value in cache.
        
        Parameters
        ----------
        key : Any
            Cache key (must be hashable).
        value : Any
            Value to cache.
        """
        with self._lock:
            # Remove existing key
            if key in self._cache:
                del self._cache[key]
            
            # Evict if full
            while len(self._cache) >= self.maxsize:
                self._cache.popitem(last=False)
                self._evictions += 1
            
            # Store value (possibly as weakref)
            if self._use_weakref:
                try:
                    value = weakref.ref(value)
                except TypeError:
                    # Some objects can't be weak referenced
                    pass
            
            self._cache[key] = value
    
    def clear(self) -> None:
        """
        Clear all cached entries.
        """
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with cache statistics.
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            
            return {
                'size': len(self._cache),
                'maxsize': self.maxsize,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': hit_rate,
                'evictions': self._evictions,
            }
    
    def __contains__(self, key: Any) -> bool:
        """Check if key is in cache."""
        with self._lock:
            return key in self._cache
    
    def __len__(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._cache)


# Global memory cache instance
_memory_cache: Optional[MemoryCache] = None


def get_memory_cache() -> MemoryCache:
    """
    Get the global memory cache instance.
    
    Returns
    -------
    MemoryCache
        The singleton memory cache instance.
    """
    global _memory_cache
    
    if _memory_cache is None:
        with _cache_lock:
            if _memory_cache is None:
                _memory_cache = MemoryCache(
                    maxsize=_config.cache_size,
                    use_weakref=_config.use_weakref_cache
                )
    
    return _memory_cache


# ============================================================================
# Result Caching Decorators
# ============================================================================

def cached(func: Callable) -> Callable:
    """
    Decorator for caching function results in memory.
    
    This decorator caches function results using the global memory cache.
    The cache key is generated from the function name and arguments.
    
    Parameters
    ----------
    func : Callable
        Function to cache.
    
    Returns
    -------
    Callable
        Wrapped function with caching.
    
    Examples
    --------
    >>> @cached
    ... def expensive_operation(x, y):
    ...     time.sleep(1)
    ...     return x + y
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Generate cache key
        key_parts = [func.__name__]
        key_parts.extend(str(arg) for arg in args)
        key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
        key = hashlib.md5('|'.join(key_parts).encode()).hexdigest()
        
        cache = get_memory_cache()
        result = cache.get(key)
        
        if result is not None:
            logger.debug(f"Cache hit for {func.__name__}")
            return result
        
        logger.debug(f"Cache miss for {func.__name__}")
        result = func(*args, **kwargs)
        cache.set(key, result)
        
        return result
    
    return wrapper


def persistent_cached(func: Callable) -> Callable:
    """
    Decorator for caching function results on disk.
    
    This decorator caches function results using the persistent cache,
    allowing results to survive between Python sessions.
    
    Parameters
    ----------
    func : Callable
        Function to cache.
    
    Returns
    -------
    Callable
        Wrapped function with persistent caching.
    
    Examples
    --------
    >>> @persistent_cached
    ... def scan_library_file(path, hints):
    ...     # Expensive file scanning
    ...     return result
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not _config.enable_persistent_cache:
            return func(*args, **kwargs)
        
        # Generate cache key
        key_parts = [func.__name__]
        key_parts.extend(str(arg) for arg in args)
        key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
        
        cache = get_persistent_cache()
        result = cache.get(tuple(key_parts))
        
        if result is not None:
            logger.debug(f"Persistent cache hit for {func.__name__}")
            return result.get('value')
        
        logger.debug(f"Persistent cache miss for {func.__name__}")
        result = func(*args, **kwargs)
        cache.set(tuple(key_parts), {'value': result})
        
        return result
    
    return wrapper


# ============================================================================
# Search Strategy Base Classes
# ============================================================================

class SearchStrategy(ABC):
    """
    Abstract base class for search strategies.
    
    This class defines the interface for all search strategies.
    Each strategy represents a different method of locating library files.
    
    Attributes
    ----------
    name : str
        Human-readable name of the strategy.
    strategy_type : StrategyType
        Type category of this strategy.
    priority : int
        Execution priority (lower numbers run first).
    enabled : bool
        Whether this strategy is currently enabled.
    
    Examples
    --------
    >>> class MyStrategy(SearchStrategy):
    ...     name = "my_strategy"
    ...     strategy_type = StrategyType.DIRECT
    ...     priority = 10
    ...     
    ...     def can_execute(self, lib_module, c_obj, hints):
    ...         return True
    ...     
    ...     def execute(self, lib_module, c_obj, hints):
    ...         return MatchResult('/path/to/lib.so', 100, 1.0, self.name, {})
    """
    
    name: str = "base"
    strategy_type: StrategyType = StrategyType.DIRECT
    priority: int = 100
    enabled: bool = True
    
    @abstractmethod
    def can_execute(self, 
                    lib_module: Any, 
                    c_obj: SearchableObject, 
                    hints: Set[str]) -> bool:
        """
        Check if this strategy can be executed in the current context.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        bool
            True if strategy can execute, False otherwise.
        """
        pass
    
    @abstractmethod
    def execute(self, 
                lib_module: Any, 
                c_obj: SearchableObject, 
                hints: Set[str]) -> Optional[MatchResult]:
        """
        Execute the search strategy.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        Optional[MatchResult]
            Match result if found, None otherwise.
        """
        pass
    
    def __repr__(self) -> str:
        """String representation of the strategy."""
        return f"{self.__class__.__name__}(name='{self.name}', priority={self.priority})"


# ============================================================================
# Direct Module File Strategy
# ============================================================================

class DirectModuleFileStrategy(SearchStrategy):
    """
    Strategy that uses the module's __file__ attribute.
    
    This is the fastest and most reliable method. It directly checks
    the __file__ attribute of the module containing the C object.
    
    Confidence: CERTAIN (1.0) when successful.
    
    Examples
    --------
    >>> strategy = DirectModuleFileStrategy()
    >>> strategy.can_execute(np, np.array, {'numpy', 'array'})
    True
    """
    
    name = "direct_module_file"
    strategy_type = StrategyType.DIRECT
    priority = 1
    
    def can_execute(self, 
                    lib_module: Any, 
                    c_obj: SearchableObject, 
                    hints: Set[str]) -> bool:
        """
        This strategy can always attempt execution.
        
        Returns
        -------
        bool
            Always True.
        """
        return True
    
    def execute(self, 
                lib_module: Any, 
                c_obj: SearchableObject, 
                hints: Set[str]) -> Optional[MatchResult]:
        """
        Execute the direct module file strategy.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        Optional[MatchResult]
            Match result if found, None otherwise.
        """
        try:
            # Try to get module from c_obj
            mod = inspect.getmodule(c_obj)
            if not mod:
                mod = lib_module
            
            if mod and hasattr(mod, '__file__') and mod.__file__:
                path = str(Path(mod.__file__).resolve())
                ext = Path(path).suffix.lower()
                
                if ext in _PLATFORM.get_extensions():
                    score = _SCORE_WEIGHTS.direct_module_file
                    
                    return MatchResult(
                        path=path,
                        score=score,
                        confidence=ConfidenceLevel.CERTAIN.value,
                        strategy=self.name,
                        details={
                            'method': '__file__',
                            'module_name': getattr(mod, '__name__', 'unknown'),
                            'extension': ext
                        }
                    )
        except Exception as e:
            logger.debug(f"Direct module file strategy failed: {e}")
        
        return None


# ============================================================================
# dladdr Strategy (POSIX)
# ============================================================================

class DladdrStrategy(SearchStrategy):
    """
    Strategy using POSIX dladdr API to locate shared libraries.
    
    This strategy uses the dladdr function to find the shared library
    containing a function's code address. Works on Linux and macOS.
    
    Confidence: CERTAIN (1.0) when successful.
    
    Limitations:
        - Only works for callable C functions
        - Requires the dl library to be available
        - Not available on Windows
    
    Examples
    --------
    >>> strategy = DladdrStrategy()
    >>> if strategy.can_execute(np, np.dot, set()):
    ...     result = strategy.execute(np, np.dot, set())
    """
    
    name = "dladdr"
    strategy_type = StrategyType.SYSTEM
    priority = 2
    
    def can_execute(self, 
                    lib_module: Any, 
                    c_obj: SearchableObject, 
                    hints: Set[str]) -> bool:
        """
        Check if dladdr can be used.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        bool
            True if on Unix and c_obj is callable.
        """
        return _PLATFORM.is_unix() and callable(c_obj)
    
    def execute(self, 
                lib_module: Any, 
                c_obj: SearchableObject, 
                hints: Set[str]) -> Optional[MatchResult]:
        """
        Execute the dladdr strategy.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        Optional[MatchResult]
            Match result if found, None otherwise.
        """
        if not self.can_execute(lib_module, c_obj, hints):
            return None
        
        try:
            # Get function address
            if hasattr(c_obj, '__code__'):
                addr = ctypes.cast(id(c_obj.__code__), ctypes.c_void_p).value
            else:
                addr = ctypes.cast(id(c_obj), ctypes.c_void_p).value
            
            # Load dl library
            libdl_path = ctypes.util.find_library('dl')
            if not libdl_path:
                return None
            
            libdl = ctypes.CDLL(libdl_path)
            libdl.dladdr.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            libdl.dladdr.restype = ctypes.c_int
            
            # Define Dl_info structure
            class DlInfo(ctypes.Structure):
                _fields_ = [
                    ('dli_fname', ctypes.c_char_p),
                    ('dli_fbase', ctypes.c_void_p),
                    ('dli_sname', ctypes.c_char_p),
                    ('dli_saddr', ctypes.c_void_p)
                ]
            
            info = DlInfo()
            if libdl.dladdr(addr, ctypes.byref(info)):
                if info.dli_fname:
                    path = info.dli_fname.decode('utf-8')
                    
                    # Verify file exists and is a library
                    if os.path.exists(path):
                        ext = Path(path).suffix.lower()
                        if ext in _PLATFORM.get_extensions():
                            score = _SCORE_WEIGHTS.dladdr_success
                            
                            details = {
                                'method': 'dladdr',
                                'symbol_name': info.dli_sname.decode('utf-8') if info.dli_sname else None
                            }
                            
                            return MatchResult(
                                path=path,
                                score=score,
                                confidence=ConfidenceLevel.CERTAIN.value,
                                strategy=self.name,
                                details=details
                            )
        except Exception as e:
            logger.debug(f"dladdr strategy failed: {e}")
        
        return None


# ============================================================================
# Windows Module Handle Strategy
# ============================================================================

class WindowsModuleHandleStrategy(SearchStrategy):
    """
    Strategy using Windows GetModuleHandle API.
    
    This strategy uses the Windows API to get the file path of a
    loaded module by its handle.
    
    Confidence: CERTAIN (1.0) when successful.
    
    Limitations:
        - Windows only
        - Requires the module to have a _handle attribute
    
    Examples
    --------
    >>> strategy = WindowsModuleHandleStrategy()
    >>> if strategy.can_execute(module, obj, set()):
    ...     result = strategy.execute(module, obj, set())
    """
    
    name = "windows_module_handle"
    strategy_type = StrategyType.SYSTEM
    priority = 3
    
    def can_execute(self, 
                    lib_module: Any, 
                    c_obj: SearchableObject, 
                    hints: Set[str]) -> bool:
        """
        Check if Windows API can be used.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        bool
            True if on Windows.
        """
        return _PLATFORM.is_windows()
    
    def execute(self, 
                lib_module: Any, 
                c_obj: SearchableObject, 
                hints: Set[str]) -> Optional[MatchResult]:
        """
        Execute the Windows module handle strategy.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        Optional[MatchResult]
            Match result if found, None otherwise.
        """
        if not self.can_execute(lib_module, c_obj, hints):
            return None
        
        try:
            import ctypes.wintypes
            
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            
            # Try to get module handle
            handle = None
            
            if hasattr(lib_module, '_handle'):
                handle = lib_module._handle
            elif hasattr(c_obj, '_handle'):
                handle = c_obj._handle
            else:
                modname = getattr(lib_module, '__name__', '')
                if modname:
                    handle = kernel32.GetModuleHandleW(modname)
            
            if not handle:
                return None
            
            # Get module filename
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            if kernel32.GetModuleFileNameW(handle, buf, ctypes.wintypes.MAX_PATH):
                path = buf.value
                
                if os.path.exists(path):
                    ext = Path(path).suffix.lower()
                    if ext in _PLATFORM.get_extensions():
                        score = _SCORE_WEIGHTS.windows_module_handle
                        
                        return MatchResult(
                            path=path,
                            score=score,
                            confidence=ConfidenceLevel.CERTAIN.value,
                            strategy=self.name,
                            details={
                                'method': 'GetModuleFileNameW',
                                'handle': handle
                            }
                        )
        except Exception as e:
            logger.debug(f"Windows module handle strategy failed: {e}")
        
        return None


# ============================================================================
# Memory Maps Strategy (Linux)
# ============================================================================

class MemoryMapsStrategy(SearchStrategy):
    """
    Strategy using /proc/pid/maps to find loaded libraries.
    
    This strategy reads the process memory maps on Linux to find
    loaded shared libraries that match the search hints.
    
    Confidence: HIGH (0.8) when successful.
    
    Limitations:
        - Linux only
        - Only finds libraries that are currently loaded
    
    Examples
    --------
    >>> strategy = MemoryMapsStrategy()
    >>> if strategy.can_execute(np, np.dot, {'numpy'}):
    ...     result = strategy.execute(np, np.dot, {'numpy'})
    """
    
    name = "memory_maps"
    strategy_type = StrategyType.MEMORY
    priority = 4
    
    def can_execute(self, 
                    lib_module: Any, 
                    c_obj: SearchableObject, 
                    hints: Set[str]) -> bool:
        """
        Check if memory maps can be read.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        bool
            True if on Linux and /proc/pid/maps exists.
        """
        if not _PLATFORM.is_linux():
            return False
        
        maps_path = f"/proc/{os.getpid()}/maps"
        return os.path.exists(maps_path) and len(hints) > 0
    
    def execute(self, 
                lib_module: Any, 
                c_obj: SearchableObject, 
                hints: Set[str]) -> Optional[MatchResult]:
        """
        Execute the memory maps strategy.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        Optional[MatchResult]
            Match result if found, None otherwise.
        """
        if not self.can_execute(lib_module, c_obj, hints):
            return None
        
        try:
            maps_path = f"/proc/{os.getpid()}/maps"
            patterns = [h.lower() for h in hints if len(h) > 2]
            
            if not patterns:
                return None
            
            with open(maps_path, 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 6:
                        path = parts[-1]
                        
                        # Skip special mappings
                        if path.startswith('[') or path == '[vdso]' or path == '[heap]':
                            continue
                        
                        path_lower = path.lower()
                        
                        # Check if any hint matches
                        matched_pattern = None
                        for pattern in patterns:
                            if pattern in path_lower:
                                matched_pattern = pattern
                                break
                        
                        if matched_pattern:
                            ext = Path(path).suffix.lower()
                            if ext in _PLATFORM.get_extensions():
                                score = _SCORE_WEIGHTS.memory_map_match
                                
                                return MatchResult(
                                    path=path,
                                    score=score,
                                    confidence=ConfidenceLevel.HIGH.value,
                                    strategy=self.name,
                                    details={
                                        'method': '/proc/pid/maps',
                                        'matched_pattern': matched_pattern,
                                        'mapping_line': line.strip()
                                    }
                                )
        except Exception as e:
            logger.debug(f"Memory maps strategy failed: {e}")
        
        return None


# ============================================================================
# ELF Header Analysis Strategy (Linux)
# ============================================================================

class ELFAnalysisStrategy(SearchStrategy):
    """
    Strategy analyzing ELF headers for symbol information.
    
    This strategy parses ELF headers of shared libraries to find
    exported symbols that match the search hints.
    
    Confidence: HIGH (0.8) when successful.
    
    Limitations:
        - Linux only
        - Requires pyelftools library (optional)
        - Only works on ELF files
    
    Examples
    --------
    >>> strategy = ELFAnalysisStrategy()
    >>> if strategy.can_execute(np, np.dot, {'numpy'}):
    ...     result = strategy.execute(np, np.dot, {'numpy'})
    """
    
    name = "elf_analysis"
    strategy_type = StrategyType.HEADER
    priority = 5
    enabled = True
    
    def can_execute(self, 
                    lib_module: Any, 
                    c_obj: SearchableObject, 
                    hints: Set[str]) -> bool:
        """
        Check if ELF analysis can be performed.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        bool
            True if on Linux, enabled, and pyelftools is available.
        """
        if not _PLATFORM.is_linux():
            return False
        
        if not _config.enable_elf_analysis:
            return False
        
        # Check if pyelftools is available
        try:
            import elftools
            return True
        except ImportError:
            logger.debug("pyelftools not available, ELF analysis disabled")
            return False
    
    def _analyze_elf(self, filepath: str, hints: Set[str]) -> Tuple[int, List[str]]:
        """
        Analyze an ELF file for matching symbols.
        
        Parameters
        ----------
        filepath : str
            Path to ELF file.
        hints : Set[str]
            Search hints to match against symbols.
        
        Returns
        -------
        Tuple[int, List[str]]
            (score, list of matched symbols)
        """
        score = 0
        matched_symbols = []
        
        try:
            from elftools.elf.elffile import ELFFile
            
            with open(filepath, 'rb') as f:
                elffile = ELFFile(f)
                
                # Check if it's a shared library
                if elffile.header.e_type != 'ET_DYN':
                    return 0, []
                
                # Get symbol table
                section = elffile.get_section_by_name('.dynsym')
                if not section:
                    section = elffile.get_section_by_name('.symtab')
                
                if section:
                    hint_lower = {h.lower() for h in hints}
                    
                    for symbol in section.iter_symbols():
                        if symbol.name:
                            name_lower = symbol.name.lower()
                            
                            for hint in hint_lower:
                                if hint in name_lower:
                                    score += _SCORE_WEIGHTS.elf_symbol_match
                                    matched_symbols.append(symbol.name)
                                    break
        except Exception as e:
            logger.debug(f"ELF analysis failed for {filepath}: {e}")
        
        return score, matched_symbols
    
    def execute(self, 
                lib_module: Any, 
                c_obj: SearchableObject, 
                hints: Set[str]) -> Optional[MatchResult]:
        """
        Execute the ELF analysis strategy.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        Optional[MatchResult]
            Match result if found, None otherwise.
        """
        if not self.can_execute(lib_module, c_obj, hints):
            return None
        
        # This strategy is typically called with a list of candidate files
        # from other strategies or directory scanning
        return None  # Defer to filesystem scanning


# ============================================================================
# PE Header Analysis Strategy (Windows)
# ============================================================================

class PEAnalysisStrategy(SearchStrategy):
    """
    Strategy analyzing PE headers for export table information.
    
    This strategy parses PE headers of DLL files to find exported
    functions that match the search hints.
    
    Confidence: HIGH (0.8) when successful.
    
    Limitations:
        - Windows only
        - Requires pefile library (optional)
    
    Examples
    --------
    >>> strategy = PEAnalysisStrategy()
    >>> if strategy.can_execute(module, obj, {'mylib'}):
    ...     result = strategy.execute(module, obj, {'mylib'})
    """
    
    name = "pe_analysis"
    strategy_type = StrategyType.HEADER
    priority = 6
    enabled = True
    
    def can_execute(self, 
                    lib_module: Any, 
                    c_obj: SearchableObject, 
                    hints: Set[str]) -> bool:
        """
        Check if PE analysis can be performed.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        bool
            True if on Windows, enabled, and pefile is available.
        """
        if not _PLATFORM.is_windows():
            return False
        
        if not _config.enable_pe_analysis:
            return False
        
        # Check if pefile is available
        try:
            import pefile
            return True
        except ImportError:
            logger.debug("pefile not available, PE analysis disabled")
            return False
    
    def _analyze_pe(self, filepath: str, hints: Set[str]) -> Tuple[int, List[str]]:
        """
        Analyze a PE file for matching exports.
        
        Parameters
        ----------
        filepath : str
            Path to PE file.
        hints : Set[str]
            Search hints to match against exports.
        
        Returns
        -------
        Tuple[int, List[str]]
            (score, list of matched exports)
        """
        score = 0
        matched_exports = []
        
        try:
            import pefile
            
            pe = pefile.PE(filepath)
            
            if hasattr(pe, 'DIRECTORY_ENTRY_EXPORT'):
                hint_lower = {h.lower() for h in hints}
                
                for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                    if exp.name:
                        try:
                            name = exp.name.decode('utf-8')
                            name_lower = name.lower()
                            
                            for hint in hint_lower:
                                if hint in name_lower:
                                    score += _SCORE_WEIGHTS.pe_export_match
                                    matched_exports.append(name)
                                    break
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"PE analysis failed for {filepath}: {e}")
        
        return score, matched_exports
    
    def execute(self, 
                lib_module: Any, 
                c_obj: SearchableObject, 
                hints: Set[str]) -> Optional[MatchResult]:
        """
        Execute the PE analysis strategy.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        Optional[MatchResult]
            Match result if found, None otherwise.
        """
        if not self.can_execute(lib_module, c_obj, hints):
            return None
        
        # This strategy is typically called with candidate files
        return None  # Defer to filesystem scanning


# ============================================================================
# File System Search Strategy
# ============================================================================

class FileSystemSearchStrategy(SearchStrategy):
    """
    Strategy for searching the filesystem for library files.
    
    This strategy scans directories for shared library files and
    scores them based on filename and content matches.
    
    Confidence: MEDIUM to LOW depending on match quality.
    
    Examples
    --------
    >>> strategy = FileSystemSearchStrategy()
    >>> if strategy.can_execute(np, np.dot, {'numpy'}):
    ...     result = strategy.execute(np, np.dot, {'numpy'})
    """
    
    name = "filesystem_search"
    strategy_type = StrategyType.FILESYSTEM
    priority = 100
    
    def can_execute(self, 
                    lib_module: Any, 
                    c_obj: SearchableObject, 
                    hints: Set[str]) -> bool:
        """
        This strategy can always attempt execution.
        
        Returns
        -------
        bool
            Always True if hints are available.
        """
        return len(hints) > 0
    
    def _get_search_roots(self, 
                          lib_module: Any, 
                          c_obj: SearchableObject) -> List[Path]:
        """
        Determine directories to search.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        
        Returns
        -------
        List[Path]
            List of directories to search.
        """
        roots = []
        
        # From lib_module
        if hasattr(lib_module, '__file__') and lib_module.__file__:
            mod_dir = Path(lib_module.__file__).resolve().parent
            roots.append(mod_dir)
            
            # Also check parent directories
            for parent in mod_dir.parents[:2]:
                if parent not in roots:
                    roots.append(parent)
        
        # From c_obj's module
        c_mod = inspect.getmodule(c_obj)
        if c_mod and hasattr(c_mod, '__file__') and c_mod.__file__:
            mod_dir = Path(c_mod.__file__).resolve().parent
            if mod_dir not in roots:
                roots.append(mod_dir)
        
        # Site-packages (priority)
        if _config.site_packages_priority:
            for sp_path in _PLATFORM.site_packages_paths:
                if sp_path.exists() and sp_path not in roots:
                    roots.append(sp_path)
        
        # Python path
        for p in sys.path:
            if p and os.path.exists(p):
                p_path = Path(p)
                if p_path not in roots:
                    # Prioritize paths with site-packages or dist-packages
                    if 'site-packages' in p or 'dist-packages' in p:
                        roots.insert(0, p_path)
                    else:
                        roots.append(p_path)
        
        # Current directory
        cwd = Path.cwd()
        if cwd not in roots:
            roots.append(cwd)
        
        return roots[:10]  # Limit to 10 roots
    
    def _scan_file(self, 
                   filepath: Path, 
                   hints: Set[str]) -> Tuple[int, Dict[str, Any]]:
        """
        Scan a single file for matching hints.
        
        Parameters
        ----------
        filepath : Path
            Path to file to scan.
        hints : Set[str]
            Search hints to look for.
        
        Returns
        -------
        Tuple[int, Dict[str, Any]]
            (score, match_details)
        """
        score = 0
        details = {}
        
        try:
            # Check file size
            size = filepath.stat().st_size
            if size > _config.max_file_size_mb * 1024 * 1024:
                return 0, {}
            
            fname = filepath.name.lower()
            stem = filepath.stem.lower()
            path_str = str(filepath).lower()
            matched_hints = []
            
            # 1. Filename scoring
            for hint in hints:
                hint_lower = hint.lower()
                
                # Exact match
                if hint_lower == stem or hint_lower == fname:
                    score += _SCORE_WEIGHTS.exact_filename
                    matched_hints.append(hint)
                    details['exact_match'] = hint
                # Partial match using word boundaries
                elif re.search(rf'\b{re.escape(hint_lower)}\b', fname):
                    score += _SCORE_WEIGHTS.partial_filename
                    matched_hints.append(hint)
                    details.setdefault('partial_matches', []).append(hint)
            
            # 2. Module path match
            for hint in hints:
                if hint.lower() in path_str:
                    score += _SCORE_WEIGHTS.module_path_match
                    break
            
            # 3. Python version in filename
            for pattern in _PYTHON_VERSION_PATTERNS:
                match = pattern.search(fname)
                if match:
                    groups = match.groups()
                    if len(groups) >= 2:
                        version = f"{groups[0]}{groups[1]}"
                        if version == _PLATFORM.python_version:
                            score += _SCORE_WEIGHTS.python_version_match
                            details['python_version_match'] = version
                            break
            
            # 4. Priority directory bonus
            for prio_dir in _PRIORITY_DIRS:
                if prio_dir.lower() in path_str:
                    score += _SCORE_WEIGHTS.directory_priority
                    details['priority_directory'] = prio_dir
                    break
            
            # 5. Site-packages bonus
            if 'site-packages' in path_str or 'dist-packages' in path_str:
                score += _SCORE_WEIGHTS.site_packages_match
                details['in_site_packages'] = True
            
            # 6. Content scanning (only if filename scored well)
            if score > 0:
                try:
                    with open(filepath, 'rb') as f:
                        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                            # Only scan first 10MB
                            scan_size = min(mm.size(), 10 * 1024 * 1024)
                            data = mm[:scan_size]
                            
                            for hint in hints:
                                hint_bytes = hint.encode('utf-8', errors='ignore')
                                if hint_bytes in data:
                                    score += _SCORE_WEIGHTS.content_pattern
                                    details.setdefault('content_matches', []).append(hint)
                                    
                                    # Check for PyInit_ symbol
                                    pyinit = f"PyInit_{hint}".encode()
                                    if pyinit in data:
                                        score += _SCORE_WEIGHTS.symbol_table_match
                                        details['has_pyinit'] = hint
                except Exception:
                    pass
            
            # 7. ELF/PE analysis if available
            if _config.enable_elf_analysis and _PLATFORM.is_linux():
                elf_strategy = ELFAnalysisStrategy()
                elf_score, symbols = elf_strategy._analyze_elf(str(filepath), hints)
                if elf_score > 0:
                    score += elf_score
                    details['elf_symbols'] = symbols
            
            if _config.enable_pe_analysis and _PLATFORM.is_windows():
                pe_strategy = PEAnalysisStrategy()
                pe_score, exports = pe_strategy._analyze_pe(str(filepath), hints)
                if pe_score > 0:
                    score += pe_score
                    details['pe_exports'] = exports
            
            details['matched_hints'] = matched_hints
            
        except Exception as e:
            logger.debug(f"Failed to scan {filepath}: {e}")
        
        return score, details
    
    def _find_in_directory(self, 
                           root_dir: Path, 
                           hints: Set[str],
                           max_files: int) -> List[Tuple[int, Path, Dict[str, Any]]]:
        """
        Search a directory for matching library files.
        
        Parameters
        ----------
        root_dir : Path
            Root directory to search.
        hints : Set[str]
            Search hints.
        max_files : int
            Maximum number of files to scan.
        
        Returns
        -------
        List[Tuple[int, Path, Dict[str, Any]]]
            List of (score, filepath, details) sorted by score.
        """
        if not root_dir.exists() or not root_dir.is_dir():
            return []
        
        extensions = _PLATFORM.get_extensions()
        files_found = []
        
        # Collect files
        for ext in extensions:
            try:
                pattern = f"*{ext}"
                for file in root_dir.rglob(pattern):
                    if file.is_file():
                        # Check depth
                        depth = len(file.relative_to(root_dir).parts)
                        if depth <= _config.max_search_depth:
                            files_found.append(file)
                            if len(files_found) >= max_files:
                                break
                if len(files_found) >= max_files:
                    break
            except (PermissionError, OSError):
                continue
        
        if not files_found:
            return []
        
        # Score files in parallel
        results = []
        with ThreadPoolExecutor(max_workers=_config.max_workers) as executor:
            future_to_file = {
                executor.submit(self._scan_file, f, hints): f
                for f in files_found[:max_files]
            }
            
            for future in as_completed(future_to_file):
                try:
                    score, details = future.result(timeout=5)
                    if score > 0:
                        results.append((score, future_to_file[future], details))
                except Exception as e:
                    logger.debug(f"Scan failed: {e}")
        
        results.sort(key=lambda x: x[0], reverse=True)
        return results[:20]
    
    def execute(self, 
                lib_module: Any, 
                c_obj: SearchableObject, 
                hints: Set[str]) -> Optional[MatchResult]:
        """
        Execute the filesystem search strategy.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        Optional[MatchResult]
            Match result if found, None otherwise.
        """
        if not self.can_execute(lib_module, c_obj, hints):
            return None
        
        search_roots = self._get_search_roots(lib_module, c_obj)
        
        # Adjust max files based on mode
        max_files = _config.max_files_to_scan
        
        best_score = 0
        best_path = None
        best_details = {}
        
        for root in search_roots[:5]:  # Limit to 5 roots
            logger.debug(f"Searching in {root}")
            results = self._find_in_directory(root, hints, max_files // len(search_roots))
            
            for score, path, details in results:
                if score > best_score:
                    best_score = score
                    best_path = path
                    best_details = details
        
        if best_path:
            # Calculate confidence using logarithmic scaling
            max_possible = (
                _SCORE_WEIGHTS.exact_filename +
                _SCORE_WEIGHTS.partial_filename +
                _SCORE_WEIGHTS.symbol_table_match +
                _SCORE_WEIGHTS.content_pattern
            )
            confidence = 1.0 - (1.0 / (1.0 + best_score / 100))
            confidence = min(1.0, max(0.0, confidence))
            
            return MatchResult(
                path=str(best_path),
                score=best_score,
                confidence=confidence,
                strategy=self.name,
                details=best_details
            )
        
        return None


# ============================================================================
# Strategy Manager
# ============================================================================

class StrategyManager:
    """
    Manages and orchestrates search strategies.
    
    This class coordinates multiple search strategies, executing them
    in priority order and returning the first successful result.
    
    Attributes
    ----------
    strategies : List[SearchStrategy]
        List of registered strategies sorted by priority.
    _instance : Optional[StrategyManager]
        Singleton instance.
    
    Examples
    --------
    >>> manager = StrategyManager()
    >>> manager.register(DirectModuleFileStrategy())
    >>> result = manager.execute_all(np, np.dot, {'numpy'})
    """
    
    _instance: Optional['StrategyManager'] = None
    _lock: Lock = Lock()
    
    def __new__(cls) -> 'StrategyManager':
        """Create or return singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance
    
    def _initialize(self) -> None:
        """Initialize with default strategies."""
        self._strategies: List[SearchStrategy] = []
        self._strategy_lock = RLock()
        
        # Register default strategies
        self.register(DirectModuleFileStrategy())
        self.register(DladdrStrategy())
        self.register(WindowsModuleHandleStrategy())
        self.register(MemoryMapsStrategy())
        self.register(ELFAnalysisStrategy())
        self.register(PEAnalysisStrategy())
        self.register(FileSystemSearchStrategy())
    
    def register(self, strategy: SearchStrategy) -> None:
        """
        Register a search strategy.
        
        Parameters
        ----------
        strategy : SearchStrategy
            Strategy to register.
        
        Examples
        --------
        >>> manager = StrategyManager()
        >>> manager.register(MyCustomStrategy())
        """
        with self._strategy_lock:
            self._strategies.append(strategy)
            self._strategies.sort(key=lambda s: s.priority)
    
    def unregister(self, strategy_name: str) -> bool:
        """
        Unregister a strategy by name.
        
        Parameters
        ----------
        strategy_name : str
            Name of strategy to remove.
        
        Returns
        -------
        bool
            True if removed, False if not found.
        """
        with self._strategy_lock:
            for i, s in enumerate(self._strategies):
                if s.name == strategy_name:
                    self._strategies.pop(i)
                    return True
        return False
    
    def get_strategies(self) -> List[SearchStrategy]:
        """
        Get list of registered strategies.
        
        Returns
        -------
        List[SearchStrategy]
            Copy of strategy list.
        """
        with self._strategy_lock:
            return self._strategies.copy()
    
    def execute_all(self, 
                    lib_module: Any, 
                    c_obj: SearchableObject, 
                    hints: Set[str],
                    stop_on_first: bool = True) -> List[MatchResult]:
        """
        Execute all applicable strategies.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        stop_on_first : bool, default=True
            Whether to stop after first successful result.
        
        Returns
        -------
        List[MatchResult]
            List of match results from strategies.
        
        Examples
        --------
        >>> manager = StrategyManager()
        >>> results = manager.execute_all(np, np.dot, {'numpy'})
        >>> for r in results:
        ...     print(f"{r.strategy}: {r.path}")
        """
        results = []
        
        with self._strategy_lock:
            strategies = [s for s in self._strategies if s.enabled]
        
        for strategy in strategies:
            if not strategy.can_execute(lib_module, c_obj, hints):
                continue
            
            logger.debug(f"Executing strategy: {strategy.name}")
            
            try:
                result = strategy.execute(lib_module, c_obj, hints)
                if result:
                    results.append(result)
                    logger.info(f"Strategy {strategy.name} found: {result.path}")
                    
                    if stop_on_first:
                        break
            except Exception as e:
                logger.warning(f"Strategy {strategy.name} failed: {e}")
        
        return results
    
    def execute_best(self, 
                     lib_module: Any, 
                     c_obj: SearchableObject, 
                     hints: Set[str]) -> Optional[MatchResult]:
        """
        Execute strategies and return the best result.
        
        Parameters
        ----------
        lib_module : Any
            Python module containing the C extension.
        c_obj : SearchableObject
            C function, method, or class to locate.
        hints : Set[str]
            Collected search hints.
        
        Returns
        -------
        Optional[MatchResult]
            Best match result, or None if not found.
        """
        results = self.execute_all(lib_module, c_obj, hints, stop_on_first=False)
        
        if not results:
            return None
        
        # Sort by confidence, then score
        results.sort(key=lambda r: (r.confidence, r.score), reverse=True)
        return results[0]
    
    def reset(self) -> None:
        """Reset to default strategies."""
        with self._strategy_lock:
            self._strategies.clear()
            self._initialize()


def get_strategy_manager() -> StrategyManager:
    """
    Get the global strategy manager instance.
    
    Returns
    -------
    StrategyManager
        The singleton strategy manager.
    
    Examples
    --------
    >>> manager = get_strategy_manager()
    >>> manager.get_strategies()
    [DirectModuleFileStrategy, DladdrStrategy, ...]
    """
    return StrategyManager()


# ============================================================================
# Hint Collection
# ============================================================================

def clean_hint(hint: str) -> Optional[str]:
    """
    Clean and normalize a hint string.
    
    Parameters
    ----------
    hint : str
        Raw hint string.
    
    Returns
    -------
    Optional[str]
        Cleaned hint, or None if too short.
    
    Examples
    --------
    >>> clean_hint("numpy_v1.0")
    'numpy'
    >>> clean_hint("_abc_")
    'abc'
    """
    if not hint or not isinstance(hint, str):
        return None
    
    # Apply cleanup patterns
    for pattern in _HINT_CLEANUP_PATTERNS:
        hint = pattern.sub('', hint)
    
    # Remove leading/trailing underscores and whitespace
    hint = hint.strip('_').strip()
    
    # Check minimum length
    if len(hint) < _config.min_hint_length:
        return None
    
    return hint


def collect_hints(lib_module: Any, 
                  c_obj: SearchableObject, 
                  additional_hints: Optional[Set[str]] = None) -> Set[str]:
    """
    Extract search hints from Python objects.
    
    This function collects potential search strings from various attributes
    of the provided objects to guide the library search process.
    
    Parameters
    ----------
    lib_module : Any
        Python module containing the C extension (e.g., numpy, cv2).
    c_obj : SearchableObject
        C function, method, or class to locate (e.g., numpy.dot, cv2.imread).
    additional_hints : Optional[Set[str]], default=None
        User-provided additional hints to supplement automatic collection.
    
    Returns
    -------
    Set[str]
        Unique set of cleaned hint strings for searching.
    
    Examples
    --------
    >>> import numpy as np
    >>> hints = collect_hints(np, np.array)
    >>> print(hints)
    {'numpy', 'array', 'ndarray', 'core'}
    
    >>> # With additional hints
    >>> hints = collect_hints(np, np.linalg.inv, {'lapack', 'blas'})
    >>> 'lapack' in hints
    True
    """
    hints = set()
    
    def add_hint(hint_str: str) -> None:
        """Add a hint after cleaning."""
        cleaned = clean_hint(hint_str)
        if cleaned:
            hints.add(cleaned)
            hints.add(cleaned.lower())
    
    # 1. Object name attributes
    for attr in ['__name__', '__qualname__', '_name', 'name']:
        if hasattr(c_obj, attr):
            name = getattr(c_obj, attr)
            if isinstance(name, str):
                add_hint(name)
                
                # Split by common separators
                for part in re.split(r'[._\-]', name):
                    add_hint(part)
    
    # 2. Class name for instances
    if not hasattr(c_obj, '__name__') and not isinstance(c_obj, type):
        class_name = c_obj.__class__.__name__
        add_hint(class_name)
    
    # 3. Module name
    modname = getattr(c_obj, '__module__', '')
    if modname and isinstance(modname, str):
        for part in modname.split('.'):
            add_hint(part)
        
        # Package name (first part)
        parts = modname.split('.')
        if parts:
            add_hint(parts[0])
    
    # 4. Library module name
    if hasattr(lib_module, '__name__'):
        lib_name = lib_module.__name__
        if isinstance(lib_name, str):
            add_hint(lib_name)
            
            for part in lib_name.split('.'):
                add_hint(part)
    
    # 5. File-based hints
    for mod in [lib_module, inspect.getmodule(c_obj)]:
        if mod and hasattr(mod, '__file__') and mod.__file__:
            try:
                path = Path(mod.__file__)
                stem = path.stem
                add_hint(stem)
                
                # Parent directory name
                parent = path.parent.name
                add_hint(parent)
            except Exception:
                pass
    
    # 6. Docstring hints
    if hasattr(c_obj, '__doc__') and c_obj.__doc__:
        doc = c_obj.__doc__
        # Look for library mentions
        lib_patterns = [r'lib(\w+)', r'(\w+)\.so', r'(\w+)\.dll']
        for pattern in lib_patterns:
            for match in re.finditer(pattern, doc, re.IGNORECASE):
                add_hint(match.group(1))
    
    # 7. Type hints for callable
    if callable(c_obj):
        try:
            sig = inspect.signature(c_obj)
            for param in sig.parameters.values():
                if param.annotation != inspect.Parameter.empty:
                    anno_str = str(param.annotation)
                    add_hint(anno_str)
        except Exception:
            pass
    
    # 8. Additional user hints
    if additional_hints:
        for hint in additional_hints:
            if isinstance(hint, str):
                add_hint(hint)
    
    # Remove empty strings and duplicates
    hints.discard('')
    
    logger.debug(f"Collected {len(hints)} hints: {sorted(list(hints))[:15]}")
    return hints


# ============================================================================
# Main Public API
# ============================================================================

def _calculate_confidence(score: int, max_possible: Optional[int] = None) -> float:
    """
    Calculate confidence value from raw score.
    
    Parameters
    ----------
    score : int
        Raw match score.
    max_possible : Optional[int], default=None
        Maximum possible score for normalization.
    
    Returns
    -------
    float
        Confidence value between 0.0 and 1.0.
    """
    if max_possible and max_possible > 0:
        normalized = min(1.0, score / max_possible)
    else:
        # Logarithmic scaling
        normalized = 1.0 - (1.0 / (1.0 + score / 100))
    
    return min(1.0, max(0.0, normalized))


def guess_file(lib_module: Any, 
               c_obj: SearchableObject,
               mode: Union[str, ScanMode] = ScanMode.BALANCED,
               additional_hints: Optional[Set[str]] = None,
               min_confidence: Optional[float] = None) -> Optional[str]:
    """
    Locate the C-extension file associated with a Python object.
    
    This function uses multiple strategies in order of speed:
        1. Direct module __file__ attribute (fastest)
        2. dladdr POSIX API (Linux/macOS)
        3. Windows module handle API
        4. Memory map scanning (/proc/pid/maps)
        5. ELF/PE header analysis
        6. Directory search with file scanning (slowest)
    
    Parameters
    ----------
    lib_module : Any
        Python module containing the C extension (e.g., numpy, cv2).
        This should be the imported module object.
    c_obj : SearchableObject
        C function, method, or class to locate (e.g., numpy.dot, cv2.imread).
        This is the object whose containing library you want to find.
    mode : Union[str, ScanMode], default=ScanMode.BALANCED
        Scanning mode balancing speed vs accuracy:
            - 'fastest' or ScanMode.FASTEST: Direct methods only, no file scanning
            - 'balanced' or ScanMode.BALANCED: Limited file scanning (default)
            - 'thorough' or ScanMode.THOROUGH: Full scanning, slower but more accurate
    additional_hints : Optional[Set[str]], default=None
        Extra search hints to improve matching. Useful for libraries with
        non-obvious naming or when automatic hint collection is insufficient.
    min_confidence : Optional[float], default=None
        Minimum confidence score (0.0 to 1.0) required to return a result.
        If None, uses the value from configuration.
    
    Returns
    -------
    Optional[str]
        Absolute path to the library file if found with sufficient confidence,
        None otherwise.
    
    Raises
    ------
    ValueError
        If lib_module or c_obj is None, or if mode is invalid.
    
    Examples
    --------
    >>> import numpy as np
    
    >>> # Basic usage
    >>> path = guess_file(np, np.dot)
    >>> print(path)
    '/usr/lib/python3/dist-packages/numpy/core/_multiarray_umath.so'
    
    >>> # Fast mode (no disk scanning)
    >>> path = guess_file(np, np.array, mode='fastest')
    
    >>> # With additional hints
    >>> path = guess_file(np, np.linalg.inv, 
    ...                   additional_hints={'lapack', 'blas'})
    
    >>> # For OpenCV
    >>> import cv2
    >>> path = guess_file(cv2, cv2.imread)
    >>> print(path)
    '/usr/lib/python3/dist-packages/cv2/cv2.so'
    
    >>> # With confidence threshold
    >>> path = guess_file(unknown_module, unknown_func, min_confidence=0.8)
    >>> if path is None:
    ...     print("No high-confidence match found")
    
    Notes
    -----
    - The function uses an internal cache to speed up repeated queries.
    - On first run, file scanning may take a few seconds. Subsequent runs
      are much faster due to caching.
    - The BALANCED mode is recommended for most use cases.
    - For maximum accuracy when fast methods fail, use THOROUGH mode.
    """
    # Validate inputs
    if lib_module is None:
        raise ValueError("lib_module cannot be None")
    if c_obj is None:
        raise ValueError("c_obj cannot be None")
    
    # Convert string mode to enum
    if isinstance(mode, str):
        try:
            mode = ScanMode(mode.lower())
        except ValueError:
            raise ValueError(f"Invalid mode: '{mode}'. Valid modes: {[m.value for m in ScanMode]}")
    
    # Set min_confidence
    if min_confidence is None:
        min_confidence = _config.confidence_threshold
    
    # Check memory cache first
    cache_key = (
        getattr(lib_module, '__name__', str(lib_module)),
        id(c_obj),
        getattr(c_obj, '__name__', str(c_obj)),
        mode.value
    )
    
    memory_cache = get_memory_cache()
    cached_result = memory_cache.get(cache_key)
    if cached_result:
        logger.debug(f"Memory cache hit for {cache_key}")
        if cached_result.get('confidence', 0) >= min_confidence:
            return cached_result.get('path')
        return None
    
    # Check persistent cache
    if _config.enable_persistent_cache:
        persistent_cache = get_persistent_cache()
        persistent_key = (
            'guess_file',
            getattr(lib_module, '__name__', str(lib_module)),
            getattr(c_obj, '__name__', str(type(c_obj))),
            mode.value,
            tuple(sorted(additional_hints)) if additional_hints else ()
        )
        cached = persistent_cache.get(persistent_key)
        if cached:
            logger.debug(f"Persistent cache hit for {persistent_key}")
            result = cached.get('value', {})
            if result.get('confidence', 0) >= min_confidence:
                memory_cache.set(cache_key, result)
                return result.get('path')
    
    # Collect hints
    hints = collect_hints(lib_module, c_obj, additional_hints)
    if not hints:
        logger.debug("No hints collected")
        return None
    
    # Get strategy manager
    manager = get_strategy_manager()
    
    # Determine which strategies to use based on mode
    result = None
    start_time = time.time()
    
    if mode == ScanMode.FASTEST:
        # Use only direct strategies
        strategies_to_use = [
            s for s in manager.get_strategies()
            if s.strategy_type in (StrategyType.DIRECT, StrategyType.SYSTEM)
        ]
        
        for strategy in strategies_to_use:
            if time.time() - start_time > _config.global_timeout:
                break
            
            if strategy.can_execute(lib_module, c_obj, hints):
                try:
                    result = strategy.execute(lib_module, c_obj, hints)
                    if result and result.confidence >= min_confidence:
                        break
                except Exception as e:
                    logger.debug(f"Strategy {strategy.name} error: {e}")
    
    elif mode == ScanMode.BALANCED:
        # Use all except thorough filesystem scanning
        result = manager.execute_best(lib_module, c_obj, hints)
        
        if not result or result.confidence < min_confidence:
            # Try filesystem search with limits
            fs_strategy = FileSystemSearchStrategy()
            if fs_strategy.can_execute(lib_module, c_obj, hints):
                try:
                    # Temporarily reduce max files
                    original_max = _config.max_files_to_scan
                    _config.max_files_to_scan = min(100, original_max)
                    
                    result = fs_strategy.execute(lib_module, c_obj, hints)
                    
                    _config.max_files_to_scan = original_max
                except Exception as e:
                    logger.debug(f"Filesystem strategy error: {e}")
    
    else:  # THOROUGH
        # Use all strategies including full filesystem search
        result = manager.execute_best(lib_module, c_obj, hints)
    
    # Process result
    if result and result.confidence >= min_confidence:
        output = {
            'path': result.path,
            'score': result.score,
            'confidence': result.confidence,
            'strategy': result.strategy,
            'details': result.details if _config.debug_mode else {}
        }
        
        # Cache the result
        memory_cache.set(cache_key, output)
        
        if _config.enable_persistent_cache:
            persistent_key = (
                'guess_file',
                getattr(lib_module, '__name__', str(lib_module)),
                getattr(c_obj, '__name__', str(type(c_obj))),
                mode.value,
                tuple(sorted(additional_hints)) if additional_hints else ()
            )
            persistent_cache = get_persistent_cache()
            persistent_cache.set(persistent_key, {'value': output})
        
        logger.info(f"Found: {result.path} (strategy: {result.strategy}, "
                   f"confidence: {result.confidence:.2f})")
        return result.path
    
    logger.debug(f"No matching file found with confidence >= {min_confidence}")
    return None


def guess_file_with_details(lib_module: Any,
                            c_obj: SearchableObject,
                            mode: Union[str, ScanMode] = ScanMode.BALANCED,
                            additional_hints: Optional[Set[str]] = None,
                            min_confidence: Optional[float] = None) -> Dict[str, Any]:
    """
    Locate C-extension file and return detailed information.
    
    This function works identically to `guess_file` but returns a
    dictionary with full details about the search process and result.
    
    Parameters
    ----------
    lib_module : Any
        Python module containing the C extension.
    c_obj : SearchableObject
        C function, method, or class to locate.
    mode : Union[str, ScanMode], default=ScanMode.BALANCED
        Scanning mode balancing speed vs accuracy.
    additional_hints : Optional[Set[str]], default=None
        Extra search hints to improve matching.
    min_confidence : Optional[float], default=None
        Minimum confidence score required.
    
    Returns
    -------
    Dict[str, Any]
        Dictionary containing:
            - 'path': str or None - The found file path
            - 'found': bool - Whether a file was found
            - 'score': int - Raw match score
            - 'confidence': float - Normalized confidence (0.0-1.0)
            - 'strategy': str - Name of strategy that found the match
            - 'hints': List[str] - Hints used for search
            - 'details': Dict - Additional details about the match
            - 'elapsed_time': float - Search duration in seconds
    
    Examples
    --------
    >>> import numpy as np
    >>> details = guess_file_with_details(np, np.dot)
    >>> print(f"Found: {details['found']}")
    >>> print(f"Path: {details['path']}")
    >>> print(f"Confidence: {details['confidence']:.2f}")
    >>> print(f"Strategy: {details['strategy']}")
    
    >>> # Inspect match details
    >>> if details['details']:
    ...     for key, value in details['details'].items():
    ...         print(f"  {key}: {value}")
    """
    start_time = time.time()
    
    # Temporarily enable debug mode
    original_debug = _config.debug_mode
    _config.debug_mode = True
    
    try:
        # Collect hints
        hints = collect_hints(lib_module, c_obj, additional_hints)
        
        # Find file
        path = guess_file(lib_module, c_obj, mode, additional_hints, min_confidence)
        
        # Get cached result for details
        cache_key = (
            getattr(lib_module, '__name__', str(lib_module)),
            id(c_obj),
            getattr(c_obj, '__name__', str(c_obj)),
            mode.value if isinstance(mode, ScanMode) else mode
        )
        
        memory_cache = get_memory_cache()
        cached = memory_cache.get(cache_key)
        
        elapsed = time.time() - start_time
        
        if cached:
            return {
                'path': cached.get('path'),
                'found': cached.get('path') is not None,
                'score': cached.get('score', 0),
                'confidence': cached.get('confidence', 0.0),
                'strategy': cached.get('strategy', 'unknown'),
                'hints': sorted(list(hints)),
                'details': cached.get('details', {}),
                'elapsed_time': elapsed
            }
        else:
            return {
                'path': path,
                'found': path is not None,
                'score': 0,
                'confidence': 0.0,
                'strategy': 'none',
                'hints': sorted(list(hints)),
                'details': {},
                'elapsed_time': elapsed
            }
    finally:
        _config.debug_mode = original_debug


def guess_file_simple(lib_module: Any, c_obj: SearchableObject) -> Optional[str]:
    """
    Simplified version with balanced default settings.
    
    This is a convenience wrapper around `guess_file` with sensible defaults
    for common use cases.
    
    Parameters
    ----------
    lib_module : Any
        Python module containing the C extension.
    c_obj : SearchableObject
        C function, method, or class to locate.
    
    Returns
    -------
    Optional[str]
        Path to library file if found, None otherwise.
    
    Examples
    --------
    >>> import numpy as np
    >>> path = guess_file_simple(np, np.dot)
    >>> print(path)
    '/usr/lib/python3/dist-packages/numpy/core/_multiarray_umath.so'
    
    >>> import cv2
    >>> path = guess_file_simple(cv2, cv2.imread)
    """
    return guess_file(lib_module, c_obj, mode=ScanMode.BALANCED)


def guess_file_fast(lib_module: Any, c_obj: SearchableObject) -> Optional[str]:
    """
    Fast version with minimal overhead, no disk scanning.
    
    Use this when you need speed and are confident the library is
    already loaded or directly accessible. Only uses direct methods
    and system APIs.
    
    Parameters
    ----------
    lib_module : Any
        Python module containing the C extension.
    c_obj : SearchableObject
        C function, method, or class to locate.
    
    Returns
    -------
    Optional[str]
        Path to library file if found, None otherwise.
    
    Examples
    --------
    >>> import numpy as np
    >>> # Fast mode - uses only __file__ or dladdr
    >>> path = guess_file_fast(np, np.dot)
    """
    return guess_file(lib_module, c_obj, mode=ScanMode.FASTEST)


def guess_file_thorough(lib_module: Any,
                        c_obj: SearchableObject,
                        additional_hints: Optional[Set[str]] = None) -> Optional[str]:
    """
    Thorough version with maximum accuracy, slower but more comprehensive.
    
    Use this when fast methods fail and you need to find the file
    regardless of performance cost. Performs full filesystem search
    and binary analysis.
    
    Parameters
    ----------
    lib_module : Any
        Python module containing the C extension.
    c_obj : SearchableObject
        C function, method, or class to locate.
    additional_hints : Optional[Set[str]], default=None
        Extra search hints to improve matching.
    
    Returns
    -------
    Optional[str]
        Path to library file if found, None otherwise.
    
    Examples
    --------
    >>> import numpy as np
    >>> # Thorough search for a complex function
    >>> path = guess_file_thorough(np, np.linalg.eig,
    ...                            additional_hints={'lapack', 'blas'})
    >>> print(path)
    '/usr/lib/python3/dist-packages/numpy/linalg/lapack_lite.so'
    """
    return guess_file(lib_module, c_obj, mode=ScanMode.THOROUGH,
                     additional_hints=additional_hints)


def locate_multiple(objects: List[Tuple[Any, SearchableObject]],
                    mode: Union[str, ScanMode] = ScanMode.BALANCED,
                    max_workers: Optional[int] = None,
                    min_confidence: Optional[float] = None,
                    return_details: bool = False) -> Dict[Any, Any]:
    """
    Locate files for multiple C-extension objects in parallel.
    
    This function efficiently processes multiple objects using a thread pool,
    making it ideal for batch operations.
    
    Parameters
    ----------
    objects : List[Tuple[Any, SearchableObject]]
        List of (lib_module, c_obj) tuples to locate.
    mode : Union[str, ScanMode], default=ScanMode.BALANCED
        Scanning mode for all searches.
    max_workers : Optional[int], default=None
        Maximum number of parallel workers. If None, uses configuration value.
    min_confidence : Optional[float], default=None
        Minimum confidence threshold. If None, uses configuration value.
    return_details : bool, default=False
        If True, returns detailed dictionaries instead of just paths.
    
    Returns
    -------
    Dict[Any, Any]
        Mapping from c_obj to result. The result is either:
            - str: File path (if return_details=False)
            - Dict: Detailed information (if return_details=True)
        If not found, the value is None (or dict with 'found': False).
    
    Examples
    --------
    >>> import numpy as np
    >>> objects = [
    ...     (np, np.dot),
    ...     (np, np.array),
    ...     (np, np.linalg.inv),
    ... ]
    >>> results = locate_multiple(objects)
    >>> for obj, path in results.items():
    ...     if path:
    ...         print(f"{obj.__name__}: {path}")
    ...     else:
    ...         print(f"{obj.__name__}: not found")
    
    >>> # With detailed results
    >>> details = locate_multiple(objects, return_details=True)
    >>> for obj, info in details.items():
    ...     print(f"{obj.__name__}: confidence={info['confidence']:.2f}")
    """
    if max_workers is None:
        max_workers = _config.max_workers
    
    results = {}
    
    def locate_one(lib_module: Any, c_obj: SearchableObject) -> Tuple[Any, Any]:
        """Helper function for parallel execution."""
        if return_details:
            result = guess_file_with_details(
                lib_module, c_obj, mode, min_confidence=min_confidence
            )
        else:
            result = guess_file(
                lib_module, c_obj, mode, min_confidence=min_confidence
            )
        return c_obj, result
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(locate_one, lib_mod, c_obj): c_obj
            for lib_mod, c_obj in objects
        }
        
        for future in as_completed(futures):
            try:
                obj, result = future.result(timeout=_config.global_timeout)
                results[obj] = result
            except Exception as e:
                obj = futures[future]
                logger.error(f"Failed to locate {obj}: {e}")
                results[obj] = None if not return_details else {'found': False, 'error': str(e)}
    
    return results


def clear_cache() -> None:
    """
    Clear all internal caches to free memory.
    
    This function clears both the in-memory cache and the persistent
    disk cache. Useful for testing or when environment changes.
    
    Examples
    --------
    >>> # After updating libraries
    >>> clear_cache()
    >>> # New searches will re-scan
    >>> path = guess_file(np, np.dot)
    """
    # Clear memory cache
    memory_cache = get_memory_cache()
    memory_cache.clear()
    
    # Clear persistent cache
    if _config.enable_persistent_cache:
        persistent_cache = get_persistent_cache()
        persistent_cache.clear()
    
    # Reset platform detector
    _PLATFORM.reset()
    
    logger.info("All caches cleared")


def get_cache_stats() -> Dict[str, Any]:
    """
    Get statistics about the cache systems.
    
    Returns
    -------
    Dict[str, Any]
        Dictionary with cache statistics including:
            - 'memory_cache': Dict - Memory cache statistics
            - 'persistent_cache': Dict - Persistent cache statistics
    
    Examples
    --------
    >>> stats = get_cache_stats()
    >>> print(f"Memory cache hit rate: {stats['memory_cache']['hit_rate']:.1%}")
    >>> print(f"Persistent cache entries: {stats['persistent_cache']['entry_count']}")
    """
    stats = {
        'memory_cache': get_memory_cache().get_stats(),
    }
    
    if _config.enable_persistent_cache:
        stats['persistent_cache'] = get_persistent_cache().get_stats()
    
    return stats


def get_library_info(filepath: str) -> Dict[str, Any]:
    """
    Get information about a library file.
    
    This function analyzes a library file and returns metadata about it,
    including file type, size, and platform-specific details.
    
    Parameters
    ----------
    filepath : str
        Path to the library file.
    
    Returns
    -------
    Dict[str, Any]
        Dictionary with library information:
            - 'path': str - Absolute path
            - 'exists': bool - Whether file exists
            - 'size': int - File size in bytes
            - 'extension': str - File extension
            - 'platform': str - Detected platform
            - 'is_elf': bool - Whether it's an ELF file (Linux)
            - 'is_pe': bool - Whether it's a PE file (Windows)
            - 'is_macho': bool - Whether it's a Mach-O file (macOS)
    
    Examples
    --------
    >>> info = get_library_info('/usr/lib/libm.so')
    >>> print(f"Size: {info['size']} bytes")
    >>> print(f"Is ELF: {info['is_elf']}")
    """
    info = {
        'path': str(Path(filepath).resolve()),
        'exists': False,
        'size': 0,
        'extension': '',
        'platform': _PLATFORM.platform,
        'is_elf': False,
        'is_pe': False,
        'is_macho': False,
    }
    
    if not os.path.exists(filepath):
        return info
    
    path = Path(filepath)
    info['exists'] = True
    info['size'] = path.stat().st_size
    info['extension'] = path.suffix
    
    # Detect file type from magic bytes
    try:
        with open(filepath, 'rb') as f:
            magic = f.read(4)
            
            if magic[:4] == b'\x7fELF':
                info['is_elf'] = True
            elif magic[:2] == b'MZ':
                info['is_pe'] = True
            elif magic[:4] in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe'):
                info['is_macho'] = True
    except Exception:
        pass
    
    return info


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Main functions
    'guess_file',
    'guess_file_with_details',
    'guess_file_simple',
    'guess_file_fast',
    'guess_file_thorough',
    'locate_multiple',
    
    # Utility functions
    'collect_hints',
    'get_library_info',
    'clear_cache',
    'get_cache_stats',
    
    # Configuration
    'configure',
    'get_config',
    'reset_config',
    'get_score_weights',
    'set_score_weights',
    'setup_logging',
    
    # Platform
    'get_platform',
    'PlatformDetector',
    
    # Cache
    'get_memory_cache',
    'get_persistent_cache',
    
    # Strategies
    'get_strategy_manager',
    'StrategyManager',
    'SearchStrategy',
    
    # Enums
    'ScanMode',
    'ConfidenceLevel',
    'StrategyType',
    
    # Classes
    'Config',
    'ScoreWeights',
    'MatchResult',
    'PersistentCache',
    'MemoryCache',
    
    # Base classes
    'DirectModuleFileStrategy',
    'DladdrStrategy',
    'WindowsModuleHandleStrategy',
    'MemoryMapsStrategy',
    'ELFAnalysisStrategy',
    'PEAnalysisStrategy',
    'FileSystemSearchStrategy',
]
