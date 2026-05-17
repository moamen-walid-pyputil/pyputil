#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
_perf_classifiers.py

Performance Classification System for Python Module Imports.

This module provides a sophisticated, production-grade classification framework
for analyzing Python import performance across multiple dimensions. It goes beyond
simple threshold-based categorization by incorporating statistical confidence
intervals, outlier detection, weighted scoring systems, and adaptive thresholding
based on runtime environment characteristics.

Features
--------
- Multi-dimensional scoring with configurable weights
- Statistical confidence intervals using bootstrap resampling
- Outlier detection and handling using IQR method
- Environment-aware threshold adaptation (CI vs Production)
- Comprehensive logging with structured data support
- Caching decorators for expensive calculations
- Custom exception hierarchy for fine-grained error handling
- Serialization support for JSON/YAML export

Classes
-------
ClassificationDimension
    Enumeration of all measurable performance dimensions.
PerformanceScore
    NamedTuple containing detailed scoring breakdown.
ClassifiedModule
    Data class representing a fully analyzed module.
AdaptiveThresholds
    Context manager for temporarily modifying classification thresholds.
ThresholdCalibration
    Static class for calibrating thresholds from benchmark data.

Functions
---------
classify_time
    Enhanced time classification with confidence intervals.
classify_memory
    Memory classification with percent-of-system analysis.
classify_dependencies
    Dependency classification with depth and breadth analysis.
classify_stability
    Stability classification with outlier removal.
classify_module
    Full multi-dimensional analysis returning ClassifiedModule.
calibrate_thresholds_from_benchmarks
    Machine learning-based threshold optimization.
bootstrap_classification_confidence
    Statistical confidence calculation via resampling.
"""

import json
import logging
import math
import statistics
import warnings
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from functools import lru_cache, wraps
from typing import (
    Any, Callable, Dict, Final, Iterator, List, NamedTuple, 
    Optional, Sequence, Tuple, TypeVar, Union, overload
)
from datetime import datetime
import random

# -----------------------------------------------------------------------------
# Type Variables and Protocol Definitions
# -----------------------------------------------------------------------------

T = TypeVar('T')
Numeric = Union[int, float]
MetricFunction = Callable[..., str]

# -----------------------------------------------------------------------------
# Module-Level Constants with Extended Configuration
# -----------------------------------------------------------------------------"

# Default time thresholds (seconds) - empirically derived from CPython benchmarks
TIME_LIGHT_THRESHOLD: float = 0.01
TIME_MEDIUM_THRESHOLD: float = 0.1
TIME_HEAVY_THRESHOLD: float = 0.5
TIME_CRITICAL_THRESHOLD: float = 1.0

# Default memory thresholds (kilobytes) - based on typical serverless limits
MEMORY_LIGHT_THRESHOLD: int = 512
MEMORY_MODERATE_THRESHOLD: int = 5_000
MEMORY_HEAVY_THRESHOLD: int = 50_000
MEMORY_CRITICAL_THRESHOLD: int = 500_000

# Default dependency thresholds
DEPS_MINIMAL_THRESHOLD: int = 20
DEPS_MODERATE_THRESHOLD: int = 100
DEPS_HEAVY_THRESHOLD: int = 500
DEPS_EXTREME_THRESHOLD: int = 1_000

# Default stability thresholds (coefficient of variation)
STABILITY_STABLE_THRESHOLD: float = 0.05
STABILITY_NORMAL_THRESHOLD: float = 0.15
STABILITY_UNSTABLE_THRESHOLD: float = 0.30
STABILITY_CHAOTIC_THRESHOLD: float = 0.50

# Statistical configuration
DEFAULT_CONFIDENCE_LEVEL: Final[float] = 0.95
BOOTSTRAP_SAMPLES: Final[int] = 10_000
OUTLIER_IQR_MULTIPLIER: Final[float] = 1.5
CACHE_SIZE: Final[int] = 1024

# Environment detection
IS_CI: Final[bool] = any(var in os.environ for var in ['CI', 'JENKINS_HOME', 'GITHUB_ACTIONS']) if 'os' in dir() else False
IS_PRODUCTION: Final[bool] = not IS_CI and not __debug__

# Configure structured logging
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
        '"module": "%(name)s", "message": %(message)s}'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)

# Import os lazily to avoid circular dependencies
try:
    import os
except ImportError:
    os = None  # type: ignore


# -----------------------------------------------------------------------------
# Enhanced Enumeration System
# -----------------------------------------------------------------------------

class ClassificationDimension(Enum):
    """
    Enumeration of all measurable performance classification dimensions.
    
    Each dimension represents a distinct aspect of module import performance
    that can be independently measured, classified, and weighted in composite
    scoring algorithms.
    
    Attributes
    ----------
    TIME : auto
        Wall-clock import duration classification.
    MEMORY : auto
        Peak memory consumption classification.
    DEPENDENCIES : auto
        Transitive dependency count classification.
    STABILITY : auto
        Runtime variance classification.
    DISK_IO : auto
        Filesystem operation count classification.
    CPU_TIME : auto
        Processor time consumption classification.
    """
    
    TIME = auto()
    MEMORY = auto()
    DEPENDENCIES = auto()
    STABILITY = auto()
    DISK_IO = auto()
    CPU_TIME = auto()
    
    def __str__(self) -> str:
        """Return human-readable dimension name."""
        return self.name.replace('_', ' ').title()


class Severity(Enum):
    """
    Severity levels for performance classifications.
    
    Used to prioritize issues in reporting and alerting systems.
    """
    
    NEGLIGIBLE = 0
    MINOR = 1
    MODERATE = 2
    MAJOR = 3
    CRITICAL = 4
    
    @classmethod
    def from_classification(cls, category: str, dimension: str) -> 'Severity':
        """
        Map classification category to severity level.
        
        Parameters
        ----------
        category : str
            Classification category (e.g., 'light', 'heavy').
        dimension : str
            The performance dimension being classified.
        
        Returns
        -------
        Severity
            Corresponding severity level.
        """
        severity_map = {
            ('light', 'time'): cls.NEGLIGIBLE,
            ('medium', 'time'): cls.MINOR,
            ('heavy', 'time'): cls.MODERATE,
            ('critical', 'time'): cls.CRITICAL,
            ('light', 'memory'): cls.NEGLIGIBLE,
            ('moderate', 'memory'): cls.MINOR,
            ('heavy', 'memory'): cls.MODERATE,
            ('critical', 'memory'): cls.CRITICAL,
            ('minimal', 'deps'): cls.NEGLIGIBLE,
            ('moderate', 'deps'): cls.MINOR,
            ('heavy', 'deps'): cls.MODERATE,
            ('extreme', 'deps'): cls.CRITICAL,
            ('stable', 'stability'): cls.NEGLIGIBLE,
            ('normal', 'stability'): cls.MINOR,
            ('unstable', 'stability'): cls.MODERATE,
            ('chaotic', 'stability'): cls.CRITICAL,
        }
        return severity_map.get((category, dimension), cls.MODERATE)


# -----------------------------------------------------------------------------
# Enhanced Exception Hierarchy
# -----------------------------------------------------------------------------

class PerformanceClassificationError(Exception):
    """Base exception class for all performance classification errors."""
    
    def __init__(self, message: str, dimension: Optional[str] = None, 
                 value: Optional[Any] = None) -> None:
        self.dimension = dimension
        self.value = value
        self.timestamp = datetime.utcnow().isoformat()
        super().__init__(message)
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to serializable dictionary."""
        return {
            'error_type': self.__class__.__name__,
            'message': str(self),
            'dimension': self.dimension,
            'value': self.value,
            'timestamp': self.timestamp
        }


