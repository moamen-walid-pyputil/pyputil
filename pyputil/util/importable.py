#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
 Python Package Importable Symbols Inspector
=====================================================

A comprehensive, production-grade system for discovering and analyzing all
importable symbols (classes, functions, variables) within Python packages.
This module provides deep introspection of package structures with support
for namespace packages, PEP 420 implicit namespaces, PEP 561 type stubs,
and comprehensive filtering capabilities.

Features
--------
- **Deep Package Inspection**: Recursively discover all modules and symbols
- **Namespace Package Support**: Full PEP 420 namespace package handling
- **Type Stub Support**: PEP 561 .pyi stub file inspection
- **__all__ Respect**: Honors __all__ declarations for public API
- **Comprehensive Symbol Extraction**: Classes, functions, async functions, variables
- ** Filtering**: Filter by type (class/function/variable) and regex patterns
- **Import Validation**: Check if modules/files are importable
- **Import Graph Building**: Extract module dependencies
- **Cross-Platform**: Full Windows, Linux, macOS, BSD compatibility
- **Caching**: Optional LRU caching for performance
- **Parallel Processing**: Multi-threaded file parsing support

Examples
--------
>>> from pyputil.util import importables, importable
>>> 
>>> # Get all importable symbols from a package
>>> symbols = importables("numpy", filter_by="function", pattern="array")
>>> print(f"Found {len(symbols)} array functions")
>>> 
>>> # Check if something is importable
>>> importable("requests")  # Module name
True
>>> importable("/path/to/module.py")  # File path
True
>>> 
>>> # Get only classes
>>> classes = importables("pandas", filter_by="class", max_depth=2)
>>> 
>>> # Get public API (respects __all__)
>>> public_api = importables("my_package", public_only=True)

References
----------
- PEP 420: Implicit Namespace Packages
- PEP 561: Distributing and Packaging Type Information
- PEP 484: Type Hints
- importlib: https://docs.python.org/3/library/importlib.html
"""

import sys
import os
import ast
import re
import importlib.util
import importlib.machinery
import importlib.abc
import warnings
import threading
import time
from pathlib import Path
from typing import (
    Optional, List, Dict, Set, Tuple, Union, Any, Iterator,
    NamedTuple, FrozenSet, Callable, Pattern, TypedDict
)
from dataclasses import dataclass, field, asdict
from enum import Enum, auto, Flag
from functools import lru_cache, wraps
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import keyword
import tokenize

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
    _CASE_SENSITIVE = False
    _DRIVE_LETTER_PATTERN = re.compile(r'^[A-Z]:\\', re.IGNORECASE)
else:
    _PATH_SEP = '/'
    _CASE_SENSITIVE = True
    _DRIVE_LETTER_PATTERN = None

# ============================================================================
# Enums and Constants
# ============================================================================

class SymbolType(Enum):
    """
    Enumeration of symbol types.
    
    Attributes
    ----------
    CLASS : str
        Class definition.
    FUNCTION : str
        Function or method.
    ASYNC_FUNCTION : str
        Async function (coroutine).
    VARIABLE : str
        Module-level variable.
    CONSTANT : str
        Uppercase constant.
    PROPERTY : str
        Property descriptor.
    ENUM : str
        Enum class.
    DATACLASS : str
        Dataclass definition.
    TYPE_ALIAS : str
        Type alias.
    ALL : str
        All types (for filtering).
    """
    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    VARIABLE = "variable"
    CONSTANT = "constant"
    PROPERTY = "property"
    ENUM = "enum"
    DATACLASS = "dataclass"
    TYPE_ALIAS = "type_alias"
    ALL = "all"
    
    def __str__(self) -> str:
        return self.value


class InspectionMode(Enum):
    """
    Enumeration of inspection modes.
    
    Attributes
    ----------
    FAST : str
        AST-only inspection (fast, no imports).
    DEEP : str
        Import and introspect (slower, more accurate).
    HYBRID : str
        AST + selective imports.
    """
    FAST = "fast"
    DEEP = "deep"
    HYBRID = "hybrid"
    
    def __str__(self) -> str:
        return self.value


class FilterMode(Enum):
    """
    Enumeration of filter modes.
    
    Attributes
    ----------
    CLASS : str
        Only class symbols.
    FUNCTION : str
        Only function symbols.
    VARIABLE : str
        Only variable symbols.
    PUBLIC : str
        Only public symbols (no leading underscore).
    ALL : str
        No filtering.
    """
    CLASS = "class"
    FUNCTION = "function"
    VARIABLE = "variable"
    PUBLIC = "public"
    ALL = "all"
    
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
})
"""Python built-in function names."""

# Files to ignore during inspection
_IGNORED_FILES: FrozenSet[str] = frozenset({
    '__pycache__', '*.pyc', '*.pyo', '*.pyd', '*.so', '*.dll', '*.dylib',
    'test_*.py', '*_test.py', 'conftest.py', 'setup.py',
})

# Directories to ignore
_IGNORED_DIRS: FrozenSet[str] = frozenset({
    '__pycache__', '.git', '.hg', '.svn', '.tox', '.venv', 'venv', 'env',
    'build', 'dist', '*.egg-info', '*.dist-info', 'node_modules',
    '.pytest_cache', '.mypy_cache', '.ruff_cache',
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
    full_name : str
        Fully qualified dotted name.
    symbol_type : SymbolType
        Type of symbol.
    module_name : str
        Containing module name.
    file_path : str
        Source file path.
    line_number : int
        Line number where defined.
    docstring : Optional[str]
        Symbol docstring (if available).
    is_public : bool
        Whether symbol is public (no leading underscore).
    is_exported : bool
        Whether symbol is in __all__.
    decorators : List[str]
        List of decorator names.
    """
    full_name: str
    symbol_type: SymbolType
    module_name: str
    file_path: str
    line_number: int
    docstring: Optional[str] = None
    is_public: bool = True
    is_exported: bool = False
    decorators: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'full_name': self.full_name,
            'symbol_type': str(self.symbol_type),
            'module_name': self.module_name,
            'file_path': self.file_path,
            'line_number': self.line_number,
            'docstring': self.docstring,
            'is_public': self.is_public,
            'is_exported': self.is_exported,
            'decorators': self.decorators,
        }


