#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Classes
-------
MetaParser
    Main parser class for metadata extraction.
MetadataInfo
    Complete parsed metadata information.
AuthorInfo
    Structured author information.
DependencyInfo
    Package dependency information.
ValidationReport
    Validation results for metadata.
ClassifierAnalysis
    Analysis results for classifiers.
ProjectRelationships
    Relationships between project URLs and metadata.

Examples
--------
>>> from pyputil.metadata import MetaParser
>>> parser = MetaParser(metadata_text)
>>> info = parser.parse()
>>> print(f"Package: {info.name} v{info.version}")
>>> print(f"Author: {info.author_info.name}")
>>> print(f"Dependencies: {len(info.dependency_info.required)} required")
"""

from .main import MetaParser
from .models import (
    MetadataInfo,
    AuthorInfo,
    DependencyInfo,
    ValidationReport,
    ClassifierAnalysis,
    ProjectRelationships,
)

__all__ = [
    "MetaParser",
    "MetadataInfo",
    "AuthorInfo",
    "DependencyInfo",
    "ValidationReport",
    "ClassifierAnalysis",
    "ProjectRelationships",
]
