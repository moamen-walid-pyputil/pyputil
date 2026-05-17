#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
Module cloning functionality with selective mutation capabilities.

This module provides a function to create deep copies of Python modules
while allowing targeted modifications to specific attributes.
"""

from typing import Dict, Any, Set, Optional
import types
import warnings
import sys
import copy


def clone(
    module: types.ModuleType,
    mutation_rules: Optional[Dict[str, Any]] = None,
    *,
    copy_all: bool = True,
    exclude: Optional[Set[str]] = None,
    deep_copy_attrs: Optional[Set[str]] = None,
    shallow_copy_attrs: Optional[Set[str]] = None,
    preserve_module_metadata: bool = True,
    module_doc: Optional[str] = None,
    import_original_on_error: bool = True,
    recursion_limit: int = 10,
    enable_warnings: bool = True,
) -> types.ModuleType:
    """
    Clone a Python module with selective mutation capabilities.

    Creates a deep copy of a module while allowing targeted modifications
    to specific attributes.

    Parameters
    ----------
    module : types.ModuleType
        The module object to clone
    mutation_rules : Dict[str, Any], optional
        Rules for mutating specific attributes. Keys are attribute names,
        values can be:
        - A callable that receives the original attribute and returns modified version
        - Any value to replace the attribute entirely
    copy_all : bool, default=True
        If True, copy all attributes not explicitly excluded
    exclude : Set[str], optional
        Set of attribute names to skip during cloning
    deep_copy_attrs : Set[str], optional
        Attributes that require deep copy even if in shallow_copy_attrs
    shallow_copy_attrs : Set[str], optional
        Attributes that should be shallow copied (shared reference)
    preserve_module_metadata : bool, default=True
        Preserve original module metadata (__file__, __package__, etc.)
    module_doc : str, optional
        Custom documentation string for the cloned module
    import_original_on_error : bool, default=True
        If True, import original attribute on copy error
    recursion_limit : int, default=10
        Maximum recursion depth for deep copying
    enable_warnings : bool, default=True
        Enable warnings for potential issues during cloning

    Returns
    -------
    types.ModuleType
        A new module object with cloned (and potentially mutated) attributes

    Raises
    ------
    TypeError
        If module is not a module object
    RecursionError
        If recursion_limit is exceeded during deep copy
    ValueError
        If invalid parameters are provided

    Examples
    --------
    >>> import math
    >>> rules = {'pi': 3.14, 'sqrt': lambda f: lambda x: f(x) * 2}
    >>> math_clone = clone(math, rules)
    >>> math_clone.pi
    3.14
    >>> math_clone.sqrt(4)
    4.0

    Notes
    -----
    - Special attributes (starting with '__' except standard dunders) are skipped
    - Functions and classes are deep copied by default
    - Module is registered in sys.modules for proper import handling
    - Circular references in the original module may cause issues
    """
    # Parameter validation
    if not isinstance(module, types.ModuleType):
        raise TypeError(f"Expected module, got {type(module).__name__}")

    if recursion_limit < 1:
        raise ValueError("recursion_limit must be at least 1")

    if mutation_rules is None:
        mutation_rules = {}

    if exclude is None:
        exclude = set()

    if deep_copy_attrs is None:
        deep_copy_attrs = set()

    if shallow_copy_attrs is None:
        shallow_copy_attrs = set()

    # Check for conflicts between deep_copy_attrs and shallow_copy_attrs
    conflicting = deep_copy_attrs.intersection(shallow_copy_attrs)
    if conflicting and enable_warnings:
        warnings.warn(
            f"Attributes {conflicting} specified in both deep_copy_attrs "
            f"and shallow_copy_attrs. Deep copy will take precedence."
        )

    # Track cloning depth for recursion protection
    sys.setrecursionlimit(max(sys.getrecursionlimit(), recursion_limit * 2))

    def safe_deepcopy(obj, _depth=0, _memo=None):
        """Safe deep copy with recursion limit and error handling."""
        if _depth > recursion_limit:
            raise RecursionError(
                f"Recursion limit ({recursion_limit}) exceeded during deep copy"
            )

        if _memo is None:
            _memo = {}

        obj_id = id(obj)
        if obj_id in _memo:
            return _memo[obj_id]

        # Handle special cases
        if isinstance(obj, (type, types.FunctionType, types.BuiltinFunctionType)):
            # For classes and functions, attempt deep copy
            try:
                result = copy.deepcopy(obj, _memo)
                _memo[obj_id] = result
                return result
            except Exception:
                # If deep copy fails, return the original
                if enable_warnings:
                    warnings.warn(
                        f"Failed to deep copy {type(obj).__name__} '{getattr(obj, '__name__', repr(obj))}'. "
                        f"Using original reference.",
                        RuntimeWarning,
                    )
                return obj

        # Default deep copy for other objects
        try:
            result = copy.deepcopy(obj, _memo)
            _memo[obj_id] = result
            return result
        except Exception as e:
            if import_original_on_error:
                if enable_warnings:
                    warnings.warn(
                        f"Deep copy failed for {type(obj).__name__}: {e}. "
                        f"Using original reference.",
                        RuntimeWarning,
                    )
                return obj
            else:
                raise

    # Create new module name
    original_name = module.__name__
    new_name = f"{original_name}_mutated"
    counter = 1

    # Ensure unique module name in sys.modules
    while new_name in sys.modules:
        new_name = f"{original_name}_mutated_{counter}"
        counter += 1

    # Create new module
    new_module = types.ModuleType(new_name)

    # Copy module-level metadata
    if preserve_module_metadata:
        for attr in ["__file__", "__package__", "__loader__", "__spec__", "__path__"]:
            if hasattr(module, attr):
                try:
                    setattr(new_module, attr, getattr(module, attr))
                except (AttributeError, TypeError):
                    pass

    # Set module documentation
    if module_doc is not None:
        new_module.__doc__ = module_doc
    elif hasattr(module, "__doc__"):
        new_module.__doc__ = module.__doc__

    # Helper to determine if attribute should be copied
    def should_copy_attr(attr_name: str, attr_value: Any) -> bool:
        """Determine if an attribute should be copied."""
        # Skip excluded attributes
        if attr_name in exclude:
            return False

        # Skip special attributes (but preserve standard dunders)
        if attr_name.startswith("__") and attr_name.endswith("__"):
            # Keep only standard Python dunder methods
            standard_dunders = {
                "__doc__",
                "__name__",
                "__package__",
                "__loader__",
                "__spec__",
                "__file__",
                "__cached__",
                "__builtins__",
                "__dict__",
                "__weakref__",
                "__module__",
            }
            if attr_name not in standard_dunders:
                return False

        # Skip module objects to avoid infinite recursion
        if isinstance(attr_value, types.ModuleType):
            if enable_warnings:
                warnings.warn(
                    f"Skipping nested module '{attr_name}' to avoid recursion",
                    RuntimeWarning,
                )
            return False

        return True

    # Get all attributes from the module
    # Use dir() but also check __dict__ for non-enumerable attributes
    all_attrs = set(dir(module))
    if hasattr(module, "__dict__"):
        all_attrs.update(module.__dict__.keys())

    # Process attributes
    for attr_name in sorted(all_attrs):
        try:
            # Skip if attribute cannot be accessed
            attr_value = getattr(module, attr_name)
        except (AttributeError, Exception):
            continue

        # Check if attribute should be copied
        if not should_copy_attr(attr_name, attr_value):
            continue

        # Apply mutation rules if specified
        if attr_name in mutation_rules:
            rule = mutation_rules[attr_name]

            if callable(rule):
                try:
                    # Apply mutation function
                    new_value = rule(attr_value)

                    # Validate the result
                    if isinstance(new_value, types.ModuleType):
                        raise ValueError(
                            f"Mutation rule for '{attr_name}' returned a module. "
                            f"Module injection is not supported."
                        )

                    setattr(new_module, attr_name, new_value)
                    continue

                except Exception as e:
                    if enable_warnings:
                        warnings.warn(
                            f"Mutation rule for '{attr_name}' failed: {e}. "
                            f"Using fallback copy.",
                            RuntimeWarning,
                        )
                    # Fall through to normal copying
            else:
                # Direct replacement with non-callable value
                setattr(new_module, attr_name, rule)
                continue

        # Skip if not copying all and not in mutation rules
        if not copy_all and attr_name not in mutation_rules:
            continue

        # Determine copy strategy
        if attr_name in deep_copy_attrs:
            # Force deep copy
            try:
                setattr(new_module, attr_name, safe_deepcopy(attr_value))
            except Exception as e:
                if enable_warnings:
                    warnings.warn(
                        f"Forced deep copy failed for '{attr_name}': {e}. "
                        f"Using shallow copy instead.",
                        RuntimeWarning,
                    )
                setattr(new_module, attr_name, attr_value)

        elif attr_name in shallow_copy_attrs:
            # Shallow copy (shared reference)
            setattr(new_module, attr_name, attr_value)

        else:
            # Default: intelligent copy based on type
            if isinstance(
                attr_value, (type, types.FunctionType, types.BuiltinFunctionType)
            ):
                # Deep copy classes and functions
                try:
                    setattr(new_module, attr_name, safe_deepcopy(attr_value))
                except Exception:
                    # Fallback to original on error
                    setattr(new_module, attr_name, attr_value)

            elif isinstance(attr_value, (int, float, str, bool, bytes, type(None))):
                # Immutable types - no copy needed
                setattr(new_module, attr_name, attr_value)

            else:
                # Other types - attempt deep copy
                try:
                    setattr(new_module, attr_name, safe_deepcopy(attr_value))
                except Exception:
                    # Fallback to shallow copy
                    setattr(new_module, attr_name, attr_value)

    # Register the module in sys.modules
    sys.modules[new_name] = new_module

    # Add reference to original module
    new_module.__original_module__ = module

    return new_module
