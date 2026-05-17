#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
pyputil.tree.builder - Dependency Tree Construction Engine
================================================================================

A sophisticated, production-ready module for building and managing Python package
dependency trees with advanced features including parallel processing, intelligent
caching, cycle detection, shared dependency deduplication, and comprehensive
statistics collection.

Module Overview
---------------
This module provides the core engine for dependency tree construction. It handles
the complex task of recursively traversing package dependencies while managing
performance, memory usage, and output quality.

Key Capabilities:
-----------------
1. Multiple Build Strategies - Depth-first, breadth-first, lazy, eager
2. Intelligent Caching - Node-level, subtree, or memoized caching
3. Cycle Detection - Prevents infinite recursion with per-depth tracking
4. Shared Dependency Deduplication - Eliminates duplicate branches (NEW!)
5. Conflict Resolution - Automatic version conflict handling
6. Parallel Processing - Thread pool for improved performance
7. Extensive Filtering - Platform, Python version, extras, optional/dev deps
8. Comprehensive Statistics - Performance metrics and tree analysis

Example Usage
-------------
>>> # Basic usage with deduplication
>>> builder = DependencyTreeBuilder(
...     max_depth=3,
...     deduplicate_shared=True,
...     duplicate_handling=DuplicateHandling.MERGE
... )
>>> tree = builder.build("requests")
>>> 
>>> # Advanced configuration
>>> builder = DependencyTreeBuilder(
...     build_strategy=BuildStrategy.BREADTH_FIRST,
...     cache_strategy=CacheStrategy.SUBTREE,
...     resolution_strategy=ResolutionStrategy.HIGHEST,
...     include_stats=True
... )
>>> tree = builder.build("pandas")
>>> print(builder.get_stats().get_summary())
"""

import sys
import time
import logging
import threading
import warnings
from typing import Optional, Set, Dict, List, Union, Any, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Import internal modules
from ..core.models import PackageInfo, DependencyType
from ..core.cache import PackageCache
from ..core.parser import parse_requirement, normalize_package_name
from ..utils.filters import should_include_requirement

# Configure module logger
logger = logging.getLogger(__name__)


# =============================================================================
# ENUMERATIONS FOR CONFIGURATION
# =============================================================================

class BuildStrategy(Enum):
    """
    Defines the traversal strategy for building the dependency tree.
    
    The build strategy determines the order in which dependencies are processed.
    Each strategy has different performance characteristics and memory usage
    patterns, making them suitable for different types of dependency trees.
    
    Attributes
    ----------
    DEPTH_FIRST : str
        Depth-first traversal - processes each branch completely before moving
        to the next. Best for deep trees with many levels of nesting.
        
        Characteristics:
        - Memory usage: Low (only one branch in memory at a time)
        - Speed: Medium (recursive overhead)
        - Best for: Deep dependency trees, limited memory environments
        
    BREADTH_FIRST : str
        Breadth-first traversal - processes all dependencies at current depth
        before going deeper. Best for wide, shallow trees.
        
        Characteristics:
        - Memory usage: Medium (multiple branches stored)
        - Speed: Medium (queue management overhead)
        - Best for: Wide trees with many dependencies per level
        
    LAZY : str
        Lazy evaluation - builds nodes on-demand with placeholders for
        dependencies. Most memory efficient but requires multiple passes.
        
        Characteristics:
        - Memory usage: Low (minimal data stored)
        - Speed: Slow (multiple traversals needed)
        - Best for: Interactive exploration, partial tree views
        
    EAGER : str
        Eager evaluation - pre-fetches all dependencies upfront. Fastest
        but uses most memory. Best for small to medium trees.
        
        Characteristics:
        - Memory usage: High (everything loaded at once)
        - Speed: Fast (minimal overhead)
        - Best for: Small trees, complete analysis
    
    Examples
    --------
    >>> # Create a depth-first builder for deep trees
    >>> builder = DependencyTreeBuilder(
    ...     build_strategy=BuildStrategy.DEPTH_FIRST,
    ...     max_depth=10
    ... )
    >>> 
    >>> # Use breadth-first for wide trees
    >>> builder = DependencyTreeBuilder(
    ...     build_strategy=BuildStrategy.BREADTH_FIRST,
    ...     parallel_processing=4
    ... )
    """
    
    DEPTH_FIRST = "depth_first"
    BREADTH_FIRST = "breadth_first"
    LAZY = "lazy"
    EAGER = "eager"
    
    def is_recursive(self) -> bool:
        """
        Determines if the strategy uses recursive traversal.
        
        Recursive strategies are simpler to implement but may hit recursion
        limits on very deep trees (depth > 1000).
        
        Returns
        -------
        bool
            True if the strategy uses recursion (DEPTH_FIRST, BREADTH_FIRST),
            False otherwise.
        
        Examples
        --------
        >>> BuildStrategy.DEPTH_FIRST.is_recursive()
        True
        >>> BuildStrategy.LAZY.is_recursive()
        False
        """
        return self in (BuildStrategy.DEPTH_FIRST, BuildStrategy.BREADTH_FIRST)
    
    def is_lazy(self) -> bool:
        """
        Determines if the strategy uses lazy evaluation.
        
        Lazy strategies build nodes on-demand rather than eagerly processing
        all dependencies upfront.
        
        Returns
        -------
        bool
            True for LAZY strategy, False otherwise.
        
        Examples
        --------
        >>> BuildStrategy.LAZY.is_lazy()
        True
        >>> BuildStrategy.EAGER.is_lazy()
        False
        """
        return self == BuildStrategy.LAZY
    
    def memory_usage(self) -> str:
        """
        Returns the relative memory usage characteristic.
        
        Different strategies have different memory footprints. Use this to
        choose the right strategy for your environment.
        
        Returns
        -------
        str
            One of: 'very_low', 'low', 'medium', 'high' indicating relative
            memory consumption.
        
        Examples
        --------
        >>> BuildStrategy.DEPTH_FIRST.memory_usage()
        'low'
        >>> BuildStrategy.EAGER.memory_usage()
        'high'
        """
        memory_map = {
            BuildStrategy.DEPTH_FIRST: 'low',
            BuildStrategy.BREADTH_FIRST: 'medium',
            BuildStrategy.LAZY: 'very_low',
            BuildStrategy.EAGER: 'high'
        }
        return memory_map.get(self, 'medium')
    
    def speed(self) -> str:
        """
        Returns the relative processing speed characteristic.
        
        Speed characteristics help choose the right strategy when performance
        is critical.
        
        Returns
        -------
        str
            One of: 'very_fast', 'fast', 'medium', 'slow' indicating relative
            processing speed.
        
        Examples
        --------
        >>> BuildStrategy.EAGER.speed()
        'very_fast'
        >>> BuildStrategy.LAZY.speed()
        'slow'
        """
        speed_map = {
            BuildStrategy.DEPTH_FIRST: 'medium',
            BuildStrategy.BREADTH_FIRST: 'medium',
            BuildStrategy.LAZY: 'slow',
            BuildStrategy.EAGER: 'very_fast'
        }
        return speed_map.get(self, 'medium')
    
    def get_description(self) -> str:
        """
        Returns a detailed human-readable description of the strategy.
        
        Returns
        -------
        str
            Detailed description explaining when to use this strategy.
        
        Examples
        --------
        >>> print(BuildStrategy.DEPTH_FIRST.get_description())
        Depth-first traversal - processes each branch completely before moving
        to the next. Best for deep trees with many levels of nesting.
        """
        descriptions = {
            BuildStrategy.DEPTH_FIRST: (
                "Depth-first traversal - processes each branch completely before moving "
                "to the next. Best for deep trees with many levels of nesting."
            ),
            BuildStrategy.BREADTH_FIRST: (
                "Breadth-first traversal - processes all dependencies at current depth "
                "before going deeper. Best for wide, shallow trees."
            ),
            BuildStrategy.LAZY: (
                "Lazy evaluation - builds nodes on-demand with placeholders for "
                "dependencies. Most memory efficient but requires multiple passes."
            ),
            BuildStrategy.EAGER: (
                "Eager evaluation - pre-fetches all dependencies upfront. Fastest "
                "but uses most memory. Best for small to medium trees."
            )
        }
        return descriptions.get(self, "Unknown strategy")


class ResolutionStrategy(Enum):
    """
    Defines how version conflicts are resolved when multiple dependencies
    require different versions of the same package.
    
    When building a dependency tree, it's common to encounter situations where
    different packages require different versions of the same dependency. This
    strategy determines which version to use in the final tree.
    
    Attributes
    ----------
    HIGHEST : str
        Select the highest compatible version. This is the recommended strategy
        for production environments as it typically provides the latest features
        and security fixes.
        
        Use case: Production deployments, when you want the latest stable versions
        
    LOWEST : str
        Select the lowest compatible version. This conservative approach minimizes
        the risk of breaking changes but may miss important updates.
        
        Use case: Conservative environments, legacy systems, maximum compatibility
        
    FIRST : str
        Select the first version encountered during traversal. This is the fastest
        strategy but may not produce optimal results.
        
        Use case: Quick analysis, when correctness is not critical
        
    USER : str
        Require manual resolution for conflicts. When a conflict is detected,
        the builder will raise an exception or mark the conflict for user input.
        
        Use case: Interactive environments, when you need to make informed decisions
    
    Examples
    --------
    >>> # Use highest version strategy (recommended)
    >>> builder = DependencyTreeBuilder(
    ...     resolution_strategy=ResolutionStrategy.HIGHEST
    ... )
    >>> 
    >>> # Manual resolution for critical packages
    >>> builder = DependencyTreeBuilder(
    ...     resolution_strategy=ResolutionStrategy.USER
    ... )
    >>> builder.set_conflict_resolution('requests', '2.28.1')
    """
    
    HIGHEST = "highest"
    LOWEST = "lowest"
    FIRST = "first"
    USER = "user"
    
    def get_priority(self) -> int:
        """
        Returns the automation priority level.
        
        Higher priority strategies are more automated and require less
        user intervention.
        
        Returns
        -------
        int
            Priority from 1 (least automated) to 4 (most automated)
        
        Examples
        --------
        >>> ResolutionStrategy.HIGHEST.get_priority()
        4
        >>> ResolutionStrategy.USER.get_priority()
        1
        """
        priorities = {
            ResolutionStrategy.HIGHEST: 4,
            ResolutionStrategy.LOWEST: 3,
            ResolutionStrategy.FIRST: 2,
            ResolutionStrategy.USER: 1
        }
        return priorities.get(self, 2)
    
    def is_automatic(self) -> bool:
        """
        Checks if the strategy resolves conflicts automatically.
        
        Returns
        -------
        bool
            True for HIGHEST, LOWEST, FIRST; False for USER
        
        Examples
        --------
        >>> ResolutionStrategy.HIGHEST.is_automatic()
        True
        >>> ResolutionStrategy.USER.is_automatic()
        False
        """
        return self != ResolutionStrategy.USER
    
    def get_description(self) -> str:
        """
        Returns a detailed description of the strategy.
        
        Returns
        -------
        str
            Human-readable description with recommendations
        
        Examples
        --------
        >>> print(ResolutionStrategy.HIGHEST.get_description())
        Select the highest compatible version. This is the recommended strategy...
        """
        descriptions = {
            ResolutionStrategy.HIGHEST: (
                "Select the highest compatible version. Recommended for production "
                "environments as it provides the latest features and security fixes."
            ),
            ResolutionStrategy.LOWEST: (
                "Select the lowest compatible version. Conservative approach for "
                "maximum compatibility with legacy systems."
            ),
            ResolutionStrategy.FIRST: (
                "Select the first version encountered. Fastest but may not be optimal."
            ),
            ResolutionStrategy.USER: (
                "Require manual resolution for conflicts. Best when you need to make "
                "informed decisions about version selection."
            )
        }
        return descriptions.get(self, "Unknown strategy")


class CacheStrategy(Enum):
    """
    Defines caching behavior for the dependency tree builder.
    
    Caching can dramatically improve performance when building multiple trees
    or when the same packages appear multiple times. Different strategies
    offer different trade-offs between memory usage and speed.
    
    Attributes
    ----------
    NONE : str
        No caching at all. Every node is rebuilt from scratch.
        
        Use case: One-off builds, memory-constrained environments, debugging
        
    NODE : str
        Cache individual nodes. When a package is encountered again, its
        cached node is returned without reprocessing.
        
        Use case: Most general use cases, good balance of speed and memory
        
    SUBTREE : str
        Cache entire subtrees including all dependencies. When a package is
        encountered again, the entire cached subtree is returned.
        
        Use case: Repeated queries on the same packages, analysis tools
        
    MEMOIZE : str
        Most aggressive caching. Caches based on package name, depth, and
        filter settings. Returns cached results even at different depths.
        
        Use case: Deep trees with many repeated patterns, performance-critical apps
    
    Examples
    --------
    >>> # Node-level caching for general use
    >>> builder = DependencyTreeBuilder(cache_strategy=CacheStrategy.NODE)
    >>> 
    >>> # Subtree caching for repeated analysis
    >>> builder = DependencyTreeBuilder(cache_strategy=CacheStrategy.SUBTREE)
    """
    
    NONE = "none"
    NODE = "node"
    SUBTREE = "subtree"
    MEMOIZE = "memoize"
    
    def should_cache_children(self) -> bool:
        """
        Determines if child dependencies should also be cached.
        
        When True, the entire subtree is cached. When False, only the node
        itself is cached.
        
        Returns
        -------
        bool
            True for SUBTREE and MEMOIZE strategies, False otherwise.
        
        Examples
        --------
        >>> CacheStrategy.SUBTREE.should_cache_children()
        True
        >>> CacheStrategy.NODE.should_cache_children()
        False
        """
        return self in (CacheStrategy.SUBTREE, CacheStrategy.MEMOIZE)
    
    def memory_overhead(self) -> str:
        """
        Returns the relative memory overhead of the caching strategy.
        
        Returns
        -------
        str
            One of: 'none', 'low', 'medium', 'high'
        
        Examples
        --------
        >>> CacheStrategy.NONE.memory_overhead()
        'none'
        >>> CacheStrategy.MEMOIZE.memory_overhead()
        'high'
        """
        overhead_map = {
            CacheStrategy.NONE: 'none',
            CacheStrategy.NODE: 'low',
            CacheStrategy.SUBTREE: 'medium',
            CacheStrategy.MEMOIZE: 'high'
        }
        return overhead_map.get(self, 'medium')
    
    def get_description(self) -> str:
        """
        Returns a detailed description of the caching strategy.
        
        Returns
        -------
        str
            Human-readable description with use case recommendations
        
        Examples
        --------
        >>> print(CacheStrategy.NODE.get_description())
        Cache individual nodes. Good balance of speed and memory for most use cases.
        """
        descriptions = {
            CacheStrategy.NONE: "No caching. Every node is rebuilt from scratch. Best for one-off builds.",
            CacheStrategy.NODE: "Cache individual nodes. Good balance of speed and memory for most use cases.",
            CacheStrategy.SUBTREE: "Cache entire subtrees. Best for repeated queries on the same packages.",
            CacheStrategy.MEMOIZE: "Most aggressive caching. Best for deep trees with repeated patterns."
        }
        return descriptions.get(self, "Unknown strategy")


class DuplicateHandling(Enum):
    """
    Defines how shared/deduplicate dependencies are handled in the tree.
    
    When the same package appears multiple times in different branches of the
    tree, this strategy determines how to represent it in the output. This is
    especially useful for reducing clutter in large dependency trees.
    
    Attributes
    ----------
    SHOW_ALL : str
        Show all occurrences. The tree displays every instance of each package,
        even if identical. This provides a complete picture but can be very
        verbose.
        
        Use case: Complete accuracy, debugging, when you need to see all paths
        
    DEDUPLICATE : str
        Show each package only once per depth level. If the same package appears
        multiple times at the same depth, only the first occurrence is shown.
        
        Use case: Reducing clutter while maintaining context
        
    MERGE : str
        Merge duplicate branches into a single reference. When a package subtree
        is identical to a previously seen one, it's replaced with a reference.
        
        Use case: Large trees, visualization, when you care about structure
        
    MARK_SHARED : str
        Show all occurrences but mark shared dependencies with a special
        status indicator (e.g., "[shared]").
        
        Use case: Analysis, when you need to identify which packages are reused
        
    COLLAPSE : str
        Collapse duplicate subtrees and show a reference count. For example,
        if the same package appears 5 times, show it once with a badge like
        "[x5]" indicating how many times it appears.
        
        Use case: High-level overview, summary reports
    
    Examples
    --------
    >>> # Merge duplicates for cleaner output
    >>> builder = DependencyTreeBuilder(
    ...     deduplicate_shared=True,
    ...     duplicate_handling=DuplicateHandling.MERGE
    ... )
    >>> 
    >>> # Mark shared dependencies for analysis
    >>> builder = DependencyTreeBuilder(
    ...     deduplicate_shared=True,
    ...     duplicate_handling=DuplicateHandling.MARK_SHARED
    ... )
    """
    
    SHOW_ALL = "show_all"
    DEDUPLICATE = "deduplicate"
    MERGE = "merge"
    MARK_SHARED = "mark_shared"
    COLLAPSE = "collapse"
    
    def should_show_shared_marker(self) -> bool:
        """
        Checks if shared dependencies should be visually marked in output.
        
        Returns
        -------
        bool
            True for DEDUPLICATE, MERGE, MARK_SHARED, COLLAPSE; False for SHOW_ALL
        
        Examples
        --------
        >>> DuplicateHandling.MARK_SHARED.should_show_shared_marker()
        True
        >>> DuplicateHandling.SHOW_ALL.should_show_shared_marker()
        False
        """
        return self != DuplicateHandling.SHOW_ALL
    
    def should_collapse(self) -> bool:
        """
        Checks if duplicate subtrees should be collapsed with reference counts.
        
        Returns
        -------
        bool
            True for COLLAPSE strategy only
        
        Examples
        --------
        >>> DuplicateHandling.COLLAPSE.should_collapse()
        True
        >>> DuplicateHandling.MERGE.should_collapse()
        False
        """
        return self == DuplicateHandling.COLLAPSE
    
    def should_merge(self) -> bool:
        """
        Checks if duplicate branches should be merged into references.
        
        Returns
        -------
        bool
            True for MERGE strategy only
        
        Examples
        --------
        >>> DuplicateHandling.MERGE.should_merge()
        True
        >>> DuplicateHandling.DEDUPLICATE.should_merge()
        False
        """
        return self == DuplicateHandling.MERGE
    
    def get_description(self) -> str:
        """
        Returns a detailed description of the duplicate handling strategy.
        
        Returns
        -------
        str
            Human-readable description with use case recommendations
        
        Examples
        --------
        >>> print(DuplicateHandling.MERGE.get_description())
        Merge duplicate branches into a single reference. Best for large trees...
        """
        descriptions = {
            DuplicateHandling.SHOW_ALL: (
                "Show all occurrences - provides complete accuracy but can be verbose. "
                "Best for debugging when you need to see all paths."
            ),
            DuplicateHandling.DEDUPLICATE: (
                "Show each package once per depth level - reduces clutter while maintaining context. "
                "Best for general use when you want cleaner output."
            ),
            DuplicateHandling.MERGE: (
                "Merge duplicate branches into a single reference - eliminates redundancy completely. "
                "Best for large trees where structure matters more than paths."
            ),
            DuplicateHandling.MARK_SHARED: (
                "Mark shared dependencies with indicators - helps identify reused packages. "
                "Best for analysis when you need to find common dependencies."
            ),
            DuplicateHandling.COLLAPSE: (
                "Collapse duplicates with reference counts - provides high-level overview. "
                "Best for summary reports and high-level analysis."
            )
        }
        return descriptions.get(self, "Unknown strategy")


# =============================================================================
# DATA CLASSES FOR STATISTICS AND METRICS
# =============================================================================

@dataclass
class BuildStats:
    """
    Comprehensive statistics and metrics collected during tree construction.
    
    This dataclass tracks every aspect of the build process, providing valuable
    insights into performance, cache efficiency, tree characteristics, and
    optimization opportunities.
    
    Attributes
    ----------
    nodes_build : int
        Total number of nodes successfully built in the dependency tree.
        Each node represents one package instance in the tree.
    
    cache_hits : int
        Number of successful cache retrievals. Higher values indicate better
        cache utilization and faster builds.
    
    cache_misses : int
        Number of cache misses that required recomputation. Lower values are better.
    
    cycles_detected : int
        Number of circular dependencies detected in the tree. Each cycle
        represents a potential issue that may need resolution.
    
    shared_dependencies : int
        Number of shared dependencies that were deduplicated. Higher values
        indicate more redundancy in the dependency graph.
    
    errors : int
        Number of errors encountered during processing (e.g., network failures,
        invalid package metadata).
    
    build_time : float
        Total time spent building the tree, in seconds. Includes all processing,
        network requests, and cache operations.
    
    max_depth_reached : int
        Maximum depth reached in the dependency tree. Deep trees may indicate
        complex dependency chains.
    
    unique_packages : int
        Number of unique package names encountered. This is the count of distinct
        packages, regardless of how many times they appear.
    
    deduplications_saved : int
        Number of duplicate nodes avoided through deduplication. Each saved node
        represents processing time and memory that was saved.
    
    processed_at : datetime
        Timestamp when the build was completed.
    
    Examples
    --------
    >>> # Create and use statistics
    >>> stats = BuildStats()
    >>> stats.record_node_built()
    >>> stats.record_cache_hit()
    >>> stats.record_shared_dependency()
    >>> stats.finish()
    >>> 
    >>> # Get summary
    >>> print(stats.get_summary())
    Build Statistics:
    -----------------
    Total Nodes Built: 1
    Cache Hits: 1
    ...
    >>> 
    >>> # Convert to dictionary for JSON export
    >>> stats_dict = stats.to_dict()
    """
    
    # Core metrics
    nodes_built: int = 0
    """Total number of nodes successfully built."""
    
    cache_hits: int = 0
    """Number of successful cache retrievals."""
    
    cache_misses: int = 0
    """Number of cache misses requiring recomputation."""
    
    cycles_detected: int = 0
    """Number of circular dependencies detected."""
    
    shared_dependencies: int = 0
    """Number of shared dependencies deduplicated."""
    
    errors: int = 0
    """Number of errors encountered during processing."""
    
    build_time: float = 0.0
    """Total build time in seconds."""
    
    max_depth_reached: int = 0
    """Maximum depth reached in the tree."""
    
    unique_packages: int = 0
    """Number of unique package names encountered."""
    
    deduplications_saved: int = 0
    """Number of duplicate nodes avoided through deduplication."""
    
    # Internal tracking (not part of public API)
    _start_time: float = field(default_factory=time.time, init=False, repr=False)
    """Internal start time for build duration tracking."""
    
    _processed_packages: Set[str] = field(default_factory=set, init=False, repr=False)
    """Internal set for tracking unique package names."""
    
    _processed_at: datetime = field(default_factory=datetime.now, init=False)
    """Timestamp when the build was completed."""
    
    def record_node_built(self) -> None:
        """
        Record that a node was successfully built.
        
        This method should be called each time a package node is added to the
        tree. It increments the node counter for statistics tracking.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.record_node_built()
        >>> stats.nodes_built
        1
        """
        self.nodes_built += 1
    
    def record_cache_hit(self) -> None:
        """
        Record a successful cache hit.
        
        Called when a requested node is found in the cache, avoiding the need
        to rebuild it. High cache hit rates indicate good cache utilization.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.record_cache_hit()
        >>> stats.cache_hits
        1
        """
        self.cache_hits += 1
    
    def record_cache_miss(self) -> None:
        """
        Record a cache miss.
        
        Called when a requested node is not found in the cache, requiring
        recomputation. High miss rates may indicate insufficient cache size
        or ineffective caching strategy.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.record_cache_miss()
        >>> stats.cache_misses
        1
        """
        self.cache_misses += 1
    
    def record_cycle(self) -> None:
        """
        Record a detected circular dependency.
        
        Called when a cycle is detected in the dependency graph. Each cycle
        is recorded for later analysis and reporting.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.record_cycle()
        >>> stats.cycles_detected
        1
        """
        self.cycles_detected += 1
    
    def record_shared_dependency(self) -> None:
        """
        Record a shared dependency that was deduplicated.
        
        Called when a shared dependency is detected and handled according to
        the duplicate handling strategy. This helps measure redundancy in the
        dependency graph.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.record_shared_dependency()
        >>> stats.shared_dependencies
        1
        """
        self.shared_dependencies += 1
    
    def record_error(self) -> None:
        """
        Record an error encountered during processing.
        
        Called when an error occurs (e.g., network failure, invalid metadata).
        Errors are tracked for monitoring build reliability.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.record_error()
        >>> stats.errors
        1
        """
        self.errors += 1
    
    def record_deduplication_saved(self) -> None:
        """
        Record a duplicate node avoided through deduplication.
        
        Called each time a duplicate node would have been added but was
        skipped due to deduplication. This metric shows how much processing
        was saved.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.record_deduplication_saved()
        >>> stats.deduplications_saved
        1
        """
        self.deduplications_saved += 1
    
    def record_package(self, package_name: str) -> None:
        """
        Record a package name for uniqueness tracking.
        
        This method maintains a set of unique package names encountered during
        the build. It updates the unique_packages count accordingly.
        
        Parameters
        ----------
        package_name : str
            The normalized name of the package to record.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.record_package("requests")
        >>> stats.record_package("requests")  # Same package
        >>> stats.record_package("urllib3")   # New package
        >>> stats.unique_packages
        2
        """
        if package_name not in self._processed_packages:
            self._processed_packages.add(package_name)
            self.unique_packages = len(self._processed_packages)
    
    def record_depth(self, depth: int) -> None:
        """
        Record the depth of a node and update max depth if needed.
        
        Parameters
        ----------
        depth : int
            The depth of the current node (0 for root).
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.record_depth(5)
        >>> stats.record_depth(10)  # New maximum
        >>> stats.max_depth_reached
        10
        """
        if depth > self.max_depth_reached:
            self.max_depth_reached = depth
    
    def finish(self) -> None:
        """
        Mark the end of building and record total build time.
        
        This method should be called when the tree construction is complete.
        It calculates the total build duration and records the timestamp.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> # ... build operations ...
        >>> stats.finish()
        >>> stats.build_time
        0.123456
        """
        self.build_time = time.time() - self._start_time
        self._processed_at = datetime.now()
    
    def get_summary(self) -> str:
        """
        Generate a human-readable summary of all build statistics.
        
        This method formats the statistics into a nicely formatted string
        suitable for console output or logging. It includes all major metrics
        and calculates derived values like cache hit rate.
        
        Returns
        -------
        str
            Formatted summary string with all statistics.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.nodes_built = 100
        >>> stats.cache_hits = 80
        >>> stats.cache_misses = 20
        >>> print(stats.get_summary())
        ==================================================
        Build Statistics Summary
        ==================================================
        Total Nodes Built: 100
        Unique Packages: 0
        Max Depth Reached: 0
        Cache Hits: 80
        Cache Misses: 20
        Cache Hit Rate: 80.0%
        Cycles Detected: 0
        Shared Dependencies: 0
        Deduplications Saved: 0
        Errors: 0
        Build Time: 0.000 seconds
        ==================================================
        """
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_requests * 100) if total_requests > 0 else 0
        
        lines = [
            "=" * 50,
            "Build Statistics Summary",
            "=" * 50,
            f"Total Nodes Built: {self.nodes_built}",
            f"Unique Packages: {self.unique_packages}",
            f"Max Depth Reached: {self.max_depth_reached}",
            f"Cache Hits: {self.cache_hits}",
            f"Cache Misses: {self.cache_misses}",
            f"Cache Hit Rate: {hit_rate:.1f}%",
            f"Cycles Detected: {self.cycles_detected}",
            f"Shared Dependencies: {self.shared_dependencies}",
            f"Deduplications Saved: {self.deduplications_saved}",
            f"Errors: {self.errors}",
            f"Build Time: {self.build_time:.3f} seconds",
            "=" * 50
        ]
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert statistics to a JSON-serializable dictionary.
        
        This method is useful for exporting statistics to JSON format for
        logging, reporting, or API responses.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing all statistics with descriptive keys.
        
        Examples
        --------
        >>> stats = BuildStats()
        >>> stats.nodes_built = 100
        >>> stats_dict = stats.to_dict()
        >>> import json
        >>> print(json.dumps(stats_dict, indent=2))
        {
          "nodes_built": 100,
          "unique_packages": 0,
          ...
        }
        """
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'nodes_built': self.nodes_built,
            'unique_packages': self.unique_packages,
            'max_depth_reached': self.max_depth_reached,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'cache_hit_rate': round(hit_rate, 2),
            'cycles_detected': self.cycles_detected,
            'shared_dependencies': self.shared_dependencies,
            'deduplications_saved': self.deduplications_saved,
            'errors': self.errors,
            'build_time': round(self.build_time, 3),
            'processed_at': self._processed_at.isoformat()
        }


