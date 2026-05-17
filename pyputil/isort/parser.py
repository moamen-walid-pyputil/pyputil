#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Import statement parser module.

This module contains functions for parsing Python files
and extracting import statements with metadata.
"""

import re
import ast
from typing import List, Tuple, Optional, Set
from pathlib import Path
from .config import ImportType, ImportConfig
from .models import ImportStatement


class ImportParser:
    """
    Parser for extracting import statements from Python code.

    This class uses both regex and AST parsing to accurately
    identify and extract import statements with their metadata.

    Parameters
    ----------
    config : ImportConfig
        Configuration object for import classification.
    """

    def __init__(self, config: ImportConfig):
        """
        Initialize the import parser.

        Parameters
        ----------
        config : ImportConfig
            Configuration object.
        """
        self.config = config

        # Regex patterns for different import styles
        self.import_patterns = {
            "simple_import": re.compile(r"^(\s*)import\s+([^#\n]+)"),
            "from_import": re.compile(r"^(\s*)from\s+([^\s]+)\s+import\s+([^#\n]+)"),
            "comment": re.compile(r"#.*$"),
        }

    def parse_file(self, filepath: str) -> List[ImportStatement]:
        """
        Parse a Python file and extract all import statements.

        Parameters
        ----------
        filepath : str
            Path to the Python file to parse.

        Returns
        -------
        List[ImportStatement]
            List of extracted import statements.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        SyntaxError
            If the file contains syntax errors.
        """
        try:
            content = Path(filepath).read_text(encoding="utf-8")
            return self.parse_content(content, filepath)
        except UnicodeDecodeError:
            # Try with different encoding
            content = Path(filepath).read_text(encoding="latin-1")
            return self.parse_content(content, filepath)

    def parse_content(self, content: str, filepath: str = "") -> List[ImportStatement]:
        """
        Parse Python code content and extract import statements.

        Parameters
        ----------
        content : str
            Python code content.
        filepath : str, optional
            Original filepath (used for relative imports).

        Returns
        -------
        List[ImportStatement]
            List of extracted import statements.
        """
        import_statements = []

        # Parse with AST for accurate structure
        ast_imports = self._parse_with_ast(content, filepath)

        # Also parse with regex for line numbers and comments
        regex_imports = self._parse_with_regex(content, filepath)

        # Merge results, preferring AST for structure, regex for metadata
        for ast_import in ast_imports:
            # Find matching regex import
            matching_regex = None
            for regex_import in regex_imports:
                if (
                    regex_import.line_number == ast_import.line_number
                    and regex_import.module == ast_import.module
                ):
                    matching_regex = regex_import
                    break

            if matching_regex:
                # Merge comments and indentation from regex
                ast_import.comments = matching_regex.comments
                ast_import.indent = matching_regex.indent
                import_statements.append(ast_import)
            else:
                import_statements.append(ast_import)

        return import_statements

    def _parse_with_ast(self, content: str, filepath: str) -> List[ImportStatement]:
        """
        Parse imports using Python's AST module.

        Parameters
        ----------
        content : str
            Python code content.
        filepath : str
            Original filepath.

        Returns
        -------
        List[ImportStatement]
            List of import statements parsed from AST.
        """
        imports = []

        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    import_stmt = self._parse_ast_node(node, filepath)
                    if import_stmt:
                        imports.append(import_stmt)

        except SyntaxError as e:
            # Fall back to regex parsing for files with syntax errors
            return self._parse_with_regex(content, filepath)

        return imports

    def _parse_ast_node(self, node, filepath: str) -> Optional[ImportStatement]:
        """
        Parse a single AST import node.

        Parameters
        ----------
        node : ast.Import or ast.ImportFrom
            AST node representing import.
        filepath : str
            Original filepath.

        Returns
        -------
        Optional[ImportStatement]
            Parsed import statement or None if invalid.
        """
        try:
            # Get line number (1-indexed in files, 0-indexed in AST)
            line_number = node.lineno if hasattr(node, "lineno") else 0

            if isinstance(node, ast.Import):
                # Simple import: import module [as alias]
                for alias in node.names:
                    module = alias.name
                    import_type = self._classify_import(module, filepath)

                    return ImportStatement(
                        raw_statement=(
                            ast.unparse(node)
                            if hasattr(ast, "unparse")
                            else f"import {module}"
                        ),
                        line_number=line_number,
                        import_type=import_type,
                        module=module,
                        is_from_import=False,
                        alias=alias.asname,
                        indent="",
                    )

            elif isinstance(node, ast.ImportFrom):
                # From import: from module import names
                module = node.module or ""
                import_type = self._classify_import(module, filepath, is_from=True)

                names = []
                for alias in node.names:
                    name = alias.name
                    if alias.asname:
                        name = f"{alias.name} as {alias.asname}"
                    names.append(name)

                return ImportStatement(
                    raw_statement=(
                        ast.unparse(node)
                        if hasattr(ast, "unparse")
                        else f"from {module} import {', '.join(names)}"
                    ),
                    line_number=line_number,
                    import_type=import_type,
                    module=module,
                    is_from_import=True,
                    names=names,
                    indent="",
                )

        except (AttributeError, TypeError):
            pass

        return None

    def _parse_with_regex(self, content: str, filepath: str) -> List[ImportStatement]:
        """
        Parse imports using regex patterns.

        Parameters
        ----------
        content : str
            Python code content.
        filepath : str
            Original filepath.

        Returns
        -------
        List[ImportStatement]
            List of import statements parsed with regex.
        """
        imports = []
        lines = content.splitlines()

        for i, line in enumerate(lines, 1):  # 1-indexed line numbers
            line = line.rstrip()

            # Skip empty lines and comments
            if not line.strip() or line.strip().startswith("#"):
                continue

            # Try to match import patterns
            import_stmt = self._parse_line_with_regex(line, i, filepath)
            if import_stmt:
                imports.append(import_stmt)

        return imports

    def _parse_line_with_regex(
        self, line: str, line_number: int, filepath: str
    ) -> Optional[ImportStatement]:
        """
        Parse a single line for import statements using regex.

        Parameters
        ----------
        line : str
            Line of Python code.
        line_number : int
            Line number in file.
        filepath : str
            Original filepath.

        Returns
        -------
        Optional[ImportStatement]
            Parsed import statement or None if not an import.
        """
        # Remove inline comments
        clean_line = self.import_patterns["comment"].sub("", line).strip()

        # Match simple import
        simple_match = self.import_patterns["simple_import"].match(line)
        if simple_match:
            indent = simple_match.group(1)
            import_part = simple_match.group(2).strip()

            # Parse module and alias
            if " as " in import_part:
                module, alias = import_part.split(" as ", 1)
                module = module.strip()
                alias = alias.strip()
            else:
                module = import_part
                alias = None

            import_type = self._classify_import(module, filepath)

            return ImportStatement(
                raw_statement=line.strip(),
                line_number=line_number,
                import_type=import_type,
                module=module,
                is_from_import=False,
                alias=alias,
                indent=indent,
                comments=self._extract_comments(line),
            )

        # Match from import
        from_match = self.import_patterns["from_import"].match(line)
        if from_match:
            indent = from_match.group(1)
            module = from_match.group(2).strip()
            import_part = from_match.group(3).strip()

            # Parse imported names
            names = []
            current_name = ""
            paren_level = 0
            in_quotes = False

            for char in import_part:
                if char in "'\"":
                    in_quotes = not in_quotes
                elif not in_quotes:
                    if char == "(":
                        paren_level += 1
                    elif char == ")":
                        paren_level -= 1
                    elif char == "," and paren_level == 0:
                        if current_name.strip():
                            names.append(current_name.strip())
                        current_name = ""
                        continue

                current_name += char

            if current_name.strip():
                names.append(current_name.strip())

            import_type = self._classify_import(module, filepath, is_from=True)

            return ImportStatement(
                raw_statement=line.strip(),
                line_number=line_number,
                import_type=import_type,
                module=module,
                is_from_import=True,
                names=names,
                indent=indent,
                comments=self._extract_comments(line),
            )

        return None

    def _classify_import(
        self, module: str, filepath: str, is_from: bool = False
    ) -> ImportType:
        """
        Classify an import into a specific category.

        Parameters
        ----------
        module : str
            Module name being imported.
        filepath : str
            Path to the file containing the import.
        is_from : bool, optional
            Whether this is a 'from ... import ...' statement.

        Returns
        -------
        ImportType
            Category of the import.
        """
        # Check for __future__ imports
        if module == "__future__":
            return ImportType.FUTURE

        # Check for relative/local imports
        if module.startswith("."):
            return ImportType.LOCAL

        # Check standard library
        if module in self.config.known_standard_library:
            return ImportType.STANDARD

        # Check first party (current project)
        if module in self.config.known_first_party:
            return ImportType.FIRST_PARTY

        # Try to determine first party from filepath
        if filepath:
            project_root = self._find_project_root(filepath)
            if project_root:
                # Check if module is in project directory
                try:
                    module_path = self._resolve_module_path(module, project_root)
                    if module_path and module_path.exists():
                        return ImportType.FIRST_PARTY
                except (ImportError, ValueError):
                    pass

        # Check third party
        if module in self.config.known_third_party:
            return ImportType.THIRD_PARTY

        # Default to third party for unknown modules
        return ImportType.THIRD_PARTY

    def _find_project_root(self, filepath: str) -> Optional[Path]:
        """
        Find the project root directory.

        Parameters
        ----------
        filepath : str
            Path to a file in the project.

        Returns
        -------
        Optional[Path]
            Path to project root or None if not found.
        """
        current = Path(filepath).parent
        markers = [
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "requirements.txt",
            ".git",
            ".hg",
        ]

        while current != current.parent:  # Stop at root
            for marker in markers:
                if (current / marker).exists():
                    return current
            current = current.parent

        return None

    def _resolve_module_path(self, module: str, project_root: Path) -> Optional[Path]:
        """
        Resolve module name to filesystem path.

        Parameters
        ----------
        module : str
            Module name.
        project_root : Path
            Project root directory.

        Returns
        -------
        Optional[Path]
            Resolved path or None if not found.
        """
        # Convert module dots to path separators
        module_path = module.replace(".", "/")

        # Try different file extensions
        for ext in [".py", "/__init__.py"]:
            candidate = project_root / (module_path + ext)
            if candidate.exists():
                return candidate

        return None

    def _extract_comments(self, line: str) -> List[str]:
        """
        Extract comments from a line of code.

        Parameters
        ----------
        line : str
            Line of Python code.

        Returns
        -------
        List[str]
            List of comment strings.
        """
        comments = []
        in_string = False
        string_char = None
        comment_start = -1

        for i, char in enumerate(line):
            if char in "'\"" and (i == 0 or line[i - 1] != "\\"):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
            elif char == "#" and not in_string:
                comment_start = i
                break

        if comment_start != -1:
            comment = line[comment_start:].strip()
            if comment:
                comments.append(comment)

        return comments
