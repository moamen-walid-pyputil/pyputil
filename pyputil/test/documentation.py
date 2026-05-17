#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
documentation.py
===================

Module Documentation Generator with Multi-Format Support.

This module provides a sophisticated, production-ready documentation generation
system for Python modules. It extracts comprehensive information including
signatures, docstrings, type hints, inheritance hierarchies, and usage examples,
generating beautiful documentation in multiple formats.

Features
--------
- Multi-format output: reStructuredText, Markdown, HTML, Plain Text, JSON
- Comprehensive type hint extraction and formatting with recursive resolution
- Inheritance hierarchy visualization with configurable depth limits
- Method resolution order (MRO) documentation for multiple inheritance scenarios
- Decorator recognition and stack unwrapping for accurate signature extraction
- Property and descriptor handling with accessor method documentation
- Async function/coroutine detection and generator identification
- Class method, static method, abstract method identification and categorization
- Dataclass field extraction with default value and metadata preservation
- Enum member enumeration with value display
- Exception hierarchy documentation
- Module-level constants and configuration variable extraction
- Automatic table of contents generation with hierarchical linking
- Cross-reference linking between documented items within the same output
- Source code linking (GitHub, GitLab, Bitbucket, and custom templates)
- Performance-optimized with thread-safe TTL-based caching
- Thread-safe operation throughout all components
- Extensible plugin system for custom object handlers
- Comprehensive error handling with graceful degradation
- Detailed generation statistics and warning collection

Classes
-------
DocumentationConfig
    Comprehensive configuration dataclass for documentation generation with
    validation and default values for all supported options.
DocumentationContext
    Context object tracking generation state including heading levels,
    generated anchors, cross-references, TOC entries, and error collection.
ObjectHandler
    Abstract base class for custom object documentation handlers defining
    the plugin interface.
ClassHandler
    Specialized handler for class documentation including inheritance trees,
    dataclass fields, enum members, and abstract method identification.
FunctionHandler
    Specialized handler for function/method documentation with signature
    extraction, decorator detection, and async/generator recognition.
VariableHandler
    Specialized handler for variable and constant documentation with type
    inference and value representation.
ModuleDocumenter
    Main documentation generation engine orchestrating the entire pipeline.
DocumentationCache
    Thread-safe, TTL-based LRU cache for generated documentation with
    hit/miss statistics tracking.
PlatformInfo
    Singleton providing cross-platform information and path normalization.

Functions
---------
doc_module
    Primary public API for generating comprehensive module documentation.
module_examples
    Enhanced function for extracting usage examples from module attributes
    with filtering and custom extraction capabilities.
generate_api_docs
    Batch documentation generation for entire package hierarchies.
export_doc
    Export generated documentation to files with automatic format inference.
configure_documentation
    Configure global documentation settings for repeated use.
get_cache_stats
    Retrieve current documentation cache statistics for monitoring.
clear_documentation_cache
    Clear the thread-safe documentation cache.
"""

from __future__ import annotations

import sys
import os
import re
import json
import inspect
import textwrap
import importlib
import warnings
import logging
import hashlib
import threading
import functools
import platform
from abc import ABC, abstractmethod
from collections import defaultdict, OrderedDict, deque, Counter
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict, is_dataclass
from datetime import datetime, timedelta
from enum import Enum, EnumMeta
from pathlib import Path
from types import (
    ModuleType, FunctionType, MethodType, BuiltinFunctionType,
    BuiltinMethodType, LambdaType, CodeType, FrameType,
    TracebackType, GetSetDescriptorType, MemberDescriptorType,
    WrapperDescriptorType, MethodDescriptorType, ClassMethodDescriptorType,
    DynamicClassAttribute, GeneratorType, CoroutineType, AsyncGeneratorType,
    MappingProxyType
)
from typing import (
    Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union,
    Iterator, overload, cast, get_origin, get_args, get_type_hints,
    ForwardRef, _GenericAlias, Protocol, runtime_checkable,
    ClassVar, Final, Literal, TypedDict, NamedTuple, Generator
)

from ..core.sca.utils import examples

try:
    import ast
    AST_AVAILABLE = True
except ImportError:
    AST_AVAILABLE = False

try:
    from markdown import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

try:
    import docutils.core
    DOCUTILS_AVAILABLE = True
except ImportError:
    DOCUTILS_AVAILABLE = False


# -----------------------------------------------------------------------------
# Module Configuration and Constants
# -----------------------------------------------------------------------------

# Default configuration values used when user overrides are not provided
DEFAULT_MAX_EXAMPLE_LENGTH: int = 500
DEFAULT_MAX_DOCSTRING_LENGTH: int = 2000
DEFAULT_MAX_INHERITANCE_DEPTH: int = 5
DEFAULT_CACHE_SIZE: int = 200
DEFAULT_CACHE_TTL: int = 3600  # 1 hour in seconds

# Set of all supported output formats for validation purposes
SUPPORTED_FORMATS = {'rst', 'markdown', 'html', 'plain', 'json'}

# Mapping of Python types to human-readable string representations
TYPE_NAME_MAP: Dict[type, str] = {
    str: 'str',
    int: 'int',
    float: 'float',
    bool: 'bool',
    list: 'list',
    dict: 'dict',
    set: 'set',
    tuple: 'tuple',
    type(None): 'None',
    Any: 'Any',
    Callable: 'Callable',
    Optional: 'Optional',
    Union: 'Union',
    List: 'List',
    Dict: 'Dict',
    Set: 'Set',
    Tuple: 'Tuple',
    Iterator: 'Iterator',
    Generator: 'Generator',
}

# Comprehensive mapping of special/magic methods to their functional categories
# Used for grouping related dunder methods in documentation output
SPECIAL_METHOD_CATEGORIES: Dict[str, str] = {
    # Object lifecycle and customization
    '__new__': 'Construction',
    '__init__': 'Construction',
    '__del__': 'Destruction',
    '__repr__': 'Representation',
    '__str__': 'Representation',
    '__format__': 'Representation',
    '__bytes__': 'Representation',
    
    # Rich comparison operators
    '__lt__': 'Comparison',
    '__le__': 'Comparison',
    '__eq__': 'Comparison',
    '__ne__': 'Comparison',
    '__gt__': 'Comparison',
    '__ge__': 'Comparison',
    '__hash__': 'Comparison',
    
    # Attribute access and dynamic attribute handling
    '__getattr__': 'Attribute Access',
    '__getattribute__': 'Attribute Access',
    '__setattr__': 'Attribute Access',
    '__delattr__': 'Attribute Access',
    '__dir__': 'Attribute Access',
    
    # Descriptor protocol implementation
    '__get__': 'Descriptor',
    '__set__': 'Descriptor',
    '__delete__': 'Descriptor',
    '__set_name__': 'Descriptor',
    
    # Container and sequence emulation
    '__len__': 'Container',
    '__length_hint__': 'Container',
    '__getitem__': 'Container',
    '__setitem__': 'Container',
    '__delitem__': 'Container',
    '__missing__': 'Container',
    '__iter__': 'Container',
    '__reversed__': 'Container',
    '__contains__': 'Container',
    
    # Numeric operator overloading
    '__add__': 'Numeric',
    '__sub__': 'Numeric',
    '__mul__': 'Numeric',
    '__matmul__': 'Numeric',
    '__truediv__': 'Numeric',
    '__floordiv__': 'Numeric',
    '__mod__': 'Numeric',
    '__divmod__': 'Numeric',
    '__pow__': 'Numeric',
    '__lshift__': 'Numeric',
    '__rshift__': 'Numeric',
    '__and__': 'Numeric',
    '__xor__': 'Numeric',
    '__or__': 'Numeric',
    
    # Callable object emulation
    '__call__': 'Callable',
    
    # Context manager protocol
    '__enter__': 'Context Manager',
    '__exit__': 'Context Manager',
    
    # Asynchronous programming support
    '__await__': 'Asynchronous',
    '__aiter__': 'Asynchronous',
    '__anext__': 'Asynchronous',
    '__aenter__': 'Asynchronous',
    '__aexit__': 'Asynchronous',
}

# Configure module-level logger with appropriate defaults
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


# -----------------------------------------------------------------------------
# Platform and Path Utilities
# -----------------------------------------------------------------------------

class PlatformInfo:
    """
    Thread-safe singleton providing cross-platform information and path utilities.
    
    This class centralizes platform detection and path normalization operations,
    ensuring consistent behavior across Windows, Linux, and macOS environments.
    It implements the singleton pattern with double-checked locking to ensure
    only one instance exists per process while maintaining thread safety.
    
    Attributes
    ----------
    system : str
        Operating system name as returned by platform.system().
    is_windows : bool
        True if running on Windows operating system.
    is_linux : bool
        True if running on Linux operating system.
    is_macos : bool
        True if running on macOS (Darwin) operating system.
    path_sep : str
        Platform-specific path separator character.
    line_sep : str
        Platform-specific line separator string.
    """
    
    _instance: Optional['PlatformInfo'] = None
    _lock = threading.RLock()
    
    def __new__(cls) -> 'PlatformInfo':
        """
        Create or return the singleton instance with thread-safe double-checked locking.
        
        Returns
        -------
        PlatformInfo
            The singleton instance of PlatformInfo.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        """
        Initialize platform information by detecting the current operating system.
        
        This method is idempotent - it only sets attributes once during the
        first instantiation of the singleton.
        """
        if not hasattr(self, '_initialized'):
            self.system = platform.system()
            self.is_windows = self.system == 'Windows'
            self.is_linux = self.system == 'Linux'
            self.is_macos = self.system == 'Darwin'
            self.path_sep = os.path.sep
            self.line_sep = os.linesep
            self._initialized = True
    
    def normalize_path(self, path: Union[str, Path]) -> str:
        """
        Normalize a filesystem path for the current platform.
        
        This method resolves relative paths to absolute paths, normalizes
        separators according to platform conventions, and handles both string
        and Path input types.
        
        Parameters
        ----------
        path : Union[str, Path]
            Input path as string or pathlib.Path object.
        
        Returns
        -------
        str
            Fully resolved, normalized absolute path as string.
            
        Examples
        --------
        >>> info = PlatformInfo()
        >>> info.normalize_path("~/documents/../file.txt")
        '/home/user/file.txt'  # On Linux
        'C:\\Users\\user\\file.txt'  # On Windows
        """
        p = Path(path) if isinstance(path, str) else path
        return str(p.resolve())

# Global singleton instance for platform utilities
_platform = PlatformInfo()


