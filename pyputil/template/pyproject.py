#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyProject Generator - PEP 621 Compliant pyproject.toml Generator
================================================================

A comprehensive, generator for creating fully compliant
pyproject.toml files following modern Python packaging standards including
PEP 517, PEP 518, PEP 621, PEP 660, and PEP 665.

This module provides both a high-level function interface and a detailed
class-based generator for creating complete Python project configurations
with support for:

Core Features:
    - PEP 621 compliant project metadata (name, version, description, authors)
    - Comprehensive dependency management with version specifiers
    - Optional dependency groups (extras) for feature flags
    - Multiple build backend support (setuptools, hatchling, poetry, flit, pdm)
    - Dynamic metadata fields for version detection from VCS or __init__.py
    - License management with SPDX identifiers and external license files

Development Tools:
    - Black code formatter configuration
    - isort import sorting with Black compatibility
    - pytest testing framework with advanced options
    - mypy static type checking with strict mode
    - Ruff fast linter and formatter
    - Coverage.py with threshold enforcement
    - pre-commit hooks configuration
    - tox testing automation

Quality Assurance:
    - Input validation following PEP standards
    - Automatic Trove classifier generation
    - Dependency sorting for consistent diffs
    - Warning system for configuration issues
    - Verbose mode for debugging
    - Generation statistics and metrics

Examples
--------
Basic package configuration:
>>> from pyputil.template import pyproject_template
>>> config = pyproject_template(
...     name="my-awesome-package",
...     version="1.0.0",
...     description="An awesome Python package",
...     authors=["Jane Doe <jane@example.com>"]
... )

Full enterprise configuration with all features:
>>> config = pyproject_template(
...     name="enterprise-lib",
...     version="2.0.0",
...     build_backend="hatchling.build",
...     license_name="Apache-2.0",
...     dependencies=["requests>=2.28.0", "click>=8.0.0"],
...     optional_dependencies={
...         "dev": ["pytest>=7.0.0", "black>=23.0.0"],
...         "aws": ["boto3>=1.26.0"]
...     },
...     entry_points={
...         "console_scripts": ["cli = package.cli:main"]
...     },
...     include_tool_sections=["black", "ruff", "mypy"]
... )

