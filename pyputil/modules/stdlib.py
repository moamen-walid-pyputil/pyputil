#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import sys
import sysconfig
from pathlib import Path
from typing import Iterable, Optional, Tuple, List, FrozenSet, Dict
import functools
from difflib import SequenceMatcher

_STDLIB_PATH: Optional[Path] = None
_STDLIB_MODULES: Optional[set] = None
_FROZEN_SET_OF_STDLIBS: FrozenSet[str] = frozenset(
    {
        "antigravity",
        "_posixsubprocess",
        "_threading_local",
        "resource",
        "graphlib",
        "zlib",
        "_strptime",
        "cmd",
        "_sha2",
        "unittest",
        "colorsys",
        "_interpchannels",
        "_pyio",
        "pyclbr",
        "xml",
        "zipapp",
        "genericpath",
        "_ast",
        "_bz2",
        "modulefinder",
        "_heapq",
        "configparser",
        "sched",
        "pstats",
        "_frozen_importlib",
        "_imp",
        "os",
        "turtle",
        "sre_parse",
        "heapq",
        "this",
        "encodings",
        "ipaddress",
        "sre_compile",
        "_opcode_metadata",
        "symtable",
        "_py_abc",
        "logging",
        "site",
        "_ios_support",
        "atexit",
        "sre_constants",
        "webbrowser",
        "winsound",
        "bz2",
        "_collections",
        "profile",
        "pyexpat",
        "stat",
        "_sqlite3",
        "fcntl",
        "textwrap",
        "_ssl",
        "zoneinfo",
        "_interpqueues",
        "_pickle",
        "importlib",
        "runpy",
        "_codecs_jp",
        "_wmi",
        "bisect",
        "codeop",
        "plistlib",
        "secrets",
        "smtplib",
        "datetime",
        "_posixshmem",
        "locale",
        "_string",
        "weakref",
        "enum",
        "builtins",
        "hashlib",
        "mailbox",
        "time",
        "_aix_support",
        "_weakref",
        "_typing",
        "posixpath",
        "tty",
        "contextvars",
        "netrc",
        "platform",
        "_datetime",
        "lzma",
        "_apple_support",
        "_tracemalloc",
        "_struct",
        "pickle",
        "_lzma",
        "html",
        "posix",
        "ssl",
        "_md5",
        "string",
        "_sha1",
        "asyncio",
        "wave",
        "mimetypes",
        "_io",
        "getpass",
        "fnmatch",
        "_weakrefset",
        "reprlib",
        "_sitebuiltins",
        "bdb",
        "_sre",
        "_codecs_cn",
        "_locale",
        "sqlite3",
        "tabnanny",
        "_multibytecodec",
        "rlcompleter",
        "pprint",
        "_suggestions",
        "ntpath",
        "abc",
        "http",
        "io",
        "tempfile",
        "traceback",
        "_statistics",
        "pkgutil",
        "opcode",
        "mmap",
        "poplib",
        "_multiprocessing",
        "signal",
        "_json",
        "_compat_pickle",
        "subprocess",
        "email",
        "_curses",
        "fileinput",
        "shelve",
        "dataclasses",
        "tokenize",
        "_asyncio",
        "imaplib",
        "linecache",
        "select",
        "glob",
        "_curses_panel",
        "calendar",
        "syslog",
        "_csv",
        "collections",
        "_pydatetime",
        "_sha3",
        "xmlrpc",
        "faulthandler",
        "_zoneinfo",
        "_warnings",
        "_codecs",
        "filecmp",
        "termios",
        "_sysconfig",
        "selectors",
        "doctest",
        "multiprocessing",
        "msvcrt",
        "_pyrepl",
        "_frozen_importlib_external",
        "_thread",
        "copy",
        "fractions",
        "_hashlib",
        "tomllib",
        "binascii",
        "pydoc",
        "optparse",
        "_markupbase",
        "dis",
        "errno",
        "gc",
        "_interpreters",
        "base64",
        "code",
        "copyreg",
        "_codecs_hk",
        "py_compile",
        "struct",
        "_dbm",
        "_pydecimal",
        "marshal",
        "cmath",
        "functools",
        "unicodedata",
        "_signal",
        "_tokenize",
        "array",
        "pickletools",
        "tkinter",
        "tracemalloc",
        "_functools",
        "winreg",
        "threading",
        "grp",
        "json",
        "decimal",
        "shlex",
        "ftplib",
        "sys",
        "_bisect",
        "token",
        "hmac",
        "_queue",
        "socket",
        "tarfile",
        "wsgiref",
        "shutil",
        "zipfile",
        "pwd",
        "venv",
        "_lsprof",
        "_socket",
        "compileall",
        "trace",
        "zipimport",
        "__future__",
        "_gdbm",
        "csv",
        "_abc",
        "ctypes",
        "random",
        "pathlib",
        "pty",
        "queue",
        "difflib",
        "_codecs_iso2022",
        "itertools",
        "nturl2path",
        "sysconfig",
        "_opcode",
        "numbers",
        "_colorize",
        "getopt",
        "_contextvars",
        "_symtable",
        "_codecs_tw",
        "_decimal",
        "dbm",
        "cProfile",
        "gettext",
        "_uuid",
        "math",
        "stringprep",
        "quopri",
        "urllib",
        "statistics",
        "timeit",
        "codecs",
        "_elementtree",
        "_operator",
        "curses",
        "ensurepip",
        "pdb",
        "idlelib",
        "typing",
        "ast",
        "_pylong",
        "keyword",
        "turtledemo",
        "warnings",
        "_codecs_kr",
        "pydoc_data",
        "_android_support",
        "concurrent",
        "_tkinter",
        "_collections_abc",
        "_blake2",
        "_overlapped",
        "gzip",
        "argparse",
        "_ctypes",
        "_stat",
        "_random",
        "uuid",
        "operator",
        "socketserver",
        "_compression",
        "contextlib",
        "readline",
        "types",
        "_osx_support",
        "inspect",
        "_winapi",
        "_scproxy",
        "nt",
        "re",
    }
)
_SET_OF_STDLIBS = set(_FROZEN_SET_OF_STDLIBS)
LIST_OF_STDLIBS = sorted(_SET_OF_STDLIBS)


