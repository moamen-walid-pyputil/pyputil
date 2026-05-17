#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Project structure generator for Python packages.

This module provides a comprehensive function to create a complete Python
package structure with all necessary configuration files, documentation,
testing setup, and CI/CD workflows. It integrates all template generators
to create a production-ready project structure in one command.

Examples
--------
>>> from pyputil.template import build_structure_template
>>> 
>>> # Basic usage
>>> build_structure_template("my_awesome_package")
>>> 
>>> # Advanced with all options
>>> build_structure_template(
...     pathname="myproject",
...     package_name="myproject",
...     version="1.0.0",
...     description="An awesome Python package",
...     author="Jane Doe",
...     author_email="jane@example.com",
...     license_type="MIT",
...     python_requires=">=3.9",
...     dependencies=["requests", "click"],
...     extras={"dev": ["pytest", "black"]},
...     create_github_actions=True,
...     create_changelog=True,
...     verbose=True
... )
"""

from pathlib import Path
from typing import Union, Optional, List, Dict, Any
from datetime import datetime
import warnings
import shutil
import sys
import os
from enum import Enum

# Import all template generators
from .readme import write_readme
from .init import write_init
from .setup import write_setup
from .gitignore import write_gitignore
from .pyproject import write_pyproject
from .license import write_license
from .changelog import write_changelog
from .github_actions import write_github_actions


class ProjectType(str, Enum):
    """Project type classifications."""
    LIBRARY = "library"
    CLI_APP = "cli"
    WEB_APP = "web"
    DATA_SCIENCE = "data-science"
    ML_APP = "ml"
    EMPTY = "empty"


class StructureStats:
    """Statistics about the generated project structure."""
    
    def __init__(self):
        self.directories_created: List[str] = []
        self.files_created: List[str] = []
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.start_time: float = 0.0
        self.end_time: float = 0.0
    
    @property
    def total_directories(self) -> int:
        return len(self.directories_created)
    
    @property
    def total_files(self) -> int:
        return len(self.files_created)
    
    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0
    
    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    @property
    def elapsed_time(self) -> float:
        if self.end_time and self.start_time:
            return self.end_time - self.start_time
        return 0.0
    
    def __str__(self) -> str:
        lines = [
            "=" * 60,
            "Project Structure Generation Statistics",
            "=" * 60,
            f"Directories created: {self.total_directories}",
            f"Files created: {self.total_files}",
            f"Time elapsed: {self.elapsed_time:.2f}s",
        ]
        
        if self.warnings:
            lines.append(f"\nWarnings ({len(self.warnings)}):")
            for warning in self.warnings[:5]:
                lines.append(f"  WARNING:  {warning}")
            if len(self.warnings) > 5:
                lines.append(f"  ... and {len(self.warnings) - 5} more")
        
        if self.errors:
            lines.append(f"\nErrors ({len(self.errors)}):")
            for error in self.errors:
                lines.append(f"  ERROR: {error}")
        
        return "\n".join(lines)


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
    show_warnings: bool = True,
) -> Dict[str, Any]:
    """
    Generate a complete Python project structure with all configuration files.
    
    This function creates a production-ready Python package structure with
    all necessary files including pyproject.toml, setup.py, README, LICENSE,
    .gitignore, GitHub Actions workflows, and more. It integrates all template
    generators to create a comprehensive project setup.
    
    Parameters
    ----------
    pathname : Union[str, Path]
        Path where the project will be created. Can be a directory name
        or full path. The function will create the directory if it doesn't exist.
        
    package_name : Optional[str], optional
        Name of the Python package. If not provided, uses the basename of pathname.
        Should follow PEP 508 naming conventions (lowercase, hyphens allowed).
        
    version : str, default="0.1.0"
        Initial version of the package following semantic versioning.
        
    description : str, default="A Python package"
        Short description of the project.
        
    author : str, default="Your Name"
        Author name for copyright and metadata.
        
    author_email : str, default="you@example.com"
        Author email for contact information.
        
    license_type : str, default="MIT"
        License type. Supports: MIT, Apache-2.0, GPL-3.0, BSD-3-Clause, ISC, etc.
        
    python_requires : str, default=">=3.8"
        Python version requirement.
        
    dependencies : Optional[List[str]], optional
        List of package dependencies. Each should follow PEP 508 format.
        
    extras : Optional[Dict[str, List[str]]], optional
        Optional dependencies for extra features. Example:
        {"dev": ["pytest", "black"], "ml": ["numpy", "pandas"]}
        
    entry_points : Optional[Dict[str, List[str]]], optional
        Console scripts and entry points. Example:
        {"console_scripts": ["mycli = mypackage.cli:main"]}
        
    project_type : Union[str, ProjectType], default="library"
        Type of project. Affects the generated structure and files:
        - "library": Standard Python library
        - "cli": Command-line application
        - "web": Web application (Flask/FastAPI)
        - "data-science": Data science project
        - "ml": Machine learning project
        - "empty": Minimal structure
        
    create_tests : bool, default=True
        Whether to create tests directory with sample test file.
        
    create_docs : bool, default=True
        Whether to create docs directory with initial documentation.
        
    create_examples : bool, default=True
        Whether to create examples directory with sample usage.
        
    create_scripts : bool, default=False
        Whether to create scripts directory for utility scripts.
        
    create_github_actions : bool, default=True
        Whether to create GitHub Actions workflow for CI/CD.
        
    create_changelog : bool, default=True
        Whether to create CHANGELOG.md file.
        
    create_gitignore : bool, default=True
        Whether to create .gitignore file.
        
    create_setup : bool, default=True
        Whether to create setup.py file (legacy support).
        
    create_init : bool, default=True
        Whether to create __init__.py files in packages.
        
    create_virtual_env : bool, default=False
        Whether to create a virtual environment after structure creation.
        
    use_poetry : bool, default=False
        Whether to configure for Poetry dependency management.
        Affects pyproject.toml and dependency caching in CI.
        
    use_pytest : bool, default=True
        Whether to configure for pytest testing framework.
        
    use_black : bool, default=True
        Whether to configure for Black code formatter.
        
    use_ruff : bool, default=True
        Whether to configure for Ruff linter.
        
    use_mypy : bool, default=False
        Whether to configure for mypy type checker.
        
    git_init : bool, default=True
        Whether to initialize Git repository.
        
    pre_commit_hooks : bool, default=False
        Whether to set up pre-commit hooks for code quality.
        
    force_overwrite : bool, default=False
        Whether to overwrite existing files and directories.
        
    verbose : bool, default=False
        Whether to print detailed information during generation.
        
    show_warnings : bool, default=True
        Whether to show warning messages.
        
    Returns
    -------
    Dict[str, Any]
        Dictionary containing:
        - "project_path": Path to the created project
        - "stats": StructureStats object with generation statistics
        - "package_name": Name of the created package
        - "version": Version of the created package
        
    Raises
    ------
    FileExistsError
        If the project directory already exists and force_overwrite is False.
    PermissionError
        If the directory cannot be created or accessed.
    ValueError
        If configuration parameters are invalid.
        
    Examples
    --------
    Basic library project:
    >>> result = build_structure_template(
    ...     pathname="my_library",
    ...     author="Jane Doe",
    ...     description="A useful library"
    ... )
    >>> print(f"Created at: {result['project_path']}")
    
    CLI application with entry points:
    >>> build_structure_template(
    ...     pathname="mycli",
    ...     project_type="cli",
    ...     entry_points={
    ...         "console_scripts": ["mycli = mycli.main:cli"]
    ...     },
    ...     dependencies=["click", "rich"]
    ... )
    
    Complete data science project:
    >>> build_structure_template(
    ...     pathname="data_analysis",
    ...     project_type="data-science",
    ...     dependencies=["numpy", "pandas", "matplotlib"],
    ...     extras={"ml": ["scikit-learn", "tensorflow"]},
    ...     use_pytest=True,
    ...     use_ruff=True,
    ...     create_github_actions=True,
    ...     verbose=True
    ... )
    
    Minimal project structure:
    >>> build_structure_template(
    ...     pathname="simple_package",
    ...     project_type="empty",
    ...     create_tests=False,
    ...     create_docs=False,
    ...     create_github_actions=False,
    ...     create_changelog=False
    ... )
    
    With Git and pre-commit hooks:
    >>> build_structure_template(
    ...     pathname="advanced_project",
    ...     git_init=True,
    ...     pre_commit_hooks=True,
    ...     use_black=True,
    ...     use_ruff=True,
    ...     use_mypy=True
    ... )
    
    Notes
    -----
    - Creates a complete project structure ready for development
    - Integrates all template generators (pyproject, license, readme, etc.)
    - Supports multiple project types with appropriate configurations
    - Includes testing setup with pytest
    - Configures code quality tools (black, ruff, mypy)
    - Sets up GitHub Actions for CI/CD
    - Initializes Git repository with initial commit
    - Creates virtual environment optionally
    - Provides detailed statistics about created files and directories
    
    See Also
    --------
    pyproject_template : Generate pyproject.toml
    license_template : Generate LICENSE file
    readme_template : Generate README.md
    setup_template : Generate setup.py
    init_template : Generate __init__.py
    gitignore_template : Generate .gitignore
    github_actions_template : Generate GitHub Actions workflow
    changelog_template : Generate CHANGELOG.md
    """
    
    import time
    
    # Initialize statistics
    stats = StructureStats()
    stats.start_time = time.time()
    
    # Validate and normalize path
    path = Path(pathname).resolve()
    project_name = package_name or path.stem
    normalized_package = project_name.replace("-", "_")
    
    if verbose:
        print(f"[INFO] Creating project structure at: {path}")
        print(f"[INFO] Package name: {project_name}")
        print(f"[INFO] Python version: {python_requires}")
    
    # Check if directory exists
    if path.exists() and not force_overwrite:
        raise FileExistsError(
            f"Directory '{path}' already exists. "
            f"Use force_overwrite=True to overwrite."
        )
    
    # Create project directory
    try:
        path.mkdir(parents=True, exist_ok=force_overwrite)
        stats.directories_created.append(str(path))
        if verbose:
            print(f"[INFO] Created project directory: {path}")
    except PermissionError as e:
        stats.errors.append(str(e))
        raise PermissionError(f"Cannot create directory '{path}': {e}")
    
    # Prepare dependencies based on project type
    deps = dependencies or []
    extras_dict = extras or {}
    
    if project_type == ProjectType.CLI_APP and "click" not in deps:
        deps.append("click>=8.0.0")
        if verbose:
            print("[INFO] Added click for CLI application")
    
    if project_type == ProjectType.WEB_APP:
        if "flask" not in deps and "fastapi" not in deps:
            deps.append("flask>=2.0.0")
            if verbose:
                print("[INFO] Added Flask for web application")
    
    if project_type == ProjectType.DATA_SCIENCE:
        if "numpy" not in deps:
            deps.append("numpy>=1.21.0")
        if "pandas" not in deps:
            deps.append("pandas>=1.3.0")
        if verbose:
            print("[INFO] Added numpy and pandas for data science project")
    
    if project_type == ProjectType.ML_APP:
        if "scikit-learn" not in deps:
            deps.append("scikit-learn>=1.0.0")
        if verbose:
            print("[INFO] Added scikit-learn for machine learning project")
    
    # Add test dependencies if pytest is used
    if use_pytest:
        if "dev" not in extras_dict:
            extras_dict["dev"] = []
        if "pytest>=7.0.0" not in extras_dict["dev"]:
            extras_dict["dev"].append("pytest>=7.0.0")
        if "pytest-cov>=4.0.0" not in extras_dict["dev"]:
            extras_dict["dev"].append("pytest-cov>=4.0.0")
    
    # Add code quality tools
    if use_black and "dev" in extras_dict:
        if "black>=23.0.0" not in extras_dict["dev"]:
            extras_dict["dev"].append("black>=23.0.0")
    
    if use_ruff and "dev" in extras_dict:
        if "ruff>=0.1.0" not in extras_dict["dev"]:
            extras_dict["dev"].append("ruff>=0.1.0")
    
    if use_mypy and "dev" in extras_dict:
        if "mypy>=1.0.0" not in extras_dict["dev"]:
            extras_dict["dev"].append("mypy>=1.0.0")
    
    # Create package directory
    package_dir = path / normalized_package
    package_dir.mkdir(exist_ok=force_overwrite)
    stats.directories_created.append(str(package_dir))
    
    if create_init:
        # Create __init__.py with version
        init_content = f'"""\n{project_name} package.\n\n{description}\n"""\n\n__version__ = "{version}"\n'
        init_file = package_dir / "__init__.py"
        init_file.write_text(init_content, encoding="utf-8")
        stats.files_created.append(str(init_file))
        if verbose:
            print(f"[INFO] Created: {init_file}")
    
    # Create main module file
    main_file = package_dir / "main.py"
    main_content = f'''"""
