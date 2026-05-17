# PyUtil Tree Module Documentation

## Overview

PyUtil Tree is a comprehensive, production-grade toolkit for building, analyzing, visualizing, and exporting Python package dependency trees. It provides advanced capabilities for dependency resolution, conflict detection, tree traversal, and multiple output formats with beautiful terminal rendering.

## Why Use This Module?

| Use Case | Solution |
|----------|----------|
| **Dependency Analysis** | Understand what packages your project depends on |
| **Conflict Detection** | Find version conflicts and circular dependencies |
| **Documentation** | Generate dependency diagrams for README files |
| **CI/CD Integration** | Validate dependencies in build pipelines |
| **Audit & Compliance** | Track and analyze dependency trees |
| **Performance Optimization** | Identify redundant or deep dependencies |

## Architecture

The tree module consists of several interconnected submodules:

```

┌─────────────────────────────────────────────────────────────────────┐
│                         pyputil.tree                                  │
├───────────────┬───────────────┬───────────────┬─────────────────────┤
│   analyzer.py │   builder.py  │   printer.py  │   (legacy modules)   │
│  (Analysis)   │ (Construction)│ (Visualization)│                     │
├───────────────┴───────────────┴───────────────┴─────────────────────┤
│                        Core Components                               │
├─────────────────────────────────────────────────────────────────────┤
│ • PackageCache - Cached distribution metadata                       │
│ • Requirement parsing - PEP 508 compliance                          │
│ • Platform filtering - OS, Python version, extras                   │
│ • Parallel processing - Thread pool for performance                 │
└─────────────────────────────────────────────────────────────────────┘

```

---

## 1. Analyzer Module (`analyzer.py`)

### What It Does

Provides comprehensive analysis of dependency trees including conflict detection, metrics calculation, cycle detection, impact analysis, and health scoring.

### Why Use It

- **Find Problems**: Detect version conflicts, circular dependencies, missing packages
- **Measure Quality**: Calculate health scores and identify areas for improvement
- **Understand Impact**: See which packages would be affected by changes
- **Get Recommendations**: Actionable suggestions for fixing issues

### Key Classes

```python
from pyputil.tree import (
    DependencyAnalyzer,
    ConflictInfo,
    ConflictType,
    TreeMetrics
)
```

Usage Examples

```python
from pyputil.tree import DependencyAnalyzer, analyze_tree_comprehensive

# Load your dependency tree (from builder or other source)
tree = load_dependency_tree()  # Your tree dictionary

# Create analyzer
analyzer = DependencyAnalyzer(tree, enable_caching=True)

# Find all conflicts
conflicts = analyzer.find_conflicts()
for conflict in conflicts:
    print(f"{conflict.package_name}: {conflict.conflict_type.value}")
    print(f"  Versions: {conflict.different_versions}")
    if conflict.resolution_suggestion:
        print(f"  Suggestion: {conflict.resolution_suggestion}")

# Calculate tree metrics
metrics = analyzer.calculate_metrics()
print(metrics.summarize())
# ==================================================
# Dependency Tree Metrics Summary
# ==================================================
# Total Packages: 42
# Unique Packages: 38
# Max Depth: 5
# Average Depth: 2.15
# Max Breadth: 12
# Circular Dependencies: 0
# ==================================================

# Detect cycles
cycles = analyzer.detect_cycles()
for cycle in cycles:
    print(f"Cycle: {' -> '.join(cycle)}")

# Find impacted packages
impacted = analyzer.find_impacted_packages('requests')
print(f"Packages depending on requests: {impacted}")

# Get orphaned packages (required but not installed)
orphans = analyzer.find_orphaned_packages()
if orphans:
    print(f"Missing packages: {orphans}")

# Comprehensive analysis
analysis = analyze_tree_comprehensive(tree)
print(f"Health score: {analysis['health_score']}/100")
print(f"Health grade: {analysis['health_grade']}")
print(f"Conflicts: {analysis['conflict_count']}")
print(f"Circular dependencies: {analysis['circular_count']}")
print(f"Recommendations: {analysis['recommendations']}")

# Export analysis results
json_output = analyzer.export_analysis('json')
with open('analysis.json', 'w') as f:
    f.write(json_output)

# Get performance stats
stats = analyzer.get_performance_stats()
print(f"Cache hit rate: {stats['cache_hit_rate']:.2%}")
```

---

2. Builder Module (builder.py)

What It Does

Provides a powerful engine for constructing Python package dependency trees with support for multiple build strategies, intelligent caching, conflict resolution, and parallel processing.

Why Use It

