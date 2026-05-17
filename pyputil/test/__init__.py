#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
PypUtil Test Project - Advanced Python Import Performance Analysis Toolkit
============================================================================

A comprehensive, production-ready toolkit for profiling, analyzing, and optimizing
Python module import performance. This package provides deep introspection into
import timing, memory consumption, dependency complexity, and runtime stability,
empowering developers to identify and resolve import-related bottlenecks.

The toolkit excels in:
----------------------
- CI/CD Integration: Automated performance regression detection
- Development Workflows: Interactive profiling and optimization
- Documentation Generation: Automated API documentation from live modules
- Testing Infrastructure: Cross-framework test discovery and execution
- Dependency Management: Virtual overlays and fake imports for testing
- Code Quality: Case-insensitive imports with typo correction
- Dynamic Imports: Flexible module loading with conflict resolution
- Execution Analysis: Deep module behavior analysis and fuzzing
- Import Tracking: Real-time import event monitoring and health scoring

Core Capabilities
-----------------
Performance Profiling: Multi-dimensional import analysis
  - Wall-clock timing with statistical rigor (mean, stddev, percentiles)
  - Peak memory consumption with allocation tracking
  - Transitive dependency counting with graph analysis
  - Import stability measurement (coefficient of variation)

Module Utilities: Advanced import manipulation
  - Case-insensitive attribute access with fuzzy typo correction
  - Dynamic module loading from arbitrary project locations
  - Virtual site-packages overlay for isolated testing
  - Fake import system for missing dependency simulation

Execution Analysis: Deep module behavior inspection
  - Function-level execution tracing and analysis
  - Health scoring with configurable severity levels
  - Circular dependency detection
  - Fuzzing capabilities for robustness testing
  - Import event tracking with detailed statistics

Test Infrastructure: Complete testing toolkit
  - Multi-framework support (unittest, pytest)
  - Intelligent test discovery with filtering
  - Comprehensive result collection and export

Documentation Engine: Automatic documentation generation
  - Multi-format output (rst, markdown, html, plain, json)
  - Type hint extraction and formatting
  - Usage example generation

Quick Start
-----------
>>> from pyputil.test import profile_import
>>> profile = profile_import("numpy", repetitions=10)
>>> print(f"NumPy import: {profile.time.formatted_average}")
>>> print(f"Memory: {profile.memory.formatted_peak}")

>>> from pyputil.test import difftime
>>> numpy, pandas, comparison = difftime("numpy", "pandas")
>>> print(comparison.summary)

>>> from pyputil.test import patch_module_case
>>> patch_module_case("requests")
>>> import requests
>>> response = requests.gEt("https://api.example.com")

>>> from pyputil.test import run_test_module
>>> result = run_test_module("my_package", framework="pytest")
>>> print(result.summary)

>>> from pyputil.test import doc_module
>>> import math
>>> docs = doc_module(math, format="markdown", include_toc=True)

>>> from pyputil.test import track_module, ImportTracker
>>> tracker = ImportTracker()
>>> tracker.start()
>>> import numpy
>>> events = tracker.stop()
>>> print(f"Tracked {len(events)} import events")

>>> from pyputil.test import execute_module, HealthScoreCalculator
>>> result = execute_module("my_module", analysis_depth=3)
>>> calculator = HealthScoreCalculator()
>>> health = calculator.calculate(result)
>>> print(f"Module health score: {health.overall_score}")

Package Structure
-----------------
pyputil.test/
    __init__.py              Package initialization and public API
    performance.py           Main profiling interface and ImportProfiler
    _perf_probes.py          Low-level measurement and probing
    _perf_classifiers.py     Performance classification algorithms
    models.py                Core data structures and containers
    test_runner.py           Test discovery and execution system
    documentation.py         Module documentation generator
    case.py                  Case-insensitive module access
    fake_imports.py          Fake import system for mocking
    virtual_site_packages.py Virtual site-packages overlay
    dynamic_importer.py      Dynamic module loading system
    executor.py              Module execution analysis engine
        AttributeInfo        Attribute metadata container
        AttributeType        Attribute type enumeration
        CallResult           Function call result tracking
        CircularDependencyError  Circular import detection
        Execution            Module execution engine
        Fuzzing              Module fuzzing capabilities
        FunctionAnalysis     Function-level analysis
        HealthScoreCalculator Health scoring system
        ImportEvent          Import event data structure
        ImportEventType      Import event type enumeration
        ImportReport         Comprehensive import report
        ImportStatistics     Import statistics tracking
        ImportTracker        Real-time import monitor
        ModuleResult         Module execution result
        ModuleTraceResults   Module tracing results
        SeverityConfig       Severity configuration
        SeverityLevel        Severity level enumeration
        track_module         Module tracking function
        execute_module       Module execution function
    examples.py              Usage examples and utilities

Environment Variables
---------------------
IMPORT_PROFILER_LOG_LEVEL : Set logging level (DEBUG, INFO, WARNING, ERROR)
IMPORT_PROFILER_CACHE_DIR : Override cache directory location
IMPORT_PROFILER_DISABLE_CACHE : Disable all caching (set to '1')
IMPORT_PROFILER_CI_MODE : Enable CI-optimized thresholds (set to '1')

