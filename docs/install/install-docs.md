# PyPutil Package Management System Documentation

## Overview

PyPutil Package Management System is a comprehensive suite of tools for managing Python packages, modules, and their dependencies. It provides functionality for installing, uninstalling, upgrading, and analyzing packages with robust error handling, security features, and automatic dependency resolution.

## Architecture

The system consists of the following core modules:

| Module | Purpose |
|--------|---------|
| `Installer.py` | Core `PackageInstaller` class for pip-based package management |
| `AutoInstaller.py` | Automatic import-based installation with meta path finder |
| `StdlibInstaller.py` | Standard library module installation from CPython repository |
| `InstallStdlib.py` | Convenience functions for stdlib installation |
| `InstallUtil.py` | File and directory installation utilities |
| `HeadersInstaller.py` | Python development headers installation |
| `exceptions.py` | Custom exception hierarchy |

## Core Classes

### 1. PackageInstaller

A robust interface to Python's pip package manager.

**Constructor:**
```python
PackageInstaller(
    package_name: str,
    pip_path: Optional[Union[str, Path]] = None,
    timeout: int = 60
)
```

Methods:

Method Description
is_installed() Check if package is installed
get_version() Get installed version
get_latest_version(pre) Get latest version from PyPI
check_upgrade(pre) Check if upgrade available
install(version, upgrade, pre, user, requirements, extra_args) Install package
uninstall(confirm, extra_args) Uninstall package
upgrade(pre, user, extra_args) Upgrade to latest version

Examples:

```python
from pyputil.install import PackageInstaller

# Basic usage
installer = PackageInstaller("requests")
if not installer.is_installed():
    installer.install()

# Install specific version
installer.install(version="2.31.0")

# Check for upgrades
if installer.check_upgrade():
    installer.upgrade()

# Install from requirements file
installer.install(requirements="/path/to/requirements.txt")

# Uninstall with confirmation
installer.uninstall(confirm=True)
```

2. AutoInstaller (Enhanced)

Automatically installs missing packages when imported with comprehensive security and compatibility features.

Configuration Class:

```python
AutoInstallConfig(
    mode: InstallationMode = InstallationMode.SILENT,
    security_level: SecurityLevel = SecurityLevel.MEDIUM,
    safe_packages: Set[str] = None,
    virtual_env_only: bool = False,
    use_safe_flags: bool = False,
    max_install_attempts: int = 1,
    timeout_seconds: int = 60,
    debounce_seconds: float = 5.0,
    auto_user_flag: bool = True,
    refresh_sys_path: bool = True,
    ...
)
```

Installation Modes:

Mode Description
SILENT Install without asking
CONFIRM Ask for confirmation before installing
DRY_RUN Show what would be installed
STRICT Only install from safe_packages list

Security Levels:

Level Description
LOW No restrictions
MEDIUM Warn about installations
HIGH Only install from safe_packages, require confirmation

Examples:

```python
from pyputil.install import auto_install, auto_install_context

# Basic auto-install
auto_install(mode="confirm")

# Android/Pydroid/Google Colab compatible (fixes sys.path issues)
auto_install(
    mode="confirm",
    virtual_env_only=False,
    use_safe_flags=False,
    refresh_sys_path=True
)

# Production with virtual environment
auto_install(
    mode="strict",
    security_level="high",
    safe_packages={'requests', 'numpy', 'pandas'},
    virtual_env_only=True,
    use_safe_flags=True
)

# Context manager (temporary)
with auto_install_context(mode="silent"):
    import missing_package  # Will auto-install

# After context, normal import behavior restored
```

Key Features of AutoInstaller:

· Package name validation to prevent injection
· Blocklist for critical packages (pip, setuptools)
· Virtual environment enforcement
· Debouncing to prevent resource exhaustion
· Thread-safe caching of successes/failures
· sys.path refresh for Android/Pydroid compatibility
· Automatic --user flag in non-virtual environments

3. StdlibInstaller

Installs Python standard library modules from CPython GitHub repository.

Constructor:

```python
StdlibInstaller(
    repo_api: Optional[str] = None,
    timeout: int = 30
)
```

Methods:

