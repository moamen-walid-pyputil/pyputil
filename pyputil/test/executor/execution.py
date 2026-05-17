#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import signal
import sys
import time
import traceback
import tracemalloc
import random
import inspect
from typing import Any, List, Optional, Dict, Tuple, Callable
from collections import defaultdict

from .base import SeverityConfig, SeverityLevel, CallResult


class Execution:
    """
    for safely executing functions.

    Parameters
    ----------
    timeout_sec : int, optional
        Execution timeout in seconds (default: 2).
    enable_memory_tracking : bool, optional
        Whether to track memory usage (default: True).
    capture_stack_trace : bool, optional
        Whether to capture full stack traces (default: True).
    severity_config : Optional[SeverityConfig], optional
        Custom severity configuration (default: None, uses default).
    """

    def __init__(
        self,
        timeout_sec: int = 2,
        enable_memory_tracking: bool = True,
        capture_stack_trace: bool = True,
        severity_config: Optional[SeverityConfig] = None,
    ):
        self.timeout_sec = timeout_sec
        self.enable_memory_tracking = enable_memory_tracking
        self.capture_stack_trace = capture_stack_trace
        self.severity_config = severity_config or SeverityConfig()
        self._timeout_handler_set = False

    def execute(
        self,
        func: Callable,
        target_name: str,
        category: str,
        round_number: int,
        fuzzer: "Fuzzing",
    ) -> CallResult:
        """
        Execute a function with fuzzed inputs and capture diagnostics.

        Parameters
        ----------
        func : Callable
            Function or method to execute.
        target_name : str
            Fully qualified name for identification.
        category : str
            Category of the callable (function, method, etc.)
        round_number : int
            Which fuzz round this execution belongs to.
        fuzzer : Fuzzing
            Fuzzing for generating inputs.

        Returns
        -------
        CallResult
            Detailed execution result with diagnostics.

        Raises
        ------
        ValueError
            If the function cannot be analyzed.
        """
        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):
            sig = None

        # Generate arguments based on signature
        args, kwargs = self._generate_arguments(func, sig, fuzzer)

        # Setup timeout handler
        self._setup_timeout_handler()

        # Initialize metrics
        start_time = time.perf_counter()
        exception = message = stack_trace = None
        timed_out = False
        memory_kb = 0.0

        if self.enable_memory_tracking:
            tracemalloc.start()

        try:
            # Set alarm for timeout
            signal.alarm(self.timeout_sec)

            # Execute the function
            func(*args, **kwargs)

            # Successful execution
            severity = SeverityLevel.OK

        except TimeoutError as e:
            timed_out = True
            exception = type(e).__name__
            message = f"Execution exceeded {self.timeout_sec} second timeout"
            severity = SeverityLevel.TIMEOUT

        except Exception as e:
            exception = type(e).__name__
            message = str(e)

            if self.capture_stack_trace:
                stack_trace = traceback.format_exc()

            # Classify the exception
            severity = self._classify_exception(e, message, args, kwargs)

        finally:
            # Cleanup
            signal.alarm(0)
            end_time = time.perf_counter()

            if self.enable_memory_tracking:
                _, peak = tracemalloc.get_traced_memory()
                memory_kb = peak / 1024.0
                tracemalloc.stop()

        exec_time_ms = (end_time - start_time) * 1000

        # Adjust severity based on performance
        severity = self._adjust_severity_for_performance(
            severity, exec_time_ms, memory_kb
        )

        return CallResult(
            target=target_name,
            signature=sig,
            args=args,
            kwargs=kwargs,
            exception=exception,
            message=message,
            stack_trace=stack_trace,
            exec_time_ms=exec_time_ms,
            memory_kb=memory_kb,
            timed_out=timed_out,
            severity=severity,
            category=category,
            round_number=round_number,
        )

    def _generate_arguments(
        self, func: Callable, sig: Optional[inspect.Signature], fuzzer: "Fuzzing"
    ) -> Tuple[List[Any], Dict[str, Any]]:
        """
        Generate arguments for a function based on its signature.

        Parameters
        ----------
        func : Callable
            Target function.
        sig : Optional[inspect.Signature]
            Function signature.
        fuzzer : Fuzzing
            Fuzzing for value generation.

        Returns
        -------
        Tuple[List[Any], Dict[str, Any]]
            Generated positional and keyword arguments.
        """
        if sig is None:
            # No signature available, use random number of arguments
            num_args = random.randint(0, 5)
            args = [fuzzer.generate_value() for _ in range(num_args)]
            return args, {}

        args = []
        kwargs = {}

        for param_name, param in sig.parameters.items():
            # Skip *args and **kwargs
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue

            # Get type annotation
            type_hint = (
                param.annotation
                if param.annotation != inspect.Parameter.empty
                else None
            )

            # Generate value
            value = fuzzer.generate_value(type_hint)

            # Assign to args or kwargs based on parameter kind
            if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
                if param.default == inspect.Parameter.empty:
                    args.append(value)
                else:
                    # For parameters with defaults, sometimes use default
                    if random.random() < 0.7:
                        args.append(value)
                    else:
                        args.append(param.default)
            elif param.kind == param.KEYWORD_ONLY:
                kwargs[param_name] = value

        return args, kwargs

    def _setup_timeout_handler(self):
        """Setup timeout signal handler if not already set."""
        if not self._timeout_handler_set:
            signal.signal(signal.SIGALRM, self._timeout_signal_handler)
            self._timeout_handler_set = True

    def _timeout_signal_handler(self, signum, frame):
        """Signal handler for timeout."""
        raise TimeoutError(f"Execution timed out after {self.timeout_sec} seconds")

    def _classify_exception(
        self, exc: Exception, message: str, args: List[Any], kwargs: Dict[str, Any]
    ) -> SeverityLevel:
        """
        Classify an exception into appropriate severity level.

        Parameters
        ----------
        exc : Exception
            The caught exception.
        message : str
            Exception message.
        args : List[Any]
            Arguments used in the call.
        kwargs : Dict[str, Any]
            Keyword arguments used.

        Returns
        -------
        SeverityLevel
            Appropriate severity level.
        """
        exc_type = type(exc).__name__
        msg_lower = str(message).lower()

        # Common noise exceptions from fuzzing
        noise_indicators = [
            "positional argument",
            "keyword argument",
            "required argument",
            "missing",
            "unexpected",
            "takes",
            "given",
            "invalid",
        ]

        if any(indicator in msg_lower for indicator in noise_indicators):
            return SeverityLevel.NOISE

        # Security-related exceptions
        security_indicators = [
            "permission",
            "access",
            "security",
            "unauthorized",
            "forbidden",
        ]

        if any(indicator in msg_lower for indicator in security_indicators):
            return SeverityLevel.SECURITY

        # Type errors are usually noise for fuzzing
        if exc_type == "TypeError":
            return SeverityLevel.NOISE

        # Attribute errors might indicate interface issues
        if exc_type == "AttributeError":
            return SeverityLevel.WARNING

        # Value/Key errors might be expected for invalid inputs
        if exc_type in ["ValueError", "KeyError", "IndexError"]:
            return SeverityLevel.NOISE

        # Import errors are critical
        if exc_type == "ImportError":
            return SeverityLevel.CRITICAL

        # Memory errors
        if exc_type in ["MemoryError", "OSError"] and "memory" in msg_lower:
            return SeverityLevel.MEMORY

        # Default to warning for unknown exceptions
        return SeverityLevel.WARNING

    def _adjust_severity_for_performance(
        self, severity: SeverityLevel, exec_time_ms: float, memory_kb: float
    ) -> SeverityLevel:
        """
        Adjust severity based on performance metrics.

        Parameters
        ----------
        severity : SeverityLevel
            Current severity level.
        exec_time_ms : float
            Execution time in milliseconds.
        memory_kb : float
            Memory usage in kilobytes.

        Returns
        -------
        SeverityLevel
            Adjusted severity level.
        """
        thresholds = self.severity_config.thresholds

        # Check for performance issues
        if exec_time_ms > thresholds["slow_execution_ms"]:
            if severity.value > SeverityLevel.PERFORMANCE.value:
                return SeverityLevel.PERFORMANCE

        # Check for memory issues
        if memory_kb > thresholds["high_memory_kb"]:
            if severity.value > SeverityLevel.MEMORY.value:
                return SeverityLevel.MEMORY
            elif memory_kb > thresholds["excessive_memory_kb"]:
                return SeverityLevel.CRITICAL

        return severity
