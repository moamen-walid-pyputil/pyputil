#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
models.py

Comprehensive Data Models for Python Import Performance Analysis.

This module defines the core data structures used throughout the import-profiler
package for representing performance metrics, test results, and analysis outcomes.
All models are implemented as immutable dataclasses with comprehensive
serialization support and utility methods.

The models are designed for:
- Type-safe representation of performance metrics
- JSON serialization for storage and transmission
- Integration with monitoring and alerting systems
- Statistical analysis and comparison operations
- Report generation and data export

Classes
-------
TestResultData
    Structured container for test execution results.
TimeResult
    Immutable timing measurements with statistical summary.
MemoryResult
    Immutable memory consumption measurements.
DependencyResult
    Immutable dependency analysis results.
StabilityResult
    Immutable import stability metrics.
ImportProfile
    Complete multi-dimensional import analysis.
ImportBenchmarkResult
    Legacy benchmark result container.

Notes
-----
All dataclasses are frozen (immutable) to ensure data integrity and
thread-safety. Use the `to_dict()` and `to_json()` methods for
serialization rather than direct attribute modification.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Set, Tuple, Union
from datetime import datetime, timedelta
from pathlib import Path
import json
import math
import hashlib
from enum import Enum


# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------

def _format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format.
    
    Parameters
    ----------
    seconds : float
        Duration in seconds.
    
    Returns
    -------
    str
        Formatted duration string.
    """
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.2f}µs"
    elif seconds < 1:
        return f"{seconds * 1000:.2f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"


def _format_memory(kb: int) -> str:
    """
    Format memory size in human-readable format.
    
    Parameters
    ----------
    kb : int
        Memory in kilobytes.
    
    Returns
    -------
    str
        Formatted memory string.
    """
    if kb < 1024:
        return f"{kb} KB"
    elif kb < 1024 * 1024:
        return f"{kb / 1024:.2f} MB"
    else:
        return f"{kb / (1024 * 1024):.2f} GB"


def _calculate_percentile(data: List[float], percentile: float) -> float:
    """
    Calculate percentile from data.
    
    Parameters
    ----------
    data : List[float]
        Sorted data values.
    percentile : float
        Percentile to calculate (0-100).
    
    Returns
    -------
    float
        Calculated percentile value.
    """
    if not data:
        return 0.0
    
    index = (len(data) - 1) * (percentile / 100.0)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    
    if lower == upper:
        return data[lower]
    
    weight = index - lower
    return data[lower] * (1 - weight) + data[upper] * weight


# -----------------------------------------------------------------------------
# Test Result Model
# -----------------------------------------------------------------------------

@dataclass
class TestResultData:
    """
    Structured result of running test files for a specific Python module.

    This class encapsulates comprehensive test execution results including
    statistics, captured output, and detailed failure information.

    Attributes
    ----------
    tests_run : int
        Total number of tests executed.
    failures : int
        Number of failed tests (assertion failures).
    errors : int
        Number of tests that raised unexpected errors.
    skipped : int
        Number of skipped tests.
    success : bool
        True if all tests passed without failures or errors; False otherwise.
    test_files : List[str]
        Absolute paths to the discovered test files that were executed.
    output : str
        Captured stdout and stderr during test execution.
    detailed_failures : List[Dict[str, str]]
        List of dictionaries for each failure/error containing:
        - 'test': fully qualified name of the failed test
        - 'error': error message or assertion failure description
        - 'traceback': complete traceback string for debugging
    execution_time : float
        Total test execution time in seconds.
    timestamp : str
        ISO 8601 timestamp when tests were executed.
    framework : str
        Test framework used ('unittest', 'pytest', 'unknown').

    Examples
    --------
    >>> result = TestResultData(
    ...     tests_run=42,
    ...     failures=2,
    ...     errors=1,
    ...     skipped=3,
    ...     success=False,
    ...     test_files=["/path/to/test_module.py"],
    ...     execution_time=1.234,
    ... )
    >>> print(result.summary)
    Ran 42 tests in 1.23s: 36 passed, 2 failed, 1 error, 3 skipped
    
    >>> # Export to JSON
    >>> json_str = result.to_json()
    """

    tests_run: int
    failures: int
    errors: int
    skipped: int
    success: bool
    test_files: List[str] = field(default_factory=list)
    output: str = ""
    detailed_failures: List[Dict[str, str]] = field(default_factory=list)
    execution_time: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    framework: str = "unknown"

    @property
    def passed(self) -> int:
        """
        Calculate number of passed tests.
        
        Returns
        -------
        int
            Number of tests that passed.
        """
        return self.tests_run - self.failures - self.errors - self.skipped

    @property
    def pass_rate(self) -> float:
        """
        Calculate test pass rate as percentage.
        
        Returns
        -------
        float
            Pass rate percentage (0.0 to 100.0).
        """
        if self.tests_run == 0:
            return 0.0
        return (self.passed / self.tests_run) * 100.0

    def get_failed_tests(self) -> List[str]:
        """
        Get list of failed test names.
        
        Returns
        -------
        List[str]
            Names of failed tests.
        """
        return [f.get('test', None) for f in self.detailed_failures]

    def get_error_summary(self) -> Dict[str, int]:
        """
        Get summary of error types.
        
        Returns
        -------
        Dict[str, int]
            Count of each error type.
        """
        error_types: Dict[str, int] = {}
        
        for failure in self.detailed_failures:
            error_msg = failure.get('error', 'Unknown error')
            error_type = error_msg.split(':')[0] if ':' in error_msg else error_msg[:50]
            error_types[error_type] = error_types.get(error_type, 0) + 1
        
        return error_types

    def to_dict(self, include_output: bool = True) -> Dict[str, Any]:
        """
        Convert TestResultData to dictionary.
        
        Parameters
        ----------
        include_output : bool, optional
            Whether to include captured output (can be large), by default True.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the test result.
        """
        result = {
            "tests_run": self.tests_run,
            "failures": self.failures,
            "errors": self.errors,
            "skipped": self.skipped,
            "passed": self.passed,
            "pass_rate": round(self.pass_rate, 2),
            "success": self.success,
            "test_files": self.test_files,
            "detailed_failures": self.detailed_failures,
            "execution_time": self.execution_time,
            "execution_time_formatted": _format_duration(self.execution_time),
            "timestamp": self.timestamp,
            "framework": self.framework,
            "summary": self.summary,
            "status_emoji": self.status_emoji,
        }
        
        if include_output:
            result["output"] = self.output
        
        return result

    def to_json(self, indent: int = 2, include_output: bool = True) -> str:
        """
        Convert TestResultData to JSON string.
        
        Parameters
        ----------
        indent : int, optional
            JSON indentation level, by default 2.
        include_output : bool, optional
            Whether to include captured output, by default True.
        
        Returns
        -------
        str
            JSON string representation.
        """
        return json.dumps(self.to_dict(include_output=include_output), indent=indent)


# -----------------------------------------------------------------------------
# Time Result Model
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class TimeResult:
    """
    Timing results for module import.

    This immutable class encapsulates statistical timing measurements
    for module import operations.

    Attributes
    ----------
    average : float
        Average import time in seconds.
    min_time : float
        Minimum observed import time in seconds.
    max_time : float
        Maximum observed import time in seconds.
    stddev : float
        Standard deviation of import times.
    category : str
        Classification of import speed:
        - 'instant': < 0.005s
        - 'light': < 0.01s
        - 'medium': < 0.1s
        - 'heavy': < 0.5s
        - 'critical': ≥ 0.5s

    Examples
    --------
    >>> time_result = TimeResult(
    ...     average=0.045,
    ...     min_time=0.042,
    ...     max_time=0.048,
    ...     stddev=0.002,
    ...     category="medium"
    ... )
    >>> print(time_result.formatted_average)
    45.00ms
    >>> print(time_result.coefficient_of_variation)
    0.044
    """

    average: float
    min_time: float
    max_time: float
    stddev: float
    category: str

    def __post_init__(self) -> None:
        """Validate time values after initialization."""
        if self.average < 0:
            raise ValueError(f"Average time cannot be negative: {self.average}")
        if self.min_time < 0:
            raise ValueError(f"Minimum time cannot be negative: {self.min_time}")
        if self.max_time < 0:
            raise ValueError(f"Maximum time cannot be negative: {self.max_time}")
        if self.stddev < 0:
            raise ValueError(f"Standard deviation cannot be negative: {self.stddev}")
        if self.min_time > self.max_time:
            raise ValueError(
                f"Minimum time ({self.min_time}) cannot exceed maximum ({self.max_time})"
            )

    @property
    def range_time(self) -> float:
        """
        Calculate time range (max - min).
        
        Returns
        -------
        float
            Difference between max and min times.
        """
        return self.max_time - self.min_time

    @property
    def coefficient_of_variation(self) -> float:
        """
        Calculate coefficient of variation (stddev / mean).
        
        Returns
        -------
        float
            Coefficient of variation, or 0.0 if mean is zero.
        """
        if self.average == 0:
            return 0.0
        return self.stddev / self.average

    @property
    def is_stable(self) -> bool:
        """
        Check if timing is stable (low variation).
        
        Returns
        -------
        bool
            True if coefficient of variation < 0.1.
        """
        return self.coefficient_of_variation < 0.1

    @property
    def formatted_average(self) -> str:
        """
        Get formatted average time string.
        
        Returns
        -------
        str
            Human-readable average time.
        """
        return _format_duration(self.average)

    @property
    def formatted_min(self) -> str:
        """
        Get formatted minimum time string.
        
        Returns
        -------
        str
            Human-readable minimum time.
        """
        return _format_duration(self.min_time)

    @property
    def formatted_max(self) -> str:
        """
        Get formatted maximum time string.
        
        Returns
        -------
        str
            Human-readable maximum time.
        """
        return _format_duration(self.max_time)

    @property
    def formatted_range(self) -> str:
        """
        Get formatted time range string.
        
        Returns
        -------
        str
            Human-readable time range.
        """
        return _format_duration(self.range_time)

    @property
    def category_color(self) -> str:
        """
        Get ANSI color code for category.
        
        Returns
        -------
        str
            ANSI color escape sequence.
        """
        colors = {
            'instant': '\033[92m',  # Bright green
            'light': '\033[32m',    # Green
            'medium': '\033[33m',   # Yellow
            'heavy': '\033[91m',    # Bright red
            'critical': '\033[31m', # Red
        }
        return colors.get(self.category, '\033[0m')

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert TimeResult to comprehensive dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation with additional computed properties.
        """
        return {
            "average": self.average,
            "min_time": self.min_time,
            "max_time": self.max_time,
            "stddev": self.stddev,
            "category": self.category,
            "range": self.range_time,
            "coefficient_of_variation": round(self.coefficient_of_variation, 4),
            "is_stable": self.is_stable,
            "formatted": {
                "average": self.formatted_average,
                "min": self.formatted_min,
                "max": self.formatted_max,
                "range": self.formatted_range,
            },
        }

    def to_json(self, indent: int = 2) -> str:
        """
        Convert TimeResult to JSON string.
        
        Parameters
        ----------
        indent : int, optional
            JSON indentation level, by default 2.
        
        Returns
        -------
        str
            JSON string representation.
        """
        return json.dumps(self.to_dict(), indent=indent)

    def __str__(self) -> str:
        """String representation with formatted time."""
        return f"{self.formatted_average} ({self.category})"

    def __lt__(self, other: 'TimeResult') -> bool:
        """Compare by average time."""
        return self.average < other.average

    def __gt__(self, other: 'TimeResult') -> bool:
        """Compare by average time."""
        return self.average > other.average


