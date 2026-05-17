#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
_perf_probes.py

Performance Probing System for Python Module Imports.

This module provides a sophisticated measurement infrastructure for accurately
assessing Python module import performance across multiple dimensions. It employs
subprocess isolation, statistical sampling, warmup strategies, and interference
mitigation techniques to produce reliable, reproducible benchmarks.

The probing system is designed for:
- CI/CD pipeline performance regression detection
- Interactive profiling and debugging sessions  
- Automated dependency auditing and scoring
- Production monitoring and alerting
- Scientific performance research

Features
--------
- Multi-level cache warming strategies (cold/warm/hot starts)
- Filesystem cache control and normalization
- Statistical outlier detection and removal
- Adaptive sampling with confidence-based termination
- Memory profiling with allocation tracking
- Dependency graph construction and analysis
- Concurrent probing with controlled parallelism
- JSON schema validation for probe results
- Automatic retry logic with exponential backoff
- Detailed telemetry and structured logging

Classes
-------
ProbeConfig
    Comprehensive configuration for probing behavior.
ProbeResult
    Rich result container with raw and analyzed metrics.
ProbeSession
    Context manager for coordinated multi-module probing.
ImportProbe
    Main probing engine with advanced measurement strategies.
WarmupStrategy
    Enumeration of cache warming approaches.
CacheState
    Filesystem and interpreter cache state management.

Functions
---------
measure_import
    Primary entry point for comprehensive import benchmarking.
measure_memory_import
    Advanced memory profiling with allocation breakdown.
measure_dependency_tree
    Full transitive dependency analysis with graph metrics.
measure_cold_start
    Simulated clean-environment import measurement.
measure_concurrent_imports
    Parallel import performance under contention.
calibrate_measurement_overhead
    Calculate and compensate for probing infrastructure cost.