Dynamic version from package __init__.py:
>>> config = pyproject_template(
...     name="dynamic-package",
...     version="0.1.0",  # Placeholder
...     dynamic_fields=["version"],
...     version_source="attr:dynamic_package.__version__"
... )
"""

from typing import List, Optional, Dict, Any, Union, Tuple
import re
from datetime import datetime
from pathlib import Path
import sys
import warnings
from dataclasses import dataclass, field
from enum import Enum


class BuildBackend(str, Enum):
    """
    Supported build system backends for Python package distribution.
    
    This enum defines the available build backends that comply with PEP 517.
    Each backend has different strengths, trade-offs, and use cases.
    
    Attributes
    ----------
    SETUPTOOLS : str
        The classic setuptools build backend. Most widely used and compatible.
        Excellent for complex packages with C extensions or legacy codebases.
        Supports extensive configuration via setup.cfg or setup.py.
        Build requirements: setuptools>=61.0
        
    HATCHLING : str
        Modern, fast build backend from the Hatch project. Minimal configuration
        required. Built-in version management. Excellent for pure Python packages.
        Build requirements: hatchling
        
    POETRY : str
        Poetry's core build backend. Provides deterministic builds with lock files.
        Excellent dependency resolution. Best for applications and libraries
        requiring reproducible environments.
        Build requirements: poetry-core
        
    FLIT : str
        Lightweight, simple build backend. Minimal configuration. Fast builds.
        Best for simple pure Python packages with few dependencies.
        Build requirements: flit_core
        
    PDM : str
        Modern Python package manager with PEP 582 support. Provides
        PEP 621 native support. Excellent for project monorepos.
        Build requirements: pdm-backend
    
    Examples
    --------
    >>> backend = BuildBackend.HATCHLING
    >>> print(backend.value)
    hatchling.build
    """
    SETUPTOOLS = "setuptools.build_meta"
    HATCHLING = "hatchling.build"
    POETRY = "poetry.core.masonry.api"
    FLIT = "flit_core.buildapi"
    PDM = "pdm.backend"


class LicenseType(str, Enum):
    """
    Standard open source licenses with SPDX identifiers for PyPI classification.
    
    This enum provides commonly used license identifiers that are recognized
    by PyPI and other package indices. Each license has specific terms and
    conditions that affect how others can use, modify, and distribute your code.
    
    Attributes
    ----------
    MIT : str
        MIT License - Highly permissive, minimal restrictions. Allows proprietary
        use, sublicensing, and modification with proper attribution.
        Most popular license for open source Python packages.
        
    APACHE_2 : str
        Apache License 2.0 - Permissive with explicit patent grants. Protects
        contributors from patent litigation. Requires state of changes.
        Popular for corporate-backed open source projects.
        
    BSD_3 : str
        BSD 3-Clause License - Permissive with non-endorsement clause. Similar
        to MIT but prohibits using contributor names for promotion.
        Common in academic and scientific software.
        
    GPL_3 : str
        GNU General Public License v3 - Strong copyleft license. Requires
        derivative works to also be GPL licensed. Includes patent protection
        and anti-tivoization clauses.
        
    LGPL_3 : str
        GNU Lesser General Public License v3 - Weak copyleft with library
        exception. Allows linking with proprietary code while keeping
        library changes open source.
        
    AGPL_3 : str
        GNU Affero General Public License v3 - Strong copyleft for network
        services. Requires source disclosure for software accessed over a
        network. Popular for web applications and SaaS.
        
    MPL_2 : str
        Mozilla Public License 2.0 - Weak copyleft at file level. Allows
        mixing with proprietary code in different files. Balanced approach
        for libraries used in commercial products.
        
    ISC : str
        ISC License - Simplified permissive license. Functionally equivalent
        to MIT but with simpler language. Popular in OpenBSD ecosystem.
        
    UNLICENSE : str
        The Unlicense - Public domain dedication. Waives all copyright
        rights. Allows unrestricted use, modification, and distribution.
        
    PROPRIETARY : str
        Proprietary/Commercial License - All rights reserved. Not open source.
        Used for commercial software or internal projects.
    
    Examples
    --------
    >>> license_type = LicenseType.MIT
    >>> print(license_type.value)
    MIT
    """
    MIT = "MIT"
    APACHE_2 = "Apache-2.0"
    BSD_3 = "BSD-3-Clause"
    GPL_3 = "GPL-3.0-or-later"
    LGPL_3 = "LGPL-3.0-or-later"
    AGPL_3 = "AGPL-3.0-or-later"
    MPL_2 = "MPL-2.0"
    ISC = "ISC"
    UNLICENSE = "Unlicense"
    PROPRIETARY = "Proprietary"


class DevelopmentStatus(str, Enum):
    """
    PyPI development status classifiers indicating project maturity.
    
    These classifiers communicate the stability and readiness of your project
    to potential users on PyPI. Choose the status that best reflects your
    project's current stage of development.
    
    Attributes
    ----------
    PLANNING : str
        1 - Planning - Project is planned but not yet started. Useful for
        reserving package names or announcing future work.
        
    PRE_ALPHA : str
        2 - Pre-Alpha - Early development stage. Code exists but is not
        feature complete. APIs are unstable and subject to change.
        
    ALPHA : str
        3 - Alpha - Initial testing release. Core functionality present but
        may have significant bugs. API still evolving.
        
    BETA : str
        4 - Beta - Feature complete. Under testing but stable enough for
        early adopters. API is stable with minimal changes expected.
        
    STABLE : str
        5 - Production/Stable - Ready for production use. Well tested,
        documented, and maintained. API is stable and backwards compatible.
        
    MATURE : str
        6 - Mature - Stable and mature. Development has slowed with only
        critical bug fixes and security patches. Long-term maintenance.
        
    INACTIVE : str
        7 - Inactive - No longer actively developed. Accepting contributions
        but not actively maintained. May be looking for maintainers.
    
    Examples
    --------
    >>> status = DevelopmentStatus.STABLE
    >>> print(status.value)
    5 - Production/Stable
    """
    PLANNING = "1 - Planning"
    PRE_ALPHA = "2 - Pre-Alpha"
    ALPHA = "3 - Alpha"
    BETA = "4 - Beta"
    STABLE = "5 - Production/Stable"
    MATURE = "6 - Mature"
    INACTIVE = "7 - Inactive"


@dataclass
class PyProjectStats:
    """
    Statistics and metrics about the generated pyproject.toml configuration.
    
    This dataclass captures comprehensive information about the generation
    process, including counts of various elements, validation results, and
    performance metrics. Useful for debugging, monitoring, and optimization.
    
    Attributes
    ----------
    dependencies_count : int
        Number of runtime dependencies specified in the project.
        
    optional_groups_count : int
        Number of optional dependency groups (extras) defined.
        
    dynamic_fields_count : int
        Number of fields marked as dynamic for build-time resolution.
        
    tools_configured : int
        Number of development tools configured in the pyproject.toml.
        
    warnings_issued : int
        Count of warnings generated during configuration validation.
        
    errors_encountered : int
        Count of validation errors that were caught and handled.
        
    generation_time_seconds : float
        Time taken to generate the configuration in seconds.
        
    output_size_bytes : int
        Size of the generated TOML content in bytes.
        
    build_backend : str
        The selected build backend for the project.
        
    python_requires : str
        Python version constraint string.
        
    timestamp : datetime
        When the configuration was generated.
    
    Examples
    --------
    >>> stats = PyProjectStats(
    ...     dependencies_count=5,
    ...     optional_groups_count=2,
    ...     tools_configured=4,
    ...     generation_time_seconds=0.025,
    ...     output_size_bytes=2048
    ... )
    """
    dependencies_count: int = 0
    optional_groups_count: int = 0
    dynamic_fields_count: int = 0
    tools_configured: int = 0
    warnings_issued: int = 0
    errors_encountered: int = 0
    generation_time_seconds: float = 0.0
    output_size_bytes: int = 0
    build_backend: str = ""
    python_requires: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class PyProjectGenerator:
    """
    Generator for PEP 621 compliant pyproject.toml files.
    
    This class provides comprehensive functionality for generating complete,
    production-ready pyproject.toml configurations following modern Python
    packaging standards. It supports all major build backends, dependency
    management strategies, and development tool configurations.
    
    Key Features:
        - Full PEP 621 compliance for project metadata
        - Support for all major build backends (setuptools, hatchling, poetry, flit, pdm)
        - Comprehensive dependency management with version specifiers
        - Optional dependency groups for feature flags and extras
        - Dynamic version detection from __init__.py or VCS
        - Automatic Trove classifier generation
        - Development tool configuration (black, isort, pytest, mypy, ruff, coverage)
        - Pre-commit hooks configuration
        - tox testing automation setup
        - Input validation with helpful error messages
        - Warning system for configuration best practices
        - Verbose mode for debugging and auditing
        - Generation statistics and performance metrics
        
    Architecture
    ------------
    The class follows the builder pattern with a fluent interface. Configuration
    is set during initialization with comprehensive validation. Generation
    produces a complete TOML document with proper formatting, comments, and
    section organization.
    
    Type Hierarchy:
        PyProjectGenerator (main orchestrator)
        ├── PyProjectStats (generation metrics)
        ├── BuildBackend (enum for backend selection)
        ├── LicenseType (enum for license identifiers)
        └── DevelopmentStatus (enum for maturity status)
    
    Examples
    --------
    Basic usage with default configuration:
    >>> generator = PyProjectGenerator(
    ...     name="my-package",
    ...     version="1.0.0",
    ...     description="A brief description",
    ...     authors=["Author Name <author@example.com>"]
    ... )
    >>> content = generator.generate()
    >>> generator.write("pyproject.toml")
    
    Advanced configuration with all features:
    >>> generator = PyProjectGenerator(
    ...     name="enterprise-lib",
    ...     version="2.0.0",
    ...     build_backend=BuildBackend.HATCHLING,
    ...     license_type=LicenseType.APACHE_2,
    ...     development_status=DevelopmentStatus.STABLE,
    ...     dependencies=["requests>=2.28.0", "click>=8.0.0,<9.0.0"],
    ...     optional_dependencies={
    ...         "dev": ["pytest>=7.0.0", "black>=23.0.0"],
    ...         "aws": ["boto3>=1.26.0"]
    ...     },
    ...     included_tools=["black", "ruff", "mypy", "pytest"],
    ...     verbose=True
    ... )
    
    Dynamic version detection:
    >>> generator = PyProjectGenerator(
    ...     name="dynamic-versioned-pkg",
    ...     version="0.1.0",  # Placeholder
    ...     dynamic_fields=["version"],
    ...     version_source="attr:dynamic_pkg.__version__",
    ...     auto_detect_version=True
    ... )
    
    Notes
    -----
    The generated pyproject.toml file follows best practices:
        - All fields are properly quoted and escaped
        - Consistent indentation (4 spaces as per TOML spec)
        - Comments for generated metadata
        - Sections organized logically
        - Arrays formatted with trailing commas for cleaner diffs
    """
    
    def __init__(
        self,
        name: str = "my_package",
        version: str = "0.1.0",
        description: str = "A short description of the project",
        authors: Optional[List[str]] = None,
        maintainers: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None,
        optional_dependencies: Optional[Dict[str, List[str]]] = None,
        python_requires: str = ">=3.8",
        build_backend: BuildBackend = BuildBackend.SETUPTOOLS,
        license_type: Optional[LicenseType] = LicenseType.MIT,
        license_file: Optional[str] = None,
        development_status: DevelopmentStatus = DevelopmentStatus.BETA,
        readme: str = "README.md",
        readme_content_type: str = "text/markdown",
        urls: Optional[Dict[str, str]] = None,
        keywords: Optional[List[str]] = None,
        classifiers: Optional[List[str]] = None,
        entry_points: Optional[Dict[str, List[str]]] = None,
        scripts: Optional[Dict[str, str]] = None,
        included_tools: Optional[List[str]] = None,
        tool_configs: Optional[Dict[str, Dict[str, Any]]] = None,
        dynamic_fields: Optional[List[str]] = None,
        extra_sections: Optional[Dict[str, Any]] = None,
        indent: int = 4,
        sort_dependencies: bool = False,
        add_timestamp_comment: bool = True,
        auto_detect_backend: bool = True,
        auto_detect_version: bool = True,
        version_source: Optional[str] = None,
        verbose: bool = False,
        show_warnings: bool = True,
    ) -> None:
        """
        Initialize the PyProjectGenerator with comprehensive configuration.
        
        This constructor sets up the generator with all necessary parameters
        for creating a complete pyproject.toml file. Each parameter has
        sensible defaults while allowing complete customization.
        
        Parameters
        ----------
        name : str, default="my_package"
            Project name following PEP 508 naming conventions.
            
            Rules:
                - Must contain only lowercase letters, numbers, hyphens, underscores, and dots
                - Cannot start with a hyphen or dot
                - Should be unique on PyPI if publishing
                - Typically matches the import name (hyphens become underscores)
                
            Examples:
                "requests", "django", "flask", "numpy", "my-awesome-package"
                
            Warning:
                Names longer than 50 characters may cause issues with some tools.
                
        version : str, default="0.1.0"
            Project version following PEP 440 semantic versioning.
            
            Format: MAJOR.MINOR.PATCH[-pre-release][+build]
            
            Pre-release suffixes:
                - "aN" or "alphaN": Alpha release (1.0.0a1)
                - "bN" or "betaN": Beta release (1.0.0b2)
                - "rcN" or "cN": Release candidate (1.0.0rc1)
                - ".devN": Development release (1.0.0.dev1)
                - ".postN": Post-release (1.0.0.post1)
                
            Examples:
                "0.1.0", "1.2.3", "2.0.0a1", "1.0.0rc1", "0.5.0.dev2"
                
            Best Practices:
                - Start with 0.1.0 for initial development
                - Use semantic versioning for compatibility communication
                - Increment major version for breaking changes
                - Increment minor for new features (backwards compatible)
                - Increment patch for bug fixes
                
        description : str, default="A short description of the project"
            One-line project summary for PyPI and package indices.
            
            Guidelines:
                - Maximum 200 characters recommended
                - Should be concise and informative
                - Appears in search results and package listings
                - First line of help text in documentation
                
            Examples:
                "HTTP library for humans"
                "Fast numerical computing library"
                "ASGI web framework for building APIs"
                
        authors : List[str], optional
            Primary creators and copyright holders of the project.
            
            Format: "Name <email@example.com>"
            
            Guidelines:
                - Order matters for attribution
                - Email is optional but recommended for contact
                - Multiple authors are comma-separated in the list
                
            Examples:
                ["Jane Doe <jane@example.com>"]
                ["John Smith <john@example.com>", "Jane Doe <jane@example.com>"]
                
            Default:
                ["Your Name <you@example.com>"] - replace with actual authors
                
        maintainers : List[str], optional
            Current maintainers actively managing the project.
            
            Format: Same as authors: "Name <email@example.com>"
            
            Purpose:
                - Identifies who is currently maintaining the project
                - Useful for projects with maintainer changes
                - Inherits from authors if not specified
                
            When to Use:
                - Project has changed maintainers
                - Different people author vs maintain
                - Multiple active maintainers to credit
                
        dependencies : List[str], optional
            Runtime dependencies with PEP 508 version specifiers.
            
            Format Patterns:
                1. Simple (latest compatible):
                    "requests"
                    
                2. With version constraint:
                    "requests>=2.28.0"
                    "requests>=2.28.0,<3.0.0"
                    "requests==2.28.0"
                    
                3. With extras:
                    "pandas[parquet]>=1.5.0"
                    
                4. Environment markers:
                    "pywin32>=304; sys_platform == 'win32'"
                    
                5. URL-based:
                    "mypkg @ git+https://github.com/user/repo.git"
                    
                6. Local path:
                    "mypkg @ file:///path/to/mypkg"
                    
            Version Specifiers:
                - `==` : Exact version match
                - `>=` : Greater than or equal
                - `<=` : Less than or equal
                - `>`  : Greater than
                - `<`  : Less than
                - `~=` : Compatible release (same major.minor)
                - `!=` : Not equal to version
                
            Examples:
                ["numpy>=1.21.0,<2.0.0", "pandas>=1.3.0"]
                ["click>=8.0.0", "colorama; sys_platform == 'win32'"]
                
        optional_dependencies : Dict[str, List[str]], optional
            Optional dependency groups for feature flags.
            
            Structure:
                {
                    "extra_name": ["dependency1", "dependency2"],
                    "dev": ["pytest", "black", "ruff"]
                }
            
            Usage:
                Install with: pip install package[extra_name]
                Multiple extras: pip install package[dev,test]
                All extras: pip install package[all] (if defined)
            
            Common Extras:
                - "dev": Development tools and testing
                - "test": Testing frameworks only
                - "docs": Documentation building tools
                - "lint": Code quality tools
                - "all": All optional dependencies combined
                - "aws": AWS-specific dependencies
                - "postgres": PostgreSQL drivers
                
            Examples:
                {
                    "dev": ["pytest>=7.0.0", "black>=23.0.0"],
                    "aws": ["boto3>=1.26.0"],
                    "test": ["pytest>=7.0.0", "pytest-cov>=4.0.0"]
                }
                
        python_requires : str, default=">=3.8"
            Python version constraints.
            
            Formats:
                - Minimum only: ">=3.8"
                - Range: ">=3.8,<3.13"
                - Maximum only: "<=3.12"
                - Exact major version: "==3.11.*"
                - Exclusion: ">=3.8, !=3.9.0"
                - Multiple conditions: ">=3.8,<3.13, !=3.10.5"
                
            Best Practices:
                - Test against all versions in your constraint range
                - Set realistic minimum based on language features used
                - Update upper bound to exclude EOL Python versions
                - Be permissive for libraries (wider range)
                - Be specific for applications (narrower range)
                
            Examples:
                ">=3.9"  # Python 3.9 and newer
                ">=3.8,<3.13"  # Python 3.8 through 3.12
                "~=3.11"  # Python 3.11.x only
                
        build_backend : BuildBackend, default=SETUPTOOLS
            Build system backend for package distribution.
            
            Options:
                SETUPTOOLS: Classic, widely compatible, C extension support
                HATCHLING: Modern, fast, minimal config
                POETRY: Deterministic builds, lock files
                FLIT: Simple, lightweight, pure Python
                PDM: PEP 582 support, modern features
                
            Selection Guide:
                - Use SETUPTOOLS for: C extensions, legacy projects, complex builds
                - Use HATCHLING for: New projects, pure Python, simple config
                - Use POETRY for: Applications, reproducible environments
                - Use FLIT for: Simple packages, quick setup
                - Use PDM for: PEP 582, monorepos, modern workflows
                
        license_type : LicenseType, optional, default=MIT
            SPDX license identifier for the project.
            
            Common Choices:
                - MIT: Permissive, most popular for open source
                - Apache-2.0: Permissive with patent protection
                - GPL-3.0-or-later: Strong copyleft
                - BSD-3-Clause: Permissive, no endorsement
                - Proprietary: Commercial, all rights reserved
                
            Legal Considerations:
                - MIT: Allows proprietary use with attribution
                - GPL: Requires derived works to also be GPL
                - Apache: Grants explicit patent license
                - MPL: File-level copyleft
                
        license_file : str, optional
            Path to external license file (e.g., "LICENSE", "LICENSE.txt").
            
            Use Cases:
                - Custom license text not in SPDX list
                - Company-specific proprietary license
                - Multiple license combination
                - License with complex terms
                
            Note:
                Cannot be used with license_type. Choose one or the other.
                
        development_status : DevelopmentStatus, default=BETA
            Project maturity indicator for PyPI.
            
            Selection by Project State:
                - PLANNING: Announcing future work, reserving name
                - PRE_ALPHA: Early prototype, not feature complete
                - ALPHA: Feature incomplete, testing begins
                - BETA: Feature complete, bug fixing
                - STABLE: Production ready, fully tested
                - MATURE: Stable, minimal changes
                - INACTIVE: No longer maintained
                
        readme : str, default="README.md"
            Path to README documentation file.
            
            Supported Formats:
                - Markdown: "README.md" (text/markdown)
                - reStructuredText: "README.rst" (text/x-rst)
                - Plain text: "README.txt" (text/plain)
                
            Content Guidelines:
                - Should be at least a few paragraphs
                - Include installation and usage examples
                - Add badges for CI, coverage, version
                - Link to full documentation if available
                
        readme_content_type : str, default="text/markdown"
            MIME type of the README file.
            
            Options:
                - "text/markdown": For .md files
                - "text/x-rst": For .rst files
                - "text/plain": For .txt files
                
            Important:
                Must match actual file format for PyPI rendering.
                
        urls : Dict[str, str], optional
            Project URLs displayed on PyPI project page.
            
            Common Keys:
                - "Homepage": Main project website
                - "Repository": Source code (GitHub, GitLab, etc.)
                - "Documentation": API docs or user guide
                - "Issues": Bug tracker (GitHub Issues, Jira)
                - "Changelog": Release notes
                - "Funding": Sponsor or donation page
                - "Discord": Community chat server
                
            Examples:
                {
                    "Homepage": "https://example.com",
                    "Repository": "https://github.com/user/repo",
                    "Documentation": "https://docs.example.com",
                    "Issues": "https://github.com/user/repo/issues"
                }
                
        keywords : List[str], optional
            Search keywords for PyPI indexing.
            
            Guidelines:
                - 5-10 relevant terms
                - Single words or short phrases
                - Lowercase preferred
                - Include domain-specific terms
                - Avoid common words (and, the, a)
                
            Examples:
                ["web", "framework", "async", "api", "rest"]
                ["data", "science", "analytics", "pandas", "numpy"]
                
        classifiers : List[str], optional
            Trove classifiers for PyPI categorization.
            
            Automatic Generation:
                If not provided, generates based on:
                    - Development status
                    - License type
                    - Python versions
                    - Operating system (OS Independent)
                    
            See: https://pypi.org/classifiers/
            
            Examples:
                [
                    "Development Status :: 5 - Production/Stable",
                    "Intended Audience :: Developers",
                    "License :: OSI Approved :: MIT License",
                    "Programming Language :: Python :: 3.10",
                    "Operating System :: OS Independent"
                ]
                
        entry_points : Dict[str, List[str]], optional
            Console scripts and plugin entry points.
            
            Groups:
                - "console_scripts": CLI commands
                - "pytest11": pytest plugins
                - "mypy": mypy plugins
                - "sphinx.html_themes": Sphinx themes
                - "flake8.extension": Flake8 plugins
                
            Format: "command = module:function"
            
            Examples:
                {
                    "console_scripts": [
                        "mycli = mypackage.cli:main",
                        "myhelper = mypackage.helper:run"
                    ],
                    "pytest11": ["mypackage = mypackage.pytest_plugin"]
                }
                
        scripts : Dict[str, str], optional
            Executable script mappings (alternative to entry_points).
            
            Difference from entry_points:
                - Simpler: Just name to path mapping
                - Less flexible: No function references
                - Script files only: Shell scripts, executables
                
            Use Cases:
                - Wrapper scripts around existing binaries
                - Shell scripts installed with package
                - Simple executable files
                
            Examples:
                {
                    "run-server": "scripts/run_server.py",
                    "db-migrate": "scripts/migrate_db.sh"
                }
                
        included_tools : List[str], optional
            Development tool sections to include.
            
            Available Tools:
                - "black": Code formatter configuration
                - "isort": Import sorter settings
                - "pytest": Testing framework options
                - "mypy": Type checker configuration
                - "ruff": Fast linter and formatter
                - "coverage": Test coverage settings
                - "pre-commit": Git hooks configuration
                - "tox": Multi-environment testing
                
            Default: All major tools included
            Set to [] to exclude all tool sections
            
            Examples:
                ["black", "ruff"]  # Only these two tools
                []  # No tool configurations
                None  # Include all default tools
                
        tool_configs : Dict[str, Dict[str, Any]], optional
            Custom tool configuration overrides.
            
            Structure:
                {
                    "tool_name": {"option": value, "nested": {"subopt": val}}
                }
            
            Examples:
                {
                    "black": {"line-length": 100},
                    "pytest": {"addopts": "-v --tb=short"},
                    "ruff": {"select": ["E", "F", "I"], "ignore": ["E501"]}
                }
                
            Note:
                Merges with defaults, user values take precedence.
                
        dynamic_fields : List[str], optional
            Fields determined at build time.
            
            Common Dynamic Fields:
                - "version": Read from __init__.py or VCS
                - "description": Generated from README
                - "dependencies": Computed from environment
                - "classifiers": Generated from metadata
                
            Requires:
                Backend-specific configuration for dynamic fields
                
            Examples:
                ["version"]  # Version is dynamic
                ["version", "description"]  # Multiple dynamic fields
                
        extra_sections : Dict[str, Any], optional
            Custom TOML sections for project needs.
            
            Structure:
                {
                    "section.name": {"key": "value", "array": [1, 2, 3]}
                }
            
            Use Cases:
                - Custom tool configuration
                - Project-specific metadata
                - Integration with external services
                
            Examples:
                {
                    "tool.poetry": {"version": "1.0.0"},
                    "myproject": {"plugin-dir": "plugins/"}
                }
                
        indent : int, default=4
            Number of spaces for indentation.
            
            TOML Standard:
                - Recommendation: 4 spaces
                - Must be consistent throughout file
                
        sort_dependencies : bool, default=False
            Sort dependencies alphabetically.
            
            Benefits:
                - Cleaner version control diffs
                - Easier to spot duplicates
                - Consistent ordering across regenerations
                
        add_timestamp_comment : bool, default=True
            Include generation timestamp in header comment.
            
            Benefits:
                - Track when config was generated
                - Debug CI/CD pipeline issues
                - Audit configuration changes
                
        auto_detect_backend : bool, default=True
            Automatically configure build requirements.
            
            Function:
                - Adds required build dependencies
                - Ensures backend works correctly
                - Updates build-system section
                
        auto_detect_version : bool, default=True
            Automatically configure version detection.
            
            Applies to:
                - Setuptools backend only
                - When "version" in dynamic_fields
                - Sets up tool.setuptools.dynamic
                
        version_source : str, optional
            Source for dynamic version detection.
            
            Options:
                - "attr:package.__version__": Read from __init__.py
                - "file:VERSION.txt": Read from version file
                - "git:tag": Use git tag as version
                
            Default:
                "attr:{package_name}.__version__"
                
        verbose : bool, default=False
            Print detailed generation information.
            
            Output Includes:
                - Configuration summary
                - Detected settings
                - Generation steps
                - Warning messages
                - Performance metrics
                
        show_warnings : bool, default=True
            Display warning messages.
            
            Warnings Indicate:
                - Potential configuration issues
                - Non-standard practices
                - Missing recommended files
                - Performance concerns
                
        Raises
        ------
        ValueError
            If validation fails:
                - Invalid project name format
                - Invalid version format
                - Conflicting license specifications
                - Missing required information
                
        Examples
        --------
        Minimal configuration:
        >>> gen = PyProjectGenerator(name="test", version="0.1.0")
        
        Production configuration:
        >>> gen = PyProjectGenerator(
        ...     name="prod-app",
        ...     version="1.0.0",
        ...     build_backend=BuildBackend.HATCHLING,
        ...     license_type=LicenseType.MIT,
        ...     dependencies=["requests>=2.28.0"],
        ...     verbose=True
        ... )
        """
        # ====================================================================
        # SECTION 1: Input Validation
        # ====================================================================
        
        # Validate project name format
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', name):
            raise ValueError(
                f"Invalid project name '{name}'. "
                f"Valid names contain only alphanumeric characters, "
                f"hyphens, underscores, and dots. "
                f"See PEP 508 for complete naming rules."
            )
        
        # Validate version format
        if not re.match(r'^\d+\.\d+\.\d+', version):
            raise ValueError(
                f"Invalid version format '{version}'. "
                f"Version must follow semantic versioning: MAJOR.MINOR.PATCH "
                f"(e.g., 0.1.0, 1.2.3, 2.0.0a1). "
                f"See PEP 440 for complete specification."
            )
        
        # Validate license configuration
        if license_type and license_file:
            raise ValueError(
                "Cannot specify both license_type and license_file. "
                "Choose either:\n"
                "  - license_type: For standard SPDX open source licenses\n"
                "  - license_file: For custom or proprietary licenses in external file"
            )
        
        # ====================================================================
        # SECTION 2: Core Metadata Initialization
        # ====================================================================
        
        # Project identification
        self.name = name
        self.version = version
        self.description = description
        
        # Authorship and ownership
        self.authors = authors or ["Your Name <you@example.com>"]
        self.maintainers = maintainers or self.authors
        
        # Dependencies management
        self.dependencies = dependencies or []
        self.optional_dependencies = optional_dependencies or {}
        
        # Environment requirements
        self.python_requires = python_requires
        
        # Build system configuration
        self.build_backend = build_backend
        self.license_type = license_type
        self.license_file = license_file
        self.development_status = development_status
        
        # Documentation paths
        self.readme = readme
        self.readme_content_type = readme_content_type
        
        # Project URLs and discovery
        self.urls = urls or {}
        self.keywords = keywords or []
        self.classifiers = classifiers
        
        # Entry points and scripts
        self.entry_points = entry_points or {}
        self.scripts = scripts or {}
        
        # Tool configuration
        self.tool_configs = tool_configs or {}
        
        # Dynamic metadata handling
        self.dynamic_fields = dynamic_fields or []
        
        # Custom sections
        self.extra_sections = extra_sections or {}
        
        # Generation options
        self.indent = indent
        self.sort_dependencies = sort_dependencies
        self.add_timestamp_comment = add_timestamp_comment
        self.auto_detect_backend = auto_detect_backend
        self.auto_detect_version = auto_detect_version
        self.version_source = version_source
        
        # Runtime behavior
        self.verbose = verbose
        self.show_warnings = show_warnings
        
        # ====================================================================
        # SECTION 3: Determine Tool Sections to Include
        # ====================================================================
        
        if included_tools is None:
            # Include all standard tool sections by default
            self.included_tools = [
                "black", "isort", "pytest", "mypy", 
                "ruff", "coverage", "pre-commit", "tox"
            ]
        else:
            self.included_tools = included_tools
        
        # ====================================================================
        # SECTION 4: Internal State Initialization
        # ====================================================================
        
        # Build system requirements (determined by backend choice)
        self._build_requires = self._get_build_requirements()
        
        # Warning and error tracking
        self._warnings = []
        self._errors = []
        
        # Generated content storage
        self._generated_content = None
        
        # Generation timestamp
        self._generation_timestamp = datetime.now()
        
        # Statistics tracking
        self._stats = PyProjectStats(
            build_backend=self.build_backend.value,
            python_requires=self.python_requires,
            timestamp=self._generation_timestamp
        )
        
        # ====================================================================
        # SECTION 5: Process Dependencies (Sorting if requested)
        # ====================================================================
        
        if self.sort_dependencies:
            self.dependencies.sort()
            for extra in self.optional_dependencies:
                self.optional_dependencies[extra].sort()
        
        # ====================================================================
        # SECTION 6: Generate Classifiers if Not Provided
        # ====================================================================
        
        if self.classifiers is None:
            self.classifiers = self._generate_classifiers()
        
        # ====================================================================
        # SECTION 7: Validate Complete Configuration
        # ====================================================================
        
        self._validate_configuration()
        
        # ====================================================================
        # SECTION 8: Log Initialization (if verbose mode)
        # ====================================================================
        
        if self.verbose:
            self._log_initialization()
    
    # ========================================================================
    # PRIVATE VALIDATION METHODS
    # ========================================================================
    
    def _get_build_requirements(self) -> List[str]:
        """
        Determine required build dependencies based on selected backend.
        
        This method maps the chosen build backend to its required Python
        packages for building and distributing the project.
        
        Returns
        -------
        List[str]
            List of package names with version constraints needed for building.
            
        Mapping Details
        ---------------
        SETUPTOOLS -> ["setuptools>=61.0"]
            Requires setuptools version that supports pyproject.toml.
            
        HATCHLING -> ["hatchling"]
            Minimal requirement, modern packaging tool.
            
        POETRY -> ["poetry-core"]
            Core of Poetry without full Poetry installation.
            
        FLIT -> ["flit_core"]
            Lightweight core for flit.
            
        PDM -> ["pdm-backend"]
            PDM's build backend implementation.
            
        Notes
        -----
        If auto_detect_backend is False, returns default setuptools requirements.
        """
        if not self.auto_detect_backend:
            return ["setuptools>=61.0"]
        
        # Map backends to their build requirements
        backend_requirements = {
            BuildBackend.SETUPTOOLS: ["setuptools>=61.0"],
            BuildBackend.HATCHLING: ["hatchling"],
            BuildBackend.POETRY: ["poetry-core"],
            BuildBackend.FLIT: ["flit_core"],
            BuildBackend.PDM: ["pdm-backend"],
        }
        
        return backend_requirements.get(self.build_backend, ["setuptools>=61.0"])
    
    def _generate_classifiers(self) -> List[str]:
        """
        Generate PyPI Trove classifiers automatically from configuration.
        
        This method creates appropriate classifiers based on:
            - Development status
            - License type
            - Python version requirements
            - Target audience (default: Developers)
            - Operating system (default: OS Independent)
        
        Returns
        -------
        List[str]
            List of classifier strings for PyPI categorization.
            
        Classifier Categories
        --------------------
        1. Development Status:
            Maps DevelopmentStatus enum to PyPI classifier format.
            
        2. Intended Audience:
            Defaults to "Intended Audience :: Developers"
            
        3. License:
            Maps license_type to appropriate OSI-approved classifier.
            
        4. Programming Language:
            - "Programming Language :: Python"
            - Specific version classifiers based on python_requires
            
        5. Operating System:
            Defaults to "Operating System :: OS Independent"
            
        License Mapping
        --------------
        MIT -> "License :: OSI Approved :: MIT License"
        Apache-2.0 -> "License :: OSI Approved :: Apache Software License"
        BSD-3-Clause -> "License :: OSI Approved :: BSD License"
        GPL-3.0-or-later -> "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)"
        LGPL-3.0-or-later -> "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)"
        AGPL-3.0-or-later -> "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)"
        MPL-2.0 -> "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)"
        ISC -> "License :: OSI Approved :: ISC License (ISCL)"
        Unlicense -> "License :: Public Domain"
        Proprietary -> "License :: Other/Proprietary License"
        """
        classifiers = []
        
        # 1. Development Status classifier
        status_map = {
            DevelopmentStatus.PLANNING: "Development Status :: 1 - Planning",
            DevelopmentStatus.PRE_ALPHA: "Development Status :: 2 - Pre-Alpha",
            DevelopmentStatus.ALPHA: "Development Status :: 3 - Alpha",
            DevelopmentStatus.BETA: "Development Status :: 4 - Beta",
            DevelopmentStatus.STABLE: "Development Status :: 5 - Production/Stable",
            DevelopmentStatus.MATURE: "Development Status :: 6 - Mature",
            DevelopmentStatus.INACTIVE: "Development Status :: 7 - Inactive",
        }
        classifiers.append(status_map[self.development_status])
        
        # 2. Intended Audience (default for libraries)
        classifiers.append("Intended Audience :: Developers")
        
        # 3. License classifier based on license_type
        license_map = {
            LicenseType.MIT: "License :: OSI Approved :: MIT License",
            LicenseType.APACHE_2: "License :: OSI Approved :: Apache Software License",
            LicenseType.BSD_3: "License :: OSI Approved :: BSD License",
            LicenseType.GPL_3: "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
            LicenseType.LGPL_3: "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)",
            LicenseType.AGPL_3: "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
            LicenseType.MPL_2: "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",
            LicenseType.ISC: "License :: OSI Approved :: ISC License (ISCL)",
            LicenseType.UNLICENSE: "License :: Public Domain",
            LicenseType.PROPRIETARY: "License :: Other/Proprietary License",
        }
        
        if self.license_type and self.license_type in license_map:
            classifiers.append(license_map[self.license_type])
        
        # 4. Programming Language classifiers
        classifiers.append("Programming Language :: Python")
        
        # Add specific Python version classifiers based on python_requires
        version_classifiers = {
            "3.8": "Programming Language :: Python :: 3.8",
            "3.9": "Programming Language :: Python :: 3.9",
            "3.10": "Programming Language :: Python :: 3.10",
            "3.11": "Programming Language :: Python :: 3.11",
            "3.12": "Programming Language :: Python :: 3.12",
            "3.13": "Programming Language :: Python :: 3.13",
        }
        
        # Extract version numbers from python_requires string
        py_version = self.python_requires.replace(">=", "").replace("<", "").strip()
        for ver, classifier in version_classifiers.items():
            if ver in py_version:
                classifiers.append(classifier)
        
        # 5. Operating System (default to OS Independent for pure Python packages)
        classifiers.append("Operating System :: OS Independent")
        
        return classifiers
    
    def _validate_configuration(self) -> None:
        """
        Validate complete configuration for consistency and best practices.
        
        This method checks for potential issues that could affect build,
        distribution, or user experience. Issues are logged as warnings
        but do not prevent generation.
        
        Validation Checks
        ----------------
        1. File Existence:
            - README file exists at specified path
            - License file exists if specified
            
        2. Dependency Management:
            - Number of dependencies (warn if >30)
            - Dependency version specifiers (check for too strict)
            
        3. Python Version Constraints:
            - Warn if using exact version locking
            - Suggest range constraints for libraries
            
        4. Project Metadata:
            - Name length (warn if >50 chars)
            - Description length (info if >200 chars)
            - Missing recommended fields
            
        5. Tool Configurations:
            - Compatibility between tools
            - Deprecated options
            - Best practice violations
        """
        # Check README file existence
        if self.readme and not Path(self.readme).exists():
            self._warn(
                f"README file '{self.readme}' does not exist in current directory. "
                f"Create this file or adjust the 'readme' path."
            )
        
        # Check license file if specified
        if self.license_file:
            license_path = Path(self.license_file)
            if not license_path.exists():
                self._warn(
                    f"License file '{self.license_file}' does not exist. "
                    f"Create the license file or use 'license_type' instead."
                )
            elif license_path.stat().st_size == 0:
                self._warn(
                    f"License file '{self.license_file}' is empty. "
                    f"Please add license text."
                )
        
        # Warn about excessive dependencies
        if len(self.dependencies) > 30:
            self._warn(
                f"Project has {len(self.dependencies)} runtime dependencies. "
                f"Consider:\n"
                f"  - Splitting into multiple packages\n"
                f"  - Reducing core dependencies\n"
                f"  - Moving optional dependencies to 'optional_dependencies'"
            )
        
        # Check for overly strict Python version constraints
        if "==" in self.python_requires and "*" not in self.python_requires:
            self._warn(
                f"Python constraint '{self.python_requires}' is very strict. "
                f"Consider using range constraints like '>=3.8,<3.13' for better "
                f"compatibility with different environments."
            )
        
        # Check name length
        if len(self.name) > 50:
            self._warn(
                f"Project name '{self.name}' is {len(self.name)} characters long. "
                f"Names longer than 50 characters may cause issues with some tools."
            )
        
        # Check description length
        if len(self.description) > 200:
            self._warn(
                f"Description is {len(self.description)} characters. "
                f"PyPI displays only the first 200 characters. "
                f"Consider shortening for better display in search results."
            )
        
        # Check for missing recommended fields
        if not self.urls:
            self._warn(
                "No 'urls' provided. Consider adding at least a 'Repository' URL "
                "to help users find the source code and report issues."
            )
        
        if not self.keywords:
            self._warn(
                "No 'keywords' provided. Adding keywords improves package discovery "
                "on PyPI and search engines."
            )
    
    def _warn(self, message: str) -> None:
        """
        Issue a non-fatal warning message.
        
        Parameters
        ----------
        message : str
            Warning message describing the issue.
            
        Notes
        -----
        Warnings are:
            - Added to internal warnings list
            - Displayed if show_warnings is True
            - Counted in generation statistics
            - Not raised as exceptions
        """
        self._warnings.append(message)
        self._stats.warnings_issued = len(self._warnings)
        
        if self.show_warnings:
            warnings.warn(message, UserWarning, stacklevel=2)
    
    def _log_initialization(self) -> None:
        """
        Log detailed initialization information when verbose mode is enabled.
        
        This method prints comprehensive configuration details including:
            - Project name and version
            - Build backend selection
            - Python version constraints
            - Dependency counts
            - Optional dependency groups
            - Dynamic fields configuration
            - Tools included
            - Any warnings issued
        """
        print("\n" + "="*60)
        print("PYPROJECT GENERATOR INITIALIZATION")
        print("="*60)
        print(f"Project:          {self.name}")
        print(f"Version:          {self.version}")
        print(f"Description:      {self.description[:50]}..." if len(self.description) > 50 else f"Description:      {self.description}")
        print(f"Build Backend:    {self.build_backend.value}")
        print(f"Python Requires:  {self.python_requires}")
        print(f"License:          {self.license_type.value if self.license_type else self.license_file or 'None'}")
        print(f"Development:      {self.development_status.value}")
        print("-"*60)
        print(f"Dependencies:     {len(self.dependencies)}")
        print(f"Optional Groups:  {len(self.optional_dependencies)}")
        print(f"Dynamic Fields:   {self.dynamic_fields or 'None'}")
        print(f"Tools Included:   {', '.join(self.included_tools)}")
        print(f"Sort Dependencies: {self.sort_dependencies}")
        print("-"*60)
        
        if self._warnings:
            print(f"WARNINGS: {len(self._warnings)}")
            for i, warning in enumerate(self._warnings[:5], 1):
                print(f"  {i}. {warning[:80]}...")
            if len(self._warnings) > 5:
                print(f"  ... and {len(self._warnings) - 5} more")
        
        print("="*60 + "\n")
    
    # ========================================================================
    # PRIVATE FORMATTING METHODS
    # ========================================================================
    
    def _escape_toml_string(self, s: str) -> str:
        """
        Escape special characters for TOML string literals.
        
        TOML requires escaping for:
            - Backslashes: becomes double backslash
            - Double quotes: becomes backslash-quote
        
        Parameters
        ----------
        s : str
            String to escape for TOML output.
            
        Returns
        -------
        str
            Escaped string safe for use in TOML double-quoted strings.
            
        Examples
        --------
        >>> gen._escape_toml_string('path\\to\\file')
        'path\\\\to\\\\file'
        >>> gen._escape_toml_string('Say "Hello"')
        'Say \\"Hello\\"'
        """
        return s.replace('\\', '\\\\').replace('"', '\\"')
    
    def _format_toml_list(self, values: List[str], indent_level: int = 1) -> str:
        """
        Format a Python list as a TOML array with proper indentation.
        
        TOML array formatting rules:
            - Empty arrays: "[]"
            - Single-line arrays: ["a", "b"] for small lists
            - Multi-line arrays: each item on new line with trailing comma
        
        Parameters
        ----------
        values : List[str]
            List of string values to format as TOML array.
        indent_level : int, default=1
            Number of indentation levels (1 = self.indent spaces).
            
        Returns
        -------
        str
            TOML-formatted array string.
            
        Examples
        --------
        >>> gen._format_toml_list(["a", "b", "c"])
        '[\n    "a",\n    "b",\n    "c"\n]'
        >>> gen._format_toml_list([])
        '[]'
        """
        if not values:
            return "[]"
        
        # Calculate indentation strings
        indent_spaces = " " * (self.indent * indent_level)
        indent_next = " " * (self.indent * (indent_level + 1))
        
        # Quote and escape each value
        quoted_values = [f'{indent_next}"{self._escape_toml_string(v)}",' for v in values]
        
        # Assemble array with trailing comma for cleaner diffs
        return "[\n" + "\n".join(quoted_values) + f"\n{indent_spaces}]"
    
    def _format_toml_table(self, data: Dict[str, Any], table_name: str) -> str:
        """
        Format a dictionary as a TOML table with nested table support.
        
        This method handles:
            - Simple key-value pairs
            - Lists as arrays
            - Nested dictionaries as sub-tables
            - Proper indentation and spacing
        
        Parameters
        ----------
        data : Dict[str, Any]
            Dictionary to format as TOML table.
        table_name : str
            Name of the TOML table (e.g., "project.urls", "tool.black").
            
        Returns
        -------
        str
            TOML-formatted table string.
            
        Examples
        --------
        >>> data = {"url": "https://example.com", "type": "homepage"}
        >>> gen._format_toml_table(data, "project.urls")
        '[project.urls]\\nurl = "https://example.com"\\ntype = "homepage"'
        
        Nested structure:
        >>> data = {"run": {"source": ["src"]}, "report": {"show_missing": True}}
        >>> gen._format_toml_table(data, "tool.coverage")
        '[tool.coverage]\\n\\n[tool.coverage.run]\\nsource = ["src"]\\n\\n[tool.coverage.report]\\nshow_missing = true'
        """
        if not data:
            return ""
        
        lines = [f"[{table_name}]"]
        
        for key, value in data.items():
            if isinstance(value, list):
                # Format as TOML array
                lines.append(f"{key} = {self._format_toml_list(value, 1)}")
            elif isinstance(value, dict):
                # Handle nested tables
                lines.append(f"\n[{table_name}.{key}]")
                for subkey, subvalue in value.items():
                    if isinstance(subvalue, list):
                        lines.append(f"{subkey} = {self._format_toml_list(subvalue, 1)}")
                    else:
                        lines.append(f"{subkey} = {repr(subvalue)}")
            else:
                # Simple key-value pair
                lines.append(f"{key} = {repr(value)}")
        
        return "\n".join(lines)
    
    def _format_optional_dependencies(self) -> str:
        """
        Format optional dependencies as TOML tables.
        
        Creates the [project.optional-dependencies] section with each
        extra group as a key-value pair containing an array of dependencies.
        
        Returns
        -------
        str
            TOML-formatted optional dependencies section, or empty string if none.
            
        Format Example
        -------------
        [project.optional-dependencies]
        dev = [
            "pytest>=7.0.0",
            "black>=23.0.0",
        ]
        test = [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
        ]
        """
        if not self.optional_dependencies:
            return ""
        
        lines = ["[project.optional-dependencies]"]
        
        for extra, deps in self.optional_dependencies.items():
            lines.append(f"{extra} = {self._format_toml_list(deps, 1)}")
        
        return "\n".join(lines)
    
    def _format_entry_points(self) -> str:
        """
        Format entry points as PEP 621-compliant TOML.
        
        Creates console scripts and plugin entry points according to
        PEP 621 specification for entry points.
        
        Returns
        -------
        str
            TOML-formatted entry points section, or empty string if none.
            
        Format Example
        -------------
        [project.entry-points."console_scripts"]
        mycli = "mypackage.cli:main"
        myhelper = "mypackage.helper:run"
        
        [project.entry-points."pytest11"]
        myplugin = "mypackage.pytest_plugin"
        
        Validation
        ----------
        Checks that each entry point follows the format "name = module:function"
        and warns if malformed entries are found.
        """
        if not self.entry_points:
            return ""
        
        lines = []
        
        for group, entries in self.entry_points.items():
            lines.append(f'[project.entry-points."{group}"]')
            
            for entry in entries:
                if "=" in entry:
                    name, value = entry.split("=", 1)
                    name = name.strip()
                    value = value.strip()
                    lines.append(f'{name} = "{value}"')
                else:
                    # Malformed entry point
                    self._warn(
                        f"Malformed entry point in group '{group}': '{entry}'. "
                        f"Expected format: 'name = module:function'"
                    )
                    lines.append(f'{entry} = "{entry}"')
        
        return "\n".join(lines)
    
    def _format_scripts(self) -> str:
        """
        Format scripts as TOML table.
        
        Creates the [project.scripts] table for executable script mappings.
        
        Returns
        -------
        str
            TOML-formatted scripts section, or empty string if none.
            
        Format Example
        -------------
        [project.scripts]
        run-server = "scripts/run_server.py"
        db-migrate = "scripts/migrate_db.sh"
        """
        if not self.scripts:
            return ""
        
        lines = ["[project.scripts]"]
        for name, path in self.scripts.items():
            lines.append(f'{name} = "{self._escape_toml_string(path)}"')
        
        return "\n".join(lines)
    
    def _format_project_section(self) -> str:
        """
        Format the main [project] section according to PEP 621.
        
        This is the core section containing all project metadata:
            - Basic info (name, version, description)
            - Dependency information
            - Author/maintainer credits
            - License and documentation
            - URLs and classifiers
        
        Returns
        -------
        str
            TOML-formatted project section.
            
        Section Structure
        ----------------
        [project]
        name = "package-name"
        version = "1.0.0"  # or dynamic
        description = "Brief description"
        readme = {file = "README.md", content-type = "text/markdown"}
        requires-python = ">=3.8"
        license = {text = "MIT"}
        authors = ["Name <email>"]
        dependencies = ["requests>=2.28.0"]
        keywords = ["web", "api"]
        classifiers = ["License :: OSI Approved :: MIT License"]
        
        PEP 621 Compliance
        -----------------
        - All required fields are included
        - Optional fields included when provided
        - Dynamic fields are properly marked
        - Arrays use multi-line formatting for readability
        """
        lines = ["[project]"]
        
        # Basic project identification
        lines.append(f'name = "{self._escape_toml_string(self.name)}"')
        
        # Version handling (static or dynamic)
        if "version" in self.dynamic_fields:
            lines.append("# Version is read from package __init__.py or VCS at build time")
            if self.version:
                lines.append(f"# Placeholder version: {self.version}")
        else:
            lines.append(f'version = "{self._escape_toml_string(self.version)}"')
        
        # Project description
        lines.append(f'description = "{self._escape_toml_string(self.description)}"')
        
        # Dynamic fields declaration
        if self.dynamic_fields:
            lines.append(f"dynamic = {self._format_toml_list(self.dynamic_fields)}")
        
        # README configuration (PEP 621 format)
        lines.append(f'readme = {{ file = "{self.readme}", content-type = "{self.readme_content_type}" }}')
        
        # Python version constraint
        lines.append(f'requires-python = "{self.python_requires}"')
        
        # License declaration
        if self.license_file:
            lines.append(f'license = {{ file = "{self.license_file}" }}')
        elif self.license_type:
            lines.append(f'license = {{ text = "{self.license_type.value}" }}')
        
        # Authorship attribution
        lines.append(f"authors = {self._format_toml_list(self.authors)}")
        
        # Maintainers (if different from authors)
        if self.maintainers != self.authors:
            lines.append(f"maintainers = {self._format_toml_list(self.maintainers)}")
        
        # Runtime dependencies
        lines.append(f"dependencies = {self._format_toml_list(self.dependencies)}")
        
        # Keywords for discoverability
        if self.keywords:
            lines.append(f"keywords = {self._format_toml_list(self.keywords)}")
        
        # Trove classifiers
        if self.classifiers:
            lines.append(f"classifiers = {self._format_toml_list(self.classifiers)}")
        
        return "\n".join(lines)
    
    def _format_build_section(self) -> str:
        """
        Format the [build-system] section.
        
        This section declares the build backend and its requirements for
        building and installing the package.
        
        Returns
        -------
        str
            TOML-formatted build system section.
            
        Format Example
        -------------
        [build-system]
        requires = ["setuptools>=61.0"]
        build-backend = "setuptools.build_meta"
        """
        return f"""[build-system]
