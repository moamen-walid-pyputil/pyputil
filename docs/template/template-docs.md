# PyPutil Template - Professional Python Project Template Generator

## Overview

PyPutil Template is a comprehensive toolkit for generating production-ready Python project structures with all necessary configuration files, documentation, and CI/CD workflows. It follows industry best practices, PEP standards, and modern Python development workflows.

## Architecture

The system consists of the following core modules:

| Module | Purpose |
|--------|---------|
| `builder.py` | Complete project structure generator |
| `pyproject.py` | PEP 621-compliant pyproject.toml generator |
| `setup.py` | Legacy setup.py generator |
| `license.py` | LICENSE file generator for various open-source licenses |
| `readme.py` | Professional README.md generator |
| `gitignore.py` | Comprehensive .gitignore generator |
| `changelog.py` | Keep a Changelog format CHANGELOG.md generator |
| `github_actions.py` | GitHub Actions CI/CD workflow generator |
| `init.py` | __init__.py generator with import organization |

## Quick Start

```python
from pyputil.template import build_structure_template

# Create a complete project structure
result = build_structure_template(
    pathname="my_awesome_project",
    author="Jane Doe",
    description="An awesome Python package"
)

print(f"Project created at: {result['project_path']}")
print(f"Package: {result['package_name']} v{result['version']}")
```

---

1. Builder Module (builder.py)

Overview

The main entry point for creating complete Python project structures. Integrates all template generators to create a production-ready project in one command.

ProjectType Enum

Value Description
LIBRARY Standard Python library
CLI_APP Command-line application
WEB_APP Web application (Flask/FastAPI)
DATA_SCIENCE Data science project
ML_APP Machine learning project
EMPTY Minimal structure

StructureStats

Statistics about the generated project structure:

Attribute Description
directories_created List of created directories
files_created List of created files
warnings Warning messages
errors Error messages

Main Function

```python
def build_structure_template(
    pathname: Union[str, Path],
    package_name: Optional[str] = None,
    version: str = "0.1.0",
    description: str = "A Python package",
    author: str = "Your Name",
    author_email: str = "you@example.com",
    license_type: str = "MIT",
    python_requires: str = ">=3.8",
    dependencies: Optional[List[str]] = None,
    extras: Optional[Dict[str, List[str]]] = None,
    entry_points: Optional[Dict[str, List[str]]] = None,
    project_type: Union[str, ProjectType] = ProjectType.LIBRARY,
    create_tests: bool = True,
    create_docs: bool = True,
    create_examples: bool = True,
    create_scripts: bool = False,
    create_github_actions: bool = True,
    create_changelog: bool = True,
    create_gitignore: bool = True,
    create_setup: bool = True,
    create_init: bool = True,
    create_virtual_env: bool = False,
    use_poetry: bool = False,
    use_pytest: bool = True,
    use_black: bool = True,
    use_ruff: bool = True,
    use_mypy: bool = False,
    git_init: bool = True,
    pre_commit_hooks: bool = False,
    force_overwrite: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]
```

Examples

```python
from pyputil.template import build_structure_template, ProjectType

# Basic library project
result = build_structure_template(
    pathname="my_library",
    author="Jane Doe",
    description="A useful library"
)

# CLI application with entry points
build_structure_template(
    pathname="mycli",
    project_type=ProjectType.CLI_APP,
    entry_points={
        "console_scripts": ["mycli = mycli.main:cli"]
    },
    dependencies=["click", "rich"]
)

# Complete data science project
build_structure_template(
    pathname="data_analysis",
    project_type=ProjectType.DATA_SCIENCE,
    dependencies=["numpy", "pandas", "matplotlib"],
    extras={"ml": ["scikit-learn", "tensorflow"]},
    use_pytest=True,
    use_ruff=True,
    create_github_actions=True,
    verbose=True
)

# Minimal project structure
build_structure_template(
    pathname="simple_package",
    project_type=ProjectType.EMPTY,
    create_tests=False,
    create_docs=False,
    create_github_actions=False,
    create_changelog=False
)

# With Git and pre-commit hooks
build_structure_template(
    pathname="advanced_project",
    git_init=True,
    pre_commit_hooks=True,
    use_black=True,
    use_ruff=True,
    use_mypy=True
)
```

---

2. PyProject Module (pyproject.py)

Overview

Generates PEP 621-compliant pyproject.toml files with support for modern Python packaging standards, multiple build backends, and development tool configurations.

Enumerations

