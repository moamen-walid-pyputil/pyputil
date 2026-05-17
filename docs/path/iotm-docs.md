# IOTextModule - Dynamic Python Module Management System

## Overview

IOTextModule is a comprehensive, production-grade system for managing Python modules dynamically with advanced features including AST-based code transformation, secure sandboxing, hot reloading, hybrid storage strategies, dependency injection, and complete virtual package management.

## Architecture

The system consists of the following core modules:

| Module | Purpose |
|--------|---------|
| `ast_editor/editor.py` | AST manipulation and code transformation |
| `sandbox/config.py` | Security configuration and profiles |
| `sandbox/sandbox.py` | Secure execution environment |
| `core/metadata.py` | Module metadata and versioning |
| `core/module.py` | Core module management (IOTextModule) |
| `package/virtual_package.py` | Virtual package and import system |

---

## 1. Core Module Management (`core/module.py`)

### What It Does

Provides comprehensive interface for managing Python modules with support for virtual modules, file-backed modules, sandboxed execution, dependency injection, hot reloading, and cross-platform compatibility.

### Why Use It

- **Dynamic Code Generation**: Create and modify modules at runtime
- **Hot Reloading**: Update module code without losing state
- **Multiple Storage Strategies**: RAM-only, disk-backed, cached, auto-sync
- **Dependency Injection**: Inject dependencies into modules

### Key Classes

```python
from iotm import (
    IOTextModule, ModuleStorageMode, ModuleState, ModuleEvent,
    open_module, create_virtual_module, load_module_from_file
)
```

Usage Examples

```python
from iotm import open_module, create_virtual_module, ModuleStorageMode

# Create a virtual module (RAM-only)
mod = open_module("my_dynamic_module")
mod.write('''
def greet(name):
    return f"Hello, {name}!"

message = greet("World")
''')
mod.exec()
print(mod.module.message)  # "Hello, World!"

# Create virtual module with initial code
mod = create_virtual_module("calculator", code='''
def add(a, b): return a + b
def multiply(a, b): return a * b
''')
mod.exec()
print(mod.module.add(5, 3))  # 8

# Load from file
mod = load_module_from_file("/path/to/module.py")
mod.exec()

# Hot reload with state preservation
mod.edit_function("greet", '''
def greet(name):
    return f"Greetings, {name}!
''')
mod.reload_hot()  # Updates without losing state

# Enable automatic hot reload
mod.enable_hot_reload(check_interval=1.0)
# Edit file externally, module auto-updates

# Storage modes
mod = open_module("persistent", storage_mode=ModuleStorageMode.PERSISTENT)
mod = open_module("cached", storage_mode=ModuleStorageMode.CACHED)
mod = open_module("auto_sync", storage_mode=ModuleStorageMode.AUTO_SYNC)

# Events
@mod.on(ModuleEvent.EXECUTED)
def on_executed(**kwargs):
    print("Module executed!")

# Snapshots
snapshot = mod.create_snapshot("Before changes")
mod.write("# New code")
mod.rollback(snapshot)  # Restored

# Dependency injection
mod.inject({"db": database_connection, "config": app_config})
mod.exec()  # Uses injected dependencies

# Get functions/classes
print(mod.get_functions())  # ['greet']
print(mod.get_classes())    # []

# Code metrics
metrics = mod.get_metrics()
print(f"Cyclomatic complexity: {metrics.cyclomatic_complexity}")
```

---

2. Module Metadata (core/metadata.py)

What It Does

Provides comprehensive metadata tracking for Python modules including versioning, dependency resolution, cryptographic verification, and audit logging.

Why Use It

· Integrity Verification: Detect tampering with cryptographic hashes
· Dependency Management: Track and validate dependencies
· Version Control: Semantic versioning support
· Audit Trail: Complete change history

Key Classes

```python
from iotm import ModuleMetadata, DependencySpec, ContentHash, VersionScheme
```

Usage Examples

```python
from iotm import ModuleMetadata, DependencyType

# Create metadata
meta = ModuleMetadata("my_package.core")
meta.version = "2.1.0"
meta.author = "Jane Doe"
meta.description = "Core functionality package"

# Add dependencies
meta.add_dependency("numpy", ">=1.20.0", DependencyType.REQUIRED)
meta.add_dependency("pandas", ">=1.3.0", DependencyType.OPTIONAL)

# Update content hash
source = "def hello(): return 'world'"
meta.update_content_hash(source)

# Verify integrity
if meta.verify_integrity(source):
    print("Module unchanged")
else:
    print("Module modified or corrupted")

# Version bumping
meta.bump_version("patch")  # 2.1.0 -> 2.1.1
meta.bump_version("minor")  # -> 2.2.0
meta.bump_version("major")  # -> 3.0.0

# Save/load metadata
meta.save_to_file("metadata.json")
loaded = ModuleMetadata.load_from_file("metadata.json")

# Validate dependencies
valid, issues = meta.validate_dependencies()
if not valid:
    for issue in issues:
        print(f"Issue: {issue}")

# Get dependency graph
graph = meta.get_dependency_graph()
print(graph)  # {'my_package.core': ['numpy', 'pandas']}

# Custom metadata
meta.set_custom_metadata("build_date", "2024-01-15")
print(meta.get_custom_metadata("build_date"))
```