requires = {self._format_toml_list(self._build_requires)}
build-backend = "{self.build_backend.value}" """
    
    def _format_tool_sections(self) -> List[str]:
        """
        Format all enabled tool configuration sections.
        
        This method generates TOML sections for development tools like:
            - Black (code formatting)
            - isort (import sorting)
            - pytest (testing)
            - mypy (type checking)
            - ruff (linting)
            - coverage (test coverage)
            - pre-commit (git hooks)
            - tox (multi-environment testing)
        
        Returns
        -------
        List[str]
            List of TOML-formatted tool configuration sections.
            
        Configuration Strategy
        ---------------------
        1. Start with well-researched default configurations
        2. Apply user overrides from tool_configs
        3. Deep-merge nested dictionaries
        4. Skip tools not in included_tools list
        """
        # Default configurations for each tool (battle-tested best practices)
        tool_defaults = {
            "black": {
                "line-length": 88,
                "target-version": ["py38"],
                "include": r'\.pyi?$',
                "extend-exclude": "build|dist|venv|\\.venv",
                "skip-string-normalization": False
            },
            "isort": {
                "profile": "black",
                "line_length": 88,
                "multi_line_output": 3,
                "include_trailing_comma": True,
                "force_grid_wrap": 0,
                "use_parentheses": True,
                "ensure_newline_before_comments": True
            },
            "pytest": {
                "testpaths": ["tests"],
                "python_files": "test_*.py",
                "python_classes": "Test*",
                "python_functions": "test_*",
                "addopts": "-v --strict-markers --tb=short --color=yes",
                "filterwarnings": ["ignore::DeprecationWarning"]
            },
            "mypy": {
                "python_version": "3.8",
                "strict": True,
                "warn_return_any": True,
                "warn_unused_configs": True,
                "ignore_missing_imports": False,
                "disallow_untyped_defs": True,
                "check_untyped_defs": True,
                "no_implicit_optional": True,
                "warn_redundant_casts": True,
                "warn_unused_ignores": True
            },
            "ruff": {
                "line-length": 88,
                "select": [
                    "E", "F", "W", "I", "N", "D", "C90", "UP", 
                    "B", "A", "C4", "SIM", "RET", "TCH", "ARG"
                ],
                "ignore": ["D100", "D104", "E501", "S101", "C901"],
                "target-version": "py38",
                "exclude": ["build", "dist", ".venv", "__pycache__", ".pytest_cache"],
                "fixable": ["A", "B", "C", "E", "F", "I", "N", "Q", "S", "T", "W"],
                "unfixable": []
            },
            "coverage": {
                "run": {
                    "source": ["src"],
                    "branch": True,
                    "parallel": True,
                    "omit": ["*/tests/*", "*/test_*.py"]
                },
                "report": {
                    "exclude_lines": [
                        "pragma: no cover",
                        "def __repr__",
                        "if self.debug:",
                        "if __name__ == .__main__.:",
                        "raise AssertionError",
                        "raise NotImplementedError",
                        "if 0:",
                        "if False:"
                    ],
                    "fail_under": 80,
                    "show_missing": True,
                    "skip_empty": False
                },
                "html": {
                    "directory": "htmlcov"
                }
            },
            "pre-commit": {
                "repos": [
                    {
                        "repo": "https://github.com/pre-commit/pre-commit-hooks",
                        "rev": "v4.5.0",
                        "hooks": [
                            {"id": "trailing-whitespace"},
                            {"id": "end-of-file-fixer"},
                            {"id": "check-yaml"},
                            {"id": "check-added-large-files"},
                            {"id": "check-json"},
                            {"id": "check-toml"},
                            {"id": "debug-statements"}
                        ]
                    },
                    {
                        "repo": "https://github.com/psf/black",
                        "rev": "23.12.1",
                        "hooks": [{"id": "black"}]
                    },
                    {
                        "repo": "https://github.com/astral-sh/ruff-pre-commit",
                        "rev": "v0.1.11",
                        "hooks": [{"id": "ruff", "args": ["--fix"]}]
                    },
                    {
                        "repo": "https://github.com/pre-commit/mirrors-mypy",
                        "rev": "v1.8.0",
                        "hooks": [{"id": "mypy", "additional_dependencies": ["types-all"]}]
                    }
                ],
                "default_language_version": {"python": "python3.11"},
                "fail_fast": False
            },
            "tox": {
                "legacy_tox_ini": """[tox]
