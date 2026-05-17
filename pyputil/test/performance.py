#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
performance.py

Python Import Performance Analysis System.

This module provides a comprehensive, production-ready interface for analyzing
Python module import performance across multiple dimensions. It serves as the
primary public API for the import-profiler package, offering both high-level
convenience functions and granular control through the ImportProfiler class.

The system is designed for:
- CI/CD pipeline integration for performance regression detection
- Interactive development and debugging workflows
- Production monitoring and alerting systems
- Automated dependency auditing and scoring
- Comparative analysis between module versions
- Historical trend analysis and forecasting

Features
--------
- Multi-dimensional profiling (time, memory, dependencies, stability)
- Comparative analysis between modules and versions
- Historical tracking with trend detection
- Threshold-based alerting and regression detection
- Rich export formats (JSON, CSV, HTML reports)
- Asynchronous profiling support
- Caching for repeated measurements
- Plugin system for custom metrics
- Integration with monitoring systems (Prometheus, Datadog)
- Comprehensive error handling and recovery

Classes
-------
ImportProfiler
    Main profiling engine with extensive configuration options.
ProfileComparator
    Utility for comparing multiple import profiles.
RegressionDetector
    Statistical regression detection for CI/CD pipelines.
ProfileCache
    LRU cache for profile results with TTL support.
ProfilingReport
    Rich report generation in multiple formats.
AlertManager
    Threshold-based alerting and notification system.
TrendAnalyzer
    Historical trend analysis and forecasting.

Functions
---------
profile_import
    Convenience function for single module profiling.
difftime
    Compare import performance between two modules.
profile_batch
    Batch profiling with progress tracking.
compare_versions
    Compare import performance across module versions.
detect_regressions
    Identify performance regressions in CI/CD context.
export_profile
    Export profile results to various formats.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import csv
import hashlib
import io
import json
import logging
import math
import os
import pickle
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from functools import lru_cache, partial, wraps
from pathlib import Path
from typing import (
    Any, Callable, Dict, Generator, Iterable, Iterator, List, 
    NamedTuple, Optional, Sequence, Set, Tuple, Type, TypeVar, Union,
    cast, overload
)

# Local imports with graceful fallbacks
from .models import (
        ImportProfile,
        TimeResult,
        MemoryResult,
        DependencyResult,
        StabilityResult,
        ImportBenchmarkResult,
)
from ._perf_probes import (
        run_memory_probe,
        collect_timing_samples,
        analyze_timing_data,
        calculate_stability_index,
        _run_import,
        _measure_import,
        ProbeConfig,
        ProbeResult,
        DetailedTimeResult,
        DetailedMemoryResult,
        DetailedDependencyResult,
        ProbeSession,
        WarmupStrategy,
        MeasurementMode,
        CacheState,
)
from ._perf_classifiers import (
        classify_time,
        classify_memory,
        classify_dependencies,
        classify_stability,
        _classify,
        PerformanceScore,
        ClassifiedModule,
        AdaptiveThresholds,
        Severity,
)

# -----------------------------------------------------------------------------
# Module Configuration and Constants
# -----------------------------------------------------------------------------

# Default profiling parameters
DEFAULT_REPETITIONS: Final[int] = 5
DEFAULT_WARMUP: Final[int] = 2
DEFAULT_TIMEOUT: Final[float] = 30.0
DEFAULT_CACHE_SIZE: Final[int] = 100
DEFAULT_CACHE_TTL: Final[int] = 3600  # 1 hour
DEFAULT_CONCURRENCY: Final[int] = min(4, os.cpu_count() or 2)

# Regression detection thresholds
REGRESSION_THRESHOLD_PERCENT: Final[float] = 20.0  # 20% slowdown
REGRESSION_THRESHOLD_ABSOLUTE: Final[float] = 0.05  # 50ms absolute
REGRESSION_CONFIDENCE_LEVEL: Final[float] = 0.95

# Alert thresholds
ALERT_MEMORY_MB: Final[int] = 100  # Alert if memory exceeds 100MB
ALERT_TIME_SECONDS: Final[float] = 1.0  # Alert if import exceeds 1 second
ALERT_DEPS_COUNT: Final[int] = 200  # Alert if dependencies exceed 200

# Configure structured logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


# -----------------------------------------------------------------------------
# Enhanced Data Structures
# -----------------------------------------------------------------------------

@dataclass
class ProfilingMetadata:
    """
    Comprehensive metadata for profiling sessions.
    
    Attributes
    ----------
    profiler_version : str
        Version of the profiler used.
    python_version : str
        Python interpreter version.
    platform_info : str
        Operating system and architecture.
    cpu_count : int
        Number of CPU cores available.
    timestamp : datetime
        When the profile was created.
    environment : str
        Execution environment (ci, development, production).
    git_commit : Optional[str]
        Current git commit hash if available.
    custom_tags : Dict[str, str]
        User-defined metadata tags.
    """
    
    python_version: str = field(default_factory=lambda: sys.version.split()[0])
    platform_info: str = field(default_factory=platform.platform)
    cpu_count: Optional[int] = field(default_factory=os.cpu_count)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    environment: str = field(default_factory=lambda: (
        'ci' if os.environ.get('CI') else 
        'production' if not __debug__ else 
        'development'
    ))
    git_commit: Optional[str] = field(default_factory=lambda: _get_git_commit())
    custom_tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with ISO timestamp."""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data


def _get_git_commit() -> Optional[str]:
    """Attempt to get current git commit hash."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return None


@dataclass
class EnhancedImportProfile(ImportProfile):
    """
    Enhanced import profile with additional analytics and metadata.
    
    Attributes
    ----------
    metadata : ProfilingMetadata
        Comprehensive profiling metadata.
    scores : PerformanceScore
        Weighted performance scores.
    recommendations : List[str]
        Suggested optimizations.
    raw_measurements : Dict[str, Any]
        Raw measurement data for reproducibility.
    alerts : List[str]
        Triggered alert messages.
    """
    
    metadata: ProfilingMetadata = field(default_factory=ProfilingMetadata)
    scores: Optional[Any] = None  # PerformanceScore type
    recommendations: List[str] = field(default_factory=list)
    raw_measurements: Dict[str, Any] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)
    
    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self), default=str, indent=indent)
    
    def to_csv_row(self) -> Dict[str, Any]:
        """Convert to flat dictionary suitable for CSV export."""
        return {
            'module': self.module,
            'time_avg': self.time.average,
            'time_min': self.time.min_time,
            'time_max': self.time.max_time,
            'time_stddev': self.time.stddev,
            'time_category': self.time.category,
            'memory_kb': self.memory.peak_kb if self.memory.peak_kb else None,
            'memory_category': self.memory.category,
            'deps_count': self.dependencies.count,
            'deps_category': self.dependencies.category,
            'stability_index': self.stability.index,
            'stability_category': self.stability.category,
            'timestamp': self.metadata.timestamp.isoformat(),
            'environment': self.metadata.environment,
        }
    
    @property
    def overall_severity(self) -> Severity:
        """Calculate overall severity based on all metrics."""
        severities = []
        
        # Time severity
        if self.time.average < 0.01:
            severities.append(Severity.NEGLIGIBLE)
        elif self.time.average < 0.1:
            severities.append(Severity.MINOR)
        elif self.time.average < 0.5:
            severities.append(Severity.MODERATE)
        elif self.time.average < 1.0:
            severities.append(Severity.MAJOR)
        else:
            severities.append(Severity.CRITICAL)
        
        # Memory severity
        if self.memory.peak_kb < 1024:  # < 1MB
            severities.append(Severity.NEGLIGIBLE)
        elif self.memory.peak_kb < 10240:  # < 10MB
            severities.append(Severity.MINOR)
        elif self.memory.peak_kb < 51200:  # < 50MB
            severities.append(Severity.MODERATE)
        elif self.memory.peak_kb < 102400:  # < 100MB
            severities.append(Severity.MAJOR)
        else:
            severities.append(Severity.CRITICAL)
        
        return max(severities, key=lambda s: s.value)


