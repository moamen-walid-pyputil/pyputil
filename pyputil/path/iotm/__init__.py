#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Dynamic Modules Management System (IOTextModule)
==========================================

A comprehensive, production-ready system for managing Python modules dynamically
with advanced features including AST-based code transformation, secure sandboxing,
hot reloading, hybrid storage strategies, dependency injection, and complete
virtual package management.

Overview
--------
IOTextModule provides a unified framework for creating, managing, and executing Python
modules entirely in memory or with flexible persistence strategies. It enables
dynamic code generation, safe execution of untrusted code, real-time module
updates without state loss, and complete virtual package hierarchies.

Key Features
------------

Core Module Management:
    - AST-Based Code Editing: Parse, analyze, and transform Python code safely
      using Abstract Syntax Tree manipulation with full validation and error recovery
    - Hot Module Reloading: Update module code at runtime without losing module
      state, preserving existing objects and only updating changed functions/classes
    - Hybrid Storage Modes: Choose from multiple storage strategies including
      virtual (RAM-only), persistent (disk-backed), cached, auto-sync, append, and
      read-only modes with cross-platform file handling
    - Dependency Injection: Inject dependencies into modules with IoC container
      support, allowing flexible configuration and testing
    - Module Lifecycle Events: Subscribe to module events (created, loaded,
      executed, modified, saved, reloaded) for monitoring and automation
    - Snapshot & Rollback: Create state snapshots for rollback capabilities,
      enabling safe experimentation and recovery

Secure Sandbox Execution:
    - Multi-Layer Security: AST static analysis, runtime namespace restrictions,
      resource monitoring, and system call interception
    - Configurable Security Levels: Predefined profiles (MINIMAL, STANDARD,
      STRICT, PARANOID) with customizable rule sets for fine-grained control
    - Resource Limiting: CPU time, memory usage, file handles, recursion depth,
      and code size limits with real-time monitoring
    - Module Whitelist/Blacklist: Pattern-based module import permissions with
      support for wildcards, regex patterns, and submodule inheritance
    - Attribute Access Control: Block dangerous attribute access with
      comprehensive filtering of dunder methods and sensitive attributes
    - Audit Logging: Complete execution audit trail with event tracking,
      security violation logging, and performance metrics
    - Cross-Platform Security: Works consistently across Windows, Linux, and
      macOS with platform-specific resource limit enforcement

Virtual Package System:
    - Complete Package Emulation: Full Python package semantics including
      __init__.py execution, __all__ management, and __path__ support
    - Nested Package Hierarchies: Create arbitrarily deep package structures
      with proper namespace handling and relative import resolution
    - Namespace Packages: PEP 420 compatible namespace packages without
      __init__.py files, supporting distributed package development
    - Custom Import Hooks: PEP 302 compliant meta path finders that seamlessly
      integrate virtual packages with Python's import system
    - Circular Import Detection: Automatic detection and reporting of circular
      imports with detailed cycle path information
    - Package Serialization: Export/import package structures to/from disk with
      complete metadata preservation and cross-platform compatibility
    - Dependency Management: Package-level dependency injection and
      configuration with support for optional dependency groups

AST Code Transformation:
    - Safe Code Editing: Modify function and class definitions, add/remove
      imports, insert code blocks with full AST validation
    - Reference Updating: Automatically update all references when renaming
      functions, classes, or variables
    - Decorator Management: Add, remove, or modify decorators with support
      for decorator arguments and chaining
    - Code Metrics: Calculate cyclomatic complexity, maintainability index,
      Halstead volume, and other code quality metrics
    - Diff Generation: Generate unified diffs between original and modified
      code for change tracking and review
    - Import Optimization: Organize, sort, and deduplicate import statements
      with PEP 8 compliance

