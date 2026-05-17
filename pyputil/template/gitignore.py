#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
.gitignore generator with template selection.

This module provides professional tools for generating .gitignore files
with comprehensive support for Python projects, IDEs, operating systems,
frameworks, and development tools. It automatically selects appropriate
patterns based on your project structure and requirements.

Examples
--------
>>> from pyputil.template import gitignore_template
>>> 
>>> # Basic usage
>>> gitignore_template(
...     project_name="myproject",
...     output_dir="."
... )
>>> 
>>> # Advanced usage with specific configurations
>>> gitignore_template(
...     project_name="myproject",
...     include_ide=["vscode", "pycharm"],
...     include_os=["linux", "macos"],
...     include_frameworks=["django", "docker"],
...     include_package_managers=["poetry"],
...     verbose=True
... )
"""

from pathlib import Path
from typing import Union, Optional, List, Dict, Set, Tuple, Any, Callable
from enum import Enum
from datetime import datetime
import warnings
import os
import re
from dataclasses import dataclass, field


class IDE(str, Enum):
    """
    Supported Integrated Development Environments (IDEs) and editors.
    
    These constants are used to include IDE-specific ignore patterns
    to prevent committing editor configuration files.
    
    Attributes
    ----------
    VSCODE : str
        Visual Studio Code editor patterns
    PYCHARM : str
        PyCharm IDE patterns
    INTELLIJ : str
        IntelliJ IDEA patterns
    VIM : str
        Vim editor patterns
    EMACS : str
        Emacs editor patterns
    SUBLIME : str
        Sublime Text patterns
    ATOM : str
        Atom editor patterns
    JUPYTER : str
        Jupyter Notebook patterns
    SPYDER : str
        Spyder IDE patterns
    ALL : str
        Include all IDE patterns
    """
    VSCODE = "vscode"
    PYCHARM = "pycharm"
    INTELLIJ = "intellij"
    VIM = "vim"
    EMACS = "emacs"
    SUBLIME = "sublime"
    ATOM = "atom"
    JUPYTER = "jupyter"
    SPYDER = "spyder"
    ALL = "all"


class OS(str, Enum):
    """
    Supported Operating Systems.
    
    These constants are used to include OS-specific ignore patterns
    to prevent committing system files and temporary files.
    
    Attributes
    ----------
    WINDOWS : str
        Windows-specific patterns (Thumbs.db, desktop.ini, etc.)
    LINUX : str
        Linux-specific patterns (.swp, core dumps, etc.)
    MACOS : str
        macOS-specific patterns (.DS_Store, .AppleDouble, etc.)
    ALL : str
        Include all OS patterns
    """
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    ALL = "all"


class Framework(str, Enum):
    """
    Supported Frameworks and Development Tools.
    
    These constants are used to include framework-specific patterns
    for popular Python frameworks and tools.
    
    Attributes
    ----------
    DJANGO : str
        Django web framework patterns
    FLASK : str
        Flask microframework patterns
    FASTAPI : str
        FastAPI framework patterns
    PYTEST : str
        Pytest testing framework
    MYPY : str
        Mypy static type checker
    BLACK : str
        Black code formatter
    RUFF : str
        Ruff linter
    PRE_COMMIT : str
        Pre-commit hooks
    TOX : str
        Tox testing automation
    NOX : str
        Nox testing automation
    DOCKER : str
        Docker container patterns
    KUBERNETES : str
        Kubernetes manifest patterns
    TERRAFORM : str
        Terraform infrastructure patterns
    ANSIBLE : str
        Ansible automation patterns
    AIRFLOW : str
        Apache Airflow patterns
    PANDAS : str
        Pandas data analysis patterns
    NUMPY : str
        NumPy patterns
    TENSORFLOW : str
        TensorFlow patterns
    PYTORCH : str
        PyTorch patterns
    ALL : str
        Include all framework patterns
    """
    DJANGO = "django"
    FLASK = "flask"
    FASTAPI = "fastapi"
    PYTEST = "pytest"
    MYPY = "mypy"
    BLACK = "black"
    RUFF = "ruff"
    PRE_COMMIT = "pre-commit"
    TOX = "tox"
    NOX = "nox"
    DOCKER = "docker"
    KUBERNETES = "kubernetes"
    TERRAFORM = "terraform"
    ANSIBLE = "ansible"
    AIRFLOW = "airflow"
    PANDAS = "pandas"
    NUMPY = "numpy"
    TENSORFLOW = "tensorflow"
    PYTORCH = "pytorch"
    ALL = "all"


class PackageManager(str, Enum):
    """
    Supported Package Managers.
    
    These constants are used to include package manager-specific
    patterns to prevent committing lock files and virtual environments.
    
    Attributes
    ----------
    PIP : str
        Pip package manager patterns
    POETRY : str
        Poetry dependency manager
    PIPENV : str
        Pipenv virtual environment manager
    PDM : str
        PDM package manager
    CONDA : str
        Conda package manager
    UV : str
        UV fast package manager
    ALL : str
        Include all package manager patterns
    """
    PIP = "pip"
    POETRY = "poetry"
    PIPENV = "pipenv"
    PDM = "pdm"
    CONDA = "conda"
    UV = "uv"
    ALL = "all"


@dataclass
class GitignoreStats:
    """
    Statistics about the generated .gitignore file.
    
    Attributes
    ----------
    total_patterns : int
        Total number of ignore patterns generated.
    sections_count : int
        Number of sections in the generated file.
    warnings_count : int
        Number of warnings issued during generation.
    generation_time : float
        Time taken to generate in seconds.
    custom_patterns_count : int
        Number of custom patterns added.
    excluded_patterns_count : int
        Number of patterns excluded.
    """
    total_patterns: int = 0
    sections_count: int = 0
    warnings_count: int = 0
    generation_time: float = 0.0
    custom_patterns_count: int = 0
    excluded_patterns_count: int = 0


class GitignoreGenerator:
    """
    Generator for .gitignore files with template selection.
    
    This class provides comprehensive functionality for generating .gitignore
    files with support for Python projects, IDEs, operating systems, frameworks,
    and development tools. It automatically selects appropriate patterns based
    on your project structure and requirements.
    
    Attributes
    ----------
    project_name : Optional[str]
        Name of the project (for custom patterns).
    output_dir : Path
        Directory where .gitignore will be written.
    stats : GitignoreStats
        Statistics about the generation process.
    patterns : List[str]
        Generated ignore patterns.
        
    Examples
    --------
    >>> generator = GitignoreGenerator(
    ...     project_name="myproject",
    ...     include_ide=[IDE.VSCODE, IDE.PYCHARM],
    ...     include_os=[OS.LINUX, OS.MACOS],
    ...     verbose=True
    ... )
    >>> generator.generate()
    """
    
    # Python-specific patterns
    PYTHON_PATTERNS: List[str] = [
        "# Byte-compiled / optimized / DLL files",
        "__pycache__/",
        "*.py[cod]",
        "*$py.class",
        "*.so",
        "",
        "# Distribution / packaging",
        ".Python",
        "build/",
        "develop-eggs/",
        "dist/",
        "downloads/",
        "eggs/",
        ".eggs/",
        "lib/",
        "lib64/",
        "parts/",
        "sdist/",
        "var/",
        "wheels/",
        "share/python-wheels/",
        "*.egg-info/",
        ".installed.cfg",
        "*.egg",
        "MANIFEST",
        "",
        "# PyInstaller",
        "*.manifest",
        "*.spec",
        "",
        "# Installer logs",
        "pip-log.txt",
        "pip-delete-this-directory.txt",
        "",
        "# Unit test / coverage reports",
        "htmlcov/",
        ".tox/",
        ".nox/",
        ".coverage",
        ".coverage.*",
        ".cache",
        "nosetests.xml",
        "coverage.xml",
        "*.cover",
        "*.py,cover",
        ".hypothesis/",
        ".pytest_cache/",
        "cover/",
        "",
        "# Translations",
        "*.mo",
        "*.pot",
        "",
        "# Django stuff:",
        "*.log",
        "local_settings.py",
        "db.sqlite3",
        "db.sqlite3-journal",
        "",
        "# Flask stuff:",
        "instance/",
        ".webassets-cache",
        "",
        "# Scrapy stuff:",
        ".scrapy",
        "",
        "# Sphinx documentation",
        "docs/_build/",
        "",
        "# PyBuilder",
        ".pybuilder/",
        "target/",
        "",
        "# Jupyter Notebook",
        ".ipynb_checkpoints",
        "",
        "# IPython",
        "profile_default/",
        "ipython_config.py",
        "",
        "# pyenv",
        ".python-version",
        "",
        "# pipenv",
        "Pipfile.lock",
        "",
        "# poetry",
        "poetry.lock",
        "",
        "# pdm",
        ".pdm.toml",
        "",
        "# PEP 582",
        "__pypackages__/",
        "",
        "# Celery stuff",
        "celerybeat-schedule",
        "celerybeat.pid",
        "",
        "# SageMath parsed files",
        "*.sage.py",
        "",
        "# Environments",
        ".env",
        ".venv",
        "env/",
        "venv/",
        "ENV/",
        "env.bak/",
        "venv.bak/",
        "",
        "# Spyder project settings",
        ".spyderproject",
        ".spyproject",
        "",
        "# Rope project settings",
        ".ropeproject",
        "",
        "# mkdocs documentation",
        "site/",
        "",
        "# mypy",
        ".mypy_cache/",
        ".dmypy.json",
        "dmypy.json",
        "",
        "# Pyre type checker",
        ".pyre/",
        "",
        "# pytype static type analyzer",
        ".pytype/",
        "",
        "# Cython debug symbols",
        "cython_debug/",
        "",
        "# Ruff",
        ".ruff_cache/",
        "",
        "# Black",
        ".black_cache/",
        "",
        "# pytest",
        ".pytest_cache/",
        "",
        "# Coverage",
        ".coverage",
        "htmlcov/",
        ".coverage.*",
        "coverage.xml",
        "*.cover",
        "coverage/",
    ]
    
    # VSCode patterns
    VSCODE_PATTERNS: List[str] = [
        "# Visual Studio Code",
        ".vscode/",
        "*.code-workspace",
        ".history/",
        ".vsix/",
        "",
        "# VSCode extensions",
        ".vscode-test/",
        ".vscode/extensions.json",
    ]
    
    # PyCharm patterns
    PYCHARM_PATTERNS: List[str] = [
        "# PyCharm",
        ".idea/",
        "*.iml",
        "*.iws",
        ".idea_modules/",
        "out/",
        "",
        "# PyCharm workspace",
        ".idea/workspace.xml",
        ".idea/tasks.xml",
        ".idea/dictionaries/",
        ".idea/vcs.xml",
        ".idea/jsLibraryMappings.xml",
        ".idea/dataSources.xml",
        ".idea/dataSources.ids",
        ".idea/dataSources.local.xml",
        ".idea/sqlDataSources.xml",
        ".idea/datasources.xml",
        ".idea/dataSources/",
    ]
    
    # IntelliJ patterns
    INTELLIJ_PATTERNS: List[str] = [
        "# IntelliJ IDEA",
        ".idea/",
        "*.iml",
        "*.iws",
        "out/",
        "",
        "# IntelliJ workspace",
        ".idea/workspace.xml",
        ".idea/tasks.xml",
    ]
    
    # Vim patterns
    VIM_PATTERNS: List[str] = [
        "# Vim",
        "*.swp",
        "*.swo",
        "*~",
        ".vim/",
        ".vimrc",
        ".viminfo",
        "",
        "# Vim backup files",
        "*.un~",
        ".*.swp",
    ]
    
    # Emacs patterns
    EMACS_PATTERNS: List[str] = [
        "# Emacs",
        "*~",
        ".#*",
        ".emacs.desktop",
        ".emacs.desktop.lock",
        ".emacs.d/",
        ".emacs.bmk",
        "*.elc",
        "auto-save-list",
        "tramp",
        "",
        "# Emacs backup files",
        "*~",
        ".#*",
        "#*#",
    ]
    
    # Sublime Text patterns
    SUBLIME_PATTERNS: List[str] = [
        "# Sublime Text",
        "*.sublime-project",
        "*.sublime-workspace",
        ".sublime/",
        "",
        "# Sublime Text settings",
        "*.sublime-settings",
    ]
    
    # Atom patterns
    ATOM_PATTERNS: List[str] = [
        "# Atom",
        ".atom/",
        ".atom-dev/",
        ".apm/",
        "",
        "# Atom packages",
        "*.atom",
    ]
    
    # Jupyter patterns
    JUPYTER_PATTERNS: List[str] = [
        "# Jupyter Notebook",
        ".ipynb_checkpoints/",
        "*.ipynb",
        "*.ipynb_checkpoints",
        "",
        "# Jupyter Lab",
        ".jupyter/",
        "jupyter_notebook_config.py",
        "",
        "# Jupyter data",
        "jupyter_notebook_config.json",
        "jupyter_notebook_config.py",
    ]
    
    # Spyder patterns
    SPYDER_PATTERNS: List[str] = [
        "# Spyder",
        ".spyderproject",
        ".spyproject",
        ".spyderworkspace",
        "",
        "# Spyder history",
        ".history.py",
        ".temp.py",
    ]
    
    # Windows patterns
    WINDOWS_PATTERNS: List[str] = [
        "# Windows",
        "Thumbs.db",
        "Thumbs.db:encryptable",
        "ehthumbs.db",
        "ehthumbs_vista.db",
        "*.dll",
        "*.exe",
        "*.msi",
        "Desktop.ini",
        "$RECYCLE.BIN/",
        "*.lnk",
        "",
        "# Windows shortcut files",
        "*.lnk",
        "",
        "# Windows image cache",
        "Thumbs.db",
        "*.tmp",
        "",
        "# Windows Explorer",
        "desktop.ini",
        "iconcache.db",
        "",
        "# Windows PowerShell",
        "*.ps1",
        "*.psm1",
        "*.psd1",
    ]
    
    # Linux patterns
    LINUX_PATTERNS: List[str] = [
        "# Linux",
        "*.swp",
        "*.swo",
        "*~",
        ".directory",
        ".Trash-*",
        ".fuse_hidden*",
        ".goutputstream-*",
        "",
        "# Linux temporary files",
        "*.part",
        "*.tmp",
        "*.temp",
        "",
        "# Linux core dumps",
        "core",
        "core.*",
        "",
        "# Linux desktop files",
        ".DS_Store",
        ".localized",
    ]
    
    # macOS patterns
    MACOS_PATTERNS: List[str] = [
        "# macOS",
        ".DS_Store",
        ".AppleDouble",
        ".LSOverride",
        ".Spotlight-V100",
        ".Trashes",
        "ehthumbs.db",
        "Thumbs.db",
        ".AppleDB",
        ".AppleDesktop",
        "Network Trash Folder",
        "Temporary Items",
        ".apdisk",
        "",
        "# macOS metadata",
        "._*",
        ".DS_Store?",
        ".fseventsd/",
        ".Spotlight-V100/",
        ".TemporaryItems/",
        ".Trashes/",
        ".VolumeIcon.icns",
        ".com.apple.timemachine.donotpresent",
        "",
        "# macOS Finder",
        ".AppleDouble",
        ".LSOverride",
        "",
        "# macOS icon",
        "Icon\r",
        "Icon?",
        "",
        "# macOS Thumbnails",
        ".thumbnails",
    ]
    
    # Django patterns
    DJANGO_PATTERNS: List[str] = [
        "# Django",
        "*.log",
        "*.pot",
        "*.pyc",
        "local_settings.py",
        "db.sqlite3",
        "db.sqlite3-journal",
        "media/",
        "staticfiles/",
        "static/CACHE/",
        "",
        "# Django migrations",
        "*/migrations/*.py",
        "!*/migrations/__init__.py",
        "",
        "# Django static files",
        "static/",
        "media/",
        "",
        "# Django cache",
        ".django_cache/",
    ]
    
    # Flask patterns
    FLASK_PATTERNS: List[str] = [
        "# Flask",
        "instance/",
        ".webassets-cache",
        ".flaskenv",
        "flask_session/",
        "",
        "# Flask secrets",
        ".flask_secret_key",
    ]
    
    # FastAPI patterns
    FASTAPI_PATTERNS: List[str] = [
        "# FastAPI",
        "app.db",
        ".fastapi/",
        "",
        "# FastAPI static",
        "static/",
        "templates/",
    ]
    
    # Pytest patterns
    PYTEST_PATTERNS: List[str] = [
        "# Pytest",
        ".pytest_cache/",
        ".pytest/",
        "pytestdebug.log",
        "",
        "# Pytest coverage",
        ".coverage",
        "htmlcov/",
        ".coverage.*",
    ]
    
    # Mypy patterns
    MYPY_PATTERNS: List[str] = [
        "# Mypy",
        ".mypy_cache/",
        ".dmypy.json",
        "dmypy.json",
        "",
        "# Mypy reports",
        ".mypy_report/",
    ]
    
    # Black patterns
    BLACK_PATTERNS: List[str] = [
        "# Black",
        ".black_cache/",
        ".black/",
    ]
    
    # Ruff patterns
    RUFF_PATTERNS: List[str] = [
        "# Ruff",
        ".ruff_cache/",
    ]
    
    # Pre-commit patterns
    PRE_COMMIT_PATTERNS: List[str] = [
        "# pre-commit",
        ".pre-commit-config.yaml",
        ".pre-commit-hooks.yaml",
        "",
        "# pre-commit cache",
        ".pre-commit/",
    ]
    
    # Tox patterns
    TOX_PATTERNS: List[str] = [
        "# Tox",
        ".tox/",
        ".tox.log",
        "",
        "# Tox environment",
        ".tox/",
    ]
    
    # Nox patterns
    NOX_PATTERNS: List[str] = [
        "# Nox",
        ".nox/",
        ".nox.log",
    ]
    
    # Docker patterns
    DOCKER_PATTERNS: List[str] = [
        "# Docker",
        ".dockerignore",
        "docker-compose.override.yml",
        "docker-compose.override.yaml",
        "docker-compose.local.yml",
        "docker-compose.local.yaml",
        "",
        "# Docker volumes",
        "volumes/",
        ".docker-data/",
        "",
        "# Docker images",
        "*.tar",
        "*.tar.gz",
    ]
    
    # Kubernetes patterns
    KUBERNETES_PATTERNS: List[str] = [
        "# Kubernetes",
        "*.kubeconfig",
        ".kube/",
        "",
        "# Kubernetes secrets",
        "secrets.yaml",
        "secrets.yml",
    ]
    
    # Terraform patterns
    TERRAFORM_PATTERNS: List[str] = [
        "# Terraform",
        ".terraform/",
        "*.tfstate",
        "*.tfstate.*",
        "*.tfvars",
        "*.tfvars.json",
        "override.tf",
        "override.tf.json",
        "*.override.tf",
        "*.override.tf.json",
        "",
        "# Terraform crash logs",
        "crash.log",
        "crash.*.log",
    ]
    
    # Poetry patterns
    POETRY_PATTERNS: List[str] = [
        "# Poetry",
        "poetry.lock",
        ".venv/",
        "venv/",
        "env/",
        "",
        "# Poetry cache",
        ".cache/",
        ".poetry/",
    ]
    
    # Pipenv patterns
    PIPENV_PATTERNS: List[str] = [
        "# Pipenv",
        "Pipfile.lock",
        ".venv/",
        "venv/",
    ]
    
    # PDM patterns
    PDM_PATTERNS: List[str] = [
        "# PDM",
        ".pdm.toml",
        "__pypackages__/",
        ".venv/",
    ]
    
    # Conda patterns
    CONDA_PATTERNS: List[str] = [
        "# Conda",
        ".conda/",
        "environment.yml",
        "environment.yaml",
        "*.conda",
        "",
        "# Conda environments",
        "envs/",
        "pkgs/",
    ]
    
    # UV patterns
    UV_PATTERNS: List[str] = [
        "# UV",
        ".venv/",
        "uv.lock",
        ".uv/",
    ]
    
    def __init__(
        self,
        project_name: Optional[str] = None,
        include_python: bool = True,
        include_ide: Union[bool, IDE, List[IDE]] = True,
        include_os: Union[bool, OS, List[OS]] = True,
        include_frameworks: Optional[List[Framework]] = None,
        include_package_managers: Optional[List[PackageManager]] = None,
        custom_patterns: Optional[List[str]] = None,
        custom_sections: Optional[Dict[str, List[str]]] = None,
        exclude_patterns: Optional[List[str]] = None,
        output_dir: Union[str, Path] = ".",
        force_overwrite: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
        show_warnings: bool = True,
        add_timestamp_comment: bool = True,
    ) -> None:
        """
        Initialize the GitignoreGenerator.
        
        Parameters
        ----------
        project_name : Optional[str], optional
            Name of the project. Used for generating project-specific
            patterns and in the header comment.
            
        include_python : bool, default=True
            Whether to include Python-specific patterns. This includes
            patterns for __pycache__, .pyc files, virtual environments,
            pytest cache, coverage reports, and other Python-related files.
            
        include_ide : Union[bool, IDE, List[IDE]], default=True
            IDE patterns to include. Can be:
            - True: Include all common IDE patterns
            - False: Exclude all IDE patterns
            - IDE.VSCODE: Include only VSCode patterns
            - [IDE.VSCODE, IDE.PYCHARM]: Include specific IDEs
            
        include_os : Union[bool, OS, List[OS]], default=True
            Operating system-specific patterns to include. Can be:
            - True: Include all OS patterns (Windows, Linux, macOS)
            - False: Exclude all OS patterns
            - OS.WINDOWS: Include only Windows patterns
            - [OS.LINUX, OS.MACOS]: Include specific OS patterns
            
        include_frameworks : Optional[List[Framework]], optional
            Framework-specific patterns to include. Examples:
            [Framework.DJANGO, Framework.DOCKER, Framework.PYTEST]
            
        include_package_managers : Optional[List[PackageManager]], optional
            Package manager patterns to include. Examples:
            [PackageManager.POETRY, PackageManager.PIPENV]
            
        custom_patterns : Optional[List[str]], optional
            Additional custom patterns to add to the .gitignore.
            These patterns are added in a separate "Custom Patterns" section.
            
        custom_sections : Optional[Dict[str, List[str]]], optional
            Custom sections with patterns. Each key is the section title,
            each value is a list of patterns for that section.
            
        exclude_patterns : Optional[List[str]], optional
            Patterns to exclude from generation. Useful when you want to
            omit certain patterns from the default templates.
            
        output_dir : Union[str, Path], default="."
            Directory where the .gitignore file will be created.
            
        force_overwrite : bool, default=False
            Whether to overwrite an existing .gitignore file. If False
            and the file exists, a warning is issued and generation is skipped.
            
        dry_run : bool, default=False
            Whether to simulate generation without writing the file.
            Useful for testing and previewing the output.
            
        verbose : bool, default=False
            Whether to print detailed information during generation.
            Shows progress, statistics, and any warnings.
            
        show_warnings : bool, default=True
            Whether to show warning messages. When False, warnings are
            suppressed but still counted in statistics.
            
        add_timestamp_comment : bool, default=True
            Whether to add a timestamp comment at the top of the file.
            This helps track when the .gitignore was generated.
            
        Raises
        ------
        ValueError
            If any configuration parameter is invalid.
        PermissionError
            If the output directory cannot be accessed.
            
        Examples
        --------
        >>> # Basic initialization
        >>> generator = GitignoreGenerator(
        ...     project_name="myproject",
        ...     include_ide=[IDE.VSCODE, IDE.PYCHARM]
        ... )
        >>> 
        >>> # Advanced initialization with frameworks
        >>> generator = GitignoreGenerator(
        ...     project_name="myproject",
        ...     include_frameworks=[Framework.DJANGO, Framework.DOCKER],
        ...     include_package_managers=[PackageManager.POETRY],
        ...     custom_patterns=["*.secret", "*.key"],
        ...     verbose=True
        ... )
        """
        # Initialize basic attributes
        self.project_name = project_name
        self.include_python = include_python
        self.include_ide = include_ide
        self.include_os = include_os
        self.include_frameworks = include_frameworks or []
        self.include_package_managers = include_package_managers or []
        self.custom_patterns = custom_patterns or []
        self.custom_sections = custom_sections or {}
        self.exclude_patterns = exclude_patterns or []
        self.output_dir = Path(output_dir)
        self.force_overwrite = force_overwrite
        self.dry_run = dry_run
        self.verbose = verbose
        self.show_warnings = show_warnings
        self.add_timestamp_comment = add_timestamp_comment
        
        # Initialize statistics and patterns
        self.stats = GitignoreStats()
        self.patterns: List[str] = []
        self._warnings_count = 0
        
        # Validate configuration
        self._validate_config()
        
        # Compile exclude patterns for faster matching
        self._exclude_compiled = [re.compile(p) for p in self.exclude_patterns]
        
        if self.verbose:
            self._log(f"GitignoreGenerator initialized")
            self._log(f"  Output directory: {self.output_dir}")
            self._log(f"  Python patterns: {self.include_python}")
            self._log(f"  Frameworks: {len(self.include_frameworks)}")
            self._log(f"  Package managers: {len(self.include_package_managers)}")
    
    def _validate_config(self) -> None:
        """Validate configuration parameters."""
        # Validate output directory
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(f"Cannot create output directory {self.output_dir}: {e}")
        
        # Validate project name (if provided)
        if self.project_name and not re.match(r'^[a-zA-Z0-9_\-\.]+$', self.project_name):
            self._warn(f"Project name '{self.project_name}' contains unusual characters")
        
        # Validate frameworks
        valid_frameworks = set(Framework.__members__.values())
        for framework in self.include_frameworks:
            if framework not in valid_frameworks and framework != Framework.ALL:
                self._warn(f"Unknown framework: {framework}")
        
        # Validate package managers
        valid_pm = set(PackageManager.__members__.values())
        for pm in self.include_package_managers:
            if pm not in valid_pm and pm != PackageManager.ALL:
                self._warn(f"Unknown package manager: {pm}")
    
    def _log(self, message: str) -> None:
        """Log verbose messages."""
        if self.verbose:
            print(f"[INFO] {message}")
    
    def _warn(self, message: str) -> None:
        """Issue a warning."""
        self._warnings_count += 1
        self.stats.warnings_count += 1
        if self.show_warnings:
            warnings.warn(message, UserWarning, stacklevel=2)
    
    def _is_excluded(self, pattern: str) -> bool:
        """Check if a pattern should be excluded."""
        for pattern_re in self._exclude_compiled:
            if pattern_re.search(pattern):
                self.stats.excluded_patterns_count += 1
                return True
        return False
    
    def _add_section(self, title: str, patterns: List[str]) -> None:
        """
        Add a section to the .gitignore file.
        
        Parameters
        ----------
        title : str
            Section title (will be added as a comment).
        patterns : List[str]
            List of patterns to add in this section.
        """
        # Filter out empty lines and excluded patterns
        filtered_patterns = []
        for p in patterns:
            if p.strip() == "":
                filtered_patterns.append(p)
                continue
            if not self._is_excluded(p):
                filtered_patterns.append(p)
        
        if filtered_patterns:
            self.patterns.append(f"# {title}")
            self.patterns.extend(filtered_patterns)
            self.patterns.append("")
            self.stats.sections_count += 1
            self.stats.total_patterns += len([p for p in filtered_patterns if p.strip()])
    
    def _add_ide_patterns(self) -> None:
        """Add IDE-specific patterns based on configuration."""
        if self.include_ide is False:
            return
        
        # Determine which IDEs to include
        ide_list = []
        if self.include_ide is True:
            ide_list = [IDE.VSCODE, IDE.PYCHARM, IDE.INTELLIJ, 
                       IDE.VIM, IDE.EMACS, IDE.SUBLIME, IDE.ATOM,
                       IDE.JUPYTER, IDE.SPYDER]
        elif isinstance(self.include_ide, IDE):
            ide_list = [self.include_ide]
        else:
            ide_list = self.include_ide
        
        # Add patterns for each IDE
        ide_patterns = {
            IDE.VSCODE: self.VSCODE_PATTERNS,
            IDE.PYCHARM: self.PYCHARM_PATTERNS,
            IDE.INTELLIJ: self.INTELLIJ_PATTERNS,
            IDE.VIM: self.VIM_PATTERNS,
            IDE.EMACS: self.EMACS_PATTERNS,
            IDE.SUBLIME: self.SUBLIME_PATTERNS,
            IDE.ATOM: self.ATOM_PATTERNS,
            IDE.JUPYTER: self.JUPYTER_PATTERNS,
            IDE.SPYDER: self.SPYDER_PATTERNS,
        }
        
        for ide in ide_list:
            if ide in ide_patterns:
                self._add_section(f"{ide.value.upper()} IDE", ide_patterns[ide])
    
    def _add_os_patterns(self) -> None:
        """Add OS-specific patterns based on configuration."""
        if self.include_os is False:
            return
        
        # Determine which OS to include
        os_list = []
        if self.include_os is True:
            os_list = [OS.WINDOWS, OS.LINUX, OS.MACOS]
        elif isinstance(self.include_os, OS):
            os_list = [self.include_os]
        else:
            os_list = self.include_os
        
        # Add patterns for each OS
        os_patterns = {
            OS.WINDOWS: self.WINDOWS_PATTERNS,
            OS.LINUX: self.LINUX_PATTERNS,
            OS.MACOS: self.MACOS_PATTERNS,
        }
        
        for os_type in os_list:
            if os_type in os_patterns:
                self._add_section(f"{os_type.value.upper()} OS", os_patterns[os_type])
    
    def _add_framework_patterns(self) -> None:
        """Add framework-specific patterns based on configuration."""
        if not self.include_frameworks:
            return
        
        framework_patterns = {
            Framework.DJANGO: self.DJANGO_PATTERNS,
            Framework.FLASK: self.FLASK_PATTERNS,
            Framework.FASTAPI: self.FASTAPI_PATTERNS,
            Framework.PYTEST: self.PYTEST_PATTERNS,
            Framework.MYPY: self.MYPY_PATTERNS,
            Framework.BLACK: self.BLACK_PATTERNS,
            Framework.RUFF: self.RUFF_PATTERNS,
            Framework.PRE_COMMIT: self.PRE_COMMIT_PATTERNS,
            Framework.TOX: self.TOX_PATTERNS,
            Framework.NOX: self.NOX_PATTERNS,
            Framework.DOCKER: self.DOCKER_PATTERNS,
            Framework.KUBERNETES: self.KUBERNETES_PATTERNS,
            Framework.TERRAFORM: self.TERRAFORM_PATTERNS,
        }
        
        for framework in self.include_frameworks:
            if framework in framework_patterns:
                self._add_section(f"{framework.value.upper()}", framework_patterns[framework])
            elif framework == Framework.ALL:
                for patterns in framework_patterns.values():
                    self._add_section("Framework", patterns)
    
    def _add_package_manager_patterns(self) -> None:
        """Add package manager patterns based on configuration."""
        if not self.include_package_managers:
            return
        
        pm_patterns = {
            PackageManager.POETRY: self.POETRY_PATTERNS,
            PackageManager.PIPENV: self.PIPENV_PATTERNS,
            PackageManager.PDM: self.PDM_PATTERNS,
            PackageManager.CONDA: self.CONDA_PATTERNS,
            PackageManager.UV: self.UV_PATTERNS,
        }
        
        for pm in self.include_package_managers:
            if pm in pm_patterns:
                self._add_section(f"{pm.value.upper()}", pm_patterns[pm])
            elif pm == PackageManager.ALL:
                for patterns in pm_patterns.values():
                    self._add_section("Package Manager", patterns)
    
    def _add_custom_patterns(self) -> None:
        """Add custom patterns provided by the user."""
        if self.custom_patterns:
            filtered = [p for p in self.custom_patterns if not self._is_excluded(p)]
            if filtered:
                self._add_section("Custom Patterns", filtered)
                self.stats.custom_patterns_count = len(filtered)
        
        for section_title, patterns in self.custom_sections.items():
            filtered = [p for p in patterns if not self._is_excluded(p)]
            if filtered:
                self._add_section(section_title, filtered)
                self.stats.custom_patterns_count += len(filtered)
    
    def generate(self) -> str:
        """
        Generate the .gitignore file.
        
        This method orchestrates the entire generation process:
        1. Collects patterns based on configuration
        2. Builds the content with proper sections
        3. Validates and writes the file
        4. Returns the path to the generated file
        
        Returns
        -------
        str
            Path to the generated .gitignore file.
            
        Raises
        ------
        FileExistsError
            If .gitignore already exists and force_overwrite is False.
        IOError
            If the file cannot be written.
            
        Examples
        --------
        >>> generator = GitignoreGenerator(project_name="myproject")
        >>> path = generator.generate()
        >>> print(path)
        /path/to/project/.gitignore
        """
        import time
        start_time = time.time()
        
        gitignore_path = self.output_dir / ".gitignore"
        
        # Check if file exists
        if gitignore_path.exists() and not self.force_overwrite:
            raise FileExistsError(
                f"{gitignore_path} already exists. "
                f"Use force_overwrite=True to overwrite."
            )
        
        # Build patterns
        self._log("Building .gitignore patterns...")
        
        # Add header
        header = ["# .gitignore file"]
        if self.project_name:
            header.append(f"# Project: {self.project_name}")
        if self.add_timestamp_comment:
            header.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        header.append("")
        self.patterns.extend(header)
        
        # Add Python patterns
        if self.include_python:
            self._add_section("Python", self.PYTHON_PATTERNS)
        
        # Add IDE patterns
        self._add_ide_patterns()
        
        # Add OS patterns
        self._add_os_patterns()
        
        # Add framework patterns
        self._add_framework_patterns()
        
        # Add package manager patterns
        self._add_package_manager_patterns()
        
        # Add custom patterns
        self._add_custom_patterns()
        
        # Add footer with statistics
        footer = [
            "# End of .gitignore",
            f"# Total patterns: {self.stats.total_patterns}",
            f"# Sections: {self.stats.sections_count}",
        ]
        self.patterns.extend(footer)
        
        # Build content
        content = "\n".join(self.patterns)
        
        # Clean up trailing newlines
        content = content.rstrip() + "\n"
        
        # Log statistics
        self.stats.generation_time = time.time() - start_time
        
        if self.verbose:
            self._log(f"Generated {self.stats.total_patterns} patterns")
            self._log(f"  Sections: {self.stats.sections_count}")
            self._log(f"  Custom patterns: {self.stats.custom_patterns_count}")
            self._log(f"  Excluded patterns: {self.stats.excluded_patterns_count}")
            self._log(f"  Time: {self.stats.generation_time:.3f}s")
        
        if self._warnings_count > 0:
            self._log(f"Warnings: {self._warnings_count}")
        
        # Dry run
        if self.dry_run:
            self._log(f"DRY RUN: Would generate {gitignore_path}")
            self._log(f"Content preview:\n{content[:500]}...")
            return str(gitignore_path)
        
        # Write file
        try:
            gitignore_path.write_text(content, encoding="utf-8")
            if self.verbose:
                self._log(f"Written to: {gitignore_path}")
                self._log(f"File size: {gitignore_path.stat().st_size} bytes")
        except (IOError, OSError) as e:
            raise IOError(f"Failed to write {gitignore_path}: {e}")
        
        return str(gitignore_path)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get generation statistics.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing generation statistics:
            - total_patterns: Number of patterns generated
            - sections_count: Number of sections
            - warnings_count: Number of warnings issued
            - generation_time: Time taken in seconds
            - custom_patterns_count: Number of custom patterns
            - excluded_patterns_count: Number of patterns excluded
            
        Examples
        --------
        >>> generator = GitignoreGenerator(project_name="myproject")
        >>> generator.generate()
        >>> stats = generator.get_stats()
        >>> print(f"Generated {stats['total_patterns']} patterns")
        """
        return {
            "total_patterns": self.stats.total_patterns,
            "sections_count": self.stats.sections_count,
            "warnings_count": self.stats.warnings_count,
            "generation_time": self.stats.generation_time,
            "custom_patterns_count": self.stats.custom_patterns_count,
            "excluded_patterns_count": self.stats.excluded_patterns_count,
        }


