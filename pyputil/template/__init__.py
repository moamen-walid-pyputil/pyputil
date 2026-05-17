#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PypUtil Template - Professional Python Project Template Generator
================================================================

A comprehensive toolkit for generating production-ready Python project structures
with all necessary configuration files, documentation, and CI/CD workflows.

This package provides a collection of template generators that follow industry
best practices, PEP standards, and modern Python development workflows. Each
generator is highly configurable, well-documented, and designed to work
seamlessly with the others.

Subpackages and Modules
-----------------------
The package is organized into several modules, each responsible for generating
a specific type of file or structure:

- **init**: __init__.py files with intelligent import organization
- **pyproject**: PEP 621-compliant pyproject.toml files
- **license**: LICENSE files for various open-source licenses
- **readme**: Professional README.md files with badges and documentation
- **setup**: Legacy setup.py files with automatic dependency detection
- **gitignore**: Comprehensive .gitignore files for Python projects
- **changelog**: Keep a Changelog format CHANGELOG.md files
- **github_actions**: GitHub Actions CI/CD workflows
- **builder**: Complete project structure generator

Quick Start
-----------
Generate a complete project structure with one command:

>>> from pyputil.template import build_structure_template
>>> 
>>> # Create a new Python project
>>> result = build_structure_template(
...     pathname="my_awesome_project",
...     author="Jane Doe",
...     description="An awesome Python package"
... )
>>> 
>>> print(f"Project created at: {result['project_path']}")

Generate individual files:

>>> from pyputil.template import write_pyproject, write_license, write_readme
>>> 
>>> # Generate pyproject.toml
>>> write_pyproject(
...     "pyproject.toml",
...     name="myproject",
...     version="1.0.0",
...     description="My awesome project"
... )
>>> 
>>> # Generate LICENSE
>>> write_license(
...     "LICENSE",
...     license_type="MIT",
...     holder="Jane Doe"
... )
>>> 
>>> # Generate README.md
>>> write_readme(
...     "README.md",
...     name="My Project",
...     description="An awesome project"
... )

Advanced Configuration
----------------------
Each generator supports extensive configuration options:

>>> from pyputil.template import (
...     write_gitignore,
...     GitignoreIDE,
...     GitignoreOS,
...     GitignoreFramework
... )
>>> 
>>> # Advanced .gitignore with specific configurations
>>> write_gitignore(
...     ".gitignore",
...     project_name="myproject",
...     include_ide=[GitignoreIDE.VSCODE, GitignoreIDE.PYCHARM],
...     include_os=[GitignoreOS.LINUX, GitignoreOS.MACOS],
...     include_frameworks=[
            GitignoreFramework.DJANGO,
            GitignoreFramework.DOCKER
        ],
...     include_package_managers=["poetry"],
...     custom_patterns=["*.secret", "config.local.py"]
... )

Integration with CI/CD
----------------------
Generate GitHub Actions workflows for continuous integration:

>>> from .template import write_github_actions
>>> 
>>> write_github_actions(
...     ".github/workflows/python.yml",
...     project_name="myproject",
...     python_versions=["3.10", "3.11", "3.12"],
...     enable_testing=True,
...     enable_linting=True,
...     enable_type_checking=True,
...     enable_building=True,
...     enable_publishing=True
... )

Complete Example
----------------
Here's a complete example that generates a full project structure:

>>> from pyputil.template import build_structure_template
>>> 
>>> # Generate a complete data science project
>>> result = build_structure_template(
...     pathname="ml_project",
...     project_type="ml",
...     package_name="mlproject",
...     version="0.1.0",
...     description="Machine learning project",
...     author="Jane Doe",
...     author_email="jane@example.com",
...     license_type="MIT",
...     python_requires=">=3.9",
...     dependencies=[
...         "numpy>=1.21.0",
...         "pandas>=1.3.0",
...         "scikit-learn>=1.0.0",
...         "matplotlib>=3.4.0"
...     ],
...     extras={
...         "dev": ["pytest>=7.0.0", "black>=23.0.0", "ruff>=0.1.0"],
...         "dl": ["tensorflow>=2.10.0", "torch>=1.12.0"]
...     },
...     entry_points={
...         "console_scripts": ["mltrain = mlproject.cli:train"]
...     },
...     create_tests=True,
...     create_docs=True,
...     create_examples=True,
...     create_github_actions=True,
...     create_changelog=True,
...     git_init=True,
...     pre_commit_hooks=True,
...     use_poetry=False,
...     use_pytest=True,
...     use_black=True,
...     use_ruff=True,
...     use_mypy=True,
...     verbose=True
... )
>>> 
>>> print(f"Project created: {result['project_path']}")
>>> print(f"Package: {result['package_name']} v{result['version']}")
>>> print(f"Files created: {result['stats'].total_files}")
>>> print(f"Directories: {result['stats'].total_directories}")