Notes
-----
- All profiling is performed in isolated subprocesses for accuracy
- Memory measurements use tracemalloc for precise tracking
- Thread-safe operations throughout for concurrent usage
- Cross-platform compatible (Windows, Linux, macOS)
- Python 3.8+ required for full functionality
"""

# -----------------------------------------------------------------------------
# Standard Library Imports
# -----------------------------------------------------------------------------

import sys
import os
import logging
import warnings
import functools
import threading
from datetime import datetime
from pathlib import Path
from typing import (
    Any, Dict, List, Optional, Tuple, Union, Callable, Type, Set,
    Iterator, Generator, overload, cast
)

# -----------------------------------------------------------------------------
# Package-Level Configuration
# -----------------------------------------------------------------------------

_logger = logging.getLogger(__name__)
_log_handler = logging.StreamHandler()
_log_handler.setFormatter(
    logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
)

_log_level = os.environ.get('IMPORT_PROFILER_LOG_LEVEL', 'WARNING').upper()
_logger.setLevel(getattr(logging, _log_level, logging.WARNING))

if not _logger.handlers:
    _logger.addHandler(_log_handler)

_CACHE_DIR = Path(
    os.environ.get(
        'IMPORT_PROFILER_CACHE_DIR',
        Path.home() / '.cache' / 'import_profiler'
    )
)
_CACHE_ENABLED = os.environ.get('IMPORT_PROFILER_DISABLE_CACHE', '0') != '1'
_CI_MODE = os.environ.get('IMPORT_PROFILER_CI_MODE', '0') == '1'

if _CACHE_ENABLED:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# Lazy Import System
# -----------------------------------------------------------------------------

_LAZY_IMPORTS: Dict[str, Any] = {}
_IMPORT_LOCK = threading.RLock()


def _lazy_import(module_name: str, attribute: str) -> Any:
    """
    Lazily import an attribute to minimize package import time.

    This internal helper defers heavy imports until they are actually needed,
    significantly reducing the package initialization overhead.

    Parameters
    ----------
    module_name : str
        The fully qualified module name to import from.
    attribute : str
        The specific attribute to retrieve from the module.

    Returns
    -------
    Any
        The imported attribute value.

    Raises
    ------
    ImportError
        If the module or attribute cannot be imported.
    """
    cache_key = f"{module_name}.{attribute}"

    with _IMPORT_LOCK:
        if cache_key not in _LAZY_IMPORTS:
            try:
                module = __import__(module_name, fromlist=[attribute])
                _LAZY_IMPORTS[cache_key] = getattr(module, attribute)
            except ImportError as e:
                _logger.warning(f"Failed to lazily import {cache_key}: {e}")
                raise

        return _LAZY_IMPORTS[cache_key]


# -----------------------------------------------------------------------------
# Public API - Performance Profiling
# -----------------------------------------------------------------------------

from .performance import (
    ImportProfiler,
    EnhancedImportProfile,
    ProfileComparator,
    RegressionDetector,
    ProfilingReport,
    profile_import,
    difftime,
    profile_batch,
    compare_versions,
    detect_regressions,
    export_profile,
    RegressionResult,
    ComparisonResult,
)

from ._perf_probes import (
    measure_import,
    measure_imports,
    run_memory_probe,
    run_dependency_probe,
    run_timed_import,
    collect_timing_samples,
    analyze_timing_data,
    calculate_stability_index,
    ProbeConfig,
    ProbeResult,
    ProbeSession,
    DetailedTimeResult,
    DetailedMemoryResult,
    DetailedDependencyResult,
    WarmupStrategy,
    MeasurementMode,
)

from ._perf_classifiers import (
    classify_time,
    classify_memory,
    classify_dependencies,
    classify_stability,
    PerformanceScore,
    ClassifiedModule,
    AdaptiveThresholds,
    Severity,
)

# -----------------------------------------------------------------------------
# Public API - Data Models
# -----------------------------------------------------------------------------

from .models import (
    TestResultData,
    TimeResult,
    MemoryResult,
    DependencyResult,
    StabilityResult,
    ImportProfile,
    ImportBenchmarkResult,
)

# -----------------------------------------------------------------------------
# Public API - Module Utilities
# -----------------------------------------------------------------------------

from .case import (
    patch_module,
    patch_modules,
    patch_pattern,
    patch_recursive,
    restore_module,
    restore_all_modules,
    is_patched,
    get_patch_stats,
    configure_patched_module,
    patch_context,
    with_case_insensitive,
    CaseInsensitiveModule,
    ModulePatcher,
    TypoSuggester,
)

from .fake_imports import (
    enable_fake_imports,
    disable_fake_imports,
    fake_imports_context,
    configure_fake_imports,
    register_fake_module,
    get_fake_import_stats,
    reset_fake_import_stats,
    is_fake_module,
    get_fake_modules,
    clear_fake_modules,
    create_fake_module,
    with_fake_imports,
    FakeModule,
    FakeLoader,
    FakeMetaPathFinder,
    FakeImportManager,
    FakeModuleConfig,
    FakeImportStats,
    FakeBehavior,
)

from .virtual_site_packages import (
    activate_virtual_site_packages,
    deactivate_virtual_site_packages,
    add_overlay_layer,
    remove_overlay_layer,
    list_active_overrides,
    list_overlay_layers,
    clear_overlay_cache,
    get_overlay_stats,
    export_overlay_config,
    import_overlay_config,
    virtual_site_packages_context,
    VirtualSitePackagesFinder,
    OverlayLayer,
    LayerManager,
    OverlayConfig,
    OverlayStats,
    ResolutionStrategy,
    OverlayType,
)

from .dynamic_importer import (
    enable_import_anywhere,
    scan_project_modules,
    import_from_path,
    reload_module,
    get_loader,
    get_import_stats,
    list_loaded_modules,
    clear_import_cache,
    ModuleLoader,
    ImportScanner,
    ConflictResolver,
    ModuleRegistry,
    ModuleMetadata,
    ImportConfig,
    ConflictStrategy,
    ImportConflictWarning,
    ImportConflictError,
)

# -----------------------------------------------------------------------------
# Public API - Test Infrastructure
# -----------------------------------------------------------------------------

from .test_runner import (
     TestRunner,
    find_tests,
    hastests,
    run_test_module,
    run_tests_with_pytest,
    run_tests_with_unittest,
    discover_test_classes,
    discover_test_functions,
    filter_tests_by_pattern,
    export_test_results,
    generate_coverage_report,
    TestDiscoveryEngine,
    TestDiscoveryConfig,
    TestExecutionConfig,
    TestFramework,
    TestCase,
    TestSuite,
    EnhancedTestResult as EnhancedTestRunResult,
    PYTEST_AVAILABLE,
    COVERAGE_AVAILABLE,
)

# -----------------------------------------------------------------------------
# Public API - Documentation Generator
# -----------------------------------------------------------------------------

from .documentation import (
    doc_module,
    module_examples,
    configure_documentation,
    clear_documentation_cache,
    get_cache_stats as get_documentation_cache_stats,
    export_doc,
    generate_api_docs,
    DocumentationConfig,
    ModuleDocumenter,
    DocumentationCache,
    SUPPORTED_FORMATS as DOCUMENTATION_FORMATS,
)

# -----------------------------------------------------------------------------
# Public API - Execution Analysis Engine
# -----------------------------------------------------------------------------

from .executor import (
    AttributeInfo,
    AttributeType,
    CallResult,
    CircularDependencyError,
    Execution,
    Fuzzing,
    FunctionAnalysis,
    HealthScoreCalculator,
    ImportEvent,
    ImportEventType,
    ImportReport,
    ImportStatistics,
    ImportTracker,
    ModuleResult,
    ModuleTraceResults,
    SeverityConfig,
    SeverityLevel,
    track_module,
    execute_module,
)

# -----------------------------------------------------------------------------
# Legacy Compatibility Aliases
# -----------------------------------------------------------------------------

from ._perf_probes import _measure_import, _run_import
from ._perf_classifiers import _classify

# -----------------------------------------------------------------------------
# Convenience Functions
# -----------------------------------------------------------------------------

_HELP_TOPICS = [
    'profiling', 'models', 'testing', 'documentation',
    'modules', 'classification', 'examples', 'configuration',
    'execution', 'tracking', 'health', 'fuzzing'
]


def help_package(topic: Optional[str] = None) -> None:
    """
    Display comprehensive help information about the package.

    This function provides interactive help for understanding and using
    the import profiler toolkit effectively.

    Parameters
    ----------
    topic : str, optional
        Specific topic to get help on:
        - 'profiling' : Import performance profiling
        - 'models' : Data models and structures
        - 'testing' : Test discovery and execution
        - 'documentation' : Documentation generation
        - 'modules' : Module manipulation utilities
        - 'classification' : Performance classification
        - 'execution' : Module execution analysis
        - 'tracking' : Import event tracking
        - 'health' : Health scoring system
        - 'fuzzing' : Module fuzzing capabilities
        - 'examples' : Usage examples
        - 'configuration' : Package configuration
        - None : General overview (default)

    Examples
    --------
    >>> from pyputil.test import help_package
    >>> help_package()
    >>> help_package('profiling')
    >>> help_package('examples')
    """
    help_texts = {
        None: f"""
{'='*70}
Python Import Profiler - Help
{'='*70}

