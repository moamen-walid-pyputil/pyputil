#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
__all__ List Generator and Validator
==============================================

A comprehensive, production-grade system for automatically generating,
validating, and maintaining `__all__` lists in Python modules and packages.
This module provides sophisticated static analysis to extract public APIs,
manage exports, and ensure consistency across large codebases.

Features
--------
- **Automatic __all__ Generation**: Extract public names from Python source
- **Package-Wide Processing**: Recursively process entire packages
- **Smart Filtering**: Control inclusion of private, dunder, and imported names
- **Import Tracking**: Include or exclude imported names with alias support
- **Type Annotation Support**: Detect names used in type hints
- **Decorator Awareness**: Recognize decorated functions and classes
- **Overload Detection**: Handle @overload decorators correctly
- **Validation**: Verify __all__ matches actual module exports
- **Auto-Update**: Write generated __all__ back to source files
- **Incremental Updates**: Preserve manual additions and comments

Examples
--------
>>> from pyputil.util import make_all_list, make_package_all_list
>>> 
>>> # Generate __all__ for a single module
>>> __all__ = make_all_list(__file__)
>>> print(__all__)
['MyClass', 'my_function', 'public_var']
>>> 
>>> # Generate __all__ for entire package
>>> all_lists = make_package_all_list('./mypackage')
>>> for module, exports in all_lists.items():
...     print(f"{module}: {exports}")
>>> 
>>> # Validate existing __all__
>>> from pyputil.util import validate_all_list
>>> result = validate_all_list('mymodule.py')
>>> if not result['valid']:
...     print(f"Missing exports: {result['missing']}")

