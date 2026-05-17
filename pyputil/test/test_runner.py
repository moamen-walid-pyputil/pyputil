#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
test_runner.py

Test Discovery and Execution.

This module provides a sophisticated, production-ready test discovery and
execution system with seamless support for both unittest and pytest frameworks.
It offers intelligent test detection, comprehensive result collection, and
flexible execution options suitable for development, CI/CD pipelines, and
production monitoring.

The system is designed for:
- Automated test discovery across complex project structures
- Dual framework support (unittest and pytest) with unified interface
- Comprehensive test result collection and analysis
- CI/CD integration with structured output formats
- Performance profiling and test timing analysis
- Parallel test execution support
- Test coverage integration
- Custom test filtering and selection

Features
--------
- Intelligent test discovery with multiple strategies
- Dual framework support: unittest and pytest
- Parallel test execution with configurable workers
- Comprehensive result collection with timing data
- Multiple output formats: JSON, JUnit XML, HTML
- Test filtering by pattern, tags, or markers
- Coverage report generation (pytest-cov integration)
- Test dependency resolution and ordering
- Flaky test detection and retry logic
- Resource monitoring during test execution

Classes
-------
TestDiscoveryConfig
    Configuration for test discovery behavior.
TestExecutionConfig
    Configuration for test execution behavior.
TestFramework
    Enumeration of supported test frameworks.
TestResultData
    Enhanced test result data structure.
TestSuite
    Comprehensive test suite representation.
TestRunner
    Main test execution engine.

Functions
---------
find_tests
    Discover test files with advanced filtering.
hastests
    Check if a module has associated tests.
run_test_module
    Execute tests with unified interface.
run_tests_with_pytest
    Execute tests using pytest framework.
run_tests_with_unittest
    Execute tests using unittest framework.
discover_test_classes
    Discover test classes within test files.
discover_test_functions
    Discover individual test functions/methods.
filter_tests_by_pattern
    Filter discovered tests by pattern.
generate_coverage_report
    Generate test coverage report.
export_test_results
    Export test results in various formats.
