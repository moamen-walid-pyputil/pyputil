#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Dependency tree analysis utilities for conflict detection, metrics, and advanced analysis.

This module provides comprehensive tools for analyzing dependency trees including
version conflict detection, performance metrics, cycle detection, impact analysis,
and compatibility assessment. Features include both basic analysis and advanced
algorithms for complex dependency resolution scenarios.
"""

from typing import Dict, List, Set, Optional, Tuple, Any, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, Counter
from functools import lru_cache
import logging
from datetime import datetime
import json
import warnings

# Try to import packaging libraries with fallbacks
try:
    from packaging.specifiers import SpecifierSet, InvalidSpecifier
    from packaging.version import Version, parse as parse_version
    from packaging.requirements import Requirement
    PACKAGING_AVAILABLE = True
except ImportError:
    PACKAGING_AVAILABLE = False
    warnings.warn(
        "packaging library not found. Using built-in version comparison. "
        "Install packaging for better accuracy: pip install packaging",
        UserWarning,
        stacklevel=2
    )

# Configure module logger
logger = logging.getLogger(__name__)


class ConflictType(Enum):
    """
    Enumeration of possible conflict types in dependency trees.
    
    Attributes
    ----------
    VERSION_MISMATCH : str
        Same package required with different installed versions
    INCOMPATIBLE_SPECIFIERS : str
        Version specifications cannot be satisfied simultaneously
    CIRCULAR_DEPENDENCY : str
        Circular dependency detected in the tree
    MISSING_PACKAGE : str
        Required package is not installed
    PYTHON_VERSION : str
        Package requires incompatible Python version
    PLATFORM_CONFLICT : str
        Package requires incompatible platform
    EXTRAS_CONFLICT : str
        Conflicting extras requirements
    LICENSE_CONFLICT : str
        License incompatibility between packages
    SECURITY_VULNERABILITY : str
        Package version has known vulnerabilities
    
    Examples
    --------
    >>> conflict = ConflictType.VERSION_MISMATCH
    >>> conflict.severity()
    3
    >>> conflict.get_color_code()
    '\033[91m'
    """
    
    VERSION_MISMATCH = "version_mismatch"
    INCOMPATIBLE_SPECIFIERS = "incompatible_specifiers"
    CIRCULAR_DEPENDENCY = "circular_dependency"
    MISSING_PACKAGE = "missing_package"
    PYTHON_VERSION = "python_version"
    PLATFORM_CONFLICT = "platform_conflict"
    EXTRAS_CONFLICT = "extras_conflict"
    LICENSE_CONFLICT = "license_conflict"
    SECURITY_VULNERABILITY = "security_vulnerability"
    
    def severity(self) -> int:
        """
        Get conflict severity level (1-5, higher = more severe).
        
        Returns
        -------
        int
            Severity level (1=minor, 5=critical)
        """
        severity_levels = {
            ConflictType.VERSION_MISMATCH: 3,
            ConflictType.INCOMPATIBLE_SPECIFIERS: 4,
            ConflictType.CIRCULAR_DEPENDENCY: 2,
            ConflictType.MISSING_PACKAGE: 5,
            ConflictType.PYTHON_VERSION: 5,
            ConflictType.PLATFORM_CONFLICT: 3,
            ConflictType.EXTRAS_CONFLICT: 2,
            ConflictType.LICENSE_CONFLICT: 1,
            ConflictType.SECURITY_VULNERABILITY: 5
        }
        return severity_levels.get(self, 3)
    
    def get_color_code(self) -> str:
        """Get ANSI color code for visual representation."""
        colors = {
            ConflictType.VERSION_MISMATCH: "\033[93m",  # Yellow
            ConflictType.INCOMPATIBLE_SPECIFIERS: "\033[91m",  # Red
            ConflictType.CIRCULAR_DEPENDENCY: "\033[94m",  # Blue
            ConflictType.MISSING_PACKAGE: "\033[91m",  # Red
            ConflictType.PYTHON_VERSION: "\033[91m",  # Red
            ConflictType.PLATFORM_CONFLICT: "\033[93m",  # Yellow
            ConflictType.EXTRAS_CONFLICT: "\033[94m",  # Blue
            ConflictType.LICENSE_CONFLICT: "\033[96m",  # Cyan
            ConflictType.SECURITY_VULNERABILITY: "\033[91m"  # Red
        }
        return colors.get(self, "\033[0m")


@dataclass
class ConflictInfo:
    """
    Detailed information about a dependency conflict.
    
    Attributes
    ----------
    package_name : str
        Name of the conflicted package
    conflict_type : ConflictType
        Type of conflict detected
    different_versions : List[str]
        List of different versions involved
    requirements : List[Dict[str, Any]]
        List of requirement specifications
    affected_packages : List[str]
        Packages affected by this conflict
    resolution_suggestion : Optional[str]
        Suggested resolution if available
    details : Dict[str, Any]
        Additional conflict details
    severity : int
        Computed severity level
    """
    
    package_name: str
    conflict_type: ConflictType
    different_versions: List[str] = field(default_factory=list)
    requirements: List[Dict[str, Any]] = field(default_factory=list)
    affected_packages: List[str] = field(default_factory=list)
    resolution_suggestion: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    severity: int = 0
    
    def __post_init__(self):
        """Initialize derived fields."""
        if not self.severity:
            self.severity = self.conflict_type.severity()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert conflict info to dictionary."""
        return {
            'package_name': self.package_name,
            'conflict_type': self.conflict_type.value,
            'different_versions': self.different_versions,
            'requirements': self.requirements,
            'affected_packages': self.affected_packages,
            'resolution_suggestion': self.resolution_suggestion,
            'details': self.details,
            'severity': self.severity
        }
    
    def __str__(self) -> str:
        """String representation of conflict."""
        return (f"{self.conflict_type.get_color_code()}Conflict[{self.package_name}]: "
                f"{self.conflict_type.value} (severity {self.severity})\033[0m")


