# PyPUtil Dependency Management Module

## Overview

PyUtil Dependency Management is a comprehensive, production-grade toolkit for analyzing, parsing, and managing Python package dependencies. It provides advanced features for requirement parsing, dependency tree building, caching, version constraint resolution, and conflict detection.

## Architecture

The module consists of the following core components:

| Component | Purpose |
|-----------|---------|
| `cache.py` | Thread-safe caching for package distribution metadata |
| `parser.py` | PEP 508 requirement string parser with enhanced features |
| `models.py` | Core data models for dependencies, packages, and trees |

## Quick Start

```python
from pyputil.tree.core import get_distribution, parse_requirement, PackageInfo

# Get package distribution
dist = get_distribution("requests")
print(f"Version: {dist.version}")

# Parse requirement
req = parse_requirement("django>=3.2; python_version>'3.6'")
print(f"Package: {req[0]}, Spec: {req[1]}")

# Build dependency tree
pkg = PackageInfo(name="requests", version="2.28.1")
```

---

1. Cache Module (cache.py)

What It Does

Provides a high-performance, thread-safe caching system for Python package distribution metadata. Reduces filesystem I/O and improves analysis performance for large dependency trees.

Why Use It

· Performance: Cache distributions to avoid repeated filesystem lookups
· Thread Safety: Safe for concurrent access with reentrant locks
· Persistence: Save/load cache to disk across sessions
· Statistics: Track hit rates, evictions, and performance metrics

Key Classes

```python
from pyputil.tree.core import PackageCache, CacheError, CacheContext
```

Usage Examples

```python
from pyputil.tree.core import PackageCache, CacheContext

# Get singleton instance
cache = PackageCache.get_instance()

# Cache package distribution
dist = cache.get_distribution("pandas")
if dist:
    print(f"Version: {dist.version}")

# Batch retrieval
packages = ["requests", "numpy", "pandas", "scipy"]
results = cache.get_batch(packages)
for name, dist in results.items():
    print(f"{name}: {dist.version if dist else 'Not found'}")

# Cache statistics
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate']:.2%}")
print(f"Cache size: {stats['current_size']}")
print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")

# Warm cache with common packages
cache.warm_cache(["numpy", "pandas", "matplotlib", "scipy"], parallel=True)

# Cache entry information
info = cache.get_cache_entry_info("requests")
if info:
    print(f"Access count: {info['access_count']}")
    print(f"Age: {info['age_seconds']:.1f}s")
    print(f"Is stale: {info['is_stale']}")

# Remove from cache
cache.remove_from_cache("requests")

# Save/load cache
cache.save_to_file("cache.pkl")
cache.load_from_file("cache.pkl")

# Clear entire cache
cache.clear_cache()

# Temporary configuration
with CacheContext(ttl_seconds=60):
    # Cache entries expire after 60 seconds here
    dist = cache.get_distribution("flask")
    # TTL restored after context exit

# Register callbacks
def on_hit(package_name):
    print(f"Cache hit: {package_name}")

def on_miss(package_name):
    print(f"Cache miss: {package_name}")

cache.register_callback('on_hit', on_hit)
cache.register_callback('on_miss', on_miss)
```

---

2. Parser Module (parser.py)

What It Does

Provides comprehensive parsing of PEP 508 requirement strings with support for all specification features including version specifiers, extras, environment markers, and URL-based requirements.

Why Use It

· PEP 508 Compliant: Full support for Python requirement specification
· Rich Metadata: Extracts version constraints, markers, extras, and more
· URL Support: Handles VCS and direct URL requirements
· Fallback Support: Works without external packaging library

Key Classes

```python
from pyputil.tree.core import PEP508Parser, ParsedRequirement, RequirementType, VersionSpecifier
```

Usage Examples

