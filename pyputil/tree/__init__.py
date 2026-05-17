#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
pyputil.tree - Python Package Dependency Tree Visualization Tool

This package provides comprehensive tools for analyzing and visualizing Python package
dependencies in various formats (text, JSON, YAML, Graphviz, Mermaid, HTML) with
advanced features like cycle detection, conflict resolution, and performance optimization.

Main Features
-------------
- Recursive dependency tree generation with cycle detection
- Multiple output formats (text, JSON, YAML, Graphviz, Mermaid, HTML)
- Advanced filtering (platform, Python version, package types, extras)
- Parallel processing for large dependency trees
- Conflict detection and resolution strategies
- Performance metrics and statistics
- Interactive HTML visualizations
- Directory tree visualization
- Requirements.txt generation

Architecture
------------
The package is organized into several modules:

- **core.models**: Core data structures (PackageInfo, DependencyType, OutputFormat)
- **core.cache**: Thread-safe caching for package metadata
- **core.parser**: PEP 508 requirement string parsing
- **tree.builder**: Dependency tree construction and management
- **tree.printer**: Text-based tree visualization
- **tree.analyzer**: Conflict detection and metrics calculation
- **formats.structured**: JSON/YAML structured output
- **formats.visual**: Graphviz, Mermaid, and HTML visualizations
- **utils.filesystem**: Filesystem utilities for directory trees
- **utils.filters**: Requirement filtering and evaluation

Basic Usage
-----------
>>> from pyputil.tree import print_tree, get_tree, find_conflicts
>>> 
>>> # Print text tree
>>> print_tree("requests", max_depth=2)
requests==2.28.1
├── certifi>=2017.4.17 [required: >=2017.4.17, installed: 2022.12.7]
├── charset-normalizer~=2.0.0 [required: ~=2.0.0, installed: 2.1.1]
└── urllib3<1.27,>=1.21.1 [required: <1.27,>=1.21.1, installed: 1.26.13]

>>> # Get structured tree
>>> tree = get_tree("requests", output_format="json", max_depth=3)
>>> print(tree)

>>> # Find conflicts
>>> conflicts = find_conflicts(tree)
>>> for pkg, info in conflicts.items():
...     print(f"Conflict in {pkg}: {info['different_versions']}")

>>> # Export visualizations
>>> from pyputil.tree import export_to_html, export_to_graphviz
>>> export_to_html(tree, "tree.html")
>>> export_to_graphviz(tree, "tree.dot")

>>> # Directory tree
>>> from pyputil.tree import tree_dir
>>> print(tree_dir("./myproject", max_depth=2))

Advanced Usage
--------------
>>> # Filter by platform and Python version
>>> tree = get_tree("scikit-learn", 
...                 platform_filter='linux',
...                 python_version_filter='>=3.8',
...                 skip_optional=True)

>>> # Parallel processing for large trees
>>> tree = get_tree("tensorflow", 
...                 parallel_processing=4,
...                 max_depth=3)

>>> # With statistics
>>> tree = get_tree("pandas", include_stats=True)
>>> print(tree['statistics']['total_dependencies'])

>>> # Custom conflict resolution
>>> builder = DependencyTreeBuilder()
>>> builder.set_conflict_resolution('requests', '2.28.1')
>>> tree = builder.build('myapp')

License
-------
MIT License

