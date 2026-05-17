#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Validation utilities for metadata fields.

Functions
---------
validate_email(email: str) -> bool
    Validate email format.
validate_url(url: str) -> bool
    Validate URL format.
validate_version(version: str) -> bool
    Validate version format.
"""

import re
from urllib.parse import urlparse
from typing import Optional, Pattern, Set, Dict, List
import packaging.version


class MetadataValidator:
    """Validator for metadata fields with pre-compiled patterns."""

    # Pre-compiled regex patterns for performance
    _EMAIL_PATTERN: Pattern = re.compile(
        r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    )
    _VERSION_PATTERN: Pattern = re.compile(
        r"^(\d+\.\d+(?:\.\d+)*)(?:[\.\-\_a-zA-Z0-9]*)$"
    )
    _URL_SCHEMES: Set[str] = {"http", "https", "ftp", "ftps", "git", "ssh"}

    @staticmethod
    def validate_email(email: str) -> bool:
        """
        Validate email format.

        Parameters
        ----------
        email : str
            Email address to validate

        Returns
        -------
        bool
            True if email is valid, False otherwise

        Examples
        --------
        >>> MetadataValidator.validate_email("test@example.com")
        True
        >>> MetadataValidator.validate_email("invalid-email")
        False
        """
        if not email or not isinstance(email, str):
            return False
        return bool(MetadataValidator._EMAIL_PATTERN.match(email.strip()))

    @staticmethod
    def validate_url(url: str) -> bool:
        """
        Validate URL format.

        Parameters
        ----------
        url : str
            URL to validate

        Returns
        -------
        bool
            True if URL is valid, False otherwise

        Examples
        --------
        >>> MetadataValidator.validate_url("https://example.com")
        True
        >>> MetadataValidator.validate_url("invalid-url")
        False
        """
        if not url or not isinstance(url, str):
            return False

        try:
            parsed = urlparse(url.strip())
            if not parsed.scheme or not parsed.netloc:
                return False
            return parsed.scheme in MetadataValidator._URL_SCHEMES
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def validate_version(version: str) -> bool:
        """
        Validate version format.

        Parameters
        ----------
        version : str
            Version string to validate

        Returns
        -------
        bool
            True if version is valid, False otherwise

        Examples
        --------
        >>> MetadataValidator.validate_version("1.2.3")
        True
        >>> MetadataValidator.validate_version("1.2.3a1")
        True
        >>> MetadataValidator.validate_version("invalid")
        False
        """
        if not version or not isinstance(version, str):
            return False

        version = version.strip()

        # Try packaging.version first
        try:
            packaging.version.parse(version)
            return True
        except packaging.version.InvalidVersion:
            # Fall back to regex pattern
            return bool(MetadataValidator._VERSION_PATTERN.match(version))

    @staticmethod
    def validate_required_fields(fields: Dict[str, str]) -> List[str]:
        """
        Validate required metadata fields.

        Parameters
        ----------
        fields : Dict[str, str]
            Dictionary of field names to values

        Returns
        -------
        List[str]
            List of missing required field names

        Notes
        -----
        Required fields according to PyPI:
        - Name
        - Version
        - Summary
        """
        required = {"name", "version", "summary"}
        missing = []

        for field in required:
            value = fields.get(field, "")
            if not value or not value.strip():
                missing.append(field)

        return missing