```python
class BuildBackend(str, Enum):
    SETUPTOOLS = "setuptools.build_meta"
    HATCHLING = "hatchling.build"
    POETRY = "poetry.core.masonry.api"
    FLIT = "flit_core.buildapi"
    PDM = "pdm.backend"

class LicenseType(str, Enum):
    MIT = "MIT"
    APACHE_2 = "Apache-2.0"
    BSD_3 = "BSD-3-Clause"
    GPL_3 = "GPL-3.0-or-later"
    ISC = "ISC"
    MPL_2 = "MPL-2.0"
    UNLICENSE = "Unlicense"
    PROPRIETARY = "Proprietary"

class DevelopmentStatus(str, Enum):
    PLANNING = "1 - Planning"
    PRE_ALPHA = "2 - Pre-Alpha"
    ALPHA = "3 - Alpha"
    BETA = "4 - Beta"
    STABLE = "5 - Production/Stable"
    MATURE = "6 - Mature"
    INACTIVE = "7 - Inactive"
```

PyProjectGenerator Class

```python
class PyProjectGenerator:
    """Generator for PEP 621 compliant pyproject.toml files."""
    
    def __init__(
        self,
        name: str = "my_package",
        version: str = "0.1.0",
        description: str = "A short description",
        authors: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None,
        optional_dependencies: Optional[Dict[str, List[str]]] = None,
        python_requires: str = ">=3.8",
        build_backend: BuildBackend = BuildBackend.SETUPTOOLS,
        license_type: Optional[LicenseType] = LicenseType.MIT,
        included_tools: Optional[List[str]] = None,
        verbose: bool = False,
    ) -> None
    
    def generate(self) -> str
    def write(self, path: Union[str, Path]) -> str
    def get_stats(self) -> Dict[str, Any]
```

Examples

```python
from pyputil.template import pyproject_template, write_pyproject, BuildBackend, LicenseType

# Basic usage
content = pyproject_template(
    name="my-package",
    version="1.0.0",
    description="A great package",
    authors=["Jane Doe <jane@example.com>"]
)

# Full configuration
content = pyproject_template(
    name="enterprise-lib",
    version="2.0.0",
    build_backend="hatchling.build",
    license_name="Apache-2.0",
    dependencies=["requests>=2.28.0", "click>=8.0.0"],
    optional_dependencies={
        "dev": ["pytest>=7.0.0", "black>=23.0.0"],
        "aws": ["boto3>=1.26.0"]
    },
    entry_points={"console_scripts": ["cli = lib.cli:main"]},
    include_tool_sections=["black", "ruff", "mypy"],
    urls={
        "Homepage": "https://example.com",
        "Repository": "https://github.com/user/repo"
    },
    keywords=["web", "api", "fast"]
)

# Dynamic version detection
content = pyproject_template(
    name="dynamic-version",
    version="0.1.0",  # Placeholder
    dynamic_fields=["version"],
    version_source="attr:package.__version__"
)

# Using the generator class directly
gen = PyProjectGenerator(
    name="myapp",
    version="1.0.0",
    build_backend=BuildBackend.HATCHLING,
    license_type=LicenseType.MIT,
    dependencies=["click>=8.0.0"],
    included_tools=["black", "ruff", "mypy"],
    verbose=True
)
gen.write("pyproject.toml")
stats = gen.get_stats()
print(f"Generated {stats['dependencies_count']} dependencies")
```

---

3. License Module (license.py)

Overview

Generates LICENSE files for various open-source licenses with support for SPDX identifiers and customizable copyright holders.

LicenseTemplate Class

Contains complete license texts for all supported licenses including:

· MIT, Apache-2.0, GPL-3.0, LGPL-3.0, AGPL-3.0
· BSD-2-Clause, BSD-3-Clause, ISC
· MPL-2.0, MIT-0, Unlicense, CC0-1.0
· BSL-1.0, Zlib

Examples

```python
from pyputil.template import license_template, write_license, detect_license_from_pyproject

# MIT license
mit_license = license_template(
    license_type="MIT",
    holder="Jane Doe",
    year=2024
)

# Apache 2.0 with organization
apache_license = license_template(
    license_type="Apache-2.0",
    holder="Jane Doe",
    organization="Example Corp",
    project_name="my-awesome-project",
    year=2024
)

# GPL v3 with custom notice
gpl_license = license_template(
    license_type="GPL-3.0",
    holder="Jane Doe",
    year=2024,
    custom_notice="Additional terms: You must preserve this notice."
)

# Write directly to file
write_license(
    "LICENSE",
    license_type="MIT",
    holder="Jane Doe",
    add_timestamp_comment=True
)

# Auto-detect from pyproject.toml
license_info = detect_license_from_pyproject()
if license_info:
    write_license(**license_info)
```

---

4. README Module (readme.py)

Overview