See Also
--------
- GitHub: https://github.com/moamen-walid-pyputil/pyputil
- Documentation: https://pyputil.readthedocs.io
"""

from typing import Optional, List, Dict, Any, Union, Pattern
import re
import warnings
from pathlib import Path

# Core models
from .core.models import DependencyType, OutputFormat, PackageInfo, RequirementInfo
from .core.cache import PackageCache
from .core.parser import parse_requirement, parse_requirement_enhanced, normalize_package_name

# Tree construction and management
from .tree.builder import DependencyTreeBuilder, BuildStrategy, CacheStrategy, ResolutionStrategy
from .tree.printer import print_dep_tree, format_tree_text, DependencyTreePrinter, TreeStyle
from .tree.analyzer import (
    find_conflicts, 
    calculate_tree_metrics, 
    find_orphaned_packages,
    analyze_tree_comprehensive,
    DependencyAnalyzer
)

# Format exporters
from .formats.structured import format_output, tree_to_requirements, filter_tree_output
from .formats.visual import (
    export_to_graphviz, 
    export_to_mermaid, 
    export_to_html,
    export_to_multiple_formats
)

# Utilities
from .utils.filesystem import (
    generate_directory_tree,
    find_package_files,
    read_requirements_file,
    safe_join,
    get_parent_directory
)
from .utils.filters import (
    should_include_requirement,
    filter_packages_by_pattern,
    RequirementFilter,
    FilterRule,
    create_environment_filter
)

# Package metadata
__all__ = [
    # Core models
    "DependencyType",
    "OutputFormat",
    "PackageInfo",
    "RequirementInfo",
    "PackageCache",
    
    # Parsers
    "parse_requirement",
    "parse_requirement_enhanced",
    "normalize_package_name",
    
    # Tree builders
    "DependencyTreeBuilder",
    "BuildStrategy",
    "CacheStrategy",
    "ResolutionStrategy",
    
    # Tree printers
    "print_dep_tree",
    "format_tree_text",
    "DependencyTreePrinter",
    "TreeStyle",
    
    # Analyzers
    "find_conflicts",
    "calculate_tree_metrics",
    "find_orphaned_packages",
    "analyze_tree_comprehensive",
    "DependencyAnalyzer",
    
    # Format exporters
    "format_output",
    "tree_to_requirements",
    "filter_tree_output",
    "export_to_graphviz",
    "export_to_mermaid",
    "export_to_html",
    "export_to_multiple_formats",
    
    # Filesystem utilities
    "generate_directory_tree",
    "find_package_files",
    "read_requirements_file",
    "safe_join",
    "get_parent_directory",
    
    # Filters
    "should_include_requirement",
    "filter_packages_by_pattern",
    "RequirementFilter",
    "FilterRule",
    "create_environment_filter",
    
    # High-level API
    "get_tree",
    "print_tree",
    "tree_dir",
    "get_tree_stats",
    "compare_trees",
    "merge_trees"
]

# Module-level logger
import logging
logger = logging.getLogger(__name__)


def get_tree(
    package_name: str,
    max_depth: Optional[int] = None,
    output_format: str = "dict",
    skip_optional: bool = False,
    skip_development: bool = False,
    parallel_processing: int = 1,
    include_stats: bool = False,
    platform_filter: Optional[str] = None,
    python_version_filter: Optional[str] = None,
    include_extras: Optional[List[str]] = None,
    build_strategy: str = "depth_first",
    cache_strategy: str = "node",
    **kwargs
) -> Union[Dict[str, Any], str, None]:
    """
    Generate a dependency tree in various structured formats.
    
    This is the main API function for building dependency trees with advanced
    filtering and optimization options.
    
    Parameters
    ----------
    package_name : str
        Root package name to analyze
    max_depth : int, optional
        Maximum recursion depth (None for unlimited)
    output_format : {"dict", "json", "yaml"}, default="dict"
        Desired output format
    skip_optional : bool, default=False
        Exclude optional dependencies
    skip_development : bool, default=False
        Exclude development dependencies
    parallel_processing : int, default=1
        Number of parallel threads for processing (1 = sequential)
    include_stats : bool, default=False
        Include tree statistics in output
    platform_filter : str, optional
        Filter by platform ('linux', 'windows', 'darwin', 'unix')
    python_version_filter : str, optional
        Filter by Python version (e.g., '>=3.8')
    include_extras : List[str], optional
        Specific extras to include
    build_strategy : str, default="depth_first"
        Tree building strategy: 'depth_first', 'breadth_first', 'lazy', 'eager'
    cache_strategy : str, default="node"
        Caching strategy: 'none', 'node', 'subtree', 'memoize'
    **kwargs : dict
        Additional arguments passed to the tree builder
    
    Returns
    -------
    dict or str or None
        Dependency tree in requested format, or None if build fails
    
    Raises
    ------
    ValueError
        If package_name is invalid or output_format is unsupported
    TimeoutError
        If build exceeds timeout per node
    
    Examples
    --------
    >>> # Basic usage - get dictionary
    >>> tree = get_tree("requests", max_depth=2)
    >>> tree['name']
    'requests'
    
    >>> # Get JSON string
    >>> json_tree = get_tree("requests", output_format="json", max_depth=3)
    >>> print(json_tree)
    
    >>> # With filtering and parallel processing
    >>> tree = get_tree("scikit-learn", 
    ...                 platform_filter='linux',
    ...                 python_version_filter='>=3.8',
    ...                 parallel_processing=4,
    ...                 include_stats=True)
    
    >>> # With custom strategies
    >>> tree = get_tree("tensorflow",
    ...                 build_strategy='breadth_first',
    ...                 cache_strategy='subtree',
    ...                 max_depth=2)
    
    >>> # For development analysis
    >>> tree = get_tree("myapp",
    ...                 skip_development=False,  # Include dev deps
    ...                 include_extras=['dev', 'test'])
    """
    from .core.models import OutputFormat
    
    # Validate input
    if not package_name or not isinstance(package_name, str):
        raise ValueError(f"Invalid package name: {package_name}")
    
    # Map output format
    format_map = {
        "dict": OutputFormat.DICT,
        "json": OutputFormat.JSON,
        "yaml": OutputFormat.YAML,
    }
    
    output_fmt = format_map.get(output_format)
    if output_format not in format_map:
        raise ValueError(f"Unsupported output format: {output_format}. "
                        f"Supported formats: {list(format_map.keys())}")
    
    # Map build strategy
    build_strategy_map = {
        "depth_first": BuildStrategy.DEPTH_FIRST,
        "breadth_first": BuildStrategy.BREADTH_FIRST,
        "lazy": BuildStrategy.LAZY,
        "eager": BuildStrategy.EAGER
    }
    build_strategy_enum = build_strategy_map.get(build_strategy, BuildStrategy.DEPTH_FIRST)
    
    # Map cache strategy
    cache_strategy_map = {
        "none": CacheStrategy.NONE,
        "node": CacheStrategy.NODE,
        "subtree": CacheStrategy.SUBTREE,
        "memoize": CacheStrategy.MEMOIZE
    }
    cache_strategy_enum = cache_strategy_map.get(cache_strategy, CacheStrategy.NODE)
    
    # Create builder with all options
    builder = DependencyTreeBuilder(
        max_depth=max_depth,
        skip_optional=skip_optional,
        skip_development=skip_development,
        parallel_processing=parallel_processing,
        include_stats=include_stats,
        build_strategy=build_strategy_enum,
        cache_strategy=cache_strategy_enum,
        platform_filter=platform_filter,
        python_version_filter=python_version_filter,
        include_extras=include_extras,
        **kwargs
    )
    
    # Build tree
    tree = builder.build(package_name)
    
    if tree is None:
        logger.error(f"Failed to build tree for {package_name}")
        return None
    
    # Format output
    from .formats.structured import format_output
    return format_output(tree, output_fmt, **kwargs)


def print_tree(
    package_name: str,
    max_depth: int = 1,
    output_format: str = "text",
    pattern_filter: Optional[str] = None,
    skip_optional: bool = False,
    skip_development: bool = False,
    parallel_processing: int = 1,
    show_extras: bool = False,
    show_markers: bool = False,
    show_versions: bool = True,
    show_required: bool = True,
    show_installed: bool = True,
    colorize: bool = False,
    **kwargs
) -> bool:
    """
    Generate and display dependency trees with flexible options.
    
    This is the main API function for printing dependency trees to the console
    with various formatting and filtering options.
    
    Parameters
    ----------
    package_name : str
        Root package name to analyze
    max_depth : int, default=1
        Maximum recursion depth (use None for unlimited)
    output_format : {"text", "json", "yaml", "dict"}, default="text"
        Desired output format for the tree
    pattern_filter : str, optional
        Regular expression pattern to filter package names
    skip_optional : bool, default=False
        Exclude optional dependencies from the tree
    skip_development : bool, default=False
        Exclude development dependencies
    parallel_processing : int, default=1
        Number of parallel threads for processing
    show_extras : bool, default=False
        Display package extras in requirement information
    show_markers : bool, default=False
        Display environment markers in requirement information
    show_versions : bool, default=True
        Display installed package versions
    show_required : bool, default=True
        Show version requirements from parent packages
    show_installed : bool, default=True
        Show installation status of dependencies
    colorize : bool, default=False
        Use ANSI colors in output
    **kwargs : dict
        Additional arguments passed to the tree builder or printer
    
    Returns
    -------
    bool
        True if tree was generated successfully, False otherwise
    
    Examples
    --------
    >>> # Basic text tree
    >>> print_tree("requests", max_depth=2)
    requests==2.28.1
    ├── certifi>=2017.4.17
    ├── charset-normalizer~=2.0.0
    └── urllib3<1.27,>=1.21.1
    
    >>> # JSON output
    >>> print_tree("django", output_format="json", max_depth=3)
    
    >>> # With filtering and color
    >>> print_tree("scikit-learn", 
    ...            pattern_filter="^numpy|^scipy",
    ...            colorize=True,
    ...            max_depth=2)
    
    >>> # Show extras and markers
    >>> print_tree("requests",
    ...            show_extras=True,
    ...            show_markers=True,
    ...            max_depth=2)
    """
    from .core.models import OutputFormat
    
    # Validate input
    if not package_name or not isinstance(package_name, str):
        raise ValueError(f"Invalid package name: {package_name}")
    
    # Handle max_depth=None for unlimited
    if max_depth == -1 or max_depth == 0:
        max_depth = None
    
    # Map output format
    format_map = {
        "text": OutputFormat.TEXT,
        "json": OutputFormat.JSON,
        "yaml": OutputFormat.YAML,
        "dict": OutputFormat.DICT,
    }
    
    output_fmt = format_map.get(output_format)
    if output_format not in format_map:
        raise ValueError(f"Unsupported output format: {output_format}")
    
    # For text output, use the printer directly
    if output_fmt == OutputFormat.TEXT:
        import re
        pattern = re.compile(pattern_filter) if pattern_filter else None
        
        # Create custom style for the printer
        style = TreeStyle(
            use_unicode=True,
            show_versions=show_versions,
            show_requirements=show_required,
            show_status=show_installed,
            show_extras=show_extras,
            show_markers=show_markers,
            colorize=colorize
        )
        
        # Create printer with all options
        printer = DependencyTreePrinter(
            style=style,
            max_depth=max_depth,
            pattern_filter=pattern,
            skip_optional=skip_optional,
            parallel_processing=parallel_processing,
            **kwargs
        )
        
        # Print the tree
        return printer.print_tree(package_name)
    
    else:
        # For structured output, use get_tree and print
        tree = get_tree(
            package_name,
            max_depth=max_depth,
            output_format=output_format,
            skip_optional=skip_optional,
            skip_development=skip_development,
            parallel_processing=parallel_processing,
            **kwargs
        )
        
        if tree is not None:
            if isinstance(tree, str):
                print(tree)
            else:
                import json
                print(json.dumps(tree, indent=2, default=str))
            return True
        
        return False


def tree_dir(
    path: str,
    max_depth: Optional[int] = None,
    show_files: bool = True,
    show_dirs: bool = True,
    sort_by: str = "name",
    ignore: Optional[List[str]] = None,
    full_path: bool = False,
    use_ascii: bool = False,
    include_size: bool = False,
    include_permissions: bool = False,
) -> str:
    """
    Generate a visual directory tree structure.
    
    This function creates a formatted directory tree visualization with various
    customization options for size, permissions, and filtering.
    
    Parameters
    ----------
    path : str
        Directory path to analyze
    max_depth : int, optional
        Maximum depth to display (None for unlimited)
    show_files : bool, default=True
        Include files in output
    show_dirs : bool, default=True
        Include directories in output
    sort_by : {"name", "size", "mtime"}, default="name"
        Sorting criteria for directory contents
    ignore : List[str], optional
        Glob patterns to ignore (e.g., ["*.pyc", "__pycache__"])
    full_path : bool, default=False
        Display full paths instead of relative names
    use_ascii : bool, default=False
        Use ASCII characters instead of Unicode for tree lines
    include_size : bool, default=False
        Include file/directory sizes in output
    include_permissions : bool, default=False
        Include file/directory permissions in output
    
    Returns
    -------
    str
        Directory tree as formatted string
    
    Raises
    ------
    FileNotFoundError
        If the specified path does not exist
    ValueError
        If path is not a directory
    
    Examples
    --------
    >>> # Basic directory tree
    >>> print(tree_dir("./myproject", max_depth=2))
    myproject/
    ├── src/
    │   ├── __init__.py
    │   └── main.py
    └── tests/
        └── test_main.py
    
    >>> # With size and permissions
    >>> print(tree_dir(".", include_size=True, include_permissions=True))
    
    >>> # With ASCII and ignore patterns
    >>> print(tree_dir("./venv", 
    ...                ignore=["*.pyc", "__pycache__"],
    ...                use_ascii=True,
    ...                max_depth=3))
    """
    # Validate path
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    
    if not path_obj.is_dir():
        raise ValueError(f"Path is not a directory: {path}")
    
    # Generate and return tree
    return generate_directory_tree(
        path=path,
        max_depth=max_depth,
        show_files=show_files,
        show_dirs=show_dirs,
        sort_by=sort_by,
        full_path=full_path,
        ignore=ignore,
        use_ascii=use_ascii,
        include_size=include_size,
        include_permissions=include_permissions
    )


def get_tree_stats(tree: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate comprehensive statistics for an existing dependency tree.
    
    Parameters
    ----------
    tree : Dict[str, Any]
        Dependency tree dictionary
    
    Returns
    -------
    Dict[str, Any]
        Statistics including total packages, unique packages, max depth,
        dependency distribution, and more
    
    Examples
    --------
    >>> tree = get_tree("requests", max_depth=3)
    >>> stats = get_tree_stats(tree)
    >>> print(f"Total packages: {stats['total_dependencies']}")
    >>> print(f"Max depth: {stats['max_depth']}")
    >>> print(f"Unique packages: {len(stats['by_status'])}")
    """
    return calculate_tree_metrics(tree)


