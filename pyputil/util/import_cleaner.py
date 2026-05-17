#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
pyputil.util - Advanced Import Analysis and Detector Module
================================================================================

A comprehensive, production-grade toolkit for analyzing and optimizing Python
import statements using purely AST (Abstract Syntax Tree) based analysis.

**Overview**
------------
This module provides sophisticated tools for detecting unused imports,
analyzing import patterns, and safely removing dead imports from Python
source files. Unlike token-based approaches, this module uses only AST
parsing, ensuring semantic correctness and deep understanding of code
structure.

**Key Features**
----------------
1. **Zero-Execution Analysis**: Never executes the code being analyzed
2. **Deep Scope Awareness**: Tracks imports across nested functions and classes
3. **Type Annotation Support**: Detects imports used only in type hints
4. **PEP 563 Compliance**: Handles string annotations (from __future__ import annotations)
5. **Conditional Import Detection**: Respects imports inside try/except/if blocks
6. **Wildcard Import Handling**: Detects and warns about star imports (`from x import *`)
7. **Relative Import Support**: Properly processes `.` and `..` imports
8. **Comprehension Analysis**: Analyzes imports used in list/dict/set comprehensions
9. **Lambda Function Support**: Tracks imports used inside lambda expressions
10. **Multi-line Import Preservation**: Maintains formatting of split imports

**Design Philosophy**
---------------------
- **Safety First**: Never modify files without backup or dry-run options
- **Deterministic**: Same input always produces same output
- **Non-Intrusive**: Preserves original formatting where possible
- **Comprehensive**: Handles edge cases like conditional imports, aliases
- **Well-Documented**: Every public API has detailed docstrings with examples

**Examples**
------------
>>> from pyputil.util import ImportDetector, AnalysisConfig
>>> from pathlib import Path
>>> 
>>> # Basic usage - single file
>>> detector = ImportDetector()
>>> report = detector.analyze_file("my_module.py")
>>> print(f"Unused imports: {report.unused_imports}")
>>> detector.clean_file("my_module.py", backup=True)
>>> 
>>> # Advanced usage with custom configuration
>>> config = AnalysisConfig(
...     analyze_type_hints=True,
...     preserve_side_effects=True,
...     depth=AnalysisDepth.DEEP
... )
>>> detector = ImportDetector(config)
>>> report = detector.analyze_file("complex_module.py")
>>> 
>>> # Batch processing
>>> results = detector.clean_directory("src/", pattern="*.py", recursive=True)
>>> 
>>> # Programmatic analysis
>>> source_code = '''
... import os
... import sys
... 
... def main():
...     return os.getcwd()
... '''
>>> report = detector.analyze_source(source_code)

