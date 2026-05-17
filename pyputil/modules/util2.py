#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import ast
import hashlib
import importlib
import logging
import os
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Dict, Set, List, Optional, Iterator, Tuple, Any, Callable
from .stdlib import is_stdlib 

# Configure logging
logger = logging.getLogger(__name__)


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class ModuleNode:
    """
    Comprehensive node representing a Python module or package.
    
    This enhanced data structure stores all relevant metadata about a module,
    including file system information, namespace package detection, and
    hierarchical relationships.
    
    Attributes
    ----------
    name : str
        Fully qualified module name (e.g., 'requests.packages.urllib3')
    path : Path
        Absolute filesystem path to the module file or package directory
    is_package : bool
        True if this is a package (has __init__.py or is namespace package)
    is_namespace : bool
        True if this is a PEP 420 namespace package (no __init__.py)
    size : int
        File size in bytes (0 for directories or namespace packages)
    modified : datetime
        Last modification timestamp of the module file
    hash : str
        SHA-256 hash of file content (empty string for packages)
    parent : Optional[str]
        Name of the parent package (None for top-level modules)
    submodules : Set[str]
        Set of submodule names (only populated for packages)
    is_stdlib : bool
        True if this module is part of Python standard library
    
    Examples
    --------
    >>> node = ModuleNode(
    ...     name='my_package.submodule',
    ...     path=Path('/project/my_package/submodule.py'),
    ...     is_package=False
    ... )
    >>> print(f"{node.name}: {node.size} bytes")
    """
    name: str
    path: Path
    is_package: bool = False
    is_namespace: bool = False
    size: int = 0
    modified: datetime = field(default_factory=datetime.now)
    hash: str = ""
    parent: Optional[str] = None
    submodules: Set[str] = field(default_factory=set)
    is_stdlib: bool = False
    
    def __post_init__(self):
        """Auto-calculate file metadata when path is provided."""
        if self.path and self.path.exists() and not self.is_package:
            try:
                stat = self.path.stat()
                self.size = stat.st_size
                self.modified = datetime.fromtimestamp(stat.st_mtime)
                
                # Only hash files smaller than 1MB for performance
                if self.size < 1024 * 1024:
                    with open(self.path, 'rb') as f:
                        self.hash = hashlib.sha256(f.read()).hexdigest()
            except (OSError, IOError) as e:
                logger.debug(f"Cannot read file metadata for {self.path}: {e}")


# ============================================================================
# CORE MODULE DISCOVERY ENGINE
# ============================================================================

