#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from .metatext import (
    MetaParser,
    MetadataInfo,
    AuthorInfo,
    DependencyInfo,
    ValidationReport,
    ClassifierAnalysis,
    ProjectRelationships,
)
from .metadata_builder import (
    ModuleMeta,
    meta_module,
    MetadataExporter,
    export_metadata,
    ConfigManager,
    AnalyzerConfig,
    ModuleMetadata,
    ExportFormat,
    AnalysisLevel,
)
from .meta import show_metadata, has_metadata
from ._meta_reader import PackageMetadata, MetadataReader
from .meta_package import get_package_metadata


__all__ = [
    "MetaParser",
    "MetadataReader",
    "MetadataInfo",
    "AuthorInfo",
    "DependencyInfo",
    "ValidationReport",
    "ProjectRelationships",
    "PackageMetadata",
    "ClassifierAnalysis",
    "meta_module",
    "MetadataExporter",
    "export_metadata",
    "ConfigManager",
    "AnalyzerConfig",
    "ModuleMetadata",
    "ExportFormat",
    "AnalysisLevel",
    "get_package_metadata",
    "show_metadata",
    "has_metadata",
]


from ..api import clean
clean(expose=__all__)