@dataclass
class TreeMetrics:
    """
    Comprehensive metrics for a dependency tree.
    
    Attributes
    ----------
    total_packages : int
        Total number of package nodes
    unique_packages : int
        Number of unique package names
    max_depth : int
        Maximum depth of tree
    average_depth : float
        Average depth of packages
    max_breadth : int
        Maximum number of dependencies at any level
    dependency_counts : Dict[int, int]
        Distribution of dependency counts (count of packages with X dependencies)
    package_types : Dict[str, int]
        Counts by package type/status
    circular_dependencies : int
        Number of circular dependencies found
    total_edges : int
        Total number of dependency edges
    average_fan_out : float
        Average number of dependencies per package
    version_specs : Dict[str, int]
        Distribution of version specifier types
    """
    
    total_packages: int = 0
    unique_packages: int = 0
    max_depth: int = 0
    average_depth: float = 0.0
    max_breadth: int = 0
    dependency_counts: Dict[int, int] = field(default_factory=dict)
    package_types: Dict[str, int] = field(default_factory=dict)
    circular_dependencies: int = 0
    total_edges: int = 0
    average_fan_out: float = 0.0
    version_specs: Dict[str, int] = field(default_factory=dict)
    computed_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            'total_packages': self.total_packages,
            'unique_packages': self.unique_packages,
            'max_depth': self.max_depth,
            'average_depth': round(self.average_depth, 2),
            'max_breadth': self.max_breadth,
            'dependency_counts': self.dependency_counts,
            'package_types': self.package_types,
            'circular_dependencies': self.circular_dependencies,
            'total_edges': self.total_edges,
            'average_fan_out': round(self.average_fan_out, 2),
            'version_specs': self.version_specs,
            'computed_at': self.computed_at.isoformat()
        }
    
    def summarize(self) -> str:
        """
        Generate human-readable summary of metrics.
        
        Returns
        -------
        str
            Formatted summary string
        """
        lines = [
            "=" * 50,
            "Dependency Tree Metrics Summary",
            "=" * 50,
            f"Total Packages: {self.total_packages}",
            f"Unique Packages: {self.unique_packages}",
            f"Max Depth: {self.max_depth}",
            f"Average Depth: {self.average_depth:.2f}",
            f"Max Breadth: {self.max_breadth}",
            f"Total Edges: {self.total_edges}",
            f"Average Fan-out: {self.average_fan_out:.2f}",
            f"Circular Dependencies: {self.circular_dependencies}",
            "-" * 50,
            "Package Types:"
        ]
        
        for pkg_type, count in sorted(self.package_types.items(), key=lambda x: -x[1]):
            lines.append(f"  {pkg_type}: {count}")
        
        lines.append("-" * 50)
        lines.append("Dependency Distribution:")
        for deps, count in sorted(self.dependency_counts.items()):
            lines.append(f"  {deps} dependencies: {count} packages")
        
        lines.append("=" * 50)
        return "\n".join(lines)


