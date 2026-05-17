#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import statistics
from typing import List, Dict, Optional
from collections import defaultdict, Counter

from .base import SeverityConfig, SeverityLevel, CallResult, FunctionAnalysis


class HealthScoreCalculator:
    """
    Calculator for health scores and metrics.

    Parameters
    ----------
    severity_config : Optional[SeverityConfig], optional
        Custom severity configuration (default: None, uses default).

    Examples
    --------
    >>> calculator = HealthScoreCalculator()
    >>> results = [call_result1, call_result2, ...]
    >>> health_score = calculator.calculate_overall_health(results)
    """

    def __init__(self, severity_config: Optional[SeverityConfig] = None):
        self.severity_config = severity_config or SeverityConfig()

    def calculate_overall_health(self, results: List[CallResult]) -> Dict[str, float]:
        """
        Calculate health metrics.

        Parameters
        ----------
        results : List[CallResult]
            List of execution results.

        Returns
        -------
        Dict[str, float]
            Dictionary containing all health metrics:
            - health_score: Overall health score (0-100)
            - stability_score: Execution stability (0-100)
            - performance_score: Performance efficiency (0-100)
            - reliability_score: Error handling reliability (0-100)

        Notes
        -----
        Scores are weighted and normalized to 0-100 range.
        Higher scores indicate better health.
        """
        if not results:
            return {
                "health_score": 100.0,
                "stability_score": 100.0,
                "performance_score": 100.0,
                "reliability_score": 100.0,
            }

        # Calculate component scores
        stability = self._calculate_stability_score(results)
        performance = self._calculate_performance_score(results)
        reliability = self._calculate_reliability_score(results)

        # Weighted overall health score
        weights = {"stability": 0.4, "performance": 0.3, "reliability": 0.3}
        health_score = (
            stability * weights["stability"]
            + performance * weights["performance"]
            + reliability * weights["reliability"]
        )

        return {
            "health_score": round(health_score, 2),
            "stability_score": round(stability, 2),
            "performance_score": round(performance, 2),
            "reliability_score": round(reliability, 2),
        }

    def _calculate_stability_score(self, results: List[CallResult]) -> float:
        """
        Calculate stability score based on exception rates.

        Parameters
        ----------
        results : List[CallResult]
            Execution results.

        Returns
        -------
        float
            Stability score (0-100).
        """
        if not results:
            return 100.0

        total = len(results)
        weights = self.severity_config.weights

        # Weighted sum of severity scores
        weighted_sum = sum(weights.get(r.severity, 0.0) for r in results)

        # Normalize to 0-100
        stability = (weighted_sum / total) * 100

        # Penalize timeouts heavily
        timeout_count = sum(1 for r in results if r.timed_out)
        if timeout_count > 0:
            timeout_penalty = (timeout_count / total) * 50  # Up to 50% penalty
            stability = max(0, stability - timeout_penalty)

        return stability

    def _calculate_performance_score(self, results: List[CallResult]) -> float:
        """
        Calculate performance score based on execution metrics.

        Parameters
        ----------
        results : List[CallResult]
            Execution results.

        Returns
        -------
        float
            Performance score (0-100).
        """
        if not results:
            return 100.0

        # Filter out failed executions for performance analysis
        valid_results = [
            r for r in results if r.severity in [SeverityLevel.OK, SeverityLevel.NOISE]
        ]

        if not valid_results:
            return 50.0  # Moderate penalty if all failed

        # Calculate time and memory percentiles
        times = [r.exec_time_ms for r in valid_results]
        memories = [r.memory_kb for r in valid_results]

        if not times or not memories:
            return 75.0

        # Normalize performance metrics
        time_score = self._normalize_performance_metric(
            times,
            ideal_max=100,  # 100ms is ideal max
            critical_max=1000,  # 1000ms is critical
        )

        memory_score = self._normalize_performance_metric(
            memories,
            ideal_max=1024,  # 1MB is ideal max
            critical_max=10240,  # 10MB is critical
        )

        # Combine scores (equal weight)
        performance_score = (time_score + memory_score) / 2

        return performance_score

    def _normalize_performance_metric(
        self, values: List[float], ideal_max: float, critical_max: float
    ) -> float:
        """
        Normalize performance metric values to 0-100 score.

        Parameters
        ----------
        values : List[float]
            Performance metric values.
        ideal_max : float
            Maximum ideal value (scores 100 at or below this).
        critical_max : float
            Critical threshold (scores 0 at or above this).

        Returns
        -------
        float
            Normalized score (0-100).
        """
        if not values:
            return 100.0

        # Use 90th percentile to ignore outliers
        try:
            percentile = sorted(values)[int(len(values) * 0.9)]
        except IndexError:
            percentile = values[-1]

        if percentile <= ideal_max:
            return 100.0
        elif percentile >= critical_max:
            return 0.0
        else:
            # Linear interpolation between ideal_max and critical_max
            return 100.0 * (1 - (percentile - ideal_max) / (critical_max - ideal_max))

    def _calculate_reliability_score(self, results: List[CallResult]) -> float:
        """
        Calculate reliability score based on error patterns.

        Parameters
        ----------
        results : List[CallResult]
            Execution results.

        Returns
        -------
        float
            Reliability score (0-100).
        """
        if not results:
            return 100.0

        # Group results by function
        func_results = defaultdict(list)
        for r in results:
            func_name = r.target
            func_results[func_name].append(r)

        # Calculate consistency per function
        consistency_scores = []
        for func_name, func_res in func_results.items():
            if len(func_res) < 2:
                continue

            # Check if all executions have same outcome
            first_severity = func_res[0].severity
            consistent = all(r.severity == first_severity for r in func_res[1:])

            if consistent:
                # High score for consistent behavior
                severity_weight = self.severity_config.weights.get(first_severity, 0.5)
                consistency_scores.append(severity_weight * 100)
            else:
                # Penalize inconsistent behavior
                consistency_scores.append(30.0)

        if consistency_scores:
            reliability = statistics.mean(consistency_scores)
        else:
            reliability = 75.0  # Default for single executions

        # Bonus for graceful error handling (NOISE vs CRITICAL)
        noise_count = sum(1 for r in results if r.severity == SeverityLevel.NOISE)
        critical_count = sum(1 for r in results if r.severity == SeverityLevel.CRITICAL)

        if noise_count > 0:
            # Functions that return graceful errors get bonus
            reliability = min(100, reliability + 5)

        if critical_count > 0:
            # Functions with critical errors get penalty
            reliability = max(0, reliability - 10)

        return reliability

    def generate_recommendations(
        self, results: List[CallResult], functions: Dict[str, FunctionAnalysis]
    ) -> List[str]:
        """
        Generate improvement recommendations based on analysis.

        Parameters
        ----------
        results : List[CallResult]
            All execution results.
        functions : Dict[str, FunctionAnalysis]
            Function analysis dictionary.

        Returns
        -------
        List[str]
            List of recommendations.
        """
        recommendations = []

        # Check for common issues
        timeout_funcs = [r.target for r in results if r.timed_out]
        if timeout_funcs:
            rec = (
                f"Found {len(set(timeout_funcs))} function(s) with timeout issues. "
                f"Consider optimizing: {', '.join(sorted(set(timeout_funcs))[:5])}"
            )
            recommendations.append(rec)

        # Check for memory issues
        high_memory = [
            (r.target, r.memory_kb) for r in results if r.memory_kb > 10240
        ]  # > 10MB
        if high_memory:
            top_offender = max(high_memory, key=lambda x: x[1])
            rec = (
                f"Memory usage concerns detected. Highest usage: "
                f"{top_offender[0]} used {top_offender[1]/1024:.1f} MB"
            )
            recommendations.append(rec)

        # Check for performance issues
        slow_funcs = [
            (r.target, r.exec_time_ms) for r in results if r.exec_time_ms > 500
        ]  # > 500ms
        if slow_funcs:
            slowest = max(slow_funcs, key=lambda x: x[1])
            rec = (
                f"Performance bottlenecks detected. Slowest: "
                f"{slowest[0]} took {slowest[1]:.0f} ms"
            )
            recommendations.append(rec)

        # Check for exception patterns
        exception_counts = Counter(r.exception for r in results if r.exception)
        common_exceptions = exception_counts.most_common(3)
        if common_exceptions:
            exc_list = [f"{exc} ({count}x)" for exc, count in common_exceptions]
            rec = f"Common exceptions: {', '.join(exc_list)}"
            recommendations.append(rec)

        # Check for inconsistent behavior
        for func_name, analysis in functions.items():
            if len(analysis.results) >= 3:
                severities = [r.severity for r in analysis.results]
                if len(set(severities)) > 2:  # More than 2 different outcomes
                    rec = f"Function '{func_name}' shows inconsistent behavior"
                    recommendations.append(rec)

        return recommendations[:10]  # Limit to top 10 recommendations
