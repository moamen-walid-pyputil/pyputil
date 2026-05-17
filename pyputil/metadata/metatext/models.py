#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Data models for metadata parsing using dataclasses.

Classes
-------
MetadataInfo
    Main dataclass containing all parsed metadata information.
ValidationReport
    Dataclass for validation results.
AuthorInfo
    Structured author information.
DependencyInfo
    Information about package dependencies.
ClassifierAnalysis
    Analysis results for classifiers.
ProjectRelationships
    Relationships between project URLs and other metadata.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from collections import defaultdict


@dataclass
class AuthorInfo:
    """Structured author information.

    Attributes
    ----------
    name : str
        Author name
    email : str
        Author email
    maintainers : List[str]
        List of maintainer names
    has_contact : bool
        Whether contact information is available
    """

    name: str = ""
    email: str = ""
    maintainers: List[str] = field(default_factory=list)
    has_contact: bool = False


@dataclass
class DependencyInfo:
    """Package dependency information.

    Attributes
    ----------
    required : List[str]
        Required dependencies
    optional : Dict[str, List[str]]
        Optional dependencies by extra
    conditional : List[str]
        Conditional dependencies
    """

    required: List[str] = field(default_factory=list)
    optional: Dict[str, List[str]] = field(default_factory=dict)
    conditional: List[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Validation results for metadata.

    Attributes
    ----------
    email_valid : bool
        Whether email is valid
    urls_valid : bool
        Whether URLs are valid
    version_valid : bool
        Whether version is valid
    missing_fields : List[str]
        List of missing required fields
    warnings : List[str]
        Validation warnings
    """

    email_valid: bool = False
    urls_valid: bool = False
    version_valid: bool = False
    missing_fields: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ClassifierAnalysis:
    """Analysis results for classifiers.

    Attributes
    ----------
    total_count : int
        Total number of classifiers
    categories : Dict[str, List[str]]
        Classifiers grouped by category
    development_status : List[str]
        Development status classifiers
    python_versions : List[str]
        Python version classifiers
    operating_systems : List[str]
        OS classifiers
    frameworks : List[str]
        Framework classifiers
    """

    total_count: int = 0
    categories: Dict[str, List[str]] = field(default_factory=dict)
    development_status: List[str] = field(default_factory=list)
    python_versions: List[str] = field(default_factory=list)
    operating_systems: List[str] = field(default_factory=list)
    frameworks: List[str] = field(default_factory=list)


@dataclass
class ProjectRelationships:
    """Relationships between project URLs and metadata.

    Attributes
    ----------
    homepage : str
        Homepage URL
    documentation : str
        Documentation URL
    repository : str
        Repository URL
    changelog : str
        Changelog URL
    tracker : str
        Issue tracker URL
    related_frameworks : List[str]
        Related frameworks from classifiers
    """

    homepage: str = ""
    documentation: str = ""
    repository: str = ""
    changelog: str = ""
    tracker: str = ""
    related_frameworks: List[str] = field(default_factory=list)


@dataclass
class MetadataInfo:
    """Complete parsed metadata information.

    Attributes
    ----------
    name : str
        Package name
    version : str
        Package version
    summary : str
        Short description
    description : str
        Full description
    author_info : AuthorInfo
        Author information
    license : str
        License text
    license_full : str
        Full license with structure
    classifiers : List[str]
        All classifiers
    project_urls : Dict[str, str]
        Project URLs by label
    requires_python : str
        Python requirement
    content_type : str
        Description content type
    extras : List[str]
        Available extras
    metadata_version : str
        Metadata version
    dependency_info : DependencyInfo
        Dependency information
    copyright : str
        Copyright information
    validation : ValidationReport
        Validation results
    classifier_analysis : ClassifierAnalysis
        Classifier analysis
    project_relationships : ProjectRelationships
        Project relationships
    """

    name: str = ""
    version: str = ""
    summary: str = ""
    description: str = ""
    author_info: AuthorInfo = field(default_factory=AuthorInfo)
    license: str = ""
    license_full: str = ""
    classifiers: List[str] = field(default_factory=list)
    project_urls: Dict[str, str] = field(default_factory=dict)
    requires_python: str = ""
    content_type: str = ""
    extras: List[str] = field(default_factory=list)
    metadata_version: str = ""
    dependency_info: DependencyInfo = field(default_factory=DependencyInfo)
    copyright: str = ""
    validation: ValidationReport = field(default_factory=ValidationReport)
    classifier_analysis: ClassifierAnalysis = field(default_factory=ClassifierAnalysis)
    project_relationships: ProjectRelationships = field(
        default_factory=ProjectRelationships
    )