Module Metadata System:
    - Comprehensive Tracking: Track module version, author, description,
      dependencies, creation/modification timestamps, and content hashes
    - Multi-Algorithm Hashing: SHA256, SHA512, MD5, and BLAKE2b hashing for
      content integrity verification with tamper detection
    - Semantic Versioning: Full semantic version support with major/minor/patch
      bumping and version constraint validation
    - Dependency Specification: Rich dependency specifications with version
      constraints, platform restrictions, Python version requirements, and
      optional dependency grouping
    - Audit Trail: Complete change history with before/after values, timestamps,
      user information, and change reasons
    - JSON Serialization: Import/export metadata to JSON with cross-platform
      path normalization

Architecture
------------
The IOTextModule system is organized into several interconnected modules:

IOTextModule/
├── __init__.py              Main package interface (this file)
├── ast_editor/
│   └── editor.py            AST manipulation and code transformation
├── sandbox/
│   ├── config.py            Security configuration and profiles
│   └── sandbox.py           Secure execution environment
├── core/
│   ├── metadata.py          Module metadata and versioning
│   └── module.py            Core module management (IOTextModuleModule)
└── package/
    └── virtual_package.py   Virtual package and import system

Quick Start Examples
--------------------

Basic Module Management:

    import iotm

    # Create a virtual module (RAM-only)
    module = iotmopen_module("my_dynamic_module")
    module.write('''
    def greet(name):
        return f"Hello, {name}!"

    message = greet("World")
    ''')

    # Execute the module
    module.exec()
    print(module.module.message)  # "Hello, World!"

    # Hot reload with changes
    module.edit_function("greet", '''
    def greet(name):
        return f"Greetings, {name}!"
    ''')
    module.reload_hot()  # Updates without losing state

Sandboxed Execution:

    import iotm

    # Create sandbox with strict security
    config = iotmSandboxConfig.from_profile("strict")
    sandbox = iotmSandbox(config)

    # Execute untrusted code safely
    result = sandbox.execute('''
    import math
    def calculate(x):
        return math.sqrt(x) * 2
    result = calculate(16)
    ''')

    print(result.result)  # 8.0

    # Inject safe objects
    sandbox.inject("data", [1, 2, 3, 4, 5])
    sandbox.execute("average = sum(data) / len(data)")

Virtual Package Creation:

    import iotm

    # Create a complete package hierarchy
    pkg = iotmcreate_package("myapp")

    # Add __init__.py
    pkg.get_init().write('''
    __version__ = "1.0.0"
    __all__ = ["core", "utils"]

    from .core import Application
    ''')

    # Create modules
    core = pkg.create_module("core")
    core.write('''
    class Application:
        def __init__(self):
            self.name = "MyApp"
        
        def run(self):
            return f"{self.name} is running"
    ''')

    utils = pkg.create_module("utils")
    utils.write('''
    def helper():
        return "Utility function"
    ''')

    # Create subpackage
    plugins = pkg.create_subpackage("plugins")
    db_plugin = plugins.create_module("database")

    # Register with import system
    pkg.register_importer()

    # Now can be imported normally
    from myapp.core import Application
    app = Application()
    print(app.run())

AST Code Transformation:

    import iotm

    # Load existing module
    module = iotmopen_module("my_module")

    # Edit function using AST
    module.edit_function("calculate", '''
    def calculate(x, y):
        return (x + y) * 2
    ''')

    # Add import
    module.add_import("functools", "ft")

    # Add decorator
    module.add_decorator("calculate", "@ft.lru_cache(maxsize=128)")

    # Get code metrics
    metrics = module.editor.get_metrics()
    print(f"Cyclomatic complexity: {metrics.cyclomatic_complexity}")

    # Get diff
    diff = module.editor.get_diff()
    print(diff)

