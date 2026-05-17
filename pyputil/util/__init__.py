#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
PyPUtil Util - Comprehensive Python Utility Library
===============================================

A production-grade collection of Python utilities for advanced package management,
import system manipulation, module inspection, and development workflows.
This library provides a unified interface to powerful tools for working with
Python packages, modules, imports, and environments.

Modules Overview
----------------
- importable: Deep package inspection and importable symbol discovery
- registers: Dynamic module registration and submodule management
- init: Package structure initialization and utilities
- copyist: Advanced module cloning with access control and lazy loading
- deep_dir: Recursive package inspection with advanced filtering
- import_cleaner: Import analysis, cleanup, and unused import detection
- all_list: Automatic __all__ generation and validation

Features
--------
Importable Symbol Discovery
    - Deep recursive inspection of package hierarchies
    - Extract all importable symbols (classes, functions, variables)
    - Namespace package support (PEP 420) and type stub support (PEP 561)
    - Advanced filtering by type and regex patterns
    - Check if modules or files are importable

Module Registration
    - Manual module registration in sys.modules
    - Submodule registration with parent package creation
    - Namespace package registration (PEP 420)
    - Dynamic module creation from dicts, files, or factories
    - Lazy-loading proxy modules and import hooks

Package Initialization
    - Read __init__.py contents from any package
    - Clean package directories (remove __pycache__)
    - Auto-generate missing __init__.py files
    - Cross-platform path handling

Module Cloning
    - Create controlled, sandboxed views of Python modules
    - Fine-grained access control (allow/deny lists)
    - Lazy attribute loading and module immutability
    - Deep recursive cloning with statistics tracking

Deep Directory Inspection
    - Recursive package exploration with depth control
    - Type-based filtering and regex pattern matching
    - Metadata collection and result analysis
    - Statistics and summary generation

Import Cleaner
    - Detect unused imports with advanced AST analysis
    - Type annotation import detection (PEP 484, PEP 563)
    - Safe import removal with formatting preservation
    - Module name normalization and path conversion

__all__ Generation
    - Automatic __all__ list generation from source files
    - Package-wide __all__ generation and updates
    - Validation with multiple strictness levels
    - Smart update modes with backup creation

Quick Examples
--------------
    # Importable discovery
    from pyputil.util import importables, importable, get_public_api
    funcs = importables("numpy", filter_by="function", pattern="array")
    print(importable("requests"))  # True

    # Module registration
    from pyputil.util import register, create_module
    mod = create_module("my_module", {"VERSION": "1.0.0"})
    register(mod)

    # Package initialization
    from pyputil.util import init, init_package
    content = init("requests")
    init_package("my_package")

    # Module cloning
    from pyputil.util import clone_module
    import math
    public_math = clone_module(math, public_only=True, frozen=True)

    # Deep inspection
    from pyputil.util import deep_dir
    result = deep_dir("numpy", max_depth=2)
    print(result.summary())

    # Import cleaning
    from pyputil.util import clean_file_imports, detect_unused_imports
    unused = detect_unused_imports("my_module.py")

    # __all__ generation
    from pyputil.util import make_all_list, validate_all_list
    __all__ = make_all_list(__file__)

