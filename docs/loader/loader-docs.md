# PyPutil Loader System Documentation

## Overview

PyPutil Loader System is a comprehensive, production-grade framework for dynamic module loading, file processing, and code execution. It provides advanced capabilities for loading Python modules from various sources (files, URLs, code strings), transforming data files into dynamic modules, caching with intelligent eviction policies, lazy loading, hot reloading, and dynamic function calling with middleware pipelines.

## Architecture

The system consists of the following core modules:

| Module | Purpose |
|--------|---------|
| `Builder.py` | Module caching and optimization with bytecode compilation |
| `Caller.py` | Dynamic function/method calling with middleware pipeline |
| `CustomLoader.py` | Custom module loader registration and management |
| `DataLoader.py` | Converting data files (JSON, CSV, XML, YAML, INI, TXT) to modules |
| `LazyLoader.py` | Thread-safe lazy module loading with dependency tracking |
| `LoaderCache.py` | Sophisticated caching with weak references and eviction policies |
| `PyLoad.py` | High-level Python module loading from files, URLs, and code |
| `Reloader.py` | Module reloading with dependency tracking and safe reloading |
| `loader_util.py` | Utility functions for finding and getting module loaders |

---

## 1. PyLoad - High-Level Module Loading

### ModuleInfo

```python
@dataclass
class ModuleInfo:
    """Detailed information about a loaded module."""
    name: str           # Module name
    is_package: bool    # Whether module is a package
    file: str           # File path or "<built-in>"
    builtin: bool       # Whether built-in module
    functions: List[str] # Function names (deep scan)
    classes: List[str]   # Class names (deep scan)
    attributes: List[str] # Other attributes
```

ImportResult

```python
@dataclass
class ImportResult:
    """Aggregated result of import attempts."""
    loaded: Dict[str, ModuleInfo]  # Successfully loaded modules
    failed: List[ModuleLoadStatus]  # Failed imports
    cache_size: int                 # Number of cached modules
    modules: List[ModuleType]       # Module objects
```

Key Functions

load_modules()

```python
def load_modules(
    module_names: list,
    max_workers: int = 8,
    deep_scan: bool = True
) -> ImportResult
```

Description: Concurrently imports multiple modules using thread pool.

Example:

```python
from pyputil.loader import load_modules

# Import multiple modules concurrently
result = load_modules(['numpy', 'pandas', 'requests'], max_workers=3)

print(f"Loaded: {list(result.loaded.keys())}")
print(f"Failed: {[f.name for f in result.failed]}")

# Access module info
for name, info in result.loaded.items():
    print(f"{name}: {len(info.functions)} functions, {len(info.classes)} classes")
```

load_from_file()

```python
def load_from_file(file_path: str, register: bool = False) -> ModuleType
```

Description: Loads a Python module from any file path with unique naming to prevent collisions.

Example:

```python
from pyputil.loader import load_from_file

# Load module from custom path
module = load_from_file("/path/to/script.py", register=True)
result = module.my_function()
```

load_from_source()

```python
def load_from_source(filepath: str, name: str) -> Any
```

Description: Loads a specific variable/class/function from a Python source file.

Example:

```python
from pyputil.loader import load_from_source

# Load specific class from file
MyClass = load_from_source("models.py", "User")
user = MyClass(name="Alice")

# Load entire module
module = load_from_source("utils.py", "*")
```

load_from_code()

```python
def load_from_code(
    source: str,
    name: str = "module",
    save: bool = False,
    globals_: Optional[Dict] = None,
    allow_builtins: bool = True,
    allow_load_modules: bool = False,
    register: bool = True,
    override: bool = False
) -> ModuleType
```

Description: Creates a module from raw Python source code string with sandboxing options.

Example:

```python
from pyputil.loader import load_from_code

code = '''
def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"

VERSION = "1.0.0"
'''

# Create module from code
module = load_from_code(code, name="greeter", save=True)
print(module.greet("World"))  # Hello, World!
print(module.VERSION)         # 1.0.0

# Sandboxed - no imports allowed
try:
    module = load_from_code("import os", allow_load_modules=False)
except ImportBlockedError:
    print("Import blocked!")
```

load_from_url()

```python
def load_from_url(
    url: str,
    cache_dir: str = ".url_cache",
    timeout_sec: int = 10
) -> Optional[ModuleType]
```

Description: Downloads and loads Python module from URL with caching.

Example:

