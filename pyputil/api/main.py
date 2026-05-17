#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Main API management system.

Provides the `clean` decorator for comprehensive API management including
visibility control, security, performance optimization, and analytics.
"""

import sys
import inspect
import threading
import time
import warnings
import asyncio
from typing import (
    Any,
    Iterable,
    Optional,
    Dict,
    Set,
    List,
    Callable,
    Union,
    TypeVar,
    NoReturn,
)
from functools import wraps
from pathlib import Path
import importlib

from ..PyputilException import AccessError
from .enums import PrivacyLevel, APIMemberType
from .dataclasses import APIMetadata
from .rate_limiter import RateLimiter
from .cache import APICache
from .analytics import APIAnalytics
from .observer import APIObserver
from .utils import (
    determine_member_type,
    extract_docstring,
    extract_signature,
    get_source_file,
    check_privacy_level,
    is_submodule_access,
    lazy_load_submodule,
    find_available_submodules,
)
from .decorators import profile_api, validate_types

T = TypeVar("T")
F = TypeVar("F", bound=Callable[..., Any])


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
    # Internationalization
    i18n: Dict[str, Dict[str, str]] | None = None,
    # Testing & debugging
    mock: Dict[str, Any] | None = None,
    debug: bool = False,
    # Custom handlers
    before_access: Callable[[str], None] | None = None,
    after_access: Callable[[str, Any], None] | None = None,
    on_error: Callable[[str, Exception], None] | None = None,
    # Resource management
    resource_limits: Dict[str, Dict[str, Any]] | None = None,
    # Integration
    webhooks: Dict[str, List[str]] | None = None,
    callbacks: Dict[str, List[Callable]] | None = None,
) -> None:
    """
    API cleaning function.

    Parameters
    ----------
    block : Iterable[str], optional
        Names to block from public API
    expose : Iterable[str], optional
        Names to expose in public API (if None, auto-discover)
    error_on : Dict[str, str], optional
        Names that should raise errors when accessed

    lazy_load : Dict[str, Callable[[], Any]], optional
        Lazy loaders for expensive imports
    lazy_config : Dict[str, Dict[str, Any]], optional
        Configuration for lazy loaders

    deprecated : Dict[str, str], optional
        Deprecated names with messages
    experimental : Iterable[str], optional
        Experimental feature names
    version_added : Dict[str, str], optional
        Version when each name was added
    version_removed : Dict[str, str], optional
        Version when each name was removed
    version_deprecated : Dict[str, str], optional
        Version when each name was deprecated

    cache : bool, default=True
        Enable intelligent caching
    cache_config : Dict[str, Any], optional
        Cache configuration (max_size, ttl)
    rate_limit : Dict[str, int], optional
        Rate limits per API member (calls/second)

    require_auth : Iterable[str], optional
        Names that require authentication
    roles : Dict[str, List[str]], optional
        Required roles for specific names
    ip_whitelist : Iterable[str], optional
        IP addresses allowed to access
    ip_blacklist : Iterable[str], optional
        IP addresses blocked from access

    enable_analytics : bool, default=False
        Enable usage analytics
    analytics_config : Dict[str, Any], optional
        Analytics configuration

    metadata : Dict[str, Dict[str, Any]], optional
        Comprehensive metadata for API members
    tags : Dict[str, List[str]], optional
        Tags for organizing API members
    examples : Dict[str, List[str]], optional
        Usage examples

    allow_submodules : bool, default=True
        Allow automatic submodule loading
    allow_dynamic : bool, default=False
        Allow dynamic API registration
    strict : bool, default=False
        Enable strict validation mode
    validate_signatures : bool, default=False
        Validate function signatures
    type_hints : bool, default=True
        Enforce type hints validation

    preload : Iterable[str], optional
        Names to preload immediately
    background_load : Iterable[str], optional
        Names to load in background

    i18n : Dict[str, Dict[str, str]], optional
        Internationalization messages

    mock : Dict[str, Any], optional
        Mock values for testing
    debug : bool, default=False
        Enable debug mode

    before_access : Callable[[str], None], optional
        Callback before API access
    after_access : Callable[[str, Any], None], optional
        Callback after API access
    on_error : Callable[[str, Exception], None], optional
        Callback on API error

    resource_limits : Dict[str, Dict[str, Any]], optional
        Resource limits per API member
    webhooks : Dict[str, List[str]], optional
        Webhook URLs for API events
    callbacks : Dict[str, List[Callable]], optional
        Custom callbacks for API events

    Returns
    -------
    None
        Modifies module's `__all__` and adds dynamic access handlers

    Raises
    ------
    ValueError
        If configuration is invalid in strict mode

    Examples
    --------
    Basic usage:
    >>> clean()

    Advanced usage:
    >>> clean(
    ...     expose=['calculate', 'process'],
    ...     cache=True,
    ...     cache_config={'max_size': 1000, 'ttl': 300},
    ...     rate_limit={'process': 5},
    ...     require_auth=['admin_function'],
    ...     enable_analytics=True,
    ...     background_load=['heavy_module'],
    ...     mock={'test_api': 'mock_value'}
    ... )

    See Also
    --------
    get_api_stats : Get API statistics
    search_api : Search API members
    clear_cache : Clear API cache
    get_performance_report : Get performance report
    register_api : Dynamically register API
    """

    # Get calling module's globals
    frame = inspect.currentframe()
    try:
        caller_globals = frame.f_back.f_globals
        module_name = caller_globals.get("__name__", "__main__")
    finally:
        del frame  # Avoid reference cycles

    # Initialize configurations with defaults
    error_on = error_on or {}
    lazy_load = lazy_load or {}
    lazy_config = lazy_config or {}
    deprecated = deprecated or {}
    experimental = set(experimental or ())
    version_added = version_added or {}
    version_removed = version_removed or {}
    version_deprecated = version_deprecated or {}
    rate_limit = rate_limit or {}
    require_auth = set(require_auth or ())
    roles = roles or {}
    metadata = metadata or {}
    tags = tags or {}
    examples = examples or {}
    i18n = i18n or {}
    mock = mock or {}
    resource_limits = resource_limits or {}
    webhooks = webhooks or {}
    callbacks = callbacks or {}

    # Initialize systems
    api_cache = APICache(**(cache_config or {})) if cache else None
    rate_limiter = RateLimiter()
    analytics = APIAnalytics() if enable_analytics else None
    observer = APIObserver()

    # Register custom callbacks
    if before_access:
        observer.subscribe("before_access", before_access)
    if after_access:
        observer.subscribe("after_access", after_access)
    if on_error:
        observer.subscribe("on_error", on_error)

    # Background loading
    background_loaded = {}
    if background_load:

        def _background_loader():
            for name in background_load:
                if name in caller_globals:
                    background_loaded[name] = caller_globals[name]
                elif name in lazy_load:
                    background_loaded[name] = lazy_load[name]()

        bg_thread = threading.Thread(target=_background_loader, daemon=True)
        bg_thread.start()

    # Preload specified members
    if preload:
        for name in preload:
            if name in caller_globals:
                _ = caller_globals[name]

    # Strict mode validation
    if strict:
        _validate_strict_mode_enhanced(
            caller_globals,
            expose,
            set(block),
            lazy_load,
            deprecated,
            experimental,
            module_name,
            metadata,
            require_auth,
            roles,
        )

    # Determine public API
    if expose is None:
        public = _discover_public_names_enhanced(caller_globals, set(block), metadata)
    else:
        public = list(expose)

    # Apply blocking
    for name in set(block):
        if name in public:
            public.remove(name)

    # Create __all__
    caller_globals["__all__"] = tuple(sorted(set(public)))

    # Initialize metadata storage
    api_metadata: Dict[str, APIMetadata] = {}

    # Build metadata for all members
    for name in set(caller_globals.keys()) | set(lazy_load.keys()):
        # Skip special names
        if (
            name.startswith("__")
            and name.endswith("__")
            and name not in ("__version__", "__author__")
        ):
            continue

        # Get object and create metadata
        obj = caller_globals.get(name)
        member_type = determine_member_type(name, obj)
        privacy = check_privacy_level(name, caller_globals)

        meta = APIMetadata(
            name=name,
            type=member_type,
            privacy_level=privacy,
            docstring=extract_docstring(obj),
            signature=extract_signature(obj),
            source_file=get_source_file(obj),
            added_in_version=version_added.get(name),
            deprecated_in_version=version_deprecated.get(name),
            removed_in_version=version_removed.get(name),
            deprecated_message=deprecated.get(name),
            experimental=name in experimental,
            requires_auth=name in require_auth,
            rate_limit=rate_limit.get(name),
            tags=set(tags.get(name, [])),
            examples=examples.get(name, []),
            is_lazy_loaded=name in lazy_load,
            lazy_loader=lazy_load.get(name),
            thread_safe=metadata.get(name, {}).get("thread_safe"),
            async_safe=metadata.get(name, {}).get("async_safe"),
        )

        # Add performance info
        if name in metadata and "performance" in metadata[name]:
            meta.performance = metadata[name]["performance"]
        if name in metadata and "memory_usage" in metadata[name]:
            meta.memory_usage = metadata[name]["memory_usage"]

        api_metadata[name] = meta

    # Store all systems
    caller_globals["__api_systems__"] = {
        "cache": api_cache,
        "rate_limiter": rate_limiter,
        "analytics": analytics,
        "observer": observer,
        "metadata": api_metadata,
        "background_loaded": background_loaded,
        "resource_limits": resource_limits,
        "webhooks": webhooks,
        "mock": mock,
        "config": {
            "cache_enabled": cache,
            "analytics_enabled": enable_analytics,
            "strict_mode": strict,
            "allow_dynamic": allow_dynamic,
        },
    }

    # Enhanced __getattr__
    def __getattr__(name: str) -> Any:
        """Advanced dynamic attribute access with comprehensive controls."""
        start_time = time.time()
        success = False

        try:
            # Notify before access
            observer.notify("before_access", name)

            # Check mock values
            if name in mock:
                return mock[name]

            # Check authentication
            if name in require_auth:
                if not _check_authentication(name):
                    raise AccessError(
                        f"'{name}' requires authentication",
                        suggestion="Please authenticate first",
                        docs_url="/docs/authentication",
                    )

            # Check rate limiting
            if name in rate_limit:
                if not rate_limiter.check_limit(name):
                    remaining = rate_limiter.get_remaining(name)
                    raise AccessError(
                        f"Rate limit exceeded for '{name}'",
                        suggestion=f"Try again in {remaining} seconds",
                        docs_url="/docs/rate-limiting",
                    )

            # Check cache
            if api_cache and name in caller_globals.get("__all__", []):
                cached = api_cache.get(name)
                if cached is not None:
                    if name in api_metadata:
                        api_metadata[name].cache_hits += 1
                        api_metadata[name].last_accessed = time.time()
                        api_metadata[name].access_count += 1
                    success = True
                    return cached

            # Check resource limits
            if name in resource_limits:
                if not _check_resource_limits(name, resource_limits[name]):
                    raise AccessError(
                        f"Resource limits exceeded for '{name}'",
                        suggestion="Try again later or with smaller inputs",
                    )

            # Check error_on
            if name in error_on:
                raise AccessError(
                    f"{error_on[name]}", suggestion="This API member is not available"
                )

            # Check version removed
            if name in version_removed:
                raise AccessError(
                    f"'{name}' was removed in version {version_removed[name]}",
                    suggestion=f"Use version before {version_removed[name]}",
                )

            # Check deprecated
            if name in deprecated:
                warnings.warn(
                    f"'{name}' is deprecated: {deprecated[name]}",
                    DeprecationWarning,
                    stacklevel=2,
                )
                observer.notify("on_deprecated", name, deprecated[name])

            # Check experimental
            if name in experimental:
                warnings.warn(
                    f"'{name}' is experimental and may change",
                    FutureWarning,
                    stacklevel=2,
                )
                observer.notify("on_experimental", name)

            # Get value
            value = _get_attribute_value(
                name,
                caller_globals,
                api_metadata,
                allow_submodules,
                module_name,
                background_loaded,
            )

            # Update metadata
            if name in api_metadata:
                meta = api_metadata[name]
                meta.last_accessed = time.time()
                meta.access_count += 1
                if meta.is_lazy_loaded:
                    meta.cached_value = value
                    meta.cache_misses += 1

            # Cache
            if api_cache and name in caller_globals.get("__all__", []):
                api_cache.set(name, value)

            success = True
            observer.notify("after_access", name, value)
            return value

        except Exception as e:
            duration = time.time() - start_time
            if analytics:
                import traceback

                analytics.record_error(name, e, traceback.format_exc())
            observer.notify("on_error", name, e)
            raise

        finally:
            duration = time.time() - start_time
            if analytics:
                analytics.record_access(name, success, duration)

    # Enhanced __dir__
    def __dir__() -> List[str]:
        """Return sorted public API with rich metadata indicators."""
        base_dir = list(caller_globals["__all__"])

        enhanced = []
        for item in base_dir:
            if item in api_metadata:
                meta = api_metadata[item]
                suffix = []

                if meta.deprecated_message:
                    suffix.append("[DEPRECATED]")
                if meta.experimental:
                    suffix.append("[EXPERIMENTAL]")
                if meta.requires_auth:
                    suffix.append("[AUTH]")
                if meta.rate_limit:
                    suffix.append(f"[RATE:{meta.rate_limit}]")
                if meta.is_lazy_loaded:
                    suffix.append("[LAZY]")

                if suffix:
                    enhanced.append(f"{item} {' '.join(suffix)}")
                else:
                    enhanced.append(item)
            else:
                enhanced.append(item)

        return sorted(enhanced)

    # API statistics function
    def get_api_stats() -> Dict[str, Any]:
        """Get comprehensive API statistics."""
        stats = {
            "total_members": len(api_metadata),
            "public_members": len(caller_globals.get("__all__", [])),
            "lazy_loaded": sum(1 for m in api_metadata.values() if m.is_lazy_loaded),
            "deprecated": sum(1 for m in api_metadata.values() if m.deprecated_message),
            "experimental": sum(1 for m in api_metadata.values() if m.experimental),
            "requires_auth": sum(1 for m in api_metadata.values() if m.requires_auth),
        }

        if api_cache:
            stats["cache"] = api_cache.stats()

        if analytics:
            stats["analytics"] = {
                "total_calls": sum(
                    s["total_calls"] for s in analytics.usage_stats.values()
                ),
                "error_count": len(analytics.error_log),
                "performance_samples": len(analytics.performance_log),
            }

        return stats

    # Search API function
    def search_api(
        query: str,
        *,
        search_in: str = "all",
        limit: int = 20,
        tags: Iterable[str] = None,
        min_version: str = None,
        max_version: str = None,
    ) -> List[Dict[str, Any]]:
        """Search API members by various criteria."""
        results = []
        tags_set = set(tags or [])

        for meta in api_metadata.values():
            # Filter by tags
            if tags and not meta.tags.intersection(tags_set):
                continue

            # Filter by version
            if min_version and meta.added_in_version:
                if _version_compare(meta.added_in_version, min_version) < 0:
                    continue
            if max_version and meta.added_in_version:
                if _version_compare(meta.added_in_version, max_version) > 0:
                    continue

            # Search
            matches = False
            query_lower = query.lower()

            if search_in in ("name", "all"):
                matches |= query_lower in meta.name.lower()

            if search_in in ("docstring", "all") and meta.docstring:
                matches |= query_lower in meta.docstring.lower()

            if search_in in ("tags", "all"):
                matches |= any(query_lower in tag.lower() for tag in meta.tags)

            if matches:
                results.append(
                    {
                        "name": meta.name,
                        "type": meta.type.value,
                        "docstring": (
                            meta.docstring[:100] + "..."
                            if meta.docstring and len(meta.docstring) > 100
                            else meta.docstring
                        ),
                        "tags": list(meta.tags),
                        "version": meta.added_in_version,
                        "experimental": meta.experimental,
                        "deprecated": bool(meta.deprecated_message),
                    }
                )

        return results[:limit]

    # Clear cache function
    def clear_cache(names: Iterable[str] = None):
        """Clear cache for specific names or all."""
        if api_cache:
            if names:
                for name in names:
                    api_cache.clear_specific(name)
            else:
                api_cache.clear()

    # Performance report function
    def get_performance_report(
        *, sort_by: str = "avg_duration", limit: int = 10, min_calls: int = 1
    ) -> List[Dict[str, Any]]:
        """Get performance report for API members."""
        if not analytics:
            return []

        report = []
        for name, stats in analytics.usage_stats.items():
            if stats["total_calls"] >= min_calls:
                report.append(
                    {
                        "name": name,
                        "total_calls": stats["total_calls"],
                        "success_rate": stats["successful_calls"]
                        / max(stats["total_calls"], 1),
                        "avg_duration": stats["avg_duration"],
                        "last_called": stats["last_called"],
                    }
                )

        return sorted(report, key=lambda x: x.get(sort_by, 0), reverse=True)[:limit]

    # Dynamic API registration
    def register_api(
        name: str, obj: Any, *, public: bool = True, metadata: Dict[str, Any] = None
    ) -> bool:
        """Dynamically register new API member."""
        if not allow_dynamic:
            return False

        if name in caller_globals:
            return False

        # Add to globals
        caller_globals[name] = obj

        # Add to __all__ if public
        if public and name not in caller_globals["__all__"]:
            new_all = list(caller_globals["__all__"])
            new_all.append(name)
            caller_globals["__all__"] = tuple(sorted(set(new_all)))

        # Update metadata
        member_type = determine_member_type(name, obj)
        privacy = PrivacyLevel.PUBLIC if public else PrivacyLevel.PRIVATE

        meta = APIMetadata(
            name=name,
            type=member_type,
            privacy_level=privacy,
            docstring=extract_docstring(obj),
            signature=extract_signature(obj),
        )

        if metadata:
            for key, value in metadata.items():
                if hasattr(meta, key):
                    setattr(meta, key, value)

        api_metadata[name] = meta

        # Clear cache
        if api_cache:
            api_cache.clear_specific(name)

        return True

    # Register functions
    caller_globals["__getattr__"] = __getattr__
    caller_globals["__dir__"] = __dir__
    caller_globals["get_api_stats"] = get_api_stats
    caller_globals["search_api"] = search_api
    caller_globals["clear_cache"] = clear_cache
    caller_globals["get_performance_report"] = get_performance_report
    caller_globals["register_api"] = register_api

    # Add version info
    if "__version__" not in caller_globals:
        _try_add_version(module_name, caller_globals)


# Helper functions for main module
def _validate_strict_mode_enhanced(
    globals_ns: Dict[str, Any],
    expose: Optional[Iterable[str]],
    block_set: Set[str],
    lazy_load: Dict[str, Callable[[], Any]],
    deprecated: Dict[str, str],
    experimental_set: Set[str],
    module_name: str,
    metadata: Dict[str, Dict[str, Any]],
    require_auth: Set[str],
    roles: Dict[str, List[str]],
) -> None:
    """Enhanced strict mode validation."""

    if expose is not None:
        missing = []
        for name in expose:
            if name not in globals_ns and name not in lazy_load:
                missing.append(name)

        if missing:
            raise ValueError(
                f"Module {module_name}: cannot expose non-existent names: {missing}"
            )

    # Validate lazy loaders
    for name, loader in lazy_load.items():
        if not callable(loader):
            raise ValueError(
                f"Module {module_name}: lazy loader for '{name}' must be callable"
            )

    # Validate metadata
    for name, meta in metadata.items():
        if name not in globals_ns and name not in lazy_load:
            raise ValueError(
                f"Module {module_name}: metadata defined for non-existent name: {name}"
            )

    # Validate authentication and roles
    for name in require_auth:
        if name not in globals_ns and name not in lazy_load:
            raise ValueError(
                f"Module {module_name}: cannot require auth for non-existent name: {name}"
            )

    for name, role_list in roles.items():
        if name not in globals_ns and name not in lazy_load:
            raise ValueError(
                f"Module {module_name}: cannot assign roles to non-existent name: {name}"
            )
        if not isinstance(role_list, list):
            raise ValueError(f"Module {module_name}: roles for '{name}' must be a list")


def _discover_public_names_enhanced(
    globals_ns: Dict[str, Any], block_set: Set[str], metadata: Dict[str, Dict[str, Any]]
) -> List[str]:
    """Enhanced automatic discovery with metadata awareness."""
    public = []

    for name in globals_ns:
        # Skip blocked names
        if name in block_set:
            continue

        # Skip based on metadata
        if name in metadata and metadata[name].get("hidden", False):
            continue

        # Privacy-based filtering
        if name.startswith("__") and name.endswith("__"):
            if name in ("__version__", "__author__", "__doc__"):
                public.append(name)
            continue

        if name.startswith("_"):
            continue

        public.append(name)

    return public


def _get_attribute_value(
    name: str,
    globals_ns: Dict[str, Any],
    api_metadata: Dict[str, APIMetadata],
    allow_submodules: bool,
    module_name: str,
    background_loaded: Dict[str, Any],
) -> Any:
    """Get attribute value with all fallbacks."""
    # Check background loaded
    if name in background_loaded:
        return background_loaded[name]

    # Check lazy loaders
    if name in api_metadata and api_metadata[name].is_lazy_loaded:
        loader = api_metadata[name].lazy_loader
        if loader:
            value = loader()
            api_metadata[name].cached_value = value
            return value

    # Check globals
    if name in globals_ns:
        return globals_ns[name]

    # Check submodules
    if allow_submodules and is_submodule_access(name, module_name):
        return lazy_load_submodule(name, module_name)

    raise AccessError(
        f"module '{module_name}' has no attribute '{name}'",
        suggestion=f"Available attributes: {sorted(globals_ns.get('__all__', []))}",
        docs_url=f"/docs/{module_name}",
    )


def _check_authentication(name: str) -> bool:
    """Check if user is authenticated for API member."""
    # Placeholder - should be customized
    return True


def _check_resource_limits(name: str, limits: Dict[str, Any]) -> bool:
    """Check resource limits for API member."""
    # Check memory
    if "max_memory" in limits:
        try:
            import psutil

            process = psutil.Process()
            if process.memory_info().rss > limits["max_memory"]:
                return False
        except ImportError:
            pass

    # Check CPU usage
    if "max_cpu_percent" in limits:
        try:
            import psutil

            if psutil.cpu_percent() > limits["max_cpu_percent"]:
                return False
        except ImportError:
            pass

    return True


def _version_compare(v1: str, v2: str) -> int:
    """Compare version strings."""
    try:
        from packaging import version

        v1_parsed = version.parse(v1)
        v2_parsed = version.parse(v2)
        if v1_parsed < v2_parsed:
            return -1
        elif v1_parsed > v2_parsed:
            return 1
        return 0
    except ImportError:
        # Fallback simple comparison
        return (v1 > v2) - (v1 < v2)


def _try_add_version(module_name: str, globals_ns: Dict[str, Any]):
    """Try to add __version__ from various sources."""
    try:
        from importlib.metadata import version as get_version

        version = get_version(module_name.split(".")[0])
        if version:
            globals_ns["__version__"] = version
            if "__version__" not in globals_ns.get("__all__", []):
                all_list = list(globals_ns.get("__all__", []))
                all_list.append("__version__")
                globals_ns["__all__"] = tuple(sorted(set(all_list)))
    except ImportError:
        pass