min_version = 4.0
env_list = py38,py39,py310,py311,py312
skipsdist = False

[testenv]
set_env =
    PYTHONPATH = {toxinidir}/src
deps =
    pytest
    pytest-cov
    pytest-timeout
commands =
    pytest tests/ \\
        --cov=src \\
        --cov-report=term-missing \\
        --cov-report=xml \\
        --timeout=30

[testenv:lint]
deps =
    black
    ruff
    mypy
commands =
    black --check src/ tests/
    ruff check src/ tests/
    mypy src/
"""
            }
        }
        
        # Map tool names to their TOML table headers
        tool_headers = {
            "black": "tool.black",
            "isort": "tool.isort",
            "pytest": "tool.pytest.ini_options",
            "mypy": "tool.mypy",
            "ruff": "tool.ruff",
            "coverage": "tool.coverage",
            "pre-commit": "tool.pre-commit",
            "tox": "tool.tox",
        }
        
        sections = []
        
        # Generate configurations for each included tool
        for tool in self.included_tools:
            if tool in tool_defaults:
                # Start with default configuration
                config = tool_defaults[tool].copy()
                
                # Apply user overrides (deep merge)
                if tool in self.tool_configs:
                    self._deep_merge(config, self.tool_configs[tool])
                
                # Format as TOML table
                sections.append(self._format_toml_table(config, tool_headers[tool]))
                self._stats.tools_configured += 1
        
        # Add custom tool sections not in defaults
        for tool_name, config in self.tool_configs.items():
            if tool_name not in self.included_tools:
                sections.append(self._format_toml_table(config, f"tool.{tool_name}"))
                self._stats.tools_configured += 1
        
        return sections
    
    def _deep_merge(self, base: Dict, override: Dict) -> None:
        """
        Deep merge two dictionaries recursively.
        
        This method merges override dictionary into base dictionary,
        with override values taking precedence.
        
        Parameters
        ----------
        base : Dict
            Base dictionary to merge into (modified in-place).
        override : Dict
            Override dictionary whose values take precedence.
            
        Example
        -------
        >>> base = {"a": 1, "b": {"c": 2, "d": 3}}
        >>> override = {"b": {"c": 4, "e": 5}, "f": 6}
        >>> deep_merge(base, override)
        >>> base
        {"a": 1, "b": {"c": 4, "d": 3, "e": 5}, "f": 6}
        """
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                # Recursively merge nested dictionaries
                self._deep_merge(base[key], value)
            else:
                # Override or add the value
                base[key] = value
    
    def _format_setuptools_dynamic(self) -> str:
        """
        Configure dynamic version for setuptools backend.
        
        When version is marked as dynamic and setuptools is the build backend,
        this method generates the necessary tool.setuptools.dynamic configuration
        to read version from a source like __init__.py.
        
        Returns
        -------
        str
            TOML-formatted setuptools dynamic configuration,
            or empty string if not applicable.
            
        Format Example
        -------------
        [tool.setuptools.dynamic]
        version = {attr = "mypackage.__version__"}
        
        Notes
        -----
        Only applies when:
            - "version" is in dynamic_fields
            - build_backend is SETUPTOOLS
            - auto_detect_version is True
        """
        if "version" not in self.dynamic_fields:
            return ""
        
        if self.build_backend != BuildBackend.SETUPTOOLS:
            if self.verbose:
                print(f"[INFO] Dynamic version not configured for {self.build_backend.value} backend")
            return ""
        
        if not self.auto_detect_version:
            return ""
        
        # Determine version source
        if self.version_source:
            version_source = self.version_source
        elif self.name:
            package_name = self.name.replace('-', '_')
            version_source = f"attr:{package_name}.__version__"
        else:
            version_source = "attr:package.__version__"
        
        return f"""