```python
from pyputil.loader import load_from_url

# Load module from remote URL
module = load_from_url("https://example.com/script.py")
if module:
    module.run()
```

loads_from_dir()

```python
def loads_from_dir(
    path: str,
    max_workers: int = 8,
    register: bool = False
) -> Dict[str, ModuleType]
```

Description: Recursively loads all .py files in a directory.

Example:

```python
from pyputil.loader import loads_from_dir

# Load all modules in directory
modules = loads_from_dir("./plugins", max_workers=4)
for name, module in modules.items():
    if hasattr(module, 'initialize'):
        module.initialize()
```

unload()

```python
def unload(module_name: str, deep: bool = False) -> bool
```

Description: Unloads a module from sys.modules with optional deep reference cleanup.

Example:

```python
from pyputil.loader import unload

# Unload module
if unload("my_module", deep=True):
    print("Module unloaded and references cleaned")
```

---

2. Reloader - Module Hot Reloading

ReloadError Hierarchy

```python
class ReloadError(Exception): pass
class ModuleNotFoundError(ReloadError): pass
class ReloadDependencyError(ReloadError): pass
```

Key Functions

reload_module()

```python
def reload_module(
    module: ModuleType,
    recursive: bool = False,
    deep: bool = False,
    clean_cache: bool = True,
    preserve_attributes: Optional[List[str]] = None,
    on_error: Optional[Callable[[str, Exception], None]] = None
) -> ModuleType
```

Description: Reloads a module with dependency tracking and attribute preservation.

Example:

```python
from pyputil.loader import reload_module
import myapp

# Basic reload
reloaded = reload_module(myapp)

# Recursive reload (all submodules)
reloaded = reload_module(myapp, recursive=True)

# Deep reload (also reload modules that depend on this one)
reloaded = reload_module(myapp, deep=True)

# Preserve specific attributes
reloaded = reload_module(myapp, preserve_attributes=['config', 'cache'])

# With error callback
def on_error(name, error):
    print(f"Failed to reload {name}: {error}")

reloaded = reload_module(myapp, on_error=on_error)
```

reload_name()

```python
def reload_name(
    module_name: str,
    recursive: bool = False,
    deep: bool = False,
    **kwargs
) -> ModuleType
```

Description: Reloads a module by name (string).

Example:

```python
from pyputil.loader import reload_name

# Reload by name
module = reload_name('myapp.utils')
```

reload_package()

```python
def reload_package(package_name: str, deep: bool = False, **kwargs) -> ModuleType
```

Description: Reloads an entire package and all its submodules.

Example:

```python
from pyputil.loader import reload_package

# Reload entire package
package = reload_package('myapp', deep=True, clean_cache=True)
```

safe_reload()

```python
def safe_reload(
    module: Union[ModuleType, str],
    fallback: Optional[Any] = None,
    **kwargs
) -> Optional[ModuleType]
```

Description: Safely reloads a module, returning fallback value on error.

Example:

```python
from pyputil.loader import safe_reload

# Safe reload with fallback
module = safe_reload('unstable_module', fallback=None)
if module is None:
    print("Using fallback implementation")
```

reload_matching()

```python
def reload_matching(
    pattern: str,
    attribute: str = "name",
    recursive: bool = True,
    **kwargs
) -> List[str]
```

Description: Reloads modules matching a pattern (by name or file path).

Example:

```python
from pyputil.loader import reload_matching

# Reload all modules containing 'utils' in name
reloaded = reload_matching('utils', attribute='name')

# Reload all modules in specific directory
reloaded = reload_matching('/project/src', attribute='file')
```

get_reloadable_modules()

```python
def get_reloadable_modules(
    include_stdlib: bool = False,
    prefix: Optional[str] = None
) -> List[str]
```

Description: Lists all modules that can be reloaded.

Example:

```python
from pyputil.loader import get_reloadable_modules

# Get all reloadable modules in project
modules = get_reloadable_modules(prefix='myproject')
print(f"Can reload {len(modules)} modules: {modules}")
```

reload_current_module()

```python
def reload_current_module(recursive: bool = False, **kwargs) -> ModuleType
```

Description: Reloads the module from which this function is called.

Example:

```python
# Inside a module
from pyputil.loader import reload_current_module

def reload_self():
    """Reload this module."""
    return reload_current_module(recursive=True)
```

---

3. LazyLoader - Lazy Module Loading

LazyLoader Class

