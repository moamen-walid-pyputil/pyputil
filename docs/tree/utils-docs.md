# PyPUtil Dependency Tree Utilities

## Overview

PyUtil Dependency Tree Utilities provide comprehensive tools for working with Python dependency trees, including filesystem operations for package discovery, intelligent requirement filtering, and advanced dependency evaluation. These utilities are designed for analyzing project dependencies, filtering requirements for different environments, and building dependency trees from various sources.

## Why Use This Module?

| Use Case | Solution |
|----------|----------|
| **Discover project dependencies** | Scan directories for package files (setup.py, requirements.txt) |
| **Filter requirements by environment** | Include/exclude dev/test/optional dependencies |
| **Platform-specific dependencies** | Filter by OS (Linux, Windows, macOS) |
| **Python version constraints** | Filter by Python version requirements |
| **Visualize directory structure** | Generate ASCII/Unicode directory trees |
| **Analyze requirement markers** | Evaluate PEP 508 environment markers |

---

## 1. Filesystem Utilities (`filesystem.py`)

### What It Does

Provides robust filesystem operations for directory traversal, package discovery, requirement file parsing, and directory tree visualization with comprehensive error handling.

### Key Functions

```python
from pyputil.tree.utils import (
    generate_directory_tree,
    find_package_files,
    read_requirements_file,
    write_requirements_file,
    get_package_directories,
    get_absolute_path,
    safe_join
)
```

Usage Examples

```python
# Generate beautiful directory tree
tree = generate_directory_tree(
    "./myproject",
    max_depth=3,
    show_files=True,
    include_size=True,
    include_permissions=True
)
print(tree)

# Output:
# myproject/
# ├── src/ (4096 bytes) [drwxr-xr-x]
# │   ├── __init__.py (0 bytes) [-rw-r--r--]
# │   └── main.py (1024 bytes) [-rw-r--r--]
# └── tests/ (4096 bytes) [drwxr-xr-x]
#     └── test_main.py (512 bytes) [-rw-r--r--]

# Find all package files
files = find_package_files("./myproject")
for f in files:
    print(f"{f['type']}: {f['path']}")
# setup.py: ./myproject/setup.py
# requirements.txt: ./myproject/requirements.txt

# Read requirements.txt with continuation handling
reqs = read_requirements_file(
    "requirements.txt",
    strip_comments=True,
    handle_continuations=True
)
# ['requests>=2.28.0', 'django==4.2.0', 'package>=1.0']

# Write requirements with backup
write_requirements_file(
    "requirements.txt",
    ["requests>=2.28.0", "django==4.2.0"],
    create_backup=True
)

# Find package directories (contain __init__.py)
packages = get_package_directories("./src")
# ['./src/mypackage', './src/mypackage/subpackage']

# Safe path joining (prevents directory traversal)
path = safe_join("/home/user", "documents", "file.txt")
# '/home/user/documents/file.txt'

# Get disk usage
usage = get_disk_usage("/home")
print(f"Free: {usage['free'] / (1024**3):.1f} GB")
```

---

2. Requirement Filters (filters.py)

What It Does

Provides intelligent filtering of Python package requirements with support for environment markers, version constraints, platform filtering, and custom filter rules.

Key Classes

```python
from pyputil.tree.utils import (
    RequirementFilter,
    FilterRule,
    FilterOperator,
    EvaluationContext,
    RequirementCategory,
    create_environment_filter
)
```

FilterRule - Custom Filter Rules

```python
# Create rules for fine-grained filtering
rule = FilterRule(
    field='name',                    # Field to filter on
    operator=FilterOperator.START_WITH,  # Operator
    value='django',                  # Value to compare
    description='Django packages only'
)

# Evaluate against requirement info
requirement = {'name': 'django-rest-framework', 'version': '3.14.0'}
rule.evaluate(requirement)  # True

# Various operators
FilterRule('version', FilterOperator.GREATER_THAN, '2.0')
FilterRule('marker', FilterOperator.CONTAINS, 'extra')
FilterRule('name', FilterOperator.MATCHES, r'^django')
```

RequirementFilter - Main Filtering Engine

```python
# Production filter (excludes dev dependencies)
prod_filter = RequirementFilter(
    skip_development=True,
    skip_optional=True,
    platform_filter='linux',
    python_version_filter='>=3.8'
)

# Test a requirement
should_include = prod_filter.should_include(
    version_spec=">=1.0",
    marker="sys_platform == 'linux'"
)
print(should_include)  # True

# Development filter (includes everything)
dev_filter = RequirementFilter(skip_development=False)

# Platform-specific filter
linux_filter = RequirementFilter(platform_filter='linux')
windows_filter = RequirementFilter(platform_filter='windows')

# Batch filtering
requirements = [
    {'name': 'django', 'version_spec': '>=3.2', 'marker': ''},
    {'name': 'pytest', 'marker': "extra == 'dev'"},
    {'name': 'requests', 'version_spec': '>=2.0', 'marker': ''}
]

filtered = prod_filter.filter_batch(requirements)
# Only django and requests (pytest excluded as dev dependency)

# Get statistics
stats = prod_filter.get_stats()
print(f"Inclusion rate: {stats['inclusion_rate']:.2%}")
print(f"Exclusion reasons: {stats['exclusion_reasons']}")
```

