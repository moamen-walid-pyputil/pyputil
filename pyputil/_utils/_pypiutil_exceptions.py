#!/usr/bin/env python3

# -*- coding: utf-8 -*-

# =================================================================================
# 4. CUSTOM EXCEPTIONS
# =================================================================================

class PyPIPublishError(Exception):
    """
    Base exception for all PyPI publishing errors.
    
    All other exceptions in the module inherit from this class,
    allowing callers to catch any publishing-related error.
    
    Examples
    --------
    >>> try:
    ...     publisher.publish()
    ... except PyPIPublishError as e:
    ...     print(f"Publishing failed: {e}")
    """
    pass


class BuildError(PyPIPublishError):
    """
    Exception raised when package building fails.
    
    Indicates problems with the build process such as:
    - Missing build dependencies
    - Syntax errors in setup files
    - Build command failures
    - Timeout during build
    """
    pass


class ValidationError(PyPIPublishError):
    """
    Exception raised when package validation fails.
    
    Indicates issues with package structure or metadata:
    - Missing required files (setup.py, README, LICENSE)
    - Invalid version format
    - Malformed package name
    - Missing author information
    """
    pass


class AuthenticationError(PyPIPublishError):
    """
    Exception raised when authentication fails.
    
    Indicates problems with repository credentials:
    - Invalid API token
    - Wrong username/password
    - Expired credentials
    - Insufficient permissions
    """
    pass


class UploadError(PyPIPublishError):
    """
    Exception raised when upload to repository fails.
    
    Indicates upload-specific issues:
    - Network connectivity problems
    - Repository server errors (5xx)
    - File already exists (409 conflict)
    - File size exceeds limits
    """
    pass


class DependencyError(PyPIPublishError):
    """
    Exception raised when required dependencies are missing.
    
    Indicates missing build or runtime dependencies:
    - 'build' package not installed
    - 'twine' package not installed
    - Required build backend missing
    """
    pass


class ConfigurationError(PyPIPublishError):
    """
    Exception raised when configuration is invalid.
    
    Indicates configuration problems:
    - Conflicting settings
    - Invalid repository URL
    - Missing required config values
    """
    pass


class TestFailureError(PyPIPublishError):
    """
    Exception raised when package tests fail.
    
    Indicates test execution failures:
    - Unit tests failing
    - Test command errors
    - Coverage below threshold
    """
    pass


class SecurityError(PyPIPublishError):
    """
    Exception raised for security policy violations.
    
    Indicates security validation failures:
    - Malicious code patterns detected
    - Hardcoded secrets found
    - Unsafe imports detected
    - Signature verification failed
    """
    pass


class ComplianceError(PyPIPublishError):
    """
    Exception raised for compliance violations.
    
    Indicates compliance check failures:
    - Unlicensed dependencies
    - Disallowed license types
    - Missing changelog
    - Author validation failed
    """
    pass


class CacheError(PyPIPublishError):
    """
    Exception raised for caching system errors.
    
    Indicates cache operation failures:
    - Corrupted cache
    - Permission denied for cache directory
    - Cache serialization errors
    """
    pass