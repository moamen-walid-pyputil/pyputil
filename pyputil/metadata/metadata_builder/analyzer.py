#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Core module metadata Meta.

Provides functions to meta Python modules and extract comprehensive metadata.
"""

import inspect
import sys
import time
import warnings
from typing import List, Optional, Dict, Any, Tuple
from types import ModuleType
from datetime import datetime

from .types import (
    ModuleMetadata,
    IdentityInfo,
    LocationInfo,
    LoaderInfo,
    RuntimeInfo,
    StructureInfo,
    DocumentationInfo,
    VersionInfo,
    RiskInfo,
    PerformanceInfo,
    AnalysisLevel,
)
from .utils import (
    hash_string,
    safe_getattr,
    get_module_size,
    extract_examples_from_doc,
    is_private_attr,
    get_source_file,
    get_package_info,
    time_function,
)


class ModuleMeta:
    """metas Python modules and extracts comprehensive metadata.

    This class provides methods to meta Python modules and extract
    various types of metadata including identity, location, structure,
    documentation, and security information.

    Attributes
    ----------
    module : ModuleType
        Module being metad
    include_private : bool
        Whether to include private attributes
    level : AnalysisLevel
        Depth of meta to perform

    Examples
    --------
    >>> import os
    >>> Meta = ModuleMeta(os)
    >>> metadata = Meta.meta()
    >>> print(metadata['identity']['name'])
    'os'
    """

    SUSPICIOUS_ATTRIBUTES = {
        "exec",
        "eval",
        "compile",
        "__import__",
        "open",
        "system",
        "popen",
        "spawn",
        "kill",
        "rmdir",
        "remove",
        "unlink",
        "chmod",
        "chown",
    }

    def __init__(
        self,
        module: ModuleType,
        include_private: bool = False,
        level: AnalysisLevel = "standard",
    ):
        """
        Initialize module Meta.

        Parameters
        ----------
        module : ModuleType
            Module to meta
        include_private : bool, optional
            Include private attributes (default=False)
        level : AnalysisLevel, optional
            meta depth (default='standard')
            Options: 'basic', 'standard', 'detailed', 'full'

        Raises
        ------
        TypeError
            If module is not a ModuleType
        ValueError
            If level is invalid
        """
        if not isinstance(module, ModuleType):
            raise TypeError(f"Expected ModuleType, got {type(module).__name__}")

        if level not in ("basic", "standard", "detailed", "full"):
            raise ValueError(f"Invalid meta level: {level}")

        self.module = module
        self.include_private = include_private
        self.level = level
        self._meta_start = time.perf_counter()

    def meta(self) -> ModuleMetadata:
        """Perform comprehensive module meta.

        Returns
        -------
        ModuleMetadata
            Complete metadata dictionary

        Notes
        -----
        meta steps:
        1. Collect basic information
        2. meta structure
        3. Extract documentation
        4. Assess risks
        5. Measure performance

        The meta level controls which steps are performed.
        """
        meta_time_start = time.perf_counter()

        # Collect all metadata components
        identity = self._meta_identity()
        location = self._meta_location()
        loader = self._meta_loader()
        runtime = self._meta_runtime()
        structure = self._meta_structure()
        documentation = self._meta_documentation()
        versioning = self._meta_versioning()
        risk_flags = self._meta_risks()

        # Performance metrics
        meta_time_ms = (time.perf_counter() - meta_time_start) * 1000
        performance = self._meta_performance(meta_time_ms)

        metadata: ModuleMetadata = {
            "identity": identity,
            "location": location,
            "loader": loader,
            "runtime": runtime,
            "structure": structure,
            "documentation": documentation,
            "versioning": versioning,
            "risk_flags": risk_flags,
            "performance": performance,
            "meta_timestamp": datetime.now().isoformat(),
            "python_version": sys.version,
        }

        return metadata

    def _meta_identity(self) -> IdentityInfo:
        """meta module identity.

        Returns
        -------
        IdentityInfo
            Identity information dictionary
        """
        name = getattr(self.module, "__name__", "unknown")

        return {
            "name": name,
            "id": id(self.module),
            "name_hash": hash_string(name),
            "full_name": getattr(self.module, "__name__", None),
        }

    def _meta_location(self) -> LocationInfo:
        """meta module location.

        Returns
        -------
        LocationInfo
            Location information dictionary
        """
        file = get_source_file(self.module)
        spec = getattr(self.module, "__spec__", None)

        return {
            "file": file,
            "is_builtin": file is None,
            "origin": getattr(spec, "origin", None) if spec else None,
            "package": get_package_info(self.module),
            "has_location": file is not None,
        }

    def _meta_loader(self) -> LoaderInfo:
        """meta module loader.

        Returns
        -------
        LoaderInfo
            Loader information dictionary
        """
        spec = getattr(self.module, "__spec__", None)
        loader = getattr(spec, "loader", None) if spec else None

        loader_type = None
        loader_name = None
        reloadable = False

        if loader:
            loader_type = type(loader).__name__
            loader_name = getattr(loader, "__name__", None)
            reloadable = hasattr(loader, "load_module")

        return {
            "type": loader_type,
            "name": loader_name,
            "reloadable": reloadable,
        }

    def _meta_runtime(self) -> RuntimeInfo:
        """meta runtime information.

        Returns
        -------
        RuntimeInfo
            Runtime information dictionary
        """
        name = getattr(self.module, "__name__", "")

        # Try to get load time (approximate)
        load_time = None
        if name in sys.modules:
            # This is an approximation - actual load time isn't tracked
            load_time = time.time()

        return {
            "loaded": name in sys.modules,
            "ref_count": sys.getrefcount(self.module)
            - 1,  # Subtract 1 for getrefcount call
            "timestamp": time.time(),
            "load_time": load_time,
            "size_bytes": (
                get_module_size(self.module)
                if self.level in ("detailed", "full")
                else None
            ),
        }

    def _meta_structure(self) -> StructureInfo:
        """meta module structure.

        Returns
        -------
        StructureInfo
            Structure information dictionary
        """
        # Get all attributes
        all_attrs = dir(self.module)

        # Filter private attributes
        if not self.include_private:
            attrs = [a for a in all_attrs if not is_private_attr(a)]
            private_count = len([a for a in all_attrs if is_private_attr(a)])
        else:
            attrs = all_attrs
            private_count = 0

        # Categorize attributes
        classes = []
        functions = []
        callables = []
        variables = []
        submodules = []

        for attr_name in attrs:
            try:
                attr = getattr(self.module, attr_name)

                if inspect.ismodule(attr):
                    submodules.append(attr_name)
                elif inspect.isclass(attr):
                    classes.append(attr_name)
                elif inspect.isfunction(attr):
                    functions.append(attr_name)
                elif callable(attr):
                    callables.append(attr_name)
                else:
                    variables.append(attr_name)
            except (AttributeError, Exception):
                # Skip attributes that cannot be accessed
                continue

        # For detailed/full meta, get more info
        if self.level in ("detailed", "full"):
            # Additional structural meta could go here
            pass

        return {
            "attributes_count": len(attrs),
            "classes": sorted(classes),
            "functions": sorted(functions),
            "callables": sorted(callables),
            "variables": sorted(variables),
            "submodules": sorted(submodules),
            "private_count": private_count,
        }

    def _meta_documentation(self) -> DocumentationInfo:
        """meta module documentation.

        Returns
        -------
        DocumentationInfo
            Documentation information dictionary
        """
        docstring = inspect.getdoc(self.module)
        has_doc = bool(docstring)
        doc_length = len(docstring) if docstring else 0

        examples = []
        if self.level in ("detailed", "full") and docstring:
            examples = extract_examples_from_doc(docstring)

        return {
            "docstring": docstring,
            "has_doc": has_doc,
            "doc_length": doc_length,
            "examples": examples if self.level in ("detailed", "full") else [],
        }

    def _meta_versioning(self) -> VersionInfo:
        """meta version information.

        Returns
        -------
        VersionInfo
            Version information dictionary
        """
        # Get version from various possible attributes
        version = None
        for attr in ("__version__", "VERSION", "version", "_version"):
            version = safe_getattr(self.module, attr)
            if version:
                break

        # Calculate source hash if possible
        source_hash = None
        if self.level in ("detailed", "full"):
            source_hash = self._calculate_source_hash()

        # Try to get author and license
        author = safe_getattr(self.module, "__author__")
        license_info = safe_getattr(self.module, "__license__")

        return {
            "version": version,
            "source_hash": source_hash,
            "author": author,
            "license": license_info,
        }

    def _meta_risks(self) -> RiskInfo:
        """meta security risks.

        Returns
        -------
        RiskInfo
            Risk assessment dictionary
        """
        attrs = dir(self.module)

        # Check for suspicious attributes
        has_exec = "exec" in attrs
        has_eval = "eval" in attrs
        has_import_hook = "__import__" in attrs

        # Find all suspicious attributes
        suspicious_attrs = [
            attr for attr in attrs if attr in self.SUSPICIOUS_ATTRIBUTES
        ]
        is_suspicious = (
            len(suspicious_attrs) > 0 or has_exec or has_eval or has_import_hook
        )

        # Determine risk level
        risk_level = "low"
        if is_suspicious:
            if has_exec or has_eval:
                risk_level = "high"
            elif len(suspicious_attrs) > 3:
                risk_level = "medium"
            else:
                risk_level = "low"

        return {
            "exec": has_exec,
            "eval": has_eval,
            "import_hook": has_import_hook,
            "suspicious": is_suspicious,
            "risk_level": risk_level,
            "suspicious_attrs": (
                suspicious_attrs if self.level in ("detailed", "full") else []
            ),
        }

    def _meta_performance(self, meta_time_ms: float) -> PerformanceInfo:
        """meta performance metrics.

        Parameters
        ----------
        meta_time_ms : float
            Time taken for meta in milliseconds

        Returns
        -------
        PerformanceInfo
            Performance information dictionary
        """
        # Measure attribute access time
        attribute_access_time_ms = 0
        if self.level in ("detailed", "full"):
            access_times = []
            attrs = dir(self.module)[:10]  # Sample first 10 attributes

            for attr_name in attrs:
                start = time.perf_counter()
                try:
                    _ = getattr(self.module, attr_name)
                except:
                    pass
                end = time.perf_counter()
                access_times.append((end - start) * 1000)

            if access_times:
                attribute_access_time_ms = sum(access_times) / len(access_times)

        return {
            "import_time_ms": None,  # Would need tracking from import time
            "meta_time_ms": meta_time_ms,
            "attribute_access_time_ms": attribute_access_time_ms,
        }

    def _calculate_source_hash(self) -> Optional[str]:
        """Calculate hash of source file.

        Returns
        -------
        Optional[str]
            SHA-256 hash of source file, None if not available
        """
        from .utils import hash_bytes

        file = get_source_file(self.module)
        if not file or not os.path.exists(file):
            return None

        try:
            with open(file, "rb") as f:
                content = f.read()
                return hash_bytes(content)
        except (OSError, IOError):
            return None


def meta_module(
    module: ModuleType, include_private: bool = False, level: AnalysisLevel = "standard"
) -> ModuleMetadata:
    """Convenience function to meta a module.

    Parameters
    ----------
    module : ModuleType
        Module to meta
    include_private : bool, optional
        Include private attributes (default=False)
    level : AnalysisLevel, optional
        meta depth (default='standard')

    Returns
    -------
    ModuleMetadata
        Complete module metadata

    Examples
    --------
    >>> import os
    >>> metadata = meta_module(os)
    >>> print(metadata['identity']['name'])
    'os'
    """
    Meta = ModuleMeta(module, include_private, level)
    return Meta.meta()