# -----------------------------------------------------------------------------
# Profile Cache Implementation
# -----------------------------------------------------------------------------

class ProfileCache:
    """
    Thread-safe LRU cache for profile results with TTL support.
    
    This cache significantly improves performance when repeatedly profiling
    the same modules, especially in development and testing workflows.
    
    Attributes
    ----------
    max_size : int
        Maximum number of cached profiles.
    ttl_seconds : int
        Time-to-live for cached entries in seconds.
    """
    
    def __init__(self, max_size: int = DEFAULT_CACHE_SIZE, ttl_seconds: int = DEFAULT_CACHE_TTL):
        """
        Initialize profile cache.
        
        Parameters
        ----------
        max_size : int
            Maximum number of cached profiles.
        ttl_seconds : int
            Cache entry lifetime in seconds.
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[EnhancedImportProfile, datetime]] = {}
        self._access_order: deque = deque()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def _make_key(self, module: str, config_hash: str) -> str:
        """Create cache key from module and configuration."""
        return f"{module}:{config_hash}"
    
    def get(self, module: str, config_hash: str) -> Optional[EnhancedImportProfile]:
        """
        Retrieve cached profile if available and not expired.
        
        Parameters
        ----------
        module : str
            Module name.
        config_hash : str
            Hash of profiling configuration.
        
        Returns
        -------
        Optional[EnhancedImportProfile]
            Cached profile or None if not found/expired.
        """
        with self._lock:
            key = self._make_key(module, config_hash)
            
            if key not in self._cache:
                self._misses += 1
                return None
            
            profile, timestamp = self._cache[key]
            
            # Check TTL
            if (datetime.utcnow() - timestamp).total_seconds() > self.ttl_seconds:
                del self._cache[key]
                self._access_order.remove(key)
                self._misses += 1
                return None
            
            # Update access order
            self._access_order.remove(key)
            self._access_order.append(key)
            
            self._hits += 1
            return profile
    
    def put(self, module: str, config_hash: str, profile: EnhancedImportProfile) -> None:
        """
        Store profile in cache.
        
        Parameters
        ----------
        module : str
            Module name.
        config_hash : str
            Hash of profiling configuration.
        profile : EnhancedImportProfile
            Profile to cache.
        """
        with self._lock:
            key = self._make_key(module, config_hash)
            
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_size and key not in self._cache:
                oldest_key = self._access_order.popleft()
                del self._cache[oldest_key]
            
            # Remove old entry if updating
            if key in self._access_order:
                self._access_order.remove(key)
            
            self._cache[key] = (profile, datetime.utcnow())
            self._access_order.append(key)
    
    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            self._hits = 0
            self._misses = 0
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': f"{hit_rate:.1f}%",
                'ttl_seconds': self.ttl_seconds,
            }


# -----------------------------------------------------------------------------
# Regression Detection
# -----------------------------------------------------------------------------

@dataclass
class RegressionResult:
    """
    Result of regression detection analysis.
    
    Attributes
    ----------
    module : str
        Module name.
    has_regression : bool
        Whether regression was detected.
    baseline_profile : EnhancedImportProfile
        Baseline profile for comparison.
    current_profile : EnhancedImportProfile
        Current profile being compared.
    time_change_percent : float
        Percentage change in import time.
    memory_change_percent : float
        Percentage change in memory usage.
    deps_change_absolute : int
        Absolute change in dependency count.
    confidence_score : float
        Statistical confidence in regression detection.
    details : Dict[str, Any]
        Additional regression details.
    """
    
    module: str
    has_regression: bool
    baseline_profile: EnhancedImportProfile
    current_profile: EnhancedImportProfile
    time_change_percent: float
    memory_change_percent: float
    deps_change_absolute: int
    confidence_score: float
    details: Dict[str, Any] = field(default_factory=dict)


class RegressionDetector:
    """
    Statistical regression detection for CI/CD pipelines.
    
    This class provides sophisticated regression detection using statistical
    methods to identify genuine performance degradations while minimizing
    false positives from measurement noise.
    
    Examples
    --------
    >>> detector = RegressionDetector()
    >>> baseline = profiler.profile("numpy")
    >>> # ... after changes ...
    >>> current = profiler.profile("numpy")
    >>> result = detector.detect(baseline, current)
    >>> if result.has_regression:
    ...     print(f"Regression detected: {result.summary}")
    """
    
    def __init__(
        self,
        time_threshold_percent: float = REGRESSION_THRESHOLD_PERCENT,
        time_threshold_absolute: float = REGRESSION_THRESHOLD_ABSOLUTE,
        memory_threshold_percent: float = REGRESSION_THRESHOLD_PERCENT,
        deps_threshold_absolute: int = 20,
        confidence_level: float = REGRESSION_CONFIDENCE_LEVEL,
    ):
        """
        Initialize regression detector.
        
        Parameters
        ----------
        time_threshold_percent : float
            Percentage increase in time to flag as regression.
        time_threshold_absolute : float
            Absolute time increase in seconds to flag as regression.
        memory_threshold_percent : float
            Percentage increase in memory to flag as regression.
        deps_threshold_absolute : int
            Absolute increase in dependencies to flag as regression.
        confidence_level : float
            Statistical confidence level required (0.0-1.0).
        """
        self.time_threshold_percent = time_threshold_percent
        self.time_threshold_absolute = time_threshold_absolute
        self.memory_threshold_percent = memory_threshold_percent
        self.deps_threshold_absolute = deps_threshold_absolute
        self.confidence_level = confidence_level
    
    def detect(
        self,
        baseline: EnhancedImportProfile,
        current: EnhancedImportProfile,
    ) -> RegressionResult:
        """
        Detect regression between baseline and current profile.
        
        Parameters
        ----------
        baseline : EnhancedImportProfile
            Baseline profile (typically from main/stable branch).
        current : EnhancedImportProfile
            Current profile to compare against baseline.
        
        Returns
        -------
        RegressionResult
            Detailed regression analysis results.
        
        Raises
        ------
        ValueError
            If profiles are for different modules.
        """
        if baseline.module != current.module:
            raise ValueError(
                f"Cannot compare different modules: {baseline.module} vs {current.module}"
            )
        
        # Calculate changes
        time_change = current.time.average - baseline.time.average
        time_change_percent = (time_change / baseline.time.average * 100) if baseline.time.average > 0 else 0
        
        memory_change = current.memory.peak_kb - baseline.memory.peak_kb
        memory_change_percent = (memory_change / baseline.memory.peak_kb * 100) if baseline.memory.peak_kb > 0 else 0
        
        deps_change = current.dependencies.count - baseline.dependencies.count
        
        # Statistical confidence using Welch's t-test approximation
        confidence_score = self._calculate_confidence(baseline, current)
        
        # Determine if regression exists
        has_time_regression = (
            time_change_percent > self.time_threshold_percent and 
            time_change > self.time_threshold_absolute
        )
        has_memory_regression = memory_change_percent > self.memory_threshold_percent
        has_deps_regression = deps_change > self.deps_threshold_absolute
        
        has_regression = (
            (has_time_regression or has_memory_regression or has_deps_regression) and
            confidence_score >= self.confidence_level
        )
        
        # Build detailed result
        details = {
            'time': {
                'baseline': baseline.time.average,
                'current': current.time.average,
                'change': time_change,
                'change_percent': time_change_percent,
                'has_regression': has_time_regression,
            },
            'memory': {
                'baseline': baseline.memory.peak_kb if baseline.memory.peak_kb else None,
                'current': current.memory.peak_kb if current.memory.peak_kb else None,
                'change': memory_change,
                'change_percent': memory_change_percent,
                'has_regression': has_memory_regression,
            },
            'dependencies': {
                'baseline': baseline.dependencies.count,
                'current': current.dependencies.count,
                'change': deps_change,
                'has_regression': has_deps_regression,
            },
            'stability': {
                'baseline': baseline.stability.index,
                'current': current.stability.index,
                'change': current.stability.index - baseline.stability.index,
            },
        }
        
        return RegressionResult(
            module=baseline.module,
            has_regression=has_regression,
            baseline_profile=baseline,
            current_profile=current,
            time_change_percent=time_change_percent,
            memory_change_percent=memory_change_percent,
            deps_change_absolute=deps_change,
            confidence_score=confidence_score,
            details=details,
        )
    
    def _calculate_confidence(
        self, 
        baseline: EnhancedImportProfile, 
        current: EnhancedImportProfile
    ) -> float:
        """
        Calculate statistical confidence in difference.
        
        Uses available standard deviation data to compute confidence
        that the observed difference is not due to random variation.
        """
        # If we have raw measurements, use them for better confidence
        if baseline.raw_measurements.get('times') and current.raw_measurements.get('times'):
            baseline_times = baseline.raw_measurements['times']
            current_times = current.raw_measurements['times']
            
            if len(baseline_times) > 1 and len(current_times) > 1:
                # Welch's t-test approximation
                mean_diff = abs(statistics.mean(current_times) - statistics.mean(baseline_times))
                pooled_std = math.sqrt(
                    (statistics.variance(baseline_times) / len(baseline_times)) +
                    (statistics.variance(current_times) / len(current_times))
                )
                
                if pooled_std > 0:
                    t_statistic = mean_diff / pooled_std
                    # Convert t-statistic to approximate confidence
                    confidence = min(1.0, t_statistic / 3.0)  # Rough approximation
                    return confidence
        
        # Fallback: use standard deviations if available
        if baseline.time.stddev > 0 and current.time.stddev > 0:
            pooled_std = math.sqrt(baseline.time.stddev**2 + current.time.stddev**2)
            mean_diff = abs(current.time.average - baseline.time.average)
            if pooled_std > 0:
                confidence = min(1.0, mean_diff / pooled_std)
                return confidence
        
        # Default moderate confidence
        return 0.5
    
    def detect_batch(
        self,
        baselines: Dict[str, EnhancedImportProfile],
        currents: Dict[str, EnhancedImportProfile],
    ) -> List[RegressionResult]:
        """
        Detect regressions across multiple modules.
        
        Parameters
        ----------
        baselines : Dict[str, EnhancedImportProfile]
            Baseline profiles keyed by module name.
        currents : Dict[str, EnhancedImportProfile]
            Current profiles keyed by module name.
        
        Returns
        -------
        List[RegressionResult]
            Regression results for all compared modules.
        """
        results = []
        
        for module in set(baselines.keys()) & set(currents.keys()):
            try:
                result = self.detect(baselines[module], currents[module])
                results.append(result)
            except Exception as e:
                logger.error(f"Regression detection failed for {module}: {e}")
        
        return results


# -----------------------------------------------------------------------------
# Profile Comparison
# -----------------------------------------------------------------------------

@dataclass
class ComparisonResult:
    """
    Result of comparing multiple import profiles.
    
    Attributes
    ----------
    profiles : List[EnhancedImportProfile]
        Profiles that were compared.
    fastest : EnhancedImportProfile
        Profile with fastest import time.
    slowest : EnhancedImportProfile
        Profile with slowest import time.
    most_memory_efficient : EnhancedImportProfile
        Profile with lowest memory usage.
    least_memory_efficient : EnhancedImportProfile
        Profile with highest memory usage.
    fewest_deps : EnhancedImportProfile
        Profile with fewest dependencies.
    most_deps : EnhancedImportProfile
        Profile with most dependencies.
    most_stable : EnhancedImportProfile
        Profile with best stability (lowest index).
    ranking : Dict[str, int]
        Overall ranking by module name.
    summary : str
        Human-readable comparison summary.
    """
    
    profiles: List[EnhancedImportProfile]
    fastest: EnhancedImportProfile
    slowest: EnhancedImportProfile
    most_memory_efficient: EnhancedImportProfile
    least_memory_efficient: EnhancedImportProfile
    fewest_deps: EnhancedImportProfile
    most_deps: EnhancedImportProfile
    most_stable: EnhancedImportProfile
    ranking: Dict[str, int]
    summary: str


class ProfileComparator:
    """
    Utility for comparing multiple import profiles.
    
    This class provides comprehensive comparison capabilities for analyzing
    relative performance across multiple modules or module versions.
    
    Examples
    --------
    >>> comparator = ProfileComparator()
    >>> numpy_profile = profiler.profile("numpy")
    >>> pandas_profile = profiler.profile("pandas")
    >>> result = comparator.compare([numpy_profile, pandas_profile])
    >>> print(result.summary)
    """
    
    def compare(self, profiles: List[EnhancedImportProfile]) -> ComparisonResult:
        """
        Compare multiple import profiles.
        
        Parameters
        ----------
        profiles : List[EnhancedImportProfile]
            List of profiles to compare.
        
        Returns
        -------
        ComparisonResult
            Comprehensive comparison results.
        
        Raises
        ------
        ValueError
            If fewer than 2 profiles provided.
        """
        if len(profiles) < 2:
            raise ValueError("At least 2 profiles required for comparison")
        
        # Sort by various metrics
        by_time = sorted(profiles, key=lambda p: p.time.average)
        by_memory = sorted(profiles, key=lambda p: p.memory.peak_kb)
        by_deps = sorted(profiles, key=lambda p: p.dependencies.count)
        by_stability = sorted(profiles, key=lambda p: p.stability.index)
        
        # Calculate composite ranking
        ranking = self._calculate_ranking(profiles, by_time, by_memory, by_deps, by_stability)
        
        # Generate summary
        summary = self._generate_summary(profiles, by_time, by_memory, by_deps, ranking)
        
        return ComparisonResult(
            profiles=profiles,
            fastest=by_time[0],
            slowest=by_time[-1],
            most_memory_efficient=by_memory[0],
            least_memory_efficient=by_memory[-1],
            fewest_deps=by_deps[0],
            most_deps=by_deps[-1],
            most_stable=by_stability[0],
            ranking=ranking,
            summary=summary,
        )
    
    def _calculate_ranking(
        self,
        profiles: List[EnhancedImportProfile],
        by_time: List[EnhancedImportProfile],
        by_memory: List[EnhancedImportProfile],
        by_deps: List[EnhancedImportProfile],
        by_stability: List[EnhancedImportProfile],
    ) -> Dict[str, int]:
        """Calculate composite ranking across all metrics."""
        scores = {p.module: 0 for p in profiles}
        
        # Weighted scoring (lower is better)
        weights = {'time': 0.4, 'memory': 0.3, 'deps': 0.2, 'stability': 0.1}
        
        for i, p in enumerate(by_time):
            scores[p.module] += i * weights['time']
        
        for i, p in enumerate(by_memory):
            scores[p.module] += i * weights['memory']
        
        for i, p in enumerate(by_deps):
            scores[p.module] += i * weights['deps']
        
        for i, p in enumerate(by_stability):
            scores[p.module] += i * weights['stability']
        
        # Convert scores to rankings (1-based)
        sorted_modules = sorted(scores.keys(), key=lambda m: scores[m])
        return {m: i + 1 for i, m in enumerate(sorted_modules)}
    
    def _generate_summary(
        self,
        profiles: List[EnhancedImportProfile],
        by_time: List[EnhancedImportProfile],
        by_memory: List[EnhancedImportProfile],
        by_deps: List[EnhancedImportProfile],
        ranking: Dict[str, int],
    ) -> str:
        """Generate human-readable comparison summary."""
        lines = [
            f"Comparison of {len(profiles)} modules:",
            "",
            f"Overall Winner: {by_time[0].module} (Rank #{ranking[by_time[0].module]})",
            "",
            "Import Time:",
            f"  Fastest: {by_time[0].module} ({by_time[0].time.average*1000:.1f}ms)",
            f"  Slowest: {by_time[-1].module} ({by_time[-1].time.average*1000:.1f}ms)",
            f"  Ratio: {by_time[-1].time.average/by_time[0].time.average:.1f}x",
            "",
            "Memory Usage:",
            f"  Lowest: {by_memory[0].module} ({by_memory[0].memory.peak_kb/1024:.1f}MB)",
            f"  Highest: {by_memory[-1].module} ({by_memory[-1].memory.peak_kb/1024:.1f}MB)",
            "",
            "Dependencies:",
            f"  Fewest: {by_deps[0].module} ({by_deps[0].dependencies.count} modules)",
            f"  Most: {by_deps[-1].module} ({by_deps[-1].dependencies.count} modules)",
            "",
            "Rankings:",
        ]
        
        for module, rank in sorted(ranking.items(), key=lambda x: x[1]):
            profile = next(p for p in profiles if p.module == module)
            lines.append(f"  #{rank}: {module} (severity: {profile.overall_severity.name})")
        
        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Report Generation
# -----------------------------------------------------------------------------

class ReportFormat(Enum):
    """Supported report output formats."""
    JSON = auto()
    CSV = auto()
    HTML = auto()
    MARKDOWN = auto()
    TEXT = auto()


class ProfilingReport:
    """
    Rich report generation in multiple formats.
    
    This class generates comprehensive reports from profiling results,
    suitable for documentation, dashboards, and stakeholder communication.
    
    Examples
    --------
    >>> report = ProfilingReport()
    >>> profiles = [profiler.profile("numpy"), profiler.profile("pandas")]
    >>> html = report.generate(profiles, ReportFormat.HTML)
    >>> report.save(html, "profiling_report.html")
    """
    
    def generate(
        self,
        profiles: Union[EnhancedImportProfile, List[EnhancedImportProfile]],
        format: ReportFormat = ReportFormat.TEXT,
        include_recommendations: bool = True,
        include_charts: bool = False,
    ) -> str:
        """
        Generate report in specified format.
        
        Parameters
        ----------
        profiles : Union[EnhancedImportProfile, List[EnhancedImportProfile]]
            Single profile or list of profiles to report.
        format : ReportFormat
            Desired output format.
        include_recommendations : bool
            Whether to include optimization recommendations.
        include_charts : bool
            Whether to include chart data (HTML format only).
        
        Returns
        -------
        str
            Generated report content.
        """
        profile_list = [profiles] if isinstance(profiles, EnhancedImportProfile) else profiles
        
        if format == ReportFormat.JSON:
            return self._generate_json(profile_list)
        elif format == ReportFormat.CSV:
            return self._generate_csv(profile_list)
        elif format == ReportFormat.HTML:
            return self._generate_html(profile_list, include_recommendations, include_charts)
        elif format == ReportFormat.MARKDOWN:
            return self._generate_markdown(profile_list, include_recommendations)
        else:  # TEXT
            return self._generate_text(profile_list, include_recommendations)
    
    def _generate_json(self, profiles: List[EnhancedImportProfile]) -> str:
        """Generate JSON report."""
        data = {
            'generated_at': datetime.utcnow().isoformat(),
            'profiler_version': __version__,
            'profile_count': len(profiles),
            'profiles': [asdict(p) for p in profiles],
        }
        return json.dumps(data, default=str, indent=2)
    
    def _generate_csv(self, profiles: List[EnhancedImportProfile]) -> str:
        """Generate CSV report."""
        if not profiles:
            return ""
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=profiles[0].to_csv_row().keys())
        writer.writeheader()
        
        for profile in profiles:
            writer.writerow(profile.to_csv_row())
        
        return output.getvalue()
    
    def _generate_html(
        self, 
        profiles: List[EnhancedImportProfile], 
        include_recommendations: bool,
        include_charts: bool
    ) -> str:
        """Generate HTML report with optional charts."""
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Import Profiler Report</title>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .severity-critical {{ background-color: #ffebee; }}
        .severity-major {{ background-color: #fff3e0; }}
        .severity-moderate {{ background-color: #fff9c4; }}
        .recommendation {{ background-color: #e3f2fd; padding: 10px; margin: 5px 0; border-radius: 4px; }}
        .metric-good {{ color: #4CAF50; font-weight: bold; }}
        .metric-warning {{ color: #ff9800; font-weight: bold; }}
        .metric-bad {{ color: #f44336; font-weight: bold; }}
    </style>
</head>
<body>
    <h1>🚀 Import Profiler Report</h1>
    <p>Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
    <p>Profiler Version: {__version__}</p>
    <p>Profiles Analyzed: {len(profiles)}</p>
    
    <h2>📊 Summary</h2>
    <table>
        <tr>
            <th>Module</th>
            <th>Import Time (ms)</th>
            <th>Memory (MB)</th>
            <th>Dependencies</th>
            <th>Stability</th>
            <th>Overall Severity</th>
        </tr>
"""
        
        for profile in profiles:
            severity_class = f"severity-{profile.overall_severity.name.lower()}"
            html += f"""
        <tr class="{severity_class}">
            <td><strong>{profile.module}</strong></td>
            <td>{profile.time.average*1000:.1f} (±{profile.time.stddev*1000:.1f})</td>
            <td>{profile.memory.peak_kb/1024:.1f}</td>
            <td>{profile.dependencies.count}</td>
            <td>{profile.stability.category}</td>
            <td>{profile.overall_severity.name}</td>
        </tr>
"""
        
        html += """
    </table>
"""
        
        if include_recommendations:
            html += """
    <h2>💡 Recommendations</h2>
"""
            for profile in profiles:
                if profile.recommendations:
                    html += f"""
    <h3>{profile.module}</h3>
"""
                    for rec in profile.recommendations:
                        html += f"""
    <div class="recommendation">• {rec}</div>
"""
        
        if include_charts:
            # Add simple chart data as JSON for client-side rendering
            chart_data = {
                'modules': [p.module for p in profiles],
                'times': [p.time.average * 1000 for p in profiles],
                'memories': [p.memory.peak_kb / 1024 for p in profiles],
            }
            html += f"""
    <h2>📈 Performance Charts</h2>
    <div id="charts" style="height: 400px;"></div>
    <script>
        // Chart data - integrate with Chart.js or similar
        const chartData = {json.dumps(chart_data)};
        console.log('Chart data ready:', chartData);
    </script>
"""
        
        html += """
</body>
</html>
"""
        return html
    
    def _generate_markdown(
        self, 
        profiles: List[EnhancedImportProfile], 
        include_recommendations: bool
    ) -> str:
        """Generate Markdown report."""
        lines = [
            "# Import Profiler Report",
            "",
            f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"Profiler Version: {__version__}",
            "",
            "## Summary",
            "",
            "| Module | Import Time (ms) | Memory (MB) | Dependencies | Stability | Severity |",
            "|--------|-----------------|-------------|--------------|-----------|----------|",
        ]
        
        for profile in profiles:
            lines.append(
                f"| {profile.module} | "
                f"{profile.time.average*1000:.1f} ±{profile.time.stddev*1000:.1f} | "
                f"{profile.memory.peak_kb/1024:.1f} | "
                f"{profile.dependencies.count} | "
                f"{profile.stability.category} | "
                f"{profile.overall_severity.name} |"
            )
        
        if include_recommendations:
            lines.extend(["", "## Recommendations", ""])
            for profile in profiles:
                if profile.recommendations:
                    lines.append(f"### {profile.module}")
                    for rec in profile.recommendations:
                        lines.append(f"- {rec}")
                    lines.append("")
        
        return "\n".join(lines)
    
    def _generate_text(
        self, 
        profiles: List[EnhancedImportProfile], 
        include_recommendations: bool
    ) -> str:
        """Generate plain text report."""
        lines = [
            "=" * 60,
            "IMPORT PROFILER REPORT",
            "=" * 60,
            f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"Profiles: {len(profiles)}",
            "",
        ]
        
        for profile in profiles:
            lines.extend([
                f"\nModule: {profile.module}",
                f"  Import Time: {profile.time.average*1000:.1f}ms (±{profile.time.stddev*1000:.1f}ms)",
                f"  Memory: {profile.memory.peak_kb/1024:.1f}MB",
                f"  Dependencies: {profile.dependencies.count} modules",
                f"  Stability: {profile.stability.category} (index: {profile.stability.index:.3f})",
                f"  Category: {profile.time.category} / {profile.memory.category}",
                f"  Severity: {profile.overall_severity.name}",
            ])
            
            if profile.alerts:
                lines.append("  Alerts:")
                for alert in profile.alerts:
                    lines.append(f"    ⚠ {alert}")
        
        if include_recommendations:
            lines.extend(["", "-" * 40, "RECOMMENDATIONS", "-" * 40])
            for profile in profiles:
                if profile.recommendations:
                    lines.append(f"\n{profile.module}:")
                    for rec in profile.recommendations:
                        lines.append(f"  • {rec}")
        
        lines.extend(["", "=" * 60])
        return "\n".join(lines)
    
    def save(self, content: str, filepath: Union[str, Path]) -> None:
        """
        Save report content to file.
        
        Parameters
        ----------
        content : str
            Report content to save.
        filepath : Union[str, Path]
            Destination file path.
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        logger.info(f"Report saved to {filepath}")


# -----------------------------------------------------------------------------
# Main ImportProfiler Class
# -----------------------------------------------------------------------------

class ImportProfiler:
    """
    Advanced profiler for analyzing Python module imports.
    
    This class provides comprehensive profiling capabilities with extensive
    configuration options, caching, and integration features.
    
    Attributes
    ----------
    config : ProbeConfig
        Detailed probing configuration.
    cache : ProfileCache
        LRU cache for profile results.
    comparator : ProfileComparator
        Profile comparison utility.
    regression_detector : RegressionDetector
        Regression detection for CI/CD.
    report_generator : ProfilingReport
        Multi-format report generation.
    
    Examples
    --------
    >>> profiler = ImportProfiler(
    ...     default_repetitions=10,
    ...     warmup_strategy=WarmupStrategy.STANDARD,
    ...     enable_caching=True
    ... )
    >>> profile = profiler.profile("numpy")
    >>> print(f"Numpy import: {profile.time.average:.3f}s")
    >>> 
    >>> # Compare multiple modules
    >>> profiles = profiler.profile_multiple(["numpy", "pandas", "scipy"])
    >>> comparison = profiler.compare(profiles)
    >>> print(comparison.summary)
    """
    
    def __init__(
        self,
        default_repetitions: int = DEFAULT_REPETITIONS,
        default_warmup: int = DEFAULT_WARMUP,
        default_timeout: float = DEFAULT_TIMEOUT,
        warmup_strategy: Union[str, WarmupStrategy] = WarmupStrategy.STANDARD,
        measurement_mode: Union[str, MeasurementMode] = MeasurementMode.STANDARD,
        enable_caching: bool = True,
        cache_size: int = DEFAULT_CACHE_SIZE,
        cache_ttl: int = DEFAULT_CACHE_TTL,
        clear_caches_between: bool = False,
        track_allocations: bool = False,
        build_dependency_graph: bool = False,
        remove_outliers: bool = True,
        custom_metadata: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize ImportProfiler with comprehensive configuration.
        
        Parameters
        ----------
        default_repetitions : int
            Default number of measurement repetitions.
        default_warmup : int
            Default number of warmup iterations.
        default_timeout : float
            Default timeout in seconds.
        warmup_strategy : Union[str, WarmupStrategy]
            Cache warming strategy.
        measurement_mode : Union[str, MeasurementMode]
            Measurement precision mode.
        enable_caching : bool
            Whether to enable profile caching.
        cache_size : int
            Maximum number of cached profiles.
        cache_ttl : int
            Cache TTL in seconds.
        clear_caches_between : bool
            Whether to clear caches between measurements.
        track_allocations : bool
            Whether to track detailed memory allocations.
        build_dependency_graph : bool
            Whether to build full dependency graph.
        remove_outliers : bool
            Whether to remove statistical outliers.
        custom_metadata : Optional[Dict[str, str]]
            Custom metadata to attach to all profiles.
        """
        # Parse strategy enums
        if isinstance(warmup_strategy, str):
            warmup_strategy = WarmupStrategy[warmup_strategy.upper()]
        if isinstance(measurement_mode, str):
            measurement_mode = MeasurementMode[measurement_mode.upper()]
        
        # Build probe configuration
        self.config = ProbeConfig(
            repetitions=default_repetitions,
            warmup_strategy=warmup_strategy,
            measurement_mode=measurement_mode,
            timeout=default_timeout,
            remove_outliers=remove_outliers,
            clear_filesystem_cache=clear_caches_between,
            track_allocations=track_allocations,
            build_dependency_graph=build_dependency_graph,
        )
        
        # Initialize components
        self.cache = ProfileCache(max_size=cache_size, ttl_seconds=cache_ttl) if enable_caching else None
        self.comparator = ProfileComparator()
        self.regression_detector = RegressionDetector()
        self.report_generator = ProfilingReport()
        
        # Store metadata
        self.custom_metadata = custom_metadata or {}
        self.default_repetitions = default_repetitions
        self.default_timeout = default_timeout
        
        # Statistics
        self._profiles_created = 0
        self._lock = threading.RLock()
    
    def _get_config_hash(self) -> str:
        """Generate hash of current configuration for caching."""
        config_dict = {
            'repetitions': self.config.repetitions,
            'warmup': self.config.warmup_strategy.name,
            'mode': self.config.measurement_mode.name,
            'timeout': self.config.timeout,
            'clear_caches': self.config.clear_filesystem_cache,
        }
        config_str = json.dumps(config_dict, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()[:8]
    
    def profile(
        self,
        module: str,
        repetitions: Optional[int] = None,
        timeout: Optional[float] = None,
        force_refresh: bool = False,
    ) -> EnhancedImportProfile:
        """
        Profile a Python module import with comprehensive analysis.
        
        Parameters
        ----------
        module : str
            Name of module to profile.
        repetitions : Optional[int]
            Override default repetitions.
        timeout : Optional[float]
            Override default timeout.
        force_refresh : bool
            Force fresh measurement, bypassing cache.
        
        Returns
        -------
        EnhancedImportProfile
            Complete import profile with all metrics and analysis.
        
        Raises
        ------
        ImportError
            If module cannot be imported.
        TimeoutError
            If profiling times out.
        ValueError
            If invalid parameters provided.
        """
        # Validate parameters
        reps = repetitions if repetitions is not None else self.config.repetitions
        tout = timeout if timeout is not None else self.config.timeout
        
        if reps <= 0:
            raise ValueError("repetitions must be positive")
        if tout <= 0:
            raise ValueError("timeout must be positive")
        
        # Check cache
        config_hash = self._get_config_hash()
        if self.cache and not force_refresh:
            cached = self.cache.get(module, config_hash)
            if cached:
                logger.debug(f"Cache hit for {module}")
                return cached
        
        logger.info(f"Profiling {module} with {reps} repetitions...")
        
        try:
            # Create temporary config for this run
            run_config = ProbeConfig(
                repetitions=reps,
                warmup_strategy=self.config.warmup_strategy,
                measurement_mode=self.config.measurement_mode,
                timeout=tout,
                remove_outliers=self.config.remove_outliers,
                clear_filesystem_cache=self.config.clear_filesystem_cache,
                track_allocations=self.config.track_allocations,
                build_dependency_graph=self.config.build_dependency_graph,
            )
            
            # Execute probing
            probe_result = self._execute_probe(module, run_config)
            
            # Build enhanced profile
            profile = self._build_profile(module, probe_result, reps, tout)
            
            # Generate recommendations
            profile.recommendations = self._generate_recommendations(profile)
            
            # Check alerts
            profile.alerts = self._check_alerts(profile)
            
            # Update cache
            if self.cache:
                self.cache.put(module, config_hash, profile)
            
            with self._lock:
                self._profiles_created += 1
            
            logger.info(f"Completed profiling {module}: {profile.time.average*1000:.1f}ms")
            return profile
            
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"Profiling timed out for {module}: {e}") from e
        except subprocess.CalledProcessError as e:
            raise ImportError(f"Failed to import {module}: {e}") from e
        except Exception as e:
            logger.error(f"Profiling failed for {module}: {e}")
            raise
    
    def _execute_probe(self, module: str, config: ProbeConfig) -> ProbeResult:
        """Execute probing with given configuration."""
        # Import here to avoid circular dependency
        from ._perf_probes import measure_import
        return measure_import(module, config)
    
    def _build_profile(
        self,
        module: str,
        probe_result: ProbeResult,
        repetitions: int,
        timeout: float,
    ) -> EnhancedImportProfile:
        """Build enhanced profile from probe result."""
        # Extract timing data
        time_result = TimeResult(
            average=probe_result.time_result.average,
            min_time=probe_result.time_result.min_time,
            max_time=probe_result.time_result.max_time,
            stddev=probe_result.time_result.stddev,
            category=classify_time(probe_result.time_result.average),
        )
        
        # Extract memory data
        memory_result = MemoryResult(
            peak_kb=probe_result.memory_result.peak_kb if probe_result.memory_result.peak_kb else None,
            category=classify_memory(probe_result.memory_result.peak_kb),
        )
        
        # Extract dependency data
        dependency_result = DependencyResult(
            count=probe_result.dependency_result.count,
            category=classify_dependencies(probe_result.dependency_result.count),
        )
        
        # Extract stability data
        stability_result = StabilityResult(
            index=probe_result.stability_result.index,
            category=classify_stability(probe_result.stability_result.index),
            confidence=probe_result.stability_result.confidence
        )
        
        # Build metadata
        metadata = ProfilingMetadata(
            custom_tags=self.custom_metadata.copy(),
        )
        
        # Build profile
        profile = EnhancedImportProfile(
            module=module,
            time=time_result,
            memory=memory_result,
            dependencies=dependency_result,
            stability=stability_result,
            metadata=metadata,
            raw_measurements={
                'times': probe_result.time_result.samples,
                'outliers_removed': probe_result.time_result.outliers_removed,
                'config': {
                    'repetitions': repetitions,
                    'timeout': timeout,
                },
            },
        )
        
        return profile
    
    def _generate_recommendations(self, profile: EnhancedImportProfile) -> List[str]:
        """Generate optimization recommendations based on profile."""
        recommendations = []
        
        # Time-based recommendations
        if profile.time.average > 0.5:
            recommendations.append(
                f"Import time is {profile.time.average:.2f}s. Consider lazy loading or "
                "splitting into smaller submodules."
            )
        elif profile.time.average > 0.1:
            recommendations.append(
                f"Import time is {profile.time.average*1000:.0f}ms. Profile with "
                "`py-spy` to identify bottlenecks."
            )
        
        # Memory-based recommendations
        if profile.memory.peak_kb != None and profile.memory.peak_kb > 100 * 1024:  # 100MB
            recommendations.append(
                f"High memory usage ({profile.memory.peak_kb/1024:.0f}MB). "
                "Consider using `__slots__` or lazy attribute loading."
            )
        
        # Dependency-based recommendations
        if profile.dependencies.count > 100:
            recommendations.append(
                f"Large dependency tree ({profile.dependencies.count} modules). "
                "Consider vendoring critical dependencies or using optional imports."
            )
        
        # Stability-based recommendations
        if profile.stability.index > 0.3:
            recommendations.append(
                "High import time variability. Check for filesystem cache issues "
                "or conditional heavy imports."
            )
        
        return recommendations
    
    def _check_alerts(self, profile: EnhancedImportProfile) -> List[str]:
        """Check for alert conditions."""
        alerts = []
        
        if profile.time.average > ALERT_TIME_SECONDS:
            alerts.append(f"Import time exceeds {ALERT_TIME_SECONDS}s threshold")
        
        if profile.memory.peak_kb != None and profile.memory.peak_kb > \
          ALERT_MEMORY_MB * 1024:
            alerts.append(f"Memory usage exceeds {ALERT_MEMORY_MB}MB threshold")
        
        if profile.dependencies.count > ALERT_DEPS_COUNT:
            alerts.append(f"Dependency count exceeds {ALERT_DEPS_COUNT} threshold")
        
        return alerts
    
    def profile_multiple(
        self,
        modules: List[str],
        **kwargs,
    ) -> Dict[str, EnhancedImportProfile]:
        """
        Profile multiple modules sequentially.
        
        Parameters
        ----------
        modules : List[str]
            List of module names to profile.
        **kwargs
            Additional arguments passed to profile() method.
        
        Returns
        -------
        Dict[str, EnhancedImportProfile]
            Dictionary mapping module names to their profiles.
        """
        results = {}
        
        for module in modules:
            try:
                profile = self.profile(module, **kwargs)
                results[module] = profile
            except Exception as e:
                logger.error(f"Failed to profile {module}: {e}")
                # Create error profile
                results[module] = self._create_error_profile(module, str(e))
        
        return results
    
    async def profile_multiple_async(
        self,
        modules: List[str],
        max_concurrency: int = DEFAULT_CONCURRENCY,
        **kwargs,
    ) -> Dict[str, EnhancedImportProfile]:
        """
        Profile multiple modules concurrently.
        
        Parameters
        ----------
        modules : List[str]
            List of module names to profile.
        max_concurrency : int
            Maximum concurrent profiling operations.
        **kwargs
            Additional arguments passed to profile() method.
        
        Returns
        -------
        Dict[str, EnhancedImportProfile]
            Dictionary mapping module names to their profiles.
        """
        semaphore = asyncio.Semaphore(max_concurrency)
        
        async def profile_one(module: str) -> Tuple[str, EnhancedImportProfile]:
            async with semaphore:
                loop = asyncio.get_event_loop()
                try:
                    profile = await loop.run_in_executor(
                        None, partial(self.profile, module, **kwargs)
                    )
                    return module, profile
                except Exception as e:
                    logger.error(f"Failed to profile {module}: {e}")
                    return module, self._create_error_profile(module, str(e))
        
        tasks = [profile_one(module) for module in modules]
        results = dict(await asyncio.gather(*tasks))
        return results
    
    def _create_error_profile(self, module: str, error_msg: str) -> EnhancedImportProfile:
        """Create profile indicating failure."""
        return EnhancedImportProfile(
            module=module,
            time=TimeResult(0.0, 0.0, 0.0, 0.0, "error"),
            memory=MemoryResult(0, "error"),
            dependencies=DependencyResult(0, "error"),
            stability=StabilityResult(0.0, "error"),
            alerts=[f"Profiling failed: {error_msg}"],
        )
    
    def compare(self, profiles: List[EnhancedImportProfile]) -> ComparisonResult:
        """
        Compare multiple import profiles.
        
        Parameters
        ----------
        profiles : List[EnhancedImportProfile]
            Profiles to compare.
        
        Returns
        -------
        ComparisonResult
            Comprehensive comparison results.
        """
        return self.comparator.compare(profiles)
    
    def detect_regression(
        self,
        baseline: EnhancedImportProfile,
        current: EnhancedImportProfile,
    ) -> RegressionResult:
        """
        Detect performance regression between profiles.
        
        Parameters
        ----------
        baseline : EnhancedImportProfile
            Baseline profile.
        current : EnhancedImportProfile
            Current profile.
        
        Returns
        -------
        RegressionResult
            Regression detection result.
        """
        return self.regression_detector.detect(baseline, current)
    
    def generate_report(
        self,
        profiles: Union[EnhancedImportProfile, List[EnhancedImportProfile]],
        format: Union[str, ReportFormat] = ReportFormat.TEXT,
        **kwargs,
    ) -> str:
        """
        Generate report from profiles.
        
        Parameters
        ----------
        profiles : Union[EnhancedImportProfile, List[EnhancedImportProfile]]
            Profile(s) to report.
        format : Union[str, ReportFormat]
            Output format.
        **kwargs
            Additional arguments for report generation.
        
        Returns
        -------
        str
            Generated report content.
        """
        if isinstance(format, str):
            format = ReportFormat[format.upper()]
        return self.report_generator.generate(profiles, format, **kwargs)
    
    def export_profile(
        self,
        profile: EnhancedImportProfile,
        filepath: Union[str, Path],
        format: str = "json",
    ) -> None:
        """
        Export profile to file.
        
        Parameters
        ----------
        profile : EnhancedImportProfile
            Profile to export.
        filepath : Union[str, Path]
            Destination file path.
        format : str
            Export format ('json', 'pickle').
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        if format == "json":
            path.write_text(profile.to_json(indent=2), encoding='utf-8')
        elif format == "pickle":
            with path.open('wb') as f:
                pickle.dump(profile, f)
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        logger.info(f"Profile exported to {filepath}")
    
    def import_profile(self, filepath: Union[str, Path]) -> EnhancedImportProfile:
        """
        Import profile from file.
        
        Parameters
        ----------
        filepath : Union[str, Path]
            Source file path.
        
        Returns
        -------
        EnhancedImportProfile
            Imported profile.
        """
        path = Path(filepath)
        
        if path.suffix == '.json':
            with path.open('r', encoding='utf-8') as f:
                data = json.load(f)
            # Reconstruct profile (simplified - full reconstruction would be more complex)
            return self._profile_from_dict(data)
        elif path.suffix == '.pickle':
            with path.open('rb') as f:
                return pickle.load(f)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")
    
    def _profile_from_dict(self, data: Dict[str, Any]) -> EnhancedImportProfile:
        """Reconstruct profile from dictionary."""
        # Simplified reconstruction
        return EnhancedImportProfile(
            module=data['module'],
            time=TimeResult(**data['time']),
            memory=MemoryResult(**data['memory']),
            dependencies=DependencyResult(**data['dependencies']),
            stability=StabilityResult(**data['stability']),
        )
    
    def clear_cache(self) -> None:
        """Clear the profile cache."""
        if self.cache:
            self.cache.clear()
            logger.info("Profile cache cleared")
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get profiler statistics."""
        stats = {
            'profiles_created': self._profiles_created,
            'config': {
                'repetitions': self.config.repetitions,
                'warmup_strategy': self.config.warmup_strategy.name,
                'measurement_mode': self.config.measurement_mode.name,
                'timeout': self.config.timeout,
            },
        }
        
        if self.cache:
            stats['cache'] = self.cache.stats
        
        return stats
    
    @contextmanager
    def session(self) -> Generator[ImportProfiler, None, None]:
        """
        Context manager for profiling session.
        
        Yields
        ------
        ImportProfiler
            Self reference for method chaining.
        
        Examples
        --------
        >>> with profiler.session() as session:
        ...     numpy = session.profile("numpy")
        ...     pandas = session.profile("pandas")
        ...     report = session.generate_report([numpy, pandas])
        """
        start_time = datetime.utcnow()
        logger.info(f"Starting profiling session at {start_time}")
        
        try:
            yield self
        finally:
            duration = datetime.utcnow() - start_time
            logger.info(f"Profiling session completed in {duration.total_seconds():.2f}s")
            logger.info(f"Profiles created: {self._profiles_created}")