General Overview
----------------
The Python Import Profiler provides comprehensive tools for analyzing
and optimizing Python module import performance.

Main Capabilities:
  1. Import Performance Profiling
  2. Module Utilities (case-insensitive, dynamic loading)
  3. Test Discovery and Execution
  4. Documentation Generation
  5. Performance Classification
  6. Execution Analysis and Fuzzing
  7. Import Event Tracking
  8. Health Score Calculation

Quick Start:
  >>> from pyputil.test import profile_import
  >>> profile = profile_import("numpy")
  >>> print(profile.time.average)

For specific help, use: help_package('topic')
Available topics: {', '.join(_HELP_TOPICS)}
""",

        'profiling': f"""
{'='*70}
Import Performance Profiling Help
{'='*70}

Core Functions:
  profile_import(module, repetitions=5, timeout=30.0)
      Profile a single module import.

  difftime(mod1, mod2, repetition=5)
      Compare import performance of two modules.

  profile_batch(modules, concurrent=True)
      Profile multiple modules concurrently.

  detect_regressions(baseline, modules)
      Detect performance regressions in CI/CD.

Key Classes:
  ImportProfiler - Main profiling engine
  EnhancedImportProfile - Comprehensive profile results
  RegressionDetector - Statistical regression detection
  ProbeConfig - Measurement configuration

Examples:
  >>> from pyputil.test import profile_import, ImportProfiler
  >>> profile = profile_import("requests", repetitions=10)
  >>> print(f"Import: {{profile.time.formatted_average}}")
  >>> profiler = ImportProfiler(default_repetitions=20, measurement_mode='precise')
  >>> profile = profiler.profile("numpy")
""",

        'models': f"""
{'='*70}
Data Models Help
{'='*70}

Core Data Structures:
  TimeResult - Timing statistics (average, min, max, stddev)
  MemoryResult - Memory usage (peak_kb, category)
  DependencyResult - Dependency count (loaded, category)
  StabilityResult - Import stability (index, category)
  ImportProfile - Complete import analysis
  TestResultData - Test execution results
  ImportBenchmarkResult - Legacy benchmark result

Examples:
  >>> from pyputil.test import TimeResult, MemoryResult
  >>> time = TimeResult(average=0.045, min_time=0.042, max_time=0.048, stddev=0.002, category="medium")
  >>> print(time.formatted_average)
  >>> memory = MemoryResult(peak_kb=2048, category="moderate")
  >>> print(memory.formatted_peak)
""",

        'testing': f"""
{'='*70}
Test Infrastructure Help
{'='*70}

Core Functions:
  find_tests(module_name, test_dir=None)
      Discover test files for a module.

  hastests(module_name)
      Check if module has tests.

  run_test_module(module_name, framework='auto')
      Run tests with specified framework.

  run_tests_with_pytest(test_paths)
      Run tests using pytest.

  run_tests_with_unittest(test_paths)
      Run tests using unittest.

Frameworks:
  - 'auto': Automatic detection
  - 'unittest': Python's built-in unittest
  - 'pytest': Pytest framework (requires pytest)

Output Formats:
  - 'json': JSON format
  - 'junit': JUnit XML (CI/CD compatible)
  - 'html': HTML report
  - 'tap': Test Anything Protocol

Examples:
  >>> from pyputil.test import run_test_module
  >>> result = run_test_module("my_package")
  >>> print(result.summary)
  >>> result = run_test_module("my_package", framework="pytest", coverage=True, output_format="junit", output_file="test-results.xml")
""",

        'documentation': f"""
{'='*70}
Documentation Generation Help
{'='*70}

Core Functions:
  doc_module(module, format='rst')
      Generate documentation for a module.

  module_examples(module, filter_by=None)
      Extract usage examples from module.

  export_doc(module, output_path)
      Generate and save documentation to file.

  generate_api_docs(package_name, output_dir)
      Generate documentation for entire package.

Output Formats:
  - 'rst': reStructuredText
  - 'markdown': Markdown
  - 'html': HTML
  - 'plain': Plain text
  - 'json': JSON (programmatic use)

Examples:
  >>> from pyputil.test import doc_module, export_doc
  >>> import math
  >>> docs = doc_module(math, format='markdown', include_toc=True)
  >>> export_doc(math, "math_docs.md")
""",

        'modules': f"""
{'='*70}
Module Utilities Help
{'='*70}

Case-Insensitive Access:
  patch_module(module)
      Enable case-insensitive attribute access.

  patch_modules(modules)
      Patch multiple modules.

  patch_context(module)
      Context manager for temporary patching.

  with_case_insensitive(modules)
      Decorator for function-level patching.

Fake Imports:
  enable_fake_imports()
      Enable fake import system globally.

  fake_imports_context()
      Context manager for temporary fake imports.

  with_fake_imports(modules)
      Decorator for function-level fake imports.

Dynamic Imports:
  enable_import_anywhere(base_path)
      Enable importing from anywhere in project.

  import_from_path(name, path)
      Import module from specific file path.

  reload_module(name)
      Reload a dynamically loaded module.

Virtual Site-Packages:
  activate_virtual_site_packages(path)
      Activate virtual overlay system.

  virtual_site_packages_context(path)
      Context manager for temporary overlay.

Examples:
  >>> from pyputil.test import patch_module
  >>> patch_module("requests")
  >>> import requests
  >>> response = requests.GeT("https://api.example.com")
  >>> from pyputil.test import enable_import_anywhere
  >>> enable_import_anywhere("/path/to/project")
  >>> import any_module_in_project
""",

        'classification': f"""
{'='*70}
Performance Classification Help
{'='*70}

Classification Functions:
  classify_time(avg_seconds)
      Classify import time: 'instant', 'light', 'medium', 'heavy', 'critical'

  classify_memory(peak_kb)
      Classify memory usage: 'light', 'moderate', 'heavy', 'critical'

  classify_dependencies(num_deps)
      Classify dependency count: 'minimal', 'moderate', 'heavy', 'explosive'

  classify_stability(index)
      Classify stability: 'stable', 'normal', 'unstable', 'chaotic'

Severity Levels:
  NEGLIGIBLE - No performance impact
  MINOR - Slight impact, generally acceptable
  MODERATE - Noticeable impact, consider optimization
  MAJOR - Significant impact, optimization recommended
  CRITICAL - Severe impact, immediate action needed

