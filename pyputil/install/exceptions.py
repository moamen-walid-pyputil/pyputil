#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from typing import Optional


# Custom exception classes for error handling
class PackageInstallerError(Exception):
    """Base exception for all package installer errors."""
    pass


class PackageInstallerNotFound(PackageInstallerError):
    """Raised when pip executable is not found."""
    pass


class PackageInstallerTimeout(PackageInstallerError):
    """Raised when a pip command times out."""
    pass


class PackageInstallerExecutionError(PackageInstallerError):
    """Raised when pip returns a non-zero exit code."""
    pass


class AutoInstallError(Exception):
    """
    Exception raised for errors during auto-installation.
    
    Parameters
    ----------
    message : str
        Explanation of the error.
    package : str, optional
        Name of the package that caused the error.
    original_exception : Exception, optional
        Original exception that was caught.
    
    Attributes
    ----------
    package : str, optional
        Name of the package that caused the error.
    original_exception : Exception, optional
        Original exception that was caught.
    """
    def __init__(self, message: str, package: Optional[str] = None, 
                 original_exception: Optional[Exception] = None):
        super().__init__(message)
        self.package = package
        self.original_exception = original_exception