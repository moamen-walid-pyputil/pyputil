#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
from pathlib import Path
import json

# ============================================================================
# Enumerations
# ============================================================================

class LogLevel(Enum):
    """
    Logging verbosity levels for controlling output detail.
    
    This enum defines four distinct verbosity levels that control how much
    information is logged during operations. Higher levels include all
    messages from lower levels.

    Attributes
    ----------
    MINIMAL : int
        Value 1 - Only critical operations and errors
    NORMAL : int
        Value 2 - Standard operations with progress indicators
    DETAILED : int
        Value 3 - Step-by-step operation details
    DEBUG : int
        Value 4 - Complete debugging information

    Examples
    --------
    Set logger to minimal output:
    >>> logger = InstallationLogger(log_level=LogLevel.MINIMAL)
    
    Set logger to debug output for troubleshooting:
    >>> logger = InstallationLogger(log_level=LogLevel.DEBUG)
    
    Compare log levels:
    >>> LogLevel.DEBUG > LogLevel.NORMAL
    True
    
    Check if level meets threshold:
    >>> current_level = LogLevel.NORMAL
    >>> is_detailed = current_level.value >= LogLevel.DETAILED.value
    """
    MINIMAL = 1
    NORMAL = 2
    DETAILED = 3
    DEBUG = 4
    
    def __ge__(self, other: 'LogLevel') -> bool:
        """
        Enable greater-than-or-equal comparison for LogLevel instances.
        
        Parameters
        ----------
        other : LogLevel
            Another LogLevel instance to compare against
            
        Returns
        -------
        bool
            True if this level's value is >= other's value
            
        Examples
        --------
        >>> LogLevel.DETAILED >= LogLevel.NORMAL
        True
        >>> LogLevel.MINIMAL >= LogLevel.DEBUG
        False
        """
        if not isinstance(other, LogLevel):
            return NotImplemented
        return self.value >= other.value
    
    def __gt__(self, other: 'LogLevel') -> bool:
        """
        Enable greater-than comparison for LogLevel instances.
        
        Parameters
        ----------
        other : LogLevel
            Another LogLevel instance to compare against
            
        Returns
        -------
        bool
            True if this level's value is > other's value
            
        Examples
        --------
        >>> LogLevel.DEBUG > LogLevel.NORMAL
        True
        >>> LogLevel.MINIMAL > LogLevel.DETAILED
        False
        """
        if not isinstance(other, LogLevel):
            return NotImplemented
        return self.value > other.value
    
    def __le__(self, other: 'LogLevel') -> bool:
        """
        Enable less-than-or-equal comparison for LogLevel instances.
        
        Parameters
        ----------
        other : LogLevel
            Another LogLevel instance to compare against
            
        Returns
        -------
        bool
            True if this level's value is <= other's value
            
        Examples
        --------
        >>> LogLevel.NORMAL <= LogLevel.DETAILED
        True
        >>> LogLevel.DEBUG <= LogLevel.MINIMAL
        False
        """
        if not isinstance(other, LogLevel):
            return NotImplemented
        return self.value <= other.value
    
    def __lt__(self, other: 'LogLevel') -> bool:
        """
        Enable less-than comparison for LogLevel instances.
        
        Parameters
        ----------
        other : LogLevel
            Another LogLevel instance to compare against
            
        Returns
        -------
        bool
            True if this level's value is < other's value
            
        Examples
        --------
        >>> LogLevel.NORMAL < LogLevel.DEBUG
        True
        >>> LogLevel.DETAILED < LogLevel.MINIMAL
        False
        """
        if not isinstance(other, LogLevel):
            return NotImplemented
        return self.value < other.value
    
    @classmethod
    def from_string(cls, name: str) -> 'LogLevel':
        """
        Create LogLevel from string name (case-insensitive).
        
        Parameters
        ----------
        name : str
            Level name: 'minimal', 'normal', 'detailed', or 'debug'
            
        Returns
        -------
        LogLevel
            Corresponding LogLevel enum member
            
        Raises
        ------
        ValueError
            If name doesn't match any valid level
            
        Examples
        --------
        >>> LogLevel.from_string("debug")
        <LogLevel.DEBUG: 4>
        >>> LogLevel.from_string("NORMAL")
        <LogLevel.NORMAL: 2>
        """
        name_lower = name.lower()
        mapping = {
            "minimal": cls.MINIMAL,
            "normal": cls.NORMAL,
            "detailed": cls.DETAILED,
            "debug": cls.DEBUG
        }
        if name_lower not in mapping:
            raise ValueError(f"Invalid log level: {name}. Valid: {list(mapping.keys())}")
        return mapping[name_lower]