Advanced Module Lifecycle:

    import iotm
    from iotm import ModuleStorageMode, ModuleEvent

    # Create module with custom storage
    module = iotmopen_module(
        "live_module",
        storage_mode=ModuleStorageMode.AUTO_SYNC,
        enable_sandbox=False
    )

    # Subscribe to events
    @module.on(ModuleEvent.MODIFIED)
    def on_modified(**kwargs):
        print(f"Module modified: {len(kwargs['new_source'])} bytes")

    @module.on(ModuleEvent.EXECUTED)
    def on_executed(**kwargs):
        print("Module executed successfully")

    # Enable hot reload with file watching
    module.enable_hot_reload(check_interval=1.0)

    # Create snapshot for rollback
    snapshot = module.create_snapshot("Before major changes")

    # Make changes...
    module.write("# New code")

    # Rollback if needed
    module.rollback(snapshot)

Security Profiles
-----------------

IOTextModule provides predefined security profiles for different use cases:

Profile     Imports    File I/O    Network    Subprocess    CPU Time    Memory    Use Case
MINIMAL     All        Yes         Yes        No            30s         500MB     Trusted code, development
STANDARD    Safe       No          No         No            5s          100MB     General purpose, most use cases
STRICT      Limited    No          No         No            2s          50MB      Untrusted code, user submissions
PARANOID    None       No          No         No            1s          10MB      Maximum security, unknown code

    import iotm

    # Use predefined profile
    config = iotmSandboxConfig.from_profile("strict")

    # Custom configuration
    config = iotmSandboxConfig(
        allow_imports=True,
        allowed_modules={"math", "json", "datetime"},
        allow_file_io=False,
        resource_limits=iotmResourceLimits(
            cpu_time_seconds=3.0,
            memory_mb=75
        )
    )

    # Create sandbox with config
    sandbox = iotmSandbox(config)

Module Storage Modes
--------------------

Choose the appropriate storage mode for your use case:

Mode         Description                                           Use Case
VIRTUAL      RAM only, never persisted to disk                     Temporary modules, testing
PERSISTENT   Saved to disk on every write                          Regular module files
CACHED       Saved only when content actually changes              Performance optimization
AUTO_SYNC    Bidirectional sync between RAM and disk               Live development, file watching
APPEND       Append new code to existing file                      Logging, incremental code gen
READONLY     Read-only access, modifications blocked               Protected modules, libraries
LAZY         Load on-demand with caching                           Large module collections

    import iotm
    from iotm import ModuleStorageMode

    # Virtual module (temporary)
    virtual_mod = iotmopen_module("temp", storage_mode=ModuleStorageMode.VIRTUAL)

    # Auto-sync module (live reload)
    live_mod = iotmopen_module("live", storage_mode=ModuleStorageMode.AUTO_SYNC)
    live_mod.enable_hot_reload()

    # Read-only module (protected)
    readonly_mod = iotmopen_module("protected", storage_mode=ModuleStorageMode.READONLY)

Error Handling
--------------

IOTextModule provides specific exception classes for different error conditions:

    from iotm import (
        SandboxViolation,
        SandboxTimeoutError,
        SandboxMemoryError,
        ASTValidationError,
        CircularImportError
    )

    try:
        sandbox.execute(untrusted_code, timeout=5.0)
    except SandboxTimeoutError as e:
        print(f"Code took too long: {e}")
    except SandboxMemoryError as e:
        print(f"Memory limit exceeded: {e}")
    except SandboxViolation as e:
        print(f"Security violation: {e.violation_type} - {e}")

Integration Examples
--------------------

Web Framework Integration (FastAPI):

    from fastapi import FastAPI
    import iotm

    app = FastAPI()
    sandbox = iotmSandbox(config=iotmSTRICT_CONFIG)

    @app.post("/execute")
    async def execute_code(code: str):
        try:
            result = sandbox.execute(code, timeout=2.0)
            return {"success": True, "result": str(result.result)}
        except Exception as e:
            return {"success": False, "error": str(e)}

