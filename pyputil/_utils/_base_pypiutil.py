#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime, timedelta
from enum import Enum, auto

# =================================================================================
# 1. CONFIGURATION DATA CLASSES
# =================================================================================

@dataclass
class BuildConfig:
    """
    Configuration for package building operations.
    
    This data class encapsulates all settings required to build Python package
    distributions (sdist and wheel) according to PEP 517/518 standards.
    
    Attributes
    ----------
    build_type : str
        Specifies which distribution types to build.
        Valid values: 'sdist', 'wheel', 'both'
        - 'sdist': Source distribution only (.tar.gz)
        - 'wheel': Built distribution only (.whl)
        - 'both': Both sdist and wheel (default)
    
    output_dir : Optional[Path]
        Directory where built distributions will be stored.
        If None, defaults to '{package_path}/dist'
    
    no_isolation : bool
        If True, disables build isolation (build dependencies must be pre-installed).
        Useful for debugging or when build isolation causes issues.
        Default: False
    
    config_settings : Dict[str, Any]
        Additional configuration settings passed to the build backend.
        Example: {'--build-option': '--enable-optimizations'}
        Default: empty dict
    
    environment : Dict[str, str]
        Environment variables to set during build process.
        These override existing environment variables.
        Default: empty dict
    
    timeout : int
        Maximum time in seconds allowed for build operations.
        Prevents hanging builds.
        Default: 600 (10 minutes)
    
    Examples
    --------
    >>> # Basic configuration
    >>> config = BuildConfig(build_type="wheel")
    >>> 
    >>> # Advanced with custom settings
    >>> config = BuildConfig(
    ...     build_type="both",
    ...     output_dir=Path("./custom_dist"),
    ...     no_isolation=False,
    ...     config_settings={"--python-tag": "py38"},
    ...     environment={"PYTHONOPTIMIZE": "2"},
    ...     timeout=900
    ... )
    """
    
    build_type: str = "both"
    output_dir: Optional[Path] = None
    no_isolation: bool = False
    config_settings: Dict[str, Any] = field(default_factory=dict)
    environment: Dict[str, str] = field(default_factory=dict)
    timeout: int = 600


@dataclass
class UploadConfig:
    """
    Configuration for package uploading to PyPI repositories.
    
    Handles all aspects of the upload process including authentication,
    repository targeting, and file handling.
    
    Attributes
    ----------
    repository_url : str
        URL of the target PyPI repository.
        Examples:
        - PyPI: "https://upload.pypi.org/legacy/"
        - TestPyPI: "https://test.pypi.org/legacy/"
        - Private: "https://private.pypi.example.com/legacy/"
        Default: "https://upload.pypi.org/legacy/"
    
    username : Optional[str]
        Username for basic HTTP authentication.
        Not required when using API tokens.
        Default: None
    
    password : Optional[str]
        Password for basic HTTP authentication.
        WARNING: Avoid hardcoding passwords in code.
        Default: None
    
    token : Optional[str]
        PyPI API token for authentication.
        Format: "pypi-xxxxxxxxxxxxxxxxxxxx"
        This is the recommended authentication method.
        Default: None
    
    sign : bool
        If True, signs distributions with GPG before upload.
        Requires GPG to be installed and configured.
        Default: False
    
    identity : Optional[str]
        GPG key ID or email for signing.
        Required if sign is True.
        Default: None
    
    skip_existing : bool
        If True, skips uploading files that already exist on the repository.
        Useful for resuming interrupted uploads.
        Default: False
    
    comment : Optional[str]
        Optional release comment added to the upload metadata.
        Default: None
    
    config_file : Optional[Path]
        Path to .pypirc configuration file.
        Alternative to providing credentials directly.
        Default: None
    
    timeout : int
        Maximum time in seconds for upload operations.
        Default: 600 (10 minutes)
    
    Examples
    --------
    >>> # Token authentication (recommended)
    >>> config = UploadConfig(
    ...     token="pypi-xxxxxxxxxxxxxxxxxxxx",
    ...     repository_url="https://upload.pypi.org/legacy/"
    ... )
    >>> 
    >>> # Basic authentication with signing
    >>> config = UploadConfig(
    ...     username="__token__",
    ...     password="pypi-xxxxxxxxxxxx",
    ...     sign=True,
    ...     identity="your@email.com"
    ... )
    """
    
    repository_url: str = "https://upload.pypi.org/legacy/"
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    sign: bool = False
    identity: Optional[str] = None
    skip_existing: bool = False
    comment: Optional[str] = None
    config_file: Optional[Path] = None
    timeout: int = 600