Main module for {project_name}.

{description}
"""

def main() -> None:
    """Main entry point for the package."""
    print("Hello from {project_name} v{version}")


if __name__ == "__main__":
    main()
'''
    main_file.write_text(main_content, encoding="utf-8")
    stats.files_created.append(str(main_file))
    
    # Create tests directory
    if create_tests:
        tests_dir = path / "tests"
        tests_dir.mkdir(exist_ok=force_overwrite)
        stats.directories_created.append(str(tests_dir))
        
        # Create test file
        test_file = tests_dir / f"test_{normalized_package}.py"
        test_content = f'''"""
Tests for {project_name}.
"""

import pytest
from {normalized_package} import main


def test_version():
    """Test package version."""
    from {normalized_package} import __version__
    assert __version__ == "{version}"


def test_main():
    """Test main function."""
    # Add your tests here
    assert True
'''
        test_file.write_text(test_content, encoding="utf-8")
        stats.files_created.append(str(test_file))
        
        # Create conftest.py
        conftest_file = tests_dir / "conftest.py"
        conftest_content = '''"""
Pytest configuration file.
"""

import pytest
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))
'''
        conftest_file.write_text(conftest_content, encoding="utf-8")
        stats.files_created.append(str(conftest_file))
    
    # Create docs directory
    if create_docs:
        docs_dir = path / "docs"
        docs_dir.mkdir(exist_ok=force_overwrite)
        stats.directories_created.append(str(docs_dir))
        
        # Create index.rst
        index_file = docs_dir / "index.rst"
        index_content = f'''.. {project_name} documentation master file

Welcome to {project_name}'s documentation!
============================================

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   usage
   api

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
'''
        index_file.write_text(index_content, encoding="utf-8")
        stats.files_created.append(str(index_file))
    
    # Create examples directory
    if create_examples:
        examples_dir = path / "examples"
        examples_dir.mkdir(exist_ok=force_overwrite)
        stats.directories_created.append(str(examples_dir))
        
        example_file = examples_dir / "basic_usage.py"
        example_content = f'''"""