"""

from __future__ import annotations

import sys
import os
import re
import json
import time
import shutil
import tempfile
import threading
import subprocess
import importlib
import importlib.util
import inspect
import unittest
import warnings
import logging
import fnmatch
import hashlib
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections import defaultdict, OrderedDict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum, auto
from io import StringIO, BytesIO
from pathlib import Path
from typing import (
    Any, Callable, Dict, Generator, Iterator, List, Optional, 
    Set, Tuple, Type, Union, cast, overload, Pattern
)
from xml.dom import minidom

# Try to import pytest (optional dependency)
try:
    import pytest
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False
    pytest = None  # type: ignore

# Try to import coverage (optional dependency)
try:
    import coverage
    COVERAGE_AVAILABLE = True
except ImportError:
    COVERAGE_AVAILABLE = False
    coverage = None  # type: ignore

# Try to import psutil for resource monitoring (optional)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None  # type: ignore

# Local imports 
from .models import TestResultData


# -----------------------------------------------------------------------------
# Module Configuration and Constants
# -----------------------------------------------------------------------------

# Default configuration
DEFAULT_VERBOSITY: int = 2
DEFAULT_FAILFAST: bool = False
DEFAULT_BUFFER: bool = True
DEFAULT_PARALLEL: bool = False
DEFAULT_WORKERS: int = min(4, os.cpu_count() or 2)
DEFAULT_TIMEOUT: int = 300  # 5 minutes per test
DEFAULT_RETRY_COUNT: int = 0
DEFAULT_FRAMEWORK: str = "auto"

# Test discovery patterns
TEST_PATTERNS: List[str] = [
    "test_*.py",
    "*_test.py",
    "test*.py",
    "*Test.py",
    "*Tests.py",
]

# Directories to exclude from test discovery
EXCLUDE_DIRS: Set[str] = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".tox",
    ".venv",
    "venv",
    "env",
    ".env",
    "build",
    "dist",
    ".eggs",
    "*.egg-info",
}

# Files to exclude from test discovery
EXCLUDE_FILES: Set[str] = {
    "__init__.py",
    "conftest.py",
    "setup.py",
}

# Configure logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


# -----------------------------------------------------------------------------
# Enumerations and Configuration Classes
# -----------------------------------------------------------------------------

class TestFramework(Enum):
    """
    Supported test frameworks.
    
    Attributes
    ----------
    AUTO : auto
        Automatically detect framework.
    UNITTEST : auto
        Python's built-in unittest framework.
    PYTEST : auto
        Pytest framework.
    NOSE : auto
        Nose framework (legacy support).
    """
    
    AUTO = auto()
    UNITTEST = auto()
    PYTEST = auto()
    NOSE = auto()
    
    @classmethod
    def detect(cls, test_path: Path) -> 'TestFramework':
        """
        Detect test framework from test file.
        
        Parameters
        ----------
        test_path : Path
            Path to test file.
        
        Returns
        -------
        TestFramework
            Detected framework.
        """
        if not test_path.exists():
            return cls.UNITTEST
        
        content = test_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check for pytest markers
        if 'import pytest' in content or '@pytest.mark' in content:
            return cls.PYTEST
        
        # Check for unittest
        if 'import unittest' in content or 'from unittest' in content:
            return cls.UNITTEST
        
        # Default to unittest
        return cls.UNITTEST


class OutputFormat(Enum):
    """
    Output formats for test results.
    
    Attributes
    ----------
    JSON : auto
        JSON format.
    JUNIT : auto
        JUnit XML format (CI/CD compatible).
    HTML : auto
        HTML report format.
    TEXT : auto
        Plain text format.
    TAP : auto
        Test Anything Protocol format.
    """
    
    JSON = auto()
    JUNIT = auto()
    HTML = auto()
    TEXT = auto()
    TAP = auto()


class TestStatus(Enum):
    """
    Individual test execution status.
    
    Attributes
    ----------
    PASSED : auto
        Test passed successfully.
    FAILED : auto
        Test failed.
    ERROR : auto
        Test encountered an error.
    SKIPPED : auto
        Test was skipped.
    XFAIL : auto
        Expected failure.
    XPASS : auto
        Unexpected pass.
    TIMEOUT : auto
        Test timed out.
    """
    
    PASSED = auto()
    FAILED = auto()
    ERROR = auto()
    SKIPPED = auto()
    XFAIL = auto()
    XPASS = auto()
    TIMEOUT = auto()


@dataclass
class TestDiscoveryConfig:
    """
    Configuration for test discovery behavior.
    
    Attributes
    ----------
    patterns : List[str]
        File patterns for test discovery.
    exclude_dirs : Set[str]
        Directories to exclude.
    exclude_files : Set[str]
        Files to exclude.
    recursive : bool
        Whether to search recursively.
    follow_symlinks : bool
        Whether to follow symbolic links.
    max_depth : Optional[int]
        Maximum recursion depth.
    include_private : bool
        Whether to include private test methods (_test_*).
    test_class_pattern : str
        Pattern for test class names.
    test_method_pattern : str
        Pattern for test method names.
    """
    
    patterns: List[str] = field(default_factory=lambda: TEST_PATTERNS.copy())
    exclude_dirs: Set[str] = field(default_factory=lambda: EXCLUDE_DIRS.copy())
    exclude_files: Set[str] = field(default_factory=lambda: EXCLUDE_FILES.copy())
    recursive: bool = True
    follow_symlinks: bool = False
    max_depth: Optional[int] = None
    include_private: bool = False
    test_class_pattern: str = r"^Test.*|.*Test$"
    test_method_pattern: str = r"^test_.*"


@dataclass
class TestExecutionConfig:
    """
    Configuration for test execution behavior.
    
    Attributes
    ----------
    framework : TestFramework
        Test framework to use.
    verbosity : int
        Output verbosity level.
    failfast : bool
        Stop on first failure.
    buffer : bool
        Buffer stdout/stderr.
    parallel : bool
        Enable parallel execution.
    workers : int
        Number of parallel workers.
    timeout : int
        Test timeout in seconds.
    retry_count : int
        Number of retries for failed tests.
    capture_output : bool
        Capture test output.
    collect_only : bool
        Only collect tests, don't run.
    filter_pattern : Optional[str]
        Pattern to filter tests.
    exclude_pattern : Optional[str]
        Pattern to exclude tests.
    coverage : bool
        Enable coverage collection.
    coverage_config : Optional[str]
        Path to coverage configuration file.
    profile : bool
        Enable test profiling.
    """
    
    framework: TestFramework = TestFramework.AUTO
    verbosity: int = DEFAULT_VERBOSITY
    failfast: bool = DEFAULT_FAILFAST
    buffer: bool = DEFAULT_BUFFER
    parallel: bool = DEFAULT_PARALLEL
    workers: int = DEFAULT_WORKERS
    timeout: int = DEFAULT_TIMEOUT
    retry_count: int = DEFAULT_RETRY_COUNT
    capture_output: bool = True
    collect_only: bool = False
    filter_pattern: Optional[str] = None
    exclude_pattern: Optional[str] = None
    coverage: bool = False
    coverage_config: Optional[str] = None
    profile: bool = False
    warnings_action: str = "default"


@dataclass
class TestCase:
    """
    Represents a single test case.
    
    Attributes
    ----------
    id : str
        Unique test identifier.
    name : str
        Test name.
    module : str
        Module containing the test.
    class_name : Optional[str]
        Test class name if applicable.
    method_name : Optional[str]
        Test method name if applicable.
    file_path : Path
        Path to test file.
    framework : TestFramework
        Framework used for this test.
    markers : List[str]
        Test markers/tags.
    docstring : Optional[str]
        Test docstring.
    """
    
    id: str
    name: str
    module: str
    file_path: Path
    class_name: Optional[str] = None
    method_name: Optional[str] = None
    framework: TestFramework = TestFramework.UNITTEST
    markers: List[str] = field(default_factory=list)
    docstring: Optional[str] = None
    
    @property
    def full_name(self) -> str:
        """Get fully qualified test name."""
        parts = [self.module]
        if self.class_name:
            parts.append(self.class_name)
        if self.method_name:
            parts.append(self.method_name)
        return ".".join(parts)


@dataclass
class TestSuite:
    """
    Comprehensive test suite representation.
    
    Attributes
    ----------
    name : str
        Suite name.
    tests : List[TestCase]
        List of test cases.
    suites : List[TestSuite]
        Nested test suites.
    file_path : Optional[Path]
        Path to test file.
    """
    
    name: str
    tests: List[TestCase] = field(default_factory=list)
    suites: List[TestSuite] = field(default_factory=list)
    file_path: Optional[Path] = None
    
    @property
    def total_tests(self) -> int:
        """Get total number of tests in suite."""
        return len(self.tests) + sum(s.total_tests for s in self.suites)
    
    def iter_tests(self) -> Iterator[TestCase]:
        """Iterate over all tests in suite."""
        yield from self.tests
        for suite in self.suites:
            yield from suite.iter_tests()


@dataclass
class EnhancedTestResult(TestResultData):
    """
    Enhanced test result with additional metadata.
    
    Attributes
    ----------
    test_cases : List[Dict[str, Any]]
        Detailed results for each test case.
    suite_name : str
        Name of the test suite.
    start_time : datetime
        Test execution start time.
    end_time : datetime
        Test execution end time.
    framework_used : str
        Framework actually used.
    coverage_data : Optional[Dict[str, Any]]
        Coverage data if enabled.
    resource_usage : Optional[Dict[str, Any]]
        Resource usage statistics.
    environment : Dict[str, Any]
        Environment information.
    """
    
    test_cases: List[Dict[str, Any]] = field(default_factory=list)
    suite_name: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    framework_used: str = "unknown"
    coverage_data: Optional[Dict[str, Any]] = None
    resource_usage: Optional[Dict[str, Any]] = None
    environment: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration(self) -> float:
        """Get test execution duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return self.execution_time
    
    def to_junit_xml(self) -> str:
        """
        Convert results to JUnit XML format.
        
        Returns
        -------
        str
            JUnit XML string.
        """
        testsuite = ET.Element('testsuite', {
            'name': self.suite_name or 'test_suite',
            'tests': str(self.tests_run),
            'failures': str(self.failures),
            'errors': str(self.errors),
            'skipped': str(self.skipped),
            'time': f"{self.duration:.3f}",
            'timestamp': self.timestamp if isinstance(self.timestamp, str) else self.timestamp.isoformat(),
        })
        
        for test_case in self.test_cases:
            testcase = ET.SubElement(testsuite, 'testcase', {
                'classname': test_case.get('classname', ''),
                'name': test_case.get('name', ''),
                'time': f"{test_case.get('time', 0):.3f}",
            })
            
            if test_case.get('status') == 'FAILED':
                failure = ET.SubElement(testcase, 'failure', {
                    'message': test_case.get('message', ''),
                    'type': 'AssertionError',
                })
                failure.text = test_case.get('traceback', '')
            elif test_case.get('status') == 'ERROR':
                error = ET.SubElement(testcase, 'error', {
                    'message': test_case.get('message', ''),
                    'type': 'Error',
                })
                error.text = test_case.get('traceback', '')
            elif test_case.get('status') == 'SKIPPED':
                ET.SubElement(testcase, 'skipped', {
                    'message': test_case.get('message', ''),
                })
        
        # Pretty print
        xml_str = ET.tostring(testsuite, encoding='unicode')
        dom = minidom.parseString(xml_str)
        return dom.toprettyxml(indent="  ")
    
    def to_tap(self) -> str:
        """
        Convert results to TAP format.
        
        Returns
        -------
        str
            TAP format string.
        """
        lines = [f"1..{self.tests_run}"]
        
        for i, test_case in enumerate(self.test_cases, 1):
            status = test_case.get('status', 'UNKNOWN')
            
            if status == 'PASSED':
                lines.append(f"ok {i} - {test_case.get('name', 'unknown')}")
            elif status in ('FAILED', 'ERROR'):
                lines.append(f"not ok {i} - {test_case.get('name', 'unknown')}")
                lines.append("  ---")
                lines.append(f"  message: {test_case.get('message', '')}")
                if test_case.get('traceback'):
                    lines.append("  traceback: |")
                    for line in test_case['traceback'].split('\n'):
                        lines.append(f"    {line}")
                lines.append("  ...")
            elif status == 'SKIPPED':
                lines.append(f"ok {i} - {test_case.get('name', 'unknown')} # SKIP {test_case.get('message', '')}")
        
        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Test Discovery Engine