def _is_stdlib(name: str, stdlibs: Iterable) -> bool:
    """
    Check if a module name exists in a given list of modules.

    Parameters
    ----------
    name : str
        The module name to check.
    stdlibs : Iterable
        An iterable containing module names to check against.

    Returns
    -------
    bool
        True if the module name is in the list (case-insensitive),
        False otherwise.

    Examples
    --------
    >>> _is_stdlib("os", ["os", "sys"])
    True
    >>> _is_stdlib("JSON", ["json", "os"])
    True
    """
    return any((name.lower() == stdlib.lower() for stdlib in stdlibs))


def isbuiltin(name: str) -> bool:
    """
    Check if a module is built into the Python interpreter.

    Parameters
    ----------
    name : str
        The module name to check.

    Returns
    -------
    bool
        True if the module is built into Python, False otherwise.

    Notes
    -----
    Built-in modules are written in C and compiled directly into
    the Python interpreter. They can be identified using
    `sys.builtin_module_names`.

    Examples
    --------
    >>> isbuiltin("sys")
    True
    >>> isbuiltin("os")
    False
    >>> isbuiltin("json")
    False
    """
    return _is_stdlib(name, sys.builtin_module_names)


@functools.lru_cache(maxsize=1024)
def is_stdlib(name: str) -> bool:
    """
    Check if a module is part of Python's standard library.

    This function uses the efficient method available
    based on the Python version. For Python 3.10+, it uses
    `sys.stdlib_module_names`. For older versions, it uses a manual
    detection method.

    Parameters
    ----------
    name : str
        The module name to check.

    Returns
    -------
    bool
        True if the module is part of Python's standard library,
        False otherwise.

    Raises
    ------
    ValueError
        If the module name is empty or None.

    Examples
    --------
    >>> is_stdlib("os")
    True
    >>> is_stdlib("json")
    True
    >>> is_stdlib("numpy")
    False
    >>> is_stdlib("django")
    False

    See Also
    --------
    isbuiltin : Check if a module is built into the interpreter.
    """
    if not name:
        raise ValueError("Module name cannot be empty or None")
    if hasattr(sys, "stdlib_module_names"):
        return _is_stdlib_python310(name)
    return _is_stdlib_legacy(name)