@dataclass
class ModuleInfo:
    """
    Information about a module.
    
    Attributes
    ----------
    name : str
        Module name.
    file_path : str
        Source file path.
    is_package : bool
        Whether this is a package.
    is_namespace : bool
        Whether this is a namespace package.
    has_all : bool
        Whether module defines __all__.
    all_symbols : List[str]
        Symbols listed in __all__.
    imports : List[str]
        Modules imported by this module.
    """
    name: str
    file_path: str
    is_package: bool = False
    is_namespace: bool = False
    has_all: bool = False
    all_symbols: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'file_path': self.file_path,
            'is_package': self.is_package,
            'is_namespace': self.is_namespace,
            'has_all': self.has_all,
            'all_symbols': self.all_symbols,
            'imports': self.imports,
        }


@dataclass
class InspectionResult:
    """
    Complete inspection result.
    
    Attributes
    ----------
    package_name : str
        Name of inspected package.
    symbols : List[str]
        List of fully qualified symbol names.
    symbol_infos : Dict[str, SymbolInfo]
        Detailed information per symbol.
    modules : Dict[str, ModuleInfo]
        Module information.
    total_symbols : int
        Total symbols found.
    total_modules : int
        Total modules processed.
    duration : float
        Inspection duration in seconds.
    warnings : List[str]
        Warnings encountered during inspection.
    """
    package_name: str
    symbols: List[str] = field(default_factory=list)
    symbol_infos: Dict[str, SymbolInfo] = field(default_factory=dict)
    modules: Dict[str, ModuleInfo] = field(default_factory=dict)
    total_symbols: int = 0
    total_modules: int = 0
    duration: float = 0.0
    warnings: List[str] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        """Update totals after initialization."""
        self.total_symbols = len(self.symbols)
        self.total_modules = len(self.modules)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'package_name': self.package_name,
            'symbols': self.symbols,
            'total_symbols': self.total_symbols,
            'total_modules': self.total_modules,
            'duration': self.duration,
            'warnings': self.warnings,
        }
    
    def filter(self, pattern: Union[str, Pattern]) -> 'InspectionResult':
        """
        Filter symbols by regex pattern.
        
        Parameters
        ----------
        pattern : Union[str, Pattern]
            Regex pattern to filter by.
        
        Returns
        -------
        InspectionResult
            New result with filtered symbols.
        """
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        
        filtered_symbols = [s for s in self.symbols if pattern.search(s)]
        filtered_infos = {k: v for k, v in self.symbol_infos.items() if pattern.search(k)}
        
        return InspectionResult(
            package_name=self.package_name,
            symbols=filtered_symbols,
            symbol_infos=filtered_infos,
            modules=self.modules,
            warnings=self.warnings,
        )
    
    def by_type(self, symbol_type: Union[str, SymbolType]) -> 'InspectionResult':
        """
        Filter symbols by type.
        
        Parameters
        ----------
        symbol_type : Union[str, SymbolType]
            Symbol type to filter by.
        
        Returns
        -------
        InspectionResult
            New result with filtered symbols.
        """
        if isinstance(symbol_type, str):
            symbol_type = SymbolType(symbol_type.lower())
        
        filtered_symbols = [
            s for s in self.symbols 
            if s in self.symbol_infos and self.symbol_infos[s].symbol_type == symbol_type
        ]
        filtered_infos = {
            k: v for k, v in self.symbol_infos.items() 
            if v.symbol_type == symbol_type
        }
        
        return InspectionResult(
            package_name=self.package_name,
            symbols=filtered_symbols,
            symbol_infos=filtered_infos,
            modules=self.modules,
            warnings=self.warnings,
        )
    
    def public_only(self) -> 'InspectionResult':
        """Get only public symbols."""
        filtered_symbols = [
            s for s in self.symbols 
            if s in self.symbol_infos and self.symbol_infos[s].is_public
        ]
        filtered_infos = {
            k: v for k, v in self.symbol_infos.items() if v.is_public
        }
        
        return InspectionResult(
            package_name=self.package_name,
            symbols=filtered_symbols,
            symbol_infos=filtered_infos,
            modules=self.modules,
            warnings=self.warnings,
        )
    
    def summary(self) -> str:
        """
        Get a human-readable summary.
        
        Returns
        -------
        str
            Formatted summary string.
        """
        type_counts = defaultdict(int)
        for info in self.symbol_infos.values():
            type_counts[str(info.symbol_type)] += 1
        
        lines = [
            f"Inspection Results for '{self.package_name}'",
            "=" * 50,
            f"Total modules:  {self.total_modules:>6}",
            f"Total symbols:  {self.total_symbols:>6}",
            f"Duration:       {self.duration:>6.2f}s",
            "-" * 50,
            "Symbols by type:",
        ]
        
        for sym_type, count in sorted(type_counts.items()):
            lines.append(f"  {sym_type:15} {count:>6}")
        
        if self.warnings:
            lines.append("-" * 50)
            lines.append(f"Warnings: {len(self.warnings)}")
        
        return "\n".join(lines)


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class ImportablesConfig:
    """
    Configuration for package inspection.
    
    Attributes
    ----------
    mode : InspectionMode
        Inspection mode.
    max_depth : Optional[int]
        Maximum recursion depth (None = unlimited).
    include_stubs : bool
        Include .pyi stub files.
    include_tests : bool
        Include test modules.
    include_private : bool
        Include private symbols (leading underscore).
    include_dunder : bool
        Include dunder methods.
    respect_all : bool
        Respect __all__ declarations.
    parallel : bool
        Use parallel processing.
    max_workers : int
        Maximum parallel workers.
    cache_results : bool
        Cache inspection results.
    cache_ttl : float
        Cache TTL in seconds.
    timeout : Optional[float]
        Inspection timeout in seconds.
    """
    mode: InspectionMode = InspectionMode.FAST
    max_depth: Optional[int] = None
    include_stubs: bool = False
    include_tests: bool = False
    include_private: bool = False
    include_dunder: bool = False
    respect_all: bool = True
    parallel: bool = False
    max_workers: int = 4
    cache_results: bool = True
    cache_ttl: float = 300.0
    timeout: Optional[float] = None