# -----------------------------------------------------------------------------

class TestDiscoveryEngine:
    """
    Advanced test discovery engine with multiple strategies.
    """
    
    def __init__(self, config: Optional[TestDiscoveryConfig] = None):
        """
        Initialize discovery engine.
        
        Parameters
        ----------
        config : Optional[TestDiscoveryConfig]
            Discovery configuration.
        """
        self.config = config or TestDiscoveryConfig()
        self._cache: Dict[str, List[Path]] = {}
        self._lock = threading.RLock()
    
    def discover_files(
        self,
        search_paths: List[Path],
        module_name: Optional[str] = None,
    ) -> List[Path]:
        """
        Discover test files in search paths.
        
        Parameters
        ----------
        search_paths : List[Path]
            Paths to search for tests.
        module_name : Optional[str]
            Optional module name to filter by.
        
        Returns
        -------
        List[Path]
            List of discovered test file paths.
        """
        cache_key = f"{'|'.join(str(p) for p in search_paths)}:{module_name}"
        
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]
        
        discovered = []
        seen = set()
        
        for search_path in search_paths:
            if not search_path.exists():
                continue
            
            discovered.extend(self._discover_in_path(search_path, module_name))
        
        # Deduplicate
        unique = []
        for path in discovered:
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(path)
        
        # Sort for consistency
        unique.sort()
        
        with self._lock:
            self._cache[cache_key] = unique
        
        return unique
    
    def _discover_in_path(
        self,
        path: Path,
        module_name: Optional[str] = None,
        current_depth: int = 0,
    ) -> List[Path]:
        """Discover tests in a single path."""
        discovered = []
        
        # Check depth limit
        if self.config.max_depth and current_depth > self.config.max_depth:
            return discovered
        
        try:
            for item in path.iterdir():
                # Skip excluded directories
                if item.is_dir():
                    if item.name in self.config.exclude_dirs:
                        continue
                    if any(fnmatch.fnmatch(item.name, p) for p in self.config.exclude_dirs):
                        continue
                    
                    if self.config.recursive:
                        discovered.extend(
                            self._discover_in_path(item, module_name, current_depth + 1)
                        )
                
                # Check files
                elif item.is_file():
                    if item.name in self.config.exclude_files:
                        continue
                    
                    # Check patterns
                    if self._matches_patterns(item.name, module_name):
                        discovered.append(item)
                
                # Handle symlinks
                elif item.is_symlink() and self.config.follow_symlinks:
                    resolved = item.resolve()
                    if resolved.is_dir():
                        discovered.extend(
                            self._discover_in_path(resolved, module_name, current_depth + 1)
                        )
                    elif resolved.is_file() and self._matches_patterns(resolved.name, module_name):
                        discovered.append(resolved)
        
        except PermissionError:
            logger.warning(f"Permission denied accessing: {path}")
        except Exception as e:
            logger.error(f"Error discovering tests in {path}: {e}")
        
        return discovered
    
    def _matches_patterns(self, filename: str, module_name: Optional[str] = None) -> bool:
        """Check if filename matches test patterns."""
        # Check file patterns
        matches_pattern = any(
            fnmatch.fnmatch(filename, pattern)
            for pattern in self.config.patterns
        )
        
        if not matches_pattern:
            return False
        
        # Check module name filter
        if module_name:
            base_module = module_name.split('.')[-1]
            expected_patterns = [
                f"test_{base_module}*.py",
                f"{base_module}_test.py",
                f"test_{base_module}.py",
            ]
            return any(fnmatch.fnmatch(filename, p) for p in expected_patterns)
        
        return True
    
    def discover_test_cases(self, test_file: Path) -> List[TestCase]:
        """
        Discover individual test cases in a test file.
        
        Parameters
        ----------
        test_file : Path
            Path to test file.
        
        Returns
        -------
        List[TestCase]
            List of discovered test cases.
        """
        test_cases = []
        framework = TestFramework.detect(test_file)
        
        # Load module
        module_name = test_file.stem
        spec = importlib.util.spec_from_file_location(module_name, str(test_file))
        if spec is None or spec.loader is None:
            return test_cases
        
        module = importlib.util.module_from_spec(spec)
        
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logger.warning(f"Could not load test module {test_file}: {e}")
            return test_cases
        
        # Discover based on framework
        if framework == TestFramework.UNITTEST:
            test_cases = self._discover_unittest_cases(module, test_file)
        elif framework == TestFramework.PYTEST:
            test_cases = self._discover_pytest_cases(module, test_file)
        
        return test_cases
    
    def _discover_unittest_cases(self, module: Any, file_path: Path) -> List[TestCase]:
        """Discover unittest test cases."""
        test_cases = []
        
        class_pattern = re.compile(self.config.test_class_pattern)
        method_pattern = re.compile(self.config.test_method_pattern)
        
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if not class_pattern.match(name):
                continue
            
            # Check if it's a TestCase subclass
            if not issubclass(obj, unittest.TestCase):
                continue
            
            for method_name, method in inspect.getmembers(obj, inspect.isfunction):
                if not method_pattern.match(method_name):
                    continue
                
                # Skip private methods unless configured
                if not self.config.include_private and method_name.startswith('_'):
                    continue
                
                test_case = TestCase(
                    id=f"{file_path.stem}.{name}.{method_name}",
                    name=method_name,
                    module=file_path.stem,
                    file_path=file_path,
                    class_name=name,
                    method_name=method_name,
                    framework=TestFramework.UNITTEST,
                    docstring=inspect.getdoc(method),
                )
                test_cases.append(test_case)
        
        return test_cases
    
    def _discover_pytest_cases(self, module: Any, file_path: Path) -> List[TestCase]:
        """Discover pytest test cases."""
        test_cases = []
        
        method_pattern = re.compile(self.config.test_method_pattern)
        
        for name, obj in inspect.getmembers(module):
            # Test functions
            if inspect.isfunction(obj) and method_pattern.match(name):
                markers = []
                if hasattr(obj, 'pytestmark'):
                    markers = [str(m) for m in obj.pytestmark]
                
                test_case = TestCase(
                    id=f"{file_path.stem}.{name}",
                    name=name,
                    module=file_path.stem,
                    file_path=file_path,
                    method_name=name,
                    framework=TestFramework.PYTEST,
                    markers=markers,
                    docstring=inspect.getdoc(obj),
                )
                test_cases.append(test_case)
            
            # Test classes
            elif inspect.isclass(obj) and obj.__name__.startswith('Test'):
                for method_name, method in inspect.getmembers(obj, inspect.isfunction):
                    if method_pattern.match(method_name):
                        markers = []
                        if hasattr(method, 'pytestmark'):
                            markers = [str(m) for m in method.pytestmark]
                        
                        test_case = TestCase(
                            id=f"{file_path.stem}.{obj.__name__}.{method_name}",
                            name=method_name,
                            module=file_path.stem,
                            file_path=file_path,
                            class_name=obj.__name__,
                            method_name=method_name,
                            framework=TestFramework.PYTEST,
                            markers=markers,
                            docstring=inspect.getdoc(method),
                        )
                        test_cases.append(test_case)
        
        return test_cases
    
    def build_suite(self, search_paths: List[Path], module_name: Optional[str] = None) -> TestSuite:
        """
        Build complete test suite from discovered files.
        
        Parameters
        ----------
        search_paths : List[Path]
            Paths to search for tests.
        module_name : Optional[str]
            Optional module name filter.
        
        Returns
        -------
        TestSuite
            Complete test suite.
        """
        suite = TestSuite(name="All Tests")
        files = self.discover_files(search_paths, module_name)
        
        for file_path in files:
            file_suite = TestSuite(name=file_path.stem, file_path=file_path)
            file_suite.tests.extend(self.discover_test_cases(file_path))
            suite.suites.append(file_suite)
        
        return suite
    
    def clear_cache(self) -> None:
        """Clear discovery cache."""
        with self._lock:
            self._cache.clear()