def compare_trees(tree1: Dict[str, Any], tree2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare two dependency trees and identify differences.
    
    Parameters
    ----------
    tree1 : Dict[str, Any]
        First dependency tree
    tree2 : Dict[str, Any]
        Second dependency tree
    
    Returns
    -------
    Dict[str, Any]
        Comparison results including:
        - common_packages: Packages in both trees
        - only_in_first: Packages only in first tree
        - only_in_second: Packages only in second tree
        - version_differences: Packages with different versions
        - similarity_score: Percentage of common packages (0-100)
    
    Examples
    --------
    >>> tree_a = get_tree("requests", max_depth=2)
    >>> tree_b = get_tree("urllib3", max_depth=2)
    >>> comparison = compare_trees(tree_a, tree_b)
    >>> print(f"Similarity: {comparison['similarity_score']:.1f}%")
    """
    def extract_packages(tree: Dict, depth: int = 0) -> Dict[str, str]:
        """Extract all packages with their versions."""
        packages = {}
        
        def traverse(node: Dict):
            name = node.get('name', '')
            version = node.get('version', '')
            if name:
                packages[name] = version
            for dep in node.get('dependencies', []):
                traverse(dep)
        
        traverse(tree)
        return packages
    
    pkgs1 = extract_packages(tree1)
    pkgs2 = extract_packages(tree2)
    
    set1 = set(pkgs1.keys())
    set2 = set(pkgs2.keys())
    
    common = set1 & set2
    only1 = set1 - set2
    only2 = set2 - set1
    
    # Find version differences
    version_diffs = {}
    for pkg in common:
        if pkgs1[pkg] != pkgs2[pkg]:
            version_diffs[pkg] = {
                'version1': pkgs1[pkg],
                'version2': pkgs2[pkg]
            }
    
    # Calculate similarity score
    total_unique = len(set1 | set2)
    similarity = (len(common) / total_unique * 100) if total_unique > 0 else 0
    
    return {
        'common_packages': list(common),
        'only_in_first': list(only1),
        'only_in_second': list(only2),
        'version_differences': version_diffs,
        'similarity_score': similarity,
        'total_packages_first': len(set1),
        'total_packages_second': len(set2),
        'common_count': len(common)
    }


def merge_trees(tree1: Dict[str, Any], tree2: Dict[str, Any], 
                strategy: str = 'union') -> Dict[str, Any]:
    """
    Merge two dependency trees using specified strategy.
    
    Parameters
    ----------
    tree1 : Dict[str, Any]
        First dependency tree
    tree2 : Dict[str, Any]
        Second dependency tree
    strategy : str, default='union'
        Merge strategy: 'union', 'intersection', 'override', 'deep'
    
    Returns
    -------
    Dict[str, Any]
        Merged tree
    
    Examples
    --------
    >>> tree_a = get_tree("requests", max_depth=1)
    >>> tree_b = get_tree("django", max_depth=1)
    >>> merged = merge_trees(tree_a, tree_b, strategy='union')
    >>> print(f"Combined dependencies: {len(merged['dependencies'])}")
    """
    from .tree.builder import merge_trees as merge_impl
    return merge_impl(tree1, tree2, strategy)


def get_package_info(package_name: str) -> Optional[PackageInfo]:
    """
    Get detailed information about a package.
    
    Parameters
    ----------
    package_name : str
        Name of the package to analyze
    
    Returns
    -------
    Optional[PackageInfo]
        Package information or None if package not found
    
    Examples
    --------
    >>> info = get_package_info("requests")
    >>> if info:
    ...     print(f"{info.name} {info.version}")
    ...     print(f"Dependencies: {len(info.dependencies)}")
    """
    builder = DependencyTreeBuilder(max_depth=1)
    tree = builder.build(package_name)
    
    if tree:
        return PackageInfo(
            name=tree.get('name', ''),
            version=tree.get('version', ''),
            status=tree.get('status', 'unknown'),
            dependencies=[],
            dep_type=DependencyType.REQUIRED
        )
    return None


def list_installed_packages() -> List[str]:
    """
    List all installed Python packages.
    
    Returns
    -------
    List[str]
        List of installed package names
    
    Examples
    --------
    >>> packages = list_installed_packages()
    >>> print(f"Total installed packages: {len(packages)}")
    """
    from ..core.cache import PackageCache
    
    # This is a simplified implementation
    # In practice, you'd use pkg_resources or importlib.metadata
    try:
        import pkg_resources
        return [dist.project_name for dist in pkg_resources.working_set]
    except ImportError:
        # Fallback for Python 3.8+
        try:
            from importlib.metadata import distributions
            return [dist.metadata['Name'] for dist in distributions()]
        except ImportError:
            logger.warning("Cannot list installed packages: no distribution API available")
            return []


# Clean up __all__ to ensure only public API is exposed
def _clean_exports():
    """Remove private attributes from __all__."""
    global __all__
    __all__ = [name for name in __all__ if not name.startswith('_')]


_clean_exports()

# Module initialization
def _setup_logging():
    """Configure module logging."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)


_setup_logging()

# Display welcome message in verbose mode
if __debug__:
    logger.debug("pyputil.tree version initialized")
    logger.debug(f"Available formats: text, json, yaml, dict, html, dot, mermaid")
    logger.debug(f"Parallel processing: available, max workers limited by system")

# Warning about missing optional dependencies
try:
    from ..core.cache import PACKAGING_AVAILABLE
    if not PACKAGING_AVAILABLE:
        warnings.warn(
            "Optional dependency 'packaging' not found. Using built-in fallbacks. "
            "Install for better accuracy: pip install packaging",
            UserWarning,
            stacklevel=2
        )
except ImportError:
    pass


from ..api import clean
clean(expose=__all__)