Plugin System:

    import iotm
    from iotm import ModuleStorageMode

    class PluginManager:
        def __init__(self):
            self.plugins = {}
            self.pkg = iotmcreate_package("plugins")
            self.pkg.register_importer()
        
        def load_plugin(self, name: str, code: str):
            module = self.pkg.create_module(name)
            module.write(code)
            module.exec()
            module.enable_hot_reload()
            self.plugins[name] = module
            return module.module
        
        def reload_plugin(self, name: str):
            if name in self.plugins:
                self.plugins[name].reload_hot()

Testing Utilities:

    import iotm

    def create_test_module(code: str):
        module = iotmcreate_virtual_module(
            f"test_{hash(code) % 10000}",
            code=code
        )
        module.exec()
        return module

    # Use in tests
    def test_function():
        mod = create_test_module("def add(a, b): return a + b")
        assert mod.module.add(2, 3) == 5

Cross-Platform Support
----------------------

IOTextModule is fully cross-platform and tested on:
    - Linux: Full resource limit support via resource module
    - macOS: Darwin-specific resource handling
    - Windows: Fallback mechanisms where platform APIs differ

Path handling is normalized across platforms using pathlib and proper
encoding detection (UTF-8, UTF-8-SIG, Latin-1, CP1252).

Version Compatibility
---------------------

    - Python 3.8+: Full support
    - Python 3.7: Limited support (some AST features unavailable)
    - PyPy: Compatible with PyPy 7.3+

Dependencies
------------

Core dependencies (minimal installation):
    - None (pure Python standard library)

Optional dependencies for enhanced features:
    - psutil: Advanced resource monitoring (recommended)
    - watchdog: Efficient file watching for hot reload

License
-------

MIT License - See LICENSE file for details