Examples:
  >>> from pyputil.test import classify_time, AdaptiveThresholds
  >>> category = classify_time(0.045)
  >>> print(category)
  >>> with AdaptiveThresholds(environment='ci'):
  ...     category = classify_time(0.015)
  ...     print(category)
""",

        'execution': f"""
{'='*70}
Execution Analysis Help
{'='*70}

Core Functions:
  execute_module(module_name, analysis_depth=2)
      Execute and analyze a module deeply.

  track_module(module_name)
      Track import events for a module.

Key Classes:
  Execution - Module execution engine
  FunctionAnalysis - Function-level analysis
  ModuleResult - Module execution result
  ModuleTraceResults - Module tracing results
  CallResult - Function call result tracking
  AttributeInfo - Attribute metadata container
  AttributeType - Attribute type enumeration

Examples:
  >>> from pyputil.test import execute_module, Execution
  >>> result = execute_module("my_module", analysis_depth=3)
  >>> print(f"Functions analyzed: {{len(result.functions)}}")
  >>> executor = Execution(analysis_depth=2, trace_calls=True)
  >>> result = executor.execute("my_module")
""",

        'tracking': f"""
{'='*70}
Import Event Tracking Help
{'='*70}

Core Classes:
  ImportTracker - Real-time import event monitor
  ImportEvent - Import event data structure
  ImportEventType - Import event type enumeration
  ImportStatistics - Import statistics tracking
  ImportReport - Comprehensive import report

Examples:
  >>> from pyputil.test import ImportTracker, track_module
  >>> tracker = ImportTracker()
  >>> tracker.start()
  >>> import numpy
  >>> events = tracker.stop()
  >>> print(f"Tracked {{len(events)}} import events")
  >>> result = track_module("pandas")
  >>> print(f"Import time: {{result.import_time}}")
""",

        'health': f"""
{'='*70}
Health Score Calculation Help
{'='*70}

Core Classes:
  HealthScoreCalculator - Health scoring system
  SeverityConfig - Severity configuration
  SeverityLevel - Severity level enumeration

Examples:
  >>> from pyputil.test import execute_module, HealthScoreCalculator
  >>> result = execute_module("my_module")
  >>> calculator = HealthScoreCalculator()
  >>> health = calculator.calculate(result)
  >>> print(f"Overall health: {{health.overall_score}}")
  >>> config = SeverityConfig(time_threshold=0.1, memory_threshold_mb=50)
  >>> calculator = HealthScoreCalculator(config)
""",

        'fuzzing': f"""
{'='*70}
Module Fuzzing Help
{'='*70}

Core Classes:
  Fuzzing - Module fuzzing engine
  CircularDependencyError - Circular import detection

Examples:
  >>> from pyputil.test import Fuzzing, CircularDependencyError
  >>> fuzzer = Fuzzing(iterations=100, timeout=5.0)
  >>> try:
  ...     results = fuzzer.fuzz_module("my_module")
  ...     print(f"Fuzzing complete: {{len(results)}} iterations")
  ... except CircularDependencyError as e:
  ...     print(f"Circular dependency detected: {{e}}")
""",

        'examples': f"""
{'='*70}
Usage Examples
{'='*70}

1. Basic Module Profiling:
   >>> from pyputil.test import profile_import
   >>> profile = profile_import("numpy", repetitions=10)
   >>> print(f"Average import: {{profile.time.formatted_average}}")

2. Comparing Modules:
   >>> from pyputil.test import difftime
   >>> n, p, c = difftime("numpy", "pandas")
   >>> print(f"Fastest: {{c.fastest.module}}")

3. CI/CD Regression Detection:
   >>> from pyputil.test import ImportProfiler
   >>> profiler = ImportProfiler()
   >>> baseline = profiler.profile("my_package")
   >>> current = profiler.profile("my_package")
   >>> result = profiler.detect_regression(baseline, current)

4. Generating Documentation:
   >>> from pyputil.test import doc_module
   >>> import my_module
   >>> docs = doc_module(my_module, format='markdown', include_toc=True)

5. Running Tests:
   >>> from pyputil.test import run_test_module
   >>> result = run_test_module("my_package", framework="pytest")

6. Case-Insensitive Imports:
   >>> from pyputil.test import patch_module
   >>> patch_module("json")
   >>> import json
   >>> json.LOADS('{{"key": "value"}}')

7. Dynamic Module Loading:
   >>> from pyputil.test import enable_import_anywhere
   >>> loader = enable_import_anywhere("/path/to/project")

8. Import Event Tracking:
   >>> from pyputil.test import ImportTracker
   >>> tracker = ImportTracker()
   >>> tracker.start()
   >>> import numpy
   >>> events = tracker.stop()

9. Module Health Check:
   >>> from pyputil.test import execute_module, HealthScoreCalculator
   >>> result = execute_module("my_module")
   >>> health = HealthScoreCalculator().calculate(result)

10. Module Fuzzing:
    >>> from pyputil.test import Fuzzing
    >>> fuzzer = Fuzzing(iterations=50)
    >>> results = fuzzer.fuzz_module("my_module")
""",

        'configuration': f"""
{'='*70}
Configuration Help
{'='*70}

Environment Variables:
  IMPORT_PROFILER_LOG_LEVEL
      Set logging level (DEBUG, INFO, WARNING, ERROR)
      Default: WARNING

  IMPORT_PROFILER_CACHE_DIR
      Override cache directory location
      Default: ~/.cache/import_profiler

  IMPORT_PROFILER_DISABLE_CACHE
      Disable all caching (set to '1')
      Default: '0' (caching enabled)

  IMPORT_PROFILER_CI_MODE
      Enable CI-optimized thresholds (set to '1')
      Default: '0' (standard thresholds)

Runtime Configuration:
  >>> from pyputil.test import configure_documentation
  >>> configure_documentation(format='markdown', include_private=False, enable_caching=True)

Current Configuration:
  Cache enabled: {_CACHE_ENABLED}
  Cache directory: {_CACHE_DIR}
  CI mode: {_CI_MODE}
  Log level: {_log_level}
""",
    }

    if topic not in help_texts:
        print(f"Unknown topic: '{topic}'\n")
        print(f"Available topics: {', '.join(_HELP_TOPICS)}")
        print("Use help_package() for general overview.")
        return

    print(help_texts[topic])


def help_package(topic: Optional[str] = None, as_text: Optional[bool] = False) -> Optional[str]:
    """
    Display comprehensive help information about the package.

    This function provides interactive help for understanding and using
    the import profiler toolkit effectively.

    Parameters
    ----------
    topic : str, optional
        Specific topic to get help on. Available topics:
        'profiling', 'models', 'testing', 'documentation',
        'modules', 'classification', 'execution', 'tracking',
        'health', 'fuzzing', 'examples', 'configuration'.
        If None, displays general overview.
    as_text : bool, optional
         If True, The topic will be returned as
         usable text; otherwise, None 

    Examples
    --------
    >>> from pyputil.test import help_package
    >>> help_package()
    >>> help_package('profiling')
    >>> help_package('examples')
    """
    help_texts = {
        None: f"""
{'='*70}
Python Import Profiler - Help
{'='*70}