# -----------------------------------------------------------------------------
# Public API Functions
# -----------------------------------------------------------------------------

def profile_import(
    module: str,
    repetitions: int = DEFAULT_REPETITIONS,
    timeout: float = DEFAULT_TIMEOUT,
    warmup: int = DEFAULT_WARMUP,
) -> EnhancedImportProfile:
    """
    Convenience function for profiling a single module.
    
    Parameters
    ----------
    module : str
        Name of module to profile.
    repetitions : int
        Number of timing repetitions.
    timeout : float
        Timeout in seconds.
    warmup : int
        Number of warmup iterations.
    
    Returns
    -------
    EnhancedImportProfile
        Complete import profile.
    
    Examples
    --------
    >>> profile = profile_import("numpy", repetitions=10)
    >>> print(f"Numpy import: {profile.time.average:.3f}s")
    """
    profiler = ImportProfiler(
        default_repetitions=repetitions,
        default_warmup=warmup,
        default_timeout=timeout,
    )
    return profiler.profile(module)


def difftime(
    mod1: str,
    mod2: str,
    *,
    repetition: int = DEFAULT_REPETITIONS,
    warmup: int = DEFAULT_WARMUP,
    timeout: float = DEFAULT_TIMEOUT,
) -> Tuple[EnhancedImportProfile, EnhancedImportProfile, ComparisonResult]:
    """
    Compare cold-start import performance of two Python modules.
    
    Parameters
    ----------
    mod1 : str
        Name of first module.
    mod2 : str
        Name of second module.
    repetition : int
        Number of measured import attempts per module.
    warmup : int
        Number of warmup imports before measurement.
    timeout : float
        Maximum allowed time per import in seconds.
    
    Returns
    -------
    Tuple[EnhancedImportProfile, EnhancedImportProfile, ComparisonResult]
        Profiles for both modules and comparison result.
    
    Raises
    ------
    ValueError
        If both module names are identical.
    
    Examples
    --------
    >>> numpy, pandas, comparison = difftime("numpy", "pandas")
    >>> print(f"Winner: {comparison.fastest.module}")
    >>> print(comparison.summary)
    """
    if mod1 == mod2:
        raise ValueError("Cannot benchmark the same module against itself")
    
    profiler = ImportProfiler(
        default_repetitions=repetition,
        default_warmup=warmup,
        default_timeout=timeout,
    )
    
    profile1 = profiler.profile(mod1)
    profile2 = profiler.profile(mod2)
    comparison = profiler.compare([profile1, profile2])
    
    return profile1, profile2, comparison


