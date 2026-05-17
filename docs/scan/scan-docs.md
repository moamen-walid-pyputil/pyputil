# PyUtil Scan - Python Module Discovery and Analysis

## Overview

PyUtil Scan is a comprehensive, production-grade toolkit for discovering, analyzing, and understanding Python modules in any environment. It combines file system scanning with Python's import machinery to provide deep insights into module structure, dependencies, and metadata.

## Why Use PyUtil Scan?

| Challenge | Solution |
|-----------|----------|
| Finding where a module is installed | Multi-provider discovery (filesystem + import system) |
| Understanding module dependencies | Automatic dependency extraction via AST analysis |
| Analyzing large codebases | Parallel scanning with intelligent caching |
| Discovering modules by pattern | Multiple search methods (exact, pattern, prefix, all) |
| Performance concerns | Configurable caching, parallel execution, timeouts |

## Quick Start

```python
from pyputil.scan import Scanner, quick_scan, batch_quick_scan

# One-liner scan
result = quick_scan("json")
print(f"Found {result.total_modules_found} module")

# Create scanner for multiple queries
scanner = Scanner()
result = scanner.scan("pytest")
for module in result.results:
    print(f"{module.name} at {module.path}")
```

Core Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Scanner                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │FileProvider │  │ImportProvider│  │   CustomProvider    │ │
│  │(filesystem) │  │(import system)│  │   (extensible)      │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│         │               │                    │              │
│         └───────────────┼────────────────────┘              │
│                         │                                   │
│                  ┌──────▼──────┐                           │
│                  │   Cache     │                           │
│                  │  Manager    │                           │
│                  └─────────────┘                           │
└─────────────────────────────────────────────────────────────┘
```

Search Methods

Method Description Example Use Case
EXACT Exact module name match "json" When you know the exact name
PATTERN Glob pattern matching "test*" Finding test modules
PREFIX Namespace discovery "numpy." Exploring package structure
ALL Combination of all methods Any query Comprehensive discovery

Module Types Classification

Type Description Detection Method
MODULE Single .py file File extension
PACKAGE Directory with __init__.py File structure
NAMESPACE_PACKAGE PEP 420 namespace package No __init__.py in package dir
BUILTIN Built into Python importlib spec origin
C_EXTENSION Compiled extension (.so, .pyd) File extension
FROZEN Frozen module Loader attribute

Configuration

```python
from pyputil.scan import ScanConfig, SearchMethod

# Basic configuration
config = ScanConfig(
    search_method=SearchMethod.ALL,    # Search strategy
    max_depth=5,                       # Package recursion limit
    timeout=30.0,                      # Timeout in seconds
    parallel_scan=True,                # Parallel execution
    workers=4,                         # Thread count
)

# Advanced configuration
config = ScanConfig(
    # Include/exclude module types
    include_builtin=True,
    include_frozen=True,
    include_c_extensions=True,
    
    # Analysis options
    analyze_dependencies=True,         # Extract imports
    
    # Path controls
    exclude_patterns=["test_*", "*_test.py"],
    exclude_paths=[Path("/tmp")],
    follow_symlinks=False,
    
    # Performance
    enable_cache=True,
    max_file_size=10 * 1024 * 1024,   # Skip files >10MB
)

result = scanner.scan("my_module", config)
```

Usage Examples

Basic Module Discovery

```python
from pyputil.scan import Scanner, quick_scan

# Simple scan
scanner = Scanner()
result = scanner.scan("json")

print(f"Module: {result.results[0].name}")
print(f"Path: {result.results[0].path}")
print(f"Type: {result.results[0].module_type.value}")
print(f"Size: {result.results[0].file_size} bytes")

# One-liner alternative
result = quick_scan("requests")
```

Pattern-Based Discovery

```python
from pyputil.scan import Scanner, SearchMethod

scanner = Scanner()
config = ScanConfig(search_method=SearchMethod.PATTERN)

# Find all test modules
results = scanner.scan("test_*.py", config)
for module in results.results:
    print(f"Test module: {module.name}")

# Find all numpy submodules
config = ScanConfig(search_method=SearchMethod.PREFIX)
results = scanner.scan("numpy.", config)
print(f"Found {len(results.results)} numpy submodules")
```

Dependency Analysis

```python
from pyputil.scan import Scanner, ScanConfig

