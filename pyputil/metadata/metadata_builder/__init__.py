#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Main components:
- ModuleMeta: Core analysis metadata logic
- MetadataExporter: Export to various formats
- ConfigManager: Configuration management

Example usage:
    >>> from pyputil.metadata import meta_module, export_metadata
    >>> import os
    >>> metadata = meta_module(os, level='detailed')
    >>> export_metadata(metadata, 'os_metadata.json', 'json')
"""

from .analyzer import ModuleMeta, meta_module
from .exporters import MetadataExporter, export_metadata
from .config import ConfigManager, AnalyzerConfig
from .types import ModuleMetadata, ExportFormat, AnalysisLevel


__all__ = [
    "ModuleMeta",
    "meta_module",
    "MetadataExporter",
    "export_metadata",
    "ConfigManager",
    "AnalyzerConfig",
    "ModuleMetadata",
    "ExportFormat",
    "AnalysisLevel",
]
