#!/usr/bin/env python3

# -*- coding: utf-8 -*-

# coding: utf-8
"""
Python Source Code Analysis Module.

This module provides comprehensive static and dynamic analysis of Python
source code, offering deep introspection into modules, classes, functions,
methods, tracebacks, frames, and code objects. It extracts structural
information, metadata, and behavioral characteristics from Python objects
and their associated source files.

The SourceParser class serves as the primary interface for all analysis
operations, providing both properties for quick access and methods for
detailed investigation.

Requirements
------------
- Python 3.8+
- Optional: python-minifier (for minification support)
- Optional: tracemalloc (for memory profiling)

Examples
--------
>>> from pyputil.core.parser._source_parser import SourceParser
>>> parser = SourceParser(my_module)
>>> parser.source[:50]  # First 50 chars of source
>>> parser.functions  # List all functions
>>> parser.decorators  # Extract decorator information
"""

from typing import (
    Any, Union, Callable, Optional, Dict, List, Tuple, Set,
    Generator, Type, TypeVar, overload, Literal
)
import ast
import string
import sys
import tokenize
from io import StringIO
import textwrap
import tracemalloc
import re
import hashlib
import dis
import linecache
from pathlib import Path
from datetime import datetime
from functools import lru_cache, cached_property
from types import (
    ModuleType,
    FunctionType,
    MethodType,
    TracebackType,
    FrameType,
    CodeType,
    DynamicClassAttribute as DCA,
    BuiltinFunctionType as BFT,
    BuiltinMethodType,
    GeneratorType,
    CoroutineType,
    AsyncGeneratorType,
)
from inspect import (
    ismodule,
    isclass,
    ismethod,
    isfunction,
    istraceback,
    isframe,
    iscode,
    isgenerator,
    iscoroutine,
    isasyncgen,
    isbuiltin,
    isabstract,
    getattr_static,
    getsource,
    getfile,
    getdoc,
    getmodule,
    currentframe,
    signature as inspect_signature,
    Parameter,
)
from ...path.utils import (
    load,
    functions,
    imports,
    classes,
    replace,
    dump,
)
from .._signature import Signature
from .utils import examples, to_callable, track_objects

# Optional dependency handling
try:
    import python_minifier
    _HAS_MINIFIER = True
except ImportError:
    python_minifier = None
    _HAS_MINIFIER = False

# Type aliases for clarity
_TargetObject = Union[
    ModuleType, Type[Any], FunctionType, MethodType,
    TracebackType, FrameType, CodeType
]
_ObjectDict = Dict[str, Any]
_AttributeFilter = Optional[Callable[[str, Any], bool]]


class SourceNotFoundError(Exception):
    """
    Exception raised when source code cannot be located for an object.

    This typically occurs with built-in types, C extensions, or
    dynamically generated objects that have no associated source file.

    Attributes
    ----------
    obj : Any
        The object for which source was requested.
    """

    def __init__(self, obj: Any) -> None:
        self.obj = obj
        obj_name = getattr(obj, '__name__', repr(obj))
        super().__init__(
            f"Source code not available for {obj_name} "
            f"(type: {type(obj).__name__}). "
            f"This may be a built-in, C extension, or dynamically created object."
        )


class UnsupportedObjectError(TypeError):
    """
    Exception raised when an unsupported object type is provided.

    The SourceParser accepts modules, classes, functions, methods,
    tracebacks, frames, and code objects.

    Attributes
    ----------
    obj_type : type
        The type of the object that was rejected.
    """

    def __init__(self, obj_type: type) -> None:
        self.obj_type = obj_type
        super().__init__(
            f"Expected module, class, method, function, traceback, frame, "
            f"or code object, but got {obj_type.__name__}. "
            f"Please provide a supported Python object type."
        )


