#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
pyputil.tree.printer - Professional Dependency Tree Printing Module
================================================================================

A comprehensive, production-ready module for printing and visualizing Python
package dependency trees directly in the terminal with beautiful formatting,
color support, and advanced deduplication features.

Module Overview
---------------
This module provides sophisticated capabilities for printing dependency trees
with professional terminal output, configurable styling, and multiple output
formats. It includes a complete rewrite of the printing engine with full
support for shared dependency deduplication.

Key Features:
-------------
1. Professional Terminal Output - Beautiful tree rendering with Unicode/ASCII
2. Advanced Deduplication - 5 strategies for handling shared dependencies
3. Multiple Output Formats - TEXT, JSON, YAML, HTML, DOT, Mermaid, Markdown
4. Configurable Styling - Colors, indentation, display toggles
5. Cycle Detection - Clear visual indicators for circular dependencies
6. Parallel Processing - Thread pool for large tree performance
7. Filtering Support - Regex patterns, optional/dev exclusion, platform filters

Example Usage
-------------
>>> from pyputil.tree.printer import print_dep_tree, DependencyTreePrinter, DuplicateHandling
>>> 
>>> # Basic usage
>>> print_dep_tree("requests", max_depth=2)
>>> 
>>> # With deduplication
>>> print_dep_tree("pyputil", max_depth=3, deduplicate_shared=True, duplicate_handling="merge")
>>> 
>>> # Custom printer
>>> printer = DependencyTreePrinter(
...     deduplicate_shared=True,
...     duplicate_handling=DuplicateHandling.COLLAPSE,
...     style=TreeStyle(colorize=True, show_extras=True)
... )
>>> printer.print_tree("pandas")
"""

import re
import sys
import logging
from typing import Optional, Set, Pattern, List, Dict, Any, Union, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
from collections import defaultdict

from ..core.cache import PackageCache
from ..core.parser import parse_requirement, normalize_package_name
from ..utils.filters import should_include_requirement

# Configure module logger
logger = logging.getLogger(__name__)

# Try to import colorama for Windows color support
try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False


# =============================================================================
# ENUMERATIONS
# =============================================================================

class DuplicateHandling(Enum):
    """
    Strategies for handling shared/deduplicate dependencies in printed output.
    
    This enumeration defines how duplicate dependencies (packages that appear
    multiple times in the dependency tree) are represented in the printed
    terminal output. Each strategy serves a different use case.
    
    Attributes
    ----------
    SHOW_ALL : str
        Show all occurrences of every package. Provides complete accuracy
        but can be very verbose. Best for debugging and when you need to
        see every path to a package.
    
    DEDUPLICATE : str
        Show each package only once per depth level. If the same package
        appears multiple times at the same depth, only the first occurrence
        is shown. This reduces clutter while maintaining context.
    
    MERGE : str
        Merge duplicate branches into a single reference pointer. When a
        package subtree is identical to a previously seen one, it is replaced
        with a "[see above]" indicator. Best for large trees where structure
        matters more than individual paths.
    
    MARK_SHARED : str
        Show all occurrences but mark shared dependencies with a special
        "[shared]" status indicator. This helps identify which packages are
        reused across the tree. Best for analysis and optimization.
    
    COLLAPSE : str
        Collapse duplicate subtrees and show a reference count. If a package
        appears 5 times, it is shown once with a badge like "[x5]". Best for
        high-level overview and summary reports.
    
    Examples
    --------
    >>> strategy = DuplicateHandling.MERGE
    >>> strategy.get_indicator()
    '[see above]'
    >>> strategy.should_collapse()
    False
    >>> strategy.is_deduplication_enabled()
    True
    """
    
    SHOW_ALL = "show_all"
    DEDUPLICATE = "deduplicate"
    MERGE = "merge"
    MARK_SHARED = "mark_shared"
    COLLAPSE = "collapse"
    
    def get_display_name(self) -> str:
        """
        Get human-readable display name for the strategy.
        
        Returns
        -------
        str
            User-friendly name for display in help text.
        """
        names = {
            DuplicateHandling.SHOW_ALL: "Show All",
            DuplicateHandling.DEDUPLICATE: "Deduplicate",
            DuplicateHandling.MERGE: "Merge",
            DuplicateHandling.MARK_SHARED: "Mark Shared",
            DuplicateHandling.COLLAPSE: "Collapse"
        }
        return names.get(self, "Unknown")
    
    def get_indicator(self) -> str:
        """
        Get the visual indicator text for this handling strategy.
        
        Returns
        -------
        str
            Indicator string to display for shared/merged dependencies.
            For COLLAPSE strategy, returns a format string with {} placeholder.
        
        Examples
        --------
        >>> DuplicateHandling.MERGE.get_indicator()
        '[see above]'
        >>> DuplicateHandling.COLLAPSE.get_indicator()
        '[x{}]'
        """
        indicators = {
            DuplicateHandling.SHOW_ALL: "",
            DuplicateHandling.DEDUPLICATE: "",
            DuplicateHandling.MERGE: "[see above]",
            DuplicateHandling.MARK_SHARED: "[shared]",
            DuplicateHandling.COLLAPSE: "[x{}]"
        }
        return indicators.get(self, "")
    
    def should_show_marker(self) -> bool:
        """
        Check if this strategy requires a visual marker on shared dependencies.
        
        Returns
        -------
        bool
            True for MARK_SHARED strategy only.
        """
        return self == DuplicateHandling.MARK_SHARED
    
    def should_collapse(self) -> bool:
        """
        Check if this strategy collapses duplicate subtrees.
        
        Returns
        -------
        bool
            True for COLLAPSE strategy only.
        """
        return self == DuplicateHandling.COLLAPSE
    
    def should_merge(self) -> bool:
        """
        Check if this strategy merges duplicate branches into references.
        
        Returns
        -------
        bool
            True for MERGE strategy only.
        """
        return self == DuplicateHandling.MERGE
    
    def is_deduplication_enabled(self) -> bool:
        """
        Check if this strategy performs any form of deduplication.
        
        Returns
        -------
        bool
            True for all strategies except SHOW_ALL.
        """
        return self != DuplicateHandling.SHOW_ALL
    
    def get_description(self) -> str:
        """
        Get detailed description of the strategy for help text.
        
        Returns
        -------
        str
            Human-readable description explaining when to use this strategy.
        """
        descriptions = {
            DuplicateHandling.SHOW_ALL: "Show all occurrences - complete accuracy, most verbose",
            DuplicateHandling.DEDUPLICATE: "Show each package once per depth - balanced",
            DuplicateHandling.MERGE: "Merge duplicate branches into references - cleanest",
            DuplicateHandling.MARK_SHARED: "Mark shared dependencies - good for analysis",
            DuplicateHandling.COLLAPSE: "Collapse with reference counts - best for overview"
        }
        return descriptions.get(self, "Unknown strategy")


class TreeOutputFormat(Enum):
    """
    Supported output formats for dependency tree visualization.
    
    This enumeration defines all available output formats for exporting
    dependency trees. Each format serves different use cases from human
    reading to machine processing and graphical visualization.
    
    Attributes
    ----------
    TEXT : str
        ASCII/Unicode tree format with box-drawing characters. Best for
        terminal display and human reading.
    
    MARKDOWN : str
        Markdown-formatted tree using indentation. Good for documentation.
    
    JSON : str
        JSON structured format. Best for programmatic processing and APIs.
    
    DICT : str
        Python dictionary representation. Best for internal use.
    
    HTML : str
        Interactive HTML tree visualization with collapsible nodes.
    
    DOT : str
        Graphviz DOT format for external graph rendering.
    
    MERMAID : str
        Mermaid flowchart syntax for web-based diagrams.
    
    PLAIN : str
        Plain text without tree characters (simple indentation).
    
    Examples
    --------
    >>> fmt = TreeOutputFormat.TEXT
    >>> fmt.is_visual()
    True
    >>> fmt.get_extension()
    '.txt'
    >>> fmt.get_description()
    'ASCII/Unicode tree format with box-drawing characters'
    """
    
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    DICT = "dict"
    HTML = "html"
    DOT = "dot"
    MERMAID = "mermaid"
    PLAIN = "plain"
    
    def is_visual(self) -> bool:
        """
        Check if format produces visual/graphical output.
        
        Returns
        -------
        bool
            True for HTML, DOT, MERMAID formats that can be rendered
            as images or interactive visualizations.
        """
        return self in (TreeOutputFormat.HTML, TreeOutputFormat.DOT, 
                       TreeOutputFormat.MERMAID)
    
    def is_structured(self) -> bool:
        """
        Check if format is structured (machine-readable).
        
        Returns
        -------
        bool
            True for JSON and DICT formats suitable for parsing.
        """
        return self in (TreeOutputFormat.JSON, TreeOutputFormat.DICT)
    
    def is_human_readable(self) -> bool:
        """
        Check if format is designed for human reading.
        
        Returns
        -------
        bool
            True for TEXT, MARKDOWN, HTML, PLAIN formats.
        """
        return self in (TreeOutputFormat.TEXT, TreeOutputFormat.MARKDOWN,
                       TreeOutputFormat.HTML, TreeOutputFormat.PLAIN)
    
    def get_extension(self) -> str:
        """
        Get standard file extension for this format.
        
        Returns
        -------
        str
            File extension including the dot (e.g., '.txt', '.json').
        
        Examples
        --------
        >>> TreeOutputFormat.JSON.get_extension()
        '.json'
        >>> TreeOutputFormat.HTML.get_extension()
        '.html'
        """
        extensions = {
            TreeOutputFormat.TEXT: '.txt',
            TreeOutputFormat.MARKDOWN: '.md',
            TreeOutputFormat.JSON: '.json',
            TreeOutputFormat.HTML: '.html',
            TreeOutputFormat.DOT: '.dot',
            TreeOutputFormat.MERMAID: '.mmd',
            TreeOutputFormat.PLAIN: '.txt'
        }
        return extensions.get(self, '.txt')
    
    def get_description(self) -> str:
        """
        Get human-readable description of the format.
        
        Returns
        -------
        str
            Description of when to use this format.
        """
        descriptions = {
            TreeOutputFormat.TEXT: "ASCII/Unicode tree format with box-drawing characters",
            TreeOutputFormat.MARKDOWN: "Markdown-formatted tree using indentation",
            TreeOutputFormat.JSON: "JSON structured format for programmatic processing",
            TreeOutputFormat.DICT: "Python dictionary representation",
            TreeOutputFormat.HTML: "Interactive HTML tree with collapsible nodes",
            TreeOutputFormat.DOT: "Graphviz DOT format for graph rendering",
            TreeOutputFormat.MERMAID: "Mermaid flowchart syntax for web diagrams",
            TreeOutputFormat.PLAIN: "Plain text with simple indentation"
        }
        return descriptions.get(self, "Unknown format")


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TreeNode:
    """
    Structured representation of a node in the dependency tree.
    
    This dataclass represents a single package node in the dependency tree
    with all its metadata and children. It supports serialization to various
    formats and provides utility methods for tree analysis.
    
    Attributes
    ----------
    name : str
        Package name (e.g., 'requests', 'numpy').
    
    version : str, default=""
        Installed version of the package (e.g., '2.28.1').
    
    requirement : str, default=""
        Version requirement from parent package (e.g., '>=2.0').
    
    status : str, default="installed"
        Installation status: 'installed', 'not_installed', 'error',
        'cycle_detected', 'shared', 'merged', 'collapsed'.
    
    dependencies : List['TreeNode'], default=[]
        List of child dependency nodes.
    
    extras : List[str], default=[]
        Package extras that activate this dependency.
    
    marker : str, default=""
        Environment marker string (PEP 508).
    
    depth : int, default=0
        Depth in the tree (0 for root).
    
    metadata : Dict[str, Any], default={}
        Additional metadata like reference counts, error messages, etc.
    
    Examples
    --------
    >>> node = TreeNode(
    ...     name='requests',
    ...     version='2.28.1',
    ...     dependencies=[
    ...         TreeNode(name='urllib3', version='1.26.13')
    ...     ]
    ... )
    >>> node.to_dict()
    {'name': 'requests', 'version': '2.28.1', ...}
    >>> node.get_size()
    2
    """
    
    name: str
    version: str = ""
    requirement: str = ""
    status: str = "installed"
    dependencies: List['TreeNode'] = field(default_factory=list)
    extras: List[str] = field(default_factory=list)
    marker: str = ""
    depth: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert node to dictionary representation recursively.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with all node data including nested dependencies.
        
        Examples
        --------
        >>> node = TreeNode(name='requests', version='2.28.1')
        >>> node.to_dict()
        {'name': 'requests', 'version': '2.28.1', 'status': 'installed', ...}
        """
        return {
            'name': self.name,
            'version': self.version,
            'requirement': self.requirement,
            'status': self.status,
            'extras': self.extras,
            'marker': self.marker,
            'depth': self.depth,
            'metadata': self.metadata,
            'dependencies': [dep.to_dict() for dep in self.dependencies]
        }
    
    def to_json(self, indent: int = 2) -> str:
        """
        Convert node to JSON string.
        
        Parameters
        ----------
        indent : int, default=2
            Indentation level for pretty printing.
        
        Returns
        -------
        str
            JSON representation of the node and its children.
        
        Examples
        --------
        >>> node = TreeNode(name='requests')
        >>> node.to_json()
        '{\\n  "name": "requests",\\n  ...\\n}'
        """
        import json
        return json.dumps(self.to_dict(), indent=indent, default=str)
    
    def get_size(self) -> int:
        """
        Get total number of nodes in the subtree.
        
        Returns
        -------
        int
            Total node count including this node and all descendants.
        
        Examples
        --------
        >>> root = TreeNode(name='root', dependencies=[
        ...     TreeNode(name='child1'),
        ...     TreeNode(name='child2')
        ... ])
        >>> root.get_size()
        3
        """
        return 1 + sum(dep.get_size() for dep in self.dependencies)
    
    def get_max_depth(self) -> int:
        """
        Get maximum depth of the subtree from this node.
        
        Returns
        -------
        int
            Maximum depth (0 if no children).
        
        Examples
        --------
        >>> node = TreeNode(name='root', depth=0)
        >>> node.get_max_depth()
        0
        """
        if not self.dependencies:
            return self.depth
        return max(dep.get_max_depth() for dep in self.dependencies)
    
    def get_leaf_count(self) -> int:
        """
        Count the number of leaf nodes (nodes with no dependencies).
        
        Returns
        -------
        int
            Number of leaf nodes in the subtree.
        """
        if not self.dependencies:
            return 1
        return sum(dep.get_leaf_count() for dep in self.dependencies)
    
    def __repr__(self) -> str:
        """String representation of node for debugging."""
        deps_count = len(self.dependencies)
        return f"<TreeNode {self.name}=={self.version} ({deps_count} deps, {self.status})>"


