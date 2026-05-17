#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from importlib.util import find_spec
from typing import Tuple, List, Iterable, Optional
import os
from pathlib import Path


def exists(module_name: str, include_builtin: bool = False) -> bool:
	"""
	Check whether a Python module exists and is importable.

	This function attempts to locate a module using `importlib.util.find_spec`.
	It determines whether the module exists based on its specification and origin.

	Parameters
	----------
	module_name : str
		Name of the module to check (e.g., 'os', 'numpy', 'my_package.module').

	include_builtin : bool, optional
		If True, built-in modules (e.g., 'sys') will be considered as existing.
		If False (default), built-in modules are ignored.

	Returns
	-------
	bool
		True if the module exists and matches the criteria, False otherwise.

	Raises
	------
	TypeError
		If `module_name` is not a string.

	Notes
	-----
	- Built-in modules typically have no file path (`spec.origin` may be None or 'built-in').
	- This function treats modules without a filesystem path as non-existent unless
	  `include_builtin=True`.

	Examples
	--------
	>>> exists("os")
	True

	>>> exists("sys")
	False

	>>> exists("sys", include_builtin=True)
	True

	>>> exists("non_existent_module")
	False
	"""
	if not isinstance(module_name, str):
		raise TypeError(
			f"Expected module name as 'str', got '{type(module_name).__name__}'"
		)

	try:
		spec = find_spec(module_name)
	except (ValueError, TypeError):
		return False

	if spec is None:
		return False

	# Handle built-in modules
	if spec.origin in (None, "built-in"):
		return include_builtin

	# Ensure it's a real file-based module
	return Path(spec.origin).exists()


def batch_exists(
	module_names: Iterable[str],
	include_builtin: bool = False
) -> List[Tuple[str, bool]]:
	"""
	Check existence of multiple Python modules.

	This function applies `exists` to a collection of module names and
	returns a list of results.

	Parameters
	----------
	module_names : Iterable[str]
		A list or iterable of module names.

	include_builtin : bool, optional
		Whether to include built-in modules as existing (default is False).

	Returns
	-------
	List[Tuple[str, bool]]
		A list of tuples where each tuple contains:
		(module_name, existence_status)

	Raises
	------
	TypeError
		If `module_names` is not iterable or contains non-string elements.

	Examples
	--------
	>>> batch_exists(["os", "sys", "fake_module"])
	[('os', True), ('sys', False), ('fake_module', False)]

	>>> batch_exists(["os", "sys"], include_builtin=True)
	[('os', True), ('sys', True)]
	"""
	if not isinstance(module_names, Iterable):
		raise TypeError("module_names must be an iterable of strings")

	results = []
	for name in module_names:
		if not isinstance(name, str):
			raise TypeError(
				f"All module names must be strings, got '{type(name).__name__}'"
			)

		results.append((name, exists(name, include_builtin=include_builtin)))

	return results


def subexists(
	module_name: str,
	submodule: str,
	include_builtin: bool = False
) -> bool:
	"""
	Check whether a submodule or subpackage exists inside a given module.

	This function verifies if a specific submodule (or subpackage) exists
	within a parent module by attempting to resolve its import specification.

	Parameters
	----------
	module_name : str
		The parent module or package name (e.g., 'os', 'numpy').

	submodule : str
		The submodule or subpackage name (e.g., 'path', 'linalg').

	include_builtin : bool, optional
		If True, allows built-in submodules (if applicable).
		Default is False.

	Returns
	-------
	bool
		True if the submodule exists inside the given module, False otherwise.

	Raises
	------
	TypeError
		If `module_name` or `submodule` is not a string.

	Notes
	-----
	- This function constructs the full module path:
	  `module_name.submodule`
	- It uses `importlib.util.find_spec` to check existence.
	- Built-in modules may not have a file path.

	Examples
	--------
	>>> subexists("os", "path")
	True

	>>> subexists("json", "decoder")
	True

	>>> subexists("os", "fake_submodule")
	False

	>>> subexists("sys", "version")
	False
	"""
	if not isinstance(module_name, str):
		raise TypeError(
			f"Expected 'module_name' as str, got '{type(module_name).__name__}'"
		)

	if not isinstance(submodule, str):
		raise TypeError(
			f"Expected 'submodule' as str, got '{type(submodule).__name__}'"
		)

	full_name = f"{module_name}.{submodule}"
	spec = find_spec(full_name)

	if spec is None:
		return False

	# Handle built-in modules
	if spec.origin in (None, "built-in"):
		return include_builtin

	return True
	