def _is_stdlib_python310(name: str) -> bool:
    """
    Check if a module is in the standard library (Python 3.10+).

    Parameters
    ----------
    name : str
        The module name to check.

    Returns
    -------
    bool
        True if the module is in sys.stdlib_module_names, False otherwise.
    """
    if isbuiltin(name):
        return True
    return _is_stdlib(name, sys.stdlib_module_names)


def _is_stdlib_legacy(name: str) -> bool:
    """
    Check if a module is in the standard library (pre-Python 3.10).

    This method uses a combination of path detection and module metadata
    to determine if a module is part of the standard library.

    Parameters
    ----------
    name : str
        The module name to check.

    Returns
    -------
    bool
        True if the module is part of the standard library, False otherwise.
    """
    if isbuiltin(name):
        return True
    module_path = _find_module_path(name)
    if not module_path:
        return False
    stdlib_path = _get_stdlib_path()
    if not stdlib_path:
        return _is_stdlib_fallback(name)
    return _is_path_in_stdlib(module_path, stdlib_path)


def _get_stdlib_path() -> Optional[Path]:
    """
    Get the path to Python's standard library directory.

    Returns
    -------
    Path or None
        Path object pointing to the standard library directory,
        or None if it cannot be determined.

    Notes
    -----
    This function uses multiple methods to find the standard library path:
    1. sysconfig.get_path("stdlib") - most reliable for Python 2.7+/3.x
    2. site module - for virtual environments and user installs
    3. sys.executable - fallback method based on interpreter location

    The result is cached to improve performance.
    """
    global _STDLIB_PATH
    if _STDLIB_PATH is not None:
        return _STDLIB_PATH
    try:
        stdlib = sysconfig.get_path("stdlib")
        if stdlib:
            _STDLIB_PATH = Path(stdlib).resolve()
            return _STDLIB_PATH
    except (AttributeError, KeyError):
        pass
    try:
        import site

        if hasattr(site, "getsitepackages"):
            for path in site.getsitepackages():
                path_str = str(path)
                if "site-packages" not in path_str and "dist-packages" not in path_str:
                    potential_path = Path(path)
                    if potential_path.exists() and potential_path.is_dir():
                        _STDLIB_PATH = potential_path.resolve()
                        return _STDLIB_PATH
    except ImportError:
        pass
    if hasattr(sys, "executable") and sys.executable:
        exe_path = Path(sys.executable).resolve()
        for parent in exe_path.parents:
            for lib_name in ["lib", "Lib"]:
                lib_path = parent / lib_name
                if lib_path.exists() and lib_path.is_dir():
                    version_dir = (
                        f"python{sys.version_info.major}.{sys.version_info.minor}"
                    )
                    version_path = lib_path / version_dir
                    if version_path.exists():
                        _STDLIB_PATH = version_path.resolve()
                        return _STDLIB_PATH
                    if any(((lib_path / f).exists() for f in ["os.py", "sys.py"])):
                        _STDLIB_PATH = lib_path.resolve()
                        return _STDLIB_PATH
    return None


