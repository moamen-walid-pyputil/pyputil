PyPutil Path Module Documentation

Overview

PyPutil Path is a comprehensive module for working with Python modules and packages at the filesystem level. It provides a pathlib.Path-like interface for modules, enabling inspection, manipulation, integrity verification, security scanning, dependency analysis, file watching, comparison, and filesystem operations.

---

1. Plib Module (plib_inspecter.py)

What It Does

Plib (Python Module Library) is a comprehensive toolkit for inspecting, analyzing, and manipulating Python modules and packages. It provides a unified interface to access module metadata, verify integrity, scan for security vulnerabilities, analyze dependencies, and perform safe file operations.

Why Use It

· Module Inspection: Get detailed information about any installed module (size, file count, type)
· Security Auditing: Scan modules for vulnerabilities like eval(), exec(), hardcoded credentials
· Integrity Verification: Create snapshots and detect unauthorized changes
· Dependency Analysis: Understand what imports a module uses
· Safe Operations: Copy, move, delete modules with path traversal protection### Key Classes

```python
from pyputil.path import Plib, ModuleInformation, VulnerabilityInformation, DependencyInformation
```

Usage Examples

```python
from pyputil.path import Plib

# Initialize module
package = Plib('requests')
print(package.exists)  # True
print(package.path)    # /usr/lib/python3/site-packages/requests

# Get comprehensive information
info = package.information()
print(f"Name: {info.module_name}")
print(f"Is package: {info.is_package}")
print(f"Size: {info.size_mb:.2f} MB")
print(f"Files: {info.file_count}")

# List all Python files
files = package.list_files(pattern="*.py", recursive=True)
for f in files[:5]:
    print(f"{f.relative_path}: {f.line_count} lines")

# Calculate size breakdown
size_info = package.calculate_size()
print(f"Total: {size_info.total_megabytes:.2f} MB")
print(f"By extension: {size_info.by_extension}")

# Create integrity snapshot
snapshot = package.create_snapshot(algorithm="sha256")
for path, entry in list(snapshot.items())[:3]:
    print(f"{path}: {entry.hash_digest[:16]}...")

# Compare with previous snapshot
diff = package.diff_snapshot(old_snapshot)
if diff.has_changes:
    print(diff.generate_report())

# Security scan
vulns = package.scan_vulnerabilities()
if not vulns.is_clean:
    print(vulns.generate_report())
    for issue in vulns.critical_issues:
        print(f"CRITICAL: {issue.file_path}:{issue.line_number}")

# Dependency analysis
deps = package.get_deps()
print(f"Third-party: {deps.third_party}")
print(f"External: {deps.external_dependencies}")

# Search code
matches = package.search_code('def get', maximum_results=10)
for match in matches:
    print(f"{match.file_path}:{match.line_number}")

# File operations
package.add_file('custom.py', '# New file content')
package.add_directory('utils')
package.remove_path('deprecated.py', safe_delete=True)
```

---

2. Watcher Module (watcher.py)

What It Does

The PackageWatcher provides file system monitoring for Python packages with hot reload capabilities. It detects file changes (creation, modification, deletion, renaming) and automatically reloads affected modules with intelligent dependency ordering.

Why Use It

· Development Workflow: Automatically reload modules when files change during development
· Live Coding: See changes reflected immediately without manual restarts
· Testing: Monitor test files and re-run tests on changes
· Dependency Tracking: Intelligently reload modules in the correct order based on dependencies

Key Classes

```python
from pyputil.path import PackageWatcher, FileChangeEvent, WatchEventType, ReloadResult
```

Usage Examples

```python
from pyputil.path import PackageWatcher
import time

# Create watcher for your package
watcher = PackageWatcher(
    package_name='myapp',
    poll_interval=0.5,
    use_content_hashing=True,
    batch_changes=True
)

# Register callback
@watcher.on_change
def on_module_change(module_name: str, event: FileChangeEvent):
    print(f"[{event.event_type.value}] {module_name} changed at line? {event.timestamp}")
    if event.event_type == WatchEventType.MODIFIED:
        print(f"  File: {event.file_path}")
        print(f"  Size: {event.file_size} bytes")

# Start watching
watcher.start_watching()

# Your application runs here...
try:
    while True:
        time.sleep(1)
        # Your main application logic
        pass
except KeyboardInterrupt:
    print("Stopping watcher...")
    watcher.stop_watching()

# Get statistics
stats = watcher.get_statistics()
print(f"Scans: {stats.scans_performed}")
print(f"Changes detected: {stats.changes_detected}")
print(f"Reloads succeeded: {stats.reloads_succeeded}")

# Force a scan
changes = watcher.force_scan()
print(f"Found {len(changes)} changes")

# Get reload history
history = watcher.get_reload_history()
for result in history:
    print(f"{result.module_name}: {'✓' if result.success else '✗'} ({result.duration:.3f}s)")

# Get watched files
files = watcher.get_watched_files()
for module, path in files.items():
    print(f"{module} -> {path}")
```

---

3. Include Module (include.py)

What It Does

Provides dynamic Python module import from file paths with integrity checking, caching, and global namespace injection capabilities.

Why Use It

· Dynamic Imports: Import modules from arbitrary file paths
· Development: Auto-reload modules when files change
· Plugin Systems: Load plugins dynamically from external files
· Configuration: Import config files as Python modules

Key Functions

```python
from pyputil.path import include, resolve_import_paths, temporary_syspath
```

Usage Examples