General Overview
----------------
The Python Import Profiler provides comprehensive tools for analyzing
and optimizing Python module import performance.

Main Capabilities:
  1. Import Performance Profiling
  2. Module Utilities (case-insensitive, dynamic loading)
  3. Test Discovery and Execution
  4. Documentation Generation
  5. Performance Classification
  6. Execution Analysis and Fuzzing
  7. Import Event Tracking
  8. Health Score Calculation

Quick Start:
  >>> from pyputil.test import profile_import
  >>> profile = profile_import("numpy")
  >>> print(profile.time.average)

For specific help, use: help_package('topic')
Available topics: {', '.join(_HELP_TOPICS)}
""",

        'profiling': f"""
{'='*70}
Import Performance Profiling Help
{'='*70}

Core Functions:
  profile_import(module, repetitions=5, timeout=30.0)
      Profile a single module import.

  difftime(mod1, mod2, repetition=5)
      Compare import performance of two modules.

  profile_batch(modules, concurrent=True)
      Profile multiple modules concurrently.

  detect_regressions(baseline, modules)
      Detect performance regressions in CI/CD.

Key Classes:
  ImportProfiler - Main profiling engine
  EnhancedImportProfile - Comprehensive profile results
  RegressionDetector - Statistical regression detection
  ProbeConfig - Measurement configuration
  WarmupStrategy - Cache warming strategies
  MeasurementMode - Precision vs speed trade-offs

Examples:
  >>> from pyputil.test import profile_import, ImportProfiler
  >>> profile = profile_import("requests", repetitions=10)
  >>> print(f"Import: {{profile.time.formatted_average}}")
  >>> profiler = ImportProfiler(default_repetitions=20, measurement_mode='precise')
  >>> profile = profiler.profile("numpy")
  >>> from pyputil.test import difftime
  >>> numpy, pandas, comparison = difftime("numpy", "pandas")
  >>> print(comparison.summary)
""",

        'models': f"""
{'='*70}
Data Models Help
{'='*70}

Core Data Structures:
  TimeResult - Timing statistics (average, min, max, stddev)
      Properties: formatted_average, coefficient_of_variation, is_stable

  MemoryResult - Memory usage (peak_kb, category)
      Properties: peak_mb, peak_bytes, formatted_peak, is_lightweight

  DependencyResult - Dependency count (loaded, category)
      Properties: complexity_score, is_minimal, is_explosive

  StabilityResult - Import stability (index, category)
      Properties: stability_percentage, reliability_score, is_stable

  ImportProfile - Complete import analysis
      Properties: overall_score, severity, summary, is_problematic

  TestResultData - Test execution results
      Properties: passed, pass_rate, summary, status_emoji

  ImportBenchmarkResult - Legacy benchmark result
      Method: to_time_result() for modern conversion

Examples:
  >>> from pyputil.test import TimeResult, MemoryResult
  >>> time = TimeResult(average=0.045, min_time=0.042, max_time=0.048, stddev=0.002, category="medium")
  >>> print(time.formatted_average)
  >>> print(f"Stability: {{time.coefficient_of_variation:.3f}}")
  >>> memory = MemoryResult(peak_kb=2048, category="moderate")
  >>> print(memory.formatted_peak)
  >>> print(f"Lightweight: {{memory.is_lightweight}}")
""",

        'testing': f"""
{'='*70}
Test Infrastructure Help
{'='*70}

Core Functions:
  find_tests(module_name, test_dir=None)
      Discover test files for a module.

  hastests(module_name)
      Check if module has tests.

  run_test_module(module_name, framework='auto', verbosity=2, failfast=False, buffer=True)
      Run tests with specified framework.

  run_tests_with_pytest(test_paths, verbosity=2)
      Run tests using pytest.

  run_tests_with_unittest(test_paths, verbosity=2)
      Run tests using unittest.

  discover_test_classes(test_file)
      Discover test classes in a test file.

  discover_test_functions(test_file)
      Discover test functions/methods in a test file.

  filter_tests_by_pattern(test_files, pattern)
      Filter test files by pattern.

  export_test_results(result, format, output_file)
      Export test results to various formats.

  generate_coverage_report(test_module, output_dir)
      Generate test coverage report.

Frameworks:
  - 'auto': Automatic detection
  - 'unittest': Python's built-in unittest
  - 'pytest': Pytest framework (requires pytest)

Output Formats:
  - 'json': JSON format
  - 'junit': JUnit XML (CI/CD compatible)
  - 'html': HTML report
  - 'tap': Test Anything Protocol
  - 'text': Plain text

Examples:
  >>> from pyputil.test import run_test_module, find_tests, hastests
  >>> if hastests("my_package"):
  ...     tests = find_tests("my_package")
  ...     print(f"Found {{len(tests)}} test files")
  >>> result = run_test_module("my_package")
  >>> print(result.summary)
  >>> result = run_test_module("my_package", framework="pytest", coverage=True, output_format="junit", output_file="test-results.xml")
  >>> from pyputil.test import export_test_results
  >>> export_test_results(result, "json", "results.json")
""",

        'documentation': f"""
{'='*70}
Documentation Generation Help
{'='*70}

Core Functions:
  doc_module(module, format='rst', include_private=False, include_examples=True, 
             max_example_length=500, section_order=None, title_level=1,
             group_private=False, filter_by=None, include_magic_methods=False,
             include_inherited=True, include_source_links=False,
             source_url_template=None, include_toc=False, show_bases=True,
             show_mro=False, verbose=False)
      Generate documentation for a module.

  module_examples(module, filter_by=None, extractor=None, skip_private=True,
                  max_examples=None, include_signatures=True)
      Extract usage examples from module.

  export_doc(module, output_path, format=None)
      Generate and save documentation to file.

  generate_api_docs(package_name, output_dir, format='markdown', recursive=True)
      Generate documentation for entire package.

  configure_documentation(format=None, include_private=None, include_examples=None,
                         max_example_length=None, enable_caching=None, cache_size=None,
                         verbose=None)
      Configure global documentation settings.

  clear_documentation_cache()
      Clear the documentation cache.

  get_documentation_cache_stats()
      Get documentation cache statistics.

Output Formats:
  - 'rst': reStructuredText
  - 'markdown': Markdown
  - 'html': HTML
  - 'plain': Plain text
  - 'json': JSON (programmatic use)

Examples:
  >>> from pyputil.test import doc_module, export_doc
  >>> import math
  >>> docs = doc_module(math, format='markdown', include_toc=True)
  >>> export_doc(math, "math_docs.md")
  >>> from pyputil.test import generate_api_docs
  >>> files = generate_api_docs("my_package", "./docs/api")
  >>> print(f"Generated {{len(files)}} documentation files")
""",

        'modules': f"""
{'='*70}
Module Utilities Help
{'='*70}

