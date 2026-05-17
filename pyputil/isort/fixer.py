#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Import fixer for import statement correction.

This module provides functions to detect and fix
common import-related issues in Python files.
"""

import re
import ast
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from .config import ImportConfig


STANDARD_LIB = ImportConfig().known_standard_library


@dataclass
class ImportIssue:
    """Represents a detected import issue."""

    line: int
    module: Optional[str] = None
    issue: Optional[str] = None
    duplicate_of: Optional[int] = None
    imports: List[int] = field(default_factory=list)
    count: Optional[int] = None
    message: Optional[str] = None


@dataclass
class ImportStatement:
    """Represents a parsed import statement."""

    type: str  # 'simple' or 'from'
    line_number: int
    indent: str
    module: str
    full_line: str
    raw_module: str
    is_multiline: bool = False
    imported_items: Optional[str] = None
    import_lines: List[str] = field(default_factory=list)


@dataclass
class ImportGroup:
    """Represents grouped import statements by category."""

    standard_simple: Dict[str, List[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    standard_from: Dict[str, List[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    third_party_simple: Dict[str, List[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    third_party_from: Dict[str, List[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    local_simple: Dict[str, List[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    local_from: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))


@dataclass
class FixResult:
    """Represents the result of fixing imports."""

    success: bool
    issues_found: int = 0
    issues: Dict[str, List[ImportIssue]] = field(default_factory=dict)
    error: Optional[str] = None


class ImportFixer:
    """
    Import statement fixer.

    Detects and fixes common import issues:
    1. Duplicate imports
    2. Incorrect indentation
    3. Multiple imports from same module in separate lines
    4. Mixed import styles
    5. Unorganized import sections
    """

    def __init__(self, filepath: str):
        """
        Initialize the import fixer for a specific file.

        Parameters
        ----------
        filepath : str
            Path to the Python file to fix.
        """
        self.filepath = filepath
        self.content = ""
        self.lines: List[str] = []
        self.import_statements: List[ImportStatement] = []
        self.non_import_lines: List[str] = []

        # Regex patterns for import detection
        self.patterns = {
            "simple_import": re.compile(r"^(\s*)import\s+([^#\n]+)(?:\s+#.*)?$"),
            "from_import": re.compile(
                r"^(\s*)from\s+([\w\.]+)\s+import\s+([^#\n]+)(?:\s+#.*)?$"
            ),
            "import_with_as": re.compile(
                r"^(\s*)import\s+([\w\.]+)\s+as\s+(\w+)(?:\s+#.*)?$"
            ),
            "continuation_line": re.compile(r"^(\s*)[\(\[].*|^\s+[^#\s].*"),
        }

    def load_file(self) -> bool:
        """
        Load the file content.

        Returns
        -------
        bool
            True if file loaded successfully, False otherwise.
        """
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self.content = f.read()
            self.lines = self.content.splitlines()
            return True
        except (IOError, UnicodeDecodeError):
            # Try with different encodings
            try:
                with open(self.filepath, "r", encoding="latin-1") as f:
                    self.content = f.read()
                self.lines = self.content.splitlines()
                return True
            except Exception:
                return False

    def init(self) -> None:
        """
         import statements in the file.

        Identifies all import statements and categorizes them.
        """
        self.import_statements = []
        self.non_import_lines = []

        i = 0
        while i < len(self.lines):
            line = self.lines[i]
            stripped = line.strip()

            # Skip empty lines and comments during initial scan
            if not stripped or stripped.startswith("#"):
                self.non_import_lines.append(line)
                i += 1
                continue

            # Check for simple import
            simple_match = self.patterns["simple_import"].match(line)
            if simple_match:
                indent = simple_match.group(1)
                import_part = simple_match.group(2).strip()

                # Handle multiple imports in one line
                if "," in import_part:
                    modules = [m.strip() for m in import_part.split(",")]
                    for module in modules:
                        if module:
                            self._add_import_statement(
                                ImportStatement(
                                    type="simple",
                                    line_number=i + 1,
                                    indent=indent,
                                    module=module.split()[0],  # Handle 'as' aliases
                                    full_line=line,
                                    raw_module=module,
                                )
                            )
                else:
                    self._add_import_statement(
                        ImportStatement(
                            type="simple",
                            line_number=i + 1,
                            indent=indent,
                            module=import_part.split()[0],
                            full_line=line,
                            raw_module=import_part,
                        )
                    )

                i += 1
                continue

            # Check for from import
            from_match = self.patterns["from_import"].match(line)
            if from_match:
                indent = from_match.group(1)
                module = from_match.group(2).strip()
                import_part = from_match.group(3).strip()

                # Check for multi-line import
                if import_part.startswith("(") or import_part.startswith("["):
                    # Multi-line import - collect continuation lines
                    import_lines = [line]
                    j = i + 1
                    while j < len(self.lines):
                        next_line = self.lines[j]
                        import_lines.append(next_line)
                        if ")" in next_line or "]" in next_line:
                            break
                        j += 1

                    full_import = "\n".join(import_lines)
                    self._add_import_statement(
                        ImportStatement(
                            type="from",
                            line_number=i + 1,
                            indent=indent,
                            module=module,
                            full_line=full_import,
                            raw_module=module,
                            is_multiline=True,
                            import_lines=import_lines,
                        )
                    )
                    i = j + 1
                else:
                    # Single line from import
                    self._add_import_statement(
                        ImportStatement(
                            type="from",
                            line_number=i + 1,
                            indent=indent,
                            module=module,
                            full_line=line,
                            raw_module=module,
                            imported_items=import_part,
                        )
                    )
                    i += 1
                continue

            # Not an import line
            self.non_import_lines.append(line)
            i += 1

    def _add_import_statement(self, import_stmt: ImportStatement) -> None:
        """
        Add an import statement to the analysis.

        Parameters
        ----------
        import_stmt : ImportStatement
            Import statement information.
        """
        self.import_statements.append(import_stmt)

    def detect_issues(self) -> Dict[str, List[ImportIssue]]:
        """
        Detect import-related issues in the file.

        Returns
        -------
        Dict[str, List[ImportIssue]]
            Dictionary of issues categorized by type.
        """
        issues = {
            "duplicate_imports": [],
            "incorrect_indentation": [],
            "multiple_same_module": [],
            "mixed_styles": [],
            "unorganized": [],
            "syntax_errors": [],
        }

        if not self.import_statements:
            return issues

        # Check for duplicate imports
        seen_modules = {}
        for imp in self.import_statements:
            module_key = f"{imp.module}_{imp.type}"
            if module_key in seen_modules:
                issues["duplicate_imports"].append(
                    ImportIssue(
                        line=imp.line_number,
                        module=imp.module,
                        duplicate_of=seen_modules[module_key],
                    )
                )
            else:
                seen_modules[module_key] = imp.line_number

        # Check indentation
        for imp in self.import_statements:
            if imp.indent and imp.indent[0] == "\t":
                issues["incorrect_indentation"].append(
                    ImportIssue(
                        line=imp.line_number, issue="Uses tabs instead of spaces"
                    )
                )
            elif len(imp.indent) % 4 != 0:
                issues["incorrect_indentation"].append(
                    ImportIssue(
                        line=imp.line_number,
                        issue=f"Indentation not multiple of 4: {len(imp.indent)} spaces",
                    )
                )

        # Check for multiple imports from same module
        module_counts = defaultdict(list)
        for imp in self.import_statements:
            if imp.type == "from":
                module_counts[imp.module].append(imp)

        for module, imports in module_counts.items():
            if len(imports) > 1:
                issues["multiple_same_module"].append(
                    ImportIssue(
                        module=module,
                        imports=[imp.line_number for imp in imports],
                        count=len(imports),
                    )
                )

        # Check for mixed import styles
        has_simple = any(imp.type == "simple" for imp in self.import_statements)
        has_from = any(imp.type == "from" for imp in self.import_statements)

        if has_simple and has_from:
            # This is normal, but check if they're mixed randomly
            simple_lines = [
                imp.line_number
                for imp in self.import_statements
                if imp.type == "simple"
            ]
            from_lines = [
                imp.line_number for imp in self.import_statements if imp.type == "from"
            ]

            if max(simple_lines) > min(from_lines):
                issues["mixed_styles"].append(
                    ImportIssue(
                        issue="Simple and from imports are mixed",
                        imports=simple_lines + from_lines,
                    )
                )

        # Check for syntax errors
        try:
            ast.parse(self.content)
        except SyntaxError as e:
            issues["syntax_errors"].append(ImportIssue(line=e.lineno, message=str(e)))

        return issues

    def fix_imports(self) -> str:
        """
        Fix all detected import issues.

        Returns
        -------
        str
            Fixed file content.
        """
        if not self.import_statements:
            return self.content

        # Group imports by type and module
        import_groups = self._group_imports()

        # Generate organized imports
        organized_imports = self._generate_organized_imports(import_groups)

        # Combine with non-import content
        fixed_content = self._combine_content(organized_imports)

        return fixed_content

    def _group_imports(self) -> ImportGroup:
        """
        Group imports by category and module.

        Returns
        -------
        ImportGroup
            Grouped import statements.
        """
        groups = ImportGroup()

        for imp in self.import_statements:
            module = imp.module

            # Determine category
            if module.startswith("."):
                category = "local"
            elif module in STANDARD_LIB:
                category = "standard"
            else:
                category = "third_party"

            # Determine type
            imp_type = "from" if imp.type == "from" else "simple"

            # Get the appropriate group
            group_dict = getattr(groups, f"{category}_{imp_type}")

            # Extract imported items for from imports
            if imp.type == "from" and imp.imported_items:
                items = [item.strip() for item in imp.imported_items.split(",")]
                group_dict[module].extend(items)
            elif imp.type == "simple":
                group_dict[module].append("*")  # Marker for simple import

        return groups

    def _generate_organized_imports(self, import_groups: ImportGroup) -> List[str]:
        """
        Generate organized import lines.

        Parameters
        ----------
        import_groups : ImportGroup
            Grouped import statements.

        Returns
        -------
        List[str]
            Organized import lines.
        """
        organized_lines = []

        # Order of sections
        sections = [
            ("standard_simple", "Standard Library - Simple Imports"),
            ("standard_from", "Standard Library - From Imports"),
            ("third_party_simple", "Third Party - Simple Imports"),
            ("third_party_from", "Third Party - From Imports"),
            ("local_simple", "Local - Simple Imports"),
            ("local_from", "Local - From Imports"),
        ]

        for section_key, section_name in sections:
            group_dict = getattr(import_groups, section_key)

            if group_dict:
                # Add section comment if there are imports
                organized_lines.append(f"# {section_name}")

                modules = sorted(group_dict.keys())

                for module in modules:
                    items = group_dict[module]

                    if "simple" in section_key:
                        # Simple imports
                        if "*" in items:  # Simple import of whole module
                            organized_lines.append(f"import {module}")
                        else:
                            # This shouldn't happen for simple imports
                            organized_lines.append(f"import {module}")
                    else:
                        # From imports
                        if items:
                            sorted_items = sorted(set(items))
                            if len(sorted_items) == 1:
                                organized_lines.append(
                                    f"from {module} import {sorted_items[0]}"
                                )
                            else:
                                # Multi-line for multiple items
                                organized_lines.append(f"from {module} import (")
                                for item in sorted_items[:-1]:
                                    organized_lines.append(f"    {item},")
                                organized_lines.append(f"    {sorted_items[-1]}")
                                organized_lines.append(")")

                organized_lines.append("")  # Empty line between sections

        # Remove trailing empty lines
        while organized_lines and organized_lines[-1] == "":
            organized_lines.pop()

        return organized_lines

    def _combine_content(self, organized_imports: List[str]) -> str:
        """
        Combine organized imports with non-import content.

        Parameters
        ----------
        organized_imports : List[str]
            Organized import lines.

        Returns
        -------
        str
            Complete fixed content.
        """
        # Get non-import content (skip original import lines)
        non_import_content = []
        import_line_numbers = {imp.line_number for imp in self.import_statements}

        for i, line in enumerate(self.lines):
            line_num = i + 1
            if line_num not in import_line_numbers:
                # Also skip continuation lines of multi-line imports
                is_continuation = False
                for imp in self.import_statements:
                    if imp.is_multiline:
                        start_line = imp.line_number
                        end_line = start_line + len(imp.import_lines) - 1
                        if start_line <= line_num <= end_line:
                            is_continuation = True
                            break

                if not is_continuation:
                    non_import_content.append(line)

        # Clean up leading empty lines in non-import content
        while non_import_content and non_import_content[0].strip() == "":
            non_import_content.pop(0)

        # Combine
        if organized_imports:
            combined = organized_imports + [""] + non_import_content
        else:
            combined = non_import_content

        return "\n".join(combined)

    def save_fixed_file(self) -> bool:
        """
        Save the fixed content to file.

        Returns
        -------
        bool
            True if saved successfully, False otherwise.
        """
        try:
            fixed_content = self.fix_imports()
            with open(self.filepath, "w", encoding="utf-8") as f:
                f.write(fixed_content)

            return True
        except Exception as e:
            return False
