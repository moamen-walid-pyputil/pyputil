# API Management System Documentation

## Overview

The API Management System is a comprehensive framework for controlling, monitoring, and optimizing Python APIs. It provides a powerful `clean()` decorator that handles visibility control, lazy loading, caching, rate limiting, authentication, analytics, and much more with minimal configuration.

## Architecture

The system consists of the following core modules:

| Module | Purpose |
|--------|---------|
| `main.py` | Core `clean()` decorator and API management logic |
| `enums.py` | Privacy levels and API member type enumerations |
| `dataclasses.py` | `APIMetadata` data class for member information |
| `cache.py` | LRU caching with TTL support |
| `rate_limiter.py` | Token bucket rate limiting |
| `analytics.py` | Usage statistics and performance monitoring |
| `observer.py` | Publish-subscribe for API events |
| `decorators.py` | Profiling, type validation, deprecation helpers |
| `utils.py` | Type detection, docstring extraction, submodule loading |

## Quick Start

```python
from pyputil.api import clean

# Basic usage - automatically exposes public API
clean()

# Advanced configuration
clean(
    expose=['calculate', 'process', 'validate'],
    block=['_internal', '_helper'],
    cache=True,
    rate_limit={'calculate': 10},
    require_auth=['admin_function'],
    enable_analytics=True,
    lazy_load={'heavy_module': lambda: __import__('heavy_module')}
)
```

Core Function: clean()

The main entry point that configures API management for the calling module.

Function Signature

```python
def clean(
    *,
    # Basic configuration
    block: Iterable[str] = (),
    expose: Iterable[str] | None = None,
    error_on: Dict[str, str] | None = None,
    
    # Lazy loading
    lazy_load: Dict[str, Callable[[], Any]] | None = None,
    lazy_config: Dict[str, Dict[str, Any]] | None = None,
    
    # Lifecycle management
    deprecated: Dict[str, str] | None = None,
    experimental: Iterable[str] | None = None,
    version_added: Dict[str, str] | None = None,
    version_removed: Dict[str, str] | None = None,
    version_deprecated: Dict[str, str] | None = None,
    
    # Performance & caching
    cache: bool = True,
    cache_config: Dict[str, Any] | None = None,
    rate_limit: Dict[str, int] | None = None,
    
    # Security & access control
    require_auth: Iterable[str] | None = None,
    roles: Dict[str, List[str]] | None = None,
    ip_whitelist: Iterable[str] | None = None,
    ip_blacklist: Iterable[str] | None = None,
    
    # Analytics & monitoring
    enable_analytics: bool = False,
    analytics_config: Dict[str, Any] | None = None,
    
    # Documentation & metadata
    metadata: Dict[str, Dict[str, Any]] | None = None,
    tags: Dict[str, List[str]] | None = None,
    examples: Dict[str, List[str]] | None = None,
    
    # Advanced features
    allow_submodules: bool = True,
    allow_dynamic: bool = False,
    strict: bool = False,
    validate_signatures: bool = False,
    type_hints: bool = True,
    
    # Performance optimization
    preload: Iterable[str] | None = None,
    background_load: Iterable[str] | None = None,
    
    # Custom handlers
    before_access: Callable[[str], None] | None = None,
    after_access: Callable[[str, Any], None] | None = None,
    on_error: Callable[[str, Exception], None] | None = None,
    
    # Testing & debugging
    mock: Dict[str, Any] | None = None,
    debug: bool = False,
) -> None
```

Usage Examples

Basic API Exposure

```python
# mymodule.py
from pyputil.api import clean

def public_function():
    """This will be exposed."""
    return "public"

def _private_function():
    """This will be hidden."""
    return "private"

__version__ = "1.0.0"

# Auto-discover public names
clean()

# __all__ is automatically created
print(__all__)  # ('public_function', '__version__')
```

Explicit Exposure and Blocking

```python
clean(
    expose=['calculate', 'validate', 'CONSTANTS'],
    block=['_internal_helper', '_cache'],
    error_on={'deprecated_func': "This function is no longer available"}
)
```

Lazy Loading for Expensive Imports