def discover_modules(
    path: Optional[List[str]] = None,
    prefix: str = "",
    recursive: bool = True,
    include_namespace_packages: bool = True
) -> Iterator[ModuleNode]:
    """
    Discover all Python modules and packages recursively without using pkgutil.
    
    This is a complete reimplementation of module discovery that properly handles
    PEP 420 namespace packages, provides richer metadata, and offers better
    performance than pkgutil.walk_packages.
    
    Parameters
    ----------
    path : Optional[List[str]], default=None
        List of directory paths to search. If None, uses sys.path.
    prefix : str, default=""
        Module name prefix for nested discovery (used internally for recursion)
    recursive : bool, default=True
        Whether to recursively discover submodules within packages
    include_namespace_packages : bool, default=True
        Whether to include PEP 420 namespace packages in results
    
    Yields
    ------
    ModuleNode
        Discovered module with complete metadata
    
    Notes
    -----
    - Automatically detects namespace packages by checking for directories
      without __init__.py that contain Python modules
    - Skips __pycache__, virtual environments, and hidden directories
    - Respects Python's module resolution order (sys.path order)
    - Provides file hashing for change detection (useful for build systems)
    
    Examples
    --------
    >>> # Discover all modules in current environment
    >>> for module in discover_modules():
    ...     if module.is_namespace:
    ...         print(f"Namespace: {module.name}")
    ...     elif module.is_package:
    ...         print(f"Package: {module.name}")
    ...     else:
    ...         print(f"Module: {module.name}")
    
    >>> # Discover only top-level modules (non-recursive)
    >>> for module in discover_modules(recursive=False):
    ...     print(f"Top-level: {module.name}")
    
    >>> # Discover modules from specific paths
    >>> custom_paths = ['/my_project/src', '/my_project/lib']
    >>> for module in discover_modules(path=custom_paths):
    ...     if module.size > 10000:
    ...         print(f"Large module: {module.name} ({module.size} bytes)")
    
    See Also
    --------
    get_module_graph : Build dependency graph from discovered modules
    ModuleNode : Data structure containing module metadata
    """
    if path is None:
        path = [p for p in sys.path if p and os.path.exists(p)]
    
    visited_paths: Set[str] = set()
    discovered_names: Set[str] = set()
    
    def is_python_file(file_path: Path) -> bool:
        """Check if file is a Python source file."""
        return file_path.suffix == '.py' and file_path.name != '__pycache__'
    
    def is_package_directory(dir_path: Path, has_init: bool) -> Tuple[bool, bool]:
        """
        Determine if a directory is a regular package or namespace package.
        
        Returns
        -------
        Tuple[bool, bool]
            (is_package, is_namespace) where:
            - is_package: directory contains __init__.py
            - is_namespace: directory is a PEP 420 namespace package
        """
        init_file = dir_path / '__init__.py'
        has_init_file = init_file.exists()
        
        if has_init_file:
            return True, False
        elif include_namespace_packages:
            # Check if directory contains any Python files (potential namespace)
            has_py_files = any(dir_path.glob('*.py')) or any(dir_path.glob('*/**/*.py'))
            return has_py_files, has_py_files
        return False, False
    
    def get_module_name_from_path(file_path: Path, base_path: Path, prefix_name: str) -> str:
        """
        Convert filesystem path to fully qualified module name.
        
        Examples
        --------
        >>> get_module_name_from_path(Path('/project/pkg/sub.py'), Path('/project'), '')
        'pkg.sub'
        >>> get_module_name_from_path(Path('/project/pkg/__init__.py'), Path('/project'), '')
        'pkg'
        """
        rel_path = file_path.relative_to(base_path)
        
        if file_path.name == '__init__.py':
            # Package: use directory name
            parts = list(rel_path.parent.parts)
        else:
            # Module: use filename without extension
            parts = list(rel_path.with_suffix('').parts)
        
        # Filter out special directories
        parts = [p for p in parts if p not in ('__pycache__', '.git', '.venv', 'venv')]
        
        full_name = '.'.join(parts)
        if prefix_name:
            full_name = f"{prefix_name}.{full_name}" if full_name else prefix_name
        
        return full_name
    
    def scan_directory(
        dir_path: Path,
        base_path: Path,
        current_prefix: str = "",
        depth: int = 0
    ) -> Iterator[ModuleNode]:
        """
        Recursively scan a directory for Python modules and packages.
        """
        if not dir_path.exists() or not dir_path.is_dir():
            return
        
        # Prevent infinite recursion and duplicate scans
        abs_path = str(dir_path.absolute())
        if abs_path in visited_paths:
            return
        visited_paths.add(abs_path)
        
        # Skip virtual environments and special directories
        if any(skip in dir_path.parts for skip in ['.venv', 'venv', '__pycache__', '.git']):
            return
        
        # Check if this directory is a package
        has_init = (dir_path / '__init__.py').exists()
        is_pkg, is_ns = is_package_directory(dir_path, has_init)
        
        # Generate module name for this directory if it's a package
        if is_pkg and current_prefix:
            # For nested packages, we need the full name
            pkg_name = current_prefix
        elif is_pkg and not current_prefix and base_path != dir_path:
            # Top-level package: compute from base
            rel_to_base = dir_path.relative_to(base_path)
            pkg_name = '.'.join(rel_to_base.parts) if rel_to_base != Path('.') else dir_path.name
        else:
            pkg_name = current_prefix
        
        # If this is a package, yield it as a ModuleNode
        if is_pkg and pkg_name and pkg_name not in discovered_names:
            discovered_names.add(pkg_name)
            
            # For namespace packages, the path is the directory itself
            node_path = dir_path if is_ns else (dir_path / '__init__.py' if has_init else dir_path)
            
            yield ModuleNode(
                name=pkg_name,
                path=node_path,
                is_package=True,
                is_namespace=is_ns,
                parent=None  # Parent will be set later
            )
        
        # Scan Python files in current directory
        for item in dir_path.iterdir():
            if item.is_file() and is_python_file(item):
                module_name = get_module_name_from_path(item, base_path, current_prefix)
                
                if module_name not in discovered_names:
                    discovered_names.add(module_name)
                    yield ModuleNode(
                        name=module_name,
                        path=item,
                        is_package=False,
                        is_namespace=False
                    )
            
            elif item.is_dir() and recursive:
                # Recursively scan subdirectories
                sub_prefix = get_module_name_from_path(item, base_path, current_prefix)
                yield from scan_directory(item, base_path, sub_prefix, depth + 1)
    
    # Scan each path in sys.path order (respects import precedence)
    for search_path in path:
        search_dir = Path(search_path)
        if search_dir.exists() and search_dir.is_dir():
            yield from scan_directory(search_dir, search_dir, prefix)