# -----------------------------------------------------------------------------
# Configuration Classes
# -----------------------------------------------------------------------------

@dataclass
class DocumentationConfig:
    """
    Comprehensive configuration dataclass for documentation generation.
    
    This class encapsulates all configurable parameters that control the behavior
    of the documentation generation process. It includes validation logic and
    sensible defaults for all options. The configuration can be serialized to
    JSON for caching purposes and supports incremental updates.
    
    Attributes
    ----------
    format : str
        Output format specification. Must be one of: 'rst', 'markdown', 'html',
        'plain', or 'json'. Defaults to 'rst'.
    include_private : bool
        When True, includes private members (names starting with '_') in output.
        Defaults to False.
    include_examples : bool
        When True, attempts to generate and include usage examples for documented
        objects. Defaults to True.
    include_inherited : bool
        When True, includes inherited members when documenting classes. Defaults
        to True.
    include_magic_methods : bool
        When True, includes special/magic methods (__*__) in documentation.
        Defaults to False.
    include_source_links : bool
        When True and source_url_template is provided, adds links to source code.
        Defaults to False.
    include_type_hints : bool
        When True, includes type hints in function/class signatures. Defaults to True.
    include_toc : bool
        When True, generates and includes a table of contents. Defaults to False.
    group_private : bool
        When True and include_private is True, groups private members in separate
        sections rather than mixing with public members. Defaults to False.
    group_by_category : bool
        When True, groups special methods by their functional categories. Defaults
        to True.
    show_annotations : bool
        When True, displays function annotations in signatures. Defaults to True.
    show_bases : bool
        When True, displays base/parent classes in class documentation. Defaults
        to True.
    show_mro : bool
        When True, displays the full method resolution order for classes. Defaults
        to False.
    show_module_metadata : bool
        When True, displays module-level metadata (file, version, author). Defaults
        to True.
    max_example_length : int
        Maximum character length for auto-generated examples. Longer examples are
        truncated. Defaults to 500.
    max_docstring_length : int
        Maximum character length for docstrings. Longer docstrings are truncated.
        Defaults to 2000.
    max_inheritance_depth : int
        Maximum depth when traversing inheritance hierarchies. Defaults to 5.
    title_level : int
        Starting heading level (1-6). Used as base for hierarchical headings.
        Defaults to 1.
    filter_by : Optional[str]
        Optional filter restricting output to specific types: 'classes', 'functions',
        'variables', or None for all. Defaults to None.
    section_order : List[str]
        Order in which documentation sections appear. Defaults to ["Classes",
        "Functions", "Variables"].
    source_url_template : Optional[str]
        Template string for generating source code links. Should contain {path}
        and {line} placeholders. Example: 'https://github.com/user/repo/blob/main/{path}#L{line}'.
        Defaults to None.
    encoding : str
        Character encoding for output files. Defaults to 'utf-8'.
    indent_size : int
        Number of spaces per indentation level. Defaults to 4.
    line_width : int
        Maximum line width for text wrapping operations. Defaults to 80.
    enable_caching : bool
        When True, enables the documentation cache for improved performance.
        Defaults to True.
    cache_size : int
        Maximum number of items to store in the LRU cache. Defaults to 200.
    cache_ttl : int
        Time-to-live for cache entries in seconds. Defaults to 3600 (1 hour).
    verbose : bool
        When True, enables verbose logging output. Defaults to False.
        
    Raises
    ------
    ValueError
        If format is not in SUPPORTED_FORMATS.
    ValueError
        If filter_by is not one of None, 'classes', 'functions', or 'variables'.
    ValueError
        If title_level is less than 1.
    """
    
    format: str = "rst"
    include_private: bool = False
    include_examples: bool = True
    include_inherited: bool = True
    include_magic_methods: bool = False
    include_source_links: bool = False
    include_type_hints: bool = True
    include_toc: bool = False
    group_private: bool = False
    group_by_category: bool = True
    show_annotations: bool = True
    show_bases: bool = True
    show_mro: bool = False
    show_module_metadata: bool = True
    max_example_length: int = DEFAULT_MAX_EXAMPLE_LENGTH
    max_docstring_length: int = DEFAULT_MAX_DOCSTRING_LENGTH
    max_inheritance_depth: int = DEFAULT_MAX_INHERITANCE_DEPTH
    title_level: int = 1
    filter_by: Optional[str] = None
    section_order: List[str] = field(default_factory=lambda: ["Classes", "Functions", "Variables"])
    source_url_template: Optional[str] = None
    encoding: str = "utf-8"
    indent_size: int = 4
    line_width: int = 80
    enable_caching: bool = True
    cache_size: int = DEFAULT_CACHE_SIZE
    cache_ttl: int = DEFAULT_CACHE_TTL
    verbose: bool = False
    
    def __post_init__(self) -> None:
        """
        Validate configuration after initialization.
        
        Performs validation of interdependent fields and ensures all values
        are within acceptable ranges.
        
        Raises
        ------
        ValueError
            If any configuration value is invalid according to the rules
            specified in the class docstring.
        """
        if self.format not in SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format: {self.format}. Use {SUPPORTED_FORMATS}")
        
        if self.filter_by and self.filter_by not in ("classes", "functions", "variables"):
            raise ValueError(f"Invalid filter_by: {self.filter_by}")
        
        if self.title_level < 1:
            raise ValueError(f"title_level must be >= 1, got {self.title_level}")


class DocumentationContext:
    """
    Context object tracking documentation generation state.
    
    This class maintains all state information during a single documentation
    generation session. It handles anchor ID generation with uniqueness guarantees,
    cross-reference management, table of contents accumulation, and error/warning
    collection. The context is passed between handlers to maintain consistency
    across the entire generation process.
    
    Attributes
    ----------
    config : DocumentationConfig
        The configuration used for this documentation generation session.
    module : ModuleType
        Reference to the module being documented.
    heading_levels : Dict[str, int]
        Current heading levels indexed by section name.
    generated_ids : Set[str]
        Set of all generated anchor IDs for uniqueness verification.
    cross_references : Dict[str, str]
        Mapping of documented object names to their anchor IDs.
    toc_entries : List[Tuple[int, str, str]]
        Table of contents entries stored as (level, title, anchor) tuples.
    warnings : List[str]
        Non-critical warnings collected during documentation generation.
    errors : List[str]
        Critical errors encountered during documentation generation.
    start_time : datetime
        UTC timestamp when documentation generation began.
    """
    
    def __init__(self, config: DocumentationConfig, module: ModuleType) -> None:
        """
        Initialize a new documentation context for a generation session.
        
        Parameters
        ----------
        config : DocumentationConfig
            Configuration controlling this documentation generation.
        module : ModuleType
            The module being documented in this session.
        """
        self.config = config
        self.module = module
        self.heading_levels: Dict[str, int] = {}
        self.generated_ids: Set[str] = set()
        self.cross_references: Dict[str, str] = {}
        self.toc_entries: List[Tuple[int, str, str]] = []
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.start_time = datetime.utcnow()
        self._anchor_counter: Dict[str, int] = defaultdict(int)
    
    def generate_anchor(self, text: str) -> str:
        """
        Generate a guaranteed-unique anchor ID from arbitrary text.
        
        This method converts text to lowercase, replaces non-alphanumeric
        characters with dashes, and ensures uniqueness by appending a counter
        when collisions would occur.
        
        Parameters
        ----------
        text : str
            The text to convert into an anchor identifier.
        
        Returns
        -------
        str
            A unique anchor ID suitable for HTML/Markdown linking.
            
        Examples
        --------
        >>> ctx = DocumentationContext(config, module)
        >>> ctx.generate_anchor("My Class")
        'my-class'
        >>> ctx.generate_anchor("My Class")
        'my-class-1'
        """
        # Convert to lowercase and replace non-alphanumeric with dashes
        anchor = re.sub(r'[^\w\s-]', '', text.lower())
        anchor = re.sub(r'[-\s]+', '-', anchor).strip('-')
        
        # Ensure uniqueness with incremental counters on collisions
        if anchor in self.generated_ids:
            self._anchor_counter[anchor] += 1
            anchor = f"{anchor}-{self._anchor_counter[anchor]}"
        
        self.generated_ids.add(anchor)
        return anchor
    
    def add_toc_entry(self, level: int, title: str, anchor: Optional[str] = None) -> None:
        """
        Add an entry to the table of contents for later rendering.
        
        Parameters
        ----------
        level : int
            Nesting level of this TOC entry (1 for top-level, 2 for sub-sections).
        title : str
            Display title for this TOC entry.
        anchor : Optional[str]
            Optional anchor ID to link to. If None, generates one from the title.
        """
        if anchor is None:
            anchor = self.generate_anchor(title)
        self.toc_entries.append((level, title, anchor))
    
    def add_cross_reference(self, name: str, anchor: str) -> None:
        """
        Store a cross-reference mapping between an object name and its anchor.
        
        Parameters
        ----------
        name : str
            Name of the documented object.
        anchor : str
            Anchor ID where this object's documentation appears.
        """
        self.cross_references[name] = anchor
    
    def get_heading_level(self, section: str) -> int:
        """
        Retrieve the heading level for a given documentation section.
        
        If no level has been explicitly set for the section, returns the
        configured base title_level.
        
        Parameters
        ----------
        section : str
            Name of the documentation section.
            
        Returns
        -------
        int
            The heading level to use for this section.
        """
        return self.heading_levels.get(section, self.config.title_level)
    
    def set_heading_level(self, section: str, level: int) -> None:
        """
        Set the heading level for a specific documentation section.
        
        Parameters
        ----------
        section : str
            Name of the documentation section.
        level : int
            Heading level to assign to this section.
        """
        self.heading_levels[section] = level


# -----------------------------------------------------------------------------
# Documentation Cache
# -----------------------------------------------------------------------------