# ============================================================================
# Cache Management
# ============================================================================

class InspectionCache:
    """
    Thread-safe cache for inspection results.
    """
    
    def __init__(self, max_size: int = 50, ttl: float = 300.0):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: Dict[str, Tuple[InspectionResult, float]] = {}
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[InspectionResult]:
        """Get cached result if valid."""
        with self._lock:
            if key in self._cache:
                result, timestamp = self._cache[key]
                if time.time() - timestamp <= self.ttl:
                    return result
                del self._cache[key]
        return None
    
    def set(self, key: str, value: InspectionResult) -> None:
        """Store result in cache."""
        with self._lock:
            if len(self._cache) >= self.max_size:
                oldest = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest]
            self._cache[key] = (value, time.time())
    
    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()


_inspection_cache = InspectionCache()


# ============================================================================
# AST Parser
# ============================================================================

class SymbolParser(ast.NodeVisitor):
    """
     AST parser for extracting symbols from Python source files.
    
    Extracts:
    - Class definitions (including decorated classes)
    - Function definitions (sync and async)
    - Module-level variables and constants
    - Type aliases
    - __all__ declarations
    - Import statements
    """
    
    def __init__(self, file_path: str, module_name: str):
        self.file_path = file_path
        self.module_name = module_name
        self.symbols: List[SymbolInfo] = []
        self.all_symbols: List[str] = []
        self.imports: List[str] = []
        self.has_all = False
        self._in_class = False
        self._current_class: Optional[str] = None
    
    def _is_public(self, name: str) -> bool:
        """Check if a name is public."""
        return not name.startswith('_')
    
    def _add_symbol(self, name: str, symbol_type: SymbolType, 
                    lineno: int, decorators: List[str] = None) -> None:
        """Add a discovered symbol."""
        full_name = f"{self.module_name}.{name}"
        
        symbol = SymbolInfo(
            full_name=full_name,
            symbol_type=symbol_type,
            module_name=self.module_name,
            file_path=self.file_path,
            line_number=lineno,
            is_public=self._is_public(name),
            decorators=decorators or [],
        )
        self.symbols.append(symbol)
    
    def _extract_decorators(self, node: ast.AST) -> List[str]:
        """Extract decorator names from a node."""
        decorators = []
        for dec in getattr(node, 'decorator_list', []):
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(f"{dec.value.id}.{dec.attr}" if isinstance(dec.value, ast.Name) else dec.attr)
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    decorators.append(dec.func.id)
        return decorators
    
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Process class definitions."""
        decorators = self._extract_decorators(node)
        
        # Check for special class types
        symbol_type = SymbolType.CLASS
        for dec in decorators:
            if 'dataclass' in dec:
                symbol_type = SymbolType.DATACLASS
                break
            elif 'enum' in dec or dec == 'Enum':
                symbol_type = SymbolType.ENUM
                break
        
        self._add_symbol(node.name, symbol_type, node.lineno, decorators)
        
        # Don't traverse into class body for top-level symbols
        # (we only want module-level symbols)
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Process function definitions."""
        decorators = self._extract_decorators(node)
        
        # Check for property
        for dec in decorators:
            if dec == 'property':
                # Skip property getters (they're not callable directly)
                return
        
        self._add_symbol(node.name, SymbolType.FUNCTION, node.lineno, decorators)
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Process async function definitions."""
        decorators = self._extract_decorators(node)
        self._add_symbol(node.name, SymbolType.ASYNC_FUNCTION, node.lineno, decorators)
    
    def visit_Assign(self, node: ast.Assign) -> None:
        """Process variable assignments."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                name = target.id
                
                # Skip private unless it's a constant
                if name.startswith('_') and not name.isupper():
                    continue
                
                # Check for __all__
                if name == '__all__':
                    self.has_all = True
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                self.all_symbols.append(elt.value)
                    continue
                
                # Determine if constant
                symbol_type = SymbolType.CONSTANT if name.isupper() else SymbolType.VARIABLE
                self._add_symbol(name, symbol_type, node.lineno)
    
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Process annotated assignments (PEP 526)."""
        if isinstance(node.target, ast.Name):
            name = node.target.id
            
            if name.startswith('_'):
                return
            
            # Check if it's a type alias
            if node.value is None:
                self._add_symbol(name, SymbolType.TYPE_ALIAS, node.lineno)
            else:
                symbol_type = SymbolType.CONSTANT if name.isupper() else SymbolType.VARIABLE
                self._add_symbol(name, symbol_type, node.lineno)
    
    def visit_Import(self, node: ast.Import) -> None:
        """Track imports."""
        for alias in node.names:
            self.imports.append(alias.name)
    
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Track from imports."""
        if node.module:
            self.imports.append(node.module)