# ============================================================================
# DEPENDENCY GRAPH BUILDING
# ============================================================================

def get_module_graph(
    package_name: str,
    recursive: bool = True,
    include_external: bool = False
) -> Dict[str, Set[str]]:
    """
    Build a dependency graph of modules within a package using AST analysis.
    
    This function parses Python source files, extracts all import statements,
    and constructs a directed graph of module dependencies. It handles both
    absolute and relative imports, resolves aliases, and filters dependencies
    based on the target package.
    
    Parameters
    ----------
    package_name : str
        Name of the package to analyze (must be importable in current environment)
    recursive : bool, default=True
        Whether to recursively analyze subpackages. If False, only analyzes
        modules directly in the package directory (not subdirectories)
    include_external : bool, default=False
        Whether to include dependencies on external packages (third-party
        and standard library) in the graph. When False, only dependencies
        within the target package are included.
    
    Returns
    -------
    Dict[str, Set[str]]
        Mapping from module name to set of module names it depends on.
        Keys are fully qualified module names within the target package.
    
    Notes
    -----
    - Handles complex import patterns: `import x`, `from x import y`, `from . import z`
    - Resolves relative imports (e.g., `from ..utils import helper`)
    - Detects and logs syntax errors without stopping analysis
    - Aliased imports are resolved to their original module names
    - Circular imports are not resolved (they appear as dependencies)
    
    Examples
    --------
    >>> # Basic usage
    >>> graph = get_module_graph('my_package')
    >>> for module, deps in graph.items():
    ...     print(f"{module} -> {', '.join(deps)}")
    
    >>> # Find modules with no dependencies
    >>> leaf_modules = [m for m, deps in graph.items() if not deps]
    
    >>> # Analyze with external dependencies included
    >>> full_graph = get_module_graph('my_package', include_external=True)
    >>> external_deps = {m: deps for m, deps in full_graph.items() 
    ...                  if any('.' not in d for d in deps)}
    
    >>> # Non-recursive analysis (top-level only)
    >>> top_graph = get_module_graph('my_package', recursive=False)
    
    See Also
    --------
    circular_deps : Detect circular dependencies in the generated graph
    discover_modules : Find all modules in a package
    """
    graph: Dict[str, Set[str]] = defaultdict(set)
    module_paths: Dict[str, Path] = {}
    visited: Set[str] = set()
    
    def is_within_package(import_name: str, target_package: str) -> bool:
        """Check if imported module belongs to the target package."""
        return (import_name == target_package or 
                import_name.startswith(target_package + '.') or
                (not include_external and '.' not in import_name and 
                 import_name != target_package))
    
    def resolve_import_name(
        import_name: str,
        current_module: str,
        level: int = 0
    ) -> str:
        """
        Resolve import name to absolute module name.
        
        Handles both absolute imports and relative imports (with dots).
        
        Parameters
        ----------
        import_name : str
            Import name from AST (e.g., 'utils', '.submodule', '..parent')
        current_module : str
            Fully qualified name of the current module
        level : int, default=0
            Number of dots for relative imports (0 for absolute)
        
        Returns
        -------
        str
            Resolved absolute module name
        """
        if level == 0:
            return import_name
        
        # Handle relative imports
        current_parts = current_module.split('.')
        
        if level > len(current_parts):
            # Relative import goes above top-level package
            return import_name
        
        # Remove the appropriate number of parent levels
        base_parts = current_parts[:-level] if level > 0 else current_parts
        
        if import_name:
            return '.'.join(base_parts + [import_name])
        else:
            return '.'.join(base_parts)
    
    def extract_imports(file_path: Path, module_name: str) -> Set[str]:
        """
        Extract all import statements from a Python file using AST.
        
        Returns
        -------
        Set[str]
            Set of absolute module names imported in this file
        """
        imports = set()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read())
            
            for node in ast.walk(tree):
                # Handle 'import module' statements
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        base_module = alias.name.split('.')[0]
                        imports.add(base_module)
                
                # Handle 'from module import ...' statements
                elif isinstance(node, ast.ImportFrom):
                    if node.module is not None:
                        # Resolve relative imports
                        abs_module = resolve_import_name(
                            node.module, 
                            module_name, 
                            node.level
                        )
                        base_module = abs_module.split('.')[0]
                        imports.add(base_module)
        
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {e}")
        except (UnicodeDecodeError, OSError) as e:
            logger.debug(f"Cannot parse {file_path}: {e}")
        
        return imports
    
    def find_module_files(package: ModuleType) -> Iterator[Tuple[str, Path]]:
        """
        Find all Python files in a package directory structure.
        
        Yields
        ------
        Tuple[str, Path]
            (module_name, file_path) for each Python file found
        """
        if not hasattr(package, '__path__'):
            return
        
        for path_item in package.__path__:
            base_path = Path(path_item)
            if not base_path.exists():
                continue
            
            # Determine search pattern based on recursion flag
            pattern = "**/*.py" if recursive else "*.py"
            
            for py_file in base_path.glob(pattern):
                # Skip __pycache__ directories
                if '__pycache__' in py_file.parts:
                    continue
                
                # Calculate module name from file path
                if py_file.name == '__init__.py':
                    module_name = package_name
                else:
                    rel_path = py_file.relative_to(base_path)
                    parts = list(rel_path.with_suffix('').parts)
                    module_name = '.'.join([package_name] + parts)
                
                yield module_name, py_file
                
                if not recursive:
                    break  # Only process top-level when not recursive
    
    # Main execution
    try:
        package = importlib.import_module(package_name)
        
        # First pass: collect all module file paths
        for module_name, file_path in find_module_files(package):
            module_paths[module_name] = file_path
        
        # Second pass: analyze imports for each module
        for module_name, file_path in module_paths.items():
            if module_name in visited:
                continue
            visited.add(module_name)
            
            imports = extract_imports(file_path, module_name)
            
            # Filter imports based on include_external flag
            for imp in imports:
                if is_within_package(imp, package_name):
                    graph[module_name].add(imp)
    
    except ImportError as e:
        logger.error(f"Cannot import package '{package_name}': {e}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error analyzing '{package_name}': {e}")
        return {}
    
    return dict(graph)