---

3. Virtual Package System (package/virtual_package.py)

What It Does

Provides complete virtual package management that fully emulates Python's package import system with support for nested modules, init.py execution, namespace packages, and relative imports.

Why Use It

· Dynamic Package Creation: Create package hierarchies without filesystem operations
· Namespace Packages: PEP 420 compatible namespace packages
· Custom Import Hooks: Seamless integration with Python's import system
· Circular Detection: Automatic circular import detection

Key Classes

```python
from iotm import (
    VirtualPackage, PackageConfig, PackageType, ImportMode,
    create_package, create_namespace_package
)
```

Usage Examples

```python
from iotm import create_package, PackageConfig, ImportMode

# Create basic package
pkg = create_package("myapp")
pkg.get_init().write('''
__version__ = "1.0.0"
__all__ = ["core", "utils"]
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

# Create subpackage
plugins = pkg.create_subpackage("plugins")
db_plugin = plugins.create_module("database")

# Register with import system
pkg.register_importer()

# Now can be imported normally
from myapp.core import Application
app = Application()
print(app.run())

# Create namespace package
ns_pkg = create_namespace_package("mycompany.shared")

# Create with custom config
config = PackageConfig(
    package_type=PackageType.STANDARD,
    import_mode=ImportMode.EAGER,
    enable_events=True
)
pkg = create_package("myapp", config=config)

# Execute all modules
results = pkg.exec_all(recursive=True, parallel=True)
print(results)

# Inject dependencies
pkg.inject_dependencies({"config": {"debug": True}, "db": connection})

# Serialize to disk
pkg.serialize("/output/myapp")

# Deserialize from disk
restored = VirtualPackage.deserialize("/output/myapp")

# Events
@pkg.on(PackageEvent.MODULE_ADDED)
def on_module_added(module_name, **kwargs):
    print(f"Module added: {module_name}")
```

---

4. Sandbox Configuration (sandbox/config.py)

What It Does

Provides comprehensive configuration management for sandbox security settings with support for different security levels, custom rule sets, and cross-platform compatibility.

Security Profiles

Profile Imports File I/O Network Subprocess CPU Time Memory Use Case
MINIMAL All Yes Yes No 30s 500MB Trusted code
STANDARD Safe No No No 5s 100MB General purpose
STRICT Limited No No No 2s 50MB Untrusted code
PARANOID None No No No 1s 10MB Maximum security

Key Classes

```python
from iotm import SandboxConfig, SecurityLevel, ResourceLimits, ModuleRule, AttributeRule
```

Usage Examples

```python
from iotm import SandboxConfig, SecurityLevel, ResourceLimits

# Use predefined profile
config = SandboxConfig.from_profile("strict")
print(config.security_level.name)  # STRICT

# Create custom configuration
config = SandboxConfig(
    security_level=SecurityLevel.CUSTOM,
    allowed_modules={"math", "json", "datetime"},
    blocked_modules={"os", "subprocess"},
    allow_imports=True,
    allow_file_io=False,
    allow_network=False,
    allow_subprocesses=False,
    resource_limits=ResourceLimits(
        cpu_time_seconds=3.0,
        memory_mb=50,
        max_recursion_depth=100
    )
)

# Module rules with patterns
config.add_module_rule("myapp.*", True, "Allow internal modules")
config.add_module_rule("test_*", False, "Block test modules")

# Attribute rules
config.add_attribute_rule("__*__", False, applies_to=".*", reason="Block dunder access")

# Check permissions
if config.is_module_allowed("math"):
    import math

if not config.is_module_allowed("os.system"):
    print("os.system is blocked")

# Save and load
config.save("sandbox_config.json")
loaded = SandboxConfig.from_file("sandbox_config.json")

# Merge configurations
strict = SandboxConfig.from_profile("strict")
custom = SandboxConfig()
merged = strict.merge(custom)

# Validate
errors = config.validate()
if errors:
    print(f"Configuration issues: {errors}")
```

---

5. Sandbox Execution (sandbox/sandbox.py)

What It Does

Provides secure Python sandbox execution environment with multi-layer security including AST static analysis, runtime namespace restrictions, resource monitoring, and system call interception.