Basic usage example for {project_name}.
"""

from {normalized_package} import main

# Basic usage
main.main()

# Your code here
'''
        example_file.write_text(example_content, encoding="utf-8")
        stats.files_created.append(str(example_file))
    
    # Create scripts directory
    if create_scripts:
        scripts_dir = path / "scripts"
        scripts_dir.mkdir(exist_ok=force_overwrite)
        stats.directories_created.append(str(scripts_dir))
    
    # Generate README.md
    try:
        readme_path = path / "README.md"
        write_readme(
            path=readme_path,
            name=project_name,
            description=description,
            version=version,
            features=["Easy to use", "Well documented", "Actively maintained"],
            author=author,
            license_name=license_type,
            from_pyproject=False,
            verbose=False
        )
        stats.files_created.append(str(readme_path))
        if verbose:
            print(f"[INFO] Created: {readme_path}")
    except Exception as e:
        stats.warnings.append(f"Failed to create README: {e}")
        if show_warnings:
            warnings.warn(f"Failed to create README: {e}", UserWarning)
    
    # Generate LICENSE
    try:
        license_path = path / "LICENSE"
        write_license(
            path=license_path,
            license_type=license_type,
            holder=author,
            year=datetime.now().year,
            verbose=False
        )
        stats.files_created.append(str(license_path))
        if verbose:
            print(f"[INFO] Created: {license_path}")
    except Exception as e:
        stats.warnings.append(f"Failed to create LICENSE: {e}")
        if show_warnings:
            warnings.warn(f"Failed to create LICENSE: {e}", UserWarning)
    
    # Generate pyproject.toml
    try:
        pyproject_path = path / "pyproject.toml"
        write_pyproject(
            path=pyproject_path,
            name=project_name,
            version=version,
            description=description,
            authors=[f"{author} <{author_email}>"],
            dependencies=deps,
            optional_dependencies=extras_dict,
            python_requires=python_requires,
            build_backend="poetry.core.masonry.api" if use_poetry else "setuptools.build_meta",
            license_name=license_type,
            verbose=False
        )
        stats.files_created.append(str(pyproject_path))
        if verbose:
            print(f"[INFO] Created: {pyproject_path}")
    except Exception as e:
        stats.warnings.append(f"Failed to create pyproject.toml: {e}")
        if show_warnings:
            warnings.warn(f"Failed to create pyproject.toml: {e}", UserWarning)
    
    # Generate setup.py
    if create_setup:
        try:
            setup_path = path / "setup.py"
            write_setup(
                path=setup_path,
                package_name=project_name,
                version=version,
                description=description,
                author=author,
                author_email=author_email,
                license_name=license_type,
                python_requires=python_requires,
                install_requires=deps,
                extras_require=extras_dict,
                entry_points=entry_points,
                output_dir=str(path),
                force_overwrite=force_overwrite,
                verbose=False
            )
            stats.files_created.append(str(setup_path))
            if verbose:
                print(f"[INFO] Created: {setup_path}")
        except Exception as e:
            stats.warnings.append(f"Failed to create setup.py: {e}")
            if show_warnings:
                warnings.warn(f"Failed to create setup.py: {e}", UserWarning)
    
    # Generate .gitignore
    if create_gitignore:
        try:
            gitignore_path = path / ".gitignore"
            write_gitignore(
                path=gitignore_path,
                project_name=project_name,
                include_python=True,
                include_ide=True,
                include_os=True,
                include_package_managers=["poetry"] if use_poetry else ["pip"],
                verbose=False
            )
            stats.files_created.append(str(gitignore_path))
            if verbose:
                print(f"[INFO] Created: {gitignore_path}")
        except Exception as e:
            stats.warnings.append(f"Failed to create .gitignore: {e}")
            if show_warnings:
                warnings.warn(f"Failed to create .gitignore: {e}", UserWarning)
    
    # Generate CHANGELOG.md
    if create_changelog:
        try:
            changelog_path = path / "CHANGELOG.md"
            write_changelog(
                path=changelog_path,
                project_name=project_name,
                versions=[
                    {
                        "version": version,
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "added": ["Initial project structure"],
                    }
                ],
                verbose=False
            )
            stats.files_created.append(str(changelog_path))
            if verbose:
                print(f"[INFO] Created: {changelog_path}")
        except Exception as e:
            stats.warnings.append(f"Failed to create CHANGELOG: {e}")
            if show_warnings:
                warnings.warn(f"Failed to create CHANGELOG: {e}", UserWarning)
    
    # Generate GitHub Actions workflow
    if create_github_actions:
        try:
            actions_path = path / ".github/workflows/python.yml"
            write_github_actions(
                path=actions_path,
                project_name=project_name,
                python_versions=["3.9", "3.10", "3.11", "3.12"],
                enable_testing=True,
                enable_linting=use_ruff or use_black,
                enable_type_checking=use_mypy,
                enable_building=True,
                enable_publishing=False,
                enable_coverage=True,
                enable_caching=True,
                cache_strategy="poetry" if use_poetry else "pip",
                test_command="pytest tests/" if use_pytest else "python -m unittest discover",
                verbose=False
            )
            stats.files_created.append(str(actions_path))
            if verbose:
                print(f"[INFO] Created: {actions_path}")
        except Exception as e:
            stats.warnings.append(f"Failed to create GitHub Actions workflow: {e}")
            if show_warnings:
                warnings.warn(f"Failed to create GitHub Actions workflow: {e}", UserWarning)
    
    # Initialize Git repository
    if git_init:
        try:
            import subprocess
            original_dir = Path.cwd()
            try:
                os.chdir(path)
                subprocess.run(["git", "init"], check=True, capture_output=True)
                subprocess.run(["git", "add", "."], check=True, capture_output=True)
                subprocess.run(
                    ["git", "commit", "-m", f"Initial commit for {project_name} v{version}"],
                    check=True,
                    capture_output=True
                )
                if verbose:
                    print("[INFO] Git repository initialized with initial commit")
            finally:
                os.chdir(original_dir)
        except subprocess.CalledProcessError as e:
            stats.warnings.append(f"Git initialization failed: {e}")
            if show_warnings:
                warnings.warn(f"Git initialization failed: {e}", UserWarning)
        except Exception as e:
            stats.warnings.append(f"Git initialization error: {e}")
            if show_warnings:
                warnings.warn(f"Git initialization error: {e}", UserWarning)
    
    # Create virtual environment
    if create_virtual_env:
        try:
            import subprocess
            original_dir = Path.cwd()
            try:
                os.chdir(path)
                if sys.platform == "win32":
                    subprocess.run(["python", "-m", "venv", "venv"], check=True)
                else:
                    subprocess.run(["python3", "-m", "venv", "venv"], check=True)
                if verbose:
                    print("[INFO] Virtual environment created in ./venv")
            finally:
                os.chdir(original_dir)
        except subprocess.CalledProcessError as e:
            stats.warnings.append(f"Virtual environment creation failed: {e}")
            if show_warnings:
                warnings.warn(f"Virtual environment creation failed: {e}", UserWarning)
    
    # Create pre-commit configuration
    if pre_commit_hooks:
        precommit_file = path / ".pre-commit-config.yaml"
        precommit_content = f'''repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: check-ast
      - id: check-json
      - id: check-toml

  - repo: https://github.com/psf/black
    rev: 23.12.1
    hooks:
      - id: black
        language_version: python3

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.9
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
'''
        precommit_file.write_text(precommit_content, encoding="utf-8")
        stats.files_created.append(str(precommit_file))
        if verbose:
            print(f"[INFO] Created: {precommit_file}")
    
    # Create pyproject.toml with tool configurations
    # (already handled by write_pyproject)
    
    # Create requirements.txt (optional)
    if deps and not use_poetry:
        req_file = path / "requirements.txt"
        req_content = "# Generated dependencies\n" + "\n".join(deps)
        req_file.write_text(req_content, encoding="utf-8")
        stats.files_created.append(str(req_file))
    
    # Create development requirements
    if "dev" in extras_dict and extras_dict["dev"]:
        dev_req_file = path / "requirements-dev.txt"
        dev_content = "# Development dependencies\n" + "\n".join(extras_dict["dev"])
        dev_req_file.write_text(dev_content, encoding="utf-8")
        stats.files_created.append(str(dev_req_file))
    
    # Calculate final statistics
    stats.end_time = time.time()
    
    # Print summary
    if verbose:
        print("\n" + "=" * 60)
        print("Project Structure Generated Successfully!")
        print("=" * 60)
        print(f"Project path: {path}")
        print(f"Package name: {project_name}")
        print(f"Version: {version}")
        print(f"Directories: {stats.total_directories}")
        print(f"Files: {stats.total_files}")
        print(f"Time: {stats.elapsed_time:.2f}s")
        
        if stats.has_warnings:
            print(f"\nWarnings: {len(stats.warnings)}")
            for warning in stats.warnings[:3]:
                print(f" WARNING: {warning}")
        
        print("\nNext steps:")
        print(f"  cd {path}")
        if create_virtual_env:
            if sys.platform == "win32":
                print("  .\\venv\\Scripts\\activate")
            else:
                print("  source venv/bin/activate")
        print("  pip install -e .[dev]")
        if use_pytest:
            print("  pytest tests/")
        if git_init:
            print("  git status")
        if pre_commit_hooks:
            print("  pre-commit install")
        print("")
    
    return {
        "project_path": str(path),
        "stats": stats,
        "package_name": project_name,
        "normalized_package": normalized_package,
        "version": version,
    }
