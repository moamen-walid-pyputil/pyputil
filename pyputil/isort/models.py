#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Data models for import sorter.

This module contains data classes representing import statements
and organized import sections.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
from .config import ImportType


@dataclass
class ImportStatement:
    """
    Represents a single import statement with metadata.

    Parameters
    ----------
    raw_statement : str
        The original import statement as string.
    line_number : int
        Line number where import was found.
    import_type : ImportType
        Type of import (standard, third-party, etc.).
    module : str
        Module name being imported.
    is_from_import : bool
        True if it's a 'from ... import ...' statement.
    names : List[str], optional
        List of imported names (for 'from' imports).
    alias : Optional[str], optional
        Alias name if using 'as' keyword.
    comments : List[str], optional
        Inline and trailing comments.
    indent : str, optional
        Indentation of the import statement.
    """

    raw_statement: str
    line_number: int
    import_type: ImportType
    module: str
    is_from_import: bool
    names: List[str] = field(default_factory=list)
    alias: Optional[str] = None
    comments: List[str] = field(default_factory=list)
    indent: str = ""

    def __lt__(self, other: "ImportStatement") -> bool:
        """
        Compare two import statements for sorting.

        Parameters
        ----------
        other : ImportStatement
            Other import statement to compare with.

        Returns
        -------
        bool
            True if self should come before other.
        """
        # First compare by type
        if self.import_type.value != other.import_type.value:
            return self.import_type.value < other.import_type.value

        # Then compare by module name
        if self.module != other.module:
            return self.module < other.module

        # For from imports, compare by imported names
        if self.is_from_import and other.is_from_import:
            if self.names and other.names:
                return self.names[0] < other.names[0]

        return False

    def formatted(self, config) -> List[str]:
        """
        Format import statement according to configuration.

        Parameters
        ----------
        config : ImportConfig
            Configuration object with formatting rules.

        Returns
        -------
        List[str]
            List of lines for the formatted import statement.
        """
        lines = []
        base_line = self.indent

        if self.is_from_import:
            base_line += f"from {self.module} import "
        else:
            base_line += f"import {self.module}"
            if self.alias:
                base_line += f" as {self.alias}"

        # Handle names for from imports
        if self.names:
            if len(self.names) == 1:
                base_line += self.names[0]
                if self.alias:
                    base_line += f" as {self.alias}"
            else:
                # Multi-line import
                base_line += "(" if config.use_parentheses else ""
                lines.append(base_line)

                for i, name in enumerate(sorted(self.names)):
                    line = self.indent + "    " + name
                    if config.include_trailing_comma or i < len(self.names) - 1:
                        line += ","
                    lines.append(line)

                closing = ")" if config.use_parentheses else ""
                lines.append(self.indent + closing)
        else:
            lines.append(base_line)

        # Add comments
        if self.comments:
            if config.ensure_newline_before_comments:
                lines.append("")
            for comment in self.comments:
                lines.append(self.indent + comment)

        return lines


@dataclass
class ImportSections:
    """
    Container for organized import statements by section.

    Parameters
    ----------
    future : List[ImportStatement]
        __future__ imports.
    standard : List[ImportStatement]
        Standard library imports.
    third_party : List[ImportStatement]
        Third-party package imports.
    first_party : List[ImportStatement]
        Current project imports.
    local : List[ImportStatement]
        Local/relative imports.
    """

    future: List[ImportStatement] = field(default_factory=list)
    standard: List[ImportStatement] = field(default_factory=list)
    third_party: List[ImportStatement] = field(default_factory=list)
    first_party: List[ImportStatement] = field(default_factory=list)
    local: List[ImportStatement] = field(default_factory=list)

    def add_statement(self, statement: ImportStatement) -> None:
        """
        Add an import statement to the appropriate section.

        Parameters
        ----------
        statement : ImportStatement
            Import statement to add.
        """
        if statement.import_type == ImportType.FUTURE:
            self.future.append(statement)
        elif statement.import_type == ImportType.STANDARD:
            self.standard.append(statement)
        elif statement.import_type == ImportType.THIRD_PARTY:
            self.third_party.append(statement)
        elif statement.import_type == ImportType.FIRST_PARTY:
            self.first_party.append(statement)
        elif statement.import_type == ImportType.LOCAL:
            self.local.append(statement)

    def get_section(self, section_type: ImportType) -> List[ImportStatement]:
        """
        Get import statements for a specific section.

        Parameters
        ----------
        section_type : ImportType
            Type of section to retrieve.

        Returns
        -------
        List[ImportStatement]
            List of import statements in the section.
        """
        sections = {
            ImportType.FUTURE: self.future,
            ImportType.STANDARD: self.standard,
            ImportType.THIRD_PARTY: self.third_party,
            ImportType.FIRST_PARTY: self.first_party,
            ImportType.LOCAL: self.local,
        }
        return sections.get(section_type, [])

    def get_all_statements(
        self, section_order: List[ImportType]
    ) -> List[ImportStatement]:
        """
        Get all import statements in specified order.

        Parameters
        ----------
        section_order : List[ImportType]
            Order in which to return sections.

        Returns
        -------
        List[ImportStatement]
            All import statements sorted by section order.
        """
        all_statements = []

        for section in section_order:
            statements = self.get_section(section)
            if statements:
                all_statements.extend(sorted(statements))
                all_statements.append(None)  # Marker for section separation

        # Remove trailing None
        if all_statements and all_statements[-1] is None:
            all_statements.pop()

        return all_statements

    def is_empty(self) -> bool:
        """
        Check if all sections are empty.

        Returns
        -------
        bool
            True if no import statements in any section.
        """
        return (
            not self.future
            and not self.standard
            and not self.third_party
            and not self.first_party
            and not self.local
        )