[tool.setuptools.dynamic]
version = {{ {version_source} }}"""
    
    # ========================================================================
    # PUBLIC GENERATION METHODS
    # ========================================================================
    
    def generate(self) -> str:
        """
        Generate the complete pyproject.toml content.
        
        This method builds the entire pyproject.toml file structure with all
        configured sections, following PEP 621 specifications and TOML syntax.
        
        Returns
        -------
        str
            Complete pyproject.toml content as a string.
            
        Generation Process
        -----------------
        1. Create timestamp header (if enabled)
        2. Generate build-system section
        3. Generate project metadata section
        4. Add optional dependencies (if any)
        5. Add URLs section (if any)
        6. Add entry points (if any)
        7. Add scripts (if any)
        8. Add setuptools dynamic config (if applicable)
        9. Add all tool configurations
        10. Add extra custom sections
        
        Returns
        -------
        str
            Formatted TOML content ready for writing to pyproject.toml.
            
        Examples
        --------
        >>> gen = PyProjectGenerator(name="myproject", version="1.0.0")
        >>> content = gen.generate()
        >>> print(content[:500])
        # Generated by PyProjectGenerator on 2024-01-01 12:00:00
        # Project: myproject
        # Python version: >=3.8
        
        [build-system]
        requires = ["setuptools>=61.0"]
        build-backend = "setuptools.build_meta"
        
        [project]
        name = "myproject"
        version = "1.0.0"
        ...
        
        Performance
        -----------
        Generation time is typically <0.1 seconds for most configurations.
        """
        import time
        start_time = time.time()
        
        # Header with generation information
        header_lines = []
        if self.add_timestamp_comment:
            header_lines.append(f"# Generated by PyProjectGenerator on {self._generation_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            header_lines.append(f"# Project: {self.name}")
            header_lines.append(f"# Version: {self.version}")
            header_lines.append(f"# Python requires: {self.python_requires}")
            header_lines.append(f"# Build backend: {self.build_backend.value}")
            if self.verbose:
                header_lines.append(f"# Generation timestamp: {self._generation_timestamp.isoformat()}")
            header_lines.append("")
        header = "\n".join(header_lines)
        
        # Assemble all sections in logical order
        sections = [header]
        
        # 1. Build system declaration
        sections.append(self._format_build_section())
        
        # 2. Core project metadata
        sections.append(self._format_project_section())
        
        # 3. Optional dependencies (extras)
        optional_deps = self._format_optional_dependencies()
        if optional_deps:
            sections.append(optional_deps)
        
        # 4. Project URLs
        if self.urls:
            sections.append(self._format_toml_table(self.urls, "project.urls"))
        
        # 5. Entry points for console scripts and plugins
        entry_pts = self._format_entry_points()
        if entry_pts:
            sections.append(entry_pts)
        
        # 6. Script mappings
        scripts = self._format_scripts()
        if scripts:
            sections.append(scripts)
        
        # 7. Dynamic version configuration (setuptools only)
        setuptools_dynamic = self._format_setuptools_dynamic()
        if setuptools_dynamic:
            sections.append(setuptools_dynamic)
        
        # 8. Development tool configurations
        tool_sections = self._format_tool_sections()
        if tool_sections:
            sections.append("\n# ================================")
            sections.append("# Development Tool Configurations")
            sections.append("# ================================")
            sections.extend(tool_sections)
        
        # 9. Custom sections for project-specific needs
        if self.extra_sections:
            sections.append("\n# ================================")
            sections.append("# Custom Project Sections")
            sections.append("# ================================")
            for section_name, section_data in self.extra_sections.items():
                sections.append(self._format_toml_table(section_data, section_name))
        
        # Join all sections with double newlines for readability
        self._generated_content = "\n\n".join(filter(None, sections))
        
        # Update statistics
        self._stats.generation_time_seconds = time.time() - start_time
        self._stats.dependencies_count = len(self.dependencies)
        self._stats.optional_groups_count = len(self.optional_dependencies)
        self._stats.dynamic_fields_count = len(self.dynamic_fields)
        self._stats.output_size_bytes = len(self._generated_content.encode('utf-8'))
        
        # Log generation summary in verbose mode
        if self.verbose:
            print("\n" + "="*60)
            print("GENERATION COMPLETE")
            print("="*60)
            print(f"Time:           {self._stats.generation_time_seconds:.3f}s")
            print(f"Size:           {self._stats.output_size_bytes} bytes")
            print(f"Lines:          {len(self._generated_content.splitlines())}")
            print(f"Dependencies:   {self._stats.dependencies_count}")
            print(f"Optional groups: {self._stats.optional_groups_count}")
            print(f"Tools configured: {self._stats.tools_configured}")
            print(f"Warnings:       {self._stats.warnings_issued}")
            print("="*60 + "\n")
        
        return self._generated_content
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive generation statistics and metrics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
                - name: Project name
                - version: Project version
                - build_backend: Selected build backend
                - python_requires: Python version constraint
                - dependencies_count: Number of runtime dependencies
                - optional_groups_count: Number of extra groups
                - dynamic_fields_count: Number of dynamic fields
                - tools_configured: Number of tools configured
                - warnings_count: Number of warnings issued
                - generation_time: Time taken to generate (seconds)
                - output_size_bytes: Size of generated content
                - timestamp: Generation timestamp (ISO format)
                
        Examples
        --------
        >>> gen = PyProjectGenerator(name="mypkg", version="1.0.0")
        >>> gen.generate()
        >>> stats = gen.get_stats()
        >>> print(f"Generated {stats['dependencies_count']} dependencies")
        """
        return {
            "name": self.name,
            "version": self.version,
            "build_backend": self.build_backend.value,
            "python_requires": self.python_requires,
            "dependencies_count": self._stats.dependencies_count,
            "optional_groups_count": self._stats.optional_groups_count,
            "dynamic_fields_count": self._stats.dynamic_fields_count,
            "tools_configured": self._stats.tools_configured,
            "warnings_count": self._stats.warnings_issued,
            "generation_time": self._stats.generation_time_seconds,
            "output_size_bytes": self._stats.output_size_bytes,
            "timestamp": self._stats.timestamp.isoformat(),
        }
    
    def write(self, path: Union[str, Path]) -> str:
        """
        Generate and write pyproject.toml to a file.
        
        This convenience method combines generation and file writing
        in a single step.
        
        Parameters
        ----------
        path : str or Path
            Destination file path for the generated configuration.
            
        Returns
        -------
        str
            Absolute path to the written file.
            
        Raises
        ------
        IOError
            If file cannot be written due to permissions or disk errors.
            
        Examples
        --------
        >>> gen = PyProjectGenerator(name="myapp", version="1.0.0")
        >>> gen.write("pyproject.toml")
        '/home/user/project/pyproject.toml'
        
        >>> gen = PyProjectGenerator(name="lib", version="2.0.0")
        >>> gen.write("config/pyproject.toml")
        '/home/user/project/config/pyproject.toml'
        
        Notes
        -----
        The parent directory will be created automatically if it doesn't exist.
        """
        content = self.generate()
        path_obj = Path(path)
        
        # Ensure parent directory exists
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file with proper encoding
        try:
            path_obj.write_text(content, encoding="utf-8")
            if self.verbose:
                print(f"[INFO] Successfully written to: {path_obj.absolute()}")
                print(f"[INFO] File size: {path_obj.stat().st_size} bytes")
            return str(path_obj.absolute())
        except (IOError, OSError) as e:
            raise IOError(f"Failed to write {path_obj}: {e}")


