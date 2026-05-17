# PyPUtil

Production-grade Python utilities for package management, module inspection,
dependency analysis, dynamic loading, project templating, and runtime tooling.

---

## Installation

```bash
pip install pyputil
```

---

## Quick Example

```python
from pyputil.install import auto_install

auto_install(mode="confirm")

import requests
```

---

## Core Features

### API Management

Control and sanitize module exports using the `clean()` utility.

```python
from pyputil.api import clean

clean(
    expose=['public_func', 'PublicClass'],
    block=['_private'],
    deprecated={'old_func': "Use new_func()"},
    cache=True
)
```

---

### Dynamic Module Loading

Load Python modules from files, code strings, or lazy loaders.

```python
from pyputil.loader import load_from_code, LazyLoader

module = load_from_code(
    "def hello(): return 'world'",
    name="greeter"
)

pd = LazyLoader("pandas")
```

!!! warning

    Only execute trusted code sources.

---

### Module Backup System

Create and restore compressed module backups safely.

```python
from pyputil.core import ModuleBackup

backup = ModuleBackup("requests")

result = backup.backup(
    compress=True,
    message="Pre-upgrade backup"
)

backup.restore(stamp=result.backup.stamp)
```

---

### Dependency Analysis

Build and inspect dependency trees.

```python
from pyputil.tree import (
    DependencyTreeBuilder,
    print_dep_tree
)

tree = DependencyTreeBuilder(
    "requests",
    max_depth=3
)

print_dep_tree("pandas", max_depth=2)
```

---

### Import Analysis Utilities

Inspect importable symbols and clean unused imports.

```python
from pyputil.util import (
    importables,
    detect_unused_imports
)

funcs = importables(
    "numpy",
    filter_by="function"
)

unused = detect_unused_imports(
    "my_module.py"
)
```

---

### Project Templates

Generate production-ready Python project structures.

```python
from pyputil.template import (
    build_structure_template,
    ProjectType
)

build_structure_template(
    pathname="mycli",
    project_type=ProjectType.CLI_APP
)
```

---

## Documentation Sections

| Section | Description |
|---|---|
| Getting Started | Installation, configuration, and quick start |
| Core Modules | Runtime utilities and package management |
| Loader System | Dynamic imports and lazy loading |
| Dependency Tools | Dependency parsing and tree analysis |
| Path Utilities | File and package inspection |
| Templates | Project scaffolding and generators |
| API Reference | Complete API documentation |

---

## Quick Links

- [Home Index](index.md)
- [Getting Started](getting-started.md)
- [API Reference](api/api-docs.md)
- [Path Package](path/path-docs.md)
- [Core pmeX Management](core/explorer-docs.md)
- [Core Searcher Management](core/searcher-docs.md)

---

## License

PyPUtil is licensed under the MIT License.