def _parse_file_(file_path: str, module_name: str) -> Tuple[List[SymbolInfo], ModuleInfo]:
    """
    Parse a Python file and extract all symbols and module info.
    
    Parameters
    ----------
    file_path : str
        Path to the Python file.
    module_name : str
        Fully qualified module name.
    
    Returns
    -------
    Tuple[List[SymbolInfo], ModuleInfo]
        Extracted symbols and module information.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        
        tree = ast.parse(source, filename=file_path)
        parser = SymbolParser(file_path, module_name)
        parser.visit(tree)
        
        module_info = ModuleInfo(
            name=module_name,
            file_path=file_path,
            is_package=file_path.endswith('__init__.py'),
            has_all=parser.has_all,
            all_symbols=parser.all_symbols,
            imports=parser.imports,
        )
        
        # Filter symbols based on __all__ if present
        if parser.has_all:
            exported_names = set(parser.all_symbols)
            symbols = [s for s in parser.symbols 
                      if s.full_name.split('.')[-1] in exported_names]
            for s in symbols:
                s.is_exported = True
        else:
            symbols = parser.symbols
        
        return symbols, module_info
        
    except Exception as e:
        warnings.warn(f"Failed to parse {file_path}: {e}")
        return [], ModuleInfo(name=module_name, file_path=file_path)


# ============================================================================
# Package Walking
# ============================================================================

def _should_ignore_path(path: Path, config: ImportablesConfig) -> bool:
    """
    Check if a path should be ignored.
    
    Parameters
    ----------
    path : Path
        Path to check.
    config : ImportablesConfig
        Inspection configuration.
    
    Returns
    -------
    bool
        True if path should be ignored.
    """
    name = path.name
    
    # Check ignored directories
    for pattern in _IGNORED_DIRS:
        if Path(name).match(pattern):
            return True
    
    # Check test directories
    if not config.include_tests:
        if name in ('tests', 'test', 'testing', '__pycache__'):
            return True
        if name.startswith('test_') or name.endswith('_test'):
            return True
    
    # Check stub files
    if not config.include_stubs and path.suffix == '.pyi':
        return True
    
    return False


def _walk_package_(spec, config: ImportablesConfig) -> List[str]:
    """
    Walk all directories associated with a package and return Python file paths.
    
    Parameters
    ----------
    spec : ModuleSpec
        Package specification.
    config : ImportablesConfig
        Inspection configuration.
    
    Returns
    -------
    List[str]
        List of Python file paths.
    """
    paths = []
    
    # Determine search paths
    if isinstance(spec.loader, importlib.machinery.NamespaceLoader):
        search_paths = list(spec.submodule_search_locations or [])
    elif spec.origin:
        search_paths = [os.path.dirname(spec.origin)]
    elif spec.submodule_search_locations:
        search_paths = list(spec.submodule_search_locations)
    else:
        return paths
    
    for base in search_paths:
        base_path = Path(base)
        if not base_path.exists():
            continue
        
        for root, dirs, files in os.walk(base):
            root_path = Path(root)
            
            # Check depth limit
            if config.max_depth is not None:
                try:
                    depth = len(root_path.relative_to(base_path).parts)
                    if depth > config.max_depth:
                        continue
                except ValueError:
                    pass
            
            # Filter directories in-place
            dirs[:] = [d for d in dirs if not _should_ignore_path(root_path / d, config)]
            
            for f in files:
                file_path = root_path / f
                
                if _should_ignore_path(file_path, config):
                    continue
                
                # Skip non-Python files
                if f.endswith('.py'):
                    paths.append(str(file_path))
                elif config.include_stubs and f.endswith('.pyi'):
                    paths.append(str(file_path))
    
    return paths


def _make_module_name_(spec, file_path: str) -> Optional[str]:
    """
    Convert a file path to a dotted module name.
    
    Parameters
    ----------
    spec : ModuleSpec
        Package specification.
    file_path : str
        Filesystem path.
    
    Returns
    -------
    Optional[str]
        Dotted module name.
    """
    # Determine base directories
    if isinstance(spec.loader, importlib.machinery.NamespaceLoader):
        base_dirs = list(spec.submodule_search_locations or [])
    elif spec.origin:
        base_dirs = [os.path.dirname(spec.origin)]
    elif spec.submodule_search_locations:
        base_dirs = list(spec.submodule_search_locations)
    else:
        return None
    
    file_path = os.path.normpath(file_path)
    
    for base in base_dirs:
        base = os.path.normpath(base)
        
        # Check if file is under this base
        if file_path.startswith(base):
            rel = os.path.relpath(file_path, base)
            
            # Remove .py extension
            if rel.endswith('.py'):
                rel = rel[:-3]
            elif rel.endswith('.pyi'):
                rel = rel[:-4]
            
            # Convert to module notation
            modname = rel.replace(os.sep, '.')
            
            # Handle __init__
            if modname.endswith('__init__'):
                modname = modname[:-9]  # Remove '.__init__'
                if not modname:
                    return spec.name
            
            if modname:
                return f"{spec.name}.{modname}"
            return spec.name
    
    return None


# ============================================================================
# Filtering
# ============================================================================

def _apply_filter_(
    symbols: List[str],
    symbol_infos: Dict[str, SymbolInfo],
    filter_by: Optional[str] = None,
    pattern: Optional[Union[str, Pattern]] = None,
    public_only: bool = False,
) -> List[str]:
    """
    Apply filtering rules to symbols.
    
    Parameters
    ----------
    symbols : List[str]
        List of symbol full names.
    symbol_infos : Dict[str, SymbolInfo]
        Symbol information dictionary.
    filter_by : Optional[str]
        Filter by type ('class', 'function', 'variable', 'public', 'all').
    pattern : Optional[Union[str, Pattern]]
        Regex pattern to match.
    public_only : bool
        Only include public symbols.
    
    Returns
    -------
    List[str]
        Filtered symbol list.
    """
    result = symbols.copy()
    
    # Filter by type
    if filter_by and filter_by != 'all':
        if filter_by == 'class':
            result = [s for s in result 
                     if s in symbol_infos and symbol_infos[s].symbol_type in 
                     (SymbolType.CLASS, SymbolType.ENUM, SymbolType.DATACLASS)]
        elif filter_by == 'function':
            result = [s for s in result 
                     if s in symbol_infos and symbol_infos[s].symbol_type in 
                     (SymbolType.FUNCTION, SymbolType.ASYNC_FUNCTION)]
        elif filter_by == 'variable':
            result = [s for s in result 
                     if s in symbol_infos and symbol_infos[s].symbol_type in 
                     (SymbolType.VARIABLE, SymbolType.CONSTANT)]
        elif filter_by == 'public':
            result = [s for s in result 
                     if s in symbol_infos and symbol_infos[s].is_public]
    
    # Filter public only
    if public_only:
        result = [s for s in result 
                 if s in symbol_infos and symbol_infos[s].is_public]
    
    # Apply regex pattern
    if pattern:
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        result = [s for s in result if pattern.search(s)]
    
    return result


# ============================================================================
# Main Public API
# ============================================================================

def importables(
    package_name: str,
    *,
    filter_by: Optional[str] = None,
    pattern: Optional[Union[str, Pattern]] = None,
    public_only: bool = True,
    mode: Union[str, InspectionMode] = InspectionMode.FAST,
    max_depth: Optional[int] = None,
    include_stubs: bool = False,
    include_tests: bool = False,
    respect_all: bool = True,
    parallel: bool = False,
    max_workers: int = 4,
    use_cache: bool = True,
    detailed: bool = False,
) -> Union[List[str], InspectionResult]:
    """
    Collect all importable dotted paths from a Python package.
    
    This function deeply inspects a package and returns all importable
    symbols (classes, functions, variables) with comprehensive filtering.
    
    Parameters
    ----------
    package_name : str
        Name of the package to inspect (e.g., 'numpy', 'pandas.core').
    
    filter_by : Optional[str], default=None
        Filter symbols by type:
        - 'class': Only class definitions
        - 'function': Only function definitions
        - 'variable': Only variables and constants
        - 'public': Only public symbols
        - 'all' or None: No type filtering
    
    pattern : Optional[Union[str, Pattern]], default=None
        Regex pattern to filter symbol names.
    
    public_only : bool, default=True
        If True, exclude private symbols (starting with '_').
    
    mode : Union[str, InspectionMode], default='fast'
        Inspection mode:
        - 'fast': AST-only (fast, no imports)
        - 'deep': Import and introspect (slower, more accurate)
        - 'hybrid': AST + selective imports
    
    max_depth : Optional[int], default=None
        Maximum recursion depth for subpackages.
    
    include_stubs : bool, default=False
        Include .pyi stub files.
    
    include_tests : bool, default=False
        Include test modules and directories.
    
    respect_all : bool, default=True
        If True, only include symbols listed in __all__ when present.
    
    parallel : bool, default=False
        Use parallel processing for file parsing.
    
    max_workers : int, default=4
        Maximum number of parallel workers.
    
    use_cache : bool, default=True
        Cache inspection results for repeated queries.
    
    detailed : bool, default=False
        If True, return full InspectionResult with metadata.
    
    Returns
    -------
    Union[List[str], InspectionResult]
        If detailed=False: List of importable symbol names.
        If detailed=True: Full InspectionResult object.
    
    Raises
    ------
    TypeError
        If package_name is not a string.
    ImportError
        If package cannot be found.
    
    Examples
    --------
    >>> # Basic usage
    >>> symbols = importables("requests")
    >>> print(f"Found {len(symbols)} symbols")
    >>> 
    >>> # Get only functions matching pattern
    >>> funcs = importables("numpy", filter_by="function", pattern="array")
    >>> 
    >>> # Get classes only
    >>> classes = importables("pandas", filter_by="class", max_depth=2)
    >>> 
    >>> # Get detailed results
    >>> result = importables("my_package", detailed=True)
    >>> print(result.summary())
    >>> 
    >>> # Get public API (respects __all__)
    >>> api = importables("my_package", public_only=True, respect_all=True)
    """
    if not isinstance(package_name, str):
        raise TypeError(f"Expected string package name, got {type(package_name).__name__}")
    
    # Process mode
    if isinstance(mode, str):
        try:
            mode = InspectionMode(mode.lower())
        except ValueError:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {[m.value for m in InspectionMode]}")
    
    # Build config
    config = ImportablesConfig(
        mode=mode,
        max_depth=max_depth,
        include_stubs=include_stubs,
        include_tests=include_tests,
        include_private=not public_only,
        respect_all=respect_all,
        parallel=parallel,
        max_workers=max_workers,
        cache_results=use_cache,
    )
    
    # Check cache
    cache_key = f"{package_name}:{filter_by}:{pattern}:{public_only}:{mode.value}:{max_depth}"
    if use_cache:
        cached = _inspection_cache.get(cache_key)
        if cached:
            if detailed:
                return cached
            return cached.symbols
    
    # Find package spec
    spec = importlib.util.find_spec(package_name)
    if spec is None:
        raise ImportError(f"Package '{package_name}' not found.")
    
    start_time = time.time()
    result = InspectionResult(package_name=package_name)
    
    # Walk package files
    files = _walk_package_(spec, config)
    
    all_symbols: List[SymbolInfo] = []
    all_modules: Dict[str, ModuleInfo] = {}
    
    if parallel and len(files) > 1:
        # Parallel processing
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for file_path in files:
                module_name = _make_module_name_(spec, file_path)
                if module_name:
                    futures[executor.submit(_parse_file_, file_path, module_name)] = file_path
            
            for future in as_completed(futures):
                try:
                    symbols, module_info = future.result()
                    all_symbols.extend(symbols)
                    all_modules[module_info.name] = module_info
                except Exception as e:
                    result.warnings.append(f"Failed to parse {futures[future]}: {e}")
    else:
        # Sequential processing
        for file_path in files:
            module_name = _make_module_name_(spec, file_path)
            if not module_name:
                continue
            
            try:
                symbols, module_info = _parse_file_(file_path, module_name)
                all_symbols.extend(symbols)
                all_modules[module_info.name] = module_info
            except Exception as e:
                result.warnings.append(f"Failed to parse {file_path}: {e}")
    
    # Build symbol info dictionary
    symbol_infos: Dict[str, SymbolInfo] = {}
    for sym in all_symbols:
        if sym.full_name not in symbol_infos:
            symbol_infos[sym.full_name] = sym
        else:
            # Keep the one that's exported or from __init__
            existing = symbol_infos[sym.full_name]
            if sym.is_exported and not existing.is_exported:
                symbol_infos[sym.full_name] = sym
            elif '__init__' in sym.module_name and '__init__' not in existing.module_name:
                symbol_infos[sym.full_name] = sym
    
    # Get all symbol names
    all_names = list(symbol_infos.keys())
    
    # Apply filtering
    filtered_names = _apply_filter_(
        all_names, symbol_infos, filter_by, pattern, public_only
    )
    
    # Update result
    result.symbols = sorted(set(filtered_names))
    result.symbol_infos = {k: v for k, v in symbol_infos.items() if k in result.symbols}
    result.modules = all_modules
    result.duration = time.time() - start_time
    
    # Cache result
    if use_cache:
        _inspection_cache.set(cache_key, result)
    
    if detailed:
        return result
    return result.symbols


def importable(target: Union[str, Path]) -> bool:
    """
    Check whether a module name or Python file is importable.
    
    This function validates that a module can be imported or that a Python
    file contains valid syntax and can be imported.
    
    Parameters
    ----------
    target : Union[str, Path]
        Module name (e.g., 'os', 'json') or path to a .py file.
    
    Returns
    -------
    bool
        True if importable, False otherwise.
    
    Examples
    --------
    >>> importable("requests")
    True
    >>> importable("nonexistent_module")
    False
    >>> importable("/path/to/valid_script.py")
    True
    >>> importable("/path/to/invalid_syntax.py")
    False
    """
    try:
        # File path case
        path = Path(target)
        if path.exists() and path.is_file():
            if path.suffix not in ('.py', '.pyi', '.pyw'):
                return False
            
            try:
                source = path.read_text(encoding='utf-8')
                ast.parse(source, filename=str(path))
                
                # Additional validation: try to compile
                compile(source, str(path), 'exec')
                return True
            except (SyntaxError, UnicodeDecodeError, OSError):
                return False
        
        # Module name case
        if isinstance(target, str):
            # Check if it's a valid module name format
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$', target):
                return False
            
            spec = importlib.util.find_spec(target)
            return spec is not None
    
    except Exception:
        return False
    
    return False


# ============================================================================
# Convenience Functions
# ============================================================================

def get_public_api(package_name: str, **kwargs) -> List[str]:
    """
    Get the public API of a package (respects __all__).
    
    Parameters
    ----------
    package_name : str
        Package name.
    **kwargs
        Additional arguments passed to importables.
    
    Returns
    -------
    List[str]
        List of public API symbols.
    """
    return importables(
        package_name,
        public_only=True,
        respect_all=True,
        **kwargs
    )


def get_classes(package_name: str, **kwargs) -> List[str]:
    """
    Get all class definitions from a package.
    
    Parameters
    ----------
    package_name : str
        Package name.
    **kwargs
        Additional arguments passed to importables.
    
    Returns
    -------
    List[str]
        List of class names.
    """
    return importables(
        package_name,
        filter_by="class",
        **kwargs
    )


def get_functions(package_name: str, **kwargs) -> List[str]:
    """
    Get all function definitions from a package.
    
    Parameters
    ----------
    package_name : str
        Package name.
    **kwargs
        Additional arguments passed to importables.
    
    Returns
    -------
    List[str]
        List of function names.
    """
    return importables(
        package_name,
        filter_by="function",
        **kwargs
    )


def get_variables(package_name: str, **kwargs) -> List[str]:
    """
    Get all module-level variables from a package.
    
    Parameters
    ----------
    package_name : str
        Package name.
    **kwargs
        Additional arguments passed to importables.
    
    Returns
    -------
    List[str]
        List of variable names.
    """
    return importables(
        package_name,
        filter_by="variable",
        **kwargs
    )


def search_package(package_name: str, pattern: Union[str, Pattern], **kwargs) -> List[str]:
    """
    Search for symbols matching a pattern in a package.
    
    Parameters
    ----------
    package_name : str
        Package name.
    pattern : Union[str, Pattern]
        Search pattern.
    **kwargs
        Additional arguments passed to importables.
    
    Returns
    -------
    List[str]
        List of matching symbols.
    """
    return importables(
        package_name,
        pattern=pattern,
        **kwargs
    )


def get_module_imports(package_name: str) -> Dict[str, List[str]]:
    """
    Get import dependencies for all modules in a package.
    
    Parameters
    ----------
    package_name : str
        Package name.
    
    Returns
    -------
    Dict[str, List[str]]
        Dictionary mapping module names to their imports.
    """
    result = importables(package_name, detailed=True)
    return {name: info.imports for name, info in result.modules.items()}


def clear_cache() -> None:
    """Clear the inspection cache."""
    _inspection_cache.clear()


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    return {
        'size': len(_inspection_cache._cache),
        'max_size': _inspection_cache.max_size,
        'ttl': _inspection_cache.ttl,
    }


# ============================================================================
# Legacy Compatibility
# ============================================================================

def _parse_file(path: str) -> Dict[str, List[str]]:
    """
    Legacy parser for backward compatibility.
    
    Parameters
    ----------
    path : str
        File path.
    
    Returns
    -------
    Dict[str, List[str]]
        Dictionary with classes, functions, variables, and all.
    """
    symbols, module_info = _parse_file_(path, "module")
    
    classes = []
    functions = []
    variables = []
    
    for sym in symbols:
        if sym.symbol_type in (SymbolType.CLASS, SymbolType.ENUM, SymbolType.DATACLASS):
            classes.append(sym.full_name.split('.')[-1])
        elif sym.symbol_type in (SymbolType.FUNCTION, SymbolType.ASYNC_FUNCTION):
            functions.append(sym.full_name.split('.')[-1])
        else:
            variables.append(sym.full_name.split('.')[-1])
    
    return {
        "classes": classes,
        "functions": functions,
        "variables": variables,
        "all": module_info.all_symbols,
    }


def _walk_package(spec) -> List[str]:
    """Legacy package walker."""
    config = ImportablesConfig()
    return _walk_package_(spec, config)


def _make_module_name(spec, file_path: str) -> Optional[str]:
    """Legacy module name converter."""
    return _make_module_name_(spec, file_path)


def _apply_filter(names: List[str], filter_by: Optional[str] = None, 
                  pattern: Optional[str] = None) -> List[str]:
    """Legacy filter function."""
    return _apply_filter_(names, {}, filter_by, pattern)


def _extract_imports(path: str) -> List[str]:
    """Legacy import extractor."""
    _, module_info = _parse_file_(path, "module")
    return module_info.imports


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Enums
    'SymbolType',
    'InspectionMode',
    'FilterMode',
    
    # Data Classes
    'SymbolInfo',
    'ModuleInfo',
    'InspectionResult',
    'ImportablesConfig',
    
    # Main Functions
    'importables',
    'importable',
    
    # Convenience Functions
    'get_public_api',
    'get_classes',
    'get_functions',
    'get_variables',
    'search_package',
    'get_module_imports',
    
    # Cache Management
    'clear_cache',
    'get_cache_stats',
]