class DocumentationCache:
    """
    Thread-safe, TTL-based LRU cache for generated documentation.
    
    This cache dramatically improves performance for repeated documentation
    generation requests with identical configuration. It implements a
    time-to-live (TTL) expiration policy combined with LRU eviction when
    the cache reaches capacity limitations. All operations are protected
    by a reentrant lock for thread safety.
    
    Attributes
    ----------
    max_size : int
        Maximum number of entries the cache can hold before eviction.
    ttl : int
        Time-to-live in seconds for cache entries.
    stats : Dict[str, Any]
        Read-only property returning cache performance statistics.
    """
    
    def __init__(self, max_size: int = DEFAULT_CACHE_SIZE, ttl: int = DEFAULT_CACHE_TTL) -> None:
        """
        Initialize a new documentation cache instance.
        
        Parameters
        ----------
        max_size : int, optional
            Maximum cache capacity in number of entries (default: DEFAULT_CACHE_SIZE).
        ttl : int, optional
            Time-to-live for entries in seconds (default: DEFAULT_CACHE_TTL).
        """
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def _make_key(self, module_name: str, config_hash: str) -> str:
        """
        Create a unique cache key from module name and configuration hash.
        
        This internal method combines the module identifier with a hash of
        the configuration to create a stable cache lookup key.
        
        Parameters
        ----------
        module_name : str
            Fully qualified name of the module.
        config_hash : str
            MD5 hash of the serialized configuration.
            
        Returns
        -------
        str
            Combined cache key string in format "module_name:config_hash".
        """
        return f"{module_name}:{config_hash}"
    
    def get(self, module_name: str, config_hash: str) -> Optional[str]:
        """
        Retrieve cached documentation if available and not expired.
        
        This method checks for a valid cache entry, updates the LRU order
        on hit, and handles TTL expiration by removing stale entries.
        
        Parameters
        ----------
        module_name : str
            Fully qualified name of the documented module.
        config_hash : str
            MD5 hash of the documentation configuration.
            
        Returns
        -------
        Optional[str]
            The cached documentation string if available and valid,
            otherwise None.
            
        Notes
        -----
        This method updates the internal hit/miss counters used for statistics.
        """
        with self._lock:
            key = self._make_key(module_name, config_hash)
            if key not in self._cache:
                self._misses += 1
                return None
            
            doc, timestamp = self._cache[key]
            
            # Check for TTL expiration
            if (datetime.utcnow() - timestamp).total_seconds() > self.ttl:
                del self._cache[key]
                self._misses += 1
                return None
            
            # Update LRU position and count hit
            self._cache.move_to_end(key)
            self._hits += 1
            return doc
    
    def put(self, module_name: str, config_hash: str, documentation: str) -> None:
        """
        Store generated documentation in the cache.
        
        This method implements an LRU eviction policy when the cache is at
        capacity by removing the least recently used entry before insertion.
        
        Parameters
        ----------
        module_name : str
            Fully qualified name of the documented module.
        config_hash : str
            MD5 hash of the documentation configuration.
        documentation : str
            Generated documentation string to cache.
            
        Notes
        -----
        Cache entries are stored with the current UTC timestamp for TTL checks.
        """
        with self._lock:
            key = self._make_key(module_name, config_hash)
            
            # LRU eviction when at capacity
            if len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
            
            self._cache[key] = (documentation, datetime.utcnow())
    
    def clear(self) -> None:
        """
        Clear all cached entries and reset statistics.
        
        This method completely empties the cache and resets hit/miss counters
        to zero. It is useful for testing scenarios or when modules have been
        modified and cached documentation is stale.
        """
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    @property
    def stats(self) -> Dict[str, Any]:
        """
        Retrieve current cache performance statistics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing cache statistics:
            - size: Current number of cached entries
            - max_size: Maximum cache capacity
            - hits: Number of successful cache retrievals
            - misses: Number of cache lookup failures
            - hit_rate: Percentage of lookups resulting in hits (as string)
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': f"{hit_rate:.1f}%",
            }


# Global singleton cache instance shared across all documenter instances
_global_cache = DocumentationCache()


# -----------------------------------------------------------------------------
# Formatting Utilities
# -----------------------------------------------------------------------------

def _format_heading(text: str, level: int, format: str, anchor: Optional[str] = None) -> str:
    """
    Format a heading according to the specified output format.
    
    This utility function provides consistent heading formatting across all
    output formats with appropriate syntax for reStructuredText, Markdown,
    HTML, and plain text.
    
    Parameters
    ----------
    text : str
        The heading text to format.
    level : int
        Heading level where 1 is the highest/top-level heading.
    format : str
        Target output format: 'rst', 'markdown', 'html', or 'plain'.
    anchor : Optional[str]
        Optional anchor ID for creating cross-reference targets.
    
    Returns
    -------
    str
        Properly formatted heading string for the target format.
        
    Examples
    --------
    >>> _format_heading("Introduction", 1, "markdown", "intro")
    '# Introduction {#intro}'
    
    >>> _format_heading("Methods", 2, "rst")
    'Methods\\n-------'
    
    >>> _format_heading("Constants", 1, "html", "constants")
    '<h1 id="constants">Constants</h1>'
    """
    if format == "rst":
        # reStructuredText uses underline characters based on level
        if level == 1:
            underline = "="
        elif level == 2:
            underline = "-"
        elif level == 3:
            underline = "~"
        elif level == 4:
            underline = "^"
        else:
            underline = '"'
        return f"{text}\n{underline * len(text)}"
    
    elif format == "markdown":
        # Markdown uses # prefixes up to 6 levels, anchors as {#id} attributes
        anchor_attr = f" {{#{anchor}}}" if anchor else ""
        return f"{'#' * min(level, 6)} {text}{anchor_attr}"
    
    elif format == "html":
        # HTML heading tags with optional id attributes
        tag = f"h{min(level, 6)}"
        anchor_attr = f' id="{anchor}"' if anchor else ""
        return f"<{tag}{anchor_attr}>{text}</{tag}>"
    
    else:  # plain text format
        return f"\n{text.upper()}\n{'-' * len(text)}"


def _format_code_block(content: str, language: str, format: str) -> str:
    """
    Format a block of source code according to the output format.
    
    Creates syntax-highlighted code blocks with language specification where
    supported by the target format.
    
    Parameters
    ----------
    content : str
        The code content to format as a block.
    language : str
        Programming language identifier for syntax highlighting.
    format : str
        Target output format specification.
    
    Returns
    -------
    str
        Formatted code block with appropriate delimiters.
    """
    if format == "rst":
        return f".. code-block:: {language}\n\n{textwrap.indent(content.rstrip(), '   ')}\n"
    
    elif format == "markdown":
        return f"```{language}\n{content.rstrip()}\n```"
    
    elif format == "html":
        # HTML requires escaping of angle brackets and ampersands
        escaped = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<pre><code class="language-{language}">{escaped}</code></pre>'
    
    else:  # plain text
        return textwrap.indent(content.rstrip(), '  ')


def _format_inline_code(text: str, format: str) -> str:
    """
    Format inline code snippets according to the output format.
    
    Parameters
    ----------
    text : str
        The code text to format as inline code.
    format : str
        Target output format specification.
    
    Returns
    -------
    str
        Formatted inline code with appropriate delimiters.
    """
    if format == "rst":
        return f"``{text}``"
    
    elif format == "markdown":
        return f"`{text}`"
    
    elif format == "html":
        return f"<code>{text}</code>"
    
    else:  # plain
        return f"'{text}'"


def _format_link(text: str, url: str, format: str) -> str:
    """
    Format a hyperlink according to the output format.
    
    Parameters
    ----------
    text : str
        Display text for the hyperlink.
    url : str
        Target URL for the hyperlink.
    format : str
        Target output format specification.
    
    Returns
    -------
    str
        Formatted hyperlink with the correct syntax for the format.
    """
    if format == "rst":
        return f"`{text} <{url}>`_"
    
    elif format == "markdown":
        return f"[{text}]({url})"
    
    elif format == "html":
        return f'<a href="{url}">{text}</a>'
    
    else:  # plain
        return f"{text} ({url})"


def _format_list(items: List[str], format: str, ordered: bool = False) -> str:
    """
    Format a list of items according to the output format.
    
    Parameters
    ----------
    items : List[str]
        List of strings representing individual list items.
    format : str
        Target output format specification.
    ordered : bool, optional
        If True, creates a numbered list; otherwise creates a bulleted list.
        Defaults to False.
    
    Returns
    -------
    str
        Formatted list with appropriate markers for the target format.
    """
    if format == "rst":
        prefix = "#." if ordered else "*"
        return "\n".join(f"{prefix} {item}" for item in items)
    
    elif format == "markdown":
        lines = []
        for i, item in enumerate(items, 1):
            prefix = f"{i}." if ordered else "-"
            lines.append(f"{prefix} {item}")
        return "\n".join(lines)
    
    elif format == "html":
        tag = "ol" if ordered else "ul"
        items_html = "\n".join(f"<li>{item}</li>" for item in items)
        return f"<{tag}>\n{items_html}\n</{tag}>"
    
    else:  # plain
        lines = []
        for i, item in enumerate(items, 1):
            prefix = f"{i}." if ordered else "•"
            lines.append(f"{prefix} {item}")
        return "\n".join(lines)


def _format_type_hint(hint: Any, format: str) -> str:
    """
    Format a type hint into a human-readable string representation.
    
    This function recursively resolves generic types, Union types (including
    Optional shorthand), and complex type annotations into readable formats
    suitable for documentation.
    
    Parameters
    ----------
    hint : Any
        The type hint to format. Can be a class, generic type, or string.
    format : str        Output format (unused but kept for API consistency).
    
    Returns
    -------
    str
        Human-readable string representation of the type hint.
        
    Examples
    --------
    >>> _format_type_hint(Optional[List[str]], "rst")
    'Optional[List[str]]'
    >>> _format_type_hint(Union[int, float, None], "markdown")
    'Optional[Union[int, float]]'
    """
    if hint is None:
        return ""
    
    # Handle string annotations directly
    if isinstance(hint, str):
        return hint
    
    # Handle basic types with predefined mappings
    if hint in TYPE_NAME_MAP:
        return TYPE_NAME_MAP[hint]
    
    # Handle Optional[T] which is syntactic sugar for Union[T, None]
    origin = get_origin(hint)
    if origin is Union:
        args = get_args(hint)
        if type(None) in args:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                return f"Optional[{_format_type_hint(non_none[0], format)}]"
    
    # Handle generic types (List[T], Dict[K,V], etc.)
    if origin is not None:
        args = get_args(hint)
        if args:
            args_str = ", ".join(_format_type_hint(a, format) for a in args)
            origin_name = getattr(origin, '__name__', str(origin))
            return f"{origin_name}[{args_str}]"
    
    # Handle regular classes
    if inspect.isclass(hint):
        return hint.__name__
    
    # Handle Callable special case
    if hint is Callable:
        return "Callable"
    
    # Fallback to string conversion
    return str(hint)


def _format_signature(
    name: str,
    obj: Any,
    format: str,
    include_type_hints: bool = True,
    show_annotations: bool = True,
) -> str:
    """
    Format an object's signature for documentation display.
    
    This function intelligently extracts and formats the call signature of
    classes (via __init__), functions, and methods, including parameter types,
    default values, and return type annotations when configured.
    
    Parameters
    ----------
    name : str
        Name of the object being documented.
    obj : Any
        Object whose signature should be formatted.
    format : str
        Output format for any formatting that depends on the target.
    include_type_hints : bool, optional
        Whether to include type hints in the signature. Defaults to True.
    show_annotations : bool, optional
        Whether to show function annotations. Defaults to True.
    
    Returns
    -------
    str
        Formatted signature string or value representation for non-callables.
        
    Notes
    -----
    For non-callable objects, returns a truncated repr() representation
    limited to 100 characters.
    """
    if inspect.isclass(obj):
        # Extract class constructor signature, skipping 'self' parameter
        try:
            sig = inspect.signature(obj.__init__)
            params = list(sig.parameters.values())[1:]  # Skip self
            param_strs = []
            
            for param in params:
                param_str = param.name
                if include_type_hints and param.annotation != inspect.Parameter.empty:
                    type_hint = _format_type_hint(param.annotation, format)
                    param_str += f": {type_hint}"
                if param.default != inspect.Parameter.empty:
                    default = repr(param.default)
                    if len(default) > 50:
                        default = default[:47] + "..."
                    param_str += f" = {default}"
                param_strs.append(param_str)
            
            signature = f"{name}({', '.join(param_strs)})"
            
            if include_type_hints and sig.return_annotation != inspect.Parameter.empty:
                return_type = _format_type_hint(sig.return_annotation, format)
                signature += f" -> {return_type}"
            
            return signature
        except (ValueError, TypeError):
            # Fallback for classes without inspectable signatures
            return f"{name}(...)"
    
    elif inspect.isfunction(obj) or inspect.ismethod(obj):
        # Extract function/method signature, skipping self/cls parameters
        try:
            sig = inspect.signature(obj)
            param_strs = []
            
            for param_name, param in sig.parameters.items():
                if param_name == 'self' or param_name == 'cls':
                    continue
                
                param_str = param.name
                if include_type_hints and param.annotation != inspect.Parameter.empty:
                    type_hint = _format_type_hint(param.annotation, format)
                    param_str += f": {type_hint}"
                if param.default != inspect.Parameter.empty:
                    default = repr(param.default)
                    if len(default) > 50:
                        default = default[:47] + "..."
                    param_str += f" = {default}"
                param_strs.append(param_str)
            
            signature = f"{name}({', '.join(param_strs)})"
            
            if include_type_hints and sig.return_annotation != inspect.Parameter.empty:
                return_type = _format_type_hint(sig.return_annotation, format)
                signature += f" -> {return_type}"
            
            return signature
        except (ValueError, TypeError):
            return f"{name}(...)"
    
    else:
        # For non-callable objects, return truncated representation
        try:
            value_repr = repr(obj)
            if len(value_repr) > 100:
                value_repr = value_repr[:97] + "..."
            return value_repr
        except:
            return "<unable to represent>"


def _get_object_type_info(obj: Any) -> Dict[str, Any]:
    """
    Analyze an object and collect detailed type information.
    
    This function performs comprehensive type analysis on arbitrary Python
    objects, identifying whether they are classes, functions, async functions,
    generators, dataclasses, enums, abstract classes, and more.
    
    Parameters
    ----------
    obj : Any
        The object to analyze for type information.
    
    Returns
    -------
    Dict[str, Any]
        Dictionary containing comprehensive type analysis with the following
        potential keys:
        - type: Name of the object's type
        - is_class: Boolean indicating if object is a class
        - is_function: Boolean indicating if object is a function
        - is_method: Boolean indicating if object is a method
        - is_builtin: Boolean indicating if object is built-in
        - is_routine: Boolean indicating if object is a routine
        - is_abstract: Boolean indicating if class is abstract
        - is_async: Boolean indicating if function is async
        - is_generator: Boolean indicating if function is generator
        - is_dataclass: Boolean indicating if class is a dataclass
        - is_enum: Boolean indicating if class is an enum
        - module: Module name where object is defined (classes only)
        - bases: List of base class names (classes only)
        - dataclass_fields: List of dataclass field names (dataclasses only)
        - enum_members: List of enum member names (enums only)
        - abstract_methods: List of abstract method names (abstract classes only)
    """
    info: Dict[str, Any] = {
        'type': type(obj).__name__,
        'is_class': inspect.isclass(obj),
        'is_function': inspect.isfunction(obj),
        'is_method': inspect.ismethod(obj),
        'is_builtin': inspect.isbuiltin(obj),
        'is_routine': inspect.isroutine(obj),
        'is_abstract': inspect.isabstract(obj),
        'is_async': inspect.iscoroutinefunction(obj) or inspect.isasyncgenfunction(obj),
        'is_generator': inspect.isgeneratorfunction(obj),
        'is_dataclass': is_dataclass(obj) if inspect.isclass(obj) else False,
        'is_enum': isinstance(obj, EnumMeta) if inspect.isclass(obj) else False,
    }
    
    if inspect.isclass(obj):
        info['module'] = obj.__module__
        info['bases'] = [base.__name__ for base in obj.__bases__]
        
        # Additional analysis for dataclasses
        if hasattr(obj, '__dataclass_fields__'):
            info['is_dataclass'] = True
            info['dataclass_fields'] = list(obj.__dataclass_fields__.keys())
        
        # Enum analysis
        if issubclass(obj, Enum) and obj is not Enum:
            info['is_enum'] = True
            info['enum_members'] = [e.name for e in obj]
        
        # Abstract method detection
        if inspect.isabstract(obj):
            info['abstract_methods'] = list(obj.__abstractmethods__) if hasattr(obj, '__abstractmethods__') else []
    
    return info


def _categorize_object(obj: Any, name: str, config: DocumentationConfig) -> Optional[str]:
    """
    Determine the documentation category for a module member.
    
    This function categorizes module members as belonging to "Classes",
    "Functions", or "Variables" sections, with consideration for configuration
    settings that may exclude certain objects from documentation.
    
    Parameters
    ----------
    obj : Any
        The object to categorize.
    name : str
        Name of the object (used for magic method detection).
    config : DocumentationConfig
        Configuration controlling inclusion criteria.
    
    Returns
    -------
    Optional[str]
        Category name ("Classes", "Functions", "Variables") or None if the
        object should be excluded from documentation.
        
    Notes
    -----
    Returns None (excluded) when:
    - Object is a magic method and include_magic_methods is False
    - Object is a private member and include_private is False (handled earlier)
    """
    # Check magic method exclusion
    if not config.include_magic_methods and name.startswith('__') and name.endswith('__'):
        return None
    
    if inspect.isclass(obj):
        return "Classes"
    
    elif inspect.isfunction(obj) or inspect.ismethod(obj) or inspect.isroutine(obj):
        return "Functions"
    
    elif not callable(obj) and not inspect.ismodule(obj):
        return "Variables"
    
    return None


def _get_special_method_category(name: str) -> Optional[str]:
    """
    Retrieve the functional category for a special/magic method.
    
    This function maps dunder method names to human-readable categories
    using the comprehensive SPECIAL_METHOD_CATEGORIES mapping.
    
    Parameters
    ----------
    name : str
        Name of the special method (e.g., '__init__', '__add__').
    
    Returns
    -------
    Optional[str]
        The category name if the method is known, or None if not.
        
    Examples
    --------
    >>> _get_special_method_category("__init__")
    'Construction'
    >>> _get_special_method_category("__add__")
    'Numeric'
    >>> _get_special_method_category("__unknown__")
    None
    """
    return SPECIAL_METHOD_CATEGORIES.get(name)


# -----------------------------------------------------------------------------
# Object Handlers
# -----------------------------------------------------------------------------

class ObjectHandler(ABC):
    """
    Abstract base class defining the interface for custom object handlers.
    
    This class establishes the plugin architecture that allows extension of
    the documentation system with custom handling logic for specific object
    types. Implementers must override both can_handle() and generate_documentation().
    
    Examples
    --------
    >>> class CustomHandler(ObjectHandler):
    ...     def can_handle(self, obj: Any) -> bool:
    ...         return hasattr(obj, 'my_custom_attribute')
    ...     
    ...     def generate_documentation(self, name: str, obj: Any, context: DocumentationContext) -> List[str]:
    ...         return [f"Custom documentation for {name}"]
    """
    
    @abstractmethod
    def can_handle(self, obj: Any) -> bool:
        """
        Determine whether this handler can document the given object.
        
        Parameters
        ----------
        obj : Any
            The object to check for compatibility with this handler.
        
        Returns
        -------
        bool
            True if this handler should be used for the object, False otherwise.
        """
        pass
    
    @abstractmethod
    def generate_documentation(
        self,
        name: str,
        obj: Any,
        context: DocumentationContext,
    ) -> List[str]:
        """
        Generate documentation lines for an object this handler supports.
        
        Parameters
        ----------
        name : str
            Name of the object being documented.
        obj : Any
            The object instance to document.
        context : DocumentationContext
            Current documentation generation context for state management.
        
        Returns
        -------
        List[str]
            List of strings representing the generated documentation lines.
        """
        pass


class ClassHandler(ObjectHandler):
    """
    Specialized handler for generating comprehensive class documentation.
    
    This handler produces detailed documentation for classes including:
    - Type information and multiple inheritance details
    - Method Resolution Order (MRO) visualization
    - Dataclass field specifications with types
    - Enum member enumeration with values
    - Abstract method listings
    - Summarized class member listings (methods, properties, class/static methods)
    - Source code linking when configured
    
    The handler follows the configuration settings from the context to
    tailor output appropriately.
    """
    
    def can_handle(self, obj: Any) -> bool:
        """
        Check if the object is a class (using inspect.isclass).
        
        Parameters
        ----------
        obj : Any
            Object to test for class type.
            
        Returns
        -------
        bool
            True if obj is a class, False otherwise.
        """
        return inspect.isclass(obj)
    
    def generate_documentation(
        self,
        name: str,
        obj: Type[Any],
        context: DocumentationContext,
    ) -> List[str]:
        """
        Generate comprehensive class documentation.
        
        Parameters
        ----------
        name : str
            Name of the class being documented.
        obj : Type[Any]
            Class object to document.
        context : DocumentationContext
            Current documentation generation context.
        
        Returns
        -------
        List[str]
            List of strings containing the generated documentation.
            
        Notes
        -----
        This method gracefully handles errors during documentation generation,
        adding them to the context's error collection rather than failing.
        """
        lines: List[str] = []
        config = context.config
        
        # Generate header with anchor for cross-referencing
        anchor = context.generate_anchor(f"class-{name}")
        context.add_cross_reference(name, anchor)
        
        heading_level = context.get_heading_level("Classes")
        lines.append(_format_heading(name, heading_level, config.format, anchor))
        lines.append("")
        
        # Basic type information header
        type_info = _get_object_type_info(obj)
        
        lines.append(f"*Type:* Class")
        
        # Base/parent class information when configured
        if config.show_bases and obj.__bases__:
            bases_str = ", ".join(base.__name__ for base in obj.__bases__ if base is not object)
            if bases_str:
                lines.append(f"*Inherits from:* {bases_str}")
        
        # Method Resolution Order for multiple inheritance scenarios
        if config.show_mro:
            mro = [c.__name__ for c in inspect.getmro(obj) if c is not object]
            if len(mro) > 1:
                lines.append(f"*MRO:* {' → '.join(mro)}")
        
        # Dataclass decoration indicator
        if type_info['is_dataclass']:
            lines.append("*Decorator:* @dataclass")
        
        # Abstract method listing for abstract base classes
        if type_info.get('abstract_methods'):
            methods_str = ", ".join(_format_inline_code(m, config.format) for m in type_info['abstract_methods'])
            lines.append(f"*Abstract Methods:* {methods_str}")
        
        lines.append("")
        
        # Class constructor signature
        sig = _format_signature(
            name, obj, config.format,
            include_type_hints=config.include_type_hints,
            show_annotations=config.show_annotations,
        )
        lines.append(f"*Signature:* {_format_inline_code(sig, config.format)}")
        lines.append("")
        
        # Class docstring extraction and formatting
        doc = inspect.getdoc(obj)
        if doc:
            paragraphs = doc.split("\n\n")
            summary = paragraphs[0].strip()
            lines.append(summary)
            lines.append("")
            
            if len(doc) < config.max_docstring_length and len(paragraphs) > 1:
                lines.append("**Details:**")
                lines.append("")
                for para in paragraphs[1:]:
                    lines.append(textwrap.fill(para.strip(), width=config.line_width))
                    lines.append("")
        
        # Dataclass field documentation
        if type_info['is_dataclass'] and type_info.get('dataclass_fields'):
            lines.append("**Dataclass Fields:**")
            lines.append("")
            field_lines = []
            for field_name in type_info['dataclass_fields']:
                field = obj.__dataclass_fields__[field_name]
                field_type = _format_type_hint(field.type, config.format)
                field_lines.append(f"- {field_name}: {field_type}")
            lines.extend(field_lines)
            lines.append("")
        
        # Enum member enumeration with values
        if type_info.get('is_enum') and type_info.get('enum_members'):
            lines.append("**Enum Members:**")
            lines.append("")
            member_lines = []
            for member_name in type_info['enum_members']:
                member = getattr(obj, member_name)
                member_lines.append(f"- {member_name} = {member.value}")
            lines.extend(member_lines)
            lines.append("")
        
        # Collect and categorize class members
        methods = []
        properties = []
        classmethods = []
        staticmethods = []
        
        for attr_name in dir(obj):
            if attr_name.startswith('_') and not config.include_private:
                continue
            
            attr = inspect.getattr_static(obj, attr_name, None)
            if attr is None:
                continue
            
            if isinstance(attr, property):
                properties.append(attr_name)
            elif isinstance(attr, classmethod):
                classmethods.append(attr_name)
            elif isinstance(attr, staticmethod):
                staticmethods.append(attr_name)
            elif inspect.isfunction(attr) or inspect.ismethod(attr):
                methods.append(attr_name)
        
        # Summarized class member listing
        if any([methods, properties, classmethods, staticmethods]):
            lines.append("**Class Members:**")
            lines.append("")
            
            if methods:
                methods_str = ", ".join(_format_inline_code(m, config.format) for m in methods[:10])
                if len(methods) > 10:
                    methods_str += f" and {len(methods) - 10} more"
                lines.append(f"- Methods: {methods_str}")
            
            if properties:
                props_str = ", ".join(_format_inline_code(p, config.format) for p in properties)
                lines.append(f"- Properties: {props_str}")
            
            if classmethods:
                cm_str = ", ".join(_format_inline_code(c, config.format) for c in classmethods)
                lines.append(f"- Class Methods: {cm_str}")
            
            if staticmethods:
                sm_str = ", ".join(_format_inline_code(s, config.format) for s in staticmethods)
                lines.append(f"- Static Methods: {sm_str}")
            
            lines.append("")
        
        # Source code link generation
        if config.include_source_links and config.source_url_template:
            try:
                file_path = inspect.getfile(obj)
                line_no = inspect.getsourcelines(obj)[1]
                url = config.source_url_template.format(
                    path=file_path,
                    line=line_no,
                )
                lines.append(_format_link("View source", url, config.format))
                lines.append("")
            except (TypeError, OSError):
                # Gracefully handle built-in or C extension classes
                pass
        
        # Usage examples generation
        if config.include_examples:
            try:
                ex = examples(obj, text=True)
                if ex:
                    if len(ex) > config.max_example_length:
                        ex = ex[:config.max_example_length] + "\n... (truncated)"
                    
                    lines.append("**Examples:**")
                    lines.append("")
                    lines.append(_format_code_block(ex.strip(), "python", config.format))
                    lines.append("")
            except Exception as e:
                if config.verbose:
                    lines.append(f"*Unable to generate examples: {e}*")
                    lines.append("")
        
        return lines


class FunctionHandler(ObjectHandler):
    """
    Specialized handler for generating comprehensive function/method documentation.
    
    This handler produces detailed documentation for functions and methods including:
    - Function type detection (async, generator, decorated)
    - Complete signature with type hints
    - Parameter, return value, and exception extraction from docstrings
    - Decorator stack unwrapping for accurate signature
    - Source code linking
    - Usage examples generation
    
    The handler recognizes Google-style, NumPy-style, and reStructuredText docstring
    sections for parameter, return, and exception extraction.
    """
    
    def can_handle(self, obj: Any) -> bool:
        """
        Check if the object is a function, method, or routine.
        
        Parameters
        ----------
        obj : Any
            Object to test for function/method/routine type.
            
        Returns
        -------
        bool
            True if obj is a function, method, or routine, False otherwise.
        """
        return inspect.isfunction(obj) or inspect.ismethod(obj) or inspect.isroutine(obj)
    
    def generate_documentation(
        self,
        name: str,
        obj: Callable[..., Any],
        context: DocumentationContext,
    ) -> List[str]:
        """
        Generate comprehensive function documentation.
        
        Parameters
        ----------
        name : str
            Name of the function being documented.
        obj : Callable[..., Any]
            Callable object to document.
        context : DocumentationContext
            Current documentation generation context.
        
        Returns
        -------
        List[str]
            List of strings containing the generated documentation.
        """
        lines: List[str] = []
        config = context.config
        
        # Generate header with anchor
        anchor = context.generate_anchor(f"func-{name}")
        context.add_cross_reference(name, anchor)
        
        heading_level = context.get_heading_level("Functions")
        lines.append(_format_heading(name, heading_level, config.format, anchor))
        lines.append("")
        
        # Detect and indicate special function types
        func_types = []
        if inspect.iscoroutinefunction(obj):
            func_types.append("Async")
        if inspect.isgeneratorfunction(obj):
            func_types.append("Generator")
        if hasattr(obj, '__wrapped__'):
            func_types.append("Decorated")
        
        type_str = f"Function ({', '.join(func_types)})" if func_types else "Function"
        lines.append(f"*Type:* {type_str}")
        
        # Decorator presence indicator
        if hasattr(obj, '__wrapped__'):
            lines.append("*Decorated:* Yes")
        
        lines.append("")
        
        # Function signature extraction and formatting
        sig = _format_signature(
            name, obj, config.format,
            include_type_hints=config.include_type_hints,
            show_annotations=config.show_annotations,
        )
        lines.append(f"*Signature:* {_format_inline_code(sig, config.format)}")
        lines.append("")
        
        # Docstring extraction with section parsing
        doc = inspect.getdoc(obj)
        if doc:
            paragraphs = doc.split("\n\n")
            summary = paragraphs[0].strip()
            lines.append(summary)
            lines.append("")
            
            if len(doc) < config.max_docstring_length and len(paragraphs) > 1:
                # Parse docstring sections (Google/NumPy/reST style)
                for para in paragraphs[1:]:
                    if para.strip().startswith(('Args:', 'Parameters:', 'Arguments:')):
                        lines.append("**Parameters:**")
                        lines.append("")
                        # Extract parameter descriptions from indented lines
                        param_lines = para.strip().split('\n')[1:]
                        for param_line in param_lines:
                            if ':' in param_line:
                                param_name, param_desc = param_line.split(':', 1)
                                lines.append(f"- {param_name.strip()}: {param_desc.strip()}")
                        lines.append("")
                    elif para.strip().startswith(('Returns:', 'Return:')):
                        lines.append("**Returns:**")
                        lines.append("")
                        return_text = para.strip().split('\n', 1)[0]
                        if ':' in return_text:
                            lines.append(return_text.split(':', 1)[1].strip())
                        lines.append("")
                    elif para.strip().startswith(('Raises:', 'Exceptions:')):
                        lines.append("**Raises:**")
                        lines.append("")
                        raise_lines = para.strip().split('\n')[1:]
                        for raise_line in raise_lines:
                            lines.append(f"- {raise_line.strip()}")
                        lines.append("")
                    else:
                        lines.append(textwrap.fill(para.strip(), width=config.line_width))
                        lines.append("")
        
        # Source code link generation
        if config.include_source_links and config.source_url_template:
            try:
                file_path = inspect.getfile(obj)
                line_no = inspect.getsourcelines(obj)[1]
                url = config.source_url_template.format(
                    path=file_path,
                    line=line_no,
                )
                lines.append(_format_link("View source", url, config.format))
                lines.append("")
            except (TypeError, OSError):
                # Gracefully handle built-in or C extension functions
                pass
        
        # Usage examples generation
        if config.include_examples:
            try:
                ex = examples(obj, text=True)
                if ex:
                    if len(ex) > config.max_example_length:
                        ex = ex[:config.max_example_length] + "\n... (truncated)"
                    
                    lines.append("**Examples:**")
                    lines.append("")
                    lines.append(_format_code_block(ex.strip(), "python", config.format))
                    lines.append("")
            except Exception as e:
                if config.verbose:
                    lines.append(f"*Unable to generate examples: {e}*")
                    lines.append("")
        
        return lines


class VariableHandler(ObjectHandler):
    """
    Specialized handler for generating variable and constant documentation.
    
    This handler produces documentation for module-level variables, constants,
    and other non-callable objects. It displays type information via the
    object's __class__.__name__ and provides a truncated representation of
    the value for inspection purposes.
    
    The handler is intentionally simple, focusing on type and value display
    rather than attempting to extract docstrings from arbitrary objects.
    """
    
    def can_handle(self, obj: Any) -> bool:
        """
        Check if the object is a variable (non-module, non-callable, non-class).
        
        Parameters
        ----------
        obj : Any
            Object to test for variable type.
            
        Returns
        -------
        bool
            True if obj is a variable, False otherwise.
        """
        return not (inspect.isclass(obj) or inspect.isroutine(obj) or inspect.ismodule(obj))
    
    def generate_documentation(
        self,
        name: str,
        obj: Any,
        context: DocumentationContext,
    ) -> List[str]:
        """
        Generate variable documentation.
        
        Parameters
        ----------
        name : str
            Name of the variable being documented.
        obj : Any
            Variable object to document.
        context : DocumentationContext
            Current documentation generation context.
        
        Returns
        -------
        List[str]
            List of strings containing the generated documentation.
        """
        lines: List[str] = []
        config = context.config
        
        # Generate header with anchor
        anchor = context.generate_anchor(f"var-{name}")
        context.add_cross_reference(name, anchor)
        
        heading_level = context.get_heading_level("Variables")
        lines.append(_format_heading(name, heading_level, config.format, anchor))
        lines.append("")
        
        # Type information from object's class
        type_name = type(obj).__name__
        lines.append(f"*Type:* Variable ({type_name})")
        
        # Truncated value representation
        try:
            value_repr = repr(obj)
            if len(value_repr) > 200:
                value_repr = value_repr[:197] + "..."
            lines.append(f"*Value:* {_format_inline_code(value_repr, config.format)}")
        except:
            lines.append("*Value:* <unable to represent>")
        
        lines.append("")
        
        # Include docstring if the variable has one (uncommon but possible)
        if hasattr(obj, '__doc__') and obj.__doc__:
            doc = inspect.getdoc(obj)
            if doc:
                lines.append(doc.strip())
                lines.append("")
        
        return lines


# -----------------------------------------------------------------------------
# Module Documenter
# -----------------------------------------------------------------------------

class ModuleDocumenter:
    """
    Main documentation generation engine orchestrating the entire pipeline.
    
    This class coordinates the complete documentation generation workflow:
    collecting module members, categorizing them, applying appropriate handlers,
    generating section headings, tables of contents, statistics, and assembling
    the final output in the requested format.
    
    The documenter supports plugin handlers through the handler registry and
    integrates with a global thread-safe cache for performance.
    
    Parameters
    ----------
    config : Optional[DocumentationConfig]
        Configuration controlling documentation generation behavior.
        If None, uses default DocumentationConfig.
    handlers : Optional[List[ObjectHandler]]
        List of custom object handlers to use. If None, uses the default
        handlers (ClassHandler, FunctionHandler, VariableHandler).
    
    Attributes
    ----------
    config : DocumentationConfig
        Current configuration used for generation.
    handlers : List[ObjectHandler]
        List of registered object documentation handlers.
    cache : DocumentationCache
        Thread-safe cache for generated documentation.
    """
    
    def __init__(
        self,
        config: Optional[DocumentationConfig] = None,
        handlers: Optional[List[ObjectHandler]] = None,
    ) -> None:
        """
        Initialize a new module documenter instance.
        
        Parameters
        ----------
        config : Optional[DocumentationConfig]
            Configuration for documentation generation. Uses defaults if None.
        handlers : Optional[List[ObjectHandler]]
            Custom object handlers. Uses default handlers if None.
        """
        self.config = config or DocumentationConfig()
        self.handlers = handlers or [
            ClassHandler(),
            FunctionHandler(),
            VariableHandler(),
        ]
        self.cache = _global_cache
        self._lock = threading.RLock()
    
    def _get_handler(self, obj: Any) -> Optional[ObjectHandler]:
        """
        Find the first handler capable of documenting the given object.
        
        Iterates through the registered handlers in order and returns the
        first one whose can_handle() method returns True.
        
        Parameters
        ----------
        obj : Any
            The object to find a handler for.
            
        Returns
        -------
        Optional[ObjectHandler]
            First compatible handler, or None if no handler is compatible.
        """
        for handler in self.handlers:
            if handler.can_handle(obj):
                return handler
        return None
    
    def _collect_objects(
        self,
        module: ModuleType,
        context: DocumentationContext,
    ) -> Tuple[Dict[str, List[Tuple[str, Any, bool]]], Dict[str, List[Tuple[str, Any, bool]]]]:
        """
        Collect and categorize all documented members from a module.
        
        This method iterates through all module members, applies filtering
        based on configuration, categorizes each member, and separates public
        from private members when requested.
        
        Parameters
        ----------
        module : ModuleType
            The module to collect members from.
        context : DocumentationContext
            Current documentation context with configuration.
        
        Returns
        -------
        Tuple containing:
            - main_sections: Dict mapping categories to lists of (name, obj, is_private) tuples
            - private_sections: Dict mapping private categories to lists of tuples
        """
        config = context.config
        
        # Initialize section containers
        main_sections: Dict[str, List[Tuple[str, Any, bool]]] = {
            "Classes": [],
            "Functions": [],
            "Variables": [],
        }
        
        # Additional sections for categorized special methods
        if config.group_by_category:
            for category in set(SPECIAL_METHOD_CATEGORIES.values()):
                main_sections[f"Special: {category}"] = []
        
        private_sections: Dict[str, List[Tuple[str, Any, bool]]] = {
            "Private Classes": [],
            "Private Functions": [],
            "Private Variables": [],
        }
        
        # Collect and categorize each module attribute
        for name in dir(module):
            is_private = name.startswith("_")
            
            # Skip private if not configured to include them
            if not config.include_private and is_private:
                continue
            
            # Safely retrieve object
            obj = inspect.getattr_static(module, name, None)
            if obj is None:
                continue
            
            # Determine primary category
            category = _categorize_object(obj, name, config)
            if category is None:
                continue
            
            # Apply type filter if specified
            if config.filter_by:
                if config.filter_by == "classes" and category != "Classes":
                    continue
                elif config.filter_by == "functions" and category != "Functions":
                    continue
                elif config.filter_by == "variables" and category != "Variables":
                    continue
            
            # Handle special method categorization override
            if config.group_by_category and name.startswith('__') and name.endswith('__'):
                special_cat = _get_special_method_category(name)
                if special_cat:
                    category = f"Special: {special_cat}"
            
            # Place in appropriate section bucket
            if config.group_private and is_private:
                private_category = f"Private {category.replace('Special: ', '')}"
                if private_category not in private_sections:
                    private_sections[private_category] = []
                private_sections[private_category].append((name, obj, is_private))
            else:
                if category not in main_sections:
                    main_sections[category] = []
                main_sections[category].append((name, obj, is_private))
        
        # Sort items alphabetically for consistent output
        for category in main_sections:
            main_sections[category].sort(key=lambda x: x[0].lower())
        
        for category in private_sections:
            private_sections[category].sort(key=lambda x: x[0].lower())
        
        return main_sections, private_sections
    
    def _generate_module_header(
        self,
        module: ModuleType,
        context: DocumentationContext,
    ) -> List[str]:
        """
        Generate the module documentation header section.
        
        Creates a heading with the module name and includes metadata such as
        source file location, version, and author information when configured.
        
        Parameters
        ----------
        module : ModuleType
            The module being documented.
        context : DocumentationContext
            Current documentation context.
            
        Returns
        -------
        List[str]
            List of strings representing the module header documentation.
        """
        lines: List[str] = []
        config = context.config
        
        mod_name = getattr(module, "__name__", "<module>")
        mod_file = getattr(module, "__file__", "unknown")
        mod_version = getattr(module, "__version__", None)
        mod_author = getattr(module, "__author__", None)
        mod_doc = inspect.getdoc(module) or "No module documentation available."
        
        # Module heading with anchor
        anchor = context.generate_anchor(f"module-{mod_name}")
        lines.append(_format_heading(mod_name, config.title_level, config.format, anchor))
        context.add_toc_entry(1, mod_name, anchor)
        lines.append("")
        
        # Module metadata section
        if config.show_module_metadata:
            lines.append(f"**Source:** {mod_file}")
            
            if mod_version:
                lines.append(f"**Version:** {mod_version}")
            
            if mod_author:
                lines.append(f"**Author:** {mod_author}")
            
            lines.append("")
        
        # Module docstring content
        lines.append(mod_doc)
        lines.append("")
        
        return lines
    
    def _generate_toc(self, context: DocumentationContext) -> List[str]:
        """
        Generate a formatted table of contents from accumulated TOC entries.
        
        Parameters
        ----------
        context : DocumentationContext
            Context containing accumulated toc_entries.
            
        Returns
        -------
        List[str]
            List of strings forming the table of contents section.
            Returns empty list if include_toc is False.
        """
        lines: List[str] = []
        config = context.config
        
        if not config.include_toc or not context.toc_entries:
            return lines
        
        toc_level = config.title_level + 1
        lines.append(_format_heading("Table of Contents", toc_level, config.format))
        lines.append("")
        
        for level, title, anchor in context.toc_entries:
            indent = "  " * (level - 1)
            if config.format == "markdown":
                lines.append(f"{indent}- [{title}](#{anchor})")
            elif config.format == "html":
                lines.append(f'{indent}<a href="#{anchor}">{title}</a><br>')
            elif config.format == "rst":
                lines.append(f"{indent}- :ref:`{title} <{anchor}>`")
            else:
                lines.append(f"{indent}- {title}")
        
        lines.append("")
        return lines
    
    def _generate_statistics(
        self,
        main_sections: Dict[str, List[Tuple[str, Any, bool]]],
        private_sections: Dict[str, List[Tuple[str, Any, bool]]],
        context: DocumentationContext,
    ) -> List[str]:
        """
        Generate a statistics summary section showing item counts by category.
        
        Parameters
        ----------
        main_sections : Dict[str, List[Tuple[str, Any, bool]]]
            Categorized public member sections.
        private_sections : Dict[str, List[Tuple[str, Any, bool]]]
            Categorized private member sections (when enabled).
        context : DocumentationContext
            Current documentation context.
            
        Returns
        -------
        List[str]
            List of strings containing the statistics summary.
        """
        lines: List[str] = []
        config = context.config
        
        if config.format not in ("rst", "markdown", "html"):
            return lines
        
        stats_level = config.title_level + 1
        lines.append(_format_heading("Summary", stats_level, config.format))
        lines.append("")
        
        total_main = sum(len(items) for items in main_sections.values())
        stats = [
            f"Total documented items: {total_main}",
        ]
        
        for category, items in main_sections.items():
            if items:
                stats.append(f"{category}: {len(items)}")
        
        if config.group_private and config.include_private:
            total_private = sum(len(items) for items in private_sections.values())
            stats[0] = f"Total documented items: {total_main + total_private}"
            
            for category, items in private_sections.items():
                if items:
                    stats.append(f"{category}: {len(items)}")
        
        lines.append(_format_list(stats, config.format))
        lines.append("")
        
        return lines
    
    def generate(self, module: ModuleType) -> str:
        """
        Generate complete documentation for a module.
        
        This is the main entry point that orchestrates the entire documentation
        generation pipeline: collection, categorization, formatting, and assembly
        into the final output string.
        
        Parameters
        ----------
        module : ModuleType
            Module to generate documentation for.
        
        Returns
        -------
        str
            Complete generated documentation in the configured format.
        
        Raises
        ------
        TypeError
            If module is not an instance of ModuleType.
            
        Notes
        -----
        This method uses caching when enabled and handles errors gracefully
        by collecting them in the context rather than failing immediately.
        """
        if not isinstance(module, ModuleType):
            raise TypeError(f"Expected ModuleType, got {type(module).__name__}")
        
        config = self.config
        mod_name = module.__name__
        
        # Attempt cache retrieval for performance
        if config.enable_caching:
            config_hash = hashlib.md5(
                json.dumps(asdict(config), sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
            
            cached = self.cache.get(mod_name, config_hash)
            if cached is not None:
                logger.debug(f"Using cached documentation for {mod_name}")
                return cached
        
        # Initialize documentation context
        context = DocumentationContext(config, module)
        
        # Configure heading levels for section types
        base_level = config.title_level
        context.set_heading_level("Classes", base_level + 1)
        context.set_heading_level("Functions", base_level + 1)
        context.set_heading_level("Variables", base_level + 1)
        
        all_lines: List[str] = []
        
        try:
            # Generate module header
            all_lines.extend(self._generate_module_header(module, context))
            
            # Collect and categorize module members
            main_sections, private_sections = self._collect_objects(module, context)
            
            # Generate table of contents when required
            toc_lines = []
            if config.include_toc:
                for section in config.section_order:
                    if section in main_sections and main_sections[section]:
                        anchor = context.generate_anchor(f"section-{section}")
                        context.add_toc_entry(2, section, anchor)
                
                toc_lines = self._generate_toc(context)
            
            # Generate documentation for each section
            section_lines: List[str] = []
            
            for section in config.section_order:
                if section in main_sections and main_sections[section]:
                    # Section heading
                    anchor = context.generate_anchor(f"section-{section}")
                    section_lines.append(_format_heading(
                        section,
                        base_level + 1,
                        config.format,
                        anchor
                    ))
                    section_lines.append("")
                    
                    # Document each item in the section
                    for name, obj, is_private in main_sections[section]:
                        handler = self._get_handler(obj)
                        if handler:
                            try:
                                item_lines = handler.generate_documentation(name, obj, context)
                                section_lines.extend(item_lines)
                            except Exception as e:
                                error_msg = f"Failed to document {name}: {e}"
                                context.errors.append(error_msg)
                                logger.error(error_msg)
                                if config.verbose:
                                    section_lines.append(f"*Error documenting {name}: {e}*")
                                    section_lines.append("")
            
            # Document private members when grouped separately
            if config.group_private and config.include_private:
                for section, items in private_sections.items():
                    if items:
                        section_lines.append(_format_heading(section, base_level + 1, config.format))
                        section_lines.append("")
                        
                        for name, obj, is_private in items:
                            handler = self._get_handler(obj)
                            if handler:
                                try:
                                    item_lines = handler.generate_documentation(name, obj, context)
                                    section_lines.extend(item_lines)
                                except Exception as e:
                                    context.errors.append(f"Failed to document {name}: {e}")
            
            # Generate statistics summary
            stats_lines = self._generate_statistics(main_sections, private_sections, context)
            
            # Assemble final output in order: TOC -> Content -> Statistics
            all_lines.extend(toc_lines)
            all_lines.extend(section_lines)
            all_lines.extend(stats_lines)
            
            # Post-processing: clean up excessive blank lines for readability
            result = "\n".join(all_lines)
            lines = result.split("\n")
            cleaned_lines = []
            blank_count = 0
            
            for line in lines:
                if line.strip() == "":
                    blank_count += 1
                    if blank_count <= 2:
                        cleaned_lines.append(line)
                else:
                    blank_count = 0
                    cleaned_lines.append(line)
            
            result = "\n".join(cleaned_lines).strip() + "\n"
            
            # Store result in cache for future requests
            if config.enable_caching:
                self.cache.put(mod_name, config_hash, result)
            
            # Log completion statistics
            if config.verbose:
                logger.info(
                    f"Documentation generated for {mod_name} "
                    f"({len(context.errors)} errors, {len(context.warnings)} warnings)"
                )
            
            return result
            
        except Exception as e:
            context.errors.append(f"Documentation generation failed: {e}")
            logger.error(f"Failed to generate documentation for {mod_name}: {e}")
            raise


# -----------------------------------------------------------------------------
# Public API Functions
# -----------------------------------------------------------------------------

# Global state for configured defaults
_global_documenter: Optional[ModuleDocumenter] = None
_global_config: Optional[DocumentationConfig] = None
_global_lock = threading.RLock()


def doc_module(
    module: ModuleType,
    *,
    include_private: bool = False,
    include_examples: bool = True,
    max_example_length: int = DEFAULT_MAX_EXAMPLE_LENGTH,
    section_order: Optional[List[str]] = None,
    format: str = "rst",
    title_level: int = 1,
    group_private: bool = False,
    filter_by: Optional[str] = None,
    include_magic_methods: bool = False,
    include_inherited: bool = True,
    include_source_links: bool = False,
    source_url_template: Optional[str] = None,
    include_toc: bool = False,
    show_bases: bool = True,
    show_mro: bool = False,
    verbose: bool = False,
) -> str:
    """
    Generate comprehensive documentation for a Python module.
    
    This is the primary public API for module documentation generation. It provides
    a convenient interface to the ModuleDocumenter engine with extensive
    configuration options for controlling output format, content inclusion, and
    formatting preferences.
    
    Parameters
    ----------
    module : ModuleType
        The module to generate documentation for.
    include_private : bool, default=False
        When True, includes private attributes (names starting with '_').
    include_examples : bool, default=True
        When True, includes auto-generated usage examples where available.
    max_example_length : int, default=500
        Maximum character length for examples before truncation.
    section_order : List[str], optional
        Custom order for documentation sections. Defaults to
        ['Classes', 'Functions', 'Variables'].
    format : str, default='rst'
        Output format. Must be one of: 'rst', 'markdown', 'html', 'plain', 'json'.
    title_level : int, default=1
        Starting heading level for the module title.
    group_private : bool, default=False
        When True and include_private is True, separates private items into
        dedicated sections.
    filter_by : str, optional
        Restrict output to a specific type: 'classes', 'functions', 'variables',
        or None for all types.
    include_magic_methods : bool, default=False
        When True, includes special/magic methods (__*__) in output.
    include_inherited : bool, default=True
        When True, includes inherited members in class documentation.
    include_source_links : bool, default=False
        When True and source_url_template is provided, adds source code links.
    source_url_template : str, optional
        URL template for source code linking. Must contain {path} and {line}
        placeholders. Example: 'https://github.com/user/repo/blob/main/{path}#L{line}'.
    include_toc : bool, default=False
        When True, generates and includes a table of contents.
    show_bases : bool, default=True
        When True, displays base/parent classes.
    show_mro : bool, default=False
        When True, displays the full method resolution order.
    verbose : bool, default=False
        When True, enables verbose logging output.
    
    Returns
    -------
    str
        Complete generated documentation string in the requested format.
    
    Raises
    ------
    TypeError
        If module is not an instance of ModuleType.
    ValueError
        If format is not supported or filter_by is invalid.
    
    Examples
    --------
    Basic usage with default settings:
    
    >>> import math
    >>> doc = doc_module(math, format='markdown')
    >>> print(doc[:200])
    
    Generate HTML documentation with table of contents:
    
    >>> doc = doc_module(
    ...     math,
    ...     format='html',
    ...     include_toc=True,
    ...     title_level=1,
    ... )
    
    Document only classes with source code links to GitHub:
    
    >>> doc = doc_module(
    ...     my_module,
    ...     filter_by='classes',
    ...     include_source_links=True,
    ...     source_url_template='https://github.com/user/repo/blob/main/{path}#L{line}',
    ... )
    
    Generate JSON output for programmatic consumption:
    
    >>> doc = doc_module(math, format='json')
    >>> import json
    >>> data = json.loads(doc)
    
    Notes
    -----
    - Uses advanced introspection for comprehensive information extraction.
    - Results are cached when identical configurations are used repeatedly.
    - Thread-safe operation for concurrent documentation generation.
    - Cross-platform path handling is automatic.
    """
    # Validate module parameter
    if not isinstance(module, ModuleType):
        raise TypeError(
            f"Expected `module` to be ModuleType, got {type(module).__name__}"
        )
    
    # Validate format parameter
    if format not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format: {format}. Use {SUPPORTED_FORMATS}"
        )
    
    # Validate filter parameter
    if filter_by and filter_by not in ("classes", "functions", "variables"):
        raise ValueError(
            f"Invalid filter_by: {filter_by}. "
            "Use 'classes', 'functions', 'variables', or None."
        )
    
    # Create configuration from parameters
    config = DocumentationConfig(
        format=format,
        include_private=include_private,
        include_examples=include_examples,
        max_example_length=max_example_length,
        section_order=section_order or ["Classes", "Functions", "Variables"],
        title_level=title_level,
        group_private=group_private,
        filter_by=filter_by,
        include_magic_methods=include_magic_methods,
        include_inherited=include_inherited,
        include_source_links=include_source_links,
        source_url_template=source_url_template,
        include_toc=include_toc,
        show_bases=show_bases,
        show_mro=show_mro,
        verbose=verbose,
    )
    
    # Create documenter and generate documentation
    documenter = ModuleDocumenter(config)
    return documenter.generate(module)


def module_examples(
    module: ModuleType,
    *,
    filter_by: Optional[Type[object]] = None,
    extractor: Optional[Callable[[Any], str]] = None,
    skip_private: bool = True,
    max_examples: Optional[int] = None,
    include_signatures: bool = True,
) -> Dict[str, str]:
    """
    Collect usage examples for module attributes with filtering and customization.
    
    This function inspects a module's public attributes and extracts example usage
    for each, supporting custom extraction functions and filtering by type.
    
    Parameters
    ----------
    module : ModuleType
        The module to extract examples from.
    filter_by : type, optional
        Only objects passing isinstance(obj, filter_by) are included.
    extractor : Callable[[Any], str], optional
        Custom function to extract examples from an object. Defaults to the
        built-in examples() function.
    skip_private : bool, default=True
        When True, skips attributes starting with '_'.
    max_examples : int, optional
        Maximum number of examples to return. Returns all if None.
    include_signatures : bool, default=True
        When True, prepends function/class signatures to examples.
    
    Returns
    -------
    Dict[str, str]
        Dictionary mapping attribute names to their example strings.
    
    Raises
    ------
    TypeError
        If module is not a ModuleType instance.
    
    Examples
    --------
    >>> import math
    >>> examples_dict = module_examples(math, filter_by=callable)
    >>> print(examples_dict.get("sqrt", "No example"))
    
    >>> def custom_extractor(obj):
    ...     return f"Example usage of {obj.__name__}"
    >>> examples_dict = module_examples(math, extractor=custom_extractor)
    
    >>> examples_dict = module_examples(math, max_examples=5)
    """
    if not isinstance(module, ModuleType):
        raise TypeError(
            f"Expected `module` to be ModuleType, got {type(module).__name__}"
        )
    
    result: Dict[str, str] = {}
    count = 0
    
    for name in dir(module):
        if max_examples and count >= max_examples:
            break
        
        if skip_private and name.startswith("_"):
            continue
        
        obj = inspect.getattr_static(module, name, None)
        if obj is None:
            continue
        
        # Apply type filter if specified
        if filter_by is not None:
            try:
                if not isinstance(obj, filter_by):
                    continue
            except TypeError:
                if not filter_by(obj):
                    continue
        
        # Extract example using custom or default extractor
        try:
            if extractor is not None:
                example_text = extractor(obj)
            else:
                example_text = examples(obj, text=True)
            
            if example_text:
                if include_signatures and (inspect.isclass(obj) or inspect.isroutine(obj)):
                    sig = _format_signature(name, obj, "plain", True, True)
                    example_text = f"{sig}\n{example_text}"
                
                result[name] = example_text
                count += 1
        except Exception as e:
            logger.debug(f"Failed to extract example for {name}: {e}")
            continue
    
    return result


def configure_documentation(
    format: Optional[str] = None,
    include_private: Optional[bool] = None,
    include_examples: Optional[bool] = None,
    max_example_length: Optional[int] = None,
    enable_caching: Optional[bool] = None,
    cache_size: Optional[int] = None,
    verbose: Optional[bool] = None,
    **kwargs: Any,
) -> None:
    """
    Configure global documentation settings for all subsequent calls.
    
    This function sets default configuration values that will be used by
    doc_module() and related functions when explicit parameters are not provided.
    It provides a convenient way to establish project-wide documentation standards.
    
    Parameters
    ----------
    format : str, optional
        Default output format for documentation.
    include_private : bool, optional
        Default setting for inclusion of private members.
    include_examples : bool, optional
        Default setting for inclusion of usage examples.
    max_example_length : int, optional
        Default maximum length for examples.
    enable_caching : bool, optional
        Default caching behavior.
    cache_size : int, optional
        Default cache capacity.
    verbose : bool, optional
        Default verbosity setting.
    **kwargs : Any
        Additional configuration options to set on DocumentationConfig.
    
    Examples
    --------
    >>> configure_documentation(
    ...     format='markdown',
    ...     include_private=False,
    ...     enable_caching=True,
    ...     verbose=True,
    ... )
    """
    global _global_config
    
    with _global_lock:
        if _global_config is None:
            _global_config = DocumentationConfig()
        
        for key, value in locals().items():
            if key not in ('kwargs',) and value is not None:
                if hasattr(_global_config, key):
                    setattr(_global_config, key, value)
        
        for key, value in kwargs.items():
            if hasattr(_global_config, key):
                setattr(_global_config, key, value)


def clear_documentation_cache() -> None:
    """
    Clear the global documentation cache.
    
    This function removes all cached documentation entries and resets
    cache statistics. It is useful when modules have been modified and
    cached documentation may be stale.
    
    Examples
    --------
    >>> clear_documentation_cache()
    """
    _global_cache.clear()
    logger.info("Documentation cache cleared")


def get_cache_stats() -> Dict[str, Any]:
    """
    Retrieve current documentation cache statistics.
    
    Returns
    -------
    Dict[str, Any]
        Dictionary with cache statistics including size, capacity, hits,
        misses, and hit rate percentage.
    
    Examples
    --------
    >>> stats = get_cache_stats()
    >>> print(f"Cache hit rate: {stats['hit_rate']}")
    >>> print(f"Cache size: {stats['size']}/{stats['max_size']}")
    """
    return _global_cache.stats


def export_doc(
    module: ModuleType,
    output_path: Union[str, Path],
    format: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """
    Generate documentation and export it to a file.
    
    This convenience function generates documentation for a module and writes
    it to the specified output file, creating parent directories as needed.
    The output format is inferred from the file extension when not explicitly
    provided.
    
    Parameters
    ----------
    module : ModuleType
        Module to document and export.
    output_path : Union[str, Path]
        Path for the output documentation file.
    format : str, optional
        Output format override. Inferred from file extension if None:
        .rst -> rst, .md -> markdown, .html/.htm -> html, .txt -> plain,
        .json -> json.
    **kwargs : Any
        Additional keyword arguments passed to doc_module().
    
    Returns
    -------
    str
        Absolute path to the exported documentation file.
    
    Examples
    --------
    >>> import math
    >>> export_doc(math, "docs/math_docs.md")
    >>> export_doc(math, "docs/math_docs.html", include_toc=True)
    """
    output_path = Path(output_path)
    
    # Infer output format from file extension when not specified
    if format is None:
        ext = output_path.suffix.lower()
        format_map = {
            '.rst': 'rst',
            '.md': 'markdown',
            '.html': 'html',
            '.htm': 'html',
            '.txt': 'plain',
            '.json': 'json',
        }
        format = format_map.get(ext, 'rst')
    
    # Generate documentation and write to file
    doc = doc_module(module, format=format, **kwargs)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc, encoding='utf-8')
    
    logger.info(f"Documentation exported to {output_path}")
    
    return str(output_path)


def generate_api_docs(
    package_name: str,
    output_dir: Union[str, Path],
    format: str = "markdown",
    recursive: bool = True,
    **kwargs: Any,
) -> List[str]:
    """
    Generate documentation for an entire Python package recursively.
    
    This function documents a package and optionally all its subpackages and
    submodules, generating individual documentation files for each module.
    
    Parameters
    ----------
    package_name : str
        Importable name of the package to document.
    output_dir : Union[str, Path]
        Directory path where documentation files will be written.
    format : str, default='markdown'
        Output format for documentation files.
    recursive : bool, default=True
        When True, documents all subpackages and submodules recursively.
    **kwargs : Any
        Additional keyword arguments passed to doc_module().
    
    Returns
    -------
    List[str]
        List of absolute paths to all generated documentation files.
    
    Raises
    ------
    ImportError
        If the specified package cannot be imported.
    
    Examples
    --------
    >>> files = generate_api_docs("my_package", "./docs/api")
    >>> print(f"Generated {len(files)} documentation files")
    
    >>> files = generate_api_docs("my_package", "./docs/api", recursive=False)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    generated_files = []
    
    try:
        package = importlib.import_module(package_name)
        
        # Document main package __init__.py
        main_output = output_dir / f"{package_name}.{_get_extension(format)}"
        export_doc(package, main_output, format=format, **kwargs)
        generated_files.append(str(main_output))
        
        # Recursively document submodules
        if recursive and hasattr(package, '__path__'):
            for path in package.__path__:
                pkg_path = Path(path)
                for py_file in pkg_path.rglob("*.py"):
                    if py_file.name == "__init__.py":
                        continue
                    
                    rel_path = py_file.relative_to(pkg_path.parent)
                    module_name = f"{package_name}.{str(rel_path.with_suffix('')).replace(os.sep, '.')}"
                    
                    try:
                        submodule = importlib.import_module(module_name)
                        sub_output = output_dir / f"{module_name}.{_get_extension(format)}"
                        sub_output.parent.mkdir(parents=True, exist_ok=True)
                        
                        export_doc(submodule, sub_output, format=format, **kwargs)
                        generated_files.append(str(sub_output))
                    except ImportError as e:
                        logger.warning(f"Could not import {module_name}: {e}")
        
        logger.info(f"Generated {len(generated_files)} documentation files")
        
    except ImportError as e:
        logger.error(f"Could not import package {package_name}: {e}")
        raise
    
    return generated_files