```python
class LazyLoader(types.ModuleType):
    """
    Thread-safe, production-grade lazy module loader.
    
    Features:
    - Thread-safe initialization with double-checked locking
    - Attribute proxying and caching
    - Module reloading support
    - Custom import hooks
    - Dependency tracking
    - Error recovery and retry mechanisms
    """
```

Constructor Parameters:

Parameter Type Default Description
module_name str Required Fully qualified module name
package str None Package context for relative imports
eager bool False Load immediately if True
retry_on_error bool False Retry failed imports on next access
max_retries int 3 Maximum retry attempts
fallback_module str None Alternative module if primary fails
preload_hook Callable None Called after successful load
cache_attributes bool True Copy attributes for faster access
track_dependencies bool False Track which attributes are accessed
attributes_to_proxy Set[str] None Specific attributes to proxy
parent_resolution bool True Automatically resolve parent packages

Properties:

Property Description
is_loaded Whether module has been loaded
loaded_module Loaded module object (if loaded)
load_error Last error that occurred

Methods:

Method Description
reload() Force reload, discarding cached version
preload() Explicitly load without accessing attributes
get_accessed_attributes() Get accessed attributes (if tracking enabled)
create_weak_ref(callback) Create weak reference to loader
is_attribute_loaded(name) Check if attribute exists (may trigger load)
eager_context() Context manager ensuring module is loaded

Examples:

```python
from pyputil.loader import LazyLoader, lazy_load

# Basic lazy loading
pd = LazyLoader('pandas')
# pandas not loaded yet

df = pd.DataFrame({'a': [1, 2, 3]})  # pandas loads here

# With fallback
loader = LazyLoader(
    'optional_module',
    fallback_module='dummy_module',
    retry_on_error=True,
    max_retries=3
)

# With dependency tracking
loader = LazyLoader(
    'myapp.database',
    track_dependencies=True,
    cache_attributes=True
)
result = loader.query("SELECT * FROM users")

# Get accessed attributes
accessed = loader.get_accessed_attributes()
print(f"Accessed: {accessed}")

# Eager context
with loader.eager_context():
    # Module guaranteed to be loaded here
    loader.initialize()

# Convenience function
np = lazy_load('numpy')
```

---

4. LoaderCache - Sophisticated Caching System

ModuleCache Class

```python
class ModuleCache:
    """
    Comprehensive cache system for module-like objects.
    
    Features:
    - Weak reference support with auto-detection
    - Strong/weak reference promotion based on access patterns
    - Dependency tracking with forward/reverse relationships
    - Multiple eviction policies (TTL, LRU, LFU, HYBRID)
    - Access prediction using Markov chains
    - Statistics collection
    - Background auto-cleanup
    """
```

Constructor Parameters:

Parameter Type Default Description
enable_weakref bool/WeakRefSupport AUTO_DETECT Weak reference mode
default_ttl float None Global TTL in seconds
eviction_policy EvictionPolicy HYBRID Cache eviction strategy
max_size int None Maximum cache size
promotion_threshold int 10 Accesses before weak→strong promotion
enable_stats bool True Collect usage statistics
auto_cleanup_interval float None Background cleanup interval
warn_on_weakref_failure bool True Log warnings for weakref failures

Eviction Policies:

Policy Description
TTL Remove expired items
LRU Remove least recently used
LFU Remove least frequently used
HYBRID TTL then LRU
NONE No automatic eviction

WeakRefSupport Modes:

Mode Description
FULL Always use weak references (warn on failure)
AUTO_DETECT Use weakref if object supports it
STRONG_ONLY Never use weak references

Examples:

```python
from pyputil.loader import ModuleCache, WeakRefSupport, EvictionPolicy

# Basic cache
cache = ModuleCache(max_size=100, default_ttl=300)

# Store objects
cache['database'] = Database()
cache.store_weakref_compatible('config', {'host': 'localhost'})

# Retrieve
db = cache['database']
config = cache.get_weakref_compatible('config')

# Dependency tracking
cache.set_deps('web_app', WebApp(), ['database', 'cache', 'logger'])
deps = cache.get_deps('web_app')        # {'database', 'cache', 'logger'}
dependents = cache.get_dependents('database')  # {'web_app'}

# Metadata
cache.set_metadata('database', {'version': '2.0', 'author': 'admin'})
metadata = cache.get_metadata('database')

# Statistics
stats = cache.get_stats()
print(f"Hit rate: {stats['hit_rate']:.2%}")
print(f"Cache size: {stats['size']}")
print(f"Strong cache: {stats['strong_count']}")
print(f"Weak cache: {stats['weak_count']}")

# Cleanup
cache.clear_expired(ttl=60)  # Remove items older than 60 seconds
cache.clear_unused(threshold=3)  # Remove items accessed < 3 times
cache.clear_lru(count=10)  # Remove 10 least recently used

# Advanced: with auto-cleanup
cache = ModuleCache(
    auto_cleanup_interval=60,  # Clean every minute
    eviction_policy=EvictionPolicy.HYBRID,
    max_size=500,
    default_ttl=3600
)

# Context manager
with ModuleCache() as cache:
    cache['temp'] = data
    # Auto-cleanup on exit
```