```python
clean(
    lazy_load={
        'pandas': lambda: __import__('pandas'),
        'numpy': lambda: __import__('numpy'),
        'heavy_compute': lambda: importlib.import_module('heavy_compute')
    },
    preload=['pandas'],  # Load immediately
    background_load=['numpy'],  # Load in background thread
    lazy_config={
        'pandas': {'timeout': 30, 'retry': 3}
    }
)
```

Deprecation and Version Management

```python
clean(
    deprecated={
        'old_function': "Use new_function() instead",
        'legacy_api': "Will be removed in v3.0"
    },
    experimental={'experimental_feature', 'beta_api'},
    version_added={
        'new_feature': '2.0.0',
        'enhanced_api': '1.5.0'
    },
    version_deprecated={
        'old_function': '2.0.0'
    },
    version_removed={
        'legacy_api': '3.0.0'
    }
)
```

Caching and Performance

```python
clean(
    cache=True,
    cache_config={
        'max_size': 500,
        'ttl': 300  # 5 minutes
    },
    rate_limit={
        'expensive_query': 5,   # 5 calls per second
        'batch_process': 2,     # 2 calls per second
        'api_endpoint': 10
    },
    preload=['common_function', 'constants']
)
```

Security and Access Control

```python
clean(
    require_auth={'admin_panel', 'user_delete', 'settings_write'},
    roles={
        'admin_panel': ['admin', 'superuser'],
        'user_delete': ['admin'],
        'report_view': ['user', 'admin', 'manager']
    },
    ip_whitelist=['192.168.1.0/24', '10.0.0.1'],
    ip_blacklist=['203.0.113.0/24']
)
```

Analytics and Monitoring

```python
clean(
    enable_analytics=True,
    analytics_config={
        'log_errors': True,
        'log_performance': True,
        'sample_rate': 1.0,
        'export_endpoint': '/api/stats'
    }
)

# After module usage, access statistics
stats = get_api_stats()
print(f"Total calls: {stats['analytics']['total_calls']}")
print(f"Cache hit rate: {stats['cache']['hit_rate']:.2%}")

# Get performance report
report = get_performance_report(sort_by='avg_duration', limit=5)
for item in report:
    print(f"{item['name']}: {item['avg_duration']:.3f}s")
```

Custom Callbacks

```python
def log_access(api_name: str):
    print(f"Accessing: {api_name}")

def log_result(api_name: str, result: Any):
    print(f"{api_name} returned: {result}")

def handle_error(api_name: str, error: Exception):
    print(f"Error in {api_name}: {error}")

clean(
    before_access=log_access,
    after_access=log_result,
    on_error=handle_error
)
```

Testing with Mocks

```python
clean(
    debug=True,
    mock={
        'database': MockDatabase(),
        'api_client': MockAPIClient(),
        'expensive_calc': lambda x: x * 2  # Simplified version
    },
    strict=True  # Validate all configurations
)
```

Dynamic API Registration

```python
from mymodule import clean

clean(allow_dynamic=True)

# Later, register new API members dynamically
register_api('new_function', lambda x: x * 2, public=True)
register_api(
    'configured_api',
    MyComplexClass,
    public=True,
    metadata={'rate_limit': 5, 'requires_auth': True}
)
```

Internationalization

```python
clean(
    i18n={
        'greeting': {
            'en': 'Hello',
            'es': 'Hola',
            'fr': 'Bonjour'
        },
        'error_message': {
            'en': 'An error occurred',
            'es': 'Ocurrió un error'
        }
    }
)
```

Built-in API Functions

After calling clean(), the following functions are available in the module:

Function Description
get_api_stats() Get comprehensive API usage statistics
search_api(query, search_in, limit, tags, min_version, max_version) Search API members by various criteria
clear_cache(names) Clear cache for specific names or all
get_performance_report(sort_by, limit, min_calls) Get performance report for API members
register_api(name, obj, public, metadata) Dynamically register new API members

Search API Examples

```python
# Search by name
results = search_api("calculate")

# Search in docstrings
results = search_api("process data", search_in="docstring")

# Filter by tags
results = search_api("auth", tags=["security", "authentication"])

# Filter by version
results = search_api("api", min_version="2.0", max_version="3.0")

# Combine filters
results = search_api(
    "database",
    search_in="all",
    tags=["core", "storage"],
    limit=10
)
```

Enumerations

PrivacyLevel