Generates professional README.md files with automatic table of contents, badge generation, and comprehensive documentation sections.

ReadmeBuilder Class

```python
class ReadmeBuilder:
    """A modular builder for generating README.md files."""
    
    def add_title(self, name: str, version: Optional[str] = None)
    def add_badges(self, badges: Dict[str, Union[str, Dict[str, str]]])
    def add_description(self, description: str)
    def add_installation(self, methods: Optional[Dict[str, str]] = None)
    def add_usage(self, examples: Optional[Dict[str, str]] = None)
    def add_features(self, features: Union[List[str], Dict[str, str]])
    def add_examples(self, examples: Dict[str, str])
    def add_tests(self, test_command: str = "pytest")
    def add_license(self, license_name: str, holder: str)
    def add_author(self, author: str, email: Optional[str] = None)
    def add_toc(self, sections: Optional[List[str]] = None)
    def build(self) -> str
```

Examples

```python
from pyputil.template import readme_template, write_readme, FeatureStyle

# Basic usage
readme = readme_template(
    name="My Awesome Package",
    description="A package that does amazing things",
    version="1.0.0",
    features=["Fast", "Easy to use", "Well documented"]
)

# Advanced usage with badges
readme = readme_template(
    name="Advanced Package",
    description="Enterprise-grade solution",
    badges={
        "python": "3.10",
        "license": "MIT",
        "coverage": {"label": "coverage", "value": "95%", "color": "green"}
    },
    installation_methods={
        "pip": "pip install advanced-package",
        "poetry": "poetry add advanced-package"
    },
    usage_examples={
        "Basic": "from advanced import Client\nclient = Client()",
        "Advanced": "client.process_large_data(file='data.csv')"
    },
    features={
        "High Performance": "Processes 1M records/second",
        "Type Hints": "Full type annotation support"
    },
    features_style=FeatureStyle.TABLE,
    author="Jane Doe",
    author_github="https://github.com/janedoe"
)

# Auto-detect from pyproject.toml
readme = readme_template(from_pyproject="pyproject.toml")

# Write directly
write_readme("README.md", name="My Project", description="A great project")
```

---

5. GitIgnore Module (gitignore.py)

Overview

Generates comprehensive .gitignore files with support for Python projects, IDEs, operating systems, frameworks, and package managers.

Enumerations

```python
class IDE(str, Enum):
    VSCODE = "vscode"
    PYCHARM = "pycharm"
    INTELLIJ = "intellij"
    VIM = "vim"
    EMACS = "emacs"
    SUBLIME = "sublime"
    ATOM = "atom"
    JUPYTER = "jupyter"
    SPYDER = "spyder"

class OS(str, Enum):
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"

class Framework(str, Enum):
    DJANGO = "django"
    FLASK = "flask"
    FASTAPI = "fastapi"
    PYTEST = "pytest"
    MYPY = "mypy"
    DOCKER = "docker"
    KUBERNETES = "kubernetes"

class PackageManager(str, Enum):
    PIP = "pip"
    POETRY = "poetry"
    PIPENV = "pipenv"
    PDM = "pdm"
    CONDA = "conda"
    UV = "uv"
```

Examples

```python
from pyputil.template import gitignore_template, write_gitignore, IDE, OS, Framework, PackageManager

# Basic usage
gitignore_template(project_name="myproject")

# Advanced with specific configurations
gitignore_template(
    project_name="myproject",
    include_ide=[IDE.VSCODE, IDE.PYCHARM],
    include_os=[OS.LINUX, OS.MACOS],
    include_frameworks=[Framework.DJANGO, Framework.DOCKER],
    include_package_managers=[PackageManager.POETRY],
    custom_patterns=["*.secret", "config.local.py"],
    verbose=True
)

# Minimal configuration (only Python)
gitignore_template(
    project_name="myproject",
    include_ide=False,
    include_os=False,
    include_frameworks=[],
    include_package_managers=[]
)

# Dry run to preview
gitignore_template(
    project_name="myproject",
    dry_run=True,
    verbose=True
)

# Write to specific location
write_gitignore(
    "./myproject/.gitignore",
    project_name="myproject",
    include_frameworks=[Framework.DJANGO]
)
```

---

6. Changelog Module (changelog.py)

Overview

Generates CHANGELOG.md files following the Keep a Changelog format with semantic versioning support.

Enumerations

```python
class ChangeType(str, Enum):
    ADDED = "added"
    CHANGED = "changed"
    DEPRECATED = "deprecated"
    REMOVED = "removed"
    FIXED = "fixed"
    SECURITY = "security"

class VersionStatus(str, Enum):
    RELEASED = "released"
    UNRELEASED = "unreleased"
    YANKED = "yanked"
```

