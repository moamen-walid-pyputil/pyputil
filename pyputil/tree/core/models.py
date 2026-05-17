#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Core data models for the package dependency tree with advanced features.

This module provides comprehensive data structures for representing Python
package dependencies, including support for PEP 508 requirements, dependency
resolution, conflict detection, and tree manipulation.
"""

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import List, Optional, Dict, Any, Set, Union, Tuple
from datetime import datetime
import hashlib
import json
from collections import defaultdict
import copy


class DependencyType(Enum):
    """
    Enumeration of dependency types in Python packages.
    
    This class categorizes dependencies based on their importance and usage context.
    
    Attributes
    ----------
    REQUIRED : str
        Essential dependencies without which the package cannot function
    OPTIONAL : str
        Dependencies that enable additional features but aren't strictly necessary
    DEVELOPMENT : str
        Dependencies used only during development, testing, or documentation
    PEER : str
        Dependencies that should be installed alongside the package
    RECOMMENDED : str
        Dependencies that are recommended but not required
    EXTRAS : str
        Dependencies that are activated by extras
    CONFLICT : str
        Dependencies that conflict with this package
    
    Examples
    --------
    >>> dep_type = DependencyType.REQUIRED
    >>> dep_type.value
    'required'
    >>> dep_type.is_optional()
    False
    """
    REQUIRED = "required"
    OPTIONAL = "optional"
    DEVELOPMENT = "development"
    PEER = "peer"
    RECOMMENDED = "recommended"
    EXTRAS = "extras"
    CONFLICT = "conflict"
    
    def is_optional(self) -> bool:
        """
        Check if this dependency type is optional.
        
        Returns
        -------
        bool
            True if optional, False if required
        """
        return self in (DependencyType.OPTIONAL, DependencyType.DEVELOPMENT, 
                       DependencyType.RECOMMENDED)
    
    def priority(self) -> int:
        """
        Get installation priority (higher = more important).
        
        Returns
        -------
        int
            Priority value (5 = highest, 1 = lowest)
        """
        priorities = {
            DependencyType.REQUIRED: 5,
            DependencyType.PEER: 4,
            DependencyType.RECOMMENDED: 3,
            DependencyType.EXTRAS: 2,
            DependencyType.OPTIONAL: 2,
            DependencyType.DEVELOPMENT: 1,
            DependencyType.CONFLICT: 0
        }
        return priorities.get(self, 0)


class OutputFormat(Enum):
    """
    Supported output formats for dependency tree representation.
    
    The tool can generate dependency trees in various formats.
    
    Attributes
    ----------
    TEXT : str
        Human-readable tree structure with ASCII art formatting
    JSON : str
        Structured data suitable for programmatic processing
    YAML : str
        Human-readable structured data format
    DICT : str
        Python dictionary for internal use within other Python code
    HTML : str
        Interactive HTML visualization
    GRAPHVIZ : str
        Graphviz DOT format for graph visualization
    MERMAID : str
        Mermaid format for web-based diagrams
    MARKDOWN : str
        Markdown-formatted tree
    
    Examples
    --------
    >>> fmt = OutputFormat.JSON
    >>> fmt == OutputFormat.JSON
    True
    >>> fmt.is_structured()
    True
    """
    TEXT = "text"
    JSON = "json"
    YAML = "yaml"
    DICT = "dict"
    HTML = "html"
    GRAPHVIZ = "graphviz"
    MERMAID = "mermaid"
    MARKDOWN = "markdown"
    
    def is_structured(self) -> bool:
        """
        Check if format is structured (machine-readable).
        
        Returns
        -------
        bool
            True for JSON, YAML, DICT; False for text formats
        """
        return self in (OutputFormat.JSON, OutputFormat.YAML, OutputFormat.DICT)
    
    def is_visual(self) -> bool:
        """
        Check if format is for visualization.
        
        Returns
        -------
        bool
            True for visualization formats
        """
        return self in (OutputFormat.HTML, OutputFormat.GRAPHVIZ, OutputFormat.MERMAID)


class PackageStatus(Enum):
    """
    Installation status of a package.
    
    Attributes
    ----------
    INSTALLED : str
        Package is installed and available
    NOT_INSTALLED : str
        Package is not installed
    ERROR : str
        Error occurred while checking the package
    CYCLE_DETECTED : str
        Circular dependency detected
    MISMATCH : str
        Version mismatch between requirement and installed
    OUTDATED : str
        Package is installed but outdated
    """
    INSTALLED = "installed"
    NOT_INSTALLED = "not_installed"
    ERROR = "error"
    CYCLE_DETECTED = "cycle_detected"
    MISMATCH = "mismatch"
    OUTDATED = "outdated"
    
    def is_healthy(self) -> bool:
        """Check if status indicates a healthy installation."""
        return self == PackageStatus.INSTALLED
    
    def get_color(self) -> str:
        """Get color code for this status."""
        colors = {
            PackageStatus.INSTALLED: "#27ae60",
            PackageStatus.NOT_INSTALLED: "#f0f0f0",
            PackageStatus.ERROR: "#e74c3c",
            PackageStatus.CYCLE_DETECTED: "#f39c12",
            PackageStatus.MISMATCH: "#e67e22",
            PackageStatus.OUTDATED: "#3498db"
        }
        return colors.get(self, "#95a5a6")


@dataclass
class VersionConstraint:
    """
    Represents a version constraint for package compatibility.
    
    Parameters
    ----------
    operator : str
        Comparison operator (==, >=, >, <=, <, !=, ~=)
    version : str
        Version string
    is_wildcard : bool
        Whether the version contains wildcard
    is_prerelease : bool
        Whether this is a pre-release version
    
    Examples
    --------
    >>> constraint = VersionConstraint(">=", "1.0.0")
    >>> constraint.matches("1.2.0")
    True
    """
    operator: str
    version: str
    is_wildcard: bool = False
    is_prerelease: bool = False
    
    def __post_init__(self):
        """Auto-detect properties after initialization."""
        if ".*" in self.version or "*" in self.version:
            self.is_wildcard = True
        if any(x in self.version.lower() for x in ['a', 'b', 'rc', 'dev', 'pre']):
            self.is_prerelease = True
    
    def matches(self, version: str) -> bool:
        """
        Check if a version matches this constraint.
        
        Parameters
        ----------
        version : str
            Version to check
        
        Returns
        -------
        bool
            True if version matches constraint
        """
        from .._utils import _version_compare
        
        if self.is_wildcard:
            prefix = self.version.split('.*')[0]
            return version.startswith(prefix)
        
        return _version_compare(version, self.operator, self.version)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'operator': self.operator,
            'version': self.version,
            'is_wildcard': self.is_wildcard,
            'is_prerelease': self.is_prerelease,
            'specifier': f"{self.operator}{self.version}"
        }


@dataclass
class PackageInfo:
    """
    Comprehensive information container for a Python package and its dependencies.
    
    This dataclass stores all relevant metadata about a package including its
    dependencies, version information, and relationship context.
    
    Parameters
    ----------
    name : str
        Canonical package name as registered in PyPI
    version : str
        Currently installed version of the package
    requirement : str, optional
        Version requirement specifier from parent package
    status : PackageStatus, optional
        Installation status of the package
    dependencies : List[PackageInfo], optional
        List of direct dependencies of this package
    dep_type : DependencyType, optional
        Classification of dependency importance
    extras : List[str], optional
        Optional extras that trigger this dependency
    metadata : Dict[str, Any], optional
        Additional package metadata
    constraints : List[VersionConstraint], optional
        Parsed version constraints
    depth : int, default=0
        Depth in dependency tree
    parent : Optional[str], optional
        Name of parent package that depends on this
    
    Attributes
    ----------
    name : str
        Package name
    version : str
        Package version
    requirement : str
        Version requirement from parent
    status : PackageStatus
        Installation status
    dependencies : List[PackageInfo]
        Direct dependencies
    dep_type : DependencyType
        Dependency type classification
    extras : List[str]
        Package extras
    metadata : Dict[str, Any]
        Additional metadata
    constraints : List[VersionConstraint]
        Parsed version constraints
    depth : int
        Tree depth
    parent : Optional[str]
        Parent package name
    resolved_version : Optional[str]
        Resolved version after conflict resolution
    
    Examples
    --------
    >>> pkg = PackageInfo(
    ...     name="requests",
    ...     version="2.28.1",
    ...     requirement=">=2.0.0",
    ...     status=PackageStatus.INSTALLED
    ... )
    >>> pkg.name
    'requests'
    >>> pkg.is_installed()
    True
    """
    name: str
    version: str
    requirement: str = ""
    status: PackageStatus = PackageStatus.INSTALLED
    dependencies: List["PackageInfo"] = field(default_factory=list)
    dep_type: DependencyType = DependencyType.REQUIRED
    extras: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    constraints: List[VersionConstraint] = field(default_factory=list)
    depth: int = 0
    parent: Optional[str] = None
    resolved_version: Optional[str] = None
    
    def __post_init__(self):
        """Initialize derived fields after creation."""
        # Parse constraints if version spec is provided
        if self.requirement and not self.constraints:
            self.constraints = self._parse_constraints(self.requirement)
        
        # Set resolved version if not provided
        if self.resolved_version is None and self.version:
            self.resolved_version = self.version
    
    def _parse_constraints(self, requirement: str) -> List[VersionConstraint]:
        """
        Parse requirement string into version constraints.
        
        Parameters
        ----------
        requirement : str
            Requirement string
        
        Returns
        -------
        List[VersionConstraint]
            List of parsed constraints
        """
        constraints = []
        pattern = r'([<>=!~]=?)\s*([a-zA-Z0-9.*]+(?:\.[a-zA-Z0-9.*]+)*)'
        
        for match in re.finditer(pattern, requirement):
            operator = match.group(1)
            version = match.group(2)
            constraints.append(VersionConstraint(operator, version))
        
        return constraints
    
    def is_installed(self) -> bool:
        """Check if package is installed and healthy."""
        return self.status == PackageStatus.INSTALLED
    
    def has_conflicts(self) -> bool:
        """Check if package has any conflicts."""
        return self.status == PackageStatus.MISMATCH
    
    def is_circular(self) -> bool:
        """Check if this represents a circular dependency."""
        return self.status == PackageStatus.CYCLE_DETECTED
    
    def matches_requirement(self) -> bool:
        """
        Check if installed version matches requirement.
        
        Returns
        -------
        bool
            True if version matches requirements
        """
        if not self.constraints:
            return True
        
        for constraint in self.constraints:
            if not constraint.matches(self.version):
                return False
        return True
    
    def find_dependency(self, name: str) -> Optional["PackageInfo"]:
        """
        Find a direct dependency by name.
        
        Parameters
        ----------
        name : str
            Name of dependency to find
        
        Returns
        -------
        Optional[PackageInfo]
            Found dependency or None
        """
        for dep in self.dependencies:
            if dep.name == name:
                return dep
        return None
    
    def get_all_dependencies(self, include_optional: bool = False) -> List["PackageInfo"]:
        """
        Get all transitive dependencies recursively.
        
        Parameters
        ----------
        include_optional : bool, default=False
            Whether to include optional dependencies
        
        Returns
        -------
        List[PackageInfo]
            List of all dependencies (flattened)
        """
        all_deps = []
        visited = set()
        
        def collect(dep: "PackageInfo"):
            if dep.name in visited:
                return
            visited.add(dep.name)
            
            if include_optional or not dep.dep_type.is_optional():
                all_deps.append(dep)
            
            for child in dep.dependencies:
                collect(child)
        
        for dep in self.dependencies:
            collect(dep)
        
        return all_deps
    
    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """
        Build a dependency graph as adjacency list.
        
        Returns
        -------
        Dict[str, List[str]]
            Graph representation
        """
        graph = defaultdict(list)
        
        def build(node: PackageInfo):
            if node.name not in graph:
                graph[node.name] = []
            for dep in node.dependencies:
                graph[node.name].append(dep.name)
                build(dep)
        
        build(self)
        return dict(graph)
    
    def detect_cycles(self) -> List[List[str]]:
        """
        Detect circular dependencies in the tree.
        
        Returns
        -------
        List[List[str]]
            List of cycles found (each cycle is list of package names)
        """
        graph = self.get_dependency_graph()
        cycles = []
        visited = set()
        rec_stack = set()
        
        def dfs(node: str, path: List[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path.copy())
                elif neighbor in rec_stack:
                    # Cycle detected
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)
            
            rec_stack.remove(node)
        
        for node in graph:
            if node not in visited:
                dfs(node, [])
        
        return cycles
    
    def get_size(self) -> int:
        """
        Get total number of nodes in tree.
        
        Returns
        -------
        int
            Total node count including this node
        """
        return 1 + sum(dep.get_size() for dep in self.dependencies)
    
    def get_depth(self, current_depth: int = 0) -> int:
        """
        Get maximum depth of dependency tree.
        
        Returns
        -------
        int
            Maximum depth
        """
        if not self.dependencies:
            return current_depth
        return max(dep.get_depth(current_depth + 1) for dep in self.dependencies)
    
    def to_dict(self, include_metadata: bool = True) -> Dict[str, Any]:
        """
        Convert to dictionary representation.
        
        Parameters
        ----------
        include_metadata : bool, default=True
            Whether to include metadata field
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation
        """
        result = {
            'name': self.name,
            'version': self.version,
            'requirement': self.requirement,
            'status': self.status.value,
            'dep_type': self.dep_type.value,
            'extras': self.extras,
            'depth': self.depth,
            'parent': self.parent,
            'resolved_version': self.resolved_version,
            'dependencies': [dep.to_dict(include_metadata) for dep in self.dependencies],
            'constraints': [c.to_dict() for c in self.constraints] if self.constraints else []
        }
        
        if include_metadata:
            result['metadata'] = self.metadata
        
        return result
    
    def to_json(self, indent: int = 2, include_metadata: bool = True) -> str:
        """
        Convert to JSON string.
        
        Parameters
        ----------
        indent : int, default=2
            Indentation level
        include_metadata : bool, default=True
            Whether to include metadata
        
        Returns
        -------
        str
            JSON representation
        """
        return json.dumps(self.to_dict(include_metadata), indent=indent, default=str)
    
    def clone(self) -> "PackageInfo":
        """
        Create a deep copy of this package and its dependencies.
        
        Returns
        -------
        PackageInfo
            Cloned package info
        """
        return copy.deepcopy(self)
    
    def merge(self, other: "PackageInfo") -> "PackageInfo":
        """
        Merge two PackageInfo instances (for conflict resolution).
        
        Parameters
        ----------
        other : PackageInfo
            Other package info to merge
        
        Returns
        -------
        PackageInfo
            Merged package info
        """
        if self.name != other.name:
            raise ValueError(f"Cannot merge different packages: {self.name} != {other.name}")
        
        # Use more specific status
        status_priority = {
            PackageStatus.ERROR: 1,
            PackageStatus.CYCLE_DETECTED: 2,
            PackageStatus.MISMATCH: 3,
            PackageStatus.OUTDATED: 4,
            PackageStatus.NOT_INSTALLED: 5,
            PackageStatus.INSTALLED: 6
        }
        
        merged_status = self.status
        if status_priority.get(other.status, 0) > status_priority.get(merged_status, 0):
            merged_status = other.status
        
        # Merge dependencies (deduplicate)
        deps_dict = {dep.name: dep for dep in self.dependencies}
        for dep in other.dependencies:
            if dep.name in deps_dict:
                deps_dict[dep.name] = deps_dict[dep.name].merge(dep)
            else:
                deps_dict[dep.name] = dep
        
        # Merge metadata
        merged_metadata = {**self.metadata, **other.metadata}
        
        return PackageInfo(
            name=self.name,
            version=self.version,
            requirement=self.requirement or other.requirement,
            status=merged_status,
            dependencies=list(deps_dict.values()),
            dep_type=self.dep_type,
            extras=list(set(self.extras + other.extras)),
            metadata=merged_metadata,
            constraints=self.constraints + other.constraints,
            depth=min(self.depth, other.depth),
            parent=self.parent or other.parent,
            resolved_version=self.resolved_version or other.resolved_version
        )
    
    def resolve_conflicts(self) -> Dict[str, Any]:
        """
        Resolve version conflicts in dependency tree.
        
        Returns
        -------
        Dict[str, Any]
            Conflict resolution report
        """
        conflicts = {}
        
        def collect_versions(node: PackageInfo, versions: Dict[str, List[str]]):
            if node.name not in versions:
                versions[node.name] = []
            versions[node.name].append(node.version)
            for dep in node.dependencies:
                collect_versions(dep, versions)
        
        all_versions: Dict[str, List[str]] = {}
        collect_versions(self, all_versions)
        
        for pkg_name, versions in all_versions.items():
            unique_versions = set(versions)
            if len(unique_versions) > 1:
                conflicts[pkg_name] = {
                    'versions': list(unique_versions),
                    'conflict': True,
                    'suggestion': max(unique_versions, key=lambda v: [int(x) for x in v.split('.') if x.isdigit()])
                }
        
        return conflicts
    
    def prune(self, max_depth: Optional[int] = None, 
              include_optional: bool = False) -> "PackageInfo":
        """
        Prune dependency tree by depth or optional status.
        
        Parameters
        ----------
        max_depth : int, optional
            Maximum depth to keep
        include_optional : bool, default=False
            Whether to keep optional dependencies
        
        Returns
        -------
        PackageInfo
            Pruned package info
        """
        if max_depth is not None and self.depth >= max_depth:
            pruned_deps = []
        else:
            pruned_deps = [
                dep.prune(max_depth, include_optional)
                for dep in self.dependencies
                if include_optional or not dep.dep_type.is_optional()
            ]
        
        return replace(self, dependencies=pruned_deps)
    
    def get_hash(self) -> str:
        """
        Generate a hash for this package tree.
        
        Returns
        -------
        str
            SHA256 hash of the tree
        """
        tree_str = json.dumps(self.to_dict(include_metadata=False), sort_keys=True)
        return hashlib.sha256(tree_str.encode()).hexdigest()
    
    def __eq__(self, other: object) -> bool:
        """Check equality of two PackageInfo objects."""
        if not isinstance(other, PackageInfo):
            return False
        return self.name == other.name and self.version == other.version
    
    def __hash__(self) -> int:
        """Generate hash for PackageInfo."""
        return hash((self.name, self.version))


@dataclass
class RequirementInfo:
    """
    Parsed requirement information following PEP 508 specification.
    
    Parameters
    ----------
    name : str or None
        Normalized package name, None if parsing fails
    version_spec : str
        Version requirement specification
    extras : List[str]
        List of optional extras requested
    marker : str
        Environment marker condition string
    metadata : dict
        Additional parsed metadata
    constraints : List[VersionConstraint]
        Parsed version constraints
    
    Attributes
    ----------
    name : str or None
        Package name
    version_spec : str
        Version specification
    extras : List[str]
        Requested extras
    marker : str
        Environment marker
    metadata : dict
        Additional metadata
    constraints : List[VersionConstraint]
        Parsed constraints
    is_valid : bool
        Whether requirement is valid
    
    Examples
    --------
    >>> req = RequirementInfo.from_string("requests[security]>=2.8.1")
    >>> req.name
    'requests'
    >>> req.extras
    ['security']
    >>> req.is_valid
    True
    """
    name: Optional[str]
    version_spec: str
    extras: List[str]
    marker: str
    metadata: dict = field(default_factory=dict)
    constraints: List[VersionConstraint] = field(default_factory=list)
    
    def __post_init__(self):
        """Parse constraints after initialization."""
        if not self.constraints and self.version_spec:
            self.constraints = self._parse_constraints()
    
    def _parse_constraints(self) -> List[VersionConstraint]:
        """Parse version spec into constraints."""
        constraints = []
        pattern = r'([<>=!~]=?)\s*([a-zA-Z0-9.*]+(?:\.[a-zA-Z0-9.*]+)*)'
        
        for match in re.finditer(pattern, self.version_spec):
            operator = match.group(1)
            version = match.group(2)
            constraints.append(VersionConstraint(operator, version))
        
        return constraints
    
    @property
    def is_valid(self) -> bool:
        """Check if requirement is valid."""
        return self.name is not None and bool(self.name)
    
    @property
    def has_extras(self) -> bool:
        """Check if requirement has extras."""
        return len(self.extras) > 0
    
    @property
    def has_marker(self) -> bool:
        """Check if requirement has environment marker."""
        return bool(self.marker)
    
    @property
    def has_version_spec(self) -> bool:
        """Check if requirement has version specification."""
        return bool(self.version_spec)
    
    def matches_environment(self, environment: Optional[Dict[str, Any]] = None) -> Optional[bool]:
        """
        Check if environment marker matches given environment.
        
        Parameters
        ----------
        environment : Dict[str, Any], optional
            Environment to evaluate against
        
        Returns
        -------
        Optional[bool]
            True if marker matches, False if not, None if no marker or evaluation fails
        """
        if not self.has_marker:
            return None
        
        try:
            from .._utils import _evaluate_marker
            return _evaluate_marker(self.marker, environment)
        except Exception:
            return None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary representation.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation
        """
        return {
            'name': self.name,
            'version_spec': self.version_spec,
            'extras': self.extras,
            'marker': self.marker,
            'metadata': self.metadata,
            'constraints': [c.to_dict() for c in self.constraints],
            'is_valid': self.is_valid,
            'has_extras': self.has_extras,
            'has_marker': self.has_marker,
            'has_version_spec': self.has_version_spec
        }
    
    @classmethod
    def from_string(cls, requirement: str) -> "RequirementInfo":
        """
        Create RequirementInfo from a requirement string.
        
        Parameters
        ----------
        requirement : str
            PEP 508 requirement string
        
        Returns
        -------
        RequirementInfo
            Parsed requirement information
        
        Examples
        --------
        >>> req = RequirementInfo.from_string("django>=3.2; python_version>'3.6'")
        >>> req.name
        'django'
        >>> req.marker
        "python_version>'3.6'"
        """
        try:
            from .parser_enhanced import parse_requirement_enhanced
            name, version_spec, extras, marker, metadata = parse_requirement_enhanced(requirement)
            return cls(name, version_spec, extras, marker, metadata)
        except ImportError:
            # Fallback to basic parser
            from .parser import parse_requirement_enhanced as parse_basic
            name, version_spec, extras, marker, metadata = parse_basic(requirement)
            return cls(name, version_spec, extras, marker, metadata)
    
    def __repr__(self) -> str:
        """String representation of requirement."""
        return f"<RequirementInfo {self.name}{self.version_spec}>"


