# PyPUtil Utilities Documentation

## Overview

PyPUtil Utilities is a comprehensive, production-grade collection of Python utilities for advanced package management, import system manipulation, module introspection, and development workflows. This library provides a unified interface to powerful tools for working with Python packages, modules, imports, and environments.

## Module Structure

The utilities module consists of several specialized submodules:

| Module | Purpose |
|--------|---------|
| `importable.py` | Deep package inspection and importable symbol discovery |
| `registers.py` | Dynamic module registration and submodule management |
| `init.py` | Package structure initialization and utilities |
| `copyist.py` | Advanced module cloning with access control and lazy loading |
| `deep_dir.py` | Recursive package inspection with advanced filtering |
| `import_cleaner.py` | Import analysis, cleanup, and unused import detection |
| `all_list.py` | Automatic __all__ generation and validation |

---

## 1. Importable Module (`importable.py`)

### Overview

Discovers and analyzes all importable symbols (classes, functions, variables) within Python packages.

### Enumerations

```python
class SymbolType(Enum):
    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    VARIABLE = "variable"
    CONSTANT = "constant"
    PROPERTY = "property"
    ENUM = "enum"
    DATACLASS = "dataclass"
    TYPE_ALIAS = "type_alias"
    ALL = "all"

class InspectionMode(Enum):
    FAST = "fast"      # AST-only (fast)
    DEEP = "deep"      # Import and introspect
    HYBRID = "hybrid"  # AST + selective imports

class FilterMode(Enum):
    CLASS = "class"
    FUNCTION = "function"
    VARIABLE = "variable"
    PUBLIC = "public"
    ALL = "all"
```

Data Classes

```python
@dataclass
class SymbolInfo:
    """Information about a discovered symbol."""
    full_name: str
    symbol_type: SymbolType
    module_name: str
    file_path: str
    line_number: int
    docstring: Optional[str]
    is_public: bool
    is_exported: bool
    decorators: List[str]

@dataclass
class ModuleInfo:
    """Information about a module."""
    name: str
    file_path: str
    is_package: bool
    is_namespace: bool
    has_all: bool
    all_symbols: List[str]
    imports: List[str]

@dataclass
class InspectionResult:
    """Complete inspection result."""
    package_name: str
    symbols: List[str]
    symbol_infos: Dict[str, SymbolInfo]
    modules: Dict[str, ModuleInfo]
    total_symbols: int
    total_modules: int
    duration: float
    warnings: List[str]
```

Main Functions

importables()

```python
def importables(
    package_name: str,
    *,
    filter_by: Optional[str] = None,
    pattern: Optional[Union[str, Pattern]] = None,
    public_only: bool = True,
    mode: Union[str, InspectionMode] = InspectionMode.FAST,
    max_depth: Optional[int] = None,
    include_stubs: bool = False,
    include_tests: bool = False,
    respect_all: bool = True,
    parallel: bool = False,
    max_workers: int = 4,
    use_cache: bool = True,
    detailed: bool = False,
) -> Union[List[str], InspectionResult]
```

Examples:

```python
from pyputil.util import importables, importable, get_public_api

# Basic symbol discovery
symbols = importables("numpy")
print(f"Found {len(symbols)} symbols")

# Filter by type and pattern
funcs = importables("numpy", filter_by="function", pattern="array")
classes = importables("pandas", filter_by="class", max_depth=2)

# Get detailed results
result = importables("requests", detailed=True)
print(result.summary())
print(f"Modules: {result.total_modules}, Symbols: {result.total_symbols}")

# Filter results
filtered = result.filter(r"session").public_only()
for symbol in filtered.symbols:
    print(f"  {symbol}")

# Public API only
api = get_public_api("my_package")
```

importable()

```python
def importable(target: Union[str, Path]) -> bool
```

Examples:

```python
from pyputil.util import importable

# Check module names
print(importable("requests"))   # True
print(importable("nonexistent")) # False

# Check file paths
print(importable("/path/to/valid.py"))  # True
print(importable("/path/to/invalid.py")) # False
```

Convenience Functions

```python
# Get specific symbol types
classes = get_classes("numpy")
functions = get_functions("pandas")
variables = get_variables("requests")

# Search package
results = search_package("numpy", r"linalg.*")

# Get module imports
imports = get_module_imports("my_package")

# Cache management
clear_cache()
stats = get_cache_stats()
```

---