EvaluationContext - Marker Evaluation with Caching

```python
# Create evaluation context
ctx = EvaluationContext()

# Evaluate markers
result = ctx.evaluate_marker("python_version >= '3.8'")
print(result)  # True (if running Python 3.8+)

# Version specification
result = ctx.evaluate_version_spec(">=1.0,<2.0", current_version="1.5.0")
print(result)  # True

# Cache statistics
stats = ctx.get_cache_stats()
print(f"Hit rate: {stats['hit_rate']:.2%}")
```

Pre-configured Environment Filters

```python
# Production environment (excludes dev/test dependencies)
prod_filter = create_environment_filter('production')

# Development environment (includes everything)
dev_filter = create_environment_filter('development')

# Test environment (includes test dependencies)
test_filter = create_environment_filter('test')

# CI environment (strict evaluation)
ci_filter = create_environment_filter('ci')
```

RequirementCategory Enum

```python
from pyputil.tree.utils import RequirementCategory

# Categories include:
# - PRODUCTION: Core runtime dependencies
# - DEVELOPMENT: Dev/test dependencies
# - OPTIONAL: Optional feature dependencies
# - PLATFORM_SPECIFIC: OS-specific dependencies
# - SECURITY: Security-related dependencies
# - DOCUMENTATION: Documentation building dependencies

category = RequirementCategory.PRODUCTION
print(category.is_core())  # True
print(category.priority())  # 10 (highest priority)

# Filter by category
category_filter = RequirementFilter(
    include_categories=[RequirementCategory.PRODUCTION, RequirementCategory.SECURITY],
    exclude_categories=[RequirementCategory.DEVELOPMENT]
)
```

Complete Example

```python
#!/usr/bin/env python3
"""Complete dependency filtering example."""

from pyputil.tree.utils import (
    RequirementFilter,
    FilterRule,
    FilterOperator,
    create_environment_filter,
    read_requirements_file
)

def analyze_requirements(env_type='production'):
    """Analyze requirements file with environment filtering."""
    
    # Read requirements
    requirements = read_requirements_file("requirements.txt")
    print(f"Found {len(requirements)} total requirements")
    
    # Parse requirements into structured dicts
    parsed_reqs = []
    for req in requirements:
        # Simple parsing (expand as needed)
        if ';' in req:
            name_version, marker = req.split(';', 1)
        else:
            name_version, marker = req, ""
        
        if '>=' in name_version or '==' in name_version:
            import re
            match = re.match(r'([a-zA-Z0-9_-]+)([<>=!~].*)', name_version)
            if match:
                name, spec = match.groups()
            else:
                name, spec = name_version, ""
        else:
            name, spec = name_version, ""
        
        parsed_reqs.append({
            'name': name.strip(),
            'version_spec': spec.strip(),
            'marker': marker.strip()
        })
    
    # Create environment filter
    filter_obj = create_environment_filter(env_type)
    
    # Add custom rules
    filter_obj.add_custom_rule(
        FilterRule('name', FilterOperator.MATCHES, '^django', 
                   description='Only Django packages')
    )
    
    # Filter requirements
    filtered = filter_obj.filter_batch(parsed_reqs)
    
    # Print results
    print(f"\n{env_type.upper()} environment:")
    print(f"  Included: {len(filtered)}/{len(parsed_reqs)} requirements")
    
    for req in filtered:
        print(f"  - {req['name']} {req['version_spec']}")
    
    # Show statistics
    stats = filter_obj.get_stats()
    print(f"\nStatistics:")
    print(f"  Inclusion rate: {stats['inclusion_rate']:.2%}")
    
    if stats['exclusion_reasons']:
        print(f"  Exclusion reasons:")
        for reason, count in stats['exclusion_reasons'].items():
            print(f"    - {reason}: {count}")

# Run analysis
analyze_requirements('production')
analyze_requirements('development')
```

---

Key Features Summary

Feature Filesystem Filters
Directory tree generation ✓ ✗
Package discovery ✓ ✗
Requirements.txt parsing ✓ ✗
Environment marker evaluation ✗ ✓
Version constraint filtering ✗ ✓
Platform filtering (Linux/Windows/macOS) ✗ ✓
Python version filtering ✗ ✓
Custom filter rules ✗ ✓
Cache support ✗ ✓
Statistics tracking ✓ ✓

Requirements

· Python 3.7+
· No external dependencies for core functionality
· Optional: packaging library for improved version handling

Error Handling

All functions include comprehensive error handling:

```python
from pyputil.tree.utils import FilesystemError

try:
    generate_directory_tree("/nonexistent/path")
except FilesystemError as e:
    print(f"Error: {e}")
    print(f"Path: {e.path}")
    print(f"Operation: {e.operation}")