# ImportHub Documentation

## Overview

ImportHub is a production-ready Python import system that extends the standard import mechanism with advanced features including automatic package installation, lazy loading, caching, validation, asynchronous imports, and flexible import patterns.

## Architecture

The system consists of the following core modules:

| Module | Purpose |
|--------|---------|
| `types.py` | Core type definitions and base classes (LazyModule, LazyAttributeProxy, ImportConfig) |
| `parser.py` | Target string parsing utilities |
| `cache.py` | Thread-safe caching system for imported modules |
| `loader.py` | Module loading from various sources (names, file paths) |
| `installer.py` | Automatic package installation via pip |
| `validator.py` | Module compatibility validation |
| `async_import.py` | Asynchronous import functionality |
| `import_module.py` | Main entry point with unified API |

## Installation

Place the module in your Python path and import:

```python
from pyputil.core.importhub import import_module
from pyputil.core.importhub.core import ImportConfig, LazyModule
```

Core Classes

ImportConfig

Configuration container for import operations.

Attributes:

Attribute Type Default Description
target str Required Import target (module name or file path)
attr Optional[str] None Specific attribute to import
auto_install bool False Auto-install missing packages
version Optional[str] None Version constraint for installation
cache bool True Enable import caching
lazy bool False Enable lazy loading
reload bool False Force module reload
default Any None Fallback value on failure
install_name Optional[str] None PyPI name (if different from import name)
package Optional[str] None Package for relative imports
search_paths Optional[List[str]] None Additional module search paths
file_mode bool False Allow file path imports
validate bool False Validate module compatibility
silent bool False Suppress exceptions
return_spec bool False Return ModuleSpec instead of module
inject_globals Optional[Dict] None Globals to inject into module
strict_attr bool False Raise error for missing attributes
async_import bool False Enable async import

LazyModule

A module proxy that loads the actual module only when accessed. Reduces startup time for large applications.

```python
from pyputil.core.importhub.core import LazyModule

# Lazy module only loads when first attribute is accessed
lazy_os = LazyModule(spec)
print(lazy_os.path)  # Loads module here
```

LazyAttributeProxy

Proxy for lazy loading of specific module attributes.

```python
from pyputil.core.importhub.core import LazyAttributeProxy

# Only loads 'loads' when accessed
lazy_loads = LazyAttributeProxy(json_module, 'loads')
data = lazy_loads('{"key": "value"}')  # Loads here
```

ImportCache

Thread-safe cache for imported modules with expiration support.

Methods:

Method Description
get(key, max_age) Get cached module (None if expired)
set(key, module) Store module in cache
has(key) Check if key exists in cache
invalidate(key) Remove specific or all cache entries
get_cache_key(module_name, attr) Generate cache key
get_file_cache_key(file_path) Generate file-based cache key

ModuleLoader

Handles loading of modules from various sources.

Methods:

Method Description
load_module(module_name, reload, lazy, inject_globals, search_paths) Load module by name
load_from_file(file_path, reload, inject_globals) Load module from file path

PackageInstaller

Handles automatic package installation via pip.

Methods:

Method Description
install(package_name, version, upgrade) Install package using pip
uninstall(package_name) Uninstall package
is_installed(package_name) Check if package is installed

ModuleValidator

Validates module compatibility with current system.

Methods:

Method Description
validate(module_name) Validate module compatibility (raises ValidationError on failure)

AsyncImporter

Handles asynchronous module imports using a thread pool.

Methods:

Method Description
import_module(module_name, reload, lazy, inject_globals, search_paths) Async import by name
import_from_file(file_path, reload, inject_globals) Async import from file
shutdown() Shutdown thread pool

Usage Examples

Basic Module Import

```python
from pyputil.core.importhub import import_module

# Import a standard module
os_module = import_module("os")
print(os_module.getcwd())

# Import with attribute
json_loads = import_module("json", attr="loads")
data = json_loads('{"name": "test"}')
```

Auto-Install Missing Packages

```python
# Automatically install missing package
numpy = import_module("numpy", auto_install=True)
# Install specific version
requests = import_module("requests", auto_install=True, version="2.31.0")
# Use different PyPI name than import name
bs4 = import_module("bs4", auto_install=True, install_name="beautifulsoup4")
```

Lazy Loading

```python
# Module loads only when first used
heavy_module = import_module("tensorflow", lazy=True)
# At this point, tensorflow is NOT loaded

# First access triggers actual import
model = heavy_module.Sequential()  # Loads here
```

Safe Imports with Fallbacks

```python
# Return None if module missing (no exception)
optional_dep = import_module("optional_package", silent=True, default=None)

# Custom default value
db = import_module("mysql.connector", silent=True, default=MockDatabase())

# Check existence without raising
try:
    module = import_module("critical_dep", silent=False)
except ModuleNotFoundError:
    print("Critical dependency missing")
```

File-Based Imports

```python
# Import from local file
script = import_module("./scripts/tool.py", file_mode=True)

# Import with relative path
utils = import_module("../utils/helpers.py", file_mode=True)
```

Relative Imports

```python
# Import from within a package
utils = import_module(".utils", package="mypackage")
# Equivalent to: from mypackage import utils

submodule = import_module("..submodule", package="mypackage.module")
```

Plugin System with Search Paths

```python
# Load plugins from custom directories
plugin = import_module(
    "custom_plugin",
    search_paths=["/app/plugins", "/usr/local/plugins"],
    silent=True
)
```

Module Validation

