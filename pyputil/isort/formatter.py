#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Import statement formatter module.

This module contains functions for formatting import statements
according to configuration rules.
"""

from typing import List, Dict, Optional
from .config import ImportConfig
from .models import ImportStatement, ImportSections


class ImportFormatter:
    """
    Formatter for import statements.

    Formats import statements according to configuration rules
    including line length, multi-line style, and spacing.

    Parameters
    ----------
    config : ImportConfig
        Configuration object with formatting rules.
    """

    def __init__(self, config: ImportConfig):
        """
        Initialize the import formatter.

        Parameters
        ----------
        config : ImportConfig
            Configuration object.
        """
        self.config = config

    def format_sections(self, sections: ImportSections) -> List[str]:
        """
        Format all import sections into lines of code.

        Parameters
        ----------
        sections : ImportSections
            Organized import sections.

        Returns
        -------
        List[str]
            Formatted lines of import statements.
        """
        formatted_lines = []
        section_order = self.config.get_section_order()

        for i, section_type in enumerate(section_order):
            statements = sections.get_section(section_type)
            if not statements:
                continue

            # Sort statements within section
            sorted_statements = sorted(statements)

            # Format each statement
            section_lines = []
            for statement in sorted_statements:
                statement_lines = self.format_statement(statement)
                section_lines.extend(statement_lines)

            # Add section separator if not first section
            if formatted_lines and section_lines:
                formatted_lines.append("")

            formatted_lines.extend(section_lines)

        return formatted_lines

    def format_statement(self, statement: ImportStatement) -> List[str]:
        """
        Format a single import statement.

        Parameters
        ----------
        statement : ImportStatement
            Import statement to format.

        Returns
        -------
        List[str]
            Formatted lines for the import statement.
        """
        if not statement.names or len(statement.names) == 1:
            return self._format_single_line(statement)
        else:
            return self._format_multi_line(statement)

    def _format_single_line(self, statement: ImportStatement) -> List[str]:
        """
        Format a single-line import statement.

        Parameters
        ----------
        statement : ImportStatement
            Import statement to format.

        Returns
        -------
        List[str]
            Single formatted line.
        """
        line = statement.indent

        if statement.is_from_import:
            line += f"from {statement.module} import "
            if statement.names:
                line += statement.names[0]
                if statement.alias:
                    line += f" as {statement.alias}"
        else:
            line += f"import {statement.module}"
            if statement.alias:
                line += f" as {statement.alias}"

        # Add comments
        if statement.comments:
            # Ensure space before comment
            if not line.endswith(" "):
                line += " "
            line += statement.comments[0]

        return [line]

    def _format_multi_line(self, statement: ImportStatement) -> List[str]:
        """
        Format a multi-line import statement.

        Parameters
        ----------
        statement : ImportStatement
            Import statement to format.

        Returns
        -------
        List[str]
            Multiple formatted lines.
        """
        lines = []
        base_indent = statement.indent
        item_indent = base_indent + "    "

        # Build the first line
        first_line = base_indent

        if statement.is_from_import:
            first_line += f"from {statement.module} import "
        else:
            # Multi-line simple imports are rare but possible
            first_line += "import "

        # Choose multi-line style based on configuration
        if self.config.multi_line_output == 0:
            # Inline style (not actually multi-line)
            if statement.is_from_import:
                first_line += ", ".join(sorted(statement.names))
            return [first_line]

        elif self.config.multi_line_output in [1, 2, 3]:
            # Grid styles
            return self._format_grid_style(statement)

        elif self.config.multi_line_output in [4, 5, 6]:
            # Hanging indent styles
            return self._format_hanging_indent(statement)

        # Default to grid style
        return self._format_grid_style(statement)

    def _format_grid_style(self, statement: ImportStatement) -> List[str]:
        """
        Format using grid style (isort styles 1-3).

        Parameters
        ----------
        statement : ImportStatement
            Import statement to format.

        Returns
        -------
        List[str]
            Formatted lines in grid style.
        """
        lines = []
        base_indent = statement.indent
        item_indent = base_indent + "    "

        # Start with opening line
        opening = base_indent

        if statement.is_from_import:
            opening += f"from {statement.module} import "
        else:
            opening += "import "

        if self.config.use_parentheses:
            opening += "("

        lines.append(opening)

        # Add items
        sorted_names = sorted(statement.names)
        for i, name in enumerate(sorted_names):
            line = item_indent + name

            # Add comma if needed
            if self.config.include_trailing_comma or i < len(sorted_names) - 1:
                line += ","

            lines.append(line)

        # Add closing
        closing = base_indent
        if self.config.use_parentheses:
            closing += ")"
        lines.append(closing)

        return lines

    def _format_hanging_indent(self, statement: ImportStatement) -> List[str]:
        """
        Format using hanging indent style (isort styles 4-6).

        Parameters
        ----------
        statement : ImportStatement
            Import statement to format.

        Returns
        -------
        List[str]
            Formatted lines with hanging indent.
        """
        lines = []
        base_indent = statement.indent

        # Build the first line
        first_line = base_indent

        if statement.is_from_import:
            first_line += f"from {statement.module} import "
        else:
            first_line += "import "

        # Add first item
        sorted_names = sorted(statement.names)
        first_line += sorted_names[0] + ","
        lines.append(first_line)

        # Add remaining items with hanging indent
        for i, name in enumerate(sorted_names[1:], 1):
            line = base_indent + "    " + name
            if i < len(sorted_names) - 1 or self.config.include_trailing_comma:
                line += ","
            lines.append(line)

        return lines

    def calculate_line_length(self, line: str) -> int:
        """
        Calculate effective line length considering tabs.

        Parameters
        ----------
        line : str
            Line of code.

        Returns
        -------
        int
            Effective line length.
        """
        # Count tabs as 4 spaces (common convention)
        return len(line.replace("\t", "    "))