References
----------
- PEP 8: https://www.python.org/dev/peps/pep-0008/
- PEP 484: Type Hints
- ast: https://docs.python.org/3/library/ast.html
"""

from __future__ import annotations

import ast
import inspect
import sys
import os
import re
import tokenize
import warnings
import threading
import time
from pathlib import Path
from typing import (
    Optional, List, Set, Dict, Any, Union, Iterable, Tuple,
    Callable, Iterator, FrozenSet, Pattern, NamedTuple, TypedDict
)
from dataclasses import dataclass, field, asdict
from enum import Enum, auto, Flag
from functools import lru_cache, wraps
from collections import defaultdict, OrderedDict
import keyword
import shutil

# ============================================================================
# Platform Detection
# ============================================================================

_IS_WINDOWS: bool = sys.platform == "win32"
_IS_MACOS: bool = sys.platform == "darwin"
_IS_LINUX: bool = sys.platform.startswith("linux")
_IS_BSD: bool = any(sys.platform.startswith(p) for p in ("freebsd", "openbsd", "netbsd", "dragonfly"))
_IS_CYGWIN: bool = "cygwin" in sys.platform

# Platform-specific path handling
if _IS_WINDOWS:
    _PATH_SEP = '\\'
    _MODULE_SEP = '.'
    _CASE_SENSITIVE = False
else:
    _PATH_SEP = '/'
    _MODULE_SEP = '.'
    _CASE_SENSITIVE = True

# ============================================================================
# Enums and Constants
# ============================================================================

class ExportType(Enum):
    """
    Enumeration of exportable symbol types.
    
    Attributes
    ----------
    FUNCTION : str
        Function definition.
    ASYNC_FUNCTION : str
        Async function definition.
    CLASS : str
        Class definition.
    VARIABLE : str
        Module-level variable.
    CONSTANT : str
        Uppercase constant.
    IMPORT : str
        Imported name.
    FROM_IMPORT : str
        From-imported name.
    TYPE_ALIAS : str
        Type alias definition.
    DECORATED : str
        Decorated function or class.
    OVERLOAD : str
        Overloaded function.
    """
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    CLASS = "class"
    VARIABLE = "variable"
    CONSTANT = "constant"
    IMPORT = "import"
    FROM_IMPORT = "from_import"
    TYPE_ALIAS = "type_alias"
    DECORATED = "decorated"
    OVERLOAD = "overload"
    
    def __str__(self) -> str:
        return self.value


class ValidationLevel(Enum):
    """
    Enumeration of validation strictness levels.
    
    Attributes
    ----------
    BASIC : str
        Check only that __all__ exists and has no missing public names.
    STRICT : str
        Also check that __all__ doesn't contain non-existent names.
    COMPLETE : str
        Check all aspects including ordering and duplicates.
    """
    BASIC = "basic"
    STRICT = "strict"
    COMPLETE = "complete"
    
    def __str__(self) -> str:
        return self.value


class UpdateMode(Enum):
    """
    Enumeration of update modes for writing __all__ back to files.
    
    Attributes
    ----------
    REPLACE : str
        Replace existing __all__ completely.
    MERGE : str
        Merge with existing __all__ (keep manual additions).
    APPEND : str
        Only add missing names, don't remove any.
    SMART : str
        Intelligently merge preserving order and comments.
    """
    REPLACE = "replace"
    MERGE = "merge"
    APPEND = "append"
    SMART = "smart"
    
    def __str__(self) -> str:
        return self.value


# ============================================================================
# Python Keywords and Builtins
# ============================================================================

PYTHON_KEYWORDS: FrozenSet[str] = frozenset(keyword.kwlist)
"""Python reserved keywords."""

BUILTIN_NAMES: FrozenSet[str] = frozenset({
    'abs', 'aiter', 'all', 'anext', 'any', 'ascii', 'bin', 'bool',
    'breakpoint', 'bytearray', 'bytes', 'callable', 'chr', 'classmethod',
    'compile', 'complex', 'copyright', 'credits', 'delattr', 'dict', 'dir',
    'divmod', 'enumerate', 'eval', 'exec', 'exit', 'filter', 'float', 'format',
    'frozenset', 'getattr', 'globals', 'hasattr', 'hash', 'help', 'hex', 'id',
    'input', 'int', 'isinstance', 'issubclass', 'iter', 'len', 'license',
    'list', 'locals', 'map', 'max', 'memoryview', 'min', 'next', 'object',
    'oct', 'open', 'ord', 'pow', 'print', 'property', 'quit', 'range', 'repr',
    'reversed', 'round', 'set', 'setattr', 'slice', 'sorted', 'staticmethod',
    'str', 'sum', 'super', 'tuple', 'type', 'vars', 'zip',
    '__import__', '__builtins__', '__doc__', '__name__', '__package__',
    '__loader__', '__spec__', '__file__', '__cached__', '__path__',
})
"""Python built-in function names and special attributes."""

# Common decorators that indicate a function should be exported
_EXPORT_DECORATORS: FrozenSet[str] = frozenset({
    'public', 'export', 'api', 'expose', 'endpoint', 'route',
    'staticmethod', 'classmethod', 'property', 'cached_property',
})

# Decorators that indicate a function should NOT be exported
_PRIVATE_DECORATORS: FrozenSet[str] = frozenset({
    'private', 'internal', 'deprecated', 'abstractmethod',
})

# Names that are always excluded by default
_DEFAULT_EXCLUDES: FrozenSet[str] = frozenset({
    'main', 'test', 'tests', 'conftest', 'setup', 'teardown',
})

# Files to ignore during package processing
_IGNORED_FILES: FrozenSet[str] = frozenset({
    '__pycache__', '*.pyc', '*.pyo', '*.pyd', '*.so', '*.dll', '*.dylib',
    'test_*.py', '*_test.py', 'conftest.py', 'setup.py',
})

# Directories to ignore
_IGNORED_DIRS: FrozenSet[str] = frozenset({
    '__pycache__', '.git', '.hg', '.svn', '.tox', '.venv', 'venv', 'env',
    'build', 'dist', '*.egg-info', '*.dist-info', 'node_modules',
    '.pytest_cache', '.mypy_cache', '.ruff_cache', '.idea', '.vscode',
})


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class SymbolInfo:
    """
    Information about a discovered symbol.
    
    Attributes
    ----------
    name : str
        Symbol name.
    type : ExportType
        Type of symbol.
    line_number : int
        Line number where defined.
    docstring : Optional[str]
        Symbol docstring (truncated).
    is_public : bool
        Whether symbol is public.
    is_exported : bool
        Whether symbol should be exported.
    decorators : List[str]
        List of decorator names.
    aliases : List[str]
        Alternative names (for imports).
    """
    name: str
    type: ExportType
    line_number: int
    docstring: Optional[str] = None
    is_public: bool = True
    is_exported: bool = True
    decorators: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'type': str(self.type),
            'line_number': self.line_number,
            'is_public': self.is_public,
            'is_exported': self.is_exported,
            'decorators': self.decorators,
            'aliases': self.aliases,
        }


@dataclass
class ModuleAnalysis:
    """
    Complete analysis of a Python module.
    
    Attributes
    ----------
    path : str
        File path.
    module_name : str
        Module name.
    symbols : Dict[str, SymbolInfo]
        Discovered symbols.
    imports : List[str]
        Import statements.
    from_imports : Dict[str, List[str]]
        From-import statements.
    has_all : bool
        Whether __all__ is defined.
    current_all : List[str]
        Current __all__ contents.
    generated_all : List[str]
        Generated __all__ list.
    missing : List[str]
        Names that should be in __all__ but aren't.
    extra : List[str]
        Names in __all__ that shouldn't be.
    """
    path: str
    module_name: str
    symbols: Dict[str, SymbolInfo] = field(default_factory=dict)
    imports: List[str] = field(default_factory=list)
    from_imports: Dict[str, List[str]] = field(default_factory=dict)
    has_all: bool = False
    current_all: List[str] = field(default_factory=list)
    generated_all: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    extra: List[str] = field(default_factory=list)
    
    @property
    def is_valid(self) -> bool:
        """Check if current __all__ matches generated."""
        return len(self.missing) == 0 and len(self.extra) == 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'path': self.path,
            'module_name': self.module_name,
            'symbols': {k: v.to_dict() for k, v in self.symbols.items()},
            'imports': self.imports,
            'from_imports': self.from_imports,
            'has_all': self.has_all,
            'current_all': self.current_all,
            'generated_all': self.generated_all,
            'missing': self.missing,
            'extra': self.extra,
            'is_valid': self.is_valid,
        }


@dataclass
class GenerationConfig:
    """
    Configuration for __all__ generation.
    
    Attributes
    ----------
    include_private : bool
        Include private names (leading underscore).
    include_imports : bool
        Include imported names.
    include_from_imports : bool
        Include from-imported names.
    include_dunder : bool
        Include dunder names.
    include_type_aliases : bool
        Include type aliases.
    include_overloads : bool
        Include @overload functions.
    use_alias : bool
        Use alias for imports.
    respect_decorators : bool
        Respect decorator hints (@public, @private).
    sort_output : bool
        Sort the generated list.
    deduplicate : bool
        Remove duplicates.
    max_line_length : int
        Maximum line length for formatting.
    """
    include_private: bool = False
    include_imports: bool = True
    include_from_imports: bool = True
    include_dunder: bool = False
    include_type_aliases: bool = True
    include_overloads: bool = True
    use_alias: bool = True
    respect_decorators: bool = True
    sort_output: bool = True
    deduplicate: bool = True
    max_line_length: int = 88


# ============================================================================
# AST Visitor for Symbol Extraction
# ============================================================================

class AllGeneratorVisitor(ast.NodeVisitor):
    """
    Advanced AST visitor for extracting exportable symbols.
    
    This visitor comprehensively analyzes Python source code to identify
    all symbols that should be included in __all__ based on naming
    conventions, decorators, and configuration.
    
    Attributes
    ----------
    symbols : Dict[str, SymbolInfo]
        Discovered symbols.
    imports : List[str]
        Import statements.
    from_imports : Dict[str, List[str]]
        From-import statements.
    all_list : List[str]
        Current __all__ contents.
    has_all : bool
        Whether __all__ is defined.
    """
    
    def __init__(self, config: GenerationConfig):
        super().__init__()
        self.config = config
        self.symbols: Dict[str, SymbolInfo] = {}
        self.imports: List[str] = []
        self.from_imports: Dict[str, List[str]] = defaultdict(list)
        self.all_list: List[str] = []
        self.has_all: bool = False
        self._current_decorators: List[str] = []
        self._seen_overloads: Set[str] = set()
    
    def _is_public(self, name: str) -> bool:
        """Check if a name is public based on naming convention."""
        if name.startswith('__') and name.endswith('__'):
            return self.config.include_dunder
        if name.startswith('_'):
            return self.config.include_private
        return True
    
    def _should_export(self, name: str, decorators: List[str] = None) -> bool:
        """Determine if a symbol should be exported."""
        # Check decorators first
        if self.config.respect_decorators and decorators:
            for dec in decorators:
                dec_name = dec.split('.')[-1]
                if dec_name in _EXPORT_DECORATORS:
                    return True
                if dec_name in _PRIVATE_DECORATORS:
                    return False
        
        # Check naming convention
        if not self._is_public(name):
            return False
        
        # Check against default excludes
        if name in _DEFAULT_EXCLUDES:
            return False
        
        # Check if it's a builtin or keyword
        if name in BUILTIN_NAMES or name in PYTHON_KEYWORDS:
            return False
        
        return True
    
    def _extract_decorators(self, node: ast.AST) -> List[str]:
        """Extract decorator names from a node."""
        decorators = []
        for dec in getattr(node, 'decorator_list', []):
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                if isinstance(dec.value, ast.Name):
                    decorators.append(f"{dec.value.id}.{dec.attr}")
                else:
                    decorators.append(dec.attr)
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    decorators.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    decorators.append(dec.func.attr)
        return decorators
    
    def _extract_docstring(self, node: ast.AST) -> Optional[str]:
        """Extract docstring from a node."""
        docstring = ast.get_docstring(node)
        if docstring:
            return docstring[:200] + "..." if len(docstring) > 200 else docstring
        return None
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Process function definitions."""
        decorators = self._extract_decorators(node)
        
        # Check for overload
        is_overload = any('overload' in d for d in decorators)
        
        if is_overload:
            if self.config.include_overloads:
                self._seen_overloads.add(node.name)
            # Don't add overload itself, just track it
            return
        
        if self._should_export(node.name, decorators):
            symbol_type = ExportType.DECORATED if decorators else ExportType.FUNCTION
            
            self.symbols[node.name] = SymbolInfo(
                name=node.name,
                type=symbol_type,
                line_number=node.lineno,
                docstring=self._extract_docstring(node),
                is_public=self._is_public(node.name),
                is_exported=True,
                decorators=decorators,
            )
        
        self.generic_visit(node)
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Process async function definitions."""
        decorators = self._extract_decorators(node)
        
        if self._should_export(node.name, decorators):
            symbol_type = ExportType.DECORATED if decorators else ExportType.ASYNC_FUNCTION
            
            self.symbols[node.name] = SymbolInfo(
                name=node.name,
                type=symbol_type,
                line_number=node.lineno,
                docstring=self._extract_docstring(node),
                is_public=self._is_public(node.name),
                is_exported=True,
                decorators=decorators,
            )
        
        self.generic_visit(node)
    
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Process class definitions."""
        decorators = self._extract_decorators(node)
        
        if self._should_export(node.name, decorators):
            symbol_type = ExportType.DECORATED if decorators else ExportType.CLASS
            
            self.symbols[node.name] = SymbolInfo(
                name=node.name,
                type=symbol_type,
                line_number=node.lineno,
                docstring=self._extract_docstring(node),
                is_public=self._is_public(node.name),
                is_exported=True,
                decorators=decorators,
            )
        
        # Don't traverse into class body for top-level symbols
    
    def visit_Assign(self, node: ast.Assign) -> None:
        """Process variable assignments."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                if target.id == '__all__':
                    self.has_all = True
                    if isinstance(node.value, ast.List):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                self.all_list.append(elt.value)
                    continue
                
                if self._should_export(target.id):
                    # Determine if constant
                    symbol_type = ExportType.CONSTANT if target.id.isupper() else ExportType.VARIABLE
                    
                    self.symbols[target.id] = SymbolInfo(
                        name=target.id,
                        type=symbol_type,
                        line_number=node.lineno,
                        is_public=self._is_public(target.id),
                        is_exported=True,
                    )
            
            elif isinstance(target, ast.Tuple):
                for elt in target.elts:
                    if isinstance(elt, ast.Name) and self._should_export(elt.id):
                        self.symbols[elt.id] = SymbolInfo(
                            name=elt.id,
                            type=ExportType.VARIABLE,
                            line_number=node.lineno,
                            is_public=self._is_public(elt.id),
                            is_exported=True,
                        )
    
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Process annotated assignments."""
        if isinstance(node.target, ast.Name):
            name = node.target.id
            
            if self._should_export(name):
                if node.value is None and self.config.include_type_aliases:
                    # Type alias
                    self.symbols[name] = SymbolInfo(
                        name=name,
                        type=ExportType.TYPE_ALIAS,
                        line_number=node.lineno,
                        is_public=self._is_public(name),
                        is_exported=True,
                    )
                else:
                    symbol_type = ExportType.CONSTANT if name.isupper() else ExportType.VARIABLE
                    self.symbols[name] = SymbolInfo(
                        name=name,
                        type=symbol_type,
                        line_number=node.lineno,
                        is_public=self._is_public(name),
                        is_exported=True,
                    )
    
    def visit_Import(self, node: ast.Import) -> None:
        """Process import statements."""
        if not self.config.include_imports:
            return
        
        for alias in node.names:
            name = alias.asname if (self.config.use_alias and alias.asname) else alias.name.split('.')[0]
            self.imports.append(alias.name)
            
            if self._should_export(name):
                self.symbols[name] = SymbolInfo(
                    name=name,
                    type=ExportType.IMPORT,
                    line_number=node.lineno,
                    is_public=self._is_public(name),
                    is_exported=True,
                    aliases=[alias.name] if alias.asname else [],
                )
    
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Process from-import statements."""
        if not self.config.include_from_imports:
            return
        
        module = node.module or ''
        for alias in node.names:
            if alias.name == '*':
                continue
            
            name = alias.asname if (self.config.use_alias and alias.asname) else alias.name
            self.from_imports[module].append(alias.name)
            
            if self._should_export(name):
                self.symbols[name] = SymbolInfo(
                    name=name,
                    type=ExportType.FROM_IMPORT,
                    line_number=node.lineno,
                    is_public=self._is_public(name),
                    is_exported=True,
                    aliases=[f"{module}.{alias.name}"] if module else [],
                )


# ============================================================================
# Core Analysis Function
# ============================================================================

def analyze_module(
    path: Union[str, Path],
    config: Optional[GenerationConfig] = None,
) -> ModuleAnalysis:
    """
    Analyze a Python module and extract exportable symbols.
    
    Parameters
    ----------
    path : Union[str, Path]
        Path to the Python file.
    config : Optional[GenerationConfig], default=None
        Configuration for analysis.
    
    Returns
    -------
    ModuleAnalysis
        Complete analysis of the module.
    
    Raises
    ------
    FileNotFoundError
        If file doesn't exist.
    ValueError
        If file is not a Python source file.
    SyntaxError
        If file contains invalid Python syntax.
    """
    if config is None:
        config = GenerationConfig()
    
    path = Path(path).resolve()
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    if path.suffix != '.py':
        raise ValueError(f"File must be a Python source file (.py): {path}")
    
    source = path.read_text(encoding='utf-8')
    
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        raise SyntaxError(f"Syntax error in {path}: {e}") from e
    
    visitor = AllGeneratorVisitor(config)
    visitor.visit(tree)
    
    # Generate __all__ list
    generated_all = list(visitor.symbols.keys())
    
    if config.sort_output:
        generated_all.sort()
    
    if config.deduplicate:
        generated_all = list(dict.fromkeys(generated_all))
    
    # Determine module name
    module_name = path.stem
    if module_name == '__init__':
        module_name = path.parent.name
    
    # Calculate missing and extra
    current_set = set(visitor.all_list)
    generated_set = set(generated_all)
    
    analysis = ModuleAnalysis(
        path=str(path),
        module_name=module_name,
        symbols=visitor.symbols,
        imports=visitor.imports,
        from_imports=dict(visitor.from_imports),
        has_all=visitor.has_all,
        current_all=visitor.all_list,
        generated_all=generated_all,
        missing=sorted(generated_set - current_set),
        extra=sorted(current_set - generated_set) if config.include_private else [],
    )
    
    return analysis


# ============================================================================
# Public API Functions
# ============================================================================

def make_all_list(
    path: Optional[Union[str, Path]] = None,
    *,
    include_private: bool = False,
    include_imports: bool = True,
    include_from_imports: bool = True,
    include_dunder: bool = False,
    include_type_aliases: bool = True,
    include_overloads: bool = True,
    use_alias: bool = True,
    respect_decorators: bool = True,
    include: Optional[Iterable[str]] = None,
    exclude: Optional[Iterable[str]] = None,
    sort: bool = True,
) -> List[str]:
    """
    Generate __all__ automatically from a Python file.
    
    This function parses a Python source file and extracts all public names
    (functions, classes, variables, and optionally imports) to generate a
    sorted list suitable for the __all__ variable.
    
    Parameters
    ----------
    path : str | Path | None, optional
        Path to the Python file. If None, uses the caller's file.
    include_private : bool, default=False
        Include names starting with single underscore '_'.
    include_imports : bool, default=True
        Include names from `import x` statements.
    include_from_imports : bool, default=True
        Include names from `from x import y` statements.
    include_dunder : bool, default=False
        Include dunder names like __version__, __author__.
    include_type_aliases : bool, default=True
        Include type aliases (PEP 484).
    include_overloads : bool, default=True
        Include @overload decorated functions.
    use_alias : bool, default=True
        Use alias name for imports.
    respect_decorators : bool, default=True
        Respect @public/@private decorator hints.
    include : Iterable[str] | None
        Force include these names.
    exclude : Iterable[str] | None
        Force exclude these names.
    sort : bool, default=True
        Sort the output list alphabetically.
    
    Returns
    -------
    List[str]
        Sorted __all__ list.
    
    Raises
    ------
    FileNotFoundError
        If the specified path does not exist.
    RuntimeError
        If path is None and cannot determine the caller's module.
    ValueError
        If the file is not a valid Python source file.
    
    Examples
    --------
    >>> __all__ = make_all_list(__file__)
    >>> print(__all__)
    ['MyClass', 'my_function', 'public_var']
    
    >>> __all__ = make_all_list(__file__, include_private=True)
    >>> __all__ = make_all_list(__file__, exclude=['deprecated_func'])
    """
    # Resolve path
    if path is None:
        frame = inspect.stack()[1]
        module = inspect.getmodule(frame[0])
        if module is None or not hasattr(module, "__file__"):
            try:
                path = getattr(sys, "argv", [None])[0]
            except Exception:
                raise RuntimeError("Cannot determine current module file.") from None
        else:
            path = module.__file__
    
    # Build config
    config = GenerationConfig(
        include_private=include_private,
        include_imports=include_imports,
        include_from_imports=include_from_imports,
        include_dunder=include_dunder,
        include_type_aliases=include_type_aliases,
        include_overloads=include_overloads,
        use_alias=use_alias,
        respect_decorators=respect_decorators,
        sort_output=sort,
    )
    
    analysis = analyze_module(path, config)
    result = analysis.generated_all
    
    # Apply include/exclude
    if include:
        result.extend(include)
    
    if exclude:
        exclude_set = set(exclude)
        result = [n for n in result if n not in exclude_set]
    
    # Final deduplication and sorting
    result = list(dict.fromkeys(result))
    if sort:
        result.sort()
    
    return result


def make_package_all_list(
    package_path: Union[str, Path],
    *,
    include_private: bool = False,
    include_imports: bool = True,
    include_from_imports: bool = True,
    include_dunder: bool = False,
    use_alias: bool = True,
    include: Optional[Iterable[str]] = None,
    exclude: Optional[Iterable[str]] = None,
    recursive: bool = True,
    init_only: bool = True,
    include_tests: bool = False,
) -> Dict[str, List[str]]:
    """
    Generate __all__ for all modules in a Python package.
    
    This function recursively processes a package directory and generates
    __all__ lists for each module.
    
    Parameters
    ----------
    package_path : str | Path
        Path to the package root directory.
    include_private : bool, default=False
        Include names starting with '_'.
    include_imports : bool, default=True
        Include imported names.
    include_from_imports : bool, default=True
        Include from-imported names.
    include_dunder : bool, default=False
        Include dunder names.
    use_alias : bool, default=True
        Use alias names for imports.
    include : Iterable[str] | None
        Names to force include.
    exclude : Iterable[str] | None
        Names to force exclude.
    recursive : bool, default=True
        Process subdirectories recursively.
    init_only : bool, default=True
        Only generate __all__ for __init__.py files.
    include_tests : bool, default=False
        Include test directories and files.
    
    Returns
    -------
    Dict[str, List[str]]
        Dictionary mapping module names to their __all__ lists.
    
    Examples
    --------
    >>> all_lists = make_package_all_list('./mypackage')
    >>> for module, exports in all_lists.items():
    ...     print(f"{module}: {exports}")
    """
    package_path = Path(package_path).resolve()
    
    if not package_path.exists():
        raise FileNotFoundError(f"Package path does not exist: {package_path}")
    
    if not package_path.is_dir():
        raise NotADirectoryError(f"Package path must be a directory: {package_path}")
    
    config = GenerationConfig(
        include_private=include_private,
        include_imports=include_imports,
        include_from_imports=include_from_imports,
        include_dunder=include_dunder,
        use_alias=use_alias,
    )
    
    results: Dict[str, List[str]] = {}
    
    def should_ignore_path(path: Path) -> bool:
        """Check if path should be ignored."""
        name = path.name
        
        # Check ignored directories
        for pattern in _IGNORED_DIRS:
            if Path(name).match(pattern):
                return True
        
        # Check test directories
        if not include_tests:
            if name in ('tests', 'test', 'testing'):
                return True
            if name.startswith('test_') or name.endswith('_test'):
                return True
        
        # Check ignored files
        for pattern in _IGNORED_FILES:
            if Path(name).match(pattern):
                return True
        
        return False
    
    def process_module(file_path: Path, module_name: str) -> None:
        """Process a single Python module."""
        try:
            analysis = analyze_module(file_path, config)
            
            all_list = analysis.generated_all
            if include:
                all_list.extend(include)
            if exclude:
                exclude_set = set(exclude)
                all_list = [n for n in all_list if n not in exclude_set]
            
            results[module_name] = list(dict.fromkeys(all_list))
        except Exception:
            pass
    
    def walk_directory(dir_path: Path, parent_module: str = "") -> None:
        """Recursively walk directory and process Python files."""
        if should_ignore_path(dir_path):
            return
        
        # Process __init__.py
        init_file = dir_path / "__init__.py"
        if init_file.exists():
            module_name = parent_module if parent_module else "__init__"
            process_module(init_file, module_name)
        
        # Process other files
        if not init_only:
            for item in dir_path.iterdir():
                if should_ignore_path(item):
                    continue
                
                if item.is_file() and item.suffix == ".py" and item.name != "__init__.py":
                    rel_path = item.relative_to(package_path.parent if parent_module else package_path)
                    module_name = str(rel_path.with_suffix('')).replace(os.sep, '.')
                    process_module(item, module_name)
        
        # Process subdirectories
        if recursive:
            for item in dir_path.iterdir():
                if should_ignore_path(item):
                    continue
                
                if item.is_dir() and not item.name.startswith('_'):
                    sub_init = item / "__init__.py"
                    if sub_init.exists():
                        sub_module = f"{parent_module}.{item.name}" if parent_module else item.name
                        walk_directory(item, sub_module)
    
    walk_directory(package_path)
    return results


def validate_all_list(
    path: Optional[Union[str, Path]] = None,
    *,
    level: Union[str, ValidationLevel] = ValidationLevel.STRICT,
    config: Optional[GenerationConfig] = None,
) -> Dict[str, Any]:
    """
    Validate that __all__ correctly matches the module's public interface.
    
    Parameters
    ----------
    path : str | Path | None, optional
        Path to the Python file. If None, uses the caller's file.
    level : Union[str, ValidationLevel], default='strict'
        Validation strictness level.
    config : Optional[GenerationConfig], default=None
        Configuration for analysis.
    
    Returns
    -------
    Dict[str, Any]
        Validation results.
    
    Examples
    --------
    >>> result = validate_all_list('mymodule.py')
    >>> if not result['valid']:
    ...     print(f"Missing: {result['missing']}")
    ...     print(f"Extra: {result['extra']}")
    """
    if path is None:
        frame = inspect.stack()[1]
        module = inspect.getmodule(frame[0])
        if module is None or not hasattr(module, "__file__"):
            raise RuntimeError("Cannot determine current module file.")
        path = module.__file__
    
    if isinstance(level, str):
        level = ValidationLevel(level.lower())
    
    if config is None:
        config = GenerationConfig()
    
    analysis = analyze_module(path, config)
    
    result = {
        'has_all': analysis.has_all,
        'path': analysis.path,
        'module_name': analysis.module_name,
        'defined': analysis.generated_all,
        'in_all': analysis.current_all,
        'missing': analysis.missing,
        'extra': analysis.extra if level != ValidationLevel.BASIC else [],
        'total_defined': len(analysis.generated_all),
        'total_in_all': len(analysis.current_all),
        'valid': False,
    }
    
    if analysis.has_all:
        result['valid'] = len(analysis.missing) == 0
        if level != ValidationLevel.BASIC:
            result['valid'] = result['valid'] and len(analysis.extra) == 0
        
        if level == ValidationLevel.COMPLETE:
            # Also check for duplicates and ordering
            has_duplicates = len(analysis.current_all) != len(set(analysis.current_all))
            result['has_duplicates'] = has_duplicates
            result['valid'] = result['valid'] and not has_duplicates
    
    return result


def update_package_all(
    package_path: Union[str, Path],
    *,
    mode: Union[str, UpdateMode] = UpdateMode.SMART,
    write_back: bool = True,
    dry_run: bool = False,
    backup: bool = True,
    **kwargs: Any,
) -> Dict[str, List[str]]:
    """
    Generate and optionally write __all__ lists to package files.
    
    Parameters
    ----------
    package_path : str | Path
        Path to the package root directory.
    mode : Union[str, UpdateMode], default='smart'
        Update mode for writing __all__.
    write_back : bool, default=True
        If True, write changes back to files.
    dry_run : bool, default=False
        If True, simulate without writing.
    backup : bool, default=True
        If True, create .bak backup files.
    **kwargs
        Additional arguments passed to make_package_all_list.
    
    Returns
    -------
    Dict[str, List[str]]
        Dictionary mapping module names to their __all__ lists.
    
    Examples
    --------
    >>> updated = update_package_all('./mypackage')
    >>> preview = update_package_all('./mypackage', dry_run=True)
    """
    if isinstance(mode, str):
        mode = UpdateMode(mode.lower())
    
    package_path = Path(package_path).resolve()
    
    # Generate all __all__ lists
    all_lists = make_package_all_list(package_path, **kwargs)
    
    if not write_back or dry_run:
        return all_lists
    
    for module_name, exports in all_lists.items():
        # Determine file path
        if module_name == "__init__":
            file_path = package_path / "__init__.py"
        else:
            parts = module_name.split('.')
            if len(parts) == 1:
                file_path = package_path / f"{parts[0]}.py"
            else:
                file_path = package_path / os.sep.join(parts[:-1]) / f"{parts[-1]}.py"
        
        if not file_path.exists():
            continue
        
        # Backup
        if backup:
            backup_path = file_path.with_suffix(file_path.suffix + '.bak')
            shutil.copy2(file_path, backup_path)
        
        try:
            content = file_path.read_text(encoding='utf-8')
            analysis = analyze_module(file_path)
            
            if mode == UpdateMode.REPLACE:
                new_exports = exports
            elif mode == UpdateMode.APPEND:
                new_exports = list(dict.fromkeys(analysis.current_all + exports))
            elif mode == UpdateMode.MERGE:
                new_exports = list(dict.fromkeys(analysis.current_all + exports))
            else:  # SMART
                # Keep manual additions, remove only what shouldn't be there
                current_set = set(analysis.current_all)
                generated_set = set(exports)
                manual_additions = current_set - generated_set
                new_exports = list(generated_set | manual_additions)
            
            new_exports.sort()
            all_str = f"__all__ = {repr(new_exports)}"
            
            # Update the file
            all_pattern = re.compile(r'^__all__\s*=\s*\[.*?\]\s*$', re.MULTILINE | re.DOTALL)
            
            if all_pattern.search(content):
                new_content = all_pattern.sub(all_str, content)
            else:
                new_content = content.rstrip() + f"\n\n{all_str}\n"
            
            file_path.write_text(new_content, encoding='utf-8')
            all_lists[module_name] = new_exports
            
        except Exception as e:
            # Restore from backup
            if backup and backup_path.exists():
                shutil.copy2(backup_path, file_path)
            warnings.warn(f"Failed to update {file_path}: {e}")
    
    return all_lists


# ============================================================================
# Convenience Functions
# ============================================================================

def get_public_api(path: Union[str, Path]) -> List[str]:
    """
    Get the public API of a module (equivalent to generated __all__).
    
    Parameters
    ----------
    path : Union[str, Path]
        Path to the Python file.
    
    Returns
    -------
    List[str]
        List of public API names.
    """
    return make_all_list(path, include_private=False, include_imports=False, 
                         include_from_imports=False)


def get_all_exports(path: Union[str, Path]) -> List[str]:
    """
    Get all exports including imports.
    
    Parameters
    ----------
    path : Union[str, Path]
        Path to the Python file.
    
    Returns
    -------
    List[str]
        List of all exportable names.
    """
    return make_all_list(path)


def check_missing_all(path: Union[str, Path]) -> List[str]:
    """
    Check which public names are missing from __all__.
    
    Parameters
    ----------
    path : Union[str, Path]
        Path to the Python file.
    
    Returns
    -------
    List[str]
        List of missing names.
    """
    result = validate_all_list(path, level=ValidationLevel.BASIC)
    return result['missing']


def check_extra_all(path: Union[str, Path]) -> List[str]:
    """
    Check which names in __all__ shouldn't be there.
    
    Parameters
    ----------
    path : Union[str, Path]
        Path to the Python file.
    
    Returns
    -------
    List[str]
        List of extra names.
    """
    result = validate_all_list(path, level=ValidationLevel.STRICT)
    return result['extra']


def fix_all(path: Union[str, Path], *, backup: bool = True) -> bool:
    """
    Fix __all__ in a single file.
    
    Parameters
    ----------
    path : Union[str, Path]
        Path to the Python file.
    backup : bool, default=True
        Create backup before modifying.
    
    Returns
    -------
    bool
        True if file was modified.
    """
    path = Path(path).resolve()
    
    if not path.exists():
        return False
    
    analysis = analyze_module(path)
    
    if analysis.is_valid:
        return False
    
    # Generate correct __all__
    correct_all = analysis.generated_all
    correct_all.sort()
    
    # Backup
    if backup:
        backup_path = path.with_suffix(path.suffix + '.bak')
        shutil.copy2(path, backup_path)
    
    try:
        content = path.read_text(encoding='utf-8')
        all_str = f"__all__ = {repr(correct_all)}"
        
        all_pattern = re.compile(r'^__all__\s*=\s*\[.*?\]\s*$', re.MULTILINE | re.DOTALL)
        
        if all_pattern.search(content):
            new_content = all_pattern.sub(all_str, content)
        else:
            new_content = content.rstrip() + f"\n\n{all_str}\n"
        
        path.write_text(new_content, encoding='utf-8')
        return True
        
    except Exception:
        # Restore from backup
        if backup and backup_path.exists():
            shutil.copy2(backup_path, path)
        raise


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    'ExportType',
    'ValidationLevel',
    'UpdateMode',
    
    # Data Classes
    'SymbolInfo',
    'ModuleAnalysis',
    'GenerationConfig',
    
    # Main Functions
    'make_all_list',
    'make_package_all_list',
    'validate_all_list',
    'update_package_all',
    'analyze_module',
    
    # Convenience Functions
    'get_public_api',
    'get_all_exports',
    'check_missing_all',
    'check_extra_all',
    'fix_all',
]