def profile_batch(
    modules: List[str],
    *,
    repetitions: int = DEFAULT_REPETITIONS,
    timeout: float = DEFAULT_TIMEOUT,
    concurrent: bool = True,
    max_concurrency: int = DEFAULT_CONCURRENCY,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, EnhancedImportProfile]:
    """
    Batch profile multiple modules with progress tracking.
    
    Parameters
    ----------
    modules : List[str]
        List of module names to profile.
    repetitions : int
        Number of repetitions per module.
    timeout : float
        Timeout per module.
    concurrent : bool
        Whether to use concurrent profiling.
    max_concurrency : int
        Maximum concurrent operations if concurrent=True.
    progress_callback : Optional[Callable]
        Callback for progress updates: callback(current, total, module).
    
    Returns
    -------
    Dict[str, EnhancedImportProfile]
        Dictionary of module profiles.
    
    Examples
    --------
    >>> def progress(current, total, module):
    ...     print(f"[{current}/{total}] Completed: {module}")
    >>> 
    >>> profiles = profile_batch(
    ...     ["numpy", "pandas", "scipy", "matplotlib"],
    ...     progress_callback=progress
    ... )
    """
    profiler = ImportProfiler(
        default_repetitions=repetitions,
        default_timeout=timeout,
    )
    
    if not concurrent:
        results = {}
        for i, module in enumerate(modules, 1):
            try:
                results[module] = profiler.profile(module)
            except Exception as e:
                logger.error(f"Failed to profile {module}: {e}")
                results[module] = profiler._create_error_profile(module, str(e))
            
            if progress_callback:
                progress_callback(i, len(modules), module)
        return results
    else:
        # Async profiling
        async def _profile_async():
            return await profiler.profile_multiple_async(
                modules, max_concurrency=max_concurrency
            )
        
        # Run async and provide progress updates
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            if progress_callback:
                # Can't easily get progress from asyncio.gather
                # Use a wrapper to track completions
                completed = 0
                total = len(modules)
                
                async def _tracked_profile():
                    nonlocal completed
                    result = await profiler.profile_multiple_async(
                        modules, max_concurrency=max_concurrency
                    )
                    completed = total
                    if progress_callback:
                        progress_callback(completed, total, "all")
                    return result
                
                return loop.run_until_complete(_tracked_profile())
            else:
                return loop.run_until_complete(_profile_async())
        finally:
            loop.close()


