#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Path utility functions for module scanning.

This module provides helper functions for path manipulation and validation.
"""

from pathlib import Path
from typing import List, Optional, Union

from ..core.exceptions import InvalidPathError


class PathUtils:
    """
    Utility class for path operations in module scanning.

    Provides static methods for path validation, resolution, and manipulation.
    """

    @staticmethod
    def validate_path(path: Union[str, Path]) -> Path:
        """
        Validate and resolve a path.

        Parameters
        ----------
        path : Union[str, Path]
            Path to validate

        Returns
        -------
        Path
            Resolved absolute path

        Raises
        ------
        InvalidPathError
            If path is invalid or doesn't exist
        """
        try:
            path_obj = Path(path).resolve()

            if not path_obj.exists():
                raise InvalidPathError(str(path), "Path does not exist")

            return path_obj

        except (OSError, ValueError) as e:
            raise InvalidPathError(str(path), str(e))

    @staticmethod
    def get_module_name_from_path(path: Path, base_path: Path) -> str:
        """
        Convert file path to module name.

        Parameters
        ----------
        path : Path
            Path to module file or package
        base_path : Path
            Base search path to strip from module name

        Returns
        -------
        str
            Dot-separated module name

        Examples
        --------
        >>> base = Path('/project')
        >>> path = Path('/project/subpackage/module.py')
        >>> PathUtils.get_module_name_from_path(path, base)
        'subpackage.module'
        """
        try:
            rel_path = path.relative_to(base_path)
        except ValueError:
            # Path is not under base_path, use stem
            return path.stem

        parts = list(rel_path.parts)

        # Handle Python files
        if path.is_file() and path.suffix == '.py':
            parts[-1] = parts[-1].replace('.py', '')

        # Remove __init__ from package names
        if parts and parts[-1] == '__init__':
            parts.pop()

        return '.'.join(parts)

    @staticmethod
    def get_all_python_files(directory: Path, recursive: bool = True) -> List[Path]:
        """
        Get all Python files in a directory.

        Parameters
        ----------
        directory : Path
            Directory to search
        recursive : bool
            Whether to search recursively

        Returns
        -------
        List[Path]
            List of Python file paths
        """
        if not directory.is_dir():
            return []

        pattern = '**/*.py' if recursive else '*.py'
        return list(directory.glob(pattern))

    @staticmethod
    def get_parent_package(path: Path, base_path: Path) -> Optional[str]:
        """
        Get the parent package name for a module.

        Parameters
        ----------
        path : Path
            Path to module or package
        base_path : Path
            Base search path

        Returns
        -------
        Optional[str]
            Parent package name, or None if at top level
        """
        try:
            rel_path = path.relative_to(base_path)
            if len(rel_path.parts) <= 1:
                return None

            parent_parts = rel_path.parts[:-1]
            return '.'.join(parent_parts)

        except ValueError:
            return None

    @staticmethod
    def is_subpath(path: Path, parent: Path) -> bool:
        """
        Check if path is a subpath of parent.

        Parameters
        ----------
        path : Path
            Path to check
        parent : Path
            Potential parent path

        Returns
        -------
        bool
            True if path is under parent
        """
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def normalize_paths(paths: List[Path]) -> List[Path]:
        """
        Normalize a list of paths (remove duplicates, resolve).

        Parameters
        ----------
        paths : List[Path]
            List of paths to normalize

        Returns
        -------
        List[Path]
            Normalized unique paths
        """
        normalized = []
        seen = set()

        for path in paths:
            try:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    normalized.append(resolved)
            except (OSError, ValueError):
                continue

        return normalized