Method Description
install(name, version, force) Install stdlib module/package
install_bulk(names, version) Install multiple modules
update(name, version) Update installed module
remove(name, ignore_errors) Remove module
list_installed(fullpath) List installed modules
is_installed(name) Check if installed

Examples:

```python
from pyputil.install import StdlibInstaller

installer = StdlibInstaller()

# Install a single module
installer.install('json')

# Install a package (directory with multiple files)
installer.install('xml')

# Install specific Python version
installer.install('asyncio', version='3.8')

# Bulk installation
results = installer.install_bulk(['csv', 'sqlite3', 'datetime'])
for name, result in results.items():
    if isinstance(result, str):
        print(f"✓ {name}: {result}")
    else:
        print(f"✗ {name}: {result}")

# Update existing installation
installer.update('json')

# Remove a package
installer.remove('json')

# List installed packages
for pkg in installer.list_installed():
    print(pkg)
```

4. File/Directory Installation Utilities

install_file():

```python
install_file(
    filename: str,
    target: Literal["site", "dynload"] = "site",
    path: Optional[str] = None,
    mode: Literal["move", "copy", "symlink"] = "move",
    overwrite: bool = False
) -> str
```

install_path():

```python
install_path(
    dirname: str,
    target: Literal["site", "dynload"] = "site",
    path: Optional[str] = None,
    mode: Literal["move", "copy", "symlink"] = "move",
    overwrite: bool = False
) -> str
```

Examples:

```python
from pyputil.install import install_file, install_path

# Install a single file to site-packages
install_file("mymodule.py", mode="copy")

# Install compiled extension to lib-dynload
install_file("fastmath.so", target="dynload", mode="copy")

# Create symlink for development
install_file("devmodule.py", mode="symlink", overwrite=True)

# Install entire package directory
install_path("mypackage", mode="copy")

# Install with custom path
install_path(
    "mypackage",
    path="/custom/python/libs",
    mode="symlink"
)
```

5. HeadersInstaller

Installs Python development headers from source.

Function:

```python
install_python_headers(
    version: Optional[str] = None,
    target_dir: Optional[Union[str, Path]] = None,
    retries: int = 3,
    retry_delay: float = 2.0,
    clean_existing: bool = False,
    backup_existing: bool = True,
    verbose: bool = False,
    include_subdirs: bool = True,
    source: str = "github",
    custom_url: Optional[str] = None
) -> Optional[str]
```

Examples:

```python
from pyputil.install import install_python_headers

# Install headers for current Python version
install_python_headers()

# Install for specific version with verbose output
install_python_headers(
    version='3.9.5',
    verbose=True,
    backup_existing=True
)

# Install from python.org source
install_python_headers(
    source="python.org",
    clean_existing=True
)

# Install to custom directory
install_python_headers(
    target_dir="./my_headers",
    include_subdirs=True
)
```

6. Dependency Analysis

get_uninstalled_packages():

```python
get_uninstalled_packages(
    file_or_code: str,
    allow_relative_import: bool = True,
    ignore: List[str] = None
) -> List[str]
```

Examples:

```python
from pyputil.install import get_uninstalled_packages

# Analyze Python file
missing = get_uninstalled_packages("script.py")
print(f"Missing packages: {missing}")

# Analyze code string
code = """
import requests
import numpy as np
from pandas import DataFrame
"""
missing = get_uninstalled_packages(code)
print(f"Missing: {missing}")

# Ignore specific packages
missing = get_uninstalled_packages(
    "script.py",
    ignore=["numpy"],
    allow_relative_import=False
)
```

Enumerations

InstallationMode

Value Description
SILENT Install without asking
CONFIRM Ask for confirmation
DRY_RUN Preview only
STRICT Only safe packages

SecurityLevel

Value Description
LOW No restrictions
MEDIUM Warnings only
HIGH Safe packages only

Exceptions

Exception Description
PackageInstallerError Base exception
PackageInstallerNotFound Pip not found
PackageInstallerTimeout Operation timeout
PackageInstallerExecutionError Pip execution failed
AutoInstallError Auto-installation error

Complete Examples

Example 1: Automated Dependency Management

