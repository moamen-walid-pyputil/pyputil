# pmeX (Python Module Explorer) Documentation

## Overview

pmeX (Python Module Explorer) is a comprehensive framework for runtime Python module analysis, modification, and control. It enables developers to dynamically inspect, mutate, clone, and monitor Python modules with fine-grained control over attributes, functions, imports, and module lifecycle.

## Architecture

The system consists of the following core modules:

| Module | Purpose |
|--------|---------|
| `core.py` | Main `pmeX` class with all module management functionality |
| `cloning.py` | Module cloning with selective mutation capabilities |
| `injection.py` | Code injection and reversion management |
| `protection.py` | Module protection, freezing, and read-only features |
| `patching.py` | Function hooks, attribute locking, and patching |

## Installation

```python
from pyputil.core import pmeX
```

Core Class: pmeX

The main class for module exploration and control.

Constructor:

```python
pmeX(module: ModuleType) -> pmeX
```

Parameters:

Parameter Type Description
module ModuleType Python module object to explore and control

Attributes:

Attribute Type Description
name str Original module name
path Optional[str] File system path to module directory
injection Injecter Manager for code injection operations
protection ProtectionManager Manager for module protection
patching PatchingManager Manager for patching and hooks

Feature Categories

1. Code Injection

inject()

Dynamically inject Python code into the module's namespace.

```python
def inject(self, code_str: str) -> Dict[str, Any]
```

Parameters:

· code_str: Valid Python code to execute within module namespace

Returns: Dictionary with 'success', 'message', 'defined' keys

Examples:

```python
import math
explorer = pmeX(math)

# Inject constant
explorer.inject("TAU = 2 * pi")
print(math.TAU)  # 6.283185307179586

# Inject function
explorer.inject('''
def circle_area(radius):
    return pi * radius ** 2
''')
print(math.circle_area(5))  # 78.53981633974483

# Inject class
explorer.inject('''
class Calculator:
    def double(self, x):
        return x * 2
''')
```

revert_injection()

Revert previously injected code.

```python
def revert_injection(self, name: Optional[str] = None, restore_all: bool = False) -> Dict[str, Any]
```

Parameters:

· name: Specific injected name to revert
· restore_all: If True, revert all injected changes

Examples:

```python
explorer.inject("TEST_VAR = 100")
explorer.revert_injection("TEST_VAR")  # Remove specific

# Revert all
explorer.revert_injection(restore_all=True)
```

2. Module Protection

disable_feature()

Disable a specific feature (function, attribute, or method).

```python
def disable_feature(self, name: str, behavior: str = "raise", message: Optional[str] = None) -> Dict[str, Any]
```

Behavior modes:

· 'raise': Raise RuntimeError when accessed
· 'warn': Print warning and return None
· 'ignore': Silently return None
· 'return': Return specified value (requires 'return_value')

Examples:

```python
# Disable with exception
explorer.disable_feature('sqrt', 'raise')
try:
    math.sqrt(16)
except RuntimeError as e:
    print(e)  # Feature 'sqrt' has been disabled

# Disable with warning
explorer.disable_feature('log', 'warn', 'Log is deprecated')

# Revert
explorer.revert_feature('sqrt')
```

freeze()

Permanently freeze the module to prevent any further modifications.

```python
def freeze(self, message: str = "Module has been frozen and cannot be modified") -> None
```

Examples:

```python
explorer.freeze("math module is locked")
try:
    math.pi = 3.0
except RuntimeError as e:
    print(e)  # math module is locked
```

readonly()

Make the module read-only, optionally with permanent freezing.

```python
def readonly(self, freeze: bool = False) -> None
```

Examples:

```python
# Read-only without freeze (reversible)
explorer.readonly(freeze=False)

# Permanent read-only
explorer.readonly(freeze=True)
```

3. Patching and Hooking

hooks()

Install before/after hooks on a function or method.

```python
def hooks(self, func_name: str, before: Optional[Callable] = None, after: Optional[Callable] = None) -> None
```

Examples:

```python
# Logging hook
def log_before(*args, **kwargs):
    print(f"Calling sqrt with args={args}")

def log_after(result, *args, **kwargs):
    print(f"sqrt returned {result}")

explorer.hooks('sqrt', before=log_before, after=log_after)
math.sqrt(16)
# Calling sqrt with args=(16,)
# sqrt returned 4.0

# Modify arguments
def double_value(*args, **kwargs):
    return (args[0] * 2,), kwargs

explorer.hooks('sqrt', before=double_value)
math.sqrt(16)  # Actually computes sqrt(32)
```