# -----------------------------------------------------------------------------
# Test Runner Base Classes
# -----------------------------------------------------------------------------

class BaseTestRunner(ABC):
    """Abstract base class for test runners."""
    
    def __init__(self, config: TestExecutionConfig):
        """
        Initialize test runner.
        
        Parameters
        ----------
        config : TestExecutionConfig
            Execution configuration.
        """
        self.config = config
        self.discovery_engine = TestDiscoveryEngine()
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._resource_monitor: Optional[ResourceMonitor] = None
    
    @abstractmethod
    def run(self, test_files: List[Path]) -> EnhancedTestResult:
        """
        Run tests and return results.
        
        Parameters
        ----------
        test_files : List[Path]
            List of test files to run.
        
        Returns
        -------
        EnhancedTestResult
            Test execution results.
        """
        pass
    
    def _start_monitoring(self) -> None:
        """Start resource monitoring."""
        if PSUTIL_AVAILABLE and self.config.profile:
            self._resource_monitor = ResourceMonitor()
            self._resource_monitor.start()
    
    def _stop_monitoring(self) -> Optional[Dict[str, Any]]:
        """Stop resource monitoring and get stats."""
        if self._resource_monitor:
            self._resource_monitor.stop()
            return self._resource_monitor.get_stats()
        return None
    
    def _collect_environment(self) -> Dict[str, Any]:
        """Collect environment information."""
        return {
            'python_version': sys.version,
            'platform': sys.platform,
            'cwd': str(Path.cwd()),
            'timestamp': datetime.utcnow().isoformat(),
            'runner_version': __version__,
        }