For detailed help, use pyputil.util.help() or pyputil.util.help_topic("topic").
Available topics: importable, register, init, clone, deep_dir,
import_cleaner, all_list, all
"""

import sys
import os
from typing import Optional, Dict, Any, List, Union

# ============================================================================
# Imports from importable module
# ============================================================================

from .importable import (
    importable,
    importables,
    SymbolType,
    InspectionMode,
    FilterMode,
    SymbolInfo,
    ModuleInfo,
    InspectionResult,
    get_public_api,
    get_classes,
    get_functions,
    get_variables,
    search_package,
    get_module_imports,
    clear_cache as clear_importables_cache,
    get_cache_stats as get_importables_cache_stats,
)

# ============================================================================
# Imports from registers module
# ============================================================================

from .registers import (
    register,
    register_as_submodule,
    RegistrationMode,
    ModuleSource,
    ConflictResolution,
    RegistrationInfo,
    RegistrationResult,
    validate_module_name,
    normalize_module_name,
    create_module,
    create_module_from_file,
    create_module_from_dict,
    create_namespace_module,
    create_proxy_module,
    register_many,
    register_namespace,
    register_from_file,
    unregister,
    unregister_many,
    reload_module,
    is_registered,
    get_registered_module,
    list_registered_modules,
    register_function,
    register_value,
    register_alias,
    get_registration_history,
    clear_registration_history,
    install_dynamic_importer,
)

# ============================================================================
# Imports from init module
# ============================================================================

from .init import (
    init,
    init_package,
    get_package_parent,
    has_init,
    get_init_path,
    create_init,
)

# ============================================================================
# Imports from copyist module
# ============================================================================

from .copyist import (
    clone_module,
    ModuleClone,
    CloneMode,
    AccessPolicy,
    CloneEvent,
    CloneStatistics,
    CloneConfig,
    ModuleCloneError,
    FrozenModuleError,
    AccessDeniedError,
    LazyLoadError,
    CircularReferenceError,
    clone_module_deep,
    clone_module_public,
    clone_module_restricted,
    clone_module_lazy,
    is_module_clone,
    get_origin_module,
    unwrap_clone,
)

# ============================================================================
# Imports from deep_dir module
# ============================================================================

from .deep_dir import (
    deep_dir,
    DeepDirResult,
    ItemType,
    InspectionStatistics,
    ItemMetadata,
    quick_dir,
    find_in_package,
    list_submodules,
    clear_cache as clear_deep_dir_cache,
    get_cache_stats as get_deep_dir_cache_stats,
)

# ============================================================================
# Imports from import_cleaner module
# ============================================================================

from .import_cleaner import (
    ImportDetector,
    AnalysisConfig,
    ImportRecord,
    AnalysisReport,
    CleanupResult,
    ImportCategory,
    UsageContext,
    AnalysisDepth,
    CleanupMode,
    analyze_file,
    analyze_source,
    clean_file,
    clean_directory,
    detect_unused_imports,
    ImportAnalysisError,
    InvalidSourceError,
    FileAccessError,
)
 

# ============================================================================
# Imports from all_list module
# ============================================================================

from .all_list import (
    make_all_list,
    make_package_all_list,
    update_package_all,
    validate_all_list,
    analyze_module,
    ExportType,
    ValidationLevel,
    UpdateMode,
    GenerationConfig,
    get_public_api as get_module_public_api,
    get_all_exports,
    check_missing_all,
    check_extra_all,
    fix_all,
)

# ============================================================================
# Help System
# ============================================================================

def help_topic(topic: Optional[str] = None) -> None:
    """
    Display detailed help about PyPUtil features and modules.

    Parameters
    ----------
    topic : str, optional
        Specific topic to get help on. Available topics:
        - 'importable': Importable symbol discovery
        - 'register': Module registration
        - 'init': Package initialization
        - 'clone': Module cloning and sandboxing
        - 'deep_dir': Deep directory inspection
        - 'import_cleaner': Import analysis and cleanup
        - 'all_list': __all__ generation
        - 'all' or None: General overview

    Examples
    --------
    >>> import pyputil
    >>> pyputil.help_topic()
    >>> pyputil.help_topic("clone")
    >>> pyputil.help_topic("all")
    """
    topics = {
        "importable": """
Importable Symbol Discovery
===========================
Functions for discovering importable symbols in Python packages.

Main Functions:
    importables(package_name, filter_by=None, pattern=None, ...)
        Get all importable symbols from a package.
    
    importable(target)
        Check if a module name or file is importable.
    
    get_public_api(package_name)
        Get the public API of a package.
    
    get_classes(package_name), get_functions(package_name)
        Get specific symbol types.

Examples:
    >>> from pyputil.util import importables, importable
    >>> funcs = importables("numpy", filter_by="function", pattern="array")
    >>> print(f"Found {len(funcs)} array functions")
    >>> importable("requests")  # True
    >>> importable("/path/to/module.py")  # True if valid syntax
""",

        "register": """
Module Registration
===================
Functions for dynamically registering modules in sys.modules.

Main Functions:
    register(module, name=None, mode='strict', ...)
        Register a module in sys.modules.
    
    register_as_submodule(parent, module, submodule_name, ...)
        Register a module as a submodule.
    
    create_module(name, attributes=None, ...)
        Create a new module with attributes.
    
    unregister(name), is_registered(name)
        Manage registered modules.

