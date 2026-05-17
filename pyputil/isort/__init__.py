#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Import Sorter - A tool for organizing Python imports.

This package provides functionality to parse, organize, and format
import statements in Python files according to configurable rules.

Modules
-------
config : Configuration classes and constants.
models : Data models for import statements and sections.
parser : Import statement parser with regex and AST support.
formatter : Import statement formatter with multiple styles.
fixer : Import fixer files.
processor : Main processor coordinating the sorting workflow.

Examples
--------
>>> from pyputil.isort import ImportProcessor
>>> processor = ImportProcessor()
>>> success, message, imports = processor.process_file("example.py")
>>> print(message)
Successfully sorted imports in example.py
"""

from .config import ImportConfig, ImportType, DEFAULT_CONFIG
from .models import ImportStatement, ImportSections
from .parser import ImportParser
from .formatter import ImportFormatter
from .fixer import ImportFixer
from .processor import ImportProcessor


__all__ = [
    "ImportConfig",
    "ImportType",
    "ImportStatement",
    "ImportSections",
    "ImportParser",
    "ImportFormatter",
    "ImportFixer",
    "ImportProcessor",
    "DEFAULT_CONFIG",
]


from ..api import clean

clean(expose=__all__)
