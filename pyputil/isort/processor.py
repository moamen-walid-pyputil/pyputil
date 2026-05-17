#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Main processor module for import sorter.

This module coordinates the parsing, organizing, and formatting
of import statements in Python files.
"""

from typing import List, Tuple, Optional, Set, Dict
from pathlib import Path
import shutil
import tempfile
from .config import ImportConfig, DEFAULT_CONFIG
from .parser import ImportParser
from .formatter import ImportFormatter
from .models import ImportStatement, ImportSections


class ImportProcessor:
    """
    Main processor for sorting import statements.

    Coordinates the entire process of reading Python files,
    extracting imports, organizing them, and writing back.

    Parameters
    ----------
    config : Optional[ImportConfig], optional
        Configuration object (default: DEFAULT_CONFIG).
    """

    def __init__(self, config: Optional[ImportConfig] = None):
        """
        Initialize the import processor.

        Parameters
        ----------
        config : Optional[ImportConfig], optional
            Configuration object (default: DEFAULT_CONFIG).
        """
        self.config = config or DEFAULT_CONFIG
        self.parser = ImportParser(self.config)
        self.formatter = ImportFormatter(self.config)

    def process_file(
        self, filepath: str, in_place: bool = True, backup: bool = False
    ) -> Tuple[bool, str, List[str]]:
        """
        Process a single Python file.

        Parameters
        ----------
        filepath : str
            Path to Python file.
        in_place : bool, optional
            Whether to modify file in place (default: True).
        backup : bool, optional
            Whether to create backup (default: False).

        Returns
        -------
        Tuple[bool, str, List[str]]
            (success, message, list of imports sorted)

        Raises
        ------
        FileNotFoundError
            If file does not exist.
        PermissionError
            If no write permission.
        """
        # Validate file
        if not Path(filepath).exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        if not filepath.endswith(".py"):
            return (False, f"Not a Python file: {filepath}", [])

        # Read file content
        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                content = Path(filepath).read_text(encoding="latin-1")
            except Exception as e:
                return (False, f"Cannot read file: {e}", [])

        # Parse imports
        try:
            imports = self.parser.parse_content(content, filepath)
        except Exception as e:
            return (False, f"Error parsing imports: {e}", [])

        if not imports:
            return (True, "No imports found", [])

        # Organize imports into sections
        sections = ImportSections()
        for import_stmt in imports:
            sections.add_statement(import_stmt)

        # Format imports
        formatted_imports = self.formatter.format_sections(sections)

        # Remove existing imports from content
        non_import_content = self._remove_imports(content, imports)

        # Combine formatted imports with non-import content
        new_content = self._combine_content(formatted_imports, non_import_content)

        # Write result
        if in_place:
            # Create backup if requested
            if backup:
                backup_path = f"{filepath}.bak"
                shutil.copy2(filepath, backup_path)

            # Write to temporary file first
            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, encoding="utf-8", suffix=".py"
            ) as tmp:
                tmp.write(new_content)
                tmp_path = tmp.name

            # Replace original file
            shutil.move(tmp_path, filepath)

            return (
                True,
                f"Successfully sorted imports in {filepath}",
                [stmt.raw_statement for stmt in imports],
            )
        else:
            # Return formatted content without writing
            return (
                True,
                "Content formatted successfully",
                [stmt.raw_statement for stmt in imports],
                new_content,
            )

    def process_dir(
        self,
        directory: str,
        recursive: bool = True,
        in_place: bool = True,
        backup: bool = False,
    ) -> Dict[str, dict]:
        """
        Process all Python files in a directory.

        Parameters
        ----------
        directory : str
            Directory path.
        recursive : bool, optional
            Whether to process subdirectories (default: True).
        in_place : bool, optional
            Whether to modify files in place (default: True).
        backup : bool, optional
            Whether to create backups (default: False).

        Returns
        -------
        Dict[str, dict]
            Dictionary with file paths as keys and results as values.
        """
        results = {}
        dir_path = Path(directory)

        if not dir_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        # Find Python files
        pattern = "**/*.py" if recursive else "*.py"

        for filepath in dir_path.glob(pattern):
            if filepath.is_file():
                try:
                    success, message, imports = self.process_file(
                        str(filepath), in_place, backup
                    )
                    results[str(filepath)] = {
                        "success": success,
                        "message": message,
                        "imports_count": len(imports),
                    }
                except Exception as e:
                    results[str(filepath)] = {
                        "success": False,
                        "message": str(e),
                        "imports_count": 0,
                    }

        return results

    def _remove_imports(self, content: str, imports: List[ImportStatement]) -> str:
        """
        Remove import statements from content.

        Parameters
        ----------
        content : str
            Original file content.
        imports : List[ImportStatement]
            Import statements to remove.

        Returns
        -------
        str
            Content without import statements.
        """
        lines = content.splitlines()

        # Create a set of line numbers to remove
        lines_to_remove = set()

        for import_stmt in imports:
            lines_to_remove.add(import_stmt.line_number - 1)  # Convert to 0-indexed

            # Also remove continuation lines for multi-line imports
            # This is a simplified approach; real implementation would need
            # to parse the actual line continuation

        # Keep lines not in the removal set
        cleaned_lines = [
            line for i, line in enumerate(lines) if i not in lines_to_remove
        ]

        # Also remove empty lines that were only for import separation
        cleaned_lines = self._clean_empty_lines(cleaned_lines)

        return "\n".join(cleaned_lines)

    def _clean_empty_lines(self, lines: List[str]) -> List[str]:
        """
        Clean up excessive empty lines.

        Parameters
        ----------
        lines : List[str]
            List of lines.

        Returns
        -------
        List[str]
            Cleaned list of lines.
        """
        cleaned = []
        consecutive_empty = 0

        for line in lines:
            if not line.strip():
                consecutive_empty += 1
                if consecutive_empty <= 2:  # Keep up to 2 consecutive empty lines
                    cleaned.append(line)
            else:
                consecutive_empty = 0
                cleaned.append(line)

        # Remove trailing empty lines
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()

        return cleaned

    def _combine_content(
        self, formatted_imports: List[str], non_import_content: str
    ) -> str:
        """
        Combine formatted imports with non-import content.

        Parameters
        ----------
        formatted_imports : List[str]
            Formatted import lines.
        non_import_content : str
            Content without imports.

        Returns
        -------
        str
            Combined content.
        """
        if not formatted_imports:
            return non_import_content.strip()

        # Build imports section
        imports_section = "\n".join(formatted_imports)

        # Clean non-import content
        non_import_lines = non_import_content.splitlines()

        # Remove leading empty lines from non-import content
        while non_import_lines and not non_import_lines[0].strip():
            non_import_lines.pop(0)

        non_import_section = "\n".join(non_import_lines)

        # Combine with appropriate spacing
        if non_import_section.strip():
            return f"{imports_section}\n\n{non_import_section}"
        else:
            return imports_section

    def check_file(self, filepath: str) -> Tuple[bool, List[str]]:
        """
        Check if imports in file are already sorted.

        Parameters
        ----------
        filepath : str
            Path to Python file.

        Returns
        -------
        Tuple[bool, List[str]]
            (is_sorted, list_of_issues)
        """
        try:
            content = Path(filepath).read_text(encoding="utf-8")
            imports = self.parser.parse_content(content, filepath)

            if not imports:
                return (True, [])

            # Organize imports
            sections = ImportSections()
            for import_stmt in imports:
                sections.add_statement(import_stmt)

            # Format imports properly
            formatted_imports = self.formatter.format_sections(sections)

            # Get current imports from file
            import_lines = []
            lines = content.splitlines()
            for import_stmt in imports:
                line_idx = import_stmt.line_number - 1
                if 0 <= line_idx < len(lines):
                    import_lines.append(lines[line_idx])

            # Compare
            issues = []
            if len(formatted_imports) != len(import_lines):
                issues.append("Number of import lines doesn't match")

            for i, (formatted, current) in enumerate(
                zip(formatted_imports, import_lines)
            ):
                if formatted.strip() != current.strip():
                    issues.append(f"Line {i+1}: '{current}' should be '{formatted}'")

            return (len(issues) == 0, issues)

        except Exception as e:
            return (False, [f"Error checking file: {e}"])