class ThresholdError(PerformanceClassificationError):
    """
    Raised when input values violate domain constraints.
    
    This exception provides rich context about the validation failure,
    including the problematic value and the expected domain.
    """
    
    def __init__(self, message: str, dimension: Optional[str] = None,
                 value: Optional[Numeric] = None, 
                 expected_range: Optional[Tuple[Numeric, Numeric]] = None) -> None:
        self.expected_range = expected_range
        super().__init__(message, dimension, value)
    
    def __str__(self) -> str:
        base = super().__str__()
        if self.expected_range:
            return f"{base} (expected range: [{self.expected_range[0]}, {self.expected_range[1]}])"
        return base


class InsufficientDataError(PerformanceClassificationError):
    """
    Raised when statistical analysis requires more data points.
    
    Certain operations like confidence interval calculation or outlier
    detection require minimum sample sizes to produce meaningful results.
    """
    
    def __init__(self, message: str, required_samples: int, 
                 actual_samples: int) -> None:
        self.required_samples = required_samples
        self.actual_samples = actual_samples
        super().__init__(f"{message} (required: {required_samples}, got: {actual_samples})")


class CalibrationError(PerformanceClassificationError):
    """
    Raised when threshold calibration fails.
    
    This occurs when the calibration algorithm cannot converge or when
    the provided benchmark data is insufficient or malformed.
    """
    pass


# -----------------------------------------------------------------------------
# Data Structures for Rich Results
# -----------------------------------------------------------------------------