2. Registers Module (registers.py)

Overview

Advanced module registration system for managing modules in sys.modules with dynamic creation, submodule registration, and namespace package support.

Enumerations

```python
class RegistrationMode(Enum):
    STRICT = "strict"  # Fail if exists
    FORCE = "force"    # Always overwrite
    MERGE = "merge"    # Merge attributes
    SKIP = "skip"      # Skip if exists

class ConflictResolution(Enum):
    ERROR = "error"
    WARN = "warn"
    OVERWRITE = "overwrite"
    MERGE = "merge"
    RENAME = "rename"

class ModuleSource(Enum):
    OBJECT = "object"
    FILE = "file"
    BYTECODE = "bytecode"
    DYNAMIC = "dynamic"
    PROXY = "proxy"
    NAMESPACE = "namespace"
```

Data Classes

```python
@dataclass
class RegistrationInfo:
    """Information about a registered module."""
    name: str
    module: ModuleType
    source: ModuleSource
    timestamp: float
    replaced: Optional[str]
    metadata: Dict[str, Any]

@dataclass
class RegistrationResult:
    """Result of a registration operation."""
    success: bool
    module: Optional[ModuleType]
    name: str
    replaced: bool
    previous: Optional[ModuleType]
    error: Optional[str]
    warnings: List[str]
```

Module Creation Functions

```python
from pyputil.util import create_module, create_module_from_dict

# Create basic module
mod = create_module("my_module", {"VERSION": "1.0.0", "hello": lambda: "world"})
print(mod.VERSION)  # '1.0.0'

# Create from dictionary with nested modules
data = {
    "VERSION": "1.0",
    "config": {"debug": True, "port": 8080}
}
mod = create_module_from_dict("my_module", data, deep=True)
print(mod.config.debug)  # True

# Create namespace package
ns = create_namespace_module("my_namespace", paths=["/path1", "/path2"])
print(ns.__path__)  # ['/path1', '/path2']

# Create lazy proxy
def load_heavy():
    import numpy as np
    return np

proxy = create_proxy_module("numpy", load_heavy)
# numpy only loaded when accessed
arr = proxy.array([1, 2, 3])
```

Registration Functions

```python
from pyputil.util import register, register_as_submodule, register_many

# Basic registration
mod = create_module("my_module", {"value": 42})
result = register(mod)
print(result.success)  # True

# Registration with options
result = register(mod, mode="force", conflict="overwrite", update_globals=True)

# Register as submodule
utils = create_module("utils", {"helper": lambda x: x * 2})
result = register_as_submodule("my_package", utils, "utils", create_parent=True)

# Register multiple modules
mods = {"mod1": mod1, "mod2": mod2}
results = register_many(mods)

# Register namespace package
register_namespace("my_namespace", paths=["/path1", "/path2"])
```

Module Management

```python
from pyputil.util import unregister, reload_module, list_registered_modules

# Unregister modules
unregister("my_module")
unregister("my_package", recursive=True)  # Also remove submodules

# Reload module
reload_module("my_module")

# List registered modules
modules = list_registered_modules(prefix="my_", include_builtins=False)

# Check registration
if is_registered("my_module"):
    mod = get_registered_module("my_module")

# Registration history
history = get_registration_history()
clear_registration_history()
```

Dynamic Importer

```python
from pyputil.util import install_dynamic_importer, register_function, register_value

# Install dynamic importer
def create_my_module():
    return create_module("my_module", {"value": 42})

finder = install_dynamic_importer({"my_module": create_my_module})
# Now 'import my_module' works

# Register single function
def greet(name):
    return f"Hello, {name}!"

register_function("greet.hello", greet)
# Now: from greet import hello

# Register value
register_value("config.DEBUG", True)
# Now: from config import DEBUG

# Register alias
register_alias("numpy", "np")
# Now: import np works as alias
```

---

3. Init Module (init.py)

Overview

Utilities for working with __init__.py files and package directory structures.

Functions

```python
from pyputil.util import init, init_package, create_init

# Read __init__.py content
content = init("requests")
if content:
    print(f"Found __init__.py with {len(content)} chars")

# Clean and prepare package directory
init_package("my_package")  # Removes __pycache__, adds missing __init__.py

# Preview changes
init_package("my_package", dry_run=True)

# Create __init__.py
create_init("./my_package/subdir", content='__version__ = "1.0.0"')

# Check if module has __init__.py
if has_init("my_package"):
    path = get_init_path("my_package")
    print(f"__init__.py at {path}")

# Get package parent directory
parent = get_package_parent("my_package.submodule")
```