Examples

```python
from pyputil.template import changelog_template, write_changelog

# Basic usage with versions
changelog = changelog_template(
    project_name="My Package",
    versions=[
        {
            "version": "1.0.0",
            "date": "2024-01-15",
            "added": ["Initial release", "Core functionality"],
            "fixed": ["Various bug fixes"]
        },
        {
            "version": "0.1.0",
            "date": "2024-01-01",
            "added": ["First beta release"]
        }
    ]
)

# With unreleased changes
changelog = changelog_template(
    project_name="My Package",
    repository_url="https://github.com/user/mypackage",
    unreleased_changes={
        "added": ["Async support", "New CLI commands"],
        "fixed": ["Memory leak in parser"],
        "changed": ["Updated documentation"]
    },
    keep_unreleased=True,
    add_comparison_links=True
)

# Complete example with all features
changelog = changelog_template(
    project_name="My Package",
    repository_url="https://github.com/user/mypackage",
    versions=[
        {
            "version": "1.0.0",
            "date": "2024-01-15",
            "added": ["Initial release"],
            "changed": ["Updated API docs"],
            "fixed": ["Bug fixes"],
            "security": ["Security patches"]
        }
    ],
    unreleased_changes={
        "added": ["New features in development"],
        "changed": ["API improvements"]
    },
    add_comparison_links=True,
    verbose=True
)

# Write directly
write_changelog(
    "CHANGELOG.md",
    project_name="My Project",
    versions=[{"version": "1.0.0", "added": ["Initial release"]}]
)
```

---

7. GitHub Actions Module (github_actions.py)

Overview

Generates GitHub Actions workflow files for CI/CD pipelines with support for matrix testing, linting, building, and publishing.

Enumerations

```python
class Trigger(str, Enum):
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    SCHEDULE = "schedule"
    WORKFLOW_DISPATCH = "workflow_dispatch"
    RELEASE = "release"

class Runner(str, Enum):
    UBUNTU_LATEST = "ubuntu-latest"
    UBUNTU_2204 = "ubuntu-22.04"
    MACOS_LATEST = "macos-latest"
    WINDOWS_LATEST = "windows-latest"

class CacheStrategy(str, Enum):
    PIP = "pip"
    POETRY = "poetry"
    PIPENV = "pipenv"
    PDM = "pdm"
    UV = "uv"

class Linter(str, Enum):
    RUFF = "ruff"
    BLACK = "black"
    ISORT = "isort"
    FLAKE8 = "flake8"
    PYLINT = "pylint"
    MYPY = "mypy"
    BANDIT = "bandit"
```

Examples

```python
from pyputil.template import github_actions_template, write_github_actions

# Basic CI workflow
github_actions_template(
    project_name="myproject",
    python_versions=["3.9", "3.10", "3.11", "3.12"],
    test_command="pytest tests/"
)

# Production workflow with all features
github_actions_template(
    project_name="myproject",
    python_versions=["3.10", "3.11", "3.12"],
    enable_linting=True,
    enable_type_checking=True,
    enable_testing=True,
    enable_building=True,
    enable_publishing=True,
    publish_to_pypi=True,
    secrets=["PYPI_TOKEN"],
    enable_coverage=True,
    enable_caching=True
)

# Poetry-based project
github_actions_template(
    project_name="myproject",
    cache_strategy="poetry",
    test_command="poetry run pytest tests/",
    coverage_command="poetry run pytest --cov=src --cov-report=xml"
)

# Cross-platform testing
github_actions_template(
    project_name="cross-platform-lib",
    runners=["ubuntu-latest", "macos-latest", "windows-latest"],
    python_versions=["3.10", "3.11"]
)

# Write to specific location
write_github_actions(
    ".github/workflows/ci.yml",
    project_name="myapp",
    python_versions=["3.11"],
    enable_testing=True
)
```

---

8. Init Module (init.py)

Overview

Generates __init__.py files with automatic import organization, duplicate handling, and alias generation.

Enumerations

```python
class ImportStyle(str, Enum):
    RELATIVE = "relative"
    ABSOLUTE = "absolute"
    BOTH = "both"

class AliasStrategy(str, Enum):
    DESCRIPTIVE = "descriptive"
    NUMERIC = "numeric"
    FOLDER_BASED = "folder_based"
    NONE = "none"

class ConflictResolution(str, Enum):
    ALIAS = "alias"
    SKIP = "skip"
    WARN = "warn"
    ERROR = "error"

class ValidationLevel(str, Enum):
    NONE = "none"
    BASIC = "basic"
    STRICT = "strict"
    FULL = "full"
```