Case-Insensitive Access:
  patch_module(module, lazy=True, enable_cache=True, enable_suggestions=True, 
               enable_stats=True, fuzzy_cutoff=0.6, max_suggestions=3, 
               case_sensitive_fallback=True)
      Enable case-insensitive attribute access with typo suggestions.

  patch_modules(modules)
      Patch multiple modules.

  patch_pattern(pattern, include_builtins=False)
      Patch all modules matching a pattern.

  patch_recursive(module, max_depth=3)
      Recursively patch module and submodules.

  restore_module(module)
      Restore a patched module to original state.

  restore_all_modules()
      Restore all patched modules.

  is_patched(module)
      Check if a module has been patched.

  get_patch_stats(module=None)
      Get statistics for patched modules.

  configure_patched_module(module)
      Configure an already patched module.

  patch_context(module, recursive=False)
      Context manager for temporary patching.

  with_case_insensitive(modules)
      Decorator for function-level patching.

Fake Imports:
  enable_fake_imports(config=None, allow_patterns=None, block_patterns=None, 
                     allow_all=True, log_level=30)
      Enable fake import system globally.

  disable_fake_imports()
      Disable and restore original import behavior.

  fake_imports_context(config=None, allow_patterns=None, block_patterns=None, 
                      allow_all=True)
      Context manager for temporary fake imports.

  configure_fake_imports(module_configs=None, pattern_configs=None, 
                        protected_modules=None)
      Configure fake import system behavior.

  register_fake_module(module_name, config=None)
      Register a custom fake module implementation.

  get_fake_import_stats()
      Retrieve statistics about faked imports.

  reset_fake_import_stats()
      Reset all fake import statistics.

  is_fake_module(module)
      Check if an object is a fake module.

  get_fake_modules()
      Get list of all currently loaded fake modules.

  clear_fake_modules()
      Remove all fake modules from sys.modules.

  create_fake_module(name, config=None)
      Create a standalone fake module.

  with_fake_imports(modules=None)
      Decorator for function-level fake imports.

Dynamic Imports:
  enable_import_anywhere(base_path=None, warn=True, verbose=False, 
                        exclude_patterns=None, include_init=False,
                        recursive=True, conflict_strategy='alias',
                        strict_mode=False, track_dependencies=False)
      Enable importing modules from anywhere in a project.

  scan_project_modules(base_path, exclude_patterns=None, include_init=False, 
                      verbose=False)
      Scan a project directory for Python modules.

  import_from_path(module_name, file_path, verbose=False)
      Import module from specific file path.

  reload_module(module_name)
      Reload a dynamically loaded module.

  get_loader()
      Get the global module loader instance.

  get_import_stats()
      Get statistics about the dynamic import system.

  list_loaded_modules()
      Get list of all dynamically loaded modules.

  clear_import_cache()
      Clear the module registry and cache.

Virtual Site-Packages:
  activate_virtual_site_packages(path='virtual_sp/overlay', preserve_system=True,
                                enable_logging=False, insert_at_front=True,
                                strategy='overlay_first')
      Activate the virtual site-packages overlay system.

  deactivate_virtual_site_packages(finder)
      Deactivate and remove a specific finder.

  add_overlay_layer(finder, name, path, priority=None)
      Add a new overlay layer.

  remove_overlay_layer(finder, name)
      Remove an overlay layer.

  list_active_overrides()
      List all active VirtualSitePackagesFinder instances.

  list_overlay_layers(finder=None)
      List overlay layers for a finder.

  clear_overlay_cache(finder=None)
      Clear overlay resolution cache.

  get_overlay_stats(finder=None)
      Get overlay system statistics.

  export_overlay_config(finder, filepath)
      Export overlay configuration to file.

  import_overlay_config(filepath, activate=True)
      Import overlay configuration from file.

  virtual_site_packages_context(path='virtual_sp/overlay')
      Context manager for temporary overlay activation.

Examples:
  >>> from pyputil.test import patch_module
  >>> patch_module("requests")
  >>> import requests
  >>> response = requests.GeT("https://api.example.com")
  >>> from pyputil.test import enable_import_anywhere
  >>> loader = enable_import_anywhere("/path/to/project")
  >>> print(f"Loaded {{loader.loaded_count}} modules")
  >>> from pyputil.test import fake_imports_context
  >>> with fake_imports_context():
  ...     import missing_module
  ...     missing_module.any_function()
  >>> from pyputil.test import activate_virtual_site_packages
  >>> finder = activate_virtual_site_packages("/path/to/overlay")
""",

        'classification': f"""
{'='*70}
Performance Classification Help
{'='*70}

Classification Functions:
  classify_time(avg_seconds)
      Classify import time: 'instant', 'light', 'medium', 'heavy', 'critical'

  classify_memory(peak_kb)
      Classify memory usage: 'light', 'moderate', 'heavy', 'critical'

  classify_dependencies(num_deps)
      Classify dependency count: 'minimal', 'moderate', 'heavy', 'explosive'

  classify_stability(index)
      Classify stability: 'stable', 'normal', 'unstable', 'chaotic'

Severity Levels:
  NEGLIGIBLE (0) - No performance impact
  MINOR (1) - Slight impact, generally acceptable
  MODERATE (2) - Noticeable impact, consider optimization
  MAJOR (3) - Significant impact, optimization recommended
  CRITICAL (4) - Severe impact, immediate action needed

Adaptive Thresholds:
  AdaptiveThresholds(environment=None, multiplier=1.0, custom_thresholds=None)
      Context manager for runtime threshold adaptation.
      - environment: 'ci', 'production', 'development'
      - multiplier: Global multiplier applied to all thresholds

Performance Score:
  PerformanceScore(total, time_score, memory_score, dependency_score, 
                   stability_score, confidence)
      Weighted composite score from 0.0 (optimal) to 1.0 (critical).

Examples:
  >>> from pyputil.test import classify_time, AdaptiveThresholds, Severity
  >>> category = classify_time(0.045)
  >>> print(f"Category: {{category}}")
  >>> severity = Severity.MODERATE
  >>> print(f"Severity value: {{severity.value}}")
  >>> with AdaptiveThresholds(environment='ci'):
  ...     category = classify_time(0.015)
  ...     print(f"CI category: {{category}}")
""",

        'execution': f"""
{'='*70}
Execution Analysis Help
{'='*70}

Core Functions:
  execute_module(module_name, analysis_depth=2, trace_calls=False, 
                capture_output=True, timeout=30.0)
      Execute and analyze a module deeply.

  track_module(module_name, track_memory=True, track_time=True, 
              track_dependencies=True)
      Track import events for a module.

Key Classes:
  Execution(analysis_depth=2, trace_calls=False, capture_output=True, 
           timeout=30.0)
      Module execution engine.

  FunctionAnalysis(name, signature, docstring, complexity, call_count, 
                  execution_time, dependencies)
      Function-level analysis results.

  ModuleResult(module_name, functions, classes, variables, import_time, 
              memory_usage, dependency_count, errors)
      Module execution result.

  ModuleTraceResults(module_name, trace_events, execution_tree, timing_data)
      Module tracing results.

  CallResult(function_name, args, kwargs, return_value, execution_time, 
            exception)
      Function call result tracking.

  AttributeInfo(name, type, value, is_callable, is_private, docstring)
      Attribute metadata container.

  AttributeType(MODULE, CLASS, FUNCTION, METHOD, PROPERTY, VARIABLE, 
               CONSTANT, DESCRIPTOR)
      Attribute type enumeration.