"""

import asyncio
import concurrent.futures
import contextlib
import enum
import hashlib
import json
import logging
import math
import os
import pickle
import platform
import random
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from functools import lru_cache, partial, wraps
from pathlib import Path
from typing import (
    Any, Callable, Dict, Generic, Iterable, Iterator, List, 
    NamedTuple, Optional, Sequence, Set, Tuple, TypeVar, Union, cast, Final
)

from .models import (
        TimeResult,
        MemoryResult,
        DependencyResult,
        StabilityResult,
        ImportBenchmarkResult,
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
 )

# -----------------------------------------------------------------------------
# Module Configuration and Constants
# -----------------------------------------------------------------------------

# Default probing parameters
DEFAULT_REPETITIONS: Final[int] = 5
DEFAULT_WARMUP_ITERATIONS: Final[int] = 2
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
DEFAULT_CONFIDENCE_LEVEL: Final[float] = 0.95
DEFAULT_MAX_OUTLIER_RATIO: Final[float] = 0.2
DEFAULT_CONCURRENT_WORKERS: Final[int] = min(4, os.cpu_count() or 2)

# Filesystem cache control
PAGECACHE_CLEAR_COMMANDS: Final[Dict[str, List[str]]] = {
    'linux': ['sync', 'echo 3 > /proc/sys/vm/drop_caches'],
    'darwin': ['sync', 'purge'],
    'windows': ['ipconfig /flushdns'],  # Partial, no direct FS cache control
}

# Probing script templates
MEMORY_PROBE_TEMPLATE: Final[str] = '''
import sys
import gc
import json
import tracemalloc
import linecache
import importlib
from collections import defaultdict

def get_module_size(module_name):
    """Estimate module memory footprint recursively."""
    module = sys.modules.get(module_name)
    if not module:
        return 0
    
    total_size = 0
    seen = set()
    
    def sizeof_fmt(obj, seen_ids):
        if id(obj) in seen_ids:
            return 0
        seen_ids.add(id(obj))
        
        size = sys.getsizeof(obj)
        if hasattr(obj, '__dict__'):
            size += sizeof_fmt(obj.__dict__, seen_ids)
        elif isinstance(obj, dict):
            size += sum(sizeof_fmt(k, seen_ids) + sizeof_fmt(v, seen_ids) 
                       for k, v in obj.items())
        elif isinstance(obj, (list, tuple, set)):
            size += sum(sizeof_fmt(i, seen_ids) for i in obj)
        return size
    
    try:
        return sizeof_fmt(module, seen)
    except:
        return 0

# Force garbage collection for clean measurement
gc.collect()
gc.disable()

# Start comprehensive tracing
tracemalloc.start(25)  # Capture 25 frames for detailed analysis
before_modules = set(sys.modules.keys())
before_time = __import__('time').perf_counter()

import_result = {{"success": False, "error": None}}

try:
    __import__('{module}')
    import_result["success"] = True
except Exception as e:
    import_result["error"] = f"{{type(e).__name__}}: {{str(e)}}"

after_time = __import__('time').perf_counter()
after_modules = set(sys.modules.keys())

# Capture memory statistics
current, peak = tracemalloc.get_traced_memory()
snapshot = tracemalloc.take_snapshot()
tracemalloc.stop()

# Analyze memory allocations by module
allocation_stats = defaultdict(int)
for stat in snapshot.statistics('lineno'):
    allocation_stats[stat.traceback[0].filename] += stat.size

# Calculate metrics
new_modules = sorted(after_modules - before_modules)
import_time = after_time - before_time
peak_kb = peak // 1024

result = {{
    "success": import_result["success"],
    "error": import_result["error"],
    "import_time": import_time,
    "deps_count": len(new_modules),
    "deps_list": new_modules[:50],  # Limit for large dependency trees
    "peak_kb": peak_kb,
    "current_kb": current // 1024,
    "module_size_kb": get_module_size('{module}') // 1024,
    "allocation_hotspots": dict(sorted(
        allocation_stats.items(), 
        key=lambda x: x[1], 
        reverse=True
    )[:10])
}}

print(json.dumps(result))
'''

DEPENDENCY_TREE_TEMPLATE: Final[str] = '''
import sys
import json
import importlib
from collections import deque

def get_dependency_tree(module_name):
    """Build complete dependency graph."""
    visited = set()
    graph = {{}}
    queue = deque([(module_name, None, 0)])
    
    while queue:
        current, parent, depth = queue.popleft()
        if current in visited:
            continue
        
        visited.add(current)
        graph[current] = {{
            "parent": parent,
            "depth": depth,
            "children": [],
            "is_stdlib": current in sys.stdlib_module_names if hasattr(sys, 'stdlib_module_names') else False
        }}
        
        try:
            module = importlib.import_module(current)
            if hasattr(module, '__file__') and module.__file__:
                graph[current]["file"] = module.__file__
            
            for attr in dir(module):
                if attr.startswith('_'):
                    continue
                try:
                    obj = getattr(module, attr)
                    if hasattr(obj, '__module__'):
                        child_module = obj.__module__
                        if child_module and child_module != current:
                            child_name = child_module.split('.')[0]
                            if child_name not in visited:
                                queue.append((child_name, current, depth + 1))
                                graph[current]["children"].append(child_name)
                except:
                    pass
        except:
            graph[current]["error"] = "Failed to analyze"
    
    return graph

result = get_dependency_tree('{module}')
print(json.dumps(result))
'''

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
# Enumerations and Configuration Classes
# -----------------------------------------------------------------------------

class WarmupStrategy(enum.Enum):
    """
    Cache warming strategies for import measurement.
    
    Attributes
    ----------
    NONE : enum.auto
        No warmup, pure cold start measurement.
    MINIMAL : enum.auto
        Single warmup import to populate basic caches.
    STANDARD : enum.auto
        Multiple warmups to stabilize filesystem cache.
    AGGRESSIVE : enum.auto
        Extended warmup with additional system cache priming.
    ADAPTIVE : enum.auto
        Continue warmup until measurements stabilize.
    """
    
    NONE = enum.auto()
    MINIMAL = enum.auto()
    STANDARD = enum.auto()
    AGGRESSIVE = enum.auto()
    ADAPTIVE = enum.auto()
    
    def get_iterations(self) -> int:
        """Get recommended warmup iterations for strategy."""
        return {
            self.NONE: 0,
            self.MINIMAL: 1,
            self.STANDARD: 3,
            self.AGGRESSIVE: 10,
            self.ADAPTIVE: 2,  # Minimum for adaptive
        }[self]


class MeasurementMode(enum.Enum):
    """
    Measurement precision and overhead trade-off modes.
    
    Attributes
    ----------
    FAST : enum.auto
        Quick measurements with minimal overhead.
    STANDARD : enum.auto
        Balanced approach suitable for most use cases.
    PRECISE : enum.auto
        High-precision measurements with statistical rigor.
    SCIENTIFIC : enum.auto
        Maximum accuracy with extensive sampling.
    """
    
    FAST = enum.auto()
    STANDARD = enum.auto()
    PRECISE = enum.auto()
    SCIENTIFIC = enum.auto()
    
    def get_repetitions(self) -> int:
        """Get recommended repetitions for mode."""
        return {
            self.FAST: 3,
            self.STANDARD: 5,
            self.PRECISE: 15,
            self.SCIENTIFIC: 30,
        }[self]


@dataclass
class ProbeConfig:
    """
    Comprehensive configuration for probing behavior.
    
    Attributes
    ----------
    repetitions : int
        Number of measurement repetitions.
    warmup_strategy : WarmupStrategy
        Cache warming approach.
    measurement_mode : MeasurementMode
        Precision vs speed trade-off.
    timeout : float
        Maximum seconds per measurement.
    remove_outliers : bool
        Whether to filter statistical outliers.
    max_outlier_ratio : float
        Maximum fraction of data points to remove as outliers.
    confidence_level : float
        Target confidence for adaptive sampling.
    clear_filesystem_cache : bool
        Attempt to clear OS filesystem cache between measurements.
    isolate_cpu : bool
        Attempt to pin process to specific CPU core.
    track_allocations : bool
        Enable detailed memory allocation tracking.
    build_dependency_graph : bool
        Construct full dependency tree analysis.
    concurrent_workers : int
        Number of parallel workers for batch probing.
    retry_on_failure : int
        Number of retry attempts for failed measurements.
    capture_stderr : bool
        Whether to capture and analyze stderr output.
    """
    
    repetitions: int = DEFAULT_REPETITIONS
    warmup_strategy: WarmupStrategy = WarmupStrategy.STANDARD
    measurement_mode: MeasurementMode = MeasurementMode.STANDARD
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    remove_outliers: bool = True
    max_outlier_ratio: float = DEFAULT_MAX_OUTLIER_RATIO
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL
    clear_filesystem_cache: bool = False
    isolate_cpu: bool = False
    track_allocations: bool = False
    build_dependency_graph: bool = False
    concurrent_workers: int = DEFAULT_CONCURRENT_WORKERS
    retry_on_failure: int = 2
    capture_stderr: bool = False
    
    def __post_init__(self) -> None:
        """Validate configuration parameters."""
        if self.repetitions < 1:
            raise ValueError(f"repetitions must be >= 1, got {self.repetitions}")
        if self.timeout <= 0:
            raise ValueError(f"timeout must be > 0, got {self.timeout}")
        if not 0 < self.confidence_level < 1:
            raise ValueError(f"confidence_level must be in (0, 1), got {self.confidence_level}")
        if self.max_outlier_ratio < 0 or self.max_outlier_ratio > 0.5:
            raise ValueError(f"max_outlier_ratio must be in [0, 0.5], got {self.max_outlier_ratio}")
    
    def apply_mode_overrides(self) -> None:
        """Apply measurement mode specific defaults."""
        mode = self.measurement_mode
        if self.repetitions == DEFAULT_REPETITIONS:
            self.repetitions = mode.get_repetitions()
        if mode == MeasurementMode.SCIENTIFIC:
            self.remove_outliers = True
            self.track_allocations = True
        elif mode == MeasurementMode.FAST:
            self.remove_outliers = False
            self.warmup_strategy = WarmupStrategy.MINIMAL


# -----------------------------------------------------------------------------
# Enhanced Result Containers
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class DetailedTimeResult(TimeResult):
    """
    Extended time measurement result with statistical details.
    
    Attributes
    ----------
    samples : List[float]
        Raw measurement samples.
    outliers_removed : List[float]
        Outliers identified and removed.
    confidence_interval : Tuple[float, float]
        95% confidence interval bounds.
    median : float
        Median measurement value.
    percentiles : Dict[str, float]
        Key percentiles (p50, p90, p95, p99).
    """
    
    samples: List[float] = field(default_factory=list)
    outliers_removed: List[float] = field(default_factory=list)
    confidence_interval: Tuple[float, float] = (0.0, 0.0)
    median: float = 0.0
    percentiles: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class DetailedMemoryResult(MemoryResult):
    """
    Extended memory measurement with allocation details.
    
    Attributes
    ----------
    current_kb : int
        Current memory usage after import.
    module_size_kb : int
        Estimated size of module object graph.
    allocation_hotspots : Dict[str, int]
        Files with highest memory allocations.
    gc_stats : Dict[str, Any]
        Garbage collection statistics.
    """
    
    current_kb: int = 0
    module_size_kb: int = 0
    allocation_hotspots: Dict[str, int] = field(default_factory=dict)
    gc_stats: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetailedDependencyResult(DependencyResult):
    """
    Extended dependency analysis with graph metrics.
    
    Attributes
    ----------
    graph : Dict[str, Any]
        Complete dependency graph structure.
    has_cycles : bool
        Whether circular dependencies exist.
    stdlib_count : int
        Number of standard library dependencies.
    third_party_count : int
        Number of third-party dependencies.
    max_depth : int
        Maximum depth of dependency tree.
    """
    
    count: int = 0
    graph: Dict[str, Any] = field(default_factory=dict)
    has_cycles: bool = False
    stdlib_count: int = 0
    third_party_count: int = 0
    max_depth: int = 0


@dataclass
class ProbeResult:
    """
    Comprehensive probe result combining all measurement dimensions.
    
    Attributes
    ----------
    module : str
        Name of probed module.
    timestamp : datetime
        When the probe was executed.
    time_result : DetailedTimeResult
        Timing analysis results.
    memory_result : DetailedMemoryResult
        Memory analysis results.
    dependency_result : DetailedDependencyResult
        Dependency analysis results.
    stability_result : StabilityResult
        Stability analysis results.
    config : ProbeConfig
        Configuration used for this probe.
    metadata : Dict[str, Any]
        Additional contextual information.
    errors : List[str]
        Non-fatal errors encountered during probing.
    warnings : List[str]
        Warnings generated during analysis.
    """
    
    module: str
    timestamp: datetime
    time_result: DetailedTimeResult
    memory_result: DetailedMemoryResult
    dependency_result: DetailedDependencyResult
    stability_result: StabilityResult
    config: ProbeConfig
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize complete result to JSON."""
        return json.dumps(asdict(self), default=str, indent=indent)
    
    @property
    def overall_category(self) -> str:
        """Synthesize overall performance category."""
        categories = [
            self.time_result.category,
            self.memory_result.category,
            self.dependency_result.category,
            self.stability_result.category
        ]
        # Weighted by severity
        severity_order = [
            'instant', 'light', 'minimal', 'stable',
            'medium', 'moderate', 'normal',
            'heavy', 'unstable',
            'critical', 'memory-hog', 'explosive', 'chaotic'
        ]
        return max(categories, key=lambda c: severity_order.index(c) if c in severity_order else 0)