scanner = Scanner()
config = ScanConfig(analyze_dependencies=True)

result = scanner.scan("requests", config)

for module in result.results:
    print(f"\nModule: {module.name}")
    print(f"Dependencies: {module.dependencies}")
    print(f"Has docstring: {module.has_docstring}")
    print(f"Lines of code: {module.line_count}")
```

Batch Scanning

```python
from pyputil.scan import batch_quick_scan, Scanner

# Simple batch scan
results = batch_quick_scan(["os", "sys", "json", "re"])
for module, result in results.items():
    print(f"{module}: {result.total_modules_found} module(s)")

# Parallel batch scan with configuration
scanner = Scanner()
config = ScanConfig(
    analyze_dependencies=True,
    parallel_scan=True,
    workers=4
)
results = scanner.batch_scan(
    ["numpy", "pandas", "scipy", "matplotlib"],
    config=config,
    parallel=True
)

for module, result in results.items():
    if result.results:
        m = result.results[0]
        print(f"{module}: {len(m.dependencies)} dependencies")
```

Custom Search Paths

```python
from pyputil.scan import Scanner
from pathlib import Path

# Add custom search paths
scanner = Scanner(paths=[
    "/my/project/src",
    "/custom/packages",
    Path.home() / "dev/libs"
])

# Scan for local module
result = scanner.scan("my_local_module")
if result.results:
    print(f"Found at: {result.results[0].path}")
```

Cache Management

```python
from pyputil.scan import Scanner

scanner = Scanner()

# First scan (populates cache)
result1 = scanner.scan("numpy")

# Second scan (from cache)
result2 = scanner.scan("numpy")
print(f"From cache: {result2.cache_used}")  # True

# Cache statistics
info = scanner.get_cache_info()
print(f"Cache size: {info['size']}")
print(f"Hit ratio: {info['hit_ratio']:.2%}")

# Clear cache
scanner.clear_cache()
```

Error Handling

```python
from pyputil.scan import (
    Scanner, SearchTimeoutError, ModuleNotFoundError,
    InvalidPathError, AnalysisError
)

scanner = Scanner()

try:
    # Timeout protection
    config = ScanConfig(timeout=5.0)
    result = scanner.scan("very_large_package", config)
    
except SearchTimeoutError as e:
    print(f"Search took too long: {e}")
    
except ModuleNotFoundError as e:
    print(f"Module not found: {e}")
    
except InvalidPathError as e:
    print(f"Invalid search path: {e}")
    
except AnalysisError as e:
    print(f"Analysis failed: {e.details}")
```

Exploring Package Structure

```python
from pyputil.scan import Scanner, ScanConfig, SearchMethod

scanner = Scanner()

# Find all submodules of a package
config = ScanConfig(
    search_method=SearchMethod.PREFIX,
    max_depth=3,
    analyze_dependencies=False
)

result = scanner.scan("django.", config)

print("Django Package Structure:")
for module in result.results:
    indent = "  " * (module.depth - 1)
    icon = "📁" if module.is_package else "📄"
    print(f"{indent}{icon} {module.name}")
```

Performance Optimization

```python
from pyputil.scan import Scanner, ScanConfig

# High-performance configuration
config = ScanConfig(
    parallel_scan=True,      # Enable parallel processing
    workers=8,               # Use 8 threads
    enable_cache=True,       # Cache results
    max_depth=2,             # Limit recursion depth
    max_file_size=5 * 1024 * 1024,  # Skip large files
    exclude_patterns=["__pycache__", "*.pyc"]
)

scanner = Scanner()
result = scanner.scan("large_package", config)

# Performance statistics
stats = scanner.get_stats()
print(f"Total scans: {stats['total_scans']}")
print(f"Total time: {stats['total_scan_time']:.2f}s")
print(f"Cache hit ratio: {stats['cache_stats']['hit_ratio']:.2%}")
```

Data Models

ModuleMeta - Comprehensive Module Information

Attribute Type Description
name str Full qualified module name
path str Absolute file path
is_package bool Whether it's a package
module_type ModuleType Classification
file_size int Size in bytes
dependencies List[str] Imported modules
has_docstring bool Contains documentation
line_count int Lines of code
hash str SHA-256 content hash

ScanResult - Scan Operation Results

Attribute Type Description
query str Original search term
results List[ModuleMeta] Discovered modules
total_modules_found int Count of modules
scan_duration float Execution time
cache_used bool Whether from cache
status ScanStatus Operation status
errors List[str] Error messages

Statistics and Monitoring

```python
from pyputil.scan import Scanner

