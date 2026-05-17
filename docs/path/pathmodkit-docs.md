```markdown
# PyPutil Path Utilities Documentation

## Overview

PyPutil Path Utilities is a comprehensive collection of tools for managing, inspecting, and manipulating Python modules and packages at the filesystem level. It provides capabilities for removing modules/packages, accessing package resources, calculating sizes, locating metadata, splitting packages, and discovering native extensions.

---

## 1. Remove Module (`remove.py`)

### What It Does

Provides safe and powerful functions for removing Python modules, packages, and pip-installed packages with dependency checking, backup creation, dry-run previews, and protection for critical packages.

### Why Use It

- **Safe Package Removal**: Remove packages with dependency checking to avoid breaking other packages
- **Protected Packages**: Automatically protects pip, setuptools, and wheel from accidental removal
- **Preview Mode**: See what would be removed before actually deleting
- **Backup Support**: Create backups before deletion for safety
- **Force Mode**: Bypass safety checks when absolutely necessary (use with caution!)

### Key Classes & Functions

```python
from pyputil.path import (
    remove, remove_module, remove_package, remove_pip_packages, preview_removal,
    RemovalStatus, RemovalResult
)
```

Usage Examples

```python
from pyputil.path import remove, remove_module, remove_package, remove_pip_packages, preview_removal

# Remove a single module file
remove_module('mymodule.py')
remove_module('mymodule.py', backup=True)  # With backup

# Remove a package directory
remove_package('my_package')
remove_package('my_package', dry_run=True)  # Preview only

# Auto-detect module vs package
remove('requests')
remove('mymodule.py')

# Remove pip packages with dependency checking
count, results = remove_pip_packages(dry_run=True)  # Preview
for r in results:
    print(f"{r.package_name}: {r.status.value} - {r.message}")

# Actual removal with logging
count, results = remove_pip_packages(
    dry_run=False,
    exclude=['requests'],  # Protect specific packages
    log_file='removal.log',
    verbose=True
)

# Preview only (convenience function)
count, results = preview_removal(exclude=['numpy', 'pandas'])

# Check results
for result in results:
    if result.status == RemovalStatus.SUCCESS:
        print(f"✓ {result.package_name}")
    elif result.status == RemovalStatus.SKIPPED_DEPENDENCY:
        print(f"⚠ {result.package_name}: has dependents - {result.dependents}")
```

---

2. Resource Data Module (data.py)

What It Does

Provides secure, cached access to package resources (data files) with support for both modern importlib.resources API and legacy fallbacks. Includes caching, path traversal protection, and streaming for large files.

Why Use It

· Safe Resource Access: Protected against path traversal attacks and symlink attacks
· Caching: Built-in LRU cache with TTL and memory limits
· Streaming: Context manager for large files without loading into memory
· Cross-version: Works with Python 3.7+ using modern or legacy APIs
· Size Limits: Configurable maximum file size to prevent memory issues

Key Functions

```python
from pyputil.path import (
    get_data, get_text_data, get_resource_stream,
    clear_resource_cache, ResourceCache
)
```

Usage Examples

```python
from pyputil.path import get_data, get_text_data, get_resource_stream

# Read binary resource
data = get_data('mypackage', 'data/config.bin')
if data:
    process_data(data)

# Read text resource
config_text = get_text_data('mypackage', 'data/settings.json')
if config_text:
    config = json.loads(config_text)

# Read with custom caching
data = get_data(
    'mypackage',
    'largefile.bin',
    use_cache=True,
    cache_ttl=3600,  # 1 hour
    max_size_mb=500
)

# Stream large file (memory efficient)
with get_resource_stream('mypackage', 'huge_file.dat') as stream:
    for chunk in iter(lambda: stream.read(8192), b''):
        process_chunk(chunk)

# Clear cache
clear_resource_cache()  # Clear all
clear_resource_cache('mypackage')  # Clear package resources
clear_resource_cache('mypackage', 'data/config.json')  # Clear specific