Why Use It

· Safe Execution: Execute untrusted code without security risks
· Resource Limits: CPU time, memory, file handles limits
· Module Control: Whitelist/blacklist modules
· Audit Logging: Complete execution audit trail

Key Classes

```python
from iotm import (
    Sandbox, SandboxViolation, SandboxTimeoutError, SandboxMemoryError,
    ExecutionResult, ExecutionEvent, create_math_sandbox
)
```

Usage Examples

```python
from iotm import Sandbox, SecurityLevel, SandboxConfig

# Basic sandbox with standard security
sandbox = Sandbox()

# Execute code safely
result = sandbox.execute("print('Hello, Sandbox!')")
print(result.success)  # True

# Execute with result capture
result = sandbox.execute("sum(range(100))", return_result=True)
print(result.result)  # 4950

# With timeout
result = sandbox.execute("import time; time.sleep(10)", timeout=2.0)
# Raises SandboxTimeoutError

# Inject objects
sandbox.inject("data", [1, 2, 3, 4, 5])
result = sandbox.execute("average = sum(data) / len(data)")
print(sandbox.get_variable("average"))  # 3.0

# Secure proxy for safe access
from iotm import SecureProxy
safe_math = SecureProxy(math, "safe_math", sandbox.config)
result = safe_math.sqrt(16)  # 4.0

# Pre-configured sandboxes
math_sandbox = create_math_sandbox()
data_sandbox = create_data_sandbox()
test_sandbox = create_test_sandbox()

# Execute file
sandbox.execute_file("/path/to/script.py")

# Get namespace copy
namespace = sandbox.get_namespace_copy(safe=True)
print(namespace.keys())

# Audit log
audit = sandbox.get_audit_log()
for entry in audit:
    print(f"{entry['event_type']}: {entry['details']}")

# Save/load state
sandbox.save_state("sandbox_state.json")
sandbox.load_state("sandbox_state.json")

# Reset
sandbox.reset()

# Context manager
with Sandbox() as sandbox:
    result = sandbox.execute("x = 42")
    # Auto-cleanup on exit
```

---

6. AST Editor (ast_editor/editor.py)

What It Does

Provides comprehensive AST manipulation for safe code transformation including renaming, editing, inserting code, and analyzing code metrics.

Why Use It

· Safe Transformations: Modify code without breaking syntax
· Reference Updating: Automatic reference updates when renaming
· Code Metrics: Calculate complexity and quality metrics
· Diff Generation: Track changes between versions

Key Classes

```python
from iotm import ASTEditor, ASTBatchEditor, CodeMetrics, ValidationResult
```

Usage Examples

```python
from iotm import ASTEditor

# Initialize editor
editor = ASTEditor("def hello(): print('Hello')")

# Rename function (updates all references)
editor.rename_function("hello", "greet")
print(editor.get_code())
# def greet(): print('Hello')

# Rename class
editor.rename_class("MyClass", "NewClass")

# Add import
editor.add_import("functools", "ft")
editor.add_import_from("os.path", ["join", "dirname"])

# Add decorator
editor.add_decorator("greet", "@staticmethod")

# Insert code
editor.insert_code_after("greet", "def world(): print('World')")
editor.insert_code_before("greet", "# This is a comment")

# Add method to class
editor.add_method_to_class("Calculator", "def multiply(self, x, y): return x * y")

# Remove function/class
editor.remove_function("deprecated_func")
editor.remove_class("OldClass")

# Get code info
print(editor.get_functions())  # ['greet', 'world']
print(editor.get_classes())    # []
print(editor.get_imports())    # List of import dicts

# Get specific source
func_source = editor.get_function_source("greet")
class_source = editor.get_class_source("MyClass")

# Code metrics
metrics = editor.get_metrics()
print(f"Lines: {metrics.lines_total}")
print(f"Functions: {metrics.functions_count}")
print(f"Cyclomatic complexity: {metrics.cyclomatic_complexity}")

# Call graph
call_graph = editor.get_call_graph()
print(call_graph)  # {'greet': [], 'world': ['print']}

# Find references
references = editor.find_references("greet")
for ref in references:
    print(f"Line {ref['line']}: {ref['context']}")

# Optimize imports
editor.optimize_imports()

# Validate
validation = editor.validate_tree()
for result in validation:
    if not result.is_valid:
        print(f"Error: {result.message}")

# Save to file
editor.save("/output/transformed.py")

# Batch operations
batch = ASTBatchEditor(editor)
batch.queue_operation("rename_function", "old", "new")
batch.queue_operation("add_import", "sys")
batch.execute()

# Get diff
diff = editor.get_diff()
print(diff)

# JSON export
json_str = editor.to_json()

# Execute transformed code
result = editor.execute()
```