· Build Trees: Create dependency trees from any Python package
· Control Depth: Limit recursion depth for large trees
· Filter Dependencies: Skip optional, development, or platform-specific deps
· Resolve Conflicts: Automatically handle version conflicts
· Optimize Performance: Use caching and parallel processing

Enumerations

```python
from pyputil.tree import (
    BuildStrategy,
    ResolutionStrategy,
    CacheStrategy,
    DuplicateHandling
)

# Build strategies
BuildStrategy.DEPTH_FIRST   # Process each branch completely
BuildStrategy.BREADTH_FIRST # Process all nodes at current depth
BuildStrategy.LAZY          # Build on-demand (memory efficient)
BuildStrategy.EAGER         # Pre-fetch everything (fastest)

# Resolution strategies
ResolutionStrategy.HIGHEST  # Choose highest version (recommended)
ResolutionStrategy.LOWEST   # Choose lowest version (conservative)
ResolutionStrategy.FIRST    # Choose first encountered (fastest)
ResolutionStrategy.USER     # Manual resolution required

# Cache strategies
CacheStrategy.NONE          # No caching
CacheStrategy.NODE          # Cache individual nodes
CacheStrategy.SUBTREE       # Cache entire subtrees
CacheStrategy.MEMOIZE       # Most aggressive caching

# Duplicate handling
DuplicateHandling.SHOW_ALL      # Show every occurrence
DuplicateHandling.DEDUPLICATE   # Show once per depth
DuplicateHandling.MERGE         # Merge with references
DuplicateHandling.MARK_SHARED   # Mark with [shared] tag
DuplicateHandling.COLLAPSE      # Collapse with [xN] count
```

Usage Examples

```python
from pyputil.tree import (
    DependencyTreeBuilder,
    BuildStrategy,
    ResolutionStrategy,
    DuplicateHandling,
    build_dependency_tree
)

# Basic builder
builder = DependencyTreeBuilder(max_depth=3)
tree = builder.build("requests")
print(tree['name'])  # 'requests'

# Advanced configuration with deduplication
builder = DependencyTreeBuilder(
    max_depth=5,
    skip_optional=True,
    skip_development=True,
    parallel_processing=4,
    build_strategy=BuildStrategy.BREADTH_FIRST,
    resolution_strategy=ResolutionStrategy.HIGHEST,
    deduplicate_shared=True,
    duplicate_handling=DuplicateHandling.MERGE,
    platform_filter='linux',
    include_stats=True
)

tree = builder.build("scikit-learn")

# Get build statistics
stats = builder.get_stats()
print(stats.get_summary())
# ==================================================
# Build Statistics Summary
# ==================================================
# Total Nodes Built: 156
# Unique Packages: 87
# Max Depth Reached: 6
# Cache Hits: 42
# Cache Misses: 114
# Cache Hit Rate: 26.9%
# Deduplications Saved: 23
# Build Time: 2.345 seconds
# ==================================================

# Manual conflict resolution
builder = DependencyTreeBuilder(
    resolution_strategy=ResolutionStrategy.USER
)
builder.set_conflict_resolution('requests', '2.28.1')
builder.set_conflict_resolution('urllib3', '1.26.13')
tree = builder.build("myapp")

# Register custom node builder
def custom_builder(name, depth, context):
    return {
        'name': name,
        'version': 'custom',
        'status': 'virtual',
        'dependencies': []
    }

builder.register_node_builder('virtual-*', custom_builder)

# Convenience function (one-liner)
tree = build_dependency_tree('pandas', max_depth=2, deduplicate_shared=True)

# Merge two trees
tree1 = build_dependency_tree('requests')
tree2 = build_dependency_tree('urllib3')
merged = merge_trees(tree1, tree2, strategy='union')

# Clear cache
builder.clear_cache()
```

---

3. Printer Module (printer.py)

What It Does

Provides beautiful, professional terminal output for dependency trees with support for Unicode/ASCII characters, ANSI colors, multiple output formats (JSON, HTML, DOT, Mermaid, Markdown), and advanced deduplication strategies.

Why Use It

· Visualize Trees: See dependency structure clearly in terminal
· Export Reports: Generate HTML, JSON, or Markdown documentation
· Create Diagrams: Export to Graphviz DOT or Mermaid for diagrams
· Reduce Clutter: Deduplicate shared dependencies with 5 strategies
· Integrate: Use output in CI/CD, documentation, or web apps

Key Classes

```python
from pyputil.tree import (
    DependencyTreePrinter,
    TreeStyle,
    TreeNode,
    DuplicateHandling,
    TreeOutputFormat
)
```