```python
from pyputil.install import (
    auto_install,
    get_uninstalled_packages,
    PackageInstaller
)

# Enable auto-installation for development
auto_install(
    mode="confirm",
    security_level="medium",
    virtual_env_only=False,
    refresh_sys_path=True
)

# Analyze project dependencies
missing = get_uninstalled_packages("my_project/__init__.py")

if missing:
    print(f"Missing dependencies: {missing}")
    installer = PackageInstaller("dummy")
    for pkg in missing:
        print(f"Installing {pkg}...")
        installer.install(pkg)
```

Example 2: Production Deployment

```python
from pyputil.install import PackageInstaller

requirements = [
    "requests>=2.31.0",
    "numpy==1.24.3",
    "pandas<2.0.0",
    "sqlalchemy~=2.0.0"
]

for req in requirements:
    pkg_name = req.split(">=")[0].split("==")[0].split("<")[0].split("~=")[0]
    installer = PackageInstaller(pkg_name.strip())
    
    if not installer.is_installed():
        print(f"Installing {req}...")
        version = req.split("==")[1] if "==" in req else None
        installer.install(version=version)
    elif installer.check_upgrade():
        print(f"Upgrading {pkg_name}...")
        installer.upgrade()
```

Example 3: Custom Package Repository

```python
from pyputil.install import PackageInstaller

# Install from custom repository
installer = PackageInstaller("my-package")
installer.install(
    extra_args=[
        "--index-url", "https://my-private-repo.com/simple",
        "--trusted-host", "my-private-repo.com"
    ]
)

# Install with no dependencies
installer.install(extra_args=["--no-deps"])

# Install to user directory
installer.install(user=True)
```

Example 4: Stdlib Package Management

```python
from pyputil.install import StdlibInstaller

installer = StdlibInstaller()

# Install common utility modules
stdlib_packages = [
    'json', 'csv', 'datetime', 'collections',
    'itertools', 'functools', 'pathlib'
]

results = installer.install_bulk(stdlib_packages)

for pkg, result in results.items():
    if isinstance(result, str):
        print(f"✓ {pkg} installed at {result}")
    else:
        print(f"✗ {pkg}: {result}")

# Verify installations
for pkg in stdlib_packages:
    if installer.is_installed(pkg):
        print(f"{pkg} is available")
```

Example 5: Android/Pydroid Compatibility

```python
# For Android-based Python environments (Pydroid, Termux)
from pyputil.install import auto_install, PackageInstaller

# Critical: refresh_sys_path fixes import visibility issues
auto_install(
    mode="silent",
    virtual_env_only=False,
    use_safe_flags=False,  # --require-virtualenv not supported
    refresh_sys_path=True,  # CRITICAL for Android
    auto_user_flag=True,    # Install to user space
    debounce_seconds=10
)

# Now imports should work correctly
try:
    import numpy
except ImportError:
    # Force installation
    installer = PackageInstaller("numpy")
    installer.install(user=True)
    # Refresh manually if needed
    from pyputil.install import SysPathRefresher
    SysPathRefresher.refresh()
    import numpy
```

Example 6: Python Headers Installation

```python
# Install Python development headers for C extensions
from pyputil.install import install_python_headers

# For CI/CD environments
install_python_headers(
    verbose=True,
    backup_existing=False,
    clean_existing=True
)

# For Docker containers
install_python_headers(
    source="python.org",
    retries=5,
    retry_delay=3.0
)
```

Requirements

· Python 3.8+
· pip (for PackageInstaller)
· Internet connection (for PyPI and GitHub downloads)
· Optional: importlib.metadata (Python 3.8+)
· Optional: packaging for version comparison
· Optional: psutil for resource monitoring

Key Features Summary

Feature PackageInstaller AutoInstaller StdlibInstaller InstallUtil
Pip integration ✓ ✓ ✗ ✗
PyPI support ✓ ✓ ✗ ✗
Stdlib installation ✗ ✗ ✓ ✗
File installation ✗ ✗ ✗ ✓
Directory installation ✗ ✗ ✓ ✓
Automatic imports ✗ ✓ ✗ ✗
Version management ✓ ✓ ✓ ✗
Security controls ✗ ✓ ✗ ✗
Dependency analysis ✗ ✗ ✗ ✓
Headers installation ✗ ✗ ✗ ✗
Android compatibility ✓ ✓ ✓ ✓