Value Description
PUBLIC Accessible to everyone
PROTECTED Accessible within package and subclasses
PRIVATE Accessible only within defining module/class
INTERNAL Internal use only
SECRET Requires authentication/authorization

APIMemberType

Value Description
FUNCTION Regular function
CLASS Class definition
MODULE Module/package
VARIABLE Regular variable
CONSTANT Constant (uppercase)
PROPERTY Property descriptor
METHOD Class method
ASYNC_FUNCTION Async function
ASYNC_METHOD Async method
CONTEXT_MANAGER Context manager
DECORATOR Decorator function
GENERATOR Generator function

Helper Decorators

@profile_api

Profiles function performance (execution time and memory usage).

```python
from pyputil.api.decorators import profile_api

@profile_api
def expensive_operation():
    # Function is automatically profiled
    pass
```

@validate_types

Validates function arguments against type hints at runtime.

```python
from pyputil.api.decorators import validate_types

@validate_types
def add(a: int, b: int) -> int:
    return a + b

add(1, 2)      # OK
add("1", 2)    # Raises TypeError
```

@deprecated

Marks function as deprecated with custom message.

```python
from pyputil.api.decorators import deprecated

@deprecated("Use process_data() instead")
def old_process():
    pass
```

@experimental

Marks function as experimental (emits FutureWarning).

```python
from pyputil.api.decorators import experimental

@experimental
def new_feature():
    pass
```

Rate Limiter

The RateLimiter class implements token bucket algorithm:

```python
from pyputil.api.rate_limiter import RateLimiter

limiter = RateLimiter(calls_per_second=5)

if limiter.check_limit("my_api"):
    make_api_call()

remaining = limiter.get_remaining("my_api")
print(f"Remaining calls: {remaining}")
```

APICache

LRU cache with TTL support:

```python
from pyputil.api.cache import APICache

cache = APICache(max_size=100, ttl=300)  # 5 minutes

cache.set("key", expensive_value)
value = cache.get("key")

stats = cache.stats()
print(f"Cache hit rate: {stats['hit_rate']:.2%}")
```

APIObserver

Publish-subscribe for API events:

```python
from pyputil.api.observer import APIObserver

observer = APIObserver()

def log_access(name):
    print(f"Accessing: {name}")

observer.subscribe("before_access", log_access)

# When clean() is called with before_access, observers are notified
```

Complete Example

```python
# mymodule.py
from pyputil.api import clean

# Module code
VERSION = "2.0.0"

def calculate(x: int, y: int) -> int:
    """Add two numbers."""
    return x + y

def _helper(x: int) -> int:
    """Internal helper - not exposed."""
    return x * 2

def expensive_operation(data: list) -> list:
    """CPU-intensive operation."""
    return [x ** 2 for x in data]

# Configure API
clean(
    expose=['calculate', 'expensive_operation', 'VERSION'],
    block=['_helper'],
    cache=True,
    cache_config={'max_size': 100, 'ttl': 60},
    rate_limit={'expensive_operation': 2},
    enable_analytics=True,
    before_access=lambda name: print(f"Accessing {name}"),
    version_added={'expensive_operation': '2.0.0'},
    tags={
        'calculate': ['math', 'basic'],
        'expensive_operation': ['performance', 'data']
    },
    examples={
        'calculate': ['>>> calculate(2, 3)\n5'],
        'expensive_operation': ['>>> expensive_operation([1, 2, 3])\n[1, 4, 9]']
    }
)

# Usage from another module
# from mymodule import calculate, expensive_operation
# result = calculate(5, 3)  # Logged and cached
```

Requirements

· Python 3.8+
· Standard library only for core functionality
· Optional: psutil for memory profiling
· Optional: packaging for version comparison
· Optional: importlib.metadata for version detection

Key Features Summary

Feature Description
Auto-discovery Automatically determines public API from naming conventions
Lazy loading Defer expensive imports until first access
Caching LRU cache with TTL for frequently accessed values
Rate limiting Token bucket algorithm per API member
Deprecation Version-aware deprecation warnings
Access control Role-based and IP-based access control
Analytics Comprehensive usage and performance metrics
Event hooks Before/after access and error callbacks
Dynamic registration Runtime API member registration
Type validation Runtime type hint validation
Profiling Execution time and memory profiling
Search Full-text search across API members
Versioning Track when features were added/deprecated/removed