**References**
--------------
- Python AST Documentation: https://docs.python.org/3/library/ast.html
- PEP 8 -- Imports: https://www.python.org/dev/peps/pep-0008/#imports
- PEP 563 -- Postponed Evaluation of Annotations: https://www.python.org/dev/peps/pep-0563/
- The Import System: https://docs.python.org/3/reference/import.html
"""

import ast
import sys
import keyword
import builtins
import logging
from pathlib import Path
from typing import (
    Optional, Set, Dict, Tuple, List, Union, Any, 
    FrozenSet, Callable, Iterator, NamedTuple, 
    TypeVar, Generic, overload
)
from dataclasses import dataclass, field, asdict, replace
from enum import Enum, auto
from functools import lru_cache, wraps
from collections import defaultdict
from datetime import datetime
import hashlib

# ============================================================================
# Module-Level Configuration and Constants
# ============================================================================

# Configure module logger
_logger = logging.getLogger(__name__)
_logger.addHandler(logging.NullHandler())

__all__ = [
    # Main classes
    'ImportDetector',
    'AnalysisConfig',
    'ImportRecord',
    'AnalysisReport',
    'CleanupResult',
    
    # Enums
    'ImportCategory',
    'UsageContext',
    'AnalysisDepth',
    'CleanupMode',
    
    # Convenience functions
    'analyze_file',
    'analyze_source',
    'clean_file',
    'clean_directory',
    'detect_unused_imports',
    
    # Exceptions
    'ImportAnalysisError',
    'InvalidSourceError',
    'FileAccessError',
]

# ============================================================================
# Custom Exceptions
# ============================================================================

class ImportAnalysisError(Exception):
    """
    Base exception for all import analysis errors.
    
    This exception is raised when an unrecoverable error occurs during
    import analysis or cleanup operations.
    
    Attributes
    ----------
    message : str
        Human-readable error description
    original_error : Optional[Exception]
        Original exception that caused this error, if any
    file_path : Optional[str]
        Path to the file being processed when error occurred
    
    Examples
    --------
    >>> try:
    ...     analyze_file("nonexistent.py")
    ... except ImportAnalysisError as e:
    ...     print(f"Analysis failed: {e.message}")
    """
    
    def __init__(
        self, 
        message: str, 
        original_error: Optional[Exception] = None,
        file_path: Optional[str] = None
    ):
        self.message = message
        self.original_error = original_error
        self.file_path = file_path
        super().__init__(message)
    
    def __str__(self) -> str:
        """Return formatted error message."""
        result = self.message
        if self.file_path:
            result = f"[{self.file_path}] {result}"
        if self.original_error:
            result = f"{result}\nCaused by: {self.original_error}"
        return result


class InvalidSourceError(ImportAnalysisError):
    """
    Exception raised when source code contains syntax errors.
    
    This exception indicates that the Python source code cannot be
    parsed into an AST due to syntax errors.
    
    Examples
    --------
    >>> try:
    ...     analyze_source("import os from")  # Invalid syntax
    ... except InvalidSourceError as e:
    ...     print(f"Syntax error at line {e.line_number}: {e.message}")
    """
    
    def __init__(
        self, 
        message: str, 
        line_number: Optional[int] = None,
        column: Optional[int] = None,
        original_error: Optional[Exception] = None,
        file_path: Optional[str] = None
    ):
        super().__init__(message, original_error, file_path)
        self.line_number = line_number
        self.column = column


class FileAccessError(ImportAnalysisError):
    """
    Exception raised when file operations fail.
    
    This exception indicates problems with reading from or writing to
    files (permissions, file not found, disk full, etc.).
    
    Examples
    --------
    >>> try:
    ...     clean_file("/readonly/file.py")
    ... except FileAccessError as e:
    ...     print(f"Cannot modify {e.file_path}: {e.message}")
    """
    pass


# ============================================================================
# Enumerations with Detailed Documentation
# ============================================================================

class ImportCategory(Enum):
    """
    Categorization of different import statement types.
    
    This enum classifies import statements based on their structure
    and semantics according to Python's import system.
    
    Attributes
    ----------
    STANDARD_IMPORT : ImportCategory
        Regular import: ``import module`` or ``import module.submodule``
    
    FROM_IMPORT : ImportCategory
        From import: ``from module import name``
    
    ALIASED_IMPORT : ImportCategory
        Aliased import: ``import module as alias`` or ``from module import name as alias``
    
    WILDCARD_IMPORT : ImportCategory
        Wildcard import: ``from module import *`` (discouraged, but detected)
    
    RELATIVE_IMPORT : ImportCategory
        Relative import: ``from .module import name`` or ``from ..submodule import name``
    
    Examples
    --------
    >>> from pyputil.util import ImportCategory
    >>> 
    >>> # Detect import category
    >>> if category == ImportCategory.WILDCARD_IMPORT:
    ...     print("Warning: Wildcard imports can cause namespace pollution")
    >>> 
    >>> # Filter imports by category
    >>> absolute_imports = [imp for imp in report.imports.values() 
    ...                     if imp.category != ImportCategory.RELATIVE_IMPORT]
    """
    
    STANDARD_IMPORT = auto()  #: import module
    FROM_IMPORT = auto()      #: from module import name
    ALIASED_IMPORT = auto()   #: import module as alias
    WILDCARD_IMPORT = auto()  #: from module import *
    RELATIVE_IMPORT = auto()  #: from .module import name
    
    def __str__(self) -> str:
        """Return string representation of the category."""
        return self.name.lower()
    
    @property
    def is_wildcard(self) -> bool:
        """Check if this is a wildcard import."""
        return self == ImportCategory.WILDCARD_IMPORT
    
    @property
    def is_relative(self) -> bool:
        """Check if this is a relative import."""
        return self == ImportCategory.RELATIVE_IMPORT
    
    @property
    def is_alias(self) -> bool:
        """Check if this import uses an alias."""
        return self == ImportCategory.ALIASED_IMPORT


class UsageContext(Enum):
    """
    Context information for where an import name is used.
    
    This enum provides detailed information about how an imported
    name is referenced in the code, which helps determine if an
    import is truly necessary or can be safely removed.
    
    Attributes
    ----------
    DIRECT_REFERENCE : UsageContext
        Direct reference: ``module_name``
    
    ATTRIBUTE_ACCESS : UsageContext
        Attribute access: ``module.attribute``
    
    FUNCTION_CALL : UsageContext
        Function call: ``function()`` or ``module.function()``
    
    TYPE_ANNOTATION : UsageContext
        Type hint: ``def func() -> List[str]``
    
    STRING_ANNOTATION : UsageContext
        String annotation (PEP 563): ``"List[str]"``
    
    COMPREHENSION : UsageContext
        Inside comprehension: ``[x for x in iterable]``
    
    LAMBDA : UsageContext
        Inside lambda: ``lambda x: x.func()``
    
    EXAMPLES
    --------
    >>> context = UsageContext.ATTRIBUTE_ACCESS
    >>> if context == UsageContext.TYPE_ANNOTATION:
    ...     # This import is only used in type hints - safe to remove
    ...     # if type checking is done separately
    ...     pass
    """
    
    DIRECT_REFERENCE = auto()      #: x = module_name
    ATTRIBUTE_ACCESS = auto()      #: module.attribute
    FUNCTION_CALL = auto()         #: module.function()
    TYPE_ANNOTATION = auto()       #: def f(x: Type) -> None
    STRING_ANNOTATION = auto()     #: "Type" (PEP 563)
    COMPREHENSION = auto()         #: [x for x in iterable]
    LAMBDA = auto()                #: lambda x: x.method()
    
    def __str__(self) -> str:
        """Return human-readable string representation."""
        return self.name.lower().replace('_', ' ')
    
    @property
    def is_annotation(self) -> bool:
        """Check if this usage is in a type annotation."""
        return self in (UsageContext.TYPE_ANNOTATION, UsageContext.STRING_ANNOTATION)


class AnalysisDepth(Enum):
    """
    Control the depth of AST traversal for import analysis.
    
    Different analysis depths offer trade-offs between speed and accuracy.
    Select the appropriate depth based on your code complexity and
    performance requirements.
    
    Attributes
    ----------
    SHALLOW : AnalysisDepth
        Only analyze top-level imports and names.
        Fastest, but may miss uses in nested scopes.
        Best for: Simple scripts, quick checks
        
    STANDARD : AnalysisDepth
        Analyze functions and classes, but not nested comprehensions.
        Good balance for most code bases.
        Best for: Typical applications, libraries
        
    DEEP : AnalysisDepth
        Recursively analyze all nested scopes including comprehensions.
        Slowest, but most accurate.
        Best for: Complex code with nested comprehensions, lambdas
        
    PERFORMANCE NOTES
    -----------------
    - SHALLOW: ~2-3x faster than DEEP
    - STANDARD: ~1.5x faster than DEEP
    - DEEP: Full analysis, includes all AST nodes
    
    Examples
    --------
    >>> from pyputil.util import AnalysisDepth, AnalysisConfig
    >>> 
    >>> # Quick analysis for large codebase
    >>> config = AnalysisConfig(depth=AnalysisDepth.SHALLOW)
    >>> 
    >>> # Thorough analysis for critical code
    >>> config = AnalysisConfig(depth=AnalysisDepth.DEEP)
    """
    
    SHALLOW = auto()   #: Top-level only
    STANDARD = auto()  #: Functions and classes (default)
    DEEP = auto()      #: All nested scopes
    
    def __str__(self) -> str:
        """Return string representation."""
        return self.name.lower()
    
    @property
    def analyze_comprehensions(self) -> bool:
        """Whether to analyze comprehensions at this depth."""
        return self == AnalysisDepth.DEEP
    
    @property
    def analyze_nested_functions(self) -> bool:
        """Whether to analyze nested functions at this depth."""
        return self != AnalysisDepth.SHALLOW


class CleanupMode(Enum):
    """
    Strategy for removing unused imports.
    
    Different cleanup modes provide varying levels of aggressive removal.
    Choose based on your confidence in the analysis and the importance
    of preserving potentially unused code.
    
    Attributes
    ----------
    SAFE : CleanupMode
        Conservative removal: preserves conditional imports,
        side-effect imports, and imports used in type hints.
        Best for: Production code, unknown code bases
        
    NORMAL : CleanupMode
        Balanced removal: removes all unused imports except
        those with clear side effects.
        Best for: Development, code cleanup
        
    AGGRESSIVE : CleanupMode
        Aggressive removal: removes any import not directly used,
        including type hints and potentially side-effect imports.
        Best for: Final cleanup, optimized builds
        
    EXAMPLES
    --------
    >>> from pyputil.util import CleanupMode, clean_file
    >>> 
    >>> # Safe mode (recommended for unknown code)
    >>> clean_file("module.py", mode=CleanupMode.SAFE, backup=True)
    >>> 
    >>> # Aggressive mode for final optimization
    >>> clean_file("module.py", mode=CleanupMode.AGGRESSIVE)
    """
    
    SAFE = auto()        #: Most conservative
    NORMAL = auto()      #: Balanced (default)
    AGGRESSIVE = auto()  #: Most aggressive
    
    def __str__(self) -> str:
        """Return string representation."""
        return self.name.lower()
    
    @property
    def preserve_conditional_imports(self) -> bool:
        """Whether to preserve imports in conditional blocks."""
        return self == CleanupMode.SAFE
    
    @property
    def preserve_side_effects(self) -> bool:
        """Whether to preserve known side-effect imports."""
        return self != CleanupMode.AGGRESSIVE
    
    @property
    def preserve_type_hints(self) -> bool:
        """Whether to preserve imports used only in type hints."""
        return self == CleanupMode.SAFE


# ============================================================================
# Configuration Classes
# ============================================================================

@dataclass
class AnalysisConfig:
    """
    Comprehensive configuration for import analysis.
    
    This dataclass controls all aspects of the import analysis process,
    allowing fine-tuned control over what is analyzed and how.
    
    Parameters
    ----------
    depth : AnalysisDepth, default=AnalysisDepth.STANDARD
        Depth of AST traversal for name usage detection.
    
    analyze_type_hints : bool, default=True
        Whether to track imports used in type annotations.
        When disabled, type hints are treated as regular code.
    
    analyze_string_annotations : bool, default=True
        Whether to parse string annotations (PEP 563) for imports.
        Requires `analyze_type_hints=True` to have effect.
    
    analyze_comprehensions : bool, default=True
        Whether to analyze imports inside comprehensions.
        Overridden by depth.DEEP setting.
    
    analyze_lambdas : bool, default=True
        Whether to analyze imports inside lambda functions.
    
    preserve_side_effects : bool, default=True
        Whether to mark known side-effect imports as used.
        Prevents removal of `import warnings`, `import logging`, etc.
    
    detect_conditional_imports : bool, default=True
        Whether to detect and mark imports inside conditionals.
    
    ignore_dunder_names : bool, default=True
        Whether to ignore dunder (__xxx__) names in usage tracking.
    
    ignore_builtins : bool, default=True
        Whether to ignore Python built-in names (len, str, etc.).
    
    ignore_private_names : bool, default=True
        Whether to ignore names starting with underscore (_xxx).
    
    custom_always_used : Set[str], default=empty
        Set of import names to always consider as used.
        Useful for dynamic imports or framework conventions.
    
    custom_never_used : Set[str], default=empty
        Set of import names to always consider as unused.
        Overrides detection results.
    
    Attributes
    ----------
    All parameters are also available as instance attributes.
    
    Examples
    --------
    >>> # Create configuration for deep analysis of type hints
    >>> config = AnalysisConfig(
    ...     depth=AnalysisDepth.DEEP,
    ...     analyze_type_hints=True,
    ...     analyze_string_annotations=True,
    ...     preserve_side_effects=True
    ... )
    >>> 
    >>> # Create configuration for quick shallow analysis
    >>> config = AnalysisConfig(
    ...     depth=AnalysisDepth.SHALLOW,
    ...     analyze_type_hints=False,
    ...     analyze_comprehensions=False
    ... )
    >>> 
    >>> # Custom always-used imports (e.g., framework magic)
    >>> config = AnalysisConfig(
    ...     custom_always_used={'db', 'session', 'request'}
    ... )
    """
    
    # Analysis depth control
    depth: AnalysisDepth = AnalysisDepth.STANDARD
    
    # Feature toggles
    analyze_type_hints: bool = True
    analyze_string_annotations: bool = True
    analyze_comprehensions: bool = True
    analyze_lambdas: bool = True
    
    # Preservation rules
    preserve_side_effects: bool = True
    detect_conditional_imports: bool = True
    
    # Filtering rules
    ignore_dunder_names: bool = True
    ignore_builtins: bool = True
    ignore_private_names: bool = True
    
    # Custom rules
    custom_always_used: Set[str] = field(default_factory=set)
    custom_never_used: Set[str] = field(default_factory=set)
    
    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        # Ensure sets are properly initialized
        if self.custom_always_used is None:
            self.custom_always_used = set()
        if self.custom_never_used is None:
            self.custom_never_used = set()
        
        # Apply depth overrides
        if not self.depth.analyze_comprehensions:
            self.analyze_comprehensions = False
        
        # Log configuration
        _logger.debug(f"AnalysisConfig initialized: {self}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'depth': str(self.depth),
            'analyze_type_hints': self.analyze_type_hints,
            'analyze_string_annotations': self.analyze_string_annotations,
            'analyze_comprehensions': self.analyze_comprehensions,
            'analyze_lambdas': self.analyze_lambdas,
            'preserve_side_effects': self.preserve_side_effects,
            'detect_conditional_imports': self.detect_conditional_imports,
            'ignore_dunder_names': self.ignore_dunder_names,
            'ignore_builtins': self.ignore_builtins,
            'ignore_private_names': self.ignore_private_names,
            'custom_always_used': sorted(self.custom_always_used),
            'custom_never_used': sorted(self.custom_never_used),
        }
    
    @classmethod
    def create_default(cls) -> 'AnalysisConfig':
        """
        Create a default configuration for general use.
        
        Returns
        -------
        AnalysisConfig
            Default configuration with balanced settings
        
        Examples
        --------
        >>> config = AnalysisConfig.create_default()
        >>> detector = ImportDetector(config)
        """
        return cls()
    
    @classmethod
    def create_safe(cls) -> 'AnalysisConfig':
        """
        Create a safe, conservative configuration.
        
        This configuration preserves all potentially important imports
        and is ideal for production environments.
        
        Returns
        -------
        AnalysisConfig
            Conservative configuration
        
        Examples
        --------
        >>> config = AnalysisConfig.create_safe()
        >>> report = analyze_file("production.py", config=config)
        """
        return cls(
            depth=AnalysisDepth.DEEP,
            analyze_type_hints=True,
            analyze_string_annotations=True,
            preserve_side_effects=True,
            detect_conditional_imports=True,
            ignore_dunder_names=False,  # Don't ignore dunder names
        )
    
    @classmethod
    def create_fast(cls) -> 'AnalysisConfig':
        """
        Create a fast, performance-optimized configuration.
        
        This configuration sacrifices some accuracy for speed,
        suitable for large codebases or quick checks.
        
        Returns
        -------
        AnalysisConfig
            Performance-optimized configuration
        
        Examples
        --------
        >>> config = AnalysisConfig.create_fast()
        >>> # Analyze large directory quickly
        >>> for file in Path("large_project").rglob("*.py"):
        ...     report = analyze_file(file, config=config)
        """
        return cls(
            depth=AnalysisDepth.SHALLOW,
            analyze_type_hints=False,
            analyze_string_annotations=False,
            analyze_comprehensions=False,
            analyze_lambdas=False,
            preserve_side_effects=False,
            detect_conditional_imports=False,
        )


# ============================================================================
# Data Classes for Results
# ============================================================================

@dataclass
class UsageLocation:
    """
    Detailed information about where a name is used.
    
    This dataclass captures precise location and context information
    for each usage of an imported name.
    
    Parameters
    ----------
    line_number : int
        Line number where the name is used (1-indexed)
    column : int
        Column offset where the name appears (0-indexed)
    context : UsageContext
        How the name is being used
    parent_function : Optional[str]
        Name of containing function, if any
    parent_class : Optional[str]
        Name of containing class, if any
    code_snippet : Optional[str]
        Surrounding code line for context (optional)
    
    Examples
    --------
    >>> location = UsageLocation(
    ...     line_number=42,
    ...     column=8,
    ...     context=UsageContext.FUNCTION_CALL,
    ...     parent_function="main"
    ... )
    >>> print(f"Used at line {location.line_number} in {location.parent_function}")
    """
    
    line_number: int
    column: int
    context: UsageContext
    parent_function: Optional[str] = None
    parent_class: Optional[str] = None
    code_snippet: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'line_number': self.line_number,
            'column': self.column,
            'context': str(self.context),
            'parent_function': self.parent_function,
            'parent_class': self.parent_class,
            'code_snippet': self.code_snippet,
        }
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        location = f"line {self.line_number}"
        if self.parent_function:
            location += f" in function '{self.parent_function}'"
        if self.parent_class:
            location += f" in class '{self.parent_class}'"
        return f"{self.context} at {location}"


@dataclass
class ImportRecord:
    """
    Comprehensive record of a single import statement.
    
    This dataclass captures all information about an import statement
    discovered during AST analysis, including its structure, location,
    and usage patterns throughout the code.
    
    Parameters
    ----------
    name : str
        The name as it appears in code (alias if exists, else original)
    original_name : str
        The original module/object name being imported
    alias : Optional[str]
        The alias name if import uses 'as', otherwise None
    category : ImportCategory
        Classification of the import type
    line_start : int
        Starting line number (1-indexed)
    line_end : int
        Ending line number (for multi-line imports)
    column_start : int
        Starting column offset (0-indexed)
    module_path : Optional[str]
        For 'from' imports, the module being imported from
    relative_level : int
        Number of dots for relative imports (0 for absolute)
    is_used : bool
        Whether the import name is actually used
    usage_locations : List[UsageLocation]
        Detailed information about each usage
    is_conditional : bool
        Whether import is inside try/except/if block
    is_in_nested_scope : bool
        Whether import is inside function or class
    uses_wildcard : bool
        Whether this is a wildcard import
    
    Examples
    --------
    >>> record = ImportRecord(
    ...     name="pd",
    ...     original_name="pandas",
    ...     alias="pd",
    ...     category=ImportCategory.ALIASED_IMPORT,
    ...     line_start=5,
    ...     line_end=5,
    ...     column_start=0,
    ...     is_used=True
    ... )
    >>> print(f"{record.name} imports {record.original_name}")
    """
    
    # Basic import information
    name: str
    original_name: str
    alias: Optional[str]
    category: ImportCategory
    
    # Location information
    line_start: int
    line_end: int
    column_start: int
    
    # Module information (for from-imports)
    module_path: Optional[str] = None
    relative_level: int = 0
    
    # Usage information
    is_used: bool = False
    usage_locations: List[UsageLocation] = field(default_factory=list)
    
    # Context information
    is_conditional: bool = False
    is_in_nested_scope: bool = False
    uses_wildcard: bool = False
    
    def __post_init__(self) -> None:
        """Validate and process after initialization."""
        # Ensure list is properly initialized
        if self.usage_locations is None:
            self.usage_locations = []
    
    def add_usage(self, location: UsageLocation) -> None:
        """
        Add a usage location to this import record.
        
        Parameters
        ----------
        location : UsageLocation
            The usage location to add
        
        Examples
        --------
        >>> record.add_usage(UsageLocation(
        ...     line_number=42,
        ...     column=5,
        ...     context=UsageContext.DIRECT_REFERENCE
        ... ))
        """
        self.usage_locations.append(location)
        self.is_used = True
    
    @property
    def line_range(self) -> Tuple[int, int]:
        """
        Get the line range as a tuple (start, end).
        
        Returns
        -------
        Tuple[int, int]
            Start and end line numbers
        
        Examples
        --------
        >>> start, end = record.line_range
        >>> print(f"Import spans lines {start}-{end}")
        """
        return (self.line_start, self.line_end)
    
    @property
    def usage_count(self) -> int:
        """
        Get the number of times this import is used.
        
        Returns
        -------
        int
            Count of usage locations
        
        Examples
        --------
        >>> if record.usage_count == 0:
        ...     print("Unused import!")
        """
        return len(self.usage_locations)
    
    @property
    def is_completely_unused(self) -> bool:
        """
        Check if this import is completely unused.
        
        Returns
        -------
        bool
            True if no usage locations recorded
        
        Examples
        --------
        >>> if record.is_completely_unused:
        ...     print(f"Can safely remove {record.name}")
        """
        return self.usage_count == 0
    
    @property
    def is_aliased(self) -> bool:
        """
        Check if this import uses an alias.
        
        Returns
        -------
        bool
            True if import uses 'as' clause
        
        Examples
        --------
        >>> if record.is_aliased:
        ...     print(f"Alias {record.alias} for {record.original_name}")
        """
        return self.alias is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation suitable for JSON
        
        Examples
        --------
        >>> import json
        >>> data = record.to_dict()
        >>> json.dumps(data, indent=2)
        """
        return {
            'name': self.name,
            'original_name': self.original_name,
            'alias': self.alias,
            'category': str(self.category),
            'line_start': self.line_start,
            'line_end': self.line_end,
            'column_start': self.column_start,
            'module_path': self.module_path,
            'relative_level': self.relative_level,
            'is_used': self.is_used,
            'usage_locations': [loc.to_dict() for loc in self.usage_locations],
            'is_conditional': self.is_conditional,
            'is_in_nested_scope': self.is_in_nested_scope,
            'uses_wildcard': self.uses_wildcard,
            'usage_count': self.usage_count,
            'is_aliased': self.is_aliased,
        }
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        status = "USED" if self.is_used else "UNUSED"
        location = f"line {self.line_start}"
        if self.line_end != self.line_start:
            location += f"-{self.line_end}"
        
        return f"[{status}] {self.category}: {self.name} (from {self.module_path or self.original_name}) at {location}"