class InstallMethod(Enum):
    """
    Installation methods supported by the pip manager.
    
    This enum defines the different methods available for installing pip.
    Currently only BOOTSTRAP is fully implemented, with WHEEL and SOURCE
    reserved for future expansion.

    Attributes
    ----------
    BOOTSTRAP : auto
        Install using get-pip.py bootstrap script (recommended)
    WHEEL : auto
        Install from wheel distribution (future support)
    SOURCE : auto
        Install from source distribution (future support)

    Examples
    --------
    >>> method = InstallMethod.BOOTSTRAP
    >>> if method == InstallMethod.BOOTSTRAP:
    ...     print("Using bootstrap method")
    Using bootstrap method
    """
    BOOTSTRAP = auto()
    WHEEL = auto()
    SOURCE = auto()


# ============================================================================
# Data Classes for Results and Reports
# ============================================================================

@dataclass
class InstallationResult:
    """
    Comprehensive result container for installation operations.
    
    This dataclass provides complete feedback about installation operations
    including success status, performance metrics, warnings, and detailed logs.

    Parameters
    ----------
    success : bool
        Whether the operation completed successfully
    message : str
        Human-readable status message describing the outcome
    pip_version : str, optional
        Version of pip that was installed (if successful)
    pip_path : Path, optional
        Filesystem path to the installed pip executable
    installation_time : float, optional
        Time taken for the operation in seconds
    warnings : list, optional
        Warning messages generated during installation
    logs : list, optional
        Detailed log entries from the operation

    Attributes
    ----------
    success : bool
        Operation success status
    message : str
        Status message
    pip_version : str or None
        Installed pip version
    pip_path : Path or None
        Path to installed pip
    installation_time : float
        Duration of installation
    warnings : List[str]
        List of warning messages
    logs : List[str]
        List of log entries

    Examples
    --------
    Create a successful result:
    >>> result = InstallationResult(
    ...     success=True,
    ...     message="Installed pip 24.0 successfully",
    ...     pip_version="24.0",
    ...     pip_path=Path("/usr/bin/pip"),
    ...     installation_time=5.2
    ... )
    
    Create a failed result:
    >>> result = InstallationResult(
    ...     success=False,
    ...     message="Download failed: connection timeout",
    ...     warnings=["SSL certificate verification skipped"]
    ... )
    
    Check result and display information:
    >>> if result.success:
    ...     print(f"Success! Version: {result.pip_version}")
    ... else:
    ...     print(f"Failed: {result.message}")
    
    Access result properties:
    >>> result.installation_time
    5.2
    >>> len(result.warnings)
    1
    """
    success: bool
    message: str
    pip_version: Optional[str] = None
    pip_path: Optional[Path] = None
    installation_time: float = 0.0
    warnings: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the result to a dictionary for serialization.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation with all fields converted to JSON-serializable types
            
        Examples
        --------
        >>> result = InstallationResult(success=True, message="OK")
        >>> result.to_dict()
        {'success': True, 'message': 'OK', 'pip_version': None, ...}
        """
        data = asdict(self)
        if self.pip_path:
            data['pip_path'] = str(self.pip_path)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InstallationResult':
        """
        Create an InstallationResult from a dictionary.
        
        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary containing result data
            
        Returns
        -------
        InstallationResult
            Reconstructed InstallationResult object
            
        Examples
        --------
        >>> data = {'success': True, 'message': 'OK', 'pip_version': '24.0'}
        >>> result = InstallationResult.from_dict(data)
        """
        if 'pip_path' in data and data['pip_path']:
            data['pip_path'] = Path(data['pip_path'])
        return cls(**data)


@dataclass
class VerificationResult:
    """
    Results from comprehensive pip installation verification.
    
    This dataclass contains all verification check results and any identified
    issues, providing a complete picture of installation health.

    Parameters
    ----------
    valid : bool
        Overall validity status of the installation
    issues : List[str]
        List of identified problems or warnings
    checks : Dict[str, Any]
        Individual check results with check names as keys

    Attributes
    ----------
    valid : bool
        Whether the installation passed all checks
    issues : List[str]
        List of issues found during verification
    checks : Dict[str, Any]
        Detailed results of each verification check

    Examples
    --------
    Create a valid verification result:
    >>> result = VerificationResult(
    ...     valid=True,
    ...     issues=[],
    ...     checks={"installed": True, "version": "24.0", "functional": True}
    ... )
    
    Create a result with issues:
    >>> result = VerificationResult(
    ...     valid=False,
    ...     issues=["pip not found in PATH", "version mismatch"],
    ...     checks={"installed": False, "importable": False}
    ... )
    
    Check verification status:
    >>> if result.valid:
    ...     print("Installation is healthy")
    ... else:
    ...     print(f"Found {len(result.issues)} issue(s)")
    ...     for issue in result.issues:
    ...         print(f"  - {issue}")
    
    Access specific check results:
    >>> result.checks.get("functional", False)
    True
    """
    valid: bool
    issues: List[str]
    checks: Dict[str, Any]
    
    def summary(self) -> str:
        """
        Generate a human-readable summary of verification results.
        
        Returns
        -------
        str
            Formatted summary string
            
        Examples
        --------
        >>> result = VerificationResult(valid=True, issues=[], checks={})
        >>> print(result.summary())
        ✓ Installation is VALID
        """
        if self.valid:
            return "✓ Installation is VALID"
        else:
            return f"✗ Installation is INVALID ({len(self.issues)} issues)"
    
    def has_check(self, check_name: str) -> bool:
        """
        Check if a specific verification check was performed.
        
        Parameters
        ----------
        check_name : str
            Name of the check to look for
            
        Returns
        -------
        bool
            True if the check exists in results
            
        Examples
        --------
        >>> result.checks = {"installed": True, "version": "24.0"}
        >>> result.has_check("version")
        True
        >>> result.has_check("path")
        False
        """
        return check_name in self.checks
    
    def get_check_result(self, check_name: str, default: Any = None) -> Any:
        """
        Get the result of a specific verification check.
        
        Parameters
        ----------
        check_name : str
            Name of the check to retrieve
        default : Any, optional
            Default value if check not found
            
        Returns
        -------
        Any
            Check result value or default
            
        Examples
        --------
        >>> result.checks = {"installed": True}
        >>> result.get_check_result("installed")
        True
        >>> result.get_check_result("missing", "unknown")
        'unknown'
        """
        return self.checks.get(check_name, default)


@dataclass
class CacheInfo:
    """
    Comprehensive information about the download cache.
    
    This dataclass provides detailed statistics and metadata about the
    download cache directory, including file count, total size, and
    individual file information.

    Parameters
    ----------
    directory : str
        Cache directory path as string
    exists : bool
        Whether the cache directory exists on disk
    size_bytes : int, optional
        Total size in bytes (default: 0)
    size_mb : float, optional
        Total size in megabytes (default: 0.0)
    file_count : int, optional
        Number of cached files (default: 0)
    files : List[Dict[str, Any]], optional
        List of cached file details (default: empty list)
    error : str, optional
        Error message if cache inspection failed (default: None)

    Attributes
    ----------
    directory : str
        Cache directory path
    exists : bool
        Cache existence flag
    size_bytes : int
        Total cache size in bytes
    size_mb : float
        Total cache size in megabytes
    file_count : int
        Number of cached files
    files : List[Dict[str, Any]]
        List of file information dictionaries
    error : Optional[str]
        Error message if any

    Examples
    --------
    Create cache info for analysis:
    >>> info = CacheInfo(
    ...     directory="/home/user/.cache/pip-manager",
    ...     exists=True,
    ...     size_bytes=1048576,
    ...     size_mb=1.0,
    ...     file_count=3,
    ...     files=[{"name": "get-pip-24.0.py", "size_bytes": 204800}]
    ... )
    
    Check cache status:
    >>> if not info.exists:
    ...     print("Cache directory not found")
    ... elif info.file_count == 0:
    ...     print("Cache is empty")
    ... else:
    ...     print(f"Cache size: {info.size_mb:.2f} MB")
    
    Display cache content:
    >>> for file_info in info.files:
    ...     print(f"  - {file_info['name']}: {file_info['size_bytes']} bytes")
    """
    directory: str
    exists: bool
    size_bytes: int = 0
    size_mb: float = 0.0
    file_count: int = 0
    files: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    
    def is_empty(self) -> bool:
        """
        Check if the cache is empty or non-existent.
        
        Returns
        -------
        bool
            True if cache doesn't exist or has no files
            
        Examples
        --------
        >>> info.file_count = 0
        >>> info.is_empty()
        True
        """
        return not self.exists or self.file_count == 0
    
    def format_size(self) -> str:
        """
        Format cache size in human-readable format.
        
        Returns
        -------
        str
            Human-readable size string (e.g., "1.23 MB")
            
        Examples
        --------
        >>> info = CacheInfo(size_bytes=1048576, size_mb=1.0)
        >>> info.format_size()
        '1.00 MB'
        """
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.2f} KB"
        else:
            return f"{self.size_mb:.2f} MB"


@dataclass
class SystemInfo:
    """
    Comprehensive system and platform information.
    
    This dataclass contains detailed information about the operating system,
    hardware architecture, and Python environment configuration.

    Parameters
    ----------
    platform : str
        Operating system name (e.g., 'Linux', 'Windows', 'Darwin')
    platform_details : str
        Detailed platform information from platform.platform()
    architecture : str
        Machine architecture (e.g., 'x86_64', 'arm64')
    processor : str
        Processor type/name
    python_version : str
        Complete Python version string (e.g., '3.11.5')
    python_implementation : str
        Python implementation (e.g., 'CPython', 'PyPy')
    python_compiler : str
        Compiler used to build Python
    python_executable : str
        Path to Python executable
    python_path : str
        System Python path (sys.executable)

    Attributes
    ----------
    platform : str
        Operating system name
    platform_details : str
        Detailed platform information
    architecture : str
        Machine architecture
    processor : str
        Processor information
    python_version : str
        Python version string
    python_implementation : str
        Python implementation name
    python_compiler : str
        Compiler information
    python_executable : str
        Python executable path
    python_path : str
        Python installation path

    Examples
    --------
    Create system info object:
    >>> info = SystemInfo(
    ...     platform="Linux",
    ...     platform_details="Linux-5.15.0-x86_64",
    ...     architecture="x86_64",
    ...     processor="x86_64",
    ...     python_version="3.11.5",
    ...     python_implementation="CPython",
    ...     python_compiler="GCC 11.2.0",
    ...     python_executable="/usr/bin/python3",
    ...     python_path="/usr/bin/python3"
    ... )
    
    Display system information:
    >>> print(f"OS: {info.platform} ({info.architecture})")
    >>> print(f"Python: {info.python_version} ({info.python_implementation})")
    """
    platform: str
    platform_details: str
    architecture: str
    processor: str
    python_version: str
    python_implementation: str
    python_compiler: str
    python_executable: str
    python_path: str
    
    @property
    def python_major_minor(self) -> Tuple[int, int]:
        """
        Extract major and minor Python version as tuple.
        
        Returns
        -------
        Tuple[int, int]
            (major, minor) version tuple
            
        Examples
        --------
        >>> info.python_version = "3.11.5"
        >>> info.python_major_minor
        (3, 11)
        """
        parts = self.python_version.split('.')
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


@dataclass
class PipStatus:
    """
    Current pip installation status information.
    
    This dataclass provides information about whether pip is installed
    and details about the existing installation.

    Parameters
    ----------
    installed : bool
        Whether pip is installed in the current environment
    version : str, optional
        Installed pip version (e.g., '24.0')
    path : str, optional
        Filesystem path to the pip installation

    Attributes
    ----------
    installed : bool
        Installation status flag
    version : Optional[str]
        Version string if installed
    path : Optional[str]
        Path string if installed

    Examples
    --------
    Create status for installed pip:
    >>> status = PipStatus(
    ...     installed=True,
    ...     version="24.0",
    ...     path="/usr/local/lib/python3.11/site-packages/pip"
    ... )
    
    Create status for missing pip:
    >>> status = PipStatus(installed=False)
    
    Check and display status:
    >>> if status.installed:
    ...     print(f"pip {status.version} installed at {status.path}")
    ... else:
    ...     print("pip is not installed")
    """
    installed: bool
    version: Optional[str] = None
    path: Optional[str] = None


@dataclass
class EnvironmentInfo:
    """
    Python environment configuration details.
    
    This dataclass provides comprehensive information about the Python
    environment, including virtual environment detection and system paths.

    Parameters
    ----------
    virtual_env : bool
        Whether running in a virtual environment
    venv_path : str, optional
        Path to virtual environment if active
    user_site : str, optional
        User site-packages directory path
    system_paths : List[str], optional
        Python path entries (sys.path)
    environment_variables : Dict[str, str], optional
        Relevant environment variables (PYTHON*, PIP*, VIRTUAL*)

    Attributes
    ----------
    virtual_env : bool
        Virtual environment flag
    venv_path : Optional[str]
        Virtual environment path
    user_site : Optional[str]
        User site-packages path
    system_paths : List[str]
        System Python path list
    environment_variables : Dict[str, str]
        Environment variables dictionary

    Examples
    --------
    Create environment info for virtual environment:
    >>> info = EnvironmentInfo(
    ...     virtual_env=True,
    ...     venv_path="/home/user/project/venv",
    ...     user_site="/home/user/.local/lib/python3.11/site-packages",
    ...     system_paths=["/home/user/project/venv/lib/python3.11/site-packages"],
    ...     environment_variables={"VIRTUAL_ENV": "/home/user/project/venv"}
    ... )
    
    Check environment type:
    >>> if info.virtual_env:
    ...     print(f"Running in virtual environment: {info.venv_path}")
    ... else:
    ...     print("Running in system Python")
    """
    virtual_env: bool
    venv_path: Optional[str] = None
    user_site: Optional[str] = None
    system_paths: List[str] = field(default_factory=list)
    environment_variables: Dict[str, str] = field(default_factory=dict)


@dataclass
class ConfigurationInfo:
    """
    Current PipManager configuration settings.
    
    This dataclass captures the current configuration state of the
    PipManager instance for reporting and debugging purposes.

    Parameters
    ----------
    timeout : int
        Operation timeout in seconds
    max_retries : int
        Maximum number of retry attempts
    verify_ssl : bool
        Whether SSL verification is enabled
    log_level : str
        Current log level name (e.g., 'NORMAL', 'DEBUG')
    cache_dir : str, optional
        Cache directory path (default: None)
    platform : str, optional
        Operating system platform (default: None)

    Attributes
    ----------
    timeout : int
        Timeout setting
    max_retries : int
        Retry count setting
    verify_ssl : bool
        SSL verification flag
    log_level : str
        Log level name
    cache_dir : Optional[str]
        Cache directory path
    platform : Optional[str]
        Platform name

    Examples
    --------
    Create configuration info:
    >>> config = ConfigurationInfo(
    ...     timeout=60,
    ...     max_retries=5,
    ...     verify_ssl=True,
    ...     log_level="DETAILED",
    ...     cache_dir="/home/user/.cache/pip-manager",
    ...     platform="Linux"
    ... )
    
    Display configuration:
    >>> print(f"Timeout: {config.timeout}s, Retries: {config.max_retries}")
    >>> print(f"SSL Verification: {'Enabled' if config.verify_ssl else 'Disabled'}")
    """
    timeout: int
    max_retries: int
    verify_ssl: bool
    log_level: str
    cache_dir: Optional[str] = None
    platform: Optional[str] = None


@dataclass
class InstallationReport:
    """
    Complete installation and system diagnostic report.
    
    This dataclass provides a comprehensive snapshot of the system,
    environment, pip status, cache, and configuration for debugging
    and auditing purposes.

    Parameters
    ----------
    timestamp : str
        ISO format timestamp of report generation
    system : SystemInfo
        System and platform information
    pip_status : PipStatus
        Current pip installation status
    environment : EnvironmentInfo
        Python environment details
    cache_info : CacheInfo
        Download cache information
    configuration : ConfigurationInfo
        Manager configuration
    logs : List[Dict[str, Any]], optional
        Recent log entries (default: empty list)

    Attributes
    ----------
    timestamp : str
        Report generation timestamp
    system : SystemInfo
        System information
    pip_status : PipStatus
        Pip status information
    environment : EnvironmentInfo
        Environment information
    cache_info : CacheInfo
        Cache information
    configuration : ConfigurationInfo
        Configuration information
    logs : List[Dict[str, Any]]
        Recent log entries

    Examples
    --------
    Generate and use a report:
    >>> report = manager.get_installation_report()
    >>> print(f"Generated: {report.timestamp}")
    >>> print(f"Platform: {report.system.platform}")
    >>> print(f"Pip installed: {report.pip_status.installed}")
    >>> if report.pip_status.installed:
    ...     print(f"Pip version: {report.pip_status.version}")
    
    Export report to JSON:
    >>> import json
    >>> from dataclasses import asdict
    >>> with open("report.json", "w") as f:
    ...     json.dump(asdict(report), f, indent=2, default=str)
    
    Check environment details:
    >>> if report.environment.virtual_env:
    ...     print(f"VirtualEnv: {report.environment.venv_path}")
    """
    timestamp: str
    system: SystemInfo
    pip_status: PipStatus
    environment: EnvironmentInfo
    cache_info: CacheInfo
    configuration: ConfigurationInfo
    logs: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_json(self, indent: int = 2) -> str:
        """
        Convert report to JSON string for serialization.
        
        Parameters
        ----------
        indent : int, optional
            JSON indentation level (default: 2)
            
        Returns
        -------
        str
            JSON string representation of the report
            
        Examples
        --------
        >>> json_str = report.to_json(indent=4)
        >>> print(json_str)
        """
        def serialize(obj):
            if hasattr(obj, '__dataclass_fields__'):
                return {k: serialize(v) for k, v in asdict(obj).items()}
            elif isinstance(obj, (list, tuple)):
                return [serialize(item) for item in obj]
            elif isinstance(obj, dict):
                return {k: serialize(v) for k, v in obj.items()}
            elif isinstance(obj, Path):
                return str(obj)
            elif isinstance(obj, datetime):
                return obj.isoformat()
            return obj
        
        return json.dumps(serialize(self), indent=indent, default=str)


@dataclass
class HashInfo:
    """
    Cryptographic hash information for file verification.
    
    This dataclass stores multiple cryptographic hash values for
    comprehensive file integrity checking. SHA-256 is recommended as
    the primary hash due to its collision resistance.

    Parameters
    ----------
    sha256 : str
        SHA-256 hash value (hexadecimal, recommended)
    md5 : str, optional
        MD5 hash value (weaker, for legacy systems)
    blake2b : str, optional
        BLAKE2b hash value (fast, modern alternative)
    sha3_256 : str, optional
        SHA3-256 hash value (latest standard)

    Attributes
    ----------
    sha256 : str
        SHA-256 hash
    md5 : Optional[str]
        MD5 hash
    blake2b : Optional[str]
        BLAKE2b hash
    sha3_256 : Optional[str]
        SHA3-256 hash

    Examples
    --------
    Create hash info for file verification:
    >>> hash_info = HashInfo(
    ...     sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    ...     md5="d41d8cd98f00b204e9800998ecf8427e",
    ...     blake2b="786a02f742015903c6c6fd852552d272912f4740e15847618a86e217f71f5419"
    ... )
    
    Verify file using SHA-256:
    >>> if SecurityVerifier.verify_file_integrity(file_path, hash_info.sha256):
    ...     print("File integrity verified")
    
    Check if hash is available:
    >>> if hash_info.sha3_256:
    ...     print("SHA3-256 available for verification")
    """
    sha256: str
    md5: Optional[str] = None
    blake2b: Optional[str] = None
    sha3_256: Optional[str] = None
    
    def has_hash(self, algorithm: str) -> bool:
        """
        Check if a specific hash algorithm is available.
        
        Parameters
        ----------
        algorithm : str
            Hash algorithm name ('sha256', 'md5', 'blake2b', 'sha3_256')
            
        Returns
        -------
        bool
            True if hash value exists for the specified algorithm
            
        Examples
        --------
        >>> hash_info.has_hash('sha256')
        True
        >>> hash_info.has_hash('sha1')
        False
        """
        return getattr(self, algorithm, None) is not None
    
    def get_best_available(self) -> Tuple[str, str]:
        """
        Get the best available hash algorithm and its value.
        
        Returns available hashes in order of preference:
        SHA3-256 (most secure) > SHA-256 > BLAKE2b > MD5
        
        Returns
        -------
        Tuple[str, str]
            (algorithm_name, hash_value) tuple
            
        Examples
        --------
        >>> algorithm, hash_value = hash_info.get_best_available()
        >>> print(f"Using {algorithm}: {hash_value[:16]}...")
        """
        preference = ['sha3_256', 'sha256', 'blake2b', 'md5']
        for algo in preference:
            value = getattr(self, algo, None)
            if value:
                return (algo, value)
        raise ValueError("No hash values available")


@dataclass
class VersionListResult:
    """
    Result containing available pip versions from PyPI.
    
    This dataclass encapsulates the result of querying PyPI for available
    pip versions, including the source of the information and any errors.

    Parameters
    ----------
    versions : List[str]
        List of version strings (e.g., ['24.0', '23.3', '23.2.1'])
    source : str
        Source of version information ('pypi_api' or 'cached')
    error : str, optional
        Error message if version retrieval failed (default: None)

    Attributes
    ----------
    versions : List[str]
        Available version list
    source : str
        Information source
    error : Optional[str]
        Error message if any

    Examples
    --------
    Successful retrieval:
    >>> result = VersionListResult(
    ...     versions=['24.0', '23.3', '23.2.1'],
    ...     source='pypi_api'
    ... )
    
    Cached fallback:
    >>> result = VersionListResult(
    ...     versions=['24.0', '23.3'],
    ...     source='cached',
    ...     error="API connection failed, using cache"
    ... )
    
    Display versions:
    >>> if result.error:
    ...     print(f"Warning: {result.error}")
    >>> for version in result.versions[:5]:
    ...     print(f"  - {version}")
    """
    versions: List[str]
    source: str
    error: Optional[str] = None
    
    def is_success(self) -> bool:
        """
        Check if version retrieval was successful.
        
        Returns
        -------
        bool
            True if versions list is non-empty
            
        Examples
        --------
        >>> result.versions = ['24.0', '23.3']
        >>> result.is_success()
        True
        """
        return len(self.versions) > 0
    
    def get_latest(self) -> Optional[str]:
        """
        Get the latest version from the list.
        
        Assumes versions are sorted with newest first.
        
        Returns
        -------
        Optional[str]
            Latest version string if available, None otherwise
            
        Examples
        --------
        >>> result.versions = ['24.0', '23.3', '23.2.1']
        >>> result.get_latest()
        '24.0'
        """
        return self.versions[0] if self.versions else None


@dataclass
class PackageListResult:
    """
    Result containing installed packages information from pip list.
    
    This dataclass encapsulates the result of listing installed Python
    packages using pip, mapping package names to their versions.

    Parameters
    ----------
    packages : Dict[str, str]
        Dictionary mapping package names to version strings
    count : int
        Number of installed packages
    error : str, optional
        Error message if listing failed (default: None)

    Attributes
    ----------
    packages : Dict[str, str]
        Package name to version mapping
    count : int
        Package count
    error : Optional[str]
        Error message if any

    Examples
    --------
    Create result with packages:
    >>> result = PackageListResult(
    ...     packages={"pip": "24.0", "setuptools": "68.2.2", "wheel": "0.41.2"},
    ...     count=3
    ... )
    
    Search for a specific package:
    >>> if "pip" in result.packages:
    ...     print(f"pip version: {result.packages['pip']}")
    
    List all packages:
    >>> for name, version in sorted(result.packages.items()):
    ...     print(f"{name}=={version}")
    """
    packages: Dict[str, str]
    count: int
    error: Optional[str] = None
    
    def has_package(self, package_name: str) -> bool:
        """
        Check if a specific package is installed.
        
        Parameters
        ----------
        package_name : str
            Name of the package to check
            
        Returns
        -------
        bool
            True if package exists in the list
            
        Examples
        --------
        >>> result.has_package("pip")
        True
        >>> result.has_package("nonexistent")
        False
        """
        return package_name in self.packages
    
    def get_version(self, package_name: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get the version of a specific installed package.
        
        Parameters
        ----------
        package_name : str
            Name of the package
        default : str, optional
            Default value if package not found
            
        Returns
        -------
        Optional[str]
            Package version string or default value
            
        Examples
        --------
        >>> result.get_version("pip")
        '24.0'
        >>> result.get_version("unknown", "not installed")
        'not installed'
        """
        return self.packages.get(package_name, default)
