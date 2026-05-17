#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import importlib.util
from types import ModuleType
from typing import Optional, List, Union, Any
import sys
from functools import lru_cache
from importlib.machinery import PathFinder


@lru_cache(maxsize=128)
def find_loader(
    module_name: str,
    *,
    raise_on_error: bool = False
) -> Optional[object]:
    """
    Find the loader for a given Python module.

    This function attempts to locate the import loader associated with a module
    name using ``importlib.util.find_spec``. It safely handles invalid inputs,
    relative module paths, and missing modules.

    Parameters
    ----------
    module_name : str
        The name of the module to search for. Can be absolute or relative.

    raise_on_error : bool, optional
        If True, raise exceptions instead of silently returning None.
        Default is False.

    Returns
    -------
    loader : object or None
        The loader object responsible for importing the module, or None if not found.

    spec : importlib.machinery.ModuleSpec, optional
        Returned only if ``return_spec=True``. Contains full import specification.

    Raises
    ------
    TypeError
        If ``module_name`` is not a string.

    ValueError
        If ``module_name`` is empty.

    ImportError
        If the module cannot be found and ``raise_on_error=True``.

    Examples
    --------
    >>> find_loader("math")
    <_frozen_importlib_external.ExtensionFileLoader object at ...>

    >>> find_loader("nonexistent_module")
    None

    Notes
    -----
    - Relative imports (starting with '.') are normalized automatically.
    - This function does not import the module, it only inspects metadata.
    - Uses Python's import system internals via ``importlib``.

    See Also
    --------
    importlib.util.find_spec : Core function used to retrieve module specs.
    """
    
    # --- Input validation ---
    if not isinstance(module_name, str):
        raise TypeError(f"Expected module name as str, got {type(module_name).__name__}")

    module_name = module_name.strip()
    if not module_name:
        raise ValueError("Module name cannot be empty")

    # Normalize relative imports (remove leading dots)
    if module_name.startswith("."):
        module_name = module_name.lstrip(".")
    if module_name.endswith("."):
        module_name = module_name.rstrip(".")

    try:
        spec = importlib.util.find_spec(module_name)

        if spec is None:
            if raise_on_error:
                raise ImportError(f"Module '{module_name}' not found")
            return None

        return spec.loader

    except (ImportError, AttributeError) as e:
        if raise_on_error:
            raise
        return None


@lru_cache(maxsize=128)
def get_loader(
    module_or_name: Union[str, ModuleType],
    *,
    use_cache: bool = True,
    raise_on_error: bool = False
) -> Optional[Any]:
    """
    Retrieve the loader for a given module or module name.

    This function safely resolves a module's loader using Python's import
    system. It supports both module objects and module names, and avoids
    unnecessary imports when possible.

    Parameters
    ----------
    module_or_name : str or ModuleType
        The module object or the fully qualified module name.

    use_cache : bool, optional
        If True, attempt to resolve the module from ``sys.modules`` first
        for faster lookup. Default is True.

    raise_on_error : bool, optional
        If True, raise exceptions instead of returning None on failure.
        Default is False.

    Returns
    -------
    loader : object or None
        The loader responsible for importing the module.

    spec : ModuleSpec, optional
        Returned only if ``return_spec=True``.

    Raises
    ------
    TypeError
        If the input is not a string or ModuleType.

    ValueError
        If the module name is empty.

    ImportError
        If the module cannot be resolved and ``raise_on_error=True``.

    Examples
    --------
    >>> get_loader("math")
    <_frozen_importlib_external.ExtensionFileLoader object at ...>

    >>> import os
    >>> get_loader(os)
    <class '_frozen_importlib.BuiltinImporter'>

    >>> get_loader("nonexistent_module")
    None

    >>> get_loader("os.path", return_spec=True)
    ModuleSpec(name='posixpath', loader=..., origin='...')

    Notes
    -----
    - This function does NOT import the module unless required by Python's
      import system to resolve its specification.
    - Uses ``importlib.util.find_spec`` internally.
    - Optimized to avoid redundant lookups.
    """

    # --- Fast path: module object ---
    if isinstance(module_or_name, ModuleType):
        module = module_or_name

        loader = getattr(module, "__loader__", None)
        if loader is not None:
            return loader

        spec = getattr(module, "__spec__", None)
        if spec is None:
            if raise_on_error:
                raise ImportError(f"Module '{module.__name__}' has no spec")
            return None

        return spec.loader

    # --- Validate input ---
    if not isinstance(module_or_name, str):
        raise TypeError(
            f"Expected str or ModuleType, got {type(module_or_name).__name__}"
        )

    name = module_or_name.strip()
    if not name:
        raise ValueError("Module name cannot be empty")

    # Normalize relative imports
    if name.startswith("."):
        name = name.lstrip(".")
    if name.endswith("."):
        name = name.rstrip(".")

    # --- Fast path: cache lookup ---
    if use_cache:
        module = sys.modules.get(name)
        if module is not None:
            loader = getattr(module, "__loader__", None)
            if loader is not None:
                return loader

            spec = getattr(module, "__spec__", None)
            if spec is not None:
                return spec.loader

    # --- Fallback: find spec ---
    try:
        spec = importlib.util.find_spec(name)

        if spec is None:
            if raise_on_error:
                raise ImportError(f"Module '{name}' not found")
            return None

        return spec.loader

    except (ImportError, AttributeError, ValueError) as e:
        if raise_on_error:
            raise
        return None