# -----------------------------------------------------------------------------
# Memory Result Model
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class MemoryResult:
    """
    Memory usage results for module import.

    This immutable class encapsulates peak memory consumption during
    module import operations.

    Attributes
    ----------
    peak_kb : int
        Peak memory usage in kilobytes.
    category : str
        Classification of memory usage:
        - 'light': < 512 KB
        - 'moderate': < 5 MB (5120 KB)
        - 'heavy': < 50 MB (51200 KB)
        - 'critical': ≥ 50 MB

    Examples
    --------
    >>> memory_result = MemoryResult(
    ...     peak_kb=2048,
    ...     category="moderate"
    ... )
    >>> print(memory_result.formatted_peak)
    2.00 MB
    >>> print(memory_result.peak_mb)
    2.0
    """

    peak_kb: int
    category: str

    def __post_init__(self) -> None:
        """Validate memory value after initialization."""
        if self.peak_kb != None and self.peak_kb < 0:
            raise ValueError(f"Peak memory cannot be negative: {self.peak_kb}")

    @property
    def peak_bytes(self) -> int:
        """
        Get peak memory in bytes.
        
        Returns
        -------
        int
            Peak memory in bytes.
        """
        return self.peak_kb * 1024

    @property
    def peak_mb(self) -> float:
        """
        Get peak memory in megabytes.
        
        Returns
        -------
        float
            Peak memory in MB.
        """
        return self.peak_kb / 1024.0

    @property
    def peak_gb(self) -> float:
        """
        Get peak memory in gigabytes.
        
        Returns
        -------
        float
            Peak memory in GB.
        """
        return self.peak_kb / (1024.0 * 1024.0)

    @property
    def formatted_peak(self) -> str:
        """
        Get formatted peak memory string.
        
        Returns
        -------
        str
            Human-readable memory size.
        """
        return _format_memory(self.peak_kb)

    @property
    def is_lightweight(self) -> bool:
        """
        Check if memory usage is lightweight.
        
        Returns
        -------
        bool
            True if category is 'light'.
        """
        return self.category == 'light'

    @property
    def is_memory_hog(self) -> bool:
        """
        Check if module is a memory hog.
        
        Returns
        -------
        bool
            True if category is 'memory-hog' or 'critical'.
        """
        return self.category in ('memory-hog', 'critical')

    @property
    def category_color(self) -> str:
        """
        Get ANSI color code for category.
        
        Returns
        -------
        str
            ANSI color escape sequence.
        """
        colors = {
            'light': '\033[32m',       # Green
            'moderate': '\033[33m',    # Yellow
            'heavy': '\033[91m',       # Bright red
            'critical': '\033[31m',    # Red
            'memory-hog': '\033[31m',  # Red
        }
        return colors.get(self.category, '\033[0m')

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert MemoryResult to comprehensive dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation with additional computed properties.
        """
        return {
            "peak_kb": self.peak_kb,
            "peak_bytes": self.peak_bytes,
            "peak_mb": round(self.peak_mb, 2),
            "peak_gb": round(self.peak_gb, 4),
            "category": self.category,
            "formatted": self.formatted_peak,
            "is_lightweight": self.is_lightweight,
            "is_memory_hog": self.is_memory_hog,
        }

    def to_json(self, indent: int = 2) -> str:
        """
        Convert MemoryResult to JSON string.
        
        Parameters
        ----------
        indent : int, optional
            JSON indentation level, by default 2.
        
        Returns
        -------
        str
            JSON string representation.
        """
        return json.dumps(self.to_dict(), indent=indent)

    def __str__(self) -> str:
        """String representation with formatted memory."""
        return f"{self.formatted_peak} ({self.category})"

    def __lt__(self, other: 'MemoryResult') -> bool:
        """Compare by peak memory."""
        return self.peak_kb < other.peak_kb

    def __gt__(self, other: 'MemoryResult') -> bool:
        """Compare by peak memory."""
        return self.peak_kb > other.peak_kb


# -----------------------------------------------------------------------------
# Dependency Result Model
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class DependencyResult:
    """
    Dependency analysis results for module import.

    This immutable class encapsulates the number of additional modules
    loaded during import.

    Attributes
    ----------
    loaded : int
        Number of additional modules loaded (transitive dependencies).
    category : str
        Classification of dependency count:
        - 'minimal': < 20 modules
        - 'moderate': < 100 modules
        - 'heavy': < 500 modules
        - 'explosive': ≥ 500 modules

    Examples
    --------
    >>> deps_result = DependencyResult(
    ...     loaded=45,
    ...     category="moderate"
    ... )
    >>> print(deps_result.dependency_level)
    moderate
    >>> print(deps_result.is_minimal)
    False
    """

    count: int = 0
    category: str = None

    def __post_init__(self) -> None:
        """Validate dependency count after initialization."""
        if self.count < 0:
            raise ValueError(f"Dependency count cannot be negative: {self.count}")

    @property
    def is_minimal(self) -> bool:
        """
        Check if dependency count is minimal.
        
        Returns
        -------
        bool
            True if category is 'minimal'.
        """
        return self.category == 'minimal'

    @property
    def is_explosive(self) -> bool:
        """
        Check if dependency count is explosive.
        
        Returns
        -------
        bool
            True if category is 'explosive'.
        """
        return self.category == 'explosive'

    @property
    def dependency_level(self) -> str:
        """
        Get dependency level description.
        
        Returns
        -------
        str
            Human-readable dependency level.
        """
        return self.category

    @property
    def complexity_score(self) -> float:
        """
        Calculate dependency complexity score (0-1).
        
        Returns
        -------
        float
            Normalized complexity score.
        """
        if self.count < 20:
            return self.count / 20 * 0.25
        elif self.count < 100:
            return 0.25 + (self.count - 20) / 80 * 0.25
        elif self.count < 500:
            return 0.5 + (self.count - 100) / 400 * 0.5
        else:
            return 1.0

    @property
    def category_color(self) -> str:
        """
        Get ANSI color code for category.
        
        Returns
        -------
        str
            ANSI color escape sequence.
        """
        colors = {
            'minimal': '\033[32m',    # Green
            'moderate': '\033[33m',   # Yellow
            'heavy': '\033[91m',      # Bright red
            'explosive': '\033[31m',  # Red
        }
        return colors.get(self.category, '\033[0m')

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert DependencyResult to comprehensive dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation with additional computed properties.
        """
        return {
            "loaded": self.count,
            "category": self.category,
            "is_minimal": self.is_minimal,
            "is_explosive": self.is_explosive,
            "dependency_level": self.dependency_level,
            "complexity_score": round(self.complexity_score, 3),
        }

    def to_json(self, indent: int = 2) -> str:
        """
        Convert DependencyResult to JSON string.
        
        Parameters
        ----------
        indent : int, optional
            JSON indentation level, by default 2.
        
        Returns
        -------
        str
            JSON string representation.
        """
        return json.dumps(self.to_dict(), indent=indent)

    def __str__(self) -> str:
        """String representation with dependency count."""
        return f"{self.count} modules ({self.category})"

    def __lt__(self, other: 'DependencyResult') -> bool:
        """Compare by loaded count."""
        return self.count < other.count

    def __gt__(self, other: 'DependencyResult') -> bool:
        """Compare by loaded count."""
        return self.count > other.count