API Reference
-------------
"""

# Project information
__copyright__ = "Copyright 2024 IOTextModule Contributors"

# Core module imports
from .core.module import (
    IOTextModule,
    ModuleStorageMode,
    ModuleState,
    ModuleEvent,
    ModuleSnapshot,
    open_module,
    create_virtual_module,
    load_module_from_file
)

# Metadata imports
from .core.metadata import (
    ModuleMetadata,
    DependencySpec,
    ContentHash,
    AuditEntry,
    VersionScheme,
    DependencyType,
    IntegrityStatus
)

# Package imports
from .package.virtual_package import (
    VirtualPackage,
    PackageConfig,
    PackageType,
    ImportMode,
    PackageEvent,
    ImportRecord,
    CircularImportError,
    VirtualImporter,
    create_package,
    create_namespace_package,
    get_package,
    list_packages
)

# Sandbox imports
from .sandbox.sandbox import (
    Sandbox,
    SandboxConfig,
    SecurityLevel,
    ResourceLimits,
    SandboxViolation,
    SandboxTimeoutError,
    SandboxMemoryError,
    SandboxResourceError,
    ExecutionResult,
    ExecutionEvent,
    ExecutionEventType,
    SecureProxy,
    RestrictedNamespace,
    ResourceMonitor,
    ASTSecurityValidator,
    create_math_sandbox,
    create_data_sandbox,
    create_test_sandbox
)

# AST Editor imports
from .ast_editor.editor import (
    ASTEditor,
    ASTBatchEditor,
    ASTValidationError,
    ASTOperationError,
    ValidationSeverity,
    OperationType,
    ValidationResult,
    OperationLog,
    CodeMetrics
)

# Configuration presets
from .sandbox.config import (
    DEFAULT_CONFIG,
    STRICT_CONFIG,
    PARANOID_CONFIG,
    MINIMAL_CONFIG
)

# Utility functions
from .ast_editor.editor import (
    normalize_import_path,
    get_ast_diff,
    is_valid_python_code
)


# Public API - Core
__all__ = [    
	# Project info 
	'__copyright__',

    # Core Module Management
    'IOTextModule',
    'ModuleStorageMode',
    'ModuleState',
    'ModuleEvent',
    'ModuleSnapshot',
    'open_module',
    'create_virtual_module',
    'load_module_from_file',
    
    # Module Metadata
    'ModuleMetadata',
    'DependencySpec',
    'ContentHash',
    'AuditEntry',
    'VersionScheme',
    'DependencyType',
    'IntegrityStatus',
    
    # Virtual Package System
    'VirtualPackage',
    'PackageConfig',
    'PackageType',
    'ImportMode',
    'PackageEvent',
    'ImportRecord',
    'CircularImportError',
    'VirtualImporter',
    'create_package',
    'create_namespace_package',
    'get_package',
    'list_packages',
    
    # Sandbox Security
    'Sandbox',
    'SandboxConfig',
    'SecurityLevel',
    'ResourceLimits',
    'SandboxViolation',
    'SandboxTimeoutError',
    'SandboxMemoryError',
    'SandboxResourceError',
    'ExecutionResult',
    'ExecutionEvent',
    'ExecutionEventType',
    'SecureProxy',
    'RestrictedNamespace',
    'ResourceMonitor',
    'ASTSecurityValidator',
    'create_math_sandbox',
    'create_data_sandbox',
    'create_test_sandbox',
    
    # AST Editor
    'ASTEditor',
    'ASTBatchEditor',
    'ASTValidationError',
    'ASTOperationError',
    'ValidationSeverity',
    'OperationType',
    'ValidationResult',
    'OperationLog',
    'CodeMetrics',
    
    # Configuration Presets
    'DEFAULT_CONFIG',
    'STRICT_CONFIG',
    'PARANOID_CONFIG',
    'MINIMAL_CONFIG',
    
    # Utilities
    'normalize_import_path',
    'get_ast_diff',
    'is_valid_python_code',
]


# Lazy loading for optional dependencies
def _check_optional_dependencies():
    optional_deps = {}
    
    try:
        import psutil
        optional_deps['psutil'] = True
    except ImportError:
        optional_deps['psutil'] = False
    
    try:
        import watchdog
        optional_deps['watchdog'] = True
    except ImportError:
        optional_deps['watchdog'] = False
    
    return optional_deps


# Module initialization
_optional_deps = _check_optional_dependencies()

if not _optional_deps['psutil']:
    import warnings
    warnings.warn(
        "psutil not installed. Resource monitoring will use fallback methods. "
        "Install with: pip install psutil",
        ImportWarning,
        stacklevel=2
    )

if not _optional_deps['watchdog']:
    import warnings
    warnings.warn(
        "watchdog not installed. File watching will use polling fallback. "
        "Install with: pip install watchdog",
        ImportWarning,
        stacklevel=2
    )


def quick_start():
    """
    Launch an interactive quick start guide.
    
    This function provides an interactive tutorial covering the main
    features of `iotm`
    
    Examples
    --------
    >>> import iotm
    >>> iotm.quick_start()  # Launches interactive tutorial
    """
    print("=" * 70)
    print("IOTextModule Quick Start Guide")
    print("=" * 70)
    print()
    print("1. Creating a Virtual Module:")
    print("   >>> from pyputil.path import iotm")
    print("   >>> mod = iotm.open_module('hello')")
    print("   >>> mod.write('def greet(): return \"Hello!\"')")
    print("   >>> mod.exec()")
    print()
    print("2. Sandboxed Execution:")
    print("   >>> sandbox = iotm.Sandbox(iotm.STRICT_CONFIG)")
    print("   >>> result = sandbox.execute('print(\"Safe!\")')")
    print()
    print("3. Virtual Package:")
    print("   >>> pkg = iotm.create_package('myapp')")
    print("   >>> pkg.register_importer()")
    print("   >>> import myapp  # Works normally!")
    print()
    print("4. Hot Reload:")
    print("   >>> mod.enable_hot_reload()")
    print("   >>> # Edit file externally, module auto-updates")
    print()


# Cleanup namespace
from ...api import clean
all_list = __all__ + ["quick_start", "__doc__"]
clean(expose=all_list)