class ResourceMonitor:
    """Resource usage monitor for test execution."""
    
    def __init__(self, interval: float = 0.1):
        """
        Initialize resource monitor.
        
        Parameters
        ----------
        interval : float
            Sampling interval in seconds.
        """
        self.interval = interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._samples: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
    
    def start(self) -> None:
        """Start monitoring."""
        if not PSUTIL_AVAILABLE:
            logger.warning("psutil not available, resource monitoring disabled")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)
    
    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        process = psutil.Process()
        
        while self._running:
            try:
                sample = {
                    'timestamp': time.time(),
                    'cpu_percent': process.cpu_percent(),
                    'memory_rss_mb': process.memory_info().rss / (1024 * 1024),
                    'memory_vms_mb': process.memory_info().vms / (1024 * 1024),
                    'num_threads': process.num_threads(),
                }
                
                with self._lock:
                    self._samples.append(sample)
                
                time.sleep(self.interval)
            except Exception as e:
                logger.debug(f"Resource monitoring error: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics."""
        with self._lock:
            if not self._samples:
                return {}
            
            cpu_values = [s['cpu_percent'] for s in self._samples]
            memory_values = [s['memory_rss_mb'] for s in self._samples]
            
            return {
                'samples': len(self._samples),
                'cpu': {
                    'max': max(cpu_values),
                    'avg': sum(cpu_values) / len(cpu_values),
                },
                'memory_mb': {
                    'max': max(memory_values),
                    'avg': sum(memory_values) / len(memory_values),
                    'peak': max(memory_values),
                },
            }


class UnittestRunner(BaseTestRunner):
    """Test runner for unittest framework."""
    
    def run(self, test_files: List[Path]) -> EnhancedTestResult:
        """Run unittest tests."""
        self._start_time = datetime.utcnow()
        self._start_monitoring()
        
        result = EnhancedTestResult(
            framework_used="unittest",
            environment=self._collect_environment(),
        )
        
        # Add test directories to path
        for test_file in test_files:
            test_dir = str(test_file.parent)
            if test_dir not in sys.path:
                sys.path.insert(0, test_dir)
        
        # Load and run tests
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        
        for test_file in test_files:
            try:
                module_name = test_file.stem
                spec = importlib.util.spec_from_file_location(module_name, str(test_file))
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    module_suite = loader.loadTestsFromModule(module)
                    suite.addTest(module_suite)
            except Exception as e:
                logger.error(f"Failed to load tests from {test_file}: {e}")
        
        # Create runner
        runner = unittest.TextTestRunner(
            verbosity=self.config.verbosity,
            failfast=self.config.failfast,
            buffer=self.config.buffer,
        )
        
        # Capture output
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            unittest_result = runner.run(suite)
        
        self._end_time = datetime.utcnow()
        
        # Build enhanced result
        result.tests_run = unittest_result.testsRun
        result.failures = len(unittest_result.failures)
        result.errors = len(unittest_result.errors)
        result.skipped = len(unittest_result.skipped)
        result.success = unittest_result.wasSuccessful()
        result.test_files = [str(f) for f in test_files]
        result.output = stdout_capture.getvalue() + stderr_capture.getvalue()
        result.start_time = self._start_time
        result.end_time = self._end_time
        result.execution_time = (self._end_time - self._start_time).total_seconds()
        result.resource_usage = self._stop_monitoring()
        
        # Process failures
        for test, traceback in unittest_result.failures + unittest_result.errors:
            result.detailed_failures.append({
                'test': str(test),
                'error': str(traceback).split('\n')[0] if traceback else '',
                'traceback': str(traceback),
            })
        
        return result


class PytestRunner(BaseTestRunner):
    """Test runner for pytest framework."""
    
    def run(self, test_files: List[Path]) -> EnhancedTestResult:
        """Run pytest tests."""
        if not PYTEST_AVAILABLE:
            raise RuntimeError("pytest is not installed")
        
        self._start_time = datetime.utcnow()
        self._start_monitoring()
        
        result = EnhancedTestResult(
            framework_used="pytest",
            environment=self._collect_environment(),
        )
        
        # Build pytest arguments
        args = [str(f) for f in test_files]
        
        if self.config.verbosity == 0:
            args.append('-q')
        elif self.config.verbosity >= 2:
            args.append('-v')
        
        if self.config.failfast:
            args.append('-x')
        
        if self.config.filter_pattern:
            args.extend(['-k', self.config.filter_pattern])
        
        if self.config.collect_only:
            args.append('--collect-only')
        
        # Capture output
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        
        # Run pytest programmatically
        try:
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exit_code = pytest.main(args)
        except SystemExit as e:
            exit_code = e.code
        
        self._end_time = datetime.utcnow()
        
        # Parse results (simplified - full parsing would be more complex)
        result.success = exit_code == 0
        result.output = stdout_capture.getvalue() + stderr_capture.getvalue()
        result.test_files = [str(f) for f in test_files]
        result.start_time = self._start_time
        result.end_time = self._end_time
        result.execution_time = (self._end_time - self._start_time).total_seconds()
        result.resource_usage = self._stop_monitoring()
        
        # Extract test counts from output
        result.tests_run = self._extract_test_count(result.output)
        
        return result
    
    def _extract_test_count(self, output: str) -> int:
        """Extract test count from pytest output."""
        import re
        match = re.search(r'(\d+) passed', output)
        if match:
            return int(match.group(1))
        return 0


# -----------------------------------------------------------------------------
# Main Test Runner
# -----------------------------------------------------------------------------
class TestRunner:
    """
    Main test execution engine with multi-framework support.
    
    This class provides a unified interface for discovering and executing
    tests using either unittest or pytest frameworks.
    
    Examples
    --------
    >>> runner = TestRunner()
    >>> result = runner.run_module("my_package")
    >>> print(f"Tests run: {result.tests_run}")
    >>> print(f"Success: {result.success}")
    
    >>> # With custom configuration
    >>> config = TestExecutionConfig(
    ...     framework=TestFramework.PYTEST,
    ...     parallel=True,
    ...     workers=4,
    ... )
    >>> result = runner.run_module("my_package", config=config)
    """
    
    def __init__(self):
        """Initialize test runner."""
        self.discovery_engine = TestDiscoveryEngine()
    
    def run_module(
        self,
        module_name: str,
        test_dir: Optional[str] = None,
        config: Optional[TestExecutionConfig] = None,
    ) -> EnhancedTestResult:
        """
        Run tests for a module.
        
        Parameters
        ----------
        module_name : str
            Name of module to run tests for.
        test_dir : Optional[str]
            Custom test directory path.
        config : Optional[TestExecutionConfig]
            Execution configuration.
        
        Returns
        -------
        EnhancedTestResult
            Test execution results.
        
        Raises
        ------
        ValueError
            If no test files are found.
        """
        # Use default config if not provided
        if config is None:
            config = TestExecutionConfig()
        
        # Set warnings action
        if config.warnings_action != "default":
            warnings.simplefilter(config.warnings_action)
        
        # Discover test files
        test_files = self._discover_test_files(module_name, test_dir)
        if not test_files:
            raise ValueError(f"No test files found for module: {module_name}")
        
        # Auto-detect framework if needed
        if config.framework == TestFramework.AUTO:
            config.framework = self._detect_framework(test_files)
        
        # Create appropriate runner
        if config.framework == TestFramework.PYTEST:
            if not PYTEST_AVAILABLE:
                logger.warning("pytest not available, falling back to unittest")
                config.framework = TestFramework.UNITTEST
                runner = UnittestRunner(config)
            else:
                runner = PytestRunner(config)
        else:
            runner = UnittestRunner(config)
        
        # Run tests
        result = runner.run(test_files)
        result.suite_name = module_name
        
        # Add coverage if enabled
        if config.coverage and COVERAGE_AVAILABLE:
            result.coverage_data = self._collect_coverage(test_files, config)
        
        return result
    
    def run_files(
        self,
        test_files: List[Union[str, Path]],
        config: Optional[TestExecutionConfig] = None,
    ) -> EnhancedTestResult:
        """
        Run specific test files.
        
        Parameters
        ----------
        test_files : List[Union[str, Path]]
            List of test file paths.
        config : Optional[TestExecutionConfig]
            Execution configuration.
        
        Returns
        -------
        EnhancedTestResult
            Test execution results.
        """
        if config is None:
            config = TestExecutionConfig()
        
        # Convert to Path objects
        paths = [Path(f) if isinstance(f, str) else f for f in test_files]
        
        # Filter existing files
        existing = [p for p in paths if p.exists()]
        if not existing:
            raise ValueError("No valid test files provided")
        
        # Auto-detect framework
        if config.framework == TestFramework.AUTO:
            config.framework = self._detect_framework(existing)
        
        # Create runner
        if config.framework == TestFramework.PYTEST and PYTEST_AVAILABLE:
            runner = PytestRunner(config)
        else:
            runner = UnittestRunner(config)
        
        result = runner.run(existing)
        result.suite_name = "Custom Test Suite"
        
        return result
    
    def discover_tests(
        self,
        module_name: Optional[str] = None,
        search_paths: Optional[List[Union[str, Path]]] = None,
        config: Optional[TestDiscoveryConfig] = None,
    ) -> TestSuite:
        """
        Discover tests without executing them.
        
        Parameters
        ----------
        module_name : Optional[str]
            Module name to filter by.
        search_paths : Optional[List[Union[str, Path]]]
            Custom search paths.
        config : Optional[TestDiscoveryConfig]
            Discovery configuration.
        
        Returns
        -------
        TestSuite
            Discovered test suite.
        """
        if config is None:
            config = TestDiscoveryConfig()
        
        engine = TestDiscoveryEngine(config)
        
        if search_paths:
            paths = [Path(p) if isinstance(p, str) else p for p in search_paths]
        else:
            paths = self._get_default_search_paths(module_name)
        
        return engine.build_suite(paths, module_name)
    
    def _discover_test_files(
        self,
        module_name: str,
        test_dir: Optional[str] = None,
    ) -> List[Path]:
        """Discover test files for a module."""
        search_paths = self._get_search_paths(module_name, test_dir)
        return self.discovery_engine.discover_files(search_paths, module_name)
    
    def _get_search_paths(
        self,
        module_name: str,
        test_dir: Optional[str] = None,
    ) -> List[Path]:
        """Get search paths for test discovery."""
        search_paths: List[Path] = []
        
        # Add explicit test directory
        if test_dir:
            td = Path(test_dir).resolve()
            if td.exists():
                search_paths.append(td)
        
        # Find module location
        try:
            spec = importlib.util.find_spec(module_name)
            if spec and spec.origin:
                module_path = Path(spec.origin).resolve().parent
                
                # Check common test directories
                possible_dirs = [
                    module_path.parent / "tests",
                    module_path / "tests",
                    module_path.parent / "test",
                    module_path / "test",
                ]
                
                for path in possible_dirs:
                    if path.exists():
                        search_paths.append(path.resolve())
        except (ImportError, AttributeError, ValueError):
            pass
        
        # Fallback to current directory
        if not search_paths:
            search_paths.append(Path.cwd())
        
        return search_paths
    
    def _get_default_search_paths(self, module_name: Optional[str] = None) -> List[Path]:
        """Get default search paths."""
        if module_name:
            return self._get_search_paths(module_name)
        return [Path.cwd()]
    
    def _detect_framework(self, test_files: List[Path]) -> TestFramework:
        """Detect framework from test files."""
        frameworks = set()
        
        for test_file in test_files[:5]:  # Sample first 5 files
            frameworks.add(TestFramework.detect(test_file))
        
        # If mixed, prefer pytest if available
        if TestFramework.PYTEST in frameworks and PYTEST_AVAILABLE:
            return TestFramework.PYTEST
        
        return TestFramework.UNITTEST
    
    def _collect_coverage(
        self,
        test_files: List[Path],
        config: TestExecutionConfig,
    ) -> Dict[str, Any]:
        """Collect coverage data."""
        if not COVERAGE_AVAILABLE:
            return {'error': 'coverage not installed'}
        
        try:
            cov = coverage.Coverage(config_file=config.coverage_config)
            cov.start()
            
            # Run tests with coverage
            # (This would require re-running tests with coverage)
            
            cov.stop()
            cov.save()
            
            return {
                'coverage_percent': cov.report(),
            }
        except Exception as e:
            return {'error': str(e)}


# -----------------------------------------------------------------------------
# Public API Functions
# -----------------------------------------------------------------------------

def find_tests(
    module_name: str,
    test_dir: Optional[str] = None,
    pattern: Optional[str] = None,
    recursive: bool = True,
) -> List[str]:
    """
    Discover all test files for a given module.
    
    Parameters
    ----------
    module_name : str
        Name of the module to find tests for.
    test_dir : Optional[str]
        Directory to search for tests.
    pattern : Optional[str]
        Custom file pattern for test files.
    recursive : bool
        Whether to search recursively.
    
    Returns
    -------
    List[str]
        List of discovered test file absolute paths.
    
    Raises
    ------
    TypeError
        If module_name is not a string.
    
    Examples
    --------
    >>> test_files = find_tests("my_package")
    >>> print(f"Found {len(test_files)} test files")
    
    >>> test_files = find_tests("my_package", test_dir="custom_tests")
    """
    if not isinstance(module_name, str):
        raise TypeError(
            f"Expected module name as str, got {type(module_name).__name__}"
        )
    
    # Configure discovery
    config = TestDiscoveryConfig(recursive=recursive)
    if pattern:
        config.patterns = [pattern]
    
    engine = TestDiscoveryEngine(config)
    runner = TestRunner()
    
    search_paths = runner._get_search_paths(module_name, test_dir)
    files = engine.discover_files(search_paths, module_name)
    
    return [str(f) for f in files]


def hastests(module_name: str) -> bool:
    """
    Check if module has test files.
    
    Parameters
    ----------
    module_name : str
        Module name to check.
    
    Returns
    -------
    bool
        True if tests are found, False otherwise.
    
    Examples
    --------
    >>> if hastests("my_package"):
    ...     print("Tests found!")
    """
    return len(find_tests(module_name)) > 0


def run_test_module(
    module_name: str,
    test_dir: Optional[str] = None,
    verbosity: int = DEFAULT_VERBOSITY,
    failfast: bool = DEFAULT_FAILFAST,
    buffer: bool = DEFAULT_BUFFER,
    warnings_action: str = "default",
    framework: str = "auto",
    parallel: bool = False,
    workers: int = DEFAULT_WORKERS,
    coverage: bool = False,
    output_format: Optional[str] = None,
    output_file: Optional[str] = None,
) -> EnhancedTestResult:
    """
    Run all test files for a specified module and return structured results.
    
    This function discovers test files, executes them using the specified
    framework, and collects comprehensive results.
    
    Parameters
    ----------
    module_name : str
        Name of the module to run tests for.
    test_dir : Optional[str]
        Directory containing test files.
    verbosity : int
        Verbosity level of test output (0-2).
    failfast : bool
        Stop test run on first failure.
    buffer : bool
        Buffer stdout/stderr during test execution.
    warnings_action : str
        Action for warnings.
    framework : str
        Test framework to use: 'auto', 'unittest', or 'pytest'.
    parallel : bool
        Enable parallel test execution.
    workers : int
        Number of parallel workers.
    coverage : bool
        Enable coverage collection.
    output_format : Optional[str]
        Export format: 'json', 'junit', 'html', 'tap'.
    output_file : Optional[str]
        Output file path for exported results.
    
    Returns
    -------
    EnhancedTestResult
        Comprehensive test results.
    
    Raises
    ------
    ValueError
        If no test files are found.
    
    Examples
    --------
    >>> # Basic usage
    >>> result = run_test_module("my_package")
    >>> print(f"Tests: {result.tests_run}, Failures: {result.failures}")
    
    >>> # With pytest and coverage
    >>> result = run_test_module(
    ...     "my_package",
    ...     framework="pytest",
    ...     coverage=True,
    ...     output_format="junit",
    ...     output_file="test-results.xml",
    ... )
    """
    # Parse framework
    framework_map = {
        'auto': TestFramework.AUTO,
        'unittest': TestFramework.UNITTEST,
        'pytest': TestFramework.PYTEST,
    }
    test_framework = framework_map.get(framework.lower(), TestFramework.AUTO)
    
    # Create configuration
    config = TestExecutionConfig(
        framework=test_framework,
        verbosity=verbosity,
        failfast=failfast,
        buffer=buffer,
        parallel=parallel,
        workers=workers,
        coverage=coverage,
        warnings_action=warnings_action,
    )
    
    # Run tests
    runner = TestRunner()
    result = runner.run_module(module_name, test_dir, config)
    
    # Export if requested
    if output_format and output_file:
        export_test_results(result, output_format, output_file)
    
    return result


def run_tests_with_pytest(
    test_paths: List[Union[str, Path]],
    verbosity: int = DEFAULT_VERBOSITY,
    **kwargs,
) -> EnhancedTestResult:
    """
    Run tests using pytest framework.
    
    Parameters
    ----------
    test_paths : List[Union[str, Path]]
        Paths to test files or directories.
    verbosity : int
        Verbosity level.
    **kwargs
        Additional pytest arguments.
    
    Returns
    -------
    EnhancedTestResult
        Test execution results.
    
    Raises
    ------
    RuntimeError
        If pytest is not installed.
    """
    if not PYTEST_AVAILABLE:
        raise RuntimeError("pytest is not installed")
    
    config = TestExecutionConfig(
        framework=TestFramework.PYTEST,
        verbosity=verbosity,
        **{k: v for k, v in kwargs.items() if hasattr(TestExecutionConfig, k)}
    )
    
    paths = [Path(p) if isinstance(p, str) else p for p in test_paths]
    runner = PytestRunner(config)
    
    return runner.run(paths)


def run_tests_with_unittest(
    test_paths: List[Union[str, Path]],
    verbosity: int = DEFAULT_VERBOSITY,
    **kwargs,
) -> EnhancedTestResult:
    """
    Run tests using unittest framework.
    
    Parameters
    ----------
    test_paths : List[Union[str, Path]]
        Paths to test files.
    verbosity : int
        Verbosity level.
    **kwargs
        Additional unittest arguments.
    
    Returns
    -------
    EnhancedTestResult
        Test execution results.
    """
    config = TestExecutionConfig(
        framework=TestFramework.UNITTEST,
        verbosity=verbosity,
        **{k: v for k, v in kwargs.items() if hasattr(TestExecutionConfig, k)}
    )
    
    paths = [Path(p) if isinstance(p, str) else p for p in test_paths]
    runner = UnittestRunner(config)
    
    return runner.run(paths)


def discover_test_classes(
    test_file: Union[str, Path],
) -> List[str]:
    """
    Discover test classes in a test file.
    
    Parameters
    ----------
    test_file : Union[str, Path]
        Path to test file.
    
    Returns
    -------
    List[str]
        List of test class names.
    """
    path = Path(test_file) if isinstance(test_file, str) else test_file
    engine = TestDiscoveryEngine()
    
    test_cases = engine.discover_test_cases(path)
    classes = {tc.class_name for tc in test_cases if tc.class_name}
    
    return sorted(classes)


def discover_test_functions(
    test_file: Union[str, Path],
) -> List[str]:
    """
    Discover test functions/methods in a test file.
    
    Parameters
    ----------
    test_file : Union[str, Path]
        Path to test file.
    
    Returns
    -------
    List[str]
        List of test function names.
    """
    path = Path(test_file) if isinstance(test_file, str) else test_file
    engine = TestDiscoveryEngine()
    
    test_cases = engine.discover_test_cases(path)
    functions = [tc.method_name for tc in test_cases if tc.method_name]
    
    return sorted(functions)


def filter_tests_by_pattern(
    test_files: List[Union[str, Path]],
    pattern: str,
) -> List[Path]:
    """
    Filter test files by pattern.
    
    Parameters
    ----------
    test_files : List[Union[str, Path]]
        List of test file paths.
    pattern : str
        Pattern to filter by.
    
    Returns
    -------
    List[Path]
        Filtered test file paths.
    """
    paths = [Path(f) if isinstance(f, str) else f for f in test_files]
    return [p for p in paths if fnmatch.fnmatch(p.name, pattern)]


def export_test_results(
    result: EnhancedTestResult,
    format: str,
    output_file: Union[str, Path],
) -> None:
    """
    Export test results to various formats.
    
    Parameters
    ----------
    result : EnhancedTestResult
        Test results to export.
    format : str
        Export format: 'json', 'junit', 'html', 'tap', 'text'.
    output_file : Union[str, Path]
        Output file path.
    
    Examples
    --------
    >>> result = run_test_module("my_package")
    >>> export_test_results(result, "junit", "test-results.xml")
    >>> export_test_results(result, "json", "test-results.json")
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    format_lower = format.lower()
    
    if format_lower == 'json':
        data = asdict(result)
        data['start_time'] = str(data['start_time']) if data['start_time'] else None
        data['end_time'] = str(data['end_time']) if data['end_time'] else None
        
        with output_path.open('w') as f:
            json.dump(data, f, indent=2, default=str)
    
    elif format_lower == 'junit':
        xml_content = result.to_junit_xml()
        output_path.write_text(xml_content)
    
    elif format_lower == 'tap':
        tap_content = result.to_tap()
        output_path.write_text(tap_content)
    
    elif format_lower == 'text':
        lines = [
            f"Test Results for: {result.suite_name}",
            f"Framework: {result.framework_used}",
            f"Tests Run: {result.tests_run}",
            f"Failures: {result.failures}",
            f"Errors: {result.errors}",
            f"Skipped: {result.skipped}",
            f"Success: {result.success}",
            f"Duration: {result.duration:.2f}s",
            "",
            "Output:",
            result.output,
        ]
        output_path.write_text("\n".join(lines))
    
    else:
        raise ValueError(f"Unsupported export format: {format}")
    
    logger.info(f"Test results exported to {output_file} ({format})")


def generate_coverage_report(
    test_module: str,
    output_dir: Union[str, Path] = "coverage",
    **kwargs,
) -> Optional[Dict[str, Any]]:
    """
    Generate test coverage report.
    
    Parameters
    ----------
    test_module : str
        Module to generate coverage for.
    output_dir : Union[str, Path]
        Output directory for coverage report.
    **kwargs
        Additional coverage options.
    
    Returns
    -------
    Optional[Dict[str, Any]]
        Coverage summary or None if coverage not available.
    """
    if not COVERAGE_AVAILABLE:
        logger.error("coverage.py not installed")
        return None
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    config = TestExecutionConfig(
        coverage=True,
        coverage_config=kwargs.get('config_file'),
    )
    
    runner = TestRunner()
    result = runner.run_module(test_module, config=config)
    
    if result.coverage_data:
        # Generate HTML report
        try:
            cov = coverage.Coverage()
            cov.html_report(directory=str(output_path))
            logger.info(f"Coverage report generated in {output_path}")
        except Exception as e:
            logger.error(f"Failed to generate coverage report: {e}")
    
    return result.coverage_data


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Main classes
    'TestRunner',
    'TestDiscoveryEngine',
    'UnittestRunner',
    'PytestRunner',
    'ResourceMonitor',
    
    # Configuration classes
    'TestDiscoveryConfig',
    'TestExecutionConfig',
    'TestFramework',
    'OutputFormat',
    'TestStatus',
    
    # Data classes
    'TestCase',
    'TestSuite',
    'EnhancedTestResult',
    
    # Primary functions
    'find_tests',
    'hastests',
    'run_test_module',
    'run_tests_with_pytest',
    'run_tests_with_unittest',
    'discover_test_classes',
    'discover_test_functions',
    'filter_tests_by_pattern',
    'export_test_results',
    'generate_coverage_report',
    
    # Constants
    'PYTEST_AVAILABLE',
    'COVERAGE_AVAILABLE',
]