```python
from pyputil.core.importhub import import_module
from pyputil.core.importhub.core import ValidationError

try:
    # Validate compatibility before using
    validated = import_module("some_package", validate=True)
except ValidationError as e:
    print(f"Module incompatible: {e}")
```

Async Imports

```python
import asyncio
from pyputil.core.importhub import import_module

async def main():
    # Non-blocking import
    module = await import_module("large_module", async_import=True)
    
    # Multiple concurrent imports
    results = await asyncio.gather(
        import_module("numpy", async_import=True),
        import_module("pandas", async_import=True),
        import_module("matplotlib", async_import=True),
    )
    return results

asyncio.run(main())
```

Caching Control

```python
# Caching enabled by default (second call returns cached)
module1 = import_module("datetime")
module2 = import_module("datetime")  # Returns cached version

# Force reload (bypasses cache)
module3 = import_module("datetime", reload=True)

# Disable caching
module4 = import_module("datetime", cache=False)
```

Injecting Globals

```python
# Inject configuration into imported module
module = import_module(
    "plugin",
    inject_globals={
        "API_KEY": "secret123",
        "DEBUG": True,
        "CONFIG_PATH": "/app/config"
    }
)
```

Strict Attribute Access

```python
# Raise error for missing attributes
try:
    module = import_module("os", attr="nonexistent", strict_attr=True)
except AttributeError as e:
    print(f"Attribute missing: {e}")

# Return None for missing attributes (default behavior)
result = import_module("os", attr="nonexistent")  # Returns None
```

Target String Format

The target parameter supports multiple formats:

Format Example Result
Module name "os" ('os', None)
Submodule "os.path" ('os.path', None)
Module:attribute "json:loads" ('json', 'loads')
Submodule:attribute "os.path:join" ('os.path', 'join')
File path "./module.py" ('./module.py', None)

```python
from pyputil.core.importhub.core import parse_target, is_file_path

module, attr = parse_target("json:loads")
# module = "json", attr = "loads"

is_path = is_file_path("./module.py")  # True
is_path = is_file_path("os")  # False
```

Cache Management

```python
from pyputil.core.importhub.core import get_cache

cache = get_cache()

# Check cache
if cache.has("numpy"):
    numpy = cache.get("numpy")

# Invalidate specific entry
cache.invalidate("numpy")

# Clear entire cache
cache.invalidate()

# Custom cache key
key = cache.get_cache_key("requests", "Session")
cache.set(key, requests_module)
```

Error Handling

```python
from pyputil.core.importhub import import_module
from pyputil.core.importhub.core import ValidationError
import sys

try:
    module = import_module(
        target="critical_package",
        auto_install=True,
        validate=True,
        strict_attr=True
    )
except ModuleNotFoundError as e:
    print(f"Package not found: {e}")
    sys.exit(1)
except ValidationError as e:
    print(f"Compatibility validation failed: {e}")
    sys.exit(1)
except AttributeError as e:
    print(f"Required attribute missing: {e}")
    sys.exit(1)
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)
```

Thread Safety

The caching system uses threading.RLock() for thread-safe operations:

```python
import threading
from pyputil.core.importhub import import_module

def worker():
    module = import_module("json", cache=True)
    return module

threads = [threading.Thread(target=worker) for _ in range(10)]
for t in threads:
    t.start()
for t in threads:
    t.join()
```

Advanced Configuration with ImportConfig

```python
from pyputil.core.importhub.core import ImportConfig
from pyputil.core.importhub import import_module

# Create configuration object
config = ImportConfig(
    target="my_module",
    attr="MyClass",
    auto_install=True,
    cache=True,
    lazy=True,
    validate=True
)

# Use with import_module (not directly supported, but config holds params)
```

Method Reference

import_module()

The main entry point function with all features.

Parameters:

Parameter Type Default Description
target str Required Import target (module or file path)
attr Optional[str] None Specific attribute to import
auto_install bool False Auto-install missing packages
version Optional[str] None Version constraint for installation
cache bool True Enable caching
lazy bool False Enable lazy loading
reload bool False Force module reload
default Any None Fallback value on failure
install_name Optional[str] None PyPI name if different
package Optional[str] None Package for relative imports
search_paths Optional[List[str]] None Additional search paths
file_mode bool False Allow file path imports
validate bool False Validate compatibility
silent bool False Suppress exceptions
return_spec bool False Return ModuleSpec
inject_globals Optional[Dict] None Globals to inject
strict_attr bool False Raise on missing attribute
async_import bool False Enable async import

Returns: The imported module, requested attribute, or default value. If async_import=True, returns a coroutine.

Logging Output Example

When configured with logging:

```
2024-01-15 10:30:45,123 - ImportHub - INFO - Importing module: requests
2024-01-15 10:30:45,124 - ImportHub - DEBUG - Cache miss for: requests
2024-01-15 10:30:45,456 - ImportHub - INFO - Module loaded: requests (2.31.0)
2024-01-15 10:30:45,457 - ImportHub - DEBUG - Cached: requests
```

Requirements

· Python 3.7+ (uses importlib, asyncio, dataclasses)
· Standard library only for core functionality
· pip required for auto_install feature (external)
· importlib.metadata for Python 3.8+ (backport available for 3.7)

Key Features Summary

Feature Description
Auto-install Automatically pip-install missing packages
Lazy loading Defer module loading until first access
Caching Thread-safe cache with expiration
Async imports Non-blocking imports via thread pool
Validation Check Python version, OS, architecture
File imports Import directly from file paths
Relative imports Support for dot-notation relative imports
Attribute injection Inject globals into module namespace
Fallback values Return defaults on failure
Plugin support Custom search paths for modules