@dataclass
class TreeStyle:
    """
    Styling configuration for tree visualization.
    
    This dataclass holds all visual styling options for printing dependency
    trees, including character sets, colors, indentation, and display toggles.
    
    Parameters
    ----------
    use_unicode : bool, default=True
        Use Unicode box-drawing characters (├──, └──, │). When False, uses
        ASCII characters (|--, `--, |) for better compatibility with older
        terminals or when output is saved to files.
    
    indent_size : int, default=2
        Number of spaces per indentation level. Larger values create more
        visual separation but reduce horizontal space for package names.
    
    show_versions : bool, default=True
        Display installed package versions next to package names.
        Example: "requests==2.28.1"
    
    show_requirements : bool, default=True
        Display version requirements from parent packages.
        Example: "[required: >=2.0]"
    
    show_status : bool, default=True
        Display installation status for packages.
        Example: "[not_installed]", "[error]"
    
    show_extras : bool, default=False
        Display package extras information.
        Example: "[extras: security,performance]"
    
    show_markers : bool, default=False
        Display environment markers.
        Example: "[marker: platform_system == 'Linux']"
    
    colorize : bool, default=False
        Use ANSI color codes for terminal output. Colors help distinguish
        different types of information (package names in green, versions in
        cyan, errors in red, etc.).
    
    compress_duplicates : bool, default=True
        Compress duplicate dependency chains to reduce output clutter.
        When True, identical subtrees are shown only once.
    
    Attributes
    ----------
    tree_chars : Dict[str, str]
        Character set used for tree drawing. Depends on use_unicode.
    colors : Dict[str, str]
        ANSI color codes for different element types. Used when colorize=True.
    
    Examples
    --------
    >>> # Default style with Unicode and colors
    >>> style = TreeStyle(use_unicode=True, colorize=True)
    >>> 
    >>> # Compact ASCII style for log files
    >>> style = TreeStyle(use_unicode=False, indent_size=1, show_versions=False)
    >>> 
    >>> # Minimal style (no extra info)
    >>> style = TreeStyle(show_versions=False, show_requirements=False, show_status=False)
    """
    
    # Core styling options
    use_unicode: bool = True
    indent_size: int = 2
    show_versions: bool = True
    show_requirements: bool = True
    show_status: bool = True
    show_extras: bool = False
    show_markers: bool = False
    colorize: bool = False
    compress_duplicates: bool = True
    
    def __post_init__(self):
        """Initialize tree characters and colors after dataclass initialization."""
        self._setup_tree_chars()
        self._setup_colors()
    
    def _setup_tree_chars(self):
        """
        Configure tree drawing characters based on Unicode preference.
        
        Unicode characters (default) provide beautiful, professional-looking
        trees with smooth lines. ASCII characters are more compatible with
        older terminals and when output is saved to text files.
        """
        if self.use_unicode:
            self.tree_chars = {
                'branch_mid': '├── ',
                'branch_last': '└── ',
                'indent_mid': '│   ',
                'indent_last': '    ',
                'vertical': '│',
                'horizontal': '─',
                'corner': '└',
                'tee': '├'
            }
        else:
            self.tree_chars = {
                'branch_mid': '|-- ',
                'branch_last': '`-- ',
                'indent_mid': '|   ',
                'indent_last': '    ',
                'vertical': '|',
                'horizontal': '-',
                'corner': '`',
                'tee': '|'
            }
    
    def _setup_colors(self):
        """
        Configure ANSI color codes for different element types.
        
        Uses colorama on Windows for better compatibility, or raw ANSI codes
        on Unix-like systems. Colors are only applied when colorize=True.
        """
        if COLORAMA_AVAILABLE and self.colorize:
            # Use colorama for cross-platform color support on Windows
            self.colors = {
                'reset': Style.RESET_ALL,
                'package': Fore.GREEN,
                'version': Fore.CYAN,
                'requirement': Fore.BLUE,
                'error': Fore.RED + Style.BRIGHT,
                'warning': Fore.YELLOW,
                'status': Fore.MAGENTA,
                'info': Fore.CYAN,
                'extra': Fore.MAGENTA,
                'marker': Style.DIM,
                'shared': Fore.YELLOW,
                'cycle': Fore.RED + Style.BRIGHT
            }
        elif self.colorize:
            # Fallback to standard ANSI codes (Unix/Linux/Mac)
            self.colors = {
                'reset': '\033[0m',
                'package': '\033[92m',
                'version': '\033[94m',
                'requirement': '\033[96m',
                'error': '\033[91m',
                'warning': '\033[93m',
                'status': '\033[95m',
                'info': '\033[96m',
                'extra': '\033[95m',
                'marker': '\033[2m',
                'shared': '\033[93m',
                'cycle': '\033[91m'
            }
        else:
            # No colors - empty strings
            self.colors = {k: '' for k in ['reset', 'package', 'version', 'requirement',
                                            'error', 'warning', 'status', 'info',
                                            'extra', 'marker', 'shared', 'cycle']}
    
    def get_branch_char(self, is_last: bool) -> str:
        """
        Get the branch character(s) for a tree line.
        
        Parameters
        ----------
        is_last : bool
            Whether this is the last item in the current list.
        
        Returns
        -------
        str
            Branch characters (e.g., "└── " for last, "├── " for middle).
        
        Examples
        --------
        >>> style = TreeStyle()
        >>> style.get_branch_char(True)
        '└── '
        >>> style.get_branch_char(False)
        '├── '
        """
        return self.tree_chars['branch_last'] if is_last else self.tree_chars['branch_mid']
    
    def get_indent_char(self, is_last_parent: bool) -> str:
        """
        Get the indentation character(s) for continuing a tree line.
        
        Parameters
        ----------
        is_last_parent : bool
            Whether the parent of this line is the last in its list.
        
        Returns
        -------
        str
            Indentation characters (e.g., "    " for last parent, "│   " otherwise).
        
        Examples
        --------
        >>> style = TreeStyle()
        >>> style.get_indent_char(True)
        '    '
        >>> style.get_indent_char(False)
        '│   '
        """
        return self.tree_chars['indent_last'] if is_last_parent else self.tree_chars['indent_mid']
    
    def colorize_text(self, text: str, color_name: str) -> str:
        """
        Apply ANSI color to text if colorization is enabled.
        
        Parameters
        ----------
        text : str
            The text to colorize.
        color_name : str
            Name of the color from self.colors (e.g., 'package', 'version').
        
        Returns
        -------
        str
            Colorized text if colorize=True and colors are defined,
            otherwise the original text unchanged.
        
        Examples
        --------
        >>> style = TreeStyle(colorize=True)
        >>> style.colorize_text("requests", "package")
        '\\033[92mrequests\\033[0m'
        """
        if not self.colorize:
            return text
        color = self.colors.get(color_name, '')
        reset = self.colors.get('reset', '')
        return f"{color}{text}{reset}"
    
    def get_status_color(self, status: str) -> str:
        """
        Get the appropriate color name for a status string.
        
        Parameters
        ----------
        status : str
            Status value ('installed', 'not_installed', 'error', etc.)
        
        Returns
        -------
        str
            Color name to use for this status.
        """
        status_colors = {
            'installed': 'package',
            'not_installed': 'warning',
            'error': 'error',
            'cycle_detected': 'cycle',
            'shared': 'shared',
            'merged': 'info',
            'collapsed': 'info'
        }
        return status_colors.get(status, 'status')