```python
from pyputil.tree.core import PEP508Parser, parse_requirement, parse_requirement_enhanced

# Create parser
parser = PEP508Parser(normalize_names=True, cache_results=True)

# Parse standard requirement
req = parser.parse("requests>=2.25.0")
print(f"Package: {req.package_name}")
print(f"Version spec: {req.version_spec}")
print(f"Is valid: {req.is_valid()}")

# Parse with extras
req = parser.parse("pandas[parquet,excel]>=1.3.0")
print(f"Extras: {req.extras}")  # ['parquet', 'excel']

# Parse with environment marker
req = parser.parse("colorama>=0.4.0; sys_platform == 'win32'")
print(f"Marker: {req.marker}")
print(f"Marker type: {req.environment_marker.marker_type}")
print(f"Marker variables: {req.environment_marker.variables}")

# Parse URL requirement
req = parser.parse("my-package @ git+https://github.com/user/repo.git")
print(f"Type: {req.requirement_type.value}")  # 'url'
print(f"VCS: {req.metadata.get('vcs_type')}")  # 'git'
print(f"Repository: {req.metadata.get('repository')}")

# Parse local path requirement
req = parser.parse("my-package @ ./local/path")
print(f"Type: {req.requirement_type.value}")  # 'local'
print(f"Path: {req.local_path}")

# Convenience functions (legacy)
name, spec, extras, marker = parse_requirement("django>=3.2")
print(f"Name: {name}, Spec: {spec}, Extras: {extras}")

# Enhanced with metadata
name, spec, extras, marker, meta = parse_requirement_enhanced("requests[security]>=2.25.0")
print(f"Has extras: {meta['has_extras']}")
print(f"Requirement type: {meta['requirement_type']}")
print(f"Version specifiers: {meta['version_specifiers']}")

# Parse version specifiers
specs = parse_version_specifiers(">=1.0.0,<2.0.0")
for spec in specs:
    print(f"{spec['operator']}{spec['version']}")

# Normalize package names
normalized = normalize_package_name("Django_Package")
print(normalized)  # 'django-package'

# Validate package names
is_valid = validate_package_name("valid-package")
print(is_valid)  # True

# Extract from requirements file
requirements = extract_requirements_from_file("requirements.txt")
for req in requirements:
    print(f"{req.package_name} {req.version_spec}")

# Parse with parser instance
parser = PEP508Parser()
parsed = parser.parse("numpy>=1.21.0,<2.0.0")
print(f"Version specifiers: {len(parsed.version_specifiers)}")
for spec in parsed.version_specifiers:
    print(f"  {spec.operator.value}{spec.version}")
```

---

3. Models Module (models.py)

What It Does

Provides comprehensive data structures for representing package dependency trees with support for version constraints, dependency types, conflict resolution, and tree manipulation.

Why Use It

· Rich Package Info: Complete package metadata and dependency tracking
· Conflict Detection: Automatic detection and resolution of version conflicts
· Cycle Detection: Identify circular dependencies
· Tree Operations: Prune, clone, merge, and analyze dependency trees

Key Classes

```python
from pyputil.tree.core import (
    PackageInfo, DependencyType, PackageStatus, 
    VersionConstraint, RequirementInfo, DependencyTreeStats
)
```

Usage Examples

```python
from pyputil.tree.core import PackageInfo, DependencyType, PackageStatus, OutputFormat

# Create package info
pkg = PackageInfo(
    name="requests",
    version="2.28.1",
    requirement=">=2.0.0",
    status=PackageStatus.INSTALLED,
    dep_type=DependencyType.REQUIRED
)

# Check status
if pkg.is_installed():
    print(f"{pkg.name} is installed")

if pkg.matches_requirement():
    print("Version matches requirement")

# Build dependency tree
requests = PackageInfo(
    name="requests",
    version="2.28.1",
    dependencies=[
        PackageInfo(
            name="urllib3",
            version="1.26.12",
            requirement=">=1.21.1,<3",
            dep_type=DependencyType.REQUIRED
        ),
        PackageInfo(
            name="certifi",
            version="2022.12.07",
            requirement=">=2017.4.17",
            dep_type=DependencyType.REQUIRED
        )
    ]
)

# Find dependency
urllib3 = requests.find_dependency("urllib3")
if urllib3:
    print(f"Found: {urllib3.name} {urllib3.version}")

# Get all transitive dependencies
all_deps = requests.get_all_dependencies()
print(f"Total dependencies: {len(all_deps)}")

# Build dependency graph
graph = requests.get_dependency_graph()
for node, deps in graph.items():
    print(f"{node} -> {deps}")

# Detect cycles
cycles = requests.detect_cycles()
if cycles:
    for cycle in cycles:
        print(f"Cycle: {' -> '.join(cycle)}")

# Get tree metrics
size = requests.get_size()
depth = requests.get_depth()
print(f"Tree size: {size} nodes, depth: {depth}")

# Prune tree (remove optional dependencies, limit depth)
pruned = requests.prune(max_depth=2, include_optional=False)

# Clone tree
clone = requests.clone()

# Merge two trees (for conflict resolution)
other = PackageInfo(name="requests", version="2.27.1")
merged = requests.merge(other)

# Resolve conflicts
conflicts = requests.resolve_conflicts()
for pkg_name, info in conflicts.items():
    print(f"Conflict in {pkg_name}: {info['versions']}")
    print(f"Suggestion: use {info['suggestion']}")

# Generate hash
tree_hash = requests.get_hash()
print(f"Tree hash: {tree_hash}")

# Convert to dictionary
as_dict = requests.to_dict(include_metadata=True)
print(as_dict['name'], as_dict['version'])

# Convert to JSON
json_str = requests.to_json(indent=2)
print(json_str)

# RequirementInfo for parsed requirements
req = RequirementInfo.from_string("django>=3.2; python_version>'3.6'")
print(f"Name: {req.name}")
print(f"Has extras: {req.has_extras}")
print(f"Has marker: {req.has_marker}")
print(f"Has version spec: {req.has_version_spec}")

# Check environment marker
matches = req.matches_environment()
if matches is not None:
    print(f"Marker matches: {matches}")

# Create stats from tree
stats = DependencyTreeStats().calculate_from_tree(requests)
print(f"Total nodes: {stats.total_nodes}")
print(f"Unique packages: {stats.unique_packages}")
print(f"Max depth: {stats.max_depth}")
print(f"Circular deps: {stats.circular_dependencies}")
print(f"Version conflicts: {stats.version_conflicts}")
```