def _find_module_path(module_name: str) -> Optional[Path]:
    """
    Find the file system path of a Python module.

    Parameters
    ----------
    module_name : str
        Name of the module to locate.

    Returns
    -------
    Path or None
        Path object pointing to the module file, or None if not found.

    Notes
    -----
    This function attempts to import the module and extract its
    __file__ attribute. It handles various edge cases including
    namespace packages, built-in modules, and import errors.
    """
    try:
        import importlib.util

        spec = importlib.util.find_spec(module_name)
        if spec and spec.origin and (spec.origin != "built-in"):
            return Path(spec.origin).resolve()
    except (ImportError, AttributeError):
        pass
    try:
        module = __import__(module_name)
        if "." in module_name:
            for part in module_name.split(".")[1:]:
                module = getattr(module, part, None)
                if module is None:
                    break
        if module and hasattr(module, "__file__") and module.__file__:
            return Path(module.__file__).resolve()
    except (ImportError, AttributeError, ValueError):
        pass
    if module_name in sys.modules:
        module = sys.modules[module_name]
        if hasattr(module, "__file__") and module.__file__:
            return Path(module.__file__).resolve()
    return None


def _is_path_in_stdlib(module_path: Path, stdlib_path: Path) -> bool:
    """
    Check if a module path is within the standard library directory.

    Parameters
    ----------
    module_path : Path
        Path to the module file.
    stdlib_path : Path
        Path to the standard library directory.

    Returns
    -------
    bool
        True if module_path is within stdlib_path or its subdirectories,
        False otherwise.
    """
    try:
        return stdlib_path in module_path.parents
    except (AttributeError, ValueError):
        return False


def _is_stdlib_fallback(name: str) -> bool:
    """
    Fallback method to check if a module is standard library.

    This method uses a comprehensive list of known standard library
    modules when path detection fails.

    Parameters
    ----------
    name : str
        The module name to check.

    Returns
    -------
    bool
        True if the module is in the known standard library list,
        False otherwise.
    """
    global _STDLIB_MODULES
    if _STDLIB_MODULES is None:
        _STDLIB_MODULES = _FROZEN_SET_OF_STDLIBS
    return name.lower() in _STDLIB_MODULES


def _similarity(a: str, b: str) -> float:
    """
    Compute a similarity ratio between two strings.

    Parameters
    ----------
    a : str
        First string to compare.
    b : str
        Second string to compare.

    Returns
    -------
    float
        Similarity ratio between ``a`` and ``b`` in the range ``[0.0, 1.0]``.
    """
    return SequenceMatcher(None, a, b).ratio()


def stdlib_audit(
    threshold: float = 0.8, max_length_diff: int = 3
) -> Dict[str, List[Tuple[str, float]]]:
    """
    Detect installed packages whose names closely resemble Python
    standard library modules.

    The function performs a audit to identify
    packages that may be confusing, misleading, or intentionally
    named similar to standard library modules (e.g. typosquatting).

    Parameters
    ----------
    threshold : float, optional
        Minimum similarity score required to consider a package
        as suspicious. Must be between ``0.0`` and ``1.0``.
        Default is ``0.8``.
    max_length_diff : int, optional
        Maximum allowed difference in string length between a
        standard library module name and a package name.
        Used as a fast pre-filter. Default is ``3``.

    Returns
    -------
    Dict[str, List[Tuple[str, float]]]
        Mapping of standard library module names to a list of
        suspicious packages. Each entry contains:

        - package name : str
        - similarity score : float

        The results for each stdlib module are sorted by similarity
        score in descending order.

    Examples
    --------
    >>> audit = stdlib_audit(threshold=0.85)
    >>> audit["json"]
    [("json3", 0.91), ("jsonlib", 0.86)]
    """
    from .packages import list_packages

    stdlib = _FROZEN_SET_OF_STDLIBS
    packages = list_packages(include_stdlib=False)
    results: Dict[str, List[Tuple[str, float]]] = {}
    for s in stdlib:
        s_len = len(s)
        s_prefix = s[:3]
        for p in packages:
            if s == p:
                continue
            if abs(len(p) - s_len) > max_length_diff:
                continue
            if not (p.startswith(s_prefix) or s in p or p in s):
                continue
            score = _similarity(s, p)
            if score >= threshold:
                results.setdefault(s, []).append((p, round(score, 3)))
    for k in results:
        results[k].sort(key=lambda x: x[1], reverse=True)
    return results