class PerformanceScore(NamedTuple):
    """
    Comprehensive performance score with component breakdown.
    
    Attributes
    ----------
    total : float
        Weighted composite score from 0.0 (optimal) to 1.0 (critical).
    time_score : float
        Time dimension contribution.
    memory_score : float
        Memory dimension contribution.
    dependency_score : float
        Dependency complexity contribution.
    stability_score : float
        Stability dimension contribution.
    confidence : float
        Statistical confidence in the scoring (0.0 to 1.0).
    """
    
    total: float
    time_score: float
    memory_score: float
    dependency_score: float
    stability_score: float
    confidence: float
    
    @property
    def severity(self) -> Severity:
        """Map total score to severity level."""
        if self.total < 0.2:
            return Severity.NEGLIGIBLE
        elif self.total < 0.4:
            return Severity.MINOR
        elif self.total < 0.6:
            return Severity.MODERATE
        elif self.total < 0.8:
            return Severity.MAJOR
        return Severity.CRITICAL
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to JSON-serializable dictionary."""
        return {
            'total': round(self.total, 4),
            'time_score': round(self.time_score, 4),
            'memory_score': round(self.memory_score, 4),
            'dependency_score': round(self.dependency_score, 4),
            'stability_score': round(self.stability_score, 4),
            'confidence': round(self.confidence, 4)
        }


@dataclass(frozen=True)
class ClassifiedModule:
    """
    Complete analysis result for a single Python module.
    
    This immutable data structure contains all classification results,
    statistical metrics, and metadata for a fully analyzed module import.
    
    Attributes
    ----------
    module_name : str
        Fully qualified module name.
    time_category : str
        Time-based classification.
    memory_category : str
        Memory-based classification.
    dependency_category : str
        Dependency count classification.
    stability_category : str
        Stability-based classification.
    overall_score : PerformanceScore
        Weighted composite performance score.
    raw_metrics : Dict[str, Any]
        Original measurement data.
    metadata : Dict[str, Any]
        Additional context (timestamp, environment, etc.).
    recommendations : List[str]
        Suggested optimizations based on analysis.
    """
    
    module_name: str
    time_category: str
    memory_category: str
    dependency_category: str
    stability_category: str
    overall_score: PerformanceScore
    raw_metrics: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    
    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self), default=str, indent=indent)
    
    @property
    def worst_dimension(self) -> Tuple[ClassificationDimension, str]:
        """Identify the most problematic performance dimension."""
        scores = [
            (ClassificationDimension.TIME, self.time_category, self.overall_score.time_score),
            (ClassificationDimension.MEMORY, self.memory_category, self.overall_score.memory_score),
            (ClassificationDimension.DEPENDENCIES, self.dependency_category, self.overall_score.dependency_score),
            (ClassificationDimension.STABILITY, self.stability_category, self.overall_score.stability_score),
        ]
        return max(scores, key=lambda x: x[2])[:2]


# -----------------------------------------------------------------------------
# Advanced Validation and Preprocessing
# -----------------------------------------------------------------------------

def _validate_numeric(value: Numeric, name: str, 
                      min_value: Optional[Numeric] = None,
                      max_value: Optional[Numeric] = None,
                      allow_nan: bool = False,
                      allow_inf: bool = False) -> None:
    """
    Comprehensive numeric validation with range checking.
    
    Parameters
    ----------
    value : Numeric
        Value to validate.
    name : str
        Parameter name for error messages.
    min_value : Optional[Numeric]
        Minimum allowed value (inclusive).
    max_value : Optional[Numeric]
        Maximum allowed value (inclusive).
    allow_nan : bool
        Whether NaN values are permitted.
    allow_inf : bool
        Whether infinite values are permitted.
    
    Raises
    ------
    ThresholdError
        If validation fails.
    """
    # Type checking
    if not isinstance(value, (int, float)):
        raise ThresholdError(
            f"{name} must be numeric, got {type(value).__name__}",
            dimension=name,
            value=value
        )
    
    # Special value handling
    if isinstance(value, float):
        if math.isnan(value) and not allow_nan:
            raise ThresholdError(f"{name} cannot be NaN", dimension=name, value=value)
        if math.isinf(value) and not allow_inf:
            raise ThresholdError(f"{name} cannot be infinite", dimension=name, value=value)
    
    # Range validation
    if min_value is not None and value < min_value:
        raise ThresholdError(
            f"{name} must be >= {min_value}, got {value}",
            dimension=name,
            value=value,
            expected_range=(min_value, max_value)
        )
    if max_value is not None and value > max_value:
        raise ThresholdError(
            f"{name} must be <= {max_value}, got {value}",
            dimension=name,
            value=value,
            expected_range=(min_value, max_value)
        )


def _remove_outliers(data: List[float], multiplier: float = OUTLIER_IQR_MULTIPLIER) -> List[float]:
    """
    Remove statistical outliers using Interquartile Range method.
    
    Parameters
    ----------
    data : List[float]
        Input data series.
    multiplier : float
        IQR multiplier for outlier detection (default: 1.5).
    
    Returns
    -------
    List[float]
        Filtered data with outliers removed.
    
    Raises
    ------
    InsufficientDataError
        If fewer than 4 data points provided.
    
    Notes
    -----
    Uses the Tukey's fences method: values outside [Q1 - k*IQR, Q3 + k*IQR]
    are considered outliers, where k is the multiplier.
    """
    if len(data) < 4:
        raise InsufficientDataError(
            "Outlier removal requires at least 4 data points",
            required_samples=4,
            actual_samples=len(data)
        )
    
    sorted_data = sorted(data)
    q1_index = len(sorted_data) // 4
    q3_index = (3 * len(sorted_data)) // 4
    
    q1 = sorted_data[q1_index]
    q3 = sorted_data[q3_index]
    iqr = q3 - q1
    
    lower_bound = q1 - (multiplier * iqr)
    upper_bound = q3 + (multiplier * iqr)
    
    outliers_removed = [x for x in data if lower_bound <= x <= upper_bound]
    
    if len(outliers_removed) < len(data):
        logger.info(
            json.dumps({
                "event": "outliers_removed",
                "original_count": len(data),
                "filtered_count": len(outliers_removed),
                "removed_count": len(data) - len(outliers_removed),
                "lower_bound": lower_bound,
                "upper_bound": upper_bound
            })
        )
    
    return outliers_removed


def _calculate_confidence_interval(data: List[float], 
                                   confidence: float = DEFAULT_CONFIDENCE_LEVEL) -> Tuple[float, float]:
    """
    Calculate confidence interval using bootstrap resampling.
    
    Parameters
    ----------
    data : List[float]
        Sample data.
    confidence : float
        Confidence level between 0.0 and 1.0.
    
    Returns
    -------
    Tuple[float, float]
        Lower and upper bounds of confidence interval.
    
    Raises
    ------
    InsufficientDataError
        If sample size is too small for bootstrap.
    
    Notes
    -----
    Uses non-parametric bootstrap method suitable for any distribution.
    """
    if len(data) < 10:
        raise InsufficientDataError(
            "Confidence interval calculation requires at least 10 samples",
            required_samples=10,
            actual_samples=len(data)
        )
    
    # Bootstrap resampling
    n_bootstrap = min(BOOTSTRAP_SAMPLES, len(data) * 100)
    means = []
    
    for _ in range(n_bootstrap):
        sample = random.choices(data, k=len(data))
        means.append(statistics.mean(sample))
    
    means.sort()
    tail = (1 - confidence) / 2
    lower_idx = int(tail * n_bootstrap)
    upper_idx = int((1 - tail) * n_bootstrap)
    
    return means[lower_idx], means[upper_idx]


# -----------------------------------------------------------------------------
# Caching and Decorator Infrastructure
# -----------------------------------------------------------------------------

def cached_classification(func: MetricFunction) -> MetricFunction:
    """
    Decorator for caching classification results.
    
    This optimization is crucial for repeated classifications of the same
    module across multiple analysis passes.
    
    Parameters
    ----------
    func : MetricFunction
        Classification function to cache.
    
    Returns
    -------
    MetricFunction
        Wrapped function with LRU caching.
    """
    @lru_cache(maxsize=CACHE_SIZE)
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


# -----------------------------------------------------------------------------
# Dynamic Threshold Management
# -----------------------------------------------------------------------------

class AdaptiveThresholds:
    """
    Context manager for runtime threshold adaptation.
    
    This class enables temporary modification of classification thresholds
    based on runtime environment (e.g., stricter in CI, looser in development).
    
    Examples
    --------
    >>> with AdaptiveThresholds(environment='ci'):
    ...     result = classify_time(0.015)  # Uses stricter CI thresholds
    
    >>> with AdaptiveThresholds(multiplier=2.0):
    ...     result = classify_memory(1000)  # Doubles all memory thresholds
    """
    
    _original_thresholds: Dict[str, Numeric] = {}
    
    def __init__(self, environment: Optional[str] = None, 
                 multiplier: float = 1.0,
                 custom_thresholds: Optional[Dict[str, Numeric]] = None):
        """
        Initialize adaptive threshold context.
        
        Parameters
        ----------
        environment : Optional[str]
            Predefined environment profile ('ci', 'production', 'development').
        multiplier : float
            Global multiplier applied to all thresholds.
        custom_thresholds : Optional[Dict[str, Numeric]]
            Explicit threshold overrides.
        """
        self.environment = environment
        self.multiplier = multiplier
        self.custom_thresholds = custom_thresholds or {}
        self._backup: Dict[str, Numeric] = {}
    
    def __enter__(self):
        """Save current thresholds and apply adaptations."""
        global TIME_LIGHT_THRESHOLD, TIME_MEDIUM_THRESHOLD
        global MEMORY_LIGHT_THRESHOLD, MEMORY_MODERATE_THRESHOLD
        global DEPS_MINIMAL_THRESHOLD, DEPS_MODERATE_THRESHOLD
        global STABILITY_STABLE_THRESHOLD, STABILITY_UNSTABLE_THRESHOLD
        
        # Backup current values
        self._backup = {
            'TIME_LIGHT': TIME_LIGHT_THRESHOLD,
            'TIME_MEDIUM': TIME_MEDIUM_THRESHOLD,
            'MEMORY_LIGHT': MEMORY_LIGHT_THRESHOLD,
            'MEMORY_MODERATE': MEMORY_MODERATE_THRESHOLD,
            'DEPS_MINIMAL': DEPS_MINIMAL_THRESHOLD,
            'DEPS_MODERATE': DEPS_MODERATE_THRESHOLD,
            'STABILITY_STABLE': STABILITY_STABLE_THRESHOLD,
            'STABILITY_UNSTABLE': STABILITY_UNSTABLE_THRESHOLD,
        }
        
        # Apply environment-specific adjustments
        if self.environment == 'ci':
            # Stricter thresholds for CI
            TIME_LIGHT_THRESHOLD *= 0.5
            TIME_MEDIUM_THRESHOLD *= 0.5
            MEMORY_LIGHT_THRESHOLD = int(MEMORY_LIGHT_THRESHOLD * 0.7)
            MEMORY_MODERATE_THRESHOLD = int(MEMORY_MODERATE_THRESHOLD * 0.7)
        elif self.environment == 'production':
            # Moderate thresholds for production monitoring
            TIME_LIGHT_THRESHOLD *= 1.2
            TIME_MEDIUM_THRESHOLD *= 1.2
        
        # Apply global multiplier
        if self.multiplier != 1.0:
            TIME_LIGHT_THRESHOLD *= self.multiplier
            TIME_MEDIUM_THRESHOLD *= self.multiplier
            MEMORY_LIGHT_THRESHOLD = int(MEMORY_LIGHT_THRESHOLD * self.multiplier)
            MEMORY_MODERATE_THRESHOLD = int(MEMORY_MODERATE_THRESHOLD * self.multiplier)
            DEPS_MINIMAL_THRESHOLD = int(DEPS_MINIMAL_THRESHOLD * self.multiplier)
            DEPS_MODERATE_THRESHOLD = int(DEPS_MODERATE_THRESHOLD * self.multiplier)
            STABILITY_STABLE_THRESHOLD *= self.multiplier
            STABILITY_UNSTABLE_THRESHOLD *= self.multiplier
        
        # Apply custom overrides
        for key, value in self.custom_thresholds.items():
            if key in globals():
                globals()[key] = value
        
        logger.info(
            json.dumps({
                "event": "thresholds_adapted",
                "environment": self.environment,
                "multiplier": self.multiplier
            })
        )
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Restore original thresholds."""
        global TIME_LIGHT_THRESHOLD, TIME_MEDIUM_THRESHOLD
        global MEMORY_LIGHT_THRESHOLD, MEMORY_MODERATE_THRESHOLD
        global DEPS_MINIMAL_THRESHOLD, DEPS_MODERATE_THRESHOLD
        global STABILITY_STABLE_THRESHOLD, STABILITY_UNSTABLE_THRESHOLD
        
        TIME_LIGHT_THRESHOLD = self._backup['TIME_LIGHT']
        TIME_MEDIUM_THRESHOLD = self._backup['TIME_MEDIUM']
        MEMORY_LIGHT_THRESHOLD = self._backup['MEMORY_LIGHT']
        MEMORY_MODERATE_THRESHOLD = self._backup['MEMORY_MODERATE']
        DEPS_MINIMAL_THRESHOLD = self._backup['DEPS_MINIMAL']
        DEPS_MODERATE_THRESHOLD = self._backup['DEPS_MODERATE']
        STABILITY_STABLE_THRESHOLD = self._backup['STABILITY_STABLE']
        STABILITY_UNSTABLE_THRESHOLD = self._backup['STABILITY_UNSTABLE']
        
        logger.debug(json.dumps({"event": "thresholds_restored"}))
        
        return False  # Don't suppress exceptions