---

4. Copyist Module (copyist.py)

Overview

Advanced module cloning with fine-grained access control, lazy loading, immutability, and comprehensive statistics.

Enumerations

```python
class CloneMode(Enum):
    SHALLOW = "shallow"   # Only wrap the module
    DEEP = "deep"         # Recursively clone submodules
    LAZY = "lazy"         # Clone on first access
    REFERENCE = "reference" # Keep references

class AccessPolicy(Enum):
    ALLOW_ALL = "allow_all"
    ALLOW_LIST = "allow_list"
    DENY_LIST = "deny_list"
    PUBLIC_ONLY = "public_only"
    CUSTOM = "custom"

class CloneEvent(Enum):
    ACCESS = "access"
    MODIFY = "modify"
    LAZY_LOAD = "lazy_load"
    ERROR = "error"
```

Data Classes

```python
@dataclass
class CloneStatistics:
    """Statistics for module clone operations."""
    access_count: int
    lazy_load_count: int
    modify_attempts: int
    blocked_accesses: int
    created_at: float
    last_access: Optional[float]

@dataclass
class CloneConfig:
    """Configuration for module cloning."""
    mode: CloneMode
    access_policy: AccessPolicy
    allowed: Optional[FrozenSet[str]]
    denied: FrozenSet[str]
    frozen: bool
    lazy: Dict[str, Callable[[], Any]]
    public_only: bool
    thread_safe: bool
    track_stats: bool
    recursive_depth: int
    preserve_docstring: bool
    preserve_file: bool
    preserve_loader: bool
```

Main Class: ModuleClone

```python
class ModuleClone(ModuleType):
    """
    Controlled, sandboxed view of an existing Python module.
    
    Provides:
    - Access control (allow/deny lists)
    - Lazy loading for expensive attributes
    - Immutability (freeze/unfreeze)
    - Statistics tracking
    - Event callbacks
    """
```

Usage Examples

```python
from pyputil.util import clone_module, clone_module_deep, clone_module_public
import math

# Basic shallow clone
math_clone = clone_module(math)
print(math_clone.sqrt(16))  # 4.0

# Public-only view
public_math = clone_module_public(math)
hasattr(public_math, 'sqrt')  # True
hasattr(public_math, '_generate')  # False

# Restricted view (allow list)
restricted = clone_module(
    math,
    access_policy="allow_list",
    allowed={'sqrt', 'pi', 'e'},
    frozen=True
)

# Deep clone with statistics
deep_clone = clone_module_deep(json, track_stats=True)
print(deep_clone.stats.access_count)

# With lazy loading
lazy_math = clone_module(
    math,
    lazy={'expensive': lambda: expensive_computation()}
)

# Event callbacks
def on_access(clone, event, name, value):
    print(f"Accessed: {name} = {value}")

clone = clone_module(math, callbacks={CloneEvent.ACCESS: [on_access]})

# Clone properties
print(clone.origin)      # Original module
print(clone.config)      # Configuration
print(clone.is_frozen)   # Is frozen?
clone.freeze()           # Make read-only
clone.unfreeze()         # Allow modifications

# Check if object is a clone
if is_module_clone(obj):
    original = get_origin_module(obj)
    unwrapped = unwrap_clone(obj)
```

---

5. Deep Directory Module (deep_dir.py)

Overview

Recursive package inspection with advanced filtering, pattern matching, and result analysis.

Enumerations

```python
class ItemType(Enum):
    MODULE = "modules"
    FUNCTION = "functions"
    CLASS = "classes"
    VARIABLE = "variables"
    PROPERTY = "properties"
    METHOD = "methods"
    ALL = "all"

class InspectionMode(Enum):
    LIVE = "live"    # Import modules
    STATIC = "static" # Static analysis only
    HYBRID = "hybrid" # Mixed

class SortOrder(Enum):
    ALPHABETICAL = "alphabetical"
    DISCOVERY = "discovery"
    HIERARCHICAL = "hierarchical"
    TYPE_FIRST = "type_first"
```

Main Class: DeepDirResult