TreeStyle Configuration

```python
from pyputil.tree import TreeStyle

# Default style (Unicode, no colors)
style = TreeStyle()

# Colorful style with all features
style = TreeStyle(
    use_unicode=True,
    indent_size=2,
    show_versions=True,
    show_requirements=True,
    show_status=True,
    show_extras=True,
    show_markers=True,
    colorize=True,
    compress_duplicates=True
)

# ASCII style for log files
ascii_style = TreeStyle(
    use_unicode=False,
    indent_size=1,
    show_versions=False,
    show_status=False
)

# Minimal style (just package names)
minimal_style = TreeStyle(
    show_versions=False,
    show_requirements=False,
    show_status=False,
    show_extras=False
)
```

Duplicate Handling Strategies

Strategy Description Best For
SHOW_ALL Show every occurrence Debugging, complete accuracy
DEDUPLICATE Show once per depth General use, cleaner output
MERGE Merge with [see above] Large trees, structure focus
MARK_SHARED Mark with [shared] Analysis, finding reuse
COLLAPSE Collapse with [xN] Overview, summary reports

Usage Examples

```python
from pyputil.tree import (
    DependencyTreePrinter,
    TreeStyle,
    DuplicateHandling,
    TreeOutputFormat,
    print_dep_tree,
    export_tree_to_file
)

# Basic printer
printer = DependencyTreePrinter(max_depth=3)
printer.print_tree("requests")
# requests==2.28.1
# ├── certifi>=2017.4.17
# ├── charset-normalizer~=2.0.0
# └── urllib3<1.27,>=1.21.1

# With deduplication (MERGE strategy)
printer = DependencyTreePrinter(
    max_depth=4,
    deduplicate_shared=True,
    duplicate_handling=DuplicateHandling.MERGE,
    style=TreeStyle(colorize=True, show_versions=True)
)
printer.print_tree("pyputil")

# COLLAPSE strategy (reference counts)
printer = DependencyTreePrinter(
    deduplicate_shared=True,
    duplicate_handling=DuplicateHandling.COLLAPSE
)
printer.print_tree("tensorflow")
# tensorflow==2.13.0
# ├── numpy==1.24.3
# ├── six==1.16.0 [shared x3]
# └── wheel==0.41.0 [shared x2]

# Export to different formats
printer = DependencyTreePrinter()

# JSON output
json_str = printer.export_tree("requests", TreeOutputFormat.JSON, indent=2)

# HTML output (interactive)
printer.export_tree("pandas", TreeOutputFormat.HTML, "pandas_tree.html", theme="dark")

# Graphviz DOT
dot_str = printer.export_tree("flask", TreeOutputFormat.DOT, rankdir="TB")

# Mermaid diagram
mermaid_str = printer.export_tree("django", TreeOutputFormat.MERMAID, direction="TB")

# Markdown documentation
md_str = printer.export_tree("scipy", TreeOutputFormat.MARKDOWN, title="SciPy Dependencies")

# Legacy function (backward compatible)
print_dep_tree(
    "requests",
    max_depth=3,
    show_versions=True,
    show_required=True,
    colorize=True,
    deduplicate_shared=True,
    duplicate_handling="merge"
)

# Export to file directly
export_tree_to_file("numpy", "numpy_tree.html", format='html', max_depth=3)
export_tree_to_file("requests", "requests.json", format='json')
export_tree_to_file("pandas", "pandas.dot", format='dot')

# Get printer statistics
stats = printer.get_stats()
print(f"Trees printed: {stats['trees_printed']}")
print(f"Total nodes: {stats['total_nodes_processed']}")
print(f"Deduplications saved: {stats['deduplications_saved']}")
print(f"Cache hit rate: {stats['cache_hit_rate']}%")

# Clear printer cache
printer.clear_cache()
```

---

4. Legacy Module (tree.py - Original)

What It Does

Provides the original tree building and printing functionality with basic deduplication support. This is the legacy entry point maintained for backward compatibility.

Why Use It

· Quick Analysis: One-line dependency tree printing
· Simple API: Fewer parameters, easier to use
· Backward Compatibility: Existing code continues to work

Usage Examples