patch()

Replace a module attribute with a new object.

```python
def patch(self, name: str, new_obj: Any) -> None
```

Examples:

```python
# Replace constant
explorer.patch('pi', 3.14)
print(math.pi)  # 3.14

# Replace function
explorer.patch('sqrt', lambda x: x ** 0.5 * 2)
print(math.sqrt(16))  # 8.0

# Restore
explorer.unpatch('pi')
```

lock_attr()

Lock specific attributes to prevent modification.

```python
def lock_attr(self, names: List[str]) -> None
```

Examples:

```python
explorer.lock_attr(['pi', 'e'])
try:
    math.pi = 3.0
except AttributeError as e:
    print(e)  # Can't modify locked attribute 'pi'
```

4. Import Control

activate_import_interception()

Activate the import interception system.

```python
def activate_import_interception(self) -> None
```

block_imports()

Block specific modules from being imported.

```python
def block_imports(self, modules: List[str]) -> Dict[str, bool]
```

Examples:

```python
explorer.activate_import_interception()
explorer.block_imports(['os', 'subprocess'])

try:
    import os
except ImportError as e:
    print(e)  # Import of module 'os' is blocked

# Wildcard blocking
explorer.block_imports(['numpy.*'])
```

mock_import()

Replace a module import with a mock object.

```python
def mock_import(self, module_name: str, mock_object: Any) -> None
```

Examples:

```python
from unittest.mock import MagicMock

mock_np = MagicMock()
mock_np.array.return_value = [1, 2, 3]
explorer.mock_import('numpy', mock_np)

import numpy as np
print(np.array([1, 2, 3]))  # [1, 2, 3]

# Remove mock
explorer.unmock_import('numpy')
```

intercept_import()

Set custom callback to intercept and modify imports.

```python
def intercept_import(self, callback: Callable[[str, Any], Tuple[str, Any]]) -> None
```

Examples:

```python
def add_prefix(name, module):
    return (f"mocked_{name}", module)

explorer.intercept_import(add_prefix)

def log_import(name, module):
    print(f"Importing: {name}")
    return (name, module)

explorer.intercept_import(log_import)
```

5. Serialization and Persistence

serialize()

Serialize current module state to bytes or file.

```python
def serialize(self, path: Optional[Union[str, Path]] = None, format: str = 'pickle') -> bytes
```

Parameters:

· path: File path to save state (None returns bytes)
· format: 'pickle' or 'json'

Examples:

```python
# Save to bytes
state_bytes = explorer.serialize()

# Save to file
explorer.serialize('/tmp/math_state.pkl')

# JSON format
state_json = explorer.serialize(format='json')
```

deserialize()

Restore module state from serialized data.

```python
def deserialize(self, source: Union[str, Path, bytes], format: str = 'pickle') -> 'pmeX'
```

Examples:

```python
# Restore from bytes
new_explorer = pmeX(math)
new_explorer.deserialize(state_bytes)

# Restore from file
new_explorer.deserialize('/tmp/math_state.pkl')
```

snapshot()

Create named snapshot of current module state.

```python
def snapshot(self, name: Optional[str] = None) -> str
```

Examples:

```python
explorer.snapshot("before_changes")
explorer.patch('pi', 3.14)
explorer.restore_snapshot("before_changes")

# Auto-generate name
snap_name = explorer.snapshot()  # snapshot_20240115_143045_123456

# List snapshots
print(explorer.list_snapshots())

# Delete snapshot
explorer.delete_snapshot("temp_state")
```

6. Batch Operations

batch_patch()

Apply multiple patches atomically or non-atomically.

```python
def batch_patch(self, patches: Dict[str, Any], atomic: bool = True) -> Dict[str, bool]
```

Examples:

```python
patches = {
    'pi': 3.14,
    'e': 2.71828,
    'tau': 6.28318,
    'sqrt': lambda x: x ** 0.5
}
results = explorer.batch_patch(patches)

# Atomic mode (all or nothing)
try:
    explorer.batch_patch(bad_patches, atomic=True)
except RuntimeError:
    print("All changes rolled back")
```

batch_inject()

Inject multiple code snippets in batch.

```python
def batch_inject(self, code_snippets: Dict[str, str], atomic: bool = True) -> Dict[str, bool]
```

Examples:

```python
snippets = {
    'constant': 'ANSWER = 42',
    'function': 'def greet(): return "Hello"',
    'class': 'class Calc: def add(self, a, b): return a + b'
}
results = explorer.batch_inject(snippets)
```