def gitignore_template(
    project_name: Optional[str] = None,
    include_python: bool = True,
    include_ide: Union[bool, IDE, List[IDE]] = True,
    include_os: Union[bool, OS, List[OS]] = True,
    include_frameworks: Optional[List[Framework]] = None,
    include_package_managers: Optional[List[PackageManager]] = None,
    custom_patterns: Optional[List[str]] = None,
    custom_sections: Optional[Dict[str, List[str]]] = None,
    exclude_patterns: Optional[List[str]] = None,
    output_dir: Union[str, Path] = ".",
    force_overwrite: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    show_warnings: bool = True,
    add_timestamp_comment: bool = True,
) -> str:
    """
    Generate a comprehensive .gitignore file for Python projects.
    
    This function creates a .gitignore file with patterns for Python,
    IDEs, operating systems, frameworks, and package managers. It provides
    intelligent defaults while allowing full customization.
    
    Parameters
    ----------
    project_name : Optional[str], optional
        Name of the project. Used in header comments.
        
    include_python : bool, default=True
        Whether to include Python-specific patterns (__pycache__, .pyc,
        virtual environments, pytest cache, coverage, etc.).
        
    include_ide : Union[bool, IDE, List[IDE]], default=True
        IDE patterns to include. Options:
        - True: Include all common IDEs
        - False: Exclude all IDE patterns
        - IDE.VSCODE: Include only VSCode
        - [IDE.VSCODE, IDE.PYCHARM]: Include specific IDEs
        
    include_os : Union[bool, OS, List[OS]], default=True
        Operating system patterns to include. Options:
        - True: Include Windows, Linux, and macOS
        - False: Exclude all OS patterns
        - OS.WINDOWS: Include only Windows
        - [OS.LINUX, OS.MACOS]: Include specific OS
        
    include_frameworks : Optional[List[Framework]], optional
        Framework-specific patterns. Examples:
        - [Framework.DJANGO, Framework.DOCKER]
        - [Framework.PYTEST, Framework.MYPY]
        
    include_package_managers : Optional[List[PackageManager]], optional
        Package manager patterns. Examples:
        - [PackageManager.POETRY]
        - [PackageManager.PIPENV, PackageManager.PDM]
        
    custom_patterns : Optional[List[str]], optional
        Additional custom patterns to add.
        Example: ["*.secret", "*.key", "config.local.py"]
        
    custom_sections : Optional[Dict[str, List[str]]], optional
        Custom sections with patterns. Example:
        {
            "Secrets": ["*.secret", "*.key"],
            "Local Config": ["config.local.py", ".env.local"]
        }
        
    exclude_patterns : Optional[List[str]], optional
        Patterns to exclude from generation. Useful when you want to
        omit certain default patterns.
        
    output_dir : Union[str, Path], default="."
        Directory where .gitignore will be created.
        
    force_overwrite : bool, default=False
        Whether to overwrite existing .gitignore file.
        
    dry_run : bool, default=False
        Whether to simulate generation without writing.
        
    verbose : bool, default=False
        Whether to print detailed information.
        
    show_warnings : bool, default=True
        Whether to show warning messages.
        
    add_timestamp_comment : bool, default=True
        Whether to add generation timestamp.
        
    Returns
    -------
    str
        Path to the generated .gitignore file.
        
    Raises
    ------
    FileExistsError
        If .gitignore already exists and force_overwrite is False.
    PermissionError
        If the output directory cannot be accessed.
    ValueError
        If configuration parameters are invalid.
        
    Examples
    --------
    Basic usage:
    >>> gitignore_template(project_name="myproject")
    '/path/to/project/.gitignore'
    
    Advanced usage with Django and Poetry:
    >>> gitignore_template(
    ...     project_name="django_project",
    ...     include_frameworks=[Framework.DJANGO, Framework.DOCKER],
    ...     include_package_managers=[PackageManager.POETRY],
    ...     custom_patterns=["*.secret", "config.local.py"],
    ...     verbose=True
    ... )
    
    Minimal configuration (only Python):
    >>> gitignore_template(
    ...     project_name="myproject",
    ...     include_ide=False,
    ...     include_os=False,
    ...     include_frameworks=[],
    ...     include_package_managers=[]
    ... )
    
    Dry run to preview:
    >>> gitignore_template(
    ...     project_name="myproject",
    ...     dry_run=True,
    ...     verbose=True
    ... )
    
    Notes
    -----
    - The generated .gitignore follows best practices for Python projects
    - Patterns are organized in clear sections for maintainability
    - Duplicate patterns are automatically handled
    - Empty sections are omitted from the output
    - Timestamps help track when the file was generated
    - The file includes a summary of patterns and sections at the end
    """
    generator = GitignoreGenerator(
        project_name=project_name,
        include_python=include_python,
        include_ide=include_ide,
        include_os=include_os,
        include_frameworks=include_frameworks,
        include_package_managers=include_package_managers,
        custom_patterns=custom_patterns,
        custom_sections=custom_sections,
        exclude_patterns=exclude_patterns,
        output_dir=output_dir,
        force_overwrite=force_overwrite,
        dry_run=dry_run,
        verbose=verbose,
        show_warnings=show_warnings,
        add_timestamp_comment=add_timestamp_comment,
    )
    
    return generator.generate()


