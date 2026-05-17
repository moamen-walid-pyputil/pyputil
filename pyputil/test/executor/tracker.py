#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import inspect
import types
import time
import traceback
import random
import statistics
from typing import Optional
from collections import Counter

from .base import SeverityConfig, ModuleTraceResults, SeverityLevel, CallResult
from .fuzzing import Fuzzing
from .execution import Execution
from .health_calculator import HealthScoreCalculator
from .utils import _analyze_function


def track_module(
    module: types.ModuleType,
    fuzz_rounds: int = 3,
    timeout_sec: int = 2,
    max_depth: int = 2,
    include_private: bool = False,
    random_seed: Optional[int] = None,
    severity_config: Optional[SeverityConfig] = None,
) -> ModuleTraceResults:
    """
    A function for tracking modules.

    Parameters
    ----------
    module : types.ModuleType
        Target Python module to trace.
    fuzz_rounds : int, optional
        Number of fuzzing rounds per callable (default: 3).
        Higher values provide more thorough testing but take longer.
    timeout_sec : int, optional
        Execution timeout per call in seconds (default: 2).
        Prevents infinite loops and excessive execution times.
    max_depth : int, optional
        Maximum depth for generating nested data structures (default: 2).
        Controls complexity of generated test inputs.
    include_private : bool, optional
        Whether to include private methods (starting with '_') (default: False).
        Enable for more thorough testing of internal APIs.
    random_seed : Optional[int], optional
        Random seed for reproducible fuzzing (default: None).
        Set for deterministic test execution.
    severity_config : Optional[SeverityConfig], optional
        Custom severity configuration (default: None).
        Use to customize scoring weights and thresholds.

    Raises
    ------
    TypeError
        If `module` is not a Python module.
    ValueError
        If module cannot be analyzed.

    Examples
    --------
    Basic usage:
    >>> import my_module
    >>> results = trace_module(my_module)
    >>> print(f"Health Score: {results.health_score}%")
    >>> print(f"Total functions tested: {results.total_functions}")

    Usage with custom configuration:
    >>> config = SeverityConfig()
    >>> config.weights[SeverityLevel.PERFORMANCE] = 0.8
    >>> results = trace_module(
    ...     my_module,
    ...     fuzz_rounds=5,
    ...     timeout_sec=5,
    ...     random_seed=42,
    ...     severity_config=config
    ... )

    See Also
    --------
    Fuzzing : For custom fuzzing strategies
    Execution : For custom execution configurations
    HealthScoreCalculator : For custom health metrics
    """
    # Input validation
    if not isinstance(module, types.ModuleType):
        raise TypeError(f"Expected a Python module, got {type(module).__name__}")

    start_time = time.time()

    # Initialize components
    fuzzer = Fuzzing(max_depth=max_depth, include_edge_cases=True, seed=random_seed)

    executor = Execution(
        timeout_sec=timeout_sec,
        enable_memory_tracking=True,
        capture_stack_trace=True,
        severity_config=severity_config,
    )

    calculator = HealthScoreCalculator(severity_config)

    # Prepare results structure
    module_path = getattr(module, "__file__", "unknown")
    results = ModuleTraceResults(
        module=module.__name__,
        module_path=module_path,
        timestamp=time.time(),
        total_calls=0,
        total_functions=0,
        duration_seconds=0.0,
    )

    functions = {}

    # Analyze all module members
    for name, obj in inspect.getmembers(module):
        # Skip private members unless requested
        if name.startswith("_") and not include_private:
            continue

        # Handle functions
        if inspect.isfunction(obj) and obj.__module__ == module.__name__:
            func_name = f"{module.__name__}.{name}"
            func_results = []

            for round_num in range(fuzz_rounds):
                try:
                    result = executor.execute(
                        func=obj,
                        target_name=func_name,
                        category="function",
                        round_number=round_num,
                        fuzzer=fuzzer,
                    )
                    func_results.append(result)
                    results.results.append(result)
                    results.total_calls += 1
                except Exception as e:
                    # Capture errors in the tracing process itself
                    error_result = CallResult(
                        target=func_name,
                        signature=None,
                        args=[],
                        kwargs={},
                        exception=type(e).__name__,
                        message=f"Tracing failed: {str(e)}",
                        stack_trace=traceback.format_exc(),
                        exec_time_ms=0.0,
                        memory_kb=0.0,
                        timed_out=False,
                        severity=SeverityLevel.CRITICAL,
                        category="function",
                        round_number=round_num,
                    )
                    func_results.append(error_result)
                    results.results.append(error_result)
                    results.total_calls += 1

            # Create function analysis
            if func_results:
                analysis = _analyze_function(func_name, func_results)
                functions[func_name] = analysis

        # Handle classes
        elif inspect.isclass(obj) and obj.__module__ == module.__name__:
            # Test class instantiation
            class_name = f"{module.__name__}.{name}"

            # Try to instantiate the class
            try:
                instance = obj()
                instantiation_success = True
            except Exception as e:
                # Record instantiation failure
                instantiation_result = CallResult(
                    target=f"{class_name}.__init__",
                    signature=None,
                    args=[],
                    kwargs={},
                    exception=type(e).__name__,
                    message=f"Instantiation failed: {str(e)}",
                    stack_trace=traceback.format_exc(),
                    exec_time_ms=0.0,
                    memory_kb=0.0,
                    timed_out=False,
                    severity=SeverityLevel.WARNING,
                    category="class_init",
                    round_number=0,
                )
                results.results.append(instantiation_result)
                results.total_calls += 1
                instantiation_success = False
                instance = None

            # Test class methods if instantiation was successful
            if instantiation_success and instance is not None:
                for meth_name, meth in inspect.getmembers(instance, inspect.ismethod):
                    if meth_name.startswith("_") and not include_private:
                        continue

                    full_meth_name = f"{class_name}.{meth_name}"
                    meth_results = []

                    for round_num in range(fuzz_rounds):
                        try:
                            result = executor.execute(
                                func=meth,
                                target_name=full_meth_name,
                                category="method",
                                round_number=round_num,
                                fuzzer=fuzzer,
                            )
                            meth_results.append(result)
                            results.results.append(result)
                            results.total_calls += 1
                        except Exception as e:
                            error_result = CallResult(
                                target=full_meth_name,
                                signature=None,
                                args=[],
                                kwargs={},
                                exception=type(e).__name__,
                                message=f"Tracing failed: {str(e)}",
                                stack_trace=traceback.format_exc(),
                                exec_time_ms=0.0,
                                memory_kb=0.0,
                                timed_out=False,
                                severity=SeverityLevel.CRITICAL,
                                category="method",
                                round_number=round_num,
                            )
                            meth_results.append(error_result)
                            results.results.append(error_result)
                            results.total_calls += 1

                    # Create method analysis
                    if meth_results:
                        analysis = _analyze_function(full_meth_name, meth_results)
                        functions[full_meth_name] = analysis

    # Calculate duration
    results.duration_seconds = time.time() - start_time

    # Update counts
    results.total_functions = len(functions)
    results.functions = functions

    # Calculate health metrics
    health_metrics = calculator.calculate_overall_health(results.results)
    results.health_score = health_metrics["health_score"]
    results.stability_score = health_metrics["stability_score"]
    results.performance_score = health_metrics["performance_score"]
    results.reliability_score = health_metrics["reliability_score"]

    # Generate statistics
    results.exception_summary = Counter(
        r.exception for r in results.results if r.exception
    )
    results.severity_summary = Counter(r.severity for r in results.results)

    # Calculate performance statistics
    if results.results:
        exec_times = [r.exec_time_ms for r in results.results]
        memories = [r.memory_kb for r in results.results]

        results.performance_stats = {
            "avg_exec_time_ms": statistics.mean(exec_times),
            "median_exec_time_ms": statistics.median(exec_times),
            "max_exec_time_ms": max(exec_times),
            "avg_memory_kb": statistics.mean(memories),
            "max_memory_kb": max(memories),
            "total_timeouts": sum(1 for r in results.results if r.timed_out),
        }

    # Generate recommendations
    results.recommendations = calculator.generate_recommendations(
        results.results, functions
    )

    # Identify critical issues
    results.critical_issues = [
        f"{r.target}: {r.exception} - {r.message}"
        for r in results.results
        if r.severity in [SeverityLevel.CRITICAL, SeverityLevel.SECURITY]
    ][
        :20
    ]  # Limit to top 20 issues

    return results