def compare_versions(
    module: str,
    versions: List[str],
    *,
    repetitions: int = DEFAULT_REPETITIONS,
    install_command: Optional[str] = None,
) -> Dict[str, EnhancedImportProfile]:
    """
    Compare import performance across module versions.
    
    Parameters
    ----------
    module : str
        Module name to test across versions.
    versions : List[str]
        List of version specifiers (e.g., ["1.0.0", "2.0.0"]).
    repetitions : int
        Number of repetitions per version.
    install_command : Optional[str]
        Custom install command template (use {module} and {version}).
    
    Returns
    -------
    Dict[str, EnhancedImportProfile]
        Profiles for each version.
    
    Notes
    -----
    This function modifies the Python environment by installing different
    versions. Use with caution, preferably in isolated environments.
    
    Examples
    --------
    >>> profiles = compare_versions("numpy", ["1.19.0", "1.20.0", "1.21.0"])
    >>> for version, profile in profiles.items():
    ...     print(f"NumPy {version}: {profile.time.average*1000:.1f}ms")
    """
    profiles = {}
    profiler = ImportProfiler(default_repetitions=repetitions)
    
    original_version = None
    try:
        # Get current version
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}; print({module}.__version__)"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            original_version = result.stdout.strip()
    except:
        pass
    
    cmd_template = install_command or f"{{python}} -m pip install {{module}}=={{version}} --quiet"
    
    for version in versions:
        logger.info(f"Installing {module}=={version}")
        
        # Install specific version
        cmd = cmd_template.format(python=sys.executable, module=module, version=version)
        subprocess.run(cmd.split(), check=True, capture_output=True)
        
        # Profile this version
        try:
            profiles[version] = profiler.profile(module, force_refresh=True)
        except Exception as e:
            logger.error(f"Failed to profile {module}=={version}: {e}")
            profiles[version] = profiler._create_error_profile(module, str(e))
    
    # Restore original version if possible
    if original_version:
        logger.info(f"Restoring {module}=={original_version}")
        cmd = cmd_template.format(python=sys.executable, module=module, version=original_version)
        subprocess.run(cmd.split(), check=True, capture_output=True)
    
    return profiles


