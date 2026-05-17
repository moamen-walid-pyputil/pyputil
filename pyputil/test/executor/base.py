#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
import inspect


class AttributeType(Enum):
    """Enumeration of possible attribute types in a module."""

    FUNCTION = "function"
    CLASS = "class"
    MODULE = "module"
    METHOD = "method"
    PROPERTY = "property"
    BUILTIN = "builtin"
    VARIABLE = "variable"
    UNKNOWN = "unknown"


@dataclass
class AttributeInfo:
    """
    Comprehensive information about a single attribute in a module.

    Attributes
    ----------
    name : str
        Name of the attribute
    type : AttributeType
        Type of the attribute (function, class, variable, etc.)
    value : Any, optional
        Value of the attribute after execution (if applicable)
    docstring : Optional[str]
        Documentation string of the attribute
    signature : Optional[str]
        Function/method signature (if applicable)
    is_callable : bool
        Whether the attribute can be called
    is_instantiated : bool
        Whether the attribute was instantiated/called
    is_private : bool
        Whether the attribute is private (starts with '_')
    has_arguments : bool
        Whether the attribute requires arguments
    source_file : Optional[str]
        Path to the source file containing the attribute
    source_line : Optional[int]
        Starting line number in the source file
    members : Dict[str, 'AttributeInfo']
        Nested attributes (for classes/modules)
    error : Optional[str]
        Error message if execution failed
    """

    name: str
    type: AttributeType
    value: Any = None
    docstring: Optional[str] = None
    signature: Optional[str] = None
    is_callable: bool = False
    is_instantiated: bool = False
    is_private: bool = False
    has_arguments: bool = False
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    members: Dict[str, "AttributeInfo"] = field(default_factory=dict)
    error: Optional[str] = None

    def __str__(self) -> str:
        """String representation of the attribute."""
        return f"{self.name}: {self.type.value} = {repr(self.value) if self.value is not None else 'None'}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert the attribute info to a dictionary."""
        return {
            "name": self.name,
            "type": self.type.value,
            "value": self.value,
            "docstring": self.docstring,
            "signature": self.signature,
            "is_callable": self.is_callable,
            "is_instantiated": self.is_instantiated,
            "is_private": self.is_private,
            "has_arguments": self.has_arguments,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "error": self.error,
            "members_count": len(self.members),
        }