Examples:
    >>> from pyputil.util import register, create_module
    >>> mod = create_module("my_mod", {"VERSION": "1.0"})
    >>> register(mod)
    >>> import my_mod
    >>> print(my_mod.VERSION)  # 1.0
    
    >>> utils = create_module("utils", {"helper": lambda x: x * 2})
    >>> register_as_submodule("my_package", utils, "utils")
""",

        "init": """
Package Initialization
======================
Utilities for working with __init__.py files and package directories.

Main Functions:
    init(module)
        Read __init__.py contents from a package.
    
    init_package(pkg_name, clean_cache=True, create_missing=True)
        Clean and prepare a package directory.
    
    create_init(directory, content="", exist_ok=True)
        Create an __init__.py file.
    
    has_init(module), get_init_path(module)
        Check for __init__.py existence and location.

Examples:
    >>> from pyputil.util import init, init_package, create_init
    >>> content = init("requests")
    >>> init_package("my_package")
    >>> create_init("./my_package/subdir", content='__version__ = "1.0.0"')
""",

        "clone": """
Module Cloning
==============
Create controlled, sandboxed views of Python modules.

Main Functions:
    clone_module(module, mode='shallow', access_policy='allow_all', ...)
        Advanced module cloning with full configuration.
    
    clone_module_deep(module), clone_module_public(module)
        Convenience functions for common cloning patterns.
    
    is_module_clone(obj), get_origin_module(obj)
        Introspection utilities.

Clone Modes:
    SHALLOW  - Only wrap the module
    DEEP     - Recursively clone submodules
    LAZY     - Clone submodules on first access
    REFERENCE - Keep references to original

Access Policies:
    ALLOW_ALL   - Allow all attributes
    ALLOW_LIST  - Only allow listed attributes
    DENY_LIST   - Allow all except denied
    PUBLIC_ONLY - Only public attributes

Examples:
    >>> from pyputil.util import clone_module
    >>> import math    
    >>> restricted = clone_module(
    ...     math,
    ...     access_policy="allow_list",
    ...     allowed={'sqrt', 'pi'},
    ...     frozen=True
    ... )
""",

        "deep_dir": """
Deep Directory Inspection
=========================
Recursively explore Python packages with advanced filtering.

Main Functions:
    deep_dir(package_name, public_only=True, max_depth=None, ...)
        Deep recursive inspection of a package.
    
    quick_dir(package_name, max_depth=1)
        Quick inspection with sensible defaults.
    
    find_in_package(package_name, pattern)
        Search for items matching a pattern.
    
    list_submodules(package_name)
        List all submodules of a package.

DeepDirResult Methods:
    filter(pattern)   - Filter by regex
    search(term)      - Search by term
    by_type(*types)   - Select specific types
    public_only()     - Get only public items
    summary()         - Human-readable summary

Examples:
    >>> from pyputil.util import deep_dir
    >>> result = deep_dir("numpy", max_depth=2)
    >>> print(result.summary())
    >>> array_items = result.search("array")
    >>> classes = result.by_type("classes")
    >>> print(f"Found {len(classes)} classes")
""",

        "import_cleaner": """
Import Cleaner
===============
Detect and remove unused imports with AST analysis.

Main Functions:
    detect_unused_imports(file_path, safe_mode=True)
        Detect unused imports in a file.
    
    clean_file_imports(file_path)
        Remove unused imports from a file.
    
    analyze_imports(file_path)
        Comprehensive import analysis with metadata.
    
    identify_module_name(name)
        Normalize a string to a valid Python module name.
    
    path_to_importable_name(path)
        Convert filesystem path to Python import path.

Examples:
    >>> from pyputil.util import detect_unused_imports, clean_file_imports
    >>> unused = detect_unused_imports("my_module.py")
    >>> print(f"Unused: {unused}")
    >>> clean_file_imports("my_module.py")
    
    >>> from pyputil.util import identify_module_name, path_to_importable_name
    >>> identify_module_name("My Cool Module!")  # 'my_cool_module'
    >>> path_to_importable_name("src/my_package/module.py")  # 'src.my_package.module'
""",

        "all_list": """
__all__ Generation
==================
Automatically generate, validate, and update __all__ lists.

Main Functions:
    make_all_list(path=None, include_private=False, ...)
        Generate __all__ for a single module.
    
    make_package_all_list(package_path, recursive=True, ...)
        Generate __all__ for an entire package.
    
    validate_all_list(path, level='strict')
        Validate existing __all__ against module contents.
    
    update_package_all(package_path, mode='smart', backup=True)
        Update __all__ in package files.
    
    fix_all(path, backup=True)
        Fix __all__ in a single file.