# ============================================================================
# LEGACY FUNCTION INTERFACES (Backward Compatible)
# ============================================================================


def pyproject_template(
    name: str = "my_package",
    version: str = "0.1.0",
    description: str = "A short description of the project",
    authors: Optional[List[str]] = None,
    maintainers: Optional[List[str]] = None,
    dependencies: Optional[List[str]] = None,
    optional_dependencies: Optional[Dict[str, List[str]]] = None,
    python_requires: str = ">=3.8",
    build_backend: str = "setuptools.build_meta",
    license_name: Optional[str] = "MIT",
    license_file: Optional[str] = None,
    readme: str = "README.md",
    readme_content_type: str = "text/markdown",
    urls: Optional[Dict[str, str]] = None,
    keywords: Optional[List[str]] = None,
    classifiers: Optional[List[str]] = None,
    entry_points: Optional[Dict[str, List[str]]] = None,
    scripts: Optional[Dict[str, str]] = None,
    include_tool_sections: Union[bool, List[str]] = True,
    tool_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    dynamic_fields: Optional[List[str]] = None,
    extra_sections: Optional[Dict[str, Any]] = None,
    indent: int = 4,
    sort_dependencies: bool = False,
    add_timestamp_comment: bool = True,
    auto_detect_backend: bool = True,
    auto_detect_version: bool = True,
    version_source: Optional[str] = None,
) -> str:
    """
    Generate a pyproject.toml template with comprehensive configuration options.
    
    This is the primary legacy function interface for generating pyproject.toml
    content. It provides a simplified API while maintaining full functionality
    for most use cases. For advanced scenarios, consider using the
    PyProjectGenerator class directly.
    
    Parameters
    ----------
    name : str, default="my_package"
        Project name following PEP 508 naming conventions. Should be unique
        on PyPI if publishing. Typically matches the import name.
        
    version : str, default="0.1.0"
        Project version following PEP 440 semantic versioning. Format should be
        MAJOR.MINOR.PATCH (e.g., "1.2.3") with optional pre-release suffixes
        like "1.2.3a1" or "1.2.3.dev1".
        
    description : str, default="A short description of the project"
        One-line summary of the project (max 200 characters recommended).
        This appears on PyPI and package indices.
        
    authors : List[str], optional
        List of project authors in "Name <email@example.com>" format.
        Example: ["Jane Doe <jane@example.com>"]
        If not provided, defaults to ["Your Name <you@example.com>"].
        
    maintainers : List[str], optional
        List of current maintainers in same format as authors.
        If not provided, inherits from authors.
        
    dependencies : List[str], optional
        Project runtime dependencies following PEP 508 format.
        Examples: "requests>=2.28.0", "click>=8.0.0,<9.0.0"
        
    optional_dependencies : Dict[str, List[str]], optional
        Optional dependencies grouped by extra name.
        Example: {"dev": ["pytest>=7.0.0", "black>=23.0.0"]}
        
    python_requires : str, default=">=3.8"
        Python version requirement using version specifiers.
        Supports: >=, <=, >, <, ==, !=, ~=, and combinations.
        
    build_backend : str, default="setuptools.build_meta"
        Build system backend. Options:
            - "setuptools.build_meta": Classic setuptools
            - "hatchling.build": Modern hatchling
            - "poetry.core.masonry.api": Poetry
            - "flit_core.buildapi": Flit
            - "pdm.backend": PDM
            
    license_name : str, optional, default="MIT"
        SPDX license identifier (e.g., "MIT", "Apache-2.0", "BSD-3-Clause").
        If None, no license field is added.
        
    license_file : str, optional
        Path to external license file (e.g., "LICENSE.txt").
        Cannot be used with license_name.
        
    readme : str, default="README.md"
        Path to README file. Supports .md, .rst, and .txt formats.
        
    readme_content_type : str, default="text/markdown"
        MIME type of README file. Options:
            - "text/markdown": for .md files
            - "text/x-rst": for .rst files
            - "text/plain": for .txt files
            
    urls : Dict[str, str], optional
        Project URLs for PyPI display.
        Common keys: "Homepage", "Repository", "Documentation", "Issues"
        
    keywords : List[str], optional
        List of search keywords for PyPI indexing.
        Example: ["web", "framework", "async", "api"]
        
    classifiers : List[str], optional
        Trove classifiers for PyPI categorization.
        If not provided, automatically generated from configuration.
        
    entry_points : Dict[str, List[str]], optional
        Console scripts and plugin entry points.
        Example: {"console_scripts": ["cli = package.cli:main"]}
        
    scripts : Dict[str, str], optional
        Executable script mappings (alternative to entry_points).
        Example: {"run-server": "scripts/run_server.py"}
        
    include_tool_sections : bool or List[str], default=True
        Controls tool configuration sections to include.
            - True: Include all standard tools
            - False: Include no tools
            - List: Include only specified tools
        Options: "black", "isort", "pytest", "mypy", "ruff", "coverage",
                 "pre-commit", "tox"
                 
    tool_configs : Dict[str, Dict[str, Any]], optional
        Custom tool configuration overrides.
        Example: {"black": {"line-length": 100}, "ruff": {"select": ["E", "F"]}}
        
    dynamic_fields : List[str], optional
        Fields determined at build time. Common: ["version"]
        
    extra_sections : Dict[str, Any], optional
        Additional custom TOML sections.
        Example: {"myproject": {"plugin-dir": "plugins/"}}
        
    indent : int, default=4
        Number of spaces for TOML indentation.
        
    sort_dependencies : bool, default=False
        Sort dependency lists alphabetically.
        
    add_timestamp_comment : bool, default=True
        Add generation timestamp comment at top of file.
        
    auto_detect_backend : bool, default=True
        Automatically determine build system requirements.
        
    auto_detect_version : bool, default=True
        Automatically configure dynamic version detection.
        
    version_source : str, optional
        Source for dynamic version (for setuptools).
        Examples: "attr:package.__version__", "file:VERSION.txt"
        
    Returns
    -------
    str
        Formatted pyproject.toml content as a string.
        
    Raises
    ------
    ValueError
        If validation fails (invalid name, version, or conflicting options).
        
    Examples
    --------
    Minimal configuration:
    >>> content = pyproject_template(
    ...     name="my-package",
    ...     version="1.0.0",
    ...     description="A great package",
    ...     authors=["Jane Doe <jane@example.com>"]
    ... )
    
    Full configuration:
    >>> content = pyproject_template(
    ...     name="enterprise-lib",
    ...     version="2.0.0",
    ...     build_backend="hatchling.build",
    ...     license_name="Apache-2.0",
    ...     dependencies=["requests>=2.28.0", "click>=8.0.0"],
    ...     optional_dependencies={"dev": ["pytest>=7.0.0"]},
    ...     entry_points={"console_scripts": ["cli = lib.cli:main"]},
    ...     include_tool_sections=["black", "ruff", "mypy"]
    ... )
    
    Dynamic version detection:
    >>> content = pyproject_template(
    ...     name="dynamic-version",
    ...     version="0.1.0",  # Placeholder
    ...     dynamic_fields=["version"],
    ...     version_source="attr:dynamic_version.__version__"
    ... )
    
    Notes
    -----
    This function is a wrapper around PyProjectGenerator for backward
    compatibility. For new code, consider using the PyProjectGenerator class
    directly for more features and better type safety.
    
    See Also
    --------
    PyProjectGenerator : Full-featured generator class
    write_pyproject : Direct file writing function
    """
    # Convert string backend to enum
    backend_map = {
        "setuptools.build_meta": BuildBackend.SETUPTOOLS,
        "hatchling.build": BuildBackend.HATCHLING,
        "poetry.core.masonry.api": BuildBackend.POETRY,
        "flit_core.buildapi": BuildBackend.FLIT,
        "pdm.backend": BuildBackend.PDM,
    }
    backend_enum = backend_map.get(build_backend, BuildBackend.SETUPTOOLS)
    
    # Convert license string to enum
    license_enum = None
    if license_name:
        license_map = {
            "MIT": LicenseType.MIT,
            "Apache-2.0": LicenseType.APACHE_2,
            "BSD-3-Clause": LicenseType.BSD_3,
            "GPL-3.0-or-later": LicenseType.GPL_3,
            "ISC": LicenseType.ISC,
            "MPL-2.0": LicenseType.MPL_2,
            "Unlicense": LicenseType.UNLICENSE,
            "Proprietary": LicenseType.PROPRIETARY,
        }
        license_enum = license_map.get(license_name, LicenseType.MIT)
    
    # Handle include_tool_sections parameter
    if isinstance(include_tool_sections, list):
        included_tools = include_tool_sections
    elif include_tool_sections is True:
        included_tools = None  # Use default
    else:
        included_tools = []
    
    # Create generator instance
    generator = PyProjectGenerator(
        name=name,
        version=version,
        description=description,
        authors=authors,
        maintainers=maintainers,
        dependencies=dependencies,
        optional_dependencies=optional_dependencies,
        python_requires=python_requires,
        build_backend=backend_enum,
        license_type=license_enum,
        license_file=license_file,
        readme=readme,
        readme_content_type=readme_content_type,
        urls=urls,
        keywords=keywords,
        classifiers=classifiers,
        entry_points=entry_points,
        scripts=scripts,
        included_tools=included_tools,
        tool_configs=tool_configs,
        dynamic_fields=dynamic_fields,
        extra_sections=extra_sections,
        indent=indent,
        sort_dependencies=sort_dependencies,
        add_timestamp_comment=add_timestamp_comment,
        auto_detect_backend=auto_detect_backend,
        auto_detect_version=auto_detect_version,
        version_source=version_source,
        verbose=False,  # Keep legacy function quiet by default
        show_warnings=True,
    )
    
    return generator.generate()