# Custom cache instance
custom_cache = ResourceCache(maxsize=50, max_memory_mb=32, default_ttl=300)
data = get_data('mypackage', 'data.bin', cache_instance=custom_cache)
```

---

3. Size Module (size.py)

What It Does

Provides comprehensive size analysis for Python modules and packages, including total size calculation, file filtering, size-based searching, and size breakdowns by file type.

Why Use It

· Size Analysis: Understand disk usage of installed packages
· Optimization: Find large files that contribute most to package size
· Filtering: Find files above/below specific size thresholds
· Breakdown: See size distribution by file extension
· Human-readable: Automatic formatting (KB, MB, GB)

Key Class

```python
from pyputil.path import size
```

Usage Examples

```python
from pyputil.path import size

# Initialize for a module
s = size("requests")
print(f"Total size: {s.readable}")
print(f"Total bytes: {s.size}")

# Find large files
large_files = s.find(size=1024*1024, cmp=">")  # Files > 1MB
large_files_with_size = s.find(size=1024*1024, cmp=">", withsize=True)

# Find files by size range
files = s.filter_sizes(min_size=10000, max_size=100000)
for name, sz in files.items():
    print(f"{name}: {sz} bytes")

# Human-readable output
files_readable = s.filter_sizes_readable(min_size=10000, max_size=100000)
for name, sz in files_readable.items():
    print(f"{name}: {sz}")

# Size by file type
py_size = s.by_suffix(".py")
so_size = s.by_suffix(".so")
print(f"Python files: {s.by_suffix_readable('.py')}")
print(f"Native extensions: {s.by_suffix_readable('.so')}")

# Get top largest files
breakdown = s.size_breakdown(top_n=10)
for name, bytes_size, pct in breakdown:
    print(f"{name}: {bytes_size} bytes ({pct:.1f}%)")

# Count files
total_files = s.count_files()
python_files = s.count_files(".py")
```

---

4. Metadata File Module (metafile.py)

What It Does

Provides functions to locate package metadata (.dist-info directories) and resolve module/package filesystem paths. Essential for package management and introspection.

Why Use It

· Package Discovery: Find where packages are installed on disk
· Metadata Access: Locate METADATA files for package information
· Multi-location Search: Searches all site-packages directories
· Parallel Search: Fast parallel scanning for better performance
· Version Awareness: Optional version-specific matching

Key Functions

```python
from pyputil.path import (
    getlocation, getmetafilepkg, getmetapath, get_all_meta_paths,
    search_metapath
)
```

Usage Examples

```python
from pyputil.path import (
    getlocation, getmetafilepkg, getmetapath, get_all_meta_paths, search_metapath
)

# Locate module filesystem path
paths = getlocation("requests")
print(paths)  # ['/usr/lib/python3/site-packages/requests/__init__.py']

# Get METADATA file path
metadata = getmetafilepkg("requests")
print(metadata)  # '/usr/lib/.../requests-2.31.0.dist-info/METADATA'

# Get .dist-info directory path
dist_info = getmetapath("requests")
print(dist_info)  # '/usr/lib/.../requests-2.31.0.dist-info'

# Get all installed package metadata directories
all_meta = get_all_meta_paths()
for meta in all_meta[:5]:
    print(meta)

# Search for packages by pattern
results = search_metapath("requests")
results = search_metapath(r"requests-\d+\.\d+", use_regex=True)
results = search_metapath("Pandas", case_sensitive=False)

# Get all meta paths with pattern
filtered = get_all_meta_paths(pattern=".*requests.*")
```

---

5. Splitter Module (splitter.py)

What It Does

Provides advanced package splitting functionality for breaking large packages into smaller chunks based on size, file count, or custom strategies. Includes intelligent analysis, parallel copying, and metadata tracking.

Why Use It

· Package Distribution: Split large packages for easier distribution
· Backup Chunking: Break packages into smaller chunks for backup
· Custom Splitting: Define your own splitting logic
· Smart Decisions: Automatic mode selection based on package analysis
· Parallel Copying: Fast multi-threaded file copying

Key Classes & Functions

```python
from pyputil.path import (
    split_package, merge_splits, split_by_size, split_by_file_count,
    analyze_package, iter_package_files,
    SplitStrategy, SplitFileFilter, SplitMetadata
)
```

Usage Examples

```python
from pyputil.path import (
    split_package, merge_splits, split_by_size, split_by_file_count,
    analyze_package, SplitFileFilter
)