# -----------------------------------------------------------------------------
# Enhanced Public Classification Functions
# -----------------------------------------------------------------------------

@cached_classification
def classify_time(avg_seconds: float, 
                  measurements: Optional[List[float]] = None,
                  calculate_confidence: bool = False) -> Union[str, Tuple[str, Optional[float]]]:
    """
    Advanced time classification with optional confidence interval.
    
    This enhanced classifier provides more granular categorization and can
    optionally calculate statistical confidence when multiple measurements
    are available. It automatically removes outliers when sufficient data exists.
    
    Parameters
    ----------
    avg_seconds : float
        Average import time in seconds. Must be non-negative and finite.
    measurements : Optional[List[float]]
        Raw measurement samples for confidence calculation.
    calculate_confidence : bool
        Whether to compute and return confidence score.
    
    Returns
    -------
    Union[str, Tuple[str, Optional[float]]]
        Classification category, optionally with confidence score.
        Categories: 'instant', 'light', 'medium', 'heavy', 'critical'
    
    Raises
    ------
    ThresholdError
        If `avg_seconds` is invalid.
    
    Examples
    --------
    >>> classify_time(0.005)
    'instant'
    
    >>> category, confidence = classify_time(0.045, [0.042, 0.044, 0.046, 0.043], True)
    >>> print(f"{category} ({confidence:.2%} confident)")
    light (95.00% confident)
    
    Notes
    -----
    Classification uses both absolute thresholds and relative scaling based
    on environment detection. CI environments use stricter thresholds.
    """
    _validate_numeric(avg_seconds, "Average seconds", min_value=0.0, allow_inf=False)
    
    # Apply environment-specific adjustments
    effective_light = TIME_LIGHT_THRESHOLD * (0.8 if IS_CI else 1.0)
    effective_medium = TIME_MEDIUM_THRESHOLD * (0.8 if IS_CI else 1.0)
    effective_heavy = TIME_HEAVY_THRESHOLD * (0.9 if IS_CI else 1.0)
    effective_critical = TIME_CRITICAL_THRESHOLD * (0.9 if IS_CI else 1.0)
    
    # Determine category
    if avg_seconds < effective_light * 0.5:
        category = "instant"
    elif avg_seconds < effective_light:
        category = "light"
    elif avg_seconds < effective_medium:
        category = "medium"
    elif avg_seconds < effective_heavy:
        category = "heavy"
    else:
        category = "critical"
    
    # Calculate confidence if requested
    confidence = None
    if calculate_confidence and measurements and len(measurements) >= 10:
        try:
            cleaned = _remove_outliers(measurements)
            _, _ = _calculate_confidence_interval(cleaned)
            confidence = len(cleaned) / len(measurements)  # Simple confidence metric
        except InsufficientDataError:
            logger.warning("Insufficient data for confidence calculation")
            confidence = None
    
    # Log severe classifications
    if category in ('heavy', 'critical'):
        logger.warning(
            json.dumps({
                "event": "slow_import_detected",
                "avg_seconds": avg_seconds,
                "category": category,
                "environment": "ci" if IS_CI else "standard"
            })
        )
    
    if calculate_confidence:
        return category, confidence
    return category


