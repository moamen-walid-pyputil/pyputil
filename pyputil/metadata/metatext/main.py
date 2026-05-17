#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Main MetaParser class for parsing package metadata.

Classes
-------
MetaParser
    Main parser for package metadata.
"""

from typing import Dict, List, Optional, Any
import re

from .models import (
    MetadataInfo,
    AuthorInfo,
    DependencyInfo,
    ValidationReport,
    ClassifierAnalysis,
    ProjectRelationships,
)
from .validators import MetadataValidator
from .parsers import MultilineParser, FieldExtractor, ClassifierParser
from .dependency_parser import DependencyParser


class MetaParser:
    """
    Metadata parser.

    Attributes
    ----------
    text : str
        Raw metadata text
    _parser : MultilineParser
        Multiline parser instance
    _cache : Dict[str, Any]
        Internal cache for computed properties
    """

    # Required fields according to PyPI standards
    REQUIRED_FIELDS = {"name", "version", "summary"}

    def __init__(self, metadata_text: str):
        """
        Initialize MetaParser with metadata text.

        Parameters
        ----------
        metadata_text : str
            Raw metadata text to parse
        """
        self.text = metadata_text.strip()
        self._parser = MultilineParser(self.text)
        self._cache: Dict[str, Any] = {}

    def _get_cached(self, key: str, compute_func):
        """Helper method for caching computed values."""
        if key not in self._cache:
            self._cache[key] = compute_func()
        return self._cache[key]

    def parse(self) -> MetadataInfo:
        """
        Parse metadata text and return structured information.

        Returns
        -------
        MetadataInfo
            Complete parsed metadata information

        Examples
        --------
        >>> parser = MetaParser(metadata_text)
        >>> info = parser.parse()
        >>> print(info.name)
        >>> print(info.version)
        """
        # Parse all components
        author_info = self._parse_author_info()
        dependency_info = self._parse_deps()
        project_urls = self._parse_project_urls()
        classifiers = self._parse_classifiers()

        # Create MetadataInfo object
        info = MetadataInfo(
            name=self._get_field("name"),
            version=self._get_field("version"),
            summary=self._get_field("summary"),
            description=self._parser.get_section("description"),
            author_info=author_info,
            license=self._parser.get_section("license"),
            license_full=self._parse_license_full(),
            classifiers=classifiers,
            project_urls=project_urls,
            requires_python=self._get_field("requires-python"),
            content_type=self._get_field("description-content-type"),
            extras=self._parse_extras(),
            metadata_version=self._get_field("metadata-version"),
            dependency_info=dependency_info,
            copyright=self._parse_copyright(),
            validation=self._validate(),
            classifier_analysis=self._analyze_classifiers(classifiers),
            project_relationships=self._analyze_project_relationships(
                project_urls, classifiers
            ),
        )

        return info

    def _get_field(self, field_name: str) -> str:
        """Get field value from parser."""
        return self._parser.get_section(field_name)

    def _parse_author_info(self) -> AuthorInfo:
        """Parse author information."""
        author_email = self._get_field("author-email")
        author_name, email = FieldExtractor.extract_author_email(author_email)

        # Extract maintainers from classifiers
        maintainers = []
        classifiers = self._parse_classifiers()
        for classifier in classifiers:
            if "Maintainer ::" in classifier:
                parts = classifier.split(" :: ")
                if len(parts) >= 2:
                    maintainer = parts[-1].strip()
                    if maintainer and maintainer not in maintainers:
                        maintainers.append(maintainer)

        return AuthorInfo(
            name=author_name,
            email=email,
            maintainers=maintainers,
            has_contact=bool(email),
        )

    def _parse_deps(self) -> DependencyInfo:
        """Parse dependency information."""
        requires_dist_lines = [
            line for line in self._parser.lines if line.startswith("Requires-Dist:")
        ]

        parsed = DependencyParser.parse_deps(requires_dist_lines)

        return DependencyInfo(
            required=parsed["required"],
            optional=parsed["optional"],
            conditional=parsed["conditional"],
        )

    def _parse_project_urls(self) -> Dict[str, str]:
        """Parse project URLs."""
        urls = {}
        for line in self._parser.lines:
            if line.startswith("Project-URL:"):
                value = line.split(":", 1)[1].strip()
                result = FieldExtractor.extract_project_url(value)
                if result:
                    label, url = result
                    urls[label] = url
        return urls

    def _parse_classifiers(self) -> List[str]:
        """Parse classifiers."""
        classifiers = []
        for line in self._parser.lines:
            if line.startswith("Classifier:"):
                classifier = line.split(":", 1)[1].strip()
                classifiers.append(classifier)
        return classifiers

    def _parse_extras(self) -> List[str]:
        """Parse extras."""
        extras = []
        for line in self._parser.lines:
            if line.startswith("Provides-Extra:"):
                extra = line.split(":", 1)[1].strip().strip("'\"")
                extras.append(extra)
        return extras

    def _parse_copyright(self) -> str:
        """Parse copyright from license."""
        license_text = self._parser.get_section("license")
        return FieldExtractor.extract_copyright(license_text)

    def _parse_license_full(self) -> str:
        """Parse full license text with type."""
        license_text = self._parser.get_section("license")
        if not license_text:
            return ""

        license_type = FieldExtractor.extract_license_type(license_text)
        if license_type != "Unknown":
            return f"{license_type} License\n\n{license_text}"
        return license_text

    def _validate(self) -> ValidationReport:
        """Validate metadata and generate report."""
        # Get field values
        fields = {
            "name": self._get_field("name"),
            "version": self._get_field("version"),
            "summary": self._get_field("summary"),
            "author_email": self._get_field("author-email"),
        }

        # Extract email from author-email field
        _, email = FieldExtractor.extract_author_email(fields["author_email"])

        # Validate individual components
        email_valid = MetadataValidator.validate_email(email)
        version_valid = MetadataValidator.validate_version(fields["version"])

        # Validate URLs
        urls = self._parse_project_urls()
        urls_valid = all(MetadataValidator.validate_url(url) for url in urls.values())

        # Check required fields
        missing_fields = MetadataValidator.validate_required_fields(fields)

        # Generate warnings
        warnings = []
        if not email_valid and email:
            warnings.append(f"Invalid email format: {email}")
        if not version_valid and fields["version"]:
            warnings.append(f"Invalid version format: {fields['version']}")

        return ValidationReport(
            email_valid=email_valid,
            urls_valid=urls_valid,
            version_valid=version_valid,
            missing_fields=missing_fields,
            warnings=warnings,
        )

    def _analyze_classifiers(self, classifiers: List[str]) -> ClassifierAnalysis:
        """Analyze classifiers."""
        categories = ClassifierParser.parse_classifiers(classifiers)
        analysis = ClassifierParser.analyze_classifiers(classifiers)

        return ClassifierAnalysis(
            total_count=len(classifiers),
            categories=categories,
            development_status=analysis["development_status"],
            python_versions=analysis["python_versions"],
            operating_systems=analysis["operating_systems"],
            frameworks=analysis["frameworks"],
        )

    def _analyze_project_relationships(
        self, project_urls: Dict[str, str], classifiers: List[str]
    ) -> ProjectRelationships:
        """Analyze project relationships."""
        # Extract related frameworks from classifiers
        related_frameworks = []
        for classifier in classifiers:
            if "Framework ::" in classifier:
                parts = classifier.split(" :: ")
                if len(parts) >= 2:
                    framework = parts[-1].strip()
                    if framework and framework not in related_frameworks:
                        related_frameworks.append(framework)

        return ProjectRelationships(
            homepage=project_urls.get("Homepage", ""),
            documentation=project_urls.get("Documentation", ""),
            repository=project_urls.get("Repository", ""),
            changelog=project_urls.get("Changelog", ""),
            tracker=project_urls.get("Tracker", ""),
            related_frameworks=related_frameworks,
        )

    def search_classifiers(self, pattern: str) -> List[str]:
        """
        Search classifiers by pattern.

        Parameters
        ----------
        pattern : str
            Pattern to search for

        Returns
        -------
        List[str]
            Matching classifiers
        """
        classifiers = self._parse_classifiers()
        pattern_lower = pattern.lower()
        return [cls for cls in classifiers if pattern_lower in cls.lower()]

    def filter_deps(self, pattern: str = None, extra: str = None) -> List[str]:
        """
        Filter deps by pattern and/or extra.

        Parameters
        ----------
        pattern : str, optional
            Pattern to search for in dependency names
        extra : str, optional
            Filter by extra requirement

        Returns
        -------
        List[str]
            Filtered deps
        """
        deps_info = self._parse_deps()
        return DependencyParser.filter_deps(
            {
                "required": deps_info.required,
                "optional": deps_info.optional,
                "conditional": deps_info.conditional,
            },
            pattern=pattern,
            extra=extra,
        )

    def get_extra_deps(self, extra_name: str) -> List[str]:
        """
        Get deps for a specific extra.

        Parameters
        ----------
        extra_name : str
            Extra name

        Returns
        -------
        List[str]
            deps for the specified extra
        """
        deps_info = self._parse_deps()
        return deps_info.optional.get(extra_name, [])

    def clear_cache(self) -> None:
        """Clear internal cache."""
        self._cache.clear()