See Also
--------
- `pyputil.template.init`: __init__.py file generator
- `pyputil.template.pyproject`: pyproject.toml generator
- `pyputil.template.license`: LICENSE file generator
- `pyputil.template.readme`: README.md generator
- `pyputil.template.setup`: setup.py generator
- `pyputil.template.gitignore`: .gitignore generator
- `pyputil.template.changelog`: CHANGELOG.md generator
- `pyputil.template.github_actions`: GitHub Actions workflow generator
- `pyputil.template.builder`: Project structure builder

Notes
-----
- All generators follow PEP 621 and modern Python packaging standards
- All functions support dry-run mode for testing
- Comprehensive error handling with clear messages
- Statistics tracking for all generation operations
- Support for both absolute and relative imports
- Type hints throughout for better IDE support

References
----------
- PEP 621: Storing project metadata in pyproject.toml
- Keep a Changelog: https://keepachangelog.com/
- Semantic Versioning: https://semver.org/
- GitHub Actions: https://docs.github.com/en/actions
- pytest: https://docs.pytest.org/
- Black: https://black.readthedocs.io/
- Ruff: https://docs.astral.sh/ruff/
"""

from .init import (
    init_template,
    write_init,
    InitFileGenerator,
    ValidationLevel as InitValidationLevel,
    ImportStyle as InitImportStyle,
    ConflictResolution as InitConflictResolution,
    AliasStrategy as InitAliasStrategy,
)
from .pyproject import (
    pyproject_template,
    write_pyproject,
)
from .license import (
    license_template,
    write_license,
    detect_license_from_pyproject,
    LICENSE_SPDX,
    LicenseTemplate,
)
from .readme import (
    readme_template,
    write_readme,
    FeatureStyle as ReadmeFeatureStyle,
    ReadmeBuilder,
)
from .setup import (
    setup_template,
    write_setup,
    VersionSource as SetupVersionSource,
    SetupGenerator,
)
from .gitignore import (
    gitignore_template,
    write_gitignore,
    GitignoreGenerator,
    IDE as GitignoreIDE,
    OS as GitignoreOS,
    Framework as GitignoreFramework,
    PackageManager as GitignorePackageManager
)
from .changelog import (
    changelog_template,
    write_changelog,
    ChangelogGenerator,
    VersionRelease as ChangelogVersionRelease,
    ChangeType as ChangelogChangeType,
    VersionStatus as ChangelogVersionStatus,
)
from .github_actions import (
    github_actions_template,
    write_github_actions,
    GitHubActionsGenerator,
    Trigger as GitHubActionsTrigger,
    Linter as GitHubActionsLinter,
    Runner as GitHubActionsRunner,
    CacheStrategy as GitHubActionsCacheStrategy,
    PythonVersion as GitHubActionsPythonVersion,
)
from .builder import (
    build_structure_template,
    ProjectType as BuilderProjectType,
    StructureStats as BuilderStructureStats,
)


# Public API - Complete list of all exported symbols
__all__ = [
    # =========================================================================
    # init module - __init__.py generator
    # =========================================================================
    "init_template",
    "write_init",
    "InitFileGenerator",
    "InitValidationLevel",
    "InitImportStyle",
    "InitConflictResolution",
    "InitAliasStrategy",
    
    # =========================================================================
    # pyproject module - pyproject.toml generator
    # =========================================================================
    "pyproject_template",
    "write_pyproject",
    
    # =========================================================================
    # license module - LICENSE generator
    # =========================================================================
    "license_template",
    "write_license",
    "detect_license_from_pyproject",
    "LICENSE_SPDX",
    "LicenseTemplate",
    
    # =========================================================================
    # readme module - README.md generator
    # =========================================================================
    "readme_template",
    "write_readme",
    "ReadmeFeatureStyle",
    "ReadmeBuilder",
    
    # =========================================================================
    # setup module - setup.py generator
    # =========================================================================
    "setup_template",
    "write_setup",
    "SetupVersionSource",
    "SetupGenerator",
    
    # =========================================================================
    # gitignore module - .gitignore generator
    # =========================================================================
    "gitignore_template",
    "write_gitignore",
    "GitignoreGenerator",
    "GitignoreIDE",
    "GitignoreOS",
    "GitignoreFramework",
    "GitignorePackageManager",
    
    # =========================================================================
    # changelog module - CHANGELOG.md generator
    # =========================================================================
    "changelog_template",
    "write_changelog",
    "ChangelogGenerator",
    "ChangelogVersionRelease",
    "ChangelogChangeType",
    "ChangelogVersionStatus",
    
    # =========================================================================
    # github_actions module - GitHub Actions workflow generator
    # =========================================================================
    "github_actions_template",
    "write_github_actions",
    "GitHubActionsGenerator",
    "GitHubActionsTrigger",
    "GitHubActionsLinter",
    "GitHubActionsRunner",
    "GitHubActionsCacheStrategy",
    "GitHubActionsPythonVersion",
    
    # =========================================================================
    # builder module - Complete project structure generator
    # =========================================================================
    "build_structure_template",
    "BuilderProjectType",
    "BuilderStructureStats",
]


from ..api import clean
clean(expose=__all__)