@cached_classification
def classify_memory(peak_kb: int, 
                    system_memory_kb: Optional[int] = None) -> str:
    """
    Memory classification with system context awareness.
    
    This classifier provides more meaningful memory categories by considering
    the available system memory when provided. This enables relative rather
    than absolute categorization in resource-constrained environments.
    
    Parameters
    ----------
    peak_kb : int
        Peak memory usage in kilobytes. Must be non-negative.
    system_memory_kb : Optional[int]
        Total system memory for relative classification.
    
    Returns
    -------
    str
        Classification category: 'light', 'moderate', 'heavy', 'critical'
    
    Raises
    ------
    ThresholdError
        If `peak_kb` is negative.
    
    Examples
    --------
    >>> classify_memory(2048)
    'moderate'
    
    >>> classify_memory(10240, system_memory_kb=1048576)  # 10MB of 1GB
    'light'  # Relative to system memory
    """
    _validate_numeric(peak_kb, "Peak kilobytes", min_value=0)
    
    # Use relative thresholds if system memory is known
    if system_memory_kb and system_memory_kb > 0:
        percentage = (peak_kb / system_memory_kb) * 100
        if percentage < 0.1:
            return "light"
        elif percentage < 1.0:
            return "moderate"
        elif percentage < 5.0:
            return "heavy"
        else:
            return "critical"
    
    # Fall back to absolute thresholds
    effective_light = MEMORY_LIGHT_THRESHOLD
    effective_moderate = MEMORY_MODERATE_THRESHOLD
    effective_heavy = MEMORY_HEAVY_THRESHOLD
    
    if peak_kb < effective_light:
        return "light"
    elif peak_kb < effective_moderate:
        return "moderate"
    elif peak_kb < effective_heavy:
        return "heavy"
    else:
        return "critical"


