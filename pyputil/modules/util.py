#!/usr/bin/env python3

# -*- coding: utf-8 -*-

from typing import Tuple, Set, Dict, List, Union, Optional, Literal, Iterable
from types import ModuleType
from pathlib import Path
from dataclasses import dataclass, field
import importlib.util
import importlib
from functools import lru_cache
import sys
import os
import pkgutil
from .stdlib import is_stdlib, LIST_OF_STDLIBS


@dataclass
class ImportType:
    direct_imports: List[str] = field(default_factory=list)
    from_imports: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    all_modules: List[str] = field(default_factory=list)


def _parse_imports(content: str) -> Tuple[Set[str], Set[str], Dict[str, str]]:
    """
    Parse Python import statements from source code.

    Parameters
    ----------
    content : str
        Python source code content as a string.

    Returns
    -------
    Tuple[Set[str], Set[str], Dict[str, str]]
        A tuple containing three elements:
        1. direct_imports : Set[str]
            Modules imported using direct `import` statements.
        2. from_imports : Set[str]
            Source modules from `from ... import ...` statements.
        3. aliases : Dict[str, str]
            Mapping of alias names to their original module names.
            Example: {'np': 'numpy', 'pd': 'pandas'}

    Examples
    --------
    >>> code = '''
    ... import os
    ... import numpy as np
    ... from pandas import DataFrame
    ... from sklearn.ensemble import (
    ...     RandomForestClassifier,
    ...     GradientBoostingClassifier
    ... )
    ... '''
    >>> direct, from_mods, aliases = _parse_imports(code)
    >>> print(direct)
    {'os', 'numpy'}
    >>> print(from_mods)
    {'pandas', 'sklearn.ensemble'}
    >>> print(aliases)
    {'np': 'numpy'}
    """
    direct_imports: Set[str] = set()
    from_imports: Set[str] = set()
    aliases: Dict[str, str] = {}
    lines = content.split("\n")
    i = 0
    in_multiline_import = False
    current_import_type: Optional[str] = None
    buffer_lines: List[str] = []
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            i += 1
            while i < len(lines) and (
                not (
                    lines[i].strip().endswith('"""') or lines[i].strip().endswith("'''")
                )
            ):
                i += 1
            if i < len(lines):
                i += 1
            continue
        if stripped.startswith("#"):
            i += 1
            continue
        if not in_multiline_import and "(" in line and line.strip().endswith("("):
            in_multiline_import = True
            buffer_lines.append(line)
            i += 1
            continue
        if in_multiline_import:
            buffer_lines.append(line)
            if ")" in line:
                multiline_content = " ".join(buffer_lines)
                _process_import_line(
                    multiline_content, direct_imports, from_imports, aliases
                )
                in_multiline_import = False
                buffer_lines = []
            i += 1
            continue
        if line.startswith("import ") or line.startswith("from "):
            _process_import_line(line, direct_imports, from_imports, aliases)
        i += 1
    if buffer_lines:
        multiline_content = " ".join(buffer_lines)
        _process_import_line(multiline_content, direct_imports, from_imports, aliases)
    return (direct_imports, from_imports, aliases)


def _process_import_line(
    line: str, direct_imports: Set[str], from_imports: Set[str], aliases: Dict[str, str]
) -> None:
    """
    Process a single import line and update the import collections.

    Parameters
    ----------
    line : str
        The import line to process.
    direct_imports : Set[str]
        Set to update with direct import module names.
    from_imports : Set[str]
        Set to update with source module names from 'from' imports.
    aliases : Dict[str, str]
        Dictionary to update with alias mappings.

    Notes
    -----
    This is an internal helper function and should not be called directly.
    """
    line = line.split("#")[0].strip()
    line = line.replace("(", " ").replace(")", " ")
    if line.startswith("import "):
        import_part = line[7:].strip()
        imports = [imp.strip() for imp in import_part.split(",") if imp.strip()]
        for imp in imports:
            if " as " in imp:
                parts = [p.strip() for p in imp.split(" as ")]
                if len(parts) == 2 and parts[0] and parts[1]:
                    module_name = parts[0]
                    alias_name = parts[1]
                    direct_imports.add(module_name)
                    aliases[alias_name] = module_name
            else:
                direct_imports.add(imp)
    elif line.startswith("from "):
        from_part = line[5:].strip()
        if " import " in from_part:
            source_part, import_part = from_part.split(" import ", 1)
            source_module = source_part.strip()
            if source_module:
                from_imports.add(source_module)
            imports = [imp.strip() for imp in import_part.split(",") if imp.strip()]
            for imp in imports:
                if " as " in imp:
                    parts = [p.strip() for p in imp.split(" as ")]
                    if len(parts) == 2 and parts[0] and parts[1]:
                        imported_name = parts[0]
                        alias_name = parts[1]
                        aliases[alias_name] = f"{source_module}.{imported_name}"