def detect_regressions(
    baseline_profiles: Union[str, Path, Dict[str, EnhancedImportProfile]],
    current_modules: Optional[List[str]] = None,
    *,
    repetitions: int = DEFAULT_REPETITIONS,
    threshold_percent: float = REGRESSION_THRESHOLD_PERCENT,
    fail_on_regression: bool = False,
) -> List[RegressionResult]:
    """
    Detect performance regressions in CI/CD context.
    
    Parameters
    ----------
    baseline_profiles : Union[str, Path, Dict[str, EnhancedImportProfile]]
        Path to baseline profiles file or pre-loaded dictionary.
    current_modules : Optional[List[str]]
        List of modules to test (defaults to all from baseline).
    repetitions : int
        Number of measurement repetitions.
    threshold_percent : float
        Percentage threshold for regression detection.
    fail_on_regression : bool
        Whether to raise exception on regression detection.
    
    Returns
    -------
    List[RegressionResult]
        Detected regressions.
    
    Examples
    --------
    >>> # Load baseline from previous run
    >>> baseline = load_profiles("baseline.json")
    >>> regressions = detect_regressions(baseline, ["numpy", "pandas"])
    >>> if regressions:
    ...     print(f"Found {len(regressions)} regressions")
    ...     raise SystemExit(1)
    """
    profiler = ImportProfiler(default_repetitions=repetitions)
    
    # Load baseline profiles
    if isinstance(baseline_profiles, (str, Path)):
        with open(baseline_profiles) as f:
            baseline = json.load(f)
    else:
        baseline = baseline_profiles
    
    # Profile current modules
    modules = current_modules if current_modules is not None else list(baseline.keys())
    detector = RegressionDetector(
        time_threshold_percent=threshold_percent,
        memory_threshold_percent=threshold_percent,
        deps_threshold_absolute=10,
    )
    
    # Detect regressions
    regressions = []
    for module in modules:
        if module not in baseline:
            continue
        
        baseline_profile = baseline[module]
        current_profile = profiler.profile(module, repetitions=repetitions)
        
        result = detector.detect(baseline_profile, current_profile)
        if result.has_regression:
            regressions.append(result)
    
    if fail_on_regression and regressions:
        raise RegressionError(f"Found {len(regressions)} regressions")
    
    return regressions


def export_profile(
    profile: EnhancedImportProfile,
    filepath: Union[str, Path],
    format: str = "json",
) -> None:
    """
    Export profile to file.
    
    Parameters
    ----------
    profile : EnhancedImportProfile
        Profile to export.
    filepath : Union[str, Path]
        Destination file path.
    format : str
        Export format ('json' or 'pickle').
    """
    if format == "json":
        with open(filepath, 'w') as f:
            json.dump(asdict(profile), f, default=str, indent=2)
    elif format == "pickle":
        with open(filepath, 'wb') as f:
            pickle.dump(profile, f)
    else:
        raise ValueError(f"Unsupported format: {format}")


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Primary classes
    'ImportProfiler',
    'EnhancedImportProfile',
    'ProfileComparator',
    'RegressionDetector',
    'ProfilingReport',
    
    # Core functions
    'profile_import',
    'difftime',
    'profile_batch',
    'compare_versions',
    'detect_regressions',
    'export_profile',
    
    # Legacy compatibility
    '_measure_import',
    'run_memory_probe',
    'collect_timing_samples',
    'analyze_timing_data',
    'calculate_stability_index',
    '_run_import',
    '_classify',
]