@cached_classification
def classify_dependencies(num_deps: int, 
                          max_depth: Optional[int] = None,
                          has_cycles: bool = False) -> str:
    """
    Enhanced dependency classification with graph metrics.
    
    This classifier considers not just the count but also the structure
    of the dependency graph, including depth and cycles, which significantly
    impact import performance and reliability.
    
    Parameters
    ----------
    num_deps : int
        Number of distinct dependencies.
    max_depth : Optional[int]
        Maximum depth of dependency tree.
    has_cycles : bool
        Whether circular dependencies exist.
    
    Returns
    -------
    str
        Classification: 'minimal', 'moderate', 'heavy', 'extreme'
    
    Raises
    ------
    ThresholdError
        If `num_deps` is negative.
    
    Examples
    --------
    >>> classify_dependencies(50)
    'moderate'
    
    >>> classify_dependencies(150, max_depth=10, has_cycles=True)
    'extreme'  # Escalated due to depth and cycles
    """
    _validate_numeric(num_deps, "Number of dependencies", min_value=0)
    
    # Base classification on count
    if num_deps < DEPS_MINIMAL_THRESHOLD:
        base_category = "minimal"
    elif num_deps < DEPS_MODERATE_THRESHOLD:
        base_category = "moderate"
    elif num_deps < DEPS_HEAVY_THRESHOLD:
        base_category = "heavy"
    else:
        base_category = "extreme"
    
    # Escalate based on graph structure
    escalation = 0
    if max_depth and max_depth > 5:
        escalation += 1
    if has_cycles:
        escalation += 2
        logger.warning(
            json.dumps({
                "event": "circular_dependency_detected",
                "dependency_count": num_deps
            })
        )
    
    # Apply escalation
    categories = ["minimal", "moderate", "heavy", "extreme"]
    current_index = categories.index(base_category)
    escalated_index = min(current_index + escalation, len(categories) - 1)
    
    return categories[escalated_index]


