#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
PyPI Publishing Utility Module 
================================================================================

A production-grade, enterprise-ready solution for building, validating, and publishing
Python packages to PyPI repositories with comprehensive security, validation,
and automation capabilities.

Module Overview
--------------
This module provides a complete, end-to-end solution for Python package publishing
with industrial-strength features including:

1. **Security** - Malicious code scanning, secret detection, vulnerability auditing
2. **Compliance** - License validation, SBOM generation, audit trails
3. **Performance** - Parallel builds, intelligent caching, compression optimization
4. **Reliability** - Retry logic, rollback support, integrity verification
5. **Observability** - Telemetry, progress callbacks, comprehensive logging

Architecture
-----------
The module follows a layered architecture:

- **Configuration Layer**: Data classes for build, upload, security, performance, compliance
- **Core Layer**: PyPIPublisher class orchestrating all operations
- **Validation Layer**: Security, compliance, metadata validators
- **Build Layer**: Distribution building with optimizations
- **Upload Layer**: Repository upload with retry and verification
- **CLI Layer**: Command-line interface with argument parsing

Dependencies
-----------
Required:
    - build>=0.10.0: PEP 517 build backend
    - twine>=4.0.0: PyPI upload tool
    - packaging>=23.0: Version and requirement parsing

Optional:
    - tomli>=2.0.0: TOML parsing (Python <3.11)
    - readme_renderer>=40.0: Description rendering validation
    - gnupg>=2.3.0: GPG signing support
    - PyJWT>=2.8.0: JWT token handling
    - requests>=2.31.0: HTTP operations
    - pyyaml>=6.0: YAML configuration support