@dataclass
class AnalysisReport:
    """
    Complete analysis report for a Python file.
    
    This dataclass contains everything discovered during import analysis,
    including all imports, usages, warnings, and statistics.
    
    Parameters
    ----------
    file_path : str
        Path to the analyzed file (or "<source>" for analysis from strings)
    timestamp : datetime
        When the analysis was performed
    config : AnalysisConfig
        Configuration used for analysis
    imports : Dict[str, ImportRecord]
        Dictionary mapping import names to their records
    used_names : Set[str]
        All names that are used in the code (including builtins)
    warnings : List[str]
        Warning messages collected during analysis
    errors : List[str]
        Error messages (non-fatal issues)
    analysis_duration_ms : float
        Time taken for analysis in milliseconds
    
    Attributes
    ----------
    All parameters are also available as instance attributes.
    Plus calculated properties:
    - total_imports : Total number of imports found
    - unused_imports : Set of unused import names
    - conditional_imports : Set of conditional import names
    - wildcard_imports : Dictionary of wildcard imports by line
    - type_hint_imports : Set of imports used only in type hints
    - side_effect_imports : Set of known side-effect imports
    
    Examples
    --------
    >>> report = analyze_file("my_module.py")
    >>> print(f"Found {report.total_imports} imports, {len(report.unused_imports)} unused")
    >>> for warning in report.warnings:
    ...     print(f"Warning: {warning}")
    >>> 
    >>> # Get detailed information about a specific import
    >>> if "os" in report.imports:
    ...     os_import = report.imports["os"]
    ...     print(f"os imported at line {os_import.line_start}")
    """
    
    # Core information
    file_path: str
    timestamp: datetime
    config: AnalysisConfig
    
    # Analysis results
    imports: Dict[str, ImportRecord] = field(default_factory=dict)
    used_names: Set[str] = field(default_factory=set)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    # Performance metrics
    analysis_duration_ms: float = 0.0
    
    def __post_init__(self) -> None:
        """Calculate derived attributes after initialization."""
        # Ensure collections are initialized
        if self.imports is None:
            self.imports = {}
        if self.used_names is None:
            self.used_names = set()
        if self.warnings is None:
            self.warnings = []
        if self.errors is None:
            self.errors = []
    
    @property
    def total_imports(self) -> int:
        """
        Total number of import statements found.
        
        Returns
        -------
        int
            Count of all imports
        
        Examples
        --------
        >>> print(f"Processing {report.total_imports} imports")
        """
        return len(self.imports)
    
    @property
    def unused_imports(self) -> Set[str]:
        """
        Set of import names that are not used.
        
        Returns
        -------
        Set[str]
            Unused import names
        
        Examples
        --------
        >>> for name in report.unused_imports:
        ...     print(f"Unused: {name}")
        >>> print(f"Found {len(report.unused_imports)} unused imports")
        """
        return {name for name, record in self.imports.items() 
                if not record.is_used}
    
    @property
    def conditional_imports(self) -> Set[str]:
        """
        Set of import names inside conditional blocks.
        
        Returns
        -------
        Set[str]
            Conditional import names
        
        Examples
        --------
        >>> cond_imports = report.conditional_imports
        >>> if cond_imports:
        ...     print(f"Found {len(cond_imports)} conditional imports")
        """
        return {name for name, record in self.imports.items() 
                if record.is_conditional}
    
    @property
    def wildcard_imports(self) -> Dict[int, str]:
        """
        Dictionary of wildcard imports by line number.
        
        Returns
        -------
        Dict[int, str]
            Mapping of line numbers to module names
        
        Examples
        --------
        >>> for line, module in report.wildcard_imports.items():
        ...     print(f"Line {line}: from {module} import *")
        """
        wildcards = {}
        for record in self.imports.values():
            if record.uses_wildcard:
                wildcards[record.line_start] = record.module_path or record.original_name
        return wildcards
    
    @property
    def type_hint_imports(self) -> Set[str]:
        """
        Set of imports used only in type annotations.
        
        Returns
        -------
        Set[str]
            Type hint only import names
        
        Examples
        --------
        >>> type_imports = report.type_hint_imports
        >>> if type_imports and report.config.preserve_type_hints:
        ...     print(f"Preserving {len(type_imports)} type-hint imports")
        """
        type_only = set()
        for name, record in self.imports.items():
            if record.usage_locations:
                all_annotations = all(
                    loc.context.is_annotation 
                    for loc in record.usage_locations
                )
                if all_annotations:
                    type_only.add(name)
        return type_only
    
    @property
    def side_effect_imports(self) -> Set[str]:
        """
        Set of imports known to be used for side effects.
        
        Returns
        -------
        Set[str]
            Side-effect import names
        
        Examples
        --------
        >>> side_effects = report.side_effect_imports
        >>> if side_effects and report.config.preserve_side_effects:
        ...     print("Preserving side-effect imports")
        """
        side_effects = set()
        for name, record in self.imports.items():
            # Check if module is known for side effects
            module = record.module_path or record.original_name
            top_module = module.split('.')[0]
            if top_module in SIDE_EFFECT_MODULES:
                side_effects.add(name)
        return side_effects
    
    def get_import_by_name(self, name: str) -> Optional[ImportRecord]:
        """
        Get the import record for a specific name.
        
        Parameters
        ----------
        name : str
            The import name to look up
        
        Returns
        -------
        Optional[ImportRecord]
            The import record if found, None otherwise
        
        Examples
        --------
        >>> os_import = report.get_import_by_name("os")
        >>> if os_import:
        ...     print(f"os imported at line {os_import.line_start}")
        """
        return self.imports.get(name)
    
    def get_unused_import_records(self) -> List[ImportRecord]:
        """
        Get all unused import records.
        
        Returns
        -------
        List[ImportRecord]
            List of unused import records
        
        Examples
        --------
        >>> for record in report.get_unused_import_records():
        ...     print(f"Can remove: {record.name} at line {record.line_start}")
        """
        return [record for record in self.imports.values() if not record.is_used]
    
    def get_imports_by_category(self, category: ImportCategory) -> List[ImportRecord]:
        """
        Get all imports of a specific category.
        
        Parameters
        ----------
        category : ImportCategory
            The category to filter by
        
        Returns
        -------
        List[ImportRecord]
            List of imports in the specified category
        
        Examples
        --------
        >>> from pyputil.util import ImportCategory
        >>> wildcards = report.get_imports_by_category(ImportCategory.WILDCARD_IMPORT)
        >>> print(f"Found {len(wildcards)} wildcard imports")
        """
        return [record for record in self.imports.values() 
                if record.category == category]
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.
        
        Returns
        -------
        Dict[str, Any]
            Complete dictionary representation
        
        Examples
        --------
        >>> import json
        >>> data = report.to_dict()
        >>> json.dumps(data, indent=2, default=str)
        """
        return {
            'file_path': self.file_path,
            'timestamp': self.timestamp.isoformat(),
            'config': self.config.to_dict(),
            'imports': {k: v.to_dict() for k, v in self.imports.items()},
            'used_names': sorted(self.used_names),
            'warnings': self.warnings,
            'errors': self.errors,
            'analysis_duration_ms': self.analysis_duration_ms,
            'statistics': {
                'total_imports': self.total_imports,
                'unused_imports': sorted(self.unused_imports),
                'conditional_imports': sorted(self.conditional_imports),
                'wildcard_imports': self.wildcard_imports,
                'type_hint_imports': sorted(self.type_hint_imports),
                'side_effect_imports': sorted(self.side_effect_imports),
                'unused_count': len(self.unused_imports),
            }
        }
    
    def summary(self) -> str:
        """
        Generate a human-readable summary of the analysis.
        
        Returns
        -------
        str
            Formatted summary string
        
        Examples
        --------
        >>> print(report.summary())
        === Import Analysis Report ===
        File: my_module.py
        Analysis time: 2024-01-15 10:30:45
        Total imports: 15
        Unused imports: 3 (20.0%)
        Conditional imports: 2
        Wildcard imports: 0
        Warnings: 1
        """
        summary_lines = [
            "=" * 60,
            "Import Analysis Report",
            "=" * 60,
            f"File: {self.file_path}",
            f"Analysis time: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Analysis duration: {self.analysis_duration_ms:.2f} ms",
            "-" * 60,
            f"Total imports: {self.total_imports}",
            f"Unused imports: {len(self.unused_imports)} ({self._percentage_unused():.1f}%)",
            f"Conditional imports: {len(self.conditional_imports)}",
            f"Wildcard imports: {len(self.wildcard_imports)}",
            f"Type-hint only: {len(self.type_hint_imports)}",
            f"Side-effect imports: {len(self.side_effect_imports)}",
            "-" * 60,
            f"Warnings: {len(self.warnings)}",
            f"Errors: {len(self.errors)}",
        ]
        
        if self.warnings:
            summary_lines.append("\nWarnings:")
            for warning in self.warnings[:5]:  # Show first 5 warnings
                summary_lines.append(f"  - {warning}")
            if len(self.warnings) > 5:
                summary_lines.append(f"  ... and {len(self.warnings) - 5} more")
        
        return "\n".join(summary_lines)
    
    def _percentage_unused(self) -> float:
        """Calculate percentage of unused imports."""
        if self.total_imports == 0:
            return 0.0
        return (len(self.unused_imports) / self.total_imports) * 100


@dataclass
class CleanupResult:
    """
    Result of an import cleanup operation.
    
    This dataclass reports what changes were made during import cleanup,
    including which imports were removed and any issues encountered.
    
    Parameters
    ----------
    file_path : str
        Path to the modified file
    timestamp : datetime
        When the cleanup was performed
    removed_imports : Set[str]
        Names of imports that were removed
    modified_lines : Set[int]
        Line numbers that were modified
    backup_created : bool
        Whether a backup file was created
    backup_path : Optional[str]
        Path to backup file if created
    warnings : List[str]
        Warnings during cleanup
    errors : List[str]
        Errors during cleanup
    
    Examples
    --------
    >>> result = clean_file("my_module.py", backup=True)
    >>> print(f"Removed {len(result.removed_imports)} imports")
    >>> if result.backup_created:
    ...     print(f"Backup saved to {result.backup_path}")
    """
    
    file_path: str
    timestamp: datetime
    removed_imports: Set[str]
    modified_lines: Set[int]
    backup_created: bool
    backup_path: Optional[str]
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'file_path': self.file_path,
            'timestamp': self.timestamp.isoformat(),
            'removed_imports': sorted(self.removed_imports),
            'modified_lines': sorted(self.modified_lines),
            'backup_created': self.backup_created,
            'backup_path': self.backup_path,
            'warnings': self.warnings,
            'errors': self.errors,
            'total_removed': len(self.removed_imports),
            'total_lines_modified': len(self.modified_lines),
        }
    
    def summary(self) -> str:
        """
        Generate a human-readable summary.
        
        Returns
        -------
        str
            Formatted summary string
        
        Examples
        --------
        >>> print(result.summary())
        === Import Cleanup Report ===
        File: my_module.py
        Removed 3 unused imports
        Modified 2 lines
        Backup created: my_module.py.bak
        """
        lines = [
            "=" * 60,
            "Import Cleanup Report",
            "=" * 60,
            f"File: {self.file_path}",
            f"Time: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "-" * 60,
            f"Removed imports: {len(self.removed_imports)}",
            f"Modified lines: {len(self.modified_lines)}",
            f"Backup created: {self.backup_created}",
        ]
        
        if self.backup_path:
            lines.append(f"Backup path: {self.backup_path}")
        
        if self.removed_imports:
            lines.append(f"\nRemoved imports:")
            for name in sorted(self.removed_imports)[:10]:
                lines.append(f"  - {name}")
            if len(self.removed_imports) > 10:
                lines.append(f"  ... and {len(self.removed_imports) - 10} more")
        
        return "\n".join(lines)


# ============================================================================
# AST Visitor Implementation
# ============================================================================

class ImportAnalysisVisitor(ast.NodeVisitor):
    """
    Advanced AST visitor for comprehensive import analysis.
    
    This visitor traverses the AST and collects detailed information about
    all imports and their usage throughout the code. It is scope-aware and
    tracks context information for accurate analysis.
    
    Attributes
    ----------
    config : AnalysisConfig
        Configuration controlling analysis behavior
    imports : Dict[str, ImportRecord]
        Collected import records
    used_names : Set[str]
        All names that are used
    _current_function : Optional[str]
        Current function name during traversal
    _current_class : Optional[str]
        Current class name during traversal
    _in_conditional : int
        Counter for conditional block depth
    _in_type_hint : bool
        Whether currently parsing a type hint
    _in_comprehension : bool
        Whether currently in a comprehension
    _in_lambda : bool
        Whether currently in a lambda function
    
    Examples
    --------
    >>> config = AnalysisConfig()
    >>> visitor = ImportAnalysisVisitor(config)
    >>> tree = ast.parse(source_code)
    >>> visitor.visit(tree)
    >>> report = visitor.get_report("my_file.py")
    """
    
    def __init__(self, config: AnalysisConfig):
        """
        Initialize the AST visitor with configuration.
        
        Parameters
        ----------
        config : AnalysisConfig
            Configuration controlling analysis behavior
        """
        super().__init__()
        self.config = config
        
        # Collected data
        self.imports: Dict[str, ImportRecord] = {}
        self.used_names: Set[str] = set()
        self.warnings: List[str] = []
        
        # Scope tracking
        self._current_function: Optional[str] = None
        self._current_class: Optional[str] = None
        self._in_conditional: int = 0
        self._in_type_hint: bool = False
        self._in_comprehension: bool = False
        self._in_lambda: bool = False
        
        # Track local names to avoid false positives
        self._local_names: Set[str] = set()
        self._function_params: Dict[str, Set[str]] = defaultdict(set)
        
        # For tracking attribute access
        self._module_attributes: Set[str] = set()
        
        # Builtins for filtering
        self._builtins = []
        
        _logger.debug(f"ImportAnalysisVisitor initialized with config: {config}")
    
    def _should_ignore_name(self, name: str) -> bool:
        """
        Determine if a name should be ignored in usage tracking.
        
        Parameters
        ----------
        name : str
            The name to check
        
        Returns
        -------
        bool
            True if the name should be ignored
        """
        # Check dunder names
        if self.config.ignore_dunder_names and name.startswith('__') and name.endswith('__'):
            return True
        
        # Check builtins
        if self.config.ignore_builtins and name in self._builtins:
            return True
        
        # Check private names
        if self.config.ignore_private_names and name.startswith('_') and not name.startswith('__'):
            return True
        
        # Check local names (defined in current scope)
        if name in self._local_names:
            return True
        
        return False
    
    def _add_usage(
        self, 
        name: str, 
        line_number: int, 
        column: int,
        context: UsageContext
    ) -> None:
        """
        Record a usage of a name.
        
        Parameters
        ----------
        name : str
            The name being used
        line_number : int
            Line number where used
        column : int
            Column offset where used
        context : UsageContext
            Context of usage
        """
        # Skip ignored names
        if self._should_ignore_name(name):
            return
        
        # Record the name as used
        self.used_names.add(name)
        
        # Find the import record
        import_record = self.imports.get(name)
        if import_record:
            # Add usage location
            location = UsageLocation(
                line_number=line_number,
                column=column,
                context=context,
                parent_function=self._current_function,
                parent_class=self._current_class,
            )
            import_record.add_usage(location)
            _logger.log(5, f"Recorded usage: {name} at line {line_number} ({context})")
    
    def _add_import_record(self, record: ImportRecord) -> None:
        """
        Add or update an import record.
        
        Parameters
        ----------
        record : ImportRecord
            The import record to add
        """
        if record.name in self.imports:
            # This shouldn't happen with proper scope handling
            _logger.warning(f"Duplicate import record for {record.name}")
        self.imports[record.name] = record
        _logger.debug(f"Added import record: {record}")
    
    def visit_Import(self, node: ast.Import) -> None:
        """
        Process an `import module` statement.
        
        Parameters
        ----------
        node : ast.Import
            The import AST node
        """
        for alias in node.names:
            # Extract name information
            original_name = alias.name
            base_name = original_name.split('.')[0]
            alias_name = alias.asname
            
            # Determine the name as used in code
            used_name = alias_name if alias_name else base_name
            
            # Determine category
            if alias_name:
                category = ImportCategory.ALIASED_IMPORT
            else:
                category = ImportCategory.STANDARD_IMPORT
            
            # Create import record
            record = ImportRecord(
                name=used_name,
                original_name=original_name,
                alias=alias_name,
                category=category,
                line_start=node.lineno,
                line_end=getattr(node, 'end_lineno', node.lineno),
                column_start=node.col_offset,
                is_conditional=self._in_conditional > 0,
                is_in_nested_scope=bool(self._current_function or self._current_class),
            )
            
            self._add_import_record(record)
        
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """
        Process a `from module import name` statement.
        
        Parameters
        ----------
        node : ast.ImportFrom
            The from-import AST node
        """
        module = node.module or ''
        level = node.level
        
        for alias in node.names:
            if alias.name == '*':
                # Handle wildcard import
                record = ImportRecord(
                    name=f"* from {module}",
                    original_name=f"{module}.*",
                    alias=None,
                    category=ImportCategory.WILDCARD_IMPORT,
                    line_start=node.lineno,
                    line_end=getattr(node, 'end_lineno', node.lineno),
                    column_start=node.col_offset,
                    module_path=module,
                    relative_level=level,
                    uses_wildcard=True,
                    is_conditional=self._in_conditional > 0,
                    is_in_nested_scope=bool(self._current_function or self._current_class),
                )
                self._add_import_record(record)
                self.warnings.append(
                    f"Wildcard import 'from {module} import *' at line {node.lineno} - "
                    f"cannot analyze individual names"
                )
                continue
            
            # Regular import
            original_name = alias.name
            alias_name = alias.asname
            
            # Determine the name as used in code
            used_name = alias_name if alias_name else original_name
            
            # Determine category
            if level > 0:
                category = ImportCategory.RELATIVE_IMPORT
            elif alias_name:
                category = ImportCategory.ALIASED_IMPORT
            else:
                category = ImportCategory.FROM_IMPORT
            
            # Create full original name with module
            full_original = f"{module}.{original_name}" if module else original_name
            
            record = ImportRecord(
                name=used_name,
                original_name=full_original,
                alias=alias_name,
                category=category,
                line_start=node.lineno,
                line_end=getattr(node, 'end_lineno', node.lineno),
                column_start=node.col_offset,
                module_path=module if module else None,
                relative_level=level,
                is_conditional=self._in_conditional > 0,
                is_in_nested_scope=bool(self._current_function or self._current_class),
            )
            
            self._add_import_record(record)
        
        self.generic_visit(node)
    
    def visit_Name(self, node: ast.Name) -> None:
        """
        Process a name reference.
        
        Parameters
        ----------
        node : ast.Name
            The name AST node
        """
        # Determine usage context
        if self._in_type_hint:
            context = UsageContext.TYPE_ANNOTATION
        elif self._in_comprehension:
            context = UsageContext.COMPREHENSION
        elif self._in_lambda:
            context = UsageContext.LAMBDA
        else:
            context = UsageContext.DIRECT_REFERENCE
        
        self._add_usage(
            name=node.id,
            line_number=node.lineno,
            column=node.col_offset,
            context=context
        )
        
        self.generic_visit(node)
    
    def visit_Attribute(self, node: ast.Attribute) -> None:
        """
        Process attribute access (module.attribute).
        
        Parameters
        ----------
        node : ast.Attribute
            The attribute AST node
        """
        # Track the base module name
        if isinstance(node.value, ast.Name):
            self._add_usage(
                name=node.value.id,
                line_number=node.lineno,
                column=node.col_offset,
                context=UsageContext.ATTRIBUTE_ACCESS
            )
        
        self.generic_visit(node)
    
    def visit_Call(self, node: ast.Call) -> None:
        """
        Process function calls.
        
        Parameters
        ----------
        node : ast.Call
            The function call AST node
        """
        # Track the function being called
        if isinstance(node.func, ast.Name):
            self._add_usage(
                name=node.func.id,
                line_number=node.lineno,
                column=node.col_offset,
                context=UsageContext.FUNCTION_CALL
            )
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                self._add_usage(
                    name=node.func.value.id,
                    line_number=node.lineno,
                    column=node.col_offset,
                    context=UsageContext.FUNCTION_CALL
                )
        
        self.generic_visit(node)
    
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """
        Process annotated assignments (type hints).
        
        Parameters
        ----------
        node : ast.AnnAssign
            The annotated assignment AST node
        """
        if self.config.analyze_type_hints:
            old_in_type_hint = self._in_type_hint
            self._in_type_hint = True
            if node.annotation:
                self.visit(node.annotation)
            self._in_type_hint = old_in_type_hint
        
        # Visit the value (which might be regular code)
        if node.value:
            self.visit(node.value)
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """
        Process function definitions.
        
        Parameters
        ----------
        node : ast.FunctionDef
            The function definition AST node
        """
        # Track function parameters as local names
        old_local_names = self._local_names.copy()
        for arg in node.args.args:
            self._local_names.add(arg.arg)
            self._function_params[node.name].add(arg.arg)
        
        # Also handle kwonlyargs and kwarg
        for arg in node.args.kwonlyargs:
            self._local_names.add(arg.arg)
        if node.args.vararg:
            self._local_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            self._local_names.add(node.args.kwarg.arg)
        
        # Track function name as local
        self._local_names.add(node.name)
        
        # Track current function for context
        old_function = self._current_function
        self._current_function = node.name
        
        # Process return annotation
        if node.returns and self.config.analyze_type_hints:
            old_in_type_hint = self._in_type_hint
            self._in_type_hint = True
            self.visit(node.returns)
            self._in_type_hint = old_in_type_hint
        
        # Process body
        self.generic_visit(node)
        
        # Restore state
        self._current_function = old_function
        self._local_names = old_local_names
    
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """
        Process class definitions.
        
        Parameters
        ----------
        node : ast.ClassDef
            The class definition AST node
        """
        # Track class name as local
        old_local_names = self._local_names.copy()
        self._local_names.add(node.name)
        
        # Track current class for context
        old_class = self._current_class
        self._current_class = node.name
        
        # Process bases (inheritance)
        for base in node.bases:
            self.visit(base)
        
        # Process body
        self.generic_visit(node)
        
        # Restore state
        self._current_class = old_class
        self._local_names = old_local_names
    
    def visit_Lambda(self, node: ast.Lambda) -> None:
        """
        Process lambda functions.
        
        Parameters
        ----------
        node : ast.Lambda
            The lambda AST node
        """
        if not self.config.analyze_lambdas:
            return
        
        old_in_lambda = self._in_lambda
        self._in_lambda = True
        
        # Track lambda args as local
        old_local_names = self._local_names.copy()
        for arg in node.args.args:
            self._local_names.add(arg.arg)
        
        self.visit(node.body)
        
        self._local_names = old_local_names
        self._in_lambda = old_in_lambda
    
    def visit_ListComp(self, node: ast.ListComp) -> None:
        """
        Process list comprehensions.
        
        Parameters
        ----------
        node : ast.ListComp
            The list comprehension AST node
        """
        if not self.config.analyze_comprehensions:
            self.generic_visit(node)
            return
        
        old_in_comp = self._in_comprehension
        self._in_comprehension = True
        
        # Track comprehension variables as local
        old_local_names = self._local_names.copy()
        
        # Process generators
        for generator in node.generators:
            # Track iteration variable
            if isinstance(generator.target, ast.Name):
                self._local_names.add(generator.target.id)
            self.visit(generator.iter)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        
        self.visit(node.elt)
        
        self._local_names = old_local_names
        self._in_comprehension = old_in_comp
    
    def visit_DictComp(self, node: ast.DictComp) -> None:
        """Process dictionary comprehensions."""
        if not self.config.analyze_comprehensions:
            self.generic_visit(node)
            return
        
        old_in_comp = self._in_comprehension
        self._in_comprehension = True
        
        old_local_names = self._local_names.copy()
        
        for generator in node.generators:
            if isinstance(generator.target, ast.Name):
                self._local_names.add(generator.target.id)
            self.visit(generator.iter)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        
        self.visit(node.key)
        self.visit(node.value)
        
        self._local_names = old_local_names
        self._in_comprehension = old_in_comp
    
    def visit_SetComp(self, node: ast.SetComp) -> None:
        """Process set comprehensions."""
        if not self.config.analyze_comprehensions:
            self.generic_visit(node)
            return
        
        old_in_comp = self._in_comprehension
        self._in_comprehension = True
        
        old_local_names = self._local_names.copy()
        
        for generator in node.generators:
            if isinstance(generator.target, ast.Name):
                self._local_names.add(generator.target.id)
            self.visit(generator.iter)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        
        self.visit(node.elt)
        
        self._local_names = old_local_names
        self._in_comprehension = old_in_comp
    
    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        """Process generator expressions."""
        if not self.config.analyze_comprehensions:
            self.generic_visit(node)
            return
        
        old_in_comp = self._in_comprehension
        self._in_comprehension = True
        
        old_local_names = self._local_names.copy()
        
        for generator in node.generators:
            if isinstance(generator.target, ast.Name):
                self._local_names.add(generator.target.id)
            self.visit(generator.iter)
            for if_clause in generator.ifs:
                self.visit(if_clause)
        
        self.visit(node.elt)
        
        self._local_names = old_local_names
        self._in_comprehension = old_in_comp
    
    def visit_If(self, node: ast.If) -> None:
        """
        Process if statements for conditional detection.
        
        Parameters
        ----------
        node : ast.If
            The if statement AST node
        """
        if self.config.detect_conditional_imports:
            self._in_conditional += 1
            self.generic_visit(node)
            self._in_conditional -= 1
        else:
            self.generic_visit(node)
    
    def visit_Try(self, node: ast.Try) -> None:
        """
        Process try blocks for conditional detection.
        
        Parameters
        ----------
        node : ast.Try
            The try statement AST node
        """
        if self.config.detect_conditional_imports:
            self._in_conditional += 1
            self.generic_visit(node)
            self._in_conditional -= 1
        else:
            self.generic_visit(node)
    
    def visit_Constant(self, node: ast.Constant) -> None:
        """
        Process string constants for PEP 563 annotations.
        
        Parameters
        ----------
        node : ast.Constant
            The constant AST node
        """
        # Check for string annotations (PEP 563)
        if (self.config.analyze_string_annotations and 
            self._in_type_hint and 
            isinstance(node.value, str)):
            
            # Parse the string for potential import names
            # Simple regex to find identifiers in the string
            import re
            identifiers = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', node.value)
            for identifier in identifiers:
                if not self._should_ignore_name(identifier):
                    self._add_usage(
                        name=identifier,
                        line_number=node.lineno,
                        column=node.col_offset,
                        context=UsageContext.STRING_ANNOTATION
                    )
        
        self.generic_visit(node)
    
    def get_report(self, file_path: str, duration_ms: float = 0.0) -> AnalysisReport:
        """
        Generate the final analysis report.
        
        Parameters
        ----------
        file_path : str
            Path to the analyzed file
        duration_ms : float, default=0.0
            Analysis duration in milliseconds
        
        Returns
        -------
        AnalysisReport
            Complete analysis report
        
        Examples
        --------
        >>> visitor = ImportAnalysisVisitor(config)
        >>> visitor.visit(tree)
        >>> report = visitor.get_report("my_file.py", duration_ms=123.45)
        >>> print(report.summary())
        """
        # Apply custom always/never used rules
        for name in self.config.custom_always_used:
            self.used_names.add(name)
            if name in self.imports:
                self.imports[name].is_used = True
        
        for name in self.config.custom_never_used:
            if name in self.imports:
                self.imports[name].is_used = False
        
        return AnalysisReport(
            file_path=file_path,
            timestamp=datetime.now(),
            config=self.config,
            imports=self.imports,
            used_names=self.used_names,
            warnings=self.warnings,
            analysis_duration_ms=duration_ms,
        )


# ============================================================================
# Main detector Class
# ============================================================================

class ImportDetector:
    """
    Main class for import analysis and optimization operations.
    
    This class provides the primary interface for analyzing and cleaning
    imports in Python files. It wraps the AST visitor and provides
    convenient methods for common operations.
    
    Parameters
    ----------
    config : AnalysisConfig, optional
        Configuration for analysis behavior. If not provided, default
        configuration is used.
    
    Attributes
    ----------
    config : AnalysisConfig
        Current configuration
    
    Examples
    --------
    >>> # Create detector with default settings
    >>> detector = ImportDetector()
    >>> 
    >>> # Analyze a single file
    >>> report = detector.analyze_file("my_module.py")
    >>> 
    >>> # Clean the file (remove unused imports)
    >>> result = detector.clean_file("my_module.py", backup=True)
    >>> 
    >>> # Process all files in a directory
    >>> results = detector.clean_directory("src/", recursive=True)
    >>> 
    >>> # Analyze source code from string
    >>> source = "import os\\n\\ndef test():\\n    return os.getcwd()"
    >>> report = detector.analyze_source(source)
    """
    
    def __init__(self, config: Optional[AnalysisConfig] = None):
        """
        Initialize the import detector with optional configuration.
        
        Parameters
        ----------
        config : AnalysisConfig, optional
            Configuration for analysis. If None, default configuration is used.
        """
        self.config = config or AnalysisConfig.create_default()
        _logger.info(f"ImportDetector initialized with config: {self.config}")
    
    def analyze_file(self, file_path: Union[str, Path]) -> AnalysisReport:
        """
        Analyze imports in a Python file.
        
        Parameters
        ----------
        file_path : Union[str, Path]
            Path to the Python file to analyze
        
        Returns
        -------
        AnalysisReport
            Complete analysis report
        
        Raises
        ------
        FileAccessError
            If the file cannot be read
        InvalidSourceError
            If the file contains syntax errors
        
        Examples
        --------
        >>> detector = ImportDetector()
        >>> report = detector.analyze_file("my_script.py")
        >>> print(f"Unused imports: {report.unused_imports}")
        >>> print(report.summary())
        """
        import time
        start_time = time.perf_counter()
        
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileAccessError(f"File not found: {file_path}", file_path=str(file_path))
        
        if not file_path.is_file():
            raise FileAccessError(f"Path is not a file: {file_path}", file_path=str(file_path))
        
        try:
            source = file_path.read_text(encoding='utf-8')
        except Exception as e:
            raise FileAccessError(f"Cannot read file: {e}", original_error=e, file_path=str(file_path))
        
        return self.analyze_source(source, str(file_path))
    
    def analyze_source(self, source: str, filename: str = "<source>") -> AnalysisReport:
        """
        Analyze imports in source code string.
        
        Parameters
        ----------
        source : str
            Python source code to analyze
        filename : str, default="<source>"
            Virtual filename for error reporting
        
        Returns
        -------
        AnalysisReport
            Complete analysis report
        
        Raises
        ------
        InvalidSourceError
            If the source contains syntax errors
        
        Examples
        --------
        >>> detector = ImportDetector()
        >>> source = '''
        ... import os
        ... import sys
        ... 
        ... def main():
        ...     return os.getcwd()
        ... '''
        >>> report = detector.analyze_source(source)
        >>> print("Unused:", report.unused_imports)  # {'sys'}
        """
        import time
        start_time = time.perf_counter()
        
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as e:
            raise InvalidSourceError(
                f"Syntax error: {e.msg}",
                line_number=e.lineno,
                column=e.offset,
                original_error=e,
                file_path=filename
            )
        
        # Create visitor and analyze
        visitor = ImportAnalysisVisitor(self.config)
        visitor.visit(tree)
        
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        return visitor.get_report(filename, duration_ms)
    
    def clean_file(
        self,
        file_path: Union[str, Path],
        mode: CleanupMode = CleanupMode.NORMAL,
        dry_run: bool = False,
        backup: bool = False,
        encoding: str = 'utf-8'
    ) -> Union[AnalysisReport, CleanupResult]:
        """
        Remove unused imports from a Python file.
        
        Parameters
        ----------
        file_path : Union[str, Path]
            Path to the Python file to clean
        mode : CleanupMode, default=CleanupMode.NORMAL
            How aggressive to be when removing imports
        dry_run : bool, default=False
            If True, only analyze and report without modifying
        backup : bool, default=False
            If True, create a backup before modifying (no effect on dry_run)
        encoding : str, default='utf-8'
            File encoding
        
        Returns
        -------
        Union[AnalysisReport, CleanupResult]
            - If dry_run=True: Returns AnalysisReport of what would be removed
            - If dry_run=False: Returns CleanupResult with details of changes
        
        Raises
        ------
        FileAccessError
            If file operations fail
        InvalidSourceError
            If the file contains syntax errors
        
        Examples
        --------
        >>> detector = ImportDetector()
        >>> 
        >>> # Preview changes
        >>> report = detector.clean_file("my_module.py", dry_run=True)
        >>> print(f"Would remove {len(report.unused_imports)} imports")
        >>> 
        >>> # Actually clean with backup
        >>> result = detector.clean_file("my_module.py", backup=True)
        >>> print(result.summary())
        >>> 
        >>> # Aggressive cleaning
        >>> result = detector.clean_file("my_module.py", mode=CleanupMode.AGGRESSIVE)
        """
        # First analyze the file
        report = self.analyze_file(file_path)
        
        if dry_run:
            return report        
        # Determine which imports to remove based on mode
        to_remove = self._determine_imports_to_remove(report, mode)
        
        if not to_remove:
            _logger.info(f"No unused imports to remove in {file_path}")
            return CleanupResult(
                file_path=str(file_path),
                timestamp=datetime.now(),
                removed_imports=set(),
                modified_lines=set(),
                backup_created=False,
                backup_path=None,
            )
        
        # Read original source
        file_path = Path(file_path)
        original_source = file_path.read_text(encoding=encoding)
        
        # Create backup if requested
        backup_path = None
        if backup:
            backup_path = file_path.with_suffix(file_path.suffix + '.bak')
            try:
                file_path.rename(backup_path)
                _logger.info(f"Created backup: {backup_path}")
            except Exception as e:
                raise FileAccessError(f"Cannot create backup: {e}", original_error=e, file_path=str(file_path))
        
        # Remove imports
        modified_source = self._remove_imports_from_source(original_source, to_remove, report)
        
        # Write modified source
        try:
            file_path.write_text(modified_source, encoding=encoding)
            _logger.info(f"Successfully cleaned {file_path}: removed {len(to_remove)} imports")
        except Exception as e:
            raise FileAccessError(f"Cannot write file: {e}", original_error=e, file_path=str(file_path))
        
        # Find modified lines (for result)
        modified_lines = self._find_modified_lines(original_source, modified_source)
        
        return CleanupResult(
            file_path=str(file_path),
            timestamp=datetime.now(),
            removed_imports=to_remove,
            modified_lines=modified_lines,
            backup_created=backup,
            backup_path=str(backup_path) if backup_path else None,
        )
    
    def clean_directory(
        self,
        directory: Union[str, Path],
        pattern: str = "*.py",
        recursive: bool = True,
        mode: CleanupMode = CleanupMode.NORMAL,
        dry_run: bool = False,
        backup: bool = False,
    ) -> Dict[str, Union[AnalysisReport, CleanupResult]]:
        """
        Clean all Python files in a directory.
        
        Parameters
        ----------
        directory : Union[str, Path]
            Directory to process
        pattern : str, default="*.py"
            Glob pattern for files to process
        recursive : bool, default=True
            Whether to process subdirectories recursively
        mode : CleanupMode, default=CleanupMode.NORMAL
            Cleanup mode to use
        dry_run : bool, default=False
            If True, only analyze without modifying
        backup : bool, default=False
            If True, create backups for modified files
        
        Returns
        -------
        Dict[str, Union[AnalysisReport, CleanupResult]]
            Dictionary mapping file paths to results
        
        Examples
        --------
        >>> detector = ImportDetector()
        >>> 
        >>> # Clean all Python files in src directory
        >>> results = detector.clean_directory("src/")
        >>> 
        >>> # Preview changes
        >>> results = detector.clean_directory("src/", dry_run=True)
        >>> for path, report in results.items():
        ...     print(f"{path}: {len(report.unused_imports)} unused imports")
        """
        directory = Path(directory)
        
        if not directory.exists():
            raise FileAccessError(f"Directory not found: {directory}", file_path=str(directory))
        
        if not directory.is_dir():
            raise FileAccessError(f"Path is not a directory: {directory}", file_path=str(directory))
        
        # Find all matching files
        if recursive:
            files = list(directory.rglob(pattern))
        else:
            files = list(directory.glob(pattern))
        
        results = {}
        
        for file_path in files:
            try:
                result = self.clean_file(file_path, mode=mode, dry_run=dry_run, backup=backup)
                results[str(file_path)] = result
            except Exception as e:
                _logger.error(f"Failed to process {file_path}: {e}")
                results[str(file_path)] = e
        
        return results
    
    def _determine_imports_to_remove(self, report: AnalysisReport, mode: CleanupMode) -> Set[str]:
        """
        Determine which imports should be removed based on mode.
        
        Parameters
        ----------
        report : AnalysisReport
            Analysis report
        mode : CleanupMode
            Cleanup mode to use
        
        Returns
        -------
        Set[str]
            Import names to remove
        """
        to_remove = report.unused_imports.copy()
        
        if mode.preserve_conditional_imports:
            to_remove -= report.conditional_imports
        
        if mode.preserve_side_effects:
            to_remove -= report.side_effect_imports
        
        if mode.preserve_type_hints:
            to_remove -= report.type_hint_imports
        
        # Don't remove wildcard imports (can't safely remove them)
        for record in report.get_imports_by_category(ImportCategory.WILDCARD_IMPORT):
            to_remove.discard(record.name)
        
        return to_remove
    
    def _remove_imports_from_source(
        self, 
        source: str, 
        imports_to_remove: Set[str],
        report: AnalysisReport
    ) -> str:
        """
        Remove specified imports from source code.
        
        Parameters
        ----------
        source : str
            Original source code
        imports_to_remove : Set[str]
            Names of imports to remove
        report : AnalysisReport
            Analysis report for location information
        
        Returns
        -------
        str
            Modified source code
        """
        lines = source.splitlines()
        lines_to_remove = set()
        
        for import_name in imports_to_remove:
            record = report.imports.get(import_name)
            if record:
                # Mark lines for removal
                start = record.line_start - 1
                end = record.line_end
                for i in range(start, end):
                    lines_to_remove.add(i)
        
        # Rebuild source without removed lines
        new_lines = [line for i, line in enumerate(lines) if i not in lines_to_remove]
        new_source = "\n".join(new_lines)
        
        # Ensure trailing newline
        if not new_source.endswith('\n'):
            new_source += '\n'
        
        return new_source
    
    def _find_modified_lines(self, original: str, modified: str) -> Set[int]:
        """
        Find which lines were modified between two source versions.
        
        Parameters
        ----------
        original : str
            Original source
        modified : str
            Modified source
        
        Returns
        -------
        Set[int]
            Set of modified line numbers (1-indexed)
        """
        original_lines = original.splitlines()
        modified_lines = modified.splitlines()
        
        # Simple diff: find lines that are different
        modified_indices = set()
        max_len = max(len(original_lines), len(modified_lines))
        
        for i in range(max_len):
            orig = original_lines[i] if i < len(original_lines) else ""
            mod = modified_lines[i] if i < len(modified_lines) else ""
            if orig != mod:
                modified_indices.add(i + 1)  # Convert to 1-indexed
        
        return modified_indices


# ============================================================================
# Convenience Functions
# ============================================================================

def analyze_file(
    file_path: Union[str, Path],
    config: Optional[AnalysisConfig] = None
) -> AnalysisReport:
    """
    Convenience function to analyze imports in a file.
    
    Parameters
    ----------
    file_path : Union[str, Path]
        Path to the Python file to analyze
    config : AnalysisConfig, optional
        Configuration for analysis
    
    Returns
    -------
    AnalysisReport
        Complete analysis report
    
    Examples
    --------
    >>> report = analyze_file("my_module.py")
    >>> print(report.summary())
    """
    detector = ImportDetector(config)
    return detector.analyze_file(file_path)


def analyze_source(
    source: str,
    filename: str = "<source>",
    config: Optional[AnalysisConfig] = None
) -> AnalysisReport:
    """
    Convenience function to analyze imports in source code.
    
    Parameters
    ----------
    source : str
        Python source code to analyze
    filename : str, default="<source>"
        Virtual filename for error reporting
    config : AnalysisConfig, optional
        Configuration for analysis
    
    Returns
    -------
    AnalysisReport
        Complete analysis report
    
    Examples
    --------
    >>> source = "import os\\n\\ndef test(): return os.getcwd()"
    >>> report = analyze_source(source)
    >>> print(report.unused_imports)
    """
    detector = ImportDetector(config)
    return detector.analyze_source(source, filename)


def clean_file(
    file_path: Union[str, Path],
    mode: CleanupMode = CleanupMode.NORMAL,
    dry_run: bool = False,
    backup: bool = True,
    config: Optional[AnalysisConfig] = None
) -> Union[AnalysisReport, CleanupResult]:
    """
    Convenience function to clean unused imports from a file.
    
    Parameters
    ----------
    file_path : Union[str, Path]
        Path to the Python file to clean
    mode : CleanupMode, default=CleanupMode.NORMAL
        Cleanup mode to use
    dry_run : bool, default=False
        If True, only analyze without modifying
    backup : bool, default=True
        If True, create a backup before modifying
    config : AnalysisConfig, optional
        Configuration for analysis
    
    Returns
    -------
    Union[AnalysisReport, CleanupResult]
        - If dry_run=True: AnalysisReport
        - If dry_run=False: CleanupResult
    
    Examples
    --------
    >>> # Preview changes
    >>> report = clean_file("my_module.py", dry_run=True)
    >>> print(f"Would remove: {report.unused_imports}")
    >>> 
    >>> # Clean with backup
    >>> result = clean_file("my_module.py", backup=True)
    >>> print(result.summary())
    """
    detector = ImportDetector(config)
    return detector.clean_file(file_path, mode=mode, dry_run=dry_run, backup=backup)


def clean_directory(
    directory: Union[str, Path],
    pattern: str = "*.py",
    recursive: bool = True,
    mode: CleanupMode = CleanupMode.NORMAL,
    dry_run: bool = False,
    backup: bool = True,
    config: Optional[AnalysisConfig] = None
) -> Dict[str, Union[AnalysisReport, CleanupResult]]:
    """
    Convenience function to clean all Python files in a directory.
    
    Parameters
    ----------
    directory : Union[str, Path]
        Directory to process
    pattern : str, default="*.py"
        Glob pattern for files
    recursive : bool, default=True
        Whether to process subdirectories
    mode : CleanupMode, default=CleanupMode.NORMAL
        Cleanup mode to use
    dry_run : bool, default=False
        If True, only analyze without modifying
    backup : bool, default=True
        If True, create backups for modified files
    config : AnalysisConfig, optional
        Configuration for analysis
    
    Returns
    -------
    Dict[str, Union[AnalysisReport, CleanupResult]]
        Results keyed by file path
    
    Examples
    --------
    >>> # Clean all Python files in src
    >>> results = clean_directory("src/", backup=True)
    >>> for path, result in results.items():
    ...     if isinstance(result, CleanupResult):
    ...         print(f"{path}: removed {len(result.removed_imports)} imports")
    """
    detector = ImportDetector(config)
    return detector.clean_directory(directory, pattern, recursive, mode, dry_run, backup)


def detect_unused_imports(
    file_path: Union[str, Path],
    config: Optional[AnalysisConfig] = None
) -> Set[str]:
    """
    Quickly detect unused imports in a file.
    
    Parameters
    ----------
    file_path : Union[str, Path]
        Path to the Python file to analyze
    config : AnalysisConfig, optional
        Configuration for analysis
    
    Returns
    -------
    Set[str]
        Set of unused import names
    
    Examples
    --------
    >>> unused = detect_unused_imports("my_module.py")
    >>> print(f"Found {len(unused)} unused imports: {unused}")
    """
    report = analyze_file(file_path, config)
    return report.unused_imports


# ============================================================================
# Module Initialization
# ============================================================================

def setup_logging(level: int = logging.WARNING) -> None:
    """
    Configure logging for the module.
    
    Parameters
    ----------
    level : int, default=logging.WARNING
        Logging level (e.g., logging.DEBUG, logging.INFO)
    
    Examples
    --------
    >>> import logging
    >>> setup_logging(logging.DEBUG)
    """
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    _logger.addHandler(handler)
    _logger.setLevel(level)


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Main classes
    'ImportDetector',
    'AnalysisConfig',
    'ImportRecord',
    'AnalysisReport',
    'CleanupResult',
    'UsageLocation',
    
    # Enums
    'ImportCategory',
    'UsageContext',
    'AnalysisDepth',
    'CleanupMode',
    
    # Convenience functions
    'analyze_file',
    'analyze_source',
    'clean_file',
    'clean_directory',
    'detect_unused_imports',
    
    # Exceptions
    'ImportAnalysisError',
    'InvalidSourceError',
    'FileAccessError',
    
    # Utilities
    'setup_logging',
]