# =============================================================================
# MAIN DEPENDENCY TREE PRINTER CLASS
# =============================================================================

class DependencyTreePrinter:
    """
    Advanced printer class for visualizing dependency trees with deduplication.
    
    This class provides comprehensive capabilities for printing dependency
    trees to the terminal with beautiful formatting, configurable styling,
    and advanced deduplication of shared dependencies.
    
    The printer supports five duplicate handling strategies:
    - SHOW_ALL: Display every occurrence (no deduplication)
    - DEDUPLICATE: Show each package once per depth level
    - MERGE: Merge duplicate branches with "[see above]" indicators
    - MARK_SHARED: Mark shared dependencies with "[shared]" tags
    - COLLAPSE: Collapse duplicates with reference counts like "[x5]"
    
    Parameters
    ----------
    style : TreeStyle, optional
        Visual styling configuration. Creates a default style if not provided.
    
    max_depth : int, optional
        Maximum depth to print. Limits how deep the tree traversal goes.
        Use None for unlimited depth.
    
    pattern_filter : Pattern, optional
        Regex pattern to filter displayed packages. Only packages matching
        the pattern are shown in the output.
    
    skip_optional : bool, default=False
        Exclude optional dependencies from the printed tree.
    
    parallel_processing : int, default=1
        Number of parallel threads for processing. Higher values improve
        performance for large trees at the cost of memory.
    
    cache_results : bool, default=True
        Cache processed results for performance improvement on repeated prints.
    
    deduplicate_shared : bool, default=False
        Enable deduplication of shared dependencies. When True, applies the
        duplicate_handling strategy to reduce output clutter.
    
    duplicate_handling : Union[str, DuplicateHandling], default="deduplicate"
        Strategy for handling duplicate dependencies. Can be a string
        ('show_all', 'deduplicate', 'merge', 'mark_shared', 'collapse')
        or a DuplicateHandling enum value.
    
    Attributes
    ----------
    style : TreeStyle
        Visual styling configuration.
    max_depth : int
        Maximum printing depth.
    pattern_filter : Pattern
        Package name filter pattern.
    skip_optional : bool
        Skip optional dependencies flag.
    parallel_processing : int
        Number of parallel threads.
    cache_results : bool
        Cache results flag.
    deduplicate_shared : bool
        Deduplication enabled flag.
    duplicate_handling : DuplicateHandling
        Duplicate handling strategy enum.
    _cache : Dict[str, TreeNode]
        Result cache for performance.
    _seen_global : Set[str]
        Global set for tracking seen packages during deduplication.
    _shared_refs : Dict[str, int]
        Reference counting for COLLAPSE strategy.
    _stats : Dict[str, Any]
        Performance statistics.
    
    Examples
    --------
    >>> # Basic printer
    >>> printer = DependencyTreePrinter(max_depth=2)
    >>> printer.print_tree("requests")
    
    >>> # With deduplication using string
    >>> printer = DependencyTreePrinter(
    ...     max_depth=3,
    ...     deduplicate_shared=True,
    ...     duplicate_handling="merge"
    ... )
    >>> printer.print_tree("pyputil")
    
    >>> # With deduplication using enum
    >>> from pyputil.tree.printer import DuplicateHandling
    >>> printer = DependencyTreePrinter(
    ...     deduplicate_shared=True,
    ...     duplicate_handling=DuplicateHandling.COLLAPSE
    ... )
    >>> printer.print_tree("tensorflow")
    
    >>> # Custom styling with colors
    >>> style = TreeStyle(colorize=True, show_extras=True, show_markers=True)
    >>> printer = DependencyTreePrinter(style=style, max_depth=4)
    >>> printer.print_tree("pandas")
    """
    
    def __init__(self,
                 style: Optional[TreeStyle] = None,
                 max_depth: Optional[int] = None,
                 pattern_filter: Optional[Pattern] = None,
                 skip_optional: bool = False,
                 parallel_processing: int = 1,
                 cache_results: bool = True,
                 deduplicate_shared: bool = False,
                 duplicate_handling: Union[str, DuplicateHandling] = "deduplicate"):
        
        # Core configuration
        self.style = style or TreeStyle()
        """Visual styling configuration."""
        
        self.max_depth = max_depth
        """Maximum depth to print (None = unlimited)."""
        
        self.pattern_filter = pattern_filter
        """Regex pattern for filtering package names."""
        
        self.skip_optional = skip_optional
        """Whether to skip optional dependencies."""
        
        self.parallel_processing = max(1, parallel_processing)
        """Number of parallel threads for processing."""
        
        self.cache_results = cache_results
        """Whether to cache results for performance."""
        
        # Deduplication configuration
        self.deduplicate_shared = deduplicate_shared
        """Enable deduplication of shared dependencies."""
        
        # Convert string to enum if needed
        if isinstance(duplicate_handling, str):
            handling_map = {
                'show_all': DuplicateHandling.SHOW_ALL,
                'deduplicate': DuplicateHandling.DEDUPLICATE,
                'merge': DuplicateHandling.MERGE,
                'mark_shared': DuplicateHandling.MARK_SHARED,
                'collapse': DuplicateHandling.COLLAPSE
            }
            self.duplicate_handling = handling_map.get(duplicate_handling, DuplicateHandling.DEDUPLICATE)
        else:
            self.duplicate_handling = duplicate_handling
        """Duplicate handling strategy."""
        
        # Internal state
        self._cache: Dict[str, TreeNode] = {}
        """Cache of processed tree nodes."""
        
        self._seen_global: Set[str] = set()
        """Global tracking for deduplication - stores normalized package names."""
        
        self._shared_refs: Dict[str, int] = {}
        """Reference counting for COLLAPSE strategy - maps package name to count."""
        
        self._stats = {
            'trees_printed': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'total_nodes': 0,
            'deduplications_saved': 0,
            'cycles_detected': 0
        }
        """Performance statistics."""
        
        # Log initialization
        logger.info(
            f"DependencyTreePrinter initialized: max_depth={max_depth}, "
            f"deduplicate={deduplicate_shared}, strategy={self.duplicate_handling.value}"
        )
    
    def print_tree(self, package_name: str, **kwargs) -> bool:
        """
        Print a dependency tree for the specified package.
        
        This is the main entry point for printing dependency trees. It builds
        the tree structure and prints it to the terminal with the configured
        styling and deduplication settings.
        
        Parameters
        ----------
        package_name : str
            Name of the root package to analyze and print.
        **kwargs
            Additional arguments passed to the internal tree builder.
        
        Returns
        -------
        bool
            True if tree was printed successfully, False otherwise.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> printer.print_tree("requests")
        requests==2.28.1
        ├── certifi>=2017.4.17
        ├── charset-normalizer~=2.0.0
        └── urllib3<1.27,>=1.21.1
        
        >>> # With depth limit
        >>> printer.print_tree("pandas", max_depth=2)
        
        >>> # Override style temporarily
        >>> printer.print_tree("numpy", show_versions=False, colorize=True)
        """
        # Override settings for this call if provided
        original_settings = {}
        for key, value in kwargs.items():
            if hasattr(self.style, key):
                original_settings[key] = getattr(self.style, key)
                setattr(self.style, key, value)
            elif key == 'max_depth':
                original_settings['max_depth'] = self.max_depth
                self.max_depth = value
        
        try:
            # Reset global tracking for this tree
            self._seen_global.clear()
            self._shared_refs.clear()
            
            # Build the tree
            root = self._build_tree(package_name)
            
            if not root:
                error_msg = f"Failed to build tree for {package_name}"
                print(self.style.colorize_text(error_msg, 'error'))
                return False
            
            # Print the tree
            self._print_node(root, 0, True)
            
            self._stats['trees_printed'] += 1
            return True
            
        except Exception as e:
            logger.error(f"Error printing tree for {package_name}: {e}")
            if kwargs.get('verbose', False):
                import traceback
                traceback.print_exc()
            return False
        finally:
            # Restore original settings
            for key, value in original_settings.items():
                if hasattr(self.style, key):
                    setattr(self.style, key, value)
                elif key == 'max_depth':
                    self.max_depth = value
    
    def _build_tree(self, package_name: str, depth: int = 0,
                    seen: Optional[Set[str]] = None,
                    requirement: str = "",
                    marker: str = "",
                    extras: Optional[List[str]] = None) -> Optional[TreeNode]:
        """
        Build a structured tree representation with deduplication support.
        
        This method recursively builds the dependency tree while applying
        the configured deduplication strategy. It handles cycle detection,
        filtering, and special node types for deduplication.
        
        Parameters
        ----------
        package_name : str
            Package name to process.
        depth : int, default=0
            Current depth in the tree.
        seen : Set[str], optional
            Set of visited packages for cycle detection.
        requirement : str, default=""
            Version requirement from parent.
        marker : str, default=""
            Environment marker from parent.
        extras : List[str], optional
            Extras from parent.
        
        Returns
        -------
        Optional[TreeNode]
            Tree node or None if package should be skipped.
        """
        # Check depth limit
        if self.max_depth is not None and depth > self.max_depth:
            return None
        
        # Check pattern filter
        if self.pattern_filter and not self.pattern_filter.search(package_name):
            return None
        
        # Initialize seen set for cycle detection
        if seen is None:
            seen = set()
        
        normalized_name = normalize_package_name(package_name)
        
        # ================================================================
        # CYCLE DETECTION
        # ================================================================
        # Check if we've seen this package at this depth (cycle detection)
        cycle_key = f"{normalized_name}:{depth}"
        if cycle_key in seen:
            self._stats['cycles_detected'] += 1
            logger.debug(f"Cycle detected: {package_name} at depth {depth}")
            return TreeNode(
                name=package_name,
                version="",
                requirement=requirement,
                status="cycle_detected",
                depth=depth,
                metadata={'cycle': True}
            )
        
        seen.add(cycle_key)
        
        # ================================================================
        # DEDUPLICATION HANDLING
        # ================================================================
        # For non-root nodes, check if we should deduplicate
        if self.deduplicate_shared and depth > 0:
            # Check if we've seen this package before (globally)
            if normalized_name in self._seen_global:
                # Increment reference count for this package
                self._shared_refs[normalized_name] = self._shared_refs.get(normalized_name, 0) + 1
                self._stats['deduplications_saved'] += 1
                
                # Strategy: MERGE - return a reference node
                if self.duplicate_handling == DuplicateHandling.MERGE:
                    seen.remove(cycle_key)
                    return TreeNode(
                        name=package_name,
                        version="",
                        requirement=requirement,
                        status="merged",
                        depth=depth,
                        metadata={'reference': normalized_name, 'merged': True}
                    )
                
                # Strategy: COLLAPSE - return a collapsed node with count
                elif self.duplicate_handling == DuplicateHandling.COLLAPSE:
                    ref_count = self._shared_refs[normalized_name]
                    seen.remove(cycle_key)
                    return TreeNode(
                        name=package_name,
                        version="",
                        requirement=requirement,
                        status="collapsed",
                        depth=depth,
                        metadata={'reference_count': ref_count + 1, 'collapsed': True}
                    )
                
                # Strategy: MARK_SHARED - continue processing but will mark later
                # Strategy: DEDUPLICATE - continue, but skip at same depth
                # Strategy: SHOW_ALL - continue normally
                # For MARK_SHARED, we still need to process but will add a marker
            
            # Add to global seen set for future deduplication
            # For DEDUPLICATE, we add at the end to prevent same-depth duplicates
            if self.duplicate_handling != DuplicateHandling.DEDUPLICATE:
                self._seen_global.add(normalized_name)
        
        # ================================================================
        # PACKAGE METADATA RETRIEVAL
        # ================================================================
        try:
            # Get package distribution from cache
            dist = PackageCache().get_distribution(package_name)
            
            if dist is None:
                # Package not installed
                node = TreeNode(
                    name=package_name,
                    version="",
                    requirement=requirement,
                    status="not_installed",
                    depth=depth,
                    extras=extras or [],
                    marker=marker
                )
                self._stats['total_nodes'] += 1
                seen.remove(cycle_key)
                return node
            
            # Package installed - extract metadata
            name = dist.metadata["Name"]
            installed_version = dist.version
            
            # Get requirements list
            requires = dist.requires or []
            
            # ================================================================
            # PROCESS DEPENDENCIES
            # ================================================================
            # Filter and parse requirements
            requirements_to_process = self._filter_requirements(requires, depth)
            
            # Process dependencies (sequential or parallel)
            if self.parallel_processing > 1 and len(requirements_to_process) > 1:
                children = self._process_requirements_parallel(requirements_to_process, depth, seen)
            else:
                children = self._process_requirements_sequential(requirements_to_process, depth, seen)
            
            # Create node
            node = TreeNode(
                name=name,
                version=installed_version,
                requirement=requirement,
                status="installed",
                dependencies=children,
                extras=extras or [],
                marker=marker,
                depth=depth
            )
            
            # Add shared marker if needed (for MARK_SHARED strategy)
            if (self.deduplicate_shared and depth > 0 and 
                self.duplicate_handling == DuplicateHandling.MARK_SHARED and
                normalized_name in self._seen_global):
                node.status = "shared"
                node.metadata['shared'] = True
                node.metadata['reference_count'] = self._shared_refs.get(normalized_name, 0) + 1
            
            self._stats['total_nodes'] += 1
            
            # For DEDUPLICATE strategy, add to global seen after processing
            if self.deduplicate_shared and self.duplicate_handling == DuplicateHandling.DEDUPLICATE:
                self._seen_global.add(normalized_name)
            
            seen.remove(cycle_key)
            return node
            
        except Exception as e:
            logger.error(f"Error building tree for {package_name}: {e}")
            node = TreeNode(
                name=package_name,
                version="",
                requirement=requirement,
                status="error",
                depth=depth,
                metadata={'error': str(e)}
            )
            seen.remove(cycle_key)
            return node
    
    def _filter_requirements(self, requirements: List[str], depth: int) -> List[Tuple]:
        """
        Filter and parse requirements based on configuration.
        
        Parameters
        ----------
        requirements : List[str]
            Raw requirement strings from package metadata.
        depth : int
            Current depth (used for deduplication decisions).
        
        Returns
        -------
        List[Tuple]
            List of (child_name, req_spec, extras, marker) tuples.
        """
        filtered = []
        
        for req in requirements:
            child_name, req_spec, extras, marker = parse_requirement(req)
            if not child_name:
                continue
            
            # Filter optional dependencies
            if self.skip_optional and not should_include_requirement(
                req_spec, marker, skip_optional=True
            ):
                continue
            
            # For DEDUPLICATE strategy, check if we've already processed this
            # package at this depth level
            if (self.deduplicate_shared and 
                self.duplicate_handling == DuplicateHandling.DEDUPLICATE and
                normalize_package_name(child_name) in self._seen_global):
                continue
            
            filtered.append((child_name, req_spec, extras, marker))
        
        return filtered
    
    def _process_requirements_sequential(self, requirements: List[Tuple],
                                         depth: int,
                                         seen: Set[str]) -> List[TreeNode]:
        """
        Process requirements sequentially (no parallelism).
        
        Parameters
        ----------
        requirements : List[Tuple]
            List of (child_name, req_spec, extras, marker) tuples.
        depth : int
            Current depth in the tree.
        seen : Set[str]
            Set of visited packages for cycle detection.
        
        Returns
        -------
        List[TreeNode]
            List of child nodes.
        """
        children = []
        
        for child_name, req_spec, extras, marker in requirements:
            child_node = self._build_tree(
                child_name,
                depth + 1,
                seen.copy(),
                req_spec,
                marker,
                extras
            )
            if child_node:
                children.append(child_node)
        
        return children
    
    def _process_requirements_parallel(self, requirements: List[Tuple],
                                       depth: int,
                                       seen: Set[str]) -> List[TreeNode]:
        """
        Process requirements in parallel using thread pool.
        
        Parameters
        ----------
        requirements : List[Tuple]
            List of (child_name, req_spec, extras, marker) tuples.
        depth : int
            Current depth in the tree.
        seen : Set[str]
            Set of visited packages for cycle detection.
        
        Returns
        -------
        List[TreeNode]
            List of child nodes.
        """
        children = []
        
        with ThreadPoolExecutor(max_workers=self.parallel_processing) as executor:
            future_to_req = {}
            
            for child_name, req_spec, extras, marker in requirements:
                future = executor.submit(
                    self._build_tree,
                    child_name, depth + 1, seen.copy(),
                    req_spec, marker, extras
                )
                future_to_req[future] = child_name
            
            for future in as_completed(future_to_req):
                try:
                    child_node = future.result(timeout=30)
                    if child_node:
                        children.append(child_node)
                except Exception as e:
                    child_name = future_to_req[future]
                    logger.error(f"Error processing {child_name}: {e}")
                    # Add error node to maintain tree completeness
                    children.append(TreeNode(
                        name=child_name,
                        version="",
                        status="error",
                        depth=depth + 1,
                        metadata={'error': str(e)}
                    ))
        
        return children
    
    def _print_node(self, node: TreeNode, indent_level: int = 0,
                    is_last_sibling: bool = True, prefix: str = "") -> None:
        """
        Print a node and its children recursively with beautiful formatting.
        
        This method handles the actual printing of tree nodes, applying
        colors, indentation, and special formatting for deduplication markers.
        
        Parameters
        ----------
        node : TreeNode
            Tree node to print.
        indent_level : int, default=0
            Current indentation level.
        is_last_sibling : bool, default=True
            Whether this node is the last child of its parent.
        prefix : str, default=""
            Prefix string for continuing tree lines.
        """
        # Build the line with proper indentation
        indent = " " * (indent_level * self.style.indent_size)
        line = prefix + indent
        
        # Add branch character (skip for root)
        if indent_level > 0:
            branch = self.style.get_branch_char(is_last_sibling)
            line += branch
        
        # Package name with color
        line += self.style.colorize_text(node.name, 'package')
        
        # Version (if showing and available)
        if self.style.show_versions and node.version:
            line += self.style.colorize_text(f"=={node.version}", 'version')
        
        # Status with appropriate color
        if self.style.show_status and node.status != "installed":
            status_color = self.style.get_status_color(node.status)
            status_display = node.status.replace('_', ' ')
            
            # Special handling for merged/collapsed nodes
            if node.status == "merged":
                line += self.style.colorize_text(" [see above]", status_color)
            elif node.status == "collapsed":
                count = node.metadata.get('reference_count', 1)
                line += self.style.colorize_text(f" [x{count}]", status_color)
            elif node.status == "shared":
                count = node.metadata.get('reference_count', 1)
                line += self.style.colorize_text(f" [shared x{count}]", status_color)
            elif node.status == "cycle_detected":
                line += self.style.colorize_text(" [cycle detected]", status_color)
            else:
                line += self.style.colorize_text(f" [{status_display}]", status_color)
        
        # Requirement info from parent
        if self.style.show_requirements and node.requirement:
            line += self.style.colorize_text(f" [required: {node.requirement}]", 'requirement')
        
        # Extras information
        if self.style.show_extras and node.extras:
            extras_str = ','.join(node.extras)
            line += self.style.colorize_text(f" [{extras_str}]", 'extra')
        
        # Environment markers
        if self.style.show_markers and node.marker:
            line += self.style.colorize_text(f" [{node.marker}]", 'marker')
        
        # Print the line
        print(line)
        
        # Don't print children for merged or collapsed nodes
        if node.status in ('merged', 'collapsed'):
            return
        
        # Print children recursively
        dependencies = node.dependencies
        for i, child in enumerate(dependencies):
            is_last = (i == len(dependencies) - 1)
            
            # Determine prefix for continuation lines
            if indent_level > 0:
                child_prefix = prefix + self.style.get_indent_char(is_last_sibling)
            else:
                child_prefix = ""
            
            self._print_node(child, indent_level + 1, is_last, child_prefix)

    
    def _format_as_text(self, node: TreeNode, **kwargs) -> str:
        """
        Format tree as text with Unicode/ASCII box-drawing characters.
        
        This method captures the output of _print_node() and returns it as
        a string instead of printing to stdout. This is useful for saving
        the tree to files or for API responses.
        
        Parameters
        ----------
        node : TreeNode
            Root node of the tree to format.
        **kwargs
            Additional formatting options (passed to _print_node via settings).
        
        Returns
        -------
        str
            Formatted tree as a string with box-drawing characters.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> tree = printer._build_tree("requests")
        >>> text_output = printer._format_as_text(tree)
        >>> print(text_output)
        requests==2.28.1
        ├── certifi>=2017.4.17
        ├── charset-normalizer~=2.0.0
        └── urllib3<1.27,>=1.21.1
        """
        import io
        from contextlib import redirect_stdout
        
        # Save original stdout to restore later
        original_stdout = sys.stdout
        buffer = io.StringIO()
        
        try:
            # Redirect stdout to buffer
            sys.stdout = buffer
            # Print the node using the existing _print_node method
            self._print_node(node, 0, True)
            # Get the captured output
            return buffer.getvalue()
        finally:
            # Always restore stdout, even if an error occurs
            sys.stdout = original_stdout
    
    def _format_as_plain(self, node: TreeNode, **kwargs) -> str:
        """
        Format tree as plain text (simple indentation, no tree characters).
        
        This produces a clean, simple representation using only spaces for
        indentation. No Unicode/ASCII box-drawing characters are used,
        making it ideal for plain text files or environments that don't
        support special characters.
        
        Parameters
        ----------
        node : TreeNode
            Root node of the tree to format.
        **kwargs
            Additional formatting options (unused, kept for API consistency).
        
        Returns
        -------
        str
            Formatted tree as plain text with space-based indentation.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> tree = printer._build_tree("requests")
        >>> plain_output = printer._format_as_plain(tree)
        >>> print(plain_output)
        requests==2.28.1
          certifi>=2017.4.17
          charset-normalizer~=2.0.0
          urllib3<1.27,>=1.21.1
        """
        lines = []
        
        def format_node(n: TreeNode, depth: int = 0):
            # Create indentation: 2 spaces per level
            indent = "  " * depth
            
            # Build the line
            line = f"{indent}{n.name}"
            if n.version:
                line += f"=={n.version}"
            if n.status != "installed":
                line += f" [{n.status}]"
            lines.append(line)
            
            # Recursively format children
            for child in n.dependencies:
                format_node(child, depth + 1)
        
        format_node(node)
        return "\n".join(lines)
    
    def _format_as_markdown(self, node: TreeNode, **kwargs) -> str:
        """
        Format tree as Markdown document.
        
        Creates a complete Markdown document with:
        - Title header
        - Code block containing the plain text tree
        - Statistics section with key metrics
        
        This format is ideal for documentation, README files, or GitHub.
        
        Parameters
        ----------
        node : TreeNode
            Root node of the tree to format.
        **kwargs
            Additional options (title, etc.)
        
        Returns
        -------
        str
            Complete Markdown document as a string.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> tree = printer._build_tree("requests")
        >>> markdown = printer._format_as_markdown(tree)
        >>> with open("dependencies.md", "w") as f:
        ...     f.write(markdown)
        """
        title = kwargs.get('title', f"Dependency Tree: {node.name}")
        
        lines = [
            f"# {title}",
            "",
            "## Tree Structure",
            "",
            "```",
            self._format_as_plain(node),
            "```",
            "",
            "## Statistics",
            "",
            f"- **Total packages:** {node.get_size()}",
            f"- **Maximum depth:** {node.get_max_depth()}",
            f"- **Direct dependencies:** {len(node.dependencies)}",
            f"- **Leaf packages:** {node.get_leaf_count()}"
        ]
        return "\n".join(lines)
    
    def _format_as_json(self, node: TreeNode, **kwargs) -> str:
        """
        Format tree as JSON string.
        
        Converts the entire tree structure to a JSON string, preserving all
        metadata, dependencies, and relationships. Perfect for API responses,
        data interchange, or programmatic processing.
        
        Parameters
        ----------
        node : TreeNode
            Root node of the tree to format.
        **kwargs
            Additional JSON options:
            - indent: Number of spaces for indentation (default: 2)
            - sort_keys: Whether to sort dictionary keys (default: False)
        
        Returns
        -------
        str
            JSON string representation of the tree.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> tree = printer._build_tree("requests")
        >>> json_output = printer._format_as_json(tree, indent=4)
        >>> print(json_output[:200])
        {
            "name": "requests",
            "version": "2.28.1",
            ...
        }
        """
        import json
        indent = kwargs.get('indent', 2)
        sort_keys = kwargs.get('sort_keys', False)
        
        # Use TreeNode's to_dict method for serialization
        tree_dict = node.to_dict()
        return json.dumps(tree_dict, indent=indent, sort_keys=sort_keys, default=str)
    
    def _format_as_dict(self, node: TreeNode, **kwargs) -> Dict:
        """
        Format tree as Python dictionary.
        
        Returns the tree as a native Python dictionary, preserving all
        structure and metadata. Most efficient for programmatic use within
        Python applications.
        
        Parameters
        ----------
        node : TreeNode
            Root node of the tree to format.
        **kwargs
            Additional options (unused, kept for API consistency).
        
        Returns
        -------
        Dict
            Dictionary representation of the tree.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> tree = printer._build_tree("requests")
        >>> tree_dict = printer._format_as_dict(tree)
        >>> print(tree_dict['name'])
        'requests'
        >>> print(len(tree_dict['dependencies']))
        3
        """
        return node.to_dict()
    
    def _format_as_html(self, node: TreeNode, **kwargs) -> str:
        """
        Format tree as interactive HTML document.
        
        Creates a standalone HTML file with an interactive, collapsible tree
        visualization. Features include:
        - Click to expand/collapse branches
        - Package statistics display
        - Responsive design
        - Dark/light theme support
        - Visual status indicators
        
        Parameters
        ----------
        node : TreeNode
            Root node of the tree to format.
        **kwargs
            Additional options:
            - title: Page title (default: "Dependency Tree: {name}")
            - theme: 'light' or 'dark' (default: 'light')
        
        Returns
        -------
        str
            Complete HTML document as a string.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> tree = printer._build_tree("pandas")
        >>> html = printer._format_as_html(tree, theme="dark")
        >>> with open("pandas_tree.html", "w") as f:
        ...     f.write(html)
        """
        import json
        title = kwargs.get('title', f"Dependency Tree: {node.name}")
        theme = kwargs.get('theme', 'light')
        
        # Colors for light and dark themes
        if theme == 'dark':
            bg_color = '#1e1e1e'
            container_bg = '#2d2d2d'
            text_color = '#e0e0e0'
            border_color = '#404040'
            hover_bg = '#404040'
            package_color = '#6fbf73'
            version_color = '#6fbf73'
            stats_bg = '#404040'
        else:
            bg_color = '#f5f5f5'
            container_bg = '#ffffff'
            text_color = '#333333'
            border_color = '#ddd'
            hover_bg = '#f0f0f0'
            package_color = '#2c3e50'
            version_color = '#27ae60'
            stats_bg = '#ecf0f1'
        
        tree_json = json.dumps(node.to_dict(), indent=2, default=str)
        
        html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', Arial, sans-serif;
            background-color: {bg_color};
            color: {text_color};
            padding: 20px;
            transition: all 0.3s ease;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background-color: {container_bg};
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 30px;
        }}
        
        .header h1 {{
            font-size: 1.8em;
            margin-bottom: 8px;
        }}
        
        .header p {{
            opacity: 0.9;
            font-size: 0.95em;
        }}
        
        .controls {{
            padding: 15px 30px;
            border-bottom: 1px solid {border_color};
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            align-items: center;
        }}
        
        button {{
            padding: 8px 16px;
            background-color: #667eea;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            transition: background-color 0.2s;
        }}
        
        button:hover {{
            background-color: #5a67d8;
        }}
        
        .stats {{
            padding: 15px 30px;
            background-color: {stats_bg};
            border-bottom: 1px solid {border_color};
            display: flex;
            gap: 30px;
            flex-wrap: wrap;
            font-size: 14px;
        }}
        
        .stat-item {{
            display: flex;
            align-items: baseline;
            gap: 8px;
        }}
        
        .stat-label {{
            font-weight: 600;
            opacity: 0.7;
        }}
        
        .stat-value {{
            font-size: 1.2em;
            font-weight: bold;
            color: #667eea;
        }}
        
        .tree-container {{
            padding: 20px 30px;
            overflow-x: auto;
            max-height: 70vh;
            overflow-y: auto;
        }}
        
        .tree-node {{
            margin-left: 25px;
            padding-left: 20px;
            border-left: 2px solid {border_color};
            position: relative;
        }}
        
        .tree-root {{
            margin-left: 0;
            border-left: none;
        }}
        
        .tree-item {{
            padding: 8px 12px;
            margin: 4px 0;
            cursor: pointer;
            border-radius: 6px;
            transition: background-color 0.2s;
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        
        .tree-item:hover {{
            background-color: {hover_bg};
        }}
        
        .toggle {{
            cursor: pointer;
            user-select: none;
            font-size: 12px;
            width: 20px;
            text-align: center;
            transition: transform 0.2s;
            font-weight: bold;
        }}
        
        .toggle.rotated {{
            transform: rotate(90deg);
        }}
        
        .package-name {{
            font-weight: 600;
            font-size: 1em;
            color: {package_color};
        }}
        
        .package-version {{
            color: {version_color};
            font-size: 0.85em;
            font-family: 'Courier New', monospace;
        }}
        
        .package-status {{
            font-size: 0.8em;
            padding: 2px 8px;
            border-radius: 12px;
        }}
        
        .status-not_installed {{
            background-color: #f0f0f0;
            color: #856404;
        }}
        
        .status-error {{
            background-color: #f8d7da;
            color: #721c24;
        }}
        
        .status-cycle_detected {{
            background-color: #fff3cd;
            color: #856404;
        }}
        
        .status-shared {{
            background-color: #d1ecf1;
            color: #0c5460;
        }}
        
        .children {{
            transition: all 0.3s ease;
        }}
        
        .children.collapsed {{
            display: none;
        }}
        
        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}
            
            .controls {{
                flex-direction: column;
                align-items: stretch;
            }}
            
            .stats {{
                flex-direction: column;
                gap: 10px;
            }}
            
            .tree-item {{
                flex-wrap: wrap;
            }}
        }}
        
        ::-webkit-scrollbar {{
            width: 8px;
            height: 8px;
        }}
        
        ::-webkit-scrollbar-track {{
            background: {border_color};
            border-radius: 4px;
        }}
        
        ::-webkit-scrollbar-thumb {{
            background: #667eea;
            border-radius: 4px;
        }}
        
        ::-webkit-scrollbar-thumb:hover {{
            background: #5a67d8;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{title}</h1>
            <p>Interactive dependency tree visualization - click on nodes to expand/collapse</p>
        </div>
        
        <div class="controls">
            <button onclick="expandAll()">Expand All</button>
            <button onclick="collapseAll()">Collapse All</button>
            <button onclick="resetView()">Reset View</button>
        </div>
        
        <div class="stats">
            <div class="stat-item">
                <span class="stat-label">📦 Total Packages:</span>
                <span class="stat-value" id="totalPackages">0</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">📏 Tree Depth:</span>
                <span class="stat-value" id="treeDepth">0</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">🔗 Direct Dependencies:</span>
                <span class="stat-value" id="directDeps">0</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">🌿 Leaf Packages:</span>
                <span class="stat-value" id="leafCount">0</span>
            </div>
        </div>
        
        <div class="tree-container">
            <div id="tree"></div>
        </div>
    </div>
    
    <script>
        const treeData = {tree_json};
        
        // Calculate statistics
        function calculateStats(node) {{
            let total = 1;
            let leafCount = (node.dependencies && node.dependencies.length === 0) ? 1 : 0;
            
            if (node.dependencies) {{
                for (const child of node.dependencies) {{
                    const childStats = calculateStats(child);
                    total += childStats.total;
                    leafCount += childStats.leafCount;
                }}
            }}
            
            return {{ total, leafCount }};
        }}
        
        function findMaxDepth(node, currentDepth = 0) {{
            if (!node.dependencies || node.dependencies.length === 0) {{
                return currentDepth;
            }}
            
            let maxChildDepth = currentDepth;
            for (const child of node.dependencies) {{
                const childDepth = findMaxDepth(child, currentDepth + 1);
                maxChildDepth = Math.max(maxChildDepth, childDepth);
            }}
            return maxChildDepth;
        }}
        
        const stats = calculateStats(treeData);
        const maxDepth = findMaxDepth(treeData);
        const directDeps = treeData.dependencies ? treeData.dependencies.length : 0;
        
        document.getElementById('totalPackages').textContent = stats.total;
        document.getElementById('treeDepth').textContent = maxDepth;
        document.getElementById('directDeps').textContent = directDeps;
        document.getElementById('leafCount').textContent = stats.leafCount;
        
        function renderNode(node, container, isRoot = false) {{
            const itemDiv = document.createElement('div');
            itemDiv.className = 'tree-item';
            
            const toggle = document.createElement('span');
            toggle.className = 'toggle';
            
            const nameSpan = document.createElement('span');
            nameSpan.className = 'package-name';
            nameSpan.textContent = node.name;
            
            const versionSpan = document.createElement('span');
            versionSpan.className = 'package-version';
            versionSpan.textContent = node.version ? `(${{node.version}})` : '';
            
            itemDiv.appendChild(toggle);
            itemDiv.appendChild(nameSpan);
            itemDiv.appendChild(versionSpan);
            
            if (node.status && node.status !== 'installed') {{
                const statusSpan = document.createElement('span');
                statusSpan.className = `package-status status-${{node.status}}`;
                let statusText = node.status.replace(/_/g, ' ');
                if (node.status === 'shared' && node.metadata && node.metadata.reference_count) {{
                    statusText = `shared x${{node.metadata.reference_count}}`;
                }} else if (node.status === 'collapsed' && node.metadata && node.metadata.reference_count) {{
                    statusText = `x${{node.metadata.reference_count}}`;
                }}
                statusSpan.textContent = statusText;
                itemDiv.appendChild(statusSpan);
            }}
            
            container.appendChild(itemDiv);
            
            if (node.dependencies && node.dependencies.length > 0) {{
                toggle.textContent = '▼';
                const childrenDiv = document.createElement('div');
                childrenDiv.className = 'children';
                
                toggle.onclick = (e) => {{
                    e.stopPropagation();
                    if (childrenDiv.style.display === 'none') {{
                        childrenDiv.style.display = 'block';
                        toggle.textContent = '▼';
                    }} else {{
                        childrenDiv.style.display = 'none';
                        toggle.textContent = '▶';
                    }}
                }};
                
                node.dependencies.forEach(child => {{
                    const childContainer = document.createElement('div');
                    childContainer.className = 'tree-node';
                    renderNode(child, childContainer);
                    childrenDiv.appendChild(childContainer);
                }});
                
                container.appendChild(childrenDiv);
            }} else {{
                toggle.style.opacity = '0.5';
                toggle.textContent = '•';
            }}
        }}
        
        function expandAll() {{
            document.querySelectorAll('.children').forEach(el => {{
                el.style.display = 'block';
                const toggle = el.parentElement?.querySelector('.toggle');
                if (toggle && toggle.textContent === '▶') toggle.textContent = '▼';
            }});
        }}
        
        function collapseAll() {{
            document.querySelectorAll('.children').forEach(el => {{
                el.style.display = 'none';
                const toggle = el.parentElement?.querySelector('.toggle');
                if (toggle && toggle.textContent === '▼') toggle.textContent = '▶';
            }});
        }}
        
        function resetView() {{
            const treeContainer = document.getElementById('tree');
            const scrollContainer = document.querySelector('.tree-container');
            if (scrollContainer) {{
                scrollContainer.scrollTop = 0;
                scrollContainer.scrollLeft = 0;
            }}
            collapseAll();
            setTimeout(expandAll, 100);
        }}
        
        const treeContainer = document.getElementById('tree');
        const rootDiv = document.createElement('div');
        rootDiv.className = 'tree-root';
        renderNode(treeData, rootDiv, true);
        treeContainer.appendChild(rootDiv);
    </script>
</body>
</html>
"""
        return html_template
    
    def _format_as_dot(self, node: TreeNode, **kwargs) -> str:
        """
        Format tree as Graphviz DOT language.
        
        Produces a DOT file that can be rendered using Graphviz tools:
        - dot -Tpng tree.dot -o tree.png (PNG image)
        - dot -Tsvg tree.dot -o tree.svg (SVG vector graphic)
        - dot -Tpdf tree.dot -o tree.pdf (PDF document)
        
        The generated graph uses:
        - LR (left-to-right) layout
        - Box-shaped nodes
        - Color-coded nodes based on status
        
        Parameters
        ----------
        node : TreeNode
            Root node of the tree to format.
        **kwargs
            Additional options:
            - rankdir: Graph direction ('LR', 'TB', 'BT', 'RL') default: 'LR'
            - node_shape: Node shape ('box', 'ellipse', 'circle') default: 'box'
        
        Returns
        -------
        str
            Graphviz DOT format string.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> tree = printer._build_tree("requests")
        >>> dot = printer._format_as_dot(tree)
        >>> with open("tree.dot", "w") as f:
        ...     f.write(dot)
        >>> # Then run: dot -Tpng tree.dot -o tree.png
        """
        rankdir = kwargs.get('rankdir', 'LR')
        node_shape = kwargs.get('node_shape', 'box')
        
        lines = [
            "digraph DependencyTree {",
            f"    rankdir={rankdir};",
            f"    node [shape={node_shape}];",
            "",
            "    // Node definitions"
        ]
        
        node_ids = {}
        node_counter = 0
        
        # Color mapping for different statuses
        status_colors = {
            'installed': 'lightgreen',
            'not_installed': 'lightgray',
            'error': 'lightcoral',
            'cycle_detected': 'lightyellow',
            'shared': 'lightblue',
            'merged': 'lightgray',
            'collapsed': 'lightgray'
        }
        
        def add_node(n: TreeNode) -> str:
            nonlocal node_counter
            if n.name not in node_ids:
                node_id = f"n{node_counter}"
                node_counter += 1
                node_ids[n.name] = node_id
                
                # Build node label with line breaks
                label_parts = [n.name]
                if n.version:
                    label_parts.append(n.version)
                if n.status != 'installed':
                    status_display = n.status.replace('_', ' ')
                    label_parts.append(f"[{status_display}]")
                
                label = "\\n".join(label_parts)
                color = status_colors.get(n.status, 'white')
                
                lines.append(f'    {node_id} [label="{label}", style="filled", fillcolor="{color}"];')
            return node_ids[n.name]
        
        def add_edges(n: TreeNode, parent_id: Optional[str] = None):
            node_id = add_node(n)
            if parent_id:
                lines.append(f"    {parent_id} -> {node_id};")
            for child in n.dependencies:
                add_edges(child, node_id)
        
        lines.append("")
        add_edges(node)
        lines.append("}")
        
        return "\n".join(lines)
    
    def _format_as_mermaid(self, node: TreeNode, **kwargs) -> str:
        """
        Format tree as Mermaid flowchart syntax.
        
        Produces a diagram that can be rendered by Mermaid:
        - GitHub: Mermaid diagrams render natively in Markdown
        - Online: https://mermaid.live/
        - Documentation: https://mermaid.js.org/
        
        The generated flowchart uses:
        - LR (left-to-right) direction
        - Styled nodes based on status
        - Clickable nodes (in supported environments)
        
        Parameters
        ----------
        node : TreeNode
            Root node of the tree to format.
        **kwargs
            Additional options:
            - direction: Flowchart direction ('LR', 'RL', 'TB', 'BT') default: 'LR'
            - theme: Mermaid theme ('default', 'dark', 'neutral') default: 'default'
        
        Returns
        -------
        str
            Mermaid flowchart syntax string.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> tree = printer._build_tree("requests")
        >>> mermaid = printer._format_as_mermaid(tree)
        >>> # Embed in Markdown:
        >>> # ```mermaid
        >>> # graph LR
        >>> #     n0["requests (2.28.1)"]
        >>> #     n1["certifi (2022.12.7)"]
        >>> #     n0 --> n1
        >>> # ```
        """
        direction = kwargs.get('direction', 'LR')
        theme = kwargs.get('theme', 'default')
        
        lines = []
        
        # Add theme directive if not default
        if theme != 'default':
            lines.append(f"%%{{init: {{'theme': '{theme}'}}}}%%")
        
        lines.append(f"graph {direction}")
        
        node_ids = {}
        node_counter = 0
        
        # CSS classes for different statuses
        lines.append("    %% Define node styles")
        lines.append("    classDef installed fill:#90EE90,stroke:#228B22,stroke-width:2px;")
        lines.append("    classDef not_installed fill:#D3D3D3,stroke:#808080,stroke-width:1px;")
        lines.append("    classDef error fill:#F08080,stroke:#FF0000,stroke-width:2px;")
        lines.append("    classDef cycle fill:#FFFACD,stroke:#FFD700,stroke-width:2px;")
        lines.append("    classDef shared fill:#ADD8E6,stroke:#4169E1,stroke-width:2px;")
        lines.append("")
        
        def get_node_id(n: TreeNode) -> str:
            nonlocal node_counter
            if n.name not in node_ids:
                node_id = f"n{node_counter}"
                node_counter += 1
                node_ids[n.name] = node_id
                
                # Build node label
                label = n.name
                if n.version:
                    label += f" ({n.version})"
                
                # Escape special characters
                label = label.replace('"', '\\"')
                
                lines.append(f'    {node_id}["{label}"]')
                
                # Add CSS class based on status
                class_map = {
                    'installed': 'installed',
                    'not_installed': 'not_installed',
                    'error': 'error',
                    'cycle_detected': 'cycle',
                    'shared': 'shared'
                }
                css_class = class_map.get(n.status)
                if css_class:
                    lines.append(f"    class {node_id} {css_class};")
                
            return node_ids[n.name]
        
        def add_edges(n: TreeNode, parent_id: Optional[str] = None):
            node_id = get_node_id(n)
            if parent_id:
                lines.append(f"    {parent_id} --> {node_id}")
            for child in n.dependencies:
                add_edges(child, node_id)
        
        add_edges(node)
        
        return "\n".join(lines)
    
    def export_tree(self, package_name: str, format: TreeOutputFormat,
                   output_file: Optional[str] = None, **kwargs) -> Optional[str]:
        """
        Export dependency tree to various formats.
        
        This is the main export method that builds a tree for the given
        package and formats it according to the specified output format.
        Can write directly to a file or return the formatted string.
        
        Parameters
        ----------
        package_name : str
            Name of the package to analyze.
        format : TreeOutputFormat
            Desired output format (TEXT, JSON, HTML, DOT, MERMAID, etc.)
        output_file : str, optional
            If provided, write output to this file instead of returning string.
        **kwargs
            Format-specific options passed to individual formatters.
        
        Returns
        -------
        Optional[str]
            If output_file is None, returns the formatted string.
            Otherwise, returns None after writing to file.
        
        Raises
        ------
        ValueError
            If tree cannot be built or format is unsupported.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> 
        >>> # Export to JSON string
        >>> json_str = printer.export_tree("requests", TreeOutputFormat.JSON)
        >>> 
        >>> # Export to HTML file
        >>> printer.export_tree("pandas", TreeOutputFormat.HTML, "tree.html")
        >>> 
        >>> # Export to Graphviz DOT
        >>> dot_str = printer.export_tree("flask", TreeOutputFormat.DOT, rankdir="TB")
        """
        # Reset global tracking for this tree
        self._seen_global.clear()
        self._shared_refs.clear()
        
        # Build the tree
        root = self._build_tree(package_name)
        if not root:
            raise ValueError(f"Failed to build tree for package: {package_name}")
        
        # Select and call the appropriate formatter
        formatters = {
            TreeOutputFormat.TEXT: self._format_as_text,
            TreeOutputFormat.PLAIN: self._format_as_plain,
            TreeOutputFormat.MARKDOWN: self._format_as_markdown,
            TreeOutputFormat.JSON: self._format_as_json,
            TreeOutputFormat.DICT: self._format_as_dict,
            TreeOutputFormat.HTML: self._format_as_html,
            TreeOutputFormat.DOT: self._format_as_dot,
            TreeOutputFormat.MERMAID: self._format_as_mermaid
        }
        
        formatter = formatters.get(format)
        if not formatter:
            raise ValueError(f"Unsupported output format: {format}")
        
        # Generate output
        output = formatter(root, **kwargs)
        
        # Write to file or return string
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(output)
            logger.info(f"Exported tree to {output_file}")
            return None
        
        return output
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get printer performance statistics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing statistics about trees printed, cache
            performance, node counts, cycles detected, and deduplication savings.
        
        Examples
        --------
        >>> printer = DependencyTreePrinter()
        >>> printer.print_tree("requests")
        >>> stats = printer.get_stats()
        >>> print(f"Nodes: {stats['total_nodes']}")
        >>> print(f"Deduplications saved: {stats['deduplications_saved']}")
        >>> print(f"Cycles detected: {stats['cycles_detected']}")
        """
        total_requests = self._stats['cache_hits'] + self._stats['cache_misses']
        hit_rate = (self._stats['cache_hits'] / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'trees_printed': self._stats['trees_printed'],
            'cache_hits': self._stats['cache_hits'],
            'cache_misses': self._stats['cache_misses'],
            'cache_hit_rate': round(hit_rate, 2),
            'cache_size': len(self._cache),
            'total_nodes_processed': self._stats['total_nodes'],
            'deduplications_saved': self._stats['deduplications_saved'],
            'cycles_detected': self._stats['cycles_detected']
        }
    
    def clear_cache(self) -> None:
        """Clear all cached trees from memory."""
        self._cache.clear()
        logger.debug("Printer cache cleared")


# =============================================================================
# CONVENIENCE FUNCTIONS FOR BACKWARD COMPATIBILITY
# =============================================================================

def print_dep_tree(
    package_name: str,
    indent: int = 0,
    seen: Optional[Set[str]] = None,
    max_depth: Optional[int] = 1,
    current_depth: int = 0,
    show_versions: bool = True,
    show_required: bool = True,
    show_installed: bool = True,
    verbose: bool = False,
    pattern_filter: Optional[Pattern] = None,
    skip_optional: bool = False,
    parallel_processing: int = 1,
    show_extras: bool = False,
    show_markers: bool = False,
    colorize: bool = False,
    # NEW: Deduplication parameters
    deduplicate_shared: bool = False,
    duplicate_handling: str = "deduplicate",
) -> bool:
    """
    Recursively print a visual dependency tree for a Python package.
    
    This is the main legacy function for printing dependency trees. It maintains
    backward compatibility with the original API while adding support for the
    new deduplication features.
    
    Parameters
    ----------
    package_name : str
        Root package name to analyze.
    
    indent : int, default=0
        Current indentation level (internal use).
    
    seen : Set[str], optional
        Set of visited packages for cycle detection.
    
    max_depth : int, default=1
        Maximum recursion depth. Use None for unlimited, or -1 for unlimited.
    
    current_depth : int, default=0
        Current recursion depth (internal use).
    
    show_versions : bool, default=True
        Display installed package versions.
    
    show_required : bool, default=True
        Show version requirements from parent packages.
    
    show_installed : bool, default=True
        Show installation status of dependencies.
    
    verbose : bool, default=False
        Display detailed error messages.
    
    pattern_filter : Pattern, optional
        Regex pattern to filter displayed packages.
    
    skip_optional : bool, default=False
        Exclude optional dependencies from the tree.
    
    parallel_processing : int, default=1
        Number of parallel threads for processing.
    
    show_extras : bool, default=False
        Display package extras in requirement info.
    
    show_markers : bool, default=False
        Display environment markers in requirement info.
    
    colorize : bool, default=False
        Use ANSI colors in output.
    
    deduplicate_shared : bool, default=False
        Enable deduplication of shared dependencies (NEW!).
    
    duplicate_handling : str, default="deduplicate"
        Strategy for handling duplicate dependencies (NEW!).
        Options: 'show_all', 'deduplicate', 'merge', 'mark_shared', 'collapse'
    
    Returns
    -------
    bool
        True if tree was built successfully, False if errors occurred.
    
    Examples
    --------
    >>> # Basic usage
    >>> print_dep_tree("requests", max_depth=2)
    requests==2.28.1
    ├── certifi>=2017.4.17
    ├── charset-normalizer~=2.0.0
    └── urllib3<1.27,>=1.21.1
    
    >>> # With deduplication
    >>> print_dep_tree("pyputil", max_depth=3, deduplicate_shared=True, duplicate_handling="merge")
    
    >>> # With filtering and colors
    >>> import re
    >>> print_dep_tree("scikit-learn", 
    ...                pattern_filter=re.compile("^numpy|^scipy"), 
    ...                max_depth=2, 
    ...                colorize=True)
    
    >>> # No extra info, compact output
    >>> print_dep_tree("pandas", 
    ...                show_versions=False, 
    ...                show_required=False, 
    ...                show_installed=False,
    ...                max_depth=2)
    """
    # Convert max_depth=-1 to None for unlimited
    if max_depth == -1:
        max_depth = None
    
    # Create style with legacy settings
    style = TreeStyle(
        use_unicode=True,
        show_versions=show_versions,
        show_requirements=show_required,
        show_status=show_installed,
        show_extras=show_extras,
        show_markers=show_markers,
        colorize=colorize
    )
    
    # Create printer with all options including deduplication
    printer = DependencyTreePrinter(
        style=style,
        max_depth=max_depth if max_depth != 1 else None,
        pattern_filter=pattern_filter,
        skip_optional=skip_optional,
        parallel_processing=parallel_processing,
        cache_results=False,  # Don't cache for legacy function
        deduplicate_shared=deduplicate_shared,
        duplicate_handling=duplicate_handling
    )
    
    # Print the tree
    return printer.print_tree(package_name, verbose=verbose)


def format_tree_text(tree: Dict, indent: int = 0) -> str:
    """
    Format a dependency tree dictionary as human-readable text.
    
    This function converts a tree dictionary (from get_tree) into a formatted
    text string without printing it directly. Useful for saving to files or
    integrating with other systems.
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure dictionary.
    indent : int, default=0
        Current indentation level (internal use).
    
    Returns
    -------
    str
        Formatted tree as multiline string.
    
    Examples
    --------
    >>> tree = {'name': 'requests', 'version': '2.28.1', 
    ...         'dependencies': [{'name': 'urllib3', 'version': '1.26.13'}]}
    >>> print(format_tree_text(tree))
    requests==2.28.1
    └── urllib3==1.26.13
    """
    if tree is None:
        return ""
    
    indent_str = " " * indent
    result = []
    
    name = tree.get("name", "")
    version = tree.get("version", "")
    status = tree.get("status", "")
    dep_type = tree.get("type", "")
    
    line = f"{indent_str}{name}"
    if version:
        line += f"=={version}"
    if status != "installed":
        line += f" [{status}]"
    if dep_type and dep_type != "required":
        line += f" ({dep_type})"
    
    result.append(line)
    
    dependencies = tree.get("dependencies", [])
    for i, dep in enumerate(dependencies):
        prefix = "├── " if i < len(dependencies) - 1 else "└── "
        child_text = format_tree_text(dep, indent + 4)
        
        if child_text:
            first_line = child_text.split("\n")[0]
            result.append(f"{indent_str}{prefix}{first_line}")
            
            remaining_lines = child_text.split("\n")[1:]
            for rem_line in remaining_lines:
                if rem_line:
                    extension = "│   " if i < len(dependencies) - 1 else "    "
                    result.append(f"{indent_str}{extension}{rem_line}")
    
    return "\n".join(result)


def export_tree_to_file(package_name: str, output_file: str,
                       format: str = 'text', **kwargs) -> bool:
    """
    Export dependency tree directly to a file.
    
    Parameters
    ----------
    package_name : str
        Package name to analyze.
    output_file : str
        Path to output file.
    format : str, default='text'
        Output format ('text', 'json', 'html', 'dot', 'mermaid', 'markdown').
    **kwargs
        Additional options passed to the exporter.
    
    Returns
    -------
    bool
        True if successful, False otherwise.
    
    Examples
    --------
    >>> export_tree_to_file("requests", "tree.html", format='html')
    True
    >>> export_tree_to_file("requests", "tree.json", format='json')
    True
    >>> export_tree_to_file("pandas", "tree.dot", format='dot')
    True
    """
    format_map = {
        'text': TreeOutputFormat.TEXT,
        'json': TreeOutputFormat.JSON,
        'html': TreeOutputFormat.HTML,
        'dot': TreeOutputFormat.DOT,
        'mermaid': TreeOutputFormat.MERMAID,
        'markdown': TreeOutputFormat.MARKDOWN,
        'plain': TreeOutputFormat.PLAIN
    }
    
    output_format = format_map.get(format.lower(), TreeOutputFormat.TEXT)
    
    try:
        printer = DependencyTreePrinter(**kwargs)
        printer.export_tree(package_name, output_format, output_file)
        return True
    except Exception as e:
        logger.error(f"Failed to export tree: {e}")
        if kwargs.get('verbose', False):
            import traceback
            traceback.print_exc()
        return False


# =============================================================================
# MODULE INITIALIZATION
# =============================================================================

def _setup_logging():
    """Configure module logging with default settings."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)


_setup_logging()
logger.debug("Dependency tree printing module initialized (v3.1.0)")


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    'DuplicateHandling',
    'TreeOutputFormat',
    
    # Data classes
    'TreeNode',
    'TreeStyle',
    
    # Main class
    'DependencyTreePrinter',
    
    # Convenience functions
    'print_dep_tree',
    'format_tree_text',
    'export_tree_to_file'
]