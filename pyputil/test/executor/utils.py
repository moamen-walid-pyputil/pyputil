#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import inspect
import statistics
from typing import List
from collections import Counter

from .base import CallResult, FunctionAnalysis, SeverityLevel


def _analyze_function(name: str, results: List[CallResult]) -> FunctionAnalysis:
    """
    Analyze execution results for a single function.

    Parameters
    ----------
    name : str
        Function name.
    results : List[CallResult]
        Execution results for the function.

    Returns
    -------
    FunctionAnalysis
        Comprehensive function analysis.
    """
    if not results:
        return FunctionAnalysis(
            name=name.split(".")[-1],
            full_name=name,
            success_rate=0.0,
        )

    # Calculate basic metrics
    success_count = sum(
        1 for r in results if r.severity in [SeverityLevel.OK, SeverityLevel.NOISE]
    )
    success_rate = (success_count / len(results)) * 100

    # Performance metrics
    exec_times = [r.exec_time_ms for r in results]
    memories = [r.memory_kb for r in results]

    # Exception analysis
    exception_count = Counter(r.exception for r in results if r.exception)

    # Severity distribution
    severity_dist = Counter(r.severity for r in results)

    return FunctionAnalysis(
        name=name.split(".")[-1],
        full_name=name,
        results=results,
        success_rate=round(success_rate, 2),
        avg_exec_time_ms=statistics.mean(exec_times) if exec_times else 0.0,
        avg_memory_kb=statistics.mean(memories) if memories else 0.0,
        max_exec_time_ms=max(exec_times) if exec_times else 0.0,
        max_memory_kb=max(memories) if memories else 0.0,
        exception_count=dict(exception_count),
        severity_distribution=dict(severity_dist),
    )