@dataclass
class DependencyTreeStats:
    """
    Statistics about a dependency tree.
    
    Parameters
    ----------
    total_nodes : int
        Total number of packages in tree
    unique_packages : int
        Number of unique packages
    max_depth : int
        Maximum depth of tree
    circular_dependencies : int
        Number of circular dependencies found
    version_conflicts : int
        Number of version conflicts
    optional_deps : int
        Number of optional dependencies
    development_deps : int
        Number of development dependencies
    required_deps : int
        Number of required dependencies
    """
    total_nodes: int = 0
    unique_packages: int = 0
    max_depth: int = 0
    circular_dependencies: int = 0
    version_conflicts: int = 0
    optional_deps: int = 0
    development_deps: int = 0
    required_deps: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'total_nodes': self.total_nodes,
            'unique_packages': self.unique_packages,
            'max_depth': self.max_depth,
            'circular_dependencies': self.circular_dependencies,
            'version_conflicts': self.version_conflicts,
            'optional_dependencies': self.optional_deps,
            'development_dependencies': self.development_deps,
            'required_dependencies': self.required_deps
        }
    
    def calculate_from_tree(self, tree: PackageInfo) -> "DependencyTreeStats":
        """
        Calculate statistics from a dependency tree.
        
        Parameters
        ----------
        tree : PackageInfo
            Dependency tree
        
        Returns
        -------
        DependencyTreeStats
            Updated stats
        """
        unique_packages = set()
        
        def traverse(node: PackageInfo, depth: int):
            if node.name in unique_packages:
                self.circular_dependencies += 1
            
            unique_packages.add(node.name)
            self.total_nodes += 1
            self.max_depth = max(self.max_depth, depth)
            
            if node.dep_type == DependencyType.REQUIRED:
                self.required_deps += 1
            elif node.dep_type == DependencyType.OPTIONAL:
                self.optional_deps += 1
            elif node.dep_type == DependencyType.DEVELOPMENT:
                self.development_deps += 1
            
            for dep in node.dependencies:
                traverse(dep, depth + 1)
        
        traverse(tree, 0)
        self.unique_packages = len(unique_packages)
        
        # Detect version conflicts
        all_versions = defaultdict(set)
        def collect_versions(node: PackageInfo):
            all_versions[node.name].add(node.version)
            for dep in node.dependencies:
                collect_versions(dep)
        collect_versions(tree)
        
        self.version_conflicts = sum(1 for versions in all_versions.values() if len(versions) > 1)
        
        return self
    
    def __repr__(self) -> str:
        """String representation of stats."""
        return (f"<DependencyTreeStats: {self.total_nodes} nodes, "
                f"{self.unique_packages} unique, depth {self.max_depth}>")


