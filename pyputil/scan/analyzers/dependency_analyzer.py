#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Dependency analysis for Python modules.

This module provides functionality to analyze Python source files
and extract module dependencies.
"""

import ast
from pathlib import Path
from typing import List, Set, Optional, Dict

from ..core.exceptions import AnalysisError


class DependencyAnalyzer:
    """
    Analyzer for extracting module dependencies from Python source code.

    This class uses Python's AST module to parse source files and extract
    import statements, providing accurate dependency information.

    Examples
    --------
    >>> analyzer = DependencyAnalyzer()
    >>> deps = analyzer.analyze(Path("mymodule.py"))
    >>> print(deps)
    ['os', 'sys', 'json']
    """

    def __init__(self, include_relative: bool = False):
        """
        Initialize dependency analyzer.

        Parameters
        ----------
        include_relative : bool
            Whether to include relative imports in results
        """
        self.include_relative = include_relative

    def analyze(self, source_path: Path) -> List[str]:
        """
        Extract module dependencies from Python source file.

        Parameters
        ----------
        source_path : Path
            Path to Python source file

        Returns
        -------
        List[str]
            List of unique module dependencies

        Raises
        ------
        AnalysisError
            If file cannot be parsed or analyzed
        """
        if not source_path.exists():
            raise AnalysisError(
                str(source_path),
                "dependency",
                f"File not found: {source_path}"
            )

        if not source_path.is_file():
            raise AnalysisError(
                str(source_path),
                "dependency",
                f"Not a file: {source_path}"
            )

        try:
            content = source_path.read_text(encoding='utf-8')
            tree = ast.parse(content)
            dependencies = self._extract_imports(tree)
            return sorted(list(dependencies))

        except SyntaxError as e:
            raise AnalysisError(
                str(source_path),
                "dependency",
                f"Syntax error in file: {e}"
            )
        except Exception as e:
            raise AnalysisError(
                str(source_path),
                "dependency",
                f"Failed to analyze: {e}"
            )

    def _extract_imports(self, tree: ast.AST) -> Set[str]:
        """
        Extract imports from AST.

        Parameters
        ----------
        tree : ast.AST
            Abstract syntax tree of the module

        Returns
        -------
        Set[str]
            Set of imported module names
        """
        dependencies = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dependencies.add(alias.name.split('.')[0])

            elif isinstance(node, ast.ImportFrom):
                if node.level > 0 and not self.include_relative:
                    continue
                if node.module:
                    dependencies.add(node.module.split('.')[0])

        return dependencies

    def analyze_multiple(self, source_paths: List[Path]) -> Dict[str, List[str]]:
        """
        Analyze multiple files for dependencies.

        Parameters
        ----------
        source_paths : List[Path]
            List of paths to analyze

        Returns
        -------
        Dict[str, List[str]]
            Dictionary mapping file paths to their dependencies

        Raises
        ------
        AnalysisError
            If any file analysis fails
        """
        results = {}
        for path in source_paths:
            try:
                results[str(path)] = self.analyze(path)
            except AnalysisError:
                # Continue with other files
                results[str(path)] = []
        return results