ModulesProxy

```python
class ModulesProxy:
    """Proxy wrapper that mimics sys.modules interface."""
```

Example:

```python
from pyputil.loader import ModulesProxy, ModuleCache

# Replace sys.modules with cached version
cache = ModuleCache()
proxy = ModulesProxy(cache)

import sys
original_modules = sys.modules
sys.modules = proxy

# Now all imports go through cache
# ... your code ...

# Restore
sys.modules = original_modules
```

---

5. Builder - Module Caching and Optimization

BuildCache Class

```python
class BuildCache:
    """Cache manager for compiled Python modules."""
```

Key Functions

build()

```python
def build(
    module_path: Union[str, Path],
    cache_dir: Union[str, Path] = CACHE_DIR,
    force_rebuild: bool = False
) -> ModuleType
```

Description: Builds optimized cached version of a module.

Example:

```python
from pyputil.loader import build

# Build optimized version
module = build("utils/math_utils.py")

# Force rebuild
module = build("utils/math_utils.py", force_rebuild=True)
```

build_frame()

```python
def build_frame(
    track_usage: bool = False,
    cache_dir: Union[str, Path] = CACHE_DIR
) -> Union[Dict, Tuple]
```

Description: Builds cached versions of all modules in current frame.

Example:

```python
from pyputil.loader import build_frame

# Build and replace modules in current namespace
modules = build_frame()

# Track usage statistics
modules, stats = build_frame(track_usage=True)
print(f"Module usage: {stats}")
```

clear_cache() / get_cache_info()

```python
def clear_cache(cache_dir: Union[str, Path] = CACHE_DIR) -> None
def get_cache_info(cache_dir: Union[str, Path] = CACHE_DIR) -> Dict
```

Example:

```python
from pyputil.loader import get_cache_info, clear_cache

# Get cache information
info = get_cache_info()
print(f"Total files: {info['total_files']}")
print(f"Total size: {info['size_human']}")

# Clear all cache
clear_cache()
```

warmup_cache()

```python
def warmup_cache(
    module_paths: List[Union[str, Path]],
    cache_dir: Union[str, Path] = CACHE_DIR
) -> None
```

Description: Pre-builds cache for multiple modules.

Example:

```python
from pyputil.loader import warmup_cache

# Pre-cache frequently used modules
warmup_cache([
    "core/utils.py",
    "core/database.py",
    "core/api.py"
])
```

---

6. Caller - Dynamic Function Calling

Caller Class

```python
class Caller:
    """
    Dynamic caller with middleware pipeline.
    
    Features:
    - Dynamic function/method resolution
    - Middleware pipeline for cross-cutting concerns
    - Automatic caching with TTL
    - Retry with exponential backoff
    - Timeout enforcement
    - Call history tracking
    - Async and sync support
    """
```

Constructor Parameters:

Parameter Type Default Description
cache_ttl int 300 Cache TTL in seconds
max_retries int 3 Maximum retry attempts
timeout float 30.0 Default timeout in seconds
enable_logging bool True Enable built-in logging
cache_size_limit int 1000 Maximum cache size

Properties:

Property Description
last_call Most recent call target
last_result Most recent call result
call_history List of all call records
cache_size Current cache size
middleware_count Number of registered middlewares
success_rate Success rate percentage

Examples:

