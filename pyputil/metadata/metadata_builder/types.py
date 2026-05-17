#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Type definitions for the metadata analyzer.

Provides TypeAlias and TypedDict definitions for type safety and clarity.
"""

from typing import TypedDict, List, Optional, Any, Dict, Union, Literal
from datetime import datetime
from types import ModuleType


class IdentityInfo(TypedDict):
    """Module identity information.

    Attributes
    ----------
    name : str
        Module name (e.g., 'os', 'sys')
    id : int
        Unique object ID from id(module)
    name_hash : str
        SHA-256 hash of the module name
    full_name : Optional[str]
        Full dotted module name
    """

    name: str
    id: int
    name_hash: str
    full_name: Optional[str]


class LocationInfo(TypedDict):
    """Module location information.

    Attributes
    ----------
    file : Optional[str]
        Path to module file, None for builtins
    is_builtin : bool
        Whether module is built-in
    origin : Optional[str]
        Module origin (e.g., 'frozen', 'builtin')
    package : Optional[str]
        Package name if module is part of a package
    has_location : bool
        Whether module has a physical location
    """

    file: Optional[str]
    is_builtin: bool
    origin: Optional[str]
    package: Optional[str]
    has_location: bool


class LoaderInfo(TypedDict):
    """Module loader information.

    Attributes
    ----------
    type : Optional[str]
        Loader type (e.g., 'SourceFileLoader')
    name : Optional[str]
        Loader class name
    reloadable : bool
        Whether module can be reloaded
    """

    type: Optional[str]
    name: Optional[str]
    reloadable: bool


class RuntimeInfo(TypedDict):
    """Module runtime information.

    Attributes
    ----------
    loaded : bool
        Whether module is currently loaded
    ref_count : int
        Reference count from sys.getrefcount()
    timestamp : float
        Analysis timestamp (Unix time)
    load_time : Optional[float]
        When module was loaded (if available)
    size_bytes : Optional[int]
        Approximate memory size in bytes
    """

    loaded: bool
    ref_count: int
    timestamp: float
    load_time: Optional[float]
    size_bytes: Optional[int]


class StructureInfo(TypedDict):
    """Module structure information.

    Attributes
    ----------
    attributes_count : int
        Total number of attributes
    classes : List[str]
        List of class names
    functions : List[str]
        List of function names
    callables : List[str]
        List of other callable names
    variables : List[str]
        List of variable/constant names
    submodules : List[str]
        List of submodule names
    private_count : int
        Number of private attributes (starting with '_')
    """

    attributes_count: int
    classes: List[str]
    functions: List[str]
    callables: List[str]
    variables: List[str]
    submodules: List[str]
    private_count: int


class DocumentationInfo(TypedDict):
    """Module documentation information.

    Attributes
    ----------
    docstring : Optional[str]
        Module docstring
    has_doc : bool
        Whether module has a docstring
    doc_length : int
        Length of docstring in characters
    examples : List[str]
        List of code examples from docstring
    """

    docstring: Optional[str]
    has_doc: bool
    doc_length: int
    examples: List[str]


class VersionInfo(TypedDict):
    """Module version information.

    Attributes
    ----------
    version : Optional[str]
        Module version string
    source_hash : Optional[str]
        SHA-256 hash of source file
    author : Optional[str]
        Module author
    license : Optional[str]
        Module license
    """

    version: Optional[str]
    source_hash: Optional[str]
    author: Optional[str]
    license: Optional[str]


class RiskInfo(TypedDict):
    """Security risk assessment.

    Attributes
    ----------
    exec : bool
        Contains 'exec' attribute
    eval : bool
        Contains 'eval' attribute
    import_hook : bool
        Contains '__import__' attribute
    suspicious : bool
        Contains suspicious attributes
    risk_level : Literal['low', 'medium', 'high']
        Overall risk level
    suspicious_attrs : List[str]
        List of suspicious attribute names
    """

    exec: bool
    eval: bool
    import_hook: bool
    suspicious: bool
    risk_level: Literal["low", "medium", "high"]
    suspicious_attrs: List[str]


class PerformanceInfo(TypedDict):
    """Performance metrics.

    Attributes
    ----------
    import_time_ms : Optional[float]
        Time to import module in milliseconds
    analysis_time_ms : float
        Time to analyze module in milliseconds
    attribute_access_time_ms : float
        Average time to access attributes in ms
    """

    import_time_ms: Optional[float]
    analysis_time_ms: float
    attribute_access_time_ms: float


class ModuleMetadata(TypedDict):
    """Complete module metadata.

    Attributes
    ----------
    identity : IdentityInfo
        Identity information
    location : LocationInfo
        Location information
    loader : LoaderInfo
        Loader information
    runtime : RuntimeInfo
        Runtime information
    structure : StructureInfo
        Structure information
    documentation : DocumentationInfo
        Documentation information
    versioning : VersionInfo
        Version information
    risk_flags : RiskInfo
        Risk assessment
    performance : PerformanceInfo
        Performance metrics
    analysis_timestamp : str
        ISO format timestamp of analysis
    python_version : str
        Python version used for analysis
    """

    identity: IdentityInfo
    location: LocationInfo
    loader: LoaderInfo
    runtime: RuntimeInfo
    structure: StructureInfo
    documentation: DocumentationInfo
    versioning: VersionInfo
    risk_flags: RiskInfo
    performance: PerformanceInfo
    analysis_timestamp: str
    python_version: str


ExportFormat = Literal["json", "toml", "yaml", "xml", "csv", "md", "txt", "html"]
AnalysisLevel = Literal["basic", "standard", "detailed", "full"]