# Analyze package first
analysis = analyze_package("numpy")
print(f"Total files: {analysis['total_files']}")
print(f"Total size: {analysis['total_size_mb']:.2f} MB")
print(f"Recommendations: {analysis['recommendations']}")

# Smart split (auto-decides strategy)
result = split_package("numpy", "./splits", split_mode="smart")

# Split by size (50MB chunks)
result = split_by_size("pandas", "./splits", 50)

# Split by file count (100 files per split)
result = split_by_file_count("requests", "./splits", 100)

# Split with filters (Python files only, exclude tests)
result = split_package(
    "scipy",
    "./splits",
    split_mode="smart",
    file_filter=SplitFileFilter.PYTHON_ONLY,
    exclude_patterns=["*/tests/*", "*/test_*"],
    verify_copies=True,
    progress_callback=lambda done, total: print(f"{done}/{total}")
)

# Target specific number of splits
result = split_package("tensorflow", "./splits", split_mode="smart", target_splits=10)

# Dry run (preview only)
result = split_package("large_package", "./splits", split_mode="size", limit=100*1024*1024, dry_run=True)

# Merge splits back together
success = merge_splits(
    ["./splits/package_0", "./splits/package_1", "./splits/package_2"],
    "./merged_package"
)

# Load split metadata
metadata = SplitMetadata.load("./splits/package_split_metadata.json")
print(f"Created {metadata.splits_created} splits")
```

---

6. Native Extensions Module (gne.py)

What It Does

Discovers native binary extension files (.so, .pyd, .dll, .dylib) in the Python environment with configurable search depth and parallel scanning.

Why Use It

· Extension Discovery: Find all compiled C/C++ extensions in your Python environment
· Platform Support: Works on Windows, macOS, and Linux
· Performance: Configurable scan depth and parallel execution
· Caching: LRU cache for repeated queries
· Custom Paths: Add additional directories to search

Key Classes & Functions

```python
from pyputil.path import get_native_extensions, ExtensionSearchDepth
```

Usage Examples

```python
from pyputil.path import get_native_extensions, ExtensionSearchDepth

# Basic usage - auto depth
extensions = get_native_extensions()
print(f"Found {len(extensions)} native extensions")

# Deep scan with custom paths
extensions = get_native_extensions(
    search_depth=ExtensionSearchDepth.DEEP,
    additional_paths=['/usr/local/lib', './custom_libs'],
    exclude_patterns=['*.py', 'test_*', '*/__pycache__/*'],
    follow_symlinks=True
)

# Shallow scan (faster, less thorough)
extensions = get_native_extensions(search_depth=ExtensionSearchDepth.SHALLOW)

# Moderate depth (root + immediate subdirectories)
extensions = get_native_extensions(search_depth=ExtensionSearchDepth.MODERATE)

# Disable caching for fresh scan
extensions = get_native_extensions(use_cache=False)

# Parallel scanning with custom worker count
extensions = get_native_extensions(max_workers=8)

# Filter results
so_files = [e for e in extensions if e.endswith('.so')]
pyd_files = [e for e in extensions if e.endswith('.pyd')]
```

---

7. Exists Module (exists.py)

What It Does

Provides functions to check if Python modules, submodules, or batch modules exist and are importable.

Why Use It

· Module Validation: Check if required modules are installed
· Batch Checking: Efficiently check multiple modules at once
· Submodule Checking: Verify submodules within packages
· Built-in Support: Optional inclusion of built-in modules

Key Functions

```python
from pyputil.path import exists, batch_exists, subexists
```

Usage Examples

```python
from pyputil.path import exists, batch_exists, subexists