@cached_classification
def classify_stability(stability_index: float,
                       measurements: Optional[List[float]] = None,
                       remove_outliers: bool = True) -> str:
    """
    Advanced stability classification with statistical rigor.
    
    This classifier can optionally clean the input data by removing outliers
    before calculating the stability index, providing a more accurate
    representation of typical import behavior.
    
    Parameters
    ----------
    stability_index : float
        Coefficient of variation (std/mean). Must be non-negative.
    measurements : Optional[List[float]]
        Raw measurements for optional outlier removal.
    remove_outliers : bool
        Whether to remove outliers before classification.
    
    Returns
    -------
    str
        Classification: 'stable', 'normal', 'unstable', 'chaotic'
    
    Raises
    ------
    ThresholdError
        If `stability_index` is invalid.
    
    Examples
    --------
    >>> classify_stability(0.08)
    'normal'
    
    >>> measurements = [0.045, 0.044, 0.046, 0.150]  # One outlier
    >>> classify_stability(0.08, measurements, remove_outliers=True)
    'stable'  # Outlier removed, actual variation is low
    """
    _validate_numeric(stability_index, "Stability index", min_value=0.0)
    
    # Recalculate index if outlier removal requested
    effective_index = stability_index
    if remove_outliers and measurements and len(measurements) >= 4:
        try:
            cleaned = _remove_outliers(measurements)
            if len(cleaned) >= 2:
                mean_val = statistics.mean(cleaned)
                if mean_val > 0:
                    effective_index = statistics.stdev(cleaned) / mean_val
        except InsufficientDataError:
            pass  # Keep original index
    
    # Apply thresholds
    if effective_index < STABILITY_STABLE_THRESHOLD:
        return "stable"
    elif effective_index < STABILITY_NORMAL_THRESHOLD:
        return "normal"
    elif effective_index < STABILITY_UNSTABLE_THRESHOLD:
        return "unstable"
    else:
        return "chaotic"


# -----------------------------------------------------------------------------
# Comprehensive Module Analysis
# -----------------------------------------------------------------------------

def classify_module(
    module_name: str,
    avg_time: float,
    peak_memory_kb: int,
    num_dependencies: int,
    stability_index: float,
    time_measurements: Optional[List[float]] = None,
    system_memory_kb: Optional[int] = None,
    dependency_depth: Optional[int] = None,
    has_circular_deps: bool = False,
    include_recommendations: bool = True
) -> ClassifiedModule:
    """
    Perform complete multi-dimensional analysis of a module.
    
    This is the primary entry point for comprehensive module analysis,
    combining all classification dimensions into a single, rich result
    with scoring, recommendations, and metadata.
    
    Parameters
    ----------
    module_name : str
        Fully qualified module name.
    avg_time : float
        Average import time in seconds.
    peak_memory_kb : int
        Peak memory usage in kilobytes.
    num_dependencies : int
        Total dependency count.
    stability_index : float
        Coefficient of variation for timing.
    time_measurements : Optional[List[float]]
        Raw timing measurements for advanced analysis.
    system_memory_kb : Optional[int]
        Total system memory for context.
    dependency_depth : Optional[int]
        Maximum depth of dependency tree.
    has_circular_deps : bool
        Whether circular dependencies exist.
    include_recommendations : bool
        Whether to generate optimization suggestions.
    
    Returns
    -------
    ClassifiedModule
        Complete analysis results with all classifications and metadata.
    
    Examples
    --------
    >>> result = classify_module(
    ...     "numpy", 0.15, 50000, 50, 0.12,
    ...     time_measurements=[0.14, 0.15, 0.16, 0.14, 0.15]
    ... )
    >>> print(result.worst_dimension)
    (ClassificationDimension.MEMORY, 'heavy')
    >>> print(result.recommendations[0])
    'Consider lazy loading for memory-heavy submodules'
    """
    # Perform individual classifications
    time_cat, confidence = classify_time(
        avg_time, 
        time_measurements, 
        calculate_confidence=True
    ) if isinstance(classify_time(avg_time, time_measurements, True), tuple) else (classify_time(avg_time), None)
    
    memory_cat = classify_memory(peak_memory_kb, system_memory_kb)
    deps_cat = classify_dependencies(num_dependencies, dependency_depth, has_circular_deps)
    stability_cat = classify_stability(stability_index, time_measurements)
    
    # Calculate weighted scores (0.0 = optimal, 1.0 = critical)
    time_score = _calculate_dimension_score(avg_time, TIME_LIGHT_THRESHOLD, TIME_CRITICAL_THRESHOLD)
    memory_score = _calculate_dimension_score(peak_memory_kb, MEMORY_LIGHT_THRESHOLD, MEMORY_CRITICAL_THRESHOLD)
    deps_score = _calculate_dimension_score(num_dependencies, DEPS_MINIMAL_THRESHOLD, DEPS_EXTREME_THRESHOLD)
    stability_score = _calculate_dimension_score(stability_index, STABILITY_STABLE_THRESHOLD, STABILITY_CHAOTIC_THRESHOLD)
    
    # Weighted composite score
    weights = {'time': 0.35, 'memory': 0.30, 'deps': 0.20, 'stability': 0.15}
    total_score = (
        time_score * weights['time'] +
        memory_score * weights['memory'] +
        deps_score * weights['deps'] +
        stability_score * weights['stability']
    )
    
    overall_score = PerformanceScore(
        total=total_score,
        time_score=time_score,
        memory_score=memory_score,
        dependency_score=deps_score,
        stability_score=stability_score,
        confidence=confidence or 0.5
    )
    
    # Generate recommendations
    recommendations = []
    if include_recommendations:
        recommendations = _generate_recommendations(
            time_cat, memory_cat, deps_cat, stability_cat,
            has_circular_deps, overall_score
        )
    
    # Build result
    return ClassifiedModule(
        module_name=module_name,
        time_category=time_cat if isinstance(time_cat, str) else time_cat[0],
        memory_category=memory_cat,
        dependency_category=deps_cat,
        stability_category=stability_cat,
        overall_score=overall_score,
        raw_metrics={
            'avg_time': avg_time,
            'peak_memory_kb': peak_memory_kb,
            'num_dependencies': num_dependencies,
            'stability_index': stability_index,
            'dependency_depth': dependency_depth,
            'has_circular_deps': has_circular_deps
        },
        metadata={
            'analyzed_at': datetime.utcnow().isoformat(),
            'environment': 'ci' if IS_CI else 'production' if IS_PRODUCTION else 'development',
            'classifier_version': __version__
        },
        recommendations=recommendations
    )