# =============================================================================
# MAIN DEPENDENCY TREE BUILDER CLASS
# =============================================================================

class DependencyTreeBuilder:
    """
    Advanced builder class for constructing package dependency trees.
    
    This is the core engine of the dependency tree analysis system. It handles
    the complex process of recursively traversing package dependencies while
    managing performance, memory usage, and output quality.
    
    The builder supports multiple strategies for traversal, caching, conflict
    resolution, and duplicate handling, allowing it to be optimized for various
    use cases from quick analysis to production-grade dependency resolution.
    
    Key Features:
    -------------
    - **Multiple Build Strategies**: Depth-first, breadth-first, lazy, eager
    - **Intelligent Caching**: Node-level, subtree, or memoized caching
    - **Cycle Detection**: Prevents infinite recursion with per-depth tracking
    - **Shared Dependency Deduplication**: Eliminates duplicate branches
    - **Conflict Resolution**: Automatic version conflict handling
    - **Parallel Processing**: Thread pool for improved performance
    - **Extensive Filtering**: Platform, Python version, extras, optional/dev deps
    - **Comprehensive Statistics**: Performance metrics and tree analysis
    
    Parameters
    ----------
    max_depth : int, optional
        Maximum recursion depth for tree traversal. If None, no limit is applied.
        Use this to prevent excessively deep trees from slowing down analysis.
    
    skip_optional : bool, default=False
        If True, exclude optional dependencies (marked with 'extra' or 'optional'
        in their environment markers). Useful for production environment analysis.
    
    skip_development : bool, default=False
        If True, exclude development dependencies (marked with 'dev', 'test',
        'docs', etc.). Useful for dependency analysis of production code.
    
    parallel_processing : int, default=1
        Number of parallel threads for processing dependencies. Set to 1 for
        sequential processing. Higher values improve performance for large trees
        but increase memory usage.
    
    include_stats : bool, default=False
        If True, include comprehensive statistics in the output tree. Also makes
        statistics available via get_stats() method.
    
    build_strategy : BuildStrategy, default=BuildStrategy.DEPTH_FIRST
        Strategy for traversing the dependency tree. Different strategies offer
        different trade-offs between memory usage and speed.
    
    cache_strategy : CacheStrategy, default=CacheStrategy.NODE
        Strategy for caching built nodes. Caching can dramatically improve
        performance for repeated builds or shared dependencies.
    
    resolution_strategy : ResolutionStrategy, default=ResolutionStrategy.HIGHEST
        Strategy for resolving version conflicts when multiple dependencies
        require different versions of the same package.
    
    duplicate_handling : DuplicateHandling, default=DuplicateHandling.DEDUPLICATE
        Strategy for handling shared dependencies that appear multiple times
        in the tree. Helps reduce clutter and improve performance.
    
    platform_filter : str, optional
        Filter dependencies by platform ('linux', 'windows', 'darwin', 'unix').
        Only dependencies compatible with the specified platform will be included.
    
    python_version_filter : str, optional
        Filter dependencies by Python version (e.g., '>=3.8', '==3.9.*').
        Only dependencies compatible with the specified Python version are included.
    
    include_extras : List[str], optional
        List of extras to include in the analysis. Only dependencies that are
        activated by these extras will be included.
    
    timeout_per_node : int, default=30
        Timeout in seconds for processing each node. Prevents hanging on
        problematic packages. Set to 0 to disable.
    
    retry_on_error : bool, default=False
        If True, retry failed package fetches up to max_retries times.
        Useful for handling transient network errors.
    
    max_retries : int, default=3
        Maximum number of retry attempts for failed package fetches when
        retry_on_error is True.
    
    deduplicate_shared : bool, default=True
        Master switch for shared dependency deduplication. When True, applies
        the duplicate_handling strategy. When False, shows all occurrences
        (equivalent to DuplicateHandling.SHOW_ALL).
    
    Attributes
    ----------
    _cache : Dict[str, Dict]
        Internal cache storage for built nodes. Structure depends on cache_strategy.
    
    _seen : Dict[int, Set[str]]
        Tracking set for cycle detection. Maps depth to set of visited package names.
    
    _seen_global : Set[str]
        Global tracking set for shared dependency deduplication. Tracks all
        packages seen anywhere in the tree, regardless of depth.
    
    _shared_refs : Dict[str, int]
        Reference counting for shared dependencies when using COLLAPSE strategy.
        Maps package names to occurrence counts.
    
    _stats : BuildStats
        Statistics collector for the build process.
    
    _lock : threading.RLock
        Reentrant lock for thread-safe access to shared data structures.
    
    _node_builders : Dict[str, Callable]
        Registered custom node builders for specific packages or patterns.
    
    _conflict_resolutions : Dict[str, str]
        Manual conflict resolution overrides for specific packages.
    
    Examples
    --------
    >>> # Basic usage with default settings
    >>> builder = DependencyTreeBuilder(max_depth=3)
    >>> tree = builder.build("requests")
    >>> print(tree['name'])
    'requests'
    
    >>> # Advanced configuration with deduplication
    >>> builder = DependencyTreeBuilder(
    ...     max_depth=5,
    ...     parallel_processing=4,
    ...     build_strategy=BuildStrategy.BREADTH_FIRST,
    ...     cache_strategy=CacheStrategy.SUBTREE,
    ...     duplicate_handling=DuplicateHandling.MERGE,
    ...     platform_filter='linux',
    ...     include_stats=True
    ... )
    >>> tree = builder.build("scikit-learn")
    >>> print(builder.get_stats().get_summary())
    
    >>> # Manual conflict resolution
    >>> builder = DependencyTreeBuilder(
    ...     resolution_strategy=ResolutionStrategy.USER
    ... )
    >>> builder.set_conflict_resolution('requests', '2.28.1')
    >>> builder.set_conflict_resolution('urllib3', '1.26.13')
    >>> tree = builder.build("myapp")
    """
    
    def __init__(
        self,
        max_depth: Optional[int] = None,
        skip_optional: bool = False,
        skip_development: bool = False,
        parallel_processing: int = 1,
        include_stats: bool = False,
        build_strategy: BuildStrategy = BuildStrategy.DEPTH_FIRST,
        cache_strategy: CacheStrategy = CacheStrategy.NODE,
        resolution_strategy: ResolutionStrategy = ResolutionStrategy.HIGHEST,
        duplicate_handling: DuplicateHandling = DuplicateHandling.DEDUPLICATE,
        platform_filter: Optional[str] = None,
        python_version_filter: Optional[str] = None,
        include_extras: Optional[List[str]] = None,
        timeout_per_node: int = 30,
        retry_on_error: bool = False,
        max_retries: int = 3,
        deduplicate_shared: bool = True,
    ):
        # Core configuration
        self.max_depth = max_depth
        """Maximum recursion depth for tree traversal."""
        
        self.skip_optional = skip_optional
        """Whether to exclude optional dependencies."""
        
        self.skip_development = skip_development
        """Whether to exclude development dependencies."""
        
        self.parallel_processing = max(1, parallel_processing)
        """Number of parallel threads for processing."""
        
        self.include_stats = include_stats
        """Whether to include statistics in output."""
        
        self.build_strategy = build_strategy
        """Strategy for tree traversal."""
        
        self.cache_strategy = cache_strategy
        """Strategy for caching built nodes."""
        
        self.resolution_strategy = resolution_strategy
        """Strategy for resolving version conflicts."""
        
        self.duplicate_handling = duplicate_handling if deduplicate_shared else DuplicateHandling.SHOW_ALL
        """Strategy for handling shared dependencies."""
        
        self.deduplicate_shared = deduplicate_shared
        """Master switch for shared dependency deduplication."""
        
        self.platform_filter = platform_filter.lower() if platform_filter else None
        """Platform filter for dependency inclusion."""
        
        self.python_version_filter = python_version_filter
        """Python version filter for dependency inclusion."""
        
        self.include_extras = set(include_extras or [])
        """Set of extras to include."""
        
        self.timeout_per_node = timeout_per_node
        """Timeout in seconds per node processing."""
        
        self.retry_on_error = retry_on_error
        """Whether to retry failed package fetches."""
        
        self.max_retries = max_retries
        """Maximum retry attempts for failed fetches."""
        
        # Internal state
        self._cache: Dict[str, Dict] = {}
        """Cache storage for built nodes."""
        
        self._seen: Dict[int, Set[str]] = defaultdict(set)
        """Per-depth tracking for cycle detection."""
        
        self._seen_global: Set[str] = set()
        """Global tracking for shared dependency deduplication."""
        
        self._shared_refs: Dict[str, int] = defaultdict(int)
        """Reference counting for shared dependencies (COLLAPSE strategy)."""
        
        self._stats = BuildStats()
        """Statistics collector for the build process."""
        
        self._lock = threading.RLock()
        """Thread lock for safe concurrent access."""
        
        self._node_builders: Dict[str, Callable] = {}
        """Custom node builders for specific packages."""
        
        self._conflict_resolutions: Dict[str, str] = {}
        """Manual conflict resolution overrides."""
        
        # Log initialization
        logger.info(
            f"DependencyTreeBuilder initialized: "
            f"strategy={build_strategy.value}, "
            f"parallel={parallel_processing}, "
            f"cache={cache_strategy.value}, "
            f"duplicate_handling={self.duplicate_handling.value}, "
            f"deduplicate={deduplicate_shared}"
        )
    
    def build(self, package_name: str, context: Optional[Dict] = None) -> Optional[Dict]:
        """
        Build a complete dependency tree for the specified package.
        
        This is the main entry point for tree construction. It orchestrates the
        entire build process, applying all configured strategies and filters.
        
        Parameters
        ----------
        package_name : str
            Name of the root package to analyze. Must be a valid Python package
            name as registered on PyPI.
        
        context : Dict, optional
            Build context containing parent information, requirement specifiers,
            markers, and extras. Typically provided automatically during
            recursive traversal.
        
        Returns
        -------
        Optional[Dict]
            Dependency tree structure as a nested dictionary, or None if the
            package is not found or an error occurs. The structure includes:
            
            - name: Package name
            - version: Installed version
            - status: Installation status (installed, not_installed, error)
            - dependencies: List of child dependency dictionaries
            - Optional fields: requirement, extras, marker, depth, statistics
        
        Raises
        ------
        ValueError
            If package_name is empty, None, or not a string.
        TimeoutError
            If processing a node exceeds timeout_per_node and timeout is enabled.
        
        Examples
        --------
        >>> builder = DependencyTreeBuilder(max_depth=2)
        >>> tree = builder.build("requests")
        >>> if tree:
        ...     print(f"Root: {tree['name']} {tree['version']}")
        ...     print(f"Dependencies: {len(tree['dependencies'])}")
        Root: requests 2.28.1
        Dependencies: 3
        
        >>> # Build with context (used internally)
        >>> tree = builder.build("requests", context={'requirement': '>=2.0'})
        """
        # Input validation
        if not package_name or not isinstance(package_name, str):
            raise ValueError(f"Invalid package name: {package_name}")
        
        # Reset state for new build
        self._seen.clear()
        self._seen_global.clear()
        self._shared_refs.clear()
        
        if self.cache_strategy == CacheStrategy.NONE:
            self._cache.clear()
        
        # Reset stats for new build
        if self.include_stats:
            self._stats = BuildStats()
        
        # Start timing
        start_time = time.time()
        
        try:
            # Build tree using selected strategy
            if self.build_strategy == BuildStrategy.DEPTH_FIRST:
                result = self._build_node_depth_first(package_name, 0, context)
            elif self.build_strategy == BuildStrategy.BREADTH_FIRST:
                result = self._build_node_breadth_first(package_name, context)
            elif self.build_strategy == BuildStrategy.LAZY:
                result = self._build_node_lazy(package_name, 0, context)
            else:  # EAGER
                result = self._build_node_eager(package_name, 0, context)
            
            # Add statistics if requested
            if result and self.include_stats:
                result['statistics'] = self._calculate_statistics(result)
            
            # Finalize statistics
            self._stats.finish()
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to build tree for {package_name}: {e}")
            self._stats.record_error()
            if self.include_stats:
                return {
                    'name': package_name,
                    'status': 'error',
                    'error': str(e),
                    'statistics': self._stats.to_dict()
                }
            return None
        finally:
            if self.include_stats:
                logger.debug(self._stats.get_summary())
    
    def _build_node_depth_first(self, package_name: str, current_depth: int,
                                context: Optional[Dict] = None) -> Optional[Dict]:
        """
        Build tree using depth-first traversal (DFS).
        
        DFS processes each branch completely before moving to the next branch.
        This is memory-efficient but can be slower for very wide trees.
        
        Parameters
        ----------
        package_name : str
            Name of the package to process.
        current_depth : int
            Current depth in the tree (0 for root).
        context : Dict, optional
            Build context with parent information.
        
        Returns
        -------
        Optional[Dict]
            Built node or None if package should be skipped.
        
        Notes
        -----
        This method is recursive. For very deep trees (depth > 1000), consider
        using BREADTH_FIRST strategy to avoid recursion limits.
        """
        # Check depth limit
        if self.max_depth is not None and current_depth > self.max_depth:
            return None
        
        # Check cache
        cache_key = self._get_cache_key(package_name, current_depth, context)
        cached_node = self._get_from_cache(cache_key)
        if cached_node:
            return cached_node
        
        # Process node and get immediate dependencies
        node = self._process_node(package_name, current_depth, context)
        if not node:
            return None
        
        # Recursively process dependencies
        if node.get('dependencies'):
            processed_deps = []
            for dep in node['dependencies']:
                # Skip if this dependency should be deduplicated
                if self._should_skip_due_to_deduplication(dep['name'], current_depth + 1):
                    continue
                
                dep_node = self._build_node_depth_first(
                    dep['name'],
                    current_depth + 1,
                    {
                        'requirement': dep.get('requirement', ''),
                        'marker': dep.get('marker', ''),
                        'extras': dep.get('extras', [])
                    }
                )
                if dep_node:
                    processed_deps.append(dep_node)
            
            node['dependencies'] = processed_deps
        
        # Apply duplicate handling post-processing
        if self.deduplicate_shared:
            node = self._apply_duplicate_handling(node, current_depth)
        
        # Cache node
        self._add_to_cache(cache_key, node)
        self._stats.record_node_built()
        
        return node
    
    def _build_node_breadth_first(self, package_name: str,
                                  context: Optional[Dict] = None) -> Optional[Dict]:
        """
        Build tree using breadth-first traversal (BFS).
        
        BFS processes all nodes at the current depth before moving deeper.
        This is good for wide trees but uses more memory.
        
        Parameters
        ----------
        package_name : str
            Name of the package to process.
        context : Dict, optional
            Build context with parent information.
        
        Returns
        -------
        Optional[Dict]
            Built node or None if package should be skipped.
        """
        from collections import deque
        
        # Initialize queue with root node
        queue = deque()
        root = self._process_node(package_name, 0, context)
        if not root:
            return None
        
        queue.append((root, 0))  # (node, depth)
        nodes_by_name = {root['name']: root}
        
        while queue:
            node, depth = queue.popleft()
            
            # Check depth limit
            if self.max_depth is not None and depth >= self.max_depth:
                continue
            
            # Process dependencies
            if node.get('dependencies'):
                processed_deps = []
                for dep in node['dependencies']:
                    dep_name = dep['name']
                    
                    # Skip if this dependency should be deduplicated
                    if self._should_skip_due_to_deduplication(dep_name, depth + 1):
                        # Add reference marker instead
                        if self.duplicate_handling == DuplicateHandling.MARK_SHARED:
                            dep['status'] = 'shared_dependency'
                            processed_deps.append(dep)
                        continue
                    
                    # Check if already processed at this depth
                    if dep_name in nodes_by_name and depth + 1 <= self.max_depth_reached:
                        # Already have this node, just reference it
                        processed_deps.append(nodes_by_name[dep_name])
                        continue
                    
                    # Build dependency node
                    dep_node = self._process_node(
                        dep_name, depth + 1,
                        {
                            'requirement': dep.get('requirement', ''),
                            'marker': dep.get('marker', ''),
                            'extras': dep.get('extras', [])
                        }
                    )
                    
                    if dep_node:
                        nodes_by_name[dep_name] = dep_node
                        processed_deps.append(dep_node)
                        queue.append((dep_node, depth + 1))
                
                node['dependencies'] = processed_deps
        
        # Apply duplicate handling post-processing
        if self.deduplicate_shared:
            root = self._apply_duplicate_handling(root, 0)
        
        return root
    
    def _build_node_lazy(self, package_name: str, current_depth: int,
                         context: Optional[Dict] = None) -> Optional[Dict]:
        """
        Build tree with lazy evaluation (dependencies as placeholders).
        
        Lazy evaluation creates placeholders for dependencies instead of
        immediately processing them. This is efficient for partial tree
        exploration or interactive use.
        
        Parameters
        ----------
        package_name : str
            Name of the package to process.
        current_depth : int
            Current depth in the tree.
        context : Dict, optional
            Build context with parent information.
        
        Returns
        -------
        Optional[Dict]
            Lazy node with dependencies as placeholders.
        """
        node = self._process_node(package_name, current_depth, context)
        
        if node:
            # Replace dependencies with lazy placeholders
            if node.get('dependencies'):
                node['dependencies'] = [
                    {
                        'name': dep['name'],
                        'requirement': dep.get('requirement', ''),
                        'version': dep.get('version', 'unknown'),
                        '_lazy': True,
                        '_depth': current_depth + 1,
                        'status': 'lazy_placeholder'
                    }
                    for dep in node['dependencies']
                ]
            
            self._stats.record_node_built()
        
        return node
    
    def _build_node_eager(self, package_name: str, current_depth: int,
                          context: Optional[Dict] = None) -> Optional[Dict]:
        """
        Build tree with eager evaluation (pre-fetch all dependencies).
        
        Eager evaluation fully processes all dependencies before returning.
        This is the fastest option but uses the most memory.
        
        Parameters
        ----------
        package_name : str
            Name of the package to process.
        current_depth : int
            Current depth in the tree.
        context : Dict, optional
            Build context with parent information.
        
        Returns
        -------
        Optional[Dict]
            Fully built node with all dependencies processed.
        """
        return self._build_node_depth_first(package_name, current_depth, context)
    
    def _process_node(self, package_name: str, current_depth: int,
                     context: Optional[Dict] = None) -> Optional[Dict]:
        """
        Process a single node (package) and its immediate dependencies.
        
        This method retrieves package information, filters requirements,
        and builds the node structure without recursing into dependencies.
        
        Parameters
        ----------
        package_name : str
            Name of the package to process.
        current_depth : int
            Current depth in the tree.
        context : Dict, optional
            Build context with parent requirement information.
        
        Returns
        -------
        Optional[Dict]
            Processed node structure or None if package should be skipped.
        
        Notes
        -----
        This method handles:
        - Cycle detection
        - Package metadata retrieval
        - Requirement parsing and filtering
        - Version conflict detection
        - Status tracking
        """
        normalized_name = normalize_package_name(package_name)
        
        # Record package for uniqueness tracking
        self._stats.record_package(normalized_name)
        self._stats.record_depth(current_depth)
        
        # Add to global seen set for deduplication
        if self.deduplicate_shared and current_depth > 0:
            if normalized_name in self._seen_global:
                self._shared_refs[normalized_name] += 1
                self._stats.record_shared_dependency()
                
                # For MARK_SHARED strategy, we still want to show the node
                if self.duplicate_handling != DuplicateHandling.MARK_SHARED:
                    return None
            
            self._seen_global.add(normalized_name)
        
        # Check for cycles at this depth
        if current_depth in self._seen and normalized_name in self._seen[current_depth]:
            self._stats.record_cycle()
            logger.debug(f"Cycle detected: {package_name} at depth {current_depth}")
            
            # For MARK_SHARED strategy, return a marked cycle node
            if self.duplicate_handling == DuplicateHandling.MARK_SHARED:
                return {
                    "name": package_name,
                    "version": "unknown",
                    "status": "cycle_detected",
                    "depth": current_depth,
                    "type": self._get_dep_type_from_context(context),
                    "cycle_note": f"Circular dependency detected at depth {current_depth}",
                    "shared": True
                }
            
            return {
                "name": package_name,
                "version": "unknown",
                "status": "cycle_detected",
                "depth": current_depth,
                "type": self._get_dep_type_from_context(context),
                "cycle_note": f"Circular dependency detected at depth {current_depth}"
            }
        
        # Add to seen set for this depth
        self._seen[current_depth].add(normalized_name)
        
        # Try to get distribution with retries
        dist = self._get_distribution_with_retry(package_name)
        
        if dist is None:
            logger.debug(f"Package not installed: {package_name}")
            # Remove from seen before returning
            self._seen[current_depth].discard(normalized_name)
            
            # For MARK_SHARED strategy, return marked not installed node
            if self.duplicate_handling == DuplicateHandling.MARK_SHARED:
                return {
                    "name": package_name,
                    "version": "unknown",
                    "status": "not_installed",
                    "type": self._get_dep_type_from_context(context),
                    "depth": current_depth,
                    "requirement": context.get('requirement', '') if context else '',
                    "shared": True
                }
            
            return {
                "name": package_name,
                "version": "unknown",
                "status": "not_installed",
                "type": self._get_dep_type_from_context(context),
                "depth": current_depth,
                "requirement": context.get('requirement', '') if context else ''
            }
        
        # Build base node structure
        node = {
            "name": dist.metadata["Name"],
            "version": dist.version,
            "status": "installed",
            "type": self._get_dep_type_from_context(context),
            "depth": current_depth,
            "dependencies": [],
        }
        
        # Add shared marker if applicable
        if self.deduplicate_shared and current_depth > 0 and self._shared_refs.get(normalized_name, 0) > 0:
            if self.duplicate_handling == DuplicateHandling.MARK_SHARED:
                node["shared"] = True
                node["reference_count"] = self._shared_refs[normalized_name] + 1
        
        # Add parent context information if provided
        if context:
            if 'requirement' in context and context['requirement']:
                node["requirement"] = context['requirement']
            if 'extras' in context and context['extras']:
                node["extras"] = context['extras']
            if 'marker' in context and context['marker']:
                node["marker"] = context['marker']
        
        # Process requirements (dependencies)
        try:
            requires = dist.requires or []
            requirements_to_process = self._filter_requirements(requires, node)
            
            # Process dependencies based on parallel setting
            if self.parallel_processing > 1 and len(requirements_to_process) > 1:
                node["dependencies"] = self._process_requirements_parallel(
                    requirements_to_process, current_depth
                )
            else:
                node["dependencies"] = self._process_requirements_sequential(
                    requirements_to_process, current_depth
                )
            
            # Resolve conflicts if multiple dependencies for same package
            node["dependencies"] = self._resolve_conflicts(node["dependencies"])
            
        except Exception as e:
            logger.error(f"Error processing requirements for {package_name}: {e}")
            self._stats.record_error()
            node["status"] = "error"
            node["error"] = str(e)
        finally:
            # Remove from seen set after processing
            self._seen[current_depth].discard(normalized_name)
        
        return node
    
    def _should_skip_due_to_deduplication(self, package_name: str, depth: int) -> bool:
        """
        Determine if a package should be skipped due to deduplication.
        
        This method implements the duplicate handling strategies by checking
        whether a package has been seen before and whether it should be
        included again based on the configured strategy.
        
        Parameters
        ----------
        package_name : str
            Name of the package to check.
        depth : int
            Current depth in the tree.
        
        Returns
        -------
        bool
            True if the package should be skipped (not added to tree),
            False if it should be included.
        
        Notes
        -----
        Different strategies have different behaviors:
        - SHOW_ALL: Never skip
        - DEDUPLICATE: Skip if seen at same depth
        - MERGE: Skip if seen anywhere (will be referenced instead)
        - MARK_SHARED: Never skip (but will be marked)
        - COLLAPSE: Skip if seen anywhere (will be collapsed)
        """
        if not self.deduplicate_shared:
            return False
        
        normalized_name = normalize_package_name(package_name)
        
        if self.duplicate_handling == DuplicateHandling.SHOW_ALL:
            return False
        
        elif self.duplicate_handling == DuplicateHandling.DEDUPLICATE:
            # Skip only if seen at the same depth
            return depth in self._seen and normalized_name in self._seen[depth]
        
        elif self.duplicate_handling == DuplicateHandling.MERGE:
            # Skip if seen anywhere in the tree
            return normalized_name in self._seen_global
        
        elif self.duplicate_handling == DuplicateHandling.MARK_SHARED:
            # Never skip, but mark as shared
            return False
        
        elif self.duplicate_handling == DuplicateHandling.COLLAPSE:
            # Skip if seen anywhere (will be collapsed with count)
            return normalized_name in self._seen_global
        
        return False
    
    def _apply_duplicate_handling(self, node: Dict, depth: int) -> Dict:
        """
        Apply duplicate handling post-processing to a node.
        
        This method modifies the node structure based on the duplicate
        handling strategy, adding reference counts or collapse markers.
        
        Parameters
        ----------
        node : Dict
            The node to process.
        depth : int
            Current depth of the node.
        
        Returns
        -------
        Dict
            Processed node with duplicate handling applied.
        
        Notes
        -----
        For COLLAPSE strategy, this method adds a 'collapsed' flag and
        'reference_count' to indicate how many times this package appears.
        """
        if not self.deduplicate_shared:
            return node
        
        normalized_name = normalize_package_name(node.get('name', ''))
        
        if self.duplicate_handling == DuplicateHandling.COLLAPSE:
            ref_count = self._shared_refs.get(normalized_name, 0)
            if ref_count > 0:
                node['collapsed'] = True
                node['reference_count'] = ref_count + 1  # +1 for current occurrence
                node['dependencies'] = []  # Clear dependencies for collapsed nodes
        
        elif self.duplicate_handling == DuplicateHandling.MERGE:
            if normalized_name in self._seen_global and depth > 0:
                node['merged'] = True
                node['reference'] = f"see_{normalized_name}"
        
        return node
    
    def _get_distribution_with_retry(self, package_name: str) -> Optional[Any]:
        """
        Get package distribution with retry logic for reliability.
        
        This method attempts to fetch package distribution information with
        configurable retry logic to handle transient failures like network
        timeouts or temporary unavailability.
        
        Parameters
        ----------
        package_name : str
            Name of the package to fetch.
        
        Returns
        -------
        Optional[Any]
            Distribution object if successful, None if package not found
            or all retries exhausted.
        
        Raises
        ------
        TimeoutError
            If timeout_per_node is set and the operation exceeds the timeout.
        
        Notes
        -----
        Retry uses exponential backoff: 0.5s, 1.0s, 2.0s, etc.
        Timeout is implemented using SIGALRM on Unix systems only.
        """
        for attempt in range(self.max_retries if self.retry_on_error else 1):
            try:
                # Use timeout if specified and on Unix
                if self.timeout_per_node > 0:
                    import signal
                    
                    def timeout_handler(signum, frame):
                        raise TimeoutError(f"Timeout ({self.timeout_per_node}s) fetching {package_name}")
                    
                    # Set timeout (Unix only)
                    if hasattr(signal, 'SIGALRM'):
                        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                        signal.alarm(self.timeout_per_node)
                
                # Fetch distribution
                dist = PackageCache().get_distribution(package_name)
                
                # Cancel alarm
                if self.timeout_per_node > 0 and hasattr(signal, 'SIGALRM'):
                    signal.alarm(0)
                    if hasattr(signal, 'SIGALRM'):
                        signal.signal(signal.SIGALRM, old_handler)
                
                return dist
                
            except TimeoutError as e:
                logger.warning(f"Timeout on attempt {attempt + 1} for {package_name}: {e}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {package_name}: {e}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(0.5 * (attempt + 1))
        
        return None
    
    def _filter_requirements(self, requirements: List[str], 
                            parent_node: Dict) -> List[Tuple]:
        """
        Filter and parse requirements based on configured filters.
        
        This method applies all configured filters (optional, development,
        platform, Python version, extras) to the raw requirement strings
        and returns only those that pass all filters.
        
        Parameters
        ----------
        requirements : List[str]
            Raw requirement strings from the package metadata.
        parent_node : Dict
            Parent node information for context.
        
        Returns
        -------
        List[Tuple]
            List of filtered requirement tuples, each containing:
            - child_name: Normalized package name
            - req_spec: Version requirement specifier
            - extras: List of extras
            - marker: Environment marker string
            - dep_type: DependencyType enum value
        
        Notes
        -----
        Requirements that fail any filter are silently excluded.
        Invalid requirements (cannot be parsed) are also excluded.
        """
        filtered = []
        
        for req in requirements:
            child_name, req_spec, extras, marker = parse_requirement(req)
            if not child_name:
                logger.debug(f"Skipping invalid requirement: {req}")
                continue
            
            # Apply optional dependency filter
            if self.skip_optional and not should_include_requirement(
                req_spec, marker, skip_optional=True
            ):
                logger.debug(f"Skipping optional dependency: {child_name}")
                continue
            
            # Apply development dependency filter
            if self.skip_development and not should_include_requirement(
                req_spec, marker, skip_development=True
            ):
                logger.debug(f"Skipping development dependency: {child_name}")
                continue
            
            # Apply platform filter
            if self.platform_filter and not should_include_requirement(
                req_spec, marker, platform_filter=self.platform_filter
            ):
                logger.debug(f"Skipping platform-specific dependency: {child_name}")
                continue
            
            # Apply Python version filter
            if self.python_version_filter and not should_include_requirement(
                req_spec, marker, python_version_filter=self.python_version_filter
            ):
                logger.debug(f"Skipping Python version-specific dependency: {child_name}")
                continue
            
            # Apply extras filter
            if self.include_extras and extras:
                if not any(extra in self.include_extras for extra in extras):
                    logger.debug(f"Skipping extra {extras} for {child_name}")
                    continue
            
            # Determine dependency type from marker
            dep_type = self._determine_dependency_type(marker)
            
            filtered.append((child_name, req_spec, extras, marker, dep_type))
        
        return filtered
    
    def _determine_dependency_type(self, marker: str) -> DependencyType:
        """
        Determine the dependency type from environment marker.
        
        Analyzes the environment marker string to classify the dependency
        into one of the DependencyType categories.
        
        Parameters
        ----------
        marker : str
            Environment marker string (PEP 508).
        
        Returns
        -------
        DependencyType
            Classified dependency type.
        
        Notes
        -----
        Classification rules:
        - Contains 'extra' or 'optional' -> OPTIONAL
        - Contains 'dev', 'test', 'docs', etc. -> DEVELOPMENT
        - Contains 'peer' or 'compatible' -> PEER
        - Contains 'recommended' -> RECOMMENDED
        - Default -> REQUIRED
        """
        marker_lower = marker.lower()
        
        if "extra" in marker_lower or "optional" in marker_lower:
            return DependencyType.OPTIONAL
        elif any(keyword in marker_lower for keyword in ["dev", "test", "testing", "docs", "doc"]):
            return DependencyType.DEVELOPMENT
        elif any(keyword in marker_lower for keyword in ["peer", "compatible"]):
            return DependencyType.PEER
        elif "recommended" in marker_lower:
            return DependencyType.RECOMMENDED
        
        return DependencyType.REQUIRED
    
    def _get_dep_type_from_context(self, context: Optional[Dict]) -> str:
        """
        Extract dependency type from build context.
        
        Parameters
        ----------
        context : Dict, optional
            Build context containing dependency type information.
        
        Returns
        -------
        str
            Dependency type as string (e.g., 'required', 'optional').
        """
        if context and 'dep_type' in context:
            return context['dep_type']
        return DependencyType.REQUIRED.value
    
    def _process_requirements_sequential(self, requirements: List[Tuple],
                                         current_depth: int) -> List[Dict]:
        """
        Process requirements sequentially (no parallelism).
        
        This method processes each requirement one after another. It's
        simpler and uses less memory than parallel processing.
        
        Parameters
        ----------
        requirements : List[Tuple]
            List of requirement tuples from _filter_requirements.
        current_depth : int
            Current depth in the tree.
        
        Returns
        -------
        List[Dict]
            List of child nodes built from the requirements.
        """
        dependencies = []
        
        for child_name, req_spec, extras, marker, dep_type in requirements:
            context = {
                'requirement': req_spec,
                'extras': extras,
                'marker': marker,
                'dep_type': dep_type.value
            }
            
            child_node = self._build_node_depth_first(
                child_name, current_depth + 1, context
            )
            
            if child_node:
                dependencies.append(child_node)
        
        return dependencies
    
    def _process_requirements_parallel(self, requirements: List[Tuple],
                                       current_depth: int) -> List[Dict]:
        """
        Process requirements in parallel using thread pool.
        
        This method uses ThreadPoolExecutor to process multiple requirements
        simultaneously, significantly improving performance for large trees.
        
        Parameters
        ----------
        requirements : List[Tuple]
            List of requirement tuples from _filter_requirements.
        current_depth : int
            Current depth in the tree.
        
        Returns
        -------
        List[Dict]
            List of child nodes built from the requirements.
        
        Notes
        -----
        Each requirement is submitted to the thread pool as a separate task.
        Results are collected as they complete (not in original order).
        Timeout per node is enforced.
        """
        dependencies = []
        
        with ThreadPoolExecutor(max_workers=self.parallel_processing) as executor:
            future_to_req = {}
            
            for child_name, req_spec, extras, marker, dep_type in requirements:
                context = {
                    'requirement': req_spec,
                    'extras': extras,
                    'marker': marker,
                    'dep_type': dep_type.value
                }
                
                future = executor.submit(
                    self._build_node_depth_first,
                    child_name, current_depth + 1, context
                )
                future_to_req[future] = child_name
            
            for future in as_completed(future_to_req):
                try:
                    child_node = future.result(timeout=self.timeout_per_node)
                    if child_node:
                        dependencies.append(child_node)
                except Exception as e:
                    child_name = future_to_req[future]
                    logger.error(f"Failed to process {child_name}: {e}")
                    self._stats.record_error()
                    
                    # Add error node to maintain tree completeness
                    dependencies.append({
                        'name': child_name,
                        'version': 'unknown',
                        'status': 'error',
                        'error': str(e),
                        'depth': current_depth + 1
                    })
        
        return dependencies
    
    def _resolve_conflicts(self, dependencies: List[Dict]) -> List[Dict]:
        """
        Resolve version conflicts when packages appear multiple times.
        
        When the same package appears multiple times in the dependency list
        (different parent requirements), this method determines which version
        to keep based on the resolution strategy.
        
        Parameters
        ----------
        dependencies : List[Dict]
            List of dependency nodes that may contain duplicates.
        
        Returns
        -------
        List[Dict]
            Deduplicated list of dependencies after conflict resolution.
        
        Notes
        -----
        Strategies:
        - HIGHEST: Keep the highest version number
        - LOWEST: Keep the lowest version number
        - FIRST: Keep the first occurrence
        - USER: Merge requirements and mark conflict for manual resolution
        """
        if not dependencies:
            return dependencies
        
        # Group by package name
        by_package: Dict[str, List[Dict]] = defaultdict(list)
        for dep in dependencies:
            by_package[dep['name']].append(dep)
        
        resolved = []
        
        for package_name, versions in by_package.items():
            if len(versions) == 1:
                resolved.append(versions[0])
                continue
            
            # Check for manual resolution override
            if package_name in self._conflict_resolutions:
                preferred = self._conflict_resolutions[package_name]
                for version in versions:
                    if version.get('version') == preferred:
                        resolved.append(version)
                        break
                else:
                    # Preferred version not found, use first
                    resolved.append(versions[0])
                continue
            
            # Auto-resolve based on strategy
            def version_key(v):
                try:
                    from packaging.version import parse
                    return parse(v.get('version', '0'))
                except:
                    return v.get('version', '0')
            
            if self.resolution_strategy == ResolutionStrategy.HIGHEST:
                chosen = max(versions, key=version_key)
                
            elif self.resolution_strategy == ResolutionStrategy.LOWEST:
                chosen = min(versions, key=version_key)
                
            elif self.resolution_strategy == ResolutionStrategy.FIRST:
                chosen = versions[0]
                
            else:  # USER strategy
                chosen = versions[0].copy()
                # Merge requirement information
                reqs = [v.get('requirement', '') for v in versions if v.get('requirement')]
                chosen['requirement'] = ', '.join(reqs) if reqs else ''
                chosen['conflict'] = True
                chosen['conflicting_versions'] = [v.get('version', 'unknown') for v in versions]
            
            resolved.append(chosen)
            logger.debug(
                f"Resolved conflict for {package_name}: "
                f"{len(versions)} versions -> {chosen.get('version', 'unknown')}"
            )
        
        return resolved
    
    def _calculate_statistics(self, node: Dict) -> Dict:
        """
        Calculate comprehensive statistics for a tree node.
        
        This method traverses the entire tree starting from the given node
        and collects various metrics about the dependency structure.
        
        Parameters
        ----------
        node : Dict
            Root node of the tree to analyze.
        
        Returns
        -------
        Dict
            Statistics dictionary containing:
            - total_dependencies: Total number of nodes
            - max_depth: Maximum depth of the tree
            - by_status: Counts by status (installed, not_installed, etc.)
            - by_type: Counts by dependency type
            - by_dependency_count: Distribution of dependency counts
            - average_dependencies: Average number of dependencies per node
        
        Examples
        --------
        >>> stats = builder._calculate_statistics(tree)
        >>> print(f"Total: {stats['total_dependencies']}")
        >>> print(f"Max depth: {stats['max_depth']}")
        """
        stats = {
            "total_dependencies": 0,
            "max_depth": 0,
            "by_status": {},
            "by_type": {t.value: 0 for t in DependencyType},
            "by_dependency_count": {},
            "average_dependencies": 0.0
        }
        
        total_dep_count = 0
        
        def traverse(subnode: Dict, depth: int = 0):
            nonlocal total_dep_count
            
            stats["total_dependencies"] += 1
            stats["max_depth"] = max(stats["max_depth"], depth)
            
            # Track status
            status = subnode.get("status", "unknown")
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
            
            # Track type
            dep_type = subnode.get("type", DependencyType.REQUIRED.value)
            if dep_type in stats["by_type"]:
                stats["by_type"][dep_type] += 1
            
            # Track dependency count distribution
            dep_count = len(subnode.get("dependencies", []))
            stats["by_dependency_count"][dep_count] = stats["by_dependency_count"].get(dep_count, 0) + 1
            total_dep_count += dep_count
            
            for dep in subnode.get("dependencies", []):
                traverse(dep, depth + 1)
        
        traverse(node)
        
        # Calculate average dependencies
        if stats["total_dependencies"] > 0:
            stats["average_dependencies"] = total_dep_count / stats["total_dependencies"]
        
        return stats
    
    def _get_cache_key(self, package_name: str, depth: int,
                       context: Optional[Dict] = None) -> str:
        """
        Generate a cache key for a node.
        
        The cache key uniquely identifies a node based on package name,
        depth, and relevant context information. Different cache strategies
        produce different key formats.
        
        Parameters
        ----------
        package_name : str
            Name of the package.
        depth : int
            Current depth in the tree.
        context : Dict, optional
            Build context (affects memoization key).
        
        Returns
        -------
        str
            Cache key string, or empty string if caching is disabled.
        
        Notes
        -----
        Key formats by strategy:
        - NODE: package_name
        - SUBTREE: package_name:depth:depth
        - MEMOIZE: package_name:depth:depth:filters
        - NONE: "" (no caching)
        """
        if self.cache_strategy == CacheStrategy.NONE:
            return ""
        
        # Normalize package name
        key = normalize_package_name(package_name)
        
        if self.cache_strategy == CacheStrategy.NODE:
            return key
        
        if self.cache_strategy == CacheStrategy.SUBTREE:
            return f"{key}:depth:{depth}"
        
        if self.cache_strategy == CacheStrategy.MEMOIZE:
            # Include filter settings in key for memoization
            filters = f"opt:{self.skip_optional}:dev:{self.skip_development}"
            if self.platform_filter:
                filters += f":plat:{self.platform_filter}"
            if self.python_version_filter:
                filters += f":py:{self.python_version_filter}"
            return f"{key}:depth:{depth}:{filters}"
        
        return key
    
    def _get_from_cache(self, cache_key: str) -> Optional[Dict]:
        """
        Retrieve a node from the cache.
        
        Parameters
        ----------
        cache_key : str
            Cache key generated by _get_cache_key.
        
        Returns
        -------
        Optional[Dict]
            Cached node if found and not expired, None otherwise.
        """
        if not cache_key or self.cache_strategy == CacheStrategy.NONE:
            return None
        
        with self._lock:
            if cache_key in self._cache:
                self._stats.record_cache_hit()
                logger.debug(f"Cache hit: {cache_key}")
                # Return a copy to prevent modification of cached data
                import copy
                return copy.deepcopy(self._cache[cache_key])
        
        self._stats.record_cache_miss()
        return None
    
    def _add_to_cache(self, cache_key: str, node: Dict) -> None:
        """
        Add a node to the cache.
        
        Parameters
        ----------
        cache_key : str
            Cache key generated by _get_cache_key.
        node : Dict
            Node to cache (will be deep copied).
        """
        if not cache_key or self.cache_strategy == CacheStrategy.NONE:
            return
        
        with self._lock:
            import copy
            self._cache[cache_key] = copy.deepcopy(node)
            logger.debug(f"Cached: {cache_key}")
    
    def register_node_builder(self, package_name: str, 
                              builder: Callable[[str, int, Optional[Dict]], Optional[Dict]]) -> None:
        """
        Register a custom node builder for specific packages.
        
        This allows overriding the default package processing logic for
        specific packages or package patterns (supports wildcards).
        
        Parameters
        ----------
        package_name : str
            Package name pattern (supports '*' wildcards).
            Examples: 'virtual-*', '*-test', 'mypackage'
        builder : Callable
            Custom builder function that takes (name, depth, context) and
            returns a node dictionary or None.
        
        Examples
        --------
        >>> def custom_builder(name, depth, context):
        ...     return {
        ...         'name': name,
        ...         'version': 'custom',
        ...         'status': 'virtual',
        ...         'dependencies': []
        ...     }
        >>> builder = DependencyTreeBuilder()
        >>> builder.register_node_builder('virtual-*', custom_builder)
        """
        self._node_builders[package_name] = builder
        logger.debug(f"Registered custom builder for pattern: {package_name}")
    
    def set_conflict_resolution(self, package_name: str, version: str) -> None:
        """
        Manually set conflict resolution for a package.
        
        When multiple versions of the same package are required, this
        forces the builder to use the specified version.
        
        Parameters
        ----------
        package_name : str
            Name of the package to resolve.
        version : str
            Preferred version to use when conflicts occur.
        
        Examples
        --------
        >>> builder = DependencyTreeBuilder(
        ...     resolution_strategy=ResolutionStrategy.USER
        ... )
        >>> builder.set_conflict_resolution('requests', '2.28.1')
        >>> builder.set_conflict_resolution('urllib3', '1.26.13')
        """
        self._conflict_resolutions[package_name] = version
        logger.info(f"Set conflict resolution for {package_name} to version {version}")
    
    def get_stats(self) -> BuildStats:
        """
        Get build statistics for the last tree built.
        
        Returns
        -------
        BuildStats
            Statistics object containing performance metrics.
        
        Notes
        -----
        Statistics are only collected if include_stats=True was passed
        to the constructor. Otherwise, the stats object will have zeros.
        
        Examples
        --------
        >>> builder = DependencyTreeBuilder(include_stats=True)
        >>> tree = builder.build("requests")
        >>> stats = builder.get_stats()
        >>> print(f"Nodes built: {stats.nodes_built}")
        >>> print(f"Cache hit rate: {stats.cache_hits / (stats.cache_hits + stats.cache_misses) * 100:.1f}%")
        """
        return self._stats
    
    def clear_cache(self) -> None:
        """Clear all cached nodes from memory."""
        with self._lock:
            self._cache.clear()
            logger.info("Cache cleared")
    
    def get_cache_size(self) -> int:
        """
        Get the current number of cached nodes.
        
        Returns
        -------
        int
            Number of nodes currently in the cache.
        """
        return len(self._cache)
    
    def get_build_summary(self) -> Dict[str, Any]:
        """
        Get a comprehensive build summary including statistics and configuration.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - statistics: Performance metrics
            - configuration: Builder configuration settings
            - cache: Cache information
        """
        return {
            'statistics': self._stats.to_dict(),
            'configuration': {
                'max_depth': self.max_depth,
                'skip_optional': self.skip_optional,
                'skip_development': self.skip_development,
                'parallel_processing': self.parallel_processing,
                'build_strategy': self.build_strategy.value,
                'cache_strategy': self.cache_strategy.value,
                'resolution_strategy': self.resolution_strategy.value,
                'duplicate_handling': self.duplicate_handling.value,
                'deduplicate_shared': self.deduplicate_shared,
                'platform_filter': self.platform_filter,
                'python_version_filter': self.python_version_filter,
                'include_extras': list(self.include_extras)
            },
            'cache': {
                'size': self.get_cache_size(),
                'max_capacity': None  # Unlimited for now
            }
        }


# =============================================================================
# CONVENIENCE FUNCTIONS FOR BACKWARD COMPATIBILITY
# =============================================================================

def build_dependency_tree(package_name: str, **kwargs) -> Optional[Dict]:
    """
    Convenience function to build a dependency tree.
    
    This is a one-liner wrapper around DependencyTreeBuilder for quick use
    without creating a builder instance manually.
    
    Parameters
    ----------
    package_name : str
        Name of the package to analyze.
    **kwargs
        Arguments passed to DependencyTreeBuilder constructor.
    
    Returns
    -------
    Optional[Dict]
        Dependency tree or None if build fails.
    
    Examples
    --------
    >>> tree = build_dependency_tree('requests', max_depth=2)
    >>> print(tree['name'])
    'requests'
    
    >>> # With deduplication
    >>> tree = build_dependency_tree(
    ...     'pandas',
    ...     deduplicate_shared=True,
    ...     duplicate_handling=DuplicateHandling.MERGE
    ... )
    """
    builder = DependencyTreeBuilder(**kwargs)
    return builder.build(package_name)


def get_tree_stats(tree: Dict) -> Dict[str, Any]:
    """
    Calculate statistics for an existing tree.
    
    Parameters
    ----------
    tree : Dict
        Dependency tree dictionary to analyze.
    
    Returns
    -------
    Dict[str, Any]
        Statistics dictionary with metrics about the tree.
    
    Examples
    --------
    >>> tree = build_dependency_tree('requests')
    >>> stats = get_tree_stats(tree)
    >>> print(f"Total packages: {stats['total_dependencies']}")
    >>> print(f"Max depth: {stats['max_depth']}")
    """
    builder = DependencyTreeBuilder(include_stats=True)
    return builder._calculate_statistics(tree)


def merge_trees(tree1: Dict, tree2: Dict, strategy: str = 'union') -> Dict:
    """
    Merge two dependency trees using the specified strategy.
    
    Parameters
    ----------
    tree1 : Dict
        First dependency tree.
    tree2 : Dict
        Second dependency tree.
    strategy : str, default='union'
        Merge strategy:
        - 'union': Combine dependencies from both trees (no duplicates)
        - 'intersection': Keep only dependencies present in both trees
        - 'override': Second tree overrides first for conflicting keys
        - 'deep': Recursively merge nested dependencies
    
    Returns
    -------
    Dict
        Merged dependency tree.
    
    Examples
    --------
    >>> tree1 = {'name': 'app', 'dependencies': [{'name': 'requests'}]}
    >>> tree2 = {'name': 'app', 'dependencies': [{'name': 'django'}]}
    >>> merged = merge_trees(tree1, tree2, strategy='union')
    >>> len(merged['dependencies'])
    2
    """
    if strategy == 'override':
        return {**tree1, **tree2}
    
    if strategy == 'union':
        merged = tree1.copy()
        if 'dependencies' in tree1 and 'dependencies' in tree2:
            dep_names = {dep['name'] for dep in tree1['dependencies']}
            merged['dependencies'] = tree1['dependencies'][:]
            
            for dep in tree2['dependencies']:
                if dep['name'] not in dep_names:
                    merged['dependencies'].append(dep)
        
        return merged
    
    if strategy == 'intersection':
        if 'dependencies' not in tree1 or 'dependencies' not in tree2:
            return tree1.copy()
        
        merged = tree1.copy()
        dep_names1 = {dep['name'] for dep in tree1['dependencies']}
        dep_names2 = {dep['name'] for dep in tree2['dependencies']}
        common = dep_names1 & dep_names2
        
        merged['dependencies'] = [
            dep for dep in tree1['dependencies'] 
            if dep['name'] in common
        ]
        return merged
    
    if strategy == 'deep':
        # Recursive deep merge
        merged = tree1.copy()
        if 'dependencies' in tree1 and 'dependencies' in tree2:
            dep_map = {dep['name']: dep for dep in tree1['dependencies']}
            for dep2 in tree2['dependencies']:
                if dep2['name'] in dep_map:
                    dep_map[dep2['name']] = merge_trees(
                        dep_map[dep2['name']], dep2, 'deep'
                    )
                else:
                    dep_map[dep2['name']] = dep2
            merged['dependencies'] = list(dep_map.values())
        
        return merged
    
    # Default: return first tree
    return tree1


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
logger.debug("Dependency tree builder module initialized")


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    'BuildStrategy',
    'ResolutionStrategy', 
    'CacheStrategy',
    'DuplicateHandling',
    
    # Data classes
    'BuildStats',
    
    # Main class
    'DependencyTreeBuilder',
    
    # Convenience functions
    'build_dependency_tree',
    'get_tree_stats',
    'merge_trees'
]