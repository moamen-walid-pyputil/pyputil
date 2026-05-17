#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
PypUtil Loader System
====================

Overview
--------
A loading system designed to handle Python modules,

Modules
-------

1. Builder
   -------
   Builds and manages a file cache for any given module **path**.
   Useful for speeding up repeated loads and avoiding redundant operations.

2. Caller
   ------
   Allows direct invocation of any object (functions, classes, variables)
   from any loaded module without manual imports.

3. DataLoader
   ------
   A generic file loading system that supports non-Python files, including:
   - .json
   - .csv
   - .xml
   - .txt
   - .yaml
   - .ini

4. LoaderCache
   -----------
   A caching mechanism inspired by `sys.modules`,
   responsible for tracking and reusing loaded modules and resources.

5. PyLoad
   ------
   A high-level Python loader capable of:
   - Loading multiple `.py` files
   - Loading a single Python file from any path
   - Loading Python code directly from a URL
   - Creating modules from raw source code

6. Reloader
   --------
   A module reloading system that can:
   - Reload an entire package
   - Reload a specific module file
   - Reload currently loaded modules dynamically

7. CustomLoader
   --------
   A module for creating and adding custom loaders:
   CustomLoader: creates and executes modules.
   CustomFinder: for custom module loading.
   AddLoader: main class that adds custom loaders.

And more...
"""

from .Builder import (
    cache_module, 
    build, build_frame, 
    warmup_cache, 
    get_cache_info, 
    clear_cache, 
    BuildCache
)
from .DataLoader import (
    load_json,
    load_xml,
    load_ini,
    load_csv,
    load_yaml,
    load_text,
    to_module as path_to_module,
    to_modules as paths_to_modules,
    watch_module as data_watch_module,
    scan_dir as data_scan_dir,
    FileModule as DataFileModule
)
from .LoaderCache import (
    WeakRefSupport as CacheWeakRefSupport,
    ModuleCache,
    ModulesProxy
)
from .PyLoad import (
    load_modules,
    load_from_file,
    unload,
    load_from_source,
    load_from_code,
    load_from_url,
    loads_from_dir
)
from .Reloader import (
    ReloadError,
    ModuleNotFoundError,
    ReloadDependencyError,
    reload_module,
    reload_name,
    reload_package,
    safe_reload,
    reload_matching,
    reload_current_module,
    get_reloadable_modules,
    clear_reload_cache,
    reload,
    reload_all,
    reload_by_file
)
from .CustomLoader import (
    CustomLoader,
    CustomLoaderConfig,
    CustomLoaderPriority,
    CustomModuleHook,
    CustomFinder,
    AddCustomLoader,
    add_custom_loader
)
from .Caller import (
    CallerError,
    TargetNotFoundError,
    CallTimeoutError,
    InvalidTargetError,
    Caller
)
from .LazyLoader import (
    LazyLoader,
    lazy_load
)
from .loader_util import (
    find_loader,
    get_loader,
)


exceptions = (
    ReloadError,
    ModuleNotFoundError,
    ReloadDependencyError,
    CallerError,
    TargetNotFoundError,
    CallTimeoutError,
    InvalidTargetError
)


__all__ = [
    # Builder
    "cache_module",
    "build",
    "build_frame",
    "warmup_cache",
    "get_cache_info",
    "clear_cache",
    "BuildCache",

    # DataLoader
    "load_json",
    "load_xml",
    "load_ini",
    "load_csv",
    "load_yaml",
    "load_text",
    "path_to_module",
    "paths_to_modules",
    "data_watch_module",
    "data_scan_dir",
    "DataFileModule",

    # LoaderCache
    "CacheWeakRefSupport",
    "ModuleCache",
    "ModulesProxy",

    # PyLoad
    "load_modules",
    "load_from_file",
    "unload",
    "load_from_source",
    "load_from_code",
    "load_from_url",
    "loads_from_dir",

    # Reloader
    "ReloadError",
    "ModuleNotFoundError",
    "ReloadDependencyError",
    "reload_module",
    "reload_name",
    "reload_package",
    "safe_reload",
    "reload_matching",
    "reload_current_module",
    "get_reloadable_modules",
    "clear_reload_cache",
    "reload",
    "reload_all",
    "reload_by_file",

    # CustomLoader
    "CustomLoader",
    "CustomLoaderConfig",
    "CustomLoaderPriority",
    "CustomModuleHook",
    "CustomFinder",
    "AddCustomLoader",
    "add_custom_loader",

    # Caller
    "CallerError",
    "TargetNotFoundError",
    "CallTimeoutError",
    "InvalidTargetError",
    "Caller",
    
    # loader_util
    "find_loader",
    "get_loader",

    # LazyLoader
    "LazyLoader",
    "lazy_load",

    # Extras
    "exceptions",
]


from ..api import clean
clean(expose=__all__)