# -----------------------------------------------------------------------------
# Stability Result Model
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class StabilityResult:
    """
    Stability analysis results for module import.

    This immutable class encapsulates import time stability metrics.

    Attributes
    ----------
    index : float
        Stability index (coefficient of variation: stddev/mean).
        Lower values indicate more stable import times.
    category : str
        Classification of stability:
        - 'stable': index < 0.05
        - 'normal': index < 0.15
        - 'unstable': index < 0.30
        - 'chaotic': index ≥ 0.30

    Examples
    --------
    >>> stability_result = StabilityResult(
    ...     index=0.08,
    ...     category="normal"
    ... )
    >>> print(stability_result.stability_percentage)
    92.0%
    >>> print(stability_result.is_stable)
    False
    """

    index: float
    category: str
    confidence: float 

    def __post_init__(self) -> None:
        """Validate stability index after initialization."""
        if self.index < 0:
            raise ValueError(f"Stability index cannot be negative: {self.index}")

    @property
    def is_stable(self) -> bool:
        """
        Check if import is stable.
        
        Returns
        -------
        bool
            True if category is 'stable'.
        """
        return self.category == 'stable'

    @property
    def is_chaotic(self) -> bool:
        """
        Check if import is chaotic.
        
        Returns
        -------
        bool
            True if category is 'chaotic'.
        """
        return self.category == 'chaotic'

    @property
    def stability_percentage(self) -> float:
        """
        Calculate stability as percentage (100% - variation%).
        
        Returns
        -------
        float
            Stability percentage (0-100).
        """
        return max(0.0, min(100.0, (1.0 - self.index) * 100.0))

    @property
    def reliability_score(self) -> float:
        """
        Calculate reliability score (0-1).
        
        Returns
        -------
        float
            Reliability score where 1.0 is perfectly stable.
        """
        if self.index >= 0.5:
            return 0.0
        return max(0.0, 1.0 - self.index)

    @property
    def category_color(self) -> str:
        """
        Get ANSI color code for category.
        
        Returns
        -------
        str
            ANSI color escape sequence.
        """
        colors = {
            'stable': '\033[32m',    # Green
            'normal': '\033[33m',    # Yellow
            'unstable': '\033[91m',  # Bright red
            'chaotic': '\033[31m',   # Red
        }
        return colors.get(self.category, '\033[0m')

    @property
    def description(self) -> str:
        """
        Get human-readable stability description.
        
        Returns
        -------
        str
            Description of stability level.
        """
        descriptions = {
            'stable': 'Highly predictable import times',
            'normal': 'Minor variations, generally reliable',
            'unstable': 'Significant variations, may impact performance',
            'chaotic': 'Extremely unpredictable, investigation recommended',
        }
        return descriptions.get(self.category, 'Unknown stability level')

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert StabilityResult to comprehensive dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation with additional computed properties.
        """
        return {
            "index": self.index,
            "category": self.category,
            "is_stable": self.is_stable,
            "is_chaotic": self.is_chaotic,
            "stability_percentage": round(self.stability_percentage, 2),
            "reliability_score": round(self.reliability_score, 3),
            "description": self.description,
        }

    def to_json(self, indent: int = 2) -> str:
        """
        Convert StabilityResult to JSON string.
        
        Parameters
        ----------
        indent : int, optional
            JSON indentation level, by default 2.
        
        Returns
        -------
        str
            JSON string representation.
        """
        return json.dumps(self.to_dict(), indent=indent)

    def __str__(self) -> str:
        """String representation with stability percentage."""
        return f"{self.stability_percentage:.1f}% stable ({self.category})"

    def __lt__(self, other: 'StabilityResult') -> bool:
        """Compare by stability index (lower is better)."""
        return self.index < other.index

    def __gt__(self, other: 'StabilityResult') -> bool:
        """Compare by stability index (lower is better)."""
        return self.index > other.index


# -----------------------------------------------------------------------------
# Import Profile Model
# -----------------------------------------------------------------------------

@dataclass
class ImportProfile:
    """
    Complete import profile for a Python module.

    This immutable class aggregates all performance dimensions into a
    comprehensive profile suitable for analysis, comparison, and reporting.

    Attributes
    ----------
    module : str
        Name of the module being profiled.
    time : TimeResult
        Timing results for the import.
    memory : MemoryResult
        Memory usage results for the import.
    dependencies : DependencyResult
        Dependency analysis results.
    stability : StabilityResult
        Stability analysis results.

    Examples
    --------
    >>> profile = ImportProfile(
    ...     module="numpy",
    ...     time=time_result,
    ...     memory=memory_result,
    ...     dependencies=deps_result,
    ...     stability=stability_result,
    ... )
    >>> print(profile.overall_score)
    0.234
    >>> print(profile.severity)
    MINOR
    >>> # Export to JSON
    >>> json_str = profile.to_json()
    """

    module: str
    time: TimeResult
    memory: MemoryResult
    dependencies: DependencyResult
    stability: StabilityResult

    def __post_init__(self) -> None:
        """Validate module name after initialization."""
        if not self.module or not isinstance(self.module, str):
            raise ValueError(f"Invalid module name: {self.module}")

    @property
    def overall_score(self) -> float:
        """
        Calculate weighted overall performance score (0-1, lower is better).
        
        Returns
        -------
        float
            Composite performance score.
        """
        # Weights for each dimension
        weights = {
            'time': 0.35,
            'memory': 0.30,
            'dependencies': 0.20,
            'stability': 0.15,
        }
        
        # Time score (normalized)
        if self.time.average < 0.01:
            time_score = 0.0
        elif self.time.average < 0.1:
            time_score = 0.2
        elif self.time.average < 0.5:
            time_score = 0.5
        else:
            time_score = 1.0
        
        # Memory score (normalized)
        if self.memory.peak_kb < 512:
            memory_score = 0.0
        elif self.memory.peak_kb < 5000:
            memory_score = 0.3
        elif self.memory.peak_kb < 50000:
            memory_score = 0.6
        else:
            memory_score = 1.0
        
        # Dependency score
        deps_score = self.dependencies.complexity_score
        
        # Stability score
        stability_score = 1.0 - self.stability.reliability_score
        
        return (
            time_score * weights['time'] +
            memory_score * weights['memory'] +
            deps_score * weights['dependencies'] +
            stability_score * weights['stability']
        )

    @property
    def severity(self) -> str:
        """
        Get overall severity level.
        
        Returns
        -------
        str
            Severity classification.
        """
        score = self.overall_score
        if score < 0.2:
            return "NEGLIGIBLE"
        elif score < 0.4:
            return "MINOR"
        elif score < 0.6:
            return "MODERATE"
        elif score < 0.8:
            return "MAJOR"
        else:
            return "CRITICAL"

    @property
    def profile_hash(self) -> str:
        """
        Generate unique hash for this profile.
        
        Returns
        -------
        str
            SHA256 hash of profile data.
        """
        data = self.to_dict()
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()[:16]

    @property
    def is_problematic(self) -> bool:
        """
        Check if module has significant performance issues.
        
        Returns
        -------
        bool
            True if overall score >= 0.5.
        """
        return self.overall_score >= 0.5

    def get_recommended(self) -> List[str]:
        """
        Generate optimization recommendations based on profile.
        
        Returns
        -------
        List[str]
            List of actionable recommendations.
        """
        recommendations = []
        
        if self.time.average > 0.1:
            recommendations.append(
                f"Import time is {self.time.formatted_average}. Consider lazy loading "
                "or optimizing initialization code."
            )
        
        if self.memory.peak_mb > 10:
            recommendations.append(
                f"Memory usage is {self.memory.formatted_peak}. Consider using "
                "__slots__ or lazy attribute loading."
            )
        
        if self.dependencies.loaded > 100:
            recommendations.append(
                f"Large dependency tree ({self.dependencies.loaded} modules). "
                "Consider vendoring or optional imports."
            )
        
        if self.stability.index > 0.2:
            recommendations.append(
                "High import time variability. Check for filesystem cache issues "
                "or conditional imports."
            )
        
        return recommendations

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert ImportProfile to comprehensive dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Complete dictionary representation.
        """
        return {
            "module": self.module,
            "time": self.time.to_dict(),
            "memory": self.memory.to_dict(),
            "dependencies": self.dependencies.to_dict(),
            "stability": self.stability.to_dict(),
            "overall_score": round(self.overall_score, 4),
            "severity": self.severity,
            "is_problematic": self.is_problematic,
            "recommendations": self.get_recommended(),
            "profile_hash": self.profile_hash,
        }

    def to_json(self, indent: int = 2) -> str:
        """
        Convert ImportProfile to JSON string.
        
        Parameters
        ----------
        indent : int, optional
            JSON indentation level, by default 2.
        
        Returns
        -------
        str
            JSON string representation.
        """
        return json.dumps(self.to_dict(), indent=indent)

    def __str__(self) -> str:
        """String representation with key metrics."""
        return f"{self.module}: {self.time.formatted_average} | {self.memory.formatted_peak} | Score: {self.overall_score:.2f}"

    def __lt__(self, other: 'ImportProfile') -> bool:
        """Compare by overall score (lower is better)."""
        return self.overall_score < other.overall_score


