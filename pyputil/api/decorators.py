#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import time
import inspect
import functools
from typing import get_type_hints
import logging

logger = logging.getLogger(__name__)


def profile_api(func):
    """
    Decorator to profile API function performance.

    Tracks execution time and memory usage of API functions.

    Parameters
    ----------
    func : Callable
        Function to profile

    Returns
    -------
    Callable
        Wrapped function with profiling

    Examples
    --------
    >>> @profile_api
    ... def expensive_function():
    ...     # do work
    ...     pass
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        start_memory = None

        # Memory profiling if available
        try:
            import psutil

            process = psutil.Process()
            start_memory = process.memory_info().rss
        except ImportError:
            pass

        try:
            result = func(*args, **kwargs)
            return result
        finally:
            end_time = time.time()
            duration = end_time - start_time

            # Log performance
            logger.debug(f"API {func.__name__} took {duration:.3f}s")

            if start_memory:
                try:
                    import psutil

                    process = psutil.Process()
                    end_memory = process.memory_info().rss
                    memory_used = end_memory - start_memory
                    logger.debug(f"API {func.__name__} used {memory_used:,} bytes")
                except:
                    pass

    return wrapper


def validate_types(func):
    """
    Decorator to validate type hints at runtime.

    Validates function arguments and return values against type hints.

    Parameters
    ----------
    func : Callable
        Function to validate

    Returns
    -------
    Callable
        Wrapped function with type validation

    Raises
    ------
    TypeError
        If argument or return type doesn't match type hints

    Examples
    --------
    >>> @validate_types
    ... def add(a: int, b: int) -> int:
    ...     return a + b
    >>> add(1, 2)  # OK
    3
    >>> add("1", 2)  # Raises TypeError
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get type hints
        type_hints = get_type_hints(func)

        # Validate arguments
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()

        for param_name, param_value in bound.arguments.items():
            if param_name in type_hints:
                expected_type = type_hints[param_name]
                if not isinstance(param_value, expected_type):
                    raise TypeError(
                        f"Parameter '{param_name}' must be of type {expected_type}, "
                        f"got {type(param_value)}"
                    )

        # Call function
        result = func(*args, **kwargs)

        # Validate return type
        if "return" in type_hints:
            expected_return_type = type_hints["return"]
            if not isinstance(result, expected_return_type):
                raise TypeError(
                    f"Return value must be of type {expected_return_type}, "
                    f"got {type(result)}"
                )

        return result

    return wrapper


def deprecated(message: str = None):
    """
    Decorator to mark API functions as deprecated.

    Parameters
    ----------
    message : str, optional
        Custom deprecation message

    Returns
    -------
    Callable
        Decorator function

    Examples
    --------
    >>> @deprecated("Use new_function instead")
    ... def old_function():
    ...     pass
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import warnings

            msg = message or f"{func.__name__} is deprecated"
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def experimental(func):
    """
    Decorator to mark API functions as experimental.

    Parameters
    ----------
    func : Callable
        Function to mark as experimental

    Returns
    -------
    Callable
        Wrapped function with warning

    Examples
    --------
    >>> @experimental
    ... def new_feature():
    ...     pass
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        import warnings

        warnings.warn(
            f"{func.__name__} is experimental and may change",
            FutureWarning,
            stacklevel=2,
        )
        return func(*args, **kwargs)

    return wrapper