```python
from pyputil.loader import Caller

# Basic usage
caller = Caller()
result = caller.call('math.sqrt', 16)  # 4.0

# Async usage
result = await caller.acall('asyncio.sleep', 1)

# With custom timeout and retries
result = caller.call(
    'unreliable_api.fetch',
    user_id=123,
    timeout=5.0,
    retries=3
)

# Disable caching
result = caller.call('random.random', use_cache=False)

# Custom middleware
async def timing_middleware(ctx, next_call):
    start = time.time()
    result = await next_call(ctx)
    print(f"Call took {time.time() - start:.2f}s")
    return result

caller.add_middleware(timing_middleware)

# Temporary middleware
async with caller.temporary_middleware(profiling_middleware):
    result = await caller.acall('expensive_function')

# Call history
history = caller.get_call_history(limit=10, success_only=True)
for record in history:
    print(f"{record.target}: {record.duration:.3f}s")

# Cache statistics
stats = caller.get_cache_stats()
print(f"Cache hits: {stats['hits']}, misses: {stats['misses']}")

# Clear cache
caller.clear_cache()
```

---

7. DataLoader - File to Module Conversion

FileModule Class

```python
class FileModule:
    """
    Main module for converting files to Python modules.
    
    Features:
    - Multiple format support (JSON, CSV, XML, YAML, INI, TXT)
    - State-based lazy loading
    - Intelligent caching with LRU eviction
    - File watching for live updates
    - Automatic file linking based on naming patterns
    - Concurrent batch processing
    """
```

Constructor Parameters:

Parameter Type Default Description
use_states bool True Enable state-based lazy loading
cache_size int 2000 Maximum cached modules
auto_link bool True Enable automatic file linking

Methods:

Method Description
create_module(file_path, force_load) Create module from file
create_many(file_paths, max_concurrent) Create multiple modules concurrently
watch_file(file_path, on_change) Watch file for changes
register_handler(extensions, states) Register custom file handler

Examples:

```python
from pyputil.loader import to_module, to_modules, watch_module, scan_dir

# Single file to module
config = to_module('config.json')
print(config.database.host.load())  # Lazy load

# Multiple files concurrently
modules = await to_modules(['data1.json', 'data2.yaml'])

# Watch file for changes
with watch_module('config.json') as config:
    # Module auto-updates when file changes
    print(config.version.load())

# Scan directory
modules = scan_dir('./data', pattern='*.json', level='global')
for name, module in modules.items():
    print(f"Loaded: {name}")
```

File Format Handlers

JSON Handler:

```python
@FileModule.register_handler(['json', 'jsonl'])
def load_json(file_path: str, module: FileModule) -> Any
```

CSV/TSV Handler:

```python
@FileModule.register_handler(['csv', 'tsv'])
def load_csv(file_path: str, module: FileModule) -> Any
# Returns: {'headers': [...], 'rows': [...], 'stats': {...}}
```

YAML Handler:

```python
@FileModule.register_handler(['yaml', 'yml'])
def load_yaml(file_path: str, module: FileModule) -> Any
# Requires PyYAML: pip install PyYAML
```

XML Handler:

```python
@FileModule.register_handler(['xml'])
def load_xml(file_path: str, module: FileModule) -> Any
# Returns nested dictionary with _tag, _attrs, _text
```

INI Handler:

```python
@FileModule.register_handler(['ini', 'cfg'])
def load_ini(file_path: str, module: FileModule) -> Any
# Returns dict of sections to options
```

Text Handler:

```python
@FileModule.register_handler(['txt'])
def load_text(file_path: str, module: FileModule) -> Any
# Returns {'content': str, 'lines': List[str], 'line_count': int}
```

State Management

```python
from pyputil.loader import ModuleState, DataField

# Module states
# UNLOADED -> LOADED -> ACTIVE -> LINKED -> OPTIMIZED

field = DataField(name="data", potential_value=42)
print(field.state)  # UNLOADED

value = field.load()  # Transitions to LOADED
print(value)  # 42

def on_change():
    print("Data changed!")

field.watch(on_change)  # Transitions to ACTIVE
```

---

8. CustomLoader - Custom Module Loading

Classes

```python
class CustomLoader(importlib.abc.Loader):
    """Custom loader that creates and executes modules."""

class CustomFinder(importlib.abc.MetaPathFinder):
    """Meta path finder for custom module loading."""

class AddCustomLoader:
    """Loader for custom module loaders with priority-based ordering."""
```

Enumerations

```python
class CustomLoaderPriority(Enum):
    HIGHEST = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    LOWEST = 4

class CustomModuleHook(Enum):
    PRE_CREATE = "pre_create"
    POST_CREATE = "post_create"
    PRE_EXEC = "pre_exec"
    POST_EXEC = "post_exec"
    PRE_LOAD = "pre_load"
    POST_LOAD = "post_load"
```

Examples