# Check single module
if exists("requests"):
    import requests

# Include built-in modules
exists("sys", include_builtin=True)  # True

# Batch check multiple modules
results = batch_exists(["os", "numpy", "pandas", "nonexistent"])
for name, exists_flag in results:
    print(f"{name}: {'✓' if exists_flag else '✗'}")

# Check submodule
if subexists("os", "path"):
    from os.path import join

if subexists("json", "decoder"):
    from json import decoder
```

---

8. Extend Module (extend.py)

What It Does

Provides functions to extend package paths for namespace packages, similar to pkgutil.extend_path but with additional features and modern Path support.

Why Use It

· Namespace Packages: Combine multiple directories into a single logical package
· PEP 420 Support: Works with implicit namespace packages
· .pkg Files: Process .pkg files for additional path configuration
· Path Validation: Optional validation of paths from .pkg files

Key Functions

```python
from pyputil.path import extend_path, extend_path2, extend_namespace_path
```

Usage Examples

```python
from pyputil.path import extend_path, extend_path2, extend_namespace_path

# Basic usage (compatible with pkgutil.extend_path)
# In your package's __init__.py:
__path__ = extend_path(__path__, __name__)

# Enhanced version with path validation
__path__ = extend_path2(
    __path__,
    __name__,
    validate_pkg_paths=True,
    follow_symlinks=True,
    encoding='utf-8'
)

# Simplified namespace-only (ignore .pkg files)
__path__ = extend_namespace_path(
    __path__,
    __name__,
    include_pkg_files=False,
    include_subdirs=True
)

# Custom .pkg file processing
# If yourpackage.pkg exists in a directory on sys.path, paths listed in it
# are automatically added to __path__
```

---

Complete Example

```python
#!/usr/bin/env python3
"""Complete example using PyPutil Path utilities."""

from pathlib import Path
from pyputil.path import (
    remove, size, getlocation, split_by_size,
    get_native_extensions, ExtensionSearchDepth
)

def analyze_and_cleanup_package(package_name: str):
    """Analyze package size and optionally split or remove."""
    
    # Get package location
    locations = getlocation(package_name)
    print(f"Package '{package_name}' found at:")
    for loc in locations:
        print(f"  - {loc}")
    
    # Analyze size
    s = size(package_name)
    print(f"\nSize Analysis:")
    print(f"  Total size: {s.readable}")
    print(f"  Total files: {s.count_files()}")
    print(f"  Python files: {s.count_files('.py')}")
    
    # Find largest files
    print(f"\nTop 5 largest files:")
    for name, bytes_size, pct in s.size_breakdown(top_n=5):
        print(f"  {name}: {bytes_size} bytes ({pct:.1f}%)")
    
    # Check if splitting is needed
    if s.size > 100 * 1024 * 1024:  # > 100MB
        print(f"\nPackage is large ({s.readable}), consider splitting")
        # Split into 50MB chunks
        result = split_by_size(package_name, f"./splits/{package_name}", 50)
        print(f"  Created {result.splits_created} splits")

# Run analysis
analyze_and_cleanup_package("numpy")

# Find native extensions
extensions = get_native_extensions(search_depth=ExtensionSearchDepth.MODERATE)
print(f"\nFound {len(extensions)} native extensions")
for ext in extensions[:5]:
    print(f"  - {ext}")
```

---

Requirements

· Python 3.8+
· Standard library only for core functionality
· Optional: pkg_resources for version checking (fallback)

Key Features Summary

Module Main Functions Primary Use
remove.py remove, remove_pip_packages Safe package/module deletion
data.py get_data, get_resource_stream Package resource access
size.py size class Package size analysis
metafile.py getmetapath, getlocation Package location discovery
splitter.py split_package, merge_splits Package splitting/merging
gne.py get_native_extensions Native extension discovery
exists.py exists, batch_exists Module existence checking
extend.py extend_path Namespace package support