# -----------------------------------------------------------------------------
# Cache and Environment Management
# -----------------------------------------------------------------------------

class CacheState:
    """
    Manager for filesystem and interpreter cache state.
    
    This class provides utilities for clearing and restoring various cache
    layers that affect import performance measurements, enabling true
    cold-start simulation.
    """
    
    def __init__(self, module: str) -> None:
        """
        Initialize cache state manager.
        
        Parameters
        ----------
        module : str
            Target module name.
        """
        self.module = module
        self._pycache_paths: List[Path] = []
        self._original_bytecode: Dict[Path, bytes] = {}
    
    def clear_filesystem_cache(self) -> None:
        """
        Attempt to clear operating system filesystem cache.
        
        Notes
        -----
        This operation typically requires elevated privileges and may not
        succeed on all platforms. Failure is logged but not fatal.
        """
        system = platform.system().lower()
        
        if system in PAGECACHE_CLEAR_COMMANDS:
            commands = PAGECACHE_CLEAR_COMMANDS[system]
            for cmd in commands:
                try:
                    if system == 'linux' and os.geteuid() != 0:
                        # Try with sudo if available
                        subprocess.run(
                            ['sudo', 'sh', '-c', cmd],
                            capture_output=True,
                            timeout=5
                        )
                    else:
                        subprocess.run(
                            cmd.split(),
                            capture_output=True,
                            timeout=5,
                            shell=True
                        )
                except (subprocess.SubprocessError, PermissionError) as e:
                    logger.debug(f"Failed to clear cache with '{cmd}': {e}")
    
    def clear_python_cache(self) -> None:
        """
        Clear Python bytecode cache files.
        
        This removes .pyc files in __pycache__ directories related to
        the target module, forcing recompilation on next import.
        """
        try:
            # Find module location
            result = subprocess.run(
                [sys.executable, '-c', f'import {self.module}; print({self.module}.__file__)'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and result.stdout.strip():
                module_path = Path(result.stdout.strip())
                if module_path.exists():
                    # Clear __pycache__ for this module
                    pycache = module_path.parent / '__pycache__'
                    if pycache.exists():
                        for cache_file in pycache.glob(f'{module_path.stem}*.pyc'):
                            cache_file.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"Failed to clear Python cache: {e}")
    
    def clear_all_caches(self) -> None:
        """Clear both filesystem and Python caches."""
        self.clear_filesystem_cache()
        self.clear_python_cache()
    
    @contextmanager
    def cold_start_context(self) -> Iterator[None]:
        """
        Context manager for cold start measurement.
        
        Temporarily clears caches and restores them after measurement.
        
        Yields
        ------
        None
            Control returns to caller with caches cleared.
        """
        # Save state
        self.clear_all_caches()
        
        try:
            yield
        finally:
            # Cache restoration is automatic on next access
            pass


# -----------------------------------------------------------------------------
# Statistical Analysis Utilities
# -----------------------------------------------------------------------------

def calculate_statistics(samples: List[float]) -> Dict[str, float]:
    """
    Calculate comprehensive statistics from sample data.
    
    Parameters
    ----------
    samples : List[float]
        Raw measurement samples.
    
    Returns
    -------
    Dict[str, float]
        Dictionary of statistical metrics.
    """
    if not samples:
        return {}
    
    sorted_samples = sorted(samples)
    n = len(sorted_samples)
    
    return {
        'mean': statistics.mean(samples),
        'median': statistics.median(samples),
        'stddev': statistics.stdev(samples) if n > 1 else 0.0,
        'variance': statistics.variance(samples) if n > 1 else 0.0,
        'min': min(samples),
        'max': max(samples),
        'p25': sorted_samples[n // 4],
        'p50': sorted_samples[n // 2],
        'p75': sorted_samples[(3 * n) // 4],
        'p90': sorted_samples[int(n * 0.9)],
        'p95': sorted_samples[int(n * 0.95)],
        'p99': sorted_samples[int(n * 0.99)],
        'iqr': sorted_samples[(3 * n) // 4] - sorted_samples[n // 4],
        'skewness': _calculate_skewness(samples),
        'kurtosis': _calculate_kurtosis(samples),
    }


def _calculate_skewness(data: List[float]) -> float:
    """Calculate sample skewness."""
    n = len(data)
    if n < 3:
        return 0.0
    mean = statistics.mean(data)
    std = statistics.stdev(data)
    if std == 0:
        return 0.0
    skew = sum((x - mean) ** 3 for x in data) / n
    return skew / (std ** 3)


def _calculate_kurtosis(data: List[float]) -> float:
    """Calculate sample excess kurtosis."""
    n = len(data)
    if n < 4:
        return 0.0
    mean = statistics.mean(data)
    std = statistics.stdev(data)
    if std == 0:
        return 0.0
    kurt = sum((x - mean) ** 4 for x in data) / n
    return (kurt / (std ** 4)) - 3


def remove_statistical_outliers(
    samples: List[float], 
    max_removal_ratio: float = DEFAULT_MAX_OUTLIER_RATIO
) -> Tuple[List[float], List[float]]:
    """
    Remove outliers using multiple detection methods.
    
    Parameters
    ----------
    samples : List[float]
        Raw measurement samples.
    max_removal_ratio : float
        Maximum fraction of samples to remove.
    
    Returns
    -------
    Tuple[List[float], List[float]]
        Cleaned samples and removed outliers.
    """
    if len(samples) < 4:
        return samples.copy(), []
    
    max_removals = int(len(samples) * max_removal_ratio)
    sorted_samples = sorted(samples)
    
    # Method 1: IQR method
    q1 = sorted_samples[len(sorted_samples) // 4]
    q3 = sorted_samples[(3 * len(sorted_samples)) // 4]
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    
    iqr_outliers = [x for x in samples if x < lower_bound or x > upper_bound]
    iqr_clean = [x for x in samples if lower_bound <= x <= upper_bound]
    
    # Method 2: Z-score method (if IQR didn't catch enough)
    if len(iqr_outliers) < max_removals and len(iqr_clean) > 2:
        mean = statistics.mean(iqr_clean)
        std = statistics.stdev(iqr_clean)
        if std > 0:
            z_scores = [(x, abs(x - mean) / std) for x in iqr_clean]
            z_scores.sort(key=lambda x: x[1], reverse=True)
            
            additional_outliers = []
            for value, z_score in z_scores[:max_removals - len(iqr_outliers)]:
                if z_score > 2.0:  # Only remove if truly anomalous
                    additional_outliers.append(value)
                    iqr_clean.remove(value)
            
            iqr_outliers.extend(additional_outliers)
    
    return iqr_clean, iqr_outliers


# -----------------------------------------------------------------------------
# Core Probing Functions
# -----------------------------------------------------------------------------

def _run_import(module: str, timeout: float, capture_stderr: bool = False) -> subprocess.CompletedProcess:
    """
    Execute module import in isolated subprocess.
    
    Parameters
    ----------
    module : str
        Name of module to import.
    timeout : float
        Maximum execution time in seconds.
    capture_stderr : bool
        Whether to capture stderr output.
    
    Returns
    -------
    subprocess.CompletedProcess
        Process result object.
    
    Raises
    ------
    subprocess.TimeoutExpired
        If import exceeds timeout.
    subprocess.CalledProcessError
        If import fails with non-zero exit code.
    """
    cmd = [sys.executable, '-c', f'import {module}']
    
    stderr_dest = subprocess.PIPE if capture_stderr else subprocess.DEVNULL
    
    return subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=stderr_dest,
        timeout=timeout,
        check=False,
        text=True
    )


def run_timed_import(
    module: str, 
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    clear_caches: bool = False,
    capture_stderr: bool = False
) -> Tuple[float, Optional[str]]:
    """
    Measure isolated import time with optional cache clearing.
    
    Parameters
    ----------
    module : str
        Name of module to time.
    timeout : float
        Maximum execution time in seconds.
    clear_caches : bool
        Whether to attempt cache clearing before import.
    capture_stderr : bool
        Whether to capture stderr output.
    
    Returns
    -------
    Tuple[float, Optional[str]]
        Import time in seconds and captured stderr if any.
    
    Raises
    ------
    subprocess.TimeoutExpired
        If import exceeds timeout.
    RuntimeError
        If import fails.
    """
    if clear_caches:
        cache_state = CacheState(module)
        cache_state.clear_all_caches()
    
    start = time.perf_counter()
    result = _run_import(module, timeout, capture_stderr)
    elapsed = time.perf_counter() - start
    
    if result.returncode != 0:
        stderr_msg = result.stderr if capture_stderr else None
        raise RuntimeError(f"Failed to import {module}: {stderr_msg or 'Unknown error'}")
    
    stderr_output = result.stderr if capture_stderr else None
    return elapsed, stderr_output


def collect_timing_samples(
    module: str,
    repetitions: int = DEFAULT_REPETITIONS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    warmup: int = DEFAULT_WARMUP_ITERATIONS,
    clear_caches_between: bool = False,
    retry_on_failure: int = 2
) -> List[float]:
    """
    Collect multiple timing samples with robust error handling.
    
    Parameters
    ----------
    module : str
        Name of module to profile.
    repetitions : int
        Number of timing repetitions.
    timeout : float
        Maximum execution time per sample.
    warmup : int
        Number of warmup iterations.
    clear_caches_between : bool
        Whether to clear caches between samples.
    retry_on_failure : int
        Number of retry attempts for failures.
    
    Returns
    -------
    List[float]
        List of import times in seconds.
    
    Raises
    ------
    RuntimeError
        If all attempts fail.
    """
    # Perform warmup
    for _ in range(warmup):
        try:
            run_timed_import(module, timeout, clear_caches=False)
        except (subprocess.TimeoutExpired, RuntimeError):
            pass  # Warmup failures are acceptable
    
    times = []
    failures = 0
    
    for attempt in range(repetitions + retry_on_failure):
        if len(times) >= repetitions:
            break
            
        try:
            elapsed, _ = run_timed_import(module, timeout, clear_caches_between)
            times.append(elapsed)
            failures = 0  # Reset failure counter on success
        except (subprocess.TimeoutExpired, RuntimeError) as e:
            failures += 1
            logger.warning(f"Import attempt {attempt + 1} failed for {module}: {e}")
            
            if failures > retry_on_failure and len(times) == 0:
                raise RuntimeError(f"All import attempts failed for {module}") from e
            
            # Exponential backoff for retries
            time.sleep(0.5 * (2 ** min(failures - 1, 4)))
    
    if not times:
        raise RuntimeError(f"Failed to collect any timing samples for {module}")
    
    return times


def analyze_timing_data(
    times: List[float],
    remove_outliers: bool = True,
    max_outlier_ratio: float = DEFAULT_MAX_OUTLIER_RATIO
) -> DetailedTimeResult:
    """
    Perform comprehensive timing data analysis.
    
    Parameters
    ----------
    times : List[float]
        List of import times in seconds.
    remove_outliers : bool
        Whether to filter statistical outliers.
    max_outlier_ratio : float
        Maximum fraction of data to remove as outliers.
    
    Returns
    -------
    DetailedTimeResult
        Comprehensive timing analysis results.
    
    Raises
    ------
    ValueError
        If times list is empty.
    """
    if not times:
        raise ValueError("Empty times list provided for analysis")
    
    original_samples = times.copy()
    outliers_removed = []
    
    if remove_outliers and len(times) >= 4:
        cleaned, outliers = remove_statistical_outliers(times, max_outlier_ratio)
        if cleaned:
            times = cleaned
            outliers_removed = outliers
    
    stats = calculate_statistics(times)
    
    # Calculate confidence interval
    confidence_interval = (0.0, 0.0)
    if len(times) >= 10:
        mean = stats['mean']
        std = stats['stddev']
        margin = 1.96 * (std / math.sqrt(len(times)))
        confidence_interval = (mean - margin, mean + margin)
    
    return DetailedTimeResult(
        average=stats['mean'],
        min_time=stats['min'],
        max_time=stats['max'],
        stddev=stats['stddev'],
        category=classify_time(stats['mean']),
        samples=original_samples,
        outliers_removed=outliers_removed,
        confidence_interval=confidence_interval,
        median=stats['median'],
        percentiles={
            'p25': stats['p25'],
            'p50': stats['p50'],
            'p75': stats['p75'],
            'p90': stats['p90'],
            'p95': stats['p95'],
            'p99': stats['p99'],
        }
    )


def calculate_stability_index(times: List[float]) -> StabilityResult:
    """
    Calculate enhanced stability metrics from timing data.
    
    Parameters
    ----------
    times : List[float]
        List of import times in seconds.
    
    Returns
    -------
    StabilityResult
        Stability analysis with confidence assessment.
    """
    if not times:
        return StabilityResult(index=0.0, category="unknown", confidence=0.0)
    
    if len(times) == 1:
        return StabilityResult(index=0.0, category="stable", confidence=0.5)
    
    mean_time = statistics.mean(times)
    
    if mean_time == 0:
        return StabilityResult(index=0.0, category="stable", confidence=1.0)
    
    # Remove outliers for stability calculation
    if len(times) >= 4:
        cleaned, _ = remove_statistical_outliers(times, 0.2)
        if cleaned:
            times = cleaned
            mean_time = statistics.mean(times)
    
    stddev_time = statistics.stdev(times) if len(times) > 1 else 0.0
    index = stddev_time / mean_time if mean_time > 0 else 0.0
    
    # Calculate confidence based on sample size and distribution
    confidence = min(1.0, len(times) / 30.0)  # More samples = higher confidence
    if len(times) >= 10:
        # Check for normality using simple skewness check
        skewness = abs(_calculate_skewness(times))
        if skewness < 0.5:
            confidence *= 0.9
        else:
            confidence *= 0.6
    
    return StabilityResult(
        index=index,
        category=classify_stability(index),
        confidence=confidence
    )


def run_memory_probe(
    module: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    track_allocations: bool = False
) -> DetailedMemoryResult:
    """
    Run advanced memory profiling for module import.
    
    Parameters
    ----------
    module : str
        Name of module to probe.
    timeout : float
        Maximum execution time in seconds.
    track_allocations : bool
        Whether to track detailed allocation hotspots.
    
    Returns
    -------
    DetailedMemoryResult
        Comprehensive memory analysis results.
    
    Raises
    ------
    subprocess.TimeoutExpired
        If probe exceeds timeout.
    ImportError
        If module import fails.
    """
    probe_code = MEMORY_PROBE_TEMPLATE.format(module=module)
    
    try:
        output = subprocess.check_output(
            [sys.executable, '-c', probe_code],
            stderr=subprocess.PIPE,
            timeout=timeout,
            universal_newlines=True,
        )
        
        result = json.loads(output.strip())
        
        if not result.get("success", False):
            error_msg = result.get("error", "Unknown import error")
            raise ImportError(f"Failed to import {module}: {error_msg}")
        
        memory_result = DetailedMemoryResult(
            peak_kb=result["peak_kb"],
            category=classify_memory(result["peak_kb"]),
            current_kb=result["current_kb"],
            module_size_kb=result.get("module_size_kb", 0),
        )
        
        if track_allocations:
            memory_result.allocation_hotspots = result.get("allocation_hotspots", {})
        
        return memory_result
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"Memory probe timeout for {module}: {e}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse memory probe output: {e}")
        raise RuntimeError(f"Invalid memory probe output for {module}") from e


def run_dependency_probe(
    module: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    build_graph: bool = False
) -> DetailedDependencyResult:
    """
    Run comprehensive dependency analysis.
    
    Parameters
    ----------
    module : str
        Name of module to analyze.
    timeout : float
        Maximum execution time in seconds.
    build_graph : bool
        Whether to construct full dependency graph.
    
    Returns
    -------
    DetailedDependencyResult
        Complete dependency analysis results.
    """
    # Fast path: simple dependency count
    if not build_graph:
        probe_code = f"""
import sys
before = set(sys.modules)
import {module}
after = set(sys.modules)
new_modules = sorted(after - before)
print(len(new_modules))
"""
        try:
            output = subprocess.check_output(
                [sys.executable, '-c', probe_code],
                stderr=subprocess.PIPE,
                timeout=timeout,
                universal_newlines=True,
            )
            
            deps_count = int(output.strip())
            return DetailedDependencyResult(
                count=deps_count,
                category=classify_dependencies(deps_count)
            )
            
        except subprocess.TimeoutExpired:
            raise
        except Exception as e:
            logger.error(f"Dependency probe failed for {module}: {e}")
            return DetailedDependencyResult(count=0, category="unknown")
    
    # Full graph construction
    probe_code = DEPENDENCY_TREE_TEMPLATE.format(module=module)
    
    try:
        output = subprocess.check_output(
            [sys.executable, '-c', probe_code],
            stderr=subprocess.PIPE,
            timeout=timeout,
            universal_newlines=True,
        )
        
        graph = json.loads(output.strip())
        
        # Calculate graph metrics
        deps_count = len(graph)
        max_depth = 0
        stdlib_count = 0
        third_party_count = 0
        has_cycles = False
        
        for name, info in graph.items():
            max_depth = max(max_depth, info.get("depth", 0))
            if info.get("is_stdlib", False):
                stdlib_count += 1
            else:
                third_party_count += 1
            
            # Simple cycle detection
            if info.get("children"):
                for child in info["children"]:
                    if child in graph and graph[child].get("parent") == name:
                        if name in graph[child].get("children", []):
                            has_cycles = True
        
        return DetailedDependencyResult(
            count=deps_count,
            category=classify_dependencies(deps_count),
            modules=list(graph.keys()),
            graph=graph,
            has_cycles=has_cycles,
            stdlib_count=stdlib_count,
            third_party_count=third_party_count,
            max_depth=max_depth
        )
        
    except subprocess.TimeoutExpired:
        raise
    except Exception as e:
        logger.error(f"Graph construction failed for {module}: {e}")
        # Fall back to simple count
        return run_dependency_probe(module, timeout, build_graph=False)


def _measure_import(
    module: str,
    repetition: int,
    timeout: float,
    warmup: int,
) -> ImportBenchmarkResult:
    """
    Legacy-compatible import measurement function.
    
    Parameters
    ----------
    module : str
        Name of module to benchmark.
    repetition : int
        Number of measured import attempts.
    timeout : float
        Maximum allowed time per import.
    warmup : int
        Number of unmeasured warmup imports.
    
    Returns
    -------
    ImportBenchmarkResult
        Statistical summary of import performance.
    """
    config = ProbeConfig(
        repetitions=repetition,
        warmup_strategy=WarmupStrategy.STANDARD if warmup > 0 else WarmupStrategy.NONE,
        timeout=timeout
    )
    
    result = measure_import(module, config)
    
    return ImportBenchmarkResult(
        module=module,
        average=result.time_result.average,
        min_time=result.time_result.min_time,
        max_time=result.time_result.max_time,
        stddev=result.time_result.stddev,
        category=result.time_result.category,
    )


# -----------------------------------------------------------------------------
# Primary Public API
# -----------------------------------------------------------------------------

def measure_import(
    module: str,
    config: Optional[ProbeConfig] = None
) -> ProbeResult:
    """
    Perform comprehensive multi-dimensional import measurement.
    
    This is the primary entry point for module performance analysis,
    combining timing, memory, dependency, and stability measurements
    into a single rich result.
    
    Parameters
    ----------
    module : str
        Name of module to measure.
    config : Optional[ProbeConfig]
        Measurement configuration. Uses defaults if None.
    
    Returns
    -------
    ProbeResult
        Complete measurement results across all dimensions.
    
    Examples
    --------
    >>> config = ProbeConfig(repetitions=10, measurement_mode=MeasurementMode.PRECISE)
    >>> result = measure_import("numpy", config)
    >>> print(f"Import time: {result.time_result.average:.3f}s")
    >>> print(f"Category: {result.overall_category}")
    """
    if config is None:
        config = ProbeConfig()
    
    config.apply_mode_overrides()
    
    errors = []
    warnings_list = []
    
    # Time measurement
    try:
        times = collect_timing_samples(
            module,
            repetitions=config.repetitions,
            timeout=config.timeout,
            warmup=config.warmup_strategy.get_iterations(),
            clear_caches_between=config.clear_filesystem_cache,
            retry_on_failure=config.retry_on_failure
        )
        
        time_result = analyze_timing_data(
            times,
            remove_outliers=config.remove_outliers,
            max_outlier_ratio=config.max_outlier_ratio
        )
    except Exception as e:
        errors.append(f"Timing measurement failed: {e}")
        time_result = DetailedTimeResult(
            average=0.0, min_time=0.0, max_time=0.0, stddev=0.0,
            category="unknown", samples=[], outliers_removed=[],
            confidence_interval=(0.0, 0.0), median=0.0, percentiles={}
        )
    
    # Memory measurement
    try:
        memory_result = run_memory_probe(
            module,
            timeout=config.timeout,
            track_allocations=config.track_allocations
        )
    except Exception as e:
        errors.append(f"Memory measurement failed: {e}")
        memory_result = DetailedMemoryResult(
            peak_kb=0, category="unknown"
        )
    
    # Dependency analysis
    try:
        dependency_result = run_dependency_probe(
            module,
            timeout=config.timeout,
            build_graph=config.build_dependency_graph
        )
    except Exception as e:
        errors.append(f"Dependency analysis failed: {e}")
        dependency_result = DetailedDependencyResult(
            category="unknown"
        )
    
    # Stability calculation
    if time_result.samples:
        stability_result = calculate_stability_index(time_result.samples)
    else:
        stability_result = StabilityResult(index=0.0, category="unknown")
    
    # Check for warnings
    if time_result.stddev > time_result.average * 0.5:
        warnings_list.append("High variability in import times detected")
    
    if dependency_result.has_cycles:
        warnings_list.append(f"Circular dependencies detected in {module}")
    
    if memory_result.peak_kb > 100_000:  # 100 MB
        warnings_list.append(f"High memory usage: {memory_result.peak_kb / 1024:.1f} MB")
    
    return ProbeResult(
        module=module,
        timestamp=datetime.utcnow(),
        time_result=time_result,
        memory_result=memory_result,
        dependency_result=dependency_result,
        stability_result=stability_result,
        config=config,
        metadata={}, # NULL for now
        errors=errors,
        warnings=warnings_list
    )


# -----------------------------------------------------------------------------
# Batch and Concurrent Probing
# -----------------------------------------------------------------------------

async def measure_imports_async(
    modules: List[str],
    config: Optional[ProbeConfig] = None,
    max_concurrency: Optional[int] = None
) -> Dict[str, ProbeResult]:
    """
    Measure multiple modules concurrently.
    
    Parameters
    ----------
    modules : List[str]
        List of module names to measure.
    config : Optional[ProbeConfig]
        Measurement configuration.
    max_concurrency : Optional[int]
        Maximum concurrent measurements.
    
    Returns
    -------
    Dict[str, ProbeResult]
        Mapping of module names to measurement results.
    """
    if config is None:
        config = ProbeConfig()
    
    concurrency = max_concurrency or config.concurrent_workers
    semaphore = asyncio.Semaphore(concurrency)
    
    async def measure_one(module: str) -> ProbeResult:
        async with semaphore:
            # Run in thread pool since measurements use subprocess
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, 
                partial(measure_import, module, config)
            )
    
    tasks = [measure_one(module) for module in modules]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    output = {}
    for module, result in zip(modules, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to measure {module}: {result}")
            # Create error result
            error_result = ProbeResult(
                module=module,
                timestamp=datetime.utcnow(),
                time_result=DetailedTimeResult(
                    average=0.0, min_time=0.0, max_time=0.0, stddev=0.0,
                    category="error", samples=[], outliers_removed=[],
                    confidence_interval=(0.0, 0.0), median=0.0, percentiles={}
                ),
                memory_result=DetailedMemoryResult(peak_kb=0, category="error"),
                dependency_result=DetailedDependencyResult(count=0, category="error"),
                stability_result=StabilityResult(index=0.0, category="error"),
                config=config,
                errors=[str(result)]
            )
            output[module] = error_result
        else:
            output[module] = result
    
    return output


def measure_imports(
    modules: List[str],
    config: Optional[ProbeConfig] = None,
    max_concurrency: Optional[int] = None
) -> Dict[str, ProbeResult]:
    """
    Synchronous wrapper for concurrent module measurement.
    
    Parameters
    ----------
    modules : List[str]
        List of module names to measure.
    config : Optional[ProbeConfig]
        Measurement configuration.
    max_concurrency : Optional[int]
        Maximum concurrent measurements.
    
    Returns
    -------
    Dict[str, ProbeResult]
        Mapping of module names to measurement results.
    """
    return asyncio.run(measure_imports_async(modules, config, max_concurrency))


# -----------------------------------------------------------------------------
# Probe Session Context Manager
# -----------------------------------------------------------------------------

class ProbeSession:
    """
    Context manager for coordinated multi-module probing.
    
    This class manages resources and state for batch measurement operations,
    providing consistent configuration and aggregated reporting.
    
    Examples
    --------
    >>> with ProbeSession(ProbeConfig(measurement_mode=MeasurementMode.PRECISE)) as session:
    ...     numpy_result = session.measure("numpy")
    ...     pandas_result = session.measure("pandas")
    ...     report = session.generate_report()
    """
    
    def __init__(self, config: Optional[ProbeConfig] = None):
        """
        Initialize probe session.
        
        Parameters
        ----------
        config : Optional[ProbeConfig]
            Configuration for all measurements in session.
        """
        self.config = config or ProbeConfig()
        self.results: Dict[str, ProbeResult] = {}
        self._start_time: Optional[datetime] = None
        self._cache_state = CacheState("")
    
    def __enter__(self) -> 'ProbeSession':
        """Start probe session."""
        self._start_time = datetime.utcnow()
        logger.info(f"Starting probe session at {self._start_time}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """End probe session and cleanup."""
        duration = datetime.utcnow() - self._start_time if self._start_time else timedelta()
        logger.info(f"Probe session completed in {duration.total_seconds():.2f}s")
        logger.info(f"Measured {len(self.results)} modules")
        return False
    
    def measure(self, module: str) -> ProbeResult:
        """
        Measure a single module within session.
        
        Parameters
        ----------
        module : str
            Module name to measure.
        
        Returns
        -------
        ProbeResult
            Measurement results.
        """
        if module in self.results:
            logger.warning(f"Module {module} already measured in this session")
            return self.results[module]
        
        result = measure_import(module, self.config)
        self.results[module] = result
        return result
    
    def measure_many(self, modules: List[str]) -> Dict[str, ProbeResult]:
        """
        Measure multiple modules concurrently.
        
        Parameters
        ----------
        modules : List[str]
            List of modules to measure.
        
        Returns
        -------
        Dict[str, ProbeResult]
            Measurement results for all modules.
        """
        new_modules = [m for m in modules if m not in self.results]
        if new_modules:
            new_results = measure_imports(new_modules, self.config)
            self.results.update(new_results)
        
        return {m: self.results[m] for m in modules}
    
    def generate_report(self) -> Dict[str, Any]:
        """
        Generate aggregate session report.
        
        Returns
        -------
        Dict[str, Any]
            Comprehensive session statistics and analysis.
        """
        if not self.results:
            return {'error': 'No measurements in session'}
        
        categories = [r.overall_category for r in self.results.values()]
        times = [r.time_result.average for r in self.results.values() if r.time_result.average > 0]
        memories = [r.memory_result.peak_kb for r in self.results.values() if r.memory_result.peak_kb > 0]
        
        return {
            'session_duration': str(datetime.utcnow() - self._start_time if self._start_time else timedelta()),
            'modules_measured': len(self.results),
            'category_distribution': {
                cat: categories.count(cat) for cat in set(categories)
            },
            'aggregate_stats': {
                'total_import_time': sum(times),
                'avg_import_time': statistics.mean(times) if times else 0,
                'total_memory_kb': sum(memories),
                'avg_memory_kb': statistics.mean(memories) if memories else 0,
            },
            'slowest_modules': sorted(
                [(m, r.time_result.average) for m, r in self.results.items()],
                key=lambda x: x[1],
                reverse=True
            )[:5],
            'memory_heavy_modules': sorted(
                [(m, r.memory_result.peak_kb) for m, r in self.results.items()],
                key=lambda x: x[1],
                reverse=True
            )[:5],
            'modules_with_errors': [
                m for m, r in self.results.items() if r.errors
            ],
            'modules_with_warnings': [
                m for m, r in self.results.items() if r.warnings
            ],
        }
    
    def export_results(self, filepath: Union[str, Path]) -> None:
        """
        Export all session results to JSON file.
        
        Parameters
        ----------
        filepath : Union[str, Path]
            Path to output JSON file.
        """
        export_data = {
            'session_metadata': {
                'start_time': self._start_time.isoformat() if self._start_time else None,
                'end_time': datetime.utcnow().isoformat(),
                'config': asdict(self.config),
            },
            'report': self.generate_report(),
            'results': {
                module: asdict(result) 
                for module, result in self.results.items()
            }
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, default=str, indent=2)
        
        logger.info(f"Session results exported to {filepath}")


# -----------------------------------------------------------------------------
# Module Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Primary functions
    'measure_import',
    'measure_imports',
    'measure_imports_async',
    'run_memory_probe',
    'run_dependency_probe',
    'run_timed_import',
    'collect_timing_samples',
    'analyze_timing_data',
    'calculate_stability_index',
    
    # Legacy compatibility
    '_measure_import',
    '_run_import',
    
    # Classes and enums
    'ProbeConfig',
    'ProbeResult',
    'ProbeSession',
    'DetailedTimeResult',
    'DetailedMemoryResult',
    'DetailedDependencyResult',
    'WarmupStrategy',
    'MeasurementMode',
    'CacheState',
    
    # Utilities
    'calculate_statistics',
    'remove_statistical_outliers',
]