```python
from pyputil.loader import add_custom_loader, CustomModuleHook

# Basic custom loader
def version_handler(module, prefix):
    module.__version__ = "2.0.0"

add_custom_loader("app.", version_handler, priority="high")

# With custom module creation
def custom_creator(module_name):
    module = ModuleType(module_name)
    module.custom_attr = "created by custom function"
    return module

add_custom_loader(
    "dynamic.",
    lambda m, p: setattr(m, 'loaded', True),
    create_module_func=custom_creator
)

# With lifecycle hooks
def pre_exec_hook(module, name, config):
    module._pre_executed = True

add_custom_loader(
    "hooked.",
    lambda m, p: None,
    hooks={CustomModuleHook.PRE_EXEC: [pre_exec_hook]}
)

# With custom code
code = '''
def hello():
    return "Hello from custom module!"
'''

add_custom_loader("code.", lambda m, p: None, module_code=code)

# Remove loader
from pyputil.loader import default_loader
default_loader.remove_loader("app.")
```

---

9. loader_util - Utility Functions

find_loader()

```python
def find_loader(
    module_name: str,
    raise_on_error: bool = False
) -> Optional[object]
```

Description: Finds the loader for a given Python module name.

Example:

```python
from pyputil.loader import find_loader

loader = find_loader("math")
print(loader)  # ExtensionFileLoader
```

get_loader()

```python
def get_loader(
    module_or_name: Union[str, ModuleType],
    use_cache: bool = True,
    raise_on_error: bool = False
) -> Optional[Any]
```

Description: Retrieves loader for module object or name.

Example:

```python
from pyputil.loader import get_loader
import math

# From module object
loader = get_loader(math)

# From module name
loader = get_loader("os.path")
```

---

Complete Example

```python
#!/usr/bin/env python3
"""Complete example using PyPutil Loader System."""

import asyncio
from pyputil.loader import (
    # PyLoad
    load_modules, load_from_file, load_from_code, loads_from_dir,
    # Reloader
    reload_module, safe_reload, reload_matching,
    # LazyLoader
    LazyLoader,
    # LoaderCache
    ModuleCache, EvictionPolicy,
    # Caller
    Caller,
    # DataLoader
    to_module, watch_module, scan_dir,
    # CustomLoader
    add_custom_loader
)

# 1. Lazy loading for heavy modules
pd = LazyLoader('pandas')
np = LazyLoader('numpy')

# 2. Cache for frequently accessed data
cache = ModuleCache(max_size=100, eviction_policy=EvictionPolicy.HYBRID)
cache['config'] = to_module('config.json')

# 3. Dynamic caller with middleware
caller = Caller(cache_ttl=60, max_retries=2)

async def timing_middleware(ctx, next_call):
    import time
    start = time.time()
    result = await next_call(ctx)
    print(f"Call took {time.time() - start:.3f}s")
    return result

caller.add_middleware(timing_middleware)

# 4. Watch configuration for changes
with watch_module('config.json') as config:
    db_host = config.database.host.load()

# 5. Load all plugins
plugins = loads_from_dir('./plugins', max_workers=4)

# 6. Custom loader for API modules
add_custom_loader("api.", lambda m, p: setattr(m, 'version', '1.0'))

# 7. Run
async def main():
    # Call API function
    result = await caller.acall('math.sqrt', 16)
    print(f"Result: {result}")
    
    # Load multiple modules
    result = load_modules(['requests', 'json'], max_workers=2)
    print(f"Loaded: {list(result.loaded.keys())}")

asyncio.run(main())
```

---

Requirements

· Python 3.7+
· Standard library only for core functionality
· Optional: PyYAML for YAML support (pip install PyYAML)

Key Features Summary

Feature Builder Caller CustomLoader DataLoader LazyLoader LoaderCache PyLoad Reloader
Module caching ✓ ✓ ✗ ✓ ✗ ✓ ✗ ✗
File loading ✗ ✗ ✗ ✓ ✗ ✗ ✓ ✗
Lazy loading ✗ ✗ ✗ ✓ ✓ ✓ ✗ ✗
Hot reload ✗ ✗ ✗ ✓ ✓ ✗ ✗ ✓
Middleware ✗ ✓ ✗ ✗ ✗ ✗ ✗ ✗
Weak references ✗ ✗ ✗ ✗ ✗ ✓ ✗ ✗
Dependency tracking ✗ ✗ ✗ ✗ ✓ ✓ ✗ ✓
Concurrency ✗ ✓ ✗ ✓ ✓ ✗ ✓ ✗