Examples:
  >>> from pyputil.test import execute_module, Execution
  >>> result = execute_module("my_module", analysis_depth=3)
  >>> print(f"Functions analyzed: {{len(result.functions)}}")
  >>> print(f"Classes found: {{len(result.classes)}}")
  >>> executor = Execution(analysis_depth=2, trace_calls=True)
  >>> result = executor.execute("my_module")
  >>> for func in result.functions:
  ...     print(f"  {{func.name}}: complexity={{func.complexity}}")
""",

        'tracking': f"""
{'='*70}
Import Event Tracking Help
{'='*70}

Core Classes:
  ImportTracker
      Real-time import event monitor.
      Methods: start(), stop(), pause(), resume(), get_events(), clear()

  ImportEvent(module_name, event_type, timestamp, duration, details)
      Import event data structure.

  ImportEventType
      Import event type enumeration.
      Values: IMPORT_START, IMPORT_COMPLETE, IMPORT_ERROR, SUBMODULE_LOADED,
              DEPENDENCY_RESOLVED, CACHE_HIT, CACHE_MISS

  ImportStatistics(total_imports, total_time, avg_time, error_count, 
                  cache_hit_rate, most_expensive, dependency_graph)
      Import statistics tracking.

  ImportReport(module_name, events, statistics, recommendations, 
              generated_at)
      Comprehensive import report.

Examples:
  >>> from pyputil.test import ImportTracker, track_module
  >>> tracker = ImportTracker()
  >>> tracker.start()
  >>> import numpy
  >>> import pandas
  >>> events = tracker.stop()
  >>> print(f"Tracked {{len(events)}} import events")
  >>> for event in events:
  ...     print(f"  {{event.module_name}}: {{event.event_type.name}} ({{event.duration:.3f}}s)")
  >>> result = track_module("pandas")
  >>> print(f"Import time: {{result.import_time:.3f}}s")
  >>> print(f"Dependencies: {{result.dependency_count}}")
""",

        'health': f"""
{'='*70}
Health Score Calculation Help
{'='*70}

Core Classes:
  HealthScoreCalculator(config=None)
      Health scoring system.
      Methods: calculate(module_result), calculate_batch(module_results)

  SeverityConfig(time_threshold=1.0, memory_threshold_mb=100, 
                deps_threshold=200, complexity_threshold=10, 
                error_penalty=10)
      Severity configuration for health scoring.

  SeverityLevel
      Severity level enumeration.
      Values: HEALTHY, MINOR_ISSUES, MODERATE_ISSUES, MAJOR_ISSUES, CRITICAL

Examples:
  >>> from pyputil.test import execute_module, HealthScoreCalculator, SeverityConfig
  >>> result = execute_module("my_module")
  >>> calculator = HealthScoreCalculator()
  >>> health = calculator.calculate(result)
  >>> print(f"Overall health: {{health.overall_score:.2f}}")
  >>> print(f"Severity: {{health.severity.name}}")
  >>> print(f"Recommendations: {{health.recommendations}}")
  >>> config = SeverityConfig(time_threshold=0.1, memory_threshold_mb=50)
  >>> calculator = HealthScoreCalculator(config)
  >>> health = calculator.calculate(result)
""",

        'fuzzing': f"""
{'='*70}
Module Fuzzing Help
{'='*70}

Core Classes:
  Fuzzing(iterations=100, timeout=5.0, random_seed=None, 
         fuzz_functions=True, fuzz_classes=True, fuzz_methods=True,
         capture_errors=True)
      Module fuzzing engine.
      Methods: fuzz_module(module_name), fuzz_function(function), 
               fuzz_class(klass)

  CircularDependencyError(module_name, dependency_chain)
      Circular import detection error.
      Properties: module_name, dependency_chain, cycle_length

Examples:
  >>> from pyputil.test import Fuzzing, CircularDependencyError
  >>> fuzzer = Fuzzing(iterations=100, timeout=5.0)
  >>> try:
  ...     results = fuzzer.fuzz_module("my_module")
  ...     print(f"Fuzzing complete: {{len(results)}} iterations")
  ...     print(f"Errors found: {{sum(1 for r in results if r.error)}}")
  ... except CircularDependencyError as e:
  ...     print(f"Circular dependency detected: {{e}}")
  ...     print(f"Dependency chain: {{' -> '.join(e.dependency_chain)}}")
  >>> fuzzer = Fuzzing(iterations=50, fuzz_functions=True, fuzz_classes=False)
  >>> results = fuzzer.fuzz_module("my_module")
""",

        'examples': f"""
{'='*70}
Usage Examples
{'='*70}

1. Basic Module Profiling:
   >>> from pyputil.test import profile_import
   >>> profile = profile_import("numpy", repetitions=10)
   >>> print(f"Average import: {{profile.time.formatted_average}}")

2. Comparing Modules:
   >>> from pyputil.test import difftime
   >>> n, p, c = difftime("numpy", "pandas")
   >>> print(f"Fastest: {{c.fastest.module}}")

3. CI/CD Regression Detection:
   >>> from pyputil.test import ImportProfiler
   >>> profiler = ImportProfiler()
   >>> baseline = profiler.profile("my_package")
   >>> current = profiler.profile("my_package")
   >>> result = profiler.detect_regression(baseline, current)

4. Generating Documentation:
   >>> from pyputil.test import doc_module
   >>> import my_module
   >>> docs = doc_module(my_module, format='markdown', include_toc=True)

5. Running Tests:
   >>> from pyputil.test import run_test_module
   >>> result = run_test_module("my_package", framework="pytest")

6. Case-Insensitive Imports:
   >>> from pyputil.test import patch_module
   >>> patch_module("json")
   >>> import json
   >>> json.LOADS('{{"key": "value"}}')

7. Dynamic Module Loading:
   >>> from pyputil.test import enable_import_anywhere
   >>> loader = enable_import_anywhere("/path/to/project")

8. Import Event Tracking:
   >>> from pyputil.test import ImportTracker
   >>> tracker = ImportTracker()
   >>> tracker.start()
   >>> import numpy
   >>> events = tracker.stop()

9. Module Health Check:
   >>> from pyputil.test import execute_module, HealthScoreCalculator
   >>> result = execute_module("my_module")
   >>> health = HealthScoreCalculator().calculate(result)

10. Module Fuzzing:
    >>> from pyputil.test import Fuzzing
    >>> fuzzer = Fuzzing(iterations=50)
    >>> results = fuzzer.fuzz_module("my_module")
""",

        'configuration': f"""
{'='*70}
Configuration Help
{'='*70}