# Import re for parsing (moved to avoid circular import)
import re
import warnings

# Add version comparison fallback
def _version_compare(version1: str, operator: str, version2: str) -> bool:
    """
    Compare two versions (fallback when packaging not available).
    
    Parameters
    ----------
    version1 : str
        First version
    operator : str
        Comparison operator
    version2 : str
        Second version
    
    Returns
    -------
    bool
        Comparison result
    """
    def normalize(v: str) -> List[Union[int, str]]:
        parts = []
        for part in re.split(r'[.-]', v):
            try:
                parts.append(int(part))
            except ValueError:
                parts.append(part)
        return parts
    
    try:
        v1 = normalize(version1)
        v2 = normalize(version2)
        
        if operator == '==':
            return v1 == v2
        elif operator == '>=':
            return v1 >= v2
        elif operator == '>':
            return v1 > v2
        elif operator == '<=':
            return v1 <= v2
        elif operator == '<':
            return v1 < v2
        elif operator == '!=':
            return v1 != v2
        elif operator == '~=':
            return v1[0] == v2[0] and v1 >= v2
        return False
    except Exception:
        return False


def _evaluate_marker(marker: str, environment: Optional[Dict[str, Any]] = None) -> bool:
    """
    Evaluate environment marker (fallback when packaging not available).
    
    Parameters
    ----------
    marker : str
        Marker expression
    environment : Dict[str, Any], optional
        Environment to evaluate against
    
    Returns
    -------
    bool
        Evaluation result
    """
    import platform
    import sys
    
    if environment is None:
        environment = {
            'python_version': f"{sys.version_info.major}.{sys.version_info.minor}",
            'platform_system': platform.system(),
            'sys_platform': sys.platform,
        }
    
    # Simple evaluation logic
    marker_lower = marker.lower()
    for var, value in environment.items():
        if var in marker_lower:
            if isinstance(value, str):
                marker = marker.replace(var, f"'{value}'")
            else:
                marker = marker.replace(var, str(value))
    
    try:
        # Safely evaluate
        safe_globals = {'__builtins__': {'True': True, 'False': False}}
        return bool(eval(marker, safe_globals, {}))
    except Exception:
        return False


# Module-level warnings
def _check_imports():
    """Check for optional imports and warn if not available."""
    try:
        import packaging.version
        import packaging.specifiers
    except ImportError:
        warnings.warn(
            "packaging library not found. Using built-in fallbacks for "
            "version comparison and marker evaluation. Install packaging "
            "for better performance: pip install packaging",
            UserWarning,
            stacklevel=2
        )


_check_imports()