```python
from pyputil.path import include, resolve_import_paths, temporary_syspath

# Basic import from file
my_module = include('path/to/my_module.py')
result = my_module.some_function()

# With custom name and integrity checking
utils = include(
    'utils.py',
    name='my_utils',
    check_integrity=True,  # Auto-reload on changes
    reload=True            # Force reload
)

# Inject into global namespace (use cautiously)
include('config.py', inject_globals=True, target_globals=globals())
print(DATABASE_URL)  # From config.py

# Safe import without crashing
module = include('optional.py', raise_on_error=False)
if module:
    module.optional_feature()

# Resolve import paths
paths = resolve_import_paths(2)  # Two levels up
paths = resolve_import_paths("..", base="/home/user/project/src")

# Temporary sys.path modification
with temporary_syspath(['/custom/modules']):
    import custom_module  # Imports from /custom/modules

# Clear cache
clear_cache()  # Clear all
clear_cache('my_module')  # Clear specific

# Get cached modules
cached = get_cached_modules()
for name, info in cached.items():
    print(f"{name}: {info['path']}")
```

---

4. Compare Module (compare.py)

What It Does

Provides comprehensive comparison between Python module directories and other filesystem locations or archives (ZIP, TAR). Supports multiple comparison methods including hash-based, size-based, content-based, and modification time-based comparisons.

Why Use It

· Backup Verification: Compare installed packages against backups
· Deployment Validation: Ensure deployed code matches source
· Integrity Checking: Detect unauthorized modifications
· Archive Comparison: Compare module contents with archived versions

Key Classes

```python
from pyputil.path import ModuleComparator, ComparisonMethod, ComparisonResult
```

Usage Examples

```python
from pyputil.path import ModuleComparator, ComparisonMethod, compare_modules, quick_compare

# Basic comparison
comparator = ModuleComparator("json", "/backup/json_backup")
result = comparator.result
print(f"Identical: {result.is_identical()}")
print(f"Similarity: {result.get_similarity_score():.2%}")

# With specific comparison method
comparator = ModuleComparator(
    "requests",
    "backup.zip",
    comparison_method=ComparisonMethod.HASH,
    parallel_processing=True
)
print(f"Different files: {len(comparator.result.diff_files)}")

# Export report
comparator.export_report("comparison_report.json")

# Quick comparison
identical = quick_compare("numpy", "/backup/numpy", method=ComparisonMethod.SIZE)

# Convenience function
result = compare_modules("pandas", "/backup/pandas")
print(f"Module only: {len(result.left_only)}")
print(f"Backup only: {len(result.right_only)}")
print(f"Different: {len(result.diff_files)}")

# Context manager
with ModuleComparator("scipy", "scipy_backup.tar.gz") as comp:
    print(f"Similarity: {comp.result.get_similarity_score():.2f}")
    print(comp)

# Filter files during comparison
comparator = ModuleComparator(
    "my_package",
    "/backup",
    include_patterns=["*.py", "*.yaml"],
    exclude_patterns=["test_*", "*_test.py"]
)
```

---

5. Transfer Metadata Module (transfer_metadata.py)

What It Does

Provides robust, production-ready utilities for copying, moving, and synchronizing Python modules and packages in the filesystem. Includes comprehensive error handling, path validation, conflict resolution, and batch operation support.

Why Use It

· Package Deployment: Deploy modules to production servers
· Backup Management: Create backups of installed packages
· Module Migration: Move packages between environments
· Synchronization: Keep two locations in sync (like rsync)

Key Classes & Functions

```python
from pyputil.path import (
    copy, move, sync, verify, info,
    ConflictResolution, OperationResult, BatchOperationResult
)
```

Usage Examples

```python
from pyputil.path import copy, move, sync, verify, info, ConflictResolution

# Copy a single module
result = copy("requests", target="/backup")
print(f"Copied {result.succeeded} modules")

# Copy multiple packages with backup on conflict
result = copy(
    ["numpy", "pandas", "scipy"],
    target="/opt/packages",
    conflict_resolution=ConflictResolution.BACKUP,
    backup_dir="/opt/backups"
)

# Copy with ignore patterns
result = copy(
    "my_package",
    target="/deploy",
    ignore_patterns=["*.pyc", "__pycache__", ".git"],
    preserve_metadata=True
)

# Move module
result = move("old_module", target="/archive")

# Move multiple packages
result = move(
    ["package1", "package2"],
    target="/new_location",
    conflict_resolution=ConflictResolution.OVERWRITE
)

# Synchronize package to deployment
result = sync(
    "my_package",
    "/var/www/my_package",
    direction="source_to_target",
    delete_orphans=True,
    checksum=True
)

# Bidirectional sync
result = sync(
    "dev_package",
    "/backup/dev_package",
    direction="bidirectional",
    ignore_patterns=["*.log", "*.tmp"]
)

# Dry run to preview
result = sync("my_package", "/target", dry_run=True)
print(f"Would sync {result.metadata['sync_stats']['files_to_sync']} files")

# Verify modules exist
verify_result = verify(["numpy", "pandas", "requests"])
print(f"Found: {verify_result.exists}")
print(f"Missing: {verify_result.missing}")

# Verify against reference
verify_result = verify("my_package", reference="/backup/my_package", checksum=True)
if verify_result.mismatched:
    print("Package differs from backup!")

# Get module information
info_dict = info(["numpy", "pandas"])
for name, module_info in info_dict.items():
    print(f"{name}: {module_info.module_type} at {module_info.path}")
    print(f"  Files: {module_info.file_count}, Size: {module_info.size} bytes")