def write_pyproject(path: Union[str, Path], **kwargs) -> None:
    """
    Generate pyproject.toml and write it directly to a file.
    
    This convenience function combines template generation and file writing
    in one call, perfect for scripts and automated workflows.
    
    Parameters
    ----------
    path : str or Path
        Destination file path where pyproject.toml will be written.
        The parent directory will be created if it doesn't exist.
        
    **kwargs
        Additional keyword arguments passed to pyproject_template().
        See pyproject_template() documentation for all available options:
            - name, version, description
            - authors, maintainers
            - dependencies, optional_dependencies
            - python_requires, build_backend
            - license_name, license_file
            - readme, urls, keywords, classifiers
            - entry_points, scripts
            - include_tool_sections, tool_configs
            - dynamic_fields, extra_sections
            - sort_dependencies, add_timestamp_comment
            - auto_detect_backend, auto_detect_version
            - version_source
            
    Returns
    -------
    None
        Writes file directly to disk; does not return content.
        
    Raises
    ------
    ValueError
        If validation fails.
    IOError
        If file cannot be written.
        
    Examples
    --------
    Basic usage:
    >>> write_pyproject(
    ...     "pyproject.toml",
    ...     name="my-package",
    ...     version="1.0.0",
    ...     description="An amazing package",
    ...     authors=["Jane Doe <jane@example.com>"]
    ... )
    
    Advanced configuration:
    >>> write_pyproject(
    ...     "config/pyproject.toml",
    ...     name="enterprise-lib",
    ...     version="2.0.0",
    ...     build_backend="hatchling.build",
    ...     dependencies=["requests>=2.28.0"],
    ...     optional_dependencies={"dev": ["pytest>=7.0.0"]}
    ... )
    
    Dynamic version:
    >>> write_pyproject(
    ...     "pyproject.toml",
    ...     name="dynamic-version",
    ...     version="0.1.0",  # Placeholder
    ...     dynamic_fields=["version"],
    ...     version_source="attr:package.__version__"
    ... )
    
    Notes
    -----
    This function:
        1. Calls pyproject_template() to generate content
        2. Creates parent directories if they don't exist
        3. Writes the content with UTF-8 encoding
        4. Does not return the content (makes side-effects explicit)
        
    For programmatic use where content is needed, use pyproject_template()
    directly instead.
    
    See Also
    --------
    pyproject_template : Generate content without writing
    PyProjectGenerator : Full-featured generator with more options
    """
    content = pyproject_template(**kwargs)
    path_obj = Path(path)
    
    # Ensure directory exists
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Write file with UTF-8 encoding
    path_obj.write_text(content, encoding="utf-8")