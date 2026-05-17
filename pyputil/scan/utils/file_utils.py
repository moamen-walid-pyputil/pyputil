#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
File utility functions for module scanning.

This module provides helper functions for file operations including
reading, writing, and analyzing file properties.
"""

from pathlib import Path
from typing import Optional, List
import hashlib


class FileUtils:
    """
    Utility class for file operations in module scanning.

    Provides static methods for common file operations needed during
    module discovery and analysis.
    """

    @staticmethod
    def count_lines(file_path: Path, encoding: str = 'utf-8') -> Optional[int]:
        """
        Count number of lines in a text file.

        Parameters
        ----------
        file_path : Path
            Path to the file
        encoding : str
            File encoding to use

        Returns
        -------
        Optional[int]
            Number of lines, or None if file cannot be read
        """
        try:
            with file_path.open('r', encoding=encoding) as f:
                return sum(1 for _ in f)
        except (IOError, OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def compute_hash(file_path: Path, algorithm: str = 'sha256') -> Optional[str]:
        """
        Compute hash of file content.

        Parameters
        ----------
        file_path : Path
            Path to the file
        algorithm : str
            Hash algorithm to use (md5, sha1, sha256, etc.)

        Returns
        -------
        Optional[str]
            Hexadecimal hash digest, or None if file cannot be read
        """
        try:
            hasher = hashlib.new(algorithm)
            with file_path.open('rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (IOError, OSError, ValueError):
            return None

    @staticmethod
    def is_python_file(file_path: Path) -> bool:
        """
        Check if file is a Python source file.

        Parameters
        ----------
        file_path : Path
            Path to check

        Returns
        -------
        bool
            True if file has .py extension and is a file
        """
        return file_path.is_file() and file_path.suffix == '.py'

    @staticmethod
    def is_package_directory(dir_path: Path) -> bool:
        """
        Check if directory is a Python package.

        Parameters
        ----------
        dir_path : Path
            Directory to check

        Returns
        -------
        bool
            True if directory contains __init__.py
        """
        return dir_path.is_dir() and (dir_path / '__init__.py').exists()

    @staticmethod
    def get_file_extension(file_path: Path) -> str:
        """
        Get file extension with dot.

        Parameters
        ----------
        file_path : Path
            Path to file

        Returns
        -------
        str
            File extension including dot (e.g., '.py')
        """
        return file_path.suffix.lower()

    @staticmethod
    def is_hidden(path: Path) -> bool:
        """
        Check if path is hidden (Unix hidden or Windows hidden).

        Parameters
        ----------
        path : Path
            Path to check

        Returns
        -------
        bool
            True if path is hidden
        """
        return path.name.startswith('.')

    @staticmethod
    def get_size_mb(file_path: Path) -> Optional[float]:
        """
        Get file size in megabytes.

        Parameters
        ----------
        file_path : Path
            Path to file

        Returns
        -------
        Optional[float]
            File size in MB, or None if file doesn't exist
        """
        try:
            size_bytes = file_path.stat().st_size
            return size_bytes / (1024 * 1024)
        except (IOError, OSError):
            return None