@lru_cache(maxsize=128)
def get_module_deps(filepath: Union[str, Path]) -> ImportType:
    """
    Extract all module dependencies from Python file.

    Parameters
    ----------
    filepath : Union[str, Path]
        Path to the Python file to analyze.

    Returns
    -------
    ImportType
        Container object contaiting dependency analysis with keys:
        - 'direct_imports': List of directly imported modules
        - 'from_imports': List of modules in 'from' imports
        - 'aliases': List of alias mappings as strings
        - 'all_modules': List of all unique module names

    Raises
    ------
    FileNotFoundError
        If the specified file does not exist.
    IOError
        If there's an error reading the file.
    UnicodeDecodeError
        If the file contains non-UTF8 characters.

    Examples
    --------
    >>> deps = get_module_deps("my_script.py")
    >>> print(deps.direct_imports)
    ['os', 'sys', 'numpy']
    >>> print(deps.aliases)
    ['np -> numpy', 'pd -> pandas']
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")
    if not filepath.is_file():
        raise ValueError(f"Path is not a file: {filepath}")
    try:
        content = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = filepath.read_text(encoding="latin-1")
        except:
            raise UnicodeDecodeError(
                f"Unable to decode file {filepath} with UTF-8 or latin-1 encoding."
            )
    direct_imports, from_imports, aliases = _parse_imports(content)
    formatted_aliases = [
        f"{alias} -> {module}" for alias, module in sorted(aliases.items())
    ]
    all_modules = sorted(direct_imports.union(from_imports))
    return ImportType(
        direct_imports=sorted(direct_imports),
        from_imports=sorted(from_imports),
        aliases=formatted_aliases,
        all_modules=all_modules,
    )


@lru_cache(maxsize=128)
def current_modules() -> ImportType:
    """
    Get import statements in the currently executing Python file.

    Returns
    -------
    ImportType
        Same structure as `get_module_deps` for the current file.

    Examples
    --------
    # In a file called analysis.py
    >>> modules = current_modules()
    >>> print(f"This file imports {len(modules.all_modules)} modules")
    """
    current_file = getattr(sys, "argv", [None])[0]
    if not current_file or current_file == "":
        raise RuntimeError("Unable to determine current file.")
    return get_module_deps(current_file)


@lru_cache(maxsize=128)
def get_deps_from_code(content: str) -> ImportType:
    """
    Extract all module dependencies from Python source code string.

    Parameters
    ----------
    content : str
        Python source code as a string.

    Returns
    -------
    ImportType
        Container object containing dependency analysis with keys:
        - 'direct_imports': List of directly imported modules
        - 'from_imports': List of modules in 'from' imports
        - 'aliases': List of alias mappings as strings
        - 'all_modules': List of all unique module names

    Raises
    ------
    TypeError
        If the provided content is not a string.

    Examples
    --------
    >>> code = '''
    ... import os
    ... import numpy as np
    ... from pandas import DataFrame
    ... '''
    >>> deps = get_deps_from_code(code)
    >>> print(deps.direct_imports)
    ['numpy', 'os']
    >>> print(deps.from_imports)
    ['pandas']
    >>> print(deps.aliases)
    ['np -> numpy']
    """
    if not isinstance(content, str):
        raise TypeError(f"Expected content to be str, got <{type(content).__name__}>")

    direct_imports, from_imports, aliases = _parse_imports(content)

    formatted_aliases = [
        f"{alias} -> {module}" for alias, module in sorted(aliases.items())
    ]

    all_modules = sorted(direct_imports.union(from_imports))

    return ImportType(
        direct_imports=sorted(direct_imports),
        from_imports=sorted(from_imports),
        aliases=formatted_aliases,
        all_modules=all_modules,
    )


def ispackage(module: Union[ModuleType, str]) -> bool:
    """
    Check whether a given module object represents a package.

    A module is considered a package if it defines a ``__path__`` attribute
    or if its import specification exposes non-None
    ``submodule_search_locations``.

    Parameters
    ----------
    module : types.ModuleType
        The module object to inspect.

    Returns
    -------
    bool
        True if the module is a package, False otherwise.

    Raises
    ------
    TypeError
        If ``module`` is not an instance of ``types.ModuleType``.

    Notes
    -----
    - Built-in modules typically return False.
    - Namespace packages are supported.

    Examples
    --------
    >>> import os
    >>> ispackage(os)
    False

    >>> ispackage('importlib')
    True
    """
    if not isinstance(module, (ModuleType, str)):
        raise TypeError(f"Expected a module name or object , got <{type(module).__name__}>")

    if hasattr(module, "__path__"):
        return True
    name = getattr(module, "__name__", None) if isinstance(module, ModuleType) else module
    if not name:
        return False
    spec = importlib.util.find_spec(name)
    if spec is None:
        return False
    return spec.submodule_search_locations is not None


def ismodule(module: Union[ModuleType, str]) -> bool:
    """Check if module object is module"""
    return isinstance(module, (ModuleType, str)) and (not ispackage(module))


def isnamespace(pkg_name: str) -> bool:
    """
    Check if the given package name corresponds to a namespace package.

    A namespace package in Python is a package that may span multiple directories
    and does not require an `__init__.py` file. This function detects both single-
    location and multi-location namespace packages.

    Parameters
    ----------
    pkg_name : str
        The name of the package to check.

    Returns
    -------
    bool
        True if `pkg_name` is a namespace package, False otherwise.

    Notes
    -----
    This function uses `importlib.util.find_spec` to retrieve the package's
    specification and examines `submodule_search_locations` and `origin` to
    determine if it's a namespace package.
    """
    try:
        spec = importlib.util.find_spec(pkg_name)
        if spec is None:
            # Package not found
            return False

        # If it's a module, not a package, it's not a namespace package
        if spec.submodule_search_locations is None:
            return False

        # A namespace package usually has no origin or has multiple locations
        if spec.origin is None:
            # Single-location namespace package without __init__.py
            return True
        elif isinstance(spec.submodule_search_locations, list) and len(spec.submodule_search_locations) > 1:
            # Multi-location namespace package
            return True

        # Otherwise, it's a regular package with __init__.py
        return False

    except ModuleNotFoundError:
        return False


def _check_pkg(pkg: str) -> Path:
    """
    Validate the package name and return its filesystem path.

    Parameters
    ----------
    pkg : str
        The name of the target package.

    Returns
    -------
    Path
        Path object pointing to the root directory of the package.

    Raises
    ------
    ImportError
            If the provided package name cannot be imported.

    ValueError
            If the package is a built-in module without a filesystem path.
    """
    spec = importlib.util.find_spec(pkg)
    if spec is None:
        raise ImportError(f"Cannot import package '{pkg}'")

    # Ensure package has a file path
    origin = spec.origin
    if not origin and spec.submodule_search_locations:
    	origin = spec.submodule_search_locations[0]
    else:
    	raise ValueError(
            f"'{pkg}' is likely a built-in module without a filesystem path"
        )

    path = Path(origin)
    if not ispackage(pkg):
        raise RuntimeError(f"Expected 'pkg' is package, got module")
    return path.parent if path.is_file() else path


def _get_py_files(path: Path) -> List[Path]:
    """
    Return all Python files (.py) within a given directory (non-recursive).
    """
    return list(path.glob("*.py"))


def _check_level(level: str, path: Path, pattern: str = "*"):
    """
    Validate the level argument and return the appropriate Path iterator.

    Parameters
    ----------
    level : str
            Either 'local' or 'global'.
    path : Path
            Base directory to search.
    pattern : str
            File search pattern (default "*" (All paths))

    Returns
    -------
    Iterator[Path]
            A generator yielding paths according to the search depth.

    Raises
    ------
    ValueError
            If level is not 'local' or 'global'.
    """
    level = level.lower()
    if level not in ["local", "global"]:
        raise ValueError(f"level can be 'local' or 'global', not '{level}'")

    return path.glob(pattern) if level == "local" else path.rglob(pattern)


@lru_cache(maxsize=128)
def getpackages(pkg: str, level: str = "local") -> List[str]:
    """
    getpackages(pkg, level='local')
    ----------------------------------
    Scan a given Python package and return a list of all **sub-packages**
    (those directories containing an `__init__.py` file).

    Parameters
    ----------
    pkg : str
            Name of the target package to scan.
            Example: 'json', 'requests', or 'importlib'

    level : str, optional
            Determines search depth:
            - 'local'  → Only look for sub-packages in the top-level directory.
            - 'global' → Recursively search all nested directories.
            Default is 'local'.

    Returns
    -------
    List[str]
            A list of sub-package names found inside the given package.

    Raises
    ------
    ImportError
            If the provided package name cannot be imported.

    ValueError
            If the level argument is invalid or package is built-in.

    Examples
    --------
    >>> getpackages("json")
    ['encoder', 'decoder', 'tool']

    >>> getpackages("importlib", level="global")
    ['abc', 'machinery', 'metadata', 'resources', 'util']
    """
    path = _check_pkg(pkg)
    search = _check_level(level, path)

    pkgs = []
    for p in search:
        # Check if directory and contains __init__.py
        if p.is_dir():
            ssearch = p.glob("*") if level == "local" else p.rglob("*")
            if any(f.name == "__init__.py" for f in ssearch):
                pkgs.append(p.stem)

    return sorted(set(pkgs))


@lru_cache(maxsize=128)
def getmodules(pkg: str, level: str = "local", parents: bool = False) -> List[str]:
    """
    getmodules(pkg, level='local', parents=False)
    ---------------------------------------------
    List all `.py` module files found inside a package.

    Parameters
    ----------
    pkg : str
            Name of the target package to scan.
            Example: 'json', 'importlib', 'requests'

    level : str, optional
            Determines search depth:
            - 'local'  → Only look for .py files in top-level directories.
            - 'global' → Recursively search all nested directories.
            Default is 'local'.

    parents : bool, optional
            If True → return dotted names including parent directories.
            If False → return only module filenames.
            Default is False.

    Returns
    -------
    List[str]
            List of module names (.py files) found within the package.

    Raises
    ------
    ImportError
            If the provided package name cannot be imported.

    ValueError
            If the package is built-in or has no path.

    Examples
    --------
    >>> getmodules("json")
    ['__init__', 'decoder', 'encoder', 'tool']

    >>> getmodules("importlib", level="global", parents=True)
    ['importlib.__init__', 'importlib.tool', 'importlib.machinery', ...]
    """
    path = _check_pkg(pkg)
    search = _check_level(level, path)
    modules = []

    for p in search:
        # If it's a directory → collect .py files inside it
        if p.is_dir():
            for pyf in _get_py_files(p):
                name = f"{p.stem}.{pyf.stem}" if parents else pyf.stem
                modules.append(name)
        # If it's a direct .py file
        elif p.suffix == ".py":
            name = f"{pkg}.{p.stem}" if parents else p.stem
            modules.append(name)

    return sorted(set(modules))


@lru_cache(maxsize=128)
def getnamespaces(
    pkg_name: str,
    level: Literal["local", "deep"] = "local"
) -> List[str]:
    """
    Discover sub-namespace packages within a given package with enhanced precision.

    This function inspects a package without importing its submodules,
    using `importlib` and `pkgutil` to safely and efficiently identify
    namespace packages as defined by PEP 420.

    Parameters
    ----------
    pkg_name : str
        The fully qualified name of the target package
        (e.g., ``"google"``).

    level : {"local", "deep"}, optional
        Controls the search depth:

        - ``"local"`` : Only direct child namespace packages.
        - ``"deep"``  : Recursively include all nested namespace packages.

        Default is ``"local"``.

    Returns
    -------
    List[str]
        A list of fully qualified names of detected namespace packages.
        Returns an empty list if none are found or the package is invalid.

    Raises
    ------
    ValueError
        If `level` is not one of {"local", "deep"}.
    ImportError
        If the base package cannot be imported (only for validation).

    Notes
    -----
    - Namespace packages are identified using multiple criteria:
      * `submodule_search_locations` exists (PEP 420)
      * `spec.origin is None` (native namespace packages)
      * `spec.loader` is a namespace loader or has `is_package` attribute
      * Actual filesystem path checking for robustness
    - This function avoids importing submodules for performance and safety.
    - Works with multi-path namespace packages and zipped packages.
    - Includes caching for improved performance with repeated calls.

    Examples
    --------
    >>> getnamespaces("google", level="local")
    ['google.cloud', 'google.protobuf']

    >>> getnamespaces("google", level="deep")
    ['google.cloud', 'google.cloud.storage', ...]

    >>> getnamespaces("collections")
    []
    """
    if level not in {"local", "deep"}:
        raise ValueError("level must be either 'local' or 'deep'")

    # Validate base package exists (optional, can be removed for performance)
    spec = importlib.util.find_spec(pkg_name)
    if spec is None:
        return []
    
    # Enhanced check: handle regular packages without submodule search locations
    if spec.submodule_search_locations is None:
        # Still might have namespace children even if parent is regular package
        # But we need to find the package's path differently
        if spec.origin and spec.origin.endswith('__init__.py'):
            # Regular package, look for namespace children in its directory
            base_path = os.path.dirname(spec.origin)
            search_paths = [base_path]
        else:
            return []
    else:
        search_paths = spec.submodule_search_locations

    results = []
    prefix = pkg_name + "."
    base_depth = prefix.count(".")
    seen_names: Set[str] = set()

    # Process all subpackages
    for module_info in pkgutil.walk_packages(search_paths, prefix):
        name = module_info.name
        
        if name in seen_names:
            continue
        seen_names.add(name)

        # Depth control with precise level checking
        if level == "local" and name.count(".") != base_depth:
            continue

        # Enhanced namespace detection with multiple strategies
        if _is_namespace_spec(name, module_info):
            results.append(name)
    
    # Sort results for consistency
    results.sort()
    return results


def _is_namespace_spec(name: str, module_info=None) -> bool:
    """
    Namespace package detection with multiple verification strategies.
    
    Returns True if the module is a namespace package, False otherwise.
    """
    import importlib
    import os
    
    # Strategy 1: Use cached module info if provided
    if module_info and hasattr(module_info, 'ispkg') and not module_info.ispkg:
        # Not a package at all
        return False
    
    try:
        spec = importlib.util.find_spec(name)
        
        # Core PEP 420 namespace package criteria
        if spec is None:
            return False
        
        # Strategy A: Standard PEP 420 namespace package
        if spec.submodule_search_locations is not None and spec.origin is None:
            return True
        
        # Strategy B: Legacy namespace packages (pkgutil.extend_path)
        if spec.submodule_search_locations is not None and spec.origin:
            # Check if origin indicates a namespace package without __init__.py
            # Some legacy namespace packages use this pattern
            if spec.origin.endswith(('__init__.py', '__init__.pyc')):
                # Has __init__.py, not a pure namespace package
                return False
            return True
        
        # Strategy C: Check loader for namespace capabilities
        if spec.loader:
            loader = spec.loader
            # Check for namespace loader attributes
            if hasattr(loader, 'is_namespace') and loader.is_namespace(name):
                return True
            if hasattr(loader, '_is_namespace'):
                return True
            # Check for module_repr that indicates namespace
            if hasattr(loader, 'module_repr'):
                try:
                    repr_str = loader.module_repr(spec)
                    if 'namespace' in repr_str.lower():
                        return True
                except:
                    pass
        
        # Strategy D: Filesystem-based verification
        if spec.submodule_search_locations:
            for location in spec.submodule_search_locations:
                if os.path.exists(location) and not os.path.exists(os.path.join(location, '__init__.py')):
                    # Path exists but has no __init__.py - likely namespace package
                    # Check if there are any Python modules/subpackages
                    try:
                        if any(f.endswith(('.py', '.pyc')) or 
                               os.path.isdir(os.path.join(location, f)) 
                               for f in os.listdir(location) if not f.startswith('_')):
                            return True
                    except OSError:
                        continue
        
        return False
        
    except (ImportError, AttributeError, OSError):
        return False


def getnamespaces_basic(pkg_name: str) -> List[str]:
    """
    Retrieve namespace packages inside a given package using a simple approach.

    This function scans all sub-packages (recursively) inside the given package
    and filters only those that are identified as namespace packages using
    the `isnamespace` function.

    Parameters
    ----------
    pkg_name : str
        Name of the target package.
        Example: 'google', 'azure', 'zope'

    Returns
    -------
    List[str]
        A list of namespace package names (not fully qualified).
        Returns an empty list if no namespace packages are found.

    Notes
    -----
    - This is a **basic implementation** and may not detect all namespace packages.
    - It relies on:
        1. `getpackages(..., level="global")` to collect sub-packages
        2. `isnamespace(...)` to determine if each package is a namespace
    - Returned names are **not fully qualified** (no parent prefix).

    Examples
    --------
    >>> getnamespaces_basic("google")
    ['cloud', 'protobuf']

    >>> getnamespaces_basic("collections")
    []

    >>> getnamespaces_basic("nonexistent_package")
    Traceback (most recent call last):
        ...
    ImportError

    See Also
    --------
    getnamespaces : Advanced and more accurate namespace detection
    isnamespace   : Function used to check if a package is a namespace
    """
    packages = getpackages(pkg_name, level="global")
    return [pkg for pkg in packages if isnamespace(pkg)]