def _get_extension(format: str) -> str:
    """
    Map documentation format to file extension.
    
    Parameters
    ----------
    format : str
        Documentation format identifier.
    
    Returns
    -------
    str
        Corresponding file extension without dot prefix.
    """
    ext_map = {
        'rst': 'rst',
        'markdown': 'md',
        'html': 'html',
        'plain': 'txt',
        'json': 'json',
    }
    return ext_map.get(format, 'txt')


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Main public API functions
    'doc_module',
    'module_examples',
    'configure_documentation',
    'clear_documentation_cache',
    'get_cache_stats',
    'export_doc',
    'generate_api_docs',
    
    # Core classes
    'DocumentationConfig',
    'DocumentationContext',
    'ModuleDocumenter',
    'DocumentationCache',
    'PlatformInfo',
    'ClassHandler',
    'FunctionHandler',
    'VariableHandler',
    'ObjectHandler',
    
    # Formatting utilities
    '_format_heading',
    '_format_code_block',
    '_format_inline_code',
    '_format_link',
    '_format_list',
    '_format_type_hint',
    '_format_signature',
    
    # Utilities
    '_categorize_object',
    '_get_object_type_info',
    '_get_special_method_category',
    
    # Module constants
    'SUPPORTED_FORMATS',
    'SPECIAL_METHOD_CATEGORIES',
]