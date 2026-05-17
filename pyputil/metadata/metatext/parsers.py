#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Parsers for extracting metadata from text.

Classes
-------
MultilineParser
    Parser for handling multiline metadata values.
FieldExtractor
    Extractor for specific metadata fields.
ClassifierParser
    Parser for classifier analysis.
"""

import re
from typing import Dict, List, Optional, Tuple, Pattern, DefaultDict
from collections import defaultdict
from email.utils import parseaddr


class MultilineParser:
    """Parser for handling multiline metadata values efficiently."""

    _MULTILINE_CONTINUATION: Pattern = re.compile(r"^\s+")

    def __init__(self, text: str):
        """
        Initialize multiline parser.

        Parameters
        ----------
        text : str
            Raw metadata text
        """
        self.lines = text.strip().split("\n")
        self._sections: Dict[str, List[str]] = {}
        self._parse_sections()

    def _parse_sections(self) -> None:
        """Parse and cache all multiline sections."""
        current_section = None
        current_lines: List[str] = []

        for line in self.lines:
            if ":" in line and not self._MULTILINE_CONTINUATION.match(line):
                # Save previous section
                if current_section is not None and current_lines:
                    self._sections[current_section] = current_lines

                # Start new section
                parts = line.split(":", 1)
                current_section = parts[0].strip().lower()
                current_lines = [parts[1].strip()] if parts[1].strip() else []
            elif current_section is not None and line.strip():
                if self._MULTILINE_CONTINUATION.match(line) or not ":" in line:
                    current_lines.append(line.strip())

        # Save last section
        if current_section is not None and current_lines:
            self._sections[current_section] = current_lines

    def get_section(self, key: str) -> str:
        """
        Get section content as a single string.

        Parameters
        ----------
        key : str
            Section key (case-insensitive)

        Returns
        -------
        str
            Combined section content
        """
        lines = self._sections.get(key.lower(), [])
        return " ".join(lines).strip()

    def get_section_lines(self, key: str) -> List[str]:
        """
        Get section content as individual lines.

        Parameters
        ----------
        key : str
            Section key (case-insensitive)

        Returns
        -------
        List[str]
            List of lines in the section
        """
        return self._sections.get(key.lower(), [])


class FieldExtractor:
    """Extractor for specific metadata field patterns."""

    # Pre-compiled regex patterns
    _EMAIL_PATTERN: Pattern = re.compile(r"(.+?)\s*<(.+?)>")
    _URL_PATTERN: Pattern = re.compile(r"([^,]+),\s*(.+)")
    _COPYRIGHT_PATTERN: Pattern = re.compile(
        r"Copyright\s*\([cC]\)\s*(.*?)(?:\n\n|$)", re.DOTALL | re.IGNORECASE
    )

    @staticmethod
    def extract_author_email(value: str) -> Tuple[str, str]:
        """
        Extract author name and email from string.

        Parameters
        ----------
        value : str
            Author-Email field value

        Returns
        -------
        Tuple[str, str]
            (author_name, email)
        """
        if not value:
            return ("", "")

        match = FieldExtractor._EMAIL_PATTERN.match(value)
        if match:
            return (match.group(1).strip(), match.group(2).strip())

        # Try email.utils as fallback
        name, email = parseaddr(value)
        if name or email:
            return (name, email)

        return (value.strip(), "")

    @staticmethod
    def extract_project_url(value: str) -> Optional[Tuple[str, str]]:
        """
        Extract project URL label and URL.

        Parameters
        ----------
        value : str
            Project-URL field value

        Returns
        -------
        Optional[Tuple[str, str]]
            (label, url) or None if invalid
        """
        if not value:
            return None

        match = FieldExtractor._URL_PATTERN.match(value)
        if match:
            return (match.group(1).strip(), match.group(2).strip())

        return None

    @staticmethod
    def extract_copyright(license_text: str) -> str:
        """
        Extract copyright from license text.

        Parameters
        ----------
        license_text : str
            License text

        Returns
        -------
        str
            Copyright statement or empty string
        """
        if not license_text:
            return ""

        match = FieldExtractor._COPYRIGHT_PATTERN.search(license_text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def extract_license_type(license_text: str) -> str:
        """
        Identify license type from text.

        Parameters
        ----------
        license_text : str
            License text

        Returns
        -------
        str
            License type (MIT, BSD, Apache, etc.)
        """
        license_text_lower = license_text.lower()

        if "mit" in license_text_lower:
            return "MIT"
        elif "apache" in license_text_lower and "2.0" in license_text_lower:
            return "Apache-2.0"
        elif "bsd" in license_text_lower:
            if "3-clause" in license_text_lower or "modified" in license_text_lower:
                return "BSD-3-Clause"
            elif "2-clause" in license_text_lower or "simplified" in license_text_lower:
                return "BSD-2-Clause"
            return "BSD"
        elif "gpl" in license_text_lower:
            if "3" in license_text_lower:
                return "GPL-3.0"
            elif "2" in license_text_lower:
                return "GPL-2.0"
            return "GPL"
        elif "lgpl" in license_text_lower:
            return "LGPL"

        return "Unknown"


class ClassifierParser:
    """Parser for classifier analysis and organization."""

    @staticmethod
    def parse_classifiers(classifiers: List[str]) -> Dict[str, List[str]]:
        """
        Organize classifiers by category.

        Parameters
        ----------
        classifiers : List[str]
            List of classifier strings

        Returns
        -------
        Dict[str, List[str]]
            Classifiers grouped by category
        """
        categories: DefaultDict[str, List[str]] = defaultdict(list)

        for classifier in classifiers:
            if " :: " in classifier:
                category = classifier.split(" :: ")[0]
                categories[category].append(classifier)
            else:
                categories["Other"].append(classifier)

        return dict(categories)

    @staticmethod
    def analyze_classifiers(classifiers: List[str]) -> Dict[str, List[str]]:
        """
        Analyze classifiers by type.

        Parameters
        ----------
        classifiers : List[str]
            List of classifier strings

        Returns
        -------
        Dict[str, List[str]]
            Classifiers grouped by analysis type
        """
        analysis = {
            "development_status": [],
            "python_versions": [],
            "operating_systems": [],
            "frameworks": [],
            "topics": [],
            "audiences": [],
            "maintainers": [],
        }

        for classifier in classifiers:
            if "Development Status ::" in classifier:
                analysis["development_status"].append(classifier)
            elif "Programming Language :: Python ::" in classifier:
                analysis["python_versions"].append(classifier)
            elif "Operating System ::" in classifier:
                analysis["operating_systems"].append(classifier)
            elif "Framework ::" in classifier:
                analysis["frameworks"].append(classifier)
            elif "Topic ::" in classifier:
                analysis["topics"].append(classifier)
            elif "Intended Audience ::" in classifier:
                analysis["audiences"].append(classifier)
            elif "Maintainer ::" in classifier:
                analysis["maintainers"].append(classifier)

        return analysis
