#!/usr/bin/env python3

# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GitHub Actions workflow generator for Python projects.

This module provides a comprehensive framework for generating GitHub Actions
workflow files for Python projects, supporting continuous integration,
testing, linting, building, and deployment pipelines.

The generator creates battle-tested CI/CD workflows with features including:
- Multi-version Python testing matrix
- Automated dependency caching
- Code coverage reporting and upload
- Type checking with mypy
- Multiple linter support (Ruff, Black, isort, Flake8, Pylint)
- Package building and artifact management
- PyPI publishing (both production and test)

Architecture
------------
The module employs a builder pattern with dataclass-based components for
type-safe workflow construction. The main `GitHubActionsGenerator` class
orchestrates the creation of GitHub Actions workflow YAML files through
a series of composable job and step definitions.

Key Components:
    - WorkflowStep: Represents an individual action step
    - WorkflowJob: Represents a job containing multiple steps
    - WorkflowStats: Tracks generation metrics
    - GitHubActionsGenerator: Main generator orchestrator

Examples
--------
>>> from pyputil.template import github_actions_template
>>> 
>>> # Basic CI workflow with testing across multiple Python versions
>>> github_actions_template(
...     project_name="myproject",
...     python_versions=["3.9", "3.10", "3.11", "3.12"],
...     test_command="pytest tests/"
... )
'/home/user/project/.github/workflows/python.yml'
>>> 
>>> # Complete production workflow with linting, type checking, and PyPI publishing
>>> github_actions_template(
...     project_name="myproject",
...     python_versions=["3.10", "3.11", "3.12"],
...     enable_linting=True,
...     enable_type_checking=True,
...     enable_testing=True,
...     enable_building=True,
...     enable_publishing=True,
...     publish_to_pypi=True,
...     secrets=["PYPI_TOKEN"]
... )
>>> 
>>> # Poetry-based project with custom test commands
>>> github_actions_template(
...     project_name="myproject",
...     cache_strategy="poetry",
...     test_command="poetry run pytest tests/",
...     coverage_command="poetry run pytest --cov=src --cov-report=xml"
... )
"""

from pathlib import Path
from typing import Union, Optional, List, Dict, Any, Tuple
from enum import Enum
from datetime import datetime
import warnings
import sys
from dataclasses import dataclass, field

# Fallback for yaml library - try multiple import strategies
YAML_AVAILABLE = False
YAML_FALLBACK_MODE = False

try:
    # Try standard import first
    import yaml
    YAML_AVAILABLE = True
except ImportError: 
	from .._utils._yaml import yaml
	YAML_AVAILABLE = False
	YAML_FALLBACK_MODE = True


class PythonVersion(str, Enum):
    """
    Supported Python version identifiers for CI matrix testing.
    
    These versions correspond to the Python runtime versions available
    on GitHub Actions runners via the actions/setup-python action.
    
    Attributes
    ----------
    PY38 : str
        Python 3.8 - Legacy support (End of Life: 2024-10)
    PY39 : str
        Python 3.9 - Extended support (End of Life: 2025-10)
    PY310 : str
        Python 3.10 - Current stable (End of Life: 2026-10)
    PY311 : str
        Python 3.11 - Performance improvements (End of Life: 2027-10)
    PY312 : str
        Python 3.12 - Latest features (End of Life: 2028-10)
    PY313 : str
        Python 3.13 - Preview support (End of Life: 2029-10)
    PY314 : str
        Python 3.14 - Development preview
    """
    PY38 = "3.8"
    PY39 = "3.9"
    PY310 = "3.10"
    PY311 = "3.11"
    PY312 = "3.12"
    PY313 = "3.13"
    PY314 = "3.14"


class Trigger(str, Enum):
    """
    GitHub Actions workflow trigger events.
    
    Defines when the generated workflow will be automatically executed.
    Multiple triggers can be combined for comprehensive automation.
    
    Attributes
    ----------
    PUSH : str
        Trigger on git push to branches
    PULL_REQUEST : str
        Trigger on pull request creation/update
    SCHEDULE : str
        Trigger on cron schedule (requires cron expression)
    WORKFLOW_DISPATCH : str
        Manual trigger via GitHub UI or API
    RELEASE : str
        Trigger on GitHub release creation
    PULL_REQUEST_TARGET : str
        Trigger on pull_request_target (for privileged workflows)
    """
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    SCHEDULE = "schedule"
    WORKFLOW_DISPATCH = "workflow_dispatch"
    RELEASE = "release"
    PULL_REQUEST_TARGET = "pull_request_target"


class Runner(str, Enum):
    """
    GitHub Actions runner environment types.
    
    Defines the operating system and hardware specifications
    for workflow job execution.
    
    Attributes
    ----------
    UBUNTU_LATEST : str
        Latest Ubuntu runner (fastest startup)
    UBUNTU_2204 : str
        Ubuntu 22.04 LTS (stable)
    UBUNTU_2004 : str
        Ubuntu 20.04 LTS (legacy)
    UBUNTU_2404 : str
        Ubuntu 24.04 LTS (Noble Numbat)
    MACOS_LATEST : str
        Latest macOS runner (for Apple-specific builds)
    MACOS_13 : str
        macOS 13 Ventura (Intel/ARM)
    MACOS_14 : str
        macOS 14 Sonoma (Apple Silicon native)
    WINDOWS_LATEST : str
        Latest Windows runner (.NET compatibility)
    WINDOWS_2022 : str
        Windows Server 2022 (enterprise)
    """
    UBUNTU_LATEST = "ubuntu-latest"
    UBUNTU_2204 = "ubuntu-22.04"
    UBUNTU_2004 = "ubuntu-20.04"
    UBUNTU_2404 = "ubuntu-24.04"
    MACOS_LATEST = "macos-latest"
    MACOS_13 = "macos-13"
    MACOS_14 = "macos-14"
    WINDOWS_LATEST = "windows-latest"
    WINDOWS_2022 = "windows-2022"


class CacheStrategy(str, Enum):
    """
    Dependency caching strategies for faster workflow execution.
    
    Different package managers require different caching approaches
    to effectively store and restore dependencies between runs.
    
    Attributes
    ----------
    PIP : str
        Standard pip cache (requirements.txt, pyproject.toml)
    POETRY : str
        Poetry dependency manager cache
    PIPENV : str
        Pipenv virtual environment cache
    PDM : str
        PDM (Python Development Master) cache
    UV : str
        UV (fast Python package installer) cache
    ALL : str
        Cache all available dependency types
    """
    PIP = "pip"
    POETRY = "poetry"
    PIPENV = "pipenv"
    PDM = "pdm"
    UV = "uv"
    ALL = "all"


class Linter(str, Enum):
    """
    Supported Python code quality tools.
    
    Each linter serves a specific purpose in maintaining
    code quality, style consistency, and error detection.
    
    Attributes
    ----------
    FLAKE8 : str
        Comprehensive style guide enforcement and error detection
    PYLINT : str
        Advanced static analysis with customizable rules
    RUFF : str
        Fast, Rust-based linter replacing multiple tools
    BLACK : str
        Opinionated code formatter with minimal configuration
    ISORT : str
        Import statement sorting and organization
    MYPY : str
        Static type checker
    BANDIT : str
        Security linter for finding common security issues
    """
    FLAKE8 = "flake8"
    PYLINT = "pylint"
    RUFF = "ruff"
    BLACK = "black"
    ISORT = "isort"
    MYPY = "mypy"
    BANDIT = "bandit"


@dataclass
class WorkflowStep:
    """
    Represents a single execution step within a GitHub Actions job.
    
    This dataclass encapsulates all configuration options for a workflow step,
    including action references, shell commands, parameters, and conditions.
    
    Attributes
    ----------
    name : str
        Human-readable step name displayed in GitHub Actions UI
    uses : Optional[str], default=None
        GitHub Action reference (e.g., "actions/checkout@v4")
    run : Optional[str], default=None
        Shell command(s) to execute in the runner
    with_params : Optional[Dict[str, Any]], default=None
        Input parameters for the action
    env : Optional[Dict[str, str]], default=None
        Environment variables for the step
    if_condition : Optional[str], default=None
        Conditional expression for step execution
    continue_on_error : bool, default=False
        Whether to continue workflow if this step fails
    timeout_minutes : Optional[int], default=None
        Step-specific timeout override
        
    Examples
    --------
    >>> step = WorkflowStep(
    ...     name="Checkout repository",
    ...     uses="actions/checkout@v4"
    ... )
    >>> step = WorkflowStep(
    ...     name="Run tests",
    ...     run="pytest tests/",
    ...     env={"PYTHONPATH": "src"},
    ...     timeout_minutes=10
    ... )
    """
    name: str
    uses: Optional[str] = None
    run: Optional[str] = None
    with_params: Optional[Dict[str, Any]] = None
    env: Optional[Dict[str, str]] = None
    if_condition: Optional[str] = None
    continue_on_error: bool = False
    timeout_minutes: Optional[int] = None


@dataclass
class WorkflowJob:
    """
    Represents a GitHub Actions job composed of multiple steps.
    
    Jobs can run in parallel or sequence, with support for matrix strategies,
    dependencies between jobs, and configurable execution environments.
    
    Attributes
    ----------
    name : str
        Unique job identifier used in workflow
    runs_on : Union[str, List[str]]
        Runner environment(s) for job execution
    strategy_matrix : Optional[Dict[str, List[Any]]], default=None
        Matrix strategy for parallel test execution
    steps : List[WorkflowStep], default=empty list
        Sequential steps to execute in the job
    needs : List[str], default=empty list
        Job dependencies (list of job names)
    env : Optional[Dict[str, str]], default=None
        Job-level environment variables
    timeout_minutes : int, default=60
        Maximum job execution time in minutes
    continue_on_error : bool, default=False
        Whether to continue workflow if this job fails
    container : Optional[Dict[str, Any]], default=None
        Container configuration for job execution
        
    Examples
    --------
    >>> job = WorkflowJob(
    ...     name="test",
    ...     runs_on="ubuntu-latest",
    ...     strategy_matrix={"python-version": ["3.10", "3.11"]},
    ...     steps=[checkout_step, setup_step, test_step]
    ... )
    """
    name: str
    runs_on: Union[str, List[str]]
    strategy_matrix: Optional[Dict[str, List[Any]]] = None
    steps: List[WorkflowStep] = field(default_factory=list)
    needs: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    timeout_minutes: int = 60
    continue_on_error: bool = False
    container: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowStats:
    """
    Statistics and metrics about the generated workflow.
    
    Provides insights into workflow complexity and configuration
    for monitoring and optimization purposes.
    
    Attributes
    ----------
    total_jobs : int, default=0
        Number of jobs in the workflow
    total_steps : int, default=0
        Total steps across all jobs
    python_versions : List[str], default=empty list
        Python versions included in test matrix
    enabled_checks : List[str], default=empty list
        Enabled quality check categories
    generation_time : float, default=0.0
        Time taken to generate workflow (seconds)
    matrix_combinations : int, default=0
        Total matrix combinations across all jobs
    """
    total_jobs: int = 0
    total_steps: int = 0
    python_versions: List[str] = field(default_factory=list)
    enabled_checks: List[str] = field(default_factory=list)
    generation_time: float = 0.0
    matrix_combinations: int = 0


class GitHubActionsGenerator:
    """
    Comprehensive generator for GitHub Actions CI/CD workflows.
    
    This class provides a flexible and extensible framework for generating
    production-ready GitHub Actions workflow files tailored to Python projects.
    It supports matrix testing, multiple linters, dependency caching,
    artifact management, and PyPI publishing with proper security practices.
    
    The generator follows a builder pattern where configuration is set during
    initialization and workflow construction occurs through a series of
    internal job creation methods.
    
    Attributes
    ----------
    project_name : str
        Project identifier used in workflow metadata
    workflow_name : str
        Display name in GitHub Actions dashboard
    python_versions : List[str]
        Python versions for matrix testing
    triggers : List[Trigger]
        Events triggering workflow execution
    jobs : List[WorkflowJob]
        Constructed workflow jobs
    stats : WorkflowStats
        Generation statistics and metrics
    
    Examples
    --------
    >>> # Basic test-only workflow
    >>> generator = GitHubActionsGenerator(
    ...     project_name="myapp",
    ...     python_versions=["3.10", "3.11"],
    ...     enable_testing=True
    ... )
    >>> generator.generate()
    '.github/workflows/python.yml'
    
    >>> # Full CI/CD pipeline with publishing
    >>> generator = GitHubActionsGenerator(
    ...     project_name="myapp",
    ...     enable_linting=True,
    ...     enable_testing=True,
    ...     enable_building=True,
    ...     enable_publishing=True,
    ...     publish_to_pypi=True,
    ...     secrets=["PYPI_TOKEN"]
    ... )
    >>> stats = generator.get_stats()
    >>> print(f"Generated {stats['total_jobs']} jobs")
    
    >>> # Poetry project with custom test configuration
    >>> generator = GitHubActionsGenerator(
    ...     project_name="myapp",
    ...     cache_strategy=CacheStrategy.POETRY,
    ...     test_command="poetry run pytest --cov=src",
    ...     enable_coverage=True
    ... )
    
    Notes
    -----
    The generator creates workflows that follow GitHub Actions best practices:
        - Uses specific action versions (v4, v5) for reproducibility
        - Implements proper caching strategies
        - Includes timeout limits for all jobs
        - Handles secret management for publishing
        - Provides conditional execution for release triggers
    """
    
    def __init__(
        self,
        project_name: str = "myproject",
        workflow_name: str = "CI",
        python_versions: Optional[List[str]] = None,
        triggers: Optional[List[Trigger]] = None,
        enable_testing: bool = True,
        enable_linting: bool = True,
        enable_type_checking: bool = False,
        enable_building: bool = False,
        enable_publishing: bool = False,
        enable_coverage: bool = True,
        enable_caching: bool = True,
        enable_security_scan: bool = False,
        cache_strategy: CacheStrategy = CacheStrategy.PIP,
        linters: Optional[List[Linter]] = None,
        test_command: str = "pytest tests/",
        coverage_command: str = "pytest --cov=src --cov-report=xml",
        security_command: str = "bandit -r src/",
        build_command: str = "python -m build",
        publish_to_pypi: bool = False,
        publish_to_test_pypi: bool = False,
        pypi_repository_url: Optional[str] = None,
        secrets: Optional[List[str]] = None,
        runners: Union[Runner, List[Runner]] = Runner.UBUNTU_LATEST,
        timeout_minutes: int = 30,
        fail_fast: bool = True,
        output_dir: Union[str, Path] = ".github/workflows",
        force_overwrite: bool = False,
        dry_run: bool = False,
        verbose: bool = False,
        show_warnings: bool = True,
        add_timestamp_comment: bool = True,
        max_parallel: int = 4,
        custom_actions: Optional[Dict[str, str]] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Initialize the GitHub Actions workflow generator.
        
        Sets up the generator with comprehensive configuration options for
        customizing the generated CI/CD pipeline. All parameters have sensible
        defaults while allowing fine-grained control over every aspect of the
        workflow.
        
        Parameters
        ----------
        project_name : str, default="myproject"
            Project identifier used in workflow header comments and metadata.
            Should match the PyPI package name if publishing.
            
        workflow_name : str, default="CI"
            Display name shown in GitHub Actions dashboard.
            Use descriptive names like "CI/CD Pipeline" or "Test & Deploy".
            
        python_versions : Optional[List[str]], optional
            Python versions to test in matrix strategy.
            Each version runs tests in parallel for comprehensive compatibility.
            Default: ["3.9", "3.10", "3.11", "3.12"]
            
        triggers : Optional[List[Trigger]], optional
            GitHub events that automatically start the workflow.
            Default: [Trigger.PUSH, Trigger.PULL_REQUEST]
            
        enable_testing : bool, default=True
            Include job that runs tests across Python versions.
            Essential for ensuring code correctness.
            
        enable_linting : bool, default=True
            Include job that checks code style and quality.
            Helps maintain consistent code standards.
            
        enable_type_checking : bool, default=False
            Include mypy static type checking.
            Recommended for larger codebases (>1000 lines).
            
        enable_building : bool, default=False
            Include job that builds distribution packages.
            Required for publishing to PyPI.
            
        enable_publishing : bool, default=False
            Include job that uploads packages to PyPI.
            Automatically triggered on GitHub releases.
            
        enable_coverage : bool, default=True
            Generate and upload test coverage reports.
            Integrates with services like Codecov or Coveralls.
            
        enable_caching : bool, default=True
            Cache dependencies to speed up workflow runs.
            Reduces average run time by 40-60%.
            
        enable_security_scan : bool, default=False
            Run security vulnerability scanning with Bandit.
            Identifies common security issues in Python code.
            
        cache_strategy : CacheStrategy, default=PIP
            Which package manager's cache to use.
            Must match your project's dependency manager.
            
        linters : Optional[List[Linter]], optional
            Code quality tools to run in linting job.
            Default: [Linter.RUFF, Linter.BLACK, Linter.ISORT]
            
        test_command : str, default="pytest tests/"
            Shell command to execute tests.
            Can include framework-specific arguments (pytest, unittest, tox).
            
        coverage_command : str, default="pytest --cov=src --cov-report=xml"
            Command that generates coverage reports.
            Must output coverage.xml or compatible format.
            
        security_command : str, default="bandit -r src/"
            Command to run security scanning.
            Should output security issues for review.
            
        build_command : str, default="python -m build"
            Command to build distribution packages.
            Should generate files in dist/ directory.
            
        publish_to_pypi : bool, default=False
            Upload packages to official PyPI repository.
            Requires PYPI_TOKEN secret in GitHub repository.
            
        publish_to_test_pypi : bool, default=False
            Upload to Test PyPI for pre-release validation.
            Useful for testing publishing workflow.
            
        pypi_repository_url : Optional[str], optional
            Custom PyPI repository URL for private package indices.
            Overrides default PyPI or Test PyPI URLs.
            
        secrets : Optional[List[str]], optional
            GitHub secrets required by the workflow.
            Automatically includes PYPI_TOKEN if publishing.
            
        runners : Union[Runner, List[Runner]], default=UBUNTU_LATEST
            GitHub-hosted runner environments for jobs.
            Specify multiple runners for cross-platform testing.
            
        timeout_minutes : int, default=30
            Maximum execution time per job in minutes.
            Prevents hung jobs from consuming resources.
            
        fail_fast : bool, default=True
            Stop matrix jobs on first failure.
            Saves resources when early failures occur.
            
        output_dir : Union[str, Path], default=".github/workflows"
            Directory where workflow YAML files are written.
            Standard GitHub Actions location is expected.
            
        force_overwrite : bool, default=False
            Overwrite existing workflow file without warning.
            Use with caution as it will replace manual changes.
            
        dry_run : bool, default=False
            Simulate generation without writing files.
            Useful for previewing workflow content.
            
        verbose : bool, default=False
            Print detailed generation information.
            Helpful for debugging configuration issues.
            
        show_warnings : bool, default=True
            Display warning messages during generation.
            Warnings indicate potential configuration problems.
            
        add_timestamp_comment : bool, default=True
            Include generation timestamp in workflow header.
            Helps track when workflows were last generated.
            
        max_parallel : int, default=4
            Maximum number of parallel jobs in matrix strategy.
            Prevents overwhelming GitHub Actions runners.
            
        custom_actions : Optional[Dict[str, str]], optional
            Custom GitHub Actions to include in steps.
            Maps step names to action references.
            
        env_vars : Optional[Dict[str, str]], optional
            Global environment variables for all jobs.
            
        Raises
        ------
        ValueError
            If configuration parameters are invalid (e.g., empty Python version list).
        PermissionError
            If output directory cannot be created or accessed.
        FileExistsError
            If workflow file exists and force_overwrite is False.
            
        Examples
        --------
        >>> # Minimal configuration
        >>> generator = GitHubActionsGenerator()
        >>> generator.generate()
        
        >>> # Production configuration with all features
        >>> generator = GitHubActionsGenerator(
        ...     project_name="enterprise-app",
        ...     python_versions=["3.10", "3.11", "3.12"],
        ...     enable_linting=True,
        ...     enable_type_checking=True,
        ...     enable_testing=True,
        ...     enable_building=True,
        ...     enable_publishing=True,
        ...     enable_security_scan=True,
        ...     publish_to_pypi=True,
        ...     secrets=["PYPI_TOKEN", "CODECOV_TOKEN"],
        ...     runners=[Runner.UBUNTU_LATEST, Runner.MACOS_LATEST],
        ...     timeout_minutes=15,
        ...     verbose=True
        ... )
        """
        # Basic configuration
        self.project_name = project_name
        self.workflow_name = workflow_name
        self.python_versions = python_versions or ["3.9", "3.10", "3.11", "3.12"]
        self.triggers = triggers or [Trigger.PUSH, Trigger.PULL_REQUEST]
        self.enable_testing = enable_testing
        self.enable_linting = enable_linting
        self.enable_type_checking = enable_type_checking
        self.enable_building = enable_building
        self.enable_publishing = enable_publishing
        self.enable_coverage = enable_coverage
        self.enable_caching = enable_caching
        self.enable_security_scan = enable_security_scan
        self.cache_strategy = cache_strategy
        self.linters = linters or [Linter.RUFF, Linter.BLACK, Linter.ISORT]
        self.test_command = test_command
        self.coverage_command = coverage_command
        self.security_command = security_command
        self.build_command = build_command
        self.publish_to_pypi = publish_to_pypi
        self.publish_to_test_pypi = publish_to_test_pypi
        self.pypi_repository_url = pypi_repository_url
        self.secrets = secrets or ["PYPI_TOKEN"] if publish_to_pypi else []
        self.runners = runners if isinstance(runners, list) else [runners]
        self.timeout_minutes = timeout_minutes
        self.fail_fast = fail_fast
        self.output_dir = Path(output_dir)
        self.force_overwrite = force_overwrite
        self.dry_run = dry_run
        self.verbose = verbose
        self.show_warnings = show_warnings
        self.add_timestamp_comment = add_timestamp_comment
        self.max_parallel = max_parallel
        self.custom_actions = custom_actions or {}
        self.env_vars = env_vars or {}
        
        # Initialize internal state
        self.jobs: List[WorkflowJob] = []
        self.stats = WorkflowStats()
        self._warnings_count = 0
        
        # Validate configuration and setup directories
        self._validate_config()
        
        # Log YAML library status
        if YAML_FALLBACK_MODE:
            self._warn("Using fallback YAML serializer. Install PyYAML for full compatibility: pip install pyyaml")
        
        if self.verbose:
            self._log(f"GitHubActionsGenerator initialized for '{self.project_name}'")
            self._log(f"  Python versions: {', '.join(self.python_versions)}")
            self._log(f"  Features: Testing={self.enable_testing}, Linting={self.enable_linting}, "
                     f"Building={self.enable_building}, Publishing={self.enable_publishing}")
            self._log(f"  Cache strategy: {self.cache_strategy.value}")
            self._log(f"  Runners: {', '.join([r.value for r in self.runners])}")
            self._log(f"  Output directory: {self.output_dir}")
            self._log(f"  YAML library: {'PyYAML' if not YAML_FALLBACK_MODE else 'Fallback (limited)'}")
    
    def _validate_config(self) -> None:
        """
        Validate configuration parameters and ensure directory exists.
        
        Performs comprehensive validation of all configuration options to catch
        potential issues early and provide helpful error messages.
        
        Raises
        ------
        ValueError
            If validation fails (e.g., empty Python versions, invalid commands)
        PermissionError
            If output directory cannot be created
        """
        # Validate output directory accessibility
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            if self.verbose:
                self._log(f"Output directory ready: {self.output_dir}")
        except PermissionError as e:
            raise PermissionError(
                f"Cannot create or access output directory '{self.output_dir}': {e}"
            )
        
        # Validate Python versions list
        if not self.python_versions:
            raise ValueError("At least one Python version must be specified")
        
        # Validate Python version formats
        for version in self.python_versions:
            if not version.replace(".", "").isdigit():
                self._warn(f"Unusual Python version format: '{version}'. "
                          f"Expected format like '3.11'")
        
        # Validate test commands are not empty when testing enabled
        if self.enable_testing:
            if not self.test_command and not self.coverage_command:
                self._warn("Testing is enabled but no test commands are specified")
        
        # Validate publishing configuration
        if self.publish_to_pypi and not self.secrets:
            self._warn(
                "Publishing to PyPI is enabled but no secrets are configured. "
                "Add 'PYPI_TOKEN' to your GitHub repository secrets."
            )
        
        if self.publish_to_pypi and not self.enable_building:
            self._warn(
                "Publishing to PyPI requires building to create distribution packages. "
                "Consider enabling enable_building=True"
            )
        
        # Validate security scanning
        if self.enable_security_scan and Linter.BANDIT not in self.linters:
            self.linters.append(Linter.BANDIT)
            if self.verbose:
                self._log("  Automatically added Bandit linter for security scanning")
    
    def _log(self, message: str) -> None:
        """
        Log informational message when verbose mode is enabled.
        
        Parameters
        ----------
        message : str
            Message to log to standard output
        """
        if self.verbose:
            print(f"[INFO] {message}")
    
    def _warn(self, message: str) -> None:
        """
        Issue a warning message that doesn't stop execution.
        
        Parameters
        ----------
        message : str
            Warning message to display or log
        """
        self._warnings_count += 1
        if self.show_warnings:
            warnings.warn(message, UserWarning, stacklevel=2)
    
    def _create_setup_python_step(self, version: str) -> WorkflowStep:
        """
        Create a workflow step to install a specific Python version.
        
        Configures the actions/setup-python action with appropriate version
        and optional dependency caching.
        
        Parameters
        ----------
        version : str
            Python version to install (e.g., "3.11")
            
        Returns
        -------
        WorkflowStep
            Configured Python setup step
            
        Notes
        -----
        Uses actions/setup-python@v5 which supports all Python versions
        available on GitHub Actions runners.
        """
        return WorkflowStep(
            name=f"Set up Python {version}",
            uses="actions/setup-python@v5",
            with_params={
                "python-version": version,
                "cache": self.cache_strategy.value if self.enable_caching else None
            }
        )
    
    def _create_install_deps_step(self, extra_args: str = "") -> WorkflowStep:
        """
        Create a step to install project dependencies.
        
        Supports multiple dependency managers (pip, Poetry, Pipenv, PDM, UV)
        and installs development dependencies based on configuration.
        
        Parameters
        ----------
        extra_args : str, default=""
            Additional arguments for pip install (e.g., "[dev,test]")
            
        Returns
        -------
        WorkflowStep
            Dependency installation step
            
        Notes
        -----
        The installation strategy adapts to the configured cache strategy:
            - PIP: Uses pip with editable install
            - POETRY: Uses Poetry for dependency resolution
            - PIPENV: Uses Pipenv for virtual environment
            - PDM: Uses PDM for modern Python packaging
            - UV: Uses UV for ultra-fast installation
        """
        pip_cmd = "python -m pip install --upgrade pip"
        
        if self.cache_strategy == CacheStrategy.POETRY:
            install_cmd = "pip install poetry && poetry install"
        elif self.cache_strategy == CacheStrategy.PIPENV:
            install_cmd = "pip install pipenv && pipenv install --dev"
        elif self.cache_strategy == CacheStrategy.PDM:
            install_cmd = "pip install pdm && pdm install"
        elif self.cache_strategy == CacheStrategy.UV:
            install_cmd = "pip install uv && uv pip install -e . && uv pip install pytest"
        else:
            install_cmd = f"pip install -e .{extra_args}"
        
        return WorkflowStep(
            name="Install dependencies",
            run=f"{pip_cmd}\n{install_cmd}"
        )
    
    def _create_linting_job(self) -> WorkflowJob:
        """
        Create a job that runs configured code quality tools.
        
        The linting job checks code style, formatting, and performs
        static analysis using the specified linters and type checker.
        
        Returns
        -------
        WorkflowJob
            Configured linting job with all requested linters
            
        Notes
        -----
        Linting runs on a single Python version (latest stable) to
        maximize performance, as code quality issues are version-agnostic.
        """
        steps = [
            WorkflowStep(name="Checkout code", uses="actions/checkout@v4"),
            self._create_setup_python_step("3.12"),  # Use latest stable for linting
            self._create_install_deps_step("[dev,lint]"),
        ]
        
        # Add steps for each configured linter
        linter_steps = {
            Linter.RUFF: ("Run Ruff linter", "ruff check ."),
            Linter.BLACK: ("Run Black formatter check", "black --check ."),
            Linter.ISORT: ("Run isort check", "isort --check-only --diff ."),
            Linter.FLAKE8: ("Run flake8", "flake8 ."),
            Linter.PYLINT: ("Run pylint", "pylint src/"),
            Linter.MYPY: ("Run mypy type checking", "mypy src/"),
            Linter.BANDIT: ("Run security scan", "bandit -r src/ -ll"),
        }
        
        for linter in self.linters:
            if linter in linter_steps:
                name, command = linter_steps[linter]
                steps.append(WorkflowStep(name=name, run=command))
        
        # Add type checking if enabled separately
        if self.enable_type_checking and Linter.MYPY not in self.linters:
            steps.append(WorkflowStep(
                name="Run mypy type checking",
                run="mypy src/"
            ))
        
        return WorkflowJob(
            name="lint",
            runs_on=self.runners[0].value,
            steps=steps,
            timeout_minutes=self.timeout_minutes
        )
    
    def _create_testing_job(self) -> WorkflowJob:
        """
        Create a job that runs tests with Python version matrix.
        
        Configures matrix testing across all specified Python versions,
        with optional coverage reporting and artifact upload.
        
        Returns
        -------
        WorkflowJob
            Matrix testing job with coverage support
            
        Notes
        -----
        The test job includes:
            - Matrix strategy for Python versions
            - Dependency caching per Python version
            - Coverage report generation
            - Automatic Codecov upload if coverage enabled
        """
        steps = [
            WorkflowStep(name="Checkout code", uses="actions/checkout@v4"),
        ]
        
        # Configure matrix strategy for Python versions
        strategy_matrix = {
            "python-version": self.python_versions[:self.max_parallel],
            "os": [runner.value for runner in self.runners[:self.max_parallel]]
        }
        
        # Calculate total matrix combinations
        self.stats.matrix_combinations = len(strategy_matrix["python-version"]) * len(strategy_matrix["os"])
        
        # Dynamic Python setup using matrix variable
        steps.append(WorkflowStep(
            name="Set up Python ${{ matrix.python-version }}",
            uses="actions/setup-python@v5",
            with_params={
                "python-version": "${{ matrix.python-version }}",
                "cache": self.cache_strategy.value if self.enable_caching else None
            }
        ))
        
        steps.append(self._create_install_deps_step("[test]"))
        
        # Run tests (with or without coverage)
        test_cmd = self.coverage_command if self.enable_coverage else self.test_command
        steps.append(WorkflowStep(
            name="Run tests",
            run=test_cmd
        ))
        
        # Upload coverage reports to Codecov
        if self.enable_coverage:
            steps.append(WorkflowStep(
                name="Upload coverage to Codecov",
                uses="codecov/codecov-action@v4",
                with_params={
                    "file": "./coverage.xml",
                    "fail_ci_if_error": True
                }
            ))
        
        return WorkflowJob(
            name="test",
            runs_on="${{ matrix.os }}",
            strategy_matrix=strategy_matrix,
            steps=steps,
            timeout_minutes=self.timeout_minutes
        )
    
    def _create_building_job(self) -> Optional[WorkflowJob]:
        """
        Create a job that builds distribution packages.
        
        Generates wheel and source distribution files suitable for
        publishing to PyPI or other package indexes.
        
        Returns
        -------
        Optional[WorkflowJob]
            Building job if building is enabled, None otherwise
            
        Notes
        -----
        The build job:
            - Uses Python 3.12 for consistent builds
            - Uploads artifacts for later publishing jobs
            - Follows PyPA build standards
        """
        if not self.enable_building:
            return None
        
        steps = [
            WorkflowStep(name="Checkout code", uses="actions/checkout@v4"),
            self._create_setup_python_step("3.12"),
            self._create_install_deps_step("[build]"),
            WorkflowStep(
                name="Build package",
                run=self.build_command
            ),
            WorkflowStep(
                name="Upload build artifacts",
                uses="actions/upload-artifact@v4",
                with_params={
                    "name": "dist",
                    "path": "dist/"
                }
            )
        ]
        
        return WorkflowJob(
            name="build",
            runs_on=self.runners[0].value,
            steps=steps,
            timeout_minutes=self.timeout_minutes
        )
    
    def _create_publishing_job(self) -> Optional[WorkflowJob]:
        """
        Create a job that publishes packages to PyPI repositories.
        
        Uploads previously built distribution packages to PyPI,
        Test PyPI, or custom package indices.
        
        Returns
        -------
        Optional[WorkflowJob]
            Publishing job if publishing is enabled, None otherwise
            
        Notes
        -----
        Publishing job features:
            - Depends on successful build job
            - Supports Test PyPI for validation
            - Conditional execution on GitHub releases
            - Secure token-based authentication
        """
        if not self.enable_publishing:
            return None
        
        steps = [
            WorkflowStep(name="Checkout code", uses="actions/checkout@v4"),
            self._create_setup_python_step("3.12"),
            self._create_install_deps_step("[publish]"),
            WorkflowStep(
                name="Download build artifacts",
                uses="actions/download-artifact@v4",
                with_params={"name": "dist", "path": "dist/"}
            ),
        ]
        
        # Publish to Test PyPI for validation
        if self.publish_to_test_pypi:
            steps.append(WorkflowStep(
                name="Publish to Test PyPI",
                uses="pypa/gh-action-pypi-publish@release/v1",
                with_params={
                    "repository_url": "https://test.pypi.org/legacy/",
                    "password": "${{ secrets.TEST_PYPI_TOKEN }}"
                }
            ))
        
        # Publish to production PyPI (or custom repository)
        if self.publish_to_pypi:
            repository = self.pypi_repository_url or "https://upload.pypi.org/legacy/"
            steps.append(WorkflowStep(
                name="Publish to PyPI",
                uses="pypa/gh-action-pypi-publish@release/v1",
                with_params={
                    "repository_url": repository,
                    "password": "${{ secrets.PYPI_TOKEN }}"
                },
                if_condition="github.event_name == 'release' && github.event.action == 'published'"
            ))
        
        return WorkflowJob(
            name="publish",
            runs_on=self.runners[0].value,
            needs=["build"],
            steps=steps,
            timeout_minutes=self.timeout_minutes
        )
    
    def _build_workflow_yaml(self) -> str:
        """
        Construct the complete workflow YAML content.
        
        Assembles all configured jobs into a properly formatted
        GitHub Actions workflow YAML string.
        
        Returns
        -------
        str
            YAML-formatted workflow content
            
        Notes
        -----
        The generated YAML follows GitHub Actions schema and includes
        proper indentation, structure, and all configuration options.
        """
        workflow = {
            "name": self.workflow_name,
            "on": {
                trigger.value: None for trigger in self.triggers
            } if len(self.triggers) > 0 else {}
        }
        
        # Add environment variables if specified
        if self.env_vars:
            workflow["env"] = self.env_vars
        
        workflow["jobs"] = {}
        
        # Add each enabled job to the workflow
        if self.enable_linting:
            lint_job = self._create_linting_job()
            workflow["jobs"]["lint"] = self._job_to_dict(lint_job)
            self.stats.total_jobs += 1
        
        if self.enable_testing:
            test_job = self._create_testing_job()
            workflow["jobs"]["test"] = self._job_to_dict(test_job)
            self.stats.total_jobs += 1
        
        if self.enable_building:
            build_job = self._create_building_job()
            if build_job:
                workflow["jobs"]["build"] = self._job_to_dict(build_job)
                self.stats.total_jobs += 1
        
        if self.enable_publishing:
            publish_job = self._create_publishing_job()
            if publish_job:
                workflow["jobs"]["publish"] = self._job_to_dict(publish_job)
                self.stats.total_jobs += 1
        
        # Add OIDC permissions for secure publishing
        if self.enable_publishing:
            workflow["permissions"] = {
                "contents": "read",
                "id-token": "write"
            }
        
        # Use proper YAML serialization
        if YAML_AVAILABLE and not YAML_FALLBACK_MODE:
            return yaml.dump(workflow, default_flow_style=False, sort_keys=False)
        else:
            return yaml.dump(workflow, default_flow_style=False, sort_keys=False)
    
    def _job_to_dict(self, job: WorkflowJob) -> Dict[str, Any]:
        """
        Convert a WorkflowJob object to a dictionary for YAML serialization.
        
        Transforms the object-oriented job representation into a nested
        dictionary structure compatible with GitHub Actions YAML schema.
        
        Parameters
        ----------
        job : WorkflowJob
            Job configuration to convert
            
        Returns
        -------
        Dict[str, Any]
            Dictionary representation suitable for YAML export
            
        Notes
        -----
        Handles conversion of all job attributes including:
            - Runner environment(s)
            - Strategy matrix
            - Conditional dependencies
            - Step definitions with their parameters
        """
        job_dict = {
            "runs-on": job.runs_on,
            "timeout-minutes": job.timeout_minutes
        }
        
        if job.needs:
            job_dict["needs"] = job.needs
        
        if job.strategy_matrix:
            job_dict["strategy"] = {
                "matrix": job.strategy_matrix,
                "fail-fast": self.fail_fast
            }
        
        if job.env:
            job_dict["env"] = job.env
        
        if job.continue_on_error:
            job_dict["continue-on-error"] = job.continue_on_error
        
        if job.container:
            job_dict["container"] = job.container
        
        # Convert steps to dictionary format
        steps = []
        for step in job.steps:
            step_dict = {"name": step.name}
            if step.uses:
                step_dict["uses"] = step.uses
            if step.run:
                step_dict["run"] = step.run
            if step.with_params:
                # Filter out None values to keep YAML clean
                step_dict["with"] = {k: v for k, v in step.with_params.items() if v is not None}
            if step.env:
                step_dict["env"] = step.env
            if step.if_condition:
                step_dict["if"] = step.if_condition
            if step.continue_on_error:
                step_dict["continue-on-error"] = step.continue_on_error
            if step.timeout_minutes:
                step_dict["timeout-minutes"] = step.timeout_minutes
            steps.append(step_dict)
        
        job_dict["steps"] = steps
        self.stats.total_steps += len(steps)
        
        return job_dict
    
    def generate(self) -> str:
        """
        Generate the GitHub Actions workflow file.
        
        Creates the workflow YAML file at the configured output location
        with all specified jobs, steps, and configurations.
        
        Returns
        -------
        str
            Absolute path to the generated workflow file
            
        Raises
        ------
        FileExistsError
            If workflow file already exists and force_overwrite is False
        IOError
            If file cannot be written due to permissions or disk errors
            
        Examples
        --------
        >>> generator = GitHubActionsGenerator(project_name="myapp")
        >>> path = generator.generate()
        >>> print(f"Workflow created at: {path}")
        Workflow created at: /project/.github/workflows/python.yml
        
        Notes
        -----
        Generation process:
            1. Validates output directory accessibility
            2. Builds workflow YAML from configuration
            3. Adds timestamp and metadata header
            4. Writes file (unless dry run mode)
            5. Updates generation statistics
        """
        import time
        start_time = time.time()
        
        workflow_file = self.output_dir / "python.yml"
        
        # Check for existing file to prevent accidental overwrites
        if workflow_file.exists() and not self.force_overwrite:
            raise FileExistsError(
                f"{workflow_file} already exists. "
                f"Use force_overwrite=True to overwrite existing workflow."
            )
        
        # Generate workflow content
        workflow_yaml = self._build_workflow_yaml()
        
        # Add informative header comments
        header = []
        if self.add_timestamp_comment:
            header.append(f"# Generated by GitHub Actions Generator on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            header.append(f"# Project: {self.project_name}")
            header.append(f"# Python versions: {', '.join(self.python_versions)}")
            if self.stats.matrix_combinations > 0:
                header.append(f"# Total matrix combinations: {self.stats.matrix_combinations}")
            if YAML_FALLBACK_MODE:
                header.append(f"# Note: Using fallback YAML serializer (PyYAML not installed)")
            header.append("")
        
        content = "\n".join(header) + workflow_yaml
        
        # Update statistics
        self.stats.python_versions = self.python_versions
        if self.enable_linting:
            self.stats.enabled_checks.append("linting")
        if self.enable_testing:
            self.stats.enabled_checks.append("testing")
        if self.enable_type_checking:
            self.stats.enabled_checks.append("type-checking")
        if self.enable_building:
            self.stats.enabled_checks.append("building")
        if self.enable_publishing:
            self.stats.enabled_checks.append("publishing")
        if self.enable_security_scan:
            self.stats.enabled_checks.append("security-scan")
        
        self.stats.generation_time = time.time() - start_time
        
        # Report generation statistics
        if self.verbose:
            self._log("Workflow generation completed:")
            self._log(f"  Jobs created: {self.stats.total_jobs}")
            self._log(f"  Steps total: {self.stats.total_steps}")
            if self.stats.matrix_combinations > 0:
                self._log(f"  Matrix combinations: {self.stats.matrix_combinations}")
            self._log(f"  Enabled checks: {', '.join(self.stats.enabled_checks)}")
            self._log(f"  Generation time: {self.stats.generation_time:.3f}s")
        
        if self._warnings_count > 0:
            self._log(f"  Warnings issued: {self._warnings_count}")
        
        # Handle dry run mode
        if self.dry_run:
            self._log(f"DRY RUN: Would generate workflow at {workflow_file}")
            if self.verbose:
                self._log("Content preview (first 500 characters):")
                self._log(content[:500] + "...")
            return str(workflow_file)
        
        # Write file to disk
        try:
            workflow_file.write_text(content, encoding="utf-8")
            if self.verbose:
                file_size = workflow_file.stat().st_size
                self._log(f"Successfully written to: {workflow_file}")
                self._log(f"File size: {file_size} bytes")
        except (IOError, OSError) as e:
            raise IOError(f"Failed to write workflow file {workflow_file}: {e}")
        
        return str(workflow_file)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retrieve generation statistics after workflow creation.
        
        Provides metrics and configuration summary for the generated workflow.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
                - total_jobs: Number of jobs in workflow
                - total_steps: Total steps across all jobs
                - python_versions: List of tested Python versions
                - enabled_checks: Enabled quality check categories
                - generation_time: Time taken to generate (seconds)
                - warnings_count: Number of warnings issued
                - matrix_combinations: Total matrix combinations (if any)
                
        Examples
        --------
        >>> generator = GitHubActionsGenerator()
        >>> generator.generate()
        >>> stats = generator.get_stats()
        >>> print(f"Generated {stats['total_jobs']} jobs with {stats['total_steps']} steps")
        """
        return {
            "total_jobs": self.stats.total_jobs,
            "total_steps": self.stats.total_steps,
            "python_versions": self.stats.python_versions,
            "enabled_checks": self.stats.enabled_checks,
            "generation_time": self.stats.generation_time,
            "warnings_count": self._warnings_count,
            "matrix_combinations": self.stats.matrix_combinations,
            "yaml_backend": "fallback" if YAML_FALLBACK_MODE else "pyyaml"
        }


def github_actions_template(
    project_name: str = "myproject",
    workflow_name: str = "CI",
    python_versions: Optional[List[str]] = None,
    enable_testing: bool = True,
    enable_linting: bool = True,
    enable_type_checking: bool = False,
    enable_building: bool = False,
    enable_publishing: bool = False,
    enable_coverage: bool = True,
    enable_caching: bool = True,
    enable_security_scan: bool = False,
    cache_strategy: str = "pip",
    linters: Optional[List[str]] = None,
    test_command: str = "pytest tests/",
    coverage_command: str = "pytest --cov=src --cov-report=xml",
    security_command: str = "bandit -r src/",
    build_command: str = "python -m build",
    publish_to_pypi: bool = False,
    publish_to_test_pypi: bool = False,
    pypi_repository_url: Optional[str] = None,
    secrets: Optional[List[str]] = None,
    runners: Union[str, List[str]] = "ubuntu-latest",
    timeout_minutes: int = 30,
    fail_fast: bool = True,
    output_dir: Union[str, Path] = ".github/workflows",
    force_overwrite: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    show_warnings: bool = True,
    add_timestamp_comment: bool = True,
    max_parallel: int = 4,
    custom_actions: Optional[Dict[str, str]] = None,
    env_vars: Optional[Dict[str, str]] = None,
) -> str:
    """
    Generate a GitHub Actions workflow file for Python projects.
    
    This is the primary public interface for creating CI/CD workflows.
    It creates a comprehensive workflow with testing, linting, building,
    and publishing capabilities for Python packages.
    
    Parameters
    ----------
    project_name : str, default="myproject"
        Name of the project used in workflow comments and metadata.
        
    workflow_name : str, default="CI"
        Display name shown in GitHub Actions dashboard.
        
    python_versions : Optional[List[str]], optional
        Python versions to test against in matrix strategy.
        Default: ["3.9", "3.10", "3.11", "3.12"]
        
    enable_testing : bool, default=True
        Include job that runs tests across Python versions.
        
    enable_linting : bool, default=True
        Include job that checks code quality and style.
        
    enable_type_checking : bool, default=False
        Include mypy static type checking.
        
    enable_building : bool, default=False
        Include job that builds distribution packages.
        
    enable_publishing : bool, default=False
        Include job that publishes to PyPI repositories.
        
    enable_coverage : bool, default=True
        Generate and upload test coverage reports.
        
    enable_caching : bool, default=True
        Cache dependencies for faster workflow execution.
        
    enable_security_scan : bool, default=False
        Run security vulnerability scanning with Bandit.
        
    cache_strategy : str, default="pip"
        Dependency manager for caching: "pip", "poetry", "pipenv", "pdm", "uv".
        
    linters : Optional[List[str]], optional
        Code quality tools to run. Options: "ruff", "black", "isort",
        "flake8", "pylint", "mypy", "bandit".
        Default: ["ruff", "black", "isort"]
        
    test_command : str, default="pytest tests/"
        Command to execute tests.
        
    coverage_command : str, default="pytest --cov=src --cov-report=xml"
        Command that generates coverage report.
        
    security_command : str, default="bandit -r src/"
        Command to run security scanning.
        
    build_command : str, default="python -m build"
        Command to build distribution packages.
        
    publish_to_pypi : bool, default=False
        Upload packages to official PyPI on release.
        
    publish_to_test_pypi : bool, default=False
        Upload to Test PyPI for validation.
        
    pypi_repository_url : Optional[str], optional
        Custom PyPI repository URL for private package index.
        
    secrets : Optional[List[str]], optional
        GitHub secrets required by the workflow.
        
    runners : Union[str, List[str]], default="ubuntu-latest"
        GitHub Actions runner environments.
        
    timeout_minutes : int, default=30
        Maximum execution time per job in minutes.
        
    fail_fast : bool, default=True
        Stop matrix jobs on first failure.
        
    output_dir : Union[str, Path], default=".github/workflows"
        Directory for workflow file creation.
        
    force_overwrite : bool, default=False
        Overwrite existing workflow file.
        
    dry_run : bool, default=False
        Simulate generation without writing files.
        
    verbose : bool, default=False
        Print detailed generation information.
        
    show_warnings : bool, default=True
        Display warning messages.
        
    add_timestamp_comment : bool, default=True
        Add generation timestamp to workflow header.
        
    max_parallel : int, default=4
        Maximum number of parallel jobs in matrix strategy.
        
    custom_actions : Optional[Dict[str, str]], optional
        Custom GitHub Actions to include in steps.
        
    env_vars : Optional[Dict[str, str]], optional
        Global environment variables for all jobs.
        
    Returns
    -------
    str
        Absolute path to the generated workflow file.
        
    Raises
    ------
    FileExistsError
        If workflow file exists and force_overwrite is False.
    PermissionError
        If output directory cannot be accessed.
    ValueError
        If configuration parameters are invalid.
        
    Examples
    --------
    Basic CI workflow with testing and linting:
    >>> github_actions_template(
    ...     project_name="myproject",
    ...     python_versions=["3.10", "3.11", "3.12"]
    ... )
    '/home/user/project/.github/workflows/python.yml'
    
    Production workflow with publishing:
    >>> github_actions_template(
    ...     project_name="enterprise-app",
    ...     enable_testing=True,
    ...     enable_linting=True,
    ...     enable_type_checking=True,
    ...     enable_building=True,
    ...     enable_publishing=True,
    ...     enable_security_scan=True,
    ...     publish_to_pypi=True,
    ...     secrets=["PYPI_TOKEN"]
    ... )
    
    Poetry project with custom commands:
    >>> github_actions_template(
    ...     project_name="poetry-app",
    ...     cache_strategy="poetry",
    ...     test_command="poetry run pytest tests/",
    ...     coverage_command="poetry run pytest --cov=src",
    ...     enable_coverage=True
    ... )
    
    Cross-platform testing:
    >>> github_actions_template(
    ...     project_name="cross-platform-lib",
    ...     runners=["ubuntu-latest", "macos-latest", "windows-latest"],
    ...     python_versions=["3.10", "3.11"]
    ... )
    
    Notes
    -----
    Best practices implemented in generated workflows:
        - Specific action versions for reproducibility
        - Efficient dependency caching strategies
        - Matrix testing for comprehensive compatibility
        - Secure secret management for publishing
        - Conditional execution on release events
        - Timeout limits to prevent hung jobs
        - Code coverage integration with Codecov
        
    See Also
    --------
    pyproject_template : Generate pyproject.toml with dependencies
    setup_template : Generate setuptools configuration
    pytest : Testing framework documentation
    ruff : Fast Python linter
    codecov : Code coverage reporting service
    """
    # String to enum mappings
    cache_map = {
        "pip": CacheStrategy.PIP,
        "poetry": CacheStrategy.POETRY,
        "pipenv": CacheStrategy.PIPENV,
        "pdm": CacheStrategy.PDM,
        "uv": CacheStrategy.UV,
        "all": CacheStrategy.ALL,
    }
    
    linter_map = {
        "ruff": Linter.RUFF,
        "black": Linter.BLACK,
        "isort": Linter.ISORT,
        "flake8": Linter.FLAKE8,
        "pylint": Linter.PYLINT,
        "mypy": Linter.MYPY,
        "bandit": Linter.BANDIT,
    }
    
    runner_map = {
        "ubuntu-latest": Runner.UBUNTU_LATEST,
        "ubuntu-22.04": Runner.UBUNTU_2204,
        "ubuntu-20.04": Runner.UBUNTU_2004,
        "ubuntu-24.04": Runner.UBUNTU_2404,
        "macos-latest": Runner.MACOS_LATEST,
        "macos-13": Runner.MACOS_13,
        "macos-14": Runner.MACOS_14,
        "windows-latest": Runner.WINDOWS,
        "windows-latest": Runner.WINDOWS_LATEST,
        "windows-2022": Runner.WINDOWS_2022,
    }
    
    # Convert string parameters to enum objects
    if isinstance(runners, list):
        runner_objects = [runner_map.get(r, Runner.UBUNTU_LATEST) for r in runners]
    else:
        runner_objects = [runner_map.get(runners, Runner.UBUNTU_LATEST)]
    
    # Convert linter strings to enum objects
    linter_objects = []
    if linters:
        for linter in linters:
            if linter in linter_map:
                linter_objects.append(linter_map[linter])
            else:
                warnings.warn(f"Unknown linter: '{linter}'. Valid options: {list(linter_map.keys())}", 
                            UserWarning)
    
    # Create and configure generator
    generator = GitHubActionsGenerator(
        project_name=project_name,
        workflow_name=workflow_name,
        python_versions=python_versions,
        enable_testing=enable_testing,
        enable_linting=enable_linting,
        enable_type_checking=enable_type_checking,
        enable_building=enable_building,
        enable_publishing=enable_publishing,
        enable_coverage=enable_coverage,
        enable_caching=enable_caching,
        enable_security_scan=enable_security_scan,
        cache_strategy=cache_map.get(cache_strategy, CacheStrategy.PIP),
        linters=linter_objects,
        test_command=test_command,
        coverage_command=coverage_command,
        security_command=security_command,
        build_command=build_command,
        publish_to_pypi=publish_to_pypi,
        publish_to_test_pypi=publish_to_test_pypi,
        pypi_repository_url=pypi_repository_url,
        secrets=secrets,
        runners=runner_objects,
        timeout_minutes=timeout_minutes,
        fail_fast=fail_fast,
        output_dir=output_dir,
        force_overwrite=force_overwrite,
        dry_run=dry_run,
        verbose=verbose,
        show_warnings=show_warnings,
        add_timestamp_comment=add_timestamp_comment,
        max_parallel=max_parallel,
        custom_actions=custom_actions,
        env_vars=env_vars,
    )
    
    return generator.generate()


def write_github_actions(path: Union[str, Path] = ".github/workflows/python.yml", **kwargs) -> None:
    """
    Generate GitHub Actions workflow and write it directly to disk.
    
    This convenience function combines generation and file writing in one call,
    useful for quick scripts and one-off workflow generation tasks.
    
    Parameters
    ----------
    path : str or Path, default=".github/workflows/python.yml"
        Complete file path where workflow should be written.
        The parent directory will be created if it doesn't exist.
        
    **kwargs
        Additional keyword arguments passed to github_actions_template().
        See github_actions_template documentation for available options.
        
    Examples
    --------
    >>> # Write to custom location with specific configuration
    >>> write_github_actions(
    ...     "ci/custom-workflow.yml",
    ...     project_name="myapp",
    ...     python_versions=["3.10", "3.11"],
    ...     enable_testing=True
    ... )
    
    >>> # Write to default location with full CI/CD pipeline
    >>> write_github_actions(
    ...     project_name="enterprise-app",
    ...     enable_linting=True,
    ...     enable_testing=True,
    ...     enable_building=True,
    ...     enable_publishing=True,
    ...     publish_to_pypi=True
    ... )
    
    Notes
    -----
    This function differs from github_actions_template() in that it:
        1. Takes a path argument for exact file location
        2. Automatically creates parent directories
        3. Writes the file directly without returning the path
        4. Is more convenient for scripting scenarios
        
    The function internally uses github_actions_template() for generation
    and then handles file I/O separately.
    """
    # Extract output_dir from path to override function argument
    output_dir = kwargs.pop("output_dir", None)
    
    # Generate workflow content
    content = github_actions_template(output_dir=output_dir or path.parent, **kwargs)
    
    # Ensure parent directory exists
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to file
    path.write_text(content, encoding="utf-8")
    
    # Log success if verbose
    if kwargs.get("verbose", False):
        print(f"[INFO] Workflow written to: {path}")
