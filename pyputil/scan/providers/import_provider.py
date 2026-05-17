#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Import-based module discovery provider.

This module implements a provider that discovers modules using Python's
import machinery, including built-in modules, frozen modules, and
installed packages.
"""

import time
from pathlib import Path
from typing import List, Dict, Any, Optional
import importlib.util

from .base import BaseProvider
from ..core.enums import ModuleType, SearchMethod
from ..core.models import ModuleMeta
from ..core.config import ScanConfig
from ..core.exceptions import AnalysisError
from ..analyzers.dependency_analyzer import DependencyAnalyzer


class ImportProvider(BaseProvider):
    """
    Import system-based module discovery provider.

    This provider leverages Python's importlib to discover modules
    available through the standard import system, including built-in
    modules, frozen modules, and installed packages.

    Attributes
    ----------
    stats : Dict[str, Any]
        Statistics about import system search operations
    dependency_analyzer : DependencyAnalyzer
        Analyzer for extracting module dependencies
    """

    def __init__(self):
        """Initialize import system provider."""
        super().__init__()
        self.dependency_analyzer = DependencyAnalyzer()
        self.stats.update({
            "import_lookups": 0,
            "builtin_modules": 0,
            "failed_imports": 0,
            "total_lookup_time": 0.0,
        })

    def _get_module_type_from_spec(self, spec) -> ModuleType:
        """
        Determine module type from importlib module spec.

        Parameters
        ----------
        spec : ModuleSpec
            Module specification from importlib

        Returns
        -------
        ModuleType
            Classified module type based on spec attributes

        Notes
        -----
        Classification order matters:
        1. Check for built-in (origin is None)
        2. Check for packages (submodule_search_locations)
        3. Check for frozen modules
        4. Check for C extensions
        5. Default to regular module
        """
        if spec.origin is None:
            return ModuleType.BUILTIN

        if spec.submodule_search_locations is not None:
            return ModuleType.PACKAGE

        if "frozen" in str(spec.loader).lower():
            return ModuleType.FROZEN

        if spec.origin and spec.origin.endswith((".so", ".pyd", ".dll")):
            return ModuleType.C_EXTENSION

        # Check if it's a namespace package
        if spec.origin.endswith("__init__.py"):
            return ModuleType.PACKAGE

        return ModuleType.MODULE

    def _should_include(self, module_type: ModuleType, config: ScanConfig) -> bool:
        """
        Check if module type should be included based on configuration.

        Parameters
        ----------
        module_type : ModuleType
            Type of module to check
        config : ScanConfig
            Scan configuration with include flags

        Returns
        -------
        bool
            True if module type should be included
        """
        include_map = {
            ModuleType.BUILTIN: config.include_builtin,
            ModuleType.FROZEN: config.include_frozen,
            ModuleType.C_EXTENSION: config.include_c_extensions,
        }
        return include_map.get(module_type, True)

    def search(self, module: str, config: ScanConfig) -> List[ModuleMeta]:
        """
        Search for modules using Python's import system.

        Parameters
        ----------
        module : str
            Module name to search for
        config : ScanConfig
            Scan configuration options

        Returns
        -------
        List[ModuleMeta]
            List of discovered modules through import system

        Notes
        -----
        This method performs exact match searches only, as the import
        system doesn't support pattern or prefix matching directly.
        """
        start_time = time.time()
        results = []

        try:
            spec = importlib.util.find_spec(module)
            self.stats["import_lookups"] += 1

            if spec:
                module_type = self._get_module_type_from_spec(spec)

                # Apply filters based on configuration
                if not self._should_include(module_type, config):
                    return results

                # Determine file path
                path = None
                if spec.origin:
                    path = Path(spec.origin)
                elif spec.has_location:
                    path = Path(spec.origin) if spec.origin else None

                is_pkg = spec.submodule_search_locations is not None

                # Extract file statistics if available
                file_size = None
                modified_time = None
                created_time = None

                if path and path.exists():
                    try:
                        stat_info = path.stat()
                        file_size = stat_info.st_size
                        modified_time = stat_info.st_mtime
                        created_time = stat_info.st_ctime
                    except (OSError, ValueError):
                        pass

                # Check for __init__.py in packages
                init_exists = False
                if is_pkg and path:
                    init_exists = (
                        path.name == "__init__.py"
                        or (path.parent / "__init__.py").exists()
                    )

                # Extract dependencies if configured
                dependencies = []
                if config.analyze_dependencies and path and path.exists():
                    source_file = path if path.is_file() else path / "__init__.py"
                    if source_file.exists():
                        try:
                            dependencies = self.dependency_analyzer.analyze(source_file)
                        except AnalysisError:
                            pass

                meta = ModuleMeta(
                    name=module,
                    path=str(path) if path else None,
                    is_package=is_pkg,
                    module_type=module_type,
                    file_size=file_size,
                    encoding="utf-8",
                    init_exists=init_exists,
                    modified_time=modified_time,
                    created_time=created_time,
                    depth=len(module.split(".")),
                    loader="importlib",
                    has_docstring=False,  # Would require actual import to check
                    source_available=path is not None and path.exists(),
                    dependencies=dependencies,
                )

                results.append(meta)

                # Update provider-specific statistics
                if module_type == ModuleType.BUILTIN:
                    self.stats["builtin_modules"] += 1
                self.stats["modules_found"] += 1

        except Exception:
            self.stats["failed_imports"] += 1

        # Update timing statistics
        lookup_time = time.time() - start_time
        self.stats["total_lookup_time"] += lookup_time
        self._update_stats(len(results), lookup_time)

        return results

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
            True only for exact match searches (import system limitation)
        """
        return method == SearchMethod.EXACT