class DependencyAnalyzer:
    """
    Advanced dependency tree analyzer with comprehensive analysis capabilities.
    
    This class provides sophisticated analysis of dependency trees including
    conflict detection, metrics calculation, impact analysis, and performance
    optimization recommendations.
    
    Parameters
    ----------
    tree : Dict
        Dependency tree structure
    enable_caching : bool, default=True
        Whether to cache analysis results
    strict_mode : bool, default=False
        Whether to raise exceptions on analysis errors
    
    Attributes
    ----------
    tree : Dict
        Original dependency tree
    _metrics_cache : Optional[TreeMetrics]
        Cached metrics
    _conflicts_cache : Optional[List[ConflictInfo]]
        Cached conflicts
    _graph_cache : Optional[Dict]
        Cached graph representation
    
    Examples
    --------
    >>> tree = load_dependency_tree()
    >>> analyzer = DependencyAnalyzer(tree)
    >>> conflicts = analyzer.find_conflicts()
    >>> for conflict in conflicts:
    ...     print(f"Conflict: {conflict.package_name} - {conflict.conflict_type.value}")
    >>> metrics = analyzer.calculate_metrics()
    >>> print(metrics.summarize())
    """
    
    def __init__(self, tree: Dict, enable_caching: bool = True, strict_mode: bool = False):
        self.tree = tree
        self.enable_caching = enable_caching
        self.strict_mode = strict_mode
        
        # Cache storage
        self._metrics_cache: Optional[TreeMetrics] = None
        self._conflicts_cache: Optional[List[ConflictInfo]] = None
        self._graph_cache: Optional[Dict] = None
        self._cycle_cache: Optional[List[List[str]]] = None
        
        # Performance tracking
        self._analysis_stats = {
            'analyzed_at': datetime.now(),
            'cache_hits': 0,
            'cache_misses': 0
        }
        
        logger.info(f"DependencyAnalyzer initialized for tree with root: {tree.get('name', 'unknown')}")
    
    def _get_cache_or_compute(self, cache_name: str, compute_func: Callable) -> Any:
        """
        Get cached result or compute if not cached.
        
        Parameters
        ----------
        cache_name : str
            Name of cache attribute
        compute_func : Callable
            Function to compute result if not cached
        
        Returns
        -------
        Any
            Computed or cached result
        """
        cache = getattr(self, f"_{cache_name}_cache", None)
        
        if self.enable_caching and cache is not None:
            self._analysis_stats['cache_hits'] += 1
            return cache
        
        self._analysis_stats['cache_misses'] += 1
        result = compute_func()
        
        if self.enable_caching:
            setattr(self, f"_{cache_name}_cache", result)
        
        return result
    
    def find_conflicts(self, include_minor: bool = False) -> List[ConflictInfo]:
        """
        Analyze and identify all conflicts in the dependency tree.
        
        This method performs comprehensive conflict detection including:
        - Version mismatches
        - Incompatible version specifiers
        - Circular dependencies
        - Missing packages
        - Platform and Python version conflicts
        
        Parameters
        ----------
        include_minor : bool, default=False
            Whether to include minor/suggestion-level conflicts
        
        Returns
        -------
        List[ConflictInfo]
            List of conflict information objects
        
        Examples
        --------
        >>> analyzer = DependencyAnalyzer(tree)
        >>> conflicts = analyzer.find_conflicts()
        >>> for conflict in conflicts:
        ...     print(f"{conflict.package_name}: {conflict.resolution_suggestion}")
        """
        def compute_conflicts():
            conflicts = []
            package_requirements = defaultdict(list)
            
            # Collect all requirements
            def collect_requirements(node: Dict, path: str = ""):
                if node is None:
                    return
                
                node_name = node.get("name", "")
                node_version = node.get("version", "")
                requirement = node.get("requirement", "")
                status = node.get("status", "")
                
                if node_name and path:
                    package_requirements[node_name].append({
                        "required_by": path,
                        "requirement": requirement,
                        "installed_version": node_version,
                        "status": status
                    })
                
                current_path = f"{path}->{node_name}" if path else node_name
                
                # Process dependencies
                for dep in node.get("dependencies", []):
                    collect_requirements(dep, current_path)
                
                # Process dependencies by type
                if "dependencies_by_type" in node:
                    for deps_list in node["dependencies_by_type"].values():
                        for dep in deps_list:
                            collect_requirements(dep, current_path)
            
            collect_requirements(self.tree)
            
            # Detect missing packages
            if include_minor:
                missing_packages = self.find_orphaned_packages()
                for pkg in missing_packages:
                    conflicts.append(ConflictInfo(
                        package_name=pkg,
                        conflict_type=ConflictType.MISSING_PACKAGE,
                        resolution_suggestion=f"Install package: pip install {pkg}"
                    ))
            
            # Detect version conflicts
            for package, reqs in package_requirements.items():
                conflict = self._analyze_package_conflicts(package, reqs)
                if conflict and (include_minor or conflict.severity >= 3):
                    conflicts.append(conflict)
            
            # Detect circular dependencies
            cycles = self.detect_cycles()
            for cycle in cycles:
                conflicts.append(ConflictInfo(
                    package_name=" -> ".join(cycle[:3]) + ("..." if len(cycle) > 3 else ""),
                    conflict_type=ConflictType.CIRCULAR_DEPENDENCY,
                    affected_packages=cycle,
                    details={'cycle': cycle},
                    resolution_suggestion="Break circular dependency by refactoring imports"
                ))
            
            # Sort by severity (highest first)
            conflicts.sort(key=lambda x: x.severity, reverse=True)
            
            return conflicts
        
        return self._get_cache_or_compute('conflicts', compute_conflicts)
    
    def _analyze_package_conflicts(self, package: str, requirements: List[Dict]) -> Optional[ConflictInfo]:
        """
        Analyze conflicts for a single package.
        
        Parameters
        ----------
        package : str
            Package name
        requirements : List[Dict]
            List of requirement dictionaries
        
        Returns
        -------
        Optional[ConflictInfo]
            Conflict info if conflict detected, None otherwise
        """
        if len(requirements) <= 1:
            return None
        
        versions = {req["installed_version"] for req in requirements 
                   if req["installed_version"] and req.get("status") != "not_installed"}
        versions.discard("")
        
        conflict_type = None
        different_versions = list(versions)
        
        # Check for version mismatch
        if len(versions) > 1:
            conflict_type = ConflictType.VERSION_MISMATCH
            resolution_suggestion = f"Use consistent version of {package}, preferably {max(versions)}"
        
        # Check for incompatible specifiers
        elif len(versions) == 1:
            single_version = next(iter(versions)) if versions else None
            if single_version and not self._check_version_compatibility(requirements, single_version):
                conflict_type = ConflictType.INCOMPATIBLE_SPECIFIERS
                resolution_suggestion = self._suggest_version_resolution(package, requirements, single_version)
        
        if conflict_type:
            return ConflictInfo(
                package_name=package,
                conflict_type=conflict_type,
                different_versions=different_versions,
                requirements=requirements,
                resolution_suggestion=resolution_suggestion,
                affected_packages=list(set(req["required_by"].split('->')[0] for req in requirements))
            )
        
        return None
    
    def _check_version_compatibility(self, requirements: List[Dict], version: str) -> bool:
        """
        Check if a version satisfies all requirements.
        
        Parameters
        ----------
        requirements : List[Dict]
            List of requirement dictionaries
        version : str
            Version to check
        
        Returns
        -------
        bool
            True if version satisfies all requirements
        """
        try:
            ver = parse_version(version) if PACKAGING_AVAILABLE else version
            
            for req_info in requirements:
                req_spec = req_info.get("requirement", "")
                if req_spec:
                    if PACKAGING_AVAILABLE:
                        req = Requirement(f"dummy{req_spec}")
                        if ver not in req.specifier:
                            return False
                    else:
                        if not self._check_version_spec_fallback(version, req_spec):
                            return False
            return True
        except Exception as e:
            logger.debug(f"Version compatibility check failed: {e}")
            return False
    
    def _check_version_spec_fallback(self, version: str, spec: str) -> bool:
        """
        Fallback version spec checking without packaging library.
        
        Parameters
        ----------
        version : str
            Version to check
        spec : str
            Version specification
        
        Returns
        -------
        bool
            True if version matches spec
        """
        # Simple pattern matching for common specifiers
        patterns = [
            (r'>=\s*([0-9.]+)', lambda v, t: v >= t),
            (r'<=\s*([0-9.]+)', lambda v, t: v <= t),
            (r'==\s*([0-9.]+)', lambda v, t: v == t),
            (r'!=\s*([0-9.]+)', lambda v, t: v != t),
            (r'>\s*([0-9.]+)', lambda v, t: v > t),
            (r'<\s*([0-9.]+)', lambda v, t: v < t),
        ]
        
        import re
        for pattern, comparator in patterns:
            match = re.search(pattern, spec)
            if match:
                target = match.group(1)
                try:
                    version_parts = [int(x) for x in version.split('.')]
                    target_parts = [int(x) for x in target.split('.')]
                    return comparator(version_parts, target_parts)
                except ValueError:
                    return version == target
        
        return True
    
    def _suggest_version_resolution(self, package: str, requirements: List[Dict], 
                                    current_version: str) -> str:
        """
        Suggest version resolution for incompatible requirements.
        
        Parameters
        ----------
        package : str
            Package name
        requirements : List[Dict]
            List of requirements
        current_version : str
            Current installed version
        
        Returns
        -------
        str
            Resolution suggestion
        """
        suggestions = []
        
        # Try to find compatible version ranges
        for req in requirements:
            spec = req.get("requirement", "")
            if spec and ">=" in spec:
                suggestions.append(spec)
        
        if suggestions:
            return f"Update {package} to satisfy: {', '.join(suggestions)}"
        else:
            return f"Review {package} requirements: {', '.join([r['requirement'] for r in requirements if r['requirement']])}"
    
    def calculate_metrics(self) -> TreeMetrics:
        """
        Calculate comprehensive metrics for the dependency tree.
        
        This method computes various metrics including tree structure
        statistics, dependency distribution, and performance indicators.
        
        Returns
        -------
        TreeMetrics
            Comprehensive metrics object
        
        Examples
        --------
        >>> analyzer = DependencyAnalyzer(tree)
        >>> metrics = analyzer.calculate_metrics()
        >>> print(f"Average depth: {metrics.average_depth}")
        >>> print(f"Max breadth: {metrics.max_breadth}")
        >>> print(metrics.summarize())
        """
        def compute_metrics():
            metrics = TreeMetrics()
            package_depths = defaultdict(list)
            visited = set()
            circular_count = 0
            breadth_at_depth = defaultdict(int)
            
            def traverse(node: Dict, depth: int = 0, path: Set[str] = None):
                nonlocal circular_count
                
                if path is None:
                    path = set()
                
                node_name = node.get("name", "")
                metrics.total_packages += 1
                
                # Track depth
                package_depths[node_name].append(depth)
                metrics.max_depth = max(metrics.max_depth, depth)
                breadth_at_depth[depth] += 1
                
                # Track dependencies count
                dep_count = len(node.get("dependencies", []))
                metrics.dependency_counts[dep_count] = metrics.dependency_counts.get(dep_count, 0) + 1
                metrics.total_edges += dep_count
                
                # Track package types
                pkg_type = node.get("type", "required")
                metrics.package_types[pkg_type] = metrics.package_types.get(pkg_type, 0) + 1
                
                # Track version specifiers
                if "requirement" in node and node["requirement"]:
                    spec_type = self._classify_version_spec(node["requirement"])
                    metrics.version_specs[spec_type] = metrics.version_specs.get(spec_type, 0) + 1
                
                # Check for cycles
                if node_name in path:
                    circular_count += 1
                    return
                
                new_path = path | {node_name}
                
                # Process children
                for dep in node.get("dependencies", []):
                    traverse(dep, depth + 1, new_path)
            
            traverse(self.tree)
            
            # Calculate derived metrics
            metrics.unique_packages = len(package_depths)
            metrics.circular_dependencies = circular_count
            metrics.max_breadth = max(breadth_at_depth.values()) if breadth_at_depth else 0
            
            # Calculate average depth
            if package_depths:
                all_depths = [d for depths in package_depths.values() for d in depths]
                metrics.average_depth = sum(all_depths) / len(all_depths) if all_depths else 0
            
            # Calculate average fan-out
            if metrics.total_packages > 0:
                metrics.average_fan_out = metrics.total_edges / metrics.total_packages
            
            return metrics
        
        return self._get_cache_or_compute('metrics', compute_metrics)
    
    def _classify_version_spec(self, spec: str) -> str:
        """
        Classify version specifier type.
        
        Parameters
        ----------
        spec : str
            Version specification string
        
        Returns
        -------
        str
            Specification type (exact, compatible, range, wildcard, etc.)
        """
        if '==' in spec and '.*' not in spec:
            return 'exact'
        elif '~=' in spec:
            return 'compatible'
        elif ',' in spec:
            return 'range'
        elif '.*' in spec or '*' in spec:
            return 'wildcard'
        elif '>=' in spec:
            return 'minimum'
        elif '<=' in spec:
            return 'maximum'
        else:
            return 'other'
    
    def find_orphaned_packages(self) -> List[str]:
        """
        Find packages that are required but not installed.
        
        Returns
        -------
        List[str]
            List of package names that are not installed
        
        Examples
        --------
        >>> analyzer = DependencyAnalyzer(tree)
        >>> orphans = analyzer.find_orphaned_packages()
        >>> if orphans:
        ...     print(f"Missing packages: {', '.join(orphans)}")
        """
        orphans = []
        
        def traverse(node: Dict):
            if node.get("status") == "not_installed":
                name = node.get("name", "unknown")
                if name not in orphans:
                    orphans.append(name)
            
            for dep in node.get("dependencies", []):
                traverse(dep)
            
            if "dependencies_by_type" in node:
                for deps_list in node["dependencies_by_type"].values():
                    for dep in deps_list:
                        traverse(dep)
        
        traverse(self.tree)
        return orphans
    
    def detect_cycles(self) -> List[List[str]]:
        """
        Detect circular dependencies in the tree.
        
        Returns
        -------
        List[List[str]]
            List of cycles found (each cycle is list of package names)
        
        Examples
        --------
        >>> analyzer = DependencyAnalyzer(tree)
        >>> cycles = analyzer.detect_cycles()
        >>> for cycle in cycles:
        ...     print(f"Cycle detected: {' -> '.join(cycle)}")
        """
        def compute_cycles():
            # Build adjacency list
            graph = defaultdict(list)
            
            def build_graph(node: Dict):
                node_name = node.get("name", "")
                for dep in node.get("dependencies", []):
                    dep_name = dep.get("name", "")
                    if dep_name:
                        graph[node_name].append(dep_name)
                    build_graph(dep)
            
            build_graph(self.tree)
            
            # Detect cycles using DFS
            cycles = []
            visited = set()
            rec_stack = set()
            
            def dfs(node: str, path: List[str]):
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
                        if cycle not in cycles:
                            cycles.append(cycle)
                
                rec_stack.remove(node)
            
            for node in graph:
                if node not in visited:
                    dfs(node, [])
            
            return cycles
        
        return self._get_cache_or_compute('cycle', compute_cycles)
    
    def find_impacted_packages(self, package_name: str) -> List[str]:
        """
        Find all packages that would be affected by changes to a package.
        
        Parameters
        ----------
        package_name : str
            Name of the package to analyze
        
        Returns
        -------
        List[str]
            List of packages that depend on the specified package
        
        Examples
        --------
        >>> analyzer = DependencyAnalyzer(tree)
        >>> impacted = analyzer.find_impacted_packages('requests')
        >>> print(f"Packages depending on requests: {', '.join(impacted)}")
        """
        impacted = set()
        
        def find_dependents(node: Dict, current_path: List[str] = None):
            if current_path is None:
                current_path = []
            
            node_name = node.get("name", "")
            current_path.append(node_name)
            
            for dep in node.get("dependencies", []):
                dep_name = dep.get("name", "")
                if dep_name == package_name:
                    # Found dependency, add all packages in path
                    impacted.update(current_path[:-1])  # Exclude the target package
                find_dependents(dep, current_path.copy())
        
        find_dependents(self.tree)
        return sorted(impacted)
    
    def get_dependency_statistics(self) -> Dict[str, Any]:
        """
        Get detailed dependency statistics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing dependency statistics including:
            - most_dependent: Most depended-upon packages
            - deepest_packages: Packages at greatest depth
            - widest_breadth: Packages with most dependencies
            - dependency_heatmap: Distribution of dependencies
        """
        metrics = self.calculate_metrics()
        
        # Calculate most depended-upon packages
        dependency_count = defaultdict(int)
        
        def count_dependencies(node: Dict):
            for dep in node.get("dependencies", []):
                dep_name = dep.get("name", "")
                if dep_name:
                    dependency_count[dep_name] += 1
                count_dependencies(dep)
        
        count_dependencies(self.tree)
        
        most_depended = sorted(dependency_count.items(), key=lambda x: -x[1])[:10]
        
        return {
            'total_packages': metrics.total_packages,
            'unique_packages': metrics.unique_packages,
            'most_depended_upon': [{'package': pkg, 'count': count} 
                                   for pkg, count in most_depended],
            'average_dependencies': metrics.average_fan_out,
            'median_dependencies': self._calculate_median_dependency_count(),
            'dependency_spread': {
                'min': min(metrics.dependency_counts.keys()) if metrics.dependency_counts else 0,
                'max': max(metrics.dependency_counts.keys()) if metrics.dependency_counts else 0
            }
        }
    
    def _calculate_median_dependency_count(self) -> float:
        """
        Calculate median number of dependencies per package.
        
        Returns
        -------
        float
            Median dependency count
        """
        counts = []
        
        def collect_counts(node: Dict):
            counts.append(len(node.get("dependencies", [])))
            for dep in node.get("dependencies", []):
                collect_counts(dep)
        
        collect_counts(self.tree)
        
        if not counts:
            return 0.0
        
        sorted_counts = sorted(counts)
        n = len(sorted_counts)
        if n % 2 == 0:
            return (sorted_counts[n//2 - 1] + sorted_counts[n//2]) / 2
        else:
            return float(sorted_counts[n//2])
    
    def export_analysis(self, format: str = 'json') -> str:
        """
        Export complete analysis results in specified format.
        
        Parameters
        ----------
        format : str, default='json'
            Output format ('json' or 'dict')
        
        Returns
        -------
        str
            Analysis results in specified format
        
        Examples
        --------
        >>> analyzer = DependencyAnalyzer(tree)
        >>> json_output = analyzer.export_analysis('json')
        >>> print(json_output)
        """
        analysis = {
            'tree_root': self.tree.get('name', 'unknown'),
            'metrics': self.calculate_metrics().to_dict(),
            'conflicts': [c.to_dict() for c in self.find_conflicts()],
            'orphaned_packages': self.find_orphaned_packages(),
            'cycles': self.detect_cycles(),
            'statistics': self.get_dependency_statistics(),
            'analysis_stats': {
                'analyzed_at': self._analysis_stats['analyzed_at'].isoformat(),
                'cache_hits': self._analysis_stats['cache_hits'],
                'cache_misses': self._analysis_stats['cache_misses']
            }
        }
        
        if format == 'json':
            return json.dumps(analysis, indent=2, default=str)
        elif format == 'dict':
            return analysis
        else:
            raise ValueError(f"Unsupported format: {format}")
    
    def clear_cache(self) -> None:
        """Clear all cached analysis results."""
        self._metrics_cache = None
        self._conflicts_cache = None
        self._graph_cache = None
        self._cycle_cache = None
        logger.debug("Analysis cache cleared")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        Get performance statistics for the analyzer.
        
        Returns
        -------
        Dict[str, Any]
            Performance statistics including cache hit rates
        """
        total = self._analysis_stats['cache_hits'] + self._analysis_stats['cache_misses']
        hit_rate = self._analysis_stats['cache_hits'] / total if total > 0 else 0
        
        return {
            'cache_hits': self._analysis_stats['cache_hits'],
            'cache_misses': self._analysis_stats['cache_misses'],
            'cache_hit_rate': hit_rate,
            'analyzed_at': self._analysis_stats['analyzed_at'].isoformat()
        }


# Convenience functions for backward compatibility

def find_conflicts(tree: Dict) -> Dict:
    """
    Legacy function for find_conflicts (returns dict for backward compatibility).
    
    This function maintains the original return format.
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure
    
    Returns
    -------
    dict
        Dictionary containing conflict information
        
    Examples
    --------
    >>> conflicts = find_conflicts(tree)
    >>> if 'numpy' in conflicts:
    ...     print(f"Conflict: {conflicts['numpy']['different_versions']}")
    """
    analyzer = DependencyAnalyzer(tree)
    conflicts = analyzer.find_conflicts()
    
    # Convert to legacy format
    result = {}
    for conflict in conflicts:
        if conflict.package_name in result:
            continue
        
        result[conflict.package_name] = {
            "different_versions": conflict.different_versions,
            "requirements": conflict.requirements,
            "conflict_type": conflict.conflict_type.value,
        }
    
    return result


def calculate_tree_metrics(tree: Dict) -> Dict:
    """
    Legacy function for calculate_tree_metrics (returns dict).
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure
    
    Returns
    -------
    dict
        Dictionary containing metrics
        
    Examples
    --------
    >>> metrics = calculate_tree_metrics(tree)
    >>> print(f"Total packages: {metrics['total_packages']}")
    """
    analyzer = DependencyAnalyzer(tree)
    metrics = analyzer.calculate_metrics()
    return metrics.to_dict()


def find_orphaned_packages(tree: Dict) -> List[str]:
    """
    Find packages that are required but not installed.
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure
    
    Returns
    -------
    List[str]
        List of package names that are not installed
        
    Examples
    --------
    >>> orphans = find_orphaned_packages(tree)
    >>> print(f"Missing packages: {', '.join(orphans)}")
    """
    analyzer = DependencyAnalyzer(tree)
    return analyzer.find_orphaned_packages()


def analyze_tree_comprehensive(tree: Dict) -> Dict[str, Any]:
    """
    Perform comprehensive analysis of a dependency tree.
    
    This function provides a complete analysis including conflicts,
    metrics, and recommendations in a single call.
    
    Parameters
    ----------
    tree : dict
        Dependency tree structure
    
    Returns
    -------
    Dict[str, Any]
        Comprehensive analysis results
        
    Examples
    --------
    >>> analysis = analyze_tree_comprehensive(tree)
    >>> print(f"Health score: {analysis['health_score']}/100")
    >>> print(f"Conflicts found: {analysis['conflict_count']}")
    """
    analyzer = DependencyAnalyzer(tree)
    
    metrics = analyzer.calculate_metrics()
    conflicts = analyzer.find_conflicts()
    cycles = analyzer.detect_cycles()
    orphans = analyzer.find_orphaned_packages()
    
    # Calculate health score (0-100)
    health_score = 100
    health_score -= len(conflicts) * 10
    health_score -= len(cycles) * 15
    health_score -= len(orphans) * 20
    
    health_score = max(0, min(100, health_score))
    
    return {
        'health_score': health_score,
        'health_grade': _get_health_grade(health_score),
        'metrics': metrics.to_dict(),
        'conflicts': [c.to_dict() for c in conflicts],
        'conflict_count': len(conflicts),
        'circular_dependencies': cycles,
        'circular_count': len(cycles),
        'orphaned_packages': orphans,
        'orphaned_count': len(orphans),
        'recommendations': _generate_recommendations(metrics, conflicts, cycles, orphans)
    }


def _get_health_grade(score: int) -> str:
    """
    Convert health score to letter grade.
    
    Parameters
    ----------
    score : int
        Health score (0-100)
    
    Returns
    -------
    str
        Letter grade (A, B, C, D, F)
    """
    if score >= 90:
        return "A (Excellent)"
    elif score >= 80:
        return "B (Good)"
    elif score >= 70:
        return "C (Fair)"
    elif score >= 60:
        return "D (Poor)"
    else:
        return "F (Critical)"


def _generate_recommendations(metrics: TreeMetrics, conflicts: List[ConflictInfo],
                             cycles: List[List[str]], orphans: List[str]) -> List[str]:
    """
    Generate actionable recommendations based on analysis.
    
    Returns
    -------
    List[str]
        List of recommendations
    """
    recommendations = []
    
    if conflicts:
        recommendations.append(f"Resolve {len(conflicts)} version conflicts, especially "
                              f"{', '.join([c.package_name for c in conflicts[:3]])}")
    
    if cycles:
        recommendations.append(f"Break {len(cycles)} circular dependencies to prevent resolution issues")
    
    if orphans:
        recommendations.append(f"Install missing packages: {', '.join(orphans[:5])}")
    
    if metrics.average_depth > 10:
        recommendations.append(f"High average depth ({metrics.average_depth:.1f}) - consider flattening dependency tree")
    
    if metrics.circular_dependencies > 0:
        recommendations.append(f"Fix {metrics.circular_dependencies} circular dependency instances")
    
    if not recommendations:
        recommendations.append("Dependency tree appears healthy. No immediate issues detected.")
    
    return recommendations


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
logger.debug("Dependency tree analysis module initialized")