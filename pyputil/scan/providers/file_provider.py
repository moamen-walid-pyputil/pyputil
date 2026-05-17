#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
File-based module discovery provider.

This module implements a provider that discovers Python modules
by scanning the file system.
"""

import time
import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional
import hashlib

from .base import BaseProvider
from ..core.enums import ModuleType, SearchMethod
from ..core.models import ModuleMeta
from ..core.config import ScanConfig
from ..core.exceptions import SearchTimeoutError, AnalysisError
from ..analyzers.dependency_analyzer import DependencyAnalyzer
from ..analyzers.docstring_analyzer import DocstringAnalyzer
from ..utils.file_utils import FileUtils
from ..utils.path_utils import PathUtils


class FileProvider(BaseProvider):
    """
    File-based module discovery provider.

    This provider performs comprehensive file system scanning to discover
    Python modules and packages. It supports multiple search methods
    including exact matching, pattern matching, and prefix-based searches.

    Attributes
    ----------
    paths : List[Path]
        File paths to search for modules
    stats : Dict[str, Any]
        Statistics about search operations and performance
    dependency_analyzer : DependencyAnalyzer
        Analyzer for extracting module dependencies
    docstring_analyzer : DocstringAnalyzer
        Analyzer for detecting module docstrings
    """

    def __init__(self, paths: List[Path]):
        """
        Initialize file search provider with search paths.

        Parameters
        ----------
        paths : List[Path]
            File system directories to include in search operations

        Raises
        ------
        InvalidPathError
            If any of the provided paths are invalid
        """
        super().__init__()
        self.paths = [PathUtils.validate_path(p) for p in paths]
        self.dependency_analyzer = DependencyAnalyzer()
        self.docstring_analyzer = DocstringAnalyzer()

    def _classify_module_type(self, path: Path, is_pkg: bool) -> ModuleType:
        """
        Classify module type based on file characteristics.

        Parameters
        ----------
        path : Path
            File path to module file or directory
        is_pkg : bool
            Whether the path represents a package

        Returns
        -------
        ModuleType
            Classified module type based on file extension and structure

        Notes
        -----
        Classification rules:
        - Directories with __init__.py -> PACKAGE
        - Directories without __init__.py -> NAMESPACE_PACKAGE
        - .py files -> MODULE
        - .so, .pyd, .dll -> C_EXTENSION
        """
        if not is_pkg:
            if path.suffix in (".so", ".pyd", ".dll"):
                return ModuleType.C_EXTENSION
            return ModuleType.MODULE
        else:
            init_file = path / "__init__.py"
            if init_file.exists():
                return ModuleType.PACKAGE
            else:
                return ModuleType.NAMESPACE_PACKAGE

    def _compute_file_hash(self, path: Path) -> Optional[str]:
        """
        Compute SHA-256 hash of file content.

        Parameters
        ----------
        path : Path
            Path to file to hash

        Returns
        -------
        Optional[str]
            Hex digest of SHA-256 hash, or None if file can't be read
        """
        try:
            content = path.read_bytes()
            return hashlib.sha256(content).hexdigest()
        except (IOError, OSError):
            return None

    def _extract_meta(
        self, name: str, path: Path, depth: int, config: ScanConfig
    ) -> ModuleMeta:
        """
        Extract comprehensive metadata from file path.

        Parameters
        ----------
        name : str
            Module name
        path : Path
            File path to module
        depth : int
            Depth in module namespace hierarchy
        config : ScanConfig
            Scan configuration for metadata extraction

        Returns
        -------
        ModuleMeta
            Fully populated module metadata object

        Raises
        ------
        AnalysisError
            If metadata extraction fails for analysis operations
        """
        is_pkg = path.is_dir()
        init_file = path / "__init__.py" if is_pkg else None

        # Determine file statistics
        try:
            stat_info = path.stat()
            file_size = stat_info.st_size if path.is_file() else None
            modified_time = stat_info.st_mtime
            created_time = stat_info.st_ctime
        except (OSError, ValueError):
            file_size = None
            modified_time = None
            created_time = None

        # Classify module type
        module_type = self._classify_module_type(path, is_pkg)

        # Extract dependencies if configured
        dependencies = []
        source_file = path if path.is_file() else init_file
        if config.analyze_dependencies and source_file and source_file.exists():
            try:
                dependencies = self.dependency_analyzer.analyze(source_file)
            except AnalysisError:
                # Continue without dependencies if analysis fails
                pass

        # Check for docstring
        has_docstring = False
        if source_file and source_file.exists():
            try:
                has_docstring = self.docstring_analyzer.has_docstring(source_file)
            except AnalysisError:
                pass

        # Compute file hash
        file_hash = None
        if source_file and source_file.exists() and source_file.is_file():
            file_hash = self._compute_file_hash(source_file)

        # Count lines
        line_count = None
        if source_file and source_file.exists() and source_file.is_file():
            try:
                line_count = FileUtils.count_lines(source_file)
            except (IOError, OSError):
                pass

        return ModuleMeta(
            name=name,
            path=str(path),
            is_package=is_pkg,
            module_type=module_type,
            file_size=file_size,
            encoding="utf-8",
            init_exists=init_file.exists() if init_file else False,
            modified_time=modified_time,
            created_time=created_time,
            depth=depth,
            loader="file",
            has_docstring=has_docstring,
            source_available=True,
            dependencies=dependencies,
            hash=file_hash,
            line_count=line_count,
        )

    def _should_exclude(self, path: Path, config: ScanConfig) -> bool:
        """
        Check if a path should be excluded from search.

        Parameters
        ----------
        path : Path
            Path to check
        config : ScanConfig
            Scan configuration with exclusion patterns

        Returns
        -------
        bool
            True if path should be excluded
        """
        # Check exclude patterns
        for pattern in config.exclude_patterns:
            if fnmatch.fnmatch(path.name, pattern):
                return True

        # Check exclude paths
        for exclude_path in config.exclude_paths:
            if path.is_relative_to(exclude_path):
                return True

        # Check hidden files
        if not config.include_hidden and path.name.startswith("."):
            return True

        return False

    def _search_exact(self, module: str, config: ScanConfig) -> List[ModuleMeta]:
        """
        Perform exact match search for module name.

        Parameters
        ----------
        module : str
            Exact module name to search for
        config : ScanConfig
            Scan configuration options

        Returns
        -------
        List[ModuleMeta]
            List of exactly matching modules
        """
        results = []
        parts = module.split(".")

        for base_path in self.paths:
            target_path = base_path.joinpath(*parts)

            # Check for exact file or directory match
            if target_path.exists() and not self._should_exclude(target_path, config):
                results.append(
                    self._extract_meta(module, target_path, len(parts), config)
                )

            # Also check for .py file if not found as directory
            if parts:
                py_file = base_path.joinpath(*parts[:-1], f"{parts[-1]}.py")
                if py_file.exists() and not self._should_exclude(py_file, config):
                    results.append(
                        self._extract_meta(module, py_file, len(parts), config)
                    )

        return results

    def _search_pattern(self, module: str, config: ScanConfig) -> List[ModuleMeta]:
        """
        Perform pattern-based search using glob matching.

        Parameters
        ----------
        module : str
            Glob pattern to match against module names
        config : ScanConfig
            Scan configuration options

        Returns
        -------
        List[ModuleMeta]
            List of modules matching the pattern
        """
        results = []

        for base_path in self.paths:
            if not base_path.exists():
                continue

            # Use rglob for recursive search
            search_pattern = f"**/*"
            for item in base_path.glob(search_pattern):
                if self._should_exclude(item, config):
                    continue

                # Skip if depth limit exceeded
                rel_path = item.relative_to(base_path)
                if config.max_depth > 0 and len(rel_path.parts) > config.max_depth:
                    continue

                # Match Python files
                if item.is_file() and item.suffix == ".py":
                    if fnmatch.fnmatch(item.stem, module):
                        depth = len(rel_path.parts)
                        module_name = ".".join(rel_path.parts[:-1] + (item.stem,))
                        results.append(
                            self._extract_meta(module_name, item, depth, config)
                        )

                # Match package directories
                elif item.is_dir():
                    if fnmatch.fnmatch(item.name, module):
                        depth = len(rel_path.parts)
                        module_name = ".".join(rel_path.parts)
                        results.append(
                            self._extract_meta(module_name, item, depth, config)
                        )

        return results

    def _search_prefix(self, module: str, config: ScanConfig) -> List[ModuleMeta]:
        """
        Perform prefix-based search for modules starting with given string.

        Parameters
        ----------
        module : str
            Prefix string to match against module names
        config : ScanConfig
            Scan configuration options

        Returns
        -------
        List[ModuleMeta]
            List of modules with names starting with the prefix
        """
        results = []

        for base_path in self.paths:
            if not base_path.exists():
                continue

            # Search for matching Python files
            for py_file in base_path.rglob("*.py"):
                if self._should_exclude(py_file, config):
                    continue

                rel_path = py_file.relative_to(base_path)

                # Check depth limit
                if config.max_depth > 0 and len(rel_path.parts) > config.max_depth:
                    continue

                if py_file.stem.startswith(module):
                    depth = len(rel_path.parts)
                    module_name = ".".join(rel_path.parts[:-1] + (py_file.stem,))
                    results.append(
                        self._extract_meta(module_name, py_file, depth, config)
                    )

            # Search for matching package directories
            for directory in base_path.rglob("*"):
                if not directory.is_dir():
                    continue

                if self._should_exclude(directory, config):
                    continue

                rel_path = directory.relative_to(base_path)

                # Check depth limit
                if config.max_depth > 0 and len(rel_path.parts) > config.max_depth:
                    continue

                if directory.name.startswith(module):
                    depth = len(rel_path.parts)
                    module_name = ".".join(rel_path.parts)
                    results.append(
                        self._extract_meta(module_name, directory, depth, config)
                    )

        return results

    def search(self, module: str, config: ScanConfig) -> List[ModuleMeta]:
        """
        Perform module search using configured search method.

        Parameters
        ----------
        module : str
            Module name, pattern, or prefix to search for
        config : ScanConfig
            Configuration controlling search behavior

        Returns
        -------
        List[ModuleMeta]
            List of discovered modules with metadata

        Raises
        ------
        SearchTimeoutError
            If search exceeds configured timeout
        """
        start_time = time.time()

        # Check timeout if configured
        if config.timeout:
            timeout_time = start_time + config.timeout

        try:
            if config.search_method == SearchMethod.EXACT:
                results = self._search_exact(module, config)
            elif config.search_method == SearchMethod.PATTERN:
                results = self._search_pattern(module, config)
            elif config.search_method == SearchMethod.PREFIX:
                results = self._search_prefix(module, config)
            elif config.search_method == SearchMethod.ALL:
                results = []
                results.extend(self._search_exact(module, config))
                results.extend(self._search_pattern(module, config))
                results.extend(self._search_prefix(module, config))
                # Remove duplicates based on path
                seen = set()
                unique_results = []
                for r in results:
                    if r.path not in seen:
                        seen.add(r.path)
                        unique_results.append(r)
                results = unique_results
            else:
                results = []

            # Check timeout
            if config.timeout and time.time() > timeout_time:
                raise SearchTimeoutError(config.timeout, module)

            # Update statistics
            scan_time = time.time() - start_time
            self._update_stats(len(results), scan_time)

            return results

        except Exception as e:
            # Update statistics even on error
            scan_time = time.time() - start_time
            self._update_stats(0, scan_time)
            raise

    def supports_method(self, method: SearchMethod) -> bool:
        """
        Check support for specific search methods.

        Parameters
        ----------
        method : SearchMethod
            Search method to check

        Returns
        -------
        bool
            Always True as file provider supports all methods
        """
        return True