@dataclass
class ModuleResult:
    """
    Comprehensive result about a module's attributes and their execution.

    Attributes
    ----------
    module_name : str
        Name of the analyzed module
    file : Optional[str]
        Path to the module file
    total_attributes : int
        Total number of attributes analyzed
    functions_called : int
        Number of functions successfully called
    classes_instantiated : int
        Number of classes successfully instantiated
    errors_count : int
        Number of errors encountered
    attributes : Dict[str, AttributeInfo]
        Dictionary of all analyzed attributes
    summary : Dict[str, int]
        Summary statistics by attribute type
    execution_time : float
        Time taken to analyze the module (in seconds)
    """

    module_name: str
    file: Optional[str]
    total_attributes: int = 0
    functions_called: int = 0
    classes_instantiated: int = 0
    errors_count: int = 0
    execution_time: float = 0.0
    attributes: Dict[str, AttributeInfo] = field(default_factory=dict)
    summary: Dict[str, int] = field(default_factory=dict)

    def __str__(self) -> str:
        """Human-readable string representation of the result."""
        lines = [
            f"Module result: {self.module_name}",
            f"File: {self.file or 'Unknown'}",
            f"Total Attributes: {self.total_attributes}",
            f"Functions Called: {self.functions_called}",
            f"Classes Instantiated: {self.classes_instantiated}",
            f"Errors: {self.errors_count}",
            f"Execution Time: {self.execution_time:.3f}s",
            "-" * 50,
        ]

        for name, info in sorted(self.attributes.items()):
            status_parts = []
            if info.error:
                status_parts.append(f"ERROR: {info.error}")
            elif info.has_arguments:
                status_parts.append("requires arguments")
            elif info.is_instantiated:
                status_parts.append("executed")

            status = f" [{', '.join(status_parts)}]" if status_parts else ""

            lines.append(f"{name:20} : {info.type.value:12}{status}")
            if info.value is not None:
                lines.append(f"    Value: {repr(info.value)}")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the result to a dictionary.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation of the result
        """
        return {
            "module": self.module_name,
            "file": self.file,
            "stats": {
                "total_attributes": self.total_attributes,
                "functions_called": self.functions_called,
                "classes_instantiated": self.classes_instantiated,
                "errors_count": self.errors_count,
                "execution_time": self.execution_time,
            },
            "summary": self.summary,
            "attributes": {
                name: info.to_dict() for name, info in self.attributes.items()
            },
        }

    def get_by_type(self, attr_type: AttributeType) -> List[AttributeInfo]:
        """
        Get all attributes of a specific type.

        Parameters
        ----------
        attr_type : AttributeType
            Type of attributes to retrieve

        Returns
        -------
        List[AttributeInfo]
            List of attributes matching the specified type
        """
        return [info for info in self.attributes.values() if info.type == attr_type]

    def get_errors(self) -> List[AttributeInfo]:
        """Get all attributes that had errors during execution."""
        return [info for info in self.attributes.values() if info.error]


class SeverityLevel(Enum):
    """Enumerated severity levels for execution results."""

    OK = auto()
    NOISE = auto()  # Expected errors (e.g., type errors from fuzzing)
    PERFORMANCE = auto()  # Performance issues (slow execution)
    MEMORY = auto()  # Memory usage issues
    WARNING = auto()  # Non-critical runtime warnings
    CRITICAL = auto()  # Critical failures
    TIMEOUT = auto()  # Execution timeout
    SECURITY = auto()  # Potential security issues


@dataclass
class SeverityConfig:
    """
    Configuration for severity scoring and classification.

    Attributes
    ----------
    weights : Dict[SeverityLevel, float]
            Weight for each severity level (0-1 scale).
    thresholds : Dict[str, float]
            Performance thresholds for classification.
    """

    weights: Dict[SeverityLevel, float] = field(
        default_factory=lambda: {
            SeverityLevel.OK: 1.0,
            SeverityLevel.NOISE: 0.95,
            SeverityLevel.PERFORMANCE: 0.75,
            SeverityLevel.MEMORY: 0.70,
            SeverityLevel.WARNING: 0.60,
            SeverityLevel.SECURITY: 0.50,
            SeverityLevel.CRITICAL: 0.25,
            SeverityLevel.TIMEOUT: 0.10,
        }
    )

    # Performance thresholds
    thresholds: Dict[str, float] = field(
        default_factory=lambda: {
            "timeout_ms": 1000,  # 1 second timeout threshold
            "slow_execution_ms": 100,  # 100ms considered slow
            "high_memory_kb": 10240,  # 10MB considered high memory
            "excessive_memory_kb": 102400,  # 100MB excessive
        }
    )


# ==========================================================
# Data Structures
# ==========================================================


@dataclass
class CallResult:
    """
    Detailed result of a single callable execution.

    Attributes
    ----------
    target : str
            Fully qualified name of the target callable.
    signature : inspect.Signature
            Signature of the callable.
    args : List[Any]
            Arguments used in the call.
    kwargs : Dict[str, Any]
            Keyword arguments used in the call.
    exception : Optional[str]
            Type of exception raised, if any.
    message : Optional[str]
            Exception message or custom message.
    stack_trace : Optional[str]
            Full stack trace for debugging.
    exec_time_ms : float
            Execution time in milliseconds.
    memory_kb : float
            Peak memory usage in kilobytes.
    timed_out : bool
            Whether execution timed out.
    severity : SeverityLevel
            Severity level of the result.
    category : str
            Category of the callable (function, method, etc.)
    round_number : int
            Which fuzz round this result belongs to.
    """

    target: str
    signature: Optional[inspect.Signature]
    args: List[Any]
    kwargs: Dict[str, Any]
    exception: Optional[str]
    message: Optional[str]
    stack_trace: Optional[str]
    exec_time_ms: float
    memory_kb: float
    timed_out: bool
    severity: SeverityLevel
    category: str
    round_number: int


@dataclass
class FunctionAnalysis:
    """
    Aggregated analysis for a single function/method.

    Attributes
    ----------
    name : str
            Name of the function.
    full_name : str
            Fully qualified name.
    results : List[CallResult]
            All execution results for this function.
    success_rate : float
            Percentage of successful executions (0-100).
    avg_exec_time_ms : float
            Average execution time.
    avg_memory_kb : float
            Average memory usage.
    max_exec_time_ms : float
            Maximum execution time.
    max_memory_kb : float
            Maximum memory usage.
    exception_count : Dict[str, int]
            Count of each exception type.
    severity_distribution : Dict[SeverityLevel, int]
            Distribution of severity levels.
    """

    name: str
    full_name: str
    results: List[CallResult] = field(default_factory=list)
    success_rate: float = 0.0
    avg_exec_time_ms: float = 0.0
    avg_memory_kb: float = 0.0
    max_exec_time_ms: float = 0.0
    max_memory_kb: float = 0.0
    exception_count: Dict[str, int] = field(default_factory=dict)
    severity_distribution: Dict[SeverityLevel, int] = field(default_factory=dict)


@dataclass
class ModuleTraceResults:
    """
    Comprehensive trace results for an entire module.

    Attributes
    ----------
    module : str
            Name of the traced module.
    module_path : str
            File path of the module.
    timestamp : float
            When the trace was performed.
    total_calls : int
            Total number of calls made.
    total_functions : int
            Number of unique functions/methods traced.
    duration_seconds : float
            Total trace duration.

    # Health Metrics
    health_score : float
            Overall health score (0-100).
    stability_score : float
            Execution stability score.
    performance_score : float
            Performance efficiency score.
    reliability_score : float
            Reliability and error handling score.

    # Detailed Results
    functions : Dict[str, FunctionAnalysis]
            Analysis per function.
    results : List[CallResult]
            All individual call results.

    # Statistics
    exception_summary : Dict[str, int]
            Summary of all exceptions.
    severity_summary : Dict[SeverityLevel, int]
            Summary of severity levels.
    performance_stats : Dict[str, float]
            Performance statistics.

    # Recommendations
    recommendations : List[str]
            Recommendations for improvement.
    critical_issues : List[str]
            List of critical issues found.
    """

    module: str
    module_path: str
    timestamp: float
    total_calls: int
    total_functions: int
    duration_seconds: float

    # Health Metrics
    health_score: float = 0.0
    stability_score: float = 0.0
    performance_score: float = 0.0
    reliability_score: float = 0.0

    # Detailed Results
    functions: Dict[str, FunctionAnalysis] = field(default_factory=dict)
    results: List[CallResult] = field(default_factory=list)

    # Statistics
    exception_summary: Dict[str, int] = field(default_factory=dict)
    severity_summary: Dict[SeverityLevel, int] = field(default_factory=dict)
    performance_stats: Dict[str, float] = field(default_factory=dict)

    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    critical_issues: List[str] = field(default_factory=list)

    def _calculate_success_rate(self) -> float:
        """Calculate overall success rate."""
        if not self.results:
            return 100.0
        success_count = sum(
            1
            for r in self.results
            if r.severity in [SeverityLevel.OK, SeverityLevel.NOISE]
        )
        return round((success_count / len(self.results)) * 100, 2)