Validation Levels:
    BASIC    - Check only for missing public names
    STRICT   - Also check for extra names
    COMPLETE - Check all aspects including duplicates

Update Modes:
    REPLACE - Replace existing completely
    MERGE   - Merge with existing
    APPEND  - Only add missing names
    SMART   - Intelligent merge preserving manual additions

Examples:
    >>> from pyputil.util import make_all_list, validate_all_list, fix_all
    >>> __all__ = make_all_list(__file__)
    >>> result = validate_all_list("mymodule.py")
    >>> if not result['valid']:
    ...     print(f"Missing: {result['missing']}")
    >>> fix_all("mymodule.py", backup=True)
""",
    }

    if topic is None or topic.lower() == "all":
        print(__doc__)
        print("\n" + "=" * 80)
        print("AVAILABLE HELP TOPICS")
        print("=" * 80)
        print("\nUse pyputil.help_topic('topic') for detailed information.\n")
        for name, desc in [
            ("importable", "Importable symbol discovery"),
            ("register", "Module registration system"),
            ("init", "Package initialization utilities"),
            ("clone", "Module cloning and sandboxing"),
            ("deep_dir", "Deep directory inspection"),
            ("import_cleaner", "Import analysis and cleanup"),
            ("all_list", "__all__ generation and validation"),
        ]:
            print(f"  {name:20} - {desc}")
        print("\n" + "=" * 80)
    elif topic.lower() in topics:
        print(topics[topic.lower()])
    else:
        available = ", ".join(topics.keys())
        print(f"Unknown topic: '{topic}'")
        print(f"Available topics: {available}")


def help() -> None:
    """
    Display general help for the PyPUtil package.

    This function prints an overview of the package, available modules,
    and common usage examples.

    Examples
    --------
    >>> import pyputil
    >>> pyputil.help()
    """
    help_topic("all")


def list_functions() -> Dict[str, List[str]]:
    """
    List all available functions grouped by module.

    Returns
    -------
    Dict[str, List[str]]
        Dictionary mapping module names to lists of function names.

    Examples
    --------
    >>> from pyputil.util import list_functions
    >>> funcs = list_functions()
    >>> print(funcs['importable'])
    ['importable', 'importables', 'get_public_api', ...]
    """
    return {
        "importable": [
            "importable", "importables", "get_public_api", "get_classes",
            "get_functions", "get_variables", "search_package", "get_module_imports",
            "clear_importables_cache", "get_importables_cache_stats",
        ],
        "registers": [
            "register", "register_as_submodule", "create_module",
            "create_module_from_file", "create_module_from_dict",
            "create_namespace_module", "create_proxy_module", "register_many",
            "register_namespace", "register_from_file", "unregister",
            "unregister_many", "reload_module", "is_registered",
            "get_registered_module", "list_registered_modules",
            "register_function", "register_value", "register_alias",
            "validate_module_name", "normalize_module_name",
            "get_registration_history", "clear_registration_history",
            "install_dynamic_importer",
        ],
        "init": [
            "init", "init_package", "get_package_parent", "has_init",
            "get_init_path", "create_init",
        ],
        "clone": [
            "copy", "clone_module", "clone_module_deep", "clone_module_public",
            "clone_module_restricted", "clone_module_lazy", "is_module_clone",
            "get_origin_module", "unwrap_clone",
        ],
        "deep_dir": [
            "deep_dir", "quick_dir", "find_in_package", "list_submodules",
            "clear_deep_dir_cache", "get_deep_dir_cache_stats",
        ],
        "import_cleaner": [
            "clean_file_imports", "remove_unused_imports", "detect_unused_imports",
            "identify_module_name", "path_to_importable_name", "analyze_imports",
            "clean_imports", "path_to_import_name", "is_stdlib_import",
            "is_third_party_import", "get_import_names", "get_import_statistics",
            "normalize_import_name",
        ],
        "all_list": [
            "make_all_list", "make_package_all_list", "update_package_all",
            "validate_all_list", "analyze_module", "get_module_public_api",
            "get_all_exports", "check_missing_all", "check_extra_all", "fix_all",
        ],
    }


def clear_all_caches() -> None:
    """
    Clear all internal caches across all modules.

    This function clears caches from importable, deep_dir, and other
    modules that maintain internal caches for performance.

    Examples
    --------
    >>> from pyputil.util import clear_all_caches
    >>> clear_all_caches()
    """
    try:
        clear_importables_cache()
    except NameError:
        pass
    
    try:
        clear_deep_dir_cache()
    except NameError:
        pass


def get_cache_info() -> Dict[str, Any]:
    """
    Get cache statistics from all modules.

    Returns
    -------
    Dict[str, Any]
        Cache statistics from all modules that maintain caches.

    Examples
    --------
    >>> from pyputil.util import get_cache_info
    >>> info = get_cache_info()
    >>> print(info)
    """
    result = {}
    
    try:
        result["importables"] = get_importables_cache_stats()
    except NameError:
        pass
    
    try:
        result["deep_dir"] = get_deep_dir_cache_stats()
    except NameError:
        pass
    
    return result


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    # Help and Info
    "help",
    "help_topic",
    "list_functions",
    "clear_all_caches",
    "get_cache_info",
    
    # Importable Module
    "importable",
    "importables",
    "SymbolType",
    "InspectionMode",
    "FilterMode",
    "SymbolInfo",
    "ModuleInfo",
    "InspectionResult",
    "get_public_api",
    "get_classes",
    "get_functions",
    "get_variables",
    "search_package",
    "get_module_imports",
    "clear_importables_cache",
    "get_importables_cache_stats",
    
    # Registers Module
    "register",
    "register_as_submodule",
    "RegistrationMode",
    "ModuleSource",
    "ConflictResolution",
    "RegistrationInfo",
    "RegistrationResult",
    "validate_module_name",
    "normalize_module_name",
    "create_module",
    "create_module_from_file",
    "create_module_from_dict",
    "create_namespace_module",
    "create_proxy_module",
    "register_many",
    "register_namespace",
    "register_from_file",
    "unregister",
    "unregister_many",
    "reload_module",
    "is_registered",
    "get_registered_module",
    "list_registered_modules",
    "register_function",
    "register_value",
    "register_alias",
    "get_registration_history",
    "clear_registration_history",
    "install_dynamic_importer",
    
    # Init Module
    "init",
    "init_package",
    "get_package_parent",
    "has_init",
    "get_init_path",
    "create_init",
    
    # Copyist Module
    "clone_module",
    "ModuleClone",
    "CloneMode",
    "AccessPolicy",
    "CloneEvent",
    "CloneStatistics",
    "CloneConfig",
    "ModuleCloneError",
    "FrozenModuleError",
    "AccessDeniedError",
    "LazyLoadError",
    "CircularReferenceError",
    "clone_module_deep",
    "clone_module_public",
    "clone_module_restricted",
    "clone_module_lazy",
    "is_module_clone",
    "get_origin_module",
    "unwrap_clone",
    
    # Deep_dir Module
    "deep_dir",
    "DeepDirResult",
    "ItemType",
    "InspectionStatistics",
    "ItemMetadata",
    "quick_dir",
    "find_in_package",
    "list_submodules",
    "clear_deep_dir_cache",
    "get_deep_dir_cache_stats",
    
    # Import_cleaner Module
    "ImportDetector",
    "AnalysisConfig",
    "ImportRecord",
    "AnalysisReport",
    "CleanupResult",
    "ImportCategory",
    "UsageContext",
    "AnalysisDepth",
    "CleanupMode",
    "analyze_file",
    "analyze_source",
    "clean_file",
    "clean_directory",
    "detect_unused_imports",
    "ImportAnalysisError",
    "InvalidSourceError",
    "FileAccessError",
    
    # All_list Module
    "make_all_list",
    "make_package_all_list",
    "update_package_all",
    "validate_all_list",
    "analyze_module",
    "ExportType",
    "ValidationLevel",
    "UpdateMode",
    "GenerationConfig",
    "get_module_public_api",
    "get_all_exports",
    "check_missing_all",
    "check_extra_all",
    "fix_all",
]

# ============================================================================
# Aliases for backward compatibility and convenience
# ============================================================================

detect_imports = detect_unused_imports
generate_all = make_all_list
validate_all = validate_all_list

# ============================================================================
# Cleanup namespace
# ============================================================================
def __dir__() -> List[str]:
	"""Retrieve the important values from this package by `__all__` list"""
	return __all__

# ============================================================================
# Interactive Console Help
# ============================================================================

if __name__ == "__main__":
    help()