scanner = Scanner()

# Perform some scans
scanner.scan("json")
scanner.scan("os")
scanner.scan("re")

# Get comprehensive statistics
stats = scanner.get_stats()

print(f"""
Scanner Statistics:
==================
Total scans: {stats['total_scans']}
Total modules found: {stats['total_modules_found']}
Total scan time: {stats['total_scan_time']:.2f}s

Cache Statistics:
================
Size: {stats['cache_stats']['size']}
Hits: {stats['cache_stats']['hits']}
Misses: {stats['cache_stats']['misses']}
Hit ratio: {stats['cache_stats']['hit_ratio']:.2%}

Active Providers:
================
{chr(10).join(f'  - {p}' for p in stats['active_providers'])}

Search Paths:
============
{chr(10).join(f'  - {p}' for p in stats['search_paths'])}
""")
```

Integration Examples

IDE Plugin Integration

```python
from pyputil.scan import Scanner, ScanConfig

class IDEModuleProvider:
    def __init__(self):
        self.scanner = Scanner()
        self.cache = {}
    
    def get_module_info(self, module_name: str) -> dict:
        result = self.scanner.scan(module_name)
        if not result.results:
            return {"found": False}
        
        m = result.results[0]
        return {
            "found": True,
            "path": m.path,
            "type": m.module_type.value,
            "size": m.file_size,
            "dependencies": m.dependencies,
            "has_docstring": m.has_docstring
        }
    
    def suggest_imports(self, code: str) -> list:
        # Simple heuristic - look for undefined names
        import re
        patterns = re.findall(r'\b([a-z][a-z0-9_]*)\b', code)
        suggestions = []
        for pattern in set(patterns):
            if len(pattern) > 2:
                result = self.scanner.scan(pattern)
                if result.results:
                    suggestions.append(pattern)
        return suggestions

# Usage
provider = IDEModuleProvider()
info = provider.get_module_info("requests")
print(f"Module path: {info['path']}")
```

Build System Integration

```python
from pyputil.scan import Scanner, ScanConfig
from pathlib import Path

class BuildDependencyAnalyzer:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.scanner = Scanner(paths=[str(project_root)])
    
    def analyze_project_dependencies(self) -> dict:
        """Analyze all modules in project and their dependencies."""
        config = ScanConfig(
            analyze_dependencies=True,
            search_method="pattern",
            max_depth=10
        )
        
        result = self.scanner.scan("*.py", config)
        
        dependency_graph = {}
        for module in result.results:
            dependency_graph[module.name] = {
                "path": str(module.path),
                "dependencies": module.dependencies,
                "is_package": module.is_package,
                "line_count": module.line_count
            }
        
        return dependency_graph
    
    def find_missing_imports(self) -> list:
        """Find imports that can't be resolved."""
        config = ScanConfig(analyze_dependencies=True)
        result = self.scanner.scan("*.py", config)
        
        missing = []
        for module in result.results:
            for dep in module.dependencies:
                check = self.scanner.scan(dep)
                if not check.results:
                    missing.append({
                        "module": module.name,
                        "missing_import": dep
                    })
        return missing

# Usage
analyzer = BuildDependencyAnalyzer("/my/project")
deps = analyzer.analyze_project_dependencies()
missing = analyzer.find_missing_imports()
```

Requirements

· Python 3.7+ (3.8+ recommended for full features)
· No external dependencies (pure Python standard library)

Key Features Summary

Feature Description
Multi-provider discovery File system + import system
Pattern matching Glob, prefix, exact, all methods
Dependency analysis Automatic import extraction
Caching LRU cache with TTL
Parallel scanning Multi-threaded execution
Timeout protection Configurable time limits
Rich metadata Size, hash, docstrings, line counts
Package detection Regular + namespace packages
Cross-platform Windows, Linux, macOS
Extensible Custom provider support