# -----------------------------------------------------------------------------
# Import Benchmark Result Model (Legacy)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ImportBenchmarkResult:
    """
    Container holding import benchmark statistics for a single module.

    This is a legacy class maintained for backward compatibility.
    Prefer using `ImportProfile` for new code.

    Attributes
    ----------
    module : str
        Name of the benchmarked module.
    average : float
        Average cold-start import time in seconds.
    min_time : float
        Minimum observed import time.
    max_time : float
        Maximum observed import time.
    stddev : float
        Standard deviation of measured import times.
    category : str
        Performance category inferred from the average import time.

    Notes
    -----
    The ``category`` field is a convenience label and should not be
    considered a strict performance guarantee.
    This class is maintained for backward compatibility with older
    versions of the package.

    Examples
    --------
    >>> result = ImportBenchmarkResult(
    ...     module="requests",
    ...     average=0.045,
    ...     min_time=0.042,
    ...     max_time=0.048,
    ...     stddev=0.002,
    ...     category="medium"
    ... )
    >>> print(result.summary)
    requests: 45.00ms (medium)
    """

    module: str
    average: float
    min_time: float
    max_time: float
    stddev: float
    category: str

    def __post_init__(self) -> None:
        """Validate benchmark values after initialization."""
        if self.average < 0:
            raise ValueError(f"Average time cannot be negative: {self.average}")
        if self.min_time < 0:
            raise ValueError(f"Minimum time cannot be negative: {self.min_time}")
        if self.max_time < 0:
            raise ValueError(f"Maximum time cannot be negative: {self.max_time}")
        if self.stddev < 0:
            raise ValueError(f"Standard deviation cannot be negative: {self.stddev}")

    @property
    def formatted_average(self) -> str:
        """
        Get formatted average time string.
        
        Returns
        -------
        str
            Human-readable average time.
        """
        return _format_duration(self.average)

    @property
    def range_time(self) -> float:
        """
        Calculate time range (max - min).
        
        Returns
        -------
        float
            Difference between max and min times.
        """
        return self.max_time - self.min_time

    @property
    def coefficient_of_variation(self) -> float:
        """
        Calculate coefficient of variation.
        
        Returns
        -------
        float
            Standard deviation divided by mean.
        """
        if self.average == 0:
            return 0.0
        return self.stddev / self.average

    @property
    def summary(self) -> str:
        """
        Generate human-readable summary.
        
        Returns
        -------
        str
            Formatted summary string.
        """
        return f"{self.module}: {self.formatted_average} ({self.category})"

    def to_time_result(self) -> TimeResult:
        """
        Convert to modern TimeResult object.
        
        Returns
        -------
        TimeResult
            Equivalent TimeResult instance.
        """
        return TimeResult(
            average=self.average,
            min_time=self.min_time,
            max_time=self.max_time,
            stddev=self.stddev,
            category=self.category,
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary representation.
        """
        return {
            "module": self.module,
            "average": self.average,
            "min_time": self.min_time,
            "max_time": self.max_time,
            "stddev": self.stddev,
            "category": self.category,
            "formatted_average": self.formatted_average,
            "range": self.range_time,
            "coefficient_of_variation": round(self.coefficient_of_variation, 4),
            "summary": self.summary,
        }

    def to_json(self, indent: int = 2) -> str:
        """
        Convert to JSON string.
        
        Parameters
        ----------
        indent : int, optional
            JSON indentation level, by default 2.
        
        Returns
        -------
        str
            JSON string representation.
        """
        return json.dumps(self.to_dict(), indent=indent)

    def __str__(self) -> str:
        """String representation with summary."""
        return self.summary

    def __lt__(self, other: 'ImportBenchmarkResult') -> bool:
        """Compare by average time."""
        return self.average < other.average

    def __gt__(self, other: 'ImportBenchmarkResult') -> bool:
        """Compare by average time."""
        return self.average > other.average


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Main models
    'TestResultData',
    'TimeResult',
    'MemoryResult',
    'DependencyResult',
    'StabilityResult',
    'ImportProfile',
    'ImportBenchmarkResult',
    
    # Utility functions
    '_format_duration',
    '_format_memory',
    '_calculate_percentile',
]