---

Enumerations Reference

DependencyType

Value Description Priority
REQUIRED Essential for functionality 5
PEER Should be installed alongside 4
RECOMMENDED Recommended but not required 3
OPTIONAL Enables additional features 2
DEVELOPMENT Only for development 1
CONFLICT Conflicts with this package 0

PackageStatus

Value Description Color
INSTALLED Package is installed Green
NOT_INSTALLED Package not installed Gray
MISMATCH Version mismatch Orange
OUTDATED Outdated version Blue
CYCLE_DETECTED Circular dependency Yellow
ERROR Error occurred Red

OutputFormat

Value Description Use Case
TEXT ASCII tree Terminal display
JSON Structured data API integration
YAML Human-readable Configuration
HTML Interactive Web visualization
GRAPHVIZ Graph format Diagram tools
MERMAID Web diagrams Markdown docs
MARKDOWN Documentation README files

---

Complete Example

```python
#!/usr/bin/env python3
"""Complete dependency analysis example."""

from pyputil.tree.core import (
    PackageCache, PEP508Parser, PackageInfo, 
    DependencyType, PackageStatus, OutputFormat
)

def analyze_project_dependencies(requirements_file: str):
    """Analyze dependencies from requirements file."""
    
    # Initialize components
    cache = PackageCache.get_instance()
    parser = PEP508Parser()
    
    # Parse requirements
    requirements = parser.extract_requirements(requirements_file)
    print(f"Found {len(requirements)} requirements")
    
    # Build dependency tree
    root = PackageInfo(
        name="my_project",
        version="1.0.0",
        status=PackageStatus.INSTALLED
    )
    
    for req in requirements:
        # Get cached distribution
        dist = cache.get_distribution(req.package_name)
        
        if dist:
            status = PackageStatus.INSTALLED
            version = dist.version
        else:
            status = PackageStatus.NOT_INSTALLED
            version = "unknown"
        
        # Create package node
        pkg = PackageInfo(
            name=req.package_name,
            version=version,
            requirement=req.version_spec,
            status=status,
            dep_type=DependencyType.REQUIRED,
            extras=req.extras
        )
        
        root.dependencies.append(pkg)
        
        # Print requirement info
        print(f"\n{req.package_name}:")
        print(f"  Required: {req.version_spec}")
        print(f"  Installed: {version}")
        print(f"  Status: {status.value}")
        if req.extras:
            print(f"  Extras: {', '.join(req.extras)}")
    
    # Analyze tree
    stats = DependencyTreeStats().calculate_from_tree(root)
    print(f"\n=== Analysis Results ===")
    print(f"Total packages: {stats.total_nodes}")
    print(f"Unique packages: {stats.unique_packages}")
    print(f"Max depth: {stats.max_depth}")
    
    # Detect conflicts
    conflicts = root.resolve_conflicts()
    if conflicts:
        print(f"\nVersion Conflicts:")
        for pkg_name, info in conflicts.items():
            print(f"  {pkg_name}: versions {info['versions']}")
            print(f"    Suggestion: use {info['suggestion']}")
    
    # Detect cycles
    cycles = root.detect_cycles()
    if cycles:
        print(f"\nCircular Dependencies:")
        for cycle in cycles:
            print(f"  {' -> '.join(cycle)}")
    
    # Cache statistics
    cache_stats = cache.get_stats()
    print(f"\nCache Performance:")
    print(f"  Hit rate: {cache_stats['hit_rate']:.2%}")
    print(f"  Cache size: {cache_stats['current_size']}")
    
    return root

# Run analysis
if __name__ == "__main__":
    tree = analyze_project_dependencies("requirements.txt")
```

---

Requirements

· Python 3.7+
· Standard library only for core functionality
· Optional: packaging library for enhanced version handling

Key Features Summary

Feature Cache Parser Models
Distribution caching ✓ ✗ ✗
Thread safety ✓ ✗ ✓
PEP 508 parsing ✗ ✓ ✗
Version constraints ✗ ✓ ✓
Dependency trees ✗ ✗ ✓
Conflict detection ✗ ✗ ✓
Cycle detection ✗ ✗ ✓
Cache persistence ✓ ✗ ✗
Environment markers ✗ ✓ ✓
URL requirements ✗ ✓ ✗
Statistics tracking ✓ ✓ ✓