```python
from pyputil.tree import build_tree, get_tree, print_tree, get_stats

# Build tree (dictionary format)
tree = build_tree("requests", max_depth=2, include_stats=True)
print(tree['name'])  # 'requests'

# Get tree statistics
stats = get_stats(tree)
print(f"Total nodes: {stats['total_nodes']}")
print(f"Max depth: {stats['max_depth']}")

# Print tree to console
print_tree("pandas", max_depth=2, show_versions=True)

# Print with deduplication (new)
print_tree(
    "pyputil",
    max_depth=3,
    deduplicate_shared=True,
    duplicate_handling="merge",
    colorize=True
)

# Print specific tree (from build_tree)
print_tree(tree, max_depth=3)

# Use pattern filter
import re
print_tree(
    "scikit-learn",
    pattern_filter=re.compile("^numpy|^scipy"),
    max_depth=2
)
```

---

Complete Example

```python
#!/usr/bin/env python3
"""Complete dependency analysis and visualization example."""

from pyputil.tree import DependencyTreeBuilder, DuplicateHandling
from pyputil.tree import analyze_tree_comprehensive
from pyputil.tree import DependencyTreePrinter, TreeStyle, TreeOutputFormat

def analyze_and_visualize(package_name: str, output_dir: str = "."):
    """Complete dependency analysis and visualization pipeline."""
    
    print(f"\n{'='*60}")
    print(f"Analyzing: {package_name}")
    print(f"{'='*60}\n")
    
    # 1. Build dependency tree with deduplication
    builder = DependencyTreeBuilder(
        max_depth=5,
        deduplicate_shared=True,
        duplicate_handling=DuplicateHandling.MERGE,
        parallel_processing=4,
        include_stats=True
    )
    
    tree = builder.build(package_name)
    if not tree:
        print(f"Failed to build tree for {package_name}")
        return
    
    # 2. Analyze the tree
    analysis = analyze_tree_comprehensive(tree)
    
    print("HEALTH REPORT")
    print("-" * 40)
    print(f"Health Score: {analysis['health_score']}/100")
    print(f"Health Grade: {analysis['health_grade']}")
    print(f"Total Packages: {analysis['metrics']['total_packages']}")
    print(f"Unique Packages: {analysis['metrics']['unique_packages']}")
    print(f"Max Depth: {analysis['metrics']['max_depth']}")
    print(f"Conflicts Found: {analysis['conflict_count']}")
    print(f"Circular Dependencies: {analysis['circular_count']}")
    
    if analysis['recommendations']:
        print("\nRECOMMENDATIONS")
        print("-" * 40)
        for rec in analysis['recommendations']:
            print(f"  • {rec}")
    
    # 3. Create visualizations
    printer = DependencyTreePrinter(
        style=TreeStyle(colorize=True, show_versions=True),
        max_depth=3
    )
    
    # Terminal output
    print("\nDEPENDENCY TREE")
    print("-" * 40)
    printer.print_tree(package_name)
    
    # Export formats
    printer.export_tree(
        package_name,
        TreeOutputFormat.HTML,
        f"{output_dir}/{package_name}_tree.html",
        theme="light"
    )
    
    printer.export_tree(
        package_name,
        TreeOutputFormat.JSON,
        f"{output_dir}/{package_name}_tree.json"
    )
    
    printer.export_tree(
        package_name,
        TreeOutputFormat.MERMAID,
        f"{output_dir}/{package_name}_tree.mmd"
    )
    
    # 4. Show builder statistics
    stats = builder.get_stats()
    print(f"\nBUILD STATISTICS")
    print("-" * 40)
    print(f"Nodes Built: {stats.nodes_built}")
    print(f"Unique Packages: {stats.unique_packages}")
    print(f"Cache Hit Rate: {(stats.cache_hits / (stats.cache_hits + stats.cache_misses) * 100):.1f}%")
    print(f"Deduplications Saved: {stats.deduplications_saved}")
    print(f"Build Time: {stats.build_time:.2f}s")
    
    print(f"\n✓ Analysis complete! Output saved to {output_dir}")

# Run analysis
if __name__ == "__main__":
    analyze_and_visualize("requests")
    analyze_and_visualize("pandas")
```

---

Requirements

· Python 3.8+
· No external dependencies for core functionality
· Optional: colorama for Windows color support
· Optional: packaging for enhanced version handling

Key Features Summary

Feature Analyzer Builder Printer
Conflict detection ✓ ✓ ✗
Cycle detection ✓ ✓ ✗
Health scoring ✓ ✗ ✗
Tree construction ✗ ✓ ✓
Parallel processing ✗ ✓ ✓
Caching ✓ ✓ ✓
Deduplication ✗ ✓ ✓
Terminal output ✗ ✗ ✓
HTML export ✗ ✗ ✓
Graphviz DOT ✗ ✗ ✓
Mermaid export ✗ ✗ ✓
JSON export ✓ ✓ ✓
Statistics ✓ ✓ ✓