Examples

```python
from pyputil.template import init_template, write_init

# Basic usage
init_template("./my_package")

# Advanced usage with exclusions
init_template(
    "./my_package",
    exclude_patterns=["*_test.py", "experimental/*"],
    use_aliases=True,
    validation_level="strict"
)

# With custom formatting
init_template(
    "./my_package",
    import_style="absolute",
    all_style="wildcard",
    add_metadata=True,
    generate_version=True
)

# Dry run to preview changes
init_template(
    "./my_package",
    dry_run=True,
    verbose=True
)

# Write to specific location
write_init(
    "./my_package/__init__.py",
    root="./my_package",
    exclude_patterns=["test_*"]
)
```

---

9. Setup Module (setup.py)

Overview

Generates legacy setup.py files with automatic dependency detection and version management.

Enumerations

```python
class VersionSource(str, Enum):
    STATIC = "static"
    FILE = "file"
    GIT = "git"
    INIT = "init"
    AUTO = "auto"
```

Examples

```python
from pyputil.template import setup_template, write_setup, VersionSource

# Basic usage
setup_template(
    package_name="mypackage",
    version="1.0.0",
    author="Jane Doe",
    author_email="jane@example.com"
)

# Advanced usage with auto-detection
setup_template(
    package_name="mypackage",
    package_path="./src/mypackage",
    version_source=VersionSource.GIT,
    entry_points={
        "console_scripts": ["mycli = mypackage.cli:main"]
    }
)

# With extras
setup_template(
    package_name="mypackage",
    install_requires=["requests>=2.28.0"],
    extras_require={
        "dev": ["pytest", "black"],
        "ml": ["numpy", "pandas"]
    }
)

# Using git version
setup_template(
    package_name="mypackage",
    version_source=VersionSource.GIT
)

# Write directly
write_setup("setup.py", package_name="mypackage", version="1.0.0")
```

---

Complete Example

```python
#!/usr/bin/env python3
"""Complete example using PyPutil Template."""

from pyputil.template import build_structure_template, ProjectType

# Generate a complete data science project
result = build_structure_template(
    pathname="ml_project",
    project_type=ProjectType.ML_APP,
    package_name="mlproject",
    version="0.1.0",
    description="Machine learning project for data analysis",
    author="Jane Doe",
    author_email="jane@example.com",
    license_type="MIT",
    python_requires=">=3.9",
    dependencies=[
        "numpy>=1.21.0",
        "pandas>=1.3.0",
        "scikit-learn>=1.0.0",
        "matplotlib>=3.4.0"
    ],
    extras={
        "dev": ["pytest>=7.0.0", "black>=23.0.0", "ruff>=0.1.0"],
        "dl": ["tensorflow>=2.10.0", "torch>=1.12.0"]
    },
    entry_points={
        "console_scripts": ["mltrain = mlproject.cli:train"]
    },
    create_tests=True,
    create_docs=True,
    create_examples=True,
    create_github_actions=True,
    create_changelog=True,
    git_init=True,
    pre_commit_hooks=True,
    use_poetry=False,
    use_pytest=True,
    use_black=True,
    use_ruff=True,
    use_mypy=True,
    verbose=True
)

print(f"Project created: {result['project_path']}")
print(f"Package: {result['package_name']} v{result['version']}")
print(f"Files created: {result['stats'].total_files}")
print(f"Directories: {result['stats'].total_directories}")
```

---

Requirements

· Python 3.8+
· Standard library only for core functionality
· Optional: tomli for pyproject.toml support (Python <3.11)
· Optional: black for code formatting
· Optional: pyyaml for YAML serialization

Key Features Summary

Feature builder pyproject license readme gitignore changelog github_actions init setup
Project structure ✓ ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✗
Package metadata ✓ ✓ ✗ ✓ ✗ ✓ ✗ ✓ ✓
License generation ✗ ✗ ✓ ✗ ✗ ✗ ✗ ✗ ✗
README generation ✗ ✗ ✗ ✓ ✗ ✗ ✗ ✗ ✗
.gitignore ✗ ✗ ✗ ✗ ✓ ✗ ✗ ✗ ✗
Changelog ✗ ✗ ✗ ✗ ✗ ✓ ✗ ✗ ✗
CI/CD workflows ✗ ✗ ✗ ✗ ✗ ✗ ✓ ✗ ✗
init.py ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✓ ✗
setup.py ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✗ ✓
Dry run support ✓ ✓ ✓ ✓ ✓ ✓ ✓ ✓ ✓
Statistics tracking ✓ ✓ ✓ ✗ ✓ ✓ ✓ ✓ ✗