Environment Variables:
  IMPORT_PROFILER_LOG_LEVEL
      Set logging level (DEBUG, INFO, WARNING, ERROR)
      Default: WARNING

  IMPORT_PROFILER_CACHE_DIR
      Override cache directory location
      Default: ~/.cache/import_profiler

  IMPORT_PROFILER_DISABLE_CACHE
      Disable all caching (set to '1')
      Default: '0' (caching enabled)

  IMPORT_PROFILER_CI_MODE
      Enable CI-optimized thresholds (set to '1')
      Default: '0' (standard thresholds)

Runtime Configuration:
  >>> from pyputil.test import configure_documentation
  >>> configure_documentation(format='markdown', include_private=False, enable_caching=True)

Current Configuration:
  Cache enabled: {_CACHE_ENABLED}
  Cache directory: {_CACHE_DIR}
  CI mode: {_CI_MODE}
  Log level: {_log_level}
""",
    }
    unknown_topic_lines: List[str] = [
         f"Unknown topic: '{topic}'\n",
         f"Available topics: {', '.join(_HELP_TOPICS)}",
         "Use help_package() for general overview."
    ]

    if topic not in help_texts:
        if as_text:
             return "\n".join(unknown_topic_lines)
        print("\n".join(unknown_topic_lines))
        return

    if as_text:
        return help_texts[topic]
    print(help_texts[topic])


# -----------------------------------------------------------------------------
# Package Initialization
# -----------------------------------------------------------------------------

def _initialize_package() -> None:
    """
    Initialize the package on import.

    This function performs startup checks and configuration
    when the package is first imported. It configures logging,
    validates the environment, and sets up CI-specific optimizations.

    Notes
    -----
    Called automatically when the package is imported. Does not
    need to be invoked manually.
    """
    _logger.debug(f"Initializing pyputil.test")

    if _CI_MODE:
        _logger.info("CI mode enabled - using stricter performance thresholds")

    if not _CACHE_ENABLED:
        _logger.info("Caching disabled via environment variable")

    if _CI_MODE:
        warnings.filterwarnings('ignore', category=DeprecationWarning)

    _logger.debug(f"Package initialized successfully")


# Run initialization
_initialize_package()


# -----------------------------------------------------------------------------
# Package Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Performance Profiling
    'ImportProfiler',
    'EnhancedImportProfile',
    'ProfileComparator',
    'RegressionDetector',
    'ProfilingReport',
    'ProbeConfig',
    'ProbeResult',
    'ProbeSession',
    'DetailedTimeResult',
    'DetailedMemoryResult',
    'DetailedDependencyResult',
    'WarmupStrategy',
    'MeasurementMode',
    'RegressionResult',
    'ComparisonResult',
    'profile_import',
    'difftime',
    'profile_batch',
    'compare_versions',
    'detect_regressions',
    'export_profile',
    'measure_import',
    'measure_imports',
    'run_memory_probe',
    'run_dependency_probe',
    'run_timed_import',
    'collect_timing_samples',
    'analyze_timing_data',
    'calculate_stability_index',

    # Performance Classification
    'classify_time',
    'classify_memory',
    'classify_dependencies',
    'classify_stability',
    'PerformanceScore',
    'ClassifiedModule',
    'AdaptiveThresholds',
    'Severity',

    # Data Models
    'TestResultData',
    'TimeResult',
    'MemoryResult',
    'DependencyResult',
    'StabilityResult',
    'ImportProfile',
    'ImportBenchmarkResult',

    # Module Utilities - Case Insensitive
    'patch_module',
    'patch_modules',
    'patch_pattern',
    'patch_recursive',
    'restore_module',
    'restore_all_modules',
    'is_patched',
    'get_patch_stats',
    'configure_patched_module',
    'patch_context',
    'with_case_insensitive',
    'CaseInsensitiveModule',
    'ModulePatcher',
    'TypoSuggester',

    # Module Utilities - Fake Imports
    'enable_fake_imports',
    'disable_fake_imports',
    'fake_imports_context',
    'configure_fake_imports',
    'register_fake_module',
    'get_fake_import_stats',
    'reset_fake_import_stats',
    'is_fake_module',
    'get_fake_modules',
    'clear_fake_modules',
    'create_fake_module',
    'with_fake_imports',
    'FakeModule',
    'FakeLoader',
    'FakeMetaPathFinder',
    'FakeImportManager',
    'FakeModuleConfig',
    'FakeImportStats',
    'FakeBehavior',

    # Module Utilities - Virtual Site-Packages
    'activate_virtual_site_packages',
    'deactivate_virtual_site_packages',
    'add_overlay_layer',
    'remove_overlay_layer',
    'list_active_overrides',
    'list_overlay_layers',
    'clear_overlay_cache',
    'get_overlay_stats',
    'export_overlay_config',
    'import_overlay_config',
    'virtual_site_packages_context',
    'VirtualSitePackagesFinder',
    'OverlayLayer',
    'LayerManager',
    'OverlayConfig',
    'OverlayStats',
    'ResolutionStrategy',
    'OverlayType',

    # Module Utilities - Dynamic Imports
    'enable_import_anywhere',
    'scan_project_modules',
    'import_from_path',
    'reload_module',
    'get_loader',
    'get_import_stats',
    'list_loaded_modules',
    'clear_import_cache',
    'ModuleLoader',
    'ImportScanner',
    'ConflictResolver',
    'ModuleRegistry',
    'ModuleMetadata',
    'ImportConfig',
    'ConflictStrategy',
    'ImportConflictWarning',
    'ImportConflictError',

    # Test Infrastructure
    'TestRunner',
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
    'TestDiscoveryEngine',
    'TestDiscoveryConfig',
    'TestExecutionConfig',
    'TestFramework',
    'TestCase',
    'TestSuite',
    'EnhancedTestRunResult',
    'PYTEST_AVAILABLE',
    'COVERAGE_AVAILABLE',

    # Documentation Generator
    'doc_module',
    'module_examples',
    'configure_documentation',
    'clear_documentation_cache',
    'get_documentation_cache_stats',
    'export_doc',
    'generate_api_docs',
    'DocumentationConfig',
    'ModuleDocumenter',
    'DocumentationCache',
    'DOCUMENTATION_FORMATS',

    # Execution Analysis Engine
    'AttributeInfo',
    'AttributeType',
    'CallResult',
    'CircularDependencyError',
    'Execution',
    'Fuzzing',
    'FunctionAnalysis',
    'HealthScoreCalculator',
    'ImportEvent',
    'ImportEventType',
    'ImportReport',
    'ImportStatistics',
    'ImportTracker',
    'ModuleResult',
    'ModuleTraceResults',
    'SeverityConfig',
    'SeverityLevel',
    'track_module',
    'execute_module',

    # Utility Functions
    'help_package',
]


# -----------------------------------------------------------------------------
# Clean up namespace
# -----------------------------------------------------------------------------

def __dir__() -> List[str]:
    """
    Return public API for interactive use.

    This method is called by dir() on the module, returning only
    the public API elements listed in __all__.

    Returns
    -------
    List[str]
        Sorted list of public API names.
    """
    return sorted(__all__)