```python
@dataclass
class DeepDirResult:
    """Container for deep directory inspection results."""
    modules: Set[str]
    functions: Set[str]
    classes: Set[str]
    variables: Set[str]
    properties: Set[str]
    methods: Set[str]
    metadata: Dict[str, ItemMetadata]
    stats: InspectionStatistics
    root_package: str
    
    def filter(self, pattern: Union[str, Pattern]) -> 'DeepDirResult'
    def search(self, term: str, case_sensitive: bool = True) -> 'DeepDirResult'
    def by_type(self, *types: Union[str, ItemType]) -> 'DeepDirResult'
    def public_only(self) -> 'DeepDirResult'
    def with_docstring(self) -> 'DeepDirResult'
    def to_dict(self) -> Dict[str, Any]
    def summary(self) -> str
```

Usage Examples

```python
from pyputil.util import deep_dir, quick_dir, find_in_package, list_submodules

# Basic deep inspection
result = deep_dir("numpy", max_depth=2)
print(result.summary())

# Quick inspection (shallow)
quick = quick_dir("pandas", max_depth=1)

# Filter results
filtered = result.filter(r"linalg|fft")
search_results = result.search("array", case_sensitive=False)

# By type
classes = result.by_type("classes")
functions = result.by_type(ItemType.FUNCTION)
public_items = result.public_only()

# Find pattern in package
found = find_in_package("numpy", r"random.*", item_types={"functions"})

# List submodules
submodules = list_submodules("scipy")

# Detailed metadata
result = deep_dir("requests", collect_metadata=True, max_depth=2)
for name, meta in result.metadata.items():
    if meta.has_docstring:
        print(f"{name}: {meta.docstring[:50]}...")

# Cache management
clear_deep_dir_cache()
stats = get_deep_dir_cache_stats()
```

---

6. Import Cleaner Module (import_cleaner.py)

Overview

Comprehensive AST-based analysis for detecting and removing unused imports with support for type annotations (PEP 484, PEP 563).

Enumerations

```python
class ImportCategory(Enum):
    STANDARD_IMPORT = auto()
    FROM_IMPORT = auto()
    ALIASED_IMPORT = auto()
    WILDCARD_IMPORT = auto()
    RELATIVE_IMPORT = auto()

class UsageContext(Enum):
    DIRECT_REFERENCE = auto()
    ATTRIBUTE_ACCESS = auto()
    FUNCTION_CALL = auto()
    TYPE_ANNOTATION = auto()
    STRING_ANNOTATION = auto()
    COMPREHENSION = auto()
    LAMBDA = auto()

class AnalysisDepth(Enum):
    SHALLOW = auto()   # Top-level only
    STANDARD = auto()  # Functions and classes
    DEEP = auto()      # All nested scopes

class CleanupMode(Enum):
    SAFE = auto()      # Most conservative
    NORMAL = auto()    # Balanced
    AGGRESSIVE = auto() # Most aggressive
```

Data Classes

```python
@dataclass
class ImportRecord:
    """Comprehensive record of a single import statement."""
    name: str
    original_name: str
    alias: Optional[str]
    category: ImportCategory
    line_start: int
    line_end: int
    column_start: int
    module_path: Optional[str]
    relative_level: int
    is_used: bool
    usage_locations: List[UsageLocation]

@dataclass
class AnalysisReport:
    """Complete analysis report for a Python file."""
    file_path: str
    timestamp: datetime
    config: AnalysisConfig
    imports: Dict[str, ImportRecord]
    used_names: Set[str]
    warnings: List[str]
    errors: List[str]

@dataclass
class CleanupResult:
    """Result of an import cleanup operation."""
    file_path: str
    timestamp: datetime
    removed_imports: Set[str]
    modified_lines: Set[int]
    backup_created: bool
    backup_path: Optional[str]
```

Main Functions

```python
from pyputil.util import (
    analyze_file, analyze_source,
    clean_file, clean_directory,
    detect_unused_imports
)

# Analyze file
report = analyze_file("my_module.py")
print(f"Total imports: {report.total_imports}")
print(f"Unused: {report.unused_imports}")
print(f"Conditional imports: {report.conditional_imports}")
print(f"Wildcard imports: {report.wildcard_imports}")
print(f"Type-hint only: {report.type_hint_imports}")

# Analyze source code
source = """
import os
import sys

def main():
    return os.getcwd()
"""
report = analyze_source(source)

# Detect unused imports
unused = detect_unused_imports("my_module.py")
print(f"Can remove: {unused}")

# Clean file (remove unused imports)
result = clean_file("my_module.py", backup=True)
print(f"Removed {len(result.removed_imports)} imports")
print(f"Modified {len(result.modified_lines)} lines")

# Dry run (preview only)
report = clean_file("my_module.py", dry_run=True)

# Clean directory
results = clean_directory("./src/", recursive=True, backup=True)

# Aggressive cleaning
result = clean_file("my_module.py", mode="aggressive")

# Safe cleaning (preserves type hints)
result = clean_file("my_module.py", mode="safe")

# Get detailed import record
for name, record in report.imports.items():
    if not record.is_used:
        print(f"Unused: {name} at line {record.line_start}")
```