class SourceParser:
    """
    Comprehensive static and dynamic analyzer for Python source code.

    This class performs deep analysis of Python objects and their associated
    source code, extracting structural information, metadata, type hints,
    decorators, documentation, and behavioral characteristics. It supports
    modules, classes, functions, methods, tracebacks, frames, and code objects.

    The analysis is performed lazily where possible, with results cached
    for efficient repeated access. The class combines AST (Abstract Syntax Tree)
    analysis for static properties with runtime introspection for dynamic
    characteristics.

    Parameters
    ----------
    obj : Any
        The Python object to analyze. Must be one of:
        - Module (e.g., ``os``, ``sys``)
        - Class (e.g., ``dict``, ``MyClass``)
        - Function (e.g., ``def my_func(): ...``)
        - Method (e.g., ``obj.method``)
        - Traceback (e.g., from ``sys.exc_info()``)
        - Frame (e.g., from ``inspect.currentframe()``)
        - Code object (e.g., ``func.__code__``)

    Raises
    ------
    UnsupportedObjectError
        If the provided object type is not supported for source analysis.
    SourceNotFoundError
        If the source code cannot be located for the given object
        (raised lazily when source-dependent properties are accessed).

    Attributes
    ----------
    obj : Any
        The original object being analyzed.
    name : str or None
        The ``__name__`` attribute of the object if available.
    source : str
        The dedented source code as a string (cached property).
    file : str
        The file path where the object is defined (cached property).
    memory_usage : dict
        Memory usage statistics (cached property).

    Notes
    -----
    - Source extraction relies on :func:`inspect.getsource`, which requires
      the source file to be accessible on the filesystem.
    - Built-in objects (e.g., ``str``, ``int``) have no Python source code
      and will raise ``SourceNotFoundError``.
    - C extension modules may have limited introspection capabilities.
    - The class uses ``tracemalloc`` for memory profiling; it is started
      during initialization and stopped after first memory measurement.

    Warnings
    --------
    - Memory profiling with ``tracemalloc`` may impact performance.
      Consider using ``memory_usage`` sparingly in production.
    - AST parsing is performed on the entire source file, which may be
      slow for very large files.

    See Also
    --------
    inspect.getsource : Standard library source extraction.
    ast : Abstract Syntax Tree module.
    dis : Python bytecode disassembler.

    Examples
    --------
    >>> def greet(name: str, greeting: str = "Hello") -> str:
    ...     '''Greet someone by name.'''
    ...     return f"{greeting}, {name}!"
    ...
    >>> parser = SourceParser(greet)
    >>> parser.name
    'greet'
    >>> parser.source
    'def greet(name: str, greeting: str = "Hello") -> str:\\n    ...'
    >>> parser.file is not None
    True
    >>> parser.decorators
    []
    >>> parser.hints
    {'greet': {'name': 'str', 'greeting': 'str', 'return': 'str'}}
    """

    # Class-level constants
    _SUPPORTED_TYPES: Tuple[type, ...] = (
        ModuleType,
        type,
        FunctionType,
        MethodType,
        TracebackType,
        FrameType,
        CodeType,
    )

    _INDENTATION_PATTERN: re.Pattern = re.compile(r'^(\s*)\S')

    def __init__(self, obj: _TargetObject) -> None:
        """
        Initialize the SourceParser with a Python object for analysis.

        Parameters
        ----------
        obj : ModuleType, type, FunctionType, MethodType, TracebackType, FrameType, or CodeType
            The Python object to analyze. Must be a module, class, function,
            method, traceback, frame, or code object.

        Raises
        ------
        UnsupportedObjectError
            If the object type is not supported.
        """
        # Validate object type
        if not isinstance(obj, self._SUPPORTED_TYPES):
            raise UnsupportedObjectError(type(obj))

        # Start memory tracking
        tracemalloc.start()

        # Initialize core attributes
        self._obj = obj
        self._name = getattr(obj, "__name__", None)
        self._cached_source: Optional[str] = None
        self._cached_file: Optional[str] = None
        self._cached_memory: Optional[Dict[str, float]] = None
        self._ast_tree: Optional[ast.AST] = None
        self._source_lines: Optional[List[str]] = None

        # Caches for derived properties
        self._cache: Dict[str, Any] = {}

    # ---- Basic Properties ----

    @property
    def obj(self) -> Any:
        """The original object being analyzed."""
        return self._obj

    @property
    def name(self) -> Optional[str]:
        """The ``__name__`` attribute of the object, or None."""
        return self._name

    @property
    def type_name(self) -> str:
        """
        Return the type name of the analyzed object.

        Returns
        -------
        str
            The name of the object's type (e.g., 'function', 'type', 'module').

        Examples
        --------
        >>> parser = SourceParser(len)
        >>> parser.type_name
        'builtin_function_or_method'
        """
        return type(self._obj).__name__

    @property
    def qualified_name(self) -> str:
        """
        Return the fully qualified name of the object.

        Returns
        -------
        str
            The ``__qualname__`` attribute if available, otherwise ``__name__``.

        Examples
        --------
        >>> class Outer:
        ...     class Inner:
        ...         pass
        ...
        >>> parser = SourceParser(Outer.Inner)
        >>> parser.qualified_name
        'Outer.Inner'
        """
        return getattr(self._obj, "__qualname__", self._name) or "unknown"

    # ---- Source Code Properties ----

    @property
    def source(self) -> str:
        """
        Extract and return the dedented source code of the object.

        This property uses :func:`inspect.getsource` to retrieve the source
        code and applies :func:`textwrap.dedent` for consistent formatting.
        The result is cached after first access.

        Returns
        -------
        str
            The dedented source code as a string.

        Raises
        ------
        SourceNotFoundError
            When the source file cannot be found (e.g., built-in objects).
        UnsupportedObjectError
            When the object type is not supported for source extraction.

        Notes
        -----
        - Source extraction reads the actual file from disk.
        - For very large source files, this may have memory implications.
        - The source is cached after first access; use ``clear_cache()``
          to force re-extraction.

        Examples
        --------
        >>> def example():
        ...     pass
        ...
        >>> parser = SourceParser(example)
        >>> 'def example():' in parser.source
        True

        >>> import math
        >>> parser = SourceParser(math)
        >>> parser.source  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        SourceNotFoundError: Source code not available for math ...
        """
        if self._cached_source is not None:
            return self._cached_source

        try:
            raw_source = getsource(self._obj)
            self._cached_source = textwrap.dedent(raw_source)
            return self._cached_source
        except OSError as exc:
            raise SourceNotFoundError(self._obj) from exc
        except TypeError as exc:
            raise UnsupportedObjectError(type(self._obj)) from exc

    @property
    def source_hash(self) -> str:
        """
        Compute the SHA-256 hash of the source code.

        Returns
        -------
        str
            Hexadecimal string of the SHA-256 hash.

        Examples
        --------
        >>> def func():
        ...     return 42
        ...
        >>> parser = SourceParser(func)
        >>> len(parser.source_hash)
        64
        """
        return hashlib.sha256(self.source.encode('utf-8')).hexdigest()

    @property
    def source_lines(self) -> List[str]:
        """
        Return the source code as a list of lines.

        Returns
        -------
        List[str]
            List of source code lines, without trailing newlines.

        Examples
        --------
        >>> def func():  # First line
        ...     x = 1    # Second line
        ...     return x # Third line
        ...
        >>> parser = SourceParser(func)
        >>> len(parser.source_lines)
        3
        """
        if self._source_lines is None:
            self._source_lines = self.source.splitlines()
        return self._source_lines

    @property
    def source_size(self) -> int:
        """
        Return the size of the source code in characters.

        Returns
        -------
        int
            Total character count of the source code.

        Examples
        --------
        >>> parser = SourceParser(len)
        >>> parser.source_size > 0
        True
        """
        return len(self.source)

    @property
    def line_count(self) -> int:
        """
        Return the number of lines in the source code.

        Returns
        -------
        int
            Total line count.

        Examples
        --------
        >>> def func():
        ...     x = 1
        ...     return x
        ...
        >>> parser = SourceParser(func)
        >>> parser.line_count
        3
        """
        return len(self.source_lines)

    def sdump(self, filesave: Union[str, Path]) -> None:
        """
        Save the current object's source code to a file.

        Parameters
        ----------
        filesave : str or Path
            Path to the output file.

        Raises
        ------
        OSError
            If the file cannot be written.

        Examples
        --------
        >>> def func(): pass
        >>> parser = SourceParser(func)
        >>> parser.sdump('/tmp/func_source.py')  # doctest: +SKIP
        """
        dump(str(filesave), self.source)

    def fdump(self, filesave: Union[str, Path]) -> None:
        """
        Save the full contents of the source file to a file.

        Parameters
        ----------
        filesave : str or Path
            Path to the output file.

        Raises
        ------
        OSError
            If the file cannot be written.
        FileNotFoundError
            If the source file cannot be located.

        Examples
        --------
        >>> parser = SourceParser(SourceParser)  # This class
        >>> parser.fdump('/tmp/source_parser.py')  # doctest: +SKIP
        """
        dump(str(filesave), self.read)

    # ---- File Information ----

    @property
    def file(self) -> str:
        """
        Return the source or compiled file where the object was defined.

        This property handles various object types by navigating through
        the object hierarchy:

        - **Modules**: Returns ``__file__`` attribute.
        - **Classes**: Returns the module file where the class is defined.
        - **Methods**: Converts to function, then to code object.
        - **Functions**: Converts to code object.
        - **Tracebacks**: Navigates to frame, then to code object.
        - **Frames**: Accesses the code object.
        - **Code objects**: Returns ``co_filename``.

        Returns
        -------
        str
            Absolute file path where the object is defined.

        Raises
        ------
        TypeError
            For built-in modules/classes without files.
        OSError
            For ``__main__`` classes without accessible source files.

        Notes
        -----
        The result is cached after first access.

        Examples
        --------
        >>> import os
        >>> parser = SourceParser(os)
        >>> parser.file.endswith('os.py')
        True

        >>> parser = SourceParser(len)
        >>> parser.file  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
            ...
        TypeError: ...
        """
        if self._cached_file is not None:
            return self._cached_file

        obj = self._obj

        # Module
        if ismodule(obj):
            if hasattr(obj, "__file__") and obj.__file__:
                self._cached_file = obj.__file__
                return self._cached_file
            raise TypeError(
                f"'{obj!r}' is a built-in module (no __file__ attribute)."
            )

        # Class
        if isclass(obj):
            module_name = getattr(obj, "__module__", None)
            if module_name:
                module = sys.modules.get(module_name)
                if module and hasattr(module, "__file__") and module.__file__:
                    self._cached_file = module.__file__
                    return self._cached_file
                if module_name == "__main__":
                    raise OSError(
                        "Source code not available for __main__ class. "
                        "The class is defined in an interactive session or "
                        "script without a saved file."
                    )
            raise TypeError(
                f"'{obj!r}' is a built-in class (no associated source file)."
            )

        # Method -> function
        if ismethod(obj):
            obj = obj.__func__

        # Function -> code object
        if isfunction(obj):
            obj = obj.__code__

        # Traceback -> frame -> code
        if istraceback(obj):
            obj = obj.tb_frame
        if isframe(obj):
            obj = obj.f_code

        # Code object -> filename
        if iscode(obj):
            self._cached_file = obj.co_filename
            return self._cached_file

        raise UnsupportedObjectError(type(obj))

    @property
    def file_info(self) -> Dict[str, Any]:
        """
        Provide detailed information about the source file.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - ``path``: Absolute file path
            - ``exists``: Whether the file exists on disk
            - ``size_bytes``: File size in bytes
            - ``last_modified``: Last modification timestamp
            - ``extension``: File extension

        Examples
        --------
        >>> parser = SourceParser(SourceParser)
        >>> info = parser.file_info
        >>> info['exists']
        True
        >>> 'path' in info
        True
        """
        try:
            path = self.file_path
            stat = path.stat() if path.exists() else None
            return {
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": stat.st_size if stat else None,
                "last_modified": (
                    datetime.fromtimestamp(stat.st_mtime) if stat else None
                ),
                "extension": path.suffix,
            }
        except Exception:
            return {
                "path": None,
                "exists": False,
                "size_bytes": None,
                "last_modified": None,
                "extension": None,
            }

    @property
    def read(self) -> Union[str, bytes]:
        """
        Load and return the full content of the source file.

        This property reads the entire source file associated with the
        object. It handles both text and binary files transparently.

        Returns
        -------
        str or bytes
            - String if the file is readable as text.
            - Bytes if the file requires binary reading (e.g., encoded files).

        Raises
        ------
        FileNotFoundError
            If the source file cannot be accessed.

        Notes
        -----
        Uses chunked reading via ``load`` for memory efficiency with
        large files.

        Examples
        --------
        >>> parser = SourceParser(SourceParser)
        >>> content = parser.read
        >>> isinstance(content, str)
        True
        >>> 'class SourceParser' in content
        True
        """
        try:
            return load(self.file)
        except UnicodeError:
            return load(self.file, mode="rb")

    # ---- AST Analysis Properties ----

    @property
    def _ast(self) -> ast.AST:
        """
        Return the parsed AST of the source code (lazy, cached).

        Returns
        -------
        ast.AST
            The root node of the parsed Abstract Syntax Tree.
        """
        if self._ast_tree is None:
            self._ast_tree = ast.parse(self.source)
        return self._ast_tree

    @property
    def parent(self) -> Optional[str]:
        """
        Determine the parent context of the object.

        Returns the module or class name that contains the object.

        Returns
        -------
        str or None
            - For classes: The containing module name.
            - For functions: The containing module or class name.
            - For modules: The main module name.
            - None if the parent cannot be determined.

        Notes
        -----
        This implementation uses multiple strategies to find the parent,
        falling back gracefully when information is unavailable.

        Examples
        --------
        >>> import os
        >>> parser = SourceParser(os.path.join)
        >>> parser.parent
        'posixpath'  # or 'ntpath' on Windows

        >>> class MyClass:
        ...     def method(self): pass
        ...
        >>> parser = SourceParser(MyClass.method)
        >>> parser.parent
        '__main__'
        """
        obj = self._obj

        try:
            if isclass(obj):
                module_name = getattr(obj, "__module__", None)
                if module_name and module_name in sys.modules:
                    return sys.modules[module_name].__name__
                return module_name

            elif isfunction(obj):
                # Check if it's a method bound to a class
                if hasattr(obj, "__qualname__") and "." in obj.__qualname__:
                    # Extract class name from qualified name
                    parts = obj.__qualname__.split(".")
                    if len(parts) >= 2:
                        return parts[-2]
                # Fall back to module
                module = getmodule(obj)
                return module.__name__ if module else None

            elif ismethod(obj):
                return obj.__self__.__class__.__name__

            elif ismodule(obj):
                return sys.modules.get("__main__", None).__name__

        except (AttributeError, KeyError, IndexError):
            pass

        return None

    @property
    def args(self) -> List[Tuple[str, List[str]]]:
        """
        Extract function and method arguments from the source code.

        Returns a list of tuples where each tuple contains:
        - ``(function_name, [argument_list])``
        - For classes with ``__init__``: ``(class_name, [init_args])``

        The argument list includes:
        - Regular positional arguments
        - Keyword-only arguments
        - ``*args`` var-positional parameter
        - ``**kwargs`` var-keyword parameter

        Returns
        -------
        List[Tuple[str, List[str]]]
            List of ``(name, arguments)`` tuples.

        Notes
        -----
        - ``self`` is included for regular methods; filter it out if needed.
        - Class-level ``__init__`` arguments are extracted for classes.
        - Default values are not included in the output.

        Examples
        --------
        >>> def process(data: list, mode: str = 'fast', *args, **kwargs):
        ...     pass
        ...
        >>> parser = SourceParser(process)
        >>> parser.args
        [('process', ['data', 'mode', 'args', 'kwargs'])]

        >>> class Calculator:
        ...     def __init__(self, precision: int = 2):
        ...         self.precision = precision
        ...
        >>> parser = SourceParser(Calculator)
        >>> parser.args
        [('Calculator', ['self', 'precision'])]
        """
        args_list: List[Tuple[str, List[str]]] = []

        for node in ast.walk(self._ast):
            if isinstance(node, ast.FunctionDef) and node.args:
                subargs: List[str] = []

                # Positional arguments
                for arg in node.args.args:
                    subargs.append(arg.arg)

                # Keyword-only arguments (after *)
                for arg in node.args.kwonlyargs:
                    subargs.append(arg.arg)

                # *args
                if node.args.vararg:
                    subargs.append(node.args.vararg.arg)

                # **kwargs
                if node.args.kwarg:
                    subargs.append(node.args.kwarg.arg)

                args_list.append((node.name, subargs))

            elif isinstance(node, ast.ClassDef):
                init_args: List[str] = []
                for body_item in node.body:
                    if (
                        isinstance(body_item, ast.FunctionDef)
                        and body_item.name == "__init__"
                    ):
                        for arg in body_item.args.args:
                            init_args.append(arg.arg)
                        break

                if init_args:
                    args_list.append((node.name, init_args))

        return args_list

    @property
    def docs(self) -> List[Tuple[str, Optional[str]]]:
        """
        Extract all docstrings from the source code.

        Returns a list of tuples containing:
        - ``(name, docstring)`` for each documented element.
        - Docstrings are extracted using :func:`ast.get_docstring`.

        Returns
        -------
        List[Tuple[str, Optional[str]]]
            List of ``(name, docstring)`` tuples. Docstring is None when
            no documentation is present.

        Examples
        --------
        >>> def documented():
        ...     '''This is a docstring.'''
        ...     pass
        ...
        >>> def undocumented():
        ...     pass
        ...
        >>> parser = SourceParser(documented)
        >>> parser.docs
        [('documented', 'This is a docstring.')]
        """
        docs_list: List[Tuple[str, Optional[str]]] = []

        for node in ast.walk(self._ast):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                name = (
                    node.name
                    if not isinstance(node, ast.Module)
                    else self._name or "__main__"
                )
                docs_list.append((name, ast.get_docstring(node)))

        return docs_list

    def getbody(self, cls_or_func_name: str) -> Optional[str]:
        """
        Extract the full body of a class or function by name.

        Performs case-insensitive matching to find the definition.

        Parameters
        ----------
        cls_or_func_name : str
            Name of the class or function to extract.

        Returns
        -------
        str or None
            The unparsed source code of the class/function if found,
            None otherwise.

        Raises
        ------
        TypeError
            If ``cls_or_func_name`` is not a string.

        Examples
        --------
        >>> class MyClass:
        ...     def my_method(self):
        ...         return 42
        ...
        >>> parser = SourceParser(MyClass)
        >>> body = parser.getbody('my_method')
        >>> 'return 42' in body
        True
        >>> parser.getbody('nonexistent') is None
        True
        """
        if not isinstance(cls_or_func_name, str):
            raise TypeError(
                f"Expected str for class/function name, "
                f"got {type(cls_or_func_name).__name__}"
            )

        target_name = cls_or_func_name.lower()

        for node in ast.walk(self._ast):
            if isinstance(node, ast.FunctionDef) and node.name.lower() == target_name:
                return ast.unparse(node)
            if isinstance(node, ast.ClassDef) and node.name.lower() == target_name:
                return ast.unparse(node)

        return None

    @property
    def decorators(self) -> List[Tuple[str, List[str]]]:
        """
        Extract all decorators applied to classes and functions.

        Returns
        -------
        List[Tuple[str, List[str]]]
            List of ``(decorated_name, [decorator_list])`` tuples.
            Supports both simple decorator names (``@decorator``) and
            attribute chains (``@module.decorator``).

        Examples
        --------
        >>> @staticmethod
        ... @deprecated
        ... def old_func():
        ...     pass
        ...
        >>> parser = SourceParser(old_func)
        >>> parser.decorators
        [('old_func', ['staticmethod', 'deprecated'])]
        """
        decorators_list: List[Tuple[str, List[str]]] = []

        for node in ast.walk(self._ast):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.decorator_list:
                decor_names: List[str] = []
                for decor in node.decorator_list:
                    if isinstance(decor, ast.Name):
                        decor_names.append(decor.id)
                    elif isinstance(decor, ast.Attribute):
                        decor_names.append(ast.unparse(decor))
                    elif isinstance(decor, ast.Call):
                        # For decorators with arguments like @decorator(args)
                        decor_names.append(ast.unparse(decor.func))
                    else:
                        decor_names.append(ast.unparse(decor))
                decorators_list.append((node.name, decor_names))

        return decorators_list

    @property
    def hints(self) -> Dict[str, Dict[str, Optional[str]]]:
        """
        Extract type hints for function arguments and return types.

        Returns
        -------
        Dict[str, Dict[str, Optional[str]]]
            Nested dictionary where:
            - Outer keys are function names.
            - Inner dictionaries map argument names to their type hints
              (as strings) and include a ``'return'`` key for the return
              type hint.
            - Type hints are None when not specified.

        Notes
        -----
        Type hints are extracted from the AST as strings, not resolved
        to actual type objects. This avoids import issues with forward
        references.

        Examples
        --------
        >>> def typed_func(x: int, y: str = "default") -> bool:
        ...     return x > 0
        ...
        >>> parser = SourceParser(typed_func)
        >>> parser.hints
        {'typed_func': {'x': 'int', 'y': 'str', 'return': 'bool'}}
        """
        hints_dict: Dict[str, Dict[str, Optional[str]]] = {}

        for node in ast.walk(self._ast):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_hints: Dict[str, Optional[str]] = {}

                # Argument type hints
                for arg in node.args.args:
                    if arg.annotation:
                        func_hints[arg.arg] = ast.unparse(arg.annotation)
                    else:
                        func_hints[arg.arg] = None

                # Return type hint
                if node.returns:
                    func_hints["return"] = ast.unparse(node.returns)
                else:
                    func_hints["return"] = None

                hints_dict[node.name] = func_hints

        return hints_dict

    @property
    def variables(self) -> List[str]:
        """
        Extract all variable names from assignment statements.

        Includes:
        - Simple assignments (``x = 1``)
        - Type-annotated assignments (``x: int = 1``)
        - Augmented assignments (``x += 1``)
        - Tuple/multiple assignments (``x, y = 1, 2``)

        Returns
        -------
        List[str]
            Deduplicated list of variable names in order of first appearance.

        Notes
        -----
        Variable names are extracted regardless of scope. If you need
        scope-aware extraction, use the AST directly.

        Examples
        --------
        >>> code = '''
        ... x = 10
        ... y: str = "hello"
        ... x += 5
        ... a, b = 1, 2
        ... '''
        >>> parser = SourceParser(some_func)  # containing the code
        >>> sorted(parser.variables)
        ['a', 'b', 'x', 'y']
        """
        variables_set: Set[str] = set()
        variables_list: List[str] = []

        for node in ast.walk(self._ast):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    self._extract_names(target, variables_set, variables_list)

            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    if node.target.id not in variables_set:
                        variables_set.add(node.target.id)
                        variables_list.append(node.target.id)

            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name):
                    if node.target.id not in variables_set:
                        variables_set.add(node.target.id)
                        variables_list.append(node.target.id)

            elif isinstance(node, ast.NamedExpr):  # Walrus operator :=
                if isinstance(node.target, ast.Name):
                    if node.target.id not in variables_set:
                        variables_set.add(node.target.id)
                        variables_list.append(node.target.id)

        return variables_list

    @staticmethod
    def _extract_names(
        node: ast.AST,
        seen: Set[str],
        output: List[str]
    ) -> None:
        """
        Recursively extract variable names from assignment targets.

        Parameters
        ----------
        node : ast.AST
            The assignment target node.
        seen : Set[str]
            Set of already-seen variable names.
        output : List[str]
            Output list to append new names to.
        """
        if isinstance(node, ast.Name):
            if node.id not in seen:
                seen.add(node.id)
                output.append(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for element in node.elts:
                SourceParser._extract_names(element, seen, output)
        elif isinstance(node, ast.Starred):
            SourceParser._extract_names(node.value, seen, output)

    def isproperty(self) -> bool:
        """
        Check if the analyzed object is a property descriptor.

        Returns
        -------
        bool
            True if the object is an instance of ``property``.

        Examples
        --------
        >>> class MyClass:
        ...     @property
        ...     def value(self):
        ...         return 42
        ...
        >>> parser = SourceParser(MyClass.value)
        >>> parser.isproperty()
        True
        """
        return isinstance(self._obj, property)

    def isbuiltin(self) -> bool:
        """
        Check if the analyzed object is a built-in function.

        Returns
        -------
        bool
            True if the object is a built-in function type.

        Examples
        --------
        >>> parser = SourceParser(len)
        >>> parser.isbuiltin()
        True

        >>> def custom(): pass
        >>> parser = SourceParser(custom)
        >>> parser.isbuiltin()
        False
        """
        return isinstance(self._obj, BFT) or isbuiltin(self._obj)

    @property
    def is_async(self) -> bool:
        """
        Check if the object is an async function or coroutine.

        Returns
        -------
        bool
            True for async functions, coroutines, and async generators.

        Examples
        --------
        >>> async def async_func():
        ...     pass
        ...
        >>> parser = SourceParser(async_func)
        >>> parser.is_async
        True
        """
        obj = self._obj
        return (
            iscoroutine(obj) or
            isasyncgen(obj) or
            (isfunction(obj) and obj.__code__.co_flags & 0x80)  # CO_COROUTINE
        )

    @property
    def is_generator(self) -> bool:
        """
        Check if the object is a generator function.

        Returns
        -------
        bool
            True for generator functions and generator objects.

        Examples
        --------
        >>> def gen():
        ...     yield 1
        ...
        >>> parser = SourceParser(gen)
        >>> parser.is_generator
        True
        """
        obj = self._obj
        return (
            isgenerator(obj) or
            (isfunction(obj) and obj.__code__.co_flags & 0x20)  # CO_GENERATOR
        )

    @property
    def is_abstract(self) -> bool:
        """
        Check if the object is an abstract base class.

        Returns
        -------
        bool
            True if the object is an abstract class.

        Examples
        --------
        >>> from abc import ABC, abstractmethod
        >>> class AbstractClass(ABC):
        ...     @abstractmethod
        ...     def method(self): pass
        ...
        >>> parser = SourceParser(AbstractClass)
        >>> parser.is_abstract
        True
        """
        return isclass(self._obj) and isabstract(self._obj)

    @property
    def bytecode(self) -> Optional[str]:
        """
        Disassemble the object's bytecode if available.

        Returns
        -------
        str or None
            Disassembled bytecode as a string, or None for objects
            without bytecode (e.g., modules).

        Notes
        -----
        Uses :func:`dis.dis` to generate the disassembly. The output
        includes line numbers, bytecode offsets, operation names,
        and arguments.

        Examples
        --------
        >>> def simple():
        ...     return 42
        ...
        >>> parser = SourceParser(simple)
        >>> 'LOAD_CONST' in parser.bytecode
        True
        """
        obj = self._obj

        try:
            if isfunction(obj):
                target = obj
            elif ismethod(obj):
                target = obj.__func__
            elif isclass(obj):
                target = obj
            elif iscode(obj):
                target = obj
            else:
                return None

            from io import StringIO
            buf = StringIO()
            dis.dis(target, file=buf)
            return buf.getvalue()
        except Exception:
            return None

    # ---- Structural Properties ----

    @property
    def linespan(self) -> List[Tuple[str, Tuple[int, int]]]:
        """
        Extract line number spans for classes and functions.

        Returns
        -------
        List[Tuple[str, Tuple[int, int]]]
            List of ``(name, (start_line, end_line))`` tuples.

        Examples
        --------
        >>> class Example:  # Line 1
        ...     def method(self):  # Line 2
        ...         pass         # Line 3
        ...
        >>> parser = SourceParser(Example)
        >>> parser.linespan
        [('method', (...)), ('Example', (...))]
        """
        linenos: List[Tuple[str, Tuple[int, int]]] = []

        for node in ast.walk(self._ast):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                linenos.append(
                    (node.name, (node.lineno, node.end_lineno))
                )

        return linenos

    def space(
        self,
        to: Optional[Literal['\t', ' ']] = None,
        spaces: int = 4
    ) -> str:
        """
        Detect or convert indentation style in the source code.

        Parameters
        ----------
        to : str or None, optional
            Target indentation style:
            - ``None``: Detect and return the current indentation type
              (``'tab'`` or ``'space'``).
            - ``'\\t'``: Convert all leading spaces to tabs.
            - ``' '``: Convert all leading tabs to spaces.
        spaces : int, optional
            Number of spaces per indentation level when converting
            between tabs and spaces. Default is 4.

        Returns
        -------
        str
            - If ``to`` is None: ``'tab'`` if tabs are used, ``'space'`` otherwise.
            - If ``to`` is specified: The modified source code after conversion.

        Raises
        ------
        ValueError
            If ``to`` is not None, ``'\\t'``, or ``' '``.

        Examples
        --------
        >>> code = "def func():\\n\\tpass"
        >>> parser = SourceParser(some_func)
        >>> parser.space()  # Detect
        'tab'  # or 'space'

        >>> parser.space(to=' ', spaces=4)  # Convert tabs to spaces
        'def func():\\n    pass'
        """
        if to is None:
            # Detect indentation style
            for line in self.source_lines:
                match = self._INDENTATION_PATTERN.match(line)
                if match:
                    indent = match.group(1)
                    return 'tab' if '\t' in indent else 'space'
            return 'space'  # Default assumption
        else:
            if to == '\t':
                return replace(self.file, ' ' * spaces, '\t')
            elif to == ' ':
                return replace(self.file, '\t', ' ' * spaces)
            else:
                raise ValueError(
                    f"'to' expected None, '\\t', or ' ' (space), got {to!r}"
                )

    @property
    def indentation_level(self) -> int:
        """
        Return the indentation level (in spaces) of the source code.

        Returns
        -------
        int
            Number of spaces per indentation level. Returns 0 if
            indentation cannot be determined.

        Examples
        --------
        >>> def func():
        ...     x = 1  # 4 spaces
        ...
        >>> parser = SourceParser(func)
        >>> parser.indentation_level
        4
        """
        for line in self.source_lines[1:]:  # Skip first line
            match = self._INDENTATION_PATTERN.match(line)
            if match:
                indent = match.group(1)
                if indent and '\t' not in indent:
                    return len(indent)
        return 0

    # ---- Call Analysis ----

    @property
    def calls(self) -> List[str]:
        """
        Extract all function/method calls from the source code.

        Returns full call chains including:
        - Simple calls: ``function()``
        - Method calls: ``obj.method()``
        - Chained calls: ``obj.attr.method()``
        - Attribute calls: ``module.Class()``

        Returns
        -------
        List[str]
            List of function/method call expressions as strings,
            in order of appearance.

        Notes
        -----
        Only calls made within the object's own source are returned,
        not calls made by nested definitions.

        Examples
        --------
        >>> def caller():
        ...     print("hello")
        ...     result = len([1, 2, 3])
        ...     return list.sort()
        ...
        >>> parser = SourceParser(caller)
        >>> parser.calls
        ['print', 'len', 'list.sort']
        """

        def get_full_call_chain(node: ast.Call) -> Optional[str]:
            """
            Recursively build the full dotted name of a call chain.

            Parameters
            ----------
            node : ast.Call
                The call node.

            Returns
            -------
            str or None
                Full dotted name string.
            """
            if isinstance(node.func, ast.Name):
                return node.func.id
            elif isinstance(node.func, ast.Attribute):
                parts: List[str] = []
                curr = node.func
                while isinstance(curr, ast.Attribute):
                    parts.append(curr.attr)
                    curr = curr.value
                if isinstance(curr, ast.Name):
                    parts.append(curr.id)
                elif isinstance(curr, ast.Call):
                    inner = get_full_call_chain(curr)
                    if inner:
                        parts.append(inner)
                parts.reverse()
                return '.'.join(parts)
            elif isinstance(node.func, ast.Subscript):
                # Handle cases like list[i]()
                return ast.unparse(node.func)
            return None

        calls_list: List[str] = []

        for node in ast.walk(self._ast):
            if isinstance(node, ast.Call):
                name = get_full_call_chain(node)
                if name:
                    calls_list.append(name)

        return calls_list

    @property
    def imports(self) -> List[str]:
        """
        Extract all import statements from the source file.

        Uses the external ``imports`` utility to parse import statements.

        Returns
        -------
        List[str]
            List of import statements found in the source file.

        Examples
        --------
        >>> import os
        >>> from typing import List
        >>>
        >>> parser = SourceParser(current_module)
        >>> parser.imports  # doctest: +SKIP
        ['import os', 'from typing import List']
        """
        try:
            return imports(load(self.file))
        except Exception:
            return []

    @property
    def defs(self) -> List[str]:
        """
        Extract all function definitions from the source code.

        Uses the external ``functions`` utility for parsing.

        Returns
        -------
        List[str]
            List of function definition names.

        Notes
        -----
        This property uses an external utility function for parsing,
        which may have different behavior than AST-based extraction.

        Examples
        --------
        >>> def func1(): pass
        >>> def func2(): pass
        >>>
        >>> parser = SourceParser(current_module)
        >>> 'func1' in parser.defs
        True
        """
        return functions(self.source)

    @property
    def classes(self) -> List[str]:
        """
        Extract all class definitions from the source code.

        Uses the external ``classes`` utility for parsing.

        Returns
        -------
        List[str]
            List of class definition names.

        Examples
        --------
        >>> class A: pass
        >>> class B: pass
        >>>
        >>> parser = SourceParser(current_module)
        >>> 'A' in parser.classes
        True
        """
        return classes(self.source)

    @property
    def comprehensions(self) -> List[str]:
        """
        Extract all comprehensions from the source code.

        Detects list, dict, set, and generator comprehensions.

        Returns
        -------
        List[str]
            List of comprehension expressions as strings.

        Examples
        --------
        >>> def func():
        ...     squares = [x**2 for x in range(10)]
        ...     evens = {x for x in range(10) if x % 2 == 0}
        ...
        >>> parser = SourceParser(func)
        >>> len(parser.comprehensions)
        2
        """
        comps: List[str] = []

        for node in ast.walk(self._ast):
            if isinstance(node, ast.comprehension):
                comps.append(ast.unparse(node).strip())

        return comps

    def signature(self) -> Optional[Signature]:
        """
        Return a Signature object for analyzing the object's call signature.

        Returns
        -------
        Signature or None
            A ``Signature`` object wrapping the source code, or None
            if signature extraction fails.

        Examples
        --------
        >>> def func(x: int, y: str = "default") -> bool:
        ...     return True
        ...
        >>> parser = SourceParser(func)
        >>> sig = parser.signature()
        """
        try:
            return Signature(self.source)
        except Exception:
            return None

    # ---- Exception Handling Analysis ----

    @property
    def exceptions(self) -> List[Dict[str, Any]]:
        """
        Extract all try-except blocks and their structure.

        Returns detailed information about each try block.

        Returns
        -------
        List[Dict[str, Any]]
            List of dictionaries with keys:
            - ``try_body``: Source code of the try block
            - ``handlers``: List of exception handler dicts with
              ``type``, ``name``, and ``body``
            - ``else_body``: Source code of the else block (or None)
            - ``finally_body``: Source code of the finally block (or None)
            - ``lineno``: ``(start_line, end_line)`` tuple

        Examples
        --------
        >>> def safe_divide(a, b):
        ...     try:
        ...         return a / b
        ...     except ZeroDivisionError as e:
        ...         return float('inf')
        ...     finally:
        ...         print('done')
        ...
        >>> parser = SourceParser(safe_divide)
        >>> len(parser.exceptions)
        1
        >>> parser.exceptions[0]['handlers'][0]['type']
        'ZeroDivisionError'
        """
        exceptions_list: List[Dict[str, Any]] = []

        for node in ast.walk(self._ast):
            if isinstance(node, ast.Try):
                exc_info: Dict[str, Any] = {
                    "try_body": ast.unparse(node.body) if node.body else "",
                    "handlers": [],
                    "else_body": (
                        ast.unparse(node.orelse) if node.orelse else None
                    ),
                    "finally_body": (
                        ast.unparse(node.finalbody) if node.finalbody else None
                    ),
                    "lineno": (node.lineno, node.end_lineno),
                }

                for handler in node.handlers:
                    handler_info: Dict[str, Optional[str]] = {
                        "type": (
                            ast.unparse(handler.type)
                            if handler.type else None
                        ),
                        "name": handler.name if handler.name else None,
                        "body": ast.unparse(handler.body) if handler.body else "",
                    }
                    exc_info["handlers"].append(handler_info)

                exceptions_list.append(exc_info)

        return exceptions_list

    # ---- Inheritance Analysis ----

    @property
    def inheritance(self) -> List[Tuple[str, Union[str, Tuple[str, ...]]]]:
        """
        Extract class inheritance information from the source code.

        Returns
        -------
        List[Tuple[str, Union[str, Tuple[str, ...]]]]
            List of ``(class_name, bases)`` tuples where ``bases`` is:
            - A single string for single inheritance.
            - A tuple of strings for multiple inheritance.

        Notes
        -----
        This property extracts inheritance from source code AST only,
        not from runtime MRO. For runtime inheritance, use
        :attr:`mro` property.

        Examples
        --------
        >>> class A: pass
        >>> class B(A): pass
        >>> class C(A, B): pass
        >>>
        >>> parser = SourceParser(some_module)
        >>> ('B', 'A') in parser.inheritance
        True
        >>> ('C', ('A', 'B')) in parser.inheritance
        True
        """
        inheritances: List[Tuple[str, Union[str, Tuple[str, ...]]]] = []

        for node in ast.walk(self._ast):
            if isinstance(node, ast.ClassDef) and node.bases:
                bases: List[str] = []
                for base in node.bases:
                    bases.append(ast.unparse(base))
                inheritances.append(
                    (
                        node.name,
                        tuple(bases) if len(bases) > 1 else bases[0]
                    )
                )

        return inheritances

    @property
    def mro(self) -> Optional[List[str]]:
        """
        Return the Method Resolution Order for classes.

        Returns
        -------
        List[str] or None
            List of class names in MRO order, or None if the object
            is not a class.

        Examples
        --------
        >>> class A: pass
        >>> class B(A): pass
        >>> class C(B): pass
        >>>
        >>> parser = SourceParser(C)
        >>> parser.mro
        ['C', 'B', 'A', 'object']
        """
        if isclass(self._obj):
            return [
                cls.__name__
                for cls in self._obj.__mro__
            ]
        return None

    # ---- Lambda Analysis ----

    @property
    def lambdas(self) -> List[Dict[str, Any]]:
        """
        Extract all lambda functions from the source code.

        Returns
        -------
        List[Dict[str, Any]]
            List of dictionaries with:
            - ``Args``: List of argument names
            - ``Body``: The lambda body expression as string
            - ``Lineno``: ``(start, end)`` line number tuple

        Examples
        --------
        >>> def func():
        ...     square = lambda x: x**2
        ...     add = lambda a, b: a + b
        ...
        >>> parser = SourceParser(func)
        >>> len(parser.lambdas)
        2
        >>> parser.lambdas[0]['Args']
        ['x']
        """
        lambdas_list: List[Dict[str, Any]] = []

        for node in ast.walk(self._ast):
            if isinstance(node, ast.Lambda):
                args = [arg.arg for arg in node.args.args]
                body = ast.unparse(node.body)
                lineno = (node.lineno, node.end_lineno)
                lambdas_list.append({
                    "Args": args,
                    "Body": body,
                    "Lineno": lineno,
                })

        return lambdas_list

    # ---- Comment Analysis ----

    @property
    def comments(self) -> List[Tuple[str, Tuple[int, int]]]:
        """
        Extract all comments from the source code.

        Uses tokenizer to parse comments with their positions.

        Returns
        -------
        List[Tuple[str, Tuple[int, int]]]
            List of ``(comment_string, (line, column))`` tuples.

        Examples
        --------
        >>> # This is a comment
        >>> def func():  # Another comment
        ...     pass
        ...
        >>> parser = SourceParser(func)
        >>> len(parser.comments) >= 2
        True
        """
        comments_list: List[Tuple[str, Tuple[int, int]]] = []

        try:
            tokens = tokenize.generate_tokens(
                StringIO(self.source).readline
            )

            for tok_type, tok_string, start, _end, _line in tokens:
                if tok_type == tokenize.COMMENT:
                    comments_list.append((tok_string, start))
        except tokenize.TokenError:
            pass

        return comments_list

    @property
    def docstrings_only(self) -> List[Tuple[int, str]]:
        """
        Extract all standalone string literals that serve as docstrings.

        Returns
        -------
        List[Tuple[int, str]]
            List of ``(line_number, docstring_text)`` tuples.

        Examples
        --------
        >>> def documented():
        ...     '''Module doc.'''
        ...     x = "not a docstring"
        ...
        >>> parser = SourceParser(documented)
        >>> len(parser.docstrings_only)
        1
        """
        docstrings: List[Tuple[int, str]] = []

        for node in ast.walk(self._ast):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                docstring = ast.get_docstring(node)
                if docstring and hasattr(node, 'lineno'):
                    docstrings.append((node.lineno, docstring))

        return docstrings

    # ---- Return Analysis ----

    @property
    def returns(self) -> List[Tuple[str, List[str]]]:
        """
        Extract all return statements from functions.

        Returns
        -------
        List[Tuple[str, List[str]]]
            List of ``(function_name, [return_values])`` tuples.
            Return values are string representations of the returned
            expressions. ``None`` return is shown as ``'None'``.

        Examples
        --------
        >>> def multi_return(x):
        ...     if x > 0:
        ...         return "positive"
        ...     return "non-positive"
        ...
        >>> parser = SourceParser(multi_return)
        >>> parser.returns
        [('multi_return', ['"positive"', '"non-positive"'])]
        """
        returns_list: List[Tuple[str, List[str]]] = []

        for node in ast.walk(self._ast):
            if isinstance(node, ast.FunctionDef):
                subreturns: List[str] = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Return):
                        subreturns.append(
                            ast.unparse(child.value)
                            if child.value else "None"
                        )
                returns_list.append((node.name, subreturns))

        return returns_list

    # ---- Unreachable Code Detection ----

    @property
    def unreachable_code(self) -> List[Tuple[int, str]]:
        """
        Identify unreachable code blocks.

        Detects code that follows ``return``, ``raise``, ``break``,
        or ``continue`` statements and is therefore unreachable
        during execution.

        Returns
        -------
        List[Tuple[int, str]]
            List of ``(line_number, code_snippet)`` tuples for
            unreachable code.

        Notes
        -----
        This is a static analysis and may produce false positives
        (e.g., code after a ``return`` in a try-finally block is
        still reachable).

        Examples
        --------
        >>> def flawed():
        ...     return 42
        ...     print("unreachable")  # This line is unreachable
        ...
        >>> parser = SourceParser(flawed)
        >>> len(parser.unreachable_code)
        1
        """
        dead_code: List[Tuple[int, str]] = []

        def check_block(
            statements: List[ast.stmt],
            source: str
        ) -> None:
            """Recursively check a block of statements for dead code."""
            dead_found = False
            for stmt in statements:
                if dead_found:
                    if hasattr(stmt, 'lineno'):
                        segment = ast.get_source_segment(source, stmt)
                        if segment:
                            dead_code.append((stmt.lineno, segment))
                if isinstance(
                    stmt,
                    (ast.Return, ast.Raise, ast.Break, ast.Continue)
                ):
                    dead_found = True
                # Recursively check nested blocks
                for field, value in ast.iter_fields(stmt):
                    if isinstance(value, list):
                        stmts = [
                            item for item in value
                            if isinstance(item, ast.stmt)
                        ]
                        if stmts:
                            check_block(stmts, source)
                    elif isinstance(value, ast.stmt):
                        check_block([value], source)

        check_block(self._ast.body, self.source)  # type: ignore[arg-type]
        return dead_code

    # ---- Constant Analysis ----

    @property
    def constants(self) -> List[Tuple[str, Any, int]]:
        """
        Extract all constant values from the source code.

        Returns
        -------
        List[Tuple[str, Any, int]]
            List of ``(type_name, value, line_number)`` tuples.
            Categories: 'int', 'float', 'str', 'bool', 'none', 'bytes',
            'tuple', 'frozenset', 'ellipsis', or 'object'.

        Examples
        --------
        >>> def consts():
        ...     x = 42
        ...     y = "hello"
        ...     z = None
        ...     flag = True
        ...
        >>> parser = SourceParser(consts)
        >>> types = {c[0] for c in parser.constants}
        >>> 'int' in types
        True
        """
        constants_list: List[Tuple[str, Any, int]] = []

        for node in ast.walk(self._ast):
            if isinstance(node, ast.Constant):
                val = node.value
                lineno = node.lineno

                if isinstance(val, int):
                    constants_list.append(("int", val, lineno))
                elif isinstance(val, float):
                    constants_list.append(("float", val, lineno))
                elif isinstance(val, str):
                    constants_list.append(("str", val, lineno))
                elif isinstance(val, bool):
                    constants_list.append(("bool", val, lineno))
                elif val is None:
                    constants_list.append(("none", val, lineno))
                elif isinstance(val, bytes):
                    constants_list.append(("bytes", val, lineno))
                elif isinstance(val, tuple):
                    constants_list.append(("tuple", val, lineno))
                elif isinstance(val, frozenset):
                    constants_list.append(("frozenset", val, lineno))
                elif val is ...:
                    constants_list.append(("ellipsis", val, lineno))
                else:
                    constants_list.append(("object", val, lineno))

        return constants_list

    # ---- Code Quality Metrics ----

    @property
    def complexity(self) -> Dict[str, Any]:
        """
        Calculate code complexity metrics.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing:
            - ``lines_total``: Total number of lines.
            - ``lines_code``: Number of non-empty, non-comment lines.
            - ``lines_comments``: Number of comment lines.
            - ``lines_blank``: Number of blank lines.
            - ``functions_count``: Number of function definitions.
            - ``classes_count``: Number of class definitions.

        Examples
        --------
        >>> def simple():
        ...     # A comment
        ...     x = 1
        ...     return x
        ...
        >>> parser = SourceParser(simple)
        >>> parser.complexity['functions_count']
        1
        """
        lines = self.source_lines
        total = len(lines)
        blank = sum(1 for line in lines if not line.strip())
        comments = sum(
            1 for line in lines
            if line.strip().startswith('#')
        )
        code_lines = total - blank - comments

        func_count = sum(
            1 for node in ast.walk(self._ast)
            if isinstance(node, ast.FunctionDef)
        )
        class_count = sum(
            1 for node in ast.walk(self._ast)
            if isinstance(node, ast.ClassDef)
        )

        return {
            "lines_total": total,
            "lines_code": code_lines,
            "lines_comments": comments,
            "lines_blank": blank,
            "functions_count": func_count,
            "classes_count": class_count,
        }

    @property
    def cyclomatic_complexity(self) -> int:
        """
        Calculate McCabe cyclomatic complexity.

        Returns
        -------
        int
            Cyclomatic complexity score. Higher values indicate more
            complex code with more branching paths.

        Notes
        -----
        Complexity is calculated as:
        ``1 + number of decision points``
        Decision points include: if, elif, for, while, and, or,
        except, with, assert, and comprehensions.

        Examples
        --------
        >>> def complex_func(x):
        ...     if x > 0:
        ...         for i in range(x):
        ...             if i % 2 == 0:
        ...                 print(i)
        ...     return x
        ...
        >>> parser = SourceParser(complex_func)
        >>> parser.cyclomatic_complexity
        4
        """
        complexity = 1  # Base complexity

        for node in ast.walk(self._ast):
            if isinstance(node, (
                ast.If, ast.For, ast.While, ast.AsyncFor,
                ast.ExceptHandler, ast.With, ast.AsyncWith,
                ast.Assert, ast.comprehension,
            )):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1

        return complexity

    # ---- Code Transformation ----

    @property
    def minify(self) -> str:
        """
        Minify the source code to reduce its size.

        Requires the optional ``python-minifier`` package.

        Returns
        -------
        str
            Minified source code string.

        Raises
        ------
        RuntimeError
            If ``python-minifier`` is not installed.

        Notes
        -----
        Minification removes comments, docstrings, unnecessary
        whitespace, and shortens variable names where safe.

        Examples
        --------
        >>> parser = SourceParser(some_func)
        >>> minified = parser.minify  # doctest: +SKIP
        """
        if not _HAS_MINIFIER:
            raise RuntimeError(
                "python-minifier is not installed. "
                "Install it with: pip install python-minifier"
            )
        return python_minifier.minify(
            self.source,
            filename=self.file if hasattr(self, 'file') else None,
        )

    def freplace(
        self,
        old: str,
        new: str,
        save: bool = False
    ) -> str:
        """
        Find and replace text in the source file.

        Parameters
        ----------
        old : str
            Text to find and replace.
        new : str
            Replacement text.
        save : bool, optional
            If True, write changes back to the file. Default is False
            (dry-run, returns modified content only).

        Returns
        -------
        str
            The modified file content.

        Raises
        ------
        FileNotFoundError
            If the source file cannot be located.

        Examples
        --------
        >>> parser = SourceParser(some_module)
        >>> modified = parser.freplace('old_name', 'new_name')
        >>> parser.freplace('old_name', 'new_name', save=True)  # Saves to file
        """
        try:
            self.file  # Validate file existence
        except Exception:
            raise FileNotFoundError(
                "SourceParser file not found. Cannot perform replacement."
            ) from None

        text = load(self.file).replace(old, new)
        if save:
            dump(self.file, text)
        return text

    # ---- Memory Analysis ----

    @property
    def memory_usage(self) -> Dict[str, float]:
        """
        Measure memory usage of the analyzed object.

        Uses :func:`sys.getsizeof` for object size and
        :mod:`tracemalloc` for current and peak memory usage.

        Returns
        -------
        Dict[str, float]
            Dictionary with:
            - ``size``: Object size in bytes (from ``sys.getsizeof``).
            - ``current``: Current tracemalloc memory usage.
            - ``peak``: Peak tracemalloc memory usage.

        Notes
        -----
        - ``tracemalloc`` is stopped after this measurement.
        - Memory measurements are approximate and may vary.
        - This property is cached after first access.

        Examples
        --------
        >>> def memory_func():
        ...     data = [1] * 1000
        ...     return data
        ...
        >>> parser = SourceParser(memory_func)
        >>> mem = parser.memory_usage
        >>> mem['size'] > 0
        True
        """
        if self._cached_memory is not None:
            return self._cached_memory

        size = sys.getsizeof(self._obj)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        self._cached_memory = {
            "size": float(size),
            "current": float(current),
            "peak": float(peak),
        }
        return self._cached_memory

    # ---- Object Introspection ----

    def getobjects(
        self,
        filter_func: _AttributeFilter = None,
        include_private: bool = False,
        include_dunder: bool = False,
    ) -> List[Tuple[str, Any]]:
        """
        Retrieve all accessible attributes of the target object.

        This method provides non-intrusive enumeration of attributes
        without invoking properties or descriptors.

        Parameters
        ----------
        filter_func : Callable[[str, Any], bool], optional
            A function that receives ``(name, value)`` pairs and returns
            True to include the attribute. Example::

                lambda n, v: callable(v)  # include only callables

        include_private : bool, optional
            If True, include attributes starting with a single
            underscore (protected). Default is False.
        include_dunder : bool, optional
            If True, include attributes starting and ending with
            double underscores (magic/dunder). Default is False.

        Returns
        -------
        List[Tuple[str, Any]]
            Alphabetically sorted list of ``(name, value)`` tuples
            matching the filter criteria.

        Notes
        -----
        - Uses :func:`inspect.getattr_static` for safe access.
        - ``DynamicClassAttribute`` descriptors are included even if
          not in ``dir()``.
        - Failed attribute access sets value to None.

        Examples
        --------
        >>> parser = SourceParser(str)
        >>> methods = parser.getobjects(lambda n, v: callable(v))
        >>> ('upper', str.upper) in methods
        True
        >>> all_attrs = parser.getobjects(include_private=True)
        """
        obj = self._obj
        names = set(dir(obj))
        results: List[Tuple[str, Any]] = []

        # Add DynamicClassAttributes for classes
        if isclass(obj):
            for base in getattr(obj, '__mro__', ()):
                for k, v in base.__dict__.items():
                    if isinstance(v, DCA):
                        names.add(k)

        for key in sorted(names):
            # Apply visibility filters
            if not include_private and key.startswith('_') and not (
                include_dunder and key.startswith('__') and key.endswith('__')
            ):
                continue
            if not include_dunder and (
                key.startswith('__') and key.endswith('__')
            ):
                continue

            # Get value safely
            try:
                value = getattr_static(obj, key)
            except Exception:
                value = None

            # Apply custom filter
            if filter_func is None or filter_func(key, value):
                results.append((key, value))

        return results

    @property
    def to_callable(self) -> Callable:
        """
        Return the object as a callable.

        Uses external utility to make the object recallable.

        Returns
        -------
        Callable
            A callable version of the object.

        Examples
        --------
        >>> parser = SourceParser(1)
        >>> callable(parser.to_callable)
        True
        """
        return to_callable(self._obj)

    def trackframe(
        self,
        calls: int = 50,
        live: bool = False
    ) -> List[Any]:
        """
        Track the current object's frame references.

        Parameters
        ----------
        calls : int, optional
            Maximum number of references to track. Default is 50.
        live : bool, optional
            If True, print tracking events in real-time. Default is False.

        Returns
        -------
        List
            List of ``FrameRecord`` objects containing tracking information.

        Examples
        --------
        >>> parser = SourceParser(some_func)
        >>> records = parser.trackframe(calls=10)  # doctest: +SKIP
        """
        return track_objects([self._obj], calls=calls, live=live)

    def examples(self, text: bool = False) -> Union[List[str], str]:
        """
        Extract runnable examples from the object's docstring.

        Locates ``>>>`` doctest examples in the docstring. If no examples
        exist, auto-generates a minimal usage example.

        Parameters
        ----------
        text : bool, optional
            If True, return examples as a formatted string.
            If False (default), return as a list of strings.

        Returns
        -------
        List[str] or str
            - List of example strings if ``text=False``.
            - Formatted example block string if ``text=True``.

        Behavior Details
        ----------------
        - Extracts ``>>>`` lines from docstrings.
        - Strips and dedents surrounding whitespace.
        - Auto-generates a fallback example when none exist.
        - Never raises for malformed docstrings.

        Examples
        --------
        >>> def add(a, b):
        ...     '''Add two numbers.
        ...
        ...     >>> add(2, 3)
        ...     5
        ...     '''
        ...     return a + b
        ...
        >>> parser = SourceParser(add)
        >>> parser.examples(text=True)
        '>>> add(2, 3)\\n5'
        """
        return examples(self._obj, text=text)

    # ---- Utility Methods ----

    def clear_cache(self) -> None:
        """
        Clear all cached properties and force re-computation.

        Useful when the source file or object may have changed
        since the parser was initialized.

        Examples
        --------
        >>> parser = SourceParser(some_func)
        >>> # ... source file changes ...
        >>> parser.clear_cache()
        >>> parser.source  # Re-reads source from disk
        """
        self._cached_source = None
        self._cached_file = None
        self._cached_memory = None
        self._ast_tree = None
        self._source_lines = None
        self._cache.clear()
        # Restart tracemalloc for fresh measurements
        tracemalloc.start()

    def diff(self, other: 'SourceParser') -> str:
        """
        Generate a unified diff between this and another source.

        Parameters
        ----------
        other : SourceParser
            Another SourceParser instance to compare against.

        Returns
        -------
        str
            Unified diff string, or empty string if identical.

        Notes
        -----
        Requires access to both source files.

        Examples
        --------
        >>> parser1 = SourceParser(func_v1)
        >>> parser2 = SourceParser(func_v2)
        >>> diff_text = parser1.diff(parser2)  # doctest: +SKIP
        """
        import difflib

        diff_lines = list(difflib.unified_diff(
            self.source_lines,
            other.source_lines,
            fromfile=getattr(self, 'file', 'source1'),
            tofile=getattr(other, 'file', 'source2'),
        ))
        return '\n'.join(diff_lines)

    def search(
        self,
        pattern: str,
        case_sensitive: bool = True,
        regex: bool = False,
    ) -> List[Tuple[int, str]]:
        """
        Search for a pattern in the source code.

        Parameters
        ----------
        pattern : str
            The search pattern (literal or regex).
        case_sensitive : bool, optional
            If False, perform case-insensitive search. Default is True.
        regex : bool, optional
            If True, treat ``pattern`` as a regular expression.
            Default is False.

        Returns
        -------
        List[Tuple[int, str]]
            List of ``(line_number, matched_line)`` tuples.

        Examples
        --------
        >>> def sample():
        ...     x = 42
        ...     y = "hello"
        ...     return x
        ...
        >>> parser = SourceParser(sample)
        >>> parser.search('return')
        [(3, '    return x')]
        """
        results: List[Tuple[int, str]] = []

        if regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                compiled = re.compile(pattern, flags)
            except re.error as e:
                raise ValueError(f"Invalid regex pattern: {e}") from e

            for i, line in enumerate(self.source_lines, 1):
                if compiled.search(line):
                    results.append((i, line))
        else:
            if not case_sensitive:
                pattern_lower = pattern.lower()
                for i, line in enumerate(self.source_lines, 1):
                    if pattern_lower in line.lower():
                        results.append((i, line))
            else:
                for i, line in enumerate(self.source_lines, 1):
                    if pattern in line:
                        results.append((i, line))

        return results

    # ---- Special Methods ----

    def __repr__(self) -> str:
        """
        Return an unambiguous string representation.

        Returns
        -------
        str
            Representation showing class name, object name, and type.
        """
        return (
            f"SourceParser("
            f"name={self._name!r}, "
            f"type={self.type_name!r})"
        )

    def __str__(self) -> str:
        """
        Return a human-readable string representation.

        Returns
        -------
        str
            Multi-line summary of the analyzed object.
        """
        lines = [
            f"SourceParser Analysis for: {self._name or 'unnamed'}",
            f"  Type: {self.type_name}",
            f"  Qualified Name: {self.qualified_name}",
            f"  File: {self.file if hasattr(self, 'file') else 'N/A'}",
            f"  Lines: {self.line_count}",
            f"  Functions: {len(self.defs)}",
            f"  Classes: {len(self.classes)}",
            f"  Variables: {len(self.variables)}",
            f"  Complexity: {self.cyclomatic_complexity}",
        ]
        return '\n'.join(lines)

    def __contains__(self, item: str) -> bool:
        """
        Check if a name is present in the source code definitions.

        Parameters
        ----------
        item : str
            Name to search for in functions and classes.

        Returns
        -------
        bool
            True if the name is found in definitions.

        Examples
        --------
        >>> def my_func(): pass
        >>> parser = SourceParser(my_func)
        >>> 'my_func' in parser
        True
        """
        return item in self.defs or item in self.classes

    def __len__(self) -> int:
        """
        Return the number of source code lines.

        Returns
        -------
        int
            Line count.

        Examples
        --------
        >>> def func():
        ...     x = 1
        ...     return x
        ...
        >>> parser = SourceParser(func)
        >>> len(parser)
        3
        """
        return self.line_count

    def __eq__(self, other: object) -> bool:
        """
        Check equality by comparing source code hashes.

        Parameters
        ----------
        other : object
            Another SourceParser instance.

        Returns
        -------
        bool
            True if both objects have identical source code.

        Examples
        --------
        >>> parser1 = SourceParser(func)
        >>> parser2 = SourceParser(func)
        >>> parser1 == parser2
        True
        """
        if not isinstance(other, SourceParser):
            return NotImplemented
        return self.source_hash == other.source_hash

    def __hash__(self) -> int:
        """
        Return hash based on source code hash.

        Returns
        -------
        int
            Hash value.

        Notes
        -----
        SourceParser instances are hashable, allowing use in sets
        and as dictionary keys.
        """
        return hash(self.source_hash)