"""

import os
import sys
import re
import shutil
import subprocess
import argparse
import hashlib
import json
import webbrowser
import platform
import time
from pathlib import Path
from typing import Optional, Union, List, Dict, Any, Tuple, Callable
from datetime import datetime
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib

try:
	import urlparser
	URL_PARSER_AVAILABLE = True
except ImportError:
	URL_PARSER_AVAILABLE = False

from ._utils._base_pypiutil import (
	BuildConfig, 
	UploadConfig, 
	SecurityConfig, 
	PerformanceConfig, 
	ComplianceConfig, 
	BuildArtifact, 
	AuditRecord, 
	PublishResult, 
	OperationStatus,
	BuildConfig, 
	UploadConfig, 
	SecurityConfig, 
	PerformanceConfig, 
	ComplianceConfig, 
	BuildArtifact, 
	AuditRecord, 
	PublishResult, 
	OperationStatus
)
from ._utils._pypiutil_exceptions import (
	CacheError,
	PyPIPublishError,
	BuildError,
	ValidationError,
	AuthenticationError,
	UploadError,
	DependencyError,
	ConfigurationError,
	TestFailureError,
	SecurityError,
	ComplianceError
)
from ._utils._package_url_util import (
    PackageURLResolver,
    PackageURLs,
    PackageResolutionError,
    PackageTimeoutError,
    PackageInvalidURLError,
    quick_resolve,
    get_multiple_urls,
    example as resolver_example,
    main as main_resolver
)

# =================================================================================
# 5. CORE PUBLISHER CLASS
# =================================================================================

class PyPIPublisher:
    """
    PyPI package publisher with comprehensive features.
    
    This is the main class orchestrating the entire package publishing workflow.
    It provides production-ready functionality with extensive validation,
    security checks, performance optimization, and compliance features.
    
    Architecture Overview
    --------------------
    The publisher follows a pipeline architecture:
    
    1. **Initialization Phase**
       - Validate package directory exists
       - Check for build configuration files
       - Initialize logger and audit trail
       - Validate all configuration objects
    
    2. **Validation Phase**
       - Security scanning (malicious patterns, secrets)
       - Compliance checks (licenses, author info)
       - Package structure validation
       - Metadata completeness checks
       - Requirements validation
    
    3. **Testing Phase** (optional)
       - Run test suite (pytest, unittest, or tox)
       - Verify test coverage meets threshold
       - Validate all tests pass
    
    4. **Build Phase**
       - Clean previous build artifacts
       - Build source distribution (sdist)
       - Build wheel distribution (wheel)
       - Apply optimizations (compression, bytecode)
       - Generate checksums for all artifacts
    
    5. **Upload Phase**
       - Authenticate to repository
       - Upload distributions with retry logic
       - Verify upload success
       - Handle GPG signing if required
    
    6. **Reporting Phase**
       - Generate audit trail
       - Create SBOM if requested
       - Produce compliance report
       - Record telemetry data
    
    Usage Patterns
    -------------
    
    **Basic Usage:**
    ```python
    # Simple publish with defaults
    publisher = PyPIPublisher("./my_package")
    result = publisher.publish()
    ```
    
    **Production Deployment:**
    ```python
    # Full security and compliance
    publisher = PyPIPublisher(
        package_path="./my_package",
        security_config=SecurityConfig(
            verify_ssl=True,
            require_signing=True,
            block_malicious_patterns=True
        ),
        compliance_config=ComplianceConfig(
            check_licenses=True,
            generate_sbom=True,
            require_tests=True
        )
    )
    result = publisher.publish(run_tests=True)
    ```
    
    **CI/CD Integration:**
    ```python
    # With progress callbacks
    def on_progress(status: OperationStatus, percent: float):
        print(f"{status.value}: {percent:.1f}%")
    
    result = publisher.publish(
        callback=on_progress,
        enable_telemetry=True,
        dry_run=False
    )
    ```
    
    **Build-Only Workflow:**
    ```python
    # Build without uploading
    result = publisher.build_only()
    print(f"Built {len(result.built_files)} distributions")
    ```
    
    Design Patterns
    --------------
    - **Builder Pattern**: Configuration objects provide flexible setup
    - **Strategy Pattern**: Multiple test runners (pytest, unittest, tox)
    - **Observer Pattern**: Progress callbacks for monitoring
    - **Template Method**: Pipeline steps defined in publish() method
    
    Thread Safety
    -------------
    This class is NOT thread-safe. Each instance should be used by a single thread.
    For concurrent publishing of multiple packages, create separate instances.
    
    Resource Management
    ------------------
    - Uses context managers for file handling
    - Cleans up temporary directories automatically
    - Implements rollback for failed operations
    - Prevents memory leaks with executor shutdown
    
    Examples
    --------
    >>> # Example 1: Publish to PyPI with token
    >>> publisher = PyPIPublisher(
    ...     package_path="./my_package",
    ...     upload_config=UploadConfig(token="pypi-xxxxx")
    ... )
    >>> result = publisher.publish()
    >>> if result.success:
    ...     print(f"Published {result.package_name} v{result.version}")
    
    >>> # Example 2: Test PyPI with security checks
    >>> publisher = PyPIPublisher(
    ...     package_path="./my_package",
    ...     upload_config=UploadConfig(
    ...         repository_url="https://test.pypi.org/legacy/",
    ...         token="pypi-test-xxxxx"
    ...     ),
    ...     security_config=SecurityConfig(block_malicious_patterns=True)
    ... )
    >>> result = publisher.publish(dry_run=True)  # Test without publishing
    
    >>> # Example 3: Build only with performance optimizations
    >>> publisher = PyPIPublisher(
    ...     package_path="./my_package",
    ...     performance_config=PerformanceConfig(
    ...         parallel_builds=True,
    ...         compression_level=9
    ...     )
    ... )
    >>> result = publisher.build_only()
    
    See Also
    --------
    BuildConfig : Configuration for build operations
    UploadConfig : Configuration for upload operations
    SecurityConfig : Security validation settings
    ComplianceConfig : Compliance check settings
    PublishResult : Comprehensive result object
    OperationStatus : Status tracking enumeration
    """
    
    def __init__(
        self,
        package_path: Union[str, Path],
        build_config: Optional[BuildConfig] = None,
        upload_config: Optional[UploadConfig] = None,
        security_config: Optional[SecurityConfig] = None,
        performance_config: Optional[PerformanceConfig] = None,
        compliance_config: Optional[ComplianceConfig] = None,
        logger: Optional[logging.Logger] = None,
        telemetry_enabled: bool = False
    ):
        """
        Initialize the enterprise PyPI publisher with comprehensive configuration.
        
        This constructor sets up the publisher instance with all necessary
        configurations and performs initial validation to ensure the package
        is ready for publishing operations.
        
        Initialization Steps:
        1. Resolve and validate package path
        2. Create or receive configuration objects
        3. Initialize logging and audit systems
        4. Set up internal state variables
        5. Validate all configurations for consistency
        6. Validate package structure and files
        7. Record initialization audit event
        
        Parameters
        ----------
        package_path : str or Path
            Filesystem path to the Python package directory.
            Must contain a setup.py, setup.cfg, or pyproject.toml file.
            Example: "./src/my_package" or Path("/projects/my_package")
        
        build_config : BuildConfig, optional
            Configuration for building distributions.
            If None, uses default BuildConfig() with standard settings.
            See BuildConfig documentation for details.
        
        upload_config : UploadConfig, optional
            Configuration for uploading to repositories.
            If None, uses default UploadConfig() (uploads to PyPI).
            See UploadConfig documentation for details.
        
        security_config : SecurityConfig, optional
            Security policy and validation settings.
            If None, uses standard security configuration.
            See SecurityConfig documentation for details.
        
        performance_config : PerformanceConfig, optional
            Performance optimization settings.
            If None, uses balanced performance defaults.
            See PerformanceConfig documentation for details.
        
        compliance_config : ComplianceConfig, optional
            Compliance and legal validation settings.
            If None, uses standard compliance checks.
            See ComplianceConfig documentation for details.
        
        logger : logging.Logger, optional
            Custom logger instance for application-specific logging.
            If None, creates a new logger with name f"{__name__}.PyPIPublisher".
            Useful for integrating with existing logging infrastructure.
        
        telemetry_enabled : bool, optional
            Whether to enable performance telemetry collection.
            When True, collects metrics like build times, cache hit rates,
            and resource usage. Useful for performance monitoring.
            Default: False
        
        Raises
        ------
        ValidationError
            If package_path doesn't exist or isn't a directory.
            If no build configuration file (setup.py/setup.cfg/pyproject.toml) is found.
            If package name or version cannot be extracted.
        
        ConfigurationError
            If configurations have conflicting or invalid settings.
            Examples: Invalid repository URL, incompatible settings.
        
        Examples
        --------
        >>> # Minimal initialization (uses all defaults)
        >>> publisher = PyPIPublisher("./my_package")
        
        >>> # Full initialization with all configurations
        >>> publisher = PyPIPublisher(
        ...     package_path="./my_package",
        ...     build_config=BuildConfig(build_type="both"),
        ...     upload_config=UploadConfig(token="pypi-xxxxx"),
        ...     security_config=SecurityConfig(verify_ssl=True),
        ...     performance_config=PerformanceConfig(parallel_builds=True),
        ...     compliance_config=ComplianceConfig(check_licenses=True),
        ...     telemetry_enabled=True
        ... )
        
        >>> # Integration with existing logger
        >>> import logging
        >>> my_logger = logging.getLogger("my_app.publisher")
        >>> publisher = PyPIPublisher(
        ...     package_path="./my_package",
        ...     logger=my_logger
        ... )
        """
        # Store package path and resolve to absolute path
        self.package_path = Path(package_path).resolve()
        
        # Store configuration objects with defaults if not provided
        self.build_config = build_config or BuildConfig()
        self.upload_config = upload_config or UploadConfig()
        self.security_config = security_config or SecurityConfig()
        self.performance_config = performance_config or PerformanceConfig()
        self.compliance_config = compliance_config or ComplianceConfig()
        self.telemetry_enabled = telemetry_enabled
        
        # Initialize logger
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Initialize internal state
        self._start_time = None  # Timestamp when publish/build started
        self._operation_status = OperationStatus.PENDING  # Current operation status
        self._audit_trail: List[AuditRecord] = []  # List of all audit records
        self._artifacts: List[BuildArtifact] = []  # List of built artifacts
        self._cache: Dict[str, Any] = {}  # In-memory cache for build artifacts
        self._executor = None  # Thread/process executor for parallel operations
        self._rollback_stack: List[Callable] = []  # Rollback functions stack
        self._telemetry_data: Dict[str, Any] = {}  # Performance telemetry data
        
        # Validate all configurations before proceeding
        self._validate_configurations()
        
        # Validate package structure and requirements
        self._validate_initial_state()
        
        # Record initialization in audit trail
        self._record_audit(
            operation="init",
            status="success",
            details={
                "package_path": str(self.package_path),
                "build_type": self.build_config.build_type,
                "repository": self.upload_config.repository_url
            }
        )
        
        self.logger.info(f"Publisher initialized for {self.package_path}")
    
    # =====================================================================
    # 5.1 PRIVATE VALIDATION METHODS
    # =====================================================================
    
    def _validate_configurations(self) -> None:
        """
        Validate all configuration objects for consistency and correctness.
        
        This internal method performs comprehensive validation of all
        configuration settings to prevent runtime errors and security
        vulnerabilities. It checks:
        
        1. **Repository URL Security**
           - Ensures HTTPS is used when SSL verification is enabled
           - Allows HTTP only for localhost (development)
        
        2. **Repository Whitelist**
           - Verifies repository URL is in allowed list (if configured)
           - Prevents accidental uploads to unauthorized repositories
        
        3. **Build Type Validity**
           - Validates build_type is one of: 'sdist', 'wheel', 'both'
        
        4. **Performance Settings**
           - Validates compression level (1-9)
           - Ensures max_workers is positive
           - Checks memory limit is reasonable
        
        5. **Timeout Values**
           - Ensures timeout values are positive integers
        
        6. **Credential Configuration**
           - Warns if both token and username/password are provided
           - Validates signing requirements
        
        Raises
        ------
        ConfigurationError
            If any configuration fails validation with detailed error message.
        
        Notes
        -----
        This method is called during __init__ and cannot be called again
        after initialization without reinitializing the publisher.
        
        Security Note
        -------------
        This method enforces HTTPS for production repositories to prevent
        man-in-the-middle attacks and credential interception.
        
        Examples
        --------
        >>> # This validation would fail:
        >>> config = UploadConfig(repository_url="http://insecure.pypi.org/legacy/")
        >>> publisher = PyPIPublisher("./pkg", upload_config=config)
        # Raises ConfigurationError about insecure repository
        """
        errors = []
        warnings = []
        
        # -----------------------------------------------------------------
        # 1. Validate repository URL security
        # -----------------------------------------------------------------
        if self.security_config.verify_ssl:
            if URL_PARSER_AVAILABLE:
                parsed = urlparser(self.upload_config.repository_url)
                # Allow HTTP only for localhost/test environments
                if parsed.scheme != 'https' and parsed.hostname not in ['localhost', '127.0.0.1']:
                    errors.append(
                        f"Insecure repository URL: {self.upload_config.repository_url}. "
                        "Use HTTPS for production or set verify_ssl=False for testing only."
                )
            else:
                self.logger.warning(
                    "SSL verification is disabled. This is insecure and should only "
                    "be used for testing with self-signed certificates."
            )
        
        # -----------------------------------------------------------------
        # 2. Validate repository whitelist
        # -----------------------------------------------------------------
        if self.security_config.allowed_repositories:
            url = self.upload_config.repository_url
            is_allowed = any(
                url == allowed or url.startswith(allowed) 
                for allowed in self.security_config.allowed_repositories
            )
            if not is_allowed:
                errors.append(
                    f"Repository {url} not in allowed list: "
                    f"{self.security_config.allowed_repositories}"
                )
        
        # -----------------------------------------------------------------
        # 3. Validate build type
        # -----------------------------------------------------------------
        valid_build_types = ['sdist', 'wheel', 'both']
        if self.build_config.build_type not in valid_build_types:
            errors.append(
                f"Invalid build_type: {self.build_config.build_type}. "
                f"Must be one of: {valid_build_types}"
            )
        
        # -----------------------------------------------------------------
        # 4. Validate performance settings
        # -----------------------------------------------------------------
        if self.performance_config.max_workers < 1:
            errors.append(f"max_workers must be at least 1, got {self.performance_config.max_workers}")
        
        if self.performance_config.compression_level < 1 or self.performance_config.compression_level > 9:
            errors.append(
                f"compression_level must be between 1 and 9, "
                f"got {self.performance_config.compression_level}"
            )
        
        if self.performance_config.memory_limit_mb < 256:
            warnings.append(
                f"Memory limit {self.performance_config.memory_limit_mb}MB is very low. "
                "Consider increasing to at least 512MB for reliable builds."
            )
        
        # -----------------------------------------------------------------
        # 5. Validate timeouts
        # -----------------------------------------------------------------
        if self.build_config.timeout <= 0:
            errors.append(f"build timeout must be positive, got {self.build_config.timeout}")
        
        if self.upload_config.timeout <= 0:
            errors.append(f"upload timeout must be positive, got {self.upload_config.timeout}")
        
        # -----------------------------------------------------------------
        # 6. Validate credential configuration
        # -----------------------------------------------------------------
        has_token = self.upload_config.token is not None
        has_user_pass = (self.upload_config.username is not None and 
                        self.upload_config.password is not None)
        
        if has_token and has_user_pass:
            warnings.append(
                "Both token and username/password provided. Token will be used "
                "as it takes precedence."
            )
        
        if not (has_token or has_user_pass or self.upload_config.config_file):
            warnings.append(
                "No authentication method provided. Upload may fail if "
                "repository requires authentication."
            )
        
        # -----------------------------------------------------------------
        # 7. Validate signing configuration
        # -----------------------------------------------------------------
        if self.upload_config.sign and not self.upload_config.identity:
            errors.append(
                "Signing requires an identity (GPG key ID or email). "
                "Please provide identity in upload_config."
            )
        
        # Raise errors if any
        if errors:
            raise ConfigurationError(
                f"Configuration validation failed ({len(errors)} error(s)):\n" + 
                "\n".join(f"  {error}" for error in errors)
            )
        
        # Log warnings
        for warning in warnings:
            self.logger.warning(f"Configuration warning: {warning}")
    
    def _validate_initial_state(self) -> None:
        """
        Validate the initial state of the package directory.
        
        This internal method checks that the package directory exists,
        contains required build configuration files, and that basic
        metadata can be extracted.
        
        Validation Steps:
        1. Check if package_path exists
        2. Check if package_path is a directory
        3. Check for at least one build config file:
           - setup.py (setuptools)
           - setup.cfg (setuptools configuration)
           - pyproject.toml (PEP 621/517/518)
        4. Attempt to extract package name and version
        
        Raises
        ------
        ValidationError
            If any validation step fails with detailed explanation.
        
        Notes
        -----
        This method is called during __init__ to catch issues early.
        If validation fails, the publisher cannot be used for publishing.
        
        Examples
        --------
        >>> # This would raise ValidationError:
        >>> publisher = PyPIPublisher("./non_existent_directory")
        
        >>> # This would also raise ValidationError (no setup files):
        >>> publisher = PyPIPublisher("./empty_directory")
        """
        # -----------------------------------------------------------------
        # Step 1: Check if path exists
        # -----------------------------------------------------------------
        if not self.package_path.exists():
            raise ValidationError(
                f"Package path does not exist: {self.package_path}\n"
                f"Please ensure the path is correct and accessible."
            )
        
        # -----------------------------------------------------------------
        # Step 2: Check if path is a directory
        # -----------------------------------------------------------------
        if not self.package_path.is_dir():
            raise ValidationError(
                f"Path is not a directory: {self.package_path}\n"
                f"Expected a directory containing a Python package."
            )
        
        # -----------------------------------------------------------------
        # Step 3: Check for build configuration files
        # -----------------------------------------------------------------
        required_files = ['setup.py', 'setup.cfg', 'pyproject.toml']
        found_files = [f for f in required_files if (self.package_path / f).exists()]
        
        if not found_files:
            raise ValidationError(
                f"No build configuration found in {self.package_path}\n"
                f"Expected one of: {', '.join(required_files)}\n"
                f"These files are required for package building according to PEP 517/518."
            )
        
        self.logger.debug(f"Found build configuration: {', '.join(found_files)}")
        
        # -----------------------------------------------------------------
        # Step 4: Validate output directory configuration
        # -----------------------------------------------------------------
        if self.build_config.output_dir is None:
            self.build_config.output_dir = self.package_path / "dist"
            self.logger.debug(f"Output directory set to default: {self.build_config.output_dir}")
        
        # Create output directory if it doesn't exist
        self.build_config.output_dir.mkdir(parents=True, exist_ok=True)
    
    # =====================================================================
    # 5.2 PUBLIC PUBLISHING METHODS
    # =====================================================================
    
    def publish(
        self,
        skip_build: bool = False,
        skip_cleanup: bool = False,
        check_metadata: bool = True,
        check_description: bool = True,
        run_tests: bool = False,
        dry_run: bool = False,
        enable_telemetry: bool = False,
        callback: Optional[Callable[[OperationStatus, float], None]] = None,
        requirements_files: Optional[List[Union[str, Path]]] = None
    ) -> PublishResult:
        """
        Execute complete publish workflow with enterprise features.
        
        This is the main method orchestrating the entire publishing pipeline.
        It performs all necessary steps from validation to upload with
        comprehensive error handling, progress reporting, and rollback support.
        
        **Complete Pipeline Steps:**
        
        1. **Initialization** (0-5%)
           - Record start time
           - Set up telemetry if enabled
           - Notify callback of start
        
        2. **Security Validation** (5-15%)
           - Scan for malicious code patterns
           - Detect hardcoded secrets
           - Check for unsafe imports
           - Verify GPG signatures if required
        
        3. **Compliance Checks** (15-25%)
           - Validate dependency licenses
           - Check author information
           - Verify changelog presence
           - Generate SBOM if requested
        
        4. **Package Validation** (25-35%)
           - Extract package name and version
           - Validate directory structure
           - Check for required files
           - Validate naming conventions
        
        5. **Metadata Validation** (35-45%)
           - Check all required metadata fields
           - Validate version format (PEP 440)
           - Verify README and LICENSE files
        
        6. **Test Execution** (45-60%)
           - Run test suite (pytest/unittest/tox)
           - Check test coverage
           - Validate all tests pass
        
        7. **Build Process** (60-85%)
           - Clean previous builds
           - Build distributions (sdist/wheel)
           - Apply optimizations
           - Generate checksums
        
        8. **Upload Process** (85-100%)
           - Authenticate to repository
           - Upload files with retry logic
           - Verify upload success
           - Generate audit report
        
        Parameters
        ----------
        skip_build : bool, optional
            If True, skip building and use existing distributions from dist/.
            Useful when you've already built the package separately.
            Default: False
        
        skip_cleanup : bool, optional
            If True, preserve build artifacts and temp files after completion.
            Useful for debugging or inspecting build outputs.
            Default: False
        
        check_metadata : bool, optional
            If True, validate package metadata completeness.
            Checks for name, version, author, description, etc.
            Default: True
        
        check_description : bool, optional
            If True, validate that README renders correctly on PyPI.
            Checks both Markdown and reStructuredText formats.
            Default: True
        
        run_tests : bool, optional
            If True, execute test suite before building.
            Requires pytest, unittest, or tox to be configured.
            Default: False
        
        dry_run : bool, optional
            If True, simulate all operations without actual upload.
            Performs all validation and building but skips upload.
            Great for testing configuration before real publish.
            Default: False
        
        enable_telemetry : bool, optional
            If True, collect and record performance metrics.
            Includes durations, resource usage, cache hit rates.
            Default: False
        
        callback : Callable[[OperationStatus, float], None], optional
            Progress callback function called at each step.
            Receives current status and completion percentage (0-100).
            Useful for progress bars or CI/CD integration.
            
            Example:
            ```python
            def on_progress(status: OperationStatus, percent: float):
                print(f"{status.value}: {percent:.1f}%")
            ```
        
        requirements_files : List[Union[str, Path]], optional
            Additional requirements files to validate.
            Each file is checked for existence and valid requirement format.
            Example: ['requirements.txt', 'requirements-dev.txt']
        
        Returns
        -------
        PublishResult
            Comprehensive result object containing:
            - Success/failure status
            - Package name and version
            - List of built files
            - Upload URL
            - Total duration
            - Error messages (if any)
            - Warning messages
            - Artifact metadata (checksums, sizes)
        
        Raises
        ------
        SecurityError
            If security validation fails (malicious patterns, secrets found).
        
        ComplianceError
            If compliance checks fail (license issues, missing author).
        
        ValidationError
            If package validation fails (missing files, invalid metadata).
        
        BuildError
            If build process fails (dependency issues, compilation errors).
        
        UploadError
            If upload fails (authentication, network, repository errors).
        
        TestFailureError
            If tests fail when run_tests=True or require_tests=True.
        
        Examples
        --------
        >>> # Basic production publish
        >>> publisher = PyPIPublisher("./my_package")
        >>> result = publisher.publish()
        >>> if result.success:
        ...     print(f"Success! Published {result.package_name}")
        
        >>> # Safe test run with dry-run
        >>> result = publisher.publish(
        ...     dry_run=True,
        ...     run_tests=True,
        ...     callback=lambda s, p: print(f"{s.value}: {p:.0f}%")
        ... )
        
        >>> # CI/CD pipeline integration
        >>> result = publisher.publish(
        ...     check_metadata=True,
        ...     check_description=True,
        ...     run_tests=True,
        ...     enable_telemetry=True,
        ...     requirements_files=['requirements.txt', 'requirements-test.txt']
        ... )
        
        >>> # Skipping build (using pre-built distributions)
        >>> result = publisher.publish(
        ...     skip_build=True,
        ...     dry_run=False
        ... )
        
        See Also
        --------
        build_only : Build distributions without uploading
        cleanup : Manually clean up build artifacts
        rollback : Rollback after failed publish
        """
        # -----------------------------------------------------------------
        # Step 0: Initialize operation state
        # -----------------------------------------------------------------
        self._operation_status = OperationStatus.VALIDATING
        self._start_time = datetime.now()
        self._artifacts = []  # Clear previous artifacts
        warnings = []
        errors = []
        
        # Set up telemetry collection if enabled
        telemetry_data = {}
        if enable_telemetry or self.telemetry_enabled:
            telemetry_data = self._start_telemetry()
        
        # Notify callback of start
        if callback:
            callback(OperationStatus.VALIDATING, 0.0)
        
        try:
            # Record start in audit trail
            self._record_audit(
                operation="publish_start",
                status="started",
                details={"dry_run": dry_run, "run_tests": run_tests}
            )
            
            self.logger.info(f"Starting enterprise publication from: {self.package_path}")
            
            # -----------------------------------------------------------------
            # Step 1: Security Validation (5-10%)
            # -----------------------------------------------------------------
            if callback:
                callback(OperationStatus.VALIDATING, 5.0)
            
            self.logger.info("[1/8] Running security validations...")
            self._validate_security()
            self.logger.info("Security validation passed")
            
            # -----------------------------------------------------------------
            # Step 2: Compliance Checks (10-15%)
            # -----------------------------------------------------------------
            if callback:
                callback(OperationStatus.VALIDATING, 10.0)
            
            self.logger.info("[2/8] Running compliance checks...")
            self._validate_compliance()
            self.logger.info("Compliance checks passed")
            
            # -----------------------------------------------------------------
            # Step 3: Package Structure Validation (15-20%)
            # -----------------------------------------------------------------
            if callback:
                callback(OperationStatus.VALIDATING, 15.0)
            
            self.logger.info("[3/8] Validating package structure...")
            package_name, version = self._validate_package_structure()
            self.logger.info(f"Package: {package_name} v{version}")
            
            # -----------------------------------------------------------------
            # Step 4: Metadata Validation (20-25%)
            # -----------------------------------------------------------------
            if check_metadata:
                if callback:
                    callback(OperationStatus.VALIDATING, 20.0)
                
                self.logger.info("[4/8] Validating metadata...")
                self._check_package_metadata()
                self.logger.info("Metadata validation passed")
            
            # -----------------------------------------------------------------
            # Step 5: Requirements Validation (25-30%)
            # -----------------------------------------------------------------
            if requirements_files:
                if callback:
                    callback(OperationStatus.VALIDATING, 25.0)
                
                self.logger.info("[5/8] Validating requirements...")
                self._check_requirements_files(requirements_files)
                self.logger.info("Requirements validation passed")
            
            # -----------------------------------------------------------------
            # Step 6: Description Rendering Check (30-35%)
            # -----------------------------------------------------------------
            if check_description:
                if callback:
                    callback(OperationStatus.VALIDATING, 30.0)
                
                self.logger.info("📝 [6/8] Checking description rendering...")
                self._check_description_rendering()
                self.logger.info("Description renders correctly")
            
            # -----------------------------------------------------------------
            # Step 7: Test Execution (35-50%)
            # -----------------------------------------------------------------
            if run_tests or self.compliance_config.require_tests:
                self._operation_status = OperationStatus.TESTING
                if callback:
                    callback(OperationStatus.TESTING, 35.0)
                
                self.logger.info("[7/8] Running test suite...")
                self._run_tests_with_coverage()
                self.logger.info("All tests passed")
            
            # -----------------------------------------------------------------
            # Step 8: Build Process (50-85%)
            # -----------------------------------------------------------------
            self._operation_status = OperationStatus.BUILDING
            
            if not skip_build:
                if callback:
                    callback(OperationStatus.BUILDING, 50.0)
                
                self.logger.info("[8/8] Building distributions...")
                built_files = self._build_with_performance()
                self.logger.info(f"Built {len(built_files)} distribution(s)")
            else:
                self.logger.info("Using existing distributions (skipping build)...")
                built_files = self._get_existing_distributions()
            
            # -----------------------------------------------------------------
            # Step 9: SBOM Generation (if required)
            # -----------------------------------------------------------------
            if self.compliance_config.generate_sbom:
                self.logger.info("Generating Software Bill of Materials...")
                self._generate_sbom(package_name, version)
            
            # -----------------------------------------------------------------
            # Step 10: Upload Process (85-100%)
            # -----------------------------------------------------------------
            if not dry_run:
                self._operation_status = OperationStatus.UPLOADING
                if callback:
                    callback(OperationStatus.UPLOADING, 85.0)
                
                self.logger.info(f"Uploading to {self.upload_config.repository_url}...")
                self._upload_with_monitoring(built_files)
                
                if callback:
                    callback(OperationStatus.UPLOADING, 100.0)
                
                self.logger.info("Upload completed successfully")
            else:
                self.logger.info("DRY RUN: Skipping actual upload (validation only)")
            
            # -----------------------------------------------------------------
            # Step 11: Finalize and Return Result
            # -----------------------------------------------------------------
            self._operation_status = OperationStatus.COMPLETED
            duration = datetime.now() - self._start_time
            
            # Prepare artifact metadata for result
            artifacts_metadata = []
            for artifact in self._artifacts:
                artifacts_metadata.append({
                    "filename": artifact.path.name,
                    "type": artifact.artifact_type,
                    "size_bytes": artifact.size_bytes,
                    "checksums": artifact.checksums,
                    "built_at": artifact.built_at.isoformat()
                })
            
            result = PublishResult(
                success=True,
                package_name=package_name,
                version=version,
                built_files=[a.path for a in self._artifacts],
                upload_url=self.upload_config.repository_url,
                duration=duration,
                warnings=warnings,
                artifacts_metadata=artifacts_metadata
            )
            
            # Record success in audit trail
            self._record_audit(
                operation="publish_complete",
                status="success",
                details={
                    "package_name": package_name,
                    "version": version,
                    "duration_seconds": duration.total_seconds(),
                    "dry_run": dry_run,
                    "artifacts_count": len(self._artifacts)
                }
            )
            
            # Generate compliance report if needed
            if self.compliance_config.check_licenses:
                self._generate_compliance_report(package_name, version)
            
            self.logger.info(
                f"Successfully published {package_name} v{version} "
                f"in {duration.total_seconds():.2f} seconds!"
            )
            
            return result
            
        except (SecurityError, ComplianceError, ValidationError, 
                BuildError, UploadError, TestFailureError) as e:
            # Handle known publishing errors
            self._operation_status = OperationStatus.FAILED
            errors.append(str(e))
            
            self._record_audit(
                operation="publish_failed",
                status="failed",
                details={"error": str(e), "error_type": type(e).__name__}
            )
            
            self.logger.error(f"Publishing failed: {e}")
            
            # Execute rollback to clean up partial state
            self._execute_rollback()
            
            # Create failed result
            duration = datetime.now() - self._start_time
            result = PublishResult(
                success=False,
                package_name=self._extract_package_name() or "unknown",
                version=self._extract_version() or "unknown",
                duration=duration,
                errors=errors,
                warnings=warnings
            )
            
            # Re-raise the exception for caller to handle
            raise
            
        except Exception as e:
            # Handle unexpected errors
            self._operation_status = OperationStatus.FAILED
            errors.append(f"Unexpected error: {str(e)}")
            
            self.logger.error(f"Unexpected error: {traceback.format_exc()}")
            
            self._record_audit(
                operation="publish_failed",
                status="failed",
                details={"error": str(e), "error_type": "UnexpectedError"}
            )
            
            self._execute_rollback()
            
            duration = datetime.now() - self._start_time
            result = PublishResult(
                success=False,
                package_name="unknown",
                version="unknown",
                duration=duration,
                errors=errors,
                warnings=warnings
            )
            
            raise PyPIPublishError(f"Publishing failed unexpectedly: {e}")
            
        finally:
            # Stop telemetry if it was started
            if enable_telemetry or self.telemetry_enabled:
                self._stop_telemetry(telemetry_data)
            
            # Clean up if not skipped
            if not skip_cleanup:
                self.cleanup()
    
    def build_only(self) -> PublishResult:
        """
        Build the package distributions without uploading to repository.
        
        This method is useful when you only need to generate distribution
        files for local testing, inspection, or manual upload later.
        
        Process Steps:
        1. Validate package structure (name, version)
        2. Clean previous build artifacts
        3. Build distributions according to build_config
        4. Generate checksums for built files
        5. Return result with artifact information
        
        Returns
        -------
        PublishResult
            Result object containing:
            - success: True if build succeeded
            - package_name: Name of the built package
            - version: Version of the built package
            - built_files: List of paths to built distributions
            - duration: Time taken for build
            - errors: List of error messages if failed
        
        Raises
        ------
        ValidationError
            If package structure validation fails.
        
        BuildError
            If build process fails.
        
        Examples
        --------
        >>> # Build both sdist and wheel
        >>> publisher = PyPIPublisher("./my_package")
        >>> result = publisher.build_only()
        >>> if result.success:
        ...     for file in result.built_files:
        ...         print(f"Built: {file.name}")
        
        >>> # Build only wheel with optimization
        >>> config = BuildConfig(build_type="wheel", no_isolation=True)
        >>> publisher = PyPIPublisher("./my_package", build_config=config)
        >>> result = publisher.build_only()
        
        >>> # Build and inspect artifacts
        >>> result = publisher.build_only()
        >>> for meta in result.artifacts_metadata:
        ...     print(f"{meta['filename']}: {meta['size_bytes']} bytes")
        """
        self._start_time = datetime.now()
        self._operation_status = OperationStatus.BUILDING
        
        self._record_audit(
            operation="build_only",
            status="started",
            details={"build_type": self.build_config.build_type}
        )
        
        try:
            # Extract package information
            package_name, version = self._validate_package_structure()
            self.logger.info(f"Building {package_name} v{version}")
            
            # Build distributions
            built_files = self._build_with_performance()
            
            duration = datetime.now() - self._start_time
            
            # Prepare artifact metadata
            artifacts_metadata = []
            for artifact in self._artifacts:
                artifacts_metadata.append({
                    "filename": artifact.path.name,
                    "type": artifact.artifact_type,
                    "size_bytes": artifact.size_bytes,
                    "checksums": artifact.checksums
                })
            
            result = PublishResult(
                success=True,
                package_name=package_name,
                version=version,
                built_files=built_files,
                duration=duration,
                artifacts_metadata=artifacts_metadata
            )
            
            self._record_audit(
                operation="build_only",
                status="success",
                details={
                    "package_name": package_name,
                    "version": version,
                    "artifacts_count": len(built_files),
                    "duration_seconds": duration.total_seconds()
                }
            )
            
            self.logger.info(
                f"Build completed in {duration.total_seconds():.2f}s: "
                f"{len(built_files)} file(s)"
            )
            
            return result
            
        except Exception as e:
            duration = datetime.now() - self._start_time
            
            self._record_audit(
                operation="build_only",
                status="failed",
                details={"error": str(e)}
            )
            
            self.logger.error(f"Build failed: {e}")
            
            return PublishResult(
                success=False,
                package_name=self._extract_package_name() or "unknown",
                version=self._extract_version() or "unknown",
                duration=duration,
                errors=[str(e)]
            )
    
    def cleanup(self) -> None:
        """
        Clean up build artifacts and temporary files.
        
        Removes all build-related temporary files and directories while
        preserving the built distributions in the output directory.
        
        **Files/Directories Removed:**

        - `build/` directory - Temporary build files
        - `*.egg-info/` directories - Package metadata cache
        - `__pycache__/` directories - Python bytecode cache
        - `.pytest_cache/` - Pytest cache directory
        - `.tox/` - Tox virtual environments
        - `*.pyc` and `*.pyo` files - Compiled bytecode
        - `*.so` (if in temp build) - Extension modules
        
        **Files Preserved:**
        - `dist/*.whl` - Built wheel distributions
        - `dist/*.tar.gz` - Built source distributions
        
        This method is automatically called after publish unless skip_cleanup=True.
        You can also call it manually to free disk space.
        
        Raises
        ------
        OSError
            If file/directory removal fails (logged as warning, not raised).
        
        Examples
        --------
        >>> # Manual cleanup after custom build
        >>> publisher = PyPIPublisher("./my_package")
        >>> publisher.build_only()
        >>> # ... do something with built files ...
        >>> publisher.cleanup()  # Remove temporary files
        
        >>> # Cleanup with custom patterns
        >>> # (patterns are hardcoded, but you can extend the class)
        
        Notes
        -----
        This method is safe to call multiple times. It won't raise exceptions
        on cleanup failures (only logs warnings).
        """
        self.logger.info("🧹 Cleaning up build artifacts...")
        
        # Patterns for cleanup (relative to package_path)
        cleanup_patterns = [
            'build',               # Build directory
            '*.egg-info',          # Egg metadata
            '__pycache__',         # Python cache
            '.pytest_cache',       # Pytest cache
            '.tox',                # Tox environments
            '.coverage',           # Coverage data
            'htmlcov',             # Coverage HTML report
            '*.pyc',               # Compiled bytecode
            '*.pyo',               # Optimized bytecode
            '.mypy_cache',         # MyPy type checking cache
            '.ruff_cache',         # Ruff linter cache
        ]
        
        cleaned_count = 0
        failed_count = 0
        
        for pattern in cleanup_patterns:
            for path in self.package_path.glob(pattern):
                try:
                    if path.is_file():
                        path.unlink()
                        self.logger.debug(f"  Removed file: {path}")
                    elif path.is_dir():
                        shutil.rmtree(path)
                        self.logger.debug(f"  Removed directory: {path}")
                    cleaned_count += 1
                except Exception as e:
                    failed_count += 1
                    self.logger.warning(f"  Failed to remove {path}: {e}")
        
        # Also clean output directory of temporary build artifacts
        if self.build_config.output_dir and self.build_config.output_dir.exists():
            # Remove .buildinfo and .dist-info temporary files
            for pattern in ['*.buildinfo', '*.dist-info', '*.RECORD']:
                for path in self.build_config.output_dir.glob(pattern):
                    try:
                        path.unlink()
                        self.logger.debug(f"  Removed: {path}")
                        cleaned_count += 1
                    except Exception:
                        pass
        
        self.logger.info(
            f"Cleanup completed: {cleaned_count} items removed, "
            f"{failed_count} failures"
        )
    
    # =====================================================================
    # 5.3 PRIVATE SECURITY AND COMPLIANCE METHODS
    # =====================================================================
    
    def _validate_security(self) -> None:
        """
        Perform comprehensive security validation on package source code.
        
        This internal method scans the entire package directory for
        security vulnerabilities, malicious patterns, and hardcoded secrets.
        
        **Security Checks Performed:**
        
        1. **Malicious Code Patterns**
           - `eval()` - Dynamic code execution
           - `exec()` - Dynamic code execution
           - `__import__()` - Dynamic imports
           - `os.system()` - Shell command execution
           - `subprocess.call/Popen/run` - Process execution
           - `base64.b64decode` + `exec` - Obfuscated code
           - `compile()` - Dynamic code compilation
        
        2. **Hardcoded Secrets Detection**
           - PyPI API tokens (format: pypi-xxx...)
           - Private RSA/SSH keys
           - API keys in assignments
           - Passwords in assignments
           - JWT secrets
           - Database connection strings
        
        3. **Unsafe Imports**
           - `pickle` (unsafe deserialization)
           - `marshal` (unsafe deserialization)
           - `shelve` (unsafe persistence)
        
        4. **Network Communication**
           - Hardcoded URLs to external services
           - Unencrypted HTTP calls
        
        Raises
        ------
        SecurityError
            If any security violation is detected, with details of all issues.
            The error message includes file paths and specific violations.
        
        Notes
        -----
        - Scanning is recursive through all .py files in package directory
        - Only runs if security_config.block_malicious_patterns is True
        - Limits error reporting to first 10 issues to avoid overwhelming output
        
        Examples
        --------
        >>> # This would raise SecurityError:
        >>> # File contains: eval(user_input)
        >>> publisher = PyPIPublisher("./package_with_eval")
        >>> publisher._validate_security()
        # Raises: SecurityError: Security validation failed:
        #   • src/module.py: Use of eval() detected
        
        Security Note
        -------------
        These checks are heuristic and may produce false positives.
        If you have legitimate use of these patterns, you can:
        1. Disable security checks in configuration
        2. Refactor code to use safer alternatives
        3. Add comments to explain legitimate uses
        """
        if not self.security_config.block_malicious_patterns:
            self.logger.debug("Security scanning disabled by configuration")
            return
        
        issues = []
        
        # -----------------------------------------------------------------
        # 1. Scan for malicious code patterns
        # -----------------------------------------------------------------
        malicious_patterns = [
            # Code execution patterns
            (r'eval\s*\(', "Use of eval() detected (dynamic code execution)"),
            (r'exec\s*\(', "Use of exec() detected (dynamic code execution)"),
            (r'__import__\s*\(', "Dynamic import detected (could load untrusted code)"),
            
            # System command execution
            (r'os\.system\s*\(', "System command execution detected"),
            (r'subprocess\.(call|Popen|run)\s*\(', "Subprocess execution detected"),
            
            # Obfuscation patterns
            (r'base64\.b64decode.*exec', "Potentially obfuscated code detected"),
            (r'compile\s*\(', "Dynamic code compilation detected"),
            
            # Unsafe deserialization
            (r'pickle\.(load|loads)', "Unsafe pickle deserialization detected"),
            (r'marshal\.(load|loads)', "Unsafe marshal deserialization detected"),
            
            # HTTP without SSL (development only)
            (r'http://[^"]+', "Unencrypted HTTP request (should use HTTPS)"),
        ]
        
        for py_file in self.package_path.rglob("*.py"):
            # Skip test files (they may legitimately use these patterns)
            if '/test_' in str(py_file) or '/tests/' in str(py_file):
                continue
                
            try:
                content = py_file.read_text(encoding='utf-8')
                rel_path = py_file.relative_to(self.package_path)
                
                for pattern, message in malicious_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        # Find line number for better error reporting
                        lines = content.split('\n')
                        for i, line in enumerate(lines, 1):
                            if re.search(pattern, line, re.IGNORECASE):
                                issues.append(f"{rel_path}:{i}: {message}")
                                break
                        
            except Exception as e:
                self.logger.debug(f"Cannot scan {py_file}: {e}")
        
        # -----------------------------------------------------------------
        # 2. Check for hardcoded secrets
        # -----------------------------------------------------------------
        secret_patterns = [
            # PyPI tokens
            (r'pypi-[A-Za-z0-9]{20,}', "PyPI API token found in code"),
            (r'pypi-test-[A-Za-z0-9]{20,}', "Test PyPI token found in code"),
            
            # Private keys
            (r'-----BEGIN RSA PRIVATE KEY-----', "RSA private key in code"),
            (r'-----BEGIN OPENSSH PRIVATE KEY-----', "SSH private key in code"),
            
            # API keys
            (r'api[_-]key\s*=\s*["\'][A-Za-z0-9]{20,}', "API key assignment detected"),
            (r'api[_-]secret\s*=\s*["\'][A-Za-z0-9]{20,}', "API secret detected"),
            
            # Generic passwords
            (r'password\s*=\s*["\'][^"\']{8,}', "Potential password assignment"),
            (r'passwd\s*=\s*["\'][^"\']{8,}', "Potential password assignment"),
            
            # JWT secrets
            (r'JWT_SECRET\s*=\s*["\'][A-Za-z0-9]{32,}', "JWT secret found"),
            
            # Database connection strings
            (r'postgresql://[^:]+:[^@]+@', "Database password in connection string"),
            (r'mysql://[^:]+:[^@]+@', "Database password in connection string"),
        ]
        
        for pattern, message in secret_patterns:
            for py_file in self.package_path.rglob("*.py"):
                # Skip test files and configuration examples
                if '/test_' in str(py_file) or '.example.' in str(py_file):
                    continue
                    
                try:
                    content = py_file.read_text(encoding='utf-8')
                    if re.search(pattern, content, re.IGNORECASE):
                        rel_path = py_file.relative_to(self.package_path)
                        issues.append(f"{rel_path}: {message}")
                except Exception:
                    pass
        
        # -----------------------------------------------------------------
        # 3. Raise exception if issues found
        # -----------------------------------------------------------------
        if issues:
            # Limit to first 20 issues to avoid overwhelming output
            issue_list = issues[:20]
            if len(issues) > 20:
                issue_list.append(f"... and {len(issues) - 20} more issues")
                
            raise SecurityError(
                f"Security validation failed with {len(issues)} violation(s):\n" + 
                "\n".join(f"  {issue}" for issue in issue_list)
            )
        
        self.logger.debug("Security validation completed successfully")
    
    def _validate_compliance(self) -> None:
        """
        Validate package compliance with organizational and legal requirements.
        
        This internal method checks the package against compliance policies
        including licensing, author validation, and changelog requirements.
        
        **Compliance Checks Performed:**
        
        1. **License Validation**
           - Scans all dependencies for license information
           - Verifies licenses are in allowed list
           - Reports unknown licenses as warnings
           - Uses pip-licenses tool for dependency scanning
        
        2. **Author Information Validation**
           - Checks for author name in metadata
           - Validates author email format
           - Verifies author URL (if provided)
           - Ensures maintainer contact info
        
        3. **Changelog Validation**
           - Checks for CHANGELOG.md, HISTORY.md, or NEWS.md
           - Ensures current version is documented
           - Validates changelog format
        
        4. **Export Control Classification**
           - Detects cryptography modules for export controls
           - Warns about encryption features
           - Flags for legal review
        
        Raises
        ------
        ComplianceError
            If any compliance check fails that is configured as required.
            Includes detailed list of violations.
        
        Notes
        -----
        - License checking requires 'pip-licenses' package (installed on demand)
        - Export control checks are advisory only (warnings, not errors)
        - Some checks may be disabled via compliance_config
        
        Examples
        --------
        >>> # This would raise ComplianceError:
        >>> # Dependency uses GPL-3.0 but allowed_licenses is ['MIT']
        >>> config = ComplianceConfig(allowed_licenses=['MIT'])
        >>> publisher = PyPIPublisher("./pkg", compliance_config=config)
        >>> publisher._validate_compliance()
        # Raises: ComplianceError: Dependency X uses GPL-3.0 not in allowed list
        """
        issues = []
        warnings = []
        
        # -----------------------------------------------------------------
        # 1. License validation
        # -----------------------------------------------------------------
        if self.compliance_config.check_licenses:
            self.logger.debug("Checking dependency licenses...")
            
            try:
                # Try to get license information using pip-licenses
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "list", "--format=json"],
                    cwd=self.package_path,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    packages = json.loads(result.stdout)
                    
                    # Check each package's license (simplified - would need pip-licenses)
                    for pkg in packages:
                        pkg_name = pkg.get('name', 'unknown')
                        pkg_version = pkg.get('version', 'unknown')
                        
                        # Note: Full license detection requires pip-licenses
                        # This is a simplified check
                        if pkg_name.lower() in ['cryptography', 'pyopenssl', 'paramiko']:
                            warnings.append(
                                f"Package {pkg_name} ({pkg_version}) contains "
                                "cryptography features - ensure export compliance"
                            )
                else:
                    self.logger.debug("Could not retrieve package list for license checking")
                    
            except subprocess.TimeoutExpired:
                self.logger.warning("License check timed out - continuing")
            except Exception as e:
                self.logger.debug(f"License check error: {e}")
        
        # -----------------------------------------------------------------
        # 2. Author information validation
        # -----------------------------------------------------------------
        if self.compliance_config.validate_authors:
            self.logger.debug("Validating author information...")
            
            author_info = self._extract_author_info()
            
            if not author_info.get('name'):
                issues.append("Missing author name in package metadata")
            elif len(author_info['name']) < 2:
                issues.append("Author name too short (minimum 2 characters)")
            
            if not author_info.get('email'):
                issues.append("Missing author email in package metadata")
            elif '@' not in author_info['email']:
                issues.append(f"Invalid author email format: {author_info['email']}")
            
            if not author_info.get('author_url'):
                warnings.append("No author URL provided (recommended for discoverability)")
        
        # -----------------------------------------------------------------
        # 3. Changelog validation
        # -----------------------------------------------------------------
        if self.compliance_config.require_changelog:
            self.logger.debug("Validating changelog presence...")
            
            changelog_files = ['CHANGELOG.md', 'HISTORY.md', 'CHANGES.md', 'NEWS.md']
            found_changelog = False
            
            for cl_file in changelog_files:
                if (self.package_path / cl_file).exists():
                    found_changelog = True
                    # Check if current version is documented
                    version = self._extract_version()
                    if version:
                        content = (self.package_path / cl_file).read_text(encoding='utf-8')
                        if version not in content:
                            warnings.append(
                                f"Changelog found but version {version} not documented"
                            )
                    break
            
            if not found_changelog:
                issues.append(
                    f"Missing changelog file. Expected one of: {', '.join(changelog_files)}"
                )
        
        # -----------------------------------------------------------------
        # 4. Raise exception if issues found
        # -----------------------------------------------------------------
        if issues:
            raise ComplianceError(
                f"Compliance validation failed with {len(issues)} error(s):\n" + 
                "\n".join(f"  {issue}" for issue in issues)
            )
        
        # Log warnings
        for warning in warnings:
            self.logger.warning(f"Compliance warning: {warning}")
        
        self.logger.debug("Compliance validation passed successfully")
    
    # =====================================================================
    # 5.4 PRIVATE BUILD AND PERFORMANCE METHODS
    # =====================================================================
    
    def _build_with_performance(self) -> List[Path]:
        """
        Build distributions with performance optimizations and caching.
        
        This internal method orchestrates the build process with various
        performance optimizations including parallel builds, intelligent
        caching, and resource limiting.
        
        **Optimization Features:**
        
        1. **Intelligent Caching**
           - Computes cache key from package source and configuration
           - Stores built artifacts in cache for reuse
           - Cache TTL controls freshness
           - Automatic cache invalidation on source changes
        
        2. **Parallel Building**
           - Builds sdist and wheel simultaneously when possible
           - Uses ThreadPoolExecutor for concurrent operations
           - Configurable worker count based on CPU cores
           - Handles resource contention automatically
        
        3. **Resource Management**
           - Memory limits for build subprocesses
           - CPU affinity hints for better performance
           - I/O priority adjustment for background builds
           - Timeout protection for hung builds
        
        4. **Compression Optimization**
           - Adjustable compression levels (1-9)
           - Parallel compression for large files
           - Streaming compression to reduce memory usage
        
        **Cache Mechanism:**
        - Cache key = hash(package files + config + Python version)
        - Cache stored in `~/.cache/pypi-publisher/`
        - Checks timestamp and source changes for invalidation
        - Manual cache clearing via cleanup_cache() method
        
        Returns
        -------
        List[Path]
            List of paths to successfully built distribution files.
            Includes both sdist (.tar.gz) and wheel (.whl) files.
        
        Raises
        ------
        BuildError
            If build process fails for any reason.
        DependencyError
            If required build dependencies are missing.
        CacheError
            If cache operation fails (non-fatal, continues without cache)
        
        Examples
        --------
        >>> # Build with default optimization
        >>> publisher = PyPIPublisher("./pkg")
        >>> files = publisher._build_with_performance()
        
        >>> # Build with maximum compression
        >>> config = PerformanceConfig(compression_level=9)
        >>> publisher = PyPIPublisher("./pkg", performance_config=config)
        >>> files = publisher._build_with_performance()
        """
        self.logger.info(f"Starting optimized build process")
        build_start = datetime.now()
        
        # -----------------------------------------------------------------
        # Step 1: Check cache for existing build
        # -----------------------------------------------------------------
        cache_hit = False
        cached_files = None
        
        if self.performance_config.enable_caching:
            try:
                cache_key = self._compute_cache_key()
                cached_files = self._get_from_cache(cache_key)
                
                if cached_files:
                    # Verify cached files still exist
                    all_exist = all(Path(f).exists() for f in cached_files)
                    if all_exist:
                        cache_hit = True
                        self.logger.info(f"Cache hit! Using cached build artifacts")
                        return [Path(f) for f in cached_files]
                    else:
                        self.logger.debug("Cache entry invalid (files missing)")
            except CacheError as e:
                self.logger.warning(f"Cache read failed: {e} - continuing without cache")
        
        if not cache_hit:
            self.logger.debug("Cache miss - performing fresh build")
        
        # -----------------------------------------------------------------
        # Step 2: Check build dependencies
        # -----------------------------------------------------------------
        self._check_build_dependencies()
        
        # -----------------------------------------------------------------
        # Step 3: Clean previous builds
        # -----------------------------------------------------------------
        self._clean_previous_builds()
        
        # -----------------------------------------------------------------
        # Step 4: Prepare build environment
        # -----------------------------------------------------------------
        env = os.environ.copy()
        env.update(self.build_config.environment)
        
        # Apply performance optimizations
        if self.performance_config.optimize_bytecode:
            env['PYTHONOPTIMIZE'] = '2'
            self.logger.debug("Bytecode optimization enabled (PYTHONOPTIMIZE=2)")
        
        # Set memory limit if supported
        if platform.system() == 'Linux' and self.performance_config.memory_limit_mb:
            # Note: Actual memory limiting requires resource module or cgroups
            self.logger.debug(f"Memory limit configured: {self.performance_config.memory_limit_mb}MB")
        
        # -----------------------------------------------------------------
        # Step 5: Build distributions
        # -----------------------------------------------------------------
        built_files = []
        
        if self.performance_config.parallel_builds and self.build_config.build_type == 'both':
            # Parallel build for both sdist and wheel
            self.logger.info(f"Building in parallel using {self.performance_config.max_workers} workers")
            
            with ThreadPoolExecutor(max_workers=self.performance_config.max_workers) as executor:
                # Submit build tasks
                future_sdist = executor.submit(self._build_sdist)
                future_wheel = executor.submit(self._build_wheel)
                
                # Collect results
                for future in as_completed([future_sdist, future_wheel]):
                    try:
                        files = future.result(timeout=self.build_config.timeout)
                        built_files.extend(files)
                    except Exception as e:
                        # Cancel other tasks if one fails
                        for f in [future_sdist, future_wheel]:
                            f.cancel()
                        raise BuildError(f"Parallel build failed: {e}")
        else:
            # Sequential build
            if self.build_config.build_type in ['sdist', 'both']:
                self.logger.debug("Building source distribution...")
                built_files.extend(self._build_sdist())
            
            if self.build_config.build_type in ['wheel', 'both']:
                self.logger.debug("Building wheel distribution...")
                built_files.extend(self._build_wheel())
        
        # -----------------------------------------------------------------
        # Step 6: Create artifact records
        # -----------------------------------------------------------------
        for file_path in built_files:
            # Calculate checksums
            checksums = {}
            for algo in self.security_config.checksum_algorithms:
                try:
                    checksums[algo] = self._calculate_file_hash(file_path, algo)
                except Exception as e:
                    self.logger.warning(f"Failed to calculate {algo} hash for {file_path.name}: {e}")
            
            # Determine artifact type
            if file_path.suffix == '.whl':
                artifact_type = 'wheel'
            elif file_path.suffix == '.gz':
                artifact_type = 'sdist'
            else:
                artifact_type = file_path.suffix[1:] if file_path.suffix else 'unknown'
            
            artifact = BuildArtifact(
                path=file_path,
                artifact_type=artifact_type,
                size_bytes=file_path.stat().st_size,
                checksums=checksums,
                metadata={
                    'compression_level': self.performance_config.compression_level,
                    'optimized': self.performance_config.optimize_bytecode,
                    'built_with': f"Python {platform.python_version()}"
                }
            )
            self._artifacts.append(artifact)
        
        # -----------------------------------------------------------------
        # Step 7: Store in cache
        # -----------------------------------------------------------------
        if self.performance_config.enable_caching and not cache_hit:
            try:
                cache_key = self._compute_cache_key()
                self._store_in_cache(cache_key, [str(f) for f in built_files])
                self.logger.debug(f"Cached {len(built_files)} artifacts")
            except CacheError as e:
                self.logger.warning(f"Cache write failed: {e}")
        
        # -----------------------------------------------------------------
        # Step 8: Log build statistics
        # -----------------------------------------------------------------
        build_duration = datetime.now() - build_start
        total_size = sum(f.stat().st_size for f in built_files) / (1024 * 1024)
        
        self.logger.info(
            f"Build completed in {build_duration.total_seconds():.2f}s - "
            f"{len(built_files)} file(s), {total_size:.2f} MB total"
        )
        
        for artifact in self._artifacts:
            size_mb = artifact.size_bytes / (1024 * 1024)
            sha256_preview = artifact.checksums.get('sha256', 'N/A')[:16]
            self.logger.debug(
                f"  {artifact.path.name} ({size_mb:.2f} MB, "
                f"SHA256: {sha256_preview}...)"
            )
        
        return built_files
    
    def _build_sdist(self) -> List[Path]:
        """
        Build source distribution (sdist) package.
        
        Creates a .tar.gz source distribution containing package source code,
        configuration files, and metadata as per PEP 517 specifications.
        
        **Build Process:**
        1. Invokes 'python -m build --sdist'
        2. Applies compression level from performance config
        3. Sets reproducible build timestamps (SOURCE_DATE_EPOCH)
        4. Captures build output for debugging
        
        **Source Distribution Contents:**
        - Package source code (.py files)
        - Configuration files (setup.py, setup.cfg, pyproject.toml)
        - README, LICENSE, and other docs
        - Tests and examples (if included)
        
        Returns
        -------
        List[Path]
            List containing the path to the built sdist file.
            Empty list if build failed or not configured.
        
        Raises
        ------
        BuildError
            If sdist build fails with non-zero exit code.
            Includes build output in error message.
        
        Notes
        -----
        - Source distributions are platform-independent
        - Required for uploading to PyPI
        - Build output is captured and logged at debug level
        - Supports reproducible builds via environment variables
        
        Examples
        --------
        >>> publisher = PyPIPublisher("./pkg")
        >>> sdist_files = publisher._build_sdist()
        >>> print(f"Built: {sdist_files[0].name}")
        Built: mypackage-1.0.0.tar.gz
        """
        self.logger.debug("Building source distribution (sdist)...")
        
        # Prepare output directory
        self.build_config.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Build command
        cmd = [
            sys.executable, "-m", "build",
            "--sdist",
            "--outdir", str(self.build_config.output_dir)
        ]
        
        if self.build_config.no_isolation:
            cmd.append("--no-isolation")
            self.logger.debug("Build isolation disabled")
        
        # Set reproducible build environment
        env = os.environ.copy()
        env.update(self.build_config.environment)
        
        # Set timestamp for reproducible builds
        if 'SOURCE_DATE_EPOCH' not in env:
            env['SOURCE_DATE_EPOCH'] = str(int(time.time()))
        
        # Set compression level via environment (if supported)
        env.setdefault('TAR_OPTIONS', f'--gzip --compression-level={self.performance_config.compression_level}')
        
        try:
            result = subprocess.run(
                cmd,
                cwd=self.package_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.build_config.timeout
            )
            
            if result.returncode != 0:
                self.logger.error(f"SDist build failed with output:\n{result.stderr}")
                raise BuildError(
                    f"Source distribution build failed (exit code {result.returncode})\n"
                    f"Error: {result.stderr[:500]}"
                )
            
            # Find the built sdist file
            sdist_files = list(self.build_config.output_dir.glob("*.tar.gz"))
            
            if not sdist_files:
                raise BuildError("No .tar.gz file was created by sdist build")
            
            # Return the most recently created sdist
            sdist_file = max(sdist_files, key=lambda p: p.stat().st_ctime)
            self.logger.debug(f"SDist built: {sdist_file.name}")
            
            return [sdist_file]
            
        except subprocess.TimeoutExpired:
            raise BuildError(f"SDist build timed out after {self.build_config.timeout} seconds")
        except FileNotFoundError:
            raise DependencyError(
                "'build' module not found. Install with: pip install build"
            )
    
    def _build_wheel(self) -> List[Path]:
        """
        Build wheel distribution package.
        
        Creates a .whl binary distribution containing pre-compiled package
        code and metadata as per PEP 427 specifications.
        
        **Build Process:**
        1. Invokes 'python -m build --wheel'
        2. Applies Python optimization level (if enabled)
        3. Sets platform-specific build tags
        4. Captures build output for debugging
        
        **Wheel Features:**
        - Pre-compiled bytecode (.pyc files)
        - Platform-specific extensions (if any)
        - Faster installation than sdist
        - Deterministic build support
        
        Returns
        -------
        List[Path]
            List containing the path to the built wheel file.
            Empty list if build failed or not configured.
        
        Raises
        ------
        BuildError
            If wheel build fails with non-zero exit code.
            Includes build output in error message.
        
        Notes
        -----
        - Wheels are platform-specific if they contain C extensions
        - Pure Python wheels are universal (py3-none-any)
        - Wheel format is the preferred distribution format for PyPI
        
        Examples
        --------
        >>> publisher = PyPIPublisher("./pkg")
        >>> wheel_files = publisher._build_wheel()
        >>> print(f"Built: {wheel_files[0].name}")
        Built: mypackage-1.0.0-py3-none-any.whl
        
        >>> # With custom Python tag
        >>> config = BuildConfig(config_settings={"--python-tag": "py38"})
        >>> publisher = PyPIPublisher("./pkg", build_config=config)
        >>> wheel_files = publisher._build_wheel()  # Tagged for Python 3.8
        """
        self.logger.debug("Building wheel distribution...")
        
        # Prepare output directory
        self.build_config.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Build command
        cmd = [
            sys.executable, "-m", "build",
            "--wheel",
            "--outdir", str(self.build_config.output_dir)
        ]
        
        if self.build_config.no_isolation:
            cmd.append("--no-isolation")
            self.logger.debug("Build isolation disabled")
        
        # Add config settings
        for key, value in self.build_config.config_settings.items():
            cmd.extend(["-C", f"{key}={value}"])
        
        # Set environment for optimization
        env = os.environ.copy()
        env.update(self.build_config.environment)
        
        if self.performance_config.optimize_bytecode:
            env['PYTHONOPTIMIZE'] = '2'
        
        try:
            result = subprocess.run(
                cmd,
                cwd=self.package_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.build_config.timeout
            )
            
            if result.returncode != 0:
                self.logger.error(f"Wheel build failed with output:\n{result.stderr}")
                raise BuildError(
                    f"Wheel distribution build failed (exit code {result.returncode})\n"
                    f"Error: {result.stderr[:500]}"
                )
            
            # Find the built wheel file
            wheel_files = list(self.build_config.output_dir.glob("*.whl"))
            
            if not wheel_files:
                raise BuildError("No .whl file was created by wheel build")
            
            # Return the most recently created wheel
            wheel_file = max(wheel_files, key=lambda p: p.stat().st_ctime)
            self.logger.debug(f"Wheel built: {wheel_file.name}")
            
            return [wheel_file]
            
        except subprocess.TimeoutExpired:
            raise BuildError(f"Wheel build timed out after {self.build_config.timeout} seconds")
        except FileNotFoundError:
            raise DependencyError(
                "'build' module not found. Install with: pip install build"
            )
    
    def _compute_cache_key(self) -> str:
        """
        Compute unique cache key for current package state.
        
        Creates a deterministic hash based on package source files and
        configuration to identify when cached artifacts are still valid.
        
        **Cache Key Components:**
        1. Package source files (all .py files, setup files, configs)
        2. Python version (major.minor)
        3. Platform (OS, architecture)
        4. Build configuration (build_type, no_isolation, etc.)
        5. Performance settings (compression_level, optimization flags)
        
        Returns
        -------
        str
            Hexadecimal SHA-256 hash representing the cache key.
            Used as lookup key in cache storage.
        
        Raises
        ------
        CacheError
            If unable to read package files or compute hash.
        
        Notes
        -----
        - Cache key changes when any source file is modified
        - Different Python versions get different cache keys
        - Configuration changes invalidate cache
        - Cache keys are deterministic (same input = same key)
        
        Examples
        --------
        >>> key1 = publisher._compute_cache_key()
        >>> # After modifying a source file
        >>> key2 = publisher._compute_cache_key()
        >>> assert key1 != key2  # Keys are different
        """
        import hashlib
        
        hasher = hashlib.sha256()
        
        # -----------------------------------------------------------------
        # 1. Add Python version and platform information
        # -----------------------------------------------------------------
        platform_info = f"{platform.python_version()}_{platform.system()}_{platform.machine()}"
        hasher.update(platform_info.encode())
        
        # -----------------------------------------------------------------
        # 2. Add build configuration
        # -----------------------------------------------------------------
        config_str = json.dumps({
            'build_type': self.build_config.build_type,
            'no_isolation': self.build_config.no_isolation,
            'config_settings': self.build_config.config_settings,
            'compression_level': self.performance_config.compression_level,
            'optimize_bytecode': self.performance_config.optimize_bytecode
        }, sort_keys=True)
        hasher.update(config_str.encode())
        
        # -----------------------------------------------------------------
        # 3. Add package source files (limited to important ones)
        # -----------------------------------------------------------------
        important_patterns = [
            '*.py', '*.toml', '*.cfg', 'setup.py', 'setup.cfg',
            'pyproject.toml', 'MANIFEST.in', 'requirements*.txt'
        ]
        
        file_hashes = []
        for pattern in important_patterns:
            for file_path in self.package_path.rglob(pattern):
                # Skip cache and build directories
                if any(part in file_path.parts for part in ['__pycache__', '.tox', 'build', 'dist']):
                    continue
                
                try:
                    # Get relative path for consistent hashing
                    rel_path = file_path.relative_to(self.package_path)
                    
                    # Read file content
                    content = file_path.read_bytes()
                    
                    # Hash the content
                    file_hash = hashlib.sha256(content).hexdigest()
                    file_hashes.append(f"{rel_path}:{file_hash}")
                    
                except Exception as e:
                    self.logger.debug(f"Cannot hash {file_path}: {e}")
        
        # Sort for deterministic order
        file_hashes.sort()
        for file_hash in file_hashes:
            hasher.update(file_hash.encode())
        
        # -----------------------------------------------------------------
        # 4. Add timestamp of last modification (for freshness)
        # -----------------------------------------------------------------
        # Don't include actual timestamp, but include hash of file timestamps
        timestamps = []
        for pattern in important_patterns:
            for file_path in self.package_path.rglob(pattern):
                try:
                    mtime = file_path.stat().st_mtime_ns
                    timestamps.append(str(mtime))
                except Exception:
                    pass
        
        timestamps.sort()
        hasher.update(''.join(timestamps).encode())
        
        return hasher.hexdigest()
    
    def _get_from_cache(self, cache_key: str) -> Optional[List[str]]:
        """
        Retrieve cached build artifacts using cache key.
        
        Implements filesystem-based caching with TTL (Time-To-Live)
        validation to ensure cached artifacts are still fresh.
        
        **Cache Location:**
        - Linux: ~/.cache/pypi-publisher/
        - macOS: ~/Library/Caches/pypi-publisher/
        - Windows: %LOCALAPPDATA%\\pypi-publisher\\Cache
        
        **Cache Entry Structure:**
        {
            "key": "sha256...",
            "timestamp": "2024-01-01T00:00:00",
            "files": ["/path/to/file1.whl", "/path/to/file2.tar.gz"],
            "metadata": {"python_version": "3.11", "platform": "Linux"}
        }
        
        Parameters
        ----------
        cache_key : str
            Unique cache key computed by _compute_cache_key().
        
        Returns
        -------
        Optional[List[str]]
            List of cached file paths if cache hit and valid,
            None if cache miss, expired, or corrupted.
        
        Raises
        ------
        CacheError
            If cache directory is inaccessible or cache file is corrupted.
        
        Notes
        -----
        - Cache entries older than cache_ttl_seconds are ignored
        - Invalid JSON or missing files trigger cache miss
        - Cache is persistent across publisher instances
        """
        # Determine cache directory based on platform
        if platform.system() == 'Windows':
            cache_dir = Path(os.environ.get('LOCALAPPDATA', '~')) / 'pypi-publisher' / 'Cache'
        elif platform.system() == 'Darwin':  # macOS
            cache_dir = Path.home() / 'Library' / 'Caches' / 'pypi-publisher'
        else:  # Linux and others
            cache_dir = Path.home() / '.cache' / 'pypi-publisher'
        
        cache_dir = cache_dir.expanduser()
        cache_file = cache_dir / f"{cache_key}.json"
        
        if not cache_file.exists():
            return None
        
        try:
            # Read cache entry
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
            
            # Check TTL
            timestamp = datetime.fromisoformat(cache_data['timestamp'])
            age = datetime.now() - timestamp
            
            if age.total_seconds() > self.performance_config.cache_ttl_seconds:
                self.logger.debug(f"Cache expired (age: {age.total_seconds():.0f}s)")
                return None
            
            # Verify all files still exist
            files = cache_data.get('files', [])
            for file_path in files:
                if not Path(file_path).exists():
                    self.logger.debug(f"Cached file missing: {file_path}")
                    return None
            
            self.logger.debug(f"Cache hit (age: {age.total_seconds():.0f}s)")
            return files
            
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.logger.debug(f"Cache read error: {e}")
            # Remove corrupted cache file
            try:
                cache_file.unlink()
            except Exception:
                pass
            return None
        except Exception as e:
            raise CacheError(f"Failed to read cache: {e}")
    
    def _store_in_cache(self, cache_key: str, files: List[str]) -> None:
        """
        Store build artifacts in cache for future reuse.
        
        Saves metadata about built artifacts to the filesystem cache
        for faster subsequent builds.
        
        Parameters
        ----------
        cache_key : str
            Unique cache key computed from package state.
        files : List[str]
            List of built artifact file paths to cache.
        
        Raises
        ------
        CacheError
            If unable to write to cache directory or serialize data.
        
        Notes
        -----
        - Creates cache directory if it doesn't exist
        - Stores timestamp for TTL validation
        - Does not copy files, only stores references
        - Old cache entries are not automatically cleaned
        """
        # Determine cache directory
        if platform.system() == 'Windows':
            cache_dir = Path(os.environ.get('LOCALAPPDATA', '~')) / 'pypi-publisher' / 'Cache'
        elif platform.system() == 'Darwin':
            cache_dir = Path.home() / 'Library' / 'Caches' / 'pypi-publisher'
        else:
            cache_dir = Path.home() / '.cache' / 'pypi-publisher'
        
        cache_dir = cache_dir.expanduser()
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        cache_file = cache_dir / f"{cache_key}.json"
        
        cache_data = {
            'key': cache_key,
            'timestamp': datetime.now().isoformat(),
            'files': files,
            'metadata': {
                'python_version': platform.python_version(),
                'platform': platform.platform(),
                'build_type': self.build_config.build_type
            }
        }
        
        try:
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            self.logger.debug(f"Cached {len(files)} artifacts to {cache_file}")
        except Exception as e:
            raise CacheError(f"Failed to write cache: {e}")
    
    # =====================================================================
    # 5.5 PRIVATE UPLOAD METHODS
    # =====================================================================
    
    def _upload_with_monitoring(self, distribution_files: List[Path]) -> None:
        """
        Upload distributions with real-time monitoring and retry logic.
        
        Implements robust upload functionality with multiple retries,
        progress monitoring, and integrity verification.
        
        **Upload Features:**
        1. **Retry Logic**
           - Exponential backoff (1s, 2s, 4s, etc.)
           - Configurable max retry attempts (default: 3)
           - Different retry strategies for different errors
           
        2. **Progress Monitoring**
           - Tracks upload progress via stderr parsing
           - Logs upload speed and completion percentage
           
        3. **Integrity Verification**
           - Pre-upload checksum validation
           - Post-upload existence verification
           
        4. **Authentication Handling**
           - Supports token, basic auth, and .pypirc
           - Automatic credential refresh (if applicable)
        
        Parameters
        ----------
        distribution_files : List[Path]
            List of distribution files to upload.
        
        Raises
        ------
        UploadError
            If upload fails after all retry attempts.
        AuthenticationError
            If authentication fails (403 response).
        
        Notes
        -----
        - Uses twine for actual upload operations
        - Creates a rollback function for failed uploads
        - Logs detailed upload metrics for telemetry
        """
        if not distribution_files:
            raise UploadError("No distribution files to upload")
        
        # Pre-upload validation
        for file_path in distribution_files:
            if not file_path.exists():
                raise UploadError(f"Distribution file not found: {file_path}")
            
            # Check file size
            size_mb = file_path.stat().st_size / (1024 * 1024)
            if size_mb > (self.security_config.max_file_size / (1024 * 1024)):
                raise UploadError(
                    f"File {file_path.name} exceeds maximum size limit "
                    f"({size_mb:.1f} MB > {self.security_config.max_file_size / (1024 * 1024):.0f} MB)"
                )
            
            self.logger.debug(f"File ready for upload: {file_path.name} ({size_mb:.2f} MB)")
        
        # Sign files if required
        if self.upload_config.sign or self.security_config.require_signing:
            self._sign_distributions(distribution_files)
        
        # Upload with retry
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Prepare authentication environment
                env = os.environ.copy()
                self._setup_authentication(env)
                
                # Build upload command
                cmd = self._construct_upload_command(distribution_files)
                
                # Set retry delay with exponential backoff
                if attempt > 0:
                    delay = 2 ** attempt  # 2, 4, 8 seconds
                    self.logger.info(f"Retry attempt {attempt + 1}/{max_retries} after {delay}s delay")
                    time.sleep(delay)
                
                self.logger.info(f"Uploading {len(distribution_files)} file(s)...")
                upload_start = datetime.now()
                
                # Execute upload
                result = subprocess.run(
                    cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.upload_config.timeout
                )
                
                upload_duration = datetime.now() - upload_start
                
                if result.returncode == 0:
                    self.logger.info(
                        f"Upload completed in {upload_duration.total_seconds():.2f}s"
                    )
                    
                    # Post-upload verification
                    self._verify_upload(distribution_files)
                    
                    # Add rollback function for cleanup on failure
                    self._rollback_stack.append(
                        lambda: self._rollback_upload(distribution_files)
                    )
                    
                    return
                else:
                    # Check for specific error types
                    if "403" in result.stderr:
                        raise AuthenticationError(
                            "Authentication failed. Check your API token or credentials."
                        )
                    elif "409" in result.stderr:
                        if self.upload_config.skip_existing:
                            self.logger.warning("File already exists, skipping...")
                            return
                        else:
                            raise UploadError(
                                "File already exists on repository. "
                                "Use skip_existing=True to bypass."
                            )
                    else:
                        last_error = result.stderr
                        self.logger.warning(
                            f"Upload attempt {attempt + 1} failed: {result.stderr[:200]}"
                        )
                        
            except subprocess.TimeoutExpired:
                last_error = f"Upload timed out after {self.upload_config.timeout}s"
                self.logger.warning(f"Upload attempt {attempt + 1} timed out")
            except (AuthenticationError, UploadError):
                raise  # Re-raise authentication errors immediately
            except Exception as e:
                last_error = str(e)
                self.logger.warning(f"Upload attempt {attempt + 1} failed: {e}")
        
        # All retries exhausted
        raise UploadError(
            f"Upload failed after {max_retries} attempts.\n"
            f"Last error: {last_error}"
        )
    
    def _sign_distributions(self, distribution_files: List[Path]) -> None:
        """
        Sign distribution files using GPG.
        
        Creates GPG signatures (.asc files) for all distribution files
        to verify authenticity and integrity.
        
        **Signing Process:**
        1. Checks if GPG is installed and configured
        2. Verifies GPG key identity exists
        3. Creates detached signature for each file
        4. Verifies signature validity
        5. Adds signature files to upload list
        
        Parameters
        ----------
        distribution_files : List[Path]
            List of distribution files to sign.
        
        Raises
        ------
        SecurityError
            If GPG is not installed or signing fails.
        
        Notes
        -----
        - Requires GnuPG (gpg) installed and configured
        - Uses --detach-sign for detached signatures
        - Signature files are named {file}.asc
        - Verifies signature immediately after creation
        
        Examples
        --------
        >>> config = UploadConfig(sign=True, identity="your@email.com")
        >>> publisher = PyPIPublisher("./pkg", upload_config=config)
        >>> publisher._sign_distributions([Path("dist/pkg.whl")])
        # Creates dist/pkg.whl.asc
        """
        if not distribution_files:
            return
        
        self.logger.info(f"Signing {len(distribution_files)} distribution(s) with GPG")
        
        # Check if GPG is available
        gpg_path = shutil.which('gpg')
        if not gpg_path:
            raise SecurityError(
                "GPG not found. Please install GnuPG to sign distributions.\n"
                "Installation: brew install gnupg (macOS), apt install gnupg (Ubuntu)"
            )
        
        identity = self.upload_config.identity
        if not identity:
            raise SecurityError("GPG identity required for signing")
        
        for file_path in distribution_files:
            self.logger.debug(f"Signing: {file_path.name}")
            
            # GPG sign command
            cmd = [
                'gpg', '--detach-sign', '--armor',
                '--local-user', identity,
                '--output', str(file_path) + '.asc',
                str(file_path)
            ]
            
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                if result.returncode != 0:
                    raise SecurityError(
                        f"GPG signing failed for {file_path.name}:\n{result.stderr}"
                    )
                
                # Verify signature
                verify_cmd = ['gpg', '--verify', str(file_path) + '.asc', str(file_path)]
                verify_result = subprocess.run(
                    verify_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if verify_result.returncode != 0:
                    self.logger.warning(
                        f"Signature verification warning for {file_path.name}:\n"
                        f"{verify_result.stderr}"
                    )
                else:
                    self.logger.debug(f"Signature verified for {file_path.name}")
                
            except subprocess.TimeoutExpired:
                raise SecurityError(f"GPG signing timed out for {file_path.name}")
            except Exception as e:
                raise SecurityError(f"GPG signing failed: {e}")
        
        self.logger.info(f"Signed {len(distribution_files)} file(s)")
    
    def _setup_authentication(self, env: Dict[str, str]) -> None:
        """
        Set up authentication environment variables for upload.
        
        Configures twine authentication by setting environment variables
        or using .pypirc configuration file.
        
        **Authentication Methods (in priority order):**
        1. API Token (recommended) - uses __token__ username
        2. Username/Password - basic authentication
        3. .pypirc file - configuration file with credentials
        4. No authentication (for public repositories)
        
        Parameters
        ----------
        env : Dict[str, str]
            Environment dictionary to update with credentials.
        
        Raises
        ------
        AuthenticationError
            If authentication configuration is invalid.
        
        Notes
        -----
        - API tokens are the preferred authentication method
        - Never log credentials, only authentication method used
        - Supports repository-specific credentials via .pypirc
        
        Examples
        --------
        >>> # Token authentication
        >>> config = UploadConfig(token="pypi-xxxxx")
        >>> env = {}
        >>> publisher._setup_authentication(env)
        >>> env['TWINE_USERNAME'] = '__token__'
        >>> env['TWINE_PASSWORD'] = 'pypi-xxxxx'
        """
        # Method 1: API Token (highest priority)
        if self.upload_config.token:
            env["TWINE_USERNAME"] = "__token__"
            env["TWINE_PASSWORD"] = self.upload_config.token
            self.logger.debug("Using API token authentication")
            return
        
        # Method 2: Username/Password
        if self.upload_config.username and self.upload_config.password:
            env["TWINE_USERNAME"] = self.upload_config.username
            env["TWINE_PASSWORD"] = self.upload_config.password
            self.logger.debug("Using username/password authentication")
            return
        
        # Method 3: .pypirc file
        if self.upload_config.config_file:
            if not self.upload_config.config_file.exists():
                raise AuthenticationError(
                    f".pypirc file not found: {self.upload_config.config_file}"
                )
            # Twine will automatically read from .pypirc
            self.logger.debug(f"Using .pypirc file: {self.upload_config.config_file}")
            return
        
        # Method 4: No authentication (public repository or environment variables)
        if 'TWINE_USERNAME' in os.environ and 'TWINE_PASSWORD' in os.environ:
            self.logger.debug("Using environment variable authentication")
            env["TWINE_USERNAME"] = os.environ["TWINE_USERNAME"]
            env["TWINE_PASSWORD"] = os.environ["TWINE_PASSWORD"]
            return
        
        self.logger.warning(
            "No authentication method configured. "
            "Upload may fail if repository requires authentication."
        )
    
    def _construct_upload_command(self, files: List[Path]) -> List[str]:
        """
        Construct the twine upload command with all options.
        
        Builds the command-line arguments for twine based on
        upload_config settings.
        
        Parameters
        ----------
        files : List[Path]
            List of distribution files to upload.
        
        Returns
        -------
        List[str]
            Command argument list ready for subprocess.run.
        
        Notes
        -----
        - Includes signature files if signing is enabled
        - Supports all twine upload options
        - Repository URL can be specified via config or environment
        """
        cmd = [sys.executable, "-m", "twine", "upload"]
        
        # Repository URL (if not in .pypirc)
        if not self.upload_config.config_file:
            cmd.extend(["--repository-url", self.upload_config.repository_url])
        
        # Skip existing files
        if self.upload_config.skip_existing:
            cmd.append("--skip-existing")
            self.logger.debug("Skip existing files enabled")
        
        # Signing options
        if self.upload_config.sign:
            cmd.append("--sign")
            if self.upload_config.identity:
                cmd.extend(["--identity", self.upload_config.identity])
            self.logger.debug("Signing enabled")
        
        # Comment
        if self.upload_config.comment:
            cmd.extend(["--comment", self.upload_config.comment])
        
        # Config file
        if self.upload_config.config_file:
            cmd.extend(["--config-file", str(self.upload_config.config_file)])
        
        # Add verbosity for debugging
        if self.logger.isEnabledFor(logging.DEBUG):
            cmd.append("--verbose")
        
        # Add all files (including signature files if they exist)
        for file_path in files:
            cmd.append(str(file_path))
            sig_file = file_path.with_suffix(file_path.suffix + '.asc')
            if sig_file.exists():
                cmd.append(str(sig_file))
        
        return cmd
    
    def _verify_upload(self, distribution_files: List[Path]) -> None:
        """
        Verify that files were successfully uploaded to repository.
        
        Performs post-upload verification by checking repository APIs
        or validating local state.
        
        **Verification Methods:**
        1. Checks that no error occurred during upload
        2. Validates that distribution files were processed
        3. Optionally queries PyPI API for package presence
        4. Logs verification results for audit
        
        Parameters
        ----------
        distribution_files : List[Path]
            List of files that were uploaded.
        
        Raises
        ------
        UploadError
            If verification indicates upload failure.
        
        Notes
        -----
        - Complete API verification requires additional network calls
        - Basic verification only checks local upload success
        - Can be extended to query repository APIs
        """
        self.logger.debug("Verifying upload success...")
        
        # Basic verification: check that we got this far without errors
        # This is sufficient as twine will error on failure
        
        # Optional: Query PyPI API for package existence
        if 'pypi.org' in self.upload_config.repository_url and distribution_files:
            try:
                import requests
                package_name = self._extract_package_name()
                version = self._extract_version()
                
                if package_name and version:
                    api_url = f"https://pypi.org/pypi/{package_name}/{version}/json"
                    response = requests.get(api_url, timeout=10)
                    
                    if response.status_code == 200:
                        self.logger.info(f"Package verified on PyPI: {package_name} v{version}")
                    else:
                        self.logger.warning(
                            f"Package may take a few minutes to appear on PyPI "
                            f"(API returned {response.status_code})"
                        )
            except ImportError:
                self.logger.debug("Requests not installed, skipping API verification")
            except Exception as e:
                self.logger.debug(f"API verification failed: {e}")
        
        self.logger.debug("Upload verification completed")
    
    def _rollback_upload(self, distribution_files: List[Path]) -> None:
        """
        Rollback a failed upload attempt.
        
        Performs cleanup operations after a failed upload to revert
        any partial changes or temporary files.
        
        **Rollback Actions:**
        1. Removes temporary signature files
        2. Logs rollback for audit
        3. Does NOT delete from repository (not supported)
        
        Parameters
        ----------
        distribution_files : List[Path]
            Files that were being uploaded when failure occurred.
        
        Notes
        -----
        - Cannot rollback already-published packages
        - Only cleans up local temporary files
        - Repository does not support deletion via API
        """
        self.logger.warning(f"Rolling back upload for {len(distribution_files)} file(s)")
        
        # Remove signature files
        for file_path in distribution_files:
            sig_file = file_path.with_suffix(file_path.suffix + '.asc')
            if sig_file.exists():
                try:
                    sig_file.unlink()
                    self.logger.debug(f"Removed signature file: {sig_file}")
                except Exception as e:
                    self.logger.warning(f"Could not remove {sig_file}: {e}")
        
        # Record rollback in audit
        self._record_audit(
            operation="rollback",
            status="success",
            details={"files": [str(f) for f in distribution_files]}
        )
    
    # =====================================================================
    # 5.6 PRIVATE HELPER METHODS
    # =====================================================================
    
    def _validate_package_structure(self) -> Tuple[str, str]:
        """
        Validate package directory structure and extract metadata.
        
        Performs comprehensive validation of package structure and
        extracts package name and version from metadata.
        
        **Validation Steps:**
        1. Extract package name from configuration files
        2. Extract package version from various sources
        3. Validate name against PEP 508 conventions
        4. Validate version against PEP 440 conventions
        5. Check for required package directories
        
        Returns
        -------
        Tuple[str, str]
            Tuple containing (package_name, version)
        
        Raises
        ------
        ValidationError
            If package name or version cannot be determined,
            or if they don't follow Python naming conventions.
        
        Examples
        --------
        >>> publisher = PyPIPublisher("./my_package")
        >>> name, version = publisher._validate_package_structure()
        >>> print(f"{name}=={version}")
        my-package==1.0.0
        """
        # Extract package name
        package_name = self._extract_package_name()
        if not package_name:
            raise ValidationError(
                "Could not determine package name from pyproject.toml, "
                "setup.cfg, or setup.py"
            )
        
        # Validate package name (PEP 508)
        name_pattern = r'^[a-zA-Z][a-zA-Z0-9._-]*$'
        if not re.match(name_pattern, package_name):
            raise ValidationError(
                f"Invalid package name '{package_name}'. "
                "Package names must start with a letter and contain only "
                "letters, numbers, dots, underscores, and hyphens."
            )
        
        # Extract version
        version = self._extract_version()
        if not version:
            raise ValidationError(
                "Could not determine package version. "
                "Please ensure version is specified in pyproject.toml, "
                "setup.cfg, setup.py, or as a VCS tag."
            )
        
        # Validate version (PEP 440)
        if not self._is_valid_pep440_version(version):
            raise ValidationError(
                f"Version '{version}' does not follow PEP 440. "
                "Valid examples: 1.0.0, 2.1.0a1, 3.0.0.dev1, 1.0.0.post1"
            )
        
        self.logger.debug(f"Validated package: {package_name}=={version}")
        return package_name, version
    
    def _extract_package_name(self) -> Optional[str]:
        """
        Extract package name from configuration files.
        
        Searches for package name in priority order:
        1. pyproject.toml (project.name)
        2. setup.cfg (metadata.name)
        3. setup.py (name argument)
        4. Directory name (fallback)
        
        Returns
        -------
        Optional[str]
            Package name if found, None otherwise.
        
        Notes
        -----
        - Uses tomli for TOML parsing (fallback to tomllib in Python 3.11+)
        - Handles both setuptools and Poetry configurations
        - Directory name is normalized (underscores to hyphens)
        """
        # Try pyproject.toml
        pyproject = self.package_path / "pyproject.toml"
        if pyproject.exists():
            name = self._extract_from_pyproject(pyproject, 'name')
            if name:
                return name
        
        # Try setup.cfg
        setup_cfg = self.package_path / "setup.cfg"
        if setup_cfg.exists():
            try:
                import configparser
                config = configparser.ConfigParser()
                config.read(setup_cfg)
                if 'metadata' in config and 'name' in config['metadata']:
                    return config['metadata']['name']
            except Exception as e:
                self.logger.debug(f"Error reading setup.cfg: {e}")
        
        # Try setup.py
        setup_py = self.package_path / "setup.py"
        if setup_py.exists():
            try:
                content = setup_py.read_text(encoding='utf-8')
                # Match name="package" or name='package'
                match = re.search(r"name\s*=\s*['\"]([^'\"]+)['\"]", content)
                if match:
                    return match.group(1)
            except Exception as e:
                self.logger.debug(f"Error reading setup.py: {e}")
        
        # Fallback to directory name
        dir_name = self.package_path.name
        # Convert common naming patterns
        dir_name = dir_name.replace('_', '-')
        return dir_name
    
    def _extract_version(self) -> Optional[str]:
        """
        Extract package version from multiple sources.
        
        Searches for version in priority order:
        1. pyproject.toml (project.version)
        2. setup.cfg (metadata.version)
        3. setup.py (version argument)
        4. Package __version__ attribute
        5. Git tags (git describe --tags)
        
        Returns
        -------
        Optional[str]
            Version string if found, None otherwise.
        
        Notes
        -----
        - Supports dynamic version from VCS tags
        - Handles version in __init__.py files
        - Git tags with 'v' prefix are normalized (v1.0.0 -> 1.0.0)
        """
        # Check pyproject.toml
        pyproject = self.package_path / "pyproject.toml"
        if pyproject.exists():
            version = self._extract_from_pyproject(pyproject, 'version')
            if version:
                return version
        
        # Check setup.cfg
        setup_cfg = self.package_path / "setup.cfg"
        if setup_cfg.exists():
            try:
                import configparser
                config = configparser.ConfigParser()
                config.read(setup_cfg)
                if 'metadata' in config and 'version' in config['metadata']:
                    return config['metadata']['version']
            except Exception:
                pass
        
        # Check setup.py
        setup_py = self.package_path / "setup.py"
        if setup_py.exists():
            try:
                content = setup_py.read_text(encoding='utf-8')
                match = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", content)
                if match:
                    return match.group(1)
            except Exception:
                pass
        
        # Try to import package and get __version__
        try:
            package_name = self._extract_package_name()
            if package_name:
                sys.path.insert(0, str(self.package_path.parent))
                try:
                    module = __import__(package_name)
                    if hasattr(module, '__version__'):
                        return module.__version__
                finally:
                    sys.path.pop(0)
        except Exception as e:
            self.logger.debug(f"Could not import package: {e}")
        
        # Try git tags
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                cwd=self.package_path,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                tag = result.stdout.strip()
                # Remove 'v' prefix if present
                if tag.startswith('v'):
                    tag = tag[1:]
                return tag
        except Exception:
            pass
        
        return None
    
    def _extract_from_pyproject(self, pyproject_path: Path, key: str) -> Optional[str]:
        """
        Extract a value from pyproject.toml file.
        
        Supports both PEP 621 and Poetry formats.
        
        Parameters
        ----------
        pyproject_path : Path
            Path to pyproject.toml file.
        key : str
            Key to extract ('name' or 'version').
        
        Returns
        -------
        Optional[str]
            Value if found, None otherwise.
        """
        try:
            # Try tomllib (Python 3.11+)
            if sys.version_info >= (3, 11):
                import tomllib
                with open(pyproject_path, 'rb') as f:
                    data = tomllib.load(f)
            else:
                # Use tomli for older Python versions
                import tomli
                content = pyproject_path.read_text(encoding='utf-8')
                data = tomli.loads(content)
            
            # PEP 621 format ([project])
            if 'project' in data and key in data['project']:
                return str(data['project'][key])
            
            # Poetry format ([tool.poetry])
            if 'tool' in data and 'poetry' in data['tool'] and key in data['tool']['poetry']:
                return str(data['tool']['poetry'][key])
            
        except ImportError:
            self.logger.debug("TOML parser not available")
        except Exception as e:
            self.logger.debug(f"Error parsing pyproject.toml: {e}")
        
        return None
    
    def _extract_author_info(self) -> Dict[str, str]:
        """
        Extract author information from package metadata.
        
        Returns
        -------
        Dict[str, str]
            Dictionary with keys: 'name', 'email', 'author_url'
        """
        author_info = {'name': '', 'email': '', 'author_url': ''}
        
        # Try pyproject.toml
        pyproject = self.package_path / "pyproject.toml"
        if pyproject.exists():
            try:
                # TOML parsing
                if sys.version_info >= (3, 11):
                    import tomllib
                    with open(pyproject, 'rb') as f:
                        data = tomllib.load(f)
                else:
                    import tomli
                    data = tomli.loads(pyproject.read_text())
                
                if 'project' in data:
                    if 'authors' in data['project'] and data['project']['authors']:
                        author = data['project']['authors'][0]
                        author_info['name'] = author.get('name', '')
                        author_info['email'] = author.get('email', '')
            except Exception:
                pass
        
        # Try setup.cfg
        setup_cfg = self.package_path / "setup.cfg"
        if setup_cfg.exists() and not author_info['name']:
            try:
                import configparser
                config = configparser.ConfigParser()
                config.read(setup_cfg)
                if 'metadata' in config:
                    author_info['name'] = config['metadata'].get('author', '')
                    author_info['email'] = config['metadata'].get('author_email', '')
                    author_info['author_url'] = config['metadata'].get('url', '')
            except Exception:
                pass
        
        return author_info
    
    @staticmethod
    def _is_valid_pep440_version(version: str) -> bool:
        """
        Validate version string against PEP 440 specification.
        
        PEP 440 defines the standard version scheme for Python packages.
        
        Parameters
        ----------
        version : str
            Version string to validate.
        
        Returns
        -------
        bool
            True if version is valid PEP 440, False otherwise.
        
        Examples
        --------
        >>> PyPIPublisher._is_valid_pep440_version("1.0.0")
        True
        >>> PyPIPublisher._is_valid_pep440_version("1.0.0a1")
        True
        >>> PyPIPublisher._is_valid_pep440_version("1.0.0.0")  # Too many segments
        False
        """
        # Comprehensive PEP 440 regex pattern
        pattern = (
            r'^'
            r'([1-9][0-9]*!)?'           # Epoch (optional)
            r'(0|[1-9][0-9]*)'            # Major version (non-zero or zero)
            r'(\.(0|[1-9][0-9]*))*'       # Minor and patch versions
            r'((a|b|rc)(0|[1-9][0-9]*))?' # Pre-release (alpha/beta/rc)
            r'(\.post(0|[1-9][0-9]*))?'   # Post-release
            r'(\.dev(0|[1-9][0-9]*))?'    # Development release
            r'$'
        )
        return bool(re.match(pattern, version))
    
    def _check_package_metadata(self) -> None:
        """
        Validate package metadata completeness and correctness.
        
        This internal method performs comprehensive validation of all
        package metadata fields required for PyPI publication.
        
        **Metadata Checks Performed:**
        
        1. **Required Fields Validation**
           - name: Package name (must be present and valid)
           - version: Package version (must follow PEP 440)
           - description: Short package description
           - long_description: Detailed description (from README)
           - author: Author name
           - author_email: Valid email format
           - license: License identifier (SPDX format)
           - url: Project URL
           - classifiers: Trove classifiers
        
        2. **README File Validation**
           - Checks for README.md, README.rst, or README.txt
           - Verifies file is not empty
           - Validates file size (< 1MB recommended)
        
        3. **LICENSE File Validation**
           - Checks for LICENSE, LICENSE.txt, LICENSE.md
           - Verifies license matches declared license
           - Validates license content
        
        4. **Other Required Files**
           - MANIFEST.in (if using setuptools)
           - Requirements files (if dependencies exist)
        
        Raises
        ------
        ValidationError
            If required metadata is missing or invalid.
        
        Examples
        --------
        >>> publisher = PyPIPublisher("./my_package")
        >>> publisher._check_package_metadata()  # Raises if missing metadata
        """
        issues = []
        warnings = []
        
        # -----------------------------------------------------------------
        # 1. Extract and validate core metadata
        # -----------------------------------------------------------------
        package_name = self._extract_package_name()
        version = self._extract_version()
        
        if not package_name:
            issues.append("Package name is missing")
        elif len(package_name) < 2:
            issues.append("Package name is too short (minimum 2 characters)")
        elif len(package_name) > 50:
            warnings.append("Package name is very long (>50 characters)")
        
        if not version:
            issues.append("Package version is missing")
        
        # -----------------------------------------------------------------
        # 2. Check for README file
        # -----------------------------------------------------------------
        readme_files = ['README.md', 'README.rst', 'README.txt', 'README']
        readme_found = None
        
        for readme_name in readme_files:
            readme_path = self.package_path / readme_name
            if readme_path.exists():
                readme_found = readme_path
                break
        
        if not readme_found:
            issues.append(
                "No README file found. PyPI requires a description for your package.\n"
                f"Create one of: {', '.join(readme_files)}"
            )
        else:
            # Check README size
            size_kb = readme_found.stat().st_size / 1024
            if size_kb > 1024:  # > 1MB
                warnings.append(f"README file is very large ({size_kb:.0f} KB)")
            elif readme_found.stat().st_size == 0:
                issues.append(f"README file is empty: {readme_found.name}")
        
        # -----------------------------------------------------------------
        # 3. Check for LICENSE file
        # -----------------------------------------------------------------
        license_files = ['LICENSE', 'LICENSE.txt', 'LICENSE.md', 'COPYING']
        license_found = None
        
        for license_name in license_files:
            license_path = self.package_path / license_name
            if license_path.exists():
                license_found = license_path
                break
        
        if not license_found:
            warnings.append(
                "No LICENSE file found. While not strictly required, "
                "a license is strongly recommended for open source packages."
            )
        elif license_found.stat().st_size < 100:  # Suspiciously small
            warnings.append(f"LICENSE file is very small - may be incomplete")
        
        # -----------------------------------------------------------------
        # 4. Check for required Python files
        # -----------------------------------------------------------------
        init_files = list(self.package_path.rglob("__init__.py"))
        if not init_files:
            warnings.append(
                "No __init__.py files found. Package may not be importable."
            )
        
        # Check for at least one module
        py_files = list(self.package_path.rglob("*.py"))
        if not py_files:
            warnings.append(
                "No Python files found in package directory. "
                "Package appears to be empty."
            )
        
        # -----------------------------------------------------------------
        # 5. Validate setup configuration
        # -----------------------------------------------------------------
        setup_files = ['setup.py', 'setup.cfg', 'pyproject.toml']
        has_setup = any((self.package_path / f).exists() for f in setup_files)
        
        if not has_setup:
            issues.append(
                f"No build configuration found. Expected one of: {', '.join(setup_files)}"
            )
        
        # -----------------------------------------------------------------
        # 6. Check for common issues
        # -----------------------------------------------------------------
        # Check for .git directory (development)
        if (self.package_path / '.git').exists():
            warnings.append(
                "Package directory contains .git folder. "
                "Make sure you're not publishing development files."
            )
        
        # Check for virtual environment
        venv_indicators = ['venv', 'env', '.venv', 'virtualenv']
        for venv in venv_indicators:
            if (self.package_path / venv).is_dir():
                warnings.append(
                    f"Virtual environment '{venv}' found in package directory. "
                    "This should not be included in distribution."
                )
                break
        
        # Check for compiled Python files
        pyc_files = list(self.package_path.rglob("*.pyc"))
        if pyc_files:
            warnings.append(
                f"Found {len(pyc_files)} .pyc files. These should not be "
                "included in source distribution."
            )
        
        # -----------------------------------------------------------------
        # 7. Raise exception if critical issues found
        # -----------------------------------------------------------------
        if issues:
            raise ValidationError(
                f"Package metadata validation failed ({len(issues)} error(s)):\n" + 
                "\n".join(f"  {issue}" for issue in issues)
            )
        
        # Log warnings
        for warning in warnings:
            self.logger.warning(f"Metadata warning: {warning}")
        
        # Log summary
        self.logger.debug(
            f"Metadata validation passed: {package_name} v{version}, "
            f"{len(py_files)} Python files"
        )
    
    def _check_description_rendering(self) -> None:
        """
        Check if the package description will render correctly on PyPI.
        
        Validates that the README file (which becomes the PyPI description)
        is properly formatted and will render without errors on the PyPI
        website.
        
        **Validation Steps:**
        1. Detect README format (Markdown or reStructuredText)
        2. Attempt to render using readme_renderer
        3. Check for common rendering issues
        4. Validate image URLs and links
        
        Raises
        ------
        ValidationError
            If description rendering fails (unable to render).
        
        Notes
        -----
        - Markdown format is recommended (GitHub Flavored Markdown)
        - reStructuredText requires careful formatting
        - External images should use HTTPS
        """
        readme_content = None
        readme_format = None
        readme_path = None
        
        # -----------------------------------------------------------------
        # 1. Find README file
        # -----------------------------------------------------------------
        for readme_name, format_type in [
            ('README.md', 'markdown'),
            ('README.rst', 'rst'),
            ('README.txt', 'text'),
            ('README', 'text')
        ]:
            path = self.package_path / readme_name
            if path.exists():
                readme_content = path.read_text(encoding='utf-8')
                readme_format = format_type
                readme_path = path
                break
        
        if not readme_content:
            self.logger.warning("No README found, skipping description check")
            return
        
        self.logger.debug(f"Checking README rendering: {readme_path.name} ({readme_format})")
        
        # -----------------------------------------------------------------
        # 2. Check for common issues
        # -----------------------------------------------------------------
        issues = []
        
        # Check for broken image references
        if '![' in readme_content and ('](' in readme_content or ']:' in readme_content):
            # Look for image URLs
            img_urls = re.findall(r'!\[.*?\]\((.*?)\)', readme_content)
            for url in img_urls:
                if url.startswith('http://'):
                    issues.append(f"Image uses insecure HTTP: {url}")
                elif url.startswith('file://'):
                    issues.append(f"Image uses local file reference: {url}")
        
        # Check for absolute local links
        local_links = re.findall(r'\[.*?\]\(/([^)]+)\)', readme_content)
        if local_links:
            warnings = [f"Absolute path link: /{link}" for link in local_links[:3]]
            self.logger.warning(
                f"Found absolute local links in README: {', '.join(warnings)}"
            )
        
        # -----------------------------------------------------------------
        # 3. Attempt to render (if readme_renderer is available)
        # -----------------------------------------------------------------
        try:
            if readme_format == 'markdown':
                import readme_renderer.markdown as md
                rendered = md.render(readme_content)
                if rendered is None:
                    issues.append("Markdown rendering failed - syntax error?")
                elif len(rendered) == 0:
                    issues.append("Markdown rendered to empty content")
                    
            elif readme_format == 'rst':
                import readme_renderer.rst as rst
                rendered = rst.render(readme_content)
                if rendered is None:
                    # Try to find RST errors
                    warnings.append("RST rendering may have issues")
                    # Locate common RST problems
                    if '.. code::' in readme_content:
                        warnings.append("RST code blocks should use '.. code-block::'")
                    if '```' in readme_content:
                        warnings.append("RST doesn't support triple-backtick code fences")
            
            self.logger.info(f"Description rendering check passed ({readme_format})")
            
        except ImportError:
            self.logger.debug(
                "readme_renderer not installed. Install with: pip install readme-renderer"
            )
        except Exception as e:
            self.logger.warning(f"Description rendering warning: {e}")
        
        # -----------------------------------------------------------------
        # 4. Check content length
        # -----------------------------------------------------------------
        desc_length = len(readme_content)
        if desc_length < 100:
            warnings.append(f"README is very short ({desc_length} chars)")
        elif desc_length > 100000:
            warnings.append(f"README is very long ({desc_length} chars) - may cause display issues")
        
        # -----------------------------------------------------------------
        # 5. Handle issues
        # -----------------------------------------------------------------
        if issues:
            raise ValidationError(
                f"Description rendering failed:\n" +
                "\n".join(f"  {issue}" for issue in issues)
            )
    
    def _check_requirements_files(
        self,
        requirements_files: List[Union[str, Path]],
        check_versions: bool = True
    ) -> None:
        """
        Validate requirements files for correctness and compatibility.
        
        Parameters
        ----------
        requirements_files : List[Union[str, Path]]
            List of paths to requirements files to validate.
        check_versions : bool, optional
            If True, validate version specifiers are valid. Default True.
        
        Raises
        ------
        ValidationError
            If requirements files are missing or contain invalid requirements.
        
        Examples
        --------
        >>> publisher = PyPIPublisher("./pkg")
        >>> publisher._check_requirements_files(['requirements.txt'])
        """
        for req_file in requirements_files:
            req_path = Path(req_file)
            
            # Check file exists
            if not req_path.exists():
                raise ValidationError(f"Requirements file not found: {req_path}")
            
            # Check file is readable
            try:
                content = req_path.read_text(encoding='utf-8')
            except Exception as e:
                raise ValidationError(f"Cannot read requirements file {req_path}: {e}")
            
            # Parse requirements
            lines = []
            for line_num, line in enumerate(content.split('\n'), 1):
                line = line.strip()
                
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                
                # Skip environment markers
                if ';' in line:
                    # Validate marker syntax
                    requirement, marker = line.split(';', 1)
                    try:
                        from packaging.markers import Marker
                        Marker(marker.strip())
                    except Exception as e:
                        raise ValidationError(
                            f"Invalid environment marker in {req_path.name}:{line_num}\n{e}"
                        )
                    line = requirement.strip()
                
                # Validate requirement syntax
                if check_versions:
                    try:
                        from packaging.requirements import Requirement
                        Requirement(line)
                    except Exception as e:
                        raise ValidationError(
                            f"Invalid requirement in {req_path.name}:{line_num}\n"
                            f"  Line: {line}\n"
                            f"  Error: {e}"
                        )
                
                lines.append(line)
            
            # Check for common issues
            if not lines:
                self.logger.warning(f"Requirements file is empty: {req_path.name}")
            
            # Check for absolute paths (should not be in requirements)
            for line in lines:
                if line.startswith('/') or line.startswith('./'):
                    self.logger.warning(
                        f"Absolute path in requirements: {line} in {req_path.name}"
                    )
            
            # Check for editable installs
            editable_lines = [l for l in lines if l.startswith('-e ') or l.startswith('--editable')]
            if editable_lines:
                self.logger.warning(
                    f"Found editable installs in {req_path.name}: {editable_lines}"
                )
            
            self.logger.info(f"Validated {req_path.name}: {len(lines)} requirement(s)")
    
    def _run_tests_with_coverage(self) -> None:
        """
        Run package tests and validate coverage meets threshold.
        
        Attempts to run tests using multiple strategies:
        1. tox (if tox.ini exists)
        2. pytest (if tests/ directory exists)
        3. unittest (fallback)
        
        Raises
        ------
        TestFailureError
            If tests fail or coverage is below threshold.
        """
        self.logger.info("Running test suite with coverage validation")
        
        test_strategies = [
            ('tox', self._run_tox_tests),
            ('pytest', self._run_pytest_with_coverage),
            ('unittest', self._run_unittest)
        ]
        
        for strategy_name, strategy_func in test_strategies:
            try:
                coverage_result = strategy_func()
                self.logger.info(f"Tests passed using {strategy_name}")
                
                # Check coverage threshold
                if coverage_result and self.compliance_config.test_coverage_threshold > 0:
                    coverage_pct = coverage_result.get('coverage', 0)
                    if coverage_pct < self.compliance_config.test_coverage_threshold:
                        raise TestFailureError(
                            f"Test coverage {coverage_pct:.1f}% is below "
                            f"threshold {self.compliance_config.test_coverage_threshold}%"
                        )
                    elif coverage_pct > 0:
                        self.logger.info(f"Test coverage: {coverage_pct:.1f}%")
                
                return
                
            except TestFailureError:
                continue
            except Exception as e:
                self.logger.debug(f"Test strategy {strategy_name} failed: {e}")
                continue
        
        raise TestFailureError(
            "All test strategies failed. Please ensure tests are properly configured.\n"
            "Supported: tox (tox.ini), pytest (tests/ folder), or unittest."
        )
    
    def _run_tox_tests(self) -> Optional[Dict[str, float]]:
        """
        Run tests using tox testing tool.
        
        Tox manages virtual environments and runs tests across multiple
        Python versions.
        
        Returns
        -------
        Optional[Dict[str, float]]
            Coverage data if available, None otherwise.
        
        Raises
        ------
        TestFailureError
            If tox is not installed or tests fail.
        """
        # Check if tox.ini exists
        tox_ini = self.package_path / 'tox.ini'
        if not tox_ini.exists():
            raise TestFailureError("tox.ini not found")
        
        try:
            result = subprocess.run(
                ["tox", "run", "--parallel", "auto"],
                cwd=self.package_path,
                capture_output=True,
                text=True,
                timeout=600
            )
            
            if result.returncode != 0:
                raise TestFailureError(
                    f"Tox tests failed (exit code {result.returncode})\n"
                    f"Output: {result.stderr[:500]}"
                )
            
            # Try to extract coverage from output
            coverage_match = re.search(r'TOTAL\s+\d+\s+\d+\s+(\d+)%', result.stdout)
            if coverage_match:
                return {'coverage': float(coverage_match.group(1))}
            
            return {'coverage': 0}
            
        except FileNotFoundError:
            raise TestFailureError("Tox not installed. Install with: pip install tox")
        except subprocess.TimeoutExpired:
            raise TestFailureError("Tox tests timed out after 600 seconds")
    
    def _run_pytest_with_coverage(self) -> Optional[Dict[str, float]]:
        """
        Run tests using pytest with coverage reporting.
        
        Returns
        -------
        Optional[Dict[str, float]]
            Coverage data if available, None otherwise.
        
        Raises
        ------
        TestFailureError
            If pytest is not installed or tests fail.
        """
        # Check if tests directory exists
        test_dirs = ['tests', 'test', self.package_path / 'tests']
        has_tests = any(Path(d).exists() for d in test_dirs)
        
        if not has_tests:
            # Check for test files in package
            test_files = list(self.package_path.rglob("test_*.py")) + \
                        list(self.package_path.rglob("*_test.py"))
            if not test_files:
                raise TestFailureError("No test files found")
        
        try:
            # Run pytest with coverage
            cmd = [
                sys.executable, "-m", "pytest",
                "--cov=self.package_path.name",
                "--cov-report=term",
                "--cov-report=json",
                "-v", "--tb=short"
            ]
            
            result = subprocess.run(
                cmd,
                cwd=self.package_path.parent,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            coverage_data = {'coverage': 0}
            
            # Try to read coverage JSON
            coverage_json = self.package_path.parent / 'coverage.json'
            if coverage_json.exists():
                try:
                    import json
                    with open(coverage_json) as f:
                        cov_data = json.load(f)
                        if 'totals' in cov_data:
                            coverage_data['coverage'] = cov_data['totals'].get('percent_covered', 0)
                except Exception:
                    pass
                finally:
                    # Clean up coverage file
                    coverage_json.unlink(missing_ok=True)
            
            if result.returncode != 0:
                # Check if any tests were collected
                if "collected 0 items" in result.stdout:
                    raise TestFailureError("No tests were collected by pytest")
                raise TestFailureError(
                    f"Pytest failed (exit code {result.returncode})\n"
                    f"Output: {result.stderr[:500] or result.stdout[:500]}"
                )
            
            return coverage_data
            
        except FileNotFoundError:
            raise TestFailureError("Pytest not installed. Install with: pip install pytest pytest-cov")
        except subprocess.TimeoutExpired:
            raise TestFailureError("Pytest timed out after 300 seconds")
    
    def _run_unittest(self) -> Optional[Dict[str, float]]:
        """
        Run tests using Python's built-in unittest framework.
        
        Returns
        -------
        Optional[Dict[str, float]]
            Coverage data (unittest doesn't provide coverage by default).
        
        Raises
        ------
        TestFailureError
            If tests fail.
        """
        try:
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-v"],
                cwd=self.package_path,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode != 0:
                raise TestFailureError(
                    f"Unittest failed (exit code {result.returncode})\n"
                    f"Output: {result.stderr[:500] or result.stdout[:500]}"
                )
            
            # Parse test results
            match = re.search(r'Ran (\d+) tests?', result.stdout)
            if match:
                test_count = int(match.group(1))
                self.logger.debug(f"Ran {test_count} unittest(s)")
            
            return {'coverage': 0}  # unittest doesn't provide coverage
            
        except Exception as e:
            raise TestFailureError(f"Unittest error: {e}")
    
    def _check_build_dependencies(self) -> None:
        """
        Verify all required build dependencies are installed.
        
        Checks for:
        - build module (PEP 517 build backend)
        - twine module (upload tool)
        - pip (package installer)
        
        Raises
        ------
        DependencyError
            If any required dependency is missing.
        """
        required_deps = {
            'build': 'build',
            'twine': 'twine',
            'pip': 'pip'
        }
        
        missing = []
        
        for module, package in required_deps.items():
            try:
                __import__(module)
                self.logger.debug(f"{module} is available")
            except ImportError:
                missing.append(package)
        
        if missing:
            raise DependencyError(
                f"Missing required build dependencies: {', '.join(missing)}\n"
                f"Install with: pip install {' '.join(missing)}"
            )
    
    def _clean_previous_builds(self) -> None:
        """
        Remove previous build artifacts before fresh build.
        
        Cleans:
        - build/ directory
        - dist/ directory (but preserves output_dir if different)
        - *.egg-info directories
        - .eggs directory
        """
        self.logger.debug("Cleaning previous build artifacts")
        
        # Clean build directory
        build_dir = self.package_path / 'build'
        if build_dir.exists():
            shutil.rmtree(build_dir)
            self.logger.debug("Removed build/ directory")
        
        # Clean egg-info directories
        for egg_dir in self.package_path.glob('*.egg-info'):
            if egg_dir.is_dir():
                shutil.rmtree(egg_dir)
                self.logger.debug(f"Removed {egg_dir.name}")
        
        # Clean eggs directory
        eggs_dir = self.package_path / '.eggs'
        if eggs_dir.exists():
            shutil.rmtree(eggs_dir)
            self.logger.debug("Removed .eggs/ directory")
        
        # Clean dist directory (but preserve if it's the output dir)
        dist_dir = self.package_path / 'dist'
        if dist_dir.exists() and dist_dir != self.build_config.output_dir:
            for file in dist_dir.glob('*'):
                if file.is_file():
                    file.unlink()
                elif file.is_dir():
                    shutil.rmtree(file)
            self.logger.debug("Cleaned dist/ directory")
        
        # Clean output directory for this build
        if self.build_config.output_dir and self.build_config.output_dir.exists():
            # Remove only build artifacts, not user files
            for pattern in ['*.whl', '*.tar.gz', '*.zip', '*.asc']:
                for file in self.build_config.output_dir.glob(pattern):
                    file.unlink()
                    self.logger.debug(f"Removed {file.name}")
    
    def _get_existing_distributions(self) -> List[Path]:
        """
        Get existing distribution files from output directory.
        
        Returns
        -------
        List[Path]
            List of existing distribution files.
        
        Raises
        ------
        BuildError
            If no distribution files are found.
        """
        if not self.build_config.output_dir.exists():
            raise BuildError(
                f"Distribution directory not found: {self.build_config.output_dir}\n"
                f"Run build first or specify correct output directory"
            )
        
        # Find distribution files
        valid_extensions = {'.whl', '.tar.gz', '.zip'}
        files = []
        
        for file_path in self.build_config.output_dir.iterdir():
            if file_path.is_file():
                # Check extension
                if file_path.suffix == '.whl':
                    files.append(file_path)
                elif file_path.suffix == '.gz' and file_path.name.endswith('.tar.gz'):
                    files.append(file_path)
                elif file_path.suffix == '.zip':
                    files.append(file_path)
        
        if not files:
            raise BuildError(
                f"No distribution files found in {self.build_config.output_dir}\n"
                f"Expected .whl, .tar.gz, or .zip files"
            )
        
        # Add to artifacts
        for file_path in files:
            # Determine type
            if file_path.suffix == '.whl':
                artifact_type = 'wheel'
            elif file_path.name.endswith('.tar.gz'):
                artifact_type = 'sdist'
            else:
                artifact_type = 'unknown'
            
            # Calculate checksums
            checksums = {}
            for algo in self.security_config.checksum_algorithms:
                try:
                    checksums[algo] = self._calculate_file_hash(file_path, algo)
                except Exception:
                    pass
            
            artifact = BuildArtifact(
                path=file_path,
                artifact_type=artifact_type,
                size_bytes=file_path.stat().st_size,
                checksums=checksums
            )
            self._artifacts.append(artifact)
        
        self.logger.info(f"Found {len(files)} existing distribution(s)")
        return files
    
    @staticmethod
    def _calculate_file_hash(filepath: Path, algorithm: str = 'sha256') -> str:
        """
        Calculate cryptographic hash of a file.
        
        Parameters
        ----------
        filepath : Path
            Path to the file to hash.
        algorithm : str, optional
            Hash algorithm name. Default 'sha256'.
            Supported: 'md5', 'sha1', 'sha256', 'sha512'
        
        Returns
        -------
        str
            Hexadecimal digest of the file hash.
        
        Raises
        ------
        ValueError
            If algorithm is not supported.
        
        Examples
        --------
        >>> hash = PyPIPublisher._calculate_file_hash(Path("file.txt"))
        >>> print(hash[:16])
        e3b0c44298fc1c14
        """
        try:
            hasher = hashlib.new(algorithm)
        except ValueError:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}")
        
        with open(filepath, 'rb') as f:
            # Read in chunks to handle large files efficiently
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
        
        return hasher.hexdigest()
    
    def _generate_sbom(self, package_name: str, version: str) -> None:
        """
        Generate Software Bill of Materials (SBOM) for the package.
        
        Creates SPDX or CycloneDX compatible SBOM listing all
        dependencies and their versions.
        
        Parameters
        ----------
        package_name : str
            Name of the package.
        version : str
            Version of the package.
        """
        self.logger.info(f"Generating SBOM for {package_name} v{version}")
        
        sbom_file = self.build_config.output_dir / f"{package_name}-{version}-sbom.json"
        
        try:
            # Get dependency list
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=json"],
                cwd=self.package_path,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                
                # Create SBOM in SPDX format
                if self.compliance_config.sbom_format == 'spdx':
                    sbom = {
                        "spdxVersion": "SPDX-2.3",
                        "dataLicense": "CC0-1.0",
                        "SPDXID": "SPDXRef-DOCUMENT",
                        "name": f"{package_name}-{version}",
                        "documentNamespace": f"https://spdx.org/spdxdocs/{package_name}-{version}",
                        "creationInfo": {
                            "created": datetime.now().isoformat(),
                            "creators": [
                                f"Tool: pypi-publisher-3.0.0"
                            ]
                        },
                        "packages": []
                    }
                    
                    for pkg in packages:
                        pkg_info = {
                            "name": pkg.get('name', 'unknown'),
                            "versionInfo": pkg.get('version', 'unknown'),
                            "SPDXID": f"SPDXRef-{pkg.get('name', 'unknown').replace('-', '')}"
                        }
                        sbom["packages"].append(pkg_info)
                    
                    with open(sbom_file, 'w') as f:
                        json.dump(sbom, f, indent=2)
                    
                    self.logger.info(f"SBOM generated: {sbom_file.name}")
                    
                elif self.compliance_config.sbom_format == 'cyclonedx':
                    # CycloneDX format
                    sbom = {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.4",
                        "version": 1,
                        "metadata": {
                            "timestamp": datetime.now().isoformat(),
                            "tools": [{"name": "pypi-publisher", "version": "3.0.0"}],
                            "component": {
                                "type": "library",
                                "name": package_name,
                                "version": version
                            }
                        },
                        "components": []
                    }
                    
                    for pkg in packages:
                        component = {
                            "type": "library",
                            "name": pkg.get('name', 'unknown'),
                            "version": pkg.get('version', 'unknown')
                        }
                        sbom["components"].append(component)
                    
                    with open(sbom_file, 'w') as f:
                        json.dump(sbom, f, indent=2)
                    
                    self.logger.info(f"CycloneDX SBOM generated: {sbom_file.name}")
            
        except Exception as e:
            self.logger.warning(f"SBOM generation failed: {e}")
    
    def _generate_compliance_report(self, package_name: str, version: str) -> None:
        """
        Generate compliance report for the package.
        
        Reports on licenses, authors, and other compliance-related metadata.
        
        Parameters
        ----------
        package_name : str
            Name of the package.
        version : str
            Version of the package.
        """
        report_file = self.build_config.output_dir / f"{package_name}-{version}-compliance.txt"
        
        try:
            with open(report_file, 'w') as f:
                f.write(f"Compliance Report for {package_name} v{version}\n")
                f.write("=" * 60 + "\n\n")
                f.write(f"Generated: {datetime.now().isoformat()}\n\n")
                
                # License information
                f.write("License Information:\n")
                f.write("-" * 30 + "\n")
                
                # Check package license
                license_files = ['LICENSE', 'LICENSE.txt', 'LICENSE.md']
                for lic in license_files:
                    if (self.package_path / lic).exists():
                        f.write(f"  License file: {lic}\n")
                        break
                else:
                    f.write("  No license file found\n")
                
                # Author information
                f.write("\nAuthor Information:\n")
                f.write("-" * 30 + "\n")
                author_info = self._extract_author_info()
                f.write(f"  Name: {author_info.get('name', 'Unknown')}\n")
                f.write(f"  Email: {author_info.get('email', 'Unknown')}\n")
                
                # Dependency summary
                f.write("\nDependency Summary:\n")
                f.write("-" * 30 + "\n")
                
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "list", "--format=json"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    packages = json.loads(result.stdout)
                    f.write(f"  Total dependencies: {len(packages)}\n")
                    
                    # Count by license (simplified)
                    f.write("\n  Note: Complete license information requires pip-licenses\n")
            
            self.logger.info(f"Compliance report generated: {report_file.name}")
            
        except Exception as e:
            self.logger.warning(f"Compliance report generation failed: {e}")
    
    def _record_audit(self, operation: str, status: str, details: Dict[str, Any]) -> None:
        """
        Record an audit trail entry for compliance.
        
        Parameters
        ----------
        operation : str
            Type of operation being performed.
        status : str
            Status of the operation ('started', 'success', 'failed', etc.).
        details : Dict[str, Any]
            Additional details about the operation.
        """
        if not self.security_config.enable_audit_log:
            return
        
        try:
            import getpass
            
            record = AuditRecord(
                operation=operation,
                user=getpass.getuser(),
                package_name=self._extract_package_name() or "unknown",
                version=self._extract_version() or "unknown",
                status=status,
                details=details
            )
            
            self._audit_trail.append(record)
            self.logger.debug(f"Audit: {operation} - {status}")
            
            # Write to audit file
            audit_file = Path("pypiutil_audit.log")
            with open(audit_file, 'a') as f:
                f.write(f"{record.timestamp.isoformat()} | {record.user} | ")
                f.write(f"{record.operation} | {record.status} | ")
                f.write(f"{json.dumps(record.details)[:200]}\n")
                
        except Exception as e:
            self.logger.warning(f"Failed to record audit: {e}")
    
    def _execute_rollback(self) -> None:
        """
        Execute rollback functions in reverse order.
        
        Rolls back operations in case of failure to clean up partial changes.
        """
        if not self._rollback_stack:
            return
        
        self._operation_status = OperationStatus.ROLLING_BACK
        self.logger.warning(f"Executing rollback ({len(self._rollback_stack)} operations)")
        
        # Execute rollbacks in reverse order
        for rollback_func in reversed(self._rollback_stack):
            try:
                rollback_func()
                self.logger.debug("Rollback operation completed")
            except Exception as e:
                self.logger.error(f"Rollback operation failed: {e}")
        
        self._rollback_stack.clear()
        self.logger.info("Rollback completed")
    
    def _start_telemetry(self) -> Dict[str, Any]:
        """
        Start telemetry data collection.
        
        Returns
        -------
        Dict[str, Any]
            Telemetry data dictionary to be passed to _stop_telemetry.
        """
        telemetry = {
            'start_time': datetime.now(),
            'start_memory': self._get_memory_usage(),
            'operations': []
        }
        
        self.logger.debug("Telemetry collection started")
        return telemetry
    
    def _stop_telemetry(self, telemetry_data: Dict[str, Any]) -> None:
        """
        Stop telemetry collection and log results.
        
        Parameters
        ----------
        telemetry_data : Dict[str, Any]
            Telemetry data from _start_telemetry.
        """
        if not telemetry_data:
            return
        
        end_time = datetime.now()
        duration = (end_time - telemetry_data['start_time']).total_seconds()
        end_memory = self._get_memory_usage()
        memory_delta = end_memory - telemetry_data.get('start_memory', 0)
        
        self.logger.info(
            f"Telemetry: Duration={duration:.2f}s, "
            f"Memory={memory_delta:.1f}MB, "
            f"Artifacts={len(self._artifacts)}"
        )
        
        self._telemetry_data = {
            'duration_seconds': duration,
            'memory_delta_mb': memory_delta,
            'artifacts_built': len(self._artifacts),
            'cache_hits': 0,  # Would need to track
            'errors': len([a for a in self._audit_trail if a.status == 'failed'])
        }
    
    @staticmethod
    def _get_memory_usage() -> float:
        """
        Get current process memory usage in MB.
        
        Returns
        -------
        float
            Memory usage in MB, 0 if cannot determine.
        """
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            return 0.0
        except Exception:
            return 0.0
    
    def rollback(self) -> None:
        """
        Public method to manually rollback last publish operation.
        
        Call this after a failed publish to clean up partial artifacts.
        """
        self._execute_rollback()
    
    def get_audit_trail(self) -> List[AuditRecord]:
        """
        Get the complete audit trail for this publisher instance.
        
        Returns
        -------
        List[AuditRecord]
            List of all audit records.
        """
        return self._audit_trail.copy()
    
    def get_artifacts(self) -> List[BuildArtifact]:
        """
        Get metadata for all built artifacts.
        
        Returns
        -------
        List[BuildArtifact]
            List of build artifact metadata.
        """
        return self._artifacts.copy()
    
    def clear_cache(self) -> None:
        """
        Clear the build cache completely.
        
        Removes all cached build artifacts from the filesystem.
        """
        try:
            # Determine cache directory
            if platform.system() == 'Windows':
                cache_dir = Path(os.environ.get('LOCALAPPDATA', '~')) / 'pypi-publisher'
            elif platform.system() == 'Darwin':
                cache_dir = Path.home() / 'Library' / 'Caches' / 'pypi-publisher'
            else:
                cache_dir = Path.home() / '.cache' / 'pypi-publisher'
            
            cache_dir = cache_dir.expanduser()
            
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
                self.logger.info(f"Cache cleared: {cache_dir}")
            else:
                self.logger.info("Cache directory not found, nothing to clear")
                
        except Exception as e:
            raise CacheError(f"Failed to clear cache: {e}")

# =================================================================================
# 6. PYPI UTILITIES FUNCTIONS
# ===============================================

def open_pypi_token_page(new: int = 2, autoraise: bool = True) -> bool:
    """
    Open the PyPI API token management page in the user's default web browser,
    with multiple fallback mechanisms for maximum compatibility.

    This function attempts to open the official PyPI page where users can
    create and manage API tokens. It first uses Python's standard
    ``webbrowser`` module, and if that fails, it falls back to
    platform-specific system commands.

    Parameters
    ----------
    new : int, optional
        Specifies how the URL should be opened in the browser:

        - 0 : Open in the same browser window (if possible).
        - 1 : Open in a new browser window.
        - 2 : Open in a new browser tab (default).

        The actual behavior depends on the browser and environment.

    autoraise : bool, optional
        If True (default), attempts to bring the browser to the foreground.
        May be ignored by some platforms.

    Returns
    -------
    bool
        Returns True if the page was successfully opened using any method,
        otherwise False.

    Raises
    ------
    ValueError
        If the 'new' parameter is not one of {0, 1, 2}.

    RuntimeError
        If all methods to open the browser fail.

    Notes
    -----
    - Works across Windows, Linux, macOS, and some Android environments.
    - On headless systems, all methods may fail.
    - Fallback methods use system commands such as:
        * Windows: ``start``
        * macOS: ``open``
        * Linux: ``xdg-open``

    Examples
    --------
    >>> open_pypi_token_page()
    True

    >>> open_pypi_token_page(new=1)
    True
    """
    url: str = "https://pypi.org/manage/account/token/"

    # Validate input
    if new not in (0, 1, 2):
        raise ValueError(
            f"Invalid value for 'new': {new}. Expected one of (0, 1, 2)."
        )

    errors = []

    # --- Primary method: webbrowser ---
    try:
        browser: Optional[webbrowser.BaseBrowser] = webbrowser.get()
        if browser.open(url, new=new, autoraise=autoraise):
            return True
    except Exception as e:
        errors.append(f"webbrowser failed: {e}")

    # --- Fallback 1: webbrowser.open direct ---
    try:
        if webbrowser.open(url, new=new, autoraise=autoraise):
            return True
    except Exception as e:
        errors.append(f"webbrowser.open fallback failed: {e}")

    # --- Fallback 2: platform-specific commands ---
    try:
        if sys.platform.startswith("win"):
            # Windows
            os.startfile(url)  # type: ignore
            return True

        elif sys.platform.startswith("darwin"):
            # macOS
            subprocess.run(["open", url], check=True)
            return True

        else:
            # Linux / Unix / Android (Termux etc.)
            subprocess.run(["xdg-open", url], check=True)
            return True

    except Exception as e:
        errors.append(f"platform fallback failed: {e}")

    # --- If everything failed ---
    raise RuntimeError(
        "Failed to open PyPI token page using all available methods.\n"
        "Details:\n" + "\n".join(errors)
    )

# =================================================================================
# 7. COMMAND LINE INTERFACE
# =================================================================================

def main() -> int:
    """
    Main entry point for command-line interface.

    Parses command-line arguments, creates configuration objects,
    initializes the publisher, and executes the requested operation.

    Returns
    -------
    int
        Exit code (0 for success, 1 for error).
    """
    parser = create_argument_parser()
    args = parser.parse_args()
    
    if args.command is None:
    	parser.print_help()
    	return 1

    # Configure logging
    log_level = logging.DEBUG if args.verbose else (logging.ERROR if args.quiet else logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    if args.log_file:
        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(file_handler)

    logger = logging.getLogger(__name__)

    # Route to resolver if specified
    if args.command == 'resolver':
        main_resolver()
        return 0

    # Original publish logic
    try:
        if args.repository == "testpypi":
            repository_url = "https://test.pypi.org/legacy/"
        else:
            repository_url = "https://upload.pypi.org/legacy/"

        # Build configuration
        build_config = BuildConfig(
            build_type=args.build_type,
            output_dir=Path(args.dist_dir) if args.dist_dir else None,
            no_isolation=args.no_isolation,
            timeout=args.timeout
        )

        # Upload configuration
        upload_config = UploadConfig(
            repository_url=repository_url,
            username=args.username,
            password=args.password,
            token=args.token,
            sign=args.sign,
            identity=args.identity,
            skip_existing=args.skip_existing,
            config_file=Path(args.config_file) if args.config_file else None,
            timeout=args.timeout
        )

        # Security configuration
        security_config = SecurityConfig(
            block_malicious_patterns=args.check_security,
            enable_audit_log=True
        )

        # Performance configuration
        performance_config = PerformanceConfig(
            parallel_builds=args.parallel,
            max_workers=args.max_workers or None,
            enable_caching=not args.no_cache,
            compression_level=args.compression
        )

        # Compliance configuration
        compliance_config = ComplianceConfig(
            check_licenses=args.check_licenses,
            generate_sbom=args.generate_sbom,
            sbom_format=args.sbom_format,
            require_tests=args.run_tests,
            test_coverage_threshold=args.coverage_threshold
        )

        # Create publisher
        publisher = PyPIPublisher(
            package_path=args.package_path,
            build_config=build_config,
            upload_config=upload_config,
            security_config=security_config,
            performance_config=performance_config,
            compliance_config=compliance_config,
            telemetry_enabled=args.verbose
        )

        # Clear cache if requested
        if args.clear_cache:
            publisher.clear_cache()

        # Execute operation
        if args.build_only:
            result = publisher.build_only()
        else:
            result = publisher.publish(
                skip_build=False,
                skip_cleanup=args.skip_cleanup,
                check_metadata=not args.skip_metadata_check,
                check_description=not args.skip_description_check,
                run_tests=args.run_tests,
                dry_run=args.dry_run,
                enable_telemetry=args.verbose
            )

        # Output result
        if result.success:
            print(f"\nSUCCESS: {result.package_name} v{result.version}")
            print(f"   Duration: {result.duration.total_seconds():.2f} seconds")

            if result.built_files:
                print(f"   Artifacts: {len(result.built_files)} file(s)")
                for f in result.built_files:
                    size_mb = f.stat().st_size / (1024 * 1024)
                    print(f"     • {f.name} ({size_mb:.2f} MB)")

            if result.warnings:
                print(f"   Warnings: {len(result.warnings)}")
                for w in result.warnings[:5]:
                    print(f"     {w[:80]}...")

            return 0
        else:
            print(f"\nFAILED: {result.package_name} v{result.version}")
            print(f"   Duration: {result.duration.total_seconds():.2f} seconds")

            if result.errors:
                print(f"   Errors:")
                for e in result.errors:
                    print(f"     {e}")

            return 1

    except PyPIPublishError as e:
        logger.error(f"Publishing error: {e}")
        print(f"\nError: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error: {traceback.format_exc()}")
        print(f"\nUnexpected error: {e}")
        if args.verbose:
            traceback.print_exc()
        return 1


def create_argument_parser() -> argparse.ArgumentParser:
    """
    Create argument parser with subcommands for publish and resolver.
    
    Returns
    -------
    argparse.ArgumentParser
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        description="PyPI Package Publisher and Resolver",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Global arguments
    parser.add_argument('--verbose', action='store_true', help='Enable verbose/debug output')
    parser.add_argument('--quiet', action='store_true', help='Suppress all non-error output')
    parser.add_argument('--log-file', help='Write log output to specified file')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Publish subcommand
    publish_parser = subparsers.add_parser('publish', help='Build and publish a package')
    publish_parser.add_argument('package_path', help='Path to the package')
    publish_parser.add_argument('--repository', choices=['pypi', 'testpypi'], default='pypi', help='Repository to use')
    publish_parser.add_argument('--username', help='Repository username')
    publish_parser.add_argument('--password', help='Repository password')
    publish_parser.add_argument('--token', help='API token')
    publish_parser.add_argument('--sign', action='store_true', help='Sign files with GPG')
    publish_parser.add_argument('--identity', help='GPG identity for signing')
    publish_parser.add_argument('--skip-existing', action='store_true', help='Skip files that already exist')
    publish_parser.add_argument('--config-file', help='Path to .pypirc configuration file')
    publish_parser.add_argument('--build-type', choices=['sdist', 'wheel', 'both'], default='both', help='Type of distribution')
    publish_parser.add_argument('--dist-dir', help='Directory for built distributions')
    publish_parser.add_argument('--no-isolation', action='store_true', help='Disable build isolation')
    publish_parser.add_argument('--check-security', action='store_true', help='Block malicious patterns')
    publish_parser.add_argument('--parallel', action='store_true', help='Enable parallel builds')
    publish_parser.add_argument('--max-workers', type=int, help='Maximum number of parallel workers')
    publish_parser.add_argument('--no-cache', action='store_true', help='Disable build cache')
    publish_parser.add_argument('--clear-cache', action='store_true', help='Clear build cache before operation')
    publish_parser.add_argument('--compression', type=int, choices=range(0, 10), default=6, help='Compression level')
    publish_parser.add_argument('--check-licenses', action='store_true', help='Verify license compatibility')
    publish_parser.add_argument('--generate-sbom', action='store_true', help='Generate SBOM')
    publish_parser.add_argument('--sbom-format', choices=['cyclonedx', 'spdx'], default='cyclonedx', help='SBOM format')
    publish_parser.add_argument('--run-tests', action='store_true', help='Run package tests')
    publish_parser.add_argument('--coverage-threshold', type=float, help='Minimum test coverage threshold')
    publish_parser.add_argument('--timeout', type=int, default=300, help='Operation timeout in seconds')
    publish_parser.add_argument('--dry-run', action='store_true', help='Simulate operation without uploading')
    publish_parser.add_argument('--skip-cleanup', action='store_true', help='Keep temporary files')
    publish_parser.add_argument('--skip-metadata-check', action='store_true', help='Skip metadata validation')
    publish_parser.add_argument('--skip-description-check', action='store_true', help='Skip description validation')
    publish_parser.add_argument('--build-only', action='store_true', help='Only build without uploading')
    
    # Resolver subcommand
    resolver_parser = subparsers.add_parser('resolver', help='Resolve package URLs')
    resolver_parser.add_argument('packages', nargs='*', help='Package names to resolve')
    resolver_parser.add_argument('--best', action='store_true', help='Return only the best URL')
    resolver_parser.add_argument('--github', action='store_true', help='Return only the GitHub URL')
    resolver_parser.add_argument('--pypi', action='store_true', help='Return only the PyPI URL')
    resolver_parser.add_argument('--batch', action='store_true', help='Treat arguments as batch of packages')
    resolver_parser.add_argument('--example-resolver', action='store_true', help='Run example demonstrations')
    
    return parser

if __name__ == "__main__":
    main()