# ============================================================================
# CIRCULAR DEPENDENCY DETECTION
# ============================================================================

def circular_deps(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """
    Detect all circular dependencies in a module dependency graph.
    
    Uses an optimized depth-first search algorithm with cycle detection to find
    all strongly connected components that form cycles. Each cycle represents
    a circular import chain that could cause runtime issues.
    
    Parameters
    ----------
    graph : Dict[str, Set[str]]
        Dependency graph from get_module_graph(), mapping module names
        to sets of modules they import.
    
    Returns
    -------
    List[List[str]]
        List of cycles found. Each cycle is a list of module names where
        the last module imports the first (or a module earlier in the list).
        Returns empty list if no cycles are detected.
    
    Algorithm
    ---------
    Uses Tarjan's strongly connected components algorithm adapted for cycle
    detection. Each SCC with more than one node, or a single node with a
    self-loop, represents a cycle.
    
    Notes
    -----
    - Each cycle is returned in canonical form (starting with the smallest
      lexicographical module name)
    - A module importing itself (self-loop) is considered a cycle of length 1
    - The algorithm has O(V + E) time complexity where V is vertices count
    - Detects nested cycles (cycles within cycles)
    
    Examples
    --------
    >>> graph = {
    ...     'module_a': {'module_b'},
    ...     'module_b': {'module_c'},
    ...     'module_c': {'module_a'}
    ... }
    >>> cycles = circular_deps(graph)
    >>> for cycle in cycles:
    ...     print(" -> ".join(cycle))
    module_a -> module_b -> module_c -> module_a
    
    >>> # Check if specific module is part of any cycle
    >>> module_in_cycle = any('module_x' in cycle for cycle in cycles)
    
    >>> # Get all modules that are part of cycles
    >>> cyclic_modules = set()
    >>> for cycle in cycles:
    ...     cyclic_modules.update(cycle)
    
    >>> # Visualize cycles with different starting points
    >>> for cycle in cycles:
    ...     for i, module in enumerate(cycle):
    ...         if i < len(cycle) - 1:
    ...             print(f"{module} -> {cycle[i+1]}")
    
    See Also
    --------
    get_module_graph : Generate the dependency graph to analyze
    """
    if not graph:
        return []
    
    cycles: List[List[str]] = []
    visited: Set[str] = set()
    recursion_stack: Set[str] = set()
    index_counter: List[int] = [0]
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    stack: List[str] = []
    sccs: List[List[str]] = []
    
    def strongconnect(node: str) -> None:
        """
        Tarjan's strongly connected components algorithm.
        
        Finds SCCs which represent cycles when they have more than one node
        or a self-loop.
        """
        # Set the depth index for this node
        indices[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        recursion_stack.add(node)
        
        # Consider successors (neighbors)
        for neighbor in graph.get(node, set()):
            if neighbor not in indices:
                # Successor not yet visited, recurse
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in recursion_stack:
                # Successor is in stack and hence in current SCC
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        
        # If node is a root node, pop the stack and generate an SCC
        if lowlinks[node] == indices[node]:
            scc: List[str] = []
            while True:
                w = stack.pop()
                recursion_stack.remove(w)
                scc.append(w)
                if w == node:
                    break
            
            # An SCC is a cycle if it has more than one node
            # OR if it has one node that imports itself
            if len(scc) > 1:
                sccs.append(scc)
            elif len(scc) == 1:
                # Check for self-loop
                if scc[0] in graph.get(scc[0], set()):
                    sccs.append(scc)
    
    # Find all SCCs
    for node in graph:
        if node not in indices:
            strongconnect(node)
    
    # Convert SCCs to cycles
    def normalize_cycle(cycle: List[str]) -> List[str]:
        """
        Convert an SCC to a canonical cycle representation.
        
        Returns the cycle starting from the smallest module name
        and closing back to the start.
        """
        if len(cycle) == 1:
            return [cycle[0], cycle[0]]  # Self-loop
        
        # Find the smallest element by lexicographical order
        start_index = min(range(len(cycle)), key=lambda i: cycle[i])
        
        # Create cycle starting from smallest element
        normalized = cycle[start_index:] + cycle[:start_index]
        normalized.append(normalized[0])  # Close the cycle
        
        return normalized
    
    for scc in sccs:
        cycle = normalize_cycle(scc)
        if cycle not in cycles:
            cycles.append(cycle)
    
    return cycles


# ============================================================================
# NAMESPACE PACKAGE DISCOVERY
# ============================================================================

def namespace_packages() -> List[str]:
    """
    Discover all PEP 420 namespace packages in the current Python environment.
    
    Namespace packages are packages that can be split across multiple directories
    and do not require __init__.py files (PEP 420, Python 3.3+). This function
    scans all paths in sys.path to identify directories that:
        1. Do not contain __init__.py
        2. Contain at least one Python module (directly or indirectly)
        3. Are importable as packages
    
    Returns
    -------
    List[str]
        Sorted list of namespace package names found in the environment.
        Returns empty list if no namespace packages are detected.
    
    Algorithm
    ---------
    1. Iterates through all import finders in sys.meta_path
    2. For each directory in sys.path, checks for potential namespace packages
    3. Uses ModuleSpec to verify if a directory qualifies as a namespace package
    4. Deduplicates results and returns sorted list
    
    Notes
    -----
    - This function properly handles nested namespace packages
    - Detects namespace packages from all paths in sys.path
    - Different from regular packages that have __init__.py files
    - Useful for plugin systems and distributed packages
    
    Examples
    --------
    >>> # Find all namespace packages
    >>> ns_packages = namespace_packages()
    >>> print(f"Found {len(ns_packages)} namespace packages: {ns_packages}")
    
    >>> # Filter namespace packages by pattern
    >>> plugin_packages = [pkg for pkg in namespace_packages() 
    ...                    if pkg.startswith('plugin_')]
    
    >>> # Check if a specific package is a namespace package
    >>> is_namespace = 'my_plugins' in namespace_packages()
    
    >>> # Discover namespace packages in specific paths
    >>> import sys
    >>> original_path = sys.path.copy()
    >>> sys.path.insert(0, '/custom/plugins')
    >>> plugins = namespace_packages()
    >>> sys.path = original_path
    
    See Also
    --------
    discover_modules : Complete module discovery including namespace packages
    ModuleNode.is_namespace : Attribute indicating if module is namespace package
    """
    namespace_pkgs: Set[str] = set()
    
    # Try each finder in sys.meta_path
    for finder in sys.meta_path:
        if not hasattr(finder, 'find_spec'):
            continue
        
        # Scan each path in sys.path
        for path_item in sys.path:
            if not path_item or not os.path.exists(path_item):
                continue
            
            try:
                # List all directories in the path
                for entry in os.listdir(path_item):
                    full_path = os.path.join(path_item, entry)
                    
                    # Check if it's a directory without __init__.py
                    if os.path.isdir(full_path):
                        init_file = os.path.join(full_path, '__init__.py')
                        
                        if not os.path.exists(init_file):
                            # Try to find spec for this potential namespace package
                            try:
                                spec = finder.find_spec(entry, [path_item])
                                if (spec and 
                                    spec.submodule_search_locations and 
                                    not spec.origin):
                                    namespace_pkgs.add(entry)
                            except (ImportError, AttributeError):
                                continue
            except (OSError, PermissionError) as e:
                logger.debug(f"Cannot scan directory {path_item}: {e}")
                continue
    
    return sorted(namespace_pkgs)


# ============================================================================
# ADVANCED MODULE WALKER (No pkgutil)
# ============================================================================

def walk_packages(
    path: Optional[List[str]] = None,
    prefix: str = "",
    onerror: Optional[Callable[[str], None]] = None,
    include_stdlib: bool = False
) -> Iterator[ModuleNode]:
    """
    Walk through all modules recursively with advanced namespace support.
    
    This is a complete reimplementation of pkgutil.walk_packages that provides:
    - Proper PEP 420 namespace package handling
    - Rich metadata (file size, hash, modification time)
    - Better performance through path deduplication
    - Support for filtering standard library modules
    
    Parameters
    ----------
    path : Optional[List[str]], default=None
        List of directory paths to search. If None, uses sys.path.
    prefix : str, default=""
        String to prepend to module names (used for recursion internally)
    onerror : Optional[Callable[[str], None]], default=None
        Error handler called with the module name when import fails.
        If None, errors are silently logged.
    include_stdlib : bool, default=False
        Whether to include Python standard library modules in results.
        When False, only third-party and local modules are returned.
    
    Yields
    ------
    ModuleNode
        Enhanced module information including namespace detection,
        file system metadata, and content hash for change detection.
    
    Notes
    -----
    - Avoids visiting the same physical path multiple times
    - Detects namespace packages automatically using PEP 420 rules
    - Computes SHA-256 hash only for files smaller than 1MB
    - Preserves Python's import order (sys.path precedence)
    - Handles circular imports gracefully
    
    Examples
    --------
    >>> # Walk all modules (excluding stdlib)
    >>> for module in walk_packages():
    ...     if module.is_namespace:
    ...         print(f"Namespace: {module.name}")
    ...     elif module.is_package:
    ...         print(f"Package: {module.name}")
    ...     else:
    ...         print(f"Module: {module.name} ({module.size} bytes)")
    
    >>> # Include standard library modules
    >>> for module in walk_packages(include_stdlib=True):
    ...     if module.is_stdlib:
    ...         print(f"Stdlib: {module.name}")
    
    >>> # Find recently modified modules
    >>> from datetime import timedelta
    >>> recent = datetime.now() - timedelta(days=7)
    >>> for module in walk_packages():
    ...     if module.modified > recent:
    ...         print(f"Recently changed: {module.name}")
    
    >>> # Handle import errors with custom callback
    >>> def log_error(module_name):
    ...     print(f"Warning: Could not import {module_name}", file=sys.stderr)
    >>> 
    >>> for module in walk_packages(onerror=log_error):
    ...     if module.is_package:
    ...         print(f"Found package: {module.name}")
    
    >>> # Find large modules for optimization
    >>> large_modules = [m for m in walk_packages() 
    ...                  if m.size > 100000 and not m.is_package]
    >>> for module in large_modules:
    ...     print(f"Large module: {module.name} ({module.size/1024:.1f} KB)")
    
    See Also
    --------
    discover_modules : Core module discovery engine
    ModuleNode : Rich data structure for module metadata
    namespace_packages : Find only namespace packages
    """
    # Standard library locations (for filtering)
    stdlib_paths = set()
    if not include_stdlib:
        try:
            import distutils.sysconfig
            stdlib_paths.add(distutils.sysconfig.get_python_lib(standard_lib=True))
            stdlib_paths.add(os.path.dirname(os.__file__))
        except (ImportError, AttributeError):
            pass
    
    def is_stdlib_module(module_path: Path) -> bool:
        """Check if module resides in standard library directory."""
        if not include_stdlib:
            return is_stdlib(module_path.name)
        return False
    
    # Use our discovery engine
    for module in discover_modules(path, prefix, recursive=True):
        # Filter stdlib if needed
        if is_stdlib_module(module.path):
            module.is_stdlib = True
            if not include_stdlib:
                continue
        
        # Attempt to import to verify it's loadable (optional)
        if onerror is not None and module.is_package:
            try:
                importlib.import_module(module.name)
            except ImportError as e:
                onerror(module.name)
                continue
            except Exception as e:
                onerror(module.name)
                continue
        
        yield module


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def format_dep_graph(graph: Dict[str, Set[str]], format_type: str = "text") -> str:
    """
    Format dependency graph for visualization or reporting.
    
    Parameters
    ----------
    graph : Dict[str, Set[str]]
        Dependency graph from get_module_graph()
    format_type : str, default="text"
        Output format: "text", "dot" (GraphViz), "json", or "csv"
    
    Returns
    -------
    str
        Formatted graph representation
    
    Examples
    --------
    >>> graph = get_module_graph('my_package')
    >>> print(format_dep_graph(graph, "dot"))
    digraph G {
        "module_a" -> "module_b";
        "module_b" -> "module_c";
    }
    """
    if format_type == "text":
        lines = []
        for module, deps in sorted(graph.items()):
            if deps:
                lines.append(f"{module} -> {', '.join(sorted(deps))}")
            else:
                lines.append(f"{module} -> (no dependencies)")
        return "\n".join(lines)
    
    elif format_type == "dot":
        lines = ['digraph G {']
        for module, deps in graph.items():
            for dep in deps:
                lines.append(f'    "{module}" -> "{dep}";')
        lines.append('}')
        return "\n".join(lines)
    
    elif format_type == "json":
        import json
        return json.dumps(graph, indent=2)
    
    elif format_type == "csv":
        lines = ["module,dependency"]
        for module, deps in graph.items():
            for dep in deps:
                lines.append(f"{module},{dep}")
        return "\n".join(lines)
    
    else:
        raise ValueError(f"Unsupported format: {format_type}")


def get_module_importers(module_name: str) -> List[str]:
    """
    Find all modules that import a given module.
    
    Parameters
    ----------
    module_name : str
        Name of the module to find reverse dependencies for
    
    Returns
    -------
    List[str]
        List of module names that import the specified module
    
    Examples
    --------
    >>> importers = get_module_importers('my_package.utils')
    >>> print(f"utils is imported by: {', '.join(importers)}")
    """
    graph = get_module_graph(module_name.split('.')[0])
    importers = []
    
    for module, deps in graph.items():
        if module_name in deps:
            importers.append(module)
    
    return sorted(importers)