Configuration

```python
from pyputil.util import AnalysisConfig, AnalysisDepth

# Create custom configuration
config = AnalysisConfig(
    depth=AnalysisDepth.DEEP,
    analyze_type_hints=True,
    analyze_string_annotations=True,
    preserve_side_effects=True,
    detect_conditional_imports=True
)

# Fast configuration
fast_config = AnalysisConfig.create_fast()

# Safe configuration (for production)
safe_config = AnalysisConfig.create_safe()

# Use with analyzer
report = analyze_file("my_module.py", config=fast_config)
```

---

7. All List Module (all_list.py)

Overview

Automatic __all__ generation, validation, and updating for Python modules and packages.

Enumerations

```python
class ExportType(Enum):
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    CLASS = "class"
    VARIABLE = "variable"
    CONSTANT = "constant"
    IMPORT = "import"
    FROM_IMPORT = "from_import"
    TYPE_ALIAS = "type_alias"

class ValidationLevel(Enum):
    BASIC = "basic"      # Check missing public names
    STRICT = "strict"    # Also check extra names
    COMPLETE = "complete" # All aspects

class UpdateMode(Enum):
    REPLACE = "replace"  # Replace completely
    MERGE = "merge"      # Merge with existing
    APPEND = "append"    # Only add missing
    SMART = "smart"      # Intelligent merge
```

Data Classes

```python
@dataclass
class SymbolInfo:
    name: str
    type: ExportType
    line_number: int
    docstring: Optional[str]
    is_public: bool
    is_exported: bool
    decorators: List[str]

@dataclass
class ModuleAnalysis:
    """Complete analysis of a Python module."""
    path: str
    module_name: str
    symbols: Dict[str, SymbolInfo]
    has_all: bool
    current_all: List[str]
    generated_all: List[str]
    missing: List[str]
    extra: List[str]

@dataclass
class GenerationConfig:
    include_private: bool = False
    include_imports: bool = True
    include_from_imports: bool = True
    include_dunder: bool = False
    include_type_aliases: bool = True
    include_overloads: bool = True
    use_alias: bool = True
    respect_decorators: bool = True
    sort_output: bool = True
    deduplicate: bool = True
```

Usage Examples

```python
from pyputil.util import (
    make_all_list, make_package_all_list,
    validate_all_list, update_package_all,
    fix_all, get_public_api
)

# Single file __all__ generation
__all__ = make_all_list(__file__)
print(__all__)

# Include private and dunder names
__all__ = make_all_list(__file__, include_private=True, include_dunder=True)

# Exclude specific names
__all__ = make_all_list(__file__, exclude={'deprecated_func', 'private_helper'})

# Force include names
__all__ = make_all_list(__file__, include={'__version__', '__author__'})

# Get public API only
public_api = get_public_api(__file__)

# Package-wide generation
all_lists = make_package_all_list("./my_package", recursive=True)
for module, exports in all_lists.items():
    print(f"{module}: {len(exports)} exports")

# Validate existing __all__
result = validate_all_list("my_module.py", level="strict")
if not result['valid']:
    print(f"Missing: {result['missing']}")
    print(f"Extra: {result['extra']}")

# Check missing/extra only
missing = check_missing_all("my_module.py")
extra = check_extra_all("my_module.py")

# Fix __all__ in a single file
if fix_all("my_module.py", backup=True):
    print("Fixed __all__")

# Update entire package
updated = update_package_all(
    "./my_package",
    mode="smart",
    write_back=True,
    backup=True,
    include_imports=False
)

# Analyze module
analysis = analyze_module("my_module.py")
print(f"Has __all__: {analysis.has_all}")
print(f"Generated __all__: {analysis.generated_all}")
```

---

Help System

