#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Custom exceptions for the module scanner.

This module defines exception classes for various error conditions
that can occur during module scanning operations.
"""


class ScannerError(Exception):
    """Base exception class for all scanner-related errors."""

    def __init__(self, message: str, details: dict = None):
        """
        Initialize scanner error.

        Parameters
        ----------
        message : str
            Error message describing the failure
        details : dict, optional
            Additional error context details
        """
        super().__init__(message)
        self.details = details or {}


class SearchTimeoutError(ScannerError):
    """Raised when a search operation exceeds the configured timeout."""

    def __init__(self, timeout: float, query: str):
        """
        Initialize timeout error.

        Parameters
        ----------
        timeout : float
            Timeout value in seconds that was exceeded
        query : str
            Search query that caused the timeout
        """
        super().__init__(
            f"Search for '{query}' exceeded timeout of {timeout} seconds",
            {"timeout": timeout, "query": query},
        )


class InvalidSearchMethodError(ScannerError):
    """Raised when an unsupported search method is requested."""

    def __init__(self, method: str, provider: str):
        """
        Initialize invalid search method error.

        Parameters
        ----------
        method : str
            The requested search method
        provider : str
            The provider that doesn't support the method
        """
        super().__init__(
            f"Provider '{provider}' does not support search method '{method}'",
            {"method": method, "provider": provider},
        )


class ModuleNotFoundError(ScannerError):
    """Raised when a specific module cannot be found."""

    def __init__(self, module_name: str):
        """
        Initialize module not found error.

        Parameters
        ----------
        module_name : str
            Name of the module that could not be found
        """
        super().__init__(
            f"Module '{module_name}' not found in search paths",
            {"module_name": module_name},
        )


class InvalidPathError(ScannerError):
    """Raised when an invalid search path is provided."""

    def __init__(self, path: str, reason: str):
        """
        Initialize invalid path error.

        Parameters
        ----------
        path : str
            The invalid path
        reason : str
            Reason why the path is invalid
        """
        super().__init__(
            f"Invalid path '{path}': {reason}",
            {"path": path, "reason": reason},
        )


class AnalysisError(ScannerError):
    """Raised when module analysis fails."""

    def __init__(self, module_name: str, analysis_type: str, reason: str):
        """
        Initialize analysis error.

        Parameters
        ----------
        module_name : str
            Name of the module being analyzed
        analysis_type : str
            Type of analysis that failed
        reason : str
            Reason for the failure
        """
        super().__init__(
            f"Failed to perform {analysis_type} analysis on '{module_name}': {reason}",
            {"module_name": module_name, "analysis_type": analysis_type, "reason": reason},
        )