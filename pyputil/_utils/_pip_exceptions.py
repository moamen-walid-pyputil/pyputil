#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from typing import Optional, Dict, Any

class PipError(Exception):
    """
    Base exception class for all pip-manager errors.
    
    This is the parent class for all custom exceptions in the pip-manager
    module. It provides common functionality for error handling and reporting.

    Parameters
    ----------
    message : str
        Human-readable error description
    original_error : Exception, optional
        The original exception that triggered this error
    context : dict, optional
        Additional contextual information about the error

    Attributes
    ----------
    message : str
        Error message
    original_error : Exception or None
        Original exception if provided
    context : dict
        Error context information
    timestamp : datetime
        Time when the error occurred

    Examples
    --------
    >>> try:
    ...     raise PipError("Something went wrong")
    ... except PipError as e:
    ...     print(f"Error: {e.message}")
    Error: Something went wrong
    
    >>> try:
    ...     raise PipError(
    ...         "Download failed",
    ...         original_error=ConnectionError("Timeout"),
    ...         context={"url": "https://example.com", "attempt": 3}
    ...     )
    ... except PipError as e:
    ...     print(f"Original: {e.original_error}")
    Original: ConnectionError: Timeout
    """
    
    def __init__(
        self,
        message: str,
        original_error: Optional[Exception] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.original_error = original_error
        self.context = context or {}
        self.timestamp = datetime.now()
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        """
        Format the error message with timestamp and context.
        
        Returns
        -------
        str
            Formatted error message string
        """
        msg = f"[{self.timestamp.isoformat()}] {self.message}"
        if self.original_error:
            msg += f"\n  Original: {type(self.original_error).__name__}: {self.original_error}"
        if self.context:
            msg += f"\n  Context: {json.dumps(self.context, indent=2, default=str)}"
        return msg
    
    def __str__(self) -> str:
        """Return string representation of the error."""
        return self._format_message()


class DownloadError(PipError):
    """
    Exception raised when download operations fail.
    
    This exception is raised specifically for download-related failures,
    including network issues, hash verification failures, or invalid URLs.

    Parameters
    ----------
    message : str
        Error description
    url : str, optional
        The URL that failed to download
    attempts : int, optional
        Number of download attempts made
    original_error : Exception, optional
        Original exception
    context : dict, optional
        Additional context

    Examples
    --------
    >>> raise DownloadError(
    ...     "Failed to download bootstrap script",
    ...     url="https://bootstrap.pypa.io/get-pip.py",
    ...     attempts=3
    ... )
    """
    
    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        attempts: Optional[int] = None,
        original_error: Optional[Exception] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        context = context or {}
        if url:
            context["url"] = url
        if attempts:
            context["attempts"] = attempts
        super().__init__(message, original_error, context)


class InstallationError(PipError):
    """
    Exception raised when pip installation fails.
    
    This exception covers failures during the pip installation process,
    including command execution failures, permission issues, or invalid
    installation parameters.

    Parameters
    ----------
    message : str
        Error description
    pip_version : str, optional
        The pip version being installed
    return_code : int, optional
        Exit code from the installation process
    original_error : Exception, optional
        Original exception
    context : dict, optional
        Additional context

    Examples
    --------
    >>> raise InstallationError(
    ...     "Installation failed with exit code 1",
    ...     pip_version="24.0",
    ...     return_code=1
    ... )
    """
    
    def __init__(
        self,
        message: str,
        pip_version: Optional[str] = None,
        return_code: Optional[int] = None,
        original_error: Optional[Exception] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        context = context or {}
        if pip_version:
            context["pip_version"] = pip_version
        if return_code:
            context["return_code"] = return_code
        super().__init__(message, original_error, context)


class ValidationError(PipError):
    """
    Exception raised when validation checks fail.
    
    This exception is used for validation failures including hash mismatches,
    SSL certificate issues, or invalid input parameters.

    Parameters
    ----------
    message : str
        Error description
    validation_type : str, optional
        Type of validation that failed (e.g., 'hash', 'ssl', 'input')
    expected : Any, optional
        Expected value
    actual : Any, optional
        Actual value found
    original_error : Exception, optional
        Original exception
    context : dict, optional
        Additional context

    Examples
    --------
    >>> raise ValidationError(
    ...     "SHA256 hash mismatch",
    ...     validation_type="hash",
    ...     expected="abc123...",
    ...     actual="def456..."
    ... )
    """
    
    def __init__(
        self,
        message: str,
        validation_type: Optional[str] = None,
        expected: Optional[Any] = None,
        actual: Optional[Any] = None,
        original_error: Optional[Exception] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        context = context or {}
        if validation_type:
            context["validation_type"] = validation_type
        if expected is not None:
            context["expected"] = str(expected)
        if actual is not None:
            context["actual"] = str(actual)
        super().__init__(message, original_error, context)