batch_disable()

Disable multiple features in batch.

```python
def batch_disable(self, features: List[str], behavior: str = "raise") -> Dict[str, bool]
```

Examples:

```python
features = ['sqrt', 'sin', 'cos', 'tan']
results = explorer.batch_disable(features, 'warn')
```

7. Change Tracking

get_change_history()

Retrieve history of all changes made to module.

```python
def get_change_history(self, limit: Optional[int] = None, since: Optional[str] = None) -> List[Dict[str, Any]]
```

Examples:

```python
# Get all changes
history = explorer.get_change_history()

# Get last 5 changes
recent = explorer.get_change_history(limit=5)

# Get changes after specific time
changes = explorer.get_change_history(since='2024-01-01T00:00:00')
```

get_changed()

Get all attributes modified from original state.

```python
def get_changed(self) -> Dict[str, Tuple[Any, Any]]
```

Examples:

```python
changed = explorer.get_changed()
for attr, (old, new) in changed.items():
    print(f"{attr}: {old} -> {new}")
```

diff()

Generate detailed difference between current and another module state.

```python
def diff(self, other: Union[ModuleType, 'pmeX']) -> Dict[str, Dict[str, Any]]
```

Examples:

```python
explorer2 = pmeX(math)
explorer2.patch('pi', 3.14)
diff = explorer.diff(explorer2)

print(diff['modified']['pi'])  # {'old': 3.14159..., 'new': 3.14}
print(diff['added'])  # {'VERSION': '2.0'}
```

rollback()

Rollback specified number of changes.

```python
def rollback(self, steps: int = 1) -> List[Dict[str, Any]]
```

Examples:

```python
explorer.patch('pi', 3.14)
explorer.patch('e', 2.718)
explorer.inject("TAU = 6.283")

# Rollback last change
explorer.rollback(1)  # TAU removed

# Rollback 2 changes
explorer.rollback(2)  # pi and e restored
```

8. Cloning

clone()

Create deep copy of module with selective mutations.

```python
def clone(
    self,
    mutation_rules: Optional[Dict[str, Any]] = None,
    copy_all: bool = True,
    exclude: Optional[Set[str]] = None,
    deep_copy_attrs: Optional[Set[str]] = None,
    shallow_copy_attrs: Optional[Set[str]] = None,
    preserve_module_metadata: bool = True,
    module_doc: Optional[str] = None,
    import_original_on_error: bool = True,
    recursion_limit: int = 10,
    enable_warnings: bool = True,
) -> ModuleType
```

Examples:

```python
# Clone with mutations
rules = {
    'pi': 3.14,
    'sqrt': lambda f: lambda x: f(x) * 2
}
math_clone = explorer.clone(rules)

print(math_clone.pi)  # 3.14
print(math_clone.sqrt(4))  # 4.0

# Clone excluding specific attributes
math_clone = explorer.clone(
    exclude={'__file__', '__loader__'},
    shallow_copy_attrs={'__builtins__'}
)
```

9. Resource Management

cleanup_unused()

Clean up unused attributes and cached data.

```python
def cleanup_unused(self, include_private: bool = False) -> Dict[str, int]
```

Examples:

```python
math.temp_var = 100
math._private = 42

stats = explorer.cleanup_unused()
print(stats['attributes_removed'])  # 1 (temp_var)

stats = explorer.cleanup_unused(include_private=True)
print(stats['attributes_removed'])  # 2 (both removed)
```

unload()

Unload module from sys.modules and clean references.

```python
def unload(self) -> bool
```

Examples:

```python
explorer.unload()
print('mymod' in sys.modules)  # False
```

reload_force()

Forcefully reload module, optionally preserving patches.

```python
def reload_force(self, preserve_patches: bool = False) -> ModuleType
```

Examples:

```python
# Reload without preserving changes
math = explorer.reload_force()

# Reload preserving patches
explorer.patch('pi', 3.14)
math = explorer.reload_force(preserve_patches=True)
print(math.pi)  # 3.14
```

10. Utility Methods

info()

Get comprehensive information about module state.

```python
def info(self) -> Dict[str, Any]
```

Examples:

```python
info = explorer.info()
print(f"Module: {info['name']}")
print(f"Functions: {info['functions']}")
print(f"Classes: {info['classes']}")
print(f"Patches: {info['patches']}")
print(f"Snapshots: {info['snapshots']}")
```

modules()

Extract modules from namespace with configurable depth.