```python
from pyputil.util import help, help_topic, list_functions, clear_all_caches, get_cache_info

# General help
help()
help_topic("all")  # Same as help()

# Topic-specific help
help_topic("importable")
help_topic("register")
help_topic("clone")
help_topic("deep_dir")
help_topic("import_cleaner")
help_topic("all_list")

# List all available functions
functions = list_functions()
for module, funcs in functions.items():
    print(f"{module}: {len(funcs)} functions")

# Clear all caches
clear_all_caches()

# Get cache statistics
cache_info = get_cache_info()
print(cache_info)
```

---

Complete Example

```python
#!/usr/bin/env python3
"""Complete example using PyPUtil utilities."""

from pathlib import Path
import sys
import tempfile

# Import utilities
from pyputil.util import (
    # Module registration
    create_module, register, unregister,
    # Import inspection
    importables, analyze_file, clean_file,
    # __all__ generation
    make_all_list,
    # Module cloning
    clone_module_public,
)

def create_demo_project():
    """Create a simple demo project."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "my_package"
        project_dir.mkdir()
        
        # Create module file
        module_path = project_dir / "my_module.py"
        module_path.write_text("""
import os
import sys
from pathlib import Path
import warnings

__version__ = "1.0.0"

def public_function(x: int) -> int:
    '''This function is public.'''
    return x * 2

def _private_helper(data):
    '''This function is private.'''
    return len(data)

class PublicClass:
    '''A public class.'''
    pass

class _InternalClass:
    '''An internal class.'''
    pass
""")
        
        # Create __init__.py
        init_path = project_dir / "__init__.py"
        init_path.write_text("from .my_module import *\n")
        
        return project_dir

def main():
    """Run all utility demonstrations."""
    print("=" * 60)
    print("PyPUtil Utilities Demo")
    print("=" * 60)
    
    # Create demo project
    project_dir = create_demo_project()
    module_file = project_dir / "my_module.py"
    
    # 1. Analyze imports
    print("\n1. Import Analysis:")
    print("-" * 30)
    report = analyze_file(module_file)
    print(f"Total imports: {report.total_imports}")
    print(f"Unused imports: {report.unused_imports}")
    
    # 2. Generate __all__
    print("\n2. __all__ Generation:")
    print("-" * 30)
    all_list = make_all_list(module_file, include_imports=False)
    print(f"Generated __all__: {all_list}")
    
    # 3. Clean imports
    print("\n3. Cleaning Imports:")
    print("-" * 30)
    result = clean_file(module_file, dry_run=True)
    print(f"Would remove: {result.unused_imports if hasattr(result, 'unused_imports') else 'analysis only'}")
    
    # 4. Dynamic module registration
    print("\n4. Dynamic Module Registration:")
    print("-" * 30)
    dynamic_mod = create_module("dynamic_utils", {
        "VERSION": "1.0",
        "square": lambda x: x ** 2
    })
    register(dynamic_mod)
    import dynamic_utils
    print(f"dynamic_utils.square(5) = {dynamic_utils.square(5)}")
    
    # 5. Module cloning
    print("\n5. Module Cloning:")
    print("-" * 30)
    import math
    safe_math = clone_module_public(math)
    print(f"Has sqrt: {hasattr(safe_math, 'sqrt')}")
    print(f"Has _pi: {hasattr(safe_math, '_pi')}")
    
    # Cleanup
    unregister("dynamic_utils")
    print("\nDemo completed successfully!")

if __name__ == "__main__":
    main()
```

---

Requirements

· Python 3.8+
· Standard library only for core functionality
· No external dependencies

Key Features Summary

Feature importable registers init copyist deep_dir import_cleaner all_list
Symbol discovery ✓ ✗ ✗ ✗ ✓ ✗ ✓
Module registration ✗ ✓ ✗ ✗ ✗ ✗ ✗
all generation ✗ ✗ ✗ ✗ ✗ ✗ ✓
Import analysis ✗ ✗ ✗ ✗ ✗ ✓ ✗
Module cloning ✗ ✗ ✗ ✓ ✗ ✗ ✗
Package inspection ✓ ✗ ✗ ✗ ✓ ✗ ✓
Cache support ✓ ✗ ✗ ✓ ✓ ✗ ✗
Parallel processing ✓ ✗ ✗ ✗ ✗ ✗ ✗
Namespace packages ✓ ✓ ✗ ✗ ✓ ✗ ✗