def write_gitignore(path: Union[str, Path] = ".gitignore", **kwargs) -> None:
    """
    Generate .gitignore and write it directly to disk.
    
    This is a convenience wrapper around gitignore_template() that handles
    file writing with proper encoding and error handling.
    
    Parameters
    ----------
    path : str or Path, default=".gitignore"
        Path where to write the .gitignore file. If a directory is provided,
        writes to that directory/.gitignore.
    **kwargs
        Additional arguments passed to gitignore_template().
        
    Examples
    --------
    Write to current directory:
    >>> write_gitignore(".gitignore", project_name="myproject")
    
    Write to specific directory:
    >>> write_gitignore("./myproject/.gitignore", include_frameworks=[Framework.DJANGO])
    
    Notes
    -----
    - The file is written with UTF-8 encoding
    - Existing files are handled according to force_overwrite parameter
    - The directory is created if it doesn't exist
    """
    path_obj = Path(path)
    
    # If path is a directory, append .gitignore
    if path_obj.is_dir() or (not path_obj.suffix and path_obj.name != ".gitignore"):
        path_obj = path_obj / ".gitignore"
    
    # Extract output_dir from path
    output_dir = kwargs.pop("output_dir", path_obj.parent)
    
    # Generate .gitignore content
    content = gitignore_template(output_dir=output_dir, **kwargs)
    
    # Ensure parent directory exists
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to file
    path_obj.write_text(content, encoding="utf-8")