```python
def modules(self, level: int = 0) -> Dict[str, ModuleType]
```

Examples:

```python
# Inspect only module's direct namespace
submodules = explorer.modules(level=0)

# Recursive inspection (depth 1)
all_modules = explorer.modules(level=1)
```

executive()

Execute or evaluate Python code in module namespace.

```python
def executive(self, code: str) -> Any
```

Examples:

```python
# Evaluate expression
result = explorer.executive("2 * pi")
print(result)  # 6.283185307179586

# Execute statement
explorer.executive("x = 100")
print(math.x)  # 100
```

Complete Usage Examples

Example 1: Module Sandboxing

```python
from pyputil.core import pmeX
import math

# Create sandboxed environment
sandbox = pmeX(math)

# Block dangerous imports
sandbox.activate_import_interception()
sandbox.block_imports(['os', 'subprocess', 'sys', 'socket'])

# Disable dangerous functions
sandbox.disable_feature('pow', 'raise', 'Power operation disabled')
sandbox.disable_feature('__import__', 'raise')

# Make module read-only
sandbox.readonly(freeze=True)

# Safe to execute untrusted code
try:
    sandbox.executive("import os")  # Will be blocked
except ImportError:
    print("Import blocked")
```

Example 2: Development Hot Reload

```python
from pyputil.core import pmeX
import mymodule

dev = pmeX(mymodule)

# Create initial snapshot
dev.snapshot("working_state")

# Apply development patches
dev.patch('process_data', debug_version)
dev.inject("DEBUG = True")

# Test changes
result = dev.executive("process_data(test_input)")

if result.failed:
    # Rollback to working state
    dev.restore_snapshot("working_state")
```

Example 3: Dependency Mocking for Testing

```python
from pyputil.core import pmeX
from unittest.mock import MagicMock
import myapp

test_env = pmeX(myapp)

# Activate import interception
test_env.activate_import_interception()

# Mock external dependencies
mock_db = MagicMock()
mock_db.query.return_value = [{"id": 1, "name": "Test"}]
test_env.mock_import('database', mock_db)

mock_api = MagicMock()
mock_api.get.return_value = {"status": "ok"}
test_env.mock_import('external_api', mock_api)

# Run tests with mocked dependencies
result = myapp.process_request()
assert result == expected
```

Example 4: Module Profiling

```python
from pyputil.core import pmeX
import time

def profile_module(module_name):
    explorer = pmeX(__import__(module_name))
    
    # Add profiling hooks
    def profile_before(*args, **kwargs):
        start_time = time.time()
        return (args, kwargs, start_time)
    
    def profile_after(result, *args, **kwargs):
        elapsed = time.time() - kwargs['start_time']
        print(f"Function took {elapsed:.4f}s")
        return result
    
    # Apply to all functions
    for name, value in explorer.module.__dict__.items():
        if callable(value) and not name.startswith('_'):
            explorer.hooks(name, before=profile_before, after=profile_after)
    
    return explorer
```

Example 5: Configuration Injection

```python
from pyputil.core import pmeX
import myapp

# Inject configuration at runtime
config = pmeX(myapp)

config.inject('''
CONFIG = {
    'api_key': 'secret123',
    'timeout': 30,
    'retries': 3,
    'debug': True
}
''')

config.inject('''
def get_config(key):
    return CONFIG.get(key)
''')

# Use injected configuration
api_key = myapp.get_config('api_key')
```

Error Handling

```python
from pyputil.core import pmeX
import math

explorer = pmeX(math)

try:
    explorer.patch('non_existent', 100)
except AttributeError as e:
    print(f"Attribute doesn't exist: {e}")

try:
    explorer.disable_feature('sqrt', 'raise')
    math.sqrt(-1)
except RuntimeError as e:
    print(f"Feature disabled: {e}")

try:
    explorer.freeze()
    explorer.patch('pi', 3.14)
except RuntimeError as e:
    print(f"Module frozen: {e}")
```

Requirements

· Python 3.7+
· Standard library only for core functionality
· pickle, json, copy, gc (standard library)

Key Features Summary

Feature Description
Code Injection Runtime injection of Python code into modules
Module Protection Freezing, read-only, feature disabling
Patching & Hooks Before/after hooks, attribute patching
Import Control Block, mock, and intercept imports
Serialization Save/restore module state (pickle/json)
Snapshots Named module state snapshots
Change Tracking Full history of modifications
Batch Operations Atomic batch patches and injections
Module Cloning Deep copy with mutations
Resource Management Cleanup, unload, reload