---

Complete Example

```python
#!/usr/bin/env python3
"""Complete example using IOTextModule system."""

from iotm import (
    # Core
    open_module, create_virtual_module, ModuleStorageMode,
    # Sandbox
    Sandbox, SandboxConfig, SecurityLevel,
    # Virtual Package
    create_package, VirtualPackage,
    # AST Editor
    ASTEditor,
    # Metadata
    ModuleMetadata
)

def create_dynamic_package():
    """Create a complete virtual package with modules."""
    
    pkg = create_package("myapp")
    
    # Setup __init__.py
    pkg.get_init().write('''
__version__ = "1.0.0"
__all__ = ["core", "utils"]

from .core import Application
''')
    
    # Core module
    core = pkg.create_module("core")
    core.write('''
class Application:
    def __init__(self):
        self.name = "MyApp"
        self._running = False
    
    def start(self):
        self._running = True
        return f"{self.name} started"
    
    def stop(self):
        self._running = False
        return f"{self.name} stopped"
''')
    
    # Utils module
    utils = pkg.create_module("utils")
    utils.write('''
def helper():
    return "Utility function"

def format_output(data):
    return f"Result: {data}"
''')
    
    # Subpackage
    plugins = pkg.create_subpackage("plugins")
    plugins.create_module("database").write('''
from ..core import Application

def get_connection():
    return "Database connected"
''')
    
    return pkg

def secure_execution_demo():
    """Demonstrate sandboxed execution."""
    
    config = SandboxConfig.from_profile(SecurityLevel.STRICT)
    config.allow_module("math")
    config.allow_module("json")
    
    with Sandbox(config) as sandbox:
        # Execute safe code
        result = sandbox.execute('''
import math
def calculate(radius):
    return math.pi * radius ** 2
result = calculate(5)
''', return_result=True)
        
        print(f"Area: {result.result}")  # 78.53981633974483
        
        # Inject data
        sandbox.inject("data", [1, 2, 3, 4, 5])
        result = sandbox.execute("average = sum(data) / len(data)")
        print(f"Average: {sandbox.get_variable('average')}")  # 3.0
        
        # This would be blocked
        try:
            sandbox.execute("import os; os.system('ls')")
        except Exception as e:
            print(f"Blocked: {e}")  # Security violation

def ast_transformation_demo():
    """Demonstrate AST code transformation."""
    
    source = '''
def calculate(x, y):
    """Calculate sum and product."""
    total = x + y
    product = x * y
    return total, product

class Calculator:
    def __init__(self):
        self.result = 0
    
    def add(self, value):
        self.result += value
        return self.result
'''
    
    editor = ASTEditor(source)
    
    # Rename function
    editor.rename_function("calculate", "compute")
    
    # Add decorator
    editor.add_decorator("compute", "@staticmethod")
    
    # Add method
    editor.add_method_to_class("Calculator", '''
def multiply(self, value):
    self.result *= value
    return self.result
''')
    
    # Get metrics
    metrics = editor.get_metrics()
    print(f"Lines: {metrics.lines_total}")
    print(f"Functions: {metrics.functions_count}")
    print(f"Classes: {metrics.classes_count}")
    
    # Get transformed code
    print(editor.get_code())

def main():
    """Run all demonstrations."""
    
    print("=" * 60)
    print("IOTextModule Complete Demo")
    print("=" * 60)
    
    print("\n1. Creating Virtual Package...")
    pkg = create_dynamic_package()
    pkg.register_importer()
    pkg.exec_all()
    
    print("\n2. Secure Execution Demo...")
    secure_execution_demo()
    
    print("\n3. AST Transformation Demo...")
    ast_transformation_demo()
    
    print("\nDemo completed successfully!")

if __name__ == "__main__":
    main()
```

---

Requirements

· Python 3.8+
· Standard library only for core functionality
· Optional: psutil for advanced resource monitoring
· Optional: watchdog for efficient file watching

Key Features Summary

Feature Module Sandbox Metadata Virtual Package AST Editor
Hot reloading ✓ ✗ ✗ ✓ ✗
Storage modes ✓ ✗ ✗ ✗ ✗
Security profiles ✗ ✓ ✗ ✗ ✗
Resource limiting ✗ ✓ ✗ ✗ ✗
Version tracking ✗ ✗ ✓ ✗ ✗
Integrity verification ✗ ✗ ✓ ✗ ✗
Package hierarchy ✗ ✗ ✗ ✓ ✗
Import hooks ✗ ✗ ✗ ✓ ✗
Code transformation ✗ ✗ ✗ ✗ ✓
Metrics calculation ✗ ✗ ✗ ✗ ✓
Diff generation ✗ ✗ ✗ ✗ ✓