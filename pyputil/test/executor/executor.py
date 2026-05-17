#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import time
import inspect
from types import ModuleType
from typing import Optional

from .module_analyzer import _analyze_attribute
from .base import AttributeInfo, ModuleResult, AttributeType


def execute_module(
    module: ModuleType,
    *,
    include_private: bool = False,
    instantiate_classes: bool = True,
    call_functions: bool = True,
    execute_variables: bool = True,
    ignore_errors: bool = True,
    get_docstrings: bool = True,
    get_signatures: bool = True,
    max_recursion: int = 0,
    current_recursion: int = 0,
) -> ModuleResult:
    """
    Analyze and execute attributes in a module.

    Parameters
    ----------
    module : ModuleType
        The module object to analyze
    include_private : bool, optional
        Include private attributes (starting with '_'), default: False
    instantiate_classes : bool, optional
        Instantiate class objects (if they have no required arguments), default: True
    call_functions : bool, optional
        Call functions (if they have no required arguments), default: True
    execute_variables : bool, optional
        Include variable values in the result, default: True
    ignore_errors : bool, optional
        Continue execution when errors occur, default: True
    get_docstrings : bool, optional
        Extract docstrings from attributes, default: True
    get_signatures : bool, optional
        Extract function/method signatures, default: True
    max_recursion : int, optional
        Maximum recursion depth for nested analysis, default: 0 (no recursion)
    current_recursion : int, optional
        Current recursion depth (used internally), default: 0

    Returns
    -------
    ModuleResult
        A result object containing all analyzed attributes.

    Raises
    ------
    TypeError
        If the input is not a module object

    Examples
    --------
    >>> import inspect
    >>> result = execute_module(inspect)
    >>> print(result)

    Notes
    -----
    - Functions and classes that require arguments will be marked as such
    - Private attributes are skipped by default
    - Errors are caught and recorded in the result by default
    - The result includes detailed metadata about each attribute
    """

    if not isinstance(module, ModuleType):
        raise TypeError("Expected a module object")

    start_time = time.time()

    result = ModuleResult(
        module_name=module.__name__, file=getattr(module, "__file__", None)
    )

    attribute_names = dir(module)
    result.total_attributes = len(attribute_names)

    for name in attribute_names:
        is_private = name.startswith("_")
        if not include_private and is_private:
            continue

        try:
            # Get the attribute
            attr = getattr(module, name)

            # Analyze the attribute
            attr_info = _analyze_attribute(
                attr, name, is_private, get_docstrings, get_signatures
            )

            # Try to execute based on type
            try:
                if call_functions and inspect.isfunction(attr):
                    try:
                        attr_info.value = attr()
                        attr_info.is_instantiated = True
                        result.functions_called += 1
                    except TypeError:
                        attr_info.has_arguments = True
                        attr_info.value = "Skipped (requires arguments)"
                    except Exception as e:
                        if ignore_errors:
                            attr_info.error = f"Function execution error: {e}"
                            result.errors_count += 1
                        else:
                            raise

                elif instantiate_classes and inspect.isclass(attr):
                    try:
                        attr_info.value = attr()
                        attr_info.is_instantiated = True
                        result.classes_instantiated += 1
                    except TypeError:
                        attr_info.has_arguments = True
                        attr_info.value = "Skipped (constructor requires arguments)"
                    except Exception as e:
                        if ignore_errors:
                            attr_info.error = f"Class instantiation error: {e}"
                            result.errors_count += 1
                        else:
                            raise

                elif execute_variables:
                    attr_info.value = attr

                # Recursive analysis for nested objects
                if max_recursion > current_recursion:
                    if (
                        inspect.ismodule(attr) and attr is not module
                    ):  # Avoid infinite recursion
                        nested_result = execute_module(
                            attr,
                            include_private=include_private,
                            instantiate_classes=instantiate_classes,
                            call_functions=call_functions,
                            execute_variables=execute_variables,
                            ignore_errors=ignore_errors,
                            get_docstrings=get_docstrings,
                            get_signatures=get_signatures,
                            max_recursion=max_recursion,
                            current_recursion=current_recursion + 1,
                        )
                        attr_info.members = nested_result.attributes

                    elif inspect.isclass(attr):
                        # Analyze class methods and attributes
                        for member_name in dir(attr):
                            if not include_private and member_name.startswith("_"):
                                continue
                            try:
                                member = getattr(attr, member_name)
                                member_info = _analyze_attribute(
                                    member,
                                    member_name,
                                    member_name.startswith("_"),
                                    get_docstrings,
                                    get_signatures,
                                )
                                attr_info.members[member_name] = member_info
                            except Exception as e:
                                if ignore_errors:
                                    attr_info.members[member_name] = AttributeInfo(
                                        name=member_name,
                                        type=AttributeType.UNKNOWN,
                                        error=str(e),
                                    )

            except Exception as e:
                if not ignore_errors:
                    raise
                attr_info.error = f"Execution error: {e}"
                result.errors_count += 1

            # Add to result
            result.attributes[name] = attr_info

        except Exception as e:
            if not ignore_errors:
                raise

            # Create error entry
            error_info = AttributeInfo(
                name=name,
                type=AttributeType.UNKNOWN,
                is_private=is_private,
                error=f"Attribute access error: {e}",
            )
            result.attributes[name] = error_info
            result.errors_count += 1

    # Calculate summary statistics
    type_counts = {}
    for info in result.attributes.values():
        type_name = info.type.value
        type_counts[type_name] = type_counts.get(type_name, 0) + 1

    result.summary = type_counts
    result.execution_time = time.time() - start_time

    return result