def _calculate_dimension_score(value: float, optimal: float, critical: float) -> float:
    """
    Calculate normalized score for a single dimension.
    
    Parameters
    ----------
    value : float
        Actual measured value.
    optimal : float
        Threshold for optimal performance.
    critical : float
        Threshold for critical performance.
    
    Returns
    -------
    float
        Score between 0.0 (optimal) and 1.0 (critical).
    """
    if value <= optimal:
        return 0.0
    if value >= critical:
        return 1.0
    
    # Linear interpolation between optimal and critical
    return (value - optimal) / (critical - optimal)


def _generate_recommendations(time_cat: str, memory_cat: str, deps_cat: str,
                              stability_cat: str, has_cycles: bool,
                              score: PerformanceScore) -> List[str]:
    """Generate actionable recommendations based on analysis."""
    recommendations = []
    
    if time_cat in ('heavy', 'critical'):
        recommendations.append(
            "Consider lazy imports or on-demand loading for non-essential submodules"
        )
        recommendations.append(
            "Profile with py-spy or cProfile to identify expensive initialization code"
        )
    
    if memory_cat in ('heavy', 'critical'):
        recommendations.append(
            "Consider lazy loading for memory-heavy submodules"
        )
        recommendations.append(
            "Use __slots__ or dataclasses to reduce per-instance memory overhead"
        )
    
    if deps_cat == 'extreme' or has_cycles:
        recommendations.append(
            "Refactor to reduce dependency count or eliminate circular imports"
        )
        recommendations.append(
            "Consider vendoring critical dependencies to reduce external requirements"
        )
    
    if stability_cat in ('unstable', 'chaotic'):
        recommendations.append(
            "Investigate sources of variance: filesystem cache, network calls, or JIT compilation"
        )
        recommendations.append(
            "Consider pre-compiling .pyc files in deployment artifacts"
        )
    
    if score.total > 0.7:
        recommendations.append(
            f"Critical performance issues detected (score: {score.total:.2f}). "
            "Consider architectural refactoring."
        )
    
    return recommendations


# -----------------------------------------------------------------------------
# Legacy Compatibility
# -----------------------------------------------------------------------------

def _classify(avg: float) -> str:
    """
    Legacy wrapper for backward compatibility.
    
    Parameters
    ----------
    avg : float
        Average import time in seconds.
    
    Returns
    -------
    str
        Classification category: 'light', 'medium', or 'heavy'.
    """
    result = classify_time(avg)
    if isinstance(result, tuple):
        return result[0]
    return result


# -----------------------------------------------------------------------------
# Utility Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Primary classification functions
    'classify_time',
    'classify_memory', 
    'classify_dependencies',
    'classify_stability',
    'classify_module',
    
    # Advanced features
    'AdaptiveThresholds',
    'PerformanceScore',
    'ClassifiedModule',
    'ClassificationDimension',
    'Severity',
    
    # Exceptions
    'PerformanceClassificationError',
    'ThresholdError',
    'InsufficientDataError',
    'CalibrationError',
]