@dataclass
class SecurityConfig:
    """
    Security configuration for publishing operations.
    
    This class defines security policies and validation requirements
    for package publishing, protecting against common attack vectors
    and ensuring supply chain security.
    
    Attributes
    ----------
    verify_ssl : bool
        Whether to verify SSL certificates when connecting to repositories.
        Set to False ONLY for testing with self-signed certificates.
        Default: True
    
    allowed_repositories : List[str]
        Whitelist of repository URLs that are permitted for upload.
        Empty list disables whitelisting.
        Default: ['https://upload.pypi.org/legacy/', 'https://test.pypi.org/legacy/']
    
    require_checksum : bool
        Whether to require checksum validation for all artifacts.
        Ensures file integrity throughout the pipeline.
        Default: True
    
    checksum_algorithms : List[str]
        Hash algorithms to use for checksum generation.
        Supported: 'md5', 'sha1', 'sha256', 'sha512'
        Default: ['sha256', 'sha512']
    
    max_file_size : int
        Maximum allowed size for distribution files in bytes.
        Prevents uploading overly large files.
        Default: 104857600 (100 MB)
    
    block_malicious_patterns : bool
        Whether to scan source code for malicious patterns.
        Detects eval(), exec(), subprocess calls, etc.
        Default: True
    
    require_signing : bool
        Whether to require GPG signing for distributions.
        Ensures package authenticity and integrity.
        Default: False
    
    credential_expiry_days : int
        Days after which stored credentials are considered expired.
        Enforces credential rotation.
        Default: 90
    
    enable_audit_log : bool
        Whether to enable comprehensive audit logging.
        Records all operations for compliance.
        Default: True
    
    Examples
    --------
    >>> # Strict security for production
    >>> config = SecurityConfig(
    ...     verify_ssl=True,
    ...     require_checksum=True,
    ...     block_malicious_patterns=True,
    ...     require_signing=True,
    ...     max_file_size=50 * 1024 * 1024  # 50MB limit
    ... )
    """
    
    verify_ssl: bool = True
    allowed_repositories: List[str] = field(default_factory=lambda: [
        "https://upload.pypi.org/legacy/",
        "https://test.pypi.org/legacy/"
    ])
    require_checksum: bool = True
    checksum_algorithms: List[str] = field(default_factory=lambda: ['sha256', 'sha512'])
    max_file_size: int = 100 * 1024 * 1024
    block_malicious_patterns: bool = True
    require_signing: bool = False
    credential_expiry_days: int = 90
    enable_audit_log: bool = True


@dataclass
class PerformanceConfig:
    """
    Performance optimization configuration.
    
    Controls various performance-related settings to optimize
    build times and resource utilization.
    
    Attributes
    ----------
    parallel_builds : bool
        Whether to build distributions in parallel.
        Significantly improves build times for multi-distribution builds.
        Default: True
    
    max_workers : int
        Maximum number of parallel worker threads.
        Auto-detection: min(4, CPU_count * 2)
        Default: dynamically calculated
    
    enable_caching : bool
        Whether to enable intelligent artifact caching.
        Speeds up repeated builds significantly.
        Default: True
    
    cache_ttl_seconds : int
        Time-to-live for cache entries in seconds.
        After this time, cache entries are invalidated.
        Default: 3600 (1 hour)
    
    compression_level : int
        Compression level for tar.gz archives (1-9).
        Higher = better compression but slower.
        Default: 6
    
    optimize_bytecode : bool
        Whether to optimize Python bytecode (PYTHONOPTIMIZE=2).
        Reduces .pyc file size and improves startup time.
        Default: True
    
    memory_limit_mb : int
        Memory limit for build processes in MB.
        Prevents memory exhaustion.
        Default: 2048 (2 GB)
    
    Examples
    --------
    >>> # Maximum performance for CI/CD
    >>> config = PerformanceConfig(
    ...     parallel_builds=True,
    ...     max_workers=8,
    ...     enable_caching=False,  # Fresh builds only
    ...     compression_level=3    # Faster compression
    ... )
    """
    
    parallel_builds: bool = True
    max_workers: int = None  # Will be set dynamically
    enable_caching: bool = True
    cache_ttl_seconds: int = 3600
    compression_level: int = 6
    optimize_bytecode: bool = True
    memory_limit_mb: int = 2048
    
    def __post_init__(self):
        """Set default max_workers based on CPU count if not specified."""
        if self.max_workers is None:
            cpu_count = os.cpu_count() or 1
            self.max_workers = min(4, cpu_count * 2)


@dataclass
class ComplianceConfig:
    """
    Compliance and legal validation configuration.
    
    Ensures packages meet organizational and legal requirements
    before publication.
    
    Attributes
    ----------
    check_licenses : bool
        Whether to validate licenses of dependencies.
        Scans all dependencies for license information.
        Default: True
    
    allowed_licenses : List[str]
        List of license types that are permitted.
        Package fails validation if any dependency uses other licenses.
        Default: ['MIT', 'BSD-3-Clause', 'Apache-2.0', 'LGPL-2.1+', 'GPL-3.0+']
    
    generate_sbom : bool
        Whether to generate Software Bill of Materials (SBOM).
        Creates SPDX or CycloneDX format SBOM.
        Default: False
    
    sbom_format : str
        SBOM format specification.
        Valid: 'spdx', 'cyclonedx'
        Default: 'spdx'
    
    validate_authors : bool
        Whether to validate author information.
        Ensures proper attribution and contact info.
        Default: True
    
    require_tests : bool
        Whether to require test suite execution.
        Prevents publishing untested code.
        Default: False
    
    test_coverage_threshold : float
        Minimum test coverage percentage required.
        Only applies if require_tests is True.
        Default: 80.0
    
    require_changelog : bool
        Whether to require a changelog for version updates.
        Ensures proper documentation of changes.
        Default: True
    
    Examples
    --------
    >>> # Strict compliance for regulated industry
    >>> config = ComplianceConfig(
    ...     check_licenses=True,
    ...     allowed_licenses=['MIT', 'BSD-3-Clause'],  # Only permissive
    ...     generate_sbom=True,
    ...     sbom_format='spdx',
    ...     require_tests=True,
    ...     test_coverage_threshold=95.0
    ... )
    """
    
    check_licenses: bool = True
    allowed_licenses: List[str] = field(default_factory=lambda: [
        'MIT', 'BSD-3-Clause', 'Apache-2.0', 'LGPL-2.1+', 'GPL-3.0+'
    ])
    generate_sbom: bool = False
    sbom_format: str = "spdx"
    validate_authors: bool = True
    require_tests: bool = False
    test_coverage_threshold: float = 80.0
    require_changelog: bool = True


# =================================================================================
# 2. DATA AND RESULT CLASSES
# =================================================================================

@dataclass
class BuildArtifact:
    """
    Detailed information about a built distribution artifact.
    
    Contains comprehensive metadata about a built package distribution
    file for tracking, validation, and audit purposes.
    
    Attributes
    ----------
    path : Path
        Filesystem path to the artifact file.
        Example: Path("/project/dist/mypackage-1.0.0-py3-none-any.whl")
    
    artifact_type : str
        Type of the distribution artifact.
        Valid values: 'whl', 'gz', 'zip', 'egg'
    
    size_bytes : int
        File size in bytes.
        Can be used for size validation and reporting.
    
    checksums : Dict[str, str]
        Dictionary mapping hash algorithm names to their hexadecimal checksums.
        Example: {'sha256': 'e3b0c44298fc1c149afbf4c8996fb924...'}
    
    metadata : Dict[str, Any]
        Additional artifact-specific metadata.
        May include Python version, ABI tag, platform, etc.
        Default: empty dict
    
    built_at : datetime
        Timestamp when the artifact was built.
        Default: current datetime when artifact is created
    
    Examples
    --------
    >>> # Create artifact record
    >>> artifact = BuildArtifact(
    ...     path=Path("./dist/mypackage-1.0.0.tar.gz"),
    ...     artifact_type="gz",
    ...     size_bytes=2048576,
    ...     checksums={"sha256": "abc123..."},
    ...     metadata={"python_version": ">=3.8"}
    ... )
    """
    
    path: Path
    artifact_type: str
    size_bytes: int
    checksums: Dict[str, str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    built_at: datetime = field(default_factory=datetime.now)


@dataclass
class AuditRecord:
    """
    Comprehensive audit record for compliance and debugging.
    
    Records every significant operation during the publishing process
    for audit trails, debugging, and compliance reporting.
    
    Attributes
    ----------
    timestamp : datetime
        When the operation occurred.
        Automatically set to creation time.
    
    operation : str
        Type of operation performed.
        Examples: 'init', 'build', 'upload', 'validate', 'publish'
    
    user : str
        User or system account performing the operation.
        Typically the OS username or CI/CD service name.
    
    package_name : str
        Name of the Python package being operated on.
    
    version : str
        Version string of the package.
    
    status : str
        Outcome of the operation.
        Valid values: 'started', 'success', 'failed', 'warning'
    
    details : Dict[str, Any]
        Operation-specific details and context.
        Examples: {'duration_seconds': 12.5, 'files_uploaded': 2}
    
    Examples
    --------
    >>> record = AuditRecord(
    ...     operation="upload",
    ...     user="jenkins",
    ...     package_name="mypackage",
    ...     version="1.0.0",
    ...     status="success",
    ...     details={"files": ["wheel", "sdist"], "repository": "pypi"}
    ... )
    """
    
    timestamp: datetime = field(default_factory=datetime.now)
    operation: str = ""
    user: str = ""
    package_name: str = ""
    version: str = ""
    status: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishResult:
    """
    Result object containing complete publishing operation outcome.
    
    Encapsulates all information about a publish operation including
    success status, artifacts, metrics, and any errors or warnings.
    
    Attributes
    ----------
    success : bool
        Whether the overall publish operation succeeded.
        True only if all steps completed without critical errors.
    
    package_name : str
        Name of the published package.
        Extracted from package metadata.
    
    version : str
        Version of the published package.
        Must follow PEP 440 versioning scheme.
    
    built_files : List[Path]
        List of paths to all built distribution files.
        May be empty if build was skipped.
        Default: empty list
    
    upload_url : str
        URL of the repository where package was uploaded.
        Example: "https://pypi.org/project/mypackage/"
        Default: empty string
    
    duration : timedelta
        Total time taken for the entire publish operation.
        Measured from start to completion/failure.
    
    errors : List[str]
        List of error messages if operation failed.
        Empty list on successful operations.
        Default: empty list
    
    warnings : List[str]
        List of warning messages generated during operation.
        Warnings don't fail the operation but indicate issues.
        Default: empty list
    
    artifacts_metadata : List[Dict[str, Any]]
        Detailed metadata for each built artifact.
        Includes checksums, sizes, and other attributes.
        Default: empty list
    
    Examples
    --------
    >>> # Successful result
    >>> result = PublishResult(
    ...     success=True,
    ...     package_name="mypackage",
    ...     version="1.0.0",
    ...     built_files=[Path("dist/mypackage-1.0.0-py3.whl")],
    ...     duration=timedelta(seconds=45)
    ... )
    >>> 
    >>> # Failed result with errors
    >>> result = PublishResult(
    ...     success=False,
    ...     package_name="unknown",
    ...     version="unknown",
    ...     errors=["Authentication failed", "Invalid token"],
    ...     duration=timedelta(seconds=5)
    ... )
    """
    
    success: bool
    package_name: str
    version: str
    built_files: List[Path] = field(default_factory=list)
    upload_url: str = ""
    duration: timedelta = field(default_factory=timedelta)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    artifacts_metadata: List[Dict[str, Any]] = field(default_factory=list)


# =================================================================================
# 3. ENUMERATIONS
# =================================================================================

class OperationStatus(Enum):
    """
    Detailed status codes for publish operations.
    
    Provides granular status tracking throughout the publishing pipeline,
    useful for progress monitoring and debugging.
    
    Values
    ------
    PENDING : Operation has been created but not started
    VALIDATING : Performing validation checks
    BUILDING : Building distributions
    TESTING : Running test suite
    UPLOADING : Uploading to repository
    COMPLETED : Operation finished successfully
    FAILED : Operation failed with errors
    CANCELLED : Operation was cancelled by user
    ROLLING_BACK : Undoing changes after failure
    """
    
    PENDING = "pending"
    VALIDATING = "validating"
    BUILDING = "building"
    TESTING = "testing"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLING_BACK = "rolling_back"


class RepositoryType(Enum):
    """
    Predefined PyPI repository types.
    
    Provides convenient shortcuts for common PyPI repositories.
    
    Values
    ------
    PYPI : Official Python Package Index
    TESTPYPI : Test PyPI for experimentation
    CUSTOM : User-specified custom repository
    """
    
    PYPI = auto()
    TESTPYPI = auto()
    CUSTOM = auto()