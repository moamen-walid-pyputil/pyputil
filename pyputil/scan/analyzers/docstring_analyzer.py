#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Docstring analysis for Python modules.

This module provides functionality to detect and extract docstrings
from Python modules and functions.
"""

import ast
from pathlib import Path
from typing import Optional, Tuple, Dict

from ..core.exceptions import AnalysisError


class DocstringAnalyzer:
    """
    Analyzer for detecting and extracting docstrings from Python source files.

    This class analyzes Python source code to determine if modules, classes,
    or functions have docstrings and optionally extract them.

    Examples
    --------
    >>> analyzer = DocstringAnalyzer()
    >>> has_doc = analyzer.has_docstring(Path("mymodule.py"))
    >>> print(has_doc)
    True
    """

    def __init__(self, extract_content: bool = False):
        """
        Initialize docstring analyzer.

        Parameters
        ----------
        extract_content : bool
            Whether to extract docstring content (vs just detecting presence)
        """
        self.extract_content = extract_content

    def has_docstring(self, source_path: Path) -> bool:
        """
        Check if Python file has a module-level docstring.

        Parameters
        ----------
        source_path : Path
            Path to Python source file

        Returns
        -------
        bool
            True if file has a module-level docstring

        Raises
        ------
        AnalysisError
            If file cannot be parsed or analyzed
        """
        try:
            content = source_path.read_text(encoding='utf-8')
            tree = ast.parse(content)
            docstring = ast.get_docstring(tree)
            return docstring is not None

        except SyntaxError as e:
            raise AnalysisError(
                str(source_path),
                "docstring",
                f"Syntax error in file: {e}"
            )
        except Exception as e:
            raise AnalysisError(
                str(source_path),
                "docstring",
                f"Failed to analyze: {e}"
            )

    def extract_docstring(self, source_path: Path) -> Optional[str]:
        """
        Extract module-level docstring from Python file.

        Parameters
        ----------
        source_path : Path
            Path to Python source file

        Returns
        -------
        Optional[str]
            Docstring content if present, None otherwise

        Raises
        ------
        AnalysisError
            If file cannot be parsed or analyzed
        """
        try:
            content = source_path.read_text(encoding='utf-8')
            tree = ast.parse(content)
            return ast.get_docstring(tree)

        except SyntaxError as e:
            raise AnalysisError(
                str(source_path),
                "docstring",
                f"Syntax error in file: {e}"
            )
        except Exception as e:
            raise AnalysisError(
                str(source_path),
                "docstring",
                f"Failed to analyze: {e}"
            )

    def analyze_fully(self, source_path: Path) -> Dict[str, any]:
        """
        Perform comprehensive docstring analysis.

        Parameters
        ----------
        source_path : Path
            Path to Python source file

        Returns
        -------
        Dict[str, any]
            Dictionary with docstring analysis results including:
            - has_module_docstring: bool
            - module_docstring: Optional[str]
            - classes_with_docstrings: int
            - functions_with_docstrings: int

        Raises
        ------
        AnalysisError
            If file cannot be parsed or analyzed
        """
        try:
            content = source_path.read_text(encoding='utf-8')
            tree = ast.parse(content)

            result = {
                "has_module_docstring": False,
                "module_docstring": None,
                "classes_with_docstrings": 0,
                "functions_with_docstrings": 0,
                "total_classes": 0,
                "total_functions": 0,
            }

            # Module docstring
            module_doc = ast.get_docstring(tree)
            if module_doc:
                result["has_module_docstring"] = True
                if self.extract_content:
                    result["module_docstring"] = module_doc

            # Analyze classes and functions
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    result["total_classes"] += 1
                    if ast.get_docstring(node):
                        result["classes_with_docstrings"] += 1

                elif isinstance(node, ast.FunctionDef):
                    result["total_functions"] += 1
                    if ast.get_docstring(node):
                        result["functions_with_docstrings"] += 1

            return result

        except SyntaxError as e:
            raise AnalysisError(
                str(source_path),
                "docstring",
                f"Syntax error in file: {e}"
            )
        except Exception as e:
            raise AnalysisError(
                str(source_path),
                "docstring",
                f"Failed to analyze: {e}"
            )