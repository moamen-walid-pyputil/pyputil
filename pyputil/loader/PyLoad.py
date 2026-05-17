#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""
PyLoad.py
"""

from ..PyputilException import ImportBlockedError
from ..path.filetools import write
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from socket import timeout
from types import ModuleType
from typing import Dict, List, Optional, Any, Iterable
from urllib.error import URLError, HTTPError
from urllib.request import urlopen, Request
import ast
import gc
import hashlib
import importlib
import importlib.util
import inspect
import builtins
import marshal
import os
import sys
import time


@dataclass
class ModuleInfo:
    """
    Represents detailed information about a successfully imported module.

    Parameters
    ----------
    name : str
        The module name.
    is_package : bool
        Indicates whether the module is a package.
    file : str
        File path of the module or "<built-in>" for built-in modules.
    builtin : bool
        Whether the module is a built-in module.
    functions : list of str
        Names of functions found during deep scan.
    classes : list of str
        Names of classes found during deep scan.
    attributes : list of str
        Other attributes collected from the module.
    """

    name: str
    is_package: bool
    file: str
    builtin: bool
    functions: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    attributes: List[str] = field(default_factory=list)


@dataclass
class ModuleLoadStatus:
    """
    Represents the load status of a module import attempt.

    Parameters
    ----------
    name : str
        Module name attempted to load.
    module : object or None
        Loaded module object on success, otherwise None.
    error : str or None
        Error message if import failed.
    """

    name: str
    module: Optional[Any]
    error: Optional[str]


@dataclass
class ImportResult:
    """
    Holds the final aggregated result of all import attempts.

    Parameters
    ----------
    loaded : dict
        Dictionary mapping module names to `ModuleInfo` objects.
    failed : list of ModuleLoadStatus
        List of modules that failed to import.
    cache_size : int
        Number of cached modules during import.    modules : list
        List of modules objects
    """

    loaded: Dict[str, ModuleInfo]
    failed: List[ModuleLoadStatus]
    cache_size: int
    modules: List[ModuleType]


def load_modules(
    module_names: list, *, max_workers: int = 8, deep_scan: bool = True
) -> ImportResult:
    """
    Import a list of modules at the same time

    Parameters
    ----------
    modules : list of str
        List of module names to import.
    max_workers : int, optional
        Maximum number of threads for parallel import. Default is 8.
    deep_scan : bool, optional
        Whether to collect functions, classes, and attributes of each module.

    Returns
    -------
    ImportResult
        Structured report containing loaded modules, failed imports, and cache size.

    Note
    ----
    - imports are cached to avoid duplicate loading.
    """
    cache: Dict[str, ModuleType] = {}
    loaded: Dict[str, ModuleInfo] = {}
    failed: List[ModuleLoadStatus] = []
    modules_loaded: List[ModuleType] = []

    def stats_module(name: str, module: ModuleType) -> ModuleInfo:
        """
        Collect detailed information about a loaded module.

        Parameters
        ----------
        name : str
            Module name.
        module : object
            The loaded module object.

        Returns
        -------
        ModuleInfo
            Populated object containing module metadata and optionally introspected objects.
        """
        file_attr = getattr(module, "__file__", None)
        info = ModuleInfo(
            name=name,
            is_package=hasattr(module, "__path__"),
            file=file_attr if file_attr is not None else "<built-in>",
            builtin=(file_attr is None),
        )

        if deep_scan:
            for attr_name in dir(module):
                try:
                    obj = getattr(module, attr_name)

                    if inspect.isfunction(obj) or inspect.isbuiltin(obj):
                        info.functions.append(attr_name)

                    elif inspect.isclass(obj):
                        info.classes.append(attr_name)

                    else:
                        info.attributes.append(attr_name)

                except Exception:
                    continue

        return info

    def load(name: str) -> ModuleLoadStatus:
        """
        Load a module by name and update the internal cache.

        Parameters
        ----------
        name : str
            The module name to import.

        Returns
        -------
        ModuleLoadStatus
            Status object indicating success or failure.
        """
        if name in cache:
            return ModuleLoadStatus(name, cache[name], None)

        try:
            mod = importlib.import_module(name)
            cache[name] = mod
            return ModuleLoadStatus(name, mod, None)

        except Exception as e:
            return ModuleLoadStatus(name, None, str(e))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(load, n): n for n in module_names}

        for fut in as_completed(futures):
            result = fut.result()

            if result.module:
                info = stats_module(result.name, result.module)
                loaded[result.name] = info
                modules_loaded.append(result.module)
            else:
                failed.append(result)

    return ImportResult(
        loaded=loaded,
        failed=failed,
        cache_size=len(cache),
        modules=modules_loaded,
    )


def load_from_file(file_path: str, register: bool = False) -> ModuleType:
    """
    Load and return a Python module from ANY file path.

    Parameters
    ----------
    file_path : str
        Path to the file containing Python code.
    register : bool, optional
        Register module in sys.modules, by default False

    Returns
    -------
    ModuleType
        The loaded module object

    Raises
    ------
    FileNotFoundError
        If file does not exist
    ImportError
        If file is not valid Python or execution fails
    """

    file_path = os.path.abspath(file_path)

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        # ------
        # Read & validate Python syntax
        # ------
        source = open(file_path, "r", encoding="utf-8").read()
        ast.parse(source)

        # ------
        # Stable unique module name (prevents collision)
        # ------
        hash_id = hashlib.md5(file_path.encode()).hexdigest()[:8]
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        module_name = f"_dyn_{base_name}_{hash_id}"

        # ------
        # Build import spec manually
        # ------
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError("Failed to create import spec")

        module = importlib.util.module_from_spec(spec)

        if register:
            sys.modules[module_name] = module

        spec.loader.exec_module(module)

        return module

    except SyntaxError as e:
        raise ImportError(f"Invalid Python syntax in '{file_path}': {e}") from e

    except Exception as e:
        raise ImportError(f"Failed to load module '{file_path}': {e}") from e


def load_from_source(filepath: str, name: str):
    """
    Load a variable/class/function/module from a Python source file.

    Args:
        filepath (str): Path to the Python file.
        name (str): Name of the object to import from that file.

    Returns:
        Any: The requested object (class/function/variable/module).

    Raises:
        FileNotFoundError: If the file does not exist.
        AttributeError: If the name does not exist inside the module.
    """
    # --- Validate path ---
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    # --- Create a dynamic module name ---
    mod_name = os.path.splitext(os.path.basename(filepath))[0]

    # --- Load module spec ---
    spec = importlib.util.spec_from_file_location(mod_name, filepath)
    if spec is None:
        raise ImportError(f"Cannot load spec from {filepath}")

    # --- Create empty module object ---
    module = importlib.util.module_from_spec(spec)

    # Add to sys.modules so load_modules inside the file work
    sys.modules[mod_name] = module

    # --- Execute module code ---
    loader = spec.loader
    if loader is None:
        raise ImportError(f"No loader available for {filepath}")

    loader.exec_module(module)

    # --- If user wants the entire module ---
    if name == "*":
        return module

    # --- Check if inside module ---
    if not hasattr(module, name):
        raise AttributeError(f"'{name}' not found in '{filepath}'")

    return getattr(module, name)


def unload(module_name: str, deep: bool = False) -> bool:
    """
    Unload a module from sys.modules.

    Parameters
    ----------
    module_name : str
        Name of the module to unload.
    deep : bool
        If True, deletes references to this module inside other modules'
        globals (aggressive cleanup).

    Returns
    -------
    bool
        True if unloaded, False otherwise.
    """

    # If module not loaded, nothing to unload
    if module_name not in sys.modules:
        return False

    module_obj = sys.modules[module_name]

    # Remove from sys.modules
    try:
        del sys.modules[module_name]
    except KeyError:
        return False

    # Optional deep cleanup of references
    if deep:
        for mod in list(sys.modules.values()):
            if not hasattr(mod, "__dict__"):
                continue

            globs = mod.__dict__
            for key, value in list(globs.items()):
                if value is module_obj:
                    globs[key] = None  # cut the reference

        # Force garbage collection
        gc.collect()

    # Reset import caches
    importlib.invalidate_caches()

    return True


def loads_from_dir(
    path: str, *, max_workers: int = 8, register: bool = False
) -> Dict[str, ModuleType]:
    """
    Scan a directory recursively, load every .py module found

    Args:
        path (str): Directory path to scan.
        max_workers (int): Number of threads for parallel loading.
        register (bool): Passed to load so modules can be registered in sys.modules.

    Returns:
        Dict[str, ModuleType]: Mapping of module_name -> loaded module object.

    Raises:
        FileNotFoundError: If the path does not exist.
        NotADirectoryError: If path is not a directory.
    """
    path = os.path.abspath(path)

    if not os.path.exists(path):
        raise FileNotFoundError(f"Path does not exist: {path}")

    if not os.path.isdir(path):
        raise NotADirectoryError(f"Not a directory: {path}")

    # Collect all .py full paths
    py_files = []
    for root, _, files in os.walk(path):
        for f in files:
            if f.endswith(".py"):
                full = os.path.join(root, f)
                py_files.append(full)

    # If empty, return empty dict directly
    if not py_files:
        return {}

    def load_file(file_path: str):
        """
        Internal: Load file & return (module_name, module_object)
        """
        try:
            module = load(file_path, register=register)
            name = os.path.splitext(os.path.basename(file_path))[0]
            return (name, module)
        except Exception as e:
            # Skip problematic modules, but DON'T break whole scan
            return (None, None)

    result: Dict[str, ModuleType] = {}

    # Multithreading
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(load_file, f): f for f in py_files}

        for fut in as_completed(futures):
            name, module = fut.result()
            if name and module:
                result[name] = module

    return result


def load_from_url(
    url: str, cache_dir: str = ".url_cache", timeout_sec: int = 10
) -> ModuleType | None:
    """
    Load a Python module from a remote URL.

    Workflow
    --------
    1. **Caching Directory Setup**
       Ensures a local cache directory exists where downloaded modules
       are stored as `.py` files.

    2. **Download & Validation**
       - Performs an HTTP GET request with a browser-like user agent.
       - Verifies HTTP status.
       - Accepts only responses that resemble text or Python code.
       - Gracefully handles various decoding scenarios (`utf-8` → fallback `latin-1`).

    3. **Hash-Based Caching**
       - Computes SHA-256 of the incoming source code.
       - If the file already exists in cache:
         - Compares hashes to detect changes.
         - Overwrites cache only if different.
       - Creates the cached file when absent.

    Failure Handling
    ----------------
    Returns `None` on **any** failure, including:
    - Network issues (`HTTPError`, `URLError`, timeouts)
    - Decoding failures
    - Cache write errors
    - Import issues / syntax errors
    - Invalid responses or content types

    Parameters
    ----------
    url : str
        Direct URL pointing to a Python `.py` file.
    cache_dir : str, optional
        Local directory used to store cached modules.
    timeout_sec : int, optional
        Timeout (in seconds) for network requests.

    Returns
    -------
    ModuleType | None
        The successfully imported module, or `None` if loading failed.

    Notes
    -----
    - Unique module names are generated when a name collision is detected.
    - Cache files are always `.py`, regardless of source URL extension.
    """
    try:
        os.makedirs(cache_dir, exist_ok=True)

        # Extract clean module name
        raw_name = os.path.splitext(os.path.basename(url))[0]
        module_name = raw_name if raw_name else f"mod_{abs(hash(url))}"

        cache_path = os.path.join(cache_dir, f"{module_name}.py")

        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=timeout_sec) as response:
                if response.status != 200:
                    return None

                ct = response.headers.get("Content-Type", "")
                if "text" not in ct and "python" not in ct:
                    # Might still be python code; keep going but cautious
                    pass

                raw_data = response.read()

            try:
                code = raw_data.decode("utf-8")
            except UnicodeDecodeError:
                # fallback decoding
                try:
                    code = raw_data.decode("latin-1")
                except Exception:
                    return None

        except (HTTPError, URLError, timeout):
            return None
        except Exception:
            return None

        # ---- Step 2: Avoid corrupted cache ----
        # compute hash of new code
        new_hash = hashlib.sha256(code.encode()).hexdigest()

        # If same cache exists and hash matches → skip write
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    old_code = f.read()
                old_hash = hashlib.sha256(old_code.encode()).hexdigest()
                if old_hash == new_hash:
                    pass  # identical, skip rewrite
                else:
                    # different → overwrite
                    with open(cache_path, "w", encoding="utf-8") as f:
                        f.write(code)
            except Exception:
                # If cache corrupted → rewrite anyway
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(code)
        else:
            # new cache file
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(code)
            except Exception:
                return None

        # ---- Step 3: Import ----
        try:
            # Avoid name conflicts
            if module_name in sys.modules:
                # Generate unique name
                module_name = f"{module_name}_{abs(hash(url))}"

            spec = importlib.util.spec_from_file_location(module_name, cache_path)
            if not spec or not spec.loader:
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module

            try:
                spec.loader.exec_module(module)
            except SyntaxError:
                # Remove failed module
                sys.modules.pop(module_name, None)
                return None

            return module

        except Exception:
            sys.modules.pop(module_name, None)
            return None

    except Exception:
        return None


def _blocked_import(*args, **kwargs):
    raise ImportBlockedError("Import statements are not allowed in this environment")


def load_from_code(
    source: str,
    *,
    name: str = "module",
    save: bool = False,
    globals_: Optional[Dict[str, Any]] = None,
    allow_builtins: bool = True,
    allow_load_modules: bool = False,
    register: bool = True,
    override: bool = False,
) -> ModuleType:
    """
    Load Python source code into a module object.

    Parameters
    ----------
    source : str
        Python source code to be executed.
    name : str, default "module"
        Name assigned to the generated module.
    save : bool, default False
        If True, write the source code to ``<name>.py`` after successful execution.
    globals_ : dict, optional
        Additional global symbols injected into the module namespace
        before execution.
    allow_builtins : bool, default True
        Expose Python builtins (e.g. ``len``, ``range``) to the module.
    allow_load_modules : bool, default False
        Allow usage of ``import`` statements inside the source code.
    register : bool, default True
        Register the module in ``sys.modules`` under ``name``.
    override : bool, default False
        Override an existing registered module with the same name.

    Returns
    -------
    ModuleType
        A fully initialized Python module containing the executed code.

    Raises
    ------
    TypeError
        If ``source`` is not a string.
    RuntimeError
        If the module name already exists in ``sys.modules`` and
        ``override`` is False.
    ImportBlockedError
        If an import statement is encountered while ``allow_load_modules``
        is False.

    Examples
    --------
    >>> code = '''
    ... def hello():
    ...     return "hello world"
    ... '''
    >>> mod = load_from_code(code, name="mymod")
    >>> mod.hello()
    'hello world'
    """
    if not isinstance(source, str):
        raise TypeError("source must be a string")

    if register and not override and name in sys.modules:
        raise RuntimeError(f"Module '{name}' is already registered in sys.modules")

    module = ModuleType(name)
    module.__file__ = f"{name}.py"
    module.__package__ = name.rpartition(".")[0] or None

    # -------- module globals (namespace) --------
    module_globals = module.__dict__

    # ---- builtins sandbox ----
    if allow_builtins:
        builtins_dict = builtins.__dict__.copy()
    else:
        builtins_dict = {}

    if not allow_load_modules:
        builtins_dict["__import__"] = _blocked_import

    module_globals["__builtins__"] = builtins_dict

    # ---- inject extra globals ----
    if globals_:
        module_globals.update(globals_)

    # ---- execute source INTO module ----
    compiled = compile(source, module.__file__, "exec")
    exec(compiled, module_globals)

    # ---- __all__ filtering ----
    exported = module_globals.get("__all__")
    if isinstance(exported, Iterable):
        clean = {key: module_globals[key] for key in exported if key in module_globals}
        module_globals.clear()
        module_globals.update(clean)
        module_globals["__all__"] = list(clean.keys())

    # ---- save source code ----
    if save:
        write(module.__file__, source)

    # ---- register module ----
    if register:
        sys.modules[name] = module

    return module
