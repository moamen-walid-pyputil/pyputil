# Getting Started with PyPUtil

Welcome to PyPUtil — a production-grade Python utilities library for package management, dynamic loading, dependency analysis, project scaffolding, runtime module inspection, and developer tooling.

---

## Installation

```bash
pip install pyputil
```

---

## 30-Second Quick Start

PyPUtil helps automate common Python workflows with simple APIs.

```python
# 1. Auto-install missing packages
from pyputil.install import auto_install

auto_install(mode="confirm")

import requests
```

```python
# 2. Explore and modify modules at runtime
from pyputil.core import pmeX
import math

explorer = pmeX(math)

explorer.inject("TAU = 2 * pi")

print(math.TAU)
```

```python
# 3. Load Python code dynamically
from pyputil.loader import load_from_code

mod = load_from_code(
    "def hello(): return 'world'"
)

print(mod.hello())
```

```python
# 4. Generate a production-ready project
from pyputil.template import build_structure_template

build_structure_template(
    "my_project",
    author="Your Name"
)
```

This automatically creates:

- `pyproject.toml`
- `README.md`
- `LICENSE`
- `.gitignore`
- `tests/`
- `docs/`

---

## Most Useful Features

### 📦 Package Management

Install and manage Python packages programmatically.

```python
from pyputil.install import PackageInstaller

installer = PackageInstaller("requests")

if not installer.is_installed():
    installer.install()
```

---

### 🔍 Module Inspection

Inspect package metadata and file information.

```python
from pyputil.path import Plib

pkg = Plib("numpy")

info = pkg.information()

print(f"Size: {info.size_mb:.1f} MB")
print(f"Files: {info.file_count}")
```

---

### 📊 Dependency Tree Visualization

Inspect package dependency structures.

```python
from pyputil.tree import print_dep_tree

print_dep_tree(
    "requests",
    max_depth=2,
    colorize=True
)
```

Example output:

```text
requests==2.28.1
├── certifi>=2017.4.17
├── charset-normalizer~=2.0.0
└── urllib3<1.27,>=1.21.1
```

---

### ✏️ Import Cleaning

Automatically remove unused imports using AST analysis.

```python
from pyputil.util import clean_file_imports

clean_file_imports(
    "my_script.py",
    backup=True
)
```

---

### 🧩 Dynamic Module Loading

Load modules from files or raw code strings.

```python
from pyputil.loader import load_from_code

module = load_from_code(
    "def add(a, b): return a + b"
)

print(module.add(5, 3))
```

!!! warning

    Only execute trusted Python code sources.

---

### 🏗️ Project Template Generator

Generate complete Python project structures instantly.

```python
from pyputil.template import build_structure_template

build_structure_template(
    "my_package",
    project_type="library",
    dependencies=["requests"],
    create_github_actions=True
)
```

---

## Common Use Cases

### Inspect Everything Inside a Package

```python
from pyputil.util import (
    importables,
    deep_dir
)

symbols = importables(
    "pandas",
    detailed=True
)

print(symbols.summary())

result = deep_dir(
    "numpy",
    max_depth=2
)

print(result.classes)
```

---

### Analyze Package Disk Usage

```python
from pyputil.path import size

s = size("tensorflow")

print(s.readable)

print(s.size_breakdown(top=5))
```

---

### Watch Files and Reload Automatically

```python
from pyputil.path import PackageWatcher

watcher = PackageWatcher("myapp")

watcher.start_watching()
```

---

## Configuration

PyPUtil supports configuration through `pyproject.toml`.

```toml
[tool.pyputil]
auto_install_mode = "confirm"
cache_enabled = true
max_depth = 3

[tool.pyputil.import_cleaner]
safe_mode = true
backup = true
```

---

## Next Steps

| If you want to... | Read this |
|---|---|
| Control API exports | API Management |
| Explore modules dynamically | pmeX Explorer |
| Load modules lazily | Loader System |
| Analyze dependencies | Dependency Module |
| Create project templates | Template Generator |
| Transform Python code | AST Editor |
| Run untrusted code safely | Sandbox |

---

## Need Help?

```python
from pyputil.util import (
    help,
    help_topic
)

help()

help_topic("clone")

help_topic("all_list")
```

---

## Requirements

- Python 3.10+
- No required external dependencies for core features.

## Optional Dependencies

Some modules require additional optional dependencies.

- Optional: `colorama`
- Optional: `packaging`

### Searcher Module

!!! note

    These dependencies are only required when using the `Searcher` module.

The `Searcher` module uses the following optional packages:

- `aiohttp`
- `aiolimiter`
- `backoff`

---

## Pro Tips

1. Use `auto_install()` inside notebooks and Colab environments
2. Use `LazyLoader` for heavy libraries like NumPy or Pandas
3. Use `print_dep_tree()` to debug dependency problems
4. Use `clean()` to control your public APIs
5. Use module cloning utilities for sandboxed environments

---

## Complete Workflow Example

```python
#!/usr/bin/env python3

from pyputil.install import auto_install
from pyputil.loader import LazyLoader
from pyputil.tree import print_dep_tree
from pyputil.util import clean_file_imports
from pyputil.template import build_structure_template

# Automatically install missing packages
auto_install(mode="silent")

# Lazy-load heavy libraries
pd = LazyLoader("pandas")
np = LazyLoader("numpy")

# Analyze dependencies
print_dep_tree(
    "my_project",
    max_depth=2
)

# Remove unused imports
clean_file_imports(
    "my_module.py",
    backup=True
)

# Generate a new project
build_structure_template(
    "new_project",